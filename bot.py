#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - بوت متكامل لإدارة القنوات والمجموعات
الإصدار: 19.4.0
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
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Optional, List, Dict, Any, Tuple
from functools import wraps
from enum import Enum, auto

# ===================== التحقق من إصدار بايثون =====================
def check_python_version():
    required_version = (3, 8)
    current_version = sys.version_info
    if current_version < required_version:
        print(f"❌ يحتاج البوت إلى بايثون {required_version[0]}.{required_version[1]} أو أحدث")
        sys.exit(1)

check_python_version()

# ===================== المسارات الأساسية =====================
def get_base_path() -> Path:
    return Path(__file__).parent.resolve()

BASE_PATH = get_base_path()
DATA_PATH = BASE_PATH / "data"
DB_PATH = DATA_PATH / "bot_data.db"
BACKUP_DIR = BASE_PATH / "backups"
LOG_PATH = BASE_PATH / "logs" / "bot.log"
BANNED_WORDS_FILE = BASE_PATH / "banned_words.txt"
TRANSLATIONS_FILE = BASE_PATH / "translations.json"

DATA_PATH.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# ===================== تثبيت المكتبات =====================
def ensure_package(package_name: str, import_name: str = None) -> bool:
    if import_name is None:
        import_name = package_name
    try:
        __import__(import_name)
        return True
    except ImportError:
        try:
            import subprocess
            print(f"📦 جاري تثبيت {package_name}...")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", package_name, "--quiet"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            __import__(import_name)
            print(f"✅ تم تثبيت {package_name}")
            return True
        except:
            print(f"⚠️ لا يمكن تثبيت {package_name}")
            return False

ensure_package("python-dotenv", "dotenv")
ensure_package("aiosqlite")
ensure_package("nest-asyncio", "nest_asyncio")
ensure_package("python-telegram-bot", "telegram")
ensure_package("deep-translator", "deep_translator")
ensure_package("psutil")
ensure_package("cachetools")

# ===================== استيراد المكتبات =====================
import nest_asyncio
nest_asyncio.apply()

import aiosqlite
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ChatPermissions
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ChatMemberHandler
from telegram.error import TimedOut, NetworkError, BadRequest, Forbidden, Conflict
from telegram.request import HTTPXRequest
from deep_translator import GoogleTranslator

try:
    import psutil
    PSUTIL_AVAILABLE = True
except:
    PSUTIL_AVAILABLE = False

try:
    from cachetools import TTLCache
    CACHETOOLS_AVAILABLE = True
except:
    CACHETOOLS_AVAILABLE = False

# ===================== استيراد الملفات المنفصلة =====================
# استيراد الردود - لا يتوقف البوت إذا فشل
try:
    from replies import ALL_REPLIES
    REPLIES_LOADED = True
    print("✅ تم تحميل الردود من replies.py")
except ImportError:
    REPLIES_LOADED = False
    ALL_REPLIES = {}
    print("⚠️ ملف replies.py غير موجود - سيتم استخدام الردود الافتراضية")

# استيراد الخادم الويب - لا يتوقف البوت إذا فشل
try:
    from web_server import start_web_server, WEB_SERVER_LOADED
    print("✅ تم تحميل web_server.py")
except ImportError:
    WEB_SERVER_LOADED = False
    print("⚠️ ملف web_server.py غير موجود")

# استيراد المسابقات - لا يتوقف البوت إذا فشل
try:
    from contests import *
    CONTESTS_LOADED = True
    print("✅ تم تحميل contests.py")
except ImportError:
    CONTESTS_LOADED = False
    print("⚠️ ملف contests.py غير موجود")

# استيراد الدفع - لا يتوقف البوت إذا فشل
try:
    from bot_pay import *
    PAY_LOADED = True
    print("✅ تم تحميل bot_pay.py")
except ImportError:
    PAY_LOADED = False
    print("⚠️ ملف bot_pay.py غير موجود")

# استيراد المفقودات - لا يتوقف البوت إذا فشل
try:
    from missing import *
    MISSING_LOADED = True
    print("✅ تم تحميل المفقودات من missing.py")
except ImportError as e:
    MISSING_LOADED = False
    print(f"⚠️ ملف missing.py غير موجود: {e}")

# ===================== إعدادات البوت =====================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("❌ BOT_TOKEN غير موجود في ملف .env")
    sys.exit(1)

try:
    PRIMARY_OWNER_ID = int(os.getenv("MAIN_ADMIN_ID", 0))
    if PRIMARY_OWNER_ID == 0:
        print("❌ MAIN_ADMIN_ID غير محدد")
        sys.exit(1)
except ValueError:
    print("❌ MAIN_ADMIN_ID يجب أن يكون رقمًا صحيحًا")
    sys.exit(1)

BOT_NAME = os.getenv("BOT_NAME", "ريلاكس مانيجر")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Reelaaaxbot")
USE_PROXY = os.getenv("USE_PROXY", "False").lower() == "true"
PROXY_URL = os.getenv("PROXY_URL", "http://127.0.0.1:10809")

MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 20 * 1024 * 1024))
MAX_UNPUBLISHED_POSTS = 1000
MAX_POSTS_PER_SESSION = 50
DB_TIMEOUT = 30
DB_MAX_RETRIES = 3
REQUEST_TIMEOUT = 30
POLL_INTERVAL = 1.0
_ADMIN_CACHE_TTL = 300
MAX_BACKUPS = 10
DEFAULT_PUBLISH_INTERVAL_SECONDS = 720

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
• لا للمحتوى غير اللائق (NSFW)

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

