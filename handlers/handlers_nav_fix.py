#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/handlers_nav_fix.py - v3.3.0 (tracing dispatcher, non-blocking)
========================================================================
🎯 v3.3.0 (FIX-AN1):
    ✅ إزالة raise ApplicationHandlerStop من نهاية log_and_delegate.
       السبب: كان يُبيد كل CallbackQueryHandler آخر في group ≥ -99،
       مما يعطّل:
           • handlers_channels_list.py  (~11 معالج)
           • handlers_analytics.py      (~2 معالج)
           • handlers_channels_delete.py (~3 معالج)
           • أي CallbackQueryHandler مُسجَّل في group=0 بلا group صريح.
       الأثر الجديد:
           • NAV_FIX يسجّل الضغطة ثم يُفوّض إلى CallbackHandlers.handle.
           • بعد التفويض، يستمر PTB في استدعاء بقية المعالجات.
           • ⚠️ إذا كان CallbackHandlers.handle يرفع
             ApplicationHandlerStop بنفسه → سيُمرَّر ويوقف البقية
             (سلوك مقصود).

🎯 v3.2.1:
    📝 إضافة توضيح في docstring log_and_delegate حول التفاعل
       مع handlers_channels_list.py وبقية CallbackQueryHandlers
       في group > -99.

🎯 v3.2:
    🔴 FIX-A: حلّ صحيح لـ CallbackHandlers.handle — يدعم
              staticmethod / classmethod / instance method.
    🟠 FIX-B: عند استثناء غير ApplicationHandlerStop → logger.critical
              + data مُقتطَعة.
    🟡 FIX-C: مستوى logging قابل للضبط عبر NAV_FIX_LOG_LEVEL.
    🟡 FIX-D: تقييد طول data في اللوج إلى NAV_FIX_LOG_DATA_MAX.
    🟡 FIX-E: logger.critical عند فشل كلا مساري الاستيراد.

🎯 v3.1:
    ✅ FIX-1: فصل ApplicationHandlerStop عن Exception العام.
    ✅ FIX-2: حماية من None في query.from_user.
    ✅ FIX-3: توثيق دور NAV_FIX كمُوزّع.

🎯 v3.0:
    - v1.x : كان يلتقط كل الأزرار ويرد عليها (يكسر كل شيء)
    - v2.0 : كان يسجّل فقط ويترك البقية
    - v3.0 : يسجّل + يُفوّض CallbackHandlers.handle() + يوقف البقية
    - v3.3 : يسجّل + يُفوّض + لا يوقف البقية (FIX-AN1)
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

# ✅ FIX-C: مستوى logging لضغطات الأزرار
_NAV_FIX_LOG_LEVEL_NAME = os.getenv(
    "NAV_FIX_LOG_LEVEL", "DEBUG"
).strip().upper()
try:
    _NAV_FIX_LOG_LEVEL = getattr(logging, _NAV_FIX_LOG_LEVEL_NAME)
    if not isinstance(_NAV_FIX_LOG_LEVEL, int):
        _NAV_FIX_LOG_LEVEL = logging.DEBUG
except Exception:
    _NAV_FIX_LOG_LEVEL = logging.DEBUG

# ✅ FIX-D: حد أقصى لطول data في اللوج
try:
    _NAV_FIX_LOG_DATA_MAX = int(
        os.getenv("NAV_FIX_LOG_DATA_MAX", "150")
    )
    if _NAV_FIX_LOG_DATA_MAX < 10:
        _NAV_FIX_LOG_DATA_MAX = 150
