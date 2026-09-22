#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
maintenance.py - الصيانة التلقائية لقاعدة البيانات (v1.0.1)
================================================================================
🎯 الوظائف الرئيسية:
  - maintenance_loop()        : 🔄 حلقة دورية (متكاملة مع main.py v5.4.3)
  - daily_maintenance()        : 🎯 صيانة شاملة واحدة
  - run_maintenance_now()      : 🧪 تشغيل يدوي فوري (يتجاوز الفحص)
  - register_maintenance_job() : 🔌 تسجيل في job_queue (اختياري)

🗑️ دوال التنظيف:
  - cleanup_old_logs()         : admin_logs (> 30 يوم)
  - cleanup_penalty_archive()  : penalty_archive (> 90 يوم)
  - cleanup_violations()       : user_violations (> 7 أيام)
  - cleanup_payment_logs()     : payment_logs (> 180 يوم)

🧹 VACUUM:
  - vacuum_critical_tables()   : VACUUM ANALYZE (DB.vacuum أو fallback)

📸 التشخيص:
  - get_table_snapshot()       : لقطة dead tuples قبل/بعد

📊 التقرير:
  - تقرير HTML يُرسل للمالك عبر Telegram

🆕 v1.0.1:
  ✅ _should_run_maintenance : احترام settings.last_maintenance_at
  ✅ _record_maintenance_time : كتابة التوقيت (متوافق مع database_tables.py)
  ✅ daily_maintenance(force) : تجاوز فحص الفاصل عند الطلب
  ✅ run_maintenance_now(force=True) : افتراضياً يتجاوز
  ✅ منع VACUUM المزدوج مع database_tables._run_maintenance_postgres
