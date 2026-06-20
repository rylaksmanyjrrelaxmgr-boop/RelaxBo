#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ===== التوكن =====
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN not set")

logging.basicConfig(level=logging.INFO)

# ===== معالج الأخطاء =====
async def global_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"خطأ: {context.error}")

# ===== أوامر البوت =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📢 مثال", callback_data="example")]]
    await update.message.reply_text("البوت يعمل ✅", reply_markup=InlineKeyboardMarkup(keyboard))

async def example(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("تم الضغط ✅")

# ===== التشغيل =====
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(global_error_handler)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(example, pattern="example"))
    print("🚀 البوت يعمل...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
