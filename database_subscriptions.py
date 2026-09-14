#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_subscriptions.py — v7.5.1
=================================================================================
إصلاحات v7.5.1 (فوق v7.5):
- ✅ PERF #1: _MemoryBackend.mget بلا await لكل مفتاح (توفير ~500 context switches
  في batch_has_active_subscription عند chunk=500 في وضع Memory backend)
  — لا تغيير سلوكي، لا تغيير واجهة.

إصلاحات v7.5 (فوق v7.4):
- ✅ FIX #W: عدم تصفير _init_lock في close() (إزالة سباق close() متعدد نهائياً)
- ✅ FIX #X: Redis pipeline في _RedisBackend.mset (كتابة دفعة واحدة)
- ✅ FIX #Y: _MemoryBackend.mset للاتساق وتماثل الواجهة
- ✅ FIX #Z: _SubscriptionCache.mset_batch (واجهة موحّدة)
- ✅ FIX #AA: batch_has_active_subscription يستخدم mset_batch (1 round-trip)
- ✅ FIX #AB: إضافة mset إلى واجهة _CacheBackend المجرّدة

محفوظ من v7.4:
- ✅ FIX #R..#V (راجع سجل v7.4)
محفوظ من v7.3:
- ✅ FIX #K..#Q (راجع سجل v7.3)
محفوظ من v7.2:
- ✅ FIX #A..#J (راجع سجل v7.2)
محفوظ من v7.1:
- ✅ FIX #1..#11 (راجع سجل v7.1)
محفوظ من v5/v6:
- CAS على subscriptions، token ذرّي في الإحالات، rollback للتجربة
- Circuit breaker لـ SQLite، Retry مع jitter
"""

import asyncio
import inspect
import json
import logging
import math
import os
import random
import secrets
import sqlite3
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Callable, Awaitable, Any, Iterable

from database import DB, TimeUtils

logger = logging.getLogger(__name__)


# =====================================================================
# 0. أدوات مساعدة
# =====================================================================

def _row_get(row, key, default=None):
    if row is None:
        return default
    try:
        if isinstance(row, dict):
            return row.get(key, default)
        value = row[key]
        return value if value is not None else default
    except (KeyError, IndexError, TypeError):
        return default


def _rowcount(result) -> int:
    try:
        if result is not None and hasattr(result, 'rowcount'):
            rc = result.rowcount
            if rc is None:
                return 0
            try:
                rc = int(rc)
            except (ValueError, TypeError):
                return 0
            return rc if rc >= 0 else 0
    except Exception:
        pass
    return 0


def _to_dt(s: Optional[Any]) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, datetime):
        dt = s
    else:
        try:
            text = str(s).strip()
            if text.endswith('Z') or text.endswith('z'):
                text = text[:-1] + '+00:00'
            text = text.replace(' ', 'T', 1)
            dt = datetime.fromisoformat(text)
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _utc_now() -> datetime:
    try:
        now = TimeUtils.utc_now()
        if isinstance(now, datetime):
            return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return datetime.now(timezone.utc)


def _days_left_ceil(expires: datetime, now: datetime) -> int:
    secs = (expires - now).total_seconds()
    if secs <= 0:
        return 0
    return max(1, math.ceil(secs / 86400))


async def _maybe_aclose(obj) -> None:
    """
    ✅ FIX #A/#B: إغلاق موحّد يدعم aclose/close sync/async.
    ✅ FIX #L: inspect.isawaitable أدقّ من asyncio.iscoroutine (يغطي Future/Task).
    ✅ FIX #T: logger.debug عند الفشل لتحسين التشخيص.
    """
    if obj is None:
        return
    try:
        close_fn = getattr(obj, 'aclose', None) or getattr(obj, 'close', None)
        if close_fn is None:
            return
        result = close_fn()
        if inspect.isawaitable(result):
            await result
    except Exception as e:
        logger.debug(f"⚠️ _maybe_aclose فشل ({type(obj).__name__}): {e}")


# =====================================================================
# 0.1 Circuit Breaker (SQLite)
# =====================================================================

class _CircuitBreaker:
    FAIL_THRESHOLD = 5
    COOLDOWN_SEC = 5.0

    def __init__(self):
        self._fails = 0
        self._opened_at = 0.0

    def allow(self) -> bool:
        if self._opened_at == 0.0:
            return True
        if (time.monotonic() - self._opened_at) >= self.COOLDOWN_SEC:
            self._opened_at = 0.0
            self._fails = 0
            return True
        return False

    def on_success(self):
        self._fails = 0
        self._opened_at = 0.0

    def on_failure(self):
        self._fails += 1
        if self._fails >= self.FAIL_THRESHOLD:
            self._opened_at = time.monotonic()
            logger.warning(
                f"🔴 Circuit Breaker فُتح بعد {self._fails} أخطاء "
                f"لمدة {self.COOLDOWN_SEC}s"
            )


_CB = _CircuitBreaker()


async def _with_retry(
    factory: Callable[[], Awaitable[Any]],
    attempts: int = 4,
    base_delay: float = 0.05,
):
    if not _CB.allow():
        raise sqlite3.OperationalError("circuit breaker open (db unstable)")

    last_err: Optional[Exception] = None
    for i in range(attempts):
        try:
            result = await factory()
            _CB.on_success()
            return result
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            is_transient = isinstance(e, sqlite3.Error) and (
                'locked' in msg or 'busy' in msg
            )
            if not is_transient or i == attempts - 1:
                if isinstance(e, sqlite3.Error):
                    _CB.on_failure()
                raise
            delay = base_delay * (2 ** i) + random.uniform(0, base_delay)
            await asyncio.sleep(delay)
    if last_err:
        raise last_err


# =====================================================================
# 0.2 Cache Layer (Memory + Redis) — v7.5.1
# =====================================================================

try:
    import redis.asyncio as aioredis
    from redis.asyncio.retry import Retry
    from redis.backoff import ExponentialBackoff
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import TimeoutError as RedisTimeoutError
    _HAS_REDIS = True
except ImportError:
    aioredis = None
    Retry = None
    ExponentialBackoff = None
    RedisConnectionError = None
    RedisTimeoutError = None
    _HAS_REDIS = False


try:
    from config import CONFIG
    _CONFIG_REDIS_URL = getattr(CONFIG, 'REDIS_URL', None)
    _CONFIG_CACHE_TTL = getattr(CONFIG, 'CACHE_TTL', None)
except Exception:
    _CONFIG_REDIS_URL = None
    _CONFIG_CACHE_TTL = None


def _resolve_redis_url() -> Optional[str]:
    return os.getenv('REDIS_URL') or _CONFIG_REDIS_URL or None


def _resolve_cache_ttl() -> float:
    # ✅ FIX #9: TTL من ENV/CONFIG
    env = os.getenv('CACHE_TTL')
    if env:
        try:
            return max(0.5, float(env))
        except (ValueError, TypeError):
            pass
    if _CONFIG_CACHE_TTL is not None:
        try:
            return max(0.5, float(_CONFIG_CACHE_TTL))
        except (ValueError, TypeError):
            pass
    return 5.0


# ─── Backend interface ───

class _CacheBackend:
    async def get(self, key: str) -> Optional[Dict]: ...
    async def mget(self, keys: List[str]) -> List[Optional[Dict]]: ...
    async def set(self, key: str, payload: Dict, ttl: float) -> None: ...
    # ✅ FIX #AB: إضافة mset إلى الواجهة المجرّدة
    async def mset(self, items: Dict[str, Dict], ttl: float) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...


class _MemoryBackend(_CacheBackend):
    def __init__(self, max_size: int = 10_000):
        self.max_size = max_size
        self._store: "OrderedDict[str, tuple[float, Dict]]" = OrderedDict()

    async def get(self, key):
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, payload = entry
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return payload

    # ✅ PERF #1: بلا await لكل مفتاح — حلقة sync واحدة داخل coroutine واحد
    #     نفس السلوك تماماً (نفس TTL، نفس LRU، نفس النتائج) لكن أسرع بكثير
    #     عند استدعائه بـ 500 مفتاح في batch_has_active_subscription.
    async def mget(self, keys):
        if not keys:
            return []
        now = time.monotonic()
        store = self._store
        out: List[Optional[Dict]] = []
        for k in keys:
            entry = store.get(k)
            if entry is None:
                out.append(None)
                continue
            expires_at, payload = entry
            if now >= expires_at:
                store.pop(k, None)
                out.append(None)
                continue
            store.move_to_end(k)
            out.append(payload)
        return out

    async def set(self, key, payload, ttl):
        self._store[key] = (time.monotonic() + ttl, payload)
        self._store.move_to_end(key)
        if len(self._store) > self.max_size:
            self._store.popitem(last=False)

    # ✅ FIX #Y: mset للاتساق مع Redis
    async def mset(self, items, ttl):
        if not items:
            return
        now_m = time.monotonic() + ttl
        for key, payload in items.items():
            self._store[key] = (now_m, payload)
            self._store.move_to_end(key)
        # فرض حجم LRU (قد نحذف عدة عناصر إذا أضفنا دفعة كبيرة)
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)

    async def delete(self, key):
        self._store.pop(key, None)

    async def flush(self):
        self._store.clear()

    async def close(self):
        self._store.clear()


class _RedisBackend(_CacheBackend):
    def __init__(self, client, prefix: str = "subs:cache:"):
        self._client = client
        self._prefix = prefix
        self._cb = _CircuitBreaker()

    def _k(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def get(self, key):
        if not self._cb.allow():
            return None
        try:
            raw = await self._client.get(self._k(key))
            self._cb.on_success()
            return json.loads(raw) if raw else None
        except Exception as e:
            self._cb.on_failure()
            logger.debug(f"⚠️ Redis GET فشل: {e}")
            return None

    # ✅ FIX #2: MGET — رحلة واحدة لعدة مفاتيح
    async def mget(self, keys):
        if not keys:
            return []
        if not self._cb.allow():
            return [None] * len(keys)
        try:
            full = [self._k(k) for k in keys]
            values = await self._client.mget(full)
            self._cb.on_success()
            out: List[Optional[Dict]] = []
            for v in values:
                if v is None:
                    out.append(None)
                else:
                    try:
                        out.append(json.loads(v))
                    except (json.JSONDecodeError, TypeError):
                        out.append(None)
            return out
        except Exception as e:
            self._cb.on_failure()
            logger.debug(f"⚠️ Redis MGET فشل: {e}")
            return [None] * len(keys)

    async def set(self, key, payload, ttl):
        if not self._cb.allow():
            return
        try:
            await self._client.set(
                self._k(key),
                json.dumps(payload, default=str, ensure_ascii=False),
                ex=max(1, int(ttl)),
            )
            self._cb.on_success()
        except Exception as e:
            self._cb.on_failure()
            logger.debug(f"⚠️ Redis SET فشل: {e}")

    # ✅ FIX #X: mset عبر pipeline — رحلة واحدة لعدة كتابات
    async def mset(self, items, ttl):
        if not items:
            return
        if not self._cb.allow():
            return
        try:
            ex_seconds = max(1, int(ttl))
            async with self._client.pipeline(transaction=False) as pipe:
                for key, payload in items.items():
                    pipe.set(
                        self._k(key),
                        json.dumps(payload, default=str, ensure_ascii=False),
                        ex=ex_seconds,
                    )
                await pipe.execute()
            self._cb.on_success()
        except Exception as e:
            self._cb.on_failure()
            logger.debug(f"⚠️ Redis MSET فشل: {e}")

    async def delete(self, key):
        if not self._cb.allow():
            return
        try:
            await self._client.delete(self._k(key))
            self._cb.on_success()
        except Exception as e:
            self._cb.on_failure()
            logger.debug(f"⚠️ Redis DEL فشل: {e}")

    async def flush(self):
        if not self._cb.allow():
            return
        try:
            pattern = f"{self._prefix}*"
            # ✅ FIX #10: SCAN مع count لتحسين الأداء
            async for k in self._client.scan_iter(match=pattern, count=1000):
                try:
                    await self._client.delete(k)
                except Exception:
                    pass
            self._cb.on_success()
        except Exception as e:
            self._cb.on_failure()
            logger.warning(f"⚠️ Redis FLUSH فشل: {e}")

    async def close(self):
        pass  # الـ client يُغلق من _SubscriptionCache


class _SubscriptionCache:
    """
    واجهة كاش موحّدة. تختار Memory أو Redis حسب REDIS_URL.

    ⚠️ FIX #6: `invalidate` و `clear` **async**.
       المستدعون القدامى (v6) يجب أن يضيفوا `await`.
    """

    INVALIDATE_CHANNEL = "subs:cache:invalidate"

    def __init__(self, ttl: float = 5.0, max_size: int = 10_000):
        self.ttl = ttl
        self.max_size = max_size
        self._backend: _CacheBackend = _MemoryBackend(max_size)
        self._mode: str = 'memory'
        self.hits = 0
        self.misses = 0
        self._redis: Optional[Any] = None
        self._pubsub_task: Optional[asyncio.Task] = None
        # ✅ FIX #I: حفظ الرابط لإعادة الاتصال المستقبلي
        # ✅ FIX #U: reserved for future use (لا يوجد مستهلك حالياً)
        self._redis_url: Optional[str] = None

        # ✅ FIX #1 + #4: لا نُنشئ primitives هنا — تُنشأ في init()
        self._subscriber_ready: Optional[asyncio.Event] = None
        # ✅ FIX #W: _init_lock يبقى طوال حياة الكائن — لا يُصفَّر
        self._init_lock: Optional[asyncio.Lock] = None
        self._initialized: bool = False

    @property
    def mode(self) -> str:
        return self._mode

    async def init(self, redis_url: Optional[str] = None) -> None:
        """يُنادى مرة واحدة من startup. idempotent."""
        # ✅ FIX #1: إنشاء primitives داخل loop الفعلي
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            # ✅ FIX #4: idempotent
            if self._initialized:
                logger.debug("🧠 Cache مُهيأ مسبقاً — تخطي")
                return

            redis_url = redis_url or _resolve_redis_url()

            if not redis_url:
                logger.info("🧠 Cache: Memory backend (لا يوجد REDIS_URL)")
                self._initialized = True
                return

            if not _HAS_REDIS:
                logger.warning(
                    "⚠️ REDIS_URL موجود لكن مكتبة `redis` غير مثبتة → Memory. "
                    "ثبّتها: pip install 'redis>=4.2'"
                )
                self._initialized = True
                return

            client = None
            try:
                # ✅ FIX #7: Retry صريح
                retry = Retry(
                    ExponentialBackoff(cap=2.0, base=0.1),
                    retries=2,
                )
                client = aioredis.from_url(
                    redis_url,
                    encoding='utf-8',
                    decode_responses=True,
                    socket_connect_timeout=2.0,
                    socket_timeout=2.0,
                    socket_keepalive=True,          # ✅ FIX #8
                    health_check_interval=30,
                    retry_on_timeout=True,
                    retry=retry,                    # ✅ FIX #7
                    retry_on_error=[RedisConnectionError, RedisTimeoutError]
                    if RedisConnectionError else None,
                )
                await client.ping()
            except Exception as e:
                # ✅ FIX #A: إغلاق client عند فشل الاتصال لمنع تسريب ConnectionPool
                await _maybe_aclose(client)
                logger.warning(f"⚠️ تعذّر الاتصال بـ Redis ({e}) → Memory fallback")
                self._initialized = True
                return

            self._redis = client
            self._redis_url = redis_url  # ✅ FIX #I
            self._backend = _RedisBackend(client, prefix="subs:cache:")
            self._mode = 'redis'
            self._subscriber_ready = asyncio.Event()  # ✅ داخل loop

            self._pubsub_task = asyncio.create_task(
                self._listen_invalidations(), name="subs_cache_pubsub"
            )
            try:
                await asyncio.wait_for(self._subscriber_ready.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.debug("⏳ Pub/Sub لم يستجب خلال 2s (سيكمل بالخلفية)")

            self._initialized = True
            safe_url = redis_url.split('@')[-1] if '@' in redis_url else redis_url
            logger.info(f"🚀 Cache: Redis backend متصل ({safe_url})")

    # ✅ FIX #3: حلقة reconnect مع backoff
    # ✅ FIX #B: إغلاق pubsub قبل إعادة المحاولة
    # ✅ FIX #K: منع hot loop في الفرع else
    # ✅ FIX #M: حماية صريحة ضد _redis=None
    # ✅ FIX #N: unsubscribe موحّد في كل الفروع
    # ✅ FIX #S: حماية التنظيف من إعادة الإلغاء
    async def _listen_invalidations(self):
        backoff = 1.0
        while True:
            # ✅ FIX #M: خروج نظيف إذا أُغلق الـ client
            if self._redis is None:
                logger.debug("⏹️ _listen_invalidations: _redis=None، إنهاء")
                return

            pubsub = None
            try:
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(self.INVALIDATE_CHANNEL)
                if self._subscriber_ready and not self._subscriber_ready.is_set():
                    self._subscriber_ready.set()
                backoff = 1.0

                async for msg in pubsub.listen():
                    if msg.get('type') != 'message':
                        continue
                    data = msg.get('data')
                    if data == '*':
                        await self._backend.flush()
                    elif data:
                        try:
                            await self._backend.delete(str(int(data)))
                        except (ValueError, TypeError):
                            pass
            except asyncio.CancelledError:
                # ✅ FIX #B/#N: تنظيف موحّد قبل الخروج
                # ✅ FIX #S: حماية التنظيف من إعادة الإلغاء
                try:
                    await self._cleanup_pubsub(pubsub)
                except (asyncio.CancelledError, Exception):
                    pass
                raise
            except Exception as e:
                # ✅ FIX #B/#N: تنظيف موحّد قبل إعادة المحاولة
                await self._cleanup_pubsub(pubsub)
                pubsub = None
                logger.warning(f"⚠️ Pub/Sub انقطع، إعادة بعد {backoff:.1f}s: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            else:
                # ✅ FIX #V: defensive — listen() نادراً ما ينتهي بنجاح
                # (لا ينتهي إلا بـ unsubscribe+close من الخارج، وهو غير مطبَّق)
                # ✅ FIX #K/#N: تنظيف + sleep قصير لمنع hot loop
                await self._cleanup_pubsub(pubsub)
                await asyncio.sleep(0.5)

    async def _cleanup_pubsub(self, pubsub) -> None:
        """✅ FIX #N: إلغاء الاشتراك + إغلاق pubsub بشكل موحّد."""
        if pubsub is None:
            return
        try:
            await pubsub.unsubscribe(self.INVALIDATE_CHANNEL)
        except Exception:
            pass
        await _maybe_aclose(pubsub)

    async def _publish(self, payload: str) -> None:
        if self._mode != 'redis' or self._redis is None:
            return
        try:
            await self._redis.publish(self.INVALIDATE_CHANNEL, payload)
        except Exception as e:
            logger.debug(f"⚠️ فشل نشر الإبطال: {e}")

    async def get(self, user_id: int) -> Optional[Dict]:
        payload = await self._backend.get(str(user_id))
        if payload is None:
            self.misses += 1
        else:
            self.hits += 1
        return payload

    # ✅ FIX #2: mget
    async def mget(self, user_ids: List[int]) -> Dict[int, Optional[Dict]]:
        if not user_ids:
            return {}
        str_keys = [str(u) for u in user_ids]
        values = await self._backend.mget(str_keys)
        out: Dict[int, Optional[Dict]] = {}
        for uid, val in zip(user_ids, values):
            out[uid] = val
            if val is None:
                self.misses += 1
            else:
                self.hits += 1
        return out

    async def set(self, user_id: int, payload: Dict) -> None:
        await self._backend.set(str(user_id), payload, self.ttl)

    # ✅ FIX #Z: mset_batch موحّد (Memory: loop، Redis: pipeline)
    async def mset_batch(self, items: Dict[int, Dict]) -> None:
        """كتابة دفعة واحدة. items = {user_id: payload}."""
        if not items:
            return
        str_items = {str(k): v for k, v in items.items()}
        await self._backend.mset(str_items, self.ttl)

    async def invalidate(self, user_id: int) -> None:
        await self._backend.delete(str(user_id))
        await self._publish(str(user_id))

    async def clear(self) -> None:
        await self._backend.flush()
        await self._publish('*')

    async def close(self) -> None:
        # ✅ FIX #O: حماية بـ _init_lock لمنع سباق نظري مع init()
        # ✅ FIX #W: لا نُصفّر _init_lock — يبقى طوال حياة الكائن
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            await self._close_inner()

    async def _close_inner(self) -> None:
        """التنفيذ الفعلي للإغلاق (بلا قفل، لا يلمس _init_lock)."""
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except (asyncio.CancelledError, Exception):
                pass
            self._pubsub_task = None

        if self._redis is not None:
            # ✅ FIX #5: توافق redis-py 4.x و 5.x
            await _maybe_aclose(self._redis)
            self._redis = None

        try:
            await self._backend.close()
        except Exception:
            pass

        self._mode = 'memory'
        self._backend = _MemoryBackend(self.max_size)
        self._initialized = False
        self._redis_url = None
        # ✅ FIX #C: تصفير الإحصائيات عند الإغلاق
        self.hits = 0
        self.misses = 0
        # ✅ إعادة تعيين primitives المرتبطة بالـ loop السابق
        self._subscriber_ready = None
        # ⚠️ FIX #W: _init_lock **يبقى** — لا يُصفَّر (يمنع سباق close() متعدد)

    async def ping_redis(self) -> bool:
        """✅ FIX #11: فحص صحة Redis للمراقبة."""
        if self._mode != 'redis' or self._redis is None:
            return False
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False

    def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        return {
            'mode': self._mode,
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': round(self.hits / total, 3) if total else 0.0,
            'ttl': self.ttl,
        }


