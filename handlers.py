#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio, re, json, logging, random
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from constants import (
    BOT_NAME, BOT_USERNAME, PRIMARY_OWNER_ID, CallbackData, UserState,
    MAX_UNPUBLISHED_POSTS, SUPPORTED_LANGUAGES,
    user_language
)
from utils import (
    safe_send_markdown, safe_edit_markdown, sanitize_text,
    utc_now, mecca_now, utc_now_iso,
    utc_to_mecca, mecca_to_utc,
    is_authorized_in_group, check_bot_permissions,
    get_advanced_group_actions_keyboard, get_advanced_mute_duration_keyboard,
    security_keyboard, get_admin_keyboard, get_group_banned_words_keyboard,
    get_replies_keyboard, get_auto_reply_keyboard, get_user_auto_reply_keyboard,
    get_banned_words_admin_keyboard, penalty_keyboard, mute_duration_keyboard,
    contains_link, contains_mention, get_ram_usage, memory_optimizer,
    build_days_keyboard, advanced_logger, log_error,
    translate_text, invalidate_user_cache, parse_days_of_week_safe,
    parse_dates_safe, rate_limiter, check_single_instance
)
from database import (
    db_register_user, db_update_user_cache, db_is_banned, db_set_ban,
    db_has_used_trial, db_activate_trial, db_activate_subscription,
    db_has_active_subscription, db_get_subscription_days_left,
    db_auto_status, db_set_auto, db_get_auto_recycle, db_set_auto_recycle,
    db_add_channel, db_get_channels, db_get_channel_info, db_delete_channel_by_id,
    db_get_active_channel, db_set_active_channel, db_get_user_channels_count,
    db_save_posts, db_get_next_post, db_mark_published, db_increment_fail_count,
    db_get_posts_count, db_get_published_count, db_reset_all_posts_to_unpublished,
    db_reset_posts_to_unpublished,
    db_get_user_posts_for_channel, db_delete_single_post, db_get_user_unpublished_posts,
    db_get_user_total_posts, db_unpublished_count, db_update_post_views,
    db_register_group, db_get_user_groups, db_get_user_groups_count, db_get_all_groups,
    db_get_security_settings, db_set_security_settings, db_check_slow_mode,
    db_add_banned_word, db_remove_banned_word, db_get_banned_words, db_contains_banned_word,
    db_register_hidden_owner_group, db_is_hidden_owner, db_add_hidden_admin,
    db_remove_hidden_admin, db_is_hidden_admin, db_get_hidden_admins,
    db_sync_group_admins, db_is_real_admin, add_bot_admin, remove_bot_admin,
    is_bot_admin, get_all_bot_admins,
    db_save_schedule, db_get_schedule, db_set_next_publish_date, db_set_last_publish,
    schedule_cron, db_update_next_publish_date, db_set_publish_time,
    db_add_scheduled_post, db_get_due_scheduled_posts, db_delete_scheduled_post,
    db_update_scheduled_post_fail,
    db_get_publish_interval, db_set_publish_interval_seconds,
    db_get_updates_channel, db_set_updates_channel,
    db_get_force_subscribe_status, db_set_force_subscribe_status,
    db_get_force_subscribe_channel, db_set_force_subscribe_channel,
    db_get_log_channel_id, db_set_log_channel_id,
    db_get_auto_backup, db_set_auto_backup, db_get_last_backup_time,
    db_get_allowed_sendcode_user, db_set_allowed_sendcode_user,
    db_add_reply, db_del_reply, db_get_reply, db_get_all_replies,
    db_get_auto_reply_settings, db_set_auto_reply_enabled, db_set_auto_reply_only_admins,
    db_toggle_auto_reply, db_get_user_auto_reply_status, db_set_user_auto_reply_status,
    db_get_referral_code, db_generate_referral_code, db_get_user_by_referral_code,
    db_add_referral, db_auto_reward_referral, db_get_referral_stats, db_claim_referral_reward,
    db_get_referral_settings, db_get_welcome_bonus_points,
    db_get_next_ticket_number, db_save_ticket, db_get_user_ticket, db_get_all_tickets,
    db_get_last_ticket_id_for_user, db_mark_ticket_replied, db_delete_all_tickets,
    db_get_user_level, db_update_user_level, get_top_users,
    db_set_chat_lock, is_chat_locked,
    db_stats, db_get_channel_stats, db_get_channel_growth, db_get_channel_stats_summary,
    db_get_active_contests_with_participants, db_get_user_participation,
    db_get_contest, db_get_random_participant, db_set_contest_winner, db_get_contest_winners,
    set_user_language, db_get_all_user_channels_no_limit, db_all_users_channels,
    db_get_user_reminder_settings, db_update_reminder_settings,
    db_get_users_needing_reminder, db_update_last_reminder_sent,
    get_user_translation_language, set_user_translation_language,
    execute_db
)
from security import (
    apply_penalty, execute_ban, execute_mute, execute_kick, execute_warn,
    execute_restrict, execute_pin, execute_unban, get_moderation_log,
    is_nsfw_enabled, get_nsfw_threshold, set_nsfw_threshold
)

