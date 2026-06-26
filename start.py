import sys, os, asyncio, subprocess

# قتل أي عمليات سابقة
subprocess.run("pkill -f python", shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

# حذف ملفات القفل
os.system("rm -f ~/.bot_* /tmp/bot_* *.sock 2>/dev/null")

# تعطيل التحقق من التشغيل الواحد في الكود الأصلي
with open("reelax_bot.py", "r") as f:
    content = f.read()
content = content.replace("lock_socket = check_single_instance()", "lock_socket = None")
content = content.replace("    lock_socket = check_single_instance()", "    lock_socket = None")
with open("reelax_bot.py", "w") as f:
    f.write(content)

print("✅ تم تعطيل التحقق من التشغيل الواحد")
print("🚀 جاري تشغيل البوت...")

# تشغيل البوت
os.system("python3 reelax_bot.py")
