#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
db_diagnostics.py — PostgreSQL/MySQL/SQLite Database Diagnostics
================================================================================
v6.5.0 — MAINTENANCE + QUICK DIAG + WEEKLY REPORT

التحسينات على v6.4.2:
    🆕 diagnose_db_quick      : تقرير صحي مختصر (4 أسطر)
    🆕 preview_maintenance    : معاينة الصيانة (بدون تعديل)
    🆕 run_maintenance        : تنفيذ DELETE + VACUUM بأمان
    🆕 format_maintenance_*   : تنسيق للعرض في تيليجرام

التحسينات الموروثة من v6.4.2:
    ✅ توحيد مصفوفات القيم المقبولة (ACCEPTED_*_SCALE_FACTORS)
    ✅ تحسين _split_for_telegram — هامش ديناميكي آمن
    ✅ عرض n_mod_since_analyze في التفاصيل
    ✅ _get_pg_settings: تحقق من القيم الفارغة
    ✅ استخدام _safe_params في كل مكان

التحسينات الموروثة من v6.4.0:
    🔴 FIX-CRITICAL: تمرير المعاملات كـ tuple دائماً عبر _safe_params
    🆕 fallback ثانٍ لـ _get_indexes
    🆕 _get_per_table_autovacuum مع reason واضح
    🆕 _split_for_telegram آمن لـ HTML
    🆕 MySQL: dead_tup غير مدعوم → تنبيه واضح

الاستخدام:
    from db_diagnostics import (
        diagnose_db, diagnose_db_split, diagnose_db_quick,
        preview_maintenance, run_maintenance,
        format_maintenance_preview, format_maintenance_result,
        vacuum_analyze_tables,
    )
