#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_diagnostics.py — واجهة تشخيص وصيانة قاعدة البيانات (v6.9.2 — FULL DETAILED)
================================================================================
الوظائف المُصدَّرة:

  📊 التشخيص الكامل:
    - diagnose_db()                   : تقرير كامل (HTML string) — 13 قسم
    - diagnose_db_split()             : List[str] — أجزاء منفصلة
    - diagnose_db_quick()             : تقرير صحي مختصر (5 أسطر)

  🧹 الصيانة:
    - preview_maintenance()           : معاينة الصيانة (dict)
    - run_maintenance()               : تنفيذ فعلي (dict)
    - format_maintenance_preview()    : تنسيق المعاينة → HTML
    - format_maintenance_result()     : تنسيق النتيجة → HTML
    - diagnose_maintenance_preview()  : معاينة مباشرة (HTML)
    - run_db_maintenance()            : تنفيذ مباشر (HTML)
    - vacuum_analyze_tables()         : VACUUM فقط

  🔧 مساعدات:
    - get_diagnostics_data()          : البيانات الخام
    - VERSION                         : "6.9.2"

⚠️ الاعتماد:
    - db_maintenance_commands.py v1.0.2+ يتوقع:
        diagnose_db_quick, preview_maintenance, run_maintenance,
        format_maintenance_preview, format_maintenance_result, VERSION

⚠️ v6.5.1+: user_violations يستخدم last_violation_time
    (بدل created_at) — لإصلاح خطأ "column does not exist".
================================================================================
"""

import logging
import html as _html
import asyncio
import time
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# الإصدار
# ═══════════════════════════════════════════════════════════════════════

VERSION = "6.9.2"


# ═══════════════════════════════════════════════════════════════════════
# Lazy imports
# ═══════════════════════════════════════════════════════════════════════

_DB_IMPORT_ERROR: Optional[str] = None


def _get_db():
    """Lazy import لـ DB — يعيد None إذا فشل."""
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


# ═══════════════════════════════════════════════════════════════════════
# أدوات مساعدة
# ═══════════════════════════════════════════════════════════════════════

def _safe_escape(text: Any) -> str:
    try:
        return _html.escape(str(text)) if text is not None else ""
    except Exception:
        return ""


# alias مختصر
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
    """تنسيق timestamp قصير: 2026-10-09 21:46"""
    if not ts:
        return "—"
    try:
        s = str(ts)
        if len(s) >= 16:
            return s[:16]
        return s
    except Exception:
        return "—"


def _bar(value: float, max_value: float, width: int = 10,
         filled: str = "█", empty: str = "░") -> str:
    try:
        v = float(value)
        m = float(max_value)
        if m <= 0:
            return empty * width
        ratio = min(1.0, max(0.0, v / m))
        n = int(round(ratio * width))
        return filled * n + empty * (width - n)
    except Exception:
        return empty * width


def _dead_color(dead: int, live: int) -> str:
    """لون ذكي لـ dead tuples."""
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


# ═══════════════════════════════════════════════════════════════════════
# 1) DB Metadata
# ═══════════════════════════════════════════════════════════════════════

async def _get_db_metadata() -> Dict[str, Any]:
    db = _get_db()
    meta = {
        "size_bytes": 0,
        "size_display": "?",
        "current_schema": "?",
        "schemas": [],
        "database_name": "?",
    }
    if db is None:
        return meta

    try:
        if _is_postgres():
            size_b = await db.fetchval(
                "SELECT pg_database_size(current_database())", default=0
            ) or 0
            meta["size_bytes"] = int(size_b)
            meta["size_display"] = _fmt_bytes(size_b)

            meta["current_schema"] = await db.fetchval(
                "SELECT current_schema()", default="public"
            ) or "public"

            rows = await db.fetchall(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname NOT LIKE 'pg_%' "
                "  AND nspname != 'information_schema' "
                "ORDER BY nspname"
            ) or []
            meta["schemas"] = [
                r.get("nspname") for r in rows
                if isinstance(r, dict) and r.get("nspname")
            ]

            meta["database_name"] = await db.fetchval(
                "SELECT current_database()", default="?"
            ) or "?"
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

    return meta


# ═══════════════════════════════════════════════════════════════════════
# 2) Dead Tuples + Clean Tables
# ═══════════════════════════════════════════════════════════════════════

async def _get_all_tables_health() -> Tuple[List[Dict], List[Dict]]:
    """يعيد (dirty_tables, clean_tables)."""
    db = _get_db()
    if db is None or not _is_postgres():
        return [], []

    try:
        rows = await db.fetchall("""
            SELECT
                c.relname AS table_name,
                s.n_live_tup AS live_tuples,
                s.n_dead_tup AS dead_tuples,
                s.n_mod_since_analyze,
                s.last_vacuum,
                s.last_autovacuum,
                s.last_analyze,
                s.last_autoanalyze,
                c.reloptions
            FROM pg_stat_user_tables s
            JOIN pg_class c ON c.oid = s.relid
            WHERE s.schemaname = current_schema()
            ORDER BY s.n_dead_tup DESC, s.n_live_tup DESC
        """) or []
    except Exception as e:
        logger.warning(f"_get_all_tables_health: {e}")
        return [], []

    dirty = []
    clean = []

    for r in rows:
        if not isinstance(r, dict):
            continue

        name = r.get("table_name") or "?"
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

        entry = {
            "name": name,
            "live": live,
            "dead": dead,
            "total": total,
            "ratio": ratio,
            "n_mod": n_mod,
            "last_av": last_av,
            "last_an": last_an,
            "auto_tuned": auto_tuned,
            "av_scale": av_scale,
            "an_scale": an_scale,
        }

        if dead > 0:
            dirty.append(entry)
        else:
            clean.append(entry)

    return dirty, clean


# ═══════════════════════════════════════════════════════════════════════
# 3) Activity Stats
# ═══════════════════════════════════════════════════════════════════════

async def _get_activity_stats() -> Dict[str, Any]:
    out = {
        "long_tx": 0,
        "idle_tx": 0,
        "vacuum_running": 0,
        "total_active": 0,
        "total_connections": 0,
    }
    db = _get_db()
    if db is None or not _is_postgres():
        return out

    try:
        row = await db.fetchone("""
            SELECT
                count(*) FILTER (WHERE state = 'active') AS active,
                count(*) FILTER (WHERE state = 'idle in transaction') AS idle_tx,
                count(*) FILTER (
                    WHERE state = 'active'
                      AND now() - xact_start > interval '5 minutes'
                ) AS long_tx,
                count(*) FILTER (
                    WHERE query ILIKE 'VACUUM%'
                      AND state = 'active'
                ) AS vacuum_running,
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

    return out


