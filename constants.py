#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ثوابت وإعدادات عامة - النسخة النهائية المعتمدة للإنتاج
"""

import os, sys, asyncio, secrets, json, logging, getpass
from pathlib import Path
from enum import Enum, auto
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_env_int(key: str, default: int) -> int:
    try: return int(os.getenv(key, str(default)))
    except: return default

def get_env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() in ['true','1','yes','on']

def get_env_float(key: str, default: float) -> float:
    try: return float(os.getenv(key, str(default)))
    except: return default

if sys.version_info < (3,8):
    logger.critical("❌ يحتاج البوت إلى بايثون 3.8 أو أحدث")
    sys.exit(1)

BASE_PATH = Path(__file__).parent.resolve()
DATA_PATH = BASE_PATH / "data"
DB_PATH = DATA_PATH / "bot_data.db"
BACKUP_DIR = BASE_PATH / "backups"
LOG_PATH = BASE_PATH / "logs" / "bot.log"
SECURITY_LOG = BASE_PATH / "logs" / "security.log"
ERROR_LOG = BASE_PATH / "logs" / "errors.log"
ACCESS_LOG = BASE_PATH / "logs" / "access.log"
TEMP_PATH = BASE_PATH / "temp"
STATIC_PATH = BASE_PATH / "static"
TEMPLATES_PATH = BASE_PATH / "templates"
LANG_PATH = BASE_PATH / "lang"
BANNED_WORDS_FILE = BASE_PATH / "banned_words.txt"

for p in [DATA_PATH, BACKUP_DIR, LOG_PATH.parent, TEMP_PATH, STATIC_PATH, TEMPLATES_PATH, LANG_PATH]:
    try: p.mkdir(parents=True, exist_ok=True)
    except: logger.critical(f"❌ لا يمكن إنشاء {p}"); sys.exit(1)

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN: logger.critical("❌ BOT_TOKEN مفقود"); sys.exit(1)

PRIMARY_OWNER_ID = get_env_int("MAIN_ADMIN_ID", 0)
if PRIMARY_OWNER_ID == 0: logger.critical("❌ MAIN_ADMIN_ID غير محدد"); sys.exit(1)

BOT_NAME = os.getenv("BOT_NAME", "ريلاكس مانيجر")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Reelaaaxbot")
USE_PROXY = get_env_bool("USE_PROXY", False)
PROXY_URL = os.getenv("PROXY_URL", "http://127.0.0.1:10809")
ENABLE_2FA = get_env_bool("ENABLE_2FA", False)
ADMIN_2FA_SECRET = os.getenv("ADMIN_2FA_SECRET", "")
DB_ENCRYPTION = get_env_bool("DB_ENCRYPTION", True)
MAX_BACKUPS = get_env_int("MAX_BACKUPS", 10)
SECURITY_LOG_LEVEL = os.getenv("SECURITY_LOG_LEVEL", "CRITICAL")

GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
CLOUD_BACKUP_ENABLED = get_env_bool("CLOUD_BACKUP_ENABLED", False)
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = os.getenv("TOKEN_FILE", "token.json")

RENDER_PORT = get_env_int("PORT", 10000)
WEB_PORT = get_env_int("WEB_PORT", RENDER_PORT)
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")
ENVIRONMENT = os.getenv('ENVIRONMENT', 'development')
if not WEB_PASSWORD and ENVIRONMENT == 'production':
    WEB_PASSWORD = secrets.token_urlsafe(16)

WEB_USERNAME = os.getenv("WEB_USERNAME", "admin")
WEB_SECRET_KEY = os.getenv("WEB_SECRET_KEY", "") or secrets.token_urlsafe(32)
WEB_SESSION_TIMEOUT = get_env_int("WEB_SESSION_TIMEOUT", 3600)
WEB_RATE_LIMIT = get_env_int("WEB_RATE_LIMIT", 100)
WEB_RATE_WINDOW = get_env_int("WEB_RATE_WINDOW", 60)

BATTERY_SAVER_MODE = get_env_bool("BATTERY_SAVER_MODE", False)

DEFAULT_PUBLISH_INTERVAL_SECONDS = 12*60
CLEANUP_SLEEP = 60*60
ONE_DAY_SECONDS = 24*60*60
ONE_WEEK_SECONDS = 7*ONE_DAY_SECONDS

if BATTERY_SAVER_MODE:
    POLL_INTERVAL=10.0; SCHEDULED_POSTS_SLEEP=120; REMINDERS_SLEEP=2*3600; AUTO_BACKUP_SLEEP=2*ONE_DAY_SECONDS
else:
    POLL_INTERVAL=1.0; SCHEDULED_POSTS_SLEEP=10; REMINDERS_SLEEP=3600; AUTO_BACKUP_SLEEP=ONE_DAY_SECONDS

MAX_FILE_SIZE = get_env_int('MAX_FILE_SIZE', 20*1024*1024)
MAX_CHANNELS_PER_CYCLE = get_env_int('MAX_CHANNELS_PER_CYCLE', 20)
PUBLISH_RETRY_DELAY = 5*60
MAX_POSTS_PER_SESSION = 50
MAX_UNPUBLISHED_POSTS = 1000
DB_TIMEOUT = 30
MAX_CONNECTIONS = 20

SIGHTENGINE_API_USER = os.getenv("SIGHTENGINE_API_USER", "")
SIGHTENGINE_API_SECRET = os.getenv("SIGHTENGINE_API_SECRET", "")
NSFW_ENABLED = get_env_bool("NSFW_ENABLED", True)
NSFW_THRESHOLD = get_env_float("NSFW_THRESHOLD", 0.7)
NSFW_MAX_FILE_SIZE = get_env_int("NSFW_MAX_FILE_SIZE", 5*1024*1024)
NSFW_MAX_VIDEO_SIZE = get_env_int("NSFW_MAX_VIDEO_SIZE", 10*1024*1024)
NSFW_FRAMES = get_env_int("NSFW_FRAMES", 5)

SUPPORTED_LANGUAGES = {
    'ar':'العربية 🇸🇦','en':'English 🇬🇧','fr':'Français 🇫🇷','tr':'Türkçe 🇹🇷',
    'zh':'中文 🇨🇳','ru':'Русский 🇷🇺','de':'Deutsch 🇩🇪','es':'Español 🇪🇸',
    'it':'Italiano 🇮🇹','pt':'Português 🇵🇹','ja':'日本語 🇯🇵','ko':'한국어 🇰🇷'
}

LEVEL_REQUIREMENTS = {1:0,2:100,3:250,4:500,5:1000,6:2000,7:3500,8:5000,9:7500,10:10000}

class UserState(Enum):
    WAITING_CHANNEL_ID=auto(); ADDING_POSTS=auto(); WAITING_INTERVAL_MINUTES=auto()
    WAITING_INTERVAL_HOURS=auto(); WAITING_INTERVAL_DAYS=auto(); WAITING_DATES=auto()
    WAITING_PUBLISH_TIME=auto(); WAITING_SCHEDULE_POST=auto(); WAITING_REMINDER_DAYS=auto()
    WAITING_UPDATE_TEXT=auto(); WAITING_UPDATE_CHANNEL=auto(); WAITING_FORCE_CHANNEL=auto()
    WAITING_BROADCAST=auto(); WAITING_SENDCODE_USER=auto(); WAITING_LOG_CHANNEL=auto()
    WAITING_KEYWORD=auto(); WAITING_REPLY=auto(); WAITING_ADMIN_ID_ADD=auto()
    WAITING_ADMIN_ID_REMOVE=auto(); WAITING_GROUP_BANNED_WORD=auto()
    WAITING_REMOVE_GROUP_BANNED_WORD=auto(); WAITING_GLOBAL_BANNED_WORD=auto()
    WAITING_REMOVE_GLOBAL_BANNED_WORD=auto(); WAITING_NSFW_THRESHOLD=auto()
    WAITING_BAN_USER=auto(); WAITING_MUTE_USER=auto(); WAITING_WARN_USER=auto()
    WAITING_KICK_USER=auto(); WAITING_RESTRICT_USER=auto(); WAITING_UNBAN_USER=auto()
    WAITING_PIN_MESSAGE=auto(); WAITING_CONTEST_TITLE=auto()
    WAITING_CONTEST_DESCRIPTION=auto(); WAITING_CONTEST_PRIZE=auto()
    WAITING_CONTEST_END_DATE=auto(); WAITING_CONTEST_ANSWER=auto()
    WAITING_SENDCODE_PASSWORD=auto(); SELECTING_DAYS=auto()

class CallbackData:
    MAIN_MENU="main_menu"
    CHANNELS_MY="channels:my_channels"; CHANNELS_ADD="channels:add"
    CHANNELS_DELETE_PREFIX="channels:delete:"; CHANNELS_SELECT_PREFIX="channels:select:"
    POSTS_ADD_15="posts:add_15"; POSTS_PUBLISH_ONE="posts:publish_one"
    POSTS_MY="posts:my_posts"; POSTS_RECYCLE="posts:recycle"
    POSTS_DELETE_SINGLE_PREFIX="posts:delete_single:"
    POSTS_CONFIRM_CLEAR_ALL_PREFIX="posts:confirm_clear_all:"
    POSTS_CLEAR_ALL_PREFIX="posts:clear_all:"
    STATS_PENDING="stats:pending"; STATS_FULL="stats:full"
    GROUPS_MY="groups:my_groups"; GROUPS_SETTINGS_PREFIX="groups:settings:"
    SETTINGS_MENU="settings:menu"; SETTINGS_TOGGLE_AUTO_PUBLISH="settings:toggle_auto_publish"
    SETTINGS_TOGGLE_AUTO_RECYCLE="settings:toggle_auto_recycle"
    SCHEDULE_MENU_PREFIX="schedule:menu:"
    SCHEDULE_SET_INTERVAL_MINUTES_PREFIX="schedule:set_interval_minutes:"
    SCHEDULE_SET_INTERVAL_HOURS_PREFIX="schedule:set_interval_hours:"
    SCHEDULE_SET_INTERVAL_DAYS_PREFIX="schedule:set_interval_days:"
    SCHEDULE_SET_DAYS_PREFIX="schedule:set_days:"; SCHEDULE_SET_DATES_PREFIX="schedule:set_dates:"
    SCHEDULE_SET_PUBLISH_TIME_PREFIX="schedule:set_publish_time:"
    SCHEDULE_DAY_SELECT_PREFIX="schedule:day_select:"; SCHEDULE_SAVE_DAYS="schedule:save_days"
    SECURITY_LINKS_PREFIX="security:links:"; SECURITY_MENTIONS_PREFIX="security:mentions:"
    SECURITY_WARN_PREFIX="security:warn:"; SECURITY_SLOWMODE_PREFIX="security:slowmode:"
    SECURITY_BANNED_WORDS_MENU_PREFIX="security:banned_words_menu:"
    SECURITY_WELCOME_PREFIX="security:welcome:"; SECURITY_GOODBYE_PREFIX="security:goodbye:"
    SECURITY_STICKERS_PREFIX="security:stickers:"; SECURITY_VIDEOS_PREFIX="security:videos:"
    SECURITY_SERVICE_MESSAGES_PREFIX="security:service_messages:"
    SECURITY_MAIN="security:main"; SECURITY_CLOSE="security:close"
    BANNED_WORDS_ADD_PREFIX="banned_words:add:"; BANNED_WORDS_LIST_PREFIX="banned_words:list:"
    BANNED_WORDS_REMOVE_PREFIX="banned_words:remove:"
    HELP="help"; SUPPORT_MENU="support:menu"; SUPPORT_HELP="support:help"
    SUPPORT_TICKET="support:ticket"; SUPPORT_BACK="support:back"
    TRIAL="trial"; SUBSCRIBE_MENU="subscribe:menu"
    BUY_SUBSCRIPTION_1="buy:subscription_1"; BUY_SUBSCRIPTION_2="buy:subscription_2"
    BUY_SUBSCRIPTION_30="buy:subscription_30"; BUY_SUBSCRIPTION_90="buy:subscription_90"
    DEVELOPER="developer"; UPDATES="updates"
    REFERRAL_MENU="referral:menu"; REFERRAL_COPY_LINK_PREFIX="referral:copy_link:"
    REFERRAL_CLAIM_REWARD="referral:claim_reward"; REFERRAL_LIST="referral:list"
    REMINDER_MENU="reminder:menu"; REMINDER_TOGGLE_SUB="reminder:toggle_sub"
    REMINDER_TOGGLE_DAILY="reminder:toggle_daily"; REMINDER_TOGGLE_WEEKLY="reminder:toggle_weekly"
    REMINDER_SET_DAYS="reminder:set_days"; REMINDER_SET_LANG="reminder:set_lang"
    REMINDER_LANG_PREFIX="reminder:lang:"
    TRANSLATION_MENU="translation:menu"; TRANSLATION_OFF="translation:off"
    TRANSLATION_SET_PREFIX="translation:set:"
    ADMIN_PANEL="admin:panel"; ADMIN_USERS="admin:users"
    ADMIN_BANNED_USERS="admin:banned_users"; ADMIN_UNBAN_ALL_USERS="admin:unban_all_users"
    ADMIN_ALL_CHANNELS="admin:all_channels"; ADMIN_BANNED_CHANNELS="admin:banned_channels"
    ADMIN_ACTIVATE_ALL_CHANNELS="admin:activate_all_channels"
    ADMIN_GROUPS="admin:groups"; ADMIN_BANNED_GROUPS="admin:banned_groups"
    ADMIN_UNBAN_ALL_GROUPS="admin:unban_all_groups"
    ADMIN_BOT_CHANNELS="admin:bot_channels"; ADMIN_BANNED_BOT_CHANNELS="admin:banned_bot_channels"
    ADMIN_UNBAN_ALL_BOT_CHANNELS="admin:unban_all_bot_channels"
    ADMIN_MONITOR_USERS="admin:monitor_users"
    ADMIN_ADD_ADMIN="admin:add_admin"; ADMIN_REMOVE_ADMIN="admin:remove_admin"
    ADMIN_RAM="admin:ram"; ADMIN_STATS="admin:stats"; ADMIN_METRICS="admin:metrics"
    ADMIN_BACKUP="admin:backup"; ADMIN_RESTORE_BACKUP="admin:restore_backup"
    ADMIN_RESTORE_BACKUP_SELECT_PREFIX="admin:restore_backup_select:"
    ADMIN_BACKUP_SETTINGS="admin:backup_settings"; ADMIN_TOGGLE_AUTO_BACKUP="admin:toggle_auto_backup"
    ADMIN_CHANGE_INTERVAL="admin:change_interval"
    ADMIN_SEND_UPDATE="admin:send_update"; ADMIN_SET_UPDATE_CHANNEL="admin:set_update_channel"
    ADMIN_SHOW_UPDATE_CHANNEL="admin:show_update_channel"; ADMIN_UPDATES="admin:updates"
    ADMIN_FORCE_SUBSCRIBE="admin:force_subscribe"; ADMIN_SET_FORCE_CHANNEL="admin:set_force_channel"
    ADMIN_BROADCAST="admin:broadcast"; ADMIN_CONFIRM_BROADCAST="admin:confirm_broadcast"
    ADMIN_SUPPORT_TICKETS="admin:support_tickets"; ADMIN_DELETE_ALL_TICKETS="admin:delete_all_tickets"
    ADMIN_CONFIRM_DELETE_TICKETS="admin:confirm_delete_tickets"
    ADMIN_MANAGE_SENDCODE="admin:manage_sendcode"; ADMIN_SET_SENDCODE_USER="admin:set_sendcode_user"
    ADMIN_SHOW_LOG_CHANNEL="admin:show_log_channel"; ADMIN_SET_LOG_CHANNEL="admin:set_log_channel"
    ADMIN_REPLIES="admin:replies"; ADMIN_ADD_REPLY="admin:add_reply"
    ADMIN_LIST_REPLIES="admin:list_replies"; ADMIN_DEL_REPLY="admin:del_reply"
    ADMIN_BANNED_WORDS="admin:banned_words"; ADMIN_ADD_BANNED_WORD="admin:add_banned_word"
    ADMIN_LIST_BANNED_WORDS="admin:list_banned_words"; ADMIN_REMOVE_BANNED_WORD="admin:remove_banned_word"
    ADMIN_CREATE_CONTEST="admin:create_contest"; ADMIN_DECLARE_WINNER="admin:declare_winner"
    PANEL_LOCK_PREFIX="panel:lock:"; PANEL_UNLOCK_PREFIX="panel:unlock:"; PANEL_CLOSE="panel:close"
    CHECK_SUBSCRIBE="check_subscribe"; BACK="back"; CANCEL_SESSION="cancel_session"
    ADVANCED_ACTIONS="advanced_actions"
    GROUP_ACTION_BAN="group_action:ban"; GROUP_ACTION_MUTE="group_action:mute"
    GROUP_ACTION_WARN="group_action:warn"; GROUP_ACTION_KICK="group_action:kick"
    GROUP_ACTION_RESTRICT="group_action:restrict"; GROUP_ACTION_PIN="group_action:pin"
    GROUP_ACTION_LOG="group_action:log"; GROUP_ACTION_UNBAN="group_action:unban"
    GROUP_MUTE_DURATION_5="group_mute_duration:5"; GROUP_MUTE_DURATION_30="group_mute_duration:30"
    GROUP_MUTE_DURATION_60="group_mute_duration:60"; GROUP_MUTE_DURATION_720="group_mute_duration:720"
    GROUP_MUTE_DURATION_1440="group_mute_duration:1440"; GROUP_MUTE_DURATION_10080="group_mute_duration:10080"
    GROUP_MUTE_DURATION_PERMANENT="group_mute_duration:permanent"
    SECURITY_SELECT_GROUP="security_select_group:"; SECURITY_REFRESH_GROUPS="security_refresh_groups"
    PENALTY_MENU="penalty_menu"; PENALTY_KICK="penalty:kick"; PENALTY_BAN="penalty:ban"; PENALTY_MUTE="penalty:mute"
    PUBLISH_ALL_CHANNELS="publish_all_channels"
    CHANNEL_STATS="channel_stats"; CHANNEL_GROWTH="channel_growth"
    CHANNEL_STATS_REFRESH="channel_stats_refresh"; MY_CHANNEL_STATS="my_channel_stats"
    ADMIN_TOGGLE_CHANNEL_BAN_PREFIX="admin:toggle_channel_ban:"
    ADMIN_TOGGLE_GROUP_BAN_PREFIX="admin:toggle_group_ban:"
    CONTESTS_MENU="contests_menu"; CONTEST_JOIN_PREFIX="contest_join:"
    CONTEST_WINNERS="contest_winners"; CONTESTS_BACK="contests_back"
    ADMIN_DEL_CONTEST_PREFIX="admin:del_contest:"
    HIDDEN_ADMIN_ADD="hidden_admin:add"; HIDDEN_ADMIN_REMOVE_PREFIX="hidden_admin:remove:"
    HIDDEN_ADMIN_LIST="hidden_admin:list"
    ADMIN_AUTO_REPLY="admin_auto_reply"; ADMIN_AUTO_REPLY_SELECT_PREFIX="admin_auto_reply_select:"
    AUTO_REPLY_MENU_PREFIX="auto_reply_menu:"; AUTO_REPLY_TOGGLE_PREFIX="auto_reply_toggle:"
    AUTO_REPLY_ADMINS_PREFIX="auto_reply_admins:"; AUTO_REPLY_RESET_PREFIX="auto_reply_reset:"
    AUTO_REPLY_CONFIRM_RESET_PREFIX="auto_reply_confirm_reset:"
    AUTO_REPLY_CANCEL_PREFIX="auto_reply_cancel:"; AUTO_REPLY_STATS_PREFIX="auto_reply_stats:"
    USER_AUTO_REPLY_TOGGLE_PREFIX="user_auto_reply_toggle:"
    NSFW_SETTINGS="nsfw_settings"; NSFW_TOGGLE="nsfw_toggle"; NSFW_THRESHOLD_SET="nsfw_threshold_set"

# Encryption setup
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    import base64
except ImportError:
    logger.critical("❌ حزمة cryptography غير مثبتة"); sys.exit(1)

def derive_key_from_password(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))

def get_encryption_key() -> bytes:
    key_file = DATA_PATH / ".db_key"
    salt_file = DATA_PATH / ".db_salt"
    if key_file.exists() and not salt_file.exists():
        logger.critical("❌ ملف الملح مفقود"); sys.exit(1)
    if key_file.exists() and salt_file.exists():
        with open(key_file,'rb') as f: return f.read()
    password = os.getenv('DB_ENCRYPTION_PASSWORD')
    if password and len(password)>=8:
        salt = os.urandom(16)
        key = derive_key_from_password(password, salt)
        with open(key_file,'wb') as f: f.write(key)
        os.chmod(key_file, 0o600)
        with open(salt_file,'wb') as f: f.write(salt)
        os.chmod(salt_file, 0o600)
        return key
    if not sys.stdin.isatty():
        key = Fernet.generate_key()
        with open(key_file,'wb') as f: f.write(key)
        os.chmod(key_file, 0o600)
        salt_file.touch(); os.chmod(salt_file, 0o600)
        return key
    try:
        password = getpass.getpass("كلمة المرور: ")
        if len(password)<8: logger.critical("❌ كلمة المرور قصيرة"); sys.exit(1)
        salt = os.urandom(16)
        key = derive_key_from_password(password, salt)
        with open(key_file,'wb') as f: f.write(key)
        os.chmod(key_file, 0o600)
        with open(salt_file,'wb') as f: f.write(salt)
        os.chmod(salt_file, 0o600)
        return key
    except: sys.exit(1)

ENCRYPTION_KEY = get_encryption_key()
cipher_suite = Fernet(ENCRYPTION_KEY)

def get_backup_encryption_key() -> bytes:
    backup_key_file = DATA_PATH / ".backup_key"
    if backup_key_file.exists():
        with open(backup_key_file,'rb') as f: return f.read()
    key = Fernet.generate_key()
    with open(backup_key_file,'wb') as f: f.write(key)
    os.chmod(backup_key_file, 0o600)
    return key

BACKUP_ENCRYPTION_KEY = get_backup_encryption_key()
BACKUP_CIPHER = Fernet(BACKUP_ENCRYPTION_KEY)

JINJA2_AVAILABLE = False
try: import jinja2; JINJA2_AVAILABLE = True
except: pass

PYOTP_AVAILABLE = False
try: import pyotp; PYOTP_AVAILABLE = True
except: pass

ZSTD_AVAILABLE = False
try: import zstandard; ZSTD_AVAILABLE = True; ZSTD_COMPRESSOR = zstandard.ZstdCompressor(level=3); ZSTD_DECOMPRESSOR = zstandard.ZstdDecompressor()
except: pass

CV2_AVAILABLE = False
try: import cv2; import numpy as np; CV2_AVAILABLE = True
except: pass

GOOGLE_AUTH_AVAILABLE = False
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    GOOGLE_AUTH_AVAILABLE = True
except: pass

user_language = {}
user_points_last_hour = defaultdict(lambda: (0,0.0))

NSFW_CACHE = {}
NSFW_CACHE_TTL = 300
try:
    from cachetools import TTLCache
    NSFW_CACHE = TTLCache(maxsize=1000, ttl=300)
except: pass

_NSFW_CACHE_LOCK = None
def get_nsfw_lock():
    global _NSFW_CACHE_LOCK
    if _NSFW_CACHE_LOCK is None: _NSFW_CACHE_LOCK = asyncio.Lock()
    return _NSFW_CACHE_LOCK

WEB_PORT_USED = WEB_PORT

async def send_web_password_to_owner(bot):
    if ENVIRONMENT == 'production' and WEB_PASSWORD and PRIMARY_OWNER_ID:
        try:
            await bot.send_message(PRIMARY_OWNER_ID,
                f"🔑 **كلمة مرور الويب:**\n`{WEB_PASSWORD}`\n\n"
                f"🌐 رابط لوحة التحكم: http://{WEB_HOST}:{WEB_PORT}\n"
                f"👤 اسم المستخدم: {WEB_USERNAME}", parse_mode="Markdown")
        except: pass
WEB_PORT = get_env_int("WEB_PORT", 10000)
