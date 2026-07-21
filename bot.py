#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
الملف الرئيسي لتشغيل البوت - النسخة النهائية المُحسَّنة
- متوافق مع BackgroundTaskManager
- متوافق مع handlers.py الكامل
- معالجة check_single_instance على جميع الأنظمة
- دمج الرسائل الخاصة مع إنشاء المسابقات
"""

import asyncio
import os
import sys
import traceback
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
from handlers import (
    # الأوامر
    start_command_handler, language_command_handler,
    syncgroup_command_handler, security_command_handler,
    register_hidden_owner_handler, add_hidden_admin_command,
    remove_hidden_admin_command, list_hidden_admins_command,
    trial_command_handler, subscribe_command_handler,
    help_command_handler, support_command_handler,
    rank_command_handler, top_command_handler,
    developer_command_handler, updates_command_handler,
    stats_command_handler, lock_chat_command_handler,
    unlock_chat_command_handler, panel_command_handler,
    schedule_post_command_handler, set_log_channel_command_handler,
    set_rules_command_handler, rules_command_handler,
    handle_moderation_commands, track_chat_add,
    track_chat_member, on_bot_added, filter_messages_handler,
    message_handler_main, global_error_handler,
    pre_checkout_callback_handler, successful_payment_callback_handler,
    # الكولباك
    main_menu_callback, back_callback, cancel_session_callback,
    add_channel_callback, my_channels_callback,
    delete_channel_callback, select_channel_callback,
    add_15_posts_callback, publish_one_callback,
    my_posts_callback, delete_single_post_callback,
    confirm_clear_all_posts_callback, clear_all_posts_callback,
    recycle_posts_callback, my_pending_stats_callback,
    my_full_stats_callback, my_groups_callback,
    delete_group_callback, group_settings_callback,
    settings_menu_callback, toggle_auto_publish_callback,
    toggle_auto_recycle_callback,
    schedule_menu_callback, set_interval_minutes_callback,
    set_interval_hours_callback, set_interval_days_callback,
    set_cron_callback, set_days_callback, set_dates_callback,
    set_publish_time_callback, day_select_callback,
    save_days_callback,
    security_links_callback, security_mentions_callback,
    security_warn_callback, security_slowmode_callback,
    security_banned_words_menu_callback, banned_words_add_callback,
    banned_words_list_callback, banned_words_remove_callback,
    security_welcome_callback, security_goodbye_callback,
    security_stickers_callback, security_videos_callback,
    security_service_messages_callback, security_close_callback,
    security_main_callback, security_select_group_callback,
    security_refresh_groups_callback,
    penalty_menu_callback, penalty_kick_callback,
    penalty_ban_callback, penalty_mute_callback,
    penalty_mute_duration_callback,
    help_callback, support_menu_callback,
    support_help_callback, support_ticket_callback,
    support_back_callback,
    trial_callback, subscribe_menu_callback,
    buy_subscription_1_callback, buy_subscription_2_callback,
    buy_subscription_30_callback, buy_subscription_90_callback,
    developer_callback, updates_callback,
    referral_menu_callback, referral_copy_link_callback,
    referral_claim_reward_callback, referral_list_callback,
    reminder_menu_callback, reminder_toggle_sub_callback,
    reminder_toggle_daily_callback, reminder_toggle_weekly_callback,
    reminder_set_days_callback, reminder_set_lang_callback,
    reminder_lang_callback,
    translation_menu_callback, translation_off_callback,
    translation_set_callback,
    admin_panel_callback,
    contests_command_handler, contests_menu_callback,
    contest_join_callback, contest_winners_callback,
    contests_back_callback,
    create_contest_command_handler, declare_winner_command_handler,
    admin_create_contest_callback, admin_declare_winner_callback,
    lang_callback_handler, handle_text_callbacks,
    advanced_actions_callback, group_action_ban_callback,
    group_action_mute_callback, advanced_mute_duration_callback,
    group_action_warn_callback, group_action_kick_callback,
    group_action_restrict_callback, group_action_pin_callback,
    group_action_log_callback, group_action_unban_callback,
    panel_lock_callback_handler, panel_unlock_callback_handler,
    panel_close_callback_handler,
    publish_all_channels_callback_handler,
    channel_stats_callback, channel_growth_callback,
    channel_stats_refresh_callback, my_channel_stats_callback,
    check_subscribe_callback_handler,
    admin_auto_reply_callback,
    # دوال إنشاء المسابقات (سيتم استدعاؤها من داخل private_message_router)
    handle_contest_creation_states,
    # دوال أخرى
    sendcode_command_handler, admin_replies_callback,
    admin_banned_words_callback, nsfw_settings_callback,
    handle_sendcode_confirmation_handler
)
from tasks import BackgroundTaskManager
from web import start_web_server

from telegram import BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, PreCheckoutQueryHandler, ChatMemberHandler
)
from telegram.request import HTTPXRequest


# ===================== دالة وسيطة لمعالج الرسائل الخاصة =====================
async def private_message_router(update, context):
    """
    معالج موحّد للرسائل الخاصة:
    - إذا كان المستخدم في جلسة إنشاء مسابقة، يتم توجيهه إلى handle_contest_creation_states
    - وإلا يتم توجيهه إلى message_handler_main
    """
    try:
        from database import db_is_creating_contest
        user_id = update.effective_user.id
        if await db_is_creating_contest(user_id):
            return await handle_contest_creation_states(update, context)
    except (ImportError, AttributeError):
        if context.user_data.get("creating_contest"):
            return await handle_contest_creation_states(update, context)

    return await message_handler_main(update, context)


# ===================== الدالة الرئيسية =====================

async def main():
    """تشغيل البوت"""
    # تهيئة قاعدة البيانات واستيراد الكلمات المحظورة
    await init_db_improved()
    await import_banned_words_on_startup()

    # تهيئة قفل NSFW
    get_nsfw_lock()

    # إعداد طلبات HTTP
    if USE_PROXY:
        request = HTTPXRequest(
            proxy_url=PROXY_URL,
            read_timeout=60.0,
            write_timeout=30.0,
            connect_timeout=30.0,
            pool_timeout=10.0,
            connection_pool_size=MAX_CONNECTIONS
        )
    else:
        request = HTTPXRequest(
            read_timeout=60.0,
            write_timeout=30.0,
            connect_timeout=30.0,
            pool_timeout=10.0,
            connection_pool_size=MAX_CONNECTIONS
        )

    application = Application.builder().token(TOKEN).request(request).build()
    application.add_error_handler(global_error_handler)

    # ========== الأوامر ==========
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("language", language_command_handler))
    application.add_handler(CommandHandler("syncgroup", syncgroup_command_handler))
    application.add_handler(CommandHandler("security", security_command_handler))
    application.add_handler(CommandHandler("register_hidden_owner", register_hidden_owner_handler))
    application.add_handler(CommandHandler("add_hidden_admin", add_hidden_admin_command))
    application.add_handler(CommandHandler("remove_hidden_admin", remove_hidden_admin_command))
    application.add_handler(CommandHandler("list_hidden_admins", list_hidden_admins_command))
    application.add_handler(CommandHandler("trial", trial_command_handler))
    application.add_handler(CommandHandler("subscribe", subscribe_command_handler))
    application.add_handler(CommandHandler("help", help_command_handler))
    application.add_handler(CommandHandler("support", support_command_handler))
    application.add_handler(CommandHandler("rank", rank_command_handler))
    application.add_handler(CommandHandler("top", top_command_handler))
    application.add_handler(CommandHandler("developer", developer_command_handler))
    application.add_handler(CommandHandler("updates", updates_command_handler))
    application.add_handler(CommandHandler("stats", stats_command_handler))
    application.add_handler(CommandHandler("lock", lock_chat_command_handler))
    application.add_handler(CommandHandler("unlock", unlock_chat_command_handler))
    application.add_handler(CommandHandler("schedule", schedule_post_command_handler))
    application.add_handler(CommandHandler("panel", panel_command_handler))
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

    # ========== الكولباك ==========
    application.add_handler(CallbackQueryHandler(lang_callback_handler, pattern="^lang_"))
    application.add_handler(CallbackQueryHandler(handle_text_callbacks, pattern="^(rank|top|schedule_post|language)$"))
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(back_callback, pattern="^back$"))
    application.add_handler(CallbackQueryHandler(cancel_session_callback, pattern="^cancel_session$"))
    application.add_handler(CallbackQueryHandler(add_channel_callback, pattern="^channels:add$"))
    application.add_handler(CallbackQueryHandler(my_channels_callback, pattern="^channels:my_channels$"))
    application.add_handler(CallbackQueryHandler(delete_channel_callback, pattern="^channels:delete:"))
    application.add_handler(CallbackQueryHandler(select_channel_callback, pattern="^channels:select:"))
    application.add_handler(CallbackQueryHandler(add_15_posts_callback, pattern="^posts:add_15$"))
    application.add_handler(CallbackQueryHandler(publish_one_callback, pattern="^posts:publish_one$"))
    application.add_handler(CallbackQueryHandler(my_posts_callback, pattern="^posts:my_posts$"))
    application.add_handler(CallbackQueryHandler(recycle_posts_callback, pattern="^posts:recycle$"))
    application.add_handler(CallbackQueryHandler(delete_single_post_callback, pattern="^posts:delete_single:"))
    application.add_handler(CallbackQueryHandler(confirm_clear_all_posts_callback, pattern="^posts:confirm_clear_all:"))
    application.add_handler(CallbackQueryHandler(clear_all_posts_callback, pattern="^posts:clear_all:"))
    application.add_handler(CallbackQueryHandler(my_pending_stats_callback, pattern="^stats:pending$"))
    application.add_handler(CallbackQueryHandler(my_full_stats_callback, pattern="^stats:full$"))
    application.add_handler(CallbackQueryHandler(my_groups_callback, pattern="^groups:my_groups$"))
    application.add_handler(CallbackQueryHandler(delete_group_callback, pattern="^delete_group:"))
    application.add_handler(CallbackQueryHandler(group_settings_callback, pattern="^groups:settings:"))
    application.add_handler(CallbackQueryHandler(settings_menu_callback, pattern="^settings:menu$"))
    application.add_handler(CallbackQueryHandler(toggle_auto_publish_callback, pattern="^settings:toggle_auto_publish$"))
    application.add_handler(CallbackQueryHandler(toggle_auto_recycle_callback, pattern="^settings:toggle_auto_recycle$"))
    application.add_handler(CallbackQueryHandler(schedule_menu_callback, pattern="^schedule:menu:"))
    application.add_handler(CallbackQueryHandler(set_interval_minutes_callback, pattern="^schedule:set_interval_minutes:"))
    application.add_handler(CallbackQueryHandler(set_interval_hours_callback, pattern="^schedule:set_interval_hours:"))
    application.add_handler(CallbackQueryHandler(set_interval_days_callback, pattern="^schedule:set_interval_days:"))
    application.add_handler(CallbackQueryHandler(set_cron_callback, pattern="^schedule:set_cron:"))
    application.add_handler(CallbackQueryHandler(set_days_callback, pattern="^schedule:set_days:"))
    application.add_handler(CallbackQueryHandler(set_dates_callback, pattern="^schedule:set_dates:"))
    application.add_handler(CallbackQueryHandler(set_publish_time_callback, pattern="^schedule:set_publish_time:"))
    application.add_handler(CallbackQueryHandler(day_select_callback, pattern="^schedule:day_select:"))
    application.add_handler(CallbackQueryHandler(save_days_callback, pattern="^schedule:save_days$"))
    application.add_handler(CallbackQueryHandler(security_links_callback, pattern="^security:links:"))
    application.add_handler(CallbackQueryHandler(security_mentions_callback, pattern="^security:mentions:"))
    application.add_handler(CallbackQueryHandler(security_warn_callback, pattern="^security:warn:"))
    application.add_handler(CallbackQueryHandler(security_slowmode_callback, pattern="^security:slowmode:"))
    application.add_handler(CallbackQueryHandler(security_banned_words_menu_callback, pattern="^security:banned_words_menu:"))
    application.add_handler(CallbackQueryHandler(security_welcome_callback, pattern="^security:welcome:"))
    application.add_handler(CallbackQueryHandler(security_goodbye_callback, pattern="^security:goodbye:"))
    application.add_handler(CallbackQueryHandler(security_stickers_callback, pattern="^security:stickers:"))
    application.add_handler(CallbackQueryHandler(security_videos_callback, pattern="^security:videos:"))
    application.add_handler(CallbackQueryHandler(security_service_messages_callback, pattern="^security:service_messages:"))
    application.add_handler(CallbackQueryHandler(security_close_callback, pattern="^security:close$"))
    application.add_handler(CallbackQueryHandler(security_main_callback, pattern="^security:main$"))
    application.add_handler(CallbackQueryHandler(security_select_group_callback, pattern="^security_select_group:"))
    application.add_handler(CallbackQueryHandler(security_refresh_groups_callback, pattern="^security_refresh_groups$"))
    application.add_handler(CallbackQueryHandler(banned_words_add_callback, pattern="^banned_words:add:"))
    application.add_handler(CallbackQueryHandler(banned_words_list_callback, pattern="^banned_words:list:"))
    application.add_handler(CallbackQueryHandler(banned_words_remove_callback, pattern="^banned_words:remove:"))
    application.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    application.add_handler(CallbackQueryHandler(support_menu_callback, pattern="^support:menu$"))
    application.add_handler(CallbackQueryHandler(support_help_callback, pattern="^support:help$"))
    application.add_handler(CallbackQueryHandler(support_ticket_callback, pattern="^support:ticket$"))
    application.add_handler(CallbackQueryHandler(support_back_callback, pattern="^support:back$"))
    application.add_handler(CallbackQueryHandler(trial_callback, pattern="^trial$"))
    application.add_handler(CallbackQueryHandler(subscribe_menu_callback, pattern="^subscribe:menu$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_1_callback, pattern="^buy:subscription_1$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_2_callback, pattern="^buy:subscription_2$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_30_callback, pattern="^buy:subscription_30$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_90_callback, pattern="^buy:subscription_90$"))
    application.add_handler(CallbackQueryHandler(developer_callback, pattern="^developer$"))
    application.add_handler(CallbackQueryHandler(updates_callback, pattern="^updates$"))
    application.add_handler(CallbackQueryHandler(referral_menu_callback, pattern="^referral:menu$"))
    application.add_handler(CallbackQueryHandler(referral_copy_link_callback, pattern="^referral:copy_link:"))
    application.add_handler(CallbackQueryHandler(referral_claim_reward_callback, pattern="^referral:claim_reward$"))
    application.add_handler(CallbackQueryHandler(referral_list_callback, pattern="^referral:list$"))
    application.add_handler(CallbackQueryHandler(reminder_menu_callback, pattern="^reminder:menu$"))
    application.add_handler(CallbackQueryHandler(reminder_toggle_sub_callback, pattern="^reminder:toggle_sub$"))
    application.add_handler(CallbackQueryHandler(reminder_toggle_daily_callback, pattern="^reminder:toggle_daily$"))
    application.add_handler(CallbackQueryHandler(reminder_toggle_weekly_callback, pattern="^reminder:toggle_weekly$"))
    application.add_handler(CallbackQueryHandler(reminder_set_days_callback, pattern="^reminder:set_days$"))
    application.add_handler(CallbackQueryHandler(reminder_set_lang_callback, pattern="^reminder:set_lang$"))
    application.add_handler(CallbackQueryHandler(reminder_lang_callback, pattern="^reminder:lang:"))
    application.add_handler(CallbackQueryHandler(translation_menu_callback, pattern="^translation:menu$"))
    application.add_handler(CallbackQueryHandler(translation_off_callback, pattern="^translation:off$"))
    application.add_handler(CallbackQueryHandler(translation_set_callback, pattern="^translation:set:"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin:panel$"))
    application.add_handler(CallbackQueryHandler(contests_menu_callback, pattern="^contests_menu$"))
    application.add_handler(CallbackQueryHandler(contest_join_callback, pattern="^contest_join:"))
    application.add_handler(CallbackQueryHandler(contest_winners_callback, pattern="^contest_winners$"))
    application.add_handler(CallbackQueryHandler(contests_back_callback, pattern="^contests_back$"))
    application.add_handler(CallbackQueryHandler(admin_create_contest_callback, pattern="^admin:create_contest$"))
    application.add_handler(CallbackQueryHandler(admin_declare_winner_callback, pattern="^admin:declare_winner$"))
    application.add_handler(CallbackQueryHandler(advanced_actions_callback, pattern="^advanced_actions:"))
    application.add_handler(CallbackQueryHandler(group_action_ban_callback, pattern="^group_action:ban:"))
    application.add_handler(CallbackQueryHandler(group_action_mute_callback, pattern="^group_action:mute:"))
    application.add_handler(CallbackQueryHandler(advanced_mute_duration_callback, pattern="^adv_mute_duration:"))
    application.add_handler(CallbackQueryHandler(group_action_warn_callback, pattern="^group_action:warn:"))
    application.add_handler(CallbackQueryHandler(group_action_kick_callback, pattern="^group_action:kick:"))
    application.add_handler(CallbackQueryHandler(group_action_restrict_callback, pattern="^group_action:restrict:"))
    application.add_handler(CallbackQueryHandler(group_action_pin_callback, pattern="^group_action:pin:"))
    application.add_handler(CallbackQueryHandler(group_action_log_callback, pattern="^group_action:log:"))
    application.add_handler(CallbackQueryHandler(group_action_unban_callback, pattern="^group_action:unban:"))
    application.add_handler(CallbackQueryHandler(panel_lock_callback_handler, pattern="^panel:lock:"))
    application.add_handler(CallbackQueryHandler(panel_unlock_callback_handler, pattern="^panel:unlock:"))
    application.add_handler(CallbackQueryHandler(panel_close_callback_handler, pattern="^panel:close$"))
    application.add_handler(CallbackQueryHandler(penalty_menu_callback, pattern="^penalty_menu:"))
    application.add_handler(CallbackQueryHandler(penalty_kick_callback, pattern="^penalty:kick:"))
    application.add_handler(CallbackQueryHandler(penalty_ban_callback, pattern="^penalty:ban:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_callback, pattern="^penalty:mute:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern="^group_mute_duration:"))
    application.add_handler(CallbackQueryHandler(publish_all_channels_callback_handler, pattern="^publish_all_channels$"))
    application.add_handler(CallbackQueryHandler(channel_stats_callback, pattern="^channel_stats:"))
    application.add_handler(CallbackQueryHandler(channel_growth_callback, pattern="^channel_growth:"))
    application.add_handler(CallbackQueryHandler(channel_stats_refresh_callback, pattern="^channel_stats_refresh:"))
    application.add_handler(CallbackQueryHandler(my_channel_stats_callback, pattern="^my_channel_stats$"))
    application.add_handler(CallbackQueryHandler(check_subscribe_callback_handler, pattern="^check_subscribe$"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern="^admin_auto_reply$"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern="^admin_auto_reply_select:"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern="^auto_reply_toggle:"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern="^auto_reply_admins:"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern="^auto_reply_reset:"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern="^auto_reply_confirm_reset:"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern="^auto_reply_cancel:"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern="^auto_reply_stats:"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern="^user_auto_reply_toggle:"))
    application.add_handler(CallbackQueryHandler(nsfw_settings_callback, pattern="^nsfw_settings$"))
    application.add_handler(CallbackQueryHandler(nsfw_settings_callback, pattern="^nsfw_toggle$"))
    application.add_handler(CallbackQueryHandler(nsfw_settings_callback, pattern="^nsfw_threshold_set$"))
    application.add_handler(CallbackQueryHandler(admin_replies_callback, pattern="^admin_replies:"))
    application.add_handler(CallbackQueryHandler(admin_banned_words_callback, pattern="^admin_banned_words:"))
    application.add_handler(CallbackQueryHandler(handle_sendcode_confirmation_handler, pattern="^sendcode_confirm:"))

    # ========== الدفع ==========
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_callback_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback_handler))

    # ========== المجموعات والأعضاء ==========
    application.add_handler(ChatMemberHandler(track_chat_add, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_bot_added))

    # ========== الرسائل ==========
    # المجموعات
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    application.add_handler(MessageHandler(filters.CAPTION & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))

    # الخاص (مع دمج إنشاء المسابقات)
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, private_message_router))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, private_message_router))
    application.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, private_message_router))
    application.add_handler(MessageHandler(filters.AUDIO & filters.ChatType.PRIVATE, private_message_router))
    application.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, private_message_router))
    application.add_handler(MessageHandler(filters.ANIMATION & filters.ChatType.PRIVATE, private_message_router))

    # ========== قائمة الأوامر ==========
    commands = [
        BotCommand("start", "بدء البوت"),
        BotCommand("trial", "تجربة مجانية"),
        BotCommand("subscribe", "الاشتراك"),
        BotCommand("syncgroup", "تفعيل المجموعة"),
        BotCommand("security", "إعدادات الأمان"),
        BotCommand("register_hidden_owner", "تسجيل مالك مخفي"),
        BotCommand("add_hidden_admin", "إضافة مشرف مخفي"),
        BotCommand("remove_hidden_admin", "إزالة مشرف مخفي"),
        BotCommand("list_hidden_admins", "عرض المشرفين المخفيين"),
        BotCommand("rank", "رتبتك"),
        BotCommand("top", "أفضل 10"),
        BotCommand("stats", "إحصائيات القناة"),
        BotCommand("lock", "قفل المجموعة"),
        BotCommand("unlock", "فتح المجموعة"),
        BotCommand("schedule", "جدولة منشور"),
        BotCommand("panel", "لوحة التحكم"),
        BotCommand("language", "تغيير اللغة"),
        BotCommand("support", "مركز الدعم"),
        BotCommand("help", "المساعدة"),
        BotCommand("developer", "المطور"),
        BotCommand("updates", "آخر التحديثات"),
        BotCommand("ban", "حظر مستخدم"),
        BotCommand("mute", "كتم مستخدم"),
        BotCommand("warn", "تحذير مستخدم"),
        BotCommand("kick", "طرد مستخدم"),
        BotCommand("restrict", "تقييد مستخدم"),
        BotCommand("pin", "تثبيت رسالة"),
        BotCommand("unban", "إلغاء حظر مستخدم"),
        BotCommand("contests", "المسابقات"),
        BotCommand("create_contest", "إنشاء مسابقة"),
        BotCommand("declare_winner", "إعلان فائز"),
        BotCommand("set_rules", "تعيين قوانين المجموعة"),
        BotCommand("rules", "عرض قوانين المجموعة"),
        BotCommand("set_log_channel", "تعيين قناة التقارير"),
        BotCommand("sendcode", "إرسال كود البوت"),
    ]
    await application.bot.set_my_commands(commands)

    # ========== مهام الخلفية وخادم الويب ==========
    task_manager = BackgroundTaskManager(application.bot)
    await task_manager.start_all()
    asyncio.create_task(start_web_server())

    print(f"🚀 تم تشغيل {BOT_NAME} (الإصدار 19.3.3)")
    print("✅ جميع الملفات تم تحميلها بنجاح")
    print("📡 جاري تشغيل البوت...")

    try:
        await application.run_polling(
            drop_pending_updates=True,
            poll_interval=POLL_INTERVAL
        )
    except asyncio.CancelledError:
        advanced_logger.log_access(0, "BOT_CANCELLED", {})
    except KeyboardInterrupt:
        advanced_logger.log_access(0, "BOT_STOPPED_BY_USER", {})
    finally:
        advanced_logger.log_access(0, "BOT_SHUTDOWN", {})
        await task_manager.stop_all()
        await db.close()


# ===================== نقطة الدخول =====================

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
