#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_channels_list.py - واجهة قائمة القنوات مع حالتها (v2.0.2)
================================================================================
🆕 v2.0.2 (إصلاح اعتراض الرسائل):
    ✅ add_channel_from_message: لا يعترض إذا كان المستخدم في حالة معلقة
       (WAIT_UPDATE_CH, WAIT_CHANNEL, WAIT_LOG_CH, ...)
    ✅ _user_has_pending_state: helper جديد لفحص الحالة
    ✅ add_channel_redirect_callback: يصفّر الحالة عند الضغط على الزر
       لتفادي تعارضات مع عمليات سابقة

🆕 v2.0.1 (إصلاح answer() المزدوج في 4 دوال):
    ✅ channel_delete_menu_callback: answer بعد فحص القنوات
    ✅ channel_delete_confirm_callback: answer بعد فحص القناة
    ✅ channel_schedule_callback: answer بعد فحص الملكية
    ✅ channel_delete_execute_callback: answer بالنتيجة النهائية فقط

🆕 v2.0.0 (إصلاح أخطاء حرجة):
    ✅ إصلاح query.answer() المزدوج في recycle/schedule_set
    ✅ استخراج _render_channel_info (helper مشترك)
    ✅ حماية DB=None في كل handler
    ✅ تضييق regex t.me ليطابق الروابط النقية فقط
    ✅ stats/channel_info محميّة ضد None
    ✅ استعلام واحد بدل اثنين في posts_add_callback
    ✅ نقل timedelta إلى imports المستوى الأعلى
    ✅ تبسيط _send_main_menu_fallback
    ✅ توحيد معالجة الأخطاء
================================================================================
"""

import logging
import re
from datetime import timedelta
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, MessageHandler, filters
)

logger = logging.getLogger(__name__)


# =====================================================================
# استيراد آمن
# =====================================================================

try:
    from database import DB, TimeUtils
except ImportError:
    logger.error("❌ فشل استيراد database.py")
    DB = None
    TimeUtils = None


# ✅ v2.0.2: استيراد StateManager و UserState لفحص الحالة
try:
    from utils import StateManager, UserState
    _STATE_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ StateManager/UserState غير متاح")
    StateManager = None
    UserState = None
    _STATE_AVAILABLE = False


try:
    from utils.keyboards import get_back_button
except (ImportError, AttributeError):
    def get_back_button():
        return InlineKeyboardButton("↩️ رجوع", callback_data="main_menu")


# =====================================================================
# 0. أدوات مساعدة
# =====================================================================

def _db_ready() -> bool:
    """✅ v2.0.0: فحص موحّد لجهوزية DB."""
    if DB is None:
        logger.error("❌ DB غير مهيأة — تخطي handler")
        return False
    return True


def _user_has_pending_state(user_id: int) -> bool:
    """
    ✅ v2.0.2: هل المستخدم في حالة معلقة (غير NONE)؟

    تستخدم لمنع اعتراض الرسائل عندما يكون المستخدم في:
    - WAIT_UPDATE_CH (تعيين قناة التحديثات)
    - WAIT_LOG_CH (تعيين قناة السجل)
    - WAIT_CHANNEL (إضافة قناة يدوياً)
    - WAIT_FORCE (الاشتراك الإجباري)
    - ... إلخ
    """
    if not _STATE_AVAILABLE or StateManager is None:
        return False
    try:
        state = StateManager.get(user_id)
        if UserState is not None:
            return state != UserState.NONE
        return state is not None
    except Exception as e:
        logger.debug(f"_user_has_pending_state({user_id}): {e}")
        return False


async def _safe_answer(query, text: str = None, show_alert: bool = False) -> None:
    """✅ v2.0.0: answer() آمن (يُتجاهل إذا أُجيب مسبقاً)."""
    try:
        if text is not None:
            await query.answer(text, show_alert=show_alert)
        else:
            await query.answer()
    except Exception as e:
        logger.debug(f"_safe_answer: {e}")


def _format_date(dt_value) -> str:
    """تنسيق التاريخ للتوقيت المحلي (مكة +3)."""
    if not dt_value:
        return "غير محدد"
    if TimeUtils is None:
        return str(dt_value)
    try:
        dt = TimeUtils.safe_parse_iso(dt_value)
        if not dt:
            return "غير محدد"
        local_dt = dt + timedelta(hours=3)
        return local_dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(dt_value)


async def _get_active_channel_id(user_id: int) -> Optional[int]:
    """
    ✅ v2.0.0: استعلام مباشر بدل الاعتماد على DB.get_active_channel.
    """
    try:
        return await DB.fetchval(
            "SELECT active_channel FROM users WHERE user_id = ?",
            (user_id,),
            default=None,
        )
    except Exception as e:
        logger.debug(f"_get_active_channel_id({user_id}): {e}")
        return None


# =====================================================================
# 1. عرض قائمة القنوات
# =====================================================================

async def show_channels_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة كل القنوات مع حالتها."""
    if not _db_ready():
        return

    user_id = update.effective_user.id
    channels = await _get_channels_with_stats(user_id)

    if not channels:
        text = (
            "📭 <b>لا توجد قنوات</b>\n\n"
            "أضف أول قناة لك بالنقر على زر <b>➕ إضافة قناة</b>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة قناة", callback_data="add_channel")],
            [InlineKeyboardButton("↩️ رجوع للقائمة الرئيسية", callback_data="main_menu")],
        ])
    else:
        active_channel_id = await _get_active_channel_id(user_id)
        text = _build_channels_text(channels, active_channel_id)
        keyboard = _build_channels_keyboard(channels, active_channel_id)

    if update.callback_query:
        await _safe_answer(update.callback_query)
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=keyboard, parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"edit_message_text: {e}")
            try:
                await update.callback_query.message.reply_text(
                    text, reply_markup=keyboard, parse_mode="HTML",
                )
            except Exception as e2:
                logger.error(f"reply_text fallback: {e2}")
    else:
        try:
            await update.message.reply_text(
                text, reply_markup=keyboard, parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"reply_text: {e}")


