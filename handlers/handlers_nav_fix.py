#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/handlers_nav_fix.py - v3.4.0 (trace-only, zero-conflict)
========================================================================
🎯 v3.4.0 (FIX-AN2 — إزالة التفويض نهائياً):
    🔴 المشكلة في v3.3.0:
        كان المُوزّع يستدعي CallbackHandlers.handle يدوياً، ثم
        لا يرفع ApplicationHandlerStop، بينما CallbackHandlers.handle
        مسجَّل أيضاً في PTB (group=0). النتيجة:
            • كل زر يُعالج مرتين (mutation تنقلب على نفسها:
              toggle_auto → True ثم False → لا تغيير).
            • ch_list يُعالج من fallback ثم من channels_list.
            • pub_all ينشر مرتين.

    ✅ الحل (FIX-AN2):
        • NAV_FIX يُسجّل الضغطة فقط (trace-only).
        • ❌ لا استدعاء لـ CallbackHandlers.handle.
        • ❌ لا رفع ApplicationHandlerStop.
        • PTB يوزّع الحادثة بشكل طبيعي على:
              group=0: register_channels_list_handlers (primary, _stop_after)
              group=0: CallbackHandlers.handle (fallback)
              group=0: handlers_analytics, handlers_channels_delete, ...
        • المكسب:
              - لا تكرار.
              - لا mutation معكوسة.
              - traceability + startup diagnostics.
              - صفر تعارض مع أي CallbackQueryHandler آخر.

    🛡️ Startup diagnostic:
        عند التسجيل، يتحقق أن CallbackHandlers.handle قابل للحل
        (من handlers.handlers_callback أو handlers_callback).
        يحذّر إذا كان imports مكسوراً — قبل أول ضغطة.

🎯 v3.3.0 (محفوظ كمرجع):
    FIX-AN1: إزالة raise ApplicationHandlerStop من نهاية
    log_and_delegate — لكن أبقى التفويض اليدوي (double execution).

🎯 v3.2.1 / v3.2 / v3.1 / v3.0 (محفوظة بالكامل):
    FIX-A: حلّ صحيح لـ CallbackHandlers.handle — يدعم
           staticmethod / classmethod / instance method.
    FIX-B: logger.critical عند استثناء.
    FIX-C: مستوى logging قابل للضبط عبر NAV_FIX_LOG_LEVEL.
    FIX-D: تقييد طول data في اللوج عبر NAV_FIX_LOG_DATA_MAX.
    FIX-E: logger.critical عند فشل كلا مساري الاستيراد.

═══════════════════════════════════════════════════════════════════════
📋 ترتيب التسجيل المُوصى به (بدون تعارض):
═══════════════════════════════════════════════════════════════════════
    from handlers_nav_fix import register_nav_fix
    from handlers_channels_list import register_channels_list_handlers
    from handlers_callback import CallbackHandlers

    register_nav_fix(application)                # group=-99  (trace-only)
    register_channels_list_handlers(application) # group=0    (primary)
    application.add_handler(CallbackQueryHandler(
        CallbackHandlers.handle))                # group=0    (fallback)

