#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_maintenance_commands.py - أوامر صيانة قاعدة البيانات (v1.1.0)
================================================================================
🆕 v1.1.0 — التنظيف التلقائي الكامل:
    🟢 AUTO-1: مهمة خلفية auto_vacuum_dirty_mvs تعمل تلقائياً.
    🟢 AUTO-2: تُصلح dead tuples على MVs (mv_active_user_limits...).
    🟢 AUTO-3: تفعيل/تعطيل عبر /db_weekly auto_on|auto_off.
    🟢 AUTO-4: تشغيل فوري عبر /db_weekly auto_now.
    🟢 AUTO-5: حالة كل المهام عبر /db_weekly status.

📋 الأوامر:
  /db_diag_quick   — تقرير صحي مختصر
  /db_maintenance  — معاينة + تنفيذ يدوي
  /db_weekly       — التقرير الأسبوعي + التنظيف التلقائي

⚠️ الاعتماديات:
    • db_diagnostics >= v6.9.4
      (يوفّر: auto_vacuum_dirty_mvs + سياسة تنظيف آمنة)
    • config.CONFIG.PRIMARY_OWNER_ID أو CONFIG.is_developer

⚠️ الصلاحيات:
    كل الأوامر تتطلب PRIMARY_OWNER_ID أو is_developer.
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


# ═══════════════════════════════════════════════════════════════════
# استيراد db_diagnostics — مع تحقق من الإصدار
# ═══════════════════════════════════════════════════════════════════

_DB_DIAGNOSTICS_VERSION = "0.0.0"
_DB_DIAGNOSTICS_MIN_VERSION = (6, 9, 4)

logger = logging.getLogger(__name__)

try:
    from db_diagnostics import (
        diagnose_db_quick,
        preview_maintenance,
        run_maintenance,
        format_maintenance_preview,
        format_maintenance_result,
        auto_vacuum_dirty_mvs,
    )

    try:
        from db_diagnostics import VERSION as _DB_DIAGNOSTICS_VERSION
    except ImportError:
        _DB_DIAGNOSTICS_VERSION = "unknown"

    def _parse_version(v):
        try:
            return tuple(int(x) for x in str(v).split("."))
        except Exception:
            return (0, 0, 0)

    _parsed = _parse_version(_DB_DIAGNOSTICS_VERSION)
    if _parsed < _DB_DIAGNOSTICS_MIN_VERSION:
        logger.warning(
            f"⚠️ db_diagnostics الإصدار {_DB_DIAGNOSTICS_VERSION} "
            f"أقدم من المطلوب "
            f"{'.'.join(map(str, _DB_DIAGNOSTICS_MIN_VERSION))} — "
            f"قد لا تعمل ميزة auto_vacuum. الرجاء ترقية db_diagnostics.py."
        )

except ImportError as _imp_err:
    logger.error(
        f"❌ db_maintenance_commands: فشل استيراد db_diagnostics: {_imp_err}"
    )
    diagnose_db_quick = None
    preview_maintenance = None
    run_maintenance = None
    format_maintenance_preview = None
    format_maintenance_result = None
    auto_vacuum_dirty_mvs = None
    _DB_DIAGNOSTICS_VERSION = "missing"


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


# ═══════════════════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════════════════

_CONFIRMATION_TIMEOUT_SEC = 300
_WEEKLY_REPORT_INTERVAL_SEC = 7 * 86400
_WEEKLY_REPORT_INITIAL_DELAY = 3600

# 🆕 v1.1.0 — التنظيف التلقائي
_AUTO_VACUUM_INTERVAL_SEC = 30 * 60      # كل 30 دقيقة
_AUTO_VACUUM_INITIAL_DELAY = 120         # أول تشغيل بعد دقيقتين
_AUTO_VACUUM_MIN_DEAD = 10               # الحد الأدنى للتنظيف


# ═══════════════════════════════════════════════════════════════════
# حالة عامة
# ═══════════════════════════════════════════════════════════════════

_weekly_task: Optional[asyncio.Task] = None
_auto_vacuum_task: Optional[asyncio.Task] = None


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
# أدوات مساعدة
# ═══════════════════════════════════════════════════════════════════

def _cleanup_stale_pending(context) -> bool:
    """يحذف أي pending قديم تجاوز مهلة التأكيد."""
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


