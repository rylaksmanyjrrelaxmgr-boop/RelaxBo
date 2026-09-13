
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/handlers_nav_fix.py - مسجّل أزرار للتشخيص فقط
================================================================================
⚠️ هذا الملف لا يعالج أي زر — يترك كل الأزرار لـ handlers_callback.py
✅ يسجّل فقط كل ضغطة زر في السجلات (للتشخيص)

سيتم التعامل مع أزرار الرجوع/الإغلاق عبر handlers_callback.py (v7.5.15+)
================================================================================
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler

logger = logging.getLogger(__name__)


async def log_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """يسجّل كل ضغطة زر — لا يفعل شيئاً آخر."""
    query = update.callback_query
    if query:
        cb = query.data or "NO_DATA"
        uid = query.from_user.id
        logger.info(f"🔔 CB: user={uid} data='{cb}'")


def register_nav_fix(application):
    """تسجيل المعالجات — logging فقط."""
    try:
        # فقط تسجيل — group=-99 يعمل قبل كل شيء دون اعتراض
        application.add_handler(
            CallbackQueryHandler(log_callback),
            group=-99,
        )
        logger.info("✅ NAV_FIX: تسجيل الأزرار (وضع تسجيل فقط)")
        return True
    except Exception as e:
        logger.error(f"❌ NAV_FIX: {e}", exc_info=True)
        return False