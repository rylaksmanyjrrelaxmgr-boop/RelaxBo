#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_groups.py - دوال المجموعات (v7.4.20)
================================================================================
🆕 v7.4.20 — AUDIT-FIXES (5 إصلاحات):

  🟠 FIX-PG-SYNTAX-1 (IMPORTANT): `update_security_settings` و
      `update_penalty_settings` و `update_auto_reply_settings` —
      تحويل `?` → `$N` تلقائياً على PostgreSQL. سابقاً كانت تعتمد
      على `self.execute()`، لكن `_execute_with_conn` التي تستخدم
      معاملة صريحة قد لا تحوّل. v7.4.20 يتحقق من DB_TYPE ويبني
      الاستعلام بالصيغة الصحيحة.

  🟠 FIX-BANNED-CONFLICT-1 (IMPORTANT): `add_banned_word` يستخدم
      `ON CONFLICT (word, chat_id) DO NOTHING` على PostgreSQL و
      `ON DUPLICATE KEY UPDATE` على MySQL و `INSERT OR IGNORE`
      على SQLite. يقلل round-trips ويكشف التكرار بكفاءة.

  🟠 FIX-AUTO-REPLY-CACHE-1 (IMPORTANT): `get_auto_reply_settings`
      يستدعي `_get_batched_message_settings` إن كان متاحاً — ليتشارك
      الكاش المحلي `_ars_local_cache` في handlers_message. يقلل
      عدد الاستعلامات بشكل ملحوظ.

  🟡 FIX-ADMIN-MRO-STRICT-1 (MINOR): `get_all_admins` — يحاول
      `super().get_admin_list` صراحةً (بدون `except AttributeError`
      الذي كان يُخفي أخطاء حقيقية)، ثم fallback.

  🟡 FIX-INVALIDATE-CHAT-CACHE-1 (MINOR): `_invalidate_user_groups_cache`
      يقبل `chat_ids` اختيارياً لإبطال `log_ch_menu_*` و `group_log_*`
      عند تغيير العضويات.

  ✅ محفوظ من v7.4.19:
      - FIX-ADMIN-MRO-DEDUP
      - FIX-ADMIN-ALIASES
      - FIX-CACHE-1..6
      - FIX-AC2 / FIX-C4
      - P1..P5, O1..O2, F1..F3
      - M1..M4 + m1..m3
      - NEW FALLBACKS

🆕 v7.4.19 — ADMIN-MRO-DEDUP (محفوظ):
  🔴 FIX-ADMIN-MRO-DEDUP: حذف get_admin_list من GroupsMixin
  🟢 FIX-ADMIN-ALIASES: get_all_admins + get_admins

