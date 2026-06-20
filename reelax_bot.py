#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - بوت متكامل لإدارة القنوات والمجموعات
الإصدار: 19.0.3 - النسخة العالمية المحسنة (المصححة بالكامل)
المطور: @RelaxMgr

الميزات:
- إدارة القنوات والمجموعات
- نشر تلقائي مع جدولة متقدمة
- إعادة تدوير المنشورات
- إحصائيات متقدمة مع رسوم بيانية
- نظام أمان متكامل
- نظام إحالات ومكافآت
- ترجمة تلقائية للمنشورات
- نسخ احتياطي تلقائي (محلي وسحابي)
- واجهة ويب مع لوحة تحكم
- دعم كامل للمالك المخفي
- نظام مستويات ونقاط
- تذاكر الدعم
- إشعارات وتذكيرات
- دعم جميع أنواع الميديا
"""

import sys
import os
from pathlib import Path
import secrets
import string

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
TEMP_PATH = get_temp_path()

BACKUP_DIR.mkdir(parents=True, exist_ok=True)
DATA_PATH.mkdir(parents=True, exist_ok=True)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
TEMP_PATH.mkdir(parents=True, exist_ok=True)

# ===================== كشف البيئة =====================
def detect_environment() -> dict:
    import platform
    env = {
        'platform': platform.system(),
        'is_termux': 'com.termux' in sys.executable,
        'is_pythonanywhere': 'pythonanywhere' in sys.executable,
        'is_replit': 'REPLIT' in os.environ,
        'is_heroku': 'HEROKU' in os.environ,
        'is_docker': os.path.exists('/.dockerenv'),
        'is_windows': platform.system() == 'Windows',
        'is_mac': platform.system() == 'Darwin',
        'is_linux': platform.system() == 'Linux',
        'is_production': os.getenv('ENVIRONMENT', 'development') == 'production',
        'is_railway': 'RAILWAY_ENVIRONMENT' in os.environ,
        'is_render': 'RENDER' in os.environ,
    }
    if env['is_termux']:
        env['max_connections'] = 3
        env['db_timeout'] = 45.0
    elif env['is_pythonanywhere']:
        env['max_connections'] = 2
        env['db_timeout'] = 60.0
    elif env['is_replit']:
        env['max_connections'] = 2
        env['db_timeout'] = 30.0
    elif env['is_heroku'] or env['is_railway'] or env['is_render']:
        env['max_connections'] = 3
        env['db_timeout'] = 60.0
    else:
        env['max_connections'] = 5
        env['db_timeout'] = 120.0
    return env

ENV = detect_environment()
MAX_CONNECTIONS = ENV['max_connections']
DB_TIMEOUT = ENV['db_timeout']

print(f"🌍 البيئة المكتشفة: {ENV['platform']}")
print(f"📌 الإعدادات: {MAX_CONNECTIONS} اتصالات، {DB_TIMEOUT}s مهلة")

# ===================== التثبيت التلقائي للمكتبات =====================
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

# تثبيت المكتبات الأساسية
ensure_package("python-dotenv", "dotenv")
ensure_package("cachetools")
ensure_package("psutil")
ensure_package("pyotp")
ensure_package("nest-asyncio", "nest_asyncio")
ensure_package("aiosqlite")
ensure_package("cryptography")
ensure_package("deep-translator", "deep_translator")
ensure_package("bleach")
ensure_package("qrcode")
ensure_package("Pillow", "PIL")
ensure_package("plotly")
ensure_package("google-auth", "google.auth")
ensure_package("google-auth-oauthlib", "google_auth_oauthlib")
ensure_package("google-api-python-client", "googleapiclient")
ensure_package("aiohttp")
ensure_package("aiofiles")
ensure_package("httpx")

# ===================== استيراد المكتبات =====================
import nest_asyncio
nest_asyncio.apply()

import asyncio
import aiosqlite
import random
import re
import shutil
import json
import logging
import time as time_module
import hashlib
import traceback
import bleach
import base64
import tempfile
import gzip
import io
import secrets
import string
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
from typing import Optional, Dict, List, Tuple, Any, Union, Callable
from functools import lru_cache, wraps
from dataclasses import dataclass, asdict
from enum import Enum
import weakref
import platform
import socket
import subprocess

try:
    from cachetools import TTLCache, LRUCache
    CACHETOOLS_AVAILABLE = True
except ImportError:
    CACHETOOLS_AVAILABLE = False
    print("⚠️ مكتبة cachetools غير مثبتة، سيتم استخدام التخزين المؤقت الأساسي")

from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, BotCommand, LabeledPrice, ChatPermissions
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler, ChatMemberHandler
from telegram.error import TimedOut, NetworkError, BadRequest, Forbidden
from telegram.request import HTTPXRequest
import httpx
from dotenv import load_dotenv
from deep_translator import GoogleTranslator
from cryptography.fernet import Fernet
from aiohttp import web, WSMsgType
import aiohttp
from aiohttp import web, WSMsgType
import aiofiles
import qrcode
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import plotly.graph_objects as go
import plotly.utils
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    PYOTP_AVAILABLE = False
    print("⚠️ مكتبة pyotp غير مثبتة، تم تعطيل المصادقة الثنائية")

# ===================== تحميل ملفات البيئة =====================
def load_env_files():
    from dotenv import load_dotenv
    env_files = [
        ".env",
        ".env.local",
        str(BASE_PATH / ".env"),
        str(BASE_PATH / "config" / ".env"),
        str(Path.home() / ".bot" / ".env"),
    ]
    for env_file in env_files:
        if os.path.exists(env_file):
            load_dotenv(env_file)
            return True
    return False

load_env_files()

def get_env_or_default(key: str, default: any, env_type: type = str) -> any:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        if env_type == bool:
            return value.lower() in ['true', '1', 'yes', 'on']
        elif env_type == int:
            return int(value)
        elif env_type == float:
            return float(value)
        return env_type(value)
    except:
        return default

# ===================== الثوابت =====================
TOKEN = get_env_or_default("BOT_TOKEN", None, str)
if not TOKEN:
    raise ValueError("❌ لم يتم العثور على BOT_TOKEN في ملفات البيئة")

MAIN_ADMIN_ID = get_env_or_default("MAIN_ADMIN_ID", 0, int)
if MAIN_ADMIN_ID == 0:
    raise ValueError("❌ MAIN_ADMIN_ID غير محدد في ملفات البيئة")

BOT_NAME = get_env_or_default("BOT_NAME", "ريلاكس مانيجر", str)
BOT_USERNAME = get_env_or_default("BOT_USERNAME", "Reelaaaxbot", str)
USE_PROXY = get_env_or_default("USE_PROXY", False, bool)
PROXY_URL = get_env_or_default("PROXY_URL", "http://127.0.0.1:10809", str)
ENABLE_2FA = get_env_or_default("ENABLE_2FA", False, bool)
ADMIN_2FA_SECRET = get_env_or_default("ADMIN_2FA_SECRET", "", str)
DB_ENCRYPTION = get_env_or_default("DB_ENCRYPTION", True, bool)
MAX_BACKUPS = get_env_or_default("MAX_BACKUPS", 10, int)
SECURITY_LOG_LEVEL = get_env_or_default("SECURITY_LOG_LEVEL", "CRITICAL", str)

GOOGLE_DRIVE_FOLDER_ID = get_env_or_default("GOOGLE_DRIVE_FOLDER_ID", "", str)
CLOUD_BACKUP_ENABLED = get_env_or_default("CLOUD_BACKUP_ENABLED", False, bool)
GOOGLE_CREDENTIALS_FILE = get_env_or_default("GOOGLE_CREDENTIALS_FILE", "credentials.json", str)
TOKEN_FILE = get_env_or_default("TOKEN_FILE", "token.json", str)

WEB_PORT = get_env_or_default("WEB_PORT", 10000, int)  # تغيير المنفذ الافتراضي إلى 10000 لـ Render
WEB_HOST = get_env_or_default("WEB_HOST", "0.0.0.0", str)
WEB_PASSWORD = get_env_or_default("WEB_PASSWORD", "", str)
if not WEB_PASSWORD and os.getenv('ENVIRONMENT', 'development') == 'production':
    print("⚠️ تحذير أمني: WEB_PASSWORD غير معيّنة في بيئة الإنتاج! سيتم طلب كلمة مرور عشوائية.")
    WEB_PASSWORD = secrets.token_urlsafe(16)
    print(f"🔑 كلمة المرور المؤقتة: {WEB_PASSWORD}")
WEB_USERNAME = get_env_or_default("WEB_USERNAME", "admin", str)
WEB_SECRET_KEY = get_env_or_default("WEB_SECRET_KEY", secrets.token_urlsafe(32), str)

BATTERY_SAVER_MODE = get_env_or_default("BATTERY_SAVER_MODE", False, bool)

DEFAULT_PUBLISH_INTERVAL_SECONDS = 720
CLEANUP_SLEEP = 3600

if BATTERY_SAVER_MODE:
    POLL_INTERVAL = 10.0
    SCHEDULED_POSTS_SLEEP = 120
    REMINDERS_SLEEP = 7200
    AUTO_BACKUP_SLEEP = 48 * 60 * 60
else:
    POLL_INTERVAL = 1.0
    SCHEDULED_POSTS_SLEEP = 10
    REMINDERS_SLEEP = 3600
    AUTO_BACKUP_SLEEP = 24 * 60 * 60

# ===================== التشفير =====================
from cryptography.fernet import Fernet

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key()
else:
    ENCRYPTION_KEY = ENCRYPTION_KEY.encode()
cipher_suite = Fernet(ENCRYPTION_KEY)

BACKUP_KEY = hashlib.sha256(TOKEN.encode()).digest()
BACKUP_CIPHER = Fernet(base64.urlsafe_b64encode(BACKUP_KEY[:32]))

# ===================== متغيرات تشغيل الخلفية =====================
_background_tasks_started = False

# ===================== تحسينات التخزين المؤقت =====================
if CACHETOOLS_AVAILABLE:
    _admin_cache = TTLCache(maxsize=1000, ttl=300)
    _security_cache = TTLCache(maxsize=500, ttl=60)
    _translation_cache = LRUCache(maxsize=200)
else:
    _admin_cache = {}
    _security_cache = {}
    _translation_cache = {}
    _ADMIN_CACHE_TTL = 60
    _SECURITY_CACHE_TTL = 30
    _TRANSLATION_CACHE_SIZE = 500

_translation_cache_lock = asyncio.Lock()
user_translation_settings_cache = {}
_user_translation_cache_lock = asyncio.Lock()
user_language = {}
_user_language_lock = asyncio.Lock()

# ===================== التحقق من التشغيل الواحد =====================
def check_single_instance():
    try:
        sock_path = TEMP_PATH / "bot.sock"
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(sock_path))
            return sock
        except socket.error:
            print("❌ البوت يعمل بالفعل!")
            sys.exit(1)
    except Exception as e:
        print(f"⚠️ لا يمكن التحقق من التشغيل الواحد: {e}")
        return None

lock_socket = check_single_instance()

# ===================== دوال التنظيف والتهرب =====================
def clean_text_for_telegram(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\u200b\u200c\u200d\u2060\uFEFF\u202a\u202b\u202c\u202d\u202e]', '', text)
    text = text.replace('\ufeff', '').replace('\ufffc', '')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def escape_markdown_v2(text: str) -> str:
    if not text:
        return ""
    text = clean_text_for_telegram(text)
    special_chars = r'_*[]()~`>#+\-=|{}.!'
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    text = text.replace('!', r'\!')
    text = re.sub(r'(\d+)\.', r'\1\.', text)
    return text

async def safe_send_markdown(bot, chat_id: int, text: str, reply_markup=None, **kwargs):
    if not text:
        return None
    clean_text = clean_text_for_telegram(text)
    formats = [
        ("MarkdownV2", lambda t: escape_markdown_v2(t)),
        ("HTML", lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")),
        (None, lambda t: re.sub(r'[*_`\[\]()~>#+\-=|{}.!\\]', '', t))
    ]
    last_error = None
    for parse_mode, formatter in formats:
        try:
            formatted_text = formatter(clean_text)
            if len(formatted_text) > 4096:
                formatted_text = formatted_text[:4093] + "..."
            return await bot.send_message(
                chat_id=chat_id,
                text=formatted_text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                **kwargs
            )
        except BadRequest as e:
            last_error = e
            if "can't parse entities" in str(e).lower():
                continue
            raise
        except Exception as e:
            last_error = e
            continue
    logger.warning(f"فشل إرسال الرسالة: {last_error}")
    plain_text = re.sub(r'[*_`\[\]()~>#+\-=|{}.!\\]', '', clean_text)
    if len(plain_text) > 4096:
        plain_text = plain_text[:4093] + "..."
    return await bot.send_message(chat_id=chat_id, text=plain_text, reply_markup=reply_markup, **kwargs)

async def safe_edit_markdown(query, text: str, reply_markup=None, **kwargs):
    if not text:
        return None
    if query is None:
        return None
    clean_text = clean_text_for_telegram(text)
    formats = [
        ("MarkdownV2", lambda t: escape_markdown_v2(t)),
        ("HTML", lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")),
        (None, lambda t: re.sub(r'[*_`\[\]()~>#+\-=|{}.!\\]', '', t))
    ]
    last_error = None
    for parse_mode, formatter in formats:
        try:
            formatted_text = formatter(clean_text)
            if len(formatted_text) > 4096:
                formatted_text = formatted_text[:4093] + "..."
            return await query.edit_message_text(
                text=formatted_text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                **kwargs
            )
        except BadRequest as e:
            last_error = e
            if "can't parse entities" in str(e).lower():
                continue
            if "Message is not modified" in str(e):
                return None
            raise
        except Exception as e:
            last_error = e
            continue
    logger.warning(f"فشل تعديل الرسالة: {last_error}")
    plain_text = re.sub(r'[*_`\[\]()~>#+\-=|{}.!\\]', '', clean_text)
    if len(plain_text) > 4096:
        plain_text = plain_text[:4093] + "..."
    try:
        return await query.edit_message_text(text=plain_text, reply_markup=reply_markup, **kwargs)
    except Exception as e:
        if "Message is not modified" in str(e):
            return None
        raise

async def safe_send_error(bot, chat_id: int, text: str):
    try:
        return await safe_send_markdown(bot, chat_id, text)
    except Exception as e:
        logger.warning(f"فشل إرسال تقرير الخطأ: {e}")
        plain_text = re.sub(r'[*_`\[\]()~>#+\-=|{}.!\\]', '', text)
        plain_text = plain_text.replace("\\", "")
        try:
            return await bot.send_message(chat_id=chat_id, text=plain_text[:4000])
        except Exception as e2:
            return await bot.send_message(chat_id=chat_id, text=text[:4000], parse_mode=None)

async def safe_send_long_message(bot, chat_id: int, text: str, reply_markup=None, max_length: int = 4000):
    if len(text) <= max_length:
        return await safe_send_markdown(bot, chat_id, text, reply_markup)
    parts = []
    current_part = ""
    for line in text.split('\n'):
        if len(current_part) + len(line) + 1 > max_length:
            parts.append(current_part)
            current_part = line
        else:
            current_part += "\n" + line if current_part else line
    if current_part:
        parts.append(current_part)
    first = True
    for part in parts:
        if first and reply_markup:
            await safe_send_markdown(bot, chat_id, part, reply_markup)
            first = False
        else:
            await safe_send_markdown(bot, chat_id, part)
        await asyncio.sleep(0.5)
    return None

async def safe_query_answer(query, text: str = None, show_alert: bool = False):
    if query is None:
        return
    try:
        await query.answer(text=text, show_alert=show_alert)
    except Exception as e:
        logger.debug(f"فشل الرد على الاستعلام: {e}")

# ===================== دوال الوقت =====================
def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def mecca_now():
    return utc_now() + timedelta(hours=3)

def utc_now_iso():
    return utc_now().isoformat()

def mecca_now_iso():
    return mecca_now().isoformat()

def to_naive(dt):
    if dt is None:
        return None
    if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt

def mecca_to_utc(mecca_dt):
    if hasattr(mecca_dt, 'tzinfo') and mecca_dt.tzinfo is not None:
        mecca_dt = mecca_dt.replace(tzinfo=None)
    return mecca_dt - timedelta(hours=3)

def utc_to_mecca(utc_dt):
    if hasattr(utc_dt, 'tzinfo') and utc_dt.tzinfo is not None:
        utc_dt = utc_dt.replace(tzinfo=None)
    return utc_dt + timedelta(hours=3)

# ===================== نظام التسجيل المحسن =====================
class CustomFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        if TOKEN and TOKEN in msg:
            msg = msg.replace(TOKEN, "[TOKEN_HIDDEN]")
        if ENCRYPTION_KEY and isinstance(ENCRYPTION_KEY, bytes):
            try:
                key_str = ENCRYPTION_KEY.decode()
                if key_str in msg:
                    msg = msg.replace(key_str, "[ENCRYPTION_KEY_HIDDEN]")
            except:
                pass
        if BACKUP_KEY and BACKUP_KEY.hex() in msg:
            msg = msg.replace(BACKUP_KEY.hex(), "[BACKUP_KEY_HIDDEN]")
        return msg

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_PATH, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
for handler in logger.handlers:
    handler.setFormatter(CustomFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")))

# ===================== نظام الأمان والتدقيق =====================
class SecurityAudit:
    async def log(self, event_type: str, user_id: int, details: dict, severity: str = "INFO"):
        log_entry = {
            "event": event_type,
            "user_id": user_id,
            "details": details,
            "severity": severity,
            "timestamp": mecca_now_iso()
        }
        logger.warning(f"[SECURITY] {event_type} | User: {user_id} | {details} | Severity: {severity}")
        try:
            with open(SECURITY_LOG, "a", encoding='utf-8') as f:
                f.write(json.dumps(log_entry) + "\n")
        except:
            pass
        return True

security_audit = SecurityAudit()

def escape_html(text: str) -> str:
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ===================== دوال الاتصال الآمن =====================
async def safe_api_call(func, *args, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except (NetworkError, TimeoutError, httpx.ConnectError, httpx.ReadError, TimedOut) as e:
            if attempt == max_retries - 1:
                raise
            wait_time = (attempt + 1) * 2
            logger.warning(f"⚠️ فشل الاتصال، إعادة محاولة {attempt + 1}/{max_retries} بعد {wait_time} ثانية: {e}")
            await asyncio.sleep(wait_time)
    return None

def get_ram_usage():
    try:
        import psutil
        mem = psutil.virtual_memory()
        return {
            'total': round(mem.total / (1024**3), 1),
            'used': round(mem.used / (1024**3), 1),
            'percent': mem.percent
        }
    except:
        try:
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
            mem_total = 0
            mem_available = 0
            for line in lines:
                if 'MemTotal:' in line:
                    mem_total = int(line.split()[1]) / (1024 * 1024)
                if 'MemAvailable:' in line:
                    mem_available = int(line.split()[1]) / (1024 * 1024)
            if mem_total > 0:
                used = mem_total - mem_available
                percent = (used / mem_total) * 100
                return {'total': round(mem_total, 1), 'used': round(used, 1), 'percent': round(percent, 1)}
        except:
            pass
        return {'total': 0, 'used': 0, 'percent': 0}

def parse_days_of_week_safe(days_str):
    if not days_str: 
        return []
    try: 
        return json.loads(days_str)
    except: 
        return []

def parse_dates_safe(dates_str):
    if not dates_str: 
        return []
    try: 
        return json.loads(dates_str)
    except: 
        return []

def contains_link(text):
    patterns = [
        r'https?://\S+',
        r'www\.\S+',
        r't\.me/\S+',
        r'telegram\.me/\S+',
        r'\b[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)+\S*'
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)

def contains_mention(text):
    return bool(re.search(r'@\w+', text))

def sanitize_text(text: str, max_length: int = 4096) -> str:
    if not text:
        return ""
    text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.DOTALL)
    text = re.sub(r'javascript:', '', text, flags=re.IGNORECASE)
    return text[:max_length]

# ===================== نظام جمع المقاييس =====================
class MetricsCollector:
    def __init__(self):
        self.commands_count = defaultdict(int)
        self.errors_count = defaultdict(int)
        self.response_times = []
        self.start_time = time_module.time()
    
    def record_command(self, command: str):
        self.commands_count[command] += 1
    
    def record_error(self, error_type: str):
        self.errors_count[error_type] += 1
    
    def record_response_time(self, seconds: float):
        self.response_times.append(seconds)
        if len(self.response_times) > 1000:
            self.response_times.pop(0)
    
    def get_stats(self) -> dict:
        avg_response = sum(self.response_times) / len(self.response_times) if self.response_times else 0
        return {
            'uptime': time_module.time() - self.start_time,
            'total_commands': sum(self.commands_count.values()),
            'commands': dict(self.commands_count),
            'errors': dict(self.errors_count),
            'avg_response_time': avg_response,
        }
    
    def get_ram_usage(self):
        return get_ram_usage()

metrics = MetricsCollector()

# ===================== نظام الترجمة المحسن =====================
class SmartTranslator:
    def __init__(self):
        self.cache = {}
        self.pending = defaultdict(list)
        self.last_cleanup = time_module.time()
        self.lock = asyncio.Lock()
    
    async def translate(self, text: str, target_lang: str) -> str:
        if not text or len(text.strip()) == 0:
            return text
        
        lang_map = {'ar': 'ar', 'en': 'en', 'fr': 'fr', 'tr': 'tr', 'zh': 'zh-CN', 'ru': 'ru'}
        if target_lang not in lang_map:
            return text
        target = lang_map[target_lang]
        
        cache_key = hashlib.md5(f"{text}_{target}".encode()).hexdigest()
        async with self.lock:
            if cache_key in self.cache:
                return self.cache[cache_key]
        
        if text in self.pending:
            future = asyncio.Future()
            self.pending[text].append(future)
            return await future
        
        self.pending[text] = []
        try:
            translator = GoogleTranslator(source='auto', target=target)
            translated = await asyncio.to_thread(translator.translate, text)
            
            async with self.lock:
                self.cache[cache_key] = translated
                if len(self.cache) > 500:
                    keys = list(self.cache.keys())[:200]
                    for k in keys:
                        del self.cache[k]
            
            for future in self.pending[text]:
                if not future.done():
                    future.set_result(translated)
            
            return translated
        except Exception as e:
            logger.error(f"خطأ في الترجمة: {e}")
            for future in self.pending[text]:
                if not future.done():
                    future.set_result(text)
            return text
        finally:
            if text in self.pending:
                del self.pending[text]

smart_translator = SmartTranslator()

async def translate_text(text: str, target_lang: str, source_lang: str = 'auto') -> str:
    return await smart_translator.translate(text, target_lang)

async def get_user_translation_language(user_id: int) -> str:
    async with _user_translation_cache_lock:
        if user_id in user_translation_settings_cache:
            return user_translation_settings_cache[user_id]
    async def _get(conn):
        cur = await conn.execute("SELECT lang FROM user_translation WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 'off'
    lang = await execute_db(_get)
    async with _user_translation_cache_lock:
        user_translation_settings_cache[user_id] = lang
    return lang

async def set_user_translation_language(user_id: int, lang: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO user_translation (user_id, lang) VALUES (?, ?)", (user_id, lang))
        await conn.commit()
    await execute_db(_set)
    async with _user_translation_cache_lock:
        user_translation_settings_cache[user_id] = lang

# ===================== نظام اللغة =====================
async def set_user_language(user_id: int, lang: str):
    async with _user_language_lock:
        user_language[user_id] = lang

def get_text(user_id: int, key: str) -> str:
    lang = user_language.get(user_id, 'ar')
    texts = {
        'ar': {
            'welcome': "🌿 **مرحباً بك في ريلاكس مانيجر**\nاختر اللغة المناسبة",
            'main_title': "🌿 **{0}**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 المعرف: `{1}`\n👥 مجموعاتي: {2}\n💎 الاشتراك: {3}\n📡 القناة النشطة: {4}\n📝 المنشورات غير المنشورة: {5}\n⚙️ النشر التلقائي: {6}",
            'no_channels': "لا توجد قنوات",
            'add_channel': "➕ إضافة قناة",
            'my_channels': "📡 قنواتي",
            'add_15_posts': "📥 إضافة 15 منشور",
            'publish_one': "📤 نشر واحد",
            'my_posts_btn': "📋 منشوراتي",
            'recycle': "♻️ إعادة تدوير",
            'stats_btn': "📊 إحصائياتي",
            'my_stats_btn': "📈 إحصائيات كاملة",
            'my_groups_btn': "👥 مجموعاتي",
            'settings_btn': "⚙️ الإعدادات",
            'schedule_btn': "⏰ الجدولة",
            'help_btn': "❓ المساعدة",
            'trial_btn': "🎁 تجربة مجانية",
            'subscribe_btn': "💎 اشتراك",
            'developer_btn': "👨‍💻 المطور",
            'language_btn': "🌐 اللغة",
            'support_btn': "📞 الدعم",
            'referral': "🔗 الإحالات",
            'reminder_settings': "⏰ التذكيرات",
            'translation_settings': "🌐 الترجمة",
            'publish_all': "📤 نشر الكل",
            'updates_btn': "📢 التحديثات",
            'add_to_group': "➕ إضافة إلى مجموعة",
            'admin_panel': "👑 لوحة الأدمن",
            'my_rank_btn': "📊 رتبتي",
            'top_10_btn': "🏆 أفضل 10",
            'schedule_post_btn': "📝 جدولة منشور",
            'channel_stats': "📊 إحصائيات القناة",
            'my_channels_summary': "📊 ملخص قنواتي",
            'auto_on': "مفعل",
            'auto_off': "معطل",
            'subscribed': "✅ مفعل",
            'not_subscribed': "❌ غير مفعل",
            'send_channel_id': "📡 أرسل معرف القناة (مثال: @channel أو -100123456)",
            'channel_added': "✅ تم إضافة القناة {0}",
            'channel_exists': "⚠️ القناة موجودة مسبقاً",
            'no_channels_list': "📭 لا توجد قنوات مسجلة",
            'channels_list': "📡 **قنواتي**\nاختر قناة للتحكم بها:",
            'delete_channel': "🗑️ حذف",
            'channel_deleted': "✅ تم حذف القناة",
            'delete_failed': "❌ فشل الحذف",
            'no_posts': "📭 لا توجد منشورات",
            'my_posts_title': "📋 **منشوراتي غير المنشورة**",
            'confirm_delete': "⚠️ هل أنت متأكد من حذف جميع المنشورات؟",
            'deleted_all': "✅ تم حذف جميع المنشورات",
            'recycled': "♻️ تم إعادة تدوير جميع المنشورات",
            'pending_stats': "📊 **إحصائيات المنشورات**\n━━━━━━━━━━━━━━━━━━━━━━\n📝 غير المنشورة: {0}\n📋 الإجمالي: {1}",
            'stats': "📈 **إحصائياتي الكاملة**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 القنوات: {0}\n📝 إجمالي المنشورات: {1}\n⏳ غير المنشورة: {2}\n👥 المجموعات: {3}\n⚙️ النشر التلقائي: {4}",
            'settings': "⚙️ **الإعدادات**\nاختر الإعداد المطلوب:",
            'disabled': "❌ تعطيل",
            'enabled': "✅ تفعيل",
            'auto_toggled': "✅ تم تغيير حالة النشر التلقائي إلى: {0}",
            'schedule_settings': "⏰ **إعدادات الجدولة**\n━━━━━━━━━━━━━━━━━━━━━━\n{0}\n━━━━━━━━━━━━━━━━━━━━━━\nاختر نوع الجدولة:",
            'interval_minutes': "دقائق: {0}",
            'interval_hours': "ساعات: {0}",
            'interval_days': "أيام: {0}",
            'days_week': "أيام الأسبوع: {0}",
            'specific_dates': "تواريخ محددة: {0}",
            'nothing': "لا شيء",
            'send_minutes': "⏱️ أرسل عدد الدقائق (مثال: 30)",
            'send_hours': "⏱️ أرسل عدد الساعات (مثال: 2)",
            'send_days': "⏱️ أرسل عدد الأيام (مثال: 1)",
            'send_dates': "📅 أرسل التواريخ مفصولة بفواصل (مثال: 2024-12-25,2025-01-01)",
            'send_time': "🕐 أرسل وقت النشر (مثال: 14:30)",
            'interval_set': "✅ تم حفظ الإعدادات",
            'invalid_number': "❌ رقم غير صالح",
            'invalid_date': "❌ تاريخ غير صالح",
            'invalid_time': "❌ وقت غير صالح",
            'days_saved': "✅ تم حفظ أيام النشر",
            'monday': "الإثنين",
            'tuesday': "الثلاثاء",
            'wednesday': "الأربعاء",
            'thursday': "الخميس",
            'friday': "الجمعة",
            'saturday': "السبت",
            'sunday': "الأحد",
            'admin_only': "🔒 هذا الأمر للمشرفين فقط!",
            'group_only': "🔒 هذا الأمر يعمل فقط في المجموعات!",
            'locked': "🔒 تم قفل المجموعة",
            'unlocked': "🔓 تم فتح المجموعة",
            'cancelled': "❌ تم الإلغاء",
            'error': "⚠️ حدث خطأ، حاول مرة أخرى",
            'help': "❓ **المساعدة**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 **الأوامر المتاحة:**\n/start - القائمة الرئيسية\n/trial - تجربة مجانية\n/subscribe - الاشتراك\n/syncgroup - تفعيل المجموعة\n/security - إعدادات الأمان\n/register_hidden_owner - تسجيل مالك مخفي\n/rank - رتبتك\n/top - أفضل 10\n/stats - إحصائيات القناة\n/lock - قفل المجموعة\n/unlock - فتح المجموعة\n/schedule - جدولة منشور\n/panel - لوحة التحكم\n/language - تغيير اللغة\n/support - مركز الدعم\n/help - هذه المساعدة\n/developer - المطور\n/updates - التحديثات",
            'support_welcome': "📞 **مركز الدعم**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الخدمة المطلوبة:",
            'support_help': "❓ **المساعدة**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 للتواصل مع الدعم:\n• استخدم /support\n• اكتب رسالتك\n• ستصلك تذكرة برقم\n• سنرد عليك بأسرع وقت\n\n📌 للمشاكل التقنية:\n• تأكد من أن البوت مشرف\n• تأكد من صلاحيات البوت\n• راجع إعدادات الأمان",
            'trial_used': "❌ لقد استخدمت التجربة المجانية مسبقاً",
            'already_subscribed': "✅ لديك اشتراك فعال بالفعل",
            'trial': "🎁 **تم تفعيل التجربة المجانية!**\n━━━━━━━━━━━━━━━━━━━━━━\n✅ لديك 30 يوماً مجاناً\n📌 استمتع بجميع الميزات\n💎 يمكنك الاشتراك بعد انتهاء التجربة",
            'subscribe': "💎 **الاشتراك**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الباقة المناسبة لك:\n\n⭐ 1 يوم - 5 نجوم\n⭐ 2 يوم - 9 نجوم\n⭐ شهر (30 يوم) - 50 نجمة\n⭐ 3 أشهر (90 يوم) - 120 نجمة\n\n📌 الدفع عبر نجوم تيليجرام",
            'updates_text': "📢 **آخر التحديثات**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 تابع قناة التحديثات لمعرفة كل جديد:\n• إضافات جديدة\n• تحسينات الأداء\n• إصلاحات الأخطاء\n• ميزات حصرية",
            'referral_title': "🔗 **الإحالات**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 رابط الإحالة الخاص بك:\n`https://t.me/{1}?start=ref_{0}`\n\n👥 عدد المحالين: {3}\n🎁 المكافآت المتاحة: {4} يوم\n⭐ المكافأة لكل إحالة: {5} يوم\n🎁 نقاط الترحيب: {6}",
            'copy_link': "📋 نسخ الرابط",
            'claim_reward': "🎁 صرف المكافآت",
            'referral_list': "📋 قائمة المحالين",
            'no_referrals': "📭 لا توجد إحالات بعد",
            'no_reward_available': "❌ لا توجد مكافآت متاحة للصرف",
            'reward_claimed': "✅ تم صرف {0} يوم اشتراك!",
            'reminder_title': "⏰ **إعدادات التذكيرات**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 تذكير انتهاء الاشتراك: {0}\n📊 تقرير يومي: {1}\n📈 تقرير أسبوعي: {2}\n⏰ التذكير قبل: {3} أيام",
            'reminder_sub': "🔔 تذكير الاشتراك",
            'reminder_daily': "📊 تقرير يومي",
            'reminder_weekly': "📈 تقرير أسبوعي",
            'reminder_days_btn': "⏰ عدد الأيام",
            'reminder_lang_btn': "🌐 لغة الإشعارات",
            'subscription_warning': "⚠️ **تنبيه!**\nاشتراكك ينتهي خلال {0} أيام\nقم بتجديده الآن لتستمر الميزات 💎",
            'daily_stats': "📊 **تقريرك اليومي**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 القنوات: {0}\n📝 إجمالي المنشورات: {1}\n⏳ غير المنشورة: {2}\n👥 المجموعات: {3}",
            'weekly_report': "📈 **تقريرك الأسبوعي**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 القنوات: {0}\n📝 إجمالي المنشورات: {1}\n⏳ غير المنشورة: {2}\n👥 المجموعات: {3}\n🔗 الإحالات: {4}",
            'translation_status_off': "معطلة ❌",
            'translation_status_on': "مفعلة ✅ إلى {0}",
            'translation_settings': "إعدادات الترجمة",
            'translation_how_it_works': "📌 كيفية العمل:\nسيتم ترجمة المنشورات تلقائياً عند النشر إلى اللغة التي تختارها",
            'translation_choose': "اختر لغة الترجمة:",
            'translation_off': "🚫 إيقاف الترجمة",
            'translation_disabled': "✅ تم إيقاف الترجمة",
            'translation_enabled': "✅ تم تفعيل الترجمة إلى {0}",
            'admin_panel': "👑 **لوحة الأدمن**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الإجراء المطلوب:",
            'admin_users': "👥 المستخدمين",
            'admin_banned': "🚫 المحظورين",
            'admin_channels': "📡 القنوات",
            'enter_admin_id': "👑 أرسل معرف المستخدم لإضافته كمشرف:",
            'enter_remove_admin_id': "🗑️ أرسل معرف المستخدم لإزالته من المشرفين:",
            'no_admins': "📭 لا يوجد مشرفون",
            'add_admin_success': "✅ تم إضافة {0} كمشرف",
            'remove_admin_success': "✅ تم إزالة {0} من المشرفين",
            'cannot_remove_main_admin': "❌ لا يمكن إزالة المطور الأساسي",
            'invalid_user_id': "❌ معرف مستخدم غير صالح",
            'select_backup': "💾 اختر النسخة الاحتياطية للاستعادة:",
            'no_backups': "📭 لا توجد نسخ احتياطية",
            'current_allowed_user': "📁 المستخدم الحالي المصرح له بـ /sendcode: {0}",
            'no_allowed_user': "لا يوجد",
            'set_new_sendcode_user': "➕ تعيين مستخدم جديد",
            'sendcode_user_set': "✅ تم تعيين {0} كمستخدم مصرح له بـ /sendcode",
            'confirm_delete_tickets': "⚠️ هل أنت متأكد من حذف جميع تذاكر الدعم؟",
            'tickets_deleted': "✅ تم حذف {0} تذكرة",
            'post_published': "✅ تم نشر المنشور بنجاح",
            'publish_error': "❌ فشل النشر: {0}",
            'not_admin': "❌ أنت لست مشرفاً في هذه المجموعة",
        },
        'en': {
            'welcome': "🌿 **Welcome to Relax Manager**\nChoose your language",
            'main_title': "🌿 **{0}**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 ID: `{1}`\n👥 My Groups: {2}\n💎 Subscription: {3}\n📡 Active Channel: {4}\n📝 Unpublished Posts: {5}\n⚙️ Auto Publish: {6}",
            'no_channels': "No channels",
            'add_channel': "➕ Add Channel",
            'my_channels': "📡 My Channels",
            'add_15_posts': "📥 Add 15 Posts",
            'publish_one': "📤 Publish One",
            'my_posts_btn': "📋 My Posts",
            'recycle': "♻️ Recycle",
            'stats_btn': "📊 My Stats",
            'my_stats_btn': "📈 Full Stats",
            'my_groups_btn': "👥 My Groups",
            'settings_btn': "⚙️ Settings",
            'schedule_btn': "⏰ Schedule",
            'help_btn': "❓ Help",
            'trial_btn': "🎁 Free Trial",
            'subscribe_btn': "💎 Subscribe",
            'developer_btn': "👨‍💻 Developer",
            'language_btn': "🌐 Language",
            'support_btn': "📞 Support",
            'referral': "🔗 Referrals",
            'reminder_settings': "⏰ Reminders",
            'translation_settings': "🌐 Translation",
            'publish_all': "📤 Publish All",
            'updates_btn': "📢 Updates",
            'add_to_group': "➕ Add to Group",
            'admin_panel': "👑 Admin Panel",
            'my_rank_btn': "📊 My Rank",
            'top_10_btn': "🏆 Top 10",
            'schedule_post_btn': "📝 Schedule Post",
            'channel_stats': "📊 Channel Stats",
            'my_channels_summary': "📊 My Channels Summary",
            'auto_on': "Enabled",
            'auto_off': "Disabled",
            'subscribed': "✅ Active",
            'not_subscribed': "❌ Inactive",
            'send_channel_id': "📡 Send channel ID (e.g., @channel or -100123456)",
            'channel_added': "✅ Channel {0} added",
            'channel_exists': "⚠️ Channel already exists",
            'no_channels_list': "📭 No channels registered",
            'channels_list': "📡 **My Channels**\nSelect a channel to control:",
            'delete_channel': "🗑️ Delete",
            'channel_deleted': "✅ Channel deleted",
            'delete_failed': "❌ Delete failed",
            'no_posts': "📭 No posts",
            'my_posts_title': "📋 **My Unpublished Posts**",
            'confirm_delete': "⚠️ Are you sure you want to delete all posts?",
            'deleted_all': "✅ All posts deleted",
            'recycled': "♻️ All posts recycled",
            'pending_stats': "📊 **Post Statistics**\n━━━━━━━━━━━━━━━━━━━━━━\n📝 Unpublished: {0}\n📋 Total: {1}",
            'stats': "📈 **My Full Stats**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 Channels: {0}\n📝 Total Posts: {1}\n⏳ Unpublished: {2}\n👥 Groups: {3}\n⚙️ Auto Publish: {4}",
            'settings': "⚙️ **Settings**\nSelect the setting:",
            'disabled': "❌ Disable",
            'enabled': "✅ Enable",
            'auto_toggled': "✅ Auto publish status changed to: {0}",
            'schedule_settings': "⏰ **Schedule Settings**\n━━━━━━━━━━━━━━━━━━━━━━\n{0}\n━━━━━━━━━━━━━━━━━━━━━━\nSelect schedule type:",
            'interval_minutes': "Minutes: {0}",
            'interval_hours': "Hours: {0}",
            'interval_days': "Days: {0}",
            'days_week': "Days of week: {0}",
            'specific_dates': "Specific dates: {0}",
            'nothing': "Nothing",
            'send_minutes': "⏱️ Send number of minutes (e.g., 30)",
            'send_hours': "⏱️ Send number of hours (e.g., 2)",
            'send_days': "⏱️ Send number of days (e.g., 1)",
            'send_dates': "📅 Send dates separated by commas (e.g., 2024-12-25,2025-01-01)",
            'send_time': "🕐 Send publish time (e.g., 14:30)",
            'interval_set': "✅ Settings saved",
            'invalid_number': "❌ Invalid number",
            'invalid_date': "❌ Invalid date",
            'invalid_time': "❌ Invalid time",
            'days_saved': "✅ Days saved",
            'monday': "Monday",
            'tuesday': "Tuesday",
            'wednesday': "Wednesday",
            'thursday': "Thursday",
            'friday': "Friday",
            'saturday': "Saturday",
            'sunday': "Sunday",
            'admin_only': "🔒 This command is for admins only!",
            'group_only': "🔒 This command works only in groups!",
            'locked': "🔒 Group locked",
            'unlocked': "🔓 Group unlocked",
            'cancelled': "❌ Cancelled",
            'error': "⚠️ An error occurred, try again",
            'help': "❓ **Help**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 **Available Commands:**\n/start - Main Menu\n/trial - Free Trial\n/subscribe - Subscribe\n/syncgroup - Activate Group\n/security - Security Settings\n/register_hidden_owner - Register Hidden Owner\n/rank - Your Rank\n/top - Top 10\n/stats - Channel Stats\n/lock - Lock Group\n/unlock - Unlock Group\n/schedule - Schedule Post\n/panel - Control Panel\n/language - Change Language\n/support - Support Center\n/help - This Help\n/developer - Developer\n/updates - Updates",
            'support_welcome': "📞 **Support Center**\n━━━━━━━━━━━━━━━━━━━━━━\nSelect the required service:",
            'support_help': "❓ **Help**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 To contact support:\n• Use /support\n• Write your message\n• You'll get a ticket number\n• We'll reply ASAP\n\n📌 For technical issues:\n• Make sure bot is admin\n• Check bot permissions\n• Review security settings",
            'trial_used': "❌ You have already used the free trial",
            'already_subscribed': "✅ You already have an active subscription",
            'trial': "🎁 **Free Trial Activated!**\n━━━━━━━━━━━━━━━━━━━━━━\n✅ You have 30 days free\n📌 Enjoy all features\n💎 You can subscribe after trial ends",
            'subscribe': "💎 **Subscription**\n━━━━━━━━━━━━━━━━━━━━━━\nChoose your plan:\n\n⭐ 1 Day - 5 Stars\n⭐ 2 Days - 9 Stars\n⭐ 30 Days (Month) - 50 Stars\n⭐ 90 Days (3 Months) - 120 Stars\n\n📌 Payment via Telegram Stars",
            'updates_text': "📢 **Latest Updates**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 Follow updates channel for news:\n• New features\n• Performance improvements\n• Bug fixes\n• Exclusive features",
            'referral_title': "🔗 **Referrals**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 Your referral link:\n`https://t.me/{1}?start=ref_{0}`\n\n👥 Total Referrals: {3}\n🎁 Available Rewards: {4} days\n⭐ Reward per Referral: {5} days\n🎁 Welcome Bonus: {6}",
            'copy_link': "📋 Copy Link",
            'claim_reward': "🎁 Claim Rewards",
            'referral_list': "📋 Referral List",
            'no_referrals': "📭 No referrals yet",
            'no_reward_available': "❌ No rewards available to claim",
            'reward_claimed': "✅ Claimed {0} days subscription!",
            'reminder_title': "⏰ **Reminder Settings**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 Subscription Reminder: {0}\n📊 Daily Report: {1}\n📈 Weekly Report: {2}\n⏰ Remind Before: {3} days",
            'reminder_sub': "🔔 Subscription Reminder",
            'reminder_daily': "📊 Daily Report",
            'reminder_weekly': "📈 Weekly Report",
            'reminder_days_btn': "⏰ Days Before",
            'reminder_lang_btn': "🌐 Notification Language",
            'subscription_warning': "⚠️ **Warning!**\nYour subscription expires in {0} days\nRenew now to keep features 💎",
            'daily_stats': "📊 **Your Daily Report**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 Channels: {0}\n📝 Total Posts: {1}\n⏳ Unpublished: {2}\n👥 Groups: {3}",
            'weekly_report': "📈 **Your Weekly Report**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 Channels: {0}\n📝 Total Posts: {1}\n⏳ Unpublished: {2}\n👥 Groups: {3}\n🔗 Referrals: {4}",
            'translation_status_off': "Disabled ❌",
            'translation_status_on': "Enabled ✅ to {0}",
            'translation_settings': "Translation Settings",
            'translation_how_it_works': "📌 How it works:\nPosts will be automatically translated to your chosen language when published",
            'translation_choose': "Choose translation language:",
            'translation_off': "🚫 Disable Translation",
            'translation_disabled': "✅ Translation disabled",
            'translation_enabled': "✅ Translation enabled to {0}",
            'admin_panel': "👑 **Admin Panel**\n━━━━━━━━━━━━━━━━━━━━━━\nSelect the action:",
            'admin_users': "👥 Users",
            'admin_banned': "🚫 Banned",
            'admin_channels': "📡 Channels",
            'enter_admin_id': "👑 Send user ID to add as admin:",
            'enter_remove_admin_id': "🗑️ Send user ID to remove from admins:",
            'no_admins': "📭 No admins",
            'add_admin_success': "✅ Added {0} as admin",
            'remove_admin_success': "✅ Removed {0} from admins",
            'cannot_remove_main_admin': "❌ Cannot remove main developer",
            'invalid_user_id': "❌ Invalid user ID",
            'select_backup': "💾 Select backup to restore:",
            'no_backups': "📭 No backups",
            'current_allowed_user': "📁 Currently allowed /sendcode user: {0}",
            'no_allowed_user': "None",
            'set_new_sendcode_user': "➕ Set new user",
            'sendcode_user_set': "✅ Set {0} as allowed /sendcode user",
            'confirm_delete_tickets': "⚠️ Are you sure you want to delete all support tickets?",
            'tickets_deleted': "✅ Deleted {0} tickets",
            'post_published': "✅ Post published successfully",
            'publish_error': "❌ Publish failed: {0}",
            'not_admin': "❌ You are not an admin in this group",
        }
    }
    lang_texts = texts.get(lang, texts['ar'])
    return lang_texts.get(key, key)

# ===================== دوال القوائم والأزرار =====================
class CallbackData:
    # القائمة الرئيسية
    MAIN_MENU = "main_menu"
    BACK = "back"
    CANCEL_SESSION = "cancel_session"
    NOOP = "noop"
    
    # الرتبة وأفضل 10 والجدولة
    RANK = "rank"
    TOP = "top"
    SCHEDULE_POST = "schedule_post"
    LANGUAGE = "language"
    
    # أزرار اللغة
    LANG_AR = "lang_ar"
    LANG_EN = "lang_en"
    LANG_FR = "lang_fr"
    LANG_TR = "lang_tr"
    LANG_ZH = "lang_zh"
    LANG_RU = "lang_ru"
    
    # القنوات
    CHANNELS_MY = "channels:my_channels"
    CHANNELS_ADD = "channels:add"
    CHANNELS_DELETE_PREFIX = "channels:delete:"
    CHANNELS_SELECT_PREFIX = "channels:select:"
    
    # المنشورات
    POSTS_ADD_15 = "posts:add_15"
    POSTS_PUBLISH_ONE = "posts:publish_one"
    POSTS_MY = "posts:my_posts"
    POSTS_RECYCLE = "posts:recycle"
    POSTS_DELETE_SINGLE_PREFIX = "posts:delete_single:"
    POSTS_CONFIRM_CLEAR_ALL_PREFIX = "posts:confirm_clear_all:"
    POSTS_CLEAR_ALL_PREFIX = "posts:clear_all:"
    CONFIRM_RECYCLE = "confirm_recycle:"  # جديد: تأكيد إعادة التدوير
    
    # الإحصائيات
    STATS_PENDING = "stats:pending"
    STATS_FULL = "stats:full"
    CHANNEL_STATS = "channel_stats"
    CHANNEL_GROWTH = "channel_growth"
    CHANNEL_STATS_REFRESH = "channel_stats_refresh"
    MY_CHANNEL_STATS = "my_channel_stats"
    
    # المجموعات
    GROUPS_MY = "groups:my_groups"
    GROUPS_SETTINGS_PREFIX = "groups:settings:"
    SECURITY_SELECT_GROUP = "security_select_group:"
    SECURITY_REFRESH_GROUPS = "security_refresh_groups"
    
    # الإعدادات
    SETTINGS_MENU = "settings:menu"
    SETTINGS_TOGGLE_AUTO_PUBLISH = "settings:toggle_auto_publish"
    
    # الجدولة
    SCHEDULE_MENU_PREFIX = "schedule:menu:"
    SCHEDULE_SET_INTERVAL_MINUTES_PREFIX = "schedule:set_interval_minutes:"
    SCHEDULE_SET_INTERVAL_HOURS_PREFIX = "schedule:set_interval_hours:"
    SCHEDULE_SET_INTERVAL_DAYS_PREFIX = "schedule:set_interval_days:"
    SCHEDULE_SET_DAYS_PREFIX = "schedule:set_days:"
    SCHEDULE_SET_DATES_PREFIX = "schedule:set_dates:"
    SCHEDULE_SET_PUBLISH_TIME_PREFIX = "schedule:set_publish_time:"
    SCHEDULE_DAY_SELECT_PREFIX = "schedule:day_select:"
    SCHEDULE_SAVE_DAYS = "schedule:save_days"
    
    # الأمان
    SECURITY_LINKS_PREFIX = "security:links:"
    SECURITY_MENTIONS_PREFIX = "security:mentions:"
    SECURITY_WARN_PREFIX = "security:warn:"
    SECURITY_SLOWMODE_PREFIX = "security:slowmode:"
    SECURITY_BANNED_WORDS_MENU_PREFIX = "security:banned_words_menu:"
    SECURITY_WELCOME_PREFIX = "security:welcome:"
    SECURITY_GOODBYE_PREFIX = "security:goodbye:"
    SECURITY_MAIN = "security:main"
    SECURITY_CLOSE = "security:close"
    
    # الكلمات المحظورة
    BANNED_WORDS_ADD_PREFIX = "banned_words:add:"
    BANNED_WORDS_LIST_PREFIX = "banned_words:list:"
    BANNED_WORDS_REMOVE_PREFIX = "banned_words:remove:"
    
    # الدعم والمساعدة
    HELP = "help"
    SUPPORT_MENU = "support:menu"
    SUPPORT_HELP = "support:help"
    SUPPORT_TICKET = "support:ticket"
    SUPPORT_BACK = "support:back"
    
    # التجربة والاشتراك
    TRIAL = "trial"
    SUBSCRIBE_MENU = "subscribe:menu"
    BUY_SUBSCRIPTION_1 = "buy:subscription_1"
    BUY_SUBSCRIPTION_2 = "buy:subscription_2"
    BUY_SUBSCRIPTION_30 = "buy:subscription_30"
    BUY_SUBSCRIPTION_90 = "buy:subscription_90"
    
    # المطور والتحديثات
    DEVELOPER = "developer"
    UPDATES = "updates"
    
    # الإحالات
    REFERRAL_MENU = "referral:menu"
    REFERRAL_COPY_LINK_PREFIX = "referral:copy_link:"
    REFERRAL_CLAIM_REWARD = "referral:claim_reward"
    REFERRAL_LIST = "referral:list"
    
    # التذكيرات
    REMINDER_MENU = "reminder:menu"
    REMINDER_TOGGLE_SUB = "reminder:toggle_sub"
    REMINDER_TOGGLE_DAILY = "reminder:toggle_daily"
    REMINDER_TOGGLE_WEEKLY = "reminder:toggle_weekly"
    REMINDER_SET_DAYS = "reminder:set_days"
    REMINDER_SET_LANG = "reminder:set_lang"
    REMINDER_LANG_PREFIX = "reminder:lang:"
    
    # الترجمة
    TRANSLATION_MENU = "translation:menu"
    TRANSLATION_OFF = "translation:off"
    TRANSLATION_SET_PREFIX = "translation:set:"
    
    # لوحة الأدمن
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
    ADMIN_DEL_BANNED_WORD_PREFIX = "admin_del_banned_word_"
    ADMIN_DEL_REPLY_PREFIX = "admin_del_reply_"
    
    # لوحة المجموعة
    PANEL_LOCK_PREFIX = "panel:lock:"
    PANEL_UNLOCK_PREFIX = "panel:unlock:"
    PANEL_CLOSE = "panel:close"
    
    # إجراءات المجموعة المتقدمة
    ADVANCED_ACTIONS = "advanced_actions"
    GROUP_ACTION_BAN = "group_action:ban"
    GROUP_ACTION_MUTE = "group_action:mute"
    GROUP_ACTION_WARN = "group_action:warn"
    GROUP_ACTION_KICK = "group_action:kick"
    GROUP_ACTION_RESTRICT = "group_action:restrict"
    GROUP_ACTION_PIN = "group_action:pin"
    GROUP_ACTION_LOG = "group_action:log"
    GROUP_ACTION_UNBAN = "group_action:unban"
    
    # مدة الكتم
    GROUP_MUTE_DURATION_5 = "group_mute_duration:5"
    GROUP_MUTE_DURATION_30 = "group_mute_duration:30"
    GROUP_MUTE_DURATION_60 = "group_mute_duration:60"
    GROUP_MUTE_DURATION_720 = "group_mute_duration:720"
    GROUP_MUTE_DURATION_1440 = "group_mute_duration:1440"
    GROUP_MUTE_DURATION_10080 = "group_mute_duration:10080"
    GROUP_MUTE_DURATION_PERMANENT = "group_mute_duration:permanent"
    ADV_MUTE_DURATION_PREFIX = "adv_mute_duration:"
    
    # العقوبات
    PENALTY_MENU = "penalty_menu"
    PENALTY_KICK = "penalty:kick"
    PENALTY_BAN = "penalty:ban"
    PENALTY_MUTE = "penalty:mute"
    
    # النشر
    PUBLISH_ALL_CHANNELS = "publish_all_channels"
    
    # الاشتراك الإجباري
    CHECK_SUBSCRIBE = "check_subscribe"
    
    # حذف المجموعة
    DELETE_GROUP_PREFIX = "delete_group:"

# ===================== نظام WebSocket =====================
class WebSocketManager:
    def __init__(self):
        self.connections = set()
        self.lock = asyncio.Lock()
    
    async def broadcast(self, data: dict):
        async with self.lock:
            if not self.connections:
                return
            message = json.dumps(data)
            to_remove = []
            for ws in self.connections:
                try:
                    await ws.send_str(message)
                except:
                    to_remove.append(ws)
            for ws in to_remove:
                self.connections.discard(ws)
    
    async def handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async with self.lock:
            self.connections.add(ws)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        if data.get('type') == 'ping':
                            await ws.send_str(json.dumps({'type': 'pong'}))
                    except:
                        pass
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"خطأ في WebSocket: {ws.exception()}")
        finally:
            async with self.lock:
                self.connections.discard(ws)
        return ws

ws_manager = WebSocketManager()

# ===================== دوال قاعدة البيانات =====================
class DatabasePool:
    def __init__(self):
        self.pool = None
        self.lock = asyncio.Lock()
    
    async def initialize(self):
        if self.pool is None:
            async with self.lock:
                if self.pool is None:
                    self.pool = await aiosqlite.connect(str(DB_PATH), timeout=DB_TIMEOUT)
                    await self.pool.execute("PRAGMA journal_mode=WAL")
                    await self.pool.execute("PRAGMA synchronous=NORMAL")
                    await self.pool.execute("PRAGMA foreign_keys=ON")
                    await self.pool.execute("PRAGMA cache_size=-64000")
                    await self.pool.execute("PRAGMA max_page_count=1000000")
                    await self.pool.execute("PRAGMA secure_delete=ON")
    
    async def get_connection(self):
        if self.pool is None:
            await self.initialize()
        return self.pool
    
    async def close(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

db_pool = DatabasePool()

async def execute_db(func):
    conn = await db_pool.get_connection()
    try:
        return await func(conn)
    except Exception as e:
        logger.error(f"خطأ في قاعدة البيانات: {e}")
        raise
    finally:
        pass

# ===================== دوال التشفير =====================
DB_ENCRYPTION_KEY = None

def init_db_encryption():
    global DB_ENCRYPTION_KEY
    db_key_file = DATA_PATH / ".db_key"
    if db_key_file.exists():
        try:
            with open(db_key_file, 'rb') as f:
                DB_ENCRYPTION_KEY = f.read()
        except:
            DB_ENCRYPTION_KEY = Fernet.generate_key()
            with open(db_key_file, 'wb') as f:
                f.write(DB_ENCRYPTION_KEY)
    else:
        DB_ENCRYPTION_KEY = Fernet.generate_key()
        with open(db_key_file, 'wb') as f:
            f.write(DB_ENCRYPTION_KEY)

def encrypt_db_backup() -> Path:
    if not DB_ENCRYPTION:
        return DB_PATH
    cipher = Fernet(DB_ENCRYPTION_KEY)
    with open(DB_PATH, 'rb') as f:
        data = f.read()
    encrypted = cipher.encrypt(data)
    encrypted_path = DB_PATH.with_suffix('.enc')
    with open(encrypted_path, 'wb') as f:
        f.write(encrypted)
    return encrypted_path

def decrypt_db_backup(encrypted_path: Path) -> bytes:
    if not DB_ENCRYPTION:
        with open(encrypted_path, 'rb') as f:
            return f.read()
    cipher = Fernet(DB_ENCRYPTION_KEY)
    with open(encrypted_path, 'rb') as f:
        encrypted_data = f.read()
    return cipher.decrypt(encrypted_data)

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
        if row and row[0]:
            try:
                current_end = datetime.fromisoformat(row[0])
                if current_end > utc_now():
                    new_end = current_end + timedelta(days=days)
                else:
                    new_end = utc_now() + timedelta(days=days)
            except:
                new_end = utc_now() + timedelta(days=days)
        else:
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
        return await cur.fetchall()
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

async def db_save_posts(channel_db_id: int, posts: list) -> int:
    async def _save(conn):
        count = 0
        for text_content, media_type, media_file_id in posts:
            await conn.execute("INSERT INTO posts (channel_db_id, text, media_type, media_file_id, created_at, views_count) VALUES (?, ?, ?, ?, ?, 0)",
                              (channel_db_id, sanitize_text(text_content), media_type, media_file_id, utc_now_iso()))
            count += 1
        await conn.commit()
        return count
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
        await conn.execute("UPDATE posts SET published=0 WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_reset)

async def db_should_auto_recycle(channel_db_id: int) -> bool:
    total = await db_get_posts_count(channel_db_id)
    published = await db_get_published_count(channel_db_id)
    return total > 0 and published >= total

async def db_reset_posts_to_unpublished(channel_db_id: int, user_id: int = None):
    async def _reset(conn):
        await conn.execute("UPDATE posts SET published=0 WHERE channel_db_id=?", (channel_db_id,))
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

async def db_get_user_channels_count(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM user_channels WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_get)

async def db_get_user_groups_count(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM bot_groups WHERE added_by=? OR chat_id IN (SELECT chat_id FROM user_groups_link WHERE user_id=?)", (user_id, user_id))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_get)

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

async def db_register_group(chat_id: int, chat_name: str, added_by: int, username: str = None) -> bool:
    async def _register(conn):
        cur = await conn.execute("SELECT chat_id FROM bot_groups WHERE chat_id=?", (chat_id,))
        if await cur.fetchone():
            await conn.execute("UPDATE bot_groups SET chat_name=?, username=?, added_by=? WHERE chat_id=?", (chat_name, username, added_by, chat_id))
            await conn.commit()
            return False
        await conn.execute("INSERT INTO bot_groups (chat_id, chat_name, username, added_by, added_at) VALUES (?, ?, ?, ?, ?)",
                          (chat_id, chat_name, username, added_by, utc_now_iso()))
        await conn.execute("INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?, ?)", (added_by, chat_id))
        await conn.commit()
        return True
    return await execute_db(_register)

async def db_get_user_groups(user_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT chat_id, chat_name, username, banned FROM bot_groups WHERE added_by=? OR chat_id IN (SELECT chat_id FROM user_groups_link WHERE user_id=?)", (user_id, user_id))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_all_groups(only_banned: bool = False):
    async def _get(conn):
        if only_banned:
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups WHERE banned=1 ORDER BY added_at DESC")
        else:
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups ORDER BY added_at DESC")
        return await cur.fetchall()
    return await execute_db(_get)

async def db_register_channel(channel_id: int, channel_name: str, added_by: int):
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

async def db_get_all_bot_channels(only_banned: bool = False):
    async def _get(conn):
        if only_banned:
            cur = await conn.execute("SELECT channel_id, channel_name, added_by, added_at, banned FROM bot_channels WHERE banned=1 ORDER BY added_at DESC")
        else:
            cur = await conn.execute("SELECT channel_id, channel_name, added_by, added_at, banned FROM bot_channels ORDER BY added_at DESC")
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_all_user_channels_no_limit():
    async def _get(conn):
        cur = await conn.execute("SELECT uc.user_id, uc.id, uc.channel_id, uc.channel_name, uc.banned FROM user_channels uc ORDER BY uc.id")
        return await cur.fetchall()
    return await execute_db(_get)

async def db_all_users_channels(only_banned: bool = False, limit: int = 500):
    async def _get(conn):
        if only_banned:
            cur = await conn.execute("SELECT user_id, id, channel_id, channel_name, banned FROM user_channels WHERE banned=1 LIMIT ?", (limit,))
        else:
            cur = await conn.execute("SELECT user_id, id, channel_id, channel_name, banned FROM user_channels LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_publish_interval() -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='publish_interval'")
        row = await cur.fetchone()
        return int(row[0]) if row else DEFAULT_PUBLISH_INTERVAL_SECONDS
    return await execute_db(_get)

async def db_get_publish_interval_seconds() -> int:
    return await db_get_publish_interval()

async def db_set_publish_interval_seconds(seconds: int, admin_id: int, is_admin: bool = False):
    if not is_admin and admin_id != MAIN_ADMIN_ID:
        return False
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(seconds),))
        await conn.commit()
    await execute_db(_set)
    return True

async def db_get_updates_channel():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='updates_channel'")
        row = await cur.fetchone()
        return row[0] if row and row[0] else None
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
        return row[0] if row and row[0] else None
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
        return row[0] if row and row[0] else None
    return await execute_db(_get)

async def db_set_log_channel_id(channel_id: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('log_channel_id', ?)", (channel_id,))
        await conn.commit()
    return await execute_db(_set)

async def db_get_security_settings(chat_id: int):
    if CACHETOOLS_AVAILABLE:
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
                'slow_mode_seconds': row[4] if row[4] else 5,
                'welcome_enabled': row[5] == 1,
                'welcome_text': row[6] if row[6] else "مرحباً {user} في {chat} 🤍",
                'goodbye_enabled': row[7] == 1,
                'goodbye_text': row[8] if row[8] else "وداعاً {user} 👋",
                'delete_banned_words': row[9] == 1,
                'auto_penalty': row[10] if row[10] else 'none',
                'auto_mute_duration': row[11] if row[11] else 60
            }
            if CACHETOOLS_AVAILABLE:
                _security_cache[chat_id] = settings
            return settings
        default_settings = {
            'links': False, 'mentions': False, 'warn': True, 'slow_mode': False,
            'slow_mode_seconds': 5, 'welcome_enabled': False, 'welcome_text': "مرحباً {user} في {chat} 🤍",
            'goodbye_enabled': False, 'goodbye_text': "وداعاً {user} 👋", 'delete_banned_words': False,
            'auto_penalty': 'none', 'auto_mute_duration': 60
        }
        if CACHETOOLS_AVAILABLE:
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
        if CACHETOOLS_AVAILABLE and chat_id in _security_cache:
            del _security_cache[chat_id]
    return await execute_db(_set)

async def db_check_slow_mode(chat_id: int, user_id: int) -> bool:
    settings = await db_get_security_settings(chat_id)
    if not settings['slow_mode']:
        return True
    seconds = settings['slow_mode_seconds']
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
    if user_id == MAIN_ADMIN_ID:
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

async def db_save_schedule(channel_db_id: int, schedule_type: str, interval_minutes: int = None, interval_hours: int = None, interval_days: int = None, days_of_week: str = None, specific_dates: str = None, publish_time: str = None):
    async def _save(conn):
        await conn.execute("""
            INSERT OR REPLACE INTO schedule (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, next_publish_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """, (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time or "00:00"))
        await conn.commit()
    return await execute_db(_save)

async def db_get_schedule(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, next_publish_date FROM schedule WHERE channel_db_id=?", (channel_db_id,))
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
        publish_time_str = schedule.get('publish_time', '00:00')
        hour, minute = map(int, publish_time_str.split(':'))
        next_date = None
        now = utc_now()
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
            days_of_week = parse_days_of_week_safe(schedule.get('days_of_week', '[]'))
            if days_of_week:
                target_date = last_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                found = False
                for i in range(1, 8):
                    check_date = target_date + timedelta(days=i)
                    if check_date.weekday() in days_of_week:
                        next_date = check_date
                        found = True
                        break
                if not found:
                    next_date = target_date + timedelta(days=7)
                    while next_date.weekday() not in days_of_week:
                        next_date += timedelta(days=1)
            else:
                next_date = last_time + timedelta(days=1)
        elif schedule_type == 'dates':
            specific_dates = parse_dates_safe(schedule.get('specific_dates', '[]'))
            if specific_dates:
                target_date = last_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                for date_str in sorted(specific_dates):
                    try:
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d').replace(hour=hour, minute=minute, second=0, microsecond=0)
                        if date_obj > last_time:
                            next_date = date_obj
                            break
                    except:
                        continue
                if not next_date:
                    try:
                        next_date = datetime.strptime(specific_dates[0], '%Y-%m-%d').replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=365)
                    except:
                        next_date = utc_now() + timedelta(days=1)
            else:
                next_date = utc_now() + timedelta(days=1)
        if next_date:
            await conn.execute("UPDATE schedule SET next_publish_date=? WHERE channel_db_id=?", (next_date.isoformat(), channel_db_id))
            await conn.commit()
    return await execute_db(_update)

async def db_set_publish_time(channel_db_id: int, time_str: str):
    async def _set(conn):
        await conn.execute("UPDATE schedule SET publish_time=? WHERE channel_db_id=?", (time_str, channel_db_id))
        await conn.commit()
    return await execute_db(_set)

async def db_unpublished_count(channel_db_id: int) -> int:
    async def _count(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_count)

async def check_bot_permissions(bot, channel_id: str) -> tuple:
    try:
        me = await bot.get_chat_member(channel_id, bot.id)
        if me.status not in ['administrator', 'creator']:
            return False, "البوت ليس مشرفاً في القناة"
        if not me.can_post_messages:
            return False, "البوت لا يملك صلاحية النشر"
        return True, ""
    except Exception as e:
        return False, str(e)[:100]

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

async def db_add_scheduled_post(chat_id: int, text: str, publish_time: datetime):
    async def _add(conn):
        await conn.execute("INSERT INTO scheduled_posts (chat_id, text, publish_time, fail_count) VALUES (?, ?, ?, 0)", (chat_id, sanitize_text(text), publish_time.isoformat()))
        await conn.commit()
    return await execute_db(_add)

async def db_get_due_scheduled_posts(now: datetime):
    async def _get(conn):
        cur = await conn.execute("SELECT id, chat_id, text, fail_count FROM scheduled_posts WHERE publish_time <= ?", (now.isoformat(),))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_update_scheduled_post_fail(post_id: int, fail_count: int):
    async def _update(conn):
        await conn.execute("UPDATE scheduled_posts SET fail_count = ? WHERE id = ?", (fail_count, post_id))
        await conn.commit()
    return await execute_db(_update)

async def db_delete_scheduled_post(post_id: int):
    async def _delete(conn):
        await conn.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
        await conn.commit()
    return await execute_db(_delete)

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

async def db_get_user_ticket(user_id):
    async def _get(conn):
        cur = await conn.execute("SELECT ticket_number, status, created_at FROM support_tickets WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        return await cur.fetchone()
    return await execute_db(_get)

async def db_get_all_tickets(limit=20):
    async def _get(conn):
        cur = await conn.execute("SELECT id, user_id, username, message, ticket_number, status, created_at FROM support_tickets ORDER BY id DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_last_ticket_id_for_user(user_id):
    async def _get(conn):
        cur = await conn.execute("SELECT id FROM support_tickets WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else None
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

async def db_get_user_by_referral_code(referral_code: str) -> int | None:
    async def _get(conn):
        cur = await conn.execute("SELECT user_id FROM users WHERE referral_code=?", (referral_code,))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_add_referral(referrer_id: int, referred_id: int) -> bool:
    async def _add(conn):
        if referrer_id == referred_id:
            return False
        cur = await conn.execute("SELECT 1 FROM referrals WHERE referred_id=?", (referred_id,))
        if await cur.fetchone():
            return False
        today_start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        cur = await conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND referred_at >= ?", (referrer_id, today_start))
        count_today = (await cur.fetchone())[0]
        settings = await db_get_referral_settings()
        max_per_day = int(settings.get('max_referrals_per_day', '5'))
        if count_today >= max_per_day:
            return False
        await conn.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, referred_id))
        await conn.execute("INSERT INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days) VALUES (?, 1, 0, 0) ON CONFLICT(user_id) DO UPDATE SET referral_count = referral_count + 1", (referrer_id,))
        await conn.commit()
        return True
    return await execute_db(_add)

async def db_auto_reward_referral(referrer_id: int, referred_id: int) -> int:
    async def _reward(conn):
        settings = await db_get_referral_settings()
        reward_days = int(settings.get('reward_days_per_referral', '3'))
        await conn.execute("INSERT INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days) VALUES (?, 0, ?, 0) ON CONFLICT(user_id) DO UPDATE SET total_reward_days = total_reward_days + ?", (referrer_id, reward_days, reward_days))
        await conn.execute("UPDATE referrals SET is_rewarded=1 WHERE referrer_id=? AND referred_id=?", (referrer_id, referred_id))
        await conn.commit()
        return reward_days
    return await execute_db(_reward)

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

async def db_get_welcome_bonus_points() -> int:
    settings = await db_get_referral_settings()
    return int(settings.get('welcome_bonus_points', '10'))

async def db_get_user_reminder_settings(user_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute("SELECT subscription_reminder, daily_stats_reminder, weekly_report, reminder_days_before, last_reminder_sent, notification_lang FROM user_reminder_settings WHERE user_id=?", (user_id,))
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
            await conn.execute("INSERT INTO user_reminder_settings (user_id, subscription_reminder, daily_stats_reminder, weekly_report, reminder_days_before, last_reminder_sent, notification_lang) VALUES (?, 1, 0, 1, 3, 0, 'ar')", (user_id,))
            await conn.commit()
            return {'subscription_reminder': True, 'daily_stats_reminder': False, 'weekly_report': True, 'reminder_days_before': 3, 'last_reminder_sent': 0, 'notification_lang': 'ar'}
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

async def db_update_last_reminder_sent(user_id: int, reminder_type: str):
    async def _update(conn):
        now_timestamp = int(time_module.time())
        await conn.execute("UPDATE user_reminder_settings SET last_reminder_sent=? WHERE user_id=?", (now_timestamp, user_id))
        await conn.commit()
    return await execute_db(_update)

async def db_get_users_needing_reminder() -> list:
    async def _get(conn):
        now = utc_now()
        users = []
        cur = await conn.execute("SELECT user_id, subscription_end FROM users WHERE subscription_end IS NOT NULL AND banned=0")
        rows = await cur.fetchall()
        for user_id, subscription_end_str in rows:
            try:
                end_date = datetime.fromisoformat(subscription_end_str)
                days_left = (end_date - now).days
                if days_left < 0:
                    continue
                settings = await db_get_user_reminder_settings(user_id)
                if settings['subscription_reminder']:
                    reminder_days = settings['reminder_days_before']
                    last_sent = settings['last_reminder_sent']
                    now_timestamp = int(time_module.time())
                    need_reminder = False
                    if 0 < days_left <= reminder_days:
                        if last_sent == 0:
                            need_reminder = True
                        elif (now_timestamp - last_sent) > (3 * 24 * 60 * 60):
                            need_reminder = True
                    if need_reminder:
                        users.append({'user_id': user_id, 'days_left': days_left, 'notification_lang': settings['notification_lang']})
            except:
                continue
        return users
    return await execute_db(_get)

async def db_get_all_active_users_for_report() -> list:
    async def _get(conn):
        thirty_days_ago = (utc_now() - timedelta(days=30)).isoformat()
        cur = await conn.execute("SELECT user_id FROM users_cache WHERE last_updated >= ?", (thirty_days_ago,))
        return [row[0] for row in await cur.fetchall()]
    return await execute_db(_get)

LEVEL_REQUIREMENTS = {1: 0, 2: 100, 3: 250, 4: 500, 5: 1000, 6: 2000, 7: 3500, 8: 5000, 9: 7500, 10: 10000}

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

user_points_last_hour = defaultdict(lambda: (0, 0.0))
async def cleanup_points_cache():
    while True:
        await asyncio.sleep(3600)
        user_points_last_hour.clear()

async def add_points(user_id: int, update: Update = None, context: ContextTypes.DEFAULT_TYPE = None):
    now = utc_now()
    count, last_timestamp = user_points_last_hour.get(user_id, (0, 0.0))
    if last_timestamp > 0:
        last_time = datetime.fromtimestamp(last_timestamp)
        last_time = to_naive(last_time)
        if (now - last_time).total_seconds() < 3600:
            if count >= 20:
                return
            new_count = count + 1
        else:
            new_count = 1
    else:
        new_count = 1
    user_points_last_hour[user_id] = (new_count, now.timestamp())
    data = await db_get_user_level(user_id)
    old_level = data['level']
    points = data['points'] + 1
    level = old_level
    new_levels = []
    for lvl, pts in LEVEL_REQUIREMENTS.items():
        if points >= pts and lvl > level:
            new_levels.append(lvl)
            level = lvl
    if new_levels and update and update.effective_user and context:
        try:
            if len(new_levels) == 1:
                msg = f"🎉 **تهانينا!**\nلقد وصلت إلى المستوى {new_levels[0]}! 🎉"
            else:
                msg = f"🎉 **تهانينا!**\nلقد تقدمت {len(new_levels)} مستويات إلى المستوى {new_levels[-1]}! 🎉"
            await safe_send_markdown(context.bot, user_id, msg)
        except:
            pass
    await db_update_user_level(user_id, points, level)

async def get_rank(user_id: int) -> dict:
    return await db_get_user_level(user_id)

async def get_top_users(limit: int = 10):
    async def _get(conn):
        cur = await conn.execute("SELECT user_id, points, level FROM user_levels ORDER BY points DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

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

async def db_create_contest(creator_id: int, title: str, description: str, prize: str, end_date: datetime):
    async def _create(conn):
        cur = await conn.execute("""
            INSERT INTO contests (creator_id, title, description, prize, end_date, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?)
        """, (creator_id, title, description, prize, end_date.isoformat(), utc_now_iso()))
        await conn.commit()
        return cur.lastrowid
    return await execute_db(_create)

async def db_get_active_contests(limit=10):
    async def _get(conn):
        cur = await conn.execute("""
            SELECT id, creator_id, title, description, prize, end_date, created_at
            FROM contests 
            WHERE status = 'active' AND end_date > datetime('now')
            ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_contest(contest_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT * FROM contests WHERE id=?", (contest_id,))
        return await cur.fetchone()
    return await execute_db(_get)

async def db_participate_in_contest(user_id: int, contest_id: int, answer: str = None):
    async def _participate(conn):
        await conn.execute("""
            INSERT OR IGNORE INTO contest_participants (user_id, contest_id, answer, joined_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, contest_id, answer, utc_now_iso()))
        await conn.commit()
        return True
    return await execute_db(_participate)

async def db_get_contest_participants(contest_id: int, limit=50):
    async def _get(conn):
        cur = await conn.execute("""
            SELECT u.user_id, u.first_name, u.username, cp.joined_at
            FROM contest_participants cp
            JOIN users_cache u ON cp.user_id = u.user_id
            WHERE cp.contest_id = ?
            ORDER BY cp.joined_at LIMIT ?
        """, (contest_id, limit))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_announce_contest_winner(contest_id: int, winner_id: int):
    async def _announce(conn):
        await conn.execute("UPDATE contests SET winner_id=?, status='ended' WHERE id=?", (winner_id, contest_id))
        await conn.commit()
        await conn.execute("""
            INSERT INTO contest_winners (contest_id, winner_id, announced_at)
            VALUES (?, ?, ?)
        """, (contest_id, winner_id, utc_now_iso()))
        await conn.commit()
    return await execute_db(_announce)

async def db_get_user_profile(user_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute("""
            SELECT bio, location, website, join_date, points, level, 
                   avatar_file_id, cover_file_id, badges, social_links, theme
            FROM user_profiles WHERE user_id=?
        """, (user_id,))
        row = await cur.fetchone()
        if row:
            badges = []
            try:
                if row[8]:
                    badges = json.loads(row[8])
            except:
                pass
            social_links = {}
            try:
                if row[9]:
                    social_links = json.loads(row[9])
            except:
                pass
            return {
                'bio': row[0], 'location': row[1], 'website': row[2],
                'join_date': row[3], 'points': row[4], 'level': row[5],
                'avatar_file_id': row[6], 'cover_file_id': row[7],
                'badges': badges,
                'social_links': social_links,
                'theme': row[10] or 'dark'
            }
        return {
            'bio': '', 'location': '', 'website': '', 'join_date': utc_now_iso(),
            'points': 0, 'level': 1, 'avatar_file_id': None, 'cover_file_id': None,
            'badges': [], 'social_links': {}, 'theme': 'dark'
        }
    return await execute_db(_get)

async def db_update_user_profile(user_id: int, **kwargs):
    async def _update(conn):
        allowed_fields = ['bio', 'location', 'website', 'avatar_file_id', 'cover_file_id', 'social_links', 'theme']
        updates = []
        values = []
        for key, value in kwargs.items():
            if key in allowed_fields:
                if key in ['social_links']:
                    updates.append(f"{key}=?")
                    values.append(json.dumps(value))
                else:
                    updates.append(f"{key}=?")
                    values.append(value)
        if updates:
            query = f"INSERT OR REPLACE INTO user_profiles (user_id, {', '.join(updates)}, join_date) VALUES (?, {', '.join(['?'] * len(updates))}, COALESCE((SELECT join_date FROM user_profiles WHERE user_id=?), datetime('now')))"
            await conn.execute(query, [user_id] + values + [user_id])
            await conn.commit()
    return await execute_db(_update)

async def db_add_badge(user_id: int, badge_name: str, badge_icon: str = "🏆"):
    async def _add(conn):
        cur = await conn.execute("SELECT badges FROM user_profiles WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        badges = []
        if row and row[0]:
            try:
                badges = json.loads(row[0])
            except:
                pass
        if not any(b['name'] == badge_name for b in badges):
            badges.append({'name': badge_name, 'icon': badge_icon, 'earned_at': utc_now_iso()})
            await conn.execute("UPDATE user_profiles SET badges=? WHERE user_id=?", (json.dumps(badges), user_id))
            await conn.commit()
            return True
        return False
    return await execute_db(_add)

async def db_get_user_badges(user_id: int) -> list:
    async def _get(conn):
        cur = await conn.execute("SELECT badges FROM user_profiles WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0]:
            try:
                return json.loads(row[0])
            except:
                return []
        return []
    return await execute_db(_get)

async def db_get_leaderboard(limit=20):
    async def _get(conn):
        cur = await conn.execute("""
            SELECT u.user_id, u.first_name, u.username, up.points, up.level
            FROM user_profiles up
            JOIN users_cache u ON up.user_id = u.user_id
            ORDER BY up.points DESC LIMIT ?
        """, (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

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

async def execute_ban(bot, chat_id: int, user_id: int, until_date=None, reason: str = "", moderator_id: int = None):
    try:
        await bot.ban_chat_member(chat_id, user_id, until_date=until_date)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'ban', 0, ?, ?, ?)", 
                              (chat_id, user_id, moderator_id or MAIN_ADMIN_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم حظر المستخدم `{user_id}` بنجاح"
    except Exception as e:
        return False, f"❌ فشل الحظر: {str(e)[:100]}"

async def execute_mute(bot, chat_id: int, user_id: int, duration_minutes: int = None, reason: str = "", moderator_id: int = None):
    try:
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
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'mute', ?, ?, ?, ?)", 
                              (chat_id, user_id, duration_minutes, moderator_id or MAIN_ADMIN_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم كتم المستخدم `{user_id}`{duration_text}"
    except Exception as e:
        return False, f"❌ فشل الكتم: {str(e)[:100]}"

async def execute_unmute(bot, chat_id: int, user_id: int):
    try:
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

async def execute_kick(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    try:
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'kick', 0, ?, ?, ?)", 
                              (chat_id, user_id, moderator_id or MAIN_ADMIN_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم طرد المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل الطرد: {str(e)[:100]}"

async def execute_warn(bot, chat_id: int, user_id: int, moderator_id: int, reason: str = "", auto_ban_limit: int = 3):
    async def _add_warning(conn):
        cur = await conn.execute("SELECT warnings FROM user_warnings WHERE user_id=? AND chat_id=?", (user_id, chat_id))
        row = await cur.fetchone()
        warnings = row[0] + 1 if row else 1
        await conn.execute("INSERT OR REPLACE INTO user_warnings (user_id, chat_id, warnings) VALUES (?,?,?)", (user_id, chat_id, warnings))
        await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'warn', ?, ?, ?, ?)", 
                          (chat_id, user_id, warnings, moderator_id, reason[:200] if reason else "", utc_now_iso()))
        await conn.commit()
        return warnings
    warnings = await execute_db(_add_warning)
    if warnings >= auto_ban_limit:
        await execute_ban(bot, chat_id, user_id, reason=f"تلقائي بعد {warnings} تحذيرات", moderator_id=moderator_id)
        async def _clear_warnings(conn):
            await conn.execute("DELETE FROM user_warnings WHERE user_id=? AND chat_id=?", (user_id, chat_id))
            await conn.commit()
        await execute_db(_clear_warnings)
        return True, f"⚠️ تم تحذير المستخدم `{user_id}` ({warnings}/{auto_ban_limit}) وتم حظره تلقائياً"
    return True, f"⚠️ تم تحذير المستخدم `{user_id}` ({warnings}/{auto_ban_limit})"

async def execute_restrict(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    try:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False
        )
        await bot.restrict_chat_member(chat_id, user_id, permissions)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'restrict', 0, ?, ?, ?)", 
                              (chat_id, user_id, moderator_id or MAIN_ADMIN_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم تقييد المستخدم `{user_id}` (لا يمكنه إرسال وسائط)"
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
        await bot.unban_chat_member(chat_id, user_id)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'unban', 0, ?, ?, ?)", 
                              (chat_id, user_id, moderator_id or MAIN_ADMIN_ID, "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم إلغاء حظر المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل إلغاء الحظر: {str(e)[:100]}"

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
        elif action == 'warn' and duration:
            duration_text = f" (تحذير #{duration})"
        elif action == 'unban':
            duration_text = ""
        reason_text = f"\n   📝 السبب: {reason[:50]}" if reason else ""
        text += f"• `{user_id}` → {action}{duration_text}{reason_text}\n   🕐 {time_str}\n\n"
    return text

# ============================================================
# دوال إحصائيات القنوات المتقدمة
# ============================================================
async def db_get_channel_stats(channel_db_id: int) -> dict:
    async def _get_stats(conn):
        cur = await conn.execute(
            """
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
            """,
            (channel_db_id,)
        )
        row = await cur.fetchone()
        if not row or row[0] == 0:
            return {
                'total_posts': 0,
                'published_posts': 0,
                'unpublished_posts': 0,
                'total_views': 0,
                'avg_views': 0,
                'last_post_time': None,
                'first_post_time': None,
                'avg_time_between_posts': 0,
                'best_publish_hour': 0,
                'best_publish_day': 0,
                'published_today': 0,
                'published_this_week': 0,
                'published_this_month': 0,
                'most_viewed_post': None,
                'least_viewed_post': None,
            }
        total_posts = row[0] or 0
        published_posts = row[1] or 0
        unpublished_posts = row[2] or 0
        total_views = row[3] or 0
        avg_views = row[4] or 0
        last_post_time = row[5]
        first_post_time = row[6]
        avg_time_between = 0
        if published_posts > 1 and last_post_time and first_post_time:
            try:
                last_dt = datetime.fromisoformat(last_post_time)
                first_dt = datetime.fromisoformat(first_post_time)
                time_diff = (last_dt - first_dt).total_seconds()
                avg_time_between = time_diff / (published_posts - 1) if published_posts > 1 else 0
            except:
                avg_time_between = 0
        best_hour = 0
        best_day = 0
        if published_posts > 0:
            cur = await conn.execute(
                """
                SELECT 
                    strftime('%H', created_at) as hour,
                    COUNT(*) as count
                FROM posts 
                WHERE channel_db_id = ? AND published = 1
                GROUP BY hour
                ORDER BY count DESC
                LIMIT 1
                """,
                (channel_db_id,)
            )
            hour_row = await cur.fetchone()
            if hour_row:
                best_hour = int(hour_row[0])
            cur = await conn.execute(
                """
                SELECT 
                    strftime('%w', created_at) as day,
                    COUNT(*) as count
                FROM posts 
                WHERE channel_db_id = ? AND published = 1
                GROUP BY day
                ORDER BY count DESC
                LIMIT 1
                """,
                (channel_db_id,)
            )
            day_row = await cur.fetchone()
            if day_row:
                best_day = int(day_row[0])
        today = utc_now().date().isoformat()
        week_start = (utc_now() - timedelta(days=7)).isoformat()
        month_start = (utc_now() - timedelta(days=30)).isoformat()
        cur = await conn.execute(
            """
            SELECT 
                SUM(CASE WHEN date(created_at) = ? THEN 1 ELSE 0 END) as today_count,
                SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as week_count,
                SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as month_count
            FROM posts 
            WHERE channel_db_id = ? AND published = 1
            """,
            (today, week_start, month_start, channel_db_id)
        )
        extra_row = await cur.fetchone()
        published_today = extra_row[0] or 0 if extra_row else 0
        published_this_week = extra_row[1] or 0 if extra_row else 0
        published_this_month = extra_row[2] or 0 if extra_row else 0
        most_viewed = None
        least_viewed = None
        cur = await conn.execute(
            """
            SELECT id, text, views_count 
            FROM posts 
            WHERE channel_db_id = ? AND published = 1
            ORDER BY views_count DESC
            LIMIT 1
            """,
            (channel_db_id,)
        )
        most_row = await cur.fetchone()
        if most_row:
            most_viewed = {'id': most_row[0], 'text': most_row[1][:50] + '...' if most_row[1] and len(most_row[1]) > 50 else most_row[1], 'views': most_row[2]}
        cur = await conn.execute(
            """
            SELECT id, text, views_count 
            FROM posts 
            WHERE channel_db_id = ? AND published = 1 AND views_count > 0
            ORDER BY views_count ASC
            LIMIT 1
            """,
            (channel_db_id,)
        )
        least_row = await cur.fetchone()
        if least_row:
            least_viewed = {'id': least_row[0], 'text': least_row[1][:50] + '...' if least_row[1] and len(least_row[1]) > 50 else least_row[1], 'views': least_row[2]}
        return {
            'total_posts': total_posts,
            'published_posts': published_posts,
            'unpublished_posts': unpublished_posts,
            'total_views': total_views,
            'avg_views': round(avg_views, 2) if avg_views else 0,
            'last_post_time': last_post_time,
            'first_post_time': first_post_time,
            'avg_time_between_posts': round(avg_time_between / 3600, 2) if avg_time_between else 0,
            'best_publish_hour': best_hour,
            'best_publish_day': best_day,
            'published_today': published_today,
            'published_this_week': published_this_week,
            'published_this_month': published_this_month,
            'most_viewed_post': most_viewed,
            'least_viewed_post': least_viewed,
        }
    return await execute_db(_get_stats)

async def db_update_post_views(post_id: int, views_count: int = None):
    async def _update_views(conn):
        if views_count is not None:
            await conn.execute(
                "UPDATE posts SET views_count = ?, last_view_time = ? WHERE id = ?",
                (views_count, utc_now_iso(), post_id)
            )
        else:
            await conn.execute(
                "UPDATE posts SET views_count = views_count + 1, last_view_time = ? WHERE id = ?",
                (utc_now_iso(), post_id)
            )
        await conn.commit()
    await execute_db(_update_views)

async def db_get_channel_stats_summary(user_id: int) -> dict:
    async def _get_summary(conn):
        channels = await db_get_channels(user_id)
        if not channels:
            return None
        total_posts = 0
        total_published = 0
        total_views = 0
        total_channels = len(channels)
        best_channel = None
        best_channel_views = 0
        for ch_db_id, ch_tele_id, ch_name, banned in channels:
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
            'total_posts': total_posts,
            'total_published': total_published,
            'total_views': total_views,
            'avg_views_per_channel': round(total_views / total_channels, 2) if total_channels > 0 else 0,
            'best_channel': best_channel,
            'active_channels': len([ch for ch in channels if ch[3] == 0])
        }
    return await execute_db(_get_summary)

async def db_get_channel_growth(channel_db_id: int, days: int = 30) -> dict:
    async def _get_growth(conn):
        start_date = (utc_now() - timedelta(days=days)).isoformat()
        cur = await conn.execute(
            """
            SELECT 
                date(created_at) as post_date,
                COUNT(*) as count,
                SUM(views_count) as views
            FROM posts 
            WHERE channel_db_id = ? AND created_at >= ?
            GROUP BY date(created_at)
            ORDER BY post_date
            """,
            (channel_db_id, start_date)
        )
        rows = await cur.fetchall()
        dates = []
        counts = []
        views = []
        for row in rows:
            dates.append(row[0])
            counts.append(row[1] or 0)
            views.append(row[2] or 0)
        return {
            'dates': dates,
            'counts': counts,
            'views': views,
            'total_days': len(dates),
            'total_posts': sum(counts),
            'total_views': sum(views)
        }
    return await execute_db(_get_growth)

# ============================================================
# دوال Google Drive المحسّنة
# ============================================================
_DRIVE_SERVICE_CACHE = None
_DRIVE_SERVICE_CACHE_TIME = 0
_DRIVE_SERVICE_CACHE_TTL = 3600

async def get_google_drive_service(force_refresh: bool = False):
    global _DRIVE_SERVICE_CACHE, _DRIVE_SERVICE_CACHE_TIME
    if not CLOUD_BACKUP_ENABLED:
        logger.warning("☁️ Google Drive Backup معطل في الإعدادات")
        return None
    now = time_module.time()
    if not force_refresh and _DRIVE_SERVICE_CACHE and (now - _DRIVE_SERVICE_CACHE_TIME) < _DRIVE_SERVICE_CACHE_TTL:
        return _DRIVE_SERVICE_CACHE
    try:
        creds = None
        token_path = Path(TOKEN_FILE)
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), 
                                                              ['https://www.googleapis.com/auth/drive.file'])
            except Exception as e:
                logger.warning(f"⚠️ فشل تحميل التوكن المخزن: {e}")
        if creds and creds.valid:
            _DRIVE_SERVICE_CACHE = build('drive', 'v3', credentials=creds)
            _DRIVE_SERVICE_CACHE_TIME = now
            logger.info("✅ تم استعادة خدمة Google Drive من التوكن المخزن")
            return _DRIVE_SERVICE_CACHE
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())
                _DRIVE_SERVICE_CACHE = build('drive', 'v3', credentials=creds)
                _DRIVE_SERVICE_CACHE_TIME = now
                logger.info("✅ تم تجديد توكن Google Drive")
                return _DRIVE_SERVICE_CACHE
            except Exception as e:
                logger.warning(f"⚠️ فشل تجديد التوكن: {e}")
                if token_path.exists():
                    token_path.unlink()
        if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
            logger.error(f"❌ ملف الاعتمادات غير موجود: {GOOGLE_CREDENTIALS_FILE}")
            return None
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(
            GOOGLE_CREDENTIALS_FILE,
            ['https://www.googleapis.com/auth/drive.file']
        )
        creds = flow.run_local_server(port=0)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
        _DRIVE_SERVICE_CACHE = build('drive', 'v3', credentials=creds)
        _DRIVE_SERVICE_CACHE_TIME = now
        logger.info("✅ تم الحصول على توكن Google Drive جديد")
        return _DRIVE_SERVICE_CACHE
    except Exception as e:
        logger.error(f"❌ خطأ في خدمة Google Drive: {e}")
        return None

async def upload_backup_to_drive(backup_path: Path, max_retries: int = 3) -> str:
    if not CLOUD_BACKUP_ENABLED or not GOOGLE_DRIVE_FOLDER_ID:
        return None
    if not backup_path.exists():
        logger.error(f"❌ ملف النسخ غير موجود: {backup_path}")
        return None
    for attempt in range(max_retries):
        try:
            service = await get_google_drive_service(force_refresh=(attempt > 0))
            if not service:
                if attempt == max_retries - 1:
                    logger.error("❌ فشل الحصول على خدمة Google Drive بعد عدة محاولات")
                    return None
                await asyncio.sleep(2 ** attempt)
                continue
            file_name = f"backup_{mecca_now().strftime('%Y%m%d_%H%M%S')}.enc"
            try:
                results = service.files().list(
                    q=f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents",
                    orderBy="createdTime desc",
                    pageSize=15,
                    fields="files(id, name)"
                ).execute()
                files = results.get('files', [])
                for old_file in files[10:]:
                    try:
                        service.files().delete(fileId=old_file['id']).execute()
                        logger.info(f"🗑️ تم حذف ملف قديم من Drive: {old_file['name']}")
                    except Exception as e:
                        logger.warning(f"⚠️ فشل حذف الملف القديم: {e}")
            except Exception as e:
                logger.warning(f"⚠️ فشل تنظيف الملفات القديمة: {e}")
            media = MediaFileUpload(
                str(backup_path), 
                mimetype='application/octet-stream', 
                resumable=True,
                chunksize=1024*1024
            )
            file_metadata = {
                'name': file_name,
                'parents': [GOOGLE_DRIVE_FOLDER_ID]
            }
            file = service.files().create(
                body=file_metadata, 
                media_body=media, 
                fields='id'
            )
            response = file.execute()
            file_id = response.get('id')
            logger.info(f"✅ تم رفع النسخة إلى Google Drive: {file_id} (المحاولة {attempt+1})")
            return file_id
        except Exception as e:
            logger.error(f"❌ خطأ في رفع النسخة: {e}")
            if attempt == max_retries - 1:
                return None
            await asyncio.sleep(2 ** attempt)
    return None

async def download_backup_from_drive(file_name: str, max_retries: int = 3) -> Path:
    if not CLOUD_BACKUP_ENABLED:
        raise Exception("☁️ Google Drive Backup معطل")
    for attempt in range(max_retries):
        try:
            service = await get_google_drive_service(force_refresh=(attempt > 0))
            if not service:
                if attempt == max_retries - 1:
                    raise Exception("فشل الحصول على خدمة Google Drive")
                await asyncio.sleep(2 ** attempt)
                continue
            results = service.files().list(
                q=f"name='{file_name}' and '{GOOGLE_DRIVE_FOLDER_ID}' in parents",
                fields="files(id, name)",
                pageSize=10
            ).execute()
            files = results.get('files', [])
            if not files:
                raise Exception(f"الملف {file_name} غير موجود في Drive")
            file_id = files[0]['id']
            request = service.files().get_media(fileId=file_id)
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.enc')
            temp_path = Path(temp_file.name)
            temp_file.close()
            fh = io.FileIO(str(temp_path), 'wb')
            downloader = MediaIoBaseDownload(fh, request, chunksize=1024*1024)
            done = False
            while not done:
                try:
                    status, done = downloader.next_chunk()
                except Exception as e:
                    logger.warning(f"⚠️ خطأ في التحميل: {e}")
                    raise
            fh.close()
            logger.info(f"✅ تم تحميل النسخة من Google Drive: {file_name}")
            return temp_path
        except Exception as e:
            logger.error(f"❌ فشل تحميل النسخة من Drive (محاولة {attempt+1}): {e}")
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
    raise Exception(f"فشل تحميل {file_name} بعد {max_retries} محاولات")

async def list_cloud_backups(limit: int = 20) -> list:
    if not CLOUD_BACKUP_ENABLED:
        return []
    try:
        service = await get_google_drive_service()
        if not service:
            return []
        results = service.files().list(
            q=f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents",
            orderBy="createdTime desc",
            pageSize=limit,
            fields="files(id, name, createdTime, size)"
        ).execute()
        files = results.get('files', [])
        return [{'id': f['id'], 'name': f['name'], 'size': f.get('size', 'غير معروف')} for f in files]
    except Exception as e:
        logger.error(f"❌ فشل جلب قائمة النسخ من السحابة: {e}")
        return []

async def create_backup():
    try:
        encrypted_path = encrypt_db_backup()
        temp_backup = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_backup.close()
        shutil.copy2(DB_PATH, temp_backup.name)
        with open(temp_backup.name, 'rb') as f:
            backup_data = f.read()
        compressed = gzip.compress(backup_data)
        encrypted = BACKUP_CIPHER.encrypt(compressed)
        backup_file = BACKUP_DIR / f"backup_{mecca_now().strftime('%Y%m%d_%H%M%S')}.enc"
        with open(backup_file, 'wb') as f:
            f.write(encrypted)
        os.unlink(temp_backup.name)
        backups = sorted(BACKUP_DIR.glob("backup_*.enc"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old_backup in backups[MAX_BACKUPS:]:
            old_backup.unlink()
        if CLOUD_BACKUP_ENABLED:
            await upload_backup_to_drive(backup_file)
        logger.info(f"✅ تم إنشاء نسخة احتياطية مشفرة: {backup_file}")
        return backup_file
    except Exception as e:
        logger.error(f"❌ فشل إنشاء النسخة الاحتياطية: {e}")
        raise

async def list_backups():
    return sorted(BACKUP_DIR.glob("backup_*.enc"), key=lambda x: x.stat().st_mtime, reverse=True)

async def restore_backup(backup_path: Path):
    if not backup_path.exists():
        raise FileNotFoundError(f"الملف {backup_path} غير موجود")
    with open(backup_path, 'rb') as f:
        encrypted = f.read()
    try:
        decrypted = BACKUP_CIPHER.decrypt(encrypted)
    except Exception as e:
        raise ValueError(f"فشل فك التشفير: {e}")
    try:
        decompressed = gzip.decompress(decrypted)
    except Exception as e:
        raise ValueError(f"فشل فك الضغط: {e}")
    temp_restore = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    temp_restore.write(decompressed)
    temp_restore.close()
    current_backup = BACKUP_DIR / f"pre_restore_{mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(DB_PATH, current_backup)
    shutil.copy2(temp_restore.name, DB_PATH)
    os.unlink(temp_restore.name)
    await db_pool.initialize()
    logger.info(f"✅ تم استعادة النسخة الاحتياطية: {backup_path}")

async def auto_backup():
    consecutive_errors = 0
    backoff = AUTO_BACKUP_SLEEP
    max_backoff = 7 * 24 * 60 * 60
    while True:
        try:
            await asyncio.sleep(AUTO_BACKUP_SLEEP)
            async def _check_and_backup(conn):
                cur = await conn.execute("SELECT value FROM settings WHERE key='auto_backup'")
                row = await cur.fetchone()
                return row and row[0] == '1'
            auto_enabled = await execute_db(_check_and_backup)
            if auto_enabled:
                await create_backup()
                async def _update_backup_time(conn):
                    await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_backup', ?)", (utc_now_iso(),))
                    await conn.commit()
                await execute_db(_update_backup_time)
            consecutive_errors = 0
            backoff = AUTO_BACKUP_SLEEP
        except Exception as e:
            logger.error(f"⚠️ خطأ في النسخ الاحتياطي التلقائي: {e}")
            backoff = min(backoff * 1.5, max_backoff)
            await asyncio.sleep(backoff)

# ============================================================
# دوال الكولباك - دوال إحصائيات القنوات
# ============================================================
async def channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إحصائيات القناة"""
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    ch_db_id = int(query.data.split(":")[-1])
    
    stats = await db_get_channel_stats(ch_db_id)
    ch_info = await db_get_channel_info(ch_db_id)
    channel_name = ch_info[1] if ch_info else "القناة"
    
    if stats['total_posts'] == 0:
        text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد منشورات بعد"
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{ch_db_id}")],
            [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{ch_db_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ]))
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
    text += f"⏱️ متوسط الوقت بين المنشورات: {stats['avg_time_between_posts']} ساعة\n"
    text += f"🕐 أفضل وقت للنشر: {stats['best_publish_hour']}:00\n"
    day_names = ['الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت']
    text += f"📅 أفضل يوم للنشر: {day_names[stats['best_publish_day']] if stats['best_publish_day'] < 7 else 'غير محدد'}\n"
    text += f"📊 المنشورات اليوم: {stats['published_today']}\n"
    text += f"📊 هذا الأسبوع: {stats['published_this_week']}\n"
    text += f"📊 هذا الشهر: {stats['published_this_month']}\n"
    
    if stats['most_viewed_post']:
        text += f"\n🏆 **الأكثر مشاهدة:**\n{stats['most_viewed_post']['text']}\n👁️ {stats['most_viewed_post']['views']} مشاهدة\n"
    if stats['least_viewed_post']:
        text += f"\n📉 **الأقل مشاهدة:**\n{stats['least_viewed_post']['text']}\n👁️ {stats['least_viewed_post']['views']} مشاهدة\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{ch_db_id}")],
        [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{ch_db_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def channel_growth_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض رسم بياني لنمو القناة"""
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    ch_db_id = int(query.data.split(":")[-1])
    
    growth = await db_get_channel_growth(ch_db_id, 30)
    ch_info = await db_get_channel_info(ch_db_id)
    channel_name = ch_info[1] if ch_info else "القناة"
    
    if not growth['dates']:
        text = f"📈 **نمو {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد بيانات كافية"
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 العودة للإحصائيات", callback_data=f"{CallbackData.CHANNEL_STATS}:{ch_db_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ]))
        return
    
    fig = go.Figure()
    fig.add_trace(go.Bar(name='المنشورات', x=growth['dates'], y=growth['counts'], marker_color='#2ecc71'))
    fig.add_trace(go.Scatter(name='المشاهدات', x=growth['dates'], y=growth['views'], mode='lines+markers', marker_color='#3498db'))
    fig.update_layout(
        title=f'نمو قناة {channel_name} - آخر 30 يوم',
        template='plotly_dark',
        xaxis_title='التاريخ',
        yaxis_title='العدد',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1)
    )
    
    try:
        img_bytes = fig.to_image(format='png', width=800, height=400)
        photo_file = BytesIO(img_bytes)
        photo_file.name = 'growth.png'
        await query.message.reply_photo(photo=photo_file, caption=f"📈 **نمو {channel_name}**\n📊 إجمالي المنشورات: {growth['total_posts']}\n👁️ إجمالي المشاهدات: {growth['total_views']}")
        await query.delete_message()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 العودة للإحصائيات", callback_data=f"{CallbackData.CHANNEL_STATS}:{ch_db_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        await safe_send_markdown(context.bot, uid, "📊 استخدم الأزرار للتنقل:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"خطأ في توليد الرسم البياني: {e}")
        text = f"📈 **نمو {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        for i in range(min(10, len(growth['dates']))):
            text += f"📅 {growth['dates'][i]}: {growth['counts'][i]} منشورات, {growth['views'][i]} مشاهدة\n"
        text += f"\n📊 إجمالي المنشورات: {growth['total_posts']}\n👁️ إجمالي المشاهدات: {growth['total_views']}"
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 العودة للإحصائيات", callback_data=f"{CallbackData.CHANNEL_STATS}:{ch_db_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ]))

async def channel_stats_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تحديث إحصائيات القناة"""
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    ch_db_id = int(query.data.split(":")[-1])
    await channel_stats_callback(update, context)

async def my_channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض ملخص إحصائيات جميع قنوات المستخدم"""
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    
    summary = await db_get_channel_stats_summary(uid)
    if not summary or summary['total_channels'] == 0:
        text = "📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد قنوات مسجلة"
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة قناة", callback_data=CallbackData.CHANNELS_ADD)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ]))
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
        text += f"📌 {summary['best_channel']['name']}\n"
        text += f"👁️ {summary['best_channel']['views']} مشاهدة\n"
        text += f"📝 {summary['best_channel']['posts']} منشور\n"
        text += f"📊 متوسط المشاهدات: {summary['best_channel']['avg_views']}\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=CallbackData.MY_CHANNEL_STATS)],
        [InlineKeyboardButton("📡 قنواتي", callback_data=CallbackData.CHANNELS_MY)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

# ============================================================
# معالج الأخطاء العام
# ============================================================
async def global_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأخطاء العام"""
    try:
        error = context.error
        logger.error(f"خطأ غير متوقع: {error}")
        import traceback
        traceback.print_exc()
        
        if update and update.effective_user:
            user_id = update.effective_user.id
            try:
                await safe_send_markdown(
                    context.bot,
                    user_id,
                    f"❌ **حدث خطأ غير متوقع**\n\n```\n{str(error)[:200]}```\n\n🔄 جرب مرة أخرى لاحقاً"
                )
            except:
                pass
        
        # إرسال تقرير للمطور
        if MAIN_ADMIN_ID:
            try:
                error_text = f"🚨 **خطأ في البوت**\n\n"
                error_text += f"📌 المستخدم: {update.effective_user.id if update and update.effective_user else 'غير معروف'}\n"
                error_text += f"⚠️ الخطأ: `{str(error)[:300]}`\n"
                if update and update.effective_message and update.effective_message.text:
                    error_text += f"📝 الرسالة: `{update.effective_message.text[:100]}`\n"
                await context.bot.send_message(MAIN_ADMIN_ID, error_text, parse_mode="MarkdownV2")
            except:
                pass
    except Exception as e:
        logger.error(f"فشل معالج الأخطاء: {e}")

# ============================================================
# معالج الرسائل في المجموعات
# ============================================================
class MessageProcessor:
    def __init__(self):
        self.rate_limit = {}
        self.cooldown = 2
    
    async def add_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.effective_chat or not update.effective_user:
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
                await safe_send_markdown(context.bot, chat_id, f"🔒 المجموعة مقفلة من قبل المشرف", 5)
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
                await safe_send_markdown(context.bot, chat_id, f"⏱️ **وضع بطيء مفعل**\n@{user.username or str(user_id)} يرجى الانتظار قبل إرسال رسالة جديدة", 3)
            except:
                pass
            return
        
        settings = await db_get_security_settings(chat_id)
        text = update.message.text or update.message.caption or ""
        
        # التحقق من الكلمات المحظورة
        if settings.get('delete_banned_words'):
            banned_word = await db_contains_banned_word(text, chat_id)
            if banned_word:
                try:
                    await update.message.delete()
                    await safe_send_markdown(context.bot, chat_id, f"🚫 **كلمة محظورة**\n@{user.username or str(user_id)} الكلمة `{banned_word}` غير مسموح بها")
                except:
                    pass
                await self._apply_penalty(context.bot, chat_id, user_id, settings)
                return
        
        # التحقق من الروابط
        if settings.get('links') and contains_link(text):
            try:
                await update.message.delete()
                await safe_send_markdown(context.bot, chat_id, f"🔗 **الروابط غير مسموح بها**\n@{user.username or str(user_id)}")
            except:
                pass
            await self._apply_penalty(context.bot, chat_id, user_id, settings)
            return
        
        # التحقق من المعرفات
        if settings.get('mentions') and contains_mention(text):
            try:
                await update.message.delete()
                await safe_send_markdown(context.bot, chat_id, f"@ **المعرفات غير مسموح بها**\n@{user.username or str(user_id)}")
            except:
                pass
            await self._apply_penalty(context.bot, chat_id, user_id, settings)
            return
        
        # ردود المجموعة
        reply = await db_get_reply(text.lower())
        if reply:
            try:
                await update.message.reply_text(reply)
            except:
                pass
    
    async def _apply_penalty(self, bot, chat_id, user_id, settings):
        penalty = settings.get('auto_penalty', 'none')
        if penalty == 'none':
            return
        
        if penalty == 'kick':
            await execute_kick(bot, chat_id, user_id, "مخالفة قواعد المجموعة")
        elif penalty == 'ban':
            await execute_ban(bot, chat_id, user_id, reason="مخالفة قواعد المجموعة")
        elif penalty == 'mute':
            duration = settings.get('auto_mute_duration', 60)
            await execute_mute(bot, chat_id, user_id, duration, "مخالفة قواعد المجموعة")

message_processor = MessageProcessor()

async def filter_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await message_processor.add_message(update, context)

# ============================================================
# نظام Rate Limiting
# ============================================================
class RateLimiter:
    def __init__(self):
        self.requests = defaultdict(list)
        self.lock = asyncio.Lock()
    
    async def check_rate_limit(self, user_id: int, action: str, max_requests: int, time_window: int) -> bool:
        async with self.lock:
            key = f"{user_id}:{action}"
            now = time_module.time()
            self.requests[key] = [t for t in self.requests[key] if now - t < time_window]
            if len(self.requests[key]) >= max_requests:
                return False
            self.requests[key].append(now)
            return True

rate_limiter = RateLimiter()

# ============================================================
# دوال التحقق من الصلاحيات
# ============================================================
async def is_authorized_in_group(bot, chat_id: int, user_id: int) -> bool:
    """التحقق من أن المستخدم مشرف في المجموعة أو مالك مخفي"""
    try:
        # التحقق من المالك المخفي
        if await db_is_hidden_owner(chat_id, user_id):
            return True
        
        # التحقق من المشرفين العاديين
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ['administrator', 'creator']
    except:
        return False

async def send_addition_report(bot, adder, chat, chat_type_name):
    """إرسال تقرير عند إضافة البوت"""
    try:
        if not adder:
            return
        text = f"✅ **تم إضافة البوت إلى {chat_type_name}**\n\n"
        text += f"📌 **المجموعة:** {chat.title or 'بدون اسم'}\n"
        text += f"🆔 **المعرف:** `{chat.id}`\n"
        if chat.username:
            text += f"🔗 **الرابط:** @{chat.username}\n"
        text += f"👤 **المضيف:** {adder.full_name or adder.first_name or adder.id}\n"
        text += f"🆔 **معرف المضيف:** `{adder.id}`\n"
        text += f"📅 **التاريخ:** {mecca_now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        text += "📌 استخدم /syncgroup لتفعيل الميزات المتقدمة"
        await bot.send_message(MAIN_ADMIN_ID, text, parse_mode="MarkdownV2")
    except:
        pass

async def detect_owner_type(bot, chat_id: int) -> dict:
    """كشف نوع المالك في المجموعة"""
    try:
        admins = await bot.get_chat_administrators(chat_id)
        for admin in admins:
            if admin.status == 'creator':
                user = admin.user
                return {
                    'is_hidden': user.username is None,
                    'user_id': user.id,
                    'username': user.username,
                    'full_name': user.full_name
                }
        return {'is_hidden': False, 'user_id': None}
    except:
        return {'is_hidden': False, 'user_id': None}

# ============================================================
# دوال الكولباك الأخرى
# ============================================================
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    kb, title, active_channel = await get_main_keyboard(uid)
    if active_channel:
        context.user_data['active_channel'] = active_channel
        await db_set_active_channel(uid, active_channel)
    await safe_edit_markdown(query, title, reply_markup=kb)

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu_callback(update, context)

async def cancel_session_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    context.user_data.pop(f"session_{uid}", None)
    context.user_data.pop(f"session_target_{uid}", None)
    context.user_data.pop('state', None)
    await query.edit_message_text(get_text(uid, 'cancelled'))
    await main_menu_callback(update, context)

async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار الفارغة"""
    await safe_query_answer(update.callback_query)

async def add_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    context.user_data['state'] = 'waiting_for_channel_id'
    await query.edit_message_text(get_text(uid, 'send_channel_id'))

async def my_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    channels = await db_get_channels(uid)
    if not channels:
        await query.edit_message_text(get_text(uid, 'no_channels_list'))
        return
    kb = []
    for ch in channels:
        ch_db_id, ch_tele_id, ch_name, banned = ch
        display = ch_name if ch_name != ch_tele_id else ch_tele_id
        kb.append([
            InlineKeyboardButton(f"📢 {display}", callback_data=f"{CallbackData.CHANNELS_SELECT_PREFIX}{ch_db_id}"),
            InlineKeyboardButton(get_text(uid, 'channel_stats'), callback_data=f"{CallbackData.CHANNEL_STATS}:{ch_db_id}"),
            InlineKeyboardButton(get_text(uid, 'delete_channel'), callback_data=f"{CallbackData.CHANNELS_DELETE_PREFIX}{ch_db_id}")
        ])
    kb.append([InlineKeyboardButton(get_text(uid, 'add_channel'), callback_data=CallbackData.CHANNELS_ADD)])
    kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)])
    await query.edit_message_text(get_text(uid, 'channels_list'), reply_markup=InlineKeyboardMarkup(kb))

async def delete_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    ch_db_id = int(query.data.split(":")[-1])
    if await db_delete_channel_by_id(uid, ch_db_id):
        await query.edit_message_text(get_text(uid, 'channel_deleted'))
        await my_channels_callback(update, context)
    else:
        await safe_query_answer(query, get_text(uid, 'delete_failed'), show_alert=True)

async def select_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    ch_db_id = int(query.data.split(":")[-1])
    await db_set_active_channel(uid, ch_db_id)
    context.user_data['active_channel'] = ch_db_id
    await invalidate_user_cache(uid)
    kb, title, new_active = await get_main_keyboard(uid)
    if new_active:
        context.user_data['active_channel'] = new_active
    await safe_edit_markdown(query, title, reply_markup=kb)

async def add_15_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        await query.edit_message_text("⚠️ اختر قناة أولاً")
        return
    context.user_data[f"session_{uid}"] = []
    context.user_data[f"session_target_{uid}"] = 15
    context.user_data['state'] = f'adding_posts_{uid}'
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.CANCEL_SESSION)]])
    await query.edit_message_text("📥 أرسل المنشورات (نصوص أو صور أو فيديوهات أو مستندات)", reply_markup=cancel_kb)

async def publish_one_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        await query.edit_message_text("⚠️ اختر قناة أولاً")
        return
    post = await db_get_next_post(active)
    if not post:
        await query.edit_message_text(get_text(uid, 'no_posts'))
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
            await context.bot.send_photo(ch_info[0], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'video' and post['media_file_id']:
            await context.bot.send_video(ch_info[0], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'document' and post['media_file_id']:
            await context.bot.send_document(ch_info[0], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'audio' and post['media_file_id']:
            await context.bot.send_audio(ch_info[0], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'voice' and post['media_file_id']:
            await context.bot.send_voice(ch_info[0], post['media_file_id'], caption=final_text if final_text else None)
        elif post['media_type'] == 'animation' and post['media_file_id']:
            await context.bot.send_animation(ch_info[0], post['media_file_id'], caption=final_text if final_text else None)
        else:
            await context.bot.send_message(ch_info[0], final_text)
        await db_mark_published(post['id'])
        await db_set_last_publish(active, utc_now())
        await db_update_next_publish_date(active)
        await query.edit_message_text(get_text(uid, 'post_published'))
    except Exception as e:
        await query.edit_message_text(get_text(uid, 'publish_error').format(str(e)[:100]))
    await main_menu_callback(update, context)

async def my_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        await query.edit_message_text("⚠️ اختر قناة أولاً")
        return
    posts = await db_get_user_posts_for_channel(active, limit=15)
    if not posts:
        await query.edit_message_text(get_text(uid, 'no_posts'))
        return
    msg = get_text(uid, 'my_posts_title') + "\n"
    kb_buttons = []
    for idx, (pid, ptext, media_type) in enumerate(posts[:10], 1):
        short = re.sub('<[^>]+>', '', ptext)[:80]
        media_icon = "🖼️" if media_type == 'photo' else "🎬" if media_type == 'video' else "📝" if media_type == 'text' else "📄"
        msg += f"{idx}. {media_icon} {short}...\n🆔 {pid}\n\n"
        kb_buttons.append([InlineKeyboardButton(f"🗑️ حذف #{pid}", callback_data=f"{CallbackData.POSTS_DELETE_SINGLE_PREFIX}{pid}_{active}")])
    kb_buttons.append([InlineKeyboardButton("🗑️ حذف الكل", callback_data=f"{CallbackData.POSTS_CONFIRM_CLEAR_ALL_PREFIX}{active}")])
    kb_buttons.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)])
    await safe_edit_markdown(query, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))

async def delete_single_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    parts = query.data.split(":")[-1].split("_")
    if len(parts) >= 2:
        post_id = int(parts[0])
        active = int(parts[1])
        if await db_delete_single_post(post_id, uid, active):
            await safe_query_answer(query, "✅ تم حذف المنشور", show_alert=True)
            await my_posts_callback(update, context)
        else:
            await safe_query_answer(query, "❌ فشل الحذف", show_alert=True)

async def confirm_clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    active = int(query.data.split(":")[-1])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم", callback_data=f"{CallbackData.POSTS_CLEAR_ALL_PREFIX}{active}"),
         InlineKeyboardButton("❌ لا", callback_data=CallbackData.BACK)]
    ])
    await query.edit_message_text(get_text(uid, 'confirm_delete'), reply_markup=kb)

async def clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    active = int(query.data.split(":")[-1])
    async def _clear_posts(conn):
        await conn.execute("DELETE FROM posts WHERE channel_db_id=?", (active,))
        await conn.commit()
    await execute_db(_clear_posts)
    await safe_query_answer(query, get_text(uid, 'deleted_all'), show_alert=True)
    await main_menu_callback(update, context)

async def recycle_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعادة تدوير المنشورات - مع تأكيد"""
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        await query.edit_message_text("⚠️ اختر قناة أولاً")
        return
    
    # جلب عدد المنشورات
    total_posts = await db_get_posts_count(active)
    published_posts = await db_get_published_count(active)
    
    if total_posts == 0:
        await query.edit_message_text("📭 لا توجد منشورات لإعادة تدويرها")
        return
    
    if published_posts == 0:
        await query.edit_message_text("📭 لا توجد منشورات منشورة لإعادة تدويرها")
        return
    
    # عرض تأكيد
    text = f"⚠️ **تأكيد إعادة التدوير**\n━━━━━━━━━━━━━━━━━━━━━━\n📝 إجمالي المنشورات: {total_posts}\n✅ المنشورة: {published_posts}\n⏳ غير المنشورة: {total_posts - published_posts}\n━━━━━━━━━━━━━━━━━━━━━━\n\nسيتم إعادة تعيين **جميع** المنشورات المنشورة إلى حالة غير منشورة.\nهل أنت متأكد؟"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، إعادة تدوير", callback_data=f"{CallbackData.CONFIRM_RECYCLE}{active}"),
         InlineKeyboardButton("❌ لا، إلغاء", callback_data=CallbackData.BACK)]
    ])
    
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def confirm_recycle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأكيد إعادة التدوير"""
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    active = int(query.data.split(":")[-1])
    
    # تنفيذ إعادة التدوير
    await db_reset_posts_to_unpublished(active, uid)
    
    text = f"♻️ **تم إعادة تدوير المنشورات بنجاح!**\n\n📡 تم إعادة تعيين جميع المنشورات إلى حالة غير منشورة."
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ]))

async def my_pending_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    unpublished = await db_get_user_unpublished_posts(uid)
    total = await db_get_user_total_posts(uid)
    text = get_text(uid, 'pending_stats').format(unpublished, total)
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]]))

async def my_full_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    channels = await db_get_user_channels_count(uid)
    total = await db_get_user_total_posts(uid)
    unpublished = await db_get_user_unpublished_posts(uid)
    groups = await db_get_user_groups_count(uid)
    auto = get_text(uid, 'auto_on') if await db_auto_status(uid) else get_text(uid, 'auto_off')
    text = get_text(uid, 'stats').format(channels, total, unpublished, groups, auto)
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]]))

async def my_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    groups = await db_get_user_groups(uid)
    if not groups:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
            [InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)],
            [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
        ])
        await safe_edit_markdown(query, "📭 لا توجد مجموعات مسجلة\n\nأضف البوت إلى مجموعة وستظهر هنا.", reply_markup=kb)
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
            InlineKeyboardButton("🗑️ حذف", callback_data=f"{CallbackData.DELETE_GROUP_PREFIX}{chat_id}")
        ])
        keyboard.append([InlineKeyboardButton("─" * 20, callback_data=CallbackData.NOOP)])
    keyboard.append([
        InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS),
        InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)
    ])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_markdown(
        query,
        "👥 **مجموعاتي**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر مجموعة للتحكم بها:\n\n✅ = نشطة  |  ⛔ = محظورة",
        reply_markup=reply_markup
    )

# ============================================================
# دوال مساعدة للتخزين المؤقت
# ============================================================
async def invalidate_user_cache(user_id: int):
    """إبطال التخزين المؤقت للمستخدم"""
    try:
        if user_id in _admin_cache:
            del _admin_cache[user_id]
    except:
        pass

async def delete_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, "❌ غير مصرح", show_alert=True)
        return
    async def _delete_group(conn):
        await conn.execute("DELETE FROM bot_groups WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM user_groups_link WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM group_security WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM chat_locks WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM moderation_log WHERE chat_id = ?", (chat_id,))
        await conn.commit()
    await execute_db(_delete_group)
    await query.edit_message_text("✅ تم حذف المجموعة من قاعدة البيانات.")
    await my_groups_callback(update, context)

async def group_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    async def _get_group_name(conn):
        cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        name = row[0] if row else str(chat_id)
        if len(name) > 50:
            name = name[:47] + "..."
        return name
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
    if settings.get('auto_penalty') == 'mute' and settings.get('auto_mute_duration'):
        minutes = settings.get('auto_mute_duration')
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
    await safe_edit_markdown(query, text, reply_markup=security_keyboard(chat_id))

async def security_links_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    settings['links'] = not settings['links']
    await db_set_security_settings(chat_id, **settings)
    await query.edit_message_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_mentions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    settings['mentions'] = not settings['mentions']
    await db_set_security_settings(chat_id, **settings)
    await query.edit_message_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_warn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    settings['warn'] = not settings['warn']
    await db_set_security_settings(chat_id, **settings)
    await query.edit_message_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_slowmode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    settings['slow_mode'] = not settings['slow_mode']
    await db_set_security_settings(chat_id, **settings)
    await query.edit_message_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_banned_words_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    await query.edit_message_text("🚫 إدارة الكلمات المحظورة للمجموعة", reply_markup=get_group_banned_words_keyboard(chat_id))

async def security_welcome_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    settings['welcome_enabled'] = not settings['welcome_enabled']
    await db_set_security_settings(chat_id, **settings)
    await query.edit_message_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_goodbye_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    settings['goodbye_enabled'] = not settings['goodbye_enabled']
    await db_set_security_settings(chat_id, **settings)
    await query.edit_message_text(get_text(uid, 'updated'))
    await group_settings_callback(update, context)

async def security_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    await query.message.delete()

async def security_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    context.user_data['state'] = 'waiting_for_group_security'
    await query.edit_message_text(get_text(uid, 'security_main'))

async def banned_words_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = f'waiting_for_group_banned_word_{chat_id}'
    await query.edit_message_text("➕ أرسل الكلمة التي تريد حظرها في هذه المجموعة")

async def banned_words_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    words = await db_get_banned_words(chat_id)
    if not words:
        await query.edit_message_text("📭 لا توجد كلمات محظورة في هذه المجموعة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]]))
        return
    msg = "🚫 **الكلمات المحظورة في هذه المجموعة:**\n\n"
    for w, by, at in words:
        msg += f"• `{w}` (أضيف بواسطة {by})\n"
    await safe_send_long_message(context.bot, query.message.chat_id, msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]]))
    await query.message.delete()

async def banned_words_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = f'waiting_for_remove_group_banned_word_{chat_id}'
    await query.edit_message_text("🗑️ أرسل الكلمة التي تريد حذفها من قائمة المحظورات")

async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    await safe_edit_markdown(query, get_text(uid, 'help'))

async def support_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP),
         InlineKeyboardButton("📋 تذكرتي", callback_data=CallbackData.SUPPORT_TICKET)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await query.edit_message_text(get_text(uid, 'support_welcome'), reply_markup=keyboard)
    context.user_data['support_mode'] = True

async def support_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.SUPPORT_MENU)]])
    await safe_edit_markdown(query, get_text(uid, 'support_help'), reply_markup=keyboard)

async def support_ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    ticket = await db_get_user_ticket(uid)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.SUPPORT_MENU)]])
    if ticket:
        ticket_num, status, created_at = ticket
        try:
            created_utc = datetime.fromisoformat(created_at)
            created_mecca = utc_to_mecca(created_utc)
            created_str = created_mecca.strftime("%Y-%m-%d %H:%M:%S")
        except:
            created_str = created_at
        text = f"📋 **تذكرتك #{ticket_num}**\n━━━━━━━━━━━━━━━━━━━━━━\n📅 تاريخ الإنشاء: {created_str}\n📌 الحالة: {'قيد المعالجة' if status == 'pending' else 'تم الرد'}\n\nسيتم الرد عليك في أقرب وقت ممكن."
    else:
        text = "📭 **لا توجد تذاكر**\n━━━━━━━━━━━━━━━━━━━━━━\nلم تقم بإرسال أي تذكرة دعم بعد.\nاستخدم الأمر /support لإنشاء تذكرة جديدة."
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def support_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await support_menu_callback(update, context)

async def trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if await db_has_used_trial(uid):
        await query.edit_message_text(get_text(uid, 'trial_used'))
        return
    if await db_has_active_subscription(uid):
        await query.edit_message_text(get_text(uid, 'already_subscribed'))
        return
    await db_activate_trial(uid)
    await query.edit_message_text(get_text(uid, 'trial'))
    await main_menu_callback(update, context)

async def subscribe_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if await db_has_active_subscription(uid):
        days = await db_get_subscription_days_left(uid)
        await query.edit_message_text(f"✅ اشتراكك مفعل، متبقي {days} يوم\nشكراً لدعمك ❤️")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_1), 
         InlineKeyboardButton("⭐ 2 يوم - 9 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_2)],
        [InlineKeyboardButton("⭐ شهر (30 يوم) - 50 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_30), 
         InlineKeyboardButton("⭐ 3 أشهر (90 يوم) - 120 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_90)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    text = get_text(uid, 'subscribe')
    await safe_edit_markdown(query, text, reply_markup=kb)

async def buy_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int, price: int, title: str):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    user_id = query.from_user.id
    try:
        await context.bot.send_invoice(chat_id=user_id, title=title, description=f"اشتراك {days} يوم", payload=f"sub_{days}_{price}", currency="XTR", prices=[LabeledPrice(label=f"اشتراك {days} يوم", amount=price)], need_name=False, need_phone_number=False, need_email=False, need_shipping_address=False, is_flexible=False)
    except Exception as e:
        if "Stars" in str(e):
            await query.edit_message_text("❌ الدفع بالنجوم غير مفعل حالياً، استخدم /trial")
        else:
            await query.edit_message_text(f"❌ خطأ: {str(e)[:100]}")

async def buy_subscription_1_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    await buy_subscription_callback(update, context, 1, 5, "اشتراك 1 يوم")

async def buy_subscription_2_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    await buy_subscription_callback(update, context, 2, 9, "اشتراك 2 يوم")

async def buy_subscription_30_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    await buy_subscription_callback(update, context, 30, 50, "اشتراك شهر")

async def buy_subscription_90_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    await buy_subscription_callback(update, context, 90, 120, "اشتراك 3 أشهر")

async def developer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    metrics_stats = metrics.get_stats()
    twofa_status = "✅ مفعلة" if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE else "❌ معطلة"
    text = f"""👑 **معلومات المطور**