except (TypeError, ValueError):
    _NAV_FIX_LOG_DATA_MAX = 150


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

    الحالات المدعومة:
        1. @staticmethod async def handle(update, context)      ✓
        2. @classmethod  async def handle(cls, update, context) ✓
        3. async def handle(self, update, context)              ✓ (instance)

    Returns:
        callable(update, context) → Awaitable[None] أو None عند الفشل.
    """
    global _handler_resolution_error

    # ── استيراد CallbackHandlers ──
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

    # ── حلّ نوع الدالة ──
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

    # ── staticmethod → الوصول المباشر ──
    if isinstance(raw_handle, staticmethod):
        try:
            return CallbackHandlers.handle
        except Exception as e:
            _handler_resolution_error = (
                f"staticmethod access فشل: {e}"
            )
            return None

    # ── classmethod → الوصول عبر الصف ──
    if isinstance(raw_handle, classmethod):
        try:
            return CallbackHandlers.handle
        except Exception as e:
            _handler_resolution_error = (
                f"classmethod access فشل: {e}"
            )
            return None

    # ── instance method → نحتاج instance ──
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
    ✅ FIX-A: نتيجة الحلّ مُخزّنة بعد أول استدعاء.
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
        # حدّد نوع الدالة للتشخيص
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
    """
    يُصفّر cache الحلّ — يُستخدَم في الاختبارات أو hot-reload.
    """
    global _handler_callable, _handler_resolved, _handler_resolution_error
    _handler_callable = None
    _handler_resolved = False
    _handler_resolution_error = None
    logger.debug("🔄 NAV_FIX: handler cache أُعيد تصفيره")


# ═════════════════════════════════════════════════════════════════════
# المُوزّع الرئيسي
# ═════════════════════════════════════════════════════════════════════

def _truncate_for_log(data: str, max_len: int = None) -> str:
    """✅ FIX-D: اقتطاع آمن لسطر اللوج."""
    limit = max_len if max_len is not None else _NAV_FIX_LOG_DATA_MAX
    if len(data) <= limit:
        return data
    return data[:limit] + f"...[+{len(data) - limit}]"


async def log_and_delegate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    🎯 المُوزّع الرئيسي للأزرار (tracing + delegation).

    الدور (v3.3.0):
        1. تسجيل كل ضغطة زر (traceability)
        2. تفويض صريح إلى CallbackHandlers.handle()
        3. ❌ لا يمنع باقي المعالجات — FIX-AN1

    ⚠️ ملاحظة معمارية مهمة (v3.3.0):
        ─────────────────────────────────────────────────────────
        هذا المُوزّع مُسجَّل في group=-99 (أول مجموعة).
        بعد تنفيذه:
            • يُسجّل الضغطة.
            • يُفوّض إلى CallbackHandlers.handle().
            • ⚠️ لا يرفع ApplicationHandlerStop — يسمح لبقية
              CallbackQueryHandlers في group ≥ -99 بالتنفيذ.

        الأثر العملي (مقصود):
            • CallbackHandlers.handle() يعمل كـ first handler.
            • handlers_channels_list.py / handlers_analytics.py /
              handlers_channels_delete.py تُستدعى أيضاً.
            • إذا أراد CallbackHandlers.handle إيقاف البقية،
              يرفع ApplicationHandlerStop بنفسه وسيُمرَّر.

        ✅ إذا لاحظت تكرار معالجة: راجع CallbackHandlers.handle
           وتأكد أن كل prefix يُعالَج في مكان واحد فقط.

        📌 ترتيب التنفيذ الموصى به:
            - group=-99 : NAV_FIX (هذا الملف) — تسجيل + تفويض
            - group=0   : CallbackHandlers.handle
            - group=0   : handlers_channels_list, handlers_analytics, ...
            - group=1   : fallback handlers (إن وُجدت)
        ─────────────────────────────────────────────────────────
    """
    query = update.callback_query
    if not query:
        return

    # ✅ FIX-D: اقتطاع data لتجنّب سطور لوج ضخمة
    raw_data = query.data if query.data is not None else "NO_DATA"
    try:
        data_str = str(raw_data)
    except Exception:
        data_str = "INVALID_DATA"
    data_for_log = _truncate_for_log(data_str)

    uid = query.from_user.id if query.from_user else 0

    # ✅ FIX-C: مستوى قابل للضبط (افتراضي DEBUG)
    logger.log(
        _NAV_FIX_LOG_LEVEL,
        f"🔔 CB: user={uid} data='{data_for_log}'",
    )

    # ── تفويض صريح إلى CallbackHandlers ─────────────────────
    handler = _get_handler_callable()
    if handler is None:
        # ✅ FIX-E: critical بدل error — هذا يعني عطلاً كاملاً
        logger.critical(
            f"❌ NAV_FIX: لا يمكن حلّ handler callable — "
            f"{_handler_resolution_error or 'سبب غير معروف'}. "
            f"لن يتم تفويض الأزرار (data='{data_for_log}')."
        )
        # لا Stop — نترك معالجات أخرى تحاول (fail-open للـ import)
        return

    # ── تنفيذ handler مع احترام ApplicationHandlerStop ──
    try:
        await handler(update, context)
    except ApplicationHandlerStop:
        # 🎯 CallbackHandlers قررت التوقف — نُمرّر القرار بدون logging كاذب
        logger.debug(
            f"⏹️ NAV_FIX: handler raised "
            f"ApplicationHandlerStop — propagating"
        )
        raise
    except Exception as e:
        # ✅ FIX-B: critical + data للسياق
        logger.critical(
            f"❌ NAV_FIX: handler error: "
            f"{type(e).__name__}: {e} | data='{data_for_log}'",
            exc_info=True,
        )
        # لا نُعيد الرفع — نتوقف بالأسفل بأنفسنا

    # ✅ FIX-AN1: لا raise ApplicationHandlerStop هنا.
    # السماح لبقية CallbackQueryHandlers في group=0 أو group=-1 بالتنفيذ.


# ═════════════════════════════════════════════════════════════════════
# التسجيل
# ═════════════════════════════════════════════════════════════════════

def register_nav_fix(application) -> bool:
    """
    يُسجّل NAV_FIX في group=-99 (الأول قبل كل شيء).

    Returns:
        True إذا نجح التسجيل، False عند الفشل.
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
            "(v3.3.0 — delegation mode + FIX-AN1 non-blocking)"
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
    # للاختبار/التشخيص
    "_resolve_handler_callable",
    "_get_handler_callable",
    "_reset_handler_cache",
    "_NAV_FIX_LOG_LEVEL",
    "_NAV_FIX_LOG_DATA_MAX",
]