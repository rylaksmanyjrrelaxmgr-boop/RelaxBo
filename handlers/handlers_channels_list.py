#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_channels_list.py - واجهة قائمة القنوات مع حالتها
================================================================================
- عرض كل القنوات مع إحصائياتها
- تبديل القناة النشطة
- حذف قناة (مع تأكيد)
- إعادة تدوير المنشورات
- تعديل الجدولة
- عرض تفاصيل قناة

الاستخدام في bot.py:
    from handlers.handlers_channels_list import register_channels_list_handlers
    register_channels_list_handlers(application)
================================================================================
"""

import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, CallbackQueryHandler

logger = logging.getLogger(__name__)


# =====================================================================
# استيراد آمن (مع fallback)
# =====================================================================

try:
    from database import DB, TimeUtils
except ImportError:
    logger.error("❌ فشل استيراد database.py")
    DB = None
    TimeUtils = None


# زر الرجوع — مع fallback إذا لم يكن موجوداً
try:
    from utils.keyboards import get_back_button
except (ImportError, AttributeError):
    def get_back_button():
        return InlineKeyboardButton("↩️ رجوع", callback_data="main_menu")


# =====================================================================
# 1. عرض قائمة القنوات
# =====================================================================

async def show_channels_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    عرض قائمة كل القنوات مع حالتها.
    يمكن استدعاؤها من:
    - زر في القائمة الرئيسية (callback_data="ch_list")
    - /channels
    """
    user_id = update.effective_user.id

    # جلب القنوات مع الإحصائيات
    channels = await _get_channels_with_stats(user_id)

    if not channels:
        text = (
            "📭 <b>لا توجد قنوات</b>\n\n"
            "أضف أول قناة لك بالنقر على زر <b>➕ إضافة قناة</b>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة قناة", callback_data="add_channel")],
            [get_back_button()],
        ])
    else:
        active_channel_id = await DB.get_active_channel(user_id)
        text = _build_channels_text(channels, active_channel_id)
        keyboard = _build_channels_keyboard(channels, active_channel_id)

    # إرسال أو تعديل
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        try:
            await update.callback_query.edit_message_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"edit_message_text: {e}")
            try:
                await update.callback_query.message.reply_text(
                    text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
            except Exception as e2:
                logger.error(f"reply_text fallback: {e2}")
    else:
        try:
            await update.message.reply_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"reply_text: {e}")


async def _get_channels_with_stats(user_id: int):
    """جلب كل قنوات المستخدم مع إحصائياتها في استعلام واحد."""
    query = """
        SELECT 
            uc.id AS channel_db_id,
            uc.channel_id,
            uc.channel_name,
            uc.banned,
            uc.created_at,
            (SELECT COUNT(*) FROM posts p 
             WHERE p.channel_db_id = uc.id AND p.published = 0
            ) AS unpublished,
            (SELECT COUNT(*) FROM posts p 
             WHERE p.channel_db_id = uc.id AND p.published = 1
            ) AS published,
            (SELECT MAX(next_publish_date) FROM schedule s 
             WHERE s.channel_db_id = uc.id
            ) AS next_publish
        FROM user_channels uc
        WHERE uc.user_id = ?
        ORDER BY uc.created_at DESC
    """
    try:
        return await DB.fetchall(query, (user_id,))
    except Exception as e:
        logger.error(f"❌ _get_channels_with_stats: {e}", exc_info=True)
        return []


def _build_channels_text(channels, active_channel_id) -> str:
    """بناء نص قائمة القنوات"""
    lines = [f"📡 <b>قنواتك ({len(channels)})</b>\n"]

    total_unpub = sum(c.get("unpublished", 0) or 0 for c in channels)
    total_pub = sum(c.get("published", 0) or 0 for c in channels)

    lines.append(f"📥 إجمالي غير منشور: <b>{total_unpub}</b>")
    lines.append(f"📤 إجمالي منشور: <b>{total_pub}</b>\n")
    lines.append("─" * 30 + "\n")

    for i, ch in enumerate(channels, 1):
        ch_db_id = ch["channel_db_id"]
        name = ch.get("channel_name") or "قناة بدون اسم"
        unpublished = ch.get("unpublished", 0) or 0
        published = ch.get("published", 0) or 0
        banned = ch.get("banned", 0)

        # أيقونة الحالة
        if banned:
            icon = "🚫"
            status = "(محظورة)"
        elif ch_db_id == active_channel_id:
            icon = "🟢"
            status = "(نشطة)"
        else:
            icon = "⚪"
            status = ""

        # اختصار الاسم
        if len(name) > 25:
            name = name[:22] + "..."

        lines.append(
            f"{icon} <b>{i}. {name}</b> {status}\n"
            f"   📥 {unpublished} | 📤 {published}\n"
        )

    return "\n".join(lines)


