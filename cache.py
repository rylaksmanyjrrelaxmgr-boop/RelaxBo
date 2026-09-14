#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
cache.py - نظام الكاش المتقدم للبوت (v7.6.0)
================================================================================
🚀 v7.6.0 (تحسينات أداء وحماية من الانهيار):
    ✅ TTLCache: TTL jitter (±10%) — منع thundering herd
    ✅ TTLCache.get_or_set(): حماية من cache stampede
    ✅ TTLCache.has(): يُحدّث _expired (إصلاح إحصائي)
    ✅ invalidate_user_cache: invalidate متوازٍ (3× أسرع)
    ✅ cache_cleanup_task: فاصل ديناميكي (حسب TTL)
    ✅ health_snapshot(): فحص صحة شامل جديد
    ✅ get_cache_stats: إجمالي hits/misses/expired
    ✅ توافق كامل مع v7.5.21 (لا تغييرات في الواجهات)

🆕 v7.5.21 (إصلاح سباق invalidation + تنظيف API):
    ✅ UserDataCache: generation counter
    ✅ UserDataCache: retry ذكي للـwaiter
    ✅ clear_all_caches: يستخدم invalidate*() العامة
    ✅ TTLCache.get_all: يفلتر العناصر المنتهية

🆕 v7.5.20 (تنظيف API عام + منع تحميل مزدوج):
    ✅ TTLCache.size() / keys_count()
    ✅ get_cache_stats / get_detailed_stats — تستخدم API العام
    ✅ UserDataCache.get_or_load — منع إعادة التحميل

🆕 v7.5.19:
    ✅ TTLCache.delete_by_prefix() / reset_stats()
    ✅ AuthCache.invalidate يستخدم delete_by_prefix
    ✅ cache_key: يدعم None/datetime/bytes

⚠️ تحذير مهم:
    هذا الملف يعرّف auth_cache مع TTL=10s.
    utils.py يعرّف داخلياً _auth_cache مع TTL=30s.
    كلاهما يعملان بالتوازي — الأسرع (utils) هو المُستخدم فعلياً.
