#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_channels_list.py - واجهة قائمة القنوات + إضافة المنشورات (v2.2.0)
================================================================================
🆕 v2.2.0 (ADDING-POSTS-HANDLER):
    🔴 FIX-CRITICAL: حل جذري لمشكلة "❌ لم أتعرف على العملية" عند
       إضافة منشور (state=UserState.ADDING_POSTS).
       السبب: لا يوجد handler مسجَّل لحالة ADDING_POSTS في المشروع.
       الحل: معالج جديد `handle_adding_posts` يستقبل النص/الصورة/الفيديو
             ويستدعي DB.add_posts() للقناة النشطة.
    ✨ posts_add_callback يضبط الآن الحالة ADDING_POSTS عند الضغط.
    ✨ زر /cancel منفصل للخروج من وضع إضافة المنشورات.
    🟠 التسجيل في group=-2 (قبل handlers_message) لتفادي UNHANDLED STATE.

🆕 v2.1.0 (WAIT-CHANNEL-ROUTING-FIX):
    🔴 FIX-1 CRITICAL: حل جذري لمشكلة "❌ تعذّر معالجة معرف القناة".
    🟠 FIX-2: استيراد ApplicationHandlerStop.
    🟡 FIX-3: تنظيم منطق مسح الحالة في helper موحّد.

