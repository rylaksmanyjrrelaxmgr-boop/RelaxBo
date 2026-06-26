#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - بوت متكامل لإدارة القنوات والمجموعات
الإصدار: 18.0.5 - نسخة عالمية (Portable) - مُحدّثة بالأمان والاستقرار والإحصائيات المتقدمة وإعادة التدوير التلقائي
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

# ===================== واجهة الويب =====================
web_app = web.Application()
CSRF_TOKEN = secrets.token_urlsafe(32)
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
    if not query or not query.message:
        return None
    
    current_text = query.message.text or ""
    current_reply_markup = query.message.reply_markup
    
    if current_text == text:
        if reply_markup is None and current_reply_markup is None:
            try:
                await query.answer("✅ تم التحديث")
            except:
                pass
            return None
        elif reply_markup is not None and current_reply_markup is not None:
            if str(reply_markup) == str(current_reply_markup):
                try:
                    await query.answer("✅ تم التحديث")
                except:
                    pass
                return None
    
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
            error_msg = str(e).lower()
            if "can't parse entities" in error_msg:
                continue
            if "message is not modified" in error_msg:
                try:
                    await query.answer("✅ تم التحديث")
                except:
                    pass
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
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            try:
                await query.answer("✅ تم التحديث")
            except:
                pass
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
            'channel_banned': "🚫 القناة محظورة",
            'channel_unbanned': "✅ تم إلغاء حظر القناة",
            'no_banned_channels': "📭 لا توجد قنوات محظورة",
            'banned_channels_list': "🚫 **القنوات المحظورة:**\n━━━━━━━━━━━━━━━━━━━━━━",
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
            'channel_banned': "🚫 Channel banned",
            'channel_unbanned': "✅ Channel unbanned",
            'no_banned_channels': "📭 No banned channels",
            'banned_channels_list': "🚫 **Banned Channels:**\n━━━━━━━━━━━━━━━━━━━━━━",
        }
    }
    lang_texts = texts.get(lang, texts['ar'])
    return lang_texts.get(key, key)

async def set_user_language(user_id: int, lang: str):
    async with _user_language_lock:
        user_language[user_id] = lang

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
    
    # إدارة حظر القنوات

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
        if row and row[0]:
            channel = row[0].strip()
            if channel.startswith('@'):
                channel = channel[1:]
            return channel if channel else None
        return None
    return await execute_db(_get)

async def db_set_updates_channel(channel: str):
    if not channel:
        return False
    channel = channel.strip()
    if channel.startswith('@'):
        channel = channel[1:]
    if not channel:
        return False
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('updates_channel', ?)", (channel,))
        await conn.commit()
    await execute_db(_set)
    logger.info(f"✅ تم حفظ قناة التحديثات: {channel}")
    return True

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

# ===================== دوال حظر القنوات =====================

    """حظر قناة المستخدم"""
    async def _ban(conn):
        await conn.execute(
            "UPDATE user_channels SET banned = 1 WHERE channel_id = ?",
            (channel_id,)
        )
        await conn.commit()
        return True
    return await execute_db(_ban)

    """إلغاء حظر قناة المستخدم"""
    async def _unban(conn):
        await conn.execute(
            "UPDATE user_channels SET banned = 0 WHERE channel_id = ?",
            (channel_id,)
        )
        await conn.commit()
        return True
    return await execute_db(_unban)

    """جلب القنوات المحظورة"""
    async def _get(conn):
        cur = await conn.execute("""
            SELECT channel_id, channel_name, user_id 
            FROM user_channels 
            WHERE banned = 1
            ORDER BY created_at DESC
        """)
        rows = await cur.fetchall()
        return [{'channel_id': row[0], 'channel_name': row[1], 'user_id': row[2]} for row in rows]
    return await execute_db(_get)

    """التحقق من حالة القناة"""
    async def _check(conn):
        cur = await conn.execute(
            "SELECT banned FROM user_channels WHERE channel_id = ?",
            (channel_id,)
        )
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_check)

    """حظر جميع قنوات المستخدم"""
    async def _ban(conn):
        await conn.execute(
            "UPDATE user_channels SET banned = 1 WHERE user_id = ?",
            (user_id,)
        )
        await conn.commit()
        cur = await conn.execute(
            "SELECT COUNT(*) FROM user_channels WHERE user_id = ?",
            (user_id,)
        )
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_ban)

# ===================== دوال حظر القنوات - الأوامر =====================

    """حظر قناة المستخدم"""
    user_id = update.effective_user.id
    if user_id != MAIN_ADMIN_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمطور فقط!")
        return
    
    args = context.args
    if not args:
        return
    
    channel_id = args[0]
    
    # التحقق من وجود القناة
    async def _check_channel(conn):
        cur = await conn.execute("SELECT channel_id, channel_name FROM user_channels WHERE channel_id = ?", (channel_id,))
        return await cur.fetchone()
    
    channel = await execute_db(_check_channel)
    if not channel:
        await update.message.reply_text(f"❌ **القناة غير موجودة:** `{channel_id}`")
        return
    
    # حظر القناة
    
    if success:
        await update.message.reply_text(
            f"✅ **تم حظر القناة:** `{channel_id}`\n"
            f"📌 اسم القناة: {channel[1]}\n"
            f"🚫 لن يتم النشر في هذه القناة."
        )
        await security_audit.log("CHANNEL_BANNED", user_id, {"channel_id": channel_id, "channel_name": channel[1]}, "HIGH")
    else:
        await update.message.reply_text(f"❌ **فشل حظر القناة:** `{channel_id}`")

    """إلغاء حظر قناة المستخدم"""
    user_id = update.effective_user.id
    if user_id != MAIN_ADMIN_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمطور فقط!")
        return
    
    args = context.args
    if not args:
        return
    
    channel_id = args[0]
    
    # التحقق من وجود القناة
    async def _check_channel(conn):
        cur = await conn.execute("SELECT channel_id, channel_name FROM user_channels WHERE channel_id = ?", (channel_id,))
        return await cur.fetchone()
    
    channel = await execute_db(_check_channel)
    if not channel:
        await update.message.reply_text(f"❌ **القناة غير موجودة:** `{channel_id}`")
        return
    
    # إلغاء حظر القناة
    
    if success:
        await update.message.reply_text(
            f"✅ **تم إلغاء حظر القناة:** `{channel_id}`\n"
            f"📌 اسم القناة: {channel[1]}\n"
            f"✅ سيتم النشر في هذه القناة."
        )
        await security_audit.log("CHANNEL_UNBANNED", user_id, {"channel_id": channel_id, "channel_name": channel[1]}, "HIGH")
    else:
        await update.message.reply_text(f"❌ **فشل إلغاء حظر القناة:** `{channel_id}`")