async def _get_channels_with_stats(user_id: int):
    """جلب كل قنوات المستخدم مع إحصائياتها."""
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
            (SELECT s.next_publish_date FROM schedule s
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
    """بناء نص قائمة القنوات."""
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

        if banned:
            icon = "🚫"
            status = "(محظورة)"
        elif ch_db_id == active_channel_id:
            icon = "🟢"
            status = "(نشطة)"
        else:
            icon = "⚪"
            status = ""

        if len(name) > 25:
            name = name[:22] + "..."

        lines.append(
            f"{icon} <b>{i}. {name}</b> {status}\n"
            f"   📥 {unpublished} | 📤 {published}\n"
        )

    return "\n".join(lines)


def _build_channels_keyboard(channels, active_channel_id):
    """بناء لوحة الأزرار."""
    keyboard = []

    for ch in channels:
        ch_db_id = ch["channel_db_id"]
        name = ch.get("channel_name") or "قناة"

        if len(name) > 20:
            name = name[:18] + "..."

        if ch.get("banned", 0):
            select_icon = "🚫"
        elif ch_db_id == active_channel_id:
            select_icon = "✅"
        else:
            select_icon = "⚪"

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

    keyboard.append([
        InlineKeyboardButton("➕ إضافة قناة", callback_data="add_channel"),
    ])
    keyboard.append([
        InlineKeyboardButton("🗑️ حذف قناة", callback_data="ch_delete_menu"),
    ])
    keyboard.append([
        InlineKeyboardButton("↩️ رجوع للقائمة الرئيسية", callback_data="main_menu"),
    ])

    return InlineKeyboardMarkup(keyboard)


# =====================================================================
# 2. اختيار قناة (تعيينها نشطة)
# =====================================================================

async def channel_select_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """عند الضغط على قناة لتعيينها نشطة."""
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    try:
        owns = await DB.is_channel_owner(user_id, ch_db_id)
        if not owns:
            await _safe_answer(query, "⚠️ لا تملك هذه القناة", show_alert=True)
            return

        success = await DB.set_active_channel(user_id, ch_db_id)
        if success:
            await _safe_answer(query, "✅ تم تعيينها كقناة نشطة")
            await show_channels_list(update, context)
        else:
            await _safe_answer(query, "⚠️ فشل التحديث", show_alert=True)
    except Exception as e:
        logger.error(f"❌ channel_select: {e}", exc_info=True)
        await _safe_answer(query, "⚠️ خطأ غير متوقع", show_alert=True)


# =====================================================================
# 3. تفاصيل قناة (helper مشترك)
# =====================================================================

async def _render_channel_info(query, user_id: int, ch_db_id: int) -> None:
    """
    ✅ v2.0.0: helper مشترك لعرض تفاصيل القناة.

    يفترض أن query.answer() تم استدعاؤه بالفعل (لا يُعيد الاستدعاء).
    """
    try:
        ch = await DB.get_channel_by_id(user_id, ch_db_id)
        if not ch:
            await _safe_answer(query, "⚠️ القناة غير موجودة", show_alert=True)
            return

        stats = await DB.get_channel_stats(user_id, ch_db_id) or {}
        active_channel_id = await _get_active_channel_id(user_id)

        try:
            schedule = await DB.get_schedule(ch_db_id)
            interval_min = schedule.get("interval_minutes", 12) if schedule else 12
            next_publish = schedule.get("next_publish_date") if schedule else None
        except Exception:
            interval_min = 12
            next_publish = None

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
        buttons.append([
            InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")
        ])

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"❌ _render_channel_info: {e}", exc_info=True)
        try:
            await query.message.reply_text(
                "⚠️ فشل عرض تفاصيل القناة. حاول لاحقاً.",
                parse_mode="HTML",
            )
        except Exception:
            pass


