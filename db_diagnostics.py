#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_diagnostics.py — واجهة تشخيص قاعدة البيانات (v6.9.1 — FULL DETAILED)
================================================================================
محاكاة كاملة للتقرير القديم مع 13 قسماً:

  1. Header + DB metadata (الحجم، Schema، Database name)
  2. الخلاصة التقنية (score/100 + جداول حرجة)
  3. التحليل المنطقي
  4. Dead Tuples + نشاط التنظيف (مفصّل: AV/AN/mod)
  4b. الجداول النظيفة (dead=0)
  5. Autovacuum للجداول الحرجة
  5b. الجداول غير المضبوطة
  6. نشاط PostgreSQL / Blockers
  7. أحجام الجداول Top 15
  8. الفهارس الحرجة
  9. إعدادات PostgreSQL
  10. Auto-Cleanup status
  11. معاينة الصيانة
  12. قائمة VACUUM الكاملة
  13. التنفيذ (/db_maintenance confirm)

الأسماء المُصدَّرة (متوقعة من handlers_command.py):
  - diagnose_db()             : تقرير كامل (HTML string)
  - diagnose_db_split()       : List[str] — أجزاء
  - vacuum_analyze_tables()   : VACUUM ANALYZE
  - diagnose_maintenance_preview() : معاينة الصيانة
  - run_db_maintenance()      : تنفيذ الصيانة الفعلي
