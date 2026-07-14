# -*- coding: utf-8 -*-
"""
missing.py - جميع الدوال والمعالجات والأزرار المفقودة
"""

import json
import shutil
import asyncio
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import ContextTypes

# ====================================================================
# ===================== استيراد من bot.py =====================
# ====================================================================

try:
    from bot import (
        execute_db, db_pool, db_get_channels, db_get_channel_info,
        db_set_active_channel, db_get_active_channel,
        db_get_user_groups, db_get_user_groups_count,
        db_auto_status, db_set_auto,
        db_has_active_subscription, db_has_used_trial,
        db_get_security_settings, db_set_security_settings,
        db_add_banned_word, db_remove_banned_word, db_get_banned_words,
        db_register_hidden_owner_group, db_is_hidden_owner,
        db_add_hidden_admin, db_remove_hidden_admin, db_is_hidden_admin,
        db_get_hidden_admins, db_set_chat_lock, is_chat_locked,
        db_get_updates_channel, db_set_updates_channel,
        db_get_force_subscribe_status, db_set_force_subscribe_status,
        db_get_force_subscribe_channel, db_set_force_subscribe_channel,
        db_get_log_channel_id, db_set_log_channel_id,
        db_get_allowed_sendcode_user, db_set_allowed_sendcode_user,
        db_add_reply, db_del_reply, db_get_reply, db_get_all_replies,
        db_get_next_ticket_number, db_save_ticket, db_get_all_tickets,
        db_mark_ticket_replied, db_delete_all_tickets,
        db_save_schedule, db_get_schedule, db_set_next_publish_date,
        db_set_last_publish, db_update_next_publish_date,
        db_set_publish_time,
        db_add_scheduled_post, db_get_due_scheduled_posts,
        db_update_scheduled_post_fail, db_delete_scheduled_post,
        db_get_user_level, db_update_user_level, get_top_users,
        db_create_contest, db_get_contest, db_get_active_contests,
        db_participate_in_contest, db_get_user_participation,
        db_set_contest_winner, db_get_contest_winners,
        db_delete_contest, db_get_random_participant,
        db_get_channel_stats, db_get_channel_growth,
        db_stats,
        db_get_publish_interval, db_set_publish_interval_seconds,
        db_get_auto_backup, db_set_auto_backup,
        db_all_users_channels, db_get_all_groups,
        db_get_all_bot_channels, db_get_group_rules,
        db_set_group_rules, db_delete_group_rules,
        db_register_group, db_get_user_groups,
        db_get_user_channels_count, db_get_user_unpublished_posts,
        db_get_user_total_posts, db_unpublished_count,
        db_get_next_post, db_mark_published,
        db_save_posts, db_reset_posts_to_unpublished,
        db_reset_all_posts_to_unpublished,
        db_delete_single_post, db_get_user_posts_for_channel,
        db_update_post_views, db_increment_fail_count,
        db_get_posts_count, db_get_published_count,
        db_register_user, db_get_all_users, db_update_user_cache,
        db_is_banned, db_set_ban, db_has_used_trial,
        db_activate_trial, db_activate_subscription,
        db_get_subscription_days_left,
        PRIMARY_OWNER_ID, BOT_NAME, BOT_USERNAME,
        BASE_PATH, DATA_PATH, DB_PATH, BACKUP_DIR,
        MAX_BACKUPS, DEFAULT_PUBLISH_INTERVAL_SECONDS,
        DEFAULT_RULES, ALL_REPLIES,
        get_text, safe_send, safe_edit,
        check_admin_access, is_authorized_in_group, is_telegram_admin,
        is_bot_admin, add_bot_admin, remove_bot_admin,
        execute_ban, execute_mute, execute_kick, execute_warn,
        execute_restrict, execute_pin, execute_unban, execute_unmute,
        check_bot_admin_permissions, apply_penalty,
        get_moderation_log,
        invalidate_user_cache,
        get_user_translation_language, set_user_translation_language,
        translate_text,
        create_backup, list_backups, restore_backup,
        check_database_health, check_telegram_health, get_ram_usage,
        utc_now, mecca_now, utc_now_iso, mecca_now_iso,
        mecca_to_utc, utc_to_mecca, log_error,
        CallbackData, UserState, LEVEL_REQUIREMENTS,
        settings_menu_callback, schedule_menu_callback,
        main_menu_callback, admin_panel_callback,
        admin_replies_callback, admin_banned_words_callback
    )
    print("✅ تم استيراد الدوال من bot.py")
except ImportError as e:
    print(f"⚠️ فشل استيراد الدوال: {e}")
    # تعريفات افتراضية في حالة فشل الاستيراد
    CallbackData = type('CallbackData', (), {})
    UserState = type('UserState', (), {})
    PRIMARY_OWNER_ID = 0
    BOT_NAME = "ريلاكس مانيجر"
    BOT_USERNAME = "Reelaaaxbot"

# ====================================================================
# ===================== الدوال المفقودة =====================
# ====================================================================

