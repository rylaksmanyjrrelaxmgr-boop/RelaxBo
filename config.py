import os
import sys
import time
import json
import base64
import secrets
import hashlib
import hmac
import logging
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

BASE_PATH = Path(__file__).parent.resolve()
DATA_PATH = BASE_PATH / "data"
DB_PATH = DATA_PATH / "bot_data.db"
BACKUP_DIR = DATA_PATH / "backups"
LOG_PATH = DATA_PATH / "logs" / "bot.log"
SECURITY_LOG = DATA_PATH / "logs" / "security.log"
ERROR_LOG = DATA_PATH / "logs" / "errors.log"
ACCESS_LOG = DATA_PATH / "logs" / "access.log"
TEMP_PATH = BASE_PATH / "temp"
STATIC_PATH = BASE_PATH / "static"
TEMPLATES_PATH = BASE_PATH / "templates"

for p in [DATA_PATH, BACKUP_DIR, LOG_PATH.parent, TEMP_PATH, STATIC_PATH, TEMPLATES_PATH]:
    p.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_PATH / ".env")

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN not set in environment")

PRIMARY_OWNER_ID = int(os.getenv("MAIN_ADMIN_ID", 0))
if PRIMARY_OWNER_ID == 0:
    raise ValueError("MAIN_ADMIN_ID not set in environment")

BOT_NAME = os.getenv("BOT_NAME", "ريلاكس مانيجر")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Reelaaaxbot")
USE_PROXY = os.getenv("USE_PROXY", "False").lower() in ["true", "1", "yes", "on"]
PROXY_URL = os.getenv("PROXY_URL", "http://127.0.0.1:10809")
ENABLE_2FA = os.getenv("ENABLE_2FA", "False").lower() in ["true", "1", "yes", "on"]
ADMIN_2FA_SECRET = os.getenv("ADMIN_2FA_SECRET", "")
DB_ENCRYPTION = os.getenv("DB_ENCRYPTION", "True").lower() in ["true", "1", "yes", "on"]
MAX_BACKUPS = int(os.getenv("MAX_BACKUPS", 10))
SECURITY_LOG_LEVEL = os.getenv("SECURITY_LOG_LEVEL", "CRITICAL")
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", 20 * 1024 * 1024))
MAX_CHANNELS_PER_CYCLE = int(os.getenv("MAX_CHANNELS_PER_CYCLE", "20"))
PUBLISH_RETRY_DELAY = int(os.getenv("PUBLISH_RETRY_DELAY", 300))
MAX_POSTS_PER_SESSION = int(os.getenv("MAX_POSTS_PER_SESSION", 50))
MAX_UNPUBLISHED_POSTS = int(os.getenv("MAX_UNPUBLISHED_POSTS", 1000))
DB_TIMEOUT = int(os.getenv("DB_TIMEOUT", 30))
MAX_CONNECTIONS = int(os.getenv("MAX_CONNECTIONS", 20))
DEFAULT_PUBLISH_INTERVAL_SECONDS = int(os.getenv("DEFAULT_PUBLISH_INTERVAL_SECONDS", 720))
CLEANUP_SLEEP = int(os.getenv("CLEANUP_SLEEP", 3600))
BATTERY_SAVER_MODE = os.getenv("BATTERY_SAVER_MODE", "False").lower() in ["true", "1", "yes", "on"]

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

WEB_PORT = int(os.getenv("PORT", "10000"))
if WEB_PORT == 0:
    WEB_PORT = 10000
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")
if not WEB_PASSWORD and os.getenv("ENVIRONMENT", "development") == "production":
    WEB_PASSWORD = secrets.token_urlsafe(16)
WEB_USERNAME = os.getenv("WEB_USERNAME", "admin")
WEB_SECRET_KEY = os.getenv("WEB_SECRET_KEY", secrets.token_urlsafe(32))
WEB_SESSION_TIMEOUT = int(os.getenv("WEB_SESSION_TIMEOUT", 3600))
WEB_RATE_LIMIT = int(os.getenv("WEB_RATE_LIMIT", 100))
WEB_RATE_WINDOW = int(os.getenv("WEB_RATE_WINDOW", 60))

GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
CLOUD_BACKUP_ENABLED = os.getenv("CLOUD_BACKUP_ENABLED", "False").lower() in ["true", "1", "yes", "on"]
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = os.getenv("TOKEN_FILE", "token.json")

