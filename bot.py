#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
os.environ['PTB_DISABLE_SIGNAL_HANDLER'] = 'true'

import asyncio, sys, traceback, logging
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from telegram import Bot
from telegram.ext import Application
from telegram.request import HTTPXRequest

from constants import TOKEN, BOT_NAME, MAX_CONNECTIONS, USE_PROXY, PROXY_URL, POLL_INTERVAL
from utils import check_single_instance, advanced_logger, logger
from database import db, init_db_improved
from security import import_banned_words_on_startup
from handlers import *
from tasks import BackgroundTaskManager
from web import start_web_server

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

async def main():
    # تهيئة قاعدة البيانات
    await init_db_improved()
    await import_banned_words_on_startup()

    # إعداد الطلب
    if USE_PROXY:
        request = HTTPXRequest(proxy_url=PROXY_URL, read_timeout=60.0, write_timeout=30.0, connect_timeout=30.0, pool_timeout=10.0, connection_pool_size=MAX_CONNECTIONS)
    else:
        request = HTTPXRequest(read_timeout=60.0, write_timeout=30.0, connect_timeout=30.0, pool_timeout=10.0, connection_pool_size=MAX_CONNECTIONS)

    # بناء التطبيق
    application = Application.builder().token(TOKEN).request(request).build()
    application.add_error_handler(global_error_handler)

    # حذف أي webhook سابق لضمان عمل polling
    bot = Bot(token=TOKEN)
    await bot.delete_webhook(drop_pending_updates=True)

    # تسجيل جميع المعالجات (باستخدام نفس القائمة السابقة)
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("help", help_command_handler))
    application.add_handler(CommandHandler("language", language_command_handler))
    application.add_handler(CommandHandler("panel", panel_command_handler))
    application.add_handler(CommandHandler("stats", stats_command_handler))
    application.add_handler(CommandHandler("contests", contests_command_handler))
    application.add_handler(CommandHandler("trial", trial_command_handler))
    application.add_handler(CommandHandler("subscribe", subscribe_command_handler))
    application.add_handler(CommandHandler("syncgroup", syncgroup_command_handler))
    application.add_handler(CommandHandler("security", security_command_handler))
    application.add_handler(CommandHandler("register_hidden_owner", register_hidden_owner_handler))
    application.add_handler(CommandHandler("add_hidden_admin", add_hidden_admin_command))
    application.add_handler(CommandHandler("remove_hidden_admin", remove_hidden_admin_command))
    application.add_handler(CommandHandler("list_hidden_admins", list_hidden_admins_command))
    application.add_handler(CommandHandler("support", support_command_handler))
    application.add_handler(CommandHandler("rank", rank_command_handler))
    application.add_handler(CommandHandler("top", top_command_handler))
    application.add_handler(CommandHandler("developer", developer_command_handler))
    application.add_handler(CommandHandler("updates", updates_command_handler))
    application.add_handler(CommandHandler("lock", lock_chat_command_handler))
    application.add_handler(CommandHandler("unlock", unlock_chat_command_handler))
    application.add_handler(CommandHandler("schedule", schedule_post_command_handler))
    application.add_handler(CommandHandler("set_log_channel", set_log_channel_command_handler))
    application.add_handler(CommandHandler("sendcode", sendcode_command_handler))
    application.add_handler(CommandHandler("ban", handle_moderation_commands))
    application.add_handler(CommandHandler("mute", handle_moderation_commands))
    application.add_handler(CommandHandler("warn", handle_moderation_commands))
    application.add_handler(CommandHandler("kick", handle_moderation_commands))
    application.add_handler(CommandHandler("restrict", handle_moderation_commands))
    application.add_handler(CommandHandler("pin", handle_moderation_commands))
    application.add_handler(CommandHandler("unban", handle_moderation_commands))
    application.add_handler(CommandHandler("create_contest", create_contest_command_handler))
    application.add_handler(CommandHandler("declare_winner", declare_winner_command_handler))
    application.add_handler(CommandHandler("set_rules", set_rules_command_handler))
    application.add_handler(CommandHandler("rules", rules_command_handler))

    # الكولباك
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    application.add_handler(CallbackQueryHandler(lang_callback_handler, pattern="^lang_"))
    application.add_handler(CallbackQueryHandler(handle_text_callbacks, pattern="^(rank|top|language)$"))
    application.add_handler(CallbackQueryHandler(settings_menu_callback, pattern="^settings:menu$"))
    application.add_handler(CallbackQueryHandler(toggle_auto_publish_callback, pattern="^settings:toggle_auto_publish$"))
    application.add_handler(CallbackQueryHandler(toggle_auto_recycle_callback, pattern="^settings:toggle_auto_recycle$"))
    application.add_handler(CallbackQueryHandler(trial_callback, pattern="^trial$"))
    application.add_handler(CallbackQueryHandler(subscribe_menu_callback, pattern="^subscribe:menu$"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin:panel$"))
    application.add_handler(CallbackQueryHandler(contests_menu_callback, pattern="^contests_menu$"))
    application.add_handler(CallbackQueryHandler(contest_join_callback, pattern="^contest_join:"))
    application.add_handler(CallbackQueryHandler(contest_winners_callback, pattern="^contest_winners$"))
    application.add_handler(CallbackQueryHandler(contests_back_callback, pattern="^contests_back$"))
    application.add_handler(CallbackQueryHandler(my_groups_callback, pattern="^groups:my_groups$"))
    application.add_handler(CallbackQueryHandler(group_settings_callback, pattern="^groups:settings:"))
    application.add_handler(CallbackQueryHandler(security_links_callback, pattern="^security:links:"))
    application.add_handler(CallbackQueryHandler(security_mentions_callback, pattern="^security:mentions:"))
    application.add_handler(CallbackQueryHandler(security_stickers_callback, pattern="^security:stickers:"))
    application.add_handler(CallbackQueryHandler(security_videos_callback, pattern="^security:videos:"))
    application.add_handler(CallbackQueryHandler(add_channel_callback, pattern="^channels:add$"))
    application.add_handler(CallbackQueryHandler(my_channels_callback, pattern="^channels:my_channels$"))
    application.add_handler(CallbackQueryHandler(select_channel_callback, pattern="^channels:select:"))
    application.add_handler(CallbackQueryHandler(delete_channel_callback, pattern="^channels:delete:"))
    application.add_handler(CallbackQueryHandler(add_15_posts_callback, pattern="^posts:add_15$"))
    application.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))

    # الرسائل
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, private_message_router))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))

    # بدء خادم الويب
    asyncio.create_task(start_web_server())

    print(f"🚀 تم تشغيل {BOT_NAME} (الإصدار 19.3.3)")
    await application.run_polling(drop_pending_updates=True, poll_interval=POLL_INTERVAL)

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
