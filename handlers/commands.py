from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from core.db_queries import *
from core.translation import get_text, user_language
from handlers.callbacks import main_menu_callback

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db_register_user(user.id)
    await main_menu_callback(update, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(get_text(user_id, "help"), parse_mode="MarkdownV2")

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("العربية 🇸🇦", callback_data="lang_ar"), InlineKeyboardButton("English 🇬🇧", callback_data="lang_en")],
    ])
    await update.message.reply_text(get_text(user_id, "welcome"), reply_markup=keyboard)

async def trial_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await db_activate_subscription(user_id, 30)
    await update.message.reply_text("🎁 تم تفعيل التجربة المجانية لمدة 30 يوم!")

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data="buy:1:5")],
        [InlineKeyboardButton("⭐ 30 يوم - 50 نجمة", callback_data="buy:30:50")],
    ])
    await update.message.reply_text("💎 اختر الباقة:", reply_markup=keyboard)

async def syncgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    chat_name = update.effective_chat.title
    user_id = update.effective_user.id
    await db_register_group(chat_id, chat_name, user_id)
    await update.message.reply_text(f"✅ تم تفعيل المجموعة: {chat_name}")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("📊 إحصائيات القناة قيد التطوير")

async def rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    level = await db_get_user_level(user_id)
    await update.message.reply_text(f"📊 **رتبتك:** المستوى {level['level']}\nنقاط: {level['points']}", parse_mode="MarkdownV2")

async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏆 أفضل 10 قيد التطوير")

async def developer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👨‍💻 المطور: @RelaxMgr\n📦 الإصدار: 19.0.8")

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📞 للدعم: تواصل مع @RelaxMgr")

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ يعمل فقط في المجموعات!")
        return
    await update.message.reply_text("🔒 تم قفل المجموعة")

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔓 تم فتح المجموعة")

async def moderation_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛠️ أمر إدارة قيد التطوير")
