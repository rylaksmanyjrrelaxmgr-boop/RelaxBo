#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_caches.py - Caches المُستخرجة من database.py (v1.0.0)
================================================================================
🎯 الهدف:
    فصل تعريفات الـ Caches من database.py لتقليل حجمه،
    وتمكين cache.py من الاستيراد المباشر بدون اعتماد دائري محتمل.

📦 المحتوى:
    - InternalQueryCache  : كاش داخلي للاستعلامات (ttl/max_size)
    - SimpleCache         : كاش async عام مع LRU eviction بسيط
    - SettingsCache       : SimpleCache بـ ttl أطول (600s افتراضي)
    - internal_cache      : كائن عالمي جاهز من InternalQueryCache

🎯 التكامل مع database.py:
    1) احذف تعريفات InternalQueryCache / SimpleCache / SettingsCache
       + السطر: internal_cache = InternalQueryCache(ttl=30, max_size=10000)

    2) استبدلها بـ:
        from database_caches import (
            InternalQueryCache,
            SimpleCache,
            SettingsCache,
            internal_cache,
        )

    3) database.py يحتفظ بـ re-export تلقائي (الأسماء في النطاق)
       → `from database import SimpleCache` سيبقى يعمل (backward-compat).

🎯 التكامل مع cache.py:
    - إذا كان cache.py يستورد:
        from database import SimpleCache, SettingsCache
      فيعمل تلقائياً (b/c database.py يمرّر الأسماء).

    - للأنظف (اختياري، لاحقاً): غيّر إلى:
        from database_caches import SimpleCache, SettingsCache
      → يُزيل الاعتماد على database.py من cache.py.

⚠️ ملاحظة مهمة:
    - هذا الملف لا يستورد أي شيء من database.py أو cache.py
      → لا circular imports إطلاقاً.
    - الاعتماد الوحيد: asyncio, time, logging, typing (stdlib فقط).
================================================================================
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Tuple, Union

logger = logging.getLogger(__name__)


# =====================================================================
# 1) InternalQueryCache — كاش داخلي للاستعلامات المتكررة
# =====================================================================

