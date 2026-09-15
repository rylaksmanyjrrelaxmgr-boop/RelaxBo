#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database.py - قاعدة البيانات المتكاملة (v7.7.13 — FIX-RESTORE-COMPUTE-TEXT-HASH)
================================================================================
🆕 v7.7.13 (FIX-RESTORE-COMPUTE-TEXT-HASH):
  ✅ استعادة _compute_text_hash المحذوفة سهواً في v7.7.9 PERF-3
  ✅ حل نهائي لـ: AttributeError: 'Database' object has no
     attribute '_compute_text_hash'
  ✅ متوافقة مع database_channels_posts.py (Mixin Contract)

🔍 v7.7.12 (AUDIT-UTC-CLEAN — لا تغيير وظيفي):
  ✅ مراجعة شاملة: كل استدعاءات التخزين تستخدم TimeUtils.utc_now()
  ✅ لا يوجد أي استخدام لـ mecca_now() في سياق التخزين
  ✅ mecca_iso() تُستعمل فقط عند الحاجة للعرض (وهي غير مستدعاة هنا)
  ✅ متوافق مع utils.py v7.8.5 (Pool Monitor + UTC Consistency)
  ⚠️ لا تعديلات وظيفية — هذا إصدار توثيقي فقط

🆕 v7.7.11 (FIX-BANNED-WORDS-CACHE-TTL):
  ✅ __init__: إضافة المتغيرات الناقصة التي يستخدمها Mixin.get_banned_words
  ✅ حل نهائي لـ: AttributeError: 'Database' object has no
     attribute '_banned_words_cache_ttl'

🚨 v7.7.10 (FIX-INT32):
  ✅ _ensure_bigint_ids: تحويل تلقائي للأعمدة INT32 → BIGINT
  ✅ log_channel_id: INTEGER → BIGINT (Telegram Channel IDs)
  ✅ BOOTSTRAP_DATA_VERSION = 7
  ✅ حل invalid input for query argument (value out of int32 range)

🚀 v7.7.9 (PERF-1..6):
  PERF-1 tables_hash: تخطي create_tables عند عدم تغيّر schema
  PERF-2 _fetch_all_columns_map: استعلام واحد لأعمدة كل الجداول
  PERF-3 حذف _ensure_text_hash_column المكرّرة
  PERF-4 SQLite PRAGMA مستقل لكل أمر
  PERF-5 _upsert_setting موحّد
  PERF-6 _init_default_data: batch INSERT بدل loop

🔥 v7.7.8 (FIX-PG-BOOTSTRAP):
  ✅ _bootstrap: لا transaction لـPG/MySQL — DDL في autocommit
  ✅ حل InFailedSQLTransactionError نهائياً

إصلاحات v7.7.7 (LOG-CHANNEL):
  LOG-1  _migrate_schema: عمود log_channel_id في bot_groups

إصلاحات v7.7.6 (HOTFIX-1):
  HOTFIX-1 __init__: self._lock = asyncio.Lock()

إصلاحات v7.7.5 (ISSUE-1..3, FIX-A..D, NOTE-1..2, FIX-MISSING):
  ISSUE-1 _destroy_connection(MySQL): close ثم release
  ISSUE-2 transaction(): except BaseException
  ISSUE-3 _recover_pool: تتبّع في _bg_tasks
  FIX-A   _find_values_end: parser متوازن
  FIX-B   _insert_before_returning: يكتشف RETURNING بعد \n/\t/\r
  FIX-C   DATABASE_URL: urlparse
  FIX-D   close(): _initialized=False في finally
  FIX-MISSING استعادة _get_secondary_indexes

إصلاحات v7.7.4 (B-1..B-5, M-1..M-6, N-2, N-4):
  B-1..B-5, M-1..M-6, N-2, N-4
