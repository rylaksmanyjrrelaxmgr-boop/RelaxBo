#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - بوت متكامل لإدارة القنوات والمجموعات
الإصدار: 19.3.1
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
try:
    from replies import ALL_REPLIES
    REPLIES_LOADED = True
    print("✅ تم تحميل الردود من replies.py")
except ImportError:
    REPLIES_LOADED = False
    ALL_REPLIES = {}
    print("⚠️ ملف replies.py غير موجود")

try:
    from web_server import start_web_server, WEB_SERVER_LOADED
    print("✅ تم تحميل web_server.py")
except ImportError:
    WEB_SERVER_LOADED = False
    print("⚠️ ملف web_server.py غير موجود")

try:
    from contests import *
    CONTESTS_LOADED = True
    print("✅ تم تحميل contests.py")
except ImportError:
    CONTESTS_LOADED = False
    print("⚠️ ملف contests.py غير موجود")

try:
    from bot_pay import *
    PAY_LOADED = True
    print("✅ تم تحميل bot_pay.py")
except ImportError:
    PAY_LOADED = False
    print("⚠️ ملف bot_pay.py غير موجود")

# ===== استيراد المفقودات =====
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
    raise ValueError("❌ BOT_TOKEN غير موجود في ملف .env")

PRIMARY_OWNER_ID = int(os.getenv("MAIN_ADMIN_ID", 0))
if PRIMARY_OWNER_ID == 0:
    raise ValueError("❌ MAIN_ADMIN_ID غير محدد")

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
ALL_REPLIES = {
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

async def safe_send(bot, chat_id, text, reply_markup=None):
    if not text:
        return
    try:
        return await bot.send_message(
            chat_id=chat_id,
            text=text[:4096],
            parse_mode='MarkdownV2',
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

async def safe_edit(query, text, reply_markup=None):
    if not query or not text:
        return
    try:
        return await query.edit_message_text(
            text[:4096],
            parse_mode='MarkdownV2',
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

# ===================== تعريفات الكولباك =====================
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
    
    # إدخال البيانات الافتراضية
    await db_pool.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (PRIMARY_OWNER_ID,))
    await db_pool.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(DEFAULT_PUBLISH_INTERVAL_SECONDS),))
    await db_pool.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_ticket_number', '0')")
    
    await db_pool.commit()
    print("✅ قاعدة البيانات جاهزة")

async def execute_db(func):
    return await func(db_pool)

# ====================================================================
# ===================== دوال قاعدة البيانات الأساسية =====================
# ====================================================================

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

async def db_get_auto_recycle(user_id: int) -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT auto_recycle FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_get)

async def db_set_auto_recycle(user_id: int, enabled: bool):
    async def _set(conn):
        await conn.execute("UPDATE users SET auto_recycle=? WHERE user_id=?", (1 if enabled else 0, user_id))
        await conn.commit()
    return await execute_db(_set)

# ====================================================================
# ===================== دوال قنوات المستخدمين =====================
# ====================================================================

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

async def db_get_user_channels_count(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM user_channels WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_get)

# ====================================================================
# ===================== دوال المنشورات =====================
# ====================================================================

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

async def db_increment_fail_count(post_id: int):
    async def _inc(conn):
        await conn.execute("UPDATE posts SET fail_count = fail_count + 1 WHERE id=?", (post_id,))
        await conn.commit()
    return await execute_db(_inc)

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

async def db_reset_all_posts_to_unpublished(channel_db_id: int) -> int:
    async def _reset(conn):
        await conn.execute("UPDATE posts SET published=0, fail_count=0 WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_reset)

async def db_reset_posts_to_unpublished(channel_db_id: int, user_id: int = None):
    async def _reset(conn):
        await conn.execute("UPDATE posts SET published=0, fail_count=0 WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
    return await execute_db(_reset)

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

async def db_unpublished_count(channel_db_id: int) -> int:
    async def _count(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_count)

# ====================================================================
# ===================== دوال المجموعات =====================
# ====================================================================

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

# ====================================================================
# ===================== دوال الأمان =====================
# ====================================================================

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

# ====================================================================
# ===================== دوال الردود =====================
# ====================================================================

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

async def db_get_reply(keyword):
    async def _get(conn):
        cur = await conn.execute("SELECT reply FROM group_replies WHERE keyword=?", (keyword.lower(),))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_get_all_replies():
    async def _get(conn):
        cur = await conn.execute("SELECT keyword, reply FROM group_replies ORDER BY keyword")
        return await cur.fetchall()
    return await execute_db(_get)

# ====================================================================
# ===================== دوال الردود المتقدمة =====================
# ====================================================================

async def db_get_auto_reply_settings(chat_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute("SELECT enabled, only_admins, ignore_bots FROM auto_reply_settings WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        if row:
            return {
                'enabled': row[0] == 1,
                'only_admins': row[1] == 1,
                'ignore_bots': row[2] == 1
            }
        return {'enabled': True, 'only_admins': False, 'ignore_bots': True}
    return await execute_db(_get)

async def db_set_auto_reply_enabled(chat_id: int, enabled: bool) -> None:
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO auto_reply_settings (chat_id, enabled) VALUES (?, ?)", (chat_id, 1 if enabled else 0))
        await conn.commit()
    return await execute_db(_set)

async def db_set_auto_reply_only_admins(chat_id: int, only_admins: bool) -> None:
    async def _set(conn):
        await conn.execute("UPDATE auto_reply_settings SET only_admins=? WHERE chat_id=?", (1 if only_admins else 0, chat_id))
        await conn.commit()
    return await execute_db(_set)

async def db_toggle_auto_reply(chat_id: int) -> bool:
    settings = await db_get_auto_reply_settings(chat_id)
    new_status = not settings['enabled']
    await db_set_auto_reply_enabled(chat_id, new_status)
    return new_status

# ====================================================================
# ===================== دوال التذاكر =====================
# ====================================================================

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

async def db_delete_all_tickets() -> int:
    async def _delete(conn):
        cur = await conn.execute("DELETE FROM support_tickets")
        count = cur.rowcount
        await conn.execute("UPDATE settings SET value='0' WHERE key='last_ticket_number'")
        await conn.commit()
        return count
    return await execute_db(_delete)

# ====================================================================
# ===================== دوال الجدولة =====================
# ====================================================================

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
        publish_time_str = schedule.get('publish_time', '00:00')
        if ':' not in publish_time_str:
            publish_time_str = '00:00'
        try:
            hour, minute = map(int, publish_time_str.split(':'))
        except:
            hour, minute = 0, 0
        next_date = None
        if schedule_type == 'interval_minutes':
            minutes = schedule.get('interval_minutes', 12)
            next_date = last_time + timedelta(minutes=minutes)
        elif schedule_type == 'interval_hours':
            hours = schedule.get('interval_hours', 1)
            next_date = last_time + timedelta(hours=hours)
        elif schedule_type == 'interval_days':
            days = schedule.get('interval_days', 1)
            next_date = last_time + timedelta(days=days)
        elif schedule_type == 'days':
            days_of_week = json.loads(schedule.get('days_of_week', '[]'))
            if days_of_week:
                target_date = last_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                for i in range(1, 8):
                    check_date = target_date + timedelta(days=i)
                    if check_date.weekday() in days_of_week:
                        next_date = check_date
                        break
                if not next_date:
                    next_date = target_date + timedelta(days=7)
                    while next_date.weekday() not in days_of_week:
                        next_date += timedelta(days=1)
            else:
                next_date = last_time + timedelta(days=1)
        elif schedule_type == 'dates':
            specific_dates = json.loads(schedule.get('specific_dates', '[]'))
            if specific_dates:
                target_date = last_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                for date_str in sorted(specific_dates):
                    try:
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d').replace(
                            hour=hour, minute=minute, second=0, microsecond=0
                        )
                        if date_obj > last_time:
                            next_date = date_obj
                            break
                    except:
                        continue
                if not next_date:
                    try:
                        next_date = datetime.strptime(specific_dates[0], '%Y-%m-%d').replace(
                            hour=hour, minute=minute, second=0, microsecond=0
                        ) + timedelta(days=365)
                    except:
                        next_date = utc_now() + timedelta(days=1)
            else:
                next_date = utc_now() + timedelta(days=1)
        else:
            next_date = utc_now() + timedelta(minutes=schedule.get('interval_minutes', 12))
        if next_date:
            await conn.execute("UPDATE schedule SET next_publish_date=? WHERE channel_db_id=?", (next_date.isoformat(), channel_db_id))
            await conn.commit()
    return await execute_db(_update)

async def db_set_publish_time(channel_db_id: int, time_str: str):
    async def _set(conn):
        await conn.execute("UPDATE schedule SET publish_time=? WHERE channel_db_id=?", (time_str, channel_db_id))
        await conn.commit()
    return await execute_db(_set)

# ====================================================================
# ===================== دوال الإحالات =====================
# ====================================================================

async def db_get_referral_settings() -> dict:
    async def _get(conn):
        settings = {}
        cur = await conn.execute("SELECT key, value FROM referral_settings")
        rows = await cur.fetchall()
        for key, value in rows:
            settings[key] = value
        return settings
    return await execute_db(_get)

async def db_get_referral_code(user_id: int) -> str:
    async def _get(conn):
        cur = await conn.execute("SELECT referral_code FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row and row[0] else None
    return await execute_db(_get)

async def db_generate_referral_code(user_id: int) -> str:
    async def _generate(conn):
        code_hash = hashlib.md5(f"{user_id}{time_module.time()}".encode()).hexdigest()[:8]
        referral_code = f"REF{code_hash.upper()}"
        await conn.execute("UPDATE users SET referral_code=? WHERE user_id=?", (referral_code, user_id))
        await conn.commit()
        return referral_code
    return await execute_db(_generate)

async def db_add_referral(referrer_id: int, referred_id: int) -> bool:
    async def _add(conn):
        if referrer_id == referred_id:
            return False
        cur = await conn.execute("SELECT 1 FROM referrals WHERE referred_id=?", (referred_id,))
        if await cur.fetchone():
            return False
        await conn.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, referred_id))
        await conn.commit()
        return True
    return await execute_db(_add)

async def db_get_referral_stats(user_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
        total_referrals = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT referral_count, total_reward_days, claimed_reward_days FROM referral_rewards WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return {
            'total_referrals': total_referrals,
            'referral_count': row[0] if row else 0,
            'total_reward_days': row[1] if row else 0,
            'claimed_reward_days': row[2] if row else 0,
            'available_days': (row[1] if row else 0) - (row[2] if row else 0)
        }
    return await execute_db(_get)

async def db_claim_referral_reward(user_id: int) -> int:
    async def _claim(conn):
        cur = await conn.execute("SELECT total_reward_days, claimed_reward_days FROM referral_rewards WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if not row:
            return 0
        total = row[0]
        claimed = row[1]
        available = total - claimed
        if available <= 0:
            return 0
        current_sub = await db_get_subscription_days_left(user_id)
        new_sub_days = current_sub + available
        end_date = (utc_now() + timedelta(days=new_sub_days)).isoformat()
        await conn.execute("UPDATE users SET subscription_end=? WHERE user_id=?", (end_date, user_id))
        await conn.execute("UPDATE referral_rewards SET claimed_reward_days = claimed_reward_days + ? WHERE user_id=?", (available, user_id))
        await conn.commit()
        return available
    return await execute_db(_claim)

# ====================================================================
# ===================== دوال التذكيرات =====================
# ====================================================================

async def db_get_user_reminder_settings(user_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute("""
            SELECT subscription_reminder, daily_stats_reminder, weekly_report,
                   reminder_days_before, last_reminder_sent, notification_lang
            FROM user_reminder_settings WHERE user_id=?
        """, (user_id,))
        row = await cur.fetchone()
        if row:
            return {
                'subscription_reminder': row[0] == 1,
                'daily_stats_reminder': row[1] == 1,
                'weekly_report': row[2] == 1,
                'reminder_days_before': row[3] if row[3] is not None else 3,
                'last_reminder_sent': row[4] if row[4] else 0,
                'notification_lang': row[5] if row[5] else 'ar'
            }
        else:
            await conn.execute("""
                INSERT INTO user_reminder_settings (
                    user_id, subscription_reminder, daily_stats_reminder,
                    weekly_report, reminder_days_before, last_reminder_sent,
                    notification_lang
                ) VALUES (?, 1, 0, 1, 3, 0, 'ar')
            """, (user_id,))
            await conn.commit()
            return {
                'subscription_reminder': True,
                'daily_stats_reminder': False,
                'weekly_report': True,
                'reminder_days_before': 3,
                'last_reminder_sent': 0,
                'notification_lang': 'ar'
            }
    return await execute_db(_get)

async def db_update_reminder_settings(user_id: int, **kwargs):
    async def _update(conn):
        fields, values = [], []
        for key, value in kwargs.items():
            if key == 'subscription_reminder':
                fields.append("subscription_reminder=?")
                values.append(1 if value else 0)
            elif key == 'daily_stats_reminder':
                fields.append("daily_stats_reminder=?")
                values.append(1 if value else 0)
            elif key == 'weekly_report':
                fields.append("weekly_report=?")
                values.append(1 if value else 0)
            elif key == 'reminder_days_before':
                fields.append("reminder_days_before=?")
                values.append(value)
            elif key == 'notification_lang':
                fields.append("notification_lang=?")
                values.append(value)
        if fields:
            query = f"UPDATE user_reminder_settings SET {', '.join(fields)} WHERE user_id=?"
            values.append(user_id)
            await conn.execute(query, values)
            await conn.commit()
    return await execute_db(_update)

# ====================================================================
# ===================== دوال الإحصائيات =====================
# ====================================================================

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
        for row in rows:
            dates.append(row[0])
            counts.append(row[1] or 0)
            views.append(row[2] or 0)
        return {'dates': dates, 'counts': counts, 'views': views}
    return await execute_db(_get_growth)

# ====================================================================
# ===================== دوال الإعدادات العامة =====================
# ====================================================================

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

async def db_get_auto_backup() -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='auto_backup'")
        row = await cur.fetchone()
        return row and row[0] == '1'
    return await execute_db(_get)

async def db_set_auto_backup(enabled: bool):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('auto_backup', ?)", ('1' if enabled else '0',))
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

# ====================================================================
# ===================== دوال المستويات =====================
# ====================================================================

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

# ====================================================================
# ===================== دوال المسابقات =====================
# ====================================================================

async def db_get_active_contests(limit: int = 10) -> list:
    async def _get(conn):
        now = utc_now().isoformat()
        cur = await conn.execute("""
            SELECT id, title, description, prize, end_date, contest_type
            FROM contests
            WHERE status = 'active' AND end_date > ?
            ORDER BY end_date ASC LIMIT ?
        """, (now, limit))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_create_contest(creator_id: int, title: str, description: str, prize: str, end_date: datetime, contest_type: str = 'raffle') -> int:
    async def _create(conn):
        end_date_str = end_date.isoformat()
        cur = await conn.execute("""
            INSERT INTO contests (
                creator_id, title, description, prize, end_date,
                status, created_at, contest_type
            ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?) RETURNING id
        """, (creator_id, title, description, prize, end_date_str, utc_now_iso(), contest_type))
        row = await cur.fetchone()
        await conn.commit()
        return row[0] if row else None
    return await execute_db(_create)

async def db_get_contest(contest_id: int) -> dict | None:
    async def _get(conn):
        cur = await conn.execute("""
            SELECT id, title, description, prize, end_date, status,
                   winner_id, creator_id, contest_type
            FROM contests WHERE id = ?
        """, (contest_id,))
        row = await cur.fetchone()
        if row:
            return {
                'id': row[0], 'title': row[1], 'description': row[2],
                'prize': row[3], 'end_date': row[4], 'status': row[5],
                'winner_id': row[6], 'creator_id': row[7],
                'contest_type': row[8] if len(row) > 8 else 'raffle'
            }
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

async def db_get_contest_winners(limit: int = 10) -> list:
    async def _get(conn):
        cur = await conn.execute("""
            SELECT c.id, c.title, c.prize, cw.winner_id, cw.announced_at
            FROM contest_winners cw
            JOIN contests c ON cw.contest_id = c.id
            ORDER BY cw.announced_at DESC LIMIT ?
        """, (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

# ====================================================================
# ===================== دوال الصلاحيات =====================
# ====================================================================

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

async def is_authorized_in_group(bot, chat_id: int, user_id: int) -> bool:
    if user_id == PRIMARY_OWNER_ID:
        return True
    if await db_is_hidden_owner(chat_id, user_id):
        return True
    if await db_is_hidden_admin(chat_id, user_id):
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ['administrator', 'creator']
    except:
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

async def get_all_bot_admins():
    async def _get(conn):
        cur = await conn.execute("SELECT user_id FROM bot_admins")
        rows = await cur.fetchall()
        return [row[0] for row in rows]
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

# ====================================================================
# ===================== دوال الإجراءات المتقدمة =====================
# ====================================================================

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

# ====================================================================
# ===================== دوال الترجمة =====================
# ====================================================================

async def get_user_translation_language(user_id: int) -> str:
    async def _get(conn):
        cur = await conn.execute("SELECT lang FROM user_translation WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 'off'
    return await execute_db(_get)

async def set_user_translation_language(user_id: int, lang: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO user_translation (user_id, lang) VALUES (?, ?)", (user_id, lang))
        await conn.commit()
    return await execute_db(_set)

async def translate_text(text: str, target_lang: str) -> str:
    if target_lang == 'off' or not text:
        return text
    try:
        translator = GoogleTranslator(target=target_lang)
        return translator.translate(text)
    except:
        return text

# ====================================================================
# ===================== دوال النسخ الاحتياطي =====================
# ====================================================================

async def create_backup():
    try:
        backup_file = BACKUP_DIR / f"backup_{mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(DB_PATH, backup_file)
        backups = sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old_backup in backups[MAX_BACKUPS:]:
            old_backup.unlink()
        return backup_file
    except Exception as e:
        print(f"❌ فشل إنشاء النسخة الاحتياطية: {e}")
        return None

async def list_backups():
    return sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)

async def restore_backup(backup_path: Path):
    try:
        current_backup = BACKUP_DIR / f"pre_restore_{mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(DB_PATH, current_backup)
        shutil.copy2(backup_path, DB_PATH)
        return True
    except Exception as e:
        print(f"❌ فشل استعادة النسخة: {e}")
        return False

# ====================================================================
# ===================== دوال الصحة والنظام =====================
# ====================================================================

async def check_database_health() -> bool:
    try:
        async def _check(conn):
            cur = await conn.execute("SELECT 1")
            row = await cur.fetchone()
            return row is not None
        return await execute_db(_check)
    except:
        return False

async def check_telegram_health() -> bool:
    try:
        from telegram.ext import Application
        app = Application.builder().token(TOKEN).build()
        me = await app.bot.get_me()
        return me is not None
    except:
        return False

def get_ram_usage():
    try:
        if PSUTIL_AVAILABLE:
            mem = psutil.virtual_memory()
            return {
                'total': round(mem.total / (1024**3), 1),
                'used': round(mem.used / (1024**3), 1),
                'percent': mem.percent
            }
    except:
        pass
    return {'total': 0, 'used': 0, 'percent': 0}

# ====================================================================
# ===================== دوال الكيبورد =====================
# ====================================================================

def get_admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
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
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])

def get_auto_reply_keyboard(chat_id: int, settings: dict) -> InlineKeyboardMarkup:
    status_text = "🟢 مفعل" if settings['enabled'] else "🔴 معطل"
    admin_text = "👑 مشرفين فقط" if settings['only_admins'] else "👥 الجميع"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 الردود التلقائية: {status_text}", callback_data=f"{CallbackData.AUTO_REPLY_TOGGLE_PREFIX}{chat_id}")],
        [InlineKeyboardButton(f"👥 المستخدمون: {admin_text}", callback_data=f"{CallbackData.AUTO_REPLY_ADMINS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

def get_group_banned_words_keyboard(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"{CallbackData.BANNED_WORDS_ADD_PREFIX}{chat_id}"),
         InlineKeyboardButton("📋 عرض الكلمات", callback_data=f"{CallbackData.BANNED_WORDS_LIST_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=f"{CallbackData.BANNED_WORDS_REMOVE_PREFIX}{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

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

def security_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 حذف الروابط", callback_data=f"{CallbackData.SECURITY_LINKS_PREFIX}{chat_id}"),
         InlineKeyboardButton("@ حذف المعرفات", callback_data=f"{CallbackData.SECURITY_MENTIONS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🚫 كلمات محظورة", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}"),
         InlineKeyboardButton("⏱️ الوضع البطيء", callback_data=f"{CallbackData.SECURITY_SLOWMODE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🎯 الترحيب", callback_data=f"{CallbackData.SECURITY_WELCOME_PREFIX}{chat_id}"),
         InlineKeyboardButton("👋 الوداع", callback_data=f"{CallbackData.SECURITY_GOODBYE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("⚖️ تحديد العقوبة", callback_data=f"{CallbackData.PENALTY_MENU}:{chat_id}"),
         InlineKeyboardButton("🔙 إغلاق", callback_data=CallbackData.SECURITY_CLOSE)]
    ])

def penalty_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 طرد", callback_data=f"{CallbackData.PENALTY_KICK}:{chat_id}"),
         InlineKeyboardButton("🛑 حظر", callback_data=f"{CallbackData.PENALTY_BAN}:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم", callback_data=f"{CallbackData.PENALTY_MUTE}:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

def mute_duration_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ 5 دقائق", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_5}:{chat_id}"),
         InlineKeyboardButton("⏱️ 30 دقيقة", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_30}:{chat_id}")],
        [InlineKeyboardButton("⏱️ 1 ساعة", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_60}:{chat_id}"),
         InlineKeyboardButton("⏱️ 12 ساعة", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_720}:{chat_id}")],
        [InlineKeyboardButton("📆 يوم", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_1440}:{chat_id}"),
         InlineKeyboardButton("📆 أسبوع", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_10080}:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم دائم", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_PERMANENT}:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.PENALTY_MENU}:{chat_id}")]
    ])

# ====================================================================
# ===================== دوال الكيبورد الرئيسية =====================
# ====================================================================

async def get_main_keyboard(user_id: int):
    channels = await db_get_channels(user_id)
    active = None
    if channels:
        active = await db_get_active_channel(user_id)
        if active is None:
            active = channels[0][0]
            await db_set_active_channel(user_id, active)
    
    cnt = 0
    ch_display = get_text(user_id, 'no_channels')
    if active is not None:
        cnt = await db_unpublished_count(active)
        ch_info = await db_get_channel_info(active)
        if ch_info:
            ch_name = ch_info[1] if ch_info[1] else ch_info[0]
            ch_display = f"{ch_name} ({ch_info[0]})"
    
    my_groups = await db_get_user_groups_count(user_id)
    has_sub = await db_has_active_subscription(user_id)
    sub_text = get_text(user_id, 'subscribed') if has_sub else get_text(user_id, 'not_subscribed')
    auto_status = await db_auto_status(user_id)
    auto_text = get_text(user_id, 'auto_on') if auto_status else get_text(user_id, 'auto_off')
    
    title = get_text(user_id, 'main_title').format(
        BOT_NAME, user_id, my_groups, sub_text,
        ch_display, cnt, auto_status
    )
    
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
        InlineKeyboardButton(get_text(user_id, 'language_btn'), callback_data=CallbackData.LANGUAGE),
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
    is_admin = (user_id == PRIMARY_OWNER_ID) or (await is_bot_admin(user_id))
    if is_admin:
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'admin_panel'), callback_data=CallbackData.ADMIN_PANEL)
        ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'add_to_group'), url=f"https://t.me/{BOT_USERNAME}?startgroup")
    ])
    return InlineKeyboardMarkup(keyboard), title, active

