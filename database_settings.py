#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_settings.py - دوال الإعدادات العامة (v7.7.34)
================================================================================
🆕 v7.7.34 (SAFETY-FIXES-AUDIT — 6 إصلاحات فوق v7.7.33):

    🟠 FIX-SET-1 (IMPORTANT): get_settings_batch — توحيد `?` بدل `$N`
        السبب: v7.7.33 كان يبني `$1, $2, ...` يدوياً على PG، بينما
        `_convert_placeholders` في database.py لا يمس `$N` (لا يحوّلها).
        النتيجة: يعمل، لكنه مزدوج مع `_prepare_query` في
        database_groups v7.4.20، وغير متسق مع بقية الاستعلامات.
        الآن: `?` في كل مكان + `_prepare_settings_query()` helper
        يستخدم `_prepare_query` إن وُجد.

    🟠 FIX-SET-2 (IMPORTANT): إبطال cache شامل عبر _invalidate_setting_caches
        السبب: set_setting كان يُبطل settings_cache فقط. القيم
        المخزّنة في internal_cache (من database.py أو handlers_message
        _dev_log_cache) قد تبقى دقيقة+ بعد التحديث.
        الآن: helper موحّد يُبطل:
          • settings_cache.invalidate_bot_settings(key)
          • internal_cache.invalidate(key)
          • internal_cache.invalidate(f"setting_{key}")

    🟠 FIX-SET-3 (IMPORTANT): get_log_channel auto-heal — إبطال شامل
        السبب: v7.7.33 auto-heal كان يُبطل settings_cache فقط.
        handlers_message._dev_log_cache + internal_cache يحتاجان
        إبطالاً أيضاً، وإلا القيمة "الملوثة" قد تُقرأ مجدداً.
        الآن: يستدعي _invalidate_setting_caches +
        handlers_message._invalidate_dev_log_cache (best-effort).

    🟡 FIX-SET-4 (MINOR): _is_valid_channel_ref يرفض cid=0
        السبب: `_is_valid_channel_ref("0")` → True، لكن chat_id=0
        غير صالح في Telegram. `-1` مقبول للتوافق مع بعض الأنظمة.

    🟡 FIX-SET-5 (MINOR): set_log_channel يُبطل cache بعد الحفظ
        السبب: بعد set_log_channel، كان يدع set_setting يُبطل
        settings_cache فقط. الآن: يُبطل كل cache + best-effort
        handlers_message.

    🟡 FIX-SET-6 (MINOR): _MISSING_SENTINEL معزول
        السبب: إذا كُتب _MISSING_SENTINEL في DB (نادر جداً)،
        get_setting كان يُعيده كقيمة صالحة. الآن: يتحقق من
        المساواة ويُعيد default بدلاً منه + log warning.

    ✅ محفوظ من v7.7.33:
        FIX-Y1: set_setting MySQL no-op ناجح
        FIX-Y1-FOLLOWUP: INSERT idempotent في fallback
    ✅ محفوظ من v7.7.32:
        _is_valid_channel_ref شامل
        set_setting validation
        get_log_channel auto-heal
        set_log_channel يقبل int/str
    ✅ محفوظ من v7.7.31:
        ensure_settings_unique_constraint
    ✅ محفوظ من v7.4.5-7.4.8:
        cache, UNIQUE, PG UPSERT, MySQL reserved words
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
# تحقق القيم قبل الحفظ (v7.7.32)
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
    مرجع قناة (سجل / اشتراك إجباري / تحديثات).

    يقبل:
      - فارغ (تعطيل)
      - معرّف رقمي (يبدأ بـ -100 عادةً، أو موجب للتوافق)
      - @username
      - username (بدون @)
      - https://t.me/username
      - http://t.me/username
      - t.me/username
      - telegram.me/username

    🟡 v7.7.34 FIX-SET-4: يرفض cid=0 (غير صالح في Telegram).
    """
    if value is None:
        return True
    v = str(value).strip()
    if not v:
        return True

    # 1) معرّف رقمي (قد يكون سالباً)
    # 🟡 v7.7.34 FIX-SET-4: رفض cid=0
    if v.lstrip('-').isdigit():
        try:
            cid = int(v)
            if cid == 0:
                return False
            # -1 محجوز في بعض الأنظمة (global) — نقبله للتوافق
            return True
        except (ValueError, TypeError):
            return False

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
    يتحقق من صحة القيمة قبل الحفظ.

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
    # 0) helpers داخلية
    # 🟠 v7.7.34 FIX-SET-1: توحيد الاستعلامات عبر _prepare_settings_query
    # 🟠 v7.7.34 FIX-SET-2: إبطال cache شامل
    # =====================================================================

    def _prepare_settings_query(self, query: str) -> str:
        """
        🟠 v7.7.34 FIX-SET-1: يستخدم `_prepare_query` (من
        database_groups v7.4.20) إن وُجد، وإلا يُرجع النص كما هو
        (`execute`/`fetchall` في database.py يحوّلون `?` تلقائياً).

        التوحيد: كل الاستعلامات تستخدم `?`، والتحويل مسؤولية الـ Database.
        """
        try:
            fn = getattr(self, "_prepare_query", None)
            if callable(fn):
                return fn(query)
        except Exception as e:
            logger.debug(f"_prepare_settings_query: {e}")
        return query

    async def _invalidate_setting_caches(self, key: str) -> None:
        """
        🟠 v7.7.34 FIX-SET-2: إبطال cache شامل لمفتاح إعداد.

        المستويات:
          1) settings_cache.invalidate_bot_settings(key)
          2) internal_cache.invalidate(key)
          3) internal_cache.invalidate(f"setting_{key}")
        """
        # 1) settings_cache
        if getattr(self, "CACHE_AVAILABLE", False):
            try:
                cache = getattr(self, "settings_cache", None)
                if cache is not None:
                    await cache.invalidate_bot_settings(key)
            except Exception as e:
                logger.debug(
                    f"_invalidate_setting_caches settings_cache({key}): "
                    f"{e}"
                )

        # 2) internal_cache
        try:
            ic = getattr(self, "internal_cache", None)
            if ic is not None:
                for _k in (key, f"setting_{key}"):
                    try:
                        await ic.invalidate(_k)
                    except Exception:
                        pass
        except Exception:
            pass

    async def _invalidate_dev_log_cache_best_effort(self) -> None:
        """
        🟠 v7.7.34 FIX-SET-3: إبطال handlers_message._dev_log_cache
        (best-effort، لا يفشل إذا handlers_message غير مستورد).
        """
        try:
            import sys as _sys
            for _mod_name in (
                "handlers_message",
                "handlers.handlers_message",
            ):
                _mod = _sys.modules.get(_mod_name)
                if _mod is None:
                    continue
                _inv = getattr(_mod, "_invalidate_dev_log_cache", None)
                if callable(_inv):
                    try:
                        _r = _inv()
                        if hasattr(_r, "__await__"):
                            await _r
                    except Exception as e:
                        logger.debug(
                            f"handlers_message._invalidate_dev_log_cache: "
                            f"{e}"
                        )
                    break
        except Exception as e:
            logger.debug(f"_invalidate_dev_log_cache_best_effort: {e}")

    async def _invalidate_log_channel_caches(self) -> None:
        """
        🟠 v7.7.34 FIX-SET-3: إبطال شامل لكل مستويات cache
        المتعلقة بـ log_channel_id.

        يُستخدم بعد:
          • set_log_channel
          • remove_log_channel
          • get_log_channel auto-heal
        """
        await self._invalidate_setting_caches("log_channel_id")
        # إبطال مرادفات محتملة أخرى
        try:
            ic = getattr(self, "internal_cache", None)
            if ic is not None:
                for _k in (
                    "log_channel",
                    "global_log_channel",
                    "dev_log_channel",
                    "group_log_channel",
                ):
                    try:
                        await ic.invalidate(_k)
                    except Exception:
                        pass
        except Exception:
            pass
        # handlers_message._dev_log_cache
        await self._invalidate_dev_log_cache_best_effort()

    # =====================================================================
    # 1) UNIQUE constraint على settings.key
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
    # 2) جلب إعداد واحد
    # 🟡 v7.7.34 FIX-SET-6: sentinel protection
    # =====================================================================

    async def get_setting(
        self, key: str, default: str = None
    ) -> Optional[str]:
        # 1) cache lookup
        if getattr(self, "CACHE_AVAILABLE", False):
            try:
                cache = getattr(self, "settings_cache", None)
                if cache is not None:
                    cached = await cache.get_bot_setting(key)
                    if cached == _MISSING_SENTINEL:
                        return default
                    if cached is not None:
                        return cached
            except Exception as e:
                logger.debug(
                    f"settings_cache.get_bot_setting failed: {e}"
                )

        # 2) DB query
        try:
            key_col = _q("key")
            value_col = _q("value")
            query = self._prepare_settings_query(
                f"SELECT {value_col} FROM settings "
                f"WHERE {key_col} = ?"
            )
            result = await self.fetchval(query, (key,), default=None)
        except Exception as e:
            logger.error(f"❌ get_setting({key}): {e}")
            return default

        # 🟡 v7.7.34 FIX-SET-6: sentinel protection
        # إذا كُتب _MISSING_SENTINEL في DB (نادر جداً)، لا نُعيده
        # كقيمة صالحة — نُعيد default بدلاً منه.
        if result == _MISSING_SENTINEL:
            logger.warning(
                f"⚠️ v7.7.34: get_setting({key}) — القيمة في DB هي "
                f"sentinel. تُعامل كـ missing."
            )
            result = None

        # 3) cache set
        if getattr(self, "CACHE_AVAILABLE", False):
            try:
                cache = getattr(self, "settings_cache", None)
                if cache is not None:
                    await cache.set_bot_setting(
                        key,
                        result if result is not None
                        else _MISSING_SENTINEL,
                    )
            except Exception as e:
                logger.debug(
                    f"settings_cache.set_bot_setting failed: {e}"
                )

        return result if result is not None else default

    # =====================================================================
    # 2.b) جلب عدة إعدادات
    # 🟠 v7.7.34 FIX-SET-1: توحيد `?` بدل `$N`
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

        # 1) cache lookup
        if getattr(self, "CACHE_AVAILABLE", False):
            cache = getattr(self, "settings_cache", None)
            for k in keys_list:
                try:
                    cached = (
                        await cache.get_bot_setting(k)
                        if cache is not None else None
                    )
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

        # 2) DB query — 🟠 v7.7.34 FIX-SET-1: `?` فقط
        try:
            placeholders = ",".join(["?"] * len(missing_keys))
            key_col = _q("key")
            value_col = _q("value")

            query = self._prepare_settings_query(
                f"SELECT {key_col}, {value_col} FROM settings "
                f"WHERE {key_col} IN ({placeholders})"
            )
            rows = await self.fetchall(query, tuple(missing_keys))

            found = {}
            if rows:
                for row in rows:
                    try:
                        k = row.get("key") if isinstance(row, dict) else None
                        v = row.get("value") if isinstance(row, dict) else None
                        if k is not None:
                            found[str(k)] = v
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"❌ get_settings_batch: {e}")
            found = {}

        # 3) معالجة النتائج + cache set
        cache = getattr(self, "settings_cache", None)
        for k in missing_keys:
            val = found.get(k)
            result[k] = val if val is not None else defaults.get(k)
            if getattr(self, "CACHE_AVAILABLE", False) and cache is not None:
                try:
                    await cache.set_bot_setting(
                        k,
                        val if val is not None else _MISSING_SENTINEL,
                    )
                except Exception:
                    pass

        return result

    # =====================================================================
    # 3) حفظ إعداد مع تحقق + idempotent
    # 🟠 v7.7.34 FIX-SET-2: إبطال cache شامل
    # =====================================================================

    async def set_setting(self, key: str, value: str) -> bool:
        """
        يتحقق من صحة القيمة أولاً، ثم يحفظ بـ UPSERT idempotent.

        🔴 v7.7.33 FIX-Y1: يُقبل rowcount=0 (no-op ناجح على MySQL).
        🟠 v7.7.34 FIX-SET-2: إبطال cache شامل بعد النجاح.
        """
        # تحقق مسبق
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
                query = self._prepare_settings_query(
                    f"INSERT INTO settings ({key_col}, {value_col}) "
                    f"VALUES (?, ?) "
                    f"ON CONFLICT ({key_col}) DO UPDATE "
                    f"SET {value_col} = EXCLUDED.{value_col}"
                )
                result = await self.execute(query, (key, value))

            elif db_type == "mysql":
                query = self._prepare_settings_query(
                    f"INSERT INTO settings ({key_col}, {value_col}) "
                    f"VALUES (?, ?) "
                    f"ON DUPLICATE KEY UPDATE "
                    f"{value_col} = VALUES({value_col})"
                )
                result = await self.execute(query, (key, value))

            else:  # SQLite
                query = self._prepare_settings_query(
                    f"INSERT OR REPLACE INTO settings "
                    f"({key_col}, {value_col}) "
                    f"VALUES (?, ?)"
                )
                result = await self.execute(query, (key, value))

            # 🔴 FIX-Y1 (v7.7.33): MySQL يُعيد rowcount=0 عندما
            # لا تتغيّر القيمة (no-op ناجح). نعتبرها نجاحاً.
            if result is not None and result >= 0:
                # 🟠 v7.7.34 FIX-SET-2: إبطال شامل
                await self._invalidate_setting_caches(key)
                return True

            # لا نصل هنا إلا إذا كان result = None (فشل حقيقي)
            logger.debug(
                f"⚠️ set_setting({key}): UPSERT returned {result} "
                f"— fallback"
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
        """
        fallback آمن — UPDATE ثم INSERT (idempotent).

        🟡 FIX-Y1-FOLLOWUP (v7.7.33): INSERT idempotent حسب المحرك
            لمنع duplicate key error عند no-op.

        ⚠️ لا نستخدم INSERT IGNORE — لتفادي كتم أخطاء حقيقية
            (type mismatch، permission، NOT NULL ...).
        """
        try:
            key_col = _q("key")
            value_col = _q("value")
            db_type = _get_db_type()

            update_query = self._prepare_settings_query(
                f"UPDATE settings SET {value_col} = ? "
                f"WHERE {key_col} = ?"
            )
            updated = await self.execute(update_query, (value, key))

            if not updated:
                if db_type == "mysql":
                    insert_sql = self._prepare_settings_query(
                        f"INSERT INTO settings ({key_col}, {value_col}) "
                        f"VALUES (?, ?) "
                        f"ON DUPLICATE KEY UPDATE "
                        f"{value_col} = VALUES({value_col})"
                    )
                elif db_type == "postgres":
                    insert_sql = self._prepare_settings_query(
                        f"INSERT INTO settings ({key_col}, {value_col}) "
                        f"VALUES (?, ?) "
                        f"ON CONFLICT ({key_col}) DO NOTHING"
                    )
                else:  # SQLite
                    insert_sql = self._prepare_settings_query(
                        f"INSERT OR IGNORE INTO settings "
                        f"({key_col}, {value_col}) VALUES (?, ?)"
                    )
                await self.execute(insert_sql, (key, value))

            # إبطال cache شامل
            await self._invalidate_setting_caches(key)

            logger.info(f"✅ set_setting({key}) (fallback) نجح")
            return True

        except Exception as e:
            logger.error(
                f"❌ set_setting_fallback({key}): {e}", exc_info=True
            )
            return False

    # =====================================================================
    # 4) قناة الاشتراك الإجباري
    # =====================================================================

    async def get_force_subscribe_channel(self) -> Optional[str]:
        value = await self.get_setting("force_subscribe_channel")
        if value is None or value == "":
            return None
        return value

    # =====================================================================
    # 5) قناة التحديثات
    # =====================================================================

    async def get_updates_channel(self) -> Optional[str]:
        value = await self.get_setting("updates_channel")
        if value is None or value == "":
            return None
        return value

    # =====================================================================
    # 6) قناة السجلات
    # 🟠 v7.7.34 FIX-SET-3: auto-heal + إبطال شامل
    # =====================================================================

    async def get_log_channel(self):
        """
        يُعيد:
          - int للقيم الرقمية
          - str لـ @username / username / رابط
          - None إذا فارغ أو غير صالح (مع auto-heal)

        🟠 v7.7.34 FIX-SET-3: auto-heal يُبطل كل cache (بما فيه
        handlers_message._dev_log_cache).
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
                cid = int(value_str)
                if cid == 0:
                    # قيمة غير صالحة — auto-heal
                    await self._auto_heal_invalid_log_channel(
                        value_str, "cid=0")
                    return None
                return cid
            except (TypeError, ValueError):
                pass

        # 2) @username / username / رابط → str
        if _is_valid_channel_ref(value_str):
            return value_str

        # 3) غير صالح → auto-heal
        await self._auto_heal_invalid_log_channel(
            value_str, "invalid_ref")
        return None

    async def _auto_heal_invalid_log_channel(
        self, value_str: str, reason: str,
    ) -> None:
        """
        🟠 v7.7.34 FIX-SET-3: auto-heal شامل لكل cache.
        """
        preview = value_str[:60]
        logger.warning(
            f"⚠️ v7.7.32/34: log_channel_id غير صالح ({reason}) — "
            f"auto-heal | القيمة: {preview!r}"
        )
        try:
            key_col = _q("key")
            value_col = _q("value")
            heal_query = self._prepare_settings_query(
                f"UPDATE settings SET {value_col} = '' "
                f"WHERE {key_col} = 'log_channel_id'"
            )
            await self.execute(heal_query)

            # 🟠 v7.7.34 FIX-SET-3: إبطال شامل
            await self._invalidate_log_channel_caches()

            logger.info(
                "✅ v7.7.34: تم مسح log_channel_id غير الصالح "
                "تلقائياً + إبطال cache"
            )
        except Exception as heal_err:
            logger.debug(f"auto-heal فشل: {heal_err}")

    async def set_log_channel(self, channel_id) -> bool:
        """
        يقبل int أو str.

        - int: -1001234567890
        - str: @username، username، https://t.me/username
        - None أو '': إزالة

        🟠 v7.7.34 FIX-SET-5: يُبطل كل cache بعد الحفظ.
        """
        if channel_id is None:
            return await self.remove_log_channel()

        value = str(channel_id).strip()
        if not value:
            return await self.remove_log_channel()

        result = await self.set_setting("log_channel_id", value)
        if result:
            # 🟠 v7.7.34 FIX-SET-5: إبطال شامل إضافي
            # (set_setting يُبطل عبر _invalidate_setting_caches،
            # لكن _invalidate_log_channel_caches يُبطل مرادفات إضافية)
            try:
                await self._invalidate_log_channel_caches()
            except Exception as e:
                logger.debug(
                    f"set_log_channel invalidate: {e}"
                )
        return result

    async def remove_log_channel(self) -> bool:
        """
        إزالة قناة السجل.

        🔴 v7.7.33 FIX-Y1: يُعيد True حتى لو كانت القيمة فارغة
        مسبقاً (no-op ناجح على MySQL).

        🟠 v7.7.34 FIX-SET-5: يُبطل كل cache بعد الحذف.
        """
        result = await self.set_setting("log_channel_id", "")
        if result:
            try:
                await self._invalidate_log_channel_caches()
            except Exception as e:
                logger.debug(
                    f"remove_log_channel invalidate: {e}"
                )
        return result

    # =====================================================================
    # 7) فترة النشر
    # =====================================================================

    async def get_publish_interval(self) -> int:
        value = await self.get_setting("publish_interval", "12")
        try:
            return max(1, int(value))
        except (ValueError, TypeError):
            return 12

    # =====================================================================
    # 8) النسخ الاحتياطي التلقائي
    # =====================================================================

    async def get_auto_backup(self) -> bool:
        value = await self.get_setting("auto_backup", "1")
        if value is None:
            return True
        return str(value).lower() in ("1", "true", "yes", "on")

    # =====================================================================
    # 9) إعدادات /start
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


