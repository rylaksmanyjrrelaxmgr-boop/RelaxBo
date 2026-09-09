#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_callback.py - المعالج النهائي الكامل لجميع الأزرار (نسخة نهائية مع جميع المعالجات)
================================================================================
- جميع الأزرار المذكورة في buttons_config_ar.json معالجة بالكامل
- بما في ذلك:
  - sec_penalty_ban, sec_penalty_mute, sec_penalty_kick, sec_penalty_restrict, sec_penalty_none
  - sec_set_antiflood_messages, sec_set_antiflood_seconds, sec_antiflood_penalty, sec_set_antiflood_penalty
  - sec_set_night_start, sec_set_night_end, sec_night_action, sec_set_night_action
  - admin_disable_force, admin_restore_sel, admin_show_backups (تم دمجها مع admin_restore)
  - جميع أزرار الأمان والجدولة والإدارة والردود التلقائية
  - عقوبات المخالفات (violation): sec_violation_settings, sec_set_violation_strikes,
    sec_set_violation_duration, sec_set_violation_penalty
- إصلاح جميع الأخطاء السابقة
"""

import asyncio
import logging
import json
import time
import shutil
import os
import weakref
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice, ChatPermissions
from telegram.ext import ContextTypes
from telegram.error import BadRequest, RetryAfter, Forbidden

from config import CONFIG, PATHS
from database import DB, TimeUtils
from utils import (
    safe_send, is_authorized_in_group,
    get_text, StateManager, UserState,
    KeyboardFactory, CB, get_ram_usage
)
from .handlers_command import CommandHandlers

logger = logging.getLogger(__name__)

MAX_CAPTION_LENGTH = 1024
MAX_MESSAGE_LENGTH = 4096
MAX_BACKUPS = CONFIG.MAX_BACKUPS
MAX_CONCURRENT_PUBLISH = 3

ACTIVE_TASKS = weakref.WeakSet()


async def _safe_answer(query, text=None, show_alert=False):
    if not query:
        return False
    try:
        if text:
            await query.answer(text, show_alert=show_alert)
        else:
            await query.answer()
        return True
    except:
        return False


async def _trans(key, lang, default_ar):
    if not lang:
        return default_ar
    try:
        text = await get_text(lang, key)
        if not text or text == key:
            return default_ar
        return text
    except:
        return default_ar


async def safe_edit(query, text, reply_markup=None, parse_mode=None, bot=None):
    await _safe_answer(query)
    if not query or not query.message:
        return False
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return True
    except BadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            return True
        elif "message is too long" in error_msg:
            chat_id = query.message.chat_id
            try:
                await query.message.delete()
            except Exception:
                pass
            try:
                send_bot = bot if bot else query._bot
                await send_bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode
                )
                return True
            except Exception as e2:
                logger.error(f"فشل إرسال رسالة جديدة بعد الطول الزائد: {e2}")
                return False
        else:
            return False
    except Exception as e:
        logger.debug(f"Edit error: {e}")
        return False


async def safe_delete_message(query_or_message):
    try:
        if hasattr(query_or_message, 'message') and query_or_message.message:
            await query_or_message.message.delete()
        elif query_or_message:
            await query_or_message.delete()
    except Exception:
        pass


def _mask_id(id_value, prefix=3, suffix=2):
    if id_value is None:
        return "***"
    s = str(id_value)
    if len(s) <= 5:
        return "***"
    return s[:prefix] + "***" + s[-suffix:]


async def _is_channel_owner(user_id: int, channel_db_id: int) -> bool:
    return await DB.is_channel_owner(user_id, channel_db_id)


class CallbackHandlers:

    @staticmethod
    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return
        data = query.data
        if not data:
            return

        debounce_key = f"debounce_{query.id}"
        now_time = time.monotonic()
        last_time = context.user_data.get(debounce_key, 0)
        if now_time - last_time < 1.5:
            await _safe_answer(query, "⚠️ انتظر لحظة")
            return
        context.user_data[debounce_key] = now_time

        user_id = query.from_user.id
        lang = await DB.get_user_language(user_id) or 'ar'
        start_time = time.monotonic()

        if 'start_time' not in context.bot_data:
            context.bot_data['start_time'] = time.monotonic()

        # ========== معالجة set_warn_penalty ==========
        if data.startswith("set_warn_penalty:"):
            try:
                _, penalty_type, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                if penalty_type in DB.VALID_PENALTY_TYPES:
                    await DB.update_security_settings(chat_id, warn_penalty=penalty_type)
                    await _safe_answer(query, f"✅ تم تعيين عقوبة التحذير: {penalty_type}")
                    settings = await DB.get_security_settings(chat_id)
                    await safe_edit(query, KeyboardFactory._format_security_text(settings), reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang), bot=context.bot)
                else:
                    await _safe_answer(query, "❌ نوع عقوبة غير صالح", show_alert=True)
            except Exception as e:
                logger.error(f"خطأ في set_warn_penalty: {e}", exc_info=True)
                await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
            return

        # ========== معالجة set_warn_duration ==========
        if data.startswith("set_warn_duration:"):
            try:
                _, duration_str, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                duration = int(duration_str)
                await DB.update_security_settings(chat_id, warn_penalty_duration=duration)
                await _safe_answer(query, f"✅ تم تعيين مدة العقوبة: {duration} ثانية")
                settings = await DB.get_security_settings(chat_id)
                await safe_edit(query, KeyboardFactory._format_security_text(settings), reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang), bot=context.bot)
            except Exception as e:
                logger.error(f"خطأ في set_warn_duration: {e}", exc_info=True)
                await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
            return

        # ========== معالجة set_duration (لجميع العقوبات بما فيها violation) ==========
        if data.startswith("set_duration:"):
            parts = data.split(":")
            if len(parts) >= 4:
                try:
                    penalty_type = parts[1]
                    chat_id = int(parts[2])
                    duration = int(parts[3])
                except (ValueError, IndexError):
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return

                col_map = {
                    'mute': 'mute_default_duration',
                    'ban': 'ban_default_duration',
                    'restrict': 'restrict_default_duration',
                    'antiflood': 'antiflood_penalty_duration',
                    'night': 'night_mode_action_duration',
                    'warn_penalty': 'warn_penalty_duration',
                    'delete_penalty': 'delete_penalty_duration',
                    'violation': 'violation_penalty_duration',  # عقوبات المخالفات
                }
                col = col_map.get(penalty_type)
                if col is None:
                    await _safe_answer(query, "❌ نوع عقوبة غير صالح", show_alert=True)
                    return
                await DB.update_security_settings(chat_id, **{col: duration})
                await _safe_answer(query, f"✅ تم تعيين المدة: {duration} ثانية")
                settings = await DB.get_security_settings(chat_id)
                await safe_edit(query, KeyboardFactory._format_security_text(settings), reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang), bot=context.bot)
                return

        # ========== معالجة sec_set_del_penalty ==========
        if data.startswith("sec_set_del_penalty:"):
            try:
                _, penalty_type, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                if penalty_type == "none":
                    await DB.update_security_settings(chat_id, delete_penalty="none")
                    await _safe_answer(query, "✅ تم تعطيل عقوبة الحذف")
                elif penalty_type in DB.VALID_PENALTY_TYPES:
                    await DB.update_security_settings(chat_id, delete_penalty=penalty_type)
                    await _safe_answer(query, f"✅ تم تعيين عقوبة الحذف: {penalty_type}")
                else:
                    await _safe_answer(query, "❌ نوع عقوبة غير صالح", show_alert=True)
                    return
                settings = await DB.get_security_settings(chat_id)
                await safe_edit(query, KeyboardFactory._format_security_text(settings), reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang), bot=context.bot)
            except Exception as e:
                logger.error(f"خطأ في sec_set_del_penalty: {e}", exc_info=True)
                await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
            return

        # ========== معالجة sec_set_del_penalty_duration ==========
        if data.startswith("sec_set_del_penalty_duration:"):
            try:
                _, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                await CallbackHandlers._show_penalty_durations(update, context, query, chat_id, lang, 'delete_penalty')
            except Exception as e:
                logger.error(f"خطأ في sec_set_del_penalty_duration: {e}", exc_info=True)
                await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
            return

        # ========== معالجة sec_penalty_durations ==========
        if data.startswith("sec_penalty_durations:"):
            try:
                _, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⏱️ مدة الكتم", callback_data=f"sec_set_mute_duration:{chat_id}"),
                     InlineKeyboardButton("⏱️ مدة الحظر", callback_data=f"sec_set_ban_duration:{chat_id}")],
                    [InlineKeyboardButton("⏱️ مدة التقييد", callback_data=f"sec_set_restrict_duration:{chat_id}"),
                     InlineKeyboardButton("⏱️ مدة عقوبة التحذير", callback_data=f"sec_warn_penalty_duration:{chat_id}")],
                    [InlineKeyboardButton("⏱️ مدة الفيضان", callback_data=f"sec_antiflood_duration:{chat_id}"),
                     InlineKeyboardButton("⏱️ مدة الليل", callback_data=f"sec_night_duration:{chat_id}")],
                    [InlineKeyboardButton("⏱️ مدة عقوبة الحذف", callback_data=f"sec_set_del_penalty_duration:{chat_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")]
                ])
                await safe_edit(query, "⏱️ اختر نوع العقوبة لتعديل مدتها:", reply_markup=kb, bot=context.bot)
            except Exception as e:
                logger.error(f"خطأ في sec_penalty_durations: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        # ========== معالجة sec_set_mute_duration, sec_set_ban_duration, sec_set_restrict_duration ==========
        if data.startswith("sec_set_mute_duration:") or data.startswith("sec_set_ban_duration:") or data.startswith("sec_set_restrict_duration:"):
            try:
                parts = data.split(":")
                action_type = parts[0].replace("sec_set_", "").replace("_duration", "")
                chat_id = int(parts[1])
                await CallbackHandlers._show_penalty_durations(update, context, query, chat_id, lang, action_type)
            except Exception as e:
                logger.error(f"خطأ في set_duration_menu: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        # ========== معالجة sec_antiflood_duration و sec_night_duration ==========
        if data.startswith("sec_antiflood_duration:") or data.startswith("sec_night_duration:"):
            try:
                parts = data.split(":")
                action_type = parts[0].replace("sec_", "").replace("_duration", "")
                chat_id = int(parts[1])
                await CallbackHandlers._show_penalty_durations(update, context, query, chat_id, lang, action_type)
            except Exception as e:
                logger.error(f"خطأ في duration_menu: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        # ========== معالجة sec_warn_penalty_duration ==========
        if data.startswith("sec_warn_penalty_duration:"):
            try:
                _, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                await CallbackHandlers._show_penalty_durations(update, context, query, chat_id, lang, 'warn_penalty')
            except Exception as e:
                logger.error(f"خطأ في sec_warn_penalty_duration: {e}", exc_info=True)
                await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
            return

        # ========== معالجة sec_penalty_* (اختيار العقوبة التلقائية) ==========
        if data.startswith("sec_penalty_"):
            try:
                parts = data.split(":")
                if len(parts) >= 2 and parts[1].isdigit():
                    chat_id = int(parts[1])
                else:
                    chat_id = context.user_data.get('security_chat_id')
                    if not chat_id and update.effective_chat:
                        chat_id = update.effective_chat.id
                if chat_id is None:
                    await _safe_answer(query, "❌ لم يتم تحديد المجموعة", show_alert=True)
                    return
                action = parts[0].replace("sec_penalty_", "")
                if action in ['ban', 'mute', 'kick', 'restrict', 'none']:
                    await DB.update_security_settings(chat_id, auto_penalty=action)
                    await _safe_answer(query, f"✅ تم تعيين العقوبة التلقائية: {action}")
                    settings = await DB.get_security_settings(chat_id)
                    await safe_edit(query, KeyboardFactory._format_security_text(settings),
                                    reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                                    bot=context.bot)
                    return
                else:
                    await _safe_answer(query, "❌ نوع عقوبة غير صالح", show_alert=True)
            except Exception as e:
                logger.error(f"خطأ في sec_penalty_*: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        # ========== معالجة sec_set_antiflood_messages, sec_set_antiflood_seconds ==========
        if data.startswith("sec_set_antiflood_messages:"):
            try:
                _, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                StateManager.set(user_id, UserState.WAIT_ANTIFLOOD_MESSAGES)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "📊 أرسل عدد الرسائل المسموحة:", bot=context.bot)
            except Exception as e:
                logger.error(f"خطأ في sec_set_antiflood_messages: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        if data.startswith("sec_set_antiflood_seconds:"):
            try:
                _, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                StateManager.set(user_id, UserState.WAIT_ANTIFLOOD_SECONDS)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "⏱️ أرسل عدد الثواني:", bot=context.bot)
            except Exception as e:
                logger.error(f"خطأ في sec_set_antiflood_seconds: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        # ========== معالجة sec_antiflood_penalty ==========
        if data.startswith("sec_antiflood_penalty:"):
            try:
                _, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                await CallbackHandlers._show_penalty_type_selection(update, context, query, chat_id, lang, 'antiflood_penalty')
            except Exception as e:
                logger.error(f"خطأ في sec_antiflood_penalty: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        # ========== معالجة sec_set_antiflood_penalty ==========
        if data.startswith("sec_set_antiflood_penalty:"):
            try:
                parts = data.split(":")
                if len(parts) >= 3:
                    chat_id = int(parts[1])
                    penalty_type = parts[2]
                    if penalty_type in ['ban', 'mute', 'kick', 'restrict', 'none']:
                        await DB.update_security_settings(chat_id, antiflood_penalty=penalty_type)
                        await _safe_answer(query, f"✅ تم تعيين عقوبة الفيضان: {penalty_type}")
                        settings = await DB.get_security_settings(chat_id)
                        await safe_edit(query, KeyboardFactory._format_security_text(settings),
                                        reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                                        bot=context.bot)
                        return
                    else:
                        await _safe_answer(query, "❌ نوع عقوبة غير صالح", show_alert=True)
                else:
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
            except Exception as e:
                logger.error(f"خطأ في sec_set_antiflood_penalty: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        # ========== معالجة sec_set_night_start, sec_set_night_end ==========
        if data.startswith("sec_set_night_start:"):
            try:
                _, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                StateManager.set(user_id, UserState.WAIT_NIGHT_START)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🌙 أرسل وقت البدء (HH:MM):", bot=context.bot)
            except Exception as e:
                logger.error(f"خطأ في sec_set_night_start: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        if data.startswith("sec_set_night_end:"):
            try:
                _, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                StateManager.set(user_id, UserState.WAIT_NIGHT_END)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🌙 أرسل وقت النهاية (HH:MM):", bot=context.bot)
            except Exception as e:
                logger.error(f"خطأ في sec_set_night_end: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        # ========== معالجة sec_night_action ==========
        if data.startswith("sec_night_action:"):
            try:
                _, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                await CallbackHandlers._show_penalty_type_selection(update, context, query, chat_id, lang, 'night_action')
            except Exception as e:
                logger.error(f"خطأ في sec_night_action: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        # ========== معالجة sec_set_night_action ==========
        if data.startswith("sec_set_night_action:"):
            try:
                parts = data.split(":")
                if len(parts) >= 3:
                    chat_id = int(parts[1])
                    action_type = parts[2]
                    if action_type in ['ban', 'mute', 'kick', 'restrict']:
                        await DB.update_security_settings(chat_id, night_mode_action=action_type)
                        await _safe_answer(query, f"✅ تم تعيين إجراء الليل: {action_type}")
                        settings = await DB.get_security_settings(chat_id)
                        await safe_edit(query, KeyboardFactory._format_security_text(settings),
                                        reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                                        bot=context.bot)
                        return
                    else:
                        await _safe_answer(query, "❌ نوع إجراء غير صالح", show_alert=True)
                else:
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
            except Exception as e:
                logger.error(f"خطأ في sec_set_night_action: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        # ========== معالجة عقوبات المخالفات (violation) ==========
        if data.startswith("sec_violation_settings:"):
            try:
                _, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                await CallbackHandlers._show_violation_penalties(update, context, query, chat_id, lang)
            except Exception as e:
                logger.error(f"خطأ في sec_violation_settings: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        if data.startswith("sec_set_violation_strikes:"):
            try:
                _, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                StateManager.set(user_id, UserState.WAIT_VIOLATION_STRIKES)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🔢 أرسل عدد المخالفات المسموحة:", bot=context.bot)
            except Exception as e:
                logger.error(f"خطأ في sec_set_violation_strikes: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        if data.startswith("sec_set_violation_duration:"):
            try:
                _, chat_id_str = data.split(":")
                chat_id = int(chat_id_str)
                await CallbackHandlers._show_penalty_durations(update, context, query, chat_id, lang, 'violation')
            except Exception as e:
                logger.error(f"خطأ في sec_set_violation_duration: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        if data.startswith("sec_set_violation_penalty:"):
            try:
                parts = data.split(":")
                if len(parts) >= 3:
                    chat_id = int(parts[1])
                    penalty_type = parts[2]
                    if penalty_type in ['ban', 'mute', 'kick', 'restrict', 'none']:
                        await DB.update_security_settings(chat_id, violation_penalty=penalty_type)
                        await _safe_answer(query, f"✅ تم تعيين عقوبة المخالفات: {penalty_type}")
                        settings = await DB.get_security_settings(chat_id)
                        await safe_edit(query, KeyboardFactory._format_security_text(settings),
                                        reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                                        bot=context.bot)
                        return
                    else:
                        await _safe_answer(query, "❌ نوع عقوبة غير صالح", show_alert=True)
                else:
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
            except Exception as e:
                logger.error(f"خطأ في sec_set_violation_penalty: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
            return

        # ========== بقية المعالجة الأساسية ==========
        base_data = data
        if ':' in data:
            parts = data.split(':')
            known = [
                CB.TOGGLE_AUTO, CB.TOGGLE_REC, CB.TRANSLATION, CB.REFERRAL,
                CB.REMINDER, CB.CONTESTS, CB.SUPPORT_TICKET, CB.CH_LIST,
                CB.POST_ADD, CB.POST_PUB, CB.POST_LIST, CB.POST_REC, CB.PUB_ALL,
                CB.GROUPS, CB.ADMIN, CB.SETTINGS, CB.PLANS, CB.INVOICES,
                CB.REF_CLAIM, CB.REF_LIST, CB.CONTEST_WINNERS, CB.DEVELOPER,
                CB.SUBSCRIBE, CB.SUPPORT, CB.LANGUAGE, CB.TRIAL, CB.HELP,
                CB.CANCEL, CB.CHECK_SUB, CB.TRANS_OFF, CB.REM_TOGGLE_SUB,
                CB.REM_TOGGLE_DAILY, CB.REM_TOGGLE_WEEKLY, CB.REM_SET_DAYS,
                CB.ADMIN_LIST_ADMINS
            ]
            if parts[0] in known:
                base_data = parts[0]

        try:
            # ========== أساسيات ==========
            if base_data == "status_only":
                await _safe_answer(query, await _trans('status', lang, "📊 الحالة"))
                return

            if base_data in [CB.MAIN, CB.BACK]:
                await _safe_answer(query)
                StateManager.clear(user_id)
                context.user_data.clear()
                context.args = []
                await CommandHandlers.start(update, context)
                return

            if base_data == CB.CANCEL:
                StateManager.clear(user_id)
                context.user_data.clear()
                context.args = []
                await _safe_answer(query, "❌ تم الإلغاء")
                return

            if base_data == CB.HELP:
                await _safe_answer(query)
                StateManager.clear(user_id)
                await CommandHandlers.help_command(update, context)
                return

            if base_data == CB.TRIAL:
                await _safe_answer(query, "🔄 جارٍ التفعيل...")
                if await DB.has_used_trial(user_id):
                    await safe_edit(query, await _trans('trial_used', lang, "❌ لقد استخدمت التجربة المجانية بالفعل."), bot=context.bot)
                    return
                days = await DB.activate_trial(user_id)
                if days > 0:
                    text = f"✅ تم تفعيل التجربة المجانية لمدة {days} يوم"
                else:
                    text = "❌ تعذر تفعيل التجربة"
                await safe_edit(query, text, bot=context.bot)
                return

            if base_data == CB.DEVELOPER:
                await _safe_answer(query)
                StateManager.clear(user_id)
                await CommandHandlers.developer(update, context)
                return

            if base_data == CB.SUBSCRIBE:
                await _safe_answer(query)
                StateManager.clear(user_id)
                await CommandHandlers.subscribe(update, context)
                return

            if base_data == CB.SUPPORT:
                await _safe_answer(query)
                StateManager.clear(user_id)
                await CommandHandlers.support(update, context)
                return

            if base_data == CB.LANGUAGE:
                await _safe_answer(query)
                StateManager.clear(user_id)
                await CommandHandlers.language(update, context)
                return

            if base_data == CB.CHECK_SUB:
                await _safe_answer(query)
                StateManager.clear(user_id)
                await CommandHandlers.start(update, context)
                return

            # ========== الإعدادات ==========
            if base_data == CB.SETTINGS:
                auto = "✅" if await DB.get_auto_publish_status(user_id) else "❌"
                rec = "✅" if await DB.get_auto_recycle_status(user_id) else "❌"
                auto_label = await _trans('auto_publish_status', lang, "📤 النشر")
                recycle_label = await _trans('auto_recycle_status', lang, "♻️ التدوير")
                kb = KeyboardFactory.build("settings", lang=lang)
                await safe_edit(query, f"⚙️ الإعدادات\n\n{auto_label}: {auto}\n{recycle_label}: {rec}", reply_markup=kb, bot=context.bot)
                return

            if base_data == CB.TOGGLE_AUTO:
                cur = await DB.get_auto_publish_status(user_id)
                await DB.set_auto_publish(user_id, not cur)
                auto = "✅" if await DB.get_auto_publish_status(user_id) else "❌"
                rec = "✅" if await DB.get_auto_recycle_status(user_id) else "❌"
                auto_label = await _trans('auto_publish_status', lang, "📤 النشر")
                recycle_label = await _trans('auto_recycle_status', lang, "♻️ التدوير")
                kb = KeyboardFactory.build("settings", lang=lang)
                await safe_edit(query, f"⚙️ الإعدادات\n\n{auto_label}: {auto}\n{recycle_label}: {rec}", reply_markup=kb, bot=context.bot)
                return

            if base_data == CB.TOGGLE_REC:
                cur = await DB.get_auto_recycle_status(user_id)
                await DB.set_auto_recycle(user_id, not cur)
                auto = "✅" if await DB.get_auto_publish_status(user_id) else "❌"
                rec = "✅" if await DB.get_auto_recycle_status(user_id) else "❌"
                auto_label = await _trans('auto_publish_status', lang, "📤 النشر")
                recycle_label = await _trans('auto_recycle_status', lang, "♻️ التدوير")
                kb = KeyboardFactory.build("settings", lang=lang)
                await safe_edit(query, f"⚙️ الإعدادات\n\n{auto_label}: {auto}\n{recycle_label}: {rec}", reply_markup=kb, bot=context.bot)
                return

            # ========== الباقات والدفع ==========
            if base_data == CB.PLANS:
                await safe_edit(query, "💎 اختر باقة:", reply_markup=KeyboardFactory.build("plans", lang=lang), bot=context.bot)
                return

            if base_data == "gift_plans":
                plans = await DB.get_gift_plans()
                if not plans:
                    await safe_edit(query, "📭 لا توجد خطط هدايا", bot=context.bot)
                    return
                kb = [[InlineKeyboardButton(f"🎁 {p['days']} يوم - {p['price']} ⭐", callback_data=f"buy_gift:{p['id']}")] for p in plans]
                kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)])
                await safe_edit(query, "💎 اختر خطة هدية:", reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)
                return

            if base_data == "redeem_gift":
                await _safe_answer(query)
                StateManager.clear(user_id)
                await CommandHandlers.redeem_gift(update, context)
                return

            if data.startswith("buy_sub_"):
                await _safe_answer(query, "🔄 جارٍ التحضير...")
                try:
                    days = int(data.split("_")[-1])
                except:
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return
                plan_names = {1: "يوم", 7: "أسبوع", 30: "شهر", 90: "3 أشهر", 365: "سنة"}
                plan_name = plan_names.get(days)
                if not plan_name:
                    await _safe_answer(query, "❌ باقة غير موجودة", show_alert=True)
                    return
                plan = await DB.get_plan_by_name(plan_name)
                if not plan:
                    await _safe_answer(query, "❌ باقة غير موجودة", show_alert=True)
                    return
                invoice_number = await DB.create_invoice(user_id, plan['id'], plan['price'])
                if not invoice_number:
                    await _safe_answer(query, "❌ فشل الدفع", show_alert=True)
                    return
                try:
                    await context.bot.send_invoice(
                        chat_id=user_id,
                        title=f"💎 {plan['name']}",
                        description=plan['description'],
                        payload=json.dumps({'plan_id': plan['id'], 'invoice': invoice_number, 'type': 'subscription'}),
                        provider_token="",
                        currency="XTR",
                        prices=[LabeledPrice(plan['name'], plan['price'])]
                    )
                    await _safe_answer(query, "✅ تم إرسال الفاتورة")
                    await safe_delete_message(query)
                except Exception as e:
                    logger.error(f"❌ فشل إرسال الفاتورة: {e}")
                    await DB.execute("UPDATE invoices SET status='cancelled' WHERE number=?", (invoice_number,))
                    await _safe_answer(query, f"❌ {str(e)[:50]}", show_alert=True)
                return

            if data.startswith("buy_gift:"):
                await _safe_answer(query, "🔄 جارٍ التحضير...")
                try:
                    gift_plan_id = int(data.split(":")[-1])
                except:
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return
                plan = await DB.get_gift_plan(gift_plan_id)
                if not plan:
                    await _safe_answer(query, "❌ خطة الهدية غير موجودة", show_alert=True)
                    return
                invoice_number = await DB.create_invoice(user_id, plan['id'], plan['price'])
                if not invoice_number:
                    await _safe_answer(query, "❌ فشل إنشاء الفاتورة", show_alert=True)
                    return
                try:
                    await context.bot.send_invoice(
                        chat_id=user_id,
                        title=f"🎁 {plan['name']}",
                        description=plan['description'] or "كود هدية",
                        payload=json.dumps({'gift_plan_id': plan['id'], 'invoice': invoice_number, 'type': 'gift'}),
                        provider_token="",
                        currency="XTR",
                        prices=[LabeledPrice(plan['name'], plan['price'])]
                    )
                    await _safe_answer(query, "✅ تم إرسال الفاتورة")
                    await safe_delete_message(query)
                except Exception as e:
                    logger.error(f"❌ فشل إرسال فاتورة الهدية: {e}")
                    await DB.execute("UPDATE invoices SET status='cancelled' WHERE number=?", (invoice_number,))
                    await _safe_answer(query, f"❌ {str(e)[:50]}", show_alert=True)
                return

            if base_data == CB.INVOICES:
                invoices = await DB.get_user_invoices(user_id, 10)
                if not invoices:
                    await safe_edit(query, "📭 لا توجد فواتير", bot=context.bot)
                    return
                text = "🧾 فواتيري\n\n" + "\n".join(f"• #{inv['number']} - {inv['amount']} ⭐" for inv in invoices)
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=CB.BACK)]]), bot=context.bot)
                return

            # ========== الإحالات ==========
            if base_data == CB.REFERRAL:
                stats = await DB.get_referral_stats(user_id)
                code = await DB.get_referral_code(user_id)
                if code.startswith('ref_'):
                    code = code[4:]
                link = f"https://t.me/{CONFIG.BOT_USERNAME}?start=ref_{code}"

                text = (
                    f"🔗 نظام الإحالات\n\n"
                    f"📎 رابطك:\n{link}\n\n"
                    f"👥 المُحالين: {stats['total']}\n"
                    f"🎁 الأيام المتاحة: {stats['available']} يوم"
                )

                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎁 صرف المكافأة", callback_data=CB.REF_CLAIM),
                     InlineKeyboardButton("📋 المُحالين", callback_data=CB.REF_LIST)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)]
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if base_data == CB.REF_CLAIM:
                days = await DB.claim_referral_reward(user_id)
                text = f"✅ تم صرف {days} يوم!" if days > 0 else "📭 لا توجد مكافآت"
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=CB.REFERRAL)]]), bot=context.bot)
                return

            if base_data == CB.REF_LIST:
                refs = await DB.get_referrals_list(user_id)
                text = "📋 المُحالين\n\n" + "\n".join(f"{i}. {_mask_id(r)}" for i, r in enumerate(refs[:20], 1)) if refs else "📭 لا يوجد"
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=CB.REFERRAL)]]), bot=context.bot)
                return

            # ========== التذكيرات ==========
            if base_data in [CB.REM_TOGGLE_SUB, CB.REM_TOGGLE_DAILY, CB.REM_TOGGLE_WEEKLY]:
                settings = await DB.get_reminder_settings(user_id) or {}
                if base_data == CB.REM_TOGGLE_SUB:
                    new_val = not settings.get('subscription_reminder', False)
                    settings['subscription_reminder'] = new_val
                    await DB.update_reminder_settings(user_id, subscription_reminder=new_val)
                elif base_data == CB.REM_TOGGLE_DAILY:
                    new_val = not settings.get('daily_stats_reminder', False)
                    settings['daily_stats_reminder'] = new_val
                    await DB.update_reminder_settings(user_id, daily_stats_reminder=new_val)
                elif base_data == CB.REM_TOGGLE_WEEKLY:
                    new_val = not settings.get('weekly_report', False)
                    settings['weekly_report'] = new_val
                    await DB.update_reminder_settings(user_id, weekly_report=new_val)

                text = (
                    f"⏰ التذكيرات\n\n"
                    f"🔔 الاشتراك: {'✅' if settings.get('subscription_reminder') else '❌'}\n"
                    f"📊 يومي: {'✅' if settings.get('daily_stats_reminder') else '❌'}\n"
                    f"📈 أسبوعي: {'✅' if settings.get('weekly_report') else '❌'}"
                )
                await safe_edit(query, text, reply_markup=KeyboardFactory.build("reminder", lang=lang), bot=context.bot)
                return

            if base_data == CB.REMINDER:
                settings = await DB.get_reminder_settings(user_id) or {}
                text = (
                    f"⏰ التذكيرات\n\n"
                    f"🔔 الاشتراك: {'✅' if settings.get('subscription_reminder') else '❌'}\n"
                    f"📊 يومي: {'✅' if settings.get('daily_stats_reminder') else '❌'}\n"
                    f"📈 أسبوعي: {'✅' if settings.get('weekly_report') else '❌'}"
                )
                await safe_edit(query, text, reply_markup=KeyboardFactory.build("reminder", lang=lang), bot=context.bot)
                return

            if base_data == CB.REM_SET_DAYS:
                StateManager.set(user_id, UserState.WAIT_REM_DAYS)
                await safe_edit(query, "📅 أرسل عدد الأيام (1-30):", bot=context.bot)
                return

            # ========== الترجمة ==========
            if base_data == CB.TRANSLATION:
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
                     InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
                    [InlineKeyboardButton("🇫🇷 Français", callback_data="lang_fr"),
                     InlineKeyboardButton("🇹🇷 Türkçe", callback_data="lang_tr")],
                    [InlineKeyboardButton("🇨🇳 中文", callback_data="lang_zh"),
                     InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
                    [InlineKeyboardButton("🇩🇪 Deutsch", callback_data="lang_de"),
                     InlineKeyboardButton("🇪🇸 Español", callback_data="lang_es")],
                    [InlineKeyboardButton("🇮🇹 Italiano", callback_data="lang_it"),
                     InlineKeyboardButton("🇵🇹 Português", callback_data="lang_pt")],
                    [InlineKeyboardButton("🇯🇵 日本語", callback_data="lang_ja"),
                     InlineKeyboardButton("🇰🇷 한국어", callback_data="lang_ko")],
                    [InlineKeyboardButton("🇮🇷 فارسی", callback_data="lang_fa"),
                     InlineKeyboardButton("🇵🇰 اردو", callback_data="lang_ur")],
                    [InlineKeyboardButton("❌ إيقاف الترجمة", callback_data=CB.TRANS_OFF)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)]
                ])
                await safe_edit(query, "🌐 اختر اللغة:", reply_markup=kb, bot=context.bot)
                return

            if base_data == CB.TRANS_OFF:
                await DB.set_user_language(user_id, 'off')
                await safe_edit(query, "✅ تم إيقاف الترجمة", bot=context.bot)
                return

            # ========== المسابقات ==========
            if base_data == CB.CONTESTS:
                await _safe_answer(query)
                StateManager.clear(user_id)
                await CommandHandlers.contests(update, context)
                return

            if base_data == CB.CONTEST_WINNERS:
                winners = await DB.get_contest_winners(10)
                text = "🏆 الفائزون\n\n" + "\n".join(f"• {w['title']} - {_mask_id(w['winner_id'])}" for w in winners) if winners else "📭 لا يوجد"
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=CB.BACK)]]), bot=context.bot)
                StateManager.clear(user_id)
                return

            # ========== الدعم ==========
            if base_data == CB.SUPPORT_TICKET:
                StateManager.set(user_id, UserState.SUPPORT_MODE)
                await safe_send(context.bot, user_id, "📞 أرسل رسالتك:")
                await _safe_answer(query)
                return

            # ========== القنوات ==========
            if base_data == CB.CH_ADD:
                if not await DB.has_active_subscription(user_id) and user_id != CONFIG.PRIMARY_OWNER_ID:
                    await _safe_answer(query, "❌ يتطلب اشتراك نشط", show_alert=True)
                    return
                StateManager.set(user_id, UserState.WAIT_CHANNEL)
                await safe_edit(query, "📡 أرسل معرف القناة:", bot=context.bot)
                return

            if base_data == CB.CH_LIST:
                await CallbackHandlers._show_channel_list(update, context, query, user_id, lang)
                return

            if data.startswith(CB.CH_SEL + ":"):
                try:
                    ch_id = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return
                if await DB.set_active_channel(user_id, ch_id):
                    await safe_edit(query, "✅ تم تحديد القناة!", bot=context.bot)
                else:
                    await _safe_answer(query, "❌ لا يمكنك تحديد هذه القناة", show_alert=True)
                return

            if data.startswith(CB.CH_DEL + ":"):
                try:
                    ch_id = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return
                if await DB.delete_channel(user_id, ch_id):
                    await _safe_answer(query, "✅ تم الحذف")
                    context.user_data['channel_page'] = 0
                    await CallbackHandlers._show_channel_list(update, context, query, user_id, lang)
                    return
                else:
                    await _safe_answer(query, "❌ فشل", show_alert=True)
                    return

            if data.startswith(CB.CH_STATS + ":"):
                try:
                    ch_id = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return
                stats = await DB.get_channel_stats(user_id, ch_id)
                text = f"📊 إحصائيات\n\n📝 {stats['total']}\n✅ {stats['published']}\n⏳ {stats['unpublished']}"
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=CB.CH_LIST)]]), bot=context.bot)
                return

            # ========== المنشورات ==========
            if base_data == CB.POST_ADD:
                if not await DB.has_active_subscription(user_id) and user_id != CONFIG.PRIMARY_OWNER_ID:
                    await _safe_answer(query, "❌ انتهى اشتراكك!", show_alert=True)
                    return
                active = await DB.get_active_channel(user_id)
                if not active:
                    await safe_edit(query, "❌ لا توجد قناة نشطة", bot=context.bot)
                    return
                StateManager.set(user_id, UserState.ADDING_POSTS)
                await safe_edit(query, "📥 أرسل المنشورات:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ إنهاء", callback_data="finish_posts")]]), bot=context.bot)
                return

            if base_data == "finish_posts":
                StateManager.clear(user_id)
                await _safe_answer(query, "✅ تم الإنهاء")
                return

            if base_data == CB.POST_PUB:
                active = await DB.get_active_channel(user_id)
                if not active:
                    await safe_edit(query, "❌ لا توجد قناة", bot=context.bot)
                    return
                post = await DB.get_next_post(active)
                if post is None:
                    await safe_edit(query, "📭 لا توجد منشورات", bot=context.bot)
                    return
                ch_info = await DB.get_channel_info(user_id, active)
                if ch_info:
                    asyncio.create_task(CallbackHandlers._publish_single(context.bot, active, ch_info['channel_id'], post))
                    await _safe_answer(query, "✅ بدأ النشر")
                return

            if base_data == CB.POST_LIST:
                await CallbackHandlers._show_post_list(update, context, query, user_id, lang)
                return

            if base_data == CB.POST_REC:
                active = await DB.get_active_channel(user_id)
                if active:
                    count = await DB.reset_posts(user_id, active)
                    await safe_edit(query, f"♻️ {count} منشور!", bot=context.bot)
                else:
                    await _safe_answer(query, "❌ لا توجد قناة نشطة", show_alert=True)
                return

            if data.startswith(CB.POST_DEL + ":"):
                try:
                    post_id = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return
                active = await DB.get_active_channel(user_id)
                if active and await DB.delete_post(user_id, post_id, active):
                    await _safe_answer(query, "✅ تم الحذف")
                    await CallbackHandlers._show_post_list(update, context, query, user_id, lang)
                    return
                else:
                    await _safe_answer(query, "❌ فشل", show_alert=True)
                    return

            if base_data == CB.POST_CLEAR:
                active = await DB.get_active_channel(user_id)
                if active:
                    await DB.execute("DELETE FROM posts WHERE channel_db_id=?", (active,))
                    await safe_edit(query, "✅ تم مسح جميع المنشورات", bot=context.bot)
                else:
                    await _safe_answer(query, "❌ لا توجد قناة نشطة", show_alert=True)
                return

            if base_data == CB.PUB_ALL:
                channels = await DB.get_user_channels(user_id)
                if not channels:
                    await safe_edit(query, "❌ لا توجد قنوات", bot=context.bot)
                    return
                task = asyncio.create_task(CallbackHandlers._publish_all(context.bot, user_id, channels))
                ACTIVE_TASKS.add(task)
                task.add_done_callback(ACTIVE_TASKS.discard)
                await _safe_answer(query, "✅ بدأ النشر الجماعي")
                return

            # ========== المجموعات ==========
            if base_data == CB.GROUPS:
                groups = await DB.get_user_groups(user_id)
                if not groups:
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{CONFIG.BOT_USERNAME}?startgroup")]])
                    await safe_edit(query, "📭 لا توجد مجموعات", reply_markup=kb, bot=context.bot)
                    return
                text = "👥 مجموعاتي\n\n"
                kb = []
                for g in groups:
                    text += f"{'✅' if not g['banned'] else '⛔'} {g['chat_name']}\n"
                    kb.append([InlineKeyboardButton(f"⚙️ أمان {g['chat_name'][:15]}", callback_data=f"{CB.GRP_SET}:{g['chat_id']}")])
                    kb.append([InlineKeyboardButton("🗑️ حذف", callback_data=f"grp_del:{g['chat_id']}")])
                kb.append([InlineKeyboardButton("🔙", callback_data=CB.BACK)])
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)
                return

            if data.startswith("grp_del:"):
                try:
                    chat_id = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return
                if await DB.delete_group(chat_id):
                    await safe_edit(query, "✅ تم حذف المجموعة", bot=context.bot)
                else:
                    await _safe_answer(query, "❌ فشل", show_alert=True)
                return

            if data.startswith(CB.GRP_SET + ":"):
                try:
                    chat_id = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return
                context.user_data['security_chat_id'] = chat_id
                if not await is_authorized_in_group(context.bot, chat_id, user_id):
                    await _safe_answer(query, "❌ لا صلاحية", show_alert=True)
                    return
                settings = await DB.get_security_settings(chat_id)
                await safe_edit(query, KeyboardFactory._format_security_text(settings), reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang), bot=context.bot)
                return

            # ========== لوحة الأدمن ==========
            if base_data == CB.ADMIN:
                if not CONFIG.is_developer(user_id):
                    await _safe_answer(query, "❌ غير مصرح", show_alert=True)
                    return
                kb = KeyboardFactory.build("admin_panel", lang=lang)
                await safe_edit(query, "👑 لوحة الأدمن", reply_markup=kb, bot=context.bot)
                return

            # ========== admin_disable_force ==========
            if data == "admin_disable_force":
                if not CONFIG.is_developer(user_id):
                    await _safe_answer(query, "❌ غير مصرح", show_alert=True)
                    return
                await DB.set_setting('force_subscribe_channel', '')
                await safe_edit(query, "✅ تم تعطيل الاشتراك الإجباري", bot=context.bot)
                return

            # ========== admin_restore_sel (مرادف لـ admin_restore) ==========
            if data == "admin_restore_sel" or data == "admin_show_backups":
                if not CONFIG.is_developer(user_id):
                    await _safe_answer(query, "❌ غير مصرح", show_alert=True)
                    return
                await CallbackHandlers._show_restore_backups(update, context, query, user_id)
                return

            # ========== توجيه المعالجات ==========
            if data.startswith("sec_"):
                await CallbackHandlers._handle_security(update, context, query, user_id, lang)
                return

            if data.startswith("admin_") or data == "admin_grant_free" or data == "admin_disable_force" or data == "admin_restore_sel" or data == "admin_show_backups":
                if CONFIG.is_developer(user_id):
                    await CallbackHandlers._handle_admin(update, context, query, user_id, lang)
                else:
                    await _safe_answer(query, "❌ غير مصرح", show_alert=True)
                return

            if data.startswith("auto_reply_") or data.startswith("auto_reply_menu:"):
                await CallbackHandlers._handle_auto_reply(update, context, query, user_id, lang)
                return

            if data.startswith("sched_open:") or data.startswith("sched_"):
                await CallbackHandlers._handle_schedule(update, context, query, user_id)
                return

            if data.startswith("ban_") or data.startswith("act_") or data.startswith("pen_"):
                await CallbackHandlers._handle_advanced_actions(update, context, query, user_id)
                return

            if data.startswith("contest_") or data.startswith(CB.DECLARE_WINNER_SEL + ":"):
                await CallbackHandlers._handle_contests(update, context, query, user_id)
                return

            if data in (CB.ADMIN_IMPORT_REPLIES, CB.ADMIN_IMPORT_GITHUB):
                await CallbackHandlers._handle_import(update, context, query, user_id)
                return

            if data.startswith("lang_"):
                lang_set = data.split("_")[-1]
                if lang_set in ['ar', 'en', 'fr', 'tr', 'zh', 'ru', 'de', 'es', 'it', 'pt', 'ja', 'ko', 'fa', 'ur', 'nl', 'pl', 'hi', 'off']:
                    await DB.set_user_language(user_id, lang_set)
                    await _safe_answer(query, f"✅ {lang_set}")
                    await CommandHandlers.start(update, context)
                else:
                    await _safe_answer(query, "❌ لغة غير مدعومة", show_alert=True)
                return

            # ========== ترقيم الصفحات ==========
            if data == "ch_page_prev":
                context.user_data['channel_page'] = max(0, context.user_data.get('channel_page', 0) - 1)
                await CallbackHandlers._show_channel_list(update, context, query, user_id, lang)
                return
            if data == "ch_page_next":
                context.user_data['channel_page'] = context.user_data.get('channel_page', 0) + 1
                await CallbackHandlers._show_channel_list(update, context, query, user_id, lang)
                return
            if data == "post_page_prev":
                context.user_data['post_page'] = max(0, context.user_data.get('post_page', 0) - 1)
                await CallbackHandlers._show_post_list(update, context, query, user_id, lang)
                return
            if data == "post_page_next":
                context.user_data['post_page'] = context.user_data.get('post_page', 0) + 1
                await CallbackHandlers._show_post_list(update, context, query, user_id, lang)
                return

            # ========== معالجات اللوحة الخاصة ==========
            if data in ["panel_lock", "panel_unlock", "panel_close"]:
                await CallbackHandlers._handle_panel(update, context, query, user_id, data)
                return

            await _safe_answer(query, "⚠️ غير متوفر", show_alert=True)

        except BadRequest as e:
            if "query is too old" not in str(e).lower():
                logger.error(f"❌ BadRequest: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"❌ Callback error: {e}", exc_info=True)
        finally:
            if time.monotonic() - start_time > 1.0:
                logger.warning(f"🐢 زر بطيء {data}")

    # ============ دوال النشر ============
    @staticmethod
    async def _publish_single(bot, ch_db_id, ch_tele, post) -> bool:
        try:
            post_id = post.get('id')
            text = post.get('text', '')
            media_type = post.get('media_type')
            media_file_id = post.get('media_file_id')
            caption = text[:MAX_CAPTION_LENGTH] if text else None

            if media_type == 'photo' and media_file_id:
                await bot.send_photo(ch_tele, media_file_id, caption=caption)
            elif media_type == 'video' and media_file_id:
                await bot.send_video(ch_tele, media_file_id, caption=caption)
            elif media_type == 'document' and media_file_id:
                await bot.send_document(ch_tele, media_file_id, caption=caption)
            elif media_type == 'audio' and media_file_id:
                await bot.send_audio(ch_tele, media_file_id, caption=caption)
            elif media_type == 'voice' and media_file_id:
                await bot.send_voice(ch_tele, media_file_id)
                if text:
                    try:
                        await bot.send_message(ch_tele, text)
                    except Exception as e:
                        logger.warning(f"فشل إرسال النص المصاحب للصوت: {e}")
            elif media_type == 'animation' and media_file_id:
                await bot.send_animation(ch_tele, media_file_id, caption=caption)
            elif media_type == 'sticker' and media_file_id:
                await bot.send_sticker(ch_tele, media_file_id)
                if text:
                    try:
                        await bot.send_message(ch_tele, text)
                    except Exception as e:
                        logger.warning(f"فشل إرسال النص المصاحب للملصق: {e}")
            elif media_type == 'video_note' and media_file_id:
                await bot.send_video_note(ch_tele, media_file_id)
                if text:
                    try:
                        await bot.send_message(ch_tele, text)
                    except Exception as e:
                        logger.warning(f"فشل إرسال النص المصاحب لفيديو نوت: {e}")
            else:
                if text and len(text) > MAX_MESSAGE_LENGTH:
                    for i in range(0, len(text), MAX_MESSAGE_LENGTH):
                        await bot.send_message(ch_tele, text[i:i+MAX_MESSAGE_LENGTH])
                else:
                    await bot.send_message(ch_tele, text if text else ".")

            if post_id:
                await DB.mark_post_published(post_id)
            await DB.update_last_publish(ch_db_id)
            await DB.update_next_publish(ch_db_id)
            return True
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            if post.get('id'):
                await DB.increment_post_fail(post['id'])
            return False
        except Forbidden as e:
            await DB.execute("UPDATE user_channels SET banned=1 WHERE id=?", (ch_db_id,))
            if post.get('id'):
                await DB.increment_post_fail(post['id'])
            return False
        except Exception as e:
            logger.error(f"❌ فشل النشر: {e}")
            if post.get('id'):
                await DB.increment_post_fail(post['id'])
            return False

    @staticmethod
    async def _publish_all(bot, user_id, channels):
        published = 0
        failed = 0
        tasks = []
        banned_count = 0
        no_post_count = 0
        for ch in channels:
            if ch.get('banned'):
                banned_count += 1
                continue
            post = await DB.get_next_post(ch['id'])
            if post:
                ch_info = await DB.get_channel_info(user_id, ch['id'])
                if ch_info:
                    tasks.append((ch['id'], ch_info['channel_id'], post))
            else:
                no_post_count += 1
        if not tasks:
            if banned_count == len(channels):
                msg = "❌ جميع القنوات محظورة"
            elif no_post_count == len(channels) - banned_count:
                msg = "📭 لا توجد منشورات للنشر"
            else:
                msg = "📭 لا توجد منشورات صالحة للنشر"
            await safe_send(bot, user_id, msg)
            return
        sem = asyncio.Semaphore(MAX_CONCURRENT_PUBLISH)

        async def run(task):
            async with sem:
                return await CallbackHandlers._publish_single(bot, task[0], task[1], task[2])

        BATCH = 10
        for i in range(0, len(tasks), BATCH):
            batch = tasks[i:i+BATCH]
            results = await asyncio.gather(*(run(t) for t in batch), return_exceptions=True)
            for r in results:
                if r is True:
                    published += 1
                else:
                    failed += 1
        await safe_send(bot, user_id, f"✅ تم نشر {published} | ❌ فشل {failed}")

    # ============ دوال عرض القوائم ============
    @staticmethod
    async def _show_channel_list(update, context, query, user_id, lang=None):
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        channels = await DB.get_user_channels(user_id)
        if not channels:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(KeyboardFactory.get_text("ch_add", lang), callback_data=CB.CH_ADD)],
                [InlineKeyboardButton(KeyboardFactory.get_text("back", lang), callback_data=CB.BACK)]
            ])
            await safe_edit(query, "📭 لا توجد قنوات!", reply_markup=kb, bot=context.bot)
            return
        page = int(context.user_data.get('channel_page', 0))
        per_page = 5
        total_pages = max(1, (len(channels) + per_page - 1) // per_page)
        if page >= total_pages:
            page = total_pages - 1
        context.user_data['channel_page'] = page
        page_channels = channels[page*per_page:(page+1)*per_page]
        text = f"📡 قنواتي (صفحة {page+1}/{total_pages})\n\n"
        kb = []
        for ch in page_channels:
            st = "✅" if not ch['banned'] else "🚫"
            text += f"{st} {ch['channel_name']}\n"
            kb.append([
                InlineKeyboardButton(f"📌 {ch['channel_name'][:20]}", callback_data=f"{CB.CH_SEL}:{ch['id']}"),
                InlineKeyboardButton("📅", callback_data=f"sched_open:{ch['id']}")
            ])
            kb.append([
                InlineKeyboardButton("📊", callback_data=f"{CB.CH_STATS}:{ch['id']}"),
                InlineKeyboardButton("🗑️", callback_data=f"{CB.CH_DEL}:{ch['id']}")
            ])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️", callback_data="ch_page_prev"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("➡️", callback_data="ch_page_next"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton(KeyboardFactory.get_text("ch_add", lang), callback_data=CB.CH_ADD)])
        kb.append([InlineKeyboardButton(KeyboardFactory.get_text("back", lang), callback_data=CB.BACK)])
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    @staticmethod
    async def _show_post_list(update, context, query, user_id, lang=None):
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        active = await DB.get_active_channel(user_id)
        if not active:
            await safe_edit(query, "❌ لا توجد قناة نشطة", bot=context.bot)
            return
        per_page = 5
        total = await DB.fetchval("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (active,), default=0)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = int(context.user_data.get('post_page', 0))
        if page >= total_pages:
            page = total_pages - 1
        context.user_data['post_page'] = page
        posts = await DB.fetchall(
            "SELECT id, text, published FROM posts WHERE channel_db_id=? ORDER BY created_at ASC LIMIT ? OFFSET ?",
            (active, per_page, page * per_page)
        )
        text = f"📋 منشوراتي (صفحة {page+1}/{total_pages})\n\n"
        kb = []
        for p in posts:
            text += f"🆔 {p['id']}: {(p['text'] or '')[:30]}\n"
            kb.append([InlineKeyboardButton(f"🗑️ حذف {p['id']}", callback_data=f"{CB.POST_DEL}:{p['id']}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️", callback_data="post_page_prev"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("➡️", callback_data="post_page_next"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton("🔄 إعادة تدوير", callback_data=CB.POST_REC)])
        kb.append([InlineKeyboardButton("🧹 مسح الكل", callback_data=CB.POST_CLEAR)])
        kb.append([InlineKeyboardButton("🔙", callback_data=CB.BACK)])
        display_text = text if posts else "📭 لا يوجد منشورات"
        await safe_edit(query, display_text, reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    # ============ معالجات الأمان ============
    @staticmethod
    async def _handle_security(update, context, query, user_id, lang=None, return_to_main=False):
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        data = query.data
        parts = data.split(":")
        if len(parts) >= 2 and parts[1].isdigit():
            chat_id = int(parts[1])
        else:
            chat_id = context.user_data.get('security_chat_id')
            if not chat_id and update.effective_chat:
                chat_id = update.effective_chat.id
        if chat_id is None:
            await _safe_answer(query, "❌ لم يتم تحديد المجموعة", show_alert=True)
            return
        action = parts[0].replace("sec_", "")
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await _safe_answer(query, "❌ لا صلاحية", show_alert=True)
            return

        try:
            toggle_map = {
                "links": "delete_links", "mentions": "mentions", "slow": "slow_mode",
                "video": "delete_videos", "audio": "delete_audio", "anim": "delete_animation",
                "service": "delete_service", "doc": "delete_documents", "sticker": "delete_stickers",
                "forward": "delete_forwarded", "poll": "delete_polls", "game": "delete_games",
                "voice": "delete_voice", "videonote": "delete_video_note", "welcome": "welcome_enabled",
                "goodbye": "goodbye_enabled", "flood": "antiflood_enabled", "night": "night_mode_enabled",
                "approve_join": "auto_approve_join", "reject_join": "auto_reject_join", "nsfw": "nsfw_enabled",
                "slow_mode_seconds": "slow_mode_seconds",
            }

            if action in toggle_map:
                col = toggle_map[action]
                settings = await DB.get_security_settings(chat_id)
                new_val = 1 - settings.get(col, 0)
                update_data = {col: new_val}
                if action == "approve_join" and new_val:
                    update_data['auto_reject_join'] = 0
                elif action == "reject_join" and new_val:
                    update_data['auto_approve_join'] = 0
                await DB.update_security_settings(chat_id, **update_data)
                settings[col] = new_val
                if action == "approve_join" and new_val:
                    settings['auto_reject_join'] = 0
                elif action == "reject_join" and new_val:
                    settings['auto_approve_join'] = 0
                await safe_edit(query, KeyboardFactory._format_security_text(settings), reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang), bot=context.bot)
                return

            elif action == "warn":
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تفعيل/تعطيل", callback_data=f"sec_warn_toggle:{chat_id}")],
                    [InlineKeyboardButton("🔢 عدد التحذيرات", callback_data=f"sec_warn_count:{chat_id}")],
                    [InlineKeyboardButton("⚖️ عقوبة التحذير", callback_data=f"sec_warn_penalty:{chat_id}")],
                    [InlineKeyboardButton("⏱️ مدة العقوبة", callback_data=f"sec_warn_penalty_duration:{chat_id}")],
                    [InlineKeyboardButton("🔙", callback_data=f"grp_set:{chat_id}")]
                ])
                await safe_edit(query, "⚠️ إدارة التحذيرات:", reply_markup=kb, bot=context.bot)
                await _safe_answer(query)
                return

            elif action == "warn_penalty":
                await CallbackHandlers._show_warn_penalty_types(update, context, query, chat_id, lang)
                return

            elif action == "warn_toggle":
                settings = await DB.get_security_settings(chat_id)
                new_val = 1 - settings.get('warn_enabled', 0)
                await DB.update_security_settings(chat_id, warn_enabled=new_val)
                settings['warn_enabled'] = new_val
                await safe_edit(query, KeyboardFactory._format_security_text(settings), reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang), bot=context.bot)
                return

            elif action == "warn_count":
                StateManager.set(user_id, UserState.WAIT_WARN_COUNT)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🔢 أرسل عدد التحذيرات:", bot=context.bot)
                return

            elif action == "penalty":
                await CallbackHandlers._show_penalty_types(update, context, query, chat_id, lang)
                return

            elif action == "del_pen":
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚫 حظر", callback_data=f"sec_set_del_penalty:ban:{chat_id}"),
                     InlineKeyboardButton("🔇 كتم", callback_data=f"sec_set_del_penalty:mute:{chat_id}")],
                    [InlineKeyboardButton("👢 طرد", callback_data=f"sec_set_del_penalty:kick:{chat_id}"),
                     InlineKeyboardButton("🔒 تقييد", callback_data=f"sec_set_del_penalty:restrict:{chat_id}")],
                    [InlineKeyboardButton("🚫 بدون عقوبة", callback_data=f"sec_set_del_penalty:none:{chat_id}")],
                    [InlineKeyboardButton("⏱️ مدة العقوبة", callback_data=f"sec_set_del_penalty_duration:{chat_id}")],
                    [InlineKeyboardButton("🔙", callback_data=f"grp_set:{chat_id}")]
                ])
                await safe_edit(query, "🚫 اختر عقوبة الحذف:", reply_markup=kb, bot=context.bot)
                return

            elif action == "banned_words":
                await CallbackHandlers._show_banned_words_menu(update, context, query, chat_id, lang)
                return

            elif action == "toggle_banned_words":
                settings = await DB.get_security_settings(chat_id)
                new_val = 1 - settings.get('delete_banned_words', 0)
                await DB.update_security_settings(chat_id, delete_banned_words=new_val)
                settings['delete_banned_words'] = new_val
                await CallbackHandlers._show_banned_words_menu(update, context, query, chat_id, lang)
                return

            elif action == "close":
                await safe_delete_message(query)
                StateManager.clear(user_id)
                context.user_data.clear()
                return

            elif action == "antiflood_settings":
                await CallbackHandlers._show_antiflood_settings(update, context, query, chat_id, lang)
                return

            elif action == "night_settings":
                await CallbackHandlers._show_night_settings(update, context, query, chat_id, lang)
                return

            elif action == "auto_reply_menu":
                await CallbackHandlers._show_auto_reply_menu(update, context, query, chat_id, lang)
                return

            elif action == "adv_act":
                await CallbackHandlers._show_advanced_actions(update, context, query, chat_id, lang)
                return

            elif action == "act_log":
                await CallbackHandlers._show_admin_logs(update, context, query, chat_id, lang)
                StateManager.clear(user_id)
                return

            elif action == "maxlen":
                StateManager.set(user_id, UserState.WAIT_MAX_LEN)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "📏 أرسل الحد الأقصى لطول الرسالة:", bot=context.bot)
                return

            elif action == "slow_mode_seconds":
                StateManager.set(user_id, UserState.WAIT_SLOW_MODE_SECONDS)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "⏱️ أرسل مدة الوضع البطيء بالثواني:", bot=context.bot)
                return

            elif action == "welcome_text":
                StateManager.set(user_id, UserState.WAIT_WELCOME_TEXT)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "📝 أرسل نص الترحيب:", bot=context.bot)
                return

            elif action == "goodbye_text":
                StateManager.set(user_id, UserState.WAIT_GOODBYE_TEXT)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "📝 أرسل نص الوداع:", bot=context.bot)
                return

            elif action == "penalty_durations":
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⏱️ مدة الكتم", callback_data=f"sec_set_mute_duration:{chat_id}"),
                     InlineKeyboardButton("⏱️ مدة الحظر", callback_data=f"sec_set_ban_duration:{chat_id}")],
                    [InlineKeyboardButton("⏱️ مدة التقييد", callback_data=f"sec_set_restrict_duration:{chat_id}"),
                     InlineKeyboardButton("⏱️ مدة عقوبة التحذير", callback_data=f"sec_warn_penalty_duration:{chat_id}")],
                    [InlineKeyboardButton("⏱️ مدة الفيضان", callback_data=f"sec_antiflood_duration:{chat_id}"),
                     InlineKeyboardButton("⏱️ مدة الليل", callback_data=f"sec_night_duration:{chat_id}")],
                    [InlineKeyboardButton("⏱️ مدة عقوبة الحذف", callback_data=f"sec_set_del_penalty_duration:{chat_id}")],
                    [InlineKeyboardButton("🔙", callback_data=f"grp_set:{chat_id}")]
                ])
                await safe_edit(query, "⏱️ اختر نوع العقوبة لتعديل مدتها:", reply_markup=kb, bot=context.bot)
                return

            # ===== معالجات جديدة للفيضان والليل =====
            elif action == "set_antiflood_messages":
                StateManager.set(user_id, UserState.WAIT_ANTIFLOOD_MESSAGES)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "📊 أرسل عدد الرسائل المسموحة:", bot=context.bot)
                return

            elif action == "set_antiflood_seconds":
                StateManager.set(user_id, UserState.WAIT_ANTIFLOOD_SECONDS)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "⏱️ أرسل عدد الثواني:", bot=context.bot)
                return

            elif action == "antiflood_penalty":
                await CallbackHandlers._show_penalty_type_selection(update, context, query, chat_id, lang, 'antiflood_penalty')
                return

            elif action.startswith("set_antiflood_penalty"):
                await _safe_answer(query, "⏳ جارٍ التحميل...")
                return

            elif action == "set_night_start":
                StateManager.set(user_id, UserState.WAIT_NIGHT_START)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🌙 أرسل وقت البدء (HH:MM):", bot=context.bot)
                return

            elif action == "set_night_end":
                StateManager.set(user_id, UserState.WAIT_NIGHT_END)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🌙 أرسل وقت النهاية (HH:MM):", bot=context.bot)
                return

            elif action == "night_action":
                await CallbackHandlers._show_penalty_type_selection(update, context, query, chat_id, lang, 'night_action')
                return

            elif action.startswith("set_night_action"):
                await _safe_answer(query, "⏳ جارٍ التحميل...")
                return

            # ===== معالجة عقوبات المخالفات (violation) =====
            elif action == "violation_settings":
                await CallbackHandlers._show_violation_penalties(update, context, query, chat_id, lang)
                return

            elif action == "violation_penalty":
                await CallbackHandlers._show_penalty_type_selection(update, context, query, chat_id, lang, 'violation_penalty')
                return

            elif action.startswith("set_violation_strikes") or action.startswith("set_violation_duration") or action.startswith("set_violation_penalty"):
                await _safe_answer(query, "⏳ جارٍ التحميل...")
                return

            else:
                await _safe_answer(query, "⚠️ غير معروف", show_alert=True)
                return

        except Exception as e:
            logger.error(f"خطأ في إعدادات الأمان: {e}", exc_info=True)
            await _safe_answer(query, "❌ حدث خطأ", show_alert=True)

    @staticmethod
    async def _show_warn_penalty_types(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 حظر", callback_data=f"set_warn_penalty:ban:{chat_id}"),
             InlineKeyboardButton("🔇 كتم", callback_data=f"set_warn_penalty:mute:{chat_id}")],
            [InlineKeyboardButton("👢 طرد", callback_data=f"set_warn_penalty:kick:{chat_id}"),
             InlineKeyboardButton("🔒 تقييد", callback_data=f"set_warn_penalty:restrict:{chat_id}")],
            [InlineKeyboardButton("🔙", callback_data=f"grp_set:{chat_id}")]
        ])
        await safe_edit(query, "⚖️ اختر عقوبة تجاوز التحذيرات:", reply_markup=kb, bot=context.bot)
        await _safe_answer(query)

    @staticmethod
    async def _show_banned_words_menu(update, context, query, chat_id, lang):
        settings = await DB.get_security_settings(chat_id)
        is_enabled = settings.get('delete_banned_words', 0)
        toggle_text = "✅ تفعيل الحذف" if not is_enabled else "❌ تعطيل الحذف"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"ban_add:{chat_id}"),
             InlineKeyboardButton("📋 القائمة", callback_data=f"ban_list:{chat_id}")],
            [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=f"ban_rem:{chat_id}")],
            [InlineKeyboardButton(toggle_text, callback_data=f"sec_toggle_banned_words:{chat_id}")],
            [InlineKeyboardButton("🔙", callback_data=f"grp_set:{chat_id}")]
        ])
        await safe_edit(query, "🚫 إدارة الكلمات المحظورة:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_penalty_type_selection(update, context, query, chat_id, lang, setting_key):
        penalty_types = [
            ("🔇 كتم", "mute"),
            ("🚫 حظر", "ban"),
            ("👢 طرد", "kick"),
            ("🔒 تقييد", "restrict"),
            ("🚫 بدون عقوبة", "none"),
        ]
        kb = []
        for label, ptype in penalty_types:
            callback = f"sec_set_{setting_key}:{chat_id}:{ptype}"
            kb.append([InlineKeyboardButton(label, callback_data=callback)])
        kb.append([InlineKeyboardButton("🔙", callback_data=f"grp_set:{chat_id}")])
        await safe_edit(query, f"🚫 اختر نوع العقوبة لـ {setting_key.replace('_', ' ')}:", reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    @staticmethod
    async def _show_penalty_durations(update, context, query, chat_id, lang, penalty_type='mute'):
        if penalty_type == 'kick':
            await _safe_answer(query, "✅ عقوبة الطرد لا تحتاج مدة")
            settings = await DB.get_security_settings(chat_id)
            await safe_edit(query, KeyboardFactory._format_security_text(settings), reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang), bot=context.bot)
            return

        durations = [
            ("دائم", 0),
            ("نصف ساعة", 1800),
            ("ساعة", 3600),
            ("يوم", 86400),
            ("أسبوع", 604800),
            ("عشرة أيام", 864000),
            ("شهر", 2592000),
        ]
        kb = []
        for i in range(0, len(durations), 2):
            row = []
            name, secs = durations[i]
            row.append(InlineKeyboardButton(name, callback_data=f"set_duration:{penalty_type}:{chat_id}:{secs}"))
            if i + 1 < len(durations):
                name2, secs2 = durations[i+1]
                row.append(InlineKeyboardButton(name2, callback_data=f"set_duration:{penalty_type}:{chat_id}:{secs2}"))
            kb.append(row)
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")])
        type_name = {
            'mute': 'كتم', 'ban': 'حظر', 'restrict': 'تقييد',
            'antiflood': 'الفيضان', 'night': 'الوضع الليلي',
            'warn_penalty': 'عقوبة التحذير', 'delete_penalty': 'عقوبة الحذف',
            'violation': 'عقوبات المخالفات'
        }.get(penalty_type, penalty_type)
        await safe_edit(query, f"⏱️ اختر مدة {type_name}:", reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    @staticmethod
    async def _show_violation_penalties(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔢 عدد المخالفات", callback_data=f"sec_set_violation_strikes:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة العقوبة", callback_data=f"sec_set_violation_duration:{chat_id}")],
            [InlineKeyboardButton("⚖️ نوع العقوبة", callback_data=f"sec_violation_penalty:{chat_id}")],
            [InlineKeyboardButton("🔙", callback_data=f"grp_set:{chat_id}")]
        ])
        await safe_edit(query, "🚨 إعدادات عقوبات المخالفات:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_antiflood_settings(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("عدد الرسائل", callback_data=f"sec_set_antiflood_messages:{chat_id}"),
             InlineKeyboardButton("الثواني", callback_data=f"sec_set_antiflood_seconds:{chat_id}")],
            [InlineKeyboardButton("نوع العقوبة", callback_data=f"sec_antiflood_penalty:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة العقوبة", callback_data=f"sec_antiflood_duration:{chat_id}")],
            [InlineKeyboardButton("🔙", callback_data=f"grp_set:{chat_id}")]
        ])
        await safe_edit(query, "🌊 إعدادات الفيضان:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_night_settings(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("وقت البدء", callback_data=f"sec_set_night_start:{chat_id}"),
             InlineKeyboardButton("وقت النهاية", callback_data=f"sec_set_night_end:{chat_id}")],
            [InlineKeyboardButton("نوع الإجراء", callback_data=f"sec_night_action:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة الإجراء", callback_data=f"sec_night_duration:{chat_id}")],
            [InlineKeyboardButton("🔙", callback_data=f"grp_set:{chat_id}")]
        ])
        await safe_edit(query, "🌙 إعدادات الوضع الليلي:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_auto_reply_menu(update, context, query, chat_id, lang):
        kb = KeyboardFactory.build("auto_reply", chat_id=chat_id, lang=lang)
        await safe_edit(query, "🤖 إعدادات الردود التلقائية:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_advanced_actions(update, context, query, chat_id, lang):
        kb = KeyboardFactory.build("advanced_actions", chat_id=chat_id, lang=lang)
        await safe_edit(query, "🛠️ الإجراءات المتقدمة:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_admin_logs(update, context, query, chat_id, lang):
        logs = await DB.get_admin_logs(chat_id, 10)
        text = "📋 سجل المشرفين\n\n" + "\n".join(f"• {l['admin_id']} → {l['action']}" for l in logs) if logs else "📭 لا يوجد"
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"grp_set:{chat_id}")]]), bot=context.bot)

    @staticmethod
    async def _show_penalty_types(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("حظر", callback_data=f"sec_penalty_ban:{chat_id}"),
             InlineKeyboardButton("كتم", callback_data=f"sec_penalty_mute:{chat_id}")],
            [InlineKeyboardButton("طرد", callback_data=f"sec_penalty_kick:{chat_id}"),
             InlineKeyboardButton("تقييد", callback_data=f"sec_penalty_restrict:{chat_id}")],
            [InlineKeyboardButton("بدون عقوبة", callback_data=f"sec_penalty_none:{chat_id}")],
            [InlineKeyboardButton("🔙", callback_data=f"grp_set:{chat_id}")]
        ])
        await safe_edit(query, "🚫 اختر نوع العقوبة:", reply_markup=kb, bot=context.bot)

    # ============ معالجات الأدمن الكاملة ============
    @staticmethod
    async def _handle_admin(update, context, query, user_id, lang=None):
        if not CONFIG.is_developer(user_id):
            await _safe_answer(query, "❌ غير مصرح", show_alert=True)
            return

        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'

        data = query.data

        try:
            if data == "admin_grant_free":
                StateManager.set(user_id, UserState.WAIT_GRANT_FREE)
                await safe_edit(query, "🎁 أرسل: معرف_المستخدم عدد_الأيام", bot=context.bot)
                return

            elif data == CB.ADMIN_USERS:
                stats = await DB.get_user_stats()
                text = f"👥 المستخدمون\n\n👥 الإجمالي: {stats['users']}\n⛔ المحظورون: {stats['banned']}"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⛔ المحظورين", callback_data=CB.ADMIN_BANNED)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)]
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            elif data == CB.ADMIN_BANNED:
                banned_users = await DB.fetchall("SELECT user_id FROM users WHERE banned=1 LIMIT 20")
                text = "⛔ المحظورين\n\n" + "\n".join(str(u['user_id']) for u in banned_users) if banned_users else "📭 لا يوجد محظورون"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ فك حظر الكل", callback_data=CB.ADMIN_UNBAN_ALL)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)]
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            elif data == CB.ADMIN_UNBAN_ALL:
                await DB.execute("UPDATE users SET banned=0 WHERE banned=1")
                await safe_edit(query, "✅ تم إلغاء حظر الجميع", bot=context.bot)
                return

            elif data == CB.ADMIN_STATS:
                stats = await DB.get_general_stats()
                text = (f"📊 إحصائيات عامة\n\n"
                        f"👥 المستخدمون: {stats['users']}\n"
                        f"📡 القنوات: {stats['channels']}\n"
                        f"👥 المجموعات: {stats['groups']}\n"
                        f"📝 المنشورات: {stats['posts']}\n"
                        f"✅ المنشورة: {stats['published']}\n"
                        f"🧾 الفواتير: {stats['invoices']}\n"
                        f"🎫 التذاكر المعلقة: {stats['tickets']}")
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)]])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            elif data == CB.ADMIN_CHANNELS:
                await CallbackHandlers._show_admin_channels(update, context, query, user_id, lang)
                return

            elif data.startswith("admin_toggle_ch:"):
                try:
                    ch_db_id = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return
                row = await DB.fetchone("SELECT banned FROM user_channels WHERE id=?", (ch_db_id,))
                if row:
                    new_val = 0 if row['banned'] else 1
                    await DB.execute("UPDATE user_channels SET banned=? WHERE id=?", (new_val, ch_db_id))
                    await _safe_answer(query, "✅ تم فك الحظر" if new_val==0 else "✅ تم حظر القناة")
                    await CallbackHandlers._show_admin_channels(update, context, query, user_id, lang)
                return

            elif data == CB.ADMIN_GROUPS:
                await CallbackHandlers._show_admin_groups(update, context, query, user_id, lang)
                return

            elif data.startswith("admin_toggle_gr:"):
                try:
                    chat_id = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return
                row = await DB.fetchone("SELECT banned FROM bot_groups WHERE chat_id=?", (chat_id,))
                if row:
                    new_val = 0 if row['banned'] else 1
                    if new_val == 1:
                        try:
                            await context.bot.leave_chat(chat_id)
                            leave_msg = "تم حظر المجموعة ومغادرتها"
                        except Exception as e:
                            leave_msg = "تم حظر المجموعة (تعذر المغادرة)"
                    else:
                        leave_msg = "تم فك حظر المجموعة"
                    await DB.execute("UPDATE bot_groups SET banned=? WHERE chat_id=?", (new_val, chat_id))
                    await _safe_answer(query, f"✅ {leave_msg}")
                    await CallbackHandlers._show_admin_groups(update, context, query, user_id, lang)
                return

            elif data == CB.ADMIN_ADD_ADMIN:
                StateManager.set(user_id, UserState.WAIT_ADMIN_ADD)
                await safe_edit(query, "👑 أرسل معرف المشرف:", bot=context.bot)
                return

            elif data == CB.ADMIN_REM_ADMIN:
                StateManager.set(user_id, UserState.WAIT_ADMIN_REM)
                await safe_edit(query, "🗑️ أرسل معرف المشرف:", bot=context.bot)
                return

            elif data == CB.ADMIN_LIST_ADMINS:
                admins = await DB.get_admin_list()
                text = "👑 المشرفون\n\n" + "\n".join(f"• {a['user_id']}" for a in admins) if admins else "📭 لا يوجد"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إضافة", callback_data=CB.ADMIN_ADD_ADMIN),
                     InlineKeyboardButton("🗑️ إزالة", callback_data=CB.ADMIN_REM_ADMIN)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)]
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            elif data == CB.ADMIN_BROADCAST:
                StateManager.set(user_id, UserState.WAIT_BROADCAST)
                await safe_edit(query, "📨 أرسل الرسالة:", bot=context.bot)
                return

            elif data == CB.ADMIN_INVOICES:
                invoices = await DB.fetchall("SELECT number, amount, status FROM invoices ORDER BY id DESC LIMIT 20")
                text = "🧾 الفواتير\n\n" + "\n".join(f"• {i['number']} - {i['amount']} ⭐ - {i['status']}" for i in invoices) if invoices else "📭 لا توجد"
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)]])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            elif data == CB.ADMIN_BACKUP:
                await _safe_answer(query, "⏳ جارٍ النسخ...")
                task = asyncio.create_task(CallbackHandlers._do_backup(context, user_id))
                ACTIVE_TASKS.add(task)
                task.add_done_callback(ACTIVE_TASKS.discard)
                return

            elif data == CB.ADMIN_RESTORE:
                await CallbackHandlers._show_restore_backups(update, context, query, user_id)
                return

            elif data == CB.ADMIN_RESTORE_SEL:
                await CallbackHandlers._show_restore_backups(update, context, query, user_id)
                return

            elif data.startswith("admin_restore_file:"):
                fname = data.split(":", 1)[1]
                backup_file = PATHS.BACKUPS / fname
                if backup_file.resolve().parent != PATHS.BACKUPS.resolve():
                    await _safe_answer(query, "❌ مسار غير صالح", show_alert=True)
                    return
                if not backup_file.exists():
                    await _safe_answer(query, "❌ الملف غير موجود", show_alert=True)
                    return
                try:
                    pre_restore_backup = PATHS.BACKUPS / f"pre_restore_{TimeUtils.mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
                    shutil.copy2(PATHS.DB, pre_restore_backup)
                    shutil.copy2(backup_file, PATHS.DB)
                    await safe_edit(query, "✅ تمت الاستعادة بنجاح! أعد تشغيل البوت لتفعيل التغييرات.", bot=context.bot)
                except Exception as e:
                    await safe_edit(query, f"❌ فشل الاستعادة: {str(e)[:100]}", bot=context.bot)
                return

            elif data == CB.ADMIN_RAM:
                ram = get_ram_usage()
                text = f"🖥️ الرام\n\n💾 الإجمالي: {ram['total']} GB\n📊 المستخدم: {ram['used']} GB\n📈 النسبة: {ram['percent']}%"
                await safe_edit(query, text, bot=context.bot)
                return

            elif data == CB.ADMIN_METRICS:
                stats = await DB.get_general_stats()
                text = (
                    f"📊 مقاييس النظام\n\n"
                    f"👥 المستخدمون: {stats['users']}\n"
                    f"📡 القنوات: {stats['channels']}\n"
                    f"👥 المجموعات: {stats['groups']}\n"
                    f"📝 المنشورات: {stats['posts']}\n"
                    f"✅ المنشورة: {stats['published']}\n"
                    f"🧾 الفواتير: {stats['invoices']}\n"
                    f"🎫 تذاكر معلقة: {stats['tickets']}\n"
                    f"💾 حجم قاعدة البيانات: {PATHS.DB.stat().st_size / 1024:.1f} KB"
                )
                await safe_edit(query, text, bot=context.bot)
                return

            elif data == CB.ADMIN_UPTIME:
                uptime = time.monotonic() - context.bot_data.get('start_time', time.monotonic())
                hours, remainder = divmod(uptime, 3600)
                minutes, seconds = divmod(remainder, 60)
                text = f"⏳ فترة التشغيل: {int(hours)} ساعة {int(minutes)} دقيقة {int(seconds)} ثانية"
                await safe_edit(query, text, bot=context.bot)
                return

            elif data == CB.ADMIN_TICKETS:
                tickets = await DB.get_tickets()
                text = "🎫 التذاكر المعلقة\n\n" + "\n".join(f"• #{t['ticket_number']} - {t['user_id']}: {t['message'][:50]}" for t in tickets[:10]) if tickets else "📭 لا توجد تذاكر"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑️ حذف الكل", callback_data=CB.ADMIN_DEL_TICKETS)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)]
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            elif data == CB.ADMIN_DEL_TICKETS:
                await DB.delete_all_tickets()
                await safe_edit(query, "✅ تم حذف جميع التذاكر", bot=context.bot)
                return

            elif data == CB.ADMIN_PAYMENT_LOGS:
                logs = await DB.fetchall("SELECT user_id, event_type, created_at FROM payment_logs ORDER BY id DESC LIMIT 20")
                text = "💳 سجلات الدفع\n\n" + "\n".join(f"• {l['user_id']} - {l['event_type']} ({l['created_at']})" for l in logs) if logs else "📭 لا توجد"
                await safe_edit(query, text, bot=context.bot)
                return

            elif data == CB.ADMIN_SET_UPDATE_CH:
                StateManager.set(user_id, UserState.WAIT_UPDATE_CH)
                await safe_edit(query, "📢 أرسل معرف قناة التحديثات:", bot=context.bot)
                return

            elif data == CB.ADMIN_SEND_UPDATE:
                StateManager.set(user_id, UserState.WAIT_UPDATE)
                await safe_edit(query, "📝 أرسل نص التحديث:", bot=context.bot)
                return

            elif data == CB.ADMIN_SHOW_UPDATE:
                ch = await DB.get_updates_channel()
                text = f"📢 قناة التحديثات: {ch}" if ch else "📭 لم يتم تعيين قناة تحديثات"
                await safe_edit(query, text, bot=context.bot)
                return

            elif data == CB.ADMIN_SET_LOG_CH:
                StateManager.set(user_id, UserState.WAIT_LOG_CH)
                await safe_edit(query, "📋 أرسل معرف قناة السجلات:", bot=context.bot)
                return

            elif data == CB.ADMIN_LOG_CH:
                ch = await DB.get_log_channel()
                text = f"📋 قناة السجلات: {ch}" if ch else "📭 لم يتم تعيين قناة سجلات"
                await safe_edit(query, text, bot=context.bot)
                return

            elif data == CB.ADMIN_FORCE_SUB:
                sub = await DB.get_force_subscribe_channel()
                text = f"🔒 الاشتراك الإجباري: {'✅ مفعل' if sub else '❌ معطل'}\n"
                if sub:
                    text += f"القناة: {sub}"
                await safe_edit(query, text, bot=context.bot)
                return

            elif data == CB.ADMIN_SET_FORCE:
                StateManager.set(user_id, UserState.WAIT_FORCE)
                await safe_edit(query, "🔒 أرسل معرف قناة الاشتراك الإجباري:", bot=context.bot)
                return

            elif data == CB.ADMIN_REFRESH_CACHE:
                await safe_edit(query, "🔄 تم تحديث الكاش", bot=context.bot)
                return

            elif data == CB.ADMIN_BANNED_CH:
                banned_channels = await DB.fetchall("SELECT channel_id, channel_name FROM user_channels WHERE banned=1 LIMIT 20")
                text = "🚫 القنوات المحظورة\n\n" + "\n".join(f"• {c['channel_name']} ({c['channel_id']})" for c in banned_channels) if banned_channels else "📭 لا توجد"
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ تفعيل الكل", callback_data=CB.ADMIN_ACTIVATE_CH)],
                                           [InlineKeyboardButton("🔙", callback_data=CB.ADMIN)]])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            elif data == CB.ADMIN_ACTIVATE_CH:
                await DB.execute("UPDATE user_channels SET banned=0 WHERE banned=1")
                await safe_edit(query, "✅ تم تفعيل جميع القنوات", bot=context.bot)
                return

            elif data == CB.ADMIN_BANNED_GR:
                banned_groups = await DB.fetchall("SELECT chat_id, chat_name FROM bot_groups WHERE banned=1 LIMIT 20")
                text = "🚫 المجموعات المحظورة\n\n" + "\n".join(f"• {g['chat_name']} ({g['chat_id']})" for g in banned_groups) if banned_groups else "📭 لا توجد"
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CB.ADMIN_UNBAN_GR)],
                                           [InlineKeyboardButton("🔙", callback_data=CB.ADMIN)]])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            elif data == CB.ADMIN_UNBAN_GR:
                await DB.execute("UPDATE bot_groups SET banned=0 WHERE banned=1")
                await safe_edit(query, "✅ تم إلغاء حظر جميع المجموعات", bot=context.bot)
                return

            elif data == CB.ADMIN_REPLIES:
                replies = await DB.fetchall("SELECT keyword FROM auto_replies WHERE chat_id=-1 LIMIT 30")
                text = "💬 الردود العامة\n\n" + "\n".join(f"• {r['keyword']}" for r in replies) if replies else "📭 لا توجد"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إضافة", callback_data="admin_add_reply"),
                     InlineKeyboardButton("🗑️ حذف", callback_data="admin_del_reply")],
                    [InlineKeyboardButton("📤 تصدير", callback_data=CB.ADMIN_EXPORT_REPLIES),
                     InlineKeyboardButton("📥 استيراد", callback_data=CB.ADMIN_IMPORT_REPLIES)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)]
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            elif data == "admin_add_reply":
                StateManager.set(user_id, UserState.WAIT_KEYWORD)
                context.user_data['auto_chat'] = -1
                await safe_edit(query, "📝 أرسل الكلمة:", bot=context.bot)
                return

            elif data == "admin_del_reply":
                StateManager.set(user_id, UserState.WAIT_AUTO_DEL)
                context.user_data['auto_chat'] = -1
                await safe_edit(query, "🗑️ أرسل الكلمة:", bot=context.bot)
                return

            elif data == "admin_list_replies":
                replies = await DB.fetchall("SELECT keyword FROM auto_replies WHERE chat_id=-1 LIMIT 50")
                text = "📋 قائمة الردود العامة\n\n" + "\n".join(f"• {r['keyword']}" for r in replies) if replies else "📭 لا توجد"
                await safe_edit(query, text, bot=context.bot)
                return

            elif data == CB.ADMIN_EXPORT_REPLIES:
                file_path = await DB.export_auto_replies_to_file()
                if file_path:
                    try:
                        with open(file_path, 'rb') as f:
                            await context.bot.send_document(chat_id=user_id, document=f, filename=Path(file_path).name)
                    except Exception as e:
                        await safe_send(context.bot, user_id, f"❌ فشل الإرسال: {e}")
                    finally:
                        try:
                            os.remove(file_path)
                        except OSError:
                            pass
                else:
                    await safe_edit(query, "📭 لا توجد ردود", bot=context.bot)
                return

            elif data == CB.ADMIN_IMPORT_REPLIES:
                StateManager.set(user_id, UserState.WAIT_IMPORT_FILE)
                await safe_edit(query, "📤 أرسل ملف JSON:", bot=context.bot)
                return

            elif data == CB.ADMIN_IMPORT_GITHUB:
                StateManager.set(user_id, UserState.WAIT_GITHUB_URL)
                await safe_edit(query, "📥 أرسل الرابط:", bot=context.bot)
                return

            elif data == CB.ADMIN_BANNED_WORDS:
                words = await DB.get_banned_words(-1)
                text = "🚫 الكلمات المحظورة العامة\n\n" + "\n".join(f"• {w}" for w in words[:30]) if words else "📭 لا توجد"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إضافة", callback_data="admin_add_banned"),
                     InlineKeyboardButton("🗑️ حذف", callback_data="admin_rem_banned")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)]
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            elif data == "admin_add_banned":
                StateManager.set(user_id, UserState.WAIT_GLOBAL_BAN)
                await safe_edit(query, "📝 أرسل الكلمة:", bot=context.bot)
                return

            elif data == "admin_rem_banned":
                StateManager.set(user_id, UserState.WAIT_REM_GLOBAL_BAN)
                await safe_edit(query, "🗑️ أرسل الكلمة:", bot=context.bot)
                return

            elif data == "admin_list_banned":
                words = await DB.get_banned_words(-1)
                text = "📋 قائمة الكلمات المحظورة العامة\n\n" + "\n".join(f"• {w}" for w in words) if words else "📭 لا توجد"
                await safe_edit(query, text, bot=context.bot)
                return

            elif data == CB.ADMIN_CREATE_CONTEST:
                StateManager.set(user_id, UserState.WAIT_CONTEST_TITLE)
                await safe_edit(query, "🏆 أرسل العنوان:", bot=context.bot)
                return

            elif data == CB.ADMIN_DECLARE_WINNER:
                contests = await DB.get_active_contests(5)
                if not contests:
                    await safe_edit(query, "📭 لا توجد مسابقات نشطة", bot=context.bot)
                    return
                kb = []
                for c in contests:
                    kb.append([InlineKeyboardButton(f"🏆 {c['title'][:20]}", callback_data=f"{CB.DECLARE_WINNER_SEL}:{c['id']}")])
                kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
                await safe_edit(query, "🏆 اختر المسابقة:", reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)
                return

            elif data == CB.ADMIN_DEL_CONTEST:
                contests = await DB.fetchall("SELECT id, title FROM contests WHERE status='active' LIMIT 10")
                if not contests:
                    await safe_edit(query, "📭 لا توجد مسابقات", bot=context.bot)
                    return
                kb = []
                for c in contests:
                    kb.append([InlineKeyboardButton(f"🗑️ {c['title'][:20]}", callback_data=f"admin_delete_contest:{c['id']}")])
                kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
                await safe_edit(query, "🗑️ اختر المسابقة للحذف:", reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)
                return

            elif data.startswith("admin_delete_contest:"):
                try:
                    contest_id = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return
                if await DB.delete_contest(contest_id, user_id):
                    await safe_edit(query, "✅ تم حذف المسابقة", bot=context.bot)
                else:
                    await _safe_answer(query, "❌ فشل", show_alert=True)
                return

            # ===== admin_disable_force =====
            elif data == "admin_disable_force":
                await DB.set_setting('force_subscribe_channel', '')
                await safe_edit(query, "✅ تم تعطيل الاشتراك الإجباري", bot=context.bot)
                return

            # ===== admin_restore_sel & admin_show_backups =====
            elif data in ["admin_restore_sel", "admin_show_backups"]:
                await CallbackHandlers._show_restore_backups(update, context, query, user_id)
                return

            else:
                await _safe_answer(query, "⚠️ غير متوفر", show_alert=True)

        except BadRequest as e:
            if "query is too old" not in str(e).lower():
                logger.error(f"خطأ في لوحة الأدمن: {e}", exc_info=True)
                await _safe_answer(query, "❌ حدث خطأ", show_alert=True)
        except Exception as e:
            logger.error(f"خطأ في لوحة الأدمن: {e}", exc_info=True)
            await _safe_answer(query, "❌ حدث خطأ", show_alert=True)

    @staticmethod
    async def _show_restore_backups(update, context, query, user_id):
        backups = sorted(PATHS.BACKUPS.glob("backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not backups:
            await safe_edit(query, "📭 لا توجد نسخ احتياطية", bot=context.bot)
            return
        kb = []
        for b in backups[:10]:
            fname = b.name
            kb.append([InlineKeyboardButton(f"📁 {fname}", callback_data=f"admin_restore_file:{fname}")])
        kb.append([InlineKeyboardButton("🔙", callback_data=CB.ADMIN)])
        await safe_edit(query, "📂 اختر نسخة احتياطية للاستعادة:", reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    @staticmethod
    async def _show_admin_channels(update, context, query, user_id, lang):
        channels = await DB.fetchall(
            "SELECT id, channel_id, channel_name, banned FROM user_channels ORDER BY channel_name LIMIT 50"
        )
        kb = []
        for c in channels:
            action = "🔓 فك حظر" if c['banned'] else "🔒 حظر"
            icon = "🚫" if c['banned'] else "✅"
            kb.append([
                InlineKeyboardButton(
                    f"{icon} {c['channel_name'][:20]} - {action}",
                    callback_data=f"admin_toggle_ch:{c['id']}"
                )
            ])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
        text = f"📡 إدارة القنوات ({len(channels)})\n\nاضغط على القناة للتبديل بين الحظر وفك الحظر:"
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    @staticmethod
    async def _show_admin_groups(update, context, query, user_id, lang):
        groups = await DB.fetchall(
            "SELECT chat_id, chat_name, banned FROM bot_groups ORDER BY chat_name LIMIT 50"
        )
        kb = []
        for g in groups:
            action = "🔓 فك حظر" if g['banned'] else "🔒 حظر"
            icon = "🚫" if g['banned'] else "✅"
            kb.append([
                InlineKeyboardButton(
                    f"{icon} {g['chat_name'][:20]} - {action}",
                    callback_data=f"admin_toggle_gr:{g['chat_id']}"
                )
            ])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
        text = f"👥 إدارة المجموعات ({len(groups)})\n\nاضغط على المجموعة للتبديل بين الحظر وفك الحظر:"
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    # ============ معالجات الردود التلقائية ============
    @staticmethod
    async def _handle_auto_reply(update, context, query, user_id, lang=None):
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        data = query.data
        parts = data.split(":")
        action = parts[0].replace("auto_reply_", "")

        chat_id = None
        if len(parts) >= 2 and parts[1].lstrip('-').isdigit():
            chat_id = int(parts[1])
        else:
            chat_id = context.user_data.get('auto_chat') or context.user_data.get('security_chat_id')
            if not chat_id and update.effective_chat:
                chat_id = update.effective_chat.id

        if chat_id is None:
            await _safe_answer(query, "❌ لم يتم تحديد المجموعة", show_alert=True)
            return

        if chat_id != -1 and not await is_authorized_in_group(context.bot, chat_id, user_id):
            await _safe_answer(query, "❌ لا صلاحية", show_alert=True)
            return

        if action == "menu":
            kb = KeyboardFactory.build("auto_reply", chat_id=chat_id, lang=lang)
            await safe_edit(query, "🤖 إعدادات الردود التلقائية:", reply_markup=kb, bot=context.bot)
            return

        try:
            if action == "toggle":
                settings = await DB.get_auto_reply_settings(chat_id) or {}
                new_status = not settings.get('enabled', False)
                await DB.update_auto_reply_settings(chat_id, enabled=new_status)
                kb = KeyboardFactory.build("auto_reply", chat_id=chat_id, lang=lang)
                text = (
                    f"🤖 إعدادات الردود التلقائية\n\n"
                    f"الحالة: {'✅ مفعلة' if new_status else '❌ معطلة'}\n"
                    f"للمشرفين فقط: {'✅ نعم' if settings.get('only_admins') else '❌ لا'}"
                )
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            elif action == "admins":
                settings = await DB.get_auto_reply_settings(chat_id) or {}
                new_status = not settings.get('only_admins', 0)
                await DB.update_auto_reply_settings(chat_id, only_admins=new_status)
                kb = KeyboardFactory.build("auto_reply", chat_id=chat_id, lang=lang)
                text = (
                    f"🤖 إعدادات الردود التلقائية\n\n"
                    f"الحالة: {'✅ مفعلة' if settings.get('enabled') else '❌ معطلة'}\n"
                    f"للمشرفين فقط: {'✅ نعم' if new_status else '❌ لا'}"
                )
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            elif action == "add":
                StateManager.set(user_id, UserState.WAIT_AUTO_KEY)
                context.user_data['auto_chat'] = chat_id
                await safe_edit(query, "📝 أرسل الكلمة:", bot=context.bot)
                return

            elif action == "del":
                StateManager.set(user_id, UserState.WAIT_AUTO_DEL)
                context.user_data['auto_chat'] = chat_id
                await safe_edit(query, "🗑️ أرسل الكلمة:", bot=context.bot)
                return

            elif action == "reset":
                await DB.reset_auto_replies(chat_id)
                await safe_edit(query, "✅ تم الحذف", bot=context.bot)
                return

            elif action == "list":
                rows = await DB.fetchall("SELECT keyword FROM auto_replies WHERE chat_id=? LIMIT 20", (chat_id,))
                text = "📋 الردود\n\n" + "\n".join(f"• {r['keyword']}" for r in rows) if rows else "📭 لا يوجد"
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"auto_reply_menu:{chat_id}")]]), bot=context.bot)
                return

            elif action == "stats":
                stats = await DB.get_auto_reply_stats(chat_id, 20)
                if stats:
                    text = "📊 إحصائيات الردود\n\n"
                    for s in stats:
                        source = "🌐 عام" if s['source'] == 'global' else "👥 مجموعة"
                        text += f"• {s['keyword']} ({source}): {s['usage_count']} استخدام\n"
                else:
                    text = "📭 لا توجد ردود"
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"auto_reply_menu:{chat_id}")]]), bot=context.bot)
                return

        except Exception as e:
            logger.error(f"خطأ في الردود التلقائية: {e}", exc_info=True)
            await _safe_answer(query, "❌ حدث خطأ", show_alert=True)

    # ============ معالجات الجدولة ============
    @staticmethod
    async def _handle_schedule(update, context, query, user_id):
        data = query.data
        parts = data.split(":")
        if len(parts) < 2:
            return
        action = parts[0].replace("sched_", "")
        try:
            ch_id = int(parts[1])
        except (ValueError, IndexError):
            await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
            return
        if not await _is_channel_owner(user_id, ch_id):
            await _safe_answer(query, "❌ لا تملك هذه القناة", show_alert=True)
            return

        if action == "open":
            await CallbackHandlers._show_schedule_menu(update, context, query, ch_id, user_id)
            return
        elif action == "min":
            StateManager.set(user_id, UserState.WAIT_MIN)
            context.user_data['schedule_ch'] = ch_id
            await safe_edit(query, "📅 أرسل الدقائق:", bot=context.bot)
            return
        elif action == "hour":
            StateManager.set(user_id, UserState.WAIT_HOUR)
            context.user_data['schedule_ch'] = ch_id
            await safe_edit(query, "📅 أرسل الساعات:", bot=context.bot)
            return
        elif action == "day":
            StateManager.set(user_id, UserState.WAIT_DAY)
            context.user_data['schedule_ch'] = ch_id
            await safe_edit(query, "📅 أرسل الأيام:", bot=context.bot)
            return
        elif action == "time":
            StateManager.set(user_id, UserState.WAIT_PUB_TIME)
            context.user_data['schedule_ch'] = ch_id
            await safe_edit(query, "🕐 أرسل الوقت HH:MM:", bot=context.bot)
            return

    @staticmethod
    async def _show_schedule_menu(update, context, query, ch_id, user_id):
        lang = await DB.get_user_language(user_id) or 'ar'
        kb = KeyboardFactory.build("channel_settings", chat_id=ch_id, lang=lang)
        await safe_edit(query, "📅 جدولة القناة", reply_markup=kb, bot=context.bot)

    # ============ معالجات الإجراءات المتقدمة والعقوبات ============
    @staticmethod
    async def _handle_advanced_actions(update, context, query, user_id):
        data = query.data
        parts = data.split(":")
        if len(parts) < 2:
            return
        action = parts[0].replace("act_", "").replace("pen_", "").replace("ban_", "")
        try:
            chat_id = int(parts[1])
        except (ValueError, IndexError):
            await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
            return

        if chat_id == -1 and (parts[0].startswith("act_") or parts[0].startswith("pen_")):
            await _safe_answer(query, "❌ معرف غير صالح", show_alert=True)
            return

        if chat_id != -1 and not await is_authorized_in_group(context.bot, chat_id, user_id):
            await _safe_answer(query, "❌ لا صلاحية", show_alert=True)
            return
        if chat_id == -1 and not CONFIG.is_developer(user_id):
            await _safe_answer(query, "❌ غير مصرح", show_alert=True)
            return

        if parts[0].startswith("ban_"):
            if action == "add":
                StateManager.set(user_id, UserState.WAIT_GROUP_BAN if chat_id != -1 else UserState.WAIT_GLOBAL_BAN)
                context.user_data['ban_chat'] = chat_id
                await safe_edit(query, "📝 أرسل الكلمة:", bot=context.bot)
                return
            elif action == "list":
                words = await DB.get_banned_words(chat_id)
                text = "🚫 الكلمات\n\n" + "\n".join(f"• {w}" for w in words[:50]) if words else "📭 لا يوجد"
                await safe_edit(query, text, bot=context.bot)
                return
            elif action == "rem":
                StateManager.set(user_id, UserState.WAIT_REM_GROUP_BAN if chat_id != -1 else UserState.WAIT_REM_GLOBAL_BAN)
                context.user_data['ban_chat'] = chat_id
                await safe_edit(query, "🗑️ أرسل الكلمة:", bot=context.bot)
                return

        elif parts[0].startswith("act_"):
            user_actions = {
                "ban": (UserState.WAIT_BAN, "🚫 أرسل معرف المستخدم:"),
                "mute": (UserState.WAIT_MUTE, "🔇 أرسل معرف المستخدم:"),
                "warn": (UserState.WAIT_WARN, "⚠️ أرسل معرف المستخدم:"),
                "kick": (UserState.WAIT_KICK, "👢 أرسل معرف المستخدم:"),
                "restrict": (UserState.WAIT_RESTRICT, "🔒 أرسل معرف المستخدم:"),
                "unban": (UserState.WAIT_UNBAN, "🔓 أرسل معرف المستخدم:"),
            }
            if action in user_actions:
                state, msg = user_actions[action]
                StateManager.set(user_id, state)
                context.user_data['adv_chat'] = chat_id
                await safe_edit(query, msg, bot=context.bot)
                return
            elif action == "pin":
                StateManager.set(user_id, UserState.WAIT_PIN)
                context.user_data['adv_chat'] = chat_id
                await safe_edit(query, "📌 قم بالرد على الرسالة المطلوب تثبيتها ثم أرسل أي شيء:", bot=context.bot)
                return
            elif action == "log":
                await CallbackHandlers._show_admin_logs(update, context, query, chat_id, lang=None)
                StateManager.clear(user_id)
                return

        elif parts[0].startswith("pen_"):
            penalty_types = {'ban', 'mute', 'kick', 'restrict', 'none'}
            if action in penalty_types:
                await DB.update_security_settings(chat_id, auto_penalty=action)
                await _safe_answer(query, f"✅ تم تعيين العقوبة: {action}")
                return

        await _safe_answer(query, "⚠️ غير معروف", show_alert=True)

    # ============ معالجات اللوحة الخاصة (panel) ============
    @staticmethod
    async def _handle_panel(update, context, query, user_id, data):
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await _safe_answer(query, "❌ لا صلاحية", show_alert=True)
            return
        if data == "panel_lock":
            await context.bot.set_chat_permissions(chat_id, permissions=ChatPermissions(can_send_messages=False))
            await safe_edit(query, "🔒 تم قفل المجموعة", bot=context.bot)
        elif data == "panel_unlock":
            await context.bot.set_chat_permissions(chat_id, permissions=ChatPermissions(can_send_messages=True))
            await safe_edit(query, "🔓 تم فتح المجموعة", bot=context.bot)
        elif data == "panel_close":
            StateManager.clear(user_id)
            context.user_data.clear()
            await safe_delete_message(query)

    # ============ معالجات المسابقات ============
    @staticmethod
    async def _handle_contests(update, context, query, user_id):
        data = query.data
        try:
            if data.startswith(CB.CONTEST_JOIN + ":"):
                try:
                    cid = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return
                contest = await DB.get_contest_by_id(cid)
                if not contest or contest['status'] != 'active':
                    await _safe_answer(query, "❌ المسابقة غير متاحة", show_alert=True)
                    StateManager.clear(user_id)
                    return
                StateManager.set(user_id, UserState.WAIT_CONTEST_ANSWER)
                context.user_data['contest_join'] = cid
                await safe_edit(query, "📝 أرسل إجابتك:", bot=context.bot)
            elif data == CB.CONTEST_WINNERS:
                winners = await DB.get_contest_winners(10)
                text = "🏆 الفائزون\n\n" + "\n".join(f"• {w['title']} - {w['winner_id']}" for w in winners) if winners else "📭 لا يوجد"
                await safe_edit(query, text, bot=context.bot)
                StateManager.clear(user_id)
            elif data.startswith(CB.DECLARE_WINNER_SEL + ":"):
                if not CONFIG.is_developer(user_id):
                    await _safe_answer(query, "❌ غير مصرح", show_alert=True)
                    return
                try:
                    cid = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await _safe_answer(query, "❌ بيانات غير صالحة", show_alert=True)
                    return
                winner = await DB.fetchone("SELECT user_id FROM contest_participants WHERE contest_id=? ORDER BY RANDOM() LIMIT 1", (cid,))
                if winner:
                    if await DB.declare_winner(cid, winner['user_id']):
                        await safe_edit(query, f"✅ الفائز: {winner['user_id']}", bot=context.bot)
                        try:
                            await context.bot.send_message(winner['user_id'], "🎉 مبروك! فزت بالمسابقة!")
                        except:
                            pass
                    else:
                        await _safe_answer(query, "❌ فشل", show_alert=True)
                else:
                    await safe_edit(query, "❌ لا يوجد مشاركون", bot=context.bot)
        except Exception as e:
            logger.error(f"خطأ في المسابقات: {e}", exc_info=True)
            await _safe_answer(query, "❌ حدث خطأ", show_alert=True)

    # ============ معالجات الاستيراد ============
    @staticmethod
    async def _handle_import(update, context, query, user_id):
        if not CONFIG.is_developer(user_id):
            await _safe_answer(query, "❌ غير مصرح", show_alert=True)
            return
        if query.data == CB.ADMIN_IMPORT_REPLIES:
            StateManager.set(user_id, UserState.WAIT_IMPORT_FILE)
            await safe_edit(query, "📤 أرسل ملف JSON:", bot=context.bot)
        elif query.data == CB.ADMIN_IMPORT_GITHUB:
            StateManager.set(user_id, UserState.WAIT_GITHUB_URL)
            await safe_edit(query, "📥 أرسل الرابط:", bot=context.bot)

    # ============ النسخ الاحتياطي ============
    @staticmethod
    async def _do_backup(context, user_id):
        try:
            PATHS.BACKUPS.mkdir(parents=True, exist_ok=True)
            backup_file = PATHS.BACKUPS / f"backup_{TimeUtils.mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
            success = await DB.backup_database(backup_file)
            if not success:
                await safe_send(context.bot, user_id, "❌ فشل النسخ الاحتياطي")
                return
            backups = sorted(PATHS.BACKUPS.glob("backup_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in backups[MAX_BACKUPS:]:
                old.unlink(missing_ok=True)
            with open(backup_file, 'rb') as f:
                await context.bot.send_document(chat_id=user_id, document=f, filename=backup_file.name)
        except Exception as e:
            logger.error(f"❌ فشل النسخ: {e}")
            await safe_send(context.bot, user_id, f"❌ فشل النسخ: {str(e)[:100]}")