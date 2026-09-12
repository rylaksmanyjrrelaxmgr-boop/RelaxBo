#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
database_reminders.py - دوال التذكيرات (Mixin)
================================================================================
Mixin يُضاف إلى فئة Database في database.py

المجموعات:
  1️⃣  إعدادات التذكيرات (Reminder Settings)
  2️⃣  دوال الاستعلام للتذكيرات (Query Reminders)
  3️⃣  دوال الإرسال (Send Reminders)

⚠️ المتطلبات (يجب توفرها في الفئة الأم Database):
  - self.DB_TYPE, self.USE_POSTGRES, self.USE_MYSQL
  - self.TimeUtils
  - self.internal_cache
  - self.fetchone, self.fetchall, self.fetchval, self.execute
  - self.connection, self.transaction
  - self._get_user_lock
  - self._fetchval_with_conn, self._fetchone_with_conn, self._fetchall_with_conn
  - self._execute_with_conn, self._executemany_with_conn

🆕 v1.0 (متوافق مع database.py v7.5.8):
  - ✅ إدارة إعدادات التذكيرات لكل مستخدم
  - ✅ دوال إرسال التذكيرات (daily/weekly/subscription)
  - ✅ جلب الاشتراكات المنتهية قريباً
  - ✅ كاش 60 ثانية لتحسين الأداء
  - ✅ دعم SQLite / PostgreSQL / MySQL
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

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
                "last_reminder_sent": datetime | None,
                "notification_lang": str,
            }
        """
        try:
            # ✅ كاش 60 ثانية
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
            else:
                # إنشاء صف افتراضي
                await self.execute(
                    """INSERT OR IGNORE INTO user_reminder_settings
                       (user_id, subscription_reminder, daily_stats_reminder,
                        weekly_report, reminder_days_before, notification_lang)
                       VALUES (?, 1, 0, 1, 3, 'ar')""",
                    (user_id,),
                )
                settings = {
                    "user_id": user_id,
                    "subscription_reminder": 1,
                    "daily_stats_reminder": 0,
                    "weekly_report": 1,
                    "reminder_days_before": 3,
                    "last_reminder_sent": None,
                    "notification_lang": "ar",
                }

            await self.internal_cache.set(cache_key, settings, ttl=60)
            return settings

        except Exception as e:
            logger.error(f"❌ Error in get_reminder_settings: {e}", exc_info=True)
            return {
                "user_id": user_id,
                "subscription_reminder": 1,
                "daily_stats_reminder": 0,
                "weekly_report": 1,
                "reminder_days_before": 3,
                "last_reminder_sent": None,
                "notification_lang": "ar",
            }

    async def update_reminder_settings(self, user_id: int, **kwargs) -> bool:
        """
        تحديث إعدادات التذكير.

        Allowed columns:
          - subscription_reminder (bool/int)
          - daily_stats_reminder (bool/int)
          - weekly_report (bool/int)
          - reminder_days_before (int)
          - notification_lang (str)

        Returns:
            True عند النجاح
        """
        try:
            allowed = {
                "subscription_reminder",
                "daily_stats_reminder",
                "weekly_report",
                "reminder_days_before",
                "notification_lang",
            }
            # تحقق من الأعمدة
            invalid = [k for k in kwargs if k not in allowed]
            if invalid:
                logger.error(f"❌ Invalid columns: {invalid}")
                return False

            if not kwargs:
                return False

            # تحويل bool إلى int
            params_dict = {}
            for k, v in kwargs.items():
                if isinstance(v, bool):
                    params_dict[k] = 1 if v else 0
                else:
                    params_dict[k] = v

            # ضمان وجود الصف
            exists = await self.fetchval(
                "SELECT 1 FROM user_reminder_settings WHERE user_id = ?",
                (user_id,),
            )
            if not exists:
                await self.execute(
                    """INSERT INTO user_reminder_settings
                       (user_id, subscription_reminder, daily_stats_reminder,
                        weekly_report, reminder_days_before, notification_lang)
                       VALUES (?, 1, 0, 1, 3, 'ar')""",
                    (user_id,),
                )

            # بناء UPDATE ديناميكي
            updates = ", ".join([f"{k} = ?" for k in params_dict.keys()])
            values = list(params_dict.values()) + [user_id]
            query = f"UPDATE user_reminder_settings SET {updates} WHERE user_id = ?"

            result = await self.execute(query, tuple(values)) > 0

            if result:
                await self.internal_cache.invalidate(f"reminder_settings_{user_id}")
                await self.internal_cache.invalidate(f"user_{user_id}")
            return result

        except Exception as e:
            logger.error(f"❌ Error in update_reminder_settings: {e}", exc_info=True)
            return False

    async def reset_reminder_settings(self, user_id: int) -> bool:
        """إعادة تعيين الإعدادات للافتراضي"""
        try:
            result = await self.execute(
                """UPDATE user_reminder_settings SET
                   subscription_reminder = 1,
                   daily_stats_reminder = 0,
                   weekly_report = 1,
                   reminder_days_before = 3,
                   notification_lang = 'ar'
                   WHERE user_id = ?""",
                (user_id,),
            ) > 0
            if result:
                await self.internal_cache.invalidate(f"reminder_settings_{user_id}")
            return result
        except Exception as e:
            logger.error(f"❌ Error in reset_reminder_settings: {e}", exc_info=True)
            return False

    # =================================================================
    # 2️⃣  دوال الاستعلام للتذكيرات (Query Reminders)
    # =================================================================

    async def get_users_for_daily_reminder(self, limit: int = 500) -> List[Dict]:
        """
        جلب المستخدمين الذين يريدون تذكيراً يومياً.
        يتحقق من مرور 20 ساعة على الأقل منذ آخر تذكير.
        """
        try:
            if self._is_postgres_reminders():
                query = """
                    SELECT u.user_id, u.first_name, u.language,
                           urs.notification_lang
                    FROM users u
                    JOIN user_reminder_settings urs ON u.user_id = urs.user_id
                    WHERE urs.daily_stats_reminder = 1
                      AND u.banned = 0
                      AND (
                        urs.last_reminder_sent IS NULL
                        OR urs.last_reminder_sent < NOW() - INTERVAL '20 hours'
                      )
                    ORDER BY u.user_id LIMIT $1
                """
                return await self.fetchall(query, (limit,))
            elif self._is_mysql_reminders():
                query = """
                    SELECT u.user_id, u.first_name, u.language,
                           urs.notification_lang
                    FROM users u
                    JOIN user_reminder_settings urs ON u.user_id = urs.user_id
                    WHERE urs.daily_stats_reminder = 1
                      AND u.banned = 0
                      AND (
                        urs.last_reminder_sent IS NULL
                        OR urs.last_reminder_sent < UTC_TIMESTAMP() - INTERVAL 20 HOUR
                      )
                    ORDER BY u.user_id LIMIT %s
                """
                return await self.fetchall(query, (limit,))
            else:
                query = """
                    SELECT u.user_id, u.first_name, u.language,
                           urs.notification_lang
                    FROM users u
                    JOIN user_reminder_settings urs ON u.user_id = urs.user_id
                    WHERE urs.daily_stats_reminder = 1
                      AND u.banned = 0
                      AND (
                        urs.last_reminder_sent IS NULL
                        OR urs.last_reminder_sent < datetime('now', '-20 hours')
                      )
                    ORDER BY u.user_id LIMIT ?
                """
                return await self.fetchall(query, (limit,))
        except Exception as e:
            logger.error(f"❌ Error in get_users_for_daily_reminder: {e}", exc_info=True)
            return []

    async def get_users_for_weekly_reminder(self, limit: int = 500) -> List[Dict]:
        """
        جلب المستخدمين الذين يريدون تقريراً أسبوعياً.
        يتحقق من مرور 6 أيام على الأقل منذ آخر تذكير.
        """
        try:
            if self._is_postgres_reminders():
                query = """
                    SELECT u.user_id, u.first_name, u.language,
                           urs.notification_lang
                    FROM users u
                    JOIN user_reminder_settings urs ON u.user_id = urs.user_id
                    WHERE urs.weekly_report = 1
                      AND u.banned = 0
                      AND (
                        urs.last_reminder_sent IS NULL
                        OR urs.last_reminder_sent < NOW() - INTERVAL '6 days'
                      )
                    ORDER BY u.user_id LIMIT $1
                """
                return await self.fetchall(query, (limit,))
            elif self._is_mysql_reminders():
                query = """
                    SELECT u.user_id, u.first_name, u.language,
                           urs.notification_lang
                    FROM users u
                    JOIN user_reminder_settings urs ON u.user_id = urs.user_id
                    WHERE urs.weekly_report = 1
                      AND u.banned = 0
                      AND (
                        urs.last_reminder_sent IS NULL
                        OR urs.last_reminder_sent < UTC_TIMESTAMP() - INTERVAL 6 DAY
                      )
                    ORDER BY u.user_id LIMIT %s
                """
                return await self.fetchall(query, (limit,))
            else:
                query = """
                    SELECT u.user_id, u.first_name, u.language,
                           urs.notification_lang
                    FROM users u
                    JOIN user_reminder_settings urs ON u.user_id = urs.user_id
                    WHERE urs.weekly_report = 1
                      AND u.banned = 0
                      AND (
                        urs.last_reminder_sent IS NULL
                        OR urs.last_reminder_sent < datetime('now', '-6 days')
                      )
                    ORDER BY u.user_id LIMIT ?
                """
                return await self.fetchall(query, (limit,))
        except Exception as e:
            logger.error(f"❌ Error in get_users_for_weekly_reminder: {e}", exc_info=True)
            return []

    async def get_subscriptions_ending_soon(self, limit: int = 500) -> List[Dict]:
        """
        جلب الاشتراكات التي تنتهي قريباً (خلال reminder_days_before).

        Returns:
            قائمة من {user_id, end_date, days_remaining, notification_lang}
        """
        try:
            if self._is_postgres_reminders():
                query = """
                    SELECT s.user_id,
                           MAX(s.end_date) AS end_date,
                           EXTRACT(DAY FROM MAX(s.end_date) - NOW())::int
                               AS days_remaining,
                           COALESCE(urs.notification_lang, 'ar')
                               AS notification_lang
                    FROM subscriptions s
                    LEFT JOIN user_reminder_settings urs
                        ON urs.user_id = s.user_id
                    WHERE s.status = 'active'
                      AND s.end_date > NOW()
                      AND s.end_date <= NOW() + INTERVAL '7 days'
                      AND (urs.subscription_reminder IS NULL
                           OR urs.subscription_reminder = 1)
                    GROUP BY s.user_id, urs.notification_lang
                    ORDER BY end_date ASC
                    LIMIT $1
                """
                return await self.fetchall(query, (limit,))
            elif self._is_mysql_reminders():
                query = """
                    SELECT s.user_id,
                           MAX(s.end_date) AS end_date,
                           DATEDIFF(MAX(s.end_date), UTC_TIMESTAMP())
                               AS days_remaining,
                           COALESCE(urs.notification_lang, 'ar')
                               AS notification_lang
                    FROM subscriptions s
                    LEFT JOIN user_reminder_settings urs
                        ON urs.user_id = s.user_id
                    WHERE s.status = 'active'
                      AND s.end_date > UTC_TIMESTAMP()
                      AND s.end_date <= DATE_ADD(UTC_TIMESTAMP(), INTERVAL 7 DAY)
                      AND (urs.subscription_reminder IS NULL
                           OR urs.subscription_reminder = 1)
                    GROUP BY s.user_id, urs.notification_lang
                    ORDER BY end_date ASC
                    LIMIT %s
                """
                return await self.fetchall(query, (limit,))
            else:
                query = """
                    SELECT s.user_id,
                           MAX(s.end_date) AS end_date,
                           CAST(julianday(MAX(s.end_date)) - julianday('now')
                                AS INTEGER) AS days_remaining,
                           COALESCE(urs.notification_lang, 'ar')
                               AS notification_lang
                    FROM subscriptions s
                    LEFT JOIN user_reminder_settings urs
                        ON urs.user_id = s.user_id
                    WHERE s.status = 'active'
                      AND s.end_date > datetime('now')
                      AND s.end_date <= datetime('now', '+7 days')
                      AND (urs.subscription_reminder IS NULL
                           OR urs.subscription_reminder = 1)
                    GROUP BY s.user_id, urs.notification_lang
                    ORDER BY end_date ASC
                    LIMIT ?
                """
                return await self.fetchall(query, (limit,))
        except Exception as e:
            logger.error(f"❌ Error in get_subscriptions_ending_soon: {e}", exc_info=True)
            return []

    # =================================================================
    # 3️⃣  دوال الإرسال (Send Reminders)
    # =================================================================

    async def mark_reminder_sent(self, user_id: int) -> bool:
        """تحديث last_reminder_sent لمستخدم واحد"""
        try:
            now_iso = self.TimeUtils.sql_iso() if hasattr(self.TimeUtils, "sql_iso") else datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            result = await self.execute(
                "UPDATE user_reminder_settings "
                "SET last_reminder_sent = ? WHERE user_id = ?",
                (now_iso, user_id),
            ) > 0
            if result:
                await self.internal_cache.invalidate(f"reminder_settings_{user_id}")
            return result
        except Exception as e:
            logger.error(f"❌ Error in mark_reminder_sent: {e}", exc_info=True)
            return False

    async def mark_reminders_sent_bulk(self, user_ids: List[int]) -> int:
        """تحديث last_reminder_sent لمجموعة مستخدمين (batch)"""
        if not user_ids:
            return 0
        try:
            now_iso = self.TimeUtils.sql_iso() if hasattr(self.TimeUtils, "sql_iso") else datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            total = 0
            BATCH = 500
            for i in range(0, len(user_ids), BATCH):
                batch = user_ids[i : i + BATCH]
                placeholders = ",".join(["?"] * len(batch))
                updated = await self.execute(
                    f"UPDATE user_reminder_settings "
                    f"SET last_reminder_sent = ? "
                    f"WHERE user_id IN ({placeholders})",
                    (now_iso, *batch),
                )
                total += updated or 0
                for uid in batch:
                    await self.internal_cache.invalidate(f"reminder_settings_{uid}")
            return total
        except Exception as e:
            logger.error(f"❌ Error in mark_reminders_sent_bulk: {e}", exc_info=True)
            return 0

    async def send_subscription_reminders(self, reminder_func) -> int:
        """
        إرسال تذكيرات الاشتراك لجميع المستخدمين المؤهلين.

        Args:
            reminder_func: دالة async تُستدعى لكل مستخدم
                           signature: async def f(user_id, days_left, lang) -> bool

        Returns:
            عدد التذكيرات المُرسلة بنجاح
        """
        try:
            users = await self.get_subscriptions_ending_soon(limit=500)
            if not users:
                return 0

            sent = 0
            sent_ids = []
            for row in users:
                try:
                    user_id = row["user_id"]
                    days_left = int(row.get("days_remaining") or 0)
                    lang = row.get("notification_lang") or "ar"

                    if days_left <= 0:
                        continue
                    # نرسل فقط عندما يتبقى X أيام حسب إعدادات المستخدم
                    settings = await self.get_reminder_settings(user_id)
                    days_before = settings.get("reminder_days_before", 3)
                    if days_left > days_before:
                        continue

                    ok = await reminder_func(user_id, days_left, lang)
                    if ok:
                        sent += 1
                        sent_ids.append(user_id)
                except Exception as e:
                    logger.warning(f"⚠️ فشل إرسال تذكير لـ {row.get('user_id')}: {e}")

            if sent_ids:
                await self.mark_reminders_sent_bulk(sent_ids)

            return sent
        except Exception as e:
            logger.error(f"❌ Error in send_subscription_reminders: {e}", exc_info=True)
            return 0

    async def send_daily_reminders(self, reminder_func) -> int:
        """
        إرسال تذكيرات يومية.

        Args:
            reminder_func: async def f(user_id, lang) -> bool

        Returns:
            عدد التذكيرات المُرسلة
        """
        try:
            users = await self.get_users_for_daily_reminder(limit=500)
            if not users:
                return 0

            sent = 0
            sent_ids = []
            for row in users:
                try:
                    user_id = row["user_id"]
                    lang = row.get("notification_lang") or row.get("language") or "ar"
                    ok = await reminder_func(user_id, lang)
                    if ok:
                        sent += 1
                        sent_ids.append(user_id)
                except Exception as e:
                    logger.warning(f"⚠️ فشل إرسال تذكير يومي لـ {row.get('user_id')}: {e}")

            if sent_ids:
                await self.mark_reminders_sent_bulk(sent_ids)

            return sent
        except Exception as e:
            logger.error(f"❌ Error in send_daily_reminders: {e}", exc_info=True)
            return 0

    async def send_weekly_reminders(self, reminder_func) -> int:
        """
        إرسال تقارير أسبوعية.

        Args:
            reminder_func: async def f(user_id, lang) -> bool

        Returns:
            عدد التقارير المُرسلة
        """
        try:
            users = await self.get_users_for_weekly_reminder(limit=500)
            if not users:
                return 0

            sent = 0
            sent_ids = []
            for row in users:
                try:
                    user_id = row["user_id"]
                    lang = row.get("notification_lang") or row.get("language") or "ar"
                    ok = await reminder_func(user_id, lang)
                    if ok:
                        sent += 1
                        sent_ids.append(user_id)
                except Exception as e:
                    logger.warning(f"⚠️ فشل إرسال تقرير أسبوعي لـ {row.get('user_id')}: {e}")

            if sent_ids:
                await self.mark_reminders_sent_bulk(sent_ids)

            return sent
        except Exception as e:
            logger.error(f"❌ Error in send_weekly_reminders: {e}", exc_info=True)
            return 0

    # =================================================================
    # 4️⃣  إحصائيات
    # =================================================================

    async def get_reminder_stats(self) -> Dict:
        """
        إحصائيات إعدادات التذكيرات.

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
                total = await self._fetchval_with_conn(
                    conn,
                    "SELECT COUNT(*) FROM user_reminder_settings",
                    default=0,
                )
                sub = await self._fetchval_with_conn(
                    conn,
                    "SELECT COUNT(*) FROM user_reminder_settings "
                    "WHERE subscription_reminder = 1",
                    default=0,
                )
                daily = await self._fetchval_with_conn(
                    conn,
                    "SELECT COUNT(*) FROM user_reminder_settings "
                    "WHERE daily_stats_reminder = 1",
                    default=0,
                )
                weekly = await self._fetchval_with_conn(
                    conn,
                    "SELECT COUNT(*) FROM user_reminder_settings "
                    "WHERE weekly_report = 1",
                    default=0,
                )
            return {
                "total_users": total,
                "subscription_reminder": sub,
                "daily_stats_reminder": daily,
                "weekly_report": weekly,
            }
        except Exception as e:
            logger.error(f"❌ Error in get_reminder_stats: {e}", exc_info=True)
            return {
                "total_users": 0,
                "subscription_reminder": 0,
                "daily_stats_reminder": 0,
                "weekly_report": 0,
            }