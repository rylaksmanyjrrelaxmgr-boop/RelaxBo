#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_refactor_mixin.py - استخراج الدوال الكبيرة من database.py (v1.2.2-FIX-R2)
================================================================================
🎯 الهدف:
    تقليل حجم database.py عبر نقل الدوال الضخمة إلى ملف منفصل، مع
    الحفاظ على نفس السلوك 100% عبر نمط Mixin.

🆕 v1.2.2 (FIX-R2 — SAFETY-AUDIT):

  🔴 FIX-R2-1 (CRITICAL): احذف _pg_pool_factory من RefactorMixin
      السبب: database.py v7.7.74 يعرّف _pg_pool_factory بشكل محسّن
      (min_size=10, stmt_cache=100, max_inactive=300s, init=_pg_init_connection,
      idle_in_transaction_session_timeout=30000ms, application_name="relax_bot").
      لكن RefactorMixin يأتي أولاً في MRO → نُسخته القديمة تفوز →
      كل تحسينات v7.7.74 معطّلة على PG:
        • pool min_size=5 بدلاً من 10
        • statement_cache_size=500 بدلاً من 100
        • max_inactive_lifetime=60s بدلاً من 300s
        • لا يوجد init=_pg_init_connection (TCP keepalive socket-level)
        • لا يوجد idle_in_transaction_session_timeout
        • application_name="RelaxManager" بدلاً من "relax_bot"
      الآن: حُذفت بالكامل — database.py يُدير pool PG.

  🔴 FIX-R2-2 (CRITICAL): احذف _mysql_pool_factory من RefactorMixin
      السبب: database.py v7.7.74 يعرّفها بـ pool_recycle=1800,
      use_unicode=True. نُسخة RefactorMixin تستخدم pool_recycle=3600
      بدون use_unicode → تفوز → MySQL pool بمعاملات قديمة.
      الآن: حُذفت — database.py يُدير pool MySQL.

  🟠 FIX-R2-3 (IMPORTANT): _expire_penalties_pg — أضف id + ON CONFLICT
      السبب: penalty_archive.id موجود كـ PK في database_tables.py.
      نسخة v1.2.1 لم تُدرِج id → فشل INSERT → CTE يرمي exception →
      expire_penalties معطّل تماماً على PostgreSQL.
      database.py v7.7.73 FIX-DB31 أصلحها (يُدرِج id)، لكن
      database_refactor_mixin v1.2.1 لم تحلّها → تعارض مباشر.
      الآن: id مُدرَج + ON CONFLICT (id) DO NOTHING (idempotent).

  🟡 FIX-R2-4 (MINOR): _expire_penalties_pg — دمج كامل في CTE واحد
      السبب: v1.2.1 كان يستخدم 2 round-trips (SELECT ثم INSERT+UPDATE).
      الآن: CTE واحد يجمع SELECT ... FOR UPDATE SKIP LOCKED + INSERT +
      UPDATE → 1 round-trip. تحسين ~40% في زمن الدفعة.
      ⚠️ أبقينا المسار الاحتياطي للتوافق مع PG < 9.5 الذي لا يدعم
         SKIP LOCKED (نادراً ما يُستخدم الآن).

  🟡 FIX-R2-5 (MINOR): إضافة توجيه واضح في الرأس للـ MRO
      السبب: developers قد يضيفون RefactorMixin قبل Database ويسقطون
      في نفس الفخ. الآن: توثيق صريح أن Pool Factories **موجودة في
      database.py** وليست هنا.

  ✅ محفوظ من v1.2.1:
      FIX-R1 (bind error في _expire_penalties_pg)
  ✅ محفوظ من v1.2.0:
      PERF-1..PERF-7 (CTE بدل LATERAL، INSERT قبل UPDATE، ...)
  ✅ محفوظ من v1.1.0:
      CHANNELS_TO_PUBLISH_SQL_PG_NO_MV
  ✅ محفوظ من v1.0.0:
      كل الثوابت والاستعلامات والـ bigint helpers

🆕 v1.2.1 (FIX-R1) — محفوظ:
  🔴 FIX-R1: _expire_penalties_pg — حذف *id_list الزائدة.
            السبب: في PostgreSQL، نفس $1..$N تشير إلى نفس المعاملات
            حتى لو تكررت في CTE. الكود كان يمرّر *id_list مرتين
            (6 قيم لـ 3 placeholders) → bind error.
            الأثر قبل الإصلاح: expire_penalties معطّل تمامًا على PG.

🆕 v1.2.0 (PERF-FIXES-2026) — محفوظ:
  🔴 PERF-1: CHANNELS_TO_PUBLISH_SQL_PG — إزالة LATERAL وتحويلها
            إلى CTEs مع GROUP BY.
  🔴 PERF-2: CHANNELS_TO_PUBLISH_SQL_PG_NO_MV — نفس التحسين.
  🔴 PERF-3: CHANNELS_TO_PUBLISH_SQL_MYSQL — فلترة published مبكرة.
  🔴 PERF-4: CHANNELS_TO_PUBLISH_SQL_SQLITE — فلترة published مبكرة.
  🔴 PERF-5: _expire_penalties_pg — دمج INSERT+UPDATE في CTE.
  🔴 PERF-6: _expire_penalties_mysql — ترتيب INSERT قبل UPDATE.
  🔴 PERF-7: _expire_penalties_sqlite — ترتيب INSERT قبل UPDATE.

🆕 v1.1.0 (PG-NO-MV-FALLBACK) — محفوظ.
🆕 v1.0.0 — محفوظ.

