import sys, os, asyncio, importlib

# تعطيل التحقق من التشغيل الواحد
sys.path.insert(0, '.')

# استيراد البوت
import reelax_bot

# تعطيل القفل
reelax_bot.lock_socket = None

# تشغيل الدالة الرئيسية
try:
    asyncio.run(reelax_bot.main())
except KeyboardInterrupt:
    print("🛑 تم الإيقاف")
except Exception as e:
    print(f"❌ خطأ: {e}")
    import traceback
    traceback.print_exc()