================================================================================
"""

import os
import sys
import json
import asyncio
import logging
import time
import sqlite3
import secrets
import re
import hashlib
import inspect
import weakref
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from typing import (
    Dict, List, Optional, Tuple, Any, Union, AsyncGenerator,
    Callable, Awaitable, Set,
)
from contextlib import asynccontextmanager
from collections import defaultdict

# =====================================================================
# 0) كشف نوع قاعدة البيانات
# =====================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_TYPE = "sqlite"

if DATABASE_URL:
    _URL_LOWER = DATABASE_URL.lower()
    if "postgres" in _URL_LOWER:
        DB_TYPE = "postgres"
        try:
            import asyncpg
            from asyncpg import Pool, Connection
        except ImportError:
            logging.error("❌ asyncpg غير مثبت: pip install asyncpg")
            raise
    elif "mysql" in _URL_LOWER or "mariadb" in _URL_LOWER:
        DB_TYPE = "mysql"
        try:
            import asyncmy
            from asyncmy import Pool, Connection
        except ImportError:
            logging.error("❌ asyncmy غير مثبت: pip install asyncmy")
            raise

if DB_TYPE == "sqlite":
    import aiosqlite

USE_POSTGRES = (DB_TYPE == "postgres")
USE_MYSQL = (DB_TYPE == "mysql")

logger = logging.getLogger(__name__)
logger.info(f"📌 قاعدة البيانات: {DB_TYPE.upper()}")

# =====================================================================
# 0.1) التكوينات
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
# 0.2) database_tables
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
# 0.3) Mixins
# =====================================================================

def _load_mixin(module_name: str, class_name: str):
    try:
        module = __import__(module_name, fromlist=[class_name])
        cls = getattr(module, class_name)
        logger.info(f"✅ تم تحميل {module_name}.py")
        return cls, True
    except ImportError as e:
        logger.warning(f"⚠️ {module_name}.py غير موجود: {e}")
        return object, False

ChannelsPostsMixin, CHANNELS_POSTS_MIXIN_AVAILABLE = _load_mixin(
    "database_channels_posts", "ChannelsPostsMixin"
)
SubscriptionsMixin, SUBSCRIPTIONS_MIXIN_AVAILABLE = _load_mixin(
    "database_subscriptions", "SubscriptionsMixin"
)
GroupsMixin, GROUPS_MIXIN_AVAILABLE = _load_mixin(
    "database_groups", "GroupsMixin"
)
TicketsMixin, TICKETS_MIXIN_AVAILABLE = _load_mixin(
    "database_tickets", "TicketsMixin"
)
ContestsMixin, CONTESTS_MIXIN_AVAILABLE = _load_mixin(
    "database_contests", "ContestsMixin"
)
StatsMixin, STATS_MIXIN_AVAILABLE = _load_mixin(
    "database_stats", "StatsMixin"
)
SettingsMixin, SETTINGS_MIXIN_AVAILABLE = _load_mixin(
    "database_settings", "SettingsMixin"
)
PointsMixin, POINTS_MIXIN_AVAILABLE = _load_mixin(
    "database_points", "PointsMixin"
)
BackupMixin, BACKUP_MIXIN_AVAILABLE = _load_mixin(
    "database_backup", "BackupMixin"
)
RemindersMixin, REMINDERS_MIXIN_AVAILABLE = _load_mixin(
    "database_reminders", "RemindersMixin"
)

# =====================================================================
# 0.4) InternalQueryCache
# =====================================================================

class InternalQueryCache:
    def __init__(self, ttl: int = 60, max_size: int = 10000):
        self._cache: Dict[str, Tuple[Any, float, int]] = {}
        self._ttl = ttl
        self._max_size = max_size
        self._eviction_lock = asyncio.Lock()

    async def get(self, key: str):
        entry = self._cache.get(key)
        if entry is not None:
            data, timestamp, ttl = entry
            if time.monotonic() - timestamp < ttl:
                return data
            self._cache.pop(key, None)
        return None

    async def set(self, key: str, data, ttl: int = None):
        effective_ttl = ttl if ttl is not None else self._ttl
        if len(self._cache) >= self._max_size and key not in self._cache:
            async with self._eviction_lock:
                if len(self._cache) >= self._max_size:
                    to_remove = list(self._cache.keys())[
                        : max(1, self._max_size // 4)
                    ]
                    for k in to_remove:
                        self._cache.pop(k, None)
        self._cache[key] = (data, time.monotonic(), effective_ttl)

    async def invalidate(self, key: str = None):
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    async def clear(self):
        self._cache.clear()

    async def get_size(self) -> int:
        return len(self._cache)

internal_cache = InternalQueryCache(ttl=30, max_size=10000)

# =====================================================================
# 0.5) SimpleCache
# =====================================================================

class SimpleCache:
    def __init__(self, default_ttl: int = 60, max_size: int = 10000):
        self._cache: Dict[Union[str, int], Tuple[Any, float, int]] = {}
        self._ttl = default_ttl
        self._max_size = max_size
        self._lock = asyncio.Lock()

    async def get(self, key):
        async with self._lock:
            if key in self._cache:
                data, ts, ttl = self._cache[key]
                if time.monotonic() - ts < ttl:
                    return data
                del self._cache[key]
            return None

    async def set(self, key, data, ttl: int = None):
        effective = ttl if ttl is not None else self._ttl
        async with self._lock:
            if len(self._cache) >= self._max_size and key not in self._cache:
                to_remove = list(self._cache.keys())[
                    : max(1, self._max_size // 4)
                ]
                for k in to_remove:
                    self._cache.pop(k, None)
            self._cache[key] = (data, time.monotonic(), effective)

    async def invalidate(self, key=None):
        async with self._lock:
            if key is not None:
                self._cache.pop(key, None)
            else:
                self._cache.clear()

    async def clear(self):
        async with self._lock:
            self._cache.clear()

    async def has(self, key) -> bool:
        async with self._lock:
            if key in self._cache:
                _, ts, ttl = self._cache[key]
                if time.monotonic() - ts < ttl:
                    return True
                del self._cache[key]
            return False

    async def get_with_ttl(self, key):
        async with self._lock:
            if key in self._cache:
                data, ts, ttl = self._cache[key]
                remaining = int(ttl - (time.monotonic() - ts))
                if remaining > 0:
                    return data, remaining
                del self._cache[key]
            return None, None

    async def set_many(self, items: Dict[Any, Any], ttl: int = None):
        effective = ttl if ttl is not None else self._ttl
        async with self._lock:
            now = time.monotonic()
            for key, data in items.items():
                if len(self._cache) >= self._max_size and key not in self._cache:
                    to_remove = list(self._cache.keys())[
                        : max(1, self._max_size // 4)
                    ]
                    for k in to_remove:
                        self._cache.pop(k, None)
                self._cache[key] = (data, now, effective)

    async def delete_many(self, keys: List[Any]) -> int:
        async with self._lock:
            count = 0
            for key in keys:
                if key in self._cache:
                    del self._cache[key]
                    count += 1
            return count

    async def get_keys(self) -> List[Any]:
        async with self._lock:
            return list(self._cache.keys())

    async def get_all(self) -> Dict[Any, Any]:
        async with self._lock:
            now = time.monotonic()
            return {
                k: v[0] for k, v in self._cache.items()
                if now - v[1] < v[2]
            }

    async def get_stats(self) -> Dict[str, Any]:
        async with self._lock:
            return {
                'size': len(self._cache),
                'max_size': self._max_size,
                'ttl': self._ttl,
            }

class SettingsCache(SimpleCache):
    pass

# =====================================================================
# 0.6) cache.py
# =====================================================================

try:
    from cache import (
        user_cache, banned_words_cache, settings_cache,
        channels_cache, groups_cache, auth_cache, posts_cache,
        invalidate_user_cache, clear_all_caches,
        get_cache_stats, cache_cleanup_task,
    )
    CACHE_AVAILABLE = True
    logger.info("✅ تم تحميل cache.py")
except ImportError:
    user_cache = SimpleCache(default_ttl=60)
    banned_words_cache = SimpleCache(default_ttl=300)
    settings_cache = SettingsCache(default_ttl=600)
    channels_cache = SimpleCache(default_ttl=60)
    groups_cache = SimpleCache(default_ttl=60)
    auth_cache = SimpleCache(default_ttl=120)
    posts_cache = SimpleCache(default_ttl=30)

    async def invalidate_user_cache(user_id: int):
        try:
            await user_cache.invalidate(user_id)
            for k in (
                f"user_{user_id}", f"user_{user_id}_True",
                f"user_{user_id}_False", f"lang_{user_id}",
                f"channels_{user_id}", f"groups_{user_id}",
                f"reminder_settings_{user_id}", f"auto_recycle_{user_id}",
                f"auto_publish_{user_id}", f"user_settings_batch_{user_id}",
                f"has_active_sub_{user_id}",
                f"has_active_subscription_{user_id}",
                f"subscription_active_{user_id}",
                f"subscription_{user_id}",
                f"start_data_{user_id}",
            ):
                await internal_cache.invalidate(k)
        except Exception:
            pass

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
        except Exception:
            pass

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
                    channels_cache, groups_cache, auth_cache, posts_cache,
                ):
                    async with cache_obj._lock:
                        now = time.monotonic()
                        expired = [
                            k for k, (_, ts, ttl) in cache_obj._cache.items()
                            if now - ts >= ttl
                        ]
                        for k in expired:
                            del cache_obj._cache[k]
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ cache_cleanup_task: {e}")

    CACHE_AVAILABLE = True
    logger.warning("⚠️ cache.py غير موجود — كاش داخلي")

# =====================================================================
# 0.7) ثوابت
# =====================================================================

MAX_POST_TEXT_LENGTH = int(os.getenv("MAX_POST_TEXT_LENGTH", "0"))
MAX_USER_LOCKS_CONFIG = int(os.getenv("MAX_USER_LOCKS", "10000"))
MAX_GROUP_LOCKS_CONFIG = int(os.getenv("MAX_GROUP_LOCKS", "5000"))
MAX_PENALTY_LOCKS_CONFIG = int(os.getenv("MAX_PENALTY_LOCKS", "5000"))
MAX_CHANNEL_LOCKS_CONFIG = int(os.getenv("MAX_CHANNEL_LOCKS", "5000"))
POSTS_BATCH_SIZE = int(os.getenv("POSTS_BATCH_SIZE", "100"))
SQLITE_POOL_SIZE = int(os.getenv("SQLITE_POOL_SIZE", "10"))
EXPLAIN_SLOW_QUERIES = os.getenv("EXPLAIN_SLOW_QUERIES", "false").lower() == "true"
MAX_ACTIVE_PENALTIES_FETCH = 1000
UTC = timezone.utc

# =====================================================================
# 1) ثوابت مساعدة
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

_UNIQUE_CACHE: Dict[str, List[str]] = {}

_ALLOWED_COLUMN_TYPES = frozenset({
    "INTEGER", "INT", "BIGINT", "SMALLINT", "TINYINT",
    "TEXT", "VARCHAR", "CHAR", "VARCHAR2",
    "REAL", "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC",
    "TIMESTAMP", "DATETIME", "DATE", "TIME",
    "BOOLEAN", "BOOL", "BLOB", "BYTEA",
})

_ALLOWED_COL_KEYWORDS = frozenset({
    "DEFAULT", "NULL", "NOT", "PRIMARY", "KEY", "UNIQUE",
    "CURRENT_TIMESTAMP", "UTC_TIMESTAMP", "NOW",
    "AUTOINCREMENT", "AUTO_INCREMENT",
    "CURRENT_DATE", "CURRENT_TIME", "SYSDATE", "LOCALTIME",
    "LOCALTIMESTAMP", "TRUE", "FALSE",
    "COLLATE", "ON", "UPDATE", "DELETE", "CASCADE",
    "REFERENCES", "CHECK", "CONSTRAINT",
})

def _validate_column_def(col_name: str, col_def: str) -> bool:
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", col_name):
        logger.error(f"❌ اسم عمود غير صالح: {col_name}")
        return False
    if not col_def or not isinstance(col_def, str):
        return False
    for dangerous in (";", "--", "/*", "*/", "\x00"):
        if dangerous in col_def:
            logger.error(f"❌ أحرف خطرة: {col_def}")
            return False
    col_def_stripped = col_def.strip()
    if not col_def_stripped:
        return False
    col_def_upper = col_def_stripped.upper()
    type_match = re.match(r"^([A-Z_][A-Z0-9_]*)", col_def_upper)
    if not type_match:
        return False
    base_type = type_match.group(1)
    if base_type not in _ALLOWED_COLUMN_TYPES:
        logger.error(f"❌ نوع غير مسموح: {base_type}")
        return False
    without_strings = re.sub(r"'[^']*'", "", col_def_upper)
    cleaned = re.sub(r"[(),.\d+\-*/=]", " ", without_strings)
    words = re.findall(r"[A-Z_]+", cleaned)
    for word in words:
        if word in _ALLOWED_COLUMN_TYPES or word in _ALLOWED_COL_KEYWORDS:
            continue
        logger.error(f"❌ كلمة غير مسموحة: {word}")
        return False
    return True

def _clone_start_data(data: Dict) -> Dict:
    if not isinstance(data, dict):
        return data
    cloned = dict(data)
    for key in ("channel_info",):
        value = cloned.get(key)
        if isinstance(value, dict):
            cloned[key] = dict(value)
        elif isinstance(value, list):
            cloned[key] = list(value)
    return cloned

class _FactoryFailed(Exception):
    def __init__(self, msg: str, pool: Any):
        super().__init__(msg)
        self.pool = pool

async def _create_pool_with_retry(
    pool_factory: Callable[[], Awaitable[Any]],
    name: str,
    max_attempts: int = 5,
    cleanup: Optional[Callable[[Any], Awaitable[None]]] = None,
) -> Any:
    last_exc: Optional[Exception] = None
    for attempt in range(max_attempts):
        try:
            pool = await pool_factory()
            if attempt > 0:
                logger.info(f"✅ نجح الاتصال بـ {name}")
            return pool
        except _FactoryFailed as e:
            last_exc = e
            if e.pool is not None and cleanup is not None:
                try:
                    await cleanup(e.pool)
                    logger.info(f"🧹 cleanup pool جزئي لـ {name}")
                except Exception as ce:
                    logger.warning(f"⚠️ cleanup pool جزئي: {ce}")
            if attempt == max_attempts - 1:
                raise
            delay = min(2 ** attempt, 30)
            logger.warning(
                f"⚠️ {name} ({attempt + 1}/{max_attempts}): "
                f"{e} — إعادة {delay}s"
            )
            await asyncio.sleep(delay)
        except Exception as e:
            last_exc = e
            if attempt == max_attempts - 1:
                raise
            delay = min(2 ** attempt, 30)
            logger.warning(
                f"⚠️ {name} ({attempt + 1}/{max_attempts}): "
                f"{e} — إعادة {delay}s"
            )
            await asyncio.sleep(delay)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"فشل الاتصال بـ {name}")

def _sql_get_setting_value() -> str:
    if USE_MYSQL:
        return "SELECT `value` FROM settings WHERE `key` = ?"
    return "SELECT value FROM settings WHERE key = ?"

def _mysql_random() -> str:
    return "RAND()" if USE_MYSQL else "RANDOM()"

# =====================================================================
# Parser للأقواس — FIX-A
# =====================================================================

def _find_values_end(query: str) -> int:
    m = re.search(r"\bVALUES\b\s*", query, re.IGNORECASE)
    if not m:
        return -1
    i = m.end()
    if i >= len(query) or query[i] != "(":
        return -1

    n = len(query)
    in_single = in_double = False
    in_line_c = in_block_c = False
    escape_next = False
    depth = 0
    j = i
    last_close = -1

    while j < n:
        ch = query[j]
        if escape_next:
            escape_next = False
            j += 1
            continue
        if ch == "\\" and (in_single or in_double):
            escape_next = True
            j += 1
            continue
        if in_line_c:
            if ch == "\n":
                in_line_c = False
            j += 1
            continue
        if in_block_c:
            if ch == "*" and j + 1 < n and query[j + 1] == "/":
                in_block_c = False
                j += 2
                continue
            j += 1
            continue
        if not in_single and not in_double:
            if ch == "-" and j + 1 < n and query[j + 1] == "-":
                in_line_c = True
                j += 2
                continue
            if ch == "/" and j + 1 < n and query[j + 1] == "*":
                in_block_c = True
                j += 2
                continue
            if ch == "#":
                in_line_c = True
                j += 1
                continue
        if ch == "'" and not in_double:
            in_single = not in_single
            j += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            j += 1
            continue
        if in_single or in_double:
            j += 1
            continue
        if ch == "(":
            depth += 1
            j += 1
            continue
        if ch == ")":
            depth -= 1
            if depth == 0:
                last_close = j + 1
            j += 1
            continue
        if depth == 0 and last_close > 0:
            if ch in " \t\n\r":
                k = j
                while k < n and query[k] in " \t\n\r":
                    k += 1
                if k < n and query[k] in ",(":
                    j += 1
                    continue
                return last_close
            elif ch == ",":
                j += 1
                continue
            elif ch == ";":
                return last_close
            else:
                return last_close
        j += 1

    return last_close if last_close > 0 else -1

def _insert_before_returning(query: str, clause: str) -> str:
    upper = query.upper()
    n = len(upper)
    in_single = in_double = False
    in_line_c = in_block_c = False
    escape_next = False
    idx = -1
    i = 0
    while i < n:
        ch = upper[i]
        if escape_next:
            escape_next = False
            i += 1
            continue
        if ch == "\\" and (in_single or in_double):
            escape_next = True
            i += 1
            continue
        if in_line_c:
            if ch == "\n":
                in_line_c = False
            i += 1
            continue
        if in_block_c:
            if ch == "*" and i + 1 < n and upper[i + 1] == "/":
                in_block_c = False
                i += 2
                continue
            i += 1
            continue
        if not in_single and not in_double:
            if ch == "-" and i + 1 < n and upper[i + 1] == "-":
                in_line_c = True
                i += 2
                continue
            if ch == "/" and i + 1 < n and upper[i + 1] == "*":
                in_block_c = True
                i += 2
                continue
            if ch == "#":
                in_line_c = True
                i += 1
                continue
        if ch == "'" and not in_double:
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            i += 1
            continue
        if in_single or in_double:
            i += 1
            continue
        if (ch in " \t\n\r"
                and i + 10 <= n
                and upper[i + 1:i + 10] == "RETURNING"
                and (i + 10 == n or upper[i + 10] in " \t\n\r;(")):
            idx = i
            break
        i += 1
    if idx > 0:
        return query[:idx] + " " + clause + query[idx:]
    return query + " " + clause

def _replace_excluded_with_values(set_clause: str) -> str:
    result: List[str] = []
    i = 0
    n = len(set_clause)
    in_single = in_double = False
    in_line_c = in_block_c = False
    escape_next = False
    while i < n:
        ch = set_clause[i]
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
        if in_line_c:
            result.append(ch)
            if ch == "\n":
                in_line_c = False
            i += 1
            continue
        if in_block_c:
            result.append(ch)
            if ch == "*" and i + 1 < n and set_clause[i + 1] == "/":
                result.append("/")
                i += 2
                in_block_c = False
                continue
            i += 1
            continue
        if not in_single and not in_double:
            if ch == "-" and i + 1 < n and set_clause[i + 1] == "-":
                in_line_c = True
                result.append(ch)
                i += 1
                continue
            if ch == "/" and i + 1 < n and set_clause[i + 1] == "*":
                in_block_c = True
                result.append(ch)
                i += 1
                continue
            if ch == "#":
                in_line_c = True
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
        if in_single or in_double:
            result.append(ch)
            i += 1
            continue
        if (ch in ("e", "E")
                and i + 9 <= n
                and set_clause[i:i + 9].lower() == "excluded."):
            prev_ok = (i == 0
                       or not (set_clause[i - 1].isalnum()
                               or set_clause[i - 1] == "_"))
            if prev_ok:
                j = i + 9
                k = j
                while k < n and (set_clause[k].isalnum() or set_clause[k] == "_"):
                    k += 1
                if k > j:
                    ident = set_clause[j:k]
                    result.append(f"VALUES({ident})")
                    i = k
                    continue
        result.append(ch)
        i += 1
    return "".join(result)

async def _get_unique_columns(table: str, conn) -> List[str]:
    if table in _UNIQUE_CACHE:
        return _UNIQUE_CACHE[table]
    columns = []
    existing_columns = set()
    table_existed = True
    try:
        if USE_POSTGRES:
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = $1 AND table_schema = current_schema()",
                table,
            )
            existing_columns = {row["column_name"] for row in rows}
            if not existing_columns:
                table_existed = False
        elif USE_MYSQL:
            if not await _table_exists(conn, table):
                table_existed = False
            else:
                cursor = await conn.cursor()
                try:
                    await cursor.execute(f"SHOW COLUMNS FROM `{table}`")
                    rows = await cursor.fetchall()
                    existing_columns = {row[0] for row in rows}
                finally:
                    await cursor.close()
        else:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name=?",
                (table,),
            )
            try:
                row = await cursor.fetchone()
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
            if row is None:
                table_existed = False
            else:
                cursor = await conn.execute(f"PRAGMA table_info({table})")
                try:
                    rows = await cursor.fetchall()
                    existing_columns = {row[1] for row in rows}
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
    except Exception as e:
        logger.warning(f"⚠️ فشل أعمدة {table}: {e}")
        return KNOWN_UNIQUE_FALLBACK.get(table, ["id"])

    if not table_existed:
        return KNOWN_UNIQUE_FALLBACK.get(table, ["id"])

    try:
        if USE_POSTGRES:
            pk_rows = await conn.fetch(
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid "
                "AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = to_regclass($1) AND i.indisprimary",
                table,
            )
            if pk_rows:
                columns = [
                    row["attname"] for row in pk_rows
                    if row["attname"] in existing_columns
                ]
            else:
                unique_rows = await conn.fetch(
                    "SELECT a.attname FROM pg_index i "
                    "JOIN pg_attribute a ON a.attrelid = i.indrelid "
                    "AND a.attnum = ANY(i.indkey) "
                    "WHERE i.indrelid = to_regclass($1) "
                    "AND i.indisunique AND NOT i.indisprimary LIMIT 1",
                    table,
                )
                if unique_rows:
                    columns = [
                        row["attname"] for row in unique_rows
                        if row["attname"] in existing_columns
                    ]
        elif USE_MYSQL:
            cursor = await conn.cursor()
            try:
                await cursor.execute(
                    f"SHOW KEYS FROM `{table}` WHERE Key_name = 'PRIMARY'"
                )
                pk_rows = await cursor.fetchall()
                if pk_rows:
                    columns = [
                        row[4] for row in pk_rows
                        if row[4] in existing_columns
                    ]
                else:
                    await cursor.execute(
                        f"SHOW KEYS FROM `{table}` "
                        f"WHERE Non_unique = 0 AND "
                        f"Key_name != 'PRIMARY' LIMIT 1"
                    )
                    unique_rows = await cursor.fetchall()
                    if unique_rows:
                        key_name = unique_rows[0][2]
                        await cursor.execute(
                            f"SHOW KEYS FROM `{table}` "
                            f"WHERE Key_name = '{key_name}'"
                        )
                        all_rows = await cursor.fetchall()
                        columns = [
                            row[4] for row in all_rows
                            if row[4] in existing_columns
                        ]
            finally:
                await cursor.close()
        else:
            cursor = await conn.execute(f"PRAGMA table_info({table})")
            try:
                rows = await cursor.fetchall()
                pk_columns = [
                    row[1] for row in rows
                    if row[5] == 1 and row[1] in existing_columns
                ]
                if pk_columns:
                    columns = pk_columns
                else:
                    fallback = KNOWN_UNIQUE_FALLBACK.get(table, [])
                    columns = [c for c in fallback if c in existing_columns]
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"⚠️ فشل UNIQUE {table}: {e}")
        fallback = KNOWN_UNIQUE_FALLBACK.get(table, [])
        columns = [c for c in fallback if c in existing_columns]

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
                SELECT i.indexname, ix.indisprimary,
                       array_agg(a.attname ORDER BY a.attnum) AS cols
                FROM pg_indexes i
                JOIN pg_class t ON t.relname = i.tablename
                JOIN pg_index ix ON ix.indexrelid = (
                    SELECT oid FROM pg_class
                    WHERE relname = i.indexname AND relkind = 'i'
                )
                JOIN pg_attribute a ON a.attrelid = t.oid
                                   AND a.attnum = ANY(ix.indkey)
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
        except Exception:
            return None
    elif USE_MYSQL:
        return None
    else:
        try:
            cursor = await conn.execute(f"PRAGMA index_list({table})")
            try:
                indexes = await cursor.fetchall()
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
            primary_cols = None
            unique_cols = None
            for idx in indexes:
                if idx[2] != 1:
                    continue
                is_primary = (idx[3] == "pk")
                cursor2 = await conn.execute(f"PRAGMA index_info({idx[1]})")
                try:
                    cols_rows = await cursor2.fetchall()
                finally:
                    try:
                        await cursor2.close()
                    except Exception:
                        pass
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
        result = []
        in_single = in_double = in_comment = in_block = False
        escape_next = False
        param_count = 0
        i = 0
        while i < len(query):
            ch = query[i]
            if escape_next:
                result.append(ch); escape_next = False; i += 1; continue
            if ch == "\\" and (in_single or in_double):
                escape_next = True; result.append(ch); i += 1; continue
            if (not in_single and not in_double and not in_block
                    and ch == "-" and i + 1 < len(query)
                    and query[i + 1] == "-"):
                in_comment = True
            if in_comment:
                if ch == "\n":
                    in_comment = False
                result.append(ch); i += 1; continue
            if (not in_single and not in_double and not in_comment
                    and ch == "/" and i + 1 < len(query)
                    and query[i + 1] == "*"):
                in_block = True; result.append(ch); i += 1; continue
            if in_block:
                if ch == "*" and i + 1 < len(query) and query[i + 1] == "/":
                    in_block = False
                    result.append(ch); result.append(query[i + 1])
                    i += 2; continue
                result.append(ch); i += 1; continue
            if ch == "'" and not in_double and not in_comment and not in_block:
                in_single = not in_single; result.append(ch); i += 1; continue
            if ch == '"' and not in_single and not in_comment and not in_block:
                in_double = not in_double; result.append(ch); i += 1; continue
            if (ch == "$" and not in_single and not in_double
                    and not in_comment and not in_block):
                j = i + 1
                while j < len(query) and query[j].isdigit():
                    j += 1
                if j > i + 1:
                    try:
                        n = int(query[i + 1:j])
                        if n > param_count:
                            param_count = n
                    except ValueError:
                        pass
                    result.append(query[i:j]); i = j; continue
            if (ch == "?" and not in_single and not in_double
                    and not in_comment and not in_block):
                param_count += 1
                result.append(f"${param_count}"); i += 1; continue
            result.append(ch); i += 1
        return "".join(result)
    elif USE_MYSQL:
        result = []
        in_single = in_double = in_comment = in_block = False
        escape_next = False
        i = 0
        while i < len(query):
            ch = query[i]
            if escape_next:
                result.append(ch); escape_next = False; i += 1; continue
            if ch == "\\" and (in_single or in_double):
                escape_next = True; result.append(ch); i += 1; continue
            if (not in_single and not in_double and not in_block
                    and ch == "-" and i + 1 < len(query)
                    and query[i + 1] == "-"):
                in_comment = True
            if in_comment:
                if ch == "\n":
                    in_comment = False
                result.append(ch); i += 1; continue
            if (not in_single and not in_double and not in_comment
                    and ch == "/" and i + 1 < len(query)
                    and query[i + 1] == "*"):
                in_block = True; result.append(ch); i += 1; continue
            if in_block:
                if ch == "*" and i + 1 < len(query) and query[i + 1] == "/":
                    in_block = False
                    result.append(ch); result.append(query[i + 1])
                    i += 2; continue
                result.append(ch); i += 1; continue
            if ch == "'" and not in_double:
                in_single = not in_single; result.append(ch); i += 1; continue
            if ch == '"' and not in_single:
                in_double = not in_double; result.append(ch); i += 1; continue
            if (ch == "?" and not in_single and not in_double
                    and not in_comment and not in_block):
                result.append("%s"); i += 1; continue
            result.append(ch); i += 1
        return "".join(result)
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
            r"INSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)\s+VALUES",
            new_query, re.IGNORECASE,
        )
        if not match:
            return _insert_before_returning(
                new_query, "ON CONFLICT DO NOTHING"
            )
        table = match.group(1)
        columns = [c.strip() for c in match.group(2).split(",") if c.strip()]
        conflict_cols = None
        if conn:
            try:
                conflict_cols = await _find_best_conflict_target(
                    table, conn, columns
                )
            except Exception:
                pass
        target = f" ({conflict_cols})" if conflict_cols else ""
        end_pos = _find_values_end(new_query)
        if end_pos > 0:
            new_query = (
                new_query[:end_pos]
                + f" ON CONFLICT{target} DO NOTHING"
                + new_query[end_pos:]
            )
        else:
            new_query = _insert_before_returning(
                new_query, f"ON CONFLICT{target} DO NOTHING"
            )
        return new_query
    elif USE_MYSQL:
        return query.replace("INSERT OR IGNORE", "INSERT IGNORE", 1)
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
            r"INSERT\s+INTO\s+(\w+)\s*\(([^)]+)\)\s+VALUES",
            new_query, re.IGNORECASE,
        )
        if not match:
            logger.error("❌ INSERT OR REPLACE بلا أعمدة")
            raise ValueError(
                "INSERT OR REPLACE requires explicit column list"
            )
        table = match.group(1)
        columns = [c.strip() for c in match.group(2).split(",") if c.strip()]

        best_cols = None
        if conn:
            try:
                best_cols = await _find_best_conflict_target(
                    table, conn, columns
                )
            except Exception:
                pass

        if not best_cols:
            fallback = KNOWN_UNIQUE_FALLBACK.get(table, [])
            usable = [c for c in fallback if c in columns]
            if usable:
                best_cols = ", ".join(usable)
            else:
                logger.error(f"❌ REPLACE على {table} بلا unique")
                raise ValueError(
                    f"INSERT OR REPLACE on {table} requires a unique "
                    f"constraint discoverable from columns {columns}"
                )

        pk_set = set(c.strip() for c in best_cols.split(","))
        set_columns = [col for col in columns if col not in pk_set]

        if not set_columns:
            end_pos = _find_values_end(new_query)
            if end_pos > 0:
                return (
                    new_query[:end_pos]
                    + f" ON CONFLICT ({best_cols}) DO NOTHING"
                    + new_query[end_pos:]
                )
            return _insert_before_returning(
                new_query,
                f"ON CONFLICT ({best_cols}) DO NOTHING",
            )

        existing_columns = set()
        try:
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = $1 AND table_schema = current_schema()",
                table,
            )
            existing_columns = {row["column_name"] for row in rows}
        except Exception:
            pass

        if existing_columns:
            set_columns = [c for c in set_columns if c in existing_columns]

        if not set_columns:
            end_pos = _find_values_end(new_query)
            if end_pos > 0:
                return (
                    new_query[:end_pos]
                    + f" ON CONFLICT ({best_cols}) DO NOTHING"
                    + new_query[end_pos:]
                )
            return _insert_before_returning(
                new_query,
                f"ON CONFLICT ({best_cols}) DO NOTHING",
            )

        set_clause = ", ".join(
            [f"{col} = EXCLUDED.{col}" for col in set_columns]
        )
        end_pos = _find_values_end(new_query)
        if end_pos > 0:
            return (
                new_query[:end_pos]
                + f" ON CONFLICT ({best_cols}) DO UPDATE SET {set_clause}"
                + new_query[end_pos:]
            )
        return _insert_before_returning(
            new_query,
            f"ON CONFLICT ({best_cols}) DO UPDATE SET {set_clause}",
        )

    elif USE_MYSQL:
        new_query = query.replace("INSERT OR REPLACE", "INSERT", 1)
        match = re.search(
            r"INSERT\s+INTO\s+`?(\w+)`?\s*\(([^)]+)\)\s+VALUES",
            new_query, re.IGNORECASE,
        )
        if not match:
            logger.error(
                "❌ INSERT OR REPLACE على MySQL بلا قائمة أعمدة "
                "— رفض التنفيذ"
            )
            raise ValueError(
                "INSERT OR REPLACE on MySQL requires column list"
            )
        table = match.group(1)
        columns = [
            c.strip().strip("`") for c in match.group(2).split(",")
            if c.strip()
        ]
        key_cols = KNOWN_UNIQUE_FALLBACK.get(table, [])
        if not key_cols and conn:
            try:
                key_cols = await _get_unique_columns(table, conn)
            except Exception:
                key_cols = []
        key_set = set(key_cols)
        update_cols = [c for c in columns if c not in key_set]
        if not update_cols:
            return new_query.replace("INSERT", "INSERT IGNORE", 1)
        set_clause = ", ".join(
            f"`{c}` = VALUES(`{c}`)" for c in update_cols
        )
        end_pos = _find_values_end(new_query)
        if end_pos > 0:
            return (
                new_query[:end_pos]
                + f" ON DUPLICATE KEY UPDATE {set_clause}"
                + new_query[end_pos:]
            )
        return _insert_before_returning(
            new_query,
            f"ON DUPLICATE KEY UPDATE {set_clause}",
        )
    return query

def _convert_upsert(query: str) -> str:
    if DB_TYPE == "sqlite" or USE_POSTGRES:
        return query
    if not USE_MYSQL:
        return query
    pattern = re.compile(
        r"ON\s+CONFLICT\s*\(([^)]+)\)\s+DO\s+UPDATE\s+SET\s+"
        r"(.+?)"
        r"(?=(?:\s+WHERE\b|\s+RETURNING\b|\s+ON\s+CONFLICT\b|;|$))",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(query)
    if not match:
        return query
    update_set = match.group(2).strip()
    new_update_set = _replace_excluded_with_values(update_set)
    new_query = query[: match.start()].rstrip()
    tail = query[match.end():]
    tail_upper = tail.lstrip().upper()
    if tail_upper.startswith("WHERE"):
        raise ValueError("MySQL: WHERE غير مدعوم بعد ON DUPLICATE KEY")
    if tail_upper.startswith("RETURNING"):
        raise ValueError("MySQL: RETURNING غير مدعوم")
    return new_query + f" ON DUPLICATE KEY UPDATE {new_update_set}" + tail

def _adapt_params(params: tuple, query: str = "") -> tuple:
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
            new_params.append(
                p if USE_POSTGRES else p.strftime("%Y-%m-%d %H:%M:%S")
            )
        elif isinstance(p, bool):
            new_params.append(p if USE_POSTGRES else (1 if p else 0))
        elif isinstance(p, (bytearray, memoryview)):
            new_params.append(bytes(p))
        else:
            new_params.append(p)
    return tuple(new_params)

async def _table_exists(conn, table: str) -> bool:
    try:
        if USE_POSTGRES:
            row = await conn.fetchval(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = $1 AND table_schema = current_schema()",
                table,
            )
            return row is not None
        elif USE_MYSQL:
            cursor = await conn.cursor()
            try:
                await cursor.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() "
                    "AND table_name = %s",
                    (table,),
                )
                row = await cursor.fetchone()
                return row is not None
            finally:
                await cursor.close()
        else:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name=?", (table,),
            )
            try:
                row = await cursor.fetchone()
                return row is not None
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
    except Exception:
        return False

# =====================================================================
# 2) TimeUtils
# =====================================================================

class TimeUtils:
    """
    🕐 القاعدة الذهبية: خزّن UTC، اعرض بتوقيت المستخدم.

    - utc_now():    للتخزين، الحسابات، المقارنات — مستخدمة في كل الكود ✅
    - mecca_now():  للعرض فقط (غير مستدعاة في database.py)
    """
    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def mecca_now() -> datetime:
        return TimeUtils.utc_now() + timedelta(hours=3)

    @staticmethod
    def utc_iso() -> str:
        return TimeUtils.utc_now().replace(tzinfo=UTC).isoformat()

    @staticmethod
    def mecca_iso() -> str:
        return TimeUtils.mecca_now().isoformat()

    @staticmethod
    def sql_iso() -> str:
        return TimeUtils.utc_now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def mecca_to_utc(dt):
        if dt is None:
            return None
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt - timedelta(hours=3)

    @staticmethod
    def utc_to_mecca(dt):
        if dt is None:
            return None
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt + timedelta(hours=3)

    @staticmethod
    def safe_parse_iso(date_str):
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
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                pass
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(UTC).replace(tzinfo=None)
            return dt
        except (ValueError, TypeError):
            return None

# =====================================================================
# 3) فئة Database
# =====================================================================

class Database(
    ChannelsPostsMixin, SubscriptionsMixin, GroupsMixin,
    TicketsMixin, ContestsMixin, StatsMixin, SettingsMixin,
    PointsMixin, BackupMixin, RemindersMixin,
):
    _instance = None
    _MAX_USER_LOCKS = MAX_USER_LOCKS_CONFIG

    BOOTSTRAP_DATA_VERSION = 7

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
        "delete_photos", "delete_banned_words", "delete_penalty",
        "antiflood", "night_mode", "warn_penalty", "violation_penalty",
    }
    VALID_VIOLATION_SETTINGS = {
        "welcome_enabled", "goodbye_enabled",
        "auto_approve_join", "auto_reject_join",
        "max_warnings", "violation_strikes", "violation_duration",
        "violation_penalty", "violation_penalty_duration",
        "auto_penalty", "delete_penalty_duration",
        "antiflood_enabled", "night_mode_enabled", "warn_enabled",
        "max_message_length",
    }
    MAX_PENALTY_DURATION = 365 * 86400

    BIGINT_COLUMNS = [
        ("bot_groups", "log_channel_id"),
        ("anonymous_admins", "user_id"),
        ("user_penalties", "user_id"),
        ("user_penalties", "chat_id"),
        ("user_warnings", "user_id"),
        ("user_warnings", "chat_id"),
        ("admin_logs", "admin_id"),
        ("admin_logs", "target_id"),
        ("admin_logs", "chat_id"),
        ("group_admins", "user_id"),
        ("group_admins", "chat_id"),
        ("hidden_admins", "admin_id"),
        ("hidden_admins", "chat_id"),
        ("hidden_owner_groups", "owner_id"),
        ("hidden_owner_groups", "chat_id"),
        ("user_messages", "user_id"),
        ("user_messages", "chat_id"),
    ]

    COLUMN_ALIASES = {
        "delete_mentions": "mentions", "delete_mention": "mentions",
        "remove_mentions": "mentions", "mention": "mentions",
        "mentions_filter": "mentions", "delete_mention_messages": "mentions",
        "delete_mention_message": "mentions",
        "delete_mentions_msgs": "mentions",
        "remove_mention": "mentions",
        "remove_links": "delete_links", "links": "delete_links",
        "delete_link": "delete_links", "remove_link": "delete_links",
        "links_filter": "delete_links", "delete_urls": "delete_links",
        "remove_urls": "delete_links", "url_filter": "delete_links",
        "delete_forwarded_messages": "delete_forwarded",
        "remove_forwards": "delete_forwarded",
        "forward": "delete_forwarded", "forwarded": "delete_forwarded",
        "delete_forward": "delete_forwarded",
        "remove_forward": "delete_forwarded",
        "forwards": "delete_forwarded",
        "delete_forwards": "delete_forwarded",
        "remove_forwarded": "delete_forwarded",
        "delete_polls_games": "delete_polls", "polls": "delete_polls",
        "remove_polls": "delete_polls", "delete_poll": "delete_polls",
        "poll": "delete_polls",
        "delete_polls_messages": "delete_polls",
        "games": "delete_games", "remove_games": "delete_games",
        "delete_game": "delete_games", "game": "delete_games",
        "delete_service_messages": "delete_service",
        "service_messages": "delete_service",
        "remove_service": "delete_service",
        "delete_service_msg": "delete_service",
        "delete_services": "delete_service",
        "service_msg": "delete_service",
        "service_message": "delete_service",
        "delete_service_message": "delete_service",
        "voice": "delete_voice", "remove_voice": "delete_voice",
        "delete_voices": "delete_voice",
        "delete_voice_messages": "delete_voice",
        "voice_messages": "delete_voice",
        "delete_voice_msg": "delete_voice",
        "remove_voice_messages": "delete_voice",
        "video_note": "delete_video_note",
        "delete_video_notes": "delete_video_note",
        "remove_video_note": "delete_video_note",
        "delete_videonote": "delete_video_note",
        "video_notes": "delete_video_note",
        "videonote": "delete_video_note",
        "remove_videonote": "delete_video_note",
        "delete_photo": "delete_photos", "photos": "delete_photos",
        "remove_photos": "delete_photos",
        "delete_photo_msg": "delete_photos",
        "photo": "delete_photos",
        "delete_photo_messages": "delete_photos",
        "remove_photo": "delete_photos",
        "delete_video": "delete_videos", "videos": "delete_videos",
        "remove_videos": "delete_videos", "video": "delete_videos",
        "delete_video_messages": "delete_videos",
        "remove_video": "delete_videos",
        "delete_audios": "delete_audio", "audios": "delete_audio",
        "remove_audio": "delete_audio", "audio": "delete_audio",
        "delete_audio_messages": "delete_audio",
        "delete_audio_msg": "delete_audio",
        "delete_gifs": "delete_animation", "gifs": "delete_animation",
        "gif": "delete_animation", "remove_gif": "delete_animation",
        "animation": "delete_animation", "animations": "delete_animation",
        "remove_animation": "delete_animation",
        "delete_document": "delete_documents",
        "documents": "delete_documents",
        "remove_documents": "delete_documents",
        "document": "delete_documents",
        "delete_document_messages": "delete_documents",
        "delete_doc": "delete_documents", "docs": "delete_documents",
        "delete_sticker": "delete_stickers", "stickers": "delete_stickers",
        "remove_stickers": "delete_stickers",
        "sticker": "delete_stickers",
        "delete_sticker_messages": "delete_stickers",
        "anti_flood": "antiflood_enabled", "flood": "antiflood_enabled",
        "antiflood": "antiflood_enabled",
        "flood_protection": "antiflood_enabled",
        "anti_flood_enabled": "antiflood_enabled",
        "anti_flood_protection": "antiflood_enabled",
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
        "warnings": "warn_enabled", "warn_system": "warn_enabled",
        "warning": "warn_enabled", "warnings_enabled": "warn_enabled",
        "warn": "warn_enabled", "warning_system": "warn_enabled",
        "welcome": "welcome_enabled",
        "welcome_message": "welcome_text",
        "welcome_msg": "welcome_text",
        "goodbye": "goodbye_enabled",
        "goodbye_message": "goodbye_text",
        "goodbye_msg": "goodbye_text",
        "auto_approve": "auto_approve_join",
        "auto_reject": "auto_reject_join",
        "approve_join": "auto_approve_join",
        "reject_join": "auto_reject_join",
        "auto_approve_enabled": "auto_approve_join",
        "auto_reject_enabled": "auto_reject_join",
        "slowmode": "slow_mode", "slow_mode_sec": "slow_mode_seconds",
        "slowmode_seconds": "slow_mode_seconds",
        "slow_mode_secs": "slow_mode_seconds",
        "nsfw": "nsfw_enabled", "nsfw_protection": "nsfw_enabled",
        "nsfw_filter_enabled": "nsfw_enabled",
        "antiflood_messages_count": "antiflood_messages",
        "antiflood_seconds_window": "antiflood_seconds",
        "antiflood_window": "antiflood_seconds",
        "message_length": "max_message_length",
        "max_length": "max_message_length",
        "message_max_length": "max_message_length",
        "auto_penalty_enabled": "auto_penalty",
        "delete_penalty_enabled": "delete_penalty",
        "delete_message_enabled": "delete_penalty",
        "violation_action": "violation_strikes",
        "violations_enabled": "violation_strikes",
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._singleton_init_done = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_singleton_init_done", False):
            return
        try:
            self._pool = None
            self._sqlite_queue = None
            self._sqlite_pool_size = SQLITE_POOL_SIZE
            self._initialized = False
            self._closing = False
            self._closed = False

            self._lock = asyncio.Lock()

            self._lifecycle_lock = asyncio.Lock()
            self._bootstrap_lock = asyncio.Lock()

            self._db_type = DB_TYPE
            self._max_connections = int(os.getenv("DB_POOL_SIZE", "20"))
            self._min_connections = int(os.getenv("DB_POOL_MIN_SIZE", "2"))
            self._connection_timeout = int(os.getenv("DB_TIMEOUT", "30"))

            self._cleanup_task = None
            self._secondary_index_task = None
            self._cache_cleanup_task = None

            self._bg_tasks: Set[asyncio.Task] = set()

            self._sqlite_creation_lock = asyncio.Lock()
            self._sqlite_open_count = 0
            self._sqlite_count_lock = asyncio.Lock()
            self._sqlite_alive_check_interval = 30.0

            try:
                self._active_sqlite_conns = weakref.WeakSet()
                self._use_weakset = True
            except Exception:
                self._active_sqlite_conns = set()
                self._use_weakset = False

            try:
                self._sqlite_alive_ts = weakref.WeakKeyDictionary()
                self._use_alive_cache = True
            except Exception:
                self._sqlite_alive_ts = None
                self._use_alive_cache = False

            self._alive_cache_warned = False
            self._pool_none_warned = False
            self._recovering_pool = False

            self._user_locks: Dict[int, asyncio.Lock] = {}
            self._channel_locks: Dict[int, asyncio.Lock] = {}
            self._user_locks_last_access: Dict[int, float] = {}
            self._user_locks_lock = asyncio.Lock()
            self._channel_locks_lock = asyncio.Lock()
            self._channel_locks_last_access = {}
            self._MAX_CHANNEL_LOCKS = MAX_CHANNEL_LOCKS_CONFIG
            self._group_locks = defaultdict(lambda: asyncio.Lock())
            self._group_locks_last_access = {}
            self._group_locks_lock = asyncio.Lock()
            self._MAX_GROUP_LOCKS = MAX_GROUP_LOCKS_CONFIG
            self._penalty_locks: Dict[Tuple[int, int], asyncio.Lock] = {}
            self._penalty_locks_last_access: Dict[Tuple[int, int], float] = {}
            self._penalty_locks_lock = asyncio.Lock()
            self._MAX_PENALTY_LOCKS = MAX_PENALTY_LOCKS_CONFIG
            self._overflow_penalty_lock = asyncio.Lock()
            self._overflow_lock_warned = False
            self._overflow_user_lock_warned = False

            self._backup_lock = asyncio.Lock()
            self._slow_query_log_threshold = float(
                os.getenv("SLOW_QUERY_LOG_THRESHOLD", "1.0")
            )
            self._max_post_text_length = MAX_POST_TEXT_LENGTH
            self._posts_batch_size = POSTS_BATCH_SIZE
            self._explain_slow_queries = EXPLAIN_SLOW_QUERIES
            self._query_timeout = self._connection_timeout * 2
            self._commit_timeout = 30
            self.DB_TYPE = DB_TYPE
            self.USE_POSTGRES = USE_POSTGRES
            self.USE_MYSQL = USE_MYSQL
            self.TimeUtils = TimeUtils
            self.internal_cache = internal_cache
            self.CACHE_AVAILABLE = CACHE_AVAILABLE
            self.banned_words_cache = banned_words_cache
            self.settings_cache = settings_cache
            self.groups_cache = groups_cache
            self.auth_cache = auth_cache
            self.posts_cache = posts_cache
            self.CONFIG = CONFIG
            self.PATHS = PATHS
            self.DATABASE_URL = DATABASE_URL

            # v7.7.11: متغيرات كاش الكلمات المحظورة
            self._banned_words_local_cache = {}
            self._global_banned_words_cache: List[str] = []
            self._global_banned_words_loaded = False
            self._global_words_lock = asyncio.Lock()

            self._banned_words_cache: Dict[int, List[str]] = {}
            self._banned_words_cache_time: Dict[int, float] = {}
            self._banned_words_cache_ttl: float = float(
                os.getenv("BANNED_WORDS_CACHE_TTL", "60")
            )
            self._banned_words_cache_lock = asyncio.Lock()

            self._group_security_columns_cache: Optional[set] = None

            self._singleton_init_done = True
        except Exception:
            self._singleton_init_done = False
            raise

    # =================================================================
    # 🔍 v7.7.12: Pool stats (اختياري — utils.py يقرأ _pool مباشرة)
    # =================================================================

    async def get_pool_stats(self) -> Dict[str, Any]:
        """
        🔍 v7.7.12: يُرجِع حالة Pool PostgreSQL/MySQL.
        ملاحظة: utils.BackgroundTasks._read_pool_stats يقرأ _pool مباشرة،
        لكن هذه الدالة تُوفّر واجهة نظيفة لمن يفضّلها.
        """
        if not (USE_POSTGRES or USE_MYSQL):
            return {"type": "sqlite_or_other"}
        pool = self._pool
        if pool is None:
            return {"type": "none", "error": "pool_is_none"}
        try:
            max_size = pool.get_max_size() if hasattr(pool, 'get_max_size') else None
            current_size = pool.get_size() if hasattr(pool, 'get_size') else None
            idle_size = pool.get_idle_size() if hasattr(pool, 'get_idle_size') else 0
            if max_size is None or current_size is None:
                return {"type": "unknown"}
            in_use = max(0, current_size - idle_size)
            util = round((in_use / max_size) * 100, 1) if max_size > 0 else 0.0
            return {
                "type": "postgres" if USE_POSTGRES else "mysql",
                "max_size": max_size,
                "current_size": current_size,
                "idle_size": idle_size,
                "in_use": in_use,
                "utilization_pct": util,
            }
        except Exception as e:
            return {"type": "error", "message": str(e)}

    # =================================================================
    # مساعد لتتبّع مهام الخلفية
    # =================================================================

    def _spawn_bg_task(self, coro) -> Optional[asyncio.Task]:
        try:
            task = asyncio.create_task(coro)
        except Exception as e:
            logger.warning(f"⚠️ فشل create_task: {e}")
            return None
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    # =================================================================
    # تتبع SQLite conns
    # =================================================================

    def _track_sqlite_conn(self, conn) -> None:
        if conn is None:
            return
        try:
            self._active_sqlite_conns.add(conn)
            return
        except TypeError as e:
            if self._use_weakset:
                logger.warning(
                    f"⚠️ WeakSet غير مدعوم لـ SQLite conn: {e} "
                    f"— التحويل إلى set() عادي"
                )
                self._active_sqlite_conns = set()
                self._use_weakset = False
                try:
                    self._active_sqlite_conns.add(conn)
                    return
                except Exception as e2:
                    logger.debug(f"_track_sqlite_conn fallback: {e2}")
        except Exception as e:
            logger.debug(f"_track_sqlite_conn: {e}")

    def _untrack_sqlite_conn(self, conn) -> None:
        if conn is None:
            return
        try:
            self._active_sqlite_conns.discard(conn)
        except Exception:
            pass
        if self._use_alive_cache and self._sqlite_alive_ts is not None:
            try:
                self._sqlite_alive_ts.pop(conn, None)
            except (TypeError, KeyError):
                pass

    # =================================================================
    # التهيئة
    # =================================================================

    async def initialize(self):
        if self._initialized:
            return
        async with self._lifecycle_lock:
            if self._initialized:
                return
            if self._closing:
                raise RuntimeError("Database is closing")
            await self._do_initialize()
            self._closed = False

    async def _do_initialize(self):
        try:
            if USE_POSTGRES:
                async def _pg_factory():
                    pool = await asyncpg.create_pool(
                        dsn=DATABASE_URL,
                        min_size=self._min_connections,
                        max_size=self._max_connections,
                        timeout=self._connection_timeout,
                        command_timeout=self._connection_timeout,
                        statement_cache_size=500,
                        server_settings={
                            "application_name": "RelaxManager",
                            "statement_timeout": "30s",
                            "timezone": "UTC",
                        },
                    )
                    try:
                        async with pool.acquire() as _c:
                            await _c.fetchval("SELECT 1")
                    except Exception as _test_e:
                        raise _FactoryFailed(
                            f"PG pool اختبار فشل: {_test_e}", pool
                        )
                    return pool

                async def _pg_cleanup(pool):
                    try:
                        await pool.close()
                    except Exception:
                        pass

                self._pool = await _create_pool_with_retry(
                    _pg_factory, "PostgreSQL", max_attempts=5,
                    cleanup=_pg_cleanup,
                )
                logger.info(
                    f"✅ Pool PostgreSQL جاهز "
                    f"(min={self._min_connections}, "
                    f"max={self._max_connections})"
                )
            elif USE_MYSQL:
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

                async def _mysql_factory():
                    pool = await asyncmy.create_pool(
                        host=_mysql_cfg["host"],
                        port=_mysql_cfg["port"],
                        user=_mysql_cfg["user"],
                        password=_mysql_cfg["password"],
                        db=_mysql_cfg["db"],
                        minsize=self._min_connections,
                        maxsize=self._max_connections,
                        pool_recycle=3600, autocommit=False,
                        charset="utf8mb4",
                        init_command="SET time_zone = '+00:00'",
                    )
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

                async def _mysql_cleanup(pool):
                    try:
                        pool.close()
                        await pool.wait_closed()
                    except Exception:
                        pass

                self._pool = await _create_pool_with_retry(
                    _mysql_factory, "MySQL", max_attempts=5,
                    cleanup=_mysql_cleanup,
                )
                logger.info(
                    f"✅ Pool MySQL جاهز "
                    f"(min={self._min_connections}, "
                    f"max={self._max_connections})"
                )
            else:
                async def _sqlite_factory():
                    conn = await self._create_sqlite_connection()
                    if conn is None:
                        raise RuntimeError("فشل اتصال SQLite")
                    return conn

                conn = await _create_pool_with_retry(
                    _sqlite_factory, "SQLite", max_attempts=3
                )
                self._sqlite_queue = asyncio.Queue(
                    maxsize=self._sqlite_pool_size
                )
                await self._sqlite_queue.put(conn)
                self._sqlite_open_count = 1
                logger.info(
                    f"✅ Pool SQLite جاهز "
                    f"(size={self._sqlite_pool_size}, initial=1)"
                )

            self._pool_none_warned = False

            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(
                    self._auto_cleanup_locks()
                )
            self._initialized = True
        except Exception as e:
            if self._pool is not None:
                try:
                    if USE_POSTGRES:
                        await self._pool.close()
                    elif USE_MYSQL:
                        self._pool.close()
                        await self._pool.wait_closed()
                except Exception:
                    pass
                self._pool = None
            if self._sqlite_queue is not None:
                try:
                    while not self._sqlite_queue.empty():
                        conn = await self._sqlite_queue.get()
                        self._untrack_sqlite_conn(conn)
                        try:
                            await conn.close()
                        except Exception:
                            pass
                except Exception:
                    pass
                self._sqlite_queue = None
                self._sqlite_open_count = 0
            logger.error(f"❌ فشل التهيئة: {e}", exc_info=True)
            raise

    async def _create_sqlite_connection(self):
        conn = None
        try:
            conn = await aiosqlite.connect(
                str(PATHS.DB),
                timeout=self._connection_timeout,
                check_same_thread=False,
            )
            conn.row_factory = aiosqlite.Row

            pragmas = [
                ("busy_timeout", "10000"),
                ("journal_mode", "WAL"),
                ("synchronous", "NORMAL"),
                ("foreign_keys", "ON"),
                ("cache_size", "-20000"),
                ("temp_store", "MEMORY"),
                ("wal_autocheckpoint", "1000"),
                ("mmap_size", "268435456"),
            ]
            for name, value in pragmas:
                try:
                    await conn.execute(f"PRAGMA {name}={value}")
                except Exception as pe:
                    logger.debug(
                        f"⚠️ PRAGMA {name}={value}: {pe}"
                    )

            self._track_sqlite_conn(conn)
            return conn
        except Exception as e:
            logger.error(f"❌ فشل SQLite conn: {e}")
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass
            return None

    async def _sqlite_is_alive(self, conn) -> bool:
        if not self._use_alive_cache or self._sqlite_alive_ts is None:
            try:
                cursor = await conn.execute("SELECT 1")
                try:
                    await cursor.fetchone()
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
                return True
            except Exception:
                return False

        now = time.monotonic()
        try:
            last = self._sqlite_alive_ts.get(conn, 0)
        except (TypeError, KeyError):
            if not self._alive_cache_warned:
                logger.debug(
                    "⚠️ WeakKeyDictionary.get فشل — fallback مباشر"
                )
                self._alive_cache_warned = True
            try:
                cursor = await conn.execute("SELECT 1")
                try:
                    await cursor.fetchone()
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
                return True
            except Exception:
                return False

        if now - last < self._sqlite_alive_check_interval:
            return True

        try:
            cursor = await conn.execute("SELECT 1")
            try:
                await cursor.fetchone()
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
            try:
                self._sqlite_alive_ts[conn] = now
            except (TypeError, KeyError):
                pass
            return True
        except Exception:
            try:
                self._sqlite_alive_ts.pop(conn, None)
            except (TypeError, KeyError):
                pass
            return False

    async def close(self):
        async with self._lifecycle_lock:
            if self._closed:
                return
            self._closing = True
            cleanup_error: Optional[BaseException] = None
            try:
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
                for bg in list(self._bg_tasks):
                    if not bg.done():
                        bg.cancel()
                        tasks.append(bg)
                if tasks:
                    results = await asyncio.gather(
                        *tasks, return_exceptions=True
                    )
                    for r in results:
                        if isinstance(r, Exception) and not isinstance(
                            r, asyncio.CancelledError
                        ):
                            logger.warning(
                                f"⚠️ فشل task أثناء close: {r}"
                            )
                self._bg_tasks.clear()

                if USE_POSTGRES and self._pool:
                    try:
                        await self._pool.close()
                    except Exception as e:
                        logger.warning(f"⚠️ إغلاق PG pool: {e}")
                    finally:
                        self._pool = None
                elif USE_MYSQL and self._pool:
                    try:
                        self._pool.close()
                        await self._pool.wait_closed()
                    except Exception as e:
                        logger.warning(f"⚠️ إغلاق MySQL pool: {e}")
                    finally:
                        self._pool = None
                else:
                    if self._sqlite_queue is not None:
                        try:
                            while not self._sqlite_queue.empty():
                                conn = await self._sqlite_queue.get()
                                self._untrack_sqlite_conn(conn)
                                try:
                                    await conn.close()
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.warning(f"⚠️ إغلاق SQLite queue: {e}")
                        finally:
                            self._sqlite_queue = None
                            self._sqlite_open_count = 0

                    if self._active_sqlite_conns:
                        active_count = len(self._active_sqlite_conns)
                        logger.info(
                            f"⏳ انتظار {active_count} SQLite conn نشط "
                            f"(grace period 5s)..."
                        )
                        grace_deadline = time.monotonic() + 5.0
                        while (
                            self._active_sqlite_conns
                            and time.monotonic() < grace_deadline
                        ):
                            await asyncio.sleep(0.1)

                        remaining = list(self._active_sqlite_conns)
                        if remaining:
                            logger.warning(
                                f"⚠️ إغلاق قسري لـ {len(remaining)} "
                                f"SQLite conn بعد انتهاء grace"
                            )
                        for conn in remaining:
                            try:
                                await conn.close()
                            except Exception:
                                pass

                    try:
                        self._active_sqlite_conns.clear()
                    except Exception:
                        pass

                    if self._use_alive_cache and self._sqlite_alive_ts is not None:
                        try:
                            self._sqlite_alive_ts.clear()
                        except Exception:
                            pass

                try:
                    await clear_all_caches()
                except Exception:
                    pass

                self._cleanup_task = None
                self._secondary_index_task = None
                self._cache_cleanup_task = None
                self._closed = True
            except BaseException as be:
                cleanup_error = be
            finally:
                self._initialized = False
                self._closing = False
            if cleanup_error is not None:
                raise cleanup_error

    async def reconnect(self):
        try:
            logger.info("🔄 إعادة الاتصال...")
            try:
                await self.close()
            except Exception as e:
                logger.warning(f"⚠️ close في reconnect: {e}")

            self._closed = False
            self._closing = False

            await self.initialize()

            try:
                async with self.connection() as conn:
                    await self._create_tables(conn=conn)
                    await self._migrate_schema(conn)
            except Exception as e:
                logger.warning(f"⚠️ re-migrate: {e}")

            if CACHE_AVAILABLE and (
                self._cache_cleanup_task is None
                or self._cache_cleanup_task.done()
            ):
                self._cache_cleanup_task = asyncio.create_task(
                    cache_cleanup_task()
                )
            logger.info("✅ reconnect نجح")
            return True
        except Exception as e:
            logger.error(f"❌ reconnect: {e}", exc_info=True)
            return False

    async def _recover_pool(self):
        if self._recovering_pool:
            return
        self._recovering_pool = True
        try:
            logger.warning("🔄 محاولة إعادة إنشاء pool...")
            await asyncio.sleep(2)
            await self.reconnect()
        except Exception as e:
            logger.error(f"❌ فشل _recover_pool: {e}")
        finally:
            self._recovering_pool = False

    # =================================================================
    # _get_connection
    # =================================================================

    async def _get_connection(self):
        if self._closing:
            raise RuntimeError("Database is closing")
        if not self._initialized:
            await self.initialize()

        if USE_POSTGRES or USE_MYSQL:
            if self._pool is None:
                raise RuntimeError("DB pool is None")
            try:
                conn = await asyncio.wait_for(
                    self._pool.acquire(),
                    timeout=self._connection_timeout,
                )
                return conn
            except asyncio.TimeoutError:
                raise RuntimeError("DB pool acquire timeout")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                err = str(e).lower()
                if "pool" in err or "closed" in err or "acquire" in err:
                    raise RuntimeError(f"DB pool unavailable: {e}")
                raise
        else:
            try:
                conn = await asyncio.wait_for(
                    self._sqlite_queue.get(), timeout=1.0
                )
                if not await self._sqlite_is_alive(conn):
                    logger.warning("⚠️ SQLite conn ميت — استبدال")
                    self._untrack_sqlite_conn(conn)
                    try:
                        await conn.close()
                    except Exception:
                        pass
                    async with self._sqlite_count_lock:
                        self._sqlite_open_count = max(
                            0, self._sqlite_open_count - 1
                        )
                    reserved = False
                    async with self._sqlite_creation_lock:
                        async with self._sqlite_count_lock:
                            if self._sqlite_open_count < self._sqlite_pool_size:
                                self._sqlite_open_count += 1
                                reserved = True
                    if reserved:
                        new_conn = await self._create_sqlite_connection()
                        if new_conn is not None:
                            return new_conn
                        async with self._sqlite_count_lock:
                            self._sqlite_open_count = max(
                                0, self._sqlite_open_count - 1
                            )
                    raise RuntimeError("فشل استبدال SQLite conn")
                return conn
            except asyncio.TimeoutError:
                reserved = False
                async with self._sqlite_creation_lock:
                    async with self._sqlite_count_lock:
                        if self._sqlite_open_count < self._sqlite_pool_size:
                            self._sqlite_open_count += 1
                            reserved = True
                if reserved:
                    conn = await self._create_sqlite_connection()
                    if conn is not None:
                        return conn
                    async with self._sqlite_count_lock:
                        self._sqlite_open_count = max(
                            0, self._sqlite_open_count - 1
                        )
                return await asyncio.wait_for(
                    self._sqlite_queue.get(),
                    timeout=self._connection_timeout,
                )

    async def _return_connection(self, conn):
        if USE_POSTGRES or USE_MYSQL:
            if self._pool is None:
                if not self._pool_none_warned:
                    logger.warning(
                        "⚠️ pool=None أثناء release (إغلاق جارٍ) — "
                        "سيتم تجاهل هذه الرسالة لاحقاً"
                    )
                    self._pool_none_warned = True
                return
            try:
                await self._pool.release(conn)
            except Exception as e:
                logger.warning(f"⚠️ release فشل: {e}")
        else:
            try:
                if self._sqlite_queue is not None:
                    try:
                        await asyncio.wait_for(
                            self._sqlite_queue.put(conn), timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning("⚠️ طابور SQLite ممتلئ")
                        self._untrack_sqlite_conn(conn)
                        await conn.close()
                        async with self._sqlite_count_lock:
                            self._sqlite_open_count = max(
                                0, self._sqlite_open_count - 1
                            )
                else:
                    self._untrack_sqlite_conn(conn)
                    await conn.close()
                    async with self._sqlite_count_lock:
                        self._sqlite_open_count = max(
                            0, self._sqlite_open_count - 1
                        )
            except Exception as e:
                logger.warning(f"⚠️ إرجاع SQLite: {e}")
                self._untrack_sqlite_conn(conn)
                try:
                    await conn.close()
                except Exception:
                    pass
                async with self._sqlite_count_lock:
                    self._sqlite_open_count = max(
                        0, self._sqlite_open_count - 1
                    )

    async def _destroy_connection(self, conn):
        if USE_POSTGRES:
            try:
                if hasattr(conn, "terminate"):
                    conn.terminate()
                else:
                    await conn.close()
            except Exception as e:
                logger.debug(f"PG destroy: {e}")
        elif USE_MYSQL:
            try:
                conn.close()
            except Exception as e:
                logger.debug(f"MySQL close: {e}")
            if self._pool is not None:
                try:
                    await self._pool.release(conn)
                except Exception as e:
                    logger.debug(f"MySQL release-after-destroy: {e}")
        else:
            self._untrack_sqlite_conn(conn)
            try:
                await conn.close()
            except Exception:
                pass
            async with self._sqlite_count_lock:
                self._sqlite_open_count = max(
                    0, self._sqlite_open_count - 1
                )

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
                    logger.error(f"❌ SQLite COMMIT فشل: {e}")
                    raise
            elif USE_MYSQL:
                try:
                    await conn.commit()
                except Exception as e:
                    logger.warning(f"⚠️ MySQL commit: {e}")
                    raise
        except Exception:
            if DB_TYPE == "sqlite":
                try:
                    if conn.in_transaction:
                        await conn.rollback()
                except Exception:
                    pass
            elif USE_MYSQL:
                try:
                    await conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            await self._return_connection(conn)

    @asynccontextmanager
    async def transaction(self):
        conn = await self._get_connection()
        tx = None
        destroy = False
        try:
            if USE_POSTGRES:
                tx = conn.transaction()
                await tx.start()
            elif USE_MYSQL:
                await conn.execute("START TRANSACTION")
            else:
                await conn.execute("BEGIN TRANSACTION")
            yield conn
            try:
                if USE_POSTGRES:
                    await asyncio.wait_for(
                        tx.commit(), timeout=self._commit_timeout
                    )
                else:
                    await asyncio.wait_for(
                        conn.execute("COMMIT"),
                        timeout=self._commit_timeout,
                    )
            except BaseException:
                destroy = True
                raise
        except BaseException as e:
            try:
                if USE_POSTGRES and tx is not None:
                    await asyncio.wait_for(
                        tx.rollback(), timeout=self._commit_timeout
                    )
                else:
                    await asyncio.wait_for(
                        conn.execute("ROLLBACK"),
                        timeout=self._commit_timeout,
                    )
            except BaseException as re_exc:
                if not isinstance(re_exc, asyncio.CancelledError):
                    logger.warning(f"⚠️ rollback: {re_exc}")
                destroy = True
            if not isinstance(e, asyncio.CancelledError):
                logger.error(f"❌ فشلت المعاملة: {e}", exc_info=True)
            raise
        finally:
            if destroy:
                try:
                    await self._destroy_connection(conn)
                except asyncio.CancelledError:
                    try:
                        if USE_POSTGRES and hasattr(conn, "terminate"):
                            conn.terminate()
                        elif USE_MYSQL:
                            conn.close()
                    except Exception:
                        pass
                    raise
                except Exception as de:
                    logger.warning(f"⚠️ destroy_connection: {de}")
                    await self._return_connection(conn)
            else:
                await self._return_connection(conn)

    # =================================================================
    # Query layer
    # =================================================================

    async def _execute_with_logging(
        self, query: str, params: tuple, conn, executor,
        skip_explain: bool = False,
    ):
        start = time.monotonic()
        try:
            result = await executor(query, params)
            elapsed = time.monotonic() - start
            if elapsed > self._slow_query_log_threshold:
                safe_query = re.sub(
                    r"\b\d{6,}\b", "[REDACTED]", query[:200]
                )
                logger.warning(f"🐌 بطيء ({elapsed:.2f}s): {safe_query}")
                if self._explain_slow_queries and not skip_explain:
                    await self._log_explain(query, params, conn)
            return result
        except Exception as e:
            elapsed = time.monotonic() - start
            safe_query = re.sub(r"\b\d{6,}\b", "[REDACTED]", query[:200])
            logger.error(
                f"❌ فشل ({elapsed:.2f}s): {safe_query} | {e}"
            )
            raise

    async def _log_explain(self, query: str, params: tuple, conn):
        try:
            upper_q = query.lstrip().upper()
            if not upper_q.startswith("SELECT"):
                return
            if " FOR UPDATE" in upper_q or " FOR SHARE" in upper_q:
                return
            if USE_POSTGRES:
                explain = await conn.fetch(
                    f"EXPLAIN (BUFFERS) {query}", *params
                )
                logger.info(
                    "📊 EXPLAIN:\n" + "\n".join(str(r) for r in explain)
                )
            elif USE_MYSQL:
                cursor = await conn.cursor()
                try:
                    await cursor.execute(f"EXPLAIN {query}", params)
                    explain = await cursor.fetchall()
                    logger.info(
                        "📊 EXPLAIN:\n"
                        + "\n".join(str(r) for r in explain)
                    )
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
            else:
                cursor = await conn.execute(
                    f"EXPLAIN QUERY PLAN {query}", params
                )
                try:
                    explain = await cursor.fetchall()
                    logger.info(
                        "📊 EXPLAIN:\n"
                        + "\n".join(str(r) for r in explain)
                    )
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"⚠️ EXPLAIN: {e}")

    async def _execute_with_retry(
        self, query: str, params, executor, max_retries=3
    ):
        AsyncMySQLError = None
        if USE_MYSQL:
            try:
                from asyncmy.errors import MySQLError as AsyncMySQLError
            except ImportError:
                try:
                    from asyncmy import MySQLError as AsyncMySQLError
                except ImportError:
                    AsyncMySQLError = None

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
                        if "malformed" in error_msg:
                            logger.error(
                                "❌ SQLite malformed — لا إعادة"
                            )
                            raise
                        if any(kw in error_msg for kw in [
                            "database is locked", "busy",
                            "disk i/o error",
                        ]):
                            retryable = True
                elif USE_POSTGRES and isinstance(
                    e, asyncpg.exceptions.DeadlockDetectedError
                ):
                    retryable = True
                elif USE_POSTGRES and isinstance(
                    e, asyncpg.exceptions.PostgresConnectionError
                ):
                    retryable = True
                    self._spawn_bg_task(self._recover_pool())
                elif USE_MYSQL and AsyncMySQLError is not None:
                    try:
                        if isinstance(e, AsyncMySQLError):
                            error_msg = str(e).lower()
                            if any(kw in error_msg for kw in [
                                "deadlock", "lock wait",
                                "connection", "timeout",
                            ]):
                                retryable = True
                            if "connection" in error_msg:
                                self._spawn_bg_task(
                                    self._recover_pool()
                                )
                    except Exception:
                        pass
                if retryable and attempt < max_retries - 1:
                    delay = (0.5 * (attempt + 1)) + (0.1 * attempt)
                    logger.warning(
                        f"⚠️ إعادة {attempt + 1}/{max_retries} "
                        f"بعد {delay:.2f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
        if last_exception is None:
            raise RuntimeError("max_retries=0")
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
        params = _adapt_params(params, q) if params else ()

        if USE_POSTGRES:
            result = await self._execute_with_logging(
                q, params, conn, lambda q2, p2: conn.execute(q2, *p2)
            )
            if not result:
                return 0
            m = re.search(
                r"\b(?:INSERT|UPDATE|DELETE)\b.*?\s(\d+)\s*$",
                result, re.IGNORECASE | re.DOTALL,
            )
            if m:
                return int(m.group(1))
            return 0
        elif USE_MYSQL:
            cursor = await conn.cursor()
            try:
                await self._execute_with_logging(
                    q, params, conn,
                    lambda q2, p2: cursor.execute(q2, p2)
                )
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
            cursor2 = await conn.cursor()
            try:
                await cursor2.execute("SELECT ROW_COUNT()")
                row = await cursor2.fetchone()
                return row[0] if row else 0
            finally:
                try:
                    await cursor2.close()
                except Exception:
                    pass
        else:
            cursor = await self._execute_with_logging(
                q, params, conn, lambda q2, p2: conn.execute(q2, p2)
            )
            try:
                return cursor.rowcount
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass

    async def _executemany_with_conn(
        self, conn, query: str, params_list: List[tuple]
    ) -> int:
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
        params_list = [_adapt_params(p, q) for p in params_list]

        upper_q_after = q.upper().lstrip()
        is_idempotent = (
            " ON CONFLICT " in upper_q_after
            or upper_q_after.startswith("INSERT IGNORE ")
        )

        if USE_POSTGRES:
            try:
                await conn.executemany(q, params_list)
                return len(params_list)
            except Exception as e:
                if not is_idempotent:
                    raise
                logger.warning(f"⚠️ executemany فشل: {e}")
                total = 0
                for params in params_list:
                    try:
                        result = await self._execute_with_logging(
                            q, params, conn,
                            lambda q2, p2: conn.execute(q2, *p2),
                            skip_explain=True,
                        )
                        m = re.search(
                            r"\b(?:INSERT|UPDATE|DELETE)\b.*?\s(\d+)\s*$",
                            result or "",
                            re.IGNORECASE | re.DOTALL,
                        )
                        total += int(m.group(1)) if m else 1
                    except Exception:
                        continue
                return total
        elif USE_MYSQL:
            cursor = await conn.cursor()
            try:
                await self._execute_with_logging(
                    q, params_list, conn,
                    lambda q2, p2: cursor.executemany(q2, p2),
                    skip_explain=True,
                )
                return cursor.rowcount
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
        else:
            cursor = await self._execute_with_logging(
                q, params_list, conn,
                lambda q2, p2: conn.executemany(q2, p2),
                skip_explain=True,
            )
            try:
                return cursor.rowcount
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass

    async def _fetchone_with_conn(self, conn, query: str, *params):
        q = _convert_placeholders(query)
        params = _adapt_params(params, q) if params else ()
        if USE_POSTGRES:
            row = await self._execute_with_logging(
                q, params, conn,
                lambda q2, p2: conn.fetchrow(q2, *p2)
            )
            return dict(row) if row else None
        elif USE_MYSQL:
            cursor = await conn.cursor()
            try:
                await self._execute_with_logging(
                    q, params, conn,
                    lambda q2, p2: cursor.execute(q2, p2)
                )
                row = await cursor.fetchone()
                desc = cursor.description
                if row and desc:
                    return dict(zip([d[0] for d in desc], row))
                return None
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
        else:
            cursor = await self._execute_with_logging(
                q, params, conn,
                lambda q2, p2: conn.execute(q2, p2)
            )
            try:
                row = await cursor.fetchone()
                return dict(row) if row else None
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass

    async def _fetchall_with_conn(self, conn, query: str, *params):
        q = _convert_placeholders(query)
        params = _adapt_params(params, q) if params else ()
        if USE_POSTGRES:
            rows = await self._execute_with_logging(
                q, params, conn,
                lambda q2, p2: conn.fetch(q2, *p2)
            )
            return [dict(row) for row in rows]
        elif USE_MYSQL:
            cursor = await conn.cursor()
            try:
                await self._execute_with_logging(
                    q, params, conn,
                    lambda q2, p2: cursor.execute(q2, p2)
                )
                rows = await cursor.fetchall()
                desc = cursor.description
                if rows and desc:
                    cols = [d[0] for d in desc]
                    return [dict(zip(cols, row)) for row in rows]
                return []
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
        else:
            cursor = await self._execute_with_logging(
                q, params, conn,
                lambda q2, p2: conn.execute(q2, p2)
            )
            try:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass

    async def _fetchval_with_conn(
        self, conn, query: str, *params, default=None
    ):
        q = _convert_placeholders(query)
        params = _adapt_params(params, q) if params else ()
        if USE_POSTGRES:
            val = await self._execute_with_logging(
                q, params, conn,
                lambda q2, p2: conn.fetchval(q2, *p2)
            )
            return val if val is not None else default
        elif USE_MYSQL:
            cursor = await conn.cursor()
            try:
                await self._execute_with_logging(
                    q, params, conn,
                    lambda q2, p2: cursor.execute(q2, p2)
                )
                row = await cursor.fetchone()
                return row[0] if row else default
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
        else:
            cursor = await self._execute_with_logging(
                q, params, conn,
                lambda q2, p2: conn.execute(q2, p2)
            )
            try:
                row = await cursor.fetchone()
                return row[0] if row else default
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass

    async def execute(self, query: str, params: tuple = ()) -> int:
        async def _exec(q, p):
            async with self.connection() as conn:
                return await self._execute_with_conn(conn, q, *p)
        try:
            return await asyncio.wait_for(
                self._execute_with_retry(query, params, _exec),
                timeout=self._query_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"❌ timeout execute: {query[:100]}")
            raise

    async def fetchone(self, query: str, params: tuple = ()):
        async def _exec(q, p):
            async with self.connection() as conn:
                return await self._fetchone_with_conn(conn, q, *p)
        try:
            return await asyncio.wait_for(
                self._execute_with_retry(query, params, _exec),
                timeout=self._query_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"❌ timeout fetchone: {query[:100]}")
            raise

    async def fetchall(self, query: str, params: tuple = ()):
        async def _exec(q, p):
            async with self.connection() as conn:
                return await self._fetchall_with_conn(conn, q, *p)
        try:
            return await asyncio.wait_for(
                self._execute_with_retry(query, params, _exec),
                timeout=self._query_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"❌ timeout fetchall: {query[:100]}")
            raise

    async def fetchval(
        self, query: str, params: tuple = (), default=None
    ):
        async def _exec(q, p):
            async with self.connection() as conn:
                return await self._fetchval_with_conn(
                    conn, q, *p, default=default
                )
        try:
            return await asyncio.wait_for(
                self._execute_with_retry(query, params, _exec),
                timeout=self._query_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"❌ timeout fetchval: {query[:100]}")
            raise

    async def executemany(
        self, query: str, params_list: List[tuple]
    ) -> int:
        if not params_list:
            return 0
        try:
            async with self.connection() as conn:
                return await asyncio.wait_for(
                    self._executemany_with_conn(
                        conn, query, params_list
                    ),
                    timeout=self._query_timeout,
                )
        except asyncio.TimeoutError:
            logger.error(f"❌ timeout executemany: {query[:100]}")
            raise

    # =================================================================
    # الأقفال
    # =================================================================

    async def _get_user_lock(self, user_id: int) -> asyncio.Lock:
        async with self._user_locks_lock:
            if len(self._user_locks) >= self._MAX_USER_LOCKS:
                sorted_items = sorted(
                    self._user_locks_last_access.items(),
                    key=lambda x: x[1],
                )
                to_remove = []
                target = max(1, len(sorted_items) // 4)
                for uid, _ in sorted_items:
                    if len(to_remove) >= target:
                        break
                    lock = self._user_locks.get(uid)
                    if lock and not lock.locked():
                        to_remove.append(uid)
                for uid in to_remove:
                    self._user_locks.pop(uid, None)
                    self._user_locks_last_access.pop(uid, None)
                if len(self._user_locks) >= self._MAX_USER_LOCKS:
                    if not self._overflow_user_lock_warned:
                        logger.warning(
                            f"⚠️ user_locks تجاوز الحد "
                            f"({len(self._user_locks)}/{self._MAX_USER_LOCKS}) "
                            f"— يسمح بالنمو"
                        )
                        self._overflow_user_lock_warned = True
            if user_id not in self._user_locks:
                self._user_locks[user_id] = asyncio.Lock()
            self._user_locks_last_access[user_id] = time.monotonic()
            return self._user_locks[user_id]

    async def _get_channel_lock(
        self, channel_db_id: int
    ) -> asyncio.Lock:
        async with self._channel_locks_lock:
            if (
                len(self._channel_locks) >= self._MAX_CHANNEL_LOCKS
                and channel_db_id not in self._channel_locks
            ):
                sorted_items = sorted(
                    self._channel_locks_last_access.items(),
                    key=lambda x: x[1],
                )
                to_remove = []
                for cid, _ in sorted_items[
                    :self._MAX_CHANNEL_LOCKS // 5
                ]:
                    lock = self._channel_locks.get(cid)
                    if lock and not lock.locked():
                        to_remove.append(cid)
                for cid in to_remove:
                    self._channel_locks.pop(cid, None)
                    self._channel_locks_last_access.pop(cid, None)
            if channel_db_id not in self._channel_locks:
                self._channel_locks[channel_db_id] = asyncio.Lock()
            self._channel_locks_last_access[channel_db_id] = (
                time.monotonic()
            )
            return self._channel_locks[channel_db_id]

    async def _get_group_lock(self, chat_id: int) -> asyncio.Lock:
        async with self._group_locks_lock:
            if (
                len(self._group_locks) >= self._MAX_GROUP_LOCKS
                and chat_id not in self._group_locks
            ):
                sorted_items = sorted(
                    self._group_locks_last_access.items(),
                    key=lambda x: x[1],
                )
                to_remove = []
                for cid, _ in sorted_items[
                    :self._MAX_GROUP_LOCKS // 5
                ]:
                    lock = self._group_locks.get(cid)
                    if lock and not lock.locked():
                        to_remove.append(cid)
                for cid in to_remove:
                    self._group_locks.pop(cid, None)
                    self._group_locks_last_access.pop(cid, None)
            self._group_locks_last_access[chat_id] = time.monotonic()
            return self._group_locks[chat_id]

    async def _get_penalty_lock(
        self, user_id: int, chat_id: int
    ) -> asyncio.Lock:
        key = (user_id, chat_id)
        async with self._penalty_locks_lock:
            if key in self._penalty_locks:
                self._penalty_locks_last_access[key] = time.monotonic()
                return self._penalty_locks[key]

            if len(self._penalty_locks) >= self._MAX_PENALTY_LOCKS:
                sorted_items = sorted(
                    self._penalty_locks_last_access.items(),
                    key=lambda x: x[1],
                )
                to_remove = []
                for k, _ in sorted_items:
                    if len(to_remove) >= self._MAX_PENALTY_LOCKS // 5:
                        break
                    lock = self._penalty_locks.get(k)
                    if lock and not lock.locked():
                        to_remove.append(k)
                for k in to_remove:
                    self._penalty_locks.pop(k, None)
                    self._penalty_locks_last_access.pop(k, None)

                if len(self._penalty_locks) >= self._MAX_PENALTY_LOCKS:
                    if not self._overflow_lock_warned:
                        logger.warning(
                            f"⚠️ penalty_locks ممتلئ "
                            f"({self._MAX_PENALTY_LOCKS}) — "
                            f"التحويل إلى overflow lock مشترك"
                        )
                        self._overflow_lock_warned = True
                    return self._overflow_penalty_lock

            self._penalty_locks[key] = asyncio.Lock()
            self._penalty_locks_last_access[key] = time.monotonic()
            return self._penalty_locks[key]

    async def cleanup_user_locks(
        self, max_idle_seconds: int = 3600
    ) -> int:
        try:
            async with self._user_locks_lock:
                now = time.monotonic()
                to_remove = []
                for uid, ts in list(
                    self._user_locks_last_access.items()
                ):
                    if now - ts > max_idle_seconds:
                        lock = self._user_locks.get(uid)
                        if lock and not lock.locked():
                            to_remove.append(uid)
                for uid in to_remove:
                    self._user_locks.pop(uid, None)
                    self._user_locks_last_access.pop(uid, None)
                if len(self._user_locks) < self._MAX_USER_LOCKS:
                    self._overflow_user_lock_warned = False
                return len(to_remove)
        except Exception as e:
            logger.error(f"❌ cleanup_user_locks: {e}")
            return 0

    async def cleanup_channel_locks(
        self, max_idle_seconds: int = 3600
    ) -> int:
        try:
            async with self._channel_locks_lock:
                now = time.monotonic()
                to_remove = []
                for cid, ts in list(
                    self._channel_locks_last_access.items()
                ):
                    if now - ts > max_idle_seconds:
                        lock = self._channel_locks.get(cid)
                        if lock and not lock.locked():
                            to_remove.append(cid)
                for cid in to_remove:
                    self._channel_locks.pop(cid, None)
                    self._channel_locks_last_access.pop(cid, None)
                return len(to_remove)
        except Exception as e:
            logger.error(f"❌ cleanup_channel_locks: {e}")
            return 0

    async def cleanup_group_locks(
        self, max_idle_seconds: int = 3600
    ) -> int:
        try:
            async with self._group_locks_lock:
                now = time.monotonic()
                to_remove = []
                for cid, ts in list(
                    self._group_locks_last_access.items()
                ):
                    if now - ts > max_idle_seconds:
                        lock = self._group_locks.get(cid)
                        if lock and not lock.locked():
                            to_remove.append(cid)
                for cid in to_remove:
                    self._group_locks.pop(cid, None)
                    self._group_locks_last_access.pop(cid, None)
                return len(to_remove)
        except Exception as e:
            logger.error(f"❌ cleanup_group_locks: {e}")
            return 0

    async def cleanup_penalty_locks(
        self, max_idle_seconds: int = 3600
    ) -> int:
        try:
            async with self._penalty_locks_lock:
                now = time.monotonic()
                to_remove = []
                for key, ts in list(
                    self._penalty_locks_last_access.items()
                ):
                    if now - ts > max_idle_seconds:
                        lock = self._penalty_locks.get(key)
                        if lock and not lock.locked():
                            to_remove.append(key)
                for key in to_remove:
                    self._penalty_locks.pop(key, None)
                    self._penalty_locks_last_access.pop(key, None)
                if len(self._penalty_locks) < self._MAX_PENALTY_LOCKS:
                    self._overflow_lock_warned = False
                return len(to_remove)
        except Exception as e:
            logger.error(f"❌ cleanup_penalty_locks: {e}")
            return 0

    async def _auto_cleanup_locks(self):
        while True:
            try:
                await self.cleanup_user_locks()
                await self.cleanup_channel_locks()
                await self.cleanup_group_locks()
                await self.cleanup_penalty_locks()
            except asyncio.CancelledError:
                logger.info("🛑 cleanup مُلغى")
                break
            except Exception as e:
                logger.error(f"❌ _auto_cleanup_locks: {e}")
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break

    # =================================================================
    # إنشاء الجداول
    # =================================================================

    async def _create_tables(self, conn=None):
        if not TABLES_MODULE_AVAILABLE:
            raise RuntimeError("❌ database_tables.py غير متاح")

        async def _do_all(c):
            if USE_POSTGRES:
                await create_tables_postgres(c, logger, TimeUtils)
                logger.info("✅ جداول PG")
            elif USE_MYSQL:
                await create_tables_mysql(c, logger, TimeUtils)
                logger.info("✅ جداول MySQL")
            else:
                await create_tables_sqlite(c, logger, TimeUtils)
                logger.info("✅ جداول SQLite")

            if hasattr(self, "ensure_settings_unique_constraint"):
                try:
                    fn = self.ensure_settings_unique_constraint
                    sig = inspect.signature(fn)
                    if "conn" in sig.parameters:
                        await fn(conn=c)
                    else:
                        await fn()
                    logger.info("✅ UNIQUE settings.key")
                except Exception as e:
                    logger.warning(f"⚠️ UNIQUE settings: {e}")

        if conn is not None:
            await _do_all(conn)
        else:
            async with self.connection() as c:
                await _do_all(c)

    async def _add_column_safe(
        self, conn, table, col_name, col_def
    ):
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table) or \
           not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", col_name):
            return
        if not _validate_column_def(col_name, col_def):
            logger.error(
                f"❌ _add_column_safe: col_def غير صالح لـ "
                f"{table}.{col_name}: {col_def}"
            )
            return
        if USE_MYSQL and "TEXT DEFAULT" in col_def.upper():
            col_def = re.sub(
                r"\bTEXT\s+DEFAULT\b", "VARCHAR(255) DEFAULT",
                col_def, flags=re.IGNORECASE,
            )
        try:
            if USE_POSTGRES:
                exists = await conn.fetchval(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = $1 AND column_name = $2 "
                    "AND table_schema = current_schema()",
                    table, col_name,
                )
                if not exists:
                    await conn.execute(
                        f'ALTER TABLE "{table}" '
                        f'ADD COLUMN "{col_name}" {col_def}'
                    )
                    if table == "group_security":
                        self._group_security_columns_cache = None
            elif USE_MYSQL:
                cursor = await conn.cursor()
                try:
                    await cursor.execute(
                        f"SHOW COLUMNS FROM `{table}` LIKE %s",
                        (col_name,),
                    )
                    exists = await cursor.fetchone()
                finally:
                    await cursor.close()
                if not exists:
                    await conn.execute(
                        f"ALTER TABLE `{table}` "
                        f"ADD COLUMN `{col_name}` {col_def}"
                    )
                    if table == "group_security":
                        self._group_security_columns_cache = None
            else:
                cursor = await conn.execute(
                    f"PRAGMA table_info({table})"
                )
                try:
                    rows = await cursor.fetchall()
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
                exists = any(row[1] == col_name for row in rows)
                if not exists:
                    await conn.execute(
                        f"ALTER TABLE {table} "
                        f"ADD COLUMN {col_name} {col_def}"
                    )
                    if table == "group_security":
                        self._group_security_columns_cache = None
        except Exception as e:
            err = str(e).lower()
            if "already exists" not in err and "duplicate" not in err:
                logger.warning(f"⚠️ {col_name} في {table}: {e}")

    async def _execute_batch_migrations(
        self, conn, table, missing_columns
    ) -> int:
        if not missing_columns:
            return 0
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table):
            return 0
        for col_name, col_def in missing_columns:
            if not _validate_column_def(col_name, col_def):
                return 0
        try:
            if USE_POSTGRES:
                alters = ", ".join([
                    f'ADD COLUMN IF NOT EXISTS "{c}" {t}'
                    for c, t in missing_columns
                ])
                await conn.execute(
                    f'ALTER TABLE "{table}" {alters}'
                )
                return len(missing_columns)
            elif USE_MYSQL:
                safe_cols = []
                for c, t in missing_columns:
                    if "TEXT DEFAULT" in t.upper():
                        t = re.sub(
                            r"\bTEXT\s+DEFAULT\b",
                            "VARCHAR(255) DEFAULT",
                            t, flags=re.IGNORECASE,
                        )
                    safe_cols.append((c, t))
                alters = ", ".join([
                    f"ADD COLUMN `{c}` {t}" for c, t in safe_cols
                ])
                await conn.execute(
                    f"ALTER TABLE `{table}` {alters}"
                )
                return len(safe_cols)
            else:
                added = 0
                for col_name, col_def in missing_columns:
                    try:
                        await conn.execute(
                            f"ALTER TABLE {table} "
                            f"ADD COLUMN {col_name} {col_def}"
                        )
                        added += 1
                    except Exception as e:
                        err = str(e).lower()
                        if "duplicate" in err or "already exists" in err:
                            continue
                return added
        except Exception as e:
            logger.warning(f"⚠️ batch ALTER {table}: {e}")
            added = 0
            for col_name, col_def in missing_columns:
                if not _validate_column_def(col_name, col_def):
                    continue
                try:
                    if USE_POSTGRES:
                        await conn.execute(
                            f'ALTER TABLE "{table}" '
                            f'ADD COLUMN IF NOT EXISTS '
                            f'"{col_name}" {col_def}'
                        )
                    elif USE_MYSQL:
                        safe_def = col_def
                        if "TEXT DEFAULT" in safe_def.upper():
                            safe_def = re.sub(
                                r"\bTEXT\s+DEFAULT\b",
                                "VARCHAR(255) DEFAULT",
                                safe_def, flags=re.IGNORECASE,
                            )
                        await conn.execute(
                            f"ALTER TABLE `{table}` "
                            f"ADD COLUMN `{col_name}` {safe_def}"
                        )
                    else:
                        await conn.execute(
                            f"ALTER TABLE {table} "
                            f"ADD COLUMN {col_name} {col_def}"
                        )
                    added += 1
                except Exception:
                    pass
            return added

    async def _column_exists(self, conn, table, column) -> bool:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table) or \
           not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", column):
            return False
        try:
            if USE_POSTGRES:
                row = await conn.fetchval(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = $1 AND column_name = $2 "
                    "AND table_schema = current_schema()",
                    table, column,
                )
                return row is not None
            elif USE_MYSQL:
                cursor = await conn.cursor()
                try:
                    await cursor.execute(
                        f"SHOW COLUMNS FROM `{table}` LIKE %s",
                        (column,),
                    )
                    row = await cursor.fetchone()
                    return row is not None
                finally:
                    await cursor.close()
            else:
                cursor = await conn.execute(
                    f"PRAGMA table_info({table})"
                )
                try:
                    rows = await cursor.fetchall()
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
                return any(row[1] == column for row in rows)
        except Exception:
            return False

    async def _ensure_text_hash_column(self, conn) -> bool:
        try:
            if not await _table_exists(conn, "posts"):
                return False
            column_exists = await self._column_exists(
                conn, "posts", "text_hash"
            )
            if not column_exists:
                try:
                    if USE_POSTGRES:
                        await conn.execute(
                            "ALTER TABLE posts ADD COLUMN "
                            "text_hash TEXT DEFAULT ''"
                        )
                    elif USE_MYSQL:
                        await conn.execute(
                            "ALTER TABLE posts ADD COLUMN "
                            "text_hash CHAR(64) DEFAULT ''"
                        )
                    else:
                        await conn.execute(
                            "ALTER TABLE posts ADD COLUMN "
                            "text_hash TEXT DEFAULT ''"
                        )
                except Exception:
                    return False
            if not await self._index_exists(
                conn, "posts", "idx_posts_text_hash"
            ):
                try:
                    await conn.execute(
                        "CREATE INDEX idx_posts_text_hash "
                        "ON posts(text_hash)"
                    )
                except Exception as e:
                    err = str(e).lower()
                    if "duplicate" not in err and \
                       "already exists" not in err:
                        logger.warning(f"⚠️ idx text_hash: {e}")
            return True
        except Exception as e:
            logger.error(f"❌ _ensure_text_hash_column: {e}")
            return False

    async def _ensure_bigint_ids(self, conn) -> int:
        if DB_TYPE == "sqlite":
            return 0

        converted = 0
        for table, col in self.BIGINT_COLUMNS:
            try:
                if USE_POSTGRES:
                    row = await conn.fetchval(
                        "SELECT data_type "
                        "FROM information_schema.columns "
                        "WHERE table_name = $1 "
                        "  AND column_name = $2 "
                        "  AND table_schema = current_schema()",
                        table, col,
                    )
                    if row is None:
                        continue
                    row_l = row.lower()
                    if row_l == "bigint":
                        continue
                    if row_l in ("integer", "int", "smallint", "smallserial"):
                        await conn.execute(
                            f'ALTER TABLE "{table}" '
                            f'ALTER COLUMN "{col}" TYPE BIGINT'
                        )
                        logger.info(
                            f"🔧 تحويل {table}.{col}: "
                            f"{row} → BIGINT"
                        )
                        converted += 1
                elif USE_MYSQL:
                    cursor = await conn.cursor()
                    try:
                        await cursor.execute(
                            "SELECT DATA_TYPE "
                            "FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = DATABASE() "
                            "  AND TABLE_NAME = %s "
                            "  AND COLUMN_NAME = %s",
                            (table, col),
                        )
                        r = await cursor.fetchone()
                        if not r:
                            continue
                        current_type = r[0].lower()
                        if current_type == "bigint":
                            continue
                        if current_type in (
                            "int", "integer", "mediumint",
                            "smallint", "tinyint",
                        ):
                            await cursor.execute(
                                f"ALTER TABLE `{table}` "
                                f"MODIFY COLUMN `{col}` "
                                f"BIGINT DEFAULT NULL"
                            )
                            logger.info(
                                f"🔧 تحويل {table}.{col}: "
                                f"{current_type} → BIGINT"
                            )
                            converted += 1
                    finally:
                        await cursor.close()
            except Exception as e:
                logger.warning(
                    f"⚠️ _ensure_bigint_ids({table}.{col}): {e}"
                )

        if converted > 0:
            logger.info(
                f"✅ تحويل {converted} عمود إلى BIGINT"
            )
        return converted

    async def _migrate_schema(self, conn):
        if USE_MYSQL:
            try:
                await conn.execute("SET SESSION FOREIGN_KEY_CHECKS=0")
            except Exception:
                pass
        try:
            migrations = {
                "group_security": [
                    ("antiflood_penalty_duration",
                     "INTEGER DEFAULT 3600"),
                    ("night_mode_action_duration",
                     "INTEGER DEFAULT 3600"),
                    ("warn_penalty_duration",
                     "INTEGER DEFAULT 3600"),
                    ("mute_default_duration",
                     "INTEGER DEFAULT 3600"),
                    ("ban_default_duration", "INTEGER DEFAULT 0"),
                    ("warn_default_duration", "INTEGER DEFAULT 0"),
                    ("restrict_default_duration",
                     "INTEGER DEFAULT 1800"),
                    ("enable_timed_penalties",
                     "INTEGER DEFAULT 1"),
                    ("auto_remove_penalties",
                     "INTEGER DEFAULT 1"),
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
                    ("delete_penalty_duration",
                     "INTEGER DEFAULT 3600"),
                    ("delete_penalty_messages",
                     "INTEGER DEFAULT 0"),
                    ("violation_penalty_duration",
                     "INTEGER DEFAULT 3600"),
                    ("violation_penalty",
                     "TEXT DEFAULT 'none'"),
                ],
                "users": [
                    ("active_channel", "INTEGER DEFAULT NULL")
                ],
                "bot_groups": [
                    ("log_channel_id", "BIGINT DEFAULT NULL"),
                ],
                "auto_replies": [
                    ("usage_count", "INTEGER DEFAULT 0")
                ],
                "anonymous_admins": [("user_id", "BIGINT")],
                "posts": [
                    ("text_hash", "TEXT DEFAULT ''"),
                    ("published_at", "TIMESTAMP"),
                    ("fail_count", "INTEGER DEFAULT 0"),
                ],
                "user_reminder_settings": [
                    ("subscription_reminder",
                     "INTEGER DEFAULT 1"),
                    ("daily_stats_reminder",
                     "INTEGER DEFAULT 0"),
                    ("weekly_report", "INTEGER DEFAULT 1"),
                    ("reminder_days_before",
                     "INTEGER DEFAULT 3"),
                    ("last_daily_sent", "TIMESTAMP"),
                    ("last_weekly_sent", "TIMESTAMP"),
                    ("last_subscription_sent", "TIMESTAMP"),
                    ("last_reminder_sent", "TIMESTAMP"),
                    ("notification_lang", "TEXT DEFAULT 'ar'"),
                ],
                "user_translation": [
                    ("lang", "TEXT DEFAULT 'off'")
                ],
            }

            t_fetch = time.monotonic()
            all_columns = await self._fetch_all_columns_map(
                conn, list(migrations.keys())
            )
            fetch_elapsed = time.monotonic() - t_fetch

            total_added = 0
            tables_processed = 0
            for table, columns in migrations.items():
                try:
                    existing = all_columns.get(table, set())
                    missing = [
                        (col, typ) for col, typ in columns
                        if col not in existing
                    ]
                    if not missing:
                        continue
                    added = await self._execute_batch_migrations(
                        conn, table, missing
                    )
                    total_added += added
                    tables_processed += 1
                except Exception as e:
                    logger.warning(f"⚠️ {table}: {e}")

            if total_added > 0:
                logger.info(
                    f"⚡ الترحيل: +{total_added} عمود "
                    f"في {tables_processed} جدول "
                    f"(fetch={fetch_elapsed:.2f}s)"
                )

            await self._ensure_text_hash_column(conn)
            await self._ensure_bigint_ids(conn)

            self._group_security_columns_cache = None
            _UNIQUE_CACHE.clear()
        finally:
            if USE_MYSQL:
                try:
                    await conn.execute(
                        "SET SESSION FOREIGN_KEY_CHECKS=1"
                    )
                except Exception:
                    pass

    async def _get_existing_columns(self, conn, table) -> set:
        try:
            if USE_POSTGRES:
                rows = await conn.fetch(
                    "SELECT column_name "
                    "FROM information_schema.columns "
                    "WHERE table_name = $1 "
                    "AND table_schema = current_schema()",
                    table,
                )
                return {row["column_name"] for row in rows}
            elif USE_MYSQL:
                if not await _table_exists(conn, table):
                    return set()
                cursor = await conn.cursor()
                try:
                    await cursor.execute(
                        f"SHOW COLUMNS FROM `{table}`"
                    )
                    rows = await cursor.fetchall()
                    return {row[0] for row in rows}
                finally:
                    await cursor.close()
            else:
                cursor = await conn.execute(
                    f"PRAGMA table_info({table})"
                )
                try:
                    rows = await cursor.fetchall()
                    return {row[1] for row in rows}
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
        except Exception:
            return set()

    async def _index_exists(self, conn, table, idx_name) -> bool:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table) or \
           not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", idx_name):
            return False
        try:
            if USE_POSTGRES:
                row = await conn.fetchval(
                    "SELECT 1 FROM pg_indexes "
                    "WHERE indexname = $1 "
                    "AND schemaname = current_schema()",
                    idx_name,
                )
                return row is not None
            elif USE_MYSQL:
                if not await _table_exists(conn, table):
                    return False
                cursor = await conn.cursor()
                try:
                    await cursor.execute(
                        "SELECT 1 FROM information_schema.STATISTICS "
                        "WHERE table_schema = DATABASE() "
                        "AND table_name = %s AND index_name = %s",
                        (table, idx_name),
                    )
                    row = await cursor.fetchone()
                    return row is not None
                finally:
                    await cursor.close()
            else:
                cursor = await conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='index' AND name=?",
                    (idx_name,),
                )
                try:
                    row = await cursor.fetchone()
                    return row is not None
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
        except Exception:
            return False

    async def _create_secondary_indexes(self, indexes):
        if not indexes:
            return
        try:
            async with self.connection() as conn:
                created = skipped = failed = 0
                for table, idx_name, create_sql in indexes:
                    try:
                        if await self._index_exists(
                            conn, table, idx_name
                        ):
                            skipped += 1
                            continue
                        await conn.execute(create_sql)
                        created += 1
                    except Exception as e:
                        msg = str(e).lower()
                        if "duplicate" in msg or \
                           "already exists" in msg:
                            skipped += 1
                        else:
                            failed += 1
                logger.info(
                    f"📊 فهارس: ✅{created} ⏭️{skipped} ❌{failed}"
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"❌ فهارس: {e}")

    # =================================================================
    # ضمان المستخدم/المجموعة
    # =================================================================

    async def _ensure_user_exists(
        self,
        user_id: int,
        username: str = "",
        first_name: str = "",
        auto_register: bool = True,
    ) -> bool:
        try:
            exists = await self.fetchval(
                "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
            )
            if exists:
                return True
            if not auto_register:
                logger.warning(f"⚠️ المستخدم {user_id} غير موجود")
                return False
            logger.info(f"ℹ️ تسجيل تلقائي {user_id}")
            return await self.register_user(
                user_id=user_id,
                username=username or "",
                first_name=first_name or "",
                force=True,
            )
        except Exception as e:
            logger.error(f"❌ _ensure_user_exists({user_id}): {e}")
            return False

    async def _ensure_group_exists(
        self,
        chat_id: int,
        chat_name: str = "",
        added_by: Optional[int] = None,
        auto_register: bool = True,
    ) -> bool:
        try:
            exists = await self.fetchval(
                "SELECT 1 FROM bot_groups WHERE chat_id = ?",
                (chat_id,),
            )
            if exists:
                return True
            if not auto_register:
                logger.warning(
                    f"⚠️ المجموعة {chat_id} غير موجودة"
                )
                return False
            now = TimeUtils.utc_now()
            if USE_POSTGRES:
                sql = (
                    "INSERT INTO bot_groups "
                    "(chat_id, chat_name, added_by, added_at, banned) "
                    "VALUES (?, ?, ?, ?, 0) "
                    "ON CONFLICT (chat_id) DO NOTHING"
                )
            elif USE_MYSQL:
                sql = (
                    "INSERT IGNORE INTO bot_groups "
                    "(chat_id, chat_name, added_by, added_at, banned) "
                    "VALUES (?, ?, ?, ?, 0)"
                )
            else:
                sql = (
                    "INSERT OR IGNORE INTO bot_groups "
                    "(chat_id, chat_name, added_by, added_at, banned) "
                    "VALUES (?, ?, ?, ?, 0)"
                )
            await self.execute(
                sql,
                (chat_id, chat_name or str(chat_id), added_by, now),
            )
            if CACHE_AVAILABLE:
                try:
                    await groups_cache.invalidate(chat_id)
                except Exception:
                    pass
            return True
        except Exception as e:
            logger.error(
                f"❌ _ensure_group_exists({chat_id}): {e}"
            )
            return False

    # =================================================================
    # البيانات الافتراضية
    # =================================================================

    async def _init_default_data(self, conn):
        default_plans = [
            {"name": "تجربة",
             "description": "تجربة مجانية 30 يوم",
             "price": 0, "duration_days": 30,
             "max_channels": 100, "max_posts": 200,
             "features":
                 '{"auto_publish":true,"security":true}',
             "is_gift": 0},
            {"name": "يوم", "description": "باقة يوم",
             "price": 5, "duration_days": 1,
             "max_channels": 1, "max_posts": 50,
             "features": '{"auto_publish":true}', "is_gift": 0},
            {"name": "أسبوع", "description": "باقة 7 أيام",
             "price": 25, "duration_days": 7,
             "max_channels": 3, "max_posts": 300,
             "features":
                 '{"auto_publish":true,"security":true}',
             "is_gift": 0},
            {"name": "شهر", "description": "باقة 30 يوم",
             "price": 75, "duration_days": 30,
             "max_channels": 10, "max_posts": 1500,
             "features":
                 '{"auto_publish":true,"security":true,'
                 '"support":true}',
             "is_gift": 0},
            {"name": "3 أشهر", "description": "باقة 90 يوم",
             "price": 200, "duration_days": 90,
             "max_channels": 25, "max_posts": 5000,
             "features":
                 '{"auto_publish":true,"security":true,'
                 '"support":true,"analytics":true}',
             "is_gift": 0},
            {"name": "سنة", "description": "باقة 365 يوم",
             "price": 700, "duration_days": 365,
             "max_channels": 100, "max_posts": 99999,
             "features":
                 '{"auto_publish":true,"security":true,'
                 '"support":true,"analytics":true,'
                 '"priority":true}',
             "is_gift": 0},
            {"name": "هدية شهر",
             "description": "كود هدية 30 يوم",
             "price": 75, "duration_days": 30,
             "max_channels": 100, "max_posts": 1500,
             "features": '{}', "is_gift": 1},
        ]
        now_dt = TimeUtils.utc_now()

        names = [p["name"] for p in default_plans]
        existing_names: Set[str] = set()
        try:
            if USE_POSTGRES:
                rows = await conn.fetch(
                    "SELECT name FROM plans "
                    "WHERE name = ANY($1::text[])",
                    names,
                )
                existing_names = {r["name"] for r in rows}
            elif USE_MYSQL:
                cursor = await conn.cursor()
                try:
                    placeholders = ",".join(["%s"] * len(names))
                    await cursor.execute(
                        f"SELECT name FROM plans "
                        f"WHERE name IN ({placeholders})",
                        names,
                    )
                    existing_names = {
                        r[0] for r in await cursor.fetchall()
                    }
                finally:
                    await cursor.close()
            else:
                placeholders = ",".join(["?"] * len(names))
                cursor = await conn.execute(
                    f"SELECT name FROM plans "
                    f"WHERE name IN ({placeholders})",
                    names,
                )
                try:
                    existing_names = {
                        r[0] for r in await cursor.fetchall()
                    }
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"⚠️ fetch existing plans: {e}")

        to_insert = [
            p for p in default_plans
            if p["name"] not in existing_names
        ]
        to_update = [
            p for p in default_plans
            if p["name"] in existing_names
        ]

        if to_insert:
            try:
                params_list = [
                    (
                        p["name"], p["description"],
                        p["price"], "XTR",
                        p["duration_days"], p["max_channels"],
                        p["max_posts"], p["features"], 1,
                        p["is_gift"], now_dt,
                    )
                    for p in to_insert
                ]
                await self._executemany_with_conn(
                    conn,
                    """INSERT OR IGNORE INTO plans
                       (name, description, price, currency,
                        duration_days, max_channels, max_posts,
                        features, is_active, is_gift, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    params_list,
                )
                logger.info(f"✅ أُدرج {len(to_insert)} باقة")
            except Exception as e:
                logger.warning(f"⚠️ insert plans batch: {e}")

        if to_update:
            for p in to_update:
                try:
                    await self._execute_with_conn(
                        conn,
                        "UPDATE plans SET max_channels = ?, "
                        "max_posts = ? WHERE name = ?",
                        p["max_channels"], p["max_posts"],
                        p["name"],
                    )
                except Exception:
                    pass

    async def _import_banned_words(self, conn):
        try:
            import banned_words
            BANNED_WORDS = getattr(banned_words, "BANNED_WORDS", [])
            if not BANNED_WORDS:
                return
            words_snapshot = "\n".join(
                str(w).strip().lower()
                for w in BANNED_WORDS
                if 2 <= len(str(w).strip()) <= 100
            )
            current_hash = hashlib.sha256(
                words_snapshot.encode("utf-8")
            ).hexdigest()
            stored_hash = await self._fetchval_with_conn(
                conn, _sql_get_setting_value(), "banned_words_hash"
            )
            if stored_hash == current_hash:
                logger.info("ℹ️ الكلمات المحظورة لم تتغيّر")
                return
            owner_id = getattr(CONFIG, "PRIMARY_OWNER_ID", None)
            if not owner_id:
                exists = await self._fetchval_with_conn(
                    conn,
                    "SELECT 1 FROM users WHERE user_id = ?",
                    1,
                )
                if not exists:
                    logger.warning("⚠️ owner_id=1 غير موجود")
                    return
                owner_id = 1
            ts = TimeUtils.utc_now()
            words_to_insert = []
            for word in BANNED_WORDS:
                word = str(word).strip().lower()
                if 2 <= len(word) <= 100:
                    words_to_insert.append(
                        (word, -1, owner_id, ts)
                    )
            if words_to_insert:
                batch_size = 500
                for i in range(
                    0, len(words_to_insert), batch_size
                ):
                    batch = words_to_insert[
                        i: i + batch_size
                    ]
                    await self._executemany_with_conn(
                        conn,
                        """INSERT OR IGNORE INTO banned_words
                           (word, chat_id, added_by, added_at)
                           VALUES (?, ?, ?, ?)""",
                        batch,
                    )
                logger.info(
                    f"✅ استورد {len(words_to_insert)} كلمة"
                )
                await self._upsert_setting(
                    conn, "banned_words_hash", current_hash
                )
                if CACHE_AVAILABLE:
                    await banned_words_cache.invalidate()
        except ImportError:
            pass
        except Exception as e:
            logger.error(f"❌ banned_words: {e}")

    async def _import_auto_replies(self, conn):
        try:
            from auto_replies import AUTO_REPLIES
            if not AUTO_REPLIES:
                return
            if isinstance(AUTO_REPLIES, dict):
                auto_replies_list = [AUTO_REPLIES]
            elif isinstance(AUTO_REPLIES, (list, tuple)):
                auto_replies_list = AUTO_REPLIES
            else:
                return
            try:
                snapshot = json.dumps(
                    auto_replies_list,
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str,
                )
            except Exception:
                snapshot = str(auto_replies_list)
            current_hash = hashlib.sha256(
                snapshot.encode("utf-8")
            ).hexdigest()
            stored_hash = await self._fetchval_with_conn(
                conn, _sql_get_setting_value(), "auto_replies_hash"
            )
            if stored_hash == current_hash:
                logger.info("ℹ️ الردود التلقائية لم تتغيّر")
                return
            replies_to_insert = []
            for item in auto_replies_list:
                try:
                    if isinstance(item, dict):
                        chat_id = item.get("chat_id", -1)
                        keyword = str(
                            item.get("keyword", "")
                        ).strip().lower()
                        reply = item.get("reply", "")
                        reply_type = item.get(
                            "reply_type", "text"
                        )
                        media_id = item.get("reply_media_id")
                        buttons = item.get("reply_buttons")
                    elif isinstance(item, (list, tuple)):
                        if len(item) == 2 and isinstance(
                            item[0], str
                        ):
                            chat_id = -1
                            keyword = str(item[0]).strip().lower()
                            reply = item[1]
                            reply_type = "text"
                            media_id = None
                            buttons = None
                        elif len(item) >= 3 and isinstance(
                            item[0], int
                        ):
                            chat_id = item[0]
                            keyword = str(item[1]).strip().lower()
                            reply = item[2]
                            reply_type = (
                                item[3]
                                if len(item) > 3
                                and isinstance(item[3], str)
                                else "text"
                            )
                            media_id = (
                                item[4] if len(item) > 4 else None
                            )
                            buttons = (
                                item[5] if len(item) > 5 else None
                            )
                        else:
                            continue
                    else:
                        continue
                    if not keyword or \
                       reply_type not in self.VALID_REPLY_TYPES:
                        continue
                    replies_to_insert.append((
                        chat_id, keyword, reply, reply_type,
                        media_id, buttons,
                        TimeUtils.utc_now(), 1, 0,
                    ))
                except Exception:
                    continue
            if replies_to_insert:
                batch_size = 100
                for i in range(
                    0, len(replies_to_insert), batch_size
                ):
                    batch = replies_to_insert[
                        i: i + batch_size
                    ]
                    await self._executemany_with_conn(
                        conn,
                        """INSERT OR IGNORE INTO auto_replies
                           (chat_id, keyword, reply, reply_type,
                            reply_media_id, reply_buttons,
                            created_at, is_active, usage_count)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        batch,
                    )
                logger.info(
                    f"✅ استورد {len(replies_to_insert)} رد"
                )
                await self._upsert_setting(
                    conn, "auto_replies_hash", current_hash
                )
        except ImportError:
            pass
        except Exception as e:
            logger.error(f"❌ auto_replies: {e}")

    def _get_secondary_indexes(self) -> List[Tuple[str, str, str]]:
        return []

    def _compute_bootstrap_hash(self) -> str:
        data = {
            "schema": CURRENT_SCHEMA_VERSION,
            "bootstrap_data": self.BOOTSTRAP_DATA_VERSION,
        }
        return hashlib.sha256(
            json.dumps(data, sort_keys=True).encode("utf-8")
        ).hexdigest()

    # ✅ v7.7.13: استعادة الدالة المحذوفة سهواً — عقد Mixin Contract
    def _compute_text_hash(self, text: str) -> str:
        """
        🔐 يحسب SHA-256 hash للنص — يُستخدم لمنع تكرار المنشورات.

        يُستدعى من ChannelsPostsMixin.add_posts (database_channels_posts.py).
        يُخزَّن الناتج في posts.text_hash (CHAR(64) في MySQL).

        ⚠️ ملاحظة مهمة: لا تضف normalization (lower/strip) هنا —
        لأن add_posts يستدعيها بالنص بعد القصّ فقط، وأي تغيير
        سيسبب تكرارات وهمية للمنشورات القديمة المخزّنة مسبقاً.
        """
        if not text:
            return ""
        return hashlib.sha256(
            str(text).encode("utf-8")
        ).hexdigest()

    def _compute_tables_hash(self) -> str:
        return hashlib.sha256(
            f"tables_v{CURRENT_SCHEMA_VERSION}".encode("utf-8")
        ).hexdigest()

    async def _upsert_setting(
        self, conn, key: str, value: str
    ) -> None:
        try:
            if USE_POSTGRES:
                await conn.execute(
                    "INSERT INTO settings (key, value) "
                    "VALUES ($1, $2) "
                    "ON CONFLICT (key) DO UPDATE SET "
                    "value = EXCLUDED.value",
                    key, value,
                )
            elif USE_MYSQL:
                cursor = await conn.cursor()
                try:
                    await cursor.execute(
                        "INSERT INTO settings (`key`, `value`) "
                        "VALUES (%s, %s) "
                        "ON DUPLICATE KEY UPDATE "
                        "`value` = VALUES(`value`)",
                        (key, value),
                    )
                finally:
                    await cursor.close()
            else:
                await conn.execute(
                    "INSERT INTO settings (key, value) "
                    "VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET "
                    "value = excluded.value",
                    (key, value),
                )
        except Exception as e:
            logger.warning(f"⚠️ _upsert_setting({key}): {e}")

    async def _fetch_all_columns_map(
        self, conn, tables: List[str]
    ) -> Dict[str, Set[str]]:
        result: Dict[str, Set[str]] = {t: set() for t in tables}
        if not tables:
            return result

        try:
            if USE_POSTGRES:
                rows = await conn.fetch(
                    "SELECT table_name, column_name "
                    "FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "  AND table_name = ANY($1::text[])",
                    tables,
                )
                for r in rows:
                    result.setdefault(r["table_name"], set()).add(
                        r["column_name"]
                    )
            elif USE_MYSQL:
                cursor = await conn.cursor()
                try:
                    placeholders = ",".join(["%s"] * len(tables))
                    await cursor.execute(
                        f"SELECT TABLE_NAME, COLUMN_NAME "
                        f"FROM information_schema.COLUMNS "
                        f"WHERE TABLE_SCHEMA = DATABASE() "
                        f"  AND TABLE_NAME IN ({placeholders})",
                        tables,
                    )
                    for r in await cursor.fetchall():
                        result.setdefault(r[0], set()).add(r[1])
                finally:
                    await cursor.close()
            else:
                for table in tables:
                    if not re.match(
                        r"^[a-zA-Z_][a-zA-Z0-9_]*$", table
                    ):
                        continue
                    cur = await conn.execute(
                        f"PRAGMA table_info({table})"
                    )
                    try:
                        rows = await cur.fetchall()
                        result[table] = {r[1] for r in rows}
                    finally:
                        try:
                            await cur.close()
                        except Exception:
                            pass
        except Exception as e:
            logger.warning(f"⚠️ _fetch_all_columns_map: {e}")

        return result

    async def has_active_subscription(self, user_id: int) -> bool:
        cache_key = f"has_active_sub_{user_id}"
        cached = await internal_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            result = await super().has_active_subscription(user_id)
        except AttributeError:
            row = await self.fetchval(
                "SELECT 1 FROM subscriptions "
                "WHERE user_id = ? AND status = 'active' "
                "AND end_date > ? LIMIT 1",
                (user_id, TimeUtils.utc_now()),
            )
            result = row is not None
        await internal_cache.set(cache_key, result, ttl=60)
        return result

    async def invalidate_subscription_cache(self, user_id: int):
        for key in (
            f"has_active_sub_{user_id}",
            f"has_active_subscription_{user_id}",
            f"subscription_active_{user_id}",
            f"subscription_{user_id}",
            f"start_data_{user_id}",
        ):
            try:
                await internal_cache.invalidate(key)
            except Exception:
                pass
        if CACHE_AVAILABLE:
            try:
                await invalidate_user_cache(user_id)
            except Exception:
                pass

    # =================================================================
    # Bootstrap
    # =================================================================

    async def _do_bootstrap_inner(self, conn) -> bool:
        tables_hash = self._compute_tables_hash()
        stored_tables_hash = await self._fetchval_with_conn(
            conn,
            _sql_get_setting_value(),
            "tables_hash",
        )

        if stored_tables_hash != tables_hash:
            t_tables = time.monotonic()
            await self._create_tables(conn=conn)
            await self._upsert_setting(
                conn, "tables_hash", tables_hash
            )
            logger.info(
                f"✅ create_tables في "
                f"{time.monotonic() - t_tables:.2f}s"
            )
        else:
            logger.info("⏩ الجداول موجودة — تخطي create_tables")

        current_hash = self._compute_bootstrap_hash()
        stored_hash = await self._fetchval_with_conn(
            conn,
            _sql_get_setting_value(),
            "bootstrap_hash",
        )

        if stored_hash == current_hash:
            logger.info("⏩ bootstrap محدّث — تخطي migrate")
        else:
            t_mig = time.monotonic()
            await self._migrate_schema(conn)
            await self._init_default_data(conn)
            elapsed = time.monotonic() - t_mig
            await self._upsert_setting(
                conn, "bootstrap_hash", current_hash
            )
            logger.info(f"✅ ترحيل في {elapsed:.2f}s")

        await self._import_banned_words(conn)
        await self._import_auto_replies(conn)
        return True

    async def _bootstrap(
        self, *, with_background: bool = True
    ) -> bool:
        async with self._bootstrap_lock:
            try:
                await self.initialize()

                if USE_POSTGRES or USE_MYSQL:
                    async with self.connection() as conn:
                        await self._do_bootstrap_inner(conn)
                else:
                    async with self.transaction() as conn:
                        await self._do_bootstrap_inner(conn)

                if with_background:
                    if CACHE_AVAILABLE and (
                        self._cache_cleanup_task is None
                        or self._cache_cleanup_task.done()
                    ):
                        self._cache_cleanup_task = (
                            asyncio.create_task(
                                cache_cleanup_task()
                            )
                        )
                return True
            except Exception as e:
                logger.error(
                    f"❌ فشل التهيئة: {e}", exc_info=True
                )
                return False

    async def initialize_db(self) -> bool:
        result = await self._bootstrap(with_background=True)
        if result:
            logger.info("✅ تم تهيئة DB")
        return result

    pre_initialize = initialize_db

    # =================================================================
    # المستخدمون
    # =================================================================

    async def get_start_data(self, user_id: int) -> Optional[Dict]:
        cache_key = f"start_data_{user_id}"
        cached = await internal_cache.get(cache_key)
        if cached is not None:
            return _clone_start_data(cached)
        try:
            row = await self.fetchone(
                """
                SELECT u.user_id, u.username, u.first_name, u.language,
                       u.auto_publish, u.auto_recycle, u.banned,
                       u.trial_used, u.active_channel,
                       (SELECT 1 FROM subscriptions s
                        WHERE s.user_id = u.user_id
                          AND s.status = 'active'
                          AND s.end_date > ?
                        LIMIT 1) AS has_sub,
                       (SELECT COUNT(*) FROM user_channels uc
                        WHERE uc.user_id = u.user_id
                          AND uc.banned = 0
                       ) AS channels_count,
                       (SELECT COUNT(*) FROM user_groups_link g
                        WHERE g.user_id = u.user_id
                       ) AS groups_count,
                       (SELECT COUNT(*) FROM posts p
                        WHERE p.channel_db_id =
                              COALESCE(u.active_channel, -1)
                          AND p.published = 0
                       ) AS unpublished_posts,
                       (SELECT COUNT(*) FROM posts p
                        JOIN user_channels uc2
                          ON p.channel_db_id = uc2.id
                        WHERE uc2.user_id = u.user_id
                          AND p.published = 0
                       ) AS total_unpublished_posts
                FROM users u
                WHERE u.user_id = ?
                """,
                (TimeUtils.utc_now(), user_id),
            )
        except Exception as e:
            logger.error(f"❌ get_start_data: {e}", exc_info=True)
            return None
        if not row:
            return None
        data = dict(row)
        data["has_subscription"] = (
            data.pop("has_sub", None) is not None
        )
        data["channels_count"] = data.get("channels_count") or 0
        data["groups_count"] = data.get("groups_count") or 0
        data["unpublished_posts"] = (
            data.get("unpublished_posts") or 0
        )
        data["total_unpublished_posts"] = (
            data.get("total_unpublished_posts") or 0
        )
        if data.get("active_channel"):
            try:
                ch = await self.fetchone(
                    "SELECT id, channel_name, channel_id "
                    "FROM user_channels "
                    "WHERE id = ? AND banned = 0",
                    (data["active_channel"],),
                )
                if ch:
                    data["channel_info"] = {
                        "id": ch.get("id"),
                        "channel_name": ch.get("channel_name"),
                        "channel_id": ch.get("channel_id"),
                    }
                    data["channel_name"] = ch.get("channel_name")
                    data["channel_id"] = ch.get("channel_id")
                else:
                    data["channel_info"] = None
            except Exception:
                data["channel_info"] = None
        else:
            data["channel_info"] = None
        await internal_cache.set(
            cache_key, _clone_start_data(data), ttl=60
        )
        return data

    async def get_user_full_data(
        self, user_id: int, include_stats: bool = True
    ) -> Optional[Dict]:
        try:
            if include_stats:
                row = await self.fetchone(
                    """
                    SELECT u.user_id, u.username, u.first_name,
                           u.language, u.auto_publish, u.auto_recycle,
                           u.banned, u.trial_used, u.subscription_end,
                           u.active_channel,
                           (SELECT 1 FROM subscriptions s
                            WHERE s.user_id = u.user_id
                              AND s.status = 'active'
                              AND s.end_date > ?
                            LIMIT 1) AS has_sub,
                           (SELECT COUNT(*) FROM user_channels uc
                            WHERE uc.user_id = u.user_id
                              AND uc.banned = 0
                           ) AS channels_count,
                           (SELECT COUNT(*) FROM user_groups_link g
                            WHERE g.user_id = u.user_id
                           ) AS groups_count,
                           (SELECT COUNT(*) FROM posts p
                            WHERE p.channel_db_id =
                                  COALESCE(u.active_channel, -1)
                              AND p.published = 0
                           ) AS unpublished_posts,
                           (SELECT COUNT(*) FROM posts p
                            JOIN user_channels uc2
                              ON p.channel_db_id = uc2.id
                            WHERE uc2.user_id = u.user_id
                              AND p.published = 0
                           ) AS total_unpublished_posts
                    FROM users u
                    WHERE u.user_id = ?
                    """,
                    (TimeUtils.utc_now(), user_id),
                )
            else:
                row = await self.fetchone(
                    "SELECT user_id, username, first_name, language, "
                    "auto_publish, auto_recycle, banned, trial_used, "
                    "subscription_end, active_channel "
                    "FROM users WHERE user_id = ?",
                    (user_id,),
                )
        except Exception as e:
            logger.error(f"❌ get_user_full_data: {e}")
            return None
        if not row:
            return None
        result = dict(row)
        if include_stats:
            result["has_subscription"] = (
                result.pop("has_sub", None) is not None
            )
            result["channels_count"] = (
                result.get("channels_count") or 0
            )
            result["groups_count"] = (
                result.get("groups_count") or 0
            )
            result["unpublished_posts"] = (
                result.get("unpublished_posts") or 0
            )
            result["total_unpublished_posts"] = (
                result.get("total_unpublished_posts") or 0
            )
        else:
            result["has_subscription"] = False
            result["unpublished_posts"] = 0
            result["total_unpublished_posts"] = 0
            result["channels_count"] = 0
            result["groups_count"] = 0
        if result.get("active_channel"):
            try:
                ch = await self.fetchone(
                    "SELECT id, channel_name, channel_id, banned "
                    "FROM user_channels WHERE id = ?",
                    (result["active_channel"],),
                )
                if ch and not ch.get("banned", 0):
                    result["channel_id"] = ch.get("id")
                    result["channel_name"] = ch.get("channel_name")
                    result["channel_banned"] = 0
                    result["channel_info"] = {
                        "id": ch.get("id"),
                        "channel_name": ch.get("channel_name"),
                        "banned": 0,
                    }
                else:
                    result["channel_info"] = None
            except Exception:
                result["channel_info"] = None
        else:
            result["channel_info"] = None
        return result

    async def get_user(
        self, user_id: int, include_stats: bool = False
    ) -> Optional[Dict]:
        try:
            if CACHE_AVAILABLE:
                cached_data = await user_cache.get(user_id)
                if cached_data:
                    user_data = cached_data.get("user_data")
                    if user_data:
                        user_data = _clone_start_data(user_data)
                        if include_stats:
                            user_data["unpublished_posts"] = (
                                cached_data.get(
                                    "unpublished_posts", 0
                                )
                            )
                            user_data["total_unpublished_posts"] = (
                                cached_data.get(
                                    "total_unpublished_posts", 0
                                )
                            )
                            user_data["has_subscription"] = (
                                cached_data.get(
                                    "has_subscription", False
                                )
                            )
                            user_data["channels_count"] = (
                                cached_data.get("channels_count", 0)
                            )
                            user_data["groups_count"] = (
                                cached_data.get("groups_count", 0)
                            )
                        return user_data
            cached = await internal_cache.get(
                f"user_{user_id}_{include_stats}"
            )
            if cached:
                return _clone_start_data(cached)
            if include_stats:
                row = await self.fetchone(
                    """
                    SELECT u.user_id, u.username, u.first_name,
                           u.language, u.auto_publish, u.auto_recycle,
                           u.banned, u.trial_used, u.subscription_end,
                           u.active_channel,
                           (SELECT 1 FROM subscriptions s
                            WHERE s.user_id = u.user_id
                              AND s.status = 'active'
                              AND s.end_date > ?
                            LIMIT 1) AS has_sub,
                           (SELECT COUNT(*) FROM user_channels uc
                            WHERE uc.user_id = u.user_id
                              AND uc.banned = 0
                           ) AS channels_count,
                           (SELECT COUNT(*) FROM user_groups_link g
                            WHERE g.user_id = u.user_id
                           ) AS groups_count,
                           (SELECT COUNT(*) FROM posts p
                            WHERE p.channel_db_id =
                                  COALESCE(u.active_channel, -1)
                              AND p.published = 0
                           ) AS unpublished_posts,
                           (SELECT COUNT(*) FROM posts p
                            JOIN user_channels uc2
                              ON p.channel_db_id = uc2.id
                            WHERE uc2.user_id = u.user_id
                              AND p.published = 0
                           ) AS total_unpublished_posts
                    FROM users u
                    WHERE u.user_id = ?
                    """,
                    (TimeUtils.utc_now(), user_id),
                )
            else:
                row = await self.fetchone(
                    "SELECT user_id, username, first_name, language, "
                    "auto_publish, auto_recycle, banned, trial_used, "
                    "subscription_end, active_channel "
                    "FROM users WHERE user_id = ?",
                    (user_id,),
                )
            if not row:
                return None
            data = dict(row)
            if include_stats:
                data["has_subscription"] = (
                    data.pop("has_sub", None) is not None
                )
                data["channels_count"] = (
                    data.get("channels_count") or 0
                )
                data["groups_count"] = (
                    data.get("groups_count") or 0
                )
                data["unpublished_posts"] = (
                    data.get("unpublished_posts") or 0
                )
                data["total_unpublished_posts"] = (
                    data.get("total_unpublished_posts") or 0
                )
            else:
                data["has_subscription"] = False
                data["channels_count"] = 0
                data["groups_count"] = 0
                data["unpublished_posts"] = 0
                data["total_unpublished_posts"] = 0
            if data.get("active_channel"):
                try:
                    ch = await self.fetchone(
                        "SELECT id, channel_name, channel_id, banned "
                        "FROM user_channels WHERE id = ?",
                        (data["active_channel"],),
                    )
                    if ch and not ch.get("banned", 0):
                        data["channel_id"] = ch.get("id")
                        data["channel_name"] = ch.get("channel_name")
                        data["channel_banned"] = 0
                    else:
                        data["channel_id"] = None
                        data["channel_name"] = None
                        data["channel_banned"] = 0
                except Exception:
                    data["channel_id"] = None
                    data["channel_name"] = None
                    data["channel_banned"] = 0
            else:
                data["channel_id"] = None
                data["channel_name"] = None
                data["channel_banned"] = 0
            await internal_cache.set(
                f"user_{user_id}_{include_stats}",
                _clone_start_data(data),
                ttl=60,
            )
            if CACHE_AVAILABLE and include_stats:
                full_data = {
                    "user_data": _clone_start_data(data),
                    "language": data.get("language", "ar"),
                    "active_channel": data.get("active_channel"),
                    "channel_info": (
                        {
                            "id": data.get("channel_id"),
                            "channel_name": data.get("channel_name"),
                            "banned": data.get(
                                "channel_banned", 0
                            ),
                        } if data.get("channel_id") else None
                    ),
                    "unpublished_posts": data.get(
                        "unpublished_posts", 0
                    ),
                    "total_unpublished_posts": data.get(
                        "total_unpublished_posts", 0
                    ),
                    "has_subscription": data.get(
                        "has_subscription", False
                    ),
                    "auto_publish": data.get("auto_publish", True),
                    "auto_recycle": data.get("auto_recycle", True),
                    "groups_count": data.get("groups_count", 0),
                    "channels_count": data.get("channels_count", 0),
                }
                await user_cache.set(user_id, full_data)
            return data
        except Exception as e:
            logger.error(f"❌ get_user: {e}", exc_info=True)
            return None

    async def _invalidate_user_cache_keys(self, user_id: int) -> None:
        for k in (
            f"user_{user_id}",
            f"user_{user_id}_True",
            f"user_{user_id}_False",
            f"lang_{user_id}",
            f"start_data_{user_id}",
            f"user_settings_batch_{user_id}",
            f"auto_publish_{user_id}",
            f"auto_recycle_{user_id}",
        ):
            await internal_cache.invalidate(k)
        if CACHE_AVAILABLE:
            try:
                await invalidate_user_cache(user_id)
            except Exception:
                pass

    async def register_user(
        self,
        user_id: int,
        username: str = "",
        first_name: str = "",
        force: bool = False,
    ) -> bool:
        try:
            async with await self._get_user_lock(user_id):
                if not force:
                    exists = await self.fetchval(
                        "SELECT 1 FROM users WHERE user_id = ?",
                        (user_id,),
                    )
                    if exists:
                        cur = await self.fetchone(
                            "SELECT username, first_name "
                            "FROM users WHERE user_id = ?",
                            (user_id,),
                        )
                        cur_username = (
                            (cur or {}).get("username") or ""
                        )
                        cur_first = (
                            (cur or {}).get("first_name") or ""
                        )
                        need_update = False
                        if username and username != cur_username:
                            need_update = True
                        if first_name and \
                           first_name != cur_first:
                            need_update = True
                        if need_update:
                            await self.execute(
                                "UPDATE users SET "
                                "username = CASE WHEN ? != '' "
                                "THEN ? ELSE username END, "
                                "first_name = CASE WHEN ? != '' "
                                "THEN ? ELSE first_name END, "
                                "updated_at = ? "
                                "WHERE user_id = ?",
                                username, username,
                                first_name, first_name,
                                TimeUtils.utc_now(), user_id,
                            )
                        return True

                referral_code = secrets.token_urlsafe(9)
                now = TimeUtils.utc_now()

                if USE_POSTGRES:
                    async with self.transaction() as conn:
                        await self._execute_with_conn(
                            conn,
                            """INSERT INTO users
                               (user_id, username, first_name,
                                referral_code, trial_used,
                                created_at, updated_at)
                               VALUES ($1, $2, $3, $4, 0, $5, $6)
                               ON CONFLICT (user_id) DO UPDATE SET
                                   username = CASE
                                       WHEN EXCLUDED.username != ''
                                       THEN EXCLUDED.username
                                       ELSE users.username END,
                                   first_name = CASE
                                       WHEN EXCLUDED.first_name != ''
                                       THEN EXCLUDED.first_name
                                       ELSE users.first_name END,
                                   updated_at = EXCLUDED.updated_at""",
                            user_id, username, first_name,
                            referral_code, now, now,
                        )
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO user_points "
                            "(user_id, points, last_updated) "
                            "VALUES ($1, 0, $2) "
                            "ON CONFLICT (user_id) DO NOTHING",
                            user_id, now,
                        )
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO referral_rewards "
                            "(user_id, referral_count, "
                            "total_reward_days, "
                            "claimed_reward_days, "
                            "last_referral_date) "
                            "VALUES ($1, 0, 0, 0, NULL) "
                            "ON CONFLICT (user_id) DO NOTHING",
                            user_id,
                        )
                elif USE_MYSQL:
                    async with self.transaction() as conn:
                        await self._execute_with_conn(
                            conn,
                            """INSERT INTO users
                               (user_id, username, first_name,
                                referral_code, trial_used,
                                created_at, updated_at)
                               VALUES (%s, %s, %s, %s, 0, %s, %s)
                               ON DUPLICATE KEY UPDATE
                                   username = CASE
                                       WHEN VALUES(username) != ''
                                       THEN VALUES(username)
                                       ELSE users.username END,
                                   first_name = CASE
                                       WHEN VALUES(first_name) != ''
                                       THEN VALUES(first_name)
                                       ELSE users.first_name END,
                                   updated_at = VALUES(updated_at)""",
                            user_id, username, first_name,
                            referral_code, now, now,
                        )
                        await self._execute_with_conn(
                            conn,
                            "INSERT IGNORE INTO user_points "
                            "(user_id, points, last_updated) "
                            "VALUES (%s, 0, %s)",
                            user_id, now,
                        )
                        await self._execute_with_conn(
                            conn,
                            "INSERT IGNORE INTO referral_rewards "
                            "(user_id, referral_count, "
                            "total_reward_days, "
                            "claimed_reward_days, "
                            "last_referral_date) "
                            "VALUES (%s, 0, 0, 0, NULL)",
                            user_id,
                        )
                else:
                    async with self.transaction() as conn:
                        await self._execute_with_conn(
                            conn,
                            """INSERT INTO users
                               (user_id, username, first_name,
                                referral_code, trial_used,
                                created_at, updated_at)
                               VALUES (?, ?, ?, ?, 0, ?, ?)
                               ON CONFLICT(user_id) DO UPDATE SET
                                   username = CASE
                                       WHEN excluded.username != ''
                                       THEN excluded.username
                                       ELSE users.username END,
                                   first_name = CASE
                                       WHEN excluded.first_name != ''
                                       THEN excluded.first_name
                                       ELSE users.first_name END,
                                   updated_at = excluded.updated_at""",
                            user_id, username, first_name,
                            referral_code, now, now,
                        )
                        await self._execute_with_conn(
                            conn,
                            "INSERT OR IGNORE INTO user_points "
                            "(user_id, points, last_updated) "
                            "VALUES (?, 0, ?)",
                            user_id, now,
                        )
                        await self._execute_with_conn(
                            conn,
                            "INSERT OR IGNORE INTO "
                            "referral_rewards "
                            "(user_id, referral_count, "
                            "total_reward_days, "
                            "claimed_reward_days, "
                            "last_referral_date) "
                            "VALUES (?, 0, 0, 0, NULL)",
                            user_id,
                        )
            return True
        except Exception as e:
            logger.error(f"❌ register_user: {e}", exc_info=True)
            return False
        finally:
            try:
                await self._invalidate_user_cache_keys(user_id)
            except Exception:
                pass

    async def get_user_language(self, user_id: int) -> str:
        try:
            if CACHE_AVAILABLE:
                cached_data = await user_cache.get(user_id)
                if cached_data:
                    return cached_data.get("language", "ar")
            cached_lang = await internal_cache.get(f"lang_{user_id}")
            if cached_lang:
                return cached_lang
            result = await self.fetchval(
                "SELECT language FROM users WHERE user_id = ?",
                (user_id,), default="ar",
            )
            lang = result if result else "ar"
            await internal_cache.set(
                f"lang_{user_id}", lang, ttl=600
            )
            return lang
        except Exception:
            return "ar"

    async def set_user_language(
        self, user_id: int, lang: str
    ) -> bool:
        result = await self.execute(
            "UPDATE users SET language = ? WHERE user_id = ?",
            (lang, user_id),
        ) > 0
        if result:
            await self._invalidate_user_cache_keys(user_id)
        return result

    async def get_auto_publish_status(self, user_id: int) -> bool:
        cache_key = f"auto_publish_{user_id}"
        cached = await internal_cache.get(cache_key)
        if cached is not None:
            return cached
        result = await self.fetchval(
            "SELECT auto_publish FROM users WHERE user_id = ?",
            (user_id,), default=1,
        )
        is_enabled = result == 1
        await internal_cache.set(cache_key, is_enabled, ttl=120)
        return is_enabled

    async def set_auto_publish(
        self, user_id: int, status: bool
    ) -> bool:
        async with self.transaction() as conn:
            exists = await self._fetchval_with_conn(
                conn,
                "SELECT 1 FROM users WHERE user_id = ?",
                user_id,
            )
            if not exists:
                return False
            await self._execute_with_conn(
                conn,
                "UPDATE users SET auto_publish = ? WHERE user_id = ?",
                1 if status else 0, user_id,
            )
        await self._invalidate_user_cache_keys(user_id)
        return True

    async def get_auto_recycle_status(self, user_id: int) -> bool:
        cache_key = f"auto_recycle_{user_id}"
        cached = await internal_cache.get(cache_key)
        if cached is not None:
            return cached
        result = await self.fetchval(
            "SELECT auto_recycle FROM users WHERE user_id = ?",
            (user_id,), default=1,
        )
        is_enabled = result == 1
        await internal_cache.set(cache_key, is_enabled, ttl=120)
        return is_enabled

    async def set_auto_recycle(
        self, user_id: int, status: bool
    ) -> bool:
        async with self.transaction() as conn:
            exists = await self._fetchval_with_conn(
                conn,
                "SELECT 1 FROM users WHERE user_id = ?",
                user_id,
            )
            if not exists:
                return False
            await self._execute_with_conn(
                conn,
                "UPDATE users SET auto_recycle = ? WHERE user_id = ?",
                1 if status else 0, user_id,
            )
        await self._invalidate_user_cache_keys(user_id)
        return True

    async def get_user_settings_batch(
        self, user_id: int
    ) -> Dict[str, Any]:
        cache_key = f"user_settings_batch_{user_id}"
        cached = await internal_cache.get(cache_key)
        if cached is not None:
            return _clone_start_data(cached)
        row = await self.fetchone(
            "SELECT auto_publish, auto_recycle, language "
            "FROM users WHERE user_id = ?", (user_id,),
        )
        if not row:
            data = {
                'auto_publish': True,
                'auto_recycle': True,
                'language': 'ar',
            }
        else:
            data = {
                'auto_publish': row.get('auto_publish', 1) == 1,
                'auto_recycle': row.get('auto_recycle', 1) == 1,
                'language': row.get('language') or 'ar',
            }
        await internal_cache.set(cache_key, data, ttl=120)
        return _clone_start_data(data)

    async def is_user_banned(self, user_id: int) -> bool:
        result = await self.fetchval(
            "SELECT banned FROM users WHERE user_id = ?",
            (user_id,), default=0,
        )
        return result == 1

    async def ban_user(self, user_id: int) -> bool:
        async with self.transaction() as conn:
            exists = await self._fetchval_with_conn(
                conn,
                "SELECT 1 FROM users WHERE user_id = ?",
                user_id,
            )
            if not exists:
                return False
            await self._execute_with_conn(
                conn,
                "UPDATE users SET banned = 1 WHERE user_id = ?",
                user_id,
            )
        await self._invalidate_user_cache_keys(user_id)
        return True

    async def unban_user(self, user_id: int) -> bool:
        async with self.transaction() as conn:
            exists = await self._fetchval_with_conn(
                conn,
                "SELECT 1 FROM users WHERE user_id = ?",
                user_id,
            )
            if not exists:
                return False
            await self._execute_with_conn(
                conn,
                "UPDATE users SET banned = 0 WHERE user_id = ?",
                user_id,
            )
        await self._invalidate_user_cache_keys(user_id)
        return True

    async def get_all_users(
        self, limit: int = 10000, offset: int = 0
    ) -> List[Dict]:
        return await self.fetchall(
            "SELECT user_id, banned FROM users "
            "ORDER BY user_id LIMIT ? OFFSET ?",
            (limit, offset),
        )

    async def iter_all_users(
        self, batch_size: int = 1000
    ) -> AsyncGenerator[Dict, None]:
        offset = 0
        while True:
            batch = await self.get_all_users(
                limit=batch_size, offset=offset
            )
            if not batch:
                break
            for user in batch:
                yield user
            offset += batch_size
            if len(batch) < batch_size:
                break

    async def mark_users_as_blocked(
        self, user_ids: List[int]
    ) -> int:
        if not user_ids:
            return 0
        try:
            total_updated = 0
            async with self.transaction() as conn:
                BATCH = 400 if DB_TYPE == "sqlite" else 500
                for i in range(0, len(user_ids), BATCH):
                    batch = user_ids[i: i + BATCH]
                    placeholders = ",".join(["?"] * len(batch))
                    updated = await self._execute_with_conn(
                        conn,
                        f"UPDATE users SET banned = 1 "
                        f"WHERE user_id IN ({placeholders})",
                        *batch,
                    )
                    total_updated += updated
            for uid in user_ids:
                await internal_cache.invalidate(f"user_{uid}")
                await internal_cache.invalidate(f"user_{uid}_True")
                await internal_cache.invalidate(f"user_{uid}_False")
            if CACHE_AVAILABLE:
                for uid in user_ids:
                    await invalidate_user_cache(uid)
            return total_updated
        except Exception as e:
            logger.error(
                f"❌ mark_users_as_blocked: {e}", exc_info=True
            )
            return 0

    # =================================================================
    # الجدولة
    # =================================================================

    async def get_schedule(self, channel_db_id: int) -> Dict:
        try:
            await self.execute(
                "INSERT OR IGNORE INTO schedule "
                "(channel_db_id, schedule_type, interval_minutes) "
                "VALUES (?, 'interval_minutes', 12)",
                (channel_db_id,),
            )
        except Exception as e:
            logger.warning(
                f"⚠️ get_schedule INSERT OR IGNORE فشل "
                f"(channel_db_id={channel_db_id}): {e}"
            )
        schedule = await self.fetchone(
            "SELECT * FROM schedule WHERE channel_db_id = ?",
            (channel_db_id,),
        )
        return schedule if schedule else {}

    async def update_schedule(
        self, channel_db_id: int, **kwargs
    ) -> bool:
        if not kwargs:
            return False
        allowed_columns = {
            "schedule_type", "interval_minutes", "interval_hours",
            "interval_days", "days_of_week", "specific_dates",
            "publish_time", "cron_expression", "next_publish_date",
        }
        for key in kwargs:
            if key not in allowed_columns:
                logger.error(f"❌ عمود غير صالح: {key}")
                return False
        updates = [f"{key} = ?" for key in kwargs]
        values = list(kwargs.values()) + [channel_db_id]
        query = (
            f"UPDATE schedule SET {', '.join(updates)} "
            f"WHERE channel_db_id = ?"
        )
        return await self.execute(query, tuple(values)) > 0

    async def update_next_publish(self, channel_db_id: int) -> bool:
        async with self.transaction() as conn:
            schedule = await self._fetchone_with_conn(
                conn,
                "SELECT * FROM schedule WHERE channel_db_id = ?",
                channel_db_id,
            )
            if not schedule:
                await self._execute_with_conn(
                    conn,
                    "INSERT OR IGNORE INTO schedule "
                    "(channel_db_id, schedule_type, "
                    "interval_minutes) "
                    "VALUES (?, 'interval_minutes', 12)",
                    channel_db_id,
                )
                schedule = await self._fetchone_with_conn(
                    conn,
                    "SELECT * FROM schedule "
                    "WHERE channel_db_id = ?",
                    channel_db_id,
                )
            last_publish = await self._fetchval_with_conn(
                conn,
                "SELECT last_publish_time FROM last_publish "
                "WHERE channel_db_id = ?",
                channel_db_id,
            )
            last_time = TimeUtils.safe_parse_iso(last_publish)
            if last_time is None:
                last_time = TimeUtils.utc_now()
            schedule_type = schedule.get(
                "schedule_type", "interval_minutes"
            )
            if schedule_type == "interval_minutes":
                interval_seconds = max(
                    1, schedule.get("interval_minutes", 12)
                ) * 60
            elif schedule_type == "interval_hours":
                interval_seconds = max(
                    1, schedule.get("interval_hours", 1)
                ) * 3600
            elif schedule_type == "interval_days":
                interval_seconds = max(
                    1, schedule.get("interval_days", 1)
                ) * 86400
            else:
                interval_seconds = 12 * 60
            next_date = last_time + timedelta(
                seconds=interval_seconds
            )
            delay_seconds = 1 + (channel_db_id % 60) * 5
            next_date += timedelta(seconds=delay_seconds)
            now = TimeUtils.utc_now()
            if next_date <= now:
                delta = now - last_time
                intervals_needed = (
                    int(delta.total_seconds() // interval_seconds)
                    + 1
                )
                next_date = last_time + timedelta(
                    seconds=interval_seconds * intervals_needed
                )
                next_date += timedelta(seconds=delay_seconds)
            await self._execute_with_conn(
                conn,
                "UPDATE schedule SET next_publish_date = ? "
                "WHERE channel_db_id = ?",
                next_date, channel_db_id,
            )
        return True

    async def update_last_publish(self, channel_db_id: int) -> bool:
        return await self.execute(
            "INSERT OR REPLACE INTO last_publish "
            "(channel_db_id, last_publish_time) VALUES (?, ?)",
            (channel_db_id, TimeUtils.utc_now()),
        ) > 0

    async def get_channels_to_publish(
        self, limit: int = 20
    ) -> List[Dict]:
        now = TimeUtils.utc_now()
        owner_id = getattr(CONFIG, "PRIMARY_OWNER_ID", 0) or 0

        if USE_MYSQL:
            now_str = now.strftime("%Y-%m-%d %H:%M:%S")
            query = """
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
                                         OR fail_count < 3)
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
            return await self.fetchall(
                query,
                (now_str, owner_id, now_str, limit),
            )
        else:
            query = """
                WITH active_subs AS (
                    SELECT s.user_id,
                           MAX(p.max_channels) AS max_channels,
                           MAX(p.max_posts) AS max_posts
                    FROM subscriptions s
                    JOIN plans p ON s.plan_id = p.id
                    WHERE s.status = 'active' AND s.end_date > ?
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
                                         OR fail_count < 3)
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
            return await self.fetchall(
                query, (now, owner_id, now, limit)
            )

    # =================================================================
    # العقوبات
    # =================================================================

    async def add_penalty(
        self,
        user_id: int,
        chat_id: int,
        penalty_type: str,
        duration: int = 0,
        reason: str = "",
        issued_by: Optional[int] = None,
        username: str = "",
        first_name: str = "",
        chat_name: str = "",
        auto_register: bool = True,
    ) -> Optional[int]:
        if penalty_type not in self.VALID_PENALTY_TYPES:
            return None
        if duration < 0:
            duration = 0
        if duration > self.MAX_PENALTY_DURATION:
            duration = self.MAX_PENALTY_DURATION

        penalty_lock = await self._get_penalty_lock(
            user_id, chat_id
        )
        async with penalty_lock:
            try:
                user_ok = await self._ensure_user_exists(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    auto_register=auto_register,
                )
                if not user_ok:
                    return None
                group_ok = await self._ensure_group_exists(
                    chat_id=chat_id,
                    chat_name=chat_name,
                    added_by=issued_by,
                    auto_register=auto_register,
                )
                if not group_ok:
                    return None

                async with self.transaction() as conn:
                    if penalty_type != "warn":
                        await self._execute_with_conn(
                            conn,
                            "UPDATE user_penalties "
                            "SET status = 'removed' "
                            "WHERE user_id = ? AND chat_id = ? "
                            "AND penalty_type = ? "
                            "AND status = 'active'",
                            user_id, chat_id, penalty_type,
                        )
                    start_time = TimeUtils.utc_now()
                    end_time = None
                    if duration > 0:
                        end_time = start_time + timedelta(
                            seconds=duration
                        )

                    if USE_POSTGRES:
                        row = await self._fetchone_with_conn(
                            conn,
                            "INSERT INTO user_penalties "
                            "(user_id, chat_id, penalty_type, "
                            "duration, start_time, end_time, "
                            "reason, issued_by, status, created_at) "
                            "VALUES ($1, $2, $3, $4, $5, $6, $7, "
                            "$8, 'active', $9) RETURNING id",
                            user_id, chat_id, penalty_type,
                            duration, start_time, end_time,
                            reason, issued_by, start_time,
                        )
                        penalty_id = row["id"] if row else None
                    elif USE_MYSQL:
                        cursor = await conn.cursor()
                        try:
                            await cursor.execute(
                                "INSERT INTO user_penalties "
                                "(user_id, chat_id, penalty_type, "
                                "duration, start_time, end_time, "
                                "reason, issued_by, status, "
                                "created_at) "
                                "VALUES (%s, %s, %s, %s, %s, %s, "
                                "%s, %s, 'active', %s)",
                                (user_id, chat_id, penalty_type,
                                 duration, start_time, end_time,
                                 reason, issued_by, start_time),
                            )
                            penalty_id = cursor.lastrowid
                        finally:
                            await cursor.close()
                    else:
                        cursor = await conn.execute(
                            "INSERT INTO user_penalties "
                            "(user_id, chat_id, penalty_type, "
                            "duration, start_time, end_time, "
                            "reason, issued_by, status, created_at) "
                            "VALUES (?,?,?,?,?,?,?,?,'active',?)",
                            (user_id, chat_id, penalty_type,
                             duration, start_time, end_time,
                             reason, issued_by, start_time),
                        )
                        penalty_id = cursor.lastrowid

                    if issued_by is not None and penalty_id:
                        try:
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO admin_logs "
                                "(chat_id, admin_id, action, "
                                "target_id, reason, created_at) "
                                "VALUES (?,?,?,?,?,?)",
                                chat_id, issued_by,
                                f"penalty_{penalty_type}",
                                user_id, reason,
                                TimeUtils.utc_now(),
                            )
                        except Exception:
                            pass
                    return penalty_id
            except Exception as e:
                logger.error(
                    f"❌ add_penalty: {e}", exc_info=True
                )
                return None

    async def remove_penalty(self, penalty_id: int) -> bool:
        async with self.transaction() as conn:
            exists = await self._fetchval_with_conn(
                conn,
                "SELECT 1 FROM user_penalties WHERE id = ?",
                penalty_id,
            )
            if not exists:
                return False
            await self._execute_with_conn(
                conn,
                "UPDATE user_penalties SET status = 'removed' "
                "WHERE id = ?",
                penalty_id,
            )
        return True

    async def remove_penalties_for_user(
        self, user_id: int, chat_id: int,
        penalty_type: str = None,
    ) -> int:
        try:
            async with self.transaction() as conn:
                query = (
                    "UPDATE user_penalties "
                    "SET status = 'removed' "
                    "WHERE user_id = ? AND chat_id = ? "
                    "AND status = 'active'"
                )
                params = [user_id, chat_id]
                if penalty_type:
                    query += " AND penalty_type = ?"
                    params.append(penalty_type)
                return await self._execute_with_conn(
                    conn, query, *params
                )
        except Exception as e:
            logger.error(
                f"❌ remove_penalties_for_user: {e}"
            )
            return 0

    async def get_active_penalties(
        self, user_id: int, chat_id: int = None
    ) -> List[Dict]:
        query = (
            "SELECT * FROM user_penalties "
            "WHERE user_id = ? AND status = 'active'"
        )
        params = [user_id]
        if chat_id:
            query += " AND chat_id = ?"
            params.append(chat_id)
        query += " ORDER BY end_time ASC"
        return await self.fetchall(query, tuple(params))

    async def expire_penalties(self) -> int:
        total_expired = 0
        BATCH = 5000
        try:
            while True:
                batch_expired = 0
                got_rows = 0
                async with self.transaction() as conn:
                    if USE_POSTGRES:
                        ids = await self._fetchall_with_conn(
                            conn,
                            "SELECT id FROM user_penalties "
                            "WHERE status = 'active' "
                            "  AND end_time IS NOT NULL "
                            "  AND end_time <= NOW() "
                            "ORDER BY id "
                            "LIMIT $1",
                            BATCH,
                        )
                        got_rows = len(ids)
                        if not ids:
                            break
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
                    elif USE_MYSQL:
                        ids = await self._fetchall_with_conn(
                            conn,
                            "SELECT id FROM user_penalties "
                            "WHERE status = 'active' "
                            "  AND end_time IS NOT NULL "
                            "  AND end_time <= UTC_TIMESTAMP() "
                            "ORDER BY id "
                            "LIMIT %s",
                            BATCH,
                        )
                        got_rows = len(ids)
                        if not ids:
                            break
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
                    else:
                        ids = await self._fetchall_with_conn(
                            conn,
                            "SELECT id FROM user_penalties "
                            "WHERE status = 'active' "
                            "  AND end_time IS NOT NULL "
                            "  AND end_time <= datetime('now') "
                            "ORDER BY id "
                            "LIMIT ?",
                            BATCH,
                        )
                        got_rows = len(ids)
                        if not ids:
                            break
                        id_list = [r["id"] for r in ids]
                        placeholders = ",".join(
                            ["?"] * len(id_list)
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
                            f"       created_at, datetime('now') "
                            f"FROM user_penalties "
                            f"WHERE id IN ({placeholders})",
                            *id_list,
                        )
                        batch_expired = (
                            await self._execute_with_conn(
                                conn,
                                f"UPDATE user_penalties "
                                f"SET status = 'expired' "
                                f"WHERE id IN "
                                f"({placeholders})",
                                *id_list,
                            ) or 0
                        )

                total_expired += batch_expired
                if got_rows < BATCH:
                    break
                await asyncio.sleep(0)

            try:
                async with self.transaction() as conn:
                    if USE_POSTGRES:
                        await conn.execute(
                            "DELETE FROM penalty_archive "
                            "WHERE archived_at IS NOT NULL "
                            "AND archived_at < "
                            "NOW() - INTERVAL '90 days'"
                        )
                    elif USE_MYSQL:
                        cursor = await conn.cursor()
                        try:
                            await cursor.execute(
                                "DELETE FROM penalty_archive "
                                "WHERE archived_at IS NOT NULL "
                                "AND archived_at < "
                                "UTC_TIMESTAMP() - INTERVAL 90 DAY"
                            )
                        finally:
                            await cursor.close()
                    else:
                        await conn.execute(
                            "DELETE FROM penalty_archive "
                            "WHERE archived_at IS NOT NULL "
                            "AND julianday('now') - "
                            "julianday(archived_at) > 90"
                        )
            except Exception as ce:
                logger.warning(f"⚠️ تنظيف الأرشيف: {ce}")
            return total_expired
        except Exception as e:
            logger.error(
                f"❌ expire_penalties: {e}", exc_info=True
            )
            return total_expired

    async def get_user_penalty_count(
        self, user_id: int, chat_id: int,
        penalty_type: str = None,
    ) -> int:
        query = (
            "SELECT COUNT(*) FROM user_penalties "
            "WHERE user_id = ? AND chat_id = ? "
            "AND status = 'active'"
        )
        params = [user_id, chat_id]
        if penalty_type:
            query += " AND penalty_type = ?"
            params.append(penalty_type)
        return await self.fetchval(
            query, tuple(params), default=0
        )

    async def get_all_active_penalties(self) -> List[Dict]:
        return await self.fetchall(
            "SELECT * FROM user_penalties "
            "WHERE status = 'active' "
            f"LIMIT {MAX_ACTIVE_PENALTIES_FETCH}"
        )

# =====================================================================
# 4) كائن عالمي
# =====================================================================

DB = Database()

async def get_db() -> Database:
    return DB

async def initialize_db() -> bool:
    return await DB.initialize_db()

# =====================================================================
# 5) __all__
# =====================================================================

__all__ = [
    "DB", "Database", "TimeUtils", "get_db", "initialize_db",
    "DB_TYPE", "USE_POSTGRES", "USE_MYSQL", "DATABASE_URL", "UTC",
    "internal_cache", "InternalQueryCache", "SimpleCache",
    "SettingsCache",
    "user_cache", "banned_words_cache", "settings_cache",
    "channels_cache", "groups_cache", "auth_cache", "posts_cache",
    "invalidate_user_cache", "clear_all_caches",
    "get_cache_stats", "cache_cleanup_task", "CACHE_AVAILABLE",
    "KNOWN_UNIQUE_FALLBACK", "_validate_column_def",
    "_clone_start_data", "_create_pool_with_retry",
    "_FactoryFailed",
    "_sql_get_setting_value", "_mysql_random",
    "_find_values_end", "_insert_before_returning",
    "_replace_excluded_with_values",
    "_get_unique_columns", "_find_best_conflict_target",
    "_convert_placeholders", "_convert_insert_or_ignore",
    "_convert_insert_or_replace", "_convert_upsert",
    "_adapt_params", "_table_exists",
]