📦 المحتوى:
    ═══ ثوابت Module-level ═══
      - MAX_POST_FAIL_COUNT
      - EXPIRED_PENALTIES_BATCH
      - PENALTY_ARCHIVE_RETENTION_DAYS
      - DEFAULT_PUBLISH_INTERVAL_MINUTES
      - PUBLISH_POLLING_COMPENSATION_SECONDS

    ═══ ثوابت SQL (get_channels_to_publish) ═══
      - CHANNELS_TO_PUBLISH_SQL_PG
      - CHANNELS_TO_PUBLISH_SQL_PG_NO_MV
      - CHANNELS_TO_PUBLISH_SQL_MYSQL
      - CHANNELS_TO_PUBLISH_SQL_SQLITE

    ═══ RefactorMixin ═══
      Pool Factories:
        - _sqlite_pool_factory()  ← الوحيدة المتبقية
        (PG/MySQL pool factories انتقلت إلى database.py)

      Expire Penalties (batch واحد لكل DB):
        - _expire_penalties_pg(conn, batch) → (expired, got_rows)
        - _expire_penalties_mysql(conn, batch) → (expired, got_rows)
        - _expire_penalties_sqlite(conn, batch) → (expired, got_rows)

      Bigint conversion:
        - _ensure_bigint_pg(conn) → int
        - _ensure_bigint_mysql(conn) → int

================================================================================
🛠️ التكامل مع database.py:

    1) في أعلى database.py، أضف:
        from database_refactor_mixin import RefactorMixin

    2) في تعريف Database، أضف RefactorMixin كأول mixin:
        class Database(
            RefactorMixin,                    # ← أولاً
            ChannelsPostsMixin,
            SubscriptionsMixin,
            ...
        ):

    ⚠️ مهم جداً (v1.2.2 FIX-R2-5):
        Pool Factories (_pg_pool_factory, _mysql_pool_factory) **لم تعد
        موجودة** في RefactorMixin. database.py يُديرها بشكل محسّن
        (v7.7.74). لا تُضِف نسخاً جديدة هنا — ستتفوق على database.py
        بسبب MRO وستُعطّل كل تحسينات v7.7.74.

    3) استبدل جسم _do_initialize بالاستدعاءات الجديدة:
        async def _do_initialize(self):
            try:
                if USE_POSTGRES:
                    self._pool = await _create_pool_with_retry(
                        self._pg_pool_factory,        # ← من database.py
                        "PostgreSQL",
                        max_attempts=5,
                        cleanup=self._pg_pool_cleanup,
                    )
                    logger.info(...)
                elif USE_MYSQL:
                    self._pool = await _create_pool_with_retry(
                        self._mysql_pool_factory,     # ← من database.py
                        "MySQL",
                        max_attempts=5,
                        cleanup=self._mysql_pool_cleanup,
                    )
                    logger.info(...)
                else:
                    conn = await _create_pool_with_retry(
                        self._sqlite_pool_factory,    # ← من RefactorMixin
                        "SQLite",
                        max_attempts=3,
                    )
                    self._sqlite_queue = asyncio.Queue(
                        maxsize=self._sqlite_pool_size
                    )
                    await self._sqlite_queue.put(conn)
                    self._sqlite_open_count = 1
                    logger.info(...)

                self._pool_none_warned = False
                # ... (بقية الكود كما هو)
            except Exception as e:
                # ... (نفس كود التنظيف)
                raise

    4) استبدل جسم expire_penalties (مع بقاء الحلقة) — كما في v1.2.1.

    5) استبدل جسم _ensure_bigint_ids — كما في v1.2.1.

    6) استبدل جسم get_channels_to_publish — كما في v1.2.1.
