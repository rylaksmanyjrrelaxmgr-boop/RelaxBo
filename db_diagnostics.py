#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_diagnostics.py — واجهة تشخيص قاعدة البيانات (v2.0.0)
================================================================================
الأسماء المتوقعة من handlers_command.py:
  - diagnose_db()             : تقرير كامل (HTML string)
  - diagnose_db_split()       : تقرير مقسّم (List[str])
  - vacuum_analyze_tables()   : VACUUM ANALYZE (HTML string)

+ Aliases (للتوافق):
  - get_diagnostics_data()    : بيانات خام
  - get_diagnostics_report()  : تقرير
  - get_quick_health()        : فحص سريع
  - get_diagnostics_one_liner()
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
    """Lazy import لـ DB — يعيد None إذا فشل."""
    global _DB_IMPORT_ERROR
    try:
        from database import DB
        return DB
    except Exception as e:
        if _DB_IMPORT_ERROR is None:
            _DB_IMPORT_ERROR = f"{type(e).__name__}: {e}"
            logger.error(
                f"❌ db_diagnostics: فشل استيراد DB: {_DB_IMPORT_ERROR}"
            )
        return None


def _now_iso() -> str:
    """وقت ISO مع fallback."""
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


# ═══════════════════════════════════════════════════════════════════════
# 1) البيانات الخام
# ═══════════════════════════════════════════════════════════════════════

async def get_diagnostics_data(top_n: int = 10) -> Dict[str, Any]:
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

    # محاولة get_db_diagnostics
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

    # Fallback
    dts = getattr(db, "get_dead_tuples", None)
    if callable(dts):
        try:
            result["dead_tuples"] = await dts(top_n) or []
        except Exception as e:
            result["errors"].append(f"get_dead_tuples: {e}")

    ts = getattr(db, "get_table_sizes", None)
    if callable(ts):
        try:
            result["table_sizes"] = await ts(top_n) or []
        except Exception as e:
            result["errors"].append(f"get_table_sizes: {e}")

    ii = getattr(db, "get_indexes_info", None)
    if callable(ii):
        try:
            tables = [t.get("name") for t in result["table_sizes"][:8]
                      if isinstance(t, dict) and t.get("name")]
            result["indexes"] = await ii(tables) if tables else {}
        except Exception as e:
            result["errors"].append(f"get_indexes_info: {e}")

    av = getattr(db, "get_autovacuum_settings", None)
    if callable(av):
        try:
            result["autovacuum"] = await av() or {}
        except Exception as e:
            result["errors"].append(f"get_autovacuum_settings: {e}")

    itx = getattr(db, "get_idle_tx_info", None)
    if callable(itx):
        try:
            result["idle_tx"] = await itx() or {}
        except Exception as e:
            result["errors"].append(f"get_idle_tx_info: {e}")

    its = getattr(db, "get_idle_tx_status_info", None)
    if callable(its):
        try:
            result["idle_tx_status"] = await its() or {}
        except Exception as e:
            result["errors"].append(f"get_idle_tx_status_info: {e}")

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
# 2) التنسيق — HTML
# ═══════════════════════════════════════════════════════════════════════