# ═══════════════════════════════════════════════════════════════════════
# 4) PG Settings
# ═══════════════════════════════════════════════════════════════════════

_CRITICAL_SETTINGS = (
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
    "idle_in_transaction_session_timeout",
    "statement_timeout",
    "server_version",
)


async def _get_pg_settings() -> Dict[str, str]:
    db = _get_db()
    if db is None or not _is_postgres():
        return {}

    try:
        rows = await db.fetchall("""
            SELECT name, setting, unit
            FROM pg_settings
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
        return out
    except Exception as e:
        logger.debug(f"_get_pg_settings: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════
# 5) Sizes + Indexes
# ═══════════════════════════════════════════════════════════════════════

async def _get_table_sizes(limit: int = 15) -> List[Dict[str, Any]]:
    db = _get_db()
    if db is None or not _is_postgres():
        return []
    fn = getattr(db, "get_table_sizes", None)
    if not callable(fn):
        return []
    try:
        return await fn(limit) or []
    except Exception as e:
        logger.debug(f"_get_table_sizes: {e}")
        return []


async def _get_indexes(tables: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    db = _get_db()
    if db is None or not _is_postgres():
        return {}
    fn = getattr(db, "get_indexes_info", None)
    if not callable(fn):
        return {}
    try:
        return await fn(tables) or {}
    except Exception as e:
        logger.debug(f"_get_indexes: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════
# 6) Auto-Cleanup Status
# ═══════════════════════════════════════════════════════════════════════

_CLEANUP_TABLES = (
    "admin_logs",
    "payment_logs",
    "sentiment_history",
    "user_messages",
    "bot_addition_log",
    "penalty_archive",
    "user_violations",
)
_CLEANUP_THRESHOLD_KB = 20 * 1024  # 20 MB


async def _get_cleanup_status() -> List[Dict[str, Any]]:
    db = _get_db()
    if db is None or not _is_postgres():
        return []

    try:
        rows = await db.fetchall("""
            SELECT relname AS table_name,
                   pg_total_relation_size(relid) AS total_bytes
            FROM pg_stat_user_tables
            WHERE relname = ANY($1::text[])
        """, (list(_CLEANUP_TABLES),)) or []
    except Exception as e:
        logger.debug(f"_get_cleanup_status: {e}")
        return []

    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = r.get("table_name")
        b = int(r.get("total_bytes") or 0)
        kb = b / 1024
        if kb >= _CLEANUP_THRESHOLD_KB:
            color = "🔴"
            status = "تجاوز الحد"
        elif kb >= _CLEANUP_THRESHOLD_KB * 0.75:
            color = "🟡"
            status = "قريب من الحد"
        else:
            color = "🟢"
            status = "ضمن الحد"
        out.append({
            "name": name,
            "bytes": b,
            "display": _fmt_bytes(b),
            "color": color,
            "status": status,
        })
    return out


# ═══════════════════════════════════════════════════════════════════════
# 7) Maintenance Helpers
# ═══════════════════════════════════════════════════════════════════════

async def _get_all_table_names() -> List[str]:
    """كل أسماء الجداول — لـ VACUUM."""
    db = _get_db()
    if db is None:
        return []
    if not _is_postgres():
        try:
            rows = await db.fetchall(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ) or []
            return [r.get("name") for r in rows
                    if isinstance(r, dict) and r.get("name")]
        except Exception:
            return []

    try:
        rows = await db.fetchall("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = current_schema()
            ORDER BY tablename
        """) or []
        return [r.get("tablename") for r in rows
                if isinstance(r, dict) and r.get("tablename")]
    except Exception as e:
        logger.debug(f"_get_all_table_names: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════
# 8) Technical Score
# ═══════════════════════════════════════════════════════════════════════

def _calc_technical_score(
    dirty: List[Dict],
    activity: Dict,
    settings: Dict,
) -> Tuple[int, int, int, int]:
    """يعيد (score/100, critical_count, warn_count, idle_tx_count)."""
    score = 100
    critical = 0
    warn = 0

    for t in dirty:
        r = t.get("ratio", 0)
        if r >= 0.20:
            critical += 1
            score -= 10
        elif r >= 0.10:
            warn += 1
            score -= 3

    if activity.get("long_tx", 0) > 0:
        score -= 5
    if activity.get("idle_tx", 0) > 0:
        score -= 2
    if settings.get("autovacuum") != "on":
        score -= 15

    score = max(0, min(100, score))
    return score, critical, warn, activity.get("idle_tx", 0)


# ═══════════════════════════════════════════════════════════════════════
# 9) Build Sections — التقرير الكامل (13 قسم)
# ═══════════════════════════════════════════════════════════════════════

async def _build_sections() -> List[str]:
    parts: List[str] = []

    # جمع البيانات
    meta = await _get_db_metadata()
    dirty, clean = await _get_all_tables_health()
    activity = await _get_activity_stats()
    settings = await _get_pg_settings()
    sizes = await _get_table_sizes(limit=15)
    cleanup_status = await _get_cleanup_status()
    all_tables = await _get_all_table_names()

    # الفهارس للجداول الحرجة
    critical_idx_tables = ["posts", "banned_words", "bot_groups",
                           "users", "user_channels", "subscriptions"]
    idx_map = await _get_indexes(critical_idx_tables)

    score, critical_count, warn_count, idle_tx_count = _calc_technical_score(
        dirty, activity, settings
    )
    total_dead = sum(t.get("dead", 0) for t in dirty)
    total_tables = len(dirty) + len(clean)

    # ═══════════════════════════════════════════════════════════
    # SECTION 1: Header + Metadata + Summary
    # ═══════════════════════════════════════════════════════════
    s1: List[str] = []
    s1.append(f"🔬 <b>تشخيص قاعدة البيانات v{VERSION}</b>")
    s1.append("━━━━━━━━━━━━━━━━━━━━━━")
    db_type_label = "PostgreSQL" if _is_postgres() else _get_db_type()
    s1.append(f"🗄️ <b>النوع:</b> {_esc(db_type_label)}")
    s1.append(f"💾 <b>الحجم:</b> {meta['size_display']}")
    s1.append(f"📋 <b>Schema:</b> {_esc(meta['current_schema'])}")
    if meta["schemas"]:
        s1.append(f"📋 <b>Schemas المتاحة:</b> {_esc(', '.join(meta['schemas']))}")
    s1.append(f"🗃️ <b>Database:</b> {_esc(meta['database_name'])}")
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
    av_setting = settings.get("autovacuum", "?")
    av_icon = "🟢" if av_setting == "on" else "🔴"
    s1.append(f"  autovacuum: {av_icon} <b>{_esc(av_setting).upper()}</b>")
    s1.append(f"  مؤشر الحالة التقني: <b>{score}/100</b> {score_icon}")
    parts.append("\n".join(s1))

    # ═══════════════════════════════════════════════════════════
    # SECTION 2: التحليل المنطقي
    # ═══════════════════════════════════════════════════════════
    s2: List[str] = []
    s2.append("╔══════════════════════════════════╗")
    s2.append("║  🎯 التحليل المنطقي          ║")
    s2.append("╚══════════════════════════════════╝")
    s2.append("")
    if av_setting == "on":
        s2.append("🟢 autovacuum = ON.")
    else:
        s2.append("🔴 autovacuum = OFF — خطر على الأداء.")

    if settings.get("synchronous_commit") == "off":
        s2.append("")
        s2.append("ℹ️ synchronous_commit=off — مقصود من v7.7.36 "
                  "لتحسين الأداء. لا تعتبره خطأً.")

    if critical_count > 0:
        s2.append("")
        s2.append(f"🔴 <b>{critical_count} جدول حرج</b> — راجع التفاصيل.")
    parts.append("\n".join(s2))

    # ═══════════════════════════════════════════════════════════
    # SECTION 3: Dead Tuples
    # ═══════════════════════════════════════════════════════════
    if dirty:
        s3: List[str] = []
        s3.append("━━━━━━━━━━━━━━━━━━━━━━")
        s3.append("📊 <b>التفاصيل الكاملة</b>")
        s3.append("━━━━━━━━━━━━━━━━━━━━━━")
        s3.append("")
        s3.append("1. <b>Dead Tuples + نشاط التنظيف</b>")
        s3.append("")
        for t in dirty[:20]:
            color = _dead_color(t["dead"], t["live"])
            name = _esc(t["name"])
            ratio_pct = t["ratio"] * 100
            s3.append(f"{color} <b>{name}</b>")
            s3.append(f"     live={_fmt_num(t['live'])} "
                      f"dead={_fmt_num(t['dead'])} ({ratio_pct:.1f}%)")
            av = _fmt_ts(t["last_av"])
            an = _fmt_ts(t["last_an"])
            mod = t["n_mod"]
            s3.append(f"     🧹 AV: {av} | 📊 AN: {an} | 🔄 mod={mod}")
            s3.append("")
        parts.append("\n".join(s3))

    # ═══════════════════════════════════════════════════════════
    # SECTION 3b: Clean Tables
    # ═══════════════════════════════════════════════════════════
    if clean:
        s3b: List[str] = []
        s3b.append("1b. <b>جداول نظيفة (dead=0)</b>")
        s3b.append("")
        clean_sorted = sorted(clean, key=lambda x: -x["live"])
        for t in clean_sorted[:15]:
            an = _fmt_ts(t["last_an"])
            s3b.append(f"✅ <b>{_esc(t['name'])}</b>")
            s3b.append(f"     live={_fmt_num(t['live'])} | 📊 AN: {an}")
        if len(clean_sorted) > 15:
            s3b.append(f"… و{len(clean_sorted) - 15} جدول نظيف آخر")
        parts.append("\n".join(s3b))

    # ═══════════════════════════════════════════════════════════
    # SECTION 4: Autovacuum Tuning
    # ═══════════════════════════════════════════════════════════
    tuned = [t for t in dirty + clean if t.get("auto_tuned")]
    not_tuned = [t for t in dirty + clean if not t.get("auto_tuned")]

    s4: List[str] = []
    s4.append("2. <b>Autovacuum للجداول الحرجة (HEAVY)</b>")
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
        s4b.append(f"2b. <b>جداول ليست مضبوطة autovacuum "
                   f"({len(not_tuned)} من {len(tuned) + len(not_tuned)})</b>")
        s4b.append("")
        for t in not_tuned[:15]:
            s4b.append(f"⚙️ <b>{_esc(t['name'])}</b> — "
                       f"live={_fmt_num(t['live'])} dead={_fmt_num(t['dead'])}")
        if len(not_tuned) > 15:
            s4b.append(f"… و{len(not_tuned) - 15} آخر")
        parts.append("\n".join(s4b))

    # ═══════════════════════════════════════════════════════════
    # SECTION 5: Activity
    # ═══════════════════════════════════════════════════════════
    s5: List[str] = []
    s5.append("3. <b>نشاط PostgreSQL / Blockers</b>")
    s5.append("")
    if (activity.get("long_tx", 0) == 0
            and activity.get("idle_tx", 0) == 0
            and activity.get("vacuum_running", 0) == 0):
        s5.append("✅ لا توجد معاملات طويلة / idle-in-tx / VACUUM جارٍ.")
    else:
        if activity.get("long_tx", 0):
            s5.append(f"⚠️ Long transactions: <b>{activity['long_tx']}</b>")
        if activity.get("idle_tx", 0):
            s5.append(f"🟠 Idle transactions: <b>{activity['idle_tx']}</b>")
        if activity.get("vacuum_running", 0):
            s5.append(f"🧹 VACUUM قيد التنفيذ: <b>{activity['vacuum_running']}</b>")
    s5.append(f"📊 إجمالي الاتصالات: <b>{activity.get('total_connections', 0)}</b>")
    parts.append("\n".join(s5))

    # ═══════════════════════════════════════════════════════════
    # SECTION 6: Table Sizes
    # ═══════════════════════════════════════════════════════════
    if sizes:
        s6: List[str] = []
        s6.append("4. <b>أحجام الجداول — Top 15</b>")
        s6.append("")
        for t in sizes[:15]:
            name = t.get("name", "?")
            display = t.get("total_display", "0 B")
            s6.append(f"  <code>{_esc(name):<22}</code> {display}")
        parts.append("\n".join(s6))

    # ═══════════════════════════════════════════════════════════
    # SECTION 7: Indexes
    # ═══════════════════════════════════════════════════════════
    if idx_map:
        s7: List[str] = []
        s7.append("5. <b>الفهارس الحرجة (يدوياً)</b>")
        s7.append("")
        for tname in critical_idx_tables:
            if tname in idx_map:
                cnt = len(idx_map[tname])
                s7.append(f"✅ <b>{_esc(tname)}</b> ({cnt})")
        parts.append("\n".join(s7))

    # ═══════════════════════════════════════════════════════════
    # SECTION 8: PG Settings
    # ═══════════════════════════════════════════════════════════
    if settings:
        s8: List[str] = []
        s8.append("6. <b>إعدادات PostgreSQL</b>")
        s8.append("")
        for k in _CRITICAL_SETTINGS:
            if k in settings:
                s8.append(f"  <code>{_esc(k)}</code> = {_esc(settings[k])}")
        parts.append("\n".join(s8))

    # ═══════════════════════════════════════════════════════════
    # SECTION 9: Auto-Cleanup
    # ═══════════════════════════════════════════════════════════
    if cleanup_status:
        s9: List[str] = []
        s9.append("8. <b>Auto-Cleanup</b>")
        s9.append("")
        for c in cleanup_status:
            s9.append(f"  {c['color']} <b>{_esc(c['name'])}</b> — "
                      f"{c['display']} (الحد: 20MB) — {c['status']}")
        s9.append("")
        s9.append("⚙️ يُشغَّل كل 6h | VACUUM: ON 🟢 | Mode: all")
        parts.append("\n".join(s9))

    # ═══════════════════════════════════════════════════════════
    # SECTION 10: Footer
    # ═══════════════════════════════════════════════════════════
    parts.append(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ <b>اكتمل التشخيص</b>\n"
        f"🕐 <i>{_now_iso()}</i>"
    )

    # ═══════════════════════════════════════════════════════════
    # SECTION 11: Maintenance Preview
    # ═══════════════════════════════════════════════════════════
    preview = await preview_maintenance()
    s11_text = format_maintenance_preview(preview)
    parts.append(s11_text)

    return parts


# ═══════════════════════════════════════════════════════════════════════
# 10) التشخيص العام — Public API
# ═══════════════════════════════════════════════════════════════════════

async def diagnose_db() -> str:
    """التقرير الكامل (HTML string)."""
    parts = await _build_sections()
    return "\n\n".join(parts)


async def diagnose_db_split() -> List[str]:
    """التقرير مقسّم لأجزاء."""
    return await _build_sections()


async def diagnose_db_quick() -> str:
    """تقرير صحي مختصر (5 أسطر)."""
    db = _get_db()
    if db is None:
        return "❌ DB غير مستورد"

    lines: List[str] = []

    try:
        meta = await _get_db_metadata()
        db_type = "PostgreSQL" if _is_postgres() else _get_db_type()
        lines.append(f"🔬 <b>DB:</b> {db_type} | 💾 {meta['size_display']}")
    except Exception:
        lines.append(f"🔬 <b>DB:</b> {_get_db_type()}")

    total_dead = 0
    critical = 0
    try:
        dirty, clean = await _get_all_tables_health()
        total_dead = sum(t.get("dead", 0) for t in dirty)
        critical = sum(1 for t in dirty if t.get("ratio", 0) >= 0.20)
    except Exception:
        pass
    lines.append(
        f"💀 Dead: <b>{_fmt_num(total_dead)}</b> | "
        f"🔴 حرجة: <b>{critical}</b>"
    )

    try:
        activity = await _get_activity_stats()
        idle = activity.get("idle_tx", 0)
        long_tx = activity.get("long_tx", 0)
        idle_icon = "🟢" if idle == 0 else ("🟡" if idle < 3 else "🔴")
        long_icon = "🟢" if long_tx == 0 else "🔴"
        lines.append(
            f"{idle_icon} idle-tx: <b>{idle}</b> | "
            f"{long_icon} long-tx: <b>{long_tx}</b>"
        )
    except Exception:
        lines.append("🟠 idle-tx: ? | long-tx: ?")

    try:
        settings = await _get_pg_settings()
        av = settings.get("autovacuum", "?")
        av_icon = "🟢" if av == "on" else "🔴"
        lines.append(f"{av_icon} autovacuum: <b>{_esc(av).upper()}</b>")
    except Exception:
        pass

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 11) Maintenance — dict-based API
# ═══════════════════════════════════════════════════════════════════════

