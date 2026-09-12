#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_callback.py - المعالج النهائي الكامل لجميع الأزرار
=====================================================================
الإصدار: v7.5.13 (مُصحَّح ومحسّن)
=====================================================================
🆕 v7.5.13 (إصلاح بطء الأزرار أثناء النشر):
    ✅ MAX_CONCURRENT_PUBLISH = 2 (بدل 3)
    ✅ PUBLISH_DELAY_SECONDS = 0.2 (بدل 0.5)
    ✅ استخدام PUBLISH_RATE_LIMITER المنفصل في _publish_all
       (يمنع تأثير النشر على استجابة الأزرار)

🆕 v7.5.12:
    ✅ handle(): query.answer() في البداية — استجابة فورية للأزرار (< 100ms)
    ✅ _safe_answer: يتجاهل "already been answered" و "query is too old"
    ✅ _handle_language_change: يستخدم _show_main_menu_inline
    ✅ _show_main_menu_inline: يستخدم KeyboardFactory.build("main_menu", ...)
    ✅ Semaphore مشترك للنشر الجماعي (_publish_semaphore)
    ✅ _do_backup: يحفظ last_backup بأمان
    ✅ تحويل التنبيهات الحرجة من show_alert=True إلى safe_edit
    ✅ حماية كاملة ضد None

🆕 v7.5.11:
    ✅ _show_main_menu_inline: عرض القائمة الرئيسية بتعديل الرسالة (أسرع 10x)
    ✅ CB.MAIN/CB.BACK: استخدام العرض السريع بدل CommandHandlers.start
    ✅ CB.CHECK_SUB: استخدام العرض السريع

🆕 v7.5.10:
    ✅ إصلاح جذري: إضافة return بعد كل فرع في _handle_advanced_actions
    ✅ إصلاح: return في _handle_contests و _handle_auto_reply
    ✅ إضافة Dispatch Table مساعد لتوجيه أسرع
    ✅ _clear_context_keys يدعم extra_keys بشكل صحيح
    ✅ معالجة asyncio.CancelledError في كل المهام الخلفية
    ✅ تحسين _unwrap_get_next_post لدعم كل الحالات
    ✅ حماية start_time في context.bot_data
    ✅ إصلاح استعلامات admin_logs (created_at بدل timestamp)

🆕 v7.5.9:
    ✅ CB.CANCEL يحذف لوحة المفاتيح
    ✅ CB.MAIN/CB.BACK لا يمسح debounce/rate limiting
    ✅ استخدام DB.get_user_settings_batch (استعلام واحد)

🆕 v7.5.7:
    ✅ get_next_post تُرجع (dict, was_recycled)

🆕 v7.5.2:
    ✅ Rate Limiting (30 ضغطة/دقيقة)
    ✅ حماية effective_chat من None
    ✅ تأخير 500ms في _publish_all