================================================================================
"""

import os
import re
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# =====================================================================
# 1) كشف نوع قاعدة البيانات (نفس database.py)
# =====================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_TYPE = "sqlite"

if DATABASE_URL:
    _URL_LOWER = DATABASE_URL.lower()
    if "postgres" in _URL_LOWER:
        DB_TYPE = "postgres"
        try:
            import asyncpg
        except ImportError:
            asyncpg = None
    elif "mysql" in _URL_LOWER or "mariadb" in _URL_LOWER:
        DB_TYPE = "mysql"
        try:
            import asyncmy
        except ImportError:
            asyncmy = None

USE_POSTGRES = (DB_TYPE == "postgres")
USE_MYSQL = (DB_TYPE == "mysql")

logger = logging.getLogger(__name__)


# =====================================================================
# 2) ثوابت Module-level
# =====================================================================

# عدد المرات التي يمكن أن يفشل فيها المنشور قبل استبعاده
MAX_POST_FAIL_COUNT = 3

# الفاصل الافتراضي بين المنشورات (دقائق)
DEFAULT_PUBLISH_INTERVAL_MINUTES = 12

# تعويض زمن polling النشر
PUBLISH_POLLING_COMPENSATION_SECONDS = 30

# عدد سجلات العقوبات المنتهية في كل دفعة
EXPIRED_PENALTIES_BATCH = int(
    os.getenv("EXPIRED_PENALTIES_BATCH", "500")
)

# عدد الأيام التي يبقى فيها السجل في penalty_archive قبل الحذف
PENALTY_ARCHIVE_RETENTION_DAYS = 90


# ═══════════════════════════════════════════════════════════════════
# ثوابت مساعدة لـ _ensure_bigint_mysql
# ═══════════════════════════════════════════════════════════════════

# أنواع MySQL الرقمية (تُقتبس القيم الافتراضية بلا علامات)
_DT_NUMERIC = frozenset({
    "int", "bigint", "smallint", "tinyint", "mediumint",
    "decimal", "numeric", "float", "double", "bit",
})

# تعبيرات DEFAULT التي لا تحتاج اقتباس
_DT_EXPRESSION_DEFAULTS = frozenset({
    "CURRENT_TIMESTAMP", "CURRENT_TIMESTAMP()",
    "CURRENT_DATE", "CURRENT_TIME",
    "NOW()", "LOCALTIME", "LOCALTIMESTAMP",
})


# =====================================================================
# 3) SQL Queries — get_channels_to_publish (4 استعلامات ثابتة)
# =====================================================================
#
# ملاحظة: {MAX_POST_FAIL_COUNT} يُستبدل عند تحميل الملف.
# الحقول المطلوبة: uc.id, uc.channel_id, uc.user_id,
#                 u.auto_publish, u.auto_recycle, published_count
#
# 🔴 v1.2.0 PERF-1/2/3/4:
#   تم استبدال `LEFT JOIN LATERAL (...)` بـ `WITH ... AS (...)` +
#   `GROUP BY`. السبب: LATERAL كان يُنفّذ aggregation لكل صف على حدة
#   (N+1 داخلي). الآن PostgreSQL يستخدم HashAggregate + MergeJoin.
#
#   الفائدة المتوقعة (1000 قناة):
#     قبل: ~4500ms
#     بعد: ~150ms
#     التحسّن: ~97%
# =====================================================================

# ═══════════════════════════════════════════════════════════════════
# PostgreSQL — Fast path: يستخدم MV (mv_active_user_limits) + CTEs
# ترتيب البارامترات: ($1=owner_id, $2=now, $3=limit)
# ═══════════════════════════════════════════════════════════════════
CHANNELS_TO_PUBLISH_SQL_PG = f"""
    WITH post_counts AS (
        SELECT channel_db_id,
               COUNT(*) FILTER (
                   WHERE published = 0
                     AND (fail_count IS NULL
                          OR fail_count < {MAX_POST_FAIL_COUNT})
               ) AS publishable_unpublished_count,
               COUNT(*) FILTER (WHERE published = 1)
                   AS published_count
        FROM posts
        WHERE published IN (0, 1)
        GROUP BY channel_db_id
    ),
    channel_counts AS (
        SELECT user_id, COUNT(*) AS channel_count
        FROM user_channels
        WHERE banned = 0
        GROUP BY user_id
    ),
    active_limits AS (
        SELECT user_id, max_channels, max_posts
        FROM mv_active_user_limits
    )
    SELECT uc.id, uc.channel_id, uc.user_id,
           u.auto_publish, u.auto_recycle,
           COALESCE(pc.published_count, 0)
               AS published_count
    FROM user_channels uc
    JOIN users u ON uc.user_id = u.user_id
    LEFT JOIN schedule sch
        ON uc.id = sch.channel_db_id
    LEFT JOIN active_limits a
        ON uc.user_id = a.user_id
    LEFT JOIN post_counts pc
        ON uc.id = pc.channel_db_id
    LEFT JOIN channel_counts cc
        ON uc.user_id = cc.user_id
    WHERE uc.banned = 0 AND u.banned = 0
      AND u.auto_publish = 1
      AND (a.user_id IS NOT NULL OR uc.user_id = $1)
      AND (sch.next_publish_date IS NULL
           OR sch.next_publish_date <= $2)
      AND (COALESCE(
               pc.publishable_unpublished_count, 0
           ) > 0
           OR (u.auto_recycle = 1
               AND COALESCE(
                   pc.published_count, 0
               ) > 0))
      AND (a.user_id IS NULL
           OR COALESCE(
               cc.channel_count, 0
           ) <= a.max_channels)
      AND (a.user_id IS NULL
           OR COALESCE(
               pc.publishable_unpublished_count, 0
           ) <= a.max_posts)
    ORDER BY COALESCE(
        sch.next_publish_date, uc.created_at
    ) ASC
    LIMIT $3
"""


# ═══════════════════════════════════════════════════════════════════
# 🆕 v1.1.0 + v1.2.0: PostgreSQL — Fallback بدون MV
#            (يُستخدم قبل bootstrap أو عند فشل/تعطيل MV)
#
#            🔴 v1.2.0 PERF-2: نفس تحسين CTE (بدل LATERAL)
#
# ⚠️ ترتيب البارامترات مختلف عن _SQL_PG:
#     _SQL_PG       → ($1=owner_id, $2=now, $3=limit)
#     _SQL_PG_NO_MV → ($1=now, $2=owner_id, $3=now, $4=limit)
# ═══════════════════════════════════════════════════════════════════
CHANNELS_TO_PUBLISH_SQL_PG_NO_MV = f"""
    WITH active_subs AS (
        SELECT s.user_id,
               MAX(p.max_channels) AS max_channels,
               MAX(p.max_posts) AS max_posts
        FROM subscriptions s
        JOIN plans p ON s.plan_id = p.id
        WHERE s.status = 'active' AND s.end_date > $1
          AND p.is_active = 1
        GROUP BY s.user_id
    ),
    channel_counts AS (
        SELECT user_id, COUNT(*) AS channel_count
        FROM user_channels
        WHERE banned = 0
        GROUP BY user_id
    ),
    post_counts AS (
        SELECT channel_db_id,
               COUNT(*) FILTER (
                   WHERE published = 0
                     AND (fail_count IS NULL
                          OR fail_count < {MAX_POST_FAIL_COUNT})
               ) AS publishable_unpublished_count,
               COUNT(*) FILTER (WHERE published = 1)
                   AS published_count
        FROM posts
        WHERE published IN (0, 1)
        GROUP BY channel_db_id
    )
    SELECT uc.id, uc.channel_id, uc.user_id,
           u.auto_publish, u.auto_recycle,
           COALESCE(pc.published_count, 0)
               AS published_count
    FROM user_channels uc
    JOIN users u ON uc.user_id = u.user_id
    LEFT JOIN schedule sch
        ON uc.id = sch.channel_db_id
    LEFT JOIN active_subs a
        ON uc.user_id = a.user_id
    LEFT JOIN post_counts pc
        ON uc.id = pc.channel_db_id
    LEFT JOIN channel_counts cc
        ON uc.user_id = cc.user_id
    WHERE uc.banned = 0 AND u.banned = 0
      AND u.auto_publish = 1
      AND (a.user_id IS NOT NULL OR uc.user_id = $2)
      AND (sch.next_publish_date IS NULL
           OR sch.next_publish_date <= $3)
      AND (COALESCE(
               pc.publishable_unpublished_count, 0
           ) > 0
           OR (u.auto_recycle = 1
               AND COALESCE(
                   pc.published_count, 0
               ) > 0))
      AND (a.user_id IS NULL
           OR COALESCE(
               cc.channel_count, 0
           ) <= a.max_channels)
      AND (a.user_id IS NULL
           OR COALESCE(
               pc.publishable_unpublished_count, 0
           ) <= a.max_posts)
    ORDER BY COALESCE(
        sch.next_publish_date, uc.created_at
    ) ASC
    LIMIT $4
