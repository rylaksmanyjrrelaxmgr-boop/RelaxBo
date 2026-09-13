#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/handlers_nav_fix.py - إصلاح التنقل
================================================================================
- يعترض أزرار الإغلاق/الرجوع
- يعيد عرض قائمة المجموعات عبر البوت الأصلي (بنفس التصميم)
================================================================================
"""

import logging
import re
from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# 1. مسجّل للتشخيص
# ═════════════════════════════════════════════════════════════════════

async def log_all_callbacks(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """يسجّل كل ضغطة زر."""
    query = update.callback_query
    if query:
        cb = query.data or "NO_DATA"
        uid = query.from_user.id
        logger.info(f"🔔 CB: user={uid} data='{cb}'")


# ═════════════════════════════════════════════════════════════════════
# 2. أنماط الإغلاق/الرجوع
# ═════════════════════════════════════════════════════════════════════

CLOSE_PATTERNS = re.compile(
    r".*"
    r"(close|back|cancel|exit|إغلاق|رجوع|خروج|إلغاء)"
    r".*",
    re.IGNORECASE,
)


# ═════════════════════════════════════════════════════════════════════
# 3. معالج زر الإغلاق — يستدعي البوت الأصلي
# ═════════════════════════════════════════════════════════════════════

async def close_button_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    عند ضغط زر الإغلاق:
    1. يحذف الرسالة الحالية
    2. يستدعي البوت الأصلي لعرض قائمة المجموعات
    """
    query = update.callback_query
    cb = query.data or ""
    uid = query.from_user.id

    logger.info(f"🔙 إغلاق: user={uid} cb='{cb}'")

    # 1) إجابة فورية
    try:
        await query.answer()
    except Exception:
        pass

    # 2) احذف الرسالة الحالية
    try:
        await query.message.delete()
    except Exception as e:
        logger.debug(f"حذف فشل: {e}")

    # 3) استدعِ البوت الأصلي لعرض قائمة المجموعات
    original_data = query.data

    try:
        # نحاكي ضغط زر "مجموعاتي" ← البوت الأصلي يعرض القائمة بنفس تصميمه
        query.data = "my_groups"

        from handlers.handlers_callback import CallbackHandlers
        await CallbackHandlers.handle(update, context)
        logger.info("✅ عرضت قائمة المجموعات عبر البوت الأصلي")
        return

    except Exception as e:
        logger.error(f"❌ فشل عرض المجموعات: {e}", exc_info=True)

    finally:
        try:
            query.data = original_data
        except Exception:
            pass

    # 4) Fallback: القائمة الرئيسية
    try:
        from handlers.handlers_command import CommandHandlers
        await CommandHandlers.start(update, context)
        logger.info("✅ عرضت القائمة الرئيسية (fallback)")
    except Exception as e:
        logger.error(f"❌ فشل fallback: {e}")


# ═════════════════════════════════════════════════════════════════════
# 4. التسجيل
# ═════════════════════════════════════════════════════════════════════

def register_nav_fix(application):
    """تسجيل المعالجات."""
    try:
        # مسجّل كل الأزرار (للتشخيص)
        application.add_handler(
            CallbackQueryHandler(log_all_callbacks),
            group=-99,
        )

        # معالج الإغلاق/الرجوع
        application.add_handler(
            CallbackQueryHandler(close_button_handler, pattern=CLOSE_PATTERNS),
            group=-10,
        )

        logger.info("✅ NAV_FIX: تم التسجيل")
        return True
    except Exception as e:
        logger.error(f"❌ NAV_FIX: {e}", exc_info=True)
        return False