async def channel_info_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """عند الضغط على ℹ️ - عرض تفاصيل القناة."""
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    await _safe_answer(query)
    await _render_channel_info(query, user_id, ch_db_id)


# =====================================================================
# 4. قائمة حذف القنوات
# =====================================================================

async def channel_delete_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    عرض قائمة القنوات للحذف.

    ✅ v2.0.1: answer بعد فحص القنوات (كان مُزدوجاً).
    """
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    channels = await _get_channels_with_stats(user_id)
    if not channels:
        await _safe_answer(query, "📭 لا توجد قنوات", show_alert=True)
        return

    await _safe_answer(query)

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


async def channel_delete_confirm_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    تأكيد الحذف.

    ✅ v2.0.1: answer بعد فحص القناة (كان مُزدوجاً).
    """
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    try:
        ch = await DB.get_channel_by_id(user_id, ch_db_id)
        if not ch:
            await _safe_answer(query, "⚠️ القناة غير موجودة", show_alert=True)
            return

        await _safe_answer(query)

        name = ch.get("channel_name", "قناة")
        stats = await DB.get_channel_stats(user_id, ch_db_id) or {}

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

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"❌ channel_delete_confirm: {e}", exc_info=True)


async def channel_delete_execute_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    تنفيذ الحذف.

    ✅ v2.0.1: answer بالنتيجة النهائية فقط.
    """
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    try:
        success = await DB.delete_channel(user_id, ch_db_id)

        if not success:
            await _safe_answer(query, "⚠️ فشل الحذف", show_alert=True)
            return

        await _safe_answer(query, "✅ تم الحذف", show_alert=True)
        logger.info(f"✅ حُذفت القناة {ch_db_id} بواسطة {user_id}")

        await show_channels_list(update, context)
    except Exception as e:
        logger.error(f"❌ channel_delete_execute: {e}", exc_info=True)
        await _safe_answer(query, "⚠️ خطأ غير متوقع", show_alert=True)


# =====================================================================
# 5. إعادة تدوير قناة
# =====================================================================

async def channel_recycle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    إعادة تدوير المنشورات لقناة محددة.

    ✅ v2.0.0: تم إصلاح answer() المزدوج.
    """
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    try:
        owns = await DB.is_channel_owner(user_id, ch_db_id)
        if not owns:
            await _safe_answer(query, "⚠️ لا تملك هذه القناة", show_alert=True)
            return

        count = await DB.reset_posts(user_id, ch_db_id)

        await _safe_answer(
            query,
            f"✅ تم إعادة تدوير {count} منشور",
            show_alert=True,
        )

        await _render_channel_info(query, user_id, ch_db_id)
    except Exception as e:
        logger.error(f"❌ channel_recycle: {e}", exc_info=True)
        await _safe_answer(query, "⚠️ خطأ غير متوقع", show_alert=True)


# =====================================================================
# 6. تعديل الجدولة
# =====================================================================

