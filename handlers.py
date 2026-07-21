#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
معالجات الأوامر والكولباك والرسائل - كاملة ومتسقة
"""

import asyncio
import json
import re
import time as time_module
import secrets
import hashlib
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, BotCommand, LabeledPrice
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters, PreCheckoutQueryHandler, ChatMemberHandler
from telegram.error import TimedOut, NetworkError, BadRequest, Forbidden

from constants import (
    BOT_NAME, BOT_USERNAME, PRIMARY_OWNER_ID, CallbackData, UserState,
    LEVEL_REQUIREMENTS, MAX_UNPUBLISHED_POSTS, MAX_POSTS_PER_SESSION,
    TOKEN, SUPPORTED_LANGUAGES, ENABLE_2FA, ADMIN_2FA_SECRET, PYOTP_AVAILABLE,
    BATTERY_SAVER_MODE, MAX_FILE_SIZE, DEFAULT_PUBLISH_INTERVAL_SECONDS,
    user_language, get_nsfw_lock
)
from utils import (
    safe_send_markdown, safe_edit_markdown, safe_send_error, safe_send_long_message,
    escape_markdown_v2, sanitize_text, utc_now, mecca_now, utc_now_iso, mecca_now_iso,
    utc_to_mecca, mecca_to_utc, is_authorized_in_group, invalidate_auth_cache,
    get_advanced_group_actions_keyboard, get_advanced_mute_duration_keyboard,
    security_keyboard, get_admin_keyboard, get_group_banned_words_keyboard,
    get_replies_keyboard, get_auto_reply_keyboard, get_user_auto_reply_keyboard,
    get_banned_words_admin_keyboard, penalty_keyboard, mute_duration_keyboard,
    contains_link, contains_mention, get_ram_usage, memory_optimizer,
    build_days_keyboard, check_bot_permissions, advanced_logger, log_error,
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
    db_register_channel, db_get_all_bot_channels, db_get_user_reminder_settings,
    db_update_reminder_settings, db_get_users_needing_reminder, db_update_last_reminder_sent,
    db_get_subscription_days_left,
    get_user_translation_language, set_user_translation_language,
    execute_db
)
from security import (
    check_nsfw_cached, check_nsfw_video, load_banned_words_from_file,
    import_banned_words_from_file, BANNED_PATTERNS,
    apply_penalty, execute_ban, execute_mute, execute_kick, execute_warn,
    execute_restrict, execute_pin, execute_unban, get_moderation_log,
    check_bot_admin_permissions, delete_message_after_delay, NSFW_ENABLED,
    NSFW_THRESHOLD, NSFW_MAX_FILE_SIZE, NSFW_MAX_VIDEO_SIZE, NSFW_FRAMES,
    security_audit, anomaly_detector, is_nsfw_enabled, get_nsfw_threshold,
    set_nsfw_threshold
)
from replies import ALL_REPLIES
from tasks import BackgroundTaskManager
from web import ws_manager, ws_extended

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
    lang = user_language.get(user_id, 'ar')
    title = f"🌿 **{BOT_NAME}**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 المعرف: `{user_id}`\n👥 مجموعاتي: {my_groups}\n💎 الاشتراك: {sub_text}\n📡 القناة النشطة: {ch_display}\n📝 المنشورات غير المنشورة: {cnt}\n⚙️ النشر التلقائي: {auto_text}"
    updates_channel = None
    try:
        updates_channel = await db_get_updates_channel()
    except:
        updates_channel = None
    updates_url = f"https://t.me/{updates_channel}" if updates_channel else None

    keyboard = []
    keyboard.append([
        InlineKeyboardButton("👥 مجموعاتي", callback_data=CallbackData.GROUPS_MY),
        InlineKeyboardButton("➕ إضافة قناة", callback_data=CallbackData.CHANNELS_ADD)
    ])
    keyboard.append([
        InlineKeyboardButton("📡 قنواتي", callback_data=CallbackData.CHANNELS_MY),
        InlineKeyboardButton("⚙️ الإعدادات", callback_data=CallbackData.SETTINGS_MENU)
    ])

    if channels:
        keyboard.append([
            InlineKeyboardButton("📥 إضافة 15 منشور", callback_data=CallbackData.POSTS_ADD_15),
            InlineKeyboardButton("📤 نشر واحد", callback_data=CallbackData.POSTS_PUBLISH_ONE)
        ])
        keyboard.append([
            InlineKeyboardButton("📋 منشوراتي", callback_data=CallbackData.POSTS_MY),
            InlineKeyboardButton("♻️ إعادة تدوير", callback_data=CallbackData.POSTS_RECYCLE)
        ])
        keyboard.append([
            InlineKeyboardButton(f"📊 منشوراتي غير المنشورة ({cnt})", callback_data=CallbackData.STATS_PENDING),
            InlineKeyboardButton("📈 إحصائيات كاملة", callback_data=CallbackData.STATS_FULL)
        ])
        if active is not None:
            keyboard.append([
                InlineKeyboardButton("⏰ الجدولة", callback_data=f"{CallbackData.SCHEDULE_MENU_PREFIX}{active}"),
                InlineKeyboardButton("📊 إحصائيات القناة", callback_data=f"{CallbackData.CHANNEL_STATS}:{active}")
            ])
        keyboard.append([
            InlineKeyboardButton("📊 ملخص قنواتي", callback_data=CallbackData.MY_CHANNEL_STATS),
            InlineKeyboardButton("📊 رتبتي", callback_data="rank")
        ])
        keyboard.append([
            InlineKeyboardButton("🏆 أفضل 10", callback_data="top"),
            InlineKeyboardButton("📝 جدولة منشور", callback_data="schedule_post")
        ])
        keyboard.append([
            InlineKeyboardButton("📤 نشر الكل", callback_data=CallbackData.PUBLISH_ALL_CHANNELS)
        ])

    keyboard.append([
        InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.HELP),
        InlineKeyboardButton("🎁 تجربة مجانية", callback_data=CallbackData.TRIAL)
    ])
    keyboard.append([
        InlineKeyboardButton("💎 اشتراك", callback_data=CallbackData.SUBSCRIBE_MENU),
        InlineKeyboardButton("👨‍💻 المطور", callback_data=CallbackData.DEVELOPER)
    ])
    keyboard.append([
        InlineKeyboardButton("🌐 اللغة", callback_data="language"),
        InlineKeyboardButton("📞 الدعم", callback_data=CallbackData.SUPPORT_MENU)
    ])
    keyboard.append([
        InlineKeyboardButton("🔗 الإحالات", callback_data=CallbackData.REFERRAL_MENU),
        InlineKeyboardButton("⏰ التذكيرات", callback_data=CallbackData.REMINDER_MENU)
    ])
    keyboard.append([
        InlineKeyboardButton("🌐 الترجمة", callback_data=CallbackData.TRANSLATION_MENU)
    ])
    keyboard.append([
        InlineKeyboardButton("🏆 المسابقات", callback_data=CallbackData.CONTESTS_MENU)
    ])
    if updates_url:
        keyboard.append([
            InlineKeyboardButton("📢 التحديثات", callback_data=CallbackData.UPDATES)
        ])
    keyboard.append([
        InlineKeyboardButton("➕ إضافة إلى مجموعة", url=f"https://t.me/{BOT_USERNAME}?startgroup")
    ])
    is_admin = False
    try:
        is_admin = (user_id == PRIMARY_OWNER_ID) or (await is_bot_admin(user_id))
    except:
        is_admin = False
    if is_admin:
        keyboard.append([
            InlineKeyboardButton("👑 لوحة الأدمن", callback_data=CallbackData.ADMIN_PANEL)
        ])
    valid_keyboard = []
    for row in keyboard:
        if row and all(isinstance(btn, InlineKeyboardButton) for btn in row):
            valid_keyboard.append(row)
    if not valid_keyboard:
        valid_keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    return InlineKeyboardMarkup(valid_keyboard), title, active

# ===================== دوال التحقق من القناة =====================
async def is_user_subscribed(bot, user_id, channel):
    if not channel:
        return True
    channel = channel.lstrip('@')
    try:
        member = await bot.get_chat_member(f"@{channel}", user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

async def ensure_force_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None):
    if user_id is None:
        if update.effective_user is None:
            return True
        user_id = update.effective_user.id
    if user_id == PRIMARY_OWNER_ID or await is_bot_admin(user_id):
        return True
    if not await db_get_force_subscribe_status():
        return True
    channel = await db_get_force_subscribe_channel()
    if not channel:
        return True
    if await is_user_subscribed(context.bot, user_id, channel):
        return True
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 اشترك في القناة", url=f"https://t.me/{channel.lstrip('@')}"),
         InlineKeyboardButton("🔄 تأكد من الاشتراك", callback_data=CallbackData.CHECK_SUBSCRIBE)],
        [InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.BACK)]
    ])
    msg = f"🔒 **اشتراك إجباري**\n\nيجب عليك الاشتراك في قناتنا أولاً:\n👉 @{channel.lstrip('@')}\n\nبعد الاشتراك، اضغط على زر التحقق."
    try:
        if update.callback_query:
            if update.callback_query.message.text == msg:
                return False
            await safe_edit_markdown(update.callback_query, msg, reply_markup=keyboard)
        elif update.message:
            await safe_send_markdown(context.bot, user_id, msg, reply_markup=keyboard)
    except:
        pass
    return False

# ===================== معالجات الأوامر الأساسية =====================
async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""
    await db_register_user(user_id)
    await db_update_user_cache(user_id, username, first_name)
    if context.args and context.args[0].startswith('ref_'):
        referral_code = context.args[0].replace('ref_', '')
        referrer_id = await db_get_user_by_referral_code(referral_code)
        if referrer_id and referrer_id != user_id:
            success = await db_add_referral(referrer_id, user_id)
            if success:
                reward_days = await db_auto_reward_referral(referrer_id, user_id)
                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"🎉 **تهانينا!**\nقام {first_name} بالاشتراك باستخدام رابط إحالتك!\nتم إضافة {reward_days} أيام إلى اشتراكك 🎁",
                        parse_mode="MarkdownV2"
                    )
                except:
                    pass
                welcome_points = await db_get_welcome_bonus_points()
                if welcome_points > 0:
                    level_data = await db_get_user_level(user_id)
                    await db_update_user_level(user_id, level_data['points'] + welcome_points, level_data['level'])
    await main_menu_callback(update, context)

async def language_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"),
         InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")],
        [InlineKeyboardButton("Français 🇫🇷", callback_data="lang_fr"),
         InlineKeyboardButton("Türkçe 🇹🇷", callback_data="lang_tr")],
        [InlineKeyboardButton("中文 🇨🇳", callback_data="lang_zh"),
         InlineKeyboardButton("Русский 🇷🇺", callback_data="lang_ru")],
        [InlineKeyboardButton("Deutsch 🇩🇪", callback_data="lang_de"),
         InlineKeyboardButton("Español 🇪🇸", callback_data="lang_es")],
        [InlineKeyboardButton("Italiano 🇮🇹", callback_data="lang_it"),
         InlineKeyboardButton("Português 🇵🇹", callback_data="lang_pt")],
        [InlineKeyboardButton("日本語 🇯🇵", callback_data="lang_ja"),
         InlineKeyboardButton("한국어 🇰🇷", callback_data="lang_ko")]
    ])
    await update.message.reply_text("🌿 **مرحباً بك في ريلاكس مانيجر**\nاختر اللغة المناسبة", reply_markup=keyboard, parse_mode="MarkdownV2")

async def syncgroup_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    chat_name = update.effective_chat.title or "بدون اسم"
    user_id = update.effective_user.id
    await db_register_group(chat_id, chat_name, user_id, update.effective_chat.username)
    await db_sync_group_admins(chat_id, context.bot, user_id)
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"⚠️ **تنبيه:**\n{bot_perms['reason']}\n\nيرجى منح البوت الصلاحيات المطلوبة.")
        return
    if await is_authorized_in_group(context.bot, chat_id, user_id):
        await db_register_hidden_owner_group(chat_id, user_id)
    await update.message.reply_text(
        f"✅ **تم تفعيل المجموعة بنجاح!**\n\n"
        f"📌 اسم المجموعة: {chat_name}\n"
        f"🆔 المعرف: {chat_id}\n"
        f"👤 المضافة بواسطة: {user_id}\n\n"
        f"🔐 استخدم /security لإعدادات الأمان\n"
        f"🛠️ استخدم /panel للوحة التحكم",
        parse_mode="MarkdownV2"
    )

async def security_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    await security_select_group_callback(update, context)

async def trial_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await trial_callback(update, context)

async def subscribe_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscribe_menu_callback(update, context)

async def help_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user_id = update.effective_user.id
    await help_callback(update, context)

async def support_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await support_menu_callback(update, context)

async def rank_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_text_callbacks(update, context)

async def top_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_text_callbacks(update, context)

async def developer_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await developer_callback(update, context)

async def updates_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await updates_callback(update, context)

async def stats_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    uid = update.effective_user.id
    if not await ensure_force_subscribe(update, context, uid):
        return
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        await update.message.reply_text("⚠️ يرجى اختيار قناة أولاً")
        return
    stats = await db_get_channel_stats(active)
    ch_info = await db_get_channel_info(active)
    channel_name = ch_info['channel_name'] if ch_info else "القناة"
    if stats['total_posts'] == 0:
        text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد منشورات بعد"
        await safe_send_markdown(context.bot, uid, text)
        return
    text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📝 إجمالي المنشورات: {stats['total_posts']}\n"
    text += f"✅ المنشورة: {stats['published_posts']}\n"
    text += f"⏳ غير المنشورة: {stats['unpublished_posts']}\n"
    text += f"👁️ إجمالي المشاهدات: {stats['total_views']}\n"
    text += f"📊 متوسط المشاهدات: {stats['avg_views']}\n"
    if stats['last_post_time']:
        try:
            last_dt = datetime.fromisoformat(stats['last_post_time'])
            last_mecca = utc_to_mecca(last_dt)
            text += f"🕐 آخر نشر: {last_mecca.strftime('%Y-%m-%d %H:%M')}\n"
        except:
            pass
    if stats['first_post_time']:
        try:
            first_dt = datetime.fromisoformat(stats['first_post_time'])
            first_mecca = utc_to_mecca(first_dt)
            text += f"📅 أول نشر: {first_mecca.strftime('%Y-%m-%d %H:%M')}\n"
        except:
            pass
    if stats['most_viewed_post']:
        text += f"\n🏆 **الأكثر مشاهدة:**\n{stats['most_viewed_post']['text']}\n👁️ {stats['most_viewed_post']['views']} مشاهدة\n"
    if stats['least_viewed_post']:
        text += f"\n📉 **الأقل مشاهدة:**\n{stats['least_viewed_post']['text']}\n👁️ {stats['least_viewed_post']['views']} مشاهدة\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{active}")],
        [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{active}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def lock_chat_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat is None or update.effective_user is None:
        return
    if update.effective_chat.type == 'private':
        await update.message.reply_text("🔒 هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    await db_set_chat_lock(chat_id, True, user_id)
    await update.message.reply_text("🔒 تم قفل المجموعة", parse_mode="MarkdownV2")

async def unlock_chat_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat is None or update.effective_user is None:
        return
    if update.effective_chat.type == 'private':
        await update.message.reply_text("🔒 هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    await db_set_chat_lock(chat_id, False)
    await update.message.reply_text("🔓 تم فتح المجموعة", parse_mode="MarkdownV2")

async def panel_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        if not await ensure_force_subscribe(update, context):
            return
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return
    chat = update.effective_chat
    user_id = update.effective_user.id
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("🔒 هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = chat.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    current_lock_status = await is_chat_locked(chat_id)
    lock_status_text = "🔒 مقفلة" if current_lock_status else "🔓 مفتوحة"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔒 قفل المجموعة", callback_data=f"{CallbackData.PANEL_LOCK_PREFIX}{chat_id}"),
         InlineKeyboardButton("🔓 فتح المجموعة", callback_data=f"{CallbackData.PANEL_UNLOCK_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}"),
         InlineKeyboardButton("🔙 إغلاق اللوحة", callback_data=CallbackData.PANEL_CLOSE)]
    ])
    await update.message.reply_text(f"🔧 **لوحة تحكم المجموعة**\n━━━━━━━━━━━━━━\n📌 **المجموعة:** {chat.title}\n🔐 **الحالة:** {lock_status_text}\n━━━━━━━━━━━━━━\n\nاستخدم الأزرار للتحكم في قفل وفتح المجموعة والإجراءات المتقدمة", reply_markup=kb, parse_mode="MarkdownV2")

async def schedule_post_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None or update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("📝 **الاستخدام:**\n`/schedule YYYY-MM-DD HH:MM نص المنشور`", parse_mode="MarkdownV2")
        return
    try:
        date_str = args[0]
        time_str = args[1]
        text = " ".join(args[2:])
        mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        if mecca_dt <= mecca_now():
            await update.message.reply_text("❌ **الوقت يجب أن يكون في المستقبل!**", parse_mode="MarkdownV2")
            return
        utc_dt = mecca_to_utc(mecca_dt)
        await db_add_scheduled_post(chat_id, text, utc_dt)
        await update.message.reply_text(f"✅ **تم جدولة المنشور!**\n📅 {date_str} 🕐 {time_str} (بتوقيت مكة)", parse_mode="MarkdownV2")
    except ValueError:
        await update.message.reply_text("❌ صيغة التاريخ أو الوقت غير صحيحة!", parse_mode="MarkdownV2")

async def set_log_channel_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args
    if not args and context.user_data.get('state') == UserState.WAITING_LOG_CHANNEL:
        identifier = context.user_data.get('temp_log_channel_identifier')
        if identifier:
            args = [identifier]
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/set_log_channel معرف_القناة`\n\nمثال: `/set_log_channel -1001234567890`\nأو `/set_log_channel @username`", parse_mode="MarkdownV2")
        return
    identifier = args[0].strip()
    if identifier.startswith('@'):
        identifier = identifier[1:]
    try:
        if identifier.startswith('-100') or identifier.lstrip('-').isdigit():
            chat_id = int(identifier)
        else:
            chat = await context.bot.get_chat(f"@{identifier}")
            chat_id = chat.id
    except Exception as e:
        await update.message.reply_text(f"❌ لا يمكن العثور على القناة: {str(e)[:100]}", parse_mode="MarkdownV2")
        return
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if bot_member.status not in ['administrator', 'creator']:
            await update.message.reply_text("❌ **البوت ليس مشرفاً في هذه القناة.**", parse_mode="MarkdownV2")
            return
        if not bot_member.can_post_messages:
            await update.message.reply_text("❌ **البوت لا يملك صلاحية الإرسال.**", parse_mode="MarkdownV2")
            return
    except Exception as e:
        await update.message.reply_text(f"❌ لا يمكن الوصول للقناة: {str(e)[:100]}", parse_mode="MarkdownV2")
        return
    await db_set_log_channel_id(str(chat_id))
    await update.message.reply_text(f"✅ **تم تعيين قناة التقارير بنجاح!**\nمعرف القناة: `{chat_id}`", parse_mode="MarkdownV2")
    try:
        await context.bot.send_message(chat_id, "✅ **تم تفعيل نظام التقارير**")
    except:
        pass
    context.user_data.pop('state', None)
    context.user_data.pop('temp_log_channel_identifier', None)

async def set_rules_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = chat.id
    user_id = user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args
    if not args:
        await update.message.reply_text(
            "📝 **تعيين قوانين المجموعة**\n\n"
            "استخدم الأمر مع النص المراد تعيينه كقوانين:\n"
            "`/set_rules نص القوانين`\n\n"
            "📌 مثال:\n"
            "`/set_rules 1- احترام الأعضاء\n2- عدم إرسال روابط\n3- الالتزام بالآداب العامة`"
        )
        return
    rules_text = " ".join(args)
    rules_text = sanitize_text(rules_text, max_length=4000)
    async def _set_rules(conn):
        await conn.execute(
            "INSERT OR REPLACE INTO group_rules (chat_id, rules_text, set_by, set_at) VALUES (?, ?, ?, ?)",
            (chat_id, rules_text, user_id, utc_now_iso())
        )
        await conn.commit()
    await execute_db(_set_rules)
    await update.message.reply_text(
        f"✅ **تم تعيين قوانين المجموعة بنجاح!**\n\n"
        f"📌 لعرض القوانين استخدم الأمر `/rules`",
        parse_mode="MarkdownV2"
    )

async def rules_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = chat.id
    async def _get_rules(conn):
        cur = await conn.execute(
            "SELECT rules_text, set_by, set_at FROM group_rules WHERE chat_id=?",
            (chat_id,)
        )
        return await cur.fetchone()
    rules_data = await execute_db(_get_rules)
    if not rules_data or not rules_data[0]:
        await update.message.reply_text(
            "📜 **لا توجد قوانين مسجلة لهذه المجموعة.**\n\n"
            "يمكن للمشرفين تعيين القوانين باستخدام:\n"
            "`/set_rules نص القوانين`"
        )
        return
    rules_text = rules_data[0]
    set_by = rules_data[1]
    set_at = rules_data[2]
    try:
        set_at_dt = datetime.fromisoformat(set_at)
        set_at_mecca = utc_to_mecca(set_at_dt)
        set_at_str = set_at_mecca.strftime("%Y-%m-%d %H:%M")
    except:
        set_at_str = set_at[:16] if set_at else "تاريخ غير معروف"
    message = f"📜 **قوانين المجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\n\n{rules_text}\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
    message += f"📌 تم التعيين بواسطة: `{set_by}`\n"
    message += f"🕐 التاريخ: {set_at_str}"
    await safe_send_markdown(context.bot, chat_id, message)

# ===================== معالجات المالك والمشرفين المخفيين =====================
async def register_hidden_owner_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        admin_ids = [admin.user.id for admin in admins]
        if user_id not in admin_ids:
            await update.message.reply_text("❌ **أنت لست مشرفاً في هذه المجموعة!**")
            return
    except:
        await update.message.reply_text("❌ **لا يمكن التحقق من صلاحياتك، تأكد من أن البوت مشرف.**")
        return
    await db_register_hidden_owner_group(chat_id, user_id)
    await update.message.reply_text("✅ **تم تسجيلك كمالك مخفي للمجموعة!**")

async def add_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/add_hidden_admin معرف_المستخدم`")
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح")
        return
    if await db_add_hidden_admin(chat_id, target_id, user_id):
        await update.message.reply_text(f"✅ تم إضافة المشرف المخفي `{target_id}` بنجاح")
    else:
        await update.message.reply_text("❌ فشل الإضافة")

async def remove_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/remove_hidden_admin معرف_المستخدم`")
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح")
        return
    if await db_remove_hidden_admin(chat_id, target_id):
        await update.message.reply_text(f"✅ تم إزالة المشرف المخفي `{target_id}` بنجاح")
    else:
        await update.message.reply_text("❌ فشل الإزالة")

async def list_hidden_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    admins = await db_get_hidden_admins(chat_id)
    if not admins:
        await update.message.reply_text("📭 لا يوجد مشرفين مخفيين في هذه المجموعة")
        return
    text = "🔒 **قائمة المشرفين المخفيين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for admin in admins:
        text += f"• `{admin['admin_id']}` (أضيف بواسطة `{admin['added_by']}` في {admin['added_at'][:10]})\n"
    await safe_send_markdown(context.bot, user_id, text)

# ===================== معالجات الكولباك الأساسية =====================
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    kb, title, active_channel = await get_main_keyboard(uid)
    if active_channel:
        context.user_data['active_channel'] = active_channel
        await db_set_active_channel(uid, active_channel)
    if query:
        await safe_edit_markdown(query, title, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, title, reply_markup=kb)

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu_callback(update, context)

async def cancel_session_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    context.user_data.pop(f"session_{uid}", None)
    context.user_data.pop(f"session_target_{uid}", None)
    context.user_data.pop('state', None)
    if query:
        await query.edit_message_text("❌ تم الإلغاء")
    else:
        await context.bot.send_message(chat_id=uid, text="❌ تم الإلغاء")
    await main_menu_callback(update, context)

async def add_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_CHANNEL_ID
    msg = "📡 أرسل معرف القناة (مثال: @RelaxMgrr أو -100123456)"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def my_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    channels = await db_get_channels(uid)
    if not channels:
        msg = "📭 لا توجد قنوات مسجلة"
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return
    kb = []
    for ch in channels:
        ch_db_id, ch_tele_id, ch_name, banned = ch
        display = ch_name if ch_name != ch_tele_id else ch_tele_id
        kb.append([
            InlineKeyboardButton(f"📢 {display}", callback_data=f"{CallbackData.CHANNELS_SELECT_PREFIX}{ch_db_id}"),
            InlineKeyboardButton("📊 إحصائيات", callback_data=f"{CallbackData.CHANNEL_STATS}:{ch_db_id}"),
            InlineKeyboardButton("🗑️ حذف", callback_data=f"{CallbackData.CHANNELS_DELETE_PREFIX}{ch_db_id}")
        ])
    kb.append([InlineKeyboardButton("➕ إضافة قناة", callback_data=CallbackData.CHANNELS_ADD)])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    if query:
        await query.edit_message_text("📡 **قنواتي**\nاختر قناة للتحكم بها:", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await safe_send_markdown(context.bot, uid, "📡 **قنواتي**\nاختر قناة للتحكم بها:", reply_markup=InlineKeyboardMarkup(kb))

async def delete_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('delete_channel_id')
    if not ch_db_id:
        return
    if await db_delete_channel_by_id(uid, ch_db_id):
        if query:
            await query.edit_message_text("✅ تم حذف القناة")
        else:
            await update.message.reply_text("✅ تم حذف القناة")
        await my_channels_callback(update, context)
    else:
        if query:
            await query.answer("❌ فشل الحذف", show_alert=True)
        else:
            await update.message.reply_text("❌ فشل الحذف")

async def select_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    await db_set_active_channel(uid, ch_db_id)
    context.user_data['active_channel'] = ch_db_id
    invalidate_user_cache(uid)
    kb, title, new_active = await get_main_keyboard(uid)
    if new_active:
        context.user_data['active_channel'] = new_active
    if query:
        await safe_edit_markdown(query, title, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, title, reply_markup=kb)

async def add_15_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
        return
    unpublished_count = await db_unpublished_count(active)
    if unpublished_count >= MAX_UNPUBLISHED_POSTS:
        if query:
            await query.edit_message_text(f"⚠️ لقد تجاوزت الحد الأقصى للمنشورات غير المنشورة ({MAX_UNPUBLISHED_POSTS}).\nقم بنشر بعض المنشورات أولاً.")
        else:
            await update.message.reply_text(f"⚠️ لقد تجاوزت الحد الأقصى للمنشورات غير المنشورة ({MAX_UNPUBLISHED_POSTS}).\nقم بنشر بعض المنشورات أولاً.")
        return
    context.user_data[f"session_{uid}"] = []
    context.user_data[f"session_target_{uid}"] = min(15, MAX_UNPUBLISHED_POSTS - unpublished_count)
    context.user_data['state'] = UserState.ADDING_POSTS
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.CANCEL_SESSION)]])
    msg = f"📥 أرسل المنشورات (نصوص أو صور أو فيديوهات أو مستندات)\nالحد الأقصى المسموح: {MAX_UNPUBLISHED_POSTS - unpublished_count} منشور"
    if query:
        await query.edit_message_text(msg, reply_markup=cancel_kb)
    else:
        await update.message.reply_text(msg, reply_markup=cancel_kb)

async def publish_one_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
        return
    post = await db_get_next_post(active)
    if not post:
        if query:
            await query.edit_message_text("📭 لا توجد منشورات")
        else:
            await update.message.reply_text("📭 لا توجد منشورات")
        return
    ch_info = await db_get_channel_info(active)
    translation_lang = await get_user_translation_language(uid)
    final_text = post['text']
    if translation_lang != 'off' and final_text:
        try:
            translated = await translate_text(final_text, translation_lang)
            if translated and translated != final_text:
                final_text = f"{final_text}\n\n🌐 {translated}"
        except:
            pass
    try:
        if post['media_type'] == 'photo' and post['media_file_id']:
            await context.bot.send_photo(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'video' and post['media_file_id']:
            await context.bot.send_video(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'document' and post['media_file_id']:
            await context.bot.send_document(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'audio' and post['media_file_id']:
            await context.bot.send_audio(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'voice' and post['media_file_id']:
            await context.bot.send_voice(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'animation' and post['media_file_id']:
            await context.bot.send_animation(ch_info['channel_id'], post['media_file_id'], caption=final_text if final_text else None)
        else:
            await context.bot.send_message(ch_info['channel_id'], final_text, parse_mode=None)
        await db_mark_published(post['id'])
        await db_set_last_publish(active, utc_now())
        await db_update_next_publish_date(active)
        if query:
            await query.edit_message_text("✅ تم نشر المنشور")
        else:
            await update.message.reply_text("✅ تم نشر المنشور")
    except Exception as e:
        if query:
            await query.edit_message_text(f"❌ فشل النشر: {str(e)[:100]}")
        else:
            await update.message.reply_text(f"❌ فشل النشر: {str(e)[:100]}")
    await main_menu_callback(update, context)

async def my_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
        return
    posts = await db_get_user_posts_for_channel(active, limit=15)
    if not posts:
        if query:
            await query.edit_message_text("📭 لا توجد منشورات")
        else:
            await update.message.reply_text("📭 لا توجد منشورات")
        return
    msg = "📋 **منشوراتي غير المنشورة**\n"
    kb_buttons = []
    for idx, (pid, ptext, media_type) in enumerate(posts[:10], 1):
        short = re.sub('<[^>]+>', '', ptext)[:80]
        media_icon = "🖼️" if media_type == 'photo' else "🎬" if media_type == 'video' else "📝" if media_type == 'text' else "📄"
        msg += f"{idx}. {media_icon} {short}...\n🆔 {pid}\n\n"
        kb_buttons.append([InlineKeyboardButton(f"🗑️ حذف #{pid}", callback_data=f"{CallbackData.POSTS_DELETE_SINGLE_PREFIX}{pid}_{active}")])
    kb_buttons.append([InlineKeyboardButton("🗑️ حذف الكل", callback_data=f"{CallbackData.POSTS_CONFIRM_CLEAR_ALL_PREFIX}{active}")])
    kb_buttons.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    if query:
        await safe_edit_markdown(query, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))
    else:
        await safe_send_markdown(context.bot, uid, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))

async def delete_single_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    parts = query.data.split(":")[-1].split("_")
    if len(parts) >= 2:
        post_id = int(parts[0])
        active = int(parts[1])
        if await db_delete_single_post(post_id, uid, active):
            if query:
                await query.answer("✅ تم حذف المنشور", show_alert=True)
            else:
                await update.message.reply_text("✅ تم حذف المنشور")
            await my_posts_callback(update, context)
        else:
            if query:
                await query.answer("❌ فشل الحذف", show_alert=True)
            else:
                await update.message.reply_text("❌ فشل الحذف")

async def confirm_clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = int(query.data.split(":")[-1]) if query else context.user_data.get('clear_all_posts_id')
    if not active:
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم", callback_data=f"{CallbackData.POSTS_CLEAR_ALL_PREFIX}{active}"),
         InlineKeyboardButton("❌ لا", callback_data=CallbackData.BACK)]
    ])
    if query:
        await query.edit_message_text("⚠️ هل أنت متأكد من حذف جميع المنشورات؟", reply_markup=kb)
    else:
        await update.message.reply_text("⚠️ هل أنت متأكد من حذف جميع المنشورات؟", reply_markup=kb)

async def clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = int(query.data.split(":")[-1]) if query else context.user_data.get('clear_all_posts_id')
    if not active:
        return
    async def _clear_posts(conn):
        await conn.execute("DELETE FROM posts WHERE channel_db_id=?", (active,))
        await conn.commit()
    await execute_db(_clear_posts)
    if query:
        await query.answer("✅ تم حذف جميع المنشورات", show_alert=True)
    else:
        await update.message.reply_text("✅ تم حذف جميع المنشورات")
    await main_menu_callback(update, context)

async def recycle_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if active:
        await db_reset_posts_to_unpublished(active, uid)
        if query:
            await query.edit_message_text("♻️ تم إعادة تدوير جميع المنشورات")
        else:
            await update.message.reply_text("♻️ تم إعادة تدوير جميع المنشورات")
    else:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
    await main_menu_callback(update, context)

async def my_pending_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    unpublished = await db_get_user_unpublished_posts(uid)
    total = await db_get_user_total_posts(uid)
    text = f"📊 **إحصائيات المنشورات**\n━━━━━━━━━━━━━━━━━━━━━━\n📝 غير المنشورة: {unpublished}\n📋 الإجمالي: {total}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def my_full_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    channels = await db_get_user_channels_count(uid)
    total = await db_get_user_total_posts(uid)
    unpublished = await db_get_user_unpublished_posts(uid)
    groups = await db_get_user_groups_count(uid)
    auto = "مفعل" if await db_auto_status(uid) else "معطل"
    text = f"📈 **إحصائياتي الكاملة**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 القنوات: {channels}\n📝 إجمالي المنشورات: {total}\n⏳ غير المنشورة: {unpublished}\n👥 المجموعات: {groups}\n⚙️ النشر التلقائي: {auto}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def my_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    groups = await db_get_user_groups(uid)
    if not groups:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
            [InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        msg = "📭 لا توجد مجموعات مسجلة\n\nأضف البوت إلى مجموعة وستظهر هنا."
        if query:
            await safe_edit_markdown(query, msg, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, msg, reply_markup=kb)
        return
    keyboard = []
    for chat_id, chat_name, username, banned in groups:
        display_name = chat_name[:28] + "..." if len(chat_name) > 31 else chat_name
        status_icon = "⛔" if banned else "✅"
        keyboard.append([
            InlineKeyboardButton(
                f"{status_icon} {display_name}",
                callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}"
            )
        ])
        keyboard.append([
            InlineKeyboardButton("🔐 الأمان", callback_data=f"{CallbackData.SECURITY_SELECT_GROUP}{chat_id}"),
            InlineKeyboardButton("📜 السجل", callback_data=f"{CallbackData.GROUP_ACTION_LOG}:{chat_id}"),
            InlineKeyboardButton("⚙️ متقدم", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}")
        ])
        is_locked = await is_chat_locked(chat_id)
        lock_label = "🔒 قفل" if not is_locked else "🔓 فتح"
        lock_callback = f"{CallbackData.PANEL_LOCK_PREFIX}{chat_id}" if not is_locked else f"{CallbackData.PANEL_UNLOCK_PREFIX}{chat_id}"
        keyboard.append([
            InlineKeyboardButton(lock_label, callback_data=lock_callback),
            InlineKeyboardButton("🗑️ حذف", callback_data=f"delete_group:{chat_id}")
        ])
        keyboard.append([InlineKeyboardButton("─" * 20, callback_data="noop")])
    keyboard.append([
        InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS),
        InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "👥 **مجموعاتي**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر مجموعة للتحكم بها:\n\n✅ = نشطة  |  ⛔ = محظورة"
    if query:
        await safe_edit_markdown(query, text, reply_markup=reply_markup)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=reply_markup)

async def delete_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('delete_group_id')
    if not chat_id:
        return
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer("❌ غير مصرح", show_alert=True)
        else:
            await update.message.reply_text("❌ غير مصرح")
        return
    async def _delete_group(conn):
        await conn.execute("DELETE FROM bot_groups WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM user_groups_link WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM group_security WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM chat_locks WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM moderation_log WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM group_admins WHERE chat_id = ?", (chat_id,))
        await conn.commit()
    await execute_db(_delete_group)
    if query:
        await query.edit_message_text("✅ تم حذف المجموعة من قاعدة البيانات.")
    else:
        await update.message.reply_text("✅ تم حذف المجموعة من قاعدة البيانات.")
    await my_groups_callback(update, context)

async def group_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('group_chat_id')
    if not chat_id:
        if query:
            await query.edit_message_text("❌ لم يتم تحديد المجموعة")
        else:
            await context.bot.send_message(chat_id=uid, text="❌ لم يتم تحديد المجموعة")
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        else:
            await context.bot.send_message(chat_id=uid, text="🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    async def _get_group_name(conn):
        async with conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            if row and row[0]:
                name = row[0]
                if len(name) > 50:
                    name = name[:47] + "..."
                return name
            return str(chat_id)
    gname = await execute_db(_get_group_name)
    text = f"⚙️ **لوحة تحكم المجموعة: {gname}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🔗 حذف الروابط: {'✅' if settings.get('links', False) else '❌'}\n"
    text += f"@ حذف المعرفات: {'✅' if settings.get('mentions', False) else '❌'}\n"
    text += f"🚫 كلمات محظورة: {'✅' if settings.get('delete_banned_words', False) else '❌'}\n"
    text += f"⏱️ وضع بطيء: {'✅' if settings.get('slow_mode', False) else '❌'}\n"
    text += f"🎯 رسالة ترحيب: {'✅' if settings.get('welcome_enabled', False) else '❌'}\n"
    text += f"👋 رسالة وداع: {'✅' if settings.get('goodbye_enabled', False) else '❌'}\n"
    text += f"🎴 حذف الملصقات: {'✅' if settings.get('delete_stickers', False) else '❌'}\n"
    text += f"🎬 حذف الفيديوهات: {'✅' if settings.get('delete_videos', False) else '❌'}\n"
    text += f"📨 حذف رسائل الخدمة: {'✅' if settings.get('delete_service_messages', False) else '❌'}\n"
    text += f"🔊 رسالة تحذير: {'✅' if settings.get('warn', True) else '❌'}\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    penalty = settings.get('auto_penalty', 'none')
    if penalty == 'kick':
        penalty_text = "طرد"
    elif penalty == 'ban':
        penalty_text = "حظر"
    elif penalty == 'mute':
        penalty_text = "كتم"
    else:
        penalty_text = "لا شيء"
    text += f"⚖️ **العقوبة التلقائية:** {penalty_text}\n"
    if penalty == 'mute':
        minutes = settings.get('auto_mute_duration', 60)
        if minutes == -1:
            text += f"   مدة الكتم: دائم\n"
        elif minutes < 60:
            text += f"   مدة الكتم: {minutes} دقيقة\n"
        elif minutes < 1440:
            text += f"   مدة الكتم: {minutes // 60} ساعة\n"
        else:
            text += f"   مدة الكتم: {minutes // 1440} يوم\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📌 **اختر الإجراء المناسب:**"
    if query:
        await safe_edit_markdown(query, text, reply_markup=security_keyboard(chat_id))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=security_keyboard(chat_id))

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    auto = await db_auto_status(uid)
    auto_btn = "❌ تعطيل" if auto else "✅ تفعيل"
    recycle = await db_get_auto_recycle(uid)
    recycle_btn = "✅ مفعل" if recycle else "❌ معطل"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{auto_btn} النشر التلقائي", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH)],
        [InlineKeyboardButton(f"♻️ إعادة التدوير: {recycle_btn}", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_RECYCLE)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await query.edit_message_text("⚙️ **الإعدادات**\nاختر الإعداد المطلوب:", reply_markup=kb)
    else:
        await update.message.reply_text("⚙️ **الإعدادات**\nاختر الإعداد المطلوب:", reply_markup=kb)

async def toggle_auto_publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    cur = await db_auto_status(uid)
    await db_set_auto(uid, not cur)
    status = "مفعل" if not cur else "معطل"
    if query:
        await query.edit_message_text(f"✅ تم تغيير حالة النشر التلقائي إلى: {status}")
    else:
        await update.message.reply_text(f"✅ تم تغيير حالة النشر التلقائي إلى: {status}")
    await main_menu_callback(update, context)

async def toggle_auto_recycle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    cur = await db_get_auto_recycle(uid)
    new_status = not cur
    await db_set_auto_recycle(uid, new_status)
    status = "مفعل" if new_status else "معطل"
    if query:
        await query.edit_message_text(f"✅ تم تغيير إعادة التدوير التلقائي إلى: {status}")
    else:
        await update.message.reply_text(f"✅ تم تغيير إعادة التدوير التلقائي إلى: {status}")
    await settings_menu_callback(update, context)

# ===================== معالجات الكولباك للجدولة =====================
async def schedule_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    parts = query.data.split(":") if query else context.user_data.get('schedule_data', '').split(":")
    if len(parts) >= 3:
        ch_db_id = int(parts[-1])
    else:
        ch_db_id = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not ch_db_id:
        if query:
            await query.edit_message_text("⚠️ يرجى اختيار قناة أولاً")
        else:
            await update.message.reply_text("⚠️ يرجى اختيار قناة أولاً")
        return
    schedule = await db_get_schedule(ch_db_id)
    if schedule['type'] == 'interval_minutes':
        txt = f"دقائق: {schedule['interval_minutes']}"
    elif schedule['type'] == 'interval_hours':
        txt = f"ساعات: {schedule['interval_hours']}"
    elif schedule['type'] == 'interval_days':
        txt = f"أيام: {schedule['interval_days']}"
    elif schedule['type'] == 'days':
        days = parse_days_of_week_safe(schedule['days_of_week'])
        day_names = ['الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
        txt = f"أيام الأسبوع: {', '.join([day_names[d] for d in days]) if days else 'لا شيء'}"
    elif schedule['type'] == 'cron':
        txt = f"⏰ CRON: {schedule.get('cron_expression', 'غير محدد')}"
    else:
        dates = parse_dates_safe(schedule['specific_dates'])
        txt = f"تواريخ محددة: {', '.join(dates) if dates else 'لا شيء'}"
    pub_time = schedule.get('publish_time', '00:00')
    txt += f"\n🕐 وقت النشر: {pub_time} (بتوقيت مكة)"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 دقائق", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_MINUTES_PREFIX}{ch_db_id}"),
         InlineKeyboardButton("🕒 ساعات", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_HOURS_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton("📆 أيام", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_DAYS_PREFIX}{ch_db_id}"),
         InlineKeyboardButton("📅 أيام أسبوع", callback_data=f"{CallbackData.SCHEDULE_SET_DAYS_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton("🗓️ تواريخ محددة", callback_data=f"{CallbackData.SCHEDULE_SET_DATES_PREFIX}{ch_db_id}"),
         InlineKeyboardButton("⏰ وقت النشر", callback_data=f"{CallbackData.SCHEDULE_SET_PUBLISH_TIME_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton("⏱️ CRON", callback_data=f"schedule:set_cron:{ch_db_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    text = f"⏰ **إعدادات الجدولة**\n━━━━━━━━━━━━━━━━━━━━━━\n{txt}\n━━━━━━━━━━━━━━━━━━━━━━\nاختر نوع الجدولة:"
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def set_interval_minutes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = UserState.WAITING_INTERVAL_MINUTES
    context.user_data['schedule_ch_id'] = ch_db_id
    if query:
        await query.edit_message_text("⏱️ أرسل عدد الدقائق (مثال: 30)")
    else:
        await update.message.reply_text("⏱️ أرسل عدد الدقائق (مثال: 30)")

async def set_interval_hours_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = UserState.WAITING_INTERVAL_HOURS
    context.user_data['schedule_ch_id'] = ch_db_id
    if query:
        await query.edit_message_text("⏱️ أرسل عدد الساعات (مثال: 2)")
    else:
        await update.message.reply_text("⏱️ أرسل عدد الساعات (مثال: 2)")

async def set_interval_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = UserState.WAITING_INTERVAL_DAYS
    context.user_data['schedule_ch_id'] = ch_db_id
    if query:
        await query.edit_message_text("⏱️ أرسل عدد الأيام (مثال: 1)")
    else:
        await update.message.reply_text("⏱️ أرسل عدد الأيام (مثال: 1)")

async def set_cron_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = UserState.WAITING_INTERVAL_MINUTES
    context.user_data['schedule_ch_id'] = ch_db_id
    context.user_data['schedule_cron'] = True
    msg = "⏱️ **إعداد CRON**\n\nأرسل تعبير CRON (مثال: `0 12 * * *` للنشر يومياً الساعة 12:00)\n\nالشرح:\n• دقيقة (0-59)\n• ساعة (0-23)\n• يوم (1-31)\n• شهر (1-12)\n• يوم أسبوع (0-6)"
    if query:
        await query.edit_message_text(msg, parse_mode="MarkdownV2")
    else:
        await update.message.reply_text(msg, parse_mode="MarkdownV2")

async def set_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['selected_days_ch'] = ch_db_id
    context.user_data['selected_days'] = []
    context.user_data['state'] = UserState.SELECTING_DAYS
    if query:
        await query.edit_message_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(uid, context))
    else:
        await update.message.reply_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(uid, context))

async def set_dates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = UserState.WAITING_DATES
    context.user_data['schedule_ch_id'] = ch_db_id
    if query:
        await query.edit_message_text("📅 أرسل التواريخ مفصولة بفواصل (مثال: 2024-12-25,2025-01-01)")
    else:
        await update.message.reply_text("📅 أرسل التواريخ مفصولة بفواصل (مثال: 2024-12-25,2025-01-01)")

async def set_publish_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = UserState.WAITING_PUBLISH_TIME
    context.user_data['schedule_ch_id'] = ch_db_id
    if query:
        await query.edit_message_text("🕐 أرسل وقت النشر (مثال: 14:30)")
    else:
        await update.message.reply_text("🕐 أرسل وقت النشر (مثال: 14:30)")

async def day_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    day = int(query.data.split(":")[-1]) if query else context.user_data.get('selected_day')
    if day is None:
        return
    selected = context.user_data.get('selected_days', [])
    if day in selected:
        selected.remove(day)
    else:
        selected.append(day)
    context.user_data['selected_days'] = selected
    if query:
        await query.edit_message_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(uid, context))
    else:
        await update.message.reply_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(uid, context))

async def save_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch = context.user_data.get('selected_days_ch')
    if ch:
        days_json = json.dumps(context.user_data.get('selected_days', []))
        await db_save_schedule(ch, 'days', days_of_week=days_json)
        await db_set_next_publish_date(ch, None)
        context.user_data.pop('selected_days_ch', None)
        context.user_data.pop('selected_days', None)
        context.user_data.pop('state', None)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, "✅ تم حفظ أيام النشر", reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, "✅ تم حفظ أيام النشر", reply_markup=kb)
    else:
        if query:
            await query.edit_message_text("❌ حدث خطأ")
        else:
            await update.message.reply_text("❌ حدث خطأ")

# ===================== معالجات الكولباك للأمان =====================
async def security_links_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['links'] = not settings['links']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text("✅ تم التحديث")
    else:
        await update.message.reply_text("✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_mentions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['mentions'] = not settings['mentions']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text("✅ تم التحديث")
    else:
        await update.message.reply_text("✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_warn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['warn'] = not settings['warn']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text("✅ تم التحديث")
    else:
        await update.message.reply_text("✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_slowmode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['slow_mode'] = not settings['slow_mode']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text("✅ تم التحديث")
    else:
        await update.message.reply_text("✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_banned_words_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['banned_words_chat_id'] = chat_id
    msg = "🚫 إدارة الكلمات المحظورة للمجموعة"
    if query:
        await query.edit_message_text(msg, reply_markup=get_group_banned_words_keyboard(chat_id))
    else:
        await update.message.reply_text(msg, reply_markup=get_group_banned_words_keyboard(chat_id))

async def banned_words_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('banned_words_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    msg = "🚫 أرسل الكلمة التي تريد إضافتها إلى قائمة الكلمات المحظورة:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def banned_words_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('banned_words_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    words = await db_get_banned_words(chat_id)
    if not words:
        msg = "📭 لا توجد كلمات محظورة في هذه المجموعة"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]])
        if query:
            await query.edit_message_text(msg, reply_markup=kb)
        else:
            await update.message.reply_text(msg, reply_markup=kb)
        return
    msg = "🚫 **قائمة الكلمات المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for word, added_by, added_at in words[:30]:
        msg += f"• `{word}` (أضيف بواسطة `{added_by}` في {added_at[:10]})\n"
    if len(words) > 30:
        msg += f"\n... و {len(words)-30} كلمة أخرى"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]])
    if query:
        await safe_edit_markdown(query, msg, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, msg, reply_markup=kb)

async def banned_words_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('banned_words_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_REMOVE_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    msg = "🚫 أرسل الكلمة التي تريد حذفها من قائمة الكلمات المحظورة:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def security_welcome_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['welcome_enabled'] = not settings['welcome_enabled']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text("✅ تم التحديث")
    else:
        await update.message.reply_text("✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_goodbye_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['goodbye_enabled'] = not settings['goodbye_enabled']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text("✅ تم التحديث")
    else:
        await update.message.reply_text("✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_stickers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['delete_stickers'] = not settings.get('delete_stickers', False)
    await db_set_security_settings(chat_id, delete_stickers=settings['delete_stickers'])
    status_text = "🟢 مفعل" if settings['delete_stickers'] else "🔴 معطل"
    if query:
        await query.edit_message_text(f"✅ حذف الملصقات: {status_text}")
    else:
        await update.message.reply_text(f"✅ حذف الملصقات: {status_text}")
    await group_settings_callback(update, context)

async def security_videos_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['delete_videos'] = not settings.get('delete_videos', False)
    await db_set_security_settings(chat_id, delete_videos=settings['delete_videos'])
    status_text = "🟢 مفعل" if settings['delete_videos'] else "🔴 معطل"
    if query:
        await query.edit_message_text(f"✅ حذف الفيديوهات: {status_text}")
    else:
        await update.message.reply_text(f"✅ حذف الفيديوهات: {status_text}")
    await group_settings_callback(update, context)

async def security_service_messages_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['delete_service_messages'] = not settings.get('delete_service_messages', False)
    await db_set_security_settings(chat_id, delete_service_messages=settings['delete_service_messages'])
    status_text = "🟢 مفعل" if settings['delete_service_messages'] else "🔴 معطل"
    if query:
        await query.edit_message_text(f"✅ حذف رسائل الخدمة: {status_text}")
    else:
        await update.message.reply_text(f"✅ حذف رسائل الخدمة: {status_text}")
    await group_settings_callback(update, context)

async def security_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.delete()

async def security_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_GROUP_SECURITY
    msg = "🔐 **إعدادات الأمان**\n\nاختر الإعداد المطلوب"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def security_select_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        error_text = """❌ **غير مصرح**