def _preview_has_errors(preview) -> bool:
    """هل فشلت أي استعلامات عدّ؟"""
    try:
        if not preview or not isinstance(preview, dict):
            return False
        plan = preview.get('plan', [])
        for item in plan:
            if not isinstance(item, dict):
                continue
            if item.get('count') == -1:
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
    """🔬 تقرير صحي مختصر (4-5 أسطر)."""
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
    🧹 الصيانة اليدوية.

    الاستخدام:
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

    _cleanup_stale_pending(context)

    args = context.args or []
    action = args[0].lower() if args else "preview"

    # ═══════════ PREVIEW ═══════════
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

        if _preview_has_errors(preview):
            text += (
                "\n\n⚠️ <b>تحذير:</b> بعض استعلامات العدّ فشلت.\n"
                "💡 تحقق من أسماء الأعمدة في الجداول."
            )

        context.user_data['_maint_pending'] = {
            'user_id': user_id,
            'created_at': time.monotonic(),
            'preview': preview,
        }

        await update.message.reply_text(
            text, parse_mode='HTML'
        )
        return

    # ═══════════ CONFIRM ═══════════
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

        # سجل في قناة المطور
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

    # ═══════════ CANCEL ═══════════
    if action == "cancel":
        had = context.user_data.pop('_maint_pending', None)
        if had:
            await update.message.reply_text("✅ تم إلغاء الصيانة.")
        else:
            await update.message.reply_text(
                "ℹ️ لا توجد صيانة معلّقة."
            )
        return

    # ═══════════ استخدام غير صحيح ═══════════
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
    """
    📅 إدارة التقرير الأسبوعي + التنظيف التلقائي.

    الاستخدام:
      /db_weekly status      — عرض حالة كل المهام
      /db_weekly on          — تفعيل التقرير الأسبوعي
      /db_weekly off         — تعطيله
      /db_weekly auto_on     — تفعيل التنظيف التلقائي
      /db_weekly auto_off    — تعطيله
      /db_weekly auto_now    — تشغيل التنظيف فوراً
    """
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not _is_authorized(user_id):
        await update.message.reply_text("⛔ غير مصرح.")
        return

    args = context.args or []
    action = args[0].lower() if args else "status"

    try:
        # ═══════════ STATUS ═══════════
        if action == "status":
            weekly_raw = await DB.get_setting(
                'db_weekly_report_enabled', default='0'
            )
            weekly_enabled = str(weekly_raw).strip() in (
                '1', 'true', 'yes', 'on'
            )

            auto_raw = await DB.get_setting(
                'db_auto_vacuum_enabled', default='1'
            )
            auto_enabled = str(auto_raw).strip() in (
                '1', 'true', 'yes', 'on'
            )

            # حالة المهام
            weekly_running = (
                _weekly_task is not None
                and not _weekly_task.done()
            )
            auto_running = (
                _auto_vacuum_task is not None
                and not _auto_vacuum_task.done()
            )

            text = (
                "📅 <b>حالة المهام الدورية</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 <b>التقرير الأسبوعي:</b> "
                f"{'🟢 مفعّل' if weekly_enabled else '🔴 معطّل'}\n"
                f"⚙️ المهمة: "
                f"{'🟢 نشطة' if weekly_running else '🔴 متوقفة'}\n"
                f"⏱️ الدورة: كل 7 أيام\n\n"
                f"🧹 <b>التنظيف التلقائي:</b> "
                f"{'🟢 مفعّل' if auto_enabled else '🔴 معطّل'}\n"
                f"⚙️ المهمة: "
                f"{'🟢 نشطة' if auto_running else '🔴 متوقفة'}\n"
                f"⏱️ الدورة: كل "
                f"{_AUTO_VACUUM_INTERVAL_SEC // 60} دقيقة\n"
                f"🎯 الحد الأدنى: {_AUTO_VACUUM_MIN_DEAD} dead tuples\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>أوامر التحكم:</b>\n"
                f"<code>/db_weekly on|off</code> — التقرير الأسبوعي\n"
                f"<code>/db_weekly auto_on|auto_off</code> — التنظيف\n"
                f"<code>/db_weekly auto_now</code> — تنظيف فوري"
            )

            await update.message.reply_text(
                text, parse_mode='HTML'
            )
            return

        # ═══════════ WEEKLY ON/OFF ═══════════
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

        # ═══════════ AUTO_VACUUM ON/OFF ═══════════
        if action == "auto_on":
            await DB.set_setting('db_auto_vacuum_enabled', '1')
            await update.message.reply_text(
                "✅ تم تفعيل التنظيف التلقائي.\n"
                f"⏱️ سيعمل كل {_AUTO_VACUUM_INTERVAL_SEC // 60} دقيقة."
            )
            return

        if action == "auto_off":
            await DB.set_setting('db_auto_vacuum_enabled', '0')
            await update.message.reply_text(
                "🔴 تم تعطيل التنظيف التلقائي."
            )
            return

        # ═══════════ AUTO_NOW (تشغيل فوري) ═══════════
        if action == "auto_now":
            if auto_vacuum_dirty_mvs is None:
                await update.message.reply_text(
                    "❌ auto_vacuum_dirty_mvs غير متوفر.\n"
                    "تأكد من db_diagnostics v6.9.4+."
                )
                return

            await update.message.reply_text(
                "⏳ <b>جارٍ التنظيف الفوري...</b>",
                parse_mode='HTML',
            )

            try:
                result = await auto_vacuum_dirty_mvs(
                    min_dead=_AUTO_VACUUM_MIN_DEAD
                )
            except Exception as e:
                logger.error(f"auto_now: {e}", exc_info=True)
                await update.message.reply_text(
                    f"❌ فشل التنظيف: {str(e)[:150]}"
                )
                return

            # بناء التقرير
            cleaned = result.get('cleaned', 0)
            before = result.get('total_dead_before', 0)
            after = result.get('total_dead_after', 0)
            duration = result.get('duration_sec', 0)

            text = (
                "🧹 <b>التنظيف الفوري</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 <b>النتيجة:</b>\n"
                f"  💀 dead قبل: <b>{before}</b>\n"
                f"  💀 dead بعد: <b>{after}</b>\n"
                f"  ✅ نُظِّف: <b>{cleaned}</b>\n"
                f"  ⏱️ المدة: <b>{duration:.2f}s</b>\n"
            )

            vacuumed = result.get('vacuumed', [])
            if vacuumed:
                text += "\n<b>التفاصيل:</b>\n"
                for v in vacuumed[:10]:
                    mv_tag = " <code>[MV]</code>" if v.get('is_matview') else ""
                    text += (
                        f"  ✅ <code>{v['name']}</code>{mv_tag} "
                        f"(dead={v['dead_before']})\n"
                    )
                if len(vacuumed) > 10:
                    text += f"  … و{len(vacuumed) - 10} آخر\n"

            failed = result.get('failed', [])
            if failed:
                text += f"\n❌ <b>فشل:</b> {len(failed)}\n"
                for f in failed[:5]:
                    text += (
                        f"  ❌ <code>{f['name']}</code> — "
                        f"<i>{f.get('error', '?')[:60]}</i>\n"
                    )

            if cleaned == 0 and before == 0:
                text += (
                    "\n✨ <i>القاعدة نظيفة — لا شيء للتنظيف.</i>"
                )

            await update.message.reply_text(
                text, parse_mode='HTML'
            )
            return

        # ═══════════ استخدام غير صحيح ═══════════
        await update.message.reply_text(
            "❌ استخدام غير صحيح.\n\n"
            "<b>الأوامر المتاحة:</b>\n"
            "<code>/db_weekly status</code>\n"
            "<code>/db_weekly on|off</code>\n"
            "<code>/db_weekly auto_on|auto_off</code>\n"
            "<code>/db_weekly auto_now</code>",
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
# 🆕 v1.1.0 — المهمة الدورية: التقرير الأسبوعي
# ═══════════════════════════════════════════════════════════════════

async def scheduled_weekly_diagnostic(bot):
    """📅 مهمة دورية — ترسل التقرير الأسبوعي."""
    logger.info(
        "📅 scheduled_weekly_diagnostic: يبدأ بعد "
        f"{_WEEKLY_REPORT_INITIAL_DELAY}s"
    )

    try:
        await asyncio.sleep(_WEEKLY_REPORT_INITIAL_DELAY)
    except asyncio.CancelledError:
        logger.info("⏹️ scheduled_weekly_diagnostic: أُلغي قبل البدء")
        return

    while True:
        try:
            enabled_raw = await DB.get_setting(
                'db_weekly_report_enabled', default='0'
            )
            enabled = str(enabled_raw).strip() in (
                '1', 'true', 'yes', 'on'
            )

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
                            f"✅ أُرسل التقرير الأسبوعي إلى {target_chat}"
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
                f"scheduled_weekly_diagnostic: {e}", exc_info=True
            )

        try:
            await asyncio.sleep(_WEEKLY_REPORT_INTERVAL_SEC)
        except asyncio.CancelledError:
            logger.info("⏹️ scheduled_weekly_diagnostic: أُلغي")
            return