================================================================================
"""

from __future__ import annotations

import logging
import re
import time as _time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


logger = logging.getLogger(__name__)


# =============================================================================
# VERSION
# =============================================================================

VERSION = "6.5.0"


# =============================================================================
# THRESHOLDS
# =============================================================================

DEAD_TUPLE_WARN_PCT = 10.0
DEAD_TUPLE_CRIT_PCT = 20.0

DEAD_TUPLE_WARN_ABS = 1_000
DEAD_TUPLE_CRIT_ABS = 10_000

MIN_TABLE_SIZE_FOR_ALERT = 200

SMALL_TABLE_THRESHOLD = 500
SMALL_TABLE_MIN_DEAD_CRIT = 100
SMALL_TABLE_MIN_DEAD_WARN = 50

ADMIN_LOGS_WARN_ROWS = 10_000
ADMIN_LOGS_CRIT_ROWS = 50_000

LONG_TX_WARN_SECONDS = 300
VERY_LONG_TX_SECONDS = 1800

IDLE_TX_WARN_SECONDS = 120
IDLE_TX_CRIT_SECONDS = 1800

AV_NOT_RUNNING_HOURS = 24
NAPTIME_WARN_SECONDS = 300

ANALYZE_MOD_WARN_PCT = 10.0
ANALYZE_MOD_CRIT_PCT = 20.0

# ═════════════════════════════════════════════════════════════════════
# v6.5.0: قيم autovacuum المقبولة (flexible)
# ═════════════════════════════════════════════════════════════════════

ACCEPTED_VACUUM_SCALE_FACTORS: Set[str] = {
    "0.02",   # database.py (v7.7.x — heavy tables)
    "0.05",   # database_tables.py (manual helper)
    "0",      # aggressive
}

ACCEPTED_ANALYZE_SCALE_FACTORS: Set[str] = {
    "0.01",   # database.py (v7.7.x — heavy tables)
    "0.02",   # database_tables.py (manual helper)
    "0",      # aggressive
}

# للعرض فقط
EXPECTED_VACUUM_SCALE_FACTOR = "0.02"
EXPECTED_ANALYZE_SCALE_FACTOR = "0.01"

# للتوافق الخلفي
EXPECTED_VACUUM_SCALE_FACTORS = ACCEPTED_VACUUM_SCALE_FACTORS
EXPECTED_ANALYZE_SCALE_FACTORS = ACCEPTED_ANALYZE_SCALE_FACTORS

DEFAULT_VACUUM_THRESHOLD = 50
DEFAULT_ANALYZE_THRESHOLD = 50

AVG_ROW_BYTES_ESTIMATE = 200

REPORT_MAX_CHARS = 3800
TELEGRAM_MESSAGE_LIMIT = 4096

REQUIRED_HEAVY_TABLE_USERS = "users"

# 🆕 v6.5.0
MAINTENANCE_MAX_DELETE_PER_TABLE = 100_000
MAINTENANCE_DEFAULT_ADMIN_LOGS_DAYS = 30
MAINTENANCE_DEFAULT_PENALTY_ARCHIVE_DAYS = 90
MAINTENANCE_DEFAULT_USER_VIOLATIONS_DAYS = 90


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
    text: str
    confidence: str = "medium"
    evidence: List[str] = field(default_factory=list)


@dataclass
class RootCause:
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


def _is_significant_table(dead: int, live: int) -> bool:
    total = max(dead, 0) + max(live, 0)
    return total >= MIN_TABLE_SIZE_FOR_ALERT


def _dead_severity(dead: int, live: int) -> str:
    total = max(dead, 0) + max(live, 0)
    if total < MIN_TABLE_SIZE_FOR_ALERT:
        return "ok"

    pct = _dead_pct(dead, live)

    if total < SMALL_TABLE_THRESHOLD:
        if dead >= DEAD_TUPLE_CRIT_ABS:
            return "critical"
        if dead >= SMALL_TABLE_MIN_DEAD_CRIT and pct >= DEAD_TUPLE_CRIT_PCT:
            return "critical"
        if dead >= SMALL_TABLE_MIN_DEAD_WARN and pct >= DEAD_TUPLE_WARN_PCT:
            return "warning"
        return "ok"

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
# PARAMETER SAFETY
# =============================================================================

def _safe_params(*args: Any) -> tuple:
    """
    يضمن أن المعاملات دائماً tuple.

    السبب: Database.fetchall/fetchone/fetchval يستخدمون *p
    داخلياً. تمرير scalar (مثل int) يُسبِّب:
        TypeError: argument after * must be an iterable
    """
    if not args:
        return ()
    if len(args) == 1:
        single = args[0]
        if single is None:
            return ()
        if isinstance(single, tuple):
            return single
        if isinstance(single, (list, set, frozenset)):
            return tuple(single)
        return (single,)
    return tuple(args)


def _build_pg_in_clause(
    items: List[str], start_index: int = 1
) -> Tuple[str, List[str]]:
    """يبني IN ($1, $2, ...) مع placeholders صريحة."""
    if not items:
        return ("NULL", [])
    placeholders = []
    for i, _ in enumerate(items):
        placeholders.append(f"${start_index + i}")
    return (", ".join(placeholders), list(items))


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
    """يُوحِّد القيم الرقمية: '0.020' → '0.02'، '0' → '0'."""
    if value is None:
        return None
    try:
        number = float(str(value).strip())
        if number == 0:
            return "0"
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
                "inserts": 0,
                "updates": 0,
                "deletes": 0,
                "mod_since_analyze": 0,
                "last_vacuum": None,
                "last_autovacuum": None,
                "last_analyze": None,
                "last_autoanalyze": None,
                "vacuum_count": 0,
                "autovacuum_count": 0,
                "analyze_count": 0,
                "autoanalyze_count": 0,
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
                "inserts": 0,
                "updates": 0,
                "deletes": 0,
                "mod_since_analyze": 0,
                "last_vacuum": None,
                "last_autovacuum": None,
                "last_analyze": None,
                "last_autoanalyze": None,
                "vacuum_count": 0,
                "autovacuum_count": 0,
                "analyze_count": 0,
                "autoanalyze_count": 0,
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
# SCHEMA INFO
# =============================================================================

async def _get_schema_info() -> Dict[str, Any]:
    from database import DB, USE_POSTGRES

    info = {
        "current_schema": None,
        "current_schemas": None,
        "search_path": None,
        "database": None,
        "user": None,
        "version": None,
    }

    if not USE_POSTGRES:
        return info

    try:
        info["current_schema"] = await DB.fetchval(
            "SELECT current_schema()"
        )
    except Exception:
        pass

    try:
        schemas_str = await DB.fetchval(
            "SELECT array_to_string(current_schemas(false), ',')"
        )
        if schemas_str:
            info["current_schemas"] = [
                s.strip() for s in str(schemas_str).split(",")
                if s.strip()
            ]
    except Exception:
        pass

    try:
        info["search_path"] = await DB.fetchval("SHOW search_path")
    except Exception:
        pass

    try:
        info["database"] = await DB.fetchval(
            "SELECT current_database()"
        )
    except Exception:
        pass

    try:
        info["user"] = await DB.fetchval("SELECT current_user")
    except Exception:
        pass

    try:
        info["version"] = await DB.fetchval("SHOW server_version")
    except Exception:
        pass

    return info


# =============================================================================
# PER-TABLE AUTOVACUUM
# =============================================================================

def _is_tuned_reloptions(reloptions: Dict[str, str]) -> bool:
    """
    v6.5.0: يعتبر الجدول مضبوطاً إذا كانت قيم scale_factor
    ضمن المجموعة المقبولة.
    """
    vacuum_raw = reloptions.get("autovacuum_vacuum_scale_factor")
    analyze_raw = reloptions.get("autovacuum_analyze_scale_factor")

    if vacuum_raw is None or analyze_raw is None:
        return False

    vacuum_norm = _normalize_factor(vacuum_raw)
    analyze_norm = _normalize_factor(analyze_raw)

    if vacuum_norm is None or analyze_norm is None:
        return False

    return (
        vacuum_norm in ACCEPTED_VACUUM_SCALE_FACTORS
        and analyze_norm in ACCEPTED_ANALYZE_SCALE_FACTORS
    )


async def _get_per_table_autovacuum() -> Dict[str, Dict[str, Any]]:
    """
    v6.5.0: منطق tuned مرن — يقبل 0.02/0.01 و 0.05/0.02 و 0/0.

    reason:
      - "ok"            : موجود ومُحمَّل
      - "not_found"     : لم يُرجعه الاستعلام (غير موجود فعلاً؟)
      - "not_in_schema" : موجود في pg_class لكن خارج current_schemas
      - "query_failed"  : الاستعلامان فشلا
    """
    from database import DB, USE_POSTGRES, HEAVY_TABLES_FOR_AUTOVACUUM

    result: Dict[str, Dict[str, Any]] = {}
    heavy = list(HEAVY_TABLES_FOR_AUTOVACUUM or [])
    for table in heavy:
        result[table] = {
            "reloptions": {},
            "is_tuned": False,
            "exists": False,
            "reason": "not_found",
        }

    if not USE_POSTGRES or not heavy:
        return result

    in_clause, params = _build_pg_in_clause(heavy, 1)

    query = f"""
        SELECT c.relname AS table_name,
               c.reloptions,
               n.nspname AS schema_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname IN ({in_clause})
          AND c.relkind IN ('r', 'p')
          AND n.nspname = ANY(current_schemas(false))
    """

    rows: List[Dict[str, Any]] = []
    primary_failed = False
    try:
        rows = await DB.fetchall(query, tuple(params)) or []
    except Exception as exc:
        primary_failed = True
        logger.warning("_get_per_table_autovacuum primary: %s", exc)

    if not rows:
        try:
            fallback_query = f"""
                SELECT c.relname AS table_name,
                       c.reloptions,
                       n.nspname AS schema_name
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname IN ({in_clause})
                  AND c.relkind IN ('r', 'p')
                  AND n.nspname NOT IN (
                      'pg_catalog', 'information_schema'
                  )
            """
            fallback_rows = await DB.fetchall(
                fallback_query, tuple(params)
            ) or []
            if fallback_rows:
                rows = fallback_rows
        except Exception as exc2:
            logger.warning(
                "_get_per_table_autovacuum fallback: %s", exc2
            )
            if primary_failed:
                for table in heavy:
                    result[table]["reason"] = "query_failed"
                return result

    found_names = set()
    for row in rows or []:
        name = row.get("table_name")
        if not name:
            continue
        found_names.add(name)
        options = _parse_reloptions(row.get("reloptions"))
        tuned = _is_tuned_reloptions(options)
        result[name] = {
            "reloptions": options,
            "is_tuned": tuned,
            "exists": True,
            "reason": "ok",
            "schema": row.get("schema_name"),
        }

    missing = [t for t in heavy if t not in found_names]
    if missing:
        try:
            miss_clause, miss_params = _build_pg_in_clause(
                missing, 1
            )
            exist_rows = await DB.fetchall(
                f"""
                    SELECT c.relname, n.nspname
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relname IN ({miss_clause})
                      AND c.relkind IN ('r', 'p')
                """,
                tuple(miss_params),
            ) or []
            for r in exist_rows:
                nm = r.get("relname")
                if nm in result and not result[nm]["exists"]:
                    result[nm]["reason"] = "not_in_schema"
        except Exception as exc:
            logger.debug("missing-tables probe: %s", exc)

    return result


# =============================================================================
# 4. BLOCKERS
# =============================================================================

async def _get_autovacuum_blockers() -> List[Dict[str, Any]]:
    """
    v6.5.0: جميع الاستدعاءات تستخدم _safe_params لتفادي TypeError.
    """
    from database import DB, USE_POSTGRES

    if not USE_POSTGRES:
        return []

    blockers: List[Dict[str, Any]] = []

    # ── long_transaction ──
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
        """, _safe_params(LONG_TX_WARN_SECONDS))
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
        logger.warning("blockers(long transaction): %s", exc)

    # ── idle_in_transaction ──
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
        """, _safe_params(IDLE_TX_WARN_SECONDS))
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
        logger.warning("blockers(idle transaction): %s", exc)

    # ── running_vacuum ──
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
# XMIN
# =============================================================================

async def _get_current_xmin_horizon() -> Optional[int]:
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

        blocks_vacuum: Optional[bool] = None
        if current_xmin is not None:
            blocks_vacuum = xmin_int < current_xmin

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

    if _is_postgres():
        in_clause, params = _build_pg_in_clause(tables, 1)

        try:
            query = f"""
                SELECT tablename AS table_name,
                       indexname AS index_name
                FROM pg_indexes
                WHERE tablename IN ({in_clause})
                  AND schemaname NOT IN (
                      'pg_catalog', 'information_schema'
                  )
                ORDER BY tablename, indexname
            """
            rows = await DB.fetchall(query, tuple(params))
            for row in rows or []:
                table = row.get("table_name")
                index = row.get("index_name")
                if (table in result and index
                        and index not in result[table]):
                    result[table].append(index)
            if any(result.values()):
                return result
        except Exception as exc:
            logger.warning("_get_indexes (pg_indexes): %s", exc)

        try:
            query = f"""
                SELECT c.relname AS table_name,
                       ic.relname AS index_name
                FROM pg_index i
                JOIN pg_class c ON c.oid = i.indrelid
                JOIN pg_class ic ON ic.oid = i.indexrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname IN ({in_clause})
                  AND n.nspname = ANY(current_schemas(false))
                ORDER BY c.relname, ic.relname
            """
            rows = await DB.fetchall(query, tuple(params))
            for row in rows or []:
                table = row.get("table_name")
                index = row.get("index_name")
                if (table in result and index
                        and index not in result[table]):
                    result[table].append(index)
            if any(result.values()):
                logger.info(
                    "ℹ️ _get_indexes: استُخدم fallback "
                    "(pg_class + pg_index)"
                )
                return result
        except Exception as exc:
            logger.warning("_get_indexes (pg_class fallback): %s", exc)

        return result

    if _is_mysql():
        try:
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
        except Exception as exc:
            logger.warning("_get_indexes mysql: %s", exc)
        return result

    try:
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
        logger.warning("_get_indexes sqlite: %s", exc)

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
            value = await DB.fetchval(f"SHOW {key}")
            if value is not None and str(value).strip():
                settings[key] = value
        except Exception as exc:
            logger.debug("SHOW %s failed: %s", key, exc)
    return settings


def _autovacuum_enabled(settings: Dict[str, Any]) -> bool:
    value = str(settings.get("autovacuum", "on")).strip().lower()
    return value in {"on", "true", "1", "yes"}


# =============================================================================
# THRESHOLD CALCULATION
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
# PROJECT CHECK
# =============================================================================

def _check_project_heavy_tables() -> Optional[str]:
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


def _check_maintenance_consistency() -> Optional[str]:
    try:
        from database_tables import MAINTENANCE_TABLES
        from database import HEAVY_TABLES_FOR_AUTOVACUUM
    except Exception as exc:
        logger.debug("_check_maintenance_consistency: %s", exc)
        return None

    maint = set(MAINTENANCE_TABLES or ())
    heavy = set(HEAVY_TABLES_FOR_AUTOVACUUM or ())

    missing = heavy - maint
    if not missing:
        return None

    missing_str = ", ".join(sorted(missing))
    return (
        "🟡 <b>VACUUM الدوري لا يشمل جداول حرجة:</b> "
        f"<code>{_escape_html(missing_str)}</code>\n"
        "💡 <b>السبب:</b> مفقودة من "
        "<code>MAINTENANCE_TABLES</code> في database_tables.py\n"
        "💡 <b>الأثر:</b> VACUUM (ANALYZE, SKIP_LOCKED) الدوري "
        "لن يعمل عليها — autovacuum وحده يعمل."
    )


async def _check_admin_logs_size() -> Optional[str]:
    from database import DB

    try:
        row_count = _safe_int(
            await DB.fetchval("SELECT COUNT(*) FROM admin_logs",
                              default=0)
        )
    except Exception as exc:
        logger.debug("_check_admin_logs_size: %s", exc)
        return None

    if row_count >= ADMIN_LOGS_CRIT_ROWS:
        return (
            f"🔴 <b>admin_logs كبير جداً:</b> "
            f"{row_count:,} صف\n"
            f"💡 نظّف القديم الآن: "
            f"<code>DELETE FROM admin_logs "
            f"WHERE created_at < NOW() - INTERVAL '30 days';</code>"
        )

    if row_count >= ADMIN_LOGS_WARN_ROWS:
        return (
            f"🟡 <b>admin_logs يحتاج تقليماً:</b> "
            f"{row_count:,} صف\n"
            f"💡 نظّف القديم: "
            f"<code>DELETE FROM admin_logs "
            f"WHERE created_at < NOW() - INTERVAL '60 days';</code>"
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

    if not av_enabled:
        general_notes.append(
            "🔴 <b>autovacuum = OFF</b> — "
            "التنظيف التلقائي معطّل عالمياً."
        )
    else:
        general_notes.append("🟢 <b>autovacuum = ON</b>.")

    sc = str(pg_settings.get("synchronous_commit", "")).strip().lower()
    if sc == "off":
        general_notes.append(
            "ℹ️ <b>synchronous_commit=off</b> — "
            "مقصود من v7.7.36 لتحسين الأداء. لا تعتبره خطأً."
        )
    elif sc == "on":
        general_notes.append(
            "⚠️ <b>synchronous_commit=on</b> — "
            "v7.7.36 يضبطه على off تلقائياً عبر server_settings."
        )

    project_warning = _check_project_heavy_tables()
    if project_warning:
        general_notes.append(project_warning)

    maint_warning = _check_maintenance_consistency()
    if maint_warning:
        general_notes.append(maint_warning)

    admin_logs_warning = await _check_admin_logs_size()
    if admin_logs_warning:
        general_notes.append(admin_logs_warning)

    if naptime is not None and naptime > NAPTIME_WARN_SECONDS:
        general_notes.append(
            "🟡 <b>autovacuum_naptime</b> = "
            f"<code>{_escape_html(pg_settings.get('autovacuum_naptime'))}</code> "
            "وهو أعلى من 5 دقائق."
        )

    if running_vacuum:
        for item in running_vacuum:
            general_notes.append(
                "🟢 VACUUM يعمل الآن على "
                f"<code>{_escape_html(item.get('table'))}</code> "
                f"— {_escape_html(item.get('phase'))} "
                f"({_escape_html(item.get('progress'))})"
            )

    current_xmin = await _get_current_xmin_horizon()
    xmin_candidates = _detect_xmin_blockers(long_tx, current_xmin)

    if xmin_candidates:
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

    for row in dead_rows:
        table = row.get("table_name")
        if not table:
            continue

        live = _safe_int(row.get("live_tup"))
        dead = _safe_int(row.get("dead_tup"))

        if not _is_significant_table(dead, live):
            continue

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

        if xmin_candidates:
            candidate = next(
                (c for c in xmin_candidates
                 if c.get("blocks_vacuum") is True),
                xmin_candidates[0],
            )
            is_real_blocker = candidate.get("blocks_vacuum") is True
            causes_list.append(CauseItem(
                text=(
                    "معاملة طويلة تحجز snapshot قديم "
                    + ("(مثبت)." if is_real_blocker
                       else "(مرشح، غير مثبت).")
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
                "⚙️ بعد ضبط reloptions: سيبدأ autovacuum عند "
                "threshold أقل من الإعداد الافتراضي."
            )

        if analyze_mod_pct >= ANALYZE_MOD_WARN_PCT:
            expected.append(
                "📊 ANALYZE سيحدّث إحصاءات المخطط ويحسن "
                "قرارات الـ planner عند الحاجة."
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
# HEALTH SCORE
# =============================================================================

def _calculate_pg_health(
    dead_rows: List[Dict[str, Any]],
    blockers: List[Dict[str, Any]],
    pg_settings: Dict[str, Any],
) -> Dict[str, Any]:
    critical = 0
    warning = 0
    total_dead = 0
    significant_tables = 0

    for row in dead_rows:
        dead = _safe_int(row.get("dead_tup"))
        live = _safe_int(row.get("live_tup"))

        total_dead += dead

        if not _is_significant_table(dead, live):
            continue

        significant_tables += 1

        severity = _dead_severity(dead, live)
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

    if total_dead >= 50_000:
        score -= 40
    elif total_dead >= 10_000:
        score -= 25
    elif total_dead >= 5_000:
        score -= 15
    elif total_dead >= 1_000:
        score -= 8
    elif total_dead >= 500:
        score -= 3

    score -= critical * 8
    score -= warning * 3

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
        "total_dead": total_dead,
        "significant_tables": significant_tables,
    }


# =============================================================================
# REPORT BUILDER
# =============================================================================

class _ReportBuilder:
    def __init__(self, max_chars: int = REPORT_MAX_CHARS):
        self._lines: List[str] = []
        self._total_chars = 0
        self._max_chars = max(1, int(max_chars))

    def add(self, value: str) -> bool:
        if value is None:
            return False
        text = str(value)
        extra = len(text) + (1 if self._lines else 0)
        if self._total_chars + extra > self._max_chars:
            return False
        self._lines.append(text)
        self._total_chars += extra
        return True

    def build(self) -> str:
        return "\n".join(self._lines)

    @property
    def char_count(self) -> int:
        return self._total_chars

    @property
    def line_count(self) -> int:
        return len(self._lines)


# =============================================================================
# HTML-SAFE SPLIT
# =============================================================================

_HTML_TAG_RE = re.compile(
    r'<(/?)(\w+)((?:\s+[^>]*?)?)(/?)>',
    re.DOTALL,
)

_VOID_HTML_TAGS = frozenset({
    "br", "hr", "img", "input", "meta", "link", "area",
    "base", "col", "embed", "source", "track", "wbr",
})


def _html_tag_name(full_open_tag: str) -> str:
    m = re.match(r'<(\w+)', full_open_tag)
    return m.group(1) if m else ""


def _get_open_html_tags(text: str) -> List[str]:
    stack: List[str] = []
    for m in _HTML_TAG_RE.finditer(text):
        is_closing = bool(m.group(1))
        tag_name_raw = m.group(2)
        tag_name = tag_name_raw.lower()
        attrs = m.group(3) or ""
        self_closing = bool(m.group(4))

        if tag_name in _VOID_HTML_TAGS:
            continue
        if self_closing:
            continue

        full_open = f"<{tag_name_raw}{attrs}>"

        if is_closing:
            for i in range(len(stack) - 1, -1, -1):
                if _html_tag_name(stack[i]).lower() == tag_name:
                    del stack[i:]
                    break
        else:
            stack.append(full_open)
    return stack


def _split_for_telegram(
    text: str,
    limit: int = TELEGRAM_MESSAGE_LIMIT,
) -> List[str]:
    if not text:
        return [""]
    if len(text) <= limit:
        return [text]

    parts: List[str] = []
    remaining = text
    base_margin = 300

    while len(remaining) > limit:
        open_tags_count = len(_get_open_html_tags(remaining[:1000]))
        dynamic_margin = base_margin + (open_tags_count * 30)
        safe_limit = max(1, limit - dynamic_margin)
        if safe_limit >= len(remaining):
            parts.append(remaining)
            break

        cut = remaining.rfind("\n", 0, safe_limit)
        if cut < safe_limit // 2:
            cut = safe_limit

        chunk = remaining[:cut]
        open_tags = _get_open_html_tags(chunk)

        closing = "".join(
            f"</{_html_tag_name(t)}>"
            for t in reversed(open_tags)
        )
        reopening = "".join(open_tags)

        parts.append(chunk.rstrip() + closing)
        remaining = reopening + remaining[cut:].lstrip("\n")

    if remaining:
        parts.append(remaining)

    return parts


# =============================================================================
# MAIN DIAGNOSTIC
# =============================================================================

async def _build_diagnose_lines() -> List[str]:
    from database import (
        DB, USE_POSTGRES, USE_MYSQL,
        HEAVY_TABLES_FOR_AUTOVACUUM,
    )

    lines: List[str] = []

    db_type = _db_type()

    lines.append(f"🔬 <b>تشخيص قاعدة البيانات v{VERSION}</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🗄️ <b>النوع:</b> <code>{_escape_html(db_type)}</code>")

    try:
        size_kb = await DB.get_db_size_kb()
        lines.append(f"💾 <b>الحجم:</b> {_fmt_size_kb(size_kb)}")
    except Exception as exc:
        logger.debug("get_db_size_kb failed: %s", exc)

    if USE_POSTGRES:
        schema_info = await _get_schema_info()
        if schema_info.get("current_schema"):
            lines.append(
                f"📋 <b>Schema:</b> "
                f"<code>{_escape_html(schema_info['current_schema'])}</code>"
            )
        if schema_info.get("current_schemas"):
            schemas_list = ", ".join(
                _escape_html(s) for s in schema_info["current_schemas"]
            )
            lines.append(
                f"📋 <b>Schemas المتاحة:</b> "
                f"<code>{schemas_list}</code>"
            )
        if schema_info.get("database"):
            lines.append(
                f"🗃️ <b>Database:</b> "
                f"<code>{_escape_html(schema_info['database'])}</code>"
            )

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
        lines.append(
            f"  💀 إجمالي dead tuples: "
            f"<b>{health['total_dead']:,}</b>"
        )
        lines.append(
            f"  📊 جداول مهمة: "
            f"<b>{health['significant_tables']}</b>"
        )
        av_state = (
            "🟢 ON"
            if _autovacuum_enabled(pg_settings)
            else "🔴 OFF"
        )
        lines.append(f"  autovacuum: <b>{av_state}</b>")
        lines.append(
            f"  مؤشر الحالة التقني: "
            f"<b>{health['score']}/100</b>"
        )

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

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📊 <b>التفاصيل الكاملة</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

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
            mod_since = _safe_int(row.get("mod_since_analyze"))
            lines.append(
                f"{emoji} <code>{_escape_html(name):<18}</code> "
                f"live={live:>7,} dead={dead:>7,} ({pct:.1f}%)"
            )
            lines.append(
                f"     🧹 AV: <code>{last_av}</code> | "
                f"📊 AN: <code>{last_an}</code> | "
                f"🔄 mod={mod_since:,}"
            )
            shown += 1
            if shown >= 12:
                break
        if shown == 0:
            lines.append("✅ لا توجد بيانات.")

    if USE_POSTGRES and per_table:
        lines.append("")
        lines.append("<b>2. Autovacuum لكل جدول حرج</b>")
        lines.append("")
        for table in HEAVY_TABLES_FOR_AUTOVACUUM:
            info = per_table.get(table, {})
            reason = info.get("reason", "not_found")
            if not info.get("exists"):
                if reason == "query_failed":
                    lines.append(
                        f"🔴 <code>{_escape_html(table)}</code> — "
                        f"<b>فشل الاستعلام</b> (تحقق من الصلاحيات)"
                    )
                elif reason == "not_in_schema":
                    lines.append(
                        f"🟠 <code>{_escape_html(table)}</code> — "
                        f"موجود لكن خارج <code>search_path</code>"
                    )
                else:
                    lines.append(
                        f"❓ <code>{_escape_html(table)}</code> — "
                        f"غير موجود في pg_class"
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
    elif USE_POSTGRES:
        lines.append("")
        lines.append("<b>3. نشاط PostgreSQL / Blockers</b>")
        lines.append("")
        lines.append("✅ لا توجد معاملات طويلة / idle-in-tx / VACUUM جارٍ.")

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

    if USE_MYSQL:
        lines.append("")
        lines.append("<b>7. ملاحظة MySQL</b>")
        lines.append(
            "ℹ️ MySQL لا يستخدم dead tuples بنفس نموذج PostgreSQL؛ "
            "يتم عرض DATA_FREE كإشارة تقريبية للمساحة الحرة/المجزأة."
        )
        lines.append(
            "⚠️ <b>لا تعتمد على هذا التقرير للحكم على صحة MySQL</b> "
            "— DATA_FREE يعني مساحة قابلة لإعادة الاستخدام، وليس "
            "بالضرورة dead tuples."
        )

    if not USE_POSTGRES and not USE_MYSQL:
        lines.append("")
        lines.append("<b>7. ملاحظة SQLite</b>")
        lines.append(
            "ℹ️ SQLite لا يملك autovacuum بنفس نموذج PostgreSQL؛ "
            "VACUUM يعيد بناء قاعدة البيانات."
        )

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("✅ <b>اكتمل التشخيص</b>")

    return lines


async def diagnose_db() -> str:
    lines = await _build_diagnose_lines()

    builder = _ReportBuilder(max_chars=REPORT_MAX_CHARS)
    for line in lines:
        if not builder.add(line):
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
    lines = await _build_diagnose_lines()
    full_text = "\n".join(lines)
    return _split_for_telegram(full_text, limit=max_chars_per_part)


# =============================================================================
# 🆕 v6.5.0: QUICK DIAGNOSTIC
# =============================================================================

async def diagnose_db_quick() -> str:
    """
    🔬 تقرير صحي مختصر — 4 أسطر فقط.
    """
    from database import DB, USE_POSTGRES

    lines: List[str] = []

    try:
        size_kb = await DB.get_db_size_kb()
        size_display = _fmt_size_kb(size_kb)
    except Exception:
        size_display = "?"

    if not USE_POSTGRES:
        return (
            f"🔬 <b>DB Quick</b> | {_escape_html(_db_type())}\n"
            f"📏 الحجم: <b>{size_display}</b>"
        )

    try:
        dead_rows = await _get_dead_tuples()
        blockers = await _get_autovacuum_blockers()
        pg_settings = await _get_pg_settings()
        health = _calculate_pg_health(dead_rows, blockers, pg_settings)
    except Exception as exc:
        logger.warning(f"diagnose_db_quick: {exc}")
        return (
            f"🔬 <b>DB Quick</b> | {_escape_html(_db_type())}\n"
            f"📏 الحجم: <b>{size_display}</b>\n"
            f"⚠️ تعذر جلب الإحصائيات"
        )

    score = health['score']
    if score >= 90:
        score_emoji = "🟢"
    elif score >= 70:
        score_emoji = "🟡"
    else:
        score_emoji = "🔴"

    dead = health['total_dead']
    if dead < 500:
        dead_emoji = "🟢"
    elif dead < 5000:
        dead_emoji = "🟡"
    else:
        dead_emoji = "🔴"

    av_on = _autovacuum_enabled(pg_settings)
    av_emoji = "🟢" if av_on else "🔴"

    blockers_count = (
        health['long_tx'] + health['idle_tx']
    )
    if blockers_count == 0:
        blockers_emoji = "🟢"
    else:
        blockers_emoji = "🟠"

    lines.append(
        f"🔬 <b>DB Health:</b> {score_emoji} "
        f"<b>{score}/100</b>"
    )
    lines.append(
        f"💀 Dead: {dead_emoji} <b>{dead:,}</b> | "
        f"📏 <b>{size_display}</b>"
    )
    lines.append(
        f"🧹 AV: {av_emoji} | "
        f"⚠️ Blockers: {blockers_emoji} <b>{blockers_count}</b>"
    )

    if score >= 90:
        lines.append("✅ لا مشاكل — كل شيء يعمل")
    elif score >= 70:
        lines.append("⚠️ انتباه: راجع /db_diag")
    else:
        lines.append("🔴 يحتاج تدخلاً — شغّل /db_diag")

    return "\n".join(lines)


# =============================================================================
# 🆕 v6.5.0: PREVIEW MAINTENANCE
# =============================================================================

async def preview_maintenance(
    admin_logs_days: int = MAINTENANCE_DEFAULT_ADMIN_LOGS_DAYS,
    penalty_archive_days: int = MAINTENANCE_DEFAULT_PENALTY_ARCHIVE_DAYS,
    user_violations_days: int = MAINTENANCE_DEFAULT_USER_VIOLATIONS_DAYS,
) -> Dict[str, Any]:
    """
    🔍 معاينة عملية الصيانة — بدون أي تعديل.
    """
    from database import (
        DB, USE_POSTGRES, HEAVY_TABLES_FOR_AUTOVACUUM,
    )

    result: Dict[str, Any] = {
        'available': False,
        'db_type': _db_type(),
        'plan': [],
        'vacuum_tables': [],
        'warnings': [],
        'error': None,
    }

    if not USE_POSTGRES:
        result['error'] = (
            "الصيانة التلقائية مدعومة فقط على PostgreSQL حالياً"
        )
        return result

    result['available'] = True

    # فحص VACUUM جارٍ
    try:
        blockers = await _get_autovacuum_blockers()
        running = [
            item for item in blockers
            if item.get("type") == "running_vacuum"
        ]
        if running:
            result['warnings'].append(
                f"⚠️ يوجد VACUUM جارٍ على "
                f"{running[0].get('table')} — سيتم تخطيه"
            )
    except Exception as exc:
        logger.debug(f"preview_maintenance(blockers): {exc}")

    # فحص الجداول المطلوبة
    tables_exist: Set[str] = set()
    try:
        rows = await DB.fetchall("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = ANY(current_schemas(false))
        """)
        for r in rows or []:
            name = r.get('tablename')
            if name:
                tables_exist.add(name)
    except Exception as exc:
        logger.warning(f"preview_maintenance(tables): {exc}")
        result['error'] = f"تعذر جلب قائمة الجداول: {exc}"
        return result

    # بناء خطة الحذف
    delete_plan = [
        ('admin_logs', 'created_at', admin_logs_days),
        ('penalty_archive', 'created_at', penalty_archive_days),
        ('user_violations', 'created_at', user_violations_days),
    ]

    for table, ts_col, days in delete_plan:
        if table not in tables_exist:
            continue

        safe_table = _quote_pg_identifier(table)
        safe_col = _quote_pg_identifier(ts_col)

        try:
            count = await DB.fetchval(
                f"SELECT COUNT(*) FROM {safe_table} "
                f"WHERE {safe_col} < "
                f"NOW() - INTERVAL '{days} days'",
                default=0,
            )
            count = _safe_int(count)
        except Exception as exc:
            logger.debug(f"count {table}: {exc}")
            count = -1

        result['plan'].append({
            'table': table,
            'action': 'DELETE',
            'column': ts_col,
            'days': days,
            'criteria': f"{ts_col} < NOW() - INTERVAL '{days} days'",
            'count': count,
        })

    # VACUUM plan
    result['vacuum_tables'] = [
        t for t in (HEAVY_TABLES_FOR_AUTOVACUUM or [])
        if t and t in tables_exist
    ]

    return result


