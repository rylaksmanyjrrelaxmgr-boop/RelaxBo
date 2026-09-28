#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_refactor_mixin.py - استخراج الدوال الكبيرة من database.py (v1.0.0)
================================================================================
🎯 الهدف:
    تقليل حجم database.py عبر نقل الدوال الضخمة إلى ملف منفصل، مع
    الحفاظ على نفس السلوك 100% عبر نمط Mixin.

📦 المحتوى:
    ═══ ثوابت Module-level ═══
      - MAX_POST_FAIL_COUNT
      - EXPIRED_PENALTIES_BATCH
      - PENALTY_ARCHIVE_RETENTION_DAYS
      - DEFAULT_PUBLISH_INTERVAL_MINUTES

    ═══ ثوابت SQL (get_channels_to_publish) ═══
      - CHANNELS_TO_PUBLISH_SQL_PG
      - CHANNELS_TO_PUBLISH_SQL_MYSQL
      - CHANNELS_TO_PUBLISH_SQL_SQLITE

    ═══ RefactorMixin ═══
      Pool Factories:
        - _pg_pool_factory()
        - _pg_pool_cleanup(pool)
        - _mysql_pool_factory()
        - _mysql_pool_cleanup(pool)
        - _sqlite_pool_factory()

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
            RefactorMixin,                    # ← جديد
            ChannelsPostsMixin,
            SubscriptionsMixin,
            ...
        ):

    3) استبدل جسم _do_initialize بالاستدعاءات الجديدة:
        async def _do_initialize(self):
            try:
                if USE_POSTGRES:
                    self._pool = await _create_pool_with_retry(
                        self._pg_pool_factory,
                        "PostgreSQL",
                        max_attempts=5,
                        cleanup=self._pg_pool_cleanup,
                    )
                    logger.info(...)

                elif USE_MYSQL:
                    self._pool = await _create_pool_with_retry(
                        self._mysql_pool_factory,
                        "MySQL",
                        max_attempts=5,
                        cleanup=self._mysql_pool_cleanup,
                    )
                    logger.info(...)

                else:
                    conn = await _create_pool_with_retry(
                        self._sqlite_pool_factory,
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

    4) استبدل جسم expire_penalties (مع بقاء الحلقة):
        async def expire_penalties(self) -> int:
            total_expired = 0
            BATCH = EXPIRED_PENALTIES_BATCH
            try:
                while True:
                    batch_expired = 0
                    got_rows = 0
                    async with self.transaction() as conn:
                        if USE_POSTGRES:
                            batch_expired, got_rows = (
                                await self._expire_penalties_pg(conn, BATCH)
                            )
                        elif USE_MYSQL:
                            batch_expired, got_rows = (
                                await self._expire_penalties_mysql(conn, BATCH)
                            )
                        else:
                            batch_expired, got_rows = (
                                await self._expire_penalties_sqlite(conn, BATCH)
                            )

                    total_expired += batch_expired
                    if got_rows < BATCH:
                        break
                    await asyncio.sleep(0)

                # Archive cleanup (كما في الأصل)
                try:
                    async with self.transaction() as conn:
                        if USE_POSTGRES:
                            await conn.execute(
                                f"DELETE FROM penalty_archive "
                                f"WHERE archived_at IS NOT NULL "
                                f"AND archived_at < NOW() - INTERVAL "
                                f"'{PENALTY_ARCHIVE_RETENTION_DAYS} days'"
                            )
                        elif USE_MYSQL:
                            cursor = await conn.cursor()
                            try:
                                await cursor.execute(
                                    f"DELETE FROM penalty_archive "
                                    f"WHERE archived_at IS NOT NULL "
                                    f"AND archived_at < "
                                    f"UTC_TIMESTAMP() - INTERVAL "
                                    f"{PENALTY_ARCHIVE_RETENTION_DAYS} DAY"
                                )
                            finally:
                                await cursor.close()
                        else:
                            await conn.execute(
                                f"DELETE FROM penalty_archive "
                                f"WHERE archived_at IS NOT NULL "
                                f"AND julianday('now') - "
                                f"julianday(archived_at) > "
                                f"{PENALTY_ARCHIVE_RETENTION_DAYS}"
                            )
                except Exception as ce:
                    logger.warning(f"⚠️ تنظيف الأرشيف: {ce}")
                return total_expired
            except Exception as e:
                logger.error(f"❌ expire_penalties: {e}", exc_info=True)
                return total_expired

    5) استبدل جسم _ensure_bigint_ids:
        async def _ensure_bigint_ids(self, conn) -> int:
            if DB_TYPE == "sqlite":
                return 0
            if not self.BIGINT_COLUMNS:
                return 0
            try:
                if USE_POSTGRES:
                    converted = await self._ensure_bigint_pg(conn)
                elif USE_MYSQL:
                    converted = await self._ensure_bigint_mysql(conn)
                else:
                    converted = 0
            except Exception as e:
                logger.warning(f"⚠️ _ensure_bigint_ids: {e}")
                converted = 0
            if converted > 0:
                logger.info(f"✅ تحويل {converted} عمود إلى BIGINT")
            return converted

    6) استبدل جسم get_channels_to_publish بالاستعلامات الثابتة:
        async def get_channels_to_publish(self, limit: int = 20) -> List[Dict]:
            from database_refactor_mixin import (
                CHANNELS_TO_PUBLISH_SQL_PG,
                CHANNELS_TO_PUBLISH_SQL_MYSQL,
                CHANNELS_TO_PUBLISH_SQL_SQLITE,
            )
            now = TimeUtils.utc_now()
            owner_id = getattr(CONFIG, "PRIMARY_OWNER_ID", 0) or 0

            if USE_POSTGRES and self._mv_available:
                now_mono = time.monotonic()
                if (now_mono - self._mv_last_refresh_mono
                        >= self._mv_refresh_cooldown):
                    try:
                        self._spawn_bg_task(self._maybe_refresh_mv())
                    except Exception as e:
                        logger.debug(f"MV refresh spawn: {e}")

            if USE_POSTGRES and self._mv_available:
                return await self.fetchall(
                    CHANNELS_TO_PUBLISH_SQL_PG,
                    (owner_id, now, limit),
                )
            elif USE_MYSQL:
                now_str = now.strftime("%Y-%m-%d %H:%M:%S")
                return await self.fetchall(
                    CHANNELS_TO_PUBLISH_SQL_MYSQL,
                    (now_str, owner_id, now_str, limit),
                )
            else:
                return await self.fetchall(
                    CHANNELS_TO_PUBLISH_SQL_SQLITE,
                    (now, owner_id, now, limit),
                )
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
# 3) SQL Queries — get_channels_to_publish (3 استعلامات ثابتة)
# =====================================================================
#
# ملاحظة: {MAX_POST_FAIL_COUNT} يُستبدل عند تحميل الملف.
# الحقول المطلوبة: uc.id, uc.channel_id, uc.user_id,
#                 u.auto_publish, u.auto_recycle, published_count
# =====================================================================