async def banned_channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض القنوات المحظورة"""
    user_id = update.effective_user.id
    if user_id != MAIN_ADMIN_ID and not await is_bot_admin(user_id):
        await update.message.reply_text("🔒 هذا الأمر للمطور فقط!")
        return
    
    
    if not channels:
        await update.message.reply_text("📭 لا توجد قنوات محظورة")
        return
    
    text = "🚫 **القنوات المحظورة:**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for ch in channels:
        text += f"• **القناة:** `{ch['channel_id']}`\n"
        text += f"  📌 **الاسم:** {ch['channel_name']}\n"
        text += f"  👤 **المستخدم:** `{ch['user_id']}`\n\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await update.message.reply_text(text, reply_markup=keyboard)

# ===================== باقي دوال قاعدة البيانات =====================

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
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('channel_stats_id')
    
    if not ch_db_id:
        await safe_send_markdown(context.bot, uid, "❌ لم يتم تحديد القناة")
        return
    
    stats = await db_get_channel_stats(ch_db_id)
    ch_info = await db_get_channel_info(ch_db_id)
    channel_name = ch_info[1] if ch_info else "القناة"
    
    if stats['total_posts'] == 0:
        text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد منشورات بعد"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{ch_db_id}")],
            [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{ch_db_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)
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
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def channel_growth_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('channel_stats_id')
    
    if not ch_db_id:
        await safe_send_markdown(context.bot, uid, "❌ لم يتم تحديد القناة")
        return
    
    growth = await db_get_channel_growth(ch_db_id, 30)
    ch_info = await db_get_channel_info(ch_db_id)
    channel_name = ch_info[1] if ch_info else "القناة"
    
    if not growth['dates']:
        text = f"📈 **نمو {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد بيانات كافية"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 العودة للإحصائيات", callback_data=f"{CallbackData.CHANNEL_STATS}:{ch_db_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)
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
        if query and query.message:
            await query.message.reply_photo(photo=photo_file, caption=f"📈 **نمو {channel_name}**\n📊 إجمالي المنشورات: {growth['total_posts']}\n👁️ إجمالي المشاهدات: {growth['total_views']}")
            await query.delete_message()
        else:
            await context.bot.send_photo(chat_id=uid, photo=photo_file, caption=f"📈 **نمو {channel_name}**\n📊 إجمالي المنشورات: {growth['total_posts']}\n👁️ إجمالي المشاهدات: {growth['total_views']}")
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
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 العودة للإحصائيات", callback_data=f"{CallbackData.CHANNEL_STATS}:{ch_db_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def channel_stats_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    await channel_stats_callback(update, context)

async def my_channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    
    summary = await db_get_channel_stats_summary(uid)
    if not summary or summary['total_channels'] == 0:
        text = "📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد قنوات مسجلة"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة قناة", callback_data=CallbackData.CHANNELS_ADD)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        if query:
            await safe_edit_markdown(query, text, reply_markup=keyboard)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)
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
    
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

# ============================================================
# معالج الأخطاء العام
# ============================================================
async def global_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        
        if await is_chat_locked(chat_id):
            try:
                await update.message.delete()
                await safe_send_markdown(context.bot, chat_id, f"🔒 المجموعة مقفلة من قبل المشرف", 5)
            except:
                pass
            return
        
        bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
        if not bot_perms['can_act']:
            return
        
        if not await db_check_slow_mode(chat_id, user_id):
            try:
                await update.message.delete()
                await safe_send_markdown(context.bot, chat_id, f"⏱️ **وضع بطيء مفعل**\n@{user.username or str(user_id)} يرجى الانتظار قبل إرسال رسالة جديدة", 3)
            except:
                pass
            return
        
        settings = await db_get_security_settings(chat_id)
        text = update.message.text or update.message.caption or ""
        
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
        
        if settings.get('links') and contains_link(text):
            try:
                await update.message.delete()
                await safe_send_markdown(context.bot, chat_id, f"🔗 **الروابط غير مسموح بها**\n@{user.username or str(user_id)}")
            except:
                pass
            await self._apply_penalty(context.bot, chat_id, user_id, settings)
            return
        
        if settings.get('mentions') and contains_mention(text):
            try:
                await update.message.delete()
                await safe_send_markdown(context.bot, chat_id, f"@ **المعرفات غير مسموح بها**\n@{user.username or str(user_id)}")
            except:
                pass
            await self._apply_penalty(context.bot, chat_id, user_id, settings)
            return
        
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
    try:
        if await db_is_hidden_owner(chat_id, user_id):
            return True
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ['administrator', 'creator']
    except:
        return False

async def send_addition_report(bot, adder, chat, chat_type_name):
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
        await query.edit_message_text(get_text(uid, 'cancelled'))
    else:
        await context.bot.send_message(chat_id=uid, text=get_text(uid, 'cancelled'))
    await main_menu_callback(update, context)

async def add_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    context.user_data['state'] = 'waiting_for_channel_id'
    msg = get_text(uid, 'send_channel_id')
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
        msg = get_text(uid, 'no_channels_list')
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
            InlineKeyboardButton(get_text(uid, 'channel_stats'), callback_data=f"{CallbackData.CHANNEL_STATS}:{ch_db_id}"),
            InlineKeyboardButton(get_text(uid, 'delete_channel'), callback_data=f"{CallbackData.CHANNELS_DELETE_PREFIX}{ch_db_id}")
        ])
    kb.append([InlineKeyboardButton(get_text(uid, 'add_channel'), callback_data=CallbackData.CHANNELS_ADD)])
    kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)])
    if query:
        await query.edit_message_text(get_text(uid, 'channels_list'), reply_markup=InlineKeyboardMarkup(kb))
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, 'channels_list'), reply_markup=InlineKeyboardMarkup(kb))

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
            await query.edit_message_text(get_text(uid, 'channel_deleted'))
        else:
            await update.message.reply_text(get_text(uid, 'channel_deleted'))
        await my_channels_callback(update, context)
    else:
        if query:
            await query.answer(get_text(uid, 'delete_failed'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'delete_failed'))

async def select_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    await db_set_active_channel(uid, ch_db_id)
    context.user_data['active_channel'] = ch_db_id
    await invalidate_user_cache(uid)
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
    context.user_data[f"session_{uid}"] = []
    context.user_data[f"session_target_{uid}"] = 15
    context.user_data['state'] = f'adding_posts_{uid}'
    cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.CANCEL_SESSION)]])
    msg = "📥 أرسل المنشورات (نصوص أو صور أو فيديوهات أو مستندات)"
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
            await query.edit_message_text(get_text(uid, 'no_posts'))
        else:
            await update.message.reply_text(get_text(uid, 'no_posts'))
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
        if query:
            await query.edit_message_text(get_text(uid, 'post_published'))
        else:
            await update.message.reply_text(get_text(uid, 'post_published'))
    except Exception as e:
        if query:
            await query.edit_message_text(get_text(uid, 'publish_error').format(str(e)[:100]))
        else:
            await update.message.reply_text(get_text(uid, 'publish_error').format(str(e)[:100]))
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
            await query.edit_message_text(get_text(uid, 'no_posts'))
        else:
            await update.message.reply_text(get_text(uid, 'no_posts'))
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
    if query:
        await safe_edit_markdown(query, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))
    else:
        await safe_send_markdown(context.bot, uid, msg, reply_markup=InlineKeyboardMarkup(kb_buttons))

async def delete_single_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    parts = query.data.split(":")[-1].split("_") if query else context.user_data.get('delete_post_data', '').split("_")
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
        await query.edit_message_text(get_text(uid, 'confirm_delete'), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, 'confirm_delete'), reply_markup=kb)

async def clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    active = int(query.data.split(":")[-1]) if query else context.user_data.get('clear_all_posts_id')
    if not active:
        return
    async def _clear_posts(conn):
        await conn.execute("DELETE FROM posts WHERE channel_db_id=?", (active,))
        await conn.commit()
    await execute_db(_clear_posts)
    if query:
        await query.answer(get_text(uid, 'deleted_all'), show_alert=True)
    else:
        await update.message.reply_text(get_text(uid, 'deleted_all'))
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
            await query.edit_message_text(get_text(uid, 'recycled'))
        else:
            await update.message.reply_text(get_text(uid, 'recycled'))
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
    text = get_text(uid, 'pending_stats').format(unpublished, total)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
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
    auto = get_text(uid, 'auto_on') if await db_auto_status(uid) else get_text(uid, 'auto_off')
    text = get_text(uid, 'stats').format(channels, total, unpublished, groups, auto)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
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
            [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
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

# ============================================================
# دوال مساعدة للتخزين المؤقت
# ============================================================
async def invalidate_user_cache(user_id: int):
    try:
        if user_id in _admin_cache:
            del _admin_cache[user_id]
    except:
        pass

# ============================================================
# دوال الكولباك المتبقية (يتم استكمالها في الأجزاء التالية)
# ============================================================

async def delete_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('delete_group_id')
    if not chat_id:
        return
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer("❌ غير مصرح", show_alert=True)
        else:
            await update.message.reply_text("❌ غير مصرح")
        return
    async def _delete_group(conn):
        await conn.execute("DELETE FROM bot_groups WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM user_groups_link WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM group_security WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM chat_locks WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM moderation_log WHERE chat_id = ?", (chat_id,))
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
            await update.message.reply_text("❌ لم يتم تحديد المجموعة")
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
    if query:
        await safe_edit_markdown(query, text, reply_markup=security_keyboard(chat_id))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=security_keyboard(chat_id))

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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['links'] = not settings['links']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['mentions'] = not settings['mentions']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['warn'] = not settings['warn']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['slow_mode'] = not settings['slow_mode']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    msg = "🚫 إدارة الكلمات المحظورة للمجموعة"
    if query:
        await query.edit_message_text(msg, reply_markup=get_group_banned_words_keyboard(chat_id))
    else:
        await update.message.reply_text(msg, reply_markup=get_group_banned_words_keyboard(chat_id))

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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['welcome_enabled'] = not settings['welcome_enabled']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    settings = await db_get_security_settings(chat_id)
    settings['goodbye_enabled'] = not settings['goodbye_enabled']
    await db_set_security_settings(chat_id, **settings)
    if query:
        await query.edit_message_text(get_text(uid, 'updated'))
    else:
        await update.message.reply_text(get_text(uid, 'updated'))
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
    context.user_data['state'] = 'waiting_for_group_security'
    msg = get_text(uid, 'security_main')
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def banned_words_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = f'waiting_for_group_banned_word_{chat_id}'
    msg = "➕ أرسل الكلمة التي تريد حظرها في هذه المجموعة"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def banned_words_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    words = await db_get_banned_words(chat_id)
    if not words:
        msg = "📭 لا توجد كلمات محظورة في هذه المجموعة"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]])
        if query:
            await query.edit_message_text(msg, reply_markup=kb)
        else:
            await update.message.reply_text(msg, reply_markup=kb)
        return
    msg = "🚫 **الكلمات المحظورة في هذه المجموعة:**\n\n"
    for w, by, at in words:
        msg += f"• `{w}` (أضيف بواسطة {by})\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]])
    if query:
        await safe_send_long_message(context.bot, query.message.chat_id, msg, reply_markup=kb)
        await query.message.delete()
    else:
        await safe_send_long_message(context.bot, uid, msg, reply_markup=kb)

async def banned_words_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    chat_id = int(query.data.split(":")[-1]) if query else context.user_data.get('security_chat_id')
    if not chat_id:
        return
    if not await is_authorized_in_group(context.bot, chat_id, uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = f'waiting_for_remove_group_banned_word_{chat_id}'
    msg = "🗑️ أرسل الكلمة التي تريد حذفها من قائمة المحظورات"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if query:
        await safe_edit_markdown(query, get_text(uid, 'help'))
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, 'help'))

async def support_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP),
         InlineKeyboardButton("📋 تذكرتي", callback_data=CallbackData.SUPPORT_TICKET)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    if query:
        await query.edit_message_text(get_text(uid, 'support_welcome'), reply_markup=keyboard)
    else:
        await update.message.reply_text(get_text(uid, 'support_welcome'), reply_markup=keyboard)
    context.user_data['support_mode'] = True

async def support_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.SUPPORT_MENU)]])
    if query:
        await safe_edit_markdown(query, get_text(uid, 'support_help'), reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, 'support_help'), reply_markup=keyboard)

async def support_ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
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
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def support_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await support_menu_callback(update, context)

async def trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if await db_has_used_trial(uid):
        if query:
            await query.edit_message_text(get_text(uid, 'trial_used'))
        else:
            await update.message.reply_text(get_text(uid, 'trial_used'))
        return
    if await db_has_active_subscription(uid):
        if query:
            await query.edit_message_text(get_text(uid, 'already_subscribed'))
        else:
            await update.message.reply_text(get_text(uid, 'already_subscribed'))
        return
    await db_activate_trial(uid)
    if query:
        await query.edit_message_text(get_text(uid, 'trial'))
    else:
        await update.message.reply_text(get_text(uid, 'trial'))
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
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    text = get_text(uid, 'subscribe')
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)

async def buy_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int, price: int, title: str):
    query = update.callback_query
    user_id = update.effective_user.id
    try:
        await context.bot.send_invoice(chat_id=user_id, title=title, description=f"اشتراك {days} يوم", payload=f"sub_{days}_{price}", currency="XTR", prices=[LabeledPrice(label=f"اشتراك {days} يوم", amount=price)], need_name=False, need_phone_number=False, need_email=False, need_shipping_address=False, is_flexible=False)
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

async def developer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    metrics_stats = metrics.get_stats()
    twofa_status = "✅ مفعلة" if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE else "❌ معطلة"
    text = f"""👑 **معلومات المطور**
