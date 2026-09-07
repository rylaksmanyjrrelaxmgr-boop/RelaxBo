#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
cache.py - نظام الكاش الموحد للبوت (نسخة محسّنة)
=================================================
- كاش منفصل لكل نوع بيانات
- كاش شامل للمستخدم (UserDataCache) لتسريع /start
- TTL مختلف لكل نوع
- تنظيف تلقائي دوري
- تحديث تلقائي عند تغيير البيانات
"""

import asyncio
import time
import logging
from collections import OrderedDict
from typing import Any, Optional, Dict

logger = logging.getLogger(__name__)


class TTLCache:
    """كاش TTL مع حد أقصى للحجم"""

    def __init__(self, maxsize: int = 100, ttl: int = 60):
        self.maxsize = maxsize
        self.ttl = ttl
        self._cache = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        """جلب قيمة من الكاش"""
        async with self._lock:
            if key not in self._cache:
                return None
            value, timestamp = self._cache[key]
            if time.time() - timestamp > self.ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return value

    async def set(self, key: str, value: Any, ttl: int = None) -> None:
        """تخزين قيمة في الكاش"""
        effective_ttl = ttl if ttl is not None else self.ttl
        async with self._lock:
            self._cache[key] = (value, time.time())
            self._cache.move_to_end(key)
            self._cleanup_locked()

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

    def _cleanup_locked(self) -> None:
        """تنظيف داخلي بدون قفل (يُستدعى داخل set)"""
        now = time.time()
        expired = [k for k, (_, ts) in self._cache.items() if now - ts > self.ttl]
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
        key = f"sec_{chat_id}"
        return await self.security.get(key)

    async def set_security(self, chat_id: int, settings: Dict):
        key = f"sec_{chat_id}"
        await self.security.set(key, settings)

    async def invalidate_security(self, chat_id: int = None):
        if chat_id is not None:
            await self.security.delete(f"sec_{chat_id}")
        else:
            await self.security.clear()

    async def get_auto_reply_settings(self, chat_id: int):
        key = f"ars_{chat_id}"
        return await self.auto_reply.get(key)

    async def set_auto_reply_settings(self, chat_id: int, settings: Dict):
        key = f"ars_{chat_id}"
        await self.auto_reply.set(key, settings)

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
        key = f"bw_{chat_id}"
        return await self.cache.get(key)

    async def set(self, chat_id: int, words: list):
        key = f"bw_{chat_id}"
        await self.cache.set(key, words)

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
        self.cache = TTLCache(maxsize=2000, ttl=15)

    async def get(self, chat_id: int, user_id: int):
        key = f"auth_{chat_id}_{user_id}"
        return await self.cache.get(key)

    async def set(self, chat_id: int, user_id: int, authorized: bool):
        key = f"auth_{chat_id}_{user_id}"
        await self.cache.set(key, authorized)

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
# ✅ كاش المستخدم الشامل (المحسّن)
# =====================================================================

class UserDataCache:
    """
    كاش شامل لبيانات المستخدم (جميع المعلومات في كائن واحد)
    - يقلل عدد استعلامات /start من 8 إلى 1
    - TTL = 30 ثانية (يتجدد تلقائياً)
    - يتم إبطاله عند تغيير أي بيانات للمستخدم
    """

    def __init__(self):
        self.cache = TTLCache(maxsize=500, ttl=30)

    async def get(self, user_id: int) -> Optional[Dict]:
        """جلب بيانات المستخدم من الكاش"""
        key = f"user_{user_id}"
        return await self.cache.get(key)

    async def set(self, user_id: int, data: Dict) -> None:
        """تخزين بيانات المستخدم في الكاش"""
        key = f"user_{user_id}"
        await self.cache.set(key, data)

    async def invalidate(self, user_id: int) -> None:
        """إبطال كاش مستخدم معين (يُستدعى عند تغيير بياناته)"""
        key = f"user_{user_id}"
        await self.cache.delete(key)

    async def invalidate_all(self) -> None:
        """إبطال كاش جميع المستخدمين (نادر الاستخدام)"""
        await self.cache.clear()

    async def get_or_load(self, user_id: int, db) -> Dict:
        """جلب من الكاش، أو تحميل من قاعدة البيانات إذا لم يكن موجوداً"""
        cached = await self.get(user_id)
        if cached is not None:
            return cached

        # تحميل جميع البيانات دفعة واحدة
        data = await self._load_user_data(db, user_id)
        await self.set(user_id, data)
        return data

    async def _load_user_data(self, db, user_id: int) -> Dict:
        """
        تحميل جميع بيانات المستخدم في استعلامات متوازية
        باستخدام asyncio.gather
        """
        # تشغيل الاستعلامات بشكل متوازٍ
        results = await asyncio.gather(
            db.get_user_language(user_id),
            db.get_active_channel(user_id),
            db.has_active_subscription(user_id),
            db.get_auto_publish_status(user_id),
            db.get_auto_recycle_status(user_id),
            db.get_user_groups(user_id),
            return_exceptions=True
        )

        # تفريغ النتائج مع معالجة الأخطاء
        lang, active_channel, has_sub, auto_pub, auto_rec, groups = results

        if isinstance(lang, Exception):
            lang = 'ar'
        if isinstance(active_channel, Exception):
            active_channel = None
        if isinstance(has_sub, Exception):
            has_sub = False
        if isinstance(auto_pub, Exception):
            auto_pub = True
        if isinstance(auto_rec, Exception):
            auto_rec = True
        if isinstance(groups, Exception):
            groups = []

        # جلب معلومات القناة النشطة (إذا وجدت)
        channel_info = None
        unpublished_posts = 0
        if active_channel:
            try:
                channel_info = await db.get_channel_info(user_id, active_channel)
                if channel_info:
                    unpublished_posts = await db.get_unpublished_posts_count(user_id, active_channel)
            except Exception:
                pass

        # بناء كائن البيانات
        return {
            'language': lang,
            'active_channel': active_channel,
            'channel_info': channel_info,
            'unpublished_posts': unpublished_posts,
            'has_subscription': has_sub,
            'auto_publish': auto_pub,
            'auto_recycle': auto_rec,
            'groups': groups,
            'groups_count': len(groups) if isinstance(groups, list) else 0
        }


# ============ إنشاء الكائنات العامة ============

settings_cache = SettingsCache()
banned_words_cache = BannedWordsCache()
auth_cache = AuthCache()
user_cache = UserDataCache()  # ✅ الكاش الجديد للمستخدمين


# =====================================================================
# دوال مساعدة للاستيراد السريع
# =====================================================================

async def invalidate_user_cache(user_id: int) -> None:
    """إبطال كاش مستخدم معين (دالة مساعدة)"""
    await user_cache.invalidate(user_id)


async def invalidate_all_user_cache() -> None:
    """إبطال كاش جميع المستخدمين (دالة مساعدة)"""
    await user_cache.invalidate_all()


# =====================================================================
# مهمة التنظيف الدورية
# =====================================================================

async def cache_cleanup_task():
    """مهمة تنظيف دورية للكاش (تُشغل في الخلفية)"""
    while True:
        await asyncio.sleep(300)  # كل 5 دقائق
        try:
            c1 = await settings_cache.security.cleanup()
            c2 = await settings_cache.auto_reply.cleanup()
            c3 = await banned_words_cache.cache.cleanup()
            c4 = await auth_cache.cache.cleanup()
            c5 = await user_cache.cache.cleanup()
            total = c1 + c2 + c3 + c4 + c5
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
        'user': len(user_cache.cache._cache),
        'total': (
            len(settings_cache.security._cache) +
            len(settings_cache.auto_reply._cache) +
            len(banned_words_cache.cache._cache) +
            len(auth_cache.cache._cache) +
            len(user_cache.cache._cache)
        )
    }