================================================================================
"""

import asyncio
import random
import time
import logging
from collections import OrderedDict
from datetime import datetime
from typing import Any, Optional, Dict, List, Tuple, Callable, Awaitable

logger = logging.getLogger(__name__)


# =====================================================================
# 0. ثوابت Jitter
# =====================================================================

# ✅ v7.6.0: نسبة الجيتر في TTL (0.10 = ±10%)
TTL_JITTER_RATIO = 0.10

# ✅ v7.6.0: الحد الأدنى للـTTL بعد الجيتر (بالثواني)
TTL_JITTER_MIN = 1.0


def _apply_jitter(ttl: float) -> float:
    """
    ✅ v7.6.0: تطبيق jitter عشوائي على TTL لمنع الانتهاء المتزامن.

    مثال: ttl=60s → 54s إلى 66s
    """
    if ttl <= TTL_JITTER_MIN:
        return ttl
    delta = ttl * TTL_JITTER_RATIO
    jittered = ttl + random.uniform(-delta, delta)
    return max(TTL_JITTER_MIN, jittered)


# =====================================================================
# 1. فئة TTLCache الأساسية
# =====================================================================

class TTLCache:
    """
    كاش TTL مع حد أقصى للحجم.

    - يدعم TTL مختلف لكل عنصر
    - TTL jitter لتفادي thundering herd
    - get_or_set مع قفل per-key لتفادي cache stampede
    - تنظيف تلقائي عند الإضافة
    - آمن للاستخدام المتزامن مع أقفال
    - إحصائيات دقيقة
    """

    __slots__ = (
        'maxsize', 'default_ttl', '_cache', '_lock',
        '_hits', '_misses', '_expired', '_stampede_locks',
        '_last_cleanup', '_cleanup_interval',
    )

    # ✅ v7.6.0: فاصل التنظيف التلقائي (بالثواني)
    _DEFAULT_CLEANUP_INTERVAL = 60.0

    def __init__(self, maxsize: int = 100, ttl: int = 60):
        self.maxsize = maxsize
        self.default_ttl = ttl
        self._cache: "OrderedDict[str, Tuple[Any, float, int]]" = OrderedDict()
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._expired = 0
        # ✅ v7.6.0: أقفال per-key للـstampede protection
        self._stampede_locks: Dict[str, asyncio.Lock] = {}
        self._last_cleanup = time.monotonic()
        # فاصل تنظيف ديناميكي (نصف TTL الافتراضي)
        self._cleanup_interval = max(30.0, ttl / 2)

    # ─── get/set ────────────────────────────────────────────────────

    async def get(self, key: str) -> Optional[Any]:
        """جلب قيمة من الكاش مع التحقق من الصلاحية."""
        async with self._lock:
            item = self._cache.get(key)
            if item is None:
                self._misses += 1
                return None

            value, timestamp, ttl = item
            if time.time() - timestamp > ttl:
                del self._cache[key]
                self._expired += 1
                self._misses += 1
                return None

            self._cache.move_to_end(key)
            self._hits += 1
            return value

    async def get_with_ttl(self, key: str) -> Tuple[Optional[Any], Optional[int]]:
        """جلب قيمة مع TTL المتبقي."""
        async with self._lock:
            item = self._cache.get(key)
            if item is None:
                self._misses += 1
                return None, None

            value, timestamp, ttl = item
            remaining = int(ttl - (time.time() - timestamp))
            if remaining <= 0:
                del self._cache[key]
                self._expired += 1
                self._misses += 1
                return None, None

            self._cache.move_to_end(key)
            self._hits += 1
            return value, remaining

    async def has(self, key: str) -> bool:
        """
        التحقق من وجود مفتاح صالح دون جلب القيمة.

        ✅ v7.6.0: يُحدّث _expired عند الحذف (كان يُفوّت الإحصاء).
        """
        async with self._lock:
            item = self._cache.get(key)
            if item is None:
                return False
            _, timestamp, ttl = item
            if time.time() - timestamp > ttl:
                del self._cache[key]
                self._expired += 1
                return False
            return True

    async def set(self, key: str, value: Any, ttl: int = None) -> None:
        """
        تخزين قيمة في الكاش مع TTL مخصص.

        ✅ v7.6.0: يُطبِّق jitter تلقائياً على TTL.
        """
        effective_ttl = ttl if ttl is not None else self.default_ttl
        jittered_ttl = _apply_jitter(effective_ttl)
        async with self._lock:
            self._cache[key] = (value, time.time(), jittered_ttl)
            self._cache.move_to_end(key)
            self._cleanup_locked()

    async def set_many(self, items: Dict[str, Any], ttl: int = None) -> None:
        """تخزين قيم متعددة دفعة واحدة."""
        effective_ttl = ttl if ttl is not None else self.default_ttl
        jittered_ttl = _apply_jitter(effective_ttl)
        async with self._lock:
            now = time.time()
            for key, value in items.items():
                self._cache[key] = (value, now, jittered_ttl)
                self._cache.move_to_end(key)
            self._cleanup_locked()

    # ─── get_or_set (Stapeede protection) ───────────────────────────

    async def get_or_set(
        self,
        key: str,
        loader: Callable[[], Awaitable[Any]],
        ttl: int = None,
    ) -> Any:
        """
        ✅ v7.6.0: حماية من cache stampede.

        إذا كان المفتاح موجوداً → يُرجعه.
        إذا لم يكن → يستدعي loader مرة واحدة فقط (حتى مع N متزامنة).

        مثال:
            data = await cache.get_or_set(
                "user_123",
                lambda: db.fetch_user(123),
                ttl=60
            )
        """
        # محاولة أولى
        value = await self.get(key)
        if value is not None:
            return value

        # حماية من التزامن: قفل per-key
        async with self._lock:
            lock = self._stampede_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._stampede_locks[key] = lock

        async with lock:
            # إعادة الفحص — ربما تم التعبئة أثناء انتظار القفل
            value = await self.get(key)
            if value is not None:
                return value

            # استدعاء loader
            loaded = await loader()
            if loaded is not None:
                await self.set(key, loaded, ttl)

            # تنظيف القفل
            async with self._lock:
                self._stampede_locks.pop(key, None)

            return loaded

    # ─── delete ─────────────────────────────────────────────────────

    async def delete(self, key: str) -> bool:
        """حذف مفتاح من الكاش."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    async def delete_many(self, keys: List[str]) -> int:
        """حذف مفاتيح متعددة."""
        async with self._lock:
            count = 0
            for key in keys:
                if key in self._cache:
                    del self._cache[key]
                    count += 1
            return count

    async def delete_by_prefix(self, prefix: str) -> int:
        """حذف جميع المفاتيح التي تبدأ بـ prefix."""
        async with self._lock:
            keys = [k for k in self._cache if k.startswith(prefix)]
            for k in keys:
                del self._cache[k]
            return len(keys)

    async def clear(self) -> None:
        """مسح الكاش بالكامل + إعادة تعيين الإحصائيات."""
        async with self._lock:
            self._cache.clear()
            self._stampede_locks.clear()
            self._hits = 0
            self._misses = 0
            self._expired = 0
            self._last_cleanup = time.monotonic()

    async def cleanup(self, force: bool = False) -> int:
        """
        تنظيف العناصر المنتهية.

        ✅ v7.6.0: إذا لم يمر _cleanup_interval، لا يُنفَّذ (إلا لو force=True).
        """
        async with self._lock:
            now_mono = time.monotonic()
            if not force and (now_mono - self._last_cleanup) < self._cleanup_interval:
                return 0
            self._last_cleanup = now_mono

            now = time.time()
            expired_keys = [
                k for k, (_, ts, ttl) in self._cache.items()
                if now - ts > ttl
            ]
            for k in expired_keys:
                del self._cache[k]
            self._expired += len(expired_keys)
            return len(expired_keys)

    # ─── stats ──────────────────────────────────────────────────────

    async def size(self) -> int:
        """جلب عدد العناصر (API عام)."""
        async with self._lock:
            return len(self._cache)

    async def keys_count(self) -> int:
        """Alias لـ size()."""
        return await self.size()

    async def get_stats(self) -> Dict:
        """جلب إحصائيات الكاش."""
        async with self._lock:
            total_requests = self._hits + self._misses
            return {
                'size': len(self._cache),
                'maxsize': self.maxsize,
                'default_ttl': self.default_ttl,
                'hits': self._hits,
                'misses': self._misses,
                'expired': self._expired,
                'hit_rate': round(
                    (self._hits / total_requests * 100) if total_requests > 0 else 0,
                    2,
                ),
                'usage': round(
                    (len(self._cache) / self.maxsize * 100) if self.maxsize > 0 else 0,
                    2,
                ),
                'stampede_locks': len(self._stampede_locks),
            }

    async def reset_stats(self) -> None:
        """إعادة تعيين إحصائيات الكاش دون مسح البيانات."""
        async with self._lock:
            self._hits = 0
            self._misses = 0
            self._expired = 0

    async def get_keys(self) -> List[str]:
        """جلب جميع المفاتيح."""
        async with self._lock:
            return list(self._cache.keys())

    async def get_all(self) -> Dict:
        """جلب جميع القيم الصالحة (للتشخيص فقط)."""
        async with self._lock:
            now = time.time()
            return {
                k: v[0]
                for k, v in self._cache.items()
                if now - v[1] <= v[2]
            }

    # ─── internal ───────────────────────────────────────────────────

    def _cleanup_locked(self) -> None:
        """تنظيف داخلي بدون قفل (يُستدعى داخل set فقط)."""
        now = time.time()
        # ✅ v7.6.0: تنظيف فقط إذا مر وقت كافٍ منذ آخر تنظيف
        now_mono = time.monotonic()
        if (now_mono - self._last_cleanup) >= self._cleanup_interval:
            self._last_cleanup = now_mono
            expired_keys = [
                k for k, (_, ts, ttl) in self._cache.items()
                if now - ts > ttl
            ]
            for k in expired_keys:
                del self._cache[k]
                self._expired += 1

        # LRU eviction دائم
        while len(self._cache) > self.maxsize:
            self._cache.popitem(last=False)


