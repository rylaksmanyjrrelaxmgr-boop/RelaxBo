#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
database_subscriptions.py - دوال الاشتراكات والباقات والإحالات (v1.1)
================================================================================
Mixin يُضاف إلى فئة Database في database.py

المجموعات:
  1️⃣  الباقات (Plans)
  2️⃣  الاشتراكات (Subscriptions)
  3️⃣  أكواد الهدايا (Gift Codes)
  4️⃣  الفواتير والدفع (Invoices & Payments)
  5️⃣  الإحالات (Referrals)

⚠️ المتطلبات (يجب توفرها في الفئة الأم Database):
  - self.DB_TYPE, self.USE_POSTGRES, self.USE_MYSQL
  - self.TimeUtils
  - self.internal_cache
  - self.fetchone, self.fetchall, self.fetchval, self.execute
  - self.connection, self.transaction
  - self._get_user_lock
  - self._fetchval_with_conn, self._fetchone_with_conn, self._fetchall_with_conn
  - self._execute_with_conn, self._executemany_with_conn

🆕 إصلاحات مدمجة (v1.0):
  - إصلاح fallback للجداول بدون id
  - معالجة date في safe_parse_iso (عبر TimeUtils)
  - ON CONFLICT مع target صريح
  - حماية من الاشتراكات المكررة
  - استخدام self.DB_TYPE بدل الاستيراد المباشر

🆕 v1.1 (متوافق مع database.py v7.5.8):
  - ✅ إبطال كاش has_active_sub_* (30s TTL) عند تغيير الاشتراك
  - الآن /start يعكس التغييرات فوراً بدلاً من انتظار 30 ثانية