أنت لست مشرفاً في هذه المجموعة، أو البوت ليس مشرفاً.
تأكد من:
1. أن البوت مشرف في المجموعة
2. أن لديك صلاحيات مشرف في المجموعة"""
        if query:
            await safe_edit_markdown(query, error_text)
        else:
            await update.message.reply_text(error_text)
        return
    settings = await db_get_security_settings(chat_id)
    async def _get_group_name(conn):
        async with conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            name = row[0] if row else str(chat_id)
            if len(name) > 50:
                name = name[:47] + "..."
            return name
    gname = await execute_db(_get_group_name)
    text = f"""⚙️ **لوحة تحكم المجموعة: {gname}**
━━━━━━━━━━━━━━━━━━━━━━
🔗 حذف الروابط: {'✅' if settings['links'] else '❌'}
@ حذف المعرفات: {'✅' if settings['mentions'] else '❌'}
🚫 كلمات محظورة: {'✅' if settings.get('delete_banned_words', False) else '❌'}
🎴 حذف الملصقات: {'✅' if settings.get('delete_stickers', False) else '❌'}
🎬 حذف الفيديوهات: {'✅' if settings.get('delete_videos', False) else '❌'}
📨 حذف رسائل الخدمة: {'✅' if settings.get('delete_service_messages', False) else '❌'}
⏱️ وضع بطيء: {'✅' if settings['slow_mode'] else '❌'}
🎯 ترحيب: {'✅' if settings['welcome_enabled'] else '❌'}
👋 وداع: {'✅' if settings['goodbye_enabled'] else '❌'}
🔊 تحذير: {'✅' if settings['warn'] else '❌'}
━━━━━━━━━━━━━━━━━━━━━━
⚖️ **العقوبة التلقائية:** {'طرد' if settings.get('auto_penalty') == 'kick' else 'حظر' if settings.get('auto_penalty') == 'ban' else 'كتم' if settings.get('auto_penalty') == 'mute' else 'لا شيء'}
━━━━━━━━━━━━━━━━━━━━━━
💡 **اختر الإجراء المناسب:**"""
    if query:
        await safe_edit_markdown(query, text, reply_markup=security_keyboard(chat_id))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=security_keyboard(chat_id))

async def security_refresh_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    groups = await db_get_user_groups(uid)
    if not groups:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ أضف البوت إلى مجموعة", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
            [InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        text = """🔐 **إعدادات الأمان**
