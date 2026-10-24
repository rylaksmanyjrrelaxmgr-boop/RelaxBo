#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_diagnostics.py — واجهة تشخيص وصيانة قاعدة البيانات 
(v7.3.1 — AUTOVACUUM-AGGRESSIVE-MANAGED)
================================================================================
🆕 v7.3.1 — AUTOVACUUM-AGGRESSIVE-MANAGED:

    🟢 FIX-AV-1: ضبط autovacuum أكثر عدوانية لجداول managed_*:
        • managed_bot_users: كان scale=0.02 + threshold=20 (يفعّل عند 41 dead)
          الآن: scale=0.0 + threshold=10 (يفعّل عند 10 dead فقط).
        • managed_bot_keywords, managed_bot_keyword_replied, managed_bots: نفس التعديل.
        • السبب: هذه الجداول عالية churn (كل رسالة = UPDATE).
          AV السابق لم يلحق بالسرعة (316 dead في 27 دقيقة).
        • النتيجة: dead tuples تبقى < 30 دائماً.

    ✅ محفوظ من v7.3.0:
        MERGE-1 (error detection from db_inspect) + MERGE-2 (new API)
    ✅ محفوظ من v7.2.25:
        FIX-25-1..7 + AUTO-TUNING + CLEANUP-VISIBILITY