logger = logging.getLogger(__name__)

# ===================== دوال القوائم الرئيسية =====================
async def get_main_keyboard(user_id: int):
    """بناء لوحة المفاتيح الرئيسية"""
    channels = await db_get_channels(user_id)
    active = None
    if channels:
        try:
            active = await db_get_active_channel(user_id)
            if active is not None:
                channel_exists = False
                for ch in channels:
                    if ch[0] == active:
                        channel_exists = True
                        break
                if not channel_exists:
                    active = channels[0][0]
                    await db_set_active_channel(user_id, active)
            else:
                active = channels[0][0]
                await db_set_active_channel(user_id, active)
        except:
            active = channels[0][0] if channels else None
    cnt = 0
    ch_display = "لا توجد قنوات"
    if active is not None:
        try:
            cnt = await db_unpublished_count(active)
            ch_info = await db_get_channel_info(active)
            if ch_info and ch_info.get('channel_id'):
                ch_tele_id = ch_info['channel_id']
                ch_name = ch_info.get('channel_name', ch_tele_id)
                ch_display = f"{ch_name} ({ch_tele_id})"
        except:
            ch_display = "لا توجد قنوات"
    my_groups = 0
    try:
        my_groups = await db_get_user_groups_count(user_id)
    except:
        my_groups = 0
    has_sub = False
    try:
        has_sub = await db_has_active_subscription(user_id)
    except:
        has_sub = False
    sub_text = "✅ مفعل" if has_sub else "❌ غير مفعل"
    auto_status = False
    try:
        auto_status = await db_auto_status(user_id)
    except:
        auto_status = False
    auto_text = "مفعل" if auto_status else "معطل"
    title = f"🌿 **{BOT_NAME}**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 المعرف: `{user_id}`\n👥 مجموعاتي: {my_groups}\n💎 الاشتراك: {sub_text}\n📡 القناة النشطة: {ch_display}\n📝 المنشورات غير المنشورة: {cnt}\n⚙️ النشر التلقائي: {auto_text}"

    keyboard = [
        [InlineKeyboardButton("👥 مجموعاتي", callback_data=CallbackData.GROUPS_MY),
         InlineKeyboardButton("➕ إضافة قناة", callback_data=CallbackData.CHANNELS_ADD)],
        [InlineKeyboardButton("📡 قنواتي", callback_data=CallbackData.CHANNELS_MY),
         InlineKeyboardButton("⚙️ الإعدادات", callback_data=CallbackData.SETTINGS_MENU)],
        [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.HELP),
         InlineKeyboardButton("🎁 تجربة مجانية", callback_data=CallbackData.TRIAL)],
        [InlineKeyboardButton("💎 اشتراك", callback_data=CallbackData.SUBSCRIBE_MENU),
         InlineKeyboardButton("👨‍💻 المطور", callback_data=CallbackData.DEVELOPER)],
        [InlineKeyboardButton("🌐 اللغة", callback_data="language"),
         InlineKeyboardButton("📞 الدعم", callback_data=CallbackData.SUPPORT_MENU)],
        [InlineKeyboardButton("🏆 المسابقات", callback_data=CallbackData.CONTESTS_MENU)],
        [InlineKeyboardButton("➕ إضافة إلى مجموعة", url=f"https://t.me/{BOT_USERNAME}?startgroup")]
    ]

    is_admin = (user_id == PRIMARY_OWNER_ID) or (await is_bot_admin(user_id))
    if is_admin:
        keyboard.append([InlineKeyboardButton("👑 لوحة الأدمن", callback_data=CallbackData.ADMIN_PANEL)])

    return InlineKeyboardMarkup(keyboard), title, active

# ===================== دوال مساعدة =====================
async def is_user_subscribed(bot, user_id, channel):
    if not channel: return True
    channel = channel.lstrip('@')
    try:
        member = await bot.get_chat_member(f"@{channel}", user_id)
        return member.status in ['member', 'administrator', 'creator']
    except: return False