━━━━━━━━━━━━━━━━━━━━━━
🤖 **البوت:** {BOT_NAME}
📦 **الإصدار:** 19.0.3 (المصحح بالكامل)
👨‍💻 **المطور:** @RelaxMgr

🔐 **الميزات الأمنية المتقدمة:**
• إعادة تدوير المنشورات تلقائياً مع تأكيد
• إحصائيات متقدمة للقنوات
• رسم بياني لنمو القناة
• نظام أمان متكامل للمجموعات
• دعم المالك المخفي
• نظام ترجمة ذكي
• دعم جميع أنواع الميديا
• واجهة ويب مع WebSocket
• نظام Rate Limiting متقدم
• مصادقة ثنائية (2FA)

⚡ **وضع السرعة:** {'مفعل' if not BATTERY_SAVER_MODE else 'معطل'}

📊 **إحصائيات الأداء:**
• وقت التشغيل: {int(metrics_stats['uptime'] / 3600)} ساعة
• إجمالي الأوامر: {metrics_stats['total_commands']}
• متوسط وقت الاستجابة: {metrics_stats['avg_response_time']:.2f} ثانية

━━━━━━━━━━━━━━━━━━━━━━
📞 **طرق التواصل:**
✅ **تيليجرام:** @RelaxMgr
✅ **البوت:** @{BOT_USERNAME}"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 تواصل مع المطور", url=f"https://t.me/RelaxMgr")],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    updates_channel = await db_get_updates_channel()
    text = get_text(uid, 'updates_text')
    keyboard = InlineKeyboardMarkup([])
    if updates_channel:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 قناة التحديثات", url=f"https://t.me/{updates_channel}")],
            [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
        ])
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
        ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def referral_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    referral_code = await db_get_referral_code(uid)
    if not referral_code:
        referral_code = await db_generate_referral_code(uid)
    stats = await db_get_referral_stats(uid)
    settings = await db_get_referral_settings()
    reward_days = int(settings.get('reward_days_per_referral', '3'))
    welcome_points = int(settings.get('welcome_bonus_points', '10'))
    text = get_text(uid, 'referral_title').format(referral_code, BOT_USERNAME, referral_code, stats['total_referrals'], stats['available_days'], reward_days, welcome_points)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(uid, 'copy_link'), callback_data=f"{CallbackData.REFERRAL_COPY_LINK_PREFIX}{referral_code}"),
         InlineKeyboardButton(get_text(uid, 'claim_reward'), callback_data=CallbackData.REFERRAL_CLAIM_REWARD)],
        [InlineKeyboardButton(get_text(uid, 'referral_list'), callback_data=CallbackData.REFERRAL_LIST),
         InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def referral_copy_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    referral_code = query.data.split(":")[-1]
    await safe_edit_markdown(query, f"🔗 **رابط الإحالة الخاص بك:**\n`https://t.me/{BOT_USERNAME}?start=ref_{referral_code}`\n\nيمكنك الضغط مع الاستمرار على الرابط لنسخه.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]]))

async def referral_claim_reward_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    stats = await db_get_referral_stats(uid)
    if stats['available_days'] <= 0:
        await safe_edit_markdown(query, get_text(uid, 'no_reward_available'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]]))
        return
    claimed = await db_claim_referral_reward(uid)
    await safe_edit_markdown(query, get_text(uid, 'reward_claimed').format(claimed), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]]))

