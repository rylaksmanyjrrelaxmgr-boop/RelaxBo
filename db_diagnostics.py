#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
db_diagnostics.py — PostgreSQL/MySQL/SQLite Database Diagnostics
================================================================================
v6.1.0 — PRODUCTION DATABASE DIAGNOSTICS ENGINE

التحسينات على v6.0.0:
    ✅ REPORT_MAX_CHARS: حدّ Telegram (4096) — يستخدم أحرف لا سطور
    ✅ فحص v7.7.37: تنبيه صريح إذا "users" ليس في HEAVY_TABLES
    ✅ تحليل synchronous_commit: يفرّق بين المقصود والخطأ
    ✅ مقارنة backend_xmin مع pg_snapshot_xmin الفعلي
    ✅ diagnose_db_split(): يرجّع List[str] جاهزة للإرسال
    ✅ توافق كامل مع v6.0.0 (نفس الواجهات العامة)

الهدف:
    تشخيص حالة قاعدة البيانات، اكتشاف أسباب تراكم dead tuples،
    مشاكل autovacuum، المعاملات الطويلة، idle-in-transaction،
    stale statistics، الفهارس المفقودة، وأحجام الجداول.

المبادئ:
    ✅ لا نخلط بين "الدليل" و"الاحتمال".
    ✅ backend_xmin وحده لا يُعتبر إثباتاً للحجب.
    ✅ لا نفترض أن VACUUM سيعيد المساحة لنظام الملفات.
    ✅ لا ننفذ pg_terminate_backend() تلقائياً.
    ✅ SQL identifiers تُقتبس بأمان.
    ✅ PostgreSQL / MySQL / SQLite لها تحليلات مختلفة.
    ✅ جميع عمليات التشخيص تقريباً read-only.
    ✅ عمليات VACUUM/OPTIMIZE منفصلة عن التشخيص.
    ✅ النتائج قابلة للاستخدام مباشرة داخل Telegram HTML.

الاستخدام:

    from db_diagnostics import diagnose_db, vacuum_analyze_tables

    report = await diagnose_db()             # str (مُقصّر)
    parts = await diagnose_db_split()        # List[str] جاهزة للإرسال
    result = await vacuum_analyze_tables()

================================================================================
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


logger = logging.getLogger(__name__)


# =============================================================================
# VERSION
# =============================================================================

VERSION = "6.1.0"


# =============================================================================
# THRESHOLDS
# =============================================================================

DEAD_TUPLE_WARN_PCT = 10.0
DEAD_TUPLE_CRIT_PCT = 20.0

DEAD_TUPLE_WARN_ABS = 1_000
DEAD_TUPLE_CRIT_ABS = 10_000

LONG_TX_WARN_SECONDS = 300
VERY_LONG_TX_SECONDS = 1800

IDLE_TX_WARN_SECONDS = 120
IDLE_TX_CRIT_SECONDS = 1800

AV_NOT_RUNNING_HOURS = 24
NAPTIME_WARN_SECONDS = 300

ANALYZE_MOD_WARN_PCT = 10.0
ANALYZE_MOD_CRIT_PCT = 20.0

EXPECTED_VACUUM_SCALE_FACTOR = "0.05"
EXPECTED_ANALYZE_SCALE_FACTOR = "0.02"

DEFAULT_VACUUM_THRESHOLD = 50
DEFAULT_ANALYZE_THRESHOLD = 50

AVG_ROW_BYTES_ESTIMATE = 200

MAX_TABLES = 50
MAX_SIZE_TABLES = 20
MAX_INDEX_TABLES = 100

# 🆕 v6.1.0: حدّ Telegram = 4096 حرف. نستخدم 3800 هامش أمان.
REPORT_MAX_CHARS = 3800
TELEGRAM_MESSAGE_LIMIT = 4096

# 🆕 v6.1.0: جدول `users` يجب أن يكون في HEAVY_TABLES بدءاً من v7.7.37
REQUIRED_HEAVY_TABLE_USERS = "users"


# =============================================================================
# CRITICAL INDEXES
# =============================================================================

_CRITICAL_INDEXES: Dict[str, List[str]] = {
    "posts": [
        "posts_pkey",
        "idx_posts_unique",
        "idx_posts_text_hash",
        "idx_posts_channel_pub_at",
        "idx_posts_channel_pub_fail_created",
        "idx_posts_channel_unpub_fresh_created",
    ],
    "banned_words": [
        "banned_words_pkey",
        "banned_words_word_chat_id_key",
        "idx_banned_words_chat",
        "idx_banned_words_chat_word",
    ],
    "bot_groups": [
        "bot_groups_pkey",
        "idx_bot_groups_added_by",
        "idx_bot_groups_banned_cover",
        "idx_bot_groups_log_channel",
        "idx_groups_banned",
    ],
    "users": [
        "users_pkey",
    ],
    "user_channels": [
        "user_channels_pkey",
    ],
    "subscriptions": [
        "subscriptions_pkey",
    ],
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class CauseItem:
    """سبب مرشح."""

    text: str
    confidence: str = "medium"
    evidence: List[str] = field(default_factory=list)


@dataclass
class RootCause:
    """تحليل جدول واحد."""

    table: str
    causes: List[CauseItem] = field(default_factory=list)
    severity: str = "🟢"
    solutions: List[Tuple[int, str, str]] = field(default_factory=list)
    expected: List[str] = field(default_factory=list)


# =============================================================================
# GENERIC HELPERS
# =============================================================================

def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _escape_html(value: Any) -> str:
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _fmt_size_kb(kb: Any) -> str:
    try:
        value = float(kb)
    except (TypeError, ValueError, OverflowError):
        return "?"
    if value < 0:
        return "?"
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.2f} GB"
    if value >= 1024:
        return f"{value / 1024:.2f} MB"
    return f"{value:.1f} KB"


def _fmt_size_bytes(value: Any) -> str:
    try:
        return _fmt_size_kb(float(value) / 1024.0)
    except (TypeError, ValueError, OverflowError):
        return "?"


def _fmt_duration_seconds(value: Any) -> str:
    seconds = _safe_int(value, -1)
    if seconds < 0:
        return "?"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        minutes = seconds // 60
        remaining = seconds % 60
        if remaining:
            return f"{minutes}m{remaining}s"
        return f"{minutes}m"
    if seconds < 86400:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if minutes:
            return f"{hours}h{minutes}m"
        return f"{hours}h"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    if hours:
        return f"{days}d{hours}h"
    return f"{days}d"


def _fmt_dt(value: Any) -> str:
    if value is None:
        return "—"
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        text = str(value)
        return text[:19] if len(text) > 19 else text
    except Exception:
        return "?"


def _dead_pct(dead: int, live: int) -> float:
    dead = max(dead, 0)
    live = max(live, 0)
    total = dead + live
    if total <= 0:
        return 0.0
    return (dead / total) * 100.0


def _dead_severity(dead: int, live: int) -> str:
    pct = _dead_pct(dead, live)
    if dead >= DEAD_TUPLE_CRIT_ABS or pct >= DEAD_TUPLE_CRIT_PCT:
        return "critical"
    if dead >= DEAD_TUPLE_WARN_ABS or pct >= DEAD_TUPLE_WARN_PCT:
        return "warning"
    return "ok"


def _dead_emoji(dead: int, live: int) -> str:
    severity = _dead_severity(dead, live)
    if severity == "critical":
        return "🔴"
    if severity == "warning":
        return "🟡"
    return "✅"


