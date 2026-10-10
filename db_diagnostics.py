#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_diagnostics.py — واجهة تشخيص قاعدة البيانات (v1.1.0)
================================================================================
يستخدم AnalyticsMixin من database_analytics.py v1.1.0

الميزات:
  - get_diagnostics_data()        : البيانات الخام (dict)
  - get_diagnostics_report()      : تقرير جاهز (HTML/نص)
  - get_quick_health()            : فحص سريع للحالة العامة
  - format_diagnostics_html()     : تنسيق HTML
  - format_diagnostics_plain()    : تنسيق نصي
  - send_diagnostics_to_chat()    : إرسال التقرير عبر Telegram
  - get_diagnostics_one_liner()   : سطر واحد مختصر

v1.1.0:
    🔴 Lazy imports — لا يستورد DB/TimeUtils عند التحميل.
    🔴 التقاط كل أخطاء الاستيراد + رسالة واضحة.
    🟡 Fallback في كل دالة إذا لم تتوفر.
================================================================================
"""

import logging
import html as _html
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Lazy imports
# ═══════════════════════════════════════════════════════════════════════

_DB_IMPORT_ERROR: Optional[str] = None
_TIMEUTILS_IMPORT_ERROR: Optional[str] = None


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


def _get_timeutils():
    """Lazy import لـ TimeUtils — يعيد None إذا فشل."""
    global _TIMEUTILS_IMPORT_ERROR
    try:
        from utils import TimeUtils
        return TimeUtils
    except Exception as e:
        if _TIMEUTILS_IMPORT_ERROR is None:
            _TIMEUTILS_IMPORT_ERROR = f"{type(e).__name__}: {e}"
            logger.error(
                f"❌ db_diagnostics: فشل استيراد TimeUtils: "
                f"{_TIMEUTILS_IMPORT_ERROR}"
            )
        return None


def _now_iso() -> str:
    """وقت ISO (Mecca) مع fallback."""
    tu = _get_timeutils()
    if tu is not None:
        try:
            return tu.mecca_iso()[:19]
        except Exception:
            pass
    try:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "?"


def _get_db_type() -> str:
    """DB_TYPE مع fallback."""
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
# 1) الوصول الآمن للبيانات
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
    logger.info("ℹ️ db_diagnostics: استخدام fallback")

    # Dead tuples
    dts = getattr(db, "get_dead_tuples", None)
    if callable(dts):
        try:
            result["dead_tuples"] = await dts(top_n) or []
        except Exception as e:
            result["errors"].append(f"get_dead_tuples: {e}")

    # Table sizes
    ts = getattr(db, "get_table_sizes", None)
    if callable(ts):
        try:
            result["table_sizes"] = await ts(top_n) or []
        except Exception as e:
            result["errors"].append(f"get_table_sizes: {e}")

    # Indexes
    ii = getattr(db, "get_indexes_info", None)
    if callable(ii):
        try:
            tables = [t.get("name") for t in result["table_sizes"][:8]
                      if isinstance(t, dict) and t.get("name")]
            result["indexes"] = await ii(tables) if tables else {}
        except Exception as e:
            result["errors"].append(f"get_indexes_info: {e}")

    # Autovacuum
    av = getattr(db, "get_autovacuum_settings", None)
    if callable(av):
        try:
            result["autovacuum"] = await av() or {}
        except Exception as e:
            result["errors"].append(f"get_autovacuum_settings: {e}")

    # Idle TX
    itx = getattr(db, "get_idle_tx_info", None)
    if callable(itx):
        try:
            result["idle_tx"] = await itx() or {}
        except Exception as e:
            result["errors"].append(f"get_idle_tx_info: {e}")

    # Idle TX Status
    its = getattr(db, "get_idle_tx_status_info", None)
    if callable(its):
        try:
            result["idle_tx_status"] = await its() or {}
        except Exception as e:
            result["errors"].append(f"get_idle_tx_status_info: {e}")

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
# 2) فحص سريع للحالة العامة
# ═══════════════════════════════════════════════════════════════════════

async def get_quick_health() -> Dict[str, Any]:
    """فحص سريع لحالة DB."""
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


# ═══════════════════════════════════════════════════════════════════════
# 3) تنسيق HTML للتقرير الكامل
# ═══════════════════════════════════════════════════════════════════════

async def format_diagnostics_html(
    data: Optional[Dict[str, Any]] = None,
    top_n: int = 10,
) -> str:
    """تنسيق تقرير التشخيص كـ HTML (لـ Telegram)."""
    if data is None:
        data = await get_diagnostics_data(top_n=top_n)

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
# 4) تنسيق نصي بسيط
# ═══════════════════════════════════════════════════════════════════════

async def format_diagnostics_plain(
    data: Optional[Dict[str, Any]] = None,
    top_n: int = 10,
) -> str:
    """تنسيق تقرير التشخيص كنص عادي."""
    if data is None:
        data = await get_diagnostics_data(top_n=top_n)

    lines: List[str] = []
    lines.append("🔬 تشخيص قاعدة البيانات")
    lines.append("=" * 40)
    lines.append("")
    lines.append(f"النوع: {data.get('db_type', _get_db_type())}")
    lines.append(f"الوقت: {_now_iso()}")
    lines.append("")

    summary = data.get("summary", {}) or {}
    if summary:
        lines.append(f"Dead: {_format_number(summary.get('dead_total', 0))}")
        lines.append(f"Live: {_format_number(summary.get('live_total', 0))}")
        lines.append(f"idle-tx: {summary.get('idle_tx_count', 0)}")
        lines.append("")

    if data.get("dead_tuples"):
        lines.append("أكبر Dead Tuples:")
        for t in data["dead_tuples"][:top_n]:
            if not isinstance(t, dict):
                continue
            lines.append(
                f"  - {t.get('name', '?')}: "
                f"{_format_number(t.get('dead', 0))} "
                f"({t.get('dead_ratio', 0) * 100:.1f}%)"
            )
        lines.append("")

    if data.get("recommendations"):
        lines.append("توصيات:")
        for r in data["recommendations"][:8]:
            clean = r
            for tag in ("<b>", "</b>", "<code>", "</code>",
                        "<i>", "</i>"):
                clean = clean.replace(tag, "")
            lines.append(f"  • {clean}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 5) التقرير الكامل
# ═══════════════════════════════════════════════════════════════════════

async def get_diagnostics_report(
    top_n: int = 10,
    as_html: bool = True,
) -> str:
    """توليد تقرير التشخيص الكامل."""
    data = await get_diagnostics_data(top_n=top_n)
    if as_html:
        return await format_diagnostics_html(data, top_n=top_n)
    return await format_diagnostics_plain(data, top_n=top_n)


# ═══════════════════════════════════════════════════════════════════════
# 6) إرسال التقرير عبر Telegram
# ═══════════════════════════════════════════════════════════════════════

async def send_diagnostics_to_chat(
    bot,
    chat_id: int,
    top_n: int = 10,
) -> bool:
    """إرسال تقرير التشخيص إلى chat_id."""
    try:
        from utils import safe_send
        report = await get_diagnostics_report(top_n=top_n, as_html=True)
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
# 7) سطر واحد مختصر
# ═══════════════════════════════════════════════════════════════════════

async def get_diagnostics_one_liner() -> str:
    """سطر واحد مختصر لحالة DB."""
    try:
        health = await get_quick_health()
        color = health.get("color", "🟢")
        db_type = health.get("db_type", "UNKNOWN")
        pool = health.get("pool", {}) or {}
        util = pool.get("utilization_pct", 0)
        return f"{color} DB={db_type} Pool={util}%"
    except Exception as e:
        return f"🔴 DB=ERROR ({str(e)[:30]})"


# ═══════════════════════════════════════════════════════════════════════
# 8) مقارنة تشخيصين
# ═══════════════════════════════════════════════════════════════════════

def compare_diagnostics(
    old_data: Dict[str, Any],
    new_data: Dict[str, Any],
) -> List[str]:
    """مقارنة تشخيصين وإرجاع الفروقات."""
    diffs: List[str] = []

    try:
        old_sum = old_data.get("summary", {}) or {}
        new_sum = new_data.get("summary", {}) or {}

        old_dead = old_sum.get("dead_total", 0)
        new_dead = new_sum.get("dead_total", 0)
        if new_dead != old_dead:
            delta = new_dead - old_dead
            icon = "📈" if delta > 0 else "📉"
            diffs.append(f"{icon} Dead tuples: {delta:+}")

        old_idle = old_sum.get("idle_tx_count", 0)
        new_idle = new_sum.get("idle_tx_count", 0)
        if new_idle != old_idle:
            delta = new_idle - old_idle
            icon = "🔴" if delta > 0 else "🟢"
            diffs.append(f"{icon} idle-tx: {delta:+}")

        old_color = old_sum.get("overall_color", "🟢")
        new_color = new_sum.get("overall_color", "🟢")
        if old_color != new_color:
            diffs.append(f"🎨 الحالة: {old_color} → {new_color}")

    except Exception as e:
        diffs.append(f"⚠️ مقارنة: {e}")

    return diffs


# ═══════════════════════════════════════════════════════════════════════
# __all__
# ═══════════════════════════════════════════════════════════════════════

__all__ = [
    "get_diagnostics_data",
    "get_quick_health",
    "format_diagnostics_html",
    "format_diagnostics_plain",
    "get_diagnostics_report",
    "send_diagnostics_to_chat",
    "get_diagnostics_one_liner",
    "compare_diagnostics",
]


# ═══════════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═══════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "🛡️ db_diagnostics.py v1.1.0 loaded (lazy imports) | "
        "get_diagnostics_data / get_diagnostics_report جاهزتان"
    )
except Exception:
    pass