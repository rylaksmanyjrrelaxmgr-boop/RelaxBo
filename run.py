import asyncio
import sys
import os
from pathlib import Path

# تعيين المسار
BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

# تحميل .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

# تعيين المتغيرات مسبقاً
os.environ.setdefault("BOT_TOKEN", "توكنك_هنا")
os.environ.setdefault("MAIN_ADMIN_ID", "0")
os.environ.setdefault("BOT_USERNAME", "اسم_البوت")

# تشغيل البوت الأصلي
if __name__ == "__main__":
    try:
        exec(open("reelax_bot.py").read())
    except Exception as e:
        print("❌ الخطأ:", e)
        import traceback
        traceback.print_exc()
