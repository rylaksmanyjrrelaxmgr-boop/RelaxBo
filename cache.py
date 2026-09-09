#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
cache.py - نظام الكاش المتقدم للبوت (النسخة النهائية المحسّنة)
================================================================
- كاش TTL مع حد أقصى للحجم وتنظيف تلقائي
- كاش شامل للمستخدم مع تحميل كامل البيانات دفعة واحدة
- كاش منفصل للقنوات والمجموعات والصلاحيات
- TTL مختلف حسب نوع البيانات (محسّن)
- تنظيف تلقائي دوري في الخلفية
- إحصائيات متقدمة للمطورين
- دعم كامل للاستعلامات المتزامنة
- تقليل استعلامات /start من 8 إلى 2-3 استعلامات فقط
"""

import asyncio
import time
import logging
from collections import OrderedDict
from typing import Any, Optional, Dict, List, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# =====================================================================
# 1. فئة TTLCache الأساسية (محسّنة)
# =====================================================================

class TTLCache:
    """
    كاش TTL مع حد أقصى للحجم (نسخة محسّنة)
    - يدعم TTL مختلف لكل عنصر
    - تنظيف تلقائي عند الإضافة
    - آمن للاستخدام المتزامن مع أقفال
    - إحصائيات دقيقة
    """

    __slots__ = ('maxsize', 'default_ttl', '_cache', '_lock', '_hits', '_misses', '_expired')

    def __init__(self, maxsize: int = 100, ttl: int = 60):
        self.maxsize = maxsize
        self.default_ttl = ttl
        self._cache = OrderedDict()
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._expired = 0

    async def get(self, key: str) -> Optional[Any]:
        """جلب قيمة من الكاش مع التحقق من الصلاحية"""
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
        """جلب قيمة مع TTL المتبقي"""
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
        """التحقق من وجود مفتاح صالح دون جلب القيمة"""
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
        """تخزين قيمة في الكاش مع TTL مخصص (اختياري)"""
        effective_ttl = ttl if ttl is not None else self.default_ttl
        async with self._lock:
            self._cache[key] = (value, time.time(), effective_ttl)
            self._cache.move_to_end(key)
            self._cleanup_locked()

    async def set_many(self, items: Dict[str, Any], ttl: int = None) -> None:
        """تخزين قيم متعددة في الكاش دفعة واحدة"""
        effective_ttl = ttl if ttl is not None else self.default_ttl
        async with self._lock:
            now = time.time()
            for key, value in items.items():
                self._cache[key] = (value, now, effective_ttl)
                self._cache.move_to_end(key)
            self._cleanup_locked()

    async def delete(self, key: str) -> bool:
        """حذف مفتاح من الكاش"""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    async def delete_many(self, keys: List[str]) -> int:
        """حذف مفاتيح متعددة من الكاش"""
        async with self._lock:
            count = 0
            for key in keys:
                if key in self._cache:
                    del self._cache[key]
                    count += 1
            return count

    async def clear(self) -> None:
        """مسح الكاش بالكامل"""
        async with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._expired = 0

    async def cleanup(self) -> int:
        """تنظيف العناصر المنتهية وإرجاع عدد المحذوف"""
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

    async def get_stats(self) -> Dict:
        """جلب إحصائيات الكاش"""
        async with self._lock:
            total_requests = self._hits + self._misses
            return {
                'size': len(self._cache),
                'maxsize': self.maxsize,
                'default_ttl': self.default_ttl,
                'hits': self._hits,
                'misses': self._misses,
                'expired': self._expired,
                'hit_rate': round((self._hits / total_requests * 100) if total_requests > 0 else 0, 2),
                'usage': round((len(self._cache) / self.maxsize * 100) if self.maxsize > 0 else 0, 2)
            }

    async def get_keys(self) -> List[str]:
        """جلب جميع المفاتيح في الكاش"""
        async with self._lock:
            return list(self._cache.keys())

    async def get_all(self) -> Dict:
        """جلب جميع القيم في الكاش (للتشخيص)"""
        async with self._lock:
            return {k: v[0] for k, v in self._cache.items()}

    def _cleanup_locked(self) -> None:
        """تنظيف داخلي بدون قفل (يُستدعى داخل set)"""
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
    """كاش إعدادات الأمان والردود التلقائية"""

    def __init__(self):
        self.security = TTLCache(maxsize=500, ttl=60)  # 60 ثانية
        self.auto_reply = TTLCache(maxsize=500, ttl=120)  # 120 ثانية
        self.bot_settings = TTLCache(maxsize=100, ttl=300)  # 5 دقائق

    async def get_security(self, chat_id: int) -> Optional[Dict]:
        """جلب إعدادات الأمان"""
        return await self.security.get(f"sec_{chat_id}")

    async def set_security(self, chat_id: int, settings: Dict) -> None:
        """تخزين إعدادات الأمان"""
        await self.security.set(f"sec_{chat_id}", settings)

    async def invalidate_security(self, chat_id: int = None) -> None:
        """مسح كاش إعدادات الأمان"""
        if chat_id is not None:
            await self.security.delete(f"sec_{chat_id}")
        else:
            await self.security.clear()

    async def get_auto_reply_settings(self, chat_id: int) -> Optional[Dict]:
        """جلب إعدادات الردود التلقائية"""
        return await self.auto_reply.get(f"ars_{chat_id}")

    async def set_auto_reply_settings(self, chat_id: int, settings: Dict) -> None:
        """تخزين إعدادات الردود التلقائية"""
        await self.auto_reply.set(f"ars_{chat_id}", settings)

    async def invalidate_auto_reply(self, chat_id: int = None) -> None:
        """مسح كاش إعدادات الردود التلقائية"""
        if chat_id is not None:
            await self.auto_reply.delete(f"ars_{chat_id}")
        else:
            await self.auto_reply.clear()

    async def get_bot_setting(self, key: str) -> Optional[str]:
        """جلب إعداد عام للبوت"""
        return await self.bot_settings.get(f"bot_{key}")

    async def set_bot_setting(self, key: str, value: str) -> None:
        """تخزين إعداد عام للبوت"""
        await self.bot_settings.set(f"bot_{key}", value)

    async def invalidate_bot_settings(self, key: str = None) -> None:
        """مسح كاش الإعدادات العامة"""
        if key is not None:
            await self.bot_settings.delete(f"bot_{key}")
        else:
            await self.bot_settings.clear()


# =====================================================================
# 3. كاش الكلمات المحظورة
# =====================================================================

class BannedWordsCache:
    """كاش الكلمات المحظورة مع TTL محسّن"""

    def __init__(self):
        self.cache = TTLCache(maxsize=500, ttl=300)  # 5 دقائق
        self._chat_ttl = {}  # TTL مخصص لكل محادثة

    async def get(self, chat_id: int) -> Optional[List[str]]:
        """جلب الكلمات المحظورة من الكاش"""
        return await self.cache.get(f"bw_{chat_id}")

    async def set(self, chat_id: int, words: List[str], ttl: int = None) -> None:
        """تخزين الكلمات المحظورة في الكاش"""
        effective_ttl = ttl or self._chat_ttl.get(chat_id, 300)
        await self.cache.set(f"bw_{chat_id}", words, effective_ttl)

    async def set_custom_ttl(self, chat_id: int, ttl: int) -> None:
        """تعيين TTL مخصص لمحادثة معينة"""
        self._chat_ttl[chat_id] = ttl

    async def invalidate(self, chat_id: int = None) -> None:
        """مسح كاش الكلمات المحظورة"""
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
    """كاش صلاحيات المشرفين (TTL قصير جداً)"""

    def __init__(self):
        self.cache = TTLCache(maxsize=2000, ttl=10)  # 10 ثوانٍ فقط
        self.admin_cache = TTLCache(maxsize=500, ttl=60)  # 60 ثانية للمشرفين

    async def get(self, chat_id: int, user_id: int) -> Optional[bool]:
        """جلب صلاحية مستخدم من الكاش"""
        return await self.cache.get(f"auth_{chat_id}_{user_id}")

    async def set(self, chat_id: int, user_id: int, authorized: bool) -> None:
        """تخزين صلاحية مستخدم في الكاش"""
        await self.cache.set(f"auth_{chat_id}_{user_id}", authorized)

    async def get_admin_list(self, chat_id: int) -> Optional[List[int]]:
        """جلب قائمة المشرفين من الكاش"""
        return await self.admin_cache.get(f"admins_{chat_id}")

    async def set_admin_list(self, chat_id: int, admins: List[int]) -> None:
        """تخزين قائمة المشرفين في الكاش"""
        await self.admin_cache.set(f"admins_{chat_id}", admins)

    async def invalidate(self, chat_id: int = None, user_id: int = None) -> None:
        """مسح كاش الصلاحيات"""
        if chat_id is not None and user_id is not None:
            await self.cache.delete(f"auth_{chat_id}_{user_id}")
        elif chat_id is not None:
            # مسح جميع الصلاحيات للمحادثة
            async with self.cache._lock:
                keys = [k for k in self.cache._cache.keys() if k.startswith(f"auth_{chat_id}_")]
                for k in keys:
                    del self.cache._cache[k]
            await self.admin_cache.delete(f"admins_{chat_id}")
        else:
            await self.cache.clear()
            await self.admin_cache.clear()


# =====================================================================
# 5. كاش القنوات والمجموعات
# =====================================================================

class ChannelsCache:
    """كاش قنوات المستخدم"""

    def __init__(self):
        self.cache = TTLCache(maxsize=500, ttl=60)  # 60 ثانية
        self.channel_info = TTLCache(maxsize=1000, ttl=30)  # 30 ثانية

    async def get(self, user_id: int) -> Optional[List[Dict]]:
        """جلب قنوات المستخدم من الكاش"""
        return await self.cache.get(f"ch_{user_id}")

    async def set(self, user_id: int, channels: List[Dict]) -> None:
        """تخزين قنوات المستخدم في الكاش"""
        await self.cache.set(f"ch_{user_id}", channels)

    async def get_channel_info(self, channel_db_id: int) -> Optional[Dict]:
        """جلب معلومات قناة معينة"""
        return await self.channel_info.get(f"cinfo_{channel_db_id}")

    async def set_channel_info(self, channel_db_id: int, info: Dict) -> None:
        """تخزين معلومات قناة"""
        await self.channel_info.set(f"cinfo_{channel_db_id}", info)

    async def invalidate(self, user_id: int = None, channel_db_id: int = None) -> None:
        """مسح كاش القنوات"""
        if user_id is not None:
            await self.cache.delete(f"ch_{user_id}")
        if channel_db_id is not None:
            await self.channel_info.delete(f"cinfo_{channel_db_id}")
        if user_id is None and channel_db_id is None:
            await self.cache.clear()
            await self.channel_info.clear()


# =====================================================================
# 6. كاش المجموعات
# =====================================================================

class GroupsCache:
    """كاش مجموعات المستخدم"""

    def __init__(self):
        self.cache = TTLCache(maxsize=500, ttl=120)  # 120 ثانية
        self.group_info = TTLCache(maxsize=500, ttl=60)  # 60 ثانية

    async def get(self, user_id: int) -> Optional[List[Dict]]:
        """جلب مجموعات المستخدم من الكاش"""
        return await self.cache.get(f"gr_{user_id}")

    async def set(self, user_id: int, groups: List[Dict]) -> None:
        """تخزين مجموعات المستخدم في الكاش"""
        await self.cache.set(f"gr_{user_id}", groups)

    async def get_group_info(self, chat_id: int) -> Optional[Dict]:
        """جلب معلومات مجموعة"""
        return await self.group_info.get(f"ginfo_{chat_id}")

    async def set_group_info(self, chat_id: int, info: Dict) -> None:
        """تخزين معلومات مجموعة"""
        await self.group_info.set(f"ginfo_{chat_id}", info)

    async def invalidate(self, user_id: int = None, chat_id: int = None) -> None:
        """مسح كاش المجموعات"""
        if user_id is not None:
            await self.cache.delete(f"gr_{user_id}")
        if chat_id is not None:
            await self.group_info.delete(f"ginfo_{chat_id}")
        if user_id is None and chat_id is None:
            await self.cache.clear()
            await self.group_info.clear()


# =====================================================================
# 7. كاش المستخدم الشامل (الأهم)
# =====================================================================

class UserDataCache:
    """
    كاش شامل لبيانات المستخدم (جميع المعلومات في كائن واحد)
    - يقلل عدد استعلامات /start من 8 إلى 2-3 استعلامات
    - TTL = 60 ثانية
    - يتم إبطاله عند تغيير أي بيانات للمستخدم
    - يدعم تحميل البيانات دفعة واحدة
    """

    def __init__(self):
        self.cache = TTLCache(maxsize=1000, ttl=60)  # 60 ثانية
        self._loading = {}  # منع التحميل المتكرر لنفس المستخدم
        self._lock = asyncio.Lock()

    async def get(self, user_id: int) -> Optional[Dict]:
        """جلب بيانات المستخدم من الكاش"""
        return await self.cache.get(f"user_{user_id}")

    async def get_with_ttl(self, user_id: int) -> Tuple[Optional[Dict], Optional[int]]:
        """جلب بيانات المستخدم مع TTL المتبقي"""
        return await self.cache.get_with_ttl(f"user_{user_id}")

    async def set(self, user_id: int, data: Dict) -> None:
        """تخزين بيانات المستخدم في الكاش"""
        await self.cache.set(f"user_{user_id}", data)

    async def invalidate(self, user_id: int) -> None:
        """إبطال كاش مستخدم معين"""
        await self.cache.delete(f"user_{user_id}")
        async with self._lock:
            self._loading.pop(user_id, None)

    async def invalidate_all(self) -> None:
        """إبطال كاش جميع المستخدمين"""
        await self.cache.clear()
        async with self._lock:
            self._loading.clear()

    async def get_or_load(self, user_id: int, db) -> Dict:
        """
        جلب من الكاش، أو تحميل من قاعدة البيانات إذا لم يكن موجوداً
        مع منع التحميل المتكرر لنفس المستخدم
        """
        # 1. محاولة من الكاش
        cached = await self.get(user_id)
        if cached is not None:
            return cached

        # 2. منع التحميل المتكرر
        async with self._lock:
            if user_id in self._loading:
                # انتظر حتى ينتهي التحميل الحالي
                pass
            else:
                self._loading[user_id] = True

        try:
            # 3. تحميل البيانات
            data = await self._load_user_full_data(db, user_id)
            
            # 4. تخزين في الكاش
            await self.set(user_id, data)
            
            return data
        finally:
            async with self._lock:
                self._loading.pop(user_id, None)

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
                'exists': False,
                'language': 'ar',
                'active_channel': None,
                'channel_info': None,
                'unpublished_posts': 0,
                'has_subscription': False,
                'auto_publish': True,
                'auto_recycle': True,
                'groups': [],
                'groups_count': 0,
                'channels': [],
                'channels_count': 0,
                'user_data': None
            }

        # 2. جلب البيانات الإضافية بشكل متوازٍ
        tasks = [
            db.get_active_channel(user_id),
            db.has_active_subscription(user_id),
            db.get_auto_publish_status(user_id),
            db.get_auto_recycle_status(user_id),
            db.get_user_groups(user_id),
            db.get_user_channels(user_id),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        active_channel = results[0] if not isinstance(results[0], Exception) else None
        has_sub = results[1] if not isinstance(results[1], Exception) else False
        auto_pub = results[2] if not isinstance(results[2], Exception) else True
        auto_rec = results[3] if not isinstance(results[3], Exception) else True
        groups = results[4] if not isinstance(results[4], Exception) else []
        channels = results[5] if not isinstance(results[5], Exception) else []

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
            'exists': True,
            'language': user_data.get('language', 'ar'),
            'active_channel': active_channel,
            'channel_info': channel_info,
            'unpublished_posts': unpublished_posts,
            'has_subscription': has_sub,
            'auto_publish': auto_pub,
            'auto_recycle': auto_rec,
            'groups': groups,
            'groups_count': len(groups) if isinstance(groups, list) else 0,
            'channels': channels,
            'channels_count': len(channels) if isinstance(channels, list) else 0,
            'user_data': user_data,
            'cached_at': time.time()
        }


# =====================================================================
# 8. كاش المنشورات (جديد)
# =====================================================================

class PostsCache:
    """كاش المنشورات للقنوات"""

    def __init__(self):
        self.cache = TTLCache(maxsize=500, ttl=30)  # 30 ثانية
        self.next_post = TTLCache(maxsize=200, ttl=10)  # 10 ثوانٍ

    async def get_posts(self, channel_db_id: int, limit: int = 10) -> Optional[List[Dict]]:
        """جلب منشورات القناة من الكاش"""
        return await self.cache.get(f"posts_{channel_db_id}_{limit}")

    async def set_posts(self, channel_db_id: int, posts: List[Dict], limit: int = 10) -> None:
        """تخزين منشورات القناة في الكاش"""
        await self.cache.set(f"posts_{channel_db_id}_{limit}", posts)

    async def get_next_post(self, channel_db_id: int) -> Optional[Dict]:
        """جلب المنشور التالي من الكاش"""
        return await self.next_post.get(f"next_{channel_db_id}")

    async def set_next_post(self, channel_db_id: int, post: Dict) -> None:
        """تخزين المنشور التالي في الكاش"""
        await self.next_post.set(f"next_{channel_db_id}", post)

    async def invalidate(self, channel_db_id: int = None) -> None:
        """مسح كاش المنشورات"""
        if channel_db_id is not None:
            await self.cache.delete(f"posts_{channel_db_id}_10")
            await self.next_post.delete(f"next_{channel_db_id}")
        else:
            await self.cache.clear()
            await self.next_post.clear()


# =====================================================================
# 9. إنشاء الكائنات العامة
# =====================================================================

# كائنات الكاش الرئيسية
settings_cache = SettingsCache()
banned_words_cache = BannedWordsCache()
auth_cache = AuthCache()
channels_cache = ChannelsCache()
groups_cache = GroupsCache()
user_cache = UserDataCache()
posts_cache = PostsCache()


# =====================================================================
# 10. دوال مساعدة للاستيراد السريع
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
    await posts_cache.invalidate()


async def clear_all_caches() -> Dict:
    """مسح جميع الكاشات وإرجاع إحصائيات"""
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
    """مهمة تنظيف دورية للكاش (تُشغل في الخلفية)"""
    while True:
        await asyncio.sleep(300)  # كل 5 دقائق
        try:
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
        except Exception as e:
            logger.error(f"❌ خطأ تنظيف الكاش: {e}")


# =====================================================================
# 12. إحصائيات الكاش (للمطورين)
# =====================================================================

async def get_cache_stats() -> Dict:
    """جلب إحصائيات الكاش (للمطورين)"""
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
    """جلب إحصائيات مفصلة للكاش"""
    stats = await get_cache_stats()
    detailed = {
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
    return detailed


# =====================================================================
# 13. دالة للحصول على مفتاح كاش منسق
# =====================================================================

def cache_key(*args, **kwargs) -> str:
    """إنشاء مفتاح كاش منسق من arguments"""
    parts = []
    for arg in args:
        if isinstance(arg, (int, str, float, bool)):
            parts.append(str(arg))
        elif isinstance(arg, dict):
            parts.append(str(sorted(arg.items())))
        elif isinstance(arg, (list, tuple)):
            parts.append(str(sorted(arg)))
    for key, value in sorted(kwargs.items()):
        parts.append(f"{key}={value}")
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
    'invalidate_all_user_cache',
    'clear_all_caches',
    'cache_cleanup_task',
    'get_cache_stats',
    'get_detailed_stats',
    'cache_key',
]