def _format_html_from_data(
    data: Dict[str, Any],
    top_n: int = 10,
) -> str:
    """تنسيق HTML من البيانات."""
    lines: List[str] = []

    lines.append("🔬 <b>تشخيص قاعدة البيانات</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    db_type = data.get("db_type", _get_db_type())
    available = data.get("available", False)
    avail_icon = "✅" if available else "⚠️"
    lines.append(f"🗄️ <b>النوع:</b> <code>{_safe_escape(db_type)}</code>")
    lines.append(f"{avail_icon} <b>التشخيص:</b> "
                 f"{'متاح' if available else 'fallback'}")
    lines.append(f"🕐 <b>الوقت:</b> {_now_iso()}")
    lines.append("")

    # Summary
    summary = data.get("summary", {}) or {}
    if summary:
        color = summary.get("overall_color", "🟢")
        dead_total = summary.get("dead_total", 0)
        live_total = summary.get("live_total", 0)
        worst = summary.get("worst_table")
        worst_ratio = summary.get("worst_ratio", 0)
        idle_count = summary.get("idle_tx_count", 0)
        idle_color = summary.get("idle_tx_color", "🟢")

        lines.append(f"<b>{color} الحالة العامة</b>")
        lines.append(f"  • Dead tuples: <b>{_format_number(dead_total)}</b>")
        lines.append(f"  • Live tuples: <b>{_format_number(live_total)}</b>")
        if worst:
            lines.append(f"  • أسوأ جدول: <code>{_safe_escape(worst)}</code> "
                         f"({worst_ratio}%)")
        lines.append(f"  • idle-tx: {idle_color} <b>{idle_count}</b>")
        lines.append("")

    # Dead tuples
    dead_tuples = data.get("dead_tuples", [])
    if dead_tuples:
        lines.append("🗑️ <b>أكبر Dead Tuples</b>")
        for t in dead_tuples[:top_n]:
            if not isinstance(t, dict):
                continue
            name = _safe_escape(t.get("name", "?"))
            dead = t.get("dead", 0)
            ratio = t.get("dead_ratio", 0) * 100
            color = t.get("color", "🟢")
            advice = t.get("advice", "")
            lines.append(f"  {color} <code>{name}</code> — "
                         f"<b>{_format_number(dead)}</b> ({ratio:.1f}%)")
            if advice:
                lines.append(f"     💡 <i>{_safe_escape(advice)}</i>")
        lines.append("")

    # Table sizes
    table_sizes = data.get("table_sizes", [])
    if table_sizes:
        lines.append("📦 <b>أكبر الجداول</b>")
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
            color = t.get("size_color", "🟢")
            bar = _bar(t.get("total_bytes", 0), max_size, width=8)
            lines.append(f"  {color} <code>{name}</code>\n"
                         f"     {bar} <b>{display}</b>")
        lines.append("")

    # idle-tx
    idle_tx = data.get("idle_tx", {}) or {}
    if isinstance(idle_tx, dict) and idle_tx.get("available"):
        count = int(idle_tx.get("count") or 0)
        if count > 0:
            color = "🔴" if count >= 3 else "🟠"
            lines.append(f"{color} <b>idle-in-transaction</b>")
            lines.append(f"  عدد الاتصالات: <b>{count}</b>")
            items = idle_tx.get("items") or []
            for it in items[:5]:
                if not isinstance(it, dict):
                    continue
                pid = it.get("pid")
                app = _safe_escape(it.get("app", "?"))
                idle_s = it.get("idle_sec", 0)
                lines.append(f"  • pid=<code>{pid}</code> "
                             f"app=<b>{app}</b> idle={idle_s}s")
            lines.append("")

    # Autovacuum
    autovacuum = data.get("autovacuum", {}) or {}
    if autovacuum:
        lines.append("⚙️ <b>Autovacuum</b>")
        for k in ("autovacuum", "autovacuum_naptime",
                  "autovacuum_max_workers"):
            if k in autovacuum:
                lines.append(f"  • {k}: <code>{_safe_escape(autovacuum[k])}</code>")
        lines.append("")

    # Recommendations
    recommendations = data.get("recommendations", [])
    if recommendations:
        lines.append("🧹 <b>توصيات الصيانة</b>")
        for r in recommendations[:8]:
            lines.append(f"  • {r}")
        lines.append("")

    # Errors
    errors = data.get("errors", [])
    if errors:
        lines.append("⚠️ <b>أخطاء أثناء التشخيص</b>")
        for e in errors[:5]:
            lines.append(f"  • <code>{_safe_escape(e)[:100]}</code>")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("<i>💡 للتحديث: اضغط 🔄</i>")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 3) الدوال الرئيسية — الأسماء المتوقعة من handlers_command