class InternalQueryCache:
    """
    🗃️ كاش بسيط async لنتائج استعلامات database الداخلية.

    الميزات:
      • TTL افتراضي: 30s (يُضبط عند الإنشاء)
      • max_size: 10000 entry (يُضبط عند الإنشاء)
      • عند الوصول للحد: يُزيل 25% (الأقدم إدراجاً)
      • eviction lock لتفادي سباق إعادة الإدراج المتزامن

    ملاحظات:
      - لا lock على get/set العاديين (لأن asyncio single-thread).
      - الـ lock يُستخدم فقط أثناء eviction لتفادي تسابق
        عدّة coroutines على نفس الـ batch.

    الاستخدام:
        cache = InternalQueryCache(ttl=30, max_size=10000)
        await cache.set("user_123", {"name": "..."})
        val = await cache.get("user_123")
    """

    def __init__(self, ttl: int = 60, max_size: int = 10000):
        self._cache: Dict[str, Tuple[Any, float, int]] = {}
        self._ttl = ttl
        self._max_size = max_size
        self._eviction_lock = asyncio.Lock()

    async def get(self, key: str):
        """
        يُرجع القيمة إن كانت صالحة، أو None إن:
          • المفتاح غير موجود
          • المفتاح انتهى (TTL) — ويُحذف تلقائياً
        """
        entry = self._cache.get(key)
        if entry is not None:
            data, timestamp, ttl = entry
            if time.monotonic() - timestamp < ttl:
                return data
            # انتهى → احذف فوري
            self._cache.pop(key, None)
        return None

    async def set(self, key: str, data, ttl: int = None):
        """
        يُخزّن القيمة.

        Args:
            key: مفتاح str
            data: القيمة (أي نوع)
            ttl: TTL مخصص (بالثواني) — إن None، يُستخدم self._ttl
        """
        effective_ttl = ttl if ttl is not None else self._ttl

        # eviction إن امتلأ الكاش
        if len(self._cache) >= self._max_size and key not in self._cache:
            async with self._eviction_lock:
                # إعادة فحص (قد يكون coroutine آخر أزال مفاتيح)
                if len(self._cache) >= self._max_size:
                    to_remove = list(self._cache.keys())[
                        : max(1, self._max_size // 4)
                    ]
                    for k in to_remove:
                        self._cache.pop(k, None)

        self._cache[key] = (data, time.monotonic(), effective_ttl)

    async def invalidate(self, key: str = None):
        """
        إبطال مفتاح واحد، أو كل المفاتيح إن كان key=None (أو "").
        """
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    async def clear(self):
        """إبطال كل الكاش — مرادف لـ invalidate(None)."""
        self._cache.clear()

    async def get_size(self) -> int:
        """
        عدد المفاتيح الحالية (يشمل المنتهية — لا يُصفّي).

        للعدد الصافي بعد التنظيف، استخدم:
            keys = await cache.get_keys()  # لكن Internal لا يوفرها
        عملياً: العدد دقيق بما يكفي للمراقبة.
        """
        return len(self._cache)


# =====================================================================
# 2) SimpleCache — كاش async عام بمفاتيح str/int
# =====================================================================

class SimpleCache:
    """
    💾 كاش async عام بمفاتيح `str` أو `int`.

    الميزات:
      • TTL per-key (قابل للتجاوز عند set)
      • max_size مع LRU eviction بسيط (يُزيل 25% عند الوصول للحد)
      • asyncio.Lock لحماية القاموس من سباقات القراءة/الكتابة
      • دوال مساعدة:
          - has(key) → bool
          - get_with_ttl(key) → (data, remaining)
          - set_many(items, ttl)
          - delete_many(keys) → int
          - get_keys() → List
          - get_all() → Dict (يُصفّي المنتهية)
          - get_stats() → Dict

    الاستخدام:
        cache = SimpleCache(default_ttl=60, max_size=10000)
        await cache.set("user_1", {"name": "ali"})
        user = await cache.get("user_1")
    """

    def __init__(self, default_ttl: int = 60, max_size: int = 10000):
        self._cache: Dict[
            Union[str, int], Tuple[Any, float, int]
        ] = {}
        self._ttl = default_ttl
        self._max_size = max_size
        self._lock = asyncio.Lock()

    async def get(self, key):
        """يُرجع القيمة أو None (يحذف المنتهية تلقائياً)."""
        async with self._lock:
            if key in self._cache:
                data, ts, ttl = self._cache[key]
                if time.monotonic() - ts < ttl:
                    return data
                del self._cache[key]
            return None

    async def set(self, key, data, ttl: int = None):
        """يُخزّن القيمة مع TTL اختياري."""
        effective = ttl if ttl is not None else self._ttl
        async with self._lock:
            if (len(self._cache) >= self._max_size
                    and key not in self._cache):
                to_remove = list(self._cache.keys())[
                    : max(1, self._max_size // 4)
                ]
                for k in to_remove:
                    self._cache.pop(k, None)
            self._cache[key] = (data, time.monotonic(), effective)

    async def invalidate(self, key=None):
        """إبطال مفتاح واحد أو الكل."""
        async with self._lock:
            if key is not None:
                self._cache.pop(key, None)
            else:
                self._cache.clear()

    async def clear(self):
        """إبطال كل الكاش."""
        async with self._lock:
            self._cache.clear()

    async def has(self, key) -> bool:
        """هل المفتاح موجود وصالح؟ (يحذف المنتهية)."""
        async with self._lock:
            if key in self._cache:
                _, ts, ttl = self._cache[key]
                if time.monotonic() - ts < ttl:
                    return True
                del self._cache[key]
            return False

    async def get_with_ttl(self, key):
        """
        يُرجع tuple: (data, ttl_remaining_seconds) أو (None, None).
        """
        async with self._lock:
            if key in self._cache:
                data, ts, ttl = self._cache[key]
                remaining = int(ttl - (time.monotonic() - ts))
                if remaining > 0:
                    return data, remaining
                del self._cache[key]
            return None, None

    async def set_many(
        self, items: Dict[Any, Any], ttl: int = None
    ):
        """يُخزّن مجموعة قيم دفعة واحدة (نفس TTL للكل)."""
        effective = ttl if ttl is not None else self._ttl
        async with self._lock:
            now = time.monotonic()
            for key, data in items.items():
                if (len(self._cache) >= self._max_size
                        and key not in self._cache):
                    to_remove = list(self._cache.keys())[
                        : max(1, self._max_size // 4)
                    ]
                    for k in to_remove:
                        self._cache.pop(k, None)
                self._cache[key] = (data, now, effective)

    async def delete_many(self, keys: List[Any]) -> int:
        """يحذف مجموعة مفاتيح. يعدّ المحذوفات فعلياً."""
        async with self._lock:
            count = 0
            for key in keys:
                if key in self._cache:
                    del self._cache[key]
                    count += 1
            return count

    async def get_keys(self) -> List[Any]:
        """
        قائمة بكل المفاتيح (بما فيها المنتهية — لا يُصفّي).

        ملاحظة: cache_cleanup_task في cache.py يستخدمها
        ثم يستدعي has() لكل مفتاح لتصفية المنتهية.
        """
        async with self._lock:
            return list(self._cache.keys())

    async def get_all(self) -> Dict[Any, Any]:
        """قاموس بكل المفاتيح الصالحة (يُصفّي المنتهية)."""
        async with self._lock:
            now = time.monotonic()
            return {
                k: v[0] for k, v in self._cache.items()
                if now - v[1] < v[2]
            }

    async def get_stats(self) -> Dict[str, Any]:
        """إحصائيات الكاش (الحجم الحالي + الحد + TTL)."""
        async with self._lock:
            return {
                'size': len(self._cache),
                'max_size': self._max_size,
                'ttl': self._ttl,
            }


# =====================================================================
# 3) SettingsCache — SimpleCache بـ ttl أطول
# =====================================================================

class SettingsCache(SimpleCache):
    """
    ⚙️ كاش إعدادات بـ ttl أطول (600s افتراضي).

    لا يُضيف أي منطق جديد — subclass فقط للتمييز المعنوي
    عن SimpleCache العامة (يسهّل القراءة والفهم لاحقاً).

    الاستخدام المتوقع في cache.py:
        settings_cache = SettingsCache(default_ttl=600)
    """
    pass


# =====================================================================
# 4) كائن عالمي جاهز — internal_cache
# =====================================================================
# يُستخدَم في database.py:
#   • _invalidate_user_cache_keys() → لتخزين نتائج استعلامات المستخدم
#   • _user_cache_invalidate_wrapper → لتحديث الكاش عند تغيير المستخدم
#
# الإعدادات: ttl=30s, max_size=10000
#   → يغطّي ~10K مستخدم نشط، ويُجدّد كل 30s تلقائياً.

internal_cache = InternalQueryCache(ttl=30, max_size=10000)


# =====================================================================
# 5) __all__
# =====================================================================

__all__ = [
    "InternalQueryCache",
    "SimpleCache",
    "SettingsCache",
    "internal_cache",
]