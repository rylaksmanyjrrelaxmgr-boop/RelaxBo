from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from core.db_queries import *
from core.translation import get_text, user_language
from utils.keyboard import get_main_keyboard

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.callback_query:
        query = update.callback_query
        await query.answer()
    else:
        query = None
    
    keyboard, title = await get_main_keyboard(user_id)
    if query:
        await query.edit_message_text(title, reply_markup=keyboard, parse_mode="MarkdownV2")
    else:
        await update.message.reply_text(title, reply_markup=keyboard, parse_mode="MarkdownV2")

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu_callback(update, context)

async def lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = query.data.split("_")[1]
    await db_set_user_language(user_id, lang)
    user_language[user_id] = lang
    await query.edit_message_text(f"✅ تم تغيير اللغة")
    await main_menu_callback(update, context)

async def add_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data["state"] = "WAITING_CHANNEL_ID"
    await query.edit_message_text("📡 أرسل معرف القناة (مثال: @channel أو -100123456)")

async def my_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    channels = await db_get_channels(user_id)
    if not channels:
        await query.edit_message_text("📭 لا توجد قنوات")
        return
    keyboard = []
    for ch in channels:
        ch_id, ch_tele, ch_name, banned = ch
        keyboard.append([InlineKeyboardButton(f"📢 {ch_name}", callback_data=f"channels:select:{ch_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back")])
    await query.edit_message_text("📡 **قنواتي**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")

async def add_15_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    active = await db_get_active_channel(user_id)
    if not active:
        await query.edit_message_text("⚠️ اختر قناة أولاً")
        return
    context.user_data["state"] = "ADDING_POSTS"
    context.user_data["session_posts"] = []
    await query.edit_message_text("📥 أرسل المنشورات (نصوص أو صور أو فيديوهات)\nلإنهاء الإرسال أرسل /cancel")

async def publish_one_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    active = await db_get_active_channel(user_id)
    if not active:
        await query.edit_message_text("⚠️ اختر قناة أولاً")
        return
    post = await db_get_next_post(active)
    if not post:
        await query.edit_message_text("📭 لا توجد منشورات")
        return
    await query.edit_message_text("✅ تم النشر")

async def my_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📋 منشوراتي قيد التطوير")

async def recycle_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    active = await db_get_active_channel(user_id)
    if active:
        await db_reset_posts_to_unpublished(active)
        await query.edit_message_text("♻️ تم إعادة تدوير المنشورات")
    else:
        await query.edit_message_text("⚠️ اختر قناة أولاً")

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    auto = await db_auto_status(user_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'✅' if auto else '❌'} النشر التلقائي", callback_data="settings:toggle_auto")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await query.edit_message_text("⚙️ **الإعدادات**", reply_markup=keyboard, parse_mode="MarkdownV2")

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != MAIN_ADMIN_ID:
        await query.edit_message_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 المستخدمين", callback_data="admin:users")],
        [InlineKeyboardButton("📡 القنوات", callback_data="admin:channels")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back")]
    ])
    await query.edit_message_text("👑 **لوحة الأدمن**", reply_markup=keyboard, parse_mode="MarkdownV2")
