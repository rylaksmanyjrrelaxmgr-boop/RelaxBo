import asyncio, logging
from aiohttp import web
from telegram import BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from config import TOKEN, PORT, BOT_NAME
from database import init_db
from handlers import (
    load_lang, load_banned_cache, auto_register, start, claim, addowner, addadmin, remove, listall,
    cmd_lock_links, cmd_unlock_links, cmd_lock_mentions, cmd_unlock_mentions,
    cmd_slowmode, cmd_welcome, cmd_goodbye,
    button_handler, msg_handler, group_msg
)
from tasks import auto_publish, reminder_loop, scheduler_loop

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def health(request):
    return web.json_response({"status":"ok","bot":BOT_NAME})

async def main():
    await init_db()
    await load_lang()
    await load_banned_cache()
    app = Application.builder().token(TOKEN).build()
    try:
        await app.bot.get_me()
        logger.info("✅ توكن صحيح")
    except Exception as e:
        logger.error(f"❌ توكن غير صالح: {e}")
        return
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, auto_register), group=1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("claim", claim))
    app.add_handler(CommandHandler("addowner", addowner))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("remove", remove))
    app.add_handler(CommandHandler("list", listall))
    app.add_handler(CommandHandler("lock_links", cmd_lock_links))
    app.add_handler(CommandHandler("unlock_links", cmd_unlock_links))
    app.add_handler(CommandHandler("lock_mentions", cmd_lock_mentions))
    app.add_handler(CommandHandler("unlock_mentions", cmd_unlock_mentions))
    app.add_handler(CommandHandler("slowmode", cmd_slowmode))
    app.add_handler(CommandHandler("welcome", cmd_welcome))
    app.add_handler(CommandHandler("goodbye", cmd_goodbye))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, group_msg))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, msg_handler))
    
    await app.bot.set_my_commands([
        BotCommand("start","بدء"), BotCommand("claim","مالك مخفي"),
        BotCommand("addowner","+مالك"), BotCommand("addadmin","+مشرف"),
        BotCommand("remove","إزالة"), BotCommand("list","عرض"),
        BotCommand("lock_links","حظر الروابط"), BotCommand("unlock_links","إلغاء حظر الروابط"),
        BotCommand("lock_mentions","حظر الإشارات"), BotCommand("unlock_mentions","إلغاء حظر الإشارات"),
        BotCommand("slowmode","وضع بطيء"), BotCommand("welcome","رسالة ترحيب"),
        BotCommand("goodbye","رسالة وداع"), BotCommand("help","مساعدة")
    ])
    
    # واجهة الويب
    web_app = web.Application()
    web_app.router.add_get("/", health)
    web_app.router.add_get("/health", health)
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    
    asyncio.create_task(auto_publish(app))
    asyncio.create_task(reminder_loop(app))
    asyncio.create_task(scheduler_loop(app))
    logger.info(f"✅ {BOT_NAME} شغال على المنفذ {PORT}")
    await app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
