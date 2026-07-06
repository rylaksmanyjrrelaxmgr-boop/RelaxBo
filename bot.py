#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - بوت متكامل لإدارة القنوات والمجموعات
الإصدار: 19.0.8
المطور: @RelaxMgr
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

for pkg in ["python-telegram-bot", "aiosqlite", "python-dotenv", "aiohttp", "Pillow"]:
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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_replies (
                keyword TEXT PRIMARY KEY,
                reply TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                message TEXT,
                ticket_number INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP,
                replied INTEGER DEFAULT 0
            )
        """)
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('publish_interval', '720')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_ticket_number', '0')")
        await conn.commit()
    print("✅ قاعدة البيانات جاهزة")

async def execute_db(query, params=()):
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        cur = await conn.execute(query, params)
        if query.strip().upper().startswith("SELECT"):
            return await cur.fetchall()
        await conn.commit()
        return cur.lastrowid

# ===================== دوال المستخدمين =====================
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

# ===================== نظام التذاكر =====================
async def db_get_next_ticket_number():
    rows = await execute_db("SELECT value FROM settings WHERE key='last_ticket_number'")
    return int(rows[0][0]) if rows else 0

async def db_save_ticket(user_id, username, message, ticket_num):
    await execute_db("INSERT INTO support_tickets (user_id, username, message, ticket_number, created_at) VALUES (?, ?, ?, ?, ?)", (user_id, username, message, ticket_num, datetime.now().isoformat()))

async def db_get_user_ticket(user_id):
    rows = await execute_db("SELECT ticket_number, status, created_at FROM support_tickets WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
    return rows[0] if rows else None

async def db_get_all_tickets(limit=20):
    return await execute_db("SELECT id, user_id, username, message, ticket_number, status, created_at FROM support_tickets ORDER BY id DESC LIMIT ?", (limit,))

async def db_delete_all_tickets():
    await execute_db("DELETE FROM support_tickets")
    await execute_db("UPDATE settings SET value='0' WHERE key='last_ticket_number'")

# ===================== نظام الصلاحيات =====================
PERMISSIONS_MAP = {
    "full": ["manage_owners", "manage_admins", "manage_messages", "ban_users", "mute_users", "pin_messages", "change_info", "delete_messages", "invite_users", "promote_admins", "view_activity", "transfer_ownership"],
    "senior": ["manage_messages", "ban_users", "mute_users", "pin_messages", "delete_messages", "invite_users", "view_activity"],
    "junior": ["manage_messages", "delete_messages", "mute_users"],
    "limited": ["delete_messages"]
}

async def check_permission(bot, chat_id: int, user_id: int, action: str = "manage") -> bool:
    if user_id == PRIMARY_OWNER_ID or user_id == MAIN_ADMIN_ID:
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
        await execute_db("INSERT INTO activity_log (chat_id, user_id, action, target_id) VALUES (?, ?, ?, ?)", (chat_id, user_id, action, target_id))
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

# ===================== نظام الردود =====================
async def db_add_reply(keyword, reply):
    await execute_db("INSERT OR REPLACE INTO group_replies (keyword, reply) VALUES (?, ?)", (keyword.lower(), reply))

async def db_del_reply(keyword):
    await execute_db("DELETE FROM group_replies WHERE keyword=?", (keyword.lower(),))

async def db_get_reply(keyword):
    rows = await execute_db("SELECT reply FROM group_replies WHERE keyword=?", (keyword.lower(),))
    return rows[0][0] if rows else None

async def db_get_all_replies():
    return await execute_db("SELECT keyword, reply FROM group_replies ORDER BY keyword")

# ===================== نظام الترجمات =====================
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
        "help_text": "❓ **المساعدة**\n/start - القائمة الرئيسية\n/help - هذه المساعدة\n/language - تغيير اللغة\n/stats - إحصائيات القناة\n/rank - رتبتك\n/claim - تسجيل مالك مخفي\n/owners - عرض المالكين\n/addowner @user - إضافة مالك\n/addadmin @user - إضافة مشرف مخفي\n/addadmin_full @user - مشرف بصلاحيات كاملة\n/remove @user - إزالة مشرف/مالك\n/list - عرض الكل\n/transfer @user - نقل الملكية\n/purge - حذف جميع الصلاحيات\n/setadmin @user [full/senior/junior/limited] - تعيين مشرف بصلاحيات\n/gstats - إحصائيات المجموعة\n/support - الدعم\n/ticket - تذكرة دعم",
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
        "help_text": "❓ **Help**\n/start - Main menu\n/help - This help\n/language - Change language\n/stats - Channel stats\n/rank - Your rank\n/claim - Register hidden owner\n/owners - List owners\n/addowner @user - Add owner\n/addadmin @user - Add hidden admin\n/addadmin_full @user - Admin with full permissions\n/remove @user - Remove admin/owner\n/list - List all\n/transfer @user - Transfer ownership\n/purge - Delete all permissions\n/setadmin @user [full/senior/junior/limited] - Set admin with permissions\n/gstats - Group statistics\n/support - Support\n/ticket - Support ticket",
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

# ===================== لوحة المفاتيح الرئيسية (مرتبة) =====================

# ===================== لوحة الأدمن (مرتبة) =====================
def get_admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        # ===== الصف 1: المستخدمين =====
        [
            InlineKeyboardButton("👥 المستخدمين", callback_data="admin:users"),
            InlineKeyboardButton("🚫 المحظورين", callback_data="admin:banned_users")
        ],
        # ===== الصف 2: القنوات =====
        [
            InlineKeyboardButton("📡 القنوات", callback_data="admin:all_channels"),
            InlineKeyboardButton("⛔ قنوات محظورة", callback_data="admin:banned_channels")
        ],
        # ===== الصف 3: المجموعات =====
        [
            InlineKeyboardButton("📊 المجموعات", callback_data="admin:groups"),
            InlineKeyboardButton("🚷 مجموعات محظورة", callback_data="admin:banned_groups")
        ],
        # ===== الصف 4: إدارة =====
        [
            InlineKeyboardButton("👑 + مشرف", callback_data="admin:add_admin"),
            InlineKeyboardButton("🗑️ - مشرف", callback_data="admin:remove_admin")
        ],
        # ===== الصف 5: ردود + كلمات =====
        [
            InlineKeyboardButton("💬 ردود", callback_data="admin:replies"),
            InlineKeyboardButton("🚫 كلمات محظورة", callback_data="admin:banned_words")
        ],
        # ===== الصف 6: مسابقات =====
        [
            InlineKeyboardButton("🏆 إنشاء مسابقة", callback_data="admin:create_contest"),
            InlineKeyboardButton("🏅 إعلان فائز", callback_data="admin:declare_winner")
        ],
        # ===== الصف 7: نظام =====
        [
            InlineKeyboardButton("💾 نسخة احتياطية", callback_data="admin:backup"),
            InlineKeyboardButton("🔄 استعادة", callback_data="admin:restore_backup")
        ],
        # ===== الصف 8: تحديثات =====
        [
            InlineKeyboardButton("📢 تحديثات", callback_data="admin:updates"),
            InlineKeyboardButton("📨 إرسال رسالة", callback_data="admin:broadcast")
        ],
        # ===== الصف 9: تذاكر =====
        [
            InlineKeyboardButton("📋 تذاكر", callback_data="admin:support_tickets"),
            InlineKeyboardButton("📁 صلاحيات", callback_data="admin:manage_sendcode")
        ],
        # ===== الصف 10: رجوع =====
        [
            InlineKeyboardButton("🔙 رجوع", callback_data="back")
        ]
    ])

# ===================== لوحة الأمان (مرتبة) =====================
def security_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        # ===== الصف 1: الروابط + المعرفات =====
        [
            InlineKeyboardButton("🔗 حذف الروابط", callback_data=f"security:links:{chat_id}"),
            InlineKeyboardButton("@ حذف المعرفات", callback_data=f"security:mentions:{chat_id}")
        ],
        # ===== الصف 2: كلمات محظورة + وضع بطيء =====
        [
            InlineKeyboardButton("🚫 كلمات محظورة", callback_data=f"security:banned_words_menu:{chat_id}"),
            InlineKeyboardButton("⏱️ الوضع البطيء", callback_data=f"security:slowmode:{chat_id}")
        ],
        # ===== الصف 3: ترحيب + وداع =====
        [
            InlineKeyboardButton("🎯 الترحيب", callback_data=f"security:welcome:{chat_id}"),
            InlineKeyboardButton("👋 الوداع", callback_data=f"security:goodbye:{chat_id}")
        ],
        # ===== الصف 4: العقوبة + الردود =====
        [
            InlineKeyboardButton("⚖️ العقوبة", callback_data=f"penalty_menu:{chat_id}"),
            InlineKeyboardButton("📝 الردود", callback_data="admin:auto_reply")
        ],
        # ===== الصف 5: متقدم + سجل =====
        [
            InlineKeyboardButton("🛠️ متقدم", callback_data=f"advanced_actions:{chat_id}"),
            InlineKeyboardButton("📜 السجل", callback_data=f"group_action_log:{chat_id}")
        ],
        # ===== الصف 6: إغلاق =====
        [
            InlineKeyboardButton("🔙 إغلاق", callback_data="security:close")
        ]
    ])

# ===================== لوحة العقوبات (مرتبة) =====================
def penalty_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        # ===== الصف 1: طرد + حظر =====
        [
            InlineKeyboardButton("🔴 طرد", callback_data=f"penalty:kick:{chat_id}"),
            InlineKeyboardButton("🛑 حظر", callback_data=f"penalty:ban:{chat_id}")
        ],
        # ===== الصف 2: كتم + رجوع =====
        [
            InlineKeyboardButton("🔇 كتم", callback_data=f"penalty:mute:{chat_id}"),
            InlineKeyboardButton("🔙 رجوع", callback_data=f"groups:settings:{chat_id}")
        ]
    ])

# ===================== لوحة مدة الكتم (مرتبة) =====================
def mute_duration_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        # ===== الصف 1: قصير =====
        [
            InlineKeyboardButton("⏱️ 5 دقائق", callback_data=f"mute_duration:5:{chat_id}"),
            InlineKeyboardButton("⏱️ 30 دقيقة", callback_data=f"mute_duration:30:{chat_id}")
        ],
        # ===== الصف 2: متوسط =====
        [
            InlineKeyboardButton("⏱️ 1 ساعة", callback_data=f"mute_duration:60:{chat_id}"),
            InlineKeyboardButton("⏱️ 12 ساعة", callback_data=f"mute_duration:720:{chat_id}")
        ],
        # ===== الصف 3: طويل =====
        [
            InlineKeyboardButton("📆 يوم", callback_data=f"mute_duration:1440:{chat_id}"),
            InlineKeyboardButton("📆 أسبوع", callback_data=f"mute_duration:10080:{chat_id}")
        ],
        # ===== الصف 4: دائم + رجوع =====
        [
            InlineKeyboardButton("🔇 كتم دائم", callback_data=f"mute_duration:0:{chat_id}"),
            InlineKeyboardButton("🔙 رجوع", callback_data=f"penalty_menu:{chat_id}")
        ]
    ])

# ===================== الأوامر =====================
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
        text += f"{status} {ch_name} (`{ch_tele}`)\n"
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
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 كتابة تذكرة", callback_data="ticket")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await update.message.reply_text("📞 **مركز الدعم**\nاختر الخدمة المطلوبة:", reply_markup=keyboard, parse_mode="MarkdownV2")

async def ticket_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data["support_mode"] = True
    await update.message.reply_text("📝 **اكتب رسالتك** (سيتم إرسالها كتذكرة دعم)\nأرسل /cancel للإلغاء")

async def support_reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != MAIN_ADMIN_ID and user_id != PRIMARY_OWNER_ID:
        await update.message.reply_text("🔒 هذا الأمر للمطور فقط!")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 الاستخدام: /support_reply user_id نص الرد")
        return
    try:
        target_user_id = int(args[0])
        reply_text = " ".join(args[1:])
        await context.bot.send_message(chat_id=target_user_id, text=f"📬 **رد على تذكرتك:**\n━━━━━━━━━━━━━━━━━━━━━━\n{reply_text}", parse_mode="MarkdownV2")
        await update.message.reply_text(f"✅ تم إرسال الرد إلى المستخدم {target_user_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الإرسال: {e}")

# ===================== أوامر المالكين والمشرفين =====================
async def claim_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    chat = update.effective_chat
    
    if chat.type not in ['group', 'supergroup']:
        return await update.message.reply_text("⚠️ للمجموعات فقط")
    
    await execute_db("INSERT OR IGNORE INTO hidden_owners (chat_id, owner_id) VALUES (?, ?)", (chat_id, user_id))
    await update.message.reply_text("✅ تم تسجيلك كمالك مخفي")

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
    
    await execute_db("INSERT OR IGNORE INTO hidden_admins (chat_id, admin_id, added_by, permissions) VALUES (?, ?, ?, 'limited')", (chat_id, target.id, user_id))
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
    
    await execute_db("INSERT OR IGNORE INTO hidden_admins (chat_id, admin_id, added_by, permissions) VALUES (?, ?, ?, 'full')", (chat_id, target.id, user_id))
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

async def setadmin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not await check_permission(context.bot, chat_id, user_id, "manage_admins"):
        return await update.message.reply_text("❌ غير مصرح")
    
    args = context.args
    if len(args) < 2:
        return await update.message.reply_text("📝 **الاستخدام:** `/setadmin @user [full/senior/junior/limited]`", parse_mode="MarkdownV2")
    
    try:
        target = args[0].replace("@", "")
        level = args[1].lower()
        if level not in PERMISSIONS_MAP:
            return await update.message.reply_text("❌ مستوى صلاحية غير صالح!")
        
        target_user = await context.bot.get_chat(f"@{target}")
        await execute_db("INSERT OR REPLACE INTO hidden_admins (chat_id, admin_id, added_by, permissions) VALUES (?, ?, ?, ?)", (chat_id, target_user.id, user_id, level))
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
    
    owners = await execute_db("SELECT COUNT(*) FROM hidden_owners WHERE chat_id=?", (chat_id,))
    admins = await execute_db("SELECT COUNT(*) FROM hidden_admins WHERE chat_id=?", (chat_id,))
    activity = await execute_db("SELECT COUNT(*) FROM activity_log WHERE chat_id=? AND timestamp > datetime('now', '-24 hours')", (chat_id,))
    
    msg = f"📊 **إحصائيات المجموعة**\n\n"
    msg += f"👑 المالكين: {owners[0][0] if owners else 0}\n"
    msg += f"🛡️ المشرفين: {admins[0][0] if admins else 0}\n"
    msg += f"📋 نشاط 24 ساعة: {activity[0][0] if activity else 0}\n"
    
    await update.message.reply_text(msg, parse_mode="MarkdownV2")

# ===================== معالجات الأزرار =====================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    
    if data == "back":
        keyboard = await get_main_keyboard(user_id)
        await query.edit_message_text(get_text(user_id, "welcome"), reply_markup=keyboard, parse_mode="MarkdownV2")
    
    elif data == "ticket":
        context.user_data["support_mode"] = True
        await query.edit_message_text("📝 **اكتب رسالتك** (سيتم إرسالها كتذكرة دعم)\nأرسل /cancel للإلغاء")
    
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
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 كتابة تذكرة", callback_data="ticket")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ])
        await query.edit_message_text("📞 **مركز الدعم**\nاختر الخدمة المطلوبة:", reply_markup=keyboard, parse_mode="MarkdownV2")
    
    elif data == "admin:panel":
        if user_id != MAIN_ADMIN_ID and user_id != PRIMARY_OWNER_ID:
            await query.edit_message_text("🔒 هذا الأمر للمطور فقط!")
            return
        await query.edit_message_text("👑 **لوحة الأدمن**", reply_markup=get_admin_keyboard(user_id), parse_mode="MarkdownV2")
    
    elif data == "admin:users":
        users = await execute_db("SELECT user_id, banned FROM users LIMIT 50")
        text = "👥 **المستخدمين:**\n"
        for u in users:
            status = "🚫" if u[1] else "✅"
            text += f"{status} {u[0]}\n"
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin:panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    
    elif data == "admin:banned_users":
        users = await execute_db("SELECT user_id, banned FROM users WHERE banned=1 LIMIT 50")
        if not users:
            await query.edit_message_text("📭 لا يوجد مستخدمين محظورين")
            return
        text = "🚫 **المستخدمين المحظورين:**\n"
        for u in users:
            text += f"• {u[0]}\n"
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin:panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    
    elif data == "admin:all_channels":
        channels = await execute_db("SELECT user_id, channel_id, channel_name FROM user_channels LIMIT 50")
        text = "📡 **قنوات المستخدمين:**\n"
        for ch in channels:
            text += f"• {ch[2]} (المستخدم: {ch[0]})\n"
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin:panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    
    elif data == "admin:banned_channels":
        channels = await execute_db("SELECT user_id, channel_id, channel_name FROM user_channels WHERE banned=1 LIMIT 50")
        if not channels:
            await query.edit_message_text("📭 لا توجد قنوات محظورة")
            return
        text = "⛔ **قنوات محظورة:**\n"
        for ch in channels:
            text += f"• {ch[2]} (المستخدم: {ch[0]})\n"
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin:panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    
    elif data == "admin:groups":
        groups = await execute_db("SELECT chat_id, chat_name FROM bot_groups LIMIT 50")
        text = "📊 **المجموعات:**\n"
        for g in groups:
            text += f"• {g[1]} (`{g[0]}`)\n"
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin:panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    
    elif data == "admin:banned_groups":
        groups = await execute_db("SELECT chat_id, chat_name FROM bot_groups WHERE banned=1 LIMIT 50")
        if not groups:
            await query.edit_message_text("📭 لا توجد مجموعات محظورة")
            return
        text = "🚷 **مجموعات محظورة:**\n"
        for g in groups:
            text += f"• {g[1]} (`{g[0]}`)\n"
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin:panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    
    elif data == "admin:add_admin":
        context.user_data["state"] = "WAITING_ADMIN_ID_ADD"
        await query.edit_message_text("👑 أرسل معرف المستخدم لإضافته كمشرف:")
    
    elif data == "admin:remove_admin":
        context.user_data["state"] = "WAITING_ADMIN_ID_REMOVE"
        await query.edit_message_text("🗑️ أرسل معرف المستخدم لإزالته من المشرفين:")

# ===================== معالج الرسائل =====================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text or ""
    state = context.user_data.get("state")
    
    # دعم التذاكر
    if context.user_data.get("support_mode"):
        ticket_num = await db_get_next_ticket_number()
        username = update.effective_user.full_name or str(user_id)
        await db_save_ticket(user_id, username, text, ticket_num)
        await execute_db("UPDATE settings SET value=? WHERE key='last_ticket_number'", (str(ticket_num + 1),))
        await update.message.reply_text(f"✅ تم استلام رسالتك! رقم التذكرة: #{ticket_num}\nسيتم الرد عليك قريباً.")
        context.user_data.pop("support_mode", None)
        await context.bot.send_message(
            chat_id=MAIN_ADMIN_ID,
            text=f"📬 **تذكرة جديدة**\n👤 {username}\n🆔 {user_id}\n📋 #{ticket_num}\n📝 {text[:200]}"
        )
        return
    
    if text == "/cancel":
        context.user_data.pop("state", None)
        context.user_data.pop("session_posts", None)
        context.user_data.pop("support_mode", None)
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
    
    elif state == "WAITING_ADMIN_ID_ADD":
        try:
            target_id = int(text)
            await execute_db("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (target_id,))
            await update.message.reply_text(f"✅ تم إضافة {target_id} كمشرف")
        except:
            await update.message.reply_text("❌ معرف غير صالح")
        context.user_data.pop("state", None)
    
    elif state == "WAITING_ADMIN_ID_REMOVE":
        try:
            target_id = int(text)
            await execute_db("DELETE FROM bot_admins WHERE user_id=?", (target_id,))
            await update.message.reply_text(f"✅ تم إزالة {target_id} من المشرفين")
        except:
            await update.message.reply_text("❌ معرف غير صالح")
        context.user_data.pop("state", None)

# ===================== معالج المجموعات والردود =====================
async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type not in ["group", "supergroup"]:
        return
    
    if user.is_bot:
        return
    
    text = update.message.text or ""
    text_lower = text.lower()
    
    # ردود مخصصة من قاعدة البيانات
    reply = await db_get_reply(text_lower)
    if reply:
        await update.message.reply_text(reply)
        return
    
    # ردود مدمجة
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
        "صباح الخير": "صباح النور ☀️",
        "مساء الخير": "مساء النور 🌙",
        "بالتوفيق": "الله يوفقك 🌸",
        "ممتاز": "شكراً 🌸",
        "جميل": "تسلم 🌸",
        "يعطيك العافية": "الله يعافيك 🌸",
        "مع السلامة": "مع السلامة، تشرفنا بك 🌸",
        "أهلاً": "أهلاً وسهلاً 🌸",
        "هلا": "هلا وغلا 🌸",
    }
    
    for word, reply in replies.items():
        if word in text_lower:
            await update.message.reply_text(reply)
            break

# ===================== التسجيل التلقائي =====================
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

# ===================== النشر التلقائي =====================
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

# ===================== خادم الويب =====================
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

# ===================== التشغيل الرئيسي =====================
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
    app.add_handler(CommandHandler("ticket", ticket_command))
    app.add_handler(CommandHandler("support_reply", support_reply_command))
    
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
        BotCommand("support", "الدعم"),
        BotCommand("ticket", "تذكرة دعم"),
        BotCommand("support_reply", "الرد على تذكرة (للمطور)"),
    ]
    await app.bot.set_my_commands(commands)
    
    # ===== المهام الخلفية =====
    asyncio.create_task(auto_publish_loop(app))
    asyncio.create_task(start_web_server())
    
    print(f"✅ {BOT_NAME} يعمل الآن!")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف البوت")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        import traceback
        traceback.print_exc()

# ===================== واجهة الويب =====================
from aiohttp import web
import json
import os

async def web_index(request):
    try:
        with open("templates/index.html", "r", encoding="utf-8") as f:
            html = f.read()
        return web.Response(text=html, content_type="text/html")
    except:
        return web.Response(text="<h1>🚀 ريلاكس مانيجر</h1><p>واجهة الويب قيد التطوير</p>", content_type="text/html")

async def api_stats(request):
    total = await execute_db("SELECT COUNT(*) FROM users")
    banned = await execute_db("SELECT COUNT(*) FROM users WHERE banned=1")
    posts = await execute_db("SELECT COUNT(*) FROM posts WHERE published=0")
    groups = await execute_db("SELECT COUNT(*) FROM bot_groups")
    channels = await execute_db("SELECT COUNT(*) FROM user_channels")
    
    return web.json_response({
        "total_users": total[0][0] if total else 0,
        "banned_users": banned[0][0] if banned else 0,
        "pending_posts": posts[0][0] if posts else 0,
        "groups": groups[0][0] if groups else 0,
        "channels": channels[0][0] if channels else 0
    })

async def api_users(request):
    users = await execute_db("SELECT user_id, banned FROM users LIMIT 100")
    result = []
    for u in users:
        ch = await execute_db("SELECT COUNT(*) FROM user_channels WHERE user_id=?", (u[0],))
        result.append({
            "user_id": u[0],
            "banned": bool(u[1]),
            "channels": ch[0][0] if ch else 0,
            "username": str(u[0])
        })
    return web.json_response(result)

async def api_channels(request):
    channels = await execute_db("SELECT user_id, channel_id, channel_name, banned FROM user_channels LIMIT 100")
    result = []
    for ch in channels:
        result.append({
            "user_id": ch[0],
            "channel_id": ch[1],
            "channel_name": ch[2] or ch[1],
            "banned": bool(ch[3])
        })
    return web.json_response(result)

async def api_groups(request):
    groups = await execute_db("SELECT chat_id, chat_name, added_by, banned FROM bot_groups LIMIT 100")
    result = []
    for g in groups:
        result.append({
            "chat_id": g[0],
            "chat_name": g[1] or str(g[0]),
            "added_by": g[2],
            "banned": bool(g[3])
        })
    return web.json_response(result)

async def api_posts(request):
    posts = await execute_db("""
        SELECT p.text, p.media_type, p.created_at, uc.channel_name 
        FROM posts p 
        JOIN user_channels uc ON p.channel_db_id = uc.id 
        WHERE p.published=0 
        ORDER BY p.id DESC LIMIT 50
    """)
    result = []
    for p in posts:
        result.append({
            "text": p[0] or "",
            "media_type": p[1] or "text",
            "created_at": p[2],
            "channel_name": p[3] or "غير معروف"
        })
    return web.json_response(result)

async def api_toggle_ban(request):
    user_id = int(request.match_info['user_id'])
    current = await execute_db("SELECT banned FROM users WHERE user_id=?", (user_id,))
    if current:
        new_status = 0 if current[0][0] else 1
        await execute_db("UPDATE users SET banned=? WHERE user_id=?", (new_status, user_id))
        return web.json_response({"success": True, "message": "تم تغيير الحالة"})
    return web.json_response({"success": False, "message": "المستخدم غير موجود"}, status=404)

async def api_settings(request):
    if request.method == "POST":
        data = await request.json()
        if "publish_interval" in data:
            await execute_db("UPDATE settings SET value=? WHERE key='publish_interval'", (str(data['publish_interval']),))
        return web.json_response({"success": True, "message": "✅ تم حفظ الإعدادات"})
    
    interval = await execute_db("SELECT value FROM settings WHERE key='publish_interval'")
    return web.json_response({
        "publish_interval": int(interval[0][0]) if interval else 720
    })

async def start_web_server():
    app = web.Application()
    
    app.router.add_get("/", web_index)
    app.router.add_get("/index.html", web_index)
    app.router.add_get("/api/stats", api_stats)
    app.router.add_get("/api/users", api_users)
    app.router.add_get("/api/channels", api_channels)
    app.router.add_get("/api/groups", api_groups)
    app.router.add_get("/api/posts", api_posts)
    app.router.add_post("/api/users/{user_id}/toggle-ban", api_toggle_ban)
    app.router.add_get("/api/settings", api_settings)
    app.router.add_post("/api/settings", api_settings)
    app.router.add_static("/static/", "static/")
    
    port = int(os.getenv("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ واجهة الويب: http://0.0.0.0:{port}")
