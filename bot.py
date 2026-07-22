#!/usr/bin/env python3
import os, sys, asyncio, traceback, logging
from pathlib import Path

# تفعيل التوافق مع Render
os.environ['PTB_DISABLE_SIGNAL_HANDLER'] = 'true'

sys.path.insert(0, str(Path(__file__).parent))

from constants import TOKEN, BOT_NAME, WEB_HOST, WEB_PORT
from utils import check_single_instance, advanced_logger
from web import start_web_server

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from handlers import (
    start_command_handler, help_command_handler, language_command_handler,
    panel_command_handler, stats_command_handler, contests_command_handler,
    trial_command_handler, subscribe_command_handler, syncgroup_command_handler,
    security_command_handler, register_hidden_owner_handler, add_hidden_admin_command,
    remove_hidden_admin_command, list_hidden_admins_command, support_command_handler,
    rank_command_handler, top_command_handler, developer_command_handler,
    updates_command_handler, lock_chat_command_handler, unlock_chat_command_handler,
    schedule_post_command_handler, set_log_channel_command_handler,
    sendcode_command_handler, handle_moderation_commands, create_contest_command_handler,
    declare_winner_command_handler, set_rules_command_handler, rules_command_handler,
    main_menu_callback, back_callback, lang_callback_handler, handle_text_callbacks,
    settings_menu_callback, toggle_auto_publish_callback, toggle_auto_recycle_callback,
    trial_callback, subscribe_menu_callback, admin_panel_callback,
    contests_menu_callback, contest_join_callback, contest_winners_callback,
    contests_back_callback, my_groups_callback, group_settings_callback,
    security_links_callback, security_mentions_callback, security_stickers_callback,
    security_videos_callback, add_channel_callback, my_channels_callback,
    select_channel_callback, delete_channel_callback, add_15_posts_callback,
    help_callback, private_message_router, filter_messages_handler, global_error_handler
)

async def main():
    application = Application.builder().token(TOKEN).build()
    application.add_error_handler(global_error_handler)

    # تسجيل جميع المعالجات الضرورية
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
    for cmd in ["ban","mute","warn","kick","restrict","pin","unban"]:
        application.add_handler(CommandHandler(cmd, handle_moderation_commands))
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

    # تشغيل خادم الويب في الخلفية
    asyncio.create_task(start_web_server())

    print(f"🚀 تم تشغيل {BOT_NAME}")
    await application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        print(f"❌ خطأ: {e}")
        traceback.print_exc()
        sys.exit(1)
