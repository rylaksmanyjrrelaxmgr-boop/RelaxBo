#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_maintenance_commands.py - أوامر صيانة قاعدة البيانات (v1.0.1)
================================================================================
🆕 v1.0.1 — إصلاحات ما بعد المراجعة:
  ✅ إزالة imports غير مستخدمة (TimeUtils)
  ✅ حماية status_msg إذا فشل reply_text (كان قد يُسبِّب AttributeError)
  ✅ تنظيف _maint_pending القديمة داخل /db_maintenance (يمنع تسريب user_data)
  ✅ توثيق مشكلة job_queue.run_repeating vs while True:
       - job_queue.run_repeating ينشئ حلقة خارجية
       - scheduled_weekly_diagnostic يحتوي while True داخلياً
       - النتيجة: double loop + task لا ينتهي
       - الحل: استخدام start_weekly_diagnostic_task بدلاً من job_queue
  ✅ إضافة start_weekly_diagnostic_task() / stop_weekly_diagnostic_task()
     — الطريقة الصحيحة لبدء/إيقاف المهمة الأسبوعية
  ✅ تحسين معالجة الأخطاء في معاينة/تنفيذ الصيانة

3 أوامر:
  /db_diag_quick   — تقرير صحي مختصر (4 أسطر)
  /db_maintenance  — معاينة + تنفيذ الصيانة (DELETE + VACUUM)
  /db_weekly       — تفعيل/تعطيل التقرير الأسبوعي التلقائي

دوال مساعدة:
  scheduled_weekly_diagnostic()      — المهمة الدورية (long-running)
  start_weekly_diagnostic_task()     — 🆕 بدء كـasyncio background
  stop_weekly_diagnostic_task()      — 🆕 إيقاف نظيف
  register_maintenance_commands()    — تسجيل الأوامر

⚠️ الصلاحيات:
  - كل الأوامر تتطلب PRIMARY_OWNER_ID أو is_developer
