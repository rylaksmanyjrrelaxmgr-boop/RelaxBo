#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
============================================================
ريلاكس مانيجر + نظام المجموعات المتكامل
============================================================
الإصدار: 19.0.9 - الكود الكامل
============================================================
"""

import os
import sys
import asyncio
import logging
import sqlite3
import json
import time
import re
import hashlib
import secrets
import base64
import tempfile
import shutil
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

# ===================== تثبيت المكتبات تلقائياً =====================
def install_package(package):
    try:
        __import__(package.split('==')[0])
        return True
    except ImportError:
        try:
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])
            return True
        except:
            return False

packages = [
    "python-telegram-bot>=20.0",
    "aiosqlite>=0.19.0",
    "python-dotenv>=1.0.0",
    "cryptography>=39.0.0",
    "cachetools>=5.3.0",
    "psutil>=5.9.0",
    "aiohttp>=3.8.0",
    "pillow>=9.0.0"
]

for pkg in packages:
    install_package(pkg)

# ===================== استيراد المكتبات =====================
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import TimedOut, NetworkError, BadRequest, Forbidden

import aiosqlite
import aiohttp
from cryptography.fernet import Fernet

# ===================== الإعدادات من متغيرات البيئة =====================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("❌ BOT_TOKEN غير موجود!")
    sys.exit(1)

MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", "0"))
if MAIN_ADMIN_ID == 0:
    print("❌ MAIN_ADMIN_ID غير موجود!")
    sys.exit(1)

BOT_NAME = os.getenv("BOT_NAME", "ريلاكس مانيجر")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Reelaaaxbot")
DB_PATH = os.getenv("DB_PATH", "bot_data.db")

# إعدادات NSFW
NSFW_ENABLED = os.getenv("NSFW_ENABLED", "True").lower() in ["true", "1", "yes", "on"]
NSFW_THRESHOLD = float(os.getenv("NSFW_THRESHOLD", "0.7"))
SIGHTENGINE_API_USER = os.getenv("SIGHTENGINE_API_USER", "")
SIGHTENGINE_API_SECRET = os.getenv("SIGHTENGINE_API_SECRET", "")

# إعدادات أخرى
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 20 * 1024 * 1024))
MAX_UNPUBLISHED_POSTS = int(os.getenv('MAX_UNPUBLISHED_POSTS', 1000))
MAX_POSTS_PER_SESSION = int(os.getenv('MAX_POSTS_PER_SESSION', 50))
DEFAULT_PUBLISH_INTERVAL_SECONDS = int(os.getenv('DEFAULT_PUBLISH_INTERVAL_SECONDS', 720))
MAX_BACKUPS = int(os.getenv('MAX_BACKUPS', 10))

# ===================== نظام التسجيل =====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===================== دوال الوقت =====================
def utc_now():
    return datetime.now()

def mecca_now():
    return utc_now() + timedelta(hours=3)

def utc_now_iso():
    return utc_now().isoformat()

def mecca_now_iso():
    return mecca_now().isoformat()

# ===================== دوال قاعدة البيانات =====================
_conn = None

async def get_db():
    global _conn
    if _conn is None:
        _conn = await aiosqlite.connect(DB_PATH)
        _conn.row_factory = aiosqlite.Row
        await _conn.executescript("""
            -- ========== جداول المستخدمين ==========
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                auto_publish INTEGER DEFAULT 1,
                banned INTEGER DEFAULT 0,
                trial_used INTEGER DEFAULT 0,
                subscription_end TEXT DEFAULT NULL,
                referral_code TEXT DEFAULT NULL,
                active_channel INTEGER DEFAULT NULL,
                auto_recycle INTEGER DEFAULT 1,
                language TEXT DEFAULT 'ar',
                points INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1
            );
            
            -- ========== جداول القنوات ==========
            CREATE TABLE IF NOT EXISTS user_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id TEXT,
                channel_name TEXT,
                created_at TIMESTAMP,
                banned INTEGER DEFAULT 0
            );
            
            -- ========== جداول المنشورات ==========
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_db_id INTEGER,
                text TEXT,
                media_type TEXT DEFAULT 'text',
                media_file_id TEXT,
                published INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                views_count INTEGER DEFAULT 0,
                last_view_time TIMESTAMP,
                created_at TIMESTAMP
            );
            
            -- ========== جداول الجدولة ==========
            CREATE TABLE IF NOT EXISTS schedule (
                channel_db_id INTEGER PRIMARY KEY,
                schedule_type TEXT DEFAULT 'interval_minutes',
                interval_minutes INTEGER DEFAULT 12,
                interval_hours INTEGER DEFAULT 0,
                interval_days INTEGER DEFAULT 0,
                days_of_week TEXT DEFAULT '',
                specific_dates TEXT DEFAULT '',
                publish_time TEXT DEFAULT '00:00',
                cron_expression TEXT DEFAULT NULL,
                next_publish_date TEXT
            );
            
            CREATE TABLE IF NOT EXISTS last_publish (
                channel_db_id INTEGER PRIMARY KEY,
                last_publish_time TIMESTAMP
            );
            
            -- ========== جداول المجموعات ==========
            CREATE TABLE IF NOT EXISTS owners (
                chat_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY(chat_id, user_id)
            );
            
            CREATE TABLE IF NOT EXISTS admins (
                chat_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY(chat_id, user_id)
            );
            
            CREATE TABLE IF NOT EXISTS group_settings (
                chat_id INTEGER PRIMARY KEY,
                lock_links INTEGER DEFAULT 0,
                lock_mentions INTEGER DEFAULT 0,
                slow_mode INTEGER DEFAULT 0,
                welcome_msg TEXT,
                goodbye_msg TEXT
            );
            
            CREATE TABLE IF NOT EXISTS moderation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                admin_id INTEGER,
                target_id INTEGER,
                action TEXT,
                reason TEXT,
                timestamp TEXT
            );
            
            -- ========== جداول الردود والكلمات المحظورة ==========
            CREATE TABLE IF NOT EXISTS replies (
                keyword TEXT PRIMARY KEY,
                reply TEXT
            );
            
            CREATE TABLE IF NOT EXISTS banned_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT,
                chat_id INTEGER DEFAULT -1,
                UNIQUE(word, chat_id)
            );
            
            -- ========== جداول المستخدمين المؤقتة ==========
            CREATE TABLE IF NOT EXISTS user_messages (
                user_id INTEGER,
                chat_id INTEGER,
                message_time TEXT,
                PRIMARY KEY(user_id, chat_id)
            );
            
            -- ========== جداول الإعدادات ==========
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            
            -- ========== جداول الدعم ==========
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                message TEXT,
                ticket_number INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP,
                replied INTEGER DEFAULT 0
            );
            
            -- ========== جداول الترجمة ==========
            CREATE TABLE IF NOT EXISTS user_translation (
                user_id INTEGER PRIMARY KEY,
                lang TEXT DEFAULT 'off'
            );
        """)
        await _conn.commit()
        
        # إدراج البيانات الافتراضية
        await _conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(DEFAULT_PUBLISH_INTERVAL_SECONDS),))
        await _conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_ticket_number', '0')")
        await _conn.commit()
    
    return _conn

async def db_execute(query: str, *params):
    conn = await get_db()
    cursor = await conn.execute(query, params)
    await conn.commit()
    return cursor

async def db_fetch(query: str, *params):
    conn = await get_db()
    cursor = await conn.execute(query, params)
    return await cursor.fetchall()

async def db_fetch_one(query: str, *params):
    conn = await get_db()
    cursor = await conn.execute(query, params)
    return await cursor.fetchone()

# ============================================================
# نظام المجموعات - دوال الصلاحيات
# ============================================================

_perm_cache = {}
_PERM_TTL = 300

async def check_perm(bot, chat_id: int, user_id: int) -> bool:
    key = f"{chat_id}_{user_id}"
    now = time.time()
    
    if key in _perm_cache:
        cached_time, cached_result = _perm_cache[key]
        if now - cached_time < _PERM_TTL:
            return cached_result
    
    result = False
    
    if user_id == MAIN_ADMIN_ID:
        result = True
    elif await db_fetch_one("SELECT 1 FROM owners WHERE chat_id=? AND user_id=?", chat_id, user_id):
        result = True
    elif await db_fetch_one("SELECT 1 FROM admins WHERE chat_id=? AND user_id=?", chat_id, user_id):
        result = True
    else:
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            if member.status in ['creator', 'administrator']:
                result = True
        except:
            pass
    
    _perm_cache[key] = (now, result)
    return result

def has_links(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r'https?://\S+', text))

def has_mentions(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r'@\w+', text))

async def auto_penalty(bot, chat_id: int, user_id: int):
    try:
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id)
    except:
        pass

# ============================================================
# نظام NSFW
# ============================================================

NSFW_CACHE = {}
NSFW_CACHE_TTL = 300

async def check_nsfw_image(image_bytes: bytes) -> dict:
    try:
        if not SIGHTENGINE_API_USER or not SIGHTENGINE_API_SECRET:
            return {"nsfw": False, "score": 0, "error": "API غير مفعل"}

        from PIL import Image
        import io
        
        img = Image.open(io.BytesIO(image_bytes))
        img.thumbnail((800, 800))
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=80)
        compressed = buffer.getvalue()

        image_b64 = base64.b64encode(compressed).decode('utf-8')

        async with aiohttp.ClientSession() as session:
            url = "https://api.sightengine.com/1.0/check.json"
            params = {
                "models": "nudity-2.0,wad",
                "api_user": SIGHTENGINE_API_USER,
                "api_secret": SIGHTENGINE_API_SECRET,
                "image": image_b64
            }

            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return {"nsfw": False, "score": 0, "error": f"فشل الاتصال ({resp.status})"}

                data = await resp.json()
                nsfw_score = data.get("nudity", {}).get("safe", 1)
                nsfw_score = 1 - nsfw_score
                wad = max(data.get("weapon", 0) or 0, data.get("drugs", 0) or 0, data.get("alcohol", 0) or 0)

                return {
                    "nsfw": nsfw_score > NSFW_THRESHOLD or wad > NSFW_THRESHOLD,
                    "nsfw_score": round(nsfw_score, 2),
                    "wad_score": round(wad, 2)
                }

    except Exception as e:
        return {"nsfw": False, "score": 0, "error": str(e)}

async def check_nsfw_cached(image_bytes: bytes) -> dict:
    cache_key = hashlib.md5(image_bytes).hexdigest()
    if cache_key in NSFW_CACHE:
        cached_data, cached_time = NSFW_CACHE[cache_key]
        if time.time() - cached_time < NSFW_CACHE_TTL:
            return cached_data
    
    result = await check_nsfw_image(image_bytes)
    NSFW_CACHE[cache_key] = (result, time.time())
    return result

# ============================================================
# دوال القنوات
# ============================================================

async def db_save_posts(channel_db_id: int, posts: list) -> int:
    conn = await get_db()
    saved = 0
    for text_content, media_type, media_file_id in posts:
        await conn.execute(
            "INSERT INTO posts (channel_db_id, text, media_type, media_file_id, created_at) VALUES (?, ?, ?, ?, ?)",
            channel_db_id, text_content, media_type, media_file_id, utc_now_iso()
        )
        saved += 1
    await conn.commit()
    return saved

async def db_get_next_post(channel_db_id: int) -> dict | None:
    row = await db_fetch_one(
        "SELECT id, text, media_type, media_file_id FROM posts WHERE channel_db_id=? AND published=0 AND (fail_count IS NULL OR fail_count < 3) ORDER BY id LIMIT 1",
        (channel_db_id,)
    )
    if row:
        return {'id': row[0], 'text': row[1], 'media_type': row[2], 'media_file_id': row[3]}
    return None

async def db_mark_published(post_id: int):
    await db_execute("UPDATE posts SET published=1 WHERE id=?", post_id)

async def db_get_unpublished_count(channel_db_id: int) -> int:
    row = await db_fetch_one("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0", (channel_db_id,))
    return row[0] if row else 0

async def db_get_channel_info(channel_db_id: int):
    return await db_fetch_one("SELECT channel_id, channel_name FROM user_channels WHERE id=?", channel_db_id)

async def db_get_active_channel(user_id: int) -> int | None:
    row = await db_fetch_one("SELECT active_channel FROM users WHERE user_id=?", user_id)
    if row and row[0]:
        return row[0]
    row = await db_fetch_one("SELECT id FROM user_channels WHERE user_id=? AND banned=0 ORDER BY id LIMIT 1", user_id)
    return row[0] if row else None

async def db_set_active_channel(user_id: int, channel_db_id: int):
    await db_execute("UPDATE users SET active_channel=? WHERE user_id=?", channel_db_id, user_id)

async def db_get_channels(user_id: int):
    return await db_fetch("SELECT id, channel_id, channel_name, banned FROM user_channels WHERE user_id=? ORDER BY id", user_id)

async def db_add_channel(user_id: int, channel_id: str, channel_name: str) -> int | None:
    existing = await db_fetch_one("SELECT id FROM user_channels WHERE user_id=? AND channel_id=?", user_id, channel_id)
    if existing:
        return None
    await db_execute(
        "INSERT INTO user_channels (user_id, channel_id, channel_name, created_at) VALUES (?, ?, ?, ?)",
        user_id, channel_id, channel_name, utc_now_iso()
    )
    row = await db_fetch_one("SELECT id FROM user_channels WHERE user_id=? AND channel_id=?", user_id, channel_id)
    return row[0] if row else None

async def db_delete_channel_by_id(user_id: int, channel_db_id: int) -> bool:
    await db_execute("DELETE FROM user_channels WHERE id=? AND user_id=?", channel_db_id, user_id)
    await db_execute("DELETE FROM posts WHERE channel_db_id=?", channel_db_id)
    await db_execute("DELETE FROM schedule WHERE channel_db_id=?", channel_db_id)
    return True

async def db_reset_posts_to_unpublished(channel_db_id: int):
    await db_execute("UPDATE posts SET published=0, fail_count=0 WHERE channel_db_id=?", channel_db_id)

async def db_get_user_unpublished_posts(user_id: int) -> int:
    row = await db_fetch_one(
        "SELECT COUNT(*) FROM posts p JOIN user_channels uc ON p.channel_db_id=uc.id WHERE uc.user_id=? AND p.published=0",
        user_id
    )
    return row[0] if row else 0

async def db_get_user_total_posts(user_id: int) -> int:
    row = await db_fetch_one(
        "SELECT COUNT(*) FROM posts p JOIN user_channels uc ON p.channel_db_id=uc.id WHERE uc.user_id=?",
        user_id
    )
    return row[0] if row else 0

async def db_get_user_channels_count(user_id: int) -> int:
    row = await db_fetch_one("SELECT COUNT(*) FROM user_channels WHERE user_id=?", user_id)
    return row[0] if row else 0

# ============================================================
# دوال المجموعات
# ============================================================

_banned_cache = {}
_banned_cache_time = 0
_BANNED_CACHE_TTL = 60

async def load_banned_cache():
    global _banned_cache, _banned_cache_time
    now = time.time()
    if now - _banned_cache_time < _BANNED_CACHE_TTL:
        return
    
    rows = await db_fetch("SELECT chat_id, word FROM banned_words")
    _banned_cache = {}
    for row in rows:
        chat_id = row['chat_id']
        word = row['word']
        if chat_id not in _banned_cache:
            _banned_cache[chat_id] = []
        _banned_cache[chat_id].append(word)
    _banned_cache_time = now

# ============================================================
# معالج الرسائل الرئيسي
# ============================================================

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return
    
    chat = update.effective_chat
    user = update.effective_user
    chat_type = chat.type
    
    if user.is_bot:
        return
    
    # ===== معالجة الرسائل الخاصة =====
    if chat_type == "private":
        await handle_private_message(update, context)
        return
    
    # ===== معالجة رسائل المجموعات =====
    if chat_type in ["group", "supergroup"]:
        await handle_group_message(update, context)
        return
    
    # ===== معالجة رسائل القنوات =====
    if chat_type == "channel":
        await handle_channel_message(update, context)
        return

# ============================================================
# معالج الرسائل الخاصة
# ============================================================

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text or ""
    
    # حالة إضافة المنشورات
    if context.user_data.get('state') == 'ADDING_POSTS':
        await handle_add_posts(update, context)
        return
    
    # حالة الدعم
    if context.user_data.get('support_mode'):
        await handle_support_message(update, context)
        return
    
    # ردود ذكية
    if text and not text.startswith('/'):
        await handle_smart_reply(update, context)

# ============================================================
# معالج رسائل المجموعات
# ============================================================

async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    text = update.message.text or update.message.caption or ""
    
    # التحقق من صلاحيات البوت
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if bot_member.status not in ['administrator', 'creator']:
            return
    except:
        return
    
    # جلب إعدادات المجموعة
    settings = await db_fetch_one("SELECT * FROM group_settings WHERE chat_id=?", chat_id)
    lock_links = settings['lock_links'] if settings else 0
    lock_mentions = settings['lock_mentions'] if settings else 0
    slow_mode = settings['slow_mode'] if settings else 0
    
    # الوضع البطيء
    if slow_mode > 0:
        last_msg = await db_fetch_one(
            "SELECT message_time FROM user_messages WHERE user_id=? AND chat_id=?",
            user_id, chat_id
        )
        now = datetime.now()
        if last_msg:
            last_time = datetime.fromisoformat(last_msg['message_time'])
            diff = (now - last_time).total_seconds()
            if diff < slow_mode:
                try:
                    await update.message.delete()
                except:
                    pass
                await update.message.reply_text(f"⏱️ انتظر {int(slow_mode - diff)} ثانية")
                return
        
        await db_execute(
            "INSERT OR REPLACE INTO user_messages (user_id, chat_id, message_time) VALUES (?, ?, ?)",
            user_id, chat_id, now.isoformat()
        )
    
    # فحص الروابط
    if lock_links and has_links(text):
        try:
            await update.message.delete()
        except:
            pass
        await auto_penalty(context.bot, chat_id, user_id)
        return
    
    # فحص الإشارات
    if lock_mentions and has_mentions(text):
        try:
            await update.message.delete()
        except:
            pass
        await auto_penalty(context.bot, chat_id, user_id)
        return
    
    # فحص الكلمات المحظورة
    await load_banned_cache()
    words = _banned_cache.get(chat_id, []) + _banned_cache.get(-1, [])
    text_lower = text.lower()
    for word in words:
        if word in text_lower:
            try:
                await update.message.delete()
            except:
                pass
            await auto_penalty(context.bot, chat_id, user_id)
            return
    
    # كشف NSFW
    if NSFW_ENABLED and update.message.photo:
        file = await context.bot.get_file(update.message.photo[-1].file_id)
        if file.file_size <= 5 * 1024 * 1024:
            try:
                file_bytes = await file.download_as_bytearray()
                result = await check_nsfw_cached(file_bytes)
                if result.get("nsfw", False):
                    await update.message.delete()
                    await update.message.reply_text(
                        f"🚫 تم حذف الصورة\nنسبة المحتوى غير اللائق: {result['nsfw_score'] * 100:.0f}%"
                    )
                    await auto_penalty(context.bot, chat_id, user_id)
                    return
            except:
                pass
    
    # الردود التلقائية
    reply = await db_fetch_one("SELECT reply FROM replies WHERE keyword=?", text_lower)
    if reply:
        await update.message.reply_text(reply['reply'])
        return
    
    # ردود مدمجة
    default_replies = {
        "مرحباً": "أهلاً وسهلاً بك 🤍",
        "السلام عليكم": "وعليكم السلام 🌹",
        "شكراً": "العفو 🤍",
        "كيف حالك": "الحمد لله بخير 🙏",
        "الو": "هلا والله 🌹",
        "هلا": "هلا بك 🤍",
        "اهلا": "أهلاً وسهلاً 🤍",
        "مرحبا": "مرحباً بك 🤍",
        "سلام": "وعليكم السلام 🌹"
    }
    for keyword, response in default_replies.items():
        if keyword in text_lower:
            await update.message.reply_text(response)
            break

# ============================================================
# معالج رسائل القنوات
# ============================================================

async def handle_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.message
    
    if not message or not chat:
        return
    
    chat_id = chat.id
    
    # البحث عن القناة في قاعدة البيانات
    channel = await db_fetch_one(
        "SELECT id FROM user_channels WHERE channel_id=? OR channel_id=?",
        str(chat_id), f"-100{chat_id}"
    )
    
    if not channel:
        return
    
    channel_db_id = channel[0]
    
    # تسجيل المشاهدات
    post = await db_fetch_one(
        "SELECT id, views_count FROM posts WHERE channel_db_id=? ORDER BY id DESC LIMIT 1",
        (channel_db_id,)
    )
    
    if post:
        post_id = post[0]
        views = post[1] + 1
        await db_execute(
            "UPDATE posts SET views_count=?, last_view_time=? WHERE id=?",
            views, utc_now_iso(), post_id
        )

# ============================================================
# نظام إضافة المنشورات
# ============================================================

async def handle_add_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session_key = f"session_{user_id}"
    
    if session_key not in context.user_data:
        return
    
    media_type = 'text'
    media_file_id = None
    text_content = update.message.text or ""
    
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
    current = len(context.user_data[session_key])
    target = context.user_data.get(f"session_target_{user_id}", 15)
    
    await update.message.reply_text(f"📥 تم استلام المنشور {current}/{target}")
    
    if current >= target:
        posts = context.user_data.get(session_key, [])
        if posts:
            active_channel = await db_get_active_channel(user_id)
            if not active_channel:
                await update.message.reply_text("⚠️ لا توجد قناة نشطة")
                return
            
            saved = await db_save_posts(active_channel, posts)
            context.user_data.pop(session_key, None)
            context.user_data.pop(f"session_target_{user_id}", None)
            context.user_data.pop('state', None)
            
            await update.message.reply_text(f"✅ تم حفظ {saved} منشور")

# ============================================================
# نظام الدعم
# ============================================================

async def handle_support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text or ""
    
    if not text:
        return
    
    # جلب رقم التذكرة
    row = await db_fetch_one("SELECT value FROM settings WHERE key='last_ticket_number'")
    ticket_num = int(row[0]) + 1 if row else 1
    
    await db_execute(
        "INSERT INTO support_tickets (user_id, username, message, ticket_number, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        user_id, update.effective_user.full_name or str(user_id), text, ticket_num, 'pending', utc_now_iso()
    )
    await db_execute("UPDATE settings SET value=? WHERE key='last_ticket_number'", str(ticket_num))
    
    await update.message.reply_text(
        f"✅ تم استلام رسالتك!\n📋 رقم التذكرة: #{ticket_num}\n\nسيتم الرد عليك في أقرب وقت ممكن."
    )
    
    try:
        await context.bot.send_message(
            MAIN_ADMIN_ID,
            f"📬 تذكرة دعم جديدة\n\n"
            f"👤 المستخدم: {update.effective_user.full_name}\n"
            f"🆔 المعرف: {user_id}\n"
            f"📋 رقم التذكرة: #{ticket_num}\n\n"
            f"📝 الرسالة:\n{text[:500]}"
        )
    except:
        pass
    
    context.user_data['support_mode'] = False

# ============================================================
# نظام الردود الذكية
# ============================================================

async def handle_smart_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    text_lower = text.lower()
    
    smart_replies = {
        "مرحباً": "أهلاً وسهلاً بك 🤍",
        "السلام عليكم": "وعليكم السلام 🌹",
        "شكراً": "العفو 🤍",
        "كيف حالك": "الحمد لله بخير 🙏",
        "الو": "هلا والله 🌹",
        "هلا": "هلا بك 🤍",
        "اهلا": "أهلاً وسهلاً 🤍",
        "مرحبا": "مرحباً بك 🤍",
        "سلام": "وعليكم السلام 🌹",
        "help": "استخدم /help لعرض الأوامر",
        "مساعدة": "استخدم /help لعرض الأوامر"
    }
    
    for keyword, response in smart_replies.items():
        if keyword in text_lower:
            await update.message.reply_text(response)
            break

# ============================================================
# أوامر البوت
# ============================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # تسجيل المستخدم
    await db_execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", user_id)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 قنواتي", callback_data="my_channels")],
        [InlineKeyboardButton("➕ إضافة قناة", callback_data="add_channel")],
        [InlineKeyboardButton("📥 إضافة 15 منشور", callback_data="add_posts")],
        [InlineKeyboardButton("📤 نشر واحد", callback_data="publish_one")],
        [InlineKeyboardButton("📋 منشوراتي", callback_data="my_posts")],
        [InlineKeyboardButton("♻️ إعادة تدوير", callback_data="recycle")],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="my_stats")],
        [InlineKeyboardButton("👥 مجموعاتي", callback_data="my_groups")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="help")],
        [InlineKeyboardButton("🌐 اللغة", callback_data="language")]
    ])
    
    await update.message.reply_text(
        f"🌿 **مرحباً بك في {BOT_NAME}**\n\n"
        f"👤 المعرف: `{user_id}`\n"
        f"اختر الإجراء المناسب:",
        reply_markup=keyboard,
        parse_mode="MarkdownV2"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    await update.message.reply_text(
        f"🤖 **{BOT_NAME}**\n\n"
        f"📌 الإصدار: 19.0.9\n"
        f"👑 المطور: @RelaxMgr\n\n"
        f"📋 **الأوامر المتاحة:**\n"
        f"/start - القائمة الرئيسية\n"
        f"/help - هذه المساعدة\n\n"
        f"👑 **أوامر المجموعات:**\n"
        f"/claim - تسجيل مالك مخفي\n"
        f"/addowner @user - إضافة مالك\n"
        f"/addadmin @user - إضافة مشرف\n"
        f"/remove @user - إزالة صلاحيات\n"
        f"/list - عرض الصلاحيات\n"
        f"/lock_links - حظر الروابط\n"
        f"/unlock_links - إلغاء حظر الروابط\n"
        f"/lock_mentions - حظر الإشارات\n"
        f"/unlock_mentions - إلغاء حظر الإشارات\n"
        f"/slowmode 5 - وضع بطيء\n"
        f"/welcome رسالة - ترحيب\n"
        f"/goodbye رسالة - وداع\n"
        f"/add_banned كلمة - كلمة محظورة\n"
        f"/remove_banned كلمة - حذف كلمة\n"
        f"/list_banned - عرض الكلمات\n"
        f"/add_reply كلمة رد - رد تلقائي\n"
        f"/remove_reply كلمة - حذف رد\n"
        f"/list_replies - عرض الردود\n"
        f"/log - سجل الإجراءات\n"
        f"/settings - إعدادات المجموعة"
    )

# ============================================================
# أوامر المجموعات
# ============================================================

async def cmd_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    existing = await db_fetch_one("SELECT 1 FROM owners WHERE chat_id=?", chat_id)
    if existing:
        await update.message.reply_text("⚠️ يوجد مالك بالفعل")
        return
    
    await db_execute("INSERT INTO owners VALUES (?, ?)", chat_id, user_id)
    await update.message.reply_text("✅ تم تسجيلك كمالك مخفي")

async def cmd_addowner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            target = await context.bot.get_chat(f"@{context.args[0].replace('@', '')}")
        except:
            try:
                target = await context.bot.get_chat(int(context.args[0]))
            except:
                pass
    
    if not target:
        await update.message.reply_text("/addowner @user")
        return
    
    await db_execute("INSERT OR IGNORE INTO owners VALUES (?, ?)", chat_id, target.id)
    await update.message.reply_text(f"✅ {target.first_name} أصبح مالكاً")

async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            target = await context.bot.get_chat(f"@{context.args[0].replace('@', '')}")
        except:
            try:
                target = await context.bot.get_chat(int(context.args[0]))
            except:
                pass
    
    if not target:
        await update.message.reply_text("/addadmin @user")
        return
    
    await db_execute("INSERT OR IGNORE INTO admins VALUES (?, ?)", chat_id, target.id)
    await update.message.reply_text(f"✅ {target.first_name} أصبح مشرفاً مخفياً")

async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            target = await context.bot.get_chat(f"@{context.args[0].replace('@', '')}")
        except:
            try:
                target = await context.bot.get_chat(int(context.args[0]))
            except:
                pass
    
    if not target:
        await update.message.reply_text("/remove @user")
        return
    
    await db_execute("DELETE FROM owners WHERE chat_id=? AND user_id=?", chat_id, target.id)
    await db_execute("DELETE FROM admins WHERE chat_id=? AND user_id=?", chat_id, target.id)
    await update.message.reply_text(f"✅ تم إزالة {target.first_name}")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    
    owners = await db_fetch("SELECT user_id FROM owners WHERE chat_id=?", chat_id)
    admins = await db_fetch("SELECT user_id FROM admins WHERE chat_id=?", chat_id)
    
    msg = "👑 **المالكين:**\n"
    for row in owners:
        try:
            user = await context.bot.get_chat(row['user_id'])
            msg += f"• {user.first_name}\n"
        except:
            msg += f"• {row['user_id']}\n"
    
    msg += "\n🛡️ **المشرفين المخفيين:**\n"
    for row in admins:
        try:
            user = await context.bot.get_chat(row['user_id'])
            msg += f"• {user.first_name}\n"
        except:
            msg += f"• {row['user_id']}\n"
    
    await update.message.reply_text(msg or "فارغ")

async def cmd_lock_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    await db_execute("INSERT OR IGNORE INTO group_settings(chat_id) VALUES (?)", chat_id)
    await db_execute("UPDATE group_settings SET lock_links=1 WHERE chat_id=?", chat_id)
    await update.message.reply_text("✅ تم تفعيل حظر الروابط")

async def cmd_unlock_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    await db_execute("UPDATE group_settings SET lock_links=0 WHERE chat_id=?", chat_id)
    await update.message.reply_text("✅ تم إلغاء حظر الروابط")

async def cmd_lock_mentions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    await db_execute("INSERT OR IGNORE INTO group_settings(chat_id) VALUES (?)", chat_id)
    await db_execute("UPDATE group_settings SET lock_mentions=1 WHERE chat_id=?", chat_id)
    await update.message.reply_text("✅ تم تفعيل حظر الإشارات")

async def cmd_unlock_mentions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    await db_execute("UPDATE group_settings SET lock_mentions=0 WHERE chat_id=?", chat_id)
    await update.message.reply_text("✅ تم إلغاء حظر الإشارات")

async def cmd_slowmode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    try:
        seconds = int(context.args[0]) if context.args else 0
    except:
        await update.message.reply_text("/slowmode 5")
        return
    
    await db_execute("INSERT OR IGNORE INTO group_settings(chat_id) VALUES (?)", chat_id)
    await db_execute("UPDATE group_settings SET slow_mode=? WHERE chat_id=?", seconds, chat_id)
    await update.message.reply_text(f"✅ وضع بطيء: {seconds} ثانية")

async def cmd_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    msg = " ".join(context.args) if context.args else ""
    if not msg:
        await update.message.reply_text("/welcome رسالة")
        return
    
    await db_execute("INSERT OR IGNORE INTO group_settings(chat_id) VALUES (?)", chat_id)
    await db_execute("UPDATE group_settings SET welcome_msg=? WHERE chat_id=?", msg, chat_id)
    await update.message.reply_text("✅ تم تعيين رسالة الترحيب")

async def cmd_goodbye(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    msg = " ".join(context.args) if context.args else ""
    if not msg:
        await update.message.reply_text("/goodbye رسالة")
        return
    
    await db_execute("INSERT OR IGNORE INTO group_settings(chat_id) VALUES (?)", chat_id)
    await db_execute("UPDATE group_settings SET goodbye_msg=? WHERE chat_id=?", msg, chat_id)
    await update.message.reply_text("✅ تم تعيين رسالة الوداع")

async def cmd_add_banned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    if not context.args:
        await update.message.reply_text("/add_banned كلمة")
        return
    
    word = context.args[0].lower()
    is_global = "-global" in context.args
    target_chat = -1 if is_global else chat_id
    
    await db_execute("INSERT OR IGNORE INTO banned_words (word, chat_id) VALUES (?, ?)", word, target_chat)
    global _banned_cache_time
    _banned_cache_time = 0
    
    await update.message.reply_text(f"✅ تم إضافة `{word}`")

async def cmd_remove_banned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    if not context.args:
        await update.message.reply_text("/remove_banned كلمة")
        return
    
    word = context.args[0].lower()
    is_global = "-global" in context.args
    target_chat = -1 if is_global else chat_id
    
    await db_execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", word, target_chat)
    global _banned_cache_time
    _banned_cache_time = 0
    
    await update.message.reply_text(f"✅ تم حذف `{word}`")

async def cmd_list_banned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    
    group_words = await db_fetch("SELECT word FROM banned_words WHERE chat_id=?", chat_id)
    global_words = await db_fetch("SELECT word FROM banned_words WHERE chat_id=-1")
    
    msg = "🚫 **الكلمات المحظورة:**\n\n"
    msg += "📌 **المجموعة:**\n"
    if group_words:
        msg += "، ".join([f"`{row['word']}`" for row in group_words])
    else:
        msg += "لا توجد"
    
    msg += "\n\n🌍 **عامة:**\n"
    if global_words:
        msg += "، ".join([f"`{row['word']}`" for row in global_words])
    else:
        msg += "لا توجد"
    
    await update.message.reply_text(msg)

async def cmd_add_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("/add_reply كلمة رد")
        return
    
    keyword = context.args[0].lower()
    reply = " ".join(context.args[1:])
    
    await db_execute("INSERT OR REPLACE INTO replies (keyword, reply) VALUES (?, ?)", keyword, reply)
    await update.message.reply_text(f"✅ تم إضافة رد للكلمة `{keyword}`")

async def cmd_remove_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    if not context.args:
        await update.message.reply_text("/remove_reply كلمة")
        return
    
    keyword = context.args[0].lower()
    await db_execute("DELETE FROM replies WHERE keyword=?", keyword)
    await update.message.reply_text(f"✅ تم حذف رد `{keyword}`")

async def cmd_list_replies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    replies = await db_fetch("SELECT keyword, reply FROM replies")
    if not replies:
        await update.message.reply_text("📭 لا توجد ردود")
        return
    
    msg = "💬 **الردود التلقائية:**\n\n"
    for row in replies:
        msg += f"• `{row['keyword']}` → {row['reply'][:50]}\n"
    
    await update.message.reply_text(msg)

async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    logs = await db_fetch(
        "SELECT * FROM moderation_log WHERE chat_id=? ORDER BY id DESC LIMIT 20",
        chat_id
    )
    
    if not logs:
        await update.message.reply_text("📭 لا توجد سجلات")
        return
    
    msg = "📜 **سجل الإجراءات:**\n\n"
    for row in logs:
        msg += f"• {row['action']} → {row['target_id']}"
        if row['reason']:
            msg += f"\n  📝 {row['reason']}"
        msg += f"\n  🕐 {row['timestamp'][:19]}\n\n"
    
    await update.message.reply_text(msg)

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ للمجموعات فقط")
        return
    
    chat_id = chat.id
    user_id = update.effective_user.id
    
    if not await check_perm(context.bot, chat_id, user_id):
        await update.message.reply_text("❌ غير مصرح")
        return
    
    settings = await db_fetch_one("SELECT * FROM group_settings WHERE chat_id=?", chat_id)
    
    if not settings:
        await update.message.reply_text("📋 لا توجد إعدادات")
        return
    
    msg = "⚙️ **الإعدادات:**\n\n"
    msg += f"🔗 الروابط: {'✅' if settings['lock_links'] else '❌'}\n"
    msg += f"@ الإشارات: {'✅' if settings['lock_mentions'] else '❌'}\n"
    msg += f"⏱️ وضع بطيء: {'✅ ' + str(settings['slow_mode']) + 'ث' if settings['slow_mode'] else '❌'}\n"
    msg += f"👋 ترحيب: {'✅' if settings['welcome_msg'] else '❌'}\n"
    msg += f"👋 وداع: {'✅' if settings['goodbye_msg'] else '❌'}"
    
    await update.message.reply_text(msg)

# ============================================================
# معالج الأحداث (الترحيب والوداع)
# ============================================================

async def on_member_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        return
    
    chat_id = chat.id
    settings = await db_fetch_one("SELECT welcome_msg FROM group_settings WHERE chat_id=?", chat_id)
    if not settings or not settings['welcome_msg']:
        return
    
    welcome_msg = settings['welcome_msg']
    
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        
        msg = welcome_msg.replace('{user}', member.full_name or member.first_name or 'عضو')
        msg = msg.replace('{chat}', chat.title or 'المجموعة')
        
        try:
            await update.message.reply_text(msg)
        except:
            pass

async def on_member_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.left_chat_member:
        return
    
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        return
    
    chat_id = chat.id
    member = update.message.left_chat_member
    
    if member.is_bot:
        return
    
    settings = await db_fetch_one("SELECT goodbye_msg FROM group_settings WHERE chat_id=?", chat_id)
    if not settings or not settings['goodbye_msg']:
        return
    
    goodbye_msg = settings['goodbye_msg']
    msg = goodbye_msg.replace('{user}', member.full_name or member.first_name or 'عضو')
    msg = msg.replace('{chat}', chat.title or 'المجموعة')
    
    try:
        await update.message.reply_text(msg)
    except:
        pass

# ============================================================
# التسجيل التلقائي عند إضافة البوت
# ============================================================

async def auto_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return
    
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        return
    
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            chat_id = chat.id
            user_id = update.effective_user.id
            
            existing = await db_fetch_one("SELECT 1 FROM owners WHERE chat_id=?", chat_id)
            if not existing:
                await db_execute("INSERT INTO owners VALUES (?, ?)", chat_id, user_id)
                
                try:
                    await context.bot.send_message(
                        user_id,
                        f"✅ تم تسجيلك كمالك مخفي\n📌 {chat.title}"
                    )
                except:
                    pass
                
                try:
                    await update.message.reply_text(
                        f"✅ تم تفعيل البوت\n👑 المالك: {update.effective_user.first_name}"
                    )
                except:
                    pass
            break

# ============================================================
# معالج الأزرار (CallbackQuery)
# ============================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data == "my_channels":
        channels = await db_get_channels(user_id)
        if not channels:
            await query.edit_message_text("📭 لا توجد قنوات")
            return
        
        text = "📡 **قنواتي:**\n\n"
        for ch in channels:
            text += f"• {ch[2]} ({ch[1]})\n"
        await query.edit_message_text(text)
    
    elif data == "add_channel":
        context.user_data['state'] = 'WAITING_CHANNEL_ID'
        await query.edit_message_text("📡 أرسل معرف القناة (مثال: @channel أو -100123456)")
    
    elif data == "add_posts":
        active = await db_get_active_channel(user_id)
        if not active:
            await query.edit_message_text("⚠️ لا توجد قناة نشطة")
            return
        
        unpublished = await db_get_unpublished_count(active)
        if unpublished >= MAX_UNPUBLISHED_POSTS:
            await query.edit_message_text(f"⚠️ تجاوزت الحد الأقصى ({MAX_UNPUBLISHED_POSTS})")
            return
        
        context.user_data['state'] = 'ADDING_POSTS'
        context.user_data[f"session_{user_id}"] = []
        context.user_data[f"session_target_{user_id}"] = min(15, MAX_UNPUBLISHED_POSTS - unpublished)
        
        await query.edit_message_text(
            f"📥 أرسل المنشورات (نصوص، صور، فيديوهات)\nالحد الأقصى: {MAX_UNPUBLISHED_POSTS - unpublished}"
        )
    
    elif data == "publish_one":
        active = await db_get_active_channel(user_id)
        if not active:
            await query.edit_message_text("⚠️ لا توجد قناة نشطة")
            return
        
        post = await db_get_next_post(active)
        if not post:
            await query.edit_message_text("📭 لا توجد منشورات")
            return
        
        channel = await db_get_channel_info(active)
        if not channel:
            await query.edit_message_text("❌ القناة غير موجودة")
            return
        
        try:
            if post['media_type'] == 'photo' and post['media_file_id']:
                await context.bot.send_photo(channel[0], post['media_file_id'], caption=post['text'])
            elif post['media_type'] == 'video' and post['media_file_id']:
                await context.bot.send_video(channel[0], post['media_file_id'], caption=post['text'])
            else:
                await context.bot.send_message(channel[0], post['text'])
            
            await db_mark_published(post['id'])
            await query.edit_message_text("✅ تم النشر بنجاح")
        except Exception as e:
            await query.edit_message_text(f"❌ فشل النشر: {str(e)[:100]}")
    
    elif data == "my_posts":
        active = await db_get_active_channel(user_id)
        if not active:
            await query.edit_message_text("⚠️ لا توجد قناة نشطة")
            return
        
        posts = await db_fetch(
            "SELECT id, text, media_type FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 15",
            (active,)
        )
        
        if not posts:
            await query.edit_message_text("📭 لا توجد منشورات")
            return
        
        text = "📋 **منشوراتي غير المنشورة:**\n\n"
        for p in posts:
            text += f"• {p[2]}: {p[1][:50]}...\n"
        await query.edit_message_text(text)
    
    elif data == "recycle":
        active = await db_get_active_channel(user_id)
        if active:
            await db_reset_posts_to_unpublished(active)
            await query.edit_message_text("♻️ تم إعادة تدوير جميع المنشورات")
        else:
            await query.edit_message_text("⚠️ لا توجد قناة نشطة")
    
    elif data == "my_stats":
        channels = await db_get_user_channels_count(user_id)
        total = await db_get_user_total_posts(user_id)
        unpublished = await db_get_user_unpublished_posts(user_id)
        
        await query.edit_message_text(
            f"📊 **إحصائياتي:**\n\n"
            f"📡 القنوات: {channels}\n"
            f"📝 إجمالي المنشورات: {total}\n"
            f"⏳ غير المنشورة: {unpublished}"
        )
    
    elif data == "my_groups":
        groups = await db_fetch("SELECT chat_id, chat_name FROM bot_groups WHERE added_by=?", user_id)
        if not groups:
            await query.edit_message_text("📭 لا توجد مجموعات")
            return
        
        text = "👥 **مجموعاتي:**\n\n"
        for g in groups:
            text += f"• {g[1]}\n"
        await query.edit_message_text(text)
    
    elif data == "settings":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 النشر التلقائي", callback_data="toggle_auto")],
            [InlineKeyboardButton("♻️ إعادة التدوير", callback_data="toggle_recycle")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ])
        await query.edit_message_text("⚙️ **الإعدادات:**", reply_markup=keyboard)
    
    elif data == "toggle_auto":
        row = await db_fetch_one("SELECT auto_publish FROM users WHERE user_id=?", user_id)
        current = row[0] if row else 1
        new = 0 if current == 1 else 1
        await db_execute("UPDATE users SET auto_publish=? WHERE user_id=?", new, user_id)
        await query.edit_message_text(f"✅ تم {'تفعيل' if new == 1 else 'تعطيل'} النشر التلقائي")
    
    elif data == "toggle_recycle":
        row = await db_fetch_one("SELECT auto_recycle FROM users WHERE user_id=?", user_id)
        current = row[0] if row else 1
        new = 0 if current == 1 else 1
        await db_execute("UPDATE users SET auto_recycle=? WHERE user_id=?", new, user_id)
        await query.edit_message_text(f"✅ تم {'تفعيل' if new == 1 else 'تعطيل'} إعادة التدوير")
    
    elif data == "language":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar")],
            [InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ])
        await query.edit_message_text("🌐 **اختر اللغة:**", reply_markup=keyboard)
    
    elif data.startswith("lang_"):
        lang = data.split("_")[1]
        await db_execute("INSERT OR REPLACE INTO user_translation (user_id, lang) VALUES (?, ?)", user_id, lang)
        await query.edit_message_text(f"✅ تم تغيير اللغة إلى {lang}")
    
    elif data == "help":
        await query.edit_message_text(
            "❓ **المساعدة:**\n\n"
            "/start - القائمة الرئيسية\n"
            "/help - هذه المساعدة\n\n"
            "📌 أوامر المجموعات:\n"
            "/claim - تسجيل مالك مخفي\n"
            "/addowner @user - إضافة مالك\n"
            "/addadmin @user - إضافة مشرف\n"
            "/remove @user - إزالة صلاحيات\n"
            "/list - عرض الصلاحيات\n"
            "/lock_links - حظر الروابط\n"
            "/unlock_links - إلغاء حظر الروابط\n"
            "/lock_mentions - حظر الإشارات\n"
            "/unlock_mentions - إلغاء حظر الإشارات\n"
            "/slowmode 5 - وضع بطيء\n"
            "/welcome رسالة - ترحيب\n"
            "/goodbye رسالة - وداع"
        )
    
    elif data == "back":
        await start_command(update, context)

# ============================================================
# معالج الرسائل النصية للخاص (إضافة قناة)
# ============================================================

async def private_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text or ""
    
    if context.user_data.get('state') == 'WAITING_CHANNEL_ID':
        channel_id = text.strip()
        if not channel_id.startswith('@') and not channel_id.startswith('-100'):
            await update.message.reply_text("❌ معرف قناة غير صالح")
            return
        
        new_id = await db_add_channel(user_id, channel_id, channel_id)
        if new_id:
            await db_set_active_channel(user_id, new_id)
            await update.message.reply_text(f"✅ تم إضافة القناة {channel_id}")
        else:
            await update.message.reply_text("⚠️ القناة موجودة مسبقاً")
        
        context.user_data.pop('state', None)
        await start_command(update, context)

# ============================================================
# الدالة الرئيسية
# ============================================================

async def main():
    print(f"🚀 تم تشغيل {BOT_NAME}")
    print("✅ نظام المجموعات المتكامل مفعل")
    print("✅ ريلاكس مانيجر مفعل")
    
    # تهيئة قاعدة البيانات
    await get_db()
    
    # إنشاء التطبيق
    app = Application.builder().token(TOKEN).build()
    
    # ===== معالجات الأوامر =====
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    
    # أوامر المجموعات
    app.add_handler(CommandHandler("claim", cmd_claim))
    app.add_handler(CommandHandler("addowner", cmd_addowner))
    app.add_handler(CommandHandler("addadmin", cmd_addadmin))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("lock_links", cmd_lock_links))
    app.add_handler(CommandHandler("unlock_links", cmd_unlock_links))
    app.add_handler(CommandHandler("lock_mentions", cmd_lock_mentions))
    app.add_handler(CommandHandler("unlock_mentions", cmd_unlock_mentions))
    app.add_handler(CommandHandler("slowmode", cmd_slowmode))
    app.add_handler(CommandHandler("welcome", cmd_welcome))
    app.add_handler(CommandHandler("goodbye", cmd_goodbye))
    app.add_handler(CommandHandler("add_banned", cmd_add_banned))
    app.add_handler(CommandHandler("remove_banned", cmd_remove_banned))
    app.add_handler(CommandHandler("list_banned", cmd_list_banned))
    app.add_handler(CommandHandler("add_reply", cmd_add_reply))
    app.add_handler(CommandHandler("remove_reply", cmd_remove_reply))
    app.add_handler(CommandHandler("list_replies", cmd_list_replies))
    app.add_handler(CommandHandler("log", cmd_log))
    app.add_handler(CommandHandler("settings", cmd_settings))
    
    # ===== معالجات الأحداث =====
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, auto_register))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_member_join))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_member_leave))
    
    # ===== معالجات الرسائل =====
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, private_text_handler))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.DOCUMENT | filters.AUDIO | filters.VOICE | filters.ANIMATION | filters.CAPTION) &
        ~filters.COMMAND,
        message_handler
    ))
    
    # ===== معالج الأزرار =====
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # ===== تعيين الأوامر =====
    await app.bot.set_my_commands([
        BotCommand("start", "القائمة الرئيسية"),
        BotCommand("help", "المساعدة"),
        BotCommand("claim", "تسجيل مالك مخفي"),
        BotCommand("addowner", "إضافة مالك مخفي"),
        BotCommand("addadmin", "إضافة مشرف مخفي"),
        BotCommand("remove", "إزالة صلاحيات"),
        BotCommand("list", "عرض الصلاحيات"),
        BotCommand("lock_links", "تفعيل حظر الروابط"),
        BotCommand("unlock_links", "إلغاء حظر الروابط"),
        BotCommand("lock_mentions", "تفعيل حظر الإشارات"),
        BotCommand("unlock_mentions", "إلغاء حظر الإشارات"),
        BotCommand("slowmode", "تفعيل الوضع البطيء"),
        BotCommand("welcome", "تعيين رسالة ترحيب"),
        BotCommand("goodbye", "تعيين رسالة وداع"),
        BotCommand("add_banned", "إضافة كلمة محظورة"),
        BotCommand("remove_banned", "حذف كلمة محظورة"),
        BotCommand("list_banned", "عرض الكلمات المحظورة"),
        BotCommand("add_reply", "إضافة رد تلقائي"),
        BotCommand("remove_reply", "حذف رد تلقائي"),
        BotCommand("list_replies", "عرض الردود التلقائية"),
        BotCommand("log", "عرض سجل الإجراءات"),
        BotCommand("settings", "عرض إعدادات المجموعة")
    ])
    
    # ===== تشغيل البوت =====
    try:
        await app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        print("🛑 تم إيقاف البوت")
    except Exception as e:
        print(f"❌ خطأ: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 تم إيقاف البوت")
    except Exception as e:
        print(f"❌ خطأ فادح: {e}")