━━━━━━━━━━━━━━━━━━━━━━
🤖 **البوت:** {BOT_NAME}
📦 **الإصدار:** 18.0.4
👨‍💻 **المطور:** @RelaxMgr

🔐 **الميزات الأمنية المتقدمة:**
• إعادة تدوير المنشورات تلقائياً (عند الانتهاء تعيد من البداية)
• إصلاح جميع أخطاء الصياغة (Syntax Errors)
• إصلاح مشكلة المسافات البادئة (Indentation)
• إحصائيات متقدمة للقنوات (المشاهدات، النمو، أفضل وقت للنشر)
• رسم بياني لنمو القناة
• إصلاح خطأ تنسيق MarkdownV2
• تحسينات كبيرة في الأداء مع ذاكرة تخزين مؤقت (LRU Cache)
• إصلاح مشكلة وقت النشر العام - يعمل الآن بشكل صحيح
• نظام متكامل لاكتشاف المالك المخفي بأربع طرق مختلفة
• دعم كامل للمالك المخفي في جميع الأوامر
• معالج فحص الرسائل في المجموعات
• حذف الروابط والمعرفات والكلمات المحظورة تلقائياً
• دعم العقوبات التلقائية (كتم/طرد/حظر)
• نظام ترجمة ذكي مع تخزين مؤقت وتجميع الطلبات
• دعم جميع أنواع الميديا
• واجهة ويب مع WebSocket
• نظام Rate Limiting متقدم
• مصادقة ثنائية (2FA) مع مهلة زمنية
• تحسينات أمنية متعددة

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
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    
    uid = update.effective_user.id
    
    # جلب القناة (ستكون بدون @)
    updates_channel = await db_get_updates_channel()
    
    if updates_channel:
        # ✅ رابط صحيح بدون @
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
    reward_days = int(settings.get('reward_days_per_referral', '3'))
    welcome_points = int(settings.get('welcome_bonus_points', '10'))
    text = get_text(uid, 'referral_title').format(referral_code, BOT_USERNAME, referral_code, stats['total_referrals'], stats['available_days'], reward_days, welcome_points)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(uid, 'copy_link'), callback_data=f"{CallbackData.REFERRAL_COPY_LINK_PREFIX}{referral_code}"),
         InlineKeyboardButton(get_text(uid, 'claim_reward'), callback_data=CallbackData.REFERRAL_CLAIM_REWARD)],
        [InlineKeyboardButton(get_text(uid, 'referral_list'), callback_data=CallbackData.REFERRAL_LIST),
         InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]])
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
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]])
        if query:
            await safe_edit_markdown(query, get_text(uid, 'no_reward_available'), reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, get_text(uid, 'no_reward_available'), reply_markup=kb)
        return
    claimed = await db_claim_referral_reward(uid)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]])
    if query:
        await safe_edit_markdown(query, get_text(uid, 'reward_claimed').format(claimed), reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, 'reward_claimed').format(claimed), reply_markup=kb)

