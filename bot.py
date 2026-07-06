import asyncio
import logging
from aiohttp import web
from telegram import BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import TOKEN, PORT, BOT_NAME
from database import init_db
from handlers import *
from tasks import auto_publish, reminder_loop, scheduler_loop

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def health(request):
    return web.json_response({"status": "ok", "bot": BOT_NAME})

async def web_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"✅ خادم الويب يعمل على المنفذ {PORT}")

async def main():
    logger.info(f"🚀 {BOT_NAME} جاري التشغيل...")

    # تهيئة قاعدة البيانات والذاكرة
    await init_db()
    await load_lang()
    await load_banned_cache()

    # بناء تطبيق البوت
    app = Application.builder().token(TOKEN).build()

    # التحقق من التوكن
    try:
        await app.bot.get_me()
        logger.info("✅ توكن صحيح")
    except Exception as e:
        logger.error(f"❌ توكن غير صالح: {e}")
        return

    # ===== التسجيل التلقائي =====
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, auto_register), group=1)

    # ===== أوامر الصلاحيات =====
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("claim", claim))
    app.add_handler(CommandHandler("addowner", addowner))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", listall))

    # ===== أوامر الحماية =====
    app.add_handler(CommandHandler("lock_links", cmd_lock_links))
    app.add_handler(CommandHandler("unlock_links", cmd_unlock_links))
    app.add_handler(CommandHandler("lock_mentions", cmd_lock_mentions))
    app.add_handler(CommandHandler("unlock_mentions", cmd_unlock_mentions))
    app.add_handler(CommandHandler("slowmode", cmd_slowmode))
    app.add_handler(CommandHandler("welcome", cmd_welcome))
    app.add_handler(CommandHandler("goodbye", cmd_goodbye))

    # ===== أوامر إضافية =====
    app.add_handler(CommandHandler("rank", rank_command))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("contests", contests_command))
    app.add_handler(CommandHandler("declare_winner", declare_winner_command))
    app.add_handler(CommandHandler("referral", referral_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("translate", translate_command))
    app.add_handler(CommandHandler("schedule", schedule_post))
    app.add_handler(CommandHandler("modlog", modlog_command))
    app.add_handler(CommandHandler("search", search_users_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("export", export_command))

    # ===== أزرار =====
    app.add_handler(CallbackQueryHandler(button_handler))

    # ===== رسائل =====
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, group_msg))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, msg_handler))

    # ===== قائمة الأوامر =====
    await app.bot.set_my_commands([
        BotCommand("start", "بدء"),
        BotCommand("claim", "مالك مخفي"),
        BotCommand("addowner", "+مالك"),
        BotCommand("addadmin", "+مشرف"),
        BotCommand("remove", "إزالة"),
        BotCommand("list", "عرض"),
        BotCommand("lock_links", "حظر الروابط"),
        BotCommand("unlock_links", "إلغاء حظر الروابط"),
        BotCommand("lock_mentions", "حظر الإشارات"),
        BotCommand("unlock_mentions", "إلغاء حظر الإشارات"),
        BotCommand("slowmode", "وضع بطيء"),
        BotCommand("welcome", "ترحيب"),
        BotCommand("goodbye", "وداع"),
        BotCommand("rank", "رتبتي"),
        BotCommand("top", "أفضل 10"),
        BotCommand("contests", "مسابقات"),
        BotCommand("referral", "إحالات"),
        BotCommand("reminders", "تذكيرات"),
        BotCommand("translate", "ترجمة"),
        BotCommand("schedule", "جدولة منشور"),
        BotCommand("modlog", "سجل الإجراءات"),
        BotCommand("help", "مساعدة"),
    ])

    # ===== تشغيل المهام الخلفية =====
    asyncio.create_task(auto_publish(app))
    asyncio.create_task(reminder_loop(app))
    asyncio.create_task(scheduler_loop(app))
    asyncio.create_task(web_server())

    # ===== تشغيل البوت =====
    logger.info(f"✅ {BOT_NAME} يعمل الآن!")
    await app.run_polling(drop_pending_updates=True)
