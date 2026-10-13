#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sleep_probe.py — كاشف تأخيرات asyncio.sleep (v1.0.0)
================================================================================
الغرض:
    كشف تأخيرات event loop الناتجة عن استدعاءات asyncio.sleep التي تنتظر
    أطول بكثير من المتوقع (50-500ms+ overshoot). هذا يظهر عندما:
      • عملية sync تسدّ الـ loop لفترة طويلة
      • الشبكة بطيئة في TLS/HTTP
      • library تستدعي time.sleep داخلياً

كيف يعمل:
    1. install_sleep_probe() يُلفّ asyncio.sleep العالمي.
    2. كل استدعاء يُقاس؛ إن overshoot > threshold → WARNING.
    3. يُسجَّل الـ traceback للوصول لمكان الاستدعاء الأصلي.
    4. get_stats() يُرجع ملخص (للتكامل مع /fullhealth أو /cache_stats).

⚠️ تحذيرات مهمة:
    • استخدم install_sleep_probe() في bot.py بعد logging.basicConfig.
    • اللفّ العالمي يؤثر على كل imports لاحقة — راجع الملاحظات في النهاية.
    • uninstall_sleep_probe() يُعيد السلوك الأصلي (reversible).
    • يمكن تفعيله تلقائياً عبر env: SLEEP_PROBE_ENABLED=1

متغيرات البيئة الاختيارية:
    SLEEP_PROBE_ENABLED=1            # تفعيل تلقائي (افتراضي: 0)
    SLEEP_PROBE_THRESHOLD_MS=100     # حد الـovershoot بالمللي ثانية
    SLEEP_PROBE_MAX_LOGS=50          # أقصى عدد WARNING
    SLEEP_PROBE_LOG_LEVEL=WARNING    # WARNING/INFO/DEBUG