================================================================================
"""

import os
import ssl
import time
import socket
import asyncio
import logging
import tempfile
import statistics
import html as _html
import hashlib
import copy as _copy
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
# الإصدار + Startup grace
# ═══════════════════════════════════════════════════════════════════════

VERSION = "7.3.1"


def _compute_process_start_monotonic() -> float:
    try:
        import psutil  # type: ignore
        created = psutil.Process().create_time()
        return time.monotonic() - (time.time() - created)
    except Exception:
        try:
            with open("/proc/self/stat", "r") as f:
                fields = f.read().split()
            starttime_ticks = int(fields[21])
            hz = os.sysconf(os.sysconf_names.get("SC_CLK_TCK", 100))
            uptime_sys = float(open("/proc/uptime").read().split()[0])
            process_age = uptime_sys - (starttime_ticks / float(hz))
            return time.monotonic() - process_age
        except Exception:
            return time.monotonic()


_PROCESS_IMPORT_TS: float = _compute_process_start_monotonic()
_PROCESS_START_TS: float = 0.0
_STARTUP_GRACE_SEC = 60.0


def mark_process_start() -> None:
    global _PROCESS_START_TS
    _PROCESS_START_TS = time.monotonic()


def _uptime_sec() -> float:
    base = _PROCESS_START_TS if _PROCESS_START_TS > 0 else _PROCESS_IMPORT_TS
    return max(0.0, time.monotonic() - base)


# ═══════════════════════════════════════════════════════════════════════
# نظام كشف الأخطاء (من db_inspect.py)
# ═══════════════════════════════════════════════════════════════════════

_ERRORS: List[Tuple[str, str]] = []
_WARNINGS: List[Tuple[str, str]] = []
_INFOS: List[Tuple[str, str]] = []


def _err(msg: str) -> None:
    _ERRORS.append(("ERROR", msg))


def _warn(msg: str) -> None:
    _WARNINGS.append(("WARN", msg))


def _info(msg: str) -> None:
    _INFOS.append(("INFO", msg))


def _clear_findings() -> None:
    _ERRORS.clear()
    _WARNINGS.clear()
    _INFOS.clear()


def _get_findings() -> Dict[str, List[Tuple[str, str]]]:
    return {
        "errors": list(_ERRORS),
        "warnings": list(_WARNINGS),
        "infos": list(_INFOS),
    }


_MIN_DEAD_FOR_CRITICAL = 50
_MIN_DEAD_FOR_COLOR = 10

_LONG_TX_THRESHOLD_SECONDS = int(
    os.getenv("LONG_TX_THRESHOLD_SECONDS", "300"))

_TELEGRAM_PROBE_CACHE_TTL = 300.0
_CONN_CLOSE_TIMEOUT = 2.0
_NEGATIVE_CACHE_TTL = 5.0
_FULL_HEALTH_TTL_NORMAL = 120.0
_FULL_HEALTH_TTL_STARTUP = 10.0

_RTT_SAME_REGION_HIGH = 15.0
_RTT_SAME_REGION_MEDIUM = 50.0
_RTT_CROSS_REGION_MIN = 150.0

_NET_DB_RTT_LOW_SAME_DC = 5.0
_NET_DB_RTT_LOW_SAME_REGION = 15.0
_NET_DB_RTT_MEDIUM = 50.0
_NET_DB_RTT_HIGH = 150.0

_INTERNAL_DB_LOW = 5.0
_INTERNAL_DB_MEDIUM = 20.0
_INTERNAL_DB_HIGH = 100.0

_DB_OWNED_TABLES: frozenset = frozenset({
    "posts", "subscriptions", "user_penalties", "users",
    "plans", "settings", "user_reminder_settings",
    "group_security", "user_points", "user_violations",
    "auto_replies", "bot_groups", "anonymous_admins",
    "user_warnings", "referral_rewards", "group_admins",
    "hidden_owner_groups", "hidden_admins", "user_groups_link",
    "auto_reply_settings", "last_publish", "schedule",
    "support_tickets", "bot_admins", "chat_locks", "group_rules",
})

_REQUIRED_TABLES = (
    "users", "user_channels", "posts", "plans", "subscriptions",
    "invoices", "payment_logs", "settings", "bot_groups",
    "banned_words", "auto_replies", "user_penalties",
    "schedule", "last_publish",
)

_OPTIONAL_TABLES = (
    "bot_admins", "group_admins", "user_warnings", "user_violations",
    "user_points", "referrals", "referral_rewards",
    "contests", "contest_participants", "contest_winners",
    "gift_codes", "support_tickets", "admin_logs",
    "user_reminder_settings", "user_groups_link",
    # 🆕 استبدل keywords/bots/keyword_replied بالأسماء الفعلية
    "managed_bots", "managed_bot_keywords", "managed_bot_keyword_replied",
    "managed_bot_users",
    "user_messages", "group_security", "chat_locks", "group_rules",
)


# ═══════════════════════════════════════════════════════════════════════
# Multi-DB Discovery
# ═══════════════════════════════════════════════════════════════════════

_DB_URL_ENV_VARS: Tuple[Tuple[str, str], ...] = (
    ("DATABASE_URL",     "postgres"),
    ("TIMESCALE_URL",    "postgres"),
    ("POSTGRES_URL",     "postgres"),
    ("POSTGRESQL_URL",   "postgres"),
    ("PG_URL",           "postgres"),
    ("POSTGRES_URI",     "postgres"),
    ("TIMESCALE_URI",    "postgres"),
    ("PG_URI",           "postgres"),
    ("MYSQL_URL",        "mysql"),
    ("MARIADB_URL",      "mysql"),
    ("MYSQL_URI",        "mysql"),
    ("MARIADB_URI",      "mysql"),
    ("DB_URL",           "unknown"),
    ("DATABASE_URI",     "unknown"),
    ("DB_URI",           "unknown"),
    ("SQLALCHEMY_DATABASE_URL", "unknown"),
)

_SQLITE_PATH_VARS: Tuple[str, ...] = (
    "SQLITE_PATH", "SQLITE_DB", "SQLITE_FILE",
    "SQLITE_DATABASE", "DB_PATH",
)

_DB_URL_PRIORITY: Tuple[str, ...] = (
    "DATABASE_URL", "TIMESCALE_URL", "POSTGRES_URL",
    "POSTGRESQL_URL", "PG_URL", "MYSQL_URL", "MARIADB_URL",
    "DB_URL", "DATABASE_URI",
)

_CLOUD_ENV_KEYS: Dict[str, str] = {
    "RENDER_SERVICE_ID":        "render",
    "RENDER":                   "render",
    "FLY_APP_NAME":             "fly",
    "HEROKU_APP_NAME":          "heroku",
    "RAILWAY_ENVIRONMENT":      "railway",
    "DYNO":                     "heroku",
    "K_SERVICE":                "gcp_cloudrun",
    "AWS_LAMBDA_FUNCTION_NAME": "aws_lambda",
    "VERCEL":                   "vercel",
    "NETLIFY":                  "netlify",
}

_RENDER_REGION_ENV_VARS = (
    "RENDER_SERVICE_REGION",
    "RENDER_REGION_NAME",
    "RENDER_REGION_ID",
    "RENDER_APP_REGION",
    "RENDER_REGION",
    "RENDER_DATACENTER",
)

_RENDER_REGION_CODES = {
    "oregon":       "us-west-2",
    "ohio":         "us-east-2",
    "virginia":     "us-east-1",
    "frankfurt":    "eu-central-1",
    "singapore":    "ap-southeast-1",
}

_TIMESCALE_REGION_MAP: Dict[str, str] = {}

_AIVEN_REGION_HINTS = {
    "europe":    "eu-central-1",
    "frankfurt": "eu-central-1",
    "virginia":  "us-east-1",
    "oregon":    "us-west-2",
    "singapore": "ap-southeast-1",
    "sydney":    "ap-southeast-2",
}

# ═══════════════════════════════════════════════════════════════════════
# Cache
# ═══════════════════════════════════════════════════════════════════════

_CACHE: Dict[str, Dict[str, Any]] = {}

_CACHE_TTL: Dict[str, float] = {
    "all_tables_health": 60.0,
    "all_table_names":   300.0,
    "db_metadata":       300.0,
    "pg_settings":       600.0,
    "table_sizes":       300.0,
    "indexes":           300.0,
    "latency_probe":     120.0,
    "full_health":       _FULL_HEALTH_TTL_NORMAL,
    "telegram_network":  _TELEGRAM_PROBE_CACHE_TTL,
    "region_info":       3600.0,
    "multi_db":          60.0,
    "activity_stats":    5.0,
    "autovacuum_tuning": 600.0,
}


def _cache_get(key: str) -> Optional[Any]:
    entry = _CACHE.get(key)
    if not entry:
        return None
    ttl = entry.get("ttl", 60.0)
    if (time.monotonic() - entry["ts"]) >= ttl:
        _CACHE.pop(key, None)
        return None
    data = entry["data"]
    if isinstance(data, (dict, list, tuple)):
        try:
            return _copy.deepcopy(data)
        except Exception:
            return data
    return data


def _cache_set(key: str, data: Any, ttl: Optional[float] = None) -> None:
    _CACHE[key] = {
        "ts": time.monotonic(),
        "data": data,
        "ttl": ttl if ttl is not None else _CACHE_TTL.get(key, 60.0),
    }


def _invalidate_cache(key: Optional[str] = None) -> None:
    if key is None:
        _CACHE.clear()
    else:
        _CACHE.pop(key, None)


def get_cache_stats() -> Dict[str, Any]:
    now = time.monotonic()
    out: Dict[str, Any] = {"entries": {}, "total_keys": 0}
    for k, v in _CACHE.items():
        age = now - v["ts"]
        ttl = v.get("ttl", 60.0)
        out["entries"][k] = {
            "age_sec": round(age, 2),
            "ttl_sec": ttl,
            "expires_in_sec": round(max(0.0, ttl - age), 2),
            "is_valid": age < ttl,
        }
        out["total_keys"] += 1
    return out


# ═══════════════════════════════════════════════════════════════════════
# سياسة التنظيف
# ═══════════════════════════════════════════════════════════════════════

_CLEANUP_POLICY: Dict[str, Dict[str, Any]] = {
    "admin_logs":        {"date_column": "created_at", "retention": 30,  "max_mb": 20, "extra_where": None},
    "payment_logs":      {"date_column": "created_at", "retention": 90,  "max_mb": 20, "extra_where": None},
    "bot_addition_log":  {"date_column": "added_at",   "retention": 90,  "max_mb": 20, "extra_where": None},
    "sentiment_history": {"date_column": "created_at", "retention": 90,  "max_mb": 20, "extra_where": None},
    "user_messages": {
        "date_column": "message_time", "retention": 30, "max_mb": 20,
        "extra_where": "user_id NOT IN (SELECT user_id FROM subscriptions WHERE status = 'active')",
    },
    "penalty_archive":   {"date_column": "created_at", "retention": 90,  "max_mb": 20, "extra_where": None},
    "user_violations": {
        "date_column": "last_violation_time", "retention": 180, "max_mb": 20,
        "extra_where": "user_id NOT IN (SELECT user_id FROM subscriptions WHERE status = 'active')",
    },
    "users":             {"protected": True},
    "subscriptions":     {"protected": True},
    "user_penalties":    {"protected": True},
    "user_warnings":     {"protected": True},
    "user_points":       {"protected": True},
    "referrals":         {"protected": True},
    "referral_rewards":  {"protected": True},
    "support_tickets":   {"protected": True},
    "scheduled_posts":   {"protected": True},
    "banned_words":      {"protected": True},
    "posts":             {"protected": True},
    "bot_groups":        {"protected": True},
    "user_channels":     {"protected": True},
    "plans":             {"protected": True},
}

_CLEANUP_TABLES = tuple(k for k, v in _CLEANUP_POLICY.items() if not v.get("protected"))
_CLEANUP_THRESHOLD_KB = 20 * 1024

# ═══════════════════════════════════════════════════════════════════════
# Lazy imports
# ═══════════════════════════════════════════════════════════════════════

_DB_IMPORT_ERROR: Optional[str] = None


def _get_db():
    global _DB_IMPORT_ERROR
    try:
        from database import DB
        return DB
    except Exception as e:
        if _DB_IMPORT_ERROR is None:
            _DB_IMPORT_ERROR = f"{type(e).__name__}: {e}"
            logger.error(f"❌ db_diagnostics: فشل استيراد DB: {_DB_IMPORT_ERROR}")
        return None


def _now_iso() -> str:
    try:
        from utils import TimeUtils
        return TimeUtils.mecca_iso()[:19]
    except Exception:
        pass
    try:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "?"


def _get_db_type() -> str:
    db = _get_db()
    if db is not None:
        return str(getattr(db, "DB_TYPE", "sqlite")).upper()
    return "UNKNOWN"


def _is_postgres() -> bool:
    db = _get_db()
    return db is not None and bool(getattr(db, "USE_POSTGRES", False))


def _is_mysql() -> bool:
    db = _get_db()
    return db is not None and bool(getattr(db, "USE_MYSQL", False))


# ═══════════════════════════════════════════════════════════════════════
# أدوات مساعدة
# ═══════════════════════════════════════════════════════════════════════

def _safe_escape(text: Any) -> str:
    try:
        return _html.escape(str(text)) if text is not None else ""
    except Exception:
        return ""


_esc = _safe_escape


def _fmt_num(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_bytes(num: Any) -> str:
    try:
        b = float(num or 0)
    except (TypeError, ValueError):
        return "0 B"
    if b < 1024:
        return f"{int(b)} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.2f} MB"
    return f"{b / (1024 * 1024 * 1024):.2f} GB"


def _fmt_ts(ts: Any) -> str:
    if not ts:
        return "—"
    try:
        s = str(ts)
        return s[:16] if len(s) >= 16 else s
    except Exception:
        return "—"


def _dead_color(dead: int, live: int) -> str:
    if dead < _MIN_DEAD_FOR_COLOR:
        return "✅"
    total = live + dead
    if total == 0:
        return "⚪"
    ratio = dead / total
    if live < 1000 and ratio < 0.20:
        return "✅"
    if ratio < 0.05:
        return "✅"
    if ratio < 0.10:
        return "🟡"
    if ratio < 0.20:
        return "🟠"
    return "🔴"


def _hash_key(prefix: str, items: Any) -> str:
    try:
        if isinstance(items, (list, tuple, set)):
            payload = ",".join(sorted(str(x) for x in items))
        else:
            payload = str(items)
        h = hashlib.md5(payload.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"{prefix}_{h}"
    except Exception:
        return f"{prefix}_fallback"


def _percentile(sorted_vals: List[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    try:
        idx = int(round(pct * (len(sorted_vals) - 1)))
        idx = max(0, min(idx, len(sorted_vals) - 1))
        return float(sorted_vals[idx])
    except Exception:
        return float(sorted_vals[0])


def _ph(n: int = 1) -> str:
    if _is_postgres():
        return f"${n}"
    if _is_mysql():
        return "%s"
    return "?"


async def _check_table_exists(db, table: str) -> bool:
    if db is None:
        return False
    try:
        db_type = _get_db_type()
        if db_type == "POSTGRES":
            return bool(await db.fetchval(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = $1",
                (table,)))
        elif db_type == "MYSQL":
            return bool(await db.fetchval(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = %s",
                (table,)))
        else:
            return bool(await db.fetchval(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name=?",
                (table,)))
    except Exception:
        return False


async def _check_column_exists(db, table: str, column: str) -> bool:
    if db is None:
        return False
    try:
        db_type = _get_db_type()
        if db_type == "POSTGRES":
            return bool(await db.fetchval(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = $1 AND column_name = $2",
                (table, column)))
        elif db_type == "MYSQL":
            return bool(await db.fetchval(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = %s "
                "AND table_schema = DATABASE()",
                (table, column)))
        else:
            rows = await db.fetchall(f"PRAGMA table_info({table})")
            return any(r.get("name") == column for r in (rows or []))
    except Exception:
        return False


async def _safe_count(db, sql: str, params: tuple = ()) -> int:
    if db is None:
        return 0
    try:
        val = await db.fetchval(sql, params)
        return int(val or 0)
    except Exception:
        return 0


async def _safe_fetch(db, sql: str, params: tuple = ()) -> List[dict]:
    if db is None:
        return []
    try:
        return await db.fetchall(sql, params) or []
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════
# دوال الفحص الشامل
# ═══════════════════════════════════════════════════════════════════════

async def _inspect_schema_integrity(db) -> None:
    for t in _REQUIRED_TABLES:
        if not await _check_table_exists(db, t):
            _err(f"جدول حرج مفقود: {t}")
    missing_opt = []
    for t in _OPTIONAL_TABLES:
        if not await _check_table_exists(db, t):
            missing_opt.append(t)
    if missing_opt:
        _warn(
            f"جداول اختيارية مفقودة ({len(missing_opt)}): "
            f"{', '.join(missing_opt[:6])}"
            f"{'...' if len(missing_opt) > 6 else ''}"
        )


async def _inspect_users_anomalies(db) -> None:
    if not await _check_table_exists(db, "users"):
        return

    bad_ids = await _safe_count(
        db, "SELECT COUNT(*) FROM users "
            "WHERE user_id IS NULL OR user_id = 0")
    if bad_ids > 0:
        _err(f"{bad_ids} مستخدم بـ user_id غير صالح (NULL أو 0)")

    if await _check_table_exists(db, "subscriptions"):
        if _is_postgres():
            banned_active = await _safe_count(
                db,
                "SELECT COUNT(DISTINCT u.user_id) FROM users u "
                "JOIN subscriptions s ON u.user_id = s.user_id "
                "WHERE u.banned = 1 AND s.status = 'active' "
                "AND s.end_date > NOW()")
        else:
            banned_active = await _safe_count(
                db,
                "SELECT COUNT(DISTINCT u.user_id) FROM users u "
                "JOIN subscriptions s ON u.user_id = s.user_id "
                "WHERE u.banned = 1 AND s.status = 'active' "
                "AND s.end_date > datetime('now')")
        if banned_active > 0:
            _warn(
                f"{banned_active} مستخدم محظور لديه اشتراك نشط "
                f"(تناقض منطقي)")

    if await _check_column_exists(db, "users", "subscription_end"):
        if _is_postgres():
            inconsistent = await _safe_count(
                db,
                "SELECT COUNT(*) FROM users u "
                "WHERE u.subscription_end IS NOT NULL "
                "AND u.subscription_end > NOW() "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM subscriptions s "
                "  WHERE s.user_id = u.user_id "
                "  AND s.status = 'active' "
                "  AND s.end_date > NOW()"
                ")")
        else:
            inconsistent = await _safe_count(
                db,
                "SELECT COUNT(*) FROM users u "
                "WHERE u.subscription_end IS NOT NULL "
                "AND u.subscription_end > datetime('now') "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM subscriptions s "
                "  WHERE s.user_id = u.user_id "
                "  AND s.status = 'active' "
                "  AND s.end_date > datetime('now')"
                ")")
        if inconsistent > 0:
            _warn(
                f"{inconsistent} مستخدم subscription_end في المستقبل "
                f"لكن لا اشتراك نشط (تناقض)")

    if await _check_column_exists(db, "users", "username"):
        dups = await _safe_fetch(
            db,
            "SELECT username, COUNT(*) as cnt FROM users "
            "WHERE username IS NOT NULL AND username != '' "
            "GROUP BY username HAVING COUNT(*) > 1 LIMIT 5")
        if dups:
            _warn(
                f"يوجد {len(dups)} username مكرر "
                f"(قد يكون طبيعياً إذا تغيّر أصحابها)")


async def _inspect_plans_anomalies(db) -> None:
    if not await _check_table_exists(db, "plans"):
        return

    bad_price = await _safe_count(
        db,
        "SELECT COUNT(*) FROM plans "
        "WHERE price IS NULL OR price < 0")
    if bad_price > 0:
        _err(f"{bad_price} باقة بسعر NULL أو سالب")

    bad_dur = await _safe_count(
        db,
        "SELECT COUNT(*) FROM plans "
        "WHERE duration_days IS NULL OR duration_days <= 0")
    if bad_dur > 0:
        _err(f"{bad_dur} باقة بمدة غير صالحة")

    active_count = await _safe_count(
        db,
        "SELECT COUNT(*) FROM plans "
        "WHERE is_active = 1 AND is_gift = 0")
    if active_count == 0:
        _err("لا توجد باقات نشطة (غير هدية) — "
             "المستخدمون لن يستطيعوا الشراء!")

    conflicts = await _safe_fetch(
        db,
        "SELECT duration_days, COUNT(*) as cnt "
        "FROM plans WHERE is_active = 1 AND is_gift = 0 "
        "GROUP BY duration_days HAVING COUNT(*) > 1")
    if conflicts:
        for c in conflicts:
            dur = c.get("duration_days")
            cnt = c.get("cnt")
            _warn(
                f"تعارض: {cnt} باقات بنفس المدة ({dur} يوم) — "
                f"قد يسبب اختيار باقة خاطئة")

    zero_trial = await _safe_fetch(
        db,
        "SELECT id, name FROM plans "
        "WHERE duration_days = 30 AND price = 0 AND is_active = 1 "
        "AND is_gift = 0")
    if len(zero_trial) > 1:
        _warn(
            f"{len(zero_trial)} باقات تجريبية (30 يوم بسعر 0) — "
            f"قد تسبب اختيار خاطئ")


async def _inspect_subscriptions_anomalies(db) -> None:
    if not await _check_table_exists(db, "subscriptions"):
        return

    if _is_postgres():
        past_active = await _safe_count(
            db,
            "SELECT COUNT(*) FROM subscriptions "
            "WHERE status = 'active' AND end_date < NOW()")
    else:
        past_active = await _safe_count(
            db,
            "SELECT COUNT(*) FROM subscriptions "
            "WHERE status = 'active' AND end_date < datetime('now')")
    if past_active > 0:
        _err(
            f"{past_active} اشتراك 'active' لكن end_date في الماضي "
            f"(تناقض — يحتاج expire_expired_subscriptions)")

    null_end = await _safe_count(
        db,
        "SELECT COUNT(*) FROM subscriptions WHERE end_date IS NULL")
    if null_end > 0:
        _err(f"{null_end} اشتراك بـ end_date = NULL")

    bad_dates = await _safe_count(
        db,
        "SELECT COUNT(*) FROM subscriptions "
        "WHERE start_date IS NOT NULL AND end_date IS NOT NULL "
        "AND start_date > end_date")
    if bad_dates > 0:
        _err(f"{bad_dates} اشتراك تاريخ بدايته بعد نهايته (تناقض)")

    orphan_user = await _safe_count(
        db,
        "SELECT COUNT(*) FROM subscriptions s "
        "WHERE NOT EXISTS (SELECT 1 FROM users u "
        "WHERE u.user_id = s.user_id)")
    if orphan_user > 0:
        _err(f"{orphan_user} اشتراك لمستخدم غير موجود (orphan FK)")

    orphan_plan = await _safe_count(
        db,
        "SELECT COUNT(*) FROM subscriptions s "
        "WHERE NOT EXISTS (SELECT 1 FROM plans p "
        "WHERE p.id = s.plan_id)")
    if orphan_plan > 0:
        _err(f"{orphan_plan} اشتراك لباقة غير موجودة (orphan FK)")


async def _inspect_channels_anomalies(db) -> None:
    if not await _check_table_exists(db, "user_channels"):
        return

    orphan = await _safe_count(
        db,
        "SELECT COUNT(*) FROM user_channels uc "
        "WHERE NOT EXISTS (SELECT 1 FROM users u "
        "WHERE u.user_id = uc.user_id)")
    if orphan > 0:
        _err(f"{orphan} قناة لمستخدم غير موجود (orphan FK)")

    if await _check_column_exists(db, "users", "active_channel"):
        bad_active = await _safe_count(
            db,
            "SELECT COUNT(*) FROM users u "
            "JOIN user_channels uc ON u.active_channel = uc.id "
            "WHERE uc.banned = 1")
        if bad_active > 0:
            _warn(
                f"{bad_active} مستخدم active_channel يشير لقناة محظورة")

    if await _check_table_exists(db, "posts"):
        orphan_posts = await _safe_count(
            db,
            "SELECT COUNT(*) FROM posts p "
            "WHERE NOT EXISTS (SELECT 1 FROM user_channels uc "
            "WHERE uc.id = p.channel_db_id)")
        if orphan_posts > 0:
            _err(
                f"{orphan_posts} منشور لقناة غير موجودة (orphan FK)")

        fail_high = await _safe_count(
            db,
            "SELECT COUNT(*) FROM posts "
            "WHERE fail_count >= 3 AND published = 0")
        if fail_high > 0:
            _warn(
                f"{fail_high} منشور فشل 3 مرات+ (لن يُنشر تلقائياً)")


async def _inspect_managed_bots_anomalies(db) -> None:
    if not await _check_table_exists(db, "managed_bots"):
        if not await _check_table_exists(db, "bots"):
            return

    if not await _check_table_exists(db, "managed_bot_keywords"):
        if not await _check_table_exists(db, "keywords"):
            return

    kws_table = "managed_bot_keywords" if await _check_table_exists(
        db, "managed_bot_keywords") else "keywords"
    bots_table = "managed_bots" if await _check_table_exists(
        db, "managed_bots") else "bots"

    orphan = await _safe_count(
        db,
        f"SELECT COUNT(*) FROM {kws_table} k "
        f"WHERE NOT EXISTS (SELECT 1 FROM {bots_table} b WHERE b.id = k.bot_id)")
    if orphan > 0:
        _err(f"{orphan} كلمة لبوت غير موجود (orphan FK)")

    empty_kw = await _safe_count(
        db,
        f"SELECT COUNT(*) FROM {kws_table} "
        "WHERE keyword IS NULL OR TRIM(keyword) = ''")
    if empty_kw > 0:
        _err(f"{empty_kw} كلمة مفتاحية فارغة")

    empty_reply = await _safe_count(
        db,
        f"SELECT COUNT(*) FROM {kws_table} "
        "WHERE reply IS NULL OR TRIM(reply) = ''")
    if empty_reply > 0:
        _warn(f"{empty_reply} كلمة مفتاحية برد فارغ")

    bots = await _safe_fetch(
        db, f"SELECT id, username FROM {bots_table} ORDER BY id ASC")
    for b in bots:
        bid = b.get("id")
        if bid is None:
            continue
        kws = await _safe_fetch(
            db,
            f"SELECT keyword FROM {kws_table} WHERE bot_id = {_ph(1)}",
            (bid,))
        kw_list = [str(k.get("keyword") or "") for k in kws]

        short = [k for k in kw_list if len(k) <= 2]
        if short:
            _warn(
                f"بوت #{bid}: {len(short)} كلمة قصيرة (≤2 حرف) — "
                f"قد تسبب مطابقة خاطئة: {short[:5]}")

        normalized = {}
        for k in kw_list:
            norm = k.strip().lower().replace("ة", "ه")
            norm = norm.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
            if norm in normalized and normalized[norm] != k:
                _warn(
                    f"بوت #{bid}: كلمات متطابقة بعد التطبيع: "
                    f"'{normalized[norm]}' و '{k}'")
            else:
                normalized[norm] = k


async def _inspect_invoices_anomalies(db) -> None:
    if not await _check_table_exists(db, "invoices"):
        return

    bad_amount = await _safe_count(
        db,
        "SELECT COUNT(*) FROM invoices "
        "WHERE status = 'paid' AND (amount <= 0 OR amount IS NULL)")
    if bad_amount > 0:
        _err(
            f"{bad_amount} فاتورة مدفوعة بمبلغ صفر أو سالب "
            f"(مشكلة محاسبية!)")

    if _is_postgres():
        stale = await _safe_count(
            db,
            "SELECT COUNT(*) FROM invoices "
            "WHERE status = 'pending' "
            "AND created_at < NOW() - INTERVAL '7 days'")
    else:
        stale = await _safe_count(
            db,
            "SELECT COUNT(*) FROM invoices "
            "WHERE status = 'pending' "
            "AND created_at < datetime('now', '-7 days')")
    if stale > 0:
        _warn(
            f"{stale} فاتورة معلّقة > 7 أيام (قد تحتاج cleanup)")


async def _inspect_settings_anomalies(db) -> None:
    if not await _check_table_exists(db, "settings"):
        _err("جدول settings غير موجود — البوت سيواجه مشاكل!")
        return

    for key in ("tables_hash", "bootstrap_hash"):
        try:
            val = await db.fetchval(
                f"SELECT value FROM settings WHERE key = {_ph(1)}",
                (key,))
            if not val or not str(val).strip():
                _warn(
                    f"{key} غير مضبوط — قد يُعاد bootstrap")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# MULTI-DB DISCOVERY
# ═══════════════════════════════════════════════════════════════════════

def _mask_db_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url)
        if p.password:
            netloc = f"{p.username}:***@{p.hostname}"
            if p.port:
                netloc += f":{p.port}"
            return f"{p.scheme}://{netloc}{p.path or ''}"
    except Exception:
        pass
    return url


def _extract_db_components(url: str) -> Dict[str, Any]:
    out = {"host": "?", "port": 0, "database": "?", "user": "?", "scheme": "?"}
    if not url:
        return out
    try:
        p = urlparse(url)
        out["scheme"] = p.scheme or "?"
        out["host"] = p.hostname or "?"
        out["port"] = p.port or 0
        out["database"] = (p.path or "/").lstrip("/") or "?"
        out["user"] = p.username or "?"
    except Exception:
        pass
    return out


def _guess_provider_from_host(host: str) -> str:
    h = (host or "").lower()
    if "timescale.com" in h: return "timescale"
    if "aivencloud.com" in h: return "aiven"
    if "rds.amazonaws.com" in h: return "aws_rds"
    if "supabase" in h: return "supabase"
    if "neon.tech" in h: return "neon"
    if "render.com" in h: return "render"
    if "railway" in h: return "railway"
    if "heroku" in h: return "heroku"
    if "cloudsql" in h or "gcp" in h: return "gcp"
    if h in ("localhost", "127.0.0.1", "::1"): return "local"
    return "unknown"


def _read_pool_metrics(pool) -> Dict[str, int]:
    metrics = {"max_size": 0, "current_size": 0, "idle_size": 0, "in_use": 0}
    if pool is None:
        return metrics
    try:
        try:
            if hasattr(pool, "get_max_size") and callable(pool.get_max_size):
                metrics["max_size"] = int(pool.get_max_size() or 0)
            else:
                _m = getattr(pool, "_maxsize", None)
                if _m is not None:
                    metrics["max_size"] = int(_m)
        except Exception:
            pass
        try:
            if hasattr(pool, "get_size") and callable(pool.get_size):
                metrics["current_size"] = int(pool.get_size() or 0)
            else:
                _s = getattr(pool, "size", None)
                if _s is not None:
                    if callable(_s):
                        metrics["current_size"] = int(_s() or 0)
                    else:
                        metrics["current_size"] = int(_s)
        except Exception:
            pass
        try:
            if hasattr(pool, "get_idle_size") and callable(pool.get_idle_size):
                metrics["idle_size"] = int(pool.get_idle_size() or 0)
            else:
                _i = getattr(pool, "freesize", None)
                if _i is not None:
                    if callable(_i):
                        metrics["idle_size"] = int(_i() or 0)
                    else:
                        metrics["idle_size"] = int(_i)
        except Exception:
            pass
        metrics["in_use"] = max(0, metrics["current_size"] - metrics["idle_size"])
        if metrics["max_size"] > 0:
            metrics["in_use"] = min(metrics["in_use"], metrics["max_size"])
            metrics["current_size"] = min(metrics["current_size"], metrics["max_size"])
            metrics["idle_size"] = min(metrics["idle_size"], metrics["max_size"])
    except Exception:
        pass
    return metrics


def _detect_active_db_source(db) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "active_url": "", "active_masked": "",
        "active_source": "unknown", "db_type": "unknown",
        "provider": "unknown",
        "components": {"host": "?", "port": 0, "database": "?", "user": "?", "scheme": "?"},
        "region": "unknown", "region_confidence": "low",
        "use_postgres": False, "use_mysql": False,
        "pool_size": 0, "pool_used": 0, "pool_idle": 0, "pool_current": 0,
    }
    if db is None:
        return out
    active_url = (getattr(db, "DATABASE_URL", "") or os.getenv("DATABASE_URL", ""))
    out["active_url"] = active_url
    out["active_masked"] = _mask_db_url(active_url)
    out["components"] = _extract_db_components(active_url)
    out["db_type"] = str(getattr(db, "DB_TYPE", "sqlite")).lower()
    out["use_postgres"] = bool(getattr(db, "USE_POSTGRES", False))
    out["use_mysql"] = bool(getattr(db, "USE_MYSQL", False))
    is_sqlite_local = (
        out["db_type"] == "sqlite"
        and not out["use_postgres"]
        and not out["use_mysql"]
    )
    if is_sqlite_local:
        out["provider"] = "sqlite_local"
        out["active_source"] = "sqlite"
        out["components"] = {"host": "local", "port": 0, "database": "sqlite",
                             "user": "?", "scheme": "sqlite"}
        out["region"] = "local"
        out["region_confidence"] = "high"
    else:
        out["provider"] = _guess_provider_from_host(out["components"].get("host", ""))
    pool = getattr(db, "_pool", None)
    if pool is not None:
        try:
            _metrics = _read_pool_metrics(pool)
            if _metrics["max_size"] <= 0:
                try:
                    _fallback_max = getattr(db, "DB_POOL_SIZE", 0) or 0
                    _metrics["max_size"] = int(_fallback_max)
                except Exception:
                    pass
            out["pool_size"] = _metrics["max_size"]
            out["pool_used"] = _metrics["in_use"]
            out["pool_idle"] = _metrics["idle_size"]
            out["pool_current"] = _metrics["current_size"]
        except Exception:
            pass
    if not is_sqlite_local:
        region_info = _guess_db_region(out["components"].get("host", ""))
        out["region"] = region_info.get("region", "unknown")
        out["region_confidence"] = region_info.get("confidence", "low")
    if active_url and not is_sqlite_local:
        for var in _DB_URL_PRIORITY:
            val = os.getenv(var, "")
            if val and val == active_url:
                out["active_source"] = var
                break
        else:
            comp = out["components"]
            for var, _ in _DB_URL_ENV_VARS:
                val = os.getenv(var, "")
                if not val:
                    continue
                if comp["host"] and comp["host"] in val and \
                   comp["database"] and comp["database"] in val:
                    out["active_source"] = f"{var} (تطابق جزئي)"
                    break
    return out


def _get_all_configured_databases() -> List[Dict[str, Any]]:
    active = _detect_active_db_source(_get_db())
    active_url = active.get("active_url", "")
    configured: List[Dict[str, Any]] = []
    seen_keys = set()
    for var, hint_type in _DB_URL_ENV_VARS:
        val = os.getenv(var, "")
        if not val or len(val) < 10:
            continue
        if "://" not in val and not val.endswith(".db"):
            continue
        comp = _extract_db_components(val)
        dedup_key = f"{comp['host']}:{comp['port']}/{comp['database']}"
        is_active = (val == active_url)
        if dedup_key in seen_keys and not is_active:
            continue
        if is_active:
            seen_keys.add(dedup_key)
        db_type = hint_type
        scheme = (comp["scheme"] or "").lower()
        if scheme in ("postgres", "postgresql"):
            db_type = "postgres"
        elif scheme in ("mysql", "mariadb"):
            db_type = "mysql"
        elif scheme == "sqlite" or val.endswith(".db"):
            db_type = "sqlite"
        elif db_type == "unknown" and scheme:
            db_type = scheme
        provider = _guess_provider_from_host(comp["host"])
        region_info = _guess_db_region(comp["host"])
        configured.append({
            "env_var": var, "db_type": db_type, "provider": provider,
            "host": comp["host"], "port": comp["port"],
            "database": comp["database"], "user": comp["user"],
            "masked_url": _mask_db_url(val), "is_active": is_active,
            "region": region_info.get("region", "unknown"),
            "region_confidence": region_info.get("confidence", "low"),
        })
    for var in _SQLITE_PATH_VARS:
        val = os.getenv(var, "")
        if not val or val in seen_keys:
            continue
        seen_keys.add(val)
        is_active = (
            val == active_url
            or (active.get("db_type") == "sqlite"
                and active.get("provider") == "sqlite_local")
        )
        configured.append({
            "env_var": var, "db_type": "sqlite", "provider": "sqlite_local",
            "host": "local", "port": 0, "database": val, "user": "?",
            "masked_url": val, "is_active": is_active,
            "region": "local", "region_confidence": "high",
        })
    configured.sort(key=lambda x: (not x["is_active"], x["env_var"]))
    return configured


def _get_multi_db_warnings(configured: List[Dict[str, Any]]) -> List[str]:
    warnings: List[str] = []
    hosts: Dict[str, List[str]] = {}
    for c in configured:
        key = f"{c['host']}:{c['port']}"
        hosts.setdefault(key, []).append(c["env_var"])
    for key, vars_list in hosts.items():
        if len(vars_list) > 1:
            warnings.append(
                f"⚠️ <b>تكرار</b>: <code>{_esc(key)}</code> "
                f"مُعرّف في: <code>{_esc(', '.join(vars_list))}</code> → نفس DB"
            )
    providers = set(c["provider"] for c in configured
                    if c["provider"] not in ("unknown", "sqlite_local", "local"))
    if len(providers) > 1:
        warnings.append(
            f"⚠️ <b>مزودون متعددون</b>: "
            f"<code>{_esc(', '.join(sorted(providers)))}</code> "
            f"— تأكد أن البوت يستخدم الصحيح"
        )
    types = {c["db_type"] for c in configured if c["db_type"] and c["db_type"] != "sqlite"}
    if len(types) > 1:
        warnings.append(
            f"⚠️ <b>أنواع DB مختلفة</b>: "
            f"<code>{_esc(', '.join(sorted(types)))}</code>"
        )
    if not any(c["is_active"] for c in configured):
        warnings.append(
            "⚠️ لم يتم تحديد أي DB كنشطة — قد يكون البوت يستخدم SQLite محلي."
        )
    return warnings


def _format_pool_line(active: Dict[str, Any]) -> str:
    max_size = active.get("pool_size", 0)
    in_use = active.get("pool_used", 0)
    idle = active.get("pool_idle", 0)
    current = active.get("pool_current", 0)
    if max_size <= 0 and current <= 0:
        return "🏊 Pool: — (غير متاح)"
    display_max = max_size if max_size > 0 else current
    util_pct = round((current / display_max) * 100, 0) if display_max > 0 else 0
    if display_max > 0:
        real_util = (in_use / display_max) * 100
        if real_util < 50:
            icon = "🟢"
        elif real_util < 80:
            icon = "🟡"
        else:
            icon = "🔴"
    else:
        icon = "⚪"
    return (
        f"🏊 Pool: {icon} {in_use}/{display_max} "
        f"(idle={idle}, current={current}, util={util_pct:.0f}%)"
    )


def format_multi_db_report() -> str:
    lines: List[str] = []
    lines.append("🗂️ <b>قواعد البيانات المُعدّة (Multi-DB Discovery)</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    active = _detect_active_db_source(_get_db())
    configured = _get_all_configured_databases()
    lines.append("🟢 <b>النشطة حالياً:</b>")
    if active.get("active_url") or active.get("provider") == "sqlite_local":
        comp = active.get("components", {})
        lines.append(
            f"   📦 <b>{_esc(active.get('provider', '?')).upper()}</b> "
            f"@ <code>{_esc(comp.get('host', '?'))}:{comp.get('port', 0)}</code>"
        )
        lines.append(f"   🗄️ DB: <code>{_esc(comp.get('database', '?'))}</code>")
        lines.append(f"   🔌 المصدر: <code>{_esc(active.get('active_source', '?'))}</code>")
        lines.append(f"   🌍 المنطقة: <code>{_esc(active.get('region', 'unknown'))}</code> "
                     f"<i>({active.get('region_confidence', '?')})</i>")
        lines.append(f"   {_format_pool_line(active)}")
        masked = active.get("active_masked", "")
        if masked:
            lines.append(f"   🔗 <code>{_esc(masked)[:80]}</code>")
    else:
        lines.append("   ⚪ لم يتم الاتصال بعد، أو SQLite محلي.")
    lines.append("")
    if not configured:
        lines.append("⚠️ لا توجد قواعد بيانات مُعدّة في env vars.")
        return "\n".join(lines)
    lines.append(f"📋 <b>كل المُعدّة ({len(configured)}):</b>")
    lines.append("")
    for c in configured:
        icon = "🟢" if c["is_active"] else "⚪"
        active_tag = " ← <b>النشطة</b>" if c["is_active"] else ""
        lines.append(f"  {icon} <code>{_esc(c['env_var'])}</code>{active_tag}")
        lines.append(f"      {_esc(c['db_type'].upper())} | "
                     f"{_esc(c['provider'])} | {_esc(c['host'])}:{c['port']}")
        lines.append(f"      📦 <code>{_esc(c['database'])}</code> | 🌍 {_esc(c['region'])}")
        lines.append(f"      🔗 <code>{_esc(c['masked_url'][:80])}</code>")
        lines.append("")
    warnings = _get_multi_db_warnings(configured)
    if warnings:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("⚠️ <b>تحذيرات:</b>")
        for w in warnings:
            lines.append(f"  {w}")
        lines.append("")
    if len(configured) == 1:
        lines.append("✅ <b>إعداد نظيف</b>: DB واحدة فقط مُعرّفة.")
    elif not warnings:
        lines.append("✅ <b>إعداد سليم</b>: قواعد متعددة لكن النشطة واضحة.")
    return "\n".join(lines)


async def diagnose_databases() -> str:
    cached = _cache_get("multi_db")
    if cached is not None:
        return cached
    text = format_multi_db_report()
    _cache_set("multi_db", text, ttl=60.0)
    return text


def format_active_db_line() -> str:
    active = _detect_active_db_source(_get_db())
    if active.get("provider") == "sqlite_local":
        return "🗄️ <b>DB النشطة:</b> SQLite (محلي)"
    if not active.get("active_url"):
        if active.get("db_type") == "sqlite":
            return "🗄️ <b>DB النشطة:</b> SQLite (محلي)"
        return ""
    comp = active.get("components", {})
    src = active.get("active_source", "?")
    provider = active.get("provider", "?")
    host = comp.get("host", "?")
    port = comp.get("port", 0)
    db_name = comp.get("database", "?")
    region = active.get("region", "unknown")
    return (
        f"🗄️ <b>DB النشطة:</b> "
        f"<code>{_esc(provider)}</code> @ "
        f"<code>{_esc(host)}:{port}/{_esc(db_name)}</code>\n"
        f"   🔌 من: <code>{_esc(src)}</code> | 🌍 <code>{_esc(region)}</code>"
    )


# ═══════════════════════════════════════════════════════════════════════
# كشف المناطق
# ═══════════════════════════════════════════════════════════════════════

def _normalize_render_region(raw: str) -> Optional[str]:
    if not raw:
        return None
    try:
        rl = str(raw).strip().lower()
        if not rl:
            return None
        if rl in _RENDER_REGION_CODES:
            return _RENDER_REGION_CODES[rl]
        if any(rl.startswith(p) for p in ("eu-", "us-", "ap-", "ca-", "sa-")):
            return rl
        for k, v in _RENDER_REGION_CODES.items():
            if k in rl:
                return v
    except Exception:
        pass
    return None


def _detect_bot_cloud() -> Dict[str, Any]:
    result: Dict[str, Any] = {"provider": "unknown", "region": "unknown",
                              "confidence": "low", "hints": []}
    for key, provider in _CLOUD_ENV_KEYS.items():
        if os.getenv(key):
            result["provider"] = provider
            result["hints"].append(key)
            result["confidence"] = "high"
            break
    provider = result["provider"]
    if provider == "render":
        for key in _RENDER_REGION_ENV_VARS:
            raw = os.getenv(key)
            if not raw:
                continue
            normalized = _normalize_render_region(raw)
            if normalized:
                result["region"] = normalized
                result["confidence"] = "high"
                result["hints"].append(f"{key}={raw}")
                break
        if result["region"] == "unknown":
            hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
            if hostname:
                normalized = _normalize_render_region(hostname)
                if normalized:
                    result["region"] = normalized
                    result["confidence"] = "medium"
                    result["hints"].append(f"hostname={hostname}")
    elif provider == "fly":
        region = os.getenv("FLY_REGION") or os.getenv("FLY_REGION_CODE")
        if region:
            result["region"] = region.lower()
            result["confidence"] = "high"
            result["hints"].append("FLY_REGION")
    elif provider == "heroku":
        region = os.getenv("HEROKU_REGION")
        if region:
            result["region"] = f"heroku-{region.lower()}"
            result["confidence"] = "high"
            result["hints"].append("HEROKU_REGION")
    elif provider == "railway":
        region = os.getenv("RAILWAY_REGION")
        if region:
            result["region"] = region.lower()
            result["confidence"] = "high"
            result["hints"].append("RAILWAY_REGION")
    return result


def _guess_db_region(db_host: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"provider": "unknown", "region": "unknown", "confidence": "low"}
    h = (db_host or "").lower().strip()
    env_region = (os.getenv("DB_REGION") or os.getenv("TIMESCALE_REGION")
                  or os.getenv("DATABASE_REGION"))
    if env_region:
        normalized = _normalize_render_region(env_region) or env_region
        result["region"] = normalized
        result["confidence"] = "high"
        if "timescale.com" in h:
            result["provider"] = "timescale"
        elif "aivencloud.com" in h:
            result["provider"] = "aiven"
        elif "rds.amazonaws.com" in h:
            result["provider"] = "aws_rds"
        return result
    if not h:
        return result
    if "aivencloud.com" in h:
        result["provider"] = "aiven"
        for hint, region in _AIVEN_REGION_HINTS.items():
            if hint in h:
                result["region"] = region
                result["confidence"] = "medium"
                return result
        result["confidence"] = "low"
        return result
    if "timescale.com" in h:
        result["provider"] = "timescale"
        result["confidence"] = "low"
        return result
    if "rds.amazonaws.com" in h:
        result["provider"] = "aws_rds"
        for p in h.split("."):
            if any(p.startswith(prefix) for prefix in ("eu-", "us-", "ap-", "ca-", "sa-")):
                result["region"] = p
                result["confidence"] = "high"
                return result
        return result
    if "cloudsql" in h or "gcp" in h:
        result["provider"] = "gcp"
        return result
    return result


def _infer_region_from_rtt(tcp_ms, bot_info, db_info) -> Dict[str, Any]:
    out = {"cross_region": None, "confidence": "low", "reason": "", "inferred": False}
    if tcp_ms is None or tcp_ms <= 0:
        return out
    t = float(tcp_ms)
    if t < _RTT_SAME_REGION_HIGH:
        out["cross_region"] = False
        out["confidence"] = "high"
        out["inferred"] = True
        out["reason"] = f"RTT={t:.0f}ms < {_RTT_SAME_REGION_HIGH:.0f}ms → نفس المنطقة (استنتاج من RTT)"
    elif t < _RTT_SAME_REGION_MEDIUM:
        out["cross_region"] = False
        out["confidence"] = "medium"
        out["inferred"] = True
        out["reason"] = f"RTT={t:.0f}ms في نطاق {_RTT_SAME_REGION_HIGH:.0f}-{_RTT_SAME_REGION_MEDIUM:.0f}ms → نفس المنطقة (احتمال مرتفع)"
    elif t < _RTT_CROSS_REGION_MIN:
        out["cross_region"] = None
        out["confidence"] = "medium"
        out["inferred"] = True
        out["reason"] = f"RTT={t:.0f}ms في نطاق {_RTT_SAME_REGION_MEDIUM:.0f}-{_RTT_CROSS_REGION_MIN:.0f}ms → احتمال cross-region"
    else:
        out["cross_region"] = True
        out["confidence"] = "high"
        out["inferred"] = True
        out["reason"] = f"RTT={t:.0f}ms ≥ {_RTT_CROSS_REGION_MIN:.0f}ms → مناطق مختلفة قطعياً"
    return out


def _detect_cross_region(bot_info, db_info, tcp_ms=None) -> Dict[str, Any]:
    out = {
        "cross_region": None,
        "bot_region": bot_info.get("region", "unknown"),
        "db_region": db_info.get("region", "unknown"),
        "bot_provider": bot_info.get("provider", "unknown"),
        "db_provider": db_info.get("provider", "unknown"),
        "confidence": "low", "recommendation": "",
        "inferred_from_rtt": False, "inference_reason": "",
    }
    bot_r = bot_info.get("region", "unknown")
    db_r = db_info.get("region", "unknown")
    if tcp_ms is not None and tcp_ms > 0:
        inference = _infer_region_from_rtt(tcp_ms, bot_info, db_info)
        if inference.get("confidence") == "high":
            out["cross_region"] = inference["cross_region"]
            out["confidence"] = "high"
            out["inferred_from_rtt"] = True
            out["inference_reason"] = inference["reason"]
            if inference["cross_region"] is False:
                out["recommendation"] = (
                    f"✅ {inference['reason']}.\n"
                    f"   RTT={tcp_ms:.0f}ms → نفس المنطقة قطعياً.\n"
                    f"   💡 لتحديد اسم المنطقة الدقيق، أضف "
                    f"<code>RENDER_SERVICE_REGION=singapore</code> "
                    f"و<code>DB_REGION=ap-southeast-1</code> في Render → Environment."
                )
            else:
                out["recommendation"] = (
                    f"🚨 {inference['reason']}.\n"
                    f"   RTT={tcp_ms:.0f}ms → مناطق مختلفة.\n"
                    f"   ✅ الحل: انقل البوت و DB إلى نفس المنطقة."
                )
            return out
    if bot_r != "unknown" and db_r != "unknown":
        out["confidence"] = ("high" if (bot_info.get("confidence") == "high"
                                        and db_info.get("confidence") == "high") else "medium")
        if bot_r == db_r:
            out["cross_region"] = False
            out["recommendation"] = f"✅ البوت و DB في نفس المنطقة ({bot_r}). RTT الطبيعي المتوقع 1-5ms."
            return out
        out["cross_region"] = True
        out["recommendation"] = (
            f"🚨 البوت في {bot_r} و DB في {db_r} — منطقتان مختلفتان!\n"
            f"   كل استعلام يقطع مسافة جغرافية (~500-5000km).\n"
            f"   ✅ الحل: انقل البوت إلى {db_r} أو انقل DB إلى {bot_r}."
        )
        return out
    inference = _infer_region_from_rtt(tcp_ms, bot_info, db_info)
    if inference.get("inferred"):
        out["cross_region"] = inference["cross_region"]
        out["confidence"] = inference["confidence"]
        out["inferred_from_rtt"] = True
        out["inference_reason"] = inference["reason"]
        if inference["cross_region"] is False:
            out["recommendation"] = (
                f"✅ {inference['reason']}.\n"
                f"   RTT={tcp_ms:.0f}ms → نفس المنطقة.\n"
                f"   💡 لتحديد اسم المنطقة الدقيق، أضف "
                f"<code>RENDER_SERVICE_REGION</code> + "
                f"<code>DB_REGION</code> في Render → Environment."
            )
        elif inference["cross_region"] is True:
            out["recommendation"] = (
                f"🚨 {inference['reason']}.\n"
                f"   RTT={tcp_ms:.0f}ms → مناطق مختلفة.\n"
                f"   ✅ الحل: انقل البوت و DB إلى نفس المنطقة."
            )
        else:
            out["recommendation"] = (
                f"🟡 {inference['reason']}.\n"
                f"   RTT={tcp_ms:.0f}ms — غير حاسم.\n"
                f"   💡 للحصول على تحديد دقيق، أضف "
                f"<code>RENDER_SERVICE_REGION</code> + "
                f"<code>DB_REGION</code> env vars."
            )
        return out
    out["recommendation"] = (
        "ℹ️ لا يمكن تحديد المناطق:\n"
        "   • bot_region=unknown (أضف RENDER_SERVICE_REGION)\n"
        "   • db_region=unknown (أضف DB_REGION)\n"
        "   • TCP=0 (لم يُقَس)\n"
        "💡 الحل: اضبط env vars في Render:\n"
        "   RENDER_SERVICE_REGION=singapore\n"
        "   DB_REGION=ap-southeast-1"
    )
    return out


# ═══════════════════════════════════════════════════════════════════════
# LATENCY PROBE
# ═══════════════════════════════════════════════════════════════════════

async def _detect_users_pk_col(conn) -> str:
    try:
        row = await conn.fetchrow("""
            SELECT a.attname AS pk_col
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a
              ON a.attrelid = i.indrelid
             AND a.attnum = ANY(i.indkey)
            WHERE c.relname = 'users'
              AND n.nspname = current_schema()
              AND i.indisprimary
            LIMIT 1
        """)
        if row:
            col = row["pk_col"] if isinstance(row, dict) else row[0]
            if col:
                return str(col)
    except Exception as e:
        logger.debug(f"_detect_users_pk_col: {e}")
    return "user_id"


async def _probe_db_latency(*, force: bool = False, socket_timeout: float = 5.0) -> Dict[str, Any]:
    if not force:
        cached = _cache_get("latency_probe")
        if cached is not None:
            return cached
    db = _get_db()
    if db is None:
        return {"ok": False, "error": "DB غير مستورد", "verdict": "unknown"}
    db_type = str(getattr(db, "DB_TYPE", "sqlite")).lower()
    result: Dict[str, Any] = {"ok": False, "db_type": db_type,
                               "verdict": "unknown", "diagnosis": "",
                               "recommendation": "", "used_pool": False}
    active_info = _detect_active_db_source(db)
    result["active_db"] = active_info
    if db_type == "sqlite":
        try:
            t0 = time.monotonic()
            await db.fetchval("SELECT 1", default=0)
            first_ms = (time.monotonic() - t0) * 1000
            warm: List[float] = []
            for _ in range(5):
                t0 = time.monotonic()
                await db.fetchval("SELECT 1", default=0)
                warm.append((time.monotonic() - t0) * 1000)
            result.update({
                "ok": True, "tcp_connect_ms": 0.0, "asyncpg_connect_ms": 0.0,
                "first_query_ms": round(first_ms, 2),
                "warm_queries_ms": [round(x, 2) for x in warm],
                "warm_median_ms": round(statistics.median(warm), 2),
                "pk_select_ms": round(first_ms, 2),
                "bulk_fetch_ms": 0.0, "bulk_rows": 0,
                "verdict": _verdict_from_warm(statistics.median(warm)),
                "diagnosis": "SQLite محلي — لا شبكة.",
                "recommendation": "الأداء يعتمد على I/O القرص.",
            })
        except Exception as e:
            result["error"] = f"SQLite probe: {e}"
        _cache_set("latency_probe", result, ttl=120.0)
        return result
    db_url = active_info.get("active_url") or (
        getattr(db, "DATABASE_URL", "") or os.getenv("DATABASE_URL", "")
    )
    host = "?"
    port = 0
    try:
        parsed = urlparse(db_url)
        host = parsed.hostname or "?"
        port = parsed.port or (5432 if db_type == "postgres" else 3306)
        result["host"] = host
        result["port"] = port
        result["active_db_source"] = active_info.get("active_source", "unknown")
    except Exception as e:
        logger.debug(f"parse DATABASE_URL: {e}")
    db_region = _guess_db_region(host)
    bot_region = _detect_bot_cloud()
    result["db_region"] = db_region
    result["bot_region"] = bot_region
    tcp_ms: Optional[float] = None
    if host != "?" and port > 0:
        try:
            t0 = time.monotonic()
            def _connect():
                s = socket.create_connection((host, port), timeout=socket_timeout)
                s.close()
            await asyncio.wait_for(asyncio.to_thread(_connect), timeout=socket_timeout + 1.0)
            tcp_ms = (time.monotonic() - t0) * 1000
            result["tcp_connect_ms"] = round(tcp_ms, 2)
        except asyncio.TimeoutError:
            result["tcp_connect_ms"] = -1.0
            result["error"] = f"TCP timeout >{socket_timeout}s"
            result["verdict"] = "critical"
            result["diagnosis"] = (f"🔴 لا يمكن الوصول إلى {host}:{port} خلال {socket_timeout}s "
                                   f"— شبكة مقطوعة أو DB مُطفأ.")
            result["cross_region"] = _detect_cross_region(bot_region, db_region, tcp_ms=None)
            _cache_set("latency_probe", result, ttl=120.0)
            return result
        except Exception as e:
            result["tcp_connect_ms"] = -1.0
            result["error"] = f"TCP: {type(e).__name__}: {e}"
            result["verdict"] = "critical"
            result["cross_region"] = _detect_cross_region(bot_region, db_region, tcp_ms=None)
            _cache_set("latency_probe", result, ttl=120.0)
            return result
    else:
        result["tcp_connect_ms"] = -1.0
    cross = _detect_cross_region(bot_region, db_region, tcp_ms=tcp_ms)
    result["cross_region"] = cross

    conn = None
    from_pool = False
    pool = getattr(db, "_pool", None)
    pool_acquire_failed = False
    pool_acquire_error: Optional[str] = None

    if pool is not None:
        try:
            t0 = time.monotonic()
            conn = await asyncio.wait_for(pool.acquire(), timeout=socket_timeout)
            result["pool_acquire_ms"] = round((time.monotonic() - t0) * 1000, 2)
            from_pool = True
            result["used_pool"] = True
        except Exception as e:
            logger.debug(f"pool.acquire فشل: {e}")
            pool_acquire_failed = True
            pool_acquire_error = f"{type(e).__name__}: {str(e)[:120]}"
            conn = None
            from_pool = False

    if conn is None and pool_acquire_failed:
        result["error"] = f"pool موجود لكن acquire فشل: {pool_acquire_error}"
        result["verdict"] = "critical"
        result["diagnosis"] = (
            f"🔴 pool موجود (max={result['active_db'].get('pool_size', '?')}) "
            f"لكن acquire فشل — مشكلة في الاتصالات الحالية.\n"
            f"   السبب: <code>{_esc(pool_acquire_error or '?')}</code>"
        )
        result["recommendation"] = (
            "✅ تحقق من:\n"
            "   • عدد الاتصالات النشطة (pg_stat_activity)\n"
            "   • idle-in-transaction leaks\n"
            "   • max_connections في PostgreSQL\n"
            "   • network بين البوت و DB"
        )
        _cache_set("latency_probe", result, ttl=120.0)
        return result

    if conn is None:
        try:
            t0 = time.monotonic()
            if db_type == "postgres":
                try:
                    import asyncpg  # type: ignore
                except ImportError:
                    result["error"] = "asyncpg غير مثبت"
                    _cache_set("latency_probe", result, ttl=120.0)
                    return result
                try:
                    conn = await asyncio.wait_for(
                        asyncpg.connect(db_url, timeout=socket_timeout),
                        timeout=socket_timeout + 2.0,
                    )
                except asyncio.TimeoutError:
                    result["error"] = "asyncpg.connect timeout"
                    result["verdict"] = "critical"
                    _cache_set("latency_probe", result, ttl=120.0)
                    return result
            elif db_type == "mysql":
                try:
                    import asyncmy  # type: ignore
                except ImportError:
                    result["error"] = "asyncmy غير مثبت"
                    _cache_set("latency_probe", result, ttl=120.0)
                    return result
                try:
                    conn = await asyncio.wait_for(asyncmy.connect(db_url),
                                                  timeout=socket_timeout + 2.0)
                except asyncio.TimeoutError:
                    result["error"] = "asyncmy.connect timeout"
                    result["verdict"] = "critical"
                    _cache_set("latency_probe", result, ttl=120.0)
                    return result
            else:
                result["error"] = f"DB type غير مدعوم: {db_type}"
                _cache_set("latency_probe", result, ttl=120.0)
                return result
            result["asyncpg_connect_ms"] = round((time.monotonic() - t0) * 1000, 2)
        except Exception as e:
            result["error"] = f"connect: {type(e).__name__}: {str(e)[:120]}"
            result["verdict"] = "critical"
            _cache_set("latency_probe", result, ttl=120.0)
            return result
    else:
        result["asyncpg_connect_ms"] = 0.0
    try:
        t0 = time.monotonic()
        if db_type == "postgres":
            await conn.fetchval("SELECT 1")
        else:
            cur = await conn.cursor()
            await cur.execute("SELECT 1")
            await cur.fetchone()
            try:
                await cur.close()
            except Exception:
                pass
        result["first_query_ms"] = round((time.monotonic() - t0) * 1000, 2)
        warm = []
        for _ in range(5):
            t0 = time.monotonic()
            if db_type == "postgres":
                await conn.fetchval("SELECT 1")
            else:
                cur = await conn.cursor()
                await cur.execute("SELECT 1")
                await cur.fetchone()
                try:
                    await cur.close()
                except Exception:
                    pass
            warm.append((time.monotonic() - t0) * 1000)
        result["warm_queries_ms"] = [round(x, 2) for x in warm]
        warm_median = statistics.median(warm)
        result["warm_median_ms"] = round(warm_median, 2)
        pk_col = "user_id"
        if db_type == "postgres":
            try:
                pk_col = await _detect_users_pk_col(conn)
            except Exception as e:
                logger.debug(f"_detect_users_pk_col: {e}")
        result["users_pk_col"] = pk_col
        pk_sql_pg = f'SELECT 1 FROM users WHERE {pk_col} = $1 LIMIT 1'
        pk_sql_mysql = "SELECT 1 FROM users WHERE user_id = %s LIMIT 1"
        try:
            if db_type == "postgres":
                await conn.fetchval(pk_sql_pg, 1)
            else:
                cur = await conn.cursor()
                await cur.execute(pk_sql_mysql, (1,))
                await cur.fetchone()
                try:
                    await cur.close()
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"pk_select warmup: {e}")
        try:
            t0 = time.monotonic()
            if db_type == "postgres":
                await conn.fetchval(pk_sql_pg, 1)
            else:
                cur = await conn.cursor()
                await cur.execute(pk_sql_mysql, (1,))
                await cur.fetchone()
                try:
                    await cur.close()
                except Exception:
                    pass
            result["pk_select_ms"] = round((time.monotonic() - t0) * 1000, 2)
        except Exception as e:
            result["pk_select_ms"] = -1.0
            logger.debug(f"pk_select probe: {e}")
        try:
            t0 = time.monotonic()
            if db_type == "postgres":
                rows = await conn.fetch("SELECT * FROM admin_logs LIMIT 100")
            else:
                cur = await conn.cursor()
                await cur.execute("SELECT * FROM admin_logs LIMIT 100")
                rows = await cur.fetchall()
                try:
                    await cur.close()
                except Exception:
                    pass
            result["bulk_fetch_ms"] = round((time.monotonic() - t0) * 1000, 2)
            result["bulk_rows"] = len(rows) if rows else 0
        except Exception as e:
            result["bulk_fetch_ms"] = -1.0
            result["bulk_rows"] = 0
            logger.debug(f"bulk_fetch probe: {e}")
        verdict, diagnosis, recommendation = _compute_latency_verdict(result)
        result["verdict"] = verdict
        result["diagnosis"] = diagnosis
        result["recommendation"] = recommendation
        result["ok"] = True
    except Exception as e:
        logger.warning(f"_probe_db_latency inner: {e}")
        result["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        result["verdict"] = "critical"
    finally:
        if conn is not None:
            if from_pool and pool is not None:
                try:
                    await asyncio.wait_for(pool.release(conn), timeout=_CONN_CLOSE_TIMEOUT)
                except Exception as e:
                    logger.debug(f"pool.release: {e}")
            else:
                try:
                    await asyncio.wait_for(conn.close(), timeout=_CONN_CLOSE_TIMEOUT)
                except asyncio.TimeoutError:
                    logger.debug("conn.close: timeout")
                except Exception as e:
                    logger.debug(f"conn.close: {e}")
    _cache_set("latency_probe", result, ttl=120.0)
    return result


def _verdict_from_warm(warm_ms: float) -> str:
    if warm_ms < 5: return "excellent"
    if warm_ms < 20: return "good"
    if warm_ms < 100: return "acceptable"
    if warm_ms < 500: return "slow"
    return "critical"


def _compute_latency_verdict(result: Dict[str, Any]) -> Tuple[str, str, str]:
    tcp = float(result.get("tcp_connect_ms") or 0)
    conn = float(result.get("asyncpg_connect_ms") or 0)
    warm = float(result.get("warm_median_ms") or 0)
    first = float(result.get("first_query_ms") or 0)
    pk = float(result.get("pk_select_ms") or 0)
    used_pool = bool(result.get("used_pool", False))
    cross = result.get("cross_region") or {}
    internal_db = max(0.0, warm - tcp) if tcp > 0 else warm
    if tcp < 0:
        return ("critical",
                "🔴 لا يمكن قياس TCP — الشبكة مقطوعة أو DB غير متاح.",
                "تحقّق من DATABASE_URL، حالة DB، وأي firewall.")
    if warm > 200 and tcp < 80:
        return ("critical",
                f"🔴 DB بطيء ({warm:.0f}ms) رغم شبكة ممتازة ({tcp:.0f}ms). "
                f"المشكلة داخل PostgreSQL نفسه — ليس في الشبكة.",
                "شغّل VACUUM ANALYZE فورًا، راجع pg_stat_statements، "
                "افحص CPU/RAM على الخادم.")
    if cross.get("cross_region") is True and tcp > 30:
        bot_r = cross.get("bot_region", "?")
        db_r = cross.get("db_region", "?")
        inferred = cross.get("inferred_from_rtt", False)
        inferred_note = ("\n   🆕 مُستنتَج من RTT (env vars غائبة)." if inferred else "")
        return ("acceptable",
                f"🚨 <b>Cross-Region مؤكّد</b>: "
                f"البوت في <code>{_esc(bot_r)}</code>، "
                f"DB في <code>{_esc(db_r)}</code>. "
                f"كل استعلام يقطع ~{tcp:.0f}ms RTT. "
                f"DB داخلياً سريع (~{internal_db:.0f}ms).{inferred_note}",
                f"✅ <b>الحل الجذري</b>: انقل البوت إلى <code>{_esc(db_r)}</code> "
                f"أو انقل DB إلى <code>{_esc(bot_r)}</code>. "
                f"النتيجة المتوقعة: 43ms → 1-3ms (تسريع 10-40×).\n"
                f"⚡ <b>حل مؤقت</b>: فعّل PgBouncer على DB لتقليل round-trips "
                f"(قد يوفّر 30-50% من التأخير).")
    if tcp > 30 and warm < 50 and internal_db < 15:
        inferred_note = ""
        if cross.get("inferred_from_rtt"):
            inferred_note = f"\n   💡 الاستنتاج: {cross.get('inference_reason', '')}"
        return ("acceptable",
                f"🟡 الشبكة بين البوت و DB تُضيف ~{tcp:.0f}ms لكل "
                f"استعلام (RTT). DB داخلياً سريع جداً "
                f"(~{internal_db:.0f}ms). المشكلة في المسافة الجغرافية.{inferred_note}",
                f"مع {tcp:.0f}ms ذهاب-وإياب، كل استعلام معقّد (3-5 RTTs) "
                f"يستغرق ~{tcp*3:.0f}-{tcp*5:.0f}ms. "
                "انقل البوت وDB إلى نفس المنطقة، أو قلّل عدد الاستعلامات "
                "في المسارات الساخنة (N+1).")
    if tcp > 300 and warm < 50:
        return ("slow",
                f"🟠 زمن TCP ({tcp:.0f}ms) مرتفع جداً، لكن DB يستجيب "
                f"بسرعة (warm={warm:.0f}ms). المشكلة في الشبكة، لا DB.",
                "انقل البوت أو DB إلى نفس المنطقة الجغرافية. "
                "أو استخدم connection pooler (PgBouncer) قريباً منك.")
    if tcp > 150 and warm < 30:
        return ("acceptable",
                f"🟡 TCP={tcp:.0f}ms (مقبول)، DB={warm:.0f}ms. "
                f"هذا يطابق نمط: كل استعلام +{tcp:.0f}ms.",
                f"مع {tcp:.0f}ms ذهاب-وإياب، كل استعلام معقّد (3-5 "
                f"round-trips) يستغرق ~{tcp*3:.0f}-{tcp*5:.0f}ms. "
                "قلّل عدد الاستعلامات أو انقل DB أقرب.")
    if warm > 500:
        return ("critical",
                f"🔴 DB بطيء حتى على SELECT 1 ({warm:.0f}ms). "
                "الخادم مُشبع أو مشاكل hardware.",
                "راجع CPU/RAM/disk I/O على خادم PostgreSQL. "
                "جرّب pg_stat_statements لكشف استعلامات ثقيلة.")
    if warm > 100:
        return ("slow",
                f"🟠 DB يستجيب بـ {warm:.0f}ms لـ SELECT 1 — بطء داخلي. "
                "ربما autovacuum يجري، أو replication lag.",
                "شغّل VACUUM ANALYZE، راجع pg_stat_activity، "
                "تحقّق من shared_buffers (يجب ≥ 25% RAM).")
    if warm < 20 and tcp < 50:
        pool_note = " (pool warm)" if used_pool else ""
        same_region_hint = ""
        if tcp < _RTT_SAME_REGION_HIGH:
            same_region_hint = " — نفس المنطقة (RTT منخفض)"
        return ("excellent",
                f"🟢 ممتاز{pool_note} — TCP={tcp:.0f}ms، DB={warm:.0f}ms{same_region_hint}.",
                "لا حاجة لأي تغيير.")
    if warm < 50 and tcp < 100:
        return ("good", f"🟢 جيد — TCP={tcp:.0f}ms، DB={warm:.0f}ms.", "الأداء سليم.")
    return ("acceptable",
            f"🟡 TCP={tcp:.0f}ms، DB={warm:.0f}ms، first={first:.0f}ms، PK={pk:.0f}ms.",
            "راقب الأداء — قد يحتاج ضبطاً لاحقاً.")


def format_latency_report(probe: Dict[str, Any]) -> str:
    if not probe.get("ok"):
        err = _esc(probe.get("error", "خطأ غير معروف"))
        diag = probe.get("diagnosis", "")
        rec = probe.get("recommendation", "")
        lines = [f"🔬 <b>اختبار الكمون</b>",
                 "━━━━━━━━━━━━━━━━━━━━━━",
                 "",
                 f"❌ <b>فشل:</b> {err}"]
        if diag:
            lines.append("")
            lines.append(f"<b>التشخيص:</b>\n  {diag}")
        if rec:
            lines.append("")
            lines.append(f"<b>التوصية:</b>\n  {rec}")
        return "\n".join(lines)
    lines: List[str] = []
    lines.append("🔬 <b>اختبار الكمون (Latency Probe)</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    active_line = format_active_db_line()
    if active_line:
        lines.append(active_line)
        lines.append("")
    cross = probe.get("cross_region") or {}
    db_region = probe.get("db_region") or {}
    bot_region = probe.get("bot_region") or {}
    if (bot_region.get("region", "unknown") != "unknown"
            or db_region.get("region", "unknown") != "unknown"
            or cross.get("inferred_from_rtt")):
        lines.append("🌍 <b>المناطق:</b>")
        bot_r = bot_region.get("region", "unknown")
        bot_p = bot_region.get("provider", "?")
        db_r = db_region.get("region", "unknown")
        db_p = db_region.get("provider", "?")
        lines.append(f"   🤖 البوت: <code>{_esc(bot_p)}</code> @ <code>{_esc(bot_r)}</code>")
        lines.append(f"   🗄️ DB: <code>{_esc(db_p)}</code> @ <code>{_esc(db_r)}</code>")
        if cross.get("cross_region") is True:
            if cross.get("inferred_from_rtt"):
                lines.append(f"   🚨 <b>منطقتان مختلفتان</b> <i>(مُستنتَج من RTT)</i>")
            else:
                lines.append(f"   🚨 <b>منطقتان مختلفتان!</b>")
        elif cross.get("cross_region") is False:
            if cross.get("inferred_from_rtt"):
                lines.append(f"   ✅ <b>نفس المنطقة</b> <i>(مُستنتَج من RTT)</i>")
            else:
                lines.append(f"   ✅ نفس المنطقة")
        else:
            lines.append(f"   ℹ️ لا يمكن التحديد بدقة")
        if cross.get("inference_reason"):
            lines.append(f"   💡 <i>{_esc(cross['inference_reason'])}</i>")
        lines.append("")
    db_type = str(probe.get("db_type", "?")).upper()
    host = probe.get("host", "")
    port = probe.get("port", "")
    if host and host != "?":
        lines.append(f"🗄️ <b>{_esc(db_type)}</b> @ <code>{_esc(host)}:{port}</code>")
    else:
        lines.append(f"🗄️ <b>{_esc(db_type)}</b> (محلي)")
    if probe.get("used_pool"):
        pool_ms = probe.get("pool_acquire_ms", 0)
        lines.append(f"   🏊 pool warm — acquire={pool_ms:.0f}ms")
    lines.append("")
    tcp = float(probe.get("tcp_connect_ms", 0) or 0)
    if tcp > 0:
        tcp_icon = ("🟢" if tcp < 5 else "🟢" if tcp < 15 else "🟡" if tcp < 50 else "🟠" if tcp < 150 else "🔴")
        lines.append(f"🌐 TCP connect: {tcp_icon} <b>{tcp:.0f}ms</b>")
    conn = float(probe.get("asyncpg_connect_ms", 0) or 0)
    if conn > 0:
        conn_icon = ("🟢" if conn < 100 else "🟡" if conn < 300 else "🔴")
        lines.append(f"🔌 connect: {conn_icon} <b>{conn:.0f}ms</b>")
        if tcp > 0:
            delta = conn - tcp
            if delta > 200:
                lines.append(f"   ⚠️ فرق TCP↔connect: +{delta:.0f}ms (TLS/auth بطيء)")
    elif probe.get("used_pool"):
        lines.append(f"🔌 connect: 🟢 <b>0ms</b> (من pool warm)")
    lines.append("")
    first = float(probe.get("first_query_ms", 0) or 0)
    if first > 0:
        first_icon = ("🟢" if first < 10 else "🟡" if first < 100 else "🔴")
        lines.append(f"⚡ أول استعلام: {first_icon} <b>{first:.0f}ms</b>")
    warm_median = float(probe.get("warm_median_ms", 0) or 0)
    warm_list = probe.get("warm_queries_ms", []) or []
    if warm_median > 0:
        warm_icon = ("🟢" if warm_median < 20 else "🟡" if warm_median < 100 else "🟠" if warm_median < 500 else "🔴")
        preview = ", ".join(f"{x:.0f}" for x in warm_list[:5])
        lines.append(f"🔥 warm (5x): {warm_icon} وسيط=<b>{warm_median:.0f}ms</b> [{preview}]")
    pk = float(probe.get("pk_select_ms", 0) or 0)
    if pk > 0:
        pk_icon = ("🟢" if pk < 20 else "🟡" if pk < 100 else "🔴")
        lines.append(f"🎯 PK SELECT: {pk_icon} <b>{pk:.0f}ms</b>")
    lines.append("")
    bulk = float(probe.get("bulk_fetch_ms", 0) or 0)
    bulk_rows = int(probe.get("bulk_rows", 0) or 0)
    if bulk > 0 and bulk_rows > 0:
        per_row = bulk / bulk_rows
        lines.append(f"📦 fetch 100: <b>{bulk:.0f}ms</b> ({per_row:.2f}ms/row)")
        lines.append("")
    verdict = str(probe.get("verdict", "unknown"))
    diagnosis = str(probe.get("diagnosis", ""))
    recommendation = str(probe.get("recommendation", ""))
    verdict_label = {"excellent": "🟢 ممتاز", "good": "🟢 جيد", "acceptable": "🟡 مقبول",
                     "slow": "🟠 بطيء", "critical": "🔴 حرج", "unknown": "⚪ غير معروف"}.get(verdict, "⚪ غير معروف")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 <b>الحكم:</b> {verdict_label}")
    lines.append("")
    if diagnosis:
        lines.append("<b>التشخيص:</b>")
        lines.append(f"  {diagnosis}")
    if recommendation:
        lines.append("")
        lines.append("<b>التوصية:</b>")
        lines.append(f"  {recommendation}")
    return "\n".join(lines)


async def diagnose_latency(*, force: bool = False) -> str:
    probe = await _probe_db_latency(force=force)
    return format_latency_report(probe)


async def get_latency_verdict() -> Dict[str, Any]:
    probe = await _probe_db_latency()
    return {
        "verdict": probe.get("verdict", "unknown"),
        "ok": probe.get("ok", False),
        "warm_median_ms": probe.get("warm_median_ms", 0),
        "tcp_connect_ms": probe.get("tcp_connect_ms", 0),
        "asyncpg_connect_ms": probe.get("asyncpg_connect_ms", 0),
        "pool_acquire_ms": probe.get("pool_acquire_ms", 0),
        "used_pool": probe.get("used_pool", False),
        "diagnosis": probe.get("diagnosis", ""),
        "recommendation": probe.get("recommendation", ""),
        "cross_region": probe.get("cross_region", {}),
        "active_db": probe.get("active_db", {}),
    }


# ═══════════════════════════════════════════════════════════════════════
# FULL HEALTH PROBE
# ═══════════════════════════════════════════════════════════════════════

async def _probe_network_to(host: str, port: int, *, with_tls: bool = False,
                            timeout: float = 5.0) -> Dict[str, Any]:
    result: Dict[str, Any] = {"host": host, "port": port, "ok": False}
    if not host or host == "?" or port <= 0:
        return result
    try:
        t0 = time.perf_counter()
        ip = await asyncio.wait_for(asyncio.to_thread(socket.gethostbyname, host),
                                     timeout=timeout)
        result["dns_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        result["resolved_ip"] = ip
    except Exception as e:
        result["dns_ms"] = -1.0
        result["error"] = f"DNS: {type(e).__name__}"
        return result
    def _do_tcp():
        t0 = time.perf_counter()
        s = socket.create_connection((host, port), timeout=timeout)
        ms = (time.perf_counter() - t0) * 1000
        return s, ms
    raw_sock = None
    try:
        raw_sock, tcp_ms = await asyncio.wait_for(asyncio.to_thread(_do_tcp),
                                                   timeout=timeout + 1.0)
        result["tcp_ms"] = round(tcp_ms, 2)
    except Exception as e:
        result["tcp_ms"] = -1.0
        result["error"] = f"TCP: {type(e).__name__}"
        return result
    finally:
        if raw_sock is not None:
            try:
                raw_sock.close()
            except Exception:
                pass
    if with_tls:
        tls_ms = -1.0
        tls_error: Optional[str] = None
        async def _do_tls_async() -> float:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            t0 = time.perf_counter()
            reader = None
            writer = None
            try:
                reader, writer = await asyncio.open_connection(host, port, ssl=ctx)
                return (time.perf_counter() - t0) * 1000
            finally:
                if writer is not None:
                    try:
                        writer.close()
                        await asyncio.wait_for(writer.wait_closed(), timeout=1.0)
                    except Exception:
                        pass
        try:
            tls_ms = await asyncio.wait_for(_do_tls_async(), timeout=timeout + 0.5)
            result["tls_ms"] = round(tls_ms, 2)
        except asyncio.TimeoutError:
            result["tls_ms"] = -1.0
            tls_error = f"TimeoutError (>{timeout + 0.5:.1f}s)"
        except asyncio.CancelledError:
            result["tls_ms"] = -1.0
            tls_error = "cancelled"
            raise
        except Exception as e:
            result["tls_ms"] = -1.0
            msg = str(e)[:80] if str(e) else type(e).__name__
            tls_error = f"{type(e).__name__}: {msg}"
        if tls_error:
            result["tls_error"] = tls_error
    result["ok"] = True
    return result


async def _probe_event_loop(samples: int = 10, sleep_ms: int = 50) -> Dict[str, Any]:
    result: Dict[str, Any] = {"ok": False, "samples_ms": [], "median_ms": 0.0,
                               "p90_ms": 0.0, "max_ms": 0.0, "_startup_window": False}
    try:
        loop = asyncio.get_running_loop()
        uptime = _uptime_sec()
        in_startup = uptime < _STARTUP_GRACE_SEC
        result["_startup_window"] = in_startup
        result["_uptime_sec"] = round(uptime, 1)
        for _ in range(2):
            t0 = loop.time()
            await asyncio.sleep(sleep_ms / 1000.0)
            _ = (loop.time() - t0) * 1000
        lags: List[float] = []
        for _ in range(samples):
            t0 = loop.time()
            await asyncio.sleep(sleep_ms / 1000.0)
            actual_ms = (loop.time() - t0) * 1000
            lag = max(0.0, actual_ms - sleep_ms)
            lags.append(lag)
        result["samples_ms"] = [round(x, 2) for x in lags]
        result["median_ms"] = round(statistics.median(lags), 2)
        sorted_lags = sorted(lags)
        result["p90_ms"] = round(_percentile(sorted_lags, 0.90), 2)
        result["max_ms"] = round(max(lags), 2)
        result["ok"] = True
    except Exception as e:
        result["error"] = str(e)
    return result


async def _probe_filesystem() -> Dict[str, Any]:
    result: Dict[str, Any] = {"ok": False}
    try:
        payload = b"x" * (1024 * 1024)
        async def _try_dir(d: Path, label: str) -> bool:
            try:
                test_file = d / "_latency_probe.bin"
                def _write_sync_read():
                    write_ms = 0.0
                    fsync_ms = 0.0
                    read_ms = 0.0
                    t0 = time.perf_counter()
                    with open(test_file, "wb") as f:
                        f.write(payload)
                        f.flush()
                        write_ms = (time.perf_counter() - t0) * 1000
                        t0 = time.perf_counter()
                        os.fsync(f.fileno())
                        fsync_ms = (time.perf_counter() - t0) * 1000
                    t0 = time.perf_counter()
                    _ = test_file.read_bytes()
                    read_ms = (time.perf_counter() - t0) * 1000
                    return write_ms, fsync_ms, read_ms
                write_ms, fsync_ms, read_ms = await asyncio.to_thread(_write_sync_read)
                result["write_1mb_ms"] = round(write_ms, 2)
                result["fsync_ms"] = round(fsync_ms, 2)
                result["read_1mb_ms"] = round(read_ms, 2)
                try:
                    test_file.unlink()
                except Exception:
                    pass
                result["tmp_dir"] = str(d)
                result["tmp_source"] = label
                result["ok"] = True
                return True
            except Exception as e:
                result["_last_dir_error"] = f"{label}: {e}"
                return False
        candidates = [(Path(tempfile.gettempdir()), "tempdir"),
                      (Path("/dev/shm"), "shm"),
                      (Path.cwd(), "cwd")]
        for d, label in candidates:
            try:
                if not d.exists() or not d.is_dir():
                    continue
            except Exception:
                continue
            if await _try_dir(d, label):
                break
        result.pop("_last_dir_error", None)
    except Exception as e:
        result["error"] = str(e)
    return result


async def _probe_system(*, prime_cpu: bool = False) -> Dict[str, Any]:
    result: Dict[str, Any] = {"ok": False}
    try:
        try:
            load1, load5, load15 = os.getloadavg()
            result["load_avg_1m"] = round(load1, 2)
            result["load_avg_5m"] = round(load5, 2)
            result["load_avg_15m"] = round(load15, 2)
        except (OSError, AttributeError):
            pass
        try:
            result["cpu_count"] = os.cpu_count() or 1
        except Exception:
            result["cpu_count"] = 1
        try:
            import psutil  # type: ignore
            vm = psutil.virtual_memory()
            result["ram_percent"] = round(vm.percent, 1)
            result["ram_used_mb"] = round(vm.used / (1024 ** 2), 1)
            result["ram_total_mb"] = round(vm.total / (1024 ** 2), 1)
            if prime_cpu:
                psutil.cpu_percent(interval=None)
                await asyncio.sleep(0.1)
                result["cpu_percent"] = round(psutil.cpu_percent(interval=None), 1)
                result["cpu_source"] = "local_prime"
        except ImportError:
            result["psutil"] = "not installed"
        result["ok"] = True
    except Exception as e:
        result["error"] = str(e)
    return result


def _identify_bottleneck(data: Dict[str, Any]) -> Dict[str, Any]:
    comps: List[Dict[str, Any]] = []
    def _add(name, kind, value, unit, severity, weight):
        comps.append({"component": name, "kind": kind,
                      "value": round(float(value), 1),
                      "unit": unit, "severity": severity,
                      "weight": round(float(weight), 2)})
    db_p = data.get("database") or {}
    cross = db_p.get("cross_region") or {}
    same_region_confirmed = (cross.get("cross_region") is False
                             and cross.get("inferred_from_rtt") is True)
    loop_p = data.get("event_loop") or {}
    in_startup = bool(loop_p.get("_startup_window", False))
    net_db = data.get("network_db") or {}
    db_tcp = float(net_db.get("tcp_ms") or 0)
    if same_region_confirmed:
        db_tcp = 0.0
    if db_tcp > 0:
        if db_tcp < _NET_DB_RTT_LOW_SAME_DC:
            sev = "low"
        elif db_tcp < _NET_DB_RTT_LOW_SAME_REGION:
            sev = "low"
        elif db_tcp < _NET_DB_RTT_MEDIUM:
            sev = "medium"
        elif db_tcp < _NET_DB_RTT_HIGH:
            sev = "high"
        else:
            sev = "critical"
        _add("network_db", "time", db_tcp, "ms", sev, db_tcp * 3.0)
    warm = float(db_p.get("warm_median_ms") or 0)
    if warm > 0:
        internal_ms = max(0.0, warm - db_tcp) if db_tcp > 0 else warm
        if internal_ms < _INTERNAL_DB_LOW:
            sev = "low"
        elif internal_ms < _INTERNAL_DB_MEDIUM:
            sev = "medium"
        elif internal_ms < _INTERNAL_DB_HIGH:
            sev = "high"
        else:
            sev = "critical"
        _add("database_internal", "time", internal_ms, "ms", sev, internal_ms * 3.0)
    lag = float(loop_p.get("p90_ms") or loop_p.get("median_ms") or 0)
    if lag > 0 and not in_startup:
        if lag < 20: sev = "low"
        elif lag < 50: sev = "medium"
        elif lag < 200: sev = "high"
        else: sev = "critical"
        _add("event_loop", "time", lag, "ms", sev, lag * 5.0)
    fs_p = data.get("filesystem") or {}
    fs_w = float(fs_p.get("write_1mb_ms") or 0)
    if fs_w > 0 and not in_startup:
        if fs_w < 30: sev = "low"
        elif fs_w < 100: sev = "medium"
        elif fs_w < 500: sev = "high"
        else: sev = "critical"
        _add("filesystem", "time", fs_w, "ms", sev, fs_w * 0.5)
    sys_p = data.get("system") or {}
    cpu = float(sys_p.get("cpu_percent") or 0)
    if cpu > 0 and not in_startup:
        if cpu < 70: sev = "low"
        elif cpu < 85: sev = "medium"
        elif cpu < 95: sev = "high"
        else: sev = "critical"
        _add("cpu", "percent", cpu, "%", sev, cpu * 1.0)
    ram = float(sys_p.get("ram_percent") or 0)
    if ram > 0 and not in_startup:
        if ram < 85: sev = "low"
        elif ram < 92: sev = "medium"
        elif ram < 97: sev = "high"
        else: sev = "critical"
        _add("ram", "percent", ram, "%", sev, ram * 0.8)
    net_tg = data.get("network_telegram") or {}
    tg_tcp = float(net_tg.get("tcp_ms") or 0)
    if tg_tcp > 0:
        if tg_tcp < 300: sev = "low"
        elif tg_tcp < 500: sev = "medium"
        elif tg_tcp < 800: sev = "high"
        else: sev = "critical"
        _add("network_telegram", "time", tg_tcp, "ms", sev, tg_tcp * 0.2)
    comps.sort(key=lambda x: -x["weight"])
    sev_rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    max_sev = "low"
    for c in comps:
        if sev_rank.get(c["severity"], 0) > sev_rank.get(max_sev, 0):
            max_sev = c["severity"]
    if max_sev == "low" or not comps:
        return {"primary": "none", "severity": "low",
                "explanation": "🟢 لا يوجد bottleneck — كل الأبعاد طبيعية.",
                "recommendation": "الأداء جيد — لا حاجة لتعديل.",
                "ranked": comps, "cross_region": cross,
                "startup_window": in_startup}
    candidates = [c for c in comps if c["severity"] == max_sev]
    candidates.sort(key=lambda x: -x["weight"])
    top = candidates[0]
    top_name = top["component"]
    tv = top["value"]
    tu = top["unit"]
    explanations = {
        "network_db": (f"🟠 الشبكة بين البوت و DB تُضيف ~{tv:.0f}{tu} لكل استعلام (TCP RTT)."),
        "database_internal": (f"🟠 DB نفسه بطيء: زمن داخلي = {tv:.0f}{tu} "
                              f"(بعد خصم RTT الشبكة — المتوقع < {_INTERNAL_DB_LOW:.0f}ms)."),
        "event_loop": (f"🟠 Event loop lag (p90) = {tv:.0f}{tu} — البوت مشبع."),
        "filesystem": f"🟠 كتابة 1MB تستغرق {tv:.0f}{tu}.",
        "cpu": f"🟠 CPU = {tv:.0f}{tu} — الخادم مشبع.",
        "ram": f"🟠 RAM = {tv:.0f}{tu} — احتمال swap.",
        "network_telegram": f"🟡 RTT إلى Telegram = {tv:.0f}{tu}.",
    }
    recommendations = {
        "network_db": ("✅ انقل البوت و DB إلى نفس المنطقة الجغرافية. "
                       "استخدم PgBouncer قريباً من البوت لتقليل round-trips. "
                       "قلّل عدد الاستعلامات في المسارات الساخنة (N+1 patterns)."),
        "database_internal": ("✅ راجع pg_stat_activity، شغّل VACUUM ANALYZE، "
                              "اضبط shared_buffers (≥ 25% RAM)."),
        "event_loop": ("✅ ابحث عن استدعاءات sync في async code: requests، "
                       "time.sleep، psycopg2، file I/O."),
        "filesystem": "✅ تجنّب كتابة ملفات كبيرة. استخدم /tmp فقط.",
        "cpu": ("✅ قلّل MAX_CHANNELS_PER_CYCLE، راجع العمليات الثقيلة "
                "(OCR، NSFW)، ارفع الـ tier."),
        "ram": "✅ راجع caches، قلّل max_size، ارفع الـ tier.",
        "network_telegram": ("✅ عادةً لا يحتاج إجراءً. تحقّق من status.telegram.org "
                             "فقط إذا تجاوز 600ms."),
    }
    if top_name == "network_db" and cross.get("cross_region") is True:
        bot_r_raw = cross.get("bot_region", "?")
        db_r_raw = cross.get("db_region", "?")
        bot_r = _esc(bot_r_raw)
        db_r = _esc(db_r_raw)
        inferred = cross.get("inferred_from_rtt", False)
        note = " (مُستنتَج من RTT)" if inferred else ""
        recommendations["network_db"] = (
            f"🚨 <b>Cross-Region مؤكّد{note}</b>: "
            f"البوت في <code>{bot_r}</code>، DB في <code>{db_r}</code>.\n"
            f"✅ <b>الحل الجذري</b>: انقل البوت إلى <code>{db_r}</code> "
            f"أو DB إلى <code>{bot_r}</code> → RTT ينخفض من "
            f"{tv:.0f}ms إلى 1-3ms (تسريع 10-40×).\n"
            f"⚡ <b>حل مؤقت</b>: PgBouncer قد يوفّر 30-50%.")
        explanations["network_db"] = (
            f"🚨 Cross-Region{note}: البوت ({bot_r}) و DB ({db_r}) في "
            f"منطقتين مختلفتين. RTT = {tv:.0f}{tu}.")
    elif top_name == "network_db" and cross.get("cross_region") is False:
        recommendations["network_db"] = (
            f"✅ <b>البوت و DB في نفس المنطقة</b>"
            f"{' (مُستنتَج من RTT)' if cross.get('inferred_from_rtt') else ''}. "
            f"RTT={tv:.0f}ms طبيعي للشبكة الداخلية.\n"
            f"💡 لتحسين أكثر: قلّل عدد الاستعلامات في المسارات الساخنة "
            f"(N+1 patterns).")
    return {"primary": top_name, "severity": max_sev,
            "explanation": explanations.get(top_name, ""),
            "recommendation": recommendations.get(top_name, ""),
            "ranked": comps, "cross_region": cross,
            "startup_window": in_startup}


async def _probe_full_health(*, force: bool = False) -> Dict[str, Any]:
    if not force:
        cached = _cache_get("full_health")
        if cached is not None:
            return cached
    result: Dict[str, Any] = {"ok": False, "ts": time.time()}
    db = _get_db()
    db_host = "?"
    db_port = 0
    if db is not None:
        active = _detect_active_db_source(db)
        url = active.get("active_url", "")
        if url:
            comp = active.get("components", {})
            db_host = comp.get("host", "?")
            db_port = comp.get("port", 0) or (5432 if "postgres" in url.lower() else 3306)
        else:
            url = (getattr(db, "DATABASE_URL", "") or os.getenv("DATABASE_URL", ""))
            try:
                p = urlparse(url)
                db_host = p.hostname or "?"
                db_port = p.port or (5432 if "postgres" in url.lower() else 3306)
            except Exception:
                pass
    _cpu_primed = False
    try:
        import psutil  # type: ignore
        psutil.cpu_percent(interval=None)
        _cpu_primed = True
    except ImportError:
        pass
    _t_gather_start = time.monotonic()
    async def _cached_telegram_probe():
        cached = _cache_get("telegram_network")
        if cached is not None:
            return cached
        res = await _probe_network_to("api.telegram.org", 443, with_tls=True)
        _cache_set("telegram_network", res, ttl=_TELEGRAM_PROBE_CACHE_TTL)
        return res
    db_latency_result: Dict[str, Any] = {}
    try:
        db_latency_result = await _probe_db_latency(force=force)
    except Exception as e:
        logger.debug(f"_probe_db_latency in full_health: {e}")
        db_latency_result = {"ok": False, "error": str(e)[:120]}
    probes = await asyncio.gather(
        _cached_telegram_probe(), _probe_event_loop(),
        _probe_filesystem(), _probe_system(prime_cpu=False),
        return_exceptions=True)
    _gather_elapsed = time.monotonic() - _t_gather_start
    def _safe(x, default):
        return default if isinstance(x, BaseException) else x
    result["network_telegram"] = _safe(probes[0], {})
    result["event_loop"] = _safe(probes[1], {})
    result["filesystem"] = _safe(probes[2], {})
    result["system"] = _safe(probes[3], {})
    result["database"] = db_latency_result
    loop_dict = result.get("event_loop")
    startup_window = bool(isinstance(loop_dict, dict)
                          and loop_dict.get("_startup_window", False))
    if isinstance(result["system"], dict):
        result["system"]["_startup_window"] = startup_window
    if isinstance(result["filesystem"], dict):
        result["filesystem"]["_startup_window"] = startup_window
    tcp_from_latency = float(db_latency_result.get("tcp_connect_ms", 0) or 0)
    if tcp_from_latency > 0:
        result["network_db"] = {"ok": True,
                                "host": db_latency_result.get("host", db_host),
                                "port": db_latency_result.get("port", db_port),
                                "tcp_ms": tcp_from_latency, "dns_ms": 0, "tls_ms": 0,
                                "_source": "reused_from_latency_probe"}
    elif db_host != "?" and db_port > 0:
        try:
            net_db = await _probe_network_to(db_host, db_port, with_tls=True)
            net_db["_source"] = "fallback_standalone"
            result["network_db"] = net_db
        except Exception as e:
            logger.debug(f"fallback network_db probe: {e}")
            result["network_db"] = {}
    else:
        result["network_db"] = {}
    if _cpu_primed:
        try:
            import psutil  # type: ignore
            real_cpu = psutil.cpu_percent(interval=None)
            if not isinstance(result["system"], dict):
                result["system"] = {}
            result["system"]["cpu_percent"] = round(real_cpu, 1)
            result["system"]["cpu_window_sec"] = round(_gather_elapsed, 2)
            result["system"]["cpu_source"] = "probe_window"
        except Exception:
            pass
    if not isinstance(result["system"], dict):
        result["system"] = {"ok": True, "error": "system probe failed"}
    result["ok"] = True
    result["bottleneck"] = _identify_bottleneck(result)
    loop_win = bool((result.get("event_loop") or {}).get("_startup_window", False))
    ttl = _FULL_HEALTH_TTL_STARTUP if loop_win else _FULL_HEALTH_TTL_NORMAL
    _cache_set("full_health", result, ttl=ttl)
    return result


def format_full_health_report(data: Dict[str, Any]) -> str:
    if not data.get("ok"):
        return "❌ فشل التشخيص الشامل"
    lines: List[str] = []
    lines.append("🏥 <b>التشخيص الشامل — Full Health Probe</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    active_line = format_active_db_line()
    if active_line:
        lines.append(active_line)
        lines.append("")
    try:
        _active = _detect_active_db_source(_get_db())
        if _active.get("pool_size", 0) > 0 or _active.get("pool_current", 0) > 0:
            lines.append(f"   {_format_pool_line(_active)}")
            lines.append("")
    except Exception:
        pass
    loop_p = data.get("event_loop") or {}
    startup_window = bool(loop_p.get("_startup_window", False))
    if startup_window:
        uptime = loop_p.get("_uptime_sec", 0)
        lines.append(f"🟡 <b>نافذة إقلاع ({uptime:.0f}s منذ البدء)</b>\n"
                     f"   <i>قياسات CPU / RAM / Event Loop / القرص "
                     f"غير موثوقة حتى 60s — أعد التشخيص لاحقاً.</i>")
        lines.append("")
    b = data.get("bottleneck") or {}
    severity = b.get("severity", "low")
    primary = b.get("primary", "none")
    icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
    cross = b.get("cross_region") or {}
    if cross.get("cross_region") is True:
        bot_r = cross.get("bot_region", "?")
        db_r = cross.get("db_region", "?")
        inferred = cross.get("inferred_from_rtt", False)
        note = " <i>(مُستنتَج من RTT)</i>" if inferred else ""
        lines.append(f"🚨 <b>تحذير Cross-Region{note}:</b>\n"
                     f"   🤖 البوت: <code>{_esc(bot_r)}</code>\n"
                     f"   🗄️ DB: <code>{_esc(db_r)}</code>\n"
                     f"   ⚠️ منطقتان مختلفتان — كل استعلام يقطع مسافة "
                     f"جغرافية (~500-5000km).")
        lines.append("")
    elif cross.get("cross_region") is False and cross.get("inferred_from_rtt"):
        reason_txt = _esc(cross.get("inference_reason", ""))
        lines.append(f"✅ <b>نفس المنطقة</b> <i>({reason_txt})</i>")
        lines.append("")
    if primary == "none":
        lines.append(f"{icon} <b>لا يوجد bottleneck — كل الأبعاد سليمة.</b>")
        if b.get("recommendation"):
            lines.append(f"   {b['recommendation']}")
    else:
        lines.append(f"{icon} <b>السبب الرئيسي للبطء:</b>")
        if b.get("explanation"):
            lines.append(f"   {b['explanation']}")
        if b.get("recommendation"):
            lines.append(f"   {b['recommendation']}")
    lines.append("")
    ranked = b.get("ranked") or []
    if ranked:
        lines.append("📊 <b>ترتيب الأبعاد (من الأعلى تأثيراً):</b>")
        for i, item in enumerate(ranked[:7], 1):
            name = item.get("component", "?")
            val = item.get("value", 0)
            unit = item.get("unit", "ms")
            sev = item.get("severity", "low")
            ic = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(sev, "⚪")
            lines.append(f"  {i}. {ic} <code>{_esc(name)}</code> {val:.0f}{unit}")
        lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📋 <b>القياسات الكاملة:</b>")
    lines.append("")
    net_db = data.get("network_db") or {}
    if net_db.get("ok"):
        lines.append("🌐 <b>الشبكة → DB</b>")
        source = net_db.get("_source", "")
        if source == "reused_from_latency_probe":
            lines.append("   <i>(قياس موحّد من latency probe)</i>")
        if net_db.get("dns_ms", 0) > 0:
            lines.append(f"   DNS: <b>{net_db['dns_ms']:.0f}ms</b>")
        if net_db.get("tcp_ms", 0) > 0:
            lines.append(f"   TCP: <b>{net_db['tcp_ms']:.0f}ms</b>")
        if net_db.get("tls_ms", 0) > 0:
            lines.append(f"   TLS: <b>{net_db['tls_ms']:.0f}ms</b> <i>(setup — لمرة واحدة)</i>")
        if net_db.get("tls_error"):
            lines.append(f"   ⚠️ TLS: <i>{_esc(net_db['tls_error'])}</i>")
        lines.append("")
    net_tg = data.get("network_telegram") or {}
    if net_tg.get("ok"):
        lines.append("📨 <b>الشبكة → Telegram</b>")
        if net_tg.get("tcp_ms", 0) > 0:
            lines.append(f"   TCP: <b>{net_tg['tcp_ms']:.0f}ms</b>")
        if net_tg.get("tls_ms", 0) > 0:
            lines.append(f"   TLS: <b>{net_tg['tls_ms']:.0f}ms</b>")
        if net_tg.get("tls_error"):
            lines.append(f"   ⚠️ TLS: <i>{_esc(net_tg['tls_error'])}</i>")
        lines.append("")
    db_p = data.get("database") or {}
    if db_p.get("ok"):
        lines.append("🗄️ <b>DB Internal</b>")
        if db_p.get("used_pool"):
            pool_ms = db_p.get("pool_acquire_ms", 0)
            lines.append(f"   pool acquire: <b>{pool_ms:.0f}ms</b> <i>(pool warm)</i>")
        if db_p.get("asyncpg_connect_ms", 0) > 0:
            lines.append(f"   connect: <b>{db_p['asyncpg_connect_ms']:.0f}ms</b>")
        elif db_p.get("used_pool"):
            lines.append("   connect: <b>0ms</b> <i>(pool warm)</i>")
        if db_p.get("first_query_ms", 0) > 0:
            lines.append(f"   first query: <b>{db_p['first_query_ms']:.0f}ms</b>")
        if db_p.get("warm_median_ms", 0) > 0:
            lines.append(f"   warm median: <b>{db_p['warm_median_ms']:.0f}ms</b>")
        if db_p.get("pk_select_ms", 0) > 0:
            lines.append(f"   PK SELECT: <b>{db_p['pk_select_ms']:.0f}ms</b>")
        if db_p.get("bulk_fetch_ms", 0) > 0:
            lines.append(f"   bulk 100: <b>{db_p['bulk_fetch_ms']:.0f}ms</b>")
        lines.append("")
    if loop_p.get("ok"):
        lines.append("🔄 <b>Event Loop</b>")
        if loop_p.get("_startup_window"):
            uptime = loop_p.get("_uptime_sec", 0)
            lines.append(f"   🟡 <i>نافذة إقلاع ({uptime:.0f}s منذ البدء) — "
                         f"القياسات غير موثوقة</i>")
            lines.append("   <i>ستصبح دقيقة بعد 60s من التشغيل.</i>")
            lines.append("")
        median_v = float(loop_p.get('median_ms', 0) or 0)
        p90_v = float(loop_p.get('p90_ms', 0) or 0)
        max_v = float(loop_p.get('max_ms', 0) or 0)
        med_icon = ("🟢" if median_v < 5 else "🟡" if median_v < 20 else "🔴")
        lines.append(f"   {med_icon} lag median: <b>{median_v:.0f}ms</b> <i>(الأساسي)</i>")
        if p90_v > 0:
            p90_icon = ("🟢" if p90_v < 20 else "🟡" if p90_v < 100 else "🔴")
            lines.append(f"   {p90_icon} lag p90: <b>{p90_v:.0f}ms</b>")
        if max_v > 1000:
            lines.append(f"   🔴 lag max: <b>{max_v:.0f}ms</b> <i>(spike معزول)</i>")
        elif max_v > 0:
            max_icon = ("🟢" if max_v < 100 else "🟡" if max_v < 500 else "🟠")
            lines.append(f"   {max_icon} lag max: <b>{max_v:.0f}ms</b>")
        lines.append("")
    fs_p = data.get("filesystem") or {}
    if fs_p.get("ok"):
        lines.append("💾 <b>القرص (1MB)</b>")
        fs_startup = bool(fs_p.get("_startup_window", False))
        fs_note = " <i>(مضخَّم — إقلاع)</i>" if fs_startup else ""
        lines.append(f"   write: <b>{fs_p.get('write_1mb_ms', 0):.0f}ms</b>{fs_note}")
        lines.append(f"   fsync: <b>{fs_p.get('fsync_ms', 0):.0f}ms</b>")
        lines.append(f"   read: <b>{fs_p.get('read_1mb_ms', 0):.0f}ms</b>")
        src = fs_p.get("tmp_source")
        if src and src != "tempdir":
            lines.append(f"   <i>(قياس على {_esc(src)})</i>")
        lines.append("")
    sys_p = data.get("system") or {}
    if sys_p.get("ok"):
        lines.append("⚙️ <b>النظام</b>")
        sys_startup = bool(sys_p.get("_startup_window", False))
        cpu_startup_note = " <i>(مضخَّم — إقلاع)</i>" if sys_startup else ""
        if "cpu_percent" in sys_p:
            cpu_val = sys_p["cpu_percent"]
            window = sys_p.get("cpu_window_sec")
            if window:
                lines.append(f"   CPU: <b>{cpu_val:.0f}%</b>{cpu_startup_note} <i>(نافذة {window:.1f}s)</i>")
            else:
                lines.append(f"   CPU: <b>{cpu_val:.0f}%</b>{cpu_startup_note}")
        if "ram_percent" in sys_p:
            ram_note = " <i>(إقلاع)</i>" if sys_startup else ""
            lines.append(f"   RAM: <b>{sys_p['ram_percent']:.0f}%</b>{ram_note} "
                         f"({sys_p.get('ram_used_mb', 0):.0f}/{sys_p.get('ram_total_mb', 0):.0f}MB)")
        if "load_avg_1m" in sys_p:
            load_note = " <i>(مضخَّم — إقلاع)</i>" if sys_startup else ""
            lines.append(f"   Load: <b>{sys_p['load_avg_1m']}</b> / "
                         f"{sys_p['load_avg_5m']} / {sys_p['load_avg_15m']}{load_note}")
        if "cpu_count" in sys_p:
            lines.append(f"   CPUs: <b>{sys_p['cpu_count']}</b>")
        lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🕐 <i>{_now_iso()}</i>")
    return "\n".join(lines)


async def diagnose_full(*, force: bool = False) -> str:
    data = await _probe_full_health(force=force)
    return format_full_health_report(data)


async def get_full_health() -> Dict[str, Any]:
    return await _probe_full_health()


# ═══════════════════════════════════════════════════════════════════════
# 1) DB Metadata
# ═══════════════════════════════════════════════════════════════════════

async def _get_db_metadata() -> Dict[str, Any]:
    cached = _cache_get("db_metadata")
    if cached is not None:
        return cached
    db = _get_db()
    meta: Dict[str, Any] = {"size_bytes": 0, "size_display": "?",
                             "current_schema": "?", "schemas": [],
                             "database_name": "?"}
    if db is None:
        return meta
    try:
        if _is_postgres():
            row = await db.fetchone("""
                SELECT
                    pg_database_size(current_database())::bigint AS size_bytes,
                    current_database() AS database_name,
                    current_schema() AS current_schema,
                    COALESCE((SELECT array_agg(nspname ORDER BY nspname)
                              FROM pg_namespace
                              WHERE nspname NOT LIKE 'pg_%'
                                AND nspname <> 'information_schema'),
                             ARRAY[]::text[]) AS schemas
            """) or {}
            size_b = int(row.get("size_bytes") or 0)
            meta["size_bytes"] = size_b
            meta["size_display"] = _fmt_bytes(size_b)
            meta["database_name"] = row.get("database_name") or "?"
            meta["current_schema"] = row.get("current_schema") or "public"
            schemas_raw = row.get("schemas")
            if isinstance(schemas_raw, list):
                meta["schemas"] = [str(s) for s in schemas_raw if s]
            elif isinstance(schemas_raw, (tuple, set)):
                meta["schemas"] = [str(s) for s in schemas_raw if s]
            else:
                meta["schemas"] = []
        elif _is_mysql():
            row = await db.fetchone("""
                SELECT
                    COALESCE((SELECT SUM(data_length + index_length)
                              FROM information_schema.TABLES
                              WHERE TABLE_SCHEMA = DATABASE()), 0) AS size_bytes,
                    DATABASE() AS database_name,
                    DATABASE() AS current_schema,
                    COALESCE((SELECT GROUP_CONCAT(SCHEMA_NAME ORDER BY SCHEMA_NAME SEPARATOR ',')
                              FROM information_schema.SCHEMATA
                              WHERE SCHEMA_NAME NOT IN (
                                  'information_schema','mysql',
                                  'performance_schema','sys')), '') AS schemas_csv
            """) or {}
            size_b = int(row.get("size_bytes") or 0)
            meta["size_bytes"] = size_b
            meta["size_display"] = _fmt_bytes(size_b)
            meta["database_name"] = row.get("database_name") or "?"
            meta["current_schema"] = row.get("current_schema") or "?"
            schemas_csv = row.get("schemas_csv") or ""
            if isinstance(schemas_csv, str):
                meta["schemas"] = [s for s in schemas_csv.split(",") if s]
            else:
                meta["schemas"] = []
        else:
            size_kb = (await db.get_db_size_kb()
                       if hasattr(db, "get_db_size_kb") else 0)
            meta["size_bytes"] = int(size_kb * 1024)
            meta["size_display"] = _fmt_bytes(meta["size_bytes"])
            meta["current_schema"] = "main"
            meta["schemas"] = ["main"]
            meta["database_name"] = "sqlite"
    except Exception as e:
        logger.debug(f"_get_db_metadata: {e}")
        _cache_set("db_metadata", meta, ttl=_NEGATIVE_CACHE_TTL)
        return meta
    _cache_set("db_metadata", meta, ttl=300.0)
    return meta


# ═══════════════════════════════════════════════════════════════════════
# 2) Dead Tuples
# ═══════════════════════════════════════════════════════════════════════

_HEALTH_FAILED_SENTINEL: Tuple[None, None] = (None, None)


async def _get_all_tables_health() -> Tuple[Optional[List[Dict]], Optional[List[Dict]]]:
    cached = _cache_get("all_tables_health")
    if cached is not None:
        if isinstance(cached, tuple) and len(cached) == 2:
            return cached
        return None, None
    db = _get_db()
    if db is None or not _is_postgres():
        if db is None:
            return None, None
        return [], []
    try:
        rows = await db.fetchall("""
            SELECT
                s.relname AS table_name,
                c.relkind AS relkind,
                COALESCE(s.n_live_tup, 0) AS live_tuples,
                COALESCE(s.n_dead_tup, 0) AS dead_tuples,
                COALESCE(s.n_mod_since_analyze, 0) AS n_mod_since_analyze,
                s.last_vacuum, s.last_autovacuum,
                s.last_analyze, s.last_autoanalyze,
                c.reloptions
            FROM pg_stat_user_tables s
            LEFT JOIN pg_class c ON c.oid = s.relid
            WHERE s.schemaname = current_schema()
              AND c.relkind IN ('r', 'm')
            ORDER BY COALESCE(s.n_dead_tup, 0) DESC,
                     COALESCE(s.n_live_tup, 0) DESC
        """) or []
    except Exception as e:
        logger.warning(f"_get_all_tables_health: {e}")
        _cache_set("all_tables_health", _HEALTH_FAILED_SENTINEL, ttl=_NEGATIVE_CACHE_TTL)
        return None, None
    dirty = []
    clean = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = r.get("table_name") or "?"
        relkind = str(r.get("relkind") or "r")
        is_matview = relkind == "m"
        live = int(r.get("live_tuples") or 0)
        dead = int(r.get("dead_tuples") or 0)
        total = live + dead
        ratio = (dead / total) if total > 0 else 0.0
        n_mod = int(r.get("n_mod_since_analyze") or 0)
        opts = r.get("reloptions") or []
        av_scale = None
        an_scale = None
        for opt in opts:
            if isinstance(opt, str):
                if "autovacuum_vacuum_scale_factor=" in opt:
                    try:
                        av_scale = float(opt.split("=")[1])
                    except Exception:
                        pass
                elif "autovacuum_analyze_scale_factor=" in opt:
                    try:
                        an_scale = float(opt.split("=")[1])
                    except Exception:
                        pass
        auto_tuned = av_scale is not None and an_scale is not None
        last_av = r.get("last_vacuum") or r.get("last_autovacuum")
        last_an = r.get("last_analyze") or r.get("last_autoanalyze")
        entry = {"name": name, "relkind": relkind, "is_matview": is_matview,
                 "live": live, "dead": dead, "total": total, "ratio": ratio,
                 "n_mod": n_mod, "last_av": last_av, "last_an": last_an,
                 "auto_tuned": auto_tuned, "av_scale": av_scale, "an_scale": an_scale}
        if dead > 0:
            dirty.append(entry)
        else:
            clean.append(entry)
    result = (dirty, clean)
    _cache_set("all_tables_health", result, ttl=60.0)
    return result


# ═══════════════════════════════════════════════════════════════════════
# 3) Activity Stats
# ═══════════════════════════════════════════════════════════════════════

async def _get_activity_stats(*, force: bool = False) -> Dict[str, Any]:
    if not force:
        cached = _cache_get("activity_stats")
        if cached is not None:
            return cached
    out: Dict[str, Any] = {"long_tx": 0, "idle_tx": 0,
                            "vacuum_running": 0, "total_active": 0,
                            "total_connections": 0}
    db = _get_db()
    if db is None or not _is_postgres():
        _cache_set("activity_stats", out, ttl=5.0)
        return out
    long_tx_sec = _LONG_TX_THRESHOLD_SECONDS
    try:
        row = await db.fetchone(f"""
            SELECT
                count(*) FILTER (WHERE state = 'active') AS active,
                count(*) FILTER (WHERE state = 'idle in transaction') AS idle_tx,
                count(*) FILTER (WHERE state = 'active'
                                 AND now() - xact_start > interval '{long_tx_sec} seconds') AS long_tx,
                count(*) FILTER (WHERE query ILIKE 'VACUUM%' AND state = 'active') AS vacuum_running,
                count(*) AS total
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
        """) or {}
        if isinstance(row, dict):
            out["total_active"] = int(row.get("active") or 0)
            out["idle_tx"] = int(row.get("idle_tx") or 0)
            out["long_tx"] = int(row.get("long_tx") or 0)
            out["vacuum_running"] = int(row.get("vacuum_running") or 0)
            out["total_connections"] = int(row.get("total") or 0)
    except Exception as e:
        logger.debug(f"_get_activity_stats: {e}")
    _cache_set("activity_stats", out, ttl=5.0)
    return out


# ═══════════════════════════════════════════════════════════════════════
# 4) PG Settings
# ═══════════════════════════════════════════════════════════════════════

_CRITICAL_SETTINGS = (
    "autovacuum", "autovacuum_naptime",
    "autovacuum_vacuum_scale_factor", "autovacuum_analyze_scale_factor",
    "autovacuum_vacuum_threshold", "autovacuum_analyze_threshold",
    "autovacuum_max_workers", "max_connections",
    "shared_buffers", "work_mem", "synchronous_commit",
    "idle_in_transaction_session_timeout",
    "statement_timeout", "server_version",
)


async def _get_pg_settings() -> Dict[str, str]:
    cached = _cache_get("pg_settings")
    if cached is not None:
        return cached
    db = _get_db()
    if db is None or not _is_postgres():
        return {}
    try:
        rows = await db.fetchall("""
            SELECT name, setting, unit FROM pg_settings
            WHERE name = ANY($1::text[])
        """, (list(_CRITICAL_SETTINGS),)) or []
        out: Dict[str, str] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            name = r.get("name")
            setting = r.get("setting") or ""
            unit = r.get("unit") or ""
            out[name] = f"{setting}{unit}" if unit else str(setting)
        _cache_set("pg_settings", out, ttl=600.0)
        return out
    except Exception as e:
        logger.debug(f"_get_pg_settings: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════
# 5) Sizes + Indexes
# ═══════════════════════════════════════════════════════════════════════

async def _get_table_sizes(limit: int = 15) -> List[Dict[str, Any]]:
    cache_key = f"table_sizes_{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    db = _get_db()
    if db is None or not _is_postgres():
        return []
    fn = getattr(db, "get_table_sizes", None)
    if not callable(fn):
        return []
    try:
        result = await fn(limit) or []
        _cache_set(cache_key, result, ttl=300.0)
        return result
    except Exception as e:
        logger.debug(f"_get_table_sizes: {e}")
        return []


async def _get_indexes(tables: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    cache_key = _hash_key("indexes", tables)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    db = _get_db()
    if db is None or not _is_postgres():
        return {}
    fn = getattr(db, "get_indexes_info", None)
    if not callable(fn):
        return {}
    try:
        result = await fn(tables) or {}
        _cache_set(cache_key, result, ttl=300.0)
        return result
    except Exception as e:
        logger.debug(f"_get_indexes: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════
# 6) Auto-Cleanup Status
# ═══════════════════════════════════════════════════════════════════════

_SQL_TABLE_TOTAL_SIZE = """
    SELECT c.relname AS table_name,
           (
               c.relpages::bigint * current_setting('block_size')::int
               + COALESCE((
                   SELECT SUM(i.relpages)::bigint * current_setting('block_size')::int
                   FROM pg_index idx
                   JOIN pg_class i ON i.oid = idx.indexrelid
                   WHERE idx.indrelid = c.oid
               ), 0)
               + CASE WHEN c.relkind = 'p' THEN
                   COALESCE((
                       SELECT SUM(
                           pc.relpages
                           + COALESCE((
                               SELECT SUM(pi.relpages)
                               FROM pg_index pidx
                               JOIN pg_class pi ON pi.oid = pidx.indexrelid
                               WHERE pidx.indrelid = pc.oid
                           ), 0)
                       )::bigint * current_setting('block_size')::int
                       FROM pg_inherits inh
                       JOIN pg_class pc ON pc.oid = inh.inhrelid
                       WHERE inh.inhparent = c.oid
                   ), 0)
                 ELSE 0
               END
           ) AS total_bytes
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = current_schema()
      AND c.relname = ANY($1::text[])
      AND c.relkind IN ('r', 'm', 'p')