# ═══════════════════════════════════════════════════════════════════
# 🆕 v1.1.0 — المهمة الدورية: التنظيف التلقائي
# ═══════════════════════════════════════════════════════════════════

async def scheduled_auto_vacuum(bot):
    """
    🧹 تنظيف تلقائي دوري.
    يعمل كل 30 دقيقة على MVs والجداول التي فيها
    dead_tuples >= _AUTO_VACUUM_MIN_DEAD.
    """
    logger.info(
        f"🧹 auto-vacuum scheduler started | "
        f"interval={_AUTO_VACUUM_INTERVAL_SEC}s | "
        f"initial_delay={_AUTO_VACUUM_INITIAL_DELAY}s | "
        f"min_dead={_AUTO_VACUUM_MIN_DEAD}"
    )

    try:
        await asyncio.sleep(_AUTO_VACUUM_INITIAL_DELAY)
    except asyncio.CancelledError:
        logger.info("⏹️ scheduled_auto_vacuum: أُلغي قبل البدء")
        return

    while True:
        try:
            # هل الميزة مفعّلة؟
            enabled = True
            try:
                raw = await DB.get_setting(
                    'db_auto_vacuum_enabled', default='1'
                )
                enabled = str(raw).strip() in (
                    '1', 'true', 'yes', 'on'
                )
            except Exception as e:
                logger.debug(f"auto_vacuum setting: {e}")

            if enabled and auto_vacuum_dirty_mvs is not None:
                try:
                    result = await auto_vacuum_dirty_mvs(
                        min_dead=_AUTO_VACUUM_MIN_DEAD
                    )
                    cleaned = result.get('cleaned', 0)
                    before = result.get('total_dead_before', 0)
                    after = result.get('total_dead_after', 0)

                    if cleaned > 0:
                        logger.info(
                            f"🧹 auto-vacuum: cleaned={cleaned} | "
                            f"dead {before} → {after}"
                        )

                        # إشعار اختياري بقناة المطور
                        try:
                            log_ch = await DB.get_dev_log_channel()
                            if log_ch and cleaned >= 3:
                                vacuumed = result.get('vacuumed', [])
                                details = "\n".join(
                                    f"  • <code>{v['name']}</code>"
                                    + (" <code>[MV]</code>"
                                       if v.get('is_matview') else "")
                                    for v in vacuumed[:5]
                                )
                                await safe_send(
                                    bot, log_ch,
                                    f"🧹 <b>تنظيف تلقائي</b>\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"✅ نُظِّف: <b>{cleaned}</b>\n"
                                    f"💀 dead: <b>{before}</b> → "
                                    f"<b>{after}</b>\n\n"
                                    f"{details}",
                                    parse_mode='HTML',
                                )
                        except Exception as e:
                            logger.debug(f"auto-vacuum notify: {e}")

                except Exception as e:
                    logger.warning(
                        f"auto_vacuum run failed: {e}",
                        exc_info=True,
                    )

        except asyncio.CancelledError:
            logger.info("⏹️ scheduled_auto_vacuum: أُلغي")
            return
        except Exception as e:
            logger.error(
                f"scheduled_auto_vacuum: {e}", exc_info=True
            )

        try:
            await asyncio.sleep(_AUTO_VACUUM_INTERVAL_SEC)
        except asyncio.CancelledError:
            logger.info("⏹️ scheduled_auto_vacuum: أُلغي")
            return


