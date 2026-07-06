from telegram import Update
from telegram.ext import ContextTypes

async def moderation_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛠️ أمر إدارة قيد التطوير")

async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass

async def track_chat_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass

async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass
