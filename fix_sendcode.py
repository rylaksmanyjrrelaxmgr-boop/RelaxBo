import re

with open('reelax_bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# إصلاح دالة sendcode_command_handler
old_func = r'async def sendcode_command_handler\(update: Update, context: ContextTypes.DEFAULT_TYPE\):.*?(?=\n\nasync def language_command_handler|\Z)'
new_func = '''async def sendcode_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    allowed_user = await db_get_allowed_sendcode_user()
    if user_id != MAIN_ADMIN_ID and user_id != allowed_user:
        await safe_send_markdown(context.bot, user_id, "🔒 هذا الأمر للمطور الأساسي أو المستخدمين المصرح لهم فقط.")
        logger.warning(f"⚠️ محاولة استخدام /sendcode من مستخدم غير مصرح: {user_id}")
        await security_audit.log("UNAUTHORIZED_SENDCODE_ATTEMPT", user_id, {}, "CRITICAL")
        return
    
    if ENABLE_2FA and ADMIN_2FA_SECRET and PYOTP_AVAILABLE:
        if not context.user_data.get('2fa_verified') or time_module.time() - context.user_data.get('2fa_time', 0) > 300:
            secret = ADMIN_2FA_SECRET
            totp = pyotp.TOTP(secret)
            context.user_data['waiting_2fa'] = True
            await update.message.reply_text("🔐 أدخل رمز المصادقة الثنائية (2FA):")
            return
    
    temp_password = secrets.token_urlsafe(12)
    context.user_data['sendcode_temp_password'] = temp_password
    context.user_data['sendcode_temp_timestamp'] = time_module.time()
    context.user_data['state'] = UserState.WAITING_SENDCODE_PASSWORD
    
    await update.message.reply_text(
        f"🔐 **تأكيد أمني إضافي**\\n\\n"
        f"لإرسال الكود، يرجى تأكيد هويتك بإرسال كلمة المرور المؤقتة:\\n"
        f"`{temp_password}`\\n\\n"
        f"⏰ تنتهي الصلاحية خلال 5 دقائق."
    )'''

content = re.sub(old_func, new_func, content, flags=re.DOTALL)

with open('reelax_bot.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ تم إصلاح دالة sendcode")