# 1. دوال إعادة التدوير التلقائي
async def db_get_auto_recycle(user_id: int) -> bool:
    """الحصول على حالة إعادة التدوير التلقائي"""
    async def _get(conn):
        cur = await conn.execute("SELECT auto_recycle FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_get)

async def db_set_auto_recycle(user_id: int, enabled: bool):
    """تعيين حالة إعادة التدوير التلقائي"""
    async def _set(conn):
        await conn.execute("UPDATE users SET auto_recycle=? WHERE user_id=?", (1 if enabled else 0, user_id))
        await conn.commit()
    return await execute_db(_set)

# 2. دوال قنوات البوت
async def db_register_channel(channel_id: int, channel_name: str, added_by: int):
    """تسجيل قناة للبوت"""
    async def _register(conn):
        cur = await conn.execute("SELECT channel_id FROM bot_channels WHERE channel_id=?", (channel_id,))
        if await cur.fetchone():
            await conn.execute("UPDATE bot_channels SET channel_name=?, added_by=? WHERE channel_id=?", (channel_name, added_by, channel_id))
            await conn.commit()
            return False
        await conn.execute("INSERT INTO bot_channels (channel_id, channel_name, added_by, added_at) VALUES (?, ?, ?, ?)",
                          (channel_id, channel_name, added_by, utc_now_iso()))
        await conn.commit()
        return True
    return await execute_db(_register)

# 3. دوال الإحصائيات المتقدمة
async def db_get_channel_stats_summary(user_id: int) -> dict:
    """الحصول على ملخص إحصائيات جميع قنوات المستخدم"""
    async def _get_summary(conn):
        channels = await db_get_channels(user_id)
        if not channels:
            return None
        total_posts = 0
        total_published = 0
        total_views = 0
        total_channels = len(channels)
        active_channels = 0
        best_channel = None
        best_channel_views = 0
        for ch_db_id, ch_tele_id, ch_name, banned in channels:
            if not banned:
                active_channels += 1
            stats = await db_get_channel_stats(ch_db_id)
            if stats and stats['total_posts'] > 0:
                total_posts += stats['total_posts']
                total_published += stats['published_posts']
                total_views += stats['total_views']
                if stats['total_views'] > best_channel_views:
                    best_channel_views = stats['total_views']
                    best_channel = {
                        'name': ch_name,
                        'views': stats['total_views'],
                        'posts': stats['published_posts'],
                        'avg_views': stats['avg_views']
                    }
        return {
            'total_channels': total_channels,
            'active_channels': active_channels,
            'total_posts': total_posts,
            'total_published': total_published,
            'total_views': total_views,
            'avg_views_per_channel': round(total_views / total_channels, 2) if total_channels > 0 else 0,
            'best_channel': best_channel
        }
    return await execute_db(_get_summary)

# 4. دوال الردود التلقائية المتقدمة
async def db_toggle_auto_reply(chat_id: int) -> bool:
    """تبديل حالة الردود التلقائية"""
    settings = await db_get_auto_reply_settings(chat_id)
    new_status = not settings['enabled']
    await db_set_auto_reply_enabled(chat_id, new_status)
    return new_status

async def db_set_auto_reply_only_admins(chat_id: int, only_admins: bool) -> None:
    """تعيين الردود التلقائية للمشرفين فقط"""
    async def _set(conn):
        await conn.execute(
            "UPDATE auto_reply_settings SET only_admins=? WHERE chat_id=?",
            (1 if only_admins else 0, chat_id)
        )
        await conn.commit()
    return await execute_db(_set)

async def db_set_auto_reply_enabled(chat_id: int, enabled: bool) -> None:
    """تفعيل أو تعطيل الردود التلقائية"""
    async def _set(conn):
        await conn.execute(
            "INSERT OR REPLACE INTO auto_reply_settings (chat_id, enabled) VALUES (?, ?)",
            (chat_id, 1 if enabled else 0)
        )
        await conn.commit()
    return await execute_db(_set)

async def db_get_auto_reply_settings(chat_id: int) -> dict:
    """الحصول على إعدادات الردود التلقائية"""
    async def _get(conn):
        cur = await conn.execute(
            "SELECT enabled, only_admins, ignore_bots FROM auto_reply_settings WHERE chat_id=?",
            (chat_id,)
        )
        row = await cur.fetchone()
        if row:
            return {
                'enabled': row[0] == 1,
                'only_admins': row[1] == 1,
                'ignore_bots': row[2] == 1
            }
        return {'enabled': True, 'only_admins': False, 'ignore_bots': True}
    return await execute_db(_get)

# 5. دوال المستخدمين
async def db_get_user_auto_reply_status(user_id: int) -> bool:
    """الحصول على حالة الردود التلقائية للمستخدم"""
    async def _get(conn):
        cur = await conn.execute("SELECT auto_reply_enabled FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_get)

async def db_set_user_auto_reply_status(user_id: int, enabled: bool) -> None:
    """تعيين حالة الردود التلقائية للمستخدم"""
    async def _set(conn):
        await conn.execute("UPDATE users SET auto_reply_enabled=? WHERE user_id=?", (1 if enabled else 0, user_id))
        await conn.commit()
    return await execute_db(_set)

# 6. دوال المنشورات المجدولة
async def db_add_scheduled_post(chat_id: int, text: str, publish_time: datetime) -> int:
    """إضافة منشور مجدول"""
    async def _add(conn):
        cur = await conn.execute(
            "INSERT INTO scheduled_posts (chat_id, text, publish_time) VALUES (?, ?, ?) RETURNING id",
            (chat_id, text, publish_time.isoformat())
        )
        row = await cur.fetchone()
        await conn.commit()
        return row[0] if row else None
    return await execute_db(_add)

async def db_get_due_scheduled_posts() -> list:
    """الحصول على المنشورات المجدولة المستحقة"""
    async def _get(conn):
        now = utc_now().isoformat()
        cur = await conn.execute(
            "SELECT id, chat_id, text, publish_time FROM scheduled_posts WHERE publish_time <= ? AND fail_count < 3 ORDER BY publish_time ASC",
            (now,)
        )
        rows = await cur.fetchall()
        return [{'id': row[0], 'chat_id': row[1], 'text': row[2], 'publish_time': row[3]} for row in rows]
    return await execute_db(_get)

async def db_update_scheduled_post_fail(post_id: int) -> None:
    """زيادة عدد فشل المنشور المجدول"""
    async def _update(conn):
        await conn.execute("UPDATE scheduled_posts SET fail_count = fail_count + 1 WHERE id=?", (post_id,))
        await conn.commit()
    return await execute_db(_update)

async def db_delete_scheduled_post(post_id: int) -> None:
    """حذف منشور مجدول"""
    async def _delete(conn):
        await conn.execute("DELETE FROM scheduled_posts WHERE id=?", (post_id,))
        await conn.commit()
    return await execute_db(_delete)

# 7. دوال عرض المنشورات
async def db_update_post_views(post_id: int, views: int) -> None:
    """تحديث عدد مشاهدات المنشور"""
    async def _update(conn):
        await conn.execute("UPDATE posts SET views_count = views_count + ? WHERE id=?", (views, post_id))
        await conn.commit()
    return await execute_db(_update)

async def db_get_due_channels() -> list:
    """الحصول على القنوات المستحقة للنشر"""
    async def _get(conn):
        now = utc_now().isoformat()
        cur = await conn.execute("""
            SELECT uc.id, uc.channel_id, u.user_id
            FROM user_channels uc
            JOIN users u ON uc.user_id = u.user_id
            LEFT JOIN schedule s ON uc.id = s.channel_db_id
            WHERE u.auto_publish = 1
              AND u.banned = 0
              AND uc.banned = 0
              AND (s.next_publish_date IS NULL OR s.next_publish_date <= ?)
            ORDER BY COALESCE(s.next_publish_date, '1970-01-01') ASC
            LIMIT 20
        """, (now,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_clean_expired_codes() -> None:
    """تنظيف رموز التحقق المنتهية"""
    async def _clean(conn):
        await conn.execute("DELETE FROM verification_codes WHERE expires_at < ?", (utc_now().isoformat(),))
        await conn.commit()
    return await execute_db(_clean)

async def db_get_verification_code(user_id: int) -> Optional[str]:
    """الحصول على رمز التحقق للمستخدم"""
    async def _get(conn):
        cur = await conn.execute(
            "SELECT code FROM verification_codes WHERE user_id = ? AND expires_at > ?",
            (user_id, utc_now().isoformat())
        )
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

# ====================================================================
# ===================== دالة sendcode =====================
# ====================================================================

async def sendcode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال رمز التحقق للمستخدم"""
    user_id = update.effective_user.id
    
    # التحقق من صلاحية المستخدم
    allowed_user = await db_get_allowed_sendcode_user()
    if allowed_user and user_id != allowed_user and user_id != PRIMARY_OWNER_ID:
        await update.message.reply_text("❌ غير مصرح لك باستخدام هذا الأمر.")
        return
    
    try:
        # إنشاء رمز عشوائي مكون من 6 أرقام
        code = str(random.randint(100000, 999999))
        
        # تخزين الرمز في قاعدة البيانات
        async def _store_code(conn):
            expires_at = (utc_now() + timedelta(minutes=5)).isoformat()
            await conn.execute(
                "INSERT OR REPLACE INTO verification_codes (user_id, code, expires_at) VALUES (?, ?, ?)",
                (user_id, code, expires_at)
            )
            await conn.commit()
        await execute_db(_store_code)
        
        await update.message.reply_text(
            f"🔐 **رمز التحقق الخاص بك:**\n`{code}`\n\n"
            "يرجى استخدام هذا الرمز للتحقق من هويتك.\n"
            "⏰ هذا الرمز صالح لمدة 5 دقائق.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        log_error(e, {'user_id': user_id, 'command': 'sendcode'})
        await update.message.reply_text("❌ فشل إرسال رمز التحقق. يرجى المحاولة مرة أخرى.")

# ====================================================================
# ===================== دوال إعدادات المجموعة =====================
# ====================================================================

async def db_get_group_settings(chat_id: int) -> dict:
    """الحصول على إعدادات المجموعة"""
    async def _get(conn):
        cur = await conn.execute("""
            SELECT settings FROM group_settings WHERE chat_id = ?
        """, (chat_id,))
        row = await cur.fetchone()
        if row:
            try:
                return json.loads(row[0])
            except:
                return {}
        return {}
    return await execute_db(_get)

async def db_set_group_settings(chat_id: int, settings: dict) -> None:
    """تعيين إعدادات المجموعة"""
    async def _set(conn):
        await conn.execute(
            "INSERT OR REPLACE INTO group_settings (chat_id, settings) VALUES (?, ?)",
            (chat_id, json.dumps(settings))
        )
        await conn.commit()
    return await execute_db(_set)

# ====================================================================
# ===================== معالجات الأوامر المفقودة =====================
# ====================================================================

# 1. أوامر القوانين
async def set_rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين قوانين المجموعة"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/set_rules نص القوانين`")
        return
    rules_text = " ".join(args)
    await db_set_group_rules(chat_id, rules_text, user_id)
    await update.message.reply_text("✅ **تم تحديث قوانين المجموعة!**")

async def reset_rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعادة تعيين قوانين المجموعة"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    await db_delete_group_rules(chat_id)
    await update.message.reply_text("✅ **تم إعادة تعيين القوانين للافتراضي!**")

# 2. أوامر الإدارة
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حظر مستخدم"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("📝 **الاستخدام:**\n`/ban user_id [السبب]`")
        return
    try:
        target_id = int(args[0])
        reason = " ".join(args[1:]) if len(args) > 1 else ""
        success, msg = await execute_ban(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
        await safe_send(context.bot, chat_id, msg)
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح")

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """كتم مستخدم"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("📝 **الاستخدام:**\n`/mute user_id [المدة_بالدقائق] [السبب]`")
        return
    try:
        target_id = int(args[0])
        duration = int(args[1]) if len(args) > 1 else 60
        reason = " ".join(args[2:]) if len(args) > 2 else ""
        success, msg = await execute_mute(context.bot, chat_id, target_id, duration, reason=reason, moderator_id=user_id)
        await safe_send(context.bot, chat_id, msg)
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح")

async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء كتم مستخدم"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("📝 **الاستخدام:**\n`/unmute user_id`")
        return
    try:
        target_id = int(args[0])
        success, msg = await execute_unmute(context.bot, chat_id, target_id, moderator_id=user_id)
        await safe_send(context.bot, chat_id, msg)
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح")

async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحذير مستخدم"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("📝 **الاستخدام:**\n`/warn user_id [السبب]`")
        return
    try:
        target_id = int(args[0])
        reason = " ".join(args[1:]) if len(args) > 1 else ""
        success, msg = await execute_warn(context.bot, chat_id, target_id, user_id, reason=reason)
        await safe_send(context.bot, chat_id, msg)
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح")

async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """طرد مستخدم"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("📝 **الاستخدام:**\n`/kick user_id [السبب]`")
        return
    try:
        target_id = int(args[0])
        reason = " ".join(args[1:]) if len(args) > 1 else ""
        success, msg = await execute_kick(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
        await safe_send(context.bot, chat_id, msg)
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح")

async def restrict_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تقييد مستخدم"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("📝 **الاستخدام:**\n`/restrict user_id [السبب]`")
        return
    try:
        target_id = int(args[0])
        reason = " ".join(args[1:]) if len(args) > 1 else ""
        success, msg = await execute_restrict(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
        await safe_send(context.bot, chat_id, msg)
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح")

async def pin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تثبيت رسالة"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("📌 **الاستخدام:**\nقم بالرد على الرسالة التي تريد تثبيتها ثم أرسل /pin")
        return
    success, msg = await execute_pin(context.bot, chat_id, update.message.reply_to_message.message_id)
    await safe_send(context.bot, chat_id, msg)

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء حظر مستخدم"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("📝 **الاستخدام:**\n`/unban user_id`")
        return
    try:
        target_id = int(args[0])
        success, msg = await execute_unban(context.bot, chat_id, target_id, moderator_id=user_id)
        await safe_send(context.bot, chat_id, msg)
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح")

# 3. أوامر الكلمات المحظورة
async def add_banned_word_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة كلمة محظورة"""
    user_id = update.effective_user.id
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("📝 **الاستخدام:**\n`/add_banned_word كلمة`")
        return
    word = args[0].lower()
    if len(word) < 2:
        await update.message.reply_text("❌ الكلمة قصيرة جداً")
        return
    if await db_add_banned_word(word, -1, user_id):
        await update.message.reply_text(f"✅ تم إضافة {word} ككلمة محظورة عامة")
    else:
        await update.message.reply_text(f"⚠️ {word} موجودة مسبقاً")

async def remove_banned_word_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف كلمة محظورة"""
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("📝 **الاستخدام:**\n`/remove_banned_word كلمة`")
        return
    word = args[0].lower()
    async def _remove(conn):
        await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
        await conn.commit()
    await execute_db(_remove)
    await update.message.reply_text(f"✅ تم حذف {word} من الكلمات المحظورة العامة")

# 4. أوامر المشرفين المخفيين
async def register_hidden_owner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تسجيل مالك مخفي"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    if await db_is_hidden_owner(chat_id, user_id):
        await update.message.reply_text("⚠️ أنت مسجل بالفعل كمالك مخفي")
        return
    await db_register_hidden_owner_group(chat_id, user_id)
    await invalidate_user_cache(user_id=user_id, chat_id=chat_id)
    await update.message.reply_text("✅ تم تسجيل المالك المخفي بنجاح")

async def add_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة مشرف مخفي"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/add_hidden_admin user_id`")
        return
    try:
        admin_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح.")
        return
    if admin_id == user_id:
        await update.message.reply_text("❌ لا يمكن إضافة نفسك كمشرف مخفي.")
        return
    if await db_is_hidden_admin(chat_id, admin_id):
        await update.message.reply_text("⚠️ هذا المستخدم مشرف مخفي بالفعل.")
        return
    if await db_add_hidden_admin(chat_id, admin_id, user_id):
        await invalidate_user_cache(user_id=admin_id, chat_id=chat_id)
        await update.message.reply_text(f"✅ تم إضافة المشرف المخفي `{admin_id}` بنجاح")
    else:
        await update.message.reply_text("❌ فشل إضافة المشرف المخفي.")

async def remove_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إزالة مشرف مخفي"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/remove_hidden_admin user_id`")
        return
    try:
        admin_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح.")
        return
    if not await db_is_hidden_admin(chat_id, admin_id):
        await update.message.reply_text("⚠️ هذا المستخدم ليس مشرفاً مخفياً.")
        return
    if await db_remove_hidden_admin(chat_id, admin_id):
        await invalidate_user_cache(user_id=admin_id, chat_id=chat_id)
        await update.message.reply_text(f"✅ تم إزالة المشرف المخفي `{admin_id}` بنجاح")
    else:
        await update.message.reply_text("❌ فشل إزالة المشرف المخفي.")

async def list_hidden_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض المشرفين المخفيين"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    admins = await db_get_hidden_admins(chat_id)
    if not admins:
        await update.message.reply_text("📭 لا يوجد مشرفين مخفيين في هذه المجموعة")
        return
    text = "🔒 **قائمة المشرفين المخفيين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for admin in admins:
        admin_id = admin['admin_id']
        added_by = admin['added_by']
        added_at = admin['added_at']
        try:
            dt = datetime.fromisoformat(added_at)
            dt_mecca = utc_to_mecca(dt)
            date_str = dt_mecca.strftime("%Y-%m-%d %H:%M")
        except:
            date_str = added_at or "غير معروف"
        text += f"• `{admin_id}` (أضيف بواسطة `{added_by}`)\n   🕐 {date_str}\n"
    await safe_send(context.bot, user_id, text)

# 5. أوامر أخرى
async def rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض الرتبة الحالية"""
    user_id = update.effective_user.id
    data = await db_get_user_level(user_id)
    points = data['points']
    level = data['level']
    next_points = LEVEL_REQUIREMENTS.get(level + 1, points)
    points_needed = next_points - points if next_points > points else 0
    text = f"📊 **رتبتك الحالية**\n━━━━━━━━━━━━━━\n⭐ **المستوى:** {level}\n📈 **النقاط:** {points}\n📌 **المتبقي للمستوى التالي:** {points_needed}"
    await safe_send(context.bot, user_id, text)

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض أفضل 10 مستخدمين"""
    user_id = update.effective_user.id
    top_users = await get_top_users(10)
    if not top_users:
        await update.message.reply_text("📭 لا توجد نقاط مسجدة بعد.")
        return
    text = "🏆 **أفضل 10 مستخدمين**\n━━━━━━━━━━━━━━\n"
    for idx, (uid, points, level) in enumerate(top_users, 1):
        try:
            user = await context.bot.get_chat(uid)
            name = user.first_name or str(uid)
        except:
            name = str(uid)
        text += f"{idx}. {name} → المستوى {level} ({points} نقطة)\n"
    await safe_send(context.bot, user_id, text)

async def update_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحديث المشرفين في المجموعة"""
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        updated_count = 0
        for admin in admins:
            admin_user = admin.user
            if admin_user.is_bot:
                continue
            admin_id = admin_user.id
            if admin.status == 'creator':
                if not await db_is_hidden_owner(chat_id, admin_id):
                    await db_register_hidden_owner_group(chat_id, admin_id)
                    updated_count += 1
            elif admin.status == 'administrator':
                if not await db_is_hidden_admin(chat_id, admin_id) and admin_id != PRIMARY_OWNER_ID:
                    await db_add_hidden_admin(chat_id, admin_id, user_id)
                    updated_count += 1
        await invalidate_user_cache(chat_id=chat_id)
        if updated_count > 0:
            await update.message.reply_text(f"✅ **تم تحديث المشرفين بنجاح!**\n\nتم تحديث {updated_count} مشرف في هذه المجموعة.")
        else:
            await update.message.reply_text("ℹ️ **لا توجد تغييرات في المشرفين.**")
    except Exception as e:
        await update.message.reply_text(f"❌ **فشل تحديث المشرفين.**\n{str(e)[:100]}")

# ====================================================================
# ===================== الكولباك المفقودة =====================
# ====================================================================

async def settings_toggle_auto_recycle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل حالة إعادة التدوير التلقائي"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    cur = await db_get_auto_recycle(user_id)
    new_status = not cur
    await db_set_auto_recycle(user_id, new_status)
    status = "مفعل" if new_status else "معطل"
    await safe_edit(query, f"✅ تم تغيير إعادة التدوير التلقائي إلى: {status}")
    await settings_menu_callback(update, context)

async def schedule_set_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين أيام النشر"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['selected_days_ch'] = ch_db_id
    context.user_data['selected_days'] = []
    context.user_data['state'] = UserState.SELECTING_DAYS
    day_names = ['الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
    keyboard = []
    for i in range(0, 7, 3):
        row = []
        for j in range(3):
            if i + j < 7:
                idx = i + j
                row.append(InlineKeyboardButton(f"☐ {day_names[idx]}", callback_data=f"schedule:day_select:{idx}"))
        keyboard.append(row)
    keyboard.append([
        InlineKeyboardButton("✅ حفظ", callback_data="schedule:save_days"),
        InlineKeyboardButton("🔙 رجوع", callback_data="back")
    ])
    await safe_edit(query, "📅 **اختر أيام النشر:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def schedule_day_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار يوم للنشر"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    day = int(query.data.split(":")[-1])
    selected = context.user_data.get('selected_days', [])
    if day in selected:
        selected.remove(day)
    else:
        selected.append(day)
    context.user_data['selected_days'] = selected
    await schedule_set_days_callback(update, context)

async def schedule_save_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حفظ أيام النشر"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch = context.user_data.get('selected_days_ch')
    if ch:
        days_json = json.dumps(context.user_data.get('selected_days', []))
        await db_save_schedule(ch, 'days', days_of_week=days_json)
        await db_set_next_publish_date(ch, None)
        context.user_data.pop('selected_days_ch', None)
        context.user_data.pop('selected_days', None)
        context.user_data.pop('state', None)
        await safe_edit(query, "✅ تم حفظ أيام النشر")
        await schedule_menu_callback(update, context)

async def schedule_set_dates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين تواريخ محددة للنشر"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_DATES
    context.user_data['schedule_ch_id'] = ch_db_id
    await safe_edit(query, "📅 أرسل التواريخ مفصولة بفواصل (مثال: 2024-12-25,2025-01-01)")

async def schedule_set_publish_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين وقت النشر"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_PUBLISH_TIME
    context.user_data['schedule_ch_id'] = ch_db_id
    await safe_edit(query, "🕐 أرسل وقت النشر (مثال: 14:30)")

async def set_interval_minutes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين الفاصل الزمني بالدقائق"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_INTERVAL_MINUTES
    context.user_data['schedule_ch_id'] = ch_db_id
    await safe_edit(query, "⏱️ أرسل عدد الدقائق بين كل منشور وآخر:")

async def set_interval_hours_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين الفاصل الزمني بالساعات"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_INTERVAL_HOURS
    context.user_data['schedule_ch_id'] = ch_db_id
    await safe_edit(query, "⏱️ أرسل عدد الساعات بين كل منشور وآخر:")

async def set_interval_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين الفاصل الزمني بالأيام"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_INTERVAL_DAYS
    context.user_data['schedule_ch_id'] = ch_db_id
    await safe_edit(query, "📆 أرسل عدد الأيام بين كل منشور وآخر:")

async def schedule_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """قائمة الجدولة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    schedule = await db_get_schedule(ch_db_id)
    text = f"📅 **إعدادات الجدولة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📌 النوع: {schedule['type']}\n"
    if schedule['type'] == 'interval_minutes':
        text += f"⏱️ الفاصل: {schedule['interval_minutes']} دقيقة\n"
    elif schedule['type'] == 'interval_hours':
        text += f"⏱️ الفاصل: {schedule['interval_hours']} ساعة\n"
    elif schedule['type'] == 'interval_days':
        text += f"📆 الفاصل: {schedule['interval_days']} يوم\n"
    text += f"🕐 وقت النشر: {schedule['publish_time']}\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ دقائق", callback_data=f"schedule:set_interval_minutes:{ch_db_id}"),
         InlineKeyboardButton("⏱️ ساعات", callback_data=f"schedule:set_interval_hours:{ch_db_id}")],
        [InlineKeyboardButton("📆 أيام", callback_data=f"schedule:set_interval_days:{ch_db_id}"),
         InlineKeyboardButton("📅 أيام أسبوع", callback_data=f"schedule:set_days:{ch_db_id}")],
        [InlineKeyboardButton("📆 تواريخ محددة", callback_data=f"schedule:set_dates:{ch_db_id}"),
         InlineKeyboardButton("🕐 وقت النشر", callback_data=f"schedule:set_publish_time:{ch_db_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def delete_single_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف منشور واحد"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    post_id = int(query.data.split(":")[-1])
    if await db_delete_single_post(post_id, user_id, 0):
        await safe_edit(query, "✅ تم حذف المنشور")
    else:
        await safe_edit(query, "❌ فشل حذف المنشور")

async def confirm_clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأكيد حذف جميع المنشورات"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، احذف الكل", callback_data=f"posts:clear_all:{ch_db_id}"),
         InlineKeyboardButton("❌ إلغاء", callback_data="back")]
    ])
    await safe_edit(query, "⚠️ هل أنت متأكد من حذف جميع المنشورات غير المنشورة؟", reply_markup=keyboard)

async def clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف جميع المنشورات"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    await db_reset_all_posts_to_unpublished(ch_db_id)
    await safe_edit(query, "✅ تم حذف جميع المنشورات")

async def security_banned_words_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """قائمة الكلمات المحظورة للأمان"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['banned_words_chat_id'] = chat_id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"banned_words:add:{chat_id}"),
         InlineKeyboardButton("📋 عرض الكلمات", callback_data=f"banned_words:list:{chat_id}")],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=f"banned_words:remove:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"groups:settings:{chat_id}")]
    ])
    await safe_edit(query, "🚫 إدارة الكلمات المحظورة للمجموعة", reply_markup=keyboard)

async def banned_words_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة كلمة محظورة للمجموعة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    await safe_edit(query, "➕ أرسل الكلمة التي تريد إضافتها للكلمات المحظورة:")

async def banned_words_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض الكلمات المحظورة في المجموعة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    words = await db_get_banned_words(chat_id)
    if not words:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"security:banned_words_menu:{chat_id}")]])
        await safe_edit(query, "📭 لا توجد كلمات محظورة في هذه المجموعة.", reply_markup=keyboard)
        return
    text = "🚫 **الكلمات المحظورة في المجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for word, added_by, added_at in words[:20]:
        text += f"• `{word}` (أضيف بواسطة {added_by})\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"security:banned_words_menu:{chat_id}")]])
    await safe_edit(query, text, reply_markup=keyboard)