async def referral_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    async def _get_referrals(conn):
        cur = await conn.execute("SELECT r.referred_id, r.referred_at, r.is_rewarded, u.first_name, u.username FROM referrals r LEFT JOIN users_cache u ON r.referred_id = u.user_id WHERE r.referrer_id = ? ORDER BY r.referred_at DESC LIMIT 20", (uid,))
        return await cur.fetchall()
    referrals = await execute_db(_get_referrals)
    if not referrals:
        await safe_edit_markdown(query, get_text(uid, 'no_referrals'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]]))
        return
    text = f"📊 **{get_text(uid, 'referral_list')}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
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
        [InlineKeyboardButton(get_text(uid, 'claim_reward'), callback_data=CallbackData.REFERRAL_CLAIM_REWARD)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def reminder_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    settings = await db_get_user_reminder_settings(uid)
    status_sub = "🟢 مفعل" if settings['subscription_reminder'] else "🔴 معطل"
    status_daily = "🟢 مفعل" if settings['daily_stats_reminder'] else "🔴 معطل"
    status_weekly = "🟢 مفعل" if settings['weekly_report'] else "🔴 معطل"
    text = get_text(uid, 'reminder_title').format(status_sub, status_daily, status_weekly, settings['reminder_days_before'])
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(uid, 'reminder_sub'), callback_data=CallbackData.REMINDER_TOGGLE_SUB),
         InlineKeyboardButton(get_text(uid, 'reminder_daily'), callback_data=CallbackData.REMINDER_TOGGLE_DAILY)],
        [InlineKeyboardButton(get_text(uid, 'reminder_weekly'), callback_data=CallbackData.REMINDER_TOGGLE_WEEKLY),
         InlineKeyboardButton(get_text(uid, 'reminder_days_btn'), callback_data=CallbackData.REMINDER_SET_DAYS)],
        [InlineKeyboardButton(get_text(uid, 'reminder_lang_btn'), callback_data=CallbackData.REMINDER_SET_LANG),
         InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def reminder_toggle_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    settings = await db_get_user_reminder_settings(uid)
    await db_update_reminder_settings(uid, subscription_reminder=not settings['subscription_reminder'])
    await reminder_menu_callback(update, context)

async def reminder_toggle_daily_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    settings = await db_get_user_reminder_settings(uid)
    await db_update_reminder_settings(uid, daily_stats_reminder=not settings['daily_stats_reminder'])
    await reminder_menu_callback(update, context)

async def reminder_toggle_weekly_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    settings = await db_get_user_reminder_settings(uid)
    await db_update_reminder_settings(uid, weekly_report=not settings['weekly_report'])
    await reminder_menu_callback(update, context)

async def reminder_set_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    context.user_data['state'] = 'waiting_for_reminder_days'
    await query.edit_message_text("⏰ **عدد أيام التذكير**\n\nأرسل عدد الأيام التي تريد أن يتم تذكيرك بها قبل انتهاء الاشتراك (1-10 أيام):", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REMINDER_MENU)]]))