━━━━━━━━━━━━━━━━━━━━━━
📌 **للتواصل مع المشرفين:** /support
"""

# ===================== الردود التلقائية =====================
# إذا لم يتم تحميل الردود من الملف، استخدم الردود الافتراضية
DEFAULT_REPLIES = {
    "مرحباً": "أهلاً وسهلاً بك في مجموعتنا 🤍",
    "السلام عليكم": "وعليكم السلام ورحمة الله وبركاته 🌹",
    "كيف حالك": "الحمد لله، بخير وأنت؟ ❤️",
    "شكراً": "العفو، تحت أمرك دائماً ❤️",
    "ما شاء الله": "تبارك الرحمن 🤍",
    "الحمد لله": "الحمد لله دائماً وأبداً 🙏",
    "الله اكبر": "الله أكبر كبيراً 🌹",
    "شو اخبارك": "كل الخير، كيفك أنت؟ 🌹",
    "وينك": "أنا هنا، شنو تحتاج؟ 🤖",
    "شنو اسمك": "أنا البوت، تحت أمرك 🙏",
    "منو انت": "أنا البوت، مساعد المجموعة 🛡️",
    "ممنوع": "تم التنبيه، يرجى احترام قوانين المجموعة 🚫",
    "قوانين": "قوانين المجموعة موجودة في الوصف 📋",
    "بليز": "حاضر، أرسل طلبك بالتفصيل 📝",
    "مساعدة": "كيف أقدر أساعدك؟ 🤖",
    "تمام": "تمام يا غالي 🌸",
    "مع السلامة": "مع السلامة، تشرفنا بك 🌸",
    "باي": "باي، نورت 🌹",
    "صباح الخير": "صباح النور 🌞",
    "مساء الخير": "مساء النور 🌙",
    "تصبح على خير": "وأنت من أهله 🌙",
    "حاضر": "حاضر، أنا جاهز 💪",
    "اوك": "أوكي، تحت أمرك 🙏",
    "ان شاء الله": "إن شاء الله خير 🌹",
    "استغفر الله": "ربي اغفر لي ولوالديّ 🙏",
    "سبحان الله": "سبحان الله وبحمده 🌹",
    "لا اله الا الله": "لا إله إلا الله محمد رسول الله 🙏",
}

# استخدام الردود المحملة أو الافتراضية
if REPLIES_LOADED and ALL_REPLIES:
    ALL_REPLIES = ALL_REPLIES
else:
    ALL_REPLIES = DEFAULT_REPLIES

# ===================== الكلمات المحظورة =====================
BANNED_WORDS = []
BANNED_PATTERNS = []

def load_banned_words():
    global BANNED_WORDS, BANNED_PATTERNS
    if not BANNED_WORDS_FILE.exists():
        try:
            with open(BANNED_WORDS_FILE, 'w', encoding='utf-8') as f:
                f.write("# قائمة الكلمات المحظورة\n")
                f.write("بورن\nسكس\nجنس\nعري\nخمر\nخمور\nمخدرات\nحشيش\nكحول\nدعارة\nسب\nشتم\n")
            print(f"✅ تم إنشاء ملف {BANNED_WORDS_FILE}")
        except:
            pass
        return
    try:
        words = []
        patterns = []
        with open(BANNED_WORDS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                word = line.lower()
                if len(word) >= 2:
                    words.append(word)
                    if '*' in word or '?' in word or '+' in word:
                        try:
                            patterns.append(re.compile(word))
                        except:
                            pass
        BANNED_WORDS = words
        BANNED_PATTERNS = patterns
        print(f"✅ تم تحميل {len(words)} كلمة محظورة")
    except Exception as e:
        print(f"❌ فشل تحميل الكلمات المحظورة: {e}")

load_banned_words()

# ===================== دوال الترجمة =====================
TRANSLATIONS = {}

def load_translations():
    global TRANSLATIONS
    default = {
        "ar": {
            "welcome": "🌿 **مرحباً بك في ريلاكس مانيجر**",
            "main_title": "🌿 **{0}**\n👤 المعرف: `{1}`",
            "admin_only": "🔒 هذا الأمر للمشرفين فقط!",
            "cancelled": "❌ تم الإلغاء",
            "no_channels": "لا توجد قنوات",
            "no_channels_list": "📭 لا توجد قنوات مسجلة",
            "send_channel_id": "📡 أرسل معرف القناة",
            "channel_added": "✅ تم إضافة القناة {0}",
            "channel_exists": "⚠️ القناة موجودة مسبقاً",
            "channel_deleted": "✅ تم حذف القناة",
            "delete_failed": "❌ فشل الحذف",
            "no_posts": "📭 لا توجد منشورات",
            "post_published": "✅ تم نشر المنشور بنجاح",
            "publish_error": "❌ فشل النشر: {0}",
            "settings": "⚙️ **الإعدادات**",
            "disabled": "❌ تعطيل",
            "enabled": "✅ تفعيل",
            "auto_toggled": "✅ تم تغيير حالة النشر التلقائي إلى: {0}",
            "help": "❓ **المساعدة**\n/start - القائمة الرئيسية\n/help - المساعدة\n/rules - القوانين",
            "trial": "🎁 **تم تفعيل التجربة المجانية!**\n✅ لديك 30 يوماً مجاناً",
            "trial_used": "❌ لقد استخدمت التجربة المجانية مسبقاً",
            "already_subscribed": "✅ لديك اشتراك فعال بالفعل",
            "subscribe": "💎 **الاشتراك**\nاختر الباقة:"
        },
        "en": {
            "welcome": "🌿 **Welcome to Relax Manager**",
            "main_title": "🌿 **{0}**\n👤 ID: `{1}`",
            "admin_only": "🔒 This command is for admins only!",
            "cancelled": "❌ Cancelled",
            "no_channels": "No channels",
            "no_channels_list": "📭 No channels registered",
            "send_channel_id": "📡 Send channel ID",
            "channel_added": "✅ Channel {0} added",
            "channel_exists": "⚠️ Channel already exists",
            "channel_deleted": "✅ Channel deleted",
            "delete_failed": "❌ Delete failed",
            "no_posts": "📭 No posts",
            "post_published": "✅ Post published successfully",
            "publish_error": "❌ Publish failed: {0}",
            "settings": "⚙️ **Settings**",
            "disabled": "❌ Disable",
            "enabled": "✅ Enable",
            "auto_toggled": "✅ Auto publish status changed to: {0}",
            "help": "❓ **Help**\n/start - Main Menu\n/help - Help\n/rules - Rules",
            "trial": "🎁 **Free Trial Activated!**\n✅ You have 30 days free",
            "trial_used": "❌ You have already used the free trial",
            "already_subscribed": "✅ You already have an active subscription",
            "subscribe": "💎 **Subscription**\nChoose your plan:"
        }
    }
    if not TRANSLATIONS_FILE.exists():
        try:
            with open(TRANSLATIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(default, f, ensure_ascii=False, indent=2)
            print(f"✅ تم إنشاء ملف translations.json")
        except:
            pass
        TRANSLATIONS = default
        return
    try:
        with open(TRANSLATIONS_FILE, 'r', encoding='utf-8') as f:
            TRANSLATIONS = json.load(f)
        print(f"✅ تم تحميل الترجمات من translations.json")
    except:
        TRANSLATIONS = default

load_translations()

user_language = {}

def get_text(user_id: int, key: str) -> str:
    lang = user_language.get(user_id, 'ar')
    lang_data = TRANSLATIONS.get(lang, TRANSLATIONS.get('ar', {}))
    return lang_data.get(key, key)

# ===================== دوال المساعدة =====================
def sanitize_text(text: str, max_length: int = 4096) -> str:
    if not text:
        return ""
    return text[:max_length]

def contains_link(text: str) -> bool:
    patterns = [
        r'https?://\S+',
        r'www\.\S+',
        r't\.me/\S+',
        r'telegram\.me/\S+',
        r'\b[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)+\S*'
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)

def contains_mention(text: str) -> bool:
    return bool(re.search(r'@\w+', text))

async def safe_send(bot, chat_id, text, reply_markup=None, parse_mode='Markdown'):
    if not text:
        return
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text[:4096],
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            timeout=REQUEST_TIMEOUT
        )
    except:
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=text[:4096],
                reply_markup=reply_markup,
                timeout=REQUEST_TIMEOUT
            )
        except:
            return None

async def safe_edit(query, text, reply_markup=None, parse_mode='Markdown'):
    if not query or not text:
        return
    try:
        return await query.edit_message_text(
            text[:4096],
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            timeout=REQUEST_TIMEOUT
        )
    except:
        try:
            return await query.edit_message_text(
                text[:4096],
                reply_markup=reply_markup,
                timeout=REQUEST_TIMEOUT
            )
        except:
            return None

def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def mecca_now():
    return utc_now() + timedelta(hours=3)

def utc_now_iso():
    return utc_now().isoformat()

def mecca_now_iso():
    return mecca_now().isoformat()

def mecca_to_utc(mecca_dt):
    if mecca_dt is None:
        return None
    if hasattr(mecca_dt, 'tzinfo') and mecca_dt.tzinfo is not None:
        mecca_dt = mecca_dt.replace(tzinfo=None)
    return mecca_dt - timedelta(hours=3)

def utc_to_mecca(utc_dt):
    if utc_dt is None:
        return None
    if hasattr(utc_dt, 'tzinfo') and utc_dt.tzinfo is not None:
        utc_dt = utc_dt.replace(tzinfo=None)
    return utc_dt + timedelta(hours=3)

def log_error(error: Exception, context: dict = None) -> str:
    error_id = secrets.token_hex(4)
    print(f"[{error_id}] خطأ: {error}")
    if context:
        print(f"السياق: {context}")
    return error_id

# ====================================================================
# ===================== تعريفات الكولباك =====================
# ====================================================================

class CallbackData:
    MAIN_MENU = "main_menu"
    BACK = "back"
    CHANNELS_ADD = "channels:add"
    CHANNELS_MY = "channels:my_channels"
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
    SETTINGS_TOGGLE_AUTO_RECYCLE = "settings:toggle_auto_recycle"
    SCHEDULE_MENU_PREFIX = "schedule:menu:"
    SCHEDULE_SET_INTERVAL_MINUTES_PREFIX = "schedule:set_interval_minutes:"
    SCHEDULE_SET_INTERVAL_HOURS_PREFIX = "schedule:set_interval_hours:"
    SCHEDULE_SET_INTERVAL_DAYS_PREFIX = "schedule:set_interval_days:"
    SCHEDULE_SET_DAYS_PREFIX = "schedule:set_days:"
    SCHEDULE_SET_DATES_PREFIX = "schedule:set_dates:"
    SCHEDULE_SET_PUBLISH_TIME_PREFIX = "schedule:set_publish_time:"
    SCHEDULE_DAY_SELECT_PREFIX = "schedule:day_select:"
    SCHEDULE_SAVE_DAYS = "schedule:save_days"
    SECURITY_LINKS_PREFIX = "security:links:"
    SECURITY_MENTIONS_PREFIX = "security:mentions:"
    SECURITY_WARN_PREFIX = "security:warn:"
    SECURITY_SLOWMODE_PREFIX = "security:slowmode:"
    SECURITY_BANNED_WORDS_MENU_PREFIX = "security:banned_words_menu:"
    SECURITY_WELCOME_PREFIX = "security:welcome:"
    SECURITY_GOODBYE_PREFIX = "security:goodbye:"
    SECURITY_MAIN = "security:main"
    SECURITY_CLOSE = "security:close"
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
    REFERRAL_COPY_LINK_PREFIX = "referral:copy_link:"
    REFERRAL_CLAIM_REWARD = "referral:claim_reward"
    REFERRAL_LIST = "referral:list"
    REMINDER_MENU = "reminder:menu"
    REMINDER_TOGGLE_SUB = "reminder:toggle_sub"
    REMINDER_TOGGLE_DAILY = "reminder:toggle_daily"
    REMINDER_TOGGLE_WEEKLY = "reminder:toggle_weekly"
    REMINDER_SET_DAYS = "reminder:set_days"
    REMINDER_SET_LANG = "reminder:set_lang"
    REMINDER_LANG_PREFIX = "reminder:lang:"
    TRANSLATION_MENU = "translation:menu"
    TRANSLATION_OFF = "translation:off"
    TRANSLATION_SET_PREFIX = "translation:set:"
    ADMIN_PANEL = "admin:panel"
    ADMIN_USERS = "admin:users"
    ADMIN_BANNED_USERS = "admin:banned_users"
    ADMIN_UNBAN_ALL_USERS = "admin:unban_all_users"
    ADMIN_ALL_CHANNELS = "admin:all_channels"
    ADMIN_BANNED_CHANNELS = "admin:banned_channels"
    ADMIN_ACTIVATE_ALL_CHANNELS = "admin:activate_all_channels"
    ADMIN_GROUPS = "admin:groups"
    ADMIN_BANNED_GROUPS = "admin:banned_groups"
    ADMIN_UNBAN_ALL_GROUPS = "admin:unban_all_groups"
    ADMIN_BOT_CHANNELS = "admin:bot_channels"
    ADMIN_BANNED_BOT_CHANNELS = "admin:banned_bot_channels"
    ADMIN_UNBAN_ALL_BOT_CHANNELS = "admin:unban_all_bot_channels"
    ADMIN_MONITOR_USERS = "admin:monitor_users"
    ADMIN_ADD_ADMIN = "admin:add_admin"
    ADMIN_REMOVE_ADMIN = "admin:remove_admin"
    ADMIN_RAM = "admin:ram"
    ADMIN_STATS = "admin:stats"
    ADMIN_METRICS = "admin:metrics"
    ADMIN_BACKUP = "admin:backup"
    ADMIN_RESTORE_BACKUP = "admin:restore_backup"
    ADMIN_RESTORE_BACKUP_SELECT_PREFIX = "admin:restore_backup_select:"
    ADMIN_BACKUP_SETTINGS = "admin:backup_settings"
    ADMIN_TOGGLE_AUTO_BACKUP = "admin:toggle_auto_backup"
    ADMIN_CHANGE_INTERVAL = "admin:change_interval"
    ADMIN_SEND_UPDATE = "admin:send_update"
    ADMIN_SET_UPDATE_CHANNEL = "admin:set_update_channel"
    ADMIN_SHOW_UPDATE_CHANNEL = "admin:show_update_channel"
    ADMIN_UPDATES = "admin:updates"
    ADMIN_FORCE_SUBSCRIBE = "admin:force_subscribe"
    ADMIN_SET_FORCE_CHANNEL = "admin:set_force_channel"
    ADMIN_BROADCAST = "admin:broadcast"
    ADMIN_CONFIRM_BROADCAST = "admin:confirm_broadcast"
    ADMIN_SUPPORT_TICKETS = "admin:support_tickets"
    ADMIN_DELETE_ALL_TICKETS = "admin:delete_all_tickets"
    ADMIN_CONFIRM_DELETE_TICKETS = "admin:confirm_delete_tickets"
    ADMIN_MANAGE_SENDCODE = "admin:manage_sendcode"
    ADMIN_SET_SENDCODE_USER = "admin:set_sendcode_user"
    ADMIN_SHOW_LOG_CHANNEL = "admin:show_log_channel"
    ADMIN_SET_LOG_CHANNEL = "admin:set_log_channel"
    ADMIN_REPLIES = "admin:replies"
    ADMIN_ADD_REPLY = "admin:add_reply"
    ADMIN_LIST_REPLIES = "admin:list_replies"
    ADMIN_DEL_REPLY = "admin:del_reply"
    ADMIN_BANNED_WORDS = "admin:banned_words"
    ADMIN_ADD_BANNED_WORD = "admin:add_banned_word"
    ADMIN_LIST_BANNED_WORDS = "admin:list_banned_words"
    ADMIN_REMOVE_BANNED_WORD = "admin:remove_banned_word"
    ADMIN_CREATE_CONTEST = "admin:create_contest"
    ADMIN_DECLARE_WINNER = "admin:declare_winner"
    PANEL_LOCK_PREFIX = "panel:lock:"
    PANEL_UNLOCK_PREFIX = "panel:unlock:"
    PANEL_CLOSE = "panel:close"
    CHECK_SUBSCRIBE = "check_subscribe"
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
    SECURITY_SELECT_GROUP = "security_select_group:"
    SECURITY_REFRESH_GROUPS = "security_refresh_groups"
    PENALTY_MENU = "penalty_menu"
    PENALTY_KICK = "penalty:kick"
    PENALTY_BAN = "penalty:ban"
    PENALTY_MUTE = "penalty:mute"
    PUBLISH_ALL_CHANNELS = "publish_all_channels"
    CHANNEL_STATS = "channel_stats"
    CHANNEL_GROWTH = "channel_growth"
    CHANNEL_STATS_REFRESH = "channel_stats_refresh"
    MY_CHANNEL_STATS = "my_channel_stats"
    ADMIN_TOGGLE_CHANNEL_BAN_PREFIX = "admin:toggle_channel_ban:"
    ADMIN_TOGGLE_GROUP_BAN_PREFIX = "admin:toggle_group_ban:"
    CONTESTS_MENU = "contests_menu"
    CONTEST_JOIN_PREFIX = "contest_join:"
    CONTEST_WINNERS = "contest_winners"
    CONTESTS_BACK = "contests_back"
    ADMIN_DEL_CONTEST_PREFIX = "admin:del_contest:"
    HIDDEN_ADMIN_ADD = "hidden_admin:add"
    HIDDEN_ADMIN_REMOVE_PREFIX = "hidden_admin:remove:"
    HIDDEN_ADMIN_LIST = "hidden_admin:list"
    ADMIN_AUTO_REPLY = "admin_auto_reply"
    ADMIN_AUTO_REPLY_SELECT_PREFIX = "admin_auto_reply_select:"
    AUTO_REPLY_MENU_PREFIX = "auto_reply_menu:"
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
    RULES_SHOW = "rules_show:"
    RULES_CONFIRM_RESET = "rules_confirm_reset:"
    RULES_CANCEL_RESET = "rules_cancel_reset:"

# ===================== تعريفات الحالات =====================
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
    WAITING_CONTEST_TITLE = auto()
    WAITING_CONTEST_DESCRIPTION = auto()
    WAITING_CONTEST_PRIZE = auto()
    WAITING_CONTEST_END_DATE = auto()
    WAITING_CONTEST_ANSWER = auto()
    WAITING_HIDDEN_ADMIN_ADD = auto()
    WAITING_HIDDEN_ADMIN_REMOVE = auto()
    WAITING_NSFW_THRESHOLD = auto()
    SUPPORT_MODE = auto()

# ===================== دوال قاعدة البيانات =====================
db_pool = None

async def init_db():
    global db_pool
    db_pool = await aiosqlite.connect(str(DB_PATH), timeout=DB_TIMEOUT)
    await db_pool.execute("PRAGMA journal_mode=WAL")
    await db_pool.execute("PRAGMA synchronous=NORMAL")
    await db_pool.execute("PRAGMA foreign_keys=ON")
    db_pool.row_factory = aiosqlite.Row
    
    # جدول المستخدمين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            auto_publish INTEGER DEFAULT 1,
            banned INTEGER DEFAULT 0,
            trial_used INTEGER DEFAULT 0,
            subscription_end TEXT DEFAULT NULL,
            active_channel INTEGER DEFAULT NULL,
            auto_recycle INTEGER DEFAULT 1,
            auto_reply_enabled INTEGER DEFAULT 1,
            referral_code TEXT DEFAULT NULL
        )
    """)
    
    # جدول قنوات المستخدمين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id TEXT,
            channel_name TEXT,
            created_at TIMESTAMP,
            banned INTEGER DEFAULT 0
        )
    """)
    
    # جدول المنشورات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_db_id INTEGER,
            text TEXT,
            media_type TEXT DEFAULT 'text',
            media_file_id TEXT,
            published INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            views_count INTEGER DEFAULT 0,
            created_at TIMESTAMP
        )
    """)
    
    # جدول الإعدادات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # جدول الردود
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS group_replies (
            keyword TEXT PRIMARY KEY,
            reply TEXT
        )
    """)
    
    # جدول إعدادات الأمان
    await db_pool.execute("""
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
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id INTEGER PRIMARY KEY
        )
    """)
    
    # جدول المجموعات
    await db_pool.execute("""
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
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_messages (
            user_id INTEGER,
            chat_id INTEGER,
            message_time TIMESTAMP
        )
    """)
    
    # جدول كاش المستخدمين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS users_cache (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_updated TIMESTAMP
        )
    """)
    
    # جدول التحذيرات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_warnings (
            user_id INTEGER,
            chat_id INTEGER,
            warnings INTEGER DEFAULT 0
        )
    """)
    
    # جدول الكلمات المحظورة
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS banned_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT,
            chat_id INTEGER,
            added_by INTEGER,
            added_at TIMESTAMP
        )
    """)
    
    # جدول المالكين المخفيين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS hidden_owner_groups (
            chat_id INTEGER PRIMARY KEY,
            owner_id INTEGER,
            is_hidden INTEGER DEFAULT 1
        )
    """)
    
    # جدول المشرفين المخفيين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS hidden_admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,
            added_by INTEGER,
            added_at TIMESTAMP
        )
    """)
    
    # جدول المستويات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_levels (
            user_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1
        )
    """)
    
    # جدول تذاكر الدعم
    await db_pool.execute("""
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
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS chat_locks (
            chat_id INTEGER PRIMARY KEY,
            locked INTEGER DEFAULT 0,
            locked_at TIMESTAMP,
            locked_by INTEGER
        )
    """)
    
    # جدول الجدولة
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            channel_db_id INTEGER PRIMARY KEY,
            schedule_type TEXT DEFAULT 'interval_minutes',
            interval_minutes INTEGER DEFAULT 12,
            interval_hours INTEGER DEFAULT 0,
            interval_days INTEGER DEFAULT 0,
            days_of_week TEXT,
            specific_dates TEXT,
            publish_time TEXT DEFAULT '00:00',
            next_publish_date TIMESTAMP
        )
    """)
    
    # جدول آخر نشر
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS last_publish (
            channel_db_id INTEGER PRIMARY KEY,
            last_publish_time TIMESTAMP
        )
    """)
    
    # جدول المنشورات المجدولة
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            publish_time TIMESTAMP NOT NULL,
            fail_count INTEGER DEFAULT 0
        )
    """)
    
    # جدول المستخدم المصرح بـ /sendcode
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS allowed_sendcode_user (
            id INTEGER PRIMARY KEY CHECK (id=1),
            user_id INTEGER
        )
    """)
    
    # جدول الإحالات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            referred_at TIMESTAMP,
            is_rewarded INTEGER DEFAULT 0
        )
    """)
    
    # جدول مكافآت الإحالات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS referral_rewards (
            user_id INTEGER PRIMARY KEY,
            referral_count INTEGER DEFAULT 0,
            total_reward_days INTEGER DEFAULT 0,
            claimed_reward_days INTEGER DEFAULT 0
        )
    """)
    
    # جدول إعدادات الإحالات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS referral_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # جدول إعدادات التذكيرات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_reminder_settings (
            user_id INTEGER PRIMARY KEY,
            subscription_reminder INTEGER DEFAULT 1,
            daily_stats_reminder INTEGER DEFAULT 0,
            weekly_report INTEGER DEFAULT 1,
            reminder_days_before INTEGER DEFAULT 3,
            last_reminder_sent INTEGER DEFAULT 0,
            notification_lang TEXT DEFAULT 'ar'
        )
    """)
    
    # جدول سجل الإجراءات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS moderation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            action TEXT,
            duration_minutes INTEGER,
            moderator_id INTEGER,
            reason TEXT,
            created_at TIMESTAMP
        )
    """)
    
    # جدول ترجمة المستخدمين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_translation (
            user_id INTEGER PRIMARY KEY,
            lang TEXT DEFAULT 'off'
        )
    """)
    
    # جدول المسابقات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS contests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            title TEXT,
            description TEXT,
            prize TEXT,
            end_date TIMESTAMP,
            status TEXT DEFAULT 'active',
            winner_id INTEGER,
            created_at TIMESTAMP,
            contest_type TEXT DEFAULT 'raffle'
        )
    """)
    
    # جدول مشاركي المسابقات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS contest_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            contest_id INTEGER,
            answer TEXT,
            joined_at TIMESTAMP
        )
    """)
    
    # جدول فائزي المسابقات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS contest_winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contest_id INTEGER,
            winner_id INTEGER,
            announced_at TIMESTAMP
        )
    """)
    
    # جدول إعدادات الردود التلقائية
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS auto_reply_settings (
            chat_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 1,
            only_admins INTEGER DEFAULT 0,
            ignore_bots INTEGER DEFAULT 1
        )
    """)
    
    # جدول قوانين المجموعة
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS group_rules (
            chat_id INTEGER PRIMARY KEY,
            rules_text TEXT,
            updated_by INTEGER,
            updated_at TIMESTAMP
        )
    """)
    
    # جدول قنوات البوت
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS bot_channels (
            channel_id INTEGER PRIMARY KEY,
            channel_name TEXT,
            added_by INTEGER,
            added_at TIMESTAMP,
            banned INTEGER DEFAULT 0
        )
    """)
    
    # جدول رموز التحقق
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS verification_codes (
            user_id INTEGER PRIMARY KEY,
            code TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # جدول إعدادات المجموعة
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id INTEGER PRIMARY KEY,
            settings TEXT DEFAULT '{}'
        )
    """)
    
    # إدخال البيانات الافتراضية
    await db_pool.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (PRIMARY_OWNER_ID,))
    await db_pool.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(DEFAULT_PUBLISH_INTERVAL_SECONDS),))
    await db_pool.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_ticket_number', '0')")
    
    await db_pool.commit()
    print("✅ قاعدة البيانات جاهزة")

async def execute_db(func):
    return await func(db_pool)

# ====================================================================
# ===================== الدوال الأساسية (مختصرة) =====================
# ====================================================================

# دوال المستخدمين
async def db_register_user(user_id: int) -> bool:
    async def _register(conn):
        cur = await conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if await cur.fetchone():
            return False
        await conn.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        await conn.commit()
        return True
    return await execute_db(_register)

async def db_get_all_users():
    async def _get(conn):
        cur = await conn.execute("SELECT user_id, banned FROM users ORDER BY user_id")
        return await cur.fetchall()
    return await execute_db(_get)

async def db_update_user_cache(user_id: int, username: str, first_name: str):
    async def _update(conn):
        await conn.execute("INSERT OR REPLACE INTO users_cache (user_id, username, first_name, last_updated) VALUES (?, ?, ?, ?)",
                          (user_id, username or "", first_name or "", utc_now_iso()))
        await conn.commit()
    return await execute_db(_update)

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

async def db_activate_subscription(user_id: int, days: int):
    async def _activate(conn):
        cur = await conn.execute("SELECT subscription_end FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        try:
            if row and row[0]:
                current_end = datetime.fromisoformat(row[0])
                if current_end > utc_now():
                    new_end = current_end + timedelta(days=days)
                else:
                    new_end = utc_now() + timedelta(days=days)
            else:
                new_end = utc_now() + timedelta(days=days)
        except:
            new_end = utc_now() + timedelta(days=days)
        await conn.execute("UPDATE users SET subscription_end=? WHERE user_id=?", (new_end.isoformat(), user_id))
        await conn.commit()
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

async def db_get_subscription_days_left(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT subscription_end FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0]:
            try:
                end_date = datetime.fromisoformat(row[0])
                days = (end_date - utc_now()).days
                return max(0, days)
            except:
                return 0
        return 0
    return await execute_db(_get)

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

# دوال قنوات المستخدمين
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
        return [(row[0], row[1], row[2] or row[1], row[3] if row[3] is not None else 0) for row in rows]
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

# دوال المنشورات (مختصرة)
async def db_save_posts(channel_db_id: int, posts: list) -> int:
    async def _save(conn):
        values = []
        for text_content, media_type, media_file_id in posts:
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

async def db_reset_posts_to_unpublished(channel_db_id: int, user_id: int = None):
    async def _reset(conn):
        await conn.execute("UPDATE posts SET published=0, fail_count=0 WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
    return await execute_db(_reset)

async def db_reset_all_posts_to_unpublished(channel_db_id: int) -> int:
    async def _reset(conn):
        await conn.execute("UPDATE posts SET published=0, fail_count=0 WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_reset)

async def db_unpublished_count(channel_db_id: int) -> int:
    async def _count(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_count)

# دوال المجموعات
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
            WHERE bg.added_by = ? OR EXISTS (SELECT 1 FROM hidden_owner_groups hog WHERE hog.chat_id = bg.chat_id AND hog.owner_id = ?)
            ORDER BY bg.chat_name
        """, (user_id, user_id))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_user_groups_count(user_id: int) -> int:
    groups = await db_get_user_groups(user_id)
    return len(groups)

