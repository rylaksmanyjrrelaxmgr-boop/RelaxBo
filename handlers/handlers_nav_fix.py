#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/handlers_nav_fix.py - v3.0 (delegating dispatcher)
=====================================================================
🎯 v3.0:
    - v1.x : كان يلتقط كل الأزرار ويرد عليها (يكسر كل شيء)
    - v2.0 : كان يسجّل فقط ويترك البقية (يسمح لمعالجات أخرى بالتدخل)
    - v3.0 : يسجّل + يُفوّض CallbackHandlers.handle() + يوقف البقية
=====================================================================
"""

import logging
from telegram import Update
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, ApplicationHandlerStop
)

logger = logging.getLogger(__name__)


async def log_and_delegate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
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
            logger.error(f"❌ NAV_FIX: لا يمكن استيراد CallbackHandlers: {e}",
                         exc_info=True)
            return  # لا Stop — نترك معالجات أخرى تحاول

    try:
        await CallbackHandlers.handle(update, context)
    except Exception as e:
        logger.error(f"❌ NAV_FIX: CallbackHandlers.handle error: {e}",
                     exc_info=True)

    # ── منع أي معالج آخر ──────────────────────────────────────
    raise ApplicationHandlerStop


def register_nav_fix(application):
    try:
        application.add_handler(
            CallbackQueryHandler(log_and_delegate),
            group=-99,
        )
        logger.info("✅ NAV_FIX: مُوزّع الأزرار مُسجّل (v3.0 — delegation mode)")
        return True
    except Exception as e:
        logger.error(f"❌ NAV_FIX: فشل التسجيل: {e}", exc_info=True)
        return False


__all__ = ["log_and_delegate", "register_nav_fix"]