def _parse_interval_seconds(value: Any) -> Optional[int]:
    """تحويل 60s / 5min / 1h / 00:05:00 / 300 إلى ثواني."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if ":" in text:
        try:
            parts = text.split(":")
            if len(parts) == 3:
                return int(
                    float(parts[0]) * 3600
                    + float(parts[1]) * 60
                    + float(parts[2])
                )
        except Exception:
            pass
    match = re.fullmatch(
        r"\s*([0-9]+(?:\.[0-9]+)?)\s*"
        r"(ms|s|sec|secs|second|seconds|"
        r"min|mins|minute|minutes|"
        r"h|hr|hrs|hour|hours|"
        r"d|day|days)?\s*",
        text,
    )
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or "s"
    multipliers = {
        "ms": 0.001,
        "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
        "min": 60, "mins": 60, "minute": 60, "minutes": 60,
        "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
        "d": 86400, "day": 86400, "days": 86400,
    }
    return int(number * multipliers.get(unit, 1))


# =============================================================================
# SQL SAFETY
# =============================================================================

def _quote_pg_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _quote_pg_literal(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text.replace("'", "''") + "'"


def _safe_sqlite_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


# =============================================================================
# DATABASE TYPE
# =============================================================================

def _is_postgres() -> bool:
    try:
        from database import USE_POSTGRES
        return bool(USE_POSTGRES)
    except Exception:
        return False


def _is_mysql() -> bool:
    try:
        from database import USE_MYSQL
        return bool(USE_MYSQL)
    except Exception:
        return False


def _db_type() -> str:
    if _is_postgres():
        return "PostgreSQL"
    if _is_mysql():
        return "MySQL"
    return "SQLite"


# =============================================================================
# TIME HELPERS
# =============================================================================

def _hours_since(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        from database import TimeUtils
        now = TimeUtils.utc_now()
        dt = value
        if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return (now - dt).total_seconds() / 3600.0
    except Exception as exc:
        logger.debug("_hours_since: %s", exc)
        return None


# =============================================================================
# RELOPTIONS
# =============================================================================

def _parse_reloptions(value: Any) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if value is None:
        return result
    try:
        if isinstance(value, (list, tuple)):
            items = value
        else:
            text = str(value).strip()
            if text.startswith("{") and text.endswith("}"):
                text = text[1:-1]
            if not text:
                return result
            items = text.split(",")
        for item in items:
            item = str(item).strip()
            if "=" not in item:
                continue
            key, val = item.split("=", 1)
            result[key.strip()] = val.strip()
    except Exception as exc:
        logger.debug("_parse_reloptions: %s", exc)
    return result


def _normalize_factor(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        number = float(str(value).strip())
        return f"{number:.6f}".rstrip("0").rstrip(".")
    except Exception:
        return str(value).strip()


# =============================================================================
# 1. DEAD TUPLES
# =============================================================================

async def _get_dead_tuples_postgres() -> List[Dict[str, Any]]:
    from database import DB
    try:
        rows = await DB.fetchall("""
            SELECT relname AS table_name,
                   n_live_tup AS live_tup,
                   n_dead_tup AS dead_tup,
                   n_tup_ins AS inserts,
                   n_tup_upd AS updates,
                   n_tup_del AS deletes,
                   n_mod_since_analyze AS mod_since_analyze,
                   last_vacuum,
                   last_autovacuum,
                   last_analyze,
                   last_autoanalyze,
                   vacuum_count,
                   autovacuum_count,
                   analyze_count,
                   autoanalyze_count
            FROM pg_stat_user_tables
            WHERE n_live_tup > 0 OR n_dead_tup > 0
            ORDER BY n_dead_tup DESC, n_live_tup DESC
            LIMIT 50
        """)
        return rows or []
    except Exception as exc:
        logger.warning("_get_dead_tuples_postgres: %s", exc)
        return []


async def _get_dead_tuples_mysql() -> List[Dict[str, Any]]:
    from database import DB
    try:
        rows = await DB.fetchall("""
            SELECT TABLE_NAME AS table_name,
                   TABLE_ROWS AS live_tup,
                   DATA_FREE AS data_free_bytes,
                   DATA_LENGTH AS data_bytes,
                   INDEX_LENGTH AS index_bytes
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
            ORDER BY DATA_FREE DESC, TABLE_ROWS DESC
            LIMIT 50
        """)
        result = []
        for row in rows or []:
            result.append({
                "table_name": row.get("table_name"),
                "live_tup": _safe_int(row.get("live_tup")),
                "dead_tup": 0,
                "data_free_bytes": _safe_int(row.get("data_free_bytes")),
                "data_bytes": _safe_int(row.get("data_bytes")),
                "index_bytes": _safe_int(row.get("index_bytes")),
                "inserts": 0, "updates": 0, "deletes": 0,
                "mod_since_analyze": 0,
                "last_vacuum": None, "last_autovacuum": None,
                "last_analyze": None, "last_autoanalyze": None,
                "vacuum_count": 0, "autovacuum_count": 0,
                "analyze_count": 0, "autoanalyze_count": 0,
            })
        return result
    except Exception as exc:
        logger.warning("_get_dead_tuples_mysql: %s", exc)
        return []


async def _get_dead_tuples_sqlite() -> List[Dict[str, Any]]:
    from database import DB
    try:
        rows = await DB.fetchall("""
            SELECT name AS table_name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)
        result = []
        for row in rows or []:
            name = row.get("table_name")
            if not name:
                continue
            safe_name = _safe_sqlite_identifier(name)
            try:
                count = _safe_int(
                    await DB.fetchval(
                        f"SELECT COUNT(*) FROM {safe_name}",
                        default=0,
                    )
                )
            except Exception:
                count = 0
            result.append({
                "table_name": name,
                "live_tup": count,
                "dead_tup": 0,
                "inserts": 0, "updates": 0, "deletes": 0,
                "mod_since_analyze": 0,
                "last_vacuum": None, "last_autovacuum": None,
                "last_analyze": None, "last_autoanalyze": None,
                "vacuum_count": 0, "autovacuum_count": 0,
                "analyze_count": 0, "autoanalyze_count": 0,
            })
        return result
    except Exception as exc:
        logger.warning("_get_dead_tuples_sqlite: %s", exc)
        return []


async def _get_dead_tuples() -> List[Dict[str, Any]]:
    if _is_postgres():
        return await _get_dead_tuples_postgres()
    if _is_mysql():
        return await _get_dead_tuples_mysql()
    return await _get_dead_tuples_sqlite()


# =============================================================================
# 2. TABLE SIZES
# =============================================================================

async def _get_table_sizes() -> List[Dict[str, Any]]:
    from database import DB

    if _is_postgres():
        try:
            return await DB.fetchall("""
                SELECT relname AS table_name,
                       pg_total_relation_size(relid) AS total_bytes,
                       pg_relation_size(relid) AS table_bytes,
                       pg_indexes_size(relid) AS index_bytes
                FROM pg_stat_user_tables
                ORDER BY pg_total_relation_size(relid) DESC
                LIMIT 20
            """) or []
        except Exception as exc:
            logger.warning("_get_table_sizes postgres: %s", exc)
            return []

    if _is_mysql():
        try:
            return await DB.fetchall("""
                SELECT TABLE_NAME AS table_name,
                       COALESCE(DATA_LENGTH, 0)
                       + COALESCE(INDEX_LENGTH, 0) AS total_bytes,
                       COALESCE(DATA_LENGTH, 0) AS table_bytes,
                       COALESCE(INDEX_LENGTH, 0) AS index_bytes
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY (
                    COALESCE(DATA_LENGTH, 0)
                    + COALESCE(INDEX_LENGTH, 0)
                ) DESC
                LIMIT 20
            """) or []
        except Exception as exc:
            logger.warning("_get_table_sizes mysql: %s", exc)
            return []

    try:
        rows = await DB.fetchall("""
            SELECT name AS table_name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        """)
        result = []
        for row in rows or []:
            name = row.get("table_name")
            if not name:
                continue
            safe_name = _safe_sqlite_identifier(name)
            try:
                count = _safe_int(
                    await DB.fetchval(
                        f"SELECT COUNT(*) FROM {safe_name}",
                        default=0,
                    )
                )
            except Exception:
                count = 0
            approx = count * AVG_ROW_BYTES_ESTIMATE
            result.append({
                "table_name": name,
                "total_bytes": approx,
                "table_bytes": approx,
                "index_bytes": 0,
                "row_count": count,
            })
        result.sort(
            key=lambda item: _safe_int(item.get("total_bytes")),
            reverse=True,
        )
        return result[:20]
    except Exception as exc:
        logger.warning("_get_table_sizes sqlite: %s", exc)
        return []


# =============================================================================
# 3. PER-TABLE AUTOVACUUM
# =============================================================================

