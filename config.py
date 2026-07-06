import os
from pathlib import Path
from cryptography.fernet import Fernet

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN غير موجود!")

MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", 0))
PRIMARY_OWNER_ID = 8290212138
BOT_NAME = os.getenv("BOT_NAME", "ريلاكس مانيجر")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Reelaaaxbot")
PORT = int(os.getenv("PORT", 10000))

DB_PATH = Path("data/bot_data.db")
DB_PATH.parent.mkdir(exist_ok=True)

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print("⚠️ تم إنشاء مفتاح تشفير جديد. احفظه في متغيرات البيئة!")