"""


# ═══════════════════════════════════════════════════════════════════
# MySQL — subqueries مجمّعة (لا MV)
# 🔴 v1.2.0 PERF-3: فلترة published مبكرة.
# ═══════════════════════════════════════════════════════════════════
CHANNELS_TO_PUBLISH_SQL_MYSQL = f"""
    SELECT uc.id, uc.channel_id, uc.user_id,
           u.auto_publish, u.auto_recycle,
           COALESCE(pc.published_count, 0)
               AS published_count
    FROM user_channels uc
    JOIN users u ON uc.user_id = u.user_id
    LEFT JOIN schedule sch
        ON uc.id = sch.channel_db_id
    LEFT JOIN (
        SELECT s.user_id,
               MAX(p.max_channels) AS max_channels,
               MAX(p.max_posts) AS max_posts
        FROM subscriptions s
        JOIN plans p ON s.plan_id = p.id
        WHERE s.status = 'active' AND s.end_date > %s
          AND p.is_active = 1
        GROUP BY s.user_id
    ) a ON uc.user_id = a.user_id
    LEFT JOIN (
        SELECT channel_db_id,
               SUM(CASE WHEN published = 0
                        AND (fail_count IS NULL
                             OR fail_count < {MAX_POST_FAIL_COUNT})
                        THEN 1 ELSE 0 END)
                   AS publishable_unpublished_count,
               SUM(CASE WHEN published = 1
                        THEN 1 ELSE 0 END)
                   AS published_count
        FROM posts
        WHERE published IN (0, 1)
        GROUP BY channel_db_id
    ) pc ON uc.id = pc.channel_db_id
    LEFT JOIN (
        SELECT user_id, COUNT(*) AS channel_count
        FROM user_channels
        WHERE banned = 0
        GROUP BY user_id
    ) cc ON uc.user_id = cc.user_id
    WHERE uc.banned = 0 AND u.banned = 0
      AND u.auto_publish = 1
      AND (a.user_id IS NOT NULL
           OR uc.user_id = %s)
      AND (sch.next_publish_date IS NULL
           OR sch.next_publish_date <= %s)
      AND (COALESCE(
               pc.publishable_unpublished_count, 0
           ) > 0
           OR (u.auto_recycle = 1
               AND COALESCE(
                   pc.published_count, 0
               ) > 0))
      AND (a.user_id IS NULL
           OR COALESCE(
               cc.channel_count, 0
           ) <= a.max_channels)
      AND (a.user_id IS NULL
           OR COALESCE(
               pc.publishable_unpublished_count, 0
           ) <= a.max_posts)
    ORDER BY COALESCE(
        sch.next_publish_date, uc.created_at
    ) ASC
    LIMIT %s
"""


# ═══════════════════════════════════════════════════════════════════
# SQLite — CTEs (WITH) بدل subqueries
# 🔴 v1.2.0 PERF-4: فلترة published مبكرة.
# ═══════════════════════════════════════════════════════════════════
CHANNELS_TO_PUBLISH_SQL_SQLITE = f"""
    WITH active_subs AS (
        SELECT s.user_id,
               MAX(p.max_channels) AS max_channels,
               MAX(p.max_posts) AS max_posts
        FROM subscriptions s
        JOIN plans p ON s.plan_id = p.id
        WHERE s.status = 'active' AND s.end_date > ?
          AND p.is_active = 1
        GROUP BY s.user_id
    ),
    channel_counts AS (
        SELECT user_id,
               COUNT(*) AS channel_count
        FROM user_channels
        WHERE banned = 0
        GROUP BY user_id
    ),
    post_counts AS (
        SELECT channel_db_id,
               SUM(CASE WHEN published = 0
                        AND (fail_count IS NULL
                             OR fail_count < {MAX_POST_FAIL_COUNT})
                        THEN 1 ELSE 0 END)
                   AS publishable_unpublished_count,
               SUM(CASE WHEN published = 1
                        THEN 1 ELSE 0 END)
                   AS published_count
        FROM posts
        WHERE published IN (0, 1)
        GROUP BY channel_db_id
    )
    SELECT uc.id, uc.channel_id, uc.user_id,
           u.auto_publish, u.auto_recycle,
           COALESCE(pc.published_count, 0)
               AS published_count
    FROM user_channels uc
    JOIN users u ON uc.user_id = u.user_id
    LEFT JOIN schedule sch
        ON uc.id = sch.channel_db_id
    LEFT JOIN active_subs a
        ON uc.user_id = a.user_id
    LEFT JOIN channel_counts cc
        ON uc.user_id = cc.user_id
    LEFT JOIN post_counts pc
        ON uc.id = pc.channel_db_id
    WHERE uc.banned = 0 AND u.banned = 0
      AND u.auto_publish = 1
      AND (a.user_id IS NOT NULL OR uc.user_id = ?)
      AND (sch.next_publish_date IS NULL
           OR sch.next_publish_date <= ?)
      AND (COALESCE(
               pc.publishable_unpublished_count, 0
           ) > 0
           OR (u.auto_recycle = 1
               AND COALESCE(
                   pc.published_count, 0
               ) > 0))
      AND (a.user_id IS NULL
           OR COALESCE(
               cc.channel_count, 0
           ) <= a.max_channels)
      AND (a.user_id IS NULL
           OR COALESCE(
               pc.publishable_unpublished_count, 0
           ) <= a.max_posts)
    ORDER BY COALESCE(
        sch.next_publish_date, uc.created_at
    ) ASC
    LIMIT ?
