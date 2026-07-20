#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
معالجات الأوامر والكولباك والرسائل - كاملة بدون اختصار
"""

import asyncio
import json
import re
import time as time_module
import secrets
import hashlib
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
    BATTERY_SAVER_MODE, MAX_FILE_SIZE, DEFAULT_PUBLISH_INTERVAL_SECONDS
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
    translate_text, 
    invalidate_user_cache, parse_days_of_week_safe, parse_dates_safe,
    rate_limiter
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
    db_get_subscription_days_left
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
from tasks import create_backup, list_backups, restore_backup, incremental_backup
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
    
    # جلب النصوص من ملفات اللغة (سيتم التعامل معها لاحقاً)
    from constants import user_language
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
    except Exception:
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
    from database import execute_db
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
    from database import execute_db
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
    from database import execute_db
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
    from database import execute_db
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
    from database import execute_db
    async def _get_group_name(conn):
        cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
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
    from database import execute_db
    async def _get_group_name(conn):
        cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
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

🔐 **الميزات الأمنية المتقدمة:**
• تشفير قاعدة البيانات بكلمة مرور (PBKDF2)
• نظام كشف النشاط المشبوه
• تخزين مؤقت محسن مع دعم Redis
• Pool اتصالات قاعدة البيانات
• إعادة تدوير المنشورات تلقائياً
• إحصائيات متقدمة للقنوات
• نظام Rate Limiting متقدم
• مصادقة ثنائية (2FA)
• دعم جميع أنواع الميديا
• مترجم ذكي غير متزامن
• WebSocket للتحديثات الفورية
• نسخ احتياطي تدريجي وضغط محسن
• Health Check متقدم
• مراقبة الذاكرة التلقائية
• نظام المسابقات المتكامل
• واجهة ويب متكاملة
• حماية واجهة الويب بكلمة مرور
• مفتاح تشفير منفصل للنسخ الاحتياطي
• تنقية النصوص باستخدام bleach
• إدارة المهام بـ Semaphore
• 200 رد تلقائي للمجموعات مع أوزان
• نظام ردود ذكي مع تحليل المشاعر
• دعم المالك والمشرفين المخفيين المتعددين
• نظام ردود متقدم مع إعدادات لكل مجموعة
• إمكانية تفعيل/تعطيل الردود لكل مجموعة
• وضع المشرفين فقط للردود
• تشفير بيانات الكولباك
• حد أقصى للمنشورات غير المنشورة
• 🔞 **كشف المحتوى غير اللائق (NSFW)** مع تخزين مؤقت
• 📥 **استيراد الكلمات المحظورة من ملف** مع دعم Regex
• 🌐 **دعم 12 لغة** مع ترجمة تلقائية
• 📊 **رسوم بيانية تفاعلية** في واجهة الويب
• 📤 **تصدير البيانات** (CSV)
• 🌙 **وضع Dark Mode**
• ⏱️ **جدولة CRON**
• 👑 **دعم كامل للمشرفين المتعددين**
• 🎴 **حذف الملصقات**
• 🎬 **حذف الفيديوهات**
• 📨 **حذف رسائل الخدمة**

⚡ **وضع السرعة:** {'مفعل' if not BATTERY_SAVER_MODE else 'معطل'}

📊 **إحصائيات الأداء:**
• استخدام الرام: {ram['percent']}%

━━━━━━━━━━━━━━━━━━━━━━
📞 **طرق التواصل:**
✅ **تيليجرام:** @RelaxMgr
✅ **البوت:** @{BOT_USERNAME}"""
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
📌 القناة: @{updates_channel}

📢 تابع القناة لمعرفة آخر التحديثات:
• ميزات جديدة ✨
• تحسينات الأداء ⚡
• إصلاحات الأخطاء 🔧
• عروض حصرية 🎁

🔗 اضغط على الزر أدناه لفتح القناة."""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 افتح القناة", url=f"https://t.me/{updates_channel}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
    else:
        text = """📢 **لم يتم تعيين قناة التحديثات بعد**

📌 **لتعيين قناة التحديثات:**
1. استخدم `/admin_panel`
2. اضغط على `⚙️ قناة التحديثات`
3. أرسل معرف القناة

⚠️ تأكد من أن البوت مشرف في القناة."""
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
    from database import execute_db
    async def _get_referrals(conn):
        cur = await conn.execute("SELECT r.referred_id, r.referred_at, r.is_rewarded, u.first_name, u.username FROM referrals r LEFT JOIN users_cache u ON r.referred_id = u.user_id WHERE r.referrer_id = ? ORDER BY r.referred_at DESC LIMIT 20", (uid,))
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
        await query.edit_message_text(msg, reply_markup=kb)
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
    msg = "🌐 **اختر لغة الإشعارات:**"
    if query:
        await query.edit_message_text(msg, reply_markup=keyboard)
    else:
        await update.message.reply_text(msg, reply_markup=keyboard)

async def reminder_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    lang = query.data.split(":")[-1] if query else context.user_data.get('reminder_lang')
    if not lang:
        return
    await db_update_reminder_settings(uid, notification_lang=lang)
    await reminder_menu_callback(update, context)

# ===================== معالجات الكولباك للترجمة =====================

async def translation_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    current_lang = await get_user_translation_language(uid)
    lang_names = {
        'ar': 'العربية', 'en': 'English', 'fr': 'Français', 'tr': 'Türkçe',
        'zh': '中文', 'ru': 'Русский', 'de': 'Deutsch', 'es': 'Español',
        'it': 'Italiano', 'pt': 'Português', 'ja': '日本語', 'ko': '한국어'
    }
    if current_lang == 'off':
        status_text = "معطلة ❌"
    else:
        status_text = f"مفعلة ✅ إلى {lang_names.get(current_lang, current_lang)}"
    text = f"""🌐 **إعدادات الترجمة**
