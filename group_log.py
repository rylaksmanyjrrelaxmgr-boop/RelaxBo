# group_log.py
"""
group_log.py — نظام سجل قنوات المجموعات الذكي (v1.3.1)
=====================================================================
v1.3.1 (PostgreSQL compatibility):
    ✅ INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING
    ✅ INSERT OR REPLACE → INSERT ... ON CONFLICT (key) DO UPDATE
    ✅ توافق كامل مع PostgreSQL + SQLite 3.24+

v1.3.0 (ذكاء المشاركة):
    ✅ get_groups_using_channel — قائمة المجموعات المشاركة
    ✅ get_channel_share_count — عدد المجموعات
    ✅ set_private يُعيد dict مع معلومات المشاركة
    ✅ send مع رأس ذكي يحمل اسم المجموعة المصدر
    ✅ _worker: تنظيف جماعي عند فشل القناة
    ✅ unset_private_bulk للتنظيف الجماعي
    ✅ كاش لأسماء المجموعات

v1.2.0 (أساس):
    ✅ get_running_loop + has_private + get_effective_target
    ✅ drain + shutdown + حماية Worker مزدوج
=====================================================================
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


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

        # Cache
        self._cache: Dict[int, List[dict]] = {}
        self._cache_ts: Dict[int, float] = {}
        self._cache_ttl = self.CACHE_TTL

        # ✅ v1.3.0: أسماء المجموعات (cache للأداء)
        self._group_names: Dict[int, str] = {}

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
            self._group_names.clear()
        else:
            self._cache.pop(group_id, None)
            self._cache_ts.pop(group_id, None)
            self._group_names.pop(group_id, None)

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
            # دعم dict و Row
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
        """
        ✅ v1.3.0: قائمة المجموعات التي تستخدم نفس القناة.

        يُرجع: [{'chat_id': int, 'chat_name': str, 'banned': int}, ...]
        """
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
            # ✅ تحويل آمن إلى dict
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
        """✅ v1.3.0: عدد المجموعات التي تستخدم نفس القناة."""
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

    # =================================================================
    # ✅ v1.3.0: set_private مع تقرير ذكي
    # =================================================================

    async def set_private(self, group_id: int, chat_id: int) -> Dict:
        """
        ✅ v1.3.0: يعيّن قناة سجل خاصة.

        يُرجع dict:
        {
            'ok': bool,
            'shared': bool,          # هل القناة مشتركة؟
            'share_count': int,      # عدد المجموعات الأخرى
            'other_groups': list,    # أسماء المجموعات الأخرى
        }
        """
        result = {
            'ok': False,
            'shared': False,
            'share_count': 0,
            'other_groups': [],
        }

        if not group_id or not chat_id:
            return result

        # ✅ فحص المشاركة أولاً
        try:
            others = await self.get_groups_using_channel(
                chat_id, exclude_group_id=group_id
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
                (chat_id, group_id),
            )
            if n and n > 0:
                self.invalidate(group_id)
                result['ok'] = True
                return result

            # لو المجموعة غير موجودة — أدرجها
            # ✅ v1.3.1: ON CONFLICT DO NOTHING (متوافق PostgreSQL + SQLite 3.24+)
            try:
                await self.db.execute(
                    "INSERT INTO bot_groups "
                    "(chat_id, chat_name, log_channel_id, added_at, banned) "
                    "VALUES (?, ?, ?, ?, 0) "
                    "ON CONFLICT (chat_id) DO NOTHING",
                    (
                        group_id,
                        str(group_id),
                        chat_id,
                        datetime.now(timezone.utc).replace(tzinfo=None),
                    ),
                )
                await self.db.execute(
                    "UPDATE bot_groups SET log_channel_id = ? "
                    "WHERE chat_id = ?",
                    (chat_id, group_id),
                )
                result['ok'] = True
            except Exception as ie:
                logger.warning(f"set_private insert fallback: {ie}")

            self.invalidate(group_id)
            return result
        except Exception as e:
            logger.error(f"set_private({group_id}, {chat_id}): {e}")
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
        """✅ v1.3.0: إزالة القناة من عدة مجموعات."""
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
    # سجل عام
    # =================================================================

    async def _get_global(self) -> Optional[int]:
        """يُرجع معرّف السجل العام (cached)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
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
        if not chat_id:
            return False
        try:
            # ✅ v1.3.1: ON CONFLICT DO UPDATE (متوافق PostgreSQL + SQLite 3.24+)
            await self.db.execute(
                "INSERT INTO settings (key, value) "
                "VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                ("global_log_channel", str(chat_id)),
            )
            self.invalidate()
            return True
        except Exception as e:
            logger.error(f"set_global: {e}")
            return False

    async def unset_global(self) -> bool:
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
            now = 0.0

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
    # ✅ v1.3.0: send مع رأس ذكي
    # =================================================================

    def send(self, group_id: int, text: str,
             event: str = "general",
             parse_mode: str = "HTML",
             silent: bool = True,
             show_group_header: bool = True) -> None:
        """
        يضع رسالة سجل في الطابور.

        ✅ v1.3.0: show_group_header — إضافة رأس باسم المجموعة
                    تلقائياً لتمييز المصدر عند المشاركة.
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
                "show_group_header": show_group_header,
            })
        except asyncio.QueueFull:
            logger.warning(
                f"group_log queue full — dropping "
                f"(grp={group_id}, event={event})"
            )

    async def _build_message_text(self, item: dict) -> str:
        """
        ✅ v1.3.0: بناء النص النهائي مع رأس ذكي.
        - قناة خاصة بمجموعة واحدة → بلا رأس
        - قناة مشتركة أو عامة → رأس باسم المجموعة
        """
        base_text = item["text"]
        group_id = item["group_id"]

        if not item.get("show_group_header", True):
            return base_text

        # هل القناة مشتركة؟
        try:
            private = await self.get_private(group_id)
            if not private:
                # يستخدم السجل العام → أضف الرأس دائماً
                shared = True
            else:
                count = await self.get_channel_share_count(
                    private, exclude_group_id=group_id
                )
                shared = count > 0
        except Exception:
            shared = True

        if not shared:
            return base_text

        # أضف رأس باسم المجموعة
        group_name = await self._get_group_name(group_id)
        header = (
            f"<b>📌 من: {group_name}</b>\n"
            f"<code>{group_id}</code>\n"
            f"━━━━━━━━━━━━━━━\n"
        )
        return header + base_text

    # =================================================================
    # Worker
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

                    # ✅ v1.3.0: بناء النص مع الرأس الذكي
                    final_text = await self._build_message_text(item)

                    for t in targets:
                        try:
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
        """
        ✅ v1.3.0: تنظيف ذكي للقناة الفاسدة.
        - قناة عامة → احذف الإعداد العام
        - قناة خاصة → احذف من **كل** المجموعات المشاركة
        """
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
    """يُرجع الـinstance الحالي (or None)."""
    return group_log


__all__ = [
    "GroupLog",
    "group_log",
    "init_group_log",
    "get_group_log",
]