async def preview_maintenance() -> Dict[str, Any]:
    """
    معاينة الصيانة — dict.

    ⚠️ v6.5.1: user_violations → last_violation_time.
    """
    db = _get_db()
    result: Dict[str, Any] = {
        'plan': [],
        'total_deletions': 0,
        'vacuum_tables': [],
        'db_type': _get_db_type(),
    }
    if db is None:
        return result

    # ⚠️ user_violations → last_violation_time
    deletions_spec = [
        ("admin_logs", "created_at", 30),
        ("penalty_archive", "created_at", 90),
        ("user_violations", "last_violation_time", 90),
    ]

    total = 0
    for tbl, col, days in deletions_spec:
        entry = {
            'name': tbl,
            'column': col,
            'days': days,
            'threshold_str': f">{days}d",
            'count': 0,
            'error': None,
        }
        try:
            if _is_postgres():
                row = await db.fetchone(
                    f"SELECT COUNT(*) AS cnt FROM {tbl} "
                    f"WHERE {col} < NOW() - INTERVAL '{days} days'"
                )
                cnt = int((row or {}).get("cnt") or 0)
                entry['count'] = cnt
                total += cnt
            else:
                entry['count'] = 0
        except Exception as e:
            logger.warning(f"preview_maintenance({tbl}): {e}")
            entry['count'] = -1
            entry['error'] = str(e)[:100]

        result['plan'].append(entry)

    result['total_deletions'] = total
    result['vacuum_tables'] = await _get_all_table_names()
    return result


