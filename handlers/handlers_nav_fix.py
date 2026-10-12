#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/handlers_nav_fix.py - v3.3.1 (controllable propagation)
========================================================================
🎯 v3.3.1 (FIX-AN1-CONTROL):
    ✅ إضافة NAV_FIX_PROPAGATE_STOP — تحكم صريح في سلوك
       ApplicationHandlerStop.
       • true  (افتراضي) → السلوك الحالي (propagate) — للتوافق الخلفي.
       • false → لا نُمرّر، نسمح لبقية handlers بالعمل.
    ✅ إضافة NAV_FIX_LOG_STOP_EVENTS — تسجيل كل حدث Stop على
       مستوى WARNING لسهولة التشخيص.
    ✅ توثيق دقيق: الفرق بين "لا نرفع في نهاية الدالة" و
       "لا نُمرّر استثناء الـdelegate".

🎯 v3.3.0 (FIX-AN1):
    ✅ إزالة raise ApplicationHandlerStop من نهاية log_and_delegate.
       السبب: كان يُبيد كل CallbackQueryHandler آخر في group ≥ -99.

🎯 v3.2.1:
    📝 توضيح تفاعل log_and_delegate مع handlers أخرى.

🎯 v3.2:
    🔴 FIX-A: حلّ CallbackHandlers.handle (static/class/instance).
    🟠 FIX-B: logger.critical عند استثناء غير ApplicationHandlerStop.
    🟡 FIX-C: NAV_FIX_LOG_LEVEL.
    🟡 FIX-D: NAV_FIX_LOG_DATA_MAX.
    🟡 FIX-E: critical عند فشل الاستيراد.
