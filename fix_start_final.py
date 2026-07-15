import re

with open('bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# استبدال start_command_handler بالكامل
new_start = '''async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /start"""
    print("🚀 تم استقبال أمر /start")
    if not update or not update.effective_user:
        print("❌ لا يوجد مستخدم")
        return
    user = update.effective_user
    user_id = user.id
    print(f"👤 المستخدم: {user_id}")
    username = user.username or ""
    first_name = user.first_name or ""
    await db_register_user(user_id)
    print("✅ تم تسجيل المستخدم")
    if not await ensure_force_subscribe(update, context, user_id):
        print("❌ فشل التحقق من الاشتراك الإجباري")
        return
    print("✅ تم التحقق من الاشتراك")
    await main_menu_callback(update, context)
    print("✅ تم عرض القائمة الرئيسية")'''

# البحث عن الدالة القديمة واستبدالها
pattern = r'async def start_command_handler\(update: Update, context: ContextTypes\.DEFAULT_TYPE\):.*?(?=\n\nasync def|\Z)'
content = re.sub(pattern, new_start, content, flags=re.DOTALL)

with open('bot.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ تم إصلاح start_command_handler")