# ====================================================================
# ===================== دوال معالجة المسابقات =====================
# ====================================================================

async def handle_contest_creation_states(update: Update, context: ContextTypes.DEFAULT_TYPE, state) -> bool:
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""
    
    if state == UserState.WAITING_CONTEST_TITLE:
        if not text:
            await update.message.reply_text("❌ الرجاء إدخال عنوان صحيح.")
            return True
        context.user_data['contest_title'] = text
        context.user_data['state'] = UserState.WAITING_CONTEST_DESCRIPTION
        await update.message.reply_text(get_text(user_id, 'create_contest_description'))
        return True
    
    elif state == UserState.WAITING_CONTEST_DESCRIPTION:
        if not text:
            await update.message.reply_text("❌ الرجاء إدخال وصف صحيح.")
            return True
        context.user_data['contest_description'] = text
        context.user_data['state'] = UserState.WAITING_CONTEST_PRIZE
        await update.message.reply_text(get_text(user_id, 'create_contest_prize'))
        return True
    
    elif state == UserState.WAITING_CONTEST_PRIZE:
        if not text:
            await update.message.reply_text("❌ الرجاء إدخال جائزة صحيحة.")
            return True
        context.user_data['contest_prize'] = text
        context.user_data['state'] = UserState.WAITING_CONTEST_END_DATE
        await update.message.reply_text(get_text(user_id, 'create_contest_end_date'))
        return True
    
    elif state == UserState.WAITING_CONTEST_END_DATE:
        try:
            end_date = datetime.strptime(text, "%Y-%m-%d %H:%M")
            if end_date <= mecca_now():
                await update.message.reply_text(get_text(user_id, 'contest_date_future'))
                return True
            title = context.user_data.pop('contest_title', 'بدون عنوان')
            description = context.user_data.pop('contest_description', '')
            prize = context.user_data.pop('contest_prize', '')
            contest_id = await db_create_contest(user_id, title, description, prize, end_date)
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
    
    return False

