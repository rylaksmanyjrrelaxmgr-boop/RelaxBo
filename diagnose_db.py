#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_db.py — فحص تشخيصي شامل لقاعدة البيانات
================================================================================
يفحص:
  1. نوع DB + الاتصال
  2. قائمة كل الجداول
  3. لكل جدول: الأعمدة، الأنواع، القيم الافتراضية، عدد الصفوف
  4. فحص خاص لـ delete_penalty في group_security
  5. تناقضات _MIGRATIONS_TYPES مع الواقع
  6. وجود كل الفهارس الحرجية
  7. الفهارس القديمة (DEPRECATED) إن كانت ما زالت موجودة
  8. التكامل المرجعي (orphaned rows)
  9. إعدادات البوت الأساسية (settings)
  10. إعدادات العقوبات لمجموعة sample
  11. نسخ احتياطي لقيم group_security

يعمل مع: SQLite / PostgreSQL / MySQL
================================================================================
"""

import asyncio
import os
import sys
import re
import json
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from typing import List, Dict, Tuple, Optional, Any, Set

# =====================================================================
# إعدادات
# =====================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_TYPE = "sqlite"
if DATABASE_URL:
    _L = DATABASE_URL.lower()
    if "postgres" in _L:
        DB_TYPE = "postgres"
    elif "mysql" in _L or "mariadb" in _L:
        DB_TYPE = "mysql"

# =====================================================================
# قوائم مرجعية (من database_tables.py)
# =====================================================================

# الأعمدة المتوقعة (من _MIGRATIONS_TYPES في database.py v7.7.32)
EXPECTED_MIGRATIONS: Dict[str, List[Tuple[str, str]]] = {
    "group_security": [
        ("antiflood_penalty_duration", "INTEGER DEFAULT 3600"),
        ("night_mode_action_duration", "INTEGER DEFAULT 3600"),
        ("warn_penalty_duration", "INTEGER DEFAULT 3600"),
        ("mute_default_duration", "INTEGER DEFAULT 3600"),
        ("ban_default_duration", "INTEGER DEFAULT 0"),
        ("warn_default_duration", "INTEGER DEFAULT 0"),
        ("restrict_default_duration", "INTEGER DEFAULT 1800"),
        ("enable_timed_penalties", "INTEGER DEFAULT 1"),
        ("auto_remove_penalties", "INTEGER DEFAULT 1"),
        ("violation_strikes", "INTEGER DEFAULT 3"),
        ("violation_duration", "INTEGER DEFAULT 60"),
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
        ("antiflood_enabled", "INTEGER DEFAULT 0"),
        ("antiflood_messages", "INTEGER DEFAULT 5"),
        ("antiflood_seconds", "INTEGER DEFAULT 10"),
        ("antiflood_penalty", "TEXT DEFAULT 'mute'"),
        ("night_mode_enabled", "INTEGER DEFAULT 0"),
        ("night_mode_start", "TEXT DEFAULT '23:00'"),
        ("night_mode_end", "TEXT DEFAULT '07:00'"),
        ("night_mode_action", "TEXT DEFAULT 'mute'"),
        ("warn_enabled", "INTEGER DEFAULT 0"),
        ("max_warnings", "INTEGER DEFAULT 3"),
        ("warn_penalty", "TEXT DEFAULT 'mute'"),
        ("welcome_enabled", "INTEGER DEFAULT 0"),
        ("welcome_text", "TEXT DEFAULT ''"),
        ("goodbye_enabled", "INTEGER DEFAULT 0"),
        ("goodbye_text", "TEXT DEFAULT ''"),
        ("auto_approve_join", "INTEGER DEFAULT 0"),
        ("auto_reject_join", "INTEGER DEFAULT 0"),
        ("slow_mode", "INTEGER DEFAULT 0"),
        ("slow_mode_seconds", "INTEGER DEFAULT 0"),
        ("max_message_length", "INTEGER DEFAULT 0"),
        ("nsfw_enabled", "INTEGER DEFAULT 0"),
        ("nsfw_threshold", "REAL DEFAULT 0.8"),
        ("nsfw_filter", "INTEGER DEFAULT 0"),
        ("auto_penalty", "TEXT DEFAULT 'mute'"),
        ("auto_mute_duration", "INTEGER DEFAULT 3600"),
        ("delete_penalty", "INTEGER DEFAULT 0"),   # v7.7.32
        ("delete_penalty_duration", "INTEGER DEFAULT 3600"),
        ("delete_penalty_messages", "INTEGER DEFAULT 0"),
        ("violation_penalty_duration", "INTEGER DEFAULT 3600"),
        ("violation_penalty", "TEXT DEFAULT 'none'"),
    ],
    "users": [("active_channel", "INTEGER DEFAULT NULL")],
    "bot_groups": [("log_channel_id", "BIGINT DEFAULT NULL")],
    "auto_replies": [("usage_count", "INTEGER DEFAULT 0")],
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
    "user_translation": [("lang", "TEXT DEFAULT 'off'")],
}

# الأعمدة "النصية" المتوقع أن تحمل نصوصاً
# (تُستخدم للكشف عن تناقضات النوع)
TEXT_LIKE_COLUMNS = {
    ("group_security", "delete_penalty"),
    ("group_security", "auto_penalty"),
    ("group_security", "night_mode_action"),
    ("group_security", "warn_penalty"),
    ("group_security", "antiflood_penalty"),
    ("group_security", "violation_penalty"),
}

# الفهارس الحرجية (من database_tables.py)
CRITICAL_INDEXES = [
    "idx_bot_groups_log_channel",
    "idx_posts_channel",
    "idx_posts_channel_published",
    "idx_posts_channel_pub_fail_created",
    "idx_posts_channel_pub_at",
    "idx_posts_channel_unpub_fresh_created",
    "idx_penalties_user_chat_status_end",
    "idx_penalties_status_end",
    "idx_penalties_active_id",
    "idx_user_channels_user_banned",
    "idx_subscriptions_user_status_end",
    "idx_schedule_channel_next",
    "idx_banned_words_chat",
    "idx_banned_words_chat_word",
    "idx_auto_replies_keyword_active",
    "idx_auto_replies_active_keyword",
    "idx_user_violations_chat",
    "idx_user_warnings_chat",
    "idx_bot_groups_banned_cover",
]

# الجداول المتوقعة (من database_tables.py)
EXPECTED_TABLES = [
    "schema_version", "users", "user_channels", "posts", "schedule",
    "last_publish", "bot_groups", "chat_locks", "user_groups_link",
    "group_admins", "hidden_owner_groups", "hidden_admins",
    "anonymous_admins", "group_security", "banned_words",
    "auto_replies", "auto_reply_settings", "support_tickets",
    "bot_admins", "settings", "referrals", "referral_rewards",
    "user_reminder_settings", "user_translation", "contests",
    "contest_participants", "contest_winners", "admin_logs",
    "user_warnings", "user_violations", "group_rules",
    "user_messages", "scheduled_posts", "sentiment_history",
    "plans", "subscriptions", "invoices", "payment_logs",
    "user_penalties", "violation_penalties", "gift_codes",
    "user_points", "penalty_archive",
]

# التكامل المرجعي: (child_table, child_col, parent_table, parent_col)
FK_CHECKS = [
    ("posts", "channel_db_id", "user_channels", "id"),
    ("subscriptions", "user_id", "users", "user_id"),
    ("subscriptions", "plan_id", "plans", "id"),
    ("invoices", "user_id", "users", "user_id"),
    ("user_points", "user_id", "users", "user_id"),
]

# =====================================================================
# أدوات مساعدة
# =====================================================================

class C:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"

    @classmethod
    def disable(cls):
        for attr in ("RED", "GREEN", "YELLOW", "BLUE", "CYAN", "BOLD", "DIM", "END"):
            setattr(cls, attr, "")

# كشف دعم الألوان
if not sys.stdout.isatty() or os.getenv("NO_COLOR"):
    C.disable()

def header(title: str):
    print(f"\n{C.BOLD}{C.CYAN}{'═' * 70}{C.END}")
    print(f"{C.BOLD}{C.CYAN}  {title}{C.END}")
    print(f"{C.BOLD}{C.CYAN}{'═' * 70}{C.END}")

def subheader(title: str):
    print(f"\n{C.BOLD}▶ {title}{C.END}")

def ok(msg: str):
    print(f"  {C.GREEN}✅ {msg}{C.END}")

def warn(msg: str):
    print(f"  {C.YELLOW}⚠️  {msg}{C.END}")

def err(msg: str):
    print(f"  {C.RED}❌ {msg}{C.END}")

def info(msg: str):
    print(f"  {C.DIM}ℹ️  {msg}{C.END}")

def kv(key: str, value: Any, indent: int = 2):
    pad = " " * indent
    print(f"{pad}{C.BOLD}{key}:{C.END} {value}")

# =====================================================================
# محرك الاتصال (يُوحّد الـ API بين DBs)
# =====================================================================

class DBEngine:
    """غلاف موحّد للاتصال بقواعد البيانات."""

    def __init__(self):
        self.db_type = DB_TYPE
        self.conn = None
        self._sqlite_conn = None

    async def connect(self):
        if self.db_type == "sqlite":
            import aiosqlite
            db_path = Path("data/relax.db")
            if not db_path.exists():
                raise FileNotFoundError(f"ملف DB غير موجود: {db_path}")
            self._sqlite_conn = await aiosqlite.connect(str(db_path))
            self._sqlite_conn.row_factory = aiosqlite.Row
            return self._sqlite_conn

        elif self.db_type == "postgres":
            import asyncpg
            self.conn = await asyncpg.connect(DATABASE_URL)
            return self.conn

        elif self.db_type == "mysql":
            import asyncmy
            p = urlparse(DATABASE_URL)
            self.conn = await asyncmy.connect(
                host=p.hostname, port=int(p.port or 3306),
                user=p.username or "", password=p.password or "",
                db=(p.path or "/").lstrip("/"), charset="utf8mb4",
            )
            return self.conn

        raise ValueError(f"نوع DB غير مدعوم: {self.db_type}")

    async def close(self):
        try:
            if self.db_type == "sqlite" and self._sqlite_conn:
                await self._sqlite_conn.close()
            elif self.db_type == "postgres" and self.conn:
                await self.conn.close()
            elif self.db_type == "mysql" and self.conn:
                self.conn.close()
        except Exception:
            pass

    async def fetchall(self, sql: str, *params) -> List[Dict]:
        if self.db_type == "sqlite":
            cursor = await self._sqlite_conn.execute(sql, params)
            try:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass

        elif self.db_type == "postgres":
            # حوّل "?" إلى "$1, $2, ..."
            if params:
                new_sql = sql
                for i in range(len(params), 0, -1):
                    new_sql = new_sql.replace("?", f"${i}", 1) if "?" in new_sql else new_sql
                # البديل الأبسط: استبدال متسلسل
                parts = sql.split("?")
                if len(parts) - 1 == len(params):
                    sql2 = parts[0]
                    for i, p in enumerate(parts[1:], 1):
                        sql2 += f"${i}" + p
                    sql = sql2
            rows = await self.conn.fetch(sql, *params)
            return [dict(r) for r in rows]

        elif self.db_type == "mysql":
            cursor = await self.conn.cursor()
            try:
                await cursor.execute(sql, params)
                rows = await cursor.fetchall()
                desc = cursor.description
                if not rows or not desc:
                    return []
                cols = [d[0] for d in desc]
                return [dict(zip(cols, r)) for r in rows]
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass

        return []

    async def fetchone(self, sql: str, *params) -> Optional[Dict]:
        rows = await self.fetchall(sql, *params)
        return rows[0] if rows else None

    async def fetchval(self, sql: str, *params, default=None) -> Any:
        row = await self.fetchone(sql, *params)
        if not row:
            return default
        # خُذ أول قيمة
        return list(row.values())[0] if row else default


# =====================================================================
# 1. فحص الاتصال
# =====================================================================

async def check_connection(db: DBEngine):
    header("1️⃣  فحص الاتصال ونوع قاعدة البيانات")

    kv("نوع DB المكتشف", f"{C.BOLD}{db.db_type.upper()}{C.END}")

    if db.db_type == "sqlite":
        db_path = Path("data/relax.db")
        size_mb = db_path.stat().st_size / (1024 * 1024)
        kv("مسار الملف", f"{db_path} ({size_mb:.2f} MB)")

    else:
        # لا تُظهر كلمة المرور
        safe_url = re.sub(r"://[^@]+@", "://***@", DATABASE_URL)
        kv("DATABASE_URL", safe_url[:80])

    try:
        if db.db_type == "sqlite":
            v = await db.fetchval("SELECT sqlite_version()")
            kv("إصدار SQLite", v)
        elif db.db_type == "postgres":
            v = await db.fetchval("SELECT version()")
            kv("إصدار PostgreSQL", str(v)[:60])
        elif db.db_type == "mysql":
            v = await db.fetchval("SELECT VERSION()")
            kv("إصدار MySQL", v)

        ok("الاتصال ناجح")
    except Exception as e:
        err(f"فشل الاتصال: {e}")
        raise


# =====================================================================
# 2. قائمة الجداول
# =====================================================================

async def get_all_tables(db: DBEngine) -> List[str]:
    if db.db_type == "sqlite":
        rows = await db.fetchall(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
        return [r["name"] for r in rows]

    elif db.db_type == "postgres":
        rows = await db.fetchall(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() "
            "AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
        return [r["table_name"] for r in rows]

    elif db.db_type == "mysql":
        rows = await db.fetchall(
            "SELECT TABLE_NAME AS table_name "
            "FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME"
        )
        return [r["table_name"] for r in rows]

    return []


async def check_tables(db: DBEngine):
    header("2️⃣  الجداول الموجودة")

    tables = await get_all_tables(db)
    kv("عدد الجداول", len(tables))

    missing = [t for t in EXPECTED_TABLES if t not in tables]
    extra = [t for t in tables if t not in EXPECTED_TABLES]

    if missing:
        err(f"جداول مفقودة ({len(missing)}): {', '.join(missing)}")
    else:
        ok("كل الجداول المتوقعة موجودة")

    if extra:
        warn(f"جداول إضافية غير متوقعة ({len(extra)}): {', '.join(extra)}")

    print(f"\n{C.DIM}كل الجداول:{C.END}")
    for t in tables:
        print(f"  • {t}")

    return tables


# =====================================================================
# 3. فحص أعمدة جدول
# =====================================================================

async def get_columns(db: DBEngine, table: str) -> List[Dict]:
    """يُعيد [{name, type, default, nullable, pk}, ...]"""
    if db.db_type == "sqlite":
        rows = await db.fetchall(f"PRAGMA table_info({table})")
        return [
            {
                "name": r["name"],
                "type": (r.get("type") or "").upper(),
                "default": r.get("dflt_value"),
                "nullable": not bool(r.get("notnull", 0)),
                "pk": bool(r.get("pk", 0)),
            }
            for r in rows
        ]

    elif db.db_type == "postgres":
        rows = await db.fetchall(
            "SELECT column_name, data_type, column_default, "
            "is_nullable, ordinal_position "
            "FROM information_schema.columns "
            "WHERE table_name = ? AND table_schema = current_schema() "
            "ORDER BY ordinal_position",
            table,
        )
        return [
            {
                "name": r["column_name"],
                "type": (r["data_type"] or "").upper(),
                "default": r.get("column_default"),
                "nullable": (r.get("is_nullable") == "YES"),
                "pk": False,  # سنكتشفها لاحقاً إن أردنا
            }
            for r in rows
        ]

    elif db.db_type == "mysql":
        rows = await db.fetchall(
            "SELECT COLUMN_NAME AS column_name, "
            "DATA_TYPE AS data_type, COLUMN_TYPE AS column_type, "
            "COLUMN_DEFAULT AS column_default, "
            "IS_NULLABLE AS is_nullable, "
            "COLUMN_KEY AS column_key "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
            table,
        )
        return [
            {
                "name": r["column_name"],
                "type": (r.get("column_type") or r.get("data_type") or "").upper(),
                "default": r.get("column_default"),
                "nullable": (r.get("is_nullable") == "YES"),
                "pk": (r.get("column_key") == "PRI"),
            }
            for r in rows
        ]

    return []


async def check_table_schema(db: DBEngine, table: str):
    subheader(f"جدول: {table}")

    try:
        cols = await get_columns(db, table)
    except Exception as e:
        err(f"فشل قراءة الأعمدة: {e}")
        return

    if not cols:
        warn("لا أعمدة")
        return

    # عدد الصفوف
    try:
        count = await db.fetchval(f"SELECT COUNT(*) FROM {table}", default=0)
    except Exception:
        count = "?"

    kv("عدد الأعمدة", len(cols))
    kv("عدد الصفوف", count)

    # طباعة الأعمدة في جدول
    print(f"\n  {C.BOLD}{'العمود':<40} {'النوع':<25} {'افتراضي':<20} {C.END}")
    print(f"  {'-' * 90}")
    for c in cols:
        name = c["name"][:38]
        typ = str(c["type"])[:23]
        dflt = str(c["default"])[:18] if c["default"] is not None else "—"
        pk_mark = " 🔑" if c["pk"] else ""
        print(f"  {name:<40} {typ:<25} {dflt:<20}{pk_mark}")


# =====================================================================
# 4. فحص delete_penalty (الفحص الحاسم)
# =====================================================================

async def check_delete_penalty(db: DBEngine):
    header("4️⃣  فحص delete_penalty (الحاسم!)")

    try:
        cols = await get_columns(db, "group_security")
    except Exception as e:
        err(f"فشل قراءة group_security: {e}")
        return

    dp_col = next(
        (c for c in cols if c["name"] == "delete_penalty"), None
    )

    if not dp_col:
        err("العمود delete_penalty غير موجود في group_security!")
        return

    print(f"\n{C.BOLD}حالة العمود:{C.END}")
    kv("النوع الفعلي", f"{C.BOLD}{dp_col['type']}{C.END}", 4)
    kv("القيمة الافتراضية",
       f"{C.BOLD}{dp_col['default']}{C.END}", 4)
    kv("Nullable", dp_col["nullable"], 4)

    # تحديد التصنيف
    typ_upper = str(dp_col["type"]).upper()
    is_text_type = any(
        k in typ_upper
        for k in ("TEXT", "VARCHAR", "CHAR", "CLOB", "STRING")
    )
    is_int_type = any(
        k in typ_upper
        for k in ("INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT")
    )

    if is_text_type:
        ok("النوع نصي (TEXT/VARCHAR) — يطابق database_tables.py")
    elif is_int_type:
        warn("النوع رقمي (INTEGER) — يطابق v7.7.32 لكن يخالف database_tables.py")
    else:
        warn(f"النوع غير معروف: {typ_upper}")

    # فحص القيم الحالية
    print(f"\n{C.BOLD}القيم الحالية:{C.END}")
    try:
        if db.db_type == "sqlite":
            rows = await db.fetchall(
                "SELECT DISTINCT delete_penalty, "
                "typeof(delete_penalty) AS t, "
                "COUNT(*) AS c "
                "FROM group_security "
                "GROUP BY delete_penalty, typeof(delete_penalty)"
            )
        elif db.db_type == "postgres":
            rows = await db.fetchall(
                "SELECT DISTINCT delete_penalty, "
                "pg_typeof(delete_penalty)::text AS t, "
                "COUNT(*) AS c "
                "FROM group_security "
                "GROUP BY delete_penalty, pg_typeof(delete_penalty)"
            )
        else:  # mysql
            rows = await db.fetchall(
                "SELECT delete_penalty, COUNT(*) AS c "
                "FROM group_security GROUP BY delete_penalty"
            )
    except Exception as e:
        err(f"فشل قراءة القيم: {e}")
        return

    if not rows:
        ok("الجدول فارغ — لا قيم محفوظة (آمن للترقية)")
        return

    print(f"  {C.BOLD}{'القيمة':<20} {'العدد':<10}{C.END}")
    print(f"  {'-' * 35}")
    all_values = []
    for r in rows:
        val = r.get("delete_penalty")
        count = r.get("c", r.get("count", "?"))
        all_values.append(val)
        t = r.get("t", "")
        print(f"  {str(val):<20} {count:<10} {t}")

    # التحليل
    print(f"\n{C.BOLD}التحليل:{C.END}")

    non_null_vals = [v for v in all_values if v is not None]
    int_vals = [v for v in non_null_vals if isinstance(v, int)]
    str_vals = [v for v in non_null_vals if isinstance(v, str)]

    if not non_null_vals:
        ok("كل القيم NULL — لا شيء يحتاج ترحيل")
    elif all(v == 0 for v in int_vals) and not str_vals:
        ok("كل القيم = 0 — الترقية آمنة تماماً")
    elif str_vals and not int_vals:
        ok(f"كل القيم نصية ({set(str_vals)}) — الترقية آمنة")
    elif int_vals and not str_vals:
        non_zero = [v for v in int_vals if v != 0]
        if not non_zero:
            ok("كل القيم = 0")
        else:
            err(f"⚠️ يوجد قيم integer > 0: {sorted(set(non_zero))}")
            err("الترقية قد تُحوّل كل قيمة > 0 إلى 'mute'!")
    else:
        warn(f"خليط من int {set(int_vals)} و str {set(str_vals)}")

    # التوصية
    print(f"\n{C.BOLD}التوصية:{C.END}")
    if is_text_type:
        ok("✅ v7.7.33 آمن — الترحيل لن يفعل شيئاً (النوع بالفعل نصي)")
    elif is_int_type and not any(isinstance(v, int) and v != 0 for v in non_null_vals):
        ok("✅ v7.7.33 آمن — الترحيل سيُحوّل 0→'none' (بلا فقدان)")
    elif is_int_type:
        warn("⚠️ راجع مع المهندس — الترحيل قد يفقد معلومات")
    else:
        warn("⚠️ حالة غير معروفة — راجع يدوياً")


# =====================================================================
# 5. فحص migrations مقابل الواقع
# =====================================================================

async def check_migrations_consistency(db: DBEngine):
    header("5️⃣  تناسق _MIGRATIONS_TYPES مع الواقع")

    total_checked = 0
    total_missing = 0
    total_type_mismatch = 0

    for table, expected_cols in EXPECTED_MIGRATIONS.items():
        try:
            actual_cols = await get_columns(db, table)
        except Exception:
            continue

        if not actual_cols:
            warn(f"جدول {table} غير موجود")
            continue

        actual_names = {c["name"]: c for c in actual_cols}

        missing = []
        type_mismatch = []

        for col_name, col_def in expected_cols:
            total_checked += 1
            if col_name not in actual_names:
                missing.append(col_name)
                continue

            # استخراج النوع المتوقع
            m = re.match(r"^([A-Z_]+)", col_def.upper())
            expected_type = m.group(1) if m else ""

            actual_type = str(actual_names[col_name]["type"]).upper()

            # تطابق تقريبي
            expected_norm = expected_type.replace("INTEGER", "INT")
            actual_norm = actual_type.replace("INTEGER", "INT")
            if expected_norm and actual_norm and \
               expected_norm not in actual_norm and \
               actual_norm not in expected_norm:
                # بعض الأنواع متكافئة
                equivalents = {
                    "INT": {"INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT", "SERIAL"},
                    "TEXT": {"TEXT", "VARCHAR", "CHAR", "CLOB", "STRING"},
                    "REAL": {"REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL"},
                }
                matched = False
                for key, alts in equivalents.items():
                    if expected_norm in alts and any(a in actual_norm for a in alts):
                        matched = True
                        break
                if not matched:
                    type_mismatch.append(
                        (col_name, expected_type, actual_type)
                    )

        if missing:
            total_missing += len(missing)
            warn(f"{table}: {len(missing)} عمود مفقود")
            for m in missing[:5]:
                print(f"      • {m}")
            if len(missing) > 5:
                print(f"      ... و{len(missing) - 5} أكثر")

        if type_mismatch:
            total_type_mismatch += len(type_mismatch)
            for col, exp, act in type_mismatch:
                print(f"  {C.YELLOW}⚠️  {table}.{col}: "
                      f"متوقع={exp}, فعلي={act}{C.END}")

    print()
    kv("أعمدة مفحوصة", total_checked)
    kv("أعمدة مفقودة", total_missing)
    kv("تناقضات نوع", total_type_mismatch)

    if total_missing == 0 and total_type_mismatch == 0:
        ok("كل شيء متسق")
    else:
        warn("هناك تناقضات — راجعها")


# =====================================================================
# 6. فحص الفهارس
# =====================================================================

async def get_all_indexes(db: DBEngine) -> Set[str]:
    if db.db_type == "sqlite":
        rows = await db.fetchall(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name IS NOT NULL"
        )
        return {r["name"] for r in rows}

    elif db.db_type == "postgres":
        rows = await db.fetchall(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = current_schema()"
        )
        return {r["indexname"] for r in rows}

    elif db.db_type == "mysql":
        rows = await db.fetchall(
            "SELECT DISTINCT INDEX_NAME AS n "
            "FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE()"
        )
        return {r["n"] for r in rows}

    return set()


async def check_indexes(db: DBEngine):
    header("6️⃣  الفهارس الحرجية")

    try:
        all_idx = await get_all_indexes(db)
    except Exception as e:
        err(f"فشل قراءة الفهارس: {e}")
        return

    kv("إجمالي الفهارس", len(all_idx))

    missing = [n for n in CRITICAL_INDEXES if n not in all_idx]
    present = [n for n in CRITICAL_INDEXES if n in all_idx]

    print()
    if present:
        ok(f"{len(present)}/{len(CRITICAL_INDEXES)} فهرس حرج موجود")
    if missing:
        err(f"{len(missing)} فهرس حرج مفقود:")
        for m in missing:
            print(f"      • {m}")

    # فهارس قديمة (deprecated) إن وُجدت
    deprecated_check = [
        "idx_posts_next", "idx_posts_channel_unpub",
        "idx_sub_user_status_end", "idx_penalties_user_chat_status",
        "idx_settings_key", "idx_users_updated",
    ]
    found_deprecated = [n for n in deprecated_check if n in all_idx]
    if found_deprecated:
        warn(f"فهارس قديمة ما زالت موجودة ({len(found_deprecated)}):")
        for d in found_deprecated:
            print(f"      • {d}")


# =====================================================================
# 7. التكامل المرجعي
# =====================================================================

async def check_fk_integrity(db: DBEngine):
    header("7️⃣  التكامل المرجعي (orphaned rows)")

    total_orphans = 0

    for child_t, child_c, parent_t, parent_c in FK_CHECKS:
        try:
            # تحقق أن الجداول موجودة
            if not await db.fetchval(
                f"SELECT 1 FROM {child_t} LIMIT 1", default=None
            ) and not await db.fetchval(
                f"SELECT 1 FROM {parent_t} LIMIT 1", default=None
            ):
                continue

            sql = (
                f"SELECT COUNT(*) AS c FROM {child_t} c "
                f"WHERE c.{child_c} IS NOT NULL "
                f"AND NOT EXISTS ("
                f"  SELECT 1 FROM {parent_t} p "
                f"  WHERE p.{parent_c} = c.{child_c}"
                f")"
            )
            orphans = await db.fetchval(sql, default=0)

            if orphans and orphans > 0:
                err(f"{child_t}.{child_c} → {parent_t}.{parent_c}: "
                    f"{orphans} صف يتيم")
                total_orphans += orphans
            else:
                ok(f"{child_t}.{child_c} → {parent_t}.{parent_c}: نظيف")

        except Exception as e:
            warn(f"{child_t}.{child_c}: تعذّر الفحص ({str(e)[:50]})")

    if total_orphans == 0:
        ok("لا orphans")
    else:
        warn(f"إجمالي {total_orphans} صف يتيم — راجعها")


# =====================================================================
# 8. فحص settings الأساسية
# =====================================================================

async def check_settings(db: DBEngine):
    header("8️⃣  settings الأساسية")

    try:
        rows = await db.fetchall(
            "SELECT key, value FROM settings ORDER BY key"
        )
    except Exception as e:
        err(f"فشل قراءة settings: {e}")
        return

    kv("عدد الإعدادات", len(rows))

    expected_keys = [
        "tables_hash", "bootstrap_hash", "banned_words_hash",
        "auto_replies_hash", "publish_interval", "auto_backup",
    ]

    found = {r["key"]: r["value"] for r in rows}
    missing = [k for k in expected_keys if k not in found]

    print()
    for key in expected_keys:
        val = found.get(key)
        if val is None:
            warn(f"{key}: غير موجود")
        else:
            preview = str(val)[:40]
            print(f"  {C.GREEN}✓{C.END} {key} = {preview}")

    if missing:
        warn(f"{len(missing)} مفتاح متوقع مفقود")


# =====================================================================
# 9. عيّنة group_security (تفصيلي)
# =====================================================================

async def check_security_sample(db: DBEngine):
    header("9️⃣  عيّنة group_security (تفصيلي)")

    try:
        total = await db.fetchval(
            "SELECT COUNT(*) FROM group_security", default=0
        )
        kv("إجمالي الصفوف", total)

        if not total:
            info("الجدول فارغ")
            return

        # اعرض أول 3 صفوف (أعمدة الحرجة فقط)
        cols_to_show = [
            "chat_id", "delete_penalty", "delete_penalty_duration",
            "auto_penalty", "auto_mute_duration", "warn_penalty",
            "antiflood_penalty", "violation_penalty",
        ]

        # تحقق من وجود الأعمدة
        actual_cols = await get_columns(db, "group_security")
        actual_names = {c["name"] for c in actual_cols}
        cols_to_show = [c for c in cols_to_show if c in actual_names]

        if not cols_to_show:
            return

        cols_sql = ", ".join(cols_to_show)
        rows = await db.fetchall(
            f"SELECT {cols_sql} FROM group_security LIMIT 3"
        )

        print(f"\n  {C.BOLD}عيّنة من أول 3 صفوف:{C.END}")
        for i, row in enumerate(rows, 1):
            print(f"\n  صف #{i}:")
            for k, v in row.items():
                print(f"    {k}: {v!r}")

    except Exception as e:
        err(f"فشل: {e}")


# =====================================================================
# 10. مقارنة الأعمدة مع database_tables.py
# =====================================================================

async def check_group_security_full(db: DBEngine):
    header("🔟  group_security كامل — مقارنة مع database_tables.py")

    # الأعمدة المتوقعة من CREATE TABLE في database_tables.py
    expected = {
        "chat_id", "delete_links", "mentions", "slow_mode",
        "slow_mode_seconds", "welcome_enabled", "welcome_text",
        "goodbye_enabled", "goodbye_text", "delete_banned_words",
        "auto_penalty", "auto_mute_duration", "delete_videos",
        "delete_audio", "delete_animation", "delete_service",
        "delete_documents", "delete_stickers", "delete_forwarded",
        "delete_polls", "delete_games", "delete_voice",
        "delete_video_note", "delete_photos", "delete_penalty",
        "delete_penalty_duration", "delete_penalty_messages",
        "antiflood_enabled", "antiflood_messages", "antiflood_seconds",
        "antiflood_penalty", "antiflood_penalty_duration",
        "max_warnings", "warn_penalty", "warn_penalty_duration",
        "warn_enabled", "max_message_length",
        "night_mode_enabled", "night_mode_start", "night_mode_end",
        "night_mode_action", "night_mode_action_duration",
        "nsfw_enabled", "nsfw_threshold", "nsfw_filter",
        "auto_approve_join", "auto_reject_join",
        "mute_default_duration", "ban_default_duration",
        "warn_default_duration", "restrict_default_duration",
        "enable_timed_penalties", "auto_remove_penalties",
        "violation_strikes", "violation_duration",
        "violation_penalty", "violation_penalty_duration",
    }

    try:
        cols = await get_columns(db, "group_security")
    except Exception as e:
        err(f"فشل: {e}")
        return

    actual = {c["name"] for c in cols}

    missing = expected - actual
    extra = actual - expected

    kv("أعمدة متوقعة", len(expected))
    kv("أعمدة فعلية", len(actual))

    if missing:
        warn(f"أعمدة متوقعة مفقودة ({len(missing)}):")
        for m in sorted(missing):
            print(f"      • {m}")
    else:
        ok("لا أعمدة مفقودة")

    if extra:
        info(f"أعمدة إضافية ({len(extra)}): {', '.join(sorted(extra))}")

    # فحص خاص: delete_penalty
    dp = next((c for c in cols if c["name"] == "delete_penalty"), None)
    if dp:
        print(f"\n{C.BOLD}🎯 delete_penalty:{C.END}")
        print(f"    النوع: {C.BOLD}{dp['type']}{C.END}")
        print(f"    الافتراضي: {dp['default']}")
        print(f"    database_tables.py يقول: TEXT DEFAULT 'none'")
        print(f"    database.py v7.7.32 يقول: INTEGER DEFAULT 0")

        typ_upper = str(dp["type"]).upper()
        if any(k in typ_upper for k in ("TEXT", "VARCHAR", "CHAR")):
            ok("✅ يطابق database_tables.py (نصي)")
        elif any(k in typ_upper for k in ("INT", "BIGINT")):
            warn("⚠️ يطابق v7.7.32 (رقمي) — يخالف database_tables.py")


# =====================================================================
# Main
# =====================================================================

async def main():
    print(f"\n{C.BOLD}{C.CYAN}")
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 15 + "🔬 تشخيص قاعدة البيانات الشامل" + " " * 22 + "║")
    print("║" + " " * 20 + f"التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}" + " " * 21 + "║")
    print("╚" + "═" * 68 + "╝")
    print(C.END)

    db = DBEngine()
    try:
        await db.connect()
    except Exception as e:
        err(f"فشل الاتصال: {e}")
        return 1

    try:
        await check_connection(db)
        await check_tables(db)
        await check_delete_penalty(db)
        await check_migrations_consistency(db)
        await check_indexes(db)
        await check_fk_integrity(db)
        await check_settings(db)
        await check_group_security_full(db)
        await check_security_sample(db)
        # عرض أعمدة group_security الكاملة
        await check_table_schema(db, "group_security")

        header("✨ انتهى التشخيص")
        print()
        print(f"{C.BOLD}انسخ كل ما فوق وأرسله للمهندس.{C.END}")
        print()

    except Exception as e:
        err(f"خطأ عام: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        await db.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))