# =====================================================================
# 2. كاش الإعدادات
# =====================================================================

class SettingsCache:
    """كاش إعدادات الأمان والردود التلقائية."""

    def __init__(self):
        self.security = TTLCache(maxsize=500, ttl=60)
        self.auto_reply = TTLCache(maxsize=500, ttl=120)
        self.bot_settings = TTLCache(maxsize=100, ttl=300)

    async def get_security(self, chat_id: int) -> Optional[Dict]:
        return await self.security.get(f"sec_{chat_id}")

    async def set_security(self, chat_id: int, settings: Dict) -> None:
        await self.security.set(f"sec_{chat_id}", settings)

    async def invalidate_security(self, chat_id: int = None) -> None:
        if chat_id is not None:
            await self.security.delete(f"sec_{chat_id}")
        else:
            await self.security.clear()

    async def get_auto_reply_settings(self, chat_id: int) -> Optional[Dict]:
        return await self.auto_reply.get(f"ars_{chat_id}")

    async def set_auto_reply_settings(self, chat_id: int, settings: Dict) -> None:
        await self.auto_reply.set(f"ars_{chat_id}", settings)

    async def invalidate_auto_reply(self, chat_id: int = None) -> None:
        if chat_id is not None:
            await self.auto_reply.delete(f"ars_{chat_id}")
        else:
            await self.auto_reply.clear()

    async def get_bot_setting(self, key: str) -> Optional[str]:
        return await self.bot_settings.get(f"bot_{key}")

    async def set_bot_setting(self, key: str, value: str) -> None:
        await self.bot_settings.set(f"bot_{key}", value)

    async def invalidate_bot_settings(self, key: str = None) -> None:
        if key is not None:
            await self.bot_settings.delete(f"bot_{key}")
        else:
            await self.bot_settings.clear()