# ═══════════════════════════════════════════════════════════════════
# PostgreSQL — يستخدم MV (mv_active_user_limits) + LATERAL
# ═══════════════════════════════════════════════════════════════════
CHANNELS_TO_PUBLISH_SQL_PG = f"""
    SELECT uc.id, uc.channel_id, uc.user_id,
           u.auto_publish, u.auto_recycle,
           COALESCE(pc.published_count, 0)
               AS published_count
    FROM user_channels uc
    JOIN users u ON uc.user_id = u.user_id
    LEFT JOIN schedule sch
        ON uc.id = sch.channel_db_id
    LEFT JOIN mv_active_user_limits a
        ON uc.user_id = a.user_id
    LEFT JOIN LATERAL (
        SELECT
            COUNT(*) FILTER (
                WHERE p.published = 0
                  AND (p.fail_count IS NULL
                       OR p.fail_count < {MAX_POST_FAIL_COUNT})
            ) AS publishable_unpublished_count,
            COUNT(*) FILTER (
                WHERE p.published = 1
            ) AS published_count
        FROM posts p
        WHERE p.channel_db_id = uc.id
    ) pc ON TRUE
    LEFT JOIN LATERAL (
        SELECT COUNT(*) AS channel_count
        FROM user_channels uc2
        WHERE uc2.user_id = uc.user_id
          AND uc2.banned = 0
    ) cc ON TRUE
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
# MySQL — subqueries مجمّعة (لا MV)
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
        SELECT user_id, COUNT(*) AS channel_count
        FROM user_channels WHERE banned = 0
        GROUP BY user_id
    ) cc ON uc.user_id = cc.user_id
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
        FROM posts GROUP BY channel_db_id
    ) pc ON uc.id = pc.channel_db_id
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
        FROM user_channels WHERE banned = 0
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
        FROM posts GROUP BY channel_db_id
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

    يفترض أن الفئة الأم (Database) تُوفّر:
      Attributes:
        • _min_connections, _max_connections, _connection_timeout
        • _sqlite_pool_size, _sqlite_open_count
        • _sqlite_creation_lock, _sqlite_count_lock
        • _create_sqlite_connection()
        • BIGINT_COLUMNS
        • _execute_with_conn, _fetchall_with_conn, _fetchone_with_conn
        • fetchall, fetchone, fetchval, execute, transaction, connection
      Module-level (يُستورد عند الحاجة):
        • _FactoryFailed, _create_pool_with_retry
    """

    # ═════════════════════════════════════════════════════════════════
    # 4.1) Pool Factories
    # ═════════════════════════════════════════════════════════════════

    async def _pg_pool_factory(self):
        """
        🏭 إنشاء PG pool (محاولة واحدة — retry في _create_pool_with_retry).

        ✅ v7.7.41 (محفوظ):
          - max_inactive_connection_lifetime=60 (بدل 0)
          - tcp_keepalives_idle=30, interval=10, count=3
          - synchronous_commit=off (المفتاح الوحيد per-session)

        Raises:
            _FactoryFailed: إذا نجح create_pool لكن اختبار SELECT 1 فشل.
                           cleanup (pool.close) يُستدعى من _create_pool_with_retry.
        """
        # lazy import لتفادي circular import
        from database import _FactoryFailed

        try:
            pool = await asyncpg.create_pool(
                dsn=DATABASE_URL,
                min_size=max(5, self._min_connections),
                max_size=self._max_connections,
                timeout=self._connection_timeout,
                command_timeout=self._connection_timeout,
                statement_cache_size=500,
                # ✅ v7.7.41: 0 → 60
                max_inactive_connection_lifetime=60,
                server_settings={
                    "application_name": "RelaxManager",
                    "statement_timeout": "30s",
                    "timezone": "UTC",
                    # المفتاح الوحيد المسموح per-session:
                    "synchronous_commit": "off",
                    # ✅ v7.7.41: TCP keepalives
                    "tcp_keepalives_idle": "30",
                    "tcp_keepalives_interval": "10",
                    "tcp_keepalives_count": "3",
                },
            )
        except asyncpg.exceptions.CantChangeRuntimeParamError as _cfg_e:
            # خطأ دائم — لا فائدة من إعادة المحاولة
            logger.error(
                f"❌ PG: server_settings غير صالح "
                f"(لا إعادة محاولة): {_cfg_e}"
            )
            raise

        # اختبار الاتصال
        try:
            async with pool.acquire() as _c:
                await _c.fetchval("SELECT 1")
        except Exception as _test_e:
            raise _FactoryFailed(
                f"PG pool اختبار فشل: {_test_e}", pool
            )
        return pool

    async def _pg_pool_cleanup(self, pool):
        """🧹 cleanup pool جزئي (يُستدعى عند فشل الاختبار)."""
        try:
            await pool.close()
        except Exception:
            pass

    async def _mysql_pool_factory(self):
        """
        🏭 إنشاء MySQL pool (محاولة واحدة).

        يستخدم asyncmy.create_pool مع:
          - pool_recycle=3600 (تجديد الاتصالات كل ساعة)
          - autocommit=False (transactions يدوية)
          - charset=utf8mb4
          - time_zone=+00:00

        Raises:
            ValueError: إذا كان DATABASE_URL غير صالح.
            _FactoryFailed: إذا نجح create_pool لكن اختبار SELECT 1 فشل.
        """
        from database import _FactoryFailed
        from urllib.parse import urlparse

        try:
            parsed = urlparse(DATABASE_URL)
            if not parsed.hostname:
                raise ValueError("no host in DATABASE_URL")
            _mysql_cfg = {
                "host": parsed.hostname,
                "port": int(parsed.port or 3306),
                "user": parsed.username or "",
                "password": parsed.password or "",
                "db": (parsed.path or "/").lstrip("/"),
            }
            if not _mysql_cfg["db"]:
                raise ValueError("no database in DATABASE_URL")
        except Exception as _pe:
            logger.error(f"❌ فشل تفكيك MySQL URL: {_pe}")
            raise ValueError(
                f"Invalid MySQL DATABASE_URL: {_pe}"
            ) from _pe

        pool = await asyncmy.create_pool(
            host=_mysql_cfg["host"],
            port=_mysql_cfg["port"],
            user=_mysql_cfg["user"],
            password=_mysql_cfg["password"],
            db=_mysql_cfg["db"],
            minsize=self._min_connections,
            maxsize=self._max_connections,
            pool_recycle=3600,
            autocommit=False,
            charset="utf8mb4",
            init_command="SET time_zone = '+00:00'",
        )

        # اختبار الاتصال
        try:
            async with pool.acquire() as _c:
                cur = await _c.cursor()
                try:
                    await cur.execute("SELECT 1")
                    await cur.fetchone()
                finally:
                    try:
                        await cur.close()
                    except Exception:
                        pass
        except Exception as _test_e:
            raise _FactoryFailed(
                f"MySQL pool اختبار فشل: {_test_e}", pool
            )
        return pool

    async def _mysql_pool_cleanup(self, pool):
        """🧹 cleanup pool جزئي لـ MySQL."""
        try:
            pool.close()
            await pool.wait_closed()
        except Exception:
            pass

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

    async def _expire_penalties_pg(
        self, conn, batch: int
    ) -> Tuple[int, int]:
        """
        🧹 دفعة واحدة من انتهاء العقوبات في PostgreSQL.

        الخطوات:
          1) SELECT id ... FOR UPDATE SKIP LOCKED  (batch)
          2) INSERT INTO penalty_archive ... SELECT ...
          3) UPDATE user_penalties SET status='expired' ...

        Args:
            conn: PG connection (داخل transaction).
            batch: عدد السجلات في الدفعة.

        Returns:
            (batch_expired, got_rows)
              - batch_expired: عدد السجلات المُنتهية فعلياً.
              - got_rows: عدد السجلات المُختارة (يقارن بـ batch لمعرفة
                          إن كانت هناك دفعة تالية).
        """
        ids = await self._fetchall_with_conn(
            conn,
            "SELECT id FROM user_penalties "
            "WHERE status = 'active' "
            "  AND end_time IS NOT NULL "
            "  AND end_time <= NOW() "
            "ORDER BY id "
            "LIMIT $1 "
            "FOR UPDATE SKIP LOCKED",
            batch,
        )
        got_rows = len(ids)
        if not ids:
            return 0, 0

        id_list = [r["id"] for r in ids]
        placeholders = ",".join(
            [f"${i+1}" for i in range(len(id_list))]
        )

        await self._execute_with_conn(
            conn,
            f"INSERT INTO penalty_archive "
            f"(user_id, chat_id, penalty_type, "
            f" duration, start_time, end_time, "
            f" reason, issued_by, status, "
            f" created_at, archived_at) "
            f"SELECT user_id, chat_id, penalty_type, "
            f"       duration, start_time, end_time, "
            f"       reason, issued_by, 'expired', "
            f"       created_at, NOW() "
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

    async def _expire_penalties_mysql(
        self, conn, batch: int
    ) -> Tuple[int, int]:
        """
        🧹 دفعة واحدة من انتهاء العقوبات في MySQL.

        ✅ v7.7.42: fallback لـ SKIP LOCKED (MySQL < 8.0.1 /
        MariaDB < 10.6). عند الفشل، يُعاد الاستعلام بدونها.

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

        await self._execute_with_conn(
            conn,
            f"INSERT INTO penalty_archive "
            f"(user_id, chat_id, penalty_type, "
            f" duration, start_time, end_time, "
            f" reason, issued_by, status, "
            f" created_at, archived_at) "
            f"SELECT user_id, chat_id, penalty_type, "
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

        لا يستخدم SKIP LOCKED (SQLite لا يدعمها) — يعتمد على
        BEGIN IMMEDIATE locking عبر self.transaction().

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

        await self._execute_with_conn(
            conn,
            f"INSERT INTO penalty_archive "
            f"(user_id, chat_id, penalty_type, "
            f" duration, start_time, end_time, "
            f" reason, issued_by, status, "
            f" created_at, archived_at) "
            f"SELECT user_id, chat_id, penalty_type, "
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