async def banned_words_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف كلمة محظورة من المجموعة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_REMOVE_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    await safe_edit(query, "🗑️ أرسل الكلمة التي تريد حذفها من الكلمات المحظورة:")

async def penalty_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """قائمة العقوبات"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 طرد", callback_data=f"penalty:kick:{chat_id}"),
         InlineKeyboardButton("🛑 حظر", callback_data=f"penalty:ban:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم", callback_data=f"penalty:mute:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"groups:settings:{chat_id}")]
    ])
    await safe_edit(query, "⚖️ **اختر العقوبة التلقائية:**", reply_markup=keyboard)

async def penalty_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين عقوبة الطرد"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    await db_set_security_settings(chat_id, auto_penalty='kick')
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"groups:settings:{chat_id}")]])
    await safe_edit(query, "✅ تم تعيين العقوبة التلقائية إلى: **طرد**", reply_markup=keyboard)

async def penalty_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين عقوبة الحظر"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    await db_set_security_settings(chat_id, auto_penalty='ban')
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"groups:settings:{chat_id}")]])
    await safe_edit(query, "✅ تم تعيين العقوبة التلقائية إلى: **حظر**", reply_markup=keyboard)

async def penalty_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين عقوبة الكتم"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['penalty_chat_id'] = chat_id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ 5 دقائق", callback_data=f"group_mute_duration:5:{chat_id}"),
         InlineKeyboardButton("⏱️ 30 دقيقة", callback_data=f"group_mute_duration:30:{chat_id}")],
        [InlineKeyboardButton("⏱️ 1 ساعة", callback_data=f"group_mute_duration:60:{chat_id}"),
         InlineKeyboardButton("⏱️ 12 ساعة", callback_data=f"group_mute_duration:720:{chat_id}")],
        [InlineKeyboardButton("📆 يوم", callback_data=f"group_mute_duration:1440:{chat_id}"),
         InlineKeyboardButton("📆 أسبوع", callback_data=f"group_mute_duration:10080:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم دائم", callback_data=f"group_mute_duration:permanent:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"penalty_menu:{chat_id}")]
    ])
    await safe_edit(query, "🔇 **اختر مدة الكتم:**", reply_markup=keyboard)

async def penalty_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين مدة الكتم للعقوبة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data_parts = query.data.split(":")
    if len(data_parts) == 3:
        duration = data_parts[1]
        chat_id = int(data_parts[2])
        if not await check_admin_access(update, context):
            await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
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
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"groups:settings:{chat_id}")]])
        await safe_edit(query, f"✅ تم تعيين العقوبة التلقائية إلى: **كتم {text}**", reply_markup=keyboard)

async def advanced_actions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """قائمة الإجراءات المتقدمة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if chat_id == 0:
        await safe_edit(query, "⚠️ يرجى اختيار مجموعة أولاً")
        return
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 حظر", callback_data=f"group_action:ban:{chat_id}"),
         InlineKeyboardButton("🔇 كتم", callback_data=f"group_action:mute:{chat_id}")],
        [InlineKeyboardButton("⚠️ تحذير", callback_data=f"group_action:warn:{chat_id}"),
         InlineKeyboardButton("👢 طرد", callback_data=f"group_action:kick:{chat_id}")],
        [InlineKeyboardButton("🔒 تقييد", callback_data=f"group_action:restrict:{chat_id}"),
         InlineKeyboardButton("📌 تثبيت", callback_data=f"group_action:pin:{chat_id}")],
        [InlineKeyboardButton("🔓 إلغاء حظر", callback_data=f"group_action:unban:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"groups:settings:{chat_id}")]
    ])
    await safe_edit(query, "🛠️ **الإجراءات المتقدمة**", reply_markup=keyboard)

