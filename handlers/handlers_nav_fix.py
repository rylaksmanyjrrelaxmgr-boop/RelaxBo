#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/handlers_nav_fix.py - إصلاح التنقل + تشخيص
================================================================================
- يسجّل كل ضغطة زر في السجلات
- يلتقط أزرار الإغلاق/الرجوع
- يعرض قائمة المجموعات الصحيحة

الاستخدام في bot.py:
    from handlers.handlers_nav_fix import register_nav_fix
    register_nav_fix(application)
================================================================================
"""

import logging
import re
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, CallbackQueryHandler

logger = logging.getLogger(__name__)

try:
    from database import DB, TimeUtils
except ImportError:
    DB = None
    TimeUtils = None


# ═════════════════════════════════════════════════════════════════════
# 1. مسجّل شامل لكل الأزرار (للتشخيص)
# ═════════════════════════════════════════════════════════════════════

async def log_all_callbacks(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    يسجّل كل ضغطة زر — لا يفعل شيئاً آخر.
    يعمل في group=-99 (قبل كل شيء).
    """
    query = update.callback_query
    if query:
        cb = query.data or "NO_DATA"
        uid = query.from_user.id
        msg_id = query.message.message_id if query.message else "?"
        logger.info(f"🔔 CB: user={uid} msg={msg_id} data='{cb}'")


# ═════════════════════════════════════════════════════════════════════
# 2. معالج زر "إغلاق" / "رجوع"
# ═════════════════════════════════════════════════════════════════════

CLOSE_PATTERNS = re.compile(
    r"^("
    r"close|cancel|exit|back|return|close_menu|back_menu|"
    r"إغلاق|رجوع|خروج|إلغاء|عودة"
    r")$",
    re.IGNORECASE,
)


async def close_button_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    يعالج ضغط زر الإغلاق/الرجوع.
    
    1. يحذف الرسالة الحالية
    2. يعرض قائمة المجموعات إن أمكن
    3. وإلا يعرض القائمة الرئيسية
    """
    query = update.callback_query
    cb = query.data or ""
    uid = query.from_user.id

    logger.info(f"🔙 إغلاق: user={uid} cb='{cb}'")

    # إجابة فورية
    try:
        await query.answer()
    except Exception:
        pass

    # احذف الرسالة
    try:
        await query.message.delete()
    except Exception as e:
        logger.debug(f"حذف فشل: {e}")

    # جرّب عرض قائمة المجموعات
    try:
        from handlers.handlers_command import CommandHandlers

        # ابحث عن أول دالة متاحة
        for name in ("groups", "my_groups", "groups_command", "show_groups"):
            method = getattr(CommandHandlers, name, None)
            if method and callable(method):
                try:
                    await method(update, context)
                    logger.info(f"✅ عرضت القائمة عبر {name}")
                    return
                except Exception as e:
                    logger.debug(f"{name} فشل: {e}")
                    continue
    except ImportError:
        pass

    # فشل → استخدم القائمة الرئيسية
    try:
        from handlers.handlers_command import CommandHandlers
        await CommandHandlers.start(update, context)
    except Exception as e:
        logger.error(f"❌ فشل عرض القائمة الرئيسية: {e}")
        try:
            await context.bot.send_message(
                uid,
                "🌿 <b>Relax Manager</b>\n\nاختر من القائمة:",
                parse_mode="HTML",
            )
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════
# 3. التسجيل
# ═════════════════════════════════════════════════════════════════════

def register_nav_fix(application):
    """تسجيل المعالجات."""
    try:
        # 1. مسجّل كل الأزرار (group=-99 — قبل كل شيء)
        application.add_handler(
            CallbackQueryHandler(log_all_callbacks),
            group=-99,
        )

        # 2. معالج إغلاق/رجوع (group=-10)
        application.add_handler(
            CallbackQueryHandler(close_button_handler, pattern=CLOSE_PATTERNS),
            group=-10,
        )

        logger.info("✅ NAV_FIX: تم التسجيل")
        return True
    except Exception as e:
        logger.error(f"❌ NAV_FIX: {e}", exc_info=True)
        return False