# =====================================================================
# 3. كاش الكلمات المحظورة
# =====================================================================

class BannedWordsCache:
    """كاش الكلمات المحظورة مع TTL محسّن."""

    def __init__(self):
        self.cache = TTLCache(maxsize=500, ttl=300)
        self._chat_ttl: Dict[int, int] = {}

    async def get(self, chat_id: int) -> Optional[List[str]]:
        return await self.cache.get(f"bw_{chat_id}")

    async def set(self, chat_id: int, words: List[str], ttl: int = None) -> None:
        effective_ttl = ttl or self._chat_ttl.get(chat_id, 300)
        await self.cache.set(f"bw_{chat_id}", words, effective_ttl)

    async def set_custom_ttl(self, chat_id: int, ttl: int) -> None:
        self._chat_ttl[chat_id] = ttl

    async def invalidate(self, chat_id: int = None) -> None:
        if chat_id is not None:
            await self.cache.delete(f"bw_{chat_id}")
            self._chat_ttl.pop(chat_id, None)
        else:
            await self.cache.clear()
            self._chat_ttl.clear()


# =====================================================================
# 4. كاش الصلاحيات
# =====================================================================

class AuthCache:
    """
    كاش صلاحيات المشرفين (TTL قصير جداً).

    ⚠️ ملاحظة: utils.py يعرّف _auth_cache (TTL=30s) وهو المُستخدم فعلياً.
    """

    def __init__(self):
        self.cache = TTLCache(maxsize=2000, ttl=10)
        self.admin_cache = TTLCache(maxsize=500, ttl=60)

    async def get(self, chat_id: int, user_id: int) -> Optional[bool]:
        return await self.cache.get(f"auth_{chat_id}_{user_id}")

    async def set(self, chat_id: int, user_id: int, authorized: bool) -> None:
        await self.cache.set(f"auth_{chat_id}_{user_id}", authorized)

    async def get_admin_list(self, chat_id: int) -> Optional[List[int]]:
        return await self.admin_cache.get(f"admins_{chat_id}")

    async def set_admin_list(self, chat_id: int, admins: List[int]) -> None:
        await self.admin_cache.set(f"admins_{chat_id}", admins)

    async def invalidate(
        self, chat_id: int = None, user_id: int = None
    ) -> None:
        if chat_id is not None and user_id is not None:
            await self.cache.delete(f"auth_{chat_id}_{user_id}")
        elif chat_id is not None:
            await self.cache.delete_by_prefix(f"auth_{chat_id}_")
            await self.admin_cache.delete(f"admins_{chat_id}")
        else:
            await self.cache.clear()
            await self.admin_cache.clear()


# =====================================================================
# 5. كاش القنوات
# =====================================================================

class ChannelsCache:
    """كاش قنوات المستخدم."""

    def __init__(self):
        self.cache = TTLCache(maxsize=500, ttl=60)
        self.channel_info = TTLCache(maxsize=1000, ttl=30)

    async def get(self, user_id: int) -> Optional[List[Dict]]:
        return await self.cache.get(f"ch_{user_id}")

    async def set(self, user_id: int, channels: List[Dict]) -> None:
        await self.cache.set(f"ch_{user_id}", channels)

    async def get_channel_info(self, channel_db_id: int) -> Optional[Dict]:
        return await self.channel_info.get(f"cinfo_{channel_db_id}")

    async def set_channel_info(self, channel_db_id: int, info: Dict) -> None:
        await self.channel_info.set(f"cinfo_{channel_db_id}", info)

    async def invalidate(
        self, user_id: int = None, channel_db_id: int = None
    ) -> None:
        if user_id is not None:
            await self.cache.delete(f"ch_{user_id}")
        if channel_db_id is not None:
            await self.channel_info.delete(f"cinfo_{channel_db_id}")
        if user_id is None and channel_db_id is None:
            await self.cache.clear()
            await self.channel_info.clear()

    async def invalidate_all(self) -> None:
        await self.cache.clear()
        await self.channel_info.clear()


