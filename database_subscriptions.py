#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
database_subscriptions.py - وحدة إدارة الباقات والاشتراكات والفواتير والإحالات (v7.5.3)
================================================================================
🆕 v7.5.3:
    ✅ SubscriptionsMixin alias — database.py يستورد الاسم بالجمع
       (كان subscription.py يعرّف SubscriptionMixin فقط → ImportError
        → Database لا يرث أي دالة اشتراك → كل الدوال تُفشل بـAttributeError
        باستثناء has_active_subscription الذي له fallback في database.py)
    ✅ __all__ — يُصدِّر الاسمين معاً

📌 v7.5.2 (هذا هو الملف الأصلي الذي يعمل عندك):
    - جميع الاستعلامات مطابقة لـschema الفعلي (status/end_date)
    - جميع الدوال: has_active_subscription, activate_trial, redeem_gift_code,
      create_gift_code, mark_invoice_paid, claim_referral_reward,
      activate_subscription_with_payment, ...إلخ

📌 كل الدوال تعمل عبر `self` للوصول إلى:
    - self.connection / self.transaction
    - self._fetchone_with_conn / self._fetchall_with_conn
    - self._fetchval_with_conn / self._execute_with_conn
    - self.execute / self.fetchone / self.fetchall / self.fetchval
    - self._get_user_lock
