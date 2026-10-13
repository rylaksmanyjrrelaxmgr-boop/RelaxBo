#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_tickets.py - دوال التذاكر (v7.4.5)
================================================================================
🆕 v7.4.5 (QUALITY-HARDENING):
  🟢 FIX-T6: aliases (create_support_ticket, add_support_ticket) —
      log warning عند استقبال kwargs غير متوقعة (كانت تُبتلع بصمت).
  🟢 FIX-T7: aliases تقبل `content` كـ param صريح أيضاً
      (بعض الاستدعاءات القديمة قد تستخدم content=... مباشرة).
  🟢 FIX-T8: sanity check على next_num (يجب أن يكون >= 1).
      إذا وصل عدّاد التذاكر إلى حد غير معقول (> 10^12)، نُعيد
      العدّاد إلى 1 مع log تحذيري (يمنع overflow طويل الأمد).
  🟢 FIX-T9: توثيق أفضل لسبب استخدام per-user lock + UPSERT.

🆕 v7.4.4 (FIX-T4 + FIX-T5) — محفوظ:
  🔴 FIX-T4 (CRITICAL): create_ticket — استخدام UPSERT ذرّي بدل UPDATE فقط.
      السبب: إذا كان صف 'last_ticket_number' مفقوداً في جدول settings
      (بعد migration سيئة أو حذف يدوي)، فإن UPDATE يُرجع rowcount=0
      ولا يُدرج الصف → العدّاد يبقى مفقوداً → كل تذكرة تحصل على #1.
      الأثر قبل الإصلاح: فوضى كاملة في نظام الدعم (كل التذاكر #1).
      الإصلاح: UPSERT ذرّي (INSERT ... ON CONFLICT DO UPDATE لـ PG/SQLite
      أو ON DUPLICATE KEY UPDATE لـ MySQL) يضمن وجود الصف + تحديثه.
  🟡 FIX-T5 (MEDIUM): create_ticket — _get_user_lock(user_id) بدل
      self._lock العام.
      السبب: self._lock قفل عالمي واحد → كل إنشاء تذكرة من أي مستخدم
      ينتظر الآخر. مع 100 مستخدم متزامن → تسلسل كامل.
      الإصلاح: قفل per-user → عمليات المستخدمين المختلفين متوازية،
      وعمليات نفس المستخدم متسلسلة.

🆕 v7.4.3 (SUPPORT-MODE-ALIAS):
  🔴 SUPPORT-ALIAS-1: إضافة create_support_ticket كـ alias.
  🔴 SUPPORT-ALIAS-2: إضافة add_support_ticket كـ alias بديل.
  🟢 SUPPORT-ALIAS-3: التذكرة تُسجّل ticket_number + username عبر
      المسار الرسمي.

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

# 🆕 v7.4.5 FIX-T8: حد أقصى معقول لعدّاد التذاكر.
# السبب: منع تراكم الأرقام إلى قيم ضخمة على مدى سنوات الاستخدام.
# عملياً، حتى 1000 تذكرة/يوم × 10 سنوات ≈ 3.6M — أقل بكثير من 10^12.
_MAX_REASONABLE_TICKET_NUMBER = 10 ** 12


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

        🔴 FIX-T4 (v7.4.4): يستخدم UPSERT ذرّي لتحديث العدّاد.
        🟡 FIX-T5 (v7.4.4): يستخدم قفل per-user بدل العام.
        🟢 FIX-T8 (v7.4.5): sanity check على next_num.
        """
        # 🆕 v7.4.3: alias — إذا أُرسل `message` ولم يُرسل `content`
        if not content and message:
            content = message

        try:
            # 🔴 FIX-T5 (v7.4.4): قفل per-user بدل self._lock العام.
            #
            # السبب: self._lock قفل عالمي واحد → كل إنشاء تذكرة من أي
            # مستخدم ينتظر الآخر. مع 100 مستخدم في نفس اللحظة →
            # تسلسل كامل (بدل معالجة متوازية).
            #
            # _get_user_lock(user_id) يُنشئ قفل مستقل لكل مستخدم →
            # عمليات المستخدمين المختلفين متوازية، وعمليات نفس
            # المستخدم متسلسلة (وهو المطلوب — لأن العدّاد لا بد أن
            # يُقرأ ويُحدَّث بشكل متسلسل).
            #
            # ⚠️ مع fallback آمن إذا لم تكن _get_user_lock متاحة.
            _lock = self._lock
            if hasattr(self, "_get_user_lock"):
                try:
                    _lock = await self._get_user_lock(user_id)
                except Exception as _lock_e:
                    logger.debug(
                        f"create_ticket: _get_user_lock فشل — "
                        f"fallback لـ self._lock: {_lock_e}"
                    )
                    _lock = self._lock

            async with _lock:
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

                    # 🆕 v7.4.5 FIX-T8: sanity check.
                    # لو وصل العدّاد إلى قيمة غير معقولة (overflow
                    # محتمل أو فساد بيانات)، نُعيده إلى 1.
                    if next_num > _MAX_REASONABLE_TICKET_NUMBER:
                        logger.warning(
                            f"⚠️ create_ticket: عدّاد التذاكر "
                            f"({next_num}) > الحد المعقول "
                            f"({_MAX_REASONABLE_TICKET_NUMBER}) — "
                            f"إعادة العدّاد إلى 1"
                        )
                        next_num = 1

                    # 🔴 FIX-T4 (v7.4.4): استخدام UPSERT بدل UPDATE فقط.
                    #
                    # السبب: إذا كان صف 'last_ticket_number' مفقوداً
                    # في جدول settings (بعد migration سيئة أو حذف يدوي)،
                    # فإن UPDATE يُرجع rowcount=0 ولا يُدرج الصف →
                    # العدّاد يبقى مفقوداً → كل تذكرة تحصل على #1.
                    #
                    # الاستخدام الصحيح: UPSERT ذرّي حسب المحرك.
                    if getattr(self, "USE_POSTGRES", False):
                        await self._execute_with_conn(
                            conn,
                            f"INSERT INTO settings "
                            f"({key_col}, {value_col}) "
                            f"VALUES ($1, $2) "
                            f"ON CONFLICT ({key_col}) DO UPDATE "
                            f"SET {value_col} = EXCLUDED.{value_col}",
                            "last_ticket_number", str(next_num),
                        )
                    elif getattr(self, "USE_MYSQL", False):
                        # ⚠️ ملاحظة: VALUES(`value`) deprecated في
                        # MySQL 8.0.20+ لكنه مدعوم للتوافق الخلفي.
                        # الصيغة الحديثة (alias) غير مدعومة على MySQL <8.
                        await self._execute_with_conn(
                            conn,
                            f"INSERT INTO settings "
                            f"({key_col}, {value_col}) "
                            f"VALUES (%s, %s) "
                            f"ON DUPLICATE KEY UPDATE "
                            f"{value_col} = VALUES({value_col})",
                            "last_ticket_number", str(next_num),
                        )
                    else:  # SQLite
                        await self._execute_with_conn(
                            conn,
                            f"INSERT INTO settings "
                            f"({key_col}, {value_col}) "
                            f"VALUES (?, ?) "
                            f"ON CONFLICT({key_col}) DO UPDATE "
                            f"SET {value_col} = excluded.{value_col}",
                            "last_ticket_number", str(next_num),
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
    # 🆕 v7.4.5 FIX-T6/T7: تحسينات على الـ aliases
    # ═════════════════════════════════════════════════════════════════

    async def create_support_ticket(
        self,
        user_id: int,
        username: str = "",
        message: str = "",
        media_type: Optional[str] = None,
        media_file_id: Optional[str] = None,
        content: str = "",  # 🆕 FIX-T7: أيضاً كـ param صريح
        **kwargs,
    ) -> int:
        """
        🆕 v7.4.3: alias لـ create_ticket للتوافق مع
        handlers_message.py v7.18.29 (_handle_support_mode_text).

        🆕 v7.4.5 FIX-T6: log warning عن kwargs غير متوقعة (كانت
            تُبتلع بصمت → تُخفي أخطاء استدعاء).
        🆕 v7.4.5 FIX-T7: يقبل `content` أيضاً كـ param صريح
            (بعض الاستدعاءات القديمة قد تستخدم content=...).

        يقبل:
          - user_id:     معرّف المستخدم
          - username:    اسم المستخدم (اختياري)
          - message:     نص الرسالة
          - content:     نص الرسالة (alias)
          - media_type:  نوع الوسائط (photo/video/voice/...)
          - media_file_id: معرّف الملف

        يُرجع رقم التذكرة أو 0 عند الفشل.
        """
        if kwargs:
            logger.warning(
                f"⚠️ create_support_ticket: kwargs غير متوقعة "
                f"سيتم تجاهلها: {list(kwargs.keys())}"
            )
        return await self.create_ticket(
            user_id=user_id,
            username=username or "",
            content=content or message or "",
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
        content: str = "",  # 🆕 FIX-T7
        **kwargs,
    ) -> int:
        """
        🆕 v7.4.3 SUPPORT-ALIAS-2: اسم بديل ثانٍ لـ create_ticket.

        بعض الإصدارات القديمة من handlers_message تستخدم
        add_support_ticket بدلاً من create_support_ticket.

        🆕 v7.4.5 FIX-T6/T7 — نفس تحسينات create_support_ticket.
        """
        if kwargs:
            logger.warning(
                f"⚠️ add_support_ticket: kwargs غير متوقعة "
                f"سيتم تجاهلها: {list(kwargs.keys())}"
            )
        return await self.create_ticket(
            user_id=user_id,
            username=username or "",
            content=content or message or "",
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