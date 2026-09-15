# group_log.py
"""
group_log.py — نظام سجل قنوات المجموعات (v1.2.0)
=====================================================================
- سجل خاص لكل مجموعة (bot_groups.log_channel_id)
- سجل عام (settings.global_log_channel)
- أولوية: خاص → عام (fallback)
- Queue + Worker لتفادي حجب البوت
- Cache 60s لتقليل ضغط DB
- ✅ v1.2.0: get_running_loop + has_private + get_effective_target
  + drain + shutdown + حماية Worker مزدوج
=====================================================================
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


class GroupLog:
    """
    إدارة سجل قنوات المجموعات.

    - كل مجموعة لها قناة سجل خاصة (اختياري)
    - قناة سجل عامة (اختياري) — fallback
    """

    QUEUE_MAX_SIZE = 1000
    CACHE_TTL = 60

    def __init__(self, db, bot):
        self.db = db
        self.bot = bot

        # Cache
        self._cache: Dict[int, List[dict]] = {}
        self._cache_ts: Dict[int, float] = {}
        self._cache_ttl = self.CACHE_TTL

        # Global log channel cache
        self._global_chat_id: Optional[int] = None
        self._global_ts: float = 0.0

        # Queue + Worker
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=self.QUEUE_MAX_SIZE)
        self._worker_task: Optional[asyncio.Task] = None
        self._started = False

    # =================================================================
    # Cache
    # =================================================================

    def invalidate(self, group_id: Optional[int] = None) -> None:
        """إبطال الكاش — لمجموعة أو للكل."""
        if group_id is None:
            self._cache.clear()
            self._cache_ts.clear()
            self._global_ts = 0.0
            self._global_chat_id = None
        else:
            self._cache.pop(group_id, None)
            self._cache_ts.pop(group_id, None)

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
            ch = row.get("log_channel_id")
            return int(ch) if ch else None
        except Exception as e:
            logger.error(f"get_private({group_id}): {e}")
            return None

    async def has_private(self, group_id: int) -> bool:
        """هل للمجموعة قناة سجل خاصة؟"""
        return (await self.get_private(group_id)) is not None

    async def set_private(self, group_id: int, chat_id: int) -> bool:
        """يعيّن قناة سجل خاصة لمجموعة."""
        if not group_id or not chat_id:
            return False

        try:
            # 1) محاولة التحديث (المجموعة موجودة)
            n = await self.db.execute(
                "UPDATE bot_groups SET log_channel_id = ? "
                "WHERE chat_id = ?",
                (chat_id, group_id),
            )
            if n and n > 0:
                self.invalidate(group_id)
                return True

            # 2) المجموعة غير موجودة — أدخلها
            try:
                await self.db.execute(
                    "INSERT OR IGNORE INTO bot_groups "
                    "(chat_id, chat_name, log_channel_id, added_at, banned) "
                    "VALUES (?, ?, ?, ?, 0)",
                    (
                        group_id,
                        str(group_id),
                        chat_id,
                        datetime.now(timezone.utc).replace(tzinfo=None),
                    ),
                )
                # تأكيد الحفظ بعد الإدراج
                await self.db.execute(
                    "UPDATE bot_groups SET log_channel_id = ? "
                    "WHERE chat_id = ?",
                    (chat_id, group_id),
                )
            except Exception as ie:
                logger.warning(f"set_private insert fallback: {ie}")

            self.invalidate(group_id)
            return True
        except Exception as e:
            logger.error(f"set_private({group_id}, {chat_id}): {e}")
            return False

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

    # =================================================================
    # سجل عام
    # =================================================================

    async def _get_global(self) -> Optional[int]:
        """يُرجع معرّف السجل العام (cached)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # لا يوجد event loop — ارجع القيمة المخزّنة
            return self._global_chat_id

        now = loop.time()
        if (self._global_chat_id is not None
                and now - self._global_ts < self._cache_ttl):
            return self._global_chat_id

        try:
            v = await self.db.fetchval(
                "SELECT value FROM settings WHERE key = ?",
                ("global_log_channel",), default=None,
            )
            self._global_chat_id = int(v) if v else None
        except Exception as e:
            logger.warning(f"_get_global: {e}")
            self._global_chat_id = None

        self._global_ts = now
        return self._global_chat_id

    async def set_global(self, chat_id: int) -> bool:
        """يعيّن السجل العام."""
        if not chat_id:
            return False
        try:
            await self.db.execute(
                "INSERT OR REPLACE INTO settings (key, value) "
                "VALUES (?, ?)",
                ("global_log_channel", str(chat_id)),
            )
            self.invalidate()
            return True
        except Exception as e:
            logger.error(f"set_global: {e}")
            return False

    async def unset_global(self) -> bool:
        """يحذف السجل العام."""
        try:
            await self.db.execute(
                "DELETE FROM settings WHERE key = ?",
                ("global_log_channel",),
            )
            self.invalidate()
            return True
        except Exception as e:
            logger.error(f"unset_global: {e}")
            return False

    async def get_global(self) -> Optional[int]:
        """يرجع معرّف السجل العام."""
        return await self._get_global()

    # =================================================================
    # Resolution — أولوية: خاص → عام
    # =================================================================

    async def get_effective_target(self, group_id: int) -> Optional[int]:
        """
        ✅ v1.2.0: القناة التي سيُرسل إليها فعلياً (خاص → عام).
        مفيد لعرض "الحالية" في القائمة.
        """
        if not group_id:
            return None
        private = await self.get_private(group_id)
        if private:
            return private
        return await self._get_global()

    async def _resolve_targets(self, group_id: int) -> List[dict]:
        """
        القنوات التي سيُرسل إليها الحدث:
        - قناة خاصة إن وُجدت
        - وإلا: القناة العامة (fallback)
        """
        try:
            loop = asyncio.get_running_loop()
            now = loop.time()
        except RuntimeError:
            now = 0.0

        ts = self._cache_ts.get(group_id, 0.0)
        if group_id in self._cache and (now - ts) < self._cache_ttl:
            return self._cache[group_id]

        targets: List[dict] = []

        # 1) خاص
        private = await self.get_private(group_id)
        if private:
            targets.append({
                "chat_id": private,
                "events": ["all"],
                "source": "private",
            })
        else:
            # 2) عام (fallback)
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
    # الإرسال (Queue)
    # =================================================================

    def send(self, group_id: int, text: str,
             event: str = "general",
             parse_mode: str = "HTML",
             silent: bool = True) -> None:
        """
        يضع رسالة سجل في الطابور — لا يحجب التنفيذ.

        event: "general" | "users" | "broadcast" | "errors" | "buttons" | "all"
        """
        if not group_id or not text:
            return
        try:
            self._queue.put_nowait({
                "group_id": group_id,
                "text": text,
                "event": event,
                "parse_mode": parse_mode,
                "silent": silent,
            })
        except asyncio.QueueFull:
            logger.warning(
                f"group_log queue full — dropping "
                f"(grp={group_id}, event={event})"
            )

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

                    for t in targets:
                        try:
                            await self.bot.send_message(
                                chat_id=t["chat_id"],
                                text=item["text"],
                                parse_mode=item["parse_mode"],
                                disable_notification=item["silent"],
                            )
                        except Exception as e:
                            err_msg = str(e).lower()
                            # لو القناة محذوفة أو البوت طُرد منها
                            if any(kw in err_msg for kw in (
                                "chat not found",
                                "bot was kicked",
                                "channel not found",
                                "chat_id is empty",
                                "user is deactivated",
                                "bot is not a member",
                            )):
                                logger.warning(
                                    f"⚠️ قناة السجل غير متاحة "
                                    f"(grp={item['group_id']}, "
                                    f"src={t['source']}) — تنظيف"
                                )
                                # نظّف القناة الفاسدة
                                try:
                                    if t["source"] == "private":
                                        await self.unset_private(
                                            item["group_id"]
                                        )
                                    elif t["source"] == "global":
                                        await self.unset_global()
                                except Exception:
                                    pass
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

    def start(self) -> None:
        """يبدأ العامل الخلفي (idempotent — لا يبدأ مرتين)."""
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
        """يوقف العامل فوراً (بدون انتظار الطابور)."""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            self._started = False

    async def drain(self, timeout: float = 5.0) -> int:
        """
        ✅ v1.2.0: ينتظر انتهاء الطابور (بحد أقصى timeout ثانية).
        يرجّع عدد الرسائل المتبقية (إن انتهت المهلة).
        """
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
        """
        ✅ v1.2.0: إيقاف لطيف — ينتظر الطابور ثم يُلغي العامل.
        """
        try:
            await self.drain(timeout=drain_timeout)
        finally:
            self.stop()

    @property
    def queue_size(self) -> int:
        """حجم الطابور الحالي."""
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        """هل العامل يعمل؟"""
        return (
            self._worker_task is not None
            and not self._worker_task.done()
        )

    # =================================================================
    # مساعدات
    # =================================================================

    @staticmethod
    def fmt_user(user) -> str:
        """تنسيق اسم مستخدم للعرض."""
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
        """الوقت الحالي بتوقيت UTC."""
        return datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    def __repr__(self) -> str:
        return (
            f"<GroupLog started={self.is_running} "
            f"queue={self.queue_size} "
            f"cached={len(self._cache)}>"
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
    """يُرجع الـinstance الحالي (أو None)."""
    return group_log


__all__ = [
    "GroupLog",
    "group_log",
    "init_group_log",
    "get_group_log",
]