async def _get_per_table_autovacuum() -> Dict[str, Dict[str, Any]]:
    from database import DB, USE_POSTGRES, HEAVY_TABLES_FOR_AUTOVACUUM

    result: Dict[str, Dict[str, Any]] = {}
    heavy = list(HEAVY_TABLES_FOR_AUTOVACUUM or [])
    for table in heavy:
        result[table] = {
            "reloptions": {},
            "is_tuned": False,
            "exists": False,
        }

    if not USE_POSTGRES or not heavy:
        return result

    try:
        rows = await DB.fetchall("""
            SELECT c.relname AS table_name, c.reloptions
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relname = ANY($1::text[])
        """, heavy)
    except Exception as exc:
        logger.warning("_get_per_table_autovacuum: %s", exc)
        return result

    for row in rows or []:
        name = row.get("table_name")
        if not name:
            continue
        options = _parse_reloptions(row.get("reloptions"))
        vacuum_factor = _normalize_factor(
            options.get("autovacuum_vacuum_scale_factor")
        )
        analyze_factor = _normalize_factor(
            options.get("autovacuum_analyze_scale_factor")
        )
        tuned = (
            vacuum_factor == _normalize_factor(EXPECTED_VACUUM_SCALE_FACTOR)
            and analyze_factor == _normalize_factor(EXPECTED_ANALYZE_SCALE_FACTOR)
        )
        result[name] = {
            "reloptions": options,
            "is_tuned": tuned,
            "exists": True,
        }
    return result


# =============================================================================
# 4. POSTGRES ACTIVITY / BLOCKERS
# =============================================================================

async def _get_autovacuum_blockers() -> List[Dict[str, Any]]:
    from database import DB, USE_POSTGRES

    if not USE_POSTGRES:
        return []

    blockers: List[Dict[str, Any]] = []

    # =========================================================================
    # Long transactions
    # =========================================================================
    try:
        rows = await DB.fetchall("""
            SELECT pid, state, usename, application_name,
                   client_addr::text AS client_addr,
                   EXTRACT(EPOCH FROM (now() - xact_start))::bigint
                       AS tx_age_sec,
                   EXTRACT(EPOCH FROM (now() - query_start))::bigint
                       AS query_age_sec,
                   backend_xmin::text AS backend_xmin,
                   backend_xid::text AS backend_xid,
                   substring(query, 1, 300) AS query
            FROM pg_stat_activity
            WHERE xact_start IS NOT NULL
              AND state <> 'idle'
              AND pid <> pg_backend_pid()
              AND EXTRACT(EPOCH FROM (now() - xact_start)) > $1
            ORDER BY tx_age_sec DESC
            LIMIT 20
        """, LONG_TX_WARN_SECONDS)
        for row in rows or []:
            blockers.append({
                "type": "long_transaction",
                "pid": row.get("pid"),
                "state": row.get("state"),
                "usename": row.get("usename"),
                "app": row.get("application_name"),
                "client": row.get("client_addr"),
                "tx_age_sec": _safe_int(row.get("tx_age_sec")),
                "query_age_sec": _safe_int(row.get("query_age_sec")),
                "backend_xmin": row.get("backend_xmin"),
                "backend_xid": row.get("backend_xid"),
                "query": (row.get("query") or "")[:300],
            })
    except Exception as exc:
        logger.debug("blockers(long transaction): %s", exc)

    # =========================================================================
    # Idle in transaction
    # =========================================================================
    try:
        rows = await DB.fetchall("""
            SELECT pid, usename, application_name,
                   client_addr::text AS client_addr,
                   EXTRACT(EPOCH FROM (now() - state_change))::bigint
                       AS idle_sec,
                   backend_xmin::text AS backend_xmin,
                   backend_xid::text AS backend_xid,
                   substring(query, 1, 300) AS query
            FROM pg_stat_activity
            WHERE state = 'idle in transaction'
              AND pid <> pg_backend_pid()
              AND EXTRACT(EPOCH FROM (now() - state_change)) > $1
            ORDER BY idle_sec DESC
            LIMIT 20
        """, IDLE_TX_WARN_SECONDS)
        for row in rows or []:
            blockers.append({
                "type": "idle_in_transaction",
                "pid": row.get("pid"),
                "usename": row.get("usename"),
                "app": row.get("application_name"),
                "client": row.get("client_addr"),
                "idle_sec": _safe_int(row.get("idle_sec")),
                "backend_xmin": row.get("backend_xmin"),
                "backend_xid": row.get("backend_xid"),
                "query": (row.get("query") or "")[:300],
            })
    except Exception as exc:
        logger.debug("blockers(idle transaction): %s", exc)

    # =========================================================================
    # Running VACUUM
    # =========================================================================
    try:
        rows = await DB.fetchall("""
            SELECT pid, datname,
                   relid::regclass::text AS table_name,
                   phase,
                   heap_blks_total,
                   heap_blks_scanned,
                   heap_blks_vacuumed,
                   CASE
                       WHEN heap_blks_total > 0
                       THEN ROUND(
                           heap_blks_vacuumed::numeric
                           / heap_blks_total::numeric * 100, 1)
                       ELSE 0
                   END AS progress_pct
            FROM pg_stat_progress_vacuum
            LIMIT 20
        """)
        for row in rows or []:
            total = _safe_int(row.get("heap_blks_total"))
            scanned = _safe_int(row.get("heap_blks_scanned"))
            vacuumed = _safe_int(row.get("heap_blks_vacuumed"))
            pct = _safe_float(row.get("progress_pct"))
            if total > 0:
                progress = (
                    f"scanned={scanned:,}; "
                    f"vacuumed={vacuumed:,}/{total:,}; "
                    f"{pct:.1f}%"
                )
            else:
                progress = "?"
            blockers.append({
                "type": "running_vacuum",
                "pid": row.get("pid"),
                "datname": row.get("datname"),
                "table": row.get("table_name"),
                "phase": row.get("phase"),
                "progress": progress,
            })
    except Exception as exc:
        logger.debug("blockers(running vacuum): %s", exc)

    return blockers


# =============================================================================
# 🆕 v6.1.0: XMIN HORIZON
# =============================================================================

async def _get_current_xmin_horizon() -> Optional[int]:
    """
    🆕 v6.1.0: يجلب pg_snapshot_xmin(pg_current_snapshot()) كعدد صحيح.

    ملاحظة تقنية:
        - `pg_current_snapshot()` متاح من PG 9.6+.
        - `pg_snapshot_xmin()` يرجع xid كـ xid8 في PG 13+.
        - نحوّله إلى int للمقارنة.

    يعيد None إذا فشل أو إذا كان الإصدار قديماً.
    """
    from database import DB

    try:
        row = await DB.fetchone(
            "SELECT pg_snapshot_xmin(pg_current_snapshot())::text "
            "AS xmin"
        )
        if not row:
            return None
        xmin_str = row.get("xmin")
        if not xmin_str:
            return None
        return int(xmin_str)
    except Exception as exc:
        logger.debug("_get_current_xmin_horizon: %s", exc)
        return None


def _parse_xmin(value: Any) -> Optional[int]:
    """يحوّل backend_xmin (نص) إلى int."""
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return int(text)
    except (TypeError, ValueError):
        return None