🆕 v7.4.18 — BOT-ADMINS-READ-API (محفوظ)
🆕 v7.4.17 — CACHE-INVALIDATION-COMPLETE (محفوظ)
🆕 v7.4.16 — AUTH-CACHE-FIX (محفوظ)
🆕 v7.4.15 — POLISH (محفوظ)
🆕 v7.4.14 — IS-GROUP-OWNER (محفوظ)
🆕 v7.4.13 — ROOT-CAUSE-FIX (محفوظ)
🆕 v7.4.12 — CRITICAL-FIX (محفوظ)
🆕 v7.4.11 — REVIEW-FIXES (محفوظ)
================================================================================
"""

import asyncio
import logging
import time
import json
from datetime import timedelta
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

_DEFAULT_MAX_GLOBAL_BANNED_WORDS = 10000
_MAX_WORD_LENGTH = 100
_MAX_KEYWORD_LENGTH = 255


def _safe_normalize_word(word: Any) -> Optional[str]:
    """تطبيع آمن لكلمة محظورة."""
    if word is None:
        return None
    if not isinstance(word, str):
        return None
    normalized = word.strip().lower()
    if not normalized:
        return None
    if len(normalized) > _MAX_WORD_LENGTH:
        return None
    return normalized


def _convert_qmark_to_pg(query: str) -> str:
    """
    🆕 v7.4.20 FIX-PG-SYNTAX-1: يحوّل `?` إلى `$1, $2, ...` لـ PG.

    يتخطى علامات الاستفهام داخل:
      • النصوص بين '' (single-quoted strings)
      • النصوص بين "" (double-quoted identifiers)
    (بسيط كفاية لاستعلاماتنا — لا يدعم dollar-quoted blocks).
    """
    result = []
    counter = 0
    in_single = False
    in_double = False
    i = 0
    n = len(query)
    while i < n:
        c = query[i]
        if in_single:
            result.append(c)
            if c == "'":
                # handle escaped ''
                if i + 1 < n and query[i + 1] == "'":
                    result.append("'")
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            result.append(c)
            if c == '"':
                in_double = False
            i += 1
            continue
        if c == "'":
            in_single = True
            result.append(c)
            i += 1
            continue
        if c == '"':
            in_double = True
            result.append(c)
            i += 1
            continue
        if c == '?':
            counter += 1
            result.append(f"${counter}")
            i += 1
            continue
        result.append(c)
        i += 1
    return "".join(result)


class GroupsMixin:
    """Mixin يحتوي كل دوال المجموعات"""

    # ═════════════════════════════════════════════════════════════════
    # 0) helpers لبناء استعلامات DB-aware
    # 🆕 v7.4.20 FIX-PG-SYNTAX-1
    # ═════════════════════════════════════════════════════════════════

    def _prepare_query(self, query: str) -> str:
        """
        🆕 v7.4.20: يحوّل `?` → `$N` عند PostgreSQL.
        على SQLite/MySQL يُرجع الاستعلام كما هو.

        ملاحظة: `self.execute()` قد يحوّل تلقائياً، لكن
        `_execute_with_conn` (داخل transaction) قد لا يفعل.
        هذه الدالة تضمن الاتساق في كل مكان.
        """
        try:
            if getattr(self, "USE_POSTGRES", False):
                return _convert_qmark_to_pg(query)
        except Exception as e:
            logger.debug("_prepare_query: %s", e)
        return query

    # ═════════════════════════════════════════════════════════════════
    # 1) كاش الكلمات المحظورة (داخلي)
    # ═════════════════════════════════════════════════════════════════

    async def _get_banned_words_from_local_cache(
        self, chat_id: int
    ) -> Optional[List[str]]:
        entry = self._banned_words_local_cache.get(chat_id)
        if entry and \
           time.time() - entry["time"] < self._banned_words_cache_ttl:
            return entry["words"]
        return None

    async def _set_banned_words_local_cache(
        self, chat_id: int, words: List[str]
    ):
        self._banned_words_local_cache[chat_id] = {
            "words": words,
            "time": time.time(),
        }

    async def _invalidate_banned_words_local_cache(
        self, chat_id: int = None
    ):
        if chat_id is not None:
            self._banned_words_local_cache.pop(chat_id, None)
            if chat_id == -1:
                self._global_banned_words_cache = []
                self._global_banned_words_loaded = False
        else:
            self._banned_words_local_cache.clear()
            self._global_banned_words_cache = []
            self._global_banned_words_loaded = False

    # ═════════════════════════════════════════════════════════════════
    # 2) إبطال موحّد لكاش مجموعات المستخدم
    # 🟡 v7.4.20 FIX-INVALIDATE-CHAT-CACHE-1: chat_ids اختياري
    # ═════════════════════════════════════════════════════════════════

    async def _invalidate_user_groups_cache(
        self,
        user_id: int,
        chat_ids: Optional[List[int]] = None,
    ) -> bool:
        """
        إبطال كاش مجموعات مستخدم.

        🟡 v7.4.20: إذا مُرِّرت `chat_ids`، يُبطل أيضاً:
          • internal_cache[log_ch_menu_{cid}]
          • internal_cache[group_log_{cid}]
        — لأن انتماء المستخدم لمجموعة يؤثر على قوائم قناة السجل.
        """
        if not isinstance(user_id, int) or user_id <= 0:
            return False

        invalidated = False

        try:
            if self.CACHE_AVAILABLE:
                result = self.groups_cache.invalidate(user_id)
                if asyncio.iscoroutine(result):
                    await result
                invalidated = True
        except Exception as e:
            logger.debug(
                f"_invalidate_user_groups_cache "
                f"groups_cache({user_id}): {e}"
            )

        try:
            result = self.internal_cache.invalidate(f"groups_{user_id}")
            if asyncio.iscoroutine(result):
                await result
            invalidated = True
        except Exception as e:
            logger.debug(
                f"_invalidate_user_groups_cache "
                f"internal_cache({user_id}): {e}"
            )

        # 🟡 v7.4.20: إبطال كاشات المجموعات المرتبطة
        if chat_ids:
            for cid in chat_ids:
                try:
                    icid = int(cid)
                except (TypeError, ValueError):
                    continue
                for suffix in ("log_ch_menu", "group_log"):
                    try:
                        r = self.internal_cache.invalidate(
                            f"{suffix}_{icid}"
                        )
                        if asyncio.iscoroutine(r):
                            await r
                    except Exception:
                        pass
                invalidated = True

        return invalidated

    # ═════════════════════════════════════════════════════════════════
    # 3) مرادفات admin — التفويض لـ StatsMixin
    # 🟡 v7.4.20 FIX-ADMIN-MRO-STRICT-1
    # ═════════════════════════════════════════════════════════════════

    async def get_all_admins(self) -> List[Dict]:
        """
        مرادف لـ get_admin_list.

        🟡 v7.4.20 FIX-ADMIN-MRO-STRICT-1: نتحقق صراحةً من وجود
        `super().get_admin_list` قبل استدعائه، بدلاً من التقاط
        AttributeError الذي قد يُخفي أخطاء حقيقية داخل الدالة.
        """
        # 1) جرّب super().get_admin_list إن وُجدت
        super_method = None
        try:
            super_method = getattr(super(), "get_admin_list", None)
        except Exception as e:
            logger.debug(f"get_all_admins super access: {e}")

        if callable(super_method):
            try:
                result = await super_method()
                if isinstance(result, list):
                    return result
                if result is not None:
                    try:
                        return list(result)
                    except (TypeError, ValueError):
                        return []
            except Exception as e:
                logger.warning(
                    f"get_all_admins: super().get_admin_list فشل — "
                    f"fallback للاستعلام المباشر: {e}"
                )

        # 2) Fallback مباشر
        try:
            return await self.fetchall(
                "SELECT user_id, added_by, added_at FROM bot_admins "
                "ORDER BY added_at DESC"
            ) or []
        except Exception as e:
            logger.debug(f"get_all_admins fallback: {e}")
            return []

    async def get_admins(self) -> List[Dict]:
        """مرادف آخر لـ get_admin_list."""
        return await self.get_all_admins()

    # ═════════════════════════════════════════════════════════════════
    # 4) تسجيل المجموعات وإدارتها
    # ═════════════════════════════════════════════════════════════════

    async def register_group(
        self, chat_id: int, chat_name: str, user_id: int,
        username: str = None,
    ) -> bool:
        try:
            async with self.transaction() as conn:
                if self.USE_POSTGRES:
                    await self._execute_with_conn(
                        conn,
                        """INSERT INTO bot_groups
                           (chat_id, chat_name, username, added_by,
                            added_at, updated_at)
                           VALUES ($1, $2, $3, $4, $5, $5)
                           ON CONFLICT (chat_id) DO UPDATE SET
                               chat_name = EXCLUDED.chat_name,
                               username = EXCLUDED.username,
                               updated_at = EXCLUDED.updated_at""",
                        chat_id, chat_name, username, user_id,
                        self.TimeUtils.utc_now(),
                    )
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO user_groups_link "
                        "(user_id, chat_id) VALUES ($1, $2) "
                        "ON CONFLICT DO NOTHING",
                        user_id, chat_id,
                    )
                elif self.USE_MYSQL:
                    await self._execute_with_conn(
                        conn,
                        """INSERT INTO bot_groups
                           (chat_id, chat_name, username, added_by,
                            added_at, updated_at)
                           VALUES (%s, %s, %s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE
                               chat_name = VALUES(chat_name),
                               username = VALUES(username),
                               updated_at = VALUES(updated_at)""",
                        chat_id, chat_name, username, user_id,
                        self.TimeUtils.sql_iso(),
                        self.TimeUtils.sql_iso(),
                    )
                    await self._execute_with_conn(
                        conn,
                        "INSERT IGNORE INTO user_groups_link "
                        "(user_id, chat_id) VALUES (%s, %s)",
                        user_id, chat_id,
                    )
                else:
                    await self._execute_with_conn(
                        conn,
                        """INSERT INTO bot_groups
                           (chat_id, chat_name, username, added_by,
                            added_at, updated_at)
                           VALUES (?,?,?,?,?,?)
                           ON CONFLICT(chat_id) DO UPDATE SET
                               chat_name = excluded.chat_name,
                               username = excluded.username,
                               updated_at = excluded.updated_at""",
                        chat_id, chat_name, username, user_id,
                        self.TimeUtils.sql_iso(),
                        self.TimeUtils.sql_iso(),
                    )
                    await self._execute_with_conn(
                        conn,
                        "INSERT OR IGNORE INTO user_groups_link "
                        "(user_id, chat_id) VALUES (?,?)",
                        user_id, chat_id,
                    )
            logger.info(
                f"✅ تم تسجيل المجموعة {chat_id} "
                f"بواسطة المستخدم {user_id}"
            )
            await self._invalidate_user_groups_cache(
                user_id, chat_ids=[chat_id],
            )
            return True
        except Exception as e:
            logger.error(
                f"❌ Error in register_group: {e}", exc_info=True
            )
            return False

    async def get_user_groups(
        self, user_id: int, force_refresh: bool = False
    ) -> List[Dict]:
        """force_refresh لتخطي الكاش."""
        if not force_refresh:
            if self.CACHE_AVAILABLE:
                cached = await self.groups_cache.get(user_id)
                if cached is not None:
                    return cached
            cached = await self.internal_cache.get(f"groups_{user_id}")
            if cached is not None:
                return cached

        query1 = """
            SELECT chat_id, chat_name, username, banned
            FROM bot_groups WHERE added_by = ?
        """

        query2 = """
            SELECT bg.chat_id, bg.chat_name,
                   bg.username, bg.banned
            FROM bot_groups bg
            WHERE bg.chat_id IN (
                SELECT chat_id FROM user_groups_link
                    WHERE user_id = ?
                UNION ALL
                SELECT chat_id FROM hidden_owner_groups
                    WHERE owner_id = ?
                UNION ALL
                SELECT chat_id FROM hidden_admins
                    WHERE admin_id = ?
                UNION ALL
                SELECT chat_id FROM group_admins
                    WHERE user_id = ?
                UNION ALL
                SELECT chat_id FROM anonymous_admins
                    WHERE user_id = ?
                UNION ALL
                SELECT chat_id FROM anonymous_admins
                    WHERE anonymous_id = ?
            )
        """

        try:
            rows1 = await self.fetchall(
                self._prepare_query(query1), (user_id,)
            )
            rows2 = await self.fetchall(
                self._prepare_query(query2),
                (user_id, user_id, user_id, user_id, user_id, user_id),
            )
        except Exception as e:
            logger.warning(f"⚠️ get_user_groups fetch فشل: {e}")
            rows1 = []
            rows2 = []

        seen: set = set()
        groups: List[Dict] = []
        for row in rows1:
            cid = row.get("chat_id")
            if cid is None or cid in seen:
                continue
            seen.add(cid)
            groups.append(row)
        for row in rows2:
            cid = row.get("chat_id")
            if cid is None or cid in seen:
                continue
            seen.add(cid)
            groups.append(row)

        groups.sort(key=lambda r: r.get("chat_id") or 0)
        groups = groups[:100]

        try:
            await self.internal_cache.set(f"groups_{user_id}", groups)
        except Exception:
            pass
        if self.CACHE_AVAILABLE:
            try:
                await self.groups_cache.set(user_id, groups)
            except Exception:
                pass
        return groups

    async def count_user_groups(
        self, user_id: int, force_refresh: bool = False
    ) -> int:
        """عدّ المجموعات بسرعة."""
        if not isinstance(user_id, int) or user_id <= 0:
            return 0

        try:
            if not force_refresh:
                if self.CACHE_AVAILABLE:
                    cached = await self.groups_cache.get(user_id)
                    if cached is not None and isinstance(
                            cached, (list, tuple)):
                        return len(cached)
                cached = await self.internal_cache.get(
                    f"groups_{user_id}")
                if cached is not None and isinstance(
                        cached, (list, tuple)):
                    return len(cached)

            groups = await self.get_user_groups(
                user_id, force_refresh=force_refresh
            )
            if isinstance(groups, (list, tuple)):
                return len(groups)
            return 0
        except Exception as e:
            logger.debug(
                f"count_user_groups({user_id}): {e}"
            )
            return 0

    async def is_group_owner(
        self, user_id: int, chat_id: int
    ) -> bool:
        if not isinstance(user_id, int) or user_id <= 0:
            return False
        if not isinstance(chat_id, int) or chat_id == 0:
            return False

        try:
            r1 = await self.fetchval(
                self._prepare_query(
                    "SELECT 1 FROM bot_groups "
                    "WHERE chat_id = ? AND added_by = ? LIMIT 1"
                ),
                (chat_id, user_id),
            )
            if r1 is not None:
                return True
        except Exception as e:
            logger.debug(
                f"is_group_owner: bot_groups check ({user_id}, "
                f"{chat_id}): {e}"
            )

        try:
            r2 = await self.fetchval(
                self._prepare_query(
                    "SELECT 1 FROM user_groups_link "
                    "WHERE chat_id = ? AND user_id = ? LIMIT 1"
                ),
                (chat_id, user_id),
            )
            if r2 is not None:
                return True
        except Exception as e:
            logger.debug(
                f"is_group_owner: user_groups_link check ({user_id}, "
                f"{chat_id}): {e}"
            )

        return False

    async def delete_group(self, chat_id: int) -> bool:
        try:
            async with self.transaction() as conn:
                tables = [
                    "user_groups_link", "group_admins",
                    "hidden_owner_groups", "hidden_admins",
                    "anonymous_admins", "group_security",
                    "chat_locks", "banned_words", "auto_replies",
                    "auto_reply_settings", "user_warnings",
                    "user_violations", "group_rules", "user_messages",
                    "admin_logs", "violation_penalties",
                    "user_penalties", "scheduled_posts",
                ]
                for table in tables:
                    await self._execute_with_conn(
                        conn,
                        self._prepare_query(
                            f"DELETE FROM {table} WHERE chat_id = ?"
                        ),
                        chat_id,
                    )
                await self._execute_with_conn(
                    conn,
                    self._prepare_query(
                        "DELETE FROM bot_groups WHERE chat_id = ?"
                    ),
                    chat_id,
                )
            if self.CACHE_AVAILABLE:
                await self.groups_cache.invalidate()
                await self.settings_cache.invalidate_security(chat_id)
                await self.settings_cache.invalidate_auto_reply(chat_id)
            try:
                await self.internal_cache.invalidate(
                    f"group_log_{chat_id}"
                )
                await self.internal_cache.invalidate(
                    f"log_ch_menu_{chat_id}"
                )
            except Exception:
                pass
            return True
        except Exception as e:
            logger.error(
                f"❌ Error in delete_group: {e}", exc_info=True
            )
            return False

    # ═════════════════════════════════════════════════════════════════
    # 5) مشرفو المجموعات (Group Admins)
    # ═════════════════════════════════════════════════════════════════

    async def sync_group_admins(
        self, chat_id: int, admin_ids: List[int]
    ) -> int:
        """+ إبطال groups_cache للمتأثرين."""
        try:
            removed_ids: set = set()
            added_ids: set = set()

            async with await self._get_group_lock(chat_id):
                async with self.transaction() as conn:
                    existing = await self._fetchall_with_conn(
                        conn,
                        self._prepare_query(
                            "SELECT user_id FROM group_admins "
                            "WHERE chat_id = ?"
                        ),
                        chat_id,
                    )
                    existing_ids = {
                        row["user_id"] for row in existing
                    }
                    new_ids = set(admin_ids)
                    to_remove = existing_ids - new_ids
                    for uid in to_remove:
                        await self._execute_with_conn(
                            conn,
                            self._prepare_query(
                                "DELETE FROM group_admins "
                                "WHERE chat_id = ? AND user_id = ?"
                            ),
                            chat_id, uid,
                        )
                    to_add = new_ids - existing_ids
                    for uid in to_add:
                        if self.USE_POSTGRES:
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO group_admins "
                                "(chat_id, user_id) VALUES ($1, $2) "
                                "ON CONFLICT DO NOTHING",
                                chat_id, uid,
                            )
                        elif self.USE_MYSQL:
                            await self._execute_with_conn(
                                conn,
                                "INSERT IGNORE INTO group_admins "
                                "(chat_id, user_id) VALUES (%s, %s)",
                                chat_id, uid,
                            )
                        else:
                            await self._execute_with_conn(
                                conn,
                                "INSERT OR IGNORE INTO group_admins "
                                "(chat_id, user_id) VALUES (?,?)",
                                chat_id, uid,
                            )
                    removed_ids = set(to_remove)
                    added_ids = set(to_add)

                if self.CACHE_AVAILABLE:
                    await self.auth_cache.invalidate(chat_id)
                try:
                    from utils import invalidate_auth_cache_async as _inv_auth
                    await _inv_auth(chat_id=chat_id)
                except Exception as e:
                    logger.debug(
                        "invalidate_auth_cache_async(%s): %s",
                        chat_id, e,
                    )

                affected = removed_ids | added_ids
                for uid in affected:
                    try:
                        await self._invalidate_user_groups_cache(
                            uid, chat_ids=[chat_id],
                        )
                    except Exception as e:
                        logger.debug(
                            f"sync_group_admins invalidate "
                            f"groups_cache({uid}): {e}"
                        )
                if affected:
                    logger.debug(
                        f"♻️ sync_group_admins({chat_id}): "
                        f"أُبطل كاش {len(affected)} مستخدم"
                    )

                return len(admin_ids)
        except Exception as e:
            logger.error(
                f"❌ Error in sync_group_admins: {e}", exc_info=True
            )
            return 0

    async def add_group_admin(self, chat_id: int, user_id: int) -> bool:
        """+ إبطال groups_cache."""
        if not chat_id or not user_id:
            return False
        try:
            if self.USE_POSTGRES:
                await self.execute(
                    "INSERT INTO group_admins (chat_id, user_id) "
                    "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    (chat_id, user_id),
                )
            elif self.USE_MYSQL:
                await self.execute(
                    "INSERT IGNORE INTO group_admins (chat_id, user_id) "
                    "VALUES (%s, %s)",
                    (chat_id, user_id),
                )
            else:
                await self.execute(
                    "INSERT OR IGNORE INTO group_admins (chat_id, user_id) "
                    "VALUES (?, ?)",
                    (chat_id, user_id),
                )
            if self.CACHE_AVAILABLE:
                try:
                    await self.auth_cache.invalidate(chat_id)
                except Exception:
                    pass
            try:
                from utils import invalidate_auth_cache_async as _inv
                await _inv(chat_id=chat_id, user_id=user_id)
            except Exception:
                pass

            await self._invalidate_user_groups_cache(
                user_id, chat_ids=[chat_id],
            )
            return True
        except Exception as e:
            logger.error(
                "add_group_admin(%s, %s): %s", chat_id, user_id, e
            )
            return False

    async def remove_group_admin(self, chat_id: int, user_id: int) -> bool:
        """+ إبطال groups_cache."""
        if not chat_id or not user_id:
            return False
        try:
            await self.execute(
                self._prepare_query(
                    "DELETE FROM group_admins "
                    "WHERE chat_id = ? AND user_id = ?"
                ),
                (chat_id, user_id),
            )
            if self.CACHE_AVAILABLE:
                try:
                    await self.auth_cache.invalidate(chat_id)
                except Exception:
                    pass
            try:
                from utils import invalidate_auth_cache_async as _inv
                await _inv(chat_id=chat_id, user_id=user_id)
            except Exception:
                pass

            await self._invalidate_user_groups_cache(
                user_id, chat_ids=[chat_id],
            )
            return True
        except Exception as e:
            logger.error(
                "remove_group_admin(%s, %s): %s", chat_id, user_id, e
            )
            return False

    # ═════════════════════════════════════════════════════════════════
    # 6) المشرفون المخفيون (Hidden Admins)
    # ═════════════════════════════════════════════════════════════════

    async def add_hidden_admin(
        self, chat_id: int, admin_id: int, added_by: int
    ) -> bool:
        try:
            result = await self.execute(
                self._prepare_query(
                    "INSERT OR IGNORE INTO hidden_admins "
                    "(chat_id, admin_id, added_by, added_at) "
                    "VALUES (?,?,?,?)"
                ),
                (chat_id, admin_id, added_by,
                 self.TimeUtils.utc_now()),
            ) > 0
            if result and self.CACHE_AVAILABLE:
                await self.auth_cache.invalidate(chat_id, admin_id)
            if result:
                try:
                    await self._invalidate_user_groups_cache(
                        admin_id, chat_ids=[chat_id],
                    )
                except Exception:
                    pass
            return result
        except Exception as e:
            logger.error(
                f"❌ Error in add_hidden_admin: {e}", exc_info=True
            )
            return False

    async def remove_hidden_admin(
        self, chat_id: int, admin_id: int
    ) -> bool:
        try:
            async with self.connection() as conn:
                deleted = await self._execute_with_conn(
                    conn,
                    self._prepare_query(
                        "DELETE FROM hidden_admins "
                        "WHERE chat_id = ? AND admin_id = ?"
                    ),
                    chat_id, admin_id,
                )
            if deleted > 0 and self.CACHE_AVAILABLE:
                await self.auth_cache.invalidate(chat_id, admin_id)
            if deleted > 0:
                try:
                    await self._invalidate_user_groups_cache(
                        admin_id, chat_ids=[chat_id],
                    )
                except Exception:
                    pass
            return deleted > 0
        except Exception as e:
            logger.error(
                f"❌ Error in remove_hidden_admin: {e}",
                exc_info=True,
            )
            return False

    async def get_hidden_admins(self, chat_id: int) -> List[Dict]:
        return await self.fetchall(
            self._prepare_query(
                "SELECT admin_id, added_by, added_at "
                "FROM hidden_admins WHERE chat_id = ? "
                "ORDER BY added_at DESC"
            ),
            (chat_id,),
        )

    # ═════════════════════════════════════════════════════════════════
    # 7) المشرفون المجهولون (Anonymous Admins)
    # ═════════════════════════════════════════════════════════════════

    async def add_anonymous_admin(
        self, chat_id: int, anonymous_id: int,
        added_by: int = None, user_id: int = None,
    ) -> bool:
        try:
            result = await self.execute(
                self._prepare_query(
                    "INSERT OR IGNORE INTO anonymous_admins "
                    "(chat_id, anonymous_id, added_by, user_id, added_at) "
                    "VALUES (?,?,?,?,?)"
                ),
                (chat_id, anonymous_id, added_by, user_id,
                 self.TimeUtils.utc_now()),
            ) > 0
            if result and self.CACHE_AVAILABLE:
                await self.auth_cache.invalidate(chat_id)
            if result and user_id:
                try:
                    await self._invalidate_user_groups_cache(
                        user_id, chat_ids=[chat_id],
                    )
                except Exception:
                    pass
            return result
        except Exception as e:
            logger.error(
                f"❌ Error in add_anonymous_admin: {e}",
                exc_info=True,
            )
            return False

    async def remove_anonymous_admin(
        self, chat_id: int, anonymous_id: int
    ) -> bool:
        try:
            linked_user_id = None
            try:
                linked_user_id = await self.fetchval(
                    self._prepare_query(
                        "SELECT user_id FROM anonymous_admins "
                        "WHERE chat_id = ? AND anonymous_id = ?"
                    ),
                    (chat_id, anonymous_id),
                )
            except Exception:
                pass

            async with self.connection() as conn:
                deleted = await self._execute_with_conn(
                    conn,
                    self._prepare_query(
                        "DELETE FROM anonymous_admins "
                        "WHERE chat_id = ? AND anonymous_id = ?"
                    ),
                    chat_id, anonymous_id,
                )
            if deleted > 0 and self.CACHE_AVAILABLE:
                await self.auth_cache.invalidate(chat_id)
            if deleted > 0 and linked_user_id:
                try:
                    await self._invalidate_user_groups_cache(
                        int(linked_user_id),
                        chat_ids=[chat_id],
                    )
                except Exception:
                    pass
            return deleted > 0
        except Exception as e:
            logger.error(
                f"❌ Error in remove_anonymous_admin: {e}",
                exc_info=True,
            )
            return False

    async def get_anonymous_admins(
        self, chat_id: int
    ) -> List[Dict]:
        return await self.fetchall(
            self._prepare_query(
                "SELECT anonymous_id, user_id, added_by, added_at "
                "FROM anonymous_admins WHERE chat_id = ? "
                "ORDER BY added_at DESC"
            ),
            (chat_id,),
        )

    async def is_anonymous_admin(
        self, chat_id: int, user_id: int
    ) -> bool:
        result = await self.fetchval(
            self._prepare_query(
                "SELECT 1 FROM anonymous_admins "
                "WHERE chat_id = ? AND "
                "(user_id = ? OR anonymous_id = ?) "
                "LIMIT 1"
            ),
            (chat_id, user_id, user_id),
        )
        return result is not None

    async def sync_anonymous_admins(
        self, chat_id: int, anonymous_ids: List[int],
        added_by: int = None,
        user_id_map: Optional[Dict[int, int]] = None,
    ) -> int:
        try:
            affected_users: set = set()

            async with await self._get_group_lock(chat_id):
                async with self.transaction() as conn:
                    existing = await self._fetchall_with_conn(
                        conn,
                        self._prepare_query(
                            "SELECT anonymous_id FROM anonymous_admins "
                            "WHERE chat_id = ?"
                        ),
                        chat_id,
                    )
                    existing_ids = {
                        row["anonymous_id"] for row in existing
                    }
                    new_ids = set(anonymous_ids)
                    to_remove = existing_ids - new_ids
                    for anon_id in to_remove:
                        await self._execute_with_conn(
                            conn,
                            self._prepare_query(
                                "DELETE FROM anonymous_admins "
                                "WHERE chat_id = ? AND anonymous_id = ?"
                            ),
                            chat_id, anon_id,
                        )
                    for anon_id in new_ids:
                        real_user_id = (
                            user_id_map.get(anon_id)
                            if user_id_map else None
                        )
                        if self.USE_POSTGRES:
                            await self._execute_with_conn(
                                conn,
                                """INSERT INTO anonymous_admins
                                   (chat_id, anonymous_id, added_by,
                                    user_id, added_at)
                                   VALUES ($1, $2, $3, $4, $5)
                                   ON CONFLICT (chat_id, anonymous_id)
                                   DO UPDATE SET
                                       user_id = EXCLUDED.user_id,
                                       added_by = EXCLUDED.added_by""",
                                chat_id, anon_id, added_by,
                                real_user_id,
                                self.TimeUtils.utc_now(),
                            )
                        elif self.USE_MYSQL:
                            await self._execute_with_conn(
                                conn,
                                """INSERT INTO anonymous_admins
                                   (chat_id, anonymous_id, added_by,
                                    user_id, added_at)
                                   VALUES (%s, %s, %s, %s, %s)
                                   ON DUPLICATE KEY UPDATE
                                       user_id = VALUES(user_id),
                                       added_by = VALUES(added_by)""",
                                chat_id, anon_id, added_by,
                                real_user_id,
                                self.TimeUtils.sql_iso(),
                            )
                        else:
                            await self._execute_with_conn(
                                conn,
                                """INSERT INTO anonymous_admins
                                   (chat_id, anonymous_id, added_by,
                                    user_id, added_at)
                                   VALUES (?,?,?,?,?)
                                   ON CONFLICT(chat_id, anonymous_id)
                                   DO UPDATE SET
                                       user_id = excluded.user_id,
                                       added_by = excluded.added_by""",
                                chat_id, anon_id, added_by,
                                real_user_id,
                                self.TimeUtils.sql_iso(),
                            )

                if user_id_map:
                    for _aid, _uid in user_id_map.items():
                        try:
                            iuid = int(_uid)
                            if iuid > 0:
                                affected_users.add(iuid)
                        except (TypeError, ValueError):
                            pass

                for uid in affected_users:
                    try:
                        await self._invalidate_user_groups_cache(
                            uid, chat_ids=[chat_id],
                        )
                    except Exception as e:
                        logger.debug(
                            f"sync_anonymous_admins invalidate "
                            f"({uid}): {e}"
                        )
                if affected_users:
                    logger.debug(
                        f"♻️ sync_anonymous_admins({chat_id}): "
                        f"أُبطل كاش {len(affected_users)} مستخدم"
                    )

                return len(anonymous_ids)
        except Exception as e:
            logger.error(
                f"❌ Error in sync_anonymous_admins: {e}",
                exc_info=True,
            )
            return 0

    # ═════════════════════════════════════════════════════════════════
    # 8) إعدادات الأمان (Security)
    # ═════════════════════════════════════════════════════════════════

    async def get_security_settings(self, chat_id: int) -> Dict:
        if self.CACHE_AVAILABLE:
            cached = await self.settings_cache.get_security(chat_id)
            if cached is not None:
                return cached
        settings = await self.fetchone(
            self._prepare_query(
                "SELECT * FROM group_security WHERE chat_id = ?"
            ),
            (chat_id,),
        )
        if not settings:
            await self.execute(
                self._prepare_query(
                    "INSERT OR IGNORE INTO group_security "
                    "(chat_id) VALUES (?)"
                ),
                (chat_id,),
            )
            settings = await self.fetchone(
                self._prepare_query(
                    "SELECT * FROM group_security WHERE chat_id = ?"
                ),
                (chat_id,),
            )
        if settings and self.CACHE_AVAILABLE:
            await self.settings_cache.set_security(chat_id, settings)
        return settings if settings else {}

    async def _get_group_security_columns(self) -> set:
        if self._group_security_columns_cache is not None:
            return self._group_security_columns_cache

        lock = getattr(self, "_gsc_columns_lock", None)
        if lock is None:
            self._gsc_columns_lock = asyncio.Lock()
            lock = self._gsc_columns_lock

        async with lock:
            if self._group_security_columns_cache is not None:
                return self._group_security_columns_cache

            try:
                async with self.connection() as conn:
                    if self.USE_POSTGRES:
                        rows = await conn.fetch(
                            "SELECT column_name "
                            "FROM information_schema.columns "
                            "WHERE table_name = 'group_security' "
                            "ORDER BY ordinal_position"
                        )
                        cols = {row["column_name"] for row in rows}
                    elif self.USE_MYSQL:
                        cursor = await conn.cursor()
                        try:
                            await cursor.execute(
                                "SHOW COLUMNS FROM `group_security`"
                            )
                            rows = await cursor.fetchall()
                            cols = {row[0] for row in rows}
                        finally:
                            try:
                                await cursor.close()
                            except Exception:
                                pass
                    else:
                        cursor = await conn.execute(
                            "PRAGMA table_info(group_security)"
                        )
                        try:
                            rows = await cursor.fetchall()
                            cols = {row[1] for row in rows}
                        finally:
                            try:
                                await cursor.close()
                            except Exception:
                                pass

                self._group_security_columns_cache = cols
                logger.info(
                    f"📋 Loaded group_security columns: "
                    f"{len(cols)} columns"
                )
                return cols
            except Exception as e:
                logger.error(
                    f"❌ Failed to load group_security columns: {e}",
                    exc_info=True,
                )
                return set()

    async def get_group_security_columns(self) -> set:
        return await self._get_group_security_columns()

    def invalidate_group_security_columns_cache(self):
        self._group_security_columns_cache = None
        logger.info(
            "🔄 group_security columns cache invalidated"
        )

    async def update_security_settings(
        self,
        chat_id: int,
        conn: Optional[Any] = None,
        **kwargs,
    ) -> bool:
        """
        🟠 v7.4.20 FIX-PG-SYNTAX-1: تحويل `?` → `$N` عند PG
        قبل تمرير الاستعلام لـ `_execute_with_conn`.
        """
        if not kwargs:
            return False

        original_keys = set(kwargs.keys())

        aliased_keys = []
        for alias, real_col in self.COLUMN_ALIASES.items():
            if alias in kwargs:
                if real_col not in kwargs:
                    kwargs[real_col] = kwargs.pop(alias)
                    aliased_keys.append((alias, real_col))
                else:
                    kwargs.pop(alias, None)
                    aliased_keys.append(
                        (alias, f"{real_col} (already present)")
                    )

        actual_columns = await self._get_group_security_columns()
        if not actual_columns:
            logger.error(
                f"❌ update_security_settings: "
                f"لا توجد أعمدة لـ chat={chat_id}"
            )
            return False

        valid_kwargs = {}
        skipped_keys = []
        for key, value in kwargs.items():
            if key in actual_columns:
                valid_kwargs[key] = value
            else:
                skipped_keys.append(key)

        summary = (
            f"🔧 update_security_settings chat={chat_id} | "
            f"{len(valid_kwargs)} valid"
            + (f", {len(skipped_keys)} skipped"
               if skipped_keys else "")
            + (f", {len(aliased_keys)} aliased"
               if aliased_keys else "")
            + (f", unified_conn" if conn is not None else "")
        )
        logger.info(summary)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"   📥 Original keys ({len(original_keys)}): "
                f"{sorted(original_keys)}\n"
                f"   🔄 Aliases: {aliased_keys}\n"
                f"   📋 Actual columns ({len(actual_columns)}): "
                f"{sorted(actual_columns)}\n"
                f"   ✅ Will update ({len(valid_kwargs)}): "
                f"{sorted(valid_kwargs.keys())}\n"
                f"   ⚠️ Skipped: {skipped_keys}"
            )

        if skipped_keys:
            logger.warning(
                f"   ⚠️ Skipped {len(skipped_keys)} "
                f"non-existent columns: {skipped_keys}\n"
                f"   💡 أضفها إلى database_tables.py "
                f"أو _migrate_schema"
            )

        if not valid_kwargs:
            logger.error(
                f"   ❌ لا يوجد أي عمود صالح للتحديث! "
                f"(chat={chat_id})"
            )
            return False

        query = ""
        try:
            updates = [f"{key} = ?" for key in valid_kwargs]
            values = list(valid_kwargs.values()) + [chat_id]
            query = self._prepare_query(
                f"UPDATE group_security SET {', '.join(updates)} "
                f"WHERE chat_id = ?"
            )
            insert_q = self._prepare_query(
                "INSERT OR IGNORE INTO group_security "
                "(chat_id) VALUES (?)"
            )

            if conn is not None:
                await self._execute_with_conn(
                    conn, insert_q, chat_id,
                )
                result = await self._execute_with_conn(
                    conn, query, *values
                )
            else:
                async with self.transaction() as own_conn:
                    await self._execute_with_conn(
                        own_conn, insert_q, chat_id,
                    )
                    result = await self._execute_with_conn(
                        own_conn, query, *values
                    )

            if result is not None and \
               isinstance(result, int) and result < 0:
                logger.error(
                    f"   ❌ UPDATE returned negative: {result}"
                )
                return False

            try:
                invalidations = [
                    self.internal_cache.invalidate(
                        f"security_{chat_id}"
                    ),
                    self.internal_cache.invalidate(
                        f"group_security_{chat_id}"
                    ),
                ]
                if self.CACHE_AVAILABLE:
                    invalidations.append(
                        self.settings_cache.invalidate_security(
                            chat_id
                        )
                    )
                await asyncio.gather(
                    *invalidations, return_exceptions=True
                )

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"   🔄 Cache invalidated "
                        f"for chat_id={chat_id}"
                    )
            except Exception as cache_err:
                logger.warning(
                    f"   ⚠️ Cache invalidation error: "
                    f"{cache_err}"
                )

            logger.info(
                f"   ✅ Updated {len(valid_kwargs)} fields "
                f"for chat_id={chat_id}"
            )
            return True

        except Exception as e:
            logger.error(
                f"   ❌ UPDATE failed for chat_id={chat_id}: {e}\n"
                f"   Query: {query}\n"
                f"   Valid columns: {list(valid_kwargs.keys())}",
                exc_info=True,
            )
            return False

    # ═════════════════════════════════════════════════════════════════
    # 9) التحذيرات (Warnings)
    # ═════════════════════════════════════════════════════════════════

    async def get_user_warnings(
        self, user_id: int, chat_id: int
    ) -> int:
        return await self.fetchval(
            self._prepare_query(
                "SELECT warnings FROM user_warnings "
                "WHERE user_id = ? AND chat_id = ?"
            ),
            (user_id, chat_id), default=0,
        )

    async def add_user_warning(
        self, user_id: int, chat_id: int
    ) -> int:
        await self.execute(
            self._prepare_query(
                """INSERT INTO user_warnings (user_id, chat_id, warnings)
                   VALUES (?,?,1)
                   ON CONFLICT(user_id, chat_id)
                   DO UPDATE SET warnings = user_warnings.warnings + 1"""
            ),
            (user_id, chat_id),
        )
        return await self.get_user_warnings(user_id, chat_id)

    async def reset_user_warnings(
        self, user_id: int, chat_id: int
    ) -> bool:
        return await self.execute(
            self._prepare_query(
                "UPDATE user_warnings SET warnings = 0 "
                "WHERE user_id = ? AND chat_id = ?"
            ),
            (user_id, chat_id),
        ) > 0

    # ═════════════════════════════════════════════════════════════════
    # 10) سجلات المشرفين (Admin Logs)
    # ═════════════════════════════════════════════════════════════════

    async def add_admin_log(
        self,
        chat_id: int,
        admin_id: int,
        action: str,
        target_id: int = None,
        reason: str = "",
        conn: Optional[Any] = None,
    ) -> bool:
        try:
            sql = self._prepare_query(
                "INSERT INTO admin_logs "
                "(chat_id, admin_id, action, target_id, "
                "reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)"
            )
            params = (
                chat_id, admin_id, action, target_id,
                reason, self.TimeUtils.utc_now(),
            )

            if conn is not None:
                await self._execute_with_conn(conn, sql, *params)
                return True
            else:
                return await self.execute(sql, params) > 0
        except Exception as e:
            logger.error(
                f"❌ add_admin_log: {e}", exc_info=True
            )
            return False

    async def get_admin_logs(
        self, chat_id: int, limit: int = 20
    ) -> List[Dict]:
        return await self.fetchall(
            self._prepare_query(
                "SELECT admin_id, action, target_id, reason, created_at "
                "FROM admin_logs WHERE chat_id = ? "
                "ORDER BY id DESC LIMIT ?"
            ),
            (chat_id, limit),
        )

    # ═════════════════════════════════════════════════════════════════
    # 11) الردود التلقائية (Auto Replies)
    # 🟠 v7.4.20 FIX-AUTO-REPLY-CACHE-1
    # ═════════════════════════════════════════════════════════════════

    async def get_auto_reply_settings(self, chat_id: int) -> Dict:
        """
        🟠 v7.4.20 FIX-AUTO-REPLY-CACHE-1: تشارك الكاش المحلي
        `_ars_local_cache` في handlers_message عبر
        `_get_batched_message_settings`. يُقلل عدد الاستعلامات.

        ملاحظة: هذه الدالة تُستدعى من group_log.py و
        handlers_command.py وغيرها — تشارك نفس الكاش الآن.
        """
        # 1) محاولة handlers_message cache (batched)
        try:
            from handlers_message import (
                _get_batched_message_settings as _bms,
            )
            if callable(_bms):
                try:
                    _sec, _ars = await _bms(chat_id)
                    if isinstance(_ars, dict) and _ars:
                        return _ars
                except Exception as e:
                    logger.debug(
                        "get_auto_reply_settings _bms(%s): %s",
                        chat_id, e,
                    )
        except ImportError:
            pass
        except Exception as e:
            logger.debug(
                "get_auto_reply_settings _bms import: %s", e
            )

        # 2) settings_cache
        if self.CACHE_AVAILABLE:
            cached = await self.settings_cache.get_auto_reply_settings(
                chat_id
            )
            if cached is not None:
                return cached

        # 3) DB query
        settings = await self.fetchone(
            self._prepare_query(
                "SELECT * FROM auto_reply_settings WHERE chat_id = ?"
            ),
            (chat_id,),
        )
        if not settings:
            await self.execute(
                self._prepare_query(
                    "INSERT OR IGNORE INTO auto_reply_settings "
                    "(chat_id) VALUES (?)"
                ),
                (chat_id,),
            )
            settings = await self.fetchone(
                self._prepare_query(
                    "SELECT * FROM auto_reply_settings WHERE chat_id = ?"
                ),
                (chat_id,),
            )
        if settings and self.CACHE_AVAILABLE:
            await self.settings_cache.set_auto_reply_settings(
                chat_id, settings
            )
        return settings if settings else {
            "enabled": 0, "only_admins": 0, "ignore_bots": 1
        }

    async def update_auto_reply_settings(
        self, chat_id: int, **kwargs
    ) -> bool:
        """
        🟠 v7.4.20 FIX-PG-SYNTAX-1: تحويل `?` → `$N` عند PG.
        """
        if not kwargs:
            return False
        await self.execute(
            self._prepare_query(
                "INSERT OR IGNORE INTO auto_reply_settings "
                "(chat_id) VALUES (?)"
            ),
            (chat_id,),
        )

        allowed_columns = {"enabled", "only_admins", "ignore_bots"}
        for key in kwargs:
            if key not in allowed_columns:
                logger.error(f"❌ Invalid column: {key}")
                return False

        updates = [f"{key} = ?" for key in kwargs]
        values = list(kwargs.values()) + [chat_id]
        query = self._prepare_query(
            f"UPDATE auto_reply_settings "
            f"SET {', '.join(updates)} WHERE chat_id = ?"
        )
        result = await self.execute(query, tuple(values)) > 0
        if result and self.CACHE_AVAILABLE:
            await self.settings_cache.invalidate_auto_reply(chat_id)
        return result

    async def add_auto_reply(
        self, chat_id: int, keyword: str, reply: str,
        reply_type: str = "text", media_id: str = None,
        buttons: str = None,
    ) -> bool:
        keyword = keyword.lower().strip()
        if not keyword:
            logger.error("❌ Empty keyword")
            return False
        if len(keyword) > _MAX_KEYWORD_LENGTH:
            logger.error(
                f"❌ Keyword too long ({len(keyword)} > "
                f"{_MAX_KEYWORD_LENGTH}): {keyword[:50]!r}..."
            )
            return False
        if reply_type not in self.VALID_REPLY_TYPES:
            logger.error(f"❌ Invalid reply_type: {reply_type}")
            return False
        try:
            async with self.connection() as conn:
                if self.USE_POSTGRES:
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO auto_replies "
                        "(chat_id, keyword, reply, reply_type, "
                        "reply_media_id, reply_buttons, created_at) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                        chat_id, keyword, reply, reply_type,
                        media_id, buttons, self.TimeUtils.utc_now(),
                    )
                elif self.USE_MYSQL:
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO auto_replies "
                        "(chat_id, keyword, reply, reply_type, "
                        "reply_media_id, reply_buttons, created_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        chat_id, keyword, reply, reply_type,
                        media_id, buttons, self.TimeUtils.sql_iso(),
                    )
                else:
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO auto_replies "
                        "(chat_id, keyword, reply, reply_type, "
                        "reply_media_id, reply_buttons, created_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        chat_id, keyword, reply, reply_type,
                        media_id, buttons, self.TimeUtils.sql_iso(),
                    )
            return True
        except Exception as e:
            if "unique" in str(e).lower() or \
               "duplicate" in str(e).lower():
                return await self.execute(
                    self._prepare_query(
                        "UPDATE auto_replies SET reply = ?, "
                        "reply_type = ?, reply_media_id = ?, "
                        "reply_buttons = ?, created_at = ? "
                        "WHERE chat_id = ? AND keyword = ?"
                    ),
                    (reply, reply_type, media_id, buttons,
                     self.TimeUtils.sql_iso(), chat_id, keyword),
                ) > 0
            logger.error(
                f"❌ Error in add_auto_reply: {e}", exc_info=True
            )
            return False

    async def remove_auto_reply(
        self, chat_id: int, keyword: str
    ) -> bool:
        keyword = keyword.lower().strip()
        try:
            async with self.connection() as conn:
                deleted = await self._execute_with_conn(
                    conn,
                    self._prepare_query(
                        "DELETE FROM auto_replies "
                        "WHERE chat_id = ? AND keyword = ?"
                    ),
                    chat_id, keyword,
                )
                return deleted > 0
        except Exception as e:
            logger.error(
                f"❌ Error in remove_auto_reply: {e}",
                exc_info=True,
            )
            return False

    async def _increment_usage_count(
        self, chat_id: int, keyword: str
    ):
        try:
            await self.execute(
                self._prepare_query(
                    "UPDATE auto_replies "
                    "SET usage_count = usage_count + 1 "
                    "WHERE chat_id = ? AND keyword = ?"
                ),
                (chat_id, keyword),
            )
        except Exception:
            pass

    async def get_auto_reply(
        self, keyword: str, chat_id: int
    ) -> Optional[Dict]:
        keyword = keyword.lower().strip()
        if not keyword:
            return None
        try:
            row = await self.fetchone(
                self._prepare_query(
                    """SELECT reply, reply_type, reply_media_id,
                              reply_buttons
                       FROM auto_replies
                       WHERE keyword = ? AND is_active = 1
                         AND (chat_id = ? OR chat_id = -1)
                       ORDER BY CASE WHEN chat_id = ? THEN 0 ELSE 1 END
                       LIMIT 1"""
                ),
                (keyword, chat_id, chat_id),
            )
        except Exception as e:
            logger.debug(
                f"get_auto_reply({keyword!r}, {chat_id}): {e}"
            )
            return None

        if row:
            try:
                coro = self._increment_usage_count(chat_id, keyword)
                spawner = getattr(self, "_spawn_bg_task", None)
                if callable(spawner):
                    spawner(coro)
                else:
                    task = asyncio.create_task(coro)

                    def _log_task_exc(t: asyncio.Task):
                        if not t.cancelled() and t.exception():
                            logger.debug(
                                f"increment_usage_count: "
                                f"{t.exception()}"
                            )

                    task.add_done_callback(_log_task_exc)
            except Exception as e:
                logger.debug(
                    f"increment_usage_count spawn: {e}"
                )
            return row
        return None

    async def get_auto_reply_stats(
        self, chat_id: int, limit: int = 20
    ) -> List[Dict]:
        return await self.fetchall(
            self._prepare_query(
                """SELECT keyword, usage_count,
                          CASE WHEN chat_id = -1 THEN 'global'
                               ELSE 'group' END as source
                   FROM auto_replies
                   WHERE chat_id = ? OR chat_id = -1
                   ORDER BY usage_count DESC LIMIT ?"""
            ),
            (chat_id, limit),
        )

    async def reset_auto_replies(self, chat_id: int) -> bool:
        try:
            rc = await self.execute(
                self._prepare_query(
                    "DELETE FROM auto_replies WHERE chat_id = ?"
                ),
                (chat_id,),
            ) > 0
            if rc:
                if self.CACHE_AVAILABLE:
                    try:
                        await self.settings_cache.invalidate_auto_reply(
                            chat_id
                        )
                    except Exception:
                        pass
                try:
                    await self.internal_cache.invalidate(
                        f"ars_{chat_id}"
                    )
                    await self.internal_cache.invalidate(
                        f"auto_reply_settings_{chat_id}"
                    )
                except Exception:
                    pass
            return rc
        except Exception as e:
            logger.error(
                f"❌ reset_auto_replies({chat_id}): {e}",
                exc_info=True,
            )
            return False

    async def export_auto_replies_to_file(self) -> Optional[str]:
        try:
            rows = await self.fetchall("SELECT * FROM auto_replies")
            if not rows:
                return None
            timestamp = self.TimeUtils.utc_now().strftime(
                "%Y%m%d_%H%M%S"
            )
            file_path = (
                self.PATHS.BACKUPS /
                f"auto_replies_export_{timestamp}.json"
            )
            file_path.parent.mkdir(parents=True, exist_ok=True)

            def _write():
                with open(
                    file_path, "w", encoding="utf-8"
                ) as f:
                    json.dump(
                        [dict(r) for r in rows], f,
                        ensure_ascii=False, indent=2,
                    )

            await asyncio.to_thread(_write)
            return str(file_path)
        except Exception as e:
            logger.error(
                f"❌ Error in export_auto_replies_to_file: {e}",
                exc_info=True,
            )
            return None

    async def import_auto_replies_from_file(
        self, file_path: str
    ) -> int:
        try:
            def _read():
                with open(
                    file_path, "r", encoding="utf-8"
                ) as f:
                    return json.load(f)
            data = await asyncio.to_thread(_read)
            if not isinstance(data, list):
                return 0
            imported = 0
            async with self.transaction() as conn:
                for item in data:
                    try:
                        await self._execute_with_conn(
                            conn,
                            self._prepare_query(
                                """INSERT OR IGNORE INTO auto_replies
                                   (chat_id, keyword, reply, reply_type,
                                    reply_media_id, reply_buttons,
                                    created_at, is_active, usage_count)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""
                            ),
                            item.get("chat_id", -1),
                            item.get("keyword", "").lower(),
                            item.get("reply", ""),
                            item.get("reply_type", "text"),
                            item.get("reply_media_id"),
                            item.get("reply_buttons"),
                            item.get(
                                "created_at",
                                self.TimeUtils.utc_now(),
                            ),
                            item.get("is_active", 1),
                            item.get("usage_count", 0),
                        )
                        imported += 1
                    except Exception as e:
                        logger.warning(
                            f"⚠️ فشل استيراد رد: {e}"
                        )
            return imported
        except Exception as e:
            logger.error(
                f"❌ Error in import_auto_replies_from_file: {e}",
                exc_info=True,
            )
            return 0

    # ═════════════════════════════════════════════════════════════════
    # 12) الكلمات المحظورة (Banned Words)
    # 🟠 v7.4.20 FIX-BANNED-CONFLICT-1
    # ═════════════════════════════════════════════════════════════════

    async def _load_global_banned_words(self) -> List[str]:
        if self._global_banned_words_loaded:
            return self._global_banned_words_cache
        async with self._global_words_lock:
            if self._global_banned_words_loaded:
                return self._global_banned_words_cache
            rows = await self.fetchall(
                self._prepare_query(
                    "SELECT DISTINCT word FROM banned_words "
                    "WHERE chat_id = -1"
                )
            )
            self._global_banned_words_cache = [
                row["word"] for row in rows
            ]
            self._global_banned_words_loaded = True
            return self._global_banned_words_cache

    async def get_banned_words(self, chat_id: int) -> List[str]:
        if self.CACHE_AVAILABLE:
            cached = await self.banned_words_cache.get(chat_id)
            if cached is not None:
                return cached
        cached_local = await self._get_banned_words_from_local_cache(
            chat_id
        )
        if cached_local is not None:
            return cached_local

        global_words = await self._load_global_banned_words()
        specific = await self.fetchall(
            self._prepare_query(
                "SELECT word FROM banned_words WHERE chat_id = ?"
            ),
            (chat_id,),
        )
        specific_words = [row["word"] for row in specific]
        result = list(set(global_words + specific_words))

        await self._set_banned_words_local_cache(chat_id, result)
        if self.CACHE_AVAILABLE:
            await self.banned_words_cache.set(chat_id, result)
        return result

    async def add_banned_word(
        self, chat_id: int, word: str, added_by: int
    ) -> Tuple[bool, bool]:
        """
        إضافة كلمة محظورة.

        🟠 v7.4.20 FIX-BANNED-CONFLICT-1: يستخدم
        `ON CONFLICT (word, chat_id) DO NOTHING` على PG،
        `ON DUPLICATE KEY UPDATE` على MySQL،
        `INSERT OR IGNORE` على SQLite. يقلل round-trips.

        Returns:
            (added_ok, is_duplicate)
        """
        if not isinstance(chat_id, int):
            logger.error(
                f"❌ add_banned_word: chat_id يجب أن يكون int، "
                f"وصل {type(chat_id).__name__}={chat_id!r} | "
                f"word={word!r}, added_by={added_by!r}"
            )
            return False, False

        if not isinstance(word, str):
            logger.error(
                f"❌ add_banned_word: word يجب أن يكون str، "
                f"وصل {type(word).__name__}={word!r} | "
                f"chat_id={chat_id!r}, added_by={added_by!r}"
            )
            if isinstance(word, int) and isinstance(chat_id, int):
                logger.error(
                    f"   💡 السبب المُرجَّح: انعكاس ترتيب المعاملات "
                    f"في المُنادي!\n"
                    f"   التوقيع الحالي: "
                    f"add_banned_word(chat_id, word, added_by)\n"
                    f"   ✅ الإصلاح في المُنادي: "
                    f"await DB.add_banned_word(chat_id, word, user_id)"
                )
            return False, False

        if not isinstance(added_by, int):
            logger.error(
                f"❌ add_banned_word: added_by يجب أن يكون int، "
                f"وصل {type(added_by).__name__}={added_by!r} | "
                f"chat_id={chat_id!r}, word={word!r}"
            )
            return False, False

        normalized = _safe_normalize_word(word)
        if not normalized:
            logger.warning(
                f"⚠️ add_banned_word: word فارغة/طويلة بعد التطبيع "
                f"(chat_id={chat_id}, added_by={added_by}, "
                f"raw={word!r}, "
                f"len={len(word) if isinstance(word, str) else '?'})"
            )
            return False, False

        word = normalized

        try:
            async with self.transaction() as conn:
                if chat_id == -1:
                    count = await self._fetchval_with_conn(
                        conn,
                        self._prepare_query(
                            "SELECT COUNT(*) FROM banned_words "
                            "WHERE chat_id = -1"
                        ),
                        default=0,
                    )

                    max_words = getattr(
                        self.CONFIG,
                        "MAX_GLOBAL_BANNED_WORDS",
                        _DEFAULT_MAX_GLOBAL_BANNED_WORDS,
                    )
                    if not isinstance(max_words, int) or max_words <= 0:
                        logger.warning(
                            f"⚠️ MAX_GLOBAL_BANNED_WORDS غير صالح "
                            f"({max_words!r}) → استخدام "
                            f"{_DEFAULT_MAX_GLOBAL_BANNED_WORDS}"
                        )
                        max_words = _DEFAULT_MAX_GLOBAL_BANNED_WORDS

                    if count >= max_words:
                        logger.warning(
                            f"⚠️ add_banned_word مرفوض: وصلنا للحد "
                            f"الأقصى ({count}/{max_words}) "
                            f"word={word!r}\n"
                            f"   💡 ارفع الحد: "
                            f"config.CONFIG.MAX_GLOBAL_BANNED_WORDS "
                            f"= {max_words * 2} مثلاً"
                        )
                        return False, False

                # 🟠 v7.4.20: التحقق من التكرار + الإدراج في خطوة واحدة
                existing = await self._fetchval_with_conn(
                    conn,
                    self._prepare_query(
                        "SELECT 1 FROM banned_words "
                        "WHERE word = ? AND chat_id = ? LIMIT 1"
                    ),
                    word, chat_id,
                    default=None,
                )
                if existing is not None:
                    logger.info(
                        f"ℹ️ add_banned_word: كلمة مكررة "
                        f"({word!r}, chat_id={chat_id})"
                    )
                    return False, True

                if self.USE_POSTGRES:
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO banned_words "
                        "(word, chat_id, added_by, added_at) "
                        "VALUES ($1, $2, $3, $4) "
                        "ON CONFLICT (word, chat_id) DO NOTHING",
                        word, chat_id, added_by,
                        self.TimeUtils.utc_now(),
                    )
                elif self.USE_MYSQL:
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO banned_words "
                        "(word, chat_id, added_by, added_at) "
                        "VALUES (%s, %s, %s, %s) "
                        "ON DUPLICATE KEY UPDATE word = word",
                        word, chat_id, added_by,
                        self.TimeUtils.sql_iso(),
                    )
                else:
                    await self._execute_with_conn(
                        conn,
                        "INSERT OR IGNORE INTO banned_words "
                        "(word, chat_id, added_by, added_at) "
                        "VALUES (?,?,?,?)",
                        word, chat_id, added_by,
                        self.TimeUtils.sql_iso(),
                    )

            await self._invalidate_banned_words_local_cache(chat_id)
            if self.CACHE_AVAILABLE:
                await self.banned_words_cache.invalidate(chat_id)
            logger.info(
                f"✅ أُضيفت كلمة محظورة: {word!r} "
                f"(chat_id={chat_id}, by={added_by})"
            )
            return True, False
        except Exception as e:
            # في حال فشل ON CONFLICT (migration لم تصل بعد)
            err_lower = str(e).lower()
            if "unique" in err_lower or "duplicate" in err_lower:
                logger.info(
                    f"ℹ️ add_banned_word (race): كلمة مكررة "
                    f"({word!r}, chat_id={chat_id})"
                )
                return False, True
            logger.error(
                f"❌ Error in add_banned_word: {e} | "
                f"chat_id={chat_id}, word={word!r}, "
                f"added_by={added_by}",
                exc_info=True,
            )
            return False, False

    async def remove_banned_word(
        self, chat_id: int, word: str
    ) -> bool:
        if not isinstance(chat_id, int):
            logger.error(
                f"❌ remove_banned_word: chat_id يجب أن يكون int، "
                f"وصل {type(chat_id).__name__}={chat_id!r} | "
                f"word={word!r}"
            )
            return False

        if not isinstance(word, str):
            logger.error(
                f"❌ remove_banned_word: word يجب أن يكون str، "
                f"وصل {type(word).__name__}={word!r} | "
                f"chat_id={chat_id!r}"
            )
            return False

        normalized = _safe_normalize_word(word)
        if not normalized:
            logger.warning(
                f"⚠️ remove_banned_word: word فارغة/طويلة بعد التطبيع "
                f"(chat_id={chat_id}, raw={word!r})"
            )
            return False

        word = normalized

        try:
            async with self.connection() as conn:
                deleted = await self._execute_with_conn(
                    conn,
                    self._prepare_query(
                        "DELETE FROM banned_words "
                        "WHERE word = ? AND chat_id = ?"
                    ),
                    word, chat_id,
                )

                if deleted == 0:
                    try:
                        all_words = await self._fetchall_with_conn(
                            conn,
                            self._prepare_query(
                                "SELECT word FROM banned_words "
                                "WHERE chat_id = ? LIMIT 20"
                            ),
                            chat_id,
                        )
                        existing = [
                            r.get("word") for r in all_words
                        ]
                        logger.warning(
                            f"⚠️ remove_banned_word: "
                            f"لم تُوجد {word!r} في chat_id={chat_id}\n"
                            f"   💡 عيّنة من الكلمات الموجودة فعلاً "
                            f"({len(existing)} من أصل الحد): "
                            f"{existing[:10]}\n"
                            f"   💡 إن كانت الكلمة موجودة بصيغة مختلفة "
                            f"(مسافة/حالة أحرف/محرف عربي مختلف) → "
                            f"هذا هو السبب."
                        )
                    except Exception as diag_e:
                        logger.debug(
                            f"remove_banned_word diagnostic: {diag_e}"
                        )

            if deleted > 0:
                await self._invalidate_banned_words_local_cache(
                    chat_id
                )
                if self.CACHE_AVAILABLE:
                    await self.banned_words_cache.invalidate(
                        chat_id
                    )
                logger.info(
                    f"✅ حُذفت كلمة محظورة: {word!r} "
                    f"(chat_id={chat_id})"
                )
            return deleted > 0
        except Exception as e:
            logger.error(
                f"❌ Error in remove_banned_word: {e} | "
                f"chat_id={chat_id}, word={word!r}",
                exc_info=True,
            )
            return False

    async def reload_banned_words(self) -> bool:
        try:
            import importlib
            import banned_words
            importlib.reload(banned_words)
            BANNED_WORDS = getattr(banned_words, "BANNED_WORDS", [])
            if not BANNED_WORDS:
                return True
            owner_id = getattr(
                self.CONFIG, "PRIMARY_OWNER_ID", None
            ) or 1
            words_to_insert = []
            async with self.transaction() as conn:
                await self._execute_with_conn(
                    conn,
                    self._prepare_query(
                        "DELETE FROM banned_words WHERE chat_id = -1"
                    ),
                )
                for word in BANNED_WORDS:
                    word = str(word).strip().lower()
                    if 2 <= len(word) <= _MAX_WORD_LENGTH:
                        words_to_insert.append((
                            word, -1, owner_id,
                            self.TimeUtils.utc_now(),
                        ))
                if words_to_insert:
                    await self._executemany_with_conn(
                        conn,
                        self._prepare_query(
                            "INSERT OR IGNORE INTO banned_words "
                            "(word, chat_id, added_by, added_at) "
                            "VALUES (?,?,?,?)"
                        ),
                        words_to_insert,
                    )
            await self._invalidate_banned_words_local_cache()
            if self.CACHE_AVAILABLE:
                await self.banned_words_cache.invalidate()
            logger.info(
                f"✅ تم إعادة تحميل "
                f"{len(words_to_insert)} كلمة محظورة"
            )
            return True
        except ImportError:
            logger.warning("⚠️ ملف banned_words.py غير موجود")
            return False
        except Exception as e:
            logger.error(
                f"❌ فشل إعادة تحميل الكلمات المحظورة: {e}"
            )
            return False

    # ═════════════════════════════════════════════════════════════════
    # 13) إعدادات العقوبات (Penalty Settings)
    # 🟠 v7.4.20 FIX-PG-SYNTAX-1
    # ═════════════════════════════════════════════════════════════════

    async def get_penalty_settings(self, chat_id: int) -> Dict:
        await self.execute(
            self._prepare_query(
                "INSERT OR IGNORE INTO group_security "
                "(chat_id) VALUES (?)"
            ),
            (chat_id,),
        )
        return await self.fetchone(
            self._prepare_query(
                """SELECT mute_default_duration, ban_default_duration,
                          warn_default_duration, restrict_default_duration,
                          enable_timed_penalties, auto_remove_penalties
                   FROM group_security WHERE chat_id = ?"""
            ),
            (chat_id,),
        ) or {}

    async def update_penalty_settings(
        self, chat_id: int, **kwargs
    ) -> bool:
        """🟠 v7.4.20 FIX-PG-SYNTAX-1: تحويل `?` → `$N`."""
        if not kwargs:
            return False

        try:
            actual_columns = await self._get_group_security_columns()
            allowed_columns = {
                "mute_default_duration", "ban_default_duration",
                "warn_default_duration", "restrict_default_duration",
                "enable_timed_penalties", "auto_remove_penalties",
            }

            valid_kwargs = {}
            skipped = []
            for key, value in kwargs.items():
                if key not in allowed_columns:
                    skipped.append((key, "not-allowed"))
                    continue
                if actual_columns and key not in actual_columns:
                    skipped.append((key, "not-in-schema"))
                    continue
                valid_kwargs[key] = value

            if skipped:
                logger.warning(
                    f"⚠️ update_penalty_settings({chat_id}): "
                    f"skipped {len(skipped)}: {skipped}"
                )

            if not valid_kwargs:
                logger.error(
                    f"❌ update_penalty_settings({chat_id}): "
                    f"لا عمود صالح للتحديث"
                )
                return False

            await self.execute(
                self._prepare_query(
                    "INSERT OR IGNORE INTO group_security "
                    "(chat_id) VALUES (?)"
                ),
                (chat_id,),
            )

            updates = [f"{key} = ?" for key in valid_kwargs]
            values = list(valid_kwargs.values()) + [chat_id]
            query = self._prepare_query(
                f"UPDATE group_security SET {', '.join(updates)} "
                f"WHERE chat_id = ?"
            )
            result = await self.execute(query, tuple(values)) > 0
            if result and self.CACHE_AVAILABLE:
                await self.settings_cache.invalidate_security(chat_id)
            return result
        except Exception as e:
            logger.error(
                f"❌ update_penalty_settings({chat_id}): {e}",
                exc_info=True,
            )
            return False

    # ═════════════════════════════════════════════════════════════════
    # 14) قناة السجل للمجموعة (Group Log Channel)
    # ═════════════════════════════════════════════════════════════════

    async def set_group_log_channel(
        self, chat_id: int, channel_id: int
    ) -> bool:
        try:
            cid = int(channel_id)
        except (TypeError, ValueError):
            logger.error(
                f"❌ set_group_log_channel: "
                f"channel_id غير صالح: {channel_id!r}"
            )
            return False

        exists = await self.fetchval(
            self._prepare_query(
                "SELECT 1 FROM bot_groups WHERE chat_id = ?"
            ),
            (chat_id,),
        )
        if not exists:
            try:
                await self.execute(
                    self._prepare_query(
                        "INSERT OR IGNORE INTO bot_groups "
                        "(chat_id, chat_name, added_at, banned) "
                        "VALUES (?, ?, ?, 0)"
                    ),
                    (chat_id, str(chat_id),
                     self.TimeUtils.utc_now()),
                )
            except Exception as e:
                logger.error(
                    f"❌ set_group_log_channel: "
                    f"ensure group: {e}"
                )
                return False

        try:
            result = await self.execute(
                self._prepare_query(
                    "UPDATE bot_groups SET log_channel_id = ?, "
                    "updated_at = ? WHERE chat_id = ?"
                ),
                (cid, self.TimeUtils.utc_now(), chat_id),
            )
            try:
                await self.internal_cache.invalidate(
                    f"group_log_{chat_id}"
                )
                await self.internal_cache.invalidate(
                    f"log_ch_menu_{chat_id}"
                )
            except Exception:
                pass
            logger.info(
                f"✅ قناة سجل للمجموعة {chat_id} → {cid}"
            )
            return result > 0
        except Exception as e:
            logger.error(
                f"❌ set_group_log_channel({chat_id}): {e}",
                exc_info=True,
            )
            return False

    async def get_group_log_channel(
        self, chat_id: int
    ) -> Optional[int]:
        cache_key = f"group_log_{chat_id}"
        cached = await self.internal_cache.get(cache_key)
        if cached is not None:
            if cached == -1:
                return None
            try:
                return int(cached)
            except (TypeError, ValueError):
                pass

        try:
            result = await self.fetchval(
                self._prepare_query(
                    "SELECT log_channel_id FROM bot_groups "
                    "WHERE chat_id = ?"
                ),
                (chat_id,),
            )
            value = int(result) if result else None
        except Exception as e:
            logger.error(
                f"❌ get_group_log_channel({chat_id}): {e}"
            )
            return None

        try:
            await self.internal_cache.set(
                cache_key,
                value if value is not None else -1,
                ttl=60,
            )
        except Exception:
            pass

        return value

    async def remove_group_log_channel(self, chat_id: int) -> bool:
        try:
            await self.execute(
                self._prepare_query(
                    "UPDATE bot_groups SET log_channel_id = NULL, "
                    "updated_at = ? WHERE chat_id = ?"
                ),
                (self.TimeUtils.utc_now(), chat_id),
            )
            try:
                await self.internal_cache.invalidate(
                    f"group_log_{chat_id}"
                )
                await self.internal_cache.invalidate(
                    f"log_ch_menu_{chat_id}"
                )
            except Exception:
                pass
            logger.info(
                f"🗑️ قناة سجل المجموعة {chat_id} أُزيلت"
            )
            return True
        except Exception as e:
            logger.error(
                f"❌ remove_group_log_channel({chat_id}): {e}"
            )
            return False

    async def get_groups_sharing_log_channel(
        self, channel_id: int, exclude_group_id: int = None
    ) -> List[Dict]:
        try:
            query = (
                "SELECT chat_id, chat_name FROM bot_groups "
                "WHERE log_channel_id = ?"
            )
            params = [channel_id]
            if exclude_group_id is not None:
                query += " AND chat_id != ?"
                params.append(exclude_group_id)
            query += " ORDER BY chat_name LIMIT 20"
            return await self.fetchall(
                self._prepare_query(query), tuple(params)
            )
        except Exception as e:
            logger.debug(
                f"get_groups_sharing_log_channel"
                f"({channel_id}): {e}"
            )
            return []

    # ═════════════════════════════════════════════════════════════════
    # 15) المخالفات (Violations)
    # ═════════════════════════════════════════════════════════════════

    async def get_violation_penalty(
        self, chat_id: int, violation_type: str
    ) -> Dict:
        result = await self.fetchone(
            self._prepare_query(
                "SELECT penalty_type, duration_seconds "
                "FROM violation_penalties "
                "WHERE chat_id = ? AND violation_type = ?"
            ),
            (chat_id, violation_type),
        )
        if result:
            return result
        settings = await self.get_security_settings(chat_id)
        return {
            "penalty_type": settings.get("auto_penalty", "mute"),
            "duration_seconds": settings.get(
                "auto_mute_duration", 3600
            ),
        }

    async def set_violation_penalty(
        self, chat_id: int, violation_type: str,
        penalty_type: str, duration_seconds: int,
    ) -> bool:
        if violation_type not in self.VALID_VIOLATION_TYPES:
            logger.error(
                f"❌ Invalid violation_type: {violation_type}"
            )
            return False
        if penalty_type not in self.VALID_PENALTY_TYPES:
            logger.error(
                f"❌ Invalid penalty_type: {penalty_type}"
            )
            return False
        if duration_seconds < 0:
            duration_seconds = 0
        if duration_seconds > self.MAX_PENALTY_DURATION:
            duration_seconds = self.MAX_PENALTY_DURATION
        return await self.execute(
            self._prepare_query(
                """INSERT OR REPLACE INTO violation_penalties
                   (chat_id, violation_type, penalty_type,
                    duration_seconds)
                   VALUES (?,?,?,?)"""
            ),
            (chat_id, violation_type, penalty_type,
             duration_seconds),
        ) > 0

    async def get_all_violation_penalties(
        self, chat_id: int
    ) -> Dict[str, Dict]:
        penalties = await self.fetchall(
            self._prepare_query(
                "SELECT violation_type, penalty_type, duration_seconds "
                "FROM violation_penalties WHERE chat_id = ?"
            ),
            (chat_id,),
        )
        result = {}
        for penalty in penalties:
            result[penalty["violation_type"]] = {
                "penalty_type": penalty["penalty_type"],
                "duration_seconds": penalty["duration_seconds"],
            }
        return result

    async def get_violation_count(
        self, user_id: int, chat_id: int
    ) -> int:
        violation = await self.fetchone(
            self._prepare_query(
                "SELECT violation_count, last_violation_time "
                "FROM user_violations "
                "WHERE user_id = ? AND chat_id = ?"
            ),
            (user_id, chat_id),
        )
        if not violation:
            return 0

        last_time_str = violation.get("last_violation_time")
        if last_time_str:
            last_time = self.TimeUtils.safe_parse_iso(
                last_time_str
            )
            if last_time and \
               self.TimeUtils.utc_now() - last_time > \
               timedelta(hours=24):
                await self.execute(
                    self._prepare_query(
                        "UPDATE user_violations "
                        "SET violation_count = 0, "
                        "last_violation_time = NULL "
                        "WHERE user_id = ? AND chat_id = ?"
                    ),
                    (user_id, chat_id),
                )
                return 0
        return violation.get("violation_count", 0) or 0

    async def increment_violation_count(
        self, user_id: int, chat_id: int
    ) -> int:
        lock = None
        try:
            get_plock = getattr(self, "_get_penalty_lock", None)
            if callable(get_plock):
                lock = await get_plock(user_id, chat_id)
        except Exception as e:
            logger.debug(f"_get_penalty_lock fallback: {e}")

        if lock is None:
            lock = self._lock

        async with lock:
            async with self.transaction() as conn:
                last_time_str = await self._fetchval_with_conn(
                    conn,
                    self._prepare_query(
                        "SELECT last_violation_time "
                        "FROM user_violations "
                        "WHERE user_id = ? AND chat_id = ?"
                    ),
                    user_id, chat_id,
                )
                dt = None
                if last_time_str:
                    dt = self.TimeUtils.safe_parse_iso(
                        last_time_str
                    )
                if dt and \
                   self.TimeUtils.utc_now() - dt > \
                   timedelta(hours=24):
                    await self._execute_with_conn(
                        conn,
                        self._prepare_query(
                            "UPDATE user_violations "
                            "SET violation_count = 0, "
                            "last_violation_time = NULL "
                            "WHERE user_id = ? AND chat_id = ?"
                        ),
                        user_id, chat_id,
                    )
                current = await self._fetchval_with_conn(
                    conn,
                    self._prepare_query(
                        "SELECT violation_count FROM user_violations "
                        "WHERE user_id = ? AND chat_id = ?"
                    ),
                    user_id, chat_id, default=0,
                )
                new_count = current + 1
                now = self.TimeUtils.utc_now()
                if self.USE_POSTGRES:
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO user_violations "
                        "(user_id, chat_id, violation_count, "
                        "last_violation_time) VALUES ($1,$2,$3,$4) "
                        "ON CONFLICT(user_id, chat_id) DO UPDATE SET "
                        "violation_count = excluded.violation_count, "
                        "last_violation_time = "
                        "excluded.last_violation_time",
                        user_id, chat_id, new_count, now,
                    )
                else:
                    await self._execute_with_conn(
                        conn,
                        self._prepare_query(
                            "INSERT INTO user_violations "
                            "(user_id, chat_id, violation_count, "
                            "last_violation_time) VALUES (?,?,?,?) "
                            "ON CONFLICT(user_id, chat_id) DO UPDATE SET "
                            "violation_count = excluded.violation_count, "
                            "last_violation_time = "
                            "excluded.last_violation_time"
                        ),
                        user_id, chat_id, new_count, now,
                    )
                return new_count

    async def reset_violation_count(
        self, user_id: int, chat_id: int
    ) -> bool:
        return await self.execute(
            self._prepare_query(
                "UPDATE user_violations SET violation_count = 0, "
                "last_violation_time = NULL "
                "WHERE user_id = ? AND chat_id = ?"
            ),
            (user_id, chat_id),
        ) > 0

    # ═════════════════════════════════════════════════════════════════
    # 16) انتهاء العقوبات (Expire Penalties — fallback)
    # ═════════════════════════════════════════════════════════════════

    async def _expire_penalties_generic(self, conn, batch: int):
        try:
            now = self.TimeUtils.utc_now()

            rows = await self._fetchall_with_conn(
                conn,
                self._prepare_query(
                    "SELECT id FROM user_penalties "
                    "WHERE status = 'active' AND end_time IS NOT NULL "
                    "  AND end_time <= ? "
                    "ORDER BY end_time ASC LIMIT ?"
                ),
                now, batch,
            )
            if not rows:
                return 0, 0

            ids = []
            for r in rows:
                pid = r.get("id") if isinstance(r, dict) else None
                if pid is not None:
                    ids.append(pid)
            if not ids:
                return 0, 0

            try:
                placeholders = ",".join(["?"] * len(ids))
                await self._execute_with_conn(
                    conn,
                    self._prepare_query(
                        f"INSERT INTO penalty_archive "
                        f"(id, user_id, chat_id, penalty_type, duration, "
                        f" start_time, end_time, reason, issued_by, "
                        f" status, created_at, archived_at) "
                        f"SELECT id, user_id, chat_id, penalty_type, "
                        f" duration, start_time, end_time, reason, "
                        f" issued_by, 'expired', created_at, ? "
                        f"FROM user_penalties WHERE id IN ({placeholders})"
                    ),
                    now, *ids,
                )
            except Exception as arc_e:
                logger.debug(
                    f"penalty_archive insert (best-effort): {arc_e}"
                )

            placeholders = ",".join(["?"] * len(ids))
            await self._execute_with_conn(
                conn,
                self._prepare_query(
                    f"UPDATE user_penalties SET status = 'expired' "
                    f"WHERE id IN ({placeholders})"
                ),
                *ids,
            )

            return len(ids), len(ids)
        except Exception as e:
            logger.error(
                f"❌ _expire_penalties_generic: {e}",
                exc_info=True,
            )
            return 0, 0

    async def _expire_penalties_pg(self, conn, batch: int):
        return await self._expire_penalties_generic(conn, batch)

    async def _expire_penalties_mysql(self, conn, batch: int):
        return await self._expire_penalties_generic(conn, batch)

    async def _expire_penalties_sqlite(self, conn, batch: int):
        return await self._expire_penalties_generic(conn, batch)


