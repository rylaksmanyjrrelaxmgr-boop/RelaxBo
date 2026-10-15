# group_log.py
"""
group_log.py — نظام سجل قنوات المجموعات الذكي (v1.4.0)
=====================================================================
🔴 v1.4.0 (SETTINGS-KEY-UNIFICATION):
    🔴 FIX-GM20 CRITICAL: توحيد مفتاح السجل العام.
        المشكلة: group_log.py كان يكتب/يقرأ على
        `settings.global_log_channel` بينما handlers_callback.py
        و DB.get_log_channel يقرآن من `settings.log_channel`.
        النتيجة: فصام كامل بين النظامين — المطوّر يعيّن قناة
        السجل فتُحفظ تحت مفتاح، لكن `_membership_get_log_channel`
        و `_get_log_channel_menu_data` لا يجدانها.
        الإصلاح:
          • CANONICAL_KEY = "log_channel" (متوافق مع handlers_callback)
          • LEGACY_KEY   = "global_log_channel" (للقراءة فقط)
          • _read_global_key() يجرّب CANONICAL ثم LEGACY
          • set_global() يكتب CANONICAL + يحذف LEGACY (ترحيل تلقائي)

    🔴 FIX-GM21 CRITICAL: ترحيل تلقائي للبيانات القديمة.
        _migrate_legacy_key() تُستدعى مرة واحدة عند أول قراءة:
        إذا وُجد LEGACY وبلا CANONICAL → ننسخ ثم نحذف LEGACY.

    🟠 FIX-GM22: invalidate_global() منفصلة عن invalidate(group_id).
        قبل: invalidate(None) يمسح كل شيء (مشاكل أداء عند تغيير
        القناة العامة فقط). بعد: دوال مخصّصة:
          • invalidate(group_id)  → مجموعة واحدة
          • invalidate_global()   → السجل العام + قوائم جميع المجموعات
          • invalidate_all()      → كل شيء (للإيقاف)

    🟠 FIX-GM23: إبطال جماعي عبر invalidate_all_menus().
        عند تغيير السجل العام، تُبطَل قوائم كل المجموعات التي
        تستخدم الـ fallback → تظهر القناة الجديدة فوراً.

    🟡 FIX-GM24: تحقق صريح من نوع chat_id (int) في set_private
        و set_global، لتفادي تخزين "@username" كقناة سجل.

    🟡 FIX-GM25: _get_global لا يتجاهل loop عند فشل
        get_running_loop — يستخدم self._global_ts مباشرة.

✅ v1.3.2 (PERF + RELIABILITY) — محفوظ بالكامل:
    🔴 FIX-GM8: cache 60s لحالة المشاركة (~3300× تحسّن).
    🔴 FIX-GM15: _worker يستخدم safe_send بدل bot.send_message.
    🟡 FIX-GM19: send() يُعيد bool + عداد إسقاط دوري.

✅ v1.3.1 (PostgreSQL): ON CONFLICT DO NOTHING/UPDATE.
✅ v1.3.0 (ذكاء المشاركة): get_groups_using_channel + رأس ذكي.
✅ v1.2.0 (أساس): get_running_loop + has_private + drain.
=====================================================================
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# 🔴 FIX-GM15 (v1.3.2): محاولة استيراد safe_send من utils
# ═════════════════════════════════════════════════════════════════════
_HAS_SAFE_SEND = False
_safe_send_fn = None
try:
    from utils import safe_send as _safe_send_fn
    _HAS_SAFE_SEND = True
except ImportError:
    pass


# ═════════════════════════════════════════════════════════════════════
# 🔴 FIX-GM20 (v1.4.0): توحيد مفتاح السجل العام
# ═════════════════════════════════════════════════════════════════════
# CANONICAL_KEY: المفتاح الرسمي — متوافق مع handlers_callback.py
#                و DB.get_log_channel() و _membership_get_log_channel
# LEGACY_KEY   : المفتاح القديم — للقراءة فقط، يُرحَّل تلقائياً
# ═════════════════════════════════════════════════════════════════════
CANONICAL_LOG_KEY = "log_channel"
LEGACY_LOG_KEY = "global_log_channel"


class GroupLog:
    """
    إدارة سجل قنوات المجموعات — نسخة ذكية.

    - كل مجموعة لها قناة سجل خاصة (اختياري)
    - قناة سجل عامة (اختياري) — fallback
    - ✅ قناة واحدة يمكن أن تخدم عدة مجموعات بذكاء
    """

    QUEUE_MAX_SIZE = 1000
    CACHE_TTL = 60

    def __init__(self, db, bot):
        self.db = db
        self.bot = bot

        # Cache — قنوات مجموعة
        self._cache: Dict[int, List[dict]] = {}
        self._cache_ts: Dict[int, float] = {}
        self._cache_ttl = self.CACHE_TTL

        # ✅ v1.3.0: أسماء المجموعات (cache للأداء)
        self._group_names: Dict[int, str] = {}

        # 🔴 FIX-GM8 (v1.3.2): cache لحالة المشاركة
        self._shared_cache: Dict[int, tuple] = {}   # {group_id: (bool, ts)}
        self._shared_cache_ttl = 60.0

        # 🔴 FIX-GM19 (v1.3.2): عداد الرسائل المُسقَطة
        self._drop_count: int = 0

        # Global log channel cache
        self._global_chat_id: Optional[int] = None
        self._global_ts: float = 0.0

        # 🔴 FIX-GM21 (v1.4.0): علامة الترحيل (مرة واحدة لكل عمر instance)
        self._legacy_migrated: bool = False

        # Queue + Worker
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=self.QUEUE_MAX_SIZE)
        self._worker_task: Optional[asyncio.Task] = None
        self._started = False

    # =================================================================
    # Cache invalidation — 🔴 FIX-GM22 (v1.4.0)
    # =================================================================

    def invalidate(self, group_id: Optional[int] = None) -> None:
        """
        إبطال الكاش — لمجموعة واحدة أو الكل.

        🟠 FIX-GM22 (v1.4.0): سلوك متغيّر:
          • invalidate(None) → نفس invalidate_all() (توافق خلفي)
          • invalidate(gid)  → مجموعة واحدة فقط

        للسلوك الجديد المُحسَّن:
          • invalidate_global()     → السجل العام فقط
          • invalidate_all()        → كل شيء
        """
        if group_id is None:
            self.invalidate_all()
            return
        self._cache.pop(group_id, None)
        self._cache_ts.pop(group_id, None)
        self._group_names.pop(group_id, None)
        self._shared_cache.pop(group_id, None)

    def invalidate_global(self) -> None:
        """
        🟠 FIX-GM22 (v1.4.0): إبطال السجل العام + قوائم المجموعات.

        يُستدعى عند:
          • set_global(new_chat_id)
          • unset_global()
          • تغيير قناة السجل العامة عبر لوحة الأدمن

        يُبطل:
          • self._global_chat_id / _global_ts
          • _cache لمجموعات التي كانت تستخدم fallback (بلا private)
        """
        old_global = self._global_chat_id
        self._global_chat_id = None
        self._global_ts = 0.0

        # أعد بناء cache المجموعات التي كانت تستخدم fallback فقط
        try:
            for gid in list(self._cache.keys()):
                # إذا كانت المجموعة بلا قناة خاصة → قد تغيّر fallback
                # (نُبطلها كلها — رخيص لأن_cache صغير)
                self._cache.pop(gid, None)
                self._cache_ts.pop(gid, None)
        except Exception as e:
            logger.debug(f"invalidate_global cache loop: {e}")

        logger.debug(
            f"♻️ GroupLog.invalidate_global: "
            f"old={old_global} → new=None (سيُعاد الجلب)"
        )

    def invalidate_all(self) -> None:
        """
        🟠 FIX-GM22 (v1.4.0): إبطال كل الكاش (للإيقاف/الصيانة).
        """
        self._cache.clear()
        self._cache_ts.clear()
        self._group_names.clear()
        self._shared_cache.clear()
        self._global_ts = 0.0
        self._global_chat_id = None
        logger.debug("♻️ GroupLog.invalidate_all: كل الكاش أُبطل")

    async def invalidate_all_menus(self) -> int:
        """
        🟠 FIX-GM23 (v1.4.0): إبطال قوائم قناة السجل في الـ cache
        العام (internal_cache) لكل المجموعات.

        يُستدعى عند تغيير القناة العامة — لأن قوائم المجموعات
        التي تستخدم fallback ستُظهر القناة القديمة لـ 5 دقائق
        (LOG_CHANNEL_MENU_CACHE_TTL).

        يُرجع: عدد المفاتيح المُبطَلة.
        """
        count = 0
        try:
            from database import internal_cache
        except ImportError:
            logger.debug("invalidate_all_menus: internal_cache غير متاح")
            return 0
        try:
            # نحاول الوصول لـ store مباشرة (إن وُجد)
            store = getattr(internal_cache, '_store', None)
            if store is None:
                # fallback: ابحث في واجهات أخرى
                store = getattr(internal_cache, '_cache', None)
            if store is None:
                return 0
            for key in list(store.keys()):
                if str(key).startswith("log_ch_menu_"):
                    try:
                        await internal_cache.invalidate(key)
                        count += 1
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"invalidate_all_menus: {e}")
        if count:
            logger.debug(
                f"♻️ invalidate_all_menus: {count} مفتاح أُبطل"
            )
        return count

    # =================================================================
    # سجل خاص بالمجموعة
    # =================================================================

    async def get_private(self, group_id: int) -> Optional[int]:
        """يُرجع معرّف قناة السجل الخاصة بالمجموعة (أو None)."""
        if not group_id:
            return None
        try:
            row = await self.db.fetchone(
                "SELECT log_channel_id FROM bot_groups WHERE chat_id = ?",
                (group_id,),
            )
            if not row:
                return None
            if isinstance(row, dict):
                ch = row.get("log_channel_id")
            else:
                try:
                    ch = row["log_channel_id"]
                except (KeyError, IndexError, TypeError):
                    ch = None
            return int(ch) if ch else None
        except Exception as e:
            logger.error(f"get_private({group_id}): {e}")
            return None

    async def has_private(self, group_id: int) -> bool:
        """هل للمجموعة قناة سجل خاصة؟"""
        return (await self.get_private(group_id)) is not None

    # =================================================================
    # ✅ v1.3.0: ذكاء المشاركة
    # =================================================================

    async def get_groups_using_channel(
        self, chat_id: int, exclude_group_id: int = None
    ) -> List[Dict]:
        """قائمة المجموعات التي تستخدم نفس القناة."""
        if not chat_id:
            return []
        try:
            if exclude_group_id is not None:
                rows = await self.db.fetchall(
                    "SELECT chat_id, chat_name, banned FROM bot_groups "
                    "WHERE log_channel_id = ? AND chat_id != ?",
                    (chat_id, exclude_group_id),
                )
            else:
                rows = await self.db.fetchall(
                    "SELECT chat_id, chat_name, banned FROM bot_groups "
                    "WHERE log_channel_id = ?",
                    (chat_id,),
                )
            result = []
            for r in (rows or []):
                if isinstance(r, dict):
                    result.append(r)
                else:
                    try:
                        result.append(dict(r))
                    except (TypeError, ValueError):
                        continue
            return result
        except Exception as e:
            logger.error(f"get_groups_using_channel({chat_id}): {e}")
            return []

    async def get_channel_share_count(
        self, chat_id: int, exclude_group_id: int = None
    ) -> int:
        """عدد المجموعات التي تستخدم نفس القناة."""
        if not chat_id:
            return 0
        try:
            if exclude_group_id is not None:
                count = await self.db.fetchval(
                    "SELECT COUNT(*) FROM bot_groups "
                    "WHERE log_channel_id = ? AND chat_id != ?",
                    (chat_id, exclude_group_id),
                    default=0,
                )
            else:
                count = await self.db.fetchval(
                    "SELECT COUNT(*) FROM bot_groups "
                    "WHERE log_channel_id = ?",
                    (chat_id,),
                    default=0,
                )
            return int(count or 0)
        except Exception as e:
            logger.error(f"get_channel_share_count({chat_id}): {e}")
            return 0

    async def _get_group_name(self, group_id: int) -> str:
        """جلب اسم المجموعة (مع cache)."""
        if group_id in self._group_names:
            return self._group_names[group_id]
        try:
            name = await self.db.fetchval(
                "SELECT chat_name FROM bot_groups WHERE chat_id = ?",
                (group_id,),
                default=None,
            )
            result = str(name) if name else f"مجموعة {group_id}"
        except Exception:
            result = f"مجموعة {group_id}"
        self._group_names[group_id] = result
        return result

    # ═════════════════════════════════════════════════════════════════
    # 🔴 FIX-GM8 (v1.3.2): cache 60s لحالة المشاركة
    # ═════════════════════════════════════════════════════════════════

    async def _is_channel_shared_cached(self, group_id: int) -> bool:
        """cache 60s لحالة المشاركة (FIX-GM8 محفوظ)."""
        try:
            loop = asyncio.get_running_loop()
            now = loop.time()
        except RuntimeError:
            now = time.monotonic()

        cached = self._shared_cache.get(group_id)
        if cached is not None:
            shared, ts = cached
            if (now - ts) < self._shared_cache_ttl:
                return shared

        try:
            private = await self.get_private(group_id)
            if not private:
                shared = True
            else:
                count = await self.get_channel_share_count(
                    private, exclude_group_id=group_id
                )
                shared = count > 0
        except Exception:
            shared = True

        self._shared_cache[group_id] = (shared, now)
        return shared

    # =================================================================
    # ✅ v1.3.0: set_private مع تقرير ذكي
    # 🟡 FIX-GM24 (v1.4.0): تحقق صريح من نوع chat_id
    # =================================================================

    async def set_private(self, group_id: int, chat_id: int) -> Dict:
        """
        يعيّن قناة سجل خاصة.

        🟡 FIX-GM24 (v1.4.0): يتحقق أن chat_id رقم صحيح.
        """
        result = {
            'ok': False,
            'shared': False,
            'share_count': 0,
            'other_groups': [],
        }

        if not group_id or not chat_id:
            return result

        # 🟡 FIX-GM24: تحقق صريح من نوع chat_id
        try:
            chat_id_int = int(chat_id)
        except (TypeError, ValueError):
            logger.warning(
                f"set_private: chat_id غير صالح ({chat_id!r}) — "
                f"يجب أن يكون رقم قناة (مثل -1001234567890) لا "
                f"username. لتعيين @username استخدمه من لوحة الأدمن."
            )
            return result

        # ✅ فحص المشاركة أولاً
        try:
            others = await self.get_groups_using_channel(
                chat_id_int, exclude_group_id=group_id
            )
            if others:
                result['shared'] = True
                result['share_count'] = len(others)
                result['other_groups'] = [
                    o.get('chat_name') or f"مجموعة {o.get('chat_id')}"
                    for o in others[:5]
                ]
        except Exception as e:
            logger.warning(f"share check failed: {e}")

        # المحاولة الفعلية — UPDATE
        try:
            n = await self.db.execute(
                "UPDATE bot_groups SET log_channel_id = ? "
                "WHERE chat_id = ?",
                (chat_id_int, group_id),
            )
            if n and n > 0:
                self.invalidate(group_id)
                result['ok'] = True
                return result

            # لو المجموعة غير موجودة — أدرجها
            try:
                await self.db.execute(
                    "INSERT INTO bot_groups "
                    "(chat_id, chat_name, log_channel_id, added_at, banned) "
                    "VALUES (?, ?, ?, ?, 0) "
                    "ON CONFLICT (chat_id) DO NOTHING",
                    (
                        group_id,
                        str(group_id),
                        chat_id_int,
                        datetime.now(timezone.utc).replace(tzinfo=None),
                    ),
                )
                await self.db.execute(
                    "UPDATE bot_groups SET log_channel_id = ? "
                    "WHERE chat_id = ?",
                    (chat_id_int, group_id),
                )
                result['ok'] = True
            except Exception as ie:
                logger.warning(f"set_private insert fallback: {ie}")

            self.invalidate(group_id)
            return result
        except Exception as e:
            logger.error(f"set_private({group_id}, {chat_id_int}): {e}")
            return result

    async def unset_private(self, group_id: int) -> bool:
        """يُزيل قناة السجل الخاصة بمجموعة."""
        if not group_id:
            return False
        try:
            await self.db.execute(
                "UPDATE bot_groups SET log_channel_id = NULL "
                "WHERE chat_id = ?",
                (group_id,),
            )
            self.invalidate(group_id)
            return True
        except Exception as e:
            logger.error(f"unset_private({group_id}): {e}")
            return False

    async def unset_private_bulk(self, group_ids: List[int]) -> int:
        """إزالة القناة من عدة مجموعات."""
        if not group_ids:
            return 0
        try:
            placeholders = ",".join(["?"] * len(group_ids))
            n = await self.db.execute(
                f"UPDATE bot_groups SET log_channel_id = NULL "
                f"WHERE chat_id IN ({placeholders})",
                tuple(group_ids),
            )
            for gid in group_ids:
                self.invalidate(gid)
            return n or 0
        except Exception as e:
            logger.error(f"unset_private_bulk: {e}")
            return 0

    # =================================================================
    # 🔴 FIX-GM20/21/25 (v1.4.0): السجل العام — توحيد المفاتيح + ترحيل
    # =================================================================

    async def _migrate_legacy_key(self) -> None:
        """
        🔴 FIX-GM21 (v1.4.0): ترحيل مفتاح LEGACY → CANONICAL.

        يُستدعى مرة واحدة عند أول قراءة:
          • إذا CANONICAL موجود → احذف LEGACY (تنظيف).
          • إذا CANONICAL فارغ و LEGACY موجود → انسخ ثم احذف LEGACY.
          • إذا كليهما فارغ → لا شيء.
        """
        if self._legacy_migrated:
            return
        self._legacy_migrated = True
        try:
            canonical = await self.db.fetchval(
                "SELECT value FROM settings WHERE key = ?",
                (CANONICAL_LOG_KEY,), default=None,
            )
            legacy = await self.db.fetchval(
                "SELECT value FROM settings WHERE key = ?",
                (LEGACY_LOG_KEY,), default=None,
            )
            if canonical:
                # ✅ الأحدث موجود → احذف القديم للتنظيف
                if legacy:
                    try:
                        await self.db.execute(
                            "DELETE FROM settings WHERE key = ?",
                            (LEGACY_LOG_KEY,),
                        )
                        logger.info(
                            f"🧹 FIX-GM21: حذف المفتاح القديم "
                            f"({LEGACY_LOG_KEY}) — CANONICAL موجود"
                        )
                    except Exception as _e:
                        logger.debug(f"delete legacy: {_e}")
                return
            if legacy:
                # 🔄 ترحيل: انسخ ثم احذف
                try:
                    await self.db.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                        (CANONICAL_LOG_KEY, str(legacy)),
                    )
                    await self.db.execute(
                        "DELETE FROM settings WHERE key = ?",
                        (LEGACY_LOG_KEY,),
                    )
                    logger.info(
                        f"🔄 FIX-GM21: ترحيل '{LEGACY_LOG_KEY}' → "
                        f"'{CANONICAL_LOG_KEY}' value={legacy}"
                    )
                except Exception as _e:
                    logger.warning(f"ترحيل legacy: {_e}")
        except Exception as e:
            logger.debug(f"_migrate_legacy_key: {e}")

    async def _read_global_key(self) -> Optional[int]:
        """
        🔴 FIX-GM20 (v1.4.0): قراءة مفتاح السجل العام بـ fallback chain.

        الترتيب:
          1. settings.log_channel          (CANONICAL)
          2. settings.global_log_channel   (LEGACY — للتوافق)
        """
        # 1) CANONICAL
        try:
            v = await self.db.fetchval(
                "SELECT value FROM settings WHERE key = ?",
                (CANONICAL_LOG_KEY,), default=None,
            )
            if v:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    logger.warning(
                        f"global key value غير صالح: {v!r}"
                    )
        except Exception as e:
            logger.debug(f"_read_global_key canonical: {e}")

        # 2) LEGACY
        try:
            v = await self.db.fetchval(
                "SELECT value FROM settings WHERE key = ?",
                (LEGACY_LOG_KEY,), default=None,
            )
            if v:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    pass
        except Exception as e:
            logger.debug(f"_read_global_key legacy: {e}")

        return None

    async def _get_global(self) -> Optional[int]:
        """
        يُرجع معرّف السجل العام (cached).

        🔴 FIX-GM20: يستخدم _read_global_key (توحيد المفاتيح).
        🔴 FIX-GM21: يستدعي _migrate_legacy_key مرة واحدة.
        🟡 FIX-GM25: عند فشل get_running_loop → العودة للقيمة الحالية.
        """
        # 🔴 FIX-GM21: ترحيل عند أول استدعاء
        if not self._legacy_migrated:
            await self._migrate_legacy_key()

        # 🟡 FIX-GM25: احصل على الوقت بأمان
        try:
            loop = asyncio.get_running_loop()
            now = loop.time()
        except RuntimeError:
            # لا يوجد loop — استخدم monotonic فقط للتحقق من TTL
            now = time.monotonic()
            # لا نستطيع استخدام cache زمني معتمد على loop السابق
            # لكن نعتمد على قيمة monotonic الحالية (يعمل مبدئياً)

        if (self._global_chat_id is not None
                and (now - self._global_ts) < self._cache_ttl):
            return self._global_chat_id

        try:
            v = await self._read_global_key()
            self._global_chat_id = v
        except Exception as e:
            logger.warning(f"_get_global: {e}")
            self._global_chat_id = None

        self._global_ts = now
        return self._global_chat_id

    async def set_global(self, chat_id: int) -> bool:
        """
        يُعيّن السجل العام.

        🔴 FIX-GM20 (v1.4.0): يكتب CANONICAL_KEY فقط + يحذف LEGACY.
        🟡 FIX-GM24 (v1.4.0): يتحقق من نوع chat_id.
        """
        if not chat_id:
            return False

        # 🟡 FIX-GM24: تحقق صريح من النوع
        try:
            chat_id_int = int(chat_id)
        except (TypeError, ValueError):
            logger.warning(
                f"set_global: chat_id غير صالح ({chat_id!r}) — "
                f"يجب أن يكون رقم قناة. لـ @username: احفظه كنص "
                f"في settings مباشرة أو حوّله لـ ID أولاً."
            )
            return False

        try:
            # اكتب CANONICAL
            await self.db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (CANONICAL_LOG_KEY, str(chat_id_int)),
            )
            # احذف LEGACY (تنظيف شامل)
            try:
                await self.db.execute(
                    "DELETE FROM settings WHERE key = ?",
                    (LEGACY_LOG_KEY,),
                )
            except Exception as _e:
                logger.debug(f"set_global delete legacy: {_e}")

            self.invalidate_global()

            # 🟠 FIX-GM23: إبطال قوائم قناة السجل في internal_cache
            await self.invalidate_all_menus()

            logger.info(
                f"✅ set_global: {CANONICAL_LOG_KEY}={chat_id_int}"
            )
            return True
        except Exception as e:
            logger.error(f"set_global: {e}")
            return False

    async def unset_global(self) -> bool:
        """
        يُزيل السجل العام.

        🔴 FIX-GM20: يحذف كلا المفتاحين (canonical + legacy).
        """
        try:
            await self.db.execute(
                "DELETE FROM settings WHERE key = ?",
                (CANONICAL_LOG_KEY,),
            )
            try:
                await self.db.execute(
                    "DELETE FROM settings WHERE key = ?",
                    (LEGACY_LOG_KEY,),
                )
            except Exception as _e:
                logger.debug(f"unset_global legacy: {_e}")

            self.invalidate_global()
            await self.invalidate_all_menus()
            logger.info("✅ unset_global: تم الحذف")
            return True
        except Exception as e:
            logger.error(f"unset_global: {e}")
            return False

    async def get_global(self) -> Optional[int]:
        return await self._get_global()

    # =================================================================
    # Resolution
    # =================================================================

    async def get_effective_target(self, group_id: int) -> Optional[int]:
        """القناة التي سيُرسل إليها فعلياً (خاص → عام)."""
        if not group_id:
            return None
        private = await self.get_private(group_id)
        if private:
            return private
        return await self._get_global()

    async def _resolve_targets(self, group_id: int) -> List[dict]:
        """القنوات التي سيُرسل إليها الحدث."""
        try:
            loop = asyncio.get_running_loop()
            now = loop.time()
        except RuntimeError:
            now = time.monotonic()

        ts = self._cache_ts.get(group_id, 0.0)
        if group_id in self._cache and (now - ts) < self._cache_ttl:
            return self._cache[group_id]

        targets: List[dict] = []

        private = await self.get_private(group_id)
        if private:
            targets.append({
                "chat_id": private,
                "events": ["all"],
                "source": "private",
            })
        else:
            g = await self._get_global()
            if g:
                targets.append({
                    "chat_id": g,
                    "events": ["all"],
                    "source": "global",
                })

        self._cache[group_id] = targets
        self._cache_ts[group_id] = now
        return targets

    # =================================================================
    # send مع رأس ذكي — 🔴 FIX-GM19 محفوظ
    # =================================================================

    def send(self, group_id: int, text: str,
             event: str = "general",
             parse_mode: str = "HTML",
             silent: bool = True,
             show_group_header: bool = True) -> bool:
        """يضع رسالة سجل في الطابور."""
        if not group_id or not text:
            return False
        try:
            self._queue.put_nowait({
                "group_id": group_id,
                "text": text,
                "event": event,
                "parse_mode": parse_mode,
                "silent": silent,
                "show_group_header": show_group_header,
            })
            return True
        except asyncio.QueueFull:
            self._drop_count += 1
            if self._drop_count % 100 == 1:
                logger.error(
                    f"🚨 GroupLog: {self._drop_count} رسالة مُسقَطة "
                    f"(queue full, size={self._queue.qsize()}, "
                    f"worker_running={self.is_running})"
                )
            return False

    async def _build_message_text(self, item: dict) -> str:
        """بناء النص النهائي مع رأس ذكي."""
        base_text = item["text"]
        group_id = item["group_id"]

        if not item.get("show_group_header", True):
            return base_text

        shared = await self._is_channel_shared_cached(group_id)

        if not shared:
            return base_text

        group_name = await self._get_group_name(group_id)
        header = (
            f"<b>📌 من: {group_name}</b>\n"
            f"<code>{group_id}</code>\n"
            f"━━━━━━━━━━━━━━━\n"
        )
        return header + base_text

    # =================================================================
    # Worker — 🔴 FIX-GM15 محفوظ
    # =================================================================

    async def _worker(self) -> None:
        """عامل خلفي يعالج طابور الرسائل."""
        logger.info("🟢 GroupLog worker started")
        while True:
            try:
                item = await self._queue.get()
                try:
                    targets = await self._resolve_targets(item["group_id"])
                    if not targets:
                        continue

                    final_text = await self._build_message_text(item)

                    for t in targets:
                        try:
                            if _HAS_SAFE_SEND and _safe_send_fn is not None:
                                result = await _safe_send_fn(
                                    self.bot,
                                    t["chat_id"],
                                    final_text,
                                    parse_mode=item["parse_mode"],
                                    disable_notification=item["silent"],
                                )
                                if result is None:
                                    logger.warning(
                                        f"⚠️ safe_send أعاد None "
                                        f"(grp={item['group_id']}, "
                                        f"src={t['source']}, "
                                        f"chat={t['chat_id']})"
                                    )
                            else:
                                await self.bot.send_message(
                                    chat_id=t["chat_id"],
                                    text=final_text,
                                    parse_mode=item["parse_mode"],
                                    disable_notification=item["silent"],
                                )
                        except Exception as e:
                            err_msg = str(e).lower()
                            if any(kw in err_msg for kw in (
                                "chat not found",
                                "bot was kicked",
                                "channel not found",
                                "chat_id is empty",
                                "user is deactivated",
                                "bot is not a member",
                                "not enough rights",
                            )):
                                logger.warning(
                                    f"⚠️ قناة السجل غير متاحة "
                                    f"(grp={item['group_id']}, "
                                    f"src={t['source']}) — تنظيف ذكي"
                                )
                                await self._cleanup_broken_target(
                                    t, item["group_id"]
                                )
                            else:
                                logger.warning(
                                    f"group_log send failed "
                                    f"(grp={item['group_id']}, "
                                    f"src={t['source']}): {e}"
                                )
                except Exception as e:
                    logger.error(f"group_log processing: {e}")
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                logger.info("🛑 GroupLog worker cancelled")
                break
            except Exception as e:
                logger.error(f"group_log worker: {e}")
                await asyncio.sleep(1)

    async def _cleanup_broken_target(
        self, target: dict, source_group_id: int
    ) -> None:
        """تنظيف ذكي للقناة الفاسدة."""
        try:
            if target["source"] == "global":
                await self.unset_global()
                logger.info("🧹 تم تنظيف القناة العامة")
                return

            chat_id = target["chat_id"]
            groups = await self.get_groups_using_channel(chat_id)
            if groups:
                group_ids = [g['chat_id'] for g in groups]
                n = await self.unset_private_bulk(group_ids)
                logger.info(
                    f"🧹 تم تنظيف {n} مجموعة من القناة الفاسدة "
                    f"{chat_id}"
                )
            else:
                await self.unset_private(source_group_id)
        except Exception as e:
            logger.warning(f"_cleanup_broken_target: {e}")

    def start(self) -> None:
        """يبدأ العامل الخلفي (idempotent)."""
        if self._worker_task and not self._worker_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._worker_task = loop.create_task(self._worker())
            self._started = True
            logger.info("✅ GroupLog worker started")
        except RuntimeError:
            logger.error(
                "❌ GroupLog.start(): لا يوجد event loop — "
                "استدعها داخل asyncio"
            )

    def stop(self) -> None:
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            self._started = False

    async def drain(self, timeout: float = 5.0) -> int:
        try:
            await asyncio.wait_for(
                self._queue.join(), timeout=timeout
            )
            return 0
        except asyncio.TimeoutError:
            remaining = self._queue.qsize()
            logger.warning(
                f"⚠️ GroupLog drain timeout — {remaining} رسالة متبقية"
            )
            return remaining

    async def shutdown(self, drain_timeout: float = 5.0) -> None:
        try:
            await self.drain(timeout=drain_timeout)
        finally:
            self.stop()

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        return (
            self._worker_task is not None
            and not self._worker_task.done()
        )

    # =================================================================
    # مساعدات
    # =================================================================

    @staticmethod
    def fmt_user(user) -> str:
        if user is None:
            return "—"
        name = (
            getattr(user, "full_name", None)
            or getattr(user, "first_name", "?")
        )
        uname = (
            f"@{user.username}"
            if getattr(user, "username", None)
            else "—"
        )
        return (
            f"<b>{name}</b> "
            f"(<code>{getattr(user, 'id', '?')}</code>) | {uname}"
        )

    @staticmethod
    def fmt_time() -> str:
        return datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    def __repr__(self) -> str:
        return (
            f"<GroupLog started={self.is_running} "
            f"queue={self.queue_size} "
            f"cached={len(self._cache)} "
            f"drops={self._drop_count}>"
        )


# =====================================================================
# Instance عالمي
# =====================================================================

group_log: Optional[GroupLog] = None


def init_group_log(db, bot) -> GroupLog:
    """يُنشئ ويهيّئ instance عالمي."""
    global group_log
    group_log = GroupLog(db, bot)
    return group_log


def get_group_log() -> Optional[GroupLog]:
    """يُرجع الـinstance الحالي (or None)."""
    return group_log


__all__ = [
    "GroupLog",
    "group_log",
    "init_group_log",
    "get_group_log",
    "CANONICAL_LOG_KEY",
    "LEGACY_LOG_KEY",
]