async def reminder_set_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("العربية 🇸🇦", callback_data=f"{CallbackData.REMINDER_LANG_PREFIX}ar"),
         InlineKeyboardButton("English 🇬🇧", callback_data=f"{CallbackData.REMINDER_LANG_PREFIX}en")],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REMINDER_MENU)]
    ])
    await query.edit_message_text("🌐 **اختر لغة الإشعارات:**", reply_markup=keyboard)

async def reminder_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    lang = query.data.split(":")[-1]
    await db_update_reminder_settings(uid, notification_lang=lang)
    await reminder_menu_callback(update, context)

async def translation_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    current_lang = await get_user_translation_language(uid)
    if current_lang == 'off':
        status_text = get_text(uid, 'translation_status_off')
    elif current_lang == 'ar':
        status_text = get_text(uid, 'translation_status_on').format("العربية")
    elif current_lang == 'en':
        status_text = get_text(uid, 'translation_status_on').format("English")
    elif current_lang == 'fr':
        status_text = get_text(uid, 'translation_status_on').format("Français")
    elif current_lang == 'tr':
        status_text = get_text(uid, 'translation_status_on').format("Türkçe")
    elif current_lang == 'zh':
        status_text = get_text(uid, 'translation_status_on').format("中文")
    elif current_lang == 'ru':
        status_text = get_text(uid, 'translation_status_on').format("Русский")
    else:
        status_text = get_text(uid, 'translation_status_off')
    text = f"""🌐 **{get_text(uid, 'translation_settings')}**
━━━━━━━━━━━━━━━━━━━━━━
📌 **الحالة:** {status_text}
{get_text(uid, 'translation_how_it_works')}
━━━━━━━━━━━━━━━━━━━━━━
{get_text(uid, 'translation_choose')}"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(uid, 'translation_off'), callback_data=CallbackData.TRANSLATION_OFF)],
        [InlineKeyboardButton("🇸🇦 العربية", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ar"),
         InlineKeyboardButton("🇬🇧 English", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}en")],
        [InlineKeyboardButton("🇫🇷 Français", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}fr"),
         InlineKeyboardButton("🇹🇷 Türkçe", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}tr")],
        [InlineKeyboardButton("🇨🇳 中文", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}zh"),
         InlineKeyboardButton("🇷🇺 Русский", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ru")],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def translation_off_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    await set_user_translation_language(uid, 'off')
    await query.edit_message_text(get_text(uid, 'translation_disabled'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]]))

async def translation_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    lang = query.data.split(":")[-1]
    await set_user_translation_language(uid, lang)
    lang_names = {'ar': 'العربية', 'en': 'English', 'fr': 'Français', 'tr': 'Türkçe', 'zh': '中文', 'ru': 'Русский'}
    lang_name = lang_names.get(lang, lang)
    await query.edit_message_text(get_text(uid, 'translation_enabled').format(lang_name), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]]))

async def handle_text_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if query.data == CallbackData.RANK:
        data = await get_rank(uid)
        points = data['points']
        level = data['level']
        next_points = LEVEL_REQUIREMENTS.get(level + 1, points)
        points_needed = next_points - points if next_points > points else 0
        text = f"📊 **رتبتك الحالية**\n━━━━━━━━━━━━━━\n👤 {query.from_user.first_name}\n⭐ **المستوى:** {level}\n📈 **النقاط:** {points}\n📌 **المتبقي للمستوى التالي:** {points_needed}"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    elif query.data == CallbackData.TOP:
        top_users = await get_top_users(10)
        if not top_users:
            msg = "📭 لا توجد نقاط مسجدة بعد."
            await query.edit_message_text(msg)
            return
        text = "🏆 **أفضل 10 مستخدمين**\n━━━━━━━━━━━━━━\n"
        for idx, (uid_user, points, level) in enumerate(top_users, 1):
            try:
                user = await context.bot.get_chat(uid_user)
                name = user.first_name or str(uid_user)
            except:
                name = str(uid_user)
            text += f"{idx}. {name} → المستوى {level} ({points} نقطة)\n"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    elif query.data == CallbackData.SCHEDULE_POST:
        context.user_data['state'] = 'waiting_for_schedule_post'
        await query.edit_message_text("📝 **جدولة منشور جديد**\n\nأرسل المنشور بالصيغة التالية:\n`YYYY-MM-DD HH:MM نص المنشور`\n\nمثال: `2024-12-31 20:00 مرحباً بالجميع!`\n\n🕐 الوقت بتوقيت مكة المكرمة", parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]]))
    elif query.data == CallbackData.LANGUAGE:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("العربية 🇸🇦", callback_data=CallbackData.LANG_AR), 
             InlineKeyboardButton("English 🇬🇧", callback_data=CallbackData.LANG_EN)],
            [InlineKeyboardButton("Français 🇫🇷", callback_data=CallbackData.LANG_FR), 
             InlineKeyboardButton("Türkçe 🇹🇷", callback_data=CallbackData.LANG_TR)],
            [InlineKeyboardButton("中文 🇨🇳", callback_data=CallbackData.LANG_ZH), 
             InlineKeyboardButton("Русский 🇷🇺", callback_data=CallbackData.LANG_RU)],
            [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
        ])
        await query.edit_message_text(get_text(uid, 'welcome'), reply_markup=keyboard)

async def security_select_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        error_text = """❌ **غير مصرح**