========================================================================
"""

import inspect
import logging
import os
from typing import Optional, Callable, Awaitable

from telegram import Update
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, ApplicationHandlerStop,
)

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# الإعدادات من البيئة
# ═════════════════════════════════════════════════════════════════════

_NAV_FIX_LOG_LEVEL_NAME = os.getenv(
    "NAV_FIX_LOG_LEVEL", "DEBUG"
).strip().upper()
try:
    _NAV_FIX_LOG_LEVEL = getattr(logging, _NAV_FIX_LOG_LEVEL_NAME)
    if not isinstance(_NAV_FIX_LOG_LEVEL, int):
        _NAV_FIX_LOG_LEVEL = logging.DEBUG
except Exception:
    _NAV_FIX_LOG_LEVEL = logging.DEBUG

try:
    _NAV_FIX_LOG_DATA_MAX = int(
        os.getenv("NAV_FIX_LOG_DATA_MAX", "150")
    )
    if _NAV_FIX_LOG_DATA_MAX < 10:
        _NAV_FIX_LOG_DATA_MAX = 150
except (TypeError, ValueError):
    _NAV_FIX_LOG_DATA_MAX = 150


# 🆕 v3.3.1: تحكم في propagation
def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


_NAV_FIX_PROPAGATE_STOP = _env_bool(
    "NAV_FIX_PROPAGATE_STOP", True
)
_NAV_FIX_LOG_STOP_EVENTS = _env_bool(
    "NAV_FIX_LOG_STOP_EVENTS", True
)


# ═════════════════════════════════════════════════════════════════════
# ✅ FIX-A: حلّ صحيح لـ CallbackHandlers.handle
# ═════════════════════════════════════════════════════════════════════

HandlerCallable = Callable[
    [Update, "ContextTypes.DEFAULT_TYPE"], Awaitable[None]
]

_handler_callable: Optional[HandlerCallable] = None
_handler_resolution_error: Optional[str] = None
_handler_resolved: bool = False


def _resolve_handler_callable() -> Optional[HandlerCallable]:
    """
    ✅ FIX-A: يُحلّ CallbackHandlers.handle بشكل صحيح.
    """
    global _handler_resolution_error

    CallbackHandlers = None
    import_err_msg = ""

    try:
        from handlers.handlers_callback import CallbackHandlers  # noqa
        logger.debug(
            "✅ NAV_FIX: CallbackHandlers من handlers.handlers_callback"
        )
    except ImportError as e1:
        import_err_msg = f"handlers.handlers_callback: {e1}"
        try:
            from handlers_callback import CallbackHandlers  # noqa
            logger.debug(
                "✅ NAV_FIX: CallbackHandlers من handlers_callback"
            )
        except ImportError as e2:
            import_err_msg += f" | handlers_callback: {e2}"

    if CallbackHandlers is None:
        _handler_resolution_error = (
            f"تعذّر استيراد CallbackHandlers — {import_err_msg}"
        )
        return None

    try:
        raw_handle = inspect.getattr_static(
            CallbackHandlers, "handle", None
        )
    except Exception as e:
        _handler_resolution_error = (
            f"getattr_static(CallbackHandlers, 'handle') فشل: {e}"
        )
        return None

    if raw_handle is None:
        _handler_resolution_error = (
            "CallbackHandlers لا يحتوي على دالة 'handle'"
        )
        return None

    if isinstance(raw_handle, staticmethod):
        try:
            return CallbackHandlers.handle
        except Exception as e:
            _handler_resolution_error = (
                f"staticmethod access فشل: {e}"
            )
            return None

    if isinstance(raw_handle, classmethod):
        try:
            return CallbackHandlers.handle
        except Exception as e:
            _handler_resolution_error = (
                f"classmethod access فشل: {e}"
            )
            return None

    try:
        instance = CallbackHandlers()
        return instance.handle
    except Exception as e:
        _handler_resolution_error = (
            f"إنشاء CallbackHandlers() فشل: {e}"
        )
        return None


def _get_handler_callable() -> Optional[HandlerCallable]:
    global _handler_callable, _handler_resolved

    if _handler_resolved:
        return _handler_callable

    _handler_callable = _resolve_handler_callable()
    _handler_resolved = True

    if _handler_callable is None:
        logger.critical(
            f"❌ NAV_FIX: فشل حلّ CallbackHandlers.handle — "
            f"{_handler_resolution_error or 'سبب غير معروف'}"
        )
    else:
        try:
            raw = inspect.getattr_static(
                type(_handler_callable), "__call__", None
            )
        except Exception:
            raw = None
        kind = "unknown"
        if raw is not None:
            kind = getattr(raw, "__name__", "unknown")
        logger.debug(
            f"✅ NAV_FIX: تم حلّ handler callable (kind={kind})"
        )

    return _handler_callable


def _reset_handler_cache() -> None:
    global _handler_callable, _handler_resolved, _handler_resolution_error
    _handler_callable = None
    _handler_resolved = False
    _handler_resolution_error = None
    logger.debug("🔄 NAV_FIX: handler cache أُعيد تصفيره")


# ═════════════════════════════════════════════════════════════════════
# المُوزّع الرئيسي
# ═════════════════════════════════════════════════════════════════════

def _truncate_for_log(data: str, max_len: int = None) -> str:
    limit = max_len if max_len is not None else _NAV_FIX_LOG_DATA_MAX
    if len(data) <= limit:
        return data
    return data[:limit] + f"...[+{len(data) - limit}]"


async def log_and_delegate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    🎯 المُوزّع الرئيسي للأزرار (tracing + delegation).

    الدور (v3.3.1):
        1. تسجيل كل ضغطة زر (traceability).
        2. تفويض صريح إلى CallbackHandlers.handle().
        3. سلوك ApplicationHandlerStop قابل للتحكم عبر:
           NAV_FIX_PROPAGATE_STOP (افتراضي: true = للتوافق الخلفي).

    ⚠️ ملاحظة معمارية (v3.3.1):
        ─────────────────────────────────────────────────────────
        هذا المُوزّع في group=-99 (أول مجموعة).

        سلوك Propagation:
        ┌─────────────────────────────────────────────────────┐
        │  Situation                    | Propagate? | Action │
        ├─────────────────────────────────────────────────────┤
        │  Handler يعيد بلا استثناء      |    —       | Finish │
        │  Handler يرفع ApplicationH...  |  true/false| حسب ENV│
        │  Handler يرفع استثناء آخر      |    —       | Log +  │
        │                                |            | finish │
        └─────────────────────────────────────────────────────┘

        • NAV_FIX_PROPAGATE_STOP=true:
            - إذا رفع delegate ApplicationHandlerStop → نُمرّره.
            - السلوك القديم (v3.3.0).

        • NAV_FIX_PROPAGATE_STOP=false:
            - نتجاهل الاستثناء ونسمح لبقية handlers بالعمل.
            - مفيد إذا كان CallbackHandlers.handle يرفع الاستثناء
              لأزرار لا يملكها (مثل full_health_btn / latency_btn).

        📌 التوصية: إذا لاحظت أن أزرار التحليلات
           (full_health_btn / latency_btn) لا تعمل، اضبط
           NAV_FIX_PROPAGATE_STOP=false ثم أعد التشغيل.
        ─────────────────────────────────────────────────────────
    """
    query = update.callback_query
    if not query:
        return

    raw_data = query.data if query.data is not None else "NO_DATA"
    try:
        data_str = str(raw_data)
    except Exception:
        data_str = "INVALID_DATA"
    data_for_log = _truncate_for_log(data_str)

    uid = query.from_user.id if query.from_user else 0

    logger.log(
        _NAV_FIX_LOG_LEVEL,
        f"🔔 CB: user={uid} data='{data_for_log}'",
    )

    handler = _get_handler_callable()
    if handler is None:
        logger.critical(
            f"❌ NAV_FIX: لا يمكن حلّ handler callable — "
            f"{_handler_resolution_error or 'سبب غير معروف'}. "
            f"لن يتم تفويض الأزرار (data='{data_for_log}')."
        )
        return

    try:
        await handler(update, context)
    except ApplicationHandlerStop:
        # 🆕 v3.3.1: تسجيل دائماً (تشخيص)
        if _NAV_FIX_LOG_STOP_EVENTS:
            logger.warning(
                f"⏹️ NAV_FIX: CallbackHandlers raised "
                f"ApplicationHandlerStop for data='{data_for_log}' | "
                f"propagate={_NAV_FIX_PROPAGATE_STOP}"
            )
        if _NAV_FIX_PROPAGATE_STOP:
            raise
        # ✅ إذا كان false → لا نرفع، بقية handlers تعمل
        return
    except Exception as e:
        logger.critical(
            f"❌ NAV_FIX: handler error: "
            f"{type(e).__name__}: {e} | data='{data_for_log}'",
            exc_info=True,
        )
        # لا نُعيد الرفع


