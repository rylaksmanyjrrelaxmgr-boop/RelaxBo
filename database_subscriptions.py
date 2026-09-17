#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_subscriptions.py - وحدة الباقات والاشتراكات والفواتير والإحالات
v7.7.29 — دعم كامل لـ SQLite + PostgreSQL + MySQL
=====================================================================
✅ v7.7.29 — إصلاحات ما بعد التدقيق:
  1) get_users_for_reminder: HAVING بلا alias — PG كان يفشل بالكامل
  2) add_referral: نطاق زمني بدل date() — أسرع + متوافق مع asyncpg
  3) redeem_gift_code: UPDATE ذرّي (WHERE used_by IS NULL) — منع سباق
  4) has_active_subscription: JOIN plans + p.is_active = 1
     (توحيد مع Database.has_active_subscription)
  5) expire_expired_subscriptions: تُرجع عدد المنتهين
     + استخدام _execute_with_conn للـ rowcount الصحيح

✅ v7.7.0 — إصلاحات حرجة (محفوظة):
  1) activate_trial: فحص ذرّي لـ trial_used
  2) create_gift_code: معاملة جديدة لكل محاولة
  3) activate_trial: -1 عند وجود اشتراك أطول
  4) expire_expired_subscriptions: فلترة المنتهين الآن فقط
  5) create_subscription: توحيد نمط PG