================================================================================
"""

import asyncio
import logging
from datetime import datetime, timedelta, time, timezone
from typing import Dict, Any, List, Optional, Tuple

try:
    from database import DB, TimeUtils
except ImportError:
    DB = None
    TimeUtils = None

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

logger = logging.getLogger(__name__)


# =====================================================================
# ⚙️ ثوابت الصيانة
# =====================================================================

# مدد الاحتفاظ (بالأيام)
ADMIN_LOGS_RETENTION_DAYS = 30
PENALTY_ARCHIVE_RETENTION_DAYS = 90
USER_VIOLATIONS_RETENTION_DAYS = 7
PAYMENT_LOGS_RETENTION_DAYS = 180

# الجداول التي تحتاج VACUUM دوري
VACUUM_TABLES: Tuple[str, ...] = (
    'admin_logs',
    'user_violations',
    'posts',
    'penalty_archive',
    'user_penalties',
    'subscriptions',
)

# التوقيت المحلي (للتسجيل فقط)
MAINTENANCE_TZ = "Asia/Riyadh"

# حجم كتل التنظيف
CLEANUP_BATCH_SIZE = 5000

# 🆕 v1.0.1: فاصل الصيانة (بالثواني) — متوافق مع database_tables.py
MAINTENANCE_INTERVAL_SECONDS = 24 * 3600

# 🆕 v1.0.1: مفتاح الإعداد المشترك مع database_tables.py
LAST_MAINTENANCE_KEY = "last_maintenance_at"


# =====================================================================
# 🆕 v1.0.1: احترام last_maintenance_at
# =====================================================================

async def _should_run_maintenance(force: bool = False) -> bool:
    """
    ✅ v1.0.1: يتحقق من settings.last_maintenance_at.
    يمنع VACUUM المزدوج مع database_tables.py.

    Args:
        force: تجاوز الفحص (للأوامر اليدوية)

    Returns:
        True إذا يجب التشغيل، False إذا حديثة
    """
    if force:
        return True
    if DB is None:
        return True

    try:
        last_val = await DB.fetchval(
            f"SELECT value FROM settings WHERE key = '{LAST_MAINTENANCE_KEY}'",
            default=None,
        )
    except Exception as e:
        logger.debug(f"_should_run_maintenance fetchval: {e}")
        return True

    if not last_val:
        return True  # أول مرة

    try:
        last_str = str(last_val).strip()
        # دعم صيغتين: ISO مع tz وبدونه
        last_dt = datetime.fromisoformat(last_str)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)

        age_seconds = (
            datetime.now(timezone.utc) - last_dt
        ).total_seconds()

        if age_seconds < MAINTENANCE_INTERVAL_SECONDS:
            logger.info(
                f"⏩ maintenance: تخطي — آخر صيانة منذ "
                f"{age_seconds / 3600:.1f}h (< 24h)"
            )
            return False
        return True
    except (ValueError, TypeError) as e:
        logger.debug(f"_should_run_maintenance parse: {e}")
        return True
    except Exception as e:
        logger.debug(f"_should_run_maintenance: {e}")
        return True


async def _record_maintenance_time() -> None:
    """
    ✅ v1.0.1: يسجّل توقيت آخر صيانة (متوافق مع database_tables.py).

    يدعم PostgreSQL (ON CONFLICT)، MySQL (ON DUPLICATE KEY)،
    و SQLite (ON CONFLICT) — عبر DB.execute.
    """
    if DB is None:
        return

    now_iso = datetime.now(timezone.utc).isoformat()

    # نحاول أولاً upsert بصيغة SQLite/PG (كلاهما يدعم ON CONFLICT)
    try:
        await DB.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (LAST_MAINTENANCE_KEY, now_iso),
        )
        return
    except Exception as e1:
        logger.debug(f"record (upsert-1): {e1}")

    # MySQL fallback: ON DUPLICATE KEY
    try:
        await DB.execute(
            "INSERT INTO settings (`key`, `value`) VALUES (?, ?) "
            "ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)",
            (LAST_MAINTENANCE_KEY, now_iso),
        )
        return
    except Exception as e2:
        logger.debug(f"record (upsert-2): {e2}")

    # آخر محاولة: INSERT ثم UPDATE
    try:
        await DB.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            (LAST_MAINTENANCE_KEY, now_iso),
        )
    except Exception:
        try:
            await DB.execute(
                "UPDATE settings SET value = ? WHERE key = ?",
                (now_iso, LAST_MAINTENANCE_KEY),
            )
        except Exception as e3:
            logger.debug(f"record (fallback): {e3}")


# =====================================================================
# 🗑️ دوال التنظيف
# =====================================================================

async def cleanup_old_logs() -> Dict[str, Any]:
    """🗑️ حذف سجلات admin_logs الأقدم من 30 يوم."""
    if DB is None:
        return {'deleted': 0, 'remaining': 0, 'error': 'DB غير متاح'}

    try:
        await DB.execute(
            f"DELETE FROM admin_logs "
            f"WHERE created_at < NOW() - INTERVAL "
            f"'{ADMIN_LOGS_RETENTION_DAYS} days'"
        )
        remaining = await DB.fetchval(
            "SELECT COUNT(*) FROM admin_logs", default=0
        ) or 0
        logger.info(
            f"🧹 admin_logs: retention={ADMIN_LOGS_RETENTION_DAYS}d, "
            f"remaining={remaining}"
        )
        return {'deleted': 0, 'remaining': int(remaining)}
    except Exception as e:
        logger.warning(f"⚠️ cleanup_old_logs: {e}")
        # fallback لصيغة مختلفة
        try:
            cutoff = (datetime.now(timezone.utc)
                      - timedelta(days=ADMIN_LOGS_RETENTION_DAYS))
            await DB.execute(
                "DELETE FROM admin_logs WHERE created_at < ?",
                (cutoff,),
            )
            remaining = await DB.fetchval(
                "SELECT COUNT(*) FROM admin_logs", default=0
            ) or 0
            return {'deleted': 0, 'remaining': int(remaining)}
        except Exception as e2:
            logger.warning(f"⚠️ cleanup_old_logs fallback: {e2}")
            return {'deleted': 0, 'remaining': 0, 'error': str(e)}


async def cleanup_penalty_archive() -> Dict[str, Any]:
    """🗑️ حذف penalty_archive الأقدم من 90 يوم."""
    if DB is None:
        return {'deleted': 0, 'remaining': 0, 'error': 'DB غير متاح'}

    try:
        await DB.execute(
            f"DELETE FROM penalty_archive "
            f"WHERE created_at < NOW() - INTERVAL "
            f"'{PENALTY_ARCHIVE_RETENTION_DAYS} days'"
        )
        remaining = await DB.fetchval(
            "SELECT COUNT(*) FROM penalty_archive", default=0
        ) or 0
        logger.info(
            f"🧹 penalty_archive: retention={PENALTY_ARCHIVE_RETENTION_DAYS}d, "
            f"remaining={remaining}"
        )
        return {'deleted': 0, 'remaining': int(remaining)}
    except Exception as e:
        logger.debug(f"cleanup_penalty_archive: {e}")
        try:
            cutoff = (datetime.now(timezone.utc)
                      - timedelta(days=PENALTY_ARCHIVE_RETENTION_DAYS))
            await DB.execute(
                "DELETE FROM penalty_archive WHERE created_at < ?",
                (cutoff,),
            )
            remaining = await DB.fetchval(
                "SELECT COUNT(*) FROM penalty_archive", default=0
            ) or 0
            return {'deleted': 0, 'remaining': int(remaining)}
        except Exception as e2:
            logger.debug(f"cleanup_penalty_archive fallback: {e2}")
            return {'deleted': 0, 'remaining': 0, 'error': str(e)}


async def cleanup_violations() -> Dict[str, Any]:
    """🗑️ حذف user_violations المنتهية (> 7 أيام + action_taken)."""
    if DB is None:
        return {'deleted': 0, 'remaining': 0, 'error': 'DB غير متاح'}

    try:
        # محاولة مع action_taken
        try:
            await DB.execute(
                f"DELETE FROM user_violations "
                f"WHERE created_at < NOW() - INTERVAL "
                f"'{USER_VIOLATIONS_RETENTION_DAYS} days' "
                f"AND (action_taken = TRUE OR action_taken = 1)"
            )
        except Exception:
            # fallback: بدون action_taken
            await DB.execute(
                f"DELETE FROM user_violations "
                f"WHERE created_at < NOW() - INTERVAL "
                f"'{USER_VIOLATIONS_RETENTION_DAYS} days'"
            )

        remaining = await DB.fetchval(
            "SELECT COUNT(*) FROM user_violations", default=0
        ) or 0
        logger.info(
            f"🧹 user_violations: retention="
            f"{USER_VIOLATIONS_RETENTION_DAYS}d, remaining={remaining}"
        )
        return {'deleted': 0, 'remaining': int(remaining)}
    except Exception as e:
        logger.warning(f"⚠️ cleanup_violations: {e}")
        try:
            cutoff = (datetime.now(timezone.utc)
                      - timedelta(days=USER_VIOLATIONS_RETENTION_DAYS))
            await DB.execute(
                "DELETE FROM user_violations WHERE created_at < ?",
                (cutoff,),
            )
            remaining = await DB.fetchval(
                "SELECT COUNT(*) FROM user_violations", default=0
            ) or 0
            return {'deleted': 0, 'remaining': int(remaining)}
        except Exception as e2:
            logger.warning(f"⚠️ cleanup_violations fallback: {e2}")
            return {'deleted': 0, 'remaining': 0, 'error': str(e)}


async def cleanup_payment_logs() -> Dict[str, Any]:
    """🗑️ حذف payment_logs الأقدم من 180 يوم."""
    if DB is None:
        return {'deleted': 0, 'remaining': 0, 'error': 'DB غير متاح'}

    try:
        await DB.execute(
            f"DELETE FROM payment_logs "
            f"WHERE created_at < NOW() - INTERVAL "
            f"'{PAYMENT_LOGS_RETENTION_DAYS} days'"
        )
        remaining = await DB.fetchval(
            "SELECT COUNT(*) FROM payment_logs", default=0
        ) or 0
        logger.info(
            f"🧹 payment_logs: retention="
            f"{PAYMENT_LOGS_RETENTION_DAYS}d, remaining={remaining}"
        )
        return {'deleted': 0, 'remaining': int(remaining)}
    except Exception as e:
        logger.debug(f"cleanup_payment_logs: {e}")
        try:
            cutoff = (datetime.now(timezone.utc)
                      - timedelta(days=PAYMENT_LOGS_RETENTION_DAYS))
            await DB.execute(
                "DELETE FROM payment_logs WHERE created_at < ?",
                (cutoff,),
            )
            remaining = await DB.fetchval(
                "SELECT COUNT(*) FROM payment_logs", default=0
            ) or 0
            return {'deleted': 0, 'remaining': int(remaining)}
        except Exception as e2:
            logger.debug(f"cleanup_payment_logs fallback: {e2}")
            return {'deleted': 0, 'remaining': 0, 'error': str(e)}


# =====================================================================
# 🧹 VACUUM
# =====================================================================

async def vacuum_critical_tables() -> Dict[str, bool]:
    """
    🧹 VACUUM ANALYZE على الجداول الحرجة.

    - لو `DB.vacuum()` موجودة → يستخدمها (autocommit مضمون).
    - وإلا → fallback إلى `DB.execute()` (يعمل في وضع connection()
      بدون transaction على PostgreSQL).
    """
    if DB is None:
        return {}

    results: Dict[str, bool] = {}
    has_vacuum_method = (
        hasattr(DB, 'vacuum')
        and callable(getattr(DB, 'vacuum', None))
    )

    for table in VACUUM_TABLES:
        try:
            if has_vacuum_method:
                await DB.vacuum(table)
            else:
                await DB.execute(f"VACUUM (ANALYZE) {table}")
            results[table] = True
            logger.info(f"✅ VACUUM {table}")
        except Exception as e:
            results[table] = False
            logger.warning(f"⚠️ VACUUM {table}: {e}")

        # تأخير بين VACUUMs لتجنب القفل المتراكم
        await asyncio.sleep(0.3)

    return results


# =====================================================================
# 📸 لقطة قبل/بعد
# =====================================================================

async def get_table_snapshot(limit: int = 20) -> Dict[str, Dict[str, Any]]:
    """
    📸 لقطة سريعة لـ live/dead tuples لكل جدول (PostgreSQL فقط).

    Returns:
        {table_name: {live, dead, ratio}, ...} أو {} على غير PG
    """
    if DB is None:
        return {}

    try:
        # PostgreSQL فقط
        if not getattr(DB, 'USE_POSTGRES', False):
            return {}

        rows = await DB.fetchall(f"""
            SELECT
                relname      AS table_name,
                n_live_tup   AS live,
                n_dead_tup   AS dead
            FROM pg_stat_user_tables
            ORDER BY n_dead_tup DESC
            LIMIT {int(limit)}
        """)

        snapshot: Dict[str, Dict[str, Any]] = {}
        for r in (rows or []):
            rd = r if isinstance(r, dict) else dict(r)
            name = rd.get('table_name') or '?'
            live = int(rd.get('live', 0) or 0)
            dead = int(rd.get('dead', 0) or 0)
            total = live + dead
            ratio = (dead / total) if total > 0 else 0.0
            snapshot[name] = {
                'live': live,
                'dead': dead,
                'ratio': round(ratio, 4),
            }
        return snapshot
    except Exception as e:
        logger.debug(f"get_table_snapshot: {e}")
        return {}


# =====================================================================
# 🎯 الصيانة الرئيسية
# =====================================================================

async def daily_maintenance(
    bot=None,
    notify_admin_id: Optional[int] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    🎯 الصيانة اليومية الشاملة.

    المراحل:
      0. فحص last_maintenance_at (إلا إذا force=True)
      1. لقطة dead tuples قبل
      2. حذف سجلات قديمة (4 جداول)
      3. VACUUM ANALYZE
      4. لقطة dead tuples بعد
      5. تسجيل last_maintenance_at
      6. إرسال تقرير HTML للمالك (اختياري)

    Args:
        bot: telegram.Bot للإشعار (اختياري)
        notify_admin_id: معرّف الأدمن للإشعار (اختياري)
        force: تجاوز فحص الفاصل الزمني (افتراضي False)
    """
    start = datetime.now()
    logger.info("=" * 60)
    logger.info("🔧 بدء الصيانة اليومية")
    logger.info("=" * 60)

    report: Dict[str, Any] = {
        'started_at': start.isoformat(),
        'skipped': False,
        'skipped_reason': None,
        'admin_logs': {},
        'penalty_archive': {},
        'user_violations': {},
        'payment_logs': {},
        'vacuum': {},
        'snapshot_before': {},
        'snapshot_after': {},
        'duration_sec': 0.0,
        'errors': [],
    }

    # 🆕 v1.0.1: احترام last_maintenance_at
    if not await _should_run_maintenance(force=force):
        report['skipped'] = True
        report['skipped_reason'] = 'recent_maintenance'
        report['finished_at'] = datetime.now().isoformat()
        logger.info("⏩ maintenance: تخطي (حديثة)")
        return report

    # 1) لقطة قبل
    try:
        report['snapshot_before'] = await get_table_snapshot()
        logger.info(
            f"📸 لقطة قبل: {len(report['snapshot_before'])} جدول"
        )
    except Exception as e:
        report['errors'].append(f"snapshot_before: {e}")

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
    try:
        report['snapshot_after'] = await get_table_snapshot()
    except Exception as e:
        report['errors'].append(f"snapshot_after: {e}")

    # 5) الحساب النهائي
    end = datetime.now()
    report['duration_sec'] = round((end - start).total_seconds(), 1)
    report['finished_at'] = end.isoformat()

    logger.info("=" * 60)
    logger.info(f"✅ انتهت الصيانة في {report['duration_sec']}s")
    if report['errors']:
        logger.warning(f"⚠️ {len(report['errors'])} أخطاء:")
        for err in report['errors']:
            logger.warning(f"   • {err}")
    logger.info("=" * 60)

    # 🆕 v1.0.1: تسجيل التوقيت (بعد نجاح كل المراحل الأساسية)
    try:
        await _record_maintenance_time()
    except Exception as e:
        logger.debug(f"record time: {e}")

    # 6) إشعار المالك (اختياري)
    if bot and notify_admin_id:
        try:
            await _send_maintenance_report(
                bot=bot,
                chat_id=int(notify_admin_id),
                report=report,
            )
        except Exception as e:
            logger.warning(f"⚠️ فشل إرسال تقرير الصيانة: {e}")

    return report