def _build_channels_keyboard(channels, active_channel_id):
    """
    بناء لوحة الأزرار.
    كل قناة = صف واحد بزرين:
    - ✅/⚪ اختيار القناة
    - ℹ️ تفاصيل
    """
    keyboard = []

    for ch in channels:
        ch_db_id = ch["channel_db_id"]
        name = ch.get("channel_name") or "قناة"

        # اختصار الاسم
        if len(name) > 20:
            name = name[:18] + "..."

        # أيقونة الحالة
        if ch.get("banned", 0):
            select_icon = "🚫"
        elif ch_db_id == active_channel_id:
            select_icon = "✅"
        else:
            select_icon = "⚪"

        # أزرار القناة
        keyboard.append([
            InlineKeyboardButton(
                f"{select_icon} {name}",
                callback_data=f"ch_select:{ch_db_id}"
            ),
            InlineKeyboardButton(
                "ℹ️",
                callback_data=f"ch_info:{ch_db_id}"
            ),
        ])

    # أزرار عامة
    keyboard.append([
        InlineKeyboardButton("➕ إضافة قناة", callback_data="add_channel"),
    ])
    keyboard.append([
        InlineKeyboardButton("🗑️ حذف قناة", callback_data="ch_delete_menu"),
    ])
    keyboard.append([get_back_button()])

    return InlineKeyboardMarkup(keyboard)


# =====================================================================
# 2. اختيار قناة (تعيينها نشطة)
# =====================================================================

async def channel_select_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """عند الضغط على قناة لتعيينها نشطة"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return

    # التحقق من الملكية
    owns = await DB.is_channel_owner(user_id, ch_db_id)
    if not owns:
        await query.answer("⚠️ لا تملك هذه القناة", show_alert=True)
        return

    # تعيين نشطة
    success = await DB.set_active_channel(user_id, ch_db_id)
    if success:
        await query.answer("✅ تم تعيينها كقناة نشطة")
        # تحديث القائمة
        await show_channels_list(update, context)
    else:
        await query.answer("⚠️ فشل التحديث", show_alert=True)


# =====================================================================
# 3. تفاصيل قناة
# =====================================================================

async def channel_info_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """عند الضغط على ℹ️ - عرض تفاصيل القناة"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return

    # جلب القناة
    ch = await DB.get_channel_by_id(user_id, ch_db_id)
    if not ch:
        await query.answer("⚠️ القناة غير موجودة", show_alert=True)
        return

    # جلب الإحصائيات
    stats = await DB.get_channel_stats(user_id, ch_db_id)
    active_channel_id = await DB.get_active_channel(user_id)

    # جلب الجدولة
    try:
        schedule = await DB.get_schedule(ch_db_id)
        interval_min = schedule.get("interval_minutes", 12) if schedule else 12
        next_publish = schedule.get("next_publish_date") if schedule else None
    except Exception:
        interval_min = 12
        next_publish = None

    # بناء النص
    name = ch.get("channel_name", "قناة بدون اسم")
    ch_telegram_id = ch.get("channel_id", "غير معروف")
    banned = ch.get("banned", 0)

    status_icon = "🚫 محظورة" if banned else (
        "🟢 نشطة" if ch_db_id == active_channel_id else "⚪ غير نشطة"
    )

    text = (
        f"📡 <b>{name}</b>\n\n"
        f"<b>المعرف:</b> <code>{ch_telegram_id}</code>\n"
        f"<b>الحالة:</b> {status_icon}\n\n"
        f"<b>📊 الإحصائيات:</b>\n"
        f"├ 📝 إجمالي: <b>{stats.get('total', 0)}</b>\n"
        f"├ 📥 غير منشور: <b>{stats.get('unpublished', 0)}</b>\n"
        f"└ 📤 منشور: <b>{stats.get('published', 0)}</b>\n\n"
        f"<b>⚙️ الجدولة:</b>\n"
        f"├ ⏱ كل: <b>{interval_min} دقيقة</b>\n"
        f"└ 📅 التالي: <b>{_format_date(next_publish)}</b>"
    )

    # الأزرار
    buttons = []

    if ch_db_id != active_channel_id and not banned:
        buttons.append([
            InlineKeyboardButton(
                "✅ تعيين نشطة",
                callback_data=f"ch_select:{ch_db_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "⚙️ تعديل الجدولة",
            callback_data=f"ch_schedule:{ch_db_id}"
        ),
    ])
    buttons.append([
        InlineKeyboardButton(
            "♻️ إعادة تدوير الآن",
            callback_data=f"ch_recycle:{ch_db_id}"
        ),
    ])
    buttons.append([
        InlineKeyboardButton(
            "🗑️ حذف القناة",
            callback_data=f"ch_delete_confirm:{ch_db_id}"
        ),
    ])
    buttons.append([
        InlineKeyboardButton("↩️ رجوع للقائمة", callback_data="ch_list")
    ])

    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"edit_message_text: {e}")


