#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import nest_asyncio
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram import BotCommand
from telegram.request import HTTPXRequest
from config import TOKEN, USE_PROXY, PROXY_URL, MAX_CONNECTIONS, BOT_NAME
from core.database import db_pool, init_db
from core.translation import load_all_languages
from handlers.commands import *
from handlers.callbacks import *
from handlers.messages import message_handler, filter_messages_handler
from services.scheduler import auto_publish_loop
from services.web_server import start_web_server
from utils.logger import setup_logger

nest_asyncio.apply()
logger = setup_logger()

async def run_bot():
    await init_db()
    await db_pool.initialize()
    await load_all_languages()
    
    if USE_PROXY:
        request = HTTPXRequest(proxy_url=PROXY_URL, read_timeout=60, connection_pool_size=MAX_CONNECTIONS)
    else:
        request = HTTPXRequest(read_timeout=60, connection_pool_size=MAX_CONNECTIONS)
    
    app = Application.builder().token(TOKEN).request(request).build()
    
    # الأوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("trial", trial_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("syncgroup", syncgroup_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("rank", rank_command))
    app.add_handler(CommandHandler("top", top_command))
    app.add_handler(CommandHandler("developer", developer_command))
    app.add_handler(CommandHandler("support", support_command))
    app.add_handler(CommandHandler("lock", lock_command))
    app.add_handler(CommandHandler("unlock", unlock_command))
    
    # الكيبورد
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    app.add_handler(CallbackQueryHandler(lang_callback, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(add_channel_callback, pattern="^channels:add$"))
    app.add_handler(CallbackQueryHandler(my_channels_callback, pattern="^channels:my$"))
    app.add_handler(CallbackQueryHandler(add_15_posts_callback, pattern="^posts:add_15$"))
    app.add_handler(CallbackQueryHandler(publish_one_callback, pattern="^posts:publish_one$"))
    app.add_handler(CallbackQueryHandler(my_posts_callback, pattern="^posts:my_posts$"))
    app.add_handler(CallbackQueryHandler(recycle_posts_callback, pattern="^posts:recycle$"))
    app.add_handler(CallbackQueryHandler(settings_menu_callback, pattern="^settings:menu$"))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin:panel$"))
    
    # الرسائل
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler))
    
    # أوامر القائمة
    commands = [
        BotCommand("start", "بدء البوت"),
        BotCommand("help", "المساعدة"),
        BotCommand("language", "تغيير اللغة"),
        BotCommand("trial", "تجربة مجانية"),
        BotCommand("subscribe", "الاشتراك"),
        BotCommand("syncgroup", "تفعيل المجموعة"),
        BotCommand("stats", "إحصائيات القناة"),
        BotCommand("rank", "رتبتك"),
        BotCommand("top", "أفضل 10"),
    ]
    await app.bot.set_my_commands(commands)
    
    # المهام الخلفية
    asyncio.create_task(auto_publish_loop(app.bot))
    asyncio.create_task(start_web_server())
    
    print(f"🚀 {BOT_NAME} يعمل الآن!")
    await app.run_polling(drop_pending_updates=True)
    # أزرار إضافية
    app.add_handler(CallbackQueryHandler(schedule_menu_callback, pattern="^schedule:menu$"))
    app.add_handler(CallbackQueryHandler(channel_stats_callback, pattern="^channel_stats$"))
    app.add_handler(CallbackQueryHandler(publish_all_callback, pattern="^publish_all$"))
    app.add_handler(CallbackQueryHandler(referral_menu_callback, pattern="^referral:menu$"))
    app.add_handler(CallbackQueryHandler(reminder_menu_callback, pattern="^reminder:menu$"))
    app.add_handler(CallbackQueryHandler(translation_menu_callback, pattern="^translation:menu$"))
    app.add_handler(CallbackQueryHandler(support_menu_callback, pattern="^support:menu$"))
    app.add_handler(CallbackQueryHandler(developer_callback, pattern="^developer$"))
    app.add_handler(CallbackQueryHandler(updates_callback, pattern="^updates$"))
    app.add_handler(CallbackQueryHandler(contests_menu_callback, pattern="^contests_menu$"))