================================================================================
"""

import asyncio
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any

from database_common import (
    TimeUtils,
    USE_POSTGRES,
    USE_MYSQL,
    PATHS,
    CONFIG,
    user_cache,
    _table_exists,
)

logger = logging.getLogger(__name__)


class SubscriptionMixin:
    """
    Mixin يجمع دوال الباقات والاشتراكات والفواتير والإحالات والتذكيرات.
    يُستخدم عبر الوراثة في فئة Database.
    """

    # =====================================================================
    # دوال الاشتراك الأساسية
    # =====================================================================

    async def has_active_subscription(self, user_id: int) -> bool:
        result = await self.fetchval(
            "SELECT 1 FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > ? LIMIT 1",
            (user_id, TimeUtils.utc_now())
        )
        return result is not None

    async def has_used_trial(self, user_id: int) -> bool:
        result = await self.fetchval(
            "SELECT trial_used FROM users WHERE user_id = ?",
            (user_id,),
            default=0
        )
        return result == 1

    async def activate_trial(self, user_id: int) -> int:
        try:
            async with await self._get_user_lock(user_id):
                now = TimeUtils.utc_now()
                trial_end = now + timedelta(days=30)
                async with self.transaction() as conn:
                    trial_plan_id = await self._fetchval_with_conn(
                        conn,
                        "SELECT id FROM plans WHERE name = 'تجربة' AND is_active = 1 LIMIT 1",
                        default=1
                    )
                    current_end = await self._fetchval_with_conn(
                        conn,
                        "SELECT MAX(end_date) FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > ?",
                        user_id, TimeUtils.utc_now()
                    )
                    current_end_dt = TimeUtils.safe_parse_iso(current_end) if current_end else None
                    if current_end_dt and current_end_dt > trial_end:
                        days_granted = 0
                        new_end = current_end_dt
                    else:
                        days_granted = 30
                        new_end = trial_end

                    if USE_POSTGRES:
                        await self._execute_with_conn(
                            conn,
                            "UPDATE users SET trial_used = 1, updated_at = $1 WHERE user_id = $2",
                            TimeUtils.utc_now(), user_id
                        )
                    else:
                        await self._execute_with_conn(
                            conn,
                            "UPDATE users SET trial_used = 1, updated_at = ? WHERE user_id = ?",
                            TimeUtils.sql_iso(), user_id
                        )

                    if days_granted > 0:
                        if USE_POSTGRES:
                            await self._execute_with_conn(
                                conn,
                                "UPDATE users SET subscription_end = $1 WHERE user_id = $2",
                                new_end, user_id
                            )
                            await self._execute_with_conn(
                                conn,
                                """INSERT INTO subscriptions 
                                   (user_id, plan_id, status, start_date, end_date, provider, created_at, updated_at)
                                   VALUES ($1, $2, 'active', $3, $4, 'trial', $5, $6)""",
                                user_id, trial_plan_id, TimeUtils.utc_now(), new_end,
                                TimeUtils.utc_now(), TimeUtils.utc_now()
                            )
                            await self._refresh_user_subscription_end(conn, user_id)
                        else:
                            await self._execute_with_conn(
                                conn,
                                "UPDATE users SET subscription_end = ? WHERE user_id = ?",
                                new_end.strftime('%Y-%m-%d %H:%M:%S'), user_id
                            )
                            await self._execute_with_conn(
                                conn,
                                """INSERT INTO subscriptions 
                                   (user_id, plan_id, status, start_date, end_date, provider, created_at, updated_at)
                                   VALUES (?,?,?,?,?,?,?,?)""",
                                user_id, trial_plan_id, 'active', TimeUtils.sql_iso(),
                                new_end.strftime('%Y-%m-%d %H:%M:%S'), 'trial',
                                TimeUtils.sql_iso(), TimeUtils.sql_iso()
                            )
                            await self._refresh_user_subscription_end(conn, user_id)
                    else:
                        if USE_POSTGRES:
                            await self._execute_with_conn(
                                conn,
                                "UPDATE users SET subscription_end = $1 WHERE user_id = $2",
                                current_end_dt, user_id
                            )
                        else:
                            await self._execute_with_conn(
                                conn,
                                "UPDATE users SET subscription_end = ? WHERE user_id = ?",
                                current_end_dt.strftime('%Y-%m-%d %H:%M:%S'), user_id
                            )

                    await user_cache.invalidate(user_id)
                    return days_granted
        except Exception as e:
            logger.error(f"❌ Error in activate_trial: {e}", exc_info=True)
            return 0

    # =====================================================================
    # دوال الإحالة (كود الإحالة)
    # =====================================================================

    async def get_referral_code(self, user_id: int) -> str:
        result = await self.fetchval(
            "SELECT referral_code FROM users WHERE user_id = ?",
            (user_id,),
            default=f"ref_{user_id}"
        )
        return result if result else f"ref_{user_id}"

    async def get_user_by_referral_code(self, code: str) -> Optional[int]:
        return await self.fetchval(
            "SELECT user_id FROM users WHERE referral_code = ?",
            (code,)
        )

    # =====================================================================
    # دوال الاشتراك النشط
    # =====================================================================

    async def get_active_subscription(self, user_id: int) -> Optional[Dict]:
        return await self.fetchone(
            """SELECT s.*, p.name, p.duration_days, p.max_channels, p.max_posts, p.features
               FROM subscriptions s
               JOIN plans p ON s.plan_id = p.id AND p.is_active = 1
               WHERE s.user_id = ? AND s.status = 'active' AND s.end_date > ?
               ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC
               LIMIT 1""",
            (user_id, TimeUtils.utc_now())
        )

    async def get_active_plan(self, user_id: int) -> Optional[Dict]:
        sub = await self.get_active_subscription(user_id)
        if sub:
            return await self.get_plan(sub['plan_id'])
        return None

    async def get_subscription_end(self, user_id: int) -> Optional[datetime]:
        result = await self.fetchval(
            "SELECT subscription_end FROM users WHERE user_id = ?",
            (user_id,)
        )
        return TimeUtils.safe_parse_iso(result) if result else None

    # =====================================================================
    # دوال الباقات (Plans)
    # =====================================================================

    async def get_plan(self, plan_id: int) -> Optional[Dict]:
        return await self.fetchone(
            "SELECT * FROM plans WHERE id = ? AND is_active = 1",
            (plan_id,)
        )

    async def get_plan_by_name(self, name: str) -> Optional[Dict]:
        return await self.fetchone(
            "SELECT * FROM plans WHERE name = ? AND is_active = 1 LIMIT 1",
            (name,)
        )

    async def get_all_plans(self) -> List[Dict]:
        return await self.fetchall(
            "SELECT * FROM plans WHERE is_active = 1 AND is_gift = 0 ORDER BY price"
        )

    async def get_gift_plans(self) -> List[Dict]:
        return await self.fetchall(
            "SELECT id, name, description, price, duration_days AS days FROM plans WHERE is_active = 1 AND is_gift = 1 ORDER BY price"
        )

    async def get_gift_plan(self, plan_id: int) -> Optional[Dict]:
        return await self.fetchone(
            "SELECT id, name, description, price, duration_days AS days FROM plans WHERE id = ? AND is_gift = 1 AND is_active = 1",
            (plan_id,)
        )

    # =====================================================================
    # استرداد كودات الهدايا
    # =====================================================================

    async def redeem_gift_code(self, user_id: int, code: str) -> tuple:
        try:
            code = code.strip()
            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    gift_code = await self._fetchone_with_conn(
                        conn, "SELECT * FROM gift_codes WHERE code = ?", code
                    )
                    if not gift_code:
                        return False, 0
                    if gift_code['used_by']:
                        return False, 0
                    if gift_code['creator_id'] == user_id:
                        return False, -1

                    plan = await self._fetchone_with_conn(
                        conn,
                        "SELECT id, name, description, price, duration_days AS days FROM plans WHERE id = ? AND is_gift = 1 AND is_active = 1",
                        gift_code['plan_id']
                    )
                    if not plan:
                        return False, 0

                    await self._execute_with_conn(
                        conn,
                        "UPDATE gift_codes SET used_by = ?, used_at = ? WHERE id = ?",
                        user_id, TimeUtils.utc_now(), gift_code['id']
                    )

                    if USE_POSTGRES:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > ?",
                            user_id, TimeUtils.utc_now()
                        )
                    elif USE_MYSQL:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = %s AND status = 'active' AND end_date > %s",
                            user_id, TimeUtils.sql_iso()
                        )
                    else:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > ?",
                            user_id, TimeUtils.sql_iso()
                        )

                    current_end = TimeUtils.safe_parse_iso(current_end) if current_end else None
                    now = TimeUtils.utc_now()
                    base = current_end if current_end and current_end > now else now
                    new_end = base + timedelta(days=plan['days'])

                    if USE_POSTGRES:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date, provider, created_at, updated_at) VALUES ($1, $2, 'active', $3, $4, 'gift', $5, $6)",
                            user_id, gift_code['plan_id'], TimeUtils.utc_now(), new_end,
                            TimeUtils.utc_now(), TimeUtils.utc_now()
                        )
                    else:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date, provider, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                            user_id, gift_code['plan_id'], 'active', TimeUtils.sql_iso(),
                            new_end.strftime('%Y-%m-%d %H:%M:%S'), 'gift',
                            TimeUtils.sql_iso(), TimeUtils.sql_iso()
                        )

                    await self._refresh_user_subscription_end(conn, user_id)
                    await user_cache.invalidate(user_id)
                    return True, plan['days']
        except Exception as e:
            logger.error(f"❌ Error in redeem_gift_code: {e}", exc_info=True)
            return False, 0

    # =====================================================================
    # منح اشتراك يدوي
    # =====================================================================

    async def grant_subscription_days(self, user_id: int, days: int, plan_id: int = None, provider: str = 'manual') -> bool:
        try:
            if days <= 0:
                return False
            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    exists = await self._fetchval_with_conn(
                        conn, "SELECT 1 FROM users WHERE user_id = ?", user_id
                    )
                    if not exists:
                        return False

                    if not plan_id:
                        if USE_POSTGRES:
                            plan_id = await self._fetchval_with_conn(
                                conn, "SELECT id FROM plans WHERE is_gift = 1 AND is_active = 1 ORDER BY max_channels DESC LIMIT 1"
                            )
                        elif USE_MYSQL:
                            plan_id = await self._fetchval_with_conn(
                                conn, "SELECT id FROM plans WHERE is_gift = 1 AND is_active = 1 ORDER BY max_channels DESC LIMIT 1"
                            )
                        else:
                            plan_id = await self._fetchval_with_conn(
                                conn, "SELECT id FROM plans WHERE is_gift = 1 AND is_active = 1 ORDER BY max_channels DESC LIMIT 1"
                            )

                        if not plan_id:
                            if USE_POSTGRES:
                                plan_id = await self._fetchval_with_conn(
                                    conn, "SELECT id FROM plans WHERE name = 'شهر' AND is_active = 1 LIMIT 1"
                                )
                            elif USE_MYSQL:
                                plan_id = await self._fetchval_with_conn(
                                    conn, "SELECT id FROM plans WHERE name = 'شهر' AND is_active = 1 LIMIT 1"
                                )
                            else:
                                plan_id = await self._fetchval_with_conn(
                                    conn, "SELECT id FROM plans WHERE name = 'شهر' AND is_active = 1 LIMIT 1"
                                )
                            if not plan_id:
                                return False

                    if USE_POSTGRES:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > ?",
                            user_id, TimeUtils.utc_now()
                        )
                    elif USE_MYSQL:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = %s AND status = 'active' AND end_date > %s",
                            user_id, TimeUtils.sql_iso()
                        )
                    else:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > ?",
                            user_id, TimeUtils.sql_iso()
                        )

                    current_end = TimeUtils.safe_parse_iso(current_end) if current_end else None
                    now = TimeUtils.utc_now()
                    base = current_end if current_end and current_end > now else now
                    new_end = base + timedelta(days=days)

                    if USE_POSTGRES:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date, provider, created_at, updated_at) VALUES ($1, $2, 'active', $3, $4, $5, $6, $7)",
                            user_id, plan_id, TimeUtils.utc_now(), new_end,
                            provider, TimeUtils.utc_now(), TimeUtils.utc_now()
                        )
                    else:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date, provider, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                            user_id, plan_id, 'active', TimeUtils.sql_iso(),
                            new_end.strftime('%Y-%m-%d %H:%M:%S'), provider,
                            TimeUtils.sql_iso(), TimeUtils.sql_iso()
                        )

                    await self._refresh_user_subscription_end(conn, user_id)
                    await user_cache.invalidate(user_id)
                    return True
        except Exception as e:
            logger.error(f"❌ Error in grant_subscription_days: {e}", exc_info=True)
            return False

    # =====================================================================
    # إنشاء اشتراك (يدوي)
    # =====================================================================

    async def create_subscription(self, user_id: int, plan_id: int, provider: str = 'xtr', provider_sub_id: str = None) -> int:
        try:
            plan = await self.get_plan(plan_id)
            if not plan:
                return 0

            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    if USE_POSTGRES:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > ?",
                            user_id, TimeUtils.utc_now()
                        )
                    elif USE_MYSQL:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = %s AND status = 'active' AND end_date > %s",
                            user_id, TimeUtils.sql_iso()
                        )
                    else:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > ?",
                            user_id, TimeUtils.sql_iso()
                        )

                    current_end = TimeUtils.safe_parse_iso(current_end) if current_end else None
                    now = TimeUtils.utc_now()
                    base = current_end if current_end and current_end > now else now
                    new_end = base + timedelta(days=plan['duration_days'])

                    if USE_POSTGRES:
                        row = await self._fetchone_with_conn(
                            conn,
                            "INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date, auto_renew, provider, provider_subscription_id, created_at, updated_at) VALUES ($1, $2, 'active', $3, $4, 0, $5, $6, $7, $7) RETURNING id",
                            user_id, plan_id, TimeUtils.utc_now(), new_end,
                            provider, provider_sub_id, TimeUtils.utc_now()
                        )
                        sub_id = row['id'] if row else 0
                        await self._execute_with_conn(
                            conn, "UPDATE users SET updated_at = $1 WHERE user_id = $2",
                            TimeUtils.utc_now(), user_id
                        )
                        await self._refresh_user_subscription_end(conn, user_id)
                        await user_cache.invalidate(user_id)
                        return sub_id
                    elif USE_MYSQL:
                        cursor = await conn.cursor()
                        await cursor.execute(
                            "INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date, auto_renew, provider, provider_subscription_id, created_at, updated_at) VALUES (%s, %s, 'active', %s, %s, 0, %s, %s, %s, %s)",
                            (user_id, plan_id, TimeUtils.sql_iso(),
                             new_end.strftime('%Y-%m-%d %H:%M:%S'), provider,
                             provider_sub_id, TimeUtils.sql_iso(), TimeUtils.sql_iso())
                        )
                        sub_id = cursor.lastrowid
                        await self._execute_with_conn(
                            conn, "UPDATE users SET updated_at = %s WHERE user_id = %s",
                            TimeUtils.sql_iso(), user_id
                        )
                        await self._refresh_user_subscription_end(conn, user_id)
                        await user_cache.invalidate(user_id)
                        return sub_id
                    else:
                        cursor = await conn.execute(
                            "INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date, auto_renew, provider, provider_subscription_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (user_id, plan_id, 'active', TimeUtils.sql_iso(),
                             new_end.strftime('%Y-%m-%d %H:%M:%S'), 0, provider,
                             provider_sub_id, TimeUtils.sql_iso(), TimeUtils.sql_iso())
                        )
                        sub_id = cursor.lastrowid if cursor.lastrowid else 0
                        await self._execute_with_conn(
                            conn, "UPDATE users SET updated_at = ? WHERE user_id = ?",
                            TimeUtils.sql_iso(), user_id
                        )
                        await self._refresh_user_subscription_end(conn, user_id)
                        await user_cache.invalidate(user_id)
                        return sub_id
        except Exception as e:
            logger.error(f"❌ Error in create_subscription: {e}", exc_info=True)
            return 0

    # =====================================================================
    # انتهاء الاشتراكات وتحديث نهايتها
    # =====================================================================

    async def expire_expired_subscriptions(self) -> None:
        try:
            async with self.transaction() as conn:
                if USE_POSTGRES:
                    await conn.execute(
                        "UPDATE subscriptions SET status = 'expired' WHERE status = 'active' AND end_date <= CURRENT_TIMESTAMP AT TIME ZONE 'UTC'"
                    )
                elif USE_MYSQL:
                    await conn.execute(
                        "UPDATE subscriptions SET status = 'expired' WHERE status = 'active' AND end_date <= UTC_TIMESTAMP()"
                    )
                else:
                    await conn.execute(
                        "UPDATE subscriptions SET status = 'expired' WHERE status = 'active' AND end_date <= datetime('now')"
                    )
                users = await self._fetchall_with_conn(
                    conn, "SELECT DISTINCT user_id FROM subscriptions WHERE status = 'expired'"
                )
                for user in users:
                    await self._refresh_user_subscription_end(conn, user['user_id'])
                    await user_cache.invalidate(user['user_id'])
        except Exception as e:
            logger.error(f"❌ Error in expire_expired_subscriptions: {e}", exc_info=True)

    async def _refresh_user_subscription_end(self, conn, user_id: int) -> None:
        if USE_POSTGRES:
            end = await self._fetchval_with_conn(
                conn,
                "SELECT MAX(end_date) FROM subscriptions WHERE user_id = $1 AND status = 'active' AND end_date > CURRENT_TIMESTAMP AT TIME ZONE 'UTC'",
                user_id
            )
            await self._execute_with_conn(
                conn,
                "UPDATE users SET subscription_end = $1, updated_at = $2 WHERE user_id = $3",
                end, TimeUtils.utc_now(), user_id
            )
        elif USE_MYSQL:
            end = await self._fetchval_with_conn(
                conn,
                "SELECT MAX(end_date) FROM subscriptions WHERE user_id = %s AND status = 'active' AND end_date > UTC_TIMESTAMP()",
                user_id
            )
            await self._execute_with_conn(
                conn,
                "UPDATE users SET subscription_end = %s, updated_at = %s WHERE user_id = %s",
                end, TimeUtils.sql_iso(), user_id
            )
        else:
            end = await self._fetchval_with_conn(
                conn,
                "SELECT MAX(end_date) FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > datetime('now')",
                user_id
            )
            await self._execute_with_conn(
                conn,
                "UPDATE users SET subscription_end = ?, updated_at = ? WHERE user_id = ?",
                end, TimeUtils.sql_iso(), user_id
            )

    # =====================================================================
    # الفواتير
    # =====================================================================

    async def create_invoice(self, user_id: int, plan_id: int, amount: int, currency: str = 'XTR', provider: str = 'xtr') -> str:
        number = f"INV-{TimeUtils.utc_now().strftime('%Y%m')}-{secrets.token_urlsafe(12).upper()}"
        result = await self.execute(
            "INSERT INTO invoices (number, user_id, plan_id, amount, currency, status, provider, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (number, user_id, plan_id, amount, currency, 'pending', provider, TimeUtils.utc_now())
        )
        return number if result > 0 else ""

    async def mark_invoice_paid(self, invoice_number: str, payment_id: str) -> bool:
        return await self.execute(
            "UPDATE invoices SET status = 'paid', provider_payment_id = ?, paid_at = ? WHERE number = ?",
            (payment_id, TimeUtils.utc_now(), invoice_number)
        ) > 0

    async def get_invoice(self, number: str) -> Optional[Dict]:
        return await self.fetchone(
            "SELECT * FROM invoices WHERE number = ?", (number,)
        )

    async def get_user_invoices(self, user_id: int, limit: int = 20) -> List[Dict]:
        return await self.fetchall(
            "SELECT * FROM invoices WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        )

    # =====================================================================
    # سجلات الدفع
    # =====================================================================

    async def add_payment_log(self, user_id: int, provider: str, event_type: str, data: dict) -> bool:
        return await self.execute(
            "INSERT INTO payment_logs (user_id, provider, event_type, data, created_at) VALUES (?,?,?,?,?)",
            (user_id, provider, event_type, json.dumps(data), TimeUtils.utc_now())
        ) > 0

    async def activate_subscription_with_payment(self, user_id: int, invoice_number: str, payment_id: str, plan_id: int) -> bool:
        try:
            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    plan = await self._fetchone_with_conn(
                        conn,
                        "SELECT * FROM plans WHERE id = ? AND is_active = 1",
                        plan_id
                    )
                    if not plan:
                        logger.error(f"❌ الخطة {plan_id} غير موجودة أو غير نشطة")
                        return False

                    invoice = await self._fetchone_with_conn(
                        conn,
                        "SELECT * FROM invoices WHERE number = ? AND user_id = ? AND status = 'pending'",
                        invoice_number, user_id
                    )
                    if not invoice:
                        logger.error(f"❌ Invoice not found or not pending: {invoice_number}")
                        return False
                    if invoice['plan_id'] != plan_id:
                        logger.error(f"❌ Plan mismatch: invoice plan {invoice['plan_id']} vs {plan_id}")
                        return False

                    await self._execute_with_conn(
                        conn,
                        "UPDATE invoices SET status = 'paid', provider_payment_id = ?, paid_at = ? WHERE number = ?",
                        payment_id, TimeUtils.utc_now(), invoice_number
                    )

                    if USE_POSTGRES:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > ?",
                            user_id, TimeUtils.utc_now()
                        )
                    elif USE_MYSQL:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = %s AND status = 'active' AND end_date > %s",
                            user_id, TimeUtils.sql_iso()
                        )
                    else:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > ?",
                            user_id, TimeUtils.sql_iso()
                        )

                    current_end = TimeUtils.safe_parse_iso(current_end) if current_end else None
                    now = TimeUtils.utc_now()
                    base = current_end if current_end and current_end > now else now
                    new_end = base + timedelta(days=plan['duration_days'])

                    if USE_POSTGRES:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date, auto_renew, provider, provider_subscription_id, created_at, updated_at) VALUES ($1, $2, 'active', $3, $4, 0, $5, $6, $7, $7)",
                            user_id, plan_id, TimeUtils.utc_now(), new_end,
                            'xtr', payment_id, TimeUtils.utc_now()
                        )
                    else:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date, auto_renew, provider, provider_subscription_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            user_id, plan_id, 'active', TimeUtils.sql_iso(),
                            new_end.strftime('%Y-%m-%d %H:%M:%S'), 0, 'xtr',
                            payment_id, TimeUtils.sql_iso(), TimeUtils.sql_iso()
                        )

                    await self._refresh_user_subscription_end(conn, user_id)
                    await user_cache.invalidate(user_id)
                    return True
        except Exception as e:
            logger.error(f"❌ Error in activate_subscription_with_payment: {e}", exc_info=True)
            return False

    # =====================================================================
    # كود الهدية
    # =====================================================================

    async def create_gift_code(self, plan_id: int, creator_id: int) -> Optional[str]:
        try:
            async with self.connection() as conn:
                for _ in range(5):
                    code = secrets.token_urlsafe(12)
                    try:
                        if USE_POSTGRES:
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO gift_codes (code, plan_id, creator_id, created_at) VALUES ($1, $2, $3, $4)",
                                code, plan_id, creator_id, TimeUtils.utc_now()
                            )
                        elif USE_MYSQL:
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO gift_codes (code, plan_id, creator_id, created_at) VALUES (%s, %s, %s, %s)",
                                code, plan_id, creator_id, TimeUtils.sql_iso()
                            )
                        else:
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO gift_codes (code, plan_id, creator_id, created_at) VALUES (?,?,?,?)",
                                code, plan_id, creator_id, TimeUtils.sql_iso()
                            )
                        return code
                    except Exception as e:
                        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                            continue
                        raise
                return None
        except Exception as e:
            logger.error(f"❌ Error in create_gift_code: {e}", exc_info=True)
            return None

    # =====================================================================
    # الإحالات
    # =====================================================================

    async def add_referral(self, referrer_id: int, referred_id: int) -> bool:
        if referrer_id == referred_id:
            return False
        try:
            async with await self._get_user_lock(referrer_id):
                async with self.transaction() as conn:
                    today = TimeUtils.utc_now().strftime('%Y-%m-%d')
                    if USE_POSTGRES:
                        count = await self._fetchval_with_conn(
                            conn,
                            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND date(created_at) = ?",
                            referrer_id, today, default=0
                        )
                    elif USE_MYSQL:
                        count = await self._fetchval_with_conn(
                            conn,
                            "SELECT COUNT(*) FROM referrals WHERE referrer_id = %s AND DATE(created_at) = %s",
                            referrer_id, today, default=0
                        )
                    else:
                        count = await self._fetchval_with_conn(
                            conn,
                            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND date(created_at) = ?",
                            referrer_id, today, default=0
                        )

                    if count >= getattr(CONFIG, 'MAX_DAILY_REFERRALS', 10):
                        logger.warning(f"⚠️ User {referrer_id} reached daily referral limit")
                        return False

                    if USE_POSTGRES:
                        inserted = await self._execute_with_conn(
                            conn,
                            "INSERT INTO referrals (referrer_id, referred_id, created_at) VALUES ($1, $2, $3) ON CONFLICT (referrer_id, referred_id) DO NOTHING",
                            referrer_id, referred_id, TimeUtils.utc_now()
                        )
                    elif USE_MYSQL:
                        inserted = await self._execute_with_conn(
                            conn,
                            "INSERT IGNORE INTO referrals (referrer_id, referred_id, created_at) VALUES (%s, %s, %s)",
                            referrer_id, referred_id, TimeUtils.sql_iso()
                        )
                    else:
                        inserted = await self._execute_with_conn(
                            conn,
                            "INSERT OR IGNORE INTO referrals (referrer_id, referred_id, created_at) VALUES (?,?,?)",
                            referrer_id, referred_id, TimeUtils.sql_iso()
                        )

                    if inserted > 0:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days, last_referral_date) VALUES (?,1,3,0,?) ON CONFLICT(user_id) DO UPDATE SET referral_count = referral_count + 1, total_reward_days = total_reward_days + 3, last_referral_date = ?",
                            referrer_id, TimeUtils.utc_now(), TimeUtils.utc_now()
                        )
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO user_points (user_id, points, last_updated) VALUES (?,5,?) ON CONFLICT(user_id) DO UPDATE SET points = points + 5, last_updated = ?",
                            referrer_id, TimeUtils.utc_now(), TimeUtils.utc_now()
                        )
                        return True
                    return False
        except Exception as e:
            logger.error(f"❌ Error in add_referral: {e}", exc_info=True)
            return False

    async def get_referral_stats(self, user_id: int) -> Dict:
        try:
            async with self.connection() as conn:
                if USE_POSTGRES:
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days, last_referral_date) VALUES ($1, 0, 0, 0, NULL) ON CONFLICT DO NOTHING",
                        user_id
                    )
                elif USE_MYSQL:
                    await self._execute_with_conn(
                        conn,
                        "INSERT IGNORE INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days, last_referral_date) VALUES (%s, 0, 0, 0, NULL)",
                        user_id
                    )
                else:
                    await self._execute_with_conn(
                        conn,
                        "INSERT OR IGNORE INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days, last_referral_date) VALUES (?, 0, 0, 0, NULL)",
                        user_id
                    )

                total = await self._fetchval_with_conn(
                    conn,
                    "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?",
                    user_id, default=0
                )
                if USE_POSTGRES:
                    reward = await self._fetchone_with_conn(
                        conn,
                        "SELECT COALESCE(total_reward_days, 0) as total_reward, COALESCE(claimed_reward_days, 0) as claimed FROM referral_rewards WHERE user_id = ?",
                        user_id
                    )
                elif USE_MYSQL:
                    reward = await self._fetchone_with_conn(
                        conn,
                        "SELECT COALESCE(total_reward_days, 0) as total_reward, COALESCE(claimed_reward_days, 0) as claimed FROM referral_rewards WHERE user_id = %s",
                        user_id
                    )
                else:
                    reward = await self._fetchone_with_conn(
                        conn,
                        "SELECT COALESCE(total_reward_days, 0) as total_reward, COALESCE(claimed_reward_days, 0) as claimed FROM referral_rewards WHERE user_id = ?",
                        user_id
                    )

                total_reward = reward['total_reward'] if reward else 0
                claimed = reward['claimed'] if reward else 0
            return {'total': total, 'claimed': claimed, 'available': max(0, total_reward - claimed)}
        except Exception as e:
            logger.error(f"❌ Error in get_referral_stats: {e}", exc_info=True)
            return {'total': 0, 'claimed': 0, 'available': 0}

    async def claim_referral_reward(self, user_id: int) -> int:
        try:
            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    if USE_POSTGRES:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days, last_referral_date) VALUES ($1, 0, 0, 0, NULL) ON CONFLICT DO NOTHING",
                            user_id
                        )
                    elif USE_MYSQL:
                        await self._execute_with_conn(
                            conn,
                            "INSERT IGNORE INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days, last_referral_date) VALUES (%s, 0, 0, 0, NULL)",
                            user_id
                        )
                    else:
                        await self._execute_with_conn(
                            conn,
                            "INSERT OR IGNORE INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days, last_referral_date) VALUES (?, 0, 0, 0, NULL)",
                            user_id
                        )

                    if USE_POSTGRES:
                        reward = await self._fetchone_with_conn(
                            conn,
                            "SELECT COALESCE(total_reward_days, 0) as total_reward, COALESCE(claimed_reward_days, 0) as claimed FROM referral_rewards WHERE user_id = ?",
                            user_id
                        )
                    elif USE_MYSQL:
                        reward = await self._fetchone_with_conn(
                            conn,
                            "SELECT COALESCE(total_reward_days, 0) as total_reward, COALESCE(claimed_reward_days, 0) as claimed FROM referral_rewards WHERE user_id = %s",
                            user_id
                        )
                    else:
                        reward = await self._fetchone_with_conn(
                            conn,
                            "SELECT COALESCE(total_reward_days, 0) as total_reward, COALESCE(claimed_reward_days, 0) as claimed FROM referral_rewards WHERE user_id = ?",
                            user_id
                        )

                    if not reward:
                        return 0
                    total_reward = reward['total_reward'] or 0
                    claimed = reward['claimed'] or 0
                    available = max(0, total_reward - claimed)
                    if available <= 0:
                        return 0

                    if USE_POSTGRES:
                        plan_id = await self._fetchval_with_conn(
                            conn,
                            "SELECT s.plan_id FROM subscriptions s JOIN plans p ON s.plan_id = p.id WHERE s.user_id = ? AND s.status = 'active' AND s.end_date > ? ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1",
                            user_id, TimeUtils.utc_now()
                        )
                    elif USE_MYSQL:
                        plan_id = await self._fetchval_with_conn(
                            conn,
                            "SELECT s.plan_id FROM subscriptions s JOIN plans p ON s.plan_id = p.id WHERE s.user_id = %s AND s.status = 'active' AND s.end_date > %s ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1",
                            user_id, TimeUtils.sql_iso()
                        )
                    else:
                        plan_id = await self._fetchval_with_conn(
                            conn,
                            "SELECT s.plan_id FROM subscriptions s JOIN plans p ON s.plan_id = p.id WHERE s.user_id = ? AND s.status = 'active' AND s.end_date > ? ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1",
                            user_id, TimeUtils.sql_iso()
                        )

                    if not plan_id:
                        if USE_POSTGRES:
                            plan_id = await self._fetchval_with_conn(
                                conn, "SELECT id FROM plans WHERE is_gift = 1 AND is_active = 1 ORDER BY max_channels DESC LIMIT 1"
                            )
                        elif USE_MYSQL:
                            plan_id = await self._fetchval_with_conn(
                                conn, "SELECT id FROM plans WHERE is_gift = 1 AND is_active = 1 ORDER BY max_channels DESC LIMIT 1"
                            )
                        else:
                            plan_id = await self._fetchval_with_conn(
                                conn, "SELECT id FROM plans WHERE is_gift = 1 AND is_active = 1 ORDER BY max_channels DESC LIMIT 1"
                            )

                        if not plan_id:
                            if USE_POSTGRES:
                                plan_id = await self._fetchval_with_conn(
                                    conn, "SELECT id FROM plans WHERE name = 'شهر' AND is_active = 1 LIMIT 1"
                                )
                            elif USE_MYSQL:
                                plan_id = await self._fetchval_with_conn(
                                    conn, "SELECT id FROM plans WHERE name = 'شهر' AND is_active = 1 LIMIT 1"
                                )
                            else:
                                plan_id = await self._fetchval_with_conn(
                                    conn, "SELECT id FROM plans WHERE name = 'شهر' AND is_active = 1 LIMIT 1"
                                )
                            if not plan_id:
                                logger.warning(f"⚠️ لا توجد خطة نشطة للمستخدم {user_id} لصرف مكافأة الإحالة")
                                return 0

                    await self._execute_with_conn(
                        conn,
                        "UPDATE referral_rewards SET claimed_reward_days = claimed_reward_days + ? WHERE user_id = ?",
                        available, user_id
                    )

                    if USE_POSTGRES:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > ?",
                            user_id, TimeUtils.utc_now()
                        )
                    elif USE_MYSQL:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = %s AND status = 'active' AND end_date > %s",
                            user_id, TimeUtils.sql_iso()
                        )
                    else:
                        current_end = await self._fetchval_with_conn(
                            conn,
                            "SELECT MAX(end_date) FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > ?",
                            user_id, TimeUtils.sql_iso()
                        )

                    current_end = TimeUtils.safe_parse_iso(current_end) if current_end else None
                    now = TimeUtils.utc_now()
                    base = current_end if current_end and current_end > now else now
                    new_end = base + timedelta(days=available)

                    if USE_POSTGRES:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date, provider, created_at, updated_at) VALUES ($1, $2, 'active', $3, $4, 'referral', $5, $6)",
                            user_id, plan_id, TimeUtils.utc_now(), new_end,
                            TimeUtils.utc_now(), TimeUtils.utc_now()
                        )
                    else:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO subscriptions (user_id, plan_id, status, start_date, end_date, provider, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                            user_id, plan_id, 'active', TimeUtils.sql_iso(),
                            new_end.strftime('%Y-%m-%d %H:%M:%S'), 'referral',
                            TimeUtils.sql_iso(), TimeUtils.sql_iso()
                        )

                    await self._refresh_user_subscription_end(conn, user_id)
                    await user_cache.invalidate(user_id)
                    return available
        except Exception as e:
            logger.error(f"❌ Error in claim_referral_reward: {e}", exc_info=True)
            return 0

    async def get_referrals_list(self, user_id: int) -> List[int]:
        referrals = await self.fetchall(
            "SELECT referred_id FROM referrals WHERE referrer_id = ? ORDER BY created_at DESC",
            (user_id,)
        )
        return [ref['referred_id'] for ref in referrals]

    # =====================================================================
    # التذكيرات
    # =====================================================================

    async def get_users_for_reminder(self) -> List[Dict]:
        now = TimeUtils.utc_now()
        if USE_POSTGRES:
            return await self.fetchall(
                """SELECT u.user_id, u.language, r.reminder_days_before,
                          EXTRACT(DAY FROM (MAX(s.end_date) - $1)) as days_left,
                          r.last_reminder_sent
                   FROM users u
                   JOIN user_reminder_settings r ON u.user_id = r.user_id
                   JOIN subscriptions s ON u.user_id = s.user_id AND s.status = 'active' AND s.end_date > $2
                   WHERE r.subscription_reminder = 1
                   GROUP BY u.user_id, u.language, r.reminder_days_before, r.last_reminder_sent
                   HAVING days_left <= r.reminder_days_before
                      AND days_left > 0
                      AND (r.last_reminder_sent IS NULL OR EXTRACT(DAY FROM ($3 - r.last_reminder_sent)) >= 1)""",
                (now, now, now)
            )
        elif USE_MYSQL:
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
                (now.strftime('%Y-%m-%d %H:%M:%S'),
                 now.strftime('%Y-%m-%d %H:%M:%S'),
                 now.strftime('%Y-%m-%d %H:%M:%S'))
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
                (now.strftime('%Y-%m-%d %H:%M:%S'),
                 now.strftime('%Y-%m-%d %H:%M:%S'),
                 now.strftime('%Y-%m-%d %H:%M:%S'))
            )

    async def update_reminder_sent(self, user_id: int) -> bool:
        return await self.execute(
            "UPDATE user_reminder_settings SET last_reminder_sent = ? WHERE user_id = ?",
            (TimeUtils.utc_now(), user_id)
        ) > 0


# =====================================================================
# ✅ v7.5.3: Alias للتوافق مع database.py
# =====================================================================
# database.py يستورد:
#     from database_subscriptions import SubscriptionsMixin
# لكن هذا الملف يُعرِّف `SubscriptionMixin` (مفرد).
# الـalias التالي يُصلح الـImportError ويجعل Database يرث كل الدوال.
# =====================================================================

SubscriptionsMixin = SubscriptionMixin


__all__ = [
    "SubscriptionMixin",
    "SubscriptionsMixin",
]