# =============================================================================
# 🆕 v6.5.0: RUN MAINTENANCE
# =============================================================================

async def run_maintenance(
    *,
    admin_logs_days: int = MAINTENANCE_DEFAULT_ADMIN_LOGS_DAYS,
    penalty_archive_days: int = MAINTENANCE_DEFAULT_PENALTY_ARCHIVE_DAYS,
    user_violations_days: int = MAINTENANCE_DEFAULT_USER_VIOLATIONS_DAYS,
    max_delete_per_table: int = MAINTENANCE_MAX_DELETE_PER_TABLE,
    skip_delete: bool = False,
    skip_vacuum: bool = False,
) -> Dict[str, Any]:
    """
    🧹 تنفيذ الصيانة الكاملة (DELETE + VACUUM) بأمان.
    """
    from database import (
        DB, USE_POSTGRES, HEAVY_TABLES_FOR_AUTOVACUUM,
    )

    t_start = _time.monotonic()

    result: Dict[str, Any] = {
        'success': False,
        'duration_sec': 0.0,
        'deletes': [],
        'vacuum': [],
        'errors': [],
    }

    if not USE_POSTGRES:
        result['errors'].append(
            "الصيانة مدعومة فقط على PostgreSQL حالياً"
        )
        return result

    # ═══ 1) DELETE PHASE ═══
    if not skip_delete:
        delete_plan = [
            ('admin_logs', 'created_at', admin_logs_days),
            ('penalty_archive', 'created_at', penalty_archive_days),
            ('user_violations', 'created_at', user_violations_days),
        ]

        for table, ts_col, days in delete_plan:
            entry = {
                'table': table,
                'deleted': 0,
                'skipped': False,
                'error': None,
            }

            try:
                count = _safe_int(await DB.fetchval(
                    f"SELECT COUNT(*) FROM "
                    f"{_quote_pg_identifier(table)} "
                    f"WHERE {_quote_pg_identifier(ts_col)} < "
                    f"NOW() - INTERVAL '{days} days'",
                    default=0,
                ))
            except Exception as exc:
                entry['error'] = f"count failed: {exc}"
                result['deletes'].append(entry)
                continue

            if count > max_delete_per_table:
                entry['skipped'] = True
                entry['error'] = (
                    f"تخطي: {count:,} > {max_delete_per_table:,} "
                    f"(سقف أمان)"
                )
                result['deletes'].append(entry)
                continue

            if count == 0:
                result['deletes'].append(entry)
                continue

            try:
                async with DB.transaction() as conn:
                    deleted = await DB._execute_with_conn(
                        conn,
                        f"DELETE FROM {_quote_pg_identifier(table)} "
                        f"WHERE {_quote_pg_identifier(ts_col)} < "
                        f"NOW() - INTERVAL '{days} days'",
                    )
                entry['deleted'] = _safe_int(deleted, count)
            except Exception as exc:
                entry['error'] = str(exc)[:200]
                logger.warning(f"delete {table}: {exc}")

            result['deletes'].append(entry)

    # ═══ 2) VACUUM PHASE ═══
    if not skip_vacuum:
        running_tables: Set[str] = set()
        try:
            blockers = await _get_autovacuum_blockers()
            for item in blockers:
                if item.get("type") == "running_vacuum":
                    t = item.get("table")
                    if t:
                        running_tables.add(t)
        except Exception:
            pass

        for table in HEAVY_TABLES_FOR_AUTOVACUUM or []:
            if not table:
                continue

            entry = {
                'table': table,
                'success': False,
                'error': None,
            }

            if table in running_tables:
                entry['error'] = "VACUUM جارٍ — تم تخطيه"
                result['vacuum'].append(entry)
                continue

            try:
                await DB.vacuum(table)
                entry['success'] = True
            except Exception as exc:
                entry['error'] = str(exc)[:200]
                logger.warning(f"vacuum {table}: {exc}")

            result['vacuum'].append(entry)

    result['duration_sec'] = round(_time.monotonic() - t_start, 2)

    # تحديد النجاح
    deletes_ok = all(
        e['error'] is None or e.get('skipped')
        for e in result['deletes']
    )
    vacuum_ok = all(
        e['success'] for e in result['vacuum']
    )
    result['success'] = deletes_ok and vacuum_ok

    return result