⚠️ لم يتم العثور على مجموعات.
📌 **لتفعيل إعدادات الأمان والإجراءات المتقدمة:**
1. أضف البوت إلى مجموعتك
2. اجعل البوت مشرفاً
3. استخدم الأمر /syncgroup في المجموعة
4. ثم عد إلى الخاص واضغط على تحديث
5. إذا كنت مالكاً مخفياً، استخدم الأمر /register_hidden_owner في المجموعة"""
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)
        return
    keyboard = []
    for group in groups:
        chat_id, chat_name, username, banned = group
        name = chat_name[:40] + "..." if len(chat_name) > 43 else chat_name
        keyboard.append([InlineKeyboardButton(f"📌 {name}", callback_data=f"{CallbackData.SECURITY_SELECT_GROUP}{chat_id}")])
    keyboard.append([InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    text = """🔐 **إعدادات الأمان والإجراءات المتقدمة**
📌 اختر المجموعة التي تريد إدارة إعداداتها:
⚠️ ملاحظة: يجب أن يكون البوت مشرفاً في المجموعة
🔒 للمالك المخفي: استخدم /register_hidden_owner في المجموعة أولاً"""
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=InlineKeyboardMarkup(keyboard))

# ===================== معالجات الكولباك للعقوبات =====================
async def penalty_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    msg = "⚖️ **اختر العقوبة التلقائية:**\n\nسيتم تطبيق هذه العقوبة عند مخالفة قواعد الحماية:"
    if query:
        await query.edit_message_text(msg, reply_markup=penalty_keyboard(chat_id))
    else:
        await update.message.reply_text(msg, reply_markup=penalty_keyboard(chat_id))

async def penalty_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    await db_set_security_settings(chat_id, auto_penalty='kick')
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    if query:
        await query.edit_message_text("✅ تم تعيين العقوبة التلقائية إلى: **طرد**", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم تعيين العقوبة التلقائية إلى: **طرد**", reply_markup=kb)

async def penalty_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    await db_set_security_settings(chat_id, auto_penalty='ban')
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    if query:
        await query.edit_message_text("✅ تم تعيين العقوبة التلقائية إلى: **حظر**", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم تعيين العقوبة التلقائية إلى: **حظر**", reply_markup=kb)

async def penalty_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['penalty_chat_id'] = chat_id
    msg = "🔇 **اختر مدة الكتم:**"
    if query:
        await query.edit_message_text(msg, reply_markup=mute_duration_keyboard(chat_id))
    else:
        await update.message.reply_text(msg, reply_markup=mute_duration_keyboard(chat_id))

async def penalty_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    data_parts = query.data.split(":") if query else context.user_data.get('penalty_mute_data', '').split(":")
    if len(data_parts) == 3:
        duration = data_parts[1]
        chat_id = int(data_parts[2])
        uid = update.effective_user.id
        if not await is_authorized_in_group(context.bot, chat_id, uid):
            if query:
                await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
            else:
                await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
            return
        if duration == "permanent":
            minutes = -1
            text = "دائم"
        else:
            minutes = int(duration)
            if minutes < 60:
                text = f"{minutes} دقيقة"
            elif minutes < 1440:
                text = f"{minutes // 60} ساعة"
            else:
                text = f"{minutes // 1440} يوم"
        await db_set_security_settings(chat_id, auto_penalty='mute', auto_mute_duration=minutes)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
        if query:
            await query.edit_message_text(f"✅ تم تعيين العقوبة التلقائية إلى: **كتم {text}**", reply_markup=kb)
        else:
            await update.message.reply_text(f"✅ تم تعيين العقوبة التلقائية إلى: **كتم {text}**", reply_markup=kb)

# ===================== معالجات الكولباك للدعم والمساعدة =====================
async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    text = """❓ **المساعدة**
━━━━━━━━━━━━━━━━━━━━━━
📌 **الأوامر المتاحة:**
/start - القائمة الرئيسية
/trial - تجربة مجانية
/subscribe - الاشتراك
/syncgroup - تفعيل المجموعة
/security - إعدادات الأمان
/register_hidden_owner - تسجيل مالك مخفي
/add_hidden_admin - إضافة مشرف مخفي
/remove_hidden_admin - إزالة مشرف مخفي
/list_hidden_admins - عرض المشرفين المخفيين
/rank - رتبتك
/top - أفضل 10
/stats - إحصائيات القناة
/lock - قفل المجموعة
/unlock - فتح المجموعة
/schedule - جدولة منشور
/panel - لوحة التحكم
/language - تغيير اللغة
/support - مركز الدعم
/help - هذه المساعدة
/developer - المطور
/updates - التحديثات
/contests - المسابقات
/create_contest - إنشاء مسابقة
/declare_winner - إعلان فائز
/set_rules - تعيين قوانين المجموعة
/rules - عرض قوانين المجموعة"""
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def support_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 كتابة تذكرة", callback_data=CallbackData.SUPPORT_TICKET)],
        [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    text = "📞 **مركز الدعم**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الخدمة المطلوبة:"
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def support_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.SUPPORT_MENU)]
    ])
    text = """❓ **المساعدة**