async def ensure_force_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None):
    if user_id is None:
        if update.effective_user is None: return True
        user_id = update.effective_user.id
    if user_id == PRIMARY_OWNER_ID or await is_bot_admin(user_id): return True
    if not await db_get_force_subscribe_status(): return True
    channel = await db_get_force_subscribe_channel()
    if not channel: return True
    if await is_user_subscribed(context.bot, user_id, channel): return True

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 اشترك في القناة", url=f"https://t.me/{channel.lstrip('@')}"),
         InlineKeyboardButton("🔄 تأكد من الاشتراك", callback_data=CallbackData.CHECK_SUBSCRIBE)],
        [InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.BACK)]
    ])
    msg = f"🔒 **اشتراك إجباري**\n\nيجب عليك الاشتراك في قناتنا أولاً:\n👉 @{channel.lstrip('@')}\n\nبعد الاشتراك، اضغط على زر التحقق."
    try:
        if update.callback_query:
            await safe_edit_markdown(update.callback_query, msg, reply_markup=keyboard)
        elif update.message:
            await safe_send_markdown(context.bot, user_id, msg, reply_markup=keyboard)
    except: pass
    return False

# ===================== معالجات الأوامر =====================
async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    user_id = user.id
    await db_register_user(user_id)
    await db_update_user_cache(user_id, user.username or "", user.first_name or "")
    if context.args and context.args[0].startswith('ref_'):
        referral_code = context.args[0].replace('ref_', '')
        referrer_id = await db_get_user_by_referral_code(referral_code)
        if referrer_id and referrer_id != user_id:
            await db_add_referral(referrer_id, user_id)
            await db_auto_reward_referral(referrer_id, user_id)
    await main_menu_callback(update, context)

async def help_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "❓ **المساعدة**\n/start - القائمة الرئيسية\n/trial - تجربة مجانية\n/subscribe - الاشتراك\n/syncgroup - تفعيل المجموعة\n/security - إعدادات الأمان\n/panel - لوحة التحكم\n/stats - إحصائيات\n/contests - المسابقات\n/lock - قفل المجموعة\n/unlock - فتح المجموعة\n/ban - حظر\n/mute - كتم\n/kick - طرد\n/warn - تحذير\n/pin - تثبيت\n/help - هذه المساعدة"
    await safe_send_markdown(context.bot, update.effective_user.id, text)

async def language_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"), InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await update.message.reply_text("اختر اللغة:", reply_markup=keyboard)

async def panel_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    current_lock = await is_chat_locked(chat_id)
    lock_status = "🔒 مقفلة" if current_lock else "🔓 مفتوحة"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 قفل المجموعة", callback_data=f"{CallbackData.PANEL_LOCK_PREFIX}{chat_id}"),
         InlineKeyboardButton("🔓 فتح المجموعة", callback_data=f"{CallbackData.PANEL_UNLOCK_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}"),
         InlineKeyboardButton("🔙 إغلاق", callback_data=CallbackData.PANEL_CLOSE)]
    ])
    await update.message.reply_text(f"🔧 **لوحة تحكم المجموعة**\nالحالة: {lock_status}", reply_markup=kb)

async def stats_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    active = await db_get_active_channel(uid)
    if not active:
        await update.message.reply_text("⚠️ يرجى اختيار قناة أولاً")
        return
    stats = await db_get_channel_stats(active)
    text = f"📊 **إحصائيات القناة**\n📝 المنشورات: {stats['total_posts']}\n✅ المنشورة: {stats['published_posts']}\n⏳ غير المنشورة: {stats['unpublished_posts']}"
    await safe_send_markdown(context.bot, uid, text)