def _format_date(dt_value) -> str:
    """تنسيق التاريخ للتوقيت المحلي (مكة +3)"""
    if not dt_value:
        return "غير محدد"
    try:
        dt = TimeUtils.safe_parse_iso(dt_value)
        if not dt:
            return "غير محدد"
        from datetime import timedelta
        local_dt = dt + timedelta(hours=3)
        return local_dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(dt_value)


# =====================================================================
# 4. قائمة حذف القنوات
# =====================================================================

async def channel_delete_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """عرض قائمة القنوات للحذف"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    channels = await _get_channels_with_stats(user_id)
    if not channels:
        await query.answer("📭 لا توجد قنوات", show_alert=True)
        return

    text = (
        "🗑️ <b>حذف قناة</b>\n\n"
        "اختر القناة التي تريد حذفها:\n"
        "<i>⚠️ الحذف لا يمكن التراجع عنه، وسيتم حذف كل المنشورات!</i>"
    )

    buttons = []
    for ch in channels:
        ch_db_id = ch["channel_db_id"]
        name = ch.get("channel_name") or "قناة"
        if len(name) > 25:
            name = name[:22] + "..."

        buttons.append([
            InlineKeyboardButton(
                f"🗑️ {name}",
                callback_data=f"ch_delete_confirm:{ch_db_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton("↩️ رجوع", callback_data="ch_list")
    ])

    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"edit_message_text: {e}")


async def channel_delete_confirm_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """تأكيد الحذف"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return

    ch = await DB.get_channel_by_id(user_id, ch_db_id)
    if not ch:
        await query.answer("⚠️ القناة غير موجودة", show_alert=True)
        return

    name = ch.get("channel_name", "قناة")
    stats = await DB.get_channel_stats(user_id, ch_db_id)

    text = (
        f"⚠️ <b>تأكيد الحذف</b>\n\n"
        f"هل أنت متأكد من حذف القناة:\n"
        f"<b>{name}</b>\n\n"
        f"<b>سيتم حذف:</b>\n"
        f"├ 📝 {stats.get('total', 0)} منشور\n"
        f"├ 📥 {stats.get('unpublished', 0)} غير منشور\n"
        f"└ 📤 {stats.get('published', 0)} منشور\n\n"
        f"<i>⚠️ لا يمكن التراجع!</i>"
    )

    buttons = [
        [
            InlineKeyboardButton(
                "🗑️ نعم، احذف",
                callback_data=f"ch_delete_execute:{ch_db_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ إلغاء",
                callback_data=f"ch_info:{ch_db_id}"
            ),
        ],
    ]

    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"edit_message_text: {e}")


async def channel_delete_execute_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """تنفيذ الحذف"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("⏳ جاري الحذف...")

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return

    success = await DB.delete_channel(user_id, ch_db_id)
    if success:
        try:
            await query.answer("✅ تم الحذف", show_alert=True)
        except Exception:
            pass
        # رجوع لقائمة القنوات
        await show_channels_list(update, context)
    else:
        await query.answer("⚠️ فشل الحذف", show_alert=True)


# =====================================================================
# 5. إعادة تدوير قناة
# =====================================================================

async def channel_recycle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """إعادة تدوير المنشورات لقناة محددة"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer("⏳ جاري إعادة التدوير...")

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return

    # التحقق من الملكية
    owns = await DB.is_channel_owner(user_id, ch_db_id)
    if not owns:
        await query.answer("⚠️ لا تملك هذه القناة", show_alert=True)
        return

    # إعادة التدوير
    count = await DB.reset_posts(user_id, ch_db_id)

    try:
        await query.answer(
            f"✅ تم إعادة تدوير {count} منشور",
            show_alert=True
        )
    except Exception:
        pass

    # رجوع لتفاصيل القناة
    await channel_info_callback(update, context)


