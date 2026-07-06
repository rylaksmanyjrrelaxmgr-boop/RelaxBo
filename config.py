import os
from cryptography.fernet import Fernet

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN غير موجود!")

OWNER_ID = int(os.getenv("OWNER_ID", "0"))
BOT_NAME = os.getenv("BOT_NAME", "ريلاكس مانيجر")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Reelaaaxbot")
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = "data/bot.db"

ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print("⚠️ تم إنشاء مفتاح تشفير جديد. احفظه في متغيرات البيئة!")

try:
    fernet = Fernet(ENCRYPTION_KEY.encode())
except Exception:
    raise ValueError("❌ مفتاح تشفير غير صالح!")
