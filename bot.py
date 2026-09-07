#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🌿 Relax Manager – البوت الرئيسي (نسخة نهائية محسّنة ومصححة)
- إصلاحات أمنية في معالجة الدفع
- تسجيل جميع الأوامر
- دعم video_note
- المهام الخلفية مع إعادة تشغيل عند الفشل
- دعم webhook و polling
- فتح المنفذ تلقائيًا لتفعيل الخدمة على Render
- قوائم أوامر منفصلة للخاص والمجموعة
- تحسين تسجيل الأخطاء والمرونة
- تنظيف دوري لأقفال المستخدمين
- دمج نظام الكاش الموحد cache.py (مع fallback)
- إزالة filters.PAYMENT (غير موجود في الإصدار 22.8)
"""

import asyncio
import os
import logging
import traceback
import json
import time
from typing import Optional

from telegram import (
    BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatJoinRequestHandler, filters,
    PreCheckoutQueryHandler
)

from config import CONFIG, PATHS
from database import DB, initialize_db
from handlers import CommandHandlers, CallbackHandlers, MessageHandlers
from utils import (
    TranslationManager, KeyboardFactory, BackgroundTasks,
    ErrorHandler, setup_webhook, safe_send
)

# استيراد cache_cleanup_task مع fallback إذا لم يوجد الملف
try:
    from cache import cache_cleanup_task
except ImportError:
    async def cache_cleanup_task():
        """دالة فارغة إذا لم يوجد cache.py"""
        await asyncio.sleep(3600)
    logging.warning("⚠️ cache.py غير موجود، تم استخدام دالة فارغة لـ cache_cleanup_task")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

ALLOWED_UPDATES = [
    "message",
    "callback_query",
    "chat_join_request",
    "pre_checkout_query"
]


async def _validate_invoice_for_payment(user_id: int, payload: str):
    """التحقق من صحة الفاتورة للدفع (مقاوم للأخطاء)"""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.error(f"❌ Invalid JSON payload: {payload[:100]}")
        return None, None, None

    invoice_number = data.get('invoice')
    if not invoice_number:
        logger.error(f"❌ Invoice number missing in payload: {payload[:100]}")
        return None, None, None

    invoice = await DB.get_invoice(invoice_number)
    if not invoice or invoice['user_id'] != user_id or invoice['status'] != 'pending':
        logger.warning(f"❌ Invoice invalid or not pending for user {user_id}: {invoice_number}")
        return None, None, None

    payment_type = data.get('type')
    if payment_type not in ('subscription', 'gift'):
        logger.warning(f"❌ Unknown payment type: {payment_type}")
        return None, None, None

    plan_id = data.get('plan_id') or data.get('gift_plan_id')
    if not plan_id:
        logger.warning(f"❌ Plan ID missing in payload: {payload[:100]}")
        return None, None, None

    if payment_type == 'subscription':
        plan = await DB.get_plan(plan_id)
    else:
        plan = await DB.get_gift_plan(plan_id)

    if not plan:
        logger.warning(f"❌ Plan not found: {plan_id}")
        return None, None, None

    return invoice, plan, data


async def pre_checkout(update, context):
    """معالجة ما قبل الدفع (محسنة)"""
    query = update.pre_checkout_query
    user_id = query.from_user.id
    payload = query.invoice_payload

    invoice, plan, data = await _validate_invoice_for_payment(user_id, payload)

    if invoice is None or plan is None:
        logger.warning(f"❌ Pre-checkout rejected for user {user_id}")
        try:
            await query.answer(ok=False, error_message="الفاتورة غير صالحة أو انتهت صلاحيتها.")
        except Exception as e:
            logger.error(f"❌ Failed to answer pre-checkout rejection: {e}")
        return

    # التحقق من المبلغ (مع السماح بالدفع المجاني إذا السعر 0)
    expected_amount = plan.get('price', 0)
    total_amount = getattr(query, 'total_amount', None)
    if total_amount is not None:
        if expected_amount > 0 and total_amount != expected_amount:
            logger.warning(f"❌ Amount mismatch for user {user_id}: expected {expected_amount}, got {total_amount}")
            try:
                await query.answer(ok=False, error_message="المبلغ غير مطابق لسعر الخطة.")
            except Exception as e:
                logger.error(f"❌ Failed to answer amount mismatch: {e}")
            return
    else:
        if expected_amount > 0:
            logger.warning(f"❌ Missing total_amount for non-free plan {plan['id']}")
            try:
                await query.answer(ok=False, error_message="خطأ في معالجة الدفع.")
            except Exception as e:
                logger.error(f"❌ Failed to answer missing amount: {e}")
            return

    try:
        await query.answer(ok=True)
        logger.info(f"✅ Pre-checkout success: {query.id}")
    except Exception as e:
        logger.error(f"❌ Failed to answer pre-checkout success: {e}")


async def successful_payment(update, context):
    """معالجة الدفع الناجح (محسنة)"""
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    total_amount = payment.total_amount
    telegram_payment_charge_id = getattr(payment, 'telegram_payment_charge_id', None)
    provider_payment_charge_id = getattr(payment, 'provider_payment_charge_id', None)

    payment_id = telegram_payment_charge_id or provider_payment_charge_id
    if not payment_id:
        logger.error(f"❌ No payment ID for user {user_id}")
        await safe_send(context.bot, user_id, "❌ حدث خطأ في معالجة الدفع (لا يوجد معرف للدفع).")
        return

    invoice, plan, data = await _validate_invoice_for_payment(user_id, payload)

    if invoice is None or plan is None:
        logger.error(f"❌ Payment processing failed: invalid invoice or plan for user {user_id}")
        await safe_send(context.bot, user_id, "❌ حدث خطأ في معالجة الدفع.")
        return

    expected_amount = plan.get('price', 0)
    if expected_amount > 0 and total_amount != expected_amount:
        logger.error(f"❌ Amount mismatch in successful payment for user {user_id}: invoice {invoice['number']}")
        await safe_send(context.bot, user_id, "❌ المبلغ المدفوع غير مطابق.")
        return

    payment_type = data.get('type')

    try:
        if payment_type == 'subscription':
            success = await DB.activate_subscription_with_payment(
                user_id=user_id,
                invoice_number=invoice['number'],
                payment_id=payment_id,
                plan_id=plan['id']
            )
            if success:
                await DB.add_payment_log(user_id, 'xtr', 'subscription_paid', {'invoice': invoice['number'], 'plan_id': plan['id']})
                await safe_send(context.bot, user_id, f"✅ تم تفعيل اشتراك {plan['name']} بنجاح!")
                logger.info(f"✅ Subscription activated for user {user_id}, plan {plan['id']}")
            else:
                await safe_send(context.bot, user_id, "❌ حدث خطأ في معالجة الدفع.")
                logger.error(f"❌ Failed to activate subscription for user {user_id}, invoice {invoice['number']}")

        elif payment_type == 'gift':
            code = await DB.create_gift_code(plan_id=plan['id'], creator_id=user_id)
            if code:
                await DB.mark_invoice_paid(invoice['number'], payment_id)
                await safe_send(context.bot, user_id, f"🎉 تم شراء كود الهدية!\n🎁 الكود: `{code}`\n📅 المدة: {plan['days']} يوم")
                logger.info(f"✅ Gift code created for user {user_id}, plan {plan['id']}")
            else:
                await safe_send(context.bot, user_id, "❌ حدث خطأ في توليد كود الهدية.")
                logger.error(f"❌ Failed to create gift code for user {user_id}, invoice {invoice['number']}")

        else:
            logger.error(f"❌ Unknown payment type: {payment_type}")
            await safe_send(context.bot, user_id, "❌ نوع دفع غير معروف.")

    except Exception as e:
        logger.exception(f"❌ Exception in payment processing: {e}")
        await safe_send(context.bot, user_id, "❌ حدث خطأ غير متوقع أثناء معالجة الدفع.")


async def payment_error(update, context):
    """معالج الأخطاء المتعلقة بالدفع (احتياطي)"""
    logger.error(f"❌ Payment error: {update}")
    try:
        await safe_send(context.bot, update.effective_user.id, "❌ حدث خطأ أثناء معالجة الدفع. يرجى المحاولة مرة أخرى.")
    except Exception as e:
        logger.error(f"❌ Failed to send payment error message: {e}")


async def main():
    """الدالة الرئيسية"""
    try:
        CONFIG.validate()
    except ValueError as e:
        logger.error(f"❌ {e}")
        raise SystemExit(1)

    logger.info(f"🌿 {CONFIG.BOT_NAME}")
    logger.info(f"👨‍💼 المالك: {CONFIG.PRIMARY_OWNER_ID}")

    # تهيئة قاعدة البيانات
    await initialize_db()

    # تسجيل المطورين
    for dev_id in CONFIG.DEVELOPER_IDS:
        try:
            await DB.register_user(dev_id)
        except Exception as e:
            logger.error(f"❌ Failed to register developer {dev_id}: {e}")
    try:
        await DB.register_user(CONFIG.PRIMARY_OWNER_ID)
    except Exception as e:
        logger.error(f"❌ Failed to register owner: {e}")

    # تحميل الإعدادات
    KeyboardFactory.load_config()
    available_langs = TranslationManager.get_available_languages()
    for lang in available_langs:
        TranslationManager.load_translation(lang)
    logger.info(f"✅ تم تحميل {len(available_langs)} لغة")

    # المنفذ: استخدام PORT من البيئة أو الافتراضي
    port = int(os.getenv("PORT", CONFIG.WEB_PORT))

    # تحديد عنوان Webhook
    hostname = (
        os.getenv("RENDER_EXTERNAL_HOSTNAME") or
        os.getenv("RENDER_EXTERNAL_URL") or
        os.getenv("RAILWAY_PUBLIC_DOMAIN") or
        os.getenv("HEROKU_APP_NAME") or
        os.getenv("WEBHOOK_URL")
    )

    app = Application.builder().token(CONFIG.TOKEN).build()
    app.bot_data['start_time'] = time.monotonic()

    try:
        await app.initialize()
    except Exception as e:
        logger.error(f"❌ Failed to initialize app: {e}")
        raise

    # ========== قائمة الأوامر الخاصة ==========
    private_commands = [
        ("start", "🏠 القائمة الرئيسية"),
        ("help", "📚 المساعدة"),
        ("trial", "🎁 تجربة مجانية"),
        ("subscribe", "💎 اشتراك"),
        ("support", "📞 دعم فني"),
        ("language", "🌐 اللغة"),
        ("developer", "👨‍💻 المطور"),
        ("contests", "🏆 المسابقات"),
        ("stats", "📊 الإحصائيات"),
        ("replies", "💬 الردود التلقائية"),
        ("grant", "🎁 منح اشتراك يدوي"),
        ("set_min_interval", "⏱️ تعيين الحد الأدنى للفاصل"),
        ("gift_plans", "🎁 خطط الهدايا"),
        ("redeem_gift", "🎟️ استرداد كود هدية"),
        ("mood", "🎭 تحليل المشاعر"),
        ("admin", "👑 لوحة الأدمن"),
        ("broadcast", "📨 بث جماعي"),
        ("set_force", "🔒 تعيين الاشتراك الإجباري"),
        ("set_update_ch", "📢 تعيين قناة التحديثات"),
        ("set_log_ch", "📋 تعيين قناة السجلات"),
        ("add_admin", "👑 إضافة مشرف"),
        ("remove_admin", "🗑️ إزالة مشرف"),
        ("export_replies", "📤 تصدير الردود"),
        ("import_replies", "📥 استيراد الردود"),
        ("backup", "💾 نسخ احتياطي"),
        ("restore", "🔄 عرض النسخ"),
        ("auto_publish", "📤 تبديل النشر التلقائي"),
        ("auto_recycle", "♻️ تبديل التدوير"),
        ("channels", "📡 قنواتي"),
        ("posts", "📋 منشوراتي"),
    ]

    # ========== قائمة أوامر المجموعة ==========
    group_commands = [
        ("syncgroup", "🔗 تفعيل المجموعة"),
        ("security", "🛡️ إعدادات الأمان"),
        ("panel", "📋 لوحة التحكم"),
        ("lock", "🔒 قفل المجموعة"),
        ("unlock", "🔓 فتح المجموعة"),
        ("ban", "🚫 حظر مستخدم"),
        ("mute", "🔇 كتم مستخدم"),
        ("warn", "⚠️ تحذير مستخدم"),
        ("kick", "👢 طرد مستخدم"),
        ("restrict", "🔒 تقييد مستخدم"),
        ("unban", "🔓 إلغاء حظر"),
        ("pin", "📌 تثبيت رسالة"),
    ]

    # تعيين الأوامر حسب النطاق
    await app.bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
    await app.bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())

    # ========== تسجيل المعالجات ==========
    # الأوامر الأساسية
    app.add_handler(CommandHandler("start", CommandHandlers.start))
    app.add_handler(CommandHandler("help", CommandHandlers.help_command))
    app.add_handler(CommandHandler("trial", CommandHandlers.trial))
    app.add_handler(CommandHandler("subscribe", CommandHandlers.subscribe))
    app.add_handler(CommandHandler("support", CommandHandlers.support))
    app.add_handler(CommandHandler("developer", CommandHandlers.developer))
    app.add_handler(CommandHandler("stats", CommandHandlers.stats))
    app.add_handler(CommandHandler("language", CommandHandlers.language))
    app.add_handler(CommandHandler("contests", CommandHandlers.contests))
    app.add_handler(CommandHandler("replies", CommandHandlers.replies_command))
    app.add_handler(CommandHandler("grant", CommandHandlers.grant))
    app.add_handler(CommandHandler("set_min_interval", CommandHandlers.set_min_interval))
    app.add_handler(CommandHandler("gift_plans", CommandHandlers.gift_plans))
    app.add_handler(CommandHandler("redeem_gift", CommandHandlers.redeem_gift))

    # أوامر المجموعات
    app.add_handler(CommandHandler("syncgroup", CommandHandlers.syncgroup))
    app.add_handler(CommandHandler("security", CommandHandlers.security))
    app.add_handler(CommandHandler("panel", CommandHandlers.panel))
    app.add_handler(CommandHandler("lock", CommandHandlers.lock))
    app.add_handler(CommandHandler("unlock", CommandHandlers.unlock))
    app.add_handler(CommandHandler("ban", CommandHandlers.ban))
    app.add_handler(CommandHandler("mute", CommandHandlers.mute))
    app.add_handler(CommandHandler("warn", CommandHandlers.warn))
    app.add_handler(CommandHandler("kick", CommandHandlers.kick))
    app.add_handler(CommandHandler("restrict", CommandHandlers.restrict))
    app.add_handler(CommandHandler("unban", CommandHandlers.unban))
    app.add_handler(CommandHandler("pin", CommandHandlers.pin))

    # أوامر المشرفين المخفيين
    app.add_handler(CommandHandler("register_hidden_owner", CommandHandlers.register_hidden_owner))
    app.add_handler(CommandHandler("remove_hidden_owner", CommandHandlers.remove_hidden_owner))
    app.add_handler(CommandHandler("add_hidden_admin", CommandHandlers.add_hidden_admin))
    app.add_handler(CommandHandler("remove_hidden_admin", CommandHandlers.remove_hidden_admin))
    app.add_handler(CommandHandler("list_hidden_admins", CommandHandlers.list_hidden_admins))

    # الأوامر الجديدة
    app.add_handler(CommandHandler("mood", CommandHandlers.mood))
    app.add_handler(CommandHandler("admin", CommandHandlers.admin))
    app.add_handler(CommandHandler("broadcast", CommandHandlers.broadcast))
    app.add_handler(CommandHandler("set_force", CommandHandlers.set_force))
    app.add_handler(CommandHandler("set_update_ch", CommandHandlers.set_update_ch))
    app.add_handler(CommandHandler("set_log_ch", CommandHandlers.set_log_ch))
    app.add_handler(CommandHandler("add_admin", CommandHandlers.add_admin))
    app.add_handler(CommandHandler("remove_admin", CommandHandlers.remove_admin))
    app.add_handler(CommandHandler("export_replies", CommandHandlers.export_replies))
    app.add_handler(CommandHandler("import_replies", CommandHandlers.import_replies))
    app.add_handler(CommandHandler("backup", CommandHandlers.backup))
    app.add_handler(CommandHandler("restore", CommandHandlers.restore))
    app.add_handler(CommandHandler("auto_publish", CommandHandlers.auto_publish))
    app.add_handler(CommandHandler("auto_recycle", CommandHandlers.auto_recycle))
    app.add_handler(CommandHandler("channels", CommandHandlers.channels))
    app.add_handler(CommandHandler("posts", CommandHandlers.posts))

    # معالجات الدفع
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    # تم حذف السطر: app.add_handler(MessageHandler(filters.PAYMENT, payment_error))

    # معالج الأزرار
    app.add_handler(CallbackQueryHandler(CallbackHandlers.handle))

    # معالجات الرسائل
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL |
         filters.AUDIO | filters.VOICE | filters.ANIMATION | filters.Sticker.ALL |
         filters.VIDEO_NOTE) &
        filters.ChatType.PRIVATE & ~filters.COMMAND,
        MessageHandlers.handle_private
    ))

    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL |
         filters.AUDIO | filters.VOICE | filters.ANIMATION | filters.Sticker.ALL |
         filters.VIDEO_NOTE) &
        filters.ChatType.GROUPS & ~filters.COMMAND,
        MessageHandlers.handle_group
    ))

    app.add_handler(MessageHandler(
        filters.StatusUpdate.ALL & filters.ChatType.GROUPS,
        MessageHandlers.handle_service
    ))

    app.add_handler(ChatJoinRequestHandler(MessageHandlers.handle_join_request))
    app.add_error_handler(ErrorHandler.handle_error)

    # ========== المهام الخلفية ==========
    async def run_task_with_retry(task_func, *args, task_name=""):
        while True:
            try:
                await task_func(*args)
            except asyncio.CancelledError:
                logger.info(f"🛑 مهمة {task_name} أُلغيت")
                raise
            except Exception as e:
                logger.error(f"❌ Task {task_name} crashed: {e}", exc_info=True)
                logger.info(f"🔄 إعادة تشغيل المهمة {task_name} بعد 5 ثوانٍ...")
                await asyncio.sleep(5)

    # مهمة تنظيف الأقفال غير المستخدمة
    async def cleanup_locks():
        while True:
            try:
                await DB.cleanup_user_locks(max_idle_seconds=3600)
                await asyncio.sleep(3600)  # كل ساعة
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"❌ cleanup_locks failed: {e}")
                await asyncio.sleep(60)

    tasks = [
        asyncio.create_task(run_task_with_retry(BackgroundTasks.auto_publish, app.bot, task_name="auto_publish")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.auto_backup, task_name="auto_backup")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.reminders, app.bot, task_name="reminders")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.heartbeat, app.bot, task_name="heartbeat")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.flush_usage_periodically, task_name="flush_usage")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.expire_subscriptions, task_name="expire_subscriptions")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.sync_admins_periodically, app.bot, task_name="sync_admins")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.expire_penalties_periodically, task_name="expire_penalties")),
        asyncio.create_task(run_task_with_retry(cache_cleanup_task, task_name="cache_cleanup")),
        asyncio.create_task(run_task_with_retry(cleanup_locks, task_name="cleanup_locks")),
    ]

    # ========== بدء التشغيل ==========
    try:
        if hostname:
            webhook_url = f"https://{hostname}/{CONFIG.TOKEN}"
            logger.info(f"🔗 Webhook: {webhook_url}")
            await app.bot.delete_webhook(drop_pending_updates=True)
            await app.bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True,
                allowed_updates=ALLOWED_UPDATES
            )
            logger.info("✅ Webhook تم التعيين")
            runner = await setup_webhook(app, port)
            try:
                await asyncio.Event().wait()
            finally:
                await runner.cleanup()
        else:
            logger.info("⚠️ Polling")
            runner = await setup_webhook(app, port)
            try:
                await app.run_polling(
                    drop_pending_updates=True,
                    allowed_updates=ALLOWED_UPDATES
                )
            finally:
                await runner.cleanup()
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await app.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 تم الإيقاف")
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        traceback.print_exc()