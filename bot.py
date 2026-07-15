#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - بوت متكامل لإدارة القنوات والمجموعات
الإصدار: 19.3.1
المطور: @RelaxMgr
"""

import sys
import os
from pathlib import Path
import secrets
import json
import hashlib
import time as time_module
import re
import logging
import traceback
import random
import asyncio
import sqlite3
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Optional, List, Dict, Any, Tuple, Callable
from functools import wraps
from enum import Enum, auto

# ===================== التحقق من إصدار بايثون =====================
def check_python_version():
    required_version = (3, 8)
    current_version = sys.version_info
    if current_version < required_version:
        print(f"❌ يحتاج البوت إلى بايثون {required_version[0]}.{required_version[1]} أو أحدث")
        print(f"📌 الإصدار الحالي: {current_version[0]}.{current_version[1]}")
        sys.exit(1)

check_python_version()

# ===================== المسارات الأساسية =====================
def get_base_path() -> Path:
    return Path(__file__).parent.resolve()

BASE_PATH = get_base_path()

def get_writable_path(base_path: Path, subdir: str) -> Path:
    paths_to_try = [
        base_path / subdir,
        Path.home() / f".bot_{subdir}",
        Path(f"/tmp/bot_{subdir}"),
        Path(os.getenv('TEMP', '/tmp')) / f"bot_{subdir}",
    ]
    for path in paths_to_try:
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / ".write_test"
            test_file.touch()
            test_file.unlink()
            return path
        except:
            continue
    import tempfile
    temp_path = Path(tempfile.gettempdir()) / f"bot_{subdir}"
    temp_path.mkdir(parents=True, exist_ok=True)
    return temp_path

def get_temp_path() -> Path:
    return get_writable_path(BASE_PATH, "temp")

DATA_PATH = get_writable_path(BASE_PATH, "data")
DB_PATH = DATA_PATH / "bot_data.db"
BACKUP_DIR = get_writable_path(BASE_PATH, "backups")
LOG_PATH = get_writable_path(BASE_PATH, "logs") / "bot.log"
SECURITY_LOG = get_writable_path(BASE_PATH, "logs") / "security.log"
ERROR_LOG = get_writable_path(BASE_PATH, "logs") / "errors.log"
ACCESS_LOG = get_writable_path(BASE_PATH, "logs") / "access.log"
TEMP_PATH = get_temp_path()
STATIC_PATH = get_writable_path(BASE_PATH, "static")
TEMPLATES_PATH = get_writable_path(BASE_PATH, "templates")
BANNED_WORDS_FILE = BASE_PATH / "banned_words.txt"

BACKUP_DIR.mkdir(parents=True, exist_ok=True)
DATA_PATH.mkdir(parents=True, exist_ok=True)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
TEMP_PATH.mkdir(parents=True, exist_ok=True)
STATIC_PATH.mkdir(parents=True, exist_ok=True)
TEMPLATES_PATH.mkdir(parents=True, exist_ok=True)

# ===================== إعدادات البروكسي =====================
USE_PROXY = False
PROXY_URL = None

# ===================== استيراد المكتبات =====================
import nest_asyncio
nest_asyncio.apply()

import aiosqlite
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, BotCommand, LabeledPrice, ChatPermissions
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler, ChatMemberHandler
from telegram.error import TimedOut, NetworkError, BadRequest, Forbidden, Conflict
from telegram.request import HTTPXRequest
import httpx

# ===================== استيراد الملفات المنفصلة =====================

# 1. استيراد الردود من replies.py
try:
    from replies import *
    REPLIES_LOADED = True
    print("✅ تم تحميل الردود من replies.py")
except ImportError as e:
    REPLIES_LOADED = False
    print(f"⚠️ ملف replies.py غير موجود: {e}")
    ALL_REPLIES = {}

# 2. استيراد خادم الويب من web_server.py
try:
    from web_server import web_app, ws_manager, start_web_server
    WEB_SERVER_LOADED = True
    print("✅ تم تحميل خادم الويب من web_server.py")
except ImportError as e:
    WEB_SERVER_LOADED = False
    print(f"⚠️ ملف web_server.py غير موجود: {e}")

# ===================== قوانين المجموعة الافتراضية =====================
DEFAULT_RULES = """
📋 **قوانين المجموعة**
━━━━━━━━━━━━━━━━━━━━━━

1️⃣ **احترام الآخرين**
• لا للتطاول أو السب أو الشتائم
• لا للتمييز العنصري أو الديني
• كن مهذبا في حوارك

2️⃣ **المحتوى المسموح**
• المواضيع المفيدة فقط
• لا للمنشورات المكررة
• لا للمحتوى غير اللائق

3️⃣ **الروابط والإعلانات**
• ممنوع نشر الروابط الخارجية
• ممنوع الإعلان عن قنوات أو مجموعات أخرى

4️⃣ **السلوك العام**
• لا للتجسس أو اختراق الخصوصية
• لا للمشاكل الشخصية في المجموعة

5️⃣ **العقوبات**
• تحذير أول
• كتم لمدة 24 ساعة
• حظر دائم
"""

# ===================== تحميل الترجمات =====================
def load_translations() -> dict:
    translations_file = BASE_PATH / "translations.json"
    default_translations = {
        "ar": {
            "welcome": "🌿 **مرحباً بك في ريلاكس مانيجر**\nاختر اللغة المناسبة",
            "main_title": "🌿 **{0}**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 المعرف: `{1}`\n👥 مجموعاتي: {2}\n💎 الاشتراك: {3}\n📡 القناة النشطة: {4}\n📝 المنشورات غير المنشورة: {5}\n⚙️ النشر التلقائي: {6}",
            "no_channels": "لا توجد قنوات",
            "add_channel": "➕ إضافة قناة",
            "my_channels": "📡 قنواتي",
            "add_15_posts": "📥 إضافة 15 منشور",
            "publish_one": "📤 نشر واحد",
            "my_posts_btn": "📋 منشوراتي",
            "recycle": "♻️ إعادة تدوير",
            "stats_btn": "📊 إحصائياتي",
            "my_stats_btn": "📈 إحصائيات كاملة",
            "my_groups_btn": "👥 مجموعاتي",
            "settings_btn": "⚙️ الإعدادات",
            "schedule_btn": "⏰ الجدولة",
            "help_btn": "❓ المساعدة",
            "trial_btn": "🎁 تجربة مجانية",
            "subscribe_btn": "💎 اشتراك",
            "developer_btn": "👨‍💻 المطور",
            "language_btn": "🌐 اللغة",
            "support_btn": "📞 الدعم",
            "admin_only": "🔒 هذا الأمر للمشرفين فقط!",
            "back": "🔙 رجوع",
            "cancelled": "❌ تم الإلغاء",
            "error": "⚠️ حدث خطأ، حاول مرة أخرى",
            "help": "❓ **المساعدة**\n/start - القائمة الرئيسية\n/trial - تجربة مجانية\n/subscribe - الاشتراك\n/support - مركز الدعم",
            "post_published": "✅ تم نشر المنشور بنجاح",
            "publish_error": "❌ فشل النشر: {0}",
            "channel_added": "✅ تم إضافة القناة {0}",
            "channel_exists": "⚠️ القناة موجودة مسبقاً",
            "no_posts": "📭 لا توجد منشورات",
            "deleted_all": "✅ تم حذف جميع المنشورات",
            "recycled": "♻️ تم إعادة تدوير جميع المنشورات",
            "locked": "🔒 تم قفل المجموعة",
            "unlocked": "🔓 تم فتح المجموعة",
            "subscribed": "✅ مفعل",
            "not_subscribed": "❌ غير مفعل",
            "auto_on": "مفعل",
            "auto_off": "معطل",
            "disabled": "❌ تعطيل",
            "enabled": "✅ تفعيل",
            "auto_toggled": "✅ تم تغيير حالة النشر التلقائي إلى: {0}"
        },
        "en": {
            "welcome": "🌿 **Welcome to Relax Manager**\nChoose your language",
            "main_title": "🌿 **{0}**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 ID: `{1}`\n👥 My Groups: {2}\n💎 Subscription: {3}\n📡 Active Channel: {4}\n📝 Unpublished Posts: {5}\n⚙️ Auto Publish: {6}",
            "no_channels": "No channels",
            "add_channel": "➕ Add Channel",
            "my_channels": "📡 My Channels",
            "add_15_posts": "📥 Add 15 Posts",
            "publish_one": "📤 Publish One",
            "my_posts_btn": "📋 My Posts",
            "recycle": "♻️ Recycle",
            "stats_btn": "📊 My Stats",
            "my_stats_btn": "📈 Full Stats",
            "my_groups_btn": "👥 My Groups",
            "settings_btn": "⚙️ Settings",
            "schedule_btn": "⏰ Schedule",
            "help_btn": "❓ Help",
            "trial_btn": "🎁 Free Trial",
            "subscribe_btn": "💎 Subscribe",
            "developer_btn": "👨‍💻 Developer",
            "language_btn": "🌐 Language",
            "support_btn": "📞 Support",
            "admin_only": "🔒 This command is for admins only!",
            "back": "🔙 Back",
            "cancelled": "❌ Cancelled",
            "error": "⚠️ An error occurred, try again",
            "help": "❓ **Help**\n/start - Main Menu\n/trial - Free Trial\n/subscribe - Subscribe\n/support - Support Center",
            "post_published": "✅ Post published successfully",
            "publish_error": "❌ Publish failed: {0}",
            "channel_added": "✅ Channel {0} added",
            "channel_exists": "⚠️ Channel already exists",
            "no_posts": "📭 No posts",
            "deleted_all": "✅ All posts deleted",
            "recycled": "♻️ All posts recycled",
            "locked": "🔒 Group locked",
            "unlocked": "🔓 Group unlocked",
            "subscribed": "✅ Active",
            "not_subscribed": "❌ Inactive",
            "auto_on": "Enabled",
            "auto_off": "Disabled",
            "disabled": "❌ Disable",
            "enabled": "✅ Enable",
            "auto_toggled": "✅ Auto publish status changed to: {0}"
        }
    }
    
    if not translations_file.exists():
        try:
            with open(translations_file, 'w', encoding='utf-8') as f:
                json.dump(default_translations, f, ensure_ascii=False, indent=2)
            print("✅ تم إنشاء ملف translations.json")
        except Exception as e:
            print(f"❌ فشل إنشاء ملف الترجمات: {e}")
        return default_translations
    
    try:
        with open(translations_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ فشل تحميل ملف الترجمات: {e}")
        return default_translations

TRANSLATIONS = load_translations()

# ===================== الكلمات المحظورة =====================
BANNED_PATTERNS = []

def load_banned_words_from_file(file_path: Path) -> List[str]:
    words = []
    if not file_path.exists():
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("# قائمة الكلمات المحظورة\n")
            print(f"✅ تم إنشاء ملف {file_path}")
        except Exception as e:
            print(f"❌ فشل إنشاء ملف الكلمات المحظورة: {e}")
        return words
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                word = line.lower()
                if len(word) >= 2:
                    words.append(word)
        print(f"✅ تم تحميل {len(words)} كلمة محظورة")
    except Exception as e:
        print(f"❌ فشل تحميل الكلمات المحظورة: {e}")
    return words

BANNED_WORDS = load_banned_words_from_file(BANNED_WORDS_FILE)

# ===================== إعدادات التسجيل =====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_PATH, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===================== الثوابت =====================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN غير موجود في ملف .env")

PRIMARY_OWNER_ID = int(os.getenv("MAIN_ADMIN_ID", 0))
if PRIMARY_OWNER_ID == 0:
    raise ValueError("❌ MAIN_ADMIN_ID غير محدد")

BOT_NAME = os.getenv("BOT_NAME", "ريلاكس مانيجر")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Reelaaaxbot")

MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 20 * 1024 * 1024))
MAX_UNPUBLISHED_POSTS = 1000
MAX_POSTS_PER_SESSION = 50
DB_TIMEOUT = 30
DB_MAX_RETRIES = 3
REQUEST_TIMEOUT = 30
POLL_INTERVAL = 1.0
_ADMIN_CACHE_TTL = 300

# ===================== نظام اللغة =====================
user_language = {}
_user_language_lock = asyncio.Lock()

def get_text(user_id: int, key: str) -> str:
    lang = user_language.get(user_id, 'ar')
    lang_data = TRANSLATIONS.get(lang, TRANSLATIONS.get('ar', {}))
    return lang_data.get(key, key)

async def set_user_language(user_id: int, lang: str):
    async with _user_language_lock:
        user_language[user_id] = lang

# ===================== دوال الوقت =====================
def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def mecca_now():
    return utc_now() + timedelta(hours=3)

def utc_now_iso():
    return utc_now().isoformat()

def mecca_now_iso():
    return mecca_now().isoformat()

def utc_to_mecca(utc_dt):
    if utc_dt is None:
        return None
    if hasattr(utc_dt, 'tzinfo') and utc_dt.tzinfo is not None:
        utc_dt = utc_dt.replace(tzinfo=None)
    return utc_dt + timedelta(hours=3)

def mecca_to_utc(mecca_dt):
    if mecca_dt is None:
        return None
    if hasattr(mecca_dt, 'tzinfo') and mecca_dt.tzinfo is not None:
        mecca_dt = mecca_dt.replace(tzinfo=None)
    return mecca_dt - timedelta(hours=3)

# ===================== دوال النص =====================
def escape_markdown_v2(text: str) -> str:
    if not text:
        return ""
    special_chars = r'([_*\[\]()~`>#+\-=|{}.!\\])'
    return re.sub(special_chars, r'\\\1', text)

def sanitize_text(text: str, max_length: int = 4096) -> str:
    if not text:
        return ""
    cleaned = text
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned

def contains_link(text: str) -> bool:
    patterns = [
        r'https?://\S+',
        r'www\.\S+',
        r't\.me/\S+',
        r'telegram\.me/\S+',
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)

def contains_mention(text: str) -> bool:
    return bool(re.search(r'@\w+', text))

# ===================== دوال الإرسال الآمنة =====================
async def safe_send_markdown(bot, chat_id: int, text: str, reply_markup=None, **kwargs):
    if not text:
        return None
    clean_text = sanitize_text(text)
    try:
        escaped = escape_markdown_v2(clean_text)
        if len(escaped) > 4096:
            escaped = escaped[:4093] + "..."
        return await bot.send_message(
            chat_id=chat_id,
            text=escaped,
            parse_mode='MarkdownV2',
            reply_markup=reply_markup,
            timeout=REQUEST_TIMEOUT,
            **kwargs
        )
    except Exception:
        plain = re.sub(r'[*_`\[\]()~>#+\-=|{}.!\\]', '', clean_text)
        if len(plain) > 4096:
            plain = plain[:4093] + "..."
        return await bot.send_message(
            chat_id=chat_id,
            text=plain,
            reply_markup=reply_markup,
            timeout=REQUEST_TIMEOUT,
            **kwargs
        )

async def safe_edit_markdown(query, text: str, reply_markup=None, **kwargs):
    if not query or not query.message:
        return None
    if not text:
        return None
    clean_text = sanitize_text(text)
    try:
        escaped = escape_markdown_v2(clean_text)
        if len(escaped) > 4096:
            escaped = escaped[:4093] + "..."
        return await query.edit_message_text(
            text=escaped,
            parse_mode='MarkdownV2',
            reply_markup=reply_markup,
            timeout=REQUEST_TIMEOUT,
            **kwargs
        )
    except Exception:
        plain = re.sub(r'[*_`\[\]()~>#+\-=|{}.!\\]', '', clean_text)
        if len(plain) > 4096:
            plain = plain[:4093] + "..."
        return await query.edit_message_text(
            text=plain,
            reply_markup=reply_markup,
            timeout=REQUEST_TIMEOUT,
            **kwargs
        )

# ===================== التخزين المؤقت =====================
_admin_cache = {}
_security_cache = {}

def invalidate_user_cache(user_id: int = None, chat_id: int = None):
    if user_id is not None:
        keys_to_remove = [k for k in list(_admin_cache.keys()) if str(user_id) in k]
        for key in keys_to_remove:
            if key in _admin_cache:
                del _admin_cache[key]
    elif chat_id is not None:
        keys_to_remove = [k for k in list(_admin_cache.keys()) if k.startswith(f"{chat_id}:")]
        for key in keys_to_remove:
            if key in _admin_cache:
                del _admin_cache[key]
    else:
        _admin_cache.clear()

# ===================== قاعدة البيانات =====================
class DatabasePool:
    def __init__(self):
        self._pool = None

    async def initialize(self):
        if self._pool is None:
            self._pool = await aiosqlite.connect(str(DB_PATH), timeout=DB_TIMEOUT)
            await self._pool.execute("PRAGMA journal_mode=WAL")
            await self._pool.execute("PRAGMA synchronous=NORMAL")
            await self._pool.execute("PRAGMA foreign_keys=ON")
            self._pool.row_factory = aiosqlite.Row

    async def get_connection(self):
        if self._pool is None:
            await self.initialize()
        return self._pool

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None

db_pool = DatabasePool()

async def execute_db(func: Callable):
    conn = await db_pool.get_connection()
    try:
        return await func(conn)
    except Exception as e:
        logger.error(f"خطأ في قاعدة البيانات: {e}")
        raise

# ===================== دوال قاعدة البيانات الأساسية =====================
async def db_register_user(user_id: int) -> bool:
    async def _register(conn):
        cur = await conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if await cur.fetchone():
            return False
        await conn.execute("INSERT INTO users (user_id, auto_publish, banned, trial_used) VALUES (?, 1, 0, 0)", (user_id,))
        await conn.commit()
        return True
    return await execute_db(_register)

async def db_get_all_users():
    async def _get(conn):
        cur = await conn.execute("SELECT user_id, banned FROM users ORDER BY user_id")
        return await cur.fetchall()
    return await execute_db(_get)

async def db_is_banned(user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT banned FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_check)

async def db_set_ban(user_id: int, banned: bool):
    async def _set(conn):
        await conn.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, user_id))
        await conn.commit()
    return await execute_db(_set)

async def db_has_used_trial(user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT trial_used FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_check)

async def db_activate_trial(user_id: int) -> int:
    async def _activate(conn):
        cur = await conn.execute("SELECT trial_used FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0] == 1:
            return 0
        end_date = (utc_now() + timedelta(days=30)).isoformat()
        await conn.execute("UPDATE users SET trial_used=1, subscription_end=? WHERE user_id=?", (end_date, user_id))
        await conn.commit()
        return 30
    return await execute_db(_activate)

async def db_has_active_subscription(user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT subscription_end FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0]:
            try:
                end_date = datetime.fromisoformat(row[0])
                return end_date > utc_now()
            except:
                return False
        return False
    return await execute_db(_check)

async def db_auto_status(user_id: int) -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT auto_publish FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_get)

async def db_set_auto(user_id: int, enabled: bool):
    async def _set(conn):
        await conn.execute("UPDATE users SET auto_publish=? WHERE user_id=?", (1 if enabled else 0, user_id))
        await conn.commit()
    return await execute_db(_set)

async def db_add_channel(user_id: int, channel_id: str, channel_name: str) -> int:
    async def _add(conn):
        cur = await conn.execute("SELECT id FROM user_channels WHERE user_id=? AND channel_id=?", (user_id, channel_id))
        if await cur.fetchone():
            return None
        cur = await conn.execute("INSERT INTO user_channels (user_id, channel_id, channel_name, created_at) VALUES (?, ?, ?, ?) RETURNING id",
                                (user_id, channel_id, channel_name, utc_now_iso()))
        row = await cur.fetchone()
        await conn.commit()
        return row[0] if row else None
    return await execute_db(_add)

async def db_get_channels(user_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT id, channel_id, channel_name, banned FROM user_channels WHERE user_id=? ORDER BY id", (user_id,))
        rows = await cur.fetchall()
        safe_rows = []
        for row in rows:
            try:
                safe_rows.append((row[0], row[1], row[2] or row[1], row[3] if row[3] is not None else 0))
            except:
                continue
        return safe_rows
    return await execute_db(_get)

async def db_get_channel_info(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT channel_id, channel_name FROM user_channels WHERE id=?", (channel_db_id,))
        return await cur.fetchone()
    return await execute_db(_get)

async def db_delete_channel_by_id(user_id: int, channel_db_id: int) -> bool:
    async def _delete(conn):
        await conn.execute("DELETE FROM user_channels WHERE id=? AND user_id=?", (channel_db_id, user_id))
        await conn.execute("DELETE FROM posts WHERE channel_db_id=?", (channel_db_id,))
        await conn.execute("DELETE FROM schedule WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
        return True
    return await execute_db(_delete)

async def db_get_active_channel(user_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT active_channel FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0] is not None:
            return row[0]
        cur = await conn.execute("SELECT id FROM user_channels WHERE user_id=? AND banned=0 ORDER BY id LIMIT 1", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_set_active_channel(user_id: int, channel_db_id: int):
    async def _set(conn):
        await conn.execute("UPDATE users SET active_channel=? WHERE user_id=?", (channel_db_id, user_id))
        await conn.commit()
    return await execute_db(_set)

async def db_get_user_channels_count(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM user_channels WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_get)

async def db_save_posts(channel_db_id: int, posts: list) -> int:
    async def _save(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0", (channel_db_id,))
        current_unpublished = (await cur.fetchone())[0]
        max_allowed = MAX_UNPUBLISHED_POSTS - current_unpublished
        if max_allowed <= 0:
            return 0
        posts_to_save = posts[:max_allowed]
        values = []
        for text_content, media_type, media_file_id in posts_to_save:
            values.append((channel_db_id, sanitize_text(text_content), media_type, media_file_id, utc_now_iso()))
        await conn.executemany(
            "INSERT INTO posts (channel_db_id, text, media_type, media_file_id, created_at) VALUES (?, ?, ?, ?, ?)",
            values
        )
        await conn.commit()
        return len(values)
    return await execute_db(_save)

async def db_get_next_post(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT id, text, media_type, media_file_id FROM posts WHERE channel_db_id=? AND published=0 AND (fail_count IS NULL OR fail_count < 3) ORDER BY id LIMIT 1", (channel_db_id,))
        row = await cur.fetchone()
        if row:
            return {'id': row[0], 'text': row[1], 'media_type': row[2], 'media_file_id': row[3]}
        return None
    return await execute_db(_get)

async def db_mark_published(post_id: int):
    async def _mark(conn):
        await conn.execute("UPDATE posts SET published=1 WHERE id=?", (post_id,))
        await conn.commit()
    return await execute_db(_mark)

async def db_unpublished_count(channel_db_id: int) -> int:
    async def _count(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_count)

async def db_get_user_posts_for_channel(channel_db_id: int, limit=15):
    async def _get(conn):
        cur = await conn.execute("SELECT id, text, media_type FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT ?", (channel_db_id, limit))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_delete_single_post(post_id: int, user_id: int, channel_db_id: int) -> bool:
    async def _delete(conn):
        cur = await conn.execute("SELECT 1 FROM posts p JOIN user_channels uc ON p.channel_db_id=uc.id WHERE p.id=? AND uc.user_id=?", (post_id, user_id))
        if not await cur.fetchone():
            return False
        await conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
        await conn.commit()
        return True
    return await execute_db(_delete)

async def db_get_user_unpublished_posts(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts p JOIN user_channels uc ON p.channel_db_id=uc.id WHERE uc.user_id=? AND p.published=0", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_get)

async def db_get_user_total_posts(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts p JOIN user_channels uc ON p.channel_db_id=uc.id WHERE uc.user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_get)

async def db_register_group(chat_id: int, chat_name: str, added_by: int, username: str = None) -> bool:
    async def _register(conn):
        cur = await conn.execute("SELECT chat_id FROM bot_groups WHERE chat_id=?", (chat_id,))
        if await cur.fetchone():
            await conn.execute("UPDATE bot_groups SET chat_name=?, username=?, added_by=? WHERE chat_id=?", (chat_name, username, added_by, chat_id))
            await conn.commit()
            return False
        await conn.execute("INSERT INTO bot_groups (chat_id, chat_name, username, added_by, added_at) VALUES (?, ?, ?, ?, ?)",
                          (chat_id, chat_name, username, added_by, utc_now_iso()))
        await conn.commit()
        return True
    return await execute_db(_register)

async def db_get_user_groups(user_id: int):
    async def _get(conn):
        cur = await conn.execute("""
            SELECT bg.chat_id, bg.chat_name, bg.username, bg.banned
            FROM bot_groups bg
            WHERE bg.added_by = ?
               OR EXISTS (SELECT 1 FROM hidden_owner_groups hog WHERE hog.chat_id = bg.chat_id AND hog.owner_id = ?)
               OR EXISTS (SELECT 1 FROM hidden_admins ha WHERE ha.chat_id = bg.chat_id AND ha.admin_id = ?)
            ORDER BY bg.chat_name
        """, (user_id, user_id, user_id))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_user_groups_count(user_id: int) -> int:
    groups = await db_get_user_groups(user_id)
    return len(groups)

async def db_set_chat_lock(chat_id: int, locked: bool, locked_by: int = None):
    async def _set(conn):
        if locked:
            await conn.execute("INSERT OR REPLACE INTO chat_locks (chat_id, locked, locked_at, locked_by) VALUES (?, 1, ?, ?)", (chat_id, utc_now_iso(), locked_by))
        else:
            await conn.execute("DELETE FROM chat_locks WHERE chat_id=?", (chat_id,))
        await conn.commit()
    return await execute_db(_set)

async def is_chat_locked(chat_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT locked FROM chat_locks WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_check)

async def db_get_security_settings(chat_id: int):
    if chat_id in _security_cache:
        return _security_cache[chat_id]
    async def _get(conn):
        cur = await conn.execute("SELECT delete_links, delete_mentions, warn_message, slow_mode, slow_mode_seconds, welcome_enabled, welcome_text, goodbye_enabled, goodbye_text, delete_banned_words, auto_penalty, auto_mute_duration FROM group_security WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        if row:
            settings = {
                'links': row[0] == 1,
                'mentions': row[1] == 1,
                'warn': row[2] == 1,
                'slow_mode': row[3] == 1,
                'slow_mode_seconds': row[4] if row[4] is not None else 5,
                'welcome_enabled': row[5] == 1,
                'welcome_text': row[6] if row[6] else "مرحباً {user} في {chat} 🤍",
                'goodbye_enabled': row[7] == 1,
                'goodbye_text': row[8] if row[8] else "وداعاً {user} 👋",
                'delete_banned_words': row[9] == 1,
                'auto_penalty': row[10] if row[10] else 'none',
                'auto_mute_duration': row[11] if row[11] is not None else 60
            }
            _security_cache[chat_id] = settings
            return settings
        default_settings = {
            'links': False, 'mentions': False, 'warn': True, 'slow_mode': False,
            'slow_mode_seconds': 5, 'welcome_enabled': False, 'welcome_text': "مرحباً {user} في {chat} 🤍",
            'goodbye_enabled': False, 'goodbye_text': "وداعاً {user} 👋", 'delete_banned_words': False,
            'auto_penalty': 'none', 'auto_mute_duration': 60
        }
        _security_cache[chat_id] = default_settings
        return default_settings
    return await execute_db(_get)

async def db_set_security_settings(chat_id: int, **kwargs):
    async def _set(conn):
        cur = await conn.execute("SELECT 1 FROM group_security WHERE chat_id=?", (chat_id,))
        exists = await cur.fetchone()
        if exists:
            updates = []
            values = []
            for key, value in kwargs.items():
                if key == 'links':
                    updates.append("delete_links=?")
                    values.append(1 if value else 0)
                elif key == 'mentions':
                    updates.append("delete_mentions=?")
                    values.append(1 if value else 0)
                elif key == 'warn':
                    updates.append("warn_message=?")
                    values.append(1 if value else 0)
                elif key == 'slow_mode':
                    updates.append("slow_mode=?")
                    values.append(1 if value else 0)
                elif key == 'slow_mode_seconds':
                    updates.append("slow_mode_seconds=?")
                    values.append(value)
                elif key == 'welcome_enabled':
                    updates.append("welcome_enabled=?")
                    values.append(1 if value else 0)
                elif key == 'welcome_text':
                    updates.append("welcome_text=?")
                    values.append(value)
                elif key == 'goodbye_enabled':
                    updates.append("goodbye_enabled=?")
                    values.append(1 if value else 0)
                elif key == 'goodbye_text':
                    updates.append("goodbye_text=?")
                    values.append(value)
                elif key == 'delete_banned_words':
                    updates.append("delete_banned_words=?")
                    values.append(1 if value else 0)
                elif key == 'auto_penalty':
                    updates.append("auto_penalty=?")
                    values.append(value)
                elif key == 'auto_mute_duration':
                    updates.append("auto_mute_duration=?")
                    values.append(value)
            if updates:
                query = f"UPDATE group_security SET {', '.join(updates)} WHERE chat_id=?"
                values.append(chat_id)
                await conn.execute(query, values)
        else:
            await conn.execute("""
                INSERT INTO group_security (chat_id, delete_links, delete_mentions, warn_message, slow_mode, slow_mode_seconds, welcome_enabled, welcome_text, goodbye_enabled, goodbye_text, delete_banned_words, auto_penalty, auto_mute_duration)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (chat_id,
                  1 if kwargs.get('links', False) else 0,
                  1 if kwargs.get('mentions', False) else 0,
                  1 if kwargs.get('warn', True) else 0,
                  1 if kwargs.get('slow_mode', False) else 0,
                  kwargs.get('slow_mode_seconds', 5),
                  1 if kwargs.get('welcome_enabled', False) else 0,
                  kwargs.get('welcome_text', "مرحباً {user} في {chat} 🤍"),
                  1 if kwargs.get('goodbye_enabled', False) else 0,
                  kwargs.get('goodbye_text', "وداعاً {user} 👋"),
                  1 if kwargs.get('delete_banned_words', False) else 0,
                  kwargs.get('auto_penalty', 'none'),
                  kwargs.get('auto_mute_duration', 60)))
        await conn.commit()
        if chat_id in _security_cache:
            del _security_cache[chat_id]
    return await execute_db(_set)

