from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8232359959:AAHkrv7oHns4iteuHPJM8X-rxi5JMlyNX9I"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ البوت يعمل!")

app = Application.builder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
print("🚀 يعمل...")
app.run_polling()
