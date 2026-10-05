#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_migrations.py - Migrations extracted from database.py (v1.1.0)
================================================================================
🆕 v1.1.0 (NEW-SECURITY-COLUMNS):
  ✅ NC1: group_security — إضافة 8 أعمدة جديدة لدعم الأزرار الأمنية الجديدة:
      - delete_at_channel          (INTEGER DEFAULT 0)
      - delete_tg_scheme           (INTEGER DEFAULT 1)
      - delete_button_links        (INTEGER DEFAULT 1)
      - delete_emails              (INTEGER DEFAULT 0)
      - delete_protected_any       (INTEGER DEFAULT 0)
      - delete_protected_forward   (INTEGER DEFAULT 0)
      - delete_postbot_pattern     (INTEGER DEFAULT 0)
      - delete_spam_score          (INTEGER DEFAULT 1)

      تُستخدم في:
        • handlers_message.py v7.15.0
        • handlers_callback.py v9.7.5
        • utils.py v7.10.0 (_format_security_text)

  ✅ NC2: توثيق شامل لكل عمود جديد (المصدر + القيمة الافتراضية + السبب).

🎯 الهدف:
    فصل منطق ترحيل Schema من database.py لتقليل حجمه وتنظيم الكود،
    مع الحفاظ على السلوك 100% عبر نمط Mixin.

📦 المحتوى:
    ═══ Module-level constants ═══
      - _ALLOWED_COLUMN_TYPES       : أنواع SQL مسموحة
      - _ALLOWED_COL_KEYWORDS        : كلمات SQL مسموحة
      - _MIGRATIONS_TYPES            : تعريفات الأعمدة المُضافة لكل جدول

    ═══ Module-level helpers ═══
      - _validate_column_def()       : تحقق من صحة تعريف عمود
      - _compute_migrations_signature() : بصمة للـ bootstrap cache
      - _table_exists()              : فحص وجود جدول (يُعاد تصديره من database.py)

    ═══ MigrationsMixin ═══
      - _add_column_safe()           : إضافة عمود مع فحص الوجود
      - _execute_batch_migrations()  : إضافة عدة أعمدة (batch)
      - _column_exists()             : فحص وجود عمود
      - _migrate_delete_penalty_type() : INTEGER→TEXT لـ delete_penalty
      - _ensure_text_hash_column()   : عمود text_hash على posts
      - _ensure_bigint_ids()         : تحويل IDs إلى BIGINT (يستدعي RefactorMixin)
      - _get_existing_columns()      : أعمدة جدول موجودة

================================================================================
🛠️ التكامل مع database.py:

    1) في أعلى database.py، أضف:
        from database_migrations import (
            MigrationsMixin,
            _MIGRATIONS_TYPES,
            _compute_migrations_signature,
            _validate_column_def,
            _table_exists,
            _ALLOWED_COLUMN_TYPES,
            _ALLOWED_COL_KEYWORDS,
        )

    2) في تعريف Database، أضف MigrationsMixin بعد RefactorMixin:
        class Database(
            RefactorMixin,
            MigrationsMixin,              # ← جديد
            ChannelsPostsMixin,
            ...
        ):

    3) احذف من database.py:
        - _ALLOWED_COLUMN_TYPES
        - _ALLOWED_COL_KEYWORDS
        - _validate_column_def
        - _MIGRATIONS_TYPES
        - _compute_migrations_signature
        - _table_exists (module-level function)
        - الطرق: _add_column_safe / _execute_batch_migrations
                / _column_exists / _migrate_delete_penalty_type
                / _ensure_text_hash_column / _ensure_bigint_ids
                / _get_existing_columns

    4) أبقِ في database.py (بلا تغيير):
        - _migrate_schema()             (يستخدم _UNIQUE_CACHE)
        - _fetch_all_columns_map()      (tight coupling)
        - _index_exists()               (يُستخدم في _create_secondary_indexes)

