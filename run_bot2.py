import sys, os, asyncio
sys.path.insert(0, '.')

# تحميل الكود وتنفيذ الدالة الرئيسية
with open("reelax_bot.py", "r") as f:
    code = f.read()

# تعطيل التحقق من التشغيل الواحد
code = code.replace("lock_socket = check_single_instance()", "lock_socket = None")

# تنفيذ الكود
exec(code)

# استدعاء الدالة الرئيسية
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("🛑 تم الإيقاف")
except Exception as e:
    print(f"❌ خطأ: {e}")
    import traceback
    traceback.print_exc()
