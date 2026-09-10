#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_reminders.py - دوال التذكيرات (v7.4.7)
================================================================================
RemindersMixin:
  - get_users_for_reminder           : جلب المستخدمين الذين يحتاجون تذكيراً
  - get_reminder_settings            : جلب إعدادات تذكير مستخدم
  - update_reminder_settings         : تحديث إعدادات التذكير
  - get_users_with_reminder_enabled  : المستخدمون الذين فعّلوا نوع تذكير
  - get_reminder_stats               : إحصائيات تذكيرات مستخدم
  - reset_reminder_settings          : إعادة تعيين إعدادات التذكير
  - bulk_update_reminder_sent        : تحديث last_reminder_sent لعدة مستخدمين
  - is_user_reminder_enabled         : هل التذكير مفعّل لمستخدم
  - update_reminder_sent             : تحديث وقت آخر تذكير

📌 مطابق 100% للسلوك الأصلي في database.py (بدون أي إضافة أو تعديل)

📌 يفترض أن الـ Database يوفّر:
  - self.fetchone / self.fetchall / self.fetchval / self.execute / self.executemany
  - self.transaction() / self._fetchone_with_conn / self._execute_with_conn
  - self.TimeUtils
  - self.internal_cache
  - self.USE_POSTGRES / self.USE_MYSQL
