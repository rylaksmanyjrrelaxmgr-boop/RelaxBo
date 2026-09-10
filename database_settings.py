#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_settings.py - دوال الإعدادات العامة (v7.4.4)
================================================================================
SettingsMixin:
  - get_setting                  : جلب إعداد من جدول settings
  - set_setting                  : حفظ/تحديث إعداد
  - get_force_subscribe_channel  : قناة الاشتراك الإجباري
  - get_updates_channel          : قناة التحديثات
  - get_log_channel              : قناة السجلات
  - get_publish_interval         : فترة النشر (بالدقائق)
  - get_auto_backup              : تفعيل النسخ الاحتياطي التلقائي

📌 مطابق 100% للسلوك الأصلي في database.py (بدون أي إضافة أو تعديل)

📌 يفترض أن الـ Database يوفّر:
  - self.fetchval / self.execute
  - self.CACHE_AVAILABLE
  - self.settings_cache
================================================================================
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SettingsMixin:
    """Mixin يحتوي كل دوال الإعدادات العامة"""

    # =====================================================================
    # 1) جلب إعداد
    # =====================================================================

    async def get_setting(self, key: str, default: str = None) -> Optional[str]:
        if self.CACHE_AVAILABLE:
            cached = await self.settings_cache.get_bot_setting(key)
            if cached is not None:
                return cached
        result = await self.fetchval("SELECT value FROM settings WHERE key = ?", (key,), default=default)
        if result and self.CACHE_AVAILABLE:
            await self.settings_cache.set_bot_setting(key, result)
        return result

    # =====================================================================
    # 2) حفظ/تحديث إعداد
    # =====================================================================

    async def set_setting(self, key: str, value: str) -> bool:
        result = await self.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value)
        ) > 0
        if result and self.CACHE_AVAILABLE:
            await self.settings_cache.invalidate_bot_settings(key)
        return result

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