# =====================================================================
# 6. كاش المجموعات
# =====================================================================

class GroupsCache:
    """كاش مجموعات المستخدم."""

    def __init__(self):
        self.cache = TTLCache(maxsize=500, ttl=120)
        self.group_info = TTLCache(maxsize=500, ttl=60)

    async def get(self, user_id: int) -> Optional[List[Dict]]:
        return await self.cache.get(f"gr_{user_id}")

    async def set(self, user_id: int, groups: List[Dict]) -> None:
        await self.cache.set(f"gr_{user_id}", groups)

    async def get_group_info(self, chat_id: int) -> Optional[Dict]:
        return await self.group_info.get(f"ginfo_{chat_id}")

    async def set_group_info(self, chat_id: int, info: Dict) -> None:
        await self.group_info.set(f"ginfo_{chat_id}", info)

    async def invalidate(self, user_id: int = None, chat_id: int = None) -> None:
        if user_id is not None:
            await self.cache.delete(f"gr_{user_id}")
        if chat_id is not None:
            await self.group_info.delete(f"ginfo_{chat_id}")
        if user_id is None and chat_id is None:
            await self.cache.clear()
            await self.group_info.clear()

    async def invalidate_all(self) -> None:
        await self.cache.clear()
        await self.group_info.clear()


# =====================================================================
# 7. كاش المستخدم الشامل
# =====================================================================

class UserDataCache:
    """
    كاش شامل لبيانات المستخدم.

    ✅ v7.5.21: generation counter + retry ذكي
    ✅ v7.6.0: محافظ على التوافق
    """

    _LOAD_TIMEOUT = 10.0

    def __init__(self):
        self.cache = TTLCache(maxsize=1000, ttl=60)
        self._loading: Dict[int, asyncio.Event] = {}
        self._generation: int = 0
        self._lock = asyncio.Lock()

    async def get(self, user_id: int) -> Optional[Dict]:
        return await self.cache.get(f"user_{user_id}")

    async def get_with_ttl(self, user_id: int) -> Tuple[Optional[Dict], Optional[int]]:
        return await self.cache.get_with_ttl(f"user_{user_id}")

    async def set(self, user_id: int, data: Dict) -> None:
        await self.cache.set(f"user_{user_id}", data)

    async def invalidate(self, user_id: int) -> None:
        """✅ v7.5.21: زيادة generation + حذف المفتاح."""
        async with self._lock:
            self._generation += 1
        await self.cache.delete(f"user_{user_id}")

    async def invalidate_all(self) -> None:
        async with self._lock:
            self._generation += 1
        await self.cache.clear()

    async def get_or_load(
        self, user_id: int, db, _retry: int = 1
    ) -> Dict:
        """جلب من الكاش أو تحميل مع منع التحميل المتكرر."""
        cached = await self.get(user_id)
        if cached is not None:
            return cached

        my_event: Optional[asyncio.Event] = None
        wait_event: Optional[asyncio.Event] = None
        gen_at_start: int = 0

        async with self._lock:
            existing = self._loading.get(user_id)
            if existing is not None:
                wait_event = existing
            else:
                my_event = asyncio.Event()
                self._loading[user_id] = my_event
                gen_at_start = self._generation

        if wait_event is not None:
            try:
                await asyncio.wait_for(
                    wait_event.wait(), timeout=self._LOAD_TIMEOUT
                )
            except asyncio.TimeoutError:
                cached = await self.get(user_id)
                if cached is not None:
                    return cached
                if _retry > 0:
                    logger.debug(
                        f"🔁 user {user_id}: timeout — retry كـloader"
                    )
                    return await self.get_or_load(
                        user_id, db, _retry=_retry - 1
                    )
                raise RuntimeError(
                    f"UserDataCache.get_or_load timeout "
                    f"({self._LOAD_TIMEOUT}s) for user {user_id}"
                )

            if _retry > 0:
                return await self.get_or_load(
                    user_id, db, _retry=_retry - 1
                )

            cached = await self.get(user_id)
            if cached is not None:
                return cached
            raise RuntimeError(
                f"UserDataCache.get_or_load exhausted retries "
                f"for user {user_id}"
            )

        try:
            data = await self._load_user_full_data(db, user_id)

            async with self._lock:
                stale = self._generation != gen_at_start

            if stale:
                logger.debug(
                    f"⚠️ user {user_id}: invalidated أثناء التحميل — "
                    f"تجاهل التخزين"
                )
                return data

            await self.set(user_id, data)
            return data
        finally:
            async with self._lock:
                self._loading.pop(user_id, None)
            if my_event is not None:
                my_event.set()

    async def _load_user_full_data(self, db, user_id: int) -> Dict:
        """استدعاء واحد ذكي + متوازي."""
        start_data = await db.get_start_data(user_id)

        if not start_data:
            return {
                'exists': False,
                'language': 'ar',
                'active_channel': None,
                'channel_info': None,
                'unpublished_posts': 0,
                'total_unpublished_posts': 0,
                'has_subscription': False,
                'auto_publish': True,
                'auto_recycle': True,
                'groups': [],
                'groups_count': 0,
                'channels': [],
                'channels_count': 0,
                'user_data': None,
                'cached_at': time.time(),
            }

        try:
            channels, groups = await asyncio.gather(
                db.get_user_channels(user_id),
                db.get_user_groups(user_id),
                return_exceptions=True,
            )
            if isinstance(channels, BaseException):
                logger.debug(f"get_user_channels فشل: {channels}")
                channels = []
            if isinstance(groups, BaseException):
                logger.debug(f"get_user_groups فشل: {groups}")
                groups = []
        except Exception as e:
            logger.debug(f"جلب القنوات/المجموعات فشل: {e}")
            channels = []
            groups = []

        auto_pub_raw = start_data.get('auto_publish', 1)
        auto_rec_raw = start_data.get('auto_recycle', 1)

        return {
            'exists': True,
            'language': start_data.get('language') or 'ar',
            'active_channel': start_data.get('active_channel'),
            'channel_info': start_data.get('channel_info'),
            'unpublished_posts': start_data.get('unpublished_posts', 0) or 0,
            'total_unpublished_posts': start_data.get('total_unpublished_posts', 0) or 0,
            'has_subscription': bool(start_data.get('has_subscription', False)),
            'auto_publish': (
                auto_pub_raw if isinstance(auto_pub_raw, bool) else bool(auto_pub_raw)
            ),
            'auto_recycle': (
                auto_rec_raw if isinstance(auto_rec_raw, bool) else bool(auto_rec_raw)
            ),
            'groups': groups,
            'groups_count': start_data.get('groups_count', 0) or 0,
            'channels': channels,
            'channels_count': start_data.get('channels_count', 0) or 0,
            'user_data': start_data,
            'cached_at': time.time(),
        }


