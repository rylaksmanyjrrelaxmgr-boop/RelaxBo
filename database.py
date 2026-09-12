#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
database.py - قاعدة البيانات المتكاملة للبوت (النسخة v7.5.9)
================================================================================
- الجداول والفهارس في database_tables.py (مُستوردة)
- دوال القنوات والمنشورات في database_channels_posts.py (Mixin)
- دوال الاشتراكات والباقات والإحالات في database_subscriptions.py (Mixin)
- دوال المجموعات في database_groups.py (Mixin)
- دوال التذاكر في database_tickets.py (Mixin)
- دوال المسابقات في database_contests.py (Mixin)
- دوال الإحصائيات والمشرفين في database_stats.py (Mixin)
- دوال الإعدادات العامة في database_settings.py (Mixin)
- دوال النقاط والمستويات في database_points.py (Mixin)
- دوال النسخ الاحتياطي في database_backup.py (Mixin)
- دوال التذكيرات في database_reminders.py (Mixin)

🆕 v7.3.1: إصلاح SyntaxError في set_violation_penalty
🆕 v7.3.2: إضافة مرادفات وقت الليل
🆕 v7.4.0: فصل دوال المجموعات إلى database_groups.py
🆕 v7.4.1: فصل دوال التذاكر إلى database_tickets.py
🆕 v7.4.2: فصل دوال المسابقات إلى database_contests.py
🆕 v7.4.3: فصل دوال الإحصائيات والمشرفين إلى database_stats.py
🆕 v7.4.4: فصل دوال الإعدادات العامة إلى database_settings.py
🆕 v7.4.5: فصل دوال النقاط إلى database_points.py
🆕 v7.4.6: فصل دوال النسخ الاحتياطي إلى database_backup.py
🆕 v7.4.7: فصل دوال التذكيرات إلى database_reminders.py
🆕 v7.5.2: إضافة 6 فهارس أداء + توافق MySQL للفهارس الجزئية
🆕 v7.5.3: تخطي استيراد البيانات المكررة (تحسين Cold Start ~9s)
🆕 v7.5.8: كاش has_active_subscription → /start أسرع 40x
🆕 v7.5.9: كاش get_auto_publish_status + دالة get_user_settings_batch
         (حل مشكلة الاستعلامات البطيئة 1.5-2s عند ضغط زر الإعدادات)
