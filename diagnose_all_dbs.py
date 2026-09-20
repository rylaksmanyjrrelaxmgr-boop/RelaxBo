#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_all_dbs.py — فحص شامل لـ SQLite + PostgreSQL + MySQL في جلسة واحدة
================================================================================
يقرأ متغيرات البيئة التالية (كلها اختيارية):
  • DATABASE_URL            ← يُكتشف نوعه تلقائياً
  • SQLITE_PATH             ← مسار ملف SQLite (افتراضي: data/relax.db)
  • POSTGRES_URL            ← postgres://user:pass@host:port/db
  • MYSQL_URL               ← mysql://user:pass@host:port/db

يفحص كل نظام متوفر:
  1. الاتصال والإصدار
  2. قائمة الجداول
  3. group_security.delete_penalty (الحاسم)
  4. تناسق migrations
  5. الفهارس الحرجية
  6. التكامل المرجعي
  7. settings الأساسية
  8. مقارنة جانبية بين الأنظمة

يعمل بدون تعديل على البوت. للقراءة فقط.
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
# إعدادات الاتصال
# =====================================================================

SQLITE_PATH = os.getenv("SQLITE_PATH", "data/relax.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
POSTGRES_URL = os.getenv("POSTGRES_URL", "").strip()
MYSQL_URL = os.getenv("MYSQL_URL", "").strip()

# استنتج الأنظمة المطلوب فحصها
def detect_targets() -> Dict[str, str]:
    targets: Dict[str, str] = {}

    # DATABASE_URL → توجيه تلقائي
    if DATABASE_URL:
        L = DATABASE_URL.lower()
        if "postgres" in L:
            targets["postgres"] = DATABASE_URL
        elif "mysql" in L or "mariadb" in L:
            targets["mysql"] = DATABASE_URL
        elif "sqlite" in L:
            targets["sqlite"] = DATABASE_URL

    # متغيرات صريحة (تتجاوز التلقائي)
    if POSTGRES_URL:
        targets["postgres"] = POSTGRES_URL
    if MYSQL_URL:
        targets["mysql"] = MYSQL_URL

    # SQLite دائماً: إما من DATABASE_URL أو من SQLITE_PATH
    if "sqlite" not in targets:
        if Path(SQLITE_PATH).exists():
            targets["sqlite"] = f"sqlite:///{SQLITE_PATH}"

    return targets


# =====================================================================
# ألوان
# =====================================================================

class C:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"

    @classmethod
    def disable(cls):
        for a in ("RED", "GREEN", "YELLOW", "BLUE", "CYAN",
                  "MAGENTA", "BOLD", "DIM", "END"):
            setattr(cls, a, "")

if not sys.stdout.isatty() or os.getenv("NO_COLOR"):
    C.disable()


# =====================================================================
# قوائم مرجعية (من database.py v7.7.32 و database_tables.py v7.6.15)
# =====================================================================

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
        ("delete_penalty", "INTEGER DEFAULT 0"),
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
}

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

