#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_settings.py - دوال الإعدادات العامة (v7.7.32)
================================================================================
🆕 v7.7.32 (LOG-CHANNEL-HARDENING):
    ✅ _is_valid_channel_ref: يقبل كل الأنواع
       - معرّف رقمي (قد يكون سالباً)
       - @username
       - username (بدون @)
       - روابط: t.me/x, https://t.me/x, telegram.me/x
    ✅ set_setting: يرفض القيم غير الصالحة قبل الحفظ
    ✅ get_log_channel: auto-heal + يقبل رقم/username
    ✅ set_log_channel: يقبل int أو str

🆕 v7.7.31:
    ✅ set_log_channel / remove_log_channel
    ✅ ensure_settings_unique_constraint(conn=None)
    ✅ _get_db_type: @lru_cache

🆕 v7.4.8 (MySQL reserved words)
🆕 v7.4.7 (UNIQUE تلقائي)
🆕 v7.4.6 (PostgreSQL UPSERT)
🆕 v7.4.5 (كاش)
================================================================================
"""

import logging
import os
import re
from functools import lru_cache
from typing import Optional, Dict, Any, Iterable

logger = logging.getLogger(__name__)

_MISSING_SENTINEL = "__SETTING_MISSING__"


# =====================================================================
# دوال مساعدة
# =====================================================================

@lru_cache(maxsize=1)
def _get_db_type() -> str:
    url = os.getenv("DATABASE_URL", "").strip().lower()
    if "postgres" in url or "postgresql" in url:
        return "postgres"
    if "mysql" in url or "mariadb" in url:
        return "mysql"
    return "sqlite"


def _q(col: str) -> str:
    if _get_db_type() == "mysql":
        return f"`{col}`"
    return col


# =====================================================================
# 🆕 v7.7.32: تحقق القيم قبل الحفظ
# =====================================================================

# نمط username في Telegram:
#   - 5-32 حرف
#   - a-z, A-Z, 0-9, _
#   - يبدأ بحرف
_TG_USERNAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{3,31}$')

# البادئات المقبولة لروابط Telegram
_TG_URL_PREFIXES = (
    'https://t.me/',
    'http://t.me/',
    'https://telegram.me/',
    'http://telegram.me/',
    'https://www.t.me/',
    'http://www.t.me/',
    't.me/',
    'telegram.me/',
    'www.t.me/',
)


def _is_valid_channel_ref(value: str) -> bool:
    """
    ✅ v7.7.32: مرجع قناة (سجل / اشتراك إجباري / تحديثات).

    يقبل:
      - فارغ (تعطيل)
      - معرّف رقمي (قد يكون سالباً: -1001234567890)
      - @username
      - username (بدون @)
      - https://t.me/username
      - http://t.me/username
      - t.me/username
      - telegram.me/username
    """
    if value is None:
        return True
    v = str(value).strip()
    if not v:
        return True

    # 1) معرّف رقمي (قد يكون سالباً)
    if v.lstrip('-').isdigit():
        return True

    # 2) @username
    if v.startswith('@'):
        username = v[1:]
        return bool(_TG_USERNAME_RE.match(username))

    # 3) username بدون @
    if _TG_USERNAME_RE.match(v):
        return True

    # 4) روابط Telegram
    lower = v.lower()
    for prefix in _TG_URL_PREFIXES:
        if lower.startswith(prefix):
            username_part = (
                v[len(prefix):].split('/')[0].split('?')[0].split('#')[0]
            )
            if username_part.startswith('@'):
                username_part = username_part[1:]
            # username عادي
            if _TG_USERNAME_RE.match(username_part):
                return True
            # رابط invite: t.me/+abc أو t.me/joinchat/abc
            if username_part.startswith('+'):
                return True
            if username_part.lower() == 'joinchat':
                return True
            return False

    return False


def _is_valid_log_channel(value: str) -> bool:
    """قناة السجل: نفس قواعد `_is_valid_channel_ref`."""
    return _is_valid_channel_ref(value)


# خريطة التحقق
_SETTING_VALIDATORS: Dict[str, tuple] = {
    "log_channel_id": (
        _is_valid_log_channel,
        "معرّف رقمي، @username، username، رابط t.me/... أو فارغ",
    ),
    "force_subscribe_channel": (
        _is_valid_channel_ref,
        "معرّف رقمي، @username، username، رابط t.me/... أو فارغ",
    ),
    "updates_channel": (
        _is_valid_channel_ref,
        "معرّف رقمي، @username، username، رابط t.me/... أو فارغ",
    ),
}


def _validate_setting_value(key: str, value) -> tuple:
    """
    ✅ v7.7.32: يتحقق من صحة القيمة قبل الحفظ.

    Returns:
        (is_valid: bool, reason: str)
    """
    if key not in _SETTING_VALIDATORS:
        return (True, "")

    if value is None:
        return (True, "")

    try:
        value_str = str(value)
    except Exception:
        return (False, "قيمة غير قابلة للتحويل لنص")

    validator, desc = _SETTING_VALIDATORS[key]

    if not validator(value_str):
        return (False, f"يجب أن يكون {desc}")

    return (True, "")


# =====================================================================
# SettingsMixin
# =====================================================================

class SettingsMixin:
    """Mixin يحتوي كل دوال الإعدادات العامة"""

    # =====================================================================
    # 0) UNIQUE constraint على settings.key
    # =====================================================================

    async def ensure_settings_unique_constraint(
        self, conn: Optional[Any] = None
    ) -> bool:
        db_type = _get_db_type()

        if db_type == "sqlite":
            logger.debug("ℹ️ SQLite: PRIMARY KEY على settings.key كافٍ")
            return True

        async def _fv(query: str, params: tuple = (), default=None):
            if conn is not None:
                if params:
                    return await self._fetchval_with_conn(
                        conn, query, *params, default=default
                    )
                return await self._fetchval_with_conn(
                    conn, query, default=default
                )
            return await self.fetchval(query, params, default=default)

        async def _fa(query: str, params: tuple = ()):
            if conn is not None:
                if params:
                    return await self._fetchall_with_conn(
                        conn, query, *params
                    )
                return await self._fetchall_with_conn(conn, query)
            return await self.fetchall(query, params)

        async def _ex(query: str, params: tuple = ()):
            if conn is not None:
                if params:
                    return await self._execute_with_conn(
                        conn, query, *params
                    )
                return await self._execute_with_conn(conn, query)
            return await self.execute(query, params)

        try:
            if db_type == "postgres":
                exists = await _fv(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_constraint c
                        JOIN pg_class t ON t.oid = c.conrelid
                        WHERE t.relname = 'settings'
                          AND c.contype = 'u'
                    )
                    """,
                    default=False,
                )
                if exists:
                    logger.debug("✅ UNIQUE على settings موجود مسبقاً")
                    return True

                constraint_exists = await _fv(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'settings_key_unique'
                    )
                    """,
                    default=False,
                )
                if constraint_exists:
                    logger.debug(
                        "✅ UNIQUE constraint 'settings_key_unique' موجود"
                    )
                    return True

                await _ex(
                    "ALTER TABLE settings "
                    "ADD CONSTRAINT settings_key_unique UNIQUE (key)"
                )
                logger.info("✅ أُضيف UNIQUE constraint على settings.key")
                return True

            elif db_type == "mysql":
                rows = await _fa(
                    "SHOW INDEX FROM `settings` "
                    "WHERE Key_name = 'settings_key_unique'"
                )
                if rows:
                    logger.debug(
                        "✅ UNIQUE KEY 'settings_key_unique' موجود"
                    )
                    return True

                rows = await _fa(
                    "SHOW INDEX FROM `settings` "
                    "WHERE Column_name = 'key' AND Non_unique = 0"
                )
                if rows:
                    logger.debug("✅ UNIQUE على settings.key موجود مسبقاً")
                    return True

                await _ex(
                    "ALTER TABLE `settings` "
                    "ADD UNIQUE KEY settings_key_unique (`key`)"
                )
                logger.info("✅ أُضيف UNIQUE KEY على settings.key")
                return True

            return True

        except Exception as e:
            err_msg = str(e).lower()
            if "already exists" in err_msg or "duplicate" in err_msg:
                logger.debug(
                    f"ℹ️ UNIQUE constraint موجود مسبقاً (سباق): {e}"
                )
                return True

            logger.warning(
                f"⚠️ فشل إضافة UNIQUE على settings.key: {e}"
            )
            return False

    # =====================================================================
    # 1) جلب إعداد واحد
    # =====================================================================

    async def get_setting(
        self, key: str, default: str = None
    ) -> Optional[str]:
        if self.CACHE_AVAILABLE:
            try:
                cached = await self.settings_cache.get_bot_setting(key)
                if cached == _MISSING_SENTINEL:
                    return default
                if cached is not None:
                    return cached
            except Exception as e:
                logger.debug(
                    f"settings_cache.get_bot_setting failed: {e}"
                )

        try:
            key_col = _q("key")
            value_col = _q("value")
            query = (
                f"SELECT {value_col} FROM settings "
                f"WHERE {key_col} = ?"
            )
            result = await self.fetchval(query, (key,), default=None)
        except Exception as e:
            logger.error(f"❌ get_setting({key}): {e}")
            return default

        if self.CACHE_AVAILABLE:
            try:
                await self.settings_cache.set_bot_setting(
                    key,
                    result if result is not None else _MISSING_SENTINEL,
                )
            except Exception as e:
                logger.debug(
                    f"settings_cache.set_bot_setting failed: {e}"
                )

        return result if result is not None else default

    # =====================================================================
    # 1.b) جلب عدة إعدادات
    # =====================================================================

    async def get_settings_batch(
        self,
        keys: Iterable[str],
        defaults: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Optional[str]]:
        keys_list = list(keys)
        if not keys_list:
            return {}

        defaults = defaults or {}
        result: Dict[str, Optional[str]] = {}
        missing_keys = []

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

        try:
            db_type = _get_db_type()
            if db_type == "postgres":
                placeholders = ",".join(
                    [f"${i+1}" for i in range(len(missing_keys))]
                )
            else:
                placeholders = ",".join(["?"] * len(missing_keys))

            key_col = _q("key")
            value_col = _q("value")

            query = (
                f"SELECT {key_col}, {value_col} FROM settings "
                f"WHERE {key_col} IN ({placeholders})"
            )
            rows = await self.fetchall(query, tuple(missing_keys))

            found = (
                {row["key"]: row["value"] for row in rows}
                if rows else {}
            )
        except Exception as e:
            logger.error(f"❌ get_settings_batch: {e}")
            found = {}

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
    # 2) ✅ v7.7.32: حفظ إعداد مع تحقق مسبق
    # =====================================================================

    async def set_setting(self, key: str, value: str) -> bool:
        """
        ✅ v7.7.32: يتحقق من صحة القيمة أولاً.

        يمنع حفظ قيم غير صالحة في:
          - log_channel_id
          - force_subscribe_channel
          - updates_channel
        """
        # 🆕 v7.7.32: تحقق مسبق
        is_valid, reason = _validate_setting_value(key, value)
        if not is_valid:
            preview = str(value)[:60] if value else ""
            logger.warning(
                f"⚠️ v7.7.32: رفض set_setting({key}) — {reason} "
                f"| القيمة: {preview!r}"
            )
            return False

        db_type = _get_db_type()

        try:
            key_col = _q("key")
            value_col = _q("value")

            if db_type == "postgres":
                query = (
                    f"INSERT INTO settings ({key_col}, {value_col}) "
                    f"VALUES ($1, $2) "
                    f"ON CONFLICT ({key_col}) DO UPDATE "
                    f"SET {value_col} = EXCLUDED.{value_col}"
                )
                result = await self.execute(query, (key, value))

            elif db_type == "mysql":
                query = (
                    f"INSERT INTO settings ({key_col}, {value_col}) "
                    f"VALUES (%s, %s) "
                    f"ON DUPLICATE KEY UPDATE "
                    f"{value_col} = VALUES({value_col})"
                )
                result = await self.execute(query, (key, value))

            else:  # SQLite
                query = (
                    f"INSERT OR REPLACE INTO settings "
                    f"({key_col}, {value_col}) "
                    f"VALUES (?, ?)"
                )
                result = await self.execute(query, (key, value))

            if result is not None and result > 0:
                if self.CACHE_AVAILABLE:
                    try:
                        await self.settings_cache.invalidate_bot_settings(
                            key
                        )
                    except Exception as e:
                        logger.debug(
                            f"settings_cache invalidate failed: {e}"
                        )
                return True

            logger.debug(
                f"⚠️ set_setting({key}): UPSERT returned {result} — fallback"
            )
            return await self._set_setting_fallback(key, value)

        except Exception as e:
            err_msg = str(e).lower()
            if any(kw in err_msg for kw in (
                "no unique", "there is no unique", "conflict",
                "on conflict", "duplicate", "unique constraint",
            )):
                logger.debug(
                    f"ℹ️ set_setting({key}): UPSERT فشل ({e}) — fallback"
                )
                return await self._set_setting_fallback(key, value)

            logger.error(f"❌ set_setting({key}): {e}", exc_info=True)
            return False

    async def _set_setting_fallback(self, key: str, value: str) -> bool:
        """fallback آمن — UPDATE ثم INSERT."""
        try:
            key_col = _q("key")
            value_col = _q("value")

            updated = await self.execute(
                f"UPDATE settings SET {value_col} = ? "
                f"WHERE {key_col} = ?",
                (value, key),
            )

            if not updated:
                await self.execute(
                    f"INSERT INTO settings ({key_col}, {value_col}) "
                    f"VALUES (?, ?)",
                    (key, value),
                )

            if self.CACHE_AVAILABLE:
                try:
                    await self.settings_cache.invalidate_bot_settings(key)
                except Exception as e:
                    logger.debug(
                        f"settings_cache invalidate failed: {e}"
                    )

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
        value = await self.get_setting("force_subscribe_channel")
        if value is None or value == "":
            return None
        return value

    # =====================================================================
    # 4) قناة التحديثات
    # =====================================================================

    async def get_updates_channel(self) -> Optional[str]:
        value = await self.get_setting("updates_channel")
        if value is None or value == "":
            return None
        return value

    # =====================================================================
    # 5) ✅ v7.7.32: قناة السجلات (auto-heal + يقبل كل الأنواع)
    # =====================================================================

    async def get_log_channel(self):
        """
        ✅ v7.7.32: يُعيد:
          - int للقيم الرقمية
          - str لـ @username / username / رابط
          - None إذا فارغ

        - إذا كانت القيمة غير صالحة تماماً (نص عشوائي):
          auto-heal → يمسحها ويُعيد None
        """
        value = await self.get_setting("log_channel_id")
        if value is None or value == "":
            return None

        value_str = str(value).strip()
        if not value_str:
            return None

        # 1) رقمي → int
        if value_str.lstrip('-').isdigit():
            try:
                return int(value_str)
            except (TypeError, ValueError):
                pass

        # 2) @username / username / رابط → str
        if _is_valid_channel_ref(value_str):
            return value_str

        # 3) غير صالح → auto-heal
        preview = value_str[:60]
        logger.warning(
            f"⚠️ v7.7.32: log_channel_id غير صالح — auto-heal "
            f"| القيمة: {preview!r}"
        )
        try:
            key_col = _q("key")
            value_col = _q("value")
            await self.execute(
                f"UPDATE settings SET {value_col} = '' "
                f"WHERE {key_col} = 'log_channel_id'"
            )
            if self.CACHE_AVAILABLE:
                try:
                    await self.settings_cache.invalidate_bot_settings(
                        "log_channel_id"
                    )
                except Exception:
                    pass
            logger.info(
                "✅ v7.7.32: تم مسح log_channel_id غير الصالح تلقائياً"
            )
        except Exception as heal_err:
            logger.debug(f"auto-heal فشل: {heal_err}")

        return None

    async def set_log_channel(self, channel_id) -> bool:
        """
        ✅ v7.7.32: يقبل int أو str.

        - int: -1001234567890
        - str: @username، username، https://t.me/username
        - None أو '': إزالة
        """
        if channel_id is None:
            return await self.remove_log_channel()

        value = str(channel_id).strip()
        if not value:
            return await self.remove_log_channel()

        return await self.set_setting("log_channel_id", value)

    async def remove_log_channel(self) -> bool:
        """✅ إزالة قناة السجل."""
        return await self.set_setting("log_channel_id", "")

    # =====================================================================
    # 6) فترة النشر
    # =====================================================================

    async def get_publish_interval(self) -> int:
        value = await self.get_setting("publish_interval", "12")
        try:
            return max(1, int(value))
        except (ValueError, TypeError):
            return 12

    # =====================================================================
    # 7) النسخ الاحتياطي التلقائي
    # =====================================================================

    async def get_auto_backup(self) -> bool:
        value = await self.get_setting("auto_backup", "1")
        if value is None:
            return True
        return str(value).lower() in ("1", "true", "yes", "on")

    # =====================================================================
    # 8) إعدادات /start
    # =====================================================================

    async def get_start_settings(self) -> Dict[str, Any]:
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

        def _clean(val):
            if val is None or val == "":
                return None
            return val

        return {
            "force_subscribe_channel": _clean(
                raw.get("force_subscribe_channel")
            ),
            "updates_channel": _clean(raw.get("updates_channel")),
            "publish_interval": interval,
            "auto_backup": str(raw.get("auto_backup", "1")).lower()
                          in ("1", "true", "yes", "on"),
            "bot_username": _clean(raw.get("bot_username")),
            "support_username": _clean(raw.get("support_username")),
        }