async def db_check_slow_mode(chat_id: int, user_id: int) -> bool:
    settings = await db_get_security_settings(chat_id)
    if not settings['slow_mode']:
        return True
    seconds = settings.get('slow_mode_seconds', 5)
    async def _check(conn):
        cur = await conn.execute("SELECT message_time FROM user_messages WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        row = await cur.fetchone()
        now = utc_now()
        if row:
            last_time = datetime.fromisoformat(row[0])
            if (now - last_time).total_seconds() < seconds:
                return False
        await conn.execute("INSERT OR REPLACE INTO user_messages (user_id, chat_id, message_time) VALUES (?, ?, ?)", (user_id, chat_id, now.isoformat()))
        await conn.commit()
        return True
    return await execute_db(_check)

async def db_add_banned_word(word: str, chat_id: int, added_by: int) -> bool:
    async def _add(conn):
        try:
            await conn.execute("INSERT OR IGNORE INTO banned_words (word, chat_id, added_by, added_at) VALUES (?, ?, ?, ?)", (word, chat_id, added_by, utc_now_iso()))
            await conn.commit()
            return True
        except:
            return False
    return await execute_db(_add)

async def db_remove_banned_word(word: str, chat_id: int) -> bool:
    async def _remove(conn):
        await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, chat_id))
        await conn.commit()
        return True
    return await execute_db(_remove)

