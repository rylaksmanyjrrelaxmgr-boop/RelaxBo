import re

# قراءة الملف الأصلي
with open('reelax_bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

# الدالة الجديدة لـ admin_create_contest_callback
new_create = '''
async def admin_create_contest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج زر إنشاء مسابقة من لوحة الأدمن (مصحح)."""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception as e:
            logger.warning(f"فشل الرد على الاستعلام: {e}")
    
    user_id = update.effective_user.id
    
    if user_id != MAIN_ADMIN_ID and not await is_bot_admin(user_id):
        if query:
            try:
                await query.edit_message_text(get_text(user_id, 'admin_only'))
            except:
                pass
        else:
            try:
                await update.message.reply_text(get_text(user_id, 'admin_only'))
            except:
                pass
        return
    
    context.user_data['state'] = UserState.WAITING_CONTEST_TITLE
    msg = get_text(user_id, 'create_contest_title')
    
    if query:
        try:
            await query.edit_message_text(msg, parse_mode="MarkdownV2")
        except Exception as e:
            logger.warning(f"فشل تعديل الرسالة في admin_create_contest_callback: {e}")
            try:
                await query.message.reply_text(msg, parse_mode="MarkdownV2")
            except:
                try:
                    await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
                except:
                    pass
    else:
        try:
            await update.message.reply_text(msg, parse_mode="MarkdownV2")
        except:
            try:
                await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
            except:
                pass
'''

# الدالة الجديدة لـ admin_declare_winner_callback
new_declare = '''
async def admin_declare_winner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج زر إعلان فائز من لوحة الأدمن (مصحح)."""
    query = update.callback_query
    if query:
        try:
            await query.answer()
        except Exception as e:
            logger.warning(f"فشل الرد على الاستعلام: {e}")
    
    user_id = update.effective_user.id
    
    if user_id != MAIN_ADMIN_ID and not await is_bot_admin(user_id):
        if query:
            try:
                await query.edit_message_text(get_text(user_id, 'admin_only'))
            except:
                pass
        else:
            try:
                await update.message.reply_text(get_text(user_id, 'admin_only'))
            except:
                pass
        return
    
    msg = "📝 **إعلان فائز في مسابقة**\\n\\nاستخدم الأمر:\\n`/declare_winner معرف_المسابقة معرف_المستخدم`\\n\\nمثال: `/declare_winner 5 123456789`\\n\\n📌 لعرض المسابقات النشطة استخدم `/contests`"
    
    if query:
        try:
            await query.edit_message_text(msg, parse_mode="MarkdownV2")
        except Exception as e:
            logger.warning(f"فشل تعديل الرسالة في admin_declare_winner_callback: {e}")
            try:
                await query.message.reply_text(msg, parse_mode="MarkdownV2")
            except:
                try:
                    await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
                except:
                    pass
    else:
        try:
            await update.message.reply_text(msg, parse_mode="MarkdownV2")
        except:
            try:
                await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="MarkdownV2")
            except:
                pass
'''

# استبدال الدوال في المحتوى
import re
pattern_create = r'async def admin_create_contest_callback\([^)]*\).*?(?=\n\nasync def admin_declare_winner_callback|\Z)'
pattern_declare = r'async def admin_declare_winner_callback\([^)]*\).*?(?=\n\nasync def |\Z)'

content = re.sub(pattern_create, new_create.strip(), content, flags=re.DOTALL)
content = re.sub(pattern_declare, new_declare.strip(), content, flags=re.DOTALL)

# حفظ الملف
with open('reelax_bot.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ تم تعديل الدوال بنجاح!")