# ====================================================================
# ===================== معالجات الأوامر =====================
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
    await safe_send(context.bot, user_id, get_text(user_id, 'help'))

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
        keyboard.append([InlineKeyboardButton(f"📌 {gname[:30]}", callback_data=f"{CallbackData.SECURITY_SELECT_GROUP}{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await safe_send(context.bot, user_id, "🔐 **اختر مجموعة:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def trial_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await trial_callback(update, context)

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscribe_menu_callback(update, context)

async def developer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await developer_callback(update, context)

async def updates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await updates_callback(update, context)

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
         InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_send(context.bot, user_id, get_text(user_id, 'welcome'), reply_markup=keyboard)

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 كتابة تذكرة", callback_data=CallbackData.SUPPORT_TICKET)],
        [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_send(context.bot, user_id, get_text(user_id, 'support_welcome'), reply_markup=keyboard)

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
            [InlineKeyboardButton("🔒 قفل المجموعة", callback_data=f"{CallbackData.PANEL_LOCK_PREFIX}{chat_id}"),
             InlineKeyboardButton("🔓 فتح المجموعة", callback_data=f"{CallbackData.PANEL_UNLOCK_PREFIX}{chat_id}")],
            [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}"),
             InlineKeyboardButton("🔙 إغلاق اللوحة", callback_data=CallbackData.PANEL_CLOSE)]
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
        keyboard.append([InlineKeyboardButton(f"📌 {gname[:30]}", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
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
        await update.message.reply_text(get_text(user_id, 'locked'))
        return
    args = context.args or []
    if args and args[0].lstrip('-').isdigit():
        chat_id = int(args[0])
        if await is_authorized_in_group(context.bot, chat_id, user_id):
            await db_set_chat_lock(chat_id, True, user_id)
            await update.message.reply_text(get_text(user_id, 'locked'))
            return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        keyboard.append([InlineKeyboardButton(f"🔒 {gname[:30]}", callback_data=f"{CallbackData.PANEL_LOCK_PREFIX}{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
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
        await update.message.reply_text(get_text(user_id, 'unlocked'))
        return
    args = context.args or []
    if args and args[0].lstrip('-').isdigit():
        chat_id = int(args[0])
        if await is_authorized_in_group(context.bot, chat_id, user_id):
            await db_set_chat_lock(chat_id, False)
            await update.message.reply_text(get_text(user_id, 'unlocked'))
            return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        keyboard.append([InlineKeyboardButton(f"🔓 {gname[:30]}", callback_data=f"{CallbackData.PANEL_UNLOCK_PREFIX}{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
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
    await contests_menu_callback(update, context)

async def create_contest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_CONTEST_TITLE
    await update.message.reply_text(get_text(user_id, 'create_contest_title'))

async def declare_winner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(get_text(user_id, 'declare_winner_usage'))
        return
    try:
        contest_id = int(args[0])
        winner_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ معرف غير صالح.")
        return
    contest = await db_get_contest(contest_id)
    if not contest:
        await update.message.reply_text(get_text(user_id, 'contest_not_found'))
        return
    if contest['status'] != 'active':
        await update.message.reply_text(get_text(user_id, 'contest_expired'))
        return
    if not await db_get_user_participation(winner_id, contest_id):
        await update.message.reply_text(get_text(user_id, 'contest_not_participant'))
        return
    if await db_set_contest_winner(contest_id, winner_id):
        await update.message.reply_text(
            get_text(user_id, 'contest_declared').format(contest['title'], winner_id, contest['prize'])
        )
    else:
        await update.message.reply_text(get_text(user_id, 'contest_declared_error'))

async def update_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
# ===================== معالجات الكولباك =====================
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
            InlineKeyboardButton(f"📢 {ch_name}", callback_data=f"{CallbackData.CHANNELS_SELECT_PREFIX}{ch_db_id}"),
            InlineKeyboardButton("🗑️ حذف", callback_data=f"{CallbackData.CHANNELS_DELETE_PREFIX}{ch_db_id}")
        ])
    keyboard.append([InlineKeyboardButton("➕ إضافة قناة", callback_data=CallbackData.CHANNELS_ADD)])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
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
        await safe_edit(query, get_text(user_id, 'recycled'))
    else:
        await safe_edit(query, "⚠️ اختر قناة أولاً")

async def my_pending_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    unpublished = await db_get_user_unpublished_posts(user_id)
    total = await db_get_user_total_posts(user_id)
    text = get_text(user_id, 'pending_stats').format(unpublished, total)
    await safe_edit(query, text)

async def my_full_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    channels = await db_get_user_channels_count(user_id)
    total = await db_get_user_total_posts(user_id)
    unpublished = await db_get_user_unpublished_posts(user_id)
    groups = await db_get_user_groups_count(user_id)
    auto = get_text(user_id, 'auto_on') if await db_auto_status(user_id) else get_text(user_id, 'auto_off')
    text = get_text(user_id, 'stats').format(channels, total, unpublished, groups, auto)
    await safe_edit(query, text)

async def my_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    groups = await db_get_user_groups(user_id)
    if not groups:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        await safe_edit(query, "📭 لا توجد مجموعات مسجلة", reply_markup=keyboard)
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        keyboard.append([
            InlineKeyboardButton(f"📌 {gname[:30]}", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{gid}")
        ])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
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
    await safe_edit(query, text)

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    auto = await db_auto_status(user_id)
    auto_btn = get_text(user_id, 'disabled') if auto else get_text(user_id, 'enabled')
    recycle = await db_get_auto_recycle(user_id)
    recycle_btn = get_text(user_id, 'enabled') if recycle else get_text(user_id, 'disabled')
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{auto_btn} النشر التلقائي", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH)],
        [InlineKeyboardButton(f"♻️ إعادة التدوير: {recycle_btn}", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_RECYCLE)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, get_text(user_id, 'settings'), reply_markup=keyboard)

async def toggle_auto_publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    cur = await db_auto_status(user_id)
    await db_set_auto(user_id, not cur)
    status = get_text(user_id, 'enabled') if not cur else get_text(user_id, 'disabled')
    await safe_edit(query, get_text(user_id, 'auto_toggled').format(status))
    await main_menu_callback(update, context)

async def toggle_auto_recycle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    cur = await db_get_auto_recycle(user_id)
    new_status = not cur
    await db_set_auto_recycle(user_id, new_status)
    status = get_text(user_id, 'enabled') if new_status else get_text(user_id, 'disabled')
    await safe_edit(query, f"✅ تم تغيير إعادة التدوير التلقائي إلى: {status}")

async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    await safe_edit(query, get_text(user_id, 'help'))

async def trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if await db_has_used_trial(user_id):
        await safe_edit(query, get_text(user_id, 'trial_used'))
        return
    if await db_has_active_subscription(user_id):
        await safe_edit(query, get_text(user_id, 'already_subscribed'))
        return
    await db_activate_trial(user_id)
    await safe_edit(query, get_text(user_id, 'trial'))
    await main_menu_callback(update, context)

async def subscribe_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if await db_has_active_subscription(user_id):
        days = await db_get_subscription_days_left(user_id)
        await safe_edit(query, f"✅ اشتراكك مفعل، متبقي {days} يوم")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_1),
         InlineKeyboardButton("⭐ 2 يوم - 9 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_2)],
        [InlineKeyboardButton("⭐ شهر (30 يوم) - 50 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_30),
         InlineKeyboardButton("⭐ 3 أشهر (90 يوم) - 120 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_90)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, get_text(user_id, 'subscribe'), reply_markup=keyboard)

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
        await safe_edit(query, f"❌ خطأ: {str(e)[:100]}")

async def buy_subscription_1_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_subscription_callback(update, context, 1, 5, "اشتراك 1 يوم")

async def buy_subscription_2_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_subscription_callback(update, context, 2, 9, "اشتراك 2 يوم")

async def buy_subscription_30_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_subscription_callback(update, context, 30, 50, "اشتراك شهر")

async def buy_subscription_90_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_subscription_callback(update, context, 90, 120, "اشتراك 3 أشهر")

async def developer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    text = f"👨‍💻 **المطور**\n@RelaxMgr\n🤖 {BOT_NAME}"
    await safe_edit(query, text)

async def updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    updates_channel = await db_get_updates_channel()
    if updates_channel:
        text = f"📢 **قناة التحديثات**\n@ {updates_channel}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 افتح القناة", url=f"https://t.me/{updates_channel}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
    else:
        text = "📢 **لم يتم تعيين قناة التحديثات بعد**"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👑 لوحة الأدمن", callback_data=CallbackData.ADMIN_PANEL)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
    await safe_edit(query, text, reply_markup=keyboard)

async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
         InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, get_text(user_id, 'welcome'), reply_markup=keyboard)

async def lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = query.data.split("_")[1]
    user_language[user_id] = lang
    await main_menu_callback(update, context)

async def support_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 كتابة تذكرة", callback_data=CallbackData.SUPPORT_TICKET)],
        [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, get_text(user_id, 'support_welcome'), reply_markup=keyboard)

async def support_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.SUPPORT_MENU)]])
    await safe_edit(query, get_text(user_id, 'support_help'), reply_markup=keyboard)

async def support_ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data=CallbackData.SUPPORT_MENU)]])
    await safe_edit(query, "📝 **اكتب رسالتك** (سيتم إرسالها كتذكرة دعم)")

async def support_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await support_menu_callback(update, context)

async def referral_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    referral_code = await db_get_referral_code(user_id)
    if not referral_code:
        referral_code = await db_generate_referral_code(user_id)
    stats = await db_get_referral_stats(user_id)
    settings = await db_get_referral_settings()
    reward_days = int(settings.get('reward_days_per_referral', '3'))
    welcome_points = int(settings.get('welcome_bonus_points', '10'))
    text = get_text(user_id, 'referral_title').format(
        referral_code, BOT_USERNAME, referral_code,
        stats['total_referrals'], stats['available_days'],
        reward_days, welcome_points
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'copy_link'), callback_data=f"{CallbackData.REFERRAL_COPY_LINK_PREFIX}{referral_code}"),
         InlineKeyboardButton(get_text(user_id, 'claim_reward'), callback_data=CallbackData.REFERRAL_CLAIM_REWARD)],
        [InlineKeyboardButton(get_text(user_id, 'referral_list'), callback_data=CallbackData.REFERRAL_LIST),
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def referral_copy_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    referral_code = query.data.split(":")[-1]
    text = f"🔗 **رابط الإحالة الخاص بك:**\n`https://t.me/{BOT_USERNAME}?start=ref_{referral_code}`"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REFERRAL_MENU)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def referral_claim_reward_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    stats = await db_get_referral_stats(user_id)
    if stats['available_days'] <= 0:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REFERRAL_MENU)]])
        await safe_edit(query, get_text(user_id, 'no_reward_available'), reply_markup=keyboard)
        return
    claimed = await db_claim_referral_reward(user_id)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REFERRAL_MENU)]])
    await safe_edit(query, get_text(user_id, 'reward_claimed').format(claimed), reply_markup=keyboard)

async def referral_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    async def _get_referrals(conn):
        cur = await conn.execute("""
            SELECT r.referred_id, r.referred_at, r.is_rewarded,
                   u.first_name, u.username
            FROM referrals r
            LEFT JOIN users_cache u ON r.referred_id = u.user_id
            WHERE r.referrer_id = ?
            ORDER BY r.referred_at DESC LIMIT 20
        """, (user_id,))
        return await cur.fetchall()
    referrals = await execute_db(_get_referrals)
    if not referrals:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REFERRAL_MENU)]])
        await safe_edit(query, get_text(user_id, 'no_referrals'), reply_markup=keyboard)
        return
    text = f"📊 **{get_text(user_id, 'referral_list')}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for referred_id, referred_at, is_rewarded, first_name, username in referrals:
        try:
            dt = datetime.fromisoformat(referred_at)
            dt_mecca = utc_to_mecca(dt)
            date_str = dt_mecca.strftime("%Y-%m-%d")
        except:
            date_str = referred_at[:10] if referred_at else "?"
        status = "✅" if is_rewarded else "⏳"
        name = first_name or username or str(referred_id)
        text += f"{status} {name} - {date_str}\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'claim_reward'), callback_data=CallbackData.REFERRAL_CLAIM_REWARD)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REFERRAL_MENU)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def reminder_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    settings = await db_get_user_reminder_settings(user_id)
    status_sub = "🟢 مفعل" if settings['subscription_reminder'] else "🔴 معطل"
    status_daily = "🟢 مفعل" if settings['daily_stats_reminder'] else "🔴 معطل"
    status_weekly = "🟢 مفعل" if settings['weekly_report'] else "🔴 معطل"
    text = get_text(user_id, 'reminder_title').format(status_sub, status_daily, status_weekly, settings['reminder_days_before'])
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'reminder_sub'), callback_data=CallbackData.REMINDER_TOGGLE_SUB),
         InlineKeyboardButton(get_text(user_id, 'reminder_daily'), callback_data=CallbackData.REMINDER_TOGGLE_DAILY)],
        [InlineKeyboardButton(get_text(user_id, 'reminder_weekly'), callback_data=CallbackData.REMINDER_TOGGLE_WEEKLY),
         InlineKeyboardButton(get_text(user_id, 'reminder_days_btn'), callback_data=CallbackData.REMINDER_SET_DAYS)],
        [InlineKeyboardButton(get_text(user_id, 'reminder_lang_btn'), callback_data=CallbackData.REMINDER_SET_LANG),
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def reminder_toggle_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    settings = await db_get_user_reminder_settings(user_id)
    await db_update_reminder_settings(user_id, subscription_reminder=not settings['subscription_reminder'])
    await reminder_menu_callback(update, context)

async def reminder_toggle_daily_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    settings = await db_get_user_reminder_settings(user_id)
    await db_update_reminder_settings(user_id, daily_stats_reminder=not settings['daily_stats_reminder'])
    await reminder_menu_callback(update, context)

async def reminder_toggle_weekly_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    settings = await db_get_user_reminder_settings(user_id)
    await db_update_reminder_settings(user_id, weekly_report=not settings['weekly_report'])
    await reminder_menu_callback(update, context)

async def reminder_set_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_REMINDER_DAYS
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REMINDER_MENU)]])
    await safe_edit(query, "⏰ **عدد أيام التذكير**\nأرسل عدد الأيام (1-10):", reply_markup=keyboard)

async def reminder_set_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("العربية 🇸🇦", callback_data=f"{CallbackData.REMINDER_LANG_PREFIX}ar"),
         InlineKeyboardButton("English 🇬🇧", callback_data=f"{CallbackData.REMINDER_LANG_PREFIX}en")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.REMINDER_MENU)]
    ])
    await safe_edit(query, "🌐 **اختر لغة الإشعارات:**", reply_markup=keyboard)

async def reminder_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = query.data.split(":")[-1]
    await db_update_reminder_settings(user_id, notification_lang=lang)
    await reminder_menu_callback(update, context)