# =============================================================================
# 🆕 v6.5.0: MAINTENANCE FORMATTERS
# =============================================================================

def format_maintenance_preview(preview: Dict[str, Any]) -> str:
    """🎨 تنسيق معاينة الصيانة."""
    if not preview.get('available'):
        return (
            "⚠️ <b>الصيانة غير متاحة</b>\n"
            f"<i>{_escape_html(preview.get('error') or '')}</i>"
        )

    lines: List[str] = []
    lines.append("🧹 <b>معاينة الصيانة</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    plan = preview.get('plan', [])
    if plan:
        lines.append("🗑️ <b>الحذف المخطط:</b>")
        total_to_delete = 0
        for item in plan:
            table = item['table']
            count = item['count']
            days = item['days']

            if count < 0:
                icon = "⚠️"
                display = "فشل العدّ"
            elif count == 0:
                icon = "✅"
                display = "لا شيء"
            elif count < 1000:
                icon = "🟢"
                display = f"<b>{count:,}</b> صف"
                total_to_delete += count
            elif count < 10000:
                icon = "🟡"
                display = f"<b>{count:,}</b> صف"
                total_to_delete += count
            else:
                icon = "🟠"
                display = f"<b>{count:,}</b> صف"
                total_to_delete += count

            lines.append(
                f"  {icon} <code>{_escape_html(table):<18}</code> "
                f"(&gt;{days}d): {display}"
            )
        lines.append("")
        lines.append(
            f"📊 <b>الإجمالي:</b> "
            f"<b>{total_to_delete:,}</b> صف سيُحذف"
        )
    else:
        lines.append("ℹ️ لا شيء للحذف.")

    vacuum_tables = preview.get('vacuum_tables', [])
    if vacuum_tables:
        lines.append("")
        lines.append("🧹 <b>VACUUM سيعمل على:</b>")
        for t in vacuum_tables:
            lines.append(f"  • <code>{_escape_html(t)}</code>")

    warnings = preview.get('warnings', [])
    if warnings:
        lines.append("")
        for w in warnings:
            lines.append(w)

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        "لتنفيذ الصيانة، أرسل:\n"
        "<code>/db_maintenance confirm</code>"
    )

    return "\n".join(lines)


