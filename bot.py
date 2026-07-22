#!/usr/bin/env python3
import os, sys, asyncio, logging
os.environ['PTB_DISABLE_SIGNAL_HANDLER'] = 'true'
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
TOKEN = os.getenv("BOT_TOKEN", "8232359959:AAHj72T_0c-O5k8hbsioQl5jwu9C5TzigXg")
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ البوت يعمل! أهلاً بك.")
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🔁 {update.message.text}")
async def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    await app.run_polling(drop_pending_updates=True, close_loop=False, stop_signals=None)
if __name__ == "__main__":
    asyncio.run(main())