# ===================== أوامر إضافية (اختصارات) =====================
async def syncgroup_command_handler(update, context): await update.message.reply_text("✅ استخدم هذا الأمر في المجموعة لتفعيلها.")
async def security_command_handler(update, context): await update.message.reply_text("🔐 استخدم /panel أو أزرار المجموعة.")
async def trial_command_handler(update, context): await trial_callback(update, context)
async def subscribe_command_handler(update, context): await subscribe_menu_callback(update, context)
async def support_command_handler(update, context): await update.message.reply_text("📞 الدعم: @RelaxMgr")
async def rank_command_handler(update, context): await handle_text_callbacks(update, context)
async def top_command_handler(update, context): await handle_text_callbacks(update, context)
async def developer_command_handler(update, context): await update.message.reply_text("👨‍💻 المطور: @RelaxMgr")
async def updates_command_handler(update, context): await update.message.reply_text("📢 تابع قناة التحديثات.")
async def lock_chat_command_handler(update, context): await update.message.reply_text("🔒 استخدم /panel.")
async def unlock_chat_command_handler(update, context): await update.message.reply_text("🔓 استخدم /panel.")
async def schedule_post_command_handler(update, context): await update.message.reply_text("⏰ استخدم أزرار الجدولة.")
async def set_log_channel_command_handler(update, context): await update.message.reply_text("📋 استخدم لوحة الأدمن.")
async def set_rules_command_handler(update, context): await update.message.reply_text("📜 استخدم /set_rules في المجموعة.")
async def rules_command_handler(update, context): await update.message.reply_text("📜 استخدم /rules في المجموعة.")
async def handle_moderation_commands(update, context): await update.message.reply_text("🛡️ استخدم الأزرار في المجموعة.")
async def track_chat_add(update, context): pass
async def track_chat_member(update, context): pass
async def on_bot_added(update, context): await update.message.reply_text("✅ تم تفعيل البوت في المجموعة!")
async def pre_checkout_callback_handler(update, context): await update.pre_checkout_query.answer(ok=True)
async def successful_payment_callback_handler(update, context): await update.message.reply_text("✅ تم الدفع!")
async def register_hidden_owner_handler(update, context): await update.message.reply_text("🔒 استخدم هذا الأمر في المجموعة.")
async def add_hidden_admin_command(update, context): await update.message.reply_text("➕ استخدم هذا الأمر في المجموعة.")
async def remove_hidden_admin_command(update, context): await update.message.reply_text("➖ استخدم هذا الأمر في المجموعة.")
async def list_hidden_admins_command(update, context): await update.message.reply_text("📋 استخدم هذا الأمر في المجموعة.")
async def create_contest_command_handler(update, context): await update.message.reply_text("🏆 استخدم لوحة الأدمن.")
async def declare_winner_command_handler(update, context): await update.message.reply_text("🏅 استخدم لوحة الأدمن.")

# ===================== الكولباك =====================
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    kb, title, active = await get_main_keyboard(uid)
    if active:
        context.user_data['active_channel'] = active
        await db_set_active_channel(uid, active)
    if query:
        await safe_edit_markdown(query, title, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, title, reply_markup=kb)

async def back_callback(update, context):
    await main_menu_callback(update, context)

async def cancel_session_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    context.user_data.pop('state', None)
    await main_menu_callback(update, context)

async def trial_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    if await db_has_used_trial(uid):
        await query.edit_message_text("❌ لقد استخدمت التجربة المجانية مسبقاً")
        return
    await db_activate_trial(uid)
    await query.edit_message_text("🎁 **تم تفعيل التجربة المجانية!**\n✅ لديك 30 يوماً مجاناً")