async def run_maintenance_now(
    bot=None,
    notify_admin_id: Optional[int] = None,
    force: bool = True,
) -> Dict[str, Any]:
    """
    🧪 تشغيل الصيانة يدوياً الآن.

    ✅ v1.0.1: افتراضياً يتجاوز فحص last_maintenance_at
    (force=True) — مناسب للأمر اليدوي /db_vacuum.
    """
    return await daily_maintenance(
        bot=bot,
        notify_admin_id=notify_admin_id,
        force=force,
    )


# =====================================================================
# 📊 التقرير HTML
# =====================================================================

async def _send_maintenance_report(
    bot,
    chat_id: int,
    report: Dict[str, Any],
) -> None:
    """📤 إرسال تقرير HTML للمالك."""
    lines: List[str] = []

    # إذا كان تخطياً
    if report.get('skipped'):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "⏩ <b>الصيانة محدّثة</b>\n"
                    "<i>آخر صيانة كانت حديثة (أقل من 24 ساعة)</i>"
                ),
                parse_mode='HTML',
            )
        except Exception as e:
            logger.debug(f"send skip msg: {e}")
        return

    # العنوان
    lines.append("🔧 <b>تقرير الصيانة اليومية</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        f"⏱️ المدة: <b>{report.get('duration_sec', 0)}s</b>"
    )
    lines.append("")

    # الاحتفاظ والحذف
    lines.append("🗑️ <b>الاحتفاظ والحذف:</b>")
    lines.append(
        f"  • admin_logs (>{ADMIN_LOGS_RETENTION_DAYS}d): "
        f"متبقٍ <b>{report.get('admin_logs', {}).get('remaining', 0)}</b>"
    )
    lines.append(
        f"  • penalty_archive (>{PENALTY_ARCHIVE_RETENTION_DAYS}d): "
        f"متبقٍ <b>{report.get('penalty_archive', {}).get('remaining', 0)}</b>"
    )
    lines.append(
        f"  • user_violations (>{USER_VIOLATIONS_RETENTION_DAYS}d): "
        f"متبقٍ <b>{report.get('user_violations', {}).get('remaining', 0)}</b>"
    )
    lines.append(
        f"  • payment_logs (>{PAYMENT_LOGS_RETENTION_DAYS}d): "
        f"متبقٍ <b>{report.get('payment_logs', {}).get('remaining', 0)}</b>"
    )
    lines.append("")

    # VACUUM
    vacuum = report.get('vacuum', {})
    if vacuum:
        lines.append("🧹 <b>VACUUM ANALYZE:</b>")
        ok_count = sum(1 for v in vacuum.values() if v)
        fail_count = len(vacuum) - ok_count
        for table, ok in vacuum.items():
            icon = "✅" if ok else "❌"
            lines.append(f"  {icon} <code>{table}</code>")
        lines.append(
            f"  📊 النتيجة: <b>{ok_count}✅</b> / <b>{fail_count}❌</b>"
        )
        lines.append("")

    # Dead Tuples قبل/بعد
    before = report.get('snapshot_before', {})
    after = report.get('snapshot_after', {})
    if before and after:
        lines.append("📊 <b>Dead Tuples (قبل → بعد):</b>")
        diffs = []
        for table in before:
            b_dead = before[table].get('dead', 0)
            a_dead = after.get(table, {}).get('dead', 0)
            diff = b_dead - a_dead
            diffs.append((table, b_dead, a_dead, diff))
        diffs.sort(key=lambda x: x[3], reverse=True)

        shown = 0
        for table, b_dead, a_dead, diff in diffs:
            if shown >= 8:
                break
            if b_dead == 0 and a_dead == 0:
                continue
            if diff > 0:
                icon = "🟢"
                sign = f"<b>−{diff}</b>"
            elif diff == 0:
                icon = "⚪"
                sign = "0"
            else:
                icon = "🟡"
                sign = f"+{abs(diff)}"
            lines.append(
                f"  {icon} <code>{table:<20}</code> "
                f"{b_dead} → {a_dead} ({sign})"
            )
            shown += 1
        lines.append("")

    # الأخطاء
    errors = report.get('errors', [])
    if errors:
        lines.append(f"⚠️ <b>أخطاء ({len(errors)}):</b>")
        for err in errors[:5]:
            lines.append(
                f"  • <code>{_html_safe(str(err))[:80]}</code>"
            )
        lines.append("")

    # تذييل
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(
        f"🕐 <i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>"
    )

    text = "\n".join(lines)

    try:
        if len(text) <= 4000:
            await bot.send_message(
                chat_id=chat_id, text=text, parse_mode='HTML'
            )
        else:
            chunks = _split_message(text, max_len=4000)
            for chunk in chunks:
                await bot.send_message(
                    chat_id=chat_id, text=chunk, parse_mode='HTML'
                )
                await asyncio.sleep(0.5)
    except Exception as e:
        logger.warning(f"_send_maintenance_report send_message: {e}")