=====================================================================
"""

import asyncio
import logging
import json
import time
import shutil
import os
import weakref
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Callable, Awaitable

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice, ChatPermissions
)
from telegram.ext import ContextTypes
from telegram.error import BadRequest, RetryAfter, Forbidden

from config import CONFIG, PATHS
from database import DB, TimeUtils

# ✅ v7.5.13: استيراد PUBLISH_RATE_LIMITER المنفصل
try:
    from utils import (
        safe_send, is_authorized_in_group,
        get_text, StateManager, UserState,
        KeyboardFactory, CB, get_ram_usage,
        invalidate_auth_cache, apply_penalty,
        export_auto_replies, import_auto_replies,
        fetch_json_from_url,
        PUBLISH_RATE_LIMITER,
    )
except ImportError:
    # fallback: إذا لم يكن PUBLISH_RATE_LIMITER موجوداً بعد
    from utils import (
        safe_send, is_authorized_in_group,
        get_text, StateManager, UserState,
        KeyboardFactory, CB, get_ram_usage,
        invalidate_auth_cache, apply_penalty,
        export_auto_replies, import_auto_replies,
        fetch_json_from_url,
        RATE_LIMITER,
    )
    PUBLISH_RATE_LIMITER = RATE_LIMITER
    logging.getLogger(__name__).warning(
        "⚠️ PUBLISH_RATE_LIMITER غير موجود في utils.py — استخدام RATE_LIMITER"
    )

try:
    from cache import user_cache, invalidate_user_cache
except ImportError:
    async def invalidate_user_cache(user_id):
        pass

try:
    from .handlers_command import CommandHandlers, _invalidate_force_sub_cache
except ImportError:
    from handlers_command import CommandHandlers, _invalidate_force_sub_cache

logger = logging.getLogger(__name__)

# =====================================================================
# ثوابت
# =====================================================================

MAX_CAPTION_LENGTH = 1024
MAX_MESSAGE_LENGTH = 4096
MAX_BACKUPS = getattr(CONFIG, "MAX_BACKUPS", 10)

# ✅ v7.5.13: خفض من 3 إلى 2 لتقليل الحجز
MAX_CONCURRENT_PUBLISH = 2
MAX_PUBLISH_DELAY_SECONDS = 60

ACTIVE_TASKS: weakref.WeakSet = weakref.WeakSet()

# ✅ v7.5.12: Semaphore مشترك للنشر الجماعي
_publish_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PUBLISH)

# ✅ v7.5.9: مفاتيح السياق التي تُمحى عند الرجوع للرئيسية
_CONTEXT_KEYS_TO_CLEAR = (
    'security_chat_id', 'auto_chat', 'adv_chat', 'schedule_ch',
    'ban_chat', 'contest_join', 'channel_page', 'post_page', 'sec_chat',
)

# ✅ v7.5.10: المفاتيح الإضافية التي تُمحى عند CANCEL (مع كل السياق)
_CANCEL_EXTRA_KEYS = ('pin_msg_id',)


# =====================================================================
# دوال مساعدة عامة
# =====================================================================

async def _safe_answer(query, text=None, show_alert=False) -> bool:
    """
    ✅ v7.5.12: دالة مساعدة للإجابة على الاستعلامات بأمان.

    - يتجاهل "already been answered" و "query is too old"
    - يُرجع True إذا نجح أو إذا كان الاستعلام قد أُجيب مسبقاً
    """
    if not query:
        return False
    try:
        if text:
            await query.answer(text, show_alert=show_alert)
        else:
            await query.answer()
        return True
    except BadRequest as e:
        err = str(e).lower()
        if "query is too old" in err or "already been answered" in err:
            return True
        logger.debug(f"Query answer error: {e}")
        return False
    except Exception as e:
        logger.debug(f"Query answer error: {e}")
        return False


async def _trans(key, lang, default_ar) -> str:
    """جلب النص المترجم مع fallback للعربية"""
    if not lang:
        return default_ar
    try:
        text = await get_text(lang, key)
        if not text or text == key:
            return default_ar
        return text
    except Exception:
        return default_ar


async def safe_edit(query, text, reply_markup=None, parse_mode=None, bot=None) -> bool:
    """
    تعديل الرسالة بأمان مع معالجة الأخطاء.
    ✅ v7.5.12: لا يستدعي _safe_answer تلقائياً.
    """
    if not query or not query.message:
        # إذا لم يكن هناك رسالة قابلة للتعديل، نحاول الإرسال عبر bot
        if bot and query and query.from_user:
            try:
                await bot.send_message(
                    chat_id=query.from_user.id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                return True
            except Exception as e:
                logger.debug(f"safe_edit fallback send: {e}")
        return False

    try:
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=parse_mode
        )
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
                send_bot = bot if bot else getattr(query, '_bot', None)
                if send_bot:
                    await send_bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                    return True
                return False
            except Exception as e2:
                logger.error(f"فشل إرسال رسالة جديدة بعد الطول الزائد: {e2}")
                return False
        elif "query is too old" in error_msg:
            logger.debug(f"safe_edit: query too old")
            return False
        else:
            logger.debug(f"safe_edit BadRequest: {e}")
            return False
    except Exception as e:
        logger.debug(f"Edit error: {e}")
        return False


async def safe_delete_message(query_or_message) -> None:
    """حذف رسالة بأمان"""
    try:
        if hasattr(query_or_message, 'message') and query_or_message.message:
            await query_or_message.message.delete()
        elif query_or_message:
            await query_or_message.delete()
    except Exception:
        pass


def _mask_id(id_value, prefix=3, suffix=2) -> str:
    """إخفاء جزء من المعرفات الحساسة"""
    if id_value is None:
        return "***"
    s = str(id_value)
    if len(s) <= 5:
        return "***"
    return s[:prefix] + "***" + s[-suffix:]


async def _is_channel_owner(user_id: int, channel_db_id: int) -> bool:
    """التحقق من ملكية القناة"""
    try:
        return await DB.is_channel_owner(user_id, channel_db_id)
    except Exception as e:
        logger.error(f"_is_channel_owner: {e}")
        return False


def _clear_context_keys(context, extra_keys=None) -> None:
    """
    ✅ v7.5.9: تمسح مفاتيح السياق فقط، وتُبقي:
    - last_cb_* (debounce)
    - rate_* (rate limiting)
    """
    for k in _CONTEXT_KEYS_TO_CLEAR:
        context.user_data.pop(k, None)
    if extra_keys:
        for k in extra_keys:
            context.user_data.pop(k, None)


def _ensure_bot_start_time(context) -> None:
    """✅ v7.5.10: التأكد من وجود start_time في bot_data"""
    if 'start_time' not in context.bot_data:
        context.bot_data['start_time'] = time.monotonic()


# =====================================================================
# CallbackHandlers
# =====================================================================

class CallbackHandlers:
    """جميع معالجات الأزرار"""

    # ✅ v7.5.2: حد ضغطات الأزرار لكل مستخدم في الدقيقة
    RATE_LIMIT_PER_MINUTE = 30
    # ✅ v7.5.13: خفض من 0.5 إلى 0.2 لتسريع النشر
    PUBLISH_DELAY_SECONDS = 0.2
    # ✅ v7.5.2: حجم الدفعة في النشر الجماعي
    PUBLISH_BATCH_SIZE = 10

    # =================================================================
    # المعالج الرئيسي
    # =================================================================

    @staticmethod
    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """المعالج الرئيسي لجميع الأزرار"""
        query = update.callback_query
        if not query:
            return
        data = query.data
        if not data:
            return

        user_id = query.from_user.id
        now_time = time.monotonic()

        # ✅ v7.5.2: Debounce بمفتاح واحد لكل مستخدم
        last_cb_key = f"last_cb_{user_id}"
        last_time = context.user_data.get(last_cb_key, 0)
        if now_time - last_time < 1.5:
            await _safe_answer(query, "⚠️ انتظر لحظة")
            return
        context.user_data[last_cb_key] = now_time

        # ============================================================
        # ✅ v7.5.12: الإجابة الفورية — قبل أي عمل آخر
        # ============================================================
        await _safe_answer(query)

        # ✅ v7.5.2: Rate Limiting (بدون show_alert — لأن answer استُدعي)
        rate_key = f"rate_{user_id}"
        rate_data = context.user_data.get(rate_key)
        if not rate_data or now_time - rate_data.get('reset', 0) > 60:
            rate_data = {'count': 0, 'reset': now_time}
        rate_data['count'] = rate_data.get('count', 0) + 1
        context.user_data[rate_key] = rate_data
        if rate_data['count'] > CallbackHandlers.RATE_LIMIT_PER_MINUTE:
            return

        lang = await DB.get_user_language(user_id) or 'ar'
        start_time = time.monotonic()
        _ensure_bot_start_time(context)

        # ✅ v7.5.10: معالجة الأزرار ذات الصيغة الخاصة (تتضمن ":")
        handled = await CallbackHandlers._handle_parameterized(
            update, context, query, user_id, lang, data
        )
        if handled:
            elapsed = time.monotonic() - start_time
            if elapsed > 1.0:
                logger.warning(f"🐢 زر بطيء (param) {data[:30]} — {elapsed:.2f}s")
            return

        # ✅ v7.5.10: تحديد base_data للتوافق
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
                CB.ADMIN_LIST_ADMINS,
            ]
            if parts[0] in known:
                base_data = parts[0]

        try:
            # ====== أساسيات ======
            if base_data == "status_only":
                await safe_edit(
                    query,
                    await _trans('status', lang, "📊 الحالة"),
                    bot=context.bot,
                )
                return

            if base_data in (CB.MAIN, CB.BACK):
                StateManager.clear(user_id)
                _clear_context_keys(context)
                context.args = []
                ok = await CallbackHandlers._show_main_menu_inline(
                    query, context, user_id
                )
                if not ok:
                    await CommandHandlers.start(update, context)
                return

            if base_data == CB.CANCEL:
                StateManager.clear(user_id)
                _clear_context_keys(context, extra_keys=list(_CANCEL_EXTRA_KEYS))
                context.args = []
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass
                return

            if base_data == CB.HELP:
                StateManager.clear(user_id)
                await CommandHandlers.help_command(update, context)
                return

            if base_data == CB.TRIAL:
                if await DB.has_used_trial(user_id):
                    await safe_edit(
                        query,
                        await _trans('trial_used', lang, "❌ لقد استخدمت التجربة المجانية بالفعل."),
                        bot=context.bot,
                    )
                    return
                days = await DB.activate_trial(user_id)
                text = f"✅ تم تفعيل التجربة المجانية لمدة {days} يوم" if days > 0 else "❌ تعذر تفعيل التجربة"
                await safe_edit(query, text, bot=context.bot)
                await invalidate_user_cache(user_id)
                return

            if base_data == CB.DEVELOPER:
                StateManager.clear(user_id)
                await CommandHandlers.developer(update, context)
                return

            if base_data == CB.SUBSCRIBE:
                StateManager.clear(user_id)
                await CommandHandlers.subscribe(update, context)
                return

            if base_data == CB.SUPPORT:
                StateManager.clear(user_id)
                await CommandHandlers.support(update, context)
                return

            if base_data == CB.LANGUAGE:
                StateManager.clear(user_id)
                await CommandHandlers.language(update, context)
                return

            if base_data == CB.CHECK_SUB:
                try:
                    _invalidate_force_sub_cache(user_id)
                except Exception as e:
                    logger.debug(f"فشل إبطال كاش الاشتراك الإجباري: {e}")
                StateManager.clear(user_id)
                ok = await CallbackHandlers._show_main_menu_inline(
                    query, context, user_id
                )
                if not ok:
                    await CommandHandlers.start(update, context)
                return

            # ====== الإعدادات ======
            if base_data == CB.SETTINGS:
                await CallbackHandlers._render_settings(query, context, user_id, lang)
                return

            if base_data == CB.TOGGLE_AUTO:
                cur = await DB.get_auto_publish_status(user_id)
                await DB.set_auto_publish(user_id, not cur)
                await CallbackHandlers._render_settings(query, context, user_id, lang)
                await invalidate_user_cache(user_id)
                return

            if base_data == CB.TOGGLE_REC:
                cur = await DB.get_auto_recycle_status(user_id)
                await DB.set_auto_recycle(user_id, not cur)
                await CallbackHandlers._render_settings(query, context, user_id, lang)
                await invalidate_user_cache(user_id)
                return

            # ====== الباقات والدفع ======
            if base_data == CB.PLANS:
                await safe_edit(query, "💎 اختر باقة:",
                                reply_markup=KeyboardFactory.build("plans", lang=lang),
                                bot=context.bot)
                return

            if base_data == "gift_plans":
                plans = await DB.get_gift_plans()
                if not plans:
                    await safe_edit(query, "📭 لا توجد خطط هدايا", bot=context.bot)
                    return
                kb = [
                    [InlineKeyboardButton(f"🎁 {p['days']} يوم - {p['price']} ⭐",
                                          callback_data=f"buy_gift:{p['id']}")]
                    for p in plans
                ]
                kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)])
                await safe_edit(query, "💎 اختر خطة هدية:",
                                reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)
                return

            if base_data == "redeem_gift":
                StateManager.clear(user_id)
                await CommandHandlers.redeem_gift(update, context)
                return

            if base_data == CB.INVOICES:
                invoices = await DB.get_user_invoices(user_id, 10)
                if not invoices:
                    await safe_edit(query, "📭 لا توجد فواتير", bot=context.bot)
                    return
                text = "🧾 فواتيري\n\n" + "\n".join(
                    f"• #{inv['number']} - {inv['amount']} ⭐" for inv in invoices
                )
                await safe_edit(
                    query, text,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)]]
                    ),
                    bot=context.bot,
                )
                return

            # ====== الإحالات ======
            if base_data == CB.REFERRAL:
                await CallbackHandlers._render_referral(query, context, user_id, lang)
                return

            if base_data == CB.REF_CLAIM:
                days = await DB.claim_referral_reward(user_id)
                text = f"✅ تم صرف {days} يوم!" if days > 0 else "📭 لا توجد مكافآت"
                await safe_edit(
                    query, text,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔙 رجوع", callback_data=CB.REFERRAL)]]
                    ),
                    bot=context.bot,
                )
                await invalidate_user_cache(user_id)
                return

            if base_data == CB.REF_LIST:
                refs = await DB.get_referrals_list(user_id)
                text = "📋 المُحالين\n\n" + "\n".join(
                    f"{i}. {_mask_id(r)}" for i, r in enumerate(refs[:20], 1)
                ) if refs else "📭 لا يوجد"
                await safe_edit(
                    query, text,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔙 رجوع", callback_data=CB.REFERRAL)]]
                    ),
                    bot=context.bot,
                )
                return

            # ====== التذكيرات ======
            if base_data in (CB.REM_TOGGLE_SUB, CB.REM_TOGGLE_DAILY, CB.REM_TOGGLE_WEEKLY):
                await CallbackHandlers._handle_reminder_toggle(
                    query, context, user_id, lang, base_data
                )
                return

            if base_data == CB.REMINDER:
                await CallbackHandlers._render_reminder(query, context, user_id, lang)
                return

            if base_data == CB.REM_SET_DAYS:
                StateManager.set(user_id, UserState.WAIT_REM_DAYS)
                await safe_edit(query, "📅 أرسل عدد الأيام (1-30):", bot=context.bot)
                return

            # ====== الترجمة ======
            if base_data == CB.TRANSLATION:
                await CallbackHandlers._render_translation_menu(query, context, lang)
                return

            if base_data == CB.TRANS_OFF:
                await DB.set_user_language(user_id, 'off')
                await safe_edit(query, "✅ تم إيقاف الترجمة", bot=context.bot)
                await invalidate_user_cache(user_id)
                return

            # ====== المسابقات ======
            if base_data == CB.CONTESTS:
                StateManager.clear(user_id)
                await CommandHandlers.contests(update, context)
                return

            if base_data == CB.CONTEST_WINNERS:
                winners = await DB.get_contest_winners(10)
                text = "🏆 الفائزون\n\n" + "\n".join(
                    f"• {w['title']} - {_mask_id(w['winner_id'])}" for w in winners
                ) if winners else "📭 لا يوجد"
                await safe_edit(
                    query, text,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)]]
                    ),
                    bot=context.bot,
                )
                StateManager.clear(user_id)
                return

            # ====== الدعم ======
            if base_data == CB.SUPPORT_TICKET:
                StateManager.set(user_id, UserState.SUPPORT_MODE)
                await safe_send(context.bot, user_id, "📞 أرسل رسالتك:")
                return

            # ====== القنوات ======
            if base_data == CB.CH_ADD:
                if not await DB.has_active_subscription(user_id) and user_id != CONFIG.PRIMARY_OWNER_ID:
                    await safe_edit(query, "❌ يتطلب اشتراك نشط", bot=context.bot)
                    return
                StateManager.set(user_id, UserState.WAIT_CHANNEL)
                await safe_edit(query, "📡 أرسل معرف القناة:", bot=context.bot)
                return

            if base_data == CB.CH_LIST:
                await CallbackHandlers._show_channel_list(update, context, query, user_id, lang)
                return

            # ====== المنشورات ======
            if base_data == CB.POST_ADD:
                await CallbackHandlers._handle_post_add(update, context, query, user_id)
                return

            if base_data == "finish_posts":
                StateManager.clear(user_id)
                return

            if base_data == CB.POST_PUB:
                await CallbackHandlers._handle_post_publish(update, context, query, user_id)
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
                    await safe_edit(query, "❌ لا توجد قناة نشطة", bot=context.bot)
                return

            if base_data == CB.POST_CLEAR:
                active = await DB.get_active_channel(user_id)
                if active:
                    await DB.execute("DELETE FROM posts WHERE channel_db_id=?", (active,))
                    await safe_edit(query, "✅ تم مسح جميع المنشورات", bot=context.bot)
                else:
                    await safe_edit(query, "❌ لا توجد قناة نشطة", bot=context.bot)
                return

            if base_data == CB.PUB_ALL:
                await CallbackHandlers._handle_publish_all(update, context, query, user_id)
                return

            # ====== المجموعات ======
            if base_data == CB.GROUPS:
                await CallbackHandlers._show_groups_list(update, context, query, user_id, lang)
                return

            # ====== لوحة الأدمن ======
            if base_data == CB.ADMIN:
                if not CONFIG.is_developer(user_id):
                    await safe_edit(query, "❌ غير مصرح", bot=context.bot)
                    return
                kb = KeyboardFactory.build("admin_panel", lang=lang)
                await safe_edit(query, "👑 لوحة الأدمن", reply_markup=kb, bot=context.bot)
                return

            # ====== التوجيه لمعالجات معقدة ======
            if data.startswith("sec_"):
                await CallbackHandlers._handle_security(update, context, query, user_id, lang)
                return

            if data.startswith("admin_") or data == "admin_grant_free":
                if CONFIG.is_developer(user_id):
                    await CallbackHandlers._handle_admin(update, context, query, user_id, lang)
                else:
                    await safe_edit(query, "❌ غير مصرح", bot=context.bot)
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
                await CallbackHandlers._handle_language_change(update, context, query, user_id)
                return

            # ====== ترقيم الصفحات ======
            if data == "ch_page_prev":
                context.user_data['channel_page'] = max(
                    0, context.user_data.get('channel_page', 0) - 1
                )
                await CallbackHandlers._show_channel_list(update, context, query, user_id, lang)
                return
            if data == "ch_page_next":
                context.user_data['channel_page'] = (
                    context.user_data.get('channel_page', 0) + 1
                )
                await CallbackHandlers._show_channel_list(update, context, query, user_id, lang)
                return
            if data == "post_page_prev":
                context.user_data['post_page'] = max(
                    0, context.user_data.get('post_page', 0) - 1
                )
                await CallbackHandlers._show_post_list(update, context, query, user_id, lang)
                return
            if data == "post_page_next":
                context.user_data['post_page'] = (
                    context.user_data.get('post_page', 0) + 1
                )
                await CallbackHandlers._show_post_list(update, context, query, user_id, lang)
                return

            # ====== لوحة خاصة ======
            if data in ("panel_lock", "panel_unlock", "panel_close"):
                await CallbackHandlers._handle_panel(update, context, query, user_id, data)
                return

            # ====== fallback ======
            await safe_edit(query, "⚠️ غير متوفر", bot=context.bot)

        except BadRequest as e:
            if "query is too old" not in str(e).lower():
                logger.error(f"❌ BadRequest: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"❌ Callback error: {e}", exc_info=True)
        finally:
            elapsed = time.monotonic() - start_time
            if elapsed > 1.0:
                logger.warning(f"🐢 زر بطيء {data[:30]} — {elapsed:.2f}s")

    # =================================================================
    # ✅ v7.5.11: عرض القائمة الرئيسية بتعديل الرسالة
    # ✅ v7.5.12: يستخدم KeyboardFactory.build("main_menu", ...)
    # =================================================================

    @staticmethod
    async def _show_main_menu_inline(query, context, user_id) -> bool:
        """
        عرض القائمة الرئيسية عبر safe_edit بدل CommandHandlers.start.

        يوفّر:
        - عدم استدعاء register_user
        - عدم استدعاء get_force_subscribe_channel
        - عدم إرسال رسالة جديدة (يُعدّل الحالية)

        الوقت المتوقع: < 500ms بدل 2-4s
        """
        try:
            user_data = await user_cache.get(user_id)
            if not user_data:
                try:
                    user_data = await user_cache.get_or_load(user_id, DB)
                except AttributeError:
                    user_data = await DB.get_start_data(user_id) or {}

            lang = user_data.get('language', 'ar') or 'ar'
            channel_info = user_data.get('channel_info')
            unpublished_posts = user_data.get('unpublished_posts', 0)
            groups_count = user_data.get('groups_count', 0)
            has_sub = bool(user_data.get('has_subscription', False))
            auto_raw = user_data.get('auto_publish', True)
            recycle_raw = user_data.get('auto_recycle', True)
            auto = bool(auto_raw) if not isinstance(auto_raw, bool) else auto_raw
            recycle = bool(recycle_raw) if not isinstance(recycle_raw, bool) else recycle_raw

            ch_display = await _trans(
                'no_active_channel', lang, "لا توجد قنوات"
            )
            if channel_info and isinstance(channel_info, dict):
                ch_display = channel_info.get('channel_name', ch_display) or ch_display

            sub_text = (
                await _trans('subscription_active', lang, "✅ مفعل")
                if has_sub
                else await _trans('subscription_inactive', lang, "❌ غير مفعل")
            )
            auto_text = (
                await _trans('enabled', lang, "مفعل")
                if auto
                else await _trans('disabled', lang, "معطل")
            )
            recycle_text = (
                await _trans('enabled', lang, "مفعل")
                if recycle
                else await _trans('disabled', lang, "معطل")
            )

            # ✅ v7.5.12: استخدام KeyboardFactory.build
            try:
                kb = KeyboardFactory.build("main_menu", lang=lang)
            except Exception as e:
                logger.warning(f"⚠️ KeyboardFactory.build('main_menu') فشل: {e}")
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)
                ]])

            # ✅ إضافة زر الأدمن إن لزم
            if CONFIG.is_developer(user_id):
                admin_text = KeyboardFactory.get_text("admin_panel_btn", lang)
                existing_callbacks = set()
                for row in kb.inline_keyboard:
                    for btn in row:
                        if btn.callback_data:
                            existing_callbacks.add(btn.callback_data)
                if CB.ADMIN not in existing_callbacks:
                    new_rows = list(kb.inline_keyboard)
                    new_rows.append([
                        InlineKeyboardButton(admin_text, callback_data=CB.ADMIN)
                    ])
                    kb = InlineKeyboardMarkup(new_rows)

            title = await get_text(
                lang,
                'main_menu',
                user_name=f"<code>{user_id}</code>",
                groups_count=groups_count,
                active_channel=ch_display,
                unpublished_posts=unpublished_posts,
                auto_publish=auto_text,
                auto_recycle=recycle_text,
                subscription_status=sub_text,
            )

            await safe_edit(
                query, title, reply_markup=kb, bot=context.bot
            )
            return True

        except Exception as e:
            logger.error(
                f"_show_main_menu_inline: {e}", exc_info=True
            )
            return False

    # =================================================================
    # معالجة الأزرار ذات الصيغة الخاصة "xxx:yyy:zzz"
    # =================================================================

    @staticmethod
    async def _handle_parameterized(
        update, context, query, user_id, lang, data
    ) -> bool:
        """
        ✅ v7.5.10: معالجة موحّدة للأزرار ذات الصيغة الخاصة.
        تُرجع True إذا تمت المعالجة، False إذا لا تنطبق.
        """
        try:
            # ========== set_warn_penalty ==========
            if data.startswith("set_warn_penalty:"):
                parts = data.split(":")
                if len(parts) != 3:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                _, penalty_type, chat_id_str = parts
                try:
                    chat_id = int(chat_id_str)
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                if penalty_type not in DB.VALID_PENALTY_TYPES:
                    await safe_edit(query, "❌ نوع عقوبة غير صالح", bot=context.bot)
                    return True
                await DB.update_security_settings(chat_id, warn_penalty=penalty_type)
                settings = await DB.get_security_settings(chat_id)
                await safe_edit(
                    query,
                    KeyboardFactory._format_security_text(settings),
                    reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                    bot=context.bot,
                )
                return True

            # ========== set_warn_duration ==========
            if data.startswith("set_warn_duration:"):
                parts = data.split(":")
                if len(parts) != 3:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[2])
                    duration = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                await DB.update_security_settings(chat_id, warn_penalty_duration=duration)
                settings = await DB.get_security_settings(chat_id)
                await safe_edit(
                    query,
                    KeyboardFactory._format_security_text(settings),
                    reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                    bot=context.bot,
                )
                return True

            # ========== set_duration ==========
            if data.startswith("set_duration:"):
                parts = data.split(":")
                if len(parts) < 4:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    penalty_type = parts[1]
                    chat_id = int(parts[2])
                    duration = int(parts[3])
                except (ValueError, IndexError):
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True

                col_map = {
                    'mute': 'mute_default_duration',
                    'ban': 'ban_default_duration',
                    'restrict': 'restrict_default_duration',
                    'antiflood': 'antiflood_penalty_duration',
                    'night': 'night_mode_action_duration',
                    'warn_penalty': 'warn_penalty_duration',
                    'delete_penalty': 'delete_penalty_duration',
                    'violation': 'violation_penalty_duration',
                }
                col = col_map.get(penalty_type)
                if col is None:
                    await safe_edit(query, "❌ نوع عقوبة غير صالح", bot=context.bot)
                    return True
                await DB.update_security_settings(chat_id, **{col: duration})
                settings = await DB.get_security_settings(chat_id)
                await safe_edit(
                    query,
                    KeyboardFactory._format_security_text(settings),
                    reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                    bot=context.bot,
                )
                return True

            # ========== sec_set_del_penalty ==========
            if data.startswith("sec_set_del_penalty:"):
                parts = data.split(":")
                if len(parts) != 3:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                _, penalty_type, chat_id_str = parts
                try:
                    chat_id = int(chat_id_str)
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True

                if penalty_type == "none":
                    await DB.update_security_settings(chat_id, delete_penalty="none")
                elif penalty_type in DB.VALID_PENALTY_TYPES:
                    await DB.update_security_settings(chat_id, delete_penalty=penalty_type)
                else:
                    await safe_edit(query, "❌ نوع عقوبة غير صالح", bot=context.bot)
                    return True
                settings = await DB.get_security_settings(chat_id)
                await safe_edit(
                    query,
                    KeyboardFactory._format_security_text(settings),
                    reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                    bot=context.bot,
                )
                return True

            # ========== sec_set_del_penalty_duration ==========
            if data.startswith("sec_set_del_penalty_duration:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                await CallbackHandlers._show_penalty_durations(
                    update, context, query, chat_id, lang, 'delete_penalty'
                )
                return True

            # ========== sec_penalty_durations ==========
            if data.startswith("sec_penalty_durations:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                await CallbackHandlers._show_all_penalty_durations_menu(query, context, chat_id)
                return True

            # ========== sec_set_mute/ban/restrict_duration ==========
            for prefix, action_type in (
                ("sec_set_mute_duration:", "mute"),
                ("sec_set_ban_duration:", "ban"),
                ("sec_set_restrict_duration:", "restrict"),
            ):
                if data.startswith(prefix):
                    parts = data.split(":")
                    if len(parts) != 2:
                        await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                        return True
                    try:
                        chat_id = int(parts[1])
                    except ValueError:
                        await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                        return True
                    await CallbackHandlers._show_penalty_durations(
                        update, context, query, chat_id, lang, action_type
                    )
                    return True

            # ========== sec_antiflood_duration / sec_night_duration ==========
            for prefix, action_type in (
                ("sec_antiflood_duration:", "antiflood"),
                ("sec_night_duration:", "night"),
            ):
                if data.startswith(prefix):
                    parts = data.split(":")
                    if len(parts) != 2:
                        await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                        return True
                    try:
                        chat_id = int(parts[1])
                    except ValueError:
                        await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                        return True
                    await CallbackHandlers._show_penalty_durations(
                        update, context, query, chat_id, lang, action_type
                    )
                    return True

            # ========== sec_warn_penalty_duration ==========
            if data.startswith("sec_warn_penalty_duration:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                await CallbackHandlers._show_penalty_durations(
                    update, context, query, chat_id, lang, 'warn_penalty'
                )
                return True

            # ========== sec_penalty_* ==========
            if data.startswith("sec_penalty_"):
                parts = data.split(":")
                if len(parts) >= 2 and parts[1].lstrip('-').isdigit():
                    chat_id = int(parts[1])
                else:
                    chat_id = context.user_data.get('security_chat_id')
                    if not chat_id and update.effective_chat:
                        chat_id = update.effective_chat.id
                if chat_id is None:
                    await safe_edit(query, "❌ لم يتم تحديد المجموعة", bot=context.bot)
                    return True
                action = parts[0].replace("sec_penalty_", "")
                if action in ('ban', 'mute', 'kick', 'restrict', 'none'):
                    await DB.update_security_settings(chat_id, auto_penalty=action)
                    settings = await DB.get_security_settings(chat_id)
                    await safe_edit(
                        query,
                        KeyboardFactory._format_security_text(settings),
                        reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                        bot=context.bot,
                    )
                else:
                    await safe_edit(query, "❌ نوع عقوبة غير صالح", bot=context.bot)
                return True

            # ========== sec_set_antiflood_messages ==========
            if data.startswith("sec_set_antiflood_messages:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                StateManager.set(user_id, UserState.WAIT_ANTIFLOOD_MESSAGES)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "📊 أرسل عدد الرسائل المسموحة:", bot=context.bot)
                return True

            if data.startswith("sec_set_antiflood_seconds:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                StateManager.set(user_id, UserState.WAIT_ANTIFLOOD_SECONDS)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "⏱️ أرسل عدد الثواني:", bot=context.bot)
                return True

            # ========== sec_antiflood_penalty ==========
            if data.startswith("sec_antiflood_penalty:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                await CallbackHandlers._show_penalty_type_selection(
                    update, context, query, chat_id, lang, 'antiflood_penalty'
                )
                return True

            # ========== sec_set_antiflood_penalty ==========
            if data.startswith("sec_set_antiflood_penalty:"):
                parts = data.split(":")
                if len(parts) < 3:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                penalty_type = parts[2]
                if penalty_type in ('ban', 'mute', 'kick', 'restrict', 'none'):
                    await DB.update_security_settings(chat_id, antiflood_penalty=penalty_type)
                    settings = await DB.get_security_settings(chat_id)
                    await safe_edit(
                        query,
                        KeyboardFactory._format_security_text(settings),
                        reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                        bot=context.bot,
                    )
                else:
                    await safe_edit(query, "❌ نوع عقوبة غير صالح", bot=context.bot)
                return True

            # ========== sec_set_night_start ==========
            if data.startswith("sec_set_night_start:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                StateManager.set(user_id, UserState.WAIT_NIGHT_START)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🌙 أرسل وقت البدء (HH:MM):", bot=context.bot)
                return True

            if data.startswith("sec_set_night_end:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                StateManager.set(user_id, UserState.WAIT_NIGHT_END)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🌙 أرسل وقت النهاية (HH:MM):", bot=context.bot)
                return True

            # ========== sec_night_action ==========
            if data.startswith("sec_night_action:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                await CallbackHandlers._show_penalty_type_selection(
                    update, context, query, chat_id, lang, 'night_action'
                )
                return True

            # ========== sec_set_night_action ==========
            if data.startswith("sec_set_night_action:"):
                parts = data.split(":")
                if len(parts) < 3:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                action_type = parts[2]
                if action_type in ('ban', 'mute', 'kick', 'restrict'):
                    await DB.update_security_settings(chat_id, night_mode_action=action_type)
                    settings = await DB.get_security_settings(chat_id)
                    await safe_edit(
                        query,
                        KeyboardFactory._format_security_text(settings),
                        reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                        bot=context.bot,
                    )
                else:
                    await safe_edit(query, "❌ نوع إجراء غير صالح", bot=context.bot)
                return True

            # ========== sec_violation_settings ==========
            if data.startswith("sec_violation_settings:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                await CallbackHandlers._show_violation_penalties(
                    update, context, query, chat_id, lang
                )
                return True

            # ========== sec_set_violation_strikes ==========
            if data.startswith("sec_set_violation_strikes:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                StateManager.set(user_id, UserState.WAIT_VIOLATION_STRIKES)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🔢 أرسل عدد المخالفات المسموحة:", bot=context.bot)
                return True

            # ========== sec_set_violation_duration ==========
            if data.startswith("sec_set_violation_duration:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                await CallbackHandlers._show_penalty_durations(
                    update, context, query, chat_id, lang, 'violation'
                )
                return True

            # ========== sec_set_violation_penalty ==========
            if data.startswith("sec_set_violation_penalty:"):
                parts = data.split(":")
                if len(parts) < 3:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                try:
                    chat_id = int(parts[1])
                except ValueError:
                    await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
                    return True
                penalty_type = parts[2]
                if penalty_type in ('ban', 'mute', 'kick', 'restrict', 'none'):
                    await DB.update_security_settings(chat_id, violation_penalty=penalty_type)
                    settings = await DB.get_security_settings(chat_id)
                    await safe_edit(
                        query,
                        KeyboardFactory._format_security_text(settings),
                        reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                        bot=context.bot,
                    )
                else:
                    await safe_edit(query, "❌ نوع عقوبة غير صالح", bot=context.bot)
                return True

            # ========== buy_sub_* ==========
            if data.startswith("buy_sub_"):
                await CallbackHandlers._handle_buy_subscription(
                    update, context, query, user_id, data
                )
                return True

            # ========== buy_gift: ==========
            if data.startswith("buy_gift:"):
                await CallbackHandlers._handle_buy_gift(
                    update, context, query, user_id, data
                )
                return True

            # ========== grp_del: ==========
            if data.startswith("grp_del:"):
                await CallbackHandlers._handle_group_delete(
                    update, context, query, data
                )
                return True

            # ========== grp_set: ==========
            if data.startswith(CB.GRP_SET + ":"):
                await CallbackHandlers._handle_group_settings(
                    update, context, query, user_id, lang, data
                )
                return True

            # ========== ch_sel / ch_del / ch_stats ==========
            if data.startswith(CB.CH_SEL + ":"):
                await CallbackHandlers._handle_channel_select(
                    update, context, query, user_id, data
                )
                return True

            if data.startswith(CB.CH_DEL + ":"):
                await CallbackHandlers._handle_channel_delete(
                    update, context, query, user_id, lang, data
                )
                return True

            if data.startswith(CB.CH_STATS + ":"):
                await CallbackHandlers._handle_channel_stats(
                    update, context, query, user_id, data
                )
                return True

            # ========== POST_DEL ==========
            if data.startswith(CB.POST_DEL + ":"):
                await CallbackHandlers._handle_post_delete(
                    update, context, query, user_id, lang, data
                )
                return True

            # ========== admin_toggle_ch / admin_toggle_gr ==========
            if data.startswith("admin_toggle_ch:") or data.startswith("admin_toggle_gr:"):
                return False

            # ========== admin_restore_file ==========
            if data.startswith("admin_restore_file:"):
                return False

            # ========== admin_delete_contest ==========
            if data.startswith("admin_delete_contest:"):
                return False

            # ========== lang_ ==========
            if data.startswith("lang_"):
                return False

            return False

        except BadRequest as e:
            if "query is too old" not in str(e).lower():
                logger.error(f"❌ _handle_parameterized BadRequest: {e}", exc_info=True)
            return True
        except Exception as e:
            logger.error(f"❌ _handle_parameterized: {e}", exc_info=True)
            return True

    # =================================================================
    # معالجات مساعدة صغيرة
    # =================================================================

    @staticmethod
    async def _render_settings(query, context, user_id, lang):
        """عرض قائمة الإعدادات"""
        s = await DB.get_user_settings_batch(user_id)
        auto = "✅" if s.get('auto_publish') else "❌"
        rec = "✅" if s.get('auto_recycle') else "❌"
        auto_label = await _trans('auto_publish_status', lang, "📤 النشر")
        recycle_label = await _trans('auto_recycle_status', lang, "♻️ التدوير")
        kb = KeyboardFactory.build("settings", lang=lang)
        await safe_edit(
            query,
            f"⚙️ الإعدادات\n\n{auto_label}: {auto}\n{recycle_label}: {rec}",
            reply_markup=kb,
            bot=context.bot,
        )

    @staticmethod
    async def _render_referral(query, context, user_id, lang):
        """عرض صفحة الإحالة"""
        stats = await DB.get_referral_stats(user_id)
        code = await DB.get_referral_code(user_id)
        if code and code.startswith('ref_'):
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
            [InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)],
        ])
        await safe_edit(query, text, reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _render_reminder(query, context, user_id, lang):
        """عرض قائمة التذكيرات"""
        settings = await DB.get_reminder_settings(user_id) or {}
        text = (
            f"⏰ التذكيرات\n\n"
            f"🔔 الاشتراك: {'✅' if settings.get('subscription_reminder') else '❌'}\n"
            f"📊 يومي: {'✅' if settings.get('daily_stats_reminder') else '❌'}\n"
            f"📈 أسبوعي: {'✅' if settings.get('weekly_report') else '❌'}"
        )
        await safe_edit(
            query, text,
            reply_markup=KeyboardFactory.build("reminder", lang=lang),
            bot=context.bot,
        )

    @staticmethod
    async def _handle_reminder_toggle(query, context, user_id, lang, base_data):
        """تبديل تذكير"""
        settings = await DB.get_reminder_settings(user_id) or {}
        if base_data == CB.REM_TOGGLE_SUB:
            new_val = not settings.get('subscription_reminder', False)
            await DB.update_reminder_settings(user_id, subscription_reminder=new_val)
        elif base_data == CB.REM_TOGGLE_DAILY:
            new_val = not settings.get('daily_stats_reminder', False)
            await DB.update_reminder_settings(user_id, daily_stats_reminder=new_val)
        elif base_data == CB.REM_TOGGLE_WEEKLY:
            new_val = not settings.get('weekly_report', False)
            await DB.update_reminder_settings(user_id, weekly_report=new_val)
        await CallbackHandlers._render_reminder(query, context, user_id, lang)

    @staticmethod
    async def _render_translation_menu(query, context, lang):
        """عرض قائمة اللغات للترجمة"""
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
            [InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)],
        ])
        await safe_edit(query, "🌐 اختر اللغة:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _handle_language_change(update, context, query, user_id):
        """
        ✅ v7.5.12: تغيير اللغة + عرض القائمة الرئيسية بتعديل الرسالة.
        """
        data = query.data
        lang_set = data.split("_")[-1]
        valid_langs = {
            'ar', 'en', 'fr', 'tr', 'zh', 'ru', 'de', 'es',
            'it', 'pt', 'ja', 'ko', 'fa', 'ur', 'nl', 'pl', 'hi', 'off',
        }
        if lang_set in valid_langs:
            await DB.set_user_language(user_id, lang_set)
            await invalidate_user_cache(user_id)
            ok = await CallbackHandlers._show_main_menu_inline(
                query, context, user_id
            )
            if not ok:
                await CommandHandlers.start(update, context)
        else:
            await safe_edit(query, "❌ لغة غير مدعومة", bot=context.bot)

    # =================================================================
    # معالجات فرعية كبيرة
    # =================================================================

    @staticmethod
    async def _handle_buy_subscription(update, context, query, user_id, data):
        """شراء اشتراك"""
        try:
            days = int(data.split("_")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return

        plan_names = {1: "يوم", 7: "أسبوع", 30: "شهر", 90: "3 أشهر", 365: "سنة"}
        plan_name = plan_names.get(days)
        if not plan_name:
            await safe_edit(query, "❌ باقة غير موجودة", bot=context.bot)
            return

        plan = await DB.get_plan_by_name(plan_name)
        if not plan:
            await safe_edit(query, "❌ باقة غير موجودة", bot=context.bot)
            return

        invoice_number = await DB.create_invoice(user_id, plan['id'], plan['price'])
        if not invoice_number:
            await safe_edit(query, "❌ فشل الدفع", bot=context.bot)
            return

        try:
            await context.bot.send_invoice(
                chat_id=user_id,
                title=f"💎 {plan['name']}",
                description=plan['description'],
                payload=json.dumps({
                    'plan_id': plan['id'],
                    'invoice': invoice_number,
                    'type': 'subscription',
                }),
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(plan['name'], plan['price'])],
            )
            await safe_delete_message(query)
        except Exception as e:
            logger.error(f"❌ فشل إرسال الفاتورة: {e}")
            await DB.execute("UPDATE invoices SET status='cancelled' WHERE number=?", (invoice_number,))
            await safe_edit(query, f"❌ {str(e)[:50]}", bot=context.bot)

    @staticmethod
    async def _handle_buy_gift(update, context, query, user_id, data):
        """شراء هدية"""
        try:
            gift_plan_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return

        plan = await DB.get_gift_plan(gift_plan_id)
        if not plan:
            await safe_edit(query, "❌ خطة الهدية غير موجودة", bot=context.bot)
            return

        invoice_number = await DB.create_invoice(user_id, plan['id'], plan['price'])
        if not invoice_number:
            await safe_edit(query, "❌ فشل إنشاء الفاتورة", bot=context.bot)
            return

        try:
            await context.bot.send_invoice(
                chat_id=user_id,
                title=f"🎁 {plan['name']}",
                description=plan['description'] or "كود هدية",
                payload=json.dumps({
                    'gift_plan_id': plan['id'],
                    'invoice': invoice_number,
                    'type': 'gift',
                }),
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(plan['name'], plan['price'])],
            )
            await safe_delete_message(query)
        except Exception as e:
            logger.error(f"❌ فشل إرسال فاتورة الهدية: {e}")
            await DB.execute("UPDATE invoices SET status='cancelled' WHERE number=?", (invoice_number,))
            await safe_edit(query, f"❌ {str(e)[:50]}", bot=context.bot)

    @staticmethod
    async def _handle_group_delete(update, context, query, data):
        """حذف مجموعة"""
        try:
            chat_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        if await DB.delete_group(chat_id):
            await safe_edit(query, "✅ تم حذف المجموعة", bot=context.bot)
        else:
            await safe_edit(query, "❌ فشل", bot=context.bot)

    @staticmethod
    async def _handle_group_settings(update, context, query, user_id, lang, data):
        """فتح إعدادات مجموعة"""
        try:
            chat_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        context.user_data['security_chat_id'] = chat_id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
            return
        settings = await DB.get_security_settings(chat_id)
        await safe_edit(
            query,
            KeyboardFactory._format_security_text(settings),
            reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
            bot=context.bot,
        )

    @staticmethod
    async def _handle_channel_select(update, context, query, user_id, data):
        """تحديد قناة نشطة"""
        try:
            ch_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        if await DB.set_active_channel(user_id, ch_id):
            await safe_edit(query, "✅ تم تحديد القناة!", bot=context.bot)
            await invalidate_user_cache(user_id)
        else:
            await safe_edit(query, "❌ لا يمكنك تحديد هذه القناة", bot=context.bot)

    @staticmethod
    async def _handle_channel_delete(update, context, query, user_id, lang, data):
        """حذف قناة"""
        try:
            ch_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        if await DB.delete_channel(user_id, ch_id):
            context.user_data['channel_page'] = 0
            await CallbackHandlers._show_channel_list(update, context, query, user_id, lang)
            await invalidate_user_cache(user_id)
        else:
            await safe_edit(query, "❌ فشل", bot=context.bot)

    @staticmethod
    async def _handle_channel_stats(update, context, query, user_id, data):
        """إحصائيات قناة"""
        try:
            ch_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        stats = await DB.get_channel_stats(user_id, ch_id)
        text = (
            f"📊 إحصائيات\n\n"
            f"📝 {stats['total']}\n"
            f"✅ {stats['published']}\n"
            f"⏳ {stats['unpublished']}"
        )
        await safe_edit(
            query, text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 رجوع", callback_data=CB.CH_LIST)]]
            ),
            bot=context.bot,
        )

    @staticmethod
    async def _handle_post_add(update, context, query, user_id):
        """إضافة منشور"""
        if not await DB.has_active_subscription(user_id) and user_id != CONFIG.PRIMARY_OWNER_ID:
            await safe_edit(query, "❌ انتهى اشتراكك!", bot=context.bot)
            return
        active = await DB.get_active_channel(user_id)
        if not active:
            await safe_edit(query, "❌ لا توجد قناة نشطة", bot=context.bot)
            return
        StateManager.set(user_id, UserState.ADDING_POSTS)
        await safe_edit(
            query, "📥 أرسل المنشورات:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("✅ إنهاء", callback_data="finish_posts")]]
            ),
            bot=context.bot,
        )

    @staticmethod
    async def _handle_post_publish(update, context, query, user_id):
        """نشر منشور واحد"""
        active = await DB.get_active_channel(user_id)
        if not active:
            await safe_edit(query, "❌ لا توجد قناة", bot=context.bot)
            return
        raw_result = await DB.get_next_post(active)
        post, was_recycled = CallbackHandlers._unwrap_get_next_post(raw_result)
        if not post or not isinstance(post, dict):
            await safe_edit(query, "📭 لا توجد منشورات", bot=context.bot)
            return
        ch_info = await DB.get_channel_info(user_id, active)
        if ch_info:
            task = asyncio.create_task(
                CallbackHandlers._publish_single(
                    context.bot, active, ch_info['channel_id'], post
                )
            )
            ACTIVE_TASKS.add(task)
            task.add_done_callback(ACTIVE_TASKS.discard)
            msg = "✅ بدأ النشر" + (" (بعد إعادة تدوير)" if was_recycled else "")
            await safe_edit(query, msg, bot=context.bot)

    @staticmethod
    async def _handle_post_delete(update, context, query, user_id, lang, data):
        """حذف منشور"""
        try:
            post_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        active = await DB.get_active_channel(user_id)
        if active and await DB.delete_post(user_id, post_id, active):
            await CallbackHandlers._show_post_list(update, context, query, user_id, lang)
        else:
            await safe_edit(query, "❌ فشل", bot=context.bot)

    @staticmethod
    async def _handle_publish_all(update, context, query, user_id):
        """نشر جماعي"""
        channels = await DB.get_user_channels(user_id)
        if not channels:
            await safe_edit(query, "❌ لا توجد قنوات", bot=context.bot)
            return
        task = asyncio.create_task(
            CallbackHandlers._publish_all(context.bot, user_id, channels)
        )
        ACTIVE_TASKS.add(task)
        task.add_done_callback(ACTIVE_TASKS.discard)
        await safe_edit(query, "✅ بدأ النشر الجماعي", bot=context.bot)

    @staticmethod
    async def _show_groups_list(update, context, query, user_id, lang):
        """عرض قائمة المجموعات"""
        groups = await DB.get_user_groups(user_id)
        if not groups:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "➕ أضف البوت",
                    url=f"https://t.me/{CONFIG.BOT_USERNAME}?startgroup"
                )],
                [InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)],
            ])
            await safe_edit(query, "📭 لا توجد مجموعات", reply_markup=kb, bot=context.bot)
            return

        text = "👥 مجموعاتي\n\n"
        kb = []
        for g in groups:
            text += f"{'✅' if not g['banned'] else '⛔'} {g['chat_name']}\n"
            kb.append([InlineKeyboardButton(
                f"⚙️ أمان {g['chat_name'][:15]}",
                callback_data=f"{CB.GRP_SET}:{g['chat_id']}"
            )])
            kb.append([InlineKeyboardButton(
                "🗑️ حذف",
                callback_data=f"grp_del:{g['chat_id']}"
            )])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)])
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    # =================================================================
    # دوال النشر
    # =================================================================

    @staticmethod
    def _unwrap_get_next_post(result) -> Tuple[Optional[Dict], bool]:
        """
        ✅ v7.5.10: get_next_post تُرجع (dict, was_recycled) أو None أو dict.
        """
        if result is None:
            return None, False
        if isinstance(result, tuple) and len(result) == 2:
            post_dict, was_recycled = result
            if post_dict is None or isinstance(post_dict, dict):
                return post_dict, bool(was_recycled)
            return None, False
        if isinstance(result, dict):
            return result, False
        return None, False

    @staticmethod
    async def _publish_single(bot, ch_db_id, ch_tele, post) -> bool:
        """نشر منشور واحد"""
        if isinstance(post, tuple) and len(post) == 2:
            post, _ = CallbackHandlers._unwrap_get_next_post(post)
        if not isinstance(post, dict):
            logger.error(
                f"❌ _publish_single: post ليس dict (type={type(post).__name__}) — تخطي"
            )
            return False

        post_id = post.get('id')
        try:
            text = post.get('text', '')
            media_type = post.get('media_type')
            media_file_id = post.get('media_file_id')

            if not text and not media_type and not media_file_id:
                logger.warning(
                    f"⚠️ المنشور {post_id} فارغ تماماً "
                    f"(text='', media_type=None, media_file_id=None)"
                )
                return False

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
                        await bot.send_message(ch_tele, text[i:i + MAX_MESSAGE_LENGTH])
                else:
                    await bot.send_message(ch_tele, text if text else ".")

            if post_id:
                await DB.mark_post_published(post_id)
            await DB.update_last_publish(ch_db_id)
            await DB.update_next_publish(ch_db_id)
            return True
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            if post_id:
                await DB.increment_post_fail(post_id)
            return False
        except Forbidden:
            await DB.execute("UPDATE user_channels SET banned=1 WHERE id=?", (ch_db_id,))
            if post_id:
                await DB.increment_post_fail(post_id)
            return False
        except asyncio.CancelledError:
            logger.info("🛑 _publish_single تم إلغاؤه")
            raise
        except Exception as e:
            logger.error(f"❌ فشل النشر: {e}", exc_info=True)
            if post_id:
                await DB.increment_post_fail(post_id)
            return False

    @staticmethod
    async def _publish_all(bot, user_id, channels):
        """
        نشر جماعي لكل القنوات.
        ✅ v7.5.12: يستخدم _publish_semaphore المشترك
        ✅ v7.5.13: يستخدم PUBLISH_RATE_LIMITER المنفصل
        """
        published = 0
        failed = 0
        tasks = []
        banned_count = 0
        no_post_count = 0

        try:
            for ch in channels:
                if ch.get('banned'):
                    banned_count += 1
                    continue
                raw_result = await DB.get_next_post(ch['id'])
                post, _ = CallbackHandlers._unwrap_get_next_post(raw_result)
                if post and isinstance(post, dict):
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

            # ✅ v7.5.13: استخدام _publish_semaphore + PUBLISH_RATE_LIMITER
            async def run(task):
                async with _publish_semaphore:
                    await PUBLISH_RATE_LIMITER.acquire()
                    result = await CallbackHandlers._publish_single(
                        bot, task[0], task[1], task[2]
                    )
                    await asyncio.sleep(CallbackHandlers.PUBLISH_DELAY_SECONDS)
                    return result

            BATCH = CallbackHandlers.PUBLISH_BATCH_SIZE
            for i in range(0, len(tasks), BATCH):
                batch = tasks[i:i + BATCH]
                results = await asyncio.gather(
                    *(run(t) for t in batch), return_exceptions=True
                )
                for r in results:
                    if r is True:
                        published += 1
                    else:
                        failed += 1

            await safe_send(bot, user_id, f"✅ تم نشر {published} | ❌ فشل {failed}")
        except asyncio.CancelledError:
            logger.info("🛑 _publish_all تم إلغاؤه")
            raise
        except Exception as e:
            logger.error(f"❌ _publish_all: {e}", exc_info=True)
            await safe_send(bot, user_id, f"❌ فشل النشر الجماعي: {str(e)[:100]}")

    # =================================================================
    # عرض القوائم
    # =================================================================

    @staticmethod
    async def _show_channel_list(update, context, query, user_id, lang=None):
        """عرض قائمة القنوات"""
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        channels = await DB.get_user_channels(user_id)
        if not channels:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    KeyboardFactory.get_text("ch_add", lang),
                    callback_data=CB.CH_ADD
                )],
                [InlineKeyboardButton(
                    KeyboardFactory.get_text("back", lang),
                    callback_data=CB.BACK
                )],
            ])
            await safe_edit(query, "📭 لا توجد قنوات!", reply_markup=kb, bot=context.bot)
            return

        page = int(context.user_data.get('channel_page', 0))
        per_page = 5
        total_pages = max(1, (len(channels) + per_page - 1) // per_page)
        if page >= total_pages:
            page = total_pages - 1
        context.user_data['channel_page'] = page
        page_channels = channels[page * per_page:(page + 1) * per_page]

        text = f"📡 قنواتي (صفحة {page + 1}/{total_pages})\n\n"
        kb = []
        for ch in page_channels:
            st = "✅" if not ch['banned'] else "🚫"
            text += f"{st} {ch['channel_name']}\n"
            kb.append([
                InlineKeyboardButton(
                    f"📌 {ch['channel_name'][:20]}",
                    callback_data=f"{CB.CH_SEL}:{ch['id']}"
                ),
                InlineKeyboardButton("📅", callback_data=f"sched_open:{ch['id']}"),
            ])
            kb.append([
                InlineKeyboardButton("📊", callback_data=f"{CB.CH_STATS}:{ch['id']}"),
                InlineKeyboardButton("🗑️", callback_data=f"{CB.CH_DEL}:{ch['id']}"),
            ])

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="ch_page_prev"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("التالي ➡️", callback_data="ch_page_next"))
        if nav:
            kb.append(nav)

        kb.append([InlineKeyboardButton(
            KeyboardFactory.get_text("ch_add", lang),
            callback_data=CB.CH_ADD
        )])
        kb.append([InlineKeyboardButton(
            KeyboardFactory.get_text("back", lang),
            callback_data=CB.BACK
        )])
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    @staticmethod
    async def _show_post_list(update, context, query, user_id, lang=None):
        """عرض قائمة المنشورات"""
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        active = await DB.get_active_channel(user_id)
        if not active:
            await safe_edit(query, "❌ لا توجد قناة نشطة", bot=context.bot)
            return

        per_page = 5
        total = await DB.fetchval(
            "SELECT COUNT(*) FROM posts WHERE channel_db_id=?",
            (active,), default=0
        )
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = int(context.user_data.get('post_page', 0))
        if page >= total_pages:
            page = total_pages - 1
        context.user_data['post_page'] = page

        posts = await DB.fetchall(
            "SELECT id, text, published FROM posts WHERE channel_db_id=? "
            "ORDER BY created_at ASC LIMIT ? OFFSET ?",
            (active, per_page, page * per_page),
        )

        text = f"📋 منشوراتي (صفحة {page + 1}/{total_pages})\n\n"
        kb = []
        for p in posts:
            text += f"🆔 {p['id']}: {(p['text'] or '')[:30]}\n"
            kb.append([InlineKeyboardButton(
                f"🗑️ حذف {p['id']}",
                callback_data=f"{CB.POST_DEL}:{p['id']}"
            )])

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="post_page_prev"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("التالي ➡️", callback_data="post_page_next"))
        if nav:
            kb.append(nav)

        kb.append([InlineKeyboardButton("🔄 إعادة تدوير", callback_data=CB.POST_REC)])
        kb.append([InlineKeyboardButton("🧹 مسح الكل", callback_data=CB.POST_CLEAR)])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)])

        display_text = text if posts else "📭 لا يوجد منشورات"
        await safe_edit(
            query, display_text,
            reply_markup=InlineKeyboardMarkup(kb),
            bot=context.bot,
        )

    # =================================================================
    # معالجات الأمان
    # =================================================================

    @staticmethod
    async def _handle_security(update, context, query, user_id, lang=None, return_to_main=False):
        """معالج إعدادات الأمان"""
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        data = query.data
        parts = data.split(":")
        if len(parts) >= 2 and parts[1].lstrip('-').isdigit():
            chat_id = int(parts[1])
        else:
            chat_id = context.user_data.get('security_chat_id')
            if not chat_id and update.effective_chat:
                chat_id = update.effective_chat.id
        if chat_id is None:
            await safe_edit(query, "❌ لم يتم تحديد المجموعة", bot=context.bot)
            return
        action = parts[0].replace("sec_", "")

        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
            return

        try:
            if action in ("activate_all", "deactivate_all"):
                confirm_action = "activate_all_confirm" if action == "activate_all" else "deactivate_all_confirm"
                if action == "activate_all":
                    confirm_text = await _trans(
                        "activate_all_confirmation", lang,
                        "⚠️ هل أنت متأكد من تفعيل جميع الإعدادات الأمنية؟"
                    )
                else:
                    confirm_text = await _trans(
                        "deactivate_all_confirmation", lang,
                        "⚠️ هل أنت متأكد من تعطيل جميع الإعدادات الأمنية؟"
                    )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ نعم", callback_data=f"sec_{confirm_action}:{chat_id}"),
                     InlineKeyboardButton("❌ إلغاء", callback_data=f"grp_set:{chat_id}")],
                ])
                await safe_edit(query, confirm_text, reply_markup=kb, bot=context.bot)
                return

            if action in ("activate_all_confirm", "deactivate_all_confirm"):
                is_activate = (action == "activate_all_confirm")
                if is_activate:
                    await DB.update_security_settings(
                        chat_id,
                        delete_links=1, delete_mentions=1, slow_mode=1,
                        slow_mode_seconds=5,
                        delete_videos=1, delete_audio=1, delete_animation=1,
                        delete_service=1, delete_documents=1, delete_stickers=1,
                        delete_forwarded=1, delete_polls=1, delete_games=1,
                        delete_voice=1, delete_video_note=1,
                        welcome_enabled=1, goodbye_enabled=1,
                        antiflood_enabled=1, antiflood_messages=5, antiflood_seconds=5,
                        antiflood_penalty="mute", antiflood_penalty_duration=60,
                        night_mode_enabled=1, night_mode_start="22:00", night_mode_end="06:00",
                        night_mode_action="mute", night_mode_action_duration=3600,
                        auto_approve_join=0, auto_reject_join=0, nsfw_enabled=0,
                        warn_enabled=1, max_warnings=3,
                        warn_penalty="mute", warn_penalty_duration=3600,
                        delete_banned_words=1,
                        auto_penalty="mute",
                        delete_penalty="mute", delete_penalty_duration=3600,
                        violation_strikes=3, violation_duration=60,
                    )
                else:
                    await DB.update_security_settings(
                        chat_id,
                        delete_links=0, delete_mentions=0, slow_mode=0, slow_mode_seconds=0,
                        delete_videos=0, delete_audio=0, delete_animation=0,
                        delete_service=0, delete_documents=0, delete_stickers=0,
                        delete_forwarded=0, delete_polls=0, delete_games=0,
                        delete_voice=0, delete_video_note=0,
                        welcome_enabled=0, goodbye_enabled=0,
                        antiflood_enabled=0, antiflood_messages=0, antiflood_seconds=0,
                        antiflood_penalty="none", antiflood_penalty_duration=0,
                        night_mode_enabled=0, night_mode_start="", night_mode_end="",
                        night_mode_action="none", night_mode_action_duration=0,
                        auto_approve_join=0, auto_reject_join=0, nsfw_enabled=0,
                        warn_enabled=0, max_warnings=0,
                        warn_penalty="none", warn_penalty_duration=0,
                        delete_banned_words=0,
                        auto_penalty="none",
                        delete_penalty="none", delete_penalty_duration=0,
                        violation_strikes=0, violation_duration=0,
                    )
                try:
                    await DB.execute(
                        "INSERT INTO admin_logs (admin_id, action, chat_id, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (user_id,
                         f"{'activate' if is_activate else 'deactivate'}_all_security",
                         chat_id, TimeUtils.utc_now()),
                    )
                except Exception as e:
                    logger.warning(f"⚠️ فشل تسجيل admin_log: {e}")

                settings = await DB.get_security_settings(chat_id)
                await safe_edit(
                    query,
                    KeyboardFactory._format_security_text(settings),
                    reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                    bot=context.bot,
                )
                return

            toggle_map = {
                "links": "delete_links", "mentions": "mentions", "slow": "slow_mode",
                "video": "delete_videos", "audio": "delete_audio",
                "anim": "delete_animation", "service": "delete_service",
                "doc": "delete_documents", "sticker": "delete_stickers",
                "forward": "delete_forwarded", "poll": "delete_polls",
                "game": "delete_games", "voice": "delete_voice",
                "videonote": "delete_video_note", "welcome": "welcome_enabled",
                "goodbye": "goodbye_enabled", "flood": "antiflood_enabled",
                "night": "night_mode_enabled",
                "approve_join": "auto_approve_join",
                "reject_join": "auto_reject_join", "nsfw": "nsfw_enabled",
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
                await safe_edit(
                    query,
                    KeyboardFactory._format_security_text(settings),
                    reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                    bot=context.bot,
                )
                return

            if action == "warn":
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تفعيل/تعطيل", callback_data=f"sec_warn_toggle:{chat_id}")],
                    [InlineKeyboardButton("🔢 عدد التحذيرات", callback_data=f"sec_warn_count:{chat_id}")],
                    [InlineKeyboardButton("⚖️ عقوبة التحذير", callback_data=f"sec_warn_penalty:{chat_id}")],
                    [InlineKeyboardButton("⏱️ مدة العقوبة", callback_data=f"sec_warn_penalty_duration:{chat_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")],
                ])
                await safe_edit(query, "⚠️ إدارة التحذيرات:", reply_markup=kb, bot=context.bot)
                return

            if action == "warn_penalty":
                await CallbackHandlers._show_warn_penalty_types(update, context, query, chat_id, lang)
                return

            if action == "warn_toggle":
                settings = await DB.get_security_settings(chat_id)
                new_val = 1 - settings.get('warn_enabled', 0)
                await DB.update_security_settings(chat_id, warn_enabled=new_val)
                settings['warn_enabled'] = new_val
                await safe_edit(
                    query,
                    KeyboardFactory._format_security_text(settings),
                    reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                    bot=context.bot,
                )
                return

            if action == "warn_count":
                StateManager.set(user_id, UserState.WAIT_WARN_COUNT)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🔢 أرسل عدد التحذيرات:", bot=context.bot)
                return

            if action == "penalty":
                await CallbackHandlers._show_penalty_types(update, context, query, chat_id, lang)
                return

            if action == "del_pen":
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚫 حظر", callback_data=f"sec_set_del_penalty:ban:{chat_id}"),
                     InlineKeyboardButton("🔇 كتم", callback_data=f"sec_set_del_penalty:mute:{chat_id}")],
                    [InlineKeyboardButton("👢 طرد", callback_data=f"sec_set_del_penalty:kick:{chat_id}"),
                     InlineKeyboardButton("🔒 تقييد", callback_data=f"sec_set_del_penalty:restrict:{chat_id}")],
                    [InlineKeyboardButton("🚫 بدون عقوبة", callback_data=f"sec_set_del_penalty:none:{chat_id}")],
                    [InlineKeyboardButton("⏱️ مدة العقوبة", callback_data=f"sec_set_del_penalty_duration:{chat_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")],
                ])
                await safe_edit(query, "🚫 اختر عقوبة الحذف:", reply_markup=kb, bot=context.bot)
                return

            if action == "banned_words":
                await CallbackHandlers._show_banned_words_menu(update, context, query, chat_id, lang)
                return

            if action == "toggle_banned_words":
                settings = await DB.get_security_settings(chat_id)
                new_val = 1 - settings.get('delete_banned_words', 0)
                await DB.update_security_settings(chat_id, delete_banned_words=new_val)
                settings['delete_banned_words'] = new_val
                await CallbackHandlers._show_banned_words_menu(update, context, query, chat_id, lang)
                return

            if action == "close":
                await safe_delete_message(query)
                StateManager.clear(user_id)
                _clear_context_keys(context)
                return

            if action == "antiflood_settings":
                await CallbackHandlers._show_antiflood_settings(update, context, query, chat_id, lang)
                return

            if action == "night_settings":
                await CallbackHandlers._show_night_settings(update, context, query, chat_id, lang)
                return

            if action == "auto_reply_menu":
                await CallbackHandlers._show_auto_reply_menu(update, context, query, chat_id, lang)
                return

            if action == "adv_act":
                await CallbackHandlers._show_advanced_actions(update, context, query, chat_id, lang)
                return

            if action == "act_log":
                await CallbackHandlers._show_admin_logs(update, context, query, chat_id, lang)
                StateManager.clear(user_id)
                return

            if action == "maxlen":
                StateManager.set(user_id, UserState.WAIT_MAX_LEN)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "📏 أرسل الحد الأقصى لطول الرسالة:", bot=context.bot)
                return

            if action == "slow_mode_seconds":
                StateManager.set(user_id, UserState.WAIT_SLOW_MODE_SECONDS)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "⏱️ أرسل مدة الوضع البطيء بالثواني:", bot=context.bot)
                return

            if action == "welcome_text":
                StateManager.set(user_id, UserState.WAIT_WELCOME_TEXT)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "📝 أرسل نص الترحيب:", bot=context.bot)
                return

            if action == "goodbye_text":
                StateManager.set(user_id, UserState.WAIT_GOODBYE_TEXT)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "📝 أرسل نص الوداع:", bot=context.bot)
                return

            if action == "penalty_durations":
                await CallbackHandlers._show_all_penalty_durations_menu(query, context, chat_id)
                return

            if action == "set_antiflood_messages":
                StateManager.set(user_id, UserState.WAIT_ANTIFLOOD_MESSAGES)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "📊 أرسل عدد الرسائل المسموحة:", bot=context.bot)
                return

            if action == "set_antiflood_seconds":
                StateManager.set(user_id, UserState.WAIT_ANTIFLOOD_SECONDS)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "⏱️ أرسل عدد الثواني:", bot=context.bot)
                return

            if action == "antiflood_penalty":
                await CallbackHandlers._show_penalty_type_selection(
                    update, context, query, chat_id, lang, 'antiflood_penalty'
                )
                return

            if action == "set_night_start":
                StateManager.set(user_id, UserState.WAIT_NIGHT_START)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🌙 أرسل وقت البدء (HH:MM):", bot=context.bot)
                return

            if action == "set_night_end":
                StateManager.set(user_id, UserState.WAIT_NIGHT_END)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🌙 أرسل وقت النهاية (HH:MM):", bot=context.bot)
                return

            if action == "night_action":
                await CallbackHandlers._show_penalty_type_selection(
                    update, context, query, chat_id, lang, 'night_action'
                )
                return

            if action == "violation_settings":
                await CallbackHandlers._show_violation_penalties(
                    update, context, query, chat_id, lang
                )
                return

            if action == "violation_penalty":
                await CallbackHandlers._show_penalty_type_selection(
                    update, context, query, chat_id, lang, 'violation_penalty'
                )
                return

            logger.debug(f"⚠️ sec action غير معروف: {action}")
            return

        except Exception as e:
            logger.error(f"خطأ في إعدادات الأمان: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    # =================================================================
    # دوال عرض الأمان
    # =================================================================

    @staticmethod
    async def _show_warn_penalty_types(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 حظر", callback_data=f"set_warn_penalty:ban:{chat_id}"),
             InlineKeyboardButton("🔇 كتم", callback_data=f"set_warn_penalty:mute:{chat_id}")],
            [InlineKeyboardButton("👢 طرد", callback_data=f"set_warn_penalty:kick:{chat_id}"),
             InlineKeyboardButton("🔒 تقييد", callback_data=f"set_warn_penalty:restrict:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")],
        ])
        await safe_edit(query, "⚖️ اختر عقوبة تجاوز التحذيرات:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_banned_words_menu(update, context, query, chat_id, lang):
        settings = await DB.get_security_settings(chat_id)
        is_enabled = settings.get('delete_banned_words', 0)
        toggle_text = "❌ تعطيل الحذف" if is_enabled else "✅ تفعيل الحذف"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"ban_add:{chat_id}"),
             InlineKeyboardButton("📋 القائمة", callback_data=f"ban_list:{chat_id}")],
            [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=f"ban_rem:{chat_id}")],
            [InlineKeyboardButton(toggle_text, callback_data=f"sec_toggle_banned_words:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")],
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
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")])
        await safe_edit(
            query,
            f"🚫 اختر نوع العقوبة لـ {setting_key.replace('_', ' ')}:",
            reply_markup=InlineKeyboardMarkup(kb),
            bot=context.bot,
        )

    @staticmethod
    async def _show_all_penalty_durations_menu(query, context, chat_id):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏱️ مدة الكتم", callback_data=f"sec_set_mute_duration:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة الحظر", callback_data=f"sec_set_ban_duration:{chat_id}")],
            [InlineKeyboardButton("⏱️ مدة التقييد", callback_data=f"sec_set_restrict_duration:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة عقوبة التحذير", callback_data=f"sec_warn_penalty_duration:{chat_id}")],
            [InlineKeyboardButton("⏱️ مدة الفيضان", callback_data=f"sec_antiflood_duration:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة الليل", callback_data=f"sec_night_duration:{chat_id}")],
            [InlineKeyboardButton("⏱️ مدة عقوبة الحذف", callback_data=f"sec_set_del_penalty_duration:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")],
        ])
        await safe_edit(query, "⏱️ اختر نوع العقوبة لتعديل مدتها:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_penalty_durations(update, context, query, chat_id, lang, penalty_type='mute'):
        if penalty_type == 'kick':
            settings = await DB.get_security_settings(chat_id)
            await safe_edit(
                query,
                KeyboardFactory._format_security_text(settings),
                reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                bot=context.bot,
            )
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
            row.append(InlineKeyboardButton(
                name,
                callback_data=f"set_duration:{penalty_type}:{chat_id}:{secs}"
            ))
            if i + 1 < len(durations):
                name2, secs2 = durations[i + 1]
                row.append(InlineKeyboardButton(
                    name2,
                    callback_data=f"set_duration:{penalty_type}:{chat_id}:{secs2}"
                ))
            kb.append(row)
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")])

        type_name = {
            'mute': 'كتم', 'ban': 'حظر', 'restrict': 'تقييد',
            'antiflood': 'الفيضان', 'night': 'الوضع الليلي',
            'warn_penalty': 'عقوبة التحذير', 'delete_penalty': 'عقوبة الحذف',
            'violation': 'عقوبات المخالفات',
        }.get(penalty_type, penalty_type)

        await safe_edit(
            query,
            f"⏱️ اختر مدة {type_name}:",
            reply_markup=InlineKeyboardMarkup(kb),
            bot=context.bot,
        )

    @staticmethod
    async def _show_violation_penalties(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔢 عدد المخالفات", callback_data=f"sec_set_violation_strikes:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة العقوبة", callback_data=f"sec_set_violation_duration:{chat_id}")],
            [InlineKeyboardButton("⚖️ نوع العقوبة", callback_data=f"sec_violation_penalty:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")],
        ])
        await safe_edit(query, "🚨 إعدادات عقوبات المخالفات:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_antiflood_settings(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("عدد الرسائل", callback_data=f"sec_set_antiflood_messages:{chat_id}"),
             InlineKeyboardButton("الثواني", callback_data=f"sec_set_antiflood_seconds:{chat_id}")],
            [InlineKeyboardButton("نوع العقوبة", callback_data=f"sec_antiflood_penalty:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة العقوبة", callback_data=f"sec_antiflood_duration:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")],
        ])
        await safe_edit(query, "🌊 إعدادات الفيضان:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_night_settings(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("وقت البدء", callback_data=f"sec_set_night_start:{chat_id}"),
             InlineKeyboardButton("وقت النهاية", callback_data=f"sec_set_night_end:{chat_id}")],
            [InlineKeyboardButton("نوع الإجراء", callback_data=f"sec_night_action:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة الإجراء", callback_data=f"sec_night_duration:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")],
        ])
        await safe_edit(query, "🌙 إعدادات الوضع الليلي:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_auto_reply_menu(update, context, query, chat_id, lang):
        kb = KeyboardFactory.build("auto_reply", chat_id=chat_id, lang=lang)
        await safe_edit(query, "🤖 إعدادات الردود التلقائية:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_advanced_actions(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 تعطيل الكل", callback_data=f"sec_deactivate_all:{chat_id}"),
             InlineKeyboardButton("🟢 تفعيل الكل", callback_data=f"sec_activate_all:{chat_id}")],
            [InlineKeyboardButton("🚫 حظر", callback_data=f"act_ban:{chat_id}"),
             InlineKeyboardButton("🔇 كتم", callback_data=f"act_mute:{chat_id}")],
            [InlineKeyboardButton("👢 طرد", callback_data=f"act_kick:{chat_id}"),
             InlineKeyboardButton("🔒 تقييد", callback_data=f"act_restrict:{chat_id}")],
            [InlineKeyboardButton("🔓 فك الحظر", callback_data=f"act_unban:{chat_id}"),
             InlineKeyboardButton("⚠️ تحذير", callback_data=f"act_warn:{chat_id}")],
            [InlineKeyboardButton("📌 تثبيت", callback_data=f"act_pin:{chat_id}"),
             InlineKeyboardButton("📋 السجل", callback_data=f"act_log:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")],
        ])
        await safe_edit(query, "🛠️ الإجراءات المتقدمة:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_admin_logs(update, context, query, chat_id, lang):
        logs = await DB.get_admin_logs(chat_id, 10)
        text = "📋 سجل المشرفين\n\n" + "\n".join(
            f"• {l.get('admin_id')} → {l.get('action')}" for l in logs
        ) if logs else "📭 لا يوجد"
        await safe_edit(
            query, text,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")]]
            ),
            bot=context.bot,
        )

    @staticmethod
    async def _show_penalty_types(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("حظر", callback_data=f"sec_penalty_ban:{chat_id}"),
             InlineKeyboardButton("كتم", callback_data=f"sec_penalty_mute:{chat_id}")],
            [InlineKeyboardButton("طرد", callback_data=f"sec_penalty_kick:{chat_id}"),
             InlineKeyboardButton("تقييد", callback_data=f"sec_penalty_restrict:{chat_id}")],
            [InlineKeyboardButton("بدون عقوبة", callback_data=f"sec_penalty_none:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"grp_set:{chat_id}")],
        ])
        await safe_edit(query, "🚫 اختر نوع العقوبة:", reply_markup=kb, bot=context.bot)

    # =================================================================
    # معالجات الأدمن
    # =================================================================

    @staticmethod
    async def _handle_admin(update, context, query, user_id, lang=None):
        if not CONFIG.is_developer(user_id):
            await safe_edit(query, "❌ غير مصرح", bot=context.bot)
            return

        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'

        data = query.data

        try:
            if data == "admin_grant_free":
                StateManager.set(user_id, UserState.WAIT_GRANT_FREE)
                await safe_edit(query, "🎁 أرسل: معرف_المستخدم عدد_الأيام", bot=context.bot)
                return

            if data == CB.ADMIN_USERS:
                stats = await DB.get_user_stats()
                text = (
                    f"👥 المستخدمون\n\n"
                    f"👥 الإجمالي: {stats['users']}\n"
                    f"⛔ المحظورون: {stats['banned']}"
                )
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⛔ المحظورين", callback_data=CB.ADMIN_BANNED)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_BANNED:
                banned_users = await DB.fetchall(
                    "SELECT user_id FROM users WHERE banned=1 LIMIT 20"
                )
                text = (
                    "⛔ المحظورين\n\n"
                    + "\n".join(str(u['user_id']) for u in banned_users)
                ) if banned_users else "📭 لا يوجد محظورون"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ فك حظر الكل", callback_data=CB.ADMIN_UNBAN_ALL)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_UNBAN_ALL:
                await DB.execute("UPDATE users SET banned=0 WHERE banned=1")
                await safe_edit(query, "✅ تم إلغاء حظر الجميع", bot=context.bot)
                return

            if data == CB.ADMIN_STATS:
                stats = await DB.get_general_stats()
                text = (
                    f"📊 إحصائيات عامة\n\n"
                    f"👥 المستخدمون: {stats['users']}\n"
                    f"📡 القنوات: {stats['channels']}\n"
                    f"👥 المجموعات: {stats['groups']}\n"
                    f"📝 المنشورات: {stats['posts']}\n"
                    f"✅ المنشورة: {stats['published']}\n"
                    f"🧾 الفواتير: {stats['invoices']}\n"
                    f"🎫 التذاكر المعلقة: {stats['tickets']}"
                )
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)]]
                )
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_CHANNELS:
                await CallbackHandlers._show_admin_channels(update, context, query, user_id, lang)
                return

            if data.startswith("admin_toggle_ch:"):
                try:
                    ch_db_id = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return
                row = await DB.fetchone(
                    "SELECT banned FROM user_channels WHERE id=?", (ch_db_id,)
                )
                if row:
                    new_val = 0 if row['banned'] else 1
                    await DB.execute(
                        "UPDATE user_channels SET banned=? WHERE id=?",
                        (new_val, ch_db_id)
                    )
                    await CallbackHandlers._show_admin_channels(update, context, query, user_id, lang)
                return

            if data == CB.ADMIN_GROUPS:
                await CallbackHandlers._show_admin_groups(update, context, query, user_id, lang)
                return

            if data.startswith("admin_toggle_gr:"):
                try:
                    chat_id = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return
                row = await DB.fetchone(
                    "SELECT banned FROM bot_groups WHERE chat_id=?", (chat_id,)
                )
                if row:
                    new_val = 0 if row['banned'] else 1
                    if new_val == 1:
                        try:
                            await context.bot.leave_chat(chat_id)
                        except Exception:
                            pass
                    await DB.execute(
                        "UPDATE bot_groups SET banned=? WHERE chat_id=?",
                        (new_val, chat_id)
                    )
                    await CallbackHandlers._show_admin_groups(update, context, query, user_id, lang)
                return

            if data == CB.ADMIN_ADD_ADMIN:
                StateManager.set(user_id, UserState.WAIT_ADMIN_ADD)
                await safe_edit(query, "👑 أرسل معرف المشرف:", bot=context.bot)
                return

            if data == CB.ADMIN_REM_ADMIN:
                StateManager.set(user_id, UserState.WAIT_ADMIN_REM)
                await safe_edit(query, "🗑️ أرسل معرف المشرف:", bot=context.bot)
                return

            if data == CB.ADMIN_LIST_ADMINS:
                admins = await DB.get_admin_list()
                text = "👑 المشرفون\n\n" + "\n".join(
                    f"• {a['user_id']}" for a in admins
                ) if admins else "📭 لا يوجد"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إضافة", callback_data=CB.ADMIN_ADD_ADMIN),
                     InlineKeyboardButton("🗑️ إزالة", callback_data=CB.ADMIN_REM_ADMIN)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_BROADCAST:
                StateManager.set(user_id, UserState.WAIT_BROADCAST)
                await safe_edit(query, "📨 أرسل الرسالة:", bot=context.bot)
                return

            if data == CB.ADMIN_INVOICES:
                invoices = await DB.fetchall(
                    "SELECT number, amount, status FROM invoices ORDER BY id DESC LIMIT 20"
                )
                text = "🧾 الفواتير\n\n" + "\n".join(
                    f"• {i['number']} - {i['amount']} ⭐ - {i['status']}"
                    for i in invoices
                ) if invoices else "📭 لا توجد"
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)]]
                )
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_BACKUP:
                task = asyncio.create_task(CallbackHandlers._do_backup(context, user_id))
                ACTIVE_TASKS.add(task)
                task.add_done_callback(ACTIVE_TASKS.discard)
                return

            if data in (CB.ADMIN_RESTORE, CB.ADMIN_RESTORE_SEL):
                await CallbackHandlers._show_restore_backups(update, context, query, user_id)
                return

            if data.startswith("admin_restore_file:"):
                fname = data.split(":", 1)[1]
                backup_file = PATHS.BACKUPS / fname
                if backup_file.resolve().parent != PATHS.BACKUPS.resolve():
                    await safe_edit(query, "❌ مسار غير صالح", bot=context.bot)
                    return
                if not backup_file.exists():
                    await safe_edit(query, "❌ الملف غير موجود", bot=context.bot)
                    return
                try:
                    pre_restore_backup = (
                        PATHS.BACKUPS
                        / f"pre_restore_{TimeUtils.mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
                    )
                    shutil.copy2(PATHS.DB, pre_restore_backup)
                    shutil.copy2(backup_file, PATHS.DB)
                    await safe_edit(
                        query,
                        "✅ تمت الاستعادة بنجاح! أعد تشغيل البوت لتفعيل التغييرات.",
                        bot=context.bot,
                    )
                except Exception as e:
                    await safe_edit(
                        query, f"❌ فشل الاستعادة: {str(e)[:100]}", bot=context.bot
                    )
                return

            if data == CB.ADMIN_RAM:
                ram = get_ram_usage()
                text = (
                    f"🖥️ الرام\n\n"
                    f"💾 الإجمالي: {ram['total']} GB\n"
                    f"📊 المستخدم: {ram['used']} GB\n"
                    f"📈 النسبة: {ram['percent']}%"
                )
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_METRICS:
                stats = await DB.get_general_stats()
                try:
                    db_size = PATHS.DB.stat().st_size / 1024
                except Exception:
                    db_size = 0
                text = (
                    f"📊 مقاييس النظام\n\n"
                    f"👥 المستخدمون: {stats['users']}\n"
                    f"📡 القنوات: {stats['channels']}\n"
                    f"👥 المجموعات: {stats['groups']}\n"
                    f"📝 المنشورات: {stats['posts']}\n"
                    f"✅ المنشورة: {stats['published']}\n"
                    f"🧾 الفواتير: {stats['invoices']}\n"
                    f"🎫 تذاكر معلقة: {stats['tickets']}\n"
                    f"💾 حجم قاعدة البيانات: {db_size:.1f} KB"
                )
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_UPTIME:
                uptime = time.monotonic() - context.bot_data.get(
                    'start_time', time.monotonic()
                )
                hours, remainder = divmod(uptime, 3600)
                minutes, seconds = divmod(remainder, 60)
                text = (
                    f"⏳ فترة التشغيل: {int(hours)} ساعة "
                    f"{int(minutes)} دقيقة {int(seconds)} ثانية"
                )
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_TICKETS:
                tickets = await DB.get_tickets()
                text = "🎫 التذاكر المعلقة\n\n" + "\n".join(
                    f"• #{t['ticket_number']} - {t['user_id']}: {t['message'][:50]}"
                    for t in tickets[:10]
                ) if tickets else "📭 لا توجد تذاكر"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑️ حذف الكل", callback_data=CB.ADMIN_DEL_TICKETS)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_DEL_TICKETS:
                await DB.delete_all_tickets()
                await safe_edit(query, "✅ تم حذف جميع التذاكر", bot=context.bot)
                return

            if data == CB.ADMIN_PAYMENT_LOGS:
                logs = await DB.fetchall(
                    "SELECT user_id, event_type, created_at FROM payment_logs "
                    "ORDER BY id DESC LIMIT 20"
                )
                text = "💳 سجلات الدفع\n\n" + "\n".join(
                    f"• {l['user_id']} - {l['event_type']} ({l['created_at']})"
                    for l in logs
                ) if logs else "📭 لا توجد"
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_SET_UPDATE_CH:
                StateManager.set(user_id, UserState.WAIT_UPDATE_CH)
                await safe_edit(query, "📢 أرسل معرف قناة التحديثات:", bot=context.bot)
                return

            if data == CB.ADMIN_SEND_UPDATE:
                StateManager.set(user_id, UserState.WAIT_UPDATE)
                await safe_edit(query, "📝 أرسل نص التحديث:", bot=context.bot)
                return

            if data == CB.ADMIN_SHOW_UPDATE:
                ch = await DB.get_updates_channel()
                text = f"📢 قناة التحديثات: {ch}" if ch else "📭 لم يتم تعيين قناة تحديثات"
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_SET_LOG_CH:
                StateManager.set(user_id, UserState.WAIT_LOG_CH)
                await safe_edit(query, "📋 أرسل معرف قناة السجلات:", bot=context.bot)
                return

            if data == CB.ADMIN_LOG_CH:
                ch = await DB.get_log_channel()
                text = f"📋 قناة السجلات: {ch}" if ch else "📭 لم يتم تعيين قناة سجلات"
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_FORCE_SUB:
                sub = await DB.get_force_subscribe_channel()
                text = f"🔒 الاشتراك الإجباري: {'✅ مفعل' if sub else '❌ معطل'}\n"
                if sub:
                    text += f"القناة: {sub}"
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_SET_FORCE:
                StateManager.set(user_id, UserState.WAIT_FORCE)
                await safe_edit(query, "🔒 أرسل معرف قناة الاشتراك الإجباري:", bot=context.bot)
                return

            if data == "admin_disable_force":
                await DB.execute(
                    "UPDATE settings SET value = '' WHERE key = 'force_subscribe_channel'"
                )
                try:
                    _invalidate_force_sub_cache()
                except Exception as e:
                    logger.debug(f"فشل إبطال كاش الاشتراك الإجباري: {e}")
                await safe_edit(query, "✅ تم تعطيل الاشتراك الإجباري", bot=context.bot)
                return

            if data == "admin_upload_backup":
                StateManager.set(user_id, UserState.WAIT_BACKUP_FILE)
                await safe_edit(query, "📤 أرسل ملف النسخ الاحتياطي بصيغة .db:", bot=context.bot)
                return

            if data == CB.ADMIN_REFRESH_CACHE:
                await invalidate_user_cache(user_id)
                await safe_edit(query, "🔄 تم تحديث الكاش", bot=context.bot)
                return

            if data == CB.ADMIN_BANNED_CH:
                banned_channels = await DB.fetchall(
                    "SELECT channel_id, channel_name FROM user_channels "
                    "WHERE banned=1 LIMIT 20"
                )
                text = "🚫 القنوات المحظورة\n\n" + "\n".join(
                    f"• {c['channel_name']} ({c['channel_id']})"
                    for c in banned_channels
                ) if banned_channels else "📭 لا توجد"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تفعيل الكل", callback_data=CB.ADMIN_ACTIVATE_CH)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_ACTIVATE_CH:
                await DB.execute("UPDATE user_channels SET banned=0 WHERE banned=1")
                await safe_edit(query, "✅ تم تفعيل جميع القنوات", bot=context.bot)
                return

            if data == CB.ADMIN_BANNED_GR:
                banned_groups = await DB.fetchall(
                    "SELECT chat_id, chat_name FROM bot_groups WHERE banned=1 LIMIT 20"
                )
                text = "🚫 المجموعات المحظورة\n\n" + "\n".join(
                    f"• {g['chat_name']} ({g['chat_id']})" for g in banned_groups
                ) if banned_groups else "📭 لا توجد"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CB.ADMIN_UNBAN_GR)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_UNBAN_GR:
                await DB.execute("UPDATE bot_groups SET banned=0 WHERE banned=1")
                await safe_edit(query, "✅ تم إلغاء حظر جميع المجموعات", bot=context.bot)
                return

            if data == CB.ADMIN_REPLIES:
                replies = await DB.fetchall(
                    "SELECT keyword FROM auto_replies WHERE chat_id=-1 LIMIT 30"
                )
                text = "💬 الردود العامة\n\n" + "\n".join(
                    f"• {r['keyword']}" for r in replies
                ) if replies else "📭 لا توجد"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إضافة", callback_data="admin_add_reply"),
                     InlineKeyboardButton("🗑️ حذف", callback_data="admin_del_reply")],
                    [InlineKeyboardButton("📤 تصدير", callback_data=CB.ADMIN_EXPORT_REPLIES),
                     InlineKeyboardButton("📥 استيراد", callback_data=CB.ADMIN_IMPORT_REPLIES)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == "admin_add_reply":
                StateManager.set(user_id, UserState.WAIT_KEYWORD)
                context.user_data['auto_chat'] = -1
                await safe_edit(query, "📝 أرسل الكلمة:", bot=context.bot)
                return

            if data == "admin_del_reply":
                StateManager.set(user_id, UserState.WAIT_AUTO_DEL)
                context.user_data['auto_chat'] = -1
                await safe_edit(query, "🗑️ أرسل الكلمة:", bot=context.bot)
                return

            if data == "admin_list_replies":
                replies = await DB.fetchall(
                    "SELECT keyword FROM auto_replies WHERE chat_id=-1 LIMIT 50"
                )
                text = "📋 قائمة الردود العامة\n\n" + "\n".join(
                    f"• {r['keyword']}" for r in replies
                ) if replies else "📭 لا توجد"
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_EXPORT_REPLIES:
                try:
                    file_path = await DB.export_auto_replies_to_file()
                except AttributeError:
                    file_path = None
                if file_path:
                    try:
                        with open(file_path, 'rb') as f:
                            await context.bot.send_document(
                                chat_id=user_id, document=f,
                                filename=Path(file_path).name
                            )
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

            if data == CB.ADMIN_IMPORT_REPLIES:
                StateManager.set(user_id, UserState.WAIT_IMPORT_FILE)
                await safe_edit(query, "📤 أرسل ملف JSON:", bot=context.bot)
                return

            if data == CB.ADMIN_IMPORT_GITHUB:
                StateManager.set(user_id, UserState.WAIT_GITHUB_URL)
                await safe_edit(query, "📥 أرسل الرابط:", bot=context.bot)
                return

            if data == CB.ADMIN_BANNED_WORDS:
                words = await DB.get_banned_words(-1)
                text = "🚫 الكلمات المحظورة العامة\n\n" + "\n".join(
                    f"• {w}" for w in words[:30]
                ) if words else "📭 لا توجد"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إضافة", callback_data="admin_add_banned"),
                     InlineKeyboardButton("🗑️ حذف", callback_data="admin_rem_banned")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == "admin_add_banned":
                StateManager.set(user_id, UserState.WAIT_GLOBAL_BAN)
                await safe_edit(query, "📝 أرسل الكلمة:", bot=context.bot)
                return

            if data == "admin_rem_banned":
                StateManager.set(user_id, UserState.WAIT_REM_GLOBAL_BAN)
                await safe_edit(query, "🗑️ أرسل الكلمة:", bot=context.bot)
                return

            if data == "admin_list_banned":
                words = await DB.get_banned_words(-1)
                text = "📋 قائمة الكلمات المحظورة العامة\n\n" + "\n".join(
                    f"• {w}" for w in words
                ) if words else "📭 لا توجد"
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_CREATE_CONTEST:
                StateManager.set(user_id, UserState.WAIT_CONTEST_TITLE)
                await safe_edit(query, "🏆 أرسل العنوان:", bot=context.bot)
                return

            if data == CB.ADMIN_DECLARE_WINNER:
                contests = await DB.get_active_contests(5)
                if not contests:
                    await safe_edit(query, "📭 لا توجد مسابقات نشطة", bot=context.bot)
                    return
                kb = []
                for c in contests:
                    kb.append([InlineKeyboardButton(
                        f"🏆 {c['title'][:20]}",
                        callback_data=f"{CB.DECLARE_WINNER_SEL}:{c['id']}"
                    )])
                kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
                await safe_edit(
                    query, "🏆 اختر المسابقة:",
                    reply_markup=InlineKeyboardMarkup(kb), bot=context.bot
                )
                return

            if data == CB.ADMIN_DEL_CONTEST:
                contests = await DB.fetchall(
                    "SELECT id, title FROM contests WHERE status='active' LIMIT 10"
                )
                if not contests:
                    await safe_edit(query, "📭 لا توجد مسابقات", bot=context.bot)
                    return
                kb = []
                for c in contests:
                    kb.append([InlineKeyboardButton(
                        f"🗑️ {c['title'][:20]}",
                        callback_data=f"admin_delete_contest:{c['id']}"
                    )])
                kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
                await safe_edit(
                    query, "🗑️ اختر المسابقة للحذف:",
                    reply_markup=InlineKeyboardMarkup(kb), bot=context.bot
                )
                return

            if data.startswith("admin_delete_contest:"):
                try:
                    contest_id = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return
                if await DB.delete_contest(contest_id, user_id):
                    await safe_edit(query, "✅ تم حذف المسابقة", bot=context.bot)
                else:
                    await safe_edit(query, "❌ فشل", bot=context.bot)
                return

            await safe_edit(query, "⚠️ غير متوفر", bot=context.bot)

        except BadRequest as e:
            if "query is too old" not in str(e).lower():
                logger.error(f"خطأ في لوحة الأدمن: {e}", exc_info=True)
                await safe_edit(query, "❌ حدث خطأ", bot=context.bot)
        except Exception as e:
            logger.error(f"خطأ في لوحة الأدمن: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    @staticmethod
    async def _show_restore_backups(update, context, query, user_id):
        backups = sorted(
            PATHS.BACKUPS.glob("backup_*.db"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not backups:
            await safe_edit(query, "📭 لا توجد نسخ احتياطية", bot=context.bot)
            return
        kb = []
        for b in backups[:10]:
            fname = b.name
            kb.append([InlineKeyboardButton(
                f"📁 {fname}",
                callback_data=f"admin_restore_file:{fname}"
            )])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
        await safe_edit(
            query, "📂 اختر نسخة احتياطية للاستعادة:",
            reply_markup=InlineKeyboardMarkup(kb), bot=context.bot
        )

    @staticmethod
    async def _show_admin_channels(update, context, query, user_id, lang):
        channels = await DB.fetchall(
            "SELECT id, channel_id, channel_name, banned FROM user_channels "
            "ORDER BY channel_name LIMIT 50"
        )
        kb = []
        for c in channels:
            action = "🔓 فك حظر" if c['banned'] else "🔒 حظر"
            icon = "🚫" if c['banned'] else "✅"
            kb.append([InlineKeyboardButton(
                f"{icon} {c['channel_name'][:20]} - {action}",
                callback_data=f"admin_toggle_ch:{c['id']}"
            )])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
        text = (
            f"📡 إدارة القنوات ({len(channels)})\n\n"
            "اضغط على القناة للتبديل بين الحظر وفك الحظر:"
        )
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    @staticmethod
    async def _show_admin_groups(update, context, query, user_id, lang):
        groups = await DB.fetchall(
            "SELECT chat_id, chat_name, banned FROM bot_groups "
            "ORDER BY chat_name LIMIT 50"
        )
        kb = []
        for g in groups:
            action = "🔓 فك حظر" if g['banned'] else "🔒 حظر"
            icon = "🚫" if g['banned'] else "✅"
            kb.append([InlineKeyboardButton(
                f"{icon} {g['chat_name'][:20]} - {action}",
                callback_data=f"admin_toggle_gr:{g['chat_id']}"
            )])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
        text = (
            f"👥 إدارة المجموعات ({len(groups)})\n\n"
            "اضغط على المجموعة للتبديل بين الحظر وفك الحظر:"
        )
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    # =================================================================
    # معالجات الردود التلقائية
    # =================================================================

    @staticmethod
    async def _handle_auto_reply(update, context, query, user_id, lang=None):
        """معالج الردود التلقائية"""
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        data = query.data
        parts = data.split(":")
        action = parts[0].replace("auto_reply_", "")

        if len(parts) >= 2 and parts[1].lstrip('-').isdigit():
            chat_id = int(parts[1])
        else:
            chat_id = (
                context.user_data.get('auto_chat')
                or context.user_data.get('security_chat_id')
            )
            if not chat_id and update.effective_chat:
                chat_id = update.effective_chat.id

        if chat_id is None:
            await safe_edit(query, "❌ لم يتم تحديد المجموعة", bot=context.bot)
            return

        if chat_id != -1 and not await is_authorized_in_group(context.bot, chat_id, user_id):
            await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
            return

        try:
            if action == "menu":
                kb = KeyboardFactory.build("auto_reply", chat_id=chat_id, lang=lang)
                await safe_edit(query, "🤖 إعدادات الردود التلقائية:",
                                reply_markup=kb, bot=context.bot)
                return

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

            if action == "admins":
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

            if action == "add":
                StateManager.set(user_id, UserState.WAIT_AUTO_KEY)
                context.user_data['auto_chat'] = chat_id
                await safe_edit(query, "📝 أرسل الكلمة:", bot=context.bot)
                return

            if action == "del":
                StateManager.set(user_id, UserState.WAIT_AUTO_DEL)
                context.user_data['auto_chat'] = chat_id
                await safe_edit(query, "🗑️ أرسل الكلمة:", bot=context.bot)
                return

            if action == "reset":
                await DB.reset_auto_replies(chat_id)
                await safe_edit(query, "✅ تم الحذف", bot=context.bot)
                return

            if action == "list":
                rows = await DB.fetchall(
                    "SELECT keyword FROM auto_replies WHERE chat_id=? LIMIT 20",
                    (chat_id,)
                )
                text = "📋 الردود\n\n" + "\n".join(
                    f"• {r['keyword']}" for r in rows
                ) if rows else "📭 لا يوجد"
                await safe_edit(
                    query, text,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔙 رجوع",
                          callback_data=f"auto_reply_menu:{chat_id}")]]
                    ),
                    bot=context.bot,
                )
                return

            if action == "stats":
                stats = await DB.get_auto_reply_stats(chat_id, 20)
                if stats:
                    text = "📊 إحصائيات الردود\n\n"
                    for s in stats:
                        source = "🌐 عام" if s['source'] == 'global' else "👥 مجموعة"
                        text += f"• {s['keyword']} ({source}): {s['usage_count']} استخدام\n"
                else:
                    text = "📭 لا توجد ردود"
                await safe_edit(
                    query, text,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔙 رجوع",
                          callback_data=f"auto_reply_menu:{chat_id}")]]
                    ),
                    bot=context.bot,
                )
                return

            await safe_edit(query, "⚠️ غير معروف", bot=context.bot)

        except Exception as e:
            logger.error(f"خطأ في الردود التلقائية: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    # =================================================================
    # معالجات الجدولة
    # =================================================================

    @staticmethod
    async def _handle_schedule(update, context, query, user_id):
        data = query.data
        parts = data.split(":")
        if len(parts) < 2:
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        action = parts[0].replace("sched_", "")
        try:
            ch_id = int(parts[1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return

        if not await _is_channel_owner(user_id, ch_id):
            await safe_edit(query, "❌ لا تملك هذه القناة", bot=context.bot)
            return

        try:
            if action == "open":
                await CallbackHandlers._show_schedule_menu(update, context, query, ch_id, user_id)
                return
            if action == "min":
                StateManager.set(user_id, UserState.WAIT_MIN)
                context.user_data['schedule_ch'] = ch_id
                await safe_edit(query, "📅 أرسل الدقائق:", bot=context.bot)
                return
            if action == "hour":
                StateManager.set(user_id, UserState.WAIT_HOUR)
                context.user_data['schedule_ch'] = ch_id
                await safe_edit(query, "📅 أرسل الساعات:", bot=context.bot)
                return
            if action == "day":
                StateManager.set(user_id, UserState.WAIT_DAY)
                context.user_data['schedule_ch'] = ch_id
                await safe_edit(query, "📅 أرسل الأيام:", bot=context.bot)
                return
            if action == "time":
                StateManager.set(user_id, UserState.WAIT_PUB_TIME)
                context.user_data['schedule_ch'] = ch_id
                await safe_edit(query, "🕐 أرسل الوقت HH:MM:", bot=context.bot)
                return

            await safe_edit(query, "⚠️ غير معروف", bot=context.bot)
        except Exception as e:
            logger.error(f"خطأ في الجدولة: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    @staticmethod
    async def _show_schedule_menu(update, context, query, ch_id, user_id):
        lang = await DB.get_user_language(user_id) or 'ar'
        kb = KeyboardFactory.build("channel_settings", chat_id=ch_id, lang=lang)
        await safe_edit(query, "📅 جدولة القناة", reply_markup=kb, bot=context.bot)

    # =================================================================
    # ✅ v7.5.10: معالج الإجراءات المتقدمة (مع returns صحيحة)
    # =================================================================

    @staticmethod
    async def _handle_advanced_actions(update, context, query, user_id):
        """
        ✅ v7.5.10: معالج الإجراءات المتقدمة والعقوبات.
        """
        data = query.data
        parts = data.split(":")
        if len(parts) < 2:
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return

        prefix = parts[0]
        action = prefix.replace("act_", "").replace("pen_", "").replace("ban_", "")

        try:
            chat_id = int(parts[1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return

        if chat_id == -1 and (prefix.startswith("act_") or prefix.startswith("pen_")):
            await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
            return

        if chat_id != -1:
            if not await is_authorized_in_group(context.bot, chat_id, user_id):
                await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                return
        else:
            if not CONFIG.is_developer(user_id):
                await safe_edit(query, "❌ غير مصرح", bot=context.bot)
                return

        try:
            if prefix.startswith("ban_"):
                if action == "add":
                    state = (
                        UserState.WAIT_GROUP_BAN if chat_id != -1
                        else UserState.WAIT_GLOBAL_BAN
                    )
                    StateManager.set(user_id, state)
                    context.user_data['ban_chat'] = chat_id
                    await safe_edit(query, "📝 أرسل الكلمة:", bot=context.bot)
                    return

                if action == "list":
                    words = await DB.get_banned_words(chat_id)
                    text = "🚫 الكلمات\n\n" + "\n".join(
                        f"• {w}" for w in words[:50]
                    ) if words else "📭 لا يوجد"
                    await safe_edit(query, text, bot=context.bot)
                    return

                if action == "rem":
                    state = (
                        UserState.WAIT_REM_GROUP_BAN if chat_id != -1
                        else UserState.WAIT_REM_GLOBAL_BAN
                    )
                    StateManager.set(user_id, state)
                    context.user_data['ban_chat'] = chat_id
                    await safe_edit(query, "🗑️ أرسل الكلمة:", bot=context.bot)
                    return

                await safe_edit(query, "⚠️ غير معروف", bot=context.bot)
                return

            if prefix.startswith("act_"):
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

                if action == "pin":
                    StateManager.set(user_id, UserState.WAIT_PIN)
                    context.user_data['adv_chat'] = chat_id
                    await safe_edit(
                        query,
                        "📌 قم بالرد على الرسالة المطلوب تثبيتها ثم أرسل أي شيء:",
                        bot=context.bot,
                    )
                    return

                if action == "log":
                    await CallbackHandlers._show_admin_logs(
                        update, context, query, chat_id, lang='ar'
                    )
                    StateManager.clear(user_id)
                    return

                await safe_edit(query, "⚠️ غير معروف", bot=context.bot)
                return

            if prefix.startswith("pen_"):
                penalty_types = {'ban', 'mute', 'kick', 'restrict', 'none'}
                if action in penalty_types:
                    await DB.update_security_settings(chat_id, auto_penalty=action)
                    settings = await DB.get_security_settings(chat_id)
                    await safe_edit(
                        query,
                        KeyboardFactory._format_security_text(settings),
                        reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang='ar'),
                        bot=context.bot,
                    )
                    return
                await safe_edit(query, "⚠️ غير معروف", bot=context.bot)
                return

            await safe_edit(query, "⚠️ غير معروف", bot=context.bot)

        except Exception as e:
            logger.error(f"خطأ في الإجراءات المتقدمة: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    # =================================================================
    # معالجات اللوحة الخاصة (panel)
    # =================================================================

    @staticmethod
    async def _handle_panel(update, context, query, user_id, data):
        """✅ v7.5.2: حماية effective_chat من None"""
        if not update.effective_chat:
            await safe_edit(query, "❌ لا يمكن تحديد المجموعة", bot=context.bot)
            return
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
            return

        try:
            if data == "panel_lock":
                await context.bot.set_chat_permissions(
                    chat_id,
                    permissions=ChatPermissions(
                        can_send_messages=False,
                        can_send_audios=False,
                        can_send_documents=False,
                        can_send_photos=False,
                        can_send_videos=False,
                        can_send_video_notes=False,
                        can_send_voice_notes=False,
                        can_send_polls=False,
                        can_send_other_messages=False,
                        can_add_web_page_previews=False,
                        can_change_info=False,
                        can_invite_users=False,
                        can_pin_messages=False,
                    ),
                )
                await safe_edit(query, "🔒 تم قفل المجموعة", bot=context.bot)
                return

            if data == "panel_unlock":
                await context.bot.set_chat_permissions(
                    chat_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_audios=True,
                        can_send_documents=True,
                        can_send_photos=True,
                        can_send_videos=True,
                        can_send_video_notes=True,
                        can_send_voice_notes=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                        can_change_info=True,
                        can_invite_users=True,
                        can_pin_messages=True,
                    ),
                )
                await safe_edit(query, "🔓 تم فتح المجموعة", bot=context.bot)
                return

            if data == "panel_close":
                StateManager.clear(user_id)
                _clear_context_keys(context)
                await safe_delete_message(query)
                return

            await safe_edit(query, "⚠️ غير معروف", bot=context.bot)

        except Exception as e:
            logger.error(f"خطأ في اللوحة: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    # =================================================================
    # معالجات المسابقات (مع returns صحيحة)
    # =================================================================

    @staticmethod
    async def _handle_contests(update, context, query, user_id):
        """✅ v7.5.10: معالجات المسابقات مع returns صحيحة"""
        data = query.data
        try:
            if data.startswith(CB.CONTEST_JOIN + ":"):
                try:
                    cid = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return
                contest = await DB.get_contest_by_id(cid)
                if not contest or contest['status'] != 'active':
                    await safe_edit(query, "❌ المسابقة غير متاحة", bot=context.bot)
                    StateManager.clear(user_id)
                    return
                StateManager.set(user_id, UserState.WAIT_CONTEST_ANSWER)
                context.user_data['contest_join'] = cid
                await safe_edit(query, "📝 أرسل إجابتك:", bot=context.bot)
                return

            if data == CB.CONTEST_WINNERS:
                winners = await DB.get_contest_winners(10)
                text = "🏆 الفائزون\n\n" + "\n".join(
                    f"• {w['title']} - {w['winner_id']}" for w in winners
                ) if winners else "📭 لا يوجد"
                await safe_edit(query, text, bot=context.bot)
                StateManager.clear(user_id)
                return

            if data.startswith(CB.DECLARE_WINNER_SEL + ":"):
                if not CONFIG.is_developer(user_id):
                    await safe_edit(query, "❌ غير مصرح", bot=context.bot)
                    return
                try:
                    cid = int(data.split(":")[-1])
                except (ValueError, IndexError):
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return
                winner = await DB.fetchone(
                    "SELECT user_id FROM contest_participants "
                    "WHERE contest_id=? ORDER BY RANDOM() LIMIT 1",
                    (cid,),
                )
                if not winner:
                    await safe_edit(query, "❌ لا يوجد مشاركون", bot=context.bot)
                    return
                if await DB.declare_winner(cid, winner['user_id']):
                    await safe_edit(query, f"✅ الفائز: {winner['user_id']}", bot=context.bot)
                    try:
                        await context.bot.send_message(
                            winner['user_id'], "🎉 مبروك! فزت بالمسابقة!"
                        )
                    except Exception:
                        pass
                else:
                    await safe_edit(query, "❌ فشل", bot=context.bot)
                return

            await safe_edit(query, "⚠️ غير معروف", bot=context.bot)

        except Exception as e:
            logger.error(f"خطأ في المسابقات: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    # =================================================================
    # معالجات الاستيراد
    # =================================================================

    @staticmethod
    async def _handle_import(update, context, query, user_id):
        if not CONFIG.is_developer(user_id):
            await safe_edit(query, "❌ غير مصرح", bot=context.bot)
            return
        try:
            if query.data == CB.ADMIN_IMPORT_REPLIES:
                StateManager.set(user_id, UserState.WAIT_IMPORT_FILE)
                await safe_edit(query, "📤 أرسل ملف JSON:", bot=context.bot)
                return
            if query.data == CB.ADMIN_IMPORT_GITHUB:
                StateManager.set(user_id, UserState.WAIT_GITHUB_URL)
                await safe_edit(query, "📥 أرسل الرابط:", bot=context.bot)
                return
            await safe_edit(query, "⚠️ غير معروف", bot=context.bot)
        except Exception as e:
            logger.error(f"خطأ في الاستيراد: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    # =================================================================
    # النسخ الاحتياطي
    # =================================================================

    @staticmethod
    async def _do_backup(context, user_id):
        """
        ✅ v7.5.12: النسخ الاحتياطي مع حفظ last_backup بأمان.
        """
        try:
            PATHS.BACKUPS.mkdir(parents=True, exist_ok=True)
            backup_file = PATHS.BACKUPS / (
                f"backup_{TimeUtils.mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
            )
            success = await DB.backup_database(backup_file)
            if not success:
                await safe_send(context.bot, user_id, "❌ فشل النسخ الاحتياطي")
                return

            try:
                await DB.set_setting('last_backup', TimeUtils.sql_iso())
            except Exception as e:
                logger.warning(f"⚠️ فشل حفظ last_backup: {e}")

            backups = sorted(
                PATHS.BACKUPS.glob("backup_*.db"),
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            for old in backups[MAX_BACKUPS:]:
                try:
                    old.unlink(missing_ok=True)
                except OSError as e:
                    logger.debug(f"فشل حذف نسخة قديمة {old}: {e}")

            with open(backup_file, 'rb') as f:
                await context.bot.send_document(
                    chat_id=user_id, document=f, filename=backup_file.name
                )
        except asyncio.CancelledError:
            logger.info("🛑 _do_backup تم إلغاؤه")
            raise
        except Exception as e:
            logger.error(f"❌ فشل النسخ: {e}", exc_info=True)
            try:
                await safe_send(context.bot, user_id, f"❌ فشل النسخ: {str(e)[:100]}")
            except Exception:
                pass


# =====================================================================
# تصدير
# =====================================================================

__all__ = ["CallbackHandlers"]
