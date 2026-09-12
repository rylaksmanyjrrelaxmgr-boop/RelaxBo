#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
database_reminders.py - دوال التذكيرات (Mixin) — v1.1
================================================================================
Mixin يُضاف إلى فئة Database في database.py

المجموعات:
  1️⃣  إعدادات التذكيرات (Reminder Settings)
  2️⃣  دوال الاستعلام للتذكيرات (Query Reminders)
  3️⃣  دوال الإرسال (Send Reminders)
  4️⃣  إحصائيات
  5️⃣  ترحيل الأعمدة (Migration)

⚠️ المتطلبات (يجب توفرها في الفئة الأم Database):
  - self.DB_TYPE, self.USE_POSTGRES, self.USE_MYSQL
  - self.TimeUtils
  - self.internal_cache
  - self.fetchone, self.fetchall, self.fetchval, self.execute
  - self.connection, self.transaction
  - self._fetchval_with_conn, self._fetchone_with_conn, self._fetchall_with_conn
  - self._execute_with_conn, self._executemany_with_conn

🆕 v1.1 — إصلاحات جوهرية:
  ✅ استخدام datetime مباشرة (بدل sql_iso مع +00:00)
  ✅ INTERVAL يستخدم reminder_days_before الفعلي
  ✅ last_daily_sent / last_weekly_sent / last_subscription_sent منفصلة
  ✅ إزالة N+1 queries في send_subscription_reminders
  ✅ EXTRACT(EPOCH)/86400 بدل EXTRACT(DAY)
  ✅ get_reminder_stats في استعلام واحد
  ✅ _send_reminders_generic لتوحيد daily/weekly
  ✅ notification_lang يستخدم u.language كـ fallback
  ✅ reset_reminder_settings يُنشئ الصف إن لم يوجد
  ✅ reminder_days_before مُقيّد بـ 1-30
  ✅ validation على notification_lang
  ✅ إبطال user_cache عند التحديث
  ✅ datetime.now(timezone.utc) بدل utcnow()
  ✅ migrate_reminders_columns() للأعمدة الجديدة
  ✅ send_*_reminders تُرجع dict

🆕 v1.0 (متوافق مع database.py v7.5.8):
  - إدارة إعدادات التذكيرات لكل مستخدم
  - دوال إرسال التذكيرات
  - جلب الاشتراكات المنتهية قريباً
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Callable, Awaitable

logger = logging.getLogger(__name__)


# =====================================================================
# استيراد التكوينات (بحماية)
# =====================================================================

try:
    from config import CONFIG
except ImportError:
    class CONFIG:
        DEFAULT_REMINDER_DAYS_BEFORE = 3


# =====================================================================
# ثوابت
# =====================================================================

DEFAULT_REMINDER_DAYS_BEFORE = 3
MIN_REMINDER_DAYS_BEFORE = 1
MAX_REMINDER_DAYS_BEFORE = 30

VALID_NOTIFICATION_LANGS = {
    "ar", "en", "fr", "tr", "zh", "ru", "de", "es", "it", "pt",
    "ja", "ko", "fa", "ur", "nl", "pl", "hi",
}

# ✅ الفاصل الزمني بين التذكيرات (بالساعات/الأيام)
DAILY_REMINDER_HOURS = 20
WEEKLY_REMINDER_DAYS = 6

# ✅ حد أقصى افتراضي للاستعلامات
DEFAULT_QUERY_LIMIT = 500
DEFAULT_BULK_BATCH = 500

# ✅ الأعمدة المسموح تحديثها
ALLOWED_UPDATE_COLUMNS = {
    "subscription_reminder",
    "daily_stats_reminder",
    "weekly_report",
    "reminder_days_before",
    "notification_lang",
}


# =====================================================================
# RemindersMixin
# =====================================================================