_CACHE = _SubscriptionCache(ttl=_resolve_cache_ttl(), max_size=10_000)


# ─── دورة الحياة ───

async def init_cache(redis_url: Optional[str] = None) -> None:
    """يُستدعى عند بدء البوت. آمن للاستدعاء أكثر من مرة."""
    await _CACHE.init(redis_url)


async def close_cache() -> None:
    """يُستدعى عند إيقاف البوت."""
    await _CACHE.close()


# ─── أدوات المراقبة/الإبطال ───

def cache_stats() -> Dict[str, Any]:
    """sync — إحصائيات محلية."""
    return _CACHE.stats()


async def cache_invalidate(user_id: int) -> None:
    """⚠️ async — يجب استدعاؤها بـ await."""
    await _CACHE.invalidate(user_id)


async def cache_clear() -> None:
    """⚠️ async — يجب استدعاؤها بـ await."""
    await _CACHE.clear()


async def cache_redis_ping() -> bool:
    """async — فحص اتصال Redis."""
    return await _CACHE.ping_redis()


# كاش المالك الأساسي
_PRIMARY_OWNER_CACHE: Optional[int] = None


def _get_primary_owner_id() -> int:
    global _PRIMARY_OWNER_CACHE
    if _PRIMARY_OWNER_CACHE is None:
        try:
            from config import CONFIG
            _PRIMARY_OWNER_CACHE = int(getattr(CONFIG, 'PRIMARY_OWNER_ID', 0) or 0)
        except Exception:
            _PRIMARY_OWNER_CACHE = 0
    return _PRIMARY_OWNER_CACHE


