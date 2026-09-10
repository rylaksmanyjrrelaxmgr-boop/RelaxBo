#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_stats.py - دوال الإحصائيات والمشرفين (v7.4.3)
================================================================================
StatsMixin:
  - get_bot_stats      : إحصائيات البوت الأساسية
  - get_general_stats  : إحصائيات عامة شاملة
  - get_user_stats     : إحصائيات المستخدمين
  - add_admin          : إضافة مشرف
  - remove_admin       : إزالة مشرف
  - get_admin_list     : قائمة المشرفين

📌 مطابق 100% للسلوك الأصلي في database.py (بدون أي إضافة أو تعديل)

📌 يفترض أن الـ Database يوفّر:
  - self.connection()
  - self._fetchval_with_conn / self._execute_with_conn
  - self.fetchall / self.fetchval / self.execute
  - self.TimeUtils
  - self.CACHE_AVAILABLE
  - self.auth_cache
================================================================================
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class StatsMixin:
    """Mixin يحتوي كل دوال الإحصائيات والمشرفين"""

    # =====================================================================
    # 1) إحصائيات البوت الأساسية
    # =====================================================================

    async def get_bot_stats(self) -> Dict:
        async with self.connection() as conn:
            users = await self._fetchval_with_conn(conn, "SELECT COUNT(*) FROM users", default=0)
            channels = await self._fetchval_with_conn(conn, "SELECT COUNT(*) FROM user_channels", default=0)
            groups = await self._fetchval_with_conn(conn, "SELECT COUNT(*) FROM bot_groups", default=0)
            posts = await self._fetchval_with_conn(conn, "SELECT COUNT(*) FROM posts", default=0)
            published = await self._fetchval_with_conn(conn, "SELECT COUNT(*) FROM posts WHERE published = 1", default=0)
            active_subs = await self._fetchval_with_conn(
                conn, "SELECT COUNT(*) FROM subscriptions WHERE status = 'active' AND end_date > ?",
                self.TimeUtils.utc_now(), default=0,
            )
            tickets = await self._fetchval_with_conn(
                conn, "SELECT COUNT(*) FROM support_tickets WHERE status = 'pending'", default=0
            )
        return {
            "users": users, "channels": channels, "groups": groups,
            "posts": posts, "published": published,
            "active_subs": active_subs, "tickets": tickets,
        }

    # =====================================================================
    # 2) إحصائيات عامة شاملة
    # =====================================================================

    async def get_general_stats(self) -> Dict:
        async with self.connection() as conn:
            users = await self._fetchval_with_conn(conn, "SELECT COUNT(*) FROM users", default=0)
            channels = await self._fetchval_with_conn(conn, "SELECT COUNT(*) FROM user_channels", default=0)
            groups = await self._fetchval_with_conn(conn, "SELECT COUNT(*) FROM bot_groups", default=0)
            posts = await self._fetchval_with_conn(conn, "SELECT COUNT(*) FROM posts", default=0)
            published = await self._fetchval_with_conn(conn, "SELECT COUNT(*) FROM posts WHERE published = 1", default=0)
            active_subs = await self._fetchval_with_conn(
                conn, "SELECT COUNT(*) FROM subscriptions WHERE status = 'active' AND end_date > ?",
                self.TimeUtils.utc_now(), default=0,
            )
            tickets = await self._fetchval_with_conn(
                conn, "SELECT COUNT(*) FROM support_tickets WHERE status = 'pending'", default=0
            )
            invoices = await self._fetchval_with_conn(conn, "SELECT COUNT(*) FROM invoices", default=0)
            active_penalties = await self._fetchval_with_conn(
                conn, "SELECT COUNT(*) FROM user_penalties WHERE status='active'", default=0
            )
        return {
            "users": users, "channels": channels, "groups": groups,
            "posts": posts, "published": published,
            "active_subs": active_subs, "tickets": tickets,
            "invoices": invoices, "active_penalties": active_penalties,
        }

    # =====================================================================
    # 3) إحصائيات المستخدمين
    # =====================================================================

    async def get_user_stats(self) -> Dict:
        total = await self.fetchval("SELECT COUNT(*) FROM users", default=0)
        banned = await self.fetchval("SELECT COUNT(*) FROM users WHERE banned = 1", default=0)
        return {"users": total, "banned": banned}

    # =====================================================================
    # 4) إضافة مشرف
    # =====================================================================

    async def add_admin(self, admin_id: int, added_by: int) -> bool:
        result = await self.execute(
            "INSERT OR IGNORE INTO bot_admins (user_id, added_by, added_at) VALUES (?,?,?)",
            (admin_id, added_by, self.TimeUtils.utc_now()),
        ) > 0
        if result and self.CACHE_AVAILABLE:
            await self.auth_cache.invalidate()
        return result

    # =====================================================================
    # 5) إزالة مشرف
    # =====================================================================

    async def remove_admin(self, admin_id: int) -> bool:
        try:
            async with self.connection() as conn:
                deleted = await self._execute_with_conn(conn, "DELETE FROM bot_admins WHERE user_id = ?", admin_id)
                if deleted > 0 and self.CACHE_AVAILABLE:
                    await self.auth_cache.invalidate()
                return deleted > 0
        except Exception as e:
            logger.error(f"❌ Error in remove_admin: {e}", exc_info=True)
            return False

    # =====================================================================
    # 6) قائمة المشرفين
    # =====================================================================

    async def get_admin_list(self) -> List[Dict]:
        if self.CACHE_AVAILABLE:
            cached = await self.auth_cache.get_admin_list(0)
            if cached is not None:
                return cached
        admins = await self.fetchall("SELECT user_id, added_by, added_at FROM bot_admins ORDER BY added_at DESC")
        if self.CACHE_AVAILABLE:
            await self.auth_cache.set_admin_list(0, [a["user_id"] for a in admins])
        return admins