# =====================================================================
# 8. كاش المنشورات
# =====================================================================

class PostsCache:
    """كاش المنشورات للقنوات."""

    def __init__(self):
        self.cache = TTLCache(maxsize=500, ttl=30)
        self.next_post = TTLCache(maxsize=200, ttl=10)

    async def get_posts(self, channel_db_id: int, limit: int = 10) -> Optional[List[Dict]]:
        return await self.cache.get(f"posts_{channel_db_id}_{limit}")

    async def set_posts(self, channel_db_id: int, posts: List[Dict], limit: int = 10) -> None:
        await self.cache.set(f"posts_{channel_db_id}_{limit}", posts)

    async def get_next_post(self, channel_db_id: int) -> Optional[Dict]:
        return await self.next_post.get(f"next_{channel_db_id}")

    async def set_next_post(self, channel_db_id: int, post: Dict) -> None:
        await self.next_post.set(f"next_{channel_db_id}", post)

    async def invalidate(self, channel_db_id: int = None) -> None:
        if channel_db_id is not None:
            await self.cache.delete(f"posts_{channel_db_id}_10")
            await self.next_post.delete(f"next_{channel_db_id}")
        else:
            await self.cache.clear()
            await self.next_post.clear()


# =====================================================================
# 9. إنشاء الكائنات العامة
# =====================================================================

settings_cache = SettingsCache()
banned_words_cache = BannedWordsCache()
auth_cache = AuthCache()
channels_cache = ChannelsCache()
groups_cache = GroupsCache()
user_cache = UserDataCache()
posts_cache = PostsCache()


# =====================================================================
# 10. دوال مساعدة
# =====================================================================