async def group_action_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حظر مستخدم من الإجراءات المتقدمة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_BAN_USER
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "🚫 أرسل معرف المستخدم لحظره:\n`/ban 123456789 السبب`")

async def group_action_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """كتم مستخدم من الإجراءات المتقدمة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ 5 دقائق", callback_data=f"adv_mute_duration:5:{chat_id}"),
         InlineKeyboardButton("⏱️ 30 دقيقة", callback_data=f"adv_mute_duration:30:{chat_id}")],
        [InlineKeyboardButton("⏱️ 1 ساعة", callback_data=f"adv_mute_duration:60:{chat_id}"),
         InlineKeyboardButton("⏱️ 12 ساعة", callback_data=f"adv_mute_duration:720:{chat_id}")],
        [InlineKeyboardButton("📆 يوم", callback_data=f"adv_mute_duration:1440:{chat_id}"),
         InlineKeyboardButton("📆 أسبوع", callback_data=f"adv_mute_duration:10080:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم دائم", callback_data=f"adv_mute_duration:0:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"advanced_actions:{chat_id}")]
    ])
    await safe_edit(query, "🔇 **اختر مدة الكتم:**", reply_markup=keyboard)

async def advanced_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين مدة الكتم للإجراءات المتقدمة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    parts = query.data.split(":")
    if len(parts) == 3:
        minutes = int(parts[1])
        chat_id = int(parts[2])
        if not await check_admin_access(update, context):
            await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
            return
        context.user_data['mute_minutes'] = minutes
        context.user_data['state'] = UserState.WAITING_MUTE_USER
        context.user_data['advanced_chat_id'] = chat_id
        if minutes == 0:
            msg = "🔇 **كتم دائم**\nأرسل معرف المستخدم:\n`/mute 123456789`"
        elif minutes < 60:
            msg = f"🔇 **كتم {minutes} دقيقة**\nأرسل معرف المستخدم:\n`/mute 123456789`"
        elif minutes < 1440:
            msg = f"🔇 **كتم {minutes // 60} ساعة**\nأرسل معرف المستخدم:\n`/mute 123456789`"
        else:
            msg = f"🔇 **كتم {minutes // 1440} يوم**\nأرسل معرف المستخدم:\n`/mute 123456789`"
        await safe_edit(query, msg)

async def group_action_warn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحذير مستخدم من الإجراءات المتقدمة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_WARN_USER
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "⚠️ أرسل معرف المستخدم لتحذيره:\n`/warn 123456789 السبب`")

async def group_action_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """طرد مستخدم من الإجراءات المتقدمة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_KICK_USER
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "👢 أرسل معرف المستخدم لطرده:\n`/kick 123456789 السبب`")

