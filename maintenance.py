#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
maintenance.py - الصيانة التلقائية لقاعدة البيانات (v1.0.0)
================================================================================
- daily_maintenance()      : job يومي 3 صباحاً
- cleanup_old_logs()        : حذف admin_logs القديمة
- cleanup_penalty_archive() : حذف penalty_archive القديمة
- cleanup_violations()      : حذف user_violations المنتهية
- vacuum_critical_tables()  : VACUUM للجداول الحرجة
- get_maintenance_status()  : تقرير نصي بآخر صيانة
================================================================================
"""

import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo

try:
    from database import DB, TimeUtils
except ImportError:
    DB = None
    TimeUtils = None

logger = logging.getLogger(__name__)


# =====================================================================
# ⚙️ ثوابت الصيانة
# =====================================================================

# المدة قبل الحذف (بالأيام)
ADMIN_LOGS_RETENTION_DAYS = 30
PENALTY_ARCHIVE_RETENTION_DAYS = 90
USER_VIOLATIONS_RETENTION_DAYS = 7
PAYMENT_LOGS_RETENTION_DAYS = 180
SLOW_QUERIES_RETENTION_DAYS = 30

# الجداول التي تحتاج VACUUM دوري
VACUUM_TABLES = (
    'admin_logs',
    'user_violations',
    'posts',
    'penalty_archive',
    'user_penalties',
    'subscriptions',
)

# التوقيت المحلي للصيانة
MAINTENANCE_HOUR = 3       # 3 صباحاً
MAINTENANCE_MINUTE = 0
MAINTENANCE_TZ = "Asia/Riyadh"   # غيّرها حسب المنطقة


# =====================================================================
# 🗑️ دوال التنظيف
# =====================================================================

async def cleanup_old_logs() -> Dict[str, int]:
    """
    🗑️ حذف السجلات القديمة من admin_logs.
    Returns: {deleted, remaining}
    """
    if DB is None:
        return {'deleted': 0, 'remaining': 0}
    try:
        # حذف الأقدم من 30 يوماً
        result = await DB.execute(
            f"DELETE FROM admin_logs "
            f"WHERE created_at < NOW() - INTERVAL '{ADMIN_LOGS_RETENTION_DAYS} days'"
        )
        deleted = getattr(result, 'rowcount', 0) or 0
        remaining = await DB.fetchval(
            "SELECT COUNT(*) FROM admin_logs", default=0
        ) or 0
        logger.info(f"🧹 admin_logs: حذف {deleted} سجل، متبقٍ {remaining}")
        return {'deleted': int(deleted), 'remaining': int(remaining)}
    except Exception as e:
        logger.warning(f"⚠️ cleanup_old_logs: {e}")
        return {'deleted': 0, 'remaining': 0, 'error': str(e)}


async def cleanup_penalty_archive() -> Dict[str, int]:
    """
    🗑️ حذف penalty_archive القديمة (> 90 يوم).
    """
    if DB is None:
        return {'deleted': 0, 'remaining': 0}
    try:
        result = await DB.execute(
            f"DELETE FROM penalty_archive "
            f"WHERE created_at < NOW() - INTERVAL '{PENALTY_ARCHIVE_RETENTION_DAYS} days'"
        )
        deleted = getattr(result, 'rowcount', 0) or 0
        remaining = await DB.fetchval(
            "SELECT COUNT(*) FROM penalty_archive", default=0
        ) or 0
        logger.info(f"🧹 penalty_archive: حذف {deleted}، متبقٍ {remaining}")
        return {'deleted': int(deleted), 'remaining': int(remaining)}
    except Exception as e:
        logger.warning(f"⚠️ cleanup_penalty_archive: {e}")
        return {'deleted': 0, 'remaining': 0, 'error': str(e)}


async def cleanup_violations() -> Dict[str, int]:
    """
    🗑️ حذف user_violations المنتهية (> 7 أيام + action_taken).
    """
    if DB is None:
        return {'deleted': 0, 'remaining': 0}
    try:
        # فقط المُعالَج منها (action_taken = true أو 1)
        result = await DB.execute(
            f"DELETE FROM user_violations "
            f"WHERE created_at < NOW() - INTERVAL '{USER_VIOLATIONS_RETENTION_DAYS} days' "
            f"AND (action_taken = TRUE OR action_taken = 1)"
        )
        deleted = getattr(result, 'rowcount', 0) or 0
        remaining = await DB.fetchval(
            "SELECT COUNT(*) FROM user_violations", default=0
        ) or 0
        logger.info(f"🧹 user_violations: حذف {deleted}، متبقٍ {remaining}")
        return {'deleted': int(deleted), 'remaining': int(remaining)}
    except Exception as e:
        logger.warning(f"⚠️ cleanup_violations: {e}")
        return {'deleted': 0, 'remaining': 0, 'error': str(e)}


async def cleanup_payment_logs() -> Dict[str, int]:
    """🗑️ حذف payment_logs الأقدم من 180 يوم."""
    if DB is None:
        return {'deleted': 0, 'remaining': 0}
    try:
        result = await DB.execute(
            f"DELETE FROM payment_logs "
            f"WHERE created_at < NOW() - INTERVAL '{PAYMENT_LOGS_RETENTION_DAYS} days'"
        )
        deleted = getattr(result, 'rowcount', 0) or 0
        logger.info(f"🧹 payment_logs: حذف {deleted}")
        return {'deleted': int(deleted)}
    except Exception as e:
        # الجدول قد لا يكون موجوداً في كل النسخ
        logger.debug(f"cleanup_payment_logs: {e}")
        return {'deleted': 0}


# =====================================================================
# 🧹 VACUUM
# =====================================================================

async def vacuum_critical_tables() -> Dict[str, bool]:
    """
    🧹 VACUUM ANALYZE على الجداول الحرجة.

    ملاحظة: VACUUM لا يعمل داخل transaction — يجب تنفيذه مباشرة.
    """
    if DB is None:
        return {}
    results = {}
    for table in VACUUM_TABLES:
        try:
            # VACUUM لا يدعم parameter binding للاسم — نمرّر كنص ثابت
            await DB.execute(f"VACUUM (ANALYZE) {table}")
            results[table] = True
            logger.info(f"✅ VACUUM {table}")
        except Exception as e:
            results[table] = False
            logger.warning(f"⚠️ VACUUM {table}: {e}")
        # تأخير بسيط بين VACUUMs لتجنّب قفل
        await asyncio.sleep(0.5)
    return results


# =====================================================================
# 🔬 فحص ما قبل الصيانة
# =====================================================================

async def get_table_snapshot() -> Dict[str, Any]:
    """📸 لقطة سريعة عن أحجام الجداول (قبل/بعد)."""
    if DB is None:
        return {}
    try:
        rows = await DB.fetchall("""
            SELECT
                relname AS table_name,
                n_live_tup AS live,
                n_dead_tup AS dead
            FROM pg_stat_user_tables
            ORDER BY n_dead_tup DESC
            LIMIT 20
        """)
        return {
            r['table_name'] if isinstance(r, dict) else r[0]: {
                'live': int(r['live'] if isinstance(r, dict) else r[1]),
                'dead': int(r['dead'] if isinstance(r, dict) else r[2]),
            }
            for r in (rows or [])
        }
    except Exception as e:
        logger.debug(f"get_table_snapshot: {e}")
        return {}


# =====================================================================
# 🎯 المهمة اليومية الرئيسية
# =====================================================================

async def daily_maintenance(bot=None, notify_admin_id: Optional[int] = None) -> Dict[str, Any]:
    """
    🎯 الصيانة اليومية الشاملة.

    1. لقطة قبل
    2. حذف سجلات قديمة
    3. VACUUM ANALYZE
    4. لقطة بعد
    5. (اختياري) إشعار الأدمن

    Args:
        bot: telegram.Bot للإشعار (اختياري)
        notify_admin_id: معرّف الأدمن للإشعار (اختياري)
    """
    start = datetime.now()
    logger.info("=" * 60)
    logger.info("🔧 بدء الصيانة اليومية")
    logger.info("=" * 60)

    report: Dict[str, Any] = {
        'started_at': start.isoformat(),
        'admin_logs': {},
        'penalty_archive': {},
        'user_violations': {},
        'payment_logs': {},
        'vacuum': {},
        'snapshot_before': {},
        'snapshot_after': {},
        'duration_sec': 0,
        'errors': [],
    }

    try:
        # 1) لقطة قبل
        report['snapshot_before'] = await get_table_snapshot()

        # 2) التنظيفات
        try:
            report['admin_logs'] = await cleanup_old_logs()
        except Exception as e:
            report['errors'].append(f"admin_logs: {e}")

        try:
            report['penalty_archive'] = await cleanup_penalty_archive()
        except Exception as e:
            report['errors'].append(f"penalty_archive: {e}")

        try:
            report['user_violations'] = await cleanup_violations()
        except Exception as e:
            report['errors'].append(f"user_violations: {e}")

        try:
            report['payment_logs'] = await cleanup_payment_logs()
        except Exception as e:
            report['errors'].append(f"payment_logs: {e}")

        # 3) VACUUM
        try:
            report['vacuum'] = await vacuum_critical_tables()
        except Exception as e:
            report['errors'].append(f"vacuum: {e}")

        # 4) لقطة بعد
        report['snapshot_after'] = await get_table_snapshot()

        # 5) الحساب النهائي
        end = datetime.now()
        report['duration_sec'] = round((end - start).total_seconds(), 1)
        report['finished_at'] = end.isoformat()

        logger.info("=" * 60)
        logger.info(f"✅ انتهت الصيانة في {report['duration_sec']}s")
        if report['errors']:
            logger.warning(f"⚠️ {len(report['errors'])} أخطاء")
        logger.info("=" * 60)

        # 6) إشعار الأدمن (اختياري)
        if bot and notify_admin_id:
            try:
                await _send_report(bot, notify_admin_id, report)
            except Exception as e:
                logger.warning(f"⚠️ send maintenance report: {e}")

    except Exception as e:
        logger.error(f"❌ daily_maintenance: {e}", exc_info=True)
        report['errors'].append(str(e))

    return report


async def _send_report(bot, chat_id: int, report: Dict[str, Any]) -> None:
    """📤 إرسال تقرير الصيانة للأدمن."""
    lines = [
        "🔧 <b>تقرير الصيانة اليومية</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"⏱️ المدة: <b>{report['duration_sec']}s</b>",
        "",
        "🗑️ <b>المحذوفات:</b>",
        f"  • admin_logs: <b>{report['admin_logs'].get('deleted', 0)}</b>",
        f"  • penalty_archive: <b>{report['penalty_archive'].get('deleted', 0)}</b>",
        f"  • user_violations: <b>{report['user_violations'].get('deleted', 0)}</b>",
        f"  • payment_logs: <b>{report['payment_logs'].get('deleted', 0)}</b>",
        "",
        "🧹 <b>VACUUM:</b>",
    ]
    for table, ok in report['vacuum'].items():
        icon = "✅" if ok else "❌"
        lines.append(f"  {icon} {table}")

    # Dead tuples قبل/بعد
    before = report.get('snapshot_before', {})
    after = report.get('snapshot_after', {})
    if before and after:
        lines.append("")
        lines.append("📊 <b>Dead Tuples (قبل → بعد):</b>")
        for table in list(before.keys())[:5]:
            b_dead = before.get(table, {}).get('dead', 0)
            a_dead = after.get(table, {}).get('dead', 0)
            diff = b_dead - a_dead
            icon = "🟢" if diff > 0 else ("⚪" if diff == 0 else "🟡")
            lines.append(
                f"  {icon} {table}: {b_dead} → {a_dead} "
                f"({'+' if diff >= 0 else ''}{diff})"
            )

    if report['errors']:
        lines.append("")
        lines.append("⚠️ <b>أخطاء:</b>")
        for err in report['errors'][:5]:
            lines.append(f"  • {err[:80]}")

    text = "\n".join(lines)
    try:
        await bot.send_message(
            chat_id=chat_id, text=text, parse_mode='HTML'
        )
    except Exception as e:
        logger.warning(f"_send_report send_message: {e}")


# =====================================================================
# 🔌 ربط job_queue
# =====================================================================

def register_maintenance_job(app, notify_admin_id: Optional[int] = None):
    """
    🔌 تسجيل الصيانة اليومية في job_queue.

    الاستخدام في main.py:
        from maintenance import register_maintenance_job
        register_maintenance_job(app, notify_admin_id=YOUR_ID)

    Args:
        app: telegram.ext.Application
        notify_admin_id: معرف الأدمن لإرسال التقرير
    """
    if not hasattr(app, 'job_queue') or app.job_queue is None:
        logger.warning("⚠️ job_queue غير متوفر — الصيانة لن تُسجَّل")
        return

    try:
        tz = ZoneInfo(MAINTENANCE_TZ)
    except Exception:
        tz = None
        logger.warning(f"⚠️ ZoneInfo({MAINTENANCE_TZ}) غير متوفر — استخدام UTC")

    run_time = time(hour=MAINTENANCE_HOUR,
                    minute=MAINTENANCE_MINUTE,
                    tzinfo=tz)

    async def _job(context):
        try:
            await daily_maintenance(
                bot=context.bot,
                notify_admin_id=notify_admin_id,
            )
        except Exception as e:
            logger.error(f"❌ maintenance job: {e}", exc_info=True)

    app.job_queue.run_daily(
        _job,
        time=run_time,
        name="daily_maintenance",
    )
    logger.info(
        f"✅ registered daily_maintenance @ "
        f"{MAINTENANCE_HOUR:02d}:{MAINTENANCE_MINUTE:02d} {MAINTENANCE_TZ}"
    )


# =====================================================================
# 🧪 تشغيل يدوي
# =====================================================================

async def run_maintenance_now(bot=None, notify_admin_id: Optional[int] = None):
    """🧪 تشغيل الصيانة يدوياً الآن (اختبار)."""
    return await daily_maintenance(bot=bot, notify_admin_id=notify_admin_id)


__all__ = [
    "daily_maintenance",
    "run_maintenance_now",
    "register_maintenance_job",
    "cleanup_old_logs",
    "cleanup_penalty_archive",
    "cleanup_violations",
    "cleanup_payment_logs",
    "vacuum_critical_tables",
    "get_table_snapshot",
]