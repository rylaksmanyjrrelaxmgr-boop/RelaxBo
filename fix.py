import sys, os, traceback, asyncio
from pathlib import Path
from dotenv import load_dotenv

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
load_dotenv()

# تأكد من وجود المتغيرات
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("❌ BOT_TOKEN غير موجود. اكتبه في .env")
    sys.exit(1)

print(f"✅ TOKEN: {TOKEN[:10]}...")
print(f"✅ ADMIN: {os.getenv('MAIN_ADMIN_ID')}")

try:
    import reelax_bot as bot
except Exception as e:
    print("❌ فشل الاستيراد:")
    traceback.print_exc()
    sys.exit(1)

async def main():
    try:
        await bot.main()
    except Exception as e:
        print("❌ خطأ في main():", e)
        traceback.print_exc()
        with open("error.log", "w") as f:
            f.write(traceback.format_exc())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 تم الإيقاف")