================================================================================
"""

import asyncio
import logging
import time
from typing import Optional

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from config import CONFIG
from database import DB

try:
    from db_diagnostics import (
        diagnose_db_quick,
        preview_maintenance,
        run_maintenance,
        format_maintenance_preview,
        format_maintenance_result,
    )
except ImportError:
    diagnose_db_quick = None
    preview_maintenance = None
    run_maintenance = None
    format_maintenance_preview = None
    format_maintenance_result = None

try:
    from utils import safe_send
except ImportError:
    async def safe_send(bot, chat_id, text, **kwargs):
        try:
            return await bot.send_message(
                chat_id=chat_id, text=text, **kwargs
            )
        except Exception as e:
            logging.warning(f"safe_send failed: {e}")
            return None


logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════════════════

_CONFIRMATION_TIMEOUT_SEC = 300          # 5 دقائق
_WEEKLY_REPORT_INTERVAL_SEC = 7 * 86400  # 7 أيام
_WEEKLY_REPORT_INITIAL_DELAY = 3600      # ساعة واحدة


# ═══════════════════════════════════════════════════════════════════
# حالة عامة — المهمة الأسبوعية
# ═══════════════════════════════════════════════════════════════════

_weekly_task: Optional[asyncio.Task] = None


# ═══════════════════════════════════════════════════════════════════
# الصلاحيات
# ═══════════════════════════════════════════════════════════════════

def _is_authorized(user_id: int) -> bool:
    """هل المستخدم مخوَّل بهذه الأوامر؟"""
    try:
        owner_id = int(getattr(CONFIG, 'PRIMARY_OWNER_ID', 0) or 0)
        if owner_id and user_id == owner_id:
            return True
        if hasattr(CONFIG, 'is_developer'):
            try:
                if CONFIG.is_developer(user_id):
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════════════════
# تنظيف التأكيدات القديمة (يمنع تسريب user_data)
# ═══════════════════════════════════════════════════════════════════

def _cleanup_stale_pending(context) -> bool:
    """
    ✅ v1.0.1: يحذف _maint_pending إذا انتهت صلاحيتها.

    Returns:
        True إذا حُذف شيء
    """
    try:
        pending = context.user_data.get('_maint_pending')
        if not pending:
            return False
        age = time.monotonic() - pending.get('created_at', 0)
        if age > _CONFIRMATION_TIMEOUT_SEC:
            context.user_data.pop('_maint_pending', None)
            return True
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════════════════
# /db_diag_quick
# ═══════════════════════════════════════════════════════════════════

async def db_diag_quick_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """🔬 تقرير صحي مختصر."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not _is_authorized(user_id):
        await update.message.reply_text("⛔ غير مصرح.")
        return

    if diagnose_db_quick is None:
        await update.message.reply_text(
            "❌ وحدة db_diagnostics غير محمَّلة."
        )
        return

    try:
        report = await diagnose_db_quick()
        await update.message.reply_text(
            report, parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"db_diag_quick: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                f"❌ فشل التشخيص: {str(e)[:150]}"
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# /db_maintenance
# ═══════════════════════════════════════════════════════════════════

async def db_maintenance_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    🧹 الصيانة.

    استخدام:
      /db_maintenance            → معاينة + طلب تأكيد
      /db_maintenance confirm    → تنفيذ فعلي
      /db_maintenance cancel     → إلغاء
    """
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not _is_authorized(user_id):
        await update.message.reply_text("⛔ غير مصرح.")
        return

    if preview_maintenance is None or run_maintenance is None:
        await update.message.reply_text(
            "❌ وحدة db_diagnostics غير محمَّلة."
        )
        return

    # ✅ v1.0.1: تنظيف أي تأكيد قديم لهذا المستخدم
    _cleanup_stale_pending(context)

    args = context.args or []
    action = args[0].lower() if args else "preview"

    # ═══ PREVIEW ═══
    if action in ("preview", ""):
        try:
            preview = await preview_maintenance()
        except Exception as e:
            logger.error(f"preview_maintenance: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ فشل المعاينة: {str(e)[:150]}"
            )
            return

        try:
            text = format_maintenance_preview(preview)
        except Exception as e:
            logger.error(f"format preview: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ فشل التنسيق: {str(e)[:150]}"
            )
            return

        context.user_data['_maint_pending'] = {
            'user_id': user_id,
            'created_at': time.monotonic(),
            'preview': preview,
        }

        await update.message.reply_text(
            text, parse_mode='HTML'
        )
        return

    # ═══ CONFIRM ═══
    if action == "confirm":
        pending = context.user_data.get('_maint_pending')

        if not pending:
            await update.message.reply_text(
                "❌ لا توجد صيانة معلّقة.\n"
                "شغّل <code>/db_maintenance</code> أولاً.",
                parse_mode='HTML',
            )
            return

        if pending.get('user_id') != user_id:
            await update.message.reply_text(
                "❌ التأكيد من مستخدم مختلف."
            )
            return

        age = time.monotonic() - pending.get('created_at', 0)
        if age > _CONFIRMATION_TIMEOUT_SEC:
            context.user_data.pop('_maint_pending', None)
            await update.message.reply_text(
                f"❌ انتهت مهلة التأكيد "
                f"({_CONFIRMATION_TIMEOUT_SEC // 60} دقيقة).\n"
                f"شغّل <code>/db_maintenance</code> مجدداً.",
                parse_mode='HTML',
            )
            return

        context.user_data.pop('_maint_pending', None)

        # ✅ v1.0.1: حماية status_msg
        status_msg = None
        try:
            status_msg = await update.message.reply_text(
                "⏳ <b>جارٍ تنفيذ الصيانة...</b>\n"
                "قد تستغرق دقائق على قواعد كبيرة.",
                parse_mode='HTML',
            )
        except Exception as e:
            logger.warning(f"send status msg failed: {e}")

        try:
            result = await run_maintenance()
        except Exception as e:
            logger.error(f"run_maintenance: {e}", exc_info=True)
            err_text = f"❌ فشلت الصيانة: {str(e)[:200]}"
            try:
                if status_msg is not None:
                    await status_msg.edit_text(err_text)
                else:
                    await update.message.reply_text(err_text)
            except Exception:
                pass
            return

        try:
            result_text = format_maintenance_result(result)
        except Exception as e:
            logger.error(f"format result: {e}", exc_info=True)
            result_text = (
                f"⚠️ اكتملت الصيانة "
                f"({result.get('duration_sec', 0):.2f}s)"
            )

        try:
            if status_msg is not None:
                await status_msg.edit_text(
                    result_text, parse_mode='HTML'
                )
            else:
                await update.message.reply_text(
                    result_text, parse_mode='HTML'
                )
        except Exception as e:
            logger.warning(f"edit status: {e}")
            try:
                await update.message.reply_text(
                    result_text, parse_mode='HTML'
                )
            except Exception:
                pass

        # سجل للقناة
        try:
            log_ch = await DB.get_dev_log_channel()
            if log_ch:
                await safe_send(
                    context.bot, log_ch,
                    f"🧹 <b>صيانة يدوية</b> "
                    f"(بواسطة <code>{user_id}</code>)\n\n"
                    + result_text,
                    parse_mode='HTML',
                )
        except Exception as e:
            logger.debug(f"log maintenance: {e}")

        return

    # ═══ CANCEL ═══
    if action == "cancel":
        had = context.user_data.pop('_maint_pending', None)
        if had:
            await update.message.reply_text("✅ تم إلغاء الصيانة.")
        else:
            await update.message.reply_text(
                "ℹ️ لا توجد صيانة معلّقة."
            )
        return

    await update.message.reply_text(
        "❌ استخدام غير صحيح.\n\n"
        "<b>الأوامر المتاحة:</b>\n"
        "<code>/db_maintenance</code> — معاينة\n"
        "<code>/db_maintenance confirm</code> — تنفيذ\n"
        "<code>/db_maintenance cancel</code> — إلغاء",
        parse_mode='HTML',
    )


# ═══════════════════════════════════════════════════════════════════
# /db_weekly
# ═══════════════════════════════════════════════════════════════════

async def db_weekly_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """📅 إدارة التقرير الأسبوعي التلقائي."""
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not _is_authorized(user_id):
        await update.message.reply_text("⛔ غير مصرح.")
        return

    args = context.args or []
    action = args[0].lower() if args else "status"

    try:
        current = await DB.get_setting(
            'db_weekly_report_enabled', default='0'
        )
        enabled = str(current).strip() in ('1', 'true', 'yes', 'on')

        if action == "status":
            status = "🟢 مفعّل" if enabled else "🔴 معطّل"
            task_status = ""
            try:
                if _weekly_task is not None and not _weekly_task.done():
                    task_status = "\n⚙️ المهمة الخلفية: 🟢 نشطة"
                else:
                    task_status = "\n⚙️ المهمة الخلفية: 🔴 متوقفة"
            except Exception:
                pass

            await update.message.reply_text(
                f"📅 <b>التقرير الأسبوعي:</b> {status}"
                f"{task_status}\n\n"
                f"لتفعيل/تعطيل:\n"
                f"<code>/db_weekly on</code>\n"
                f"<code>/db_weekly off</code>",
                parse_mode='HTML',
            )
            return

        if action == "on":
            await DB.set_setting('db_weekly_report_enabled', '1')
            await update.message.reply_text(
                "✅ تم تفعيل التقرير الأسبوعي."
            )
            return

        if action == "off":
            await DB.set_setting('db_weekly_report_enabled', '0')
            await update.message.reply_text(
                "🔴 تم تعطيل التقرير الأسبوعي."
            )
            return

        await update.message.reply_text(
            "❌ استخدام: <code>/db_weekly on|off|status</code>",
            parse_mode='HTML',
        )

    except Exception as e:
        logger.error(f"db_weekly: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                f"❌ فشل: {str(e)[:150]}"
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# المهمة الدورية الأسبوعية (long-running)
# ═══════════════════════════════════════════════════════════════════

async def scheduled_weekly_diagnostic(bot):
    """
    📅 مهمة دورية طويلة — ترسل التقرير الأسبوعي إلى قناة السجل.

    - تبدأ بعد ساعة من تشغيل البوت
    - تكرر كل 7 أيام
    - ترسل فقط إذا كان db_weekly_report_enabled = 1
    - fallback إلى المالك إذا لم توجد قناة سجل

    ⚠️ مهم:
        هذه الدالة تحتوي على `while True` — long-running.
        ✅ استخدم `start_weekly_diagnostic_task(application)` لبدئها.
        ❌ لا تستخدم `job_queue.run_repeating` معها (double loop).
    """
    logger.info("📅 جدولة التقرير الأسبوعي: تبدأ بعد ساعة")

    try:
        await asyncio.sleep(_WEEKLY_REPORT_INITIAL_DELAY)
    except asyncio.CancelledError:
        logger.info("⏹️ scheduled_weekly_diagnostic: أُلغي قبل البدء")
        return

    while True:
        try:
            try:
                enabled_raw = await DB.get_setting(
                    'db_weekly_report_enabled', default='0'
                )
                enabled = str(enabled_raw).strip() in (
                    '1', 'true', 'yes', 'on'
                )
            except Exception as e:
                logger.debug(f"weekly setting: {e}")
                enabled = False

            if enabled and diagnose_db_quick is not None:
                target_chat = None
                try:
                    target_chat = await DB.get_dev_log_channel()
                except Exception:
                    pass

                if not target_chat:
                    try:
                        owner = int(
                            getattr(CONFIG, 'PRIMARY_OWNER_ID', 0) or 0
                        )
                        if owner:
                            target_chat = owner
                    except Exception:
                        pass

                if target_chat:
                    try:
                        quick = await diagnose_db_quick()
                        text = (
                            "📅 <b>التقرير الأسبوعي — DB</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                            + quick
                        )
                        await safe_send(
                            bot, target_chat, text,
                            parse_mode='HTML',
                        )
                        logger.info(
                            f"✅ أُرسل التقرير الأسبوعي إلى "
                            f"{target_chat}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"فشل إرسال التقرير الأسبوعي: {e}"
                        )
                else:
                    logger.debug(
                        "لا قناة سجل ولا owner — تخطي التقرير"
                    )

        except asyncio.CancelledError:
            logger.info("⏹️ scheduled_weekly_diagnostic: أُلغي")
            return
        except Exception as e:
            logger.error(
                f"scheduled_weekly_diagnostic: {e}",
                exc_info=True,
            )

        try:
            await asyncio.sleep(_WEEKLY_REPORT_INTERVAL_SEC)
        except asyncio.CancelledError:
            logger.info("⏹️ scheduled_weekly_diagnostic: أُلغي")
            return


# ═══════════════════════════════════════════════════════════════════
# 🆕 v1.0.1: إدارة المهمة الأسبوعية
# ═══════════════════════════════════════════════════════════════════

def start_weekly_diagnostic_task(application) -> bool:
    """
    ✅ v1.0.1: بدء المهمة الأسبوعية كـasyncio background task.

    الطريقة الصحيحة (بدل job_queue.run_repeating).

    Args:
        application: telegram.ext.Application

    Returns:
        True عند النجاح، False عند الفشل
    """
    global _weekly_task

    # إلغاء أي مهمة سابقة
    if _weekly_task is not None and not _weekly_task.done():
        try:
            _weekly_task.cancel()
            logger.info("🔄 إلغاء المهمة الأسبوعية السابقة")
        except Exception as e:
            logger.debug(f"cancel previous weekly task: {e}")

    try:
        bot = getattr(application, 'bot', None)
        if bot is None:
            logger.warning(
                "start_weekly_diagnostic_task: application.bot is None"
            )
            return False

        _weekly_task = asyncio.create_task(
            scheduled_weekly_diagnostic(bot)
        )
        logger.info("✅ Weekly diagnostic task started")
        return True

    except Exception as e:
        logger.error(
            f"start_weekly_diagnostic_task: {e}", exc_info=True
        )
        return False


async def stop_weekly_diagnostic_task(timeout: float = 3.0) -> None:
    """
    ✅ v1.0.1: إيقاف المهمة الأسبوعية بشكل نظيف.

    يُستدعى عند shutdown.

    Args:
        timeout: المهلة القصوى للانتظار (بالثواني)
    """
    global _weekly_task

    if _weekly_task is None or _weekly_task.done():
        return

    try:
        _weekly_task.cancel()
        try:
            await asyncio.wait_for(_weekly_task, timeout=timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        logger.info("🛑 weekly diagnostic task stopped")
    except Exception as e:
        logger.debug(f"stop_weekly_diagnostic_task: {e}")
    finally:
        _weekly_task = None


# ═══════════════════════════════════════════════════════════════════
# التسجيل
# ═══════════════════════════════════════════════════════════════════

def register_maintenance_commands(application) -> bool:
    """
    ✅ v1.0.1: تسجيل الأوامر بشكل مستقل (كل أمر في try/except منفصل).

    Returns:
        True إذا نجح الكل، False إذا فشل أمر واحد على الأقل
    """
    ok_all = True

    try:
        application.add_handler(CommandHandler(
            "db_diag_quick", db_diag_quick_command
        ))
    except Exception as e:
        logger.error(f"❌ register db_diag_quick: {e}", exc_info=True)
        ok_all = False

    try:
        application.add_handler(CommandHandler(
            "db_maintenance", db_maintenance_command
        ))
    except Exception as e:
        logger.error(f"❌ register db_maintenance: {e}", exc_info=True)
        ok_all = False

    try:
        application.add_handler(CommandHandler(
            "db_weekly", db_weekly_command
        ))
    except Exception as e:
        logger.error(f"❌ register db_weekly: {e}", exc_info=True)
        ok_all = False

    if ok_all:
        logger.info(
            "✅ Maintenance commands registered: "
            "/db_diag_quick, /db_maintenance, /db_weekly"
        )
    else:
        logger.warning(
            "⚠️ بعض أوامر الصيانة فشلت في التسجيل"
        )

    return ok_all


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

__all__ = [
    "db_diag_quick_command",
    "db_maintenance_command",
    "db_weekly_command",
    "scheduled_weekly_diagnostic",
    "start_weekly_diagnostic_task",
    "stop_weekly_diagnostic_task",
    "register_maintenance_commands",
]