def format_maintenance_result(result: Dict[str, Any]) -> str:
    """🎨 تنسيق نتيجة الصيانة."""
    lines: List[str] = []

    if result.get('success'):
        lines.append("✅ <b>اكتملت الصيانة بنجاح</b>")
    else:
        lines.append("⚠️ <b>اكتملت الصيانة (مع تحذيرات)</b>")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append(
        f"⏱️ <b>المدة:</b> {result.get('duration_sec', 0):.2f}s"
    )

    deletes = result.get('deletes', [])
    if deletes:
        lines.append("")
        lines.append("🗑️ <b>الحذف:</b>")
        total_deleted = 0
        for entry in deletes:
            table = entry['table']
            deleted = entry['deleted']
            error = entry.get('error')
            skipped = entry.get('skipped')

            if skipped:
                icon = "⏭️"
                display = f"<i>{_escape_html(error or 'تم تخطيه')}</i>"
            elif error:
                icon = "❌"
                display = f"<i>{_escape_html(error)}</i>"
            elif deleted == 0:
                icon = "✅"
                display = "لا شيء"
            else:
                icon = "🟢"
                display = f"<b>{deleted:,}</b> صف"
                total_deleted += deleted

            lines.append(
                f"  {icon} <code>{_escape_html(table):<18}</code> "
                f"{display}"
            )

        if total_deleted > 0:
            lines.append("")
            lines.append(
                f"📊 <b>إجمالي المحذوف:</b> "
                f"<b>{total_deleted:,}</b> صف"
            )

    vacuum = result.get('vacuum', [])
    if vacuum:
        lines.append("")
        lines.append("🧹 <b>VACUUM:</b>")
        ok_count = 0
        fail_count = 0
        for entry in vacuum:
            table = entry['table']
            if entry['success']:
                icon = "✅"
                ok_count += 1
            else:
                icon = "❌"
                fail_count += 1
            err = entry.get('error') or ""
            suffix = f" — <i>{_escape_html(err)}</i>" if err else ""
            lines.append(
                f"  {icon} <code>{_escape_html(table)}</code>{suffix}"
            )
        lines.append("")
        lines.append(
            f"📊 نجح: <b>{ok_count}</b> | فشل: <b>{fail_count}</b>"
        )

    errors = result.get('errors', [])
    if errors:
        lines.append("")
        lines.append("🚨 <b>أخطاء عامة:</b>")
        for err in errors[:5]:
            lines.append(f"  • {_escape_html(err)}")

    return "\n".join(lines)