━━━━━━━━━━━━━━━━━━━━━━
📌 للتواصل مع الدعم:
• استخدم /support
• اكتب رسالتك
• ستصلك تذكرة برقم
• سنرد عليك بأسرع وقت

📌 للمشاكل التقنية:
• تأكد من أن البوت مشرف
• تأكد من صلاحيات البوت
• راجع إعدادات الأمان"""
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def support_ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 إلغاء", callback_data=CallbackData.SUPPORT_MENU)]
    ])
    text = "📝 **اكتب رسالتك** (سيتم إرسالها كتذكرة دعم)\nيمكنك إلغاء العملية بالضغط على الزر أدناه."
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def support_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await support_menu_callback(update, context)

# ===================== معالجات الكولباك للتجربة والاشتراك =====================
async def trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if await db_has_used_trial(uid):
        if query:
            await query.edit_message_text("❌ لقد استخدمت التجربة المجانية مسبقاً")
        else:
            await update.message.reply_text("❌ لقد استخدمت التجربة المجانية مسبقاً")
        return
    if await db_has_active_subscription(uid):
        if query:
            await query.edit_message_text("✅ لديك اشتراك فعال بالفعل")
        else:
            await update.message.reply_text("✅ لديك اشتراك فعال بالفعل")
        return
    await db_activate_trial(uid)
    if query:
        await query.edit_message_text("🎁 **تم تفعيل التجربة المجانية!**\n━━━━━━━━━━━━━━━━━━━━━━\n✅ لديك 30 يوماً مجاناً\n📌 استمتع بجميع الميزات\n💎 يمكنك الاشتراك بعد انتهاء التجربة")
    else:
        await update.message.reply_text("🎁 **تم تفعيل التجربة المجانية!**\n━━━━━━━━━━━━━━━━━━━━━━\n✅ لديك 30 يوماً مجاناً\n📌 استمتع بجميع الميزات\n💎 يمكنك الاشتراك بعد انتهاء التجربة")
    await main_menu_callback(update, context)

async def subscribe_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if await db_has_active_subscription(uid):
        days = await db_get_subscription_days_left(uid)
        msg = f"✅ اشتراكك مفعل، متبقي {days} يوم\nشكراً لدعمك ❤️"
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_1),
         InlineKeyboardButton("⭐ 2 يوم - 9 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_2)],
        [InlineKeyboardButton("⭐ شهر (30 يوم) - 50 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_30),
         InlineKeyboardButton("⭐ 3 أشهر (90 يوم) - 120 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_90)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    text = "💎 **الاشتراك**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الباقة المناسبة لك:\n\n⭐ 1 يوم - 5 نجوم\n⭐ 2 يوم - 9 نجوم\n⭐ شهر (30 يوم) - 50 نجمة\n⭐ 3 أشهر (90 يوم) - 120 نجمة\n\n📌 الدفع عبر نجوم تيليجرام"
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)

async def buy_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int, price: int, title: str):
    query = update.callback_query
    user_id = update.effective_user.id
    try:
        await context.bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=f"اشتراك {days} يوم",
            payload=f"sub_{days}_{price}",
            currency="XTR",
            prices=[LabeledPrice(label=f"اشتراك {days} يوم", amount=price)],
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            is_flexible=False
        )
    except Exception as e:
        if "Stars" in str(e):
            if query:
                await query.edit_message_text("❌ الدفع بالنجوم غير مفعل حالياً، استخدم /trial")
            else:
                await update.message.reply_text("❌ الدفع بالنجوم غير مفعل حالياً، استخدم /trial")
        else:
            if query:
                await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}")
            else:
                await update.message.reply_text(f"❌ خطأ: {str(e)[:100]}")

async def buy_subscription_1_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await buy_subscription_callback(update, context, 1, 5, "اشتراك 1 يوم")

async def buy_subscription_2_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await buy_subscription_callback(update, context, 2, 9, "اشتراك 2 يوم")

async def buy_subscription_30_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await buy_subscription_callback(update, context, 30, 50, "اشتراك شهر")

async def buy_subscription_90_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await buy_subscription_callback(update, context, 90, 120, "اشتراك 3 أشهر")

# ===================== معالجات الكولباك للمطور والتحديثات =====================
async def developer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ram = get_ram_usage()
    text = f"""👑 **معلومات المطور**