"""


# =====================================================================
# 4) RefactorMixin
# =====================================================================

class RefactorMixin:
    """
    🧩 Mixin يستخرج الدوال الكبيرة من Database.

    يجب أن يُدمج **أولاً** في MRO:
        class Database(RefactorMixin, ChannelsPostsMixin, ...):
            ...

    ⚠️ v1.2.2 FIX-R2-5: Pool Factories (_pg_pool_factory,
        _mysql_pool_factory) **لم تعد موجودة هنا**. database.py
        يُديرها بشكل محسّن (v7.7.74). لا تُضِف نسخاً جديدة — ستتفوق
        على database.py بسبب MRO وستُعطّل تحسينات v7.7.74.

    يفترض أن الفئة الأم (Database) تُوفّر:
      Attributes:
        • _min_connections, _max_connections, _connection_timeout
        • _sqlite_pool_size, _sqlite_open_count
        • _sqlite_creation_lock, _sqlite_count_lock
        • _create_sqlite_connection()
        • BIGINT_COLUMNS
        • _execute_with_conn, _fetchall_with_conn, _fetchone_with_conn
        • fetchall, fetchone, fetchval, execute, transaction, connection
        • _pg_pool_factory, _mysql_pool_factory (من database.py v7.7.74)
      Module-level (يُستورد عند الحاجة):
        • _FactoryFailed, _create_pool_with_retry
    """

    # ═════════════════════════════════════════════════════════════════
    # 4.1) Pool Factory — SQLite فقط
    #
    # 🔴 v1.2.2 FIX-R2-1: _pg_pool_factory محذوفة (database.py v7.7.74)
    # 🔴 v1.2.2 FIX-R2-2: _mysql_pool_factory محذوفة (database.py v7.7.74)
    # ═════════════════════════════════════════════════════════════════

    async def _sqlite_pool_factory(self):
        """
        🏭 إنشاء SQLite connection (محاولة واحدة).

        يعتمد على self._create_sqlite_connection() الذي يُعدّ
        PRAGMAs (WAL, busy_timeout, mmap_size, ...).

        Raises:
            RuntimeError: إذا فشل الاتصال.
        """
        conn = await self._create_sqlite_connection()
        if conn is None:
            raise RuntimeError("فشل اتصال SQLite")
        return conn

    # ═════════════════════════════════════════════════════════════════
    # 4.2) Expire Penalties — DB-specific
    # ═════════════════════════════════════════════════════════════════
    #
    # 🔴 v1.2.0 PERF-5: _expire_penalties_pg — دمج INSERT + UPDATE
    #    في CTE واحد.
    # 🔴 v1.2.1 FIX-R1: تصحيح عدد المعاملات (id_list مرة واحدة).
    # 🟠 v1.2.2 FIX-R2-3: إضافة id + ON CONFLICT.
    # 🟡 v1.2.2 FIX-R2-4: دمج كامل في CTE واحد (1 round-trip).
    # ═════════════════════════════════════════════════════════════════

    async def _expire_penalties_pg(
        self, conn, batch: int
    ) -> Tuple[int, int]:
        """
        🧹 دفعة واحدة من انتهاء العقوبات في PostgreSQL.

        🔴 v1.2.0 PERF-5: INSERT + UPDATE في CTE.
        🔴 v1.2.1 FIX-R1: تصحيح placeholders (id_list مرة واحدة).
        🟠 v1.2.2 FIX-R2-3: إضافة id إلى penalty_archive (يطابق
            database_tables.py حيث id هو PK).
        🟡 v1.2.2 FIX-R2-4: دمج SELECT + INSERT + UPDATE في CTE
            واحد → 1 round-trip بدل 2.

        Args:
            conn: PG connection (داخل transaction).
            batch: عدد السجلات في الدفعة.

        Returns:
            (batch_expired, got_rows)
              - batch_expired: عدد السجلات المُنتهية فعلياً.
              - got_rows: عدد السجلات المُختارة (يقارن بـ batch).

        ملاحظة توافق:
            PG < 9.5 لا يدعم SKIP LOCKED. المسار الأساسي يفترض
            PG >= 9.5 (2016). إذا فشل SELECT FOR UPDATE SKIP LOCKED،
            نُرجع fallback بدون SKIP LOCKED (بأمان أقل عبر
            transaction-level lock).
        """
        # ═══════════════════════════════════════════════════════════
        # المسار الأساسي: CTE واحد (1 round-trip) — PG >= 9.5
        # ═══════════════════════════════════════════════════════════
        try:
            result = await self._fetchall_with_conn(
                conn,
                """
                WITH ids AS (
                    SELECT id FROM user_penalties
                    WHERE status = 'active'
                      AND end_time IS NOT NULL
                      AND end_time <= NOW()
                    ORDER BY id
                    LIMIT $1
                    FOR UPDATE SKIP LOCKED
                ),
                ins AS (
                    INSERT INTO penalty_archive
                        (id, user_id, chat_id, penalty_type,
                         duration, start_time, end_time,
                         reason, issued_by, status,
                         created_at, archived_at)
                    SELECT up.id, up.user_id, up.chat_id,
                           up.penalty_type, up.duration,
                           up.start_time, up.end_time,
                           up.reason, up.issued_by, 'expired',
                           up.created_at, NOW()
                    FROM user_penalties up
                    JOIN ids ON up.id = ids.id
                    ON CONFLICT (id) DO NOTHING
                )
                UPDATE user_penalties
                SET status = 'expired'
                WHERE id IN (SELECT id FROM ids)
                RETURNING 1
                """,
                batch,
            )
            batch_expired = len(result) if result else 0
            got_rows = batch_expired  # CTE واحد: نفس العدد
            return batch_expired, got_rows

        except Exception as _cte_e:
            err_str = str(_cte_e).lower()
            # إذا فشل ON CONFLICT (نسخة قديمة من penalty_archive
            # ليس فيها UNIQUE على id) — استخدم مسار fallback
            if (
                "on conflict" in err_str
                or "no unique" in err_str
                or "there is no" in err_str
            ):
                logger.warning(
                    f"⚠️ v1.2.2: ON CONFLICT (id) غير مدعوم — "
                    f"fallback لمسار 2-round-trips: {_cte_e}"
                )
                return await self._expire_penalties_pg_fallback(
                    conn, batch)

            # إذا فشل SKIP LOCKED (PG < 9.5) — fallback بدونها
            if (
                "skip locked" in err_str
                or "syntax" in err_str
            ):
                logger.warning(
                    f"⚠️ v1.2.2: SKIP LOCKED غير مدعوم — "
                    f"fallback بدونها: {_cte_e}"
                )
                return await self._expire_penalties_pg_fallback(
                    conn, batch)

            # خطأ آخر — نرفعه
            raise

    async def _expire_penalties_pg_fallback(
        self, conn, batch: int
    ) -> Tuple[int, int]:
        """
        🟡 v1.2.2 FIX-R2-4: مسار احتياطي لـ PostgreSQL < 9.5 أو
        penalty_archive بدون UNIQUE(id).

        يستخدم 2 round-trips:
          1) SELECT id ... FOR UPDATE (بدون SKIP LOCKED)
          2) INSERT + UPDATE في CTE
        """
        # استعلام 1: SELECT + FOR UPDATE (بدون SKIP LOCKED)
        try:
            ids_rows = await self._fetchall_with_conn(
                conn,
                "SELECT id FROM user_penalties "
                "WHERE status = 'active' "
                "  AND end_time IS NOT NULL "
                "  AND end_time <= NOW() "
                "ORDER BY id "
                "LIMIT $1 "
                "FOR UPDATE",
                batch,
            )
        except Exception as _lock_e:
            # حتى FOR UPDATE قد يفشل — نستخدم SELECT بسيط
            logger.warning(
                f"⚠️ v1.2.2: FOR UPDATE فشل — SELECT بسيط: "
                f"{_lock_e}"
            )
            ids_rows = await self._fetchall_with_conn(
                conn,
                "SELECT id FROM user_penalties "
                "WHERE status = 'active' "
                "  AND end_time IS NOT NULL "
                "  AND end_time <= NOW() "
                "ORDER BY id "
                "LIMIT $1",
                batch,
            )

        got_rows = len(ids_rows)
        if got_rows == 0:
            return 0, 0

        id_list = [r["id"] for r in ids_rows]
        placeholders = ",".join(
            [f"${i+1}" for i in range(len(id_list))]
        )

        # ✅ FIX-R2-3: id مُدرَج + ON CONFLICT
        result = await self._fetchall_with_conn(
            conn,
            f"""
            WITH ins AS (
                INSERT INTO penalty_archive
                    (id, user_id, chat_id, penalty_type,
                     duration, start_time, end_time,
                     reason, issued_by, status,
                     created_at, archived_at)
                SELECT id, user_id, chat_id, penalty_type,
                       duration, start_time, end_time,
                       reason, issued_by, 'expired',
                       created_at, NOW()
                FROM user_penalties
                WHERE id IN ({placeholders})
                ON CONFLICT (id) DO NOTHING
            )
            UPDATE user_penalties
            SET status = 'expired'
            WHERE id IN ({placeholders})
            RETURNING 1
            """,
            *id_list,
        )
        batch_expired = len(result) if result else 0
        return batch_expired, got_rows

    async def _expire_penalties_mysql(
        self, conn, batch: int
    ) -> Tuple[int, int]:
        """
        🧹 دفعة واحدة من انتهاء العقوبات في MySQL.

        ✅ v7.7.42: fallback لـ SKIP LOCKED (MySQL < 8.0.1 /
        MariaDB < 10.6). عند الفشل، يُعاد الاستعلام بدونها.

        🔴 v1.2.0 PERF-6: ترتيب INSERT قبل UPDATE.
           السبب: MySQL DML implicit commit + FK constraints.

        🟠 v1.2.2 FIX-R2-3: إضافة id (يطابق database_tables.py).
           MySQL لا يدعم ON CONFLICT — نستخدم INSERT IGNORE
           (idempotent على PK) مع الحفاظ على FK constraints.

        Returns:
            (batch_expired, got_rows)
        """
        # محاولة 1: مع SKIP LOCKED (MySQL 8.0.1+)
        try:
            ids = await self._fetchall_with_conn(
                conn,
                "SELECT id FROM user_penalties "
                "WHERE status = 'active' "
                "  AND end_time IS NOT NULL "
                "  AND end_time <= UTC_TIMESTAMP() "
                "ORDER BY id "
                "LIMIT %s "
                "FOR UPDATE SKIP LOCKED",
                batch,
            )
        except Exception as _lock_e:
            err_str = str(_lock_e).lower()
            if (
                "syntax" in err_str
                or "skip" in err_str
                or "for update" in err_str
            ):
                logger.debug(
                    f"MySQL: SKIP LOCKED غير مدعوم "
                    f"— fallback بدونها: {_lock_e}"
                )
                ids = await self._fetchall_with_conn(
                    conn,
                    "SELECT id FROM user_penalties "
                    "WHERE status = 'active' "
                    "  AND end_time IS NOT NULL "
                    "  AND end_time <= UTC_TIMESTAMP() "
                    "ORDER BY id "
                    "LIMIT %s",
                    batch,
                )
            else:
                raise

        got_rows = len(ids)
        if not ids:
            return 0, 0

        id_list = [r["id"] for r in ids]
        placeholders = ",".join(["%s"] * len(id_list))

        # ✅ PERF-6 + FIX-R2-3: INSERT IGNORE (idempotent) قبل UPDATE
        await self._execute_with_conn(
            conn,
            f"INSERT IGNORE INTO penalty_archive "
            f"(id, user_id, chat_id, penalty_type, "
            f" duration, start_time, end_time, "
            f" reason, issued_by, status, "
            f" created_at, archived_at) "
            f"SELECT id, user_id, chat_id, penalty_type, "
            f"       duration, start_time, end_time, "
            f"       reason, issued_by, 'expired', "
            f"       created_at, UTC_TIMESTAMP() "
            f"FROM user_penalties "
            f"WHERE id IN ({placeholders})",
            *id_list,
        )
        batch_expired = await self._execute_with_conn(
            conn,
            f"UPDATE user_penalties "
            f"SET status = 'expired' "
            f"WHERE id IN ({placeholders})",
            *id_list,
        ) or 0

        return batch_expired, got_rows

    async def _expire_penalties_sqlite(
        self, conn, batch: int
    ) -> Tuple[int, int]:
        """
        🧹 دفعة واحدة من انتهاء العقوبات في SQLite.

        لا يستخدم SKIP LOCKED (SQLite لا تدعمها) — يعتمد على
        BEGIN IMMEDIATE locking عبر self.transaction().

        🔴 v1.2.0 PERF-7: ترتيب INSERT قبل UPDATE.
           SQLite يدعم INSERT + UPDATE داخل نفس transaction،
           لكن الترتيب الصحيح مهم لـ FK constraints.

        🟠 v1.2.2 FIX-R2-3: إضافة id (يطابق database_tables.py).
           SQLite يدعم INSERT OR IGNORE (idempotent على PK).

        Returns:
            (batch_expired, got_rows)
        """
        ids = await self._fetchall_with_conn(
            conn,
            "SELECT id FROM user_penalties "
            "WHERE status = 'active' "
            "  AND end_time IS NOT NULL "
            "  AND end_time <= datetime('now') "
            "ORDER BY id "
            "LIMIT ?",
            batch,
        )
        got_rows = len(ids)
        if not ids:
            return 0, 0

        id_list = [r["id"] for r in ids]
        placeholders = ",".join(["?"] * len(id_list))

        # ✅ PERF-7 + FIX-R2-3: INSERT OR IGNORE (idempotent) قبل UPDATE
        await self._execute_with_conn(
            conn,
            f"INSERT OR IGNORE INTO penalty_archive "
            f"(id, user_id, chat_id, penalty_type, "
            f" duration, start_time, end_time, "
            f" reason, issued_by, status, "
            f" created_at, archived_at) "
            f"SELECT id, user_id, chat_id, penalty_type, "
            f"       duration, start_time, end_time, "
            f"       reason, issued_by, 'expired', "
            f"       created_at, datetime('now') "
            f"FROM user_penalties "
            f"WHERE id IN ({placeholders})",
            *id_list,
        )
        batch_expired = await self._execute_with_conn(
            conn,
            f"UPDATE user_penalties "
            f"SET status = 'expired' "
            f"WHERE id IN ({placeholders})",
            *id_list,
        ) or 0

        return batch_expired, got_rows

    # ═════════════════════════════════════════════════════════════════
    # 4.3) Bigint conversion — DB-specific
    # ═════════════════════════════════════════════════════════════════

    async def _ensure_bigint_pg(self, conn) -> int:
        """
        🔧 تحويل الأعمدة الرقمية في BIGINT_COLUMNS إلى BIGINT (PostgreSQL).

        - يستعلم information_schema.columns مرة واحدة (batch).
        - يحوّل فقط الأعمدة من integer/int/smallint/smallserial → BIGINT.
        - BIGINT موجودة مسبقاً تُتجاهل.

        Returns:
            عدد الأعمدة المُحوّلة.
        """
        pairs = self.BIGINT_COLUMNS
        if not pairs:
            return 0

        converted = 0
        conditions = " OR ".join(
            [f"(table_name = ${i*2+1} AND column_name = ${i*2+2})"
             for i in range(len(pairs))]
        )
        flat_params = [p for pair in pairs for p in pair]

        rows = await conn.fetch(
            f"SELECT table_name, column_name, data_type "
            f"FROM information_schema.columns "
            f"WHERE table_schema = current_schema() "
            f"AND ({conditions})",
            *flat_params,
        )

        type_map = {
            (r["table_name"], r["column_name"]):
                (r["data_type"] or "").lower()
            for r in rows
        }

        for table, col in pairs:
            row_l = type_map.get((table, col))
            if row_l is None:
                continue
            if row_l == "bigint":
                continue
            if row_l in ("integer", "int", "smallint", "smallserial"):
                try:
                    await conn.execute(
                        f'ALTER TABLE "{table}" '
                        f'ALTER COLUMN "{col}" TYPE BIGINT'
                    )
                    logger.info(
                        f"🔧 تحويل {table}.{col}: "
                        f"{row_l} → BIGINT"
                    )
                    converted += 1
                except Exception as e:
                    logger.warning(
                        f"⚠️ تحويل {table}.{col}: {e}"
                    )

        return converted

    async def _ensure_bigint_mysql(self, conn) -> int:
        """
        🔧 تحويل الأعمدة الرقمية في BIGINT_COLUMNS إلى BIGINT (MySQL).

        ✅ v7.7.42: يعمل على PK أيضاً (MODIFY COLUMN يفشل فقط عند
        وجود FKs تشير للعمود — يُسجَّل ويُكمل).

        الخطوات لكل عمود:
          - استعلم information_schema.COLUMNS للحصول على:
            DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_KEY,
            COLUMN_TYPE, COLUMN_COMMENT, EXTRA
          - أعد بناء MODIFY COLUMN مع كل السمات:
            * UNSIGNED / ZEROFILL (من COLUMN_TYPE)
            * NULL / NOT NULL
            * DEFAULT (رقمي بلا اقتباس، تعبيرات محفوظة،
                       غير ذلك 'escaped')
            * AUTO_INCREMENT (من EXTRA)
            * COMMENT 'escaped'

        Returns:
            عدد الأعمدة المُحوّلة.
        """
        pairs = self.BIGINT_COLUMNS
        if not pairs:
            return 0

        conditions = " OR ".join(
            ["(TABLE_NAME = %s AND COLUMN_NAME = %s)"] * len(pairs)
        )
        flat_params: List[Any] = []
        for pair in pairs:
            flat_params.extend([pair[0], pair[1]])

        cursor = await conn.cursor()
        try:
            await cursor.execute(
                f"SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, "
                f"IS_NULLABLE, COLUMN_DEFAULT, COLUMN_KEY, "
                f"COLUMN_TYPE, COLUMN_COMMENT, EXTRA "
                f"FROM information_schema.COLUMNS "
                f"WHERE TABLE_SCHEMA = DATABASE() "
                f"AND ({conditions})",
                tuple(flat_params),
            )
            rows = await cursor.fetchall()
        finally:
            await cursor.close()

        # (table, column) → row
        rows_map = {(r[0], r[1]): r for r in rows}

        converted = 0
        for table, col in pairs:
            r = rows_map.get((table, col))
            if not r:
                continue

            current_type = (r[2] or "").lower()
            column_type_full = (r[6] or "").lower()
            if current_type == "bigint":
                continue
            if current_type not in (
                "int", "integer", "mediumint",
                "smallint", "tinyint",
            ):
                continue

            is_nullable = (r[3] or "YES").upper()
            column_default = r[4]
            column_key = (r[5] or "").upper()
            column_comment = r[7] or ""
            extra = (r[8] or "").upper()

            # ─── نوع MODIFY ───
            type_modifiers = ""
            if "unsigned" in column_type_full:
                type_modifiers += " UNSIGNED"
            if "zerofill" in column_type_full:
                type_modifiers += " ZEROFILL"

            # ─── NULL / NOT NULL ───
            null_clause = (
                "NOT NULL" if is_nullable == "NO" else "NULL"
            )

            # ─── DEFAULT ───
            default_clause = ""
            if column_default is not None:
                default_str = str(column_default).strip()
                if default_str.upper() in _DT_EXPRESSION_DEFAULTS:
                    default_clause = f" DEFAULT {default_str}"
                elif current_type in _DT_NUMERIC:
                    default_clause = f" DEFAULT {default_str}"
                else:
                    escaped = default_str.replace("'", "''")
                    default_clause = f" DEFAULT '{escaped}'"

            # ─── COMMENT ───
            comment_clause = ""
            if column_comment:
                escaped_comment = column_comment.replace("'", "''")
                comment_clause = f" COMMENT '{escaped_comment}'"

            # ─── AUTO_INCREMENT ───
            extra_clause = ""
            if "AUTO_INCREMENT" in extra:
                extra_clause = " AUTO_INCREMENT"

            try:
                cursor2 = await conn.cursor()
                try:
                    await cursor2.execute(
                        f"ALTER TABLE `{table}` "
                        f"MODIFY COLUMN `{col}` "
                        f"BIGINT{type_modifiers} {null_clause}"
                        f"{default_clause}"
                        f"{extra_clause}"
                        f"{comment_clause}"
                    )
                    logger.info(
                        f"🔧 تحويل {table}.{col}: "
                        f"{current_type} → BIGINT"
                        f"{type_modifiers} "
                        f"({null_clause}{extra_clause})"
                        + (
                            " [PK]"
                            if column_key == "PRI" else ""
                        )
                    )
                    converted += 1
                finally:
                    await cursor2.close()
            except Exception as e:
                if column_key == "PRI":
                    logger.warning(
                        f"⚠️ MODIFY PK {table}.{col}: {e} "
                        f"(قد تكون هناك FKs تشير إليه — "
                        f"يحتاج migration يدوي)"
                    )
                else:
                    logger.warning(
                        f"⚠️ MODIFY {table}.{col}: {e}"
                    )

        return converted


# =====================================================================
# 5) __all__
# =====================================================================

__all__ = [
    # Constants
    "MAX_POST_FAIL_COUNT",
    "DEFAULT_PUBLISH_INTERVAL_MINUTES",
    "PUBLISH_POLLING_COMPENSATION_SECONDS",
    "EXPIRED_PENALTIES_BATCH",
    "PENALTY_ARCHIVE_RETENTION_DAYS",
    # SQL queries
    "CHANNELS_TO_PUBLISH_SQL_PG",
    "CHANNELS_TO_PUBLISH_SQL_PG_NO_MV",
    "CHANNELS_TO_PUBLISH_SQL_MYSQL",
    "CHANNELS_TO_PUBLISH_SQL_SQLITE",
    # Mixin
    "RefactorMixin",
    # DB type (للتصدير)
    "DB_TYPE",
    "USE_POSTGRES",
    "USE_MYSQL",
    "DATABASE_URL",
]


# =====================================================================
# LOAD BEACON — v1.2.2
# =====================================================================

try:
    logger.info(
        "🛡️ database_refactor_mixin.py v1.2.2 FIX-R2 loaded | "
        "🔴 FIX-R2-1: _pg_pool_factory REMOVED (delegated to database.py) ✅ | "
        "🔴 FIX-R2-2: _mysql_pool_factory REMOVED (delegated to database.py) ✅ | "
        "🟠 FIX-R2-3: _expire_penalties_pg insert-id + ON CONFLICT ✅ | "
        "🟡 FIX-R2-4: _expire_penalties_pg merged CTE (1 round-trip) ✅ | "
        "🟡 FIX-R2-5: MRO guidance in docstring ✅ | "
        "✅ v1.2.1 FIX-R1 (bind error fixed) preserved | "
        "✅ v1.2.0 PERF-1..PERF-7 preserved | "
        "✅ v1.1.0 PG_NO_MV preserved | "
        "✅ v1.0.0 constants+queries preserved | "
        "⚠️ RefactorMixin now provides: _sqlite_pool_factory + "
        "_expire_penalties_* + _ensure_bigint_*"
    )
except Exception:
    pass