# =============================================================================
# VACUUM / OPTIMIZE
# =============================================================================

async def vacuum_analyze_tables() -> str:
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
    # Main diagnostics
    "diagnose_db",
    "diagnose_db_split",
    "diagnose_db_quick",
    # Maintenance
    "preview_maintenance",
    "run_maintenance",
    "format_maintenance_preview",
    "format_maintenance_result",
    # Vacuum
    "vacuum_analyze_tables",
    # Dataclasses
    "RootCause",
    "CauseItem",
    # Internal helpers (للاختبار)
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
    "_check_maintenance_consistency",
    "_check_admin_logs_size",
    "_get_schema_info",
    "_split_for_telegram",
    "_get_open_html_tags",
    "_safe_params",
    "_is_tuned_reloptions",
    "_ReportBuilder",
    "_is_significant_table",
    "_build_pg_in_clause",
    # Constants
    "REPORT_MAX_CHARS",
    "TELEGRAM_MESSAGE_LIMIT",
    "MIN_TABLE_SIZE_FOR_ALERT",
    "SMALL_TABLE_THRESHOLD",
    "SMALL_TABLE_MIN_DEAD_CRIT",
    "SMALL_TABLE_MIN_DEAD_WARN",
    "ADMIN_LOGS_WARN_ROWS",
    "ADMIN_LOGS_CRIT_ROWS",
    "ACCEPTED_VACUUM_SCALE_FACTORS",
    "ACCEPTED_ANALYZE_SCALE_FACTORS",
    "EXPECTED_VACUUM_SCALE_FACTOR",
    "EXPECTED_ANALYZE_SCALE_FACTOR",
    "EXPECTED_VACUUM_SCALE_FACTORS",
    "EXPECTED_ANALYZE_SCALE_FACTORS",
    "MAINTENANCE_MAX_DELETE_PER_TABLE",
    "MAINTENANCE_DEFAULT_ADMIN_LOGS_DAYS",
    "MAINTENANCE_DEFAULT_PENALTY_ARCHIVE_DAYS",
    "MAINTENANCE_DEFAULT_USER_VIOLATIONS_DAYS",
]