━━━━━━━━━━━━━━━━━━━━━━
🤖 **البوت:** {BOT_NAME}
📦 **الإصدار:** 19.3.3
👨‍💻 **المطور:** @RelaxMgr
━━━━━━━━━━━━━━━━━━━━━━
📊 **إحصائيات الأداء:**
• استخدام الرام: {ram['percent']}%"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 تواصل مع المطور", url=f"https://t.me/RelaxMgr")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    updates_channel = await db_get_updates_channel()
    if updates_channel:
        text = f"""📢 **قناة التحديثات**
━━━━━━━━━━━━━━━━━━━━━━
📌 القناة: @{updates_channel}"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 افتح القناة", url=f"https://t.me/{updates_channel}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
    else:
        text = """📢 **لم يتم تعيين قناة التحديثات بعد**"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👑 الذهاب للوحة الأدمن", callback_data=CallbackData.ADMIN_PANEL)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

# ===================== معالجات الكولباك للإحالات =====================
async def referral_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    referral_code = await db_get_referral_code(uid)
    if not referral_code:
        referral_code = await db_generate_referral_code(uid)
    stats = await db_get_referral_stats(uid)
    settings = await db_get_referral_settings()
    reward_days = safe_int(settings.get('reward_days_per_referral', '3'), 3)
    welcome_points = safe_int(settings.get('welcome_bonus_points', '10'), 10)
    text = f"🔗 **الإحالات**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 رابط الإحالة الخاص بك:\n`https://t.me/{BOT_USERNAME}?start=ref_{referral_code}`\n\n👥 عدد المحالين: {stats['total_referrals']}\n🎁 المكافآت المتاحة: {stats['available_days']} يوم\n⭐ المكافأة لكل إحالة: {reward_days} يوم\n🎁 نقاط الترحيب: {welcome_points}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 نسخ الرابط", callback_data=f"{CallbackData.REFERRAL_COPY_LINK_PREFIX}{referral_code}"),
         InlineKeyboardButton("🎁 صرف المكافآت", callback_data=CallbackData.REFERRAL_CLAIM_REWARD)],
        [InlineKeyboardButton("📋 قائمة المحالين", callback_data=CallbackData.REFERRAL_LIST),
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def referral_copy_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    referral_code = query.data.split(":")[-1] if query else context.user_data.get('referral_code')
    if not referral_code:
        return
    text = f"🔗 **رابط الإحالة الخاص بك:**\n`https://t.me/{BOT_USERNAME}?start=ref_{referral_code}`\n\nيمكنك الضغط مع الاستمرار على الرابط لنسخه."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REFERRAL_MENU)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def referral_claim_reward_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    stats = await db_get_referral_stats(uid)
    if stats['available_days'] <= 0:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REFERRAL_MENU)]])
        if query:
            await safe_edit_markdown(query, "❌ لا توجد مكافآت متاحة للصرف", reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, "❌ لا توجد مكافآت متاحة للصرف", reply_markup=kb)
        return
    claimed = await db_claim_referral_reward(uid)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REFERRAL_MENU)]])
    if query:
        await safe_edit_markdown(query, f"✅ تم صرف {claimed} يوم اشتراك!", reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, f"✅ تم صرف {claimed} يوم اشتراك!", reply_markup=kb)