# ═══════════════════════════════════════════════════════════════════════

async def diagnose_db() -> str:
    """
    ✅ /db_diag — التقرير الكامل (HTML string).

    الأسماء المتوقعة من handlers_command.py.
    """
    data = await get_diagnostics_data(top_n=10)
    return _format_html_from_data(data, top_n=10)


async def diagnose_db_split() -> List[str]:
    """
    ✅ /db_diag — التقرير مقسّم لأجزاء (List[str]).

    يُستخدم أولاً من handlers_command، قبل diagnose_db.
    كل جزء يحتوي HTML صالح.
    """
    data = await get_diagnostics_data(top_n=10)

    parts: List[str] = []

    # الجزء 1: المعلومات العامة + Summary
    header_lines: List[str] = []
    header_lines.append("🔬 <b>تشخيص قاعدة البيانات</b>")
    header_lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    header_lines.append("")
    header_lines.append(f"🗄️ <b>النوع:</b> <code>{_safe_escape(data.get('db_type'))}</code>")
    header_lines.append(f"🕐 <b>الوقت:</b> {_now_iso()}")
    header_lines.append("")

    summary = data.get("summary", {}) or {}
    if summary:
        color = summary.get("overall_color", "🟢")
        header_lines.append(f"<b>{color} الحالة العامة</b>")
        header_lines.append(
            f"  • Dead tuples: <b>{_format_number(summary.get('dead_total', 0))}</b>"
        )
        header_lines.append(
            f"  • Live tuples: <b>{_format_number(summary.get('live_total', 0))}</b>"
        )
        worst = summary.get("worst_table")
        if worst:
            header_lines.append(
                f"  • أسوأ جدول: <code>{_safe_escape(worst)}</code> "
                f"({summary.get('worst_ratio', 0)}%)"
            )
        header_lines.append(
            f"  • idle-tx: {summary.get('idle_tx_color', '🟢')} "
            f"<b>{summary.get('idle_tx_count', 0)}</b>"
        )

    parts.append("\n".join(header_lines))

    # الجزء 2: Dead tuples
    dead_tuples = data.get("dead_tuples", [])
    if dead_tuples:
        dt_lines = ["🗑️ <b>أكبر Dead Tuples</b>", ""]
        for t in dead_tuples[:10]:
            if not isinstance(t, dict):
                continue
            name = _safe_escape(t.get("name", "?"))
            dead = t.get("dead", 0)
            ratio = t.get("dead_ratio", 0) * 100
            color = t.get("color", "🟢")
            advice = t.get("advice", "")
            dt_lines.append(
                f"  {color} <code>{name}</code> — "
                f"<b>{_format_number(dead)}</b> ({ratio:.1f}%)"
            )
            if advice:
                dt_lines.append(f"     💡 <i>{_safe_escape(advice)}</i>")
        parts.append("\n".join(dt_lines))

    # الجزء 3: Table sizes
    table_sizes = data.get("table_sizes", [])
    if table_sizes:
        ts_lines = ["📦 <b>أكبر الجداول</b>", ""]
        max_size = max(
            (t.get("total_bytes", 0) for t in table_sizes
             if isinstance(t, dict)),
            default=1
        ) or 1
        for t in table_sizes[:10]:
            if not isinstance(t, dict):
                continue
            name = _safe_escape(t.get("name", "?"))
            display = t.get("total_display", "0 B")
            color = t.get("size_color", "🟢")
            bar = _bar(t.get("total_bytes", 0), max_size, width=8)
            ts_lines.append(f"  {color} <code>{name}</code>")
            ts_lines.append(f"     {bar} <b>{display}</b>")
        parts.append("\n".join(ts_lines))

    # الجزء 4: idle-tx
    idle_tx = data.get("idle_tx", {}) or {}
    if isinstance(idle_tx, dict) and idle_tx.get("available"):
        count = int(idle_tx.get("count") or 0)
        if count > 0:
            itx_lines = ["🔴 <b>idle-in-transaction</b>", ""]
            itx_lines.append(f"عدد الاتصالات: <b>{count}</b>")
            items = idle_tx.get("items") or []
            for it in items[:5]:
                if not isinstance(it, dict):
                    continue
                pid = it.get("pid")
                app = _safe_escape(it.get("app", "?"))
                idle_s = it.get("idle_sec", 0)
                itx_lines.append(
                    f"  • pid=<code>{pid}</code> "
                    f"app=<b>{app}</b> idle={idle_s}s"
                )
            parts.append("\n".join(itx_lines))

    # الجزء 5: Recommendations
    recommendations = data.get("recommendations", [])
    if recommendations:
        rec_lines = ["🧹 <b>توصيات الصيانة</b>", ""]
        for r in recommendations[:8]:
            rec_lines.append(f"  • {r}")
        parts.append("\n".join(rec_lines))

    # الجزء 6: Errors (إن وجدت)
    errors = data.get("errors", [])
    if errors:
        err_lines = ["⚠️ <b>أخطاء أثناء التشخيص</b>", ""]
        for e in errors[:5]:
            err_lines.append(f"  • <code>{_safe_escape(e)[:100]}</code>")
        parts.append("\n".join(err_lines))

    if not parts:
        parts.append("⚠️ لا توجد بيانات")

    return parts