async def group_action_restrict_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تقييد مستخدم من الإجراءات المتقدمة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_RESTRICT_USER
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "🔒 أرسل معرف المستخدم لتقييده:\n`/restrict 123456789`")

async def group_action_pin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تثبيت رسالة من الإجراءات المتقدمة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_PIN_MESSAGE
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "📌 قم بالرد على الرسالة ثم أرسل /pin")

async def group_action_log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض سجل الإجراءات"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    text = await get_moderation_log(chat_id, 20)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"groups:settings:{chat_id}")]])
    await safe_edit(query, text, reply_markup=keyboard)

async def group_action_unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء حظر مستخدم من الإجراءات المتقدمة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_UNBAN_USER
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "🔓 أرسل معرف المستخدم لإلغاء حظره:\n`/unban 123456789`")

async def panel_lock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """قفل المجموعة من اللوحة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if await check_admin_access(update, context):
        await db_set_chat_lock(chat_id, True, user_id)
        await safe_edit(query, "🔒 تم قفل المجموعة")
    else:
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")

async def panel_unlock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """فتح المجموعة من اللوحة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if await check_admin_access(update, context):
        await db_set_chat_lock(chat_id, False)
        await safe_edit(query, "🔓 تم فتح المجموعة")
    else:
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")