أنت لست مشرفاً في هذه المجموعة، أو البوت ليس مشرفاً.

تأكد من:
1. أن البوت مشرف في المجموعة
2. أن لديك صلاحيات مشرف في المجموعة"""
        await safe_edit_markdown(query, error_text)
        return
    settings = await db_get_security_settings(chat_id)
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
⏱️ وضع بطيء: {'✅' if settings['slow_mode'] else '❌'}
🎯 ترحيب: {'✅' if settings['welcome_enabled'] else '❌'}
👋 وداع: {'✅' if settings['goodbye_enabled'] else '❌'}
🔊 تحذير: {'✅' if settings['warn'] else '❌'}
━━━━━━━━━━━━━━━━━━━━━━
⚖️ **العقوبة التلقائية:** {'طرد' if settings.get('auto_penalty') == 'kick' else 'حظر' if settings.get('auto_penalty') == 'ban' else 'كتم' if settings.get('auto_penalty') == 'mute' else 'لا شيء'}
━━━━━━━━━━━━━━━━━━━━━━
💡 **اختر الإجراء المناسب:**"""
    await safe_edit_markdown(query, text, reply_markup=security_keyboard(chat_id))

async def security_refresh_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
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
        await safe_edit_markdown(query, text, reply_markup=keyboard)
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
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def advanced_actions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if chat_id == 0:
        await query.edit_message_text("⚠️ يرجى اختيار مجموعة أولاً باستخدام أمر /security")
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    await safe_edit_markdown(query, "🛠️ **الإجراءات المتقدمة للمجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الإجراء المطلوب:", reply_markup=get_advanced_group_actions_keyboard(chat_id))

async def group_action_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = f'waiting_for_ban_user_{chat_id}'
    await safe_edit_markdown(query, "🚫 **حظر مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /ban\n\nيمكنك إضافة سبب بعد المعرف: `/ban 123456789 السبب`")

async def group_action_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    await safe_edit_markdown(query, "🔇 **كتم مستخدم**\n\nاختر مدة الكتم:", reply_markup=get_advanced_mute_duration_keyboard(chat_id))

async def advanced_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    parts = query.data.split(":")
    if len(parts) == 3:
        minutes = int(parts[1])
        chat_id = int(parts[2])
        uid = query.from_user.id
        if not await is_authorized_in_group(context.bot, chat_id, uid):
            await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
            return
        context.user_data['mute_minutes'] = minutes
        context.user_data['state'] = f'waiting_for_mute_user_{chat_id}'
        if minutes == 0:
            await safe_edit_markdown(query, "🔇 **كتم دائم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`")
        elif minutes < 60:
            await safe_edit_markdown(query, f"🔇 **كتم {minutes} دقيقة**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`")
        elif minutes < 1440:
            await safe_edit_markdown(query, f"🔇 **كتم {minutes // 60} ساعة**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`")
        else:
            await safe_edit_markdown(query, f"🔇 **كتم {minutes // 1440} يوم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute\n\nيمكنك إضافة سبب: `/mute 123456789 السبب`")

async def group_action_warn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = f'waiting_for_warn_user_{chat_id}'
    await safe_edit_markdown(query, "⚠️ **تحذير مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /warn\n\nيمكنك إضافة سبب: `/warn 123456789 السبب`\n\n📌 بعد 3 تحذيرات يتم حظر المستخدم تلقائياً")

async def group_action_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = f'waiting_for_kick_user_{chat_id}'
    await safe_edit_markdown(query, "👢 **طرد مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /kick\n\nيمكنك إضافة سبب: `/kick 123456789 السبب`")

async def group_action_restrict_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = f'waiting_for_restrict_user_{chat_id}'
    await safe_edit_markdown(query, "🔒 **تقييد مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /restrict\n\n📌 التقييد يمنع المستخدم من إرسال الصور والفيديوهات والملفات")

async def group_action_pin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = f'waiting_for_pin_message_{chat_id}'
    await safe_edit_markdown(query, "📌 **تثبيت رسالة**\n\nقم بالرد على الرسالة التي تريد تثبيتها ثم أرسل /pin")

async def group_action_log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    text = await get_moderation_log(chat_id, 20)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def group_action_unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = f'waiting_for_unban_user_{chat_id}'
    await safe_edit_markdown(query, "🔓 **إلغاء حظر مستخدم**\n\nأرسل معرف المستخدم (user_id) لإلغاء حظره:\n`/unban 123456789`")

async def penalty_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    await query.edit_message_text("⚖️ **اختر العقوبة التلقائية:**\n\nسيتم تطبيق هذه العقوبة عند مخالفة قواعد الحماية:", reply_markup=penalty_keyboard(chat_id))

