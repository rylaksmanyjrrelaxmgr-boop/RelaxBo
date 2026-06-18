#!/usr/bin/env python3
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import nest_asyncio
nest_asyncio.apply()

TOKEN = "8806390759:AAHDDBoveEyMhgLNjDKQK5FHfvH5WbfKN9I"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ البوت يعمل بنجاح!")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