async def translation_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    current_lang = await get_user_translation_language(user_id)
    if current_lang == 'off':
        status_text = get_text(user_id, 'translation_status_off')
    else:
        status_text = get_text(user_id, 'translation_status_on').format(current_lang)
    text = f"🌐 **{get_text(user_id, 'translation_settings')}**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 **الحالة:** {status_text}\n{get_text(user_id, 'translation_how_it_works')}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'translation_off'), callback_data=CallbackData.TRANSLATION_OFF)],
        [InlineKeyboardButton("🇸🇦 العربية", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ar"),
         InlineKeyboardButton("🇬🇧 English", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}en")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def translation_off_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    await set_user_translation_language(user_id, 'off')
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    await safe_edit(query, get_text(user_id, 'translation_disabled'), reply_markup=keyboard)

async def translation_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = query.data.split(":")[-1]
    await set_user_translation_language(user_id, lang)
    lang_names = {
        'ar': 'العربية', 'en': 'English', 'fr': 'Français', 'tr': 'Türkçe',
        'zh': '中文', 'ru': 'Русский', 'de': 'Deutsch', 'es': 'Español',
        'it': 'Italiano', 'pt': 'Português', 'ja': '日本語', 'ko': '한국어'
    }
    lang_name = lang_names.get(lang, lang)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    await safe_edit(query, get_text(user_id, 'translation_enabled').format(lang_name), reply_markup=keyboard)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    await safe_edit(query, get_text(user_id, 'admin_panel'), reply_markup=get_admin_keyboard(user_id))

async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    users = await db_get_all_users()
    if not users:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا يوجد مستخدمون مسجلون.", reply_markup=keyboard)
        return
    text = "👥 **قائمة المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for uid, banned in users[:50]:
        status = "🚫 محظور" if banned else "✅ نشط"
        text += f"• `{uid}` - {status}\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_banned_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    users = await db_get_all_users()
    banned_users = [u for u in users if u[1] == 1]
    if not banned_users:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا يوجد مستخدمون محظورون.", reply_markup=keyboard)
        return
    text = "🚫 **المستخدمون المحظورون**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for uid, _ in banned_users[:50]:
        text += f"• `{uid}`\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_USERS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_unban_all_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    async def _unban_all(conn):
        await conn.execute("UPDATE users SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_all)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, "✅ تم إلغاء حظر جميع المستخدمين.", reply_markup=keyboard)

async def admin_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    channels = await db_all_users_channels(limit=500)
    if not channels:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا توجد قنوات مسجلة.", reply_markup=keyboard)
        return
    text = "📡 **قنوات المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for idx, (uid, ch_id, ch_tele, ch_name, banned) in enumerate(channels[:100], 1):
        status = "⛔ محظورة" if banned else "✅ نشطة"
        text += f"{idx}. {status} `{ch_name}`\n   👤 المستخدم: `{uid}`\n   🆔 القناة: `{ch_tele}`\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_banned_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    channels = await db_all_users_channels(only_banned=True, limit=500)
    if not channels:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا توجد قنوات محظورة.", reply_markup=keyboard)
        return
    text = "⛔ **قنوات المستخدمين المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for uid, ch_id, ch_tele, ch_name, banned in channels[:50]:
        text += f"• المستخدم: `{uid}` | القناة: {ch_name} (`{ch_tele}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ تنشيط الكل", callback_data=CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_activate_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    async def _activate_all(conn):
        await conn.execute("UPDATE user_channels SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_activate_all)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, "✅ تم إلغاء حظر جميع قنوات المستخدمين.", reply_markup=keyboard)

async def admin_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    groups = await db_get_all_groups(only_banned=False)
    if not groups:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا توجد مجموعات مسجلة.", reply_markup=keyboard)
        return
    text = "👥 **المجموعات المسجلة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for gid, gname, username, added_by, added_at, banned in groups[:50]:
        status = "⛔ محظورة" if banned else "✅ نشطة"
        text += f"• {gname} (ID: `{gid}`)\n  الحالة: {status}\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_banned_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    groups = await db_get_all_groups(only_banned=True)
    if not groups:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا توجد مجموعات محظورة.", reply_markup=keyboard)
        return
    text = "🚷 **المجموعات المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for gid, gname, username, added_by, added_at, banned in groups[:50]:
        text += f"• {gname} (ID: `{gid}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_GROUPS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_unban_all_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    async def _unban_groups(conn):
        await conn.execute("UPDATE bot_groups SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_groups)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, "✅ تم إلغاء حظر جميع المجموعات.", reply_markup=keyboard)

async def admin_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    channels = await db_get_all_bot_channels(only_banned=False)
    if not channels:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا توجد قنوات أضيف إليها البوت.", reply_markup=keyboard)
        return
    text = "📢 **قنوات البوت**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for channel_id, channel_name, added_by, added_at, banned in channels[:50]:
        text += f"• {channel_name} (ID: `{channel_id}`)\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_banned_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    channels = await db_get_all_bot_channels(only_banned=True)
    if not channels:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا توجد قنوات بوت محظورة.", reply_markup=keyboard)
        return
    text = "🚫 **قنوات البوت المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for channel_id, channel_name, added_by, added_at, banned in channels[:50]:
        text += f"• {channel_name} (ID: `{channel_id}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_BOT_CHANNELS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_unban_all_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    async def _unban_bot_channels(conn):
        await conn.execute("UPDATE bot_channels SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_bot_channels)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, "✅ تم إلغاء حظر جميع قنوات البوت.", reply_markup=keyboard)

async def admin_monitor_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    all_users = await db_get_all_users()
    total_users = len(all_users)
    active_users = len([u for u in all_users if u[1] == 0])
    banned_users = len([u for u in all_users if u[1] == 1])
    admins_list = await get_all_bot_admins()
    admin_count = len(admins_list)
    all_channels = await db_all_users_channels()
    channels_count = len(all_channels)
    all_groups = await db_get_all_groups()
    groups_count = len(all_groups)
    text = f"📂 **مراقبة المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n👥 إجمالي المستخدمين: {total_users}\n✅ النشطاء: {active_users}\n🚫 المحظورون: {banned_users}\n👑 المشرفون: {admin_count}\n━━━━━━━━━━━━━━━━━━━━━━\n📡 قنوات المستخدمين: {channels_count}\n👥 المجموعات المسجلة: {groups_count}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_add_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_ADMIN_ID_ADD
    await safe_edit(query, get_text(user_id, 'enter_admin_id'))

async def admin_remove_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    admins = await get_all_bot_admins()
    if not admins:
        await safe_edit(query, get_text(user_id, 'no_admins'))
        return
    text = "👑 المشرفون الحاليون:\n"
    for a in admins:
        text += f"- {a}\n"
    text += "\n" + get_text(user_id, 'enter_remove_admin_id')
    context.user_data['state'] = UserState.WAITING_ADMIN_ID_REMOVE
    await safe_edit(query, text)

async def admin_ram_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    ram = get_ram_usage()
    text = f"🖥️ **حالة الرام**\n━━━━━━━━━━━━━━━━━━━━━━\n• الإجمالي: {ram['total']} GB\n• المستخدم: {ram['used']} GB\n• النسبة: {ram['percent']}%"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    total, banned, posts, groups, channels = await db_stats()
    text = f"📊 **إحصائيات عامة**\n━━━━━━━━━━━━━━━━━━━━━━\n• المستخدمين: {total}\n• المحظورين: {banned}\n• المنشورات غير المنشورة: {posts}\n• المجموعات: {groups}\n• قنوات المستخدمين: {channels}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_metrics_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    ram = get_ram_usage()
    text = f"📈 **مقاييس الأداء**\n━━━━━━━━━━━━━━━━━━━━━━\n🖥️ **حالة النظام:**\n• إجمالي الرام: {ram['total']} GB\n• المستخدم: {ram['used']} GB\n• النسبة: {ram['percent']}%"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    backup_file = await create_backup()
    if backup_file:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, f"✅ تم إنشاء نسخة احتياطية جديدة.\n📁 اسم الملف: `{backup_file.name}`", reply_markup=keyboard)
    else:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "❌ فشل إنشاء النسخة الاحتياطية.", reply_markup=keyboard)

async def admin_restore_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    backups = await list_backups()
    if not backups:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا توجد نسخ احتياطية.", reply_markup=keyboard)
        return
    keyboard = []
    for b in backups[:10]:
        keyboard.append([InlineKeyboardButton(b.name, callback_data=f"{CallbackData.ADMIN_RESTORE_BACKUP_SELECT_PREFIX}{b.name}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)])
    await safe_edit(query, "💾 اختر النسخة الاحتياطية للاستعادة:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_restore_backup_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    backup_name = query.data.split(":")[-1]
    backup_path = BACKUP_DIR / backup_name
    if await restore_backup(backup_path):
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, f"✅ تم استعادة النسخة الاحتياطية بنجاح.\n📁 الملف: `{backup_name}`", reply_markup=keyboard)
    else:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "❌ فشل استعادة النسخة.", reply_markup=keyboard)

async def admin_backup_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    auto = await db_get_auto_backup()
    status = "مفعل" if auto else "معطل"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تبديل النسخ التلقائي", callback_data=CallbackData.ADMIN_TOGGLE_AUTO_BACKUP)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    text = f"⚙️ **إعدادات النسخ الاحتياطي**\n━━━━━━━━━━━━━━━━━━━━━━\n• النسخ التلقائي: {status}\n• الحد الأقصى للنسخ: {MAX_BACKUPS}"
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_toggle_auto_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    auto = await db_get_auto_backup()
    new_auto = not auto
    await db_set_auto_backup(new_auto)
    status = "مفعل" if new_auto else "معطل"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, f"✅ تم تغيير إعداد النسخ التلقائي إلى: {status}", reply_markup=keyboard)

async def admin_change_interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    current = await db_get_publish_interval()
    current_min = current // 60
    context.user_data['state'] = UserState.WAITING_INTERVAL_MINUTES
    context.user_data['admin_interval'] = True
    await safe_edit(query, f"⏱️ **وقت النشر العام الحالي:** {current_min} دقيقة\nأرسل العدد الجديد من الدقائق (1-1440):")

async def admin_send_update_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    channel = await db_get_updates_channel()
    if not channel:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ تعيين قناة", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
        ])
        await safe_edit(query, "⚠️ **لم يتم تعيين قناة تحديثات بعد!**", reply_markup=keyboard)
        return
    context.user_data['state'] = UserState.WAITING_UPDATE_TEXT
    await safe_edit(query, f"📢 أرسل نص التحديث الذي تريد نشره في قناة التحديثات @{channel}:")

async def admin_set_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_UPDATE_CHANNEL
    await safe_edit(query, "⚙️ **تعيين قناة التحديثات**\nأرسل معرف قناة التحديثات:\n• `@username`\n• أو المعرف الرقمي")

async def admin_show_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    channel = await db_get_updates_channel()
    if channel:
        text = f"📢 **قناة التحديثات الحالية:**\n`@{channel}`"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 فتح القناة", url=f"https://t.me/{channel}")],
            [InlineKeyboardButton("🔄 تغيير القناة", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
        ])
    else:
        text = "📢 **لم يتم تعيين قناة تحديثات بعد**"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ تعيين قناة", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
        ])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_force_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    enabled = await db_get_force_subscribe_status()
    new_status = not enabled
    await db_set_force_subscribe_status(new_status)
    status_text = "مفعل" if new_status else "معطل"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, f"✅ تم {status_text} الاشتراك الإجباري.", reply_markup=keyboard)

async def admin_set_force_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_FORCE_CHANNEL
    await safe_edit(query, "⚙️ أرسل معرف قناة الاشتراك الإجباري:")

async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_BROADCAST
    await safe_edit(query, "📨 أرسل النص الذي تريد إرساله إلى جميع المستخدمين:")

async def admin_confirm_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    broadcast_text = context.user_data.get('broadcast_text', '')
    if not broadcast_text:
        await safe_edit(query, "❌ لا يوجد نص للإرسال")
        return
    await safe_edit(query, "📨 جاري الإرسال...")
    users = await db_get_all_users()
    sent = 0
    failed = 0
    for uid, banned in users:
        if banned:
            continue
        try:
            await safe_send(context.bot, uid, broadcast_text)
            sent += 1
        except:
            failed += 1
        await asyncio.sleep(0.5)
    context.user_data.pop('broadcast_text', None)
    context.user_data.pop('state', None)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, f"✅ **تم إرسال الرسالة**\n\n📨 تم الإرسال إلى: {sent} مستخدم\n❌ فشل الإرسال إلى: {failed} مستخدم", reply_markup=keyboard)

async def admin_support_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    tickets = await db_get_all_tickets(limit=20)
    if not tickets:
        await safe_edit(query, "📭 لا توجد تذاكر دعم مسجلة")
        return
    text = "📋 **تذاكر الدعم**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for tid, uid_u, username, msg, ticket_num, status, created_at in tickets:
        try:
            dt = datetime.fromisoformat(created_at)
            dt_mecca = utc_to_mecca(dt)
            created_str = dt_mecca.strftime("%Y-%m-%d %H:%M")
        except:
            created_str = created_at
        status_icon = "🟡" if status == "pending" else "🟢"
        msg_preview = msg[:40] + "..." if len(msg) > 40 else msg
        text += f"{status_icon} #{ticket_num} | 👤 {username}\n🆔 `{uid_u}` | 📅 {created_str}\n📝 {msg_preview}\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_delete_all_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    confirm_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، احذف الكل", callback_data=CallbackData.ADMIN_CONFIRM_DELETE_TICKETS),
         InlineKeyboardButton("❌ لا، إلغاء", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit(query, "⚠️ هل أنت متأكد من حذف جميع تذاكر الدعم؟", reply_markup=confirm_kb)

async def admin_confirm_delete_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    count = await db_delete_all_tickets()
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, f"✅ تم حذف {count} تذكرة", reply_markup=keyboard)

async def admin_manage_sendcode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    allowed_user = await db_get_allowed_sendcode_user()
    if allowed_user:
        current_text = get_text(user_id, 'current_allowed_user').format(f"`{allowed_user}`")
    else:
        current_text = get_text(user_id, 'current_allowed_user').format(get_text(user_id, 'no_allowed_user'))
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'set_new_sendcode_user'), callback_data=CallbackData.ADMIN_SET_SENDCODE_USER)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit(query, current_text, reply_markup=keyboard)