async def channel_schedule_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    عرض خيارات الجدولة لقناة.

    ✅ v2.0.1: answer بعد فحص الملكية (كان مُزدوجاً).
    """
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    try:
        owns = await DB.is_channel_owner(user_id, ch_db_id)
        if not owns:
            await _safe_answer(query, "⚠️ لا تملك هذه القناة", show_alert=True)
            return

        await _safe_answer(query)

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

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"❌ channel_schedule: {e}", exc_info=True)


async def channel_schedule_set_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    تعيين التردد الجديد.

    ✅ v2.0.0: تم إصلاح answer() المزدوج.
    """
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        parts = query.data.split(":")
        ch_db_id = int(parts[1])
        minutes = int(parts[2])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    if minutes <= 0 or minutes > 30 * 24 * 60:
        await _safe_answer(query, "⚠️ قيمة غير مسموحة", show_alert=True)
        return

    try:
        owns = await DB.is_channel_owner(user_id, ch_db_id)
        if not owns:
            await _safe_answer(query, "⚠️ لا تملك هذه القناة", show_alert=True)
            return

        success = await DB.update_schedule(
            ch_db_id,
            schedule_type="interval_minutes",
            interval_minutes=minutes,
        )

        if not success:
            await _safe_answer(query, "⚠️ فشل التحديث", show_alert=True)
            return

        try:
            await DB.update_next_publish(ch_db_id)
        except Exception as e:
            logger.debug(f"update_next_publish: {e}")

        await _safe_answer(query, f"✅ التردد الجديد: {minutes} دقيقة")

        await _render_channel_info(query, user_id, ch_db_id)
    except Exception as e:
        logger.error(f"❌ channel_schedule_set: {e}", exc_info=True)
        await _safe_answer(query, "⚠️ خطأ غير متوقع", show_alert=True)


# =====================================================================
# 7. الرجوع للقائمة الرئيسية
# =====================================================================

async def back_to_main_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """الرجوع للقائمة الرئيسية."""
    query = update.callback_query
    await _safe_answer(query)

    try:
        await query.message.delete()
    except Exception as e:
        logger.debug(f"حذف الرسالة: {e}")

    try:
        from handlers.handlers_command import CommandHandlers

        try:
            await CommandHandlers.start(update, context)
            return
        except (AttributeError, TypeError) as e:
            logger.debug(f"CommandHandlers.start فشل: {e}")
    except ImportError as e:
        logger.debug(f"handlers.handlers_command غير متاح: {e}")

    try:
        await _send_main_menu_fallback(context, query.from_user.id)
    except Exception as e:
        logger.error(f"❌ back_to_main_menu fallback: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                query.from_user.id,
                "⚠️ فشل عرض القائمة الرئيسية.\nأرسل /start",
            )
        except Exception:
            pass


async def _send_main_menu_fallback(context, user_id: int):
    """إرسال القائمة الرئيسية بطريقة احتياطية."""
    text = "🌿 <b>Relax Manager</b>\n\nاختر من القائمة:"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 قنواتي", callback_data="ch_list")],
        [InlineKeyboardButton("📋 منشوراتي", callback_data="posts_menu")],
        [InlineKeyboardButton("💎 اشتراكي", callback_data="subscription_info")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings_menu")],
        [InlineKeyboardButton("❓ مساعدة", callback_data="help_menu")],
    ])
    await context.bot.send_message(
        user_id, text, reply_markup=kb, parse_mode="HTML",
    )


# =====================================================================
# 8. إضافة قناة (زر → تعليمات)
# =====================================================================

