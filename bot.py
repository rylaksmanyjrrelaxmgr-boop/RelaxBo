#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio, os, sys, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from constants import (
    TOKEN, PRIMARY_OWNER_ID, BOT_NAME, BOT_USERNAME,
    USE_PROXY, PROXY_URL, MAX_CONNECTIONS,
    POLL_INTERVAL, WEB_HOST, WEB_PORT,
    BATTERY_SAVER_MODE, LOG_PATH, ERROR_LOG,
    get_nsfw_lock
)
from utils import advanced_logger, log_error, check_single_instance
from database import db, init_db_improved
from security import import_banned_words_on_startup
from handlers import *
from tasks import BackgroundTaskManager
from web import start_web_server

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, PreCheckoutQueryHandler, ChatMemberHandler
from telegram.request import HTTPXRequest
from telegram import BotCommand

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

    # الأوامر الأساسية
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("help", help_command_handler))
    application.add_handler(CommandHandler("language", language_command_handler))
    application.add_handler(CommandHandler("trial", trial_command_handler))
    application.add_handler(CommandHandler("subscribe", subscribe_command_handler))
    application.add_handler(CommandHandler("panel", panel_command_handler))
    application.add_handler(CommandHandler("security", security_command_handler))
    application.add_handler(CommandHandler("stats", stats_command_handler))
    application.add_handler(CommandHandler("lock", lock_chat_command_handler))
    application.add_handler(CommandHandler("unlock", unlock_chat_command_handler))
    application.add_handler(CommandHandler("schedule", schedule_post_command_handler))
    application.add_handler(CommandHandler("syncgroup", syncgroup_command_handler))
    application.add_handler(CommandHandler("support", support_command_handler))
    application.add_handler(CommandHandler("rank", rank_command_handler))
    application.add_handler(CommandHandler("top", top_command_handler))
    application.add_handler(CommandHandler("developer", developer_command_handler))
    application.add_handler(CommandHandler("updates", updates_command_handler))
    application.add_handler(CommandHandler("set_log_channel", set_log_channel_command_handler))
    application.add_handler(CommandHandler("sendcode", sendcode_command_handler))
    application.add_handler(CommandHandler("ban", handle_moderation_commands))
    application.add_handler(CommandHandler("mute", handle_moderation_commands))
    application.add_handler(CommandHandler("warn", handle_moderation_commands))
    application.add_handler(CommandHandler("kick", handle_moderation_commands))
    application.add_handler(CommandHandler("restrict", handle_moderation_commands))
    application.add_handler(CommandHandler("pin", handle_moderation_commands))
    application.add_handler(CommandHandler("unban", handle_moderation_commands))
    application.add_handler(CommandHandler("contests", contests_command_handler))
    application.add_handler(CommandHandler("create_contest", create_contest_command_handler))
    application.add_handler(CommandHandler("declare_winner", declare_winner_command_handler))
    application.add_handler(CommandHandler("set_rules", set_rules_command_handler))
    application.add_handler(CommandHandler("rules", rules_command_handler))
    application.add_handler(CommandHandler("register_hidden_owner", register_hidden_owner_handler))
    application.add_handler(CommandHandler("add_hidden_admin", add_hidden_admin_command))
    application.add_handler(CommandHandler("remove_hidden_admin", remove_hidden_admin_command))
    application.add_handler(CommandHandler("list_hidden_admins", list_hidden_admins_command))

    # الكولباك
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    application.add_handler(CallbackQueryHandler(settings_menu_callback, pattern="^settings:menu$"))
    application.add_handler(CallbackQueryHandler(trial_callback, pattern="^trial$"))
    application.add_handler(CallbackQueryHandler(subscribe_menu_callback, pattern="^subscribe:menu$"))
    application.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    application.add_handler(CallbackQueryHandler(lang_callback_handler, pattern="^lang_"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin:panel$"))
    application.add_handler(CallbackQueryHandler(contests_menu_callback, pattern="^contests_menu$"))

    # الرسائل
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, private_message_router))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))

    await application.bot.set_my_commands([BotCommand("start", "بدء البوت"), BotCommand("help", "المساعدة"), BotCommand("panel", "لوحة التحكم"), BotCommand("stats", "إحصائيات"), BotCommand("contests", "المسابقات")])

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
            print("❌ البوت يعمل بالفعل!")
            sys.exit(1)
        os.environ["WEB_CONCURRENCY"] = "1"
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 تم إيقاف البوت")
    except Exception as e:
        print(f"❌ خطأ فادح: {e}")
        traceback.print_exc()
        sys.exit(1)