=====================================================================
"""

import os
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


# =====================================================================
# 0) كشف نوع قاعدة البيانات
# =====================================================================
_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
_URL_LOWER = _DATABASE_URL.lower()
USE_POSTGRES = "postgres" in _URL_LOWER
USE_MYSQL = "mysql" in _URL_LOWER or "mariadb" in _URL_LOWER


# =====================================================================
# 0.1) Placeholder Helpers
# =====================================================================
def _ph(n: int = 1) -> str:
    if USE_POSTGRES:
        return f"${n}"
    if USE_MYSQL:
        return "%s"
    return "?"


def _phs(count: int) -> str:
    if USE_POSTGRES:
        return ", ".join(f"${i}" for i in range(1, count + 1))
    if USE_MYSQL:
        return ", ".join(["%s"] * count)
    return ", ".join(["?"] * count)


# =====================================================================
# 1) CONFIG / PATHS (fallback)
# =====================================================================
try:
    from config import CONFIG, PATHS
except ImportError:
    from pathlib import Path as _Path

    class PATHS:
        DB = _Path("data/relax.db")
        BACKUPS = _Path("data/backups")
        DB.parent.mkdir(parents=True, exist_ok=True)
        BACKUPS.mkdir(parents=True, exist_ok=True)

    class CONFIG:
        PRIMARY_OWNER_ID = 0
        MAX_DAILY_REFERRALS = 10
        MAX_GLOBAL_BANNED_WORDS = 500


# =====================================================================
# 2) user_cache (fallback)
# =====================================================================
try:
    from cache import user_cache
except ImportError:
    class _DummyUserCache:
        async def get(self, user_id): return None
        async def set(self, user_id, data): return None
        async def invalidate(self, user_id=None): return None
        async def clear(self): return None

    user_cache = _DummyUserCache()
    logger.warning("⚠️ cache.py غير متاح — user_cache = Dummy")


# =====================================================================
# 3) TimeUtils
# =====================================================================
_UTC = timezone.utc


class TimeUtils:
    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(_UTC).replace(tzinfo=None)

    @staticmethod
    def mecca_now() -> datetime:
        return TimeUtils.utc_now() + timedelta(hours=3)

    @staticmethod
    def utc_iso() -> str:
        return TimeUtils.utc_now().isoformat()

    @staticmethod
    def sql_iso() -> str:
        return TimeUtils.utc_now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def mecca_to_utc(dt):
        if dt is None: return None
        if dt.tzinfo is not None: dt = dt.replace(tzinfo=None)
        return dt - timedelta(hours=3)

    @staticmethod
    def utc_to_mecca(dt):
        if dt is None: return None
        if dt.tzinfo is not None: dt = dt.replace(tzinfo=None)
        return dt + timedelta(hours=3)

    @staticmethod
    def safe_parse_iso(date_str):
        if date_str is None: return None
        if isinstance(date_str, datetime):
            if date_str.tzinfo is not None:
                return date_str.astimezone(_UTC).replace(tzinfo=None)
            return date_str
        if not isinstance(date_str, str): return None
        if date_str.endswith("+00:00"):
            date_str = date_str[:-6]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                pass
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(_UTC).replace(tzinfo=None)
            return dt
        except (ValueError, TypeError):
            return None


# =====================================================================
# 4) _table_exists
# =====================================================================
async def _table_exists(conn, table: str) -> bool:
    try:
        if USE_POSTGRES:
            row = await conn.fetchval(
                "SELECT 1 FROM information_schema.tables WHERE table_name = $1",
                table,
            )
            return row is not None
        elif USE_MYSQL:
            cursor = await conn.cursor()
            await cursor.execute("SHOW TABLES LIKE %s", (table,))
            row = await cursor.fetchone()
            await cursor.close()
            return row is not None
        else:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            )
            row = await cursor.fetchone()
            return row is not None
    except Exception:
        return False


# =====================================================================
# 5) SubscriptionMixin
# =====================================================================
class SubscriptionMixin:
    """
    يتطلب أن الفئة الأم توفّر:
      self.fetchval/fetchone/fetchall/execute
      self.connection()/self.transaction()
      self._fetchone_with_conn/_fetchall_with_conn
      self._fetchval_with_conn/_execute_with_conn
      self._get_user_lock
    """

    # -----------------------------------------------------------------
    # Helper داخلي: جلب MAX(end_date) من الاشتراكات الفعّالة
    # -----------------------------------------------------------------
    async def _get_current_end(self, conn, user_id: int) -> Optional[datetime]:
        sql = (
            f"SELECT MAX(end_date) FROM subscriptions "
            f"WHERE user_id = {_ph(1)} AND status = 'active' "
            f"AND end_date > {_ph(2)}"
        )
        now_param = TimeUtils.utc_now() if USE_POSTGRES else TimeUtils.sql_iso()
        result = await self._fetchval_with_conn(conn, sql, user_id, now_param)
        return TimeUtils.safe_parse_iso(result) if result else None

    # -----------------------------------------------------------------
    # Helper: INSERT subscription (8 أعمدة)
    # -----------------------------------------------------------------
    async def _insert_subscription_simple(
        self, conn, user_id: int, plan_id: int,
        new_end: datetime, provider: str,
    ) -> bool:
        sql = (
            f"INSERT INTO subscriptions "
            f"(user_id, plan_id, status, start_date, end_date, "
            f" provider, created_at, updated_at) "
            f"VALUES ({_phs(8)})"
        )
        if USE_POSTGRES:
            await self._execute_with_conn(
                conn, sql, user_id, plan_id, 'active',
                TimeUtils.utc_now(), new_end, provider,
                TimeUtils.utc_now(), TimeUtils.utc_now(),
            )
        else:
            await self._execute_with_conn(
                conn, sql, user_id, plan_id, 'active',
                TimeUtils.sql_iso(),
                new_end.strftime('%Y-%m-%d %H:%M:%S'), provider,
                TimeUtils.sql_iso(), TimeUtils.sql_iso(),
            )
        return True

    # -----------------------------------------------------------------
    # Helper: INSERT subscription (10 أعمدة)
    # -----------------------------------------------------------------
    async def _insert_subscription_full(
        self, conn, user_id: int, plan_id: int,
        new_end: datetime, provider: str,
        provider_sub_id: Optional[str] = None,
    ) -> bool:
        sql = (
            f"INSERT INTO subscriptions "
            f"(user_id, plan_id, status, start_date, end_date, "
            f" auto_renew, provider, provider_subscription_id, "
            f" created_at, updated_at) "
            f"VALUES ({_phs(10)})"
        )
        if USE_POSTGRES:
            await self._execute_with_conn(
                conn, sql, user_id, plan_id, 'active',
                TimeUtils.utc_now(), new_end, 0, provider,
                provider_sub_id, TimeUtils.utc_now(), TimeUtils.utc_now(),
            )
        else:
            await self._execute_with_conn(
                conn, sql, user_id, plan_id, 'active',
                TimeUtils.sql_iso(),
                new_end.strftime('%Y-%m-%d %H:%M:%S'),
                0, provider, provider_sub_id,
                TimeUtils.sql_iso(), TimeUtils.sql_iso(),
            )
        return True

    # -----------------------------------------------------------------
    # Helper: UPSERT referral_rewards (+1 عدّاد، +3 أيام)
    # -----------------------------------------------------------------
    async def _upsert_referral_reward(self, conn, user_id: int) -> None:
        if USE_POSTGRES:
            sql = (
                "INSERT INTO referral_rewards "
                "(user_id, referral_count, total_reward_days, "
                " claimed_reward_days, last_referral_date) "
                "VALUES ($1, 1, 3, 0, $2) "
                "ON CONFLICT (user_id) DO UPDATE SET "
                " referral_count = referral_rewards.referral_count + 1, "
                " total_reward_days = referral_rewards.total_reward_days + 3, "
                " last_referral_date = $2"
            )
            await self._execute_with_conn(
                conn, sql, user_id, TimeUtils.utc_now()
            )
        elif USE_MYSQL:
            sql = (
                "INSERT INTO referral_rewards "
                "(user_id, referral_count, total_reward_days, "
                " claimed_reward_days, last_referral_date) "
                "VALUES (%s, 1, 3, 0, %s) "
                "ON DUPLICATE KEY UPDATE "
                " referral_count = referral_count + 1, "
                " total_reward_days = total_reward_days + 3, "
                " last_referral_date = VALUES(last_referral_date)"
            )
            await self._execute_with_conn(
                conn, sql, user_id, TimeUtils.sql_iso()
            )
        else:
            sql = (
                "INSERT INTO referral_rewards "
                "(user_id, referral_count, total_reward_days, "
                " claimed_reward_days, last_referral_date) "
                "VALUES (?, 1, 3, 0, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                " referral_count = referral_count + 1, "
                " total_reward_days = total_reward_days + 3, "
                " last_referral_date = ?"
            )
            await self._execute_with_conn(
                conn, sql, user_id, TimeUtils.sql_iso(), TimeUtils.sql_iso()
            )

    # -----------------------------------------------------------------
    # Helper: UPSERT user_points (+points)
    # -----------------------------------------------------------------
    async def _upsert_user_points(
        self, conn, user_id: int, points: int
    ) -> None:
        if USE_POSTGRES:
            sql = (
                "INSERT INTO user_points (user_id, points, last_updated) "
                "VALUES ($1, $2, $3) "
                "ON CONFLICT (user_id) DO UPDATE SET "
                " points = user_points.points + $2, last_updated = $3"
            )
            await self._execute_with_conn(
                conn, sql, user_id, points, TimeUtils.utc_now()
            )
        elif USE_MYSQL:
            sql = (
                "INSERT INTO user_points (user_id, points, last_updated) "
                "VALUES (%s, %s, %s) "
                "ON DUPLICATE KEY UPDATE "
                " points = points + VALUES(points), "
                " last_updated = VALUES(last_updated)"
            )
            await self._execute_with_conn(
                conn, sql, user_id, points, TimeUtils.sql_iso()
            )
        else:
            sql = (
                "INSERT INTO user_points (user_id, points, last_updated) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                " points = points + ?, last_updated = ?"
            )
            await self._execute_with_conn(
                conn, sql, user_id, points, TimeUtils.sql_iso(),
                points, TimeUtils.sql_iso(),
            )

    # -----------------------------------------------------------------
    # Helper: INSERT OR IGNORE صف referral_rewards فارغ
    # -----------------------------------------------------------------
    async def _ensure_referral_reward_row(self, conn, user_id: int) -> None:
        if USE_POSTGRES:
            sql = (
                "INSERT INTO referral_rewards "
                "(user_id, referral_count, total_reward_days, "
                " claimed_reward_days, last_referral_date) "
                "VALUES ($1, 0, 0, 0, NULL) "
                "ON CONFLICT (user_id) DO NOTHING"
            )
        elif USE_MYSQL:
            sql = (
                "INSERT IGNORE INTO referral_rewards "
                "(user_id, referral_count, total_reward_days, "
                " claimed_reward_days, last_referral_date) "
                "VALUES (%s, 0, 0, 0, NULL)"
            )
        else:
            sql = (
                "INSERT OR IGNORE INTO referral_rewards "
                "(user_id, referral_count, total_reward_days, "
                " claimed_reward_days, last_referral_date) "
                "VALUES (?, 0, 0, 0, NULL)"
            )
        await self._execute_with_conn(conn, sql, user_id)

    # -----------------------------------------------------------------
    # Helper: قراءة total_reward / claimed
    # -----------------------------------------------------------------
    async def _read_referral_reward(self, conn, user_id: int) -> Optional[Dict]:
        sql = (
            f"SELECT COALESCE(total_reward_days, 0) AS total_reward, "
            f"       COALESCE(claimed_reward_days, 0) AS claimed "
            f"FROM referral_rewards WHERE user_id = {_ph(1)}"
        )
        return await self._fetchone_with_conn(conn, sql, user_id)

    # =================================================================
    # الاشتراك الأساسي
    # =================================================================
    async def has_active_subscription(self, user_id: int) -> bool:
        """
        ✅ v7.7.29: JOIN plans + p.is_active = 1
        (توحيد مع Database.has_active_subscription v7.7.26)
        """
        sql = (
            f"SELECT 1 FROM subscriptions s "
            f"JOIN plans p ON s.plan_id = p.id "
            f"WHERE s.user_id = {_ph(1)} AND s.status = 'active' "
            f"AND s.end_date > {_ph(2)} "
            f"AND p.is_active = 1 "
            f"LIMIT 1"
        )
        now_param = TimeUtils.utc_now() if USE_POSTGRES else TimeUtils.sql_iso()
        result = await self.fetchval(sql, (user_id, now_param))
        return result is not None

    async def has_used_trial(self, user_id: int) -> bool:
        sql = f"SELECT trial_used FROM users WHERE user_id = {_ph(1)}"
        result = await self.fetchval(sql, (user_id,), default=0)
        return result == 1

    async def activate_trial(self, user_id: int) -> int:
        """
        Returns:
            30   : تم تفعيل التجربة
            0    : فشل، أو المستخدم استخدم التجربة مسبقاً
            -1   : فُعّلت، لكن اشتراك المستخدم الحالي أطول
        """
        try:
            async with await self._get_user_lock(user_id):
                now = TimeUtils.utc_now()
                trial_end = now + timedelta(days=30)
                async with self.transaction() as conn:
                    trial_used = await self._fetchval_with_conn(
                        conn,
                        f"SELECT trial_used FROM users WHERE user_id = {_ph(1)}",
                        user_id,
                        default=1,
                    )
                    if trial_used == 1:
                        return 0

                    trial_plan_id = await self._fetchval_with_conn(
                        conn,
                        "SELECT id FROM plans WHERE name = 'تجربة' "
                        "AND is_active = 1 LIMIT 1",
                        default=1,
                    )
                    current_end_dt = await self._get_current_end(conn, user_id)

                    if current_end_dt and current_end_dt > trial_end:
                        days_granted = -1
                        new_end = current_end_dt
                    else:
                        days_granted = 30
                        new_end = trial_end

                    sql_upd = (
                        f"UPDATE users SET trial_used = 1, "
                        f"updated_at = {_ph(1)} WHERE user_id = {_ph(2)}"
                    )
                    upd_now = (
                        TimeUtils.utc_now() if USE_POSTGRES
                        else TimeUtils.sql_iso()
                    )
                    await self._execute_with_conn(
                        conn, sql_upd, upd_now, user_id
                    )

                    sql_end = (
                        f"UPDATE users SET subscription_end = {_ph(1)} "
                        f"WHERE user_id = {_ph(2)}"
                    )
                    end_val = (
                        new_end if USE_POSTGRES
                        else new_end.strftime('%Y-%m-%d %H:%M:%S')
                    )
                    await self._execute_with_conn(
                        conn, sql_end, end_val, user_id
                    )

                    if days_granted > 0:
                        await self._insert_subscription_simple(
                            conn, user_id, trial_plan_id,
                            new_end, 'trial',
                        )

                    await self._refresh_user_subscription_end(conn, user_id)
                    await user_cache.invalidate(user_id)
                    return days_granted
        except Exception as e:
            logger.error(f"❌ activate_trial: {e}", exc_info=True)
            return 0

    # =================================================================
    # الإحالة (كود)
    # =================================================================
    async def get_referral_code(self, user_id: int) -> str:
        sql = f"SELECT referral_code FROM users WHERE user_id = {_ph(1)}"
        result = await self.fetchval(sql, (user_id,), default=f"ref_{user_id}")
        return result if result else f"ref_{user_id}"

    async def get_user_by_referral_code(self, code: str) -> Optional[int]:
        sql = f"SELECT user_id FROM users WHERE referral_code = {_ph(1)}"
        return await self.fetchval(sql, (code,))

    # =================================================================
    # الاشتراك النشط
    # =================================================================
    async def get_active_subscription(self, user_id: int) -> Optional[Dict]:
        sql = (
            f"SELECT s.*, p.name, p.duration_days, p.max_channels, "
            f"       p.max_posts, p.features "
            f"FROM subscriptions s "
            f"JOIN plans p ON s.plan_id = p.id AND p.is_active = 1 "
            f"WHERE s.user_id = {_ph(1)} AND s.status = 'active' "
            f"AND s.end_date > {_ph(2)} "
            f"ORDER BY p.max_channels DESC, p.max_posts DESC, "
            f"         s.end_date DESC LIMIT 1"
        )
        now_param = TimeUtils.utc_now() if USE_POSTGRES else TimeUtils.sql_iso()
        return await self.fetchone(sql, (user_id, now_param))

    async def get_active_plan(self, user_id: int) -> Optional[Dict]:
        sub = await self.get_active_subscription(user_id)
        if sub:
            return await self.get_plan(sub['plan_id'])
        return None

    async def get_subscription_end(self, user_id: int) -> Optional[datetime]:
        sql = f"SELECT subscription_end FROM users WHERE user_id = {_ph(1)}"
        result = await self.fetchval(sql, (user_id,))
        return TimeUtils.safe_parse_iso(result) if result else None

    # =================================================================
    # الباقات
    # =================================================================
    async def get_plan(self, plan_id: int) -> Optional[Dict]:
        sql = f"SELECT * FROM plans WHERE id = {_ph(1)} AND is_active = 1"
        return await self.fetchone(sql, (plan_id,))

    async def get_plan_by_name(self, name: str) -> Optional[Dict]:
        sql = (
            f"SELECT * FROM plans WHERE name = {_ph(1)} "
            f"AND is_active = 1 LIMIT 1"
        )
        return await self.fetchone(sql, (name,))

    async def get_all_plans(self) -> List[Dict]:
        return await self.fetchall(
            "SELECT * FROM plans WHERE is_active = 1 AND is_gift = 0 "
            "ORDER BY price"
        )

    async def get_gift_plans(self) -> List[Dict]:
        return await self.fetchall(
            "SELECT id, name, description, price, "
            "       duration_days AS days "
            "FROM plans WHERE is_active = 1 AND is_gift = 1 ORDER BY price"
        )

    async def get_gift_plan(self, plan_id: int) -> Optional[Dict]:
        sql = (
            f"SELECT id, name, description, price, duration_days AS days "
            f"FROM plans WHERE id = {_ph(1)} AND is_gift = 1 "
            f"AND is_active = 1"
        )
        return await self.fetchone(sql, (plan_id,))

    # =================================================================
    # استرداد كود الهدية
    # =================================================================
    async def redeem_gift_code(self, user_id: int, code: str) -> tuple:
        """
        ✅ v7.7.29: UPDATE ذرّي (WHERE used_by IS NULL) لمنع سباق
        استرداد مزدوج للكود نفسه.
        """
        try:
            code = code.strip()
            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    sql_gc = (
                        f"SELECT * FROM gift_codes WHERE code = {_ph(1)}"
                    )
                    gift_code = await self._fetchone_with_conn(
                        conn, sql_gc, code
                    )
                    if not gift_code:
                        return False, 0
                    if gift_code['used_by']:
                        return False, 0
                    if gift_code['creator_id'] == user_id:
                        return False, -1

                    sql_plan = (
                        f"SELECT id, name, description, price, "
                        f"       duration_days AS days "
                        f"FROM plans WHERE id = {_ph(1)} AND is_gift = 1 "
                        f"AND is_active = 1"
                    )
                    plan = await self._fetchone_with_conn(
                        conn, sql_plan, gift_code['plan_id']
                    )
                    if not plan:
                        return False, 0

                    # ✅ v7.7.29: WHERE used_by IS NULL — منع سباق
                    sql_upd = (
                        f"UPDATE gift_codes SET used_by = {_ph(1)}, "
                        f"used_at = {_ph(2)} "
                        f"WHERE id = {_ph(3)} AND used_by IS NULL"
                    )
                    used_at = (
                        TimeUtils.utc_now() if USE_POSTGRES
                        else TimeUtils.sql_iso()
                    )
                    updated = await self._execute_with_conn(
                        conn, sql_upd, user_id, used_at, gift_code['id']
                    )
                    if updated == 0:
                        # سباق — استُبدل الكود من process آخر
                        logger.info(
                            f"ℹ️ gift_code '{code}' سُبق في الاسترداد"
                        )
                        return False, 0

                    current_end = await self._get_current_end(conn, user_id)
                    now = TimeUtils.utc_now()
                    base = (
                        current_end if current_end and current_end > now
                        else now
                    )
                    new_end = base + timedelta(days=plan['days'])

                    await self._insert_subscription_simple(
                        conn, user_id, gift_code['plan_id'],
                        new_end, 'gift',
                    )

                    await self._refresh_user_subscription_end(conn, user_id)
                    await user_cache.invalidate(user_id)
                    return True, plan['days']
        except Exception as e:
            logger.error(f"❌ redeem_gift_code: {e}", exc_info=True)
            return False, 0

    # =================================================================
    # منح اشتراك يدوي
    # =================================================================
    async def grant_subscription_days(
        self, user_id: int, days: int,
        plan_id: Optional[int] = None, provider: str = 'manual',
    ) -> bool:
        try:
            if days <= 0:
                return False
            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    sql_ex = (
                        f"SELECT 1 FROM users WHERE user_id = {_ph(1)}"
                    )
                    exists = await self._fetchval_with_conn(
                        conn, sql_ex, user_id
                    )
                    if not exists:
                        return False

                    if not plan_id:
                        plan_id = await self._fetchval_with_conn(
                            conn,
                            "SELECT id FROM plans WHERE is_gift = 1 "
                            "AND is_active = 1 "
                            "ORDER BY max_channels DESC LIMIT 1",
                        )
                        if not plan_id:
                            plan_id = await self._fetchval_with_conn(
                                conn,
                                "SELECT id FROM plans WHERE name = 'شهر' "
                                "AND is_active = 1 LIMIT 1",
                            )
                            if not plan_id:
                                return False

                    current_end = await self._get_current_end(conn, user_id)
                    now = TimeUtils.utc_now()
                    base = (
                        current_end if current_end and current_end > now
                        else now
                    )
                    new_end = base + timedelta(days=days)

                    await self._insert_subscription_simple(
                        conn, user_id, plan_id, new_end, provider
                    )
                    await self._refresh_user_subscription_end(conn, user_id)
                    await user_cache.invalidate(user_id)
                    return True
        except Exception as e:
            logger.error(
                f"❌ grant_subscription_days: {e}", exc_info=True
            )
            return False

    # =================================================================
    # إنشاء اشتراك
    # =================================================================
    async def create_subscription(
        self, user_id: int, plan_id: int,
        provider: str = 'xtr', provider_sub_id: Optional[str] = None,
    ) -> int:
        try:
            plan = await self.get_plan(plan_id)
            if not plan:
                return 0

            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    current_end = await self._get_current_end(conn, user_id)
                    now = TimeUtils.utc_now()
                    base = (
                        current_end if current_end and current_end > now
                        else now
                    )
                    new_end = base + timedelta(days=plan['duration_days'])

                    if USE_POSTGRES:
                        sql = (
                            f"INSERT INTO subscriptions "
                            f"(user_id, plan_id, status, start_date, end_date, "
                            f" auto_renew, provider, provider_subscription_id, "
                            f" created_at, updated_at) "
                            f"VALUES ({_phs(10)}) "
                            f"RETURNING id"
                        )
                        row = await self._fetchone_with_conn(
                            conn, sql, user_id, plan_id, 'active',
                            TimeUtils.utc_now(), new_end, 0, provider,
                            provider_sub_id, TimeUtils.utc_now(),
                            TimeUtils.utc_now(),
                        )
                        sub_id = row['id'] if row else 0
                    elif USE_MYSQL:
                        sql = (
                            f"INSERT INTO subscriptions "
                            f"(user_id, plan_id, status, start_date, end_date, "
                            f" auto_renew, provider, provider_subscription_id, "
                            f" created_at, updated_at) "
                            f"VALUES ({_phs(10)})"
                        )
                        cursor = await conn.cursor()
                        await cursor.execute(
                            sql,
                            (user_id, plan_id, 'active', TimeUtils.sql_iso(),
                             new_end.strftime('%Y-%m-%d %H:%M:%S'),
                             0, provider, provider_sub_id,
                             TimeUtils.sql_iso(), TimeUtils.sql_iso()),
                        )
                        sub_id = cursor.lastrowid
                        await cursor.close()
                    else:
                        sql = (
                            f"INSERT INTO subscriptions "
                            f"(user_id, plan_id, status, start_date, end_date, "
                            f" auto_renew, provider, provider_subscription_id, "
                            f" created_at, updated_at) "
                            f"VALUES ({_phs(10)})"
                        )
                        cursor = await conn.execute(
                            sql,
                            (user_id, plan_id, 'active', TimeUtils.sql_iso(),
                             new_end.strftime('%Y-%m-%d %H:%M:%S'),
                             0, provider, provider_sub_id,
                             TimeUtils.sql_iso(), TimeUtils.sql_iso()),
                        )
                        sub_id = cursor.lastrowid or 0

                    await self._refresh_user_subscription_end(conn, user_id)
                    await user_cache.invalidate(user_id)
                    return sub_id
        except Exception as e:
            logger.error(f"❌ create_subscription: {e}", exc_info=True)
            return 0

    # =================================================================
    # انتهاء الاشتراكات
    # =================================================================
    async def expire_expired_subscriptions(self) -> int:
        """
        ✅ v7.7.29: تُرجع عدد الاشتراكات المُنتهية.
        تستخدم _execute_with_conn لـ rowcount موحد عبر DBs.
        """
        expired_count = 0
        try:
            async with self.transaction() as conn:
                if USE_POSTGRES:
                    soon_expiring = await self._fetchall_with_conn(
                        conn,
                        "SELECT DISTINCT user_id FROM subscriptions "
                        "WHERE status = 'active' "
                        "AND end_date <= CURRENT_TIMESTAMP AT TIME ZONE 'UTC'",
                    )
                    expired_count = await self._execute_with_conn(
                        conn,
                        "UPDATE subscriptions SET status = 'expired' "
                        "WHERE status = 'active' "
                        "AND end_date <= CURRENT_TIMESTAMP AT TIME ZONE 'UTC'",
                    )
                elif USE_MYSQL:
                    soon_expiring = await self._fetchall_with_conn(
                        conn,
                        "SELECT DISTINCT user_id FROM subscriptions "
                        "WHERE status = 'active' "
                        "AND end_date <= UTC_TIMESTAMP()",
                    )
                    expired_count = await self._execute_with_conn(
                        conn,
                        "UPDATE subscriptions SET status = 'expired' "
                        "WHERE status = 'active' "
                        "AND end_date <= UTC_TIMESTAMP()",
                    )
                else:
                    soon_expiring = await self._fetchall_with_conn(
                        conn,
                        "SELECT DISTINCT user_id FROM subscriptions "
                        "WHERE status = 'active' "
                        "AND end_date <= datetime('now')",
                    )
                    expired_count = await self._execute_with_conn(
                        conn,
                        "UPDATE subscriptions SET status = 'expired' "
                        "WHERE status = 'active' "
                        "AND end_date <= datetime('now')",
                    )

                for user in soon_expiring:
                    await self._refresh_user_subscription_end(
                        conn, user['user_id']
                    )
                    await user_cache.invalidate(user['user_id'])
        except Exception as e:
            logger.error(
                f"❌ expire_expired_subscriptions: {e}", exc_info=True
            )
        return expired_count or 0

    async def _refresh_user_subscription_end(self, conn, user_id: int) -> None:
        if USE_POSTGRES:
            end = await self._fetchval_with_conn(
                conn,
                "SELECT MAX(end_date) FROM subscriptions "
                "WHERE user_id = $1 AND status = 'active' "
                "AND end_date > CURRENT_TIMESTAMP AT TIME ZONE 'UTC'",
                user_id,
            )
            await self._execute_with_conn(
                conn,
                "UPDATE users SET subscription_end = $1, updated_at = $2 "
                "WHERE user_id = $3",
                end, TimeUtils.utc_now(), user_id,
            )
        elif USE_MYSQL:
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
                end, TimeUtils.sql_iso(), user_id,
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
                end, TimeUtils.sql_iso(), user_id,
            )

    # =================================================================
    # الفواتير
    # =================================================================
    async def create_invoice(
        self, user_id: int, plan_id: int, amount: int,
        currency: str = 'XTR', provider: str = 'xtr',
    ) -> str:
        number = (
            f"INV-{TimeUtils.utc_now().strftime('%Y%m')}-"
            f"{secrets.token_urlsafe(12).upper()}"
        )
        sql = (
            f"INSERT INTO invoices "
            f"(number, user_id, plan_id, amount, currency, status, "
            f" provider, created_at) "
            f"VALUES ({_phs(8)})"
        )
        created = (
            TimeUtils.utc_now() if USE_POSTGRES else TimeUtils.sql_iso()
        )
        result = await self.execute(
            sql, (number, user_id, plan_id, amount, currency,
                  'pending', provider, created),
        )
        return number if result > 0 else ""

    async def mark_invoice_paid(
        self, invoice_number: str, payment_id: str
    ) -> bool:
        sql = (
            f"UPDATE invoices SET status = 'paid', "
            f"       provider_payment_id = {_ph(1)}, paid_at = {_ph(2)} "
            f"WHERE number = {_ph(3)}"
        )
        paid_at = TimeUtils.utc_now() if USE_POSTGRES else TimeUtils.sql_iso()
        return await self.execute(
            sql, (payment_id, paid_at, invoice_number)
        ) > 0

    async def get_invoice(self, number: str) -> Optional[Dict]:
        sql = f"SELECT * FROM invoices WHERE number = {_ph(1)}"
        return await self.fetchone(sql, (number,))

    async def get_user_invoices(
        self, user_id: int, limit: int = 20
    ) -> List[Dict]:
        sql = (
            f"SELECT * FROM invoices WHERE user_id = {_ph(1)} "
            f"ORDER BY created_at DESC LIMIT {_ph(2)}"
        )
        return await self.fetchall(sql, (user_id, limit))

    # =================================================================
    # سجلات الدفع
    # =================================================================
    async def add_payment_log(
        self, user_id: int, provider: str,
        event_type: str, data: dict,
    ) -> bool:
        sql = (
            f"INSERT INTO payment_logs "
            f"(user_id, provider, event_type, data, created_at) "
            f"VALUES ({_phs(5)})"
        )
        created = TimeUtils.utc_now() if USE_POSTGRES else TimeUtils.sql_iso()
        return await self.execute(
            sql, (user_id, provider, event_type, json.dumps(data), created)
        ) > 0

    async def activate_subscription_with_payment(
        self, user_id: int, invoice_number: str,
        payment_id: str, plan_id: int,
    ) -> bool:
        try:
            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    sql_plan = (
                        f"SELECT * FROM plans "
                        f"WHERE id = {_ph(1)} AND is_active = 1"
                    )
                    plan = await self._fetchone_with_conn(
                        conn, sql_plan, plan_id
                    )
                    if not plan:
                        logger.error(f"❌ الخطة {plan_id} غير موجودة")
                        return False

                    sql_inv = (
                        f"SELECT * FROM invoices "
                        f"WHERE number = {_ph(1)} AND user_id = {_ph(2)} "
                        f"AND status = 'pending'"
                    )
                    invoice = await self._fetchone_with_conn(
                        conn, sql_inv, invoice_number, user_id
                    )
                    if not invoice:
                        logger.error(
                            f"❌ Invoice not found/pending: {invoice_number}"
                        )
                        return False
                    if invoice['plan_id'] != plan_id:
                        logger.error(
                            f"❌ Plan mismatch: invoice "
                            f"{invoice['plan_id']} vs {plan_id}"
                        )
                        return False

                    sql_paid = (
                        f"UPDATE invoices SET status = 'paid', "
                        f"       provider_payment_id = {_ph(1)}, "
                        f"       paid_at = {_ph(2)} "
                        f"WHERE number = {_ph(3)}"
                    )
                    paid_at = (
                        TimeUtils.utc_now() if USE_POSTGRES
                        else TimeUtils.sql_iso()
                    )
                    await self._execute_with_conn(
                        conn, sql_paid, payment_id, paid_at, invoice_number
                    )

                    current_end = await self._get_current_end(conn, user_id)
                    now = TimeUtils.utc_now()
                    base = (
                        current_end if current_end and current_end > now
                        else now
                    )
                    new_end = base + timedelta(days=plan['duration_days'])

                    await self._insert_subscription_full(
                        conn, user_id, plan_id, new_end, 'xtr', payment_id
                    )
                    await self._refresh_user_subscription_end(conn, user_id)
                    await user_cache.invalidate(user_id)
                    return True
        except Exception as e:
            logger.error(
                f"❌ activate_subscription_with_payment: {e}",
                exc_info=True,
            )
            return False

    # =================================================================
    # إنشاء كود هدية
    # =================================================================
    async def create_gift_code(
        self, plan_id: int, creator_id: int
    ) -> Optional[str]:
        try:
            sql = (
                f"INSERT INTO gift_codes "
                f"(code, plan_id, creator_id, created_at) "
                f"VALUES ({_phs(4)})"
            )
            created = (
                TimeUtils.utc_now() if USE_POSTGRES
                else TimeUtils.sql_iso()
            )
            for _ in range(5):
                code = secrets.token_urlsafe(12)
                try:
                    async with self.transaction() as conn:
                        await self._execute_with_conn(
                            conn, sql, code, plan_id, creator_id, created
                        )
                    return code
                except Exception as e:
                    msg = str(e).lower()
                    if "unique" in msg or "duplicate" in msg:
                        continue
                    logger.error(
                        f"❌ create_gift_code (non-dup): {e}",
                        exc_info=True,
                    )
                    return None
            return None
        except Exception as e:
            logger.error(f"❌ create_gift_code: {e}", exc_info=True)
            return None

    # =================================================================
    # الإحالات
    # =================================================================
    async def add_referral(
        self, referrer_id: int, referred_id: int
    ) -> bool:
        """
        ✅ v7.7.29: نطاق زمني [day_start, day_end) بدل date(created_at).
        - يستفيد من index على created_at
        - متوافق مع asyncpg (لا اعتماد على implicit cast text→date)
        """
        if referrer_id == referred_id:
            return False
        try:
            async with await self._get_user_lock(referrer_id):
                async with self.transaction() as conn:
                    now = TimeUtils.utc_now()
                    day_start = now.replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    day_end = day_start + timedelta(days=1)

                    sql_cnt = (
                        f"SELECT COUNT(*) FROM referrals "
                        f"WHERE referrer_id = {_ph(1)} "
                        f"AND created_at >= {_ph(2)} "
                        f"AND created_at < {_ph(3)}"
                    )
                    count = await self._fetchval_with_conn(
                        conn, sql_cnt,
                        referrer_id, day_start, day_end,
                        default=0,
                    )

                    max_ref = getattr(CONFIG, 'MAX_DAILY_REFERRALS', 10)
                    if count >= max_ref:
                        logger.warning(
                            f"⚠️ User {referrer_id} reached daily limit"
                        )
                        return False

                    if USE_POSTGRES:
                        sql_ins = (
                            "INSERT INTO referrals "
                            "(referrer_id, referred_id, created_at) "
                            "VALUES ($1, $2, $3) "
                            "ON CONFLICT (referrer_id, referred_id) "
                            "DO NOTHING"
                        )
                        ins_val = TimeUtils.utc_now()
                    elif USE_MYSQL:
                        sql_ins = (
                            "INSERT IGNORE INTO referrals "
                            "(referrer_id, referred_id, created_at) "
                            "VALUES (%s, %s, %s)"
                        )
                        ins_val = TimeUtils.sql_iso()
                    else:
                        sql_ins = (
                            "INSERT OR IGNORE INTO referrals "
                            "(referrer_id, referred_id, created_at) "
                            "VALUES (?, ?, ?)"
                        )
                        ins_val = TimeUtils.sql_iso()

                    inserted = await self._execute_with_conn(
                        conn, sql_ins, referrer_id, referred_id, ins_val
                    )

                    if inserted > 0:
                        await self._upsert_referral_reward(
                            conn, referrer_id
                        )
                        await self._upsert_user_points(conn, referrer_id, 5)
                        return True
                    return False
        except Exception as e:
            logger.error(f"❌ add_referral: {e}", exc_info=True)
            return False

    async def get_referral_stats(self, user_id: int) -> Dict:
        try:
            async with self.connection() as conn:
                await self._ensure_referral_reward_row(conn, user_id)

                sql_total = (
                    f"SELECT COUNT(*) FROM referrals "
                    f"WHERE referrer_id = {_ph(1)}"
                )
                total = await self._fetchval_with_conn(
                    conn, sql_total, user_id, default=0
                )

                reward = await self._read_referral_reward(conn, user_id)
                total_reward = reward['total_reward'] if reward else 0
                claimed = reward['claimed'] if reward else 0

            return {
                'total': total,
                'claimed': claimed,
                'available': max(0, total_reward - claimed),
            }
        except Exception as e:
            logger.error(f"❌ get_referral_stats: {e}", exc_info=True)
            return {'total': 0, 'claimed': 0, 'available': 0}

    async def claim_referral_reward(self, user_id: int) -> int:
        try:
            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    await self._ensure_referral_reward_row(conn, user_id)
                    reward = await self._read_referral_reward(conn, user_id)

                    if not reward:
                        return 0
                    total_reward = reward['total_reward'] or 0
                    claimed = reward['claimed'] or 0
                    available = max(0, total_reward - claimed)
                    if available <= 0:
                        return 0

                    if USE_POSTGRES:
                        sql_plan = (
                            "SELECT s.plan_id FROM subscriptions s "
                            "JOIN plans p ON s.plan_id = p.id "
                            "WHERE s.user_id = $1 AND s.status = 'active' "
                            "AND s.end_date > $2 "
                            "ORDER BY p.max_channels DESC, "
                            "         p.max_posts DESC, "
                            "         s.end_date DESC LIMIT 1"
                        )
                        end_param = TimeUtils.utc_now()
                    elif USE_MYSQL:
                        sql_plan = (
                            "SELECT s.plan_id FROM subscriptions s "
                            "JOIN plans p ON s.plan_id = p.id "
                            "WHERE s.user_id = %s AND s.status = 'active' "
                            "AND s.end_date > %s "
                            "ORDER BY p.max_channels DESC, "
                            "         p.max_posts DESC, "
                            "         s.end_date DESC LIMIT 1"
                        )
                        end_param = TimeUtils.sql_iso()
                    else:
                        sql_plan = (
                            "SELECT s.plan_id FROM subscriptions s "
                            "JOIN plans p ON s.plan_id = p.id "
                            "WHERE s.user_id = ? AND s.status = 'active' "
                            "AND s.end_date > ? "
                            "ORDER BY p.max_channels DESC, "
                            "         p.max_posts DESC, "
                            "         s.end_date DESC LIMIT 1"
                        )
                        end_param = TimeUtils.sql_iso()

                    plan_id = await self._fetchval_with_conn(
                        conn, sql_plan, user_id, end_param
                    )

                    if not plan_id:
                        plan_id = await self._fetchval_with_conn(
                            conn,
                            "SELECT id FROM plans WHERE is_gift = 1 "
                            "AND is_active = 1 "
                            "ORDER BY max_channels DESC LIMIT 1",
                        )
                        if not plan_id:
                            plan_id = await self._fetchval_with_conn(
                                conn,
                                "SELECT id FROM plans WHERE name = 'شهر' "
                                "AND is_active = 1 LIMIT 1",
                            )
                            if not plan_id:
                                logger.warning(
                                    f"⚠️ لا توجد خطة نشطة للمستخدم {user_id}"
                                )
                                return 0

                    sql_upd = (
                        f"UPDATE referral_rewards "
                        f"SET claimed_reward_days = claimed_reward_days "
                        f"  + {_ph(1)} WHERE user_id = {_ph(2)}"
                    )
                    await self._execute_with_conn(
                        conn, sql_upd, available, user_id
                    )

                    current_end = await self._get_current_end(conn, user_id)
                    now = TimeUtils.utc_now()
                    base = (
                        current_end if current_end and current_end > now
                        else now
                    )
                    new_end = base + timedelta(days=available)

                    await self._insert_subscription_simple(
                        conn, user_id, plan_id, new_end, 'referral'
                    )
                    await self._refresh_user_subscription_end(conn, user_id)
                    await user_cache.invalidate(user_id)
                    return available
        except Exception as e:
            logger.error(
                f"❌ claim_referral_reward: {e}", exc_info=True
            )
            return 0

    async def get_referrals_list(self, user_id: int) -> List[int]:
        sql = (
            f"SELECT referred_id FROM referrals "
            f"WHERE referrer_id = {_ph(1)} ORDER BY created_at DESC"
        )
        referrals = await self.fetchall(sql, (user_id,))
        return [ref['referred_id'] for ref in referrals]

    # =================================================================
    # التذكيرات
    # =================================================================
    async def get_users_for_reminder(self) -> List[Dict]:
        """
        ✅ v7.7.29: HAVING يكرر التعبير بدل استخدام alias —
        PostgreSQL لا يسمح بـ SELECT aliases في HAVING
        (كان الاستعلام يفشل بالكامل على PG قبل هذا الإصلاح).
        """
        now = TimeUtils.utc_now()
        if USE_POSTGRES:
            return await self.fetchall(
                """SELECT u.user_id, u.language, r.reminder_days_before,
                          EXTRACT(DAY FROM (MAX(s.end_date) - $1))
                              AS days_left,
                          r.last_reminder_sent
                   FROM users u
                   JOIN user_reminder_settings r ON u.user_id = r.user_id
                   JOIN subscriptions s ON u.user_id = s.user_id
                        AND s.status = 'active' AND s.end_date > $2
                   WHERE r.subscription_reminder = 1
                   GROUP BY u.user_id, u.language,
                            r.reminder_days_before, r.last_reminder_sent
                   HAVING EXTRACT(DAY FROM (MAX(s.end_date) - $1))
                              <= r.reminder_days_before
                      AND EXTRACT(DAY FROM (MAX(s.end_date) - $1)) > 0
                      AND (r.last_reminder_sent IS NULL
                           OR EXTRACT(DAY FROM
                                ($3 - r.last_reminder_sent)) >= 1)""",
                (now, now, now),
            )
        elif USE_MYSQL:
            now_str = now.strftime('%Y-%m-%d %H:%M:%S')
            return await self.fetchall(
                """SELECT u.user_id, u.language, r.reminder_days_before,
                          TIMESTAMPDIFF(DAY, %s, MAX(s.end_date))
                              AS days_left,
                          r.last_reminder_sent
                   FROM users u
                   JOIN user_reminder_settings r ON u.user_id = r.user_id
                   JOIN subscriptions s ON u.user_id = s.user_id
                        AND s.status = 'active' AND s.end_date > %s
                   WHERE r.subscription_reminder = 1
                   GROUP BY u.user_id, u.language,
                            r.reminder_days_before, r.last_reminder_sent
                   HAVING TIMESTAMPDIFF(DAY, %s, MAX(s.end_date))
                              <= r.reminder_days_before
                      AND TIMESTAMPDIFF(DAY, %s, MAX(s.end_date)) > 0
                      AND (r.last_reminder_sent IS NULL
                           OR TIMESTAMPDIFF(DAY,
                                r.last_reminder_sent, %s) >= 1)""",
                (now_str, now_str, now_str, now_str, now_str),
            )
        else:
            now_str = now.strftime('%Y-%m-%d %H:%M:%S')
            return await self.fetchall(
                """SELECT u.user_id, u.language, r.reminder_days_before,
                          CAST(julianday(MAX(s.end_date))
                               - julianday(?) AS INTEGER) AS days_left,
                          r.last_reminder_sent
                   FROM users u
                   JOIN user_reminder_settings r ON u.user_id = r.user_id
                   JOIN subscriptions s ON u.user_id = s.user_id
                        AND s.status = 'active' AND s.end_date > ?
                   WHERE r.subscription_reminder = 1
                   GROUP BY u.user_id, u.language,
                            r.reminder_days_before, r.last_reminder_sent
                   HAVING CAST(julianday(MAX(s.end_date))
                               - julianday(?) AS INTEGER)
                              <= r.reminder_days_before
                      AND CAST(julianday(MAX(s.end_date))
                               - julianday(?) AS INTEGER) > 0
                      AND (r.last_reminder_sent IS NULL
                           OR julianday(?) - julianday(r.last_reminder_sent)
                              >= 1)""",
                (now_str, now_str, now_str, now_str, now_str),
            )

    async def update_reminder_sent(self, user_id: int) -> bool:
        sql = (
            f"UPDATE user_reminder_settings "
            f"SET last_reminder_sent = {_ph(1)} WHERE user_id = {_ph(2)}"
        )
        sent_at = TimeUtils.utc_now() if USE_POSTGRES else TimeUtils.sql_iso()
        return await self.execute(sql, (sent_at, user_id)) > 0


# =====================================================================
# Aliases
# =====================================================================
SubscriptionsMixin = SubscriptionMixin


__all__ = [
    "SubscriptionMixin", "SubscriptionsMixin", "TimeUtils",
    "USE_POSTGRES", "USE_MYSQL", "PATHS", "CONFIG",
    "user_cache", "_table_exists", "_ph", "_phs",
]