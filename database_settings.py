#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_settings.py - دوال الإعدادات العامة (v7.4.5)
================================================================================
SettingsMixin:
  - get_setting                  : جلب إعداد من جدول settings
  - get_settings_batch           : جلب عدة إعدادات باستعلام واحد 🆕
  - get_start_settings           : إعدادات /start محسّنة 🆕
  - set_setting                  : حفظ/تحديث إعداد
  - get_force_subscribe_channel  : قناة الاشتراك الإجباري
  - get_updates_channel          : قناة التحديثات
  - get_log_channel              : قناة السجلات
  - get_publish_interval         : فترة النشر (بالدقائق)
  - get_auto_backup              : تفعيل النسخ الاحتياطي التلقائي

🆕 v7.4.5:
  ✅ كاش للقيم المفقودة (sentinel __MISSING__) — يمنع إعادة الاستعلام عن إعداد غير موجود
  ✅ get_settings_batch — استعلام واحد بدل N استعلامات
  ✅ get_start_settings — مُحسّن لـ /start (يُقلّل الزمن من ~5s إلى ~50ms)
  ✅ set_setting — فحص فعلي لنتيجة PostgreSQL (يكشف DO NOTHING الصامت)

📌 يفترض أن الـ Database يوفّر:
  - self.fetchval / self.fetchall / self.execute
  - self.CACHE_AVAILABLE
  - self.settings_cache
================================================================================
"""

import logging
from typing import Optional, Dict, Any, Iterable

logger = logging.getLogger(__name__)

# ✅ علامة خاصة للقيم غير الموجودة في قاعدة البيانات
_MISSING_SENTINEL = "__SETTING_MISSING__"


class SettingsMixin:
    """Mixin يحتوي كل دوال الإعدادات العامة"""

    # =====================================================================
    # 1) جلب إعداد واحد
    # =====================================================================

    async def get_setting(self, key: str, default: str = None) -> Optional[str]:
        # 1) ابحث في الكاش أولاً
        if self.CACHE_AVAILABLE:
            cached = await self.settings_cache.get_bot_setting(key)
            if cached == _MISSING_SENTINEL:
                return default
            if cached is not None:
                return cached

        # 2) اقرأ من قاعدة البيانات
        result = await self.fetchval(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
            default=None,
        )

        # 3) احفظ في الكاش (حتى القيم المفقودة)
        if self.CACHE_AVAILABLE:
            await self.settings_cache.set_bot_setting(
                key, result if result is not None else _MISSING_SENTINEL
            )

        return result if result is not None else default

    # =====================================================================
    # 1.b) 🆕 جلب عدة إعدادات باستعلام واحد
    # =====================================================================

    async def get_settings_batch(
        self,
        keys: Iterable[str],
        defaults: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Optional[str]]:
        """
        ✅ v7.4.5: استعلام واحد بدل N استعلامات.
        يُقلّل زمن /start بشكل كبير.
        """
        keys_list = list(keys)
        if not keys_list:
            return {}

        defaults = defaults or {}
        result: Dict[str, Optional[str]] = {}
        missing_keys = []

        # اقرأ من الكاش أولاً
        if self.CACHE_AVAILABLE:
            for k in keys_list:
                cached = await self.settings_cache.get_bot_setting(k)
                if cached == _MISSING_SENTINEL:
                    result[k] = defaults.get(k)
                elif cached is not None:
                    result[k] = cached
                else:
                    missing_keys.append(k)
        else:
            missing_keys = keys_list

        if not missing_keys:
            return result

        # استعلام واحد لكل المفاتيح الناقصة
        placeholders = ",".join(["?"] * len(missing_keys))
        rows = await self.fetchall(
            f"SELECT key, value FROM settings WHERE key IN ({placeholders})",
            tuple(missing_keys),
        )
        found = {row["key"]: row["value"] for row in rows}

        for k in missing_keys:
            val = found.get(k)
            result[k] = val if val is not None else defaults.get(k)
            if self.CACHE_AVAILABLE:
                await self.settings_cache.set_bot_setting(
                    k, val if val is not None else _MISSING_SENTINEL
                )

        return result

    # =====================================================================
    # 2) حفظ/تحديث إعداد
    # =====================================================================

    async def set_setting(self, key: str, value: str) -> bool:
        """
        ✅ v7.4.5: فحص فعلي — إذا فشل INSERT OR REPLACE بصمت (DO NOTHING
        بسبب غياب UNIQUE على key)، نُجري UPDATE ثم INSERT.
        """
        try:
            result = await self.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                (key, value),
            )

            # ✅ على PostgreSQL: إذا كان DO NOTHING بدون UNIQUE، النتيجة 0
            if result is None or result == 0:
                # جرّب UPDATE صريح
                updated = await self.execute(
                    "UPDATE settings SET value = ? WHERE key = ?",
                    (value, key),
                )
                # إذا لم يوجد صف أصلاً، أدرِج
                if not updated:
                    await self.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?)",
                        (key, value),
                    )

            if self.CACHE_AVAILABLE:
                await self.settings_cache.invalidate_bot_settings(key)
            return True
        except Exception as e:
            logger.error(f"❌ set_setting({key}): {e}", exc_info=True)
            return False

    # =====================================================================
    # 3) قناة الاشتراك الإجباري
    # =====================================================================

    async def get_force_subscribe_channel(self) -> Optional[str]:
        return await self.get_setting("force_subscribe_channel")

    # =====================================================================
    # 4) قناة التحديثات
    # =====================================================================

    async def get_updates_channel(self) -> Optional[str]:
        return await self.get_setting("updates_channel")

    # =====================================================================
    # 5) قناة السجلات
    # =====================================================================

    async def get_log_channel(self) -> Optional[str]:
        return await self.get_setting("log_channel_id")

    # =====================================================================
    # 6) فترة النشر (بالدقائق)
    # =====================================================================

    async def get_publish_interval(self) -> int:
        value = await self.get_setting("publish_interval", "12")
        try:
            return max(1, int(value))
        except (ValueError, TypeError):
            return 12

    # =====================================================================
    # 7) تفعيل النسخ الاحتياطي التلقائي
    # =====================================================================

    async def get_auto_backup(self) -> bool:
        value = await self.get_setting("auto_backup", "1")
        return value in ("1", "true", "True", "yes", "on")

    # =====================================================================
    # 8) 🆕 إعدادات /start محسّنة (استعلام واحد)
    # =====================================================================

    async def get_start_settings(self) -> Dict[str, Any]:
        """
        ✅ v7.4.5: يجلب كل إعدادات /start باستعلام واحد.
        بدل 4+ استعلامات متتالية → 1 استعلام فقط.
        """
        keys = [
            "force_subscribe_channel",
            "updates_channel",
            "publish_interval",
            "auto_backup",
            "bot_username",
            "support_username",
        ]
        defaults = {
            "publish_interval": "12",
            "auto_backup": "1",
        }
        raw = await self.get_settings_batch(keys, defaults)

        try:
            interval = max(1, int(raw.get("publish_interval") or 12))
        except (ValueError, TypeError):
            interval = 12

        return {
            "force_subscribe_channel": raw.get("force_subscribe_channel"),
            "updates_channel": raw.get("updates_channel"),
            "publish_interval": interval,
            "auto_backup": str(raw.get("auto_backup", "1")).lower()
                          in ("1", "true", "yes", "on"),
            "bot_username": raw.get("bot_username"),
            "support_username": raw.get("support_username"),
        }