async def panel_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إغلاق لوحة التحكم"""
    query = update.callback_query
    await query.answer()
    await query.message.delete()

async def check_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التحقق من الاشتراك"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    enabled = await db_get_force_subscribe_status()
    channel = await db_get_force_subscribe_channel()
    if enabled and channel:
        await safe_edit(query, "✅ تم التحقق! أنت مشترك الآن.")
    else:
        await safe_edit(query, "⚠️ الاشتراك الإجباري غير مفعل")

async def publish_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نشر في جميع القنوات"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    channels = await db_get_channels(user_id)
    if not channels:
        await safe_edit(query, "📭 لا توجد قنوات للنشر فيها.")
        return
    await safe_edit(query, "📤 جاري النشر في جميع القنوات...")
    results = []
    success_count = 0
    fail_count = 0
    for ch_db_id, ch_tele_id, ch_name, banned in channels:
        if banned:
            results.append(f"⛔ {ch_name}: قناة محظورة")
            continue
        post = await db_get_next_post(ch_db_id)
        if not post:
            results.append(f"📭 {ch_name}: لا توجد منشورات")
            continue
        try:
            ch_info = await db_get_channel_info(ch_db_id)
            if post['media_type'] == 'photo' and post['media_file_id']:
                await context.bot.send_photo(ch_info[0], post['media_file_id'], caption=post['text'])
            else:
                await context.bot.send_message(ch_info[0], post['text'])
            await db_mark_published(post['id'])
            results.append(f"✅ {ch_name}: تم النشر بنجاح")
            success_count += 1
        except Exception as e:
            results.append(f"❌ {ch_name}: {str(e)[:50]}")
            fail_count += 1
        await asyncio.sleep(1)
    summary = f"📊 **نتائج النشر**\n✅ نجح: {success_count}\n❌ فشل: {fail_count}\n\n"
    result_text = summary + "\n".join(results[:20])
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]])
    await safe_edit(query, result_text, reply_markup=keyboard)

async def channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إحصائيات القناة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    try:
        channel_db_id = int(query.data.split(":")[-1])
    except:
        channel_db_id = context.user_data.get('channel_stats_id')
    if not channel_db_id:
        await safe_edit(query, "⚠️ لم يتم تحديد القناة.")
        return
    channels = await db_get_channels(user_id)
    if not any(ch[0] == channel_db_id for ch in channels):
        await query.answer("❌ هذه القناة ليست لك", show_alert=True)
        return
    stats = await db_get_channel_stats(channel_db_id)
    ch_info = await db_get_channel_info(channel_db_id)
    channel_name = ch_info[1] if ch_info else "القناة"
    if stats['total_posts'] == 0:
        text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد منشورات بعد"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data=f"channel_stats_refresh:{channel_db_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ])
        await safe_edit(query, text, reply_markup=keyboard)
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
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"channel_stats_refresh:{channel_db_id}")],
        [InlineKeyboardButton("📈 نمو القناة", callback_data=f"channel_growth:{channel_db_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def channel_growth_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض نمو القناة"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    try:
        channel_db_id = int(query.data.split(":")[-1])
    except:
        channel_db_id = context.user_data.get('channel_stats_id')
    if not channel_db_id:
        await safe_edit(query, "⚠️ لم يتم تحديد القناة.")
        return
    channels = await db_get_channels(user_id)
    if not any(ch[0] == channel_db_id for ch in channels):
        await query.answer("❌ هذه القناة ليست لك", show_alert=True)
        return
    growth = await db_get_channel_growth(channel_db_id, days=30)
    ch_info = await db_get_channel_info(channel_db_id)
    channel_name = ch_info[1] if ch_info else "القناة"
    if not growth['dates']:
        text = f"📈 **نمو {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\nلا توجد بيانات كافية."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"channel_stats:{channel_db_id}")]])
        await safe_edit(query, text, reply_markup=keyboard)
        return
    text = f"📈 **نمو {channel_name} (آخر 30 يوم)**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📝 إجمالي المنشورات: {growth['total_posts']}\n"
    text += f"👁️ إجمالي المشاهدات: {growth['total_views']}\n"
    text += "\n📅 **التفاصيل اليومية:**\n"
    for i, (date, count, views) in enumerate(zip(growth['dates'], growth['counts'], growth['views'])):
        if i >= 10:
            break
        text += f"• {date}: {count} منشورات، {views} مشاهدة\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 العودة للإحصائيات", callback_data=f"channel_stats:{channel_db_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def channel_stats_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحديث إحصائيات القناة"""
    await channel_stats_callback(update, context)