"""


async def _get_cleanup_status() -> List[Dict[str, Any]]:
    db = _get_db()
    if db is None or not _is_postgres():
        return []
    deletable = [k for k, v in _CLEANUP_POLICY.items() if not v.get("protected")]
    if not deletable:
        return []
    try:
        rows = await db.fetchall(_SQL_TABLE_TOTAL_SIZE, (deletable,)) or []
    except Exception as e:
        logger.warning(f"_get_cleanup_status: {e}")
        return [{
            "name": "__error__",
            "bytes": 0,
            "display": "—",
            "color": "❌",
            "status": f"فشل: {str(e)[:60]}",
            "retention_days": 0,
            "max_mb": 0,
        }]
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = r.get("table_name")
        if name not in _CLEANUP_POLICY:
            continue
        policy = _CLEANUP_POLICY[name]
        retention_days = policy["retention"]
        max_mb = policy["max_mb"]
        b = int(r.get("total_bytes") or 0)
        kb = b / 1024
        threshold_kb = max_mb * 1024
        if kb >= threshold_kb:
            color = "🔴"
            status = f"تجاوز الحد ({max_mb}MB) — سيُنظَّف"
        elif kb >= threshold_kb * 0.75:
            color = "🟡"
            status = f"قريب من الحد ({max_mb}MB)"
        else:
            color = "🟢"
            status = f"ضمن الحد ({max_mb}MB)"
        out.append({"name": name, "bytes": b, "display": _fmt_bytes(b),
                    "color": color, "status": status,
                    "retention_days": retention_days, "max_mb": max_mb})
    out.sort(key=lambda x: ({"🔴": 0, "🟡": 1, "🟢": 2}.get(x["color"], 3), -x["bytes"]))
    return out


# ═══════════════════════════════════════════════════════════════════════
# 7) Table Names Helper
# ═══════════════════════════════════════════════════════════════════════

async def _get_all_table_names() -> List[str]:
    cached = _cache_get("all_table_names")
    if cached is not None:
        return cached
    db = _get_db()
    if db is None:
        return []
    db_type = _get_db_type()
    if db_type == "MYSQL":
        try:
            rows = await db.fetchall(
                "SELECT TABLE_NAME AS tablename FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "  AND TABLE_TYPE IN ('BASE TABLE', 'VIEW') ORDER BY TABLE_NAME") or []
            result = [r.get("tablename") or r.get("TABLE_NAME")
                      for r in rows if isinstance(r, dict)]
            result = [t for t in result if t]
            _cache_set("all_table_names", result, ttl=300.0)
            return result
        except Exception as e:
            logger.warning(f"_get_all_table_names (MySQL): {e}")
            return []
    if _is_postgres():
        try:
            rows = await db.fetchall("""
                SELECT c.relname AS tablename
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = current_schema()
                  AND c.relkind IN ('r', 'm')
                ORDER BY c.relkind DESC, c.relname
            """) or []
            result = [r.get("tablename") for r in rows
                      if isinstance(r, dict) and r.get("tablename")]
            _cache_set("all_table_names", result, ttl=300.0)
            return result
        except Exception as e:
            logger.debug(f"_get_all_table_names (PG): {e}")
            try:
                rows = await db.fetchall("""
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = current_schema()
                    ORDER BY tablename
                """) or []
                result = [r.get("tablename") for r in rows
                          if isinstance(r, dict) and r.get("tablename")]
                _cache_set("all_table_names", result, ttl=300.0)
                return result
            except Exception:
                return []
    try:
        rows = await db.fetchall(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'") or []
        result = [r.get("name") for r in rows
                  if isinstance(r, dict) and r.get("name")]
        _cache_set("all_table_names", result, ttl=300.0)
        return result
    except Exception as e:
        logger.debug(f"_get_all_table_names (SQLite): {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════
# 8) Score
# ═══════════════════════════════════════════════════════════════════════

def _calc_technical_score(dirty, activity, settings) -> Tuple[int, int, int, int]:
    score = 100
    critical = 0
    warn = 0
    for t in dirty:
        dead = int(t.get("dead", 0))
        r = float(t.get("ratio", 0))
        if dead < _MIN_DEAD_FOR_CRITICAL:
            continue
        if r >= 0.20:
            critical += 1
            score -= 10
        elif r >= 0.10:
            warn += 1
            score -= 3
    long_tx = int(activity.get("long_tx", 0) or 0)
    if long_tx > 0:
        penalty = min(20, 5 + (long_tx - 1) * 2)
        score -= penalty
    idle_tx = int(activity.get("idle_tx", 0) or 0)
    if idle_tx > 0:
        penalty = min(10, 2 + (idle_tx - 1))
        score -= penalty
    if settings and settings.get("autovacuum") != "on":
        score -= 15
    score = max(0, min(100, score))
    return score, critical, warn, idle_tx


# ═══════════════════════════════════════════════════════════════════════
# 9) Maintenance helpers
# ═══════════════════════════════════════════════════════════════════════

def _build_cleanup_where(db_type: str, col: str, days: int,
                          extra_where: Optional[str]) -> str:
    dt = (db_type or "").upper()
    if dt == "MYSQL":
        base = f"{col} < (NOW() - INTERVAL {int(days)} DAY)"
    elif dt == "SQLITE":
        base = f"{col} < datetime('now', '-{int(days)} days')"
    else:
        base = f"{col} < NOW() - INTERVAL '{int(days)} days'"
    if extra_where:
        return f"({base}) AND ({extra_where})"
    return base


async def preview_maintenance() -> Dict[str, Any]:
    db = _get_db()
    result: Dict[str, Any] = {
        'plan': [], 'total_deletions': 0, 'has_errors': False,
        'vacuum_tables': [], 'db_type': _get_db_type(),
        'protected_tables': [k for k, v in _CLEANUP_POLICY.items()
                              if v.get("protected")],
    }
    if db is None:
        return result
    deletable = [k for k, v in _CLEANUP_POLICY.items() if not v.get("protected")]
    if not _is_postgres():
        result['vacuum_tables'] = await _get_all_table_names()
        return result
    sizes_map: Dict[str, int] = {}
    try:
        rows = await db.fetchall(_SQL_TABLE_TOTAL_SIZE, (deletable,)) or []
        for r in rows:
            if isinstance(r, dict) and r.get("table_name"):
                sizes_map[r["table_name"]] = int(r.get("total_bytes") or 0)
    except Exception as e:
        logger.debug(f"preview_maintenance sizes: {e}")
    total = 0
    has_errors = False
    db_type = _get_db_type()
    for tbl in deletable:
        policy = _CLEANUP_POLICY[tbl]
        col = policy["date_column"]
        days = policy["retention"]
        max_mb = policy["max_mb"]
        extra_where = policy.get("extra_where")
        size_bytes = sizes_map.get(tbl, 0)
        size_kb = size_bytes / 1024
        threshold_kb = max_mb * 1024
        entry = {'name': tbl, 'column': col, 'days': days, 'max_mb': max_mb,
                 'threshold_str': f">{days}d | {max_mb}MB",
                 'size_display': _fmt_bytes(size_bytes),
                 'over_limit': size_kb >= threshold_kb,
                 'count': 0, 'error': None}
        if not entry['over_limit']:
            entry['skip_reason'] = 'within_limit'
            result['plan'].append(entry)
            continue
        try:
            where_sql = _build_cleanup_where(db_type, col, days, extra_where)
            row = await db.fetchone(f"SELECT COUNT(*) AS cnt FROM {tbl} WHERE {where_sql}")
            cnt = int((row or {}).get("cnt") or 0)
            entry['count'] = cnt
            total += cnt
        except Exception as e:
            logger.warning(f"preview_maintenance({tbl}): {e}")
            entry['count'] = -1
            entry['error'] = str(e)[:100]
            has_errors = True
        result['plan'].append(entry)
    result['total_deletions'] = total
    result['has_errors'] = has_errors
    result['vacuum_tables'] = await _get_all_table_names()
    return result


async def run_maintenance() -> Dict[str, Any]:
    db = _get_db()
    start = time.monotonic()
    result: Dict[str, Any] = {
        'duration_sec': 0.0, 'deletions': {}, 'deletion_errors': {},
        'skipped': [], 'protected': [k for k, v in _CLEANUP_POLICY.items()
                                      if v.get("protected")],
        'vacuum': {'success': 0, 'failed': 0, 'details': []},
    }
    if db is None:
        result['duration_sec'] = round(time.monotonic() - start, 2)
        return result
    db_type = _get_db_type()
    deletable = [k for k, v in _CLEANUP_POLICY.items() if not v.get("protected")]
    sizes_map: Dict[str, int] = {}
    if _is_postgres():
        try:
            rows = await db.fetchall(_SQL_TABLE_TOTAL_SIZE, (deletable,)) or []
            for r in rows:
                if isinstance(r, dict) and r.get("table_name"):
                    sizes_map[r["table_name"]] = int(r.get("total_bytes") or 0)
        except Exception as e:
            logger.debug(f"run_maintenance sizes: {e}")
    for tbl in deletable:
        policy = _CLEANUP_POLICY[tbl]
        col = policy["date_column"]
        days = policy["retention"]
        max_mb = policy["max_mb"]
        extra_where = policy.get("extra_where")
        if _is_postgres():
            size_kb = sizes_map.get(tbl, 0) / 1024
            threshold_kb = max_mb * 1024
            if size_kb < threshold_kb:
                result['skipped'].append({
                    'name': tbl, 'reason': 'within_limit',
                    'size_display': _fmt_bytes(sizes_map.get(tbl, 0))})
                continue
        try:
            where_sql = _build_cleanup_where(db_type, col, days, extra_where)
            r = await db.execute(f"DELETE FROM {tbl} WHERE {where_sql}")
            result['deletions'][tbl] = int(r or 0)
        except Exception as e:
            logger.warning(f"run_maintenance delete({tbl}): {e}")
            result['deletions'][tbl] = 0
            result['deletion_errors'][tbl] = str(e)[:100]
    if db_type == "SQLITE":
        try:
            await db.execute("VACUUM")
            try:
                await db.execute("ANALYZE")
            except Exception:
                pass
            result['vacuum']['success'] = 1
            result['vacuum']['details'].append(("__sqlite_full__", True, None))
        except Exception as e:
            result['vacuum']['failed'] = 1
            result['vacuum']['details'].append(("__sqlite_full__", False, str(e)[:80]))
    else:
        tables = await _get_all_table_names()
        for t in tables:
            try:
                if db_type == "MYSQL":
                    await db.execute(f"ANALYZE TABLE `{t}`")
                    await db.execute(f"OPTIMIZE TABLE `{t}`")
                elif hasattr(db, "vacuum") and callable(db.vacuum):
                    await db.vacuum(t)
                else:
                    await db.execute(f'VACUUM ANALYZE "{t}"')
                result['vacuum']['success'] += 1
                result['vacuum']['details'].append((t, True, None))
            except Exception as e:
                err = str(e).lower()
                if "does not exist" in err or "no such" in err:
                    result['vacuum']['details'].append((t, True, "skip"))
                else:
                    result['vacuum']['failed'] += 1
                    result['vacuum']['details'].append((t, False, str(e)[:80]))
            try:
                await asyncio.sleep(0.05)
            except Exception:
                pass
    result['duration_sec'] = round(time.monotonic() - start, 2)
    _invalidate_cache()
    return result


# ═══════════════════════════════════════════════════════════════════════
# 10) Maintenance formatters
# ═══════════════════════════════════════════════════════════════════════

def format_maintenance_preview(preview: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("🧹 <b>معاينة الصيانة الآمنة</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("🔒 <i>المشتركون النشطون محميون تلقائياً</i>")
    lines.append("")
    plan = preview.get('plan', []) if isinstance(preview, dict) else []
    has_errors = False
    over = [p for p in plan if p.get('over_limit')]
    within = [p for p in plan if not p.get('over_limit')]
    if over:
        lines.append("🗑️ <b>جداول ستُحذف منها سجلات قديمة:</b>")
        for item in over:
            name = _esc(item.get('name', '?'))
            threshold = _esc(item.get('threshold_str', '?'))
            cnt = item.get('count', 0)
            size = _esc(item.get('size_display', '?'))
            if cnt == -1:
                icon = "❌"
                val = f"<i>فشل: {_esc(item.get('error', '?'))[:40]}</i>"
                has_errors = True
            elif cnt == 0:
                icon = "✅"
                val = "لا شيء (كلها محمية أو حديثة)"
            else:
                icon = "🗑️"
                val = f"<b>{cnt}</b> صف"
            lines.append(f"  {icon} <code>{name}</code>")
            lines.append(f"      {size} | {threshold} → {val}")
        lines.append("")
    if within:
        lines.append(f"✅ <b>جداول ضمن الحد ({len(within)}):</b>")
        for item in within:
            name = _esc(item.get('name', '?'))
            size = _esc(item.get('size_display', '?'))
            max_mb = item.get('max_mb', '?')
            lines.append(f"  🟢 <code>{name}</code> {size} / {max_mb}MB")
        lines.append("")
    protected = preview.get('protected_tables', []) if isinstance(preview, dict) else []
    if protected:
        lines.append(f"🔒 <b>جداول محمية ({len(protected)}):</b>")
        lines.append("  <i>users, subscriptions, user_penalties, "
                     "user_warnings, referral_rewards, ...</i>")
        lines.append("")
    total = (preview.get('total_deletions', 0) if isinstance(preview, dict) else 0)
    if has_errors or preview.get('has_errors'):
        lines.append(f"📊 <b>الإجمالي:</b> {total} صف سيُحذف <i>(بعض العدّ فشل)</i>")
    else:
        lines.append(f"📊 <b>الإجمالي:</b> {total} صف سيُحذف")
    lines.append("")
    tables = (preview.get('vacuum_tables', []) if isinstance(preview, dict) else [])
    if tables:
        lines.append(f"🧹 <b>VACUUM على ({len(tables)} جدول/MV)</b>")
        lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("لتنفيذ الصيانة:")
    lines.append("<code>/db_maintenance confirm</code>")
    if has_errors:
        lines.append("")
        lines.append("⚠️ <i>بعض استعلامات العدّ فشلت.</i>")
    return "\n".join(lines)


def format_maintenance_result(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("✅ <b>اكتملت الصيانة بنجاح</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    duration = (result.get('duration_sec', 0.0) if isinstance(result, dict) else 0.0)
    lines.append(f"⏱️ <b>المدة:</b> {duration:.2f}s")
    lines.append("")
    deletions = (result.get('deletions', {}) if isinstance(result, dict) else {})
    deletion_errors = (result.get('deletion_errors', {}) if isinstance(result, dict) else {})
    skipped = (result.get('skipped', []) if isinstance(result, dict) else [])
    if deletions:
        lines.append("🗑️ <b>الحذف:</b>")
        for name, cnt in deletions.items():
            if name in deletion_errors:
                icon = "❌"
                val = "<i>فشل</i>"
            elif cnt == 0:
                icon = "✅"
                val = "لا شيء"
            else:
                icon = "🗑️"
                val = f"<b>{cnt}</b>"
            lines.append(f"  {icon} <code>{_esc(name)}</code> {val}")
        lines.append("")
    if skipped:
        lines.append(f"⏭️ <b>تخطّي ({len(skipped)} — ضمن الحد)</b>")
        lines.append("")
    protected = result.get('protected', [])
    if protected:
        lines.append(f"🔒 <b>محمية ({len(protected)}):</b>")
        lines.append(f"  <i>{', '.join(protected[:6])}"
                     + ("..." if len(protected) > 6 else "") + "</i>")
        lines.append("")
    vacuum = (result.get('vacuum', {}) if isinstance(result, dict) else {})
    success = vacuum.get('success', 0) if isinstance(vacuum, dict) else 0
    failed = vacuum.get('failed', 0) if isinstance(vacuum, dict) else 0
    lines.append("🧹 <b>VACUUM:</b>")
    lines.append(f"  ✅ نجح: <b>{success}</b>")
    if failed:
        lines.append(f"  ❌ فشل: <b>{failed}</b>")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 11) Maintenance shortcuts
# ═══════════════════════════════════════════════════════════════════════

async def diagnose_maintenance_preview() -> str:
    preview = await preview_maintenance()
    return format_maintenance_preview(preview)


async def run_db_maintenance() -> str:
    result = await run_maintenance()
    return format_maintenance_result(result)


async def vacuum_analyze_tables() -> str:
    db = _get_db()
    if db is None:
        return "❌ DB غير مستورد"
    start = time.monotonic()
    db_type = _get_db_type()
    if db_type == "SQLITE":
        lines = ["🧹 <b>VACUUM (SQLite)</b>", "━━━━━━━━━━━━━━━━━━━━━━", ""]
        try:
            await db.execute("VACUUM")
            try:
                await db.execute("ANALYZE")
            except Exception as _e:
                logger.debug(f"SQLite ANALYZE: {_e}")
            lines.append("  ✅ VACUUM + ANALYZE كامل")
            success = 1
            fail = 0
        except Exception as e:
            lines.append(f"  ❌ فشل: <code>{_esc(str(e)[:80])}</code>")
            success = 0
            fail = 1
        elapsed = time.monotonic() - start
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"⏱️ المدة: {elapsed:.2f}s | ✅ نجح: {success} | ❌ فشل: {fail}")
        _invalidate_cache()
        return "\n".join(lines)
    tables = await _get_all_table_names()
    lines = ["🧹 <b>VACUUM ANALYZE</b>", "━━━━━━━━━━━━━━━━━━━━━━", ""]
    success = 0
    fail = 0
    for t in tables:
        try:
            if db_type == "MYSQL":
                await db.execute(f"ANALYZE TABLE `{t}`")
                await db.execute(f"OPTIMIZE TABLE `{t}`")
            elif hasattr(db, "vacuum") and callable(db.vacuum):
                await db.vacuum(t)
            else:
                await db.execute(f'VACUUM ANALYZE "{t}"')
            success += 1
            lines.append(f"  ✅ {_esc(t)}")
        except Exception as e:
            err = str(e).lower()
            if "does not exist" in err or "no such" in err:
                lines.append(f"  ⏭️ {_esc(t)}")
            else:
                fail += 1
                lines.append(f"  ❌ {_esc(t)} — <code>{_esc(str(e)[:60])}</code>")
        await asyncio.sleep(0.05)
    elapsed = time.monotonic() - start
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"⏱️ المدة: {elapsed:.2f}s | ✅ نجح: {success} | ❌ فشل: {fail}")
    _invalidate_cache()
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 11b) Auto-vacuum
# ═══════════════════════════════════════════════════════════════════════

async def auto_vacuum_dirty_mvs(min_dead: int = 10) -> Dict[str, Any]:
    db = _get_db()
    result: Dict[str, Any] = {
        'vacuumed': [], 'failed': [],
        'skipped': [], 'remaining': [],
        'total_dead_before': 0, 'total_dead_after': 0,
        'cleaned': 0, 'duration_sec': 0.0,
        'error': None,
    }
    if db is None or not _is_postgres():
        return result

    start = time.monotonic()
    _invalidate_cache("all_tables_health")
    dirty, _ = await _get_all_tables_health()

    if dirty is None:
        result['error'] = "فشل فحص dead tuples"
        result['duration_sec'] = round(time.monotonic() - start, 2)
        return result

    result['total_dead_before'] = sum(int(t.get('dead', 0)) for t in dirty)

    targets = [t for t in dirty
               if int(t.get('dead', 0)) >= int(min_dead)]
    below = [t for t in dirty
             if 0 < int(t.get('dead', 0)) < int(min_dead)]

    result['skipped'] = [
        {
            'name': t['name'],
            'dead': int(t.get('dead', 0)),
            'is_mv': bool(t.get('is_matview', False)),
            'reason': f'dead<{int(min_dead)}',
        }
        for t in below
    ]

    if not targets:
        _invalidate_cache("all_tables_health")
        dirty_after, _ = await _get_all_tables_health()
        if dirty_after is not None:
            result['total_dead_after'] = sum(
                int(t.get('dead', 0)) for t in dirty_after)
            result['remaining'] = [
                {
                    'name': t['name'],
                    'dead': int(t.get('dead', 0)),
                    'ratio_pct': round(float(t.get('ratio', 0)) * 100, 2),
                    'is_mv': bool(t.get('is_matview', False)),
                }
                for t in dirty_after
            ]
        result['duration_sec'] = round(time.monotonic() - start, 2)
        return result

    for t in targets:
        name = t.get('name')
        dead_before = int(t.get('dead', 0))
        is_mv = bool(t.get('is_matview', False))
        try:
            if hasattr(db, "vacuum") and callable(db.vacuum):
                await db.vacuum(name)
            else:
                await db.execute(f'VACUUM ANALYZE "{name}"')

            dead_after = 0
            try:
                row = await db.fetchone(
                    "SELECT COALESCE(n_dead_tup,0) AS d "
                    "FROM pg_stat_user_tables "
                    "WHERE relname = $1 "
                    "  AND schemaname = current_schema()",
                    name,
                )
                if isinstance(row, dict):
                    dead_after = int(row.get('d') or 0)
            except Exception as e:
                logger.debug(f"auto_vacuum read dead_after({name}): {e}")

            result['vacuumed'].append({
                'name': name,
                'dead_before': dead_before,
                'dead_after': dead_after,
                'is_mv': is_mv,
            })
            result['cleaned'] += 1
        except Exception as e:
            err = str(e)[:120]
            logger.warning(f"auto_vacuum({name}): {err}")
            result['failed'].append({'name': name, 'error': err})
        try:
            await asyncio.sleep(0.05)
        except Exception:
            pass

    _invalidate_cache("all_tables_health")
    dirty_after, _ = await _get_all_tables_health()
    if dirty_after is not None:
        result['total_dead_after'] = sum(
            int(t.get('dead', 0)) for t in dirty_after)
        result['remaining'] = [
            {
                'name': t['name'],
                'dead': int(t.get('dead', 0)),
                'ratio_pct': round(float(t.get('ratio', 0)) * 100, 2),
                'is_mv': bool(t.get('is_matview', False)),
            }
            for t in dirty_after
        ]

    result['duration_sec'] = round(time.monotonic() - start, 2)
    logger.info(
        "🧹 auto_vacuum_dirty_mvs: cleaned=%d | dead %d → %d | %.2fs",
        result['cleaned'], result['total_dead_before'],
        result['total_dead_after'], result['duration_sec'])
    return result


# ═══════════════════════════════════════════════════════════════════════
# 11c) AUTO-TUNING
# 🆕 v7.3.1: managed_* جداول → scale=0.0 + threshold=10 (عدواني)
# ═══════════════════════════════════════════════════════════════════════

_AUTOVACUUM_TUNING_RULES: Dict[str, Optional[Dict[str, float]]] = {
    # 🆕 v7.3.1 FIX-AV-1: جداول managed_* عالية churn → عدوانية قصوى
    # السبب: كل رسالة مستخدم = UPDATE، فـ AV السابق لم يلحق.
    # القاعدة: scale=0.0 + threshold=10 → AV يعمل عند 10 dead tuples فقط.
    "managed_bot_users": {
        "vacuum_scale_factor": 0.0,
        "vacuum_threshold": 10,
        "analyze_scale_factor": 0.0,
        "analyze_threshold": 10,
    },
    "managed_bot_keywords": {
        "vacuum_scale_factor": 0.0,
        "vacuum_threshold": 10,
        "analyze_scale_factor": 0.0,
        "analyze_threshold": 10,
    },
    "managed_bot_keyword_replied": {
        "vacuum_scale_factor": 0.0,
        "vacuum_threshold": 10,
        "analyze_scale_factor": 0.0,
        "analyze_threshold": 10,
    },
    "managed_bots": {
        "vacuum_scale_factor": 0.0,
        "vacuum_threshold": 10,
        "analyze_scale_factor": 0.0,
        "analyze_threshold": 10,
    },
    # جداول نظامية شبه ثابتة → اتركها افتراضية
    "schema_version": None,
    "_dual_sync_state": None,
    "mv_active_user_limits": None,
}

_AUTOVACUUM_AUTO_DISCOVER = True
_AUTOVACUUM_AUTO_RATIO = 0.10
_AUTOVACUUM_AUTO_MOD = 1000
_AUTOVACUUM_AUTO_MIN_DEAD = 20

_AUTOVACUUM_TUNE_CACHE_KEY = "autovacuum_tuning"


async def _read_reloptions(table: str) -> Dict[str, str]:
    db = _get_db()
    if db is None or not _is_postgres():
        return {}
    try:
        row = await db.fetchone("""
            SELECT COALESCE(reloptions, ARRAY[]::text[]) AS opts
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = $1 AND n.nspname = current_schema()
            LIMIT 1
        """, table)
        if not isinstance(row, dict):
            return {}
        out: Dict[str, str] = {}
        for o in (row.get("opts") or []):
            if isinstance(o, str) and "=" in o:
                k, v = o.split("=", 1)
                out[k.strip()] = v.strip()
        return out
    except Exception:
        return {}


def _build_alter_sql(table: str, rules: Dict[str, float]) -> Optional[str]:
    if not rules:
        return None
    params = []
    if "vacuum_scale_factor" in rules:
        params.append(f"autovacuum_vacuum_scale_factor = {rules['vacuum_scale_factor']}")
    if "vacuum_threshold" in rules:
        params.append(f"autovacuum_vacuum_threshold = {int(rules['vacuum_threshold'])}")
    if "analyze_scale_factor" in rules:
        params.append(f"autovacuum_analyze_scale_factor = {rules['analyze_scale_factor']}")
    if "analyze_threshold" in rules:
        params.append(f"autovacuum_analyze_threshold = {int(rules['analyze_threshold'])}")
    if not params:
        return None
    safe = str(table).replace('"', '""')
    return f'ALTER TABLE "{safe}" SET ({", ".join(params)})'


async def ensure_autovacuum_tuning(*, force: bool = False) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        'ok': False, 'tuned': [], 'skipped': [], 'failed': [],
        'duration_sec': 0.0,
    }
    db = _get_db()
    if db is None or not _is_postgres():
        result['ok'] = True
        result['skipped'].append({'name': '*', 'reason': 'not_postgres'})
        return result

    if not force:
        cached = _cache_get(_AUTOVACUUM_TUNE_CACHE_KEY)
        if cached is not None:
            return cached

    start = time.monotonic()
    targets: Dict[str, Dict[str, float]] = {}

    for name, rules in _AUTOVACUUM_TUNING_RULES.items():
        if rules is None:
            result['skipped'].append({'name': name, 'reason': 'system_default'})
            continue
        targets[name] = rules

    if _AUTOVACUUM_AUTO_DISCOVER:
        try:
            dirty, _ = await _get_all_tables_health()
            for t in (dirty or []):
                name = t['name']
                if name in targets or name in _AUTOVACUUM_TUNING_RULES:
                    continue
                if t.get('is_matview'):
                    continue
                if name in _DB_OWNED_TABLES:
                    result['skipped'].append({
                        'name': name,
                        'reason': 'managed_by_database_py',
                    })
                    continue
                dead = int(t.get('dead', 0))
                ratio = float(t.get('ratio', 0))
                mod = int(t.get('n_mod', 0))
                if dead < _AUTOVACUUM_AUTO_MIN_DEAD:
                    continue
                if ratio < _AUTOVACUUM_AUTO_RATIO and mod < _AUTOVACUUM_AUTO_MOD:
                    continue
                targets[name] = {
                    'vacuum_scale_factor': 0.05,
                    'vacuum_threshold': 50,
                    'analyze_scale_factor': 0.02,
                    'analyze_threshold': 50,
                }
        except Exception as e:
            logger.debug(f"ensure_autovacuum_tuning discovery: {e}")

    keymap = {
        'vacuum_scale_factor':   'autovacuum_vacuum_scale_factor',
        'vacuum_threshold':      'autovacuum_vacuum_threshold',
        'analyze_scale_factor':  'autovacuum_analyze_scale_factor',
        'analyze_threshold':     'autovacuum_analyze_threshold',
    }
    for name, rules in targets.items():
        try:
            current = await _read_reloptions(name)

            already_ok = True
            for k, want in rules.items():
                cur = current.get(keymap.get(k, ""))
                if cur is None or abs(float(cur) - float(want)) > 1e-9:
                    already_ok = False
                    break

            if already_ok:
                result['skipped'].append({
                    'name': name, 'reason': 'already_tuned',
                })
                continue

            sql = _build_alter_sql(name, rules)
            if sql is None:
                result['skipped'].append({'name': name, 'reason': 'no_rules'})
                continue

            await db.execute(sql)
            result['tuned'].append({
                'name': name,
                'before': current,
                'after': rules,
            })
            logger.info(f"🔧 autovacuum tuned: {name} → {rules}")
        except Exception as e:
            err = str(e)[:120]
            logger.warning(f"ensure_autovacuum_tuning({name}): {err}")
            result['failed'].append({'name': name, 'error': err})

    result['duration_sec'] = round(time.monotonic() - start, 2)
    result['ok'] = len(result['failed']) == 0
    _cache_set(_AUTOVACUUM_TUNE_CACHE_KEY, result, ttl=600.0)
    return result


async def init_autovacuum_tuning() -> Dict[str, Any]:
    try:
        result = await ensure_autovacuum_tuning()
        tuned = len(result.get('tuned', []))
        skipped = len(result.get('skipped', []))
        failed = len(result.get('failed', []))
        if tuned or failed:
            logger.info(
                "🔧 autovacuum auto-tuning: tuned=%d skipped=%d failed=%d (%.2fs)",
                tuned, skipped, failed, result.get('duration_sec', 0.0),
            )
        return result
    except Exception as e:
        logger.warning(f"init_autovacuum_tuning: {e}")
        return {'ok': False, 'error': str(e)}


def format_autovacuum_tuning(result: Dict[str, Any]) -> str:
    lines = ["⚙️ <b>ضبط autovacuum تلقائيًا</b>", "━━━━━━━━━━━━━━━━━━━━━━", ""]
    tuned = result.get('tuned', [])
    skipped = result.get('skipped', [])
    failed = result.get('failed', [])

    if not tuned and not failed:
        lines.append(f"✅ <b>كل الجداول مضبوطة مسبقاً ({len(skipped)})</b>")
        lines.append("")
        lines.append("💡 لا حاجة لأي تغيير — autovacuum يعمل بكفاءة.")
        lines.append("")
        if skipped:
            by_reason: Dict[str, int] = {}
            for s in skipped:
                r = s.get('reason', '?')
                by_reason[r] = by_reason.get(r, 0) + 1
            lines.append("<b>تفصيل التخطي:</b>")
            for reason, count in sorted(by_reason.items()):
                lines.append(f"  • <code>{_esc(reason)}</code>: {count}")
            lines.append("")
        lines.append(f"⏱️ <i>{result.get('duration_sec', 0):.2f}s</i>")
        return "\n".join(lines)

    if tuned:
        lines.append(f"✅ <b>ضُبطت ({len(tuned)}):</b>")
        for t in tuned:
            lines.append(f"  🔧 <code>{_esc(t['name'])}</code>")
        lines.append("")
    if skipped:
        lines.append(f"⏭️ <b>تخطّي ({len(skipped)}):</b>")
        for t in skipped[:10]:
            lines.append(f"  • <code>{_esc(t['name'])}</code> — "
                         f"{_esc(t.get('reason', '?'))}")
        if len(skipped) > 10:
            lines.append(f"  … و{len(skipped) - 10} آخر")
        lines.append("")
    if failed:
        lines.append(f"❌ <b>فشل ({len(failed)}):</b>")
        for t in failed[:10]:
            lines.append(f"  • <code>{_esc(t['name'])}</code> — "
                         f"{_esc(t.get('error', '?'))}")
        lines.append("")
    lines.append(f"⏱️ <i>{result.get('duration_sec', 0):.2f}s</i>")
    return "\n".join(lines)


async def diagnose_autovacuum_tuning(*, force: bool = False) -> str:
    result = await ensure_autovacuum_tuning(force=force)
    return format_autovacuum_tuning(result)


# ═══════════════════════════════════════════════════════════════════════
# تقرير الأخطاء الشامل (Findings Report)
# ═══════════════════════════════════════════════════════════════════════

def format_findings_report() -> str:
    lines: List[str] = []
    lines.append("🔍 <b>تقرير كشف الأخطاء الشامل</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    if not _ERRORS and not _WARNINGS:
        lines.append("")
        lines.append("🎉 <b>لا توجد أخطاء أو تحذيرات!</b>")
        lines.append("")
        lines.append("✅ قاعدة البيانات بصحة ممتازة")
        return "\n".join(lines)

    if _ERRORS:
        lines.append("")
        lines.append(f"🔴 <b>أخطاء حرجة ({len(_ERRORS)}):</b>")
        lines.append("")
        for i, (_, msg) in enumerate(_ERRORS, 1):
            lines.append(f"  {i}. {_esc(msg)}")

    if _WARNINGS:
        lines.append("")
        lines.append(f"🟡 <b>تحذيرات ({len(_WARNINGS)}):</b>")
        lines.append("")
        for i, (_, msg) in enumerate(_WARNINGS, 1):
            lines.append(f"  {i}. {_esc(msg)}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        f"📊 <b>الخلاصة:</b> {len(_ERRORS)} خطأ، {len(_WARNINGS)} تحذير")
    if _ERRORS:
        lines.append("")
        lines.append("🔴 <b>يُنصح بمعالجة الأخطاء الحرجة فوراً!</b>")
    elif _WARNINGS:
        lines.append("")
        lines.append("🟡 <b>يُنصح بمراجعة التحذيرات لاحقاً</b>")

    return "\n".join(lines)


async def _run_all_findings_checks() -> None:
    _clear_findings()
    db = _get_db()
    if db is None:
        _err("DB غير مستورد — لا يمكن الفحص")
        return

    try:
        await _inspect_schema_integrity(db)
    except Exception as e:
        _warn(f"فحص البنية فشل: {str(e)[:80]}")

    try:
        await _inspect_users_anomalies(db)
    except Exception as e:
        _warn(f"فحص المستخدمين فشل: {str(e)[:80]}")

    try:
        await _inspect_plans_anomalies(db)
    except Exception as e:
        _warn(f"فحص الباقات فشل: {str(e)[:80]}")

    try:
        await _inspect_subscriptions_anomalies(db)
    except Exception as e:
        _warn(f"فحص الاشتراكات فشل: {str(e)[:80]}")

    try:
        await _inspect_channels_anomalies(db)
    except Exception as e:
        _warn(f"فحص القنوات فشل: {str(e)[:80]}")

    try:
        await _inspect_managed_bots_anomalies(db)
    except Exception as e:
        _warn(f"فحص البوتات المُدارة فشل: {str(e)[:80]}")

    try:
        await _inspect_invoices_anomalies(db)
    except Exception as e:
        _warn(f"فحص الفواتير فشل: {str(e)[:80]}")

    try:
        await _inspect_settings_anomalies(db)
    except Exception as e:
        _warn(f"فحص الإعدادات فشل: {str(e)[:80]}")


async def diagnose_findings_only() -> str:
    await _run_all_findings_checks()
    return format_findings_report()


async def diagnose_with_errors(*, include_probes: bool = True) -> str:
    await _run_all_findings_checks()
    findings_text = format_findings_report()

    try:
        parts = await _build_sections(include_probes=include_probes)
    except Exception as e:
        logger.warning(f"diagnose_with_errors: _build_sections فشل: {e}")
        parts = [f"⚠️ فشل تشخيص الأداء: {_esc(str(e)[:100])}"]

    all_parts = [findings_text] + parts
    return "\n\n".join(all_parts)


async def get_findings() -> Dict[str, List[Tuple[str, str]]]:
    return _get_findings()


async def run_findings_checks() -> Dict[str, List[Tuple[str, str]]]:
    await _run_all_findings_checks()
    return _get_findings()


# ═══════════════════════════════════════════════════════════════════════
# 12) Build Sections
# ═══════════════════════════════════════════════════════════════════════

async def _build_sections(*, include_probes: bool = True) -> List[str]:
    parts: List[str] = []
    critical_idx_tables = ["posts", "banned_words", "bot_groups",
                           "users", "user_channels", "subscriptions"]
    gathered = await asyncio.gather(
        _get_db_metadata(), _get_all_tables_health(),
        _get_activity_stats(force=True), _get_pg_settings(),
        _get_table_sizes(limit=15), _get_cleanup_status(),
        _get_all_table_names(), _get_indexes(critical_idx_tables),
        return_exceptions=True)
    meta = gathered[0] if not isinstance(gathered[0], BaseException) else {}
    health_result = (gathered[1] if not isinstance(gathered[1], BaseException)
                     else (None, None))
    activity = gathered[2] if not isinstance(gathered[2], BaseException) else {}
    settings = gathered[3] if not isinstance(gathered[3], BaseException) else {}
    sizes = gathered[4] if not isinstance(gathered[4], BaseException) else []
    cleanup_status = (gathered[5] if not isinstance(gathered[5], BaseException) else [])
    idx_map = gathered[7] if not isinstance(gathered[7], BaseException) else {}
    if isinstance(health_result, tuple) and len(health_result) == 2:
        dirty, clean = health_result
    else:
        dirty, clean = None, None
    health_failed = (dirty is None or clean is None)
    if health_failed:
        dirty, clean = [], []
    if not isinstance(meta, dict):
        meta = {"size_display": "?", "current_schema": "?",
                "schemas": [], "database_name": "?"}
    if not isinstance(activity, dict): activity = {}
    if not isinstance(settings, dict): settings = {}
    if not isinstance(sizes, list): sizes = []
    if not isinstance(cleanup_status, list): cleanup_status = []
    if not isinstance(idx_map, dict): idx_map = {}
    score, critical_count, warn_count, idle_tx_count = _calc_technical_score(
        dirty, activity, settings)
    total_dead = sum(t.get("dead", 0) for t in dirty)
    total_tables = len(dirty) + len(clean)
    s0: List[str] = []
    active_line = format_active_db_line()
    if active_line:
        s0.append(active_line)
        s0.append("")
    if health_failed and _is_postgres():
        s0.append("🟠 <b>تنبيه:</b> فحص dead tuples فشل مؤقتاً — "
                  "القياسات المتعلقة بالجداول قد تكون غير دقيقة.")
        s0.append("")
    configured_dbs = _get_all_configured_databases()
    if len(configured_dbs) > 1:
        s0.append(f"⚠️ <b>تحذير:</b> يوجد <b>{len(configured_dbs)}</b> "
                  f"قواعد بيانات مُعدّة — راجع /db_diag للتفاصيل.")
        s0.append("")
    if s0:
        parts.append("\n".join(s0))
    s1: List[str] = []
    s1.append(f"🔬 <b>تشخيص قاعدة البيانات v{VERSION}</b>")
    s1.append("━━━━━━━━━━━━━━━━━━━━━━")
    db_type_label = "PostgreSQL" if _is_postgres() else _get_db_type()
    s1.append(f"🗄️ <b>النوع:</b> {_esc(db_type_label)}")
    s1.append(f"💾 <b>الحجم:</b> {meta.get('size_display', '?')}")
    s1.append(f"📋 <b>Schema:</b> {_esc(meta.get('current_schema', '?'))}")
    schemas = meta.get("schemas", [])
    if schemas:
        s1.append(f"📋 <b>Schemas:</b> {_esc(', '.join(schemas))}")
    s1.append(f"🗃️ <b>Database:</b> {_esc(meta.get('database_name', '?'))}")
    s1.append("")
    score_icon = "🟢" if score >= 80 else ("🟡" if score >= 60 else "🔴")
    s1.append("📌 <b>الخلاصة التقنية</b>")
    s1.append(f"  🔴 جداول حرجة: <b>{critical_count}</b>")
    s1.append(f"  🟡 جداول تحتاج انتباه: <b>{warn_count}</b>")
    s1.append(f"  ⚠️ Long transactions: <b>{activity.get('long_tx', 0)}</b>")
    s1.append(f"  🟠 Idle transactions: <b>{idle_tx_count}</b>")
    s1.append(f"  💀 إجمالي dead tuples: <b>{_fmt_num(total_dead)}</b>")
    s1.append(f"  📊 جداول مهمة: <b>{len(dirty)}</b>")
    s1.append(f"  🗂️ إجمالي الجداول: <b>{total_tables}</b>")
    av_setting = settings.get("autovacuum", "")
    if av_setting:
        av_icon = "🟢" if av_setting == "on" else "🔴"
        s1.append(f"  autovacuum: {av_icon} <b>{_esc(av_setting).upper()}</b>")
    s1.append(f"  مؤشر الحالة: <b>{score}/100</b> {score_icon}")
    parts.append("\n".join(s1))
    s2: List[str] = []
    s2.append("╔══════════════════════════════════╗")
    s2.append("║  🎯 التحليل المنطقي          ║")
    s2.append("╚══════════════════════════════════╝")
    s2.append("")
    if av_setting:
        if av_setting == "on":
            s2.append("🟢 autovacuum = ON.")
        else:
            s2.append("🔴 autovacuum = OFF — خطر.")
    else:
        s2.append("ℹ️ autovacuum: N/A.")
    if settings.get("synchronous_commit") == "off":
        s2.append("")
        s2.append("ℹ️ synchronous_commit=off — مقصود. ليس خطأً.")
    if health_failed and _is_postgres():
        s2.append("")
        s2.append("🟠 <b>فحص dead-tuples فشل مؤقتاً</b> — أعد المحاولة.")
    elif critical_count > 0:
        s2.append("")
        s2.append(f"🔴 <b>{critical_count} جدول حرج</b> — راجع التفاصيل.")
    else:
        s2.append("")
        s2.append(f"✅ لا توجد جداول حرجة (الحد {_MIN_DEAD_FOR_CRITICAL}).")
    s2.append("")
    s2.append("🔒 <b>سياسة التنظيف:</b> آمنة — المشتركون محميون.")
    parts.append("\n".join(s2))
    if dirty:
        s3: List[str] = []
        s3.append("━━━━━━━━━━━━━━━━━━━━━━")
        s3.append("📊 <b>التفاصيل الكاملة</b>")
        s3.append("━━━━━━━━━━━━━━━━━━━━━━")
        s3.append("")
        s3.append("1. <b>Dead Tuples + التنظيف</b>")
        s3.append("")
        for t in dirty[:20]:
            color = _dead_color(t["dead"], t["live"])
            name = _esc(t["name"])
            mv_tag = " <code>[MV]</code>" if t.get("is_matview") else ""
            ratio_pct = t["ratio"] * 100
            s3.append(f"{color} <b>{name}</b>{mv_tag}")
            s3.append(f"     live={_fmt_num(t['live'])} "
                      f"dead={_fmt_num(t['dead'])} ({ratio_pct:.1f}%)")
            av = _fmt_ts(t["last_av"])
            an = _fmt_ts(t["last_an"])
            mod = t["n_mod"]
            s3.append(f"     🧹 AV: {av} | 📊 AN: {an} | 🔄 mod={mod}")
            s3.append("")
        parts.append("\n".join(s3))
    if clean:
        s3b: List[str] = []
        s3b.append("1b. <b>جداول نظيفة (dead=0)</b>")
        s3b.append("")
        clean_sorted = sorted(clean, key=lambda x: -x["live"])
        for t in clean_sorted[:15]:
            an = _fmt_ts(t["last_an"])
            mv_tag = " <code>[MV]</code>" if t.get("is_matview") else ""
            s3b.append(f"✅ <b>{_esc(t['name'])}</b>{mv_tag}")
            s3b.append(f"     live={_fmt_num(t['live'])} | 📊 AN: {an}")
        if len(clean_sorted) > 15:
            s3b.append(f"… و{len(clean_sorted) - 15} جدول نظيف آخر")
        parts.append("\n".join(s3b))
    tuned = [t for t in dirty + clean if t.get("auto_tuned")]
    not_tuned = [t for t in dirty + clean if not t.get("auto_tuned")]
    s4: List[str] = []
    s4.append("2. <b>Autovacuum للجداول الحرجة</b>")
    s4.append("")
    for tname in ("posts", "subscriptions", "user_penalties", "users"):
        match = next((t for t in tuned if t["name"] == tname), None)
        if match:
            av = match.get("av_scale", "?")
            an = match.get("an_scale", "?")
            s4.append(f"✅ <b>{_esc(tname)}</b> — مضبوط ({av}/{an})")
        else:
            match2 = next((t for t in not_tuned if t["name"] == tname), None)
            if match2:
                s4.append(f"⚙️ <b>{_esc(tname)}</b> — غير مضبوط")
    parts.append("\n".join(s4))
    if not_tuned:
        s4b: List[str] = []
        s4b.append("")
        s4b.append(f"2b. <b>غير مضبوطة ({len(not_tuned)} من {len(tuned) + len(not_tuned)})</b>")
        s4b.append("")
        for t in not_tuned[:15]:
            mv_tag = " <code>[MV]</code>" if t.get("is_matview") else ""
            s4b.append(f"⚙️ <b>{_esc(t['name'])}</b>{mv_tag} — "
                       f"live={_fmt_num(t['live'])} dead={_fmt_num(t['dead'])}")
        if len(not_tuned) > 15:
            s4b.append(f"… و{len(not_tuned) - 15} آخر")
        parts.append("\n".join(s4b))
    s5: List[str] = []
    s5.append("3. <b>نشاط PostgreSQL / Blockers</b>")
    s5.append("")
    if (activity.get("long_tx", 0) == 0 and activity.get("idle_tx", 0) == 0
            and activity.get("vacuum_running", 0) == 0):
        s5.append("✅ لا توجد معاملات طويلة / idle-in-tx / VACUUM.")
    else:
        if activity.get("long_tx", 0):
            s5.append(f"⚠️ Long transactions: <b>{activity['long_tx']}</b>")
        if activity.get("idle_tx", 0):
            s5.append(f"🟠 Idle transactions: <b>{activity['idle_tx']}</b>")
        if activity.get("vacuum_running", 0):
            s5.append(f"🧹 VACUUM جارٍ: <b>{activity['vacuum_running']}</b>")
    s5.append(f"📊 إجمالي الاتصالات: <b>{activity.get('total_connections', 0)}</b>")
    parts.append("\n".join(s5))
    if sizes:
        s6: List[str] = []
        s6.append("4. <b>أحجام الجداول — Top 15</b>")
        s6.append("")
        for t in sizes[:15]:
            name = t.get("name", "?")
            display = t.get("total_display", "0 B")
            s6.append(f"  <code>{_esc(name)}</code> {display}")
        parts.append("\n".join(s6))
    if idx_map:
        s7: List[str] = []
        s7.append("5. <b>الفهارس الحرجة</b>")
        s7.append("")
        for tname in critical_idx_tables:
            if tname in idx_map:
                cnt = len(idx_map[tname])
                s7.append(f"✅ <b>{_esc(tname)}</b> ({cnt})")
        parts.append("\n".join(s7))
    if settings:
        s8: List[str] = []
        s8.append("6. <b>إعدادات PostgreSQL</b>")
        s8.append("")
        for k in _CRITICAL_SETTINGS:
            if k in settings:
                s8.append(f"  <code>{_esc(k)}</code> = {_esc(settings[k])}")
        parts.append("\n".join(s8))
    if cleanup_status:
        s9: List[str] = []
        s9.append("8. <b>Auto-Cleanup (سياسة آمنة)</b>")
        s9.append("")
        s9.append("🔒 <i>المشتركون محميون تلقائياً</i>")
        s9.append("")
        for c in cleanup_status:
            retention = c.get("retention_days", "?")
            s9.append(f"  {c['color']} <b>{_esc(c['name'])}</b> — "
                      f"{c['display']} (حد {c['max_mb']}MB, احتفاظ {retention}d)")
        s9.append("")
        protected_list = [k for k, v in _CLEANUP_POLICY.items() if v.get("protected")]
        s9.append(f"🔒 <b>محمية ({len(protected_list)}):</b>")
        s9.append("  <i>users, subscriptions, user_penalties, ...</i>")
        s9.append("")
        s9.append("⚙️ كل 6h | VACUUM: ON 🟢")
        parts.append("\n".join(s9))
    parts.append("━━━━━━━━━━━━━━━━━━━━━━\n"
                 "✅ <b>اكتمل التشخيص</b>\n"
                 f"🕐 <i>{_now_iso()}</i>")
    try:
        preview = await preview_maintenance()
        s11_text = format_maintenance_preview(preview)
        parts.append(s11_text)
    except Exception as e:
        logger.warning(f"maintenance preview in sections: {e}")
    if include_probes:
        probes = await asyncio.gather(_probe_full_health(), return_exceptions=True)
        full_health = (probes[0] if not isinstance(probes[0], BaseException) else {})
        latency_probe = ((full_health.get("database") or {})
                         if isinstance(full_health, dict) else {})
        try:
            verdict = (latency_probe.get("verdict", "unknown")
                       if isinstance(latency_probe, dict) else "unknown")
            if verdict in ("slow", "critical", "acceptable"):
                latency_text = format_latency_report(latency_probe)
                parts.append(latency_text)
        except Exception as e:
            logger.debug(f"latency probe in sections: {e}")
        try:
            b = (full_health.get("bottleneck") or {}
                 if isinstance(full_health, dict) else {})
            if b.get("primary") not in ("none", None):
                health_text = format_full_health_report(full_health)
                parts.append(health_text)
        except Exception as e:
            logger.debug(f"full health in sections: {e}")
    return parts


# ═══════════════════════════════════════════════════════════════════════
# 13) Public API
# ═══════════════════════════════════════════════════════════════════════

async def diagnose_db(*, include_probes: bool = True) -> str:
    parts = await _build_sections(include_probes=include_probes)
    return "\n\n".join(parts)


async def diagnose_db_split(*, include_probes: bool = True) -> List[str]:
    return await _build_sections(include_probes=include_probes)


async def diagnose_db_quick() -> str:
    db = _get_db()
    if db is None:
        return "❌ DB غير مستورد"
    lines: List[str] = []
    active = _detect_active_db_source(db)
    if active.get("provider") == "sqlite_local":
        lines.append("🗄️ <b>DB النشطة:</b> SQLite (محلي)")
    elif active.get("active_url"):
        comp = active.get("components", {})
        lines.append(f"🗄️ <b>DB النشطة:</b> "
                     f"<code>{_esc(active.get('provider', '?'))}</code> @ "
                     f"<code>{_esc(comp.get('host', '?'))}:{comp.get('port', 0)}"
                     f"/{_esc(comp.get('database', '?'))}</code>")
    try:
        meta = await _get_db_metadata()
        db_type = "PostgreSQL" if _is_postgres() else _get_db_type()
        lines.append(f"🔬 <b>DB:</b> {db_type} | 💾 {meta.get('size_display', '?')}")
    except Exception:
        lines.append(f"🔬 <b>DB:</b> {_get_db_type()}")
    total_dead = 0
    critical = 0
    try:
        dirty, clean = await _get_all_tables_health()
        if dirty is None:
            lines.append("🟠 فحص dead-tuples فشل مؤقتاً")
        else:
            total_dead = sum(t.get("dead", 0) for t in dirty)
            critical = sum(1 for t in dirty
                           if t.get("ratio", 0) >= 0.20
                           and int(t.get("dead", 0)) >= _MIN_DEAD_FOR_CRITICAL)
            lines.append(f"💀 Dead: <b>{_fmt_num(total_dead)}</b> | "
                         f"🔴 حرجة: <b>{critical}</b>")
    except Exception:
        lines.append("🟠 فحص dead-tuples فشل")
    try:
        activity = await _get_activity_stats(force=True)
        idle = activity.get("idle_tx", 0)
        long_tx = activity.get("long_tx", 0)
        idle_icon = "🟢" if idle == 0 else ("🟡" if idle < 3 else "🔴")
        long_icon = "🟢" if long_tx == 0 else "🔴"
        lines.append(f"{idle_icon} idle-tx: <b>{idle}</b> | "
                     f"{long_icon} long-tx: <b>{long_tx}</b>")
    except Exception:
        lines.append("🟠 idle-tx: ? | long-tx: ?")
    try:
        settings = await _get_pg_settings()
        if settings:
            av = settings.get("autovacuum", "?")
            av_icon = "🟢" if av == "on" else "🔴"
            lines.append(f"{av_icon} autovacuum: <b>{_esc(av).upper()}</b>")
    except Exception:
        pass
    try:
        cached_latency = _cache_get("latency_probe")
        if cached_latency and isinstance(cached_latency, dict):
            verdict = cached_latency.get("verdict", "unknown")
            icon = {"excellent": "🟢", "good": "🟢", "acceptable": "🟡",
                    "slow": "🟠", "critical": "🔴"}.get(verdict, "⚪")
            warm = cached_latency.get("warm_median_ms", 0)
            tcp = cached_latency.get("tcp_connect_ms", 0)
            if tcp and tcp > 0:
                lines.append(f"{icon} كمون: TCP={tcp:.0f}ms، DB={warm:.0f}ms")
            else:
                lines.append(f"{icon} كمون DB: {warm:.0f}ms")
    except Exception:
        pass
    try:
        cached_full = _cache_get("full_health")
        if cached_full and isinstance(cached_full, dict):
            b = cached_full.get("bottleneck") or {}
            if b.get("primary") != "none":
                sev = b.get("severity", "low")
                icon = {"critical": "🔴", "high": "🟠",
                        "medium": "🟡", "low": "🟢"}.get(sev, "⚪")
                lines.append(f"{icon} السبب: <code>{b.get('primary')}</code>")
            cross = b.get("cross_region") or {}
            if cross.get("cross_region") is True:
                lines.append(f"🚨 <b>Cross-Region</b>: "
                             f"bot={_esc(cross.get('bot_region'))} | "
                             f"db={_esc(cross.get('db_region'))}")
            elif (cross.get("cross_region") is False
                  and cross.get("inferred_from_rtt")):
                lines.append(f"✅ <b>نفس المنطقة</b> <i>(مُستنتَج من RTT)</i>")
    except Exception:
        pass
    configured_dbs = _get_all_configured_databases()
    if len(configured_dbs) > 1:
        lines.append(f"⚠️ <b>{len(configured_dbs)} قواعد بيانات مُعدّة</b> — "
                     f"استخدم /db_diag للتفاصيل")
    if _ERRORS or _WARNINGS:
        lines.append("")
        lines.append(
            f"🔴 أخطاء: <b>{len(_ERRORS)}</b> | "
            f"🟡 تحذيرات: <b>{len(_WARNINGS)}</b>")
        lines.append("  <i>استخدم /db_errors للتفاصيل</i>")
    return "\n".join(lines)


async def get_diagnostics_data(top_n: int = 15) -> Dict[str, Any]:
    parts = await _build_sections()
    return {"sections": parts, "available": True,
            "db_type": _get_db_type(), "version": VERSION}


async def get_region_info() -> Dict[str, Any]:
    cached = _cache_get("region_info")
    if cached is not None:
        return cached
    db = _get_db()
    host = "?"
    if db is not None:
        active = _detect_active_db_source(db)
        host = active.get("components", {}).get("host", "?")
        if host == "?":
            url = (getattr(db, "DATABASE_URL", "") or os.getenv("DATABASE_URL", ""))
            try:
                p = urlparse(url)
                host = p.hostname or "?"
            except Exception:
                pass
    bot_info = _detect_bot_cloud()
    db_info = _guess_db_region(host)
    cross = _detect_cross_region(bot_info, db_info, tcp_ms=None)
    result = {"bot": bot_info, "db": db_info,
              "cross_region": cross, "db_host": host}
    _cache_set("region_info", result, ttl=3600.0)
    return result


async def get_all_databases_info() -> Dict[str, Any]:
    active = _detect_active_db_source(_get_db())
    configured = _get_all_configured_databases()
    warnings = _get_multi_db_warnings(configured)
    return {"active": active, "configured": configured,
            "warnings": warnings, "count": len(configured)}


# ═══════════════════════════════════════════════════════════════════════
# 14) Aliases
# ═══════════════════════════════════════════════════════════════════════

maintenance_preview = diagnose_maintenance_preview
preview_maintenance_html = diagnose_maintenance_preview
run_maintenance_html = run_db_maintenance
execute_maintenance = run_db_maintenance
perform_maintenance = run_db_maintenance
do_maintenance = run_db_maintenance

vacuum_all_tables = vacuum_analyze_tables
vacuum_tables = vacuum_analyze_tables
run_vacuum = vacuum_analyze_tables
do_vacuum = vacuum_analyze_tables
vacuum_db = vacuum_analyze_tables

diagnose = diagnose_db
run_diagnostics = diagnose_db
get_diagnostics = diagnose_db
diagnose_postgres = diagnose_db
diag = diagnose_db
diagnose_database = diagnose_db
diagnose_split = diagnose_db_split
get_diagnostics_split = diagnose_db_split
diagnostics_split = diagnose_db_split
split_diagnostics = diagnose_db_split
get_diagnostics_report = diagnose_db
get_quick_health = diagnose_db_quick

get_db_info = _get_db_metadata
get_database_info = _get_db_metadata
get_pg_info = _get_db_metadata

auto_vacuum = auto_vacuum_dirty_mvs
auto_cleanup = auto_vacuum_dirty_mvs
cleanup_dead_tuples = auto_vacuum_dirty_mvs
vacuum_dirty_tables = auto_vacuum_dirty_mvs

autovacuum_tune = ensure_autovacuum_tuning
tune_autovacuum = ensure_autovacuum_tuning
tune_vacuum = ensure_autovacuum_tuning
ensure_auto_tuning = ensure_autovacuum_tuning

invalidate_cache = _invalidate_cache
clear_cache = _invalidate_cache

probe_latency = _probe_db_latency
latency_report = diagnose_latency
check_latency = diagnose_latency
get_latency_report = diagnose_latency

full_health = diagnose_full
check_full_health = diagnose_full
health_report = diagnose_full

detect_bot_region = _detect_bot_cloud
detect_db_region = _guess_db_region
get_cross_region_info = get_region_info

databases_report = diagnose_databases
list_databases = diagnose_databases
multi_db_report = diagnose_databases
show_databases = diagnose_databases
get_active_db = _detect_active_db_source


# ═══════════════════════════════════════════════════════════════════════
# 15) __all__
# ═══════════════════════════════════════════════════════════════════════

__all__ = [
    "VERSION", "mark_process_start",
    "invalidate_cache", "clear_cache", "get_cache_stats",
    "diagnose_db", "diagnose_db_split", "diagnose_db_quick",
    "get_diagnostics_data",
    "diagnose_latency", "get_latency_verdict", "format_latency_report",
    "probe_latency", "latency_report", "check_latency", "get_latency_report",
    "diagnose_full", "get_full_health", "format_full_health_report",
    "full_health", "check_full_health", "health_report",
    "auto_vacuum_dirty_mvs", "auto_vacuum", "auto_cleanup",
    "cleanup_dead_tuples", "vacuum_dirty_tables",
    "ensure_autovacuum_tuning", "init_autovacuum_tuning",
    "format_autovacuum_tuning", "diagnose_autovacuum_tuning",
    "autovacuum_tune", "tune_autovacuum", "tune_vacuum", "ensure_auto_tuning",
    "preview_maintenance", "run_maintenance",
    "format_maintenance_preview", "format_maintenance_result",
    "diagnose_maintenance_preview", "run_db_maintenance",
    "vacuum_analyze_tables",
    "maintenance_preview", "preview_maintenance_html", "run_maintenance_html",
    "execute_maintenance", "perform_maintenance", "do_maintenance",
    "vacuum_all_tables", "vacuum_tables", "run_vacuum", "do_vacuum", "vacuum_db",
    "diagnose", "run_diagnostics", "get_diagnostics", "diagnose_postgres",
    "diag", "diagnose_database", "diagnose_split", "get_diagnostics_split",
    "diagnostics_split", "split_diagnostics", "get_diagnostics_report",
    "get_quick_health",
    "get_db_info", "get_database_info", "get_pg_info",
    "detect_bot_region", "detect_db_region", "get_cross_region_info",
    "get_region_info",
    "diagnose_databases", "get_all_databases_info", "format_multi_db_report",
    "format_active_db_line", "databases_report", "list_databases",
    "multi_db_report", "show_databases", "get_active_db",
    "diagnose_with_errors",
    "diagnose_findings_only",
    "format_findings_report",
    "get_findings",
    "run_findings_checks",
    "_DB_OWNED_TABLES",
    "_LONG_TX_THRESHOLD_SECONDS",
]


# ═══════════════════════════════════════════════════════════════════════
# LOAD BEACON — v7.3.1
# ═══════════════════════════════════════════════════════════════════════

try:
    _mark_state = "mark_called" if _PROCESS_START_TS > 0 else "import_ts(fallback)"
    _uptime_at_import = time.monotonic() - _PROCESS_IMPORT_TS
    logger.info(
        "🛡️ db_diagnostics.py v%s loaded | "
        "AUTOVACUUM-AGGRESSIVE-MANAGED ✅ | "
        "FIX-AV-1: managed_* → scale=0.0 + threshold=10 ✅ | "
        "KEPT v7.3.0: MERGE-1 (findings) + MERGE-2 (API) ✅ | "
        "KEPT v7.2.25: SAFETY-FIXES-AUDIT ✅ | "
        "DB-owned-tables=%d | long_tx_threshold=%ds | "
        "grace_sec=%d | cache_keys=%d | exports=%d | "
        "required_tables=%d | optional_tables=%d | "
        "mark_state=%s | process_age_at_import=%.1fs",
        VERSION,
        len(_DB_OWNED_TABLES),
        _LONG_TX_THRESHOLD_SECONDS,
        int(_STARTUP_GRACE_SEC),
        len(_CACHE_TTL),
        len(__all__),
        len(_REQUIRED_TABLES),
        len(_OPTIONAL_TABLES),
        _mark_state,
        _uptime_at_import,
    )
except Exception:
    pass