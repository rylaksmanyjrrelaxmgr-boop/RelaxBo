#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_diagnostics.py — واجهة تشخيص قاعدة البيانات (v2.1.0 — DETAILED)
================================================================================
الأسماء المتوقعة من handlers_command.py:
  - diagnose_db()             : تقرير كامل (HTML string)
  - diagnose_db_split()       : تقرير مقسّم (List[str]) — أجزاء مفصّلة
  - vacuum_analyze_tables()   : VACUUM ANALYZE (HTML string)

v2.1.0:
  🆕 إضافة الفهارس (Indexes) لكل جدول
  🆕 إضافة تفاصيل Vacuum/Analyze لكل جدول
  🆕 إضافة n_mod_since_analyze
  🆕 إضافة حالة نظام رصد idle-tx (idle_tx_status)
  🆕 إضافة إعدادات Autovacuum الكاملة
  🆕 أقسام مفصّلة أكثر (10 أجزاء في split)
================================================================================
"""

import logging
import html as _html
import asyncio
from typing import Dict, List, Any, Optional

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


# ═══════════════════════════════════════════════════════════════════════
# أدوات مساعدة
# ═══════════════════════════════════════════════════════════════════════

def _safe_escape(text: Any) -> str:
    try:
        return _html.escape(str(text)) if text is not None else ""
    except Exception:
        return ""


def _format_number(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


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


def _format_ts(ts: Any) -> str:
    """تنسيق timestamp قصير."""
    if not ts:
        return "—"
    try:
        s = str(ts)
        # ISO format: 2026-10-09 12:34:56+00:00 → 10-09 12:34
        if len(s) >= 16:
            return s[5:16].replace("-", "/")
        return s[:16]
    except Exception:
        return "—"


# ═══════════════════════════════════════════════════════════════════════
# 1) البيانات الخام
# ═══════════════════════════════════════════════════════════════════════

async def get_diagnostics_data(top_n: int = 15) -> Dict[str, Any]:
    """جلب بيانات التشخيص من DB.get_db_diagnostics()."""
    result: Dict[str, Any] = {
        "available": False,
        "db_type": _get_db_type(),
        "dead_tuples": [],
        "table_sizes": [],
        "indexes": {},
        "autovacuum": {},
        "idle_tx": {},
        "idle_tx_status": {},
        "recommendations": [],
        "summary": {},
        "errors": [],
    }

    db = _get_db()
    if db is None:
        result["errors"].append(
            f"DB غير مستورد: {_DB_IMPORT_ERROR or 'غير معروف'}"
        )
        return result

    fn = getattr(db, "get_db_diagnostics", None)
    if callable(fn):
        try:
            data = await fn(top_n=top_n)
            if isinstance(data, dict):
                result.update(data)
                result["available"] = True
                return result
        except Exception as e:
            logger.warning(f"get_db_diagnostics failed: {e}")
            result["errors"].append(f"get_db_diagnostics: {e}")

    # Fallback — جمع يدوي
    for name, key in [
        ("get_dead_tuples", "dead_tuples"),
        ("get_table_sizes", "table_sizes"),
    ]:
        fn2 = getattr(db, name, None)
        if callable(fn2):
            try:
                result[key] = await fn2(top_n) or []
            except Exception as e:
                result["errors"].append(f"{name}: {e}")

    for name, key in [
        ("get_autovacuum_settings", "autovacuum"),
        ("get_idle_tx_info", "idle_tx"),
        ("get_idle_tx_status_info", "idle_tx_status"),
    ]:
        fn2 = getattr(db, name, None)
        if callable(fn2):
            try:
                result[key] = await fn2() or {}
            except Exception as e:
                result["errors"].append(f"{name}: {e}")

    # Indexes
    ii = getattr(db, "get_indexes_info", None)
    if callable(ii):
        try:
            tables = [t.get("name") for t in result["table_sizes"][:8]
                      if isinstance(t, dict) and t.get("name")]
            result["indexes"] = await ii(tables) if tables else {}
        except Exception as e:
            result["errors"].append(f"get_indexes_info: {e}")

    # Recommendations
    mr = getattr(db, "get_maintenance_recommendations", None)
    if callable(mr):
        try:
            result["recommendations"] = await mr(
                dead_tables=result["dead_tuples"],
                table_sizes=result["table_sizes"],
                idle_tx_info=result["idle_tx"],
            ) or []
        except Exception as e:
            result["errors"].append(f"get_maintenance_recommendations: {e}")

    # Summary
    try:
        dead_total = sum(
            t.get("dead", 0) for t in result["dead_tuples"]
            if isinstance(t, dict)
        )
        live_total = sum(
            t.get("live", 0) for t in result["dead_tuples"]
            if isinstance(t, dict)
        )
        worst_ratio = 0.0
        worst_table = None
        for t in result["dead_tuples"]:
            if not isinstance(t, dict):
                continue
            r = t.get("dead_ratio", 0)
            if r > worst_ratio:
                worst_ratio = r
                worst_table = t.get("name")

        overall_color = "🟢"
        if live_total > 0:
            g = dead_total / (live_total + dead_total)
            if g >= 0.20:
                overall_color = "🔴"
            elif g >= 0.10:
                overall_color = "🟠"
            elif g >= 0.05:
                overall_color = "🟡"

        idle_count = 0
        idle_color = "🟢"
        if (isinstance(result["idle_tx"], dict)
                and result["idle_tx"].get("available")):
            idle_count = int(result["idle_tx"].get("count") or 0)
            if idle_count >= 3:
                idle_color = "🔴"
            elif idle_count >= 1:
                idle_color = "🟠"

        result["summary"] = {
            "dead_total": dead_total,
            "live_total": live_total,
            "worst_table": worst_table,
            "worst_ratio": round(worst_ratio * 100, 1),
            "overall_color": overall_color,
            "tables_count": len(result["dead_tuples"]),
            "idle_tx_count": idle_count,
            "idle_tx_color": idle_color,
        }
        result["available"] = True
    except Exception as e:
        result["errors"].append(f"summary: {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════
# 2) بناء الأجزاء — الدالة المركزية
# ═══════════════════════════════════════════════════════════════════════

def _build_sections(data: Dict[str, Any], top_n: int = 15) -> List[str]:
    """يبني كل الأجزاء ويُعيد قائمة HTML strings."""
    parts: List[str] = []

    # ═══════════════════════════════════════════════
    # الجزء 1: Header + Summary
    # ═══════════════════════════════════════════════
    h: List[str] = []
    h.append("🔬 <b>تشخيص قاعدة البيانات</b>")
    h.append("━━━━━━━━━━━━━━━━━━━━━━")
    h.append("")
    h.append(f"🗄️ <b>النوع:</b> <code>{_safe_escape(data.get('db_type'))}</code>")
    h.append(f"🕐 <b>الوقت:</b> {_now_iso()}")

    available = data.get("available", False)
    h.append(f"{'✅' if available else '⚠️'} <b>الحالة:</b> "
             f"{'كامل' if available else 'fallback'}")
    h.append("")

    summary = data.get("summary", {}) or {}
    if summary:
        color = summary.get("overall_color", "🟢")
        h.append(f"<b>{color} الحالة العامة</b>")
        h.append(f"  📊 Dead: <b>{_format_number(summary.get('dead_total', 0))}</b>"
                 f"  |  Live: <b>{_format_number(summary.get('live_total', 0))}</b>")
        if summary.get("worst_table"):
            h.append(f"  ⚠️ أسوأ جدول: <code>{_safe_escape(summary['worst_table'])}</code>"
                     f" ({summary.get('worst_ratio', 0)}%)")
        h.append(f"  🔌 idle-tx: {summary.get('idle_tx_color', '🟢')} "
                 f"<b>{summary.get('idle_tx_count', 0)}</b>")
    parts.append("\n".join(h))

    # ═══════════════════════════════════════════════
    # الجزء 2: Dead Tuples — مفصّل
    # ═══════════════════════════════════════════════
    dead_tuples = data.get("dead_tuples", [])
    if dead_tuples:
        dt: List[str] = []
        dt.append(f"🗑️ <b>Dead Tuples ({len(dead_tuples)} جدول)</b>")
        dt.append("━━━━━━━━━━━━━━━━━━━━━━")
        for t in dead_tuples[:top_n]:
            if not isinstance(t, dict):
                continue
            name = _safe_escape(t.get("name", "?"))
            dead = t.get("dead", 0)
            live = t.get("live", 0)
            ratio = t.get("dead_ratio", 0) * 100
            color = t.get("color", "🟢")
            advice = t.get("advice", "")
            n_mod = t.get("n_mod_since_analyze", 0)

            dt.append(f"{color} <b>{name}</b>")
            dt.append(f"   📊 Dead: <b>{_format_number(dead)}</b> "
                      f"| Live: {_format_number(live)} "
                      f"| ({ratio:.1f}%)")

            # آخر vacuum/analyze
            last_vac = t.get("last_vacuum") or t.get("last_autovacuum")
            last_an = t.get("last_analyze") or t.get("last_autoanalyze")
            if last_vac or last_an:
                dt.append(f"   🧹 Vacuum: {_format_ts(last_vac)} "
                          f"| Analyze: {_format_ts(last_an)}")
            if n_mod:
                dt.append(f"   ✏️ تعديلات منذ آخر Analyze: <b>{_format_number(n_mod)}</b>")

            if advice:
                dt.append(f"   💡 <i>{_safe_escape(advice)}</i>")
            dt.append("")
        parts.append("\n".join(dt))

    # ═══════════════════════════════════════════════
    # الجزء 3: أحجام الجداول
    # ═══════════════════════════════════════════════
    table_sizes = data.get("table_sizes", [])
    if table_sizes:
        ts: List[str] = []
        ts.append("📦 <b>أحجام الجداول</b>")
        ts.append("━━━━━━━━━━━━━━━━━━━━━━")
        max_size = max(
            (t.get("total_bytes", 0) for t in table_sizes
             if isinstance(t, dict)),
            default=1
        ) or 1
        for t in table_sizes[:top_n]:
            if not isinstance(t, dict):
                continue
            name = _safe_escape(t.get("name", "?"))
            display = t.get("total_display", "0 B")
            table_b = t.get("table_bytes", 0)
            index_b = t.get("index_bytes", 0)
            color = t.get("size_color", "🟢")
            bar = _bar(t.get("total_bytes", 0), max_size, width=8)

            ts.append(f"{color} <b>{name}</b>")
            ts.append(f"   {bar} <b>{display}</b>")
            if table_b and index_b:
                # تحويل لصيغة مقروءة
                def _fmt_b(b):
                    try:
                        b = float(b)
                        if b < 1024:
                            return f"{int(b)}B"
                        if b < 1024*1024:
                            return f"{b/1024:.1f}KB"
                        if b < 1024*1024*1024:
                            return f"{b/(1024*1024):.2f}MB"
                        return f"{b/(1024*1024*1024):.2f}GB"
                    except Exception:
                        return "?"
                ts.append(f"   📄 بيانات: {_fmt_b(table_b)} "
                          f"| 🗂️ فهارس: {_fmt_b(index_b)}")
            ts.append("")
        parts.append("\n".join(ts))

    # ═══════════════════════════════════════════════
    # الجزء 4: الفهارس — 🆕
    # ═══════════════════════════════════════════════
    indexes = data.get("indexes", {}) or {}
    if indexes:
        ix: List[str] = []
        ix.append("🗂️ <b>الفهارس (Indexes)</b>")
        ix.append("━━━━━━━━━━━━━━━━━━━━━━")
        total_idx = sum(len(v) for v in indexes.values() if v)
        ix.append(f"📊 إجمالي: <b>{total_idx}</b> فهرس "
                  f"على <b>{len(indexes)}</b> جدول")
        ix.append("")

        for tname, idx_list in indexes.items():
            if not idx_list:
                continue
            tname_esc = _safe_escape(tname)
            ix.append(f"📋 <b>{tname_esc}</b> ({len(idx_list)})")
            for idx in idx_list[:6]:
                if not isinstance(idx, dict):
                    continue
                iname = _safe_escape(idx.get("index_name", "?"))
                is_unique = "🔒" if idx.get("is_unique") else "  "
                is_primary = "🔑" if idx.get("is_primary") else "  "
                size = idx.get("size_display", "0 B")
                ix.append(f"   {is_primary}{is_unique} <code>{iname}</code> "
                          f"— {size}")
            if len(idx_list) > 6:
                ix.append(f"   <i>... و{len(idx_list) - 6} آخرين</i>")
            ix.append("")
        parts.append("\n".join(ix))

    # ═══════════════════════════════════════════════
    # الجزء 5: idle-in-transaction
    # ═══════════════════════════════════════════════
    idle_tx = data.get("idle_tx", {}) or {}
    if isinstance(idle_tx, dict) and idle_tx.get("available"):
        count = int(idle_tx.get("count") or 0)
        if count > 0:
            itx: List[str] = []
            color = "🔴" if count >= 3 else "🟠"
            itx.append(f"{color} <b>idle-in-transaction</b>")
            itx.append("━━━━━━━━━━━━━━━━━━━━━━")
            itx.append(f"عدد الاتصالات: <b>{count}</b>")
            itx.append(f"من تطبيقنا: <b>{idle_tx.get('app_matches', 0)}</b>")
            itx.append(f"إجمالي idle-tx: <b>{idle_tx.get('total_idle_tx', 0)}</b>")
            itx.append("")

            by_app = idle_tx.get("by_app", {}) or {}
            if by_app:
                itx.append("👥 <b>حسب التطبيق:</b>")
                for app, cnt in sorted(by_app.items(),
                                        key=lambda x: -x[1])[:5]:
                    itx.append(f"   • <code>{_safe_escape(app)}</code>: {cnt}")
                itx.append("")

            items = idle_tx.get("items") or []
            if items:
                itx.append("🔍 <b>أقدم الاتصالات:</b>")
                for it in items[:5]:
                    if not isinstance(it, dict):
                        continue
                    pid = it.get("pid")
                    app = _safe_escape(it.get("app", "?"))
                    idle_s = it.get("idle_sec", 0)
                    tx_age = it.get("tx_age_sec", 0)
                    itx.append(f"   • pid=<code>{pid}</code> "
                               f"app=<b>{app}</b>")
                    itx.append(f"     idle: {idle_s}s | tx_age: {tx_age}s")
            parts.append("\n".join(itx))

    # ═══════════════════════════════════════════════
    # الجزء 6: حالة نظام رصد idle-tx — 🆕
    # ═══════════════════════════════════════════════
    idle_status = data.get("idle_tx_status", {}) or {}
    if isinstance(idle_status, dict) and idle_status.get("available"):
        ist: List[str] = []
        ist.append("📡 <b>نظام رصد idle-tx الدوري</b>")
        ist.append("━━━━━━━━━━━━━━━━━━━━━━")

        enabled = idle_status.get("enabled", False)
        running = idle_status.get("running", False)

        ist.append(f"{'✅' if enabled else '❌'} مُفعّل: "
                   f"<b>{'نعم' if enabled else 'لا'}</b>")
        ist.append(f"{'🟢' if running else '🔴'} يعمل الآن: "
                   f"<b>{'نعم' if running else 'لا'}</b>")
        ist.append(f"⏱️ الفترة: <b>{idle_status.get('interval_sec', 0)}s</b>")
        ist.append(f"🎯 الحد: <b>{idle_status.get('alert_threshold', 1)}</b>")

        if idle_status.get("app_filter"):
            ist.append(f"🔍 فلتر: <code>{_safe_escape(idle_status['app_filter'])}</code>")

        ist.append("")
        ist.append(f"📊 دورات الفحص: <b>{idle_status.get('iterations', 0)}</b>")
        ist.append(f"🚨 تنبيهات: <b>{idle_status.get('alert_count', 0)}</b>")
        ist.append(f"📍 آخر قراءة: <b>{idle_status.get('last_count', 0)}</b>")
        ist.append(f"⏱️ مُشتغل منذ: <b>{idle_status.get('uptime_sec', 0)}s</b>")

        parts.append("\n".join(ist))

    # ═══════════════════════════════════════════════
    # الجزء 7: Autovacuum — 🆕 (كل الحقول)
    # ═══════════════════════════════════════════════
    av = data.get("autovacuum", {}) or {}
    if av:
        avg: List[str] = []
        avg.append("⚙️ <b>إعدادات Autovacuum</b>")
        avg.append("━━━━━━━━━━━━━━━━━━━━━━")
        for k, v in av.items():
            k_esc = _safe_escape(k)
            v_esc = _safe_escape(v)
            avg.append(f"  • <code>{k_esc}</code>: {v_esc}")
        parts.append("\n".join(avg))

    # ═══════════════════════════════════════════════
    # الجزء 8: توصيات الصيانة
    # ═══════════════════════════════════════════════
    recommendations = data.get("recommendations", [])
    if recommendations:
        rc: List[str] = []
        rc.append("🧹 <b>توصيات الصيانة</b>")
        rc.append("━━━━━━━━━━━━━━━━━━━━━━")
        for r in recommendations[:10]:
            rc.append(f"  • {r}")
        parts.append("\n".join(rc))

    # ═══════════════════════════════════════════════
    # الجزء 9: Errors (إن وجدت)
    # ═══════════════════════════════════════════════
    errors = data.get("errors", [])
    if errors:
        er: List[str] = []
        er.append("⚠️ <b>أخطاء أثناء التشخيص</b>")
        er.append("━━━━━━━━━━━━━━━━━━━━━━")
        for e in errors[:8]:
            er.append(f"  • <code>{_safe_escape(e)[:120]}</code>")
        parts.append("\n".join(er))

    # ═══════════════════════════════════════════════
    # الجزء 10: Footer
    # ═══════════════════════════════════════════════
    parts.append(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>🕐 {_now_iso()}</i>\n"
        "<i>💡 /db_vacuum لتنظيف الجداول</i>"
    )

    return parts


# ═══════════════════════════════════════════════════════════════════════
# 3) الدوال الرئيسية
# ═══════════════════════════════════════════════════════════════════════

async def diagnose_db() -> str:
    """✅ /db_diag — التقرير الكامل (HTML string)."""
    data = await get_diagnostics_data(top_n=15)
    parts = _build_sections(data, top_n=15)
    return "\n\n".join(parts)


async def diagnose_db_split() -> List[str]:
    """✅ /db_diag — التقرير مقسّم لأجزاء (List[str])."""
    data = await get_diagnostics_data(top_n=15)
    return _build_sections(data, top_n=15)


async def vacuum_analyze_tables() -> str:
    """✅ /db_vacuum — VACUUM ANALYZE لكل الجداول."""
    db = _get_db()
    if db is None:
        return "❌ <b>DB غير مستورد</b>"

    lines: List[str] = []
    lines.append("🧹 <b>VACUUM ANALYZE</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    tables = [
        "posts", "subscriptions", "user_penalties", "users",
        "user_channels", "admin_logs", "banned_words",
        "auto_replies", "user_warnings", "user_violations",
        "bot_groups", "schedule", "last_publish",
    ]

    success_count = 0
    fail_count = 0
    skip_count = 0

    for table in tables:
        try:
            vacuum_fn = getattr(db, "vacuum", None)
            if callable(vacuum_fn):
                await vacuum_fn(table)
                success_count += 1
                lines.append(f"  ✅ <code>{_safe_escape(table)}</code>")
            else:
                await db.execute(f"VACUUM (ANALYZE) {table}")
                success_count += 1
                lines.append(f"  ✅ <code>{_safe_escape(table)}</code>")
        except Exception as e:
            err_lower = str(e).lower()
            if ("does not exist" in err_lower
                    or "no such table" in err_lower):
                skip_count += 1
                lines.append(
                    f"  ⏭️ <code>{_safe_escape(table)}</code> "
                    f"<i>(غير موجود)</i>"
                )
            else:
                fail_count += 1
                lines.append(
                    f"  ❌ <code>{_safe_escape(table)}</code> — "
                    f"<code>{_safe_escape(str(e)[:80])}</code>"
                )
        try:
            await asyncio.sleep(0.1)
        except Exception:
            pass

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        f"✅ نجح: <b>{success_count}</b>  |  "
        f"⏭️ تخطي: <b>{skip_count}</b>  |  "
        f"❌ فشل: <b>{fail_count}</b>"
    )
    lines.append("")
    lines.append(f"🕐 <i>{_now_iso()}</i>")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 4) Aliases
# ═══════════════════════════════════════════════════════════════════════

async def get_diagnostics_report(top_n: int = 15, as_html: bool = True) -> str:
    return await diagnose_db()


async def get_quick_health() -> Dict[str, Any]:
    health = {
        "ok": True,
        "color": "🟢",
        "message": "قاعدة البيانات تعمل بشكل طبيعي",
        "db_type": _get_db_type(),
        "pool": {},
    }
    db = _get_db()
    if db is None:
        health["ok"] = False
        health["color"] = "🔴"
        health["message"] = f"DB غير مستورد: {_DB_IMPORT_ERROR}"
        return health

    try:
        pool_fn = getattr(db, "get_pool_stats", None)
        if callable(pool_fn):
            pool = await pool_fn()
            health["pool"] = pool or {}
            util = (pool.get("utilization_pct", 0)
                    if isinstance(pool, dict) else 0)
            if util >= 85:
                health["color"] = "🔴"
                health["message"] = f"استخدام Pool مرتفع ({util}%)"
                health["ok"] = False
            elif util >= 70:
                health["color"] = "🟡"
                health["message"] = f"استخدام Pool متوسط ({util}%)"
    except Exception as e:
        logger.debug(f"get_quick_health pool: {e}")

    try:
        await db.fetchval("SELECT 1", default=1)
    except Exception as e:
        health["ok"] = False
        health["color"] = "🔴"
        health["message"] = f"فشل الاتصال: {str(e)[:80]}"
    return health


async def get_diagnostics_one_liner() -> str:
    try:
        health = await get_quick_health()
        color = health.get("color", "🟢")
        db_type = health.get("db_type", "UNKNOWN")
        pool = health.get("pool", {}) or {}
        util = pool.get("utilization_pct", 0)
        return f"{color} DB={db_type} Pool={util}%"
    except Exception as e:
        return f"🔴 DB=ERROR ({str(e)[:30]})"


async def send_diagnostics_to_chat(bot, chat_id: int, top_n: int = 15) -> bool:
    try:
        from utils import safe_send
        report = await diagnose_db()
        await safe_send(
            bot, chat_id, report,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        logger.error(f"send_diagnostics_to_chat: {e}", exc_info=True)
        return False


__all__ = [
    "diagnose_db",
    "diagnose_db_split",
    "vacuum_analyze_tables",
    "get_diagnostics_data",
    "get_diagnostics_report",
    "get_quick_health",
    "get_diagnostics_one_liner",
    "send_diagnostics_to_chat",
]


try:
    logger.info(
        "🛡️ db_diagnostics.py v2.1.0 DETAILED loaded | "
        "10 sections | indexes + idle_tx_status + full autovacuum"
    )
except Exception:
    pass