#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - أقوى نظام متكامل للبوتات
الإصدار: 19.0.8
"""

import asyncio
import sys
import os
import json
import sqlite3
import hashlib
import secrets
import re
import time
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# ===================== تثبيت المكتبات =====================
def install_package(pkg):
    try:
        __import__(pkg)
        return True
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "--quiet"])
        return True

for pkg in ["python-telegram-bot", "aiosqlite", "python-dotenv", "aiohttp"]:
    install_package(pkg)

# ===================== المكتبات =====================
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ChatMemberHandler
from telegram.error import TimedOut, NetworkError, Forbidden, BadRequest
import aiosqlite
from dotenv import load_dotenv

load_dotenv()

# ===================== الإعدادات =====================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN غير موجود")

MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", 0))
PRIMARY_OWNER_ID = 8290212138
BOT_NAME = os.getenv("BOT_NAME", "ريلاكس مانيجر")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Reelaaaxbot")

DB_PATH = Path("data/bot_data.db")
DB_PATH.parent.mkdir(exist_ok=True)

# ===================== قاعدة البيانات =====================
async def init_db():
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                auto_publish INTEGER DEFAULT 1,
                banned INTEGER DEFAULT 0,
                subscription_end TEXT,
                language TEXT DEFAULT 'ar',
                active_channel INTEGER
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id TEXT,
                channel_name TEXT,
                created_at TIMESTAMP,
                banned INTEGER DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_db_id INTEGER,
                text TEXT,
                media_type TEXT DEFAULT 'text',
                media_file_id TEXT,
                published INTEGER DEFAULT 0,
                created_at TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_groups (
                chat_id INTEGER PRIMARY KEY,
                chat_name TEXT,
                username TEXT,
                added_by INTEGER,
                added_at TIMESTAMP,
                banned INTEGER DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hidden_owners (
                chat_id INTEGER,
                owner_id INTEGER,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, owner_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hidden_admins (
                chat_id INTEGER,
                admin_id INTEGER,
                added_by INTEGER,
                permissions TEXT DEFAULT 'full',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, admin_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                action TEXT,
                target_id INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('publish_interval', '720')")
        await conn.commit()
    print("✅ قاعدة البيانات جاهزة")

# ===================== دوال قاعدة البيانات =====================
async def execute_db(query, params=()):
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        cur = await conn.execute(query, params)
        if query.strip().upper().startswith("SELECT"):
            return await cur.fetchall()
        await conn.commit()
        return cur.lastrowid

async def db_register_user(user_id: int) -> bool:
    users = await execute_db("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if users:
        return False
    await execute_db("INSERT INTO users (user_id) VALUES (?)", (user_id,))
    return True

async def db_get_channels(user_id: int):
    return await execute_db("SELECT id, channel_id, channel_name, banned FROM user_channels WHERE user_id=? ORDER BY id", (user_id,))

async def db_add_channel(user_id: int, channel_id: str, channel_name: str) -> int:
    existing = await execute_db("SELECT id FROM user_channels WHERE user_id=? AND channel_id=?", (user_id, channel_id))
    if existing:
        return None
    return await execute_db("INSERT INTO user_channels (user_id, channel_id, channel_name, created_at) VALUES (?, ?, ?, ?)", (user_id, channel_id, channel_name, datetime.now().isoformat()))

async def db_delete_channel(channel_db_id: int, user_id: int):
    await execute_db("DELETE FROM user_channels WHERE id=? AND user_id=?", (channel_db_id, user_id))
    await execute_db("DELETE FROM posts WHERE channel_db_id=?", (channel_db_id,))

async def db_get_active_channel(user_id: int):
    row = await execute_db("SELECT active_channel FROM users WHERE user_id=?", (user_id,))
    if row and row[0][0]:
        return row[0][0]
    channels = await db_get_channels(user_id)
    return channels[0][0] if channels else None

async def db_set_active_channel(user_id: int, channel_db_id: int):
    await execute_db("UPDATE users SET active_channel=? WHERE user_id=?", (channel_db_id, user_id))

async def db_save_posts(channel_db_id: int, posts: list) -> int:
    count = 0
    for text, media_type, media_file_id in posts:
        await execute_db("INSERT INTO posts (channel_db_id, text, media_type, media_file_id, created_at) VALUES (?, ?, ?, ?, ?)", (channel_db_id, text, media_type, media_file_id, datetime.now().isoformat()))
        count += 1
    return count

async def db_get_next_post(channel_db_id: int):
    rows = await execute_db("SELECT id, text, media_type, media_file_id FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 1", (channel_db_id,))
    if rows:
        return {"id": rows[0][0], "text": rows[0][1], "media_type": rows[0][2], "media_file_id": rows[0][3]}
    return None

async def db_mark_published(post_id: int):
    await execute_db("UPDATE posts SET published=1 WHERE id=?", (post_id,))

async def db_reset_posts_to_unpublished(channel_db_id: int):
    await execute_db("UPDATE posts SET published=0 WHERE channel_db_id=?", (channel_db_id,))

async def db_get_unpublished_count(channel_db_id: int) -> int:
    rows = await execute_db("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0", (channel_db_id,))
    return rows[0][0] if rows else 0

async def db_auto_status(user_id: int) -> bool:
    rows = await execute_db("SELECT auto_publish FROM users WHERE user_id=?", (user_id,))
    return rows and rows[0][0] == 1

async def db_set_auto(user_id: int, enabled: bool):
    await execute_db("UPDATE users SET auto_publish=? WHERE user_id=?", (1 if enabled else 0, user_id))

async def db_get_publish_interval():
    rows = await execute_db("SELECT value FROM settings WHERE key='publish_interval'")
    return int(rows[0][0]) if rows else 720

async def db_register_group(chat_id: int, chat_name: str, added_by: int):
    existing = await execute_db("SELECT chat_id FROM bot_groups WHERE chat_id=?", (chat_id,))
    if existing:
        return False
    await execute_db("INSERT INTO bot_groups (chat_id, chat_name, added_by, added_at) VALUES (?, ?, ?, ?)", (chat_id, chat_name, added_by, datetime.now().isoformat()))
    return True

async def db_get_user_groups(user_id: int):
    return await execute_db("SELECT chat_id, chat_name, username, banned FROM bot_groups WHERE added_by=? ORDER BY chat_name", (user_id,))

async def db_is_banned(user_id: int) -> bool:
    rows = await execute_db("SELECT banned FROM users WHERE user_id=?", (user_id,))
    return rows and rows[0][0] == 1

async def db_set_banned(user_id: int, banned: bool):
    await execute_db("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, user_id))

async def db_has_active_subscription(user_id: int) -> bool:
    rows = await execute_db("SELECT subscription_end FROM users WHERE user_id=?", (user_id,))
    if rows and rows[0][0]:
        try:
            end = datetime.fromisoformat(rows[0][0])
            return end > datetime.now()
        except:
            return False
    return False

async def db_activate_subscription(user_id: int, days: int):
    rows = await execute_db("SELECT subscription_end FROM users WHERE user_id=?", (user_id,))
    if rows and rows[0][0]:
        try:
            current = datetime.fromisoformat(rows[0][0])
            new_end = current + timedelta(days=days)
        except:
            new_end = datetime.now() + timedelta(days=days)
    else:
        new_end = datetime.now() + timedelta(days=days)
    await execute_db("UPDATE users SET subscription_end=? WHERE user_id=?", (new_end.isoformat(), user_id))

async def db_get_user_language(user_id: int) -> str:
    rows = await execute_db("SELECT language FROM users WHERE user_id=?", (user_id,))
    return rows[0][0] if rows else "ar"

async def db_set_user_language(user_id: int, lang: str):
    await execute_db("UPDATE users SET language=? WHERE user_id=?", (lang, user_id))

# ===================== 1. نظام الصلاحيات الموسع =====================
PERMISSIONS_MAP = {
    "full": [
        "manage_owners", "manage_admins", "manage_messages",
        "ban_users", "mute_users", "pin_messages",
        "change_info", "delete_messages", "invite_users",
        "promote_admins", "view_activity", "transfer_ownership"
    ],
    "senior": [
        "manage_messages", "ban_users", "mute_users",
        "pin_messages", "delete_messages", "invite_users",
        "view_activity"
    ],
    "junior": [
        "manage_messages", "delete_messages", "mute_users"
    ],
    "limited": [
        "delete_messages"
    ]
}

async def check_permission(bot, chat_id: int, user_id: int, action: str = "manage") -> bool:
    if user_id == PRIMARY_OWNER_ID:
        return True
    rows = await execute_db("SELECT 1 FROM hidden_owners WHERE chat_id=? AND owner_id=?", (chat_id, user_id))
    if rows:
        return True
    rows = await execute_db("SELECT permissions FROM hidden_admins WHERE chat_id=? AND admin_id=?", (chat_id, user_id))
    if rows:
        allowed = PERMISSIONS_MAP.get(rows[0][0], [])
        if action in allowed:
            return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status == 'creator':
            return True
        if member.status == 'administrator':
            basic = ['delete_messages', 'ban_users', 'pin_messages']
            return action in basic
    except:
        pass
    return False

async def log_activity(chat_id: int, user_id: int, action: str, target_id: int):
    try:
        await execute_db(
            "INSERT INTO activity_log (chat_id, user_id, action, target_id) VALUES (?, ?, ?, ?)",
            (chat_id, user_id, action, target_id)
        )
    except:
        pass

async def get_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    if context.args:
        try:
            target = context.args[0].replace("@", "")
            return await context.bot.get_chat(f"@{target}")
        except:
            try:
                return await context.bot.get_chat(int(context.args[0]))
            except:
                return None
    return None

# ===================== 2. نظام الحماية المتقدم =====================
async def anti_spam_check(chat_id, user_id):
    count = await execute_db(
        "SELECT COUNT(*) FROM activity_log WHERE chat_id=? AND user_id=? AND timestamp > datetime('now', '-10 seconds')",
        (chat_id, user_id)
    )
    if count and count[0][0] > 5:
        return False
    return True

async def rate_limit_check(user_id, action):
    count = await execute_db(
        "SELECT COUNT(*) FROM activity_log WHERE user_id=? AND action=? AND timestamp > datetime('now', '-1 minute')",
        (user_id, action)
    )
    return count and count[0][0] < 10

# ===================== 3. نظام النسخ الاحتياطي =====================
async def backup_permissions(chat_id):
    owners = await execute_db("SELECT * FROM hidden_owners WHERE chat_id=?", (chat_id,))
    admins = await execute_db("SELECT * FROM hidden_admins WHERE chat_id=?", (chat_id,))
    backup = {"chat_id": chat_id, "owners": owners, "admins": admins, "timestamp": datetime.now().isoformat()}
    await execute_db("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (f"backup_{chat_id}", json.dumps(backup)))
    return backup

async def restore_permissions(chat_id):
    rows = await execute_db("SELECT value FROM settings WHERE key=?", (f"backup_{chat_id}",))
    if not rows:
        return False
    backup = json.loads(rows[0][0])
    await execute_db("DELETE FROM hidden_owners WHERE chat_id=?", (chat_id,))
    await execute_db("DELETE FROM hidden_admins WHERE chat_id=?", (chat_id,))
    for owner in backup["owners"]:
        await execute_db("INSERT INTO hidden_owners (chat_id, owner_id) VALUES (?, ?)", (chat_id, owner[1]))
    for admin in backup["admins"]:
        await execute_db("INSERT INTO hidden_admins (chat_id, admin_id, added_by, permissions) VALUES (?, ?, ?, ?)", (chat_id, admin[1], admin[2], admin[3]))
    return True

# ===================== 4. نظام الإحصائيات المتقدم =====================
async def get_group_stats(chat_id):
    total_owners = await execute_db("SELECT COUNT(*) FROM hidden_owners WHERE chat_id=?", (chat_id,))
    total_admins = await execute_db("SELECT COUNT(*) FROM hidden_admins WHERE chat_id=?", (chat_id,))
    full_admins = await execute_db("SELECT COUNT(*) FROM hidden_admins WHERE chat_id=? AND permissions='full'", (chat_id,))
    senior_admins = await execute_db("SELECT COUNT(*) FROM hidden_admins WHERE chat_id=? AND permissions='senior'", (chat_id,))
    junior_admins = await execute_db("SELECT COUNT(*) FROM hidden_admins WHERE chat_id=? AND permissions='junior'", (chat_id,))
    limited_admins = await execute_db("SELECT COUNT(*) FROM hidden_admins WHERE chat_id=? AND permissions='limited'", (chat_id,))
    recent_activity = await execute_db("SELECT COUNT(*) FROM activity_log WHERE chat_id=? AND timestamp > datetime('now', '-24 hours')", (chat_id,))
    
    return {
        "owners": total_owners[0][0] if total_owners else 0,
        "admins": total_admins[0][0] if total_admins else 0,
        "full": full_admins[0][0] if full_admins else 0,
        "senior": senior_admins[0][0] if senior_admins else 0,
        "junior": junior_admins[0][0] if junior_admins else 0,
        "limited": limited_admins[0][0] if limited_admins else 0,
        "activity_24h": recent_activity[0][0] if recent_activity else 0
    }

# ===================== 5. أوامر متقدمة =====================
async def setadmin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not await check_permission(context.bot, chat_id, user_id, "manage_admins"):
        return await update.message.reply_text("❌ غير مصرح")
    
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text(
            "📝 **الاستخدام:** `/setadmin @user [full/senior/junior/limited]`",
            parse_mode="MarkdownV2"
        )
    
    try:
        target = args[0].replace("@", "")
        level = args[1].lower()
        if level not in PERMISSIONS_MAP:
            return await update.message.reply_text("❌ مستوى صلاحية غير صالح!")
        
        target_user = await context.bot.get_chat(f"@{target}")
        await execute_db(
            "INSERT OR REPLACE INTO hidden_admins (chat_id, admin_id, added_by, permissions) VALUES (?, ?, ?, ?)",
            (chat_id, target_user.id, user_id, level)
        )
        await log_activity(chat_id, user_id, f"set_admin_{level}", target_user.id)
        await update.message.reply_text(f"✅ تم تعيين @{target} كمشرف {level}")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")

async def gstats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if update.effective_chat.type not in ['group', 'supergroup']:
        return await update.message.reply_text("⚠️ للمجموعات فقط")
    
    if not await check_permission(context.bot, chat_id, user_id, "view_activity"):
        return await update.message.reply_text("❌ غير مصرح")
    
    stats = await get_group_stats(chat_id)
    
    msg = f"📊 **إحصائيات المجموعة**\n\n"
    msg += f"👑 المالكين: {stats['owners']}\n"
    msg += f"🛡️ المشرفين: {stats['admins']}\n"
    msg += f"  ⭐ كامل: {stats['full']}\n"
    msg += f"  🔶 كبير: {stats['senior']}\n"
    msg += f"  🔹 صغير: {stats['junior']}\n"
    msg += f"  ▪️ محدود: {stats['limited']}\n"
    msg += f"📋 نشاط 24 ساعة: {stats['activity_24h']}\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 عرض النشاط", callback_data=f"activity:{chat_id}"),
         InlineKeyboardButton("💾 نسخ احتياطي", callback_data=f"backup:{chat_id}")],
        [InlineKeyboardButton("🔄 استعادة", callback_data=f"restore:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await update.message.reply_text(msg, reply_markup=keyboard, parse_mode="MarkdownV2")

# ===================== 6. أوامر المالكين الأساسية =====================
async def claim_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    chat = update.effective_chat
    
    if chat.type not in ['group', 'supergroup']:
        return await update.message.reply_text("⚠️ للمجموعات فقط")
    
    if await check_permission(context.bot, chat_id, user_id, "manage_owners"):
        await execute_db(
            "INSERT OR IGNORE INTO hidden_owners (chat_id, owner_id) VALUES (?, ?)",
            (chat_id, user_id)
        )
        await update.message.reply_text("✅ تم تسجيلك كمالك مخفي")
    else:
        await update.message.reply_text("❌ غير مصرح")

async def owners_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not await check_permission(context.bot, chat_id, user_id, "view_activity"):
        return await update.message.reply_text("❌ غير مصرح")
    
    owners = await execute_db("SELECT owner_id FROM hidden_owners WHERE chat_id=?", (chat_id,))
    msg = "👑 **المالكين:**\n"
    for o in owners:
        try:
            u = await context.bot.get_chat(o[0])
            msg += f"• [{u.first_name}](tg://user?id={o[0]}) - `{o[0]}`\n"
        except:
            msg += f"• `{o[0]}`\n"
    await update.message.reply_text(msg, parse_mode="MarkdownV2")

async def addowner_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not await check_permission(context.bot, chat_id, user_id, "manage_owners"):
        return await update.message.reply_text("❌ غير مصرح")
    
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("📝 /addowner @user")
    
    await execute_db("INSERT OR IGNORE INTO hidden_owners (chat_id, owner_id) VALUES (?, ?)", (chat_id, target.id))
    await log_activity(chat_id, user_id, "add_owner", target.id)
    await update.message.reply_text(f"✅ تم إضافة [{target.first_name}](tg://user?id={target.id}) كمالك", parse_mode="MarkdownV2")

async def addadmin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not await check_permission(context.bot, chat_id, user_id, "manage_admins"):
        return await update.message.reply_text("❌ غير مصرح")
    
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("📝 /addadmin @user")
    
    await execute_db(
        "INSERT OR IGNORE INTO hidden_admins (chat_id, admin_id, added_by, permissions) VALUES (?, ?, ?, 'limited')",
        (chat_id, target.id, user_id)
    )
    await log_activity(chat_id, user_id, "add_admin_limited", target.id)
    await update.message.reply_text(f"✅ تم إضافة [{target.first_name}](tg://user?id={target.id}) كمشرف مخفي (صلاحيات محدودة)", parse_mode="MarkdownV2")

async def addadmin_full_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not await check_permission(context.bot, chat_id, user_id, "manage_admins"):
        return await update.message.reply_text("❌ غير مصرح")
    
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("📝 /addadmin_full @user")
    
    await execute_db(
        "INSERT OR IGNORE INTO hidden_admins (chat_id, admin_id, added_by, permissions) VALUES (?, ?, ?, 'full')",
        (chat_id, target.id, user_id)
    )
    await log_activity(chat_id, user_id, "add_admin_full", target.id)
    await update.message.reply_text(f"✅ تم إضافة [{target.first_name}](tg://user?id={target.id}) كمشرف مخفي (صلاحيات كاملة)", parse_mode="MarkdownV2")

async def remove_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not await check_permission(context.bot, chat_id, user_id, "manage_admins"):
        return await update.message.reply_text("❌ غير مصرح")
    
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("📝 /remove @user")
    
    await execute_db("DELETE FROM hidden_owners WHERE chat_id=? AND owner_id=?", (chat_id, target.id))
    await execute_db("DELETE FROM hidden_admins WHERE chat_id=? AND admin_id=?", (chat_id, target.id))
    await log_activity(chat_id, user_id, "remove", target.id)
    await update.message.reply_text(f"✅ تم إزالة [{target.first_name}](tg://user?id={target.id})", parse_mode="MarkdownV2")

async def list_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not await check_permission(context.bot, chat_id, user_id, "view_activity"):
        return await update.message.reply_text("❌ غير مصرح")
    
    msg = f"🏰 **نظام الصلاحيات**\n\n"
    
    owners = await execute_db("SELECT owner_id FROM hidden_owners WHERE chat_id=?", (chat_id,))
    msg += "👑 **المالكين:**\n"
    for o in owners:
        try:
            u = await context.bot.get_chat(o[0])
            msg += f"• [{u.first_name}](tg://user?id={o[0]})\n"
        except:
            msg += f"• `{o[0]}`\n"
    
    admins = await execute_db("SELECT admin_id, permissions FROM hidden_admins WHERE chat_id=? ORDER BY permissions DESC", (chat_id,))
    msg += "\n🛡️ **المشرفين المخفيين:**\n"
    if admins:
        for a in admins:
            badge = "⭐" if a[1] == 'full' else "🔶" if a[1] == 'senior' else "🔹" if a[1] == 'junior' else "▪️"
            try:
                u = await context.bot.get_chat(a[0])
                msg += f"{badge} [{u.first_name}](tg://user?id={a[0]})\n"
            except:
                msg += f"{badge} `{a[0]}`\n"
    else:
        msg += "• لا يوجد\n"
    
    msg += f"\n🔑 **المالك الأعلى:** `{PRIMARY_OWNER_ID}`"
    await update.message.reply_text(msg, parse_mode="MarkdownV2")

async def transfer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    owners = await execute_db("SELECT owner_id FROM hidden_owners WHERE chat_id=? AND owner_id=?", (chat_id, user_id))
    if user_id != PRIMARY_OWNER_ID and not owners:
        return await update.message.reply_text("❌ غير مصرح")
    
    target = await get_target(update, context)
    if not target:
        return await update.message.reply_text("📝 /transfer @user")
    
    await execute_db("DELETE FROM hidden_owners WHERE chat_id=?", (chat_id,))
    await execute_db("INSERT INTO hidden_owners (chat_id, owner_id) VALUES (?, ?)", (chat_id, target.id))
    await log_activity(chat_id, user_id, "transfer_ownership", target.id)
    await update.message.reply_text(f"✅ تم نقل الملكية إلى [{target.first_name}](tg://user?id={target.id})", parse_mode="MarkdownV2")

async def purge_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id != PRIMARY_OWNER_ID:
        return await update.message.reply_text("❌ فقط المالك الأعلى")
    
    await execute_db("DELETE FROM hidden_owners WHERE chat_id=?", (chat_id,))
    await execute_db("DELETE FROM hidden_admins WHERE chat_id=?", (chat_id,))
    await execute_db("DELETE FROM activity_log WHERE chat_id=?", (chat_id,))
    await update.message.reply_text("✅ تم مسح جميع الصلاحيات")

# ===================== 7. معالجات الأزرار المتقدمة =====================
async def activity_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[1])
    
    if not await check_permission(context.bot, chat_id, user_id, "view_activity"):
        return await query.edit_message_text("❌ غير مصرح")
    
    logs = await execute_db(
        "SELECT user_id, action, target_id, timestamp FROM activity_log WHERE chat_id=? ORDER BY timestamp DESC LIMIT 20",
        (chat_id,)
    )
    
    if not logs:
        return await query.edit_message_text("📭 لا يوجد نشاط")
    
    msg = "📋 **آخر النشاطات:**\n\n"
    for log in logs:
        try:
            u = await context.bot.get_chat(log[0])
            user_name = u.first_name
        except:
            user_name = log[0]
        msg += f"• {user_name} - {log[1]} - {log[3][:16]}\n"
    
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data=f"stats_back:{chat_id}")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")

async def backup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[1])
    
    if not await check_permission(context.bot, chat_id, user_id, "manage_owners"):
        return await query.edit_message_text("❌ غير مصرح")
    
    await backup_permissions(chat_id)
    await query.edit_message_text("✅ تم عمل نسخ احتياطي للصلاحيات")

async def restore_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[1])
    
    if user_id != PRIMARY_OWNER_ID:
        return await query.edit_message_text("❌ فقط المالك الأعلى")
    
    if await restore_permissions(chat_id):
        await query.edit_message_text("✅ تم استعادة الصلاحيات")
    else:
        await query.edit_message_text("❌ لا يوجد نسخ احتياطي")

# ===================== 8. الترجمة =====================
TRANSLATIONS = {
    "ar": {
        "welcome": "🌿 **مرحباً بك في ريلاكس مانيجر**\nاختر الإجراء المناسب:",
        "no_channels": "📭 لا توجد قنوات",
        "add_channel": "➕ إضافة قناة",
        "my_channels": "📡 قنواتي",
        "settings": "⚙️ الإعدادات",
        "back": "🔙 رجوع",
        "admin_only": "🔒 هذا الأمر للمشرفين فقط!",
        "error": "⚠️ حدث خطأ، حاول مرة أخرى",
        "cancelled": "❌ تم الإلغاء",
        "channel_added": "✅ تم إضافة القناة",
        "channel_deleted": "✅ تم حذف القناة",
        "no_posts": "📭 لا توجد منشورات",
        "post_saved": "✅ تم حفظ المنشورات",
        "post_published": "✅ تم النشر",
        "recycled": "♻️ تم إعادة التدوير",
        "auto_on": "✅ النشر التلقائي مفعل",
        "auto_off": "❌ النشر التلقائي معطل",
        "help_text": "❓ **المساعدة**\n/start - القائمة الرئيسية\n/help - هذه المساعدة\n/language - تغيير اللغة\n/stats - إحصائيات القناة\n/rank - رتبتك\n/claim - تسجيل مالك مخفي\n/owners - عرض المالكين\n/addowner @user - إضافة مالك\n/addadmin @user - إضافة مشرف مخفي\n/addadmin_full @user - مشرف بصلاحيات كاملة\n/remove @user - إزالة مشرف/مالك\n/list - عرض الكل\n/transfer @user - نقل الملكية\n/purge - حذف جميع الصلاحيات\n/setadmin @user [full/senior/junior/limited] - تعيين مشرف بصلاحيات\n/gstats - إحصائيات المجموعة",
    },
    "en": {
        "welcome": "🌿 **Welcome to Relax Manager**\nChoose an action:",
        "no_channels": "📭 No channels",
        "add_channel": "➕ Add Channel",
        "my_channels": "📡 My Channels",
        "settings": "⚙️ Settings",
        "back": "🔙 Back",
        "admin_only": "🔒 For admins only!",
        "error": "⚠️ An error occurred, try again",
        "cancelled": "❌ Cancelled",
        "channel_added": "✅ Channel added",
        "channel_deleted": "✅ Channel deleted",
        "no_posts": "📭 No posts",
        "post_saved": "✅ Posts saved",
        "post_published": "✅ Published",
        "recycled": "♻️ Recycled",
        "auto_on": "✅ Auto publish enabled",
        "auto_off": "❌ Auto publish disabled",
        "help_text": "❓ **Help**\n/start - Main menu\n/help - This help\n/language - Change language\n/stats - Channel stats\n/rank - Your rank\n/claim - Register hidden owner\n/owners - List owners\n/addowner @user - Add owner\n/addadmin @user - Add hidden admin\n/addadmin_full @user - Admin with full permissions\n/remove @user - Remove admin/owner\n/list - List all\n/transfer @user - Transfer ownership\n/purge - Delete all permissions\n/setadmin @user [full/senior/junior/limited] - Set admin with permissions\n/gstats - Group statistics",
    }
}

user_language = {}

def get_text(user_id: int, key: str) -> str:
    lang = user_language.get(user_id, "ar")
    return TRANSLATIONS.get(lang, TRANSLATIONS["ar"]).get(key, key)

async def load_user_languages():
    users = await execute_db("SELECT user_id, language FROM users WHERE language IS NOT NULL")
    for user_id, lang in users:
        user_language[user_id] = lang

# ===================== 9. لوحة المفاتيح الأساسية =====================
async def get_main_keyboard(user_id: int):
    channels = await db_get_channels(user_id)
    active = await db_get_active_channel(user_id)
    unpublished = await db_get_unpublished_count(active) if active else 0
    
    keyboard = [
        [InlineKeyboardButton("👥 مجموعاتي", callback_data="groups:my"),
         InlineKeyboardButton("➕ إضافة قناة", callback_data="channels:add")],
        [InlineKeyboardButton("📡 قنواتي", callback_data="channels:my"),
         InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings:menu")],
    ]
    
    if channels:
        keyboard.append([
            InlineKeyboardButton("📥 إضافة 15 منشور", callback_data="posts:add_15"),
            InlineKeyboardButton("📤 نشر واحد", callback_data="posts:publish_one")
        ])
        keyboard.append([
            InlineKeyboardButton("📋 منشوراتي", callback_data="posts:my"),
            InlineKeyboardButton("♻️ إعادة تدوير", callback_data="posts:recycle")
        ])
        keyboard.append([
            InlineKeyboardButton(f"📊 إحصائياتي ({unpublished})", callback_data="stats:pending"),
            InlineKeyboardButton("📈 إحصائيات كاملة", callback_data="stats:full")
        ])
    
    keyboard.append([
        InlineKeyboardButton("❓ المساعدة", callback_data="help"),
        InlineKeyboardButton("🌐 اللغة", callback_data="language")
    ])
    keyboard.append([
        InlineKeyboardButton("🎁 تجربة مجانية", callback_data="trial"),
        InlineKeyboardButton("💎 اشتراك", callback_data="subscribe")
    ])
    keyboard.append([
        InlineKeyboardButton("👨‍💻 المطور", callback_data="developer"),
        InlineKeyboardButton("📞 الدعم", callback_data="support")
    ])
    
    if user_id == MAIN_ADMIN_ID or user_id == PRIMARY_OWNER_ID:
        keyboard.append([
            InlineKeyboardButton("👑 لوحة الأدمن", callback_data="admin:panel")
        ])
    
    return InlineKeyboardMarkup(keyboard)

# ===================== 10. الأوامر الأساسية =====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db_register_user(user.id)
    user_language[user.id] = await db_get_user_language(user.id)
    keyboard = await get_main_keyboard(user.id)
    await update.message.reply_text(get_text(user.id, "welcome"), reply_markup=keyboard, parse_mode="MarkdownV2")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(get_text(user_id, "help_text"), parse_mode="MarkdownV2")

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"), InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")],
    ])
    await update.message.reply_text("🌐 اختر اللغة / Choose language:", reply_markup=keyboard)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    channels = await db_get_channels(user_id)
    if not channels:
        await update.message.reply_text(get_text(user_id, "no_channels"))
        return
    text = "📊 **قنواتي:**\n"
    for ch in channels:
        ch_id, ch_tele, ch_name, banned = ch
        status = "⛔" if banned else "✅"
        text += f"{status} {ch_name}\n"
    await update.message.reply_text(text, parse_mode="MarkdownV2")

async def syncgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    await db_register_group(chat.id, chat.title, user.id)
    await update.message.reply_text(f"✅ تم تفعيل المجموعة: {chat.title}")

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ يعمل فقط في المجموعات!")
        return
    await update.message.reply_text("🔒 تم قفل المجموعة")

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔓 تم فتح المجموعة")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ يعمل فقط في المجموعات!")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("📝 قم بالرد على رسالة المستخدم")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(chat.id, target.id)
        await update.message.reply_text(f"✅ تم حظر {target.first_name}")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الحظر: {e}")

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ يعمل فقط في المجموعات!")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("📝 قم بالرد على رسالة المستخدم")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.restrict_chat_member(chat.id, target.id, permissions=ChatPermissions(can_send_messages=False))
        await update.message.reply_text(f"🔇 تم كتم {target.first_name}")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الكتم: {e}")

async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ يعمل فقط في المجموعات!")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("📝 قم بالرد على رسالة المستخدم")
        return
    target = update.message.reply_to_message.from_user
    try:
        await context.bot.ban_chat_member(chat.id, target.id)
        await context.bot.unban_chat_member(chat.id, target.id)
        await update.message.reply_text(f"👢 تم طرد {target.first_name}")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الطرد: {e}")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ يعمل فقط في المجموعات!")
        return
    args = context.args
    if not args:
        await update.message.reply_text("📝 الاستخدام: /unban معرف_المستخدم")
        return
    try:
        user_id = int(args[0])
        await context.bot.unban_chat_member(chat.id, user_id)
        await update.message.reply_text(f"✅ تم إلغاء حظر {user_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل إلغاء الحظر: {e}")

async def trial_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await db_activate_subscription(user_id, 30)
    await update.message.reply_text("🎁 تم تفعيل التجربة المجانية لمدة 30 يوم!")

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data="buy:1:5")],
        [InlineKeyboardButton("⭐ 30 يوم - 50 نجمة", callback_data="buy:30:50")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")],
    ])
    await update.message.reply_text("💎 **اختر الباقة:**", reply_markup=keyboard, parse_mode="MarkdownV2")

async def rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    channels = await db_get_channels(user_id)
    count = len(channels)
    await update.message.reply_text(f"📊 **رتبتك:**\n• عدد القنوات: {count}\n• المستوى: 1\n• النقاط: 0", parse_mode="MarkdownV2")

async def developer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👨‍💻 **المطور:** @RelaxMgr\n📦 **الإصدار:** 19.0.8\n🤖 **البوت:** ريلاكس مانيجر", parse_mode="MarkdownV2")

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📞 **للتواصل:**\n• المطور: @RelaxMgr\n• البوت: @Reelaaaxbot", parse_mode="MarkdownV2")

# ===================== 11. معالجات الأزرار =====================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    
    if data == "back":
        keyboard = await get_main_keyboard(user_id)
        await query.edit_message_text(get_text(user_id, "welcome"), reply_markup=keyboard, parse_mode="MarkdownV2")
    
    elif data.startswith("activity:"):
        await activity_handler(update, context)
    
    elif data.startswith("backup:"):
        await backup_handler(update, context)
    
    elif data.startswith("restore:"):
        await restore_handler(update, context)
    
    elif data.startswith("stats_back:"):
        chat_id = int(data.split(":")[1])
        await gstats_handler(update, context)
    
    elif data == "channels:my":
        channels = await db_get_channels(user_id)
        if not channels:
            await query.edit_message_text(get_text(user_id, "no_channels"))
            return
        keyboard = []
        for ch in channels:
            ch_id, ch_tele, ch_name, banned = ch
            keyboard.append([InlineKeyboardButton(f"📢 {ch_name}", callback_data=f"channel_select:{ch_id}")])
        keyboard.append([InlineKeyboardButton("➕ إضافة قناة", callback_data="channels:add")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
        await query.edit_message_text("📡 **قنواتي**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    
    elif data == "channels:add":
        context.user_data["state"] = "WAITING_CHANNEL_ID"
        await query.edit_message_text("📡 أرسل معرف القناة (مثال: @channel أو -100123456)")
    
    elif data.startswith("channel_select:"):
        ch_db_id = int(data.split(":")[1])
        await db_set_active_channel(user_id, ch_db_id)
        keyboard = await get_main_keyboard(user_id)
        await query.edit_message_text("✅ تم اختيار القناة", reply_markup=keyboard, parse_mode="MarkdownV2")
    
    elif data == "posts:add_15":
        active = await db_get_active_channel(user_id)
        if not active:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
            return
        context.user_data["state"] = "ADDING_POSTS"
        context.user_data["session_posts"] = []
        await query.edit_message_text("📥 أرسل المنشورات (نصوص/صور/فيديوهات)\nأرسل /cancel للإلغاء")
    
    elif data == "posts:publish_one":
        active = await db_get_active_channel(user_id)
        if not active:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
            return
        post = await db_get_next_post(active)
        if not post:
            await query.edit_message_text(get_text(user_id, "no_posts"))
            return
        ch_info = await execute_db("SELECT channel_id FROM user_channels WHERE id=?", (active,))
        if ch_info:
            try:
                if post["media_type"] == "photo":
                    await context.bot.send_photo(ch_info[0][0], post["media_file_id"], caption=post["text"])
                elif post["media_type"] == "video":
                    await context.bot.send_video(ch_info[0][0], post["media_file_id"], caption=post["text"])
                else:
                    await context.bot.send_message(ch_info[0][0], post["text"])
                await db_mark_published(post["id"])
                await query.edit_message_text(get_text(user_id, "post_published"))
            except Exception as e:
                await query.edit_message_text(f"❌ فشل النشر: {e}")
    
    elif data == "posts:my":
        active = await db_get_active_channel(user_id)
        if not active:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
            return
        posts = await execute_db("SELECT id, text, media_type FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 15", (active,))
        if not posts:
            await query.edit_message_text(get_text(user_id, "no_posts"))
            return
        text = "📋 **منشوراتي:**\n"
        for p in posts:
            text += f"• {p[1][:50]}...\n"
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    
    elif data == "posts:recycle":
        active = await db_get_active_channel(user_id)
        if active:
            await db_reset_posts_to_unpublished(active)
            await query.edit_message_text(get_text(user_id, "recycled"))
        else:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
    
    elif data == "settings:menu":
        auto = await db_auto_status(user_id)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{'✅' if auto else '❌'} النشر التلقائي", callback_data="settings:toggle_auto")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ])
        await query.edit_message_text("⚙️ **الإعدادات**", reply_markup=keyboard, parse_mode="MarkdownV2")
    
    elif data == "settings:toggle_auto":
        auto = await db_auto_status(user_id)
        await db_set_auto(user_id, not auto)
        await query.edit_message_text(get_text(user_id, "auto_on") if not auto else get_text(user_id, "auto_off"))
        await button_callback(update, context)
    
    elif data == "stats:pending":
        active = await db_get_active_channel(user_id)
        if not active:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
            return
        count = await db_get_unpublished_count(active)
        await query.edit_message_text(f"📊 **المنشورات غير المنشورة:** {count}", parse_mode="MarkdownV2")
    
    elif data == "stats:full":
        channels = await db_get_channels(user_id)
        text = "📈 **إحصائياتي:**\n"
        for ch in channels:
            ch_id, ch_tele, ch_name, banned = ch
            count = await db_get_unpublished_count(ch_id)
            text += f"• {ch_name}: {count} غير منشور\n"
        await query.edit_message_text(text, parse_mode="MarkdownV2")
    
    elif data == "groups:my":
        groups = await db_get_user_groups(user_id)
        if not groups:
            await query.edit_message_text("📭 لا توجد مجموعات")
            return
        text = "👥 **مجموعاتي:**\n"
        for g in groups:
            text += f"• {g[1]}\n"
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    
    elif data == "help":
        await query.edit_message_text(get_text(user_id, "help_text"), parse_mode="MarkdownV2")
    
    elif data == "language":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"), InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")],
        ])
        await query.edit_message_text("🌐 اختر اللغة:", reply_markup=keyboard)
    
    elif data.startswith("lang_"):
        lang = data.split("_")[1]
        await db_set_user_language(user_id, lang)
        user_language[user_id] = lang
        keyboard = await get_main_keyboard(user_id)
        await query.edit_message_text(f"✅ تم تغيير اللغة إلى {'العربية' if lang == 'ar' else 'English'}", reply_markup=keyboard, parse_mode="MarkdownV2")
    
    elif data == "trial":
        await db_activate_subscription(user_id, 30)
        await query.edit_message_text("🎁 تم تفعيل التجربة المجانية لمدة 30 يوم!")
    
    elif data == "subscribe":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data="buy:1:5")],
            [InlineKeyboardButton("⭐ 30 يوم - 50 نجمة", callback_data="buy:30:50")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")],
        ])
        await query.edit_message_text("💎 **اختر الباقة:**", reply_markup=keyboard, parse_mode="MarkdownV2")
    
    elif data.startswith("buy:"):
        parts = data.split(":")
        days = int(parts[1])
        await db_activate_subscription(user_id, days)
        await query.edit_message_text(f"✅ تم تفعيل اشتراكك لمدة {days} يوم!")
    
    elif data == "developer":
        await query.edit_message_text("👨‍💻 **المطور:** @RelaxMgr\n📦 **الإصدار:** 19.0.8", parse_mode="MarkdownV2")
    
    elif data == "support":
        await query.edit_message_text("📞 **للتواصل:**\n• المطور: @RelaxMgr\n• البوت: @Reelaaaxbot", parse_mode="MarkdownV2")
    
    elif data == "admin:panel":
        if user_id != MAIN_ADMIN_ID and user_id != PRIMARY_OWNER_ID:
            await query.edit_message_text("🔒 هذا الأمر للمطور فقط!")
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 المستخدمين", callback_data="admin:users")],
            [InlineKeyboardButton("📡 القنوات", callback_data="admin:channels")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ])
        await query.edit_message_text("👑 **لوحة الأدمن**", reply_markup=keyboard, parse_mode="MarkdownV2")
    
    elif data == "admin:users":
        users = await execute_db("SELECT user_id, banned FROM users LIMIT 50")
        text = "👥 **المستخدمين:**\n"
        for u in users:
            status = "🚫" if u[1] else "✅"
            text += f"{status} {u[0]}\n"
        await query.edit_message_text(text, parse_mode="MarkdownV2")
    
    elif data == "admin:channels":
        channels = await execute_db("SELECT user_id, channel_id, channel_name FROM user_channels LIMIT 50")
        text = "📡 **قنوات المستخدمين:**\n"
        for ch in channels:
            text += f"• {ch[2]} (المستخدم: {ch[0]})\n"
        await query.edit_message_text(text, parse_mode="MarkdownV2")

# ===================== 12. معالج الرسائل =====================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text or ""
    state = context.user_data.get("state")
    
    if text == "/cancel":
        context.user_data.pop("state", None)
        context.user_data.pop("session_posts", None)
        await update.message.reply_text(get_text(user_id, "cancelled"))
        keyboard = await get_main_keyboard(user_id)
        await update.message.reply_text(get_text(user_id, "welcome"), reply_markup=keyboard, parse_mode="MarkdownV2")
        return
    
    if state == "WAITING_CHANNEL_ID":
        channel_id = text.strip()
        if not channel_id.startswith("@") and not channel_id.startswith("-100"):
            await update.message.reply_text("❌ معرف قناة غير صالح!\nاستخدم @username أو -100123456")
            return
        new_id = await db_add_channel(user_id, channel_id, channel_id)
        if new_id:
            await db_set_active_channel(user_id, new_id)
            await update.message.reply_text(get_text(user_id, "channel_added"))
        else:
            await update.message.reply_text("⚠️ القناة موجودة مسبقاً")
        context.user_data.pop("state", None)
        keyboard = await get_main_keyboard(user_id)
        await update.message.reply_text(get_text(user_id, "welcome"), reply_markup=keyboard, parse_mode="MarkdownV2")
        return
    
    if state == "ADDING_POSTS":
        posts = context.user_data.get("session_posts", [])
        media_type = "text"
        media_file_id = None
        text_content = text
        
        if update.message.photo:
            media_type = "photo"
            media_file_id = update.message.photo[-1].file_id
            text_content = update.message.caption or ""
        elif update.message.video:
            media_type = "video"
            media_file_id = update.message.video.file_id
            text_content = update.message.caption or ""
        elif update.message.document:
            media_type = "document"
            media_file_id = update.message.document.file_id
            text_content = update.message.caption or ""
        
        posts.append((text_content, media_type, media_file_id))
        context.user_data["session_posts"] = posts
        
        if len(posts) >= 15:
            active = await db_get_active_channel(user_id)
            if active:
                saved = await db_save_posts(active, posts)
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور")
            context.user_data.pop("state", None)
            context.user_data.pop("session_posts", None)
            keyboard = await get_main_keyboard(user_id)
            await update.message.reply_text(get_text(user_id, "welcome"), reply_markup=keyboard, parse_mode="MarkdownV2")
        else:
            await update.message.reply_text(f"📥 {len(posts)}/15")

# ===================== 13. معالج المجموعات =====================
async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type not in ["group", "supergroup"]:
        return
    
    if user.is_bot:
        return
    
    text = update.message.text or ""
    text_lower = text.lower()
    
    replies = {
        "مرحباً": "أهلاً وسهلاً بك 🤍",
        "السلام عليكم": "وعليكم السلام ورحمة الله 🌹",
        "كيف حالك": "الحمد لله بخير، وأنت؟ 🙏",
        "شكراً": "العفو 🤍",
        "حبيبي": "حبيبي نورت 🌸",
        "ماشاء الله": "تبارك الله 🌸",
        "الحمد لله": "الحمد لله دائماً وأبداً 🌸",
        "سبحان الله": "سبحان الله وبحمده 🌸",
        "الله أكبر": "الله أكبر 🌸",
        "استغفر الله": "اللهم اغفر لنا 🌸",
        "جزاك الله خيراً": "وإياك 🌸",
        "الله يجزيك الخير": "وإياك 🤍",
        "تعبان": "لا تستسلم، أنت أقوى مما تظن 💪",
        "من أنت": "أنا ريلاكس مانيجر، بوت متكامل 🤖",
        "نكتة": "مرة وحدة قالت للثانية... خلاص ما في نكتة 😂",
    }
    
    for word, reply in replies.items():
        if word in text_lower:
            await update.message.reply_text(reply)
            break

# ===================== 14. التسجيل التلقائي =====================
async def auto_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    chat = update.effective_chat
    
    if not update.message or not update.message.new_chat_members:
        return
    
    bot_id = context.bot.id
    for member in update.message.new_chat_members:
        if member.id == bot_id:
            owners = await execute_db("SELECT owner_id FROM hidden_owners WHERE chat_id=?", (chat_id,))
            if not owners:
                await execute_db("INSERT INTO hidden_owners (chat_id, owner_id) VALUES (?, ?)", (chat_id, user_id))
                await log_activity(chat_id, user_id, "auto_register_owner", 0)
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"🎉 **مبروك!** تم تسجيلك كمالك مخفي\n📌 المجموعة: {chat.title}\n🆔 معرفك: `{user_id}`",
                        parse_mode="MarkdownV2"
                    )
                except:
                    pass
            break

# ===================== 15. النشر التلقائي =====================
async def auto_publish_loop(app):
    await asyncio.sleep(10)
    while True:
        try:
            interval = await db_get_publish_interval()
            users = await execute_db("SELECT user_id FROM users WHERE auto_publish=1 AND banned=0")
            
            for (user_id,) in users:
                active = await db_get_active_channel(user_id)
                if not active:
                    continue
                post = await db_get_next_post(active)
                if not post:
                    continue
                ch_info = await execute_db("SELECT channel_id FROM user_channels WHERE id=?", (active,))
                if not ch_info:
                    continue
                try:
                    if post["media_type"] == "photo":
                        await app.bot.send_photo(ch_info[0][0], post["media_file_id"], caption=post["text"])
                    elif post["media_type"] == "video":
                        await app.bot.send_video(ch_info[0][0], post["media_file_id"], caption=post["text"])
                    else:
                        await app.bot.send_message(ch_info[0][0], post["text"])
                    await db_mark_published(post["id"])
                except Exception as e:
                    print(f"⚠️ فشل النشر: {e}")
                await asyncio.sleep(2)
            
            await asyncio.sleep(interval)
        except Exception as e:
            print(f"❌ خطأ في النشر التلقائي: {e}")
            await asyncio.sleep(60)

# ===================== 16. خادم الويب =====================
async def start_web_server():
    try:
        from aiohttp import web
        app = web.Application()
        async def health(request):
            return web.json_response({"status": "healthy", "bot": BOT_NAME, "version": "19.0.8"})
        app.router.add_get("/", health)
        app.router.add_get("/health", health)
        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.getenv("PORT", 10000))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"✅ خادم الويب يعمل على المنفذ {port}")
    except Exception as e:
        print(f"⚠️ فشل خادم الويب: {e}")

# ===================== 17. الدالة الرئيسية =====================
async def run_bot():
    print(f"🚀 {BOT_NAME} جاري التشغيل...")
    
    await init_db()
    await load_user_languages()
    
    app = Application.builder().token(TOKEN).build()
    
    # ===== التسجيل التلقائي =====
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, auto_register), group=1)
    
    # ===== أوامر المالكين والمشرفين المخفيين =====
    app.add_handler(CommandHandler("claim", claim_handler))
    app.add_handler(CommandHandler("owners", owners_handler))
    app.add_handler(CommandHandler("addowner", addowner_handler))
    app.add_handler(CommandHandler("addadmin", addadmin_handler))
    app.add_handler(CommandHandler("addadmin_full", addadmin_full_handler))
    app.add_handler(CommandHandler("remove", remove_handler))
    app.add_handler(CommandHandler("list", list_handler))
    app.add_handler(CommandHandler("transfer", transfer_handler))
    app.add_handler(CommandHandler("purge", purge_handler))
    
    # ===== الأوامر المتقدمة =====
    app.add_handler(CommandHandler("setadmin", setadmin_handler))
    app.add_handler(CommandHandler("gstats", gstats_handler))
    
    # ===== الأوامر الأساسية =====
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("syncgroup", syncgroup_command))
    app.add_handler(CommandHandler("lock", lock_command))
    app.add_handler(CommandHandler("unlock", unlock_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("kick", kick_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("trial", trial_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("rank", rank_command))
    app.add_handler(CommandHandler("developer", developer_command))
    app.add_handler(CommandHandler("support", support_command))
    
    # ===== الأزرار =====
    app.add_handler(CallbackQueryHandler(button_callback))
    
    # ===== الرسائل =====
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, group_message_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler))
    
    # ===== أوامر القائمة =====
    commands = [
        BotCommand("start", "بدء البوت"),
        BotCommand("help", "المساعدة"),
        BotCommand("language", "تغيير اللغة"),
        BotCommand("syncgroup", "تفعيل المجموعة"),
        BotCommand("trial", "تجربة مجانية"),
        BotCommand("subscribe", "الاشتراك"),
        BotCommand("stats", "إحصائيات القناة"),
        BotCommand("rank", "رتبتك"),
        BotCommand("claim", "تسجيل مالك مخفي"),
        BotCommand("owners", "عرض المالكين"),
        BotCommand("addowner", "إضافة مالك"),
        BotCommand("addadmin", "إضافة مشرف مخفي"),
        BotCommand("addadmin_full", "مشرف بصلاحيات كاملة"),
        BotCommand("remove", "إزالة مشرف/مالك"),
        BotCommand("list", "عرض الكل"),
        BotCommand("transfer", "نقل الملكية"),
        BotCommand("setadmin", "تعيين مشرف بصلاحيات"),
        BotCommand("gstats", "إحصائيات المجموعة"),
    ]
    await app.bot.set_my_commands(commands)
    
    # ===== المهام الخلفية =====
    asyncio.create_task(auto_publish_loop(app))
    asyncio.create_task(start_web_server())
    
    print(f"✅ {BOT_NAME} يعمل الآن!")
    await app.run_polling(drop_pending_updates=True)

# ===================== 18. التشغيل =====================
if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف البوت")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        import traceback
        traceback.print_exc()