async def subscribe_menu_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    if await db_has_active_subscription(uid):
        days = await db_get_subscription_days_left(uid)
        await query.edit_message_text(f"✅ اشتراكك مفعل، متبقي {days} يوم")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_1),
         InlineKeyboardButton("⭐ 2 يوم - 9 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_2)],
        [InlineKeyboardButton("⭐ شهر (30 يوم) - 50 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_30),
         InlineKeyboardButton("⭐ 3 أشهر (90 يوم) - 120 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_90)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit_markdown(query, "💎 **الاشتراك**\nاختر الباقة:", reply_markup=kb)

async def settings_menu_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    auto = await db_auto_status(uid)
    auto_btn = "❌ تعطيل" if auto else "✅ تفعيل"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{auto_btn} النشر التلقائي", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await query.edit_message_text("⚙️ **الإعدادات**", reply_markup=kb)

async def toggle_auto_publish_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    cur = await db_auto_status(uid)
    await db_set_auto(uid, not cur)
    await query.edit_message_text(f"✅ النشر التلقائي {'مفعل' if not cur else 'معطل'}")

async def toggle_auto_recycle_callback(update, context): pass

async def lang_callback_handler(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    lang = query.data.split("_")[-1]
    if lang not in SUPPORTED_LANGUAGES: return
    user_language[uid] = lang
    await set_user_language(uid, lang)
    await query.edit_message_text(f"✅ اللغة: {SUPPORTED_LANGUAGES[lang]}")

async def handle_text_callbacks(update, context):
    query = update.callback_query
    if query: await query.answer()
    data = query.data
    uid = update.effective_user.id
    if data == "rank":
        level = await db_get_user_level(uid)
        await safe_edit_markdown(query, f"🏆 **رتبتك**\n⭐ المستوى: {level['level']}\n💎 النقاط: {level['points']}")
    elif data == "top":
        top = await get_top_users(10)
        text = "🏆 **أفضل 10**\n" + "\n".join([f"{i}. `{u}` - ⭐ {l} - 💎 {p}" for i, (u, p, l) in enumerate(top, 1)])
        await safe_edit_markdown(query, text)
    elif data == "language":
        await language_command_handler(update, context)

# ===================== مجموعاتي وقنواتي =====================
async def my_groups_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    groups = await db_get_user_groups(uid)
    if not groups:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{BOT_USERNAME}?startgroup")], [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
        await safe_edit_markdown(query, "📭 لا توجد مجموعات", reply_markup=kb)
        return
    keyboard = []
    for chat_id, chat_name, _, _ in groups:
        display = chat_name[:28] + "..." if len(chat_name) > 31 else chat_name
        keyboard.append([InlineKeyboardButton(display, callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await safe_edit_markdown(query, "👥 **مجموعاتي**", reply_markup=InlineKeyboardMarkup(keyboard))

async def group_settings_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await query.edit_message_text("🔒 غير مصرح")
        return
    kb = security_keyboard(chat_id)
    await safe_edit_markdown(query, "⚙️ **لوحة تحكم المجموعة**", reply_markup=kb)

async def security_links_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid): return
    settings = await db_get_security_settings(chat_id)
    await db_set_security_settings(chat_id, links=not settings['links'])
    await group_settings_callback(update, context)

async def security_mentions_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid): return
    settings = await db_get_security_settings(chat_id)
    await db_set_security_settings(chat_id, mentions=not settings['mentions'])
    await group_settings_callback(update, context)

async def security_stickers_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid): return
    settings = await db_get_security_settings(chat_id)
    await db_set_security_settings(chat_id, delete_stickers=not settings.get('delete_stickers', False))
    await group_settings_callback(update, context)

async def security_videos_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid): return
    settings = await db_get_security_settings(chat_id)
    await db_set_security_settings(chat_id, delete_videos=not settings.get('delete_videos', False))
    await group_settings_callback(update, context)

async def add_channel_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_CHANNEL_ID
    await query.edit_message_text("📡 أرسل معرف القناة:")

async def my_channels_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    channels = await db_get_channels(uid)
    if not channels:
        await query.edit_message_text("📭 لا توجد قنوات")
        return
    kb = []
    for ch_db_id, ch_tele_id, ch_name, _ in channels:
        display = ch_name if ch_name != ch_tele_id else ch_tele_id
        kb.append([InlineKeyboardButton(f"📢 {display}", callback_data=f"{CallbackData.CHANNELS_SELECT_PREFIX}{ch_db_id}"),
                   InlineKeyboardButton("🗑️ حذف", callback_data=f"{CallbackData.CHANNELS_DELETE_PREFIX}{ch_db_id}")])
    kb.append([InlineKeyboardButton("➕ إضافة قناة", callback_data=CallbackData.CHANNELS_ADD)])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await query.edit_message_text("📡 **قنواتي**", reply_markup=InlineKeyboardMarkup(kb))

async def select_channel_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    await db_set_active_channel(uid, ch_db_id)
    context.user_data['active_channel'] = ch_db_id
    await query.edit_message_text("✅ تم تعيين القناة النشطة")

async def delete_channel_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    if await db_delete_channel_by_id(uid, ch_db_id):
        await query.edit_message_text("✅ تم حذف القناة")
    else:
        await query.answer("❌ فشل الحذف", show_alert=True)

async def add_15_posts_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        await query.edit_message_text("⚠️ اختر قناة أولاً")
        return
    context.user_data['state'] = UserState.ADDING_POSTS
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.CANCEL_SESSION)]])
    await query.edit_message_text("📥 أرسل المنشورات الآن:", reply_markup=cancel_kb)

async def help_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    text = "❓ **المساعدة**\n/start - القائمة الرئيسية\n/help - هذه المساعدة"
    await safe_edit_markdown(query, text)