# ═══════════════════════════════════════════════════════════════════
# إدارة المهام
# ═══════════════════════════════════════════════════════════════════

def start_weekly_diagnostic_task(application) -> bool:
    """✅ بدء المهمة الأسبوعية."""
    global _weekly_task

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
    """✅ إيقاف المهمة الأسبوعية."""
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


def start_auto_vacuum_task(application) -> bool:
    """✅ بدء مهمة التنظيف التلقائي."""
    global _auto_vacuum_task

    if _auto_vacuum_task is not None and not _auto_vacuum_task.done():
        try:
            _auto_vacuum_task.cancel()
            logger.info("🔄 إلغاء مهمة التنظيف السابقة")
        except Exception as e:
            logger.debug(f"cancel previous auto_vacuum task: {e}")

    try:
        bot = getattr(application, 'bot', None)
        if bot is None:
            logger.warning(
                "start_auto_vacuum_task: application.bot is None"
            )
            return False

        _auto_vacuum_task = asyncio.create_task(
            scheduled_auto_vacuum(bot)
        )
        logger.info("✅ Auto-vacuum task started")
        return True

    except Exception as e:
        logger.error(
            f"start_auto_vacuum_task: {e}", exc_info=True
        )
        return False


async def stop_auto_vacuum_task(timeout: float = 3.0) -> None:
    """✅ إيقاف مهمة التنظيف."""
    global _auto_vacuum_task

    if _auto_vacuum_task is None or _auto_vacuum_task.done():
        return

    try:
        _auto_vacuum_task.cancel()
        try:
            await asyncio.wait_for(_auto_vacuum_task, timeout=timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        logger.info("🛑 auto-vacuum task stopped")
    except Exception as e:
        logger.debug(f"stop_auto_vacuum_task: {e}")
    finally:
        _auto_vacuum_task = None


# ═══════════════════════════════════════════════════════════════════
# 🆕 v1.1.0 — التسجيل الرئيسي
# ═══════════════════════════════════════════════════════════════════

def register_maintenance_commands(application) -> bool:
    """
    ✅ v1.1.0: تسجيل الأوامر + بدء مهمة التنظيف التلقائي.

    كل أمر في try/except منفصل — إذا فشل أمر، الآخرون يُسجَّلون.
    """
    ok_all = True

    # ═══════════ تسجيل الأوامر ═══════════
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

    # ═══════════ بدء المهام الدورية ═══════════
    # 1) المهمة الأسبوعية
    try:
        started = start_weekly_diagnostic_task(application)
        if not started:
            logger.warning(
                "⚠️ فشل بدء المهمة الأسبوعية"
            )
    except Exception as e:
        logger.error(f"weekly startup: {e}", exc_info=True)

    # 2) التنظيف التلقائي (فقط إذا auto_vacuum متوفر)
    try:
        if auto_vacuum_dirty_mvs is not None:
            started = start_auto_vacuum_task(application)
            if started:
                logger.info(
                    f"✅ Auto-vacuum scheduler registered "
                    f"(every {_AUTO_VACUUM_INTERVAL_SEC // 60} min)"
                )
            else:
                logger.warning(
                    "⚠️ فشل بدء مهمة التنظيف التلقائي"
                )
        else:
            logger.warning(
                "⚠️ auto_vacuum_dirty_mvs غير متوفر — "
                "تأكد من db_diagnostics >= v6.9.4"
            )
    except Exception as e:
        logger.error(f"auto_vacuum startup: {e}", exc_info=True)

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
# Aliases (لأي اسم يستورده main.py)
# ═══════════════════════════════════════════════════════════════════

register = register_maintenance_commands
register_commands = register_maintenance_commands
setup_commands = register_maintenance_commands
setup = register_maintenance_commands
register_maintenance = register_maintenance_commands
register_db_maintenance = register_maintenance_commands


# ═══════════════════════════════════════════════════════════════════
# __all__
# ═══════════════════════════════════════════════════════════════════

__all__ = [
    # الأوامر
    "db_diag_quick_command",
    "db_maintenance_command",
    "db_weekly_command",
    # المهمة الأسبوعية
    "scheduled_weekly_diagnostic",
    "start_weekly_diagnostic_task",
    "stop_weekly_diagnostic_task",
    # 🆕 v1.1.0: التنظيف التلقائي
    "scheduled_auto_vacuum",
    "start_auto_vacuum_task",
    "stop_auto_vacuum_task",
    # التسجيل (الرئيسي + aliases)
    "register_maintenance_commands",
    "register",
    "register_commands",
    "setup_commands",
    "setup",
    "register_maintenance",
    "register_db_maintenance",
]


# ═══════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═══════════════════════════════════════════════════════════════════

try:
    logger.info(
        "🛡️ db_maintenance_commands.py v1.1.0 loaded | "
        "commands: /db_diag_quick, /db_maintenance, /db_weekly | "
        "auto-vacuum: ✅ every %d min | "
        "db_diagnostics=%s",
        _AUTO_VACUUM_INTERVAL_SEC // 60,
        _DB_DIAGNOSTICS_VERSION,
    )
except Exception:
    pass