"""

import os
import sys
import json
import asyncio
import logging
import time
import shutil
import sqlite3
import secrets
import re
import gzip
import tempfile
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any, Union, AsyncGenerator
from contextlib import asynccontextmanager
from collections import defaultdict

# =====================================================================
# 0. كشف نوع قاعدة البيانات
# =====================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_TYPE = "sqlite"

if DATABASE_URL:
    if "postgres" in DATABASE_URL.lower() or "postgresql" in DATABASE_URL.lower():
        DB_TYPE = "postgres"
        try:
            import asyncpg
            from asyncpg import Pool, Connection
        except ImportError:
            logging.error("❌ asyncpg غير مثبت. قم بتثبيته: pip install asyncpg")
            raise
    elif "mysql" in DATABASE_URL.lower() or "mariadb" in DATABASE_URL.lower():
        DB_TYPE = "mysql"
        try:
            import asyncmy
            from asyncmy import Pool, Connection
        except ImportError:
            logging.error("❌ asyncmy غير مثبت. قم بتثبيته: pip install asyncmy")
            raise
    else:
        DB_TYPE = "sqlite"
        import aiosqlite

if DB_TYPE == "sqlite":
    import aiosqlite

USE_POSTGRES = (DB_TYPE == "postgres")
USE_MYSQL = (DB_TYPE == "mysql")

logger = logging.getLogger(__name__)
logger.info(f"📌 سيتم استخدام قاعدة البيانات: {DB_TYPE.upper()}")

# =====================================================================
# 0.1 استيراد التكوينات
# =====================================================================

try:
    from config import CONFIG, PATHS
except ImportError:
    class PATHS:
        DB = Path("data/relax.db")
        BACKUPS = Path("data/backups")
    PATHS.DB.parent.mkdir(parents=True, exist_ok=True)
    PATHS.BACKUPS.mkdir(parents=True, exist_ok=True)

    class CONFIG:
        PRIMARY_OWNER_ID = 0
        MAX_DAILY_REFERRALS = 10
        MAX_GLOBAL_BANNED_WORDS = 500

# =====================================================================
# 0.2 استيراد وحدة إنشاء الجداول
# =====================================================================

try:
    from database_tables import (
        create_tables_sqlite,
        create_tables_postgres,
        create_tables_mysql,
        CURRENT_SCHEMA_VERSION,
    )
    TABLES_MODULE_AVAILABLE = True
    logger.info("✅ تم تحميل database_tables.py")
except ImportError as e:
    logging.error(f"❌ فشل استيراد database_tables.py: {e}")
    create_tables_sqlite = None
    create_tables_postgres = None
    create_tables_mysql = None
    CURRENT_SCHEMA_VERSION = 1
    TABLES_MODULE_AVAILABLE = False

# =====================================================================
# 0.2.1 استيراد ChannelsPostsMixin (دوال القنوات + المنشورات)
# =====================================================================

try:
    from database_channels_posts import ChannelsPostsMixin
    CHANNELS_POSTS_MIXIN_AVAILABLE = True
    logger.info("✅ تم تحميل database_channels_posts.py")
except ImportError as e:
    logger.warning(f"⚠️ database_channels_posts.py غير موجود: {e}")
    ChannelsPostsMixin = object
    CHANNELS_POSTS_MIXIN_AVAILABLE = False

# =====================================================================
# 0.2.2 استيراد SubscriptionsMixin (الاشتراكات والباقات والإحالات)
# =====================================================================

try:
    from database_subscriptions import SubscriptionsMixin
    SUBSCRIPTIONS_MIXIN_AVAILABLE = True
    logger.info("✅ تم تحميل database_subscriptions.py")
except ImportError as e:
    logger.warning(f"⚠️ database_subscriptions.py غير موجود: {e}")
    SubscriptionsMixin = object
    SUBSCRIPTIONS_MIXIN_AVAILABLE = False

# =====================================================================
# 0.2.3 استيراد GroupsMixin (دوال المجموعات)
# =====================================================================

try:
    from database_groups import GroupsMixin
    GROUPS_MIXIN_AVAILABLE = True
    logger.info("✅ تم تحميل database_groups.py")
except ImportError as e:
    logger.warning(f"⚠️ database_groups.py غير موجود: {e}")
    GroupsMixin = object
    GROUPS_MIXIN_AVAILABLE = False

# =====================================================================
# 0.2.4 استيراد TicketsMixin (دوال التذاكر)
# =====================================================================

try:
    from database_tickets import TicketsMixin
    TICKETS_MIXIN_AVAILABLE = True
    logger.info("✅ تم تحميل database_tickets.py")
except ImportError as e:
    logger.warning(f"⚠️ database_tickets.py غير موجود: {e}")
    TicketsMixin = object
    TICKETS_MIXIN_AVAILABLE = False

# =====================================================================
# 0.2.5 استيراد ContestsMixin (دوال المسابقات)
# =====================================================================

try:
    from database_contests import ContestsMixin
    CONTESTS_MIXIN_AVAILABLE = True
    logger.info("✅ تم تحميل database_contests.py")
except ImportError as e:
    logger.warning(f"⚠️ database_contests.py غير موجود: {e}")
    ContestsMixin = object
    CONTESTS_MIXIN_AVAILABLE = False

# =====================================================================
# 0.2.6 استيراد StatsMixin (الإحصائيات والمشرفين)
# =====================================================================

try:
    from database_stats import StatsMixin
    STATS_MIXIN_AVAILABLE = True
    logger.info("✅ تم تحميل database_stats.py")
except ImportError as e:
    logger.warning(f"⚠️ database_stats.py غير موجود: {e}")
    StatsMixin = object
    STATS_MIXIN_AVAILABLE = False

# =====================================================================
# 0.2.7 استيراد SettingsMixin (الإعدادات العامة)
# =====================================================================

try:
    from database_settings import SettingsMixin
    SETTINGS_MIXIN_AVAILABLE = True
    logger.info("✅ تم تحميل database_settings.py")
except ImportError as e:
    logger.warning(f"⚠️ database_settings.py غير موجود: {e}")
    SettingsMixin = object
    SETTINGS_MIXIN_AVAILABLE = False

# =====================================================================
# 0.2.8 استيراد PointsMixin (النقاط والمستويات)
# =====================================================================

try:
    from database_points import PointsMixin
    POINTS_MIXIN_AVAILABLE = True
    logger.info("✅ تم تحميل database_points.py")
except ImportError as e:
    logger.warning(f"⚠️ database_points.py غير موجود: {e}")
    PointsMixin = object
    POINTS_MIXIN_AVAILABLE = False

# =====================================================================
# 0.2.9 استيراد BackupMixin (النسخ الاحتياطي)
# =====================================================================

try:
    from database_backup import BackupMixin
    BACKUP_MIXIN_AVAILABLE = True
    logger.info("✅ تم تحميل database_backup.py")
except ImportError as e:
    logger.warning(f"⚠️ database_backup.py غير موجود: {e}")
    BackupMixin = object
    BACKUP_MIXIN_AVAILABLE = False

# =====================================================================
# 0.2.10 استيراد RemindersMixin (التذكيرات)
# =====================================================================

try:
    from database_reminders import RemindersMixin
    REMINDERS_MIXIN_AVAILABLE = True
    logger.info("✅ تم تحميل database_reminders.py")
except ImportError as e:
    logger.warning(f"⚠️ database_reminders.py غير موجود: {e}")
    RemindersMixin = object
    REMINDERS_MIXIN_AVAILABLE = False

# =====================================================================
# 0.3 كاش داخلي
# =====================================================================

class InternalQueryCache:
    """كاش داخلي للاستعلامات المتكررة (مع حد أعلى)"""

    def __init__(self, ttl: int = 60, max_size: int = 10000):
        self._cache = {}
        self._ttl = ttl
        self._max_size = max_size
        self._lock = asyncio.Lock()

    async def get(self, key: str):
        async with self._lock:
            if key in self._cache:
                data, timestamp, ttl = self._cache[key]
                if time.time() - timestamp < ttl:
                    return data
                else:
                    del self._cache[key]
        return None

    async def set(self, key: str, data, ttl: int = None):
        effective_ttl = ttl if ttl is not None else self._ttl
        async with self._lock:
            if len(self._cache) >= self._max_size and key not in self._cache:
                to_remove = list(self._cache.keys())[: max(1, self._max_size // 4)]
                for k in to_remove:
                    self._cache.pop(k, None)
            self._cache[key] = (data, time.time(), effective_ttl)

    async def invalidate(self, key: str = None):
        async with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()

    async def clear(self):
        async with self._lock:
            self._cache.clear()

    async def get_size(self) -> int:
        async with self._lock:
            return len(self._cache)


internal_cache = InternalQueryCache(ttl=30, max_size=10000)

# =====================================================================
# 0.4 SimpleCache الكامل
# =====================================================================

class SimpleCache:
    """كاش داخلي كامل - يدعم كل الدوال المطلوبة"""

    def __init__(self, default_ttl: int = 60, max_size: int = 10000):
        self._cache: Dict[str, Tuple[Any, float, int]] = {}
        self._ttl = default_ttl
        self._max_size = max_size
        self._lock = asyncio.Lock()

    async def get(self, key: str):
        async with self._lock:
            if key in self._cache:
                data, ts, ttl = self._cache[key]
                if time.time() - ts < ttl:
                    return data
                del self._cache[key]
            return None

    async def set(self, key: str, data, ttl: int = None):
        effective = ttl if ttl is not None else self._ttl
        async with self._lock:
            if len(self._cache) >= self._max_size and key not in self._cache:
                to_remove = list(self._cache.keys())[: max(1, self._max_size // 4)]
                for k in to_remove:
                    self._cache.pop(k, None)
            self._cache[key] = (data, time.time(), effective)

    async def invalidate(self, key: str = None):
        async with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()

    async def clear(self):
        async with self._lock:
            self._cache.clear()

    async def has(self, key: str) -> bool:
        async with self._lock:
            if key in self._cache:
                _, ts, ttl = self._cache[key]
                if time.time() - ts < ttl:
                    return True
                del self._cache[key]
            return False

    async def get_with_ttl(self, key: str):
        async with self._lock:
            if key in self._cache:
                data, ts, ttl = self._cache[key]
                remaining = int(ttl - (time.time() - ts))
                if remaining > 0:
                    return data, remaining
                del self._cache[key]
            return None, None

    async def set_many(self, items: Dict[str, Any], ttl: int = None):
        effective = ttl if ttl is not None else self._ttl
        async with self._lock:
            now = time.time()
            for key, data in items.items():
                if len(self._cache) >= self._max_size and key not in self._cache:
                    to_remove = list(self._cache.keys())[: max(1, self._max_size // 4)]
                    for k in to_remove:
                        self._cache.pop(k, None)
                self._cache[key] = (data, now, effective)

    async def delete_many(self, keys: List[str]) -> int:
        async with self._lock:
            count = 0
            for key in keys:
                if key in self._cache:
                    del self._cache[key]
                    count += 1
            return count

    async def get_keys(self) -> List[str]:
        async with self._lock:
            return list(self._cache.keys())

    async def get_all(self) -> Dict[str, Any]:
        async with self._lock:
            return {k: v[0] for k, v in self._cache.items()}

    async def get_stats(self) -> Dict[str, Any]:
        async with self._lock:
            return {
                'size': len(self._cache),
                'max_size': self._max_size,
                'ttl': self._ttl
            }

    async def get_channel_info(self, channel_db_id: int):
        return await self.get(f"channel_info:{channel_db_id}")

    async def set_channel_info(self, channel_db_id: int, data, ttl: int = None):
        await self.set(f"channel_info:{channel_db_id}", data, ttl)

    async def invalidate_channel_info(self, channel_db_id: int):
        await self.invalidate(f"channel_info:{channel_db_id}")

    async def get_group_info(self, chat_id: int):
        return await self.get(f"group_info:{chat_id}")

    async def set_group_info(self, chat_id: int, data, ttl: int = None):
        await self.set(f"group_info:{chat_id}", data, ttl)

    async def invalidate_group_info(self, chat_id: int):
        await self.invalidate(f"group_info:{chat_id}")

    async def get_next_post(self, channel_db_id: int):
        return await self.get(f"next_post:{channel_db_id}")

    async def set_next_post(self, channel_db_id: int, post, ttl: int = None):
        await self.set(f"next_post:{channel_db_id}", post, ttl)

    async def get_posts(self, channel_db_id: int, limit: int = 10):
        return await self.get(f"posts:{channel_db_id}:{limit}")

    async def set_posts(self, channel_db_id: int, posts, limit: int = 10, ttl: int = None):
        await self.set(f"posts:{channel_db_id}:{limit}", posts, ttl)

    async def get_admin_list(self, key: int = 0):
        return await self.get(f"admin_list:{key}")

    async def set_admin_list(self, key: int, data, ttl: int = None):
        await self.set(f"admin_list:{key}", data, ttl)

    async def get_security(self, chat_id: int):
        return await self.get(f"security:{chat_id}")

    async def set_security(self, chat_id: int, data, ttl: int = None):
        await self.set(f"security:{chat_id}", data, ttl)

    async def invalidate_security(self, chat_id: int):
        await self.invalidate(f"security:{chat_id}")

    async def get_auto_reply_settings(self, chat_id: int):
        return await self.get(f"auto_reply_settings:{chat_id}")

    async def set_auto_reply_settings(self, chat_id: int, data, ttl: int = None):
        await self.set(f"auto_reply_settings:{chat_id}", data, ttl)

    async def invalidate_auto_reply(self, chat_id: int):
        await self.invalidate(f"auto_reply_settings:{chat_id}")

    async def get_bot_setting(self, key: str):
        return await self.get(f"bot_setting:{key}")

    async def set_bot_setting(self, key: str, value, ttl: int = None):
        await self.set(f"bot_setting:{key}", value, ttl)

    async def invalidate_bot_settings(self, key: str = None):
        if key is None:
            await self.invalidate()
        else:
            await self.invalidate(f"bot_setting:{key}")


class SettingsCache(SimpleCache):
    """كاش متخصص للإعدادات"""
    pass

# =====================================================================
# 0.5 محاولة تحميل cache.py الحقيقي
# =====================================================================

try:
    from cache import (
        user_cache,
        banned_words_cache,
        settings_cache,
        channels_cache,
        groups_cache,
        auth_cache,
        posts_cache,
        invalidate_user_cache,
        clear_all_caches,
        get_cache_stats,
        cache_cleanup_task,
    )
    CACHE_AVAILABLE = True
    logger.info("✅ تم تحميل نظام الكاش المتقدم من cache.py")

except ImportError:
    user_cache = SimpleCache(default_ttl=60)
    banned_words_cache = SimpleCache(default_ttl=300)
    settings_cache = SettingsCache(default_ttl=120)
    channels_cache = SimpleCache(default_ttl=60)
    groups_cache = SimpleCache(default_ttl=60)
    auth_cache = SimpleCache(default_ttl=120)
    posts_cache = SimpleCache(default_ttl=30)

    async def invalidate_user_cache(user_id: int):
        try:
            await user_cache.invalidate(user_id)
            await internal_cache.invalidate(f"user_{user_id}")
            await internal_cache.invalidate(f"user_{user_id}_True")
            await internal_cache.invalidate(f"user_{user_id}_False")
            await internal_cache.invalidate(f"lang_{user_id}")
            await internal_cache.invalidate(f"channels_{user_id}")
            await internal_cache.invalidate(f"groups_{user_id}")
            await internal_cache.invalidate(f"reminder_settings_{user_id}")
            await internal_cache.invalidate(f"auto_recycle_{user_id}")
            await internal_cache.invalidate(f"auto_publish_{user_id}")           # ✅ v7.5.9
            await internal_cache.invalidate(f"user_settings_batch_{user_id}")    # ✅ v7.5.9
            await internal_cache.invalidate(f"has_active_sub_{user_id}")
        except Exception as e:
            logger.debug(f"invalidate_user_cache: {e}")

    async def clear_all_caches():
        try:
            await user_cache.clear()
            await banned_words_cache.clear()
            await settings_cache.clear()
            await channels_cache.clear()
            await groups_cache.clear()
            await auth_cache.clear()
            await posts_cache.clear()
            await internal_cache.clear()
        except Exception as e:
            logger.warning(f"clear_all_caches: {e}")

    async def get_cache_stats() -> Dict[str, Any]:
        return {
            'mode': 'fallback',
            'user_cache': await user_cache.get_stats(),
            'banned_words_cache': await banned_words_cache.get_stats(),
            'channels_cache': await channels_cache.get_stats(),
            'posts_cache': await posts_cache.get_stats(),
            'auth_cache': await auth_cache.get_stats(),
            'internal_cache': {'size': await internal_cache.get_size()},
        }

    async def cache_cleanup_task():
        while True:
            try:
                await asyncio.sleep(300)
                for cache_obj in (
                    user_cache, banned_words_cache, settings_cache,
                    channels_cache, groups_cache, auth_cache, posts_cache
                ):
                    async with cache_obj._lock:
                        now = time.time()
                        expired = [
                            k for k, (_, ts, ttl) in cache_obj._cache.items()
                            if now - ts >= ttl
                        ]
                        for k in expired:
                            del cache_obj._cache[k]
                logger.debug("🧹 تم تنظيف الكاش (fallback mode)")
            except asyncio.CancelledError:
                logger.info("🛑 cache_cleanup_task تم إلغاؤه")
                break
            except Exception as e:
                logger.error(f"❌ cache_cleanup_task: {e}")

    CACHE_AVAILABLE = True
    logger.warning("⚠️ cache.py غير موجود، تم استخدام كاش داخلي كامل")

# =====================================================================
# 0.6 ثوابت
# =====================================================================

MAX_POST_TEXT_LENGTH = int(os.getenv("MAX_POST_TEXT_LENGTH", "0"))
MAX_USER_LOCKS_CONFIG = int(os.getenv("MAX_USER_LOCKS", "10000"))
POSTS_BATCH_SIZE = int(os.getenv("POSTS_BATCH_SIZE", "100"))
SQLITE_POOL_SIZE = int(os.getenv("SQLITE_POOL_SIZE", "10"))
EXPLAIN_SLOW_QUERIES = os.getenv("EXPLAIN_SLOW_QUERIES", "false").lower() == "true"

UTC = timezone.utc

# =====================================================================
# 1. دوال مساعدة للتوافق
# =====================================================================

KNOWN_UNIQUE_FALLBACK = {
    'users': ['user_id'],
    'user_channels': ['user_id', 'channel_id'],
    'posts': ['id'],
    'schedule': ['channel_db_id'],
    'last_publish': ['channel_db_id'],
    'bot_groups': ['chat_id'],
    'user_groups_link': ['user_id', 'chat_id'],
    'group_admins': ['chat_id', 'user_id'],
    'hidden_owner_groups': ['chat_id', 'owner_id'],
    'hidden_admins': ['chat_id', 'admin_id'],
    'anonymous_admins': ['chat_id', 'anonymous_id'],
    'group_security': ['chat_id'],
    'chat_locks': ['chat_id'],
    'banned_words': ['word', 'chat_id'],
    'auto_replies': ['chat_id', 'keyword'],
    'auto_reply_settings': ['chat_id'],
    'support_tickets': ['id'],
    'bot_admins': ['user_id'],
    'settings': ['key'],
    'referrals': ['referrer_id', 'referred_id'],
    'referral_rewards': ['user_id'],
    'user_reminder_settings': ['user_id'],
    'user_translation': ['user_id'],
    'contests': ['id'],
    'contest_participants': ['user_id', 'contest_id'],
    'contest_winners': ['id'],
    'admin_logs': ['id'],
    'user_warnings': ['user_id', 'chat_id'],
    'user_violations': ['user_id', 'chat_id'],
    'group_rules': ['chat_id'],
    'user_messages': ['user_id', 'chat_id'],
    'scheduled_posts': ['id'],
    'sentiment_history': ['id'],
    'plans': ['id'],
    'subscriptions': ['id'],
    'invoices': ['id'],
    'payment_logs': ['id'],
    'user_penalties': ['id'],
    'violation_penalties': ['chat_id', 'violation_type'],
    'gift_codes': ['id'],
    'user_points': ['user_id'],
    'schema_version': ['version'],
}

_UNIQUE_CACHE = {}


async def _get_unique_columns(table: str, conn) -> List[str]:
    if table in _UNIQUE_CACHE:
        return _UNIQUE_CACHE[table]

    columns = []
    existing_columns = set()

    try:
        if USE_POSTGRES:
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
                table,
            )
            existing_columns = {row["column_name"] for row in rows}
        elif USE_MYSQL:
            if not await _table_exists(conn, table):
                return KNOWN_UNIQUE_FALLBACK.get(table, ["id"])
            cursor = await conn.cursor()
            await cursor.execute(f"SHOW COLUMNS FROM `{table}`")
            rows = await cursor.fetchall()
            existing_columns = {row[0] for row in rows}
            await cursor.close()
        else:
            cursor = await conn.execute(f"PRAGMA table_info({table})")
            rows = await cursor.fetchall()
            existing_columns = {row[1] for row in rows}
    except Exception as e:
        logger.warning(f"⚠️ فشل جلب أعمدة جدول {table}: {e}")
        return KNOWN_UNIQUE_FALLBACK.get(table, ["id"])

    try:
        if USE_POSTGRES:
            pk_rows = await conn.fetch(
                """
                SELECT a.attname
                FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = $1::regclass
                  AND i.indisprimary
                """,
                table,
            )
            if pk_rows:
                columns = [row["attname"] for row in pk_rows if row["attname"] in existing_columns]
            else:
                unique_rows = await conn.fetch(
                    """
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = $1::regclass
                      AND i.indisunique
                      AND NOT i.indisprimary
                    LIMIT 1
                    """,
                    table,
                )
                if unique_rows:
                    columns = [row["attname"] for row in unique_rows if row["attname"] in existing_columns]
        elif USE_MYSQL:
            cursor = await conn.cursor()
            await cursor.execute(f"SHOW KEYS FROM `{table}` WHERE Key_name = 'PRIMARY'")
            pk_rows = await cursor.fetchall()
            if pk_rows:
                columns = [row[4] for row in pk_rows if row[4] in existing_columns]
            else:
                await cursor.execute(
                    f"SHOW KEYS FROM `{table}` WHERE Non_unique = 0 AND Key_name != 'PRIMARY' LIMIT 1"
                )
                unique_rows = await cursor.fetchall()
                if unique_rows:
                    key_name = unique_rows[0][2]
                    await cursor.execute(f"SHOW KEYS FROM `{table}` WHERE Key_name = '{key_name}'")
                    all_rows = await cursor.fetchall()
                    columns = [row[4] for row in all_rows if row[4] in existing_columns]
            await cursor.close()
        else:
            cursor = await conn.execute(f"PRAGMA table_info({table})")
            rows = await cursor.fetchall()
            pk_columns = [row[1] for row in rows if row[5] == 1 and row[1] in existing_columns]
            if pk_columns:
                columns = pk_columns
            else:
                fallback = KNOWN_UNIQUE_FALLBACK.get(table, [])
                columns = [col for col in fallback if col in existing_columns]
                if not columns and rows:
                    columns = [rows[0][1]] if rows[0][1] in existing_columns else []
    except Exception as e:
        logger.warning(f"⚠️ فشل جلب المفاتيح الفريدة لجدول {table}: {e}")
        fallback = KNOWN_UNIQUE_FALLBACK.get(table, [])
        columns = [col for col in fallback if col in existing_columns]
        if not columns and existing_columns:
            columns = [list(existing_columns)[0]]

    if not columns:
        columns = ["id"]

    _UNIQUE_CACHE[table] = columns
    return columns


async def _find_best_conflict_target(
    table: str, conn, insert_columns: List[str]
) -> Optional[str]:
    insert_set = set(insert_columns)

    if USE_POSTGRES:
        try:
            rows = await conn.fetch(
                """
                SELECT i.indexname,
                       ix.indisprimary,
                       array_agg(a.attname ORDER BY a.attnum) AS cols
                FROM pg_indexes i
                JOIN pg_class t ON t.relname = i.tablename
                JOIN pg_index ix ON ix.indexrelid = (
                    SELECT oid FROM pg_class
                    WHERE relname = i.indexname AND relkind = 'i'
                )
                JOIN pg_attribute a
                  ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
                WHERE i.tablename = $1 AND ix.indisunique
                GROUP BY i.indexname, ix.indisprimary
                """,
                table,
            )
            for row in rows:
                if not row["indisprimary"]:
                    cols = list(row["cols"])
                    if cols and all(c in insert_set for c in cols):
                        return ", ".join(cols)
            for row in rows:
                if row["indisprimary"]:
                    cols = list(row["cols"])
                    if cols and all(c in insert_set for c in cols):
                        return ", ".join(cols)
            return None
        except Exception as e:
            logger.warning(f"⚠️ فشل جلب قيود UNIQUE لـ {table}: {e}")
            return None

    elif USE_MYSQL:
        return None

    else:
        try:
            cursor = await conn.execute(f"PRAGMA index_list({table})")
            indexes = await cursor.fetchall()
            primary_cols = None
            unique_cols = None
            for idx in indexes:
                if idx[2] != 1:
                    continue
                is_primary = (idx[3] == "pk")
                cursor2 = await conn.execute(f"PRAGMA index_info({idx[1]})")
                cols_rows = await cursor2.fetchall()
                cols = [r[2] for r in cols_rows]
                if not cols:
                    continue
                if all(c in insert_set for c in cols):
                    if is_primary and primary_cols is None:
                        primary_cols = cols
                    elif not is_primary and unique_cols is None:
                        unique_cols = cols
            if unique_cols:
                return ", ".join(unique_cols)
            if primary_cols:
                return ", ".join(primary_cols)
            return None
        except Exception:
            return None


def _convert_placeholders(query: str) -> str:
    if DB_TYPE == "sqlite":
        return query
    if USE_POSTGRES:
        existing_params = re.findall(r"\$(\d+)", query)
        param_count = max((int(n) for n in existing_params), default=0)

        result = []
        in_single = False
        in_double = False
        in_comment = False
        in_block_comment = False
        escape_next = False
        i = 0
        while i < len(query):
            ch = query[i]
            if escape_next:
                result.append(ch)
                escape_next = False
                i += 1
                continue
            if ch == "\\" and (in_single or in_double):
                escape_next = True
                result.append(ch)
                i += 1
                continue
            if (not in_single and not in_double and not in_block_comment
                    and ch == "-" and i + 1 < len(query) and query[i + 1] == "-"):
                in_comment = True
            if in_comment:
                if ch == "\n":
                    in_comment = False
                result.append(ch)
                i += 1
                continue
            if (not in_single and not in_double and not in_comment
                    and ch == "/" and i + 1 < len(query) and query[i + 1] == "*"):
                in_block_comment = True
                result.append(ch)
                i += 1
                continue
            if in_block_comment:
                if ch == "*" and i + 1 < len(query) and query[i + 1] == "/":
                    in_block_comment = False
                    result.append(ch)
                    result.append(query[i + 1])
                    i += 2
                    continue
                result.append(ch)
                i += 1
                continue
            if ch == "'" and not in_double and not in_comment and not in_block_comment:
                in_single = not in_single
                result.append(ch)
                i += 1
                continue
            if ch == '"' and not in_single and not in_comment and not in_block_comment:
                in_double = not in_double
                result.append(ch)
                i += 1
                continue
            if (ch == "?" and not in_single and not in_double
                    and not in_comment and not in_block_comment):
                param_count += 1
                result.append(f"${param_count}")
                i += 1
                continue
            result.append(ch)
            i += 1
        return "".join(result)
    elif USE_MYSQL:
        result = []
        in_single = False
        in_double = False
        in_block_comment = False
        escape_next = False
        i = 0
        while i < len(query):
            ch = query[i]
            if escape_next:
                result.append(ch)
                escape_next = False
                i += 1
                continue
            if ch == "\\" and (in_single or in_double):
                escape_next = True
                result.append(ch)
                i += 1
                continue
            if ch == "/" and i + 1 < len(query) and query[i + 1] == "*":
                in_block_comment = True
                result.append(ch)
                i += 1
                continue
            if in_block_comment:
                if ch == "*" and i + 1 < len(query) and query[i + 1] == "/":
                    in_block_comment = False
                    result.append(ch)
                    result.append(query[i + 1])
                    i += 2
                    continue
                result.append(ch)
                i += 1
                continue
            if ch == "'" and not in_double:
                in_single = not in_single
                result.append(ch)
                i += 1
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                result.append(ch)
                i += 1
                continue
            if ch == "?" and not in_single and not in_double and not in_block_comment:
                result.append("%s")
                i += 1
                continue
            result.append(ch)
            i += 1
        return "".join(result)
    else:
        return query


async def _convert_insert_or_ignore(query: str, conn=None) -> str:
    if DB_TYPE == "sqlite":
        return query
    upper_query = query.upper().lstrip()
    if not upper_query.startswith("INSERT OR IGNORE"):
        return query
    if USE_POSTGRES:
        new_query = query.replace("INSERT OR IGNORE", "INSERT", 1)
        match = re.search(
            r"INSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)\s+VALUES", new_query, re.IGNORECASE
        )
        if not match:
            return new_query + " ON CONFLICT DO NOTHING"
        table = match.group(1)
        columns = [c.strip() for c in match.group(2).split(",") if c.strip()]

        conflict_cols = None
        if conn:
            try:
                conflict_cols = await _find_best_conflict_target(table, conn, columns)
            except Exception as e:
                logger.warning(f"⚠️ فشل جلب المفاتيح الفريدة لـ {table}: {e}")

        if conflict_cols:
            target = f" ({conflict_cols})"
        else:
            target = ""

        values_match = re.search(r"VALUES\s*\([^)]*\)", new_query, re.IGNORECASE)
        if values_match:
            end_pos = values_match.end()
            new_query = (
                new_query[:end_pos]
                + f" ON CONFLICT{target} DO NOTHING"
                + new_query[end_pos:]
            )
        else:
            new_query = new_query + f" ON CONFLICT{target} DO NOTHING"
        return new_query
    elif USE_MYSQL:
        return query.replace("INSERT OR IGNORE", "INSERT IGNORE", 1)
    else:
        return query


async def _convert_insert_or_replace(query: str, conn=None) -> str:
    if DB_TYPE == "sqlite":
        return query
    upper_query = query.upper().lstrip()
    if not upper_query.startswith("INSERT OR REPLACE"):
        return query
    if USE_POSTGRES:
        new_query = query.replace("INSERT OR REPLACE", "INSERT", 1)
        match = re.search(
            r"INSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)\s+VALUES", new_query, re.IGNORECASE
        )
        if not match:
            return new_query + " ON CONFLICT DO NOTHING"
        table = match.group(1)
        columns = [c.strip() for c in match.group(2).split(",") if c.strip()]

        best_cols = None
        if conn:
            try:
                best_cols = await _find_best_conflict_target(table, conn, columns)
            except Exception as e:
                logger.warning(f"⚠️ فشل جلب المفاتيح الفريدة لـ {table}: {e}")

        if not best_cols:
            values_match = re.search(r"VALUES\s*\([^)]*\)", new_query, re.IGNORECASE)
            if values_match:
                end_pos = values_match.end()
                return new_query[:end_pos] + " ON CONFLICT DO NOTHING" + new_query[end_pos:]
            return new_query + " ON CONFLICT DO NOTHING"

        pk_list = [c.strip() for c in best_cols.split(",") if c.strip()]
        pk_set = set(pk_list)
        set_columns = [col for col in columns if col not in pk_set]

        if not set_columns:
            values_match = re.search(r"VALUES\s*\([^)]*\)", new_query, re.IGNORECASE)
            if values_match:
                end_pos = values_match.end()
                new_query = new_query[:end_pos] + f" ON CONFLICT ({best_cols}) DO NOTHING" + new_query[end_pos:]
            else:
                new_query = new_query + f" ON CONFLICT ({best_cols}) DO NOTHING"
            return new_query

        existing_columns = set()
        try:
            if USE_POSTGRES:
                rows = await conn.fetch(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
                    table,
                )
                existing_columns = {row["column_name"] for row in rows}
            elif USE_MYSQL:
                cursor = await conn.cursor()
                await cursor.execute(f"SHOW COLUMNS FROM `{table}`")
                rows = await cursor.fetchall()
                existing_columns = {row[0] for row in rows}
                await cursor.close()
            else:
                cursor = await conn.execute(f"PRAGMA table_info({table})")
                rows = await cursor.fetchall()
                existing_columns = {row[1] for row in rows}
        except Exception:
            pass

        set_columns = [col for col in set_columns if col in existing_columns]
        if not set_columns:
            values_match = re.search(r"VALUES\s*\([^)]*\)", new_query, re.IGNORECASE)
            if values_match:
                end_pos = values_match.end()
                new_query = new_query[:end_pos] + f" ON CONFLICT ({best_cols}) DO NOTHING" + new_query[end_pos:]
            else:
                new_query = new_query + f" ON CONFLICT ({best_cols}) DO NOTHING"
            return new_query

        set_clause = ", ".join([f"{col} = EXCLUDED.{col}" for col in set_columns])
        values_match = re.search(r"VALUES\s*\([^)]*\)", new_query, re.IGNORECASE)
        if values_match:
            end_pos = values_match.end()
            new_query = new_query[:end_pos] + f" ON CONFLICT ({best_cols}) DO UPDATE SET {set_clause}" + new_query[end_pos:]
        else:
            new_query = new_query + f" ON CONFLICT ({best_cols}) DO UPDATE SET {set_clause}"
        return new_query
    elif USE_MYSQL:
        return query.replace("INSERT OR REPLACE", "REPLACE", 1)
    else:
        return query


def _convert_upsert(query: str) -> str:
    if DB_TYPE == "sqlite":
        return query
    if not USE_MYSQL and not USE_POSTGRES:
        return query

    pattern = r"ON\s+CONFLICT\s*\(([^)]+)\)\s+DO\s+UPDATE\s+SET\s+(.+)"
    match = re.search(pattern, query, re.IGNORECASE | re.DOTALL)
    if not match:
        return query

    if USE_MYSQL:
        update_set = match.group(2).strip()

        def replace_excluded(m):
            return f"VALUES({m.group(1)})"

        new_update_set = re.sub(
            r"excluded\.([a-zA-Z_][a-zA-Z0-9_]*)", replace_excluded, update_set
        )
        new_query = query[: match.start()].rstrip()
        return new_query + f" ON DUPLICATE KEY UPDATE {new_update_set}"
    else:
        return query


def _adapt_params(params: tuple) -> tuple:
    if params is None:
        return ()
    new_params = []
    for p in params:
        if isinstance(p, datetime):
            if p.tzinfo is not None:
                try:
                    p = p.astimezone(UTC).replace(tzinfo=None)
                except Exception:
                    p = p.replace(tzinfo=None)

            if USE_POSTGRES:
                new_params.append(p)
            elif USE_MYSQL:
                new_params.append(p.strftime("%Y-%m-%d %H:%M:%S"))
            else:
                new_params.append(p.strftime("%Y-%m-%d %H:%M:%S"))
        elif isinstance(p, bool):
            new_params.append(1 if p else 0)
        else:
            new_params.append(p)
    return tuple(new_params)


async def _table_exists(conn, table: str) -> bool:
    try:
        if USE_POSTGRES:
            row = await conn.fetchval(
                "SELECT 1 FROM information_schema.tables WHERE table_name = $1", table
            )
            return row is not None
        elif USE_MYSQL:
            cursor = await conn.cursor()
            await cursor.execute(f"SHOW TABLES LIKE '{table}'")
            row = await cursor.fetchone()
            await cursor.close()
            return row is not None
        else:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            )
            row = await cursor.fetchone()
            return row is not None
    except Exception:
        return False

# =====================================================================
# 2. فئة TimeUtils
# =====================================================================

class TimeUtils:
    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def mecca_now() -> datetime:
        return TimeUtils.utc_now() + timedelta(hours=3)

    @staticmethod
    def utc_iso() -> str:
        return TimeUtils.utc_now().isoformat()

    @staticmethod
    def mecca_iso() -> str:
        return TimeUtils.mecca_now().isoformat()

    @staticmethod
    def sql_iso() -> str:
        return TimeUtils.utc_now().strftime("%Y-%m-%d %H:%M:%S+00:00")

    @staticmethod
    def mecca_to_utc(dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt - timedelta(hours=3)

    @staticmethod
    def utc_to_mecca(dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt + timedelta(hours=3)

    @staticmethod
    def safe_parse_iso(date_str: Optional[Union[str, datetime]]) -> Optional[datetime]:
        if date_str is None:
            return None
        if isinstance(date_str, datetime):
            if date_str.tzinfo is not None:
                return date_str.astimezone(UTC).replace(tzinfo=None)
            return date_str
        if not isinstance(date_str, str):
            return None
        if date_str.endswith("+00:00"):
            date_str = date_str[:-6]
        try:
            return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except (ValueError, TypeError):
            pass
        try:
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            pass
        return None

# =====================================================================
# 3. فئة Database (ترث من كل الـ Mixins)
# =====================================================================

class Database(
    ChannelsPostsMixin,
    SubscriptionsMixin,
    GroupsMixin,
    TicketsMixin,
    ContestsMixin,
    StatsMixin,
    SettingsMixin,
    PointsMixin,
    BackupMixin,
    RemindersMixin,
):
    _instance = None
    _lock = asyncio.Lock()
    _user_locks = {}
    _channel_locks = defaultdict(lambda: asyncio.Lock())
    _user_locks_last_access = {}
    _MAX_USER_LOCKS = MAX_USER_LOCKS_CONFIG

    VALID_PENALTY_TYPES = {"mute", "ban", "restrict", "kick", "warn"}
    VALID_REPLY_TYPES = {
        "text", "photo", "video", "animation", "document",
        "sticker", "voice", "video_note",
    }
    VALID_VIOLATION_TYPES = {
        "link", "mention", "flood", "nsfw", "banned_word", "media", "other",
        "forward", "sticker", "gif", "poll", "game", "voice", "video_note",
        "photo", "video", "document", "audio", "animation", "spam",
        "delete_links", "mentions", "slow_mode", "delete_videos",
        "delete_audio", "delete_animation", "delete_service",
        "delete_documents", "delete_stickers", "delete_forwarded",
        "delete_polls", "delete_games", "delete_voice", "delete_video_note",
        "delete_photos", "antiflood", "night_mode", "warn_penalty",
    }
    MAX_PENALTY_DURATION = 365 * 86400

    COLUMN_ALIASES = {
        # ==================== Mentions ====================
        "delete_mentions": "mentions",
        "delete_mention": "mentions",
        "remove_mentions": "mentions",
        "mention": "mentions",
        "mentions_filter": "mentions",
        "delete_mention_messages": "mentions",
        # ==================== Links ====================
        "remove_links": "delete_links",
        "links": "delete_links",
        "delete_link": "delete_links",
        "remove_link": "delete_links",
        "links_filter": "delete_links",
        # ==================== Forward ====================
        "delete_forwarded_messages": "delete_forwarded",
        "remove_forwards": "delete_forwarded",
        "forward": "delete_forwarded",
        "forwarded": "delete_forwarded",
        "delete_forward": "delete_forwarded",
        "remove_forward": "delete_forwarded",
        "forwards": "delete_forwarded",
        # ==================== Polls ====================
        "delete_polls_games": "delete_polls",
        "polls": "delete_polls",
        "remove_polls": "delete_polls",
        "delete_poll": "delete_polls",
        "poll": "delete_polls",
        # ==================== Games ====================
        "games": "delete_games",
        "remove_games": "delete_games",
        "delete_game": "delete_games",
        "game": "delete_games",
        # ==================== Service messages ====================
        "delete_service_messages": "delete_service",
        "service_messages": "delete_service",
        "remove_service": "delete_service",
        "delete_service_msg": "delete_service",
        "delete_services": "delete_service",
        "service_msg": "delete_service",
        "service_message": "delete_service",
        "delete_service_message": "delete_service",
        # ==================== Voice ====================
        "voice": "delete_voice",
        "remove_voice": "delete_voice",
        "delete_voices": "delete_voice",
        "delete_voice_messages": "delete_voice",
        "voice_messages": "delete_voice",
        "delete_voice_msg": "delete_voice",
        # ==================== Video note ====================
        "video_note": "delete_video_note",
        "delete_video_notes": "delete_video_note",
        "remove_video_note": "delete_video_note",
        "delete_videonote": "delete_video_note",
        "video_notes": "delete_video_note",
        "videonote": "delete_video_note",
        # ==================== Photos ====================
        "delete_photo": "delete_photos",
        "photos": "delete_photos",
        "remove_photos": "delete_photos",
        "delete_photo_msg": "delete_photos",
        "photo": "delete_photos",
        "delete_photo_messages": "delete_photos",
        # ==================== Videos ====================
        "delete_video": "delete_videos",
        "videos": "delete_videos",
        "remove_videos": "delete_videos",
        "video": "delete_videos",
        "delete_video_messages": "delete_videos",
        # ==================== Audio ====================
        "delete_audios": "delete_audio",
        "audios": "delete_audio",
        "remove_audio": "delete_audio",
        "audio": "delete_audio",
        "delete_audio_messages": "delete_audio",
        # ==================== Animation / GIF ====================
        "delete_gifs": "delete_animation",
        "gifs": "delete_animation",
        "gif": "delete_animation",
        "remove_gif": "delete_animation",
        "animation": "delete_animation",
        "animations": "delete_animation",
        # ==================== Documents ====================
        "delete_document": "delete_documents",
        "documents": "delete_documents",
        "remove_documents": "delete_documents",
        "document": "delete_documents",
        "delete_document_messages": "delete_documents",
        # ==================== Stickers ====================
        "delete_sticker": "delete_stickers",
        "stickers": "delete_stickers",
        "remove_stickers": "delete_stickers",
        "sticker": "delete_stickers",
        "delete_sticker_messages": "delete_stickers",
        # ==================== Antiflood ====================
        "anti_flood": "antiflood_enabled",
        "flood": "antiflood_enabled",
        "antiflood": "antiflood_enabled",
        "flood_protection": "antiflood_enabled",
        "anti_flood_enabled": "antiflood_enabled",
        # ==================== Night mode ====================
        "nightmode": "night_mode_enabled",
        "night_mode": "night_mode_enabled",
        "night": "night_mode_enabled",
        "night_mode_active": "night_mode_enabled",
        "night_start": "night_mode_start",
        "night_end": "night_mode_end",
        "night_mode_begin": "night_mode_start",
        "night_mode_finish": "night_mode_end",
        "start_night": "night_mode_start",
        "end_night": "night_mode_end",
        # ==================== Warnings ====================
        "warnings": "warn_enabled",
        "warn_system": "warn_enabled",
        "warning": "warn_enabled",
        "warnings_enabled": "warn_enabled",
        "warn": "warn_enabled",
        # ==================== Welcome/Goodbye ====================
        "welcome": "welcome_enabled",
        "welcome_message": "welcome_text",
        "welcome_msg": "welcome_text",
        "goodbye": "goodbye_enabled",
        "goodbye_message": "goodbye_text",
        "goodbye_msg": "goodbye_text",
        # ==================== Join requests ====================
        "auto_approve": "auto_approve_join",
        "auto_reject": "auto_reject_join",
        "approve_join": "auto_approve_join",
        "reject_join": "auto_reject_join",
        "auto_approve_enabled": "auto_approve_join",
        "auto_reject_enabled": "auto_reject_join",
        # ==================== Slow mode ====================
        "slowmode": "slow_mode",
        "slow_mode_sec": "slow_mode_seconds",
        "slowmode_seconds": "slow_mode_seconds",
        # ==================== NSFW ====================
        "nsfw": "nsfw_enabled",
        "nsfw_protection": "nsfw_enabled",
        "nsfw_filter_enabled": "nsfw_enabled",
        # ==================== Antiflood variants ====================
        "antiflood_messages_count": "antiflood_messages",
        "antiflood_seconds_window": "antiflood_seconds",
        "antiflood_window": "antiflood_seconds",
        # ==================== Max message length ====================
        "message_length": "max_message_length",
        "max_length": "max_message_length",
        "message_max_length": "max_message_length",
        # ==================== Penalty variants ====================
        "auto_penalty_enabled": "auto_penalty",
        "delete_penalty_enabled": "delete_penalty",
        "delete_message_enabled": "delete_penalty",
        # ==================== Violations ====================
        "violation_action": "violation_strikes",
        "violations_enabled": "violation_strikes",
    }

    def __new__(cls) -> "Database":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._pool = None
        self._sqlite_queue = None
        self._sqlite_pool_size = SQLITE_POOL_SIZE
        self._initialized = False
        self._db_type = DB_TYPE
        self._max_connections = int(os.getenv("DB_POOL_SIZE", "10"))
        self._connection_timeout = int(os.getenv("DB_TIMEOUT", "30"))
        self._cleanup_task = None
        self._secondary_index_task = None
        self._cache_cleanup_task = None
        self._sqlite_creation_lock = asyncio.Lock()
        self._sqlite_open_count = 0
        self._sqlite_count_lock = asyncio.Lock()
        self._user_locks_lock = asyncio.Lock()
        self._channel_locks_lock = asyncio.Lock()
        self._channel_locks_last_access = {}
        self._group_locks = defaultdict(lambda: asyncio.Lock())
        self._group_locks_last_access = {}
        self._group_locks_lock = asyncio.Lock()
        if not hasattr(self, "_lock"):
            self._lock = asyncio.Lock()
        self._slow_query_log_threshold = float(os.getenv("SLOW_QUERY_LOG_THRESHOLD", "1.0"))
        self._max_post_text_length = MAX_POST_TEXT_LENGTH
        self._posts_batch_size = POSTS_BATCH_SIZE
        self._explain_slow_queries = EXPLAIN_SLOW_QUERIES
        # ✅ خصائص مشتركة لكل الـ Mixins
        self.DB_TYPE = DB_TYPE
        self.USE_POSTGRES = USE_POSTGRES
        self.USE_MYSQL = USE_MYSQL
        self.TimeUtils = TimeUtils
        self.internal_cache = internal_cache
        # ✅ خصائص مطلوبة لـ Mixins
        self.CACHE_AVAILABLE = CACHE_AVAILABLE
        self.banned_words_cache = banned_words_cache
        self.settings_cache = settings_cache
        self.groups_cache = groups_cache
        self.auth_cache = auth_cache
        self.CONFIG = CONFIG
        self.PATHS = PATHS
        self.DATABASE_URL = DATABASE_URL
        # ✅ كاش محلي للكلمات المحظورة
        self._banned_words_local_cache = {}
        self._banned_words_cache_ttl = 300
        self._global_banned_words_cache: List[str] = []
        self._global_banned_words_loaded = False
        self._global_words_lock = asyncio.Lock()
        # ✅ كاش أعمدة group_security
        self._group_security_columns_cache: Optional[set] = None

    # =====================================================================
    # دوال التهيئة والإتصال
    # =====================================================================

    async def initialize(self):
        if self._initialized:
            return
        try:
            if USE_POSTGRES:
                self._pool = await asyncpg.create_pool(
                    dsn=DATABASE_URL,
                    min_size=1,
                    max_size=self._max_connections,
                    timeout=self._connection_timeout,
                    command_timeout=self._connection_timeout,
                    server_settings={
                        "application_name": "RelaxManager",
                        "statement_timeout": "30s",
                        "timezone": "UTC",
                    },
                )
                logger.info(f"✅ Pool PostgreSQL جاهز (max={self._max_connections})")
            elif USE_MYSQL:
                pattern = r"mysql(?:\+asyncmy)?://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)"
                match = re.match(pattern, DATABASE_URL)
                if not match:
                    raise ValueError("Invalid MySQL DATABASE_URL format")
                user, password, host, port, database = match.groups()
                self._pool = await asyncmy.create_pool(
                    host=host, port=int(port), user=user, password=password,
                    db=database, minsize=1, maxsize=self._max_connections,
                    pool_recycle=3600, autocommit=False, charset="utf8mb4",
                    init_command="SET time_zone = '+00:00'",
                )
                logger.info(f"✅ Pool MySQL جاهز (max={self._max_connections})")
            else:
                conn = await self._create_sqlite_connection()
                if conn is None:
                    raise RuntimeError("فشل إنشاء اتصال SQLite الأولي")
                self._sqlite_queue = asyncio.Queue(maxsize=self._sqlite_pool_size)
                await self._sqlite_queue.put(conn)
                self._sqlite_open_count = 1
                logger.info(f"✅ Pool SQLite جاهز (size={self._sqlite_pool_size}, initial=1)")
            self._initialized = True
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._auto_cleanup_locks())
        except Exception as e:
            if self._pool is not None:
                if USE_POSTGRES:
                    await self._pool.close()
                elif USE_MYSQL:
                    self._pool.close()
                    await self._pool.wait_closed()
                self._pool = None
            if self._sqlite_queue is not None:
                while not self._sqlite_queue.empty():
                    conn = await self._sqlite_queue.get()
                    await conn.close()
                self._sqlite_queue = None
                self._sqlite_open_count = 0
            logger.error(f"❌ فشل تهيئة قاعدة البيانات: {e}", exc_info=True)
            raise

    async def _create_sqlite_connection(self):
        try:
            conn = await aiosqlite.connect(
                str(PATHS.DB), timeout=self._connection_timeout, check_same_thread=False
            )
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA busy_timeout=10000")
            await conn.execute("PRAGMA cache_size=-20000")
            await conn.execute("PRAGMA temp_store=MEMORY")
            return conn
        except Exception as e:
            logger.error(f"❌ فشل إنشاء اتصال SQLite: {e}")
            return None

    async def close(self):
        tasks = []
        if self._cleanup_task:
            self._cleanup_task.cancel()
            tasks.append(self._cleanup_task)
        if self._secondary_index_task:
            self._secondary_index_task.cancel()
            tasks.append(self._secondary_index_task)
        if getattr(self, "_cache_cleanup_task", None):
            self._cache_cleanup_task.cancel()
            tasks.append(self._cache_cleanup_task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        if USE_POSTGRES and self._pool:
            await self._pool.close()
            self._pool = None
        elif USE_MYSQL and self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
        else:
            if self._sqlite_queue is not None:
                while not self._sqlite_queue.empty():
                    conn = await self._sqlite_queue.get()
                    await conn.close()
                self._sqlite_queue = None
                self._sqlite_open_count = 0

        try:
            await clear_all_caches()
        except Exception as e:
            logger.debug(f"clear_all_caches on close: {e}")

        self._initialized = False

    async def _get_connection(self):
        if not self._initialized:
            await self.initialize()
        if USE_POSTGRES or USE_MYSQL:
            return await asyncio.wait_for(self._pool.acquire(), timeout=self._connection_timeout)
        else:
            try:
                return await asyncio.wait_for(self._sqlite_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                async with self._sqlite_count_lock:
                    if self._sqlite_open_count < self._sqlite_pool_size:
                        conn = await self._create_sqlite_connection()
                        if conn is not None:
                            self._sqlite_open_count += 1
                            return conn
                return await asyncio.wait_for(
                    self._sqlite_queue.get(), timeout=self._connection_timeout
                )

    async def _return_connection(self, conn):
        if USE_POSTGRES or USE_MYSQL:
            await self._pool.release(conn)
        else:
            try:
                if self._sqlite_queue is not None:
                    try:
                        await asyncio.wait_for(self._sqlite_queue.put(conn), timeout=1.0)
                    except asyncio.TimeoutError:
                        logger.warning("⚠️ طابور SQLite ممتلئ، إغلاق الاتصال الزائد")
                        await conn.close()
                        async with self._sqlite_count_lock:
                            self._sqlite_open_count = max(0, self._sqlite_open_count - 1)
                else:
                    await conn.close()
                    async with self._sqlite_count_lock:
                        self._sqlite_open_count = max(0, self._sqlite_open_count - 1)
            except Exception as e:
                logger.warning(f"⚠️ فشل إرجاع اتصال SQLite: {e}")
                try:
                    await conn.close()
                except Exception:
                    pass
                async with self._sqlite_count_lock:
                    self._sqlite_open_count = max(0, self._sqlite_open_count - 1)

    @asynccontextmanager
    async def connection(self):
        conn = await self._get_connection()
        try:
            yield conn
            if DB_TYPE == "sqlite":
                try:
                    if conn.in_transaction:
                        await conn.commit()
                except Exception as e:
                    logger.debug(f"connection commit SQLite: {e}")
        except Exception:
            if DB_TYPE == "sqlite":
                try:
                    if conn.in_transaction:
                        await conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            await self._return_connection(conn)

    @asynccontextmanager
    async def transaction(self):
        conn = await self._get_connection()
        try:
            if USE_POSTGRES:
                await conn.execute("BEGIN")
            elif USE_MYSQL:
                await conn.execute("START TRANSACTION")
            else:
                await conn.execute("BEGIN TRANSACTION")
            yield conn
            if USE_POSTGRES:
                await conn.execute("COMMIT")
            elif USE_MYSQL:
                await conn.execute("COMMIT")
            else:
                await conn.execute("COMMIT")
        except Exception as e:
            try:
                if USE_POSTGRES:
                    await conn.execute("ROLLBACK")
                elif USE_MYSQL:
                    await conn.execute("ROLLBACK")
                else:
                    await conn.execute("ROLLBACK")
            except Exception:
                pass
            logger.error(f"❌ فشلت المعاملة: {e}", exc_info=True)
            raise
        finally:
            await self._return_connection(conn)

    # =====================================================================
    # دوال الاستعلام
    # =====================================================================

    async def _execute_with_logging(self, query: str, params: tuple, conn, executor):
        start = time.monotonic()
        try:
            result = await executor(query, params)
            elapsed = time.monotonic() - start
            if elapsed > self._slow_query_log_threshold:
                safe_query = re.sub(r"\b\d{6,}\b", "[REDACTED]", query[:200])
                logger.warning(f"🐌 استعلام بطيء ({elapsed:.2f}s): {safe_query}...")
                if self._explain_slow_queries:
                    try:
                        if USE_POSTGRES:
                            explain = await conn.fetch(f"EXPLAIN (ANALYZE, BUFFERS) {query}", *params)
                            logger.info("📊 EXPLAIN:\n" + "\n".join([str(row) for row in explain]))
                        elif USE_MYSQL:
                            cursor = await conn.cursor()
                            await cursor.execute(f"EXPLAIN {query}", params)
                            explain = await cursor.fetchall()
                            await cursor.close()
                            logger.info("📊 EXPLAIN:\n" + "\n".join([str(row) for row in explain]))
                        else:
                            cursor = await conn.execute(f"EXPLAIN QUERY PLAN {query}", params)
                            explain = await cursor.fetchall()
                            logger.info("📊 EXPLAIN:\n" + "\n".join([str(row) for row in explain]))
                    except Exception as e:
                        logger.warning(f"⚠️ فشل تنفيذ EXPLAIN: {e}")
            return result
        except Exception as e:
            elapsed = time.monotonic() - start
            safe_query = re.sub(r"\b\d{6,}\b", "[REDACTED]", query[:200])
            logger.error(f"❌ فشل الاستعلام ({elapsed:.2f}s): {safe_query}... | خطأ: {e}")
            raise

    async def _execute_with_retry(self, query: str, params, executor, max_retries=3):
        last_exception = None
        for attempt in range(max_retries):
            try:
                return await executor(query, params)
            except Exception as e:
                last_exception = e
                retryable = False
                if DB_TYPE == "sqlite" and isinstance(e, sqlite3.Error):
                    if not isinstance(e, sqlite3.IntegrityError):
                        error_msg = str(e).lower()
                        if any(kw in error_msg for kw in [
                            "database is locked", "busy", "disk i/o error",
                            "disk i/o", "malformed", "database disk image is malformed",
                        ]):
                            retryable = True
                elif USE_POSTGRES and isinstance(e, asyncpg.exceptions.DeadlockDetectedError):
                    retryable = True
                elif USE_POSTGRES and isinstance(e, asyncpg.exceptions.PostgresConnectionError):
                    retryable = True
                elif USE_MYSQL and isinstance(e, asyncmy.MySQLError):
                    error_msg = str(e).lower()
                    if any(kw in error_msg for kw in ["deadlock", "lock wait", "connection", "timeout"]):
                        retryable = True
                if retryable and attempt < max_retries - 1:
                    delay = (0.5 * (attempt + 1)) + (0.1 * attempt)
                    logger.warning(f"⚠️ إعادة محاولة {attempt + 1}/{max_retries} بعد {delay:.2f}s: {e}")
                    await asyncio.sleep(delay)
                    continue
                raise last_exception
        raise last_exception

    async def _execute_with_conn(self, conn, query: str, *params) -> int:
        q = _convert_placeholders(query)
        upper_q = q.upper().lstrip()
        is_ignore = upper_q.startswith("INSERT OR IGNORE")
        is_replace = upper_q.startswith("INSERT OR REPLACE")
        if is_ignore:
            q = await _convert_insert_or_ignore(q, conn)
        elif is_replace:
            q = await _convert_insert_or_replace(q, conn)
        if not is_ignore and not is_replace:
            q = _convert_upsert(q)
        params = _adapt_params(params) if params else ()
        if USE_POSTGRES:
            result = await self._execute_with_logging(
                q, params, conn, lambda q2, p2: conn.execute(q2, *p2)
            )
            parts = result.split()
            return int(parts[-1]) if parts and parts[-1].isdigit() else 0
        elif USE_MYSQL:
            cursor = await conn.cursor()
            await self._execute_with_logging(q, params, conn, lambda q2, p2: cursor.execute(q2, p2))
            await cursor.execute("SELECT ROW_COUNT()")
            row = await cursor.fetchone()
            await cursor.close()
            return row[0] if row else 0
        else:
            cursor = await self._execute_with_logging(q, params, conn, lambda q2, p2: conn.execute(q2, p2))
            return cursor.rowcount

    async def _executemany_with_conn(self, conn, query: str, params_list: List[tuple]) -> int:
        if not params_list:
            return 0
        q = _convert_placeholders(query)
        upper_q = q.upper().lstrip()
        is_ignore = upper_q.startswith("INSERT OR IGNORE")
        is_replace = upper_q.startswith("INSERT OR REPLACE")
        if is_ignore:
            q = await _convert_insert_or_ignore(q, conn)
        elif is_replace:
            q = await _convert_insert_or_replace(q, conn)
        if not is_ignore and not is_replace:
            q = _convert_upsert(q)
        params_list = [_adapt_params(p) for p in params_list]
        if USE_POSTGRES:
            try:
                await conn.executemany(q, params_list)
                return len(params_list)
            except Exception as e:
                logger.warning(f"⚠️ فشل executemany الجماعي ({e})، العودة للحلقة البطيئة")
                total = 0
                for params in params_list:
                    try:
                        result = await self._execute_with_logging(
                            q, params, conn, lambda q2, p2: conn.execute(q2, *p2)
                        )
                        parts = result.split()
                        if parts and parts[-1].isdigit():
                            total += int(parts[-1])
                        else:
                            total += 1
                    except Exception as e2:
                        logger.warning(f"⚠️ فشل تنفيذ صف في executemany: {e2}")
                        continue
                return total
        elif USE_MYSQL:
            cursor = await conn.cursor()
            await self._execute_with_logging(
                q, params_list, conn, lambda q2, p2: cursor.executemany(q2, p2)
            )
            rc = cursor.rowcount
            await cursor.close()
            return rc
        else:
            cursor = await self._execute_with_logging(
                q, params_list, conn, lambda q2, p2: conn.executemany(q2, p2)
            )
            return cursor.rowcount

    async def _fetchone_with_conn(self, conn, query: str, *params) -> Optional[Dict]:
        q = _convert_placeholders(query)
        params = _adapt_params(params) if params else ()
        if USE_POSTGRES:
            row = await self._execute_with_logging(q, params, conn, lambda q2, p2: conn.fetchrow(q2, *p2))
            return dict(row) if row else None
        elif USE_MYSQL:
            cursor = await conn.cursor()
            await self._execute_with_logging(q, params, conn, lambda q2, p2: cursor.execute(q2, p2))
            row = await cursor.fetchone()
            desc = cursor.description
            await cursor.close()
            if row and desc:
                columns = [d[0] for d in desc]
                return dict(zip(columns, row))
            return None
        else:
            cursor = await self._execute_with_logging(q, params, conn, lambda q2, p2: conn.execute(q2, p2))
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

    async def _fetchall_with_conn(self, conn, query: str, *params) -> List[Dict]:
        q = _convert_placeholders(query)
        params = _adapt_params(params) if params else ()
        if USE_POSTGRES:
            rows = await self._execute_with_logging(q, params, conn, lambda q2, p2: conn.fetch(q2, *p2))
            return [dict(row) for row in rows]
        elif USE_MYSQL:
            cursor = await conn.cursor()
            await self._execute_with_logging(q, params, conn, lambda q2, p2: cursor.execute(q2, p2))
            rows = await cursor.fetchall()
            desc = cursor.description
            await cursor.close()
            if rows and desc:
                columns = [d[0] for d in desc]
                return [dict(zip(columns, row)) for row in rows]
            return []
        else:
            cursor = await self._execute_with_logging(q, params, conn, lambda q2, p2: conn.execute(q2, p2))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def _fetchval_with_conn(self, conn, query: str, *params, default=None) -> Any:
        q = _convert_placeholders(query)
        params = _adapt_params(params) if params else ()
        if USE_POSTGRES:
            row = await self._execute_with_logging(q, params, conn, lambda q2, p2: conn.fetchrow(q2, *p2))
            return row[0] if row else default
        elif USE_MYSQL:
            cursor = await conn.cursor()
            await self._execute_with_logging(q, params, conn, lambda q2, p2: cursor.execute(q2, p2))
            row = await cursor.fetchone()
            await cursor.close()
            return row[0] if row else default
        else:
            cursor = await self._execute_with_logging(q, params, conn, lambda q2, p2: conn.execute(q2, p2))
            row = await cursor.fetchone()
            return row[0] if row else default

    async def execute(self, query: str, params: tuple = ()) -> int:
        async def _exec(q, p):
            async with self.connection() as conn:
                return await self._execute_with_conn(conn, q, *p)
        return await self._execute_with_retry(query, params, _exec)

    async def fetchone(self, query: str, params: tuple = ()) -> Optional[Dict]:
        async def _exec(q, p):
            async with self.connection() as conn:
                return await self._fetchone_with_conn(conn, q, *p)
        return await self._execute_with_retry(query, params, _exec)

    async def fetchall(self, query: str, params: tuple = ()) -> List[Dict]:
        async def _exec(q, p):
            async with self.connection() as conn:
                return await self._fetchall_with_conn(conn, q, *p)
        return await self._execute_with_retry(query, params, _exec)

    async def fetchval(self, query: str, params: tuple = (), default: Any = None) -> Any:
        async def _exec(q, p):
            async with self.connection() as conn:
                return await self._fetchval_with_conn(conn, q, *p, default=default)
        return await self._execute_with_retry(query, params, _exec)

    async def executemany(self, query: str, params_list: List[tuple]) -> int:
        if not params_list:
            return 0
        q = _convert_placeholders(query)
        params_list = [_adapt_params(p) for p in params_list]

        async def _exec(q2, p_list):
            async with self.connection() as conn:
                return await self._executemany_with_conn(conn, q2, p_list)
        return await self._execute_with_retry(q, params_list, _exec)

    # =====================================================================
    # دوال الأقفال
    # =====================================================================

    async def _get_user_lock(self, user_id: int) -> asyncio.Lock:
        async with self._user_locks_lock:
            if len(self._user_locks) >= self._MAX_USER_LOCKS:
                sorted_items = sorted(self._user_locks_last_access.items(), key=lambda x: x[1])
                to_remove = []
                max_to_remove = len(sorted_items) // 2
                for uid, _ in sorted_items:
                    if len(to_remove) >= max_to_remove:
                        break
                    lock = self._user_locks.get(uid)
                    if lock and not lock.locked() and not getattr(lock, "_waiters", None):
                        to_remove.append(uid)
                for uid in to_remove:
                    self._user_locks.pop(uid, None)
                    self._user_locks_last_access.pop(uid, None)
                if to_remove:
                    logger.warning(f"🧹 تم تنظيف {len(to_remove)} قفل مستخدم")
            if user_id not in self._user_locks:
                self._user_locks[user_id] = asyncio.Lock()
            self._user_locks_last_access[user_id] = time.monotonic()
            return self._user_locks[user_id]

    async def _get_channel_lock(self, channel_db_id: int) -> asyncio.Lock:
        async with self._channel_locks_lock:
            self._channel_locks_last_access[channel_db_id] = time.monotonic()
            return self._channel_locks[channel_db_id]

    async def _get_group_lock(self, chat_id: int) -> asyncio.Lock:
        async with self._group_locks_lock:
            self._group_locks_last_access[chat_id] = time.monotonic()
            return self._group_locks[chat_id]

    async def cleanup_user_locks(self, max_idle_seconds: int = 3600) -> int:
        try:
            async with self._user_locks_lock:
                now = time.monotonic()
                to_remove = []
                for user_id, last_access in self._user_locks_last_access.items():
                    if now - last_access > max_idle_seconds:
                        lock = self._user_locks.get(user_id)
                        if lock and not lock.locked() and not getattr(lock, "_waiters", None):
                            to_remove.append(user_id)
                for user_id in to_remove:
                    self._user_locks.pop(user_id, None)
                    self._user_locks_last_access.pop(user_id, None)
                if to_remove:
                    logger.info(f"🧹 تم تنظيف {len(to_remove)} قفل مستخدم")
                return len(to_remove)
        except Exception as e:
            logger.error(f"❌ Error in cleanup_user_locks: {e}")
            return 0

    async def cleanup_channel_locks(self, max_idle_seconds: int = 3600) -> int:
        try:
            async with self._channel_locks_lock:
                now = time.monotonic()
                to_remove = []
                for ch, ts in list(self._channel_locks_last_access.items()):
                    if now - ts > max_idle_seconds:
                        lock = self._channel_locks.get(ch)
                        if lock and not lock.locked() and not getattr(lock, "_waiters", None):
                            to_remove.append(ch)
                for ch in to_remove:
                    self._channel_locks.pop(ch, None)
                    self._channel_locks_last_access.pop(ch, None)
                if to_remove:
                    logger.info(f"🧹 تم تنظيف {len(to_remove)} قفل قناة")
                return len(to_remove)
        except Exception as e:
            logger.error(f"❌ Error in cleanup_channel_locks: {e}")
            return 0

    async def cleanup_group_locks(self, max_idle_seconds: int = 3600) -> int:
        try:
            async with self._group_locks_lock:
                now = time.monotonic()
                to_remove = []
                for ch, ts in list(self._group_locks_last_access.items()):
                    if now - ts > max_idle_seconds:
                        lock = self._group_locks.get(ch)
                        if lock and not lock.locked() and not getattr(lock, "_waiters", None):
                            to_remove.append(ch)
                for ch in to_remove:
                    self._group_locks.pop(ch, None)
                    self._group_locks_last_access.pop(ch, None)
                if to_remove:
                    logger.info(f"🧹 تم تنظيف {len(to_remove)} قفل مجموعة")
                return len(to_remove)
        except Exception as e:
            logger.error(f"❌ Error in cleanup_group_locks: {e}")
            return 0

    async def _auto_cleanup_locks(self):
        while True:
            try:
                await asyncio.sleep(3600)
                await self.cleanup_user_locks()
                await self.cleanup_channel_locks()
                await self.cleanup_group_locks()
            except asyncio.CancelledError:
                logger.info("🛑 مهمة تنظيف الأقفال تم إلغاؤها")
                break
            except Exception as e:
                logger.error(f"❌ Error in _auto_cleanup_locks: {e}")

    # =====================================================================
    # إنشاء الجداول
    # =====================================================================

    def _compute_text_hash(self, text: Optional[str]) -> str:
        if text is None:
            return hashlib.sha256(b"").hexdigest()
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    async def _create_tables(self):
        if not TABLES_MODULE_AVAILABLE:
            raise RuntimeError(
                "❌ database_tables.py غير متاح — تأكد من وجوده بجانب database.py"
            )
        async with self.connection() as conn:
            if USE_POSTGRES:
                await create_tables_postgres(conn, logger, TimeUtils)
                logger.info("✅ تم إنشاء جداول PostgreSQL عبر database_tables.py")
            elif USE_MYSQL:
                await create_tables_mysql(conn, logger, TimeUtils)
                logger.info("✅ تم إنشاء جداول MySQL عبر database_tables.py")
            else:
                await create_tables_sqlite(conn, logger, TimeUtils)
                logger.info("✅ تم إنشاء جداول SQLite عبر database_tables.py")

    # =====================================================================
    # ترحيل المخطط
    # =====================================================================

    async def _add_column_safe(self, conn, table: str, col_name: str, col_def: str):
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table) or not re.match(
            r"^[a-zA-Z_][a-zA-Z0-9_]*$", col_name
        ):
            return
        try:
            if USE_POSTGRES:
                exists = await conn.fetchval(
                    "SELECT 1 FROM information_schema.columns WHERE table_name = $1 AND column_name = $2",
                    table, col_name,
                )
                if not exists:
                    await conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col_name}" {col_def}')
                    logger.info(f"✅ أُضيف العمود {col_name} إلى جدول {table}")
                    if table == "group_security":
                        self._group_security_columns_cache = None
            elif USE_MYSQL:
                cursor = await conn.cursor()
                await cursor.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", (col_name,))
                exists = await cursor.fetchone()
                await cursor.close()
                if not exists:
                    await conn.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col_name}` {col_def}")
                    logger.info(f"✅ أُضيف العمود {col_name} إلى جدول {table}")
                    if table == "group_security":
                        self._group_security_columns_cache = None
            else:
                cursor = await conn.execute(f"PRAGMA table_info({table})")
                rows = await cursor.fetchall()
                exists = any(row[1] == col_name for row in rows)
                if not exists:
                    await conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                    logger.info(f"✅ أُضيف العمود {col_name} إلى جدول {table}")
                    if table == "group_security":
                        self._group_security_columns_cache = None
        except Exception as e:
            if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                logger.warning(f"⚠️ فشل إضافة العمود {col_name} إلى {table}: {e}")

    async def _column_exists(self, conn, table: str, column: str) -> bool:
        try:
            if USE_POSTGRES:
                row = await conn.fetchval(
                    "SELECT 1 FROM information_schema.columns WHERE table_name = $1 AND column_name = $2",
                    table, column,
                )
                return row is not None
            elif USE_MYSQL:
                cursor = await conn.cursor()
                await cursor.execute(f"SHOW COLUMNS FROM `{table}` LIKE '{column}'")
                row = await cursor.fetchone()
                await cursor.close()
                return row is not None
            else:
                cursor = await conn.execute(f"PRAGMA table_info({table})")
                rows = await cursor.fetchall()
                return any(row[1] == column for row in rows)
        except Exception as e:
            logger.warning(f"⚠️ فشل التحقق من وجود العمود {column} في {table}: {e}")
            return False

    async def _ensure_text_hash_column(self, conn) -> bool:
        try:
            if not await _table_exists(conn, "posts"):
                logger.warning("⚠️ جدول posts غير موجود، لا يمكن إضافة text_hash")
                return False
            if await self._column_exists(conn, "posts", "text_hash"):
                return True
            try:
                if USE_POSTGRES:
                    await conn.execute("ALTER TABLE posts ADD COLUMN text_hash TEXT DEFAULT ''")
                elif USE_MYSQL:
                    await conn.execute("ALTER TABLE posts ADD COLUMN text_hash CHAR(64) DEFAULT ''")
                else:
                    await conn.execute("ALTER TABLE posts ADD COLUMN text_hash TEXT DEFAULT ''")
                logger.info("✅ تم إضافة عمود text_hash إلى posts")

                if not await self._index_exists(conn, "posts", "idx_posts_text_hash"):
                    try:
                        await conn.execute("CREATE INDEX idx_posts_text_hash ON posts(text_hash)")
                        logger.info("✅ تم إنشاء فهرس idx_posts_text_hash")
                    except Exception as e:
                        if "duplicate" not in str(e).lower():
                            logger.warning(f"⚠️ فشل إنشاء فهرس text_hash: {e}")
                return True
            except Exception as e:
                logger.error(f"❌ فشل إضافة عمود text_hash: {e}")
                return False
        except Exception as e:
            logger.error(f"❌ خطأ في _ensure_text_hash_column: {e}")
            return False

    async def _migrate_schema(self, conn):
        if USE_MYSQL:
            await conn.execute("SET FOREIGN_KEY_CHECKS=0")
        try:
            migrations = {
                "group_security": [
                    ("antiflood_penalty_duration", "INTEGER DEFAULT 3600"),
                    ("night_mode_action_duration", "INTEGER DEFAULT 3600"),
                    ("warn_penalty_duration", "INTEGER DEFAULT 3600"),
                    ("mute_default_duration", "INTEGER DEFAULT 3600"),
                    ("ban_default_duration", "INTEGER DEFAULT 0"),
                    ("warn_default_duration", "INTEGER DEFAULT 0"),
                    ("restrict_default_duration", "INTEGER DEFAULT 1800"),
                    ("enable_timed_penalties", "INTEGER DEFAULT 1"),
                    ("auto_remove_penalties", "INTEGER DEFAULT 1"),
                    ("violation_strikes", "INTEGER DEFAULT 3"),
                    ("violation_duration", "INTEGER DEFAULT 60"),
                    ("delete_links", "INTEGER DEFAULT 0"),
                    ("mentions", "INTEGER DEFAULT 0"),
                    ("delete_videos", "INTEGER DEFAULT 0"),
                    ("delete_audio", "INTEGER DEFAULT 0"),
                    ("delete_animation", "INTEGER DEFAULT 0"),
                    ("delete_service", "INTEGER DEFAULT 0"),
                    ("delete_documents", "INTEGER DEFAULT 0"),
                    ("delete_stickers", "INTEGER DEFAULT 0"),
                    ("delete_forwarded", "INTEGER DEFAULT 0"),
                    ("delete_polls", "INTEGER DEFAULT 0"),
                    ("delete_games", "INTEGER DEFAULT 0"),
                    ("delete_voice", "INTEGER DEFAULT 0"),
                    ("delete_video_note", "INTEGER DEFAULT 0"),
                    ("delete_photos", "INTEGER DEFAULT 0"),
                    ("delete_banned_words", "INTEGER DEFAULT 0"),
                    ("antiflood_enabled", "INTEGER DEFAULT 0"),
                    ("antiflood_messages", "INTEGER DEFAULT 5"),
                    ("antiflood_seconds", "INTEGER DEFAULT 10"),
                    ("antiflood_penalty", "TEXT DEFAULT 'mute'"),
                    ("night_mode_enabled", "INTEGER DEFAULT 0"),
                    ("night_mode_start", "TEXT DEFAULT '23:00'"),
                    ("night_mode_end", "TEXT DEFAULT '07:00'"),
                    ("night_mode_action", "TEXT DEFAULT 'mute'"),
                    ("warn_enabled", "INTEGER DEFAULT 0"),
                    ("max_warnings", "INTEGER DEFAULT 3"),
                    ("warn_penalty", "TEXT DEFAULT 'mute'"),
                    ("welcome_enabled", "INTEGER DEFAULT 0"),
                    ("welcome_text", "TEXT DEFAULT ''"),
                    ("goodbye_enabled", "INTEGER DEFAULT 0"),
                    ("goodbye_text", "TEXT DEFAULT ''"),
                    ("auto_approve_join", "INTEGER DEFAULT 0"),
                    ("auto_reject_join", "INTEGER DEFAULT 0"),
                    ("slow_mode", "INTEGER DEFAULT 0"),
                    ("slow_mode_seconds", "INTEGER DEFAULT 0"),
                    ("max_message_length", "INTEGER DEFAULT 0"),
                    ("nsfw_enabled", "INTEGER DEFAULT 0"),
                    ("nsfw_threshold", "REAL DEFAULT 0.8"),
                    ("nsfw_filter", "INTEGER DEFAULT 0"),
                    ("auto_penalty", "TEXT DEFAULT 'mute'"),
                    ("auto_mute_duration", "INTEGER DEFAULT 3600"),
                    ("delete_penalty", "INTEGER DEFAULT 0"),
                    ("delete_penalty_duration", "INTEGER DEFAULT 3600"),
                    ("delete_penalty_messages", "INTEGER DEFAULT 0"),
                ],
                "users": [
                    ("active_channel", "INTEGER DEFAULT NULL"),
                ],
                "auto_replies": [
                    ("usage_count", "INTEGER DEFAULT 0"),
                ],
                "anonymous_admins": [
                    ("user_id", "INTEGER"),
                ],
                "posts": [
                    ("text_hash", "TEXT DEFAULT ''"),
                    ("published_at", "TIMESTAMP"),
                    ("fail_count", "INTEGER DEFAULT 0"),
                ],
                "user_reminder_settings": [
                    ("subscription_reminder", "INTEGER DEFAULT 1"),
                    ("daily_stats_reminder", "INTEGER DEFAULT 0"),
                    ("weekly_report", "INTEGER DEFAULT 1"),
                    ("reminder_days_before", "INTEGER DEFAULT 3"),
                    ("last_reminder_sent", "TIMESTAMP"),
                    ("notification_lang", "TEXT DEFAULT 'ar'"),
                ],
                "user_translation": [
                    ("lang", "TEXT DEFAULT 'off'"),
                ],
            }
            for table, columns in migrations.items():
                existing = await self._get_existing_columns(conn, table)
                for col_name, col_def in columns:
                    if col_name not in existing:
                        await self._add_column_safe(conn, table, col_name, col_def)
            await self._ensure_text_hash_column(conn)
            self._group_security_columns_cache = None
        finally:
            if USE_MYSQL:
                await conn.execute("SET FOREIGN_KEY_CHECKS=1")

    async def _get_existing_columns(self, conn, table: str) -> set:
        try:
            if USE_POSTGRES:
                rows = await conn.fetch(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = $1",
                    table,
                )
                return {row["column_name"] for row in rows}
            elif USE_MYSQL:
                if not await _table_exists(conn, table):
                    return set()
                cursor = await conn.cursor()
                await cursor.execute(f"SHOW COLUMNS FROM `{table}`")
                rows = await cursor.fetchall()
                await cursor.close()
                return {row[0] for row in rows}
            else:
                cursor = await conn.execute(f"PRAGMA table_info({table})")
                rows = await cursor.fetchall()
                return {row[1] for row in rows}
        except Exception:
            return set()

    async def _index_exists(self, conn, table: str, idx_name: str) -> bool:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table) or not re.match(
            r"^[a-zA-Z_][a-zA-Z0-9_]*$", idx_name
        ):
            return False
        try:
            if USE_POSTGRES:
                row = await conn.fetchval("SELECT 1 FROM pg_indexes WHERE indexname = $1", idx_name)
                return row is not None
            elif USE_MYSQL:
                if not await _table_exists(conn, table):
                    return False
                cursor = await conn.cursor()
                await cursor.execute(f"SHOW INDEX FROM `{table}` WHERE Key_name = %s", (idx_name,))
                rows = await cursor.fetchall()
                await cursor.close()
                return len(rows) > 0
            else:
                cursor = await conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (idx_name,)
                )
                row = await cursor.fetchone()
                return row is not None
        except Exception:
            return False

    async def _create_secondary_indexes(self, indexes):
        try:
            async with self.connection() as conn:
                created = 0
                skipped = 0
                failed = 0
                for table, idx_name, create_sql in indexes:
                    try:
                        if await self._index_exists(conn, table, idx_name):
                            skipped += 1
                            continue
                        await conn.execute(create_sql)
                        logger.info(f"✅ تم إنشاء فهرس ثانوي {idx_name}")
                        created += 1
                    except Exception as e:
                        if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                            logger.warning(f"⚠️ فشل إنشاء فهرس {idx_name}: {e}")
                            failed += 1
                logger.info(
                    f"📊 انتهى إنشاء الفهارس: ✅ {created} جديد | ⏭️ {skipped} موجود | ❌ {failed} فشل"
                )
        except asyncio.CancelledError:
            logger.info("🛑 مهمة إنشاء الفهارس الثانوية تم إلغاؤها")
        except Exception as e:
            logger.error(f"❌ فشل إنشاء الفهارس الثانوية: {e}")

    # =====================================================================
    # البيانات الافتراضية والاستيراد
    # =====================================================================

    async def _init_default_data(self, conn):
        default_plans = [
            {"name": "تجربة", "description": "تجربة مجانية لمدة 30 يوم", "price": 0, "duration_days": 30, "max_channels": 100, "max_posts": 200, "features": '{"auto_publish":true,"security":true}', "is_gift": 0},
            {"name": "يوم", "description": "باقة يوم واحد", "price": 5, "duration_days": 1, "max_channels": 1, "max_posts": 50, "features": '{"auto_publish":true}', "is_gift": 0},
            {"name": "أسبوع", "description": "باقة 7 أيام", "price": 25, "duration_days": 7, "max_channels": 3, "max_posts": 300, "features": '{"auto_publish":true,"security":true}', "is_gift": 0},
            {"name": "شهر", "description": "باقة 30 يوم", "price": 75, "duration_days": 30, "max_channels": 10, "max_posts": 1500, "features": '{"auto_publish":true,"security":true,"support":true}', "is_gift": 0},
            {"name": "3 أشهر", "description": "باقة 90 يوم", "price": 200, "duration_days": 90, "max_channels": 25, "max_posts": 5000, "features": '{"auto_publish":true,"security":true,"support":true,"analytics":true}', "is_gift": 0},
            {"name": "سنة", "description": "باقة 365 يوم", "price": 700, "duration_days": 365, "max_channels": 100, "max_posts": 99999, "features": '{"auto_publish":true,"security":true,"support":true,"analytics":true,"priority":true}', "is_gift": 0},
            {"name": "هدية شهر", "description": "كود هدية لمدة 30 يوم", "price": 75, "duration_days": 30, "max_channels": 100, "max_posts": 1500, "features": '{}', "is_gift": 1},
        ]
        for plan in default_plans:
            if USE_POSTGRES:
                existing = await conn.fetchval("SELECT id FROM plans WHERE name = $1", plan["name"])
                if not existing:
                    await conn.execute(
                        """INSERT INTO plans (name, description, price, currency, duration_days, max_channels, max_posts, features, is_active, is_gift, created_at)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
                        plan["name"], plan["description"], plan["price"], "XTR",
                        plan["duration_days"], plan["max_channels"], plan["max_posts"],
                        plan["features"], 1, plan["is_gift"], TimeUtils.utc_now(),
                    )
                else:
                    await conn.execute(
                        "UPDATE plans SET max_channels = $1, max_posts = $2 WHERE name = $3",
                        plan["max_channels"], plan["max_posts"], plan["name"],
                    )
            elif USE_MYSQL:
                cursor = await conn.cursor()
                await cursor.execute("SELECT id FROM plans WHERE name = %s", (plan["name"],))
                existing = await cursor.fetchone()
                await cursor.close()
                if not existing:
                    await conn.execute(
                        """INSERT INTO plans (name, description, price, currency, duration_days, max_channels, max_posts, features, is_active, is_gift, created_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (plan["name"], plan["description"], plan["price"], "XTR",
                         plan["duration_days"], plan["max_channels"], plan["max_posts"],
                         plan["features"], 1, plan["is_gift"], TimeUtils.sql_iso()),
                    )
                else:
                    await conn.execute(
                        "UPDATE plans SET max_channels = %s, max_posts = %s WHERE name = %s",
                        (plan["max_channels"], plan["max_posts"], plan["name"]),
                    )
            else:
                cursor = await conn.execute("SELECT id FROM plans WHERE name = ?", (plan["name"],))
                existing = await cursor.fetchone()
                if not existing:
                    await conn.execute(
                        """INSERT INTO plans (name, description, price, currency, duration_days, max_channels, max_posts, features, is_active, is_gift, created_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (plan["name"], plan["description"], plan["price"], "XTR",
                         plan["duration_days"], plan["max_channels"], plan["max_posts"],
                         plan["features"], 1, plan["is_gift"], TimeUtils.sql_iso()),
                    )
                else:
                    await conn.execute(
                        "UPDATE plans SET max_channels = ?, max_posts = ? WHERE name = ?",
                        (plan["max_channels"], plan["max_posts"], plan["name"]),
                    )

    async def _import_banned_words(self, conn):
        """
        ✅ v7.5.3: تحسين Cold Start - تخطي الاستيراد إذا كانت الكلمات موجودة.
        """
        try:
            existing_count = await self._fetchval_with_conn(
                conn,
                "SELECT COUNT(*) FROM banned_words WHERE chat_id = -1",
                default=0,
            )
            if existing_count and existing_count >= 100:
                logger.info(
                    f"ℹ️ تم تخطي استيراد الكلمات المحظورة "
                    f"({existing_count} موجودة مسبقاً)"
                )
                return

            import banned_words
            BANNED_WORDS = getattr(banned_words, "BANNED_WORDS", [])
            if not BANNED_WORDS:
                return
            owner_id = getattr(CONFIG, "PRIMARY_OWNER_ID", None)
            if not owner_id:
                logger.warning("⚠️ PRIMARY_OWNER_ID غير محدد — استخدام 1")
                owner_id = 1
            words_to_insert = []
            for word in BANNED_WORDS:
                word = str(word).strip().lower()
                if len(word) >= 2:
                    words_to_insert.append((word, -1, owner_id, TimeUtils.utc_now()))
            if words_to_insert:
                batch_size = 500
                for i in range(0, len(words_to_insert), batch_size):
                    batch = words_to_insert[i : i + batch_size]
                    await self._executemany_with_conn(
                        conn,
                        """INSERT OR IGNORE INTO banned_words (word, chat_id, added_by, added_at) VALUES (?, ?, ?, ?)""",
                        batch,
                    )
                logger.info(f"✅ تم استيراد {len(words_to_insert)} كلمة محظورة")
                if hasattr(self, "_invalidate_banned_words_local_cache"):
                    await self._invalidate_banned_words_local_cache()
                if CACHE_AVAILABLE:
                    await banned_words_cache.invalidate()
        except ImportError:
            logger.info("ℹ️ لا يوجد ملف banned_words.py")
        except Exception as e:
            logger.error(f"❌ خطأ في استيراد الكلمات المحظورة: {e}")

    async def _import_auto_replies(self, conn):
        """
        ✅ v7.5.3: تحسين Cold Start - تخطي الاستيراد إذا كانت الردود موجودة.
        """
        try:
            existing_count = await self._fetchval_with_conn(
                conn,
                "SELECT COUNT(*) FROM auto_replies WHERE chat_id = -1",
                default=0,
            )
            if existing_count and existing_count >= 100:
                logger.info(
                    f"ℹ️ تم تخطي استيراد الردود التلقائية "
                    f"({existing_count} موجودة مسبقاً)"
                )
                return

            from auto_replies import AUTO_REPLIES
            if not AUTO_REPLIES:
                return
            if isinstance(AUTO_REPLIES, dict):
                auto_replies_list = [AUTO_REPLIES]
            elif isinstance(AUTO_REPLIES, (list, tuple)):
                auto_replies_list = AUTO_REPLIES
            else:
                logger.warning("⚠️ AUTO_REPLIES يجب أن يكون قائمة أو قاموساً")
                return

            replies_to_insert = []
            for item in auto_replies_list:
                try:
                    if isinstance(item, dict):
                        chat_id = item.get("chat_id", -1)
                        keyword = str(item.get("keyword", "")).strip().lower()
                        reply = item.get("reply", "")
                        reply_type = item.get("reply_type", "text")
                        media_id = item.get("reply_media_id")
                        buttons = item.get("reply_buttons")
                    elif isinstance(item, (list, tuple)):
                        if len(item) == 2 and isinstance(item[0], str):
                            chat_id = -1
                            keyword = str(item[0]).strip().lower()
                            reply = item[1]
                            reply_type = "text"
                            media_id = None
                            buttons = None
                        elif len(item) >= 3 and isinstance(item[0], int):
                            chat_id = item[0]
                            keyword = str(item[1]).strip().lower()
                            reply = item[2]
                            reply_type = item[3] if len(item) > 3 and isinstance(item[3], str) else "text"
                            media_id = item[4] if len(item) > 4 else None
                            buttons = item[5] if len(item) > 5 else None
                        elif len(item) >= 2:
                            chat_id = -1
                            keyword = str(item[0]).strip().lower()
                            reply = item[1]
                            reply_type = item[2] if len(item) > 2 and isinstance(item[2], str) else "text"
                            media_id = item[3] if len(item) > 3 else None
                            buttons = item[4] if len(item) > 4 else None
                        else:
                            continue
                    else:
                        continue
                    if not keyword or reply_type not in self.VALID_REPLY_TYPES:
                        continue
                    replies_to_insert.append((
                        chat_id, keyword, reply, reply_type, media_id, buttons,
                        TimeUtils.utc_now(), 1, 0,
                    ))
                except Exception as e:
                    logger.warning(f"⚠️ تجاهل رد تلقائي غير صالح: {e}")

            if replies_to_insert:
                batch_size = 100
                for i in range(0, len(replies_to_insert), batch_size):
                    batch = replies_to_insert[i : i + batch_size]
                    await self._executemany_with_conn(
                        conn,
                        """INSERT OR IGNORE INTO auto_replies
                           (chat_id, keyword, reply, reply_type, reply_media_id, reply_buttons, created_at, is_active, usage_count)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        batch,
                    )
                logger.info(f"✅ تم استيراد {len(replies_to_insert)} رد تلقائي")
        except ImportError:
            logger.info("ℹ️ لا يوجد ملف auto_replies.py")
        except Exception as e:
            logger.error(f"❌ خطأ في استيراد الردود التلقائية: {e}")

    # =====================================================================
    # ✅ v7.5.2 — دوال الفهارس الثانوية (متوافقة مع SQLite / PostgreSQL / MySQL)
    # =====================================================================

    def _get_secondary_indexes(self) -> List[Tuple[str, str, str]]:
        """يُرجع قائمة الفهارس الثانوية المناسبة لنوع قاعدة البيانات."""
        if USE_MYSQL:
            return [
                ("posts", "idx_posts_fail_count",
                 "CREATE INDEX idx_posts_fail_count ON posts(fail_count)"),
                ("posts", "idx_posts_created_at",
                 "CREATE INDEX idx_posts_created_at ON posts(created_at)"),
                ("users", "idx_users_trial_used",
                 "CREATE INDEX idx_users_trial_used ON users(trial_used)"),
                ("banned_words", "idx_banned_words_word",
                 "CREATE INDEX idx_banned_words_word ON banned_words(word)"),
                ("auto_replies", "idx_auto_replies_keyword",
                 "CREATE INDEX idx_auto_replies_keyword ON auto_replies(keyword)"),
                ("referral_rewards", "idx_referral_rewards_count",
                 "CREATE INDEX idx_referral_rewards_count ON referral_rewards(referral_count)"),
                ("contest_participants", "idx_contest_participants_contest",
                 "CREATE INDEX idx_contest_participants_contest ON contest_participants(contest_id)"),
                ("gift_codes", "idx_gift_codes_plan",
                 "CREATE INDEX idx_gift_codes_plan ON gift_codes(plan_id)"),
                ("user_penalties", "idx_user_penalties_active_end",
                 "CREATE INDEX idx_user_penalties_active_end "
                 "ON user_penalties(status, end_time)"),
                ("posts", "idx_posts_published",
                 "CREATE INDEX idx_posts_published ON posts(published, published_at)"),
                ("posts", "idx_posts_channel_published",
                 "CREATE INDEX idx_posts_channel_published ON posts(channel_db_id, published)"),
                ("subscriptions", "idx_subscriptions_active_end",
                 "CREATE INDEX idx_subscriptions_active_end "
                 "ON subscriptions(user_id, status, end_date)"),
                ("user_reminder_settings", "idx_reminders_subscription",
                 "CREATE INDEX idx_reminders_subscription "
                 "ON user_reminder_settings(subscription_reminder, last_reminder_sent)"),
                ("user_violations", "idx_violations_user_chat",
                 "CREATE INDEX idx_violations_user_chat ON user_violations(user_id, chat_id)"),
            ]
        else:
            return [
                ("posts", "idx_posts_fail_count",
                 "CREATE INDEX IF NOT EXISTS idx_posts_fail_count ON posts(fail_count)"),
                ("posts", "idx_posts_created_at",
                 "CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at)"),
                ("users", "idx_users_trial_used",
                 "CREATE INDEX IF NOT EXISTS idx_users_trial_used ON users(trial_used)"),
                ("banned_words", "idx_banned_words_word",
                 "CREATE INDEX IF NOT EXISTS idx_banned_words_word ON banned_words(word)"),
                ("auto_replies", "idx_auto_replies_keyword",
                 "CREATE INDEX IF NOT EXISTS idx_auto_replies_keyword ON auto_replies(keyword)"),
                ("referral_rewards", "idx_referral_rewards_count",
                 "CREATE INDEX IF NOT EXISTS idx_referral_rewards_count ON referral_rewards(referral_count)"),
                ("contest_participants", "idx_contest_participants_contest",
                 "CREATE INDEX IF NOT EXISTS idx_contest_participants_contest ON contest_participants(contest_id)"),
                ("gift_codes", "idx_gift_codes_plan",
                 "CREATE INDEX IF NOT EXISTS idx_gift_codes_plan ON gift_codes(plan_id)"),
                ("user_penalties", "idx_user_penalties_active_end",
                 "CREATE INDEX IF NOT EXISTS idx_user_penalties_active_end "
                 "ON user_penalties(status, end_time) WHERE status = 'active'"),
                ("posts", "idx_posts_published",
                 "CREATE INDEX IF NOT EXISTS idx_posts_published "
                 "ON posts(published, published_at)"),
                ("posts", "idx_posts_channel_published",
                 "CREATE INDEX IF NOT EXISTS idx_posts_channel_published "
                 "ON posts(channel_db_id, published)"),
                ("subscriptions", "idx_subscriptions_active_end",
                 "CREATE INDEX IF NOT EXISTS idx_subscriptions_active_end "
                 "ON subscriptions(user_id, status, end_date) WHERE status = 'active'"),
                ("user_reminder_settings", "idx_reminders_subscription",
                 "CREATE INDEX IF NOT EXISTS idx_reminders_subscription "
                 "ON user_reminder_settings(subscription_reminder, last_reminder_sent)"),
                ("user_violations", "idx_violations_user_chat",
                 "CREATE INDEX IF NOT EXISTS idx_violations_user_chat "
                 "ON user_violations(user_id, chat_id)"),
            ]

    # =====================================================================
    # ✅ v7.5.8 — كاش has_active_subscription (لتقليل استعلامات /start)
    # =====================================================================

    async def has_active_subscription(self, user_id: int) -> bool:
        """
        ✅ v7.5.8: كاش 30 ثانية — يُستدعى كثيراً عند /start
        يقلل الضغط على DB بنسبة ~90% ويحل مشكلة البطء عند /start.
        """
        cache_key = f"has_active_sub_{user_id}"
        cached = await internal_cache.get(cache_key)
        if cached is not None:
            return cached

        # محاولة استخدام النسخة الأصلية من الـ Mixin
        try:
            result = await super().has_active_subscription(user_id)
        except AttributeError:
            # Fallback: استعلام مباشر (لو الدالة غير موجودة في Mixin)
            row = await self.fetchval(
                "SELECT 1 FROM subscriptions "
                "WHERE user_id = ? AND status = 'active' AND end_date > ? LIMIT 1",
                (user_id, TimeUtils.utc_now()),
            )
            result = row is not None

        await internal_cache.set(cache_key, result, ttl=30)
        return result

    async def invalidate_subscription_cache(self, user_id: int):
        """✅ v7.5.8: للاستدعاء عند تفعيل/إلغاء اشتراك"""
        await internal_cache.invalidate(f"has_active_sub_{user_id}")

    # =====================================================================
    # التهيئة الكاملة
    # =====================================================================

    async def initialize_db(self) -> bool:
        """التهيئة الكاملة لقاعدة البيانات."""
        try:
            await self.initialize()

            async with self.connection() as conn:
                await self._create_tables()
                await self._migrate_schema(conn)
                await self._init_default_data(conn)
                await self._import_banned_words(conn)
                await self._import_auto_replies(conn)
                await self._ensure_text_hash_column(conn)

            if self._secondary_index_task is None or self._secondary_index_task.done():
                secondary_indexes = self._get_secondary_indexes()
                logger.info(
                    f"📊 جدولة إنشاء {len(secondary_indexes)} فهرس ثانوي "
                    f"(DB={DB_TYPE.upper()})..."
                )
                self._secondary_index_task = asyncio.create_task(
                    self._create_secondary_indexes(secondary_indexes)
                )

            if CACHE_AVAILABLE and (
                self._cache_cleanup_task is None or self._cache_cleanup_task.done()
            ):
                self._cache_cleanup_task = asyncio.create_task(cache_cleanup_task())

            logger.info("✅ تم تهيئة قاعدة البيانات بنجاح (مع المهام الخلفية)")
            return True

        except Exception as e:
            logger.error(f"❌ فشل تهيئة قاعدة البيانات: {e}", exc_info=True)
            return False

    async def pre_initialize(self):
        """تهيئة مبكرة (تستخدم عادةً من startup hook أو preload)."""
        try:
            await self.initialize()

            async with self.connection() as conn:
                await self._create_tables()
                await self._migrate_schema(conn)
                await self._ensure_text_hash_column(conn)
                await self._init_default_data(conn)
                await self._import_banned_words(conn)
                await self._import_auto_replies(conn)

            if self._secondary_index_task is None or self._secondary_index_task.done():
                secondary_indexes = self._get_secondary_indexes()
                self._secondary_index_task = asyncio.create_task(
                    self._create_secondary_indexes(secondary_indexes)
                )

            if CACHE_AVAILABLE and (
                self._cache_cleanup_task is None or self._cache_cleanup_task.done()
            ):
                self._cache_cleanup_task = asyncio.create_task(cache_cleanup_task())

            logger.info("✅ تم التهيئة المبكرة لقاعدة البيانات (مع المهام الخلفية)")
            return True

        except Exception as e:
            logger.error(f"❌ فشل التهيئة المبكرة: {e}", exc_info=True)
            return False

    # ═══════════════════════════════════════════════════════════════════
    # 📌 الدوال المنقولة إلى Mixins (متاحة عبر الوراثة):
    #   → database_groups.py (GroupsMixin)        : 48 دالة
    #   → database_tickets.py (TicketsMixin)      : 4 دوال
    #   → database_contests.py (ContestsMixin)    : 8 دوال
    #   → database_stats.py (StatsMixin)          : 6 دوال
    #   → database_settings.py (SettingsMixin)    : 7 دوال
    #   → database_points.py (PointsMixin)        : 4 دوال
    #   → database_backup.py (BackupMixin)        : 6 دوال
    #   → database_reminders.py (RemindersMixin)  : 9 دوال
    # ═══════════════════════════════════════════════════════════════════

    # =====================================================================
    # دوال المستخدمين
    # =====================================================================

    async def get_user_full_data(self, user_id: int, include_stats: bool = True) -> Optional[Dict]:
        query = """
            SELECT u.user_id, u.username, u.first_name, u.language, u.auto_publish, u.auto_recycle,
                   u.banned, u.trial_used, u.subscription_end, u.active_channel,
                   uc.id as channel_id, uc.channel_name, uc.banned as channel_banned
            FROM users u
            LEFT JOIN user_channels uc ON u.active_channel = uc.id AND uc.banned = 0
            WHERE u.user_id = ?
        """
        row = await self.fetchone(query, (user_id,))
        if not row:
            return None
        result = dict(row)
        if include_stats:
            stats = await self.fetchone(
                """
                SELECT
                    COALESCE((SELECT COUNT(*) FROM posts p JOIN user_channels uc2 ON p.channel_db_id = uc2.id WHERE uc2.user_id = ? AND p.published = 0), 0) as unpublished_posts,
                    COALESCE((SELECT 1 FROM subscriptions WHERE user_id = ? AND status = 'active' AND end_date > ?), 0) as has_subscription,
                    COALESCE((SELECT COUNT(*) FROM user_channels WHERE user_id = ? AND banned = 0), 0) as channels_count,
                    COALESCE((SELECT COUNT(*) FROM user_groups_link WHERE user_id = ?), 0) as groups_count
                """,
                (user_id, user_id, TimeUtils.utc_now(), user_id, user_id),
            )
            if stats:
                result["unpublished_posts"] = stats.get("unpublished_posts", 0)
                result["has_subscription"] = bool(stats.get("has_subscription", 0))
                result["channels_count"] = stats.get("channels_count", 0)
                result["groups_count"] = stats.get("groups_count", 0)
        else:
            result["has_subscription"] = False
            result["unpublished_posts"] = 0
            result["channels_count"] = 0
            result["groups_count"] = 0
        result["channel_info"] = None
        if result.get("channel_id"):
            result["channel_info"] = {
                "id": result["channel_id"],
                "channel_name": result.get("channel_name", ""),
                "banned": result.get("channel_banned", 0),
            }
        return result

    async def get_user(self, user_id: int, include_stats: bool = False) -> Optional[Dict]:
        try:
            if CACHE_AVAILABLE:
                cached_data = await user_cache.get(user_id)
                if cached_data:
                    user_data = cached_data.get("user_data")
                    if user_data:
                        if include_stats:
                            user_data["unpublished_posts"] = cached_data.get("unpublished_posts", 0)
                            user_data["has_subscription"] = cached_data.get("has_subscription", False)
                            user_data["channels_count"] = cached_data.get("channels_count", 0)
                            user_data["groups_count"] = cached_data.get("groups_count", 0)
                            user_data["channel_info"] = cached_data.get("channel_info")
                        return user_data

            cached = await internal_cache.get(f"user_{user_id}_{include_stats}")
            if cached:
                return cached

            query = """
                SELECT u.user_id, u.username, u.first_name, u.language, u.auto_publish, u.auto_recycle,
                       u.banned, u.trial_used, u.subscription_end, u.active_channel,
                       uc.id as channel_id, uc.channel_name, uc.banned as channel_banned,
                       (SELECT COUNT(*) FROM posts p WHERE p.channel_db_id = uc.id AND p.published = 0) as unpublished_posts,
                       EXISTS(SELECT 1 FROM subscriptions s WHERE s.user_id = u.user_id AND s.status = 'active' AND s.end_date > __NOW__) as has_subscription,
                       (SELECT COUNT(*) FROM user_channels uc2 WHERE uc2.user_id = u.user_id AND uc2.banned = 0) as channels_count,
                       (SELECT COUNT(*) FROM user_groups_link l WHERE l.user_id = u.user_id) as groups_count
                FROM users u
                LEFT JOIN user_channels uc ON u.active_channel = uc.id AND uc.banned = 0
                WHERE u.user_id = ?
            """
            if USE_POSTGRES:
                query = query.replace("__NOW__", "NOW()")
            elif USE_MYSQL:
                query = query.replace("__NOW__", "UTC_TIMESTAMP()")
            else:
                query = query.replace("__NOW__", "datetime('now')")

            row = await self.fetchone(query, (user_id,))
            if not row:
                return None
            data = dict(row)
            data["has_subscription"] = bool(data.get("has_subscription", 0))
            await internal_cache.set(f"user_{user_id}_{include_stats}", data)
            if CACHE_AVAILABLE and not include_stats:
                full_data = {
                    "user_data": data,
                    "language": data.get("language", "ar"),
                    "active_channel": data.get("active_channel"),
                    "channel_info": {
                        "id": data.get("channel_id"),
                        "channel_name": data.get("channel_name"),
                        "banned": data.get("channel_banned", 0),
                    } if data.get("channel_id") else None,
                    "unpublished_posts": data.get("unpublished_posts", 0),
                    "has_subscription": data.get("has_subscription", False),
                    "auto_publish": data.get("auto_publish", True),
                    "auto_recycle": data.get("auto_recycle", True),
                    "groups_count": data.get("groups_count", 0),
                    "channels_count": data.get("channels_count", 0),
                }
                await user_cache.set(user_id, full_data)
            return data
        except Exception as e:
            logger.error(f"❌ Error in get_user: {e}", exc_info=True)
            return None

    async def register_user(self, user_id: int, username: str = "", first_name: str = "") -> bool:
        try:
            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    user_inserted = False
                    for attempt in range(5):
                        code = secrets.token_urlsafe(9)
                        try:
                            if USE_POSTGRES:
                                await self._execute_with_conn(
                                    conn,
                                    """INSERT INTO users (user_id, username, first_name, referral_code, trial_used, created_at, updated_at)
                                       VALUES ($1, $2, $3, $4, 0, $5, $6)
                                       ON CONFLICT(user_id) DO UPDATE SET
                                           username = CASE WHEN $2 != '' THEN $2 ELSE users.username END,
                                           first_name = CASE WHEN $3 != '' THEN $3 ELSE users.first_name END,
                                           updated_at = $6""",
                                    user_id, username, first_name, code,
                                    TimeUtils.utc_now(), TimeUtils.utc_now(),
                                )
                            elif USE_MYSQL:
                                await self._execute_with_conn(
                                    conn,
                                    """INSERT INTO users (user_id, username, first_name, referral_code, trial_used, created_at, updated_at)
                                       VALUES (%s, %s, %s, %s, 0, %s, %s)
                                       ON DUPLICATE KEY UPDATE
                                           username = CASE WHEN %s != '' THEN %s ELSE users.username END,
                                           first_name = CASE WHEN %s != '' THEN %s ELSE users.first_name END,
                                           updated_at = %s""",
                                    user_id, username, first_name, code,
                                    TimeUtils.sql_iso(), TimeUtils.sql_iso(),
                                    username, username, first_name, first_name, TimeUtils.sql_iso(),
                                )
                            else:
                                await self._execute_with_conn(
                                    conn,
                                    """INSERT INTO users (user_id, username, first_name, referral_code, trial_used, created_at, updated_at)
                                       VALUES (?, ?, ?, ?, 0, ?, ?)
                                       ON CONFLICT(user_id) DO UPDATE SET
                                           username = CASE WHEN ? != '' THEN ? ELSE users.username END,
                                           first_name = CASE WHEN ? != '' THEN ? ELSE users.first_name END,
                                           updated_at = ?""",
                                    user_id, username, first_name, code,
                                    TimeUtils.sql_iso(), TimeUtils.sql_iso(),
                                    username, username, first_name, first_name, TimeUtils.sql_iso(),
                                )
                            user_inserted = True
                            break
                        except Exception as e:
                            err = str(e).lower()
                            if "referral_code" in err:
                                logger.warning(f"⚠️ تصادم referral_code للمستخدم {user_id}، محاولة {attempt + 1}/5")
                                continue
                            if "unique" in err or "duplicate" in err:
                                user_inserted = True
                                break
                            raise

                    if not user_inserted:
                        logger.error(f"❌ فشل إدراج المستخدم {user_id} بعد 5 محاولات")
                        return False

                    if USE_POSTGRES:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO user_points (user_id, points, last_updated) VALUES ($1, 0, $2) ON CONFLICT(user_id) DO UPDATE SET last_updated = $2",
                            user_id, TimeUtils.utc_now(),
                        )
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days, last_referral_date) VALUES ($1, 0, 0, 0, NULL) ON CONFLICT DO NOTHING",
                            user_id,
                        )
                    elif USE_MYSQL:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO user_points (user_id, points, last_updated) VALUES (%s, 0, %s) ON DUPLICATE KEY UPDATE last_updated = VALUES(last_updated)",
                            user_id, TimeUtils.sql_iso(),
                        )
                        await self._execute_with_conn(
                            conn,
                            "INSERT IGNORE INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days, last_referral_date) VALUES (%s, 0, 0, 0, NULL)",
                            user_id,
                        )
                    else:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO user_points (user_id, points, last_updated) VALUES (?, 0, ?) ON CONFLICT(user_id) DO UPDATE SET last_updated = excluded.last_updated",
                            user_id, TimeUtils.sql_iso(),
                        )
                        await self._execute_with_conn(
                            conn,
                            "INSERT OR IGNORE INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days, last_referral_date) VALUES (?, 0, 0, 0, NULL)",
                            user_id,
                        )
            await internal_cache.invalidate(f"user_{user_id}")
            if CACHE_AVAILABLE:
                await invalidate_user_cache(user_id)
            return True
        except Exception as e:
            logger.error(f"❌ Error in register_user: {e}", exc_info=True)
            return False

    async def get_user_language(self, user_id: int) -> str:
        try:
            if CACHE_AVAILABLE:
                cached_data = await user_cache.get(user_id)
                if cached_data:
                    return cached_data.get("language", "ar")
            cached_lang = await internal_cache.get(f"lang_{user_id}")
            if cached_lang:
                return cached_lang
            result = await self.fetchval("SELECT language FROM users WHERE user_id = ?", (user_id,), default="ar")
            lang = result if result else "ar"
            await internal_cache.set(f"lang_{user_id}", lang)
            return lang
        except Exception as e:
            logger.error(f"❌ Error in get_user_language: {e}")
            return "ar"

    async def set_user_language(self, user_id: int, lang: str) -> bool:
        result = await self.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id)) > 0
        if result:
            await internal_cache.invalidate(f"user_{user_id}")
            await internal_cache.invalidate(f"lang_{user_id}")
            if CACHE_AVAILABLE:
                await invalidate_user_cache(user_id)
        return result

    # ✅ v7.5.9: get_auto_publish_status مع كاش (كان بدون كاش — سبب البطء)
    async def get_auto_publish_status(self, user_id: int) -> bool:
        """
        ✅ v7.5.9: كاش 60 ثانية — كان يستدعي DB في كل ضغطة زر.
        يحل مشكلة الاستعلامات البطيئة (1.5-2s) عند فتح الإعدادات.
        """
        cache_key = f"auto_publish_{user_id}"
        cached = await internal_cache.get(cache_key)
        if cached is not None:
            return cached
        result = await self.fetchval(
            "SELECT auto_publish FROM users WHERE user_id = ?",
            (user_id,),
            default=1,
        )
        is_enabled = result == 1
        await internal_cache.set(cache_key, is_enabled, ttl=60)
        return is_enabled

    # ✅ v7.5.9: set_auto_publish يُبطل الكاش الجديد
    async def set_auto_publish(self, user_id: int, status: bool) -> bool:
        result = await self.execute(
            "UPDATE users SET auto_publish = ? WHERE user_id = ?",
            (1 if status else 0, user_id),
        ) > 0
        if result:
            await internal_cache.invalidate(f"user_{user_id}")
            await internal_cache.invalidate(f"auto_publish_{user_id}")           # ✅ v7.5.9
            await internal_cache.invalidate(f"user_settings_batch_{user_id}")    # ✅ v7.5.9
            if CACHE_AVAILABLE:
                await invalidate_user_cache(user_id)
        return result

    async def get_auto_recycle_status(self, user_id: int) -> bool:
        cache_key = f"auto_recycle_{user_id}"
        cached = await internal_cache.get(cache_key)
        if cached is not None:
            return cached
        result = await self.fetchval("SELECT auto_recycle FROM users WHERE user_id = ?", (user_id,), default=1)
        is_enabled = result == 1
        await internal_cache.set(cache_key, is_enabled, ttl=60)
        return is_enabled

    async def set_auto_recycle(self, user_id: int, status: bool) -> bool:
        result = await self.execute(
            "UPDATE users SET auto_recycle = ? WHERE user_id = ?",
            (1 if status else 0, user_id),
        ) > 0
        if result:
            await internal_cache.invalidate(f"user_{user_id}")
            await internal_cache.invalidate(f"auto_recycle_{user_id}")
            await internal_cache.invalidate(f"user_settings_batch_{user_id}")    # ✅ v7.5.9
            if CACHE_AVAILABLE:
                await invalidate_user_cache(user_id)
        return result

    # ✅ v7.5.9: دالة batch — استعلام واحد بدل اثنين
    async def get_user_settings_batch(self, user_id: int) -> Dict[str, Any]:
        """
        ✅ v7.5.9: جلب auto_publish + auto_recycle + language في استعلام واحد.
        تُستخدم في CB.SETTINGS و CB.TOGGLE_AUTO و CB.TOGGLE_REC
        لتقليل عدد الاستعلامات من 2 إلى 1 + كاش 60 ثانية.
        """
        cache_key = f"user_settings_batch_{user_id}"
        cached = await internal_cache.get(cache_key)
        if cached is not None:
            return cached

        row = await self.fetchone(
            "SELECT auto_publish, auto_recycle, language FROM users WHERE user_id = ?",
            (user_id,),
        )
        if not row:
            data = {'auto_publish': True, 'auto_recycle': True, 'language': 'ar'}
        else:
            data = {
                'auto_publish': row.get('auto_publish', 1) == 1,
                'auto_recycle': row.get('auto_recycle', 1) == 1,
                'language': row.get('language') or 'ar',
            }
        await internal_cache.set(cache_key, data, ttl=60)
        return data

    async def is_user_banned(self, user_id: int) -> bool:
        result = await self.fetchval("SELECT banned FROM users WHERE user_id = ?", (user_id,), default=0)
        return result == 1

    async def ban_user(self, user_id: int) -> bool:
        result = await self.execute("UPDATE users SET banned = 1 WHERE user_id = ?", (user_id,)) > 0
        if result:
            await internal_cache.invalidate(f"user_{user_id}")
            await internal_cache.invalidate(f"user_{user_id}_True")
            await internal_cache.invalidate(f"user_{user_id}_False")
            if CACHE_AVAILABLE:
                await invalidate_user_cache(user_id)
        return result

    async def unban_user(self, user_id: int) -> bool:
        result = await self.execute("UPDATE users SET banned = 0 WHERE user_id = ?", (user_id,)) > 0
        if result:
            await internal_cache.invalidate(f"user_{user_id}")
            await internal_cache.invalidate(f"user_{user_id}_True")
            await internal_cache.invalidate(f"user_{user_id}_False")
            if CACHE_AVAILABLE:
                await invalidate_user_cache(user_id)
        return result

    async def get_all_users(self, limit: int = 10000, offset: int = 0) -> List[Dict]:
        return await self.fetchall(
            "SELECT user_id, banned FROM users ORDER BY user_id LIMIT ? OFFSET ?",
            (limit, offset),
        )

    async def iter_all_users(self, batch_size: int = 1000) -> AsyncGenerator[Dict, None]:
        offset = 0
        while True:
            batch = await self.get_all_users(limit=batch_size, offset=offset)
            if not batch:
                break
            for user in batch:
                yield user
            offset += batch_size
            if len(batch) < batch_size:
                break

    async def mark_users_as_blocked(self, user_ids: List[int]) -> int:
        if not user_ids:
            return 0
        try:
            async with self.transaction() as conn:
                BATCH = 500
                total_updated = 0
                for i in range(0, len(user_ids), BATCH):
                    batch = user_ids[i : i + BATCH]
                    placeholders = ",".join(["?"] * len(batch))
                    updated = await self._execute_with_conn(
                        conn,
                        f"UPDATE users SET banned = 1 WHERE user_id IN ({placeholders})",
                        *batch,
                    )
                    total_updated += updated
                    for uid in batch:
                        await internal_cache.invalidate(f"user_{uid}")
                        await internal_cache.invalidate(f"user_{uid}_True")
                        await internal_cache.invalidate(f"user_{uid}_False")
                if CACHE_AVAILABLE:
                    for uid in user_ids:
                        await invalidate_user_cache(uid)
            return total_updated
        except Exception as e:
            logger.error(f"❌ Error in mark_users_as_blocked: {e}", exc_info=True)
            return 0

    # =====================================================================
    # دوال الجدولة
    # =====================================================================

    async def get_schedule(self, channel_db_id: int) -> Dict:
        schedule = await self.fetchone("SELECT * FROM schedule WHERE channel_db_id = ?", (channel_db_id,))
        if schedule:
            return schedule
        await self.execute(
            "INSERT OR IGNORE INTO schedule (channel_db_id, schedule_type, interval_minutes) VALUES (?, 'interval_minutes', 12)",
            (channel_db_id,),
        )
        schedule = await self.fetchone("SELECT * FROM schedule WHERE channel_db_id = ?", (channel_db_id,))
        return schedule if schedule else {}

    async def update_schedule(self, channel_db_id: int, **kwargs) -> bool:
        if not kwargs:
            return False
        allowed_columns = {
            "schedule_type", "interval_minutes", "interval_hours", "interval_days",
            "days_of_week", "specific_dates", "publish_time", "cron_expression",
            "next_publish_date",
        }
        for key in kwargs:
            if key not in allowed_columns:
                logger.error(f"❌ Invalid column: {key}")
                return False
        updates = [f"{key} = ?" for key in kwargs]
        values = list(kwargs.values()) + [channel_db_id]
        query = f"UPDATE schedule SET {', '.join(updates)} WHERE channel_db_id = ?"
        return await self.execute(query, tuple(values)) > 0

    async def update_next_publish(self, channel_db_id: int) -> bool:
        async with self.transaction() as conn:
            schedule = await self._fetchone_with_conn(
                conn, "SELECT * FROM schedule WHERE channel_db_id = ?", channel_db_id
            )
            if not schedule:
                await self._execute_with_conn(
                    conn,
                    "INSERT OR IGNORE INTO schedule (channel_db_id, schedule_type, interval_minutes) VALUES (?, 'interval_minutes', 12)",
                    channel_db_id,
                )
                schedule = await self._fetchone_with_conn(
                    conn, "SELECT * FROM schedule WHERE channel_db_id = ?", channel_db_id
                )
            last_publish = await self._fetchval_with_conn(
                conn, "SELECT last_publish_time FROM last_publish WHERE channel_db_id = ?", channel_db_id
            )
            last_time = TimeUtils.safe_parse_iso(last_publish) if last_publish else TimeUtils.utc_now()
            if isinstance(last_time, str):
                last_time = TimeUtils.safe_parse_iso(last_time) or TimeUtils.utc_now()

            schedule_type = schedule.get("schedule_type", "interval_minutes")
            if schedule_type == "interval_minutes":
                interval_seconds = max(1, schedule.get("interval_minutes", 12)) * 60
            elif schedule_type == "interval_hours":
                interval_seconds = max(1, schedule.get("interval_hours", 1)) * 3600
            elif schedule_type == "interval_days":
                interval_seconds = max(1, schedule.get("interval_days", 1)) * 86400
            else:
                interval_seconds = 12 * 60

            next_date = last_time + timedelta(seconds=interval_seconds)
            delay_seconds = (channel_db_id % 60) * 5
            next_date += timedelta(seconds=delay_seconds)

            now = TimeUtils.utc_now()
            if next_date <= now:
                delta = now - last_time
                intervals_needed = int(delta.total_seconds() // interval_seconds) + 1
                next_date = last_time + timedelta(seconds=interval_seconds * intervals_needed)
                next_date += timedelta(seconds=delay_seconds)

            await self._execute_with_conn(
                conn, "UPDATE schedule SET next_publish_date = ? WHERE channel_db_id = ?",
                next_date, channel_db_id,
            )
        return True

    async def update_last_publish(self, channel_db_id: int) -> bool:
        query = "INSERT OR REPLACE INTO last_publish (channel_db_id, last_publish_time) VALUES (?, ?)"
        return await self.execute(query, (channel_db_id, TimeUtils.utc_now())) > 0

    async def get_channels_to_publish(self, limit: int = 20) -> List[Dict]:
        now = TimeUtils.utc_now()
        if USE_MYSQL:
            query = """
                SELECT uc.id, uc.channel_id, uc.user_id, u.auto_publish, u.auto_recycle,
                       COALESCE(pc.published_count, 0) AS published_count
                FROM user_channels uc
                JOIN users u ON uc.user_id = u.user_id
                LEFT JOIN schedule sch ON uc.id = sch.channel_db_id
                INNER JOIN (
                    SELECT s.user_id, MAX(p.max_channels) AS max_channels, MAX(p.max_posts) AS max_posts
                    FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                    WHERE s.status = 'active' AND s.end_date > %s
                    GROUP BY s.user_id
                ) a ON uc.user_id = a.user_id
                LEFT JOIN (
                    SELECT user_id, COUNT(*) AS channel_count
                    FROM user_channels WHERE banned = 0 GROUP BY user_id
                ) cc ON uc.user_id = cc.user_id
                LEFT JOIN (
                    SELECT channel_db_id,
                           SUM(CASE WHEN published = 0 AND (fail_count IS NULL OR fail_count < 3) THEN 1 ELSE 0 END) AS publishable_unpublished_count,
                           SUM(CASE WHEN published = 1 THEN 1 ELSE 0 END) AS published_count
                    FROM posts GROUP BY channel_db_id
                ) pc ON uc.id = pc.channel_db_id
                WHERE uc.banned = 0 AND u.banned = 0 AND u.auto_publish = 1
                  AND (sch.next_publish_date IS NULL OR sch.next_publish_date <= %s)
                  AND (COALESCE(pc.publishable_unpublished_count, 0) > 0
                       OR (u.auto_recycle = 1 AND COALESCE(pc.published_count, 0) > 0))
                  AND COALESCE(cc.channel_count, 0) <= a.max_channels
                  AND COALESCE(pc.publishable_unpublished_count, 0) <= a.max_posts
                ORDER BY COALESCE(sch.next_publish_date, uc.created_at) ASC
                LIMIT %s
            """
            return await self.fetchall(
                query,
                (now.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d %H:%M:%S"), limit),
            )
        else:
            query = """
                WITH active_subs AS (
                    SELECT s.user_id, MAX(p.max_channels) AS max_channels, MAX(p.max_posts) AS max_posts
                    FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                    WHERE s.status = 'active' AND s.end_date > ?
                    GROUP BY s.user_id
                ),
                channel_counts AS (
                    SELECT user_id, COUNT(*) AS channel_count
                    FROM user_channels WHERE banned = 0 GROUP BY user_id
                ),
                post_counts AS (
                    SELECT channel_db_id,
                           SUM(CASE WHEN published = 0 AND (fail_count IS NULL OR fail_count < 3) THEN 1 ELSE 0 END) AS publishable_unpublished_count,
                           SUM(CASE WHEN published = 1 THEN 1 ELSE 0 END) AS published_count
                    FROM posts GROUP BY channel_db_id
                )
                SELECT uc.id, uc.channel_id, uc.user_id, u.auto_publish, u.auto_recycle,
                       COALESCE(pc.published_count, 0) AS published_count
                FROM user_channels uc
                JOIN users u ON uc.user_id = u.user_id
                LEFT JOIN schedule sch ON uc.id = sch.channel_db_id
                INNER JOIN active_subs a ON uc.user_id = a.user_id
                LEFT JOIN channel_counts cc ON uc.user_id = cc.user_id
                LEFT JOIN post_counts pc ON uc.id = pc.channel_db_id
                WHERE uc.banned = 0 AND u.banned = 0 AND u.auto_publish = 1
                  AND (sch.next_publish_date IS NULL OR sch.next_publish_date <= ?)
                  AND (COALESCE(pc.publishable_unpublished_count, 0) > 0
                       OR (u.auto_recycle = 1 AND COALESCE(pc.published_count, 0) > 0))
                  AND COALESCE(cc.channel_count, 0) <= a.max_channels
                  AND COALESCE(pc.publishable_unpublished_count, 0) <= a.max_posts
                ORDER BY COALESCE(sch.next_publish_date, uc.created_at) ASC
                LIMIT ?
            """
            return await self.fetchall(query, (now, now, limit))

    # =====================================================================
    # دوال العقوبات (User Penalties)
    # =====================================================================

    async def add_penalty(self, user_id: int, chat_id: int, penalty_type: str,
                          duration: int = 0, reason: str = "", issued_by: int = None) -> Optional[int]:
        try:
            if penalty_type not in self.VALID_PENALTY_TYPES:
                logger.error(f"❌ Invalid penalty_type: {penalty_type}")
                return None
            if duration < 0:
                duration = 0
            if duration > self.MAX_PENALTY_DURATION:
                duration = self.MAX_PENALTY_DURATION

            user_exists = await self.fetchval("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
            if not user_exists:
                logger.warning(f"⚠️ المستخدم {user_id} غير موجود")
                return None
            group_exists = await self.fetchval("SELECT 1 FROM bot_groups WHERE chat_id = ?", (chat_id,))
            if not group_exists:
                logger.warning(f"⚠️ المجموعة {chat_id} غير موجودة")
                return None

            async with self.transaction() as conn:
                if penalty_type != "warn":
                    await self._execute_with_conn(
                        conn,
                        "UPDATE user_penalties SET status = 'removed' WHERE user_id = ? AND chat_id = ? AND penalty_type = ? AND status = 'active'",
                        user_id, chat_id, penalty_type,
                    )
                start_time = TimeUtils.utc_now()
                end_time = None
                if duration > 0:
                    end_time = start_time + timedelta(seconds=duration)
                if USE_POSTGRES:
                    row = await self._fetchone_with_conn(
                        conn,
                        "INSERT INTO user_penalties (user_id, chat_id, penalty_type, duration, start_time, end_time, reason, issued_by, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id",
                        user_id, chat_id, penalty_type, duration, start_time, end_time, reason, issued_by, start_time,
                    )
                    penalty_id = row["id"] if row else None
                elif USE_MYSQL:
                    cursor = await conn.cursor()
                    await cursor.execute(
                        "INSERT INTO user_penalties (user_id, chat_id, penalty_type, duration, start_time, end_time, reason, issued_by, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (user_id, chat_id, penalty_type, duration, start_time, end_time, reason, issued_by, start_time),
                    )
                    penalty_id = cursor.lastrowid
                    await cursor.close()
                else:
                    cursor = await conn.execute(
                        "INSERT INTO user_penalties (user_id, chat_id, penalty_type, duration, start_time, end_time, reason, issued_by, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (user_id, chat_id, penalty_type, duration, start_time, end_time, reason, issued_by, start_time),
                    )
                    penalty_id = cursor.lastrowid
                if issued_by:
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO admin_logs (chat_id, admin_id, action, target_id, reason, created_at) VALUES (?,?,?,?,?,?)",
                        chat_id, issued_by, f"penalty_{penalty_type}", user_id, reason, TimeUtils.utc_now(),
                    )
                return penalty_id
        except Exception as e:
            logger.error(f"❌ Error in add_penalty: {e}", exc_info=True)
            return None

    async def remove_penalty(self, penalty_id: int) -> bool:
        return await self.execute(
            "UPDATE user_penalties SET status = 'removed' WHERE id = ?", (penalty_id,)
        ) > 0

    async def remove_penalties_for_user(self, user_id: int, chat_id: int, penalty_type: str = None) -> int:
        try:
            async with self.transaction() as conn:
                query = "UPDATE user_penalties SET status = 'removed' WHERE user_id = ? AND chat_id = ? AND status = 'active'"
                params = [user_id, chat_id]
                if penalty_type:
                    query += " AND penalty_type = ?"
                    params.append(penalty_type)
                return await self._execute_with_conn(conn, query, *params)
        except Exception as e:
            logger.error(f"❌ Error in remove_penalties_for_user: {e}", exc_info=True)
            return 0

    async def get_active_penalties(self, user_id: int, chat_id: int = None) -> List[Dict]:
        query = "SELECT * FROM user_penalties WHERE user_id = ? AND status = 'active'"
        params = [user_id]
        if chat_id:
            query += " AND chat_id = ?"
            params.append(chat_id)
        query += " ORDER BY end_time ASC"
        return await self.fetchall(query, tuple(params))

    async def expire_penalties(self) -> int:
        try:
            async with self.transaction() as conn:
                if USE_POSTGRES:
                    expired_count = await self._fetchval_with_conn(
                        conn,
                        "SELECT COUNT(*) FROM user_penalties WHERE status = 'active' AND end_time IS NOT NULL AND end_time <= NOW()",
                        default=0,
                    )
                    if expired_count > 0:
                        await conn.execute(
                            """INSERT INTO penalty_archive (user_id, chat_id, penalty_type, duration, start_time, end_time, reason, issued_by, status, created_at, archived_at)
                               SELECT user_id, chat_id, penalty_type, duration, start_time, end_time, reason, issued_by, 'expired', created_at, NOW()
                               FROM user_penalties WHERE status = 'active' AND end_time IS NOT NULL AND end_time <= NOW()"""
                        )
                        await conn.execute(
                            "UPDATE user_penalties SET status = 'expired' WHERE status = 'active' AND end_time IS NOT NULL AND end_time <= NOW()"
                        )
                    await conn.execute(
                        "DELETE FROM penalty_archive WHERE archived_at < NOW() - INTERVAL '90 days'"
                    )
                elif USE_MYSQL:
                    cursor = await conn.cursor()
                    await cursor.execute(
                        """INSERT INTO penalty_archive (user_id, chat_id, penalty_type, duration, start_time, end_time, reason, issued_by, status, created_at, archived_at)
                           SELECT user_id, chat_id, penalty_type, duration, start_time, end_time, reason, issued_by, 'expired', created_at, UTC_TIMESTAMP()
                           FROM user_penalties WHERE status = 'active' AND end_time IS NOT NULL AND end_time <= UTC_TIMESTAMP()"""
                    )
                    expired_count = cursor.rowcount
                    if expired_count > 0:
                        await cursor.execute(
                            "UPDATE user_penalties SET status = 'expired' WHERE status = 'active' AND end_time IS NOT NULL AND end_time <= UTC_TIMESTAMP()"
                        )
                    await cursor.execute("DELETE FROM penalty_archive WHERE archived_at < UTC_TIMESTAMP() - INTERVAL 90 DAY")
                    await cursor.close()
                else:
                    cursor = await conn.execute(
                        """INSERT INTO penalty_archive (user_id, chat_id, penalty_type, duration, start_time, end_time, reason, issued_by, status, created_at, archived_at)
                           SELECT user_id, chat_id, penalty_type, duration, start_time, end_time, reason, issued_by, 'expired', created_at, datetime('now')
                           FROM user_penalties WHERE status = 'active' AND end_time IS NOT NULL AND end_time <= datetime('now')"""
                    )
                    expired_count = cursor.rowcount
                    if expired_count > 0:
                        await conn.execute(
                            "UPDATE user_penalties SET status = 'expired' WHERE status = 'active' AND end_time IS NOT NULL AND end_time <= datetime('now')"
                        )
                    await conn.execute("DELETE FROM penalty_archive WHERE julianday('now') - julianday(archived_at) > 90")
                return expired_count
        except Exception as e:
            logger.error(f"❌ Error in expire_penalties: {e}", exc_info=True)
            return 0

    async def get_user_penalty_count(self, user_id: int, chat_id: int, penalty_type: str = None) -> int:
        query = "SELECT COUNT(*) FROM user_penalties WHERE user_id = ? AND chat_id = ? AND status = 'active'"
        params = [user_id, chat_id]
        if penalty_type:
            query += " AND penalty_type = ?"
            params.append(penalty_type)
        return await self.fetchval(query, tuple(params), default=0)

    async def get_all_active_penalties(self) -> List[Dict]:
        return await self.fetchall("SELECT * FROM user_penalties WHERE status = 'active'")


# =====================================================================
# كائن عالمي + دوال مساعدة
# =====================================================================

DB = Database()


async def get_db() -> Database:
    return DB


async def initialize_db() -> bool:
    return await DB.initialize_db()