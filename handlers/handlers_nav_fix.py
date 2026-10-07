#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/handlers_nav_fix.py - v3.2.1 (delegating dispatcher, hardened)
=====================================================================
🎯 v3.2.1 (توثيق):
    📝 إضافة توضيح في docstring log_and_delegate حول التفاعل
       مع handlers_channels_list.py وبقية CallbackQueryHandlers
       في group > -99.

🎯 v3.2:
    🔴 FIX-A: حلّ صحيح لـ CallbackHandlers.handle — يدعم
              staticmethod / classmethod / instance method.
              قبل: كان يفترض staticmethod دائماً → إن كان instance
                    method، كل الأزرار تصبح ميتة بصمت.
    🟠 FIX-B: عند استثناء غير ApplicationHandlerStop → logger.critical
              + data مُقتطَعة (لتشخيص أوضح).
    🟡 FIX-C: مستوى logging لضغطات الأزرار قابل للضبط عبر البيئة
              NAV_FIX_LOG_LEVEL (افتراضي: DEBUG بدل INFO).
    🟡 FIX-D: تقييد طول data في اللوج إلى NAV_FIX_LOG_DATA_MAX
              (افتراضي 150) لمنع سطور logs ضخمة.
    🟡 FIX-E: توضيح رسالة ImportError بـ logger.critical عند فشل
              كلا مساري الاستيراد (كان error).

🎯 v3.1:
    ✅ FIX-1: فصل ApplicationHandlerStop عن Exception العام
              (يمنع logging مضلِّل ويحترم قرار CallbackHandlers)
    ✅ FIX-2: حماية من None في query.from_user
    ✅ FIX-3: توثيق دور NAV_FIX كمُوزّع وحيد (single dispatcher)

🎯 v3.0:
    - v1.x : كان يلتقط كل الأزرار ويرد عليها (يكسر كل شيء)
    - v2.0 : كان يسجّل فقط ويترك البقية (يسمح لمعالجات أخرى بالتدخل)
    - v3.0 : يسجّل + يُفوّض CallbackHandlers.handle() + يوقف البقية
=====================================================================
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
    🎯 المُوزّع الرئيسي للأزرار.

    الدور:
        1. تسجيل كل ضغطة زر (traceability)
        2. تفويض صريح إلى CallbackHandlers.handle()
        3. منع باقي المعالجات من التشغيل (ApplicationHandlerStop)

    ⚠️ ملاحظة معمارية مهمة (v3.2.1):
        ─────────────────────────────────────────────────────────
        هذا المُوزّع مُسجَّل في group=-99 (أول مجموعة).
        بعد تنفيذه، يرفع ApplicationHandlerStop فيتوقف PTB عن
        استدعاء أي CallbackQueryHandler آخر في group ≥ -99.

        الأثر العملي:
            • أي CallbackQueryHandler في bot.py يُسجَّل بدون group
              صريح (أي group=0) → **لن يُنفَّذ**.
            • أي CallbackQueryHandler في handlers_channels_list.py
              (مثل ch_list, ch_info:, ch_select:, ch_schedule:, ...)
              → **لن يُنفَّذ أيضاً**.
            • كل الأزرار تُفوَّض إلى CallbackHandlers.handle() الذي
              يجب أن يعرف هذه الـ prefixes.

        ✅ هذا مقصود (delegation mode):
            CallbackHandlers.handle() هو الـ single source of truth
            لتوجيه الأزرار. أي prefix غير معروف سيتجاهله، وأي handler
            آخر كان سيعالجه يصبح غير فعّال.

        ⚠️ إذا أردت تشغيل handlers معينة قبل NAV_FIX:
            سجّلها في group=-100 (أصغر من -99)، مثال:

                application.add_handler(
                    CallbackQueryHandler(ch_list_handler),
                    group=-100,  # ← يسبق NAV_FIX
                )

        📌 تشخيص سريع:
            لو ضغطة زر لا تفعل شيئاً، فالمشكلة في:
              (أ) CallbackHandlers.handle() لا يعرف الـ prefix
              (ب) أو handler آخر في group=-100 يعترض قبل NAV_FIX
            وليس في NAV_FIX نفسه.
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

    # ── منع أي معالج آخر ──────────────────────────────────────
    raise ApplicationHandlerStop


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
            "(v3.2.1 — delegation mode + stop-safe + handler-resolve)"
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