async def penalty_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    await db_set_security_settings(chat_id, auto_penalty='kick')
    await query.edit_message_text("✅ تم تعيين العقوبة التلقائية إلى: **طرد**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]]))

async def penalty_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    await db_set_security_settings(chat_id, auto_penalty='ban')
    await query.edit_message_text("✅ تم تعيين العقوبة التلقائية إلى: **حظر**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]]))

async def penalty_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['penalty_chat_id'] = chat_id
    await query.edit_message_text("🔇 **اختر مدة الكتم:**", reply_markup=mute_duration_keyboard(chat_id))

async def penalty_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    data_parts = query.data.split(":")
    if len(data_parts) == 3:
        duration = data_parts[1]
        chat_id = int(data_parts[2])
        uid = query.from_user.id
        if not await is_authorized_in_group(context.bot, chat_id, uid):
            await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
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
        await query.edit_message_text(f"✅ تم تعيين العقوبة التلقائية إلى: **كتم {text}**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]]))

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    await safe_edit_markdown(query, get_text(uid, 'admin_panel'), reply_markup=get_admin_keyboard(uid))

async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    users = await db_get_all_users()
    if not users:
        await query.edit_message_text("📭 لا يوجد مستخدمون مسجلون.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))
        return
    text = "👥 **قائمة المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, banned in users[:50]:
        status = "🚫 محظور" if banned else "✅ نشط"
        text += f"• `{user_id}` - {status}\n"
    if len(users) > 50:
        text += f"\nو {len(users)-50} آخرون..."
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_banned_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    users = await db_get_all_users()
    banned_users = [u for u in users if u[1] == 1]
    if not banned_users:
        await query.edit_message_text("📭 لا يوجد مستخدمون محظورون.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))
        return
    text = "🚫 **المستخدمون المحظورون**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, _ in banned_users[:50]:
        text += f"• `{user_id}`\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_USERS)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_unban_all_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    async def _unban_all(conn):
        await conn.execute("UPDATE users SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_all)
    await query.edit_message_text("✅ تم إلغاء حظر جميع المستخدمين.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    channels = await db_get_all_user_channels_no_limit()
    if not channels:
        await query.edit_message_text("📭 لا توجد قنوات مسجلة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))
        return
    text = "📡 **قنوات المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for idx, (user_id, ch_id, ch_tele, ch_name, banned) in enumerate(channels[:100], 1):
        status = "⛔" if banned else "✅"
        text += f"{idx}. {status} `{ch_name}`\n   👤 المستخدم: `{user_id}`\n   🆔 القناة: `{ch_tele}`\n\n"
    if len(channels) > 100:
        text += f"\nو {len(channels)-100} قناة أخرى..."
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_banned_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    channels = await db_all_users_channels(only_banned=True, limit=500)
    if not channels:
        await query.edit_message_text("📭 لا توجد قنوات محظورة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))
        return
    text = "⛔ **قنوات المستخدمين المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, ch_id, ch_tele, ch_name, banned in channels[:50]:
        text += f"• المستخدم: `{user_id}` | القناة: {ch_name} (`{ch_tele}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ تنشيط الكل", callback_data=CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_activate_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    async def _activate_all(conn):
        await conn.execute("UPDATE user_channels SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_activate_all)
    await query.edit_message_text("✅ تم إلغاء حظر جميع قنوات المستخدمين.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    groups = await db_get_all_groups(only_banned=False)
    if not groups:
        await query.edit_message_text("📭 لا توجد مجموعات مسجلة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))
        return
    text = "👥 **المجموعات المسجلة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for chat_id, chat_name, username, added_by, added_at, banned in groups[:50]:
        text += f"• {chat_name} (ID: `{chat_id}`)\n  أضيف بواسطة: `{added_by}`\n"
    if len(groups) > 50:
        text += f"\nو {len(groups)-50} أخرى..."
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_banned_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    groups = await db_get_all_groups(only_banned=True)
    if not groups:
        await query.edit_message_text("📭 لا توجد مجموعات محظورة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))
        return
    text = "🚷 **المجموعات المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for chat_id, chat_name, username, added_by, added_at, banned in groups[:50]:
        text += f"• {chat_name} (ID: `{chat_id}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_GROUPS)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_unban_all_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    async def _unban_groups(conn):
        await conn.execute("UPDATE bot_groups SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_groups)
    await query.edit_message_text("✅ تم إلغاء حظر جميع المجموعات.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    channels = await db_get_all_bot_channels(only_banned=False)
    if not channels:
        await query.edit_message_text("📭 لا توجد قنوات أضيف إليها البوت.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))
        return
    text = "📢 **قنوات البوت**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for channel_id, channel_name, added_by, added_at, banned in channels[:50]:
        text += f"• {channel_name} (ID: `{channel_id}`)\n  أضيف بواسطة: `{added_by}`\n"
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_banned_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    channels = await db_get_all_bot_channels(only_banned=True)
    if not channels:
        await query.edit_message_text("📭 لا توجد قنوات بوت محظورة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))
        return
    text = "🚫 **قنوات البوت المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for channel_id, channel_name, added_by, added_at, banned in channels[:50]:
        text += f"• {channel_name} (ID: `{channel_id}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_BOT_CHANNELS)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_unban_all_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    async def _unban_bot_channels(conn):
        await conn.execute("UPDATE bot_channels SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_bot_channels)
    await query.edit_message_text("✅ تم إلغاء حظر جميع قنوات البوت.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_monitor_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
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
    text = (
        f"📂 **مراقبة المستخدمين**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **إجمالي المستخدمين:** `{total_users}`\n"
        f"✅ **النشطاء:** `{active_users}`\n"
        f"🚫 **المحظورون:** `{banned_users}`\n"
        f"👑 **المشرفون:** `{admin_count}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 **قنوات المستخدمين:** `{channels_count}`\n"
        f"👥 **المجموعات المسجلة:** `{groups_count}`\n"
    )
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_add_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = 'waiting_for_admin_id_add'
    await safe_edit_markdown(query, get_text(uid, 'enter_admin_id'))

async def admin_remove_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    admins = await get_all_bot_admins()
    if not admins:
        await query.edit_message_text(get_text(uid, 'no_admins'))
        return
    text = "👑 المشرفون الحاليون:\n"
    for a in admins:
        text += f"- {a}\n"
    text += "\n" + get_text(uid, 'enter_remove_admin_id')
    context.user_data['state'] = 'waiting_for_admin_id_remove'
    await safe_edit_markdown(query, text)

async def admin_ram_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    ram = metrics.get_ram_usage()
    text = f"🖥️ **حالة الرام**\n━━━━━━━━━━━━━━━━━━━━━━\n• الإجمالي: {ram['total']} GB\n• المستخدم: {ram['used']} GB\n• النسبة: {ram['percent']}%"
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    total, banned, posts, groups, channels = await db_stats()
    text = f"📊 **إحصائيات عامة**\n━━━━━━━━━━━━━━━━━━━━━━\n• المستخدمين: {total}\n• المحظورين: {banned}\n• المنشورات غير المنشورة: {posts}\n• المجموعات: {groups}\n• قنوات المستخدمين: {channels}"
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_metrics_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    stats = metrics.get_stats()
    ram = metrics.get_ram_usage()
    text = f"""📈 **مقاييس الأداء**
━━━━━━━━━━━━━━━━━━━━━━
⏱️ **وقت التشغيل:** {int(stats['uptime'] / 3600)} ساعة {int((stats['uptime'] % 3600) / 60)} دقيقة
📊 **إجمالي الأوامر:** {stats['total_commands']}
⚡ **متوسط وقت الاستجابة:** {stats['avg_response_time']:.3f} ثانية
🖥️ **حالة النظام:**
• إجمالي الرام: {ram['total']} GB
• المستخدم: {ram['used']} GB
• النسبة: {ram['percent']}%
📋 **الأخطاء المسجلة:**
{chr(10).join([f'• {k}: {v}' for k, v in stats['errors'].items()]) if stats['errors'] else '• لا توجد أخطاء'}"""
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    try:
        await create_backup()
        await query.edit_message_text("✅ تم إنشاء نسخة احتياطية مشفرة جديدة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))
    except Exception as e:
        await query.edit_message_text(f"❌ فشل إنشاء النسخة: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_restore_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    backups = await list_backups()
    if not backups:
        await query.edit_message_text(get_text(uid, 'no_backups'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))
        return
    kb = []
    for b in backups[:10]:
        kb.append([InlineKeyboardButton(b.name, callback_data=f"{CallbackData.ADMIN_RESTORE_BACKUP_SELECT_PREFIX}{b.name}")])
    kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)])
    await query.edit_message_text(get_text(uid, 'select_backup'), reply_markup=InlineKeyboardMarkup(kb))

async def admin_restore_backup_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    backup_name = query.data.split(":")[-1]
    backup_path = BACKUP_DIR / backup_name
    try:
        await restore_backup(backup_path)
        await query.edit_message_text("✅ تم استعادة النسخة الاحتياطية المشفرة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))
    except Exception as e:
        await query.edit_message_text(f"❌ فشل الاستعادة: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_backup_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    async def _get_auto_backup(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='auto_backup'")
        row = await cur.fetchone()
        return row and row[0] == '1'
    auto = await execute_db(_get_auto_backup)
    status = "مفعل" if auto else "معطل"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تبديل النسخ التلقائي", callback_data=CallbackData.ADMIN_TOGGLE_AUTO_BACKUP)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, f"⚙️ **إعدادات النسخ الاحتياطي**\n━━━━━━━━━━━━━━━━━━━━━━\n• النسخ التلقائي: {status}\n• تشفير النسخ: ✅ مفعل\n• الحد الأقصى للنسخ: {MAX_BACKUPS}\n\nيمكنك تبديل الحالة بالزر أدناه.", reply_markup=kb)

async def admin_toggle_auto_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    async def _get_auto_backup(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='auto_backup'")
        row = await cur.fetchone()
        return row and row[0] == '1'
    auto = await execute_db(_get_auto_backup)
    new_auto = not auto
    async def _set_auto_backup(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('auto_backup', ?)", ('1' if new_auto else '0',))
        await conn.commit()
    await execute_db(_set_auto_backup)
    status = "مفعل" if new_auto else "معطل"
    await query.edit_message_text(f"✅ تم تغيير إعداد النسخ التلقائي إلى: {status}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_BACKUP_SETTINGS)]]))

async def admin_change_interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    current = await db_get_publish_interval()
    current_min = current // 60
    context.user_data['state'] = 'admin_waiting_for_interval'
    await safe_edit_markdown(query, 
        f"⏱️ **وقت النشر العام الحالي:** {current_min} دقيقة\n\n"
        f"📌 **ملاحظة:** هذا الإعداد يؤثر على الفاصل الزمني بين دورات النشر.\n"
        f"أرسل العدد الجديد من الدقائق (الحد الأدنى 1 دقيقة، الحد الأقصى 1440 دقيقة = 24 ساعة):")

async def admin_send_update_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = 'waiting_for_update_text'
    await safe_edit_markdown(query, "📢 أرسل نص التحديث الذي تريد نشره في قناة التحديثات:")

async def admin_set_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = 'waiting_for_update_channel'
    await safe_edit_markdown(query, "⚙️ أرسل معرف قناة التحديثات (مثال: @channel_username أو -1001234567890):")

async def admin_updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    channel = await db_get_updates_channel()
    text = f"📢 **قناة التحديثات الحالية:** @{channel}\n\nيمكنك تغييرها باستخدام زر '⚙️ قناة التحديثات'"
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_force_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    enabled = await db_get_force_subscribe_status()
    new_status = not enabled
    await db_set_force_subscribe_status(new_status)
    status_text = "مفعل" if new_status else "معطل"
    await query.edit_message_text(f"✅ تم {status_text} الاشتراك الإجباري.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_set_force_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = 'admin_waiting_for_force_channel'
    await safe_edit_markdown(query, "⚙️ أرسل معرف قناة الاشتراك الإجباري (مثال: @channel_username):")

async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = 'waiting_for_broadcast'
    await safe_edit_markdown(query, "📨 أرسل النص الذي تريد إرساله إلى جميع المستخدمين:")

async def admin_confirm_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    broadcast_text = context.user_data.get('broadcast_text', '')
    if not broadcast_text:
        await query.edit_message_text("❌ لا يوجد نص للإرسال")
        return
    dangerous_patterns = [r'<script', r'javascript:', r'data:', r'vbscript:', r'<\?php', r'<%', r'{%']
    for pattern in dangerous_patterns:
        if re.search(pattern, broadcast_text, re.IGNORECASE):
            await query.edit_message_text("❌ النص يحتوي على كود ضار! تم منع الإرسال.")
            return
    if len(broadcast_text) > 4000:
        await query.edit_message_text("❌ النص طويل جداً (الحد الأقصى 4000 حرف)")
        return
    await query.edit_message_text("📨 جاري الإرسال... يرجى الانتظار")
    async def _get_active_users(conn):
        cur = await conn.execute("SELECT user_id FROM users WHERE banned = 0")
        return [row[0] for row in await cur.fetchall()]
    users = await execute_db(_get_active_users)
    sent = 0
    failed = 0
    if not users:
        await query.edit_message_text("📭 لا يوجد مستخدمين نشطين لإرسال الرسالة لهم.")
        return
    for i, user_id in enumerate(users):
        try:
            await asyncio.sleep(random.uniform(0.5, 1.5))
            await safe_send_markdown(context.bot, user_id, broadcast_text)
            sent += 1
        except Exception as e:
            failed += 1
            logger.warning(f"فشل إرسال broadcast للمستخدم {user_id}: {e}")
    context.user_data.pop('broadcast_text', None)
    context.user_data.pop('state', None)
    await query.edit_message_text(f"✅ **تم إرسال الرسالة**\n\n📨 تم الإرسال إلى: {sent} مستخدم\n❌ فشل الإرسال إلى: {failed} مستخدم", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_support_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    tickets = await db_get_all_tickets(limit=20)
    if not tickets:
        await query.edit_message_text("📭 لا توجد تذاكر دعم مسجلة")
        return
    text = "📋 **تذاكر الدعم**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for tid, uid_u, username, msg, ticket_num, status, created_at in tickets:
        try:
            created_utc = datetime.fromisoformat(created_at)
            created_mecca = utc_to_mecca(created_utc)
            created_str = created_mecca.strftime("%Y-%m-%d %H:%M")
        except:
            created_str = created_at
        status_icon = "🟡" if status == "pending" else "🟢"
        msg_preview = msg[:40] + "..." if len(msg) > 40 else msg
        text += f"\n{status_icon} #{ticket_num} | 👤 {username}\n🆔 `{uid_u}` | 📅 {created_str}\n📝 {msg_preview}\n💡 `/support_reply {uid_u} نص الرد`\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_delete_all_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    confirm_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، احذف الكل", callback_data=CallbackData.ADMIN_CONFIRM_DELETE_TICKETS),
         InlineKeyboardButton("❌ لا، إلغاء", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await query.edit_message_text(get_text(uid, 'confirm_delete_tickets'), reply_markup=confirm_kb)

async def admin_confirm_delete_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    count = await db_delete_all_tickets()
    await query.edit_message_text(get_text(uid, 'tickets_deleted').format(count), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_manage_sendcode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    allowed_user = await db_get_allowed_sendcode_user()
    if allowed_user:
        current_text = get_text(uid, 'current_allowed_user').format(f"`{allowed_user}`")
    else:
        current_text = get_text(uid, 'current_allowed_user').format(get_text(uid, 'no_allowed_user'))
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(uid, 'set_new_sendcode_user'), callback_data=CallbackData.ADMIN_SET_SENDCODE_USER)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit_markdown(query, current_text, reply_markup=keyboard)

async def admin_set_sendcode_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = 'waiting_for_sendcode_user'
    await query.edit_message_text("➕ أرسل معرف المستخدم (user_id) الذي تريد منحه صلاحية استخدام أمر /sendcode:")

async def admin_show_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    log_ch = await db_get_log_channel_id()
    if log_ch:
        await safe_edit_markdown(query, f"📋 **قناة التقارير الحالية:**\n`{log_ch}`\n\nيمكنك تغييرها باستخدام الأمر `/set_log_channel`\nأو الضغط على زر 'تعيين قناة التقارير'.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))
    else:
        await query.edit_message_text("📋 **لم يتم تعيين قناة تقارير بعد.**\nاستخدم الأمر `/set_log_channel` أو زر 'تعيين قناة التقارير' لتعيينها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_set_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = 'waiting_for_log_channel'
    await query.edit_message_text("📢 **تعيين قناة التقارير**\n\nأرسل معرف القناة (ID) أو معرف المستخدم (@username) للقناة التي تريد استقبال التقارير فيها.\n\nمثال: `-1001234567890` أو `@channel_username`\n\n⚠️ تأكد من أن البوت مشرف في القناة ولديه صلاحية إرسال الرسائل.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]]))

async def admin_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    await query.edit_message_text("💬 **إدارة ردود المجموعة**", reply_markup=get_replies_keyboard())

async def admin_add_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = 'admin_waiting_for_keyword'
    await query.edit_message_text("📝 **إضافة رد تلقائي**\n\nأرسل الكلمة المفتاحية (مثل: مرحبا، السلام عليكم، كيف حالك):")

async def admin_list_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    replies = await db_get_all_replies()
    if not replies:
        await query.edit_message_text("📭 لا توجد ردود مسجلة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_REPLIES)]]))
        return
    text = "💬 **قائمة الردود التلقائية**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for kw, rep in replies[:30]:
        short_rep = rep[:40] + "..." if len(rep) > 40 else rep
        text += f"• **{kw}** → {short_rep}\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ حذف {kw}", callback_data=f"{CallbackData.ADMIN_DEL_REPLY_PREFIX}{kw}")])
    keyboard.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_REPLIES)])
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_del_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    if query.data.startswith(CallbackData.ADMIN_DEL_REPLY_PREFIX):
        keyword = query.data.replace(CallbackData.ADMIN_DEL_REPLY_PREFIX, "")
        if await db_del_reply(keyword):
            await safe_query_answer(query, f"✅ تم حذف رد {keyword}", show_alert=True)
        else:
            await safe_query_answer(query, f"❌ الكلمة {keyword} غير موجودة", show_alert=True)
        await admin_list_replies_callback(update, context)
    else:
        context.user_data['state'] = 'admin_del_reply'
        await query.edit_message_text("🗑️ **حذف رد تلقائي**\n\nأرسل الكلمة المفتاحية لحذف ردها:")

async def admin_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    await query.edit_message_text("🚫 **إدارة الكلمات المحظورة على مستوى البوت (لجميع المجموعات)**", reply_markup=get_banned_words_admin_keyboard())

async def admin_add_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = 'waiting_for_global_banned_word'
    await query.edit_message_text("➕ أرسل الكلمة التي تريد حظرها على مستوى البوت:")

async def admin_list_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    words = await db_get_banned_words(-1)
    if not words:
        await query.edit_message_text("📭 لا توجد كلمات محظورة عامة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_BANNED_WORDS)]]))
        return
    text = "🚫 **الكلمات المحظورة عامة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for w, by, at in words[:20]:
        text += f"• `{w}` (أضيف بواسطة {by})\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ حذف {w}", callback_data=f"{CallbackData.ADMIN_DEL_BANNED_WORD_PREFIX}{w}")])
    keyboard.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_BANNED_WORDS)])
    await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_remove_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = 'waiting_for_remove_global_banned_word'
    await query.edit_message_text("🗑️ أرسل الكلمة التي تريد حذفها من الكلمات المحظورة العامة:")

async def admin_del_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    word = query.data.replace(CallbackData.ADMIN_DEL_BANNED_WORD_PREFIX, "")
    async def _remove_global_word(conn):
        await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
        await conn.commit()
    await execute_db(_remove_global_word)
    await safe_query_answer(query, f"✅ تم حذف {word}", show_alert=True)
    await admin_list_banned_words_callback(update, context)

async def lang_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    lang_map = {
        CallbackData.LANG_AR: 'ar',
        CallbackData.LANG_EN: 'en',
        CallbackData.LANG_FR: 'fr',
        CallbackData.LANG_TR: 'tr',
        CallbackData.LANG_ZH: 'zh',
        CallbackData.LANG_RU: 'ru'
    }
    lang = lang_map.get(query.data, 'ar')
    await set_user_language(uid, lang)
    await safe_query_answer(query, get_text(uid, 'lang_set'))
    kb, _, _ = await get_main_keyboard(uid)
    await safe_edit_markdown(query, "🌿 القائمة الرئيسية", reply_markup=kb)

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    auto = await db_auto_status(uid)
    btn = get_text(uid, 'disabled') if auto else get_text(uid, 'enabled')
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{btn} النشر التلقائي", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    await query.edit_message_text(get_text(uid, 'settings'), reply_markup=kb)

async def toggle_auto_publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    cur = await db_auto_status(uid)
    await db_set_auto(uid, not cur)
    status = get_text(uid, 'enabled') if not cur else get_text(uid, 'disabled')
    await query.edit_message_text(get_text(uid, 'auto_toggled').format(status))
    await main_menu_callback(update, context)

async def schedule_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    parts = query.data.split(":")
    if len(parts) >= 3:
        ch_db_id = int(parts[-1])
    else:
        ch_db_id = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not ch_db_id:
        await query.edit_message_text("⚠️ يرجى اختيار قناة أولاً")
        return
    schedule = await db_get_schedule(ch_db_id)
    if schedule['type'] == 'interval_minutes':
        txt = get_text(uid, 'interval_minutes').format(schedule['interval_minutes'])
    elif schedule['type'] == 'interval_hours':
        txt = get_text(uid, 'interval_hours').format(schedule['interval_hours'])
    elif schedule['type'] == 'interval_days':
        txt = get_text(uid, 'interval_days').format(schedule['interval_days'])
    elif schedule['type'] == 'days':
        days = parse_days_of_week_safe(schedule['days_of_week'])
        day_names = [get_text(uid, 'monday'), get_text(uid, 'tuesday'), get_text(uid, 'wednesday'), 
                     get_text(uid, 'thursday'), get_text(uid, 'friday'), get_text(uid, 'saturday'), 
                     get_text(uid, 'sunday')]
        txt = get_text(uid, 'days_week').format(', '.join([day_names[d] for d in days]) if days else get_text(uid, 'nothing'))
    else:
        dates = parse_dates_safe(schedule['specific_dates'])
        txt = get_text(uid, 'specific_dates').format(', '.join(dates) if dates else get_text(uid, 'nothing'))
    pub_time = schedule.get('publish_time', '00:00')
    txt += f"\n🕐 وقت النشر: {pub_time} (بتوقيت مكة)"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 دقائق", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_MINUTES_PREFIX}{ch_db_id}"), 
         InlineKeyboardButton("🕒 ساعات", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_HOURS_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton("📆 أيام", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_DAYS_PREFIX}{ch_db_id}"), 
         InlineKeyboardButton("📅 أيام أسبوع", callback_data=f"{CallbackData.SCHEDULE_SET_DAYS_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton("🗓️ تواريخ محددة", callback_data=f"{CallbackData.SCHEDULE_SET_DATES_PREFIX}{ch_db_id}"), 
         InlineKeyboardButton("⏰ وقت النشر", callback_data=f"{CallbackData.SCHEDULE_SET_PUBLISH_TIME_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit_markdown(query, get_text(uid, 'schedule_settings').format(txt), reply_markup=kb)

async def set_interval_minutes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = f'waiting_interval_minutes_{ch_db_id}'
    await query.edit_message_text(get_text(uid, 'send_minutes'))

async def set_interval_hours_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = f'waiting_interval_hours_{ch_db_id}'
    await query.edit_message_text(get_text(uid, 'send_hours'))

async def set_interval_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = f'waiting_interval_days_{ch_db_id}'
    await query.edit_message_text(get_text(uid, 'send_days'))

async def set_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['selected_days_ch'] = ch_db_id
    context.user_data['selected_days'] = []
    context.user_data['state'] = f'selecting_days_{ch_db_id}'
    await query.edit_message_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(uid, context))

async def set_dates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = f'waiting_dates_{ch_db_id}'
    await query.edit_message_text(get_text(uid, 'send_dates'))

async def set_publish_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = f'waiting_publish_time_{ch_db_id}'
    await query.edit_message_text(get_text(uid, 'send_time'))

async def day_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    day = int(query.data.split(":")[-1])
    selected = context.user_data.get('selected_days', [])
    if day in selected:
        selected.remove(day)
    else:
        selected.append(day)
    context.user_data['selected_days'] = selected
    await query.edit_message_text("اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(uid, context))

async def save_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    ch = context.user_data.get('selected_days_ch')
    if ch:
        days_json = json.dumps(context.user_data.get('selected_days', []))
        await db_save_schedule(ch, 'days', days_of_week=days_json)
        await db_set_next_publish_date(ch, None)
        context.user_data.pop('selected_days_ch', None)
        context.user_data.pop('selected_days', None)
        context.user_data.pop('state', None)
        await safe_edit_markdown(query, get_text(uid, 'days_saved'), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]]))
    else:
        await query.edit_message_text(get_text(uid, 'error'))

def security_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 حذف الروابط", callback_data=f"{CallbackData.SECURITY_LINKS_PREFIX}{chat_id}"), 
         InlineKeyboardButton("@ حذف المعرفات", callback_data=f"{CallbackData.SECURITY_MENTIONS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🚫 كلمات محظورة", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}"), 
         InlineKeyboardButton("⏱️ الوضع البطيء", callback_data=f"{CallbackData.SECURITY_SLOWMODE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🎯 الترحيب", callback_data=f"{CallbackData.SECURITY_WELCOME_PREFIX}{chat_id}"), 
         InlineKeyboardButton("👋 الوداع", callback_data=f"{CallbackData.SECURITY_GOODBYE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("⚖️ تحديد العقوبة", callback_data=f"{CallbackData.PENALTY_MENU}:{chat_id}"), 
         InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}")],
        [InlineKeyboardButton("📜 سجل الإجراءات", callback_data=f"{CallbackData.GROUP_ACTION_LOG}:{chat_id}")],
        [InlineKeyboardButton("🔙 إغلاق", callback_data=CallbackData.SECURITY_CLOSE)]
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

def get_replies_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة رد", callback_data=CallbackData.ADMIN_ADD_REPLY), 
         InlineKeyboardButton("📋 عرض الردود", callback_data=CallbackData.ADMIN_LIST_REPLIES)],
        [InlineKeyboardButton("🗑️ حذف رد", callback_data=CallbackData.ADMIN_DEL_REPLY), 
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])

def get_group_banned_words_keyboard(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"{CallbackData.BANNED_WORDS_ADD_PREFIX}{chat_id}"), 
         InlineKeyboardButton("📋 عرض الكلمات", callback_data=f"{CallbackData.BANNED_WORDS_LIST_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=f"{CallbackData.BANNED_WORDS_REMOVE_PREFIX}{chat_id}"), 
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

def get_banned_words_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة عامة", callback_data=CallbackData.ADMIN_ADD_BANNED_WORD), 
         InlineKeyboardButton("📋 عرض الكلمات", callback_data=CallbackData.ADMIN_LIST_BANNED_WORDS)],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=CallbackData.ADMIN_REMOVE_BANNED_WORD), 
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
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
        [InlineKeyboardButton("⏱️ 5 دقائق", callback_data=f"{CallbackData.ADV_MUTE_DURATION_PREFIX}5:{chat_id}"),
         InlineKeyboardButton("⏱️ 30 دقيقة", callback_data=f"{CallbackData.ADV_MUTE_DURATION_PREFIX}30:{chat_id}")],
        [InlineKeyboardButton("⏱️ 1 ساعة", callback_data=f"{CallbackData.ADV_MUTE_DURATION_PREFIX}60:{chat_id}"),
         InlineKeyboardButton("⏱️ 12 ساعة", callback_data=f"{CallbackData.ADV_MUTE_DURATION_PREFIX}720:{chat_id}")],
        [InlineKeyboardButton("📆 يوم", callback_data=f"{CallbackData.ADV_MUTE_DURATION_PREFIX}1440:{chat_id}"),
         InlineKeyboardButton("📆 أسبوع", callback_data=f"{CallbackData.ADV_MUTE_DURATION_PREFIX}10080:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم دائم", callback_data=f"{CallbackData.ADV_MUTE_DURATION_PREFIX}0:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}")]
    ])

def get_admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'admin_users'), callback_data=CallbackData.ADMIN_USERS), 
         InlineKeyboardButton(get_text(user_id, 'admin_banned'), callback_data=CallbackData.ADMIN_BANNED_USERS)],
        [InlineKeyboardButton(get_text(user_id, 'admin_channels'), callback_data=CallbackData.ADMIN_ALL_CHANNELS), 
         InlineKeyboardButton("⛔ قنوات محظورة", callback_data=CallbackData.ADMIN_BANNED_CHANNELS)],
        [InlineKeyboardButton("📊 المجموعات", callback_data=CallbackData.ADMIN_GROUPS), 
         InlineKeyboardButton("🚷 مجموعات محظورة", callback_data=CallbackData.ADMIN_BANNED_GROUPS)],
        [InlineKeyboardButton("📢 قنوات البوت", callback_data=CallbackData.ADMIN_BOT_CHANNELS), 
         InlineKeyboardButton("🚫 قنوات بوت محظورة", callback_data=CallbackData.ADMIN_BANNED_BOT_CHANNELS)],
        [InlineKeyboardButton("❤️ تنشيط الكل", callback_data=CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS), 
         InlineKeyboardButton("📂 مراقبة المستخدمين", callback_data=CallbackData.ADMIN_MONITOR_USERS)],
        [InlineKeyboardButton("👑 + مشرف", callback_data=CallbackData.ADMIN_ADD_ADMIN), 
         InlineKeyboardButton("🗑️ - مشرف", callback_data=CallbackData.ADMIN_REMOVE_ADMIN)],
        [InlineKeyboardButton("💬 ردود المجموعة", callback_data=CallbackData.ADMIN_REPLIES), 
         InlineKeyboardButton("🚫 كلمات محظورة (عامة)", callback_data=CallbackData.ADMIN_BANNED_WORDS)],
        [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:0")],
        [InlineKeyboardButton("🖥️ حالة الرام", callback_data=CallbackData.ADMIN_RAM), 
         InlineKeyboardButton("📊 إحصائيات عامة", callback_data=CallbackData.ADMIN_STATS)],
        [InlineKeyboardButton("📈 مقاييس الأداء", callback_data=CallbackData.ADMIN_METRICS)],
        [InlineKeyboardButton("💾 نسخة احتياطية", callback_data=CallbackData.ADMIN_BACKUP), 
         InlineKeyboardButton("🔄 استعادة نسخة", callback_data=CallbackData.ADMIN_RESTORE_BACKUP)],
        [InlineKeyboardButton("⏱️ وقت النشر (عام)", callback_data=CallbackData.ADMIN_CHANGE_INTERVAL), 
         InlineKeyboardButton("⚙️ إعدادات النسخ", callback_data=CallbackData.ADMIN_BACKUP_SETTINGS)],
        [InlineKeyboardButton("📢 نشر تحديث", callback_data=CallbackData.ADMIN_SEND_UPDATE), 
         InlineKeyboardButton("⚙️ قناة التحديثات", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
        [InlineKeyboardButton("🔄 التحديثات", callback_data=CallbackData.ADMIN_UPDATES), 
         InlineKeyboardButton("🔒 الاشتراك الإجباري", callback_data=CallbackData.ADMIN_FORCE_SUBSCRIBE)],
        [InlineKeyboardButton("⚙️ تعيين القناة", callback_data=CallbackData.ADMIN_SET_FORCE_CHANNEL), 
         InlineKeyboardButton("📨 إرسال رسالة", callback_data=CallbackData.ADMIN_BROADCAST)],
        [InlineKeyboardButton("📋 تذاكر الدعم", callback_data=CallbackData.ADMIN_SUPPORT_TICKETS), 
         InlineKeyboardButton("🗑️ حذف جميع التذاكر", callback_data=CallbackData.ADMIN_DELETE_ALL_TICKETS)],
        [InlineKeyboardButton("📁 صلاحية /sendcode", callback_data=CallbackData.ADMIN_MANAGE_SENDCODE), 
         InlineKeyboardButton("📋 قناة التقارير", callback_data=CallbackData.ADMIN_SHOW_LOG_CHANNEL)],
        [InlineKeyboardButton("📋 تعيين قناة التقارير", callback_data=CallbackData.ADMIN_SET_LOG_CHANNEL)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])

async def build_days_keyboard(uid, context):
    selected = context.user_data.get('selected_days', [])
    day_names = [get_text(uid, 'monday'), get_text(uid, 'tuesday'), get_text(uid, 'wednesday'), 
                 get_text(uid, 'thursday'), get_text(uid, 'friday'), get_text(uid, 'saturday'), 
                 get_text(uid, 'sunday')]
    kb_buttons = []
    for i in range(0, 7, 3):
        row = []
        for j in range(3):
            if i + j < 7:
                day_index = i + j
                name = day_names[day_index]
                mark = "✅ " if day_index in selected else ""
                row.append(InlineKeyboardButton(f"{mark}{name}", callback_data=f"{CallbackData.SCHEDULE_DAY_SELECT_PREFIX}{day_index}"))
        if row:
            kb_buttons.append(row)
    kb_buttons.append([
        InlineKeyboardButton("✔️ حفظ", callback_data=CallbackData.SCHEDULE_SAVE_DAYS),
        InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)
    ])
    return InlineKeyboardMarkup(kb_buttons)

async def get_main_keyboard(user_id: int):
    channels = await db_get_channels(user_id)
    active = await db_get_active_channel(user_id)
    cnt = 0
    ch_display = get_text(user_id, 'no_channels')
    if channels:
        if active is None or active not in [ch[0] for ch in channels]:
            active = channels[0][0]
            await db_set_active_channel(user_id, active)
        cnt = await db_unpublished_count(active)
        ch_info = await db_get_channel_info(active)
        ch_display = f"{ch_info[1]} ({ch_info[0]})" if ch_info else get_text(user_id, 'no_channels')
    my_groups = await db_get_user_groups_count(user_id)
    has_sub = await db_has_active_subscription(user_id)
    sub_text = get_text(user_id, 'subscribed') if has_sub else get_text(user_id, 'not_subscribed')
    auto_text = get_text(user_id, 'auto_on') if await db_auto_status(user_id) else get_text(user_id, 'auto_off')
    title = get_text(user_id, 'main_title').format(BOT_NAME, user_id, my_groups, sub_text, ch_display, cnt, auto_text)
    updates_channel = await db_get_updates_channel()
    updates_url = f"https://t.me/{updates_channel}" if updates_channel else None
    keyboard = []
    if not channels:
        keyboard = [
            [InlineKeyboardButton(get_text(user_id, 'add_channel'), callback_data=CallbackData.CHANNELS_ADD), 
             InlineKeyboardButton(get_text(user_id, 'my_channels'), callback_data=CallbackData.CHANNELS_MY)],
        ]
        if active:
            keyboard.append([
                [InlineKeyboardButton(get_text(user_id, 'channel_stats'), callback_data=f"{CallbackData.CHANNEL_STATS}:{active}")]
            ])
        keyboard.extend([
            [InlineKeyboardButton(get_text(user_id, 'help_btn'), callback_data=CallbackData.HELP), 
             InlineKeyboardButton(get_text(user_id, 'trial_btn'), callback_data=CallbackData.TRIAL)],
            [InlineKeyboardButton(get_text(user_id, 'subscribe_btn'), callback_data=CallbackData.SUBSCRIBE_MENU), 
             InlineKeyboardButton(get_text(user_id, 'developer_btn'), callback_data=CallbackData.DEVELOPER)],
            [InlineKeyboardButton(get_text(user_id, 'language_btn'), callback_data=CallbackData.LANGUAGE), 
             InlineKeyboardButton(get_text(user_id, 'support_btn'), callback_data=CallbackData.SUPPORT_MENU)],
            [InlineKeyboardButton(get_text(user_id, 'referral'), callback_data=CallbackData.REFERRAL_MENU), 
             InlineKeyboardButton(get_text(user_id, 'reminder_settings'), callback_data=CallbackData.REMINDER_MENU)],
            [InlineKeyboardButton(get_text(user_id, 'translation_settings'), callback_data=CallbackData.TRANSLATION_MENU)],
            [InlineKeyboardButton(get_text(user_id, 'publish_all'), callback_data=CallbackData.PUBLISH_ALL_CHANNELS)],
        ])
        if updates_url:
            keyboard.append([InlineKeyboardButton(get_text(user_id, 'updates_btn'), callback_data=CallbackData.UPDATES)])
        keyboard.append([InlineKeyboardButton(get_text(user_id, 'add_to_group'), url=f"https://t.me/{BOT_USERNAME}?startgroup")])
        if user_id == MAIN_ADMIN_ID or await is_bot_admin(user_id):
            keyboard.append([InlineKeyboardButton(get_text(user_id, 'admin_panel'), callback_data=CallbackData.ADMIN_PANEL)])
        return InlineKeyboardMarkup([row for row in keyboard if row]), title, active
    keyboard = [
        [InlineKeyboardButton(get_text(user_id, 'add_channel'), callback_data=CallbackData.CHANNELS_ADD), 
         InlineKeyboardButton(get_text(user_id, 'my_channels'), callback_data=CallbackData.CHANNELS_MY)],
        [InlineKeyboardButton(get_text(user_id, 'add_15_posts'), callback_data=CallbackData.POSTS_ADD_15), 
         InlineKeyboardButton(get_text(user_id, 'publish_one'), callback_data=CallbackData.POSTS_PUBLISH_ONE)],
        [InlineKeyboardButton(get_text(user_id, 'my_posts_btn'), callback_data=CallbackData.POSTS_MY), 
         InlineKeyboardButton(get_text(user_id, 'recycle'), callback_data=CallbackData.POSTS_RECYCLE)],
        [InlineKeyboardButton(f"{get_text(user_id, 'stats_btn')} ({cnt})", callback_data=CallbackData.STATS_PENDING), 
         InlineKeyboardButton(get_text(user_id, 'my_stats_btn'), callback_data=CallbackData.STATS_FULL)],
        [InlineKeyboardButton(get_text(user_id, 'my_groups_btn'), callback_data=CallbackData.GROUPS_MY), 
         InlineKeyboardButton(get_text(user_id, 'settings_btn'), callback_data=CallbackData.SETTINGS_MENU)],
        [InlineKeyboardButton(get_text(user_id, 'schedule_btn'), callback_data=f"{CallbackData.SCHEDULE_MENU_PREFIX}{active}"), 
         InlineKeyboardButton(get_text(user_id, 'channel_stats'), callback_data=f"{CallbackData.CHANNEL_STATS}:{active}")],
        [InlineKeyboardButton(get_text(user_id, 'my_channels_summary'), callback_data=CallbackData.MY_CHANNEL_STATS),
         InlineKeyboardButton(get_text(user_id, 'my_rank_btn'), callback_data=CallbackData.RANK)],
        [InlineKeyboardButton(get_text(user_id, 'top_10_btn'), callback_data=CallbackData.TOP), 
         InlineKeyboardButton(get_text(user_id, 'schedule_post_btn'), callback_data=CallbackData.SCHEDULE_POST)],
        [InlineKeyboardButton(get_text(user_id, 'help_btn'), callback_data=CallbackData.HELP), 
         InlineKeyboardButton(get_text(user_id, 'trial_btn'), callback_data=CallbackData.TRIAL)],
        [InlineKeyboardButton(get_text(user_id, 'subscribe_btn'), callback_data=CallbackData.SUBSCRIBE_MENU), 
         InlineKeyboardButton(get_text(user_id, 'developer_btn'), callback_data=CallbackData.DEVELOPER)],
        [InlineKeyboardButton(get_text(user_id, 'language_btn'), callback_data=CallbackData.LANGUAGE), 
         InlineKeyboardButton(get_text(user_id, 'support_btn'), callback_data=CallbackData.SUPPORT_MENU)],
        [InlineKeyboardButton(get_text(user_id, 'referral'), callback_data=CallbackData.REFERRAL_MENU), 
         InlineKeyboardButton(get_text(user_id, 'reminder_settings'), callback_data=CallbackData.REMINDER_MENU)],
        [InlineKeyboardButton(get_text(user_id, 'translation_settings'), callback_data=CallbackData.TRANSLATION_MENU)],
        [InlineKeyboardButton(get_text(user_id, 'publish_all'), callback_data=CallbackData.PUBLISH_ALL_CHANNELS)],
    ]
    if updates_url:
        keyboard.append([InlineKeyboardButton(get_text(user_id, 'updates_btn'), callback_data=CallbackData.UPDATES)])
    keyboard.append([InlineKeyboardButton(get_text(user_id, 'add_to_group'), url=f"https://t.me/{BOT_USERNAME}?startgroup")])
    if user_id == MAIN_ADMIN_ID or await is_bot_admin(user_id):
        keyboard.append([InlineKeyboardButton(get_text(user_id, 'admin_panel'), callback_data=CallbackData.ADMIN_PANEL)])
    return InlineKeyboardMarkup([row for row in keyboard if row]), title, active

async def filter_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await message_processor.add_message(update, context)

async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    chat = update.effective_chat
    if chat.type in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ استخدم هذا الأمر في الخاص")
        return
    uid = update.effective_user.id
    user = update.effective_user
    if not await rate_limiter.check_rate_limit(uid, 'start', 5, 60):
        await update.message.reply_text("⏳ أنت تستخدم الأمر بسرعة كبيرة. انتظر قليلاً.")
        return
    if not await ensure_force_subscribe(update, context, uid):
        return
    if context.args and len(context.args) > 0:
        arg = context.args[0]
        if arg.startswith('ref_'):
            referral_code = arg[4:]
            referrer = await db_get_user_by_referral_code(referral_code)
            if referrer and referrer != uid:
                success = await db_add_referral(referrer, uid)
                if success:
                    reward_days = await db_auto_reward_referral(referrer, uid)
                    welcome_points = await db_get_welcome_bonus_points()
                    current_level = await db_get_user_level(uid)
                    await db_update_user_level(uid, current_level['points'] + welcome_points, current_level['level'])
                    try:
                        await safe_send_markdown(context.bot, referrer, f"🎉 **تهانينا!**\nقام مستخدم جديد بالتسجيل عبر رابط الإحالة الخاص بك!\n🎁 لقد حصلت على {reward_days} يوم اشتراك مجاني!")
                    except:
                        pass
                    await safe_send_markdown(context.bot, uid, f"🎉 **مرحباً بك!**\nلقد تم تسجيل دخولك عبر دعوة من مستخدم آخر.\n🎁 لقد حصلت على {welcome_points} نقطة ترحيب!")
    await db_update_user_cache(uid, user.username, user.first_name)
    if uid not in user_language:
        await set_user_language(uid, 'ar')
    await db_register_user(uid)
    if await db_is_banned(uid):
        await update.message.reply_text("🚫 أنت محظور.")
        return
    referral_code = await db_get_referral_code(uid)
    if not referral_code:
        await db_generate_referral_code(uid)
    active = context.user_data.get('active_channel')
    if not active:
        active = await db_get_active_channel(uid)
    channels = await db_get_channels(uid)
    kb, title, new_active = await get_main_keyboard(uid)
    if active is None and channels:
        active = channels[0][0]
        context.user_data['active_channel'] = active
        await db_set_active_channel(uid, active)
    await safe_send_markdown(context.bot, uid, title, reply_markup=kb)
    return

async def language_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await ensure_force_subscribe(update, context, user_id):
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("العربية 🇸🇦", callback_data=CallbackData.LANG_AR), 
         InlineKeyboardButton("English 🇬🇧", callback_data=CallbackData.LANG_EN)],
        [InlineKeyboardButton("Français 🇫🇷", callback_data=CallbackData.LANG_FR), 
         InlineKeyboardButton("Türkçe 🇹🇷", callback_data=CallbackData.LANG_TR)],
        [InlineKeyboardButton("中文 🇨🇳", callback_data=CallbackData.LANG_ZH), 
         InlineKeyboardButton("Русский 🇷🇺", callback_data=CallbackData.LANG_RU)]
    ])
    await update.message.reply_text(get_text(user_id, 'welcome'), reply_markup=keyboard)

async def syncgroup_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_subscribe(update, context):
        return
    if update.message is None:
        return
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("هذا الأمر يعمل فقط في المجموعات.")
        return
    user = update.effective_user
    if user is None:
        return
    if not await is_authorized_in_group(context.bot, chat.id, user.id):
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة البوت", url=f"https://t.me/{BOT_USERNAME}?startgroup")]])
        await update.message.reply_text(get_text(user.id, 'admin_only'), reply_markup=keyboard)
        return
    group_username = chat.username if chat.username else None
    is_new = await db_register_group(chat.id, chat.title or "بدون اسم", user.id, group_username)
    if is_new:
        await update.message.reply_text(f"✅ **تم تفعيل البوت في {chat.title}**\n📌 استخدم /security للإعدادات\n🛠️ استخدم /panel للإجراءات المتقدمة\n👑 للمالك المخفي: /register_hidden_owner", parse_mode="MarkdownV2")
    else:
        await update.message.reply_text(f"ℹ️ تم تحديث معلومات {chat.title}")

async def security_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_subscribe(update, context):
        return
    if update.message is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    uid = user.id
    if chat.type == 'private':
        groups = await db_get_user_groups(uid)
        if not groups:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ أضف البوت إلى مجموعة", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
                [InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)]
            ])
            text = """🔐 **إعدادات الأمان**

⚠️ لم يتم العثور على مجموعات.

📌 **لتفعيل إعدادات الأمان والإجراءات المتقدمة:**
1. أضف البوت إلى مجموعتك
2. اجعل البوت مشرفاً
3. استخدم الأمر /syncgroup في المجموعة
4. ثم عد إلى الخاص واضغط على تحديث
5. إذا كنت مالكاً مخفياً، استخدم الأمر /register_hidden_owner في المجموعة"""
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
        await safe_send_markdown(context.bot, uid, text, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    if await is_authorized_in_group(context.bot, chat.id, user.id):
        settings = await db_get_security_settings(chat.id)
        text = f"""🔐 **إعدادات أمان المجموعة**
🔗 حذف الروابط: {'✅' if settings['links'] else '❌'}
@ حذف المعرفات: {'✅' if settings['mentions'] else '❌'}
🚫 كلمات محظورة: {'✅' if settings.get('delete_banned_words', False) else '❌'}
🔊 رسالة تحذير: {'✅' if settings['warn'] else '❌'}
🚦 وضع بطيء: {'✅' if settings['slow_mode'] else '❌'}
🎯 ترحيب: {'✅' if settings['welcome_enabled'] else '❌'}
👋 وداع: {'✅' if settings['goodbye_enabled'] else '❌'}"""
        await update.message.reply_text(text, reply_markup=security_keyboard(chat.id), parse_mode="MarkdownV2")
    else:
        await update.message.reply_text(get_text(uid, 'admin_only'))

async def trial_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    uid = update.effective_user.id
    if not await ensure_force_subscribe(update, context, uid):
        return
    if await db_has_used_trial(uid):
        await update.message.reply_text(get_text(uid, 'trial_used'))
        return
    if await db_has_active_subscription(uid):
        await update.message.reply_text(get_text(uid, 'already_subscribed'))
        return
    days = await db_activate_trial(uid)
    if days == 0:
        await update.message.reply_text(get_text(uid, 'already_subscribed'))
    else:
        await update.message.reply_text(get_text(uid, 'trial'), parse_mode="MarkdownV2")

async def subscribe_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    uid = update.effective_user.id
    if not await ensure_force_subscribe(update, context, uid):
        return
    if await db_has_active_subscription(uid):
        days = await db_get_subscription_days_left(uid)
        await update.message.reply_text(f"✅ اشتراكك مفعل، متبقي {days} يوم\nشكراً لدعمك ❤️")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_1), 
         InlineKeyboardButton("⭐ 2 يوم - 9 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_2)],
        [InlineKeyboardButton("⭐ شهر (30 يوم) - 50 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_30), 
         InlineKeyboardButton("⭐ 3 أشهر (90 يوم) - 120 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_90)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    text = get_text(uid, 'subscribe')
    await update.message.reply_text(text, reply_markup=kb, parse_mode="MarkdownV2")

async def help_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else MAIN_ADMIN_ID
    if update.callback_query:
        await safe_send_markdown(context.bot, update.callback_query.message.chat_id, get_text(uid, 'help'))
        await safe_query_answer(update.callback_query)
    elif update.message:
        await safe_send_markdown(context.bot, update.message.chat_id, get_text(uid, 'help'))

async def support_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_force_subscribe(update, context):
        return
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP),
         InlineKeyboardButton("📋 تذكرتي", callback_data=CallbackData.SUPPORT_TICKET)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await update.message.reply_text(get_text(user_id, 'support_welcome'), reply_markup=keyboard, parse_mode="MarkdownV2")
    context.user_data['support_mode'] = True

async def rank_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    effective_user = update.effective_user
    if effective_user is None:
        return
    user_id = effective_user.id
    data = await get_rank(user_id)
    points = data['points']
    level = data['level']
    next_points = LEVEL_REQUIREMENTS.get(level + 1, points)
    points_needed = next_points - points if next_points > points else 0
    text = f"📊 **رتبتك الحالية**\n━━━━━━━━━━━━━━\n👤 {effective_user.first_name}\n⭐ **المستوى:** {level}\n📈 **النقاط:** {points}\n📌 **المتبقي للمستوى التالي:** {points_needed}"
    if update.callback_query:
        await safe_query_answer(update.callback_query)
        await safe_send_markdown(context.bot, update.callback_query.message.chat_id, text)
    else:
        await safe_send_markdown(context.bot, update.message.chat_id, text)

async def top_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_users = await get_top_users(10)
    if not top_users:
        msg = "📭 لا توجد نقاط مسجدة بعد."
        if update.callback_query:
            await safe_query_answer(update.callback_query)
            await safe_send_markdown(context.bot, update.callback_query.message.chat_id, msg)
        else:
            await safe_send_markdown(context.bot, update.message.chat_id, msg)
        return
    text = "🏆 **أفضل 10 مستخدمين**\n━━━━━━━━━━━━━━\n"
    for idx, (uid, points, level) in enumerate(top_users, 1):
        try:
            user = await context.bot.get_chat(uid)
            name = user.first_name or str(uid)
        except:
            name = str(uid)
        text += f"{idx}. {name} → المستوى {level} ({points} نقطة)\n"
    if update.callback_query:
        await safe_query_answer(update.callback_query)
        await safe_send_markdown(context.bot, update.callback_query.message.chat_id, text)
    else:
        await safe_send_markdown(context.bot, update.message.chat_id, text)

async def developer_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else MAIN_ADMIN_ID
    metrics_stats = metrics.get_stats()
    twofa_status = "✅ مفعلة" if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE else "❌ معطلة"
    text = f"""👑 **معلومات المطور**
━━━━━━━━━━━━━━━━━━━━━━
🤖 **البوت:** {BOT_NAME}
📦 **الإصدار:** 19.0.3 (المصحح بالكامل)
👨‍💻 **المطور:** @RelaxMgr

🔐 **الميزات الأمنية المتقدمة:**
• إعادة تدوير المنشورات تلقائياً مع تأكيد
• إحصائيات متقدمة للقنوات
• رسم بياني لنمو القناة
• نظام أمان متكامل للمجموعات
• دعم المالك المخفي
• نظام ترجمة ذكي
• دعم جميع أنواع الميديا
• واجهة ويب مع WebSocket
• نظام Rate Limiting متقدم
• مصادقة ثنائية (2FA)

⚡ **وضع السرعة:** {'مفعل' if not BATTERY_SAVER_MODE else 'معطل'}

📊 **إحصائيات الأداء:**
• وقت التشغيل: {int(metrics_stats['uptime'] / 3600)} ساعة
• إجمالي الأوامر: {metrics_stats['total_commands']}
• متوسط وقت الاستجابة: {metrics_stats['avg_response_time']:.2f} ثانية

━━━━━━━━━━━━━━━━━━━━━━
📞 **طرق التواصل:**
✅ **تيليجرام:** @RelaxMgr
✅ **البوت:** @{BOT_USERNAME}"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 تواصل مع المطور", url=f"https://t.me/RelaxMgr")],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    if update.callback_query:
        await safe_query_answer(update.callback_query)
        await safe_edit_markdown(update.callback_query, text, reply_markup=keyboard)
    elif update.message:
        await safe_send_markdown(context.bot, update.message.chat_id, text, reply_markup=keyboard)

async def updates_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    uid = update.effective_user.id
    updates_channel = await db_get_updates_channel()
    text = get_text(uid, 'updates_text')
    keyboard = InlineKeyboardMarkup([])
    if updates_channel:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 قناة التحديثات", url=f"https://t.me/{updates_channel}")],
            [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
        ])
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
        ])
    await update.message.reply_text(text, reply_markup=keyboard, parse_mode="MarkdownV2")

async def stats_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    uid = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
    if not active:
        await update.message.reply_text("⚠️ يرجى اختيار قناة أولاً")
        return
    class MockQuery:
        def __init__(self, from_user, message):
            self.from_user = from_user
            self.message = message
            self.data = f"channel_stats:{active}"
        async def answer(self):
            pass
        async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
            await self.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        async def delete_message(self):
            pass
    mock_query = MockQuery(update.effective_user, update.message)
    await channel_stats_callback(update, context)

async def sendcode_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    allowed_user = await db_get_allowed_sendcode_user()
    if user_id != MAIN_ADMIN_ID and user_id != allowed_user:
        await safe_send_markdown(context.bot, user_id, "🔒 هذا الأمر للمطور الأساسي أو المستخدمين المصرح لهم فقط.")
        logger.warning(f"⚠️ محاولة استخدام /sendcode من مستخدم غير مصرح: {user_id}")
        await security_audit.log("UNAUTHORIZED_SENDCODE_ATTEMPT", user_id, {}, "CRITICAL")
        return
    if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE:
        if not context.user_data.get('2fa_verified') or time_module.time() - context.user_data.get('2fa_time', 0) > 300:
            secret = ADMIN_2FA_SECRET
            totp = pyotp.TOTP(secret)
            context.user_data['waiting_2fa'] = True
            await update.message.reply_text("🔐 أدخل رمز المصادقة الثنائية (2FA):")
            return
    import random
    import string
    confirm_code = ''.join(random.choices(string.digits, k=6))
    context.user_data['sendcode_confirm'] = confirm_code
    context.user_data['sendcode_timestamp'] = time_module.time()
    await safe_send_markdown(context.bot, user_id, 
        f"🚨 **تحذير أمني شديد!**\n\n"
        f"أنت على وشك إرسال كود البوت الكامل.\n"
        f"هذا الكود يحتوي على:\n"
        f"• توكن البوت\n"
        f"• مفاتيح التشفير\n"
        f"• هيكل قاعدة البيانات الكامل\n"
        f"• معلومات المستخدمين\n\n"
        f"**للتأكيد، أرسل الرمز التالي:**\n"
        f"`{confirm_code}`\n\n"
        f"⚠️ تأكد 100% أن المستخدم الذي ترسل له الكود موثوق!\n"
        f"⏰ لديك 60 ثانية لإدخال الرمز",
    )
    context.user_data['state'] = 'waiting_sendcode_confirmation'

async def handle_sendcode_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    allowed_user = await db_get_allowed_sendcode_user()
    if user_id != MAIN_ADMIN_ID and user_id != allowed_user:
        await update.message.reply_text("❌ غير مصرح")
        return
    expected_code = context.user_data.get('sendcode_confirm')
    timestamp = context.user_data.get('sendcode_timestamp', 0)
    if not expected_code:
        await update.message.reply_text("❌ لم يتم طلب إرسال كود")
        context.user_data.pop('state', None)
        return
    if time_module.time() - timestamp > 60:
        await update.message.reply_text("❌ انتهت صلاحية رمز التأكيد. أعد استخدام الأمر /sendcode")
        context.user_data.pop('sendcode_confirm', None)
        context.user_data.pop('sendcode_timestamp', None)
        context.user_data.pop('state', None)
        return
    if update.message.text.strip() == expected_code:
        try:
            with open(__file__, 'r', encoding='utf-8') as f:
                content = f.read()
            watermark = f"""# ============================================================
# ORIGINAL_OWNER: {user_id}
# GENERATED_AT: {mecca_now().strftime('%Y-%m-%d %H:%M:%S')}
# SIGNATURE: {hashlib.sha256(f"{user_id}{time_module.time()}{TOKEN}".encode()).hexdigest()[:16]}
# ============================================================
# ⚠️ تحذير: هذا الكود يحتوي على معلومات حساسة
# لا تشاركه مع أي شخص غير موثوق
# ============================================================

"""
            watermarked_content = watermark + content
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, f"bot_code_{user_id}_{int(time_module.time())}.py")
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(watermarked_content)
            await context.bot.send_document(
                chat_id=user_id,
                document=open(temp_file, 'rb'),
                filename=f"relax_bot_secure_{mecca_now().strftime('%Y%m%d')}.py",
                caption="⚠️ **هذا الكود موقع رقمياً - لا تشاركه مع أي شخص غير موثوق!**\n\n📌 يحتوي على:\n• التوكن والمفاتيح\n• هيكل قاعدة البيانات\n• معلومات حساسة أخرى"
            )
            os.unlink(temp_file)
            await security_audit.log("SENDCODE_EXECUTED", user_id, {"timestamp": mecca_now_iso()}, "CRITICAL")
            await update.message.reply_text("✅ تم إرسال الكود بنجاح مع توقيع رقمي")
            logger.info(f"📁 تم إرسال كود البوت من المستخدم {user_id} مع توقيع رقمي")
        except Exception as e:
            await update.message.reply_text(f"❌ فشل إرسال الكود: {e}")
        context.user_data.pop('sendcode_confirm', None)
        context.user_data.pop('sendcode_timestamp', None)
        context.user_data.pop('state', None)
    else:
        await update.message.reply_text("❌ رمز التأكيد غير صحيح! تم إلغاء العملية.")
        await security_audit.log("SENDCODE_FAILED_ATTEMPT", user_id, {"attempt_code": update.message.text[:6]}, "HIGH")
        context.user_data.pop('sendcode_confirm', None)
        context.user_data.pop('sendcode_timestamp', None)
        context.user_data.pop('state', None)

async def lock_chat_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat is None or update.effective_user is None:
        return
    if update.effective_chat.type == 'private':
        await update.message.reply_text(get_text(update.effective_user.id, 'group_only'))
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    await db_set_chat_lock(chat_id, True, user_id)
    await update.message.reply_text(get_text(user_id, 'locked'), parse_mode="MarkdownV2")

async def unlock_chat_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat is None or update.effective_user is None:
        return
    if update.effective_chat.type == 'private':
        await update.message.reply_text(get_text(update.effective_user.id, 'group_only'))
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    await db_set_chat_lock(chat_id, False)
    await update.message.reply_text(get_text(user_id, 'unlocked'), parse_mode="MarkdownV2")

async def panel_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user:
        if not await ensure_force_subscribe(update, context):
            return
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return
    chat = update.effective_chat
    user_id = update.effective_user.id
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text(get_text(user_id, 'group_only'))
        return
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
    await update.message.reply_text(f"🔧 **لوحة تحكم المجموعة**\n━━━━━━━━━━━━━━\n📌 **المجموعة:** {chat.title}\n🔐 **الحالة:** {lock_status_text}\n━━━━━━━━━━━━━━\n\nاستخدم الأزرار للتحكم في قفل وفتح المجموعة والإجراءات المتقدمة", reply_markup=kb, parse_mode="MarkdownV2")

async def register_hidden_owner_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    user = update.effective_user
    if user is None:
        return
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ يعمل فقط في المجموعات")
        return
    if not await is_authorized_in_group(context.bot, chat.id, user.id):
        await update.message.reply_text(get_text(user.id, 'admin_only'))
        return
    await db_register_hidden_owner_group(chat.id, user.id)
    await update.message.reply_text("✅ **تم تسجيل هذه المجموعة كمجموعة يملكها مالك مخفي!**\nالآن يمكنك استخدام /security داخل المجموعة ولن يظهر اسمك كمشرف.", parse_mode="MarkdownV2")

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
    if user_id != MAIN_ADMIN_ID and not await is_bot_admin(user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args
    if not args and context.user_data.get('state') == 'waiting_for_log_channel':
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
        await update.message.reply_text(f"❌ لا يمكن العثور على القناة: {e}", parse_mode="MarkdownV2")
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
        await update.message.reply_text(f"❌ لا يمكن الوصول للقناة: {e}", parse_mode="MarkdownV2")
        return
    await db_set_log_channel_id(str(chat_id))
    await update.message.reply_text(f"✅ **تم تعيين قناة التقارير بنجاح!**\nمعرف القناة: `{chat_id}`", parse_mode="MarkdownV2")
    try:
        await context.bot.send_message(chat_id, "✅ **تم تفعيل نظام التقارير**")
    except:
        pass
    context.user_data.pop('state', None)
    context.user_data.pop('temp_log_channel_identifier', None)

async def support_reply_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MAIN_ADMIN_ID and not await is_bot_admin(update.effective_user.id):
        await update.message.reply_text(get_text(update.effective_user.id, 'admin_only'))
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("📝 **الاستخدام:**\n`/support_reply user_id نص الرد`", parse_mode="MarkdownV2")
        return
    try:
        target_user_id = int(args[0])
        reply_text = " ".join(args[1:])
        ticket_id = await db_get_last_ticket_id_for_user(target_user_id)
        if ticket_id:
            await db_mark_ticket_replied(ticket_id)
        await context.bot.send_message(chat_id=target_user_id, text=f"📬 **رد على تذكرتك:**\n━━━━━━━━━━━━━━━━━━━━━━\n{reply_text}", parse_mode="MarkdownV2")
        await update.message.reply_text(f"✅ تم إرسال الرد إلى المستخدم {target_user_id}")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل الإرسال: {e}")

async def handle_moderation_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_chat is None or update.effective_user is None:
        return
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        return
    user_id = update.effective_user.id
    chat_id = chat.id
    text = update.message.text.strip() if update.message.text else ""
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"❌ {bot_perms['reason']}")
        return
    args = text.split(maxsplit=1)
    reason = args[1] if len(args) > 1 else ""
    if text.startswith("/ban") and update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        success, msg = await execute_ban(context.bot, chat_id, target_user.id, reason=reason, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/mute") and update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        minutes = context.user_data.get('mute_minutes', 60)
        success, msg = await execute_mute(context.bot, chat_id, target_user.id, minutes, reason=reason, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/warn") and update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        success, msg = await execute_warn(context.bot, chat_id, target_user.id, user_id, reason=reason)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/kick") and update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        success, msg = await execute_kick(context.bot, chat_id, target_user.id, reason=reason, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/restrict") and update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user
        success, msg = await execute_restrict(context.bot, chat_id, target_user.id, reason=reason, moderator_id=user_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/pin") and update.message.reply_to_message:
        success, msg = await execute_pin(context.bot, chat_id, update.message.reply_to_message.message_id)
        await safe_send_markdown(context.bot, chat_id, msg)
        return
    if text.startswith("/unban"):
        parts = text.split()
        if len(parts) >= 2:
            try:
                target_id = int(parts[1])
                success, msg = await execute_unban(context.bot, chat_id, target_id, moderator_id=user_id)
                await safe_send_markdown(context.bot, chat_id, msg)
            except ValueError:
                await update.message.reply_text("❌ معرف مستخدم غير صالح")
        else:
            await update.message.reply_text("📝 **الاستخدام:** `/unban معرف_المستخدم`", parse_mode="MarkdownV2")
        return

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

async def auto_publish_loop_improved(bot):
    await asyncio.sleep(5)
    consecutive_errors = 0
    backoff = 10
    max_backoff = 60
    while True:
        try:
            publish_interval = await db_get_publish_interval_seconds()
            async def _get_all_channels_to_publish(conn):
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
                    LIMIT 100
                """, (now_utc_iso,))
                return await cur.fetchall()
            rows = await execute_db(_get_all_channels_to_publish)
            for row in rows:
                ch_db_id = row[0]
                ch_tele_id = row[1]
                user_id = row[2]
                if not await db_has_active_subscription(user_id) and not await db_has_used_trial(user_id):
                    continue
                has_permission, permission_msg = await check_bot_permissions(bot, ch_tele_id)
                if not has_permission:
                    continue
                if await db_should_auto_recycle(ch_db_id):
                    total_posts = await db_get_posts_count(ch_db_id)
                    logger.info(f"♻️ إعادة تدوير تلقائي للقناة {ch_tele_id}: تم نشر جميع {total_posts} منشور، جاري إعادة التعيين...")
                    await db_reset_all_posts_to_unpublished(ch_db_id)
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"♻️ **تم إعادة تدوير المنشورات تلقائياً!**\n\n📡 القناة: {ch_tele_id}\n📝 تم إعادة تعيين {total_posts} منشور للنشر من جديد.",
                            parse_mode="MarkdownV2"
                        )
                    except:
                        pass
                    continue
                post = await db_get_next_post(ch_db_id)
                if not post:
                    continue
                translation_lang = await get_user_translation_language(user_id)
                final_text = post['text']
                if translation_lang != 'off' and final_text:
                    try:
                        translated = await translate_text(final_text, translation_lang)
                        if translated and translated != final_text:
                            final_text = f"{final_text}\n\n🌐 {translated}"
                    except:
                        pass
                success = False
                for attempt in range(2):
                    try:
                        if post['media_type'] == 'photo' and post['media_file_id']:
                            await bot.send_photo(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                        elif post['media_type'] == 'video' and post['media_file_id']:
                            await bot.send_video(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                        elif post['media_type'] == 'document' and post['media_file_id']:
                            await bot.send_document(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                        elif post['media_type'] == 'audio' and post['media_file_id']:
                            await bot.send_audio(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                        elif post['media_type'] == 'voice' and post['media_file_id']:
                            await bot.send_voice(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                        elif post['media_type'] == 'animation' and post['media_file_id']:
                            await bot.send_animation(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                        else:
                            await bot.send_message(ch_tele_id, final_text)
                        success = True
                        break
                    except Exception as e:
                        logger.warning(f"محاولة {attempt+1} فشلت في النشر للقناة {ch_tele_id}: {e}")
                        await asyncio.sleep(1)
                if success:
                    await db_mark_published(post['id'])
                    await db_set_last_publish(ch_db_id, utc_now())
                    await db_update_next_publish_date(ch_db_id)
                else:
                    await db_increment_fail_count(post['id'])
                    logger.error(f"فشل دائم في نشر المنشور {post['id']} في القناة {ch_tele_id}")
                await asyncio.sleep(random.uniform(2, 5))
            consecutive_errors = 0
            backoff = publish_interval
            await asyncio.sleep(publish_interval)
        except Exception as e:
            logger.error(f"خطأ في حلقة النشر: {e}")
            consecutive_errors += 1
            backoff = min(backoff * 1.5, max_backoff)
            await asyncio.sleep(backoff)

async def run_scheduled_posts_loop_improved(bot):
    consecutive_errors = 0
    backoff = SCHEDULED_POSTS_SLEEP
    max_backoff = 60
    while True:
        try:
            await asyncio.sleep(SCHEDULED_POSTS_SLEEP)
            now_utc = utc_now()
            posts = await db_get_due_scheduled_posts(now_utc)
            for post_id, chat_id, text, fail_count in posts:
                try:
                    await bot.send_message(chat_id, text)
                    await db_delete_scheduled_post(post_id)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    new_fail = fail_count + 1
                    await db_update_scheduled_post_fail(post_id, new_fail)
                    if new_fail >= 5:
                        await db_delete_scheduled_post(post_id)
                        logger.warning(f"تم حذف منشور مجدول بعد 5 محاولات فاشلة: {post_id}")
                    else:
                        logger.error(f"فشل إرسال منشور مجدول: {e}")
            consecutive_errors = 0
            backoff = SCHEDULED_POSTS_SLEEP
        except Exception as e:
            logger.error(f"خطأ في حلقة المنشورات المجدولة: {e}")
            backoff = min(backoff * 1.5, max_backoff)
            await asyncio.sleep(backoff)

async def send_reminders_loop_improved(bot):
    await asyncio.sleep(30)
    asyncio.create_task(daily_reminder_task(bot))
    asyncio.create_task(weekly_reminder_task(bot))
    while True:
        try:
            now = utc_now()
            now_mecca = utc_to_mecca(now)
            today_str = now_mecca.strftime("%Y-%m-%d")
            users_to_remind = await db_get_users_needing_reminder()
            for user_data in users_to_remind:
                user_id = user_data['user_id']
                days_left = user_data['days_left']
                lang = user_data['notification_lang']
                original_lang = user_language.get(user_id, 'ar')
                user_language[user_id] = lang
                text = get_text(user_id, 'subscription_warning').format(days_left)
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💎 تجديد الاشتراك", callback_data=CallbackData.SUBSCRIBE_MENU), InlineKeyboardButton("🔕 إيقاف التذكير", callback_data=CallbackData.REMINDER_TOGGLE_SUB)]])
                try:
                    await safe_send_markdown(bot, user_id, text, reply_markup=keyboard)
                    await db_update_last_reminder_sent(user_id, "subscription_expiry")
                except:
                    pass
                user_language[user_id] = original_lang
                await asyncio.sleep(0.5)
            await asyncio.sleep(REMINDERS_SLEEP)
        except Exception as e:
            logger.error(f"خطأ في حلقة الإشعارات: {e}")
            await asyncio.sleep(60)

async def daily_reminder_task(bot):
    last_daily_date = None
    while True:
        try:
            now = utc_now()
            now_mecca = utc_to_mecca(now)
            today_str = now_mecca.strftime("%Y-%m-%d")
            if last_daily_date != today_str:
                last_daily_date = today_str
                async def _get_daily_users(conn):
                    cur = await conn.execute("SELECT user_id, notification_lang FROM user_reminder_settings WHERE daily_stats_reminder=1")
                    return await cur.fetchall()
                daily_users = await execute_db(_get_daily_users)
                for user_id, lang in daily_users:
                    original_lang = user_language.get(user_id, 'ar')
                    user_language[user_id] = lang
                    channels = await db_get_user_channels_count(user_id)
                    total_posts = await db_get_user_total_posts(user_id)
                    unpublished = await db_get_user_unpublished_posts(user_id)
                    groups = await db_get_user_groups_count(user_id)
                    text = get_text(user_id, 'daily_stats').format(channels, total_posts, unpublished, groups)
                    try:
                        await safe_send_markdown(bot, user_id, text)
                    except:
                        pass
                    user_language[user_id] = original_lang
                    await asyncio.sleep(0.3)
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"خطأ في مهمة الإشعار اليومي: {e}")
            await asyncio.sleep(60)

async def weekly_reminder_task(bot):
    last_weekly_date = None
    while True:
        try:
            now = utc_now()
            now_mecca = utc_to_mecca(now)
            today_str = now_mecca.strftime("%Y-%m-%d")
            if last_weekly_date != today_str and now_mecca.weekday() == 6:
                last_weekly_date = today_str
                async def _get_weekly_users(conn):
                    cur = await conn.execute("SELECT user_id, notification_lang FROM user_reminder_settings WHERE weekly_report=1")
                    return await cur.fetchall()
                weekly_users = await execute_db(_get_weekly_users)
                for user_id, lang in weekly_users:
                    original_lang = user_language.get(user_id, 'ar')
                    user_language[user_id] = lang
                    channels = await db_get_user_channels_count(user_id)
                    total_posts = await db_get_user_total_posts(user_id)
                    unpublished = await db_get_user_unpublished_posts(user_id)
                    groups = await db_get_user_groups_count(user_id)
                    referral_stats = await db_get_referral_stats(user_id)
                    text = get_text(user_id, 'weekly_report').format(channels, total_posts, unpublished, groups, referral_stats['total_referrals'])
                    try:
                        await safe_send_markdown(bot, user_id, text)
                    except:
                        pass
                    user_language[user_id] = original_lang
                    await asyncio.sleep(0.3)
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"خطأ في مهمة الإشعار الأسبوعي: {e}")
            await asyncio.sleep(60)

async def cleanup_expired_sessions_improved():
    CLEANUP_SLEEP = 3600
    while True:
        await asyncio.sleep(CLEANUP_SLEEP)
        now = time_module.time()
        async def _cleanup_sessions(conn):
            await conn.execute("DELETE FROM web_sessions WHERE expires < ?", (now,))
            await conn.commit()
        await execute_db(_cleanup_sessions)
        async def _cleanup_tickets(conn):
            cutoff = (utc_now() - timedelta(days=30)).isoformat()
            await conn.execute("DELETE FROM support_tickets WHERE created_at < ? AND status='closed'", (cutoff,))
            await conn.commit()
        await execute_db(_cleanup_tickets)
        logger.info(f"✅ تم تنظيف الجلسات المنتهية والتذاكر القديمة")

async def broadcast_stats_periodically():
    while True:
        await asyncio.sleep(5)
        total, banned, posts, groups, channels = await db_stats()
        await ws_manager.broadcast({
            'type': 'stats',
            'data': {
                'total_users': total,
                'active_users': total - banned,
                'banned_users': banned,
                'pending_posts': posts,
                'groups': groups,
                'channels': channels
            }
        })

async def ensure_force_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None) -> bool:
    if user_id is None:
        if update.effective_user is None:
            return True
        user_id = update.effective_user.id
    if user_id == MAIN_ADMIN_ID or await is_bot_admin(user_id):
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

async def is_user_subscribed(bot, user_id, channel):
    if not channel:
        return True
    channel = channel.lstrip('@')
    try:
        member = await bot.get_chat_member(f"@{channel}", user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

async def panel_lock_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if await is_authorized_in_group(context.bot, chat_id, uid):
        await db_set_chat_lock(chat_id, True, uid)
        await safe_edit_markdown(query, get_text(uid, 'locked'))
    else:
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)

async def panel_unlock_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    chat_id = int(query.data.split(":")[-1])
    if await is_authorized_in_group(context.bot, chat_id, uid):
        await db_set_chat_lock(chat_id, False)
        await safe_edit_markdown(query, get_text(uid, 'unlocked'))
    else:
        await safe_query_answer(query, get_text(uid, 'admin_only'), show_alert=True)

async def panel_close_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    await query.message.delete()

async def check_subscribe_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    enabled = await db_get_force_subscribe_status()
    channel = await db_get_force_subscribe_channel()
    if enabled and channel:
        if await is_user_subscribed(context.bot, uid, channel):
            await safe_edit_markdown(query, "✅ تم التحقق! أنت مشترك الآن.")
            await main_menu_callback(update, context)
        else:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 اشترك", url=f"https://t.me/{channel.lstrip('@')}"),
                 InlineKeyboardButton("🔄 تأكد", callback_data=CallbackData.CHECK_SUBSCRIBE),
                 InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
            ])
            await safe_edit_markdown(query, f"❌ لم تشترك في @{channel.lstrip('@')}", reply_markup=kb)
    else:
        await safe_edit_markdown(query, "⚠️ الاشتراك الإجباري غير مفعل")

async def publish_all_channels_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_query_answer(query)
    if query is None:
        return
    uid = query.from_user.id
    channels = await db_get_channels(uid)
    if not channels:
        await query.edit_message_text("📭 لا توجد قنوات للنشر فيها.")
        return
    await query.edit_message_text("📤 جاري النشر في جميع القنوات...")
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
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit_markdown(query, result_text, reply_markup=keyboard)

async def message_handler_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    chat = update.effective_chat
    user = update.effective_user
    uid = user.id if user else 0
    text = update.message.text.strip() if update.message.text else ""
    if user and user.is_bot:
        return
    if text == "/cancel":
        context.user_data.pop('state', None)
        context.user_data.pop('support_mode', None)
        await update.message.reply_text(get_text(uid, 'cancelled'))
        if chat.type == 'private':
            await main_menu_callback(update, context)
        return
    if context.user_data.get('waiting_2fa') and text:
        if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE:
            try:
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
    state = context.user_data.get('state', '')
    if state == 'waiting_sendcode_confirmation':
        await handle_sendcode_confirmation_handler(update, context)
        return
    if state and state.startswith('adding_posts_'):
        session_key = f"session_{uid}"
        if text == "/cancel":
            context.user_data.pop(session_key, None)
            context.user_data.pop(f"session_target_{uid}", None)
            context.user_data.pop('state', None)
            await update.message.reply_text(get_text(uid, 'cancelled'))
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
        if cur >= target:
            active = context.user_data.get('active_channel') or await db_get_active_channel(uid)
            if not active:
                await update.message.reply_text(get_text(uid, 'error'))
                context.user_data.pop(session_key, None)
                context.user_data.pop('state', None)
                return
            saved = await db_save_posts(active, context.user_data[session_key])
            context.user_data.pop(session_key, None)
            context.user_data.pop(f"session_target_{uid}", None)
            context.user_data.pop('state', None)
            has_sub = await db_has_active_subscription(uid) or await db_has_used_trial(uid)
            auto_status = await db_auto_status(uid)
            if not has_sub:
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور\n⚠️ النشر التلقائي غير مفعل بسبب عدم وجود اشتراك\nاستخدم /trial للحصول على 30 يوماً مجاناً")
            elif not auto_status:
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور\n⚠️ النشر التلقائي معطل\nفعله من الإعدادات")
            else:
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور\n🔄 سيتم نشرها تلقائياً")
            await main_menu_callback(update, context)
        else:
            await update.message.reply_text(f"📥 {cur}/{target}")
        return
    if state and state.startswith('waiting_interval_minutes_'):
        ch_db_id = int(state.split('_')[-1])
        context.user_data.pop('state', None)
        try:
            minutes = int(text)
            if minutes < 1:
                minutes = 1
            await db_save_schedule(ch_db_id, 'interval_minutes', interval_minutes=minutes)
            await db_set_next_publish_date(ch_db_id, None)
            await update.message.reply_text(get_text(uid, 'interval_set'))
        except:
            await update.message.reply_text(get_text(uid, 'invalid_number'))
        await schedule_menu_callback(update, context)
        return
    if state and state.startswith('waiting_interval_hours_'):
        ch_db_id = int(state.split('_')[-1])
        context.user_data.pop('state', None)
        try:
            hours = int(text)
            if hours < 1:
                hours = 1
            await db_save_schedule(ch_db_id, 'interval_hours', interval_hours=hours)
            await db_set_next_publish_date(ch_db_id, None)
            await update.message.reply_text(get_text(uid, 'interval_set'))
        except:
            await update.message.reply_text(get_text(uid, 'invalid_number'))
        await schedule_menu_callback(update, context)
        return
    if state and state.startswith('waiting_interval_days_'):
        ch_db_id = int(state.split('_')[-1])
        context.user_data.pop('state', None)
        try:
            days = int(text)
            if days < 1:
                days = 1
            await db_save_schedule(ch_db_id, 'interval_days', interval_days=days)
            await db_set_next_publish_date(ch_db_id, None)
            await update.message.reply_text(get_text(uid, 'interval_set'))
        except:
            await update.message.reply_text(get_text(uid, 'invalid_number'))
        await schedule_menu_callback(update, context)
        return
    if state and state.startswith('waiting_dates_'):
        ch_db_id = int(state.split('_')[-1])
        context.user_data.pop('state', None)
        dates = text.split(',')
        valid_dates = []
        for d in dates:
            d = d.strip()
            try:
                datetime.strptime(d, '%Y-%m-%d')
                valid_dates.append(d)
            except:
                await update.message.reply_text(get_text(uid, 'invalid_date'))
                return
        await db_save_schedule(ch_db_id, 'dates', specific_dates=json.dumps(valid_dates))
        await db_set_next_publish_date(ch_db_id, None)
        await update.message.reply_text(get_text(uid, 'dates_saved'))
        await schedule_menu_callback(update, context)
        return
    if state and state.startswith('waiting_publish_time_'):
        ch_db_id = int(state.split('_')[-1])
        context.user_data.pop('state', None)
        try:
            time_str = text.strip()
            hour, minute = map(int, time_str.split(':'))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                await db_set_publish_time(ch_db_id, time_str)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text(get_text(uid, 'interval_set'))
            else:
                await update.message.reply_text(get_text(uid, 'invalid_time'))
        except:
            await update.message.reply_text(get_text(uid, 'invalid_time'))
        await schedule_menu_callback(update, context)
        return
    if state == 'waiting_for_channel_id':
        context.user_data.pop('state', None)
        new_id = await db_add_channel(uid, text, text)
        if new_id:
            context.user_data['active_channel'] = new_id
            await db_set_active_channel(uid, new_id)
            await update.message.reply_text(get_text(uid, 'channel_added').format(text))
        else:
            await update.message.reply_text(get_text(uid, 'channel_exists'))
        kb, title, active = await get_main_keyboard(uid)
        context.user_data['active_channel'] = active
        await safe_send_markdown(context.bot, uid, title, reply_markup=kb)
        return
    if state == 'waiting_for_group_security':
        context.user_data.pop('state', None)
        identifier = text.lstrip('@')
        async def _find_group(conn):
            if identifier.startswith('-') or identifier.isdigit():
                cur = await conn.execute("SELECT chat_id, chat_name FROM bot_groups WHERE chat_id=?", (int(identifier),))
            else:
                cur = await conn.execute("SELECT chat_id, chat_name FROM bot_groups WHERE username=?", (identifier,))
            return await cur.fetchone()
        row = await execute_db(_find_group)
        if not row:
            await update.message.reply_text("❌ لم يتم العثور على المجموعة")
            return
        chat_id, group_name = row
        if not await is_authorized_in_group(context.bot, chat_id, uid):
            await update.message.reply_text(get_text(uid, 'not_admin'))
            return
        settings = await db_get_security_settings(chat_id)
        text_msg = f"🔐 إعدادات أمان {group_name}\n🔗 روابط: {'✅' if settings['links'] else '❌'}\n@ معرفات: {'✅' if settings['mentions'] else '❌'}\n🚫 كلمات: {'✅' if settings.get('delete_banned_words', False) else '❌'}\n🔊 تحذير: {'✅' if settings['warn'] else '❌'}\n🚦 بطيء: {'✅' if settings['slow_mode'] else '❌'}\n🎯 ترحيب: {'✅' if settings['welcome_enabled'] else '❌'}\n👋 وداع: {'✅' if settings['goodbye_enabled'] else '❌'}"
        await update.message.reply_text(text_msg, reply_markup=security_keyboard(chat_id), parse_mode="MarkdownV2")
        return
    if state and state.startswith('waiting_for_group_banned_word_'):
        chat_id = int(state.split('_')[-1])
        context.user_data.pop('state', None)
        word = text.split()[0].lower() if text else ""
        if len(word) < 2:
            await update.message.reply_text("❌ الكلمة قصيرة جداً")
            return
        if await db_add_banned_word(word, chat_id, uid):
            await update.message.reply_text(f"✅ تم إضافة {word}")
        else:
            await update.message.reply_text(f"⚠️ {word} موجودة مسبقاً")
        return
    if state and state.startswith('waiting_for_remove_group_banned_word_'):
        chat_id = int(state.split('_')[-1])
        context.user_data.pop('state', None)
        word = text.lower()
        if await db_remove_banned_word(word, chat_id):
            await update.message.reply_text(f"✅ تم حذف {word}")
        else:
            await update.message.reply_text(f"⚠️ الكلمة {word} غير موجودة")
        return
    if state == 'waiting_for_admin_id_add':
        try:
            target_id = int(text)
            if target_id == MAIN_ADMIN_ID:
                await update.message.reply_text(get_text(uid, 'cannot_remove_main_admin'))
            else:
                await add_bot_admin(target_id)
                await security_audit.log("ADMIN_ADDED", uid, {"target": target_id}, "CRITICAL")
                await update.message.reply_text(get_text(uid, 'add_admin_success').format(target_id), parse_mode="MarkdownV2")
        except ValueError:
            await update.message.reply_text(get_text(uid, 'invalid_user_id'))
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    if state == 'waiting_for_admin_id_remove':
        try:
            target_id = int(text)
            if target_id == MAIN_ADMIN_ID:
                await update.message.reply_text(get_text(uid, 'cannot_remove_main_admin'))
            else:
                await remove_bot_admin(target_id)
                await security_audit.log("ADMIN_REMOVED", uid, {"target": target_id}, "CRITICAL")
                await update.message.reply_text(get_text(uid, 'remove_admin_success').format(target_id), parse_mode="MarkdownV2")
        except ValueError:
            await update.message.reply_text(get_text(uid, 'invalid_user_id'))
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    if state == 'admin_waiting_for_interval':
        context.user_data.pop('state', None)
        try:
            minutes = int(text)
            if minutes < 1:
                minutes = 1
            if minutes > 1440:
                minutes = 1440
            seconds = minutes * 60
            await db_set_publish_interval_seconds(seconds, uid, is_admin=True)
            await update.message.reply_text(f"✅ **تم ضبط وقت النشر العام بنجاح!**\n\n🕐 الوقت الجديد: {minutes} دقيقة ({seconds} ثانية)\n📌 سيتم تطبيق التغيير في دورة النشر التالية.")
        except ValueError:
            await update.message.reply_text("❌ رقم غير صالح. الرجاء إدخال عدد صحيح من الدقائق (1-1440).")
        await admin_panel_callback(update, context)
        return
    if state == 'waiting_for_update_text':
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
    if state == 'waiting_for_update_channel':
        context.user_data.pop('state', None)
        await db_set_updates_channel(text)
        await update.message.reply_text(f"✅ تم تعيين قناة التحديثات: {text}")
        await admin_panel_callback(update, context)
        return
    if state == 'admin_waiting_for_force_channel':
        context.user_data.pop('state', None)
        await db_set_force_subscribe_channel(text)
        await update.message.reply_text(f"✅ تم تعيين قناة الاشتراك الإجباري: {text}")
        await admin_panel_callback(update, context)
        return
    if state == 'waiting_for_broadcast':
        context.user_data.pop('state', None)
        confirm_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم، أرسل", callback_data=CallbackData.ADMIN_CONFIRM_BROADCAST),
             InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.ADMIN_PANEL)]
        ])
        context.user_data['broadcast_text'] = text
        await update.message.reply_text(f"📨 **تأكيد الإرسال الجماعي**\n\nالنص المرسل:\n━━━━━━━━━━━━━━\n{text[:500]}\n━━━━━━━━━━━━━━\n\n⚠️ سيتم إرسال هذه الرسالة إلى **جميع مستخدمي البوت**\nهل أنت متأكد؟", reply_markup=confirm_kb, parse_mode="MarkdownV2")
        return
    if state == 'waiting_for_sendcode_user':
        context.user_data.pop('state', None)
        try:
            target_user_id = int(text)
        except ValueError:
            await update.message.reply_text(get_text(uid, 'invalid_number'))
            return
        await db_set_allowed_sendcode_user(target_user_id)
        await security_audit.log("SENDCODE_PERMISSION_GRANTED", uid, {"target": target_user_id}, "CRITICAL")
        await update.message.reply_text(get_text(uid, 'sendcode_user_set').format(target_user_id), parse_mode="MarkdownV2")
        await admin_panel_callback(update, context)
        return
    if state == 'waiting_for_log_channel':
        context.user_data.pop('state', None)
        context.user_data['temp_log_channel_identifier'] = text
        await set_log_channel_command_handler(update, context)
        return
    if state == 'admin_waiting_for_keyword':
        context.user_data.pop('state', None)
        context.user_data['state'] = 'admin_waiting_for_reply'
        context.user_data['admin_keyword'] = text.lower()
        await update.message.reply_text("📝 أرسل الرد الذي تريده لهذه الكلمة:")
        return
    if state == 'admin_waiting_for_reply':
        context.user_data.pop('state', None)
        kw = context.user_data.pop('admin_keyword', '')
        reply = text
        if kw and reply:
            await db_add_reply(kw, reply)
            await update.message.reply_text(f"✅ تم إضافة رد للكلمة {kw}")
        else:
            await update.message.reply_text("❌ حدث خطأ")
        await admin_replies_callback(update, context)
        return
    if state == 'admin_del_reply':
        context.user_data.pop('state', None)
        kw = text.lower()
        if await db_del_reply(kw):
            await update.message.reply_text(f"✅ تم حذف رد {kw}")
        else:
            await update.message.reply_text(f"⚠️ الكلمة {kw} غير موجودة")
        await admin_replies_callback(update, context)
        return
    if state == 'waiting_for_reminder_days':
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
    if state == 'waiting_for_schedule_post':
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
    if context.user_data.get('support_mode') and chat.type == 'private' and text and not text.startswith('/'):
        ticket_num = await db_get_next_ticket_number()
        username = user.full_name or user.first_name or str(uid)
        clean_text = bleach.clean(text, strip=True)[:2000]
        await db_save_ticket(uid, username, clean_text, ticket_num)
        now_mecca = mecca_now()
        now_str = now_mecca.strftime("%Y-%m-%d %H:%M:%S")
        reply_text = f"✅ **تم استلام رسالتك!**\n📋 رقم التذكرة: #{ticket_num}\n🕐 {now_str}\n\nسيتم الرد عليك في أقرب وقت ممكن."
        await update.message.reply_text(reply_text, parse_mode="MarkdownV2")
        notification_text = f"📬 **تذكرة دعم جديدة**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 المستخدم: {username}\n🆔 المعرف: `{uid}`\n📋 رقم التذكرة: #{ticket_num}\n🕐 الوقت: {now_str}\n━━━━━━━━━━━━━━━━━━━━━━\n📝 **الرسالة:**\n{clean_text[:500]}\n━━━━━━━━━━━━━━━━━━━━━━\nللرد استخدم:\n`/support_reply {uid} نص الرد`"
        await context.bot.send_message(chat_id=MAIN_ADMIN_ID, text=notification_text, parse_mode="MarkdownV2")
        context.user_data['support_mode'] = False
        return
    if chat.type == 'private':
        if text == "/start":
            await start_command_handler(update, context)
        elif text == "/cancel":
            context.user_data.pop('state', None)
            await update.message.reply_text(get_text(uid, 'cancelled'))
            await main_menu_callback(update, context)

async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
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
            chat_type_name = "مجموعة" if chat.type == 'group' else "سوبر جروب"
            await send_addition_report(context.bot, inviter, chat, chat_type_name)
            owner_info = await detect_owner_type(context.bot, chat.id)
            hidden_owner_registered = False
            if owner_info.get('is_hidden', False):
                await db_register_hidden_owner_group(chat.id, added_by_id)
                hidden_owner_registered = True
                logger.info(f"🔒 تم تسجيل مالك مخفي تلقائياً للمجموعة {chat.id} (المضيف: {added_by_id})")
            elif owner_info.get('user_id'):
                await db_register_hidden_owner_group(chat.id, owner_info['user_id'])
                hidden_owner_registered = True
                logger.info(f"👑 تم تسجيل المالك تلقائياً للمجموعة {chat.id} (المالك: {owner_info['user_id']}")
            try:
                msg = "✅ **تم تفعيل البوت في المجموعة**"
                if hidden_owner_registered:
                    msg += "\n🔒 **تم تسجيل المالك تلقائياً**"
                else:
                    msg += "\n👑 **المالك غير مخفي**\nإذا كنت مالكاً مخفياً، استخدم /register_hidden_owner"
                await safe_send_markdown(context.bot, chat.id, msg)
            except:
                pass
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
            if chat.type == 'channel':
                await db_register_channel(chat.id, chat.title or "بدون اسم", adder.id)
                chat_type_name = "قناة"
            elif chat.type in ['group', 'supergroup']:
                await db_register_group(chat.id, chat.title or "بدون اسم", adder.id, chat.username)
                chat_type_name = "مجموعة" if chat.type == 'group' else "سوبر جروب"
            else:
                return
            await send_addition_report(context.bot, adder, chat, chat_type_name)

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

async def init_db_improved():
    async with aiosqlite.connect(str(DB_PATH), timeout=DB_TIMEOUT) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA cache_size=-64000")
        await conn.execute("PRAGMA temp_store=MEMORY")
        await conn.execute("PRAGMA wal_autocheckpoint=1000")
        await conn.execute("PRAGMA optimize")
        await conn.execute("PRAGMA max_page_count=1000000")
        await conn.execute("PRAGMA secure_delete=ON")
        await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, auto_publish INTEGER DEFAULT 1, banned INTEGER DEFAULT 0, trial_used INTEGER DEFAULT 0, subscription_end TEXT DEFAULT NULL, referral_code TEXT DEFAULT NULL, referred_by INTEGER DEFAULT NULL, active_channel INTEGER DEFAULT NULL)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, channel_id TEXT, channel_name TEXT, created_at TIMESTAMP, banned INTEGER DEFAULT 0, FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE)")
        await conn.execute("CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_db_id INTEGER, text TEXT, media_type TEXT DEFAULT 'text', media_file_id TEXT, published INTEGER DEFAULT 0, fail_count INTEGER DEFAULT 0, views_count INTEGER DEFAULT 0, last_view_time TIMESTAMP, created_at TIMESTAMP, FOREIGN KEY(channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE)")
        await conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS group_replies (keyword TEXT PRIMARY KEY, reply TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS group_security (chat_id INTEGER PRIMARY KEY, delete_links INTEGER DEFAULT 0, delete_mentions INTEGER DEFAULT 0, warn_message INTEGER DEFAULT 1, slow_mode INTEGER DEFAULT 0, slow_mode_seconds INTEGER DEFAULT 5, welcome_enabled INTEGER DEFAULT 0, welcome_text TEXT DEFAULT 'مرحباً {user} في {chat} 🤍', goodbye_enabled INTEGER DEFAULT 0, goodbye_text TEXT DEFAULT 'وداعاً {user} 👋', delete_banned_words INTEGER DEFAULT 0, auto_penalty TEXT DEFAULT 'none', auto_mute_duration INTEGER DEFAULT 60)")
        await conn.execute("CREATE TABLE IF NOT EXISTS group_settings (chat_id INTEGER PRIMARY KEY, anti_links INTEGER DEFAULT 0, anti_badwords INTEGER DEFAULT 0, welcome_msg INTEGER DEFAULT 1, mute_all INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS bot_admins (user_id INTEGER PRIMARY KEY)")
        await conn.execute("CREATE TABLE IF NOT EXISTS bot_groups (chat_id INTEGER PRIMARY KEY, chat_name TEXT, username TEXT, added_by INTEGER, added_at TIMESTAMP, banned INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS bot_channels (channel_id INTEGER PRIMARY KEY, channel_name TEXT, added_by INTEGER, added_at TIMESTAMP, banned INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_messages (user_id INTEGER, chat_id INTEGER, message_time TIMESTAMP, PRIMARY KEY (user_id, chat_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS users_cache (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_updated TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_warnings (user_id INTEGER, chat_id INTEGER, warnings INTEGER DEFAULT 0, PRIMARY KEY(user_id, chat_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS banned_words (id INTEGER PRIMARY KEY AUTOINCREMENT, word TEXT, chat_id INTEGER, added_by INTEGER, added_at TIMESTAMP, UNIQUE(word, chat_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS hidden_owner_groups (chat_id INTEGER PRIMARY KEY, owner_id INTEGER, is_hidden INTEGER DEFAULT 1)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_groups_link (user_id INTEGER, chat_id INTEGER, PRIMARY KEY(user_id, chat_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_levels (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, level INTEGER DEFAULT 1)")
        await conn.execute("CREATE TABLE IF NOT EXISTS support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, message TEXT, ticket_number INTEGER, status TEXT DEFAULT 'pending', created_at TIMESTAMP, replied INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS chat_locks (chat_id INTEGER PRIMARY KEY, locked INTEGER DEFAULT 0, locked_at TIMESTAMP, locked_by INTEGER)")
        await conn.execute("CREATE TABLE IF NOT EXISTS schedule (channel_db_id INTEGER PRIMARY KEY, schedule_type TEXT DEFAULT 'interval_minutes', interval_minutes INTEGER DEFAULT 12, interval_hours INTEGER DEFAULT 0, interval_days INTEGER DEFAULT 0, days_of_week TEXT DEFAULT '', specific_dates TEXT DEFAULT '', publish_time TEXT DEFAULT '00:00', next_publish_date TEXT, FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE)")
        await conn.execute("CREATE TABLE IF NOT EXISTS last_publish (channel_db_id INTEGER PRIMARY KEY, last_publish_time TIMESTAMP, FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE)")
        await conn.execute("CREATE TABLE IF NOT EXISTS scheduled_posts (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, text TEXT NOT NULL, publish_time TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, fail_count INTEGER DEFAULT 0)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_time ON scheduled_posts(publish_time)")
        await conn.execute("CREATE TABLE IF NOT EXISTS allowed_sendcode_user (id INTEGER PRIMARY KEY CHECK (id=1), user_id INTEGER)")
        await conn.execute("CREATE TABLE IF NOT EXISTS referrals (id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER NOT NULL, referred_id INTEGER NOT NULL, referred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_rewarded INTEGER DEFAULT 0, UNIQUE(referred_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS referral_rewards (user_id INTEGER PRIMARY KEY, referral_count INTEGER DEFAULT 0, total_reward_days INTEGER DEFAULT 0, claimed_reward_days INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS referral_settings (key TEXT PRIMARY KEY, value TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_reminder_settings (user_id INTEGER PRIMARY KEY, subscription_reminder INTEGER DEFAULT 1, daily_stats_reminder INTEGER DEFAULT 0, weekly_report INTEGER DEFAULT 1, reminder_days_before INTEGER DEFAULT 3, last_reminder_sent INTEGER DEFAULT 0, notification_lang TEXT DEFAULT 'ar')")
        await conn.execute("CREATE TABLE IF NOT EXISTS moderation_log (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER, action TEXT, duration_minutes INTEGER, moderator_id INTEGER, reason TEXT, created_at TIMESTAMP)")
        await conn.execute("CREATE TABLE IF NOT EXISTS contests (id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER, title TEXT, description TEXT, prize TEXT, end_date TEXT, status TEXT DEFAULT 'active', winner_id INTEGER, created_at TIMESTAMP)")
        await conn.execute("CREATE TABLE IF NOT EXISTS contest_participants (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, contest_id INTEGER, answer TEXT, joined_at TIMESTAMP, UNIQUE(user_id, contest_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS contest_winners (id INTEGER PRIMARY KEY AUTOINCREMENT, contest_id INTEGER, winner_id INTEGER, announced_at TIMESTAMP)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_profiles (user_id INTEGER PRIMARY KEY, bio TEXT, location TEXT, website TEXT, join_date TEXT, points INTEGER DEFAULT 0, level INTEGER DEFAULT 1, avatar_file_id TEXT, cover_file_id TEXT, badges TEXT, social_links TEXT, theme TEXT DEFAULT 'dark')")
        await conn.execute("CREATE TABLE IF NOT EXISTS web_sessions (session_id TEXT PRIMARY KEY, user_data TEXT, expires INTEGER)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_translation (user_id INTEGER PRIMARY KEY, lang TEXT DEFAULT 'off')")
        await conn.execute("CREATE TABLE IF NOT EXISTS channel_stats (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_db_id INTEGER NOT NULL, total_posts INTEGER DEFAULT 0, published_posts INTEGER DEFAULT 0, unpublished_posts INTEGER DEFAULT 0, total_views INTEGER DEFAULT 0, avg_views_per_post REAL DEFAULT 0, last_post_time TIMESTAMP, avg_time_between_posts REAL DEFAULT 0, best_publish_hour INTEGER DEFAULT 0, best_publish_day INTEGER DEFAULT 0, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE, UNIQUE(channel_db_id))")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_channel_published ON posts(channel_db_id, published)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_next ON schedule(next_publish_date)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_channels_user ON user_channels(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_banned_words_chat ON banned_words(chat_id, word)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_messages_time ON user_messages(message_time)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_channel_fail ON posts(channel_db_id, published, fail_count)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_subscription ON users(subscription_end)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_levels_points ON user_levels(points DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_moderation_chat ON moderation_log(chat_id, created_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_contests_active ON contests(status, end_date)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_channel_stats ON channel_stats(channel_db_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_views ON posts(views_count)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_published_views ON posts(published, views_count)")
        try:
            cursor = await conn.execute("PRAGMA table_info(group_security)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if 'auto_penalty' not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN auto_penalty TEXT DEFAULT 'none'")
                logger.info("✅ تم إضافة عمود auto_penalty إلى جدول group_security")
            if 'auto_mute_duration' not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN auto_mute_duration INTEGER DEFAULT 60")
                logger.info("✅ تم إضافة عمود auto_mute_duration إلى جدول group_security")
            await conn.commit()
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تحديث جدول group_security: {e}")
        try:
            cursor = await conn.execute("PRAGMA table_info(users)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if 'active_channel' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN active_channel INTEGER DEFAULT NULL")
                logger.info("✅ تم إضافة عمود active_channel إلى جدول users")
            if 'referral_code' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN referral_code TEXT DEFAULT NULL")
                logger.info("✅ تم إضافة عمود referral_code إلى جدول users")
            await conn.commit()
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تحديث جدول users: {e}")
        try:
            cursor = await conn.execute("PRAGMA table_info(posts)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if 'views_count' not in column_names:
                await conn.execute("ALTER TABLE posts ADD COLUMN views_count INTEGER DEFAULT 0")
                logger.info("✅ تم إضافة عمود views_count إلى جدول posts")
            if 'last_view_time' not in column_names:
                await conn.execute("ALTER TABLE posts ADD COLUMN last_view_time TIMESTAMP")
                logger.info("✅ تم إضافة عمود last_view_time إلى جدول posts")
            await conn.commit()
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تحديث جدول posts: {e}")
        await conn.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (MAIN_ADMIN_ID,))
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(DEFAULT_PUBLISH_INTERVAL_SECONDS),))
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('updates_channel', '')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('force_subscribe_enabled', '0')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('force_subscribe_channel', '')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_backup', '1')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_backup', '')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_ticket_number', '0')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('log_channel_id', '')")
        await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('reward_days_per_referral', '3')")
        await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('referral_bonus_points', '50')")
        await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('max_referrals_per_day', '5')")
        await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('welcome_bonus_points', '10')")
        await conn.commit()
    await db_pool.initialize()
    init_db_encryption()
    logger.info("✅ قاعدة البيانات جاهزة مع جميع التحسينات والإحصائيات المتقدمة")

# ============================================================
# تشغيل خادم الويب
# ============================================================
async def start_web_server():
    """تشغيل خادم الويب - متوافق مع Render وجميع البيئات"""
    try:
        # Render يحدد PORT في متغيرات البيئة
        port = int(os.getenv('PORT', WEB_PORT))
        host = os.getenv('HOST', WEB_HOST)
        
        # محاولة تشغيل على المنفذ المحدد
        try:
            runner = web.AppRunner(web_app)
            await runner.setup()
            site = web.TCPSite(runner, host, port)
            await site.start()
            logger.info(f"✅ خادم الويب يعمل على http://{host}:{port}")
            return
        except OSError as e:
            if "address already in use" in str(e):
                logger.warning(f"⚠️ المنفذ {port} مشغول، جرب المنافذ الأخرى...")
            else:
                raise
        
        # محاولة المنافذ البديلة
        ports_to_try = [8080, 8081, 8082, 8083, 8084, 8085, 10000]
        for p in ports_to_try:
            if p == port:
                continue
            try:
                runner = web.AppRunner(web_app)
                await runner.setup()
                site = web.TCPSite(runner, host, p)
                await site.start()
                logger.info(f"✅ خادم الويب يعمل على http://{host}:{p}")
                return
            except OSError:
                continue
        
        logger.error("❌ لا يمكن العثور على منفذ متاح لخادم الويب")
    except Exception as e:
        logger.error(f"❌ فشل تشغيل خادم الويب: {e}")

# ============================================================
# تطبيق الويب
# ============================================================
web_app = web.Application()

# ============================================================
# الدالة الرئيسية
# ============================================================
async def main():
    await init_db_improved()
    
    # إعداد الوكيل إذا لزم الأمر
    if USE_PROXY:
        request_kwargs = {
            'proxy_url': PROXY_URL,
            'read_timeout': 60.0,
            'write_timeout': 30.0,
            'connect_timeout': 30.0,
            'pool_timeout': 10.0,
            'connection_pool_size': MAX_CONNECTIONS
        }
        request = HTTPXRequest(**request_kwargs)
        application = Application.builder().token(TOKEN).request(request).build()
    else:
        request_kwargs = {
            'read_timeout': 60.0,
            'write_timeout': 30.0,
            'connect_timeout': 30.0,
            'pool_timeout': 10.0,
            'connection_pool_size': MAX_CONNECTIONS
        }
        request = HTTPXRequest(**request_kwargs)
        application = Application.builder().token(TOKEN).request(request).build()
    
    # إضافة معالج الأخطاء
    application.add_error_handler(global_error_handler)
    
    # ===================== الأوامر =====================
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("language", language_command_handler))
    application.add_handler(CommandHandler("syncgroup", syncgroup_command_handler))
    application.add_handler(CommandHandler("security", security_command_handler))
    application.add_handler(CommandHandler("trial", trial_command_handler))
    application.add_handler(CommandHandler("subscribe", subscribe_command_handler))
    application.add_handler(CommandHandler("help", help_command_handler))
    application.add_handler(CommandHandler("support", support_command_handler))
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
    application.add_handler(CommandHandler("register_hidden_owner", register_hidden_owner_handler))
    application.add_handler(CommandHandler("set_log_channel", set_log_channel_command_handler))
    application.add_handler(CommandHandler("support_reply", support_reply_command_handler))
    application.add_handler(CommandHandler("ban", handle_moderation_commands))
    application.add_handler(CommandHandler("mute", handle_moderation_commands))
    application.add_handler(CommandHandler("warn", handle_moderation_commands))
    application.add_handler(CommandHandler("kick", handle_moderation_commands))
    application.add_handler(CommandHandler("restrict", handle_moderation_commands))
    application.add_handler(CommandHandler("pin", handle_moderation_commands))
    application.add_handler(CommandHandler("unban", handle_moderation_commands))
    
    # ===================== معالجات الكولباك (مرتبة من الأكثر تحديداً إلى الأقل) =====================
    # 1. الكوبلات الأكثر تحديداً (معرفات فريدة)
    application.add_handler(CallbackQueryHandler(noop_callback, pattern=f"^{CallbackData.NOOP}$"))
    application.add_handler(CallbackQueryHandler(lang_callback_handler, pattern=f"^({CallbackData.LANG_AR}|{CallbackData.LANG_EN}|{CallbackData.LANG_FR}|{CallbackData.LANG_TR}|{CallbackData.LANG_ZH}|{CallbackData.LANG_RU})$"))
    
    # 2. الكوبلات ذات البادئات (تحتوي على معرفات)
    application.add_handler(CallbackQueryHandler(admin_restore_backup_select_callback, pattern=f"^{CallbackData.ADMIN_RESTORE_BACKUP_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_del_reply_callback, pattern=f"^{CallbackData.ADMIN_DEL_REPLY_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_del_banned_word_callback, pattern=f"^{CallbackData.ADMIN_DEL_BANNED_WORD_PREFIX}"))
    application.add_handler(CallbackQueryHandler(advanced_mute_duration_callback, pattern=f"^{CallbackData.ADV_MUTE_DURATION_PREFIX}"))
    
    # 3. الكوبلات المتبقية (مرتبة حسب الأهمية)
    application.add_handler(CallbackQueryHandler(handle_text_callbacks, pattern=f"^({CallbackData.RANK}|{CallbackData.TOP}|{CallbackData.SCHEDULE_POST}|{CallbackData.LANGUAGE})$"))
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
    application.add_handler(CallbackQueryHandler(confirm_recycle_callback, pattern=f"^{CallbackData.CONFIRM_RECYCLE}"))
    application.add_handler(CallbackQueryHandler(delete_single_post_callback, pattern=f"^{CallbackData.POSTS_DELETE_SINGLE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(confirm_clear_all_posts_callback, pattern=f"^{CallbackData.POSTS_CONFIRM_CLEAR_ALL_PREFIX}"))
    application.add_handler(CallbackQueryHandler(clear_all_posts_callback, pattern=f"^{CallbackData.POSTS_CLEAR_ALL_PREFIX}"))
    application.add_handler(CallbackQueryHandler(my_pending_stats_callback, pattern=f"^{CallbackData.STATS_PENDING}$"))
    application.add_handler(CallbackQueryHandler(my_full_stats_callback, pattern=f"^{CallbackData.STATS_FULL}$"))
    application.add_handler(CallbackQueryHandler(my_groups_callback, pattern=f"^{CallbackData.GROUPS_MY}$"))
    application.add_handler(CallbackQueryHandler(group_settings_callback, pattern=f"^{CallbackData.GROUPS_SETTINGS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(settings_menu_callback, pattern=f"^{CallbackData.SETTINGS_MENU}$"))
    application.add_handler(CallbackQueryHandler(toggle_auto_publish_callback, pattern=f"^{CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH}$"))
    application.add_handler(CallbackQueryHandler(schedule_menu_callback, pattern=f"^{CallbackData.SCHEDULE_MENU_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_interval_minutes_callback, pattern=f"^{CallbackData.SCHEDULE_SET_INTERVAL_MINUTES_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_interval_hours_callback, pattern=f"^{CallbackData.SCHEDULE_SET_INTERVAL_HOURS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_interval_days_callback, pattern=f"^{CallbackData.SCHEDULE_SET_INTERVAL_DAYS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_days_callback, pattern=f"^{CallbackData.SCHEDULE_SET_DAYS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_dates_callback, pattern=f"^{CallbackData.SCHEDULE_SET_DATES_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_publish_time_callback, pattern=f"^{CallbackData.SCHEDULE_SET_PUBLISH_TIME_PREFIX}"))
    application.add_handler(CallbackQueryHandler(day_select_callback, pattern=f"^{CallbackData.SCHEDULE_DAY_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(save_days_callback, pattern=f"^{CallbackData.SCHEDULE_SAVE_DAYS}$"))
    application.add_handler(CallbackQueryHandler(security_links_callback, pattern=f"^{CallbackData.SECURITY_LINKS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_mentions_callback, pattern=f"^{CallbackData.SECURITY_MENTIONS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_warn_callback, pattern=f"^{CallbackData.SECURITY_WARN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_slowmode_callback, pattern=f"^{CallbackData.SECURITY_SLOWMODE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_banned_words_menu_callback, pattern=f"^{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_welcome_callback, pattern=f"^{CallbackData.SECURITY_WELCOME_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_goodbye_callback, pattern=f"^{CallbackData.SECURITY_GOODBYE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_close_callback, pattern=f"^{CallbackData.SECURITY_CLOSE}$"))
    application.add_handler(CallbackQueryHandler(security_main_callback, pattern=f"^{CallbackData.SECURITY_MAIN}$"))
    application.add_handler(CallbackQueryHandler(banned_words_add_callback, pattern=f"^{CallbackData.BANNED_WORDS_ADD_PREFIX}"))
    application.add_handler(CallbackQueryHandler(banned_words_list_callback, pattern=f"^{CallbackData.BANNED_WORDS_LIST_PREFIX}"))
    application.add_handler(CallbackQueryHandler(banned_words_remove_callback, pattern=f"^{CallbackData.BANNED_WORDS_REMOVE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(help_callback, pattern=f"^{CallbackData.HELP}$"))
    application.add_handler(CallbackQueryHandler(support_menu_callback, pattern=f"^{CallbackData.SUPPORT_MENU}$"))
    application.add_handler(CallbackQueryHandler(support_help_callback, pattern=f"^{CallbackData.SUPPORT_HELP}$"))
    application.add_handler(CallbackQueryHandler(support_ticket_callback, pattern=f"^{CallbackData.SUPPORT_TICKET}$"))
    application.add_handler(CallbackQueryHandler(support_back_callback, pattern=f"^{CallbackData.SUPPORT_BACK}$"))
    application.add_handler(CallbackQueryHandler(trial_callback, pattern=f"^{CallbackData.TRIAL}$"))
    application.add_handler(CallbackQueryHandler(subscribe_menu_callback, pattern=f"^{CallbackData.SUBSCRIBE_MENU}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_1_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_1}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_2_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_2}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_30_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_30}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_90_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_90}$"))
    application.add_handler(CallbackQueryHandler(developer_callback, pattern=f"^{CallbackData.DEVELOPER}$"))
    application.add_handler(CallbackQueryHandler(updates_callback, pattern=f"^{CallbackData.UPDATES}$"))
    application.add_handler(CallbackQueryHandler(referral_menu_callback, pattern=f"^{CallbackData.REFERRAL_MENU}$"))
    application.add_handler(CallbackQueryHandler(referral_copy_link_callback, pattern=f"^{CallbackData.REFERRAL_COPY_LINK_PREFIX}"))
    application.add_handler(CallbackQueryHandler(referral_claim_reward_callback, pattern=f"^{CallbackData.REFERRAL_CLAIM_REWARD}$"))
    application.add_handler(CallbackQueryHandler(referral_list_callback, pattern=f"^{CallbackData.REFERRAL_LIST}$"))
    application.add_handler(CallbackQueryHandler(reminder_menu_callback, pattern=f"^{CallbackData.REMINDER_MENU}$"))
    application.add_handler(CallbackQueryHandler(reminder_toggle_sub_callback, pattern=f"^{CallbackData.REMINDER_TOGGLE_SUB}$"))
    application.add_handler(CallbackQueryHandler(reminder_toggle_daily_callback, pattern=f"^{CallbackData.REMINDER_TOGGLE_DAILY}$"))
    application.add_handler(CallbackQueryHandler(reminder_toggle_weekly_callback, pattern=f"^{CallbackData.REMINDER_TOGGLE_WEEKLY}$"))
    application.add_handler(CallbackQueryHandler(reminder_set_days_callback, pattern=f"^{CallbackData.REMINDER_SET_DAYS}$"))
    application.add_handler(CallbackQueryHandler(reminder_set_lang_callback, pattern=f"^{CallbackData.REMINDER_SET_LANG}$"))
    application.add_handler(CallbackQueryHandler(reminder_lang_callback, pattern=f"^{CallbackData.REMINDER_LANG_PREFIX}"))
    application.add_handler(CallbackQueryHandler(translation_menu_callback, pattern=f"^{CallbackData.TRANSLATION_MENU}$"))
    application.add_handler(CallbackQueryHandler(translation_off_callback, pattern=f"^{CallbackData.TRANSLATION_OFF}$"))
    application.add_handler(CallbackQueryHandler(translation_set_callback, pattern=f"^{CallbackData.TRANSLATION_SET_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=f"^{CallbackData.ADMIN_PANEL}$"))
    application.add_handler(CallbackQueryHandler(admin_users_callback, pattern=f"^{CallbackData.ADMIN_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_users_callback, pattern=f"^{CallbackData.ADMIN_BANNED_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_unban_all_users_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_all_channels_callback, pattern=f"^{CallbackData.ADMIN_ALL_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_channels_callback, pattern=f"^{CallbackData.ADMIN_BANNED_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_activate_all_channels_callback, pattern=f"^{CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_groups_callback, pattern=f"^{CallbackData.ADMIN_GROUPS}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_groups_callback, pattern=f"^{CallbackData.ADMIN_BANNED_GROUPS}$"))
    application.add_handler(CallbackQueryHandler(admin_unban_all_groups_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_GROUPS}$"))
    application.add_handler(CallbackQueryHandler(admin_bot_channels_callback, pattern=f"^{CallbackData.ADMIN_BOT_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_bot_channels_callback, pattern=f"^{CallbackData.ADMIN_BANNED_BOT_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_unban_all_bot_channels_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_BOT_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_monitor_users_callback, pattern=f"^{CallbackData.ADMIN_MONITOR_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_add_admin_callback, pattern=f"^{CallbackData.ADMIN_ADD_ADMIN}$"))
    application.add_handler(CallbackQueryHandler(admin_remove_admin_callback, pattern=f"^{CallbackData.ADMIN_REMOVE_ADMIN}$"))
    application.add_handler(CallbackQueryHandler(admin_ram_callback, pattern=f"^{CallbackData.ADMIN_RAM}$"))
    application.add_handler(CallbackQueryHandler(admin_stats_callback, pattern=f"^{CallbackData.ADMIN_STATS}$"))
    application.add_handler(CallbackQueryHandler(admin_metrics_callback, pattern=f"^{CallbackData.ADMIN_METRICS}$"))
    application.add_handler(CallbackQueryHandler(admin_backup_callback, pattern=f"^{CallbackData.ADMIN_BACKUP}$"))
    application.add_handler(CallbackQueryHandler(admin_restore_backup_callback, pattern=f"^{CallbackData.ADMIN_RESTORE_BACKUP}$"))
    application.add_handler(CallbackQueryHandler(admin_restore_backup_select_callback, pattern=f"^{CallbackData.ADMIN_RESTORE_BACKUP_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_backup_settings_callback, pattern=f"^{CallbackData.ADMIN_BACKUP_SETTINGS}$"))
    application.add_handler(CallbackQueryHandler(admin_toggle_auto_backup_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_AUTO_BACKUP}$"))
    application.add_handler(CallbackQueryHandler(admin_change_interval_callback, pattern=f"^{CallbackData.ADMIN_CHANGE_INTERVAL}$"))
    application.add_handler(CallbackQueryHandler(admin_send_update_callback, pattern=f"^{CallbackData.ADMIN_SEND_UPDATE}$"))
    application.add_handler(CallbackQueryHandler(admin_set_update_channel_callback, pattern=f"^{CallbackData.ADMIN_SET_UPDATE_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_updates_callback, pattern=f"^{CallbackData.ADMIN_UPDATES}$"))
    application.add_handler(CallbackQueryHandler(admin_force_subscribe_callback, pattern=f"^{CallbackData.ADMIN_FORCE_SUBSCRIBE}$"))
    application.add_handler(CallbackQueryHandler(admin_set_force_channel_callback, pattern=f"^{CallbackData.ADMIN_SET_FORCE_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_broadcast_callback, pattern=f"^{CallbackData.ADMIN_BROADCAST}$"))
    application.add_handler(CallbackQueryHandler(admin_confirm_broadcast_callback, pattern=f"^{CallbackData.ADMIN_CONFIRM_BROADCAST}$"))
    application.add_handler(CallbackQueryHandler(admin_support_tickets_callback, pattern=f"^{CallbackData.ADMIN_SUPPORT_TICKETS}$"))
    application.add_handler(CallbackQueryHandler(admin_delete_all_tickets_callback, pattern=f"^{CallbackData.ADMIN_DELETE_ALL_TICKETS}$"))
    application.add_handler(CallbackQueryHandler(admin_confirm_delete_tickets_callback, pattern=f"^{CallbackData.ADMIN_CONFIRM_DELETE_TICKETS}$"))
    application.add_handler(CallbackQueryHandler(admin_manage_sendcode_callback, pattern=f"^{CallbackData.ADMIN_MANAGE_SENDCODE}$"))
    application.add_handler(CallbackQueryHandler(admin_set_sendcode_user_callback, pattern=f"^{CallbackData.ADMIN_SET_SENDCODE_USER}$"))
    application.add_handler(CallbackQueryHandler(admin_show_log_channel_callback, pattern=f"^{CallbackData.ADMIN_SHOW_LOG_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_set_log_channel_callback, pattern=f"^{CallbackData.ADMIN_SET_LOG_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_replies_callback, pattern=f"^{CallbackData.ADMIN_REPLIES}$"))
    application.add_handler(CallbackQueryHandler(admin_add_reply_callback, pattern=f"^{CallbackData.ADMIN_ADD_REPLY}$"))
    application.add_handler(CallbackQueryHandler(admin_list_replies_callback, pattern=f"^{CallbackData.ADMIN_LIST_REPLIES}$"))
    application.add_handler(CallbackQueryHandler(admin_del_reply_callback, pattern=f"^{CallbackData.ADMIN_DEL_REPLY}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_words_callback, pattern=f"^{CallbackData.ADMIN_BANNED_WORDS}$"))
    application.add_handler(CallbackQueryHandler(admin_add_banned_word_callback, pattern=f"^{CallbackData.ADMIN_ADD_BANNED_WORD}$"))
    application.add_handler(CallbackQueryHandler(admin_list_banned_words_callback, pattern=f"^{CallbackData.ADMIN_LIST_BANNED_WORDS}$"))
    application.add_handler(CallbackQueryHandler(admin_remove_banned_word_callback, pattern=f"^{CallbackData.ADMIN_REMOVE_BANNED_WORD}$"))
    application.add_handler(CallbackQueryHandler(channel_stats_callback, pattern=f"^{CallbackData.CHANNEL_STATS}:"))
    application.add_handler(CallbackQueryHandler(channel_growth_callback, pattern=f"^{CallbackData.CHANNEL_GROWTH}:"))
    application.add_handler(CallbackQueryHandler(channel_stats_refresh_callback, pattern=f"^{CallbackData.CHANNEL_STATS_REFRESH}:"))
    application.add_handler(CallbackQueryHandler(my_channel_stats_callback, pattern=f"^{CallbackData.MY_CHANNEL_STATS}$"))
    application.add_handler(CallbackQueryHandler(check_subscribe_callback_handler, pattern=f"^{CallbackData.CHECK_SUBSCRIBE}$"))
    application.add_handler(CallbackQueryHandler(panel_lock_callback_handler, pattern=f"^{CallbackData.PANEL_LOCK_PREFIX}"))
    application.add_handler(CallbackQueryHandler(panel_unlock_callback_handler, pattern=f"^{CallbackData.PANEL_UNLOCK_PREFIX}"))
    application.add_handler(CallbackQueryHandler(panel_close_callback_handler, pattern=f"^{CallbackData.PANEL_CLOSE}$"))
    application.add_handler(CallbackQueryHandler(advanced_actions_callback, pattern=f"^{CallbackData.ADVANCED_ACTIONS}:"))
    application.add_handler(CallbackQueryHandler(group_action_ban_callback, pattern=f"^{CallbackData.GROUP_ACTION_BAN}:"))
    application.add_handler(CallbackQueryHandler(group_action_mute_callback, pattern=f"^{CallbackData.GROUP_ACTION_MUTE}:"))
    application.add_handler(CallbackQueryHandler(group_action_warn_callback, pattern=f"^{CallbackData.GROUP_ACTION_WARN}:"))
    application.add_handler(CallbackQueryHandler(group_action_kick_callback, pattern=f"^{CallbackData.GROUP_ACTION_KICK}:"))
    application.add_handler(CallbackQueryHandler(group_action_restrict_callback, pattern=f"^{CallbackData.GROUP_ACTION_RESTRICT}:"))
    application.add_handler(CallbackQueryHandler(group_action_pin_callback, pattern=f"^{CallbackData.GROUP_ACTION_PIN}:"))
    application.add_handler(CallbackQueryHandler(group_action_log_callback, pattern=f"^{CallbackData.GROUP_ACTION_LOG}:"))
    application.add_handler(CallbackQueryHandler(group_action_unban_callback, pattern=f"^{CallbackData.GROUP_ACTION_UNBAN}:"))
    application.add_handler(CallbackQueryHandler(security_select_group_callback, pattern=f"^{CallbackData.SECURITY_SELECT_GROUP}"))
    application.add_handler(CallbackQueryHandler(security_refresh_groups_callback, pattern=f"^{CallbackData.SECURITY_REFRESH_GROUPS}$"))
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
    application.add_handler(CallbackQueryHandler(publish_all_channels_callback_handler, pattern=f"^{CallbackData.PUBLISH_ALL_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(delete_group_callback, pattern=f"^{CallbackData.DELETE_GROUP_PREFIX}"))
    
    # ===================== معالجات الدفع =====================
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_callback_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback_handler))
    
    # ===================== معالجات المجموعات =====================
    application.add_handler(ChatMemberHandler(track_chat_add, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_bot_added))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    application.add_handler(MessageHandler(filters.CAPTION & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    
    # ===================== معالجات الرسائل الخاصة (المصححة) =====================
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler_main))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.AUDIO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.ANIMATION & filters.ChatType.PRIVATE, message_handler_main))
    # ✅ التصحيح: استخدام filters.Document() بدلاً من filters.Document
    application.add_handler(MessageHandler(filters.Document() & filters.ChatType.PRIVATE, message_handler_main))
    
    # ===================== تعيين الأوامر =====================
    commands = [
        BotCommand("start", "بدء البوت"),
        BotCommand("trial", "تجربة مجانية"),
        BotCommand("subscribe", "الاشتراك"),
        BotCommand("syncgroup", "تفعيل المجموعة"),
        BotCommand("security", "إعدادات الأمان"),
        BotCommand("register_hidden_owner", "تسجيل مالك مخفي"),
        BotCommand("rank", "رتبتك"),
        BotCommand("top", "أفضل 10"),
        BotCommand("stats", "إحصائيات القناة"),
        BotCommand("lock", "قفل المجموعة"),
        BotCommand("unlock", "فتح المجموعة"),
        BotCommand("schedule", "جدولة منشور"),
        BotCommand("panel", "لوحة التحكم"),
        BotCommand("language", "تغيير اللغة"),
        BotCommand("support", "مركز الدعم"),
        BotCommand("support_reply", "الرد على تذكرة"),
        BotCommand("help", "المساعدة"),
        BotCommand("developer", "المطور"),
        BotCommand("updates", "آخر التحديثات"),
        BotCommand("sendcode", "إرسال كود البوت"),
        BotCommand("set_log_channel", "تعيين قناة التقارير"),
        BotCommand("ban", "حظر مستخدم"),
        BotCommand("mute", "كتم مستخدم"),
        BotCommand("warn", "تحذير مستخدم"),
        BotCommand("kick", "طرد مستخدم"),
        BotCommand("restrict", "تقييد مستخدم"),
        BotCommand("pin", "تثبيت رسالة"),
        BotCommand("unban", "إلغاء حظر مستخدم"),
    ]
    await application.bot.set_my_commands(commands)
    
    # ===================== تشغيل المهام الخلفية =====================
    asyncio.create_task(auto_publish_loop_improved(application.bot))
    asyncio.create_task(auto_backup())
    asyncio.create_task(run_scheduled_posts_loop_improved(application.bot))
    asyncio.create_task(send_reminders_loop_improved(application.bot))
    asyncio.create_task(cleanup_expired_sessions_improved())
    asyncio.create_task(start_web_server())
    asyncio.create_task(broadcast_stats_periodically())
    asyncio.create_task(cleanup_points_cache())
    
    print(f"🚀 تم تشغيل {BOT_NAME} (الإصدار 19.0.3 - المصحح بالكامل)")
    print(f"✅ جميع التحسينات المطلوبة تم تطبيقها:")
    print(f"   • إعادة تدوير المنشورات تلقائياً مع تأكيد")
    print(f"   • إحصائيات متقدمة للقنوات")
    print(f"   • رسم بياني لنمو القناة")
    print(f"   • تحسين الذاكرة باستخدام LRU Cache")
    print(f"   • نظام Rate Limiting متقدم")
    print(f"   • دعم جميع أنواع الميديا")
    print(f"   • مترجم ذكي مع تجميع الطلبات")
    print(f"   • WebSocket للتحديثات الفورية")
    print(f"   • مصادقة ثنائية (2FA) مع مهلة زمنية")
    print(f"   • تحسين معالج الرسائل")
    print(f"   • جلسات ويب في قاعدة البيانات")
    print(f"   • تحسينات الأداء والاستقرار")
    print(f"   • إصلاحات أمنية متعددة")
    print(f"   • تسجيل المالك المخفي تلقائياً")
    print(f"   • تحسين Google Drive مع إعادة المحاولة")
    print(f"   • حل مشكلة المنفذ المشغول تلقائياً")
    print(f"   • أزرار محسّنة في قائمة المجموعات")
    print(f"   • إصلاح تداخل معالجات الكوبلات")
    print(f"   • توحيد جميع الكوبلات في كلاس واحد")
    print(f"   • ✅ إصلاح خطأ filters.Document")
    
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
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 تم إيقاف البوت")
    except Exception as e:
        logger.error(f"❌ خطأ فادح: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