# الأعمدة المتوقعة في group_security (من database_tables.py)
GROUP_SECURITY_EXPECTED_COLS = {
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

# =====================================================================
# طباعة
# =====================================================================

def main_header(title: str):
    print(f"\n{C.BOLD}{C.MAGENTA}{'█' * 72}{C.END}")
    print(f"{C.BOLD}{C.MAGENTA}  {title}{C.END}")
    print(f"{C.BOLD}{C.MAGENTA}{'█' * 72}{C.END}")

def header(title: str):
    print(f"\n{C.BOLD}{C.CYAN}─── {title} {'─' * (66 - len(title))}{C.END}")

def subheader(title: str):
    print(f"\n{C.BOLD}  ▶ {title}{C.END}")

def ok(msg: str):
    print(f"    {C.GREEN}✅ {msg}{C.END}")

def warn(msg: str):
    print(f"    {C.YELLOW}⚠️  {msg}{C.END}")

def err(msg: str):
    print(f"    {C.RED}❌ {msg}{C.END}")

def info(msg: str):
    print(f"    {C.DIM}ℹ️  {msg}{C.END}")

def kv(key: str, value: Any, indent: int = 4):
    pad = " " * indent
    print(f"{pad}{C.BOLD}{key}:{C.END} {value}")


# =====================================================================
# محرك موحّد للاتصال
# =====================================================================

class DBEngine:
    """غلاف موحّد للاتصال بأي من الأنظمة الثلاثة."""

    def __init__(self, db_type: str, url: str):
        self.db_type = db_type
        self.url = url
        self.conn = None
        self._sqlite_conn = None
        self.connected = False
        self.error = None
        self.version = "?"

    async def connect(self) -> bool:
        try:
            if self.db_type == "sqlite":
                import aiosqlite
                # استخرج المسار
                path = self.url.replace("sqlite:///", "").replace("sqlite://", "")
                if not path:
                    path = SQLITE_PATH
                if not Path(path).exists():
                    self.error = f"ملف غير موجود: {path}"
                    return False
                self._sqlite_conn = await aiosqlite.connect(str(path))
                self._sqlite_conn.row_factory = aiosqlite.Row
                self.version = await self.fetchval("SELECT sqlite_version()")
                self.connected = True
                return True

            elif self.db_type == "postgres":
                import asyncpg
                self.conn = await asyncpg.connect(self.url)
                self.version = await self.fetchval(
                    "SELECT SUBSTRING(version() FROM 1 FOR 60)"
                )
                self.connected = True
                return True

            elif self.db_type == "mysql":
                import asyncmy
                p = urlparse(self.url)
                self.conn = await asyncmy.connect(
                    host=p.hostname, port=int(p.port or 3306),
                    user=p.username or "", password=p.password or "",
                    db=(p.path or "/").lstrip("/"), charset="utf8mb4",
                )
                self.version = await self.fetchval("SELECT VERSION()")
                self.connected = True
                return True

        except ImportError as e:
            self.error = f"مكتبة مفقودة: {e}"
        except Exception as e:
            self.error = str(e)[:120]
        return False

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
            if params:
                parts = sql.split("?")
                if len(parts) - 1 == len(params):
                    new_sql = parts[0]
                    for i, p in enumerate(parts[1:], 1):
                        new_sql += f"${i}" + p
                    sql = new_sql
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
        r = await self.fetchall(sql, *params)
        return r[0] if r else None

    async def fetchval(self, sql: str, *params, default=None) -> Any:
        r = await self.fetchone(sql, *params)
        if not r:
            return default
        return list(r.values())[0]

    # ─── دوال مساعدة ───

    async def get_tables(self) -> List[str]:
        try:
            if self.db_type == "sqlite":
                rows = await self.fetchall(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                )
                return [r["name"] for r in rows]
            elif self.db_type == "postgres":
                rows = await self.fetchall(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema() "
                    "AND table_type = 'BASE TABLE' "
                    "ORDER BY table_name"
                )
                return [r["table_name"] for r in rows]
            elif self.db_type == "mysql":
                rows = await self.fetchall(
                    "SELECT TABLE_NAME AS t "
                    "FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() "
                    "AND TABLE_TYPE = 'BASE TABLE' "
                    "ORDER BY TABLE_NAME"
                )
                return [r["t"] for r in rows]
        except Exception:
            return []
        return []

    async def get_columns(self, table: str) -> List[Dict]:
        try:
            if self.db_type == "sqlite":
                rows = await self.fetchall(f"PRAGMA table_info({table})")
                return [{
                    "name": r["name"],
                    "type": (r.get("type") or "").upper(),
                    "default": r.get("dflt_value"),
                    "pk": bool(r.get("pk", 0)),
                } for r in rows]

            elif self.db_type == "postgres":
                rows = await self.fetchall(
                    "SELECT column_name, data_type, column_default, "
                    "ordinal_position "
                    "FROM information_schema.columns "
                    "WHERE table_name = ? AND table_schema = current_schema() "
                    "ORDER BY ordinal_position",
                    table,
                )
                return [{
                    "name": r["column_name"],
                    "type": (r["data_type"] or "").upper(),
                    "default": r.get("column_default"),
                    "pk": False,
                } for r in rows]

            elif self.db_type == "mysql":
                rows = await self.fetchall(
                    "SELECT COLUMN_NAME, DATA_TYPE, COLUMN_TYPE, "
                    "COLUMN_DEFAULT, COLUMN_KEY "
                    "FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ? "
                    "ORDER BY ORDINAL_POSITION",
                    table,
                )
                return [{
                    "name": r["COLUMN_NAME"],
                    "type": (r.get("COLUMN_TYPE") or r.get("DATA_TYPE") or "").upper(),
                    "default": r.get("COLUMN_DEFAULT"),
                    "pk": (r.get("COLUMN_KEY") == "PRI"),
                } for r in rows]
        except Exception:
            return []
        return []

    async def get_indexes(self) -> Set[str]:
        try:
            if self.db_type == "sqlite":
                rows = await self.fetchall(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='index' AND name IS NOT NULL"
                )
                return {r["name"] for r in rows}
            elif self.db_type == "postgres":
                rows = await self.fetchall(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = current_schema()"
                )
                return {r["indexname"] for r in rows}
            elif self.db_type == "mysql":
                rows = await self.fetchall(
                    "SELECT DISTINCT INDEX_NAME AS n "
                    "FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA = DATABASE()"
                )
                return {r["n"] for r in rows}
        except Exception:
            return set()
        return set()


# =====================================================================
# فحوصات (تُطبَّق على أي engine)
# =====================================================================

async def diagnose_engine(db: DBEngine) -> Dict[str, Any]:
    """يشغّل كل الفحوصات على engine ويُعيد ملخصاً."""
    result = {
        "db_type": db.db_type,
        "connected": db.connected,
        "error": db.error,
        "version": db.version,
        "tables_count": 0,
        "missing_tables": [],
        "extra_tables": [],
        "delete_penalty_type": None,
        "delete_penalty_default": None,
        "delete_penalty_values": [],
        "delete_penalty_verdict": "؟",
        "migrations_missing": 0,
        "migrations_mismatch": 0,
        "indexes_total": 0,
        "critical_missing": [],
        "settings_count": 0,
        "settings_keys": [],
        "group_security_rows": 0,
        "group_security_missing_cols": [],
        "group_security_extra_cols": [],
        "tables": [],
        "group_security_columns": [],
    }

    if not db.connected:
        return result

    # ── الجداول ──
    tables = await db.get_tables()
    result["tables"] = tables
    result["tables_count"] = len(tables)
    result["missing_tables"] = [t for t in EXPECTED_TABLES if t not in tables]
    result["extra_tables"] = [t for t in tables if t not in EXPECTED_TABLES]

    # ── delete_penalty ──
    try:
        cols = await db.get_columns("group_security")
        result["group_security_columns"] = cols
        dp = next((c for c in cols if c["name"] == "delete_penalty"), None)
        if dp:
            result["delete_penalty_type"] = dp["type"]
            result["delete_penalty_default"] = dp["default"]

        # القيم
        if db.db_type == "sqlite":
            rows = await db.fetchall(
                "SELECT DISTINCT delete_penalty AS v, "
                "typeof(delete_penalty) AS t, COUNT(*) AS c "
                "FROM group_security "
                "GROUP BY delete_penalty, typeof(delete_penalty)"
            )
        elif db.db_type == "postgres":
            rows = await db.fetchall(
                "SELECT DISTINCT delete_penalty AS v, "
                "pg_typeof(delete_penalty)::text AS t, COUNT(*) AS c "
                "FROM group_security "
                "GROUP BY delete_penalty, pg_typeof(delete_penalty)"
            )
        else:  # mysql
            rows = await db.fetchall(
                "SELECT delete_penalty AS v, "
                "COUNT(*) AS c "
                "FROM group_security GROUP BY delete_penalty"
            )
        result["delete_penalty_values"] = rows

        # التوصية
        if not rows:
            result["delete_penalty_verdict"] = "✅ فارغ — الترقية آمنة"
        else:
            non_null = [r["v"] for r in rows if r["v"] is not None]
            ints = [v for v in non_null if isinstance(v, int)]
            strs = [v for v in non_null if isinstance(v, str)]
            if strs and not ints:
                result["delete_penalty_verdict"] = (
                    f"✅ نصوص فقط {set(strs)} — آمن"
                )
            elif ints and not strs:
                non_zero = [v for v in ints if v != 0]
                if not non_zero:
                    result["delete_penalty_verdict"] = (
                        "✅ كلها 0 — آمن"
                    )
                else:
                    result["delete_penalty_verdict"] = (
                        f"⚠️ يوجد int>0: {sorted(set(non_zero))} — خطر"
                    )
            else:
                result["delete_penalty_verdict"] = (
                    f"⚠️ خليط — راجع"
                )

        # group_security missing/extra
        actual = {c["name"] for c in cols}
        result["group_security_missing_cols"] = sorted(
            GROUP_SECURITY_EXPECTED_COLS - actual
        )
        result["group_security_extra_cols"] = sorted(
            actual - GROUP_SECURITY_EXPECTED_COLS
        )
    except Exception as e:
        result["delete_penalty_verdict"] = f"خطأ: {e}"

    # ── عدد صفوف group_security ──
    try:
        result["group_security_rows"] = await db.fetchval(
            "SELECT COUNT(*) FROM group_security", default=0
        )
    except Exception:
        pass

    # ── تناسق migrations ──
    for table, expected_cols in EXPECTED_MIGRATIONS.items():
        try:
            cols = await db.get_columns(table)
        except Exception:
            continue
        if not cols:
            continue
        names = {c["name"] for c in cols}
        for col_name, col_def in expected_cols:
            if col_name not in names:
                result["migrations_missing"] += 1
                continue
            m = re.match(r"^([A-Z_]+)", col_def.upper())
            expected = m.group(1) if m else ""
            actual_col = next(c for c in cols if c["name"] == col_name)
            actual = str(actual_col["type"]).upper()
            # تطابق مرن
            eq = {
                "INTEGER": ("INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT", "SERIAL"),
                "INT": ("INT", "INTEGER", "BIGINT"),
                "TEXT": ("TEXT", "VARCHAR", "CHAR", "CLOB", "STRING"),
                "REAL": ("REAL", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL"),
                "TIMESTAMP": ("TIMESTAMP", "DATETIME"),
                "BIGINT": ("BIGINT", "INT", "INTEGER"),
            }
            ok_type = False
            for k, alts in eq.items():
                if expected.startswith(k) and any(a in actual for a in alts):
                    ok_type = True
                    break
            if expected and expected not in actual and not ok_type:
                result["migrations_mismatch"] += 1

    # ── الفهارس ──
    all_idx = await db.get_indexes()
    result["indexes_total"] = len(all_idx)
    result["critical_missing"] = [
        n for n in CRITICAL_INDEXES if n not in all_idx
    ]

    # ── settings ──
    try:
        rows = await db.fetchall(
            "SELECT key, value FROM settings ORDER BY key"
        )
        result["settings_count"] = len(rows)
        result["settings_keys"] = [r["key"] for r in rows]
    except Exception:
        pass

    return result


# =====================================================================
# طباعة تقرير engine واحد
# =====================================================================

async def print_engine_report(db: DBEngine, res: Dict[str, Any], index: int):
    main_header(f"🖥️  النظام #{index}: {db.db_type.upper()}")

    if not db.connected:
        err(f"فشل الاتصال: {db.error}")
        return

    ok(f"متصل — الإصدار: {db.version}")

    # ─── 1. الجداول ───
    header("1. الجداول")
    kv("العدد", res["tables_count"])
    if res["missing_tables"]:
        err(f"مفقود ({len(res['missing_tables'])}): "
            f"{', '.join(res['missing_tables'][:8])}")
        if len(res["missing_tables"]) > 8:
            info(f"... و{len(res['missing_tables']) - 8} أكثر")
    else:
        ok("كل الجداول المتوقعة موجودة")

    if res["extra_tables"]:
        info(f"جداول إضافية ({len(res['extra_tables'])}): "
             f"{', '.join(res['extra_tables'][:8])}")

    # ─── 2. delete_penalty ───
    header("2. delete_penalty (الحاسم)")
    if res["delete_penalty_type"] is None:
        err("العمود غير موجود!")
    else:
        kv("النوع", f"{C.BOLD}{res['delete_penalty_type']}{C.END}")
        kv("الافتراضي", res["delete_penalty_default"])
        kv("صفوف في الجدول", res["group_security_rows"])

        if res["delete_penalty_values"]:
            subheader("القيم الحالية")
            for r in res["delete_penalty_values"]:
                v = r.get("v")
                c = r.get("c", r.get("count", "?"))
                t = r.get("t", "")
                print(f"      {str(v):<20} ({c}) {t}")
        else:
            ok("لا قيم")

        subheader("الحكم")
        verdict = res["delete_penalty_verdict"]
        if verdict.startswith("✅"):
            ok(verdict)
        elif verdict.startswith("⚠️"):
            warn(verdict)
        else:
            info(verdict)

    # ─── 3. group_security أعمدة ───
    header("3. group_security — اكتمال الأعمدة")
    kv("عدد الأعمدة", len(res["group_security_columns"]))
    if res["group_security_missing_cols"]:
        err(f"مفقود ({len(res['group_security_missing_cols'])}): "
            f"{', '.join(res['group_security_missing_cols'])}")
    else:
        ok("كل الأعمدة المتوقعة موجودة")

    if res["group_security_extra_cols"]:
        info(f"إضافي: {', '.join(res['group_security_extra_cols'])}")

    # ─── 4. تناسق migrations ───
    header("4. تناسق migrations")
    kv("أعمدة مفقودة", res["migrations_missing"])
    kv("تناقضات النوع", res["migrations_mismatch"])
    if res["migrations_missing"] == 0 and res["migrations_mismatch"] == 0:
        ok("متسق تماماً")
    else:
        warn("هناك تناقضات — راجع أعلاه")

    # ─── 5. الفهارس ───
    header("5. الفهارس")
    kv("إجمالي الفهارس", res["indexes_total"])
    if res["critical_missing"]:
        err(f"حرجية مفقودة ({len(res['critical_missing'])}):")
        for m in res["critical_missing"]:
            print(f"      • {m}")
    else:
        ok(f"كل الفهارس الحرجية ({len(CRITICAL_INDEXES)}) موجودة")

    # ─── 6. settings ───
    header("6. settings")
    kv("عدد الإعدادات", res["settings_count"])
    keys_expected = [
        "tables_hash", "bootstrap_hash", "banned_words_hash",
        "auto_replies_hash", "publish_interval",
    ]
    for k in keys_expected:
        if k in res["settings_keys"]:
            ok(f"{k} موجود")
        else:
            warn(f"{k} مفقود")


# =====================================================================
# المقارنة الجانبية
# =====================================================================

def print_comparison(all_results: List[Tuple[str, Dict[str, Any]]]):
    main_header("📊 المقارنة الجانبية بين الأنظمة")

    # عناوين الأعمدة
    systems = [name for name, _ in all_results]
    col_w = 22
    header_row = f"{'المعيار':<32}" + "".join(
        f"{name:<{col_w}}" for name in systems
    )
    print(f"\n{C.BOLD}{header_row}{C.END}")
    print("─" * (32 + col_w * len(systems)))

    def row(label: str, values: List[str]):
        line = f"{label:<32}"
        for v in values:
            line += f"{v:<{col_w}}"
        print(line)

    def color(v: str, is_ok: bool) -> str:
        return f"{C.GREEN if is_ok else C.YELLOW}{v}{C.END}"

    # الاتصال
    row("الاتصال",
        [("✅" if r["connected"] else "❌") for _, r in all_results])

    # الجداول
    row("عدد الجداول",
        [str(r["tables_count"]) for _, r in all_results])
    row("جداول مفقودة",
        [color(str(len(r["missing_tables"])),
               len(r["missing_tables"]) == 0)
         for _, r in all_results])

    # delete_penalty
    row("delete_penalty — النوع",
        [str(r["delete_penalty_type"] or "—") for _, r in all_results])
    row("delete_penalty — عدد الصفوف",
        [str(r["group_security_rows"]) for _, r in all_results])
    row("delete_penalty — الحكم",
        [r["delete_penalty_verdict"][:20] for _, r in all_results])

    # migrations
    row("migrations — مفقود",
        [color(str(r["migrations_missing"]),
               r["migrations_missing"] == 0)
         for _, r in all_results])
    row("migrations — تناقضات",
        [color(str(r["migrations_mismatch"]),
               r["migrations_mismatch"] == 0)
         for _, r in all_results])

    # فهارس
    row("عدد الفهارس",
        [str(r["indexes_total"]) for _, r in all_results])
    row("فهارس حرجية مفقودة",
        [color(str(len(r["critical_missing"])),
               len(r["critical_missing"]) == 0)
         for _, r in all_results])

    # settings
    row("settings",
        [str(r["settings_count"]) for _, r in all_results])

    # ─── الحكم النهائي ───
    print(f"\n{C.BOLD}{'─' * 72}{C.END}")
    print(f"{C.BOLD}🎯 التوصية النهائية للترقية إلى v7.7.33:{C.END}\n")

    for name, r in all_results:
        if not r["connected"]:
            print(f"  {C.DIM}{name}: غير متصل — تخطٍ{C.END}")
            continue

        verdict = r["delete_penalty_verdict"]
        if verdict.startswith("✅"):
            print(f"  {C.GREEN}✓ {name}: آمن للترقية{C.END}")
        elif verdict.startswith("⚠️"):
            print(f"  {C.YELLOW}⚠ {name}: يحتاج مراجعة{C.END}")
        else:
            print(f"  {C.DIM}? {name}: {verdict[:40]}{C.END}")


# =====================================================================
# Main
# =====================================================================

async def main():
    print(f"\n{C.BOLD}{C.MAGENTA}")
    print("╔" + "═" * 70 + "╗")
    print("║" + " " * 12 +
          "🔬 تشخيص قواعد البيانات — SQLite / PostgreSQL / MySQL" +
          " " * 4 + "║")
    print("║" + " " * 20 +
          f"التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" +
          " " * 18 + "║")
    print("╚" + "═" * 70 + "╝")
    print(C.END)

    targets = detect_targets()

    if not targets:
        err("لا يوجد أي نظام للفحص!")
        info("اضبط أحد المتغيرات: DATABASE_URL / POSTGRES_URL / MYSQL_URL")
        info("أو ضع ملف SQLite في: data/relax.db")
        return 1

    info(f"الأنظمة المُكتشَفة للفحص: {', '.join(targets.keys())}\n")

    all_results: List[Tuple[str, Dict[str, Any]]] = []
    engines: List[DBEngine] = []

    try:
        for i, (db_type, url) in enumerate(targets.items(), 1):
            print(f"\n{C.DIM}{'·' * 72}{C.END}")
            info(f"الاتصال بـ {db_type.upper()}...")

            engine = DBEngine(db_type, url)
            engines.append(engine)

            if not await engine.connect():
                print(f"\n{C.BOLD}{C.MAGENTA}{'█' * 72}{C.END}")
                print(f"{C.BOLD}{C.MAGENTA}  🖥️  النظام #{i}: {db_type.upper()}{C.END}")
                print(f"{C.BOLD}{C.MAGENTA}{'█' * 72}{C.END}")
                err(f"فشل الاتصال: {engine.error}")
                all_results.append((db_type, {
                    "db_type": db_type, "connected": False,
                    "error": engine.error,
                    "tables_count": 0, "missing_tables": [],
                    "extra_tables": [],
                    "delete_penalty_type": None,
                    "delete_penalty_default": None,
                    "delete_penalty_values": [],
                    "delete_penalty_verdict": "❌ غير متصل",
                    "migrations_missing": 0, "migrations_mismatch": 0,
                    "indexes_total": 0, "critical_missing": [],
                    "settings_count": 0, "settings_keys": [],
                    "group_security_rows": 0,
                    "group_security_missing_cols": [],
                    "group_security_extra_cols": [],
                    "tables": [], "group_security_columns": [],
                }))
                continue

            res = await diagnose_engine(engine)
            all_results.append((db_type, res))
            await print_engine_report(engine, res, i)

        # ─── المقارنة ───
        if len(all_results) > 1:
            print_comparison(all_results)
        elif len(all_results) == 1:
            print(f"\n{C.DIM}(نظام واحد فقط — لا مقارنة){C.END}")

        # ─── الخلاصة النهائية ───
        main_header("✨ الخلاصة")
        print()

        for name, r in all_results:
            if not r["connected"]:
                print(f"  {C.RED}✗ {name}: {r.get('error', 'فشل')}{C.END}")
                continue
            print(f"  {C.GREEN}✓ {name}: متصل{C.END}")

            # أهم نقطة: delete_penalty
            v = r["delete_penalty_verdict"]
            if v.startswith("✅"):
                print(f"      {C.GREEN}→ delete_penalty: {v}{C.END}")
            elif v.startswith("⚠️"):
                print(f"      {C.YELLOW}→ delete_penalty: {v}{C.END}")
            else:
                print(f"      {C.DIM}→ delete_penalty: {v}{C.END}")

        print()
        print(f"{C.BOLD}انسخ التقرير كاملاً وأرسله للمهندس.{C.END}")
        print()

    finally:
        for e in engines:
            await e.close()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}تم الإلغاء{C.END}")
        sys.exit(130)