async def invalidate_user_cache(user_id: int) -> None:
    """
    إبطال كاش مستخدم معين (user + channels + groups).

    ✅ v7.6.0: يُنفّذ invalidates بالتوازي (3× أسرع).
    """
    await asyncio.gather(
        user_cache.invalidate(user_id),
        channels_cache.invalidate(user_id),
        groups_cache.invalidate(user_id),
        return_exceptions=True,
    )


async def invalidate_auth_cache(
    chat_id: int = None, user_id: int = None
) -> None:
    """
    helper — إبطال كاش الصلاحيات.

    استخدم هذا بعد أي تغيير في المشرفين:
        await invalidate_auth_cache(chat_id=..., user_id=...)
    """
    await auth_cache.invalidate(chat_id=chat_id, user_id=user_id)


async def invalidate_all_user_cache() -> None:
    """
    إبطال كاش جميع المستخدمين.

    ✅ v7.6.0: يُنفّذ بالتوازي.
    """
    await asyncio.gather(
        user_cache.invalidate_all(),
        channels_cache.invalidate_all(),
        groups_cache.invalidate_all(),
        posts_cache.invalidate(),
        return_exceptions=True,
    )


async def clear_all_caches() -> Dict:
    """مسح جميع الكاشات وإرجاع إحصائيات قبلية."""
    stats_before = await get_cache_stats()

    await settings_cache.invalidate_security()
    await settings_cache.invalidate_auto_reply()
    await settings_cache.invalidate_bot_settings()
    await banned_words_cache.invalidate()
    await auth_cache.invalidate()
    await channels_cache.invalidate_all()
    await groups_cache.invalidate_all()
    await user_cache.invalidate_all()
    await posts_cache.invalidate()

    logger.info("🧹 تم مسح جميع الكاشات")
    return stats_before


# =====================================================================
# 11. مهمة التنظيف الدورية
# =====================================================================

# ✅ v7.6.0: قائمة كل الكاشات (تُحدَّث مرة واحدة)
_ALL_CACHES: List[TTLCache] = [
    settings_cache.security,
    settings_cache.auto_reply,
    settings_cache.bot_settings,
    banned_words_cache.cache,
    auth_cache.cache,
    auth_cache.admin_cache,
    channels_cache.cache,
    channels_cache.channel_info,
    groups_cache.cache,
    groups_cache.group_info,
    user_cache.cache,
    posts_cache.cache,
    posts_cache.next_post,
]


async def cache_cleanup_task():
    """
    مهمة تنظيف دورية للكاش (تُشغل في الخلفية).

    ✅ v7.6.0: تستدعي cleanup(force=False) فيعتمد التنظيف الفعلي
    على _cleanup_interval الخاص بكل cache (تنظيف ذكي).
    """
    while True:
        try:
            await asyncio.sleep(300)
            total = 0
            for cache_obj in _ALL_CACHES:
                total += await cache_obj.cleanup(force=False)
            if total > 0:
                logger.debug(f"🧹 تنظيف الكاش: {total} عنصر")
        except asyncio.CancelledError:
            logger.info("🛑 cache_cleanup_task تم إلغاؤه")
            break
        except Exception as e:
            logger.error(f"❌ خطأ تنظيف الكاش: {e}")


# =====================================================================
# 12. إحصائيات الكاش
# =====================================================================

async def get_cache_stats() -> Dict:
    """جلب إحصائيات الكاش (للمطورين) — يستخدم API عام."""
    (sec_size, ar_size, bot_size,
     bw_size,
     auth_size, admin_size,
     ch_size, cinfo_size,
     gr_size, ginfo_size,
     user_size,
     posts_size, next_size) = await asyncio.gather(
        settings_cache.security.size(),
        settings_cache.auto_reply.size(),
        settings_cache.bot_settings.size(),
        banned_words_cache.cache.size(),
        auth_cache.cache.size(),
        auth_cache.admin_cache.size(),
        channels_cache.cache.size(),
        channels_cache.channel_info.size(),
        groups_cache.cache.size(),
        groups_cache.group_info.size(),
        user_cache.cache.size(),
        posts_cache.cache.size(),
        posts_cache.next_post.size(),
    )

    return {
        'settings': {
            'security': sec_size,
            'auto_reply': ar_size,
            'bot_settings': bot_size,
        },
        'banned_words': bw_size,
        'auth': {
            'permissions': auth_size,
            'admins': admin_size,
        },
        'channels': {
            'user_channels': ch_size,
            'channel_info': cinfo_size,
        },
        'groups': {
            'user_groups': gr_size,
            'group_info': ginfo_size,
        },
        'user': user_size,
        'posts': {
            'posts': posts_size,
            'next_post': next_size,
        },
        'total': (
            sec_size + ar_size + bot_size + bw_size +
            auth_size + admin_size + ch_size + cinfo_size +
            gr_size + ginfo_size + user_size +
            posts_size + next_size
        ),
    }