async def my_channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض ملخص قنواتي"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    summary = await db_get_channel_stats_summary(user_id)
    if not summary:
        text = "📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد قنوات مسجلة."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة قناة", callback_data="channels:add")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ])
        await safe_edit(query, text, reply_markup=keyboard)
        return
    text = f"📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📡 عدد القنوات: {summary['total_channels']}\n"
    text += f"✅ القنوات النشطة: {summary['active_channels']}\n"
    text += f"📝 إجمالي المنشورات: {summary['total_posts']}\n"
    text += f"✅ المنشورة: {summary['total_published']}\n"
    text += f"👁️ إجمالي المشاهدات: {summary['total_views']}\n"
    if summary['best_channel']:
        text += f"\n🏆 **أفضل قناة:**\n"
        text += f"• {summary['best_channel']['name']}\n"
        text += f"• مشاهدات: {summary['best_channel']['views']}\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 عرض القنوات", callback_data="channels:my_channels")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_auto_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لوحة إدارة الردود التلقائية"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await safe_edit(query, "📭 لا توجد مجموعات مسجلة.")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        keyboard.append([InlineKeyboardButton(f"📝 {gname[:30]}", callback_data=f"admin_auto_reply_select:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin:panel")])
    await safe_edit(query, "📝 **إدارة الردود التلقائية**\nاختر مجموعة:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_auto_reply_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اختيار مجموعة لإدارة الردود التلقائية"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_auto_reply_settings(chat_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 الردود التلقائية: {'🟢 مفعل' if settings['enabled'] else '🔴 معطل'}", callback_data=f"auto_reply_toggle:{chat_id}")],
        [InlineKeyboardButton(f"👥 المستخدمون: {'👑 مشرفين فقط' if settings['only_admins'] else '👥 الجميع'}", callback_data=f"auto_reply_admins:{chat_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"groups:settings:{chat_id}")]
    ])
    await safe_edit(query, f"📝 **إعدادات الردود**", reply_markup=keyboard)

async def auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل حالة الردود التلقائية"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    new_status = await db_toggle_auto_reply(chat_id)
    settings = await db_get_auto_reply_settings(chat_id)
    status_text = "🟢 مفعل" if new_status else "🔴 معطل"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 الردود التلقائية: {status_text}", callback_data=f"auto_reply_toggle:{chat_id}")],
        [InlineKeyboardButton(f"👥 المستخدمون: {'👑 مشرفين فقط' if settings['only_admins'] else '👥 الجميع'}", callback_data=f"auto_reply_admins:{chat_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"groups:settings:{chat_id}")]
    ])
    await safe_edit(query, f"✅ تم تغيير حالة الردود التلقائية", reply_markup=keyboard)

async def auto_reply_admins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل وضع الردود التلقائية للمشرفين فقط"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_auto_reply_settings(chat_id)
    new_status = not settings['only_admins']
    await db_set_auto_reply_only_admins(chat_id, new_status)
    settings = await db_get_auto_reply_settings(chat_id)
    admin_text = "👑 مشرفين فقط" if new_status else "👥 الجميع"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 الردود التلقائية: {'🟢 مفعل' if settings['enabled'] else '🔴 معطل'}", callback_data=f"auto_reply_toggle:{chat_id}")],
        [InlineKeyboardButton(f"👥 المستخدمون: {admin_text}", callback_data=f"auto_reply_admins:{chat_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"groups:settings:{chat_id}")]
    ])
    await safe_edit(query, f"✅ تم تغيير وضع الردود إلى: {admin_text}", reply_markup=keyboard)

async def nsfw_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعدادات NSFW"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    await safe_edit(query, "🔞 **إعدادات NSFW**\n\n📌 نظام كشف المحتوى غير اللائق")

async def nsfw_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل NSFW"""
    query = update.callback_query
    await query.answer()
    await nsfw_settings_callback(update, context)

async def nsfw_threshold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين نسبة حساسية NSFW"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_NSFW_THRESHOLD
    await safe_edit(query, "📊 أرسل النسبة المئوية (من 0 إلى 100):")

# ====================================================================
# ===================== تصدير كل شيء =====================
# ====================================================================

__all__ = [
    # دوال
    'db_get_auto_recycle', 'db_set_auto_recycle',
    'db_register_channel', 'db_get_channel_stats_summary',
    'db_toggle_auto_reply', 'db_set_auto_reply_only_admins',
    'db_set_auto_reply_enabled', 'db_get_auto_reply_settings',
    'db_get_user_auto_reply_status', 'db_set_user_auto_reply_status',
    'db_add_scheduled_post', 'db_get_due_scheduled_posts',
    'db_update_scheduled_post_fail', 'db_delete_scheduled_post',
    'db_update_post_views', 'db_get_due_channels',
    'db_clean_expired_codes', 'db_get_verification_code',
    'db_get_group_settings', 'db_set_group_settings',
    
    # أوامر
    'sendcode_command',
    'set_rules_command', 'reset_rules_command',
    'ban_command', 'mute_command', 'unmute_command',
    'warn_command', 'kick_command', 'restrict_command',
    'pin_command', 'unban_command',
    'add_banned_word_command', 'remove_banned_word_command',
    'register_hidden_owner_command', 'add_hidden_admin_command',
    'remove_hidden_admin_command', 'list_hidden_admins_command',
    'rank_command', 'top_command', 'update_admins_command',
    
    # كولباك
    'settings_toggle_auto_recycle_callback',
    'schedule_set_days_callback', 'schedule_day_select_callback',
    'schedule_save_days_callback', 'schedule_set_dates_callback',
    'schedule_set_publish_time_callback',
    'set_interval_minutes_callback', 'set_interval_hours_callback',
    'set_interval_days_callback', 'schedule_menu_callback',
    'delete_single_post_callback', 'confirm_clear_all_posts_callback',
    'clear_all_posts_callback',
    'security_banned_words_menu_callback',
    'banned_words_add_callback', 'banned_words_list_callback',
    'banned_words_remove_callback',
    'penalty_menu_callback', 'penalty_kick_callback',
    'penalty_ban_callback', 'penalty_mute_callback',
    'penalty_mute_duration_callback',
    'advanced_actions_callback',
    'group_action_ban_callback', 'group_action_mute_callback',
    'advanced_mute_duration_callback',
    'group_action_warn_callback', 'group_action_kick_callback',
    'group_action_restrict_callback', 'group_action_pin_callback',
    'group_action_log_callback', 'group_action_unban_callback',
    'panel_lock_callback', 'panel_unlock_callback',
    'panel_close_callback', 'check_subscribe_callback',
    'publish_all_channels_callback',
    'channel_stats_callback', 'channel_growth_callback',
    'channel_stats_refresh_callback', 'my_channel_stats_callback',
    'admin_auto_reply_callback', 'admin_auto_reply_select_callback',
    'auto_reply_toggle_callback', 'auto_reply_admins_callback',
    'nsfw_settings_callback', 'nsfw_toggle_callback',
    'nsfw_threshold_callback'
]