async def admin_set_sendcode_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_SENDCODE_USER
    await safe_edit(query, "➕ أرسل معرف المستخدم (user_id) الذي تريد منحه صلاحية استخدام أمر /sendcode:")

async def admin_show_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    log_ch = await db_get_log_channel_id()
    if log_ch:
        text = f"📋 **قناة التقارير الحالية:**\n`{log_ch}`"
    else:
        text = "📋 **لم يتم تعيين قناة تقارير بعد.**"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_set_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
    await safe_edit(query, "📢 **تعيين قناة التقارير**\nأرسل معرف القناة (ID) أو معرف المستخدم (@username):")

async def admin_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    await safe_edit(query, "💬 **إدارة ردود المجموعة**", reply_markup=get_replies_keyboard())

async def admin_add_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_KEYWORD
    await safe_edit(query, "📝 **إضافة رد تلقائي**\nأرسل الكلمة المفتاحية:")

async def admin_list_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    replies = await db_get_all_replies()
    if not replies:
        await safe_edit(query, "📭 لا توجد ردود مسجلة.")
        return
    text = "💬 **قائمة الردود التلقائية**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for kw, rep in replies[:30]:
        short_rep = rep[:40] + "..." if len(rep) > 40 else rep
        text += f"• **{kw}** → {short_rep}\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_del_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    if query and query.data.startswith("admin_del_reply_"):
        keyword = query.data.replace("admin_del_reply_", "")
        if await db_del_reply(keyword):
            await query.answer(f"✅ تم حذف رد {keyword}", show_alert=True)
        else:
            await query.answer(f"❌ الكلمة {keyword} غير موجودة", show_alert=True)
        await admin_list_replies_callback(update, context)
    else:
        context.user_data['state'] = UserState.WAITING_REPLY
        context.user_data['admin_del_reply'] = True
        await safe_edit(query, "🗑️ **حذف رد تلقائي**\nأرسل الكلمة المفتاحية لحذف ردها:")

async def admin_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    await safe_edit(query, "🚫 **إدارة الكلمات المحظورة**", reply_markup=get_banned_words_admin_keyboard())

async def admin_add_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_GLOBAL_BANNED_WORD
    await safe_edit(query, "➕ أرسل الكلمة التي تريد حظرها على مستوى البوت:")

async def admin_list_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    words = await db_get_banned_words(-1)
    if not words:
        await safe_edit(query, "📭 لا توجد كلمات محظورة عامة.")
        return
    text = "🚫 **الكلمات المحظورة عامة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for w, by, at in words[:20]:
        text += f"• `{w}` (أضيف بواسطة {by})\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_remove_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_REMOVE_GLOBAL_BANNED_WORD
    await safe_edit(query, "🗑️ أرسل الكلمة التي تريد حذفها من الكلمات المحظورة العامة:")

async def admin_del_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    word = query.data.replace("admin_del_banned_word_", "")
    async def _remove_global_word(conn):
        await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
        await conn.commit()
    await execute_db(_remove_global_word)
    await query.answer(f"✅ تم حذف {word}", show_alert=True)
    await admin_list_banned_words_callback(update, context)

