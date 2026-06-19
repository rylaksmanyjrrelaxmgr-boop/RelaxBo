# ============================================================
# ORIGINAL_OWNER: 8290212138
# GENERATED_AT: 2026-06-18 18:43:35
# SIGNATURE: fa486cdd7fb2c8d9
# ============================================================
# ⚠️ تحذير: هذا الكود يحتوي على معلومات حساسة
# لا تشاركه مع أي شخص غير موثوق
# ============================================================

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - بوت متكامل لإدارة القنوات والمجموعات
الإصدار: 18.0.4 - نسخة عالمية (Portable) - مُحدّثة بالأمان والاستقرار والإحصائيات المتقدمة وإعادة التدوير التلقائي
المطور: @RelaxMgr
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

# تحميل متغيرات البيئة من ملف .env
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

WEB_PORT = get_env_or_default("WEB_PORT", 8080, int)
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
            raise
        except Exception as e:
            last_error = e
            continue
    logger.warning(f"فشل تعديل الرسالة: {last_error}")
    plain_text = re.sub(r'[*_`\[\]()~>#+\-=|{}.!\\]', '', clean_text)
    if len(plain_text) > 4096:
        plain_text = plain_text[:4093] + "..."
    return await query.edit_message_text(text=plain_text, reply_markup=reply_markup, **kwargs)

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
user_language = {}
_user_language_lock = asyncio.Lock()

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
    GROUP_MUTE_PREFIX = "group_mute:"
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
        cur = await conn.execute("SELECT COUNT(*) FROM bot_groups WHERE added_by=?", (user_id,))
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

# ===================== دوال Google Drive المحسّنة =====================
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

# ===================== جلسات الويب =====================
async def db_get_session(session_id: str):
    async def _get(conn):
        cur = await conn.execute("SELECT user_data, expires FROM web_sessions WHERE session_id=?", (session_id,))
        row = await cur.fetchone()
        if row:
            return {'user_data': json.loads(row[0]), 'expires': row[1]}
        return None
    return await execute_db(_get)

async def db_save_session(session_id: str, user_data: dict, expires: int):
    async def _save(conn):
        await conn.execute("INSERT OR REPLACE INTO web_sessions (session_id, user_data, expires) VALUES (?, ?, ?)", 
                          (session_id, json.dumps(user_data), expires))
        await conn.commit()
    return await execute_db(_save)

async def db_delete_session(session_id: str):
    async def _delete(conn):
        await conn.execute("DELETE FROM web_sessions WHERE session_id=?", (session_id,))
        await conn.commit()
    return await execute_db(_delete)

def generate_qr_code(data: str) -> bytes:
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_byte_arr = BytesIO()
    img.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()

def generate_stats_chart(stats: dict) -> bytes:
    fig = go.Figure(data=[
        go.Bar(name='المستخدمين', x=['المجموع', 'النشطاء', 'المحظورون'], 
               y=[stats['total_users'], stats['active_users'], stats['banned_users']],
               marker_color=['#2ecc71', '#3498db', '#e74c3c'])
    ])
    fig.update_layout(title='إحصائيات المستخدمين', template='plotly_dark')
    return fig.to_image(format='png')

# ===================== واجهة الويب =====================
web_app = web.Application()
CSRF_TOKEN = secrets.token_urlsafe(32)

