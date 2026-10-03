#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/handlers_nav_fix.py - v3.1 (delegating dispatcher)
=====================================================================
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

import logging
from telegram import Update
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, ApplicationHandlerStop,
)

logger = logging.getLogger(__name__)


async def log_and_delegate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    🎯 المُوزّع الرئيسي للأزرار.

    الدور:
        1. تسجيل كل ضغطة زر (traceability)
        2. تفويض صريح إلى CallbackHandlers.handle()
        3. منع باقي المعالجات من التشغيل (ApplicationHandlerStop)

    ⚠️ ملاحظة معمارية:
        لأن هذا المُوزّع يُسجَّل في group=-99 (أول مجموعة)، فهو يعمل
        قبل أي CallbackQueryHandler آخر. وبعد رفعه ApplicationHandlerStop،
        لا تُنفَّذ أي معالجة أخرى للأزرار.

        إذن: أيّ CallbackQueryHandler آخر في `main.py` لا يُنفَّذ
        (مثل channels_list إن لم يعتمد على group أصغر من -99).
    """
    query = update.callback_query
    if not query:
        return

    data = query.data or "NO_DATA"
    uid = query.from_user.id if query.from_user else 0

    logger.info(f"🔔 CB: user={uid} data='{data}'")

    # ── تفويض صريح إلى CallbackHandlers ─────────────────────
    try:
        from handlers.handlers_callback import CallbackHandlers
    except ImportError:
        try:
            from handlers_callback import CallbackHandlers
        except ImportError as e:
            logger.error(
                f"❌ NAV_FIX: لا يمكن استيراد CallbackHandlers: {e}",
                exc_info=True,
            )
            return  # لا Stop — نترك معالجات أخرى تحاول

    # ── ✅ FIX-1: احترام ApplicationHandlerStop القادم من الأسفل ──
    try:
        await CallbackHandlers.handle(update, context)
    except ApplicationHandlerStop:
        # 🎯 CallbackHandlers قررت التوقف — نُمرّر القرار بدون logging كاذب
        logger.debug(
            f"⏹️ NAV_FIX: CallbackHandlers raised "
            f"ApplicationHandlerStop — propagating"
        )
        raise
    except Exception as e:
        logger.error(
            f"❌ NAV_FIX: CallbackHandlers.handle error: {e}",
            exc_info=True,
        )
        # لا نُعيد الرفع — نتوقف بالأسفل بأنفسنا

    # ── منع أي معالج آخر ──────────────────────────────────────
    raise ApplicationHandlerStop


def register_nav_fix(application):
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
            "(v3.1 — delegation mode + stop-safe)"
        )
        return True
    except Exception as e:
        logger.error(
            f"❌ NAV_FIX: فشل التسجيل: {e}",
            exc_info=True,
        )
        return False


__all__ = ["log_and_delegate", "register_nav_fix"]