async def admin_toggle_channel_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    channel_db_id = int(query.data.split(":")[-1])
    async def _get_ban(conn):
        cur = await conn.execute("SELECT banned FROM user_channels WHERE id=?", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    current = await execute_db(_get_ban)
    new_status = 0 if current == 1 else 1
    async def _update_ban(conn):
        await conn.execute("UPDATE user_channels SET banned=? WHERE id=?", (new_status, channel_db_id))
        await conn.commit()
    await execute_db(_update_ban)
    status_text = "محظورة" if new_status == 1 else "نشطة"
    await query.answer(f"✅ تم تغيير حالة القناة إلى: {status_text}", show_alert=True)
    await admin_all_channels_callback(update, context)

async def admin_toggle_group_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    group_chat_id = int(query.data.split(":")[-1])
    async def _get_ban(conn):
        cur = await conn.execute("SELECT banned FROM bot_groups WHERE chat_id=?", (group_chat_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    current = await execute_db(_get_ban)
    new_status = 0 if current == 1 else 1
    async def _update_ban(conn):
        await conn.execute("UPDATE bot_groups SET banned=? WHERE chat_id=?", (new_status, group_chat_id))
        await conn.commit()
    await execute_db(_update_ban)
    status_text = "محظورة" if new_status == 1 else "نشطة"
    await query.answer(f"✅ تم تغيير حالة المجموعة إلى: {status_text}", show_alert=True)
    await admin_groups_callback(update, context)

async def auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def auto_reply_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، إعادة تعيين", callback_data=f"auto_reply_confirm_reset:{chat_id}")],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"auto_reply_cancel:{chat_id}")]
    ])
    await safe_edit(query, "⚠️ **تأكيد إعادة التعيين**\nسيتم حذف جميع الردود المخصصة. هل أنت متأكد؟", reply_markup=keyboard)

async def auto_reply_confirm_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    async def _reset_replies(conn):
        await conn.execute("DELETE FROM group_replies WHERE keyword LIKE ?", (f"{chat_id}:%",))
        await conn.commit()
    await execute_db(_reset_replies)
    await db_set_auto_reply_enabled(chat_id, True)
    await db_set_auto_reply_only_admins(chat_id, False)
    settings = await db_get_auto_reply_settings(chat_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 الردود التلقائية: {'🟢 مفعل' if settings['enabled'] else '🔴 معطل'}", callback_data=f"auto_reply_toggle:{chat_id}")],
        [InlineKeyboardButton(f"👥 المستخدمون: {'👑 مشرفين فقط' if settings['only_admins'] else '👥 الجميع'}", callback_data=f"auto_reply_admins:{chat_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"groups:settings:{chat_id}")]
    ])
    await safe_edit(query, "✅ **تم إعادة تعيين الردود بنجاح!**", reply_markup=keyboard)

async def auto_reply_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    settings = await db_get_auto_reply_settings(chat_id)
    await safe_edit(query, "❌ تم إلغاء إعادة التعيين", reply_markup=settings_keyboard)

async def auto_reply_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    async def _get_stats(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM group_replies WHERE keyword LIKE ?", (f"{chat_id}:%",))
        custom_count = (await cur.fetchone())[0]
        return {'custom_replies': custom_count, 'embedded_replies': len(ALL_REPLIES)}
    stats = await execute_db(_get_stats)
    settings = await db_get_auto_reply_settings(chat_id)
    status_text = "🟢 مفعل" if settings['enabled'] else "🔴 معطل"
    admin_text = "👑 مشرفين فقط" if settings['only_admins'] else "👥 الجميع"
    text = f"📊 **إحصائيات الردود التلقائية**\n━━━━━━━━━━━━━━━━━━━━━━\n📝 **الحالة:** {status_text}\n👥 **المستخدمون:** {admin_text}\n📋 **الردود المخصصة:** {stats['custom_replies']}\n💾 **الردود المدمجة:** {stats['embedded_replies']}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 الردود التلقائية: {status_text}", callback_data=f"auto_reply_toggle:{chat_id}")],
        [InlineKeyboardButton(f"👥 المستخدمون: {admin_text}", callback_data=f"auto_reply_admins:{chat_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"groups:settings:{chat_id}")]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def user_auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split(":")[-1])
    current_status = await db_get_user_auto_reply_status(user_id)
    new_status = not current_status
    await db_set_user_auto_reply_status(user_id, new_status)
    status_text = "🟢 مفعل" if new_status else "🔴 معطل"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 الردود التلقائية: {status_text}", callback_data=f"user_auto_reply_toggle:{user_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await safe_edit(query, f"✅ تم تغيير حالة الردود التلقائية", reply_markup=keyboard)

async def admin_auto_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        settings = await db_get_auto_reply_settings(gid)
        status = "🟢" if settings['enabled'] else "🔴"
        keyboard.append([InlineKeyboardButton(f"{status} {gname[:30]}", callback_data=f"admin_auto_reply_select:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)])
    await safe_edit(query, "📝 **إدارة الردود التلقائية**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_auto_reply_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def nsfw_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    await safe_edit(query, "🔞 **إعدادات NSFW**\n📌 نظام كشف المحتوى غير اللائق")

async def nsfw_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await nsfw_settings_callback(update, context)

async def nsfw_threshold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_NSFW_THRESHOLD
    await safe_edit(query, "📊 أرسل النسبة المئوية (من 0 إلى 100):")

async def contests_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await contests_command(update, context)

async def contest_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    contest_id = int(query.data.split(":")[-1])
    contest = await db_get_contest(contest_id)
    if not contest:
        await safe_edit(query, "❌ المسابقة غير موجودة.")
        return
    if contest['status'] != 'active':
        await safe_edit(query, "❌ هذه المسابقة غير متاحة حالياً.")
        return
    if await db_get_user_participation(user_id, contest_id):
        await safe_edit(query, get_text(user_id, 'contest_participated'))
        return
    context.user_data['contest_join_id'] = contest_id
    context.user_data['state'] = UserState.WAITING_CONTEST_ANSWER
    await safe_edit(query, f"📝 **المشاركة في المسابقة: {contest['title']}**\nأرسل إجابتك أو اضغط /skip")

async def contest_winners_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    winners = await db_get_contest_winners(limit=10)
    if not winners:
        text = get_text(user_id, 'no_winners')
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.CONTESTS_BACK)]])
        await safe_edit(query, text, reply_markup=keyboard)
        return
    text = get_text(user_id, 'contest_winners_title')
    for contest_id, title, prize, winner_id, announced_at in winners:
        try:
            winner = await context.bot.get_chat(winner_id)
            winner_name = winner.first_name or str(winner_id)
        except:
            winner_name = str(winner_id)
        try:
            dt = datetime.fromisoformat(announced_at)
            dt_mecca = utc_to_mecca(dt)
            date_str = dt_mecca.strftime("%Y-%m-%d")
        except:
            date_str = announced_at[:10] if announced_at else "?"
        text += f"📌 **{title}**\n🎁 {prize}\n👤 {winner_name}\n📅 {date_str}\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=CallbackData.CONTEST_WINNERS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.CONTESTS_BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def contests_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await contests_menu_callback(update, context)

async def admin_create_contest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_CONTEST_TITLE
    await safe_edit(query, get_text(user_id, 'create_contest_title'))

async def admin_declare_winner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    await safe_edit(query, get_text(user_id, 'declare_winner_usage'))

async def security_links_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['links'] = not settings['links']
    await db_set_security_settings(chat_id, **settings)
    await safe_edit(query, "✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_mentions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['mentions'] = not settings['mentions']
    await db_set_security_settings(chat_id, **settings)
    await safe_edit(query, "✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_warn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['warn'] = not settings['warn']
    await db_set_security_settings(chat_id, **settings)
    await safe_edit(query, "✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_slowmode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['slow_mode'] = not settings['slow_mode']
    await db_set_security_settings(chat_id, **settings)
    await safe_edit(query, "✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_banned_words_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['banned_words_chat_id'] = chat_id
    await safe_edit(query, "🚫 إدارة الكلمات المحظورة للمجموعة", reply_markup=get_group_banned_words_keyboard(chat_id))

async def security_welcome_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['welcome_enabled'] = not settings['welcome_enabled']
    await db_set_security_settings(chat_id, **settings)
    await safe_edit(query, "✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_goodbye_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    settings = await db_get_security_settings(chat_id)
    settings['goodbye_enabled'] = not settings['goodbye_enabled']
    await db_set_security_settings(chat_id, **settings)
    await safe_edit(query, "✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.delete()

async def security_select_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "❌ **غير مصرح**")
        return
    settings = await db_get_security_settings(chat_id)
    text = f"🔐 **إعدادات الأمان**\n━━━━━━━━━━━━━━━━━━━━━━\n🔗 حذف الروابط: {'✅' if settings['links'] else '❌'}\n@ حذف المعرفات: {'✅' if settings['mentions'] else '❌'}\n⏱️ وضع بطيء: {'✅' if settings['slow_mode'] else '❌'}\n🎯 ترحيب: {'✅' if settings['welcome_enabled'] else '❌'}"
    await safe_edit(query, text)

async def security_refresh_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    groups = await db_get_user_groups(user_id)
    if not groups:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        await safe_edit(query, "📭 لا توجد مجموعات مسجلة", reply_markup=keyboard)
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        keyboard.append([InlineKeyboardButton(f"📌 {gname[:30]}", callback_data=f"{CallbackData.SECURITY_SELECT_GROUP}{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await safe_edit(query, "🔐 **اختر مجموعة:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def banned_words_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    await safe_edit(query, "➕ أرسل الكلمة التي تريد إضافتها:")

async def banned_words_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    words = await db_get_banned_words(chat_id)
    if not words:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]])
        await safe_edit(query, "📭 لا توجد كلمات محظورة", reply_markup=keyboard)
        return
    text = "🚫 **الكلمات المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for word, added_by, added_at in words[:20]:
        text += f"• `{word}` (أضيف بواسطة {added_by})\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]])
    await safe_edit(query, text, reply_markup=keyboard)

async def banned_words_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_REMOVE_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    await safe_edit(query, "🗑️ أرسل الكلمة التي تريد حذفها:")

async def penalty_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    await safe_edit(query, "⚖️ **اختر العقوبة التلقائية:**", reply_markup=penalty_keyboard(chat_id))

async def penalty_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    await db_set_security_settings(chat_id, auto_penalty='kick')
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    await safe_edit(query, "✅ تم تعيين العقوبة إلى: **طرد**", reply_markup=keyboard)

async def penalty_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    await db_set_security_settings(chat_id, auto_penalty='ban')
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    await safe_edit(query, "✅ تم تعيين العقوبة إلى: **حظر**", reply_markup=keyboard)

async def penalty_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['penalty_chat_id'] = chat_id
    await safe_edit(query, "🔇 **اختر مدة الكتم:**", reply_markup=mute_duration_keyboard(chat_id))

async def penalty_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
        await safe_edit(query, f"✅ تم تعيين العقوبة إلى: **كتم {text}**", reply_markup=keyboard)

async def advanced_actions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await safe_edit(query, "🛠️ **الإجراءات المتقدمة**", reply_markup=get_advanced_group_actions_keyboard(chat_id))

async def group_action_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_BAN_USER
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "🚫 أرسل معرف المستخدم لحظره:\n`/ban 123456789`")

async def group_action_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    await safe_edit(query, "🔇 **اختر مدة الكتم:**", reply_markup=get_advanced_mute_duration_keyboard(chat_id))

async def advanced_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_WARN_USER
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "⚠️ أرسل معرف المستخدم لتحذيره:\n`/warn 123456789`")

async def group_action_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    context.user_data['state'] = UserState.WAITING_KICK_USER
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "👢 أرسل معرف المستخدم لطرده:\n`/kick 123456789`")

async def group_action_restrict_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    text = await get_moderation_log(chat_id, 20)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    await safe_edit(query, text, reply_markup=keyboard)

async def group_action_unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if await check_admin_access(update, context):
        await db_set_chat_lock(chat_id, True, user_id)
        await safe_edit(query, get_text(user_id, 'locked'))
    else:
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")

async def panel_unlock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if await check_admin_access(update, context):
        await db_set_chat_lock(chat_id, False)
        await safe_edit(query, get_text(user_id, 'unlocked'))
    else:
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")

async def panel_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.delete()

async def check_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]])
    await safe_edit(query, result_text, reply_markup=keyboard)

async def channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{channel_db_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
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
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{channel_db_id}")],
        [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{channel_db_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def channel_growth_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.CHANNEL_STATS}:{channel_db_id}")]])
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
        [InlineKeyboardButton("📊 العودة للإحصائيات", callback_data=f"{CallbackData.CHANNEL_STATS}:{channel_db_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def channel_stats_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await channel_stats_callback(update, context)

async def my_channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    summary = await db_get_channel_stats_summary(user_id)
    if not summary:
        text = "📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد قنوات مسجلة."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة قناة", callback_data=CallbackData.CHANNELS_ADD)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
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
        [InlineKeyboardButton("📡 عرض القنوات", callback_data=CallbackData.CHANNELS_MY)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def schedule_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    context.user_data['schedule_chat_id'] = chat_id
    context.user_data['state'] = UserState.WAITING_SCHEDULE_POST
    await safe_edit(query, "📝 **أرسل المنشور بالصيغة التالية:**\n`YYYY-MM-DD HH:MM نص المنشور`")

async def register_hidden_owner_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def rules_show_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 هذا الأمر للمشرفين فقط!")
        return
    rules = await db_get_group_rules(chat_id)
    if not rules:
        rules = DEFAULT_RULES
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"rules_show:{chat_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, rules, reply_markup=keyboard)

async def reset_rules_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await check_admin_access(update, context):
        await safe_edit(query, "🔒 غير مصرح!")
        return
    await db_delete_group_rules(chat_id)
    await safe_edit(query, "✅ **تم إعادة تعيين القوانين للافتراضي!**")

async def reset_rules_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_edit(query, "❌ تم إلغاء إعادة التعيين.")

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
# ===================== معالج الرسائل =====================
# ====================================================================

async def message_handler_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text or ""
    state = context.user_data.get('state')
    
    if text == "/cancel":
        context.user_data.pop('state', None)
        await update.message.reply_text(get_text(user_id, 'cancelled'))
        await main_menu_callback(update, context)
        return
    
    if state == UserState.WAITING_CHANNEL_ID:
        channel_id = text.strip()
        new_id = await db_add_channel(user_id, channel_id, channel_id)
        if new_id:
            await db_set_active_channel(user_id, new_id)
            await update.message.reply_text(get_text(user_id, 'channel_added').format(channel_id))
        else:
            await update.message.reply_text(get_text(user_id, 'channel_exists'))
        context.user_data.pop('state', None)
        await main_menu_callback(update, context)
        return
    
    if state == UserState.ADDING_POSTS:
        posts = context.user_data.get('session_posts', [])
        target = context.user_data.get('session_target', 15)
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
        posts.append((text_content, media_type, media_file_id))
        context.user_data['session_posts'] = posts
        if len(posts) >= target:
            active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
            if active:
                saved = await db_save_posts(active, posts)
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور")
            context.user_data.pop('state', None)
            context.user_data.pop('session_posts', None)
            await main_menu_callback(update, context)
        else:
            await update.message.reply_text(f"📥 {len(posts)}/{target}")
        return
    
    if state == UserState.WAITING_ADMIN_ID_ADD:
        try:
            target_id = int(text)
            if target_id == PRIMARY_OWNER_ID:
                await update.message.reply_text("❌ لا يمكن إزالة المطور الأساسي")
            else:
                await add_bot_admin(target_id)
                await update.message.reply_text(f"✅ تم إضافة {target_id} كمشرف")
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    if state == UserState.WAITING_ADMIN_ID_REMOVE:
        try:
            target_id = int(text)
            if target_id == PRIMARY_OWNER_ID:
                await update.message.reply_text("❌ لا يمكن إزالة المطور الأساسي")
            else:
                await remove_bot_admin(target_id)
                await update.message.reply_text(f"✅ تم إزالة {target_id} من المشرفين")
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    if state == UserState.WAITING_INTERVAL_MINUTES:
        ch_db_id = context.user_data.get('schedule_ch_id')
        is_admin = context.user_data.get('admin_interval', False)
        try:
            minutes = int(text)
            if minutes < 1:
                minutes = 1
            if is_admin:
                seconds = minutes * 60
                await db_set_publish_interval_seconds(seconds, user_id, is_admin=True)
                await update.message.reply_text(f"✅ تم ضبط وقت النشر العام إلى {minutes} دقيقة")
                await admin_panel_callback(update, context)
            else:
                await db_save_schedule(ch_db_id, 'interval_minutes', interval_minutes=minutes)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text("✅ تم حفظ الإعدادات")
                await schedule_menu_callback(update, context)
        except ValueError:
            await update.message.reply_text("❌ رقم غير صالح")
        context.user_data.pop('state', None)
        return
    
    if state == UserState.WAITING_INTERVAL_HOURS:
        ch_db_id = context.user_data.get('schedule_ch_id')
        try:
            hours = int(text)
            if hours < 1:
                hours = 1
            await db_save_schedule(ch_db_id, 'interval_hours', interval_hours=hours)
            await db_set_next_publish_date(ch_db_id, None)
            await update.message.reply_text("✅ تم حفظ الإعدادات")
        except ValueError:
            await update.message.reply_text("❌ رقم غير صالح")
        context.user_data.pop('state', None)
        await schedule_menu_callback(update, context)
        return
    
    if state == UserState.WAITING_INTERVAL_DAYS:
        ch_db_id = context.user_data.get('schedule_ch_id')
        try:
            days = int(text)
            if days < 1:
                days = 1
            await db_save_schedule(ch_db_id, 'interval_days', interval_days=days)
            await db_set_next_publish_date(ch_db_id, None)
            await update.message.reply_text("✅ تم حفظ الإعدادات")
        except ValueError:
            await update.message.reply_text("❌ رقم غير صالح")
        context.user_data.pop('state', None)
        await schedule_menu_callback(update, context)
        return
    
    if state == UserState.WAITING_DATES:
        ch_db_id = context.user_data.get('schedule_ch_id')
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
        await update.message.reply_text("✅ تم حفظ الإعدادات")
        context.user_data.pop('state', None)
        await schedule_menu_callback(update, context)
        return
    
    if state == UserState.WAITING_PUBLISH_TIME:
        ch_db_id = context.user_data.get('schedule_ch_id')
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
        context.user_data.pop('state', None)
        await schedule_menu_callback(update, context)
        return
    
    if state == UserState.WAITING_SCHEDULE_POST:
        chat_id = context.user_data.get('schedule_chat_id')
        if not chat_id:
            await update.message.reply_text("❌ لم يتم تحديد المجموعة.")
            return
        args = text.split()
        if len(args) < 3:
            await update.message.reply_text("❌ **صيغة غير صحيحة!**\n\nالاستخدام:\n`YYYY-MM-DD HH:MM نص المنشور`")
            return
        try:
            date_str = args[0]
            time_str = args[1]
            post_text = " ".join(args[2:])
            mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if mecca_dt <= mecca_now():
                await update.message.reply_text("❌ **الوقت يجب أن يكون في المستقبل!**")
                return
            utc_dt = mecca_to_utc(mecca_dt)
            await db_add_scheduled_post(chat_id, post_text, utc_dt)
            await update.message.reply_text(f"✅ **تم جدولة المنشور!**\n📅 {date_str} 🕐 {time_str} (بتوقيت مكة)")
        except ValueError:
            await update.message.reply_text("❌ **صيغة التاريخ أو الوقت غير صحيحة!**")
        context.user_data.pop('state', None)
        await main_menu_callback(update, context)
        return
    
    if state == UserState.WAITING_REMINDER_DAYS:
        try:
            days = int(text)
            if 1 <= days <= 10:
                await db_update_reminder_settings(user_id, reminder_days_before=days)
                await update.message.reply_text(f"✅ تم تعيين التذكير قبل {days} يوم")
            else:
                await update.message.reply_text("❌ الرجاء إدخال رقم بين 1 و 10")
        except ValueError:
            await update.message.reply_text("❌ الرجاء إدخال رقم صحيح")
        context.user_data.pop('state', None)
        await reminder_menu_callback(update, context)
        return
    
    if state == UserState.WAITING_UPDATE_TEXT:
        channel = await db_get_updates_channel()
        if channel:
            try:
                await context.bot.send_message(chat_id=f"@{channel}", text=text)
                await update.message.reply_text("✅ تم نشر التحديث")
            except Exception as e:
                await update.message.reply_text(f"❌ فشل النشر: {str(e)[:100]}")
        else:
            await update.message.reply_text("❌ لم يتم تعيين قناة تحديثات بعد")
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    if state == UserState.WAITING_UPDATE_CHANNEL:
        channel = text.strip()
        if channel.startswith('@'):
            channel = channel[1:]
        if not channel:
            await update.message.reply_text("❌ **معرف قناة غير صالح!**")
            return
        if await db_set_updates_channel(channel):
            await update.message.reply_text(f"✅ **تم تعيين قناة التحديثات:** @{channel}")
        else:
            await update.message.reply_text("❌ **فشل حفظ القناة!**")
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    if state == UserState.WAITING_FORCE_CHANNEL:
        await db_set_force_subscribe_channel(text)
        await update.message.reply_text(f"✅ تم تعيين قناة الاشتراك الإجباري: {text}")
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    if state == UserState.WAITING_BROADCAST:
        context.user_data['broadcast_text'] = text
        confirm_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم، أرسل", callback_data=CallbackData.ADMIN_CONFIRM_BROADCAST),
             InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.ADMIN_PANEL)]
        ])
        await update.message.reply_text(
            f"📨 **تأكيد الإرسال الجماعي**\n\nالنص:\n{text[:500]}\n\n⚠️ سيتم إرسالها لجميع المستخدمين",
            reply_markup=confirm_kb
        )
        context.user_data.pop('state', None)
        return
    
    if state == UserState.WAITING_SENDCODE_USER:
        try:
            target_user_id = int(text)
        except ValueError:
            await update.message.reply_text("❌ رقم غير صالح")
            return
        await db_set_allowed_sendcode_user(target_user_id)
        await update.message.reply_text(f"✅ تم تعيين {target_user_id} كمستخدم مصرح له بـ /sendcode")
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    if state == UserState.WAITING_LOG_CHANNEL:
        identifier = text.strip()
        try:
            if identifier.startswith('@'):
                identifier = identifier[1:]
            if identifier.startswith('-100') or identifier.lstrip('-').isdigit():
                chat_id = int(identifier)
            else:
                chat = await context.bot.get_chat(f"@{identifier}")
                chat_id = chat.id
            await db_set_log_channel_id(str(chat_id))
            await update.message.reply_text(f"✅ **تم تعيين قناة التقارير:** `{chat_id}`")
        except Exception as e:
            await update.message.reply_text(f"❌ **لا يمكن الوصول إلى القناة:** {str(e)[:100]}")
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    if state == UserState.WAITING_KEYWORD:
        keyword = text.strip().lower()
        if len(keyword) < 2:
            await update.message.reply_text("❌ الكلمة قصيرة جداً")
            return
        context.user_data['state'] = UserState.WAITING_REPLY
        context.user_data['admin_keyword'] = keyword
        await update.message.reply_text(f"📝 أرسل الرد للكلمة: `{keyword}`")
        return
    
    if state == UserState.WAITING_REPLY:
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
        context.user_data.pop('state', None)
        await admin_replies_callback(update, context)
        return
    
    if state == UserState.WAITING_GROUP_BANNED_WORD:
        chat_id = context.user_data.get('banned_words_chat_id')
        if chat_id:
            word = text.lower()
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
    
    if state == UserState.WAITING_GLOBAL_BANNED_WORD:
        word = text.lower()
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
    
    if state == UserState.WAITING_NSFW_THRESHOLD:
        try:
            threshold = float(text)
            if 0 < threshold <= 100:
                global NSFW_THRESHOLD
                NSFW_THRESHOLD = threshold / 100
                await update.message.reply_text(f"✅ تم تغيير نسبة الحساسية إلى: {threshold}%")
            else:
                await update.message.reply_text("❌ الرجاء إدخال رقم بين 1 و 100")
        except ValueError:
            await update.message.reply_text("❌ الرجاء إدخال رقم صحيح")
        context.user_data.pop('state', None)
        await nsfw_settings_callback(update, context)
        return
    
    if state == UserState.WAITING_BAN_USER:
        parts = text.split(maxsplit=1)
        reason = parts[1] if len(parts) > 1 else ""
        try:
            target_id = int(parts[0])
            success, msg = await execute_ban(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
            await safe_send(context.bot, chat_id, msg)
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
            success, msg = await execute_mute(context.bot, chat_id, target_id, minutes, reason=reason, moderator_id=user_id)
            await safe_send(context.bot, chat_id, msg)
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        return
    
    if state == UserState.WAITING_WARN_USER:
        parts = text.split(maxsplit=1)
        reason = parts[1] if len(parts) > 1 else ""
        try:
            target_id = int(parts[0])
            success, msg = await execute_warn(context.bot, chat_id, target_id, user_id, reason=reason)
            await safe_send(context.bot, chat_id, msg)
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        return
    
    if state == UserState.WAITING_KICK_USER:
        parts = text.split(maxsplit=1)
        reason = parts[1] if len(parts) > 1 else ""
        try:
            target_id = int(parts[0])
            success, msg = await execute_kick(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
            await safe_send(context.bot, chat_id, msg)
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        return
    
    if state == UserState.WAITING_RESTRICT_USER:
        parts = text.split(maxsplit=1)
        reason = parts[1] if len(parts) > 1 else ""
        try:
            target_id = int(parts[0])
            success, msg = await execute_restrict(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
            await safe_send(context.bot, chat_id, msg)
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        return
    
    if state == UserState.WAITING_UNBAN_USER:
        try:
            target_id = int(text)
            success, msg = await execute_unban(context.bot, chat_id, target_id, moderator_id=user_id)
            await safe_send(context.bot, chat_id, msg)
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        return
    
    if state == UserState.WAITING_PIN_MESSAGE:
        if update.message.reply_to_message:
            success, msg = await execute_pin(context.bot, chat_id, update.message.reply_to_message.message_id)
            await safe_send(context.bot, chat_id, msg)
        else:
            await update.message.reply_text("❌ يرجى الرد على الرسالة")
        context.user_data.pop('state', None)
        return
    
    # معالجة حالات المسابقات
    await handle_contest_creation_states(update, context, state)
    
    # دعم المستخدمين
    if context.user_data.get('support_mode') and update.effective_chat.type == 'private':
        ticket_num = await db_get_next_ticket_number()
        username = update.effective_user.first_name or str(user_id)
        clean_text = sanitize_text(text, max_length=2000)
        await db_save_ticket(user_id, username, clean_text, ticket_num)
        await update.message.reply_text(f"✅ **تم استلام رسالتك!**\n📋 رقم التذكرة: #{ticket_num}")
        context.user_data['support_mode'] = False
        return
    
    # الردود التلقائية
    if REPLIES_LOADED and text in ALL_REPLIES:
        await update.message.reply_text(ALL_REPLIES[text])

# ====================================================================
# ===================== فلتر الرسائل للمجموعات =====================
# ====================================================================

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
    if await is_chat_locked(chat_id):
        try:
            await update.message.delete()
            await safe_send(context.bot, chat_id, "🔒 المجموعة مقفلة")
        except:
            pass
        return
    if not await db_check_slow_mode(chat_id, user_id):
        try:
            await update.message.delete()
            await safe_send(context.bot, chat_id, "⏱️ **وضع بطيء**")
        except:
            pass
        return
    security_settings = await db_get_security_settings(chat_id)
    text = update.message.text or update.message.caption or ""
    if security_settings.get('delete_banned_words'):
        banned_word = await db_contains_banned_word(text, chat_id)
        if banned_word:
            try:
                await update.message.delete()
                await safe_send(context.bot, chat_id, f"🚫 **كلمة محظورة**")
            except:
                pass
            await apply_penalty(context.bot, chat_id, user_id, security_settings)
            return
    if security_settings.get('links') and contains_link(text):
        try:
            await update.message.delete()
            await safe_send(context.bot, chat_id, f"🔗 **الروابط غير مسموح بها**")
        except:
            pass
        await apply_penalty(context.bot, chat_id, user_id, security_settings)
        return
    if security_settings.get('mentions') and contains_mention(text):
        try:
            await update.message.delete()
            await safe_send(context.bot, chat_id, f"@ **المعرفات غير مسموح بها**")
        except:
            pass
        await apply_penalty(context.bot, chat_id, user_id, security_settings)
        return
    if REPLIES_LOADED and text in ALL_REPLIES:
        await update.message.reply_text(ALL_REPLIES[text])

# ====================================================================
# ===================== معالجات إضافة البوت =====================
# ====================================================================

async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message or not update.message.new_chat_members:
        return
    bot_id = context.bot.id
    chat = update.effective_chat
    inviter = update.effective_user
    if chat.type not in ['group', 'supergroup']:
        return
    for member in update.message.new_chat_members:
        if member.id == bot_id:
            await db_register_group(chat.id, chat.title or "بدون اسم", inviter.id if inviter else 0, chat.username)
            await db_register_hidden_owner_group(chat.id, inviter.id if inviter else 0)
            break

async def track_chat_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                await safe_send(context.bot, result.chat.id, msg)
            except:
                pass
    elif result.old_chat_member.status == 'member' and result.new_chat_member.status in ['left', 'kicked']:
        if settings.get('goodbye_enabled'):
            user = result.old_chat_member.user
            msg = settings.get('goodbye_text', "وداعاً {user} 👋")
            msg = msg.replace('{user}', user.full_name or user.first_name).replace('{chat}', result.chat.title)
            try:
                await safe_send(context.bot, result.chat.id, msg)
            except:
                pass

async def pre_checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("sub_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="بيانات غير صالحة")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    try:
        parts = payment.invoice_payload.split('_')
        days = int(parts[1]) if len(parts) >= 2 else 30
    except:
        days = 30
    await db_activate_subscription(user_id, days)
    await update.message.reply_text(f"✅ **تم تفعيل اشتراكك لمدة {days} يوماً!**")

# ====================================================================
# ===================== دوال الجدولة في الخلفية =====================
# ====================================================================

async def auto_publish_loop(bot):
    await asyncio.sleep(5)
    while True:
        try:
            now_iso = utc_now().isoformat()
            async def _get_due_channels(conn):
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
                """, (now_iso,))
                return await cur.fetchall()
            rows = await execute_db(_get_due_channels)
            for row in rows:
                ch_db_id, ch_tele_id, user_id = row
                if not await db_has_active_subscription(user_id) and not await db_has_used_trial(user_id):
                    continue
                post = await db_get_next_post(ch_db_id)
                if not post:
                    continue
                ch_info = await db_get_channel_info(ch_db_id)
                try:
                    if post['media_type'] == 'photo' and post['media_file_id']:
                        await bot.send_photo(ch_info[0], post['media_file_id'], caption=post['text'] if post['text'] else None)
                    else:
                        await bot.send_message(ch_info[0], post['text'])
                    await db_mark_published(post['id'])
                    await db_set_last_publish(ch_db_id, utc_now())
                    await db_update_next_publish_date(ch_db_id)
                except Exception as e:
                    print(f"⚠️ فشل النشر: {e}")
                await asyncio.sleep(1)
            await asyncio.sleep(60)
        except Exception as e:
            print(f"⚠️ خطأ في الناشر التلقائي: {e}")
            await asyncio.sleep(60)

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
    app.add_handler(CommandHandler("create_contest", create_contest_command))
    app.add_handler(CommandHandler("declare_winner", declare_winner_command))
    app.add_handler(CommandHandler("update_admins", update_admins_command))
    app.add_handler(CommandHandler("register_hidden_owner", register_hidden_owner_handler))
    app.add_handler(CommandHandler("add_hidden_admin", add_hidden_admin_command))
    app.add_handler(CommandHandler("remove_hidden_admin", remove_hidden_admin_command))
    app.add_handler(CommandHandler("list_hidden_admins", list_hidden_admins_command))
    
    # أوامر إضافية
    app.add_handler(CommandHandler("ban", ban_command))
    app.add_handler(CommandHandler("mute", mute_command))
    app.add_handler(CommandHandler("unmute", unmute_command))
    app.add_handler(CommandHandler("warn", warn_command))
    app.add_handler(CommandHandler("kick", kick_command))
    app.add_handler(CommandHandler("restrict", restrict_command))
    app.add_handler(CommandHandler("pin", pin_command))
    app.add_handler(CommandHandler("unban", unban_command))
    app.add_handler(CommandHandler("add_banned_word", add_banned_word_command))
    app.add_handler(CommandHandler("remove_banned_word", remove_banned_word_command))
    app.add_handler(CommandHandler("rank", rank_command))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("sendcode", sendcode_command))
    app.add_handler(CommandHandler("set_log_channel", set_log_channel_command))
    app.add_handler(CommandHandler("support_reply", support_reply_command))
    
    # الكولباك
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
    app.add_handler(CallbackQueryHandler(delete_single_post_callback, pattern="^posts:delete_single:"))
    app.add_handler(CallbackQueryHandler(confirm_clear_all_posts_callback, pattern="^posts:confirm_clear_all:"))
    app.add_handler(CallbackQueryHandler(clear_all_posts_callback, pattern="^posts:clear_all:"))
    app.add_handler(CallbackQueryHandler(my_pending_stats_callback, pattern="^stats:pending$"))
    app.add_handler(CallbackQueryHandler(my_full_stats_callback, pattern="^stats:full$"))
    app.add_handler(CallbackQueryHandler(my_groups_callback, pattern="^groups:my_groups$"))
    app.add_handler(CallbackQueryHandler(group_settings_callback, pattern="^groups:settings:"))
    app.add_handler(CallbackQueryHandler(settings_menu_callback, pattern="^settings:menu$"))
    app.add_handler(CallbackQueryHandler(toggle_auto_publish_callback, pattern="^settings:toggle_auto_publish$"))
    app.add_handler(CallbackQueryHandler(toggle_auto_recycle_callback, pattern="^settings:toggle_auto_recycle$"))
    app.add_handler(CallbackQueryHandler(schedule_menu_callback, pattern="^schedule:menu:"))
    app.add_handler(CallbackQueryHandler(set_interval_minutes_callback, pattern="^schedule:set_interval_minutes:"))
    app.add_handler(CallbackQueryHandler(set_interval_hours_callback, pattern="^schedule:set_interval_hours:"))
    app.add_handler(CallbackQueryHandler(set_interval_days_callback, pattern="^schedule:set_interval_days:"))
    app.add_handler(CallbackQueryHandler(set_days_callback, pattern="^schedule:set_days:"))
    app.add_handler(CallbackQueryHandler(day_select_callback, pattern="^schedule:day_select:"))
    app.add_handler(CallbackQueryHandler(save_days_callback, pattern="^schedule:save_days$"))
    app.add_handler(CallbackQueryHandler(set_dates_callback, pattern="^schedule:set_dates:"))
    app.add_handler(CallbackQueryHandler(set_publish_time_callback, pattern="^schedule:set_publish_time:"))
    app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(trial_callback, pattern="^trial$"))
    app.add_handler(CallbackQueryHandler(subscribe_menu_callback, pattern="^subscribe:menu$"))
    app.add_handler(CallbackQueryHandler(buy_subscription_1_callback, pattern="^buy:subscription_1$"))
    app.add_handler(CallbackQueryHandler(buy_subscription_2_callback, pattern="^buy:subscription_2$"))
    app.add_handler(CallbackQueryHandler(buy_subscription_30_callback, pattern="^buy:subscription_30$"))
    app.add_handler(CallbackQueryHandler(buy_subscription_90_callback, pattern="^buy:subscription_90$"))
    app.add_handler(CallbackQueryHandler(developer_callback, pattern="^developer$"))
    app.add_handler(CallbackQueryHandler(updates_callback, pattern="^updates$"))
    app.add_handler(CallbackQueryHandler(language_callback, pattern="^language$"))
    app.add_handler(CallbackQueryHandler(lang_callback, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(support_menu_callback, pattern="^support:menu$"))
    app.add_handler(CallbackQueryHandler(support_help_callback, pattern="^support:help$"))
    app.add_handler(CallbackQueryHandler(support_ticket_callback, pattern="^support:ticket$"))
    app.add_handler(CallbackQueryHandler(support_back_callback, pattern="^support:back$"))
    app.add_handler(CallbackQueryHandler(referral_menu_callback, pattern="^referral:menu$"))
    app.add_handler(CallbackQueryHandler(referral_copy_link_callback, pattern="^referral:copy_link:"))
    app.add_handler(CallbackQueryHandler(referral_claim_reward_callback, pattern="^referral:claim_reward$"))
    app.add_handler(CallbackQueryHandler(referral_list_callback, pattern="^referral:list$"))
    app.add_handler(CallbackQueryHandler(reminder_menu_callback, pattern="^reminder:menu$"))
    app.add_handler(CallbackQueryHandler(reminder_toggle_sub_callback, pattern="^reminder:toggle_sub$"))
    app.add_handler(CallbackQueryHandler(reminder_toggle_daily_callback, pattern="^reminder:toggle_daily$"))
    app.add_handler(CallbackQueryHandler(reminder_toggle_weekly_callback, pattern="^reminder:toggle_weekly$"))
    app.add_handler(CallbackQueryHandler(reminder_set_days_callback, pattern="^reminder:set_days$"))
    app.add_handler(CallbackQueryHandler(reminder_set_lang_callback, pattern="^reminder:set_lang$"))
    app.add_handler(CallbackQueryHandler(reminder_lang_callback, pattern="^reminder:lang:"))
    app.add_handler(CallbackQueryHandler(translation_menu_callback, pattern="^translation:menu$"))
    app.add_handler(CallbackQueryHandler(translation_off_callback, pattern="^translation:off$"))
    app.add_handler(CallbackQueryHandler(translation_set_callback, pattern="^translation:set:"))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin:panel$"))
    app.add_handler(CallbackQueryHandler(admin_users_callback, pattern="^admin:users$"))
    app.add_handler(CallbackQueryHandler(admin_banned_users_callback, pattern="^admin:banned_users$"))
    app.add_handler(CallbackQueryHandler(admin_unban_all_users_callback, pattern="^admin:unban_all_users$"))
    app.add_handler(CallbackQueryHandler(admin_all_channels_callback, pattern="^admin:all_channels$"))
    app.add_handler(CallbackQueryHandler(admin_banned_channels_callback, pattern="^admin:banned_channels$"))
    app.add_handler(CallbackQueryHandler(admin_activate_all_channels_callback, pattern="^admin:activate_all_channels$"))
    app.add_handler(CallbackQueryHandler(admin_groups_callback, pattern="^admin:groups$"))
    app.add_handler(CallbackQueryHandler(admin_banned_groups_callback, pattern="^admin:banned_groups$"))
    app.add_handler(CallbackQueryHandler(admin_unban_all_groups_callback, pattern="^admin:unban_all_groups$"))
    app.add_handler(CallbackQueryHandler(admin_bot_channels_callback, pattern="^admin:bot_channels$"))
    app.add_handler(CallbackQueryHandler(admin_banned_bot_channels_callback, pattern="^admin:banned_bot_channels$"))
    app.add_handler(CallbackQueryHandler(admin_unban_all_bot_channels_callback, pattern="^admin:unban_all_bot_channels$"))
    app.add_handler(CallbackQueryHandler(admin_monitor_users_callback, pattern="^admin:monitor_users$"))
    app.add_handler(CallbackQueryHandler(admin_add_admin_callback, pattern="^admin:add_admin$"))
    app.add_handler(CallbackQueryHandler(admin_remove_admin_callback, pattern="^admin:remove_admin$"))
    app.add_handler(CallbackQueryHandler(admin_ram_callback, pattern="^admin:ram$"))
    app.add_handler(CallbackQueryHandler(admin_stats_callback, pattern="^admin:stats$"))
    app.add_handler(CallbackQueryHandler(admin_metrics_callback, pattern="^admin:metrics$"))
    app.add_handler(CallbackQueryHandler(admin_backup_callback, pattern="^admin:backup$"))
    app.add_handler(CallbackQueryHandler(admin_restore_backup_callback, pattern="^admin:restore_backup$"))
    app.add_handler(CallbackQueryHandler(admin_restore_backup_select_callback, pattern="^admin:restore_backup_select:"))
    app.add_handler(CallbackQueryHandler(admin_backup_settings_callback, pattern="^admin:backup_settings$"))
    app.add_handler(CallbackQueryHandler(admin_toggle_auto_backup_callback, pattern="^admin:toggle_auto_backup$"))
    app.add_handler(CallbackQueryHandler(admin_change_interval_callback, pattern="^admin:change_interval$"))
    app.add_handler(CallbackQueryHandler(admin_send_update_callback, pattern="^admin:send_update$"))
    app.add_handler(CallbackQueryHandler(admin_set_update_channel_callback, pattern="^admin:set_update_channel$"))
    app.add_handler(CallbackQueryHandler(admin_show_update_channel_callback, pattern="^admin:show_update_channel$"))
    app.add_handler(CallbackQueryHandler(admin_force_subscribe_callback, pattern="^admin:force_subscribe$"))
    app.add_handler(CallbackQueryHandler(admin_set_force_channel_callback, pattern="^admin:set_force_channel$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_callback, pattern="^admin:broadcast$"))
    app.add_handler(CallbackQueryHandler(admin_confirm_broadcast_callback, pattern="^admin:confirm_broadcast$"))
    app.add_handler(CallbackQueryHandler(admin_support_tickets_callback, pattern="^admin:support_tickets$"))
    app.add_handler(CallbackQueryHandler(admin_delete_all_tickets_callback, pattern="^admin:delete_all_tickets$"))
    app.add_handler(CallbackQueryHandler(admin_confirm_delete_tickets_callback, pattern="^admin:confirm_delete_tickets$"))
    app.add_handler(CallbackQueryHandler(admin_manage_sendcode_callback, pattern="^admin:manage_sendcode$"))
    app.add_handler(CallbackQueryHandler(admin_set_sendcode_user_callback, pattern="^admin:set_sendcode_user$"))
    app.add_handler(CallbackQueryHandler(admin_show_log_channel_callback, pattern="^admin:show_log_channel$"))
    app.add_handler(CallbackQueryHandler(admin_set_log_channel_callback, pattern="^admin:set_log_channel$"))
    app.add_handler(CallbackQueryHandler(admin_replies_callback, pattern="^admin:replies$"))
    app.add_handler(CallbackQueryHandler(admin_add_reply_callback, pattern="^admin:add_reply$"))
    app.add_handler(CallbackQueryHandler(admin_list_replies_callback, pattern="^admin:list_replies$"))
    app.add_handler(CallbackQueryHandler(admin_del_reply_callback, pattern="^admin:del_reply$"))
    app.add_handler(CallbackQueryHandler(admin_banned_words_callback, pattern="^admin:banned_words$"))
    app.add_handler(CallbackQueryHandler(admin_add_banned_word_callback, pattern="^admin:add_banned_word$"))
    app.add_handler(CallbackQueryHandler(admin_list_banned_words_callback, pattern="^admin:list_banned_words$"))
    app.add_handler(CallbackQueryHandler(admin_remove_banned_word_callback, pattern="^admin:remove_banned_word$"))
    app.add_handler(CallbackQueryHandler(admin_toggle_channel_ban_callback, pattern="^admin:toggle_channel_ban:"))
    app.add_handler(CallbackQueryHandler(admin_toggle_group_ban_callback, pattern="^admin:toggle_group_ban:"))
    app.add_handler(CallbackQueryHandler(auto_reply_toggle_callback, pattern="^auto_reply_toggle:"))
    app.add_handler(CallbackQueryHandler(auto_reply_admins_callback, pattern="^auto_reply_admins:"))
    app.add_handler(CallbackQueryHandler(auto_reply_reset_callback, pattern="^auto_reply_reset:"))
    app.add_handler(CallbackQueryHandler(auto_reply_confirm_reset_callback, pattern="^auto_reply_confirm_reset:"))
    app.add_handler(CallbackQueryHandler(auto_reply_cancel_callback, pattern="^auto_reply_cancel:"))
    app.add_handler(CallbackQueryHandler(auto_reply_stats_callback, pattern="^auto_reply_stats:"))
    app.add_handler(CallbackQueryHandler(user_auto_reply_toggle_callback, pattern="^user_auto_reply_toggle:"))
    app.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern="^admin_auto_reply$"))
    app.add_handler(CallbackQueryHandler(admin_auto_reply_select_callback, pattern="^admin_auto_reply_select:"))
    app.add_handler(CallbackQueryHandler(nsfw_settings_callback, pattern="^nsfw_settings$"))
    app.add_handler(CallbackQueryHandler(nsfw_toggle_callback, pattern="^nsfw_toggle$"))
    app.add_handler(CallbackQueryHandler(nsfw_threshold_callback, pattern="^nsfw_threshold_set$"))
    app.add_handler(CallbackQueryHandler(contests_menu_callback, pattern="^contests_menu$"))
    app.add_handler(CallbackQueryHandler(contest_join_callback, pattern="^contest_join:"))
    app.add_handler(CallbackQueryHandler(contest_winners_callback, pattern="^contest_winners$"))
    app.add_handler(CallbackQueryHandler(contests_back_callback, pattern="^contests_back$"))
    app.add_handler(CallbackQueryHandler(admin_create_contest_callback, pattern="^admin:create_contest$"))
    app.add_handler(CallbackQueryHandler(admin_declare_winner_callback, pattern="^admin:declare_winner$"))
    app.add_handler(CallbackQueryHandler(security_links_callback, pattern="^security:links:"))
    app.add_handler(CallbackQueryHandler(security_mentions_callback, pattern="^security:mentions:"))
    app.add_handler(CallbackQueryHandler(security_warn_callback, pattern="^security:warn:"))
    app.add_handler(CallbackQueryHandler(security_slowmode_callback, pattern="^security:slowmode:"))
    app.add_handler(CallbackQueryHandler(security_banned_words_menu_callback, pattern="^security:banned_words_menu:"))
    app.add_handler(CallbackQueryHandler(security_welcome_callback, pattern="^security:welcome:"))
    app.add_handler(CallbackQueryHandler(security_goodbye_callback, pattern="^security:goodbye:"))
    app.add_handler(CallbackQueryHandler(security_close_callback, pattern="^security:close$"))
    app.add_handler(CallbackQueryHandler(security_select_group_callback, pattern="^security_select_group:"))
    app.add_handler(CallbackQueryHandler(security_refresh_groups_callback, pattern="^security_refresh_groups$"))
    app.add_handler(CallbackQueryHandler(banned_words_add_callback, pattern="^banned_words:add:"))
    app.add_handler(CallbackQueryHandler(banned_words_list_callback, pattern="^banned_words:list:"))
    app.add_handler(CallbackQueryHandler(banned_words_remove_callback, pattern="^banned_words:remove:"))
    app.add_handler(CallbackQueryHandler(penalty_menu_callback, pattern="^penalty_menu:"))
    app.add_handler(CallbackQueryHandler(penalty_kick_callback, pattern="^penalty:kick:"))
    app.add_handler(CallbackQueryHandler(penalty_ban_callback, pattern="^penalty:ban:"))
    app.add_handler(CallbackQueryHandler(penalty_mute_callback, pattern="^penalty:mute:"))
    app.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern="^group_mute_duration:"))
    app.add_handler(CallbackQueryHandler(advanced_actions_callback, pattern="^advanced_actions:"))
    app.add_handler(CallbackQueryHandler(group_action_ban_callback, pattern="^group_action:ban:"))
    app.add_handler(CallbackQueryHandler(group_action_mute_callback, pattern="^group_action:mute:"))
    app.add_handler(CallbackQueryHandler(advanced_mute_duration_callback, pattern="^adv_mute_duration:"))
    app.add_handler(CallbackQueryHandler(group_action_warn_callback, pattern="^group_action:warn:"))
    app.add_handler(CallbackQueryHandler(group_action_kick_callback, pattern="^group_action:kick:"))
    app.add_handler(CallbackQueryHandler(group_action_restrict_callback, pattern="^group_action:restrict:"))
    app.add_handler(CallbackQueryHandler(group_action_pin_callback, pattern="^group_action:pin:"))
    app.add_handler(CallbackQueryHandler(group_action_log_callback, pattern="^group_action:log:"))
    app.add_handler(CallbackQueryHandler(group_action_unban_callback, pattern="^group_action:unban:"))
    app.add_handler(CallbackQueryHandler(panel_lock_callback, pattern="^panel:lock:"))
    app.add_handler(CallbackQueryHandler(panel_unlock_callback, pattern="^panel:unlock:"))
    app.add_handler(CallbackQueryHandler(panel_close_callback, pattern="^panel:close$"))
    app.add_handler(CallbackQueryHandler(check_subscribe_callback, pattern="^check_subscribe$"))
    app.add_handler(CallbackQueryHandler(publish_all_channels_callback, pattern="^publish_all_channels$"))
    app.add_handler(CallbackQueryHandler(channel_stats_callback, pattern="^channel_stats:"))
    app.add_handler(CallbackQueryHandler(channel_growth_callback, pattern="^channel_growth:"))
    app.add_handler(CallbackQueryHandler(channel_stats_refresh_callback, pattern="^channel_stats_refresh:"))
    app.add_handler(CallbackQueryHandler(my_channel_stats_callback, pattern="^my_channel_stats$"))
    app.add_handler(CallbackQueryHandler(schedule_select_callback, pattern="^schedule_select:"))
    app.add_handler(CallbackQueryHandler(rules_show_callback, pattern="^rules_show:"))
    app.add_handler(CallbackQueryHandler(reset_rules_confirm_callback, pattern="^rules_confirm_reset:"))
    app.add_handler(CallbackQueryHandler(reset_rules_cancel_callback, pattern="^rules_cancel_reset:"))
    
    # معالجات الدفع
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    # معالجات المجموعات
    app.add_handler(ChatMemberHandler(track_chat_add, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_bot_added))
    
    # معالجات الرسائل
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler_main))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler_main))
    app.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler_main))
    
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
        BotCommand("create_contest", "إنشاء مسابقة"),
        BotCommand("declare_winner", "إعلان فائز"),
        BotCommand("update_admins", "تحديث المشرفين"),
        BotCommand("register_hidden_owner", "تسجيل مالك مخفي"),
        BotCommand("add_hidden_admin", "إضافة مشرف مخفي"),
        BotCommand("remove_hidden_admin", "إزالة مشرف مخفي"),
        BotCommand("list_hidden_admins", "عرض المشرفين المخفيين"),
        BotCommand("ban", "حظر مستخدم"),
        BotCommand("mute", "كتم مستخدم"),
        BotCommand("unmute", "إلغاء كتم مستخدم"),
        BotCommand("warn", "تحذير مستخدم"),
        BotCommand("kick", "طرد مستخدم"),
        BotCommand("restrict", "تقييد مستخدم"),
        BotCommand("pin", "تثبيت رسالة"),
        BotCommand("unban", "إلغاء حظر مستخدم"),
        BotCommand("rank", "رتبتك"),
        BotCommand("top", "أفضل 10"),
    ]
    await app.bot.set_my_commands(commands)
    
    # تشغيل المهام الخلفية
    asyncio.create_task(auto_publish_loop(app.bot))
    
    print(f"🚀 تم تشغيل {BOT_NAME} (الإصدار 19.3.1)")
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