def _detect_xmin_blockers(
    blockers: List[Dict[str, Any]],
    current_xmin: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    يحدد المعاملات التي تستحق التحقيق بسبب backend_xmin قديم.

    v6.1.0:
        إذا توفّر current_xmin → نقارن ونفلتر من يحجب فعلاً
        (backend_xmin < current_xmin = يمنع VACUUM من تنظيف tuples
        من هذه النقطة وما قبلها).
    """
    candidates: List[Dict[str, Any]] = []

    for item in blockers:
        if item.get("type") != "long_transaction":
            continue

        age = _safe_int(item.get("tx_age_sec"))
        xmin_raw = item.get("backend_xmin")
        xmin_int = _parse_xmin(xmin_raw)

        if age < VERY_LONG_TX_SECONDS:
            continue
        if xmin_int is None:
            continue

        # 🆕 v6.1.0: تحقق فعلي إن أمكن
        blocks_vacuum: Optional[bool] = None
        if current_xmin is not None:
            # backend_xmin < current_xmin → يحجز tuples
            # backend_xmin >= current_xmin → حديث، لا يحجب
            blocks_vacuum = xmin_int < current_xmin

        # ─── القرار ───
        if blocks_vacuum is True:
            confidence = "high"
            note = "يحجب VACUUM فعلاً (xmin < horizon)"
        elif blocks_vacuum is False:
            confidence = "medium"
            note = "لا يحجب حالياً (xmin >= horizon)"
        else:
            confidence = "medium"
            note = "غير مؤكد (لا يمكن قراءة horizon)"

        candidates.append({
            "pid": item.get("pid"),
            "age": age,
            "xmin": xmin_int,
            "backend_xid": item.get("backend_xid"),
            "state": item.get("state"),
            "query": item.get("query") or "",
            "blocks_vacuum": blocks_vacuum,
            "confidence": confidence,
            "note": note,
        })

    # ترتيب: الحاجبون فعلاً أولاً، ثم الأقدم
    candidates.sort(
        key=lambda c: (
            c.get("blocks_vacuum") is not True,
            -_safe_int(c.get("age")),
        )
    )

    return candidates


def _detect_xmin_blocker(
    long_tx: List[Dict[str, Any]],
    current_xmin: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Backward-compatible helper."""
    candidates = _detect_xmin_blockers(long_tx, current_xmin)
    return candidates[0] if candidates else None


# =============================================================================
# 5. INDEXES
# =============================================================================

async def _get_indexes(
    tables: List[str],
) -> Dict[str, List[str]]:
    from database import DB

    result: Dict[str, List[str]] = {table: [] for table in tables}
    if not tables:
        return result

    try:
        if _is_postgres():
            rows = await DB.fetchall("""
                SELECT tablename AS table_name,
                       indexname AS index_name
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = ANY($1::text[])
                ORDER BY tablename, indexname
            """, tables)
            for row in rows or []:
                table = row.get("table_name")
                index = row.get("index_name")
                if (table in result and index
                        and index not in result[table]):
                    result[table].append(index)

        elif _is_mysql():
            rows = await DB.fetchall("""
                SELECT TABLE_NAME AS table_name,
                       INDEX_NAME AS index_name
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                ORDER BY TABLE_NAME, INDEX_NAME
            """)
            for row in rows or []:
                table = row.get("table_name")
                index = row.get("index_name")
                if (table in result and index
                        and index not in result[table]):
                    result[table].append(index)

        else:
            rows = await DB.fetchall("""
                SELECT name AS index_name,
                       tbl_name AS table_name
                FROM sqlite_master
                WHERE type = 'index'
            """)
            for row in rows or []:
                table = row.get("table_name")
                index = row.get("index_name")
                if (table in result and index
                        and index not in result[table]):
                    result[table].append(index)

    except Exception as exc:
        logger.warning("_get_indexes: %s", exc)

    return result


# =============================================================================
# 6. POSTGRES SETTINGS
# =============================================================================

async def _get_pg_settings() -> Dict[str, Any]:
    from database import DB, USE_POSTGRES

    if not USE_POSTGRES:
        return {}

    keys = [
        "autovacuum",
        "autovacuum_naptime",
        "autovacuum_vacuum_scale_factor",
        "autovacuum_analyze_scale_factor",
        "autovacuum_vacuum_threshold",
        "autovacuum_analyze_threshold",
        "autovacuum_max_workers",
        "autovacuum_vacuum_cost_delay",
        "autovacuum_vacuum_cost_limit",
        "max_connections",
        "shared_buffers",
        "work_mem",
        "effective_cache_size",
        "synchronous_commit",
        "server_version",
    ]
    settings: Dict[str, Any] = {}
    for key in keys:
        try:
            settings[key] = await DB.fetchval(f"SHOW {key}")
        except Exception as exc:
            logger.debug("SHOW %s failed: %s", key, exc)
            settings[key] = None
    return settings


def _autovacuum_enabled(settings: Dict[str, Any]) -> bool:
    value = str(settings.get("autovacuum", "on")).strip().lower()
    return value in {"on", "true", "1", "yes"}


# =============================================================================
# AUTOVACUUM THRESHOLD CALCULATION
# =============================================================================

def _autovacuum_vacuum_trigger(
    live_rows: int,
    settings: Dict[str, Any],
    table_options: Optional[Dict[str, str]] = None,
) -> int:
    options = table_options or {}
    threshold_raw = options.get("autovacuum_vacuum_threshold")
    scale_raw = options.get("autovacuum_vacuum_scale_factor")
    if threshold_raw is None:
        threshold_raw = settings.get("autovacuum_vacuum_threshold")
    if scale_raw is None:
        scale_raw = settings.get("autovacuum_vacuum_scale_factor")
    threshold = _safe_int(threshold_raw, DEFAULT_VACUUM_THRESHOLD)
    scale = _safe_float(scale_raw, 0.2)
    trigger = threshold + int(max(live_rows, 0) * max(scale, 0.0))
    return max(trigger, 0)


def _autovacuum_analyze_trigger(
    live_rows: int,
    settings: Dict[str, Any],
    table_options: Optional[Dict[str, str]] = None,
) -> int:
    options = table_options or {}
    threshold_raw = options.get("autovacuum_analyze_threshold")
    scale_raw = options.get("autovacuum_analyze_scale_factor")
    if threshold_raw is None:
        threshold_raw = settings.get("autovacuum_analyze_threshold")
    if scale_raw is None:
        scale_raw = settings.get("autovacuum_analyze_scale_factor")
    threshold = _safe_int(threshold_raw, DEFAULT_ANALYZE_THRESHOLD)
    scale = _safe_float(scale_raw, 0.1)
    trigger = threshold + int(max(live_rows, 0) * max(scale, 0.0))
    return max(trigger, 0)


# =============================================================================
# 🆕 v6.1.0: PROJECT CONFIG CHECK (v7.7.37)
# =============================================================================

def _check_project_heavy_tables() -> Optional[str]:
    """
    🆕 v6.1.0: يتحقق من أن "users" موجود في HEAVY_TABLES_FOR_AUTOVACUUM.

    السبب:
        v7.7.37 أضاف "users" للقائمة. إذا نسيت النشر/restart،
        سيبقى users غير مُضبوط.

    يعيد نص تحذير أو None إذا كل شيء سليم.
    """
    try:
        from database import HEAVY_TABLES_FOR_AUTOVACUUM
    except Exception as exc:
        logger.debug("_check_project_heavy_tables: %s", exc)
        return None

    heavy = set(HEAVY_TABLES_FOR_AUTOVACUUM or [])

    if REQUIRED_HEAVY_TABLE_USERS not in heavy:
        return (
            "🔴 <b>v7.7.37 لم يُطبَّق</b> — "
            f'"{REQUIRED_HEAVY_TABLE_USERS}" مفقود من '
            "HEAVY_TABLES_FOR_AUTOVACUUM. "
            "أعد النشر + restart البوت."
        )
    return None


# =============================================================================
# ANALYSIS ENGINE
# =============================================================================

async def _analyze_root_causes(
    dead_rows: List[Dict[str, Any]],
    per_table: Dict[str, Dict[str, Any]],
    blockers: List[Dict[str, Any]],
    pg_settings: Dict[str, Any],
) -> Tuple[List[RootCause], List[str]]:
    if not _is_postgres():
        return [], []

    from database import HEAVY_TABLES_FOR_AUTOVACUUM

    causes_out: List[RootCause] = []
    general_notes: List[str] = []

    heavy_tables = set(HEAVY_TABLES_FOR_AUTOVACUUM or [])

    long_tx = [b for b in blockers
               if b.get("type") == "long_transaction"]
    idle_tx = [b for b in blockers
               if b.get("type") == "idle_in_transaction"]
    running_vacuum = [b for b in blockers
                      if b.get("type") == "running_vacuum"]

    av_enabled = _autovacuum_enabled(pg_settings)
    naptime = _parse_interval_seconds(
        pg_settings.get("autovacuum_naptime")
    )

    # ─── Global state ───
    if not av_enabled:
        general_notes.append(
            "🔴 <b>autovacuum = OFF</b> — "
            "التنظيف التلقائي معطّل عالمياً."
        )
    else:
        general_notes.append("🟢 <b>autovacuum = ON</b>.")

    # 🆕 v6.1.0: تحليل synchronous_commit
    sc = str(pg_settings.get("synchronous_commit", "")).strip().lower()
    if sc == "off":
        general_notes.append(
            "ℹ️ <b>synchronous_commit=off</b> — "
            "مقصود من v7.7.36 لتحسين الأداء. "
            "لا تعتبره خطأً."
        )
    elif sc == "on":
        general_notes.append(
            "⚠️ <b>synchronous_commit=on</b> — "
            "v7.7.36 يضبطه على off تلقائياً عبر server_settings. "
            "إن كنت متأكداً أن الكود ينشئ pool بشكل صحيح، "
            "فهذا يعني أن تعيين per-session لم يُطبَّق."
        )

    # 🆕 v6.1.0: فحص v7.7.37
    project_warning = _check_project_heavy_tables()
    if project_warning:
        general_notes.append(project_warning)

    if naptime is not None and naptime > NAPTIME_WARN_SECONDS:
        general_notes.append(
            "🟡 <b>autovacuum_naptime</b> = "
            f"<code>{_escape_html(pg_settings.get('autovacuum_naptime'))}</code> "
            "وهو أعلى من 5 دقائق."
        )

    # ─── Running VACUUM ───
    if running_vacuum:
        for item in running_vacuum:
            general_notes.append(
                "🟢 VACUUM يعمل الآن على "
                f"<code>{_escape_html(item.get('table'))}</code> "
                f"— {_escape_html(item.get('phase'))} "
                f"({_escape_html(item.get('progress'))})"
            )

    # 🆕 v6.1.0: مقارنة xmin الفعلية
    current_xmin = await _get_current_xmin_horizon()
    xmin_candidates = _detect_xmin_blockers(long_tx, current_xmin)

    if xmin_candidates:
        # ابحث عن أول واحد يحجب فعلاً
        real_blockers = [
            c for c in xmin_candidates
            if c.get("blocks_vacuum") is True
        ]
        if real_blockers:
            candidate = real_blockers[0]
            general_notes.append(
                "🔴 <b>معاملة تحجب VACUUM فعلاً:</b> "
                f"pid=<code>{candidate.get('pid')}</code> "
                f"العمر={_fmt_duration_seconds(candidate.get('age'))} "
                f"xmin=<code>{candidate.get('xmin')}</code> "
                f"< horizon=<code>{current_xmin}</code>"
            )
        else:
            candidate = xmin_candidates[0]
            general_notes.append(
                "🟡 <b>مرشح للتحقيق (غير مؤكد):</b> "
                f"pid=<code>{candidate.get('pid')}</code> "
                f"العمر={_fmt_duration_seconds(candidate.get('age'))} "
                f"xmin=<code>{candidate.get('xmin')}</code>"
            )
    elif long_tx:
        general_notes.append(
            f"🟡 توجد <b>{len(long_tx)}</b> معاملة طويلة؛ "
            "لم يظهر دليل كافٍ لإثبات أنها تحجز VACUUM."
        )

    # ─── Idle transactions ───
    if idle_tx:
        severe_idle = [
            item for item in idle_tx
            if _safe_int(item.get("idle_sec")) >= IDLE_TX_CRIT_SECONDS
        ]
        if severe_idle:
            general_notes.append(
                "🔴 توجد معاملات <b>idle in transaction</b> "
                f"لفترة طويلة ({len(severe_idle)})."
            )
        else:
            general_notes.append(
                f"🟠 توجد <b>{len(idle_tx)}</b> "
                "idle-in-transaction؛ قد تحتفظ بـ snapshot."
            )

    # ─── Per table ───
    for row in dead_rows:
        table = row.get("table_name")
        if not table:
            continue

        live = _safe_int(row.get("live_tup"))
        dead = _safe_int(row.get("dead_tup"))
        severity = _dead_severity(dead, live)
        if severity == "ok":
            continue

        pct = _dead_pct(dead, live)
        info = per_table.get(table, {})
        reloptions = info.get("reloptions") or {}
        is_heavy = table in heavy_tables
        is_tuned = bool(info.get("is_tuned"))

        last_av = row.get("last_autovacuum")
        av_hours = _hours_since(last_av)
        analyze_mod = _safe_int(row.get("mod_since_analyze"))
        analyze_mod_pct = (
            analyze_mod / live * 100.0 if live > 0 else 0.0
        )

        vacuum_trigger = _autovacuum_vacuum_trigger(
            live, pg_settings, reloptions
        )
        analyze_trigger = _autovacuum_analyze_trigger(
            live, pg_settings, reloptions
        )

        active_vacuum = any(
            item.get("type") == "running_vacuum"
            and item.get("table") == table
            for item in blockers
        )

        # ─── Causes ───
        causes_list: List[CauseItem] = []

        if active_vacuum:
            causes_list.append(CauseItem(
                text=(
                    "VACUUM يعمل حالياً على الجدول؛ "
                    "قد تكون الإحصاءات الحالية مؤقتة."
                ),
                confidence="high",
                evidence=["pg_stat_progress_vacuum"],
            ))

        if not av_enabled:
            causes_list.append(CauseItem(
                text=(
                    "autovacuum معطّل عالمياً؛ "
                    "لن يحدث تنظيف تلقائي."
                ),
                confidence="high",
                evidence=["autovacuum=off"],
            ))

        if dead >= vacuum_trigger:
            causes_list.append(CauseItem(
                text=(
                    "عدد dead tuples تجاوز threshold "
                    "المحسوب تقريبياً لـ autovacuum."
                ),
                confidence="high",
                evidence=[
                    f"dead={dead:,}",
                    f"trigger≈{vacuum_trigger:,}",
                ],
            ))

        if is_heavy and not is_tuned:
            causes_list.append(CauseItem(
                text=(
                    "<b>إعدادات الجدول الخاصة بـ autovacuum "
                    "ليست على القيم المستهدفة.</b>"
                ),
                confidence="high",
                evidence=[
                    "reloptions="
                    + (
                        ", ".join(
                            f"{k}={v}"
                            for k, v in list(reloptions.items())[:5]
                        )
                        if reloptions
                        else "default"
                    )
                ],
            ))

        # xmin
        if xmin_candidates:
            # استخدم الأول ذا blocks_vacuum=True إن وُجد
            candidate = next(
                (c for c in xmin_candidates
                 if c.get("blocks_vacuum") is True),
                xmin_candidates[0],
            )
            is_real_blocker = candidate.get("blocks_vacuum") is True
            causes_list.append(CauseItem(
                text=(
                    "معاملة طويلة تحجز snapshot قديم "
                    + (
                        "(مثبت)."
                        if is_real_blocker
                        else "(مرشح، غير مثبت)."
                    )
                ),
                confidence=(
                    "high" if is_real_blocker else "medium"
                ),
                evidence=[
                    f"pid={candidate.get('pid')}",
                    "age=" + _fmt_duration_seconds(
                        candidate.get("age")
                    ),
                    f"backend_xmin={candidate.get('xmin')}",
                    f"note={candidate.get('note', '')}",
                ],
            ))
        elif long_tx:
            causes_list.append(CauseItem(
                text=(
                    f"توجد {len(long_tx)} معاملة طويلة، "
                    "لكن الحجب غير مثبت."
                ),
                confidence="low",
                evidence=[
                    (
                        f"pid={item.get('pid')} "
                        f"age={_fmt_duration_seconds(item.get('tx_age_sec'))}"
                    )
                    for item in long_tx[:3]
                ],
            ))

        if idle_tx:
            causes_list.append(CauseItem(
                text=(
                    f"توجد {len(idle_tx)} "
                    "idle-in-transaction؛ قد تحتفظ "
                    "بـ snapshot مفتوح."
                ),
                confidence="medium",
                evidence=[
                    (
                        f"pid={item.get('pid')} "
                        f"idle={_fmt_duration_seconds(item.get('idle_sec'))}"
                    )
                    for item in idle_tx[:3]
                ],
            ))

        if av_hours is not None and av_hours > AV_NOT_RUNNING_HOURS:
            causes_list.append(CauseItem(
                text="آخر autovacuum أقدم من 24 ساعة.",
                confidence="medium",
                evidence=[f"last_autovacuum={_fmt_dt(last_av)}"],
            ))

        if av_hours is None and dead > DEAD_TUPLE_WARN_ABS:
            causes_list.append(CauseItem(
                text=(
                    "لا توجد قيمة last_autovacuum؛ "
                    "قد يعني ذلك أن autovacuum لم يُسجّل "
                    "على هذا الجدول بعد."
                ),
                confidence="medium",
                evidence=["last_autovacuum=NULL"],
            ))

        if analyze_mod_pct >= ANALYZE_MOD_WARN_PCT:
            causes_list.append(CauseItem(
                text=(
                    "إحصاءات الجدول قديمة بسبب عدد كبير "
                    "من التعديلات منذ آخر ANALYZE."
                ),
                confidence=(
                    "high"
                    if analyze_mod_pct >= ANALYZE_MOD_CRIT_PCT
                    else "medium"
                ),
                evidence=[
                    f"mod_since_analyze={analyze_mod:,}",
                    f"ratio={analyze_mod_pct:.1f}%",
                    f"trigger≈{analyze_trigger:,}",
                ],
            ))

        if not causes_list:
            causes_list.append(CauseItem(
                text="لم يظهر سبب جذري واضح من البيانات الحالية.",
                confidence="low",
                evidence=[f"dead/live={pct:.1f}%"],
            ))

        # ─── Solutions ───
        solutions: List[Tuple[int, str, str]] = []
        priority = 1
        safe_table = _quote_pg_identifier(table)
        safe_table_html = _escape_html(safe_table)

        if active_vacuum:
            solutions.append((
                priority,
                "⏳ انتظر VACUUM الجاري ثم أعد التشخيص.",
                (
                    "SELECT relname, n_live_tup, n_dead_tup "
                    "FROM pg_stat_user_tables "
                    f"WHERE relname = {_quote_pg_literal(table)};"
                ),
            ))
        else:
            solutions.append((
                priority,
                (
                    "🧹 <b>تنظيف فوري:</b> "
                    f"<code>VACUUM (ANALYZE) "
                    f"{safe_table_html};</code>"
                ),
                f"VACUUM (ANALYZE) {safe_table};",
            ))
        priority += 1

        if is_heavy and not is_tuned:
            solutions.append((
                priority,
                "⚙️ اضبط autovacuum للجدول على القيم المستهدفة:",
                (
                    f"ALTER TABLE {safe_table} SET ("
                    "autovacuum_vacuum_scale_factor = "
                    f"{EXPECTED_VACUUM_SCALE_FACTOR}, "
                    "autovacuum_analyze_scale_factor = "
                    f"{EXPECTED_ANALYZE_SCALE_FACTOR}"
                    ");"
                ),
            ))
            priority += 1

        if not av_enabled:
            solutions.append((
                priority,
                "🔴 فعّل autovacuum عالمياً.",
                (
                    "ALTER SYSTEM SET autovacuum = on; "
                    "SELECT pg_reload_conf();"
                ),
            ))
            priority += 1

        if xmin_candidates:
            candidate = next(
                (c for c in xmin_candidates
                 if c.get("blocks_vacuum") is True),
                xmin_candidates[0],
            )
            pid = _safe_int(candidate.get("pid"))
            solutions.append((
                priority,
                (
                    "🔎 افحص المعاملة المرشحة "
                    f"(pid={pid}) قبل أي إجراء."
                ),
                (
                    "SELECT pid, usename, application_name, "
                    "state, xact_start, backend_xmin, "
                    "backend_xid, query "
                    "FROM pg_stat_activity "
                    f"WHERE pid = {pid};"
                ),
            ))
            priority += 1

            solutions.append((
                priority,
                (
                    "⚠️ لا تنهِ المعاملة إلا بعد "
                    "التأكد من أنها عالقة وآمنة للإلغاء."
                ),
                "",
            ))
            priority += 1

        if idle_tx:
            solutions.append((
                priority,
                "🟠 افحص idle-in-transaction:",
                (
                    "SELECT pid, usename, application_name, "
                    "state, state_change, backend_xmin, query "
                    "FROM pg_stat_activity "
                    "WHERE state = 'idle in transaction' "
                    "ORDER BY state_change;"
                ),
            ))
            priority += 1

        if analyze_mod_pct >= ANALYZE_MOD_WARN_PCT:
            solutions.append((
                priority,
                (
                    "📊 حدّث إحصاءات الجدول: "
                    f"<code>ANALYZE {safe_table_html};</code>"
                ),
                f"ANALYZE {safe_table};",
            ))
            priority += 1

        if naptime is not None and naptime > NAPTIME_WARN_SECONDS:
            solutions.append((
                priority,
                (
                    "⚙️ يمكن تقليل autovacuum_naptime إذا كان "
                    "تأخر بدء autovacuum مشكلة فعلية."
                ),
                (
                    "ALTER SYSTEM SET "
                    "autovacuum_naptime = '60s'; "
                    "SELECT pg_reload_conf();"
                ),
            ))
            priority += 1

        solutions.append((
            priority,
            "📈 أعد القياس بعد انتهاء العملية.",
            (
                "SELECT relname, n_live_tup, n_dead_tup, "
                "last_autovacuum, last_autoanalyze "
                "FROM pg_stat_user_tables "
                f"WHERE relname = {_quote_pg_literal(table)};"
            ),
        ))

        # ─── Expected ───
        expected: List[str] = []

        if active_vacuum:
            expected.append(
                "⏳ لا نحكم على النتيجة قبل انتهاء VACUUM الجاري."
            )
        else:
            expected.append(
                "🧹 المتوقع: انخفاض dead tuples القابلة للتنظيف "
                "بعد VACUUM."
            )
            expected.append(
                "ℹ️ n_dead_tup قد لا يصبح صفراً فوراً؛ "
                "الإحصاءات والعمليات المتزامنة قد تؤثر على الرقم."
            )
            expected.append(
                "💾 VACUUM العادي لا يعني بالضرورة عودة المساحة "
                "لنظام الملفات؛ المساحة قد تصبح متاحة لإعادة "
                "الاستخدام داخل الجدول."
            )

        if is_heavy and not is_tuned:
            expected.append(
                "⚙️ بعد ضبط reloptions: س يبدأ autovacuum عند "
                "threshold أقل من الإعداد الافتراضي."
            )

        if analyze_mod_pct >= ANALYZE_MOD_WARN_PCT:
            expected.append(
                "📊 ANALYZE سيحدّث إحصاءات المخطط ويحسن قرارات "
                "الـ planner عند الحاجة."
            )

        severity_emoji = (
            "🔴" if severity == "critical" else "🟡"
        )

        causes_out.append(RootCause(
            table=table,
            causes=causes_list,
            severity=severity_emoji,
            solutions=solutions,
            expected=expected,
        ))

    causes_out.sort(
        key=lambda item: (
            item.severity != "🔴",
            item.severity != "🟡",
            item.table,
        )
    )

    return causes_out, general_notes


# =============================================================================
# TECHNICAL HEALTH SUMMARY
# =============================================================================

def _calculate_pg_health(
    dead_rows: List[Dict[str, Any]],
    blockers: List[Dict[str, Any]],
    pg_settings: Dict[str, Any],
) -> Dict[str, Any]:
    critical = 0
    warning = 0

    for row in dead_rows:
        severity = _dead_severity(
            _safe_int(row.get("dead_tup")),
            _safe_int(row.get("live_tup")),
        )
        if severity == "critical":
            critical += 1
        elif severity == "warning":
            warning += 1

    long_tx_count = sum(
        1 for item in blockers
        if item.get("type") == "long_transaction"
    )
    idle_count = sum(
        1 for item in blockers
        if item.get("type") == "idle_in_transaction"
    )

    score = 100
    score -= critical * 15
    score -= warning * 5
    score -= long_tx_count * 4
    score -= idle_count * 3

    if not _autovacuum_enabled(pg_settings):
        score -= 30

    score = max(0, min(100, score))

    return {
        "score": score,
        "critical": critical,
        "warning": warning,
        "long_tx": long_tx_count,
        "idle_tx": idle_count,
    }


# =============================================================================
# 🆕 v6.1.0: REPORT BUILDER (chars, not lines)
# =============================================================================

class _ReportBuilder:
    """
    🆕 v6.1.0: باني تقرير يحترم حدّ Telegram (4096 حرف).

    يقيس الأحرف الفعلية (بما فيها newlines) — لا السطور.
    """

    def __init__(
        self,
        max_chars: int = REPORT_MAX_CHARS,
    ):
        self._lines: List[str] = []
        self._total_chars = 0
        self._max_chars = max(1, int(max_chars))

    def add(self, value: str) -> bool:
        """
        يضيف سطراً. يرجع True إذا نُضيف، False إذا تجاهِلناه.
        """
        if value is None:
            return False
        text = str(value)
        # +1 لـ newline عند الدمج
        extra = len(text) + (1 if self._lines else 0)
        if self._total_chars + extra > self._max_chars:
            return False
        self._lines.append(text)
        self._total_chars += extra
        return True

    def add_many(self, values: List[str]) -> int:
        added = 0
        for v in values:
            if self.add(v):
                added += 1
        return added

    def build(self) -> str:
        return "\n".join(self._lines)

    @property
    def char_count(self) -> int:
        return self._total_chars

    @property
    def line_count(self) -> int:
        return len(self._lines)

    def full(self) -> bool:
        return self._total_chars >= self._max_chars


def _split_for_telegram(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> List[str]:
    """
    🆕 v6.1.0: يقسم النص إلى أجزاء آمنة لـ Telegram.

    - يحاول القسمة عند newline قريبة
    - يتفادى كسر HTML tags قدر الإمكان
    """
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]

    parts: List[str] = []
    remaining = text
    safe_limit = max(1, limit - 100)   # هامش أمان

    while len(remaining) > safe_limit:
        # ابحث عن آخر newline قبل الحدّ
        cut = remaining.rfind("\n", 0, safe_limit)
        if cut < safe_limit // 2:
            # لا newline مناسبة → قطع قسري
            cut = safe_limit
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")

    if remaining:
        parts.append(remaining)

    return parts


# =============================================================================
# MAIN DIAGNOSTIC
# =============================================================================

async def _build_diagnose_lines() -> List[str]:
    """
    🆕 v6.1.0: يبني كامل التقرير كقائمة سطور.

    يفصل بناء المحتوى عن إدارة الحدّ (chars / split).
    """
    from database import (
        DB, USE_POSTGRES, USE_MYSQL,
        HEAVY_TABLES_FOR_AUTOVACUUM,
    )

    lines: List[str] = []

    db_type = _db_type()

    # Header
    lines.append(f"🔬 <b>تشخيص قاعدة البيانات v{VERSION}</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🗄️ <b>النوع:</b> <code>{_escape_html(db_type)}</code>")

    try:
        size_kb = await DB.get_db_size_kb()
        lines.append(f"💾 <b>الحجم:</b> {_fmt_size_kb(size_kb)}")
    except Exception as exc:
        logger.debug("get_db_size_kb failed: %s", exc)

    # جمع البيانات
    dead_rows = await _get_dead_tuples()
    per_table = (
        await _get_per_table_autovacuum() if USE_POSTGRES else {}
    )
    blockers = (
        await _get_autovacuum_blockers() if USE_POSTGRES else []
    )
    pg_settings = (
        await _get_pg_settings() if USE_POSTGRES else {}
    )
    sizes = await _get_table_sizes()
    indexes = await _get_indexes(list(_CRITICAL_INDEXES.keys()))

    # PostgreSQL summary
    if USE_POSTGRES:
        health = _calculate_pg_health(dead_rows, blockers, pg_settings)
        lines.append("")
        lines.append("📌 <b>الخلاصة التقنية</b>")
        lines.append(f"  🔴 جداول حرجة: <b>{health['critical']}</b>")
        lines.append(
            f"  🟡 جداول تحتاج انتباه: <b>{health['warning']}</b>"
        )
        lines.append(
            f"  ⚠️ Long transactions: <b>{health['long_tx']}</b>"
        )
        lines.append(
            f"  🟠 Idle transactions: <b>{health['idle_tx']}</b>"
        )
        av_state = (
            "🟢 ON"
            if _autovacuum_enabled(pg_settings)
            else "🔴 OFF"
        )
        lines.append(f"  autovacuum: <b>{av_state}</b>")
        lines.append(
            f"  مؤشر الحالة التقني: <b>{health['score']}/100</b>"
        )

    # Analysis
    causes: List[RootCause] = []
    general_notes: List[str] = []

    if USE_POSTGRES:
        causes, general_notes = await _analyze_root_causes(
            dead_rows, per_table, blockers, pg_settings
        )

    if causes or general_notes:
        lines.append("")
        lines.append("╔══════════════════════════════════╗")
        lines.append("║  🎯 <b>التحليل المنطقي</b>          ║")
        lines.append("╚══════════════════════════════════╝")
        lines.append("")

        for note in general_notes:
            lines.append(note)
            lines.append("")

        confidence_label = {
            "high": "🟢 ثقة عالية",
            "medium": "🟡 ثقة متوسطة",
            "low": "🟠 ثقة منخفضة",
        }

        for cause_group in causes:
            lines.append(
                f"{cause_group.severity} "
                f"<b>جدول: "
                f"<code>{_escape_html(cause_group.table)}</code>"
                f"</b>"
            )

            if cause_group.causes:
                sorted_causes = sorted(
                    cause_group.causes,
                    key=lambda item: (
                        {"high": 0, "medium": 1, "low": 2}
                        .get(item.confidence, 3)
                    ),
                )
                lines.append(
                    f"├─ <b>الأسباب المرشحة "
                    f"({len(cause_group.causes)}):</b>"
                )
                for cause in sorted_causes:
                    label = confidence_label.get(
                        cause.confidence, "?"
                    )
                    lines.append(f"│   {label} — {cause.text}")
                    for evidence in cause.evidence[:3]:
                        lines.append(
                            f"│       • "
                            f"<i>{_escape_html(evidence)}</i>"
                        )

            if cause_group.solutions:
                lines.append("├─ <b>الإجراءات:</b>")
                for priority, title, _sql in cause_group.solutions:
                    icon = (
                        "🟥" if priority == 1
                        else ("🟧" if priority == 2 else "🟨")
                    )
                    lines.append(f"│   {icon} {title}")

            if cause_group.expected:
                lines.append("├─ <b>التوقع بعد الإصلاح:</b>")
                for expected in cause_group.expected:
                    lines.append(f"│   {expected}")

            lines.append("")

    # Full details
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📊 <b>التفاصيل الكاملة</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    # PG dead tuples
    if USE_POSTGRES:
        lines.append("")
        lines.append("<b>1. Dead Tuples + نشاط التنظيف</b>")
        lines.append("")
        shown = 0
        for row in dead_rows:
            name = row.get("table_name") or "?"
            live = _safe_int(row.get("live_tup"))
            dead = _safe_int(row.get("dead_tup"))
            if live == 0 and dead == 0:
                continue
            pct = _dead_pct(dead, live)
            emoji = _dead_emoji(dead, live)
            last_av = _fmt_dt(row.get("last_autovacuum"))
            last_an = _fmt_dt(row.get("last_autoanalyze"))
            lines.append(
                f"{emoji} <code>{_escape_html(name):<18}</code> "
                f"live={live:>7,} dead={dead:>7,} ({pct:.1f}%)"
            )
            lines.append(
                f"     🧹 AV: <code>{last_av}</code> | "
                f"📊 AN: <code>{last_an}</code>"
            )
            shown += 1
            if shown >= 12:
                break
        if shown == 0:
            lines.append("✅ لا توجد بيانات.")

    # Per-table AV
    if USE_POSTGRES and per_table:
        lines.append("")
        lines.append("<b>2. Autovacuum لكل جدول حرج</b>")
        lines.append("")
        for table in HEAVY_TABLES_FOR_AUTOVACUUM:
            info = per_table.get(table, {})
            if not info.get("exists"):
                lines.append(
                    f"❓ <code>{_escape_html(table)}</code> — غير موجود"
                )
                continue
            if info.get("is_tuned"):
                lines.append(
                    f"✅ <code>{_escape_html(table)}</code> — مضبوط "
                    f"({EXPECTED_VACUUM_SCALE_FACTOR}/"
                    f"{EXPECTED_ANALYZE_SCALE_FACTOR})"
                )
            elif info.get("reloptions"):
                summary = ", ".join(
                    f"{key}={value}"
                    for key, value in list(
                        info["reloptions"].items()
                    )[:4]
                )
                lines.append(
                    f"🟡 <code>{_escape_html(table)}</code> — "
                    f"{_escape_html(summary)}"
                )
            else:
                lines.append(
                    f"⚠️ <code>{_escape_html(table)}</code> — "
                    f"القيم الافتراضية"
                )

    # Blockers
    if USE_POSTGRES and blockers:
        lines.append("")
        lines.append("<b>3. نشاط PostgreSQL / Blockers</b>")
        lines.append("")
        for item in blockers:
            kind = item.get("type")
            if kind == "long_transaction":
                xmin = item.get("backend_xmin") or "—"
                lines.append(
                    f"🟡 <b>Long tx</b> "
                    f"pid=<code>{item.get('pid')}</code> "
                    f"عمر={_fmt_duration_seconds(item.get('tx_age_sec'))} "
                    f"xmin=<code>{_escape_html(xmin)}</code>"
                )
            elif kind == "idle_in_transaction":
                lines.append(
                    f"🟠 <b>Idle-in-tx</b> "
                    f"pid=<code>{item.get('pid')}</code> "
                    f"خامل={_fmt_duration_seconds(item.get('idle_sec'))}"
                )
            elif kind == "running_vacuum":
                lines.append(
                    f"🟢 <b>VACUUM</b> على "
                    f"<code>{_escape_html(item.get('table'))}</code> — "
                    f"{_escape_html(item.get('phase'))} "
                    f"({_escape_html(item.get('progress'))})"
                )

    # Sizes
    if sizes:
        lines.append("")
        lines.append("<b>4. أحجام الجداول — Top 10</b>")
        lines.append("")
        for row in sizes[:10]:
            name = row.get("table_name") or "?"
            total = _safe_int(row.get("total_bytes"))
            lines.append(
                f"  <code>{_escape_html(name):<20}</code> "
                f"{_fmt_size_bytes(total)}"
            )

    # Indexes
    lines.append("")
    lines.append("<b>5. الفهارس الحرجة</b>")
    for table, expected_indexes in _CRITICAL_INDEXES.items():
        actual = set(indexes.get(table, []))
        missing = [
            index for index in expected_indexes
            if index not in actual
        ]
        if missing:
            lines.append(
                f"⚠️ <b>{_escape_html(table)}</b> "
                f"({len(actual)}) — مفقود {len(missing)}"
            )
            for missing_index in missing:
                lines.append(
                    f"   ❌ <code>{_escape_html(missing_index)}</code>"
                )
        else:
            lines.append(
                f"✅ <b>{_escape_html(table)}</b> ({len(actual)})"
            )

    # PG settings
    if USE_POSTGRES and pg_settings:
        lines.append("")
        lines.append("<b>6. إعدادات PostgreSQL</b>")
        lines.append("")
        keys = (
            "autovacuum",
            "autovacuum_naptime",
            "autovacuum_vacuum_scale_factor",
            "autovacuum_analyze_scale_factor",
            "autovacuum_vacuum_threshold",
            "autovacuum_analyze_threshold",
            "autovacuum_max_workers",
            "max_connections",
            "shared_buffers",
            "work_mem",
            "synchronous_commit",
            "server_version",
        )
        for key in keys:
            value = pg_settings.get(key)
            if value is None:
                continue
            lines.append(
                f"  <code>{_escape_html(key)} = "
                f"{_escape_html(value)}</code>"
            )

    # MySQL notes
    if USE_MYSQL:
        lines.append("")
        lines.append("<b>7. ملاحظة MySQL</b>")
        lines.append(
            "ℹ️ MySQL لا يستخدم dead tuples بنفس نموذج PostgreSQL؛ "
            "يتم عرض DATA_FREE كإشارة تقريبية للمساحة الحرة/المجزأة."
        )

    # SQLite notes
    if not USE_POSTGRES and not USE_MYSQL:
        lines.append("")
        lines.append("<b>7. ملاحظة SQLite</b>")
        lines.append(
            "ℹ️ SQLite لا يملك autovacuum بنفس نموذج PostgreSQL؛ "
            "VACUUM يعيد بناء قاعدة البيانات."
        )

    # Footer
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("✅ <b>اكتمل التشخيص</b>")

    return lines


async def diagnose_db() -> str:
    """
    🆕 v6.1.0: يعيد تقريراً مقتصراً على REPORT_MAX_CHARS حرف.

    ملاحظة: إذا كان التقرير أطول، سيُقتصر. للحصول على
    التقرير كاملاً مقسّماً، استخدم diagnose_db_split().
    """
    lines = await _build_diagnose_lines()

    builder = _ReportBuilder(max_chars=REPORT_MAX_CHARS)
    for line in lines:
        if not builder.add(line):
            # حاول إضافة سطر التنبيه
            builder.add("")
            builder.add("… <i>(تم اقتصار التقرير للحدّ الأقصى)</i>")
            builder.add(
                "💡 استخدم /db_diag_split للتقرير الكامل."
            )
            break

    return builder.build()


async def diagnose_db_split(
    max_chars_per_part: int = TELEGRAM_MESSAGE_LIMIT,
) -> List[str]:
    """
    🆕 v6.1.0: يعيد قائمة أجزاء جاهزة للإرسال.

    كل جزء < max_chars_per_part (افتراضياً 4096).
    """
    lines = await _build_diagnose_lines()
    full_text = "\n".join(lines)
    return _split_for_telegram(full_text, limit=max_chars_per_part)


# =============================================================================
# VACUUM / OPTIMIZE
# =============================================================================

async def vacuum_analyze_tables() -> str:
    """
    تنظيف الجداول الحرجة.

    PostgreSQL: DB.vacuum(table)
    MySQL:      DB.vacuum(table)
    SQLite:     DB.vacuum(table)
    """
    from database import (
        DB, USE_POSTGRES, USE_MYSQL,
        HEAVY_TABLES_FOR_AUTOVACUUM,
    )

    lines: List[str] = []
    lines.append("🧹 <b>تنظيف قاعدة البيانات</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    if USE_POSTGRES:
        lines.append("🗄️ PostgreSQL — VACUUM")
    elif USE_MYSQL:
        lines.append("🗄️ MySQL — OPTIMIZE/maintenance")
    else:
        lines.append("🗄️ SQLite — VACUUM")
    lines.append("")

    # VACUUM running check
    if USE_POSTGRES:
        try:
            blockers = await _get_autovacuum_blockers()
            running = [
                item for item in blockers
                if item.get("type") == "running_vacuum"
            ]
        except Exception as exc:
            logger.debug("vacuum running check failed: %s", exc)
            running = []

        if running:
            lines.append("⚠️ <b>يوجد VACUUM جارٍ:</b>")
            for item in running:
                lines.append(
                    f"  • <code>"
                    f"{_escape_html(item.get('table'))}"
                    f"</code> — "
                    f"{_escape_html(item.get('phase'))} "
                    f"({_escape_html(item.get('progress'))})"
                )
            lines.append("")
            lines.append("💡 لن نوقف العملية الجارية.")
            lines.append("")

    tables = list(HEAVY_TABLES_FOR_AUTOVACUUM or [])
    if not tables:
        lines.append(
            "ℹ️ لا توجد جداول في HEAVY_TABLES_FOR_AUTOVACUUM."
        )
        return "\n".join(lines)

    results: List[Tuple[str, bool, str]] = []
    for table in tables:
        if not table:
            continue
        try:
            await DB.vacuum(table)
            results.append((table, True, ""))
        except Exception as exc:
            logger.exception("VACUUM failed for %s", table)
            results.append((table, False, str(exc)[:300]))

    success = 0
    failed = 0
    for table, ok, error in results:
        if ok:
            lines.append(f"✅ <code>{_escape_html(table)}</code>")
            success += 1
        else:
            lines.append(
                f"❌ <code>{_escape_html(table)}</code> — "
                f"{_escape_html(error)}"
            )
            failed += 1

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"✅ نجح: <b>{success}</b> | ❌ فشل: <b>{failed}</b>")

    if USE_POSTGRES and success:
        lines.append("")
        lines.append("💡 <b>التحقق:</b>")
        lines.append(
            "شغّل <code>/db_diag</code> بعد انتهاء VACUUM "
            "ثم قارن:"
        )
        lines.append("• <code>n_dead_tup</code>")
        lines.append("• <code>last_autovacuum</code>")
        lines.append("• <code>last_autoanalyze</code>")
        lines.append("• حجم الجدول")
        lines.append("")
        lines.append(
            "ℹ️ لا تتوقع بالضرورة أن يصبح "
            "<code>n_dead_tup</code> صفراً، "
            "ولا تعتبر انخفاضه دليلاً على "
            "انكماش حجم الملف على القرص."
        )

    return "\n".join(lines)


# =============================================================================
# PUBLIC API
# =============================================================================

__all__ = [
    "VERSION",

    "diagnose_db",
    "diagnose_db_split",
    "vacuum_analyze_tables",

    "RootCause",
    "CauseItem",

    "_analyze_root_causes",
    "_detect_xmin_blocker",
    "_detect_xmin_blockers",
    "_get_current_xmin_horizon",

    "_get_per_table_autovacuum",
    "_get_autovacuum_blockers",

    "_get_dead_tuples",
    "_get_table_sizes",
    "_get_indexes",

    "_autovacuum_vacuum_trigger",
    "_autovacuum_analyze_trigger",

    "_check_project_heavy_tables",
    "_split_for_telegram",
    "_ReportBuilder",

    "REPORT_MAX_CHARS",
    "TELEGRAM_MESSAGE_LIMIT",
]