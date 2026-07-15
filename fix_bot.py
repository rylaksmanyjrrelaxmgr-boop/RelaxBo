import re
import sys

def fix_bot():
    print("📝 جاري إصلاح bot.py...")
    
    with open('bot.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # ===== إزالة if USE_PROXY و else =====
    content = re.sub(r'    if USE_PROXY:.*?else:\n', '', content, flags=re.DOTALL)
    
    # ===== إصلاح المسافات في main() =====
    content = re.sub(r'^        request_kwargs = \{', '    request_kwargs = {', content, flags=re.MULTILINE)
    content = re.sub(r"^            'read_timeout': 60.0,", "        'read_timeout': 60.0,", content, flags=re.MULTILINE)
    content = re.sub(r"^            'write_timeout': 30.0,", "        'write_timeout': 30.0,", content, flags=re.MULTILINE)
    content = re.sub(r"^            'connect_timeout': 30.0,", "        'connect_timeout': 30.0,", content, flags=re.MULTILINE)
    content = re.sub(r"^            'pool_timeout': 10.0,", "        'pool_timeout': 10.0,", content, flags=re.MULTILINE)
    content = re.sub(r'^        \}', '    }', content, flags=re.MULTILINE)
    content = re.sub(r'^        request = HTTPXRequest', '    request = HTTPXRequest', content, flags=re.MULTILINE)
    content = re.sub(r'^        application = Application', '    application = Application', content, flags=re.MULTILINE)
    
    # ===== الدوال المفقودة =====
    missing_functions = '''

# ===================== الدوال المفقودة =====================

async def admin_confirm_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأكيد الإرسال الجماعي"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        return
    
    broadcast_text = context.user_data.get("broadcast_text")
    if not broadcast_text:
        await query.edit_message_text("❌ لا يوجد نص للإرسال.")
        return
    
    await query.edit_message_text("📨 جاري الإرسال إلى جميع المستخدمين...")
    
    users = await db_get_all_users()
    success_count = 0
    fail_count = 0
    
    for user in users:
        uid = user[0]
        if user[1] == 1:
            continue
        try:
            await context.bot.send_message(chat_id=uid, text=broadcast_text)
            success_count += 1
            await asyncio.sleep(0.1)
        except:
            fail_count += 1
    
    context.user_data.pop("broadcast_text", None)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, "back"), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await query.edit_message_text(
        f"✅ **تم الإرسال الجماعي!**\\n\\n"
        f"✅ نجح: {success_count}\\n"
        f"❌ فشل: {fail_count}",
        reply_markup=keyboard
    )


async def admin_delete_all_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف جميع تذاكر الدعم"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، احذف الكل", callback_data=CallbackData.ADMIN_CONFIRM_DELETE_TICKETS),
         InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await query.edit_message_text(
        get_text(user_id, "confirm_delete_tickets"),
        reply_markup=keyboard
    )


async def admin_confirm_delete_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تأكيد حذف جميع تذاكر الدعم"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        return
    
    async def _delete_all_tickets(conn):
        await conn.execute("DELETE FROM support_tickets")
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM support_tickets")
        count = (await cur.fetchone())[0]
        return count
    
    count = await execute_db(_delete_all_tickets)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, "back"), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await query.edit_message_text(
        get_text(user_id, "tickets_deleted").format(count),
        reply_markup=keyboard
    )


async def db_get_auto_recycle(user_id: int) -> bool:
    """الحصول على حالة إعادة التدوير التلقائي"""
    async def _get(conn):
        cur = await conn.execute("SELECT auto_recycle FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_get)


async def admin_banned_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض القنوات المحظورة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        return
    
    async def _get_banned_channels(conn):
        cur = await conn.execute("SELECT id, channel_id, channel_name FROM user_channels WHERE banned=1")
        return await cur.fetchall()
    
    channels = await execute_db(_get_banned_channels)
    
    if not channels:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(user_id, "back"), callback_data=CallbackData.ADMIN_PANEL)]
        ])
        await query.edit_message_text("📭 لا توجد قنوات محظورة.", reply_markup=keyboard)
        return
    
    text = "⛔ **القنوات المحظورة**\\n━━━━━━━━━━━━━━━━━━━━━━\\n"
    for ch_id, ch_tele, ch_name in channels:
        text += f"• {ch_name or ch_tele} (`{ch_tele}`)\\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS)],
        [InlineKeyboardButton(get_text(user_id, "back"), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await safe_edit_markdown(query, text, reply_markup=keyboard)


async def admin_activate_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تفعيل جميع القنوات المحظورة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        return
    
    async def _activate_all(conn):
        await conn.execute("UPDATE user_channels SET banned=0 WHERE banned=1")
        await conn.commit()
    
    await execute_db(_activate_all)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, "back"), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await query.edit_message_text("✅ تم تفعيل جميع القنوات.", reply_markup=keyboard)


async def admin_banned_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض المجموعات المحظورة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        return
    
    async def _get_banned_groups(conn):
        cur = await conn.execute("SELECT chat_id, chat_name FROM bot_groups WHERE banned=1")
        return await cur.fetchall()
    
    groups = await execute_db(_get_banned_groups)
    
    if not groups:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(user_id, "back"), callback_data=CallbackData.ADMIN_PANEL)]
        ])
        await query.edit_message_text("📭 لا توجد مجموعات محظورة.", reply_markup=keyboard)
        return
    
    text = "⛔ **المجموعات المحظورة**\\n━━━━━━━━━━━━━━━━━━━━━━\\n"
    for gid, gname in groups:
        text += f"• {gname} (`{gid}`)\\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_GROUPS)],
        [InlineKeyboardButton(get_text(user_id, "back"), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await safe_edit_markdown(query, text, reply_markup=keyboard)


async def admin_unban_all_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء حظر جميع المجموعات"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        return
    
    async def _unban_all(conn):
        await conn.execute("UPDATE bot_groups SET banned=0 WHERE banned=1")
        await conn.commit()
    
    await execute_db(_unban_all)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, "back"), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await query.edit_message_text("✅ تم إلغاء حظر جميع المجموعات.", reply_markup=keyboard)


async def admin_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إدارة الكلمات المحظورة العامة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة محظورة", callback_data=CallbackData.ADMIN_ADD_BANNED_WORD)],
        [InlineKeyboardButton("📋 عرض الكلمات المحظورة", callback_data=CallbackData.ADMIN_LIST_BANNED_WORDS)],
        [InlineKeyboardButton("🗑️ حذف كلمة محظورة", callback_data=CallbackData.ADMIN_REMOVE_BANNED_WORD)],
        [InlineKeyboardButton(get_text(user_id, "back"), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    
    await query.edit_message_text("🚫 **إدارة الكلمات المحظورة العامة**", reply_markup=keyboard)


async def admin_add_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إضافة كلمة محظورة عامة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        return
    
    context.user_data['state'] = UserState.WAITING_GLOBAL_BANNED_WORD
    await query.edit_message_text("➕ أرسل الكلمة التي تريد إضافتها ككلمة محظورة عامة:")


async def admin_list_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض الكلمات المحظورة العامة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        return
    
    words = await db_get_banned_words(-1)
    
    if not words:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(user_id, "back"), callback_data=CallbackData.ADMIN_BANNED_WORDS)]
        ])
        await query.edit_message_text("📭 لا توجد كلمات محظورة عامة.", reply_markup=keyboard)
        return
    
    text = "🚫 **الكلمات المحظورة العامة**\\n━━━━━━━━━━━━━━━━━━━━━━\\n"
    for word, added_by, added_at in words:
        text += f"• `{word}` (أضيف بواسطة {added_by})\\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, "back"), callback_data=CallbackData.ADMIN_BANNED_WORDS)]
    ])
    
    await safe_edit_markdown(query, text, reply_markup=keyboard)


async def admin_remove_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف كلمة محظورة عامة"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, "admin_only"), show_alert=True)
        return
    
    context.user_data['state'] = UserState.WAITING_REMOVE_GLOBAL_BANNED_WORD
    await query.edit_message_text("🗑️ أرسل الكلمة التي تريد حذفها من الكلمات المحظورة العامة:")

'''

    # ===== أضف الدوال المفقودة قبل نهاية الملف =====
    if 'if __name__ == "__main__":' in content:
        content = content.replace('if __name__ == "__main__":', missing_functions + '\nif __name__ == "__main__":')
    else:
        content += missing_functions
    
    with open('bot.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ تم إصلاح bot.py بنجاح!")

if __name__ == "__main__":
    fix_bot()
