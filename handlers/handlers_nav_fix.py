#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/handlers_nav_fix.py - إصلاح أزرار الرجوع/الإغلاق
================================================================================
- يلتقط أزرار "إغلاق" و"رجوع" و"رجوع للخلف"
- يوجهها للقائمة الصحيحة (المجموعات، الأمان، إلخ)
- يعمل مع الملفات الموجودة — لا يُعدّلها

الاستخدام في bot.py:
    from handlers.handlers_nav_fix import register_nav_fix
    register_nav_fix(application)  # قبل CallbackHandlers.handle
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
# أنماط الأزرار التي نلتقطها
# ═════════════════════════════════════════════════════════════════════

CLOSE_PATTERNS = re.compile(
    r"^("
    r"close|exit|cancel|back|return|"
    r"close_menu|menu_close|back_menu|"
    r"close_security|sec_close|security_close|"
    r"close_groups|groups_close|back_to_groups|"
    r"إغلاق|رجوع|خروج|إلغاء|"
    r"cancel_\w+|close_\w+|back_\w+"
    r")$",
    re.IGNORECASE,
)


# ═════════════════════════════════════════════════════════════════════
# المعالج الرئيسي
# ═════════════════════════════════════════════════════════════════════

async def nav_interceptor(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    يعترض أزرار الإغلاق/الرجوع ويوجهها للقائمة الصحيحة.
    """
    query = update.callback_query
    if not query:
        return

    callback_data = query.data or ""
    user_id = query.from_user.id

    # طباعة للتشخيص
    logger.info(f"🔙 NAV: {user_id} ضغط {callback_data}")

    # ═══ 1. حفظ سياق التنقل ═══
    # إذا ضغط "أمان" → احفظ أننا في سياق "مجموعة"
    if "security" in callback_data.lower() or "أمان" in callback_data:
        if context.user_data is not None:
            context.user_data["nav_last_parent"] = "groups"
            logger.info(f"   📌 حفظ: المستخدم في سياق المجموعات")

    # ═══ 2. تحديد الوجهة ═══
    target = "groups"  # افتراضي: المجموعات

    if context.user_data:
        target = context.user_data.get("nav_last_parent", "groups")

    logger.info(f"   🎯 الوجهة: {target}")

    # ═══ 3. الإجابة على الـ callback ═══
    try:
        await query.answer()
    except Exception:
        pass

    # ═══ 4. حذف الرسالة الحالية ═══
    try:
        await query.message.delete()
    except Exception as e:
        logger.debug(f"حذف الرسالة: {e}")

    # ═══ 5. إظهار الوجهة ═══
    if target == "groups":
        shown = await _show_groups_menu(update, context, user_id)
        if not shown:
            await _show_main_menu(update, context, user_id)
    else:
        await _show_main_menu(update, context, user_id)


# ═════════════════════════════════════════════════════════════════════
# دوال مساعدة
# ═════════════════════════════════════════════════════════════════════

async def _show_groups_menu(update, context, user_id) -> bool:
    """محاولة عرض قائمة المجموعات."""
    # محاولة 1: CommandHandlers.groups
    try:
        from handlers.handlers_command import CommandHandlers

        for method_name in ("groups", "my_groups", "show_groups", "groups_command"):
            method = getattr(CommandHandlers, method_name, None)
            if method and callable(method):
                try:
                    await method(update, context)
                    logger.info(f"   ✅ عرضت القائمة عبر CommandHandlers.{method_name}")
                    return True
                except Exception as e:
                    logger.debug(f"فشل {method_name}: {e}")
                    continue
    except ImportError:
        pass

    # محاولة 2: استدعاء زر callback يعرض المجموعات
    try:
        # نحاكي ضغطة زر "مجموعاتي" إذا كان موجوداً
        fake_callback_data = "my_groups"

        # ابحث عن handler يعالج my_groups
        # بدلاً من ذلك، أرسل رسالة جديدة
        await context.bot.send_message(
            user_id,
            "👥 <b>مجموعاتي</b>\n\n"
            "أرسل /groups لعرض قائمة المجموعات",
            parse_mode="HTML",
        )
        logger.info("   ⚠️ أرسلت رسالة نصية بدل القائمة")
        return True
    except Exception as e:
        logger.debug(f"فشل إرسال رسالة المجموعات: {e}")

    return False


async def _show_main_menu(update, context, user_id) -> bool:
    """عرض القائمة الرئيسية."""
    try:
        from handlers.handlers_command import CommandHandlers
        await CommandHandlers.start(update, context)
        return True
    except Exception as e:
        logger.debug(f"فشل عرض القائمة الرئيسية: {e}")

    try:
        await context.bot.send_message(
            user_id,
            "🌿 <b>Relax Manager</b>\n\nأرسل /start",
            parse_mode="HTML",
        )
        return True
    except Exception:
        return False


# ═════════════════════════════════════════════════════════════════════
# التسجيل
# ═════════════════════════════════════════════════════════════════════

def register_nav_fix(application):
    """تسجيل معالج التنقل."""
    try:
        # group=-10 → يعمل قبل كل شيء
        application.add_handler(
            CallbackQueryHandler(
                nav_interceptor,
                pattern=CLOSE_PATTERNS,
            ),
            group=-10,
        )
        logger.info("✅ NAV_FIX: معالج الإغلاق/الرجوع مُسجّل")
        return True
    except Exception as e:
        logger.error(f"❌ NAV_FIX: {e}", exc_info=True)
        return False