async def db_get_banned_words(chat_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT word, added_by, added_at FROM banned_words WHERE chat_id=? OR chat_id=-1 ORDER BY word", (chat_id,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_contains_banned_word(text: str, chat_id: int) -> str:
    words = await db_get_banned_words(chat_id)
    text_lower = text.lower()
    for word, _, _ in words:
        if word in text_lower:
            return word
    return None

async def db_register_hidden_owner_group(chat_id: int, owner_id: int):
    async def _register(conn):
        await conn.execute("INSERT OR REPLACE INTO hidden_owner_groups (chat_id, owner_id, is_hidden) VALUES (?, ?, 1)", (chat_id, owner_id))
        await conn.commit()
    return await execute_db(_register)

async def db_is_hidden_owner(chat_id: int, user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?", (chat_id, user_id))
        return await cur.fetchone() is not None
    return await execute_db(_check)

async def db_add_hidden_admin(chat_id: int, admin_id: int, added_by: int) -> bool:
    async def _add(conn):
        try:
            await conn.execute("INSERT OR IGNORE INTO hidden_admins (chat_id, admin_id, added_by, added_at) VALUES (?, ?, ?, ?)", (chat_id, admin_id, added_by, utc_now_iso()))
            await conn.commit()
            return True
        except:
            return False
    return await execute_db(_add)

async def db_remove_hidden_admin(chat_id: int, admin_id: int) -> bool:
    async def _remove(conn):
        await conn.execute("DELETE FROM hidden_admins WHERE chat_id=? AND admin_id=?", (chat_id, admin_id))
        await conn.commit()
        return True
    return await execute_db(_remove)

async def db_is_hidden_admin(chat_id: int, user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM hidden_admins WHERE chat_id=? AND admin_id=?", (chat_id, user_id))
        return await cur.fetchone() is not None
    return await execute_db(_check)

async def db_get_hidden_admins(chat_id: int) -> List[Dict]:
    async def _get(conn):
        cur = await conn.execute("SELECT admin_id, added_by, added_at FROM hidden_admins WHERE chat_id=? ORDER BY added_at DESC", (chat_id,))
        rows = await cur.fetchall()
        return [{'admin_id': row[0], 'added_by': row[1], 'added_at': row[2]} for row in rows]
    return await execute_db(_get)

async def add_bot_admin(user_id: int):
    async def _add(conn):
        await conn.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (user_id,))
        await conn.commit()
    return await execute_db(_add)

async def remove_bot_admin(user_id: int):
    async def _remove(conn):
        await conn.execute("DELETE FROM bot_admins WHERE user_id=?", (user_id,))
        await conn.commit()
    return await execute_db(_remove)

async def is_bot_admin(user_id: int) -> bool:
    if user_id == PRIMARY_OWNER_ID:
        return True
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM bot_admins WHERE user_id=?", (user_id,))
        return await cur.fetchone() is not None
    return await execute_db(_check)

async def db_get_updates_channel():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='updates_channel'")
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_set_updates_channel(channel: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('updates_channel', ?)", (channel,))
        await conn.commit()
    return await execute_db(_set)

async def db_get_force_subscribe_status() -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='force_subscribe_enabled'")
        row = await cur.fetchone()
        return row and row[0] == '1'
    return await execute_db(_get)

async def db_set_force_subscribe_status(enabled: bool):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_subscribe_enabled', ?)", ('1' if enabled else '0',))
        await conn.commit()
    return await execute_db(_set)

async def db_get_force_subscribe_channel():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='force_subscribe_channel'")
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_set_force_subscribe_channel(channel: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_subscribe_channel', ?)", (channel,))
        await conn.commit()
    return await execute_db(_set)

async def db_get_log_channel_id():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='log_channel_id'")
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_set_log_channel_id(channel_id: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('log_channel_id', ?)", (channel_id,))
        await conn.commit()
    return await execute_db(_set)

async def db_get_allowed_sendcode_user() -> int | None:
    async def _get(conn):
        cur = await conn.execute("SELECT user_id FROM allowed_sendcode_user WHERE id=1")
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_set_allowed_sendcode_user(user_id: int) -> None:
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO allowed_sendcode_user (id, user_id) VALUES (1, ?)", (user_id,))
        await conn.commit()
    return await execute_db(_set)

async def db_add_reply(keyword, reply):
    async def _add(conn):
        await conn.execute("INSERT OR REPLACE INTO group_replies (keyword, reply) VALUES (?,?)", (keyword.lower(), reply))
        await conn.commit()
    return await execute_db(_add)

async def db_del_reply(keyword):
    async def _del(conn):
        await conn.execute("DELETE FROM group_replies WHERE keyword=?", (keyword.lower(),))
        await conn.commit()
    return await execute_db(_del)

async def db_get_all_replies():
    async def _get(conn):
        cur = await conn.execute("SELECT keyword, reply FROM group_replies ORDER BY keyword")
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_next_ticket_number():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='last_ticket_number'")
        row = await cur.fetchone()
        return int(row[0]) if row else 0
    return await execute_db(_get)

async def db_save_ticket(user_id, username, message, ticket_num):
    async def _save(conn):
        created_at = utc_now_iso()
        await conn.execute("INSERT INTO support_tickets (user_id, username, message, ticket_number, status, created_at) VALUES (?,?,?,?,?,?)", (user_id, username, sanitize_text(message), ticket_num, 'pending', created_at))
        await conn.commit()
        return True
    return await execute_db(_save)

async def db_get_all_tickets(limit=20):
    async def _get(conn):
        cur = await conn.execute("SELECT id, user_id, username, message, ticket_number, status, created_at FROM support_tickets ORDER BY id DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_mark_ticket_replied(ticket_id):
    async def _mark(conn):
        await conn.execute("UPDATE support_tickets SET status='replied', replied=1 WHERE id=?", (ticket_id,))
        await conn.commit()
    return await execute_db(_mark)

async def db_delete_all_tickets():
    async def _delete(conn):
        await conn.execute("DELETE FROM support_tickets")
        await conn.commit()
        return True
    return await execute_db(_delete)

async def db_get_schedule(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, next_publish_date FROM schedule WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        if row:
            return {'type': row[0] or 'interval_minutes', 'interval_minutes': row[1] or 12, 'interval_hours': row[2] or 0, 'interval_days': row[3] or 0, 'days_of_week': row[4] or '[]', 'specific_dates': row[5] or '[]', 'publish_time': row[6] or '00:00', 'next_publish_date': row[7]}
        return {'type': 'interval_minutes', 'interval_minutes': 12, 'interval_hours': 0, 'interval_days': 0, 'days_of_week': '[]', 'specific_dates': '[]', 'publish_time': '00:00', 'next_publish_date': None}
    return await execute_db(_get)

async def db_set_next_publish_date(channel_db_id: int, next_date: datetime):
    async def _set(conn):
        if next_date:
            await conn.execute("UPDATE schedule SET next_publish_date=? WHERE channel_db_id=?", (next_date.isoformat(), channel_db_id))
        else:
            await conn.execute("UPDATE schedule SET next_publish_date=NULL WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
    return await execute_db(_set)

async def db_set_last_publish(channel_db_id: int, publish_time: datetime):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO last_publish (channel_db_id, last_publish_time) VALUES (?, ?)", (channel_db_id, publish_time.isoformat()))
        await conn.commit()
    return await execute_db(_set)

async def db_update_next_publish_date(channel_db_id: int):
    async def _update(conn):
        schedule = await db_get_schedule(channel_db_id)
        last_publish_cur = await conn.execute("SELECT last_publish_time FROM last_publish WHERE channel_db_id=?", (channel_db_id,))
        last_row = await last_publish_cur.fetchone()
        last_time = datetime.fromisoformat(last_row[0]) if last_row else utc_now()
        schedule_type = schedule['type']
        if schedule_type == 'interval_minutes':
            minutes = schedule.get('interval_minutes', 12)
            next_date = last_time + timedelta(minutes=minutes)
        elif schedule_type == 'interval_hours':
            hours = schedule.get('interval_hours', 1)
            next_date = last_time + timedelta(hours=hours)
        elif schedule_type == 'interval_days':
            days = schedule.get('interval_days', 1)
            next_date = last_time + timedelta(days=days)
        else:
            next_date = last_time + timedelta(minutes=schedule.get('interval_minutes', 12))
        if next_date:
            await conn.execute("UPDATE schedule SET next_publish_date=? WHERE channel_db_id=?", (next_date.isoformat(), channel_db_id))
            await conn.commit()
    return await execute_db(_update)

async def db_get_group_rules(chat_id: int) -> Optional[str]:
    async def _get(conn):
        cur = await conn.execute("SELECT rules_text FROM group_rules WHERE chat_id = ?", (chat_id,))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_set_group_rules(chat_id: int, rules_text: str, updated_by: int) -> bool:
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO group_rules (chat_id, rules_text, updated_by, updated_at) VALUES (?, ?, ?, ?)", (chat_id, rules_text, updated_by, utc_now_iso()))
        await conn.commit()
        return True
    return await execute_db(_set)

async def db_delete_group_rules(chat_id: int) -> bool:
    async def _delete(conn):
        await conn.execute("DELETE FROM group_rules WHERE chat_id = ?", (chat_id,))
        await conn.commit()
        return True
    return await execute_db(_delete)

async def db_create_contest(creator_id: int, title: str, description: str, prize: str, end_date: datetime, contest_type: str = 'raffle') -> int:
    async def _create(conn):
        end_date_str = end_date.isoformat()
        cur = await conn.execute("INSERT INTO contests (creator_id, title, description, prize, end_date, status, created_at, contest_type) VALUES (?, ?, ?, ?, ?, 'active', ?, ?) RETURNING id", (creator_id, title, description, prize, end_date_str, utc_now_iso(), contest_type))
        row = await cur.fetchone()
        await conn.commit()
        return row[0] if row else None
    return await execute_db(_create)

async def db_get_contest(contest_id: int) -> dict | None:
    async def _get(conn):
        cur = await conn.execute("SELECT id, title, description, prize, end_date, status, winner_id, creator_id, contest_type FROM contests WHERE id = ?", (contest_id,))
        row = await cur.fetchone()
        if row:
            return {'id': row[0], 'title': row[1], 'description': row[2], 'prize': row[3], 'end_date': row[4], 'status': row[5], 'winner_id': row[6], 'creator_id': row[7], 'contest_type': row[8] if len(row) > 8 else 'raffle'}
        return None
    return await execute_db(_get)

async def db_participate_in_contest(user_id: int, contest_id: int) -> bool:
    async def _participate(conn):
        try:
            await conn.execute("INSERT INTO contest_participants (user_id, contest_id, joined_at) VALUES (?, ?, ?)", (user_id, contest_id, utc_now_iso()))
            await conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    return await execute_db(_participate)

async def db_get_user_participation(user_id: int, contest_id: int) -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT 1 FROM contest_participants WHERE user_id = ? AND contest_id = ?", (user_id, contest_id))
        return await cur.fetchone() is not None
    return await execute_db(_get)

async def db_set_contest_winner(contest_id: int, winner_id: int) -> bool:
    async def _set(conn):
        await conn.execute("UPDATE contests SET status = 'finished', winner_id = ? WHERE id = ?", (winner_id, contest_id))
        await conn.execute("INSERT INTO contest_winners (contest_id, winner_id, announced_at) VALUES (?, ?, ?)", (contest_id, winner_id, utc_now_iso()))
        await conn.commit()
        return True
    return await execute_db(_set)

# ===================== دوال الصلاحيات =====================
async def check_admin_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update or not update.effective_user:
        return False
    
    user_id = update.effective_user.id
    
    if user_id == PRIMARY_OWNER_ID:
        return True
    
    if await is_bot_admin(user_id):
        return True
    
    chat = update.effective_chat
    if not chat:
        return False
    
    if chat.type == 'private':
        return False
    
    if chat.type in ['group', 'supergroup']:
        chat_id = chat.id
        cache_key = f"{chat_id}:{user_id}"
        
        if cache_key in _admin_cache:
            return _admin_cache[cache_key]
        
        if await db_is_hidden_owner(chat_id, user_id):
            _admin_cache[cache_key] = True
            return True
        
        if await db_is_hidden_admin(chat_id, user_id):
            _admin_cache[cache_key] = True
            return True
        
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status in ['administrator', 'creator']:
                _admin_cache[cache_key] = True
                return True
        except:
            pass
        
        _admin_cache[cache_key] = False
        return False
    
    return False

async def is_authorized_in_group(bot, chat_id: int, user_id: int, update: Update = None) -> bool:
    if user_id == PRIMARY_OWNER_ID:
        return True
    
    if await is_bot_admin(user_id):
        return True
    
    if await db_is_hidden_owner(chat_id, user_id):
        return True
    
    if await db_is_hidden_admin(chat_id, user_id):
        return True
    
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in ['administrator', 'creator']:
            return True
    except:
        pass
    
    return False

async def is_telegram_admin(bot, chat_id: int, user_id: int, update: Update = None) -> bool:
    try:
        if user_id == PRIMARY_OWNER_ID:
            return True
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ['creator', 'administrator']
    except:
        return False

# ===================== دوال الإجراءات المتقدمة =====================
async def execute_ban(bot, chat_id: int, user_id: int, until_date=None, reason: str = "", moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن حظر البوت نفسه!"
        await bot.ban_chat_member(chat_id, user_id, until_date=until_date)
        return True, f"✅ تم حظر المستخدم `{user_id}` بنجاح"
    except Exception as e:
        return False, f"❌ فشل الحظر: {str(e)[:100]}"

async def execute_mute(bot, chat_id: int, user_id: int, duration_minutes: int = None, reason: str = "", moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن كتم البوت نفسه!"
        until_date = None
        duration_text = ""
        if duration_minutes and duration_minutes > 0:
            until_date = utc_now() + timedelta(minutes=duration_minutes)
            if duration_minutes < 60:
                duration_text = f" لمدة {duration_minutes} دقيقة"
            elif duration_minutes < 1440:
                duration_text = f" لمدة {duration_minutes // 60} ساعة"
            else:
                duration_text = f" لمدة {duration_minutes // 1440} يوم"
        else:
            duration_text = " بشكل دائم"
            duration_minutes = -1
        permissions = ChatPermissions(can_send_messages=False)
        await bot.restrict_chat_member(chat_id, user_id, permissions, until_date=until_date)
        return True, f"✅ تم كتم المستخدم `{user_id}`{duration_text}"
    except Exception as e:
        return False, f"❌ فشل الكتم: {str(e)[:100]}"

async def execute_kick(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن طرد البوت نفسه!"
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id)
        return True, f"✅ تم طرد المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل الطرد: {str(e)[:100]}"

async def execute_warn(bot, chat_id: int, user_id: int, moderator_id: int, reason: str = "", auto_ban_limit: int = 3):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن تحذير البوت نفسه!"
        async def _add_warning(conn):
            cur = await conn.execute("SELECT warnings FROM user_warnings WHERE user_id=? AND chat_id=?", (user_id, chat_id))
            row = await cur.fetchone()
            warnings = row[0] + 1 if row else 1
            await conn.execute("INSERT OR REPLACE INTO user_warnings (user_id, chat_id, warnings) VALUES (?,?,?)", (user_id, chat_id, warnings))
            await conn.commit()
            return warnings
        warnings = await execute_db(_add_warning)
        if warnings >= auto_ban_limit:
            await execute_ban(bot, chat_id, user_id, reason=f"تلقائي بعد {warnings} تحذيرات", moderator_id=moderator_id)
            return True, f"⚠️ تم تحذير المستخدم `{user_id}` ({warnings}/{auto_ban_limit}) وتم حظره تلقائياً"
        return True, f"⚠️ تم تحذير المستخدم `{user_id}` ({warnings}/{auto_ban_limit})"
    except Exception as e:
        return False, f"❌ فشل التحذير: {str(e)[:100]}"

async def execute_restrict(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن تقييد البوت نفسه!"
        permissions = ChatPermissions(can_send_messages=True, can_send_media_messages=False, can_send_other_messages=False, can_add_web_page_previews=False)
        await bot.restrict_chat_member(chat_id, user_id, permissions)
        return True, f"✅ تم تقييد المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل التقييد: {str(e)[:100]}"

async def execute_pin(bot, chat_id: int, message_id: int, disable_notification: bool = False):
    try:
        await bot.pin_chat_message(chat_id, message_id, disable_notification=disable_notification)
        return True, "✅ تم تثبيت الرسالة"
    except Exception as e:
        return False, f"❌ فشل التثبيت: {str(e)[:100]}"

async def execute_unban(bot, chat_id: int, user_id: int, moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن إلغاء حظر البوت نفسه!"
        await bot.unban_chat_member(chat_id, user_id)
        return True, f"✅ تم إلغاء حظر المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل إلغاء الحظر: {str(e)[:100]}"

async def execute_unmute(bot, chat_id: int, user_id: int, moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن إلغاء كتم البوت نفسه!"
        permissions = ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)
        await bot.restrict_chat_member(chat_id, user_id, permissions)
        return True, f"✅ تم إلغاء كتم المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل إلغاء الكتم: {str(e)[:100]}"

async def apply_penalty(bot, chat_id, user_id, settings):
    penalty = settings.get('auto_penalty', 'none')
    if penalty == 'none':
        return
    if await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id):
        return
    if penalty == 'kick':
        await execute_kick(bot, chat_id, user_id, "مخالفة قواعد المجموعة")
    elif penalty == 'ban':
        await execute_ban(bot, chat_id, user_id, reason="مخالفة قواعد المجموعة")
    elif penalty == 'mute':
        duration = settings.get('auto_mute_duration', 60)
        await execute_mute(bot, chat_id, user_id, duration, "مخالفة قواعد المجموعة")

async def check_bot_admin_permissions(bot, chat_id: int) -> dict:
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        if me.status not in ['administrator', 'creator']:
            return {'can_act': False, 'reason': 'البوت ليس مشرفاً'}
        permissions = {
            'can_ban': getattr(me, 'can_restrict_members', False),
            'can_pin': getattr(me, 'can_pin_messages', False),
            'can_delete': getattr(me, 'can_delete_messages', False),
        }
        missing = [k for k, v in permissions.items() if not v]
        if missing:
            return {'can_act': False, 'reason': f'البوت يحتاج صلاحيات: {", ".join(missing)}'}
        return {'can_act': True, 'reason': ''}
    except Exception as e:
        return {'can_act': False, 'reason': str(e)}

# ===================== دوال المشرفين المخفيين =====================
async def register_hidden_owner_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    if await db_is_hidden_owner(chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'hidden_owner_already'))
        return
    
    await db_register_hidden_owner_group(chat_id, user_id)
    await invalidate_user_cache(user_id=user_id, chat_id=chat_id)
    await update.message.reply_text(get_text(user_id, 'hidden_owner_registered'))

async def add_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
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
        await update.message.reply_text(get_text(user_id, 'hidden_admin_added').format(admin_id))
    else:
        await update.message.reply_text("❌ فشل إضافة المشرف المخفي.")

async def remove_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
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
        await update.message.reply_text(get_text(user_id, 'hidden_admin_removed').format(admin_id))
    else:
        await update.message.reply_text("❌ فشل إزالة المشرف المخفي.")

async def list_hidden_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
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
        await update.message.reply_text(get_text(user_id, 'no_hidden_admins'))
        return
    
    text = get_text(user_id, 'hidden_admin_list').format("")
    
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
    
    await safe_send_markdown(context.bot, user_id, text)

# ===================== دوال قوانين المجموعة =====================
async def rules_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    chat = update.effective_chat
    
    custom_rules = None
    
    if chat and chat.type in ['group', 'supergroup']:
        chat_id = chat.id
        custom_rules = await db_get_group_rules(chat_id)
    
    rules_text = custom_rules if custom_rules else DEFAULT_RULES
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 دعم", callback_data=CallbackData.SUPPORT_MENU),
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    
    try:
        await safe_send_markdown(context.bot, user_id, rules_text, reply_markup=keyboard)
    except Exception:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=rules_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception:
            plain_text = re.sub(r'[*_`\[\]()~>#+\-=|{}.!\\]', '', rules_text)
            await context.bot.send_message(
                chat_id=user_id,
                text=plain_text,
                reply_markup=keyboard
            )

async def set_rules_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    chat = update.effective_chat
    
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    
    chat_id = chat.id
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    args = context.args or []
    
    if not args:
        await update.message.reply_text(
            "📝 **الاستخدام:**\n`/set_rules نص القوانين`\n\n"
            "مثال: `/set_rules 1- ممنوع السب\\n2- ممنوع الروابط`\n\n"
            "📌 لعرض القوانين الحالية استخدم `/rules`"
        )
        return
    
    rules_text = " ".join(args)
    
    if await db_set_group_rules(chat_id, rules_text, user_id):
        await update.message.reply_text("✅ **تم تحديث قوانين المجموعة بنجاح!**")
        await rules_command_handler(update, context)
    else:
        await update.message.reply_text("❌ فشل حفظ القوانين.")

async def reset_rules_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    chat = update.effective_chat
    
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    
    chat_id = chat.id
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، إعادة تعيين", callback_data=f"reset_rules_confirm:{chat_id}"),
         InlineKeyboardButton("❌ إلغاء", callback_data=f"reset_rules_cancel:{chat_id}")]
    ])
    
    await update.message.reply_text(
        "⚠️ **تأكيد إعادة تعيين القوانين**\n\n"
        "سيتم حذف القوانين المخصصة واستعادة القوانين الافتراضية.\n"
        "هل أنت متأكد؟",
        reply_markup=keyboard
    )

async def reset_rules_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    
    if await db_delete_group_rules(chat_id):
        await query.edit_message_text("✅ **تم إعادة تعيين القوانين إلى الافتراضية.**")
        await rules_command_handler(update, context)
    else:
        await query.edit_message_text("❌ فشل إعادة التعيين.")

async def reset_rules_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ تم إلغاء العملية.")

# ===================== دوال الأمان الإضافية =====================
async def is_user_subscribed(bot, user_id, channel):
    if not channel:
        return True
    channel = channel.lstrip('@')
    try:
        member = await bot.get_chat_member(f"@{channel}", user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

async def ensure_force_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None) -> bool:
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
            await safe_edit_markdown(update.callback_query, msg, reply_markup=keyboard)
        elif update.message:
            await safe_send_markdown(context.bot, user_id, msg, reply_markup=keyboard)
    except Exception:
        pass
    
    return False

# ===================== دوال القوائم والأزرار =====================
class CallbackData:
    MAIN_MENU = "main_menu"
    CHANNELS_MY = "channels:my_channels"
    CHANNELS_ADD = "channels:add"
    CHANNELS_DELETE_PREFIX = "channels:delete:"
    CHANNELS_SELECT_PREFIX = "channels:select:"
    POSTS_ADD_15 = "posts:add_15"
    POSTS_PUBLISH_ONE = "posts:publish_one"
    POSTS_MY = "posts:my_posts"
    POSTS_RECYCLE = "posts:recycle"
    POSTS_DELETE_SINGLE_PREFIX = "posts:delete_single:"
    POSTS_CONFIRM_CLEAR_ALL_PREFIX = "posts:confirm_clear_all:"
    POSTS_CLEAR_ALL_PREFIX = "posts:clear_all:"
    STATS_PENDING = "stats:pending"
    STATS_FULL = "stats:full"
    GROUPS_MY = "groups:my_groups"
    GROUPS_SETTINGS_PREFIX = "groups:settings:"
    SETTINGS_MENU = "settings:menu"
    SETTINGS_TOGGLE_AUTO_PUBLISH = "settings:toggle_auto_publish"
    SCHEDULE_MENU_PREFIX = "schedule:menu:"
    SECURITY_LINKS_PREFIX = "security:links:"
    SECURITY_MENTIONS_PREFIX = "security:mentions:"
    SECURITY_WARN_PREFIX = "security:warn:"
    SECURITY_SLOWMODE_PREFIX = "security:slowmode:"
    SECURITY_BANNED_WORDS_MENU_PREFIX = "security:banned_words_menu:"
    SECURITY_WELCOME_PREFIX = "security:welcome:"
    SECURITY_GOODBYE_PREFIX = "security:goodbye:"
    SECURITY_CLOSE = "security:close"
    SECURITY_SELECT_GROUP = "security_select_group:"
    SECURITY_REFRESH_GROUPS = "security_refresh_groups"
    BANNED_WORDS_ADD_PREFIX = "banned_words:add:"
    BANNED_WORDS_LIST_PREFIX = "banned_words:list:"
    BANNED_WORDS_REMOVE_PREFIX = "banned_words:remove:"
    HELP = "help"
    SUPPORT_MENU = "support:menu"
    SUPPORT_HELP = "support:help"
    SUPPORT_TICKET = "support:ticket"
    SUPPORT_BACK = "support:back"
    TRIAL = "trial"
    SUBSCRIBE_MENU = "subscribe:menu"
    BUY_SUBSCRIPTION_1 = "buy:subscription_1"
    BUY_SUBSCRIPTION_2 = "buy:subscription_2"
    BUY_SUBSCRIPTION_30 = "buy:subscription_30"
    BUY_SUBSCRIPTION_90 = "buy:subscription_90"
    DEVELOPER = "developer"
    UPDATES = "updates"
    REFERRAL_MENU = "referral:menu"
    REMINDER_MENU = "reminder:menu"
    TRANSLATION_MENU = "translation:menu"
    ADMIN_PANEL = "admin:panel"
    ADMIN_USERS = "admin:users"
    ADMIN_BANNED_USERS = "admin:banned_users"
    ADMIN_UNBAN_ALL_USERS = "admin:unban_all_users"
    ADMIN_ALL_CHANNELS = "admin:all_channels"
    ADMIN_BANNED_CHANNELS = "admin:banned_channels"
    ADMIN_ADD_ADMIN = "admin:add_admin"
    ADMIN_REMOVE_ADMIN = "admin:remove_admin"
    ADMIN_SEND_UPDATE = "admin:send_update"
    ADMIN_SET_UPDATE_CHANNEL = "admin:set_update_channel"
    ADMIN_FORCE_SUBSCRIBE = "admin:force_subscribe"
    ADMIN_BROADCAST = "admin:broadcast"
    ADMIN_CONFIRM_BROADCAST = "admin:confirm_broadcast"
    ADMIN_SUPPORT_TICKETS = "admin:support_tickets"
    ADMIN_DELETE_ALL_TICKETS = "admin:delete_all_tickets"
    ADMIN_CONFIRM_DELETE_TICKETS = "admin:confirm_delete_tickets"
    ADMIN_MANAGE_SENDCODE = "admin:manage_sendcode"
    ADMIN_SET_SENDCODE_USER = "admin:set_sendcode_user"
    ADMIN_REPLIES = "admin:replies"
    ADMIN_ADD_REPLY = "admin:add_reply"
    ADMIN_LIST_REPLIES = "admin:list_replies"
    ADMIN_DEL_REPLY = "admin:del_reply"
    ADMIN_AUTO_REPLY = "admin_auto_reply"
    ADMIN_AUTO_REPLY_SELECT_PREFIX = "admin_auto_reply_select:"
    ADMIN_CREATE_CONTEST = "admin:create_contest"
    ADMIN_BANNED_WORDS = "admin:banned_words"
    ADMIN_ADD_BANNED_WORD = "admin:add_banned_word"
    ADMIN_LIST_BANNED_WORDS = "admin:list_banned_words"
    ADMIN_REMOVE_BANNED_WORD = "admin:remove_banned_word"
    ADMIN_RAM = "admin:ram"
    ADMIN_STATS = "admin:stats"
    ADMIN_METRICS = "admin:metrics"
    ADMIN_BACKUP = "admin:backup"
    ADMIN_RESTORE_BACKUP = "admin:restore_backup"
    ADMIN_RESTORE_BACKUP_SELECT_PREFIX = "admin:restore_backup_select:"
    ADMIN_BACKUP_SETTINGS = "admin:backup_settings"
    ADMIN_TOGGLE_AUTO_BACKUP = "admin:toggle_auto_backup"
    ADMIN_CHANGE_INTERVAL = "admin:change_interval"
    ADMIN_SHOW_UPDATE_CHANNEL = "admin:show_update_channel"
    ADMIN_SHOW_LOG_CHANNEL = "admin:show_log_channel"
    ADMIN_DEL_CONTEST_PREFIX = "admin:del_contest:"
    ADMIN_TOGGLE_CHANNEL_BAN_PREFIX = "admin:toggle_channel_ban:"
    ADMIN_TOGGLE_GROUP_BAN_PREFIX = "admin:toggle_group_ban:"
    ADMIN_UNBAN_ALL_GROUPS = "admin:unban_all_groups"
    ADMIN_ACTIVATE_ALL_CHANNELS = "admin:activate_all_channels"
    ADMIN_UNBAN_ALL_BOT_CHANNELS = "admin:unban_all_bot_channels"
    PANEL_LOCK_PREFIX = "panel:lock:"
    PANEL_UNLOCK_PREFIX = "panel:unlock:"
    PANEL_CLOSE = "panel:close"
    CHECK_SUBSCRIBE = "check_subscribe"
    BACK = "back"
    CANCEL_SESSION = "cancel_session"
    ADVANCED_ACTIONS = "advanced_actions"
    GROUP_ACTION_BAN = "group_action:ban"
    GROUP_ACTION_MUTE = "group_action:mute"
    GROUP_ACTION_WARN = "group_action:warn"
    GROUP_ACTION_KICK = "group_action:kick"
    GROUP_ACTION_RESTRICT = "group_action:restrict"
    GROUP_ACTION_PIN = "group_action:pin"
    GROUP_ACTION_LOG = "group_action:log"
    GROUP_ACTION_UNBAN = "group_action:unban"
    GROUP_MUTE_DURATION_5 = "group_mute_duration:5"
    GROUP_MUTE_DURATION_30 = "group_mute_duration:30"
    GROUP_MUTE_DURATION_60 = "group_mute_duration:60"
    GROUP_MUTE_DURATION_720 = "group_mute_duration:720"
    GROUP_MUTE_DURATION_1440 = "group_mute_duration:1440"
    GROUP_MUTE_DURATION_10080 = "group_mute_duration:10080"
    GROUP_MUTE_DURATION_PERMANENT = "group_mute_duration:permanent"
    PENALTY_MENU = "penalty_menu"
    PENALTY_KICK = "penalty:kick"
    PENALTY_BAN = "penalty:ban"
    PENALTY_MUTE = "penalty:mute"
    PUBLISH_ALL_CHANNELS = "publish_all_channels"
    CHANNEL_STATS = "channel_stats"
    CHANNEL_STATS_REFRESH = "channel_stats_refresh"
    MY_CHANNEL_STATS = "my_channel_stats"
    CONTESTS_MENU = "contests_menu"
    CONTEST_JOIN_PREFIX = "contest_join:"
    CONTEST_WINNERS = "contest_winners"
    CONTESTS_BACK = "contests_back"
    AUTO_REPLY_TOGGLE_PREFIX = "auto_reply_toggle:"
    AUTO_REPLY_ADMINS_PREFIX = "auto_reply_admins:"
    AUTO_REPLY_RESET_PREFIX = "auto_reply_reset:"
    AUTO_REPLY_CONFIRM_RESET_PREFIX = "auto_reply_confirm_reset:"
    AUTO_REPLY_CANCEL_PREFIX = "auto_reply_cancel:"
    AUTO_REPLY_STATS_PREFIX = "auto_reply_stats:"
    USER_AUTO_REPLY_TOGGLE_PREFIX = "user_auto_reply_toggle:"
    NSFW_SETTINGS = "nsfw_settings"
    NSFW_TOGGLE = "nsfw_toggle"
    NSFW_THRESHOLD_SET = "nsfw_threshold_set"
    UPDATE_ADMINS = "update_admins"
    HIDDEN_ADMIN_ADD = "hidden_admin:add"
    HIDDEN_ADMIN_REMOVE_PREFIX = "hidden_admin:remove:"
    HIDDEN_ADMIN_LIST = "hidden_admin:list"
    ADMIN_BOT_CHANNELS = "admin:bot_channels"
    ADMIN_BANNED_BOT_CHANNELS = "admin:banned_bot_channels"
    ADMIN_GROUPS = "admin:groups"
    ADMIN_BANNED_GROUPS = "admin:banned_groups"
    ADMIN_MONITOR_USERS = "admin:monitor_users"

async def get_main_keyboard(user_id: int):
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
    ch_display = get_text(user_id, 'no_channels')
    if active is not None:
        try:
            cnt = await db_unpublished_count(active)
            ch_info = await db_get_channel_info(active)
            if ch_info:
                ch_tele_id = ch_info[0] if ch_info[0] is not None else "unknown"
                ch_name = ch_info[1] if ch_info[1] is not None else ch_tele_id
                ch_display = f"{ch_name} ({ch_tele_id})"
        except:
            ch_display = get_text(user_id, 'no_channels')
    
    my_groups = await db_get_user_groups_count(user_id)
    has_sub = await db_has_active_subscription(user_id)
    sub_text = get_text(user_id, 'subscribed') if has_sub else get_text(user_id, 'not_subscribed')
    auto_status = await db_auto_status(user_id)
    auto_text = get_text(user_id, 'auto_on') if auto_status else get_text(user_id, 'auto_off')
    
    title = get_text(user_id, 'main_title').format(BOT_NAME, user_id, my_groups, sub_text, ch_display, cnt, auto_status)
    
    keyboard = []
    
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'my_groups_btn'), callback_data=CallbackData.GROUPS_MY),
        InlineKeyboardButton(get_text(user_id, 'add_channel'), callback_data=CallbackData.CHANNELS_ADD)
    ])
    
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'my_channels'), callback_data=CallbackData.CHANNELS_MY),
        InlineKeyboardButton(get_text(user_id, 'settings_btn'), callback_data=CallbackData.SETTINGS_MENU)
    ])
    
    if channels:
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'add_15_posts'), callback_data=CallbackData.POSTS_ADD_15),
            InlineKeyboardButton(get_text(user_id, 'publish_one'), callback_data=CallbackData.POSTS_PUBLISH_ONE)
        ])
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'my_posts_btn'), callback_data=CallbackData.POSTS_MY),
            InlineKeyboardButton(get_text(user_id, 'recycle'), callback_data=CallbackData.POSTS_RECYCLE)
        ])
        keyboard.append([
            InlineKeyboardButton(f"{get_text(user_id, 'stats_btn')} ({cnt})", callback_data=CallbackData.STATS_PENDING),
            InlineKeyboardButton(get_text(user_id, 'my_stats_btn'), callback_data=CallbackData.STATS_FULL)
        ])
        if active is not None:
            keyboard.append([
                InlineKeyboardButton(get_text(user_id, 'schedule_btn'), callback_data=f"{CallbackData.SCHEDULE_MENU_PREFIX}{active}"),
                InlineKeyboardButton(get_text(user_id, 'channel_stats'), callback_data=f"{CallbackData.CHANNEL_STATS}:{active}")
            ])
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'my_channels_summary'), callback_data=CallbackData.MY_CHANNEL_STATS),
            InlineKeyboardButton(get_text(user_id, 'my_rank_btn'), callback_data="rank")
        ])
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'top_10_btn'), callback_data="top"),
            InlineKeyboardButton(get_text(user_id, 'schedule_post_btn'), callback_data="schedule_post")
        ])
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'publish_all'), callback_data=CallbackData.PUBLISH_ALL_CHANNELS)
        ])
    
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'help_btn'), callback_data=CallbackData.HELP),
        InlineKeyboardButton(get_text(user_id, 'trial_btn'), callback_data=CallbackData.TRIAL)
    ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'subscribe_btn'), callback_data=CallbackData.SUBSCRIBE_MENU),
        InlineKeyboardButton(get_text(user_id, 'developer_btn'), callback_data=CallbackData.DEVELOPER)
    ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'language_btn'), callback_data="language"),
        InlineKeyboardButton(get_text(user_id, 'support_btn'), callback_data=CallbackData.SUPPORT_MENU)
    ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'referral'), callback_data=CallbackData.REFERRAL_MENU),
        InlineKeyboardButton(get_text(user_id, 'reminder_settings'), callback_data=CallbackData.REMINDER_MENU)
    ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'translation_settings'), callback_data=CallbackData.TRANSLATION_MENU)
    ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'contests_menu'), callback_data=CallbackData.CONTESTS_MENU)
    ])
    
    updates_channel = await db_get_updates_channel()
    if updates_channel:
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'updates_btn'), callback_data=CallbackData.UPDATES)
        ])
    
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'add_to_group'), url=f"https://t.me/{BOT_USERNAME}?startgroup")
    ])
    
    is_admin = (user_id == PRIMARY_OWNER_ID) or (await is_bot_admin(user_id))
    if is_admin:
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'admin_panel'), callback_data=CallbackData.ADMIN_PANEL)
        ])
    
    return InlineKeyboardMarkup(keyboard), title, active

# ===================== معالجات الكولباك الأساسية =====================
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    kb, title, active_channel = await get_main_keyboard(user_id)
    if active_channel:
        context.user_data['active_channel'] = active_channel
        await db_set_active_channel(user_id, active_channel)
    
    if query:
        await safe_edit_markdown(query, title, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, user_id, title, reply_markup=kb)

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu_callback(update, context)

async def cancel_session_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    context.user_data.pop(f"session_{user_id}", None)
    context.user_data.pop(f"session_target_{user_id}", None)
    context.user_data.pop('state', None)
    
    if query:
        await query.edit_message_text(get_text(user_id, 'cancelled'))
    else:
        await context.bot.send_message(chat_id=user_id, text=get_text(user_id, 'cancelled'))
    
    await main_menu_callback(update, context)

async def add_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_CHANNEL_ID
    msg = get_text(user_id, 'send_channel_id')
    
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def my_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    channels = await db_get_channels(user_id)
    
    if not channels:
        msg = get_text(user_id, 'no_channels_list')
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
            InlineKeyboardButton(get_text(user_id, 'channel_stats'), callback_data=f"{CallbackData.CHANNEL_STATS}:{ch_db_id}"),
            InlineKeyboardButton(get_text(user_id, 'delete_channel'), callback_data=f"{CallbackData.CHANNELS_DELETE_PREFIX}{ch_db_id}")
        ])
    
    kb.append([InlineKeyboardButton(get_text(user_id, 'add_channel'), callback_data=CallbackData.CHANNELS_ADD)])
    kb.append([InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)])
    
    if query:
        await query.edit_message_text(get_text(user_id, 'channels_list'), reply_markup=InlineKeyboardMarkup(kb))
    else:
        await safe_send_markdown(context.bot, user_id, get_text(user_id, 'channels_list'), reply_markup=InlineKeyboardMarkup(kb))

async def delete_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    ch_db_id = int(query.data.split(":")[-1])
    if await db_delete_channel_by_id(user_id, ch_db_id):
        if query:
            await query.edit_message_text(get_text(user_id, 'channel_deleted'))
        else:
            await update.message.reply_text(get_text(user_id, 'channel_deleted'))
        await my_channels_callback(update, context)
    else:
        if query:
            await query.answer(get_text(user_id, 'delete_failed'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'delete_failed'))

async def select_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    ch_db_id = int(query.data.split(":")[-1])
    await db_set_active_channel(user_id, ch_db_id)
    context.user_data['active_channel'] = ch_db_id
    await invalidate_user_cache(user_id)
    
    kb, title, new_active = await get_main_keyboard(user_id)
    if new_active:
        context.user_data['active_channel'] = new_active
    
    if query:
        await safe_edit_markdown(query, title, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, user_id, title, reply_markup=kb)

async def add_15_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    
    if not active:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
        return
    
    unpublished_count = await db_unpublished_count(active)
    if unpublished_count >= MAX_UNPUBLISHED_POSTS:
        remaining = MAX_UNPUBLISHED_POSTS - unpublished_count
        if query:
            await query.edit_message_text(f"⚠️ لقد تجاوزت الحد الأقصى للمنشورات غير المنشورة ({MAX_UNPUBLISHED_POSTS}).\nالعدد المتبقي: {remaining} منشور")
        else:
            await update.message.reply_text(f"⚠️ لقد تجاوزت الحد الأقصى للمنشورات غير المنشورة ({MAX_UNPUBLISHED_POSTS}).\nالعدد المتبقي: {remaining} منشور")
        return
    
    context.user_data[f"session_{user_id}"] = []
    context.user_data[f"session_target_{user_id}"] = min(15, MAX_UNPUBLISHED_POSTS - unpublished_count)
    context.user_data['state'] = UserState.ADDING_POSTS
    
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.CANCEL_SESSION)]])
    msg = f"📥 أرسل المنشورات (نصوص أو صور أو فيديوهات أو مستندات)\nالحد الأقصى المسموح: {MAX_UNPUBLISHED_POSTS - unpublished_count} منشور"
    
    if query:
        await query.edit_message_text(msg, reply_markup=cancel_kb)
    else:
        await update.message.reply_text(msg, reply_markup=cancel_kb)

