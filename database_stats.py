#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_stats.py - دوال الإحصائيات والمشرفين (v7.4.7)
================================================================================
StatsMixin:
  - get_bot_stats      : إحصائيات البوت الأساسية
  - get_general_stats  : إحصائيات عامة شاملة (🚀 استعلام واحد)
  - get_user_stats     : إحصائيات المستخدمين
  - add_admin          : إضافة مشرف (UPSERT متوافق)
  - remove_admin       : إزالة مشرف
  - get_admin_list     : قائمة المشرفين (⚠️ المصدر الوحيد الموثوق)

🆕 v7.4.7 (SAFETY-FIXES-AUDIT):

  🟠 FIX-STATS-1 (IMPORTANT): cache لـ get_user_stats (TTL=300s)
      السبب: get_user_stats يجري 2 استعلامات على users (الجدول
      الأكبر عادةً). على تطبيقات كبيرة (100k+)، قد يأخذ 100-2000ms.
      الآن: cache 5 دقائق → 0ms عند hit.

  🟠 FIX-STATS-2 (IMPORTANT): add_admin idempotent = True
      السبب: ON CONFLICT DO NOTHING / INSERT OR IGNORE يرجع
      rowcount=0 عند "موجود مسبقاً" → add_admin ترجع False →
      المُنادي يعرض "فشل الإضافة" مُضللاً. الآن: فحص وجود
      مسبق + اعتبار "موجود" نجاحاً (idempotent semantics).

  🟠 FIX-STATS-3 (IMPORTANT): cache لـ get_bot_stats + get_general_stats
      TTL=30s + 60s على التوالي.
      السبب: /stats و /admin تُفتح بضغطات متكررة → 200ms × 100
      استدعاء/دقيقة = حمل زائد على DB. cache قصير يُقلل ذلك
      بشكل كبير.

  🟡 FIX-STATS-4 (MINOR): get_general_stats — fallback عند فشل
      UNION ALL على PG (جدول مفقود مثل invoices).
      السبب: إذا كان invoices مفقوداً، كان fetchall يفشل كاملاً
      → كل الإحصائيات = 0 (خطأ صامت). الآن: fallback للاستعلامات
      المنفصلة، كل واحد بـ try/except → الإحصائيات الصحيحة تُعرض
      حتى لو invoices مفقود.

  🟡 FIX-STATS-5 (MINOR): db_size_kb + db_size_kb_available
      السبب: "0.0 KB" يظهر عند فشل get_db_size_kb. الآن: حقل
      إضافي يُخبر المستهلك بالحالة. المستهلك يمكنه عرض "غير متاح".

  🟡 FIX-STATS-6 (MINOR): use _prepare_query if available
      السبب: database_groups.py v7.4.20 أضاف _prepare_query (helper).
      database_stats يجب أن يستخدمه للاتساق على PG (رغم أن
      _execute_with_conn يحوّل تلقائياً). الآن: self._prepare_query
      إن وُجد، وإلا النص الأصلي.

  ✅ محفوظ من v7.4.6:
      FIX-ADMIN-DEDUP (CRITICAL — documentation)
      FIX-ADMIN-CACHE-CONSISTENCY
  ✅ محفوظ من v7.4.5:
      db_size_kb في get_bot_stats + get_general_stats
  ✅ محفوظ من v7.4.4:
      UNION ALL batching
      UPSERT multi-DB
      get_admin_list fix (full rows)
      full None protection

📌 مطابق 100% للسلوك الأصلي في database.py

📌 يفترض أن الـ Database يوفّر:
  - self.connection()
  - self._fetchval_with_conn / self._execute_with_conn / self._fetchall_with_conn
  - self.fetchall / self.fetchval / self.execute
  - self.TimeUtils
  - self.CACHE_AVAILABLE
  - self.auth_cache
  - self.internal_cache
  - self.USE_POSTGRES / self.USE_MYSQL
  - self.get_db_size_kb()  ← من database.py v7.7.14
  - self._prepare_query()  ← من database_groups.py v7.4.20 (اختياري)
================================================================================
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# ثوابت
# ═════════════════════════════════════════════════════════════════════

