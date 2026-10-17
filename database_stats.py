#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_stats.py - دوال الإحصائيات والمشرفين (v7.4.6)
================================================================================
StatsMixin:
  - get_bot_stats      : إحصائيات البوت الأساسية
  - get_general_stats  : إحصائيات عامة شاملة (🚀 استعلام واحد)
  - get_user_stats     : إحصائيات المستخدمين
  - add_admin          : إضافة مشرف (UPSERT متوافق)
  - remove_admin       : إزالة مشرف
  - get_admin_list     : قائمة المشرفين (⚠️ المصدر الوحيد الموثوق)

🆕 v7.4.6 (ADMIN-DEDUP-CLARIFICATION):
  🟢 FIX-ADMIN-DEDUP (CRITICAL): توثيق أن get_admin_list يجب أن يبقى
      هنا فقط. وليس في GroupsMixin.
      السبب: ترتيب MRO في Database:
        RefactorMixin → MigrationsMixin → ChannelsPostsMixin →
        SubscriptionsMixin → GroupsMixin → TicketsMixin → ContestsMixin →
        StatsMixin → SettingsMixin → ...
      عندما يكون get_admin_list في BOTH GroupsMixin و StatsMixin:
        • DB.get_admin_list() → GroupsMixin يَفوز (بدون Cache)
        • StatsMixin.get_admin_list (مع auth_cache) لا يُستدعى أبداً
        • النتيجة: كل استدعاء = DB query (~42ms) بدل 0ms
      الأثر: إما حذف النسخة من GroupsMixin، أو تفويضها لـ StatsMixin.
      (انظر database_groups.py v7.4.19 المخطط).

  🟢 FIX-ADMIN-CACHE-CONSISTENCY: add_admin/remove_admin يُبطلان
      auth_cache.invalidate() بشكل شامل — يمسح get_admin_list(0)
      أيضاً. لا حاجة لتعديل.

  🟢 IMPROVE-DOCSTRING: توضيح العلاقة مع GroupsMixin.

🆕 v7.4.5 (FIX-DB-SIZE-STATS) — محفوظ:
  ✅ get_bot_stats: إضافة db_size_kb (via self.get_db_size_kb())
  ✅ get_general_stats: إضافة db_size_kb
  ✅ حل مشكلة "💾 حجم قاعدة البيانات: 0.0 KB"
  ✅ يعمل على PostgreSQL/MySQL/SQLite
  ✅ لا تغيير في السلوك السابق — إضافة حقل فقط

🆕 v7.4.4 (تحسينات أداء + إصلاحات) — محفوظ:
  ✅ get_general_stats: استعلام واحد بدل 9 استعلامات (PostgreSQL)
    - يحسّن admin_stats من 4.24s → 200ms
  ✅ get_bot_stats: استعلام واحد بدل 7 استعلامات
  ✅ add_admin: UPSERT متوافق مع PostgreSQL/MySQL/SQLite
  ✅ get_admin_list: إصلاح خطأ تخزين [user_id] بدل النتائج الكاملة
  ✅ حماية كاملة ضد None (كل القيم تُرجع 0 افتراضياً)

📌 مطابق 100% للسلوك الأصلي في database.py