async def referral_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    async def _get_referrals(conn):
        cur = await conn.execute("SELECT r.referred_id, r.referred_at, r.is_rewarded, u.first_name, u.username FROM referrals r LEFT JOIN users_cache u ON r.referred_id = u.user_id WHERE r.referrer_id = ? ORDER BY r.referred_at DESC LIMIT 20", (uid,))
        return await cur.fetchall()
    referrals = await execute_db(_get_referrals)
    if not referrals:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REFERRAL_MENU)]])
        if query:
            await safe_edit_markdown(query, get_text(uid, 'no_referrals'), reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, get_text(uid, 'no_referrals'), reply_markup=kb)
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
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def reminder_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
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
    context.user_data['state'] = 'waiting_for_reminder_days'
    msg = "⏰ **عدد أيام التذكير**\n\nأرسل عدد الأيام التي تريد أن يتم تذكيرك بها قبل انتهاء الاشتراك (1-10 أيام):"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REMINDER_MENU)]])
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
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.REMINDER_MENU)]
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

async def translation_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
    if query:
        await query.edit_message_text(get_text(uid, 'translation_disabled'), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, 'translation_disabled'), reply_markup=kb)

async def translation_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    lang = query.data.split(":")[-1] if query else context.user_data.get('translation_lang')
    if not lang:
        return
    await set_user_translation_language(uid, lang)
    lang_names = {'ar': 'العربية', 'en': 'English', 'fr': 'Français', 'tr': 'Türkçe', 'zh': '中文', 'ru': 'Русский'}
    lang_name = lang_names.get(lang, lang)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
    if query:
        await query.edit_message_text(get_text(uid, 'translation_enabled').format(lang_name), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, 'translation_enabled').format(lang_name), reply_markup=kb)