# ===================== مسابقات =====================
async def contests_menu_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    contests = await db_get_active_contests_with_participants(10)
    if not contests:
        text = "📭 لا توجد مسابقات نشطة"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    else:
        text = "🏆 **المسابقات النشطة**\n"
        kb = []
        for c in contests:
            kb.append([InlineKeyboardButton(f"🎯 {c[1]}", callback_data=f"{CallbackData.CONTEST_JOIN_PREFIX}{c[0]}")])
        kb.append([InlineKeyboardButton("🏅 الفائزون السابقون", callback_data=CallbackData.CONTEST_WINNERS)])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.CONTESTS_BACK)])
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(kb))

async def contest_join_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    uid = update.effective_user.id
    cid = int(query.data.split(":")[-1])
    if await db_get_user_participation(uid, cid):
        await query.answer("أنت مشترك بالفعل", show_alert=True)
        return
    async def _join(conn):
        await conn.execute("INSERT INTO contest_participants (user_id, contest_id, joined_at) VALUES (?, ?, ?)", (uid, cid, utc_now_iso()))
        await conn.commit()
    await execute_db(_join)
    await query.edit_message_text("✅ تم الاشتراك في المسابقة")

async def contest_winners_callback(update, context):
    query = update.callback_query
    if query: await query.answer()
    winners = await db_get_contest_winners()
    text = "🏅 **الفائزون السابقون**\n" + "\n".join([f"• {w[1]} - الفائز: {w[3]}" for w in winners])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.CONTESTS_BACK)]])
    await safe_edit_markdown(query, text, reply_markup=kb)

async def contests_back_callback(update, context):
    await main_menu_callback(update, context)

async def contests_command_handler(update, context):
    await contests_menu_callback(update, context)

# ===================== رسائل المجموعات =====================
async def filter_messages_handler(update, context):
    if not update.message: return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    msg = update.message
    text = msg.text or msg.caption or ""
    if await is_chat_locked(chat_id) and not await is_authorized_in_group(context.bot, chat_id, user_id):
        try: await msg.delete()
        except: pass
        return
    settings = await db_get_security_settings(chat_id)
    if settings.get('links') and contains_link(text):
        await msg.delete()
        await apply_penalty(context.bot, chat_id, user_id, settings, "إرسال رابط")
        return
    if settings.get('mentions') and contains_mention(text):
        await msg.delete()
        await apply_penalty(context.bot, chat_id, user_id, settings, "إرسال معرف")
        return
    if settings.get('delete_stickers') and msg.sticker:
        try: await msg.delete()
        except: pass
        return
    if settings.get('delete_videos') and (msg.video or msg.video_note):
        try: await msg.delete()
        except: pass
        return

# ===================== رسائل الخاص =====================
async def message_handler_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg: return
    user_id = update.effective_user.id
    state = context.user_data.get('state')

    if state == UserState.WAITING_CHANNEL_ID:
        channel_id = msg.text.strip().lstrip('@')
        try:
            chat = await context.bot.get_chat(f"@{channel_id}")
            await db_add_channel(user_id, str(chat.id), chat.title or channel_id)
            await msg.reply_text("✅ تمت إضافة القناة بنجاح")
        except:
            await msg.reply_text("❌ فشل إضافة القناة")
        context.user_data.pop('state', None)
        await main_menu_callback(update, context)
        return

    if state == UserState.ADDING_POSTS:
        text_content = msg.text or msg.caption or ""
        media_type = 'text'
        media_file_id = ''
        if msg.photo:
            media_type = 'photo'
            media_file_id = msg.photo[-1].file_id
        elif msg.video:
            media_type = 'video'
            media_file_id = msg.video.file_id
        elif msg.document:
            media_type = 'document'
            media_file_id = msg.document.file_id
        active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
        if active:
            await db_save_posts(active, [(text_content, media_type, media_file_id)])
            await msg.reply_text("✅ تم حفظ المنشور")
        context.user_data.pop('state', None)
        await main_menu_callback(update, context)
        return

    # إذا لم يكن في حالة خاصة، عرض القائمة الرئيسية
    await main_menu_callback(update, context)

# ===================== الدوال المفقودة التي قد يحتاجها bot.py =====================
async def private_message_router(update, context):
    """موجه الرسائل الخاصة"""
    return await message_handler_main(update, context)

async def global_error_handler(update, context):
    logger.error(msg="حدث خطأ:", exc_info=context.error)

async def admin_panel_callback(update, context): pass
async def handle_contest_creation_states(update, context): pass
async def sendcode_command_handler(update, context): pass
async def admin_replies_callback(update, context): pass
async def admin_banned_words_callback(update, context): pass
async def nsfw_settings_callback(update, context): pass
async def handle_sendcode_confirmation_handler(update, context): pass