SIGHTENGINE_API_USER = os.getenv("SIGHTENGINE_API_USER", "")
SIGHTENGINE_API_SECRET = os.getenv("SIGHTENGINE_API_SECRET", "")
NSFW_ENABLED = os.getenv("NSFW_ENABLED", "True").lower() in ["true", "1", "yes", "on"]
NSFW_THRESHOLD = float(os.getenv("NSFW_THRESHOLD", "0.7"))
NSFW_MAX_FILE_SIZE = int(os.getenv("NSFW_MAX_FILE_SIZE", 5 * 1024 * 1024))
NSFW_MAX_VIDEO_SIZE = int(os.getenv("NSFW_MAX_VIDEO_SIZE", 10 * 1024 * 1024))
NSFW_FRAMES = int(os.getenv("NSFW_FRAMES", "5"))
NSFW_CACHE_TTL = int(os.getenv("NSFW_CACHE_TTL", 300))

try:
    from cachetools import TTLCache, LRUCache
    CACHETOOLS_AVAILABLE = True
    _admin_cache = TTLCache(maxsize=1000, ttl=300)
    _security_cache = TTLCache(maxsize=500, ttl=60)
    _user_cache = TTLCache(maxsize=2000, ttl=3600)
    _group_cache = TTLCache(maxsize=500, ttl=300)
except ImportError:
    CACHETOOLS_AVAILABLE = False
    _admin_cache = {}
    _security_cache = {}
    _user_cache = {}
    _group_cache = {}
    _admin_cache_time = {}
    _security_cache_time = {}
    _ADMIN_CACHE_TTL = 60
    _SECURITY_CACHE_TTL = 30

NSFW_CACHE = {}
_translation_cache = {}
_reply_cache = {}
_reply_cache_time = {}
_REPLY_CACHE_TTL = 300
user_points_last_hour = {}
user_translation_settings_cache = {}
user_language = {}

def derive_key_from_password(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key

def get_encryption_key() -> bytes:
    key_file = DATA_PATH / ".db_key"
    salt_file = DATA_PATH / ".db_salt"
    if key_file.exists() and salt_file.exists():
        try:
            with open(key_file, "rb") as f:
                return f.read()
        except:
            pass
    password = os.getenv("DB_ENCRYPTION_PASSWORD")
    if password and len(password) >= 8:
        salt = os.urandom(16)
        key = derive_key_from_password(password, salt)
        try:
            with open(key_file, "wb") as f:
                f.write(key)
            with open(salt_file, "wb") as f:
                f.write(salt)
        except:
            pass
        return key
    key = Fernet.generate_key()
    try:
        with open(key_file, "wb") as f:
            f.write(key)
    except:
        pass
    return key

ENCRYPTION_KEY = get_encryption_key()
cipher_suite = Fernet(ENCRYPTION_KEY)

def get_backup_encryption_key() -> bytes:
    backup_key_file = DATA_PATH / ".backup_key"
    if backup_key_file.exists():
        try:
            with open(backup_key_file, "rb") as f:
                return f.read()
        except:
            pass
    new_key = Fernet.generate_key()
    try:
        with open(backup_key_file, "wb") as f:
            f.write(new_key)
    except:
        pass
    return new_key

BACKUP_ENCRYPTION_KEY = get_backup_encryption_key()
BACKUP_CIPHER = Fernet(BACKUP_ENCRYPTION_KEY)

SUPPORTED_LANGUAGES = {
    "ar": "العربية 🇸🇦",
    "en": "English 🇬🇧",
    "fr": "Français 🇫🇷",
    "tr": "Türkçe 🇹🇷",
    "zh": "中文 🇨🇳",
    "ru": "Русский 🇷🇺",
    "de": "Deutsch 🇩🇪",
    "es": "Español 🇪🇸",
    "it": "Italiano 🇮🇹",
    "pt": "Português 🇵🇹",
    "ja": "日本語 🇯🇵",
    "ko": "한국어 🇰🇷"
}

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
    if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt

def mecca_to_utc(mecca_dt):
    if mecca_dt is None:
        return None
    if hasattr(mecca_dt, "tzinfo") and mecca_dt.tzinfo is not None:
        mecca_dt = mecca_dt.replace(tzinfo=None)
    return mecca_dt - timedelta(hours=3)

def utc_to_mecca(utc_dt):
    if utc_dt is None:
        return None
    if hasattr(utc_dt, "tzinfo") and utc_dt.tzinfo is not None:
        utc_dt = utc_dt.replace(tzinfo=None)
    return utc_dt + timedelta(hours=3)