async def referral_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    async def _get_referrals(conn):
        async with conn.execute("SELECT r.referred_id, r.referred_at, r.is_rewarded, u.first_name, u.username FROM referrals r LEFT JOIN users_cache u ON r.referred_id = u.user_id WHERE r.referrer_id = ? ORDER BY r.referred_at DESC LIMIT 20", (uid,)) as cur:
            return await cur.fetchall()
    referrals = await execute_db(_get_referrals)
    if not referrals:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REFERRAL_MENU)]])
        if query:
            await safe_edit_markdown(query, "📭 لا توجد إحالات بعد", reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, "📭 لا توجد إحالات بعد", reply_markup=kb)
        return
    text = f"📊 **قائمة المحالين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for referred_id, referred_at, is_rewarded, first_name, username in referrals:
        try:
            referred_dt = datetime.fromisoformat(referred_at)
            referred_mecca = utc_to_mecca(referred_dt)
            date_str = referred_mecca.strftime("%Y-%m-%d")
        except:
            date_str = referred_at[:10] if referred_at else "تاريخ غير معروف"
        status = "✅" if is_rewarded else "⏳"
        name = first_name or username or str(referred_id)
        text += f"{status} {name} - {date_str}\n"
    text += "\n✅ = تم منح المكافأة  |  ⏳ = قيد الانتظار"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎁 صرف المكافآت", callback_data=CallbackData.REFERRAL_CLAIM_REWARD)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REFERRAL_MENU)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

# ===================== معالجات الكولباك للتذكيرات =====================
async def reminder_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    settings = await db_get_user_reminder_settings(uid)
    status_sub = "🟢 مفعل" if settings['subscription_reminder'] else "🔴 معطل"
    status_daily = "🟢 مفعل" if settings['daily_stats_reminder'] else "🔴 معطل"
    status_weekly = "🟢 مفعل" if settings['weekly_report'] else "🔴 معطل"
    text = f"⏰ **إعدادات التذكيرات**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 تذكير انتهاء الاشتراك: {status_sub}\n📊 تقرير يومي: {status_daily}\n📈 تقرير أسبوعي: {status_weekly}\n⏰ التذكير قبل: {settings['reminder_days_before']} أيام"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔔 تذكير الاشتراك", callback_data=CallbackData.REMINDER_TOGGLE_SUB),
         InlineKeyboardButton("📊 تقرير يومي", callback_data=CallbackData.REMINDER_TOGGLE_DAILY)],
        [InlineKeyboardButton("📈 تقرير أسبوعي", callback_data=CallbackData.REMINDER_TOGGLE_WEEKLY),
         InlineKeyboardButton("⏰ عدد الأيام", callback_data=CallbackData.REMINDER_SET_DAYS)],
        [InlineKeyboardButton("🌐 لغة الإشعارات", callback_data=CallbackData.REMINDER_SET_LANG),
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def reminder_toggle_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    settings = await db_get_user_reminder_settings(uid)
    await db_update_reminder_settings(uid, subscription_reminder=not settings['subscription_reminder'])
    await reminder_menu_callback(update, context)

async def reminder_toggle_daily_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    settings = await db_get_user_reminder_settings(uid)
    await db_update_reminder_settings(uid, daily_stats_reminder=not settings['daily_stats_reminder'])
    await reminder_menu_callback(update, context)

async def reminder_toggle_weekly_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    settings = await db_get_user_reminder_settings(uid)
    await db_update_reminder_settings(uid, weekly_report=not settings['weekly_report'])
    await reminder_menu_callback(update, context)

async def reminder_set_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_REMINDER_DAYS
    msg = "⏰ **عدد أيام التذكير**\n\nأرسل عدد الأيام التي تريد أن يتم تذكيرك بها قبل انتهاء الاشتراك (1-10 أيام):"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REMINDER_MENU)]])
    if query:
        await safe_edit_markdown(query, msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def reminder_set_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("العربية 🇸🇦", callback_data=f"{CallbackData.REMINDER_LANG_PREFIX}ar"),
         InlineKeyboardButton("English 🇬🇧", callback_data=f"{CallbackData.REMINDER_LANG_PREFIX}en")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REMINDER_MENU)]
    ])
    if query:
        await query.edit_message_text("🌐 اختر لغة الإشعارات:", reply_markup=keyboard)
    else:
        await update.message.reply_text("🌐 اختر لغة الإشعارات:", reply_markup=keyboard)

async def reminder_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    lang = query.data.split(":")[-1] if query else context.user_data.get('reminder_lang')
    if not lang:
        return
    await db_update_reminder_settings(uid, notification_lang=lang)
    if query:
        await query.edit_message_text("✅ تم تحديث لغة الإشعارات")
    else:
        await update.message.reply_text("✅ تم تحديث لغة الإشعارات")
    await reminder_menu_callback(update, context)