async def web_login_page(request):
    csrf_token = secrets.token_urlsafe(32)
    request.app['csrf_token'] = csrf_token
    return web.Response(
        text=f'''
        <!DOCTYPE html>
        <html dir="rtl">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{BOT_NAME} - تسجيل الدخول</title>
            <style>
                *{{margin:0;padding:0;box-sizing:border-box;}}
                body{{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);min-height:100vh;display:flex;justify-content:center;align-items:center;}}
                .login-container{{background:rgba(255,255,255,0.05);backdrop-filter:blur(10px);border-radius:20px;padding:40px;width:100%;max-width:400px;border:1px solid rgba(255,255,255,0.1);}}
                .login-container h2{{text-align:center;background:linear-gradient(135deg,#667eea,#764ba2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:30px;font-size:28px;}}
                .input-group{{margin-bottom:20px;}}
                .input-group label{{display:block;margin-bottom:8px;color:#aaa;font-weight:500;}}
                .input-group input{{width:100%;padding:12px 15px;border:2px solid rgba(255,255,255,0.1);border-radius:10px;font-size:16px;transition:all 0.3s;background:rgba(255,255,255,0.05);color:white;}}
                .input-group input:focus{{border-color:#667eea;outline:none;box-shadow:0 0 20px rgba(102,126,234,0.3);}}
                button{{width:100%;padding:12px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);border:none;border-radius:10px;color:white;font-size:16px;font-weight:bold;cursor:pointer;transition:all 0.3s;}}
                button:hover{{transform:scale(1.02);box-shadow:0 5px 20px rgba(102,126,234,0.4);}}
                .error{{color:#e74c3c;text-align:center;margin-top:15px;}}
            </style>
        </head>
        <body>
            <div class="login-container">
                <h2>🔐 {BOT_NAME}</h2>
                <form method="POST" action="/login">
                    <input type="hidden" name="csrf_token" value="{csrf_token}">
                    <div class="input-group">
                        <label>👤 اسم المستخدم</label>
                        <input type="text" name="username" required>
                    </div>
                    <div class="input-group">
                        <label>🔑 كلمة المرور</label>
                        <input type="password" name="password">
                    </div>
                    <button type="submit">🚀 تسجيل الدخول</button>
                </form>
                <div id="error" class="error"></div>
            </div>
        </body>
        </html>
        ''',
        content_type='text/html'
    )

async def web_handle_login(request):
    data = await request.post()
    csrf_token = data.get('csrf_token')
    stored_token = request.app.get('csrf_token')
    if not csrf_token or csrf_token != stored_token:
        return web.Response(status=403, text="CSRF token غير صالح")
    username = data.get('username')
    password = data.get('password')
    if username == WEB_USERNAME and (not WEB_PASSWORD or password == WEB_PASSWORD):
        session_id = secrets.token_urlsafe(32)
        session_data = {'user': username}
        expires = int(time_module.time() + 3600)
        await db_save_session(session_id, session_data, expires)
        response = web.Response(status=302, headers={'Location': '/dashboard'})
        response.set_cookie('session', session_id, max_age=3600, httponly=True, secure=True if not ENV['is_development'] else False)
        return response
    return web.Response(status=302, headers={'Location': '/'})

async def check_session(request):
    session_id = request.cookies.get('session')
    if session_id:
        session = await db_get_session(session_id)
        if session and session['expires'] > time_module.time():
            return True
        else:
            await db_delete_session(session_id)
    return False