async def add_channel_redirect_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    عرض تعليمات إضافة قناة.

    ✅ v2.0.2: يصفّر الحالة لتفادي تعارضات مع عمليات سابقة.
    """
    query = update.callback_query
    await _safe_answer(query)

    user_id = query.from_user.id

    # ✅ v2.0.2: تصفير الحالة (لتفادي تعارضات مع WAIT_UPDATE_CH وغيرها)
    if _STATE_AVAILABLE and StateManager is not None:
        try:
            StateManager.clear(user_id)
            logger.debug(
                f"🔄 add_channel_redirect: cleared state for {user_id}"
            )
        except Exception as e:
            logger.debug(f"StateManager.clear({user_id}): {e}")

    if context.user_data is not None:
        context.user_data["awaiting_channel_add"] = True

    try:
        text = (
            "➕ <b>إضافة قناة جديدة</b>\n\n"
            "لإضافة قناة، اختر إحدى الطرق التالية:\n\n"
            "1️⃣ <b>أرسل معرف القناة</b> في المحادثة\n"
            "   مثال: <code>@my_channel</code>\n\n"
            "2️⃣ <b>أعد توجيه رسالة</b> من القناة إلى البوت\n\n"
            "3️⃣ <b>أرسل رابط القناة</b>\n"
            "   مثال: <code>https://t.me/my_channel</code>\n\n"
            "⚠️ <b>مهم:</b> تأكد من أن البوت <b>مشرف</b> في القناة!\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "💡 <i>أرسل الآن اسم القناة أو رابطها للبدء</i>"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ رجوع للقائمة", callback_data="ch_list")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
        ])

        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"❌ add_channel_redirect: {e}", exc_info=True)


# =====================================================================
# 9. معالج الرسائل النصية لإضافة قناة
# =====================================================================

# ✅ v2.0.0: regex مُضيَّق — يطابق فقط @channel أو t.me/channel منفردين
_USERNAME_RE = re.compile(r"^@([a-zA-Z0-9_]{4,})$")
_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?t\.me/([a-zA-Z0-9_]{4,})/?$",
    re.IGNORECASE,
)


def _extract_channel_username(text: str) -> Optional[str]:
    """استخراج اسم القناة من النص (فقط إذا كان النص قناة نقية)."""
    text = text.strip()
    m = _USERNAME_RE.match(text)
    if m:
        return m.group(1)
    m = _URL_RE.match(text)
    if m:
        return m.group(1)
    return None


async def add_channel_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    معالج الرسائل النصية لإضافة قناة.

    ✅ v2.0.2: لا يعترض الرسالة إذا كان المستخدم في حالة معلقة.

    حالات لا يعترض فيها:
    - WAIT_UPDATE_CH (تعيين قناة التحديثات)
    - WAIT_LOG_CH (تعيين قناة السجل)
    - WAIT_CHANNEL (إضافة قناة يدوياً)
    - WAIT_FORCE (الاشتراك الإجباري)
    - WAIT_BROADCAST, WAIT_UPDATE, ...
    """
    if not _db_ready():
        return

    message = update.message
    if not message or not message.text:
        return

    user_id = message.from_user.id

    # ═══════════════════════════════════════════════════════════════
    # ✅ v2.0.2: لا تعترض إذا كان المستخدم في حالة معلقة
    # ═══════════════════════════════════════════════════════════════
    if _user_has_pending_state(user_id):
        logger.debug(
            f"⏭️ add_channel_from_message: تجاهل — "
            f"المستخدم {user_id} في حالة معلقة"
        )
        return

    text = message.text.strip()

    channel_username = _extract_channel_username(text)
    if not channel_username:
        if context.user_data and context.user_data.get("awaiting_channel_add"):
            try:
                await message.reply_text(
                    "⚠️ <b>صيغة غير صحيحة</b>\n\n"
                    "أرسل:\n"
                    "• <code>@my_channel</code>\n"
                    "• <code>https://t.me/my_channel</code>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        return

    logger.info(f"📥 محاولة إضافة قناة: @{channel_username} من {user_id}")

    processing_msg = None
    try:
        processing_msg = await message.reply_text(
            f"⏳ جاري التحقق من <code>@{channel_username}</code>...",
            parse_mode="HTML",
        )
    except Exception:
        pass

    # ═══ فحص المستخدم ═══
    try:
        user = await DB.get_user_full_data(user_id, include_stats=True)
        if not user:
            await _edit_or_send(
                processing_msg, message,
                "⚠️ الرجاء إرسال /start أولاً."
            )
            return

        if user.get("banned"):
            await _edit_or_send(
                processing_msg, message,
                "🚫 أنت محظور من استخدام البوت."
            )
            return

        if not user.get("has_subscription"):
            await _edit_or_send(
                processing_msg, message,
                "💎 <b>يجب أن يكون لديك اشتراك نشط</b>\n\n"
                "استخدم /subscribe للاشتراك."
            )
            return

        channels_count = user.get("channels_count", 0)
        active_sub = await DB.get_active_subscription(user_id)
        if active_sub:
            max_channels = active_sub.get("max_channels", 0)
            if channels_count >= max_channels:
                await _edit_or_send(
                    processing_msg, message,
                    f"⚠️ <b>وصلت للحد الأقصى</b>\n\n"
                    f"عدد قنواتك: {channels_count}/{max_channels}"
                )
                return

    except Exception as e:
        logger.error(f"❌ فحص الصلاحيات: {e}", exc_info=True)
        await _edit_or_send(
            processing_msg, message,
            "⚠️ حدث خطأ. حاول لاحقاً."
        )
        return

    # ═══ جلب القناة ═══
    try:
        chat = await context.bot.get_chat(f"@{channel_username}")
    except Exception as e:
        logger.warning(f"⚠️ فشل جلب القناة @{channel_username}: {e}")
        await _edit_or_send(
            processing_msg, message,
            f"❌ <b>لم أتمكن من الوصول للقناة</b>\n\n"
            f"تأكد أن:\n"
            f"• القناة موجودة\n"
            f"• المعرّف صحيح: <code>@{channel_username}</code>\n"
            f"• القناة عامة (public)"
        )
        return

    # ═══ فحص صلاحيات البوت ═══
    try:
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        bot_status = getattr(bot_member, "status", "")

        if bot_status not in ("administrator", "creator"):
            await _edit_or_send(
                processing_msg, message,
                f"⚠️ <b>البوت ليس مشرفاً في القناة</b>\n\n"
                f"📌 القناة: <b>{chat.title}</b>\n\n"
                f"<b>الحل:</b>\n"
                f"1. أضف البوت إلى القناة\n"
                f"2. ارقِّه إلى <b>مشرف</b>\n"
                f"3. امنحه صلاحية <b>نشر الرسائل</b>\n"
                f"4. أعد إرسال <code>@{channel_username}</code>"
            )
            return

        can_post = getattr(bot_member, "can_post_messages", True)
        if not can_post:
            await _edit_or_send(
                processing_msg, message,
                f"⚠️ <b>البوت لا يملك صلاحية النشر</b>\n\n"
                f"امنح البوت صلاحية <b>Post Messages</b>."
            )
            return

    except Exception as e:
        logger.error(f"❌ فحص صلاحيات البوت: {e}", exc_info=True)
        await _edit_or_send(
            processing_msg, message,
            "⚠️ لم أتمكن من التحقق من صلاحيات البوت."
        )
        return

    # ═══ إضافة القناة ═══
    try:
        result = await DB.add_channel(
            user_id=user_id,
            channel_id=chat.id,
            channel_name=chat.title,
            set_active=True,
        )
    except Exception as e:
        logger.error(f"❌ فشل add_channel: {e}", exc_info=True)
        await _edit_or_send(
            processing_msg, message,
            "❌ حدث خطأ أثناء إضافة القناة."
        )
        return

    # ═══ النتيجة ═══
    if result:
        channel_name = result.get("channel_name", chat.title) if isinstance(result, dict) else chat.title
        posts_count = result.get("posts_count", 0) if isinstance(result, dict) else 0

        success_text = (
            f"✅ <b>تم إضافة القناة بنجاح!</b>\n\n"
            f"📡 <b>{channel_name}</b>\n"
            f"🆔 <code>{chat.id}</code>\n"
            f"🔗 @{channel_username}\n\n"
            f"📥 منشورات موجودة: {posts_count}\n"
            f"🟢 تم تعيينها <b>القناة النشطة</b>"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📡 قنواتي", callback_data="ch_list")],
            [InlineKeyboardButton("➕ إضافة منشورات", callback_data="post_add")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
        ])

        try:
            if processing_msg:
                await processing_msg.edit_text(
                    success_text, reply_markup=keyboard, parse_mode="HTML",
                )
            else:
                await message.reply_text(
                    success_text, reply_markup=keyboard, parse_mode="HTML",
                )
        except Exception:
            try:
                await message.reply_text(
                    success_text, reply_markup=keyboard, parse_mode="HTML",
                )
            except Exception:
                pass

        logger.info(f"✅ تم إضافة القناة @{channel_username} للمستخدم {user_id}")

        if context.user_data:
            context.user_data.pop("awaiting_channel_add", None)
    else:
        await _edit_or_send(
            processing_msg, message,
            f"❌ <b>فشل إضافة القناة</b>\n\n"
            f"قد تكون مسجلة مسبقاً."
        )


async def _edit_or_send(processing_msg, message, text: str):
    """تعديل الرسالة أو إرسال جديدة."""
    try:
        if processing_msg:
            await processing_msg.edit_text(text, parse_mode="HTML")
        else:
            await message.reply_text(text, parse_mode="HTML")
    except Exception:
        try:
            await message.reply_text(text, parse_mode="HTML")
        except Exception:
            pass


# =====================================================================
# 10. معالج سريع لزر "إضافة منشورات"
# =====================================================================

async def posts_add_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    معالج سريع لزر إضافة منشورات.

    ✅ v2.0.0: استعلام واحد فقط بدل اثنين.
    """
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id
    await _safe_answer(query)

    # ✅ استعلام واحد يجلب اسم القناة النشطة إن وُجدت
    ch_name = None
    try:
        row = await DB.fetchone(
            """
            SELECT uc.channel_name
            FROM users u
            JOIN user_channels uc ON uc.id = u.active_channel
            WHERE u.user_id = ? AND uc.banned = 0
            """,
            (user_id,),
        )
        if row:
            ch_name = row.get("channel_name")
    except Exception as e:
        logger.error(f"posts_add_callback query: {e}")

    # بناء النص
    if ch_name:
        text = (
            f"➕ <b>إضافة منشورات</b>\n\n"
            f"📡 القناة النشطة: <b>{ch_name}</b>\n\n"
            f"<b>📌 طرق الإضافة:</b>\n"
            f"• أرسل <b>نص</b> مباشرة في المحادثة\n"
            f"• أرسل <b>صورة/فيديو/ملف</b> مع تعليق\n"
            f"• أرسل <b>عدة رسائل</b> — كلها تُضاف تلقائياً\n\n"
            f"💡 <i>ابدأ بإرسال المحتوى الآن</i>"
        )
    else:
        text = (
            "⚠️ <b>لا توجد قناة نشطة</b>\n\n"
            "اختر قناة أولاً من قائمة قنواتك."
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 قنواتي", callback_data="ch_list")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ])

    try:
        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode="HTML",
        )
    except Exception as e:
        logger.debug(f"edit_message_text: {e}")
        try:
            await query.message.reply_text(
                text, reply_markup=keyboard, parse_mode="HTML",
            )
        except Exception as e2:
            logger.error(f"reply_text: {e2}")


# =====================================================================
# 11. تسجيل كل الـ handlers
# =====================================================================

def register_channels_list_handlers(application):
    """تسجيل كل handlers قائمة القنوات."""
    try:
        # ═══ الرجوع للقائمة الرئيسية ═══
        application.add_handler(
            CallbackQueryHandler(
                back_to_main_menu_callback,
                pattern=r"^(main_menu|back_to_main|back_to_main_menu|home)$"
            )
        )

        # ═══ إضافة قناة (زر) ═══
        application.add_handler(
            CallbackQueryHandler(
                add_channel_redirect_callback,
                pattern=r"^add_channel$"
            )
        )

        # ═══ إضافة منشورات (سريع) ═══
        application.add_handler(
            CallbackQueryHandler(
                posts_add_callback,
                pattern=r"^(post_add|posts_add)$"
            )
        )

        # ═══ قائمة القنوات ═══
        application.add_handler(
            CallbackQueryHandler(show_channels_list, pattern=r"^ch_list$")
        )

        # ═══ اختيار/تفاصيل ═══
        application.add_handler(
            CallbackQueryHandler(channel_select_callback, pattern=r"^ch_select:")
        )
        application.add_handler(
            CallbackQueryHandler(channel_info_callback, pattern=r"^ch_info:")
        )

        # ═══ الحذف ═══
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

        # ═══ إعادة التدوير ═══
        application.add_handler(
            CallbackQueryHandler(
                channel_recycle_callback, pattern=r"^ch_recycle:"
            )
        )

        # ═══ الجدولة ═══
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

        # ═══ معالج الرسائل النصية لإضافة قناة ═══
        # ✅ v2.0.2: هذا المعالج في group=-1 (قبل handlers_message).
        #    الآن يفحص الحالة أولاً عبر _user_has_pending_state
        #    ولا يعترض إذا كان المستخدم في WAIT_UPDATE_CH وغيره.
        application.add_handler(
            MessageHandler(
                filters.TEXT
                & filters.ChatType.PRIVATE
                & ~filters.COMMAND
                & filters.Regex(
                    r"^(?:@[a-zA-Z0-9_]{4,}|"
                    r"(?:https?://)?(?:www\.)?t\.me/[a-zA-Z0-9_]{4,}/?)$"
                ),
                add_channel_from_message,
            ),
            group=-1,
        )

        logger.info("✅ تم تسجيل handlers قائمة القنوات (v2.0.2)")
        return True
    except Exception as e:
        logger.error(f"❌ فشل تسجيل handlers: {e}", exc_info=True)
        return False