class RemindersMixin:
    """
    Mixin لدوال التذكيرات.

    يعتمد على الخصائص التالية في الفئة الأم:
      - self.DB_TYPE          : "sqlite" | "postgres" | "mysql"
      - self.TimeUtils        : فئة TimeUtils
      - self.internal_cache   : InternalQueryCache
      - دوال fetchone/fetchall/fetchval/execute
      - دوال connection/transaction
    """

    # =================================================================
    # دوال داخلية مساعدة
    # =================================================================

    def _is_postgres_reminders(self) -> bool:
        return getattr(self, "DB_TYPE", "sqlite") == "postgres"

    def _is_mysql_reminders(self) -> bool:
        return getattr(self, "DB_TYPE", "sqlite") == "mysql"

    def _now_utc_reminders(self) -> datetime:
        """✅ v1.1: datetime نظيف (بدون tz) — للاستخدام في الاستعلامات."""
        try:
            return self.TimeUtils.utc_now()
        except Exception:
            return datetime.now(timezone.utc).replace(tzinfo=None)

    def _default_settings_reminders(self, user_id: int) -> Dict:
        """✅ v1.1: القيم الافتراضية الموحّدة."""
        return {
            "user_id": user_id,
            "subscription_reminder": 1,
            "daily_stats_reminder": 0,
            "weekly_report": 1,
            "reminder_days_before": DEFAULT_REMINDER_DAYS_BEFORE,
            "last_daily_sent": None,
            "last_weekly_sent": None,
            "last_subscription_sent": None,
            "last_reminder_sent": None,  # للتوافق العكسي
            "notification_lang": "ar",
        }

    async def _invalidate_user_reminder_cache(self, user_id: int):
        """✅ v1.1: إبطال كل الكاشات المتعلقة بالمستخدم."""
        try:
            await self.internal_cache.invalidate(f"reminder_settings_{user_id}")
            await self.internal_cache.invalidate(f"user_{user_id}")
            await self.internal_cache.invalidate(f"user_{user_id}_True")
            await self.internal_cache.invalidate(f"user_{user_id}_False")
        except Exception as e:
            logger.debug(f"_invalidate_user_reminder_cache: {e}")

        # محاولة استخدام cache.py إن وُجد
        try:
            from cache import invalidate_user_cache
            await invalidate_user_cache(user_id)
        except (ImportError, Exception):
            pass

    # =================================================================
    # 1️⃣  إعدادات التذكيرات (Reminder Settings)
    # =================================================================

    async def get_reminder_settings(self, user_id: int) -> Dict:
        """
        جلب إعدادات التذكير للمستخدم (مع إنشاء افتراضي إن لم يوجد).

        Returns:
            {
                "user_id": int,
                "subscription_reminder": int (0/1),
                "daily_stats_reminder": int (0/1),
                "weekly_report": int (0/1),
                "reminder_days_before": int,
                "last_daily_sent": datetime | None,
                "last_weekly_sent": datetime | None,
                "last_subscription_sent": datetime | None,
                "notification_lang": str,
            }
        """
        try:
            cache_key = f"reminder_settings_{user_id}"
            cached = await self.internal_cache.get(cache_key)
            if cached is not None:
                return cached

            row = await self.fetchone(
                "SELECT * FROM user_reminder_settings WHERE user_id = ?",
                (user_id,),
            )

            if row:
                settings = dict(row)
                # ✅ v1.1: توافق عكسي — إذا لم توجد أعمدة جديدة، استخدم last_reminder_sent
                if "last_daily_sent" not in settings:
                    settings["last_daily_sent"] = settings.get("last_reminder_sent")
                if "last_weekly_sent" not in settings:
                    settings["last_weekly_sent"] = settings.get("last_reminder_sent")
                if "last_subscription_sent" not in settings:
                    settings["last_subscription_sent"] = settings.get("last_reminder_sent")
            else:
                # إنشاء صف افتراضي
                try:
                    await self.execute(
                        """INSERT OR IGNORE INTO user_reminder_settings
                           (user_id, subscription_reminder, daily_stats_reminder,
                            weekly_report, reminder_days_before, notification_lang)
                           VALUES (?, 1, 0, 1, ?, 'ar')""",
                        (user_id, DEFAULT_REMINDER_DAYS_BEFORE),
                    )
                except Exception as e:
                    logger.warning(
                        f"⚠️ فشل إنشاء صف تذكيرات لـ {user_id}: {e}"
                    )
                settings = self._default_settings_reminders(user_id)

            await self.internal_cache.set(cache_key, settings, ttl=60)
            return settings

        except Exception as e:
            logger.error(f"❌ Error in get_reminder_settings: {e}", exc_info=True)
            return self._default_settings_reminders(user_id)

    async def update_reminder_settings(self, user_id: int, **kwargs) -> bool:
        """
        تحديث إعدادات التذكير.

        Allowed columns:
          - subscription_reminder (bool/int)
          - daily_stats_reminder (bool/int)
          - weekly_report (bool/int)
          - reminder_days_before (int, 1-30)
          - notification_lang (str, في VALID_NOTIFICATION_LANGS)

        Returns:
            True عند النجاح
        """
        try:
            # ✅ v1.1: فحص الأعمدة
            invalid = [k for k in kwargs if k not in ALLOWED_UPDATE_COLUMNS]
            if invalid:
                logger.error(f"❌ Invalid columns: {invalid}")
                return False

            if not kwargs:
                return False

            # ✅ v1.1: تحويل القيم + validation
            params_dict: Dict[str, Any] = {}
            for k, v in kwargs.items():
                if k in ("subscription_reminder", "daily_stats_reminder", "weekly_report"):
                    params_dict[k] = 1 if v else 0
                elif k == "reminder_days_before":
                    try:
                        days = int(v)
                    except (TypeError, ValueError):
                        logger.error(f"❌ reminder_days_before غير رقمي: {v}")
                        return False
                    if not (MIN_REMINDER_DAYS_BEFORE <= days <= MAX_REMINDER_DAYS_BEFORE):
                        logger.error(
                            f"❌ reminder_days_before خارج النطاق: {days} "
                            f"(يجب أن يكون {MIN_REMINDER_DAYS_BEFORE}-{MAX_REMINDER_DAYS_BEFORE})"
                        )
                        return False
                    params_dict[k] = days
                elif k == "notification_lang":
                    lang = str(v).strip().lower() if v else "ar"
                    if lang not in VALID_NOTIFICATION_LANGS:
                        logger.error(f"❌ notification_lang غير مدعوم: {v}")
                        return False
                    params_dict[k] = lang
                else:
                    params_dict[k] = v

            # ضمان وجود الصف
            exists = await self.fetchval(
                "SELECT 1 FROM user_reminder_settings WHERE user_id = ?",
                (user_id,),
            )
            if not exists:
                try:
                    await self.execute(
                        """INSERT INTO user_reminder_settings
                           (user_id, subscription_reminder, daily_stats_reminder,
                            weekly_report, reminder_days_before, notification_lang)
                           VALUES (?, 1, 0, 1, ?, 'ar')""",
                        (user_id, DEFAULT_REMINDER_DAYS_BEFORE),
                    )
                except Exception as e:
                    logger.warning(f"⚠️ فشل إنشاء صف تذكيرات: {e}")
                    return False

            # ✅ v1.1: بناء UPDATE ديناميكي آمن
            # (params_dict.keys() كلها في ALLOWED_UPDATE_COLUMNS)
            updates = ", ".join([f"{k} = ?" for k in params_dict.keys()])
            values = list(params_dict.values()) + [user_id]
            query = f"UPDATE user_reminder_settings SET {updates} WHERE user_id = ?"

            result = await self.execute(query, tuple(values)) > 0

            if result:
                await self._invalidate_user_reminder_cache(user_id)
            return result

        except Exception as e:
            logger.error(f"❌ Error in update_reminder_settings: {e}", exc_info=True)
            return False

    async def reset_reminder_settings(self, user_id: int) -> bool:
        """
        ✅ v1.1: إعادة تعيين الإعدادات للافتراضي.
        يُنشئ الصف إن لم يكن موجودًا (بدل الفشل الصامت).
        """
        try:
            # ✅ v1.1: INSERT OR IGNORE أولاً لضمان وجود الصف
            await self.execute(
                """INSERT OR IGNORE INTO user_reminder_settings
                   (user_id, subscription_reminder, daily_stats_reminder,
                    weekly_report, reminder_days_before, notification_lang)
                   VALUES (?, 1, 0, 1, ?, 'ar')""",
                (user_id, DEFAULT_REMINDER_DAYS_BEFORE),
            )

            result = await self.execute(
                """UPDATE user_reminder_settings SET
                       subscription_reminder = 1,
                       daily_stats_reminder = 0,
                       weekly_report = 1,
                       reminder_days_before = ?,
                       notification_lang = 'ar'
                   WHERE user_id = ?""",
                (DEFAULT_REMINDER_DAYS_BEFORE, user_id),
            ) > 0

            await self._invalidate_user_reminder_cache(user_id)
            return result

        except Exception as e:
            logger.error(f"❌ Error in reset_reminder_settings: {e}", exc_info=True)
            return False

    # =================================================================
    # 2️⃣  دوال الاستعلام للتذكيرات (Query Reminders)
    # =================================================================

    async def get_users_for_daily_reminder(self, limit: int = DEFAULT_QUERY_LIMIT) -> List[Dict]:
        """
        ✅ v1.1: جلب المستخدمين الذين يريدون تذكيراً يومياً.
        يستخدم last_daily_sent (بدل last_reminder_sent المشترك).
        """
        try:
            limit = max(1, min(limit, 1000))

            if self._is_postgres_reminders():
                query = """
                    SELECT u.user_id, u.first_name, u.language,
                           COALESCE(urs.notification_lang, u.language, 'ar')
                               AS notification_lang
                    FROM users u
                    JOIN user_reminder_settings urs ON u.user_id = urs.user_id
                    WHERE urs.daily_stats_reminder = 1
                      AND u.banned = 0
                      AND (
                        urs.last_daily_sent IS NULL
                        OR urs.last_daily_sent < NOW() - INTERVAL '20 hours'
                      )
                    ORDER BY u.user_id
                    LIMIT $1
                """
                return await self.fetchall(query, (limit,))
            elif self._is_mysql_reminders():
                query = """
                    SELECT u.user_id, u.first_name, u.language,
                           COALESCE(urs.notification_lang, u.language, 'ar')
                               AS notification_lang
                    FROM users u
                    JOIN user_reminder_settings urs ON u.user_id = urs.user_id
                    WHERE urs.daily_stats_reminder = 1
                      AND u.banned = 0
                      AND (
                        urs.last_daily_sent IS NULL
                        OR urs.last_daily_sent < UTC_TIMESTAMP() - INTERVAL 20 HOUR
                      )
                    ORDER BY u.user_id
                    LIMIT %s
                """
                return await self.fetchall(query, (limit,))
            else:
                query = """
                    SELECT u.user_id, u.first_name, u.language,
                           COALESCE(urs.notification_lang, u.language, 'ar')
                               AS notification_lang
                    FROM users u
                    JOIN user_reminder_settings urs ON u.user_id = urs.user_id
                    WHERE urs.daily_stats_reminder = 1
                      AND u.banned = 0
                      AND (
                        urs.last_daily_sent IS NULL
                        OR urs.last_daily_sent < datetime('now', '-20 hours')
                      )
                    ORDER BY u.user_id
                    LIMIT ?
                """
                return await self.fetchall(query, (limit,))
        except Exception as e:
            logger.error(
                f"❌ Error in get_users_for_daily_reminder: {e}", exc_info=True
            )
            return []

    async def get_users_for_weekly_reminder(self, limit: int = DEFAULT_QUERY_LIMIT) -> List[Dict]:
        """
        ✅ v1.1: جلب المستخدمين الذين يريدون تقريراً أسبوعياً.
        يستخدم last_weekly_sent (بدل last_reminder_sent المشترك).
        """
        try:
            limit = max(1, min(limit, 1000))

            if self._is_postgres_reminders():
                query = """
                    SELECT u.user_id, u.first_name, u.language,
                           COALESCE(urs.notification_lang, u.language, 'ar')
                               AS notification_lang
                    FROM users u
                    JOIN user_reminder_settings urs ON u.user_id = urs.user_id
                    WHERE urs.weekly_report = 1
                      AND u.banned = 0
                      AND (
                        urs.last_weekly_sent IS NULL
                        OR urs.last_weekly_sent < NOW() - INTERVAL '6 days'
                      )
                    ORDER BY u.user_id
                    LIMIT $1
                """
                return await self.fetchall(query, (limit,))
            elif self._is_mysql_reminders():
                query = """
                    SELECT u.user_id, u.first_name, u.language,
                           COALESCE(urs.notification_lang, u.language, 'ar')
                               AS notification_lang
                    FROM users u
                    JOIN user_reminder_settings urs ON u.user_id = urs.user_id
                    WHERE urs.weekly_report = 1
                      AND u.banned = 0
                      AND (
                        urs.last_weekly_sent IS NULL
                        OR urs.last_weekly_sent < UTC_TIMESTAMP() - INTERVAL 6 DAY
                      )
                    ORDER BY u.user_id
                    LIMIT %s
                """
                return await self.fetchall(query, (limit,))
            else:
                query = """
                    SELECT u.user_id, u.first_name, u.language,
                           COALESCE(urs.notification_lang, u.language, 'ar')
                               AS notification_lang
                    FROM users u
                    JOIN user_reminder_settings urs ON u.user_id = urs.user_id
                    WHERE urs.weekly_report = 1
                      AND u.banned = 0
                      AND (
                        urs.last_weekly_sent IS NULL
                        OR urs.last_weekly_sent < datetime('now', '-6 days')
                      )
                    ORDER BY u.user_id
                    LIMIT ?
                """
                return await self.fetchall(query, (limit,))

        except Exception as e:
            logger.error(
                f"❌ Error in get_users_for_weekly_reminder: {e}", exc_info=True
            )
            return []

    async def get_subscriptions_ending_soon(self, limit: int = DEFAULT_QUERY_LIMIT) -> List[Dict]:
        """
        ✅ v1.1: جلب الاشتراكات التي تنتهي قريباً.
        - يستخدم reminder_days_before الفعلي من DB (بدل 7 أيام ثابت).
        - يستخدم EXTRACT(EPOCH)/86400 للحصول على أيام دقيقة.
        - يُرجع reminder_days_before ضمن النتائج (يمنع N+1).

        Returns:
            قائمة من {user_id, end_date, days_remaining, reminder_days_before, notification_lang}
        """
        try:
            limit = max(1, min(limit, 1000))

            if self._is_postgres_reminders():
                query = """
                    SELECT
                        s.user_id,
                        MAX(s.end_date) AS end_date,
                        GREATEST(
                            0,
                            FLOOR(
                                EXTRACT(EPOCH FROM (MAX(s.end_date) - NOW())) / 86400
                            )
                        )::int AS days_remaining,
                        COALESCE(urs.reminder_days_before, 3) AS reminder_days_before,
                        COALESCE(urs.notification_lang, u.language, 'ar')
                            AS notification_lang
                    FROM subscriptions s
                    LEFT JOIN user_reminder_settings urs
                        ON urs.user_id = s.user_id
                    LEFT JOIN users u
                        ON u.user_id = s.user_id
                    WHERE s.status = 'active'
                      AND s.end_date > NOW()
                      AND s.end_date <= NOW()
                          + (COALESCE(urs.reminder_days_before, 3) || ' days')::interval
                      AND (urs.subscription_reminder IS NULL
                           OR urs.subscription_reminder = 1)
                    GROUP BY s.user_id, urs.reminder_days_before,
                             urs.notification_lang, u.language
                    ORDER BY end_date ASC
                    LIMIT $1
                """
                return await self.fetchall(query, (limit,))

            elif self._is_mysql_reminders():
                query = """
                    SELECT
                        s.user_id,
                        MAX(s.end_date) AS end_date,
                        GREATEST(
                            0,
                            DATEDIFF(MAX(s.end_date), UTC_TIMESTAMP())
                        ) AS days_remaining,
                        COALESCE(urs.reminder_days_before, 3) AS reminder_days_before,
                        COALESCE(urs.notification_lang, u.language, 'ar')
                            AS notification_lang
                    FROM subscriptions s
                    LEFT JOIN user_reminder_settings urs
                        ON urs.user_id = s.user_id
                    LEFT JOIN users u
                        ON u.user_id = s.user_id
                    WHERE s.status = 'active'
                      AND s.end_date > UTC_TIMESTAMP()
                      AND s.end_date <= DATE_ADD(
                              UTC_TIMESTAMP(),
                              INTERVAL COALESCE(urs.reminder_days_before, 3) DAY
                          )
                      AND (urs.subscription_reminder IS NULL
                           OR urs.subscription_reminder = 1)
                    GROUP BY s.user_id, urs.reminder_days_before,
                             urs.notification_lang, u.language
                    ORDER BY end_date ASC
                    LIMIT %s
                """
                return await self.fetchall(query, (limit,))

            else:  # SQLite
                query = """
                    SELECT
                        s.user_id,
                        MAX(s.end_date) AS end_date,
                        MAX(
                            0,
                            CAST(
                                (julianday(MAX(s.end_date)) - julianday('now'))
                                AS INTEGER
                            )
                        ) AS days_remaining,
                        COALESCE(urs.reminder_days_before, 3) AS reminder_days_before,
                        COALESCE(urs.notification_lang, u.language, 'ar')
                            AS notification_lang
                    FROM subscriptions s
                    LEFT JOIN user_reminder_settings urs
                        ON urs.user_id = s.user_id
                    LEFT JOIN users u
                        ON u.user_id = s.user_id
                    WHERE s.status = 'active'
                      AND s.end_date > datetime('now')
                      AND s.end_date <= datetime(
                              'now',
                              '+' || COALESCE(urs.reminder_days_before, 3) || ' days'
                          )
                      AND (urs.subscription_reminder IS NULL
                           OR urs.subscription_reminder = 1)
                    GROUP BY s.user_id, urs.reminder_days_before,
                             urs.notification_lang, u.language
                    ORDER BY end_date ASC
                    LIMIT ?
                """
                return await self.fetchall(query, (limit,))

        except Exception as e:
            logger.error(
                f"❌ Error in get_subscriptions_ending_soon: {e}", exc_info=True
            )
            return []

    # =================================================================
    # 3️⃣  دوال الإرسال (Send Reminders)
    # =================================================================

    async def mark_reminder_sent(
        self, user_id: int, reminder_type: str = "daily"
    ) -> bool:
        """
        ✅ v1.1: تحديث حقل last_*_sent المناسب.

        Args:
            reminder_type: "daily" | "weekly" | "subscription"
        """
        try:
            column_map = {
                "daily": "last_daily_sent",
                "weekly": "last_weekly_sent",
                "subscription": "last_subscription_sent",
            }
            col = column_map.get(reminder_type)
            if not col:
                logger.error(f"❌ reminder_type غير معروف: {reminder_type}")
                return False

            now_dt = self._now_utc_reminders()  # ✅ datetime نظيف

            result = await self.execute(
                f"UPDATE user_reminder_settings "
                f"SET {col} = ?, last_reminder_sent = ? "
                f"WHERE user_id = ?",
                (now_dt, now_dt, user_id),
            ) > 0

            if result:
                await self._invalidate_user_reminder_cache(user_id)
            return result

        except Exception as e:
            logger.error(f"❌ Error in mark_reminder_sent: {e}", exc_info=True)
            return False

    async def mark_reminders_sent_bulk(
        self, user_ids: List[int], reminder_type: str = "daily"
    ) -> int:
        """
        ✅ v1.1: تحديث جماعي مع نفس منطق mark_reminder_sent.
        """
        if not user_ids:
            return 0

        try:
            column_map = {
                "daily": "last_daily_sent",
                "weekly": "last_weekly_sent",
                "subscription": "last_subscription_sent",
            }
            col = column_map.get(reminder_type)
            if not col:
                logger.error(f"❌ reminder_type غير معروف: {reminder_type}")
                return 0

            now_dt = self._now_utc_reminders()

            total = 0
            for i in range(0, len(user_ids), DEFAULT_BULK_BATCH):
                batch = user_ids[i : i + DEFAULT_BULK_BATCH]
                placeholders = ",".join(["?"] * len(batch))

                updated = await self.execute(
                    f"UPDATE user_reminder_settings "
                    f"SET {col} = ?, last_reminder_sent = ? "
                    f"WHERE user_id IN ({placeholders})",
                    (now_dt, now_dt, *batch),
                )
                total += updated or 0

                for uid in batch:
                    await self._invalidate_user_reminder_cache(uid)

            return total

        except Exception as e:
            logger.error(
                f"❌ Error in mark_reminders_sent_bulk: {e}", exc_info=True
            )
            return 0

    async def send_subscription_reminders(
        self,
        reminder_func: Callable[[int, int, str], Awaitable[bool]],
    ) -> Dict[str, int]:
        """
        ✅ v1.1: إرسال تذكيرات الاشتراك.
        - لا N+1 queries (reminder_days_before ضمن النتائج).
        - يُحدّث last_subscription_sent فقط عند النجاح.
        - يُرجع dict مع sent/skipped/failed.

        Args:
            reminder_func: async def f(user_id, days_left, lang) -> bool
        """
        result = {"sent": 0, "skipped": 0, "failed": 0}
        try:
            users = await self.get_subscriptions_ending_soon(limit=DEFAULT_QUERY_LIMIT)
            if not users:
                return result

            sent_ids: List[int] = []
            for row in users:
                try:
                    user_id = row.get("user_id")
                    if not user_id:
                        result["skipped"] += 1
                        continue

                    days_left = int(row.get("days_remaining") or 0)
                    lang = row.get("notification_lang") or "ar"
                    days_before = int(
                        row.get("reminder_days_before") or DEFAULT_REMINDER_DAYS_BEFORE
                    )

                    # ✅ v1.1: نتخطى إذا لم يحن الوقت بعد
                    if days_left <= 0:
                        result["skipped"] += 1
                        continue
                    if days_left > days_before:
                        result["skipped"] += 1
                        continue

                    ok = await reminder_func(user_id, days_left, lang)
                    if ok:
                        result["sent"] += 1
                        sent_ids.append(user_id)
                    else:
                        result["failed"] += 1

                except Exception as e:
                    result["failed"] += 1
                    logger.warning(
                        f"⚠️ فشل إرسال تذكير اشتراك لـ {row.get('user_id')}: {e}"
                    )

            if sent_ids:
                await self.mark_reminders_sent_bulk(
                    sent_ids, reminder_type="subscription"
                )

            logger.info(
                f"📨 تذكيرات الاشتراك: ✅ {result['sent']} | "
                f"⏭️ {result['skipped']} | ❌ {result['failed']}"
            )
            return result

        except Exception as e:
            logger.error(
                f"❌ Error in send_subscription_reminders: {e}", exc_info=True
            )
            return result

    async def _send_reminders_generic(
        self,
        users: List[Dict],
        reminder_func: Callable[[int, str], Awaitable[bool]],
        reminder_type: str,
    ) -> Dict[str, int]:
        """
        ✅ v1.1: دالة موحّدة لإرسال daily/weekly reminders.
        """
        result = {"sent": 0, "skipped": 0, "failed": 0}
        if not users:
            return result

        sent_ids: List[int] = []
        for row in users:
            try:
                user_id = row.get("user_id")
                if not user_id:
                    result["skipped"] += 1
                    continue

                lang = row.get("notification_lang") or row.get("language") or "ar"
                ok = await reminder_func(user_id, lang)
                if ok:
                    result["sent"] += 1
                    sent_ids.append(user_id)
                else:
                    result["failed"] += 1

            except Exception as e:
                result["failed"] += 1
                logger.warning(
                    f"⚠️ فشل إرسال {reminder_type} لـ {row.get('user_id')}: {e}"
                )

        if sent_ids:
            await self.mark_reminders_sent_bulk(sent_ids, reminder_type=reminder_type)

        logger.info(
            f"📨 {reminder_type}: ✅ {result['sent']} | "
            f"⏭️ {result['skipped']} | ❌ {result['failed']}"
        )
        return result

    async def send_daily_reminders(
        self,
        reminder_func: Callable[[int, str], Awaitable[bool]],
    ) -> Dict[str, int]:
        """
        ✅ v1.1: إرسال تذكيرات يومية.
        Args:
            reminder_func: async def f(user_id, lang) -> bool
        """
        try:
            users = await self.get_users_for_daily_reminder(limit=DEFAULT_QUERY_LIMIT)
            return await self._send_reminders_generic(users, reminder_func, "daily")
        except Exception as e:
            logger.error(f"❌ Error in send_daily_reminders: {e}", exc_info=True)
            return {"sent": 0, "skipped": 0, "failed": 0}

    async def send_weekly_reminders(
        self,
        reminder_func: Callable[[int, str], Awaitable[bool]],
    ) -> Dict[str, int]:
        """
        ✅ v1.1: إرسال تقارير أسبوعية.
        Args:
            reminder_func: async def f(user_id, lang) -> bool
        """
        try:
            users = await self.get_users_for_weekly_reminder(limit=DEFAULT_QUERY_LIMIT)
            return await self._send_reminders_generic(users, reminder_func, "weekly")
        except Exception as e:
            logger.error(f"❌ Error in send_weekly_reminders: {e}", exc_info=True)
            return {"sent": 0, "skipped": 0, "failed": 0}

    # =================================================================
    # 4️⃣  إحصائيات
    # =================================================================

    async def get_reminder_stats(self) -> Dict:
        """
        ✅ v1.1: إحصائيات إعدادات التذكيرات (استعلام واحد).

        Returns:
            {
                "total_users": int,
                "subscription_reminder": int,
                "daily_stats_reminder": int,
                "weekly_report": int,
            }
        """
        try:
            async with self.connection() as conn:
                row = await self._fetchone_with_conn(
                    conn,
                    """SELECT
                           COUNT(*) AS total_users,
                           COALESCE(SUM(CASE WHEN subscription_reminder = 1
                                             THEN 1 ELSE 0 END), 0)
                               AS subscription_reminder,
                           COALESCE(SUM(CASE WHEN daily_stats_reminder = 1
                                             THEN 1 ELSE 0 END), 0)
                               AS daily_stats_reminder,
                           COALESCE(SUM(CASE WHEN weekly_report = 1
                                             THEN 1 ELSE 0 END), 0)
                               AS weekly_report
                       FROM user_reminder_settings""",
                )
            if row:
                return {
                    "total_users": int(row.get("total_users") or 0),
                    "subscription_reminder": int(row.get("subscription_reminder") or 0),
                    "daily_stats_reminder": int(row.get("daily_stats_reminder") or 0),
                    "weekly_report": int(row.get("weekly_report") or 0),
                }
            return {
                "total_users": 0,
                "subscription_reminder": 0,
                "daily_stats_reminder": 0,
                "weekly_report": 0,
            }
        except Exception as e:
            logger.error(f"❌ Error in get_reminder_stats: {e}", exc_info=True)
            return {
                "total_users": 0,
                "subscription_reminder": 0,
                "daily_stats_reminder": 0,
                "weekly_report": 0,
            }

    # =================================================================
    # 5️⃣  ترحيل الأعمدة (Migration)
    # =================================================================

    async def migrate_reminders_columns(self) -> bool:
        """
        ✅ v1.1: إضافة الأعمدة الجديدة (last_daily_sent, etc.) إذا لم تكن موجودة.
        آمن للاستدعاء المتكرر (IF NOT EXISTS).
        """
        new_columns = [
            ("last_daily_sent", "TIMESTAMP"),
            ("last_weekly_sent", "TIMESTAMP"),
            ("last_subscription_sent", "TIMESTAMP"),
        ]

        success = True
        try:
            async with self.connection() as conn:
                for col_name, col_type in new_columns:
                    try:
                        # فحص وجود العمود
                        if self._is_postgres_reminders():
                            exists = await self._fetchval_with_conn(
                                conn,
                                "SELECT 1 FROM information_schema.columns "
                                "WHERE table_name = 'user_reminder_settings' "
                                "AND column_name = $1",
                                col_name,
                            )
                            if not exists:
                                await conn.execute(
                                    f'ALTER TABLE user_reminder_settings '
                                    f'ADD COLUMN "{col_name}" {col_type}'
                                )
                                logger.info(
                                    f"✅ أُضيف العمود {col_name} إلى user_reminder_settings"
                                )
                        elif self._is_mysql_reminders():
                            cursor = await conn.cursor()
                            await cursor.execute(
                                "SHOW COLUMNS FROM user_reminder_settings LIKE %s",
                                (col_name,),
                            )
                            exists = await cursor.fetchone()
                            await cursor.close()
                            if not exists:
                                await conn.execute(
                                    f"ALTER TABLE user_reminder_settings "
                                    f"ADD COLUMN `{col_name}` {col_type}"
                                )
                                logger.info(
                                    f"✅ أُضيف العمود {col_name} إلى user_reminder_settings"
                                )
                        else:  # SQLite
                            cursor = await conn.execute(
                                "PRAGMA table_info(user_reminder_settings)"
                            )
                            rows = await cursor.fetchall()
                            cols = {r[1] for r in rows}
                            if col_name not in cols:
                                await conn.execute(
                                    f"ALTER TABLE user_reminder_settings "
                                    f"ADD COLUMN {col_name} {col_type}"
                                )
                                logger.info(
                                    f"✅ أُضيف العمود {col_name} إلى user_reminder_settings"
                                )
                    except Exception as e:
                        err = str(e).lower()
                        if "already exists" in err or "duplicate" in err:
                            continue
                        logger.warning(f"⚠️ فشل إضافة العمود {col_name}: {e}")
                        success = False

                # نقل البيانات القديمة من last_reminder_sent (مرة واحدة)
                try:
                    await conn.execute(
                        "UPDATE user_reminder_settings SET "
                        "last_daily_sent = COALESCE(last_daily_sent, last_reminder_sent), "
                        "last_weekly_sent = COALESCE(last_weekly_sent, last_reminder_sent), "
                        "last_subscription_sent = COALESCE(last_subscription_sent, last_reminder_sent) "
                        "WHERE last_reminder_sent IS NOT NULL"
                    )
                except Exception as e:
                    logger.debug(f"نقل بيانات last_reminder_sent: {e}")

            logger.info("✅ انتهى ترحيل أعمدة التذكيرات")
            return success

        except Exception as e:
            logger.error(f"❌ Error in migrate_reminders_columns: {e}", exc_info=True)
            return False