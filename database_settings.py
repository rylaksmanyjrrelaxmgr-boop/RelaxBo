#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_settings.py - دوال الإعدادات العامة (v7.4.6)
================================================================================
SettingsMixin:
  - get_setting                  : جلب إعداد من جدول settings
  - get_settings_batch           : جلب عدة إعدادات باستعلام واحد
  - get_start_settings           : إعدادات /start محسّنة
  - set_setting                  : حفظ/تحديث إعداد (PostgreSQL/MySQL/SQLite)
  - get_force_subscribe_channel  : قناة الاشتراك الإجباري
  - get_updates_channel          : قناة التحديثات
  - get_log_channel              : قناة السجلات
  - get_publish_interval         : فترة النشر (بالدقائق)
  - get_auto_backup              : تفعيل النسخ الاحتياطي التلقائي

🆕 v7.4.6 (إصلاحات PostgreSQL):
  ✅ set_setting: يعمل بدون UNIQUE constraint على key
    - PostgreSQL: يُجرّب ON CONFLICT أولاً
    - إذا فشل: يستخدم UPDATE + INSERT (آمن)
    - MySQL: ON DUPLICATE KEY UPDATE
    - SQLite: INSERT OR REPLACE
  ✅ get_settings_batch: PostgreSQL يستخدم $1, $2 بدل ?,?
  ✅ معالجة القيم الفارغة ("" → None)
  ✅ تنظيف الاستيرادات

🆕 v7.4.5:
  ✅ كاش للقيم المفقودة (sentinel __MISSING__)
  ✅ get_settings_batch — استعلام واحد بدل N
  ✅ get_start_settings — مُحسّن لـ /start (~50ms)

📌 يفترض أن الـ Database يوفّر:
  - self.fetchval / self.fetchall / self.execute
  - self.CACHE_AVAILABLE
  - self.settings_cache
