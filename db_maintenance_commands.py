#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_maintenance_commands.py - أوامر صيانة قاعدة البيانات (v1.1.5)
================================================================================
🆕 v1.1.5 — SAFETY-FIXES-AUDIT (7 إصلاحات فوق v1.1.4):

    🟠 FIX-AM27 (IMPORTANT): تتبّع startup auto-tuning task
        السبب: _init_autovacuum_tuning_at_startup() كان يُنشأ عبر
        asyncio.create_task() بدون تتبّع — task leak عند الإغلاق
        واستثناءات مدفونة. الآن:
          • _startup_tune_task global
          • add_done_callback لتسجيل النتيجة
          • إلغاء في stop_auto_vacuum_task
          • لا يُنشأ مرتين (idempotent)

    🟠 FIX-AM28 (IMPORTANT): AUTO_TUNING_RECYCLE_CYCLES = max(1, ...)
        السبب: إذا env='0' → counter=1 < 0 خطأ → الضبط يعمل كل
        دورة (30 دقيقة) بدل 6 ساعات. الآن القيمة الدنيا = 1.

    🟠 FIX-AM29 (IMPORTANT): idempotent register يُعيد بدء المهام
        السبب: بعد stop_weekly_diagnostic_task / stop_auto_vacuum_task
        ثم register_maintenance_commands مرة أخرى، كان يرى
        _commands_registered=True → يتخطى → لا يُعيد بدء المهام
        → المهمة متوقفة نهائياً. الآن:
          • إذا كانت المهمة متوقفة → يُعيد بدءها
          • بدون إعادة تسجيل الأوامر

    🟡 FIX-AM30 (MINOR): _maybe_run_auto_tuning يُصفّر العداد عند التعطيل
        السبب: إذا عُطِّل ثم فُعِّل، عداد قديم >= N → تنفيذ فوري
        بدل الانتظار. الآن: تصفير العداد عند التعطيل.

    🟡 FIX-AM31 (MINOR): /db_weekly auto_now — فحص unit قبل DB type
        السبب: إذا auto_vacuum_dirty_mvs=None، كان يُظهر
        "PG فقط" بدلاً من "الوحدة غير متوفرة".

    🟡 FIX-AM32 (MINOR): عرض "غير مثبت" بدل "unknown" في status
        السبب: UX — "الحالي: unknown" قبيح.

    🟡 FIX-AM33 (MINOR): /db_weekly status يُظهر startup_tune state
        السبب: بعد FIX-AM27، صار لدينا task إضافي — يجب عرض حالته.

    ✅ محفوظ من v1.1.4:
        FIX-AM20..AM26 (auto-tuning integration)
    ✅ محفوظ من v1.1.3 / v1.1.2 / v1.1.1 / v1.1.0:
        كل التحسينات السابقة.

📋 الأوامر:
  /db_diag_quick   — تقرير صحي مختصر
  /db_maintenance  — معاينة + تنفيذ يدوي
  /db_weekly       — التقرير الأسبوعي + التنظيف التلقائي + الضبط
  /db_tune         — ضبط autovacuum يدوي فوري

⚠️ الاعتماديات:
    • db_diagnostics >= v7.2.24 (لـ /db_tune والضبط التلقائي)
    • db_diagnostics >= v7.2.23 (لـ skipped/remaining/dead_after/is_mv)
    • النسخ الأقدم تعمل لكن بدون الميزات الجديدة.

⚠️ الصلاحيات:
    كل الأوامر تتطلب PRIMARY_OWNER_ID أو is_developer.

⚠️ FIX-AM1 (v1.1.1) — نقاط إيقاف إلزامية:
    عند إغلاق التطبيق، يجب على bot.py استدعاء:
      1) stop_weekly_diagnostic_task(timeout=3.0)
      2) stop_auto_vacuum_task(timeout=3.0)
    (الأخير يُلغي الآن أيضاً startup_tune_task — FIX-AM27)
