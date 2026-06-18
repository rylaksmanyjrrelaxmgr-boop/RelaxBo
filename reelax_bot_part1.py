#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - بوت متكامل لإدارة القنوات والمجموعات
الإصدار: 18.0.3 - نسخة عالمية (Portable) - مُحدّثة بالأمان والاستقرار والإحصائيات المتقدمة
المطور: @RelaxMgr
"""

import sys
import os
from pathlib import Path
import secrets
import string

def check_python_version():
    required_version = (3, 8)
    current_version = sys.version_info
    if current_version < required_version:
        print(f"❌ يحتاج البوت إلى بايثون {required_version[0]}.{required_version[1]} أو أحدث")
        print(f"📌 الإصدار الحالي: {current_version[0]}.{current_version[1]}")
        sys.exit(1)

check_python_version()

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
    temp_path = get_writable_path(BASE_PATH, "temp")
    return temp_path

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

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, BotCommand, LabeledPrice, ChatPermissions, LinkPreviewOptions
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

from cryptography.fernet import Fernet

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key()
else:
    ENCRYPTION_KEY = ENCRYPTION_KEY.encode()
cipher_suite = Fernet(ENCRYPTION_KEY)

BACKUP_KEY = hashlib.sha256(TOKEN.encode()).digest()
BACKUP_CIPHER = Fernet(base64.urlsafe_b64encode(BACKUP_KEY[:32]))

_background_tasks_started = False

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

async def invalidate_user_cache(user_id: int):
    try:
        if CACHETOOLS_AVAILABLE:
            pass
    except:
        pass

async def invalidate_channel_cache(channel_db_id: int):
    try:
        pass
    except:
        pass

async def log_activity(action: str, details: str):
    if not BATTERY_SAVER_MODE:
        try:
            with open(LOG_PATH.parent / "logs.txt", "a", encoding='utf-8', errors='replace') as f:
                f.write(f"[{mecca_now().strftime('%Y-%m-%d %H:%M:%S')}] {action}: {details}\n")
        except Exception as e:
            logger.warning(f"خطأ في تسجيل النشاط: {e}")

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

def safe_int_convert(val):
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None

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

def parse_time_safe(time_str):
    if not time_str: 
        return None
    try:
        parts = time_str.split(':')
        return (int(parts[0]), int(parts[1]))
    except: 
        return None

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

def track_command(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        start_time = time_module.time()
        try:
            result = await func(update, context, *args, **kwargs)
            metrics.record_response_time(time_module.time() - start_time)
            if update and update.message and update.message.text:
                cmd = update.message.text.split()[0]
                metrics.record_command(cmd)
            return result
        except Exception as e:
            metrics.record_error(type(e).__name__)
            raise
    return wrapper

async def global_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    error_trace = traceback.format_exc()
    
    safe_error_msg = str(error)
    if TOKEN and TOKEN in safe_error_msg:
        safe_error_msg = safe_error_msg.replace(TOKEN, "[TOKEN_HIDDEN]")
    if ENCRYPTION_KEY and isinstance(ENCRYPTION_KEY, bytes):
        try:
            key_str = ENCRYPTION_KEY.decode()
            if key_str in safe_error_msg:
                safe_error_msg = safe_error_msg.replace(key_str, "[ENCRYPTION_KEY_HIDDEN]")
        except:
            pass
    if BACKUP_KEY and BACKUP_KEY.hex() in safe_error_msg:
        safe_error_msg = safe_error_msg.replace(BACKUP_KEY.hex(), "[BACKUP_KEY_HIDDEN]")
    
    logger.error(f"خطأ عام: {safe_error_msg}\n{error_trace}")
    
    user_id = update.effective_user.id if update and update.effective_user else "غير معروف"
    user_name = update.effective_user.full_name if update and update.effective_user else "غير معروف"
    user_username = f"@{update.effective_user.username}" if update and update.effective_user and update.effective_user.username else "لا يوجد"
    chat_id = update.effective_chat.id if update and update.effective_chat else "غير معروف"
    chat_type = update.effective_chat.type if update and update.effective_chat else "غير معروف"
    chat_title = update.effective_chat.title if update and update.effective_chat and hasattr(update.effective_chat, 'title') else "غير معروف"
    message_text = update.effective_message.text if update and update.effective_message and update.effective_message.text else "غير معروف"
    callback_data = update.callback_query.data if update and update.callback_query and update.callback_query.data else "لا يوجد"
    error_time = mecca_now().strftime("%Y-%m-%d %H:%M:%S")
    
    def escape_md(text: str) -> str:
        if not text:
            return ""
        special_chars = r'_*[]()~`>#+\-=|{}.!'
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        text = re.sub(r'(\d+)\.', r'\1\.', text)
        return text
    
    error_report = f"""🚨 **تقرير خطأ جديد**

━━━━━━━━━━━━━━━━━━━━━━
👤 **المستخدم:**
• المعرف: `{escape_md(str(user_id))}`
• الاسم: {escape_md(str(user_name))}
• اليوزر: {escape_md(user_username)}

━━━━━━━━━━━━━━━━━━━━━━
💬 **المحادثة:**
• المعرف: `{escape_md(str(chat_id))}`
• النوع: {escape_md(chat_type)}
• الاسم: {escape_md(str(chat_title))}

━━━━━━━━━━━━━━━━━━━━━━
📝 **الرسالة:**
• النص: {escape_md(str(message_text)[:200])}
• كولباك: {escape_md(str(callback_data)[:100])}

━━━━━━━━━━━━━━━━━━━━━━
⚠️ **الخطأ:**
• النوع: `{escape_md(type(error).__name__)}`
• التفاصيل: `{escape_md(safe_error_msg[:300])}`

━━━━━━━━━━━━━━━━━━━━━━
📅 **التوقيت:** {escape_md(error_time)} (مكة المكرمة)
━━━━━━━━━━━━━━━━━━━━━━"""
    
    log_channel = await db_get_log_channel_id()
    if log_channel:
        try:
            await safe_send_error(context.bot, log_channel, error_report)
            logger.info(f"✅ تم إرسال تقرير الخطأ إلى قناة التقارير: {log_channel}")
        except Exception as e:
            logger.error(f"❌ فشل إرسال تقرير الخطأ إلى قناة التقارير: {e}")
            try:
                await context.bot.send_message(chat_id=MAIN_ADMIN_ID, text=f"⚠️ فشل إرسال تقرير الخطأ إلى قناة التقارير\nالخطأ: {e}")
            except:
                pass
    else:
        try:
            await safe_send_error(context.bot, MAIN_ADMIN_ID, error_report)
        except:
            try:
                await context.bot.send_message(chat_id=MAIN_ADMIN_ID, text=error_report.replace("*", "").replace("`", ""))
            except:
                pass