⚠️ ملاحظات:
    - التبعيات: stdlib فقط (os, re, logging, typing)
    - لا circular imports
    - _table_exists يُعاد تصديره من database.py عبر الاستيراد
    - DB_TYPE/USE_POSTGRES/USE_MYSQL تُكتشف محلياً (نفس env vars)
================================================================================
"""

import os
import re
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


# =====================================================================
# 0) كشف نوع قاعدة البيانات (نفس منطق database.py — مستقل)
# =====================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_TYPE = "sqlite"

if DATABASE_URL:
    _URL_LOWER = DATABASE_URL.lower()
    if "postgres" in _URL_LOWER:
        DB_TYPE = "postgres"
    elif "mysql" in _URL_LOWER or "mariadb" in _URL_LOWER:
        DB_TYPE = "mysql"

USE_POSTGRES = (DB_TYPE == "postgres")
USE_MYSQL = (DB_TYPE == "mysql")


# =====================================================================
# 1) ثوابت التحقق من الأعمدة
# =====================================================================

_ALLOWED_COLUMN_TYPES = frozenset({
    "INTEGER", "INT", "BIGINT", "SMALLINT", "TINYINT",
    "TEXT", "VARCHAR", "CHAR", "VARCHAR2",
    "REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC",
    "TIMESTAMP", "DATETIME", "DATE", "TIME",
    "BOOLEAN", "BOOL", "BLOB", "BYTEA",
})

_ALLOWED_COL_KEYWORDS = frozenset({
    "DEFAULT", "NULL", "NOT", "PRIMARY", "KEY", "UNIQUE",
    "CURRENT_TIMESTAMP", "UTC_TIMESTAMP", "NOW",
    "AUTOINCREMENT", "AUTO_INCREMENT",
    "CURRENT_DATE", "CURRENT_TIME", "SYSDATE", "LOCALTIME",
    "LOCALTIMESTAMP", "TRUE", "FALSE",
    "COLLATE", "ON", "UPDATE", "DELETE", "CASCADE",
    "REFERENCES", "CHECK", "CONSTRAINT",
})


def _validate_column_def(col_name: str, col_def: str) -> bool:
    """
    ✅ تحقق صارم من تعريف عمود قبل تنفيذ ALTER TABLE.

    يرفض:
      - أسماء أعمدة لا تُطابق ^[a-zA-Z_][a-zA-Z0-9_]*$
      - تعريفات تحتوي ; أو -- أو /* أو */ أو \x00
      - أنواع SQL غير مسموحة
      - كلمات مفتاحية غير معروفة
    """
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", col_name):
        logger.error(f"❌ اسم عمود غير صالح: {col_name}")
        return False
    if not col_def or not isinstance(col_def, str):
        return False
    for dangerous in (";", "--", "/*", "*/", "\x00"):
        if dangerous in col_def:
            logger.error(f"❌ أحرف خطرة: {col_def}")
            return False
    col_def_stripped = col_def.strip()
    if not col_def_stripped:
        return False
    col_def_upper = col_def_stripped.upper()
    type_match = re.match(r"^([A-Z_][A-Z0-9_]*)", col_def_upper)
    if not type_match:
        return False
    base_type = type_match.group(1)
    if base_type not in _ALLOWED_COLUMN_TYPES:
        logger.error(f"❌ نوع غير مسموح: {base_type}")
        return False
    without_strings = re.sub(r"'[^']*'", "", col_def_upper)
    cleaned = re.sub(r"[(),.\d+\-*/=]", " ", without_strings)
    words = re.findall(r"[A-Z_]+", cleaned)
    for word in words:
        if word in _ALLOWED_COLUMN_TYPES or word in _ALLOWED_COL_KEYWORDS:
            continue
        if re.match(r"^[A-Z_][A-Z0-9_]*$", word):
            continue
        logger.error(f"❌ كلمة غير مسموحة: {word}")
        return False
    return True


# =====================================================================
# 2) Migrations constants
# =====================================================================

_MIGRATIONS_TYPES: Dict[str, List[Tuple[str, str]]] = {
    "group_security": [
        # ═══ مدد العقوبات (v7.7.0) ═══
        ("antiflood_penalty_duration", "INTEGER DEFAULT 3600"),
        ("night_mode_action_duration", "INTEGER DEFAULT 3600"),
        ("warn_penalty_duration", "INTEGER DEFAULT 3600"),
        ("mute_default_duration", "INTEGER DEFAULT 3600"),
        ("ban_default_duration", "INTEGER DEFAULT 0"),
        ("warn_default_duration", "INTEGER DEFAULT 0"),
        ("restrict_default_duration", "INTEGER DEFAULT 1800"),
        ("enable_timed_penalties", "INTEGER DEFAULT 1"),
        ("auto_remove_penalties", "INTEGER DEFAULT 1"),

        # ═══ المخالفات (v7.7.x) ═══
        ("violation_strikes", "INTEGER DEFAULT 3"),
        ("violation_duration", "INTEGER DEFAULT 60"),

        # ═══ أزرار الأمان الأساسية ═══
        ("delete_links", "INTEGER DEFAULT 0"),
        ("mentions", "INTEGER DEFAULT 0"),
        ("delete_videos", "INTEGER DEFAULT 0"),
        ("delete_audio", "INTEGER DEFAULT 0"),
        ("delete_animation", "INTEGER DEFAULT 0"),
        ("delete_service", "INTEGER DEFAULT 0"),
        ("delete_documents", "INTEGER DEFAULT 0"),
        ("delete_stickers", "INTEGER DEFAULT 0"),
        ("delete_forwarded", "INTEGER DEFAULT 0"),
        ("delete_polls", "INTEGER DEFAULT 0"),
        ("delete_games", "INTEGER DEFAULT 0"),
        ("delete_voice", "INTEGER DEFAULT 0"),
        ("delete_video_note", "INTEGER DEFAULT 0"),
        ("delete_photos", "INTEGER DEFAULT 0"),
        ("delete_banned_words", "INTEGER DEFAULT 0"),

        # ═══ الحماية من الفيضان ═══
        ("antiflood_enabled", "INTEGER DEFAULT 0"),
        ("antiflood_messages", "INTEGER DEFAULT 5"),
        ("antiflood_seconds", "INTEGER DEFAULT 10"),
        ("antiflood_penalty", "TEXT DEFAULT 'mute'"),

        # ═══ الوضع الليلي ═══
        ("night_mode_enabled", "INTEGER DEFAULT 0"),
        ("night_mode_start", "TEXT DEFAULT '23:00'"),
        ("night_mode_end", "TEXT DEFAULT '07:00'"),
        ("night_mode_action", "TEXT DEFAULT 'mute'"),

        # ═══ التحذيرات ═══
        ("warn_enabled", "INTEGER DEFAULT 0"),
        ("max_warnings", "INTEGER DEFAULT 3"),
        ("warn_penalty", "TEXT DEFAULT 'mute'"),

        # ═══ الترحيب والوداع ═══
        ("welcome_enabled", "INTEGER DEFAULT 0"),
        ("welcome_text", "TEXT DEFAULT ''"),
        ("goodbye_enabled", "INTEGER DEFAULT 0"),
        ("goodbye_text", "TEXT DEFAULT ''"),

        # ═══ الانضمام ═══
        ("auto_approve_join", "INTEGER DEFAULT 0"),
        ("auto_reject_join", "INTEGER DEFAULT 0"),

        # ═══ الوضع البطيء / الطول / NSFW ═══
        ("slow_mode", "INTEGER DEFAULT 0"),
        ("slow_mode_seconds", "INTEGER DEFAULT 0"),
        ("max_message_length", "INTEGER DEFAULT 0"),
        ("nsfw_enabled", "INTEGER DEFAULT 0"),
        ("nsfw_threshold", "REAL DEFAULT 0.8"),
        ("nsfw_filter", "INTEGER DEFAULT 0"),

        # ═══ العقوبات التلقائية ═══
        ("auto_penalty", "TEXT DEFAULT 'mute'"),
        ("auto_mute_duration", "INTEGER DEFAULT 3600"),
        ("delete_penalty", "TEXT DEFAULT 'none'"),
        ("delete_penalty_duration", "INTEGER DEFAULT 3600"),
        ("delete_penalty_messages", "INTEGER DEFAULT 0"),
        ("violation_penalty_duration", "INTEGER DEFAULT 3600"),
        ("violation_penalty", "TEXT DEFAULT 'none'"),

        # ═══════════════════════════════════════════════════════════
        # 🆕 v1.1.0: أعمدة الأزرار الأمنية الجديدة
        #    تُستخدم في handlers_message v7.15.0 + handlers_callback v9.7.5
        #    + utils v7.10.0 (_format_security_text)
        # ═══════════════════════════════════════════════════════════

        # sec_at_channel — منشن القنوات (@channel)
        # افتراضي 0: FP عالٍ لأن @username شائع في النقاشات الطبيعية
        ("delete_at_channel", "INTEGER DEFAULT 0"),

        # sec_tg_scheme — روابط tg://
        # افتراضي 1: روابط tg:// دعائية بحتة بلا سياق مشروع
        ("delete_tg_scheme", "INTEGER DEFAULT 1"),

        # sec_button_links — أزرار بروابط خارجية
        # افتراضي 1: أزرار بروابط = نمط Spam شائع
        ("delete_button_links", "INTEGER DEFAULT 1"),

        # sec_emails — البريد الإلكتروني
        # افتراضي 0: FP عالٍ — البريد شائع في النقاش الطبيعي
        ("delete_emails", "INTEGER DEFAULT 0"),

        # sec_protected_any — المحتوى المحمي بدون سياق forward
        # افتراضي 0: يمنع رسائل من قنوات شريكة إن فُعّل
        ("delete_protected_any", "INTEGER DEFAULT 0"),

        # delete_protected_forward — المحتوى المحمي مع hint (legacy من v7.13)
        # افتراضي 0: يُفعَّل جنباً إلى جنب مع delete_forwarded عبر sec_forward
        ("delete_protected_forward", "INTEGER DEFAULT 0"),

        # sec_postbot — كاشف نمط PostBot المزعج
        # افتراضي 0: يحتاج ثقة — قد يُنتج FP
        ("delete_postbot_pattern", "INTEGER DEFAULT 0"),

        # delete_spam_score — كاشف spam score (يُحذف تلقائياً)
        # افتراضي 1: ميزة أساسية مُفعّلة افتراضياً
        ("delete_spam_score", "INTEGER DEFAULT 1"),
    ],
    "users": [
        ("active_channel", "INTEGER DEFAULT NULL")
    ],
    "bot_groups": [
        ("log_channel_id", "BIGINT DEFAULT NULL"),
    ],
    "auto_replies": [
        ("usage_count", "INTEGER DEFAULT 0")
    ],
    "anonymous_admins": [("user_id", "BIGINT")],
    "posts": [
        ("text_hash", "TEXT DEFAULT ''"),
        ("published_at", "TIMESTAMP"),
        ("fail_count", "INTEGER DEFAULT 0"),
    ],
    "user_reminder_settings": [
        ("subscription_reminder", "INTEGER DEFAULT 1"),
        ("daily_stats_reminder", "INTEGER DEFAULT 0"),
        ("weekly_report", "INTEGER DEFAULT 1"),
        ("reminder_days_before", "INTEGER DEFAULT 3"),
        ("last_daily_sent", "TIMESTAMP"),
        ("last_weekly_sent", "TIMESTAMP"),
        ("last_subscription_sent", "TIMESTAMP"),
        ("last_reminder_sent", "TIMESTAMP"),
        ("notification_lang", "TEXT DEFAULT 'ar'"),
    ],
    "user_translation": [
        ("lang", "TEXT DEFAULT 'off'")
    ],
}


def _compute_migrations_signature() -> Dict[str, List[str]]:
    """
    🔏 بصمة للـ migrations تُستخدم في _compute_bootstrap_hash.
    تغيير أي تعريف عمود يُغيّر البصمة → يُعيد _migrate_schema.
    """
    return {
        table: [f"{col}:{typ}" for col, typ in cols]
        for table, cols in _MIGRATIONS_TYPES.items()
    }


# =====================================================================
# 3) Module-level helper: _table_exists
# =====================================================================

async def _table_exists(conn, table: str) -> bool:
    """
    ✅ فحص وجود جدول في قاعدة البيانات (PG/MySQL/SQLite).

    يُعاد تصديره من database.py — بعض الدوال في database.py
    (_get_unique_columns_impl, _index_exists, إلخ) تستخدمه.
    """
    try:
        if USE_POSTGRES:
            row = await conn.fetchval(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = $1 AND table_schema = current_schema()",
                table,
            )
            return row is not None
        elif USE_MYSQL:
            cursor = await conn.cursor()
            try:
                await cursor.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() "
                    "AND table_name = %s",
                    (table,),
                )
                row = await cursor.fetchone()
                return row is not None
            finally:
                await cursor.close()
        else:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name=?", (table,),
            )
            try:
                row = await cursor.fetchone()
                return row is not None
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
    except Exception:
        return False


# =====================================================================
# 4) MigrationsMixin
# =====================================================================

class MigrationsMixin:
    """
    🧩 Mixin يستخرج منطق الترحيل من Database.

    يجب أن يُدمج بعد RefactorMixin:
        class Database(RefactorMixin, MigrationsMixin, ...):
            ...

    يفترض أن الفئة الأم تُوفّر:
      Attributes:
        • _group_security_columns_cache
        • BIGINT_COLUMNS
      Methods (تُستدعى عبر self):
        • _index_exists()
        • _ensure_bigint_pg() / _ensure_bigint_mysql()  ← من RefactorMixin
    """

    # ═════════════════════════════════════════════════════════════════
    # 4.1) إضافة الأعمدة
    # ═════════════════════════════════════════════════════════════════

    async def _add_column_safe(
        self, conn, table, col_name, col_def
    ):
        """
        ➕ إضافة عمود واحد بأمان (يفحص الوجود أولاً).

        - رفض الأسماء/التعريفات غير الصالحة
        - MySQL: تحويل TEXT DEFAULT → VARCHAR(255) DEFAULT
        - تنظيف الكاش (`_group_security_columns_cache`) لو الجدول
          group_security
        """
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table) or \
           not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", col_name):
            return
        if not _validate_column_def(col_name, col_def):
            logger.error(
                f"❌ _add_column_safe: col_def غير صالح لـ "
                f"{table}.{col_name}: {col_def}"
            )
            return
        if USE_MYSQL and "TEXT DEFAULT" in col_def.upper():
            col_def = re.sub(
                r"\bTEXT\s+DEFAULT\b", "VARCHAR(255) DEFAULT",
                col_def, flags=re.IGNORECASE,
            )
        try:
            if USE_POSTGRES:
                exists = await conn.fetchval(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = $1 AND column_name = $2 "
                    "AND table_schema = current_schema()",
                    table, col_name,
                )
                if not exists:
                    await conn.execute(
                        f'ALTER TABLE "{table}" '
                        f'ADD COLUMN "{col_name}" {col_def}'
                    )
                    if table == "group_security":
                        self._group_security_columns_cache = None
            elif USE_MYSQL:
                cursor = await conn.cursor()
                try:
                    await cursor.execute(
                        f"SHOW COLUMNS FROM `{table}` LIKE %s",
                        (col_name,),
                    )
                    exists = await cursor.fetchone()
                finally:
                    await cursor.close()
                if not exists:
                    await conn.execute(
                        f"ALTER TABLE `{table}` "
                        f"ADD COLUMN `{col_name}` {col_def}"
                    )
                    if table == "group_security":
                        self._group_security_columns_cache = None
            else:
                cursor = await conn.execute(
                    f"PRAGMA table_info({table})"
                )
                try:
                    rows = await cursor.fetchall()
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
                exists = any(row[1] == col_name for row in rows)
                if not exists:
                    await conn.execute(
                        f"ALTER TABLE {table} "
                        f"ADD COLUMN {col_name} {col_def}"
                    )
                    if table == "group_security":
                        self._group_security_columns_cache = None
        except Exception as e:
            err = str(e).lower()
            if "already exists" not in err and "duplicate" not in err:
                logger.warning(f"⚠️ {col_name} في {table}: {e}")

    async def _execute_batch_migrations(
        self, conn, table, missing_columns
    ) -> int:
        """
        📦 إضافة عدة أعمدة في ALTER TABLE واحد (batch).

        - PG: ADD COLUMN IF NOT EXISTS (متعدد)
        - MySQL: ADD COLUMN `x` def, ADD COLUMN `y` def (متعدد)
        - SQLite: حلقة فردية (لا يدعم batch)

        Returns:
            عدد الأعمدة المُضافة فعلياً.
        """
        if not missing_columns:
            return 0
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table):
            return 0
        for col_name, col_def in missing_columns:
            if not _validate_column_def(col_name, col_def):
                return 0
        try:
            if USE_POSTGRES:
                alters = ", ".join([
                    f'ADD COLUMN IF NOT EXISTS "{c}" {t}'
                    for c, t in missing_columns
                ])
                await conn.execute(
                    f'ALTER TABLE "{table}" {alters}'
                )
                return len(missing_columns)
            elif USE_MYSQL:
                safe_cols = []
                for c, t in missing_columns:
                    if "TEXT DEFAULT" in t.upper():
                        t = re.sub(
                            r"\bTEXT\s+DEFAULT\b",
                            "VARCHAR(255) DEFAULT",
                            t, flags=re.IGNORECASE,
                        )
                    safe_cols.append((c, t))
                alters = ", ".join([
                    f"ADD COLUMN `{c}` {t}" for c, t in safe_cols
                ])
                await conn.execute(
                    f"ALTER TABLE `{table}` {alters}"
                )
                return len(safe_cols)
            else:
                added = 0
                for col_name, col_def in missing_columns:
                    try:
                        await conn.execute(
                            f"ALTER TABLE {table} "
                            f"ADD COLUMN {col_name} {col_def}"
                        )
                        added += 1
                    except Exception as e:
                        err = str(e).lower()
                        if "duplicate" in err or "already exists" in err:
                            continue
                return added
        except Exception as e:
            logger.warning(f"⚠️ batch ALTER {table}: {e}")
            added = 0
            for col_name, col_def in missing_columns:
                if not _validate_column_def(col_name, col_def):
                    continue
                try:
                    if USE_POSTGRES:
                        await conn.execute(
                            f'ALTER TABLE "{table}" '
                            f'ADD COLUMN IF NOT EXISTS '
                            f'"{col_name}" {col_def}'
                        )
                    elif USE_MYSQL:
                        safe_def = col_def
                        if "TEXT DEFAULT" in safe_def.upper():
                            safe_def = re.sub(
                                r"\bTEXT\s+DEFAULT\b",
                                "VARCHAR(255) DEFAULT",
                                safe_def, flags=re.IGNORECASE,
                            )
                        await conn.execute(
                            f"ALTER TABLE `{table}` "
                            f"ADD COLUMN `{col_name}` {safe_def}"
                        )
                    else:
                        await conn.execute(
                            f"ALTER TABLE {table} "
                            f"ADD COLUMN {col_name} {col_def}"
                        )
                    added += 1
                except Exception:
                    pass
            return added

    # ═════════════════════════════════════════════════════════════════
    # 4.2) فحص الأعمدة
    # ═════════════════════════════════════════════════════════════════

    async def _column_exists(self, conn, table, column) -> bool:
        """🔍 هل العمود موجود في الجدول؟ (PG/MySQL/SQLite)."""
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table) or \
           not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", column):
            return False
        try:
            if USE_POSTGRES:
                row = await conn.fetchval(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = $1 AND column_name = $2 "
                    "AND table_schema = current_schema()",
                    table, column,
                )
                return row is not None
            elif USE_MYSQL:
                cursor = await conn.cursor()
                try:
                    await cursor.execute(
                        f"SHOW COLUMNS FROM `{table}` LIKE %s",
                        (column,),
                    )
                    row = await cursor.fetchone()
                    return row is not None
                finally:
                    await cursor.close()
            else:
                cursor = await conn.execute(
                    f"PRAGMA table_info({table})"
                )
                try:
                    rows = await cursor.fetchall()
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
                return any(row[1] == column for row in rows)
        except Exception:
            return False

    async def _get_existing_columns(self, conn, table) -> set:
        """
        📋 مجموعة بأسماء كل أعمدة الجدول (فارغة لو الجدول غير موجود).

        ملاحظة: غير مُستخدمة حالياً لكن kept للأمان (كانت موجودة
        في الإصدارات السابقة).
        """
        try:
            if USE_POSTGRES:
                rows = await conn.fetch(
                    "SELECT column_name "
                    "FROM information_schema.columns "
                    "WHERE table_name = $1 "
                    "AND table_schema = current_schema()",
                    table,
                )
                return {row["column_name"] for row in rows}
            elif USE_MYSQL:
                if not await _table_exists(conn, table):
                    return set()
                cursor = await conn.cursor()
                try:
                    await cursor.execute(
                        f"SHOW COLUMNS FROM `{table}`"
                    )
                    rows = await cursor.fetchall()
                    return {row[0] for row in rows}
                finally:
                    await cursor.close()
            else:
                cursor = await conn.execute(
                    f"PRAGMA table_info({table})"
                )
                try:
                    rows = await cursor.fetchall()
                    return {row[1] for row in rows}
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
        except Exception:
            return set()

    # ═════════════════════════════════════════════════════════════════
    # 4.3) ترحيلات خاصة
    # ═════════════════════════════════════════════════════════════════

    async def _migrate_delete_penalty_type(self, conn) -> bool:
        """
        🔧 ترحيل delete_penalty من INTEGER إلى TEXT.

        - SQLite: لا شيء (type affinity يسمح بالمزج)
        - PostgreSQL: ALTER COLUMN TYPE TEXT (مع USING)
        - MySQL: MODIFY COLUMN VARCHAR(20) (مع UPDATE أولاً)
        """
        if DB_TYPE == "sqlite":
            return True

        try:
            if USE_POSTGRES:
                row = await conn.fetchrow(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = 'group_security' "
                    "AND column_name = 'delete_penalty' "
                    "AND table_schema = current_schema()"
                )
                if not row:
                    return False
                current_type = (row["data_type"] or "").lower()
                if current_type in ("text", "character varying", "varchar"):
                    return True

                if current_type != "integer":
                    logger.debug(
                        f"ℹ️ delete_penalty نوعه: {current_type} — "
                        f"لا تغيير"
                    )
                    return False

                try:
                    await conn.execute(
                        "ALTER TABLE group_security "
                        "ALTER COLUMN delete_penalty TYPE TEXT "
                        "USING CASE "
                        "  WHEN delete_penalty = 0 THEN 'none' "
                        "  WHEN delete_penalty IS NULL THEN 'none' "
                        "  ELSE 'mute' "
                        "END"
                    )
                    logger.info(
                        "🔧 v7.7.33: delete_penalty "
                        "INTEGER → TEXT (PostgreSQL)"
                    )
                    return True
                except Exception as alter_e:
                    logger.warning(
                        f"⚠️ ALTER delete_penalty فشل: {alter_e}"
                    )
                    return False

            elif USE_MYSQL:
                cursor = await conn.cursor()
                try:
                    await cursor.execute(
                        "SELECT DATA_TYPE, COLUMN_TYPE "
                        "FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() "
                        "AND TABLE_NAME = 'group_security' "
                        "AND COLUMN_NAME = 'delete_penalty'"
                    )
                    row = await cursor.fetchone()
                    if not row:
                        return False
                    data_type = (row[0] or "").lower()
                    column_type = (row[1] or "").lower()
                    if data_type in ("varchar", "text", "char"):
                        return True

                    await cursor.execute(
                        "UPDATE group_security SET delete_penalty = "
                        "  CASE "
                        "    WHEN delete_penalty = 0 OR "
                        "         delete_penalty IS NULL THEN 'none' "
                        "    ELSE 'mute' "
                        "  END"
                    )
                    await cursor.execute(
                        "ALTER TABLE group_security "
                        "MODIFY COLUMN delete_penalty "
                        "VARCHAR(20) DEFAULT 'none'"
                    )
                    logger.info(
                        "🔧 v7.7.33: delete_penalty "
                        "NUMERIC → VARCHAR(20) (MySQL)"
                    )
                    return True
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass

        except Exception as e:
            logger.warning(
                f"⚠️ _migrate_delete_penalty_type: {e}",
                exc_info=True,
            )
            return False

        return False

    async def _ensure_text_hash_column(self, conn) -> bool:
        """
        🔧 ضمان وجود عمود text_hash على posts + فهرسه.

        - يُضيف العمود لو مفقود (TEXT على PG/SQLite، CHAR(64) على MySQL)
        - يُنشئ فهرس idx_posts_text_hash (CONCURRENTLY على PG)
        """
        try:
            if not await _table_exists(conn, "posts"):
                return False
            column_exists = await self._column_exists(
                conn, "posts", "text_hash"
            )
            if not column_exists:
                try:
                    if USE_POSTGRES:
                        await conn.execute(
                            "ALTER TABLE posts ADD COLUMN "
                            "text_hash TEXT DEFAULT ''"
                        )
                    elif USE_MYSQL:
                        await conn.execute(
                            "ALTER TABLE posts ADD COLUMN "
                            "text_hash CHAR(64) DEFAULT ''"
                        )
                    else:
                        await conn.execute(
                            "ALTER TABLE posts ADD COLUMN "
                            "text_hash TEXT DEFAULT ''"
                        )
                except Exception:
                    return False
            if not await self._index_exists(
                conn, "posts", "idx_posts_text_hash"
            ):
                try:
                    if USE_POSTGRES:
                        try:
                            await conn.execute(
                                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                                "idx_posts_text_hash ON posts(text_hash)"
                            )
                        except Exception:
                            await conn.execute(
                                "CREATE INDEX IF NOT EXISTS "
                                "idx_posts_text_hash ON posts(text_hash)"
                            )
                    else:
                        await conn.execute(
                            "CREATE INDEX IF NOT EXISTS "
                            "idx_posts_text_hash ON posts(text_hash)"
                        )
                except Exception as e:
                    err = str(e).lower()
                    if "duplicate" not in err and \
                       "already exists" not in err:
                        logger.warning(f"⚠️ idx text_hash: {e}")
            return True
        except Exception as e:
            logger.error(f"❌ _ensure_text_hash_column: {e}")
            return False

    async def _ensure_bigint_ids(self, conn) -> int:
        """
        🔧 تحويل الأعمدة الرقمية إلى BIGINT (PG/MySQL).

        يستدعي _ensure_bigint_pg / _ensure_bigint_mysql من RefactorMixin.
        نفس السلوك 100% كما في v7.7.42/43.

        Returns:
            عدد الأعمدة المُحوّلة.
        """
        if DB_TYPE == "sqlite":
            return 0

        if not self.BIGINT_COLUMNS:
            return 0

        converted = 0
        try:
            if USE_POSTGRES:
                converted = await self._ensure_bigint_pg(conn)
            elif USE_MYSQL:
                converted = await self._ensure_bigint_mysql(conn)
        except Exception as e:
            logger.warning(f"⚠️ _ensure_bigint_ids: {e}")

        if converted > 0:
            logger.info(
                f"✅ تحويل {converted} عمود إلى BIGINT"
            )
        return converted


# =====================================================================
# 5) __all__
# =====================================================================

__all__ = [
    "MigrationsMixin",
    "_MIGRATIONS_TYPES",
    "_compute_migrations_signature",
    "_validate_column_def",
    "_table_exists",
    "_ALLOWED_COLUMN_TYPES",
    "_ALLOWED_COL_KEYWORDS",
]