⚠️ لا تُسجّل CallbackHandlers.handle قبل channels_list.
⚠️ لا ترفع NAV_FIX إلى group=0 — يجب أن يبقى في group=-99.
═══════════════════════════════════════════════════════════════════════
"""

import inspect
import logging
import os
from typing import Optional, Callable, Awaitable

from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# الإعدادات من البيئة (FIX-C / FIX-D)
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


# ═════════════════════════════════════════════════════════════════════
# FIX-A: حلّ CallbackHandlers.handle — للتشخيص عند startup فقط
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

    v3.4.0: النتيجة تُستخدم للتشخيص فقط — لا تفويض.

    الحالات المدعومة:
        1. @staticmethod async def handle(update, context)      ✓
        2. @classmethod  async def handle(cls, update, context) ✓
        3. async def handle(self, update, context)              ✓ (instance)

    Returns:
        callable(update, context) → Awaitable[None] أو None عند الفشل.
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
    """
    يُرجع الـ callable المحلول (مع cache).
    v3.4.0: يُستخدم في startup diagnostic فقط.
    """
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
        kind = type(_handler_callable).__name__
        logger.debug(
            f"✅ NAV_FIX: تم حلّ handler callable (kind={kind})"
        )

    return _handler_callable


def _reset_handler_cache() -> None:
    """
    يُصفّر cache الحلّ — للاختبارات أو hot-reload.
    """
    global _handler_callable, _handler_resolved, _handler_resolution_error
    _handler_callable = None
    _handler_resolved = False
    _handler_resolution_error = None
    logger.debug("🔄 NAV_FIX: handler cache أُعيد تصفيره")


# ═════════════════════════════════════════════════════════════════════
# المُوزّع — trace-only (v3.4.0)
# ═════════════════════════════════════════════════════════════════════

def _truncate_for_log(data: str, max_len: int = None) -> str:
    """✅ FIX-D: اقتطاع آمن لسطر اللوج."""
    limit = max_len if max_len is not None else _NAV_FIX_LOG_DATA_MAX
    if len(data) <= limit:
        return data
    return data[:limit] + f"...[+{len(data) - limit}]"


async def trace_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    🎯 v3.4.0: تسجيل ضغطة الزر فقط (trace-only).

    ⚠️ لا تفويض. لا ApplicationHandlerStop. لا side effects.
       PTB يوزّع الحادثة بشكل طبيعي على بقية المعالجات في
       group=0 (channels_list primary, ثم CallbackHandlers.handle
       كـ fallback).

    الأمان:
        • لا يقرأ/يكتب user_data
        • لا يتصل بـ DB
        • لا يُعدّل أي شيء
        • لا يستدعي query.answer() (وإلا كسر answer الحقيقي)

    الأثر:
        group=-99: هذا المُوزّع (سطر لوج واحد)
        group=0:   handlers_channels_list (primary, _stop_after)
        group=0:   CallbackHandlers.handle (fallback)
        group=0:   handlers_analytics / handlers_channels_delete / ...
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
    # ← لا شيء آخر. لا delegation. لا Stop.


# ✅ v3.4.0: اسم بديل للتوافق الرجعي
log_and_delegate = trace_callback


# ═════════════════════════════════════════════════════════════════════
# Startup diagnostics
# ═════════════════════════════════════════════════════════════════════

def _count_registered_callback_handlers(application) -> int:
    """
    يحسب عدد CallbackQueryHandler المسجَّلة (بعد إضافة NAV_FIX).
    """
    try:
        total = 0
        handlers_dict = getattr(application, "handlers", None)
        if handlers_dict is None:
            return -1
        for group, handlers_list in handlers_dict.items():
            for h in handlers_list:
                if isinstance(h, CallbackQueryHandler):
                    total += 1
        return total
    except Exception as e:
        logger.debug(f"NAV_FIX: _count_registered: {e}")
        return -1


def _startup_diagnostics(application) -> None:
    """
    فحوصات عند التسجيل — قبل أول ضغطة:
        1. هل CallbackHandlers.handle قابل للحل؟
        2. هل هناك CallbackQueryHandlers أخرى؟
    """
    handler = _get_handler_callable()
    if handler is None:
        logger.warning(
            "⚠️ NAV_FIX: CallbackHandlers.handle غير قابل للحل — "
            "تأكد من تسجيل handle() بنفسك، وإلا لن تُعالج الأزرار. "
            f"({_handler_resolution_error})"
        )
    else:
        logger.debug("✅ NAV_FIX: CallbackHandlers.handle مُتحقَّق منه.")

    count = _count_registered_callback_handlers(application)
    if count == 0:
        logger.warning(
            "⚠️ NAV_FIX: لا توجد CallbackQueryHandler أخرى مسجّلة. "
            "تأكد من استدعاء register_channels_list_handlers(application) "
            "و/أو إضافة CallbackQueryHandler(CallbackHandlers.handle)."
        )
    elif count > 0:
        logger.info(
            "✅ NAV_FIX: %d CallbackQueryHandler أخرى مسجّلة (بعد NAV_FIX).",
            count,
        )


# ═════════════════════════════════════════════════════════════════════
# التسجيل
# ═════════════════════════════════════════════════════════════════════

def register_nav_fix(application) -> bool:
    """
    يُسجّل NAV_FIX في group=-99 (أولوية التسجيل فقط).

    v3.4.0: trace-only. لا تفويض. لا Stop.

    Returns:
        True إذا نجح التسجيل، False عند الفشل.
    """
    if application is None:
        logger.error("❌ NAV_FIX: application=None")
        return False

    try:
        application.add_handler(
            CallbackQueryHandler(trace_callback),
            group=-99,
        )
    except Exception as e:
        logger.error(
            f"❌ NAV_FIX: فشل التسجيل: {e}",
            exc_info=True,
        )
        return False

    logger.info(
        "✅ NAV_FIX: مُوزّع trace مُسجَّل "
        "(v3.4.0 — trace-only, zero-conflict, group=-99)"
    )

    try:
        _startup_diagnostics(application)
    except Exception as e:
        logger.debug(f"NAV_FIX: startup diagnostics فشل: {e}")

    return True


# ═════════════════════════════════════════════════════════════════════
# __all__
# ═════════════════════════════════════════════════════════════════════

__all__ = [
    "trace_callback",
    "log_and_delegate",  # alias للتوافق الرجعي
    "register_nav_fix",
    # للاختبار/التشخيص
    "_resolve_handler_callable",
    "_get_handler_callable",
    "_reset_handler_cache",
    "_NAV_FIX_LOG_LEVEL",
    "_NAV_FIX_LOG_DATA_MAX",
]