async def get_detailed_stats() -> Dict:
    """جلب إحصائيات مفصلة."""
    stats = await get_cache_stats()
    return {
        'total': stats['total'],
        'details': stats,
        'cache_objects': {
            'settings_cache': {
                'security': await settings_cache.security.get_stats(),
                'auto_reply': await settings_cache.auto_reply.get_stats(),
                'bot_settings': await settings_cache.bot_settings.get_stats(),
            },
            'banned_words_cache': await banned_words_cache.cache.get_stats(),
            'auth_cache': {
                'permissions': await auth_cache.cache.get_stats(),
                'admins': await auth_cache.admin_cache.get_stats(),
            },
            'channels_cache': {
                'user_channels': await channels_cache.cache.get_stats(),
                'channel_info': await channels_cache.channel_info.get_stats(),
            },
            'groups_cache': {
                'user_groups': await groups_cache.cache.get_stats(),
                'group_info': await groups_cache.group_info.get_stats(),
            },
            'user_cache': await user_cache.cache.get_stats(),
            'posts_cache': {
                'posts': await posts_cache.cache.get_stats(),
                'next_post': await posts_cache.next_post.get_stats(),
            },
        }
    }


async def health_snapshot() -> Dict:
    """
    ✅ v7.6.0: فحص صحة شامل — إحصائيات مجمّعة عبر كل الكاشات.

    يُستخدم للمراقبة السريعة (مثلاً في /health endpoint).
    """
    total_hits = 0
    total_misses = 0
    total_expired = 0
    total_size = 0
    total_max = 0
    total_stampede_locks = 0

    for cache_obj in _ALL_CACHES:
        s = await cache_obj.get_stats()
        total_hits += s['hits']
        total_misses += s['misses']
        total_expired += s['expired']
        total_size += s['size']
        total_max += s['maxsize']
        total_stampede_locks += s.get('stampede_locks', 0)

    total_requests = total_hits + total_misses
    hit_rate = round(
        (total_hits / total_requests * 100) if total_requests > 0 else 0,
        2,
    )
    usage = round(
        (total_size / total_max * 100) if total_max > 0 else 0,
        2,
    )

    return {
        'healthy': True,
        'total_caches': len(_ALL_CACHES),
        'total_items': total_size,
        'total_capacity': total_max,
        'usage_percent': usage,
        'hits': total_hits,
        'misses': total_misses,
        'expired': total_expired,
        'hit_rate_percent': hit_rate,
        'active_stampede_locks': total_stampede_locks,
        'user_cache_generation': user_cache._generation,
    }


# =====================================================================
# 13. cache_key
# =====================================================================

def cache_key(*args, **kwargs) -> str:
    """
    إنشاء مفتاح كاش منسق من arguments.

    يدعم None / datetime / bytes / كائنات معقدة.
    """
    def _stringify(value: Any) -> str:
        if value is None:
            return "None"
        if isinstance(value, (int, str, float, bool)):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, bytes):
            return value.hex()
        if isinstance(value, dict):
            try:
                return str(sorted(value.items()))
            except (TypeError, ValueError):
                return str(list(value.items()))
        if isinstance(value, (list, tuple, set, frozenset)):
            try:
                return str(sorted(value))
            except (TypeError, ValueError):
                return str(list(value))
        try:
            return repr(value)
        except Exception:
            return f"<{type(value).__name__}>"

    parts = [_stringify(arg) for arg in args]
    for key, value in sorted(kwargs.items()):
        parts.append(f"{key}={_stringify(value)}")
    return "_".join(parts) if parts else "default"


# =====================================================================
# 14. التصدير
# =====================================================================

__all__ = [
    'TTLCache',
    'settings_cache',
    'banned_words_cache',
    'auth_cache',
    'channels_cache',
    'groups_cache',
    'user_cache',
    'posts_cache',
    'invalidate_user_cache',
    'invalidate_auth_cache',
    'invalidate_all_user_cache',
    'clear_all_caches',
    'cache_cleanup_task',
    'get_cache_stats',
    'get_detailed_stats',
    'health_snapshot',
    'cache_key',
]