async def handle_text_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    data = query.data if query else context.user_data.get('text_callback_data')
    if not data:
        return
    if data == "rank":
        data_rank = await get_rank(uid)
        points = data_rank['points']
        level = data_rank['level']
        next_points = LEVEL_REQUIREMENTS.get(level + 1, points)
        points_needed = next_points - points if next_points > points else 0
        text = f"📊 **رتبتك الحالية**\n━━━━━━━━━━━━━━\n👤 {query.from_user.first_name if query else '👤'}\n⭐ **المستوى:** {level}\n📈 **النقاط:** {points}\n📌 **المتبقي للمستوى التالي:** {points_needed}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
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
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=kb)
    elif data == "schedule_post":
        context.user_data['state'] = 'waiting_for_schedule_post'
        msg = "📝 **جدولة منشور جديد**\n\nأرسل المنشور بالصيغة التالية:\n`YYYY-MM-DD HH:MM نص المنشور`\n\nمثال: `2024-12-31 20:00 مرحباً بالجميع!`\n\n🕐 الوقت بتوقيت مكة المكرمة"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
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
            [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
        ])
        if query:
            await query.edit_message_text(get_text(uid, 'welcome'), reply_markup=keyboard)
        else:
            await update.message.reply_text(get_text(uid, 'welcome'), reply_markup=keyboard)

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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = f'waiting_for_ban_user_{chat_id}'
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
                await query.answer(get_text(uid, 'admin_only'), show_alert=True)
            else:
                await update.message.reply_text(get_text(uid, 'admin_only'))
            return
        context.user_data['mute_minutes'] = minutes
        context.user_data['state'] = f'waiting_for_mute_user_{chat_id}'
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = f'waiting_for_warn_user_{chat_id}'
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = f'waiting_for_kick_user_{chat_id}'
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = f'waiting_for_restrict_user_{chat_id}'
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = f'waiting_for_pin_message_{chat_id}'
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = f'waiting_for_unban_user_{chat_id}'
    msg = "🔓 **إلغاء حظر مستخدم**\n\nأرسل معرف المستخدم (user_id) لإلغاء حظره:\n`/unban 123456789`"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
                await query.answer(get_text(uid, 'admin_only'), show_alert=True)
            else:
                await update.message.reply_text(get_text(uid, 'admin_only'))
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

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    if query:
        await safe_edit_markdown(query, get_text(uid, 'admin_panel'), reply_markup=get_admin_keyboard(uid))
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, 'admin_panel'), reply_markup=get_admin_keyboard(uid))

async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    users = await db_get_all_users()
    if not users:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا يوجد مستخدمون مسجلون.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا يوجد مستخدمون مسجلون.", reply_markup=kb)
        return
    text = "👥 **قائمة المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, banned in users[:50]:
        status = "🚫 محظور" if banned else "✅ نشط"
        text += f"• `{user_id}` - {status}\n"
    if len(users) > 50:
        text += f"\nو {len(users)-50} آخرون..."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_banned_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    users = await db_get_all_users()
    banned_users = [u for u in users if u[1] == 1]
    if not banned_users:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا يوجد مستخدمون محظورون.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا يوجد مستخدمون محظورون.", reply_markup=kb)
        return
    text = "🚫 **المستخدمون المحظورون**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, _ in banned_users[:50]:
        text += f"• `{user_id}`\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_USERS)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def admin_unban_all_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    async def _unban_all(conn):
        await conn.execute("UPDATE users SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_all)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text("✅ تم إلغاء حظر جميع المستخدمين.", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم إلغاء حظر جميع المستخدمين.", reply_markup=kb)

async def admin_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    channels = await db_get_all_user_channels_no_limit()
    if not channels:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد قنوات مسجلة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد قنوات مسجلة.", reply_markup=kb)
        return
    text = "📡 **قنوات المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for idx, (user_id, ch_id, ch_tele, ch_name, banned) in enumerate(channels[:100], 1):
        status = "⛔" if banned else "✅"
        text += f"{idx}. {status} `{ch_name}`\n   👤 المستخدم: `{user_id}`\n   🆔 القناة: `{ch_tele}`\n\n"
    if len(channels) > 100:
        text += f"\nو {len(channels)-100} قناة أخرى..."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_banned_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    channels = await db_all_users_channels(only_banned=True, limit=500)
    if not channels:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد قنوات محظورة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد قنوات محظورة.", reply_markup=kb)
        return
    text = "⛔ **قنوات المستخدمين المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, ch_id, ch_tele, ch_name, banned in channels[:50]:
        text += f"• المستخدم: `{user_id}` | القناة: {ch_name} (`{ch_tele}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ تنشيط الكل", callback_data=CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def admin_activate_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    async def _activate_all(conn):
        await conn.execute("UPDATE user_channels SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_activate_all)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text("✅ تم إلغاء حظر جميع قنوات المستخدمين.", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم إلغاء حظر جميع قنوات المستخدمين.", reply_markup=kb)

async def admin_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    groups = await db_get_all_groups(only_banned=False)
    if not groups:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد مجموعات مسجلة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد مجموعات مسجلة.", reply_markup=kb)
        return
    text = "👥 **المجموعات المسجلة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for chat_id, chat_name, username, added_by, added_at, banned in groups[:50]:
        text += f"• {chat_name} (ID: `{chat_id}`)\n  أضيف بواسطة: `{added_by}`\n"
    if len(groups) > 50:
        text += f"\nو {len(groups)-50} أخرى..."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_banned_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    groups = await db_get_all_groups(only_banned=True)
    if not groups:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد مجموعات محظورة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد مجموعات محظورة.", reply_markup=kb)
        return
    text = "🚷 **المجموعات المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for chat_id, chat_name, username, added_by, added_at, banned in groups[:50]:
        text += f"• {chat_name} (ID: `{chat_id}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_GROUPS)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def admin_unban_all_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    async def _unban_groups(conn):
        await conn.execute("UPDATE bot_groups SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_groups)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text("✅ تم إلغاء حظر جميع المجموعات.", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم إلغاء حظر جميع المجموعات.", reply_markup=kb)

async def admin_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    channels = await db_get_all_bot_channels(only_banned=False)
    if not channels:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد قنوات أضيف إليها البوت.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد قنوات أضيف إليها البوت.", reply_markup=kb)
        return
    text = "📢 **قنوات البوت**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for channel_id, channel_name, added_by, added_at, banned in channels[:50]:
        text += f"• {channel_name} (ID: `{channel_id}`)\n  أضيف بواسطة: `{added_by}`\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_banned_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    channels = await db_get_all_bot_channels(only_banned=True)
    if not channels:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("📭 لا توجد قنوات بوت محظورة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد قنوات بوت محظورة.", reply_markup=kb)
        return
    text = "🚫 **قنوات البوت المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for channel_id, channel_name, added_by, added_at, banned in channels[:50]:
        text += f"• {channel_name} (ID: `{channel_id}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_BOT_CHANNELS)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await safe_edit_markdown(query, text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=keyboard)

