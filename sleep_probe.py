#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sleep_probe.py — كاشف تأخيرات asyncio.sleep (v1.0.3)
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

🆕 v1.0.3 — DEDUP-PER-LOCATION:
    🟢 FIX-STARTUP-NOISE: التحذيرات كانت تُولَّد مئات المرات من نفس
        الموقع (مثلاً _gil_lag_monitor يحلِق في `await asyncio.sleep(0.1)`
        و BG-TASK stagger `await asyncio.sleep(0.4)`). كل دورة تُنتج تحذيراً
        منفصلاً → ضوضاء تغمر السجل بلا قيمة تشخيصية.
    🟢 FIX-DEDUP: لكل موقع (`file:line in func`) لا نُسجِّل أكثر من مرة
        واحدة كل SLEEP_PROBE_DEDUP_SEC (افتراضي 60s). أول تجاوز للـthreshold
        يُسجَّل فوراً، ثم نكتفي بتحديث الإحصاءات صامتةً حتى انتهاء النافذة.
    🟢 FIX-DEFAULT-THRESHOLD: رفع الافتراضي 100ms → 150ms لأن أحداث
        100-150ms شائعة على Render free tier تحت ضغط البوت ولا تُشير لخلل.
        الإعداد القابل للضبط عبر env يبقى سارياً إن حُدِّد صراحةً.
    🟢 FIX-STARTUP-GRACE: فترة سماح SLEEP_PROBE_GRACE_SEC (افتراضي 30s)
        بعد install لا تُسجَّل فيها تحذيرات إطلاقاً. السبب: استنزاف عادي
        أثناء بدء التشغيل (DB init, handlers register, managed_bots spawn)
        يُولِّد overshoot مؤقت لا يعكس مشكلة دائمة. الإحصاءات تُحدَّث.

🆕 v1.0.2 — FULL-POLISHED (محفوظ):
    🔴 FIX-UNINSTALL-REDUNDANT: تبسيط uninstall_sleep_probe().
        الفرعان كانا يفعلان نفس السطر — تم توحيدهما في سطر واحد.
    🟡 FIX-UNINSTALL-DETECT: كشف الحالة الفعلية عبر السمة
        _sleep_probe_wrapped بدل الاعتماد على _INSTALLED فقط.
        يضمن الاستعادة حتى بعد importlib.reload.
    🟡 FIX-SHOULD-LOG: ضمان صحة should_log حتى لو فشل increment
        الإحصاء (يُحدَّد بشكل مستقل عن try/except).

🆕 v1.0.1 — POLISHED (محفوظ):
    • إزالة imports غير مستخدمة (Deque, Tuple).
    • _traceback_hint() كسول (lazy).
    • حماية double-wrap عبر سمة _sleep_probe_wrapped.
    • signature مطابق للأصل (delay, result=None).

⚠️ تحذيرات مهمة:
    • استخدم install_sleep_probe() في bot.py بعد logging.basicConfig.
    • اللفّ العالمي يؤثر على كل imports لاحقة.
    • uninstall_sleep_probe() يُعيد السلوك الأصلي (reversible).
    • يمكن تفعيله تلقائياً عبر env: SLEEP_PROBE_ENABLED=1

متغيرات البيئة الاختيارية:
    SLEEP_PROBE_ENABLED=1            # تفعيل تلقائي (افتراضي: 0)
    SLEEP_PROBE_THRESHOLD_MS=150     # حد الـovershoot بالمللي ثانية
    SLEEP_PROBE_MAX_LOGS=50          # أقصى عدد WARNING إجمالي
    SLEEP_PROBE_LOG_LEVEL=WARNING    # WARNING/INFO/DEBUG
    SLEEP_PROBE_DEDUP_SEC=60         # لا تكرر نفس الموقع قبل هذه المدة
    SLEEP_PROBE_GRACE_SEC=30         # فترة سماح بعد install بلا تحذيرات
    SLEEP_PROBE_MAX_LOGS_PER_LOC=3   # أقصى تحذيرات لكل موقع (طوال العمر)
