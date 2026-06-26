import re

with open('reelax_bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# إصلاح دالة handle_sendcode_confirmation_handler
old_confirm = r'async def handle_sendcode_confirmation_handler\(update: Update, context: ContextTypes.DEFAULT_TYPE\):.*?(?=\n\nasync def language_command_handler|\Z)'
new_confirm = '''async def handle_sendcode_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج تأكيد إرسال الكود - مصحح."""
    user_id = update.effective_user.id
    expected_password = context.user_data.get('sendcode_temp_password')
    timestamp = context.user_data.get('sendcode_temp_timestamp', 0)
    
    if not expected_password:
        await update.message.reply_text("❌ لم يتم طلب إرسال كود")
        context.user_data.pop('state', None)
        return
    
    if time_module.time() - timestamp > 300:
        await update.message.reply_text("❌ انتهت صلاحية كلمة المرور. أعد استخدام الأمر /sendcode")
        context.user_data.pop('sendcode_temp_password', None)
        context.user_data.pop('sendcode_temp_timestamp', None)
        context.user_data.pop('state', None)
        return
    
    if update.message.text.strip() == expected_password:
        try:
            with open(__file__, 'r', encoding='utf-8') as f:
                content = f.read()
            
            watermark = f"""# ============================================================
# ORIGINAL_OWNER: {user_id}
# GENERATED_AT: {mecca_now().strftime('%Y-%m-%d %H:%M:%S')}
# SIGNATURE: {hashlib.sha256(f"{user_id}{time_module.time()}{TOKEN}".encode()).hexdigest()[:16]}
# ============================================================
# ⚠️ تحذير: هذا الكود يحتوي على معلومات حساسة
# لا تشاركه مع أي شخص غير موثوق
# ============================================================

"""
            watermarked_content = watermark + content
            
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, f"bot_code_{user_id}_{int(time_module.time())}.py")
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(watermarked_content)
            
            with open(temp_file, 'rb') as f:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=f,
                    filename=f"relax_bot_secure_{mecca_now().strftime('%Y%m%d')}.py",
                    caption="✅ **كود البوت - نسخة آمنة**\\n\\n🔑 موقّع رقمياً بإسمك\\n📅 تم الإنشاء: " + mecca_now().strftime('%Y-%m-%d %H:%M:%S') + "\\n\\n⚠️ لا تشارك هذا الملف مع أي شخص!"
                )
            
            os.unlink(temp_file)
            
            await update.message.reply_text("✅ **تم إرسال الكود على الخاص!** 📦\n\nافتح الدردشة مع البوت وابحث عن الملف.")
            logger.info(f"📁 تم إرسال كود البوت للمستخدم {user_id} على الخاص")
            
        except Exception as e:
            await update.message.reply_text(f"❌ فشل إرسال الكود: {str(e)[:100]}")
            logger.error(f"خطأ في إرسال الكود: {e}")
        
        context.user_data.pop('sendcode_temp_password', None)
        context.user_data.pop('sendcode_temp_timestamp', None)
        context.user_data.pop('state', None)
    else:
        await update.message.reply_text("❌ كلمة المرور غير صحيحة! تم إلغاء العملية.")
        context.user_data.pop('sendcode_temp_password', None)
        context.user_data.pop('sendcode_temp_timestamp', None)
        context.user_data.pop('state', None)'''

content = re.sub(old_confirm, new_confirm, content, flags=re.DOTALL)

# التأكد من أن state='waiting_sendcode_confirmation' يتم تعيينه بشكل صحيح
old_sendcode = r'async def sendcode_command_handler\(update: Update, context: ContextTypes.DEFAULT_TYPE\):.*?(?=\n\nasync def language_command_handler|\Z)'
new_sendcode = '''async def sendcode_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إرسال كود البوت - مع تأكيد أمني."""
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
    context.user_data['state'] = 'waiting_sendcode_confirmation'  # تأكد من تعيين الحالة
    
    await update.message.reply_text(
        f"🔐 **تأكيد أمني إضافي**\\n\\n"
        f"لإرسال الكود، يرجى تأكيد هويتك بإرسال كلمة المرور المؤقتة:\\n"
        f"`{temp_password}`\\n\\n"
        f"⏰ تنتهي الصلاحية خلال 5 دقائق."
    )'''

content = re.sub(old_sendcode, new_sendcode, content, flags=re.DOTALL)

with open('reelax_bot.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ تم إصلاح معالج تأكيد /sendcode!")
print("📌 أعد تشغيل البوت وجرب /sendcode مرة أخرى")
