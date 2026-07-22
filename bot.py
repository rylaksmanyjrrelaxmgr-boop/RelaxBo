#!/usr/bin/env python3
import os, sys, asyncio, traceback
os.environ['PTB_DISABLE_SIGNAL_HANDLER'] = 'true'
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from constants import TOKEN, BOT_NAME, MAX_CONNECTIONS, USE_PROXY, PROXY_URL, POLL_INTERVAL
from utils import check_single_instance
from database import db, init_db_improved
from security import import_banned_words_on_startup
from handlers import *
from tasks import BackgroundTaskManager
from web import start_web_server

from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram.request import HTTPXRequest

async def main():
    await init_db_improved()
    await import_banned_words_on_startup()

    if USE_PROXY:
        request = HTTPXRequest(proxy_url=PROXY_URL, read_timeout=60.0, write_timeout=30.0, connect_timeout=30.0, pool_timeout=10.0, connection_pool_size=MAX_CONNECTIONS)
    else:
        request = HTTPXRequest(read_timeout=60.0, write_timeout=30.0, connect_timeout=30.0, pool_timeout=10.0, connection_pool_size=MAX_CONNECTIONS)

    app = Application.builder().token(TOKEN).request(request).build()
    app.add_error_handler(global_error_handler)

    # الأوامر
    app.add_handler(CommandHandler("start", start_command_handler))
    app.add_handler(CommandHandler("help", help_command_handler))
    app.add_handler(CommandHandler("panel", panel_command_handler))
    app.add_handler(CommandHandler("stats", stats_command_handler))
    app.add_handler(CommandHandler("contests", contests_command_handler))
    app.add_handler(CommandHandler("trial", trial_command_handler))
    app.add_handler(CommandHandler("subscribe", subscribe_command_handler))
    app.add_handler(CommandHandler("syncgroup", syncgroup_command_handler))
    app.add_handler(CommandHandler("language", language_command_handler))
    app.add_handler(CommandHandler("security", security_command_handler))

    # الكولباك
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(lang_callback_handler, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(handle_text_callbacks, pattern="^(rank|top|language)$"))
    app.add_handler(CallbackQueryHandler(settings_menu_callback, pattern="^settings:menu$"))
    app.add_handler(CallbackQueryHandler(trial_callback, pattern="^trial$"))
    app.add_handler(CallbackQueryHandler(subscribe_menu_callback, pattern="^subscribe:menu$"))
    app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    app.add_handler(CallbackQueryHandler(contests_menu_callback, pattern="^contests_menu$"))
    app.add_handler(CallbackQueryHandler(my_groups_callback, pattern="^groups:my_groups$"))
    app.add_handler(CallbackQueryHandler(group_settings_callback, pattern="^groups:settings:"))
    app.add_handler(CallbackQueryHandler(security_links_callback, pattern="^security:links:"))
    app.add_handler(CallbackQueryHandler(security_mentions_callback, pattern="^security:mentions:"))
    app.add_handler(CallbackQueryHandler(security_stickers_callback, pattern="^security:stickers:"))
    app.add_handler(CallbackQueryHandler(security_videos_callback, pattern="^security:videos:"))

    # الرسائل (الخاص والمجموعات)
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, private_message_router))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))

    # لو عايز تشغل خادم الويب برضه (عشان لوحة التحكم)، ده شغال عادي:
    asyncio.create_task(start_web_server())

    print(f"🚀 تم تشغيل {BOT_NAME} - يرد في الخاص والمجموعات ✅")
    await app.run_polling(drop_pending_updates=True, poll_interval=POLL_INTERVAL)
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