"""

import os
import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


# =====================================================================
# استيراد التكوينات (بحماية)
# =====================================================================

try:
    from config import CONFIG
except ImportError:
    class CONFIG:
        MAX_DAILY_REFERRALS = 10
        PRIMARY_OWNER_ID = 0


# =====================================================================
# استيراد دوال الكاش (بحماية)
# =====================================================================

try:
    from cache import invalidate_user_cache
    _CACHE_AVAILABLE = True
except ImportError:
    _CACHE_AVAILABLE = False

    async def invalidate_user_cache(user_id: int):
        """Fallback no-op"""
        pass


# =====================================================================
# SubscriptionsMixin
# =====================================================================

class SubscriptionsMixin:
    """
    Mixin لدوال الاشتراكات والباقات والإحالات.

    يعتمد على الخصائص التالية في الفئة الأم:
      - self.DB_TYPE          : "sqlite" | "postgres" | "mysql"
      - self.TimeUtils        : فئة TimeUtils
      - self.internal_cache   : InternalQueryCache
      - دوال fetchone/fetchall/fetchval/execute
      - دوال connection/transaction
      - self._get_user_lock
      - دوال _fetch*_with_conn و _execute_with_conn
    """

    # =================================================================
    # دوال داخلية مساعدة
    # =================================================================

    def _is_postgres(self) -> bool:
        return getattr(self, "DB_TYPE", "sqlite") == "postgres"

    def _is_mysql(self) -> bool:
        return getattr(self, "DB_TYPE", "sqlite") == "mysql"

    def _is_sqlite(self) -> bool:
        return getattr(self, "DB_TYPE", "sqlite") == "sqlite"

    async def _invalidate_subscription_caches(self, user_id: int) -> None:
        """إبطال كل الكاش المرتبط بالمستخدم"""
        try:
            await self.internal_cache.invalidate(f"user_{user_id}")
            await self.internal_cache.invalidate(f"user_{user_id}_True")
            await self.internal_cache.invalidate(f"user_{user_id}_False")
            await self.internal_cache.invalidate(f"subscription_{user_id}")
            # ✅ v1.1: إبطال كاش has_active_sub_* (متوافق مع database.py v7.5.8)
            await self.internal_cache.invalidate(f"has_active_sub_{user_id}")
        except Exception as e:
            logger.debug(f"invalidate_subscription_caches: {e}")

        if _CACHE_AVAILABLE:
            try:
                await invalidate_user_cache(user_id)
            except Exception as e:
                logger.debug(f"invalidate_user_cache: {e}")

    # =================================================================
    # 1️⃣  الباقات (Plans)
    # =================================================================

    async def get_plan(self, plan_id: int) -> Optional[Dict]:
        """جلب باقة بالمعرّف"""
        try:
            return await self.fetchone(
                "SELECT * FROM plans WHERE id = ? AND is_active = 1",
                (plan_id,),
            )
        except Exception as e:
            logger.error(f"❌ Error in get_plan: {e}", exc_info=True)
            return None

    async def get_plan_by_name(self, name: str) -> Optional[Dict]:
        """جلب باقة بالاسم"""
        try:
            return await self.fetchone(
                "SELECT * FROM plans WHERE name = ? AND is_active = 1 LIMIT 1",
                (name,),
            )
        except Exception as e:
            logger.error(f"❌ Error in get_plan_by_name: {e}", exc_info=True)
            return None

    async def get_all_plans(self) -> List[Dict]:
        """كل الباقات (بدون الهدايا)"""
        try:
            return await self.fetchall(
                "SELECT * FROM plans WHERE is_active = 1 AND is_gift = 0 ORDER BY price"
            )
        except Exception as e:
            logger.error(f"❌ Error in get_all_plans: {e}", exc_info=True)
            return []

    async def get_gift_plans(self) -> List[Dict]:
        """باقات الهدايا فقط"""
        try:
            return await self.fetchall(
                "SELECT id, name, description, price, duration_days AS days "
                "FROM plans WHERE is_active = 1 AND is_gift = 1 ORDER BY price"
            )
        except Exception as e:
            logger.error(f"❌ Error in get_gift_plans: {e}", exc_info=True)
            return []

    async def get_gift_plan(self, plan_id: int) -> Optional[Dict]:
        """باقة هدية بالمعرّف"""
        try:
            return await self.fetchone(
                "SELECT id, name, description, price, duration_days AS days "
                "FROM plans WHERE id = ? AND is_gift = 1 AND is_active = 1",
                (plan_id,),
            )
        except Exception as e:
            logger.error(f"❌ Error in get_gift_plan: {e}", exc_info=True)
            return None

    # =================================================================
    # 2️⃣  الاشتراكات (Subscriptions)
    # =================================================================

    async def has_active_subscription(self, user_id: int) -> bool:
        """هل المستخدم لديه اشتراك نشط؟"""
        try:
            result = await self.fetchval(
                "SELECT 1 FROM subscriptions "
                "WHERE user_id = ? AND status = 'active' AND end_date > ? LIMIT 1",
                (user_id, self.TimeUtils.utc_now()),
            )
            return result is not None
        except Exception as e:
            logger.error(f"❌ Error in has_active_subscription: {e}", exc_info=True)
            return False

    async def has_used_trial(self, user_id: int) -> bool:
        """هل استخدم التجربة المجانية؟"""
        try:
            result = await self.fetchval(
                "SELECT trial_used FROM users WHERE user_id = ?",
                (user_id,),
                default=0,
            )
            return result == 1
        except Exception as e:
            logger.error(f"❌ Error in has_used_trial: {e}", exc_info=True)
            return False

    async def activate_trial(self, user_id: int) -> int:
        """
        تفعيل التجربة المجانية (30 يوم).

        Returns:
            عدد الأيام المُضافة (0 إذا فشل)
        """
        try:
            async with await self._get_user_lock(user_id):
                now = self.TimeUtils.utc_now()
                trial_end = now + timedelta(days=30)

                async with self.transaction() as conn:
                    trial_plan_id = await self._fetchval_with_conn(
                        conn,
                        "SELECT id FROM plans WHERE name = 'تجربة' AND is_active = 1 LIMIT 1",
                        default=1,
                    )

                    current_end = await self._fetchval_with_conn(
                        conn,
                        "SELECT MAX(end_date) FROM subscriptions "
                        "WHERE user_id = ? AND status = 'active' AND end_date > ?",
                        user_id, self.TimeUtils.utc_now(),
                    )
                    current_end_dt = (
                        self.TimeUtils.safe_parse_iso(current_end)
                        if current_end else None
                    )

                    if current_end_dt and current_end_dt > trial_end:
                        days_granted = 0
                        new_end = current_end_dt
                    else:
                        days_granted = 30
                        new_end = trial_end

                    # تعليم التجربة كمستخدمة
                    if self._is_postgres():
                        await self._execute_with_conn(
                            conn,
                            "UPDATE users SET trial_used = 1, updated_at = $1 WHERE user_id = $2",
                            self.TimeUtils.utc_now(), user_id,
                        )
                    else:
                        await self._execute_with_conn(
                            conn,
                            "UPDATE users SET trial_used = 1, updated_at = ? WHERE user_id = ?",
                            self.TimeUtils.sql_iso(), user_id,
                        )

                    if days_granted > 0:
                        if self._is_postgres():
                            await self._execute_with_conn(
                                conn,
                                "UPDATE users SET subscription_end = $1 WHERE user_id = $2",
                                new_end, user_id,
                            )
                            await self._execute_with_conn(
                                conn,
                                """INSERT INTO subscriptions
                                   (user_id, plan_id, status, start_date, end_date,
                                    provider, created_at, updated_at)
                                   VALUES ($1, $2, 'active', $3, $4, 'trial', $5, $6)""",
                                user_id, trial_plan_id,
                                self.TimeUtils.utc_now(), new_end,
                                self.TimeUtils.utc_now(), self.TimeUtils.utc_now(),
                            )
                        else:
                            await self._execute_with_conn(
                                conn,
                                "UPDATE users SET subscription_end = ? WHERE user_id = ?",
                                new_end.strftime("%Y-%m-%d %H:%M:%S"), user_id,
                            )
                            await self._execute_with_conn(
                                conn,
                                """INSERT INTO subscriptions
                                   (user_id, plan_id, status, start_date, end_date,
                                    provider, created_at, updated_at)
                                   VALUES (?,?,?,?,?,?,?,?)""",
                                user_id, trial_plan_id, "active",
                                self.TimeUtils.sql_iso(),
                                new_end.strftime("%Y-%m-%d %H:%M:%S"),
                                "trial",
                                self.TimeUtils.sql_iso(),
                                self.TimeUtils.sql_iso(),
                            )
                        await self._refresh_user_subscription_end(conn, user_id)

                    await self._invalidate_subscription_caches(user_id)
                    return days_granted

        except Exception as e:
            logger.error(f"❌ Error in activate_trial: {e}", exc_info=True)
            return 0

    async def get_active_subscription(self, user_id: int) -> Optional[Dict]:
        """جلب الاشتراك النشط (الأول بالأولوية)"""
        try:
            return await self.fetchone(
                """SELECT s.*, p.name, p.duration_days, p.max_channels,
                          p.max_posts, p.features
                   FROM subscriptions s
                   JOIN plans p ON s.plan_id = p.id AND p.is_active = 1
                   WHERE s.user_id = ? AND s.status = 'active' AND s.end_date > ?
                   ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC
                   LIMIT 1""",
                (user_id, self.TimeUtils.utc_now()),
            )
        except Exception as e:
            logger.error(f"❌ Error in get_active_subscription: {e}", exc_info=True)
            return None

    async def get_active_plan(self, user_id: int) -> Optional[Dict]:
        """جلب الباقة النشطة"""
        try:
            sub = await self.get_active_subscription(user_id)
            if sub:
                return await self.get_plan(sub["plan_id"])
            return None
        except Exception as e:
            logger.error(f"❌ Error in get_active_plan: {e}", exc_info=True)
            return None

    async def get_subscription_end(self, user_id: int) -> Optional[datetime]:
        """جلب تاريخ انتهاء الاشتراك من users.subscription_end"""
        try:
            result = await self.fetchval(
                "SELECT subscription_end FROM users WHERE user_id = ?",
                (user_id,),
            )
            return self.TimeUtils.safe_parse_iso(result) if result else None
        except Exception as e:
            logger.error(f"❌ Error in get_subscription_end: {e}", exc_info=True)
            return None

    async def create_subscription(
        self,
        user_id: int,
        plan_id: int,
        provider: str = "xtr",
        provider_sub_id: str = None,
    ) -> int:
        """
        إنشاء اشتراك جديد.

        Returns:
            معرّف الاشتراك (0 عند الفشل)
        """
        try:
            plan = await self.get_plan(plan_id)
            if not plan:
                logger.warning(f"⚠️ الباقة {plan_id} غير موجودة أو غير مفعّلة")
                return 0

            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    current_end = await self._fetchval_with_conn(
                        conn,
                        "SELECT MAX(end_date) FROM subscriptions "
                        "WHERE user_id = ? AND status = 'active' AND end_date > ?",
                        user_id, self.TimeUtils.sql_iso(),
                    )
                    current_end_dt = (
                        self.TimeUtils.safe_parse_iso(current_end)
                        if current_end else None
                    )
                    now = self.TimeUtils.utc_now()
                    base = (
                        current_end_dt
                        if current_end_dt and current_end_dt > now
                        else now
                    )
                    new_end = base + timedelta(days=plan["duration_days"])

                    if self._is_postgres():
                        row = await self._fetchone_with_conn(
                            conn,
                            """INSERT INTO subscriptions
                               (user_id, plan_id, status, start_date, end_date, auto_renew,
                                provider, provider_subscription_id, created_at, updated_at)
                               VALUES ($1, $2, 'active', $3, $4, 0, $5, $6, $7, $7)
                               RETURNING id""",
                            user_id, plan_id, self.TimeUtils.utc_now(),
                            new_end, provider, provider_sub_id,
                            self.TimeUtils.utc_now(),
                        )
                        sub_id = row["id"] if row else 0
                    elif self._is_mysql():
                        cursor = await conn.cursor()
                        await cursor.execute(
                            """INSERT INTO subscriptions
                               (user_id, plan_id, status, start_date, end_date, auto_renew,
                                provider, provider_subscription_id, created_at, updated_at)
                               VALUES (%s, %s, 'active', %s, %s, 0, %s, %s, %s, %s)""",
                            (user_id, plan_id, self.TimeUtils.sql_iso(),
                             new_end.strftime("%Y-%m-%d %H:%M:%S"),
                             provider, provider_sub_id,
                             self.TimeUtils.sql_iso(), self.TimeUtils.sql_iso()),
                        )
                        sub_id = cursor.lastrowid
                        await cursor.close()
                    else:
                        cursor = await conn.execute(
                            """INSERT INTO subscriptions
                               (user_id, plan_id, status, start_date, end_date, auto_renew,
                                provider, provider_subscription_id, created_at, updated_at)
                               VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (user_id, plan_id, "active", self.TimeUtils.sql_iso(),
                             new_end.strftime("%Y-%m-%d %H:%M:%S"), 0,
                             provider, provider_sub_id,
                             self.TimeUtils.sql_iso(), self.TimeUtils.sql_iso()),
                        )
                        sub_id = cursor.lastrowid if cursor.lastrowid else 0

                    await self._execute_with_conn(
                        conn,
                        "UPDATE users SET updated_at = ? WHERE user_id = ?",
                        self.TimeUtils.sql_iso(), user_id,
                    )
                    await self._refresh_user_subscription_end(conn, user_id)

                await self._invalidate_subscription_caches(user_id)
                return sub_id

        except Exception as e:
            logger.error(f"❌ Error in create_subscription: {e}", exc_info=True)
            return 0

    async def grant_subscription_days(
        self,
        user_id: int,
        days: int,
        plan_id: int = None,
        provider: str = "manual",
    ) -> bool:
        """منح أيام اشتراك يدوياً"""
        try:
            if days <= 0:
                return False

            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    exists = await self._fetchval_with_conn(
                        conn, "SELECT 1 FROM users WHERE user_id = ?", user_id
                    )
                    if not exists:
                        logger.warning(f"⚠️ المستخدم {user_id} غير موجود")
                        return False

                    if not plan_id:
                        plan_id = await self._fetchval_with_conn(
                            conn,
                            "SELECT id FROM plans WHERE is_gift = 1 AND is_active = 1 "
                            "ORDER BY max_channels DESC LIMIT 1",
                        )
                        if not plan_id:
                            plan_id = await self._fetchval_with_conn(
                                conn,
                                "SELECT id FROM plans WHERE name = 'شهر' AND is_active = 1 LIMIT 1",
                            )
                            if not plan_id:
                                logger.error("❌ لا يوجد plan_id افتراضي")
                                return False

                    current_end = await self._fetchval_with_conn(
                        conn,
                        "SELECT MAX(end_date) FROM subscriptions "
                        "WHERE user_id = ? AND status = 'active' AND end_date > ?",
                        user_id, self.TimeUtils.sql_iso(),
                    )
                    current_end_dt = (
                        self.TimeUtils.safe_parse_iso(current_end)
                        if current_end else None
                    )
                    now = self.TimeUtils.utc_now()
                    base = (
                        current_end_dt
                        if current_end_dt and current_end_dt > now
                        else now
                    )
                    new_end = base + timedelta(days=days)

                    await self._execute_with_conn(
                        conn,
                        """INSERT INTO subscriptions
                           (user_id, plan_id, status, start_date, end_date,
                            provider, created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        user_id, plan_id, "active", self.TimeUtils.sql_iso(),
                        new_end.strftime("%Y-%m-%d %H:%M:%S"), provider,
                        self.TimeUtils.sql_iso(), self.TimeUtils.sql_iso(),
                    )
                    await self._refresh_user_subscription_end(conn, user_id)

                await self._invalidate_subscription_caches(user_id)
                return True

        except Exception as e:
            logger.error(f"❌ Error in grant_subscription_days: {e}", exc_info=True)
            return False

    async def expire_expired_subscriptions(self) -> None:
        """
        تعليم الاشتراكات المنتهية + تحديث users.subscription_end.
        تُستدعى دورياً من مهمة خلفية.
        """
        try:
            async with self.transaction() as conn:
                if self._is_postgres():
                    await conn.execute(
                        "UPDATE subscriptions SET status = 'expired' "
                        "WHERE status = 'active' AND end_date <= NOW()"
                    )
                    users = await self._fetchall_with_conn(
                        conn,
                        """SELECT DISTINCT user_id FROM subscriptions
                           WHERE status = 'expired'
                             AND end_date > NOW() - INTERVAL '1 day'""",
                    )
                elif self._is_mysql():
                    await conn.execute(
                        "UPDATE subscriptions SET status = 'expired' "
                        "WHERE status = 'active' AND end_date <= UTC_TIMESTAMP()"
                    )
                    users = await self._fetchall_with_conn(
                        conn,
                        """SELECT DISTINCT user_id FROM subscriptions
                           WHERE status = 'expired'
                             AND end_date > UTC_TIMESTAMP() - INTERVAL 1 DAY""",
                    )
                else:
                    await conn.execute(
                        "UPDATE subscriptions SET status = 'expired' "
                        "WHERE status = 'active' AND end_date <= datetime('now')"
                    )
                    users = await self._fetchall_with_conn(
                        conn,
                        """SELECT DISTINCT user_id FROM subscriptions
                           WHERE status = 'expired'
                             AND end_date > datetime('now', '-1 day')""",
                    )

                if not users:
                    return

                user_ids = [u["user_id"] for u in users]
                BATCH = 500

                for i in range(0, len(user_ids), BATCH):
                    batch = user_ids[i : i + BATCH]

                    if self._is_postgres():
                        placeholders = ",".join(f"${j+2}" for j in range(len(batch)))
                        await self._execute_with_conn(
                            conn,
                            f"""UPDATE users
                                SET subscription_end = (
                                    SELECT MAX(s.end_date) FROM subscriptions s
                                    WHERE s.user_id = users.user_id
                                      AND s.status = 'active'
                                      AND s.end_date > NOW()
                                ),
                                updated_at = $1
                                WHERE user_id IN ({placeholders})""",
                            self.TimeUtils.utc_now(),
                            *batch,
                        )
                    elif self._is_mysql():
                        placeholders = ",".join(["%s"] * len(batch))
                        await self._execute_with_conn(
                            conn,
                            f"""UPDATE users u
                                LEFT JOIN (
                                    SELECT user_id, MAX(end_date) AS max_end
                                    FROM subscriptions
                                    WHERE status = 'active'
                                      AND end_date > UTC_TIMESTAMP()
                                    GROUP BY user_id
                                ) s ON s.user_id = u.user_id
                                SET u.subscription_end = s.max_end,
                                    u.updated_at = %s
                                WHERE u.user_id IN ({placeholders})""",
                            self.TimeUtils.sql_iso(),
                            *batch,
                        )
                    else:
                        placeholders = ",".join(["?"] * len(batch))
                        await self._execute_with_conn(
                            conn,
                            f"""UPDATE users
                                SET subscription_end = (
                                    SELECT MAX(s.end_date) FROM subscriptions s
                                    WHERE s.user_id = users.user_id
                                      AND s.status = 'active'
                                      AND s.end_date > datetime('now')
                                ),
                                updated_at = ?
                                WHERE user_id IN ({placeholders})""",
                            self.TimeUtils.sql_iso(),
                            *batch,
                        )

                    for uid in batch:
                        await self._invalidate_subscription_caches(uid)

        except Exception as e:
            logger.error(
                f"❌ Error in expire_expired_subscriptions: {e}", exc_info=True
            )

    async def _refresh_user_subscription_end(self, conn, user_id: int) -> None:
        """
        تحديث users.subscription_end لأقصى تاريخ اشتراك نشط.
        ⚠️ دالة داخلية — تستدعى ضمن transaction مفتوح.
        """
        try:
            if self._is_postgres():
                end = await self._fetchval_with_conn(
                    conn,
                    "SELECT MAX(end_date) FROM subscriptions "
                    "WHERE user_id = $1 AND status = 'active' AND end_date > NOW()",
                    user_id,
                )
                await self._execute_with_conn(
                    conn,
                    "UPDATE users SET subscription_end = $1, updated_at = $2 "
                    "WHERE user_id = $3",
                    end, self.TimeUtils.utc_now(), user_id,
                )
            elif self._is_mysql():
                end = await self._fetchval_with_conn(
                    conn,
                    "SELECT MAX(end_date) FROM subscriptions "
                    "WHERE user_id = %s AND status = 'active' "
                    "AND end_date > UTC_TIMESTAMP()",
                    user_id,
                )
                await self._execute_with_conn(
                    conn,
                    "UPDATE users SET subscription_end = %s, updated_at = %s "
                    "WHERE user_id = %s",
                    end, self.TimeUtils.sql_iso(), user_id,
                )
            else:
                end = await self._fetchval_with_conn(
                    conn,
                    "SELECT MAX(end_date) FROM subscriptions "
                    "WHERE user_id = ? AND status = 'active' "
                    "AND end_date > datetime('now')",
                    user_id,
                )
                await self._execute_with_conn(
                    conn,
                    "UPDATE users SET subscription_end = ?, updated_at = ? "
                    "WHERE user_id = ?",
                    end, self.TimeUtils.sql_iso(), user_id,
                )
        except Exception as e:
            logger.error(
                f"❌ Error in _refresh_user_subscription_end: {e}", exc_info=True
            )

    # =================================================================
    # 3️⃣  أكواد الهدايا (Gift Codes)
    # =================================================================

    async def create_gift_code(
        self, plan_id: int, creator_id: int
    ) -> Optional[str]:
        """
        إنشاء كود هدية جديد.

        Returns:
            الكود (None عند الفشل)
        """
        try:
            async with self.connection() as conn:
                for attempt in range(5):
                    code = secrets.token_urlsafe(12)
                    try:
                        if self._is_postgres():
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO gift_codes "
                                "(code, plan_id, creator_id, created_at) "
                                "VALUES ($1, $2, $3, $4)",
                                code, plan_id, creator_id,
                                self.TimeUtils.utc_now(),
                            )
                        elif self._is_mysql():
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO gift_codes "
                                "(code, plan_id, creator_id, created_at) "
                                "VALUES (%s, %s, %s, %s)",
                                code, plan_id, creator_id,
                                self.TimeUtils.sql_iso(),
                            )
                        else:
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO gift_codes "
                                "(code, plan_id, creator_id, created_at) "
                                "VALUES (?,?,?,?)",
                                code, plan_id, creator_id,
                                self.TimeUtils.sql_iso(),
                            )
                        logger.info(
                            f"✅ تم إنشاء كود هدية {code} للباقة {plan_id}"
                        )
                        return code
                    except Exception as e:
                        err_lower = str(e).lower()
                        if "unique" in err_lower or "duplicate" in err_lower:
                            logger.warning(
                                f"⚠️ تصادم كود هدية، محاولة {attempt + 1}/5"
                            )
                            continue
                        raise
                logger.error("❌ فشل توليد كود فريد بعد 5 محاولات")
                return None
        except Exception as e:
            logger.error(f"❌ Error in create_gift_code: {e}", exc_info=True)
            return None

    async def redeem_gift_code(
        self, user_id: int, code: str
    ) -> Tuple[bool, int]:
        """
        استرداد كود هدية.

        Returns:
            (نجح؟, عدد الأيام)
            - (False, 0) : كود غير صالح أو مستخدم
            - (False, -1): المستخدم هو منشئ الكود
            - (True, N)  : نجح — N = عدد الأيام
        """
        try:
            code = code.strip()
            if not code:
                return False, 0

            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    gift_code = await self._fetchone_with_conn(
                        conn,
                        "SELECT * FROM gift_codes WHERE code = ?",
                        code,
                    )
                    if not gift_code:
                        return False, 0

                    if gift_code["used_by"]:
                        return False, 0

                    if gift_code["creator_id"] == user_id:
                        return False, -1

                    plan = await self._fetchone_with_conn(
                        conn,
                        "SELECT id, name, description, price, "
                        "duration_days AS days "
                        "FROM plans WHERE id = ? AND is_gift = 1 "
                        "AND is_active = 1",
                        gift_code["plan_id"],
                    )
                    if not plan:
                        return False, 0

                    # تعليم الكود كمستخدم
                    await self._execute_with_conn(
                        conn,
                        "UPDATE gift_codes "
                        "SET used_by = ?, used_at = ? WHERE id = ?",
                        user_id, self.TimeUtils.utc_now(), gift_code["id"],
                    )

                    current_end = await self._fetchval_with_conn(
                        conn,
                        "SELECT MAX(end_date) FROM subscriptions "
                        "WHERE user_id = ? AND status = 'active' "
                        "AND end_date > ?",
                        user_id, self.TimeUtils.sql_iso(),
                    )
                    current_end_dt = (
                        self.TimeUtils.safe_parse_iso(current_end)
                        if current_end else None
                    )
                    now = self.TimeUtils.utc_now()
                    base = (
                        current_end_dt
                        if current_end_dt and current_end_dt > now
                        else now
                    )
                    new_end = base + timedelta(days=plan["days"])

                    await self._execute_with_conn(
                        conn,
                        """INSERT INTO subscriptions
                           (user_id, plan_id, status, start_date, end_date,
                            provider, created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        user_id, gift_code["plan_id"], "active",
                        self.TimeUtils.sql_iso(),
                        new_end.strftime("%Y-%m-%d %H:%M:%S"), "gift",
                        self.TimeUtils.sql_iso(), self.TimeUtils.sql_iso(),
                    )
                    await self._refresh_user_subscription_end(conn, user_id)

                await self._invalidate_subscription_caches(user_id)
                logger.info(
                    f"✅ المستخدم {user_id} استرد كود هدية ({plan['days']} يوم)"
                )
                return True, plan["days"]

        except Exception as e:
            logger.error(f"❌ Error in redeem_gift_code: {e}", exc_info=True)
            return False, 0

    # =================================================================
    # 4️⃣  الفواتير والدفع (Invoices & Payments)
    # =================================================================

    async def create_invoice(
        self,
        user_id: int,
        plan_id: int,
        amount: int,
        currency: str = "XTR",
        provider: str = "xtr",
    ) -> str:
        """
        إنشاء فاتورة جديدة.

        Returns:
            رقم الفاتورة (سلسلة فارغة عند الفشل)
        """
        try:
            number = (
                f"INV-{self.TimeUtils.utc_now().strftime('%Y%m')}-"
                f"{secrets.token_urlsafe(12).upper()}"
            )
            result = await self.execute(
                "INSERT INTO invoices "
                "(number, user_id, plan_id, amount, currency, status, "
                "provider, created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (number, user_id, plan_id, amount, currency, "pending",
                 provider, self.TimeUtils.utc_now()),
            ) > 0
            return number if result else ""
        except Exception as e:
            logger.error(f"❌ Error in create_invoice: {e}", exc_info=True)
            return ""

    async def mark_invoice_paid(
        self, invoice_number: str, payment_id: str
    ) -> bool:
        """تعليم فاتورة كمدفوعة"""
        try:
            return await self.execute(
                "UPDATE invoices "
                "SET status = 'paid', provider_payment_id = ?, paid_at = ? "
                "WHERE number = ?",
                (payment_id, self.TimeUtils.utc_now(), invoice_number),
            ) > 0
        except Exception as e:
            logger.error(f"❌ Error in mark_invoice_paid: {e}", exc_info=True)
            return False

    async def get_invoice(self, number: str) -> Optional[Dict]:
        """جلب فاتورة برقمها"""
        try:
            return await self.fetchone(
                "SELECT * FROM invoices WHERE number = ?", (number,)
            )
        except Exception as e:
            logger.error(f"❌ Error in get_invoice: {e}", exc_info=True)
            return None

    async def get_user_invoices(
        self, user_id: int, limit: int = 20
    ) -> List[Dict]:
        """فواتير المستخدم"""
        try:
            return await self.fetchall(
                "SELECT * FROM invoices "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            )
        except Exception as e:
            logger.error(f"❌ Error in get_user_invoices: {e}", exc_info=True)
            return []

    async def add_payment_log(
        self,
        user_id: int,
        provider: str,
        event_type: str,
        data: dict,
    ) -> bool:
        """تسجيل حدث دفع"""
        try:
            return await self.execute(
                "INSERT INTO payment_logs "
                "(user_id, provider, event_type, data, created_at) "
                "VALUES (?,?,?,?,?)",
                (user_id, provider, event_type,
                 json.dumps(data, ensure_ascii=False),
                 self.TimeUtils.utc_now()),
            ) > 0
        except Exception as e:
            logger.error(f"❌ Error in add_payment_log: {e}", exc_info=True)
            return False

    async def activate_subscription_with_payment(
        self,
        user_id: int,
        invoice_number: str,
        payment_id: str,
        plan_id: int,
    ) -> bool:
        """
        تفعيل اشتراك بعد دفع ناجح.
        ⚠️ يتحقق من:
          - الفاتورة موجودة + pending
          - plan_id يطابق الفاتورة
        """
        try:
            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    plan = await self._fetchone_with_conn(
                        conn,
                        "SELECT * FROM plans "
                        "WHERE id = ? AND is_active = 1",
                        plan_id,
                    )
                    if not plan:
                        logger.error(f"❌ الخطة {plan_id} غير موجودة")
                        return False

                    invoice = await self._fetchone_with_conn(
                        conn,
                        "SELECT * FROM invoices "
                        "WHERE number = ? AND user_id = ? "
                        "AND status = 'pending'",
                        invoice_number, user_id,
                    )
                    if not invoice:
                        logger.warning(
                            f"⚠️ فاتورة غير صالحة: {invoice_number}"
                        )
                        return False

                    if invoice["plan_id"] != plan_id:
                        logger.warning(
                            f"⚠️ plan_id لا يطابق الفاتورة: "
                            f"{invoice['plan_id']} != {plan_id}"
                        )
                        return False

                    # تعليم الفاتورة كمدفوعة
                    await self._execute_with_conn(
                        conn,
                        "UPDATE invoices "
                        "SET status = 'paid', provider_payment_id = ?, "
                        "paid_at = ? WHERE number = ?",
                        payment_id, self.TimeUtils.utc_now(), invoice_number,
                    )

                    current_end = await self._fetchval_with_conn(
                        conn,
                        "SELECT MAX(end_date) FROM subscriptions "
                        "WHERE user_id = ? AND status = 'active' "
                        "AND end_date > ?",
                        user_id, self.TimeUtils.sql_iso(),
                    )
                    current_end_dt = (
                        self.TimeUtils.safe_parse_iso(current_end)
                        if current_end else None
                    )
                    now = self.TimeUtils.utc_now()
                    base = (
                        current_end_dt
                        if current_end_dt and current_end_dt > now
                        else now
                    )
                    new_end = base + timedelta(days=plan["duration_days"])

                    await self._execute_with_conn(
                        conn,
                        """INSERT INTO subscriptions
                           (user_id, plan_id, status, start_date, end_date,
                            auto_renew, provider, provider_subscription_id,
                            created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        user_id, plan_id, "active", self.TimeUtils.sql_iso(),
                        new_end.strftime("%Y-%m-%d %H:%M:%S"), 0,
                        "xtr", payment_id,
                        self.TimeUtils.sql_iso(), self.TimeUtils.sql_iso(),
                    )
                    await self._refresh_user_subscription_end(conn, user_id)

                await self._invalidate_subscription_caches(user_id)
                logger.info(
                    f"✅ تم تفعيل اشتراك المستخدم {user_id} "
                    f"(باقة {plan_id}, {plan['duration_days']} يوم)"
                )
                return True

        except Exception as e:
            logger.error(
                f"❌ Error in activate_subscription_with_payment: {e}",
                exc_info=True,
            )
            return False

    # =================================================================
    # 5️⃣  الإحالات (Referrals)
    # =================================================================

    async def get_referral_code(self, user_id: int) -> str:
        """جلب كود الإحالة (أو توليد fallback)"""
        try:
            result = await self.fetchval(
                "SELECT referral_code FROM users WHERE user_id = ?",
                (user_id,),
                default=f"ref_{user_id}",
            )
            return result if result else f"ref_{user_id}"
        except Exception as e:
            logger.error(f"❌ Error in get_referral_code: {e}", exc_info=True)
            return f"ref_{user_id}"

    async def get_user_by_referral_code(self, code: str) -> Optional[int]:
        """البحث عن مستخدم بكود الإحالة"""
        try:
            return await self.fetchval(
                "SELECT user_id FROM users WHERE referral_code = ?",
                (code,),
            )
        except Exception as e:
            logger.error(
                f"❌ Error in get_user_by_referral_code: {e}", exc_info=True
            )
            return None

    async def add_referral(
        self, referrer_id: int, referred_id: int
    ) -> bool:
        """
        إضافة إحالة جديدة.
        - يتحقق من عدم تجاوز الحد اليومي
        - يمنع الإحالة الذاتية
        - يمنح 3 أيام + 5 نقاط للمُحيل
        """
        if referrer_id == referred_id:
            return False

        try:
            async with await self._get_user_lock(referrer_id):
                async with self.transaction() as conn:
                    today = self.TimeUtils.utc_now().strftime("%Y-%m-%d")

                    # تحقق من الحد اليومي
                    count = await self._fetchval_with_conn(
                        conn,
                        "SELECT COUNT(*) FROM referrals "
                        "WHERE referrer_id = ? AND date(created_at) = ?",
                        referrer_id, today,
                        default=0,
                    )
                    max_daily = getattr(CONFIG, "MAX_DAILY_REFERRALS", 10)
                    if count >= max_daily:
                        logger.warning(
                            f"⚠️ المستخدم {referrer_id} "
                            f"وصل للحد اليومي ({max_daily})"
                        )
                        return False

                    # إدراج الإحالة
                    inserted = await self._execute_with_conn(
                        conn,
                        "INSERT OR IGNORE INTO referrals "
                        "(referrer_id, referred_id, created_at) "
                        "VALUES (?,?,?)",
                        referrer_id, referred_id,
                        self.TimeUtils.sql_iso(),
                    )

                    if inserted <= 0:
                        return False

                    # تحديث مكافآت المُحيل
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO referral_rewards "
                        "(user_id, referral_count, total_reward_days, "
                        "claimed_reward_days, last_referral_date) "
                        "VALUES (?,1,3,0,?) "
                        "ON CONFLICT(user_id) DO UPDATE SET "
                        "referral_count = referral_count + 1, "
                        "total_reward_days = total_reward_days + 3, "
                        "last_referral_date = ?",
                        referrer_id,
                        self.TimeUtils.utc_now(),
                        self.TimeUtils.utc_now(),
                    )

                    # إضافة نقاط
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO user_points "
                        "(user_id, points, last_updated) "
                        "VALUES (?,5,?) "
                        "ON CONFLICT(user_id) DO UPDATE SET "
                        "points = points + 5, last_updated = ?",
                        referrer_id,
                        self.TimeUtils.utc_now(),
                        self.TimeUtils.utc_now(),
                    )

                await self._invalidate_subscription_caches(referrer_id)
                return True

        except Exception as e:
            logger.error(f"❌ Error in add_referral: {e}", exc_info=True)
            return False

    async def get_referral_stats(self, user_id: int) -> Dict:
        """
        إحصائيات الإحالات.

        Returns:
            {"total": int, "claimed": int, "available": int}
        """
        try:
            async with self.connection() as conn:
                # ضمان وجود صف
                await self._execute_with_conn(
                    conn,
                    "INSERT OR IGNORE INTO referral_rewards "
                    "(user_id, referral_count, total_reward_days, "
                    "claimed_reward_days, last_referral_date) "
                    "VALUES (?, 0, 0, 0, NULL)",
                    user_id,
                )

                total = await self._fetchval_with_conn(
                    conn,
                    "SELECT COUNT(*) FROM referrals "
                    "WHERE referrer_id = ?",
                    user_id,
                    default=0,
                )

                reward = await self._fetchone_with_conn(
                    conn,
                    "SELECT COALESCE(total_reward_days, 0) AS total_reward, "
                    "COALESCE(claimed_reward_days, 0) AS claimed "
                    "FROM referral_rewards WHERE user_id = ?",
                    user_id,
                )

                total_reward = reward["total_reward"] if reward else 0
                claimed = reward["claimed"] if reward else 0

            return {
                "total": total,
                "claimed": claimed,
                "available": max(0, total_reward - claimed),
            }
        except Exception as e:
            logger.error(f"❌ Error in get_referral_stats: {e}", exc_info=True)
            return {"total": 0, "claimed": 0, "available": 0}

    async def claim_referral_reward(self, user_id: int) -> int:
        """
        استلام مكافأة الإحالات.

        Returns:
            عدد الأيام المُضافة (0 إذا لم توجد مكافآت)
        """
        try:
            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    # ضمان وجود صف
                    await self._execute_with_conn(
                        conn,
                        "INSERT OR IGNORE INTO referral_rewards "
                        "(user_id, referral_count, total_reward_days, "
                        "claimed_reward_days, last_referral_date) "
                        "VALUES (?, 0, 0, 0, NULL)",
                        user_id,
                    )

                    reward = await self._fetchone_with_conn(
                        conn,
                        "SELECT COALESCE(total_reward_days, 0) AS total_reward, "
                        "COALESCE(claimed_reward_days, 0) AS claimed "
                        "FROM referral_rewards WHERE user_id = ?",
                        user_id,
                    )
                    if not reward:
                        return 0

                    total_reward = reward["total_reward"] or 0
                    claimed = reward["claimed"] or 0
                    available = max(0, total_reward - claimed)

                    if available <= 0:
                        return 0

                    # اختيار الباقة: النشطة → هدية → "شهر"
                    plan_id = await self._fetchval_with_conn(
                        conn,
                        "SELECT s.plan_id FROM subscriptions s "
                        "JOIN plans p ON s.plan_id = p.id "
                        "WHERE s.user_id = ? AND s.status = 'active' "
                        "AND s.end_date > ? "
                        "ORDER BY p.max_channels DESC, p.max_posts DESC, "
                        "s.end_date DESC LIMIT 1",
                        user_id, self.TimeUtils.sql_iso(),
                    )
                    if not plan_id:
                        plan_id = await self._fetchval_with_conn(
                            conn,
                            "SELECT id FROM plans "
                            "WHERE is_gift = 1 AND is_active = 1 "
                            "ORDER BY max_channels DESC LIMIT 1",
                        )
                        if not plan_id:
                            plan_id = await self._fetchval_with_conn(
                                conn,
                                "SELECT id FROM plans "
                                "WHERE name = 'شهر' AND is_active = 1 LIMIT 1",
                            )
                            if not plan_id:
                                logger.error(
                                    "❌ لا يوجد plan_id افتراضي للمكافأة"
                                )
                                return 0

                    # تحديث claimed
                    await self._execute_with_conn(
                        conn,
                        "UPDATE referral_rewards "
                        "SET claimed_reward_days = claimed_reward_days + ? "
                        "WHERE user_id = ?",
                        available, user_id,
                    )

                    # حساب تاريخ الانتهاء الجديد
                    current_end = await self._fetchval_with_conn(
                        conn,
                        "SELECT MAX(end_date) FROM subscriptions "
                        "WHERE user_id = ? AND status = 'active' "
                        "AND end_date > ?",
                        user_id, self.TimeUtils.sql_iso(),
                    )
                    current_end_dt = (
                        self.TimeUtils.safe_parse_iso(current_end)
                        if current_end else None
                    )
                    now = self.TimeUtils.utc_now()
                    base = (
                        current_end_dt
                        if current_end_dt and current_end_dt > now
                        else now
                    )
                    new_end = base + timedelta(days=available)

                    await self._execute_with_conn(
                        conn,
                        """INSERT INTO subscriptions
                           (user_id, plan_id, status, start_date, end_date,
                            provider, created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        user_id, plan_id, "active",
                        self.TimeUtils.sql_iso(),
                        new_end.strftime("%Y-%m-%d %H:%M:%S"),
                        "referral",
                        self.TimeUtils.sql_iso(),
                        self.TimeUtils.sql_iso(),
                    )
                    await self._refresh_user_subscription_end(conn, user_id)

                await self._invalidate_subscription_caches(user_id)
                logger.info(
                    f"✅ المستخدم {user_id} استلم {available} يوم مكافأة"
                )
                return available

        except Exception as e:
            logger.error(
                f"❌ Error in claim_referral_reward: {e}", exc_info=True
            )
            return 0

    async def get_referrals_list(self, user_id: int) -> List[int]:
        """قائمة معرّفات المحالين"""
        try:
            referrals = await self.fetchall(
                "SELECT referred_id FROM referrals "
                "WHERE referrer_id = ? ORDER BY created_at DESC",
                (user_id,),
            )
            return [ref["referred_id"] for ref in referrals]
        except Exception as e:
            logger.error(f"❌ Error in get_referrals_list: {e}", exc_info=True)
            return []

    async def get_referral_count(self, user_id: int) -> int:
        """عدد الإحالات (سريع)"""
        try:
            return await self.fetchval(
                "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?",
                (user_id,),
                default=0,
            )
        except Exception as e:
            logger.error(f"❌ Error in get_referral_count: {e}", exc_info=True)
            return 0