def _split_message(text: str, max_len: int = 4000) -> List[str]:
    """تقسيم نص طويل إلى رسائل."""
    if len(text) <= max_len:
        return [text]
    chunks: List[str] = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)
    return chunks


# =====================================================================
# 🔄 حلقة دورية — متكاملة مع main.py v5.4.3
# =====================================================================

async def maintenance_loop(
    bot=None,
    notify_admin_id: Optional[int] = None,
    interval_hours: int = 24,
    run_on_startup: bool = False,
    startup_delay_sec: int = 300,
) -> None:
    """
    🔄 حلقة صيانة دورية — مصمّمة للعمل مع:
        asyncio.create_task(run_task_with_retry(
            maintenance_loop, app.bot, owner_id, task_name="maintenance"
        ))

    Args:
        bot: telegram.Bot للإشعار
        notify_admin_id: معرّف المالك
        interval_hours: الفاصل بين الصيانات
        run_on_startup: تشغيل فوري عند الإقلاع؟
        startup_delay_sec: تأخير أول تشغيل
    """
    interval_sec = max(1, int(interval_hours)) * 3600

    # معرّف آمن
    safe_admin_id: Optional[int] = None
    if notify_admin_id is not None:
        try:
            safe_admin_id = int(notify_admin_id)
        except (TypeError, ValueError):
            logger.warning(
                f"⚠️ notify_admin_id غير صالح: {notify_admin_id!r}"
            )

    logger.info(
        f"🔧 maintenance_loop بدأ — "
        f"interval={interval_hours}h, "
        f"startup={'now+' + str(startup_delay_sec) + 's' if run_on_startup else 'after 1 interval'}"
    )

    # التشغيل الأول
    if run_on_startup:
        logger.info(
            f"⏳ maintenance_loop: أول تشغيل خلال {startup_delay_sec}s"
        )
        await asyncio.sleep(startup_delay_sec)
    else:
        logger.info(
            f"⏳ maintenance_loop: أول تشغيل بعد {interval_hours}h"
        )
        await asyncio.sleep(interval_sec)

    # الحلقة
    iteration = 0
    while True:
        iteration += 1
        try:
            logger.info(
                f"🔧 maintenance_loop #{iteration}: بدء الصيانة"
            )
            # في الحلقة التلقائية: force=False → احترام last_maintenance_at
            report = await daily_maintenance(
                bot=bot,
                notify_admin_id=safe_admin_id,
                force=False,
            )
            if report.get('skipped'):
                logger.info(
                    f"⏩ maintenance_loop #{iteration}: "
                    f"تخطي — {report.get('skipped_reason', '?')}"
                )
            else:
                logger.info(
                    f"✅ maintenance_loop #{iteration}: "
                    f"انتهت في {report['duration_sec']}s"
                )
        except asyncio.CancelledError:
            logger.info("🛑 maintenance_loop: أُلغيت")
            raise
        except Exception as e:
            logger.error(
                f"❌ maintenance_loop #{iteration}: {e}",
                exc_info=True,
            )

        try:
            await asyncio.sleep(interval_sec)
        except asyncio.CancelledError:
            logger.info("🛑 maintenance_loop: sleep أُلغي")
            raise


