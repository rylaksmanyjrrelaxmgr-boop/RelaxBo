#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
os.environ['PTB_DISABLE_SIGNAL_HANDLER'] = 'true'

import asyncio
import sys
import traceback
from pathlib import Path

# إضافة المسار الحالي
sys.path.insert(0, str(Path(__file__).parent))

# استيراد المكونات الأساسية فقط
from constants import TOKEN, BOT_NAME
from utils import check_single_instance

# استيراد مكتبة تيليجرام
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# ===================== معالجات مدمجة مباشرة =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج أمر /start"""
    user = update.effective_user
    await update.message.reply_text(
        f"🌿 **{BOT_NAME}**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 المعرف: `{user.id}`\n\n"
        f"مرحباً بك! البوت يعمل بنجاح ✅",
        parse_mode="MarkdownV2"
    )

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الرسائل النصية"""
    text = update.message.text
    await update.message.reply_text(f"📩 استلمت: {text}")

# ===================== الدالة الرئيسية =====================
async def main():
    """تشغيل البوت"""
    # بناء التطبيق
    application = Application.builder().token(TOKEN).build()

    # تسجيل المعالجات الأساسية
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # حذف أي webhook سابق
    bot = Bot(token=TOKEN)
    await bot.delete_webhook(drop_pending_updates=True)

    print(f"🚀 تم تشغيل {BOT_NAME}")
    print("📡 البوت جاهز لاستقبال الرسائل...")

    # بدء البوت
    await application.run_polling(drop_pending_updates=True)

# ===================== نقطة الدخول =====================
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 تم إيقاف البوت")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        traceback.print_exc()
        sys.exit(1)