# =====================================================================
# 6. تعديل الجدولة
# =====================================================================

async def channel_schedule_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """عرض خيارات الجدولة لقناة"""
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        return

    # التحقق من الملكية
    owns = await DB.is_channel_owner(user_id, ch_db_id)
    if not owns:
        await query.answer("⚠️ لا تملك هذه القناة", show_alert=True)
        return

    try:
        schedule = await DB.get_schedule(ch_db_id)
        current = schedule.get("interval_minutes", 12) if schedule else 12
    except Exception:
        current = 12

    text = (
        f"⚙️ <b>تعديل الجدولة</b>\n\n"
        f"التردد الحالي: <b>{current} دقيقة</b>\n\n"
        f"اختر التردد الجديد:"
    )

    intervals = [5, 10, 15, 30, 60, 120, 360, 720, 1440]
    buttons = []
    row = []

    for minutes in intervals:
        if minutes < 60:
            label = f"{minutes} د"
        elif minutes < 1440:
            label = f"{minutes // 60} س"
        else:
            label = "يوم"

        row.append(InlineKeyboardButton(
            label,
            callback_data=f"ch_sched_set:{ch_db_id}:{minutes}"
        ))

        if len(row) == 3:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton("↩️ رجوع", callback_data=f"ch_info:{ch_db_id}")
    ])

    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"edit_message_text: {e}")


async def channel_schedule_set_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """تعيين التردد الجديد"""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        parts = query.data.split(":")
        ch_db_id = int(parts[1])
        minutes = int(parts[2])
    except (ValueError, IndexError):
        await query.answer("⚠️ خطأ في البيانات", show_alert=True)
        return

    owns = await DB.is_channel_owner(user_id, ch_db_id)
    if not owns:
        await query.answer("⚠️ لا تملك هذه القناة", show_alert=True)
        return

    try:
        success = await DB.update_schedule(
            ch_db_id,
            schedule_type="interval_minutes",
            interval_minutes=minutes,
        )
        if success:
            try:
                await DB.update_next_publish(ch_db_id)
            except Exception:
                pass

        if success:
            await query.answer(f"✅ التردد الجديد: {minutes} دقيقة")
            await channel_info_callback(update, context)
        else:
            await query.answer("⚠️ فشل التحديث", show_alert=True)
    except Exception as e:
        logger.error(f"❌ channel_schedule_set: {e}", exc_info=True)
        await query.answer("⚠️ خطأ غير متوقع", show_alert=True)


# =====================================================================
# 7. تسجيل كل الـ handlers
# =====================================================================

def register_channels_list_handlers(application):
    """
    تسجيل كل handlers قائمة القنوات.
    استدعِ هذه الدالة في bot.py بعد تهيئة التطبيق.
    """
    try:
        application.add_handler(
            CallbackQueryHandler(show_channels_list, pattern=r"^ch_list$")
        )
        application.add_handler(
            CallbackQueryHandler(channel_select_callback, pattern=r"^ch_select:")
        )
        application.add_handler(
            CallbackQueryHandler(channel_info_callback, pattern=r"^ch_info:")
        )
        application.add_handler(
            CallbackQueryHandler(
                channel_delete_menu_callback, pattern=r"^ch_delete_menu$"
            )
        )
        application.add_handler(
            CallbackQueryHandler(
                channel_delete_confirm_callback, pattern=r"^ch_delete_confirm:"
            )
        )
        application.add_handler(
            CallbackQueryHandler(
                channel_delete_execute_callback, pattern=r"^ch_delete_execute:"
            )
        )
        application.add_handler(
            CallbackQueryHandler(
                channel_recycle_callback, pattern=r"^ch_recycle:"
            )
        )
        application.add_handler(
            CallbackQueryHandler(
                channel_schedule_callback, pattern=r"^ch_schedule:"
            )
        )
        application.add_handler(
            CallbackQueryHandler(
                channel_schedule_set_callback, pattern=r"^ch_sched_set:"
            )
        )

        logger.info("✅ تم تسجيل handlers قائمة القنوات")
        return True
    except Exception as e:
        logger.error(f"❌ فشل تسجيل handlers: {e}", exc_info=True)
        return False