# =====================================================================
# 🔌 دعم job_queue (اختياري)
# =====================================================================

def register_maintenance_job(
    app,
    notify_admin_id: Optional[int] = None,
    hour: int = 3,
    minute: int = 0,
) -> bool:
    """
    🔌 تسجيل الصيانة في job_queue (اختياري).

    ملاحظة: main.py v5.4.3 يستخدم run_task_with_retry بدلاً من
    job_queue. هذه الدالة موجودة فقط للتوافق مع أنماط أخرى.

    Args:
        app: telegram.ext.Application
        notify_admin_id: معرّف المالك
        hour: الساعة (0-23)
        minute: الدقيقة (0-59)

    Returns:
        True إذا نجح، False خلاف ذلك
    """
    if not hasattr(app, 'job_queue') or app.job_queue is None:
        logger.warning(
            "⚠️ job_queue غير متوفر — استخدم maintenance_loop مع "
            "asyncio.create_task"
        )
        return False

    try:
        tz = None
        if ZoneInfo is not None:
            try:
                tz = ZoneInfo(MAINTENANCE_TZ)
            except Exception as e:
                logger.debug(f"ZoneInfo({MAINTENANCE_TZ}): {e}")

        safe_admin_id: Optional[int] = None
        if notify_admin_id is not None:
            try:
                safe_admin_id = int(notify_admin_id)
            except (TypeError, ValueError):
                pass

        run_time = time(
            hour=int(hour), minute=int(minute), tzinfo=tz
        )

        async def _job(context):
            try:
                await daily_maintenance(
                    bot=context.bot,
                    notify_admin_id=safe_admin_id,
                    force=False,
                )
            except Exception as e:
                logger.error(
                    f"❌ maintenance job: {e}", exc_info=True
                )

        app.job_queue.run_daily(
            _job,
            time=run_time,
            name="daily_maintenance",
        )
        logger.info(
            f"✅ register_maintenance_job: "
            f"{int(hour):02d}:{int(minute):02d} "
            f"{MAINTENANCE_TZ if tz else 'UTC'}"
        )
        return True
    except Exception as e:
        logger.error(
            f"❌ register_maintenance_job: {e}", exc_info=True
        )
        return False