async def run_maintenance() -> Dict[str, Any]:
    """
    تنفيذ الصيانة — dict.

    ⚠️ v6.5.1: user_violations → last_violation_time.
    """
    db = _get_db()
    start = time.monotonic()
    result: Dict[str, Any] = {
        'duration_sec': 0.0,
        'deletions': {},
        'deletion_errors': {},
        'vacuum': {'success': 0, 'failed': 0, 'details': []},
    }
    if db is None:
        result['duration_sec'] = round(time.monotonic() - start, 2)
        return result

    # ═══ 1. الحذف ═══
    deletions_spec = [
        ("admin_logs", "created_at", 30),
        ("penalty_archive", "created_at", 90),
        ("user_violations", "last_violation_time", 90),
    ]

    for tbl, col, days in deletions_spec:
        try:
            if _is_postgres():
                r = await db.execute(
                    f"DELETE FROM {tbl} "
                    f"WHERE {col} < NOW() - INTERVAL '{days} days'"
                )
                result['deletions'][tbl] = int(r or 0)
            else:
                result['deletions'][tbl] = 0
        except Exception as e:
            logger.warning(f"run_maintenance delete({tbl}): {e}")
            result['deletions'][tbl] = 0
            result['deletion_errors'][tbl] = str(e)[:100]

    # ═══ 2. VACUUM ═══
    tables = await _get_all_table_names()
    for t in tables:
        try:
            if hasattr(db, "vacuum") and callable(db.vacuum):
                await db.vacuum(t)
            else:
                await db.execute(f"VACUUM ANALYZE {t}")
            result['vacuum']['success'] += 1
            result['vacuum']['details'].append((t, True, None))
        except Exception as e:
            err = str(e).lower()
            if "does not exist" in err or "no such" in err:
                result['vacuum']['details'].append((t, True, "skip"))
            else:
                result['vacuum']['failed'] += 1
                result['vacuum']['details'].append(
                    (t, False, str(e)[:80])
                )
        try:
            await asyncio.sleep(0.05)
        except Exception:
            pass

    result['duration_sec'] = round(time.monotonic() - start, 2)
    return result