async def vacuum_analyze_tables() -> str:
    """
    ✅ /db_vacuum — VACUUM ANALYZE لكل الجداول المهمة.

    يعيد HTML string بنتيجة العملية.
    """
    db = _get_db()
    if db is None:
        return "❌ <b>DB غير مستورد</b>"

    lines: List[str] = []
    lines.append("🧹 <b>VACUUM ANALYZE</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    # قائمة الجداول المهمة
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
            # استخدم vacuum() من DB إن وجدت
            vacuum_fn = getattr(db, "vacuum", None)
            if callable(vacuum_fn):
                await vacuum_fn(table)
                success_count += 1
                lines.append(f"  ✅ <code>{_safe_escape(table)}</code>")
            else:
                # Fallback: VACUUM مباشر
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
        # استراحة صغيرة بين الجداول
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
# 4) Aliases + Helpers
# ═══════════════════════════════════════════════════════════════════════

async def get_diagnostics_report(
    top_n: int = 10,
    as_html: bool = True,
) -> str:
    """تقرير كامل — alias لـ diagnose_db."""
    return await diagnose_db()


async def get_quick_health() -> Dict[str, Any]:
    """فحص سريع للحالة العامة."""
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
    """سطر واحد مختصر."""
    try:
        health = await get_quick_health()
        color = health.get("color", "🟢")
        db_type = health.get("db_type", "UNKNOWN")
        pool = health.get("pool", {}) or {}
        util = pool.get("utilization_pct", 0)
        return f"{color} DB={db_type} Pool={util}%"
    except Exception as e:
        return f"🔴 DB=ERROR ({str(e)[:30]})"


async def send_diagnostics_to_chat(bot, chat_id: int, top_n: int = 10) -> bool:
    """إرسال التقرير عبر Telegram."""
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


# ═══════════════════════════════════════════════════════════════════════
# __all__
# ═══════════════════════════════════════════════════════════════════════

__all__ = [
    # الأسماء الرئيسية (متوقعة من handlers_command)
    "diagnose_db",
    "diagnose_db_split",
    "vacuum_analyze_tables",
    # Aliases
    "get_diagnostics_data",
    "get_diagnostics_report",
    "get_quick_health",
    "get_diagnostics_one_liner",
    "send_diagnostics_to_chat",
]


# ═══════════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═══════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "🛡️ db_diagnostics.py v2.0.0 loaded | "
        "diagnose_db + diagnose_db_split + vacuum_analyze_tables"
    )
except Exception:
    pass