================================================================================
"""

import asyncio
import logging
import os
import time
import traceback
from collections import deque
from typing import Any, Deque, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
# الحالة العامة
# ═══════════════════════════════════════════════════════════════════════

# نحفظ الدالة الأصلية قبل أي patch
_ORIG_SLEEP = asyncio.sleep

_INSTALLED = False

# الإعدادات (تُحدَّث عند install)
_THRESHOLD_MS: float = 100.0
_MAX_LOGS: int = 50
_LOG_LEVEL: int = logging.WARNING

# إحصاءات
_STATS: Dict[str, Any] = {
    "total_sleeps": 0,
    "overshoot_count": 0,
    "max_overshoot_ms": 0.0,
    "top_slow": deque(maxlen=10),   # deque[(overshoot_ms, delay_s, location)]
}

# ═══════════════════════════════════════════════════════════════════════
# أدوات داخلية
# ═══════════════════════════════════════════════════════════════════════

def _env_float(name: str, default: float) -> float:
    try:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        val = float(raw)
        return val if val > 0 else default
    except (TypeError, ValueError):
        return default

def _env_int(name: str, default: int) -> int:
    try:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        val = int(raw)
        return val if val > 0 else default
    except (TypeError, ValueError):
        return default

def _env_log_level(name: str, default: int) -> int:
    try:
        raw = os.getenv(name, "").strip().upper()
        if not raw:
            return default
        return getattr(logging, raw, default)
    except Exception:
        return default

def _traceback_hint() -> str:
    """
    يعيد آخر إطار stack **قبل** sleep_probe — أي مكان الاستدعاء الحقيقي.
    مثال: 'handlers/handlers_callback.py:2341 in _publish_single'
    """
    try:
        stack = traceback.extract_stack()
        # تجاهل frames sleep_probe نفسه + asyncio internals
        for frame in reversed(stack[:-1]):
            fname = frame.filename or ""
            if ("sleep_probe" in fname
                    or "/asyncio/" in fname
                    or "\\asyncio\\" in fname):
                continue
            # نحاول إظهار اسم ملف مختصر
            short = fname
            for sep in ("/", "\\"):
                if sep in short:
                    parts = short.split(sep)
                    short = "/".join(parts[-2:]) if len(parts) >= 2 else short
                    break
            return f"{short}:{frame.lineno} in {frame.name}"
        return "?"
    except Exception:
        return "?"

# ═══════════════════════════════════════════════════════════════════════
# الدالة المُلفَّفة
# ═══════════════════════════════════════════════════════════════════════

async def _wrapped_sleep(delay, *args, **kwargs):
    """
    نسخة مُلفَّفة من asyncio.sleep.

    السلوك:
      • تستدعي الأصلية بنفس الوسائط.
      • تقيس الزمن الفعلي وتقارنه بالمتوقع.
      • عند overshoot > _THRESHOLD_MS → WARNING (بحد أقصى _MAX_LOGS).
      • تعيد رفع asyncio.CancelledError كما هو (لا تكسره).
      • آمنة للاستدعاء من مهام متعددة في وقت واحد.
    """
    # حماية: بعض المكتبات تمرّر delay=None أو None-ish
    if delay is None:
        delay = 0
    try:
        delay_f = float(delay)
        if delay_f < 0:
            delay_f = 0.0
    except (TypeError, ValueError):
        delay_f = 0.0

    t0 = time.monotonic()
    cancelled = False
    result = None
    try:
        result = await _ORIG_SLEEP(delay, *args, **kwargs)
    except asyncio.CancelledError:
        cancelled = True
        raise
    finally:
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        expected_ms = delay_f * 1000.0
        overshoot_ms = elapsed_ms - expected_ms

        try:
            _STATS["total_sleeps"] += 1
        except Exception:
            pass

        # لا نُسجِّل عند الإلغاء (سلوك طبيعي)
        if not cancelled and overshoot_ms > _THRESHOLD_MS:
            try:
                _STATS["overshoot_count"] += 1
                if overshoot_ms > _STATS["max_overshoot_ms"]:
                    _STATS["max_overshoot_ms"] = overshoot_ms
                _STATS["top_slow"].append((
                    round(overshoot_ms, 1),
                    round(delay_f, 3),
                    _traceback_hint(),
                ))
            except Exception:
                pass

            # حد السبام
            if _STATS["overshoot_count"] <= _MAX_LOGS:
                try:
                    logger.log(
                        _LOG_LEVEL,
                        "🐢 sleep overshoot: "
                        "delay=%.0fms actual=%.0fms overshoot=%.0fms | at=%s",
                        expected_ms,
                        elapsed_ms,
                        overshoot_ms,
                        _STATS["top_slow"][-1][2],
                    )
                except Exception:
                    pass

    return result

# ═══════════════════════════════════════════════════════════════════════
# API العام
# ═══════════════════════════════════════════════════════════════════════

def install_sleep_probe(
    *,
    threshold_ms: Optional[float] = None,
    max_logs: Optional[int] = None,
    log_level: Optional[int] = None,
) -> bool:
    """
    يُثبِّت المُلفِّف. آمن للتكرار (idempotent).

    Args:
        threshold_ms: الحد الأدنى للـovershoot لتسجيله. افتراضي 100ms.
        max_logs:     أقصى عدد WARNING قبل التوقف. افتراضي 50.
        log_level:    مستوى التسجيل. افتراضي WARNING.

    Returns:
        True   إذا ثُبِّت الآن.
        False  إذا كان مُثبَّتاً سابقاً.
    """
    global _INSTALLED, _THRESHOLD_MS, _MAX_LOGS, _LOG_LEVEL

    if _INSTALLED:
        logger.debug("sleep_probe: already installed — skipped")
        return False

    # إعدادات: الوسائط تتقدّم على env vars
    if threshold_ms is not None:
        _THRESHOLD_MS = max(10.0, float(threshold_ms))
    else:
        _THRESHOLD_MS = max(10.0, _env_float("SLEEP_PROBE_THRESHOLD_MS", 100.0))

    if max_logs is not None:
        _MAX_LOGS = max(1, int(max_logs))
    else:
        _MAX_LOGS = max(1, _env_int("SLEEP_PROBE_MAX_LOGS", 50))

    if log_level is not None:
        _LOG_LEVEL = int(log_level)
    else:
        _LOG_LEVEL = _env_log_level("SLEEP_PROBE_LOG_LEVEL", logging.WARNING)

    asyncio.sleep = _wrapped_sleep
    _INSTALLED = True

    try:
        logger.info(
            "🔍 sleep_probe: INSTALLED | "
            "threshold=%.0fms | max_logs=%d | log_level=%s",
            _THRESHOLD_MS,
            _MAX_LOGS,
            logging.getLevelName(_LOG_LEVEL),
        )
    except Exception:
        pass
    return True

def uninstall_sleep_probe() -> bool:
    """يُعيد asyncio.sleep الأصلي (reversible)."""
    global _INSTALLED
    if not _INSTALLED:
        return False
    asyncio.sleep = _ORIG_SLEEP
    _INSTALLED = False
    try:
        logger.info("🔍 sleep_probe: UNINSTALLED")
    except Exception:
        pass
    return True

def is_installed() -> bool:
    return _INSTALLED

def get_stats() -> Dict[str, Any]:
    """ملخص الإحصاءات — للاستخدام في /fullhealth أو /cache_stats."""
    try:
        total = _STATS["total_sleeps"]
        over = _STATS["overshoot_count"]
        return {
            "installed": _INSTALLED,
            "threshold_ms": _THRESHOLD_MS,
            "max_logs": _MAX_LOGS,
            "total_sleeps": total,
            "overshoot_count": over,
            "overshoot_rate_pct": (
                round(over / total * 100.0, 2) if total > 0 else 0.0
            ),
            "max_overshoot_ms": round(_STATS["max_overshoot_ms"], 1),
            "top_slow": [
                {
                    "overshoot_ms": item[0],
                    "delay_s": item[1],
                    "at": item[2],
                }
                for item in sorted(
                    _STATS["top_slow"], key=lambda x: -x[0]
                )[:5]
            ],
        }
    except Exception as e:
        return {"error": str(e)[:120]}

def get_stats_text(limit: int = 5) -> str:
    """نسخة HTML جاهزة للعرض في Telegram (اختياري)."""
    s = get_stats()
    if "error" in s:
        return f"⚠️ sleep_probe: {s['error']}"

    if not s.get("installed"):
        return "ℹ️ sleep_probe: غير مُثبَّت"

    lines = [
        "🔍 <b>sleep_probe</b>",
        f"  threshold: <b>{s['threshold_ms']:.0f}ms</b>",
        f"  total sleeps: <b>{s['total_sleeps']:,}</b>",
        f"  overshoots: <b>{s['overshoot_count']}</b> "
        f"({s['overshoot_rate_pct']}%)",
        f"  max overshoot: <b>{s['max_overshoot_ms']:.0f}ms</b>",
    ]
    top = s.get("top_slow") or []
    if top:
        lines.append("  <b>أبطأ 5:</b>")
        for i, item in enumerate(top[:limit], 1):
            lines.append(
                f"    {i}. <b>{item['overshoot_ms']:.0f}ms</b> "
                f"@ <code>{_html_escape(item['at'])}</code>"
            )
    return "\n".join(lines)

def reset_stats() -> None:
    """يُصفِّر الإحصاءات (يبقى اللفّ مفعّلاً)."""
    _STATS["total_sleeps"] = 0
    _STATS["overshoot_count"] = 0
    _STATS["max_overshoot_ms"] = 0.0
    _STATS["top_slow"].clear()

def auto_install() -> bool:
    """
    يُثبِّت تلقائياً بناءً على env var SLEEP_PROBE_ENABLED.
    مُصمَّم للاستدعاء من bot.py عند الإقلاع.

    Returns:
        True إذا فُعِّل، False إذا لم يُفعَّل (env غير مضبوط).
    """
    try:
        enabled = os.getenv("SLEEP_PROBE_ENABLED", "0").strip().lower()
    except Exception:
        return False
    if enabled in ("1", "true", "yes", "on"):
        return install_sleep_probe()
    return False

def _html_escape(s: Any) -> str:
    try:
        import html
        return html.escape(str(s)) if s is not None else ""
    except Exception:
        return ""

# ═══════════════════════════════════════════════════════════════════════
# __all__
# ═══════════════════════════════════════════════════════════════════════

__all__ = [
    "install_sleep_probe",
    "uninstall_sleep_probe",
    "is_installed",
    "get_stats",
    "get_stats_text",
    "reset_stats",
    "auto_install",
]

# ═══════════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═══════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "🛡️ sleep_probe.py v1.0.0 loaded | "
        "install/uninstall ✅ | "
        "idempotent ✅ | "
        "cancel-safe ✅ | "
        "traceback-hint ✅ | "
        "env-config ✅ | "
        "auto_install=%s",
        "on" if os.getenv("SLEEP_PROBE_ENABLED", "0") == "1" else "off",
    )
except Exception:
    pass