================================================================================
"""

import logging
import html as _html
import asyncio
import time
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger(__name__)


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


# ═══════════════════════════════════════════════════════════════════════
# أدوات مساعدة
# ═══════════════════════════════════════════════════════════════════════

def _esc(text: Any) -> str:
    try:
        return _html.escape(str(text)) if text is not None else ""
    except Exception:
        return ""


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


# ═══════════════════════════════════════════════════════════════════════
# 1) Metadata
# ═══════════════════════════════════════════════════════════════════════

async def _get_db_metadata() -> Dict[str, Any]:
    """جلب معلومات DB الحجم/الإسم/Schema."""
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
            size_kb = await db.get_db_size_kb() if hasattr(db, "get_db_size_kb") else 0
            meta["size_bytes"] = int(size_kb * 1024)
            meta["size_display"] = _fmt_bytes(meta["size_bytes"])
            meta["current_schema"] = "main"
            meta["schemas"] = ["main"]
            meta["database_name"] = "sqlite"
    except Exception as e:
        logger.debug(f"_get_db_metadata: {e}")

    return meta


# ═══════════════════════════════════════════════════════════════════════
# 2) Dead Tuples + Clean Tables + Autovacuum tuning
# ═══════════════════════════════════════════════════════════════════════

async def _get_all_tables_health() -> Tuple[List[Dict], List[Dict]]:
    """
    يعيد (dirty_tables, clean_tables).

    كل جدول: {name, live, dead, ratio, last_av, last_an, n_mod,
              auto_tuned, av_scale, an_scale}
    """
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

        # فحص autovacuum tuning
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


def _dead_color(dead: int, live: int) -> str:
    """لون ذكي."""
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
# 3) PostgreSQL Activity / Blockers
# ═══════════════════════════════════════════════════════════════════════

async def _get_activity_stats() -> Dict[str, Any]:
    """Long tx / idle tx / vacuum running."""
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
# 4) PostgreSQL Settings
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
# 5) Table sizes + Indexes
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
# 6) Auto-Cleanup thresholds
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
# 7) Maintenance preview
# ═══════════════════════════════════════════════════════════════════════

async def _get_maintenance_preview() -> Dict[str, Any]:
    """يحسب ما سيُحذف عند /db_maintenance."""
    db = _get_db()
    if db is None:
        return {"deletions": {}, "total_deletions": 0}

    out = {
        "deletions": {
            "admin_logs_30d": 0,
            "penalty_archive_90d": 0,
            "user_violations_90d": 0,
        },
        "total_deletions": 0,
    }

    if not _is_postgres():
        return out

    try:
        row = await db.fetchone("""
            SELECT
                (SELECT COUNT(*) FROM admin_logs
                 WHERE created_at < NOW() - INTERVAL '30 days') AS al,
                (SELECT COUNT(*) FROM penalty_archive
                 WHERE created_at < NOW() - INTERVAL '90 days') AS pa,
                (SELECT COUNT(*) FROM user_violations
                 WHERE created_at < NOW() - INTERVAL '90 days') AS uv
        """) or {}
        if isinstance(row, dict):
            out["deletions"]["admin_logs_30d"] = int(row.get("al") or 0)
            out["deletions"]["penalty_archive_90d"] = int(row.get("pa") or 0)
            out["deletions"]["user_violations_90d"] = int(row.get("uv") or 0)
            out["total_deletions"] = sum(out["deletions"].values())
    except Exception as e:
        logger.debug(f"_get_maintenance_preview: {e}")

    return out


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
# 8) Build Sections
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


async def _build_sections() -> List[str]:
    parts: List[str] = []

    # جمع البيانات
    meta = await _get_db_metadata()
    dirty, clean = await _get_all_tables_health()
    activity = await _get_activity_stats()
    settings = await _get_pg_settings()
    sizes = await _get_table_sizes(limit=15)
    cleanup_status = await _get_cleanup_status()
    preview = await _get_maintenance_preview()
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
    s1.append("🔬 <b>تشخيص قاعدة البيانات v6.9.1</b>")
    s1.append("━━━━━━━━━━━━━━━━━━━━━━")
    s1.append(f"🗄️ <b>النوع:</b> {_esc(meta['database_name']) and 'PostgreSQL' or _get_db_type()}")
    s1.append(f"💾 <b>الحجم:</b> {meta['size_display']}")
    s1.append(f"📋 <b>Schema:</b> {_esc(meta['current_schema'])}")
    if meta["schemas"]:
        s1.append(f"📋 <b>Schemas المتاحة:</b> {_esc(', '.join(meta['schemas']))}")
    s1.append(f"🗃️ <b>Database:</b> {_esc(meta['database_name'])}")
    s1.append("")

    # الخلاصة التقنية
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
    # SECTION 3: Dead Tuples المُفصَّل
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
    # SECTION 3b: الجداول النظيفة
    # ═══════════════════════════════════════════════════════════
    if clean:
        s3b: List[str] = []
        s3b.append("1b. <b>جداول نظيفة (dead=0)</b>")
        s3b.append("")
        # رتب حسب live تنازلياً
        clean_sorted = sorted(clean, key=lambda x: -x["live"])
        for t in clean_sorted[:15]:
            an = _fmt_ts(t["last_an"])
            s3b.append(f"✅ <b>{_esc(t['name'])}</b>")
            s3b.append(f"     live={_fmt_num(t['live'])} | 📊 AN: {an}")
        if len(clean_sorted) > 15:
            s3b.append(f"… و{len(clean_sorted) - 15} جدول نظيف آخر")
        parts.append("\n".join(s3b))

    # ═══════════════════════════════════════════════════════════
    # SECTION 4: Autovacuum tuning
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

    # الجداول غير المضبوطة
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
    # SECTION 6: أحجام الجداول Top 15
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
    # SECTION 7: الفهارس الحرجة
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
    # SECTION 8: PostgreSQL Settings
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
    s11: List[str] = []
    s11.append("")
    s11.append("🧹 <b>معاينة الصيانة</b>")
    s11.append("━━━━━━━━━━━━━━━━━━━━━━")
    s11.append("")
    s11.append("🗑️ <b>الحذف المخطط:</b>")
    d = preview.get("deletions", {})
    s11.append(f"  {'✅' if d.get('admin_logs_30d', 0) == 0 else '⚠️'} "
               f"admin_logs (>30d): "
               f"{'لا شيء' if d.get('admin_logs_30d', 0) == 0 else d['admin_logs_30d']}")
    s11.append(f"  {'✅' if d.get('penalty_archive_90d', 0) == 0 else '⚠️'} "
               f"penalty_archive (>90d): "
               f"{'لا شيء' if d.get('penalty_archive_90d', 0) == 0 else d['penalty_archive_90d']}")
    s11.append(f"  {'✅' if d.get('user_violations_90d', 0) == 0 else '⚠️'} "
               f"user_violations (>90d): "
               f"{'لا شيء' if d.get('user_violations_90d', 0) == 0 else d['user_violations_90d']}")
    s11.append("")
    total_del = preview.get("total_deletions", 0)
    s11.append(f"📊 <b>الإجمالي:</b> {total_del} صف سيُحذف")
    s11.append("")

    if all_tables:
        s11.append(f"🧹 <b>VACUUM سيعمل على ({len(all_tables)} جدول):</b>")
        for t in all_tables:
            s11.append(f"  • {_esc(t)}")
    parts.append("\n".join(s11))

    # ═══════════════════════════════════════════════════════════
    # SECTION 12: تنفيذ
    # ═══════════════════════════════════════════════════════════
    parts.append(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "لتنفيذ الصيانة، أرسل:\n"
        "<code>/db_maintenance confirm</code>"
    )

    return parts


# ═══════════════════════════════════════════════════════════════════════
# 9) Public API
# ═══════════════════════════════════════════════════════════════════════

async def diagnose_db() -> str:
    """التقرير الكامل (HTML string)."""
    parts = await _build_sections()
    return "\n\n".join(parts)


async def diagnose_db_split() -> List[str]:
    """التقرير مقسّم لأجزاء."""
    return await _build_sections()


async def diagnose_maintenance_preview() -> str:
    """معاينة الصيانة منفصلة (للـ /db_maintenance)."""
    preview = await _get_maintenance_preview()
    all_tables = await _get_all_table_names()

    lines = []
    lines.append("🧹 <b>معاينة الصيانة</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("🗑️ <b>الحذف المخطط:</b>")
    d = preview.get("deletions", {})
    for key, label in (
        ("admin_logs_30d", "admin_logs (>30d)"),
        ("penalty_archive_90d", "penalty_archive (>90d)"),
        ("user_violations_90d", "user_violations (>90d)"),
    ):
        cnt = d.get(key, 0)
        icon = "✅" if cnt == 0 else "⚠️"
        val = "لا شيء" if cnt == 0 else cnt
        lines.append(f"  {icon} {label}: {val}")
    lines.append("")
    lines.append(f"📊 <b>الإجمالي:</b> "
                 f"{preview.get('total_deletions', 0)} صف سيُحذف")
    lines.append("")
    if all_tables:
        lines.append(f"🧹 <b>VACUUM سيعمل على ({len(all_tables)} جدول):</b>")
        for t in all_tables:
            lines.append(f"  • {_esc(t)}")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("لتنفيذ الصيانة، أرسل:")
    lines.append("<code>/db_maintenance confirm</code>")
    return "\n".join(lines)


async def run_db_maintenance() -> str:
    """تنفيذ الصيانة الفعلية (حذف + VACUUM)."""
    db = _get_db()
    if db is None:
        return "❌ DB غير مستورد"

    start = time.monotonic()
    lines: List[str] = []
    lines.append("✅ <b>اكتملت الصيانة بنجاح</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    # ═══ 1. الحذف ═══
    deleted = {
        "admin_logs": 0,
        "penalty_archive": 0,
        "user_violations": 0,
    }

    if _is_postgres():
        try:
            r = await db.execute(
                "DELETE FROM admin_logs "
                "WHERE created_at < NOW() - INTERVAL '30 days'"
            )
            deleted["admin_logs"] = int(r or 0)
        except Exception as e:
            logger.warning(f"cleanup admin_logs: {e}")
        try:
            r = await db.execute(
                "DELETE FROM penalty_archive "
                "WHERE created_at < NOW() - INTERVAL '90 days'"
            )
            deleted["penalty_archive"] = int(r or 0)
        except Exception as e:
            logger.warning(f"cleanup penalty_archive: {e}")
        try:
            r = await db.execute(
                "DELETE FROM user_violations "
                "WHERE created_at < NOW() - INTERVAL '90 days'"
            )
            deleted["user_violations"] = int(r or 0)
        except Exception as e:
            logger.warning(f"cleanup user_violations: {e}")

    lines.append("🗑️ <b>الحذف:</b>")
    for name, cnt in deleted.items():
        icon = "✅" if cnt == 0 else "🗑️"
        val = "لا شيء" if cnt == 0 else cnt
        lines.append(f"  {icon} {_esc(name):<20} {val}")
    lines.append("")

    # ═══ 2. VACUUM ═══
    all_tables = await _get_all_table_names()
    lines.append("🧹 <b>VACUUM:</b>")
    success = 0
    fail = 0
    for t in all_tables:
        try:
            if hasattr(db, "vacuum"):
                await db.vacuum(t)
            else:
                await db.execute(f"VACUUM ANALYZE {t}")
            success += 1
            lines.append(f"  ✅ {_esc(t)}")
        except Exception as e:
            err = str(e).lower()
            if "does not exist" in err or "no such" in err:
                lines.append(f"  ⏭️ {_esc(t)} (غير موجود)")
            else:
                fail += 1
                lines.append(f"  ❌ {_esc(t)} — "
                             f"<code>{_esc(str(e)[:60])}</code>")
        await asyncio.sleep(0.05)

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    elapsed = time.monotonic() - start
    lines.append(f"⏱️ <b>المدة:</b> {elapsed:.2f}s")
    lines.append(f"📊 <b>نجح:</b> {success} | <b>فشل:</b> {fail}")

    return "\n".join(lines)


async def vacuum_analyze_tables() -> str:
    """VACUUM سريع (بدون حذف)."""
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
            if hasattr(db, "vacuum"):
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


# Aliases
async def get_diagnostics_data(top_n: int = 15) -> Dict[str, Any]:
    """للتوافق — يعيد نفس الأقسام كـ dict."""
    parts = await _build_sections()
    return {
        "sections": parts,
        "available": True,
        "db_type": _get_db_type(),
    }


__all__ = [
    "diagnose_db",
    "diagnose_db_split",
    "diagnose_maintenance_preview",
    "run_db_maintenance",
    "vacuum_analyze_tables",
    "get_diagnostics_data",
]


try:
    logger.info(
        "🛡️ db_diagnostics.py v6.9.1 FULL DETAILED loaded | "
        "13 sections | metadata + dead_tuples + activity + settings + "
        "cleanup_status + maintenance_preview"
    )
except Exception:
    pass