async def admin_unban_all_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    async def _unban_bot_channels(conn):
        await conn.execute("UPDATE bot_channels SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_bot_channels)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text("✅ تم إلغاء حظر جميع قنوات البوت.", reply_markup=kb)
    else:
        await update.message.reply_text("✅ تم إلغاء حظر جميع قنوات البوت.", reply_markup=kb)

async def admin_monitor_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_add_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = 'waiting_for_admin_id_add'
    if query:
        await safe_edit_markdown(query, get_text(uid, 'enter_admin_id'))
    else:
        await update.message.reply_text(get_text(uid, 'enter_admin_id'))

async def admin_remove_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    admins = await get_all_bot_admins()
    if not admins:
        if query:
            await query.edit_message_text(get_text(uid, 'no_admins'))
        else:
            await update.message.reply_text(get_text(uid, 'no_admins'))
        return
    text = "👑 المشرفون الحاليون:\n"
    for a in admins:
        text += f"- {a}\n"
    text += "\n" + get_text(uid, 'enter_remove_admin_id')
    context.user_data['state'] = 'waiting_for_admin_id_remove'
    if query:
        await safe_edit_markdown(query, text)
    else:
        await update.message.reply_text(text)

async def admin_ram_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    ram = metrics.get_ram_usage()
    text = f"🖥️ **حالة الرام**\n━━━━━━━━━━━━━━━━━━━━━━\n• الإجمالي: {ram['total']} GB\n• المستخدم: {ram['used']} GB\n• النسبة: {ram['percent']}%"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    total, banned, posts, groups, channels = await db_stats()
    text = f"📊 **إحصائيات عامة**\n━━━━━━━━━━━━━━━━━━━━━━\n• المستخدمين: {total}\n• المحظورين: {banned}\n• المنشورات غير المنشورة: {posts}\n• المجموعات: {groups}\n• قنوات المستخدمين: {channels}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_metrics_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    try:
        await create_backup()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("✅ تم إنشاء نسخة احتياطية مشفرة جديدة.", reply_markup=kb)
        else:
            await update.message.reply_text("✅ تم إنشاء نسخة احتياطية مشفرة جديدة.", reply_markup=kb)
    except Exception as e:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text(f"❌ فشل إنشاء النسخة: {e}", reply_markup=kb)
        else:
            await update.message.reply_text(f"❌ فشل إنشاء النسخة: {e}", reply_markup=kb)

async def admin_restore_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    
    backups = await list_backups()
    if not backups:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text(get_text(uid, 'no_backups'), reply_markup=kb)
        else:
            await update.message.reply_text(get_text(uid, 'no_backups'), reply_markup=kb)
        return
    kb = []
    for b in backups[:10]:
        kb.append([InlineKeyboardButton(b.name, callback_data=f"{CallbackData.ADMIN_RESTORE_BACKUP_SELECT_PREFIX}{b.name}")])
    kb.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)])
    if query:
        await query.edit_message_text(get_text(uid, 'select_backup'), reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(get_text(uid, 'select_backup'), reply_markup=InlineKeyboardMarkup(kb))

async def admin_restore_backup_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    backup_name = query.data.split(":")[-1] if query else context.user_data.get('restore_backup_name')
    if not backup_name:
        return
    backup_path = BACKUP_DIR / backup_name
    try:
        await restore_backup(backup_path)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text("✅ تم استعادة النسخة الاحتياطية المشفرة.", reply_markup=kb)
        else:
            await update.message.reply_text("✅ تم استعادة النسخة الاحتياطية المشفرة.", reply_markup=kb)
    except Exception as e:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text(f"❌ فشل الاستعادة: {e}", reply_markup=kb)
        else:
            await update.message.reply_text(f"❌ فشل الاستعادة: {e}", reply_markup=kb)

async def admin_backup_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
    text = f"⚙️ **إعدادات النسخ الاحتياطي**\n━━━━━━━━━━━━━━━━━━━━━━\n• النسخ التلقائي: {status}\n• تشفير النسخ: ✅ مفعل\n• الحد الأقصى للنسخ: {MAX_BACKUPS}\n\nيمكنك تبديل الحالة بالزر أدناه."
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_toggle_auto_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_BACKUP_SETTINGS)]])
    if query:
        await query.edit_message_text(f"✅ تم تغيير إعداد النسخ التلقائي إلى: {status}", reply_markup=kb)
    else:
        await update.message.reply_text(f"✅ تم تغيير إعداد النسخ التلقائي إلى: {status}", reply_markup=kb)

async def admin_change_interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    current = await db_get_publish_interval()
    current_min = current // 60
    context.user_data['state'] = 'admin_waiting_for_interval'
    msg = (f"⏱️ **وقت النشر العام الحالي:** {current_min} دقيقة\n\n"
           f"📌 **ملاحظة:** هذا الإعداد يؤثر على الفاصل الزمني بين دورات النشر.\n"
           f"أرسل العدد الجديد من الدقائق (الحد الأدنى 1 دقيقة، الحد الأقصى 1440 دقيقة = 24 ساعة):")
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_send_update_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = 'waiting_for_update_text'
    msg = "📢 أرسل نص التحديث الذي تريد نشره في قناة التحديثات:"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_set_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = 'waiting_for_update_channel'
    msg = """⚙️ **تعيين قناة التحديثات**

📢 أرسل معرف قناة التحديثات:

• `@username` (مثل: @my_channel)
• أو المعرف الرقمي (مثل: -1001234567890)

⚠️ **تنبيهات مهمة:**
• تأكد من أن البوت مشرف في القناة
• تأكد من أن البوت لديه صلاحية الإرسال
• القناة يجب أن تكون عامة (Public)"""
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_show_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    
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
    
    await safe_edit_markdown(query, text, reply_markup=keyboard)

async def admin_updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    channel = await db_get_updates_channel()
    text = f"📢 **قناة التحديثات الحالية:** @{channel}\n\nيمكنك تغييرها باستخدام زر '⚙️ قناة التحديثات'"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_force_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    enabled = await db_get_force_subscribe_status()
    new_status = not enabled
    await db_set_force_subscribe_status(new_status)
    status_text = "مفعل" if new_status else "معطل"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(f"✅ تم {status_text} الاشتراك الإجباري.", reply_markup=kb)
    else:
        await update.message.reply_text(f"✅ تم {status_text} الاشتراك الإجباري.", reply_markup=kb)

async def admin_set_force_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = 'admin_waiting_for_force_channel'
    msg = "⚙️ أرسل معرف قناة الاشتراك الإجباري (مثال: @channel_username):"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = 'waiting_for_broadcast'
    msg = "📨 أرسل النص الذي تريد إرساله إلى جميع المستخدمين:"
    if query:
        await safe_edit_markdown(query, msg)
    else:
        await update.message.reply_text(msg)