# =====================================================================
# 1. الاشتراكات
# =====================================================================

class SubscriptionDB:

    @staticmethod
    async def has_active_subscription(user_id: int) -> bool:
        if user_id == _get_primary_owner_id():
            return True

        cached = await _CACHE.get(user_id)
        if cached is not None:
            return bool(cached.get('active'))

        now = _utc_now()
        row = await DB.fetchone(
            "SELECT id, expires_at FROM subscriptions "
            "WHERE user_id=? AND is_active=1 ORDER BY id DESC LIMIT 1",
            (user_id,)
        )

        if not row:
            await _CACHE.set(user_id, {'active': False, 'days_left': 0,
                                       'expires_at': None})
            return False

        expires = _to_dt(_row_get(row, 'expires_at'))
        if expires is None:
            row_id = _row_get(row, 'id')
            raw_exp = _row_get(row, 'expires_at')
            # ✅ FIX #G: تصعيد التحذير إلى error — بيانات تالفة تستحق الانتباه
            logger.error(
                f"🚨 expires_at تالف (user={user_id}, row_id={row_id}, "
                f"value={raw_exp!r}) — سيُعطَّل السجل"
            )
            if row_id is not None:
                try:
                    await DB.execute(
                        "UPDATE subscriptions SET is_active=0 WHERE id=?",
                        (row_id,)
                    )
                    await _CACHE.invalidate(user_id)
                except Exception as e:
                    logger.warning(f"⚠️ فشل تعطيل اشتراك معطوب (user={user_id}): {e}")
            await _CACHE.set(user_id, {'active': False, 'days_left': 0,
                                       'expires_at': None})
            return False

        if expires > now:
            days_left = _days_left_ceil(expires, now)
            await _CACHE.set(user_id, {
                'active': True,
                'days_left': days_left,
                'expires_at': expires.isoformat(),
            })
            return True

        try:
            await DB.execute(
                "UPDATE subscriptions SET is_active=0 "
                "WHERE user_id=? AND is_active=1 AND expires_at <= ?",
                (user_id, now.isoformat())
            )
        except Exception as e:
            logger.warning(f"⚠️ فشل تعطيل اشتراك منتهي (user={user_id}): {e}")
        await _CACHE.set(user_id, {'active': False, 'days_left': 0,
                                   'expires_at': None})
        return False

    @staticmethod
    async def batch_has_active_subscription(
        user_ids: Iterable[int]
    ) -> Dict[int, bool]:
        """
        ✅ FIX #2: mget للقراءة (رحلة واحدة).
        ✅ FIX #H: إزالة التكرار.
        ✅ FIX #AA: mset_batch للكتابة (رحلة واحدة).
        """
        # ✅ FIX #H: dict.fromkeys يحافظ على الترتيب ويزيل التكرار
        ids = list(dict.fromkeys(int(u) for u in user_ids if u is not None))
        if not ids:
            return {}

        owner = _get_primary_owner_id()
        result: Dict[int, bool] = {}
        uncached: List[int] = []

        # ✅ MGET واحد لكل المجموعة
        cached_map = await _CACHE.mget(ids)
        for uid in ids:
            if uid == owner:
                result[uid] = True
                continue
            cached = cached_map.get(uid)
            if cached is not None:
                result[uid] = bool(cached.get('active'))
            else:
                uncached.append(uid)

        if not uncached:
            return result

        now = _utc_now()
        now_iso = now.isoformat()
        # ✅ FIX #P: 500 placeholder + 1 (now_iso) = 501 ≤ حد SQLite الآمن (999)
        CHUNK = 500

        for i in range(0, len(uncached), CHUNK):
            chunk = uncached[i:i + CHUNK]
            placeholders = ','.join('?' * len(chunk))
            rows = await DB.fetchall(
                f"""SELECT user_id, expires_at FROM subscriptions
                    WHERE user_id IN ({placeholders})
                      AND is_active=1 AND expires_at > ?
                    ORDER BY id DESC""",
                (*chunk, now_iso)
            )
            active_map: Dict[int, str] = {}
            for r in rows or []:
                uid = _row_get(r, 'user_id')
                exp = _row_get(r, 'expires_at')
                if uid not in active_map:
                    active_map[uid] = exp

            # ✅ FIX #AA: بناء دفعة الكتابة كاملة ثم كتابتها بـ mset_batch
            to_cache: Dict[int, Dict] = {}
            for uid in chunk:
                if uid in active_map:
                    exp_dt = _to_dt(active_map[uid])
                    days_left = _days_left_ceil(exp_dt, now) if exp_dt else 0
                    result[uid] = True
                    to_cache[uid] = {
                        'active': True,
                        'days_left': days_left,
                        'expires_at': active_map[uid],
                    }
                else:
                    result[uid] = False
                    to_cache[uid] = {'active': False, 'days_left': 0,
                                     'expires_at': None}

            # ✅ FIX #AA: كتابة الدفعة بـ 1 round-trip (Redis pipeline)
            await _CACHE.mset_batch(to_cache)

        return result

    @staticmethod
    async def activate_subscription(user_id: int, days: int) -> bool:
        if days == 0:
            return True

        # ✅ FIX #D: رفع الحد إلى 12 محاولة + backoff أطول بعد الثالثة
        _MAX_CAS_RETRIES = 12
        now = _utc_now()

        for attempt in range(_MAX_CAS_RETRIES):
            row = await DB.fetchone(
                "SELECT id, expires_at FROM subscriptions "
                "WHERE user_id=? AND is_active=1 ORDER BY id DESC LIMIT 1",
                (user_id,)
            )

            if row:
                row_id = _row_get(row, 'id')
                if row_id is None:
                    return False

                old_expires_raw = _row_get(row, 'expires_at')
                current = _to_dt(old_expires_raw)

                if days > 0:
                    base = current if (current and current > now) else now
                else:
                    base = current if current else now

                new_expires_iso = (base + timedelta(days=days)).isoformat()

                try:
                    result = await _with_retry(lambda: DB.execute(
                        "UPDATE subscriptions SET expires_at=?, is_active=1 "
                        "WHERE id=? AND expires_at IS ?",
                        (new_expires_iso, row_id, old_expires_raw)
                    ))
                except Exception as e:
                    logger.error(f"❌ فشل تمديد الاشتراك (user={user_id}): {e}")
                    return False

                if _rowcount(result) > 0:
                    await _CACHE.invalidate(user_id)
                    return True

                # ✅ FIX #D: backoff أقوى بعد المحاولة الثالثة
                if attempt < 3:
                    delay = 0.01 * (2 ** attempt) + random.uniform(0, 0.01)
                else:
                    delay = min(0.05 * (2 ** (attempt - 2)), 0.4) \
                        + random.uniform(0, 0.05)
                await asyncio.sleep(delay)
                continue

            if days < 0:
                return False

            new_expires_iso = (now + timedelta(days=days)).isoformat()
            try:
                await DB.execute(
                    "INSERT INTO subscriptions "
                    "(user_id, expires_at, is_active, created_at) "
                    "VALUES (?, ?, 1, ?)",
                    (user_id, new_expires_iso, TimeUtils.sql_iso())
                )
                await _CACHE.invalidate(user_id)
                return True
            except Exception as e:
                logger.debug(f"🔁 INSERT retry (user={user_id}): {e}")
                if attempt < 3:
                    delay = 0.01 * (2 ** attempt) + random.uniform(0, 0.01)
                else:
                    delay = min(0.05 * (2 ** (attempt - 2)), 0.4) \
                        + random.uniform(0, 0.05)
                await asyncio.sleep(delay)
                continue

        logger.warning(
            f"⚠️ activate_subscription فشلت بعد {_MAX_CAS_RETRIES} محاولات "
            f"(user={user_id}, days={days})"
        )
        return False

    @staticmethod
    async def get_subscription(user_id: int) -> Optional[Dict]:
        row = await DB.fetchone(
            "SELECT * FROM subscriptions WHERE user_id=? AND is_active=1 "
            "ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        if not row:
            return None
        return dict(row) if not isinstance(row, dict) else row

    @staticmethod
    async def get_subscription_days_left(user_id: int) -> int:
        cached = await _CACHE.get(user_id)
        if cached is not None:
            return int(cached.get('days_left', 0))
        await SubscriptionDB.has_active_subscription(user_id)
        cached = await _CACHE.get(user_id)
        return int(cached.get('days_left', 0)) if cached else 0

    @staticmethod
    async def expire_expired_subscriptions() -> int:
        now_iso = _utc_now().isoformat()
        try:
            result = await _with_retry(lambda: DB.execute(
                "UPDATE subscriptions SET is_active=0 "
                "WHERE is_active=1 AND expires_at <= ?",
                (now_iso,)
            ))
        except Exception as e:
            logger.error(f"❌ فشل تعطيل الاشتراكات المنتهية: {e}")
            return 0

        count = _rowcount(result)
        if count:
            await _CACHE.clear()
            logger.info(f"⏰ تم تعطيل {count} اشتراك منتهي عند {now_iso}")
        return count

    @staticmethod
    async def get_users_for_reminder() -> List[Dict]:
        now = _utc_now()
        soon = now + timedelta(days=3)
        rows = await DB.fetchall(
            """SELECT u.user_id AS user_id,
                      u.language AS language,
                      s.expires_at AS expires_at
               FROM subscriptions s
               JOIN users u ON u.user_id = s.user_id
               WHERE s.is_active=1 AND s.expires_at BETWEEN ? AND ?""",
            (now.isoformat(), soon.isoformat())
        )
        result = []
        for r in rows or []:
            expires = _to_dt(_row_get(r, 'expires_at'))
            if expires is None:
                continue
            result.append({
                'user_id': _row_get(r, 'user_id'),
                'language': _row_get(r, 'language', 'ar') or 'ar',
                'days_left': _days_left_ceil(expires, now),
            })
        return result


# =====================================================================
# 2. التجربة المجانية
# =====================================================================

class TrialDB:

    @staticmethod
    async def has_used_trial(user_id: int) -> bool:
        row = await DB.fetchone(
            "SELECT 1 FROM trials WHERE user_id=? LIMIT 1",
            (user_id,)
        )
        return row is not None

    @staticmethod
    async def activate_trial(user_id: int, days: int = 3) -> int:
        """
        يُعيد عدد الأيام عند النجاح، أو 0 عند:
          - days <= 0
          - سبق استخدام التجربة
          - فشل تسجيل التجربة في DB
          - فشل تفعيل الاشتراك (مع rollback)
        """
        if days <= 0:
            return 0

        try:
            result = await DB.execute(
                "INSERT OR IGNORE INTO trials (user_id, used_at) VALUES (?, ?)",
                (user_id, TimeUtils.sql_iso())
            )
        except Exception as e:
            logger.warning(f"⚠️ فشل تسجيل التجربة (user={user_id}): {e}")
            return 0

        if _rowcount(result) == 0:
            logger.debug(f"ℹ️ المستخدم {user_id} استخدم التجربة سابقاً")
            return 0

        success = await SubscriptionDB.activate_subscription(user_id, days)
        if not success:
            try:
                await DB.execute("DELETE FROM trials WHERE user_id=?", (user_id,))
                logger.warning(f"⚠️ تراجع عن تسجيل التجربة (user={user_id})")
            except Exception as e2:
                logger.error(f"❌ فشل التراجع عن التجربة: {e2}")
            return 0

        return days


# =====================================================================
# 3. الباقات
# =====================================================================

class PlansDB:

    @staticmethod
    async def get_plan_by_name(name: str) -> Optional[Dict]:
        row = await DB.fetchone(
            "SELECT * FROM plans WHERE name=? AND is_active=1 LIMIT 1", (name,)
        )
        if not row:
            return None
        return dict(row) if not isinstance(row, dict) else row

    @staticmethod
    async def get_all_plans() -> List[Dict]:
        rows = await DB.fetchall(
            "SELECT * FROM plans WHERE is_active=1 ORDER BY price ASC"
        )
        if not rows:
            return []
        return [dict(r) if not isinstance(r, dict) else r for r in rows]

    @staticmethod
    async def get_gift_plan(gift_plan_id: int) -> Optional[Dict]:
        row = await DB.fetchone(
            "SELECT * FROM gift_plans WHERE id=? AND is_active=1 LIMIT 1",
            (gift_plan_id,)
        )
        if not row:
            return None
        return dict(row) if not isinstance(row, dict) else row

    @staticmethod
    async def get_gift_plans() -> List[Dict]:
        rows = await DB.fetchall(
            "SELECT * FROM gift_plans WHERE is_active=1 ORDER BY price ASC"
        )
        if not rows:
            return []
        return [dict(r) if not isinstance(r, dict) else r for r in rows]


# =====================================================================
# 4. الفواتير
# =====================================================================

class InvoicesDB:

    @staticmethod
    async def create_invoice(user_id: int, plan_id: int, amount: int,
                             invoice_type: str = "subscription") -> Optional[str]:
        if amount < 0:
            logger.error(f"❌ مبلغ فاتورة سالب: {amount}")
            return None

        number = f"INV-{int(time.time())}-{user_id}-{uuid.uuid4().hex[:6]}"
        try:
            await DB.execute(
                """INSERT INTO invoices
                   (number, user_id, plan_id, amount, status, type, created_at)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
                (number, user_id, plan_id, amount, invoice_type, TimeUtils.sql_iso())
            )
            return number
        except Exception as e:
            logger.error(f"❌ فشل إنشاء الفاتورة: {e}")
            return None

    @staticmethod
    async def get_user_invoices(user_id: int, limit: int = 10) -> List[Dict]:
        rows = await DB.fetchall(
            "SELECT * FROM invoices WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        )
        if not rows:
            return []
        return [dict(r) if not isinstance(r, dict) else r for r in rows]

    @staticmethod
    async def mark_invoice_paid(number: str, user_id: Optional[int] = None) -> bool:
        try:
            if user_id is None:
                result = await DB.execute(
                    "UPDATE invoices SET status='paid', paid_at=? "
                    "WHERE number=? AND status='pending'",
                    (TimeUtils.sql_iso(), number)
                )
            else:
                result = await DB.execute(
                    "UPDATE invoices SET status='paid', paid_at=? "
                    "WHERE number=? AND status='pending' AND user_id=?",
                    (TimeUtils.sql_iso(), number, user_id)
                )
            affected = _rowcount(result)
            if affected == 0:
                logger.warning(f"⚠️ لم تُحدَّث الفاتورة {number}")
                return False
            return True
        except Exception as e:
            logger.error(f"❌ فشل تحديث الفاتورة {number}: {e}")
            return False

    @staticmethod
    async def mark_invoice_cancelled(number: str,
                                     user_id: Optional[int] = None) -> bool:
        try:
            if user_id is None:
                result = await DB.execute(
                    "UPDATE invoices SET status='cancelled' "
                    "WHERE number=? AND status='pending'",
                    (number,)
                )
            else:
                result = await DB.execute(
                    "UPDATE invoices SET status='cancelled' "
                    "WHERE number=? AND status='pending' AND user_id=?",
                    (number, user_id)
                )
            return _rowcount(result) > 0
        except Exception as e:
            logger.error(f"❌ فشل إلغاء الفاتورة {number}: {e}")
            return False


# =====================================================================
# 5. الإحالات
# =====================================================================

class ReferralDB:

    @staticmethod
    async def get_referral_code(user_id: int) -> Optional[str]:
        row = await DB.fetchone(
            "SELECT code FROM referral_codes WHERE user_id=? LIMIT 1", (user_id,)
        )
        code = _row_get(row, 'code') if row else None
        if code:
            return code

        for attempt in range(4):
            # ✅ FIX #E: طول ثابت للكود (12 بايت ~ 16 حرف)
            candidate = f"ref_{secrets.token_urlsafe(12)}"
            try:
                await DB.execute(
                    "INSERT OR IGNORE INTO referral_codes "
                    "(user_id, code, created_at) VALUES (?, ?, ?)",
                    (user_id, candidate, TimeUtils.sql_iso())
                )
            except Exception as e:
                logger.warning(f"⚠️ فشل إدراج كود (attempt={attempt+1}): {e}")
                await asyncio.sleep(0.02 * (2 ** attempt)
                                    + random.uniform(0, 0.02))
                continue

            row = await DB.fetchone(
                "SELECT code FROM referral_codes WHERE user_id=? LIMIT 1",
                (user_id,)
            )
            real = _row_get(row, 'code') if row else None
            if real:
                return real
            await asyncio.sleep(0.02 * (2 ** attempt) + random.uniform(0, 0.02))

        logger.error(f"❌ تعذّر إنشاء كود إحالة (user={user_id})")
        return None

    @staticmethod
    async def get_referral_stats(user_id: int) -> Dict[str, int]:
        total_row = await DB.fetchone(
            "SELECT COUNT(*) AS c FROM referrals WHERE referrer_id=?", (user_id,)
        )
        available_row = await DB.fetchone(
            "SELECT COALESCE(SUM(days_earned),0) AS d FROM referrals "
            "WHERE referrer_id=? AND claimed=0",
            (user_id,)
        )
        return {
            'total': int(_row_get(total_row, 'c', 0) or 0),
            'available': int(_row_get(available_row, 'd', 0) or 0),
        }

    @staticmethod
    async def claim_referral_reward(user_id: int) -> int:
        claim_token = f"{TimeUtils.sql_iso()}#{secrets.token_hex(4)}"
        try:
            await DB.execute(
                "UPDATE referrals SET claimed=1, claimed_at=? "
                "WHERE referrer_id=? AND claimed=0",
                (claim_token, user_id)
            )
        except Exception as e:
            logger.error(f"❌ فشل تعليم الإحالات (user={user_id}): {e}")
            return 0

        row = await DB.fetchone(
            "SELECT COALESCE(SUM(days_earned),0) AS d FROM referrals "
            "WHERE referrer_id=? AND claimed=1 AND claimed_at=?",
            (user_id, claim_token)
        )
        days = int(_row_get(row, 'd', 0) or 0)
        if days <= 0:
            return 0

        ok = await SubscriptionDB.activate_subscription(user_id, days)
        if not ok:
            logger.warning(
                f"⚠️ تعذّر تفعيل مكافأة الإحالة (user={user_id})، تراجع..."
            )
            try:
                await DB.execute(
                    "UPDATE referrals SET claimed=0, claimed_at=NULL "
                    "WHERE referrer_id=? AND claimed=1 AND claimed_at=?",
                    (user_id, claim_token)
                )
            except Exception as e:
                logger.error(f"❌ فشل التراجع: {e}")
            return 0
        return days

    @staticmethod
    async def get_referrals_list(user_id: int) -> List[int]:
        rows = await DB.fetchall(
            "SELECT referred_id FROM referrals WHERE referrer_id=? "
            "ORDER BY id DESC LIMIT 50",
            (user_id,)
        )
        if not rows:
            return []
        return [
            _row_get(r, 'referred_id')
            for r in rows
            if _row_get(r, 'referred_id') is not None
        ]

    @staticmethod
    async def add_referral(referrer_id: int, referred_id: int,
                           days_earned: int = 1) -> bool:
        if referrer_id == referred_id or days_earned <= 0:
            return False
        try:
            result = await DB.execute(
                """INSERT OR IGNORE INTO referrals
                   (referrer_id, referred_id, days_earned, claimed, created_at)
                   VALUES (?, ?, ?, 0, ?)""",
                (referrer_id, referred_id, days_earned, TimeUtils.sql_iso())
            )
            return _rowcount(result) > 0
        except Exception as e:
            logger.error(f"❌ فشل إضافة الإحالة: {e}")
            return False


# =====================================================================
# 6. ربط جميع الدوال بكائن DB
# =====================================================================

def _attach_methods_to_db(db_class) -> None:
    classes = [SubscriptionDB, TrialDB, PlansDB, InvoicesDB, ReferralDB]
    attached: List[str] = []
    skipped: List[str] = []

    for cls in classes:
        for name in dir(cls):
            if name.startswith('_'):
                continue
            try:
                attr = getattr(cls, name)
            except AttributeError:
                continue
            if not callable(attr):
                continue
            if hasattr(db_class, name):
                skipped.append(name)
                continue
            setattr(db_class, name, staticmethod(attr))
            attached.append(name)

    # ربط أدوات الكاش والمراقبة
    for helper_name, helper in (
        ('cache_stats', cache_stats),
        ('cache_invalidate', cache_invalidate),
        ('cache_clear', cache_clear),
        ('cache_redis_ping', cache_redis_ping),
        ('init_cache', init_cache),
        ('close_cache', close_cache),
    ):
        if not hasattr(db_class, helper_name):
            setattr(db_class, helper_name, staticmethod(helper))
            attached.append(helper_name)
        else:
            skipped.append(helper_name)

    # ✅ FIX #F: تقرير موحّد
    # ✅ FIX #Q: downgrade warning إلى debug إذا تخطّى كل الأسماء (إعادة استيراد)
    total_candidates = len(attached) + len(skipped)
    if skipped:
        msg = (
            f"⚠️ تم تخطي {len(skipped)} دالة (موجودة مسبقاً في DB): "
            f"{', '.join(sorted(set(skipped)))}"
        )
        if attached:
            logger.warning(msg)
        else:
            # إعادة استيراد كاملة — ليست مشكلة تشغيلية
            logger.debug(msg)

    logger.info(
        f"✅ تم ربط {len(attached)} دالة من database_subscriptions بـ DB "
        f"(من أصل {total_candidates} مرشّح)"
    )
    if attached:
        # ✅ FIX #J: log.info لقائمة الأسماء
        logger.info(f"📎 الأسماء المربوطة: {', '.join(sorted(attached))}")


try:
    _attach_methods_to_db(DB)
except Exception as e:
    logger.error(f"❌ فشل ربط دوال الاشتراكات بـ DB: {e}", exc_info=True)