# ===================== معالجات الكولباك للترجمة =====================
async def translation_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ إيقاف الترجمة", callback_data=CallbackData.TRANSLATION_OFF)],
        [InlineKeyboardButton("العربية 🇸🇦", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ar"),
         InlineKeyboardButton("English 🇬🇧", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}en")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await query.edit_message_text("🌐 **الترجمة التلقائية**\nاختر اللغة التي تريد الترجمة إليها:", reply_markup=keyboard)
    else:
        await update.message.reply_text("🌐 **الترجمة التلقائية**\nاختر اللغة التي تريد الترجمة إليها:", reply_markup=keyboard)

async def translation_off_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    await set_user_translation_language(uid, 'off')
    if query:
        await query.edit_message_text("✅ تم إيقاف الترجمة التلقائية")
    else:
        await update.message.reply_text("✅ تم إيقاف الترجمة التلقائية")
    await main_menu_callback(update, context)

async def translation_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    lang = query.data.split(":")[-1] if query else context.user_data.get('translation_lang')
    if not lang:
        return
    await set_user_translation_language(uid, lang)
    lang_name = SUPPORTED_LANGUAGES.get(lang, lang)
    if query:
        await query.edit_message_text(f"✅ تم تعيين لغة الترجمة إلى: {lang_name}")
    else:
        await update.message.reply_text(f"✅ تم تعيين لغة الترجمة إلى: {lang_name}")
    await main_menu_callback(update, context)

# ===================== معالجات الكولباك للغة =====================
async def lang_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    lang = query.data.split("_")[-1] if query else context.user_data.get('selected_lang')
    if not lang or lang not in SUPPORTED_LANGUAGES:
        return
    user_language[uid] = lang
    await set_user_language(uid, lang)
    if query:
        await query.edit_message_text(f"✅ تم تغيير اللغة إلى: {SUPPORTED_LANGUAGES[lang]}")
    else:
        await update.message.reply_text(f"✅ تم تغيير اللغة إلى: {SUPPORTED_LANGUAGES[lang]}")
    await main_menu_callback(update, context)

# ===================== معالجات الكولباك للنصوص العامة =====================
async def handle_text_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        data = query.data
    else:
        data = context.user_data.get('callback_data')
    if not data:
        return
    uid = update.effective_user.id
    if data == "rank":
        level_data = await db_get_user_level(uid)
        text = f"🏆 **رتبتك**\n━━━━━━━━━━━━━━━━━━━━━━\n⭐ المستوى: {level_data['level']}\n💎 النقاط: {level_data['points']}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=kb)
    elif data == "top":
        top = await get_top_users(10)
        text = "🏆 **أفضل 10 مستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for i, (uid, pts, lvl) in enumerate(top, 1):
            text += f"{i}. `{uid}` - ⭐ {lvl} - 💎 {pts}\n"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=kb)
    elif data == "language":
        await language_command_handler(update, context)

# ===================== لوحة الأدمن =====================
async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer("🔒 غير مصرح", show_alert=True)
        else:
            await update.message.reply_text("🔒 غير مصرح")
        return
    text = "👑 **لوحة تحكم الأدمن**"
    kb = get_admin_keyboard(uid)
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

# ===================== معالجات الأدمن الأساسية =====================
async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    users = await db_get_all_users()
    text = f"👥 **قائمة المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\nإجمالي المستخدمين: {len(users)}\n"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 عرض المحظورين", callback_data=CallbackData.ADMIN_BANNED_USERS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, update.effective_user.id, text, reply_markup=kb)

async def admin_banned_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    users = await db_get_all_users()
    banned = [u for u in users if u[1] == 1]
    text = f"🚫 **المستخدمين المحظورين**\n━━━━━━━━━━━━━━━━━━━━━━\nالعدد: {len(banned)}\n"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 فك حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_USERS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, update.effective_user.id, text, reply_markup=kb)

async def admin_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    channels = await db_get_all_user_channels_no_limit()
    text = f"📡 **جميع القنوات**\n━━━━━━━━━━━━━━━━━━━━━━\nالعدد: {len(channels)}\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, update.effective_user.id, text, reply_markup=kb)

async def admin_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    groups = await db_get_all_groups()
    text = f"📊 **جميع المجموعات**\n━━━━━━━━━━━━━━━━━━━━━━\nالعدد: {len(groups)}\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, update.effective_user.id, text, reply_markup=kb)

# ===================== معالجات الإجراءات المتقدمة =====================
async def advanced_actions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 غير مصرح", show_alert=True)
        return
    kb = get_advanced_group_actions_keyboard(chat_id)
    if query:
        await query.edit_message_text("🛠️ **إجراءات متقدمة**", reply_markup=kb)
    else:
        await update.message.reply_text("🛠️ **إجراءات متقدمة**", reply_markup=kb)

async def group_action_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_BAN_USER
    context.user_data['ban_chat_id'] = chat_id
    if query:
        await query.edit_message_text("🚫 أرسل معرف المستخدم الذي تريد حظره:")

async def group_action_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    kb = get_advanced_mute_duration_keyboard(chat_id)
    if query:
        await query.edit_message_text("🔇 اختر مدة الكتم:", reply_markup=kb)

async def advanced_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    parts = query.data.split(":")
    duration = int(parts[1])
    chat_id = int(parts[2])
    context.user_data['state'] = UserState.WAITING_MUTE_USER
    context.user_data['mute_chat_id'] = chat_id
    context.user_data['mute_duration'] = duration if duration > 0 else None
    if query:
        await query.edit_message_text("🔇 أرسل معرف المستخدم الذي تريد كتمه:")

async def group_action_warn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    chat_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_WARN_USER
    context.user_data['warn_chat_id'] = chat_id
    if query:
        await query.edit_message_text("⚠️ أرسل معرف المستخدم الذي تريد تحذيره:")

async def group_action_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    chat_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_KICK_USER
    context.user_data['kick_chat_id'] = chat_id
    if query:
        await query.edit_message_text("👢 أرسل معرف المستخدم الذي تريد طرده:")

async def group_action_restrict_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    chat_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_RESTRICT_USER
    context.user_data['restrict_chat_id'] = chat_id
    if query:
        await query.edit_message_text("🔒 أرسل معرف المستخدم الذي تريد تقييده:")

async def group_action_pin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    chat_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_PIN_MESSAGE
    context.user_data['pin_chat_id'] = chat_id
    if query:
        await query.edit_message_text("📌 أرسل معرف الرسالة التي تريد تثبيتها:")

async def group_action_unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    chat_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_UNBAN_USER
    context.user_data['unban_chat_id'] = chat_id
    if query:
        await query.edit_message_text("🔓 أرسل معرف المستخدم الذي تريد فك حظره:")

async def group_action_log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('log_chat_id')
    text = await get_moderation_log(chat_id)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, update.effective_user.id, text, reply_markup=kb)

# ===================== معالجات لوحة التحكم =====================
async def panel_lock_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    chat_id = int(query.data.split(":")[-1])
    await db_set_chat_lock(chat_id, True, update.effective_user.id)
    if query:
        await query.edit_message_text("🔒 تم قفل المجموعة")

async def panel_unlock_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    chat_id = int(query.data.split(":")[-1])
    await db_set_chat_lock(chat_id, False)
    if query:
        await query.edit_message_text("🔓 تم فتح المجموعة")

async def panel_close_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.delete()

# ===================== نشر الكل وإحصائيات القنوات =====================
async def publish_all_channels_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    channels = await db_get_channels(uid)
    if not channels:
        if query:
            await query.edit_message_text("📭 لا توجد قنوات")
        return
    count = 0
    for ch in channels:
        post = await db_get_next_post(ch[0])
        if not post:
            continue
        try:
            if post.get('media_file_id'):
                await context.bot.send_photo(ch[1], post['media_file_id'], caption=post.get('text'))
            else:
                await context.bot.send_message(ch[1], post['text'])
            await db_mark_published(post['id'])
            count += 1
        except:
            pass
    if query:
        await query.edit_message_text(f"✅ تم النشر في {count} قناة")

async def channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    stats = await db_get_channel_stats(ch_db_id)
    text = f"📊 **إحصائيات القناة**\n━━━━━━━━━━━━━━━━━━━━━━\n📝 المنشورات: {stats['total_posts']}\n✅ المنشورة: {stats['published_posts']}\n⏳ غير المنشورة: {stats['unpublished_posts']}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{ch_db_id}")],
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{ch_db_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def channel_growth_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    ch_db_id = int(query.data.split(":")[-1])
    growth = await db_get_channel_growth(ch_db_id)
    text = f"📈 **نمو القناة**\nإجمالي المنشورات: {growth['total_posts']}\nإجمالي المشاهدات: {growth['total_views']}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.CHANNEL_STATS}:{ch_db_id}")]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)

async def channel_stats_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await channel_stats_callback(update, context)

async def my_channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    summary = await db_get_channel_stats_summary(uid)
    if not summary:
        text = "📭 لا توجد إحصائيات"
    else:
        text = f"📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 القنوات: {summary['total_channels']}\n✅ النشطة: {summary['active_channels']}\n📝 المنشورات: {summary['total_posts']}\n👁️ المشاهدات: {summary['total_views']}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

# ===================== الإشتراك الإجباري =====================
async def check_subscribe_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if await ensure_force_subscribe(update, context, uid):
        await main_menu_callback(update, context)

# ===================== إعدادات الردود التلقائية =====================
async def admin_auto_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    data = query.data if query else context.user_data.get('auto_reply_data', '')
    chat_id = None
    if ":" in data:
        chat_id = int(data.split(":")[-1])
    if data.startswith("admin_auto_reply_select"):
        settings = await db_get_auto_reply_settings(chat_id)
        kb = get_auto_reply_keyboard(chat_id, settings)
        if query:
            await query.edit_message_text("📝 **إعدادات الردود التلقائية**", reply_markup=kb)
    elif data.startswith("auto_reply_toggle"):
        await db_toggle_auto_reply(chat_id)
        await admin_auto_reply_callback(update, context)
    elif data.startswith("auto_reply_admins"):
        settings = await db_get_auto_reply_settings(chat_id)
        await db_set_auto_reply_only_admins(chat_id, not settings['only_admins'])
        await admin_auto_reply_callback(update, context)
    elif data.startswith("user_auto_reply_toggle"):
        user_id = int(data.split(":")[-1])
        status = await db_get_user_auto_reply_status(user_id)
        await db_set_user_auto_reply_status(user_id, not status)
        if query:
            await query.edit_message_text("✅ تم تحديث الإعدادات")
        await main_menu_callback(update, context)

# ===================== NSFW =====================
async def nsfw_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    data = query.data if query else context.user_data.get('nsfw_data', '')
    if data == "nsfw_toggle":
        new_val = not is_nsfw_enabled()
        os.environ["NSFW_ENABLED"] = str(new_val)
        import constants
        constants.NSFW_ENABLED = new_val
        if query:
            await query.edit_message_text(f"✅ NSFW {'مفعل' if new_val else 'معطل'}")
    elif data == "nsfw_threshold_set":
        context.user_data['state'] = UserState.WAITING_NSFW_THRESHOLD
        if query:
            await query.edit_message_text("🔢 أرسل النسبة الجديدة (0.0 - 1.0):")

