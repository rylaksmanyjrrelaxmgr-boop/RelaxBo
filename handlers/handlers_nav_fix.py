#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/handlers_nav_fix.py - إصلاح التنقل + عرض المجموعات
================================================================================
- يلتقط أزرار الإغلاق/الرجوع
- يعرض قائمة المجموعات مباشرة من DB
- يعرض القائمة الرئيسية إذا لزم
================================================================================
"""

import logging
import re
from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import ContextTypes, CallbackQueryHandler

logger = logging.getLogger(__name__)

try:
    from database import DB, TimeUtils
except ImportError:
    DB = None
    TimeUtils = None


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
# 2. أنماط أزرار الإغلاق/الرجوع
# ═════════════════════════════════════════════════════════════════════

CLOSE_PATTERNS = re.compile(
    r"^("
    r"close|cancel|exit|back|return|close_menu|back_menu|"
    r"إغلاق|رجوع|خروج|إلغاء|عودة"
    r")$",
    re.IGNORECASE,
)


# ═════════════════════════════════════════════════════════════════════
# 3. عرض قائمة المجموعات الحقيقية
# ═════════════════════════════════════════════════════════════════════

async def show_groups_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int
):
    """
    يعرض قائمة المجموعات الحقيقية من قاعدة البيانات.
    """
    try:
        # جلب المجموعات
        groups = await DB.get_user_groups(user_id)

        if not groups:
            text = (
                "👥 <b>مجموعاتي</b>\n\n"
                "📭 <i>لا توجد مجموعات بعد</i>\n\n"
                "أضف البوت إلى مجموعة واكتب /syncgroup فيها."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
            ])
        else:
            text = f"👥 <b>مجموعاتي ({len(groups)})</b>\n\n"
            text += "اختر مجموعة للتحكم:\n"
            text += "━━━━━━━━━━━━━━━━\n\n"

            keyboard_buttons = []

            for i, g in enumerate(groups, 1):
                name = g.get("chat_name") or "مجموعة بدون اسم"
                chat_id = g.get("chat_id")
                banned = g.get("banned", 0)

                # اختصار
                if len(name) > 25:
                    name = name[:22] + "..."

                # أيقونة
                icon = "🚫" if banned else "👥"

                text += f"{icon} <b>{i}. {name}</b>\n"
                text += f"   🆔 <code>{chat_id}</code>\n\n"

                # زرّان للمجموعة
                keyboard_buttons.append([
                    InlineKeyboardButton(
                        f"{icon} {name}",
                        callback_data=f"grp_info:{chat_id}"
                    ),
                    InlineKeyboardButton(
                        "⚙️ أمان",
                        callback_data=f"grp_sec:{chat_id}"
                    ),
                ])

            keyboard_buttons.append([
                InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu"),
            ])

            keyboard = InlineKeyboardMarkup(keyboard_buttons)

        # أرسل
        try:
            if update.callback_query:
                await update.callback_query.message.reply_text(
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
        except Exception as e:
            logger.warning(f"reply_text: {e}")
            await context.bot.send_message(
                user_id,
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        return True

    except Exception as e:
        logger.error(f"❌ show_groups_menu: {e}", exc_info=True)
        return False


async def show_main_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int
):
    """يعرض القائمة الرئيسية."""
    try:
        from handlers.handlers_command import CommandHandlers
        await CommandHandlers.start(update, context)
        return True
    except Exception as e:
        logger.debug(f"CommandHandlers.start فشل: {e}")

    # fallback: رسالة بسيطة
    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 مجموعاتي", callback_data="my_groups")],
            [InlineKeyboardButton("📡 قنواتي", callback_data="ch_list")],
            [InlineKeyboardButton("💎 اشتراكي", callback_data="subscription_info")],
            [InlineKeyboardButton("❓ مساعدة", callback_data="help_menu")],
        ])
        await context.bot.send_message(
            user_id,
            "🌿 <b>Relax Manager</b>\n\nاختر من القائمة:",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        return True
    except Exception as e:
        logger.error(f"❌ فشل عرض القائمة الرئيسية: {e}")
        return False


# ═════════════════════════════════════════════════════════════════════
# 4. معالج زر الإغلاق
# ═════════════════════════════════════════════════════════════════════

async def close_button_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """يعالج ضغط زر الإغلاق/الرجوع."""
    query = update.callback_query
    cb = query.data or ""
    uid = query.from_user.id

    logger.info(f"🔙 إغلاق: user={uid} cb='{cb}'")

    # إجابة فورية
    try:
        await query.answer()
    except Exception:
        pass

    # احذف الرسالة الحالية
    try:
        await query.message.delete()
    except Exception as e:
        logger.debug(f"حذف فشل: {e}")

    # ═══ قرّر الوجهة ═══
    # إذا كنا في سياق قناة → ارجع لقائمة القنوات
    if "ch_" in cb or "قناة" in cb or "channel" in cb.lower():
        try:
            from handlers.handlers_channels_list import show_channels_list
            await show_channels_list(update, context)
            logger.info("✅ رجعت لقائمة القنوات")
            return
        except Exception as e:
            logger.debug(f"show_channels_list: {e}")

    # إذا كنا في سياق مجموعة → ارجع لقائمة المجموعات
    if "grp" in cb.lower() or "sec" in cb.lower() or "مجموع" in cb:
        success = await show_groups_menu(update, context, uid)
        if success:
            logger.info("✅ رجعت لقائمة المجموعات")
            return

    # ═══ افتراضي: قائمة المجموعات ═══
    # جربها أولاً (معظم الحالات)
    success = await show_groups_menu(update, context, uid)
    if success:
        logger.info("✅ رجعت لقائمة المجموعات (افتراضي)")
        return

    # فشل → القائمة الرئيسية
    await show_main_menu(update, context, uid)
    logger.info("✅ رجعت للقائمة الرئيسية")


# ═════════════════════════════════════════════════════════════════════
# 5. عرض قائمة المجموعات (عند الضغط على "مجموعاتي")
# ═════════════════════════════════════════════════════════════════════

async def my_groups_button_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """يعالج زر 'مجموعاتي'."""
    query = update.callback_query
    uid = query.from_user.id

    try:
        await query.answer()
    except Exception:
        pass

    # احذف الرسالة القديمة
    try:
        await query.message.delete()
    except Exception:
        pass

    # اعرض القائمة
    await show_groups_menu(update, context, uid)


# ═════════════════════════════════════════════════════════════════════
# 6. التسجيل
# ═════════════════════════════════════════════════════════════════════

def register_nav_fix(application):
    """تسجيل المعالجات."""
    try:
        # 1. مسجّل كل الأزرار (للتشخيص)
        application.add_handler(
            CallbackQueryHandler(log_all_callbacks),
            group=-99,
        )

        # 2. معالج زر "مجموعاتي"
        application.add_handler(
            CallbackQueryHandler(
                my_groups_button_handler,
                pattern=r"^(my_groups|groups|مجموعاتي)$",
            ),
            group=-10,
        )

        # 3. معالج أزرار الإغلاق/الرجوع
        application.add_handler(
            CallbackQueryHandler(close_button_handler, pattern=CLOSE_PATTERNS),
            group=-10,
        )

        logger.info("✅ NAV_FIX: تم التسجيل")
        return True
    except Exception as e:
        logger.error(f"❌ NAV_FIX: {e}", exc_info=True)
        return False