# =====================================================================
# 🧰 أدوات مساعدة
# =====================================================================

def _safe_int(value, default: int = 0) -> int:
    """تحويل آمن إلى int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _html_safe(text: str) -> str:
    """تهريب HTML."""
    try:
        import html as _h
        return _h.escape(str(text))
    except Exception:
        return str(text)


# =====================================================================
# 📤 التصدير
# =====================================================================

__all__ = [
    # الرئيسية
    "daily_maintenance",
    "run_maintenance_now",
    "maintenance_loop",
    "register_maintenance_job",
    # التنظيف
    "cleanup_old_logs",
    "cleanup_penalty_archive",
    "cleanup_violations",
    "cleanup_payment_logs",
    # VACUUM
    "vacuum_critical_tables",
    # التشخيص
    "get_table_snapshot",
    # الثوابت
    "ADMIN_LOGS_RETENTION_DAYS",
    "PENALTY_ARCHIVE_RETENTION_DAYS",
    "USER_VIOLATIONS_RETENTION_DAYS",
    "PAYMENT_LOGS_RETENTION_DAYS",
    "VACUUM_TABLES",
    "MAINTENANCE_TZ",
    "MAINTENANCE_INTERVAL_SECONDS",
    "LAST_MAINTENANCE_KEY",
]