# ═══════════════════════════════════════════════════════════════════════
# 12) Maintenance — HTML formatters
# ═══════════════════════════════════════════════════════════════════════

def format_maintenance_preview(preview: Dict[str, Any]) -> str:
    """تنسيق معاينة الصيانة → HTML."""
    lines: List[str] = []
    lines.append("🧹 <b>معاينة الصيانة</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("🗑️ <b>الحذف المخطط:</b>")

    plan = preview.get('plan', []) if isinstance(preview, dict) else []
    has_errors = False

    for item in plan:
        if not isinstance(item, dict):
            continue
        name = _esc(item.get('name', '?'))
        threshold = _esc(item.get('threshold_str', '?'))
        cnt = item.get('count', 0)
        err = item.get('error')

        if cnt == -1:
            icon = "❌"
            val = f"<i>فشل: {_esc(err or '?')[:60]}</i>"
            has_errors = True
        elif cnt == 0:
            icon = "✅"
            val = "لا شيء"
        else:
            icon = "⚠️"
            val = str(cnt)

        lines.append(
            f"  {icon} <code>{name:<20}</code> ({threshold}): {val}"
        )

    lines.append("")
    total = (preview.get('total_deletions', 0)
             if isinstance(preview, dict) else 0)
    lines.append(f"📊 <b>الإجمالي:</b> {total} صف سيُحذف")
    lines.append("")

    tables = (preview.get('vacuum_tables', [])
              if isinstance(preview, dict) else [])
    if tables:
        lines.append(f"🧹 <b>VACUUM سيعمل على ({len(tables)} جدول):</b>")
        for t in tables:
            lines.append(f"  • {_esc(t)}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("لتنفيذ الصيانة، أرسل:")
    lines.append("<code>/db_maintenance confirm</code>")

    if has_errors:
        lines.append("")
        lines.append(
            "⚠️ <i>بعض استعلامات العدّ فشلت — "
            "تأكد من تحديث db_diagnostics</i>"
        )

    return "\n".join(lines)


def format_maintenance_result(result: Dict[str, Any]) -> str:
    """تنسيق نتيجة الصيانة → HTML."""
    lines: List[str] = []
    lines.append("✅ <b>اكتملت الصيانة بنجاح</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    duration = (result.get('duration_sec', 0.0)
                if isinstance(result, dict) else 0.0)
    lines.append(f"⏱️ <b>المدة:</b> {duration:.2f}s")
    lines.append("")

    # الحذف
    lines.append("🗑️ <b>الحذف:</b>")
    deletions = (result.get('deletions', {})
                 if isinstance(result, dict) else {})
    deletion_errors = (result.get('deletion_errors', {})
                       if isinstance(result, dict) else {})

    if not deletions:
        lines.append("  ℹ️ لا توجد عمليات حذف")
    else:
        for name, cnt in deletions.items():
            if name in deletion_errors:
                icon = "❌"
                val = "<i>فشل</i>"
            elif cnt == 0:
                icon = "✅"
                val = "لا شيء"
            else:
                icon = "🗑️"
                val = str(cnt)
            lines.append(f"  {icon} <code>{_esc(name):<20}</code> {val}")

    lines.append("")

    # VACUUM
    lines.append("🧹 <b>VACUUM:</b>")
    vacuum = (result.get('vacuum', {})
              if isinstance(result, dict) else {})
    details = (vacuum.get('details', [])
               if isinstance(vacuum, dict) else [])

    if not details:
        lines.append("  ℹ️ لا توجد عمليات VACUUM")
    else:
        for item in details:
            if not isinstance(item, tuple) or len(item) < 3:
                continue
            tname, ok, err = item
            if ok and err is None:
                lines.append(f"  ✅ {_esc(tname)}")
            elif ok and err == "skip":
                lines.append(f"  ⏭️ {_esc(tname)} <i>(غير موجود)</i>")
            else:
                lines.append(
                    f"  ❌ {_esc(tname)} — "
                    f"<code>{_esc(str(err or '?')[:60])}</code>"
                )

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    success = (vacuum.get('success', 0)
               if isinstance(vacuum, dict) else 0)
    failed = (vacuum.get('failed', 0)
              if isinstance(vacuum, dict) else 0)
    lines.append(f"📊 <b>نجح:</b> {success} | <b>فشل:</b> {failed}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 13) Maintenance — HTML shortcuts
# ═══════════════════════════════════════════════════════════════════════

async def diagnose_maintenance_preview() -> str:
    """معاينة مباشرة → HTML."""
    preview = await preview_maintenance()
    return format_maintenance_preview(preview)


async def run_db_maintenance() -> str:
    """تنفيذ مباشر → HTML."""
    result = await run_maintenance()
    return format_maintenance_result(result)


async def vacuum_analyze_tables() -> str:
    """VACUUM ANALYZE فقط → HTML."""
    db = _get_db()
    if db is None:
        return "❌ DB غير مستورد"

    start = time.monotonic()
    tables = await _get_all_table_names()
    lines = ["🧹 <b>VACUUM ANALYZE</b>", "━━━━━━━━━━━━━━━━━━━━━━", ""]

    success = 0
    fail = 0
    for t in tables:
        try:
            if hasattr(db, "vacuum") and callable(db.vacuum):
                await db.vacuum(t)
            else:
                await db.execute(f"VACUUM ANALYZE {t}")
            success += 1
            lines.append(f"  ✅ {_esc(t)}")
        except Exception as e:
            err = str(e).lower()
            if "does not exist" in err or "no such" in err:
                lines.append(f"  ⏭️ {_esc(t)}")
            else:
                fail += 1
                lines.append(f"  ❌ {_esc(t)} — "
                             f"<code>{_esc(str(e)[:60])}</code>")
        await asyncio.sleep(0.05)

    elapsed = time.monotonic() - start
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"⏱️ المدة: {elapsed:.2f}s | "
                 f"✅ نجح: {success} | ❌ فشل: {fail}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 14) Data Accessor — للتوافق
# ═══════════════════════════════════════════════════════════════════════

async def get_diagnostics_data(top_n: int = 15) -> Dict[str, Any]:
    """البيانات الخام — dict."""
    parts = await _build_sections()
    return {
        "sections": parts,
        "available": True,
        "db_type": _get_db_type(),
        "version": VERSION,
    }


# ═══════════════════════════════════════════════════════════════════════
# 15) Aliases — للتوافق مع كل الأسماء المحتملة
# ═══════════════════════════════════════════════════════════════════════

# Maintenance aliases
maintenance_preview = diagnose_maintenance_preview
preview_maintenance_html = diagnose_maintenance_preview
run_maintenance_html = run_db_maintenance
execute_maintenance = run_db_maintenance
perform_maintenance = run_db_maintenance
do_maintenance = run_db_maintenance

# Vacuum aliases
vacuum_all_tables = vacuum_analyze_tables
vacuum_tables = vacuum_analyze_tables
run_vacuum = vacuum_analyze_tables
do_vacuum = vacuum_analyze_tables
vacuum_db = vacuum_analyze_tables

# Diagnostics aliases
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

# Helpers
get_db_info = _get_db_metadata
get_database_info = _get_db_metadata
get_pg_info = _get_db_metadata


# ═══════════════════════════════════════════════════════════════════════
# 16) __all__
# ═══════════════════════════════════════════════════════════════════════

__all__ = [
    # Meta
    "VERSION",
    # Diagnostics
    "diagnose_db",
    "diagnose_db_split",
    "diagnose_db_quick",
    "get_diagnostics_data",
    # Maintenance (dict API) — v6.9.2
    "preview_maintenance",
    "run_maintenance",
    # Maintenance (HTML formatters) — v6.9.2
    "format_maintenance_preview",
    "format_maintenance_result",
    # Maintenance (HTML shortcuts)
    "diagnose_maintenance_preview",
    "run_db_maintenance",
    "vacuum_analyze_tables",
    # Aliases — maintenance
    "maintenance_preview",
    "preview_maintenance_html",
    "run_maintenance_html",
    "execute_maintenance",
    "perform_maintenance",
    "do_maintenance",
    # Aliases — vacuum
    "vacuum_all_tables",
    "vacuum_tables",
    "run_vacuum",
    "do_vacuum",
    "vacuum_db",
    # Aliases — diagnostics
    "diagnose",
    "run_diagnostics",
    "get_diagnostics",
    "diagnose_postgres",
    "diag",
    "diagnose_database",
    "diagnose_split",
    "get_diagnostics_split",
    "diagnostics_split",
    "split_diagnostics",
    "get_diagnostics_report",
    "get_quick_health",
    # Helpers
    "get_db_info",
    "get_database_info",
    "get_pg_info",
]


# ═══════════════════════════════════════════════════════════════════════
# LOAD BEACON — v6.9.2
# ═══════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "🛡️ db_diagnostics.py v%s loaded | "
        "13 sections + full maintenance API | "
        "user_violations.last_violation_time ✅ | exports=%d",
        VERSION,
        len(__all__),
    )
except Exception:
    pass