================================================================================
"""

__version__ = "1.1.5"

import os
import asyncio
import logging
import time
import html as _html_mod
from typing import Optional, Dict, Any, List

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from config import CONFIG
from database import DB


# ═══════════════════════════════════════════════════════════════════
# استيراد db_diagnostics — مع تحقق من الإصدار
# ═══════════════════════════════════════════════════════════════════

_DB_DIAGNOSTICS_VERSION = "0.0.0"
_DB_DIAGNOSTICS_MIN_VERSION = (6, 9, 4)
_VERSION_OK = False

logger = logging.getLogger(__name__)


def _parse_version(v) -> tuple:
    """
    يستخرج الأرقام حتى مع suffixes
    (7.2.6-rc1 → (7, 2, 6)؛ 7.2.6.dev0 → (7, 2, 6)).
    """
    try:
        out = []
        for part in str(v).split("."):
            digits = "".join(c for c in part if c.isdigit())
            if digits:
                out.append(int(digits))
            else:
                out.append(0)
        return tuple(out) if out else (0, 0, 0)
    except Exception:
        return (0, 0, 0)


def _format_version_display(v: str) -> str:
    """🟡 v1.1.5 FIX-AM32: عرض 'غير مثبت' بدل 'unknown'."""
    if v in ("unknown", "missing", "0.0.0", None, ""):
        return "غير مثبت"
    return str(v)


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

    _parsed = _parse_version(_DB_DIAGNOSTICS_VERSION)
    _VERSION_OK = _parsed >= _DB_DIAGNOSTICS_MIN_VERSION

    if not _VERSION_OK:
        logger.warning(
            f"⚠️ db_diagnostics الإصدار {_DB_DIAGNOSTICS_VERSION} "
            f"أقدم من المطلوب "
            f"{'.'.join(map(str, _DB_DIAGNOSTICS_MIN_VERSION))} — "
            f"سيُعطَّل التنظيف التلقائي. الرجاء ترقية db_diagnostics.py."
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
    _VERSION_OK = False


# استيراد دوال الضبط التلقائي (v7.2.24+) — مع fallback آمن
_AUTO_TUNING_AVAILABLE = False
try:
    from db_diagnostics import (
        ensure_autovacuum_tuning,
        init_autovacuum_tuning,
        diagnose_autovacuum_tuning,
        format_autovacuum_tuning,
    )
    _AUTO_TUNING_AVAILABLE = True
except ImportError:
    ensure_autovacuum_tuning = None
    init_autovacuum_tuning = None
    diagnose_autovacuum_tuning = None
    format_autovacuum_tuning = None
    logger.info(
        "ℹ️ db_diagnostics < v7.2.24 — ميزة /db_tune والضبط التلقائي معطّلة "
        "(يمكن ترقية db_diagnostics لتفعيلها)."
    )


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

# التنظيف التلقائي
_AUTO_VACUUM_INTERVAL_SEC = 30 * 60      # كل 30 دقيقة
_AUTO_VACUUM_INITIAL_DELAY = 120         # أول تشغيل بعد دقيقتين

# من env
_AUTO_VACUUM_MIN_DEAD = int(
    os.getenv("AUTO_VACUUM_MIN_DEAD", "10")
)

# ثابت موثّق
_AUTO_VACUUM_NOTIFY_MIN_CLEANED = 3

# 🟠 v1.1.5 FIX-AM28: max(1, ...) — لا يسمح بـ 0
_AUTO_TUNING_RECYCLE_CYCLES = max(1, int(
    os.getenv("AUTO_TUNING_RECYCLE_CYCLES", "12")
))

# idempotency
_commands_registered = False
_auto_vacuum_previous_state: Optional[bool] = None
_auto_tune_previous_state: Optional[bool] = None
_auto_tuning_cycle_counter = 0


# ═══════════════════════════════════════════════════════════════════
# حالة عامة
# ═══════════════════════════════════════════════════════════════════

_weekly_task: Optional[asyncio.Task] = None
_auto_vacuum_task: Optional[asyncio.Task] = None
# 🟠 v1.1.5 FIX-AM27: تتبّع startup auto-tuning task
_startup_tune_task: Optional[asyncio.Task] = None


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

def _esc(text: Any) -> str:
    """HTML escape آمن."""
    try:
        if text is None:
            return ""
        return _html_mod.escape(str(text))
    except Exception:
        return ""


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


def _is_postgres() -> bool:
    """فحص موحّد لنوع DB."""
    try:
        return bool(getattr(DB, "USE_POSTGRES", False))
    except Exception:
        return False


def _is_db_closing() -> bool:
    """هل DB في حالة إغلاق؟"""
    try:
        return bool(
            getattr(DB, "_closing", False)
            or getattr(DB, "_closed", False)
        )
    except Exception:
        return False


def _is_task_alive(task: Optional[asyncio.Task]) -> bool:
    """🆕 v1.1.5: فحص موحّد لحالة task."""
    return task is not None and not task.done()


def get_tasks_status() -> Dict[str, Any]:
    """
    حالة المهام الدورية للتشخيص.
    🟡 v1.1.5 FIX-AM33: أضيف startup_tune_running + version_display.
    """
    return {
        "weekly_running": _is_task_alive(_weekly_task),
        "auto_vacuum_running": _is_task_alive(_auto_vacuum_task),
        # 🟡 v1.1.5 FIX-AM33
        "startup_tune_running": _is_task_alive(_startup_tune_task),
        "commands_registered": _commands_registered,
        "db_diagnostics_version": _DB_DIAGNOSTICS_VERSION,
        "db_diagnostics_version_display": _format_version_display(
            _DB_DIAGNOSTICS_VERSION
        ),
        "db_diagnostics_version_ok": _VERSION_OK,
        "is_postgres": _is_postgres(),
        "auto_vacuum_min_dead": _AUTO_VACUUM_MIN_DEAD,
        "auto_vacuum_interval_sec": _AUTO_VACUUM_INTERVAL_SEC,
        "auto_tuning_available": _AUTO_TUNING_AVAILABLE,
        "auto_tuning_recycle_cycles": _AUTO_TUNING_RECYCLE_CYCLES,
        "auto_tuning_cycle_counter": _auto_tuning_cycle_counter,
    }


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
                f"❌ فشل التشخيص: {_esc(str(e)[:150])}"
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# /db_tune
# ═══════════════════════════════════════════════════════════════════

async def db_tune_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    ⚙️ ضبط autovacuum يدوي فوري على كل الجداول المعروفة + التلقائية.
    مكافئ لـ `/db_weekly tune_now` لكن مستقل.
    """
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not _is_authorized(user_id):
        await update.message.reply_text("⛔ غير مصرح.")
        return

    if not _AUTO_TUNING_AVAILABLE or diagnose_autovacuum_tuning is None:
        await update.message.reply_text(
            "❌ /db_tune يتطلب db_diagnostics >= v7.2.24.\n"
            f"الإصدار الحالي: "
            f"<code>{_esc(_format_version_display(_DB_DIAGNOSTICS_VERSION))}"
            f"</code>",
            parse_mode='HTML',
        )
        return

    if not _is_postgres():
        await update.message.reply_text(
            "⚠️ الضبط التلقائي يعمل فقط على PostgreSQL."
        )
        return

    try:
        text = await diagnose_autovacuum_tuning(force=True)
        await update.message.reply_text(text, parse_mode='HTML')
    except Exception as e:
        logger.error(f"db_tune: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                f"❌ فشل الضبط: {_esc(str(e)[:150])}"
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
                f"❌ فشل المعاينة: {_esc(str(e)[:150])}"
            )
            return

        try:
            text = format_maintenance_preview(preview)
        except Exception as e:
            logger.error(f"format preview: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ فشل التنسيق: {_esc(str(e)[:150])}"
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
            err_text = f"❌ فشلت الصيانة: {_esc(str(e)[:200])}"
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

def _build_auto_now_report(result: Dict[str, Any]) -> str:
    """
    بناء تقرير auto_now مع التفاصيل الكاملة.

    يتعامل مع كلا الحالتين:
      • db_diagnostics v7.2.23+ → skipped/remaining/dead_after موجودة
      • db_diagnostics أقدم → الحقول غائبة (نتخطاها بأمان)
    """
    cleaned  = int(result.get('cleaned', 0) or 0)
    before   = int(result.get('total_dead_before', 0) or 0)
    after_raw = result.get('total_dead_after', None)
    after_display = (
        str(int(after_raw)) if isinstance(after_raw, (int, float))
        else "?"
    )
    duration = float(result.get('duration_sec', 0) or 0)

    text = (
        "🧹 <b>التنظيف الفوري</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>النتيجة:</b>\n"
        f"  💀 dead قبل: <b>{before}</b>\n"
        f"  💀 dead بعد: <b>{after_display}</b>\n"
        f"  ✅ نُظِّف: <b>{cleaned}</b>\n"
        f"  ⏱️ المدة: <b>{duration:.2f}s</b>\n"
    )

    # ═══ ✅ ما تم تنظيفه ═══
    vacuumed = result.get('vacuumed', []) or []
    if vacuumed:
        text += "\n<b>✅ ما تم تنظيفه:</b>\n"
        for v in vacuumed[:15]:
            name = _esc(v.get('name', '?'))
            mv_tag = " <code>[MV]</code>" if v.get('is_mv') else ""
            db_  = v.get('dead_before', 0)
            da_  = v.get('dead_after', '?')
            da_str = str(da_) if da_ != '?' else "?"
            text += (
                f"  ✅ <code>{name}</code>{mv_tag} "
                f"— dead {db_} → {da_str}\n"
            )
        if len(vacuumed) > 15:
            text += f"  … و{len(vacuumed) - 15} آخر\n"

    # ═══ 💀 ما تبقّى في القاعدة ═══
    remaining = result.get('remaining', []) or []
    skipped   = result.get('skipped', []) or []

    seen_names = {r.get('name') for r in remaining if r.get('name')}
    all_rem: List[Dict[str, Any]] = []

    for r in remaining:
        all_rem.append({
            'name': r.get('name', '?'),
            'dead': int(r.get('dead', 0) or 0),
            'ratio_pct': float(r.get('ratio_pct', 0) or 0),
            'is_mv': bool(r.get('is_mv', False)),
            'note': '',
        })

    for s in skipped:
        name = s.get('name')
        if not name or name in seen_names:
            continue
        all_rem.append({
            'name': name,
            'dead': int(s.get('dead', 0) or 0),
            'ratio_pct': 0.0,
            'is_mv': bool(s.get('is_mv', False)),
            'note': f" (dead<{_AUTO_VACUUM_MIN_DEAD}، تُرك)",
        })

    if all_rem:
        all_rem.sort(key=lambda x: -x['dead'])
        text += "\n<b>💀 ما تبقّى في القاعدة:</b>\n"
        for r in all_rem[:15]:
            name = _esc(r['name'])
            mv_tag = " <code>[MV]</code>" if r.get('is_mv') else ""
            pct = r.get('ratio_pct', 0)
            pct_str = f" ({pct:.2f}%)" if pct and pct > 0 else ""
            text += (
                f"  • <code>{name}</code>{mv_tag} — "
                f"dead={r['dead']}{pct_str}{r.get('note', '')}\n"
            )
        if len(all_rem) > 15:
            text += f"  … و{len(all_rem) - 15} آخر\n"

    # ═══ ❌ فشل ═══
    failed = result.get('failed', []) or []
    if failed:
        text += f"\n❌ <b>فشل ({len(failed)}):</b>\n"
        for f in failed[:5]:
            name = _esc(f.get('name', '?'))
            err  = _esc(str(f.get('error', '?'))[:60])
            text += f"  ❌ <code>{name}</code> — <i>{err}</i>\n"

    # ═══ حالة خاصة ═══
    if cleaned == 0 and before == 0:
        text += "\n✨ <i>القاعدة نظيفة — لا شيء للتنظيف.</i>"
    elif cleaned == 0 and before > 0:
        text += (
            f"\n💡 <i>لم يُنظَّف شيء لأن كل الجداول تحت "
            f"الحد ({_AUTO_VACUUM_MIN_DEAD} dead tuples).</i>"
        )

    return text


def _build_auto_tune_report(result: Dict[str, Any]) -> str:
    """
    تقرير ضبط autovacuum — يفوّض لـ format_autovacuum_tuning
    إن كانت متاحة، وإلا يبني تقريرًا مبسّطًا.
    """
    if format_autovacuum_tuning is not None:
        try:
            return format_autovacuum_tuning(result)
        except Exception as e:
            logger.debug(f"format_autovacuum_tuning: {e}")

    tuned = result.get('tuned', []) or []
    skipped = result.get('skipped', []) or []
    failed = result.get('failed', []) or []
    duration = float(result.get('duration_sec', 0) or 0)

    lines = ["⚙️ <b>ضبط autovacuum</b>", "━━━━━━━━━━━━━━━━━━━━━━", ""]
    if tuned:
        lines.append(f"✅ <b>ضُبطت ({len(tuned)}):</b>")
        for t in tuned[:10]:
            lines.append(f"  🔧 <code>{_esc(t.get('name', '?'))}</code>")
        lines.append("")
    if skipped:
        lines.append(f"⏭️ <b>تخطّي ({len(skipped)}):</b>")
        for t in skipped[:5]:
            lines.append(
                f"  • <code>{_esc(t.get('name', '?'))}</code> — "
                f"{_esc(t.get('reason', '?'))}"
            )
        lines.append("")
    if failed:
        lines.append(f"❌ <b>فشل ({len(failed)}):</b>")
        for t in failed[:5]:
            lines.append(
                f"  • <code>{_esc(t.get('name', '?'))}</code> — "
                f"{_esc(str(t.get('error', '?'))[:60])}"
            )
        lines.append("")
    lines.append(f"⏱️ <i>{duration:.2f}s</i>")
    return "\n".join(lines)


async def db_weekly_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    📅 إدارة التقرير الأسبوعي + التنظيف التلقائي + الضبط التلقائي.

    الاستخدام:
      /db_weekly status      — عرض حالة كل المهام
      /db_weekly on          — تفعيل التقرير الأسبوعي
      /db_weekly off         — تعطيله
      /db_weekly auto_on     — تفعيل التنظيف التلقائي
      /db_weekly auto_off    — تعطيله
      /db_weekly auto_now    — تشغيل التنظيف فوراً
      /db_weekly tune_on     — تفعيل الضبط الدوري
      /db_weekly tune_off    — تعطيله
      /db_weekly tune_now    — ضبط فوري
    """
    if not update.effective_user or not update.message:
        return

    user_id = update.effective_user.id

    if not _is_authorized(user_id):
        await update.message.reply_text("⛔ غير مصرح.")
        return

    _cleanup_stale_pending(context)

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

            tune_raw = await DB.get_setting(
                'db_auto_tune_enabled', default='1'
            )
            tune_enabled = str(tune_raw).strip() in (
                '1', 'true', 'yes', 'on'
            )

            # حالة المهام
            weekly_running = _is_task_alive(_weekly_task)
            auto_running = _is_task_alive(_auto_vacuum_task)
            # 🟡 v1.1.5 FIX-AM33
            startup_tune_running = _is_task_alive(_startup_tune_task)

            # توضيح للـ admin إذا DB ليست PG
            pg_note = ""
            if not _is_postgres():
                pg_note = (
                    "\n⚠️ <i>Auto-vacuum معطّل — DB ليست PostgreSQL.</i>"
                )

            # قسم الضبط
            version_display = _format_version_display(
                _DB_DIAGNOSTICS_VERSION
            )

            tune_section = "\n"
            if not _AUTO_TUNING_AVAILABLE:
                tune_section += (
                    "⚙️ <b>ضبط autovacuum:</b> 🔴 غير متاح\n"
                    f"   <i>يتطلب db_diagnostics ≥ v7.2.24 "
                    f"(الحالي: {_esc(version_display)})</i>\n"
                )
            elif not _is_postgres():
                tune_section += (
                    "⚙️ <b>ضبط autovacuum:</b> 🔴 غير متاح (ليست PG)\n"
                )
            else:
                tune_icon = "🟢" if tune_enabled else "🔴"
                tune_state = "مفعّل" if tune_enabled else "معطّل"
                recycle_min = (
                    _AUTO_TUNING_RECYCLE_CYCLES
                    * _AUTO_VACUUM_INTERVAL_SEC // 60
                )
                tune_section += (
                    f"⚙️ <b>ضبط autovacuum:</b> {tune_icon} {tune_state}\n"
                    f"⏱️ إعادة الضبط: كل {recycle_min} دقيقة "
                    f"({_AUTO_TUNING_RECYCLE_CYCLES} دورة)\n"
                    f"🔁 دورات منذ آخر ضبط: "
                    f"{_auto_tuning_cycle_counter}"
                    f"/{_AUTO_TUNING_RECYCLE_CYCLES}\n"
                )
                # 🟡 v1.1.5 FIX-AM33: عرض startup_tune task
                if startup_tune_running:
                    tune_section += (
                        "🚀 <i>startup_tune نشط الآن...</i>\n"
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
                f"🎯 الحد الأدنى: {_AUTO_VACUUM_MIN_DEAD} dead tuples"
                f"{pg_note}\n"
                f"{tune_section}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>أوامر التحكم:</b>\n"
                f"<code>/db_weekly on|off</code> — التقرير الأسبوعي\n"
                f"<code>/db_weekly auto_on|auto_off</code> — التنظيف\n"
                f"<code>/db_weekly auto_now</code> — تنظيف فوري\n"
                f"<code>/db_weekly tune_on|tune_off</code> — الضبط\n"
                f"<code>/db_weekly tune_now</code> — ضبط فوري\n"
                f"<code>/db_tune</code> — ضبط فوري (مكافئ)"
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
            # 🟡 v1.1.5 FIX-AM31: فحص unit قبل DB type
            if auto_vacuum_dirty_mvs is None:
                await update.message.reply_text(
                    "❌ auto_vacuum_dirty_mvs غير متوفر.\n"
                    "تأكد من db_diagnostics v6.9.4+."
                )
                return

            if not _is_postgres():
                await update.message.reply_text(
                    "⚠️ التنظيف التلقائي يعمل فقط على PostgreSQL."
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
                    f"❌ فشل التنظيف: {_esc(str(e)[:150])}"
                )
                return

            text = _build_auto_now_report(result)

            await update.message.reply_text(
                text, parse_mode='HTML'
            )
            return

        # ═══════════ TUNE ON/OFF/NOW ═══════════
        if action == "tune_on":
            if not _AUTO_TUNING_AVAILABLE:
                await update.message.reply_text(
                    "❌ الضبط التلقائي يتطلب db_diagnostics ≥ v7.2.24.\n"
                    f"الحالي: "
                    f"<code>{_esc(_format_version_display(_DB_DIAGNOSTICS_VERSION))}"
                    f"</code>",
                    parse_mode='HTML',
                )
                return
            await DB.set_setting('db_auto_tune_enabled', '1')
            await update.message.reply_text(
                "✅ تم تفعيل الضبط الدوري.\n"
                f"⏱️ سيعمل كل "
                f"{_AUTO_TUNING_RECYCLE_CYCLES * _AUTO_VACUUM_INTERVAL_SEC // 60} دقيقة."
            )
            return

        if action == "tune_off":
            await DB.set_setting('db_auto_tune_enabled', '0')
            await update.message.reply_text(
                "🔴 تم تعطيل الضبط الدوري.\n"
                "ℹ️ يمكنك الضبط الفوري عبر <code>/db_tune</code>.",
                parse_mode='HTML',
            )
            return

        if action == "tune_now":
            if not _AUTO_TUNING_AVAILABLE or diagnose_autovacuum_tuning is None:
                await update.message.reply_text(
                    "❌ الضبط الفوري يتطلب db_diagnostics ≥ v7.2.24.\n"
                    f"الحالي: "
                    f"<code>{_esc(_format_version_display(_DB_DIAGNOSTICS_VERSION))}"
                    f"</code>",
                    parse_mode='HTML',
                )
                return
            if not _is_postgres():
                await update.message.reply_text(
                    "⚠️ الضبط التلقائي يعمل فقط على PostgreSQL."
                )
                return
            try:
                text = await diagnose_autovacuum_tuning(force=True)
                await update.message.reply_text(text, parse_mode='HTML')
            except Exception as e:
                logger.error(f"tune_now: {e}", exc_info=True)
                await update.message.reply_text(
                    f"❌ فشل الضبط: {_esc(str(e)[:150])}"
                )
            return

        # ═══════════ استخدام غير صحيح ═══════════
        await update.message.reply_text(
            "❌ استخدام غير صحيح.\n\n"
            "<b>الأوامر المتاحة:</b>\n"
            "<code>/db_weekly status</code>\n"
            "<code>/db_weekly on|off</code>\n"
            "<code>/db_weekly auto_on|auto_off</code>\n"
            "<code>/db_weekly auto_now</code>\n"
            "<code>/db_weekly tune_on|tune_off</code>\n"
            "<code>/db_weekly tune_now</code>",
            parse_mode='HTML',
        )

    except Exception as e:
        logger.error(f"db_weekly: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                f"❌ فشل: {_esc(str(e)[:150])}"
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# المهمة الدورية: التقرير الأسبوعي
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
                f"scheduled_weekly_diagnostic: {e}", exc_info=True
            )

        try:
            await asyncio.sleep(_WEEKLY_REPORT_INTERVAL_SEC)
        except asyncio.CancelledError:
            logger.info("⏹️ scheduled_weekly_diagnostic: أُلغي")
            return


# ═══════════════════════════════════════════════════════════════════
# المهمة الدورية: التنظيف التلقائي
# ═══════════════════════════════════════════════════════════════════

async def _maybe_run_auto_tuning(bot) -> None:
    """
    تنفيذ الضبط الدوري كل N دورة.
    يُستدعى من داخل scheduled_auto_vacuum — لا يعمل بذاته.

    🟡 v1.1.5 FIX-AM30: تصفير العداد عند التعطيل.
    """
    global _auto_tuning_cycle_counter, _auto_tune_previous_state

    if not _AUTO_TUNING_AVAILABLE or ensure_autovacuum_tuning is None:
        return
    if not _is_postgres():
        return
    if _is_db_closing():
        return

    # هل الميزة مفعّلة؟
    enabled = True
    try:
        raw = await DB.get_setting(
            'db_auto_tune_enabled', default='1'
        )
        enabled = str(raw).strip() in ('1', 'true', 'yes', 'on')
    except Exception as e:
        logger.debug(f"auto_tune setting: {e}")

    if _auto_tune_previous_state != enabled:
        if _auto_tune_previous_state is None:
            logger.info(
                f"⚙️ auto-tuning: الحالة الأولية = "
                f"{'مفعّل' if enabled else 'معطّل'}"
            )
        else:
            logger.info(
                f"🔄 auto-tuning: "
                f"{'عُطِّل' if not enabled else 'فُعِّل'}"
            )
        _auto_tune_previous_state = enabled

    if not enabled:
        # 🟡 v1.1.5 FIX-AM30: تصفير العداد عند التعطيل
        if _auto_tuning_cycle_counter != 0:
            logger.debug(
                f"⚙️ auto-tuning: معطّل — إعادة العداد "
                f"({_auto_tuning_cycle_counter} → 0)"
            )
            _auto_tuning_cycle_counter = 0
        return

    _auto_tuning_cycle_counter += 1
    if _auto_tuning_cycle_counter < _AUTO_TUNING_RECYCLE_CYCLES:
        return

    # حان وقت الضبط
    _auto_tuning_cycle_counter = 0
    try:
        result = await ensure_autovacuum_tuning(force=True)
        tuned = result.get('tuned', []) if isinstance(result, dict) else []
        failed = result.get('failed', []) if isinstance(result, dict) else []
        if tuned:
            logger.info(
                f"⚙️ auto-tuning periodic: {len(tuned)} جدول ضُبط"
            )
            # إشعار بقناة المطور
            try:
                log_ch = await DB.get_dev_log_channel()
                if log_ch and len(tuned) >= 1:
                    names = ", ".join(
                        _esc(t.get('name', '?')) for t in tuned[:5]
                    )
                    await safe_send(
                        bot, log_ch,
                        "⚙️ <b>ضبط دوري لـ autovacuum</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"✅ ضُبط: <b>{len(tuned)}</b>\n"
                        f"<code>{names}</code>",
                        parse_mode='HTML',
                    )
            except Exception as e:
                logger.debug(f"auto-tuning notify: {e}")
        if failed:
            logger.warning(
                f"⚠️ auto-tuning: {len(failed)} فشل"
            )
    except Exception as e:
        logger.warning(
            f"auto-tuning periodic: {e}", exc_info=True
        )


async def scheduled_auto_vacuum(bot):
    """
    🧹 تنظيف تلقائي دوري.
    يشمل إعادة ضبط autovacuum كل N دورة.

    - يتوقف فوراً إذا DB_TYPE != postgres.
    - يتخطى الدورة إذا DB في حالة إغلاق.
    - log عند تغيّر حالة التفعيل.
    """
    global _auto_vacuum_previous_state

    if not _is_postgres():
        logger.info(
            "⏭️ scheduled_auto_vacuum: DB ليست PostgreSQL — "
            "المهمة لا تعمل."
        )
        return

    logger.info(
        f"🧹 auto-vacuum scheduler started | "
        f"interval={_AUTO_VACUUM_INTERVAL_SEC}s | "
        f"initial_delay={_AUTO_VACUUM_INITIAL_DELAY}s | "
        f"min_dead={_AUTO_VACUUM_MIN_DEAD} | "
        f"auto_tune_recycle={_AUTO_TUNING_RECYCLE_CYCLES} cycles"
    )

    try:
        await asyncio.sleep(_AUTO_VACUUM_INITIAL_DELAY)
    except asyncio.CancelledError:
        logger.info("⏹️ scheduled_auto_vacuum: أُلغي قبل البدء")
        return

    while True:
        try:
            # فحص إغلاق DB
            if _is_db_closing():
                logger.debug(
                    "⏭️ auto-vacuum: DB في حالة إغلاق — تخطي الدورة"
                )
                try:
                    await asyncio.sleep(_AUTO_VACUUM_INTERVAL_SEC)
                except asyncio.CancelledError:
                    logger.info("⏹️ scheduled_auto_vacuum: أُلغي")
                    return
                continue

            # قد يُشغّل الضبط الدوري
            try:
                await _maybe_run_auto_tuning(bot)
            except asyncio.CancelledError:
                logger.info("⏹️ scheduled_auto_vacuum: أُلغي")
                return
            except Exception as e:
                logger.warning(f"_maybe_run_auto_tuning: {e}")

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

            # log عند التغيّر
            if _auto_vacuum_previous_state != enabled:
                if _auto_vacuum_previous_state is None:
                    logger.info(
                        f"🧹 auto-vacuum: الحالة الأولية = "
                        f"{'مفعّل' if enabled else 'معطّل'}"
                    )
                else:
                    logger.info(
                        f"🔄 auto-vacuum: "
                        f"{'عُطِّل' if not enabled else 'فُعِّل'}"
                    )
                _auto_vacuum_previous_state = enabled

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
                            if (log_ch and cleaned
                                    >= _AUTO_VACUUM_NOTIFY_MIN_CLEANED):
                                vacuumed = result.get('vacuumed', [])
                                details = "\n".join(
                                    f"  • <code>{_esc(v.get('name', '?'))}"
                                    f"</code>"
                                    + (" <code>[MV]</code>"
                                       if v.get('is_mv') else "")
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
    """بدء المهمة الأسبوعية."""
    global _weekly_task

    if _is_task_alive(_weekly_task):
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
    """إيقاف المهمة الأسبوعية."""
    global _weekly_task

    if not _is_task_alive(_weekly_task):
        return

    try:
        try:
            loop = asyncio.get_running_loop()
            if loop.is_closed():
                logger.debug(
                    "stop_weekly_diagnostic_task: loop مغلق — تخطي"
                )
                _weekly_task = None
                return
        except RuntimeError:
            try:
                _weekly_task.cancel()
            except Exception:
                pass
            _weekly_task = None
            return

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
    """بدء مهمة التنظيف التلقائي."""
    global _auto_vacuum_task

    if _is_task_alive(_auto_vacuum_task):
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
    """
    إيقاف مهمة التنظيف.

    🟠 v1.1.5 FIX-AM27: يُلغي أيضاً startup_tune_task.
    """
    global _auto_vacuum_task, _startup_tune_task

    try:
        loop = asyncio.get_running_loop()
        if loop.is_closed():
            logger.debug(
                "stop_auto_vacuum_task: loop مغلق — تخطي"
            )
            _auto_vacuum_task = None
            _startup_tune_task = None
            return
    except RuntimeError:
        if _auto_vacuum_task is not None:
            try:
                _auto_vacuum_task.cancel()
            except Exception:
                pass
        if _startup_tune_task is not None:
            try:
                _startup_tune_task.cancel()
            except Exception:
                pass
        _auto_vacuum_task = None
        _startup_tune_task = None
        return

    # 🟠 v1.1.5 FIX-AM27: إلغاء startup_tune أولاً
    if _is_task_alive(_startup_tune_task):
        try:
            _startup_tune_task.cancel()
            try:
                await asyncio.wait_for(
                    _startup_tune_task, timeout=timeout
                )
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            logger.debug("🛑 startup_tune task stopped")
        except Exception as e:
            logger.debug(f"stop startup_tune: {e}")
        finally:
            _startup_tune_task = None

    # ثم auto_vacuum
    if _is_task_alive(_auto_vacuum_task):
        try:
            _auto_vacuum_task.cancel()
            try:
                await asyncio.wait_for(
                    _auto_vacuum_task, timeout=timeout
                )
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            logger.info("🛑 auto-vacuum task stopped")
        except Exception as e:
            logger.debug(f"stop_auto_vacuum_task: {e}")
        finally:
            _auto_vacuum_task = None
    else:
        _auto_vacuum_task = None


# ═══════════════════════════════════════════════════════════════════
# التسجيل الرئيسي
# ═══════════════════════════════════════════════════════════════════

async def _init_autovacuum_tuning_at_startup() -> None:
    """
    استدعاء init_autovacuum_tuning() مرة عند التسجيل.
    آمن للاستدعاء المتكرر + مقيد بمفتاح db_auto_tune_enabled.
    """
    if not _AUTO_TUNING_AVAILABLE or init_autovacuum_tuning is None:
        logger.debug(
            "⏭️ startup auto-tuning: db_diagnostics < v7.2.24 — تخطي."
        )
        return
    if not _is_postgres():
        logger.debug(
            "⏭️ startup auto-tuning: DB ليست PostgreSQL — تخطي."
        )
        return

    # هل الميزة مفعّلة؟
    try:
        raw = await DB.get_setting(
            'db_auto_tune_enabled', default='1'
        )
        enabled = str(raw).strip() in ('1', 'true', 'yes', 'on')
    except Exception as e:
        logger.debug(f"startup auto-tuning setting: {e}")
        enabled = True

    if not enabled:
        logger.info(
            "⏭️ startup auto-tuning: db_auto_tune_enabled='0' — تخطي."
        )
        return

    try:
        result = await init_autovacuum_tuning()
        tuned = result.get('tuned', []) if isinstance(result, dict) else []
        failed = result.get('failed', []) if isinstance(result, dict) else []
        if tuned:
            names = ", ".join(
                _esc(t.get('name', '?')) for t in tuned[:5]
            )
            logger.info(
                f"⚙️ startup auto-tuning: {len(tuned)} جدول ضُبط | "
                f"{names}"
            )
        elif failed:
            logger.warning(
                f"⚠️ startup auto-tuning: {len(failed)} فشل"
            )
        else:
            logger.info(
                "⚙️ startup auto-tuning: كل الجداول مضبوطة مسبقاً."
            )
    except Exception as e:
        logger.warning(
            f"startup auto-tuning: {e}", exc_info=True
        )


def _on_startup_tune_done(task: asyncio.Task) -> None:
    """🟠 v1.1.5 FIX-AM27: callback عند انتهاء startup_tune task."""
    try:
        if task.cancelled():
            logger.debug("🛑 startup_tune task cancelled")
        elif task.exception() is not None:
            logger.warning(
                f"⚠️ startup_tune task failed: {task.exception()}"
            )
        else:
            logger.debug("✅ startup_tune task finished")
    except Exception as e:
        logger.debug(f"_on_startup_tune_done: {e}")


def _start_startup_tuning_task() -> None:
    """🟠 v1.1.5 FIX-AM27: بدء task مع تتبّع كامل."""
    global _startup_tune_task

    # idempotent — لا تُنشئ task جديداً إذا كان موجوداً ويعمل
    if _is_task_alive(_startup_tune_task):
        logger.debug(
            "startup_tune: task موجود ويعمل — تخطي الإنشاء"
        )
        return

    try:
        _startup_tune_task = asyncio.create_task(
            _init_autovacuum_tuning_at_startup(),
            name="startup-auto-tuning",
        )
        _startup_tune_task.add_done_callback(_on_startup_tune_done)
        logger.info("⚙️ startup auto-tuning scheduled (tracked)")
    except Exception as e:
        logger.warning(
            f"schedule startup auto-tuning: {e}"
        )
        _startup_tune_task = None


def _restart_tasks_if_needed(application) -> None:
    """
    🟠 v1.1.5 FIX-AM29: إعادة بدء المهام إذا كانت متوقفة.
    يُستدعى من المسار idempotent.
    """
    # weekly
    if not _is_task_alive(_weekly_task):
        try:
            if start_weekly_diagnostic_task(application):
                logger.info(
                    "🔄 restart: weekly diagnostic task"
                )
        except Exception as e:
            logger.warning(f"restart weekly: {e}")

    # auto_vacuum
    if (_is_postgres()
            and auto_vacuum_dirty_mvs is not None
            and _VERSION_OK
            and not _is_task_alive(_auto_vacuum_task)):
        try:
            if start_auto_vacuum_task(application):
                logger.info("🔄 restart: auto_vacuum task")
        except Exception as e:
            logger.warning(f"restart auto_vacuum: {e}")

    # startup_tune
    if (_AUTO_TUNING_AVAILABLE
            and init_autovacuum_tuning is not None
            and _is_postgres()
            and not _is_task_alive(_startup_tune_task)):
        try:
            _start_startup_tuning_task()
            logger.info("🔄 restart: startup_tune task")
        except Exception as e:
            logger.warning(f"restart startup_tune: {e}")


def register_maintenance_commands(application) -> bool:
    """
    تسجيل الأوامر + بدء مهمة التنظيف التلقائي + الضبط الأولي.

    🟠 v1.1.5 FIX-AM29: إذا كانت الأوامر مُسجَّلة مسبقاً لكن
    المهام متوقفة (مثلاً بعد stop_*)، يُعيد بدءها.
    """
    global _commands_registered

    # المسار idempotent — لكن يتحقق من المهام
    if _commands_registered:
        logger.debug(
            "register_maintenance_commands: "
            "الأوامر مُسجَّلة مسبقاً — التحقق من المهام."
        )
        # 🟠 v1.1.5 FIX-AM29: إعادة بدء المهام إذا لزم
        _restart_tasks_if_needed(application)
        return True

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

    if _AUTO_TUNING_AVAILABLE:
        try:
            application.add_handler(CommandHandler(
                "db_tune", db_tune_command
            ))
        except Exception as e:
            logger.error(f"❌ register db_tune: {e}", exc_info=True)
            ok_all = False
    else:
        logger.info(
            "⏭️ /db_tune لم يُسجَّل — db_diagnostics < v7.2.24"
        )

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

    # 2) التنظيف التلقائي
    try:
        if auto_vacuum_dirty_mvs is None:
            logger.warning(
                "⚠️ auto_vacuum_dirty_mvs غير متوفر — "
                "تأكد من db_diagnostics >= v6.9.4"
            )
        elif not _VERSION_OK:
            logger.error(
                f"❌ رفض تشغيل auto-vacuum — "
                f"db_diagnostics={_DB_DIAGNOSTICS_VERSION} "
                f"< الحد الأدنى "
                f"{'.'.join(map(str, _DB_DIAGNOSTICS_MIN_VERSION))}"
            )
        elif not _is_postgres():
            logger.info(
                "⏭️ auto-vacuum: DB ليست PostgreSQL — "
                "المهمة لن تُسجَّل."
            )
        else:
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
    except Exception as e:
        logger.error(f"auto_vacuum startup: {e}", exc_info=True)

    # 3) الضبط الأولي
    try:
        if (_AUTO_TUNING_AVAILABLE
                and init_autovacuum_tuning is not None
                and _is_postgres()):
            _start_startup_tuning_task()
    except Exception as e:
        logger.error(f"auto_tuning startup: {e}", exc_info=True)

    # تحديث flag
    if ok_all:
        _commands_registered = True

    # ═══════════════════════════════════════════════════════════════════
    # ⚠️ FIX-AM1 (v1.1.1): توثيق إلزامي — يجب على bot.py استدعاء
    # stop_auto_vacuum_task() و stop_weekly_diagnostic_task() عند
    # الإغلاق لضمان إغلاق نظيف.
    #
    # 🟠 v1.1.5 FIX-AM27: stop_auto_vacuum_task الآن يُلغي أيضاً
    # startup_tune_task (لا حاجة لاستدعاء منفصل).
    # ═══════════════════════════════════════════════════════════════════

    if ok_all:
        cmd_list = "/db_diag_quick, /db_maintenance, /db_weekly"
        if _AUTO_TUNING_AVAILABLE:
            cmd_list += ", /db_tune"
        logger.info(
            f"✅ Maintenance commands registered: {cmd_list} | "
            f"⚠️ تأكد من bot.py: stop_auto_vacuum_task + "
            f"stop_weekly_diagnostic_task عند الإغلاق"
        )
    else:
        logger.warning(
            "⚠️ بعض أوامر الصيانة فشلت في التسجيل"
        )

    return ok_all


# ═══════════════════════════════════════════════════════════════════
# Aliases
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
    "__version__",
    # الأوامر
    "db_diag_quick_command",
    "db_maintenance_command",
    "db_weekly_command",
    "db_tune_command",
    # المهام
    "scheduled_weekly_diagnostic",
    "scheduled_auto_vacuum",
    # إدارة
    "start_weekly_diagnostic_task",
    "stop_weekly_diagnostic_task",
    "start_auto_vacuum_task",
    "stop_auto_vacuum_task",
    # تشخيص
    "get_tasks_status",
    # builders
    "_build_auto_now_report",
    "_build_auto_tune_report",
    # التسجيل
    "register_maintenance_commands",
    "register",
    "register_commands",
    "setup_commands",
    "setup",
    "register_maintenance",
    "register_db_maintenance",
]


# ═══════════════════════════════════════════════════════════════════
# LOAD BEACON — v1.1.5
# ═══════════════════════════════════════════════════════════════════

try:
    _beacon_parts = [
        f"🛡️ db_maintenance_commands.py v{__version__} loaded",
        f"commands: /db_diag_quick, /db_maintenance, /db_weekly"
        + (", /db_tune" if _AUTO_TUNING_AVAILABLE else ""),
        f"auto-vacuum: ✅ every {_AUTO_VACUUM_INTERVAL_SEC // 60} min",
        f"min_dead={_AUTO_VACUUM_MIN_DEAD}",
        f"auto-tuning: "
        + ("✅" if _AUTO_TUNING_AVAILABLE else "❌")
        + f" recycle={_AUTO_TUNING_RECYCLE_CYCLES} cycles (max-1 enforced)",
        f"db_diagnostics={_format_version_display(_DB_DIAGNOSTICS_VERSION)}",
        f"version_ok={_VERSION_OK}",
        f"auto_tuning_available={_AUTO_TUNING_AVAILABLE}",
        "FIX-AM1 shutdown docs ✅",
        "FIX-AM2 idempotent-reg ✅",
        "FIX-AM3 db-type-aware ✅",
        "FIX-AM4 html-escape ✅",
        "FIX-AM5 version-guard ✅",
        "FIX-AM6 closing-guard ✅",
        "FIX-AM7 env-min-dead ✅",
        "FIX-AM8 pre-release-parse ✅",
        "FIX-AM9 state-change-log ✅",
        "FIX-AM10 closed-loop-guard ✅",
        "FIX-AM11 weekly-pending-clean ✅",
        "FIX-AM12 weekly-target-log ✅",
        "FIX-AM13 notify-threshold-const ✅",
        "FIX-AM14 tasks-status-helper ✅",
        "FIX-AM16 is_mv-key-fix ✅",
        "FIX-AM17 report-visibility ✅",
        "FIX-AM18 dead-after-display ✅",
        "FIX-AM19 notify-is_mv ✅",
        "FIX-AM20 tune-imports ✅",
        "FIX-AM21 tune-startup ✅",
        "FIX-AM22 db_tune-cmd ✅",
        "FIX-AM23 tune-periodic ✅",
        "FIX-AM24 tune-subcommands ✅",
        "FIX-AM25 tune-status ✅",
        "FIX-AM26 tune-weekly-status ✅",
        "FIX-AM27 startup-tune-tracked ✅",
        "FIX-AM28 recycle-cycles-min-1 ✅",
        "FIX-AM29 idempotent-restart-tasks ✅",
        "FIX-AM30 reset-counter-on-disable ✅",
        "FIX-AM31 auto_now-unit-first ✅",
        "FIX-AM32 version-display ✅",
        "FIX-AM33 startup-tune-status ✅",
    ]
    logger.info(" | ".join(_beacon_parts))
except Exception:
    pass