================================================================================
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class RemindersMixin:
    """Mixin يحتوي كل دوال التذكيرات"""

    # =====================================================================
    # 1) جلب المستخدمين الذين يحتاجون تذكيراً
    # =====================================================================

    async def get_users_for_reminder(self) -> List[Dict]:
        """EXTRACT(EPOCH) بدل EXTRACT(DAY)"""
        now = self.TimeUtils.utc_now()
        if self.USE_POSTGRES:
            return await self.fetchall(
                """SELECT u.user_id, u.language, r.reminder_days_before,
                          EXTRACT(EPOCH FROM (MAX(s.end_date) - $1)) / 86400 as days_left,
                          r.last_reminder_sent
                   FROM users u
                   JOIN user_reminder_settings r ON u.user_id = r.user_id
                   JOIN subscriptions s ON u.user_id = s.user_id AND s.status = 'active' AND s.end_date > $2
                   WHERE r.subscription_reminder = 1
                   GROUP BY u.user_id, u.language, r.reminder_days_before, r.last_reminder_sent
                   HAVING days_left <= r.reminder_days_before
                      AND days_left > 0
                      AND (r.last_reminder_sent IS NULL
                           OR EXTRACT(EPOCH FROM ($3 - r.last_reminder_sent)) / 86400 >= 1)""",
                (now, now, now),
            )
        elif self.USE_MYSQL:
            return await self.fetchall(
                """SELECT u.user_id, u.language, r.reminder_days_before,
                          TIMESTAMPDIFF(DAY, %s, MAX(s.end_date)) as days_left,
                          r.last_reminder_sent
                   FROM users u
                   JOIN user_reminder_settings r ON u.user_id = r.user_id
                   JOIN subscriptions s ON u.user_id = s.user_id AND s.status = 'active' AND s.end_date > %s
                   WHERE r.subscription_reminder = 1
                   GROUP BY u.user_id, u.language, r.reminder_days_before, r.last_reminder_sent
                   HAVING days_left <= r.reminder_days_before
                      AND days_left > 0
                      AND (r.last_reminder_sent IS NULL OR TIMESTAMPDIFF(DAY, r.last_reminder_sent, %s) >= 1)""",
                (now.strftime("%Y-%m-%d %H:%M:%S"),
                 now.strftime("%Y-%m-%d %H:%M:%S"),
                 now.strftime("%Y-%m-%d %H:%M:%S")),
            )
        else:
            return await self.fetchall(
                """SELECT u.user_id, u.language, r.reminder_days_before,
                          CAST(julianday(MAX(s.end_date)) - julianday(?) AS INTEGER) as days_left,
                          r.last_reminder_sent
                   FROM users u
                   JOIN user_reminder_settings r ON u.user_id = r.user_id
                   JOIN subscriptions s ON u.user_id = s.user_id AND s.status = 'active' AND s.end_date > ?
                   WHERE r.subscription_reminder = 1
                   GROUP BY u.user_id, u.language, r.reminder_days_before, r.last_reminder_sent
                   HAVING days_left <= r.reminder_days_before
                      AND days_left > 0
                      AND (r.last_reminder_sent IS NULL OR julianday(?) - julianday(r.last_reminder_sent) >= 1)""",
                (now.strftime("%Y-%m-%d %H:%M:%S"),
                 now.strftime("%Y-%m-%d %H:%M:%S"),
                 now.strftime("%Y-%m-%d %H:%M:%S")),
            )

    # =====================================================================
    # 2) جلب إعدادات تذكير مستخدم
    # =====================================================================

    async def get_reminder_settings(self, user_id: int) -> Optional[Dict]:
        try:
            cached = await self.internal_cache.get(f"reminder_settings_{user_id}")
            if cached is not None:
                return cached
            async with self.transaction() as conn:
                settings = await self._fetchone_with_conn(
                    conn, "SELECT * FROM user_reminder_settings WHERE user_id = ?", user_id
                )
                if not settings:
                    await self._execute_with_conn(
                        conn,
                        """INSERT OR IGNORE INTO user_reminder_settings
                           (user_id, subscription_reminder, daily_stats_reminder,
                            weekly_report, reminder_days_before, notification_lang)
                           VALUES (?, 1, 0, 1, 3, 'ar')""",
                        user_id,
                    )
                    settings = await self._fetchone_with_conn(
                        conn, "SELECT * FROM user_reminder_settings WHERE user_id = ?", user_id
                    )
            if settings:
                await self.internal_cache.set(f"reminder_settings_{user_id}", settings, ttl=60)
                return settings
            return {
                "user_id": user_id,
                "subscription_reminder": 1,
                "daily_stats_reminder": 0,
                "weekly_report": 1,
                "reminder_days_before": 3,
                "last_reminder_sent": None,
                "notification_lang": "ar",
            }
        except Exception as e:
            logger.error(f"❌ Error in get_reminder_settings: {e}", exc_info=True)
            return None

    # =====================================================================
    # 3) تحديث إعدادات التذكير
    # =====================================================================

    async def update_reminder_settings(self, user_id: int, **kwargs) -> bool:
        if not kwargs:
            return False
        allowed = {
            "subscription_reminder", "daily_stats_reminder", "weekly_report",
            "reminder_days_before", "last_reminder_sent", "notification_lang",
        }
        for key in kwargs:
            if key not in allowed:
                logger.error(f"❌ Invalid column: {key}")
                return False
        try:
            async with self.transaction() as conn:
                await self._execute_with_conn(
                    conn,
                    """INSERT OR IGNORE INTO user_reminder_settings
                       (user_id, subscription_reminder, daily_stats_reminder,
                        weekly_report, reminder_days_before, notification_lang)
                       VALUES (?, 1, 0, 1, 3, 'ar')""",
                    user_id,
                )
                updates = [f"{key} = ?" for key in kwargs]
                values = list(kwargs.values()) + [user_id]
                query = f"UPDATE user_reminder_settings SET {', '.join(updates)} WHERE user_id = ?"
                result = await self._execute_with_conn(conn, query, *values)
                success = result > 0
            if success:
                await self.internal_cache.invalidate(f"reminder_settings_{user_id}")
            return success
        except Exception as e:
            logger.error(f"❌ Error in update_reminder_settings: {e}", exc_info=True)
            return False

    # =====================================================================
    # 4) المستخدمون الذين فعّلوا نوع تذكير
    # =====================================================================

    async def get_users_with_reminder_enabled(self, reminder_type: str) -> List[Dict]:
        column_map = {
            "subscription": "subscription_reminder",
            "daily_stats": "daily_stats_reminder",
            "weekly_report": "weekly_report",
        }
        column = column_map.get(reminder_type)
        if not column:
            logger.warning(f"⚠️ reminder_type غير معروف: {reminder_type}")
            return []
        return await self.fetchall(
            f"""SELECT u.user_id, u.language, r.*
                FROM users u
                JOIN user_reminder_settings r ON u.user_id = r.user_id
                WHERE r.{column} = 1 AND u.banned = 0""",
            (),
        )

    # =====================================================================
    # 5) إحصائيات تذكيرات مستخدم
    # =====================================================================

    async def get_reminder_stats(self, user_id: int) -> Dict:
        settings = await self.get_reminder_settings(user_id)
        if not settings:
            return {}
        return {
            "subscription_reminder": bool(settings.get("subscription_reminder", 1)),
            "daily_stats_reminder": bool(settings.get("daily_stats_reminder", 0)),
            "weekly_report": bool(settings.get("weekly_report", 1)),
            "reminder_days_before": settings.get("reminder_days_before", 3),
            "last_reminder_sent": settings.get("last_reminder_sent"),
            "notification_lang": settings.get("notification_lang", "ar"),
        }

    # =====================================================================
    # 6) إعادة تعيين إعدادات التذكير
    # =====================================================================

    async def reset_reminder_settings(self, user_id: int) -> bool:
        try:
            result = await self.execute(
                """UPDATE user_reminder_settings
                   SET subscription_reminder = 1, daily_stats_reminder = 0,
                       weekly_report = 1, reminder_days_before = 3,
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

    # =====================================================================
    # 7) تحديث last_reminder_sent لعدة مستخدمين
    # =====================================================================

    async def bulk_update_reminder_sent(self, user_ids: List[int]) -> int:
        if not user_ids:
            return 0
        now = self.TimeUtils.utc_now()
        try:
            params = [(now, uid) for uid in user_ids]
            count = await self.executemany(
                "UPDATE user_reminder_settings SET last_reminder_sent = ? WHERE user_id = ?", params
            )
            for uid in user_ids:
                await self.internal_cache.invalidate(f"reminder_settings_{uid}")
            return count
        except Exception as e:
            logger.error(f"❌ Error in bulk_update_reminder_sent: {e}", exc_info=True)
            return 0

    # =====================================================================
    # 8) هل التذكير مفعّل لمستخدم
    # =====================================================================

    async def is_user_reminder_enabled(self, user_id: int, reminder_type: str) -> bool:
        """مفتاح weekly_report الصحيح"""
        settings = await self.get_reminder_settings(user_id)
        if not settings:
            return False
        column_map = {
            "subscription": "subscription_reminder",
            "daily_stats": "daily_stats_reminder",
            "weekly_report": "weekly_report",
        }
        col = column_map.get(reminder_type)
        if not col:
            logger.warning(f"⚠️ reminder_type غير معروف: {reminder_type}")
            return False
        return bool(settings.get(col, 0))

    # =====================================================================
    # 9) تحديث وقت آخر تذكير
    # =====================================================================

    async def update_reminder_sent(self, user_id: int) -> bool:
        return await self.execute(
            "UPDATE user_reminder_settings SET last_reminder_sent = ? WHERE user_id = ?",
            (self.TimeUtils.utc_now(), user_id),
        ) > 0