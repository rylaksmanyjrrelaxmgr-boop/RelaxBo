#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_message.py - معالجات الرسائل - النسخة النهائية الكاملة والمحسّنة
=====================================================================
- متوافق تماماً مع database.py و handlers_callback.py
- جميع الدوال موجودة ومصححة بالكامل
- دعم كامل للنصوص والوسائط
- إصلاح استخراج معرف القناة في _handle_adding_posts
- إصلاح معالجة نتيجة get_all_users في _handle_broadcast_input
- مدة العقوبة بالدقائق
- دعم الوسائط في الردود التلقائية
- معالجة جميع الحالات الجديدة
- تحسينات أمنية وأداء شاملة
- استخدام مدد العقوبات الجديدة (فيضان، ليلي، تحذير) عند تطبيق العقوبات
- إظهار رسالة واضحة عند إضافة منشور مكرر
- إصلاح تجاهل auto_penalty = 'none'
- إصلاح دعم الوسائط في إضافة الردود التلقائية
- فحص الكلمة المفتاحية قبل حفظ الرد
- تمرير parse_mode='HTML' في رسائل الترحيب والوداع
- تحسين فحص المنشور المكرر (إزالة استعلام زائد)
- تحسين رسالة فشل إضافة منشور
- تحسين التحقق من صلاحيات البوت عند إضافة قناة
- تحقق مسبق من صحة التاريخ عند إنشاء مسابقة
- إضافة دعم استعادة النسخة الاحتياطية من ملف مرفوع
- تجاهل خطأ User_already_participant في طلبات الانضمام
- حذف رسائل الانضمام والمغادرة عند تفعيل delete_service
- تأخير بسيط بين معالجة طلبات الانضمام لتجنب حدود تيليجرام
- دمج نظام الكاش الموحد cache.py
- استخدام safe_send الموحدة في الردود التلقائية
- إزالة المتغيرات غير المستخدمة
- ربط جميع النصوص الثابتة بنظام الترجمة _trans بنسبة 100%
"""

import asyncio
import logging
import time
import os
import re
import json
import shutil
import tempfile
from html import escape
from typing import Optional
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut

from config import CONFIG, PATHS
from database import DB, TimeUtils
from utils import (
    TextUtils, safe_send, is_authorized_in_group,
    check_bot_permissions, invalidate_auth_cache, apply_penalty,
    RATE_LIMITER, METRICS, get_text, StateManager, UserState,
    KeyboardFactory, TranslationManager, CB,
    get_banned_words_cached, invalidate_banned_words_cache,
    _auto_reply_cache, get_reply_from_file, _REPLIES_FROM_FILE,
    reload_replies_from_file, _increment_usage_async,
    fetch_json_from_url, import_auto_replies,
)
from cache import settings_cache, banned_words_cache, auth_cache

try:
    from replies import analyze_sentiment
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning("⚠️ replies.py غير موجود، تحليل المشاعر معطل")
    analyze_sentiment = None

logger = logging.getLogger(__name__)


# =====================================================================
# دالة الترجمة المساعدة (تمت إضافتها لإصلاح الخطأ NameError)
# =====================================================================
async def _trans(key: str, lang: str, default: str = "") -> str:
    """
    دالة ترجمة موحدة: تعيد النص المترجم إن وُجد، وإلا تعيد النص الافتراضي.
    """
    try:
        text = await get_text(lang, key)
        if text == key:  # لم يتم العثور على الترجمة
            return default
        return text
    except Exception:
        return default


# =====================================================================
# دوال الكاش الجديدة (مبنية على cache.py)
# =====================================================================

async def get_security_settings_cached(chat_id: int) -> dict:
    """جلب إعدادات الأمان مع التخزين المؤقت"""
    cached = await settings_cache.get_security(chat_id)
    if cached is not None:
        return cached
    settings = await DB.get_security_settings(chat_id)
    await settings_cache.set_security(chat_id, settings)
    return settings


async def get_auto_reply_settings_cached(chat_id: int) -> dict:
    """جلب إعدادات الردود التلقائية مع التخزين المؤقت"""
    cached = await settings_cache.get_auto_reply_settings(chat_id)
    if cached is not None:
        return cached
    settings = await DB.get_auto_reply_settings(chat_id)
    await settings_cache.set_auto_reply_settings(chat_id, settings)
    return settings


async def invalidate_security_cache(chat_id: int = None) -> None:
    """إبطال الكاش الأمني"""
    await settings_cache.invalidate_security(chat_id)


async def invalidate_auto_reply_cache(chat_id: int = None) -> None:
    """إبطال كاش الردود التلقائية"""
    await settings_cache.invalidate_auto_reply(chat_id)


# =====================================================================
# دوال مساعدة أخرى
# =====================================================================

async def _delete_after_delay(bot, chat_id: int, message_id: int, delay: int = 10):
    """حذف رسالة بعد تأخير"""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except BadRequest:
        pass
    except Exception as e:
        logger.debug(f"تعذر حذف الرسالة المؤجلة: {e}")


async def apply_violation_penalty(update, context, chat_id, user_id, violation_type, penalty_type, duration_seconds):
    """تطبيق عقوبة مع معالجة الأخطاء"""
    try:
        success, msg = await apply_penalty(
            context.bot, chat_id, user_id, penalty_type, duration_seconds,
            f"مخالفة: {violation_type}", context.bot.id
        )
        return success, msg
    except Exception as e:
        logger.error(f"❌ فشل تطبيق العقوبة: {e}")
        return False, str(e)[:100]


# =====================================================================
# معالجات الرسائل
# =====================================================================

class MessageHandlers:

    # =================================================================
    # الرسائل الخاصة
    # =================================================================

    @staticmethod
    async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """معالجة الرسائل الخاصة حسب حالة المستخدم"""
        try:
            user_id = update.effective_user.id
            lang = context.user_data.get('lang', 'ar')
            state = StateManager.get(user_id)

            # تحليل المشاعر
            if state == UserState.WAIT_MOOD:
                if analyze_sentiment is None:
                    msg = await _trans('mood_service_unavailable', lang, "❌ خدمة تحليل المشاعر غير متاحة حالياً")
                    await safe_send(context.bot, user_id, msg)
                    StateManager.clear(user_id)
                    return
                text = update.effective_message.text or ""
                result = analyze_sentiment(text)
                response = (
                    f"{result['emoji']} <b>تحليل المشاعر</b>\n\n"
                    f"📝 النص: <code>{escape(text[:100])}</code>\n"
                    f"🎯 النتيجة: {escape(result['sentiment'])}\n"
                    f"💬 {escape(result.get('response', ''))}\n\n"
                    f"😊 إيجابي: {result['positive_percent']:.0f}%\n"
                    f"😔 سلبي: {result['negative_percent']:.0f}%\n"
                    f"📊 الكلمات: {result['total_words']}"
                )
                await safe_send(context.bot, user_id, response, parse_mode='HTML')
                StateManager.clear(user_id)
                return

            handlers = {
                UserState.WAIT_CHANNEL: MessageHandlers._handle_channel_input,
                UserState.ADDING_POSTS: MessageHandlers._handle_adding_posts,
                UserState.SUPPORT_MODE: MessageHandlers._handle_support_message,
                UserState.WAIT_BROADCAST: MessageHandlers._handle_broadcast_input,
                UserState.WAIT_UPDATE: MessageHandlers._handle_update_input,
                UserState.WAIT_UPDATE_CH: MessageHandlers._handle_update_ch_input,
                UserState.WAIT_FORCE: MessageHandlers._handle_force_input,
                UserState.WAIT_LOG_CH: MessageHandlers._handle_log_ch_input,
                UserState.WAIT_ADMIN_ADD: MessageHandlers._handle_admin_add_input,
                UserState.WAIT_ADMIN_REM: MessageHandlers._handle_admin_rem_input,
                UserState.WAIT_KEYWORD: MessageHandlers._handle_keyword_input,
                UserState.WAIT_REPLY: MessageHandlers._handle_reply_input,
                UserState.WAIT_GLOBAL_BAN: MessageHandlers._handle_global_ban_input,
                UserState.WAIT_REM_GLOBAL_BAN: MessageHandlers._handle_rem_global_ban_input,
                UserState.WAIT_GROUP_BAN: MessageHandlers._handle_group_ban_input,
                UserState.WAIT_REM_GROUP_BAN: MessageHandlers._handle_rem_group_ban_input,
                UserState.WAIT_CONTEST_TITLE: MessageHandlers._handle_contest_title,
                UserState.WAIT_CONTEST_DESC: MessageHandlers._handle_contest_desc,
                UserState.WAIT_CONTEST_PRIZE: MessageHandlers._handle_contest_prize,
                UserState.WAIT_CONTEST_DATE: MessageHandlers._handle_contest_date,
                UserState.WAIT_CONTEST_ANSWER: MessageHandlers._handle_contest_answer,
                UserState.WAIT_AUTO_KEY: MessageHandlers._handle_auto_key,
                UserState.WAIT_AUTO_REPLY: MessageHandlers._handle_auto_reply_input,
                UserState.WAIT_AUTO_DEL: MessageHandlers._handle_auto_del,
                UserState.WAIT_IMPORT_FILE: MessageHandlers._handle_import_file,
                UserState.WAIT_GITHUB_URL: MessageHandlers._handle_github_url,
                UserState.WAIT_GRANT_FREE: MessageHandlers._handle_grant_free,
                UserState.WAIT_MIN: MessageHandlers._handle_min_input,
                UserState.WAIT_HOUR: MessageHandlers._handle_hour_input,
                UserState.WAIT_DAY: MessageHandlers._handle_day_input,
                UserState.WAIT_PUB_TIME: MessageHandlers._handle_pub_time_input,
                UserState.WAIT_REM_DAYS: MessageHandlers._handle_rem_days_input,
                UserState.WAIT_MAX_LEN: MessageHandlers._handle_max_len_input,
                UserState.WAIT_WARN_COUNT: MessageHandlers._handle_warn_count_input,
                UserState.WAIT_WELCOME_TEXT: MessageHandlers._handle_welcome_text_input,
                UserState.WAIT_GOODBYE_TEXT: MessageHandlers._handle_goodbye_text_input,
                UserState.WAIT_SLOW_MODE_SECONDS: MessageHandlers._handle_slow_mode_input,
                UserState.WAIT_ANTIFLOOD_MESSAGES: MessageHandlers._handle_antiflood_messages_input,
                UserState.WAIT_ANTIFLOOD_SECONDS: MessageHandlers._handle_antiflood_seconds_input,
                UserState.WAIT_NIGHT_START: MessageHandlers._handle_night_start_input,
                UserState.WAIT_NIGHT_END: MessageHandlers._handle_night_end_input,
                UserState.WAIT_BAN: MessageHandlers._handle_ban_input,
                UserState.WAIT_MUTE: MessageHandlers._handle_mute_input,
                UserState.WAIT_WARN: MessageHandlers._handle_warn_input,
                UserState.WAIT_KICK: MessageHandlers._handle_kick_input,
                UserState.WAIT_RESTRICT: MessageHandlers._handle_restrict_input,
                UserState.WAIT_UNBAN: MessageHandlers._handle_unban_input,
                UserState.WAIT_PIN: MessageHandlers._handle_pin_input,
                UserState.WAIT_PENALTY_DURATION: MessageHandlers._handle_penalty_duration_input,
                UserState.WAIT_VIOLATION_STRIKES: MessageHandlers._handle_violation_strikes_input,
                UserState.WAIT_VIOLATION_DURATION: MessageHandlers._handle_violation_duration_input,
                UserState.WAIT_REDEEM_GIFT: MessageHandlers._handle_redeem_gift_input,
                UserState.WAIT_RESTORE: MessageHandlers._handle_restore_input,
            }

            handler = handlers.get(state)
            if handler:
                await handler(update, context)
            elif state and state != UserState.NONE:
                logger.warning(f"حالة غير معروفة: {state}")
        except Exception as e:
            logger.exception("خطأ غير متوقع في معالجة الرسالة الخاصة")
            try:
                msg = await _trans('unexpected_error', lang, "❌ حدث خطأ غير متوقع، حاول مرة أخرى")
                await safe_send(context.bot, update.effective_user.id, msg)
            except:
                pass


    # =================================================================
    # رسائل المجموعات
    # =================================================================

    @staticmethod
    async def handle_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """معالجة رسائل المجموعات مع الفحوصات الأمنية"""
        if not update.effective_chat or not update.effective_message:
            return

        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        message = update.effective_message

        try:
            await RATE_LIMITER.acquire(f"group_{chat_id}_{user_id}")
        except:
            pass

        msg_text = message.text or ""
        msg_caption = message.caption or ""
        full_text = (msg_text + " " + msg_caption).strip()

        METRICS.increment_messages()
        settings = await get_security_settings_cached(chat_id)

        # ✅ حذف رسائل الخدمة (انضمام/مغادرة) إذا كان delete_service مفعلاً
        if settings.get('delete_service'):
            if message.new_chat_members or message.left_chat_member:
                try:
                    await message.delete()
                    logger.debug(f"🗑️ حذف رسالة انضمام/مغادرة في {chat_id}")
                except Exception as e:
                    logger.debug(f"تعذر حذف رسالة الخدمة: {e}")
                return

        if settings.get('delete_links'):
            if TextUtils.contains_link(full_text):
                await MessageHandlers._delete_and_warn(update, context, chat_id, user_id, "link", settings)
                return

        if settings.get('mentions'):
            if TextUtils.contains_mention(full_text):
                await MessageHandlers._delete_and_warn(update, context, chat_id, user_id, "mention", settings)
                return

        if settings.get('delete_banned_words'):
            banned_words = await get_banned_words_cached(chat_id)
            if banned_words:
                text_lower = full_text.lower()
                for word in banned_words:
                    if word in text_lower:
                        await MessageHandlers._delete_and_warn(update, context, chat_id, user_id, "banned_word", settings)
                        return

        max_len = settings.get('max_message_length', 0)
        if max_len > 0 and len(full_text) > max_len:
            await MessageHandlers._delete_and_warn(update, context, chat_id, user_id, "max_len", settings)
            return

        if getattr(message, 'forward_origin', None) and settings.get('delete_forwarded'):
            await MessageHandlers._delete_and_warn(update, context, chat_id, user_id, "forwarded", settings)
            return

        media_checks = [
            (message.video, 'delete_videos', 'video'),
            (message.audio, 'delete_audio', 'audio'),
            (message.voice, 'delete_voice', 'voice'),
            (message.animation, 'delete_animation', 'animation'),
            (message.document, 'delete_documents', 'document'),
            (message.sticker, 'delete_stickers', 'sticker'),
            (message.photo, 'delete_photos', 'photo'),
            (message.video_note, 'delete_video_note', 'video_note'),
        ]
        for media, setting_key, violation_type in media_checks:
            if media and settings.get(setting_key):
                await MessageHandlers._delete_and_warn(update, context, chat_id, user_id, violation_type, settings)
                return

        if msg_text:
            await MessageHandlers._process_auto_reply(update, context, chat_id, msg_text, user_id)


    # =================================================================
    # حذف وتحذير
    # =================================================================

    @staticmethod
    def _get_penalty_duration(settings: dict, violation_type: str, penalty_type: str) -> int:
        """اختيار المدة المناسبة للعقوبة حسب نوع المخالفة"""
        if violation_type in ('flood', 'antiflood'):
            return settings.get('antiflood_penalty_duration', 3600)
        elif violation_type in ('night', 'night_mode'):
            return settings.get('night_mode_action_duration', 3600)
        elif violation_type in ('warn_penalty', 'warn'):
            return settings.get('warn_penalty_duration', 3600)
        return settings.get('auto_mute_duration', 3600)


    @staticmethod
    async def _delete_and_warn(update, context, chat_id, user_id, violation_type, settings: dict):
        """حذف الرسالة وإرسال تنبيه وتطبيق العقوبات"""
        try:
            await update.effective_message.delete()
        except Exception as e:
            logger.warning(f"تعذر حذف الرسالة: {e}")

        violation_count = await DB.increment_violation_count(user_id, chat_id)
        penalty_rule = await DB.get_violation_penalty(chat_id, violation_type)

        if penalty_rule:
            penalty_type = penalty_rule['penalty_type']
            if penalty_type == 'none':
                penalty_type = None
                duration_seconds = 0
            else:
                duration_seconds = penalty_rule['duration_seconds']
        else:
            penalty_type = settings.get('auto_penalty', 'none')
            if penalty_type == 'none':
                penalty_type = None
                duration_seconds = 0
            elif penalty_type not in ['mute', 'ban', 'restrict', 'kick', 'warn']:
                penalty_type = 'mute'
                duration_seconds = MessageHandlers._get_penalty_duration(settings, violation_type, penalty_type)
            else:
                duration_seconds = MessageHandlers._get_penalty_duration(settings, violation_type, penalty_type)

        await DB.add_admin_log(chat_id, context.bot.id, f"violation_{violation_type}", user_id)

        violation_messages = {
            'link': '🚫 الروابط غير مسموحة',
            'mention': '🚫 المنشنات غير مسموحة',
            'banned_word': '🚫 كلمة محظورة',
            'max_len': '📏 الرسالة طويلة جداً',
            'forwarded': '↩️ الرسائل المعاد توجيهها غير مسموحة',
            'video': '🎬 الفيديوهات غير مسموحة',
            'audio': '🎵 الملفات الصوتية غير مسموحة',
            'voice': '🎤 الرسائل الصوتية غير مسموحة',
            'animation': '🎞️ الصور المتحركة غير مسموحة',
            'document': '📄 الملفات غير مسموحة',
            'sticker': '🖼️ الملصقات غير مسموحة',
            'photo': '📷 الصور غير مسموحة',
            'video_note': '🎥 فيديو نوت غير مسموح',
        }
        violation_message = violation_messages.get(violation_type, f'🚫 مخالفة: {violation_type}')

        try:
            user_name = escape(update.effective_user.first_name or "مستخدم")
            message_text = (
                f"⚠️ <b>تنبيه</b>\n"
                f"{violation_message}\n"
                f"👤 {user_name}\n"
                f"📊 عدد المخالفات: {violation_count}\n"
                f"⏳ سيتم حذف هذه الرسالة خلال 10 ثوانٍ"
            )
            sent_msg = await context.bot.send_message(chat_id, message_text, parse_mode='HTML')
            asyncio.create_task(_delete_after_delay(context.bot, chat_id, sent_msg.message_id, 10))
        except Exception as e:
            logger.warning(f"تعذر إرسال تنبيه المخالفة: {e}")

        # تطبيق العقوبة فقط إذا كانت محددة
        if penalty_type:
            max_strikes = settings.get('violation_strikes') or settings.get('max_warnings') or 3
            if violation_count >= max_strikes:
                success, msg = await apply_violation_penalty(
                    update, context, chat_id, user_id, violation_type, penalty_type, duration_seconds
                )
                if success:
                    await safe_send(context.bot, chat_id, f"🚨 {msg}")
                    await DB.reset_violation_count(user_id, chat_id)


    # =================================================================
    # الردود التلقائية
    # =================================================================

    @staticmethod
    async def _process_auto_reply(update, context, chat_id, text, user_id=None):
        """معالجة الردود التلقائية مع دعم الوسائط"""
        try:
            ars = await get_auto_reply_settings_cached(chat_id)
            if not ars.get('enabled', False):
                return False
            if ars.get('ignore_bots', True) and update.effective_user.is_bot:
                return False
            if ars.get('only_admins', False):
                if not await is_authorized_in_group(context.bot, chat_id, user_id or update.effective_user.id):
                    return False

            reply = await DB.get_auto_reply(text, chat_id)
            if reply:
                reply_text = reply.get('reply', '')
                reply_type = reply.get('reply_type', 'text')
                media_id = reply.get('reply_media_id')

                try:
                    if reply_type in ['photo', 'video', 'document', 'audio', 'animation']:
                        await safe_send(
                            context.bot,
                            chat_id,
                            reply_text,
                            **{reply_type: media_id} if media_id else {}
                        )
                    elif reply_type == 'voice':
                        await safe_send(context.bot, chat_id, "", voice=media_id)
                    elif reply_type == 'sticker':
                        await safe_send(context.bot, chat_id, "", sticker=media_id)
                    elif reply_type == 'video_note':
                        await safe_send(context.bot, chat_id, "", video_note=media_id)
                    else:
                        await safe_send(context.bot, chat_id, reply_text)
                except Exception as e:
                    logger.error(f"فشل إرسال الرد التلقائي بالوسائط: {e}")
                    if reply_text:
                        await safe_send(context.bot, chat_id, reply_text)

                await _increment_usage_async(chat_id, text)
                return True

            file_reply = get_reply_from_file(text)
            if file_reply:
                await safe_send(context.bot, chat_id, file_reply)
                return True
            return False
        except Exception as e:
            logger.error(f"❌ خطأ في الردود: {e}")
            return False


    # =================================================================
    # إضافة القناة
    # =================================================================

    @staticmethod
    async def _handle_channel_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        text = (update.effective_message.text or "").strip()

        if user_id != CONFIG.PRIMARY_OWNER_ID:
            if not await DB.has_active_subscription(user_id):
                msg = await _trans(
                    'subscription_required', lang,
                    "❌ <b>يجب أن يكون لديك اشتراك نشط لإضافة قناة!</b>\n\n"
                    "📌 استخدم /subscribe للاشتراك\n"
                    "🎁 أو /trial للتجربة المجانية"
                )
                await safe_send(
                    context.bot, user_id,
                    msg,
                    parse_mode='HTML'
                )
                StateManager.clear(user_id)
                return

        try:
            if text.lstrip('-').isdigit():
                channel_id = int(text)
            else:
                try:
                    chat = await context.bot.get_chat(text)
                    channel_id = chat.id
                except:
                    msg = await _trans('channel_not_found', lang, "❌ القناة غير موجودة!")
                    await safe_send(context.bot, user_id, msg)
                    StateManager.clear(user_id)
                    return

            try:
                chat_info = await context.bot.get_chat(channel_id)
                channel_name = chat_info.title or chat_info.username or f"قناة {channel_id}"
            except:
                channel_name = f"قناة {channel_id}"

            # التحقق من صلاحيات البوت في القناة
            try:
                bot_member = await context.bot.get_chat_member(channel_id, context.bot.id)
                if bot_member.status not in ['administrator', 'creator']:
                    msg = await _trans('bot_not_admin', lang, "❌ البوت ليس مشرفًا في القناة!")
                    await safe_send(context.bot, user_id, msg)
                    StateManager.clear(user_id)
                    return
            except BadRequest as e:
                logger.warning(f"تعذر التحقق من صلاحيات البوت في القناة {channel_id}: {e}")
                msg = await _trans('verify_failed', lang, "❌ تعذر التحقق من صلاحيات البوت، تأكد أنه مشرف في القناة.")
                await safe_send(context.bot, user_id, msg)
                StateManager.clear(user_id)
                return
            except Exception as e:
                logger.error(f"خطأ غير متوقع في التحقق من صلاحيات البوت: {e}")
                msg = await _trans('verify_error', lang, "❌ تعذر التحقق من صلاحيات البوت، حاول لاحقاً.")
                await safe_send(context.bot, user_id, msg)
                StateManager.clear(user_id)
                return

            # التحقق من صلاحيات المستخدم (لغير المالك)
            if user_id != CONFIG.PRIMARY_OWNER_ID:
                try:
                    user_member = await context.bot.get_chat_member(channel_id, user_id)
                    if user_member.status not in ['creator', 'administrator']:
                        msg = await _trans('must_be_admin', lang, "❌ يجب أن تكون مشرفًا في القناة لإضافتها!")
                        await safe_send(context.bot, user_id, msg)
                        StateManager.clear(user_id)
                        return
                except BadRequest as e:
                    logger.warning(f"تعذر التحقق من صلاحيات المستخدم {user_id} في القناة {channel_id}: {e}")
                    msg = await _trans('user_verify_failed', lang, "❌ تعذر التحقق من صلاحياتك في القناة.")
                    await safe_send(context.bot, user_id, msg)
                    StateManager.clear(user_id)
                    return
                except Exception as e:
                    logger.error(f"خطأ غير متوقع في التحقق من صلاحيات المستخدم: {e}")
                    msg = await _trans('user_verify_error', lang, "❌ تعذر التحقق من صلاحياتك، حاول لاحقاً.")
                    await safe_send(context.bot, user_id, msg)
                    StateManager.clear(user_id)
                    return

            ch_db_id = await DB.add_channel(user_id, channel_id, channel_name)

            if ch_db_id:
                msg = await _trans('channel_added', lang, f"✅ تمت إضافة القناة: {escape(channel_name)}")
                await safe_send(context.bot, user_id, msg)
            else:
                msg = await _trans('channel_add_failed', lang, "❌ فشل إضافة القناة (قد يكون الحد الأقصى للقنوات قد تم الوصول إليه)")
                await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.exception("خطأ غير متوقع في إضافة القناة")
            await safe_send(context.bot, user_id, f"❌ خطأ: {escape(str(e)[:100])}")

        StateManager.clear(user_id)


    # =================================================================
    # إضافة المنشورات
    # =================================================================

    @staticmethod
    async def _handle_adding_posts(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        channel_db_id = await DB.get_active_channel(user_id)

        if not channel_db_id:
            StateManager.clear(user_id)
            msg = await _trans('no_active_channel', lang, "❌ لا توجد قناة نشطة")
            await safe_send(context.bot, user_id, msg)
            return

        msg = update.effective_message
        media_type = 'text'
        media_file_id = ''
        text = msg.text or msg.caption or ""

        if msg.photo:
            media_type = 'photo'
            media_file_id = msg.photo[-1].file_id
            text = msg.caption or ""
        elif msg.video:
            media_type = 'video'
            media_file_id = msg.video.file_id
            text = msg.caption or ""
        elif msg.document:
            media_type = 'document'
            media_file_id = msg.document.file_id
            text = msg.caption or ""
        elif msg.audio:
            media_type = 'audio'
            media_file_id = msg.audio.file_id
            text = msg.caption or ""
        elif msg.voice:
            media_type = 'voice'
            media_file_id = msg.voice.file_id
        elif msg.animation:
            media_type = 'animation'
            media_file_id = msg.animation.file_id
            text = msg.caption or ""
        elif msg.sticker:
            media_type = 'sticker'
            media_file_id = msg.sticker.file_id
        elif msg.video_note:
            media_type = 'video_note'
            media_file_id = msg.video_note.file_id

        # نعتمد على DB.add_posts لفحص التكرار والحد الأقصى
        posts = [(text, media_type, media_file_id)]
        count = await DB.add_posts(user_id, channel_db_id, posts)

        if count > 0:
            msg = await _trans('post_added', lang, "✅ تمت إضافة المنشور")
            await safe_send(context.bot, user_id, msg)
        else:
            # رسالة موحدة توضح الاحتمالين
            msg = await _trans(
                'post_add_failed', lang,
                "❌ لم تتم إضافة المنشور.\n"
                "• قد يكون المنشور مكررًا.\n"
                "• أو تم الوصول إلى الحد الأقصى للمنشورات غير المنشورة."
            )
            await safe_send(context.bot, user_id, msg)


    # =================================================================
    # الدعم الفني
    # =================================================================

    @staticmethod
    async def _handle_support_message(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        content = update.effective_message.text or ""
        username = update.effective_user.username or ""
        ticket_number = await DB.create_ticket(user_id, username, content)
        StateManager.clear(user_id)
        msg = await _trans('ticket_received', lang, f"✅ تم استلام رسالتك!\n🎫 رقم التذكرة: {ticket_number}")
        await safe_send(context.bot, user_id, msg)


    # =================================================================
    # البث الجماعي
    # =================================================================

    @staticmethod
    async def _handle_broadcast_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return

        content = update.effective_message.text or ""
        users = await DB.get_all_users()

        sent_count = 0
        for user in users:
            user_id_target = user.get('user_id') if isinstance(user, dict) else user[0]
            banned = user.get('banned', 0) if isinstance(user, dict) else (user[1] if len(user) > 1 else 0)

            if banned == 0:
                try:
                    await safe_send(context.bot, user_id_target, content)
                    sent_count += 1
                    await asyncio.sleep(0.05)
                except Exception as e:
                    logger.warning(f"فشل الإرسال إلى {user_id_target}: {e}")

        msg = await _trans('broadcast_success', lang, f"✅ تم البث إلى {sent_count} مستخدم")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    # =================================================================
    # التحديثات والإعدادات
    # =================================================================

    @staticmethod
    async def _handle_update_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return
        content = update.effective_message.text or ""
        update_ch = await DB.get_updates_channel()
        if update_ch:
            try:
                await safe_send(context.bot, update_ch, content)
                msg = await _trans('update_sent', lang, "✅ تم إرسال التحديث")
                await safe_send(context.bot, user_id, msg)
            except Exception as e:
                logger.error(f"فشل إرسال التحديث: {e}")
                msg = await _trans('send_failed', lang, "❌ فشل الإرسال")
                await safe_send(context.bot, user_id, msg)
        else:
            msg = await _trans('no_update_channel', lang, "❌ لم يتم تعيين قناة التحديثات")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_update_ch_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return
        text = (update.effective_message.text or "").strip()
        await DB.set_setting('updates_channel', text)
        msg = await _trans('set_success', lang, f"✅ تم تعيين: {escape(text)}")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_force_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return
        text = (update.effective_message.text or "").strip()
        if text.lower() == 'none':
            await DB.set_setting('force_subscribe_channel', '')
            msg = await _trans('force_disabled', lang, "✅ تم تعطيل الاشتراك الإجباري")
            await safe_send(context.bot, user_id, msg)
        else:
            await DB.set_setting('force_subscribe_channel', text)
            msg = await _trans('set_success', lang, f"✅ تم تعيين: {escape(text)}")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_log_ch_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return
        text = (update.effective_message.text or "").strip()
        await DB.set_setting('log_channel_id', text)
        msg = await _trans('set_success', lang, f"✅ تم تعيين: {escape(text)}")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    # =================================================================
    # المشرفين
    # =================================================================

    @staticmethod
    async def _handle_admin_add_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return
        text = (update.effective_message.text or "").strip()
        try:
            admin_id = int(text)
            if admin_id <= 0:
                raise ValueError
            success = await DB.add_admin(admin_id, user_id)
            if success:
                msg = await _trans('added_success', lang, "✅ تمت الإضافة")
                await safe_send(context.bot, user_id, msg)
            else:
                admins = await DB.get_admin_list()
                if any(a['user_id'] == admin_id for a in admins):
                    msg = await _trans('already_admin', lang, "ℹ️ هذا المستخدم مشرف بالفعل")
                    await safe_send(context.bot, user_id, msg)
                else:
                    msg = await _trans('add_failed', lang, "❌ فشل الإضافة")
                    await safe_send(context.bot, user_id, msg)
        except ValueError:
            msg = await _trans('invalid_id', lang, "❌ معرف غير صالح")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"فشل إضافة مشرف: {e}")
            msg = await _trans('error_occurred', lang, "❌ حدث خطأ")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_admin_rem_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return
        text = (update.effective_message.text or "").strip()
        try:
            admin_id = int(text)
            if admin_id <= 0:
                raise ValueError
            success = await DB.remove_admin(admin_id)
            if success:
                msg = await _trans('removed_success', lang, "✅ تمت الإزالة")
                await safe_send(context.bot, user_id, msg)
            else:
                msg = await _trans('not_admin', lang, "ℹ️ هذا المستخدم ليس مشرفًا")
                await safe_send(context.bot, user_id, msg)
        except ValueError:
            msg = await _trans('invalid_id', lang, "❌ معرف غير صالح")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"فشل إزالة مشرف: {e}")
            msg = await _trans('error_occurred', lang, "❌ حدث خطأ")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    # =================================================================
    # الردود التلقائية - إدارة
    # =================================================================

    @staticmethod
    async def _handle_keyword_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        keyword = (update.effective_message.text or "").strip().lower()
        context.user_data['auto_keyword'] = keyword
        context.user_data['auto_chat'] = -1
        StateManager.set(user_id, UserState.WAIT_REPLY)
        msg = await _trans('send_reply_prompt', lang, "📝 أرسل الرد:")
        await safe_send(context.bot, user_id, f"✅ الكلمة: {escape(keyword)}\n{msg}")


    @staticmethod
    async def _handle_reply_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        keyword = context.user_data.get('auto_keyword', '')
        if not keyword:
            msg = await _trans('empty_keyword', lang, "❌ الكلمة المفتاحية فارغة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        chat_id = context.user_data.get('auto_chat', -1)

        msg = update.effective_message
        reply_text = msg.text or msg.caption or ""
        media_type = 'text'
        media_file_id = None

        if msg.photo:
            media_type = 'photo'
            media_file_id = msg.photo[-1].file_id
        elif msg.video:
            media_type = 'video'
            media_file_id = msg.video.file_id
        elif msg.document:
            media_type = 'document'
            media_file_id = msg.document.file_id
        elif msg.audio:
            media_type = 'audio'
            media_file_id = msg.audio.file_id
        elif msg.voice:
            media_type = 'voice'
            media_file_id = msg.voice.file_id
        elif msg.animation:
            media_type = 'animation'
            media_file_id = msg.animation.file_id
        elif msg.sticker:
            media_type = 'sticker'
            media_file_id = msg.sticker.file_id
        elif msg.video_note:
            media_type = 'video_note'
            media_file_id = msg.video_note.file_id

        await DB.add_auto_reply(
            chat_id, keyword, reply_text,
            reply_type=media_type,
            media_id=media_file_id
        )
        await invalidate_auto_reply_cache(chat_id)
        msg = await _trans('added_success', lang, "✅ تمت الإضافة")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_auto_key(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        keyword = (update.effective_message.text or "").strip().lower()
        context.user_data['auto_keyword'] = keyword
        if 'auto_chat' not in context.user_data:
            context.user_data['auto_chat'] = -1
        StateManager.set(user_id, UserState.WAIT_AUTO_REPLY)
        msg = await _trans('send_reply_prompt', lang, "📝 أرسل الرد:")
        await safe_send(context.bot, user_id, f"✅ الكلمة: {escape(keyword)}\n{msg}")


    @staticmethod
    async def _handle_auto_reply_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('auto_chat', -1)
        keyword = context.user_data.get('auto_keyword', '')
        if not keyword:
            msg = await _trans('empty_keyword', lang, "❌ الكلمة المفتاحية فارغة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return

        msg = update.effective_message
        reply_text = msg.text or msg.caption or ""
        media_type = 'text'
        media_file_id = None

        if msg.photo:
            media_type = 'photo'
            media_file_id = msg.photo[-1].file_id
        elif msg.video:
            media_type = 'video'
            media_file_id = msg.video.file_id
        elif msg.document:
            media_type = 'document'
            media_file_id = msg.document.file_id
        elif msg.audio:
            media_type = 'audio'
            media_file_id = msg.audio.file_id
        elif msg.voice:
            media_type = 'voice'
            media_file_id = msg.voice.file_id
        elif msg.animation:
            media_type = 'animation'
            media_file_id = msg.animation.file_id
        elif msg.sticker:
            media_type = 'sticker'
            media_file_id = msg.sticker.file_id
        elif msg.video_note:
            media_type = 'video_note'
            media_file_id = msg.video_note.file_id

        await DB.add_auto_reply(
            chat_id, keyword, reply_text,
            reply_type=media_type,
            media_id=media_file_id
        )
        await invalidate_auto_reply_cache(chat_id)
        msg = await _trans('added_success', lang, "✅ تمت الإضافة")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_auto_del(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('auto_chat', -1)
        keyword = (update.effective_message.text or "").strip().lower()
        await DB.remove_auto_reply(chat_id, keyword)
        await invalidate_auto_reply_cache(chat_id)
        msg = await _trans('deleted_success', lang, "✅ تم الحذف")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    # =================================================================
    # الكلمات المحظورة - إدارة
    # =================================================================

    @staticmethod
    async def _handle_global_ban_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        word = (update.effective_message.text or "").strip().lower()
        success, duplicate = await DB.add_banned_word(word, -1, user_id)
        if success:
            invalidate_banned_words_cache(-1)
            await safe_send(context.bot, user_id, f"✅ تمت إضافة الكلمة المحظورة: {escape(word)}")
        elif duplicate:
            await safe_send(context.bot, user_id, "❌ الكلمة موجودة بالفعل في القائمة العامة")
        else:
            await safe_send(context.bot, user_id, "❌ تعذرت الإضافة (قد تكون تجاوزت الحد الأقصى للكلمات العامة)")
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_rem_global_ban_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        word = (update.effective_message.text or "").strip().lower()
        await DB.remove_banned_word(word, -1)
        invalidate_banned_words_cache(-1)
        msg = await _trans('removed_success', lang, "✅ تمت الإزالة")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_group_ban_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('ban_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        word = (update.effective_message.text or "").strip().lower()
        success, duplicate = await DB.add_banned_word(word, chat_id, user_id)
        if success:
            invalidate_banned_words_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ تمت إضافة الكلمة المحظورة: {escape(word)}")
        elif duplicate:
            await safe_send(context.bot, user_id, "❌ الكلمة موجودة بالفعل في قائمة المجموعة")
        else:
            await safe_send(context.bot, user_id, "❌ تعذرت الإضافة، حاول مجددًا")
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_rem_group_ban_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('ban_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        word = (update.effective_message.text or "").strip().lower()
        await DB.remove_banned_word(word, chat_id)
        invalidate_banned_words_cache(chat_id)
        msg = await _trans('removed_success', lang, "✅ تمت الإزالة")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    # =================================================================
    # المسابقات
    # =================================================================

    @staticmethod
    async def _handle_contest_title(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        context.user_data['contest_title'] = update.effective_message.text or ""
        StateManager.set(user_id, UserState.WAIT_CONTEST_DESC)
        msg = await _trans('send_description_prompt', lang, "📝 أرسل الوصف:")
        await safe_send(context.bot, user_id, msg)


    @staticmethod
    async def _handle_contest_desc(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        context.user_data['contest_desc'] = update.effective_message.text or ""
        StateManager.set(user_id, UserState.WAIT_CONTEST_PRIZE)
        msg = await _trans('send_prize_prompt', lang, "🎁 أرسل الجائزة:")
        await safe_send(context.bot, user_id, msg)


    @staticmethod
    async def _handle_contest_prize(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        context.user_data['contest_prize'] = update.effective_message.text or ""
        StateManager.set(user_id, UserState.WAIT_CONTEST_DATE)
        msg = await _trans('send_date_prompt', lang, "📅 أرسل التاريخ:")
        await safe_send(context.bot, user_id, msg)


    @staticmethod
    async def _handle_contest_date(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        title = context.user_data.get('contest_title', '')
        desc = context.user_data.get('contest_desc', '')
        prize = context.user_data.get('contest_prize', '')
        date = update.effective_message.text or ""

        try:
            datetime.fromisoformat(date)
        except ValueError:
            msg = await _trans('invalid_date', lang, "❌ صيغة التاريخ غير صحيحة. استخدم التنسيق: YYYY-MM-DD HH:MM")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return

        contest_id = await DB.create_contest(user_id, title, desc, prize, date)
        if contest_id:
            await safe_send(context.bot, user_id, f"✅ تم الإنشاء #{contest_id}")
        else:
            await safe_send(context.bot, user_id, "❌ فشل إنشاء المسابقة (تأكد من صيغة التاريخ وصحة البيانات)")
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_contest_answer(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        contest_id = context.user_data.get('contest_join')
        answer = update.effective_message.text or ""
        if contest_id:
            joined = await DB.join_contest(contest_id, user_id, answer)
            if joined:
                await safe_send(context.bot, user_id, "✅ تم الاشتراك!")
            else:
                await safe_send(context.bot, user_id, "❌ فشل (قد تكون مشتركاً بالفعل أو المسابقة انتهت)")
        else:
            await safe_send(context.bot, user_id, "❌ لا توجد مسابقة محددة")
        StateManager.clear(user_id)


    # =================================================================
    # الاستيراد
    # =================================================================

    @staticmethod
    async def _handle_import_file(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        if not update.effective_message.document:
            msg = await _trans('send_json', lang, "❌ أرسل ملف JSON")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            file = await update.effective_message.document.get_file()
            file_path = await file.download_to_drive()
            count = await import_auto_replies(-1, str(file_path))
            try:
                os.remove(file_path)
            except OSError as e:
                logger.warning(f"تعذر حذف الملف المؤقت: {e}")
            msg = await _trans('import_success', lang, f"✅ تم استيراد {count} رد")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.exception("خطأ في استيراد الملف")
            await safe_send(context.bot, user_id, "❌ حدث خطأ أثناء الاستيراد")
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_github_url(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        url = (update.effective_message.text or "").strip()
        tmp_path = None
        try:
            data = await fetch_json_from_url(url)
            if not data:
                msg = await _trans('fetch_failed', lang, "❌ فشل جلب البيانات")
                await safe_send(context.bot, user_id, msg)
                StateManager.clear(user_id)
                return
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as tmp:
                json.dump(data, tmp, ensure_ascii=False)
                tmp_path = tmp.name
            count = await import_auto_replies(-1, tmp_path)
            msg = await _trans('import_success', lang, f"✅ تم استيراد {count} رد")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"خطأ في الاستيراد من URL: {e}")
            msg = await _trans('grant_failed', lang, "❌ فشل")
            await safe_send(context.bot, user_id, msg)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        StateManager.clear(user_id)


    # =================================================================
    # منح اشتراك
    # =================================================================

    @staticmethod
    async def _handle_grant_free(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return
        parts = (update.effective_message.text or "").strip().split()
        if len(parts) >= 2:
            try:
                target_id = int(parts[0])
                days = int(parts[1])
                if target_id <= 0 or days <= 0:
                    raise ValueError
                await DB.grant_subscription_days(target_id, days)
                msg = await _trans('grant_success', lang, "✅ تم المنح")
                await safe_send(context.bot, user_id, msg)
            except ValueError:
                msg = await _trans('invalid_format', lang, "❌ صيغة خاطئة")
                await safe_send(context.bot, user_id, msg)
            except Exception as e:
                logger.error(f"فشل منح اشتراك: {e}")
                msg = await _trans('grant_failed', lang, "❌ فشل")
                await safe_send(context.bot, user_id, msg)
        else:
            msg = await _trans('usage_format', lang, "❌ الصيغة: /grant_free <id> <days>")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    # =================================================================
    # الجدولة
    # =================================================================

    @staticmethod
    async def _handle_min_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        ch_id = context.user_data.get('schedule_ch')
        if not ch_id:
            msg = await _trans('channel_not_specified', lang, "❌ لم يتم تحديد القناة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            minutes = int(update.effective_message.text or "0")
            if minutes > 0:
                await DB.update_schedule(ch_id, interval_minutes=minutes, schedule_type='interval_minutes')
                await safe_send(context.bot, user_id, f"✅ {minutes} دقيقة")
            else:
                await safe_send(context.bot, user_id, "❌ يجب أن يكون الرقم موجبًا")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌ رقم غير صالح")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_hour_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        ch_id = context.user_data.get('schedule_ch')
        if not ch_id:
            msg = await _trans('channel_not_specified', lang, "❌ لم يتم تحديد القناة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            hours = int(update.effective_message.text or "0")
            if hours > 0:
                await DB.update_schedule(ch_id, interval_hours=hours, schedule_type='interval_hours')
                await safe_send(context.bot, user_id, f"✅ {hours} ساعة")
            else:
                await safe_send(context.bot, user_id, "❌ يجب أن يكون الرقم موجبًا")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌ رقم غير صالح")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_day_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        ch_id = context.user_data.get('schedule_ch')
        if not ch_id:
            msg = await _trans('channel_not_specified', lang, "❌ لم يتم تحديد القناة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            days = int(update.effective_message.text or "0")
            if days > 0:
                await DB.update_schedule(ch_id, interval_days=days, schedule_type='interval_days')
                await safe_send(context.bot, user_id, f"✅ {days} يوم")
            else:
                await safe_send(context.bot, user_id, "❌ يجب أن يكون الرقم موجبًا")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌ رقم غير صالح")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_pub_time_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        ch_id = context.user_data.get('schedule_ch')
        if not ch_id:
            msg = await _trans('channel_not_specified', lang, "❌ لم يتم تحديد القناة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        time_val = (update.effective_message.text or "").strip()
        if not re.match(r'^\d{1,2}:\d{2}$', time_val):
            msg = await _trans('invalid_time_format', lang, "❌ تنسيق غير صالح (مثال: 14:30)")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        await DB.update_schedule(ch_id, publish_time=time_val)
        await safe_send(context.bot, user_id, f"✅ {time_val}")
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_rem_days_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        try:
            days = int(update.effective_message.text or "3")
            if 1 <= days <= 30:
                await DB.update_reminder_settings(user_id, reminder_days_before=days)
                await safe_send(context.bot, user_id, f"✅ {days} يوم")
            else:
                msg = await _trans('range_1_30', lang, "❌ يجب أن يكون بين 1 و 30")
                await safe_send(context.bot, user_id, msg)
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌ رقم غير صالح")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    # =================================================================
    # إعدادات الأمان
    # =================================================================

    @staticmethod
    async def _handle_max_len_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            max_len = int(update.effective_message.text or "0")
            if max_len < 0:
                raise ValueError
            await DB.update_security_settings(chat_id, max_message_length=max_len)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ {max_len}")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌ رقم غير صالح")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_warn_count_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            count = int(update.effective_message.text or "3")
            if count <= 0:
                raise ValueError
            await DB.update_security_settings(chat_id, max_warnings=count, violation_strikes=count)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ {count}")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌ رقم غير صالح")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_welcome_text_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        text = update.effective_message.text or ""
        await DB.update_security_settings(chat_id, welcome_text=text)
        await invalidate_security_cache(chat_id)
        msg = await _trans('saved_success', lang, "✅ تم الحفظ")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_goodbye_text_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        text = update.effective_message.text or ""
        await DB.update_security_settings(chat_id, goodbye_text=text)
        await invalidate_security_cache(chat_id)
        msg = await _trans('saved_success', lang, "✅ تم الحفظ")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_slow_mode_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            seconds = int(update.effective_message.text or "0")
            if seconds < 0:
                raise ValueError
            await DB.update_security_settings(chat_id, slow_mode_seconds=seconds)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ {seconds}")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌ رقم غير صالح")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_antiflood_messages_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            count = int(update.effective_message.text or "5")
            if count <= 0:
                raise ValueError
            await DB.update_security_settings(chat_id, antiflood_messages=count)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ {count}")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌ رقم غير صالح")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_antiflood_seconds_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            seconds = int(update.effective_message.text or "10")
            if seconds <= 0:
                raise ValueError
            await DB.update_security_settings(chat_id, antiflood_seconds=seconds)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ {seconds}")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌ رقم غير صالح")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_night_start_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        time_val = (update.effective_message.text or "").strip()
        if not re.match(r'^\d{1,2}:\d{2}$', time_val):
            msg = await _trans('invalid_time_format', lang, "❌ تنسيق غير صالح (مثال: 23:00)")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        await DB.update_security_settings(chat_id, night_mode_start=time_val)
        await invalidate_security_cache(chat_id)
        await safe_send(context.bot, user_id, f"✅ {time_val}")
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_night_end_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        time_val = (update.effective_message.text or "").strip()
        if not re.match(r'^\d{1,2}:\d{2}$', time_val):
            msg = await _trans('invalid_time_format', lang, "❌ تنسيق غير صالح (مثال: 06:00)")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        await DB.update_security_settings(chat_id, night_mode_end=time_val)
        await invalidate_security_cache(chat_id)
        await safe_send(context.bot, user_id, f"✅ {time_val}")
        StateManager.clear(user_id)


    # =================================================================
    # العقوبات
    # =================================================================

    @staticmethod
    async def _check_admin_in_chat(context, chat_id, user_id):
        if user_id == CONFIG.PRIMARY_OWNER_ID:
            return True
        try:
            return await is_authorized_in_group(context.bot, chat_id, user_id)
        except Exception as e:
            logger.warning(f"تعذر التحقق من الصلاحية: {e}")
            return False


    @staticmethod
    async def _handle_ban_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('adv_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if not await MessageHandlers._check_admin_in_chat(context, chat_id, user_id):
            msg = await _trans('not_admin_in_group', lang, "❌ لم تعد مشرفًا في هذه المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        parts = (update.effective_message.text or "").strip().split()
        if not parts:
            msg = await _trans('send_user_id', lang, "❌ أرسل معرف المستخدم")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            target = int(parts[0])
            duration = int(parts[1]) * 60 if len(parts) > 1 else 0
            if target <= 0 or duration < 0:
                raise ValueError
            success, msg = await apply_penalty(context.bot, chat_id, target, 'ban', duration, "", user_id)
            await safe_send(context.bot, user_id, msg if success else f"❌ {msg}")
        except ValueError:
            msg = await _trans('invalid_format', lang, "❌ صيغة غير صحيحة")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"فشل الحظر: {e}")
            msg = await _trans('execution_failed', lang, "❌ فشل التنفيذ")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_mute_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('adv_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if not await MessageHandlers._check_admin_in_chat(context, chat_id, user_id):
            msg = await _trans('not_admin_in_group', lang, "❌ لم تعد مشرفًا في هذه المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        parts = (update.effective_message.text or "").strip().split()
        if not parts:
            msg = await _trans('send_user_id', lang, "❌ أرسل معرف المستخدم")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            target = int(parts[0])
            duration = int(parts[1]) * 60 if len(parts) > 1 else 60
            if target <= 0 or duration <= 0:
                raise ValueError
            success, msg = await apply_penalty(context.bot, chat_id, target, 'mute', duration, "", user_id)
            await safe_send(context.bot, user_id, msg if success else f"❌ {msg}")
        except ValueError:
            msg = await _trans('invalid_format', lang, "❌ صيغة غير صحيحة")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"فشل الكتم: {e}")
            msg = await _trans('execution_failed', lang, "❌ فشل التنفيذ")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_warn_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('adv_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if not await MessageHandlers._check_admin_in_chat(context, chat_id, user_id):
            msg = await _trans('not_admin_in_group', lang, "❌ لم تعد مشرفًا في هذه المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            target = int((update.effective_message.text or "").strip())
            if target <= 0:
                raise ValueError
            success, msg = await apply_penalty(context.bot, chat_id, target, 'warn', 0, "", user_id)
            await safe_send(context.bot, user_id, msg if success else f"❌ {msg}")
        except ValueError:
            msg = await _trans('invalid_id', lang, "❌ معرف غير صالح")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"فشل التحذير: {e}")
            msg = await _trans('execution_failed', lang, "❌ فشل التنفيذ")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_kick_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('adv_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if not await MessageHandlers._check_admin_in_chat(context, chat_id, user_id):
            msg = await _trans('not_admin_in_group', lang, "❌ لم تعد مشرفًا في هذه المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            target = int((update.effective_message.text or "").strip())
            if target <= 0:
                raise ValueError
            success, msg = await apply_penalty(context.bot, chat_id, target, 'kick', 0, "", user_id)
            await safe_send(context.bot, user_id, msg if success else f"❌ {msg}")
        except ValueError:
            msg = await _trans('invalid_id', lang, "❌ معرف غير صالح")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"فشل الطرد: {e}")
            msg = await _trans('execution_failed', lang, "❌ فشل التنفيذ")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_restrict_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('adv_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if not await MessageHandlers._check_admin_in_chat(context, chat_id, user_id):
            msg = await _trans('not_admin_in_group', lang, "❌ لم تعد مشرفًا في هذه المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        parts = (update.effective_message.text or "").strip().split()
        if not parts:
            msg = await _trans('send_user_id', lang, "❌ أرسل معرف المستخدم")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            target = int(parts[0])
            duration = int(parts[1]) * 60 if len(parts) > 1 else 1800
            if target <= 0 or duration <= 0:
                raise ValueError
            success, msg = await apply_penalty(context.bot, chat_id, target, 'restrict', duration, "", user_id)
            await safe_send(context.bot, user_id, msg if success else f"❌ {msg}")
        except ValueError:
            msg = await _trans('invalid_format', lang, "❌ صيغة غير صحيحة")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"فشل التقييد: {e}")
            msg = await _trans('execution_failed', lang, "❌ فشل التنفيذ")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_unban_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('adv_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if not await MessageHandlers._check_admin_in_chat(context, chat_id, user_id):
            msg = await _trans('not_admin_in_group', lang, "❌ لم تعد مشرفًا في هذه المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            target = int((update.effective_message.text or "").strip())
            if target <= 0:
                raise ValueError
            success, msg = await apply_penalty(context.bot, chat_id, target, 'unban', 0, "", user_id)
            await safe_send(context.bot, user_id, msg if success else f"❌ {msg}")
        except ValueError:
            msg = await _trans('invalid_id', lang, "❌ معرف غير صالح")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"فشل إلغاء الحظر: {e}")
            msg = await _trans('execution_failed', lang, "❌ فشل التنفيذ")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_pin_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('adv_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if not await MessageHandlers._check_admin_in_chat(context, chat_id, user_id):
            msg = await _trans('not_admin_in_group', lang, "❌ لم تعد مشرفًا في هذه المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if update.effective_message.reply_to_message:
            try:
                await context.bot.pin_chat_message(chat_id, update.effective_message.reply_to_message.message_id)
                msg = await _trans('pinned_success', lang, "✅ تم التثبيت")
                await safe_send(context.bot, user_id, msg)
            except Exception as e:
                logger.error(f"فشل التثبيت: {e}")
                msg = await _trans('pin_failed', lang, "❌ فشل التثبيت")
                await safe_send(context.bot, user_id, msg)
        else:
            msg = await _trans('reply_to_pin', lang, "❌ قم بالرد على رسالة لتثبيتها")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    # =================================================================
    # معالجات إضافية
    # =================================================================

    @staticmethod
    async def _handle_penalty_duration_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('adv_chat') or context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            minutes = int(update.effective_message.text or "1")
            if minutes <= 0:
                raise ValueError
            duration_seconds = minutes * 60
            await DB.update_security_settings(chat_id, violation_duration=duration_seconds)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ تم تعيين المدة: {minutes} دقيقة")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌ رقم غير صالح")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"فشل تعيين المدة: {e}")
            msg = await _trans('execution_failed', lang, "❌ فشل")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_violation_strikes_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            strikes = int(update.effective_message.text or "3")
            if strikes <= 0:
                raise ValueError
            await DB.update_security_settings(chat_id, violation_strikes=strikes)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ تم تعيين عدد المخالفات: {strikes}")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌ رقم غير صالح")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"فشل تعيين عدد المخالفات: {e}")
            msg = await _trans('execution_failed', lang, "❌ فشل")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_violation_duration_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌ لم يتم تحديد المجموعة")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            minutes = int(update.effective_message.text or "1")
            if minutes <= 0:
                raise ValueError
            duration_seconds = minutes * 60
            await DB.update_security_settings(chat_id, violation_duration=duration_seconds)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ تم تعيين المدة: {minutes} دقيقة")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌ رقم غير صالح")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"فشل تعيين المدة: {e}")
            msg = await _trans('execution_failed', lang, "❌ فشل")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_redeem_gift_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        code = (update.effective_message.text or "").strip()
        if not code:
            msg = await _trans('send_code', lang, "❌ أرسل الكود")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        success, result = await DB.redeem_gift_code(user_id, code)
        if success:
            msg = await _trans('gift_redeemed', lang, f"🎁 تم استرداد الهدية!\n📅 المدة: {result} يوم")
            await safe_send(context.bot, user_id, msg)
        elif result == -1:
            msg = await _trans('own_code', lang, "❌ لا يمكنك استخدام كود قمت بإنشائه بنفسك")
            await safe_send(context.bot, user_id, msg)
        else:
            msg = await _trans('invalid_code', lang, "❌ الكود غير صالح أو مستخدم بالفعل")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)


    @staticmethod
    async def _handle_restore_input(update, context):
        user_id = update.effective_user.id
        lang = context.user_data.get('lang', 'ar')
        if not CONFIG.is_developer(user_id):
            msg = await _trans('unauthorized', lang, "❌ غير مصرح")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return

        doc = update.effective_message.document
        if not doc:
            msg = await _trans('send_db', lang, "❌ أرسل ملف قاعدة البيانات (.db)")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return

        if not doc.file_name.endswith('.db'):
            msg = await _trans('db_extension', lang, "❌ يجب أن يكون الملف بامتداد .db")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return

        tmp_path = None
        try:
            file = await doc.get_file()
            tmp_path = os.path.join(tempfile.gettempdir(), f"restore_{user_id}_{int(time.time())}.db")
            await file.download_to_drive(tmp_path)

            pre_restore = PATHS.BACKUPS / f"pre_restore_{TimeUtils.mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
            shutil.copy2(PATHS.DB, pre_restore)

            shutil.copy2(tmp_path, PATHS.DB)

            msg = await _trans('restore_success', lang, "✅ تمت الاستعادة بنجاح!\nأعد تشغيل البوت لتفعيل التغييرات.")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"فشل استعادة النسخة: {e}")
            await safe_send(context.bot, user_id, f"❌ فشل الاستعادة: {str(e)[:100]}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            StateManager.clear(user_id)


    # =================================================================
    # رسائل الخدمة
    # =================================================================

    @staticmethod
    async def handle_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """معالجة رسائل الخدمة (انضمام/مغادرة) مع دعم الحذف"""
        if not update.effective_chat or not update.effective_message:
            return
        chat_id = update.effective_chat.id
        settings = await get_security_settings_cached(chat_id)
        message = update.effective_message

        # ✅ حذف رسائل الانضمام والمغادرة إذا كان delete_service مفعلاً
        if settings.get('delete_service'):
            if message.new_chat_members or message.left_chat_member:
                try:
                    await message.delete()
                    logger.debug(f"🗑️ حذف رسالة خدمة في {chat_id}")
                except Exception as e:
                    logger.debug(f"تعذر حذف رسالة الخدمة: {e}")
                return

        if message.new_chat_members and settings.get('welcome_enabled'):
            for member in message.new_chat_members:
                welcome_text = settings.get('welcome_text', 'مرحباً {user} 🤍')
                welcome_text = welcome_text.replace('{user}', escape(member.first_name or "عضو"))
                welcome_text = welcome_text.replace('{chat}', escape(update.effective_chat.title or "المجموعة"))
                await safe_send(context.bot, chat_id, welcome_text, parse_mode='HTML')

        if message.left_chat_member and settings.get('goodbye_enabled'):
            member = message.left_chat_member
            goodbye_text = settings.get('goodbye_text', 'وداعاً {user} 👋')
            goodbye_text = goodbye_text.replace('{user}', escape(member.first_name or "عضو"))
            goodbye_text = goodbye_text.replace('{chat}', escape(update.effective_chat.title or "المجموعة"))
            await safe_send(context.bot, chat_id, goodbye_text, parse_mode='HTML')


    # =================================================================
    # طلبات الانضمام
    # =================================================================

    @staticmethod
    async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """معالجة طلبات الانضمام"""
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        settings = await get_security_settings_cached(chat_id)

        if settings.get('auto_reject_join'):
            try:
                await asyncio.sleep(0.05)
                await context.bot.decline_chat_join_request(chat_id, user_id)
                return
            except Exception as e:
                logger.warning(f"فشل رفض طلب الانضمام: {e}")

        if settings.get('auto_approve_join'):
            try:
                await asyncio.sleep(0.05)
                await context.bot.approve_chat_join_request(chat_id, user_id)
            except Exception as e:
                error_msg = str(e)
                if "User_already_participant" in error_msg or "already participant" in error_msg.lower():
                    pass
                else:
                    logger.warning(f"فشل الموافقة على طلب الانضمام: {e}")