_BOT_STATS_CACHE_TTL = 30.0        # 30s — بيانات تتغير بحركة نشطة
_GENERAL_STATS_CACHE_TTL = 60.0    # 60s — بيانات إدارية
_USER_STATS_CACHE_TTL = 300.0      # 300s — users/banned نادراً ما يتغيران

_BOT_STATS_CACHE_KEY = "bot_stats_v747"
_GENERAL_STATS_CACHE_KEY = "general_stats_v747"
_USER_STATS_CACHE_KEY = "user_stats_v747"


class StatsMixin:
    """Mixin يحتوي كل دوال الإحصائيات والمشرفين"""

    # ═══════════════════════════════════════════════════════════════
    # 0) helpers داخلية
    # 🟡 v7.4.7 FIX-STATS-6: use _prepare_query if available
    # ═══════════════════════════════════════════════════════════════

    def _prepare_stats_query(self, query: str) -> str:
        """
        🟡 v7.4.7 FIX-STATS-6: يستخدم self._prepare_query إن وُجد،
        وإلا يُرجع النص كما هو (execute → _convert_placeholders).

        هذا للاتساق مع database_groups.py v7.4.20 (حيث تمر كل
        الاستعلامات عبر _prepare_query).
        """
        try:
            fn = getattr(self, "_prepare_query", None)
            if callable(fn):
                return fn(query)
        except Exception as e:
            logger.debug(f"_prepare_stats_query: {e}")
        return query

    async def _stats_cache_get(self, key: str) -> Optional[Any]:
        """يقرأ من internal_cache إن كانت متاحة."""
        try:
            if not getattr(self, "CACHE_AVAILABLE", False):
                return None
            cache = getattr(self, "internal_cache", None)
            if cache is None:
                return None
            return await cache.get(key)
        except Exception as e:
            logger.debug(f"_stats_cache_get({key}): {e}")
            return None

    async def _stats_cache_set(
        self, key: str, value: Any, ttl: float,
    ) -> None:
        """يخزّن في internal_cache إن كانت متاحة."""
        try:
            if not getattr(self, "CACHE_AVAILABLE", False):
                return
            cache = getattr(self, "internal_cache", None)
            if cache is None:
                return
            await cache.set(key, value, ttl=ttl)
        except Exception as e:
            logger.debug(f"_stats_cache_set({key}): {e}")

    async def _stats_cache_invalidate(self, key: str) -> None:
        """يبطل مفتاحاً واحداً في internal_cache."""
        try:
            if not getattr(self, "CACHE_AVAILABLE", False):
                return
            cache = getattr(self, "internal_cache", None)
            if cache is None:
                return
            await cache.invalidate(key)
        except Exception as e:
            logger.debug(f"_stats_cache_invalidate({key}): {e}")

    # =====================================================================
    # 1) إحصائيات البوت الأساسية
    # 🟠 v7.4.7 FIX-STATS-3: cache TTL=30s
    # =====================================================================

    async def get_bot_stats(self) -> Dict:
        """
        إحصائيات البوت الأساسية.

        🟠 v7.4.7 FIX-STATS-3: cache 30s لتقليل الضغط على DB.
        """
        # cache lookup
        cached = await self._stats_cache_get(_BOT_STATS_CACHE_KEY)
        if isinstance(cached, dict):
            return cached

        try:
            stats: Dict[str, int] = {}
            if getattr(self, "USE_POSTGRES", False):
                # PostgreSQL: استعلام واحد بـ UNION ALL
                query = self._prepare_stats_query("""
                    SELECT 'users' AS metric,
                           (SELECT COUNT(*) FROM users) AS value
                    UNION ALL
                    SELECT 'channels', (SELECT COUNT(*) FROM user_channels)
                    UNION ALL
                    SELECT 'groups', (SELECT COUNT(*) FROM bot_groups)
                    UNION ALL
                    SELECT 'posts', (SELECT COUNT(*) FROM posts)
                    UNION ALL
                    SELECT 'published',
                           (SELECT COUNT(*) FROM posts WHERE published = 1)
                    UNION ALL
                    SELECT 'active_subs',
                           (SELECT COUNT(*) FROM subscriptions
                            WHERE status = 'active' AND end_date > ?)
                    UNION ALL
                    SELECT 'tickets',
                           (SELECT COUNT(*) FROM support_tickets
                            WHERE status = 'pending')
                """)
                try:
                    rows = await self.fetchall(
                        query, (self.TimeUtils.utc_now(),))
                    stats = (
                        {row['metric']: row['value'] for row in rows}
                        if rows else {}
                    )
                except Exception as e:
                    logger.warning(
                        f"⚠️ get_bot_stats PG UNION ALL فشل: {e} "
                        f"— fallback فردي")
                    stats = await self._get_bot_stats_fallback()

            else:
                # SQLite/MySQL: استعلامات منفصلة (أسرع في هذه المحركات)
                stats = await self._get_bot_stats_fallback()

            # حساب حجم DB
            db_size_kb = None
            db_size_available = False
            try:
                fn = getattr(self, "get_db_size_kb", None)
                if callable(fn):
                    db_size_kb = await fn()
                    db_size_available = db_size_kb is not None
            except AttributeError:
                logger.debug(
                    "⚠️ get_db_size_kb غير متاح "
                    "(database.py قديم؟)")
            except Exception as e:
                logger.warning(f"⚠️ get_db_size_kb: {e}")

            result = {
                "users": int(stats.get('users', 0) or 0),
                "channels": int(stats.get('channels', 0) or 0),
                "groups": int(stats.get('groups', 0) or 0),
                "posts": int(stats.get('posts', 0) or 0),
                "published": int(stats.get('published', 0) or 0),
                "active_subs": int(stats.get('active_subs', 0) or 0),
                "tickets": int(stats.get('tickets', 0) or 0),
                "db_size_kb": float(db_size_kb or 0.0),
                # 🟡 v7.4.7 FIX-STATS-5
                "db_size_kb_available": db_size_available,
            }

            # cache set
            await self._stats_cache_set(
                _BOT_STATS_CACHE_KEY, result, _BOT_STATS_CACHE_TTL)

            return result

        except Exception as e:
            logger.error(f"❌ get_bot_stats: {e}", exc_info=True)
            return {
                "users": 0, "channels": 0, "groups": 0,
                "posts": 0, "published": 0,
                "active_subs": 0, "tickets": 0,
                "db_size_kb": 0.0,
                "db_size_kb_available": False,
            }

    async def _get_bot_stats_fallback(self) -> Dict[str, int]:
        """🟠 v7.4.7: fallback فردي عند فشل UNION ALL."""
        stats: Dict[str, int] = {
            'users': 0, 'channels': 0, 'groups': 0,
            'posts': 0, 'published': 0,
            'active_subs': 0, 'tickets': 0,
        }
        try:
            async with self.connection() as conn:
                _pairs = [
                    ('users', "SELECT COUNT(*) FROM users", ()),
                    ('channels',
                     "SELECT COUNT(*) FROM user_channels", ()),
                    ('groups',
                     "SELECT COUNT(*) FROM bot_groups", ()),
                    ('posts', "SELECT COUNT(*) FROM posts", ()),
                    ('published',
                     "SELECT COUNT(*) FROM posts WHERE published = 1",
                     ()),
                    ('active_subs',
                     "SELECT COUNT(*) FROM subscriptions "
                     "WHERE status = 'active' AND end_date > ?",
                     (self.TimeUtils.utc_now(),)),
                    ('tickets',
                     "SELECT COUNT(*) FROM support_tickets "
                     "WHERE status = 'pending'", ()),
                ]
                for name, sql, params in _pairs:
                    try:
                        q = self._prepare_stats_query(sql)
                        val = await self._fetchval_with_conn(
                            conn, q, *params, default=0)
                        stats[name] = int(val or 0)
                    except Exception as _e:
                        logger.debug(
                            f"bot_stats fallback {name}: {_e}")
                        stats[name] = 0
        except Exception as e:
            logger.warning(
                f"⚠️ _get_bot_stats_fallback: {e}")
        return stats

    # =====================================================================
    # 2) إحصائيات عامة شاملة
    # 🟠 v7.4.7 FIX-STATS-3: cache TTL=60s
    # 🟡 v7.4.7 FIX-STATS-4: fallback عند فشل UNION ALL
    # =====================================================================

    async def get_general_stats(self) -> Dict:
        """
        إحصائيات عامة شاملة.

        🟠 v7.4.7 FIX-STATS-3: cache 60s.
        🟡 v7.4.7 FIX-STATS-4: fallback لكل استعلام عند فشل
        UNION ALL (جدول مفقود = لا صفر للجميع).
        """
        # cache lookup
        cached = await self._stats_cache_get(_GENERAL_STATS_CACHE_KEY)
        if isinstance(cached, dict):
            return cached

        try:
            stats: Dict[str, int] = {}
            if getattr(self, "USE_POSTGRES", False):
                # PostgreSQL: استعلام واحد بـ UNION ALL
                query = self._prepare_stats_query("""
                    SELECT 'users' AS metric,
                           (SELECT COUNT(*) FROM users) AS value
                    UNION ALL
                    SELECT 'channels', (SELECT COUNT(*) FROM user_channels)
                    UNION ALL
                    SELECT 'groups', (SELECT COUNT(*) FROM bot_groups)
                    UNION ALL
                    SELECT 'posts', (SELECT COUNT(*) FROM posts)
                    UNION ALL
                    SELECT 'published',
                           (SELECT COUNT(*) FROM posts WHERE published = 1)
                    UNION ALL
                    SELECT 'active_subs',
                           (SELECT COUNT(*) FROM subscriptions
                            WHERE status = 'active' AND end_date > ?)
                    UNION ALL
                    SELECT 'tickets',
                           (SELECT COUNT(*) FROM support_tickets
                            WHERE status = 'pending')
                    UNION ALL
                    SELECT 'invoices',
                           (SELECT COUNT(*) FROM invoices)
                    UNION ALL
                    SELECT 'active_penalties',
                           (SELECT COUNT(*) FROM user_penalties
                            WHERE status = 'active')
                """)
                try:
                    rows = await self.fetchall(
                        query, (self.TimeUtils.utc_now(),))
                    stats = (
                        {row['metric']: row['value'] for row in rows}
                        if rows else {}
                    )
                except Exception as e:
                    logger.warning(
                        f"⚠️ get_general_stats PG UNION ALL فشل: {e} "
                        f"— fallback فردي")
                    stats = await self._get_general_stats_fallback()

            else:
                # SQLite/MySQL: استعلامات منفصلة
                stats = await self._get_general_stats_fallback()

            # حساب حجم DB
            db_size_kb = None
            db_size_available = False
            try:
                fn = getattr(self, "get_db_size_kb", None)
                if callable(fn):
                    db_size_kb = await fn()
                    db_size_available = db_size_kb is not None
            except AttributeError:
                logger.debug(
                    "⚠️ get_db_size_kb غير متاح "
                    "(database.py قديم؟)")
            except Exception as e:
                logger.warning(f"⚠️ get_db_size_kb: {e}")

            result = {
                "users": int(stats.get('users', 0) or 0),
                "channels": int(stats.get('channels', 0) or 0),
                "groups": int(stats.get('groups', 0) or 0),
                "posts": int(stats.get('posts', 0) or 0),
                "published": int(stats.get('published', 0) or 0),
                "active_subs": int(stats.get('active_subs', 0) or 0),
                "tickets": int(stats.get('tickets', 0) or 0),
                "invoices": int(stats.get('invoices', 0) or 0),
                "active_penalties": int(
                    stats.get('active_penalties', 0) or 0),
                "db_size_kb": float(db_size_kb or 0.0),
                # 🟡 v7.4.7 FIX-STATS-5
                "db_size_kb_available": db_size_available,
            }

            # cache set
            await self._stats_cache_set(
                _GENERAL_STATS_CACHE_KEY, result,
                _GENERAL_STATS_CACHE_TTL)

            return result

        except Exception as e:
            logger.error(
                f"❌ get_general_stats: {e}", exc_info=True)
            return {
                "users": 0, "channels": 0, "groups": 0,
                "posts": 0, "published": 0,
                "active_subs": 0, "tickets": 0,
                "invoices": 0, "active_penalties": 0,
                "db_size_kb": 0.0,
                "db_size_kb_available": False,
            }

    async def _get_general_stats_fallback(self) -> Dict[str, int]:
        """
        🟡 v7.4.7 FIX-STATS-4: fallback فردي محصّن.
        كل استعلام معزول — جدول مفقود لا يُصفّر الباقي.
        """
        stats: Dict[str, int] = {
            'users': 0, 'channels': 0, 'groups': 0,
            'posts': 0, 'published': 0,
            'active_subs': 0, 'tickets': 0,
            'invoices': 0, 'active_penalties': 0,
        }
        try:
            async with self.connection() as conn:
                _pairs = [
                    ('users',
                     "SELECT COUNT(*) FROM users", ()),
                    ('channels',
                     "SELECT COUNT(*) FROM user_channels", ()),
                    ('groups',
                     "SELECT COUNT(*) FROM bot_groups", ()),
                    ('posts', "SELECT COUNT(*) FROM posts", ()),
                    ('published',
                     "SELECT COUNT(*) FROM posts WHERE published = 1",
                     ()),
                    ('active_subs',
                     "SELECT COUNT(*) FROM subscriptions "
                     "WHERE status = 'active' AND end_date > ?",
                     (self.TimeUtils.utc_now(),)),
                    ('tickets',
                     "SELECT COUNT(*) FROM support_tickets "
                     "WHERE status = 'pending'", ()),
                    ('invoices',
                     "SELECT COUNT(*) FROM invoices", ()),
                    ('active_penalties',
                     "SELECT COUNT(*) FROM user_penalties "
                     "WHERE status = 'active'", ()),
                ]
                for name, sql, params in _pairs:
                    try:
                        q = self._prepare_stats_query(sql)
                        val = await self._fetchval_with_conn(
                            conn, q, *params, default=0)
                        stats[name] = int(val or 0)
                    except Exception as _e:
                        # جدول مفقود أو خطأ — نُبقي 0 مع log
                        logger.debug(
                            f"general_stats fallback {name}: {_e}")
                        stats[name] = 0
        except Exception as e:
            logger.warning(
                f"⚠️ _get_general_stats_fallback: {e}")
        return stats

    # =====================================================================
    # 3) إحصائيات المستخدمين
    # 🟠 v7.4.7 FIX-STATS-1: cache TTL=300s
    # =====================================================================

    async def get_user_stats(self) -> Dict:
        """
        إحصائيات المستخدمين (users + banned).

        🟠 v7.4.7 FIX-STATS-1: cache 5 دقائق.
        السبب: users الجدول الأكبر عادةً. 100k+ صفوف = 200ms+
        لكل استدعاء بدون cache.
        """
        # cache lookup
        cached = await self._stats_cache_get(_USER_STATS_CACHE_KEY)
        if isinstance(cached, dict):
            return cached

        try:
            if getattr(self, "USE_POSTGRES", False):
                # PostgreSQL: استعلام واحد
                query = self._prepare_stats_query("""
                    SELECT 'users' AS metric,
                           (SELECT COUNT(*) FROM users) AS value
                    UNION ALL
                    SELECT 'banned',
                           (SELECT COUNT(*) FROM users WHERE banned = 1)
                """)
                try:
                    rows = await self.fetchall(query)
                    stats = (
                        {row['metric']: row['value'] for row in rows}
                        if rows else {}
                    )
                except Exception as e:
                    logger.debug(
                        f"user_stats PG UNION ALL فشل: {e} "
                        f"— fallback فردي")
                    stats = {}
                    try:
                        _q = self._prepare_stats_query(
                            "SELECT COUNT(*) FROM users")
                        stats['users'] = await self.fetchval(
                            _q, default=0) or 0
                    except Exception:
                        stats['users'] = 0
                    try:
                        _q = self._prepare_stats_query(
                            "SELECT COUNT(*) FROM users WHERE banned = 1")
                        stats['banned'] = await self.fetchval(
                            _q, default=0) or 0
                    except Exception:
                        stats['banned'] = 0
            else:
                stats = {}
                try:
                    _q = self._prepare_stats_query(
                        "SELECT COUNT(*) FROM users")
                    stats['users'] = await self.fetchval(
                        _q, default=0) or 0
                except Exception as _e:
                    logger.debug(f"users count: {_e}")
                    stats['users'] = 0
                try:
                    _q = self._prepare_stats_query(
                        "SELECT COUNT(*) FROM users WHERE banned = 1")
                    stats['banned'] = await self.fetchval(
                        _q, default=0) or 0
                except Exception as _e:
                    logger.debug(f"banned count: {_e}")
                    stats['banned'] = 0

            result = {
                "users": int(stats.get('users', 0) or 0),
                "banned": int(stats.get('banned', 0) or 0),
            }

            # cache set
            await self._stats_cache_set(
                _USER_STATS_CACHE_KEY, result, _USER_STATS_CACHE_TTL)

            return result

        except Exception as e:
            logger.error(
                f"❌ get_user_stats: {e}", exc_info=True)
            return {"users": 0, "banned": 0}

    # =====================================================================
    # 4) إضافة مشرف
    # 🟠 v7.4.7 FIX-STATS-2: idempotent semantics
    # =====================================================================

    async def add_admin(self, admin_id: int, added_by: int) -> bool:
        """
        إضافة مشرف.

        🟠 v7.4.7 FIX-STATS-2: idempotent.
          - إذا كان موجوداً → True (نجاح، لا خطأ)
          - إذا أُضيف الآن → True
          - إذا فشل الإدراج → False

        السبب: ON CONFLICT DO NOTHING / INSERT OR IGNORE يرجع
        rowcount=0 عند "موجود مسبقاً" → false negatives في
        المُنادي (handlers_command.py يعرض "فشل الإضافة" مُضللاً).
        """
        try:
            # 🟠 فحص وجود مسبق (idempotent semantics)
            try:
                _check_q = self._prepare_stats_query(
                    "SELECT 1 FROM bot_admins WHERE user_id = ? LIMIT 1")
                existing = await self.fetchval(
                    _check_q, (admin_id,), default=None)
                if existing is not None:
                    logger.debug(
                        f"add_admin({admin_id}): موجود مسبقاً → True")
                    return True
            except Exception as _e:
                logger.debug(f"add_admin existence check: {_e}")
                # نكمل — قد ينجح الإدراج

            db_type = "sqlite"
            if getattr(self, "USE_POSTGRES", False):
                db_type = "postgres"
            elif getattr(self, "USE_MYSQL", False):
                db_type = "mysql"

            if db_type == "postgres":
                query = self._prepare_stats_query(
                    "INSERT INTO bot_admins "
                    "(user_id, added_by, added_at) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT (user_id) DO NOTHING"
                )
                result = await self.execute(
                    query,
                    (admin_id, added_by, self.TimeUtils.utc_now()),
                )
            elif db_type == "mysql":
                query = self._prepare_stats_query(
                    "INSERT IGNORE INTO bot_admins "
                    "(user_id, added_by, added_at) "
                    "VALUES (?, ?, ?)"
                )
                result = await self.execute(
                    query,
                    (admin_id, added_by, self.TimeUtils.utc_now()),
                )
            else:
                query = self._prepare_stats_query(
                    "INSERT OR IGNORE INTO bot_admins "
                    "(user_id, added_by, added_at) "
                    "VALUES (?, ?, ?)"
                )
                result = await self.execute(
                    query,
                    (admin_id, added_by, self.TimeUtils.utc_now()),
                )

            # نجاح الإدراج أو "موجود مسبقاً" (race condition)
            # — كلاهما يعتبر True في idempotent semantics
            inserted = result is not None and result > 0
            if inserted or result == 0:
                # result == 0 → موجود مسبقاً (race) → True
                if self.CACHE_AVAILABLE:
                    try:
                        await self.auth_cache.invalidate()
                    except Exception as e:
                        logger.debug(
                            f"auth_cache invalidate: {e}")
                # إبطال caches الإحصائيات
                await self._invalidate_stats_caches()
                return True
            return False

        except Exception as e:
            logger.error(
                f"❌ add_admin({admin_id}): {e}", exc_info=True)
            return False

    # =====================================================================
    # 5) إزالة مشرف
    # =====================================================================

    async def remove_admin(self, admin_id: int) -> bool:
        """
        إزالة مشرف من القائمة.

        🟢 FIX-ADMIN-CACHE-CONSISTENCY (v7.4.6):
            - auth_cache.invalidate() بدون معامل يمسح get_admin_list(0).
        """
        try:
            async with self.connection() as conn:
                query = self._prepare_stats_query(
                    "DELETE FROM bot_admins WHERE user_id = ?")
                deleted = await self._execute_with_conn(
                    conn, query, admin_id,
                )
                if deleted > 0 and self.CACHE_AVAILABLE:
                    try:
                        await self.auth_cache.invalidate()
                    except Exception as e:
                        logger.debug(
                            f"auth_cache invalidate: {e}")
                if deleted > 0:
                    await self._invalidate_stats_caches()
                return deleted > 0
        except Exception as e:
            logger.error(
                f"❌ Error in remove_admin: {e}", exc_info=True)
            return False

    async def _invalidate_stats_caches(self) -> None:
        """🟠 v7.4.7: إبطال caches الإحصائيات بعد تغيير مشرفين."""
        for _key in (
            _BOT_STATS_CACHE_KEY,
            _GENERAL_STATS_CACHE_KEY,
            _USER_STATS_CACHE_KEY,
        ):
            try:
                await self._stats_cache_invalidate(_key)
            except Exception:
                pass

    # =====================================================================
    # 6) قائمة المشرفين
    # =====================================================================

    async def get_admin_list(self) -> List[Dict]:
        """
        قائمة المشرفين — النسخة المُحصَّنة مع auth_cache.

        🟢 FIX-ADMIN-DEDUP (CRITICAL, v7.4.6):
            هذه هي النسخة المُحصَّنة مع auth_cache.
            يجب ألا تكون هناك نسخة مكرّرة في GroupsMixin — لأن ترتيب
            MRO يجعل GroupsMixin يفوز (قبل StatsMixin) → يفقد
            الـ Cache → 42ms إضافية لكل استدعاء.

            (انظر database_groups.py v7.4.19/v7.4.20 المخطط)

        الآلية:
          • Cache hit → 0ms (من auth_cache)
          • Cache miss → DB query (~42ms) + cache set (TTL auth_cache)
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
            query = self._prepare_stats_query(
                "SELECT user_id, added_by, added_at FROM bot_admins "
                "ORDER BY added_at DESC"
            )
            admins = await self.fetchall(query)
            admins = admins or []

            if self.CACHE_AVAILABLE:
                try:
                    # تخزين النتائج الكاملة (ليس فقط user_id)
                    await self.auth_cache.set_admin_list(0, admins)
                except Exception as e:
                    logger.debug(
                        f"auth_cache.set_admin_list: {e}")

            return admins
        except Exception as e:
            logger.error(
                f"❌ get_admin_list: {e}", exc_info=True)
            return []


__all__ = [
    "StatsMixin",
    # ثوابت (للاستخدام الخارجي إن لزم)
    "_BOT_STATS_CACHE_TTL",
    "_GENERAL_STATS_CACHE_TTL",
    "_USER_STATS_CACHE_TTL",
    "_BOT_STATS_CACHE_KEY",
    "_GENERAL_STATS_CACHE_KEY",
    "_USER_STATS_CACHE_KEY",
]


# ═════════════════════════════════════════════════════════════════════
# LOAD BEACON — v7.4.7
# ═════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "✅ database_stats.py v7.4.7 SAFETY-FIXES-AUDIT loaded | "
        "FIX-STATS-1: user_stats-cache-300s ✅ | "
        "FIX-STATS-2: add_admin-idempotent-True ✅ | "
        "FIX-STATS-3: bot_stats-cache-30s + general_stats-cache-60s ✅ | "
        "FIX-STATS-4: general_stats-fallback-per-query ✅ | "
        "FIX-STATS-5: db_size_kb_available flag ✅ | "
        "FIX-STATS-6: use _prepare_query ✅ | "
        "✅ v7.4.6 ADMIN-DEDUP-DOC preserved | "
        "✅ v7.4.6 ADMIN-CACHE-CONSISTENCY preserved | "
        "✅ v7.4.5 db_size_kb preserved | "
        "✅ v7.4.4 UNION-ALL + UPSERT + full-rows preserved | "
        "⚠️ تحقق: GroupsMixin لا يجب أن تعرّف get_admin_list"
    )
except Exception:
    pass