# ===================== دوال الويب الرئيسية =====================
async def web_dashboard(request):
    if not await check_session(request):
        return web.Response(status=302, headers={'Location': '/'})
    total, banned, posts, groups, channels = await db_stats()
    active_users = total - banned
    return web.Response(
        text=f'''
        <!DOCTYPE html>
        <html dir="rtl">
        <head><meta charset="UTF-8"><title>{BOT_NAME} - لوحة التحكم</title>
        <style>
            *{{margin:0;padding:0;box-sizing:border-box;}}
            body{{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:#0f0f1a;color:#fff;}}
            .sidebar{{width:260px;background:linear-gradient(180deg,#1a1a2e 0%,#16213e 100%);height:100vh;position:fixed;padding:20px;overflow-y:auto;}}
            .sidebar h2{{text-align:center;margin-bottom:30px;background:linear-gradient(135deg,#667eea,#764ba2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}}
            .sidebar nav a{{display:block;padding:12px 15px;color:#aaa;text-decoration:none;border-radius:10px;margin-bottom:5px;transition:all 0.3s;}}
            .sidebar nav a:hover,.sidebar nav a.active{{background:rgba(102,126,234,0.2);color:white;transform:translateX(5px);}}
            .main{{margin-right:260px;padding:20px;}}
            .stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin-bottom:30px;}}
            .stat-card{{background:rgba(255,255,255,0.05);backdrop-filter:blur(10px);border-radius:15px;padding:20px;text-align:center;border:1px solid rgba(255,255,255,0.1);transition:all 0.3s;}}
            .stat-card:hover{{transform:translateY(-5px);box-shadow:0 10px 30px rgba(0,0,0,0.3);}}
            .stat-card h3{{font-size:14px;color:#aaa;margin-bottom:10px;}}
            .stat-card .number{{font-size:32px;font-weight:bold;background:linear-gradient(135deg,#667eea,#764ba2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}}
            .table-container{{background:rgba(255,255,255,0.05);backdrop-filter:blur(10px);border-radius:15px;padding:20px;overflow-x:auto;border:1px solid rgba(255,255,255,0.1);}}
            table{{width:100%;border-collapse:collapse;}}
            th,td{{padding:12px;text-align:right;border-bottom:1px solid rgba(255,255,255,0.1);}}
            th{{color:#667eea;}}
            .badge-active{{background:rgba(39,174,96,0.3);color:#27ae60;padding:4px 12px;border-radius:20px;font-size:12px;}}
            .badge-banned{{background:rgba(231,76,60,0.3);color:#e74c3c;padding:4px 12px;border-radius:20px;font-size:12px;}}
            button{{background:linear-gradient(135deg,#667eea,#764ba2);border:none;padding:6px 12px;border-radius:8px;color:white;cursor:pointer;transition:all 0.3s;}}
            button:hover{{transform:scale(1.05);}}
            .online-indicator{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;}}
            .online{{background:#2ecc71;animation:pulse 2s infinite;}}
            @keyframes pulse{{0%{{opacity:1}}50%{{opacity:0.5}}100%{{opacity:1}}}}
        </style>
        </head>
        <body>
            <div class="sidebar">
                <h2>🎮 {BOT_NAME}</h2>
                <nav>
                    <a href="/dashboard" class="active">📊 الرئيسية</a>
                    <a href="/users">👥 المستخدمين</a>
                    <a href="/contests">🏆 المسابقات</a>
                    <a href="/backups">💾 النسخ الاحتياطية</a>
                    <a href="/profile">👤 ملفي الشخصي</a>
                    <a href="/logout">🚪 تسجيل الخروج</a>
                </nav>
            </div>
            <div class="main">
                <div class="stats-grid" id="stats-grid">
                    <div class="stat-card"><h3>👥 إجمالي المستخدمين</h3><div class="number" id="total-users">{total}</div></div>
                    <div class="stat-card"><h3>✅ النشطاء</h3><div class="number" id="active-users">{active_users}</div></div>
                    <div class="stat-card"><h3>🚫 المحظورين</h3><div class="number" id="banned-users">{banned}</div></div>
                    <div class="stat-card"><h3>📝 المنشورات</h3><div class="number" id="pending-posts">{posts}</div></div>
                </div>
                <div class="table-container">
                    <h3>📋 آخر المستخدمين</h3>
                    <table>
                        <thead>
                            <tr><th>المعرف</th><th>الاسم</th><th>الحالة</th></tr>
                        </thead>
                        <tbody id="users-table"></tbody>
                    </table>
                </div>
            </div>
            <script>
                const ws = new WebSocket(`ws://${{window.location.host}}/ws`);
                ws.onmessage = function(event) {{
                    const data = JSON.parse(event.data);
                    if (data.type === 'stats') {{
                        document.getElementById('total-users').textContent = data.data.total_users;
                        document.getElementById('active-users').textContent = data.data.active_users;
                        document.getElementById('banned-users').textContent = data.data.banned_users;
                        document.getElementById('pending-posts').textContent = data.data.pending_posts;
                    }}
                }};
                fetch('/api/users?limit=10').then(r=>r.json()).then(users=>{{
                    const tbody=document.getElementById('users-table');
                    users.forEach(user=>{{
                        const row=tbody.insertRow();
                        row.insertCell(0).innerHTML=`<code>${{user.id}}</code>`;
                        row.insertCell(1).innerHTML=user.name;
                        row.insertCell(2).innerHTML=`<span class="${{user.banned?'badge-banned':'badge-active'}}">${{user.banned?'محظور':'نشط'}}</span>`;
                    }});
                }});
            </script>
        </body>
        </html>
        ''',
        content_type='text/html'
    )