🆕 v2.0.3: (POLISH-FIXES)
🆕 v2.0.2: (إصلاح اعتراض الرسائل)
🆕 v2.0.1: (إصلاح answer() المزدوج)
🆕 v2.0.0: (إصلاح أخطاء حرجة)
================================================================================
"""

import logging
import re
from datetime import timedelta
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, MessageHandler, filters,
    CommandHandler, ApplicationHandlerStop,
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
# 🆕 v2.1.0: حالات إضافة القناة المسموح بها
# =====================================================================

_CHANNEL_ADD_STATES = (
    "WAIT_CHANNEL",
    "WAIT_ADD_CHANNEL",
    "WAIT_UPDATE_CH",
    "WAIT_UPDATE_CHANNEL",
    "WAIT_LOG_CH",
)


# =====================================================================
# 0. أدوات مساعدة
# =====================================================================

def _db_ready() -> bool:
    if DB is None:
        logger.error("❌ DB غير مهيأة — تخطي handler")
        return False
    return True


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        if hasattr(row, 'keys'):
            return {k: row[k] for k in row.keys()}
    except Exception:
        pass
    try:
        return dict(row)
    except (TypeError, ValueError):
        return {}


def _get_state_str(user_id: int) -> str:
    if not _STATE_AVAILABLE or StateManager is None:
        return ""
    try:
        state = StateManager.get(user_id)
        if state is None:
            return ""
        return str(state) or ""
    except Exception as e:
        logger.debug(f"_get_state_str({user_id}): {e}")
        return ""


def _is_channel_add_state(state_str: str) -> bool:
    if not state_str:
        return False
    return any(s in state_str for s in _CHANNEL_ADD_STATES)


def _is_adding_posts_state(state_str: str) -> bool:
    """🆕 v2.2.0: هل المستخدم في حالة إضافة منشورات؟"""
    if not state_str:
        return False
    return "ADDING_POSTS" in state_str


def _clear_user_state(user_id: int) -> None:
    if not _STATE_AVAILABLE or StateManager is None:
        return
    try:
        StateManager.clear(user_id)
        logger.debug(f"🔄 state cleared for user {user_id}")
    except Exception as e:
        logger.debug(f"_clear_user_state({user_id}): {e}")


def _set_user_state(user_id: int, state) -> bool:
    """🆕 v2.2.0: ضبط حالة المستخدم بأمان."""
    if not _STATE_AVAILABLE or StateManager is None:
        return False
    try:
        StateManager.set(user_id, state)
        logger.debug(f"✅ state set for user {user_id}: {state}")
        return True
    except Exception as e:
        logger.warning(f"_set_user_state({user_id}): {e}")
        return False


def _user_has_pending_state(user_id: int) -> bool:
    if not _STATE_AVAILABLE or StateManager is None:
        return False
    try:
        state = StateManager.get(user_id)
        if state is None:
            return False

        state_str = str(state) or ""

        if _is_channel_add_state(state_str):
            return False
        if _is_adding_posts_state(state_str):
            return False

        if UserState is not None:
            none_state = getattr(UserState, "NONE", None)
            if none_state is not None:
                return state != none_state
        return True
    except Exception as e:
        logger.debug(f"_user_has_pending_state({user_id}): {e}")
        return False


async def _safe_answer(query, text: str = None, show_alert: bool = False) -> None:
    try:
        if text is not None:
            await query.answer(text, show_alert=show_alert)
        else:
            await query.answer()
    except Exception as e:
        logger.debug(f"_safe_answer: {e}")


def _format_date(dt_value) -> str:
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
                if update.callback_query.message is not None:
                    await update.callback_query.message.reply_text(
                        text, reply_markup=keyboard, parse_mode="HTML",
                    )
            except Exception as e2:
                logger.error(f"reply_text fallback: {e2}")
    else:
        try:
            if update.message is not None:
                await update.message.reply_text(
                    text, reply_markup=keyboard, parse_mode="HTML",
                )
        except Exception as e:
            logger.error(f"reply_text: {e}")


async def _get_channels_with_stats(user_id: int):
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
        rows = await DB.fetchall(query, (user_id,))
        return [_row_to_dict(r) for r in (rows or [])]
    except Exception as e:
        logger.error(f"❌ _get_channels_with_stats: {e}", exc_info=True)
        return []


def _build_channels_text(channels, active_channel_id) -> str:
    lines = [f"📡 <b>قنواتك ({len(channels)})</b>\n"]

    total_unpub = sum(c.get("unpublished", 0) or 0 for c in channels)
    total_pub = sum(c.get("published", 0) or 0 for c in channels)

    lines.append(f"📥 إجمالي غير منشور: <b>{total_unpub}</b>")
    lines.append(f"📤 إجمالي منشور: <b>{total_pub}</b>\n")
    lines.append("─" * 30 + "\n")

    for i, ch in enumerate(channels, 1):
        ch_db_id = ch.get("channel_db_id")
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
    keyboard = []

    for ch in channels:
        ch_db_id = ch.get("channel_db_id")
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
# 3. تفاصيل قناة
# =====================================================================

async def _render_channel_info(query, user_id: int, ch_db_id: int) -> None:
    try:
        ch_raw = await DB.get_channel_by_id(user_id, ch_db_id)
        ch = _row_to_dict(ch_raw)
        if not ch:
            await _safe_answer(query, "⚠️ القناة غير موجودة", show_alert=True)
            return

        stats_raw = await DB.get_channel_stats(user_id, ch_db_id) or {}
        stats = _row_to_dict(stats_raw)
        active_channel_id = await _get_active_channel_id(user_id)

        try:
            schedule_raw = await DB.get_schedule(ch_db_id)
            schedule = _row_to_dict(schedule_raw)
            interval_min = schedule.get("interval_minutes", 12) or 12
            next_publish = schedule.get("next_publish_date")
        except Exception:
            interval_min = 12
            next_publish = None

        name = ch.get("channel_name") or "قناة بدون اسم"
        ch_telegram_id = ch.get("channel_id") or "غير معروف"
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
            if query.message is not None:
                await query.message.reply_text(
                    "⚠️ فشل عرض تفاصيل القناة. حاول لاحقاً.",
                    parse_mode="HTML",
                )
        except Exception:
            pass


async def channel_info_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
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
# 4. حذف القنوات
# =====================================================================

async def channel_delete_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
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
        ch_db_id = ch.get("channel_db_id")
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
        ch_raw = await DB.get_channel_by_id(user_id, ch_db_id)
        ch = _row_to_dict(ch_raw)
        if not ch:
            await _safe_answer(query, "⚠️ القناة غير موجودة", show_alert=True)
            return

        await _safe_answer(query)

        name = ch.get("channel_name") or "قناة"
        stats_raw = await DB.get_channel_stats(user_id, ch_db_id) or {}
        stats = _row_to_dict(stats_raw)

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
# 5. إعادة تدوير
# =====================================================================

async def channel_recycle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
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
# 6. الجدولة
# =====================================================================

async def channel_schedule_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
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
            schedule_raw = await DB.get_schedule(ch_db_id)
            schedule = _row_to_dict(schedule_raw)
            current = schedule.get("interval_minutes", 12) or 12
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
    query = update.callback_query
    await _safe_answer(query)

    try:
        if query.message is not None:
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
    query = update.callback_query
    await _safe_answer(query)

    user_id = query.from_user.id

    _clear_user_state(user_id)

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

_USERNAME_RE = re.compile(r"^@([a-zA-Z][a-zA-Z0-9_]{3,31})$")
_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?t\.me/([a-zA-Z][a-zA-Z0-9_]{3,31})/?$",
    re.IGNORECASE,
)

_FILTER_REGEX = (
    r"^(?:@[a-zA-Z][a-zA-Z0-9_]{3,31}|"
    r"(?:https?://)?(?:www\.)?t\.me/[a-zA-Z][a-zA-Z0-9_]{3,31}/?)$"
)


def _extract_channel_username(text: str) -> Optional[str]:
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
    if not _db_ready():
        return

    message = update.message
    if not message or not message.text:
        return

    user_id = message.from_user.id

    state_str = _get_state_str(user_id)
    is_channel_add_ctx = _is_channel_add_state(state_str)

    if _user_has_pending_state(user_id):
        logger.debug(
            f"⏭️ add_channel_from_message: تجاهل — "
            f"المستخدم {user_id} في حالة معلقة ({state_str})"
        )
        return

    text = message.text.strip()

    channel_username = _extract_channel_username(text)
    if not channel_username:
        if (context.user_data and context.user_data.get("awaiting_channel_add")) \
                or is_channel_add_ctx:
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
            _clear_user_state(user_id)
            if context.user_data:
                context.user_data.pop("awaiting_channel_add", None)
            raise ApplicationHandlerStop
        return

    logger.info(
        f"📥 محاولة إضافة قناة: @{channel_username} من {user_id} "
        f"(state={state_str or 'none'})"
    )

    if context.user_data is not None:
        if context.user_data.get("_adding_channel_lock"):
            logger.debug(
                f"🔒 add_channel_from_message: قفل مسبق للمستخدم {user_id}"
            )
            raise ApplicationHandlerStop
        context.user_data["_adding_channel_lock"] = True

    processing_msg = None
    try:
        try:
            user_raw = await DB.get_user_full_data(user_id, include_stats=True)
            user = _row_to_dict(user_raw)
            if not user:
                await _edit_or_send(
                    processing_msg, message,
                    "⚠️ الرجاء إرسال /start أولاً."
                )
                _clear_user_state(user_id)
                raise ApplicationHandlerStop

            if user.get("banned"):
                await _edit_or_send(
                    processing_msg, message,
                    "🚫 أنت محظور من استخدام البوت."
                )
                _clear_user_state(user_id)
                raise ApplicationHandlerStop

            if not user.get("has_subscription"):
                await _edit_or_send(
                    processing_msg, message,
                    "💎 <b>يجب أن يكون لديك اشتراك نشط</b>\n\n"
                    "استخدم /subscribe للاشتراك."
                )
                _clear_user_state(user_id)
                raise ApplicationHandlerStop

            channels_count = user.get("channels_count", 0) or 0
            active_sub_raw = await DB.get_active_subscription(user_id)
            active_sub = _row_to_dict(active_sub_raw)
            if active_sub:
                max_channels = active_sub.get("max_channels", 0) or 0
                if channels_count >= max_channels:
                    await _edit_or_send(
                        processing_msg, message,
                        f"⚠️ <b>وصلت للحد الأقصى</b>\n\n"
                        f"عدد قنواتك: {channels_count}/{max_channels}"
                    )
                    _clear_user_state(user_id)
                    raise ApplicationHandlerStop

        except ApplicationHandlerStop:
            raise
        except Exception as e:
            logger.error(f"❌ فحص الصلاحيات: {e}", exc_info=True)
            await _edit_or_send(
                processing_msg, message,
                "⚠️ حدث خطأ. حاول لاحقاً."
            )
            _clear_user_state(user_id)
            raise ApplicationHandlerStop

        try:
            processing_msg = await message.reply_text(
                f"⏳ جاري التحقق من <code>@{channel_username}</code>...",
                parse_mode="HTML",
            )
        except Exception:
            processing_msg = None

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
            _clear_user_state(user_id)
            raise ApplicationHandlerStop

        try:
            bot_member = await context.bot.get_chat_member(
                chat.id, context.bot.id)
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
                _clear_user_state(user_id)
                raise ApplicationHandlerStop

            can_post = getattr(bot_member, "can_post_messages", True)
            if not can_post:
                await _edit_or_send(
                    processing_msg, message,
                    f"⚠️ <b>البوت لا يملك صلاحية النشر</b>\n\n"
                    f"امنح البوت صلاحية <b>Post Messages</b>."
                )
                _clear_user_state(user_id)
                raise ApplicationHandlerStop

        except ApplicationHandlerStop:
            raise
        except Exception as e:
            logger.error(f"❌ فحص صلاحيات البوت: {e}", exc_info=True)
            await _edit_or_send(
                processing_msg, message,
                "⚠️ لم أتمكن من التحقق من صلاحيات البوت."
            )
            _clear_user_state(user_id)
            raise ApplicationHandlerStop

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
            _clear_user_state(user_id)
            raise ApplicationHandlerStop

        result_d = _row_to_dict(result)
        if result_d or result:
            channel_name = (
                result_d.get("channel_name")
                if result_d else chat.title
            ) or chat.title
            posts_count = (
                result_d.get("posts_count", 0)
                if result_d else 0
            ) or 0

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

            logger.info(
                f"✅ تم إضافة القناة @{channel_username} للمستخدم {user_id}"
            )
        else:
            await _edit_or_send(
                processing_msg, message,
                f"❌ <b>فشل إضافة القناة</b>\n\n"
                f"قد تكون مسجلة مسبقاً."
            )

        _clear_user_state(user_id)
        if context.user_data:
            context.user_data.pop("awaiting_channel_add", None)
            context.user_data.pop("_adding_channel_lock", None)
        raise ApplicationHandlerStop

    except ApplicationHandlerStop:
        if context.user_data is not None:
            context.user_data.pop("_adding_channel_lock", None)
        raise
    except Exception as e:
        logger.error(
            f"❌ add_channel_from_message غير متوقع: {e}",
            exc_info=True,
        )
        _clear_user_state(user_id)
        if context.user_data:
            context.user_data.pop("awaiting_channel_add", None)
            context.user_data.pop("_adding_channel_lock", None)
        try:
            await message.reply_text(
                "⚠️ حدث خطأ غير متوقع. حاول مجدداً.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        raise ApplicationHandlerStop


async def _edit_or_send(processing_msg, message, text: str):
    if processing_msg is not None:
        try:
            mid = getattr(processing_msg, "message_id", None)
            if mid:
                await processing_msg.edit_text(text, parse_mode="HTML")
                return
        except Exception as e:
            logger.debug(f"_edit_or_send edit_text: {e}")

    try:
        await message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.debug(f"_edit_or_send reply_text: {e}")


# =====================================================================
# 🆕 v2.2.0: معالج إضافة المنشورات (ADDING_POSTS)
# =====================================================================

async def handle_adding_posts(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    🆕 v2.2.0: معالج حالة ADDING_POSTS.

    يستقبل: نص / صورة / فيديو / مستند / صوت / فويس من المستخدم
    ويضيفه للقناة النشطة عبر DB.add_posts().
    """
    if not _db_ready():
        return

    message = update.message or update.effective_message
    if not message:
        return

    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return

    # ─── تحقق من الحالة ───
    state_str = _get_state_str(user_id)
    if not _is_adding_posts_state(state_str):
        # ليست حالته — لا نتدخل
        return

    logger.info(
        f"📝 handle_adding_posts: user={user_id} state={state_str}"
    )

    # ─── جلب القناة النشطة ───
    channel_db_id = await _get_active_channel_id(user_id)
    if not channel_db_id:
        try:
            await context.bot.send_message(
                user_id,
                "⚠️ <b>لا توجد قناة نشطة</b>\n\n"
                "اختر قناة أولاً من <b>📡 قنواتي</b>.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        _clear_user_state(user_id)
        raise ApplicationHandlerStop

    # ─── استخراج المحتوى ───
    text = (message.text or message.caption or "")
    media_type = ""
    media_file_id = ""

    try:
        if getattr(message, "photo", None):
            media_type = "photo"
            media_file_id = message.photo[-1].file_id
        elif getattr(message, "video", None):
            media_type = "video"
            media_file_id = message.video.file_id
        elif getattr(message, "document", None):
            media_type = "document"
            media_file_id = message.document.file_id
        elif getattr(message, "animation", None):
            media_type = "animation"
            media_file_id = message.animation.file_id
        elif getattr(message, "voice", None):
            media_type = "voice"
            media_file_id = message.voice.file_id
        elif getattr(message, "audio", None):
            media_type = "audio"
            media_file_id = message.audio.file_id
        elif getattr(message, "video_note", None):
            media_type = "video_note"
            media_file_id = message.video_note.file_id
    except Exception as e:
        logger.debug("handle_adding_posts media extract: %s", e)

    if not text and not media_file_id:
        try:
            await context.bot.send_message(
                user_id,
                "⚠️ <b>لا يوجد محتوى قابل للإضافة</b>\n\n"
                "أرسل نصاً، أو صورة، أو فيديو، أو مستنداً.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        raise ApplicationHandlerStop

    # ─── إضافة المنشور ───
    try:
        added = await DB.add_posts(
            user_id=user_id,
            channel_db_id=channel_db_id,
            posts=[(text, media_type, media_file_id)],
        )
    except Exception as e:
        logger.error(
            "handle_adding_posts add_posts: %s", e, exc_info=True)
        added = 0

    # ─── الرد ───
    try:
        if added and added > 0:
            await context.bot.send_message(
                user_id,
                "✅ <b>تمت إضافة المنشور</b>\n\n"
                "أرسل المزيد، أو /cancel للخروج.",
                parse_mode="HTML",
            )
        else:
            await context.bot.send_message(
                user_id,
                "⚠️ <b>لم يُضف المنشور</b>\n\n"
                "• قد يكون مكرراً\n"
                "• أو وصلت للحد الأقصى\n"
                "• أو القناة غير متاحة\n\n"
                "للمتابعة أرسل المزيد، أو /cancel للخروج.",
                parse_mode="HTML",
            )
    except Exception:
        pass

    # ⚠️ نرفع Stop حتى لا يصل الحدث لـ handlers_message
    raise ApplicationHandlerStop


async def cancel_adding_posts_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    🆕 v2.2.0: /cancel للخروج من وضع إضافة المنشورات.
    """
    message = update.message or update.effective_message
    if not message:
        return

    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return

    state_str = _get_state_str(user_id)
    if not _is_adding_posts_state(state_str):
        # ليس في حالتنا — لا نتدخل
        return

    _clear_user_state(user_id)

    try:
        await context.bot.send_message(
            user_id,
            "✅ <b>تم الخروج من وضع إضافة المنشورات</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass

    raise ApplicationHandlerStop


async def posts_add_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    🆕 v2.2.0: يضبط الآن الحالة ADDING_POSTS لاستقبال المنشورات.
    """
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id
    await _safe_answer(query)

    # ─── جلب اسم القناة النشطة ───
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
        row_d = _row_to_dict(row)
        if row_d:
            ch_name = row_d.get("channel_name")
    except Exception as e:
        logger.error(f"posts_add_callback query: {e}")

    if ch_name:
        # 🆕 v2.2.0: ضبط الحالة
        if _STATE_AVAILABLE and UserState is not None:
            adding_state = getattr(UserState, "ADDING_POSTS", None)
            if adding_state is not None:
                _set_user_state(user_id, adding_state)
                logger.info(
                    f"✅ posts_add_callback: state set to ADDING_POSTS "
                    f"for user {user_id}"
                )
            else:
                logger.warning(
                    "⚠️ UserState.ADDING_POSTS غير موجود في enum!"
                )
        else:
            logger.warning(
                "⚠️ StateManager/UserState غير متاح — "
                "لا يمكن ضبط حالة إضافة المنشورات"
            )

        text = (
            f"➕ <b>إضافة منشورات</b>\n\n"
            f"📡 القناة النشطة: <b>{ch_name}</b>\n\n"
            f"<b>📌 طرق الإضافة:</b>\n"
            f"• أرسل <b>نص</b> مباشرة في المحادثة\n"
            f"• أرسل <b>صورة/فيديو/ملف</b> مع تعليق\n"
            f"• أرسل <b>عدة رسائل</b> — كلها تُضاف تلقائياً\n\n"
            f"<b>🛑 للخروج:</b> /cancel\n\n"
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
            if query.message is not None:
                await query.message.reply_text(
                    text, reply_markup=keyboard, parse_mode="HTML",
                )
        except Exception as e2:
            logger.error(f"reply_text: {e2}")


# =====================================================================
# 11. التسجيل
# =====================================================================

def register_channels_list_handlers(application):
    """تسجيل كل handlers قائمة القنوات + إضافة المنشورات."""
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

        # ═══════════════════════════════════════════════════════════
        # 🆕 v2.2.0: /cancel لإضافة المنشورات (group=-3)
        # ═══════════════════════════════════════════════════════════
        application.add_handler(
            CommandHandler(
                "cancel",
                cancel_adding_posts_command,
            ),
            group=-3,
        )

        # ═══════════════════════════════════════════════════════════
        # 🆕 v2.2.0: معالج ADDING_POSTS (group=-2)
        #   يقبل: نص، صورة، فيديو، مستند، صوت، فويس، animation، video_note
        #   يعمل فقط إذا كان المستخدم في حالة ADDING_POSTS.
        # ═══════════════════════════════════════════════════════════
        application.add_handler(
            MessageHandler(
                (
                    filters.TEXT
                    | filters.PHOTO
                    | filters.VIDEO
                    | filters.Document.ALL
                    | filters.AUDIO
                    | filters.VOICE
                    | filters.ANIMATION
                    | filters.VIDEO_NOTE
                )
                & filters.ChatType.PRIVATE
                & ~filters.COMMAND,
                handle_adding_posts,
            ),
            group=-2,
        )

        # ═══════════════════════════════════════════════════════════
        # معالج الرسائل النصية لإضافة قناة (group=-1)
        # ═══════════════════════════════════════════════════════════
        application.add_handler(
            MessageHandler(
                filters.TEXT
                & filters.ChatType.PRIVATE
                & ~filters.COMMAND
                & filters.Regex(_FILTER_REGEX),
                add_channel_from_message,
            ),
            group=-1,
        )

        logger.info(
            "✅ تم تسجيل handlers قائمة القنوات (v2.2.0 — "
            "WAIT-CHANNEL + ADDING-POSTS)"
        )
        return True
    except Exception as e:
        logger.error(f"❌ فشل تسجيل handlers: {e}", exc_info=True)
        return False