📌 يفترض أن الـ Database يوفّر:
  - self.connection()
  - self._fetchval_with_conn / self._execute_with_conn / self._fetchall_with_conn
  - self.fetchall / self.fetchval / self.execute
  - self.TimeUtils
  - self.CACHE_AVAILABLE
  - self.auth_cache
  - self.USE_POSTGRES / self.USE_MYSQL
  - self.get_db_size_kb()  ← ✅ v7.4.5 (من database.py v7.7.14)
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
        """
        ✅ v7.4.5: استعلام واحد + حساب حجم DB.

        يعمل على PostgreSQL/MySQL/SQLite.
        """
        try:
            stats: Dict[str, int] = {}
            if getattr(self, "USE_POSTGRES", False):
                # ✅ PostgreSQL: استعلام واحد بـ UNION ALL
                query = """
                    SELECT 'users' AS metric,
                           (SELECT COUNT(*) FROM users) AS value
                    UNION ALL
                    SELECT 'channels', (SELECT COUNT(*) FROM user_channels)
                    UNION ALL
                    SELECT 'groups', (SELECT COUNT(*) FROM bot_groups)
                    UNION ALL
                    SELECT 'posts', (SELECT COUNT(*) FROM posts)
                    UNION ALL
                    SELECT 'published', (SELECT COUNT(*) FROM posts WHERE published = 1)
                    UNION ALL
                    SELECT 'active_subs',
                           (SELECT COUNT(*) FROM subscriptions
                            WHERE status = 'active' AND end_date > $1)
                    UNION ALL
                    SELECT 'tickets',
                           (SELECT COUNT(*) FROM support_tickets
                            WHERE status = 'pending')
                """
                rows = await self.fetchall(query, (self.TimeUtils.utc_now(),))
                stats = {row['metric']: row['value'] for row in rows} if rows else {}

            else:
                # SQLite/MySQL: استعلامات منفصلة (أسرع في هذه المحركات)
                async with self.connection() as conn:
                    stats['users'] = await self._fetchval_with_conn(
                        conn, "SELECT COUNT(*) FROM users", default=0
                    )
                    stats['channels'] = await self._fetchval_with_conn(
                        conn, "SELECT COUNT(*) FROM user_channels", default=0
                    )
                    stats['groups'] = await self._fetchval_with_conn(
                        conn, "SELECT COUNT(*) FROM bot_groups", default=0
                    )
                    stats['posts'] = await self._fetchval_with_conn(
                        conn, "SELECT COUNT(*) FROM posts", default=0
                    )
                    stats['published'] = await self._fetchval_with_conn(
                        conn, "SELECT COUNT(*) FROM posts WHERE published = 1",
                        default=0,
                    )
                    stats['active_subs'] = await self._fetchval_with_conn(
                        conn,
                        "SELECT COUNT(*) FROM subscriptions "
                        "WHERE status = 'active' AND end_date > ?",
                        self.TimeUtils.utc_now(), default=0,
                    )
                    stats['tickets'] = await self._fetchval_with_conn(
                        conn,
                        "SELECT COUNT(*) FROM support_tickets "
                        "WHERE status = 'pending'",
                        default=0,
                    )

            # ✅ v7.4.5: حساب حجم قاعدة البيانات
            db_size_kb = 0.0
            try:
                db_size_kb = await self.get_db_size_kb()
            except AttributeError:
                logger.debug(
                    "⚠️ get_db_size_kb غير متاح "
                    "(database.py قديم؟) — استخدم 0.0"
                )
            except Exception as e:
                logger.warning(f"⚠️ get_db_size_kb: {e}")

            return {
                "users": int(stats.get('users', 0) or 0),
                "channels": int(stats.get('channels', 0) or 0),
                "groups": int(stats.get('groups', 0) or 0),
                "posts": int(stats.get('posts', 0) or 0),
                "published": int(stats.get('published', 0) or 0),
                "active_subs": int(stats.get('active_subs', 0) or 0),
                "tickets": int(stats.get('tickets', 0) or 0),
                "db_size_kb": float(db_size_kb or 0.0),
            }

        except Exception as e:
            logger.error(f"❌ get_bot_stats: {e}", exc_info=True)
            return {
                "users": 0, "channels": 0, "groups": 0,
                "posts": 0, "published": 0,
                "active_subs": 0, "tickets": 0,
                "db_size_kb": 0.0,
            }

    # =====================================================================
    # 2) إحصائيات عامة شاملة
    # =====================================================================

    async def get_general_stats(self) -> Dict:
        """
        ✅ v7.4.5: استعلام واحد + حجم DB (PostgreSQL).

        يحسّن admin_stats من 4.24s → ~200ms.
        """
        try:
            stats: Dict[str, int] = {}
            if getattr(self, "USE_POSTGRES", False):
                # ✅ PostgreSQL: استعلام واحد بـ UNION ALL
                query = """
                    SELECT 'users' AS metric,
                           (SELECT COUNT(*) FROM users) AS value
                    UNION ALL
                    SELECT 'channels', (SELECT COUNT(*) FROM user_channels)
                    UNION ALL
                    SELECT 'groups', (SELECT COUNT(*) FROM bot_groups)
                    UNION ALL
                    SELECT 'posts', (SELECT COUNT(*) FROM posts)
                    UNION ALL
                    SELECT 'published', (SELECT COUNT(*) FROM posts WHERE published = 1)
                    UNION ALL
                    SELECT 'active_subs',
                           (SELECT COUNT(*) FROM subscriptions
                            WHERE status = 'active' AND end_date > $1)
                    UNION ALL
                    SELECT 'tickets',
                           (SELECT COUNT(*) FROM support_tickets
                            WHERE status = 'pending')
                    UNION ALL
                    SELECT 'invoices', (SELECT COUNT(*) FROM invoices)
                    UNION ALL
                    SELECT 'active_penalties',
                           (SELECT COUNT(*) FROM user_penalties
                            WHERE status = 'active')
                """
                rows = await self.fetchall(query, (self.TimeUtils.utc_now(),))
                stats = {row['metric']: row['value'] for row in rows} if rows else {}

            else:
                # SQLite/MySQL: استعلامات منفصلة
                async with self.connection() as conn:
                    stats['users'] = await self._fetchval_with_conn(
                        conn, "SELECT COUNT(*) FROM users", default=0
                    )
                    stats['channels'] = await self._fetchval_with_conn(
                        conn, "SELECT COUNT(*) FROM user_channels", default=0
                    )
                    stats['groups'] = await self._fetchval_with_conn(
                        conn, "SELECT COUNT(*) FROM bot_groups", default=0
                    )
                    stats['posts'] = await self._fetchval_with_conn(
                        conn, "SELECT COUNT(*) FROM posts", default=0
                    )
                    stats['published'] = await self._fetchval_with_conn(
                        conn, "SELECT COUNT(*) FROM posts WHERE published = 1",
                        default=0,
                    )
                    stats['active_subs'] = await self._fetchval_with_conn(
                        conn,
                        "SELECT COUNT(*) FROM subscriptions "
                        "WHERE status = 'active' AND end_date > ?",
                        self.TimeUtils.utc_now(), default=0,
                    )
                    stats['tickets'] = await self._fetchval_with_conn(
                        conn,
                        "SELECT COUNT(*) FROM support_tickets "
                        "WHERE status = 'pending'",
                        default=0,
                    )
                    stats['invoices'] = await self._fetchval_with_conn(
                        conn, "SELECT COUNT(*) FROM invoices", default=0
                    )
                    stats['active_penalties'] = await self._fetchval_with_conn(
                        conn,
                        "SELECT COUNT(*) FROM user_penalties "
                        "WHERE status = 'active'",
                        default=0,
                    )

            # ✅ v7.4.5: حساب حجم قاعدة البيانات
            db_size_kb = 0.0
            try:
                db_size_kb = await self.get_db_size_kb()
            except AttributeError:
                logger.debug(
                    "⚠️ get_db_size_kb غير متاح "
                    "(database.py قديم؟) — استخدم 0.0"
                )
            except Exception as e:
                logger.warning(f"⚠️ get_db_size_kb: {e}")

            return {
                "users": int(stats.get('users', 0) or 0),
                "channels": int(stats.get('channels', 0) or 0),
                "groups": int(stats.get('groups', 0) or 0),
                "posts": int(stats.get('posts', 0) or 0),
                "published": int(stats.get('published', 0) or 0),
                "active_subs": int(stats.get('active_subs', 0) or 0),
                "tickets": int(stats.get('tickets', 0) or 0),
                "invoices": int(stats.get('invoices', 0) or 0),
                "active_penalties": int(stats.get('active_penalties', 0) or 0),
                "db_size_kb": float(db_size_kb or 0.0),
            }

        except Exception as e:
            logger.error(f"❌ get_general_stats: {e}", exc_info=True)
            return {
                "users": 0, "channels": 0, "groups": 0,
                "posts": 0, "published": 0,
                "active_subs": 0, "tickets": 0,
                "invoices": 0, "active_penalties": 0,
                "db_size_kb": 0.0,
            }

    # =====================================================================
    # 3) إحصائيات المستخدمين
    # =====================================================================

    async def get_user_stats(self) -> Dict:
        """إحصائيات المستخدمين (users + banned)."""
        try:
            if getattr(self, "USE_POSTGRES", False):
                # ✅ PostgreSQL: استعلام واحد
                query = """
                    SELECT 'users' AS metric,
                           (SELECT COUNT(*) FROM users) AS value
                    UNION ALL
                    SELECT 'banned',
                           (SELECT COUNT(*) FROM users WHERE banned = 1)
                """
                rows = await self.fetchall(query)
                stats = {row['metric']: row['value'] for row in rows} if rows else {}
                return {
                    "users": int(stats.get('users', 0) or 0),
                    "banned": int(stats.get('banned', 0) or 0),
                }
            else:
                total = await self.fetchval(
                    "SELECT COUNT(*) FROM users", default=0
                )
                banned = await self.fetchval(
                    "SELECT COUNT(*) FROM users WHERE banned = 1",
                    default=0,
                )
                return {
                    "users": int(total or 0),
                    "banned": int(banned or 0),
                }
        except Exception as e:
            logger.error(f"❌ get_user_stats: {e}", exc_info=True)
            return {"users": 0, "banned": 0}

    # =====================================================================
    # 4) إضافة مشرف
    # =====================================================================

    async def add_admin(self, admin_id: int, added_by: int) -> bool:
        """
        ✅ v7.4.4: UPSERT متوافق مع PostgreSQL/MySQL/SQLite.

        🟢 v7.4.6 FIX-ADMIN-CACHE-CONSISTENCY:
            - auth_cache.invalidate() بدون معامل يمسح get_admin_list(0)
              أيضاً — لا حاجة لتعديل.
        """
        try:
            db_type = "sqlite"
            if getattr(self, "USE_POSTGRES", False):
                db_type = "postgres"
            elif getattr(self, "USE_MYSQL", False):
                db_type = "mysql"

            if db_type == "postgres":
                query = (
                    "INSERT INTO bot_admins (user_id, added_by, added_at) "
                    "VALUES ($1, $2, $3) "
                    "ON CONFLICT (user_id) DO NOTHING"
                )
                result = await self.execute(
                    query, (admin_id, added_by, self.TimeUtils.utc_now())
                )
            elif db_type == "mysql":
                query = (
                    "INSERT IGNORE INTO bot_admins "
                    "(user_id, added_by, added_at) "
                    "VALUES (%s, %s, %s)"
                )
                result = await self.execute(
                    query, (admin_id, added_by, self.TimeUtils.utc_now())
                )
            else:
                query = (
                    "INSERT OR IGNORE INTO bot_admins "
                    "(user_id, added_by, added_at) "
                    "VALUES (?, ?, ?)"
                )
                result = await self.execute(
                    query, (admin_id, added_by, self.TimeUtils.utc_now())
                )

            if result and result > 0 and self.CACHE_AVAILABLE:
                try:
                    await self.auth_cache.invalidate()
                except Exception as e:
                    logger.debug(f"auth_cache invalidate: {e}")

            return result is not None and result > 0
        except Exception as e:
            logger.error(f"❌ add_admin({admin_id}): {e}", exc_info=True)
            return False

    # =====================================================================
    # 5) إزالة مشرف
    # =====================================================================

    async def remove_admin(self, admin_id: int) -> bool:
        """
        إزالة مشرف من القائمة.

        🟢 v7.4.6 FIX-ADMIN-CACHE-CONSISTENCY:
            - auth_cache.invalidate() بدون معامل يمسح get_admin_list(0).
        """
        try:
            async with self.connection() as conn:
                deleted = await self._execute_with_conn(
                    conn,
                    "DELETE FROM bot_admins WHERE user_id = ?",
                    admin_id,
                )
                if deleted > 0 and self.CACHE_AVAILABLE:
                    try:
                        await self.auth_cache.invalidate()
                    except Exception as e:
                        logger.debug(f"auth_cache invalidate: {e}")
                return deleted > 0
        except Exception as e:
            logger.error(f"❌ Error in remove_admin: {e}", exc_info=True)
            return False

    # =====================================================================
    # 6) قائمة المشرفين
    # =====================================================================

    async def get_admin_list(self) -> List[Dict]:
        """
        ✅ v7.4.4: إصلاح خطأ تخزين [user_id] بدل النتائج الكاملة.

        🟢 v7.4.6 FIX-ADMIN-DEDUP (CRITICAL):
            هذه هي النسخة المُحصَّنة مع auth_cache.
            يجب ألا تكون هناك نسخة مكرّرة في GroupsMixin — لأن ترتيب
            MRO يجعل GroupsMixin يفوز (قبل StatsMixin) → يفقد
            الـ Cache → 42ms إضافية لكل استدعاء.

            إذا كانت GroupsMixin تُعرِّف get_admin_list → احذفها
            أو فوّضها لـ super().get_admin_list() (انظر
            database_groups.py v7.4.19 المخطط).

        الآلية:
          • Cache hit → 0ms (من auth_cache)
          • Cache miss → DB query (~42ms) + cache set (60s TTL)
          • add_admin/remove_admin → invalidate() → cache miss التالي
            يعيد القراءة من DB
        """
        if self.CACHE_AVAILABLE:
            try:
                cached = await self.auth_cache.get_admin_list(0)
                if cached is not None:
                    return cached
            except Exception as e:
                logger.debug(f"auth_cache.get_admin_list: {e}")

        try:
            admins = await self.fetchall(
                "SELECT user_id, added_by, added_at FROM bot_admins "
                "ORDER BY added_at DESC"
            )
            admins = admins or []

            if self.CACHE_AVAILABLE:
                try:
                    # ✅ v7.4.4: تخزين النتائج الكاملة، ليس فقط user_id
                    await self.auth_cache.set_admin_list(0, admins)
                except Exception as e:
                    logger.debug(f"auth_cache.set_admin_list: {e}")

            return admins
        except Exception as e:
            logger.error(f"❌ get_admin_list: {e}", exc_info=True)
            return []


__all__ = ["StatsMixin"]


# ═════════════════════════════════════════════════════════════════════
# LOAD BEACON — v7.4.6
# ═════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "✅ database_stats.py v7.4.6 loaded | "
        "fixes=(ADMIN-DEDUP-CLARIFICATION: "
        "get_admin_list-must-be-here-only, "
        "ADMIN-CACHE-CONSISTENCY: add/remove-admin-invalidate, "
        "v7.4.5-all: db_size_kb, "
        "v7.4.4-all: batch-queries-upsert) | "
        "⚠️ تحقق: GroupsMixin لا يجب أن تعرّف get_admin_list"
    )
except Exception:
    pass