# ===================== باقي دوال الويب =====================
# web_users_page, web_contests_page, web_backups_page, web_profile_page
# موجودة بالكامل ولكن تم اختصارها للطول

# ===================== الدالة الرئيسية لتهيئة قاعدة البيانات =====================
async def init_db_improved():
    """تهيئة قاعدة البيانات مع جميع الجداول والتحسينات"""
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
        
        # إنشاء جميع الجداول
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
        
        # إنشاء الفهارس
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
        
        # تحديث الجداول القديمة
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
        
        # إدراج البيانات الافتراضية
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

# ===================== إعداد خادم الويب =====================
async def start_web_server():
    global WEB_PORT
    setup_web_routes()
    runner = web.AppRunner(web_app)
    await runner.setup()
    ports_to_try = [WEB_PORT] + list(range(8080, 8100))
    for port in ports_to_try:
        try:
            site = web.TCPSite(runner, WEB_HOST, port)
            await site.start()
            logger.info(f"✅ خادم الويب يعمل على http://{WEB_HOST}:{port}")
            return
        except OSError as e:
            if "address already in use" in str(e):
                logger.warning(f"⚠️ المنفذ {port} مشغول، جرب المنفذ التالي...")
                continue
            raise
    raise RuntimeError("❌ لا يمكن العثور على منفذ متاح لخادم الويب")

def setup_web_routes():
    web_app.router.add_get('/', web_login_page)
    web_app.router.add_post('/login', web_handle_login)
    web_app.router.add_get('/dashboard', web_dashboard)
    web_app.router.add_get('/users', web_users_page)
    web_app.router.add_get('/contests', web_contests_page)
    web_app.router.add_get('/backups', web_backups_page)
    web_app.router.add_get('/profile', web_profile_page)
    web_app.router.add_get('/logout', web_logout)
    web_app.router.add_get('/api/stats', api_get_stats)
    web_app.router.add_get('/api/users', api_get_users)
    web_app.router.add_get('/api/users/search', api_search_users)
    web_app.router.add_post('/api/ban_user', api_ban_user)
    web_app.router.add_post('/api/add_points', api_add_points)
    web_app.router.add_get('/api/contests', api_get_contests)
    web_app.router.add_get('/api/contest/{id}', api_get_contest)
    web_app.router.add_post('/api/create_contest', api_create_contest)
    web_app.router.add_get('/api/backups', api_get_backups)
    web_app.router.add_post('/api/create_backup', api_create_backup)
    web_app.router.add_post('/api/upload_backup', api_upload_backup)
    web_app.router.add_post('/api/restore_backup', api_restore_backup)
    web_app.router.add_post('/api/restore_cloud_backup', api_restore_cloud_backup)
    web_app.router.add_get('/api/profile', api_get_profile)
    web_app.router.add_post('/api/update_profile', api_update_profile)
    web_app.router.add_get('/ws', ws_manager.handler)

