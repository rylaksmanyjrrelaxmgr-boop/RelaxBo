#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_tickets.py - دوال التذاكر (v7.4.3)
================================================================================
🆕 v7.4.3 (SUPPORT-MODE-ALIAS):
  🔴 SUPPORT-ALIAS-1: إضافة create_support_ticket كـ alias لـ create_ticket.
      السبب: handlers_message.py v7.18.29 (_handle_support_mode_text)
      يبحث عن create_support_ticket — لم يكن موجوداً → كان يستخدم
      fallback INSERT مباشر (بدون ترقيم تلقائي).
  🔴 SUPPORT-ALIAS-2: إضافة add_support_ticket كـ alias بديل.
  🟢 SUPPORT-ALIAS-3: إنشاء التذكرة الآن يسجّل ticket_number + username
      بشكل صحيح عبر المسار الرسمي.

🆕 v7.4.2 (إصلاح MySQL):
    ✅ create_ticket: backticks حول `key` و `value` لـ MySQL
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
from typing import Dict, List, Optional

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
        username: str = "",
        content: str = "",
        media_type: Optional[str] = None,
        media_file_id: Optional[str] = None,
        message: Optional[str] = None,  # 🆕 v7.4.3: alias للتوافق
    ) -> int:
        """
        ينشئ تذكرة جديدة بترقيم تلقائي.
        يُرجع رقم التذكرة (ticket_number) أو 0 عند الفشل.

        🆕 v7.4.3: يقبل `message` كـ alias لـ `content` للتوافق مع
        استدعاءات SUPPORT_MODE التي تستخدم `message=...`.
        """
        # 🆕 v7.4.3: alias — إذا أُرسل `message` ولم يُرسل `content`
        if not content and message:
            content = message

        try:
            async with self._lock:
                async with self.transaction() as conn:
                    # ✅ v7.4.2: backticks لـ MySQL
                    key_col = self._tq("key")
                    value_col = self._tq("value")

                    # ✅ v7.4.2: parameterized query
                    next_num_str = await self._fetchval_with_conn(
                        conn,
                        f"SELECT {value_col} FROM settings "
                        f"WHERE {key_col} = ?",
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

                    # تحديث العدّاد
                    await self._execute_with_conn(
                        conn,
                        f"UPDATE settings SET {value_col} = ? "
                        f"WHERE {key_col} = ?",
                        str(next_num), "last_ticket_number",
                    )

                    # إدراج التذكرة
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO support_tickets "
                        "(user_id, username, message, media_type, "
                        " media_file_id, ticket_number, status, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        user_id,
                        username or "",
                        content or "",
                        media_type,
                        media_file_id,
                        next_num,
                        'pending',
                        self.TimeUtils.utc_now(),
                    )
                return next_num
        except Exception as e:
            logger.error(
                f"❌ Error in create_ticket: {e}", exc_info=True)
            return 0

    # ═════════════════════════════════════════════════════════════════
    # 🆕 v7.4.3 SUPPORT-ALIAS-1/2: aliases للتوافق مع handlers_message
    # ═════════════════════════════════════════════════════════════════

    async def create_support_ticket(
        self,
        user_id: int,
        username: str = "",
        message: str = "",
        media_type: Optional[str] = None,
        media_file_id: Optional[str] = None,
        **kwargs,
    ) -> int:
        """
        🆕 v7.4.3: alias لـ create_ticket للتوافق مع
        handlers_message.py v7.18.29 (_handle_support_mode_text).

        يقبل:
          - user_id:     معرّف المستخدم
          - username:    اسم المستخدم (اختياري)
          - message:     نص الرسالة
          - media_type:  نوع الوسائط (photo/video/voice/...)
          - media_file_id: معرّف الملف

        يُرجع رقم التذكرة أو 0 عند الفشل.
        """
        return await self.create_ticket(
            user_id=user_id,
            username=username or "",
            content=message or "",
            media_type=media_type,
            media_file_id=media_file_id,
        )

    async def add_support_ticket(
        self,
        user_id: int,
        username: str = "",
        message: str = "",
        media_type: Optional[str] = None,
        media_file_id: Optional[str] = None,
        **kwargs,
    ) -> int:
        """
        🆕 v7.4.3 SUPPORT-ALIAS-2: اسم بديل ثانٍ لـ create_ticket.

        بعض الإصدارات القديمة من handlers_message تستخدم
        add_support_ticket بدلاً من create_support_ticket.
        """
        return await self.create_ticket(
            user_id=user_id,
            username=username or "",
            content=message or "",
            media_type=media_type,
            media_file_id=media_file_id,
        )

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


# ═══════════════════════════════════════════════════════════════════════
# التصدير
# ═══════════════════════════════════════════════════════════════════════

__all__ = ["TicketsMixin"]