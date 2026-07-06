# -*- coding: utf-8 -*-
import os
import secrets
from pathlib import Path
from dotenv import load_dotenv

BASE_PATH = Path(__file__).parent.resolve()

def get_env(key, default=None, env_type=str):
    value = os.getenv(key)
    if value is None:
        return default
    try:
        if env_type == bool:
            return value.lower() in ["true", "1", "yes", "on"]
        return env_type(value)
    except:
        return default

load_dotenv()

TOKEN = get_env("BOT_TOKEN", None, str)
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN غير موجود")

MAIN_ADMIN_ID = get_env("MAIN_ADMIN_ID", 0, int)
if MAIN_ADMIN_ID == 0:
    raise ValueError("❌ MAIN_ADMIN_ID غير موجود")

BOT_NAME = get_env("BOT_NAME", "ريلاكس مانيجر", str)
BOT_USERNAME = get_env("BOT_USERNAME", "Reelaaaxbot", str)
USE_PROXY = get_env("USE_PROXY", False, bool)
PROXY_URL = get_env("PROXY_URL", "http://127.0.0.1:10809", str)

PORT = int(os.getenv("PORT", 10000))
WEB_HOST = "0.0.0.0"

DB_PATH = BASE_PATH / "data" / "bot_data.db"
DB_TIMEOUT = 30
MAX_CONNECTIONS = 20
DEFAULT_PUBLISH_INTERVAL_SECONDS = 720
MAX_UNPUBLISHED_POSTS = 1000
MAX_FILE_SIZE = get_env("MAX_FILE_SIZE", 20 * 1024 * 1024, int)
MAX_BACKUPS = get_env("MAX_BACKUPS", 10, int)

NSFW_ENABLED = get_env("NSFW_ENABLED", True, bool)
NSFW_THRESHOLD = get_env("NSFW_THRESHOLD", 0.7, float)

BACKUP_DIR = BASE_PATH / "backups"
LOG_PATH = BASE_PATH / "logs" / "bot.log"
TRANSLATIONS_PATH = BASE_PATH / "translations"
TEMPLATES_PATH = BASE_PATH / "static" / "templates"
DATA_PATH = BASE_PATH / "data"

for path in [BACKUP_DIR, LOG_PATH.parent, TRANSLATIONS_PATH, TEMPLATES_PATH, DATA_PATH]:
    path.mkdir(parents=True, exist_ok=True)