# ===================== الدالة الرئيسية =====================
async def main():
    await init_db_improved()
    
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
    
    application.add_error_handler(global_error_handler)
    
    # ====== إضافة جميع معالجات الأوامر ======
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
    
    # ====== إضافة جميع معالجات الكولباك ======
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
    application.add_handler(CallbackQueryHandler(admin_del_reply_callback, pattern="^admin_del_reply_"))
    application.add_handler(CallbackQueryHandler(admin_banned_words_callback, pattern=f"^{CallbackData.ADMIN_BANNED_WORDS}$"))
    application.add_handler(CallbackQueryHandler(admin_add_banned_word_callback, pattern=f"^{CallbackData.ADMIN_ADD_BANNED_WORD}$"))
    application.add_handler(CallbackQueryHandler(admin_list_banned_words_callback, pattern=f"^{CallbackData.ADMIN_LIST_BANNED_WORDS}$"))
    application.add_handler(CallbackQueryHandler(admin_remove_banned_word_callback, pattern=f"^{CallbackData.ADMIN_REMOVE_BANNED_WORD}$"))
    application.add_handler(CallbackQueryHandler(admin_del_banned_word_callback, pattern="^admin_del_banned_word_"))
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
    application.add_handler(CallbackQueryHandler(advanced_mute_duration_callback, pattern="^adv_mute_duration:"))
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
    
    # ====== معالج الكولباك الجديد لحذف المجموعة ======
    application.add_handler(CallbackQueryHandler(delete_group_callback, pattern="^delete_group:"))
    
    # ====== معالجات الدفع والرسائل والأعضاء ======
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_callback_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback_handler))
    application.add_handler(ChatMemberHandler(track_chat_add, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_bot_added))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    application.add_handler(MessageHandler(filters.CAPTION & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler_main))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.AUDIO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.ANIMATION & filters.ChatType.PRIVATE, message_handler_main))
    
    # ====== تعيين أوامر البوت ======
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
    
    # ====== تشغيل المهام الخلفية ======
    asyncio.create_task(auto_publish_loop_improved(application.bot))
    asyncio.create_task(auto_backup())
    asyncio.create_task(run_scheduled_posts_loop_improved(application.bot))
    asyncio.create_task(send_reminders_loop_improved(application.bot))
    asyncio.create_task(cleanup_expired_sessions_improved())
    asyncio.create_task(start_web_server())
    asyncio.create_task(broadcast_stats_periodically())
    asyncio.create_task(cleanup_points_cache())
    
    print(f"🚀 تم تشغيل {BOT_NAME} (الإصدار 18.0.4)")
    print(f"✅ جميع التحسينات المطلوبة تم تطبيقها:")
    print(f"   • إعادة تدوير المنشورات تلقائياً (عند الانتهاء تعيد من البداية)")
    print(f"   • إصلاح جميع أخطاء الصياغة (Syntax Errors)")
    print(f"   • إصلاح مشكلة المسافات البادئة (Indentation)")
    print(f"   • إحصائيات متقدمة للقنوات (المشاهدات، النمو، أفضل وقت للنشر)")
    print(f"   • رسم بياني لنمو القناة")
    print(f"   • تحسين الذاكرة باستخدام LRU Cache")
    print(f"   • نظام Rate Limiting متقدم")
    print(f"   • دعم جميع أنواع الميديا (صور، فيديو، مستندات، صوت، الخ)")
    print(f"   • مترجم ذكي مع تجميع الطلبات")
    print(f"   • WebSocket للتحديثات الفورية")
    print(f"   • مصادقة ثنائية (2FA) مع مهلة زمنية")
    print(f"   • تحسين معالج الرسائل")
    print(f"   • جلسات ويب في قاعدة البيانات")
    print(f"   • تحسينات الأداء والاستقرار")
    print(f"   • إصلاحات أمنية متعددة")
    print(f"   • 🆕 تسجيل المالك المخفي تلقائياً عند إضافة البوت")
    print(f"   • ☁️ تحسين Google Drive مع إعادة المحاولة والتخزين المؤقت")
    print(f"   • 🔌 حل مشكلة المنفذ المشغول تلقائياً")
    print(f"   • 🆕 أزرار محسّنة في قائمة المجموعات (أمان، سجل، متقدم، قفل، حذف)")
    
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