================================================================================
"""

import asyncio
import logging
import os
import time
import traceback
from collections import deque
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════
# استخراج asyncio.sleep الأصلي بأمان (متجاوزاً أي wrap سابق منّا)
# ═══════════════════════════════════════════════════════════════════════

def _get_true_orig_sleep():
    """
    يُرجع asyncio.sleep الأصلي الحقيقي، متجاوزاً أي wrap سابق منّا.

    السبب: عند importlib.reload(sleep_probe) بعد install،
    asyncio.sleep يكون نسخة _wrapped_sleep من الجلسة السابقة.
    نكشف ذلك عبر السمة _sleep_probe_wrapped.
    """
    current = asyncio.sleep
    inner = getattr(current, "_sleep_probe_wrapped", None)
    if inner is not None and callable(inner):
        return inner
    return current

_ORIG_SLEEP = _get_true_orig_sleep()

# ═══════════════════════════════════════════════════════════════════════
# الحالة العامة
# ═══════════════════════════════════════════════════════════════════════

_INSTALLED = False

# الإعدادات (تُحدَّث عند install)
_THRESHOLD_MS: float = 150.0
_MAX_LOGS: int = 50
_LOG_LEVEL: int = logging.WARNING
_DEDUP_SEC: float = 60.0          # 🆕 v1.0.3: لا تكرر نفس الموقع قبل هذه المدة
_GRACE_SEC: float = 30.0          # 🆕 v1.0.3: فترة سماح بعد install بلا تحذيرات
_MAX_LOGS_PER_LOC: int = 3        # 🆕 v1.0.3: أقصى تحذيرات لكل موقع (طوال العمر)

# 🆕 v1.0.3: تتبع آخر تسجيل لكل موقع + عداد لكل موقع
# البنية: { hint: {"last_ts": float, "count": int} }
_LAST_LOG_PER_LOC: Dict[str, Dict[str, Any]] = {}

# 🆕 v1.0.3: لحظة التثبيت (لحساب فترة السماح)
_INSTALL_TS: float = 0.0

# إحصاءات
_STATS: Dict[str, Any] = {
    "total_sleeps": 0,
    "overshoot_count": 0,
    "max_overshoot_ms": 0.0,
    "top_slow": deque(maxlen=10),
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
        for frame in reversed(stack[:-1]):
            fname = frame.filename or ""
            if ("sleep_probe" in fname
                    or "/asyncio/" in fname
                    or "\\asyncio\\" in fname):
                continue
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

async def _wrapped_sleep(delay, result=None):
    """
    نسخة مُلفَّفة من asyncio.sleep.

    signature مطابق للأصل: async def sleep(delay, result=None).

    السلوك:
      • تستدعي الأصلية بنفس الوسائط.
      • تقيس الزمن الفعلي وتقارنه بالمتوقع.
      • عند overshoot > _THRESHOLD_MS → WARNING (بحد أقصى _MAX_LOGS).
      • تعيد رفع asyncio.CancelledError كما هو (لا تكسره).
      • آمنة للاستدعاء من مهام متعددة في وقت واحد.
      • _traceback_hint() يُستدعى فقط عندما نكون على وشك التسجيل.
    """
    # حماية: بعض المكتبات تمرّر delay=None
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
    return_value = None
    try:
        if result is not None:
            return_value = await _ORIG_SLEEP(delay, result)
        else:
            return_value = await _ORIG_SLEEP(delay)
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
            # تحديث الإحصاءات
            try:
                _STATS["overshoot_count"] += 1
                if overshoot_ms > _STATS["max_overshoot_ms"]:
                    _STATS["max_overshoot_ms"] = overshoot_ms
            except Exception:
                pass

            # نحفظ hint فقط إذا كنا سنُسجِّل — احسبه الآن لأن dedup يعتمد عليه
            hint = _traceback_hint()

            # 🟢 v1.0.3 FIX-DEDUP: للكل موقع لا نُسجِّل أكثر من مرة كل _DEDUP_SEC،
            # وأيضاً نحترم سقف _MAX_LOGS_PER_LOC لكل موقع (طوال العمر).
            # الإحصاءات تُحدَّث دائماً (للرصد عبر /fullhealth) — الصمت هنا على
            # التسجيل فقط، لا على الرصد.
            now_ts = time.monotonic()
            should_log = False
            try:
                # 🟢 v1.0.3 FIX-STARTUP-GRACE: فترة سماح بعد install
                if _INSTALL_TS == 0.0 or (now_ts - _INSTALL_TS) >= _GRACE_SEC:
                    # السقف الإجمالي
                    if _STATS["overshoot_count"] <= _MAX_LOGS:
                        loc_entry = _LAST_LOG_PER_LOC.get(hint)
                        if loc_entry is None:
                            # أول مرة لهذا الموقع → سجّل فوراً
                            should_log = True
                            _LAST_LOG_PER_LOC[hint] = {
                                "last_ts": now_ts,
                                "count": 1,
                            }
                        else:
                            within_dedup = (
                                now_ts - loc_entry["last_ts"]
                            ) < _DEDUP_SEC
                            under_loc_cap = (
                                loc_entry["count"] < _MAX_LOGS_PER_LOC
                            )
                            if under_loc_cap and not within_dedup:
                                should_log = True
                                loc_entry["last_ts"] = now_ts
                                loc_entry["count"] = (
                                    loc_entry["count"] + 1
                                )
            except Exception:
                should_log = False

            try:
                _STATS["top_slow"].append((
                    round(overshoot_ms, 1),
                    round(delay_f, 3),
                    hint,
                ))
            except Exception:
                pass

            # التسجيل (spam-limited)
            if should_log:
                try:
                    logger.log(
                        _LOG_LEVEL,
                        "🐢 sleep overshoot: "
                        "delay=%.0fms actual=%.0fms overshoot=%.0fms | at=%s",
                        expected_ms,
                        elapsed_ms,
                        overshoot_ms,
                        hint,
                    )
                except Exception:
                    pass

    return return_value

# حفظ الأصل على الدالة نفسها لكشف double-wrap لاحقاً
_wrapped_sleep._sleep_probe_wrapped = _ORIG_SLEEP

# ═══════════════════════════════════════════════════════════════════════
# API العام
# ═══════════════════════════════════════════════════════════════════════

def install_sleep_probe(
    *,
    threshold_ms: Optional[float] = None,
    max_logs: Optional[int] = None,
    log_level: Optional[int] = None,
    dedup_sec: Optional[float] = None,
    grace_sec: Optional[float] = None,
    max_logs_per_loc: Optional[int] = None,
) -> bool:
    """
    يُثبِّت المُلفِّف. آمن للتكرار (idempotent).

    Args:
        threshold_ms:     الحد الأدنى للـovershoot لتسجيله. افتراضي 150ms.
        max_logs:         أقصى عدد WARNING إجمالي. افتراضي 50.
        log_level:        مستوى التسجيل. افتراضي WARNING.
        dedup_sec:        🆕 v1.0.3 لا تكرر نفس الموقع قبل هذه المدة.
                          افتراضي 60s.
        grace_sec:        🆕 v1.0.3 فترة سماح بعد install بلا تحذيرات.
                          افتراضي 30s.
        max_logs_per_loc: 🆕 v1.0.3 أقصى تحذيرات لكل موقع (طوال العمر).
                          افتراضي 3.

    Returns:
        True   إذا ثُبِّت الآن.
        False  إذا كان مُثبَّتاً سابقاً.
    """
    global _INSTALLED, _THRESHOLD_MS, _MAX_LOGS, _LOG_LEVEL
    global _DEDUP_SEC, _GRACE_SEC, _MAX_LOGS_PER_LOC, _INSTALL_TS
    global _LAST_LOG_PER_LOC

    if _INSTALLED:
        logger.debug("sleep_probe: already installed — skipped")
        return False

    if threshold_ms is not None:
        _THRESHOLD_MS = max(10.0, float(threshold_ms))
    else:
        _THRESHOLD_MS = max(
            10.0, _env_float("SLEEP_PROBE_THRESHOLD_MS", 150.0)
        )

    if max_logs is not None:
        _MAX_LOGS = max(1, int(max_logs))
    else:
        _MAX_LOGS = max(1, _env_int("SLEEP_PROBE_MAX_LOGS", 50))

    if log_level is not None:
        _LOG_LEVEL = int(log_level)
    else:
        _LOG_LEVEL = _env_log_level(
            "SLEEP_PROBE_LOG_LEVEL", logging.WARNING
        )

    # 🆕 v1.0.3
    if dedup_sec is not None:
        _DEDUP_SEC = max(0.0, float(dedup_sec))
    else:
        _DEDUP_SEC = max(0.0, _env_float("SLEEP_PROBE_DEDUP_SEC", 60.0))

    if grace_sec is not None:
        _GRACE_SEC = max(0.0, float(grace_sec))
    else:
        _GRACE_SEC = max(0.0, _env_float("SLEEP_PROBE_GRACE_SEC", 30.0))

    if max_logs_per_loc is not None:
        _MAX_LOGS_PER_LOC = max(1, int(max_logs_per_loc))
    else:
        _MAX_LOGS_PER_LOC = max(
            1, _env_int("SLEEP_PROBE_MAX_LOGS_PER_LOC", 3)
        )

    # 🆕 v1.0.3: تصفير تتبع المواقع + لحظة التثبيت
    _LAST_LOG_PER_LOC = {}
    _INSTALL_TS = time.monotonic()

    asyncio.sleep = _wrapped_sleep
    _INSTALLED = True

    try:
        logger.info(
            "🔍 sleep_probe: INSTALLED | "
            "threshold=%.0fms | max_logs=%d | log_level=%s | "
            "dedup=%.0fs | grace=%.0fs | max_per_loc=%d",
            _THRESHOLD_MS,
            _MAX_LOGS,
            logging.getLevelName(_LOG_LEVEL),
            _DEDUP_SEC,
            _GRACE_SEC,
            _MAX_LOGS_PER_LOC,
        )
    except Exception:
        pass
    return True

def uninstall_sleep_probe() -> bool:
    """
    يُعيد asyncio.sleep الأصلي (reversible).

    🟡 FIX-UNINSTALL-DETECT: كشف الحالة الفعلية عبر السمة بدل
    الاعتماد على _INSTALLED فقط. يضمن الاستعادة حتى بعد reload.

    🟡 FIX-UNINSTALL-REDUNDANT: سطر استعادة واحد (لا فروع مكررة).
    """
    global _INSTALLED

    # كشف الحالة الفعلية: هل asyncio.sleep يحمل سمتنا؟
    currently_wrapped = (
        getattr(asyncio.sleep, "_sleep_probe_wrapped", None) is not None
    )

    if not _INSTALLED and not currently_wrapped:
        return False

    # استعادة الأصل مباشرة (سطر واحد)
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
            "dedup_sec": _DEDUP_SEC,
            "grace_sec": _GRACE_SEC,
            "max_logs_per_loc": _MAX_LOGS_PER_LOC,
            "total_sleeps": total,
            "overshoot_count": over,
            "overshoot_rate_pct": (
                round(over / total * 100.0, 2) if total > 0 else 0.0
            ),
            "max_overshoot_ms": round(_STATS["max_overshoot_ms"], 1),
            "tracked_locations": len(_LAST_LOG_PER_LOC),
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
    # 🆕 v1.0.3: تصفية تتبع المواقع ليُسمح بتسجيلها مجدداً
    _LAST_LOG_PER_LOC.clear()

def auto_install() -> bool:
    """
    يُثبِّت تلقائياً بناءً على env var SLEEP_PROBE_ENABLED.

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
# LOAD BEACON — v1.0.3
# ═══════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "🛡️ sleep_probe.py v1.0.3 loaded | "
        "install/uninstall ✅ | "
        "idempotent ✅ | "
        "cancel-safe ✅ | "
        "traceback-hint ✅ | "
        "env-config ✅ | "
        "double-wrap-guard ✅ | "
        "signature-preserved ✅ | "
        "lazy-hint ✅ | "
        "uninstall-detect ✅ | "
        "dedup-per-loc ✅ | "
        "grace-period ✅ | "
        "auto_install=%s",
        "on" if os.getenv("SLEEP_PROBE_ENABLED", "0") == "1" else "off",
    )
except Exception:
    pass