# دوال الجدولة (مختصرة)
async def db_save_schedule(channel_db_id: int, schedule_type: str, interval_minutes: int = None, 
                           interval_hours: int = None, interval_days: int = None, 
                           days_of_week: str = None, specific_dates: str = None, 
                           publish_time: str = None):
    async def _save(conn):
        await conn.execute("""
            INSERT OR REPLACE INTO schedule (
                channel_db_id, schedule_type, interval_minutes, interval_hours,
                interval_days, days_of_week, specific_dates, publish_time, next_publish_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """, (channel_db_id, schedule_type, interval_minutes, interval_hours,
              interval_days, days_of_week, specific_dates, publish_time or "00:00"))
        await conn.commit()
    return await execute_db(_save)

async def db_get_schedule(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("""
            SELECT schedule_type, interval_minutes, interval_hours, interval_days,
                   days_of_week, specific_dates, publish_time, next_publish_date
            FROM schedule WHERE channel_db_id=?
        """, (channel_db_id,))
        row = await cur.fetchone()
        if row:
            return {
                'type': row[0] or 'interval_minutes',
                'interval_minutes': row[1] or 12,
                'interval_hours': row[2] or 0,
                'interval_days': row[3] or 0,
                'days_of_week': row[4] or '[]',
                'specific_dates': row[5] or '[]',
                'publish_time': row[6] or '00:00',
                'next_publish_date': row[7]
            }
        return {
            'type': 'interval_minutes',
            'interval_minutes': 12,
            'interval_hours': 0,
            'interval_days': 0,
            'days_of_week': '[]',
            'specific_dates': '[]',
            'publish_time': '00:00',
            'next_publish_date': None
        }
    return await execute_db(_get)

async def db_set_next_publish_date(channel_db_id: int, next_date: datetime):
    async def _set(conn):
        if next_date:
            await conn.execute("UPDATE schedule SET next_publish_date=? WHERE channel_db_id=?", (next_date.isoformat(), channel_db_id))
        else:
            await conn.execute("UPDATE schedule SET next_publish_date=NULL WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
    return await execute_db(_set)

# دوال الإحصائيات (مختصرة)
async def db_stats():
    async def _stats(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM users")
        total = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM users WHERE banned=1")
        banned = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE published=0")
        posts = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM bot_groups")
        groups = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM user_channels")
        channels = (await cur.fetchone())[0]
        return total, banned, posts, groups, channels
    return await execute_db(_stats)

async def db_get_channel_stats(channel_db_id: int) -> dict:
    async def _get_stats(conn):
        cur = await conn.execute("""
            SELECT
                COUNT(*) as total_posts,
                SUM(CASE WHEN published = 1 THEN 1 ELSE 0 END) as published_posts,
                SUM(CASE WHEN published = 0 THEN 1 ELSE 0 END) as unpublished_posts,
                SUM(views_count) as total_views,
                AVG(views_count) as avg_views,
                MAX(created_at) as last_post_time,
                MIN(created_at) as first_post_time
            FROM posts
            WHERE channel_db_id = ?
        """, (channel_db_id,))
        row = await cur.fetchone()
        if not row or row[0] == 0:
            return {
                'total_posts': 0,
                'published_posts': 0,
                'unpublished_posts': 0,
                'total_views': 0,
                'avg_views': 0,
                'last_post_time': None,
                'first_post_time': None
            }
        return {
            'total_posts': row[0] or 0,
            'published_posts': row[1] or 0,
            'unpublished_posts': row[2] or 0,
            'total_views': row[3] or 0,
            'avg_views': round(row[4], 2) if row[4] else 0,
            'last_post_time': row[5],
            'first_post_time': row[6]
        }
    return await execute_db(_get_stats)

async def db_get_channel_growth(channel_db_id: int, days: int = 30) -> dict:
    async def _get_growth(conn):
        start_date = (utc_now() - timedelta(days=days)).isoformat()
        cur = await conn.execute("""
            SELECT
                date(created_at) as post_date,
                COUNT(*) as count,
                SUM(views_count) as views
            FROM posts
            WHERE channel_db_id = ? AND created_at >= ?
            GROUP BY date(created_at)
            ORDER BY post_date
        """, (channel_db_id, start_date))
        rows = await cur.fetchall()
        dates = []
        counts = []
        views = []
        total_posts = 0
        total_views = 0
        for row in rows:
            dates.append(row[0])
            counts.append(row[1] or 0)
            views.append(row[2] or 0)
            total_posts += row[1] or 0
            total_views += row[2] or 0
        return {'dates': dates, 'counts': counts, 'views': views, 'total_posts': total_posts, 'total_views': total_views}
    return await execute_db(_get_growth)

# دوال الإعدادات العامة (مختصرة)
async def db_get_publish_interval() -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='publish_interval'")
        row = await cur.fetchone()
        return int(row[0]) if row else DEFAULT_PUBLISH_INTERVAL_SECONDS
    return await execute_db(_get)

async def db_set_publish_interval_seconds(seconds: int, admin_id: int, is_admin: bool = False):
    if not is_admin and admin_id != PRIMARY_OWNER_ID:
        return False
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(seconds),))
        await conn.commit()
    return await execute_db(_set)

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

async def db_set_allowed_sendcode_user(user_id: int):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO allowed_sendcode_user (id, user_id) VALUES (1, ?)", (user_id,))
        await conn.commit()
    return await execute_db(_set)

# دوال الكلمات المحظورة
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

# دوال الأمان
async def db_get_security_settings(chat_id: int):
    async def _get(conn):
        cur = await conn.execute("""
            SELECT delete_links, delete_mentions, warn_message, slow_mode, slow_mode_seconds,
                   welcome_enabled, welcome_text, goodbye_enabled, goodbye_text,
                   delete_banned_words, auto_penalty, auto_mute_duration
            FROM group_security WHERE chat_id=?
        """, (chat_id,))
        row = await cur.fetchone()
        if row:
            return {
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
        return {
            'links': False, 'mentions': False, 'warn': True, 'slow_mode': False,
            'slow_mode_seconds': 5, 'welcome_enabled': False,
            'welcome_text': "مرحباً {user} في {chat} 🤍",
            'goodbye_enabled': False, 'goodbye_text': "وداعاً {user} 👋",
            'delete_banned_words': False, 'auto_penalty': 'none', 'auto_mute_duration': 60
        }
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
                INSERT INTO group_security (
                    chat_id, delete_links, delete_mentions, warn_message,
                    slow_mode, slow_mode_seconds, welcome_enabled, welcome_text,
                    goodbye_enabled, goodbye_text, delete_banned_words,
                    auto_penalty, auto_mute_duration
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

# دوال الصلاحيات
_admin_cache = {}

async def check_admin_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update or not update.effective_user:
        return False
    user_id = update.effective_user.id
    if user_id == PRIMARY_OWNER_ID:
        return True
    chat = update.effective_chat
    if not chat or chat.type == 'private':
        return False
    if chat.type in ['group', 'supergroup']:
        chat_id = chat.id
        cache_key = f"{chat_id}:{user_id}"
        if cache_key in _admin_cache:
            return _admin_cache[cache_key]
        # تحقق من المالك المخفي
        async def _check_hidden(conn):
            cur = await conn.execute("SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?", (chat_id, user_id))
            if await cur.fetchone():
                return True
            cur = await conn.execute("SELECT 1 FROM hidden_admins WHERE chat_id=? AND admin_id=?", (chat_id, user_id))
            return await cur.fetchone() is not None
        if await execute_db(_check_hidden):
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

async def is_telegram_admin(bot, chat_id: int, user_id: int, update: Update = None) -> bool:
    try:
        if user_id == PRIMARY_OWNER_ID:
            return True
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ['creator', 'administrator']
    except:
        return False

async def is_bot_admin(user_id: int) -> bool:
    if user_id == PRIMARY_OWNER_ID:
        return True
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM bot_admins WHERE user_id=?", (user_id,))
        return await cur.fetchone() is not None
    return await execute_db(_check)

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

def invalidate_user_cache(user_id: int = None, chat_id: int = None):
    if user_id is not None:
        keys_to_remove = [k for k in list(_admin_cache.keys()) if str(user_id) in k]
        for key in keys_to_remove:
            del _admin_cache[key]
    elif chat_id is not None:
        keys_to_remove = [k for k in list(_admin_cache.keys()) if k.startswith(f"{chat_id}:")]
        for key in keys_to_remove:
            del _admin_cache[key]
    else:
        _admin_cache.clear()

# دوال الإجراءات المتقدمة
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
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False
        )
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
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
        await bot.restrict_chat_member(chat_id, user_id, permissions)
        return True, f"✅ تم إلغاء كتم المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل إلغاء الكتم: {str(e)[:100]}"

async def get_moderation_log(chat_id: int, limit: int = 20) -> str:
    async def _get_log(conn):
        cur = await conn.execute("""
            SELECT user_id, action, duration_minutes, reason, created_at
            FROM moderation_log
            WHERE chat_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (chat_id, limit))
        return await cur.fetchall()
    logs = await execute_db(_get_log)
    if not logs:
        return "📭 لا توجد سجلات إجراءات"
    text = "📜 **سجل إجراءات المجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, action, duration, reason, created_at in logs:
        try:
            dt = datetime.fromisoformat(created_at)
            dt_mecca = utc_to_mecca(dt)
            time_str = dt_mecca.strftime("%Y-%m-%d %H:%M")
        except:
            time_str = created_at[:16] if created_at else "?"
        duration_text = ""
        if action == 'mute' and duration:
            if duration == -1:
                duration_text = " (دائم)"
            elif duration < 60:
                duration_text = f" ({duration} دقيقة)"
            elif duration < 1440:
                duration_text = f" ({duration//60} ساعة)"
            else:
                duration_text = f" ({duration//1440} يوم)"
        reason_text = f"\n   📝 السبب: {reason[:50]}" if reason else ""
        text += f"• `{user_id}` → {action}{duration_text}{reason_text}\n   🕐 {time_str}\n\n"
    return text

# دوال المستويات
LEVEL_REQUIREMENTS = {
    1: 0, 2: 100, 3: 250, 4: 500, 5: 1000,
    6: 2000, 7: 3500, 8: 5000, 9: 7500, 10: 10000
}

async def db_get_user_level(user_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT points, level FROM user_levels WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row:
            return {'points': row[0], 'level': row[1]}
        return {'points': 0, 'level': 1}
    return await execute_db(_get)

async def db_update_user_level(user_id: int, points: int, level: int):
    async def _update(conn):
        await conn.execute("INSERT OR REPLACE INTO user_levels (user_id, points, level) VALUES (?,?,?)", (user_id, points, level))
        await conn.commit()
    return await execute_db(_update)

async def get_top_users(limit: int = 10):
    async def _get(conn):
        cur = await conn.execute("SELECT user_id, points, level FROM user_levels ORDER BY points DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

# دوال الكيبورد الأساسية
async def get_main_keyboard(user_id: int):
    channels = await db_get_channels(user_id)
    active = None
    if channels:
        active = await db_get_active_channel(user_id)
        if active is None:
            active = channels[0][0]
            await db_set_active_channel(user_id, active)
    
    cnt = 0
    ch_display = "لا توجد قنوات"
    if active is not None:
        cnt = await db_unpublished_count(active)
        ch_info = await db_get_channel_info(active)
        if ch_info:
            ch_name = ch_info[1] if ch_info[1] else ch_info[0]
            ch_display = f"{ch_name} ({ch_info[0]})"
    
    my_groups = await db_get_user_groups_count(user_id)
    has_sub = await db_has_active_subscription(user_id)
    sub_text = "✅ مفعل" if has_sub else "❌ غير مفعل"
    auto_status = await db_auto_status(user_id)
    auto_text = "مفعل" if auto_status else "معطل"
    
    title = f"🌿 **{BOT_NAME}**\n👤 المعرف: `{user_id}`\n"
    title += f"👥 مجموعاتي: {my_groups}\n"
    title += f"💎 الاشتراك: {sub_text}\n"
    title += f"📡 القناة النشطة: {ch_display}\n"
    title += f"📝 منشورات غير منشورة: {cnt}\n"
    title += f"🔄 النشر التلقائي: {auto_text}"
    
    keyboard = []
    keyboard.append([
        InlineKeyboardButton("👥 مجموعاتي", callback_data="groups:my_groups"),
        InlineKeyboardButton("➕ إضافة قناة", callback_data="channels:add")
    ])
    keyboard.append([
        InlineKeyboardButton("📡 قنواتي", callback_data="channels:my_channels"),
        InlineKeyboardButton("⚙️ إعدادات", callback_data="settings:menu")
    ])
    if channels:
        keyboard.append([
            InlineKeyboardButton("📥 إضافة 15 منشور", callback_data="posts:add_15"),
            InlineKeyboardButton("📤 نشر واحد", callback_data="posts:publish_one")
        ])
        keyboard.append([
            InlineKeyboardButton("📋 منشوراتي", callback_data="posts:my_posts"),
            InlineKeyboardButton("♻️ إعادة تدوير", callback_data="posts:recycle")
        ])
        keyboard.append([
            InlineKeyboardButton(f"📊 منشورات غير منشورة ({cnt})", callback_data="stats:pending"),
            InlineKeyboardButton("📈 إحصائياتي", callback_data="stats:full")
        ])
        if active is not None:
            keyboard.append([
                InlineKeyboardButton("📅 جدولة", callback_data=f"schedule:menu:{active}"),
                InlineKeyboardButton("📊 إحصائيات القناة", callback_data=f"channel_stats:{active}")
            ])
        keyboard.append([
            InlineKeyboardButton("📊 ملخص قنواتي", callback_data="my_channel_stats"),
            InlineKeyboardButton("📈 رتبتي", callback_data="rank")
        ])
        keyboard.append([
            InlineKeyboardButton("🏆 أفضل 10", callback_data="top"),
            InlineKeyboardButton("📅 جدولة منشور", callback_data="schedule_post")
        ])
        keyboard.append([
            InlineKeyboardButton("📤 نشر في الكل", callback_data="publish_all_channels")
        ])
    keyboard.append([
        InlineKeyboardButton("❓ مساعدة", callback_data="help"),
        InlineKeyboardButton("🎁 تجربة مجانية", callback_data="trial")
    ])
    keyboard.append([
        InlineKeyboardButton("💎 اشتراك", callback_data="subscribe:menu"),
        InlineKeyboardButton("👨‍💻 المطور", callback_data="developer")
    ])
    keyboard.append([
        InlineKeyboardButton("🌐 اللغة", callback_data="language"),
        InlineKeyboardButton("📞 الدعم", callback_data="support:menu")
    ])
    keyboard.append([
        InlineKeyboardButton("🔗 الإحالات", callback_data="referral:menu"),
        InlineKeyboardButton("🔔 التذكيرات", callback_data="reminder:menu")
    ])
    keyboard.append([
        InlineKeyboardButton("🌍 الترجمة", callback_data="translation:menu")
    ])
    keyboard.append([
        InlineKeyboardButton("🏆 المسابقات", callback_data="contests_menu")
    ])
    is_admin = (user_id == PRIMARY_OWNER_ID) or (await is_bot_admin(user_id))
    if is_admin:
        keyboard.append([
            InlineKeyboardButton("👑 لوحة الأدمن", callback_data="admin:panel")
        ])
    keyboard.append([
        InlineKeyboardButton("➕ إضافة إلى مجموعة", url=f"https://t.me/{BOT_USERNAME}?startgroup")
    ])
    return InlineKeyboardMarkup(keyboard), title, active

# ====================================================================
# ===================== الأوامر الأساسية =====================
# ====================================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db_register_user(user.id)
    await db_update_user_cache(user.id, user.username or "", user.first_name or "")
    keyboard, title, active = await get_main_keyboard(user.id)
    if active:
        await db_set_active_channel(user.id, active)
    await safe_send(context.bot, user.id, title, reply_markup=keyboard)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = "❓ **المساعدة**\n\n"
    text += "/start - القائمة الرئيسية\n"
    text += "/help - المساعدة\n"
    text += "/rules - قوانين المجموعة\n"
    text += "/set_rules - تعيين قوانين (للمشرفين)\n"
    text += "/reset_rules - إعادة تعيين القوانين\n"
    text += "/syncgroup - تفعيل المجموعة\n"
    text += "/security - إعدادات الأمان\n"
    text += "/trial - تجربة مجانية\n"
    text += "/subscribe - الاشتراك\n"
    text += "/developer - المطور\n"
    text += "/updates - التحديثات\n"
    text += "/language - تغيير اللغة\n"
    text += "/support - الدعم\n"
    text += "/panel - لوحة التحكم\n"
    text += "/schedule - جدولة منشور\n"
    text += "/lock - قفل المجموعة\n"
    text += "/unlock - فتح المجموعة\n"
    text += "/stats - إحصائيات القناة\n"
    text += "/contests - المسابقات\n"
    text += "/ban - حظر مستخدم\n"
    text += "/mute - كتم مستخدم\n"
    text += "/warn - تحذير مستخدم\n"
    text += "/kick - طرد مستخدم\n"
    text += "/rank - رتبتك\n"
    text += "/top - أفضل 10"
    await safe_send(context.bot, user_id, text)

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat = update.effective_chat
    rules = DEFAULT_RULES
    if chat and chat.type in ['group', 'supergroup']:
        custom = await db_get_group_rules(chat.id)
        if custom:
            rules = custom
    await safe_send(context.bot, user_id, rules)

async def set_rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def syncgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    chat_name = update.effective_chat.title or "بدون اسم"
    user_id = update.effective_user.id
    await db_register_group(chat_id, chat_name, user_id, update.effective_chat.username)
    await db_register_hidden_owner_group(chat_id, user_id)
    await update.message.reply_text("✅ **تم تفعيل المجموعة بنجاح!**")

async def security_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        if not await check_admin_access(update, context):
            await update.message.reply_text(get_text(user_id, 'admin_only'))
            return
        settings = await db_get_security_settings(chat_id)
        text = f"🔐 **إعدادات الأمان**\n━━━━━━━━━━━━━━━━━━━━━━\n🔗 حذف الروابط: {'✅' if settings['links'] else '❌'}\n@ حذف المعرفات: {'✅' if settings['mentions'] else '❌'}\n⏱️ وضع بطيء: {'✅' if settings['slow_mode'] else '❌'}\n🎯 ترحيب: {'✅' if settings['welcome_enabled'] else '❌'}"
        await update.message.reply_text(text)
        return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await safe_send(context.bot, user_id, "📭 لا توجد مجموعات مسجلة")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        keyboard.append([InlineKeyboardButton(f"📌 {gname[:30]}", callback_data=f"security_select_group:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
    await safe_send(context.bot, user_id, "🔐 **اختر مجموعة:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def trial_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await db_has_used_trial(user_id):
        await update.message.reply_text(get_text(user_id, 'trial_used'))
        return
    if await db_has_active_subscription(user_id):
        await update.message.reply_text(get_text(user_id, 'already_subscribed'))
        return
    await db_activate_trial(user_id)
    await update.message.reply_text(get_text(user_id, 'trial'))

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if await db_has_active_subscription(user_id):
        days = await db_get_subscription_days_left(user_id)
        await update.message.reply_text(f"✅ اشتراكك مفعل، متبقي {days} يوم")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data="buy:subscription_1"),
         InlineKeyboardButton("⭐ 2 يوم - 9 نجوم", callback_data="buy:subscription_2")],
        [InlineKeyboardButton("⭐ شهر (30 يوم) - 50 نجمة", callback_data="buy:subscription_30"),
         InlineKeyboardButton("⭐ 3 أشهر (90 يوم) - 120 نجمة", callback_data="buy:subscription_90")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await update.message.reply_text(get_text(user_id, 'subscribe'), reply_markup=keyboard)

async def developer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = f"👨‍💻 **المطور**\n@RelaxMgr\n🤖 {BOT_NAME}"
    await safe_send(context.bot, user_id, text)

async def updates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    updates_channel = await db_get_updates_channel()
    if updates_channel:
        text = f"📢 **قناة التحديثات**\n@{updates_channel}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 افتح القناة", url=f"https://t.me/{updates_channel}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ])
        await safe_send(context.bot, user_id, text, reply_markup=keyboard)
    else:
        await safe_send(context.bot, user_id, "📢 **لم يتم تعيين قناة التحديثات بعد**")

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
         InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await safe_send(context.bot, user_id, get_text(user_id, 'welcome'), reply_markup=keyboard)

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 كتابة تذكرة", callback_data="support:ticket")],
        [InlineKeyboardButton("❓ المساعدة", callback_data="support:help")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await safe_send(context.bot, user_id, "📞 **مرحباً بك في قسم الدعم**\nاختر أحد الخيارات:", reply_markup=keyboard)

async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type in ['group', 'supergroup']:
        chat = update.effective_chat
        chat_id = chat.id
        if not await check_admin_access(update, context):
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
            return
        current_lock_status = await is_chat_locked(chat_id)
        lock_status_text = "🔒 مقفلة" if current_lock_status else "🔓 مفتوحة"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔒 قفل المجموعة", callback_data=f"panel:lock:{chat_id}"),
             InlineKeyboardButton("🔓 فتح المجموعة", callback_data=f"panel:unlock:{chat_id}")],
            [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"advanced_actions:{chat_id}"),
             InlineKeyboardButton("🔙 إغلاق اللوحة", callback_data="panel:close")]
        ])
        await update.message.reply_text(
            f"🔧 **لوحة تحكم المجموعة**\n━━━━━━━━━━━━━━\n📌 **المجموعة:** {chat.title}\n🔐 **الحالة:** {lock_status_text}",
            reply_markup=kb
        )
        return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        keyboard.append([InlineKeyboardButton(f"📌 {gname[:30]}", callback_data=f"advanced_actions:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
    await update.message.reply_text("🔧 **لوحة التحكم**\nاختر مجموعة:", reply_markup=InlineKeyboardMarkup(keyboard))

async def schedule_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args or []
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
        chat_id = update.effective_chat.id if update.effective_chat.type in ['group', 'supergroup'] else None
        if not chat_id:
            await update.message.reply_text("⚠️ هذا الأمر يعمل في المجموعات فقط!")
            return
        await db_add_scheduled_post(chat_id, text, utc_dt)
        await update.message.reply_text(f"✅ **تم جدولة المنشور!**\n📅 {date_str} 🕐 {time_str} (بتوقيت مكة)")
    except ValueError:
        await update.message.reply_text("❌ صيغة التاريخ أو الوقت غير صحيحة!")

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = None
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        if not await check_admin_access(update, context):
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
            return
        await db_set_chat_lock(chat_id, True, user_id)
        await update.message.reply_text("🔒 تم قفل المجموعة")
        return
    args = context.args or []
    if args and args[0].lstrip('-').isdigit():
        chat_id = int(args[0])
        if await is_telegram_admin(context.bot, chat_id, user_id):
            await db_set_chat_lock(chat_id, True, user_id)
            await update.message.reply_text("🔒 تم قفل المجموعة")
            return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        keyboard.append([InlineKeyboardButton(f"🔒 {gname[:30]}", callback_data=f"panel:lock:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
    await update.message.reply_text("🔒 **اختر مجموعة لقفلها:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = None
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        if not await check_admin_access(update, context):
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
            return
        await db_set_chat_lock(chat_id, False)
        await update.message.reply_text("🔓 تم فتح المجموعة")
        return
    args = context.args or []
    if args and args[0].lstrip('-').isdigit():
        chat_id = int(args[0])
        if await is_telegram_admin(context.bot, chat_id, user_id):
            await db_set_chat_lock(chat_id, False)
            await update.message.reply_text("🔓 تم فتح المجموعة")
            return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        keyboard.append([InlineKeyboardButton(f"🔓 {gname[:30]}", callback_data=f"panel:unlock:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
    await update.message.reply_text("🔓 **اختر مجموعة لفتحها:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await safe_send(context.bot, user_id, text)
        return
    text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📝 إجمالي المنشورات: {stats['total_posts']}\n"
    text += f"✅ المنشورة: {stats['published_posts']}\n"
    text += f"⏳ غير المنشورة: {stats['unpublished_posts']}\n"
    text += f"👁️ إجمالي المشاهدات: {stats['total_views']}\n"
    text += f"📊 متوسط المشاهدات: {stats['avg_views']}\n"
    await safe_send(context.bot, user_id, text)

async def contests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    contests = await db_get_active_contests(limit=10)
    if not contests:
        text = "🏆 **المسابقات**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد مسابقات فعالة حالياً."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]])
        await safe_send(context.bot, user_id, text, reply_markup=keyboard)
        return
    text = "🏆 **المسابقات الفعالة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for contest_id, title, description, prize, end_date, contest_type in contests:
        try:
            end_dt = datetime.fromisoformat(end_date)
            end_mecca = utc_to_mecca(end_dt)
            end_str = end_mecca.strftime("%Y-%m-%d %H:%M")
        except:
            end_str = end_date
        text += f"📌 **{title}**\n🎁 {prize}\n📅 ينتهي: {end_str}\n"
        text += f"🔗 `/join_contest {contest_id}`\n\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back")]])
    await safe_send(context.bot, user_id, text, reply_markup=keyboard)

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = await db_get_user_level(user_id)
    points = data['points']
    level = data['level']
    next_points = LEVEL_REQUIREMENTS.get(level + 1, points)
    points_needed = next_points - points if next_points > points else 0
    text = f"📊 **رتبتك الحالية**\n━━━━━━━━━━━━━━\n⭐ **المستوى:** {level}\n📈 **النقاط:** {points}\n📌 **المتبقي للمستوى التالي:** {points_needed}"
    await safe_send(context.bot, user_id, text)

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def sendcode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال رمز التحقق للمستخدم"""
    user_id = update.effective_user.id
    allowed_user = await db_get_allowed_sendcode_user()
    if allowed_user and user_id != allowed_user and user_id != PRIMARY_OWNER_ID:
        await update.message.reply_text("❌ غير مصرح لك باستخدام هذا الأمر.")
        return
    try:
        code = str(random.randint(100000, 999999))
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
# ===================== الكولباك الأساسية =====================
# ====================================================================

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    keyboard, title, active = await get_main_keyboard(user_id)
    if active:
        await db_set_active_channel(user_id, active)
    await safe_edit(query, title, reply_markup=keyboard)

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu_callback(update, context)

async def cancel_session_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data.pop('state', None)
    await safe_edit(query, get_text(user_id, 'cancelled'))
    await main_menu_callback(update, context)

async def add_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_CHANNEL_ID
    await safe_edit(query, get_text(user_id, 'send_channel_id'))

async def my_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    channels = await db_get_channels(user_id)
    if not channels:
        await safe_edit(query, get_text(user_id, 'no_channels_list'))
        return
    keyboard = []
    for ch in channels:
        ch_db_id, ch_tele_id, ch_name, banned = ch
        keyboard.append([
            InlineKeyboardButton(f"📢 {ch_name}", callback_data=f"channels:select:{ch_db_id}"),
            InlineKeyboardButton("🗑️ حذف", callback_data=f"channels:delete:{ch_db_id}")
        ])
    keyboard.append([InlineKeyboardButton("➕ إضافة قناة", callback_data="channels:add")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
    await safe_edit(query, "📡 **قنواتي**", reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    if await db_delete_channel_by_id(user_id, ch_db_id):
        await safe_edit(query, get_text(user_id, 'channel_deleted'))
    else:
        await safe_edit(query, get_text(user_id, 'delete_failed'))
    await my_channels_callback(update, context)

async def select_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    await db_set_active_channel(user_id, ch_db_id)
    await main_menu_callback(update, context)

async def add_15_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data['state'] = UserState.ADDING_POSTS
    context.user_data['session_posts'] = []
    context.user_data['session_target'] = 15
    await safe_edit(query, "📥 أرسل المنشورات (نصوص، صور، فيديوهات)\nالحد الأقصى: 15 منشور")

async def publish_one_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    if not active:
        await safe_edit(query, "⚠️ اختر قناة أولاً")
        return
    post = await db_get_next_post(active)
    if not post:
        await safe_edit(query, get_text(user_id, 'no_posts'))
        return
    ch_info = await db_get_channel_info(active)
    try:
        if post['media_type'] == 'photo' and post['media_file_id']:
            await context.bot.send_photo(ch_info[0], post['media_file_id'], caption=post['text'] if post['text'] else None)
        else:
            await context.bot.send_message(ch_info[0], post['text'])
        await db_mark_published(post['id'])
        await safe_edit(query, get_text(user_id, 'post_published'))
    except Exception as e:
        await safe_edit(query, get_text(user_id, 'publish_error').format(str(e)[:100]))

async def my_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    if not active:
        await safe_edit(query, "⚠️ اختر قناة أولاً")
        return
    posts = await db_get_user_posts_for_channel(active, limit=15)
    if not posts:
        await safe_edit(query, get_text(user_id, 'no_posts'))
        return
    text = "📋 **منشوراتي غير المنشورة**\n"
    for pid, ptext, media_type in posts[:10]:
        short = ptext[:50] + "..." if len(ptext) > 50 else ptext
        text += f"• {short}\n🆔 {pid}\n\n"
    await safe_edit(query, text)

async def recycle_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    if active:
        await db_reset_posts_to_unpublished(active)
        await safe_edit(query, "♻️ **تم إعادة تدوير المنشورات بنجاح!**")
    else:
        await safe_edit(query, "⚠️ اختر قناة أولاً")

async def my_pending_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    unpublished = await db_get_user_unpublished_posts(user_id)
    total = await db_get_user_total_posts(user_id)
    text = f"📊 **المنشورات غير المنشورة:** {unpublished}\n📝 **إجمالي المنشورات:** {total}"
    await safe_edit(query, text)

async def my_full_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    channels = await db_get_user_channels_count(user_id)
    total = await db_get_user_total_posts(user_id)
    unpublished = await db_get_user_unpublished_posts(user_id)
    groups = await db_get_user_groups_count(user_id)
    auto = "مفعل" if await db_auto_status(user_id) else "معطل"
    text = f"📊 **إحصائياتي**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 القنوات: {channels}\n📝 إجمالي المنشورات: {total}\n⏳ غير المنشورة: {unpublished}\n👥 المجموعات: {groups}\n🔄 النشر التلقائي: {auto}"
    await safe_edit(query, text)

async def my_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    groups = await db_get_user_groups(user_id)
    if not groups:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
        ])
        await safe_edit(query, "📭 لا توجد مجموعات مسجلة", reply_markup=keyboard)
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        keyboard.append([
            InlineKeyboardButton(f"📌 {gname[:30]}", callback_data=f"groups:settings:{gid}")
        ])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
    await safe_edit(query, "👥 **مجموعاتي**", reply_markup=InlineKeyboardMarkup(keyboard))

async def group_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, get_text(user_id, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    text = f"⚙️ **إعدادات المجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\n🔗 حذف الروابط: {'✅' if settings['links'] else '❌'}\n@ حذف المعرفات: {'✅' if settings['mentions'] else '❌'}\n⏱️ وضع بطيء: {'✅' if settings['slow_mode'] else '❌'}\n🎯 ترحيب: {'✅' if settings['welcome_enabled'] else '❌'}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔐 الأمان", callback_data=f"security:main:{chat_id}"),
         InlineKeyboardButton("⚖️ العقوبات", callback_data=f"penalty_menu:{chat_id}")],
        [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"advanced_actions:{chat_id}"),
         InlineKeyboardButton("📜 سجل الإجراءات", callback_data=f"group_action:log:{chat_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    auto = await db_auto_status(user_id)
    auto_btn = "معطل" if auto else "مفعل"
    recycle = await db_get_auto_recycle(user_id)
    recycle_btn = "مفعل" if recycle else "معطل"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{auto_btn} النشر التلقائي", callback_data="settings:toggle_auto_publish")],
        [InlineKeyboardButton(f"♻️ إعادة التدوير: {recycle_btn}", callback_data="settings:toggle_auto_recycle")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await safe_edit(query, get_text(user_id, 'settings'), reply_markup=keyboard)

async def toggle_auto_publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    cur = await db_auto_status(user_id)
    await db_set_auto(user_id, not cur)
    status = "مفعل" if not cur else "معطل"
    await safe_edit(query, f"✅ تم تغيير حالة النشر التلقائي إلى: {status}")
    await main_menu_callback(update, context)

async def settings_toggle_auto_recycle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    cur = await db_get_auto_recycle(user_id)
    new_status = not cur
    await db_set_auto_recycle(user_id, new_status)
    status = "مفعل" if new_status else "معطل"
    await safe_edit(query, f"✅ تم تغيير إعادة التدوير التلقائي إلى: {status}")
    await settings_menu_callback(update, context)

# ====================================================================
# ===================== معالج الأخطاء =====================
# ====================================================================

async def global_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        error = context.error
        error_id = secrets.token_hex(4)
        print(f"❌ [{error_id}] {error}")
        if isinstance(error, (TimedOut, NetworkError, Conflict, Forbidden)):
            return
        if update and update.effective_user:
            try:
                await safe_send(context.bot, update.effective_user.id, f"❌ حدث خطأ (الرمز: {error_id})")
            except:
                pass
        if PRIMARY_OWNER_ID:
            try:
                await context.bot.send_message(
                    PRIMARY_OWNER_ID,
                    f"🚨 **خطأ في البوت**\nالرمز: {error_id}\nالخطأ: {str(error)[:200]}"
                )
            except:
                pass
    except Exception as e:
        print(f"❌ فشل معالج الأخطاء نفسه: {e}")

# ====================================================================
# ===================== الوظيفة الرئيسية =====================
# ====================================================================

async def main():
    await init_db()
    
    if USE_PROXY:
        request = HTTPXRequest(proxy_url=PROXY_URL)
        app = Application.builder().token(TOKEN).request(request).build()
    else:
        app = Application.builder().token(TOKEN).build()
    
    app.add_error_handler(global_error_handler)
    
    # الأوامر الأساسية
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("rules", rules_command))
    app.add_handler(CommandHandler("set_rules", set_rules_command))
    app.add_handler(CommandHandler("reset_rules", reset_rules_command))
    app.add_handler(CommandHandler("syncgroup", syncgroup_command))
    app.add_handler(CommandHandler("security", security_command))
    app.add_handler(CommandHandler("trial", trial_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("developer", developer_command))
    app.add_handler(CommandHandler("updates", updates_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("support", support_command))
    app.add_handler(CommandHandler("panel", panel_command))
    app.add_handler(CommandHandler("schedule", schedule_post_command))
    app.add_handler(CommandHandler("lock", lock_command))
    app.add_handler(CommandHandler("unlock", unlock_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("contests", contests_command))
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("warn", warn_command))
    app.add_handler(CommandHandler("kick", kick_command))
    app.add_handler(CommandHandler("rank", rank_command))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("sendcode", sendcode_command))
    
    # الكولباك الأساسية
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(cancel_session_callback, pattern="^cancel_session$"))
    app.add_handler(CallbackQueryHandler(add_channel_callback, pattern="^channels:add$"))
    app.add_handler(CallbackQueryHandler(my_channels_callback, pattern="^channels:my_channels$"))
    app.add_handler(CallbackQueryHandler(delete_channel_callback, pattern="^channels:delete:"))
    app.add_handler(CallbackQueryHandler(select_channel_callback, pattern="^channels:select:"))
    app.add_handler(CallbackQueryHandler(add_15_posts_callback, pattern="^posts:add_15$"))
    app.add_handler(CallbackQueryHandler(publish_one_callback, pattern="^posts:publish_one$"))
    app.add_handler(CallbackQueryHandler(my_posts_callback, pattern="^posts:my_posts$"))
    app.add_handler(CallbackQueryHandler(recycle_posts_callback, pattern="^posts:recycle$"))
    app.add_handler(CallbackQueryHandler(my_pending_stats_callback, pattern="^stats:pending$"))
    app.add_handler(CallbackQueryHandler(my_full_stats_callback, pattern="^stats:full$"))
    app.add_handler(CallbackQueryHandler(my_groups_callback, pattern="^groups:my_groups$"))
    app.add_handler(CallbackQueryHandler(group_settings_callback, pattern="^groups:settings:"))
    app.add_handler(CallbackQueryHandler(settings_menu_callback, pattern="^settings:menu$"))
    app.add_handler(CallbackQueryHandler(toggle_auto_publish_callback, pattern="^settings:toggle_auto_publish$"))
    app.add_handler(CallbackQueryHandler(settings_toggle_auto_recycle_callback, pattern="^settings:toggle_auto_recycle$"))
    
    # قائمة الأوامر
    commands = [
        BotCommand("start", "القائمة الرئيسية"),
        BotCommand("help", "المساعدة"),
        BotCommand("rules", "قوانين المجموعة"),
        BotCommand("set_rules", "تعيين قوانين (للمشرفين)"),
        BotCommand("reset_rules", "إعادة تعيين القوانين (للمشرفين)"),
        BotCommand("syncgroup", "تفعيل المجموعة"),
        BotCommand("security", "إعدادات الأمان"),
        BotCommand("trial", "تجربة مجانية"),
        BotCommand("subscribe", "الاشتراك"),
        BotCommand("developer", "المطور"),
        BotCommand("updates", "التحديثات"),
        BotCommand("language", "تغيير اللغة"),
        BotCommand("support", "الدعم"),
        BotCommand("panel", "لوحة التحكم"),
        BotCommand("schedule", "جدولة منشور"),
        BotCommand("lock", "قفل المجموعة"),
        BotCommand("unlock", "فتح المجموعة"),
        BotCommand("stats", "إحصائيات القناة"),
        BotCommand("contests", "المسابقات"),
        BotCommand("ban", "حظر مستخدم"),
        BotCommand("mute", "كتم مستخدم"),
        BotCommand("warn", "تحذير مستخدم"),
        BotCommand("kick", "طرد مستخدم"),
        BotCommand("rank", "رتبتك"),
        BotCommand("top", "أفضل 10"),
    ]
    await app.bot.set_my_commands(commands)
    
    print(f"🚀 تم تشغيل {BOT_NAME} (الإصدار 19.4.0)")
    print("✅ جميع التصحيحات والتحسينات تم تطبيقها")
    
    try:
        await app.run_polling(drop_pending_updates=True, poll_interval=POLL_INTERVAL)
    except KeyboardInterrupt:
        print("🛑 تم إيقاف البوت")
    finally:
        if db_pool:
            await db_pool.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 تم إيقاف البوت")
    except Exception as e:
        print(f"❌ خطأ فادح: {e}")
        traceback.print_exc()
        sys.exit(1)
