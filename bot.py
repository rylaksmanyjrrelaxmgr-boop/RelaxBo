#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
os.environ['PTB_DISABLE_SIGNAL_HANDLER'] = 'true'

import asyncio, sys, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from constants import (
    TOKEN, PRIMARY_OWNER_ID, BOT_NAME, BOT_USERNAME,
    USE_PROXY, PROXY_URL, MAX_CONNECTIONS,
    POLL_INTERVAL, WEB_HOST, WEB_PORT,
    BATTERY_SAVER_MODE, LOG_PATH, ERROR_LOG,
    get_nsfw_lock
)
from utils import (
    advanced_logger, log_error, memory_optimizer,
    check_single_instance, logger
)
from database import db, init_db_improved
from security import import_banned_words_on_startup
from handlers import *
from tasks import BackgroundTaskManager
from web import start_web_server

from telegram import BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, PreCheckoutQueryHandler, ChatMemberHandler
)
from telegram.request import HTTPXRequest

async def private_message_router(update, context):
    try:
        if context.user_data.get("creating_contest"):
            return await handle_contest_creation_states(update, context)
    except: pass
    return await message_handler_main(update, context)

async def main():
    await init_db_improved()
    await import_banned_words_on_startup()
    get_nsfw_lock()

    if USE_PROXY:
        request = HTTPXRequest(proxy_url=PROXY_URL, read_timeout=60.0, write_timeout=30.0, connect_timeout=30.0, pool_timeout=10.0, connection_pool_size=MAX_CONNECTIONS)
    else:
        request = HTTPXRequest(read_timeout=60.0, write_timeout=30.0, connect_timeout=30.0, pool_timeout=10.0, connection_pool_size=MAX_CONNECTIONS)

    application = Application.builder().token(TOKEN).request(request).build()
    application.add_error_handler(global_error_handler)

    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("help", help_command_handler))
    application.add_handler(CommandHandler("panel", panel_command_handler))
    application.add_handler(CommandHandler("stats", stats_command_handler))
    application.add_handler(CommandHandler("contests", contests_command_handler))

    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))

    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, private_message_router))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))

    await application.bot.set_my_commands([BotCommand("start", "بدء البوت"), BotCommand("help", "المساعدة")])

    task_manager = BackgroundTaskManager(application.bot)
    await task_manager.start_all()
    asyncio.create_task(start_web_server())

    print(f"🚀 تم تشغيل {BOT_NAME} (الإصدار 19.3.3)")
    await application.run_polling(drop_pending_updates=True, poll_interval=POLL_INTERVAL)
    await task_manager.stop_all()
    await db.close()

if __name__ == "__main__":
    try:
        lock_socket = check_single_instance()
        if lock_socket is False:
            print("❌ البوت يعمل بالفعل!"); sys.exit(1)
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 تم إيقاف البوت")
    except Exception as e:
        print(f"❌ خطأ فادح: {e}")
        traceback.print_exc()
        sys.exit(1)
