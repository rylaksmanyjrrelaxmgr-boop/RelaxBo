#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_tickets.py - دوال التذاكر (v7.4.2)
================================================================================
🆕 v7.4.2 (إصلاح MySQL):
    ✅ create_ticket: backticks حول `key` و `value` لـ MySQL
       (كان يفشل على MySQL — كلمات محجوزة)
    ✅ معالجة آمنة لـ next_num (int/None/غائب)
    ✅ parameterized query بدل 'last_ticket_number' كـliteral

📌 v7.4.1:
    - create_ticket       : إنشاء تذكرة جديدة (مع ترقيم تلقائي)
    - get_tickets         : جلب كل التذاكر المعلّقة
    - close_ticket        : إغلاق تذكرة
    - delete_all_tickets  : حذف كل التذاكر

📌 مطابق تماماً للسلوك الأصلي في database.py
================================================================================
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class TicketsMixin:
    """Mixin يحتوي كل دوال التذاكر"""

    # =====================================================================
    # 0) ✅ v7.4.2: helper داخلي للتوافق مع MySQL
    # =====================================================================

    def _tq(self, col: str) -> str:
        """
        ✅ v7.4.2: يُرجع اسم العمود مع backticks لـ MySQL فقط.

        السبب: `key` و `value` كلمات محجوزة في MySQL.
        PostgreSQL/SQLite: لا يحتاجان backticks.
        """
        if getattr(self, "USE_MYSQL", False):
            return f"`{col}`"
        return col

    # =====================================================================
    # 1) إنشاء تذكرة جديدة
    # =====================================================================

    async def create_ticket(
        self,
        user_id: int,
        username: str,
        content: str,
        media_type: str = None,
        media_file_id: str = None,
    ) -> int:
        """ينشئ تذكرة جديدة بترقيم تلقائي. يُرجع رقم التذكرة أو 0 عند الفشل."""
        try:
            async with self._lock:
                async with self.transaction() as conn:
                    # ✅ v7.4.2: backticks لـ MySQL
                    key_col = self._tq("key")
                    value_col = self._tq("value")

                    # ✅ v7.4.2: parameterized query بدل 'last_ticket_number' literal
                    next_num_str = await self._fetchval_with_conn(
                        conn,
                        f"SELECT {value_col} FROM settings WHERE {key_col} = ?",
                        "last_ticket_number",
                        default="0",
                    )

                    # ✅ v7.4.2: معالجة آمنة (None / "" / نص غير رقمي)
                    try:
                        next_num = int(next_num_str) + 1
                        if next_num <= 0:
                            next_num = 1
                    except (ValueError, TypeError):
                        next_num = 1

                    await self._execute_with_conn(
                        conn,
                        f"UPDATE settings SET {value_col} = ? WHERE {key_col} = ?",
                        str(next_num), "last_ticket_number",
                    )
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO support_tickets "
                        "(user_id, username, message, media_type, media_file_id, ticket_number, created_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        user_id, username, content, media_type, media_file_id,
                        next_num, self.TimeUtils.utc_now(),
                    )
                return next_num
        except Exception as e:
            logger.error(f"❌ Error in create_ticket: {e}", exc_info=True)
            return 0

    # =====================================================================
    # 2) جلب كل التذاكر المعلّقة
    # =====================================================================

    async def get_tickets(self) -> List[Dict]:
        """يجلب كل التذاكر بحالة 'pending' (من الأحدث)."""
        return await self.fetchall(
            "SELECT id, user_id, username, ticket_number, message, "
            "status, created_at "
            "FROM support_tickets "
            "WHERE status = 'pending' "
            "ORDER BY created_at DESC"
        )

    # =====================================================================
    # 3) إغلاق تذكرة
    # =====================================================================

    async def close_ticket(self, ticket_id: int) -> bool:
        """يغلق تذكرة. يُرجع True إذا تم التحديث (تذكرة موجودة)."""
        return await self.execute(
            "UPDATE support_tickets SET status = 'closed' WHERE id = ?",
            (ticket_id,),
        ) > 0

    # =====================================================================
    # 4) حذف كل التذاكر
    # =====================================================================

    async def delete_all_tickets(self) -> bool:
        """
        يحذف كل التذاكر.
        يُرجع True فقط إذا حُذف صف واحد على الأقل (مطابق للسلوك الأصلي).
        """
        return await self.execute("DELETE FROM support_tickets") > 0