# ===================== أوامر المودريشن (تنفيذ) =====================
async def handle_moderation_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    cmd = update.message.text.split()[0].replace('/', '')
    args = context.args
    if not args:
        await update.message.reply_text("📝 يرجى تحديد معرف المستخدم")
        return
    target_id = int(args[0]) if args[0].lstrip('-').isdigit() else None
    if not target_id:
        await update.message.reply_text("❌ معرف غير صالح")
        return
    if cmd == "ban":
        await execute_ban(context.bot, chat_id, target_id, moderator_id=user_id)
    elif cmd == "mute":
        await execute_mute(context.bot, chat_id, target_id, moderator_id=user_id)
    elif cmd == "kick":
        await execute_kick(context.bot, chat_id, target_id, moderator_id=user_id)
    elif cmd == "warn":
        await execute_warn(context.bot, chat_id, target_id, moderator_id=user_id)
    elif cmd == "restrict":
        await execute_restrict(context.bot, chat_id, target_id, moderator_id=user_id)
    elif cmd == "unban":
        await execute_unban(context.bot, chat_id, target_id, moderator_id=user_id)
    elif cmd == "pin":
        if update.message.reply_to_message:
            await execute_pin(context.bot, chat_id, update.message.reply_to_message.message_id)
        else:
            await update.message.reply_text("📌 يرجى الرد على الرسالة المراد تثبيتها")
    await update.message.reply_text("✅ تم تنفيذ الإجراء")

# ===================== مسابقات =====================
async def contests_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await contests_menu_callback(update, context)

async def contests_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    contests = await db_get_active_contests_with_participants(10)
    if not contests:
        text = "📭 لا توجد مسابقات نشطة حالياً"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    else:
        text = "🏆 **المسابقات النشطة**\n"
        kb = []
        for c in contests:
            kb.append([InlineKeyboardButton(f"🎯 {c[1]}", callback_data=f"{CallbackData.CONTEST_JOIN_PREFIX}{c[0]}")])
        kb.append([InlineKeyboardButton("🏅 الفائزون السابقون", callback_data=CallbackData.CONTEST_WINNERS)])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.CONTESTS_BACK)])
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await safe_send_markdown(context.bot, update.effective_user.id, text, reply_markup=InlineKeyboardMarkup(kb))

async def contest_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    cid = int(query.data.split(":")[-1])
    contest = await db_get_contest(cid)
    if not contest:
        return
    if await db_get_user_participation(uid, cid):
        if query:
            await query.answer("أنت مشترك بالفعل", show_alert=True)
        return
    async def _join(conn):
        await conn.execute("INSERT INTO contest_participants (user_id, contest_id, joined_at) VALUES (?, ?, ?)", (uid, cid, utc_now_iso()))
        await conn.commit()
    await execute_db(_join)
    if query:
        await query.edit_message_text(f"✅ تم الاشتراك في مسابقة: {contest['title']}")

async def contest_winners_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    winners = await db_get_contest_winners()
    text = "🏅 **الفائزون السابقون**\n"
    for w in winners:
        text += f"• {w[1]} - الفائز: {w[3]}\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.CONTESTS_BACK)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)

async def contests_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu_callback(update, context)

async def admin_create_contest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    context.user_data['state'] = UserState.WAITING_CONTEST_TITLE
    if query:
        await query.edit_message_text("🏆 أرسل عنوان المسابقة:")

async def admin_declare_winner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    context.user_data['state'] = UserState.WAITING_CONTEST_ANSWER
    if query:
        await query.edit_message_text("🏆 أرسل معرف المسابقة لإعلان الفائز:")

async def create_contest_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_create_contest_callback(update, context)

async def declare_winner_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_declare_winner_callback(update, context)

# ===================== معالجات تسجيل المجموعات تلقائياً =====================
async def track_chat_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup']:
        await db_register_group(chat.id, chat.title, PRIMARY_OWNER_ID, chat.username)

async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass

async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup']:
        await db_register_group(chat.id, chat.title, PRIMARY_OWNER_ID, chat.username)
        await update.message.reply_text("✅ تم تفعيل البوت في المجموعة!")

# ===================== نظام تصفية الرسائل في المجموعات =====================
async def filter_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    msg = update.message
    text = msg.text or msg.caption or ""
    if await is_chat_locked(chat_id) and not await is_authorized_in_group(context.bot, chat_id, user_id):
        try:
            await msg.delete()
        except:
            pass
        return
    settings = await db_get_security_settings(chat_id)
    if settings['links'] and contains_link(text):
        await msg.delete()
        await apply_penalty(context.bot, chat_id, user_id, settings, "إرسال رابط")
        return
    if settings['mentions'] and contains_mention(text):
        await msg.delete()
        await apply_penalty(context.bot, chat_id, user_id, settings, "إرسال معرف")
        return
    word = await db_contains_banned_word(text, chat_id)
    if word:
        await msg.delete()
        await apply_penalty(context.bot, chat_id, user_id, settings, f"كلمة محظورة: {word}")
        return
    if not await db_check_slow_mode(chat_id, user_id):
        await msg.delete()
        return

# ===================== معالج الرسائل في الخاص =====================
async def message_handler_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    user_id = update.effective_user.id
    state = context.user_data.get('state')
    if state == UserState.WAITING_CHANNEL_ID:
        channel_id = msg.text.strip()
        if channel_id.startswith('@'):
            channel_id = channel_id[1:]
        try:
            chat = await context.bot.get_chat(f"@{channel_id}")
            await db_add_channel(user_id, str(chat.id), chat.title or channel_id)
            await msg.reply_text("✅ تمت إضافة القناة بنجاح")
        except:
            await msg.reply_text("❌ فشل إضافة القناة، تأكد من صحة المعرف ومن أن البوت مشرف في القناة")
        context.user_data.pop('state', None)
        await main_menu_callback(update, context)
        return
    elif state == UserState.ADDING_POSTS:
        session_key = f"session_{user_id}"
        target_key = f"session_target_{user_id}"
        posts = context.user_data.get(session_key, [])
        target = context.user_data.get(target_key, 15)
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
        elif msg.audio:
            media_type = 'audio'
            media_file_id = msg.audio.file_id
        elif msg.voice:
            media_type = 'voice'
            media_file_id = msg.voice.file_id
        elif msg.animation:
            media_type = 'animation'
            media_file_id = msg.animation.file_id
        posts.append((text_content, media_type, media_file_id))
        context.user_data[session_key] = posts
        remaining = target - len(posts)
        if remaining <= 0:
            active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
            if active:
                await db_save_posts(active, posts)
                await msg.reply_text(f"✅ تم حفظ {len(posts)} منشور")
            context.user_data.pop(session_key, None)
            context.user_data.pop(target_key, None)
            context.user_data.pop('state', None)
            await main_menu_callback(update, context)
        else:
            await msg.reply_text(f"📥 تم الاستلام ({len(posts)}/{target})، أرسل {remaining} منشورات أخرى أو اضغط /cancel")
        return
    elif state == UserState.WAITING_BROADCAST:
        text = msg.text
        users = await db_get_all_users()
        count = 0
        for u in users:
            try:
                await context.bot.send_message(u[0], text)
                count += 1
            except:
                pass
        context.user_data.pop('state', None)
        await msg.reply_text(f"✅ تم الإرسال إلى {count} مستخدم")
        return
    elif state == UserState.WAITING_FORCE_CHANNEL:
        channel = msg.text.strip()
        await db_set_force_subscribe_channel(channel)
        context.user_data.pop('state', None)
        await msg.reply_text("✅ تم تعيين قناة الاشتراك الإجباري")
        return
    elif state == UserState.WAITING_LOG_CHANNEL:
        await set_log_channel_command_handler(update, context)
        return
    elif state == UserState.WAITING_SENDCODE_PASSWORD:
        context.user_data['sendcode_password'] = msg.text
        await msg.reply_text("✅ تم استلام كلمة المرور")
        return
    if msg.text:
        from replies import get_random_reply
        reply = get_random_reply(msg.text)
        if reply:
            await msg.reply_text(reply)
            return
    await main_menu_callback(update, context)

# ===================== معالج الأخطاء العام =====================
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="حدث خطأ:", exc_info=context.error)
    try:
        if update and hasattr(update, 'effective_chat') and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ حدث خطأ غير متوقع. تم تسجيل الخطأ وسيتم معالجته."
            )
    except:
        pass

# ===================== دوال مساعدة لإنشاء المسابقات =====================
async def handle_contest_creation_states(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    state = context.user_data.get('state')
    if state == UserState.WAITING_CONTEST_TITLE:
        context.user_data['contest_title'] = msg.text
        context.user_data['state'] = UserState.WAITING_CONTEST_DESCRIPTION
        await msg.reply_text("📝 أرسل وصف المسابقة:")
    elif state == UserState.WAITING_CONTEST_DESCRIPTION:
        context.user_data['contest_description'] = msg.text
        context.user_data['state'] = UserState.WAITING_CONTEST_PRIZE
        await msg.reply_text("🎁 أرسل الجائزة:")
    elif state == UserState.WAITING_CONTEST_PRIZE:
        context.user_data['contest_prize'] = msg.text
        context.user_data['state'] = UserState.WAITING_CONTEST_END_DATE
        await msg.reply_text("📅 أرسل تاريخ انتهاء المسابقة (YYYY-MM-DD):")
    elif state == UserState.WAITING_CONTEST_END_DATE:
        try:
            end_date = datetime.strptime(msg.text.strip(), "%Y-%m-%d")
            if end_date <= utc_now():
                await msg.reply_text("❌ التاريخ يجب أن يكون في المستقبل")
                return
            context.user_data['contest_end_date'] = end_date.isoformat()
            title = context.user_data.get('contest_title', '')
            description = context.user_data.get('contest_description', '')
            prize = context.user_data.get('contest_prize', '')
            async def _save(conn):
                await conn.execute(
                    "INSERT INTO contests (creator_id, title, description, prize, end_date, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (update.effective_user.id, title, description, prize, end_date.isoformat(), utc_now_iso())
                )
                await conn.commit()
            await execute_db(_save)
            for key in ['contest_title', 'contest_description', 'contest_prize', 'contest_end_date', 'state']:
                context.user_data.pop(key, None)
            await msg.reply_text("✅ تم إنشاء المسابقة بنجاح!")
        except ValueError:
            await msg.reply_text("❌ صيغة التاريخ غير صحيحة")
    elif state == UserState.WAITING_CONTEST_ANSWER:
        contest_id = int(msg.text.strip())
        winner = await db_get_random_participant(contest_id)
        if winner:
            await db_set_contest_winner(contest_id, winner)
            await msg.reply_text(f"✅ تم إعلان الفائز: {winner}")
        else:
            await msg.reply_text("❌ لا يوجد مشاركون في هذه المسابقة")
        context.user_data.pop('state', None)
    else:
        await message_handler_main(update, context)

# ===================== دوال sendcode والتأكيد =====================
async def sendcode_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    allowed_user = await db_get_allowed_sendcode_user()
    if allowed_user and user_id != allowed_user and user_id != PRIMARY_OWNER_ID:
        await update.message.reply_text("🔒 غير مصرح")
        return
    context.user_data['state'] = UserState.WAITING_SENDCODE_PASSWORD
    await update.message.reply_text("🔐 أرسل كلمة المرور للمتابعة:")

async def handle_sendcode_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    if query:
        await query.edit_message_text("✅ تم التأكيد")

async def admin_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    kb = get_replies_keyboard()
    if query:
        await query.edit_message_text("💬 **إدارة الردود**", reply_markup=kb)

async def admin_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    kb = get_banned_words_admin_keyboard()
    if query:
        await query.edit_message_text("🚫 **الكلمات المحظورة العامة**", reply_markup=kb)

# ===================== معالج الدفع =====================
async def pre_checkout_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def successful_payment_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload
    if payload.startswith("sub_"):
        _, days, _ = payload.split("_")
        await db_activate_subscription(uid, int(days))
        await update.message.reply_text(f"✅ تم تفعيل اشتراكك لمدة {days} يوم! شكراً لدعمك ❤️")
    await main_menu_callback(update, context)