async def admin_confirm_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    broadcast_text = context.user_data.get('broadcast_text', '')
    if not broadcast_text:
        if query:
            await query.edit_message_text("❌ لا يوجد نص للإرسال")
        else:
            await update.message.reply_text("❌ لا يوجد نص للإرسال")
        return
    dangerous_patterns = [r'<script', r'javascript:', r'data:', r'vbscript:', r'<\?php', r'<%', r'{%']
    for pattern in dangerous_patterns:
        if re.search(pattern, broadcast_text, re.IGNORECASE):
            if query:
                await query.edit_message_text("❌ النص يحتوي على كود ضار! تم منع الإرسال.")
            else:
                await update.message.reply_text("❌ النص يحتوي على كود ضار! تم منع الإرسال.")
            return
    if len(broadcast_text) > 4000:
        if query:
            await query.edit_message_text("❌ النص طويل جداً (الحد الأقصى 4000 حرف)")
        else:
            await update.message.reply_text("❌ النص طويل جداً (الحد الأقصى 4000 حرف)")
        return
    if query:
        await query.edit_message_text("📨 جاري الإرسال... يرجى الانتظار")
    else:
        await update.message.reply_text("📨 جاري الإرسال... يرجى الانتظار")
    async def _get_active_users(conn):
        cur = await conn.execute("SELECT user_id FROM users WHERE banned = 0")
        return [row[0] for row in await cur.fetchall()]
    users = await execute_db(_get_active_users)
    sent = 0
    failed = 0
    if not users:
        if query:
            await query.edit_message_text("📭 لا يوجد مستخدمين نشطين لإرسال الرسالة لهم.")
        else:
            await update.message.reply_text("📭 لا يوجد مستخدمين نشطين لإرسال الرسالة لهم.")
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
    msg = f"✅ **تم إرسال الرسالة**\n\n📨 تم الإرسال إلى: {sent} مستخدم\n❌ فشل الإرسال إلى: {failed} مستخدم"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def admin_support_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    tickets = await db_get_all_tickets(limit=20)
    if not tickets:
        if query:
            await query.edit_message_text("📭 لا توجد تذاكر دعم مسجلة")
        else:
            await update.message.reply_text("📭 لا توجد تذاكر دعم مسجلة")
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
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await safe_edit_markdown(query, text, reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=kb)

async def admin_delete_all_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    confirm_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، احذف الكل", callback_data=CallbackData.ADMIN_CONFIRM_DELETE_TICKETS),
         InlineKeyboardButton("❌ لا، إلغاء", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    if query:
        await query.edit_message_text(get_text(uid, 'confirm_delete_tickets'), reply_markup=confirm_kb)
    else:
        await update.message.reply_text(get_text(uid, 'confirm_delete_tickets'), reply_markup=confirm_kb)

async def admin_confirm_delete_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    count = await db_delete_all_tickets()
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(get_text(uid, 'tickets_deleted').format(count), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, 'tickets_deleted').format(count), reply_markup=kb)

async def admin_manage_sendcode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
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
    if query:
        await safe_edit_markdown(query, current_text, reply_markup=keyboard)
    else:
        await safe_send_markdown(context.bot, uid, current_text, reply_markup=keyboard)

async def admin_set_sendcode_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = 'waiting_for_sendcode_user'
    msg = "➕ أرسل معرف المستخدم (user_id) الذي تريد منحه صلاحية استخدام أمر /sendcode:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def admin_show_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    log_ch = await db_get_log_channel_id()
    if log_ch:
        text = f"📋 **قناة التقارير الحالية:**\n`{log_ch}`\n\nيمكنك تغييرها باستخدام الأمر `/set_log_channel`\nأو الضغط على زر 'تعيين قناة التقارير'."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await safe_edit_markdown(query, text, reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, text, reply_markup=kb)
    else:
        text = "📋 **لم يتم تعيين قناة تقارير بعد.**\nاستخدم الأمر `/set_log_channel` أو زر 'تعيين قناة التقارير' لتعيينها."
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        if query:
            await query.edit_message_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)

async def admin_set_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = 'waiting_for_log_channel'
    msg = "📢 **تعيين قناة التقارير**\n\nأرسل معرف القناة (ID) أو معرف المستخدم (@username) للقناة التي تريد استقبال التقارير فيها.\n\nمثال: `-1001234567890` أو `@channel_username`\n\n⚠️ تأكد من أن البوت مشرف في القناة ولديه صلاحية إرسال الرسائل."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    if query:
        await query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)

async def admin_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    msg = "💬 **إدارة ردود المجموعة**"
    if query:
        await query.edit_message_text(msg, reply_markup=get_replies_keyboard())
    else:
        await update.message.reply_text(msg, reply_markup=get_replies_keyboard())

async def admin_add_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = 'admin_waiting_for_keyword'
    msg = "📝 **إضافة رد تلقائي**\n\nأرسل الكلمة المفتاحية (مثل: مرحبا، السلام عليكم، كيف حالك):"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def admin_list_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    replies = await db_get_all_replies()
    if not replies:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_REPLIES)]])
        if query:
            await query.edit_message_text("📭 لا توجد ردود مسجلة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد ردود مسجلة.", reply_markup=kb)
        return
    text = "💬 **قائمة الردود التلقائية**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for kw, rep in replies[:30]:
        short_rep = rep[:40] + "..." if len(rep) > 40 else rep
        text += f"• **{kw}** → {short_rep}\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ حذف {kw}", callback_data=f"admin_del_reply_{kw}")])
    keyboard.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_REPLIES)])
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_del_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    if query and query.data.startswith("admin_del_reply_"):
        keyword = query.data.replace("admin_del_reply_", "")
        if await db_del_reply(keyword):
            await query.answer(f"✅ تم حذف رد {keyword}", show_alert=True)
        else:
            await query.answer(f"❌ الكلمة {keyword} غير موجودة", show_alert=True)
        await admin_list_replies_callback(update, context)
        return
    else:
        context.user_data['state'] = 'admin_del_reply'
        msg = "🗑️ **حذف رد تلقائي**\n\nأرسل الكلمة المفتاحية لحذف ردها:"
        if query:
            await query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)

async def admin_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    msg = "🚫 **إدارة الكلمات المحظورة على مستوى البوت (لجميع المجموعات)**"
    if query:
        await query.edit_message_text(msg, reply_markup=get_banned_words_admin_keyboard())
    else:
        await update.message.reply_text(msg, reply_markup=get_banned_words_admin_keyboard())