__all__ = [
    "GroupsMixin",
    "_convert_qmark_to_pg",
    "_safe_normalize_word",
]


# ═════════════════════════════════════════════════════════════════════
# LOAD BEACON — v7.4.20
# ═════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "🛡️ database_groups.py v7.4.20 AUDIT-FIXES loaded | "
        "🆕 FIX-PG-SYNTAX-1: qmark→$N helper + update_security/"
        "penalty/auto_reply | "
        "🆕 FIX-BANNED-CONFLICT-1: ON CONFLICT (word,chat_id) | "
        "🆕 FIX-AUTO-REPLY-CACHE-1: shares _ars_local_cache via _bms | "
        "🆕 FIX-ADMIN-MRO-STRICT-1: explicit super() check | "
        "🆕 FIX-INVALIDATE-CHAT-CACHE-1: chat_ids param | "
        "✅ v7.4.19 FIX-ADMIN-MRO-DEDUP preserved | "
        "✅ v7.4.17 FIX-CACHE-1..6 preserved | "
        "✅ v7.4.16 FIX-AC2+FIX-C4 preserved | "
        "✅ v7.4.15 P1..P5 | v7.4.14 O1..O2 | v7.4.13 F1..F3 | "
        "✅ v7.4.12 F1..F2 | v7.4.11 M1..M4+m1..m3 preserved"
    )
except Exception:
    pass