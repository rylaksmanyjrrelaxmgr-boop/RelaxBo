#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
cache.py - نظام الكاش المتقدم للبوت (v7.5.19 - النسخة المُصحّحة)
================================================================================
🆕 v7.5.19 (تصحيحات أمنية + API عام):
    ✅ TTLCache.delete_by_prefix() — API عام جديد
    ✅ TTLCache.reset_stats() — إعادة تعيين الإحصائيات
    ✅ AuthCache.invalidate لا يستخدم _cache._lock بعد الآن
    ✅ UserDataCache.get_or_load: منع إعادة التحميل المزدوجة عند timeout
    ✅ cache_key: دعم None/datetime/bytes/كائنات معقدة
    ✅ invalidate_auth_cache() helper جديد top-level
    ✅ توثيق تحذيري حول تعارض utils._auth_cache

⚠️ تحذير مهم:
    هذا الملف يعرّف auth_cache مع TTL=10s.
    utils.py يعرّف داخلياً _auth_cache مع TTL=600s.
    يجب على utils.py استخدام auth_cache من هنا وعدم تعريف
    كاش خاص به — وإلا فقد يبقى مشرف مُزَال قادراً 10 دقائق.

- كاش TTL مع حد أقصى للحجم وتنظيف تلقائي
- كاش شامل للمستخدم مع تحميل كامل البيانات دفعة واحدة
- كاش منفصل للقنوات والمجموعات والصلاحيات
- TTL مختلف حسب نوع البيانات (محسّن)
- تنظيف تلقائي دوري في الخلفية
- إحصائيات متقدمة للمطورين
- دعم كامل للاستعلامات المتزامنة
"""

import asyncio
import time
import logging
from collections import OrderedDict
from datetime import datetime
from typing import Any, Optional, Dict, List, Tuple

logger = logging.getLogger(__name__)


# =====================================================================
# 1. فئة TTLCache الأساسية
# =====================================================================

class TTLCache:
    """
    كاش TTL مع حد أقصى للحجم.

    - يدعم TTL مختلف لكل عنصر
    - تنظيف تلقائي عند الإضافة
    - آمن للاستخدام المتزامن مع أقفال
    - إحصائيات دقيقة
    - API عام للحذف الجماعي (بدون الوصول للـ private fields)
    """

    __slots__ = (
        'maxsize', 'default_ttl', '_cache', '_lock',
        '_hits', '_misses', '_expired',
    )

    def __init__(self, maxsize: int = 100, ttl: int = 60):
        self.maxsize = maxsize
        self.default_ttl = ttl
        self._cache: "OrderedDict[str, Tuple[Any, float, int]]" = OrderedDict()
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._expired = 0

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
        """التحقق من وجود مفتاح صالح دون جلب القيمة."""
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
        """تخزين قيمة في الكاش مع TTL مخصص (اختياري)."""
        effective_ttl = ttl if ttl is not None else self.default_ttl
        async with self._lock:
            self._cache[key] = (value, time.time(), effective_ttl)
            self._cache.move_to_end(key)
            self._cleanup_locked()

    async def set_many(self, items: Dict[str, Any], ttl: int = None) -> None:
        """تخزين قيم متعددة دفعة واحدة."""
        effective_ttl = ttl if ttl is not None else self.default_ttl
        async with self._lock:
            now = time.time()
            for key, value in items.items():
                self._cache[key] = (value, now, effective_ttl)
                self._cache.move_to_end(key)
            self._cleanup_locked()

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

    # ✅ NEW v7.5.19: API عام للحذف بالبادئة
    async def delete_by_prefix(self, prefix: str) -> int:
        """
        حذف جميع المفاتيح التي تبدأ بـ prefix.
        API عام بديل عن الوصول إلى self._cache._lock و self._cache._cache.
        """
        async with self._lock:
            keys = [k for k in self._cache if k.startswith(prefix)]
            for k in keys:
                del self._cache[k]
            return len(keys)

    async def clear(self) -> None:
        """مسح الكاش بالكامل + إعادة تعيين الإحصائيات."""
        async with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._expired = 0

    async def cleanup(self) -> int:
        """تنظيف العناصر المنتهية وإرجاع عدد المحذوف."""
        async with self._lock:
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
            }

    # ✅ NEW v7.5.19: إعادة تعيين الإحصائيات
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
        """جلب جميع القيم (للتشخيص)."""
        async with self._lock:
            return {k: v[0] for k, v in self._cache.items()}

    # ─── internal ───────────────────────────────────────────────────

    def _cleanup_locked(self) -> None:
        """تنظيف داخلي بدون قفل (يُستدعى داخل set فقط)."""
        now = time.time()
        expired_keys = [
            k for k, (_, ts, ttl) in self._cache.items()
            if now - ts > ttl
        ]
        for k in expired_keys:
            del self._cache[k]

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

    ⚠️ تحذير: TTL=10 ثوانٍ هنا.
    تأكد أن utils.py يستخدم هذا الكاش وليس كاشاً خاصاً بـ TTL أطول.
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
        """
        ✅ v7.5.19: يستخدم delete_by_prefix بدل الوصول للـ private fields.
        """
        if chat_id is not None and user_id is not None:
            await self.cache.delete(f"auth_{chat_id}_{user_id}")
        elif chat_id is not None:
            # ✅ API عام بدل self.cache._lock / self.cache._cache
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

    ✅ v7.5.19:
      - get_or_load: منع إعادة التحميل المزدوجة عند timeout
      - _load_user_full_data: توثيق الاستدعاءات المتوازية
    """

    def __init__(self):
        self.cache = TTLCache(maxsize=1000, ttl=60)
        self._loading: Dict[int, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    async def get(self, user_id: int) -> Optional[Dict]:
        return await self.cache.get(f"user_{user_id}")

    async def get_with_ttl(self, user_id: int) -> Tuple[Optional[Dict], Optional[int]]:
        return await self.cache.get_with_ttl(f"user_{user_id}")

    async def set(self, user_id: int, data: Dict) -> None:
        await self.cache.set(f"user_{user_id}", data)

    async def invalidate(self, user_id: int) -> None:
        await self.cache.delete(f"user_{user_id}")
        async with self._lock:
            self._loading.pop(user_id, None)

    async def invalidate_all(self) -> None:
        await self.cache.clear()
        async with self._lock:
            self._loading.clear()

    async def get_or_load(self, user_id: int, db) -> Dict:
        """
        ✅ v7.5.19: جلب من الكاش أو تحميل مع منع التحميل المتكرر.
        عند timeout: لا نُعيد التحميل، بل نرمي استثناء واضح.
        """
        # 1. محاولة من الكاش
        cached = await self.get(user_id)
        if cached is not None:
            return cached

        # 2. منع التحميل المتكرر
        my_event: Optional[asyncio.Event] = None
        wait_event: Optional[asyncio.Event] = None
        async with self._lock:
            existing = self._loading.get(user_id)
            if existing is not None:
                wait_event = existing
            else:
                my_event = asyncio.Event()
                self._loading[user_id] = my_event

        # 3. إذا كان هناك تحميل جارٍ، انتظره
        if wait_event is not None:
            try:
                await asyncio.wait_for(wait_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                # ✅ v7.5.19: لا نُعيد التحميل — نرفع استثناء واضح
                # (إعادة التحميل كانت تُضاعف الحمل تحت ضغط عالٍ)
                logger.warning(
                    f"⏱️ timeout 10s في انتظار تحميل المستخدم {user_id}"
                )
                # نحاول القراءة من الكاش مرة أخيرة قبل الفشل
                cached = await self.get(user_id)
                if cached is not None:
                    return cached
                raise RuntimeError(
                    f"UserDataCache.get_or_load timeout for user {user_id}"
                )

            # بعد الانتظار، حاول الكاش مرة أخيرة
            cached = await self.get(user_id)
            if cached is not None:
                return cached

            # المنتظر لم يجد نتيجة → يُحمّل بنفسه (بعد انتهاء المنتظر الأول)
            # ملاحظة: هذا يحدث فقط لو فشل المحمّل الأول
            return await self._load_user_full_data(db, user_id)

        # 4. نحن المسؤولون عن التحميل
        try:
            data = await self._load_user_full_data(db, user_id)
            await self.set(user_id, data)
            return data
        finally:
            async with self._lock:
                self._loading.pop(user_id, None)
            if my_event is not None:
                my_event.set()

    async def _load_user_full_data(self, db, user_id: int) -> Dict:
        """
        ✅ v7.5.19: استدعاء واحد ذكي + متوازي.

        ملاحظة معمارية:
        - db.get_start_data() يُرجع: user_data أساسي + counts + channel_info
          لكنه **لا يُرجع** قوائم القنوات/المجموعات الفعلية.
        - لذلك نحتاج استدعاء get_user_channels و get_user_groups
          بالتوازي لجلب القوائم الكاملة.
        - لا يمكن حذف هذه الاستدعاءات دون تغيير DB.get_start_data.
        """
        # 1. البيانات الأساسية
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

        # 2. جلب القوائم الكاملة بالتوازي
        # (get_start_data يُرجع counts فقط، لا القوائم)
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

        # 3. بناء الكائن الموحّد
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
    """إبطال كاش مستخدم معين (user + channels + groups)."""
    await user_cache.invalidate(user_id)
    await channels_cache.invalidate(user_id)
    await groups_cache.invalidate(user_id)


async def invalidate_auth_cache(
    chat_id: int = None, user_id: int = None
) -> None:
    """
    ✅ v7.5.19: helper جديد — إبطال كاش الصلاحيات.

    استخدم هذا بعد أي تغيير في المشرفين:
        await invalidate_auth_cache(chat_id=..., user_id=...)
    """
    await auth_cache.invalidate(chat_id=chat_id, user_id=user_id)


async def invalidate_all_user_cache() -> None:
    """إبطال كاش جميع المستخدمين."""
    await user_cache.invalidate_all()
    await channels_cache.invalidate_all()
    await groups_cache.invalidate_all()
    await posts_cache.invalidate()


async def clear_all_caches() -> Dict:
    """مسح جميع الكاشات وإرجاع إحصائيات قبلية."""
    stats_before = await get_cache_stats()

    await settings_cache.security.clear()
    await settings_cache.auto_reply.clear()
    await settings_cache.bot_settings.clear()
    await banned_words_cache.cache.clear()
    await auth_cache.cache.clear()
    await auth_cache.admin_cache.clear()
    await channels_cache.cache.clear()
    await channels_cache.channel_info.clear()
    await groups_cache.cache.clear()
    await groups_cache.group_info.clear()
    await user_cache.cache.clear()
    await posts_cache.cache.clear()
    await posts_cache.next_post.clear()

    logger.info("🧹 تم مسح جميع الكاشات")
    return stats_before


# =====================================================================
# 11. مهمة التنظيف الدورية
# =====================================================================

async def cache_cleanup_task():
    """مهمة تنظيف دورية للكاش (تُشغل في الخلفية)."""
    while True:
        try:
            await asyncio.sleep(300)
            total = 0
            for cache_obj in (
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
            ):
                total += await cache_obj.cleanup()
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
    """جلب إحصائيات الكاش (للمطورين)."""
    return {
        'settings': {
            'security': len(settings_cache.security._cache),
            'auto_reply': len(settings_cache.auto_reply._cache),
            'bot_settings': len(settings_cache.bot_settings._cache),
        },
        'banned_words': len(banned_words_cache.cache._cache),
        'auth': {
            'permissions': len(auth_cache.cache._cache),
            'admins': len(auth_cache.admin_cache._cache),
        },
        'channels': {
            'user_channels': len(channels_cache.cache._cache),
            'channel_info': len(channels_cache.channel_info._cache),
        },
        'groups': {
            'user_groups': len(groups_cache.cache._cache),
            'group_info': len(groups_cache.group_info._cache),
        },
        'user': len(user_cache.cache._cache),
        'posts': {
            'posts': len(posts_cache.cache._cache),
            'next_post': len(posts_cache.next_post._cache),
        },
        'total': sum([
            len(settings_cache.security._cache),
            len(settings_cache.auto_reply._cache),
            len(settings_cache.bot_settings._cache),
            len(banned_words_cache.cache._cache),
            len(auth_cache.cache._cache),
            len(auth_cache.admin_cache._cache),
            len(channels_cache.cache._cache),
            len(channels_cache.channel_info._cache),
            len(groups_cache.cache._cache),
            len(groups_cache.group_info._cache),
            len(user_cache.cache._cache),
            len(posts_cache.cache._cache),
            len(posts_cache.next_post._cache),
        ])
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


# =====================================================================
# 13. cache_key
# =====================================================================

def cache_key(*args, **kwargs) -> str:
    """
    إنشاء مفتاح كاش منسق من arguments.

    ✅ v7.5.19: يدعم None / datetime / bytes / كائنات معقدة.
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
        # احتياطي: أي كائن آخر
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
    'cache_key',
]