async def admin_add_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = 'waiting_for_global_banned_word'
    msg = "➕ أرسل الكلمة التي تريد حظرها على مستوى البوت:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def admin_list_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    words = await db_get_banned_words(-1)
    if not words:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_BANNED_WORDS)]])
        if query:
            await query.edit_message_text("📭 لا توجد كلمات محظورة عامة.", reply_markup=kb)
        else:
            await update.message.reply_text("📭 لا توجد كلمات محظورة عامة.", reply_markup=kb)
        return
    text = "🚫 **الكلمات المحظورة عامة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for w, by, at in words[:20]:
        text += f"• `{w}` (أضيف بواسطة {by})\n"
        keyboard.append([InlineKeyboardButton(f"🗑️ حذف {w}", callback_data=f"admin_del_banned_word_{w}")])
    keyboard.append([InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.ADMIN_BANNED_WORDS)])
    if query:
        await safe_edit_markdown(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await safe_send_markdown(context.bot, uid, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_remove_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    context.user_data['state'] = 'waiting_for_remove_global_banned_word'
    msg = "🗑️ أرسل الكلمة التي تريد حذفها من الكلمات المحظورة العامة:"
    if query:
        await query.edit_message_text(msg)
    else:
        await update.message.reply_text(msg)

async def admin_del_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    if uid != MAIN_ADMIN_ID and not await is_bot_admin(uid):
        if query:
            await query.answer(get_text(uid, 'admin_only'), show_alert=True)
        else:
            await update.message.reply_text(get_text(uid, 'admin_only'))
        return
    word = query.data.replace("admin_del_banned_word_", "") if query else context.user_data.get('del_banned_word')
    if not word:
        return
    async def _remove_global_word(conn):
        await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
        await conn.commit()
    await execute_db(_remove_global_word)
    if query:
        await query.answer(f"✅ تم حذف {word}", show_alert=True)
    else:
        await update.message.reply_text(f"✅ تم حذف {word}")
    await admin_list_banned_words_callback(update, context)

async def lang_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    lang = query.data.split("_")[1] if query else context.user_data.get('lang_set')
    if not lang:
        return
    await set_user_language(uid, lang)
    if query:
        await query.answer(get_text(uid, 'lang_set'))
    else:
        await update.message.reply_text(get_text(uid, 'lang_set'))
    kb, _, _ = await get_main_keyboard(uid)
    if query:
        await safe_edit_markdown(query, "🌿 القائمة الرئيسية", reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, "🌿 القائمة الرئيسية", reply_markup=kb)

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    auto = await db_auto_status(uid)
    btn = get_text(uid, 'disabled') if auto else get_text(uid, 'enabled')
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{btn} النشر التلقائي", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH)],
        [InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]
    ])
    if query:
        await query.edit_message_text(get_text(uid, 'settings'), reply_markup=kb)
    else:
        await update.message.reply_text(get_text(uid, 'settings'), reply_markup=kb)

async def toggle_auto_publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    cur = await db_auto_status(uid)
    await db_set_auto(uid, not cur)
    status = get_text(uid, 'enabled') if not cur else get_text(uid, 'disabled')
    if query:
        await query.edit_message_text(get_text(uid, 'auto_toggled').format(status))
    else:
        await update.message.reply_text(get_text(uid, 'auto_toggled').format(status))
    await main_menu_callback(update, context)

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
    if query:
        await safe_edit_markdown(query, get_text(uid, 'schedule_settings').format(txt), reply_markup=kb)
    else:
        await safe_send_markdown(context.bot, uid, get_text(uid, 'schedule_settings').format(txt), reply_markup=kb)

async def set_interval_minutes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = f'waiting_interval_minutes_{ch_db_id}'
    if query:
        await query.edit_message_text(get_text(uid, 'send_minutes'))
    else:
        await update.message.reply_text(get_text(uid, 'send_minutes'))

async def set_interval_hours_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = f'waiting_interval_hours_{ch_db_id}'
    if query:
        await query.edit_message_text(get_text(uid, 'send_hours'))
    else:
        await update.message.reply_text(get_text(uid, 'send_hours'))

async def set_interval_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = f'waiting_interval_days_{ch_db_id}'
    if query:
        await query.edit_message_text(get_text(uid, 'send_days'))
    else:
        await update.message.reply_text(get_text(uid, 'send_days'))

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
    context.user_data['state'] = f'selecting_days_{ch_db_id}'
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
    context.user_data['state'] = f'waiting_dates_{ch_db_id}'
    if query:
        await query.edit_message_text(get_text(uid, 'send_dates'))
    else:
        await update.message.reply_text(get_text(uid, 'send_dates'))

async def set_publish_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    uid = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1]) if query else context.user_data.get('schedule_ch_id')
    if not ch_db_id:
        return
    context.user_data['state'] = f'waiting_publish_time_{ch_db_id}'
    if query:
        await query.edit_message_text(get_text(uid, 'send_time'))
    else:
        await update.message.reply_text(get_text(uid, 'send_time'))

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
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(uid, 'back'), callback_data=CallbackData.BACK)]])
        if query:
            await safe_edit_markdown(query, get_text(uid, 'days_saved'), reply_markup=kb)
        else:
            await safe_send_markdown(context.bot, uid, get_text(uid, 'days_saved'), reply_markup=kb)
    else:
        if query:
            await query.edit_message_text(get_text(uid, 'error'))
        else:
            await update.message.reply_text(get_text(uid, 'error'))

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
        [InlineKeyboardButton("⏱️ 5 دقائق", callback_data=f"adv_mute_duration:5:{chat_id}"),
         InlineKeyboardButton("⏱️ 30 دقيقة", callback_data=f"adv_mute_duration:30:{chat_id}")],
        [InlineKeyboardButton("⏱️ 1 ساعة", callback_data=f"adv_mute_duration:60:{chat_id}"),
         InlineKeyboardButton("⏱️ 12 ساعة", callback_data=f"adv_mute_duration:720:{chat_id}")],
        [InlineKeyboardButton("📆 يوم", callback_data=f"adv_mute_duration:1440:{chat_id}"),
         InlineKeyboardButton("📆 أسبوع", callback_data=f"adv_mute_duration:10080:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم دائم", callback_data=f"adv_mute_duration:0:{chat_id}"),
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
        [InlineKeyboardButton("📢 عرض القناة الحالية", callback_data=CallbackData.ADMIN_SHOW_UPDATE_CHANNEL)],
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