# ═════════════════════════════════════════════════════════════════════
# التسجيل
# ═════════════════════════════════════════════════════════════════════

def register_nav_fix(application) -> bool:
    """
    يُسجّل NAV_FIX في group=-99 (الأول قبل كل شيء).
    """
    if application is None:
        logger.error("❌ NAV_FIX: application=None")
        return False

    try:
        application.add_handler(
            CallbackQueryHandler(log_and_delegate),
            group=-99,
        )
        logger.info(
            "✅ NAV_FIX: مُوزّع الأزرار مُسجّل "
            f"(v3.3.1 — propagate={_NAV_FIX_PROPAGATE_STOP}, "
            f"log_stops={_NAV_FIX_LOG_STOP_EVENTS})"
        )
        return True
    except Exception as e:
        logger.error(
            f"❌ NAV_FIX: فشل التسجيل: {e}",
            exc_info=True,
        )
        return False


# ═════════════════════════════════════════════════════════════════════
# __all__
# ═════════════════════════════════════════════════════════════════════

__all__ = [
    "log_and_delegate",
    "register_nav_fix",
    "_resolve_handler_callable",
    "_get_handler_callable",
    "_reset_handler_cache",
    "_NAV_FIX_LOG_LEVEL",
    "_NAV_FIX_LOG_DATA_MAX",
    # 🆕 v3.3.1
    "_NAV_FIX_PROPAGATE_STOP",
    "_NAV_FIX_LOG_STOP_EVENTS",
]