__all__ = [
    "SettingsMixin",
    # Validators
    "_is_valid_channel_ref",
    "_is_valid_log_channel",
    "_validate_setting_value",
    "_SETTING_VALIDATORS",
    # Constants
    "_MISSING_SENTINEL",
    "_get_db_type",
    "_q",
    "_TG_USERNAME_RE",
    "_TG_URL_PREFIXES",
]


# ═════════════════════════════════════════════════════════════════════
# LOAD BEACON — v7.7.34
# ═════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "✅ database_settings.py v7.7.34 SAFETY-FIXES-AUDIT loaded | "
        "FIX-SET-1: qmark-unified ✅ | "
        "FIX-SET-2: invalidate-all-levels ✅ | "
        "FIX-SET-3: auto-heal-deep-invalidate ✅ | "
        "FIX-SET-4: reject-cid-0 ✅ | "
        "FIX-SET-5: set/remove-log-channel-invalidate ✅ | "
        "FIX-SET-6: sentinel-db-protection ✅ | "
        "✅ v7.7.33 FIX-Y1 (MySQL no-op) preserved | "
        "✅ v7.7.33 FIX-Y1-FOLLOWUP (idempotent insert) preserved | "
        "✅ v7.7.32 (_is_valid_channel_ref + validation + auto-heal) "
        "preserved | "
        "✅ v7.7.31 (ensure_settings_unique_constraint) preserved | "
        "✅ v7.4.5-7.4.8 (cache, UNIQUE, PG UPSERT, MySQL reserved) "
        "preserved"
    )
except Exception:
    pass