================================================================================
"""

import logging
import os
from typing import Optional, Dict, Any, Iterable

logger = logging.getLogger(__name__)

# ✅ علامة خاصة للقيم غير الموجودة في قاعدة البيانات
_MISSING_SENTINEL = "__SETTING_MISSING__"


def _get_db_type() -> str:
    """
    ✅ v7.4.6: كشف نوع قاعدة البيانات من DATABASE_URL.
    يُرجع: "postgres" | "mysql" | "sqlite"
    """
    url = os.getenv("DATABASE_URL", "").strip().lower()
    if "postgres" in url or "postgresql" in url:
        return "postgres"
    if "mysql" in url or "mariadb" in url:
        return "mysql"
    return "sqlite"


class SettingsMixin:
    """Mixin يحتوي كل دوال الإعدادات العامة"""

    # =====================================================================
    # 1) جلب إعداد واحد
    # =====================================================================

    async def get_setting(self, key: str, default: str = None) -> Optional[str]:
        """
        ✅ v7.4.5: يجلب إعداداً واحداً مع كاش.

        - إذا كانت القيمة مفقودة، يخزّن sentinel في الكاش
        - يمنع إعادة الاستعلام عن إعداد غير موجود
        """
        # 1) ابحث في الكاش أولاً
        if self.CACHE_AVAILABLE:
            try:
                cached = await self.settings_cache.get_bot_setting(key)
                if cached == _MISSING_SENTINEL:
                    return default
                if cached is not None:
                    return cached
            except Exception as e:
                logger.debug(f"settings_cache.get_bot_setting failed: {e}")

        # 2) اقرأ من قاعدة البيانات
        try:
            result = await self.fetchval(
                "SELECT value FROM settings WHERE key = ?",
                (key,),
                default=None,
            )
        except Exception as e:
            logger.error(f"❌ get_setting({key}): {e}")
            return default

        # 3) احفظ في الكاش (حتى القيم المفقودة)
        if self.CACHE_AVAILABLE:
            try:
                await self.settings_cache.set_bot_setting(
                    key, result if result is not None else _MISSING_SENTINEL
                )
            except Exception as e:
                logger.debug(f"settings_cache.set_bot_setting failed: {e}")

        return result if result is not None else default

    # =====================================================================
    # 1.b) جلب عدة إعدادات باستعلام واحد
    # =====================================================================

    async def get_settings_batch(
        self,
        keys: Iterable[str],
        defaults: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Optional[str]]:
        """
        ✅ v7.4.6: استعلام واحد بدل N استعلامات.
        يدعم PostgreSQL ($1, $2, ...) بشكل صحيح.
        """
        keys_list = list(keys)
        if not keys_list:
            return {}

        defaults = defaults or {}
        result: Dict[str, Optional[str]] = {}
        missing_keys = []

        # 1) اقرأ من الكاش
        if self.CACHE_AVAILABLE:
            for k in keys_list:
                try:
                    cached = await self.settings_cache.get_bot_setting(k)
                except Exception:
                    cached = None

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

        # 2) استعلام واحد لكل المفاتيح الناقصة
        try:
            db_type = _get_db_type()
            if db_type == "postgres":
                # PostgreSQL: $1, $2, ...
                placeholders = ",".join(
                    [f"${i+1}" for i in range(len(missing_keys))]
                )
            else:
                # SQLite/MySQL: ?, ?, ...
                placeholders = ",".join(["?"] * len(missing_keys))

            query = f"SELECT key, value FROM settings WHERE key IN ({placeholders})"
            rows = await self.fetchall(query, tuple(missing_keys))
            found = {row["key"]: row["value"] for row in rows} if rows else {}
        except Exception as e:
            logger.error(f"❌ get_settings_batch: {e}")
            found = {}

        # 3) املأ النتائج + احفظ في الكاش
        for k in missing_keys:
            val = found.get(k)
            result[k] = val if val is not None else defaults.get(k)
            if self.CACHE_AVAILABLE:
                try:
                    await self.settings_cache.set_bot_setting(
                        k, val if val is not None else _MISSING_SENTINEL
                    )
                except Exception:
                    pass

        return result

    # =====================================================================
    # 2) حفظ/تحديث إعداد
    # =====================================================================

    async def set_setting(self, key: str, value: str) -> bool:
        """
        ✅ v7.4.6: يعمل بدون UNIQUE constraint على key.

        الاستراتيجية:
        1. جرّب UPSERT (سريع إذا UNIQUE موجود)
        2. إذا فشل، استخدم UPDATE + INSERT (آمن دائماً)
        3. إذا فشل كل شيء، سجّل الخطأ

        PostgreSQL: ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        MySQL:      ON DUPLICATE KEY UPDATE value = VALUES(value)
        SQLite:     INSERT OR REPLACE
        """
        db_type = _get_db_type()

        try:
            # ✅ المحاولة 1: UPSERT الأصلي
            if db_type == "postgres":
                query = (
                    "INSERT INTO settings (key, value) VALUES ($1, $2) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
                )
                result = await self.execute(query, (key, value))

            elif db_type == "mysql":
                query = (
                    "INSERT INTO settings (key, value) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE value = VALUES(value)"
                )
                result = await self.execute(query, (key, value))

            else:  # SQLite
                query = (
                    "INSERT OR REPLACE INTO settings (key, value) "
                    "VALUES (?, ?)"
                )
                result = await self.execute(query, (key, value))

            # ✅ إذا نجح UPSERT، نُكمل
            # - PostgreSQL UPSERT: يُرجع 1
            # - MySQL UPSERT: يُرجع 1 أو 2
            # - SQLite: يُرجع 1
            if result is not None and result > 0:
                # إبطال الكاش
                if self.CACHE_AVAILABLE:
                    try:
                        await self.settings_cache.invalidate_bot_settings(key)
                    except Exception as e:
                        logger.debug(f"settings_cache invalidate failed: {e}")
                return True

            # ✅ المحاولة 2: fallback (UPDATE + INSERT)
            logger.debug(
                f"⚠️ set_setting({key}): UPSERT returned {result} — fallback"
            )
            return await self._set_setting_fallback(key, value)

        except Exception as e:
            # ✅ إذا فشل UPSERT (مثلاً: no unique constraint)، نُجرّب fallback
            err_msg = str(e).lower()
            if any(kw in err_msg for kw in (
                "no unique", "there is no unique", "conflict",
                "on conflict", "duplicate", "unique constraint"
            )):
                logger.debug(
                    f"ℹ️ set_setting({key}): UPSERT فشل ({e}) — fallback"
                )
                return await self._set_setting_fallback(key, value)

            # خطأ آخر — نسجّله
            logger.error(f"❌ set_setting({key}): {e}", exc_info=True)
            return False

    async def _set_setting_fallback(self, key: str, value: str) -> bool:
        """
        ✅ v7.4.6: fallback آمن — UPDATE ثم INSERT.

        يعمل بدون UNIQUE constraint (يُستخدم عند فشل UPSERT).
        """
        try:
            # جرّب UPDATE
            updated = await self.execute(
                "UPDATE settings SET value = ? WHERE key = ?",
                (value, key),
            )

            # إذا لم يوجد الصف، أدرِج
            if not updated:
                await self.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )

            # إبطال الكاش
            if self.CACHE_AVAILABLE:
                try:
                    await self.settings_cache.invalidate_bot_settings(key)
                except Exception as e:
                    logger.debug(f"settings_cache invalidate failed: {e}")

            logger.info(f"✅ set_setting({key}) (fallback) نجح")
            return True

        except Exception as e:
            logger.error(
                f"❌ set_setting_fallback({key}): {e}", exc_info=True
            )
            return False

    # =====================================================================
    # 3) قناة الاشتراك الإجباري
    # =====================================================================

    async def get_force_subscribe_channel(self) -> Optional[str]:
        """
        جلب قناة الاشتراك الإجباري.
        تُرجع None إذا لم تكن معينة.
        """
        value = await self.get_setting("force_subscribe_channel")
        if value is None or value == "":
            return None
        return value

    # =====================================================================
    # 4) قناة التحديثات
    # =====================================================================

    async def get_updates_channel(self) -> Optional[str]:
        """جلب معرف قناة التحديثات."""
        value = await self.get_setting("updates_channel")
        if value is None or value == "":
            return None
        return value

    # =====================================================================
    # 5) قناة السجلات
    # =====================================================================

    async def get_log_channel(self) -> Optional[str]:
        """جلب معرف قناة السجلات."""
        value = await self.get_setting("log_channel_id")
        if value is None or value == "":
            return None
        return value

    # =====================================================================
    # 6) فترة النشر (بالدقائق)
    # =====================================================================

    async def get_publish_interval(self) -> int:
        """جلب فترة النشر بالدقائق (افتراضي: 12)."""
        value = await self.get_setting("publish_interval", "12")
        try:
            return max(1, int(value))
        except (ValueError, TypeError):
            return 12

    # =====================================================================
    # 7) تفعيل النسخ الاحتياطي التلقائي
    # =====================================================================

    async def get_auto_backup(self) -> bool:
        """هل النسخ الاحتياطي التلقائي مُفعّل؟"""
        value = await self.get_setting("auto_backup", "1")
        if value is None:
            return True
        return str(value).lower() in ("1", "true", "yes", "on")

    # =====================================================================
    # 8) إعدادات /start محسّنة (استعلام واحد)
    # =====================================================================

    async def get_start_settings(self) -> Dict[str, Any]:
        """
        ✅ v7.4.6: يجلب كل إعدادات /start باستعلام واحد.
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

        # معالجة القيم الفارغة
        def _clean(val):
            if val is None or val == "":
                return None
            return val

        return {
            "force_subscribe_channel": _clean(raw.get("force_subscribe_channel")),
            "updates_channel": _clean(raw.get("updates_channel")),
            "publish_interval": interval,
            "auto_backup": str(raw.get("auto_backup", "1")).lower()
                          in ("1", "true", "yes", "on"),
            "bot_username": _clean(raw.get("bot_username")),
            "support_username": _clean(raw.get("support_username")),
        }