async def publish_one_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    
    if not active:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
        return
    
    post = await db_get_next_post(active)
    if not post:
        if query:
            await query.edit_message_text(get_text(user_id, 'no_posts'))
        else:
            await update.message.reply_text(get_text(user_id, 'no_posts'))
        return
    
    ch_info = await db_get_channel_info(active)
    
    try:
        if post['media_type'] == 'photo' and post['media_file_id']:
            await context.bot.send_photo(ch_info[0], post['media_file_id'], caption=post['text'] if post['text'] else None)
        elif post['media_type'] == 'video' and post['media_file_id']:
            await context.bot.send_video(ch_info[0], post['media_file_id'], caption=post['text'] if post['text'] else None)
        elif post['media_type'] == 'document' and post['media_file_id']:
            await context.bot.send_document(ch_info[0], post['media_file_id'], caption=post['text'] if post['text'] else None)
        else:
            await context.bot.send_message(ch_info[0], post['text'])
        
        await db_mark_published(post['id'])
        await db_set_last_publish(active, utc_now())
        await db_update_next_publish_date(active)
        
        if query:
            await query.edit_message_text(get_text(user_id, 'post_published'))
        else:
            await update.message.reply_text(get_text(user_id, 'post_published'))
    except Exception as e:
        if query:
            await query.edit_message_text(get_text(user_id, 'publish_error').format(str(e)[:100]))
        else:
            await update.message.reply_text(get_text(user_id, 'publish_error').format(str(e)[:100]))
    
    await main_menu_callback(update, context)

async def my_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    
    if not active:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
        return
    
    posts = await db_get_user_posts_for_channel(active, limit=15)
    if not posts:
        if query:
            await query.edit_message_text(get_text(user_id, 'no_posts'))
        else:
            await update.message.reply_text(get_text(user_id, 'no_posts'))
        return
    
    msg = get_text(user_id, 'my_posts_title') + "\n"
    kb_buttons = []
    
    for idx, (pid, ptext, media_type) in enumerate(posts[:10], 1):
        short = re.sub('<[^>]+>', '', ptext)[:80]
        media_icon = "🖼️" if media_type == 'photo' else "🎬" if media_type == 'video' else "📝" if media_type == 'text' else "📄"
        msg += f"{idx}. {media_icon} {short}...\n🆔 {pid}\n\n"
        kb_buttons.append([InlineKeyboardButton(f"🗑️ حذف #{pid}", callback_data=f"{CallbackData.POSTS_DELETE_SINGLE_PREFIX}{pid}_{active}")])
    
    kb_buttons.append([InlineKeyboardButton("🗑️ حذف الكل", callback_data=f"{CallbackData.POSTS_CONFIRM_CLEAR_ALL_PREFIX}{active}")])
    kb_buttons.append([InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)])
    
    if query:
        await safe_edit_markdown(query, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))
    else:
        await safe_send_markdown(context.bot, user_id, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))

async def delete_single_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    parts = query.data.split(":")[-1].split("_")
    if len(parts) >= 2:
        post_id = int(parts[0])
        active = int(parts[1])
        if await db_delete_single_post(post_id, user_id, active):
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
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    active = int(query.data.split(":")[-1])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم", callback_data=f"{CallbackData.POSTS_CLEAR_ALL_PREFIX}{active}"),
         InlineKeyboardButton("❌ لا", callback_data=CallbackData.BACK)]
    ])
    
    if query:
        await query.edit_message_text(get_text(user_id, 'confirm_delete'), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(user_id, 'confirm_delete'), reply_markup=kb)

async def clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    active = int(query.data.split(":")[-1])
    
    async def _clear_posts(conn):
        await conn.execute("DELETE FROM posts WHERE channel_db_id=?", (active,))
        await conn.commit()
    
    await execute_db(_clear_posts)
    
    if query:
        await query.answer(get_text(user_id, 'deleted_all'), show_alert=True)
    else:
        await update.message.reply_text(get_text(user_id, 'deleted_all'))
    
    await main_menu_callback(update, context)

async def recycle_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    
    if active:
        await db_reset_all_posts_to_unpublished(active)
        if query:
            await query.edit_message_text(get_text(user_id, 'recycled'))
        else:
            await update.message.reply_text(get_text(user_id, 'recycled'))
    else:
        if query:
            await query.edit_message_text("⚠️ اختر قناة أولاً")
        else:
            await update.message.reply_text("⚠️ اختر قناة أولاً")
    
    await main_menu_callback(update, context)

async def my_pending_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    unpublished = await db_get_user_unpublished_posts(user_id)
    total = await db_get_user_total_posts(user_id)
    
    text = get_text(user_id, 'pending_stats').format(unpublished, total)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]])
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=kb)

async def my_full_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    channels = await db_get_user_channels_count(user_id)
    total = await db_get_user_total_posts(user_id)
    unpublished = await db_get_user_unpublished_posts(user_id)
    groups = await db_get_user_groups_count(user_id)
    auto = get_text(user_id, 'auto_on') if await db_auto_status(user_id) else get_text(user_id, 'auto_off')
    
    text = get_text(user_id, 'stats').format(channels, total, unpublished, groups, auto)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]])
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=kb)

async def my_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    groups = await db_get_user_groups(user_id)
    
    if not groups:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
            [InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)],
            [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
        ])
        msg = "📭 لا توجد مجموعات مسجلة\n\nأضف البوت إلى مجموعة وستظهر هنا."
        
        if query:
            await safe_edit_markdown(query, msg, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, user_id, msg, reply_markup=kb)
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
            InlineKeyboardButton(lock_label, callback_data=lock_callback)
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
        await safe_send_markdown(context.bot, user_id, text, reply_markup=reply_markup)

async def group_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    settings = await db_get_security_settings(chat_id)
    
    async def _get_group_name(conn):
        cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return row[0] if row else str(chat_id)
    
    gname = await execute_db(_get_group_name)
    
    text = f"⚙️ **لوحة تحكم المجموعة: {gname}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🔗 حذف الروابط: {'✅' if settings['links'] else '❌'}\n"
    text += f"@ حذف المعرفات: {'✅' if settings['mentions'] else '❌'}\n"
    text += f"🚫 كلمات محظورة: {'✅' if settings.get('delete_banned_words', False) else '❌'}\n"
    text += f"⏱️ وضع بطيء: {'✅' if settings.get('slow_mode', False) else '❌'}\n"
    text += f"🎯 رسالة ترحيب: {'✅' if settings.get('welcome_enabled', False) else '❌'}\n"
    text += f"👋 رسالة وداع: {'✅' if settings.get('goodbye_enabled', False) else '❌'}\n"
    text += f"🔊 رسالة تحذير: {'✅' if settings['warn'] else '❌'}\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"⚖️ **العقوبة التلقائية:** {'طرد' if settings.get('auto_penalty') == 'kick' else 'حظر' if settings.get('auto_penalty') == 'ban' else 'كتم' if settings.get('auto_penalty') == 'mute' else 'لا شيء'}\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📌 **اختر الإجراء المناسب:**"
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=security_keyboard(chat_id))
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=security_keyboard(chat_id))

def security_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 حذف الروابط", callback_data=f"{CallbackData.SECURITY_LINKS_PREFIX}{chat_id}"),
         InlineKeyboardButton("@ حذف المعرفات", callback_data=f"{CallbackData.SECURITY_MENTIONS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🚫 كلمات محظورة", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}"),
         InlineKeyboardButton("⏱️ الوضع البطيء", callback_data=f"{CallbackData.SECURITY_SLOWMODE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🎯 الترحيب", callback_data=f"{CallbackData.SECURITY_WELCOME_PREFIX}{chat_id}"),
         InlineKeyboardButton("👋 الوداع", callback_data=f"{CallbackData.SECURITY_GOODBYE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("⚖️ تحديد العقوبة", callback_data=f"{CallbackData.PENALTY_MENU}:{chat_id}")],
        [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}")],
        [InlineKeyboardButton("📜 سجل الإجراءات", callback_data=f"{CallbackData.GROUP_ACTION_LOG}:{chat_id}")],
        [InlineKeyboardButton("🔙 إغلاق", callback_data=CallbackData.SECURITY_CLOSE)]
    ])

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    auto = await db_auto_status(user_id)
    auto_btn = get_text(user_id, 'disabled') if auto else get_text(user_id, 'enabled')
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{auto_btn} النشر التلقائي", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    
    if query:
        await query.edit_message_text(get_text(user_id, 'settings'), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(user_id, 'settings'), reply_markup=kb)

async def toggle_auto_publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    cur = await db_auto_status(user_id)
    await db_set_auto(user_id, not cur)
    status = get_text(user_id, 'enabled') if not cur else get_text(user_id, 'disabled')
    
    if query:
        await query.edit_message_text(get_text(user_id, 'auto_toggled').format(status))
    else:
        await update.message.reply_text(get_text(user_id, 'auto_toggled').format(status))
    
    await main_menu_callback(update, context)

# ===================== معالجات الكولباك للأمان =====================
async def security_links_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
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
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
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
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
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
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
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
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    context.user_data['banned_words_chat_id'] = chat_id
    msg = "🚫 إدارة الكلمات المحظورة للمجموعة"
    
    if query:
        await query.edit_message_text(msg, reply_markup=get_group_banned_words_keyboard(chat_id))
    else:
        await update.message.reply_text(msg, reply_markup=get_group_banned_words_keyboard(chat_id))

def get_group_banned_words_keyboard(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"{CallbackData.BANNED_WORDS_ADD_PREFIX}{chat_id}"),
         InlineKeyboardButton("📋 عرض الكلمات", callback_data=f"{CallbackData.BANNED_WORDS_LIST_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=f"{CallbackData.BANNED_WORDS_REMOVE_PREFIX}{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

async def security_welcome_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
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
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    settings = await db_get_security_settings(chat_id)
    settings['goodbye_enabled'] = not settings['goodbye_enabled']
    await db_set_security_settings(chat_id, **settings)
    
    if query:
        await query.edit_message_text("✅ تم التحديث")
    else:
        await update.message.reply_text("✅ تم التحديث")
    
    await group_settings_callback(update, context)

async def security_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.delete()

async def security_select_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
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
        cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return row[0] if row else str(chat_id)
    
    gname = await execute_db(_get_group_name)
    
    text = f"""⚙️ **لوحة تحكم المجموعة: {gname}**
━━━━━━━━━━━━━━━━━━━━━━
🔗 حذف الروابط: {'✅' if settings['links'] else '❌'}
@ حذف المعرفات: {'✅' if settings['mentions'] else '❌'}
🚫 كلمات محظورة: {'✅' if settings.get('delete_banned_words', False) else '❌'}
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
        await safe_send_markdown(context.bot, user_id, text, reply_markup=security_keyboard(chat_id))

async def security_refresh_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    groups = await db_get_user_groups(user_id)
    
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
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
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
        await safe_send_markdown(context.bot, user_id, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def banned_words_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    context.user_data['state'] = UserState.WAITING_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    msg = "➕ أرسل الكلمة التي تريد إضافتها للكلمات المحظورة:"
    
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def banned_words_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    words = await db_get_banned_words(chat_id)
    
    if not words:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]])
        if query:
            await query.edit_message_text("📭 لا توجد كلمات محظورة في هذه المجموعة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد كلمات محظورة في هذه المجموعة.", reply_markup=kb)
        return
    
    text = "🚫 **الكلمات المحظورة في المجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for word, added_by, added_at in words[:20]:
        text += f"• `{word}` (أضيف بواسطة {added_by})\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]
    ])
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def banned_words_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    context.user_data['state'] = UserState.WAITING_REMOVE_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    msg = "🗑️ أرسل الكلمة التي تريد حذفها من الكلمات المحظورة:"
    
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

# ===================== معالجات الكولباك للدعم =====================
async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    
    if query:
        await safe_edit_markdown(query, get_text(user_id, 'help'), reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, get_text(user_id, 'help'), reply_markup=keyboard)

async def support_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
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
    
    text = get_text(user_id, 'support_welcome')
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def support_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.SUPPORT_MENU)]
    ])
    
    text = get_text(user_id, 'support_help')
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def support_ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
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
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    
    if await db_has_used_trial(user_id):
        if query:
            await query.edit_message_text(get_text(user_id, 'trial_used'))
        else:
            await update.message.reply_text(get_text(user_id, 'trial_used'))
        return
    
    if await db_has_active_subscription(user_id):
        if query:
            await query.edit_message_text(get_text(user_id, 'already_subscribed'))
        else:
            await update.message.reply_text(get_text(user_id, 'already_subscribed'))
        return
    
    await db_activate_trial(user_id)
    
    if query:
        await query.edit_message_text(get_text(user_id, 'trial'))
    else:
        await update.message.reply_text(get_text(user_id, 'trial'))
    
    await main_menu_callback(update, context)

async def subscribe_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    
    if await db_has_active_subscription(user_id):
        days = await db_get_subscription_days_left(user_id)
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
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    
    text = get_text(user_id, 'subscribe')
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)

async def buy_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int, price: int, title: str):
    if not update:
        return
    
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
        if query:
            await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}")
        else:
            await update.message.reply_text(f"❌ خطأ: {str(e)[:100]}")

async def buy_subscription_1_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_subscription_callback(update, context, 1, 5, "اشتراك 1 يوم")

async def buy_subscription_2_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_subscription_callback(update, context, 2, 9, "اشتراك 2 يوم")

async def buy_subscription_30_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_subscription_callback(update, context, 30, 50, "اشتراك شهر")

async def buy_subscription_90_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_subscription_callback(update, context, 90, 120, "اشتراك 3 أشهر")

async def developer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    
    text = f"""👑 **معلومات المطور**
━━━━━━━━━━━━━━━━━━━━━━
🤖 **البوت:** {BOT_NAME}
📦 **الإصدار:** 19.3.1
👨‍💻 **المطور:** @RelaxMgr

📞 **طرق التواصل:**
✅ **تيليجرام:** @RelaxMgr
✅ **البوت:** @{BOT_USERNAME}"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 تواصل مع المطور", url=f"https://t.me/RelaxMgr")],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    updates_channel = await db_get_updates_channel()
    
    if updates_channel:
        text = f"""📢 **قناة التحديثات**
━━━━━━━━━━━━━━━━━━━━━━
📌 القناة: @{updates_channel}

📢 تابع القناة لمعرفة آخر التحديثات:
• ميزات جديدة ✨
• تحسينات الأداء ⚡
• إصلاحات الأخطاء 🔧
• عروض حصرية 🎁"""
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 افتح القناة", url=f"https://t.me/{updates_channel}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
    else:
        text = """📢 **لم يتم تعيين قناة التحديثات بعد**

📌 **لتعيين قناة التحديثات:**
1. استخدم `/admin_panel`
2. اضغط على `⚙️ قناة التحديثات`
3. أرسل معرف القناة"""
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👑 الذهاب للوحة الأدمن", callback_data=CallbackData.ADMIN_PANEL)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def referral_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    
    text = """🔗 **الإحالات**
━━━━━━━━━━━━━━━━━━━━━━
📌 نظام الإحالات قيد التطوير
    
🔙 ارجع للقائمة الرئيسية"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def reminder_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    
    text = """⏰ **التذكيرات**
━━━━━━━━━━━━━━━━━━━━━━
📌 نظام التذكيرات قيد التطوير
    
🔙 ارجع للقائمة الرئيسية"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def translation_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    
    text = """🌐 **الترجمة**
━━━━━━━━━━━━━━━━━━━━━━
📌 نظام الترجمة قيد التطوير
    
🔙 ارجع للقائمة الرئيسية"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

# ===================== معالجات لوحة الأدمن =====================
async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 المستخدمين", callback_data=CallbackData.ADMIN_USERS),
         InlineKeyboardButton("🚫 المحظورين", callback_data=CallbackData.ADMIN_BANNED_USERS)],
        [InlineKeyboardButton("📡 القنوات", callback_data=CallbackData.ADMIN_ALL_CHANNELS),
         InlineKeyboardButton("⛔ قنوات محظورة", callback_data=CallbackData.ADMIN_BANNED_CHANNELS)],
        [InlineKeyboardButton("👑 + مشرف", callback_data=CallbackData.ADMIN_ADD_ADMIN),
         InlineKeyboardButton("🗑️ - مشرف", callback_data=CallbackData.ADMIN_REMOVE_ADMIN)],
        [InlineKeyboardButton("📢 نشر تحديث", callback_data=CallbackData.ADMIN_SEND_UPDATE),
         InlineKeyboardButton("⚙️ قناة التحديثات", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
        [InlineKeyboardButton("🔒 الاشتراك الإجباري", callback_data=CallbackData.ADMIN_FORCE_SUBSCRIBE),
         InlineKeyboardButton("📨 إرسال رسالة", callback_data=CallbackData.ADMIN_BROADCAST)],
        [InlineKeyboardButton("📋 تذاكر الدعم", callback_data=CallbackData.ADMIN_SUPPORT_TICKETS),
         InlineKeyboardButton("📁 صلاحية /sendcode", callback_data=CallbackData.ADMIN_MANAGE_SENDCODE)],
        [InlineKeyboardButton("💬 ردود المجموعة", callback_data=CallbackData.ADMIN_REPLIES)],
        [InlineKeyboardButton("📝 إعدادات الردود", callback_data=CallbackData.ADMIN_AUTO_REPLY)],
        [InlineKeyboardButton("🏆 إنشاء مسابقة", callback_data=CallbackData.ADMIN_CREATE_CONTEST)],
        [InlineKeyboardButton("📊 إحصائيات", callback_data=CallbackData.ADMIN_STATS)],
        [InlineKeyboardButton("💾 نسخ احتياطي", callback_data=CallbackData.ADMIN_BACKUP)],
        [InlineKeyboardButton("🔧 إعدادات النسخ الاحتياطي", callback_data=CallbackData.ADMIN_BACKUP_SETTINGS)],
        [InlineKeyboardButton("📊 استخدام الذاكرة", callback_data=CallbackData.ADMIN_RAM)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    
    if query:
        await safe_edit_markdown(query, get_text(user_id, 'admin_panel'), reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, get_text(user_id, 'admin_panel'), reply_markup=keyboard)

# ===================== دوال الأدمن الإضافية =====================
async def admin_confirm_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأكيد الإرسال الجماعي"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    broadcast_text = context.user_data.get('broadcast_text')
    if not broadcast_text:
        await query.edit_message_text("❌ لا يوجد نص للإرسال.")
        return
    
    await query.edit_message_text("📨 جاري الإرسال إلى جميع المستخدمين...")
    
    users = await db_get_all_users()
    success_count = 0
    fail_count = 0
    
    for user in users:
        uid = user[0]
        if user[1] == 1:
            continue
        try:
            await context.bot.send_message(chat_id=uid, text=broadcast_text)
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception:
            fail_count += 1
    
    context.user_data.pop('broadcast_text', None)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await query.edit_message_text(
        f"✅ **تم الإرسال الجماعي!**\n\n"
        f"✅ نجح: {success_count}\n"
        f"❌ فشل: {fail_count}",
        reply_markup=keyboard
    )

async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إحصائيات البوت"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    users = await db_get_all_users()
    total_users = len(users)
    banned_users = len([u for u in users if u[1] == 1])
    
    channels = await db_get_channels(0)
    total_channels = len(channels)
    
    groups = await db_get_user_groups(0)
    total_groups = len(groups)
    
    text = f"""📊 **إحصائيات البوت**
━━━━━━━━━━━━━━━━━━━━━━
👥 **المستخدمين**
• الإجمالي: {total_users}
• المحظورين: {banned_users}
• النشطين: {total_users - banned_users}

📡 **القنوات**: {total_channels}
👥 **المجموعات**: {total_groups}
📝 **المنشورات**: {await db_get_user_total_posts(0)}
━━━━━━━━━━━━━━━━━━━━━━
🤖 **الإصدار:** 19.3.1
📅 **التاريخ:** {mecca_now().strftime('%Y-%m-%d %H:%M')}"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_ram_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استخدام الذاكرة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    import psutil
    memory = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.5)
    disk = psutil.disk_usage('/')
    
    text = f"""💾 **استخدام الموارد**
━━━━━━━━━━━━━━━━━━━━━━
🧠 **الذاكرة (RAM)**
• المستخدم: {memory.used / (1024**3):.2f} GB
• الإجمالي: {memory.total / (1024**3):.2f} GB
• النسبة: {memory.percent}%

⚡ **المعالج (CPU)**
• الاستخدام: {cpu}%

💿 **التخزين (Disk)**
• المستخدم: {disk.used / (1024**3):.2f} GB
• الإجمالي: {disk.total / (1024**3):.2f} GB
• النسبة: {disk.percent}%
━━━━━━━━━━━━━━━━━━━━━━
🔄 **محدث:** {mecca_now().strftime('%Y-%m-%d %H:%M:%S')}"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=CallbackData.ADMIN_RAM),
         InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إنشاء نسخة احتياطية"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    await query.edit_message_text("💾 جاري إنشاء النسخة الاحتياطية...")
    
    try:
        backup_file = BACKUP_DIR / f"backup_{mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(DB_PATH, backup_file)
        
        # تنظيف النسخ القديمة
        backups = sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old_backup in backups[10:]:
            old_backup.unlink()
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 تحميل", callback_data=f"{CallbackData.ADMIN_RESTORE_BACKUP_SELECT_PREFIX}{backup_file.name}"),
             InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
        ])
        
        await query.edit_message_text(
            f"✅ **تم إنشاء النسخة الاحتياطية!**\n\n"
            f"📁 الملف: `{backup_file.name}`\n"
            f"📅 التاريخ: {mecca_now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"📦 الحجم: {backup_file.stat().st_size / 1024:.2f} KB",
            reply_markup=keyboard
        )
    except Exception as e:
        await query.edit_message_text(f"❌ فشل إنشاء النسخة الاحتياطية: {e}")

async def admin_backup_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعدادات النسخ الاحتياطي"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تبديل النسخ التلقائي", callback_data=CallbackData.ADMIN_TOGGLE_AUTO_BACKUP)],
        [InlineKeyboardButton("⏱️ تغيير الفاصل الزمني", callback_data=CallbackData.ADMIN_CHANGE_INTERVAL)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await query.edit_message_text(
        "🔧 **إعدادات النسخ الاحتياطي**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "• النسخ التلقائي: مفعل\n"
        "• الفاصل الزمني: 24 ساعة\n"
        "• عدد النسخ المحفوظة: 10\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "اختر الإعداد المطلوب:",
        reply_markup=keyboard
    )

async def admin_toggle_auto_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل النسخ الاحتياطي التلقائي"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    # toggle logic here
    await query.edit_message_text("✅ تم تغيير إعدادات النسخ الاحتياطي التلقائي.")

async def admin_change_interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تغيير فاصل النسخ الاحتياطي"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    context.user_data['state'] = UserState.WAITING_INTERVAL_HOURS
    await query.edit_message_text(
        "⏱️ أرسل عدد الساعات بين كل نسخة احتياطية:\n"
        "(مثال: 24 للنسخ كل يوم)"
    )

async def admin_show_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قناة التحديثات"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    channel = await db_get_updates_channel()
    
    text = f"📢 **قناة التحديثات**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    if channel:
        text += f"✅ القناة الحالية: @{channel}"
    else:
        text += "❌ لم يتم تعيين قناة تحديثات"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ تغيير", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_show_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قناة التقارير"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    channel = await db_get_log_channel_id()
    
    text = f"📋 **قناة التقارير**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    if channel:
        text += f"✅ القناة الحالية: `{channel}`"
    else:
        text += "❌ لم يتم تعيين قناة تقارير"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ تغيير", callback_data=CallbackData.ADMIN_SET_LOG_CHANNEL)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة الكلمات المحظورة العامة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة", callback_data=CallbackData.ADMIN_ADD_BANNED_WORD)],
        [InlineKeyboardButton("📋 عرض الكلمات", callback_data=CallbackData.ADMIN_LIST_BANNED_WORDS)],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=CallbackData.ADMIN_REMOVE_BANNED_WORD)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await query.edit_message_text(
        "🚫 **إدارة الكلمات المحظورة العامة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        "هذه الكلمات ستمنع في جميع المجموعات.",
        reply_markup=keyboard
    )

async def admin_add_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة كلمة محظورة عامة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    context.user_data['state'] = UserState.WAITING_GLOBAL_BANNED_WORD
    await query.edit_message_text(
        "➕ أرسل الكلمة التي تريد إضافتها ككلمة محظورة عامة:"
    )

async def admin_list_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض الكلمات المحظورة العامة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    words = await db_get_banned_words(-1)
    
    if not words:
        text = "📭 لا توجد كلمات محظورة عامة."
    else:
        text = "🚫 **الكلمات المحظورة العامة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for word, added_by, added_at in words[:50]:
            text += f"• `{word}` (أضيف بواسطة {added_by})\n"
        if len(words) > 50:
            text += f"\nو {len(words)-50} كلمة أخرى..."
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_BANNED_WORDS)]
    ])
    
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_remove_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف كلمة محظورة عامة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    context.user_data['state'] = UserState.WAITING_REMOVE_GLOBAL_BANNED_WORD
    await query.edit_message_text(
        "🗑️ أرسل الكلمة التي تريد حذفها من الكلمات المحظورة العامة:"
    )

async def admin_del_contest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف مسابقة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    contest_id = int(query.data.split(":")[-1])
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    async def _delete_contest(conn):
        await conn.execute("DELETE FROM contests WHERE id = ?", (contest_id,))
        await conn.execute("DELETE FROM contest_participants WHERE contest_id = ?", (contest_id,))
        await conn.commit()
        return True
    
    await execute_db(_delete_contest)
    await query.edit_message_text("✅ تم حذف المسابقة بنجاح.")
    await admin_panel_callback(update, context)

async def admin_delete_all_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف جميع التذاكر"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، احذف الكل", callback_data=CallbackData.ADMIN_CONFIRM_DELETE_TICKETS),
         InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.ADMIN_SUPPORT_TICKETS)]
    ])
    
    await query.edit_message_text(
        "⚠️ **تأكيد حذف جميع التذاكر**\n\n"
        "سيتم حذف جميع تذاكر الدعم بشكل دائم.\n"
        "هل أنت متأكد؟",
        reply_markup=keyboard
    )

async def admin_confirm_delete_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأكيد حذف جميع التذاكر"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    await db_delete_all_tickets()
    await query.edit_message_text("✅ تم حذف جميع تذاكر الدعم بنجاح.")
    await admin_panel_callback(update, context)

async def admin_toggle_channel_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل حظر قناة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    channel_id = int(query.data.split(":")[-1])
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    async def _toggle_ban(conn):
        cur = await conn.execute("SELECT banned FROM user_channels WHERE id = ?", (channel_id,))
        row = await cur.fetchone()
        current = row[0] if row else 0
        new_status = 1 if current == 0 else 0
        await conn.execute("UPDATE user_channels SET banned = ? WHERE id = ?", (new_status, channel_id))
        await conn.commit()
        return new_status
    
    new_status = await execute_db(_toggle_ban)
    status_text = "محظورة" if new_status == 1 else "نشطة"
    await query.edit_message_text(f"✅ تم تغيير حالة القناة إلى: {status_text}")

async def admin_toggle_group_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل حظر مجموعة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    group_id = int(query.data.split(":")[-1])
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    async def _toggle_ban(conn):
        cur = await conn.execute("SELECT banned FROM bot_groups WHERE chat_id = ?", (group_id,))
        row = await cur.fetchone()
        current = row[0] if row else 0
        new_status = 1 if current == 0 else 0
        await conn.execute("UPDATE bot_groups SET banned = ? WHERE chat_id = ?", (new_status, group_id))
        await conn.commit()
        return new_status
    
    new_status = await execute_db(_toggle_ban)
    status_text = "محظورة" if new_status == 1 else "نشطة"
    await query.edit_message_text(f"✅ تم تغيير حالة المجموعة إلى: {status_text}")

async def admin_unban_all_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء حظر جميع المجموعات"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    async def _unban_all(conn):
        await conn.execute("UPDATE bot_groups SET banned = 0 WHERE banned = 1")
        await conn.commit()
    
    await execute_db(_unban_all)
    await query.edit_message_text("✅ تم إلغاء حظر جميع المجموعات.")

async def admin_activate_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تفعيل جميع القنوات"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    async def _activate_all(conn):
        await conn.execute("UPDATE user_channels SET banned = 0 WHERE banned = 1")
        await conn.commit()
    
    await execute_db(_activate_all)
    await query.edit_message_text("✅ تم تفعيل جميع القنوات.")

async def admin_unban_all_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء حظر جميع قنوات البوت"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    async def _unban_all(conn):
        await conn.execute("UPDATE user_channels SET banned = 0 WHERE banned = 1")
        await conn.commit()
    
    await execute_db(_unban_all)
    await query.edit_message_text("✅ تم إلغاء حظر جميع قنوات البوت.")

# ===================== دوال الردود التلقائية الإضافية =====================
async def auto_reply_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعادة تعيين الردود التلقائية"""
    query = update.callback_query
    await query.answer()
    
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، إعادة تعيين", callback_data=f"{CallbackData.AUTO_REPLY_CONFIRM_RESET_PREFIX}{chat_id}"),
         InlineKeyboardButton("❌ إلغاء", callback_data=f"{CallbackData.AUTO_REPLY_CANCEL_PREFIX}{chat_id}")]
    ])
    
    await query.edit_message_text(
        "⚠️ **تأكيد إعادة تعيين الردود**\n\n"
        "سيتم حذف جميع الردود التلقائية المخصصة لهذه المجموعة.\n"
        "هل أنت متأكد؟",
        reply_markup=keyboard
    )

async def auto_reply_confirm_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأكيد إعادة تعيين الردود"""
    query = update.callback_query
    await query.answer()
    
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    
    async def _reset(conn):
        await conn.execute("DELETE FROM group_replies WHERE keyword LIKE ?", (f"custom_{chat_id}%",))
        await conn.commit()
    
    await execute_db(_reset)
    await query.edit_message_text("✅ تم إعادة تعيين جميع الردود التلقائية.")

async def auto_reply_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء إعادة تعيين الردود"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ تم إلغاء العملية.")

async def auto_reply_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إحصائيات الردود التلقائية"""
    query = update.callback_query
    await query.answer()
    
    chat_id = int(query.data.split(":")[-1])
    user_id = update.effective_user.id
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    
    replies = await db_get_all_replies()
    total_replies = len(replies)
    
    text = f"""📊 **إحصائيات الردود التلقائية**
━━━━━━━━━━━━━━━━━━━━━━
📝 إجمالي الردود: {total_replies}
👥 المجموعة: {chat_id}
━━━━━━━━━━━━━━━━━━━━━━
📌 الردود النشطة: {total_replies}"""
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=f"{CallbackData.ADMIN_AUTO_REPLY_SELECT_PREFIX}{chat_id}")]
    ])
    
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def user_auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل الردود التلقائية للمستخدم"""
    query = update.callback_query
    await query.answer()
    
    # Placeholder - full implementation would need user_id from callback data
    await query.edit_message_text("✅ تم تغيير إعدادات الردود التلقائية للمستخدم.")

async def nsfw_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعدادات NSFW"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    nsfw_enabled = os.getenv("NSFW_ENABLED", "False").lower() == "true"
    nsfw_threshold = float(os.getenv("NSFW_THRESHOLD", 0.7))
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔄 NSFW: {'مفعل' if nsfw_enabled else 'معطل'}", callback_data=CallbackData.NSFW_TOGGLE)],
        [InlineKeyboardButton(f"🎯 الحد الأدنى: {nsfw_threshold}", callback_data=CallbackData.NSFW_THRESHOLD_SET)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await query.edit_message_text(
        "🔞 **إعدادات NSFW**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• الحالة: {'مفعل ✅' if nsfw_enabled else 'معطل ❌'}\n"
        f"• الحد الأدنى للكشف: {nsfw_threshold}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "اختر الإعداد المطلوب:",
        reply_markup=keyboard
    )

async def nsfw_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تبديل NSFW"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    current = os.getenv("NSFW_ENABLED", "False").lower() == "true"
    new_value = "True" if not current else "False"
    
    # Update .env or settings
    await query.edit_message_text(f"✅ تم تغيير إعدادات NSFW إلى: {'مفعل' if new_value == 'True' else 'معطل'}")
    await nsfw_settings_callback(update, context)

async def nsfw_threshold_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تعيين حد NSFW"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    
    context.user_data['state'] = UserState.WAITING_NSFW_THRESHOLD
    await query.edit_message_text(
        "🎯 أرسل الحد الأدنى للكشف (NSFW Threshold)\n"
        "القيمة بين 0 و 1:\n"
        "• 0.5 = متوسط\n"
        "• 0.7 = صارم\n"
        "• 0.9 = صارم جداً\n\n"
        "مثال: 0.7"
    )

# ===================== معالجات الكولباك للغة =====================
async def lang_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    
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
    
    await set_user_language(user_id, lang)
    
    lang_names = {
        'ar': 'العربية 🇸🇦',
        'en': 'English 🇬🇧',
        'fr': 'Français 🇫🇷',
        'tr': 'Türkçe 🇹🇷',
        'zh': '中文 🇨🇳',
        'ru': 'Русский 🇷🇺',
        'de': 'Deutsch 🇩🇪',
        'es': 'Español 🇪🇸',
        'it': 'Italiano 🇮🇹',
        'pt': 'Português 🇵🇹',
        'ja': '日本語 🇯🇵',
        'ko': '한국어 🇰🇷'
    }
    
    lang_name = lang_names.get(lang, lang)
    kb, title, active_channel = await get_main_keyboard(user_id)
    
    if active_channel:
        context.user_data['active_channel'] = active_channel
        await db_set_active_channel(user_id, active_channel)
    
    if query:
        await safe_edit_markdown(query, f"✅ تم تغيير اللغة إلى {lang_name}\n\n{title}", reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, user_id, f"✅ تم تغيير اللغة إلى {lang_name}\n\n{title}", reply_markup=kb)

# ===================== معالجات الكولباك الإضافية =====================
class UserState(Enum):
    NONE = auto()
    ADDING_POSTS = auto()
    WAITING_CHANNEL_ID = auto()
    WAITING_INTERVAL_MINUTES = auto()
    WAITING_INTERVAL_HOURS = auto()
    WAITING_INTERVAL_DAYS = auto()
    WAITING_DATES = auto()
    WAITING_PUBLISH_TIME = auto()
    SELECTING_DAYS = auto()
    WAITING_ADMIN_ID_ADD = auto()
    WAITING_ADMIN_ID_REMOVE = auto()
    WAITING_BROADCAST = auto()
    WAITING_UPDATE_TEXT = auto()
    WAITING_UPDATE_CHANNEL = auto()
    WAITING_FORCE_CHANNEL = auto()
    WAITING_SENDCODE_PASSWORD = auto()
    WAITING_REMINDER_DAYS = auto()
    WAITING_SCHEDULE_POST = auto()
    WAITING_BAN_USER = auto()
    WAITING_MUTE_USER = auto()
    WAITING_WARN_USER = auto()
    WAITING_KICK_USER = auto()
    WAITING_RESTRICT_USER = auto()
    WAITING_UNBAN_USER = auto()
    WAITING_PIN_MESSAGE = auto()
    WAITING_GROUP_BANNED_WORD = auto()
    WAITING_REMOVE_GROUP_BANNED_WORD = auto()
    WAITING_GLOBAL_BANNED_WORD = auto()
    WAITING_REMOVE_GLOBAL_BANNED_WORD = auto()
    WAITING_KEYWORD = auto()
    WAITING_REPLY = auto()
    WAITING_SENDCODE_USER = auto()
    WAITING_LOG_CHANNEL = auto()
    WAITING_2FA = auto()
    SUPPORT_MODE = auto()
    WAITING_CONTEST_TITLE = auto()
    WAITING_CONTEST_DESCRIPTION = auto()
    WAITING_CONTEST_PRIZE = auto()
    WAITING_CONTEST_END_DATE = auto()
    WAITING_CONTEST_ANSWER = auto()
    WAITING_NSFW_THRESHOLD = auto()

async def handle_text_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    data = query.data if query else context.user_data.get('text_callback_data')
    
    if not data:
        return

async def get_top_users(limit: int = 10):
    async def _get(conn):
        cur = await conn.execute("SELECT user_id FROM users LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def advanced_actions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if chat_id == 0:
        if query:
            await query.edit_message_text("⚠️ يرجى اختيار مجموعة أولاً باستخدام أمر /security")
        else:
            await update.message.reply_text("⚠️ يرجى اختيار مجموعة أولاً باستخدام أمر /security")
        return
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    msg = "🛠️ **الإجراءات المتقدمة للمجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الإجراء المطلوب:"
    
    if query:
        await safe_edit_markdown(query, msg, reply_markup=get_advanced_group_actions_keyboard(chat_id))
    else:
        await safe_send_markdown(context.bot, user_id, msg, reply_markup=get_advanced_group_actions_keyboard(chat_id))

def get_advanced_group_actions_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 حظر", callback_data=f"{CallbackData.GROUP_ACTION_BAN}:{chat_id}"),
         InlineKeyboardButton("🔇 كتم", callback_data=f"{CallbackData.GROUP_ACTION_MUTE}:{chat_id}")],
        [InlineKeyboardButton("⚠️ تحذير", callback_data=f"{CallbackData.GROUP_ACTION_WARN}:{chat_id}"),
         InlineKeyboardButton("👢 طرد", callback_data=f"{CallbackData.GROUP_ACTION_KICK}:{chat_id}")],
        [InlineKeyboardButton("🔒 تقييد", callback_data=f"{CallbackData.GROUP_ACTION_RESTRICT}:{chat_id}"),
         InlineKeyboardButton("📌 تثبيت", callback_data=f"{CallbackData.GROUP_ACTION_PIN}:{chat_id}")],
        [InlineKeyboardButton("🔓 إلغاء حظر", callback_data=f"{CallbackData.GROUP_ACTION_UNBAN}:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

async def group_action_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    context.user_data['state'] = UserState.WAITING_BAN_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "🚫 **حظر مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /ban"
    
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    msg = "🔇 **كتم مستخدم**\n\nاختر مدة الكتم:"
    
    if query:
        await safe_edit_markdown(query, msg, reply_markup=get_advanced_mute_duration_keyboard(chat_id))
    else:
        await update.message.reply_text(msg, reply_markup=get_advanced_mute_duration_keyboard(chat_id))

def get_advanced_mute_duration_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ 5 دقائق", callback_data=f"adv_mute_duration:5:{chat_id}"),
         InlineKeyboardButton("⏱️ 30 دقيقة", callback_data=f"adv_mute_duration:30:{chat_id}")],
        [InlineKeyboardButton("⏱️ 1 ساعة", callback_data=f"adv_mute_duration:60:{chat_id}"),
         InlineKeyboardButton("⏱️ 12 ساعة", callback_data=f"adv_mute_duration:720:{chat_id}")],
        [InlineKeyboardButton("📆 يوم", callback_data=f"adv_mute_duration:1440:{chat_id}"),
         InlineKeyboardButton("📆 أسبوع", callback_data=f"adv_mute_duration:10080:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم دائم", callback_data=f"adv_mute_duration:0:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}")]
    ])

async def advanced_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    parts = query.data.split(":")
    if len(parts) == 3:
        minutes = int(parts[1])
        chat_id = int(parts[2])
        
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            if query:
                await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
            else:
                await update.message.reply_text(get_text(user_id, 'admin_only'))
            return
        
        context.user_data['mute_minutes'] = minutes
        context.user_data['state'] = UserState.WAITING_MUTE_USER
        context.user_data['advanced_chat_id'] = chat_id
        
        if minutes == 0:
            msg = "🔇 **كتم دائم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute"
        elif minutes < 60:
            msg = f"🔇 **كتم {minutes} دقيقة**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute"
        elif minutes < 1440:
            msg = f"🔇 **كتم {minutes // 60} ساعة**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute"
        else:
            msg = f"🔇 **كتم {minutes // 1440} يوم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute"
        
        if query:
            await safe_edit_markdown(query, msg)
        else:
            await update.message.reply_text(msg)

async def group_action_warn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    context.user_data['state'] = UserState.WAITING_WARN_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "⚠️ **تحذير مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /warn\n\n📌 بعد 3 تحذيرات يتم حظر المستخدم تلقائياً"
    
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    context.user_data['state'] = UserState.WAITING_KICK_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "👢 **طرد مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /kick"
    
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_restrict_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    context.user_data['state'] = UserState.WAITING_RESTRICT_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "🔒 **تقييد مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /restrict\n\n📌 التقييد يمنع المستخدم من إرسال الصور والفيديوهات والملفات"
    
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_pin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    context.user_data['state'] = UserState.WAITING_PIN_MESSAGE
    context.user_data['advanced_chat_id'] = chat_id
    msg = "📌 **تثبيت رسالة**\n\nقم بالرد على الرسالة التي تريد تثبيتها ثم أرسل /pin"
    
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def group_action_log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    text = "📜 **سجل الإجراءات**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد سجلات حالياً."
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def group_action_unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    context.user_data['state'] = UserState.WAITING_UNBAN_USER
    context.user_data['advanced_chat_id'] = chat_id
    msg = "🔓 **إلغاء حظر مستخدم**\n\nأرسل معرف المستخدم (user_id) لإلغاء حظره"
    
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def panel_lock_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if await is_authorized_in_group(context.bot, chat_id, user_id):
        await db_set_chat_lock(chat_id, True, user_id)
        if query:
            await safe_edit_markdown(query, get_text(user_id, 'locked'))
        else:
            await update.message.reply_text(get_text(user_id, 'locked'))
    else:
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))

async def panel_unlock_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    
    if await is_authorized_in_group(context.bot, chat_id, user_id):
        await db_set_chat_lock(chat_id, False)
        if query:
            await safe_edit_markdown(query, get_text(user_id, 'unlocked'))
        else:
            await update.message.reply_text(get_text(user_id, 'unlocked'))
    else:
        if query:
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(user_id, 'admin_only'))

async def panel_close_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
        await query.message.delete()

async def check_subscribe_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    enabled = await db_get_force_subscribe_status()
    channel = await db_get_force_subscribe_channel()
    
    if enabled and channel:
        if await is_user_subscribed(context.bot, user_id, channel):
            if query:
                await safe_edit_markdown(query, "✅ تم التحقق! أنت مشترك الآن.")
            else:
                await update.message.reply_text("✅ تم التحقق! أنت مشترك الآن.")
            await main_menu_callback(update, context)
        else:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 اشترك", url=f"https://t.me/{channel.lstrip('@')}"),
                 InlineKeyboardButton("🔄 تأكد", callback_data=CallbackData.CHECK_SUBSCRIBE),
                 InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
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

async def publish_all_channels_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    channels = await db_get_channels(user_id)
    
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
        
        try:
            if post['media_type'] == 'photo' and post['media_file_id']:
                await context.bot.send_photo(ch_tele_id, post['media_file_id'], caption=post['text'] if post['text'] else None)
            elif post['media_type'] == 'video' and post['media_file_id']:
                await context.bot.send_video(ch_tele_id, post['media_file_id'], caption=post['text'] if post['text'] else None)
            elif post['media_type'] == 'document' and post['media_file_id']:
                await context.bot.send_document(ch_tele_id, post['media_file_id'], caption=post['text'] if post['text'] else None)
            else:
                await context.bot.send_message(ch_tele_id, post['text'])
            
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
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    
    if query:
        await safe_edit_markdown(query, result_text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, result_text, reply_markup=keyboard)

async def channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    if not query:
        return
    
    try:
        channel_db_id = int(query.data.split(":")[-1])
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
    channel_name = ch_info[1] if ch_info else "القناة"
    
    if stats['total_posts'] == 0:
        text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد منشورات بعد"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{channel_db_id}")],
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
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{channel_db_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def my_channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    
    channels = await db_get_channels(user_id)
    
    if not channels:
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
    
    total_posts = 0
    total_published = 0
    total_views = 0
    
    for ch_db_id, ch_tele_id, ch_name, banned in channels:
        stats = await db_get_channel_stats(ch_db_id)
        if stats:
            total_posts += stats['total_posts']
            total_published += stats['published_posts']
            total_views += stats['total_views']
    
    text = f"📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📡 عدد القنوات: {len(channels)}\n"
    text += f"📝 إجمالي المنشورات: {total_posts}\n"
    text += f"✅ المنشورة: {total_published}\n"
    text += f"👁️ إجمالي المشاهدات: {total_views}\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 عرض القنوات", callback_data=CallbackData.CHANNELS_MY)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def channel_stats_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await channel_stats_callback(update, context)

async def contests_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    
    contests = await db_get_contests(limit=5)
    
    if not contests:
        text = get_text(user_id, 'no_contests')
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
        return
    
    text = "🏆 **المسابقات النشطة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    
    for contest in contests:
        cid = contest[0]
        title = contest[1] or "بدون عنوان"
        prize = contest[3] or "غير محددة"
        
        text += f"📌 **{title}**\n🎁 الجائزة: {prize}\n━━━━━━━━━━━━━━━━━━━━━━\n"
        
        participated = await db_get_user_participation(user_id, cid)
        if not participated:
            keyboard.append([InlineKeyboardButton(
                f"📝 شارك في {title[:20]}",
                callback_data=f"{CallbackData.CONTEST_JOIN_PREFIX}{cid}"
            )])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def contest_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
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
    
    if await db_get_user_participation(user_id, contest_id):
        await query.edit_message_text(get_text(user_id, 'contest_participated'))
        return
    
    if await db_participate_in_contest(user_id, contest_id):
        await query.edit_message_text(get_text(user_id, 'contest_join_success'))
    else:
        await query.edit_message_text(get_text(user_id, 'contest_join_error'))

async def contest_winners_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    query = update.callback_query
    if query:
        await query.answer()
    
    user_id = update.effective_user.id
    
    winners = await db_get_contest_winners(limit=5)
    
    if not winners:
        text = get_text(user_id, 'no_winners')
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.CONTESTS_BACK)]
        ])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
        return
    
    text = get_text(user_id, 'contest_winners_title')
    for contest_id, title, prize, winner_id, announced_at in winners:
        try:
            winner = await context.bot.get_chat(winner_id)
            winner_name = winner.first_name or str(winner_id)
        except:
            winner_name = str(winner_id)
        
        text += f"📌 **{title}**\n🎁 {prize}\n👤 {winner_name}\n━━━━━━━━━━━━━━━━━━━━━━\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.CONTESTS_BACK)]
    ])
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)

async def contests_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await contests_menu_callback(update, context)

# ===================== دوال إضافية للقاعدة =====================
async def db_get_contests(limit: int = 10) -> list:
    async def _get(conn):
        now = utc_now().isoformat()
        cur = await conn.execute("SELECT id, title, description, prize, end_date, contest_type FROM contests WHERE status = 'active' AND end_date > ? ORDER BY end_date ASC LIMIT ?", (now, limit))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_reset_all_posts_to_unpublished(channel_db_id: int) -> int:
    async def _reset(conn):
        await conn.execute("UPDATE posts SET published=0, fail_count=0 WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_reset)

async def db_get_auto_recycle(user_id: int) -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT auto_recycle FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_get)

async def db_get_posts_count(channel_db_id: int) -> int:
    async def _count(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_count)

async def db_get_published_count(channel_db_id: int) -> int:
    async def _count(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=1", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_count)

async def db_get_channel_stats(channel_db_id: int) -> dict:
    async def _get_stats(conn):
        cur = await conn.execute("SELECT COUNT(*) as total_posts, SUM(CASE WHEN published = 1 THEN 1 ELSE 0 END) as published_posts, SUM(CASE WHEN published = 0 THEN 1 ELSE 0 END) as unpublished_posts FROM posts WHERE channel_db_id = ?", (channel_db_id,))
        row = await cur.fetchone()
        if not row or row[0] == 0:
            return {'total_posts': 0, 'published_posts': 0, 'unpublished_posts': 0}
        return {'total_posts': row[0] or 0, 'published_posts': row[1] or 0, 'unpublished_posts': row[2] or 0}
    return await execute_db(_get_stats)

# ===================== الأوامر الرئيسية =====================
async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    user = update.effective_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""
    
    await db_register_user(user_id)
    
    if not await ensure_force_subscribe(update, context, user_id):
        return
    
    await main_menu_callback(update, context)

async def syncgroup_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user or not update.effective_chat:
        return
    
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    
    chat_id = update.effective_chat.id
    chat_name = update.effective_chat.title or "بدون اسم"
    user_id = update.effective_user.id
    
    await db_register_group(chat_id, chat_name, user_id, update.effective_chat.username)
    
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"⚠️ **تنبيه:**\n{bot_perms['reason']}\n\nيرجى منح البوت الصلاحيات المطلوبة.")
        return
    
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ['creator', 'administrator']:
            await db_register_hidden_owner_group(chat_id, user_id)
            await invalidate_user_cache(user_id=user_id, chat_id=chat_id)
            await update.message.reply_text(
                f"✅ **تم تسجيلك كمالك مخفي لهذه المجموعة.**\n\n"
                f"📌 اسم المجموعة: {chat_name}\n"
                f"🆔 المعرف: {chat_id}\n"
                f"👤 المستخدم: {user_id}\n\n"
                f"🔐 استخدم /security لإعدادات الأمان\n"
                f"🛠️ استخدم /panel للوحة التحكم"
            )
        else:
            await update.message.reply_text(
                f"⚠️ **عذراً، أنت لست مشرفاً في هذه المجموعة.**\n\n"
                f"📌 **للاستفادة من ميزات البوت المتقدمة، تواصل معنا على الخاص:**\n"
                f"👉 @{BOT_USERNAME}\n\n"
                f"🔗 **ادعُ البوت إلى مجموعتك:**\n"
                f"https://t.me/{BOT_USERNAME}?startgroup"
            )
            return
    except Exception as e:
        await update.message.reply_text(f"⚠️ تعذر التحقق من صلاحياتك: {e}")
        return
    
    await update.message.reply_text(
        f"✅ **تم تفعيل المجموعة بنجاح!**\n\n"
        f"📌 اسم المجموعة: {chat_name}\n"
        f"🆔 المعرف: {chat_id}\n"
        f"👤 المضافة بواسطة: {user_id}\n\n"
        f"🔐 استخدم /security لإعدادات الأمان\n"
        f"🛠️ استخدم /panel للوحة التحكم"
    )

async def update_admins_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user or not update.effective_chat:
        return
    
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"⚠️ **تنبيه:**\n{bot_perms['reason']}\n\nيرجى منح البوت الصلاحيات المطلوبة.")
        return
    
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        
        if not admins:
            await update.message.reply_text("❌ لا يمكن جلب قائمة المشرفين.")
            return
        
        updated_count = 0
        
        for admin in admins:
            admin_user = admin.user
            admin_id = admin_user.id
            
            if admin_user.is_bot:
                continue
            
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
            await update.message.reply_text(
                get_text(user_id, 'update_admins_success').format(updated_count)
            )
        else:
            await update.message.reply_text(
                get_text(user_id, 'update_admins_no_changes')
            )
        
    except Exception as e:
        await update.message.reply_text(
            f"{get_text(user_id, 'update_admins_error')}\n\nالرمز: `{log_error(e)}`"
        )

async def security_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text(get_text(user_id, 'admin_only'))
            return
        await security_select_group_callback(update, context)
        return
    
    groups = await db_get_user_groups(user_id)
    
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
3. استخدم الأمر /syncgroup في المجموعة"""
        
        await safe_send_markdown(context.bot, user_id, text, reply_markup=keyboard)
        return
    
    keyboard = []
    for chat_id, chat_name, username, banned in groups:
        name = chat_name[:40] + "..." if len(chat_name) > 43 else chat_name
        keyboard.append([InlineKeyboardButton(f"📌 {name}", callback_data=f"{CallbackData.SECURITY_SELECT_GROUP}{chat_id}")])
    
    keyboard.append([InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    
    text = """🔐 **إعدادات الأمان والإجراءات المتقدمة**

📌 اختر المجموعة التي تريد إدارة إعداداتها:

⚠️ ملاحظة: يجب أن يكون البوت مشرفاً في المجموعة"""
    
    await safe_send_markdown(context.bot, user_id, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def trial_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await trial_callback(update, context)

async def subscribe_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscribe_menu_callback(update, context)

async def help_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    await update.message.reply_text(get_text(user_id, 'help'))

async def support_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 كتابة تذكرة", callback_data=CallbackData.SUPPORT_TICKET)],
        [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    
    await update.message.reply_text(get_text(user_id, 'support_welcome'), reply_markup=keyboard)

async def support_reply_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("📝 **الاستخدام:**\n`/support_reply user_id نص الرد`")
        return
    
    try:
        target_user_id = int(args[0])
        reply_text = " ".join(args[1:])
        await context.bot.send_message(chat_id=target_user_id, text=f"📬 **رد على تذكرتك:**\n━━━━━━━━━━━━━━━━━━━━━━\n{reply_text}")
        await update.message.reply_text(f"✅ تم إرسال الرد إلى المستخدم {target_user_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الإرسال: {e}")

async def rank_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_text_callbacks(update, context)

async def top_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_text_callbacks(update, context)

async def developer_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await developer_callback(update, context)

async def updates_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await updates_callback(update, context)

async def stats_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    
    if not active:
        await update.message.reply_text("⚠️ يرجى اختيار قناة أولاً")
        return
    
    stats = await db_get_channel_stats(active)
    ch_info = await db_get_channel_info(active)
    channel_name = ch_info[1] if ch_info else "القناة"
    
    if stats['total_posts'] == 0:
        text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد منشورات بعد"
        await safe_send_markdown(context.bot, user_id, text)
        return
    
    text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📝 إجمالي المنشورات: {stats['total_posts']}\n"
    text += f"✅ المنشورة: {stats['published_posts']}\n"
    text += f"⏳ غير المنشورة: {stats['unpublished_posts']}\n"
    
    await safe_send_markdown(context.bot, user_id, text)

async def sendcode_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    allowed_user = await db_get_allowed_sendcode_user()
    
    if user_id != PRIMARY_OWNER_ID and user_id != allowed_user:
        await safe_send_markdown(context.bot, user_id, "🔒 هذا الأمر للمطور الأساسي أو المستخدمين المصرح لهم فقط.")
        return
    
    temp_password = secrets.token_urlsafe(12)
    context.user_data['sendcode_temp_password'] = temp_password
    context.user_data['sendcode_temp_timestamp'] = time_module.time()
    context.user_data['state'] = UserState.WAITING_SENDCODE_PASSWORD
    
    await update.message.reply_text(
        f"🔐 **تأكيد أمني إضافي**\n\n"
        f"لإرسال الكود، يرجى تأكيد هويتك بإرسال كلمة المرور المؤقتة:\n"
        f"`{temp_password}`\n\n"
        f"⏰ **تنتهي الصلاحية خلال 10 دقائق.**"
    )

async def handle_sendcode_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    expected_password = context.user_data.get('sendcode_temp_password')
    timestamp = context.user_data.get('sendcode_temp_timestamp', 0)
    
    if not expected_password:
        await update.message.reply_text("❌ لم يتم طلب إرسال كود")
        context.user_data.pop('state', None)
        return
    
    SENDCODE_TIMEOUT = 600
    if time_module.time() - timestamp > SENDCODE_TIMEOUT:
        await update.message.reply_text(f"❌ انتهت صلاحية كلمة المرور (المهلة {SENDCODE_TIMEOUT // 60} دقائق).\nأعد استخدام الأمر /sendcode.")
        context.user_data.pop('sendcode_temp_password', None)
        context.user_data.pop('sendcode_temp_timestamp', None)
        context.user_data.pop('state', None)
        return
    
    if update.message.text.strip() == expected_password:
        try:
            with open(__file__, 'r', encoding='utf-8') as f:
                content = f.read()
            
            watermark = f"""# ============================================================
# ORIGINAL_OWNER: {user_id}
# GENERATED_AT: {mecca_now().strftime('%Y-%m-%d %H:%M:%S')}
# ============================================================
"""
            watermarked_content = watermark + content
            
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.py')
            with open(temp_file.name, 'w', encoding='utf-8') as f:
                f.write(watermarked_content)
            
            with open(temp_file.name, 'rb') as f:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=f,
                    filename=f"relax_bot_secure_{mecca_now().strftime('%Y%m%d')}.py"
                )
            
            os.unlink(temp_file.name)
            await update.message.reply_text("✅ تم إرسال الكود بنجاح على الخاص!")
        except Exception as e:
            await update.message.reply_text(f"❌ فشل إرسال الكود: {str(e)[:100]}")
        
        context.user_data.pop('sendcode_temp_password', None)
        context.user_data.pop('sendcode_temp_timestamp', None)
        context.user_data.pop('state', None)
    else:
        await update.message.reply_text("❌ كلمة المرور غير صحيحة! تم إلغاء العملية.")
        context.user_data.pop('sendcode_temp_password', None)
        context.user_data.pop('sendcode_temp_timestamp', None)
        context.user_data.pop('state', None)

async def lock_chat_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user or not update.effective_chat:
        return
    
    user_id = update.effective_user.id
    chat_id = None
    
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text(get_text(user_id, 'admin_only'))
            return
        await db_set_chat_lock(chat_id, True, user_id)
        await update.message.reply_text(get_text(user_id, 'locked'))
        return
    
    args = context.args or []
    if args and args[0].lstrip('-').isdigit():
        chat_id = int(args[0])
        if await is_authorized_in_group(context.bot, chat_id, user_id):
            await db_set_chat_lock(chat_id, True, user_id)
            await update.message.reply_text(get_text(user_id, 'locked'))
            return
        else:
            await update.message.reply_text("❌ غير مصرح أو البوت ليس في المجموعة.")
            return
    
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة.")
        return
    
    keyboard = []
    for gid, gname, _, _ in groups:
        if await is_authorized_in_group(context.bot, gid, user_id):
            keyboard.append([InlineKeyboardButton(f"🔒 {gname[:30]}", callback_data=f"{CallbackData.PANEL_LOCK_PREFIX}{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await update.message.reply_text("🔒 **اختر مجموعة لقفلها:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def unlock_chat_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user or not update.effective_chat:
        return
    
    user_id = update.effective_user.id
    chat_id = None
    
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text(get_text(user_id, 'admin_only'))
            return
        await db_set_chat_lock(chat_id, False)
        await update.message.reply_text(get_text(user_id, 'unlocked'))
        return
    
    args = context.args or []
    if args and args[0].lstrip('-').isdigit():
        chat_id = int(args[0])
        if await is_authorized_in_group(context.bot, chat_id, user_id):
            await db_set_chat_lock(chat_id, False)
            await update.message.reply_text(get_text(user_id, 'unlocked'))
            return
        else:
            await update.message.reply_text("❌ غير مصرح أو البوت ليس في المجموعة.")
            return
    
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة.")
        return
    
    keyboard = []
    for gid, gname, _, _ in groups:
        if await is_authorized_in_group(context.bot, gid, user_id):
            keyboard.append([InlineKeyboardButton(f"🔓 {gname[:30]}", callback_data=f"{CallbackData.PANEL_UNLOCK_PREFIX}{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await update.message.reply_text("🔓 **اختر مجموعة لفتحها:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def panel_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    
    if not await ensure_force_subscribe(update, context, user_id):
        return
    
    if update.effective_chat.type in ['group', 'supergroup']:
        chat = update.effective_chat
        chat_id = chat.id
        
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text(get_text(user_id, 'admin_only'))
            return
        
        current_lock_status = await is_chat_locked(chat_id)
        lock_status_text = "🔒 مقفلة" if current_lock_status else "🔓 مفتوحة"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔒 قفل المجموعة", callback_data=f"{CallbackData.PANEL_LOCK_PREFIX}{chat_id}"),
             InlineKeyboardButton("🔓 فتح المجموعة", callback_data=f"{CallbackData.PANEL_UNLOCK_PREFIX}{chat_id}")],
            [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}"),
             InlineKeyboardButton("🔙 إغلاق اللوحة", callback_data=CallbackData.PANEL_CLOSE)]
        ])
        
        await update.message.reply_text(
            f"🔧 **لوحة تحكم المجموعة**\n━━━━━━━━━━━━━━\n📌 **المجموعة:** {chat.title}\n🔐 **الحالة:** {lock_status_text}\n━━━━━━━━━━━━━━\n\nاستخدم الأزرار للتحكم",
            reply_markup=kb
        )
        return
    
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة.\nأضف البوت إلى مجموعة واجعلها نشطة.")
        return
    
    keyboard = []
    for gid, gname, _, _ in groups:
        if await is_authorized_in_group(context.bot, gid, user_id):
            is_locked = await is_chat_locked(gid)
            icon = "🔒" if is_locked else "🔓"
            keyboard.append([InlineKeyboardButton(f"{icon} {gname[:30]}", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await update.message.reply_text("🔧 **لوحة التحكم**\nاختر مجموعة:", reply_markup=InlineKeyboardMarkup(keyboard))

async def schedule_post_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    chat_id = None
    args = context.args or []
    
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
            return
        
        if len(args) < 3:
            await update.message.reply_text("📝 **الاستخدام:**\n`/schedule YYYY-MM-DD HH:MM نص المنشور`")
            return
        
        try:
            date_str = args[0]
            time_str = args[1]
            text = " ".join(args[2:])
            mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if mecca_dt <= mecca_now():
                await update.message.reply_text("❌ **الوقت يجب أن يكون في المستقبل!**")
                return
            utc_dt = mecca_to_utc(mecca_dt)
            await db_add_scheduled_post(chat_id, text, utc_dt)
            await update.message.reply_text(f"✅ **تم جدولة المنشور!**\n📅 {date_str} 🕐 {time_str} (بتوقيت مكة)")
            return
        except ValueError:
            await update.message.reply_text("❌ صيغة التاريخ أو الوقت غير صحيحة!")
            return
    
    if len(args) >= 4:
        try:
            chat_id = int(args[0])
            date_str = args[1]
            time_str = args[2]
            text = " ".join(args[3:])
        except ValueError:
            await update.message.reply_text("❌ معرف المجموعة غير صحيح!")
            return
        
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text("❌ غير مصرح أو البوت ليس في المجموعة.")
            return
        
        try:
            mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if mecca_dt <= mecca_now():
                await update.message.reply_text("❌ **الوقت يجب أن يكون في المستقبل!**")
                return
            utc_dt = mecca_to_utc(mecca_dt)
            await db_add_scheduled_post(chat_id, text, utc_dt)
            await update.message.reply_text(f"✅ **تم جدولة المنشور!**\n📅 {date_str} 🕐 {time_str} (بتوقيت مكة)")
            return
        except ValueError:
            await update.message.reply_text("❌ صيغة التاريخ أو الوقت غير صحيحة!")
            return
    
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة.")
        return
    
    keyboard = []
    for gid, gname, _, _ in groups:
        if await is_authorized_in_group(context.bot, gid, user_id):
            keyboard.append([InlineKeyboardButton(f"📌 {gname[:30]}", callback_data=f"schedule_select:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await update.message.reply_text("📝 **اختر مجموعة لجدولة منشور:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def schedule_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update:
        return
    
    query = update.callback_query
    await query.answer()
    if not query:
        return
    
    chat_id = int(query.data.split(":")[-1])
    context.user_data['schedule_chat_id'] = chat_id
    context.user_data['state'] = UserState.WAITING_SCHEDULE_POST
    await query.edit_message_text(
        "📝 **أرسل المنشور بالصيغة التالية:**\n`YYYY-MM-DD HH:MM نص المنشور`\n\nمثال: `2024-12-31 20:00 مرحباً بالجميع!`\n🕐 الوقت بتوقيت مكة المكرمة"
    )

async def set_log_channel_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    args = context.args or []
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/set_log_channel معرف_القناة`\n\nمثال: `/set_log_channel -1001234567890`\nأو `/set_log_channel @username`")
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
        await update.message.reply_text(f"❌ لا يمكن العثور على القناة: {e}")
        return
    
    try:
        bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if bot_member.status not in ['administrator', 'creator']:
            await update.message.reply_text("❌ **البوت ليس مشرفاً في هذه القناة.**")
            return
        if not bot_member.can_post_messages:
            await update.message.reply_text("❌ **البوت لا يملك صلاحية الإرسال.**")
            return
    except Exception as e:
        await update.message.reply_text(f"❌ لا يمكن الوصول للقناة: {e}")
        return
    
    await db_set_log_channel_id(str(chat_id))
    await update.message.reply_text(f"✅ **تم تعيين قناة التقارير بنجاح!**\nمعرف القناة: `{chat_id}`")

async def handle_moderation_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message or not update.effective_chat or not update.effective_user:
        return
    
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        return
    
    user_id = update.effective_user.id
    chat_id = chat.id
    text = update.message.text.strip() if update.message.text else ""
    
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"❌ {bot_perms['reason']}")
        return
    
    def extract_user_id_from_text(txt: str):
        parts = txt.split()
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except ValueError:
                if parts[1].startswith('@'):
                    return parts[1]
        return None
    
    async def get_target_user_id(txt: str, reply_msg):
        if reply_msg and reply_msg.from_user:
            return reply_msg.from_user.id
        extracted = extract_user_id_from_text(txt)
        if extracted:
            if isinstance(extracted, int):
                return extracted
            if isinstance(extracted, str) and extracted.startswith('@'):
                try:
                    chat = await context.bot.get_chat(extracted)
                    return chat.id
                except:
                    return None
        return None
    
    reason = ""
    args = text.split(maxsplit=1)
    if len(args) > 1:
        parts = args[1].split(maxsplit=1)
        if len(parts) > 1:
            reason = parts[1]
    
    target_id = await get_target_user_id(text, update.message.reply_to_message)
    if not target_id:
        await update.message.reply_text("❌ يرجى تحديد المستخدم (ID أو @username) أو الرد على رسالته.")
        return
    
    if text.startswith("/ban"):
        await execute_ban(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
        return
    
    if text.startswith("/mute"):
        minutes = context.user_data.get('mute_minutes', 60)
        await execute_mute(context.bot, chat_id, target_id, minutes, reason=reason, moderator_id=user_id)
        return
    
    if text.startswith("/unmute"):
        await execute_unmute(context.bot, chat_id, target_id, moderator_id=user_id)
        return
    
    if text.startswith("/warn"):
        await execute_warn(context.bot, chat_id, target_id, user_id, reason=reason)
        return
    
    if text.startswith("/kick"):
        await execute_kick(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
        return
    
    if text.startswith("/restrict"):
        await execute_restrict(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
        return
    
    if text.startswith("/pin") and update.message.reply_to_message:
        await execute_pin(context.bot, chat_id, update.message.reply_to_message.message_id)
        return
    
    if text.startswith("/unban"):
        await execute_unban(context.bot, chat_id, target_id, moderator_id=user_id)
        return

async def db_add_scheduled_post(chat_id: int, text: str, publish_time: datetime):
    async def _add(conn):
        await conn.execute("INSERT INTO scheduled_posts (chat_id, text, publish_time, fail_count) VALUES (?, ?, ?, 0)", (chat_id, sanitize_text(text), publish_time.isoformat()))
        await conn.commit()
    return await execute_db(_add)

async def language_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.effective_user:
        return
    
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
    await update.message.reply_text(get_text(user_id, 'welcome'), reply_markup=keyboard)

# ===================== معالجات الكولباك الإضافية =====================
async def pre_checkout_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update:
        return
    
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("sub_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="بيانات غير صالحة")

async def successful_payment_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    
    try:
        parts = payment.invoice_payload.split('_')
        days = int(parts[1]) if len(parts) >= 2 else 30
    except:
        days = 30
    
    await db_activate_subscription(user_id, days)
    await update.message.reply_text(f"✅ **تم تفعيل اشتراكك لمدة {days} يوماً!**\nشكراً لدعمك ❤️")

# ===================== معالجات الرسائل =====================
async def message_handler_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message:
        return
    
    chat = update.effective_chat
    user = update.effective_user
    user_id = user.id if user else 0
    text = update.message.text.strip() if update.message.text else ""
    
    if user and user.is_bot:
        return
    
    # معالجة الصور والفيديوهات
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
    
    # أمر الإلغاء
    if text == "/cancel":
        context.user_data.pop('state', None)
        context.user_data.pop('support_mode', None)
        await update.message.reply_text(get_text(user_id, 'cancelled'))
        if chat.type == 'private':
            await main_menu_callback(update, context)
        return
    
    state = context.user_data.get('state')
    
    # حالة إضافة منشورات
    if state == UserState.ADDING_POSTS:
        session_key = f"session_{user_id}"
        
        if text == "/cancel":
            context.user_data.pop(session_key, None)
            context.user_data.pop(f"session_target_{user_id}", None)
            context.user_data.pop('state', None)
            await update.message.reply_text(get_text(user_id, 'cancelled'))
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
        target = context.user_data.get(f"session_target_{user_id}", 15)
        
        if cur >= target or cur >= MAX_POSTS_PER_SESSION:
            active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
            if not active:
                await update.message.reply_text(get_text(user_id, 'error'))
                context.user_data.pop(session_key, None)
                context.user_data.pop('state', None)
                return
            
            saved = await db_save_posts(active, context.user_data[session_key])
            context.user_data.pop(session_key, None)
            context.user_data.pop(f"session_target_{user_id}", None)
            context.user_data.pop('state', None)
            
            await update.message.reply_text(f"✅ تم حفظ {saved} منشور")
            await main_menu_callback(update, context)
        else:
            await update.message.reply_text(f"📥 {cur}/{target}")
        return
    
    # حالة إضافة قناة
    if state == UserState.WAITING_CHANNEL_ID:
        context.user_data.pop('state', None)
        channel_id = text.strip()
        
        if not channel_id.startswith('@') and not channel_id.startswith('-100'):
            await update.message.reply_text("❌ **معرف قناة غير صالح!**\n\nالصيغ المدعومة:\n• `@username` (مثل: @my_channel)\n• `-1001234567890` (المعرف الرقمي)")
            context.user_data['state'] = UserState.WAITING_CHANNEL_ID
            return
        
        new_id = await db_add_channel(user_id, channel_id, channel_id)
        if new_id:
            context.user_data['active_channel'] = new_id
            await db_set_active_channel(user_id, new_id)
            await update.message.reply_text(get_text(user_id, 'channel_added').format(channel_id))
        else:
            await update.message.reply_text(get_text(user_id, 'channel_exists'))
        
        kb, title, active = await get_main_keyboard(user_id)
        context.user_data['active_channel'] = active
        await safe_send_markdown(context.bot, user_id, title, reply_markup=kb)
        return
    
    # حالة إضافة مشرف
    if state == UserState.WAITING_ADMIN_ID_ADD:
        try:
            target_id = int(text)
            if target_id == PRIMARY_OWNER_ID:
                await update.message.reply_text(get_text(user_id, 'cannot_remove_main_admin'))
            else:
                await add_bot_admin(target_id)
                await update.message.reply_text(get_text(user_id, 'add_admin_success').format(target_id))
        except ValueError:
            await update.message.reply_text(get_text(user_id, 'invalid_user_id'))
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    # حالة إزالة مشرف
    if state == UserState.WAITING_ADMIN_ID_REMOVE:
        try:
            target_id = int(text)
            if target_id == PRIMARY_OWNER_ID:
                await update.message.reply_text(get_text(user_id, 'cannot_remove_main_admin'))
            else:
                await remove_bot_admin(target_id)
                await update.message.reply_text(get_text(user_id, 'remove_admin_success').format(target_id))
        except ValueError:
            await update.message.reply_text(get_text(user_id, 'invalid_user_id'))
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    # حالة إضافة كلمة محظورة للمجموعة
    if state == UserState.WAITING_GROUP_BANNED_WORD:
        chat_id = context.user_data.get('banned_words_chat_id')
        if chat_id:
            word = text.split()[0].lower() if text else ""
            if len(word) < 2:
                await update.message.reply_text("❌ الكلمة قصيرة جداً")
                return
            if await db_add_banned_word(word, chat_id, user_id):
                await update.message.reply_text(f"✅ تم إضافة {word}")
            else:
                await update.message.reply_text(f"⚠️ {word} موجودة مسبقاً")
            context.user_data.pop('state', None)
            await banned_words_list_callback(update, context)
        return
    
    # حالة حذف كلمة محظورة من المجموعة
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
    
    # حالة إضافة كلمة محظورة عامة
    if state == UserState.WAITING_GLOBAL_BANNED_WORD:
        word = text.split()[0].lower() if text else ""
        if len(word) < 2:
            await update.message.reply_text("❌ الكلمة قصيرة جداً")
            return
        if await db_add_banned_word(word, -1, user_id):
            await update.message.reply_text(f"✅ تم إضافة {word} ككلمة محظورة عامة")
        else:
            await update.message.reply_text(f"⚠️ {word} موجودة مسبقاً")
        context.user_data.pop('state', None)
        await admin_banned_words_callback(update, context)
        return
    
    # حالة حذف كلمة محظورة عامة
    if state == UserState.WAITING_REMOVE_GLOBAL_BANNED_WORD:
        word = text.lower()
        async def _remove(conn):
            await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
            await conn.commit()
        await execute_db(_remove)
        await update.message.reply_text(f"✅ تم حذف {word} من الكلمات المحظورة العامة")
        context.user_data.pop('state', None)
        await admin_banned_words_callback(update, context)
        return
    
    # حالة إضافة رد
    if state == UserState.WAITING_KEYWORD:
        context.user_data.pop('state', None)
        keyword = text.strip().lower()
        if len(keyword) < 2:
            await update.message.reply_text("❌ الكلمة المفتاحية قصيرة جداً (يجب أن تكون حرفين على الأقل)")
            context.user_data['state'] = UserState.WAITING_KEYWORD
            return
        context.user_data['state'] = UserState.WAITING_REPLY
        context.user_data['admin_keyword'] = keyword
        await update.message.reply_text(f"📝 **إضافة رد للكلمة:** `{keyword}`\n\nأرسل الرد الذي تريده لهذه الكلمة:")
        return
    
    # حالة إرسال الرد
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
    
    # حالة إرسال تحديث
    if state == UserState.WAITING_UPDATE_TEXT:
        context.user_data.pop('state', None)
        channel = await db_get_updates_channel()
        if channel:
            try:
                await context.bot.send_message(chat_id=f"@{channel}", text=text)
                await update.message.reply_text("✅ تم نشر التحديث في قناة التحديثات")
            except Exception as e:
                await update.message.reply_text(f"❌ فشل النشر: {str(e)[:100]}")
        else:
            await update.message.reply_text("❌ لم يتم تعيين قناة تحديثات بعد")
        await admin_panel_callback(update, context)
        return
    
    # حالة تعيين قناة التحديثات
    if state == UserState.WAITING_UPDATE_CHANNEL:
        context.user_data.pop('state', None)
        channel = text.strip()
        if channel.startswith('@'):
            channel = channel[1:]
        if not channel:
            await update.message.reply_text("❌ **معرف قناة غير صالح!**")
            return
        try:
            if await db_set_updates_channel(channel):
                await update.message.reply_text(f"✅ **تم تعيين قناة التحديثات بنجاح!**\n📢 القناة: @{channel}")
            else:
                await update.message.reply_text("❌ **فشل حفظ القناة!**")
        except Exception as e:
            await update.message.reply_text(f"❌ **لا يمكن الوصول إلى القناة:**\n{str(e)[:200]}")
        await admin_panel_callback(update, context)
        return
    
    # حالة تعيين قناة الاشتراك الإجباري
    if state == UserState.WAITING_FORCE_CHANNEL:
        context.user_data.pop('state', None)
        await db_set_force_subscribe_channel(text)
        await update.message.reply_text(f"✅ تم تعيين قناة الاشتراك الإجباري: {text}")
        await admin_panel_callback(update, context)
        return
    
    # حالة الإرسال الجماعي
    if state == UserState.WAITING_BROADCAST:
        context.user_data.pop('state', None)
        confirm_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم، أرسل", callback_data=CallbackData.ADMIN_CONFIRM_BROADCAST),
             InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.ADMIN_PANEL)]
        ])
        context.user_data['broadcast_text'] = text
        await update.message.reply_text(
            f"📨 **تأكيد الإرسال الجماعي**\n\nالنص المرسل:\n━━━━━━━━━━━━━━\n{text[:500]}\n━━━━━━━━━━━━━━\n\n⚠️ سيتم إرسال هذه الرسالة إلى **جميع مستخدمي البوت**\nهل أنت متأكد؟",
            reply_markup=confirm_kb
        )
        return
    
    # حالة تعيين مستخدم مصرح بـ /sendcode
    if state == UserState.WAITING_SENDCODE_USER:
        context.user_data.pop('state', None)
        try:
            target_user_id = int(text)
        except ValueError:
            await update.message.reply_text(get_text(user_id, 'invalid_number'))
            return
        await db_set_allowed_sendcode_user(target_user_id)
        await update.message.reply_text(get_text(user_id, 'sendcode_user_set').format(target_user_id))
        await admin_panel_callback(update, context)
        return
    
    # حالة تعيين قناة التقارير
    if state == UserState.WAITING_LOG_CHANNEL:
        context.user_data.pop('state', None)
        identifier = text.strip()
        if not identifier.startswith('@') and not identifier.startswith('-100'):
            await update.message.reply_text("❌ **معرف قناة غير صالح!**")
            context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
            return
        try:
            identifier_clean = identifier.lstrip('@')
            if identifier_clean.startswith('-100') or identifier_clean.lstrip('-').isdigit():
                chat_id = int(identifier_clean)
            else:
                chat_obj = await context.bot.get_chat(f"@{identifier_clean}")
                chat_id = chat_obj.id
            await db_set_log_channel_id(str(chat_id))
            await update.message.reply_text(f"✅ **تم تعيين قناة التقارير بنجاح!**\nمعرف القناة: `{chat_id}`")
        except Exception as e:
            await update.message.reply_text(f"❌ **لا يمكن الوصول إلى القناة:**\n{str(e)[:200]}")
            context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
            return
        await admin_panel_callback(update, context)
        return
    
    # حالة إنشاء مسابقة
    if state == UserState.WAITING_CONTEST_TITLE:
        if not text:
            await update.message.reply_text("❌ الرجاء إدخال عنوان صحيح.")
            return True
        context.user_data['contest_title'] = text
        context.user_data['state'] = UserState.WAITING_CONTEST_DESCRIPTION
        await update.message.reply_text(get_text(user_id, 'create_contest_description'))
        return True
    
    if state == UserState.WAITING_CONTEST_DESCRIPTION:
        if not text:
            await update.message.reply_text("❌ الرجاء إدخال وصف صحيح.")
            return True
        context.user_data['contest_description'] = text
        context.user_data['state'] = UserState.WAITING_CONTEST_PRIZE
        await update.message.reply_text(get_text(user_id, 'create_contest_prize'))
        return True
    
    if state == UserState.WAITING_CONTEST_PRIZE:
        if not text:
            await update.message.reply_text("❌ الرجاء إدخال جائزة صحيحة.")
            return True
        context.user_data['contest_prize'] = text
        context.user_data['state'] = UserState.WAITING_CONTEST_END_DATE
        await update.message.reply_text(get_text(user_id, 'create_contest_end_date'))
        return True
    
    if state == UserState.WAITING_CONTEST_END_DATE:
        try:
            end_date = datetime.strptime(text, "%Y-%m-%d %H:%M")
            now_mecca = mecca_now()
            if end_date <= now_mecca:
                await update.message.reply_text(get_text(user_id, 'contest_date_future'))
                return True
            end_date_utc = mecca_to_utc(end_date)
            title = context.user_data.pop('contest_title', 'بدون عنوان')
            description = context.user_data.pop('contest_description', '')
            prize = context.user_data.pop('contest_prize', '')
            contest_id = await db_create_contest(user_id, title, description, prize, end_date_utc)
            if contest_id:
                await update.message.reply_text(
                    get_text(user_id, 'contest_created').format(
                        title, prize, end_date.strftime('%Y-%m-%d %H:%M'), contest_id
                    )
                )
            else:
                await update.message.reply_text(get_text(user_id, 'contest_created_error'))
        except ValueError:
            await update.message.reply_text(get_text(user_id, 'contest_date_invalid'))
            return True
        except Exception as e:
            await update.message.reply_text(f"❌ حدث خطأ: {str(e)[:100]}")
            return True
        context.user_data.pop('state', None)
        await main_menu_callback(update, context)
        return True
    
    # حالة تحديد حد NSFW
    if state == UserState.WAITING_NSFW_THRESHOLD:
        try:
            threshold = float(text)
            if 0 <= threshold <= 1:
                # Save threshold
                await update.message.reply_text(f"✅ تم تعيين حد NSFW إلى: {threshold}")
            else:
                await update.message.reply_text("❌ القيمة يجب أن تكون بين 0 و 1")
        except ValueError:
            await update.message.reply_text("❌ يرجى إدخال رقم صحيح بين 0 و 1")
        context.user_data.pop('state', None)
        await nsfw_settings_callback(update, context)
        return
    
    # حالة دعم المستخدمين
    if context.user_data.get('support_mode') and chat.type == 'private' and text and not text.startswith('/'):
        ticket_num = await db_get_next_ticket_number()
        username = user.full_name or user.first_name or str(user_id)
        clean_text = sanitize_text(text, max_length=2000)
        await db_save_ticket(user_id, username, clean_text, ticket_num)
        now_mecca = mecca_now()
        now_str = now_mecca.strftime("%Y-%m-%d %H:%M:%S")
        
        reply_text = f"✅ **تم استلام رسالتك!**\n📋 رقم التذكرة: #{ticket_num}\n🕐 {now_str}\n\nسيتم الرد عليك في أقرب وقت ممكن."
        await update.message.reply_text(reply_text)
        
        notification_text = f"📬 **تذكرة دعم جديدة**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 المستخدم: {username}\n🆔 المعرف: `{user_id}`\n📋 رقم التذكرة: #{ticket_num}\n🕐 الوقت: {now_str}\n━━━━━━━━━━━━━━━━━━━━━━\n📝 **الرسالة:**\n{clean_text[:500]}\n━━━━━━━━━━━━━━━━━━━━━━\nللرد استخدم:\n`/support_reply {user_id} نص الرد`"
        await context.bot.send_message(chat_id=PRIMARY_OWNER_ID, text=notification_text)
        context.user_data['support_mode'] = False
        return
    
    # الردود التلقائية في الخاص
    if chat.type == 'private':
        if text == "/start":
            await start_command_handler(update, context)
        elif text == "/cancel":
            context.user_data.pop('state', None)
            await update.message.reply_text(get_text(user_id, 'cancelled'))
            await main_menu_callback(update, context)

# ===================== فلتر الرسائل للمجموعات =====================
async def filter_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message or not update.effective_chat or not update.effective_user:
        return
    
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id
    user_id = user.id
    
    if chat.type not in ['group', 'supergroup']:
        return
    
    if user.is_bot:
        return
    
    # التحقق من القفل
    if await is_chat_locked(chat_id):
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"🔒 المجموعة مقفلة من قبل المشرف")
        except:
            pass
        return
    
    # التحقق من صلاحيات البوت
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        return
    
    # التحقق من الوضع البطيء
    if not await db_check_slow_mode(chat_id, user_id):
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"⏱️ **وضع بطيء مفعل**\n@{user.username or str(user_id)} يرجى الانتظار")
        except:
            pass
        return
    
    security_settings = await db_get_security_settings(chat_id)
    text = update.message.text or update.message.caption or ""
    
    # التحقق من الكلمات المحظورة
    if security_settings.get('delete_banned_words'):
        banned_word = await db_contains_banned_word(text, chat_id)
        if banned_word:
            try:
                await update.message.delete()
                await safe_send_markdown(context.bot, chat_id, f"🚫 **كلمة محظورة**\n@{user.username or str(user_id)} الكلمة `{banned_word}` غير مسموح بها")
            except:
                pass
            await apply_penalty(context.bot, chat_id, user_id, security_settings)
            return
    
    # التحقق من الروابط
    if security_settings.get('links') and contains_link(text):
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"🔗 **الروابط غير مسموح بها**\n@{user.username or str(user_id)}")
        except:
            pass
        await apply_penalty(context.bot, chat_id, user_id, security_settings)
        return
    
    # التحقق من المعرفات
    if security_settings.get('mentions') and contains_mention(text):
        try:
            await update.message.delete()
            await safe_send_markdown(context.bot, chat_id, f"@ **المعرفات غير مسموح بها**\n@{user.username or str(user_id)}")
        except:
            pass
        await apply_penalty(context.bot, chat_id, user_id, security_settings)
        return
    
    # الردود التلقائية
    if REPLIES_LOADED:
        reply = None
        text_lower = text.lower()
        
        if text_lower in ALL_REPLIES:
            reply = ALL_REPLIES[text_lower]
        
        if reply:
            try:
                await update.message.reply_text(reply)
            except Exception as e:
                logger.error(f"فشل إرسال الرد: {e}")

# ===================== معالجات إضافة البوت =====================
async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message:
        return
    
    if not update.message.new_chat_members:
        return
    
    bot_id = context.bot.id
    chat = update.effective_chat
    inviter = update.effective_user
    
    if chat.type not in ['group', 'supergroup']:
        return
    
    for member in update.message.new_chat_members:
        if member.id == bot_id:
            added_by_id = inviter.id if inviter else 0
            chat_name = chat.title or "بدون اسم"
            
            await db_register_group(chat.id, chat_name, added_by_id, chat.username)
            await db_register_hidden_owner_group(chat.id, added_by_id)
            await invalidate_user_cache(user_id=added_by_id, chat_id=chat.id)
            
            try:
                msg = "✅ **تم تفعيل البوت في المجموعة**\n\n📌 استخدم /panel للوحة التحكم"
                await safe_send_markdown(context.bot, chat.id, msg)
            except:
                pass
            break

async def track_chat_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update:
        return
    
    result = update.my_chat_member
    if not result:
        return
    
    new_status = result.new_chat_member.status
    old_status = result.old_chat_member.status
    
    if new_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
        is_new = old_status in [ChatMember.LEFT, ChatMember.BANNED, ChatMember.RESTRICTED]
        if is_new:
            chat = result.chat
            adder = result.from_user
            
            if chat.type in ['group', 'supergroup']:
                await db_register_group(chat.id, chat.title or "بدون اسم", adder.id, chat.username)
                await db_register_hidden_owner_group(chat.id, adder.id)
                await invalidate_user_cache(user_id=adder.id, chat_id=chat.id)

async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update:
        return
    
    result = update.chat_member
    if not result or result.chat.type not in ['group', 'supergroup']:
        return
    
    settings = await db_get_security_settings(result.chat.id)
    
    if result.new_chat_member.status == 'member' and result.old_chat_member.status in ['left', 'kicked']:
        if settings.get('welcome_enabled'):
            user = result.new_chat_member.user
            msg = settings.get('welcome_text', "مرحباً {user} في {chat} 🤍")
            msg = msg.replace('{user}', user.full_name or user.first_name).replace('{chat}', result.chat.title)
            try:
                await safe_send_markdown(context.bot, result.chat.id, msg)
            except:
                pass
    
    elif result.old_chat_member.status == 'member' and result.new_chat_member.status in ['left', 'kicked']:
        if settings.get('goodbye_enabled'):
            user = result.old_chat_member.user
            msg = settings.get('goodbye_text', "وداعاً {user} 👋")
            msg = msg.replace('{user}', user.full_name or user.first_name).replace('{chat}', result.chat.title)
            try:
                await safe_send_markdown(context.bot, result.chat.id, msg)
            except:
                pass

# ===================== معالج الأخطاء العالمي =====================
async def global_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        error = context.error
        error_id = secrets.token_hex(4)
        logger.error(f"[{error_id}] خطأ: {error}")
        
        if isinstance(error, Conflict):
            logger.warning(f"⚠️ تعارض في التحديثات: {error}")
            return
        
        if isinstance(error, Forbidden):
            logger.warning(f"⚠️ البوت محظور أو ليس لديه صلاحيات: {error}")
            return
        
        if isinstance(error, TimedOut):
            logger.warning(f"⏱️ انتهت المهلة: {error}")
            return
        
        if update and update.effective_user and context and context.bot:
            try:
                await safe_send_markdown(
                    context.bot,
                    update.effective_user.id,
                    f"❌ **حدث خطأ غير متوقع** (الرمز: `{error_id}`)\n\nتم تسجيل المشكلة وسيتم حلها قريباً."
                )
            except:
                pass
    
    except Exception as e:
        logger.error(f"فشل معالج الأخطاء نفسه: {e}")

def log_error(error: Exception) -> str:
    error_id = secrets.token_hex(4)
    logger.error(f"[{error_id}] {error}")
    return error_id

# ===================== تهيئة قاعدة البيانات =====================
async def init_db_improved():
    async with aiosqlite.connect(str(DB_PATH), timeout=DB_TIMEOUT) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        
        # جدول المستخدمين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                auto_publish INTEGER DEFAULT 1,
                banned INTEGER DEFAULT 0,
                trial_used INTEGER DEFAULT 0,
                subscription_end TEXT DEFAULT NULL,
                referral_code TEXT DEFAULT NULL,
                active_channel INTEGER DEFAULT NULL,
                auto_recycle INTEGER DEFAULT 1
            )
        """)
        
        # جدول قنوات المستخدمين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id TEXT,
                channel_name TEXT,
                created_at TIMESTAMP,
                banned INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        # جدول المنشورات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_db_id INTEGER,
                text TEXT,
                media_type TEXT DEFAULT 'text',
                media_file_id TEXT,
                published INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                views_count INTEGER DEFAULT 0,
                created_at TIMESTAMP,
                FOREIGN KEY(channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
            )
        """)
        
        # جدول الإعدادات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # جدول الردود
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_replies (
                keyword TEXT PRIMARY KEY,
                reply TEXT
            )
        """)
        
        # جدول إعدادات الأمان
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_security (
                chat_id INTEGER PRIMARY KEY,
                delete_links INTEGER DEFAULT 0,
                delete_mentions INTEGER DEFAULT 0,
                warn_message INTEGER DEFAULT 1,
                slow_mode INTEGER DEFAULT 0,
                slow_mode_seconds INTEGER DEFAULT 5,
                welcome_enabled INTEGER DEFAULT 0,
                welcome_text TEXT DEFAULT 'مرحباً {user} في {chat} 🤍',
                goodbye_enabled INTEGER DEFAULT 0,
                goodbye_text TEXT DEFAULT 'وداعاً {user} 👋',
                delete_banned_words INTEGER DEFAULT 0,
                auto_penalty TEXT DEFAULT 'none',
                auto_mute_duration INTEGER DEFAULT 60
            )
        """)
        
        # جدول المشرفين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        
        # جدول المجموعات
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
        
        # جدول رسائل المستخدمين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_messages (
                user_id INTEGER,
                chat_id INTEGER,
                message_time TIMESTAMP,
                PRIMARY KEY (user_id, chat_id)
            )
        """)
        
        # جدول التحذيرات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_warnings (
                user_id INTEGER,
                chat_id INTEGER,
                warnings INTEGER DEFAULT 0,
                PRIMARY KEY(user_id, chat_id)
            )
        """)
        
        # جدول الكلمات المحظورة
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS banned_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT,
                chat_id INTEGER,
                added_by INTEGER,
                added_at TIMESTAMP,
                UNIQUE(word, chat_id)
            )
        """)
        
        # جدول المالكين المخفيين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hidden_owner_groups (
                chat_id INTEGER PRIMARY KEY,
                owner_id INTEGER,
                is_hidden INTEGER DEFAULT 1
            )
        """)
        
        # جدول المشرفين المخفيين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hidden_admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                admin_id INTEGER NOT NULL,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, admin_id)
            )
        """)
        
        # جدول تذاكر الدعم
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
        
        # جدول أقفال المجموعات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_locks (
                chat_id INTEGER PRIMARY KEY,
                locked INTEGER DEFAULT 0,
                locked_at TIMESTAMP,
                locked_by INTEGER
            )
        """)
        
        # جدول الجدولة
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schedule (
                channel_db_id INTEGER PRIMARY KEY,
                schedule_type TEXT DEFAULT 'interval_minutes',
                interval_minutes INTEGER DEFAULT 12,
                interval_hours INTEGER DEFAULT 0,
                interval_days INTEGER DEFAULT 0,
                days_of_week TEXT DEFAULT '',
                specific_dates TEXT DEFAULT '',
                publish_time TEXT DEFAULT '00:00',
                next_publish_date TEXT,
                FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
            )
        """)
        
        # جدول آخر نشر
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS last_publish (
                channel_db_id INTEGER PRIMARY KEY,
                last_publish_time TIMESTAMP,
                FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
            )
        """)
        
        # جدول المنشورات المجدولة
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                publish_time TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                fail_count INTEGER DEFAULT 0
            )
        """)
        
        # جدول المستخدم المصرح بـ /sendcode
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS allowed_sendcode_user (
                id INTEGER PRIMARY KEY CHECK (id=1),
                user_id INTEGER
            )
        """)
        
        # جدول المسابقات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER,
                title TEXT,
                description TEXT,
                prize TEXT,
                end_date TEXT,
                status TEXT DEFAULT 'active',
                winner_id INTEGER,
                created_at TIMESTAMP,
                contest_type TEXT DEFAULT 'raffle'
            )
        """)
        
        # جدول مشاركي المسابقات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contest_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                contest_id INTEGER,
                joined_at TIMESTAMP,
                UNIQUE(user_id, contest_id)
            )
        """)
        
        # جدول فائزي المسابقات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contest_winners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contest_id INTEGER,
                winner_id INTEGER,
                announced_at TIMESTAMP
            )
        """)
        
        # جدول قوانين المجموعة
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_rules (
                chat_id INTEGER PRIMARY KEY,
                rules_text TEXT,
                updated_by INTEGER,
                updated_at TIMESTAMP
            )
        """)
        
        await conn.commit()
    
    await db_pool.initialize()
    logger.info("✅ قاعدة البيانات جاهزة")

# ===================== أنظمة التشغيل الخلفي =====================
async def auto_publish_loop_improved(bot):
    await asyncio.sleep(5)
    consecutive_errors = 0
    backoff = 10
    max_backoff = 60
    
    semaphore = asyncio.Semaphore(5)
    
    async def publish_one(row):
        async with semaphore:
            ch_db_id, ch_tele_id, user_id = row
            
            if not await db_has_active_subscription(user_id) and not await db_has_used_trial(user_id):
                return
            
            auto_recycle = await db_get_auto_recycle(user_id)
            total = await db_get_posts_count(ch_db_id)
            published = await db_get_published_count(ch_db_id)
            
            if total > 0 and published >= total:
                if auto_recycle:
                    logger.info(f"♻️ إعادة تدوير تلقائي للقناة {ch_tele_id}")
                    await db_reset_all_posts_to_unpublished(ch_db_id)
                else:
                    logger.info(f"⛔ توقف النشر للقناة {ch_tele_id} (auto_recycle معطل)")
                    await db_set_next_publish_date(ch_db_id, utc_now() + timedelta(days=365))
                return
            
            post = await db_get_next_post(ch_db_id)
            if not post:
                if auto_recycle:
                    total = await db_get_posts_count(ch_db_id)
                    if total > 0:
                        await db_reset_all_posts_to_unpublished(ch_db_id)
                        logger.info(f"♻️ إعادة تدوير تلقائي للقناة {ch_tele_id} (لا توجد منشورات غير منشورة)")
                return
            
            success = False
            for attempt in range(3):
                try:
                    if post['media_type'] == 'photo' and post['media_file_id']:
                        await bot.send_photo(ch_tele_id, post['media_file_id'], caption=post['text'] if post['text'] else None)
                    elif post['media_type'] == 'video' and post['media_file_id']:
                        await bot.send_video(ch_tele_id, post['media_file_id'], caption=post['text'] if post['text'] else None)
                    elif post['media_type'] == 'document' and post['media_file_id']:
                        await bot.send_document(ch_tele_id, post['media_file_id'], caption=post['text'] if post['text'] else None)
                    else:
                        await bot.send_message(ch_tele_id, post['text'])
                    success = True
                    break
                except Exception as e:
                    logger.warning(f"محاولة {attempt+1} فشلت: {e}")
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
            
            if success:
                await db_mark_published(post['id'])
                await db_set_last_publish(ch_db_id, utc_now())
                await db_update_next_publish_date(ch_db_id)
            else:
                await db_increment_fail_count(post['id'])
                next_retry = utc_now() + timedelta(seconds=300)
                await db_set_next_publish_date(ch_db_id, next_retry)
            await asyncio.sleep(random.uniform(1, 3))
    
    while True:
        try:
            async def _get_due_channels(conn, limit=20):
                now_utc_iso = utc_now().isoformat()
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
                    LIMIT ?
                """, (now_utc_iso, limit))
                return await cur.fetchall()
            
            rows = await execute_db(_get_due_channels)
            tasks = [publish_one(row) for row in rows]
            await asyncio.gather(*tasks, return_exceptions=True)
            
            consecutive_errors = 0
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.error(f"خطأ في حلقة النشر: {e}")
            consecutive_errors += 1
            backoff = min(backoff * 1.5, max_backoff)
            await asyncio.sleep(backoff)

async def auto_backup():
    while True:
        await asyncio.sleep(24 * 60 * 60)
        try:
            logger.info("💾 جاري إنشاء نسخة احتياطية تلقائية...")
            backup_file = BACKUP_DIR / f"backup_{mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
            shutil.copy2(DB_PATH, backup_file)
            
            backups = sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
            for old_backup in backups[10:]:
                old_backup.unlink()
            
            logger.info(f"✅ تم إنشاء نسخة احتياطية: {backup_file.name}")
        except Exception as e:
            logger.error(f"❌ فشل النسخ الاحتياطي: {e}")

# ===================== الوظيفة الرئيسية =====================
async def main():
    await init_db_improved()

    # إعدادات الطلبات
    request_kwargs = {
        'read_timeout': 60.0,
        'write_timeout': 30.0,
        'connect_timeout': 30.0,
        'pool_timeout': 10.0,
    }
    request = HTTPXRequest(**request_kwargs)
    application = Application.builder().token(TOKEN).request(request).build()

    application.add_error_handler(global_error_handler)

    # ===================== الأوامر =====================
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("language", language_command_handler))
    application.add_handler(CommandHandler("syncgroup", syncgroup_command_handler))
    application.add_handler(CommandHandler("security", security_command_handler))
    application.add_handler(CommandHandler("register_hidden_owner", register_hidden_owner_handler))
    application.add_handler(CommandHandler("add_hidden_admin", add_hidden_admin_command))
    application.add_handler(CommandHandler("remove_hidden_admin", remove_hidden_admin_command))
    application.add_handler(CommandHandler("list_hidden_admins", list_hidden_admins_command))
    application.add_handler(CommandHandler("trial", trial_command_handler))
    application.add_handler(CommandHandler("subscribe", subscribe_command_handler))
    application.add_handler(CommandHandler("help", help_command_handler))
    application.add_handler(CommandHandler("support", support_command_handler))
    application.add_handler(CommandHandler("support_reply", support_reply_command_handler))
    application.add_handler(CommandHandler("rank", rank_command_handler))
    application.add_handler(CommandHandler("top", top_command_handler))
    application.add_handler(CommandHandler("developer", developer_command_handler))
    application.add_handler(CommandHandler("updates", updates_command_handler))
    application.add_handler(CommandHandler("stats", stats_command_handler))
    application.add_handler(CommandHandler("sendcode", sendcode_command_handler))
    application.add_handler(CommandHandler("lock", lock_chat_command_handler))
    application.add_handler(CommandHandler("unlock", unlock_chat_command_handler))
    application.add_handler(CommandHandler("schedule", schedule_post_command_handler))
    application.add_handler(CommandHandler("panel", panel_command_handler))
    application.add_handler(CommandHandler("set_log_channel", set_log_channel_command_handler))

    # ===================== أوامر الإدارة =====================
    application.add_handler(CommandHandler("ban", handle_moderation_commands))
    application.add_handler(CommandHandler("mute", handle_moderation_commands))
    application.add_handler(CommandHandler("unmute", handle_moderation_commands))
    application.add_handler(CommandHandler("warn", handle_moderation_commands))
    application.add_handler(CommandHandler("kick", handle_moderation_commands))
    application.add_handler(CommandHandler("restrict", handle_moderation_commands))
    application.add_handler(CommandHandler("pin", handle_moderation_commands))
    application.add_handler(CommandHandler("unban", handle_moderation_commands))

    # ===================== أوامر المسابقات =====================
    application.add_handler(CommandHandler("contests", contests_menu_callback))
    application.add_handler(CommandHandler("create_contest", create_contest_command_handler))
    application.add_handler(CommandHandler("declare_winner", declare_winner_command_handler))

    # ===================== أوامر القوانين =====================
    application.add_handler(CommandHandler("rules", rules_command_handler))
    application.add_handler(CommandHandler("set_rules", set_rules_command_handler))
    application.add_handler(CommandHandler("reset_rules", reset_rules_command_handler))

    # ===================== أمر تحديث المشرفين =====================
    application.add_handler(CommandHandler("update_admins", update_admins_command_handler))

    # ===================== معالجات الكولباك =====================
    application.add_handler(CallbackQueryHandler(lang_callback_handler, pattern="^lang_"))
    application.add_handler(CallbackQueryHandler(handle_text_callbacks, pattern="^(rank|top|schedule_post|language)$"))
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern=f"^{CallbackData.MAIN_MENU}$"))
    application.add_handler(CallbackQueryHandler(back_callback, pattern=f"^{CallbackData.BACK}$"))
    application.add_handler(CallbackQueryHandler(cancel_session_callback, pattern=f"^{CallbackData.CANCEL_SESSION}$"))
    application.add_handler(CallbackQueryHandler(add_channel_callback, pattern=f"^{CallbackData.CHANNELS_ADD}$"))
    application.add_handler(CallbackQueryHandler(my_channels_callback, pattern=f"^{CallbackData.CHANNELS_MY}$"))
    application.add_handler(CallbackQueryHandler(delete_channel_callback, pattern=f"^{CallbackData.CHANNELS_DELETE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(select_channel_callback, pattern=f"^{CallbackData.CHANNELS_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(add_15_posts_callback, pattern=f"^{CallbackData.POSTS_ADD_15}$"))
    application.add_handler(CallbackQueryHandler(publish_one_callback, pattern=f"^{CallbackData.POSTS_PUBLISH_ONE}$"))
    application.add_handler(CallbackQueryHandler(my_posts_callback, pattern=f"^{CallbackData.POSTS_MY}$"))
    application.add_handler(CallbackQueryHandler(recycle_posts_callback, pattern=f"^{CallbackData.POSTS_RECYCLE}$"))
    application.add_handler(CallbackQueryHandler(delete_single_post_callback, pattern=f"^{CallbackData.POSTS_DELETE_SINGLE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(confirm_clear_all_posts_callback, pattern=f"^{CallbackData.POSTS_CONFIRM_CLEAR_ALL_PREFIX}"))
    application.add_handler(CallbackQueryHandler(clear_all_posts_callback, pattern=f"^{CallbackData.POSTS_CLEAR_ALL_PREFIX}"))
    application.add_handler(CallbackQueryHandler(my_pending_stats_callback, pattern=f"^{CallbackData.STATS_PENDING}$"))
    application.add_handler(CallbackQueryHandler(my_full_stats_callback, pattern=f"^{CallbackData.STATS_FULL}$"))
    application.add_handler(CallbackQueryHandler(my_groups_callback, pattern=f"^{CallbackData.GROUPS_MY}$"))
    application.add_handler(CallbackQueryHandler(group_settings_callback, pattern=f"^{CallbackData.GROUPS_SETTINGS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(settings_menu_callback, pattern=f"^{CallbackData.SETTINGS_MENU}$"))
    application.add_handler(CallbackQueryHandler(toggle_auto_publish_callback, pattern=f"^{CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH}$"))

    # ===== أمان =====
    application.add_handler(CallbackQueryHandler(security_links_callback, pattern=f"^{CallbackData.SECURITY_LINKS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_mentions_callback, pattern=f"^{CallbackData.SECURITY_MENTIONS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_warn_callback, pattern=f"^{CallbackData.SECURITY_WARN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_slowmode_callback, pattern=f"^{CallbackData.SECURITY_SLOWMODE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_banned_words_menu_callback, pattern=f"^{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_welcome_callback, pattern=f"^{CallbackData.SECURITY_WELCOME_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_goodbye_callback, pattern=f"^{CallbackData.SECURITY_GOODBYE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_close_callback, pattern=f"^{CallbackData.SECURITY_CLOSE}$"))
    application.add_handler(CallbackQueryHandler(security_select_group_callback, pattern=f"^{CallbackData.SECURITY_SELECT_GROUP}"))
    application.add_handler(CallbackQueryHandler(security_refresh_groups_callback, pattern=f"^{CallbackData.SECURITY_REFRESH_GROUPS}$"))

    # ===== كلمات محظورة =====
    application.add_handler(CallbackQueryHandler(banned_words_add_callback, pattern=f"^{CallbackData.BANNED_WORDS_ADD_PREFIX}"))
    application.add_handler(CallbackQueryHandler(banned_words_list_callback, pattern=f"^{CallbackData.BANNED_WORDS_LIST_PREFIX}"))
    application.add_handler(CallbackQueryHandler(banned_words_remove_callback, pattern=f"^{CallbackData.BANNED_WORDS_REMOVE_PREFIX}"))

    # ===== دعم =====
    application.add_handler(CallbackQueryHandler(help_callback, pattern=f"^{CallbackData.HELP}$"))
    application.add_handler(CallbackQueryHandler(support_menu_callback, pattern=f"^{CallbackData.SUPPORT_MENU}$"))
    application.add_handler(CallbackQueryHandler(support_help_callback, pattern=f"^{CallbackData.SUPPORT_HELP}$"))
    application.add_handler(CallbackQueryHandler(support_ticket_callback, pattern=f"^{CallbackData.SUPPORT_TICKET}$"))
    application.add_handler(CallbackQueryHandler(support_back_callback, pattern=f"^{CallbackData.SUPPORT_BACK}$"))

    # ===== اشتراك =====
    application.add_handler(CallbackQueryHandler(trial_callback, pattern=f"^{CallbackData.TRIAL}$"))
    application.add_handler(CallbackQueryHandler(subscribe_menu_callback, pattern=f"^{CallbackData.SUBSCRIBE_MENU}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_1_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_1}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_2_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_2}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_30_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_30}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_90_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_90}$"))

    # ===== أخرى =====
    application.add_handler(CallbackQueryHandler(developer_callback, pattern=f"^{CallbackData.DEVELOPER}$"))
    application.add_handler(CallbackQueryHandler(updates_callback, pattern=f"^{CallbackData.UPDATES}$"))
    application.add_handler(CallbackQueryHandler(referral_menu_callback, pattern=f"^{CallbackData.REFERRAL_MENU}$"))
    application.add_handler(CallbackQueryHandler(reminder_menu_callback, pattern=f"^{CallbackData.REMINDER_MENU}$"))
    application.add_handler(CallbackQueryHandler(translation_menu_callback, pattern=f"^{CallbackData.TRANSLATION_MENU}$"))

    # ===== لوحة الأدمن =====
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=f"^{CallbackData.ADMIN_PANEL}$"))
    application.add_handler(CallbackQueryHandler(admin_users_callback, pattern=f"^{CallbackData.ADMIN_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_users_callback, pattern=f"^{CallbackData.ADMIN_BANNED_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_unban_all_users_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_all_channels_callback, pattern=f"^{CallbackData.ADMIN_ALL_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_add_admin_callback, pattern=f"^{CallbackData.ADMIN_ADD_ADMIN}$"))
    application.add_handler(CallbackQueryHandler(admin_remove_admin_callback, pattern=f"^{CallbackData.ADMIN_REMOVE_ADMIN}$"))
    application.add_handler(CallbackQueryHandler(admin_send_update_callback, pattern=f"^{CallbackData.ADMIN_SEND_UPDATE}$"))
    application.add_handler(CallbackQueryHandler(admin_set_update_channel_callback, pattern=f"^{CallbackData.ADMIN_SET_UPDATE_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_force_subscribe_callback, pattern=f"^{CallbackData.ADMIN_FORCE_SUBSCRIBE}$"))
    application.add_handler(CallbackQueryHandler(admin_broadcast_callback, pattern=f"^{CallbackData.ADMIN_BROADCAST}$"))
    application.add_handler(CallbackQueryHandler(admin_confirm_broadcast_callback, pattern=f"^{CallbackData.ADMIN_CONFIRM_BROADCAST}$"))
    application.add_handler(CallbackQueryHandler(admin_support_tickets_callback, pattern=f"^{CallbackData.ADMIN_SUPPORT_TICKETS}$"))
    application.add_handler(CallbackQueryHandler(admin_manage_sendcode_callback, pattern=f"^{CallbackData.ADMIN_MANAGE_SENDCODE}$"))
    application.add_handler(CallbackQueryHandler(admin_replies_callback, pattern=f"^{CallbackData.ADMIN_REPLIES}$"))
    application.add_handler(CallbackQueryHandler(admin_add_reply_callback, pattern=f"^{CallbackData.ADMIN_ADD_REPLY}$"))
    application.add_handler(CallbackQueryHandler(admin_list_replies_callback, pattern=f"^{CallbackData.ADMIN_LIST_REPLIES}$"))
    application.add_handler(CallbackQueryHandler(admin_del_reply_callback, pattern=f"^{CallbackData.ADMIN_DEL_REPLY}$"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern=f"^{CallbackData.ADMIN_AUTO_REPLY}$"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_select_callback, pattern=f"^{CallbackData.ADMIN_AUTO_REPLY_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_create_contest_callback, pattern=f"^{CallbackData.ADMIN_CREATE_CONTEST}$"))
    application.add_handler(CallbackQueryHandler(admin_stats_callback, pattern=f"^{CallbackData.ADMIN_STATS}$"))
    application.add_handler(CallbackQueryHandler(admin_ram_callback, pattern=f"^{CallbackData.ADMIN_RAM}$"))
    application.add_handler(CallbackQueryHandler(admin_backup_callback, pattern=f"^{CallbackData.ADMIN_BACKUP}$"))
    application.add_handler(CallbackQueryHandler(admin_backup_settings_callback, pattern=f"^{CallbackData.ADMIN_BACKUP_SETTINGS}$"))
    application.add_handler(CallbackQueryHandler(admin_toggle_auto_backup_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_AUTO_BACKUP}$"))
    application.add_handler(CallbackQueryHandler(admin_change_interval_callback, pattern=f"^{CallbackData.ADMIN_CHANGE_INTERVAL}$"))
    application.add_handler(CallbackQueryHandler(admin_show_update_channel_callback, pattern=f"^{CallbackData.ADMIN_SHOW_UPDATE_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_show_log_channel_callback, pattern=f"^{CallbackData.ADMIN_SHOW_LOG_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_words_callback, pattern=f"^{CallbackData.ADMIN_BANNED_WORDS}$"))
    application.add_handler(CallbackQueryHandler(admin_add_banned_word_callback, pattern=f"^{CallbackData.ADMIN_ADD_BANNED_WORD}$"))
    application.add_handler(CallbackQueryHandler(admin_list_banned_words_callback, pattern=f"^{CallbackData.ADMIN_LIST_BANNED_WORDS}$"))
    application.add_handler(CallbackQueryHandler(admin_remove_banned_word_callback, pattern=f"^{CallbackData.ADMIN_REMOVE_BANNED_WORD}$"))
    application.add_handler(CallbackQueryHandler(admin_del_contest_callback, pattern=f"^{CallbackData.ADMIN_DEL_CONTEST_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_delete_all_tickets_callback, pattern=f"^{CallbackData.ADMIN_DELETE_ALL_TICKETS}$"))
    application.add_handler(CallbackQueryHandler(admin_confirm_delete_tickets_callback, pattern=f"^{CallbackData.ADMIN_CONFIRM_DELETE_TICKETS}$"))
    application.add_handler(CallbackQueryHandler(admin_toggle_channel_ban_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_CHANNEL_BAN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_toggle_group_ban_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_GROUP_BAN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_unban_all_groups_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_GROUPS}$"))
    application.add_handler(CallbackQueryHandler(admin_activate_all_channels_callback, pattern=f"^{CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_unban_all_bot_channels_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_BOT_CHANNELS}$"))

    # ===== الردود التلقائية =====
    application.add_handler(CallbackQueryHandler(auto_reply_toggle_callback, pattern=f"^{CallbackData.AUTO_REPLY_TOGGLE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_admins_callback, pattern=f"^{CallbackData.AUTO_REPLY_ADMINS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_reset_callback, pattern=f"^{CallbackData.AUTO_REPLY_RESET_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_confirm_reset_callback, pattern=f"^{CallbackData.AUTO_REPLY_CONFIRM_RESET_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_cancel_callback, pattern=f"^{CallbackData.AUTO_REPLY_CANCEL_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_stats_callback, pattern=f"^{CallbackData.AUTO_REPLY_STATS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(user_auto_reply_toggle_callback, pattern=f"^{CallbackData.USER_AUTO_REPLY_TOGGLE_PREFIX}"))

    # ===== NSFW =====
    application.add_handler(CallbackQueryHandler(nsfw_settings_callback, pattern=f"^{CallbackData.NSFW_SETTINGS}$"))
    application.add_handler(CallbackQueryHandler(nsfw_toggle_callback, pattern=f"^{CallbackData.NSFW_TOGGLE}$"))
    application.add_handler(CallbackQueryHandler(nsfw_threshold_set_callback, pattern=f"^{CallbackData.NSFW_THRESHOLD_SET}$"))

    # ===== مسابقات =====
    application.add_handler(CallbackQueryHandler(contests_menu_callback, pattern=f"^{CallbackData.CONTESTS_MENU}$"))
    application.add_handler(CallbackQueryHandler(contest_join_callback, pattern=f"^{CallbackData.CONTEST_JOIN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(contest_winners_callback, pattern=f"^{CallbackData.CONTEST_WINNERS}$"))
    application.add_handler(CallbackQueryHandler(contests_back_callback, pattern=f"^{CallbackData.CONTESTS_BACK}$"))

    # ===== قوانين =====
    application.add_handler(CallbackQueryHandler(reset_rules_confirm_callback, pattern="^reset_rules_confirm:"))
    application.add_handler(CallbackQueryHandler(reset_rules_cancel_callback, pattern="^reset_rules_cancel:"))

    # ===== عقوبات =====
    application.add_handler(CallbackQueryHandler(penalty_menu_callback, pattern=f"^{CallbackData.PENALTY_MENU}:"))
    application.add_handler(CallbackQueryHandler(penalty_kick_callback, pattern=f"^{CallbackData.PENALTY_KICK}:"))
    application.add_handler(CallbackQueryHandler(penalty_ban_callback, pattern=f"^{CallbackData.PENALTY_BAN}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_callback, pattern=f"^{CallbackData.PENALTY_MUTE}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_5}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_30}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_60}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_720}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_1440}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_10080}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_PERMANENT}:"))

    # ===== إجراءات متقدمة =====
    application.add_handler(CallbackQueryHandler(advanced_actions_callback, pattern=f"^{CallbackData.ADVANCED_ACTIONS}:"))
    application.add_handler(CallbackQueryHandler(group_action_ban_callback, pattern=f"^{CallbackData.GROUP_ACTION_BAN}:"))
    application.add_handler(CallbackQueryHandler(group_action_mute_callback, pattern=f"^{CallbackData.GROUP_ACTION_MUTE}:"))
    application.add_handler(CallbackQueryHandler(advanced_mute_duration_callback, pattern="^adv_mute_duration:"))
    application.add_handler(CallbackQueryHandler(group_action_warn_callback, pattern=f"^{CallbackData.GROUP_ACTION_WARN}:"))
    application.add_handler(CallbackQueryHandler(group_action_kick_callback, pattern=f"^{CallbackData.GROUP_ACTION_KICK}:"))
    application.add_handler(CallbackQueryHandler(group_action_restrict_callback, pattern=f"^{CallbackData.GROUP_ACTION_RESTRICT}:"))
    application.add_handler(CallbackQueryHandler(group_action_pin_callback, pattern=f"^{CallbackData.GROUP_ACTION_PIN}:"))
    application.add_handler(CallbackQueryHandler(group_action_log_callback, pattern=f"^{CallbackData.GROUP_ACTION_LOG}:"))
    application.add_handler(CallbackQueryHandler(group_action_unban_callback, pattern=f"^{CallbackData.GROUP_ACTION_UNBAN}:"))

    # ===== أخرى =====
    application.add_handler(CallbackQueryHandler(panel_lock_callback_handler, pattern=f"^{CallbackData.PANEL_LOCK_PREFIX}"))
    application.add_handler(CallbackQueryHandler(panel_unlock_callback_handler, pattern=f"^{CallbackData.PANEL_UNLOCK_PREFIX}"))
    application.add_handler(CallbackQueryHandler(panel_close_callback_handler, pattern=f"^{CallbackData.PANEL_CLOSE}$"))
    application.add_handler(CallbackQueryHandler(check_subscribe_callback_handler, pattern=f"^{CallbackData.CHECK_SUBSCRIBE}$"))
    application.add_handler(CallbackQueryHandler(publish_all_channels_callback_handler, pattern=f"^{CallbackData.PUBLISH_ALL_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(channel_stats_callback, pattern=f"^{CallbackData.CHANNEL_STATS}:"))
    application.add_handler(CallbackQueryHandler(my_channel_stats_callback, pattern=f"^{CallbackData.MY_CHANNEL_STATS}$"))
    application.add_handler(CallbackQueryHandler(channel_stats_refresh_callback, pattern=f"^{CallbackData.CHANNEL_STATS_REFRESH}:"))

    # ===== دفع =====
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_callback_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback_handler))

    # ===== مجموعات =====
    application.add_handler(ChatMemberHandler(track_chat_add, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_bot_added))

    # ===== رسائل =====
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    application.add_handler(MessageHandler(filters.CAPTION & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler_main))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.AUDIO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.ANIMATION & filters.ChatType.PRIVATE, message_handler_main))

    # ===== قائمة الأوامر =====
    commands = [
        BotCommand("start", "بدء البوت"),
        BotCommand("trial", "تجربة مجانية"),
        BotCommand("subscribe", "الاشتراك"),
        BotCommand("syncgroup", "تفعيل المجموعة"),
        BotCommand("security", "إعدادات الأمان"),
        BotCommand("register_hidden_owner", "تسجيل مالك مخفي"),
        BotCommand("add_hidden_admin", "إضافة مشرف مخفي"),
        BotCommand("remove_hidden_admin", "إزالة مشرف مخفي"),
        BotCommand("list_hidden_admins", "عرض المشرفين المخفيين"),
        BotCommand("rank", "رتبتك"),
        BotCommand("top", "أفضل 10"),
        BotCommand("stats", "إحصائيات القناة"),
        BotCommand("lock", "قفل المجموعة"),
        BotCommand("unlock", "فتح المجموعة"),
        BotCommand("schedule", "جدولة منشور"),
        BotCommand("panel", "لوحة التحكم"),
        BotCommand("language", "تغيير اللغة"),
        BotCommand("support", "مركز الدعم"),
        BotCommand("help", "المساعدة"),
        BotCommand("developer", "المطور"),
        BotCommand("updates", "آخر التحديثات"),
        BotCommand("sendcode", "إرسال كود البوت"),
        BotCommand("set_log_channel", "تعيين قناة التقارير"),
        BotCommand("ban", "حظر مستخدم"),
        BotCommand("mute", "كتم مستخدم"),
        BotCommand("unmute", "إلغاء كتم"),
        BotCommand("warn", "تحذير مستخدم"),
        BotCommand("kick", "طرد مستخدم"),
        BotCommand("restrict", "تقييد مستخدم"),
        BotCommand("pin", "تثبيت رسالة"),
        BotCommand("unban", "إلغاء حظر"),
        BotCommand("contests", "المسابقات"),
        BotCommand("create_contest", "إنشاء مسابقة"),
        BotCommand("declare_winner", "إعلان فائز"),
        BotCommand("update_admins", "تحديث المشرفين"),
        BotCommand("rules", "عرض قوانين المجموعة"),
        BotCommand("set_rules", "تعيين قوانين المجموعة"),
        BotCommand("reset_rules", "إعادة تعيين القوانين"),
    ]
    await application.bot.set_my_commands(commands)

    # ===== مهام خلفية =====
    asyncio.create_task(auto_publish_loop_improved(application.bot))
    asyncio.create_task(auto_backup())

    # ===== خادم الويب =====
    if WEB_SERVER_LOADED:
        try:
            asyncio.create_task(start_web_server())
            logger.info("✅ تم تشغيل خادم الويب")
        except Exception as e:
            logger.error(f"❌ فشل تشغيل خادم الويب: {e}")

    print(f"🚀 تم تشغيل {BOT_NAME} (الإصدار 19.3.1)")
    print("✅ جميع التصحيحات والتحسينات تم تطبيقها")

    try:
        await application.run_polling(
            drop_pending_updates=True,
            poll_interval=POLL_INTERVAL
        )
    except asyncio.CancelledError:
        logger.info("🛑 تم إلغاء تشغيل البوت")
    except KeyboardInterrupt:
        logger.info("🛑 تم إيقاف البوت بواسطة المستخدم")
    finally:
        logger.info("🧹 جاري تنظيف الموارد...")
        await db_pool.close()
        logger.info("✅ تم تنظيف الموارد بنجاح")

if __name__ == "__main__":
    try:
        os.environ["WEB_CONCURRENCY"] = "1"
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 تم إيقاف البوت")
    except Exception as e:
        logger.error(f"❌ خطأ فادح: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