━━━━━━━━━━━━━━━━━━━━━━
📌 **الحالة:** {status_text}
📌 كيفية العمل:
سيتم ترجمة المنشورات تلقائياً عند النشر إلى اللغة التي تختارها
━━━━━━━━━━━━━━━━━━━━━━
اختر لغة الترجمة:"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 إيقاف الترجمة", callback_data=CallbackData.TRANSLATION_OFF)],
        [InlineKeyboardButton("🇸🇦 العربية", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ar"),
         InlineKeyboardButton("🇬🇧 English", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}en")],
        [InlineKeyboardButton("🇫🇷 Français", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}fr"),
         InlineKeyboardButton("🇹🇷 Türkçe", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}tr")],
        [InlineKeyboardButton("🇨🇳 中文", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}zh"),
         InlineKeyboardButton("🇷🇺 Русский", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ru")],
        [InlineKeyboardButton("🇩🇪 Deutsch", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}de"),
         InlineKeyboardButton("🇪🇸 Español", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}es")],
        [InlineKeyboardButton("🇮🇹 Italiano", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}it"),
         InlineKeyboardButton("🇵🇹 Português", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}pt")],
        [InlineKeyboardButton("🇯🇵 日本語", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ja"),
         InlineKeyboardButton("🇰🇷 한국어", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ko")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def translation_off_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    await set_user_translation_language(uid, 'off')
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    if query:
        await query.edit_message_text("✅ تم إيقاف الترجمة", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم إيقاف الترجمة", reply_markup=kb)

async def translation_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    lang = query.data.split(":")[-1] if query else context.user_data.get('translation_lang')
    if not lang:
        return
    await set_user_translation_language(uid, lang)
    lang_names = {
        'ar': 'العربية', 'en': 'English', 'fr': 'Français', 'tr': 'Türkçe',
        'zh': '中文', 'ru': 'Русский', 'de': 'Deutsch', 'es': 'Español',
        'it': 'Italiano', 'pt': 'Português', 'ja': '日本語', 'ko': '한국어'
    }
    lang_name = lang_names.get(lang, lang)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    if query:
        await query.edit_message_text(f"✅ تم تفعيل الترجمة إلى {lang_name}", reply_markup=kb)
    else:
        await update.message.reply_text(f"✅ تم تفعيل الترجمة إلى {lang_name}", reply_markup=kb)

# ===================== معالجات الكولباك للوحة المشرف =====================

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != PRIMARY_OWNER_ID and not await is_bot_admin(uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    if query:
        await safe_edit_markdown(query, "👑 **لوحة الأدمن**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الإجراء المطلوب:", reply_markup=get_admin_keyboard(uid))
    else:
        await safe_send_markdown(context.bot, uid, "👑 **لوحة الأدمن**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الإجراء المطلوب:", reply_markup=get_admin_keyboard(uid))

# ===================== معالجات الكولباك للمسابقات =====================

async def contests_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update or not update.effective_user:
            return
        user_id = update.effective_user.id
        contests = await db_get_active_contests_with_participants(limit=10)
        if not contests:
            text = "📭 لا توجد مسابقات نشطة حالياً"
            if update.callback_query:
                await safe_edit_markdown(update.callback_query, text)
            else:
                await safe_send_markdown(context.bot, user_id, text)
            return
        text = "🏆 **المسابقات النشطة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        keyboard = []
        for contest in contests:
            cid = contest[0]
            title = contest[1] or "بدون عنوان"
            desc = contest[2] or ""
            prize = contest[3] or "غير محددة"
            end_date = contest[4]
            participants = contest[5] if len(contest) > 5 else 0
            contest_type = contest[6] if len(contest) > 6 else 'raffle'
            try:
                end_dt = datetime.fromisoformat(end_date)
                days_left = (end_dt - utc_now()).days
                time_left = f"⏳ متبقي {days_left} يوم" if days_left > 0 else "🔴 انتهت"
            except:
                time_left = "📅 تاريخ غير صحيح"
                days_left = 0
            participated = await db_get_user_participation(user_id, cid)
            status_icon = "✅" if participated else "📝"
            type_icon = "📝" if contest_type == 'quiz' else "🎲" if contest_type == 'raffle' else "🗳️" if contest_type == 'vote' else "📤"
            text += f"📌 **{title}** {type_icon}\n"
            text += f"📝 {(desc)[:100]}{'...' if len(desc) > 100 else ''}\n"
            text += f"🎁 الجائزة: {prize}\n"
            text += f"👥 المشاركون: {participants}\n"
            text += f"🕐 {time_left}\n"
            text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
            if not participated and days_left > 0:
                keyboard.append([InlineKeyboardButton(
                    f"{status_icon} شارك في {title[:20]}",
                    callback_data=f"{CallbackData.CONTEST_JOIN_PREFIX}{cid}"
                )])
        keyboard.append([InlineKeyboardButton("🏆 الفائزون السابقون", callback_data=CallbackData.CONTEST_WINNERS)])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
        if update.callback_query:
            await safe_edit_markdown(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        error_id = log_error(e, {'user_id': update.effective_user.id if update else None})
        msg = f"❌ حدث خطأ أثناء تحميل المسابقات (الرمز: `{error_id}`)."
        try:
            if update.callback_query:
                await safe_edit_markdown(update.callback_query, msg)
            else:
                await safe_send_markdown(context.bot, user_id, msg)
        except:
            pass

async def contests_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
    await contests_command_handler(update, context)

async def contest_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    user_id = update.effective_user.id
    try:
        contest_id = int(query.data.split(":")[-1])
    except:
        await query.edit_message_text("❌ بيانات غير صالحة.")
        return
    contest = await db_get_contest(contest_id)
    if not contest:
        await query.edit_message_text("❌ المسابقة غير موجودة.")
        return
    if contest['status'] != 'active':
        await query.edit_message_text("❌ هذه المسابقة غير متاحة حالياً.")
        return
    try:
        end_date = datetime.fromisoformat(contest['end_date'])
        if end_date < utc_now():
            await query.edit_message_text("❌ هذه المسابقة قد انتهت.")
            return
    except:
        pass
    participation = await db_get_user_participation(user_id, contest_id)
    if participation:
        await query.edit_message_text("✅ أنت مشترك بالفعل في هذه المسابقة.")
        return
    context.user_data['contest_join_id'] = contest_id
    context.user_data['state'] = UserState.WAITING_CONTEST_ANSWER
    msg = (
        f"📝 **المشاركة في المسابقة: {contest['title']}**\n\n"
        f"📌 أرسل إجابتك (نص) أو اضغط /skip للمشاركة بدون إجابة.\n"
        f"⏳ يمكنك تعديل إجابتك قبل انتهاء المسابقة.\n"
        f"📝 نوع المسابقة: {contest.get('contest_type', 'raffle')}"
    )
    try:
        await query.edit_message_text(msg, parse_mode="MarkdownV2")
    except:
        await query.edit_message_text(msg)

async def contest_winners_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    winners = await db_get_contest_winners(limit=10)
    if not winners:
        if query:
            await query.edit_message_text("🏆 لا يوجد فائزون سابقون")
        else:
            await safe_send_markdown(context.bot, user_id, "🏆 لا يوجد فائزون سابقون")
        return
    text = "🏆 **الفائزون السابقون**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for contest_id, title, prize, winner_id, announced_at in winners:
        try:
            winner = await context.bot.get_chat(winner_id)
            winner_name = winner.first_name or str(winner_id)
        except:
            winner_name = str(winner_id)
        try:
            announced_dt = datetime.fromisoformat(announced_at)
            announced_mecca = utc_to_mecca(announced_dt)
            date_str = announced_mecca.strftime("%Y-%m-%d")
        except:
            date_str = announced_at[:10] if announced_at else "?"
        text += f"📌 **{title}**\n🎁 {prize}\n👤 {winner_name}\n📅 {date_str}\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=CallbackData.CONTEST_WINNERS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.CONTESTS_BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def contests_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await contests_command_handler(update, context)

async def create_contest_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_CONTEST_TITLE
    await update.message.reply_text("📝 **إنشاء مسابقة جديدة**\n\nأرسل **عنوان** المسابقة:")

async def declare_winner_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 **الاستخدام:**\n`/declare_winner معرف_المسابقة معرف_المستخدم`")
        return
    try:
        contest_id = int(args[0])
        winner_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ معرف غير صالح.")
        return
    contest = await db_get_contest(contest_id)
    if not contest:
        await update.message.reply_text("❌ المسابقة غير موجودة.")
        return
    if contest['status'] != 'active':
        await update.message.reply_text("❌ هذه المسابقة غير نشطة.")
        return
    participation = await db_get_user_participation(winner_id, contest_id)
    if not participation:
        await update.message.reply_text("❌ هذا المستخدم لم يشارك في المسابقة.")
        return
    success = await db_set_contest_winner(contest_id, winner_id)
    if success:
        await update.message.reply_text(
            f"✅ تم إعلان فائز المسابقة **{contest['title']}**\n👤 المستخدم: `{winner_id}`\n🎁 الجائزة: {contest['prize']}"
        )
        try:
            await context.bot.send_message(
                winner_id,
                f"🎉 **تهانينا!**\nلقد فزت في مسابقة **{contest['title']}**\n🎁 الجائزة: {contest['prize']}"
            )
        except:
            pass
        level_data = await db_get_user_level(winner_id)
        await db_update_user_level(winner_id, level_data['points'] + 50, level_data['level'])
    else:
        await update.message.reply_text("❌ فشل إعلان الفائز.")

async def admin_create_contest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        if query:
            await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_CONTEST_TITLE
    msg = "📝 **إنشاء مسابقة جديدة**\n\nأرسل **عنوان** المسابقة:"
    if query:
        await query.edit_message_text(msg, parse_mode="MarkdownV2")
    else:
        await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")

async def admin_declare_winner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        if query:
            await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    msg = "📝 **إعلان فائز في مسابقة**\n\nاستخدم الأمر:\n`/declare_winner معرف_المسابقة معرف_المستخدم`\n\nمثال: `/declare_winner 5 123456789`\n\n📌 لعرض المسابقات النشطة استخدم `/contests`"
    if query:
        await query.edit_message_text(msg, parse_mode="MarkdownV2")
    else:
        await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")

# ===================== معالجات الكولباك للغة =====================

async def lang_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if query:
        lang = query.data.split("_")[1] if "_" in query.data else None
    else:
        lang = context.user_data.get('lang_set')
    if not lang:
        if query:
            await query.edit_message_text("❌ لم يتم تحديد اللغة")
        else:
            await update.message.reply_text("❌ لم يتم تحديد اللغة")
        return
    await set_user_language(uid, lang)
    lang_names = {
        'ar': 'العربية 🇸🇦', 'en': 'English 🇬🇧', 'fr': 'Français 🇫🇷',
        'tr': 'Türkçe 🇹🇷', 'zh': '中文 🇨🇳', 'ru': 'Русский 🇷🇺',
        'de': 'Deutsch 🇩🇪', 'es': 'Español 🇪🇸', 'it': 'Italiano 🇮🇹',
        'pt': 'Português 🇵🇹', 'ja': '日本語 🇯🇵', 'ko': '한국어 🇰🇷'
    }
    lang_name = lang_names.get(lang, lang)
    kb, title, active_channel = await get_main_keyboard(uid)
    if active_channel:
        context.user_data['active_channel'] = active_channel
        await db_set_active_channel(uid, active_channel)
    if query:
        await safe_edit_markdown(query, f"✅ تم تغيير اللغة إلى {lang_name}\n\n{title}", reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, f"✅ تم تغيير اللغة إلى {lang_name}\n\n{title}", reply_markup=kb)

async def handle_text_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    data = query.data if query else context.user_data.get('text_callback_data')
    if not data:
        return
    if data == "rank":
        data_rank = await db_get_user_level(uid)
        points = data_rank['points']
        level = data_rank['level']
        next_points = LEVEL_REQUIREMENTS.get(level + 1, points)
        points_needed = next_points - points if next_points > points else 0
        text = f"📊 **رتبتك الحالية**\n━━━━━━━━━━━━━━\n👤 {query.from_user.first_name if query else '👤'}\n⭐ **المستوى:** {level}\n📈 **النقاط:** {points}\n📌 **المتبقي للمستوى التالي:** {points_needed}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=kb)
    elif data == "top":
        top_users = await get_top_users(10)
        if not top_users:
            msg = "📭 لا توجد نقاط مسجدة بعد."
            if query:
                await query.edit_message_text(msg)
            else:
                await update.message.reply_text(msg)
            return
        text = "🏆 **أفضل 10 مستخدمين**\n━━━━━━━━━━━━━━\n"
        for idx, (uid_user, points, level) in enumerate(top_users, 1):
            try:
                user = await context.bot.get_chat(uid_user)
                name = user.first_name or str(uid_user)
            except:
                name = str(uid_user)
            text += f"{idx}. {name} → المستوى {level} ({points} نقطة)\n"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=kb)
    elif data == "schedule_post":
        context.user_data['state'] = UserState.WAITING_SCHEDULE_POST
        msg = "📝 **جدولة منشور جديد**\n\nأرسل المنشور بالصيغة التالية:\n`YYYY-MM-DD HH:MM نص المنشور`\n\nمثال: `2024-12-31 20:00 مرحباً بالجميع!`\n\n🕐 الوقت بتوقيت مكة المكرمة"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
        if query:
            await query.edit_message_text(msg, parse_mode="MarkdownV2", reply_markup=kb)
        else:
            await update.message.reply_text(msg, parse_mode="MarkdownV2", reply_markup=kb)
    elif data == "language":
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
             InlineKeyboardButton("한국어 🇰🇷", callback_data="lang_ko")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        if query:
            await query.edit_message_text("🌿 **مرحباً بك في ريلاكس مانيجر**\nاختر اللغة المناسبة", reply_markup=keyboard)
        else:
            await update.message.reply_text("🌿 **مرحباً بك في ريلاكس مانيجر**\nاختر اللغة المناسبة", reply_markup=keyboard)
    elif data == CallbackData.CONTESTS_MENU:
        await contests_command_handler(update, context)

# ===================== معالجات الكولباك للإجراءات المتقدمة =====================

async def advanced_actions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if chat_id == 0:
        if query:
            await query.edit_message_text("⚠️ يرجى اختيار مجموعة أولاً باستخدام أمر /security")
        else:
            await update.message.reply_text("⚠️ يرجى اختيار مجموعة أولاً باستخدام أمر /security")
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    msg = "🛠️ **الإجراءات المتقدمة للمجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الإجراء المطلوب:"
    if query:
        await safe_edit_markdown(query, msg, reply_markup=get_advanced_group_actions_keyboard(chat_id))
    else:
        await safe_send_markdown(context.bot, uid, msg, reply_markup=get_advanced_group_actions_keyboard(chat_id))

async def group_action_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_BAN_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "🚫 **حظر مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /ban\n\nيمكنك إضافة سبب بعد المعرف: `/ban 123456789 السبب`"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    msg = "🔇 **كتم مستخدم**\n\nاختر مدة الكتم:"
    if query:
        await safe_edit_markdown(query, msg, reply_markup=get_advanced_mute_duration_keyboard(chat_id))
    else:
        await update.message.reply_text(msg, reply_markup=get_advanced_mute_duration_keyboard(chat_id))

async def advanced_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    parts = query.data.split(":") if query else context.user_data.get('mute_duration_data', '').split(":")
    if len(parts) == 3:
        minutes = int(parts[1])
        chat_id = int(parts[2])
        uid = update.effective_user.id
        if not await is_authorized_in_group(context.bot, chat_id, uid):
            if query:
                await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
            else:
                await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
            return
        context.user_data['mute_minutes'] = minutes
        context.user_data['state'] = UserState.WAITING_MUTE_USER
        context.user_data['advanced_chat_id'] = chat_id
        if minutes == 0:
            msg = "🔇 **كتم دائم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`"
        elif minutes < 60:
            msg = f"🔇 **كتم {minutes} دقيقة**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`"
        elif minutes < 1440:
            msg = f"🔇 **كتم {minutes // 60} ساعة**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`"
        else:
            msg = f"🔇 **كتم {minutes // 1440} يوم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`"
        if query:
            await safe_edit_markdown(query, msg)
        else:
            await update.message.reply_text(msg)

async def group_action_warn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_WARN_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "⚠️ **تحذير مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /warn\n\nيمكنك إضافة سبب: `/warn 123456789 السبب`\n\n📌 بعد 3 تحذيرات يتم حظر المستخدم تلقائياً"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_KICK_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "👢 **طرد مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /kick\n\nيمكنك إضافة سبب: `/kick 123456789 السبب`"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_restrict_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_RESTRICT_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "🔒 **تقييد مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /restrict\n\n📌 التقييد يمنع المستخدم من إرسال الصور والفيديوهات والملفات"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_pin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_PIN_MESSAGE
    context.user_data['advanced_chat_id'] = chat_id
    msg = "📌 **تثبيت رسالة**\n\nقم بالرد على الرسالة التي تريد تثبيتها ثم أرسل /pin"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    text = await get_moderation_log(chat_id, 20)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def group_action_unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('advanced_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_UNBAN_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "🔓 **إلغاء حظر مستخدم**\n\nأرسل معرف المستخدم (user_id) لإلغاء حظره:\n`/unban 123456789`"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

# ===================== معالجات الكولباك للوحة التحكم =====================

async def panel_lock_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('panel_chat_id')
    if not chat_id:
        return
    if await is_authorized_in_group(context.bot, chat_id, uid):
        await db_set_chat_lock(chat_id, True, uid)
        if query:
            await safe_edit_markdown(query, "🔒 تم قفل المجموعة")
        else:
            await update.message.reply_text("🔒 تم قفل المجموعة")
    else:
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")

async def panel_unlock_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('panel_chat_id')
    if not chat_id:
        return
    if await is_authorized_in_group(context.bot, chat_id, uid):
        await db_set_chat_lock(chat_id, False)
        if query:
            await safe_edit_markdown(query, "🔓 تم فتح المجموعة")
        else:
            await update.message.reply_text("🔓 تم فتح المجموعة")
    else:
        if query:
            await query.answer("🔒 هذا الأمر للمشرفين فقط!", show_alert=True)
        else:
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")

async def panel_close_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.delete()

# ===================== معالجات الكولباك للنشر في جميع القنوات =====================

async def publish_all_channels_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    channels = await db_get_channels(uid)
    if not channels:
        if query:
            await query.edit_message_text("📭 لا توجد قنوات للنشر فيها.")
        else:
            await update.message.reply_text("📭 لا توجد قنوات للنشر فيها.")
        return
    if query:
        await query.edit_message_text("📤 جاري النشر في جميع القنوات...")
    else:
        await update.message.reply_text("📤 جاري النشر في جميع القنوات...")
    results = []
    success_count = 0
    fail_count = 0
    no_posts_count = 0
    for ch_db_id, ch_tele_id, ch_name, banned in channels:
        if banned:
            results.append(f"⛔ {ch_name}: قناة محظورة")
            continue
        post = await db_get_next_post(ch_db_id)
        if not post:
            results.append(f"📭 {ch_name}: لا توجد منشورات")
            no_posts_count += 1
            continue
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
                await context.bot.send_photo(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
            elif post['media_type'] == 'video' and post['media_file_id']:
                await context.bot.send_video(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
            elif post['media_type'] == 'document' and post['media_file_id']:
                await context.bot.send_document(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
            elif post['media_type'] == 'audio' and post['media_file_id']:
                await context.bot.send_audio(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
            elif post['media_type'] == 'voice' and post['media_file_id']:
                await context.bot.send_voice(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
            elif post['media_type'] == 'animation' and post['media_file_id']:
                await context.bot.send_animation(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
            else:
                await context.bot.send_message(ch_tele_id, final_text)
            await db_mark_published(post['id'])
            await db_set_last_publish(ch_db_id, utc_now())
            await db_update_next_publish_date(ch_db_id)
            results.append(f"✅ {ch_name}: تم النشر بنجاح")
            success_count += 1
        except Exception as e:
            results.append(f"❌ {ch_name}: {str(e)[:50]}")
            fail_count += 1
        await asyncio.sleep(1)
    summary = f"📊 **نتائج النشر في جميع القنوات**\n━━━━━━━━━━━━━━━━━━━━━━\n✅ نجح: {success_count}\n❌ فشل: {fail_count}\n📭 لا توجد منشورات: {no_posts_count}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    result_text = summary + "\n".join(results[:20])
    if len(results) > 20:
        result_text += f"\n\n... و {len(results)-20} نتيجة أخرى"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, result_text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, result_text, reply_markup=keyboard)

# ===================== معالجات الكولباك لإحصائيات القنوات =====================

async def channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    try:
        channel_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('channel_stats_id')
    except:
        channel_db_id = context.user_data.get('channel_stats_id')
    if not channel_db_id:
        if query:
            await query.edit_message_text("⚠️ لم يتم تحديد القناة.")
        else:
            await update.message.reply_text("⚠️ لم يتم تحديد القناة.")
        return
    channels = await db_get_channels(user_id)
    if not any(ch[0] == channel_db_id for ch in channels):
        if query:
            await query.answer("❌ هذه القناة ليست لك", show_alert=True)
        else:
            await update.message.reply_text("❌ هذه القناة ليست لك")
        return
    stats = await db_get_channel_stats(channel_db_id)
    ch_info = await db_get_channel_info(channel_db_id)
    channel_name = ch_info['channel_name'] if ch_info else "القناة"
    if stats['total_posts'] == 0:
        text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد منشورات بعد"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{channel_db_id}")],
            [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{channel_db_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
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
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{channel_db_id}")],
        [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{channel_db_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def channel_growth_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    try:
        channel_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('channel_stats_id')
    except:
        channel_db_id = context.user_data.get('channel_stats_id')
    if not channel_db_id:
        if query:
            await query.edit_message_text("⚠️ لم يتم تحديد القناة.")
        else:
            await update.message.reply_text("⚠️ لم يتم تحديد القناة.")
        return
    channels = await db_get_channels(user_id)
    if not any(ch[0] == channel_db_id for ch in channels):
        if query:
            await query.answer("❌ هذه القناة ليست لك", show_alert=True)
        else:
            await update.message.reply_text("❌ هذه القناة ليست لك")
        return
    growth = await db_get_channel_growth(channel_db_id, days=30)
    ch_info = await db_get_channel_info(channel_db_id)
    channel_name = ch_info['channel_name'] if ch_info else "القناة"
    if not growth['dates']:
        text = f"📈 **نمو {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\nلا توجد بيانات كافية لعرض النمو."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.CHANNEL_STATS}:{channel_db_id}")]
        ])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
        return
    text = f"📈 **نمو {channel_name} (آخر 30 يوم)**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📝 إجمالي المنشورات في الفترة: {growth['total_posts']}\n"
    text += f"👁️ إجمالي المشاهدات: {growth['total_views']}\n"
    text += f"📅 عدد الأيام: {growth['total_days']}\n"
    text += f"📊 متوسط المنشورات يومياً: {growth['total_posts'] / max(1, growth['total_days']):.1f}\n"
    text += f"📊 متوسط المشاهدات يومياً: {growth['total_views'] / max(1, growth['total_days']):.1f}\n"
    text += "\n📅 **التفاصيل اليومية:**\n"
    for i, (date, count, views) in enumerate(zip(growth['dates'], growth['counts'], growth['views'])):
        if i >= 10:
            break
        text += f"• {date}: {count} منشورات، {views} مشاهدة\n"
    if len(growth['dates']) > 10:
        text += f"\n... و {len(growth['dates']) - 10} أيام أخرى"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 العودة للإحصائيات", callback_data=f"{CallbackData.CHANNEL_STATS}:{channel_db_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def channel_stats_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await channel_stats_callback(update, context)

async def my_channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    summary = await db_get_channel_stats_summary(user_id)
    if not summary:
        text = "📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد قنوات مسجلة."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة قناة", callback_data=CallbackData.CHANNELS_ADD)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
        return
    text = f"📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📡 عدد القنوات: {summary['total_channels']}\n"
    text += f"✅ القنوات النشطة: {summary['active_channels']}\n"
    text += f"📝 إجمالي المنشورات: {summary['total_posts']}\n"
    text += f"✅ المنشورة: {summary['total_published']}\n"
    text += f"👁️ إجمالي المشاهدات: {summary['total_views']}\n"
    text += f"📊 متوسط المشاهدات لكل قناة: {summary['avg_views_per_channel']}\n"
    if summary['best_channel']:
        text += f"\n🏆 **أفضل قناة:**\n"
        text += f"• {summary['best_channel']['name']}\n"
        text += f"• مشاهدات: {summary['best_channel']['views']}\n"
        text += f"• منشورات: {summary['best_channel']['posts']}\n"
        text += f"• متوسط المشاهدات: {summary['best_channel']['avg_views']}\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 عرض القنوات", callback_data=CallbackData.CHANNELS_MY)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

# ===================== معالجات الكولباك للإشتراك الإجباري =====================

async def check_subscribe_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    enabled = await db_get_force_subscribe_status()
    channel = await db_get_force_subscribe_channel()
    if enabled and channel:
        if await is_user_subscribed(context.bot, uid, channel):
            if query:
                await safe_edit_markdown(query, "✅ تم التحقق! أنت مشترك الآن.")
            else:
                await update.message.reply_text("✅ تم التحقق! أنت مشترك الآن.")
            await main_menu_callback(update, context)
        else:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 اشترك", url=f"https://t.me/{channel.lstrip('@')}"),
                 InlineKeyboardButton("🔄 تأكد", callback_data=CallbackData.CHECK_SUBSCRIBE),
                 InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
            ])
            if query:
                await safe_edit_markdown(query, f"❌ لم تشترك في @{channel.lstrip('@')}", reply_markup=kb)
            else:
                await update.message.reply_text(f"❌ لم تشترك في @{channel.lstrip('@')}", reply_markup=kb)
    else:
        if query:
            await safe_edit_markdown(query, "⚠️ الاشتراك الإجباري غير مفعل")
        else:
            await update.message.reply_text("⚠️ الاشتراك الإجباري غير مفعل")

# ===================== معالجات الدفع =====================

async def pre_checkout_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("sub_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="بيانات غير صالحة")

async def successful_payment_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None:
        return
    uid = update.effective_user.id
    payment = update.message.successful_payment
    try:
        parts = payment.invoice_payload.split('_')
        days = int(parts[1]) if len(parts) >= 2 else 30
    except:
        days = 30
    await db_activate_subscription(uid, days)
    await update.message.reply_text(f"✅ **تم تفعيل اشتراكك لمدة {days} يوماً!**\nشكراً لدعمك ❤️", parse_mode="MarkdownV2")

# ===================== معالجات أوامر المشرفين الإضافية =====================

async def handle_moderation_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None or update.effective_chat is None:
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    command = update.message.text.split()[0][1:] if update.message.text else ""
    args = update.message.text.split()[1:] if update.message.text else []
    target_user_id = None
    reason = ""
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        target_user_id = update.message.reply_to_message.from_user.id
        if args:
            reason = " ".join(args)
    elif args:
        try:
            target_user_id = int(args[0])
            if len(args) > 1:
                reason = " ".join(args[1:])
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
            return
    else:
        await update.message.reply_text(f"❌ يرجى تحديد مستخدم (بالمعرف أو بالرد على رسالته)")
        return
    if target_user_id == context.bot.id:
        await update.message.reply_text("❌ لا يمكن تطبيق هذا الأمر على البوت")
        return
    if command == "ban":
        success, msg = await execute_ban(context.bot, chat_id, target_user_id, reason=reason, moderator_id=user_id)
    elif command == "mute":
        minutes = 60
        if args and len(args) > 1 and args[1].isdigit():
            minutes = int(args[1])
        success, msg = await execute_mute(context.bot, chat_id, target_user_id, minutes, reason=reason, moderator_id=user_id)
    elif command == "warn":
        success, msg = await execute_warn(context.bot, chat_id, target_user_id, user_id, reason=reason)
    elif command == "kick":
        success, msg = await execute_kick(context.bot, chat_id, target_user_id, reason=reason, moderator_id=user_id)
    elif command == "restrict":
        success, msg = await execute_restrict(context.bot, chat_id, target_user_id, reason=reason, moderator_id=user_id)
    elif command == "unban":
        success, msg = await execute_unban(context.bot, chat_id, target_user_id, moderator_id=user_id)
    else:
        return
    await safe_send_markdown(context.bot, chat_id, msg)

# ===================== معالجات تحديثات المجموعة =====================

async def track_chat_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.my_chat_member and update.my_chat_member.new_chat_member.status in ['administrator', 'creator']:
        chat = update.effective_chat
        if chat and chat.type in ['group', 'supergroup']:
            chat_id = chat.id
            chat_name = chat.title or "بدون اسم"
            user_id = update.effective_user.id
            await db_register_group(chat_id, chat_name, user_id, chat.username)
            await db_sync_group_admins(chat_id, context.bot, user_id)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ **تم تفعيل البوت في المجموعة!**\n\n"
                     f"📌 استخدم /syncgroup لتحديث الإعدادات\n"
                     f"🔐 استخدم /security لإعدادات الأمان\n"
                     f"🛠️ استخدم /panel للوحة التحكم",
                parse_mode="MarkdownV2"
            )

async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.chat_member and update.chat_member.new_chat_member:
        chat = update.effective_chat
        if chat and chat.type in ['group', 'supergroup']:
            await db_sync_group_admins(chat.id, context.bot)

async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.new_chat_members:
        for member in update.message.new_chat_members:
            if member.id == context.bot.id:
                chat_id = update.effective_chat.id
                chat_name = update.effective_chat.title or "بدون اسم"
                user_id = update.effective_user.id
                await db_register_group(chat_id, chat_name, user_id, update.effective_chat.username)
                await db_sync_group_admins(chat_id, context.bot, user_id)
                break

# ===================== معالج الرسائل الرئيسي (كامل) =====================

async def message_handler_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    uid = user.id if user else 0
    text = update.message.text.strip() if update.message.text else ""
    if user and user.is_bot:
        return

    # التحقق من حجم الملفات
    if update.message.photo:
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الصورة كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.video:
        file = await context.bot.get_file(update.message.video.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الفيديو كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.document:
        file = await context.bot.get_file(update.message.document.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الملف كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.audio:
        file = await context.bot.get_file(update.message.audio.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الصوت كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.voice:
        file = await context.bot.get_file(update.message.voice.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم الرسالة الصوتية كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return
    if update.message.animation:
        file = await context.bot.get_file(update.message.animation.file_id)
        if file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(f"❌ حجم المتحركة كبير جداً (الحد الأقصى {MAX_FILE_SIZE//(1024*1024)} ميجابايت)")
            return

    # معالجة إلغاء العملية
    if text == "/cancel":
        context.user_data.pop('state', None)
        context.user_data.pop('support_mode', None)
        await update.message.reply_text("❌ تم الإلغاء")
        if chat.type == 'private':
            await main_menu_callback(update, context)
        return

    # معالجة المصادقة الثنائية
    if context.user_data.get('waiting_2fa') and text:
        if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE:
            try:
                import pyotp
                totp = pyotp.TOTP(ADMIN_2FA_SECRET)
                if totp.verify(text):
                    context.user_data['2fa_verified'] = True
                    context.user_data['2fa_time'] = time_module.time()
                    context.user_data.pop('waiting_2fa', None)
                    await update.message.reply_text("✅ تم التحقق من المصادقة الثنائية!")
                    await sendcode_command_handler(update, context)
                    return
                else:
                    await update.message.reply_text("❌ رمز غير صحيح!")
                    context.user_data.pop('waiting_2fa', None)
                    return
            except:
                await update.message.reply_text("❌ خطأ في التحقق")
                context.user_data.pop('waiting_2fa', None)
                return

    state = context.user_data.get('state')

    # ===================== حالة إضافة المنشورات =====================
    if state == UserState.ADDING_POSTS:
        session_key = f"session_{uid}"
        if text == "/cancel":
            context.user_data.pop(session_key, None)
            context.user_data.pop(f"session_target_{uid}", None)
            context.user_data.pop('state', None)
            await update.message.reply_text("❌ تم الإلغاء")
            await main_menu_callback(update, context)
            return
        media_type = 'text'
        media_file_id = None
        text_content = text
        if update.message.photo:
            media_type = 'photo'
            media_file_id = update.message.photo[-1].file_id
            text_content = update.message.caption or ""
        elif update.message.video:
            media_type = 'video'
            media_file_id = update.message.video.file_id
            text_content = update.message.caption or ""
        elif update.message.document:
            media_type = 'document'
            media_file_id = update.message.document.file_id
            text_content = update.message.caption or ""
        elif update.message.audio:
            media_type = 'audio'
            media_file_id = update.message.audio.file_id
            text_content = update.message.caption or ""
        elif update.message.voice:
            media_type = 'voice'
            media_file_id = update.message.voice.file_id
            text_content = update.message.caption or ""
        elif update.message.animation:
            media_type = 'animation'
            media_file_id = update.message.animation.file_id
            text_content = update.message.caption or ""
        context.user_data[session_key].append((text_content, media_type, media_file_id))
        cur = len(context.user_data[session_key])
        target = context.user_data.get(f"session_target_{uid}", 15)
        if cur >= target or cur >= MAX_POSTS_PER_SESSION:
            active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
            if not active:
                await update.message.reply_text("❌ حدث خطأ")
                context.user_data.pop(session_key, None)
                context.user_data.pop('state', None)
                return
            saved = await db_save_posts(active, context.user_data[session_key])
            context.user_data.pop(session_key, None)
            context.user_data.pop(f"session_target_{uid}", None)
            context.user_data.pop('state', None)
            await update.message.reply_text(f"✅ تم حفظ {saved} منشور")
            await main_menu_callback(update, context)
        else:
            await update.message.reply_text(f"📥 {cur}/{target}")
        return

    # ===================== حالة إنشاء المسابقات =====================
    if state in [UserState.WAITING_CONTEST_TITLE, UserState.WAITING_CONTEST_DESCRIPTION,
                 UserState.WAITING_CONTEST_PRIZE, UserState.WAITING_CONTEST_END_DATE,
                 UserState.WAITING_CONTEST_ANSWER]:
        if await handle_contest_creation_states(update, context, state):
            return

    # ===================== حالة تأكيد /sendcode =====================
    if state == UserState.WAITING_SENDCODE_PASSWORD:
        await handle_sendcode_confirmation_handler(update, context)
        return

    # ===================== حالة إضافة قناة =====================
    if state == UserState.WAITING_CHANNEL_ID:
        context.user_data.pop('state', None)
        channel_id = text.strip()
        if not channel_id.startswith('@') and not channel_id.startswith('-100'):
            await update.message.reply_text("❌ **معرف قناة غير صالح!**\n\nالصيغ المدعومة:\n• `@username` (مثل: @my_channel)\n• `-1001234567890` (المعرف الرقمي)\n\nتأكد من أن البوت مشرف في القناة.", parse_mode="MarkdownV2")
            context.user_data['state'] = UserState.WAITING_CHANNEL_ID
            return
        new_id = await db_add_channel(uid, channel_id, channel_id)
        if new_id:
            context.user_data['active_channel'] = new_id
            await db_set_active_channel(uid, new_id)
            await update.message.reply_text(f"✅ تم إضافة القناة {channel_id}")
        else:
            await update.message.reply_text("⚠️ القناة موجودة مسبقاً")
        kb, title, active = await get_main_keyboard(uid)
        context.user_data['active_channel'] = active
        await safe_send_markdown(context.bot, uid, title, reply_markup=kb)
        return

    # ===================== حالة الدقائق =====================
    if state == UserState.WAITING_INTERVAL_MINUTES:
        context.user_data.pop('state', None)
        ch_db_id = context.user_data.pop('schedule_ch_id', None)
        is_admin = context.user_data.pop('admin_interval', False)
        is_cron = context.user_data.pop('schedule_cron', False)
        if is_cron:
            cron_expr = text.strip()
            if len(cron_expr.split()) >= 5:
                await schedule_cron(ch_db_id, cron_expr)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text(f"✅ **تم حفظ تعبير CRON:** `{cron_expr}`")
                await schedule_menu_callback(update, context)
                return
            else:
                await update.message.reply_text("❌ **تعبير CRON غير صحيح!**\nتأكد من الصيغة: `دقيقة ساعة يوم شهر يوم_أسبوع`")
                return
        try:
            minutes = int(text)
            if minutes < 1:
                minutes = 1
            if is_admin:
                seconds = minutes * 60
                if seconds > 86400:
                    seconds = 86400
                await db_set_publish_interval_seconds(seconds, uid, is_admin=True)
                await update.message.reply_text(f"✅ **تم ضبط وقت النشر العام بنجاح!**\n\n🕐 الوقت الجديد: {minutes} دقيقة ({seconds} ثانية)")
                await admin_panel_callback(update, context)
            else:
                await db_save_schedule(ch_db_id, 'interval_minutes', interval_minutes=minutes)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text("✅ تم حفظ الإعدادات")
                await schedule_menu_callback(update, context)
        except ValueError:
            await update.message.reply_text("❌ رقم غير صالح")
        return

    # ===================== حالة الساعات =====================
    if state == UserState.WAITING_INTERVAL_HOURS:
        context.user_data.pop('state', None)
        ch_db_id = context.user_data.pop('schedule_ch_id', None)
        try:
            hours = int(text)
            if hours < 1:
                hours = 1
            await db_save_schedule(ch_db_id, 'interval_hours', interval_hours=hours)
            await db_set_next_publish_date(ch_db_id, None)
            await update.message.reply_text("✅ تم حفظ الإعدادات")
        except:
            await update.message.reply_text("❌ رقم غير صالح")
        await schedule_menu_callback(update, context)
        return

    # ===================== حالة الأيام =====================
    if state == UserState.WAITING_INTERVAL_DAYS:
        context.user_data.pop('state', None)
        ch_db_id = context.user_data.pop('schedule_ch_id', None)
        try:
            days = int(text)
            if days < 1:
                days = 1
            await db_save_schedule(ch_db_id, 'interval_days', interval_days=days)
            await db_set_next_publish_date(ch_db_id, None)
            await update.message.reply_text("✅ تم حفظ الإعدادات")
        except:
            await update.message.reply_text("❌ رقم غير صالح")
        await schedule_menu_callback(update, context)
        return

    # ===================== حالة التواريخ =====================
    if state == UserState.WAITING_DATES:
        context.user_data.pop('state', None)
        ch_db_id = context.user_data.pop('schedule_ch_id', None)
        dates = text.split(',')
        valid_dates = []
        for d in dates:
            d = d.strip()
            try:
                datetime.strptime(d, '%Y-%m-%d')
                valid_dates.append(d)
            except:
                await update.message.reply_text("❌ تاريخ غير صالح")
                return
        await db_save_schedule(ch_db_id, 'dates', specific_dates=json.dumps(valid_dates))
        await db_set_next_publish_date(ch_db_id, None)
        await update.message.reply_text("✅ تم حفظ التواريخ")
        await schedule_menu_callback(update, context)
        return

    # ===================== حالة وقت النشر =====================
    if state == UserState.WAITING_PUBLISH_TIME:
        context.user_data.pop('state', None)
        ch_db_id = context.user_data.pop('schedule_ch_id', None)
        try:
            time_str = text.strip()
            hour, minute = map(int, time_str.split(':'))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                await db_set_publish_time(ch_db_id, time_str)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text("✅ تم حفظ الإعدادات")
            else:
                await update.message.reply_text("❌ وقت غير صالح")
        except:
            await update.message.reply_text("❌ وقت غير صالح")
        await schedule_menu_callback(update, context)
        return

    # ===================== حالة جدولة منشور =====================
    if state == UserState.WAITING_SCHEDULE_POST:
        context.user_data.pop('state', None)
        args = text.split()
        if len(args) < 3:
            await update.message.reply_text("❌ **صيغة غير صحيحة!**\n\nالاستخدام الصحيح:\n`YYYY-MM-DD HH:MM نص المنشور`\n\nمثال: `2024-12-31 20:00 مرحباً بالجميع!`", parse_mode="MarkdownV2")
            return
        try:
            date_str = args[0]
            time_str = args[1]
            post_text = " ".join(args[2:])
            mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if mecca_dt <= mecca_now():
                await update.message.reply_text("❌ **الوقت يجب أن يكون في المستقبل!**", parse_mode="MarkdownV2")
                return
            utc_dt = mecca_to_utc(mecca_dt)
            await db_add_scheduled_post(chat.id, post_text, utc_dt)
            await update.message.reply_text(f"✅ **تم جدولة المنشور بنجاح!**\n\n📅 التاريخ: {date_str}\n🕐 الوقت: {time_str} (بتوقيت مكة)\n📝 المنشور: {post_text[:100]}{'...' if len(post_text) > 100 else ''}", parse_mode="MarkdownV2")
        except ValueError:
            await update.message.reply_text("❌ **صيغة التاريخ أو الوقت غير صحيحة!**\n\nتأكد من الصيغة:\n• التاريخ: YYYY-MM-DD (مثال: 2024-12-31)\n• الوقت: HH:MM (مثال: 20:00)", parse_mode="MarkdownV2")
        await main_menu_callback(update, context)
        return

    # ===================== حالة أيام التذكير =====================
    if state == UserState.WAITING_REMINDER_DAYS:
        context.user_data.pop('state', None)
        try:
            days = int(text)
            if 1 <= days <= 10:
                await db_update_reminder_settings(uid, reminder_days_before=days)
                await update.message.reply_text(f"✅ تم تعيين التذكير قبل {days} يوم من انتهاء الاشتراك")
            else:
                await update.message.reply_text("❌ الرجاء إدخال رقم بين 1 و 10")
        except ValueError:
            await update.message.reply_text("❌ الرجاء إدخال رقم صحيح")
        await reminder_menu_callback(update, context)
        return

    # ===================== حالة نص التحديث =====================
    if state == UserState.WAITING_UPDATE_TEXT:
        context.user_data.pop('state', None)
        channel = await db_get_updates_channel()
        if channel:
            try:
                await context.bot.send_message(chat_id=f"@{channel}", text=text, parse_mode="HTML")
                await update.message.reply_text("✅ تم نشر التحديث في قناة التحديثات")
            except Exception as e:
                await update.message.reply_text(f"❌ فشل النشر: {str(e)[:100]}\nتأكد من أن البوت مشرف في القناة @{channel}")
        else:
            await update.message.reply_text("❌ لم يتم تعيين قناة تحديثات بعد\nاستخدم زر '⚙️ قناة التحديثات' أولاً")
        await admin_panel_callback(update, context)
        return

    # ===================== حالة تعيين قناة التحديثات =====================
    if state == UserState.WAITING_UPDATE_CHANNEL:
        context.user_data.pop('state', None)
        channel = text.strip()
        if channel.startswith('@'):
            channel = channel[1:]
        if not channel:
            await update.message.reply_text("❌ **معرف قناة غير صالح!**\nالرجاء إدخال معرف صحيح.")
            return
        try:
            if channel.startswith('-'):
                chat_obj = await context.bot.get_chat(int(channel))
            else:
                chat_obj = await context.bot.get_chat(f"@{channel}")
            if chat_obj.type != 'channel':
                await update.message.reply_text("❌ **هذا ليس قناة!**\nتأكد من أن المعرف ينتمي لقناة.")
                return
            success = await db_set_updates_channel(channel)
            if success:
                saved_channel = await db_get_updates_channel()
                if saved_channel == channel:
                    await update.message.reply_text(f"✅ **تم تعيين قناة التحديثات بنجاح!**\n📢 القناة: @{channel}")
                    try:
                        await context.bot.send_message(
                            chat_id=f"@{channel}",
                            text="✅ **تم تفعيل قناة التحديثات!**\nسيتم نشر التحديثات هنا."
                        )
                        await update.message.reply_text("✅ تم إرسال رسالة اختبار للقناة.")
                    except Exception as e:
                        await update.message.reply_text(f"⚠️ **تنبيه:** لم أتمكن من إرسال رسالة اختبار للقناة.\nتأكد من أن البوت مشرف ولديه صلاحية الإرسال.\nالخطأ: {str(e)[:100]}")
                else:
                    await update.message.reply_text("❌ **فشل حفظ القناة!** حاول مرة أخرى.")
            else:
                await update.message.reply_text("❌ **فشل حفظ القناة!** المعرف غير صالح.")
        except Exception as e:
            await update.message.reply_text(f"❌ **لا يمكن الوصول إلى القناة:**\n{str(e)[:200]}\n\n📌 تأكد من:\n• المعرف صحيح\n• البوت مشرف في القناة\n• القناة عامة (Public)")
        await admin_panel_callback(update, context)
        return

    # ===================== حالة تعيين قناة الإشتراك الإجباري =====================
    if state == UserState.WAITING_FORCE_CHANNEL:
        context.user_data.pop('state', None)
        await db_set_force_subscribe_channel(text)
        await update.message.reply_text(f"✅ تم تعيين قناة الاشتراك الإجباري: {text}")
        await admin_panel_callback(update, context)
        return

    # ===================== حالة الإرسال الجماعي =====================
    if state == UserState.WAITING_BROADCAST:
        context.user_data.pop('state', None)
        confirm_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم، أرسل", callback_data=CallbackData.ADMIN_CONFIRM_BROADCAST),
             InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.ADMIN_PANEL)]
        ])
        context.user_data['broadcast_text'] = text
        await update.message.reply_text(f"📨 **تأكيد الإرسال الجماعي**\n\nالنص المرسل:\n━━━━━━━━━━━━━━\n{text[:500]}\n━━━━━━━━━━━━━━\n\n⚠️ سيتم إرسال هذه الرسالة إلى **جميع مستخدمي البوت**\nهل أنت متأكد؟", reply_markup=confirm_kb, parse_mode="MarkdownV2")
        return

    # ===================== حالة تعيين مستخدم /sendcode =====================
    if state == UserState.WAITING_SENDCODE_USER:
        context.user_data.pop('state', None)
        try:
            target_user_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ رقم غير صالح")
            return
        await db_set_allowed_sendcode_user(target_user_id)
        await security_audit.log("SENDCODE_PERMISSION_GRANTED", uid, {"target": target_user_id}, "CRITICAL")
        await update.message.reply_text(f"✅ تم تعيين المستخدم `{target_user_id}` للاستخدام /sendcode", parse_mode="MarkdownV2")
        await admin_panel_callback(update, context)
        return

    # ===================== حالة تعيين قناة التقارير =====================
    if state == UserState.WAITING_LOG_CHANNEL:
        context.user_data.pop('state', None)
        identifier = text.strip()
        if not identifier.startswith('@') and not identifier.startswith('-100'):
            await update.message.reply_text("❌ **معرف قناة غير صالح!**\n\nالصيغ المدعومة:\n• `@username` (مثل: @my_channel)\n• `-1001234567890` (المعرف الرقمي)", parse_mode="MarkdownV2")
            context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
            return
        try:
            identifier_clean = identifier.lstrip('@')
            if identifier_clean.startswith('-100') or identifier_clean.lstrip('-').isdigit():
                chat_id = int(identifier_clean)
            else:
                chat_obj = await context.bot.get_chat(f"@{identifier_clean}")
                chat_id = chat_obj.id
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await update.message.reply_text("❌ **البوت ليس مشرفاً في هذه القناة.**", parse_mode="MarkdownV2")
                context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
                return
            if not bot_member.can_post_messages:
                await update.message.reply_text("❌ **البوت لا يملك صلاحية الإرسال في هذه القناة.**", parse_mode="MarkdownV2")
                context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
                return
            await db_set_log_channel_id(str(chat_id))
            await update.message.reply_text(f"✅ **تم تعيين قناة التقارير بنجاح!**\nمعرف القناة: `{chat_id}`", parse_mode="MarkdownV2")
            try:
                await context.bot.send_message(chat_id, "✅ **تم تفعيل نظام التقارير**")
            except:
                pass
        except Exception as e:
            await update.message.reply_text(f"❌ **لا يمكن الوصول إلى القناة:**\n{str(e)[:200]}", parse_mode="MarkdownV2")
            context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
            return
        await admin_panel_callback(update, context)
        return

    # ===================== حالة إضافة رد (كلمة مفتاحية) =====================
    if state == UserState.WAITING_KEYWORD:
        context.user_data.pop('state', None)
        keyword = text.strip().lower()
        if len(keyword) < 2:
            await update.message.reply_text("❌ الكلمة المفتاحية قصيرة جداً (يجب أن تكون حرفين على الأقل)")
            context.user_data['state'] = UserState.WAITING_KEYWORD
            return
        context.user_data['state'] = UserState.WAITING_REPLY
        context.user_data['admin_keyword'] = keyword
        await update.message.reply_text(f"📝 **إضافة رد للكلمة:** `{keyword}`\n\nأرسل الرد الذي تريده لهذه الكلمة:", parse_mode="MarkdownV2")
        return

    # ===================== حالة إضافة الرد النصي =====================
    if state == UserState.WAITING_REPLY:
        context.user_data.pop('state', None)
        if context.user_data.get('admin_del_reply'):
            kw = text.lower()
            if await db_del_reply(kw):
                await update.message.reply_text(f"✅ تم حذف رد {kw}")
            else:
                await update.message.reply_text(f"⚠️ الكلمة {kw} غير موجودة")
            context.user_data.pop('admin_del_reply', None)
            await admin_replies_callback(update, context)
            return
        kw = context.user_data.pop('admin_keyword', '')
        reply = text.strip()
        if kw and reply:
            await db_add_reply(kw, reply)
            await update.message.reply_text(f"✅ تم إضافة رد للكلمة {kw}")
        else:
            await update.message.reply_text("❌ حدث خطأ")
        await admin_replies_callback(update, context)
        return

    # ===================== حالة إضافة مشرف =====================
    if state == UserState.WAITING_ADMIN_ID_ADD:
        try:
            target_id = int(text)
            if target_id == PRIMARY_OWNER_ID:
                await update.message.reply_text("❌ لا يمكن إزالة المالك الأساسي")
            else:
                await add_bot_admin(target_id)
                await security_audit.log("ADMIN_ADDED", uid, {"target": target_id}, "CRITICAL")
                await update.message.reply_text(f"✅ تم إضافة المشرف `{target_id}`")
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return

    # ===================== حالة إزالة مشرف =====================
    if state == UserState.WAITING_ADMIN_ID_REMOVE:
        try:
            target_id = int(text)
            if target_id == PRIMARY_OWNER_ID:
                await update.message.reply_text("❌ لا يمكن إزالة المالك الأساسي")
            else:
                await remove_bot_admin(target_id)
                await security_audit.log("ADMIN_REMOVED", uid, {"target": target_id}, "CRITICAL")
                await update.message.reply_text(f"✅ تم إزالة المشرف `{target_id}`")
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return

    # ===================== حالة إضافة كلمة محظورة للمجموعة =====================
    if state == UserState.WAITING_GROUP_BANNED_WORD:
        chat_id = context.user_data.get('banned_words_chat_id')
        if chat_id:
            word = text.split()[0].lower() if text else ""
            if len(word) < 2:
                await update.message.reply_text("❌ الكلمة قصيرة جداً")
                return
            if await db_add_banned_word(word, chat_id, uid):
                await update.message.reply_text(f"✅ تم إضافة {word}")
            else:
                await update.message.reply_text(f"⚠️ {word} موجودة مسبقاً")
            context.user_data.pop('state', None)
            await banned_words_list_callback(update, context)
        return

    # ===================== حالة حذف كلمة محظورة من المجموعة =====================
    if state == UserState.WAITING_REMOVE_GROUP_BANNED_WORD:
        chat_id = context.user_data.get('banned_words_chat_id')
        if chat_id:
            word = text.lower()
            if await db_remove_banned_word(word, chat_id):
                await update.message.reply_text(f"✅ تم حذف {word}")
            else:
                await update.message.reply_text(f"⚠️ الكلمة {word} غير موجودة")
            context.user_data.pop('state', None)
            await banned_words_list_callback(update, context)
        return

    # ===================== حالة إضافة كلمة محظورة عامة =====================
    if state == UserState.WAITING_GLOBAL_BANNED_WORD:
        word = text.split()[0].lower() if text else ""
        if len(word) < 2:
            await update.message.reply_text("❌ الكلمة قصيرة جداً")
            return
        if await db_add_banned_word(word, -1, uid):
            await update.message.reply_text(f"✅ تم إضافة {word} ككلمة محظورة عامة")
        else:
            await update.message.reply_text(f"⚠️ {word} موجودة مسبقاً")
        context.user_data.pop('state', None)
        await admin_banned_words_callback(update, context)
        return

    # ===================== حالة حذف كلمة محظورة عامة =====================
    if state == UserState.WAITING_REMOVE_GLOBAL_BANNED_WORD:
        word = text.lower()
        from database import execute_db
        async def _remove(conn):
            await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
            await conn.commit()
        await execute_db(_remove)
        await update.message.reply_text(f"✅ تم حذف {word} من الكلمات المحظورة العامة")
        context.user_data.pop('state', None)
        await admin_banned_words_callback(update, context)
        return

    # ===================== حالة تغيير نسبة NSFW =====================
    if state == UserState.WAITING_NSFW_THRESHOLD:
        try:
            threshold = float(text)
            if 0 < threshold <= 100:
                global NSFW_THRESHOLD
                NSFW_THRESHOLD = threshold / 100
                os.environ["NSFW_THRESHOLD"] = str(NSFW_THRESHOLD)
                await update.message.reply_text(f"✅ تم تغيير نسبة الحساسية إلى: {threshold}%")
            else:
                await update.message.reply_text("❌ الرجاء إدخال رقم بين 1 و 100")
        except ValueError:
            await update.message.reply_text("❌ الرجاء إدخال رقم صحيح (مثال: 75)")
        context.user_data.pop('state', None)
        await nsfw_settings_callback(update, context)
        return

    # ===================== حالات الإجراءات المتقدمة (حظر، كتم، تحذير، طرد، تقييد، تثبيت، إلغاء حظر) =====================
    if state and isinstance(state, UserState) and state.name.startswith('WAITING_'):
        chat_id = context.user_data.get('advanced_chat_id')
        if not chat_id:
            return
        if state == UserState.WAITING_BAN_USER:
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                success, msg = await execute_ban(context.bot, chat_id, target_id, reason=reason, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop('state', None)
            return
        if state == UserState.WAITING_MUTE_USER:
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                minutes = context.user_data.get('mute_minutes', 60)
                success, msg = await execute_mute(context.bot, chat_id, target_id, minutes, reason=reason, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop('state', None)
            return
        if state == UserState.WAITING_WARN_USER:
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                success, msg = await execute_warn(context.bot, chat_id, target_id, uid, reason=reason)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop('state', None)
            return
        if state == UserState.WAITING_KICK_USER:
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                success, msg = await execute_kick(context.bot, chat_id, target_id, reason=reason, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop('state', None)
            return
        if state == UserState.WAITING_RESTRICT_USER:
            parts = text.split(maxsplit=1)
            reason = parts[1] if len(parts) > 1 else ""
            try:
                target_id = int(parts[0])
                success, msg = await execute_restrict(context.bot, chat_id, target_id, reason=reason, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop('state', None)
            return
        if state == UserState.WAITING_UNBAN_USER:
            try:
                target_id = int(text)
                success, msg = await execute_unban(context.bot, chat_id, target_id, moderator_id=uid)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
            context.user_data.pop('state', None)
            return
        if state == UserState.WAITING_PIN_MESSAGE:
            if update.message.reply_to_message:
                success, msg = await execute_pin(context.bot, chat_id, update.message.reply_to_message.message_id)
                await safe_send_markdown(context.bot, chat_id, msg)
            else:
                await update.message.reply_text("❌ يرجى الرد على الرسالة التي تريد تثبيتها")
            context.user_data.pop('state', None)
            return

    # ===================== وضع الدعم (كتابة تذكرة) =====================
    if context.user_data.get('support_mode') and chat.type == 'private' and text and not text.startswith('/'):
        ticket_num = await db_get_next_ticket_number()
        username = user.full_name or user.first_name or str(uid)
        clean_text = sanitize_text(text, max_length=2000)
        await db_save_ticket(uid, username, clean_text, ticket_num)
        now_mecca = mecca_now()
        now_str = now_mecca.strftime("%Y-%m-%d %H:%M:%S")
        reply_text = f"✅ **تم استلام رسالتك!**\n📋 رقم التذكرة: #{ticket_num}\n🕐 {now_str}\n\nسيتم الرد عليك في أقرب وقت ممكن."
        await update.message.reply_text(reply_text, parse_mode="MarkdownV2")
        notification_text = f"📬 **تذكرة دعم جديدة**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 المستخدم: {username}\n🆔 المعرف: `{uid}`\n📋 رقم التذكرة: #{ticket_num}\n🕐 الوقت: {now_str}\n━━━━━━━━━━━━━━━━━━━━━━\n📝 **الرسالة:**\n{clean_text[:500]}\n━━━━━━━━━━━━━━━━━━━━━━\nللرد استخدم:\n`/support_reply {uid} نص الرد`"
        await context.bot.send_message(chat_id=PRIMARY_OWNER_ID, text=notification_text, parse_mode="MarkdownV2")
        context.user_data['support_mode'] = False
        return

    # ===================== أوامر خاصة في الخاص =====================
    if chat.type == 'private':
        if text == "/start":
            await start_command_handler(update, context)
        elif text == "/cancel":
            context.user_data.pop('state', None)
            await update.message.reply_text("❌ تم الإلغاء")
            await main_menu_callback(update, context)

# ===================== دوال مساعدة (سيتم تعريفها في الملفات الأخرى) =====================

async def handle_contest_creation_states(update, context, state):
    # سيتم تنفيذها في handlers الإضافية
    return False

async def handle_sendcode_confirmation_handler(update, context):
    # سيتم تنفيذها في handlers الإضافية
    pass

async def sendcode_command_handler(update, context):
    # سيتم تنفيذها في handlers الإضافية
    pass

async def admin_replies_callback(update, context):
    # سيتم تنفيذها في handlers الإضافية
    pass

async def admin_banned_words_callback(update, context):
    # سيتم تنفيذها في handlers الإضافية
    pass

async def nsfw_settings_callback(update, context):
    # سيتم تنفيذها في handlers الإضافية
    pass
# ===================== دوال مؤقتة للتوافق =====================

async def sendcode_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ أمر /sendcode غير مفعل حالياً. تواصل مع المطور.")

async def admin_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ إدارة الردود غير مفعلة حالياً.")

async def admin_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ إدارة الكلمات المحظورة غير مفعلة حالياً.")

async def nsfw_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⚠️ إعدادات NSFW غير مفعلة حالياً.")

async def handle_contest_creation_states(update, context, state):
    return False

async def handle_sendcode_confirmation_handler(update, context):
    await update.message.reply_text("⚠️ تأكيد /sendcode غير مفعل.")

import time as time_module
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from constants import CallbackData, UserState, PRIMARY_OWNER_ID, ENABLE_2FA, ADMIN_2FA_SECRET, PYOTP_AVAILABLE, NSFW_ENABLED, NSFW_THRESHOLD
from database import db_get_allowed_sendcode_user, db_get_all_replies, db_get_banned_words, db_get_auto_reply_settings
from utils import safe_edit_markdown, safe_send_markdown, is_authorized_in_group, is_bot_admin, utc_now, utc_now_iso
# ===================== دوال مؤقتة للتوافق (يمكن تطويرها لاحقاً) =====================

async def sendcode_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    معالج أمر /sendcode - إرسال كود البوت لمستخدم معين
    """
    user_id = update.effective_user.id
    # التحقق من صلاحية المستخدم
    allowed_user = await db_get_allowed_sendcode_user()
    if user_id != PRIMARY_OWNER_ID and user_id != allowed_user:
        await update.message.reply_text("🔒 هذا الأمر غير مصرح لك.")
        return
    # التحقق من وجود 2FA
    if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE:
        context.user_data['waiting_2fa'] = True
        await update.message.reply_text("🔐 أدخل رمز المصادقة الثنائية (2FA):")
        return
    # إرسال الكود
    try:
        bot_info = await context.bot.get_me()
        code = f"@{bot_info.username}"
        await update.message.reply_text(f"📋 **كود البوت:**\n`{code}`\n\nيمكنك مشاركة هذا الكود مع الآخرين لتفعيل البوت.", parse_mode="MarkdownV2")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل إرسال الكود: {str(e)[:100]}")

async def admin_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    لوحة إدارة الردود التلقائية للمجموعات
    """
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    # عرض قائمة الردود
    replies = await db_get_all_replies()
    if not replies:
        text = "📭 لا توجد ردود مسجلة."
    else:
        text = "📋 **قائمة الردود التلقائية:**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for keyword, reply in replies[:20]:
            text += f"• `{keyword}` → {reply[:50]}{'...' if len(reply) > 50 else ''}\n"
        if len(replies) > 20:
            text += f"\n... و {len(replies)-20} رد آخر"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة رد", callback_data=CallbackData.ADMIN_ADD_REPLY),
         InlineKeyboardButton("🗑️ حذف رد", callback_data=CallbackData.ADMIN_DEL_REPLY)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def admin_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    لوحة إدارة الكلمات المحظورة العامة
    """
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    words = await db_get_banned_words(-1)  # -1 يعني عامة
    if not words:
        text = "📭 لا توجد كلمات محظورة عامة."
    else:
        text = "🚫 **الكلمات المحظورة العامة:**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for word, added_by, added_at in words[:30]:
            text += f"• `{word}` (أضيف بواسطة `{added_by}` في {added_at[:10]})\n"
        if len(words) > 30:
            text += f"\n... و {len(words)-30} كلمة أخرى"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة", callback_data=CallbackData.ADMIN_ADD_BANNED_WORD),
         InlineKeyboardButton("🗑️ حذف كلمة", callback_data=CallbackData.ADMIN_REMOVE_BANNED_WORD)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def nsfw_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    إعدادات NSFW (كشف المحتوى غير اللائق)
    """
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    status = "🟢 مفعل" if NSFW_ENABLED else "🔴 معطل"
    threshold = NSFW_THRESHOLD * 100
    text = f"🔞 **إعدادات NSFW**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 الحالة: {status}\n📊 نسبة الحساسية: {threshold:.0f}%\n\n🔍 يتم كشف المحتوى غير اللائق في الصور والفيديوهات."
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔄 تبديل الحالة", callback_data=CallbackData.NSFW_TOGGLE)],
        [InlineKeyboardButton(f"⚙️ تغيير الحساسية", callback_data=CallbackData.NSFW_THRESHOLD_SET)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def handle_contest_creation_states(update: Update, context: ContextTypes.DEFAULT_TYPE, state: UserState):
    """
    معالج حالات إنشاء المسابقات
    """
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""
    contest_data = context.user_data.get('contest_data', {})

    if state == UserState.WAITING_CONTEST_TITLE:
        contest_data['title'] = text
        context.user_data['state'] = UserState.WAITING_CONTEST_DESCRIPTION
        await update.message.reply_text("📝 **وصف المسابقة:**\nأرسل وصفاً تفصيلياً للمسابقة:")
        return True

    elif state == UserState.WAITING_CONTEST_DESCRIPTION:
        contest_data['description'] = text
        context.user_data['state'] = UserState.WAITING_CONTEST_PRIZE
        await update.message.reply_text("🎁 **جائزة المسابقة:**\nأرسل الجائزة (مثال: 100 نقطة، هدية، إلخ):")
        return True

    elif state == UserState.WAITING_CONTEST_PRIZE:
        contest_data['prize'] = text
        context.user_data['state'] = UserState.WAITING_CONTEST_END_DATE
        await update.message.reply_text("📅 **تاريخ انتهاء المسابقة:**\nأرسل التاريخ بالصيغة: `YYYY-MM-DD`\nمثال: `2025-12-31`")
        return True

    elif state == UserState.WAITING_CONTEST_END_DATE:
        try:
            end_date = datetime.strptime(text, '%Y-%m-%d')
            if end_date <= utc_now().date():
                await update.message.reply_text("❌ التاريخ يجب أن يكون في المستقبل!")
                return True
            contest_data['end_date'] = end_date.isoformat()
            # حفظ المسابقة في قاعدة البيانات
            from database import execute_db
            async def _save_contest(conn):
                await conn.execute("""
                    INSERT INTO contests (creator_id, title, description, prize, end_date, status, created_at, contest_type)
                    VALUES (?, ?, ?, ?, ?, 'active', ?, 'raffle')
                """, (user_id, contest_data['title'], contest_data['description'], contest_data['prize'], contest_data['end_date'], utc_now_iso()))
                await conn.commit()
                return conn.lastrowid
            contest_id = await execute_db(_save_contest)
            context.user_data.pop('contest_data', None)
            context.user_data.pop('state', None)
            await update.message.reply_text(f"✅ **تم إنشاء المسابقة بنجاح!**\n🆔 المعرف: {contest_id}\n📌 العنوان: {contest_data['title']}")
            await admin_panel_callback(update, context)
        except ValueError:
            await update.message.reply_text("❌ صيغة تاريخ غير صحيحة! استخدم: `YYYY-MM-DD`")
        return True

    elif state == UserState.WAITING_CONTEST_ANSWER:
        contest_id = context.user_data.get('contest_join_id')
        if not contest_id:
            await update.message.reply_text("❌ حدث خطأ، حاول مرة أخرى.")
            return True
        # حفظ مشاركة المستخدم
        from database import execute_db
        async def _save_participation(conn):
            await conn.execute("""
                INSERT OR IGNORE INTO contest_participants (user_id, contest_id, answer, joined_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, contest_id, text, utc_now_iso()))
            await conn.commit()
        await execute_db(_save_participation)
        context.user_data.pop('contest_join_id', None)
        context.user_data.pop('state', None)
        await update.message.reply_text("✅ **تم تسجيل مشاركتك في المسابقة!**\nنتمنى لك حظاً سعيداً 🍀")
        await contests_command_handler(update, context)
        return True

    return False

async def handle_sendcode_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    تأكيد المصادقة الثنائية لأمر /sendcode
    """
    user_id = update.effective_user.id
    code = update.message.text.strip()
    if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE:
        try:
            import pyotp
            totp = pyotp.TOTP(ADMIN_2FA_SECRET)
            if totp.verify(code):
                context.user_data['2fa_verified'] = True
                context.user_data['2fa_time'] = time_module.time()
                context.user_data.pop('waiting_2fa', None)
                context.user_data.pop('state', None)
                await update.message.reply_text("✅ تم التحقق من المصادقة الثنائية!")
                # إعادة توجيه لأمر sendcode
                await sendcode_command_handler(update, context)
            else:
                await update.message.reply_text("❌ رمز غير صحيح!")
                context.user_data.pop('waiting_2fa', None)
                context.user_data.pop('state', None)
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ في التحقق: {str(e)[:100]}")
            context.user_data.pop('waiting_2fa', None)
            context.user_data.pop('state', None)
    else:
        await update.message.reply_text("❌ المصادقة الثنائية غير مفعلة.")

async def admin_auto_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    إعدادات الردود التلقائية للمجموعة
    """
    query = update.callback_query
    if query:
        await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('auto_reply_chat_id')
    if not chat_id:
        await update.message.reply_text("❌ لم يتم تحديد المجموعة.")
        return
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_auto_reply_settings(chat_id)
    text = f"📝 **إعدادات الردود التلقائية**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 الحالة: {'🟢 مفعل' if settings['enabled'] else '🔴 معطل'}\n👥 المستخدمون: {'👑 مشرفين فقط' if settings['only_admins'] else '👥 الجميع'}\n🤖 تجاهل البوتات: {'✅' if settings['ignore_bots'] else '❌'}"
    if query:
        await safe_edit_markdown(query, text, reply_markup=get_auto_reply_keyboard(chat_id, settings))
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=get_auto_reply_keyboard(chat_id, settings))

