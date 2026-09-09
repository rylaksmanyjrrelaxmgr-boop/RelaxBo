#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
cache.py - نظام الكاش الموحد للبوت (النسخة المحسّنة)
=====================================================
- تحسين أداء TTLCache
- كاش شامل للمستخدم (UserDataCache) مع تحميل كامل البيانات
- كاش منفصل للقنوات والمجموعات
- TTL مختلف حسب نوع البيانات
- تنظيف تلقائي دوري
"""

import asyncio
import time
import logging
from collections import OrderedDict
from typing import Any, Optional, Dict, List

logger = logging.getLogger(__name__)


class TTLCache:
    """كاش TTL مع حد أقصى للحجم (نسخة محسّنة)"""

    __slots__ = ('maxsize', 'ttl', '_cache', '_lock')

    def __init__(self, maxsize: int = 100, ttl: int = 60):
        self.maxsize = maxsize
        self.ttl = ttl
        self._cache = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        """جلب قيمة من الكاش مع التحقق من الصلاحية"""
        async with self._lock:
            item = self._cache.get(key)
            if item is None:
                return None
            value, timestamp = item
            if time.time() - timestamp > self.ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return value

    async def has(self, key: str) -> bool:
        """التحقق من وجود مفتاح صالح دون جلب القيمة"""
        async with self._lock:
            item = self._cache.get(key)
            if item is None:
                return False
            _, timestamp = item
            if time.time() - timestamp > self.ttl:
                del self._cache[key]
                return False
            return True

    async def set(self, key: str, value: Any, ttl: int = None) -> None:
        """تخزين قيمة في الكاش مع TTL مخصص (اختياري)"""
        effective_ttl = ttl if ttl is not None else self.ttl
        async with self._lock:
            self._cache[key] = (value, time.time())
            self._cache.move_to_end(key)
            self._cleanup_locked(effective_ttl)

    async def delete(self, key: str) -> None:
        """حذف مفتاح"""
        async with self._lock:
            self._cache.pop(key, None)

    async def clear(self) -> None:
        """مسح الكاش بالكامل"""
        async with self._lock:
            self._cache.clear()

    async def cleanup(self) -> int:
        """تنظيف العناصر المنتهية وإرجاع عدد المحذوف"""
        async with self._lock:
            now = time.time()
            expired = [k for k, (_, ts) in self._cache.items() if now - ts > self.ttl]
            for k in expired:
                del self._cache[k]
            return len(expired)

    def _cleanup_locked(self, ttl: int = None) -> None:
        """تنظيف داخلي بدون قفل (يُستدعى داخل set)"""
        now = time.time()
        effective_ttl = ttl if ttl is not None else self.ttl
        expired = [k for k, (_, ts) in self._cache.items() if now - ts > effective_ttl]
        for k in expired:
            del self._cache[k]
        while len(self._cache) > self.maxsize:
            self._cache.popitem(last=False)


# =====================================================================
# كاش الإعدادات
# =====================================================================

class SettingsCache:
    """كاش إعدادات الأمان والردود التلقائية"""

    def __init__(self):
        self.security = TTLCache(maxsize=500, ttl=30)
        self.auto_reply = TTLCache(maxsize=500, ttl=60)

    async def get_security(self, chat_id: int):
        return await self.security.get(f"sec_{chat_id}")

    async def set_security(self, chat_id: int, settings: Dict):
        await self.security.set(f"sec_{chat_id}", settings)

    async def invalidate_security(self, chat_id: int = None):
        if chat_id is not None:
            await self.security.delete(f"sec_{chat_id}")
        else:
            await self.security.clear()

    async def get_auto_reply_settings(self, chat_id: int):
        return await self.auto_reply.get(f"ars_{chat_id}")

    async def set_auto_reply_settings(self, chat_id: int, settings: Dict):
        await self.auto_reply.set(f"ars_{chat_id}", settings)

    async def invalidate_auto_reply(self, chat_id: int = None):
        if chat_id is not None:
            await self.auto_reply.delete(f"ars_{chat_id}")
        else:
            await self.auto_reply.clear()


# =====================================================================
# كاش الكلمات المحظورة
# =====================================================================

class BannedWordsCache:
    """كاش الكلمات المحظورة"""

    def __init__(self):
        self.cache = TTLCache(maxsize=300, ttl=60)

    async def get(self, chat_id: int):
        return await self.cache.get(f"bw_{chat_id}")

    async def set(self, chat_id: int, words: list):
        await self.cache.set(f"bw_{chat_id}", words)

    async def invalidate(self, chat_id: int = None):
        if chat_id is not None:
            await self.cache.delete(f"bw_{chat_id}")
        else:
            await self.cache.clear()


# =====================================================================
# كاش الصلاحيات
# =====================================================================

class AuthCache:
    """كاش صلاحيات المشرفين"""

    def __init__(self):
        self.cache = TTLCache(maxsize=2000, ttl=10)  # TTL قصير لأن الصلاحيات تتغير كثيراً

    async def get(self, chat_id: int, user_id: int):
        return await self.cache.get(f"auth_{chat_id}_{user_id}")

    async def set(self, chat_id: int, user_id: int, authorized: bool):
        await self.cache.set(f"auth_{chat_id}_{user_id}", authorized)

    async def invalidate(self, chat_id: int = None, user_id: int = None):
        if chat_id is not None and user_id is not None:
            await self.cache.delete(f"auth_{chat_id}_{user_id}")
        elif chat_id is not None:
            async with self.cache._lock:
                keys = [k for k in self.cache._cache.keys() if k.startswith(f"auth_{chat_id}_")]
                for k in keys:
                    del self.cache._cache[k]
        else:
            await self.cache.clear()


# =====================================================================
# كاش القنوات والمجموعات (جديد)
# =====================================================================

class ChannelsCache:
    """كاش قنوات المستخدم"""

    def __init__(self):
        self.cache = TTLCache(maxsize=200, ttl=15)

    async def get(self, user_id: int):
        return await self.cache.get(f"ch_{user_id}")

    async def set(self, user_id: int, channels: list):
        await self.cache.set(f"ch_{user_id}", channels)

    async def invalidate(self, user_id: int = None):
        if user_id is not None:
            await self.cache.delete(f"ch_{user_id}")
        else:
            await self.cache.clear()


class GroupsCache:
    """كاش مجموعات المستخدم"""

    def __init__(self):
        self.cache = TTLCache(maxsize=200, ttl=30)

    async def get(self, user_id: int):
        return await self.cache.get(f"gr_{user_id}")

    async def set(self, user_id: int, groups: list):
        await self.cache.set(f"gr_{user_id}", groups)

    async def invalidate(self, user_id: int = None):
        if user_id is not None:
            await self.cache.delete(f"gr_{user_id}")
        else:
            await self.cache.clear()


# =====================================================================
# كاش المستخدم الشامل (المحسّن)
# =====================================================================

class UserDataCache:
    """
    كاش شامل لبيانات المستخدم (جميع المعلومات في كائن واحد)
    - يقلل عدد استعلامات /start من 8 إلى 2-3 استعلامات
    - TTL = 30 ثانية (يتجدد تلقائياً)
    - يتم إبطاله عند تغيير أي بيانات للمستخدم
    """

    def __init__(self):
        self.cache = TTLCache(maxsize=500, ttl=30)

    async def get(self, user_id: int) -> Optional[Dict]:
        """جلب بيانات المستخدم من الكاش"""
        return await self.cache.get(f"user_{user_id}")

    async def set(self, user_id: int, data: Dict) -> None:
        """تخزين بيانات المستخدم في الكاش"""
        await self.cache.set(f"user_{user_id}", data)

    async def invalidate(self, user_id: int) -> None:
        """إبطال كاش مستخدم معين (يُستدعى عند تغيير بياناته)"""
        await self.cache.delete(f"user_{user_id}")

    async def invalidate_all(self) -> None:
        """إبطال كاش جميع المستخدمين"""
        await self.cache.clear()

    async def get_or_load(self, user_id: int, db) -> Dict:
        """جلب من الكاش، أو تحميل من قاعدة البيانات إذا لم يكن موجوداً"""
        cached = await self.get(user_id)
        if cached is not None:
            return cached

        # تحميل جميع البيانات دفعة واحدة
        data = await self._load_user_full_data(db, user_id)
        await self.set(user_id, data)
        return data

    async def _load_user_full_data(self, db, user_id: int) -> Dict:
        """
        تحميل جميع بيانات المستخدم في استعلامات متوازية
        باستخدام asyncio.gather
        """
        # 1. جلب بيانات المستخدم الأساسية
        user_data = await db.get_user(user_id, include_stats=False)
        if not user_data:
            # إذا لم يكن المستخدم موجوداً، نعيد بيانات افتراضية
            return {
                'language': 'ar',
                'active_channel': None,
                'channel_info': None,
                'unpublished_posts': 0,
                'has_subscription': False,
                'auto_publish': True,
                'auto_recycle': True,
                'groups': [],
                'groups_count': 0,
                'user_data': None
            }

        # 2. جلب البيانات الإضافية بشكل متوازٍ
        tasks = [
            db.get_active_channel(user_id),
            db.has_active_subscription(user_id),
            db.get_auto_publish_status(user_id),
            db.get_auto_recycle_status(user_id),
            db.get_user_groups(user_id),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        active_channel = results[0] if not isinstance(results[0], Exception) else None
        has_sub = results[1] if not isinstance(results[1], Exception) else False
        auto_pub = results[2] if not isinstance(results[2], Exception) else True
        auto_rec = results[3] if not isinstance(results[3], Exception) else True
        groups = results[4] if not isinstance(results[4], Exception) else []

        # 3. جلب معلومات القناة النشطة وعدد المنشورات غير المنشورة
        channel_info = None
        unpublished_posts = 0
        if active_channel:
            try:
                channel_info = await db.get_channel_info(user_id, active_channel)
                if channel_info:
                    unpublished_posts = await db.get_unpublished_posts_count(user_id, active_channel)
            except Exception:
                pass

        # 4. بناء كائن البيانات الكامل
        return {
            'language': user_data.get('language', 'ar'),
            'active_channel': active_channel,
            'channel_info': channel_info,
            'unpublished_posts': unpublished_posts,
            'has_subscription': has_sub,
            'auto_publish': auto_pub,
            'auto_recycle': auto_rec,
            'groups': groups,
            'groups_count': len(groups) if isinstance(groups, list) else 0,
            'user_data': user_data,  # يحتوي على الاسم، الحالة، إلخ
        }


# =====================================================================
# إنشاء الكائنات العامة (نسخة محسّنة)
# =====================================================================

settings_cache = SettingsCache()
banned_words_cache = BannedWordsCache()
auth_cache = AuthCache()
channels_cache = ChannelsCache()
groups_cache = GroupsCache()
user_cache = UserDataCache()


# =====================================================================
# دوال مساعدة للاستيراد السريع
# =====================================================================

async def invalidate_user_cache(user_id: int) -> None:
    """إبطال كاش مستخدم معين (دالة مساعدة)"""
    await user_cache.invalidate(user_id)
    await channels_cache.invalidate(user_id)
    await groups_cache.invalidate(user_id)


async def invalidate_all_user_cache() -> None:
    """إبطال كاش جميع المستخدمين"""
    await user_cache.invalidate_all()
    await channels_cache.invalidate_all()
    await groups_cache.invalidate_all()


async def clear_all_caches() -> None:
    """مسح جميع الكاشات"""
    await settings_cache.security.clear()
    await settings_cache.auto_reply.clear()
    await banned_words_cache.cache.clear()
    await auth_cache.cache.clear()
    await channels_cache.cache.clear()
    await groups_cache.cache.clear()
    await user_cache.cache.clear()
    logger.info("🧹 تم مسح جميع الكاشات")


# =====================================================================
# مهمة التنظيف الدورية
# =====================================================================

async def cache_cleanup_task():
    """مهمة تنظيف دورية للكاش (تُشغل في الخلفية)"""
    while True:
        await asyncio.sleep(300)  # كل 5 دقائق
        try:
            total = 0
            for cache_obj in (
                settings_cache.security,
                settings_cache.auto_reply,
                banned_words_cache.cache,
                auth_cache.cache,
                channels_cache.cache,
                groups_cache.cache,
                user_cache.cache,
            ):
                total += await cache_obj.cleanup()
            if total > 0:
                logger.debug(f"🧹 تنظيف الكاش: {total} عنصر")
        except Exception as e:
            logger.error(f"❌ خطأ تنظيف الكاش: {e}")


# =====================================================================
# إحصائيات الكاش (للمطورين)
# =====================================================================

async def get_cache_stats() -> Dict:
    """جلب إحصائيات الكاش (للمطورين)"""
    return {
        'security': len(settings_cache.security._cache),
        'auto_reply': len(settings_cache.auto_reply._cache),
        'banned_words': len(banned_words_cache.cache._cache),
        'auth': len(auth_cache.cache._cache),
        'channels': len(channels_cache.cache._cache),
        'groups': len(groups_cache.cache._cache),
        'user': len(user_cache.cache._cache),
        'total': sum([
            len(settings_cache.security._cache),
            len(settings_cache.auto_reply._cache),
            len(banned_words_cache.cache._cache),
            len(auth_cache.cache._cache),
            len(channels_cache.cache._cache),
            len(groups_cache.cache._cache),
            len(user_cache.cache._cache),
        ])
    }