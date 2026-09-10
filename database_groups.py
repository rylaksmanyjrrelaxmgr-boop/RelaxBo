#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_groups.py - دوال المجموعات (v7.3.2)
================================================================================
GroupsMixin:
  - تسجيل المجموعات وإدارتها
  - المشرفون المخفيون والمجهولون
  - إعدادات الأمان
  - التحذيرات
  - سجلات المشرفين
  - الردود التلقائية
  - الكلمات المحظورة
  - إعدادات العقوبات والمخالفات
================================================================================
"""

import asyncio
import logging
import time
import json
from datetime import timedelta
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


class GroupsMixin:
    """
    Mixin يحتوي كل دوال المجموعات.
    يفترض أن الـ Database يوفّر:
      - self.fetchone / self.fetchall / self.fetchval / self.execute
      - self.transaction / self.connection
      - self._fetchone_with_conn / self._fetchall_with_conn /
        self._fetchval_with_conn / self._execute_with_conn /
        self._executemany_with_conn
      - self._get_group_lock
      - self.TimeUtils
      - self.internal_cache
      - self.CACHE_AVAILABLE / self.banned_words_cache /
        self.settings_cache / self.groups_cache / self.auth_cache
      - self.CONFIG / self.PATHS
      - self.COLUMN_ALIASES
      - self.VALID_VIOLATION_TYPES / self.VALID_PENALTY_TYPES /
        self.VALID_REPLY_TYPES / self.MAX_PENALTY_DURATION
      - self._group_security_columns_cache
      - self._banned_words_local_cache / self._banned_words_cache_ttl /
        self._global_banned_words_cache / self._global_banned_words_loaded /
        self._global_words_lock
      - self.USE_POSTGRES / self.USE_MYSQL / self.DB_TYPE
    """

    # =====================================================================
    # 1) كاش الكلمات المحظورة (داخلي)
    # =====================================================================

    async def _get_banned_words_from_local_cache(self, chat_id: int) -> Optional[List[str]]:
        entry = self._banned_words_local_cache.get(chat_id)
        if entry and time.time() - entry["time"] < self._banned_words_cache_ttl:
            return entry["words"]
        return None

    async def _set_banned_words_local_cache(self, chat_id: int, words: List[str]):
        self._banned_words_local_cache[chat_id] = {"words": words, "time": time.time()}

    async def _invalidate_banned_words_local_cache(self, chat_id: int = None):
        if chat_id is not None:
            self._banned_words_local_cache.pop(chat_id, None)
            if chat_id == -1:
                self._global_banned_words_cache = []
                self._global_banned_words_loaded = False
        else:
            self._banned_words_local_cache.clear()
            self._global_banned_words_cache = []
            self._global_banned_words_loaded = False

    # =====================================================================
    # 2) تسجيل المجموعات وإدارتها
    # =====================================================================

    async def register_group(self, chat_id: int, chat_name: str, user_id: int,
                              username: str = None) -> bool:
        try:
            async with self.connection() as conn:
                if self.USE_POSTGRES:
                    await self._execute_with_conn(
                        conn,
                        """INSERT INTO bot_groups (chat_id, chat_name, username, added_by, added_at, updated_at)
                           VALUES ($1, $2, $3, $4, $5, $5)
                           ON CONFLICT (chat_id) DO UPDATE SET
                               chat_name = EXCLUDED.chat_name,
                               username = EXCLUDED.username,
                               updated_at = EXCLUDED.updated_at""",
                        chat_id, chat_name, username, user_id, self.TimeUtils.utc_now(),
                    )
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO user_groups_link (user_id, chat_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                        user_id, chat_id,
                    )
                elif self.USE_MYSQL:
                    await self._execute_with_conn(
                        conn,
                        """INSERT INTO bot_groups (chat_id, chat_name, username, added_by, added_at, updated_at)
                           VALUES (%s, %s, %s, %s, %s, %s)
                           ON DUPLICATE KEY UPDATE
                               chat_name = VALUES(chat_name),
                               username = VALUES(username),
                               updated_at = VALUES(updated_at)""",
                        chat_id, chat_name, username, user_id,
                        self.TimeUtils.sql_iso(), self.TimeUtils.sql_iso(),
                    )
                    await self._execute_with_conn(
                        conn,
                        "INSERT IGNORE INTO user_groups_link (user_id, chat_id) VALUES (%s, %s)",
                        user_id, chat_id,
                    )
                else:
                    await self._execute_with_conn(
                        conn,
                        """INSERT INTO bot_groups (chat_id, chat_name, username, added_by, added_at, updated_at)
                           VALUES (?,?,?,?,?,?)
                           ON CONFLICT(chat_id) DO UPDATE SET
                               chat_name = excluded.chat_name,
                               username = excluded.username,
                               updated_at = excluded.updated_at""",
                        chat_id, chat_name, username, user_id,
                        self.TimeUtils.sql_iso(), self.TimeUtils.sql_iso(),
                    )
                    await self._execute_with_conn(
                        conn,
                        "INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?,?)",
                        user_id, chat_id,
                    )
                logger.info(f"✅ تم تسجيل المجموعة {chat_id} بواسطة المستخدم {user_id}")
                if self.CACHE_AVAILABLE:
                    await self.groups_cache.invalidate(user_id)
                await self.internal_cache.invalidate(f"groups_{user_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error in register_group: {e}", exc_info=True)
            return False

    async def get_user_groups(self, user_id: int) -> List[Dict]:
        if self.CACHE_AVAILABLE:
            cached = await self.groups_cache.get(user_id)
            if cached is not None:
                return cached
        cached = await self.internal_cache.get(f"groups_{user_id}")
        if cached is not None:
            return cached

        if self.USE_POSTGRES:
            query = """
                SELECT DISTINCT chat_id, chat_name, username, banned
                FROM (
                    SELECT chat_id, chat_name, username, banned FROM bot_groups WHERE added_by = $1
                    UNION
                    SELECT bg.chat_id, bg.chat_name, bg.username, bg.banned
                    FROM bot_groups bg JOIN user_groups_link l ON bg.chat_id = l.chat_id
                    WHERE l.user_id = $1
                    UNION
                    SELECT bg.chat_id, bg.chat_name, bg.username, bg.banned
                    FROM bot_groups bg JOIN hidden_owner_groups ho ON bg.chat_id = ho.chat_id
                    WHERE ho.owner_id = $1
                    UNION
                    SELECT bg.chat_id, bg.chat_name, bg.username, bg.banned
                    FROM bot_groups bg JOIN hidden_admins ha ON bg.chat_id = ha.chat_id
                    WHERE ha.admin_id = $1
                    UNION
                    SELECT bg.chat_id, bg.chat_name, bg.username, bg.banned
                    FROM bot_groups bg JOIN group_admins ga ON bg.chat_id = ga.chat_id
                    WHERE ga.user_id = $1
                    UNION
                    SELECT bg.chat_id, bg.chat_name, bg.username, bg.banned
                    FROM bot_groups bg JOIN anonymous_admins aa ON bg.chat_id = aa.chat_id
                    WHERE aa.user_id = $1 OR aa.anonymous_id = $1
                ) AS groups ORDER BY chat_id
            """
            groups = await self.fetchall(query, (user_id,))
        else:
            query = """
                SELECT DISTINCT bg.chat_id, bg.chat_name, bg.username, bg.banned
                FROM bot_groups bg
                WHERE bg.added_by = ?
                   OR EXISTS (SELECT 1 FROM user_groups_link l WHERE l.chat_id = bg.chat_id AND l.user_id = ?)
                   OR EXISTS (SELECT 1 FROM hidden_owner_groups ho WHERE ho.chat_id = bg.chat_id AND ho.owner_id = ?)
                   OR EXISTS (SELECT 1 FROM hidden_admins ha WHERE ha.chat_id = bg.chat_id AND ha.admin_id = ?)
                   OR EXISTS (SELECT 1 FROM group_admins ga WHERE ga.chat_id = bg.chat_id AND ga.user_id = ?)
                   OR EXISTS (SELECT 1 FROM anonymous_admins aa WHERE aa.chat_id = bg.chat_id AND aa.user_id = ?)
                   OR EXISTS (SELECT 1 FROM anonymous_admins aa2 WHERE aa2.chat_id = bg.chat_id AND aa2.anonymous_id = ?)
                LIMIT 100
            """
            groups = await self.fetchall(
                query,
                (user_id, user_id, user_id, user_id, user_id, user_id, user_id),
            )
        await self.internal_cache.set(f"groups_{user_id}", groups)
        if self.CACHE_AVAILABLE:
            await self.groups_cache.set(user_id, groups)
        return groups

    async def delete_group(self, chat_id: int) -> bool:
        try:
            async with self.transaction() as conn:
                tables = [
                    "user_groups_link", "group_admins", "hidden_owner_groups",
                    "hidden_admins", "anonymous_admins", "group_security",
                    "chat_locks", "banned_words", "auto_replies", "auto_reply_settings",
                    "user_warnings", "user_violations", "group_rules", "user_messages",
                    "admin_logs", "violation_penalties", "user_penalties", "scheduled_posts",
                ]
                for table in tables:
                    await self._execute_with_conn(conn, f"DELETE FROM {table} WHERE chat_id = ?", chat_id)
                await self._execute_with_conn(conn, "DELETE FROM bot_groups WHERE chat_id = ?", chat_id)
            if self.CACHE_AVAILABLE:
                await self.groups_cache.invalidate()
                await self.settings_cache.invalidate_security(chat_id)
                await self.settings_cache.invalidate_auto_reply(chat_id)
            return True
        except Exception as e:
            logger.error(f"❌ Error in delete_group: {e}", exc_info=True)
            return False

    # =====================================================================
    # 3) مشرفو المجموعات (Group Admins)
    # =====================================================================

    async def sync_group_admins(self, chat_id: int, admin_ids: List[int]) -> int:
        try:
            async with await self._get_group_lock(chat_id):
                async with self.transaction() as conn:
                    existing = await self._fetchall_with_conn(
                        conn, "SELECT user_id FROM group_admins WHERE chat_id = ?", chat_id
                    )
                    existing_ids = {row["user_id"] for row in existing}
                    new_ids = set(admin_ids)
                    to_remove = existing_ids - new_ids
                    for uid in to_remove:
                        await self._execute_with_conn(
                            conn, "DELETE FROM group_admins WHERE chat_id = ? AND user_id = ?",
                            chat_id, uid,
                        )
                    to_add = new_ids - existing_ids
                    for uid in to_add:
                        if self.USE_POSTGRES:
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO group_admins (chat_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                                chat_id, uid,
                            )
                        elif self.USE_MYSQL:
                            await self._execute_with_conn(
                                conn,
                                "INSERT IGNORE INTO group_admins (chat_id, user_id) VALUES (%s, %s)",
                                chat_id, uid,
                            )
                        else:
                            await self._execute_with_conn(
                                conn,
                                "INSERT OR IGNORE INTO group_admins (chat_id, user_id) VALUES (?,?)",
                                chat_id, uid,
                            )
                if self.CACHE_AVAILABLE:
                    await self.auth_cache.invalidate(chat_id)
                return len(admin_ids)
        except Exception as e:
            logger.error(f"❌ Error in sync_group_admins: {e}", exc_info=True)
            return 0

    # =====================================================================
    # 4) المشرفون المخفيون (Hidden Admins)
    # =====================================================================

    async def add_hidden_admin(self, chat_id: int, admin_id: int, added_by: int) -> bool:
        return await self.execute(
            "INSERT OR IGNORE INTO hidden_admins (chat_id, admin_id, added_by, added_at) VALUES (?,?,?,?)",
            (chat_id, admin_id, added_by, self.TimeUtils.utc_now()),
        ) > 0

    async def remove_hidden_admin(self, chat_id: int, admin_id: int) -> bool:
        try:
            async with self.transaction() as conn:
                await self._execute_with_conn(
                    conn, "DELETE FROM hidden_owner_groups WHERE chat_id = ? AND owner_id = ?",
                    chat_id, admin_id,
                )
                await self._execute_with_conn(
                    conn, "DELETE FROM hidden_admins WHERE chat_id = ? AND admin_id = ?",
                    chat_id, admin_id,
                )
            return True
        except Exception as e:
            logger.error(f"❌ Error in remove_hidden_admin: {e}", exc_info=True)
            return False

    async def get_hidden_admins(self, chat_id: int) -> List[Dict]:
        return await self.fetchall(
            "SELECT admin_id, added_by, added_at FROM hidden_admins WHERE chat_id = ? ORDER BY added_at DESC",
            (chat_id,),
        )

    # =====================================================================
    # 5) المشرفون المجهولون (Anonymous Admins)
    # =====================================================================

    async def add_anonymous_admin(self, chat_id: int, anonymous_id: int,
                                   added_by: int = None, user_id: int = None) -> bool:
        return await self.execute(
            "INSERT OR IGNORE INTO anonymous_admins (chat_id, anonymous_id, added_by, user_id, added_at) VALUES (?,?,?,?,?)",
            (chat_id, anonymous_id, added_by, user_id, self.TimeUtils.utc_now()),
        ) > 0

    async def remove_anonymous_admin(self, chat_id: int, anonymous_id: int) -> bool:
        try:
            async with self.connection() as conn:
                deleted = await self._execute_with_conn(
                    conn, "DELETE FROM anonymous_admins WHERE chat_id = ? AND anonymous_id = ?",
                    chat_id, anonymous_id,
                )
                return deleted > 0
        except Exception as e:
            logger.error(f"❌ Error in remove_anonymous_admin: {e}", exc_info=True)
            return False

    async def get_anonymous_admins(self, chat_id: int) -> List[Dict]:
        return await self.fetchall(
            "SELECT anonymous_id, user_id, added_by, added_at FROM anonymous_admins WHERE chat_id = ? ORDER BY added_at DESC",
            (chat_id,),
        )

    async def is_anonymous_admin(self, chat_id: int, user_id: int) -> bool:
        result = await self.fetchval(
            "SELECT 1 FROM anonymous_admins WHERE chat_id = ? AND (user_id = ? OR anonymous_id = ?) LIMIT 1",
            (chat_id, user_id, user_id),
        )
        return result is not None

    async def sync_anonymous_admins(
        self, chat_id: int, anonymous_ids: List[int],
        added_by: int = None, user_id_map: Optional[Dict[int, int]] = None,
    ) -> int:
        try:
            async with await self._get_group_lock(chat_id):
                async with self.transaction() as conn:
                    existing = await self._fetchall_with_conn(
                        conn, "SELECT anonymous_id FROM anonymous_admins WHERE chat_id = ?", chat_id
                    )
                    existing_ids = {row["anonymous_id"] for row in existing}
                    new_ids = set(anonymous_ids)
                    to_remove = existing_ids - new_ids
                    for anon_id in to_remove:
                        await self._execute_with_conn(
                            conn, "DELETE FROM anonymous_admins WHERE chat_id = ? AND anonymous_id = ?",
                            chat_id, anon_id,
                        )
                    for anon_id in new_ids:
                        real_user_id = user_id_map.get(anon_id) if user_id_map else None
                        if self.USE_POSTGRES:
                            await self._execute_with_conn(
                                conn,
                                """INSERT INTO anonymous_admins (chat_id, anonymous_id, added_by, user_id, added_at)
                                   VALUES ($1, $2, $3, $4, $5)
                                   ON CONFLICT (chat_id, anonymous_id) DO UPDATE SET
                                       user_id = EXCLUDED.user_id,
                                       added_by = EXCLUDED.added_by""",
                                chat_id, anon_id, added_by, real_user_id, self.TimeUtils.utc_now(),
                            )
                        elif self.USE_MYSQL:
                            await self._execute_with_conn(
                                conn,
                                """INSERT INTO anonymous_admins (chat_id, anonymous_id, added_by, user_id, added_at)
                                   VALUES (%s, %s, %s, %s, %s)
                                   ON DUPLICATE KEY UPDATE user_id = VALUES(user_id), added_by = VALUES(added_by)""",
                                chat_id, anon_id, added_by, real_user_id, self.TimeUtils.sql_iso(),
                            )
                        else:
                            await self._execute_with_conn(
                                conn,
                                """INSERT INTO anonymous_admins (chat_id, anonymous_id, added_by, user_id, added_at)
                                   VALUES (?,?,?,?,?)
                                   ON CONFLICT(chat_id, anonymous_id) DO UPDATE SET
                                       user_id = excluded.user_id,
                                       added_by = excluded.added_by""",
                                chat_id, anon_id, added_by, real_user_id, self.TimeUtils.sql_iso(),
                            )
                return len(anonymous_ids)
        except Exception as e:
            logger.error(f"❌ Error in sync_anonymous_admins: {e}", exc_info=True)
            return 0

    # =====================================================================
    # 6) إعدادات الأمان (Security)
    # =====================================================================

    async def get_security_settings(self, chat_id: int) -> Dict:
        if self.CACHE_AVAILABLE:
            cached = await self.settings_cache.get_security(chat_id)
            if cached is not None:
                return cached
        settings = await self.fetchone("SELECT * FROM group_security WHERE chat_id = ?", (chat_id,))
        if not settings:
            await self.execute("INSERT OR IGNORE INTO group_security (chat_id) VALUES (?)", (chat_id,))
            settings = await self.fetchone("SELECT * FROM group_security WHERE chat_id = ?", (chat_id,))
        if settings and self.CACHE_AVAILABLE:
            await self.settings_cache.set_security(chat_id, settings)
        return settings if settings else {}

    async def _get_group_security_columns(self) -> set:
        if self._group_security_columns_cache is not None:
            return self._group_security_columns_cache

        try:
            async with self.connection() as conn:
                if self.USE_POSTGRES:
                    rows = await conn.fetch(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'group_security' "
                        "ORDER BY ordinal_position"
                    )
                    cols = {row["column_name"] for row in rows}
                elif self.USE_MYSQL:
                    cursor = await conn.cursor()
                    await cursor.execute("SHOW COLUMNS FROM `group_security`")
                    rows = await cursor.fetchall()
                    await cursor.close()
                    cols = {row[0] for row in rows}
                else:
                    cursor = await conn.execute("PRAGMA table_info(group_security)")
                    rows = await cursor.fetchall()
                    cols = {row[1] for row in rows}

            self._group_security_columns_cache = cols
            logger.info(f"📋 Loaded group_security columns: {len(cols)} columns")
            return cols
        except Exception as e:
            logger.error(f"❌ Failed to load group_security columns: {e}", exc_info=True)
            return set()

    async def get_group_security_columns(self) -> set:
        return await self._get_group_security_columns()

    def invalidate_group_security_columns_cache(self):
        self._group_security_columns_cache = None
        logger.info("🔄 group_security columns cache invalidated")

    async def update_security_settings(self, chat_id: int, **kwargs) -> bool:
        if not kwargs:
            return False

        original_keys = set(kwargs.keys())
        logger.info(f"🔧 update_security_settings called for chat_id={chat_id}")
        logger.info(f"   📥 Original keys ({len(original_keys)}): {sorted(original_keys)}")

        # 1) معالجة المرادفات
        aliased_keys = []
        for alias, real_col in self.COLUMN_ALIASES.items():
            if alias in kwargs:
                if real_col not in kwargs:
                    kwargs[real_col] = kwargs.pop(alias)
                    aliased_keys.append((alias, real_col))
                else:
                    kwargs.pop(alias, None)
                    aliased_keys.append((alias, f"{real_col} (already present)"))

        if aliased_keys:
            logger.info(f"   🔄 Aliases resolved: {aliased_keys}")

        # 2) ضمان وجود صف
        await self.execute(
            "INSERT OR IGNORE INTO group_security (chat_id) VALUES (?)",
            (chat_id,)
        )

        # 3) جلب الأعمدة الفعلية
        actual_columns = await self._get_group_security_columns()
        if not actual_columns:
            logger.error(f"   ❌ لم يتمكن من جلب أعمدة group_security")
            return False

        logger.info(f"   📋 Actual columns in group_security ({len(actual_columns)}): {sorted(actual_columns)}")

        # 4) فلترة kwargs
        valid_kwargs = {}
        skipped_keys = []
        for key, value in kwargs.items():
            if key in actual_columns:
                valid_kwargs[key] = value
            else:
                skipped_keys.append(key)

        if skipped_keys:
            logger.warning(
                f"   ⚠️ Skipped {len(skipped_keys)} non-existent columns: {skipped_keys}"
            )

        if not valid_kwargs:
            logger.error(f"   ❌ لا يوجد أي عمود صالح للتحديث!")
            return False

        logger.info(f"   ✅ Will update {len(valid_kwargs)} columns: {sorted(valid_kwargs.keys())}")

        # 5) تنفيذ UPDATE
        try:
            updates = [f"{key} = ?" for key in valid_kwargs]
            values = list(valid_kwargs.values()) + [chat_id]
            query = f"UPDATE group_security SET {', '.join(updates)} WHERE chat_id = ?"

            result = await self.execute(query, tuple(values))
            success = result >= 0

            if success:
                try:
                    if self.CACHE_AVAILABLE:
                        await self.settings_cache.invalidate_security(chat_id)
                    await self.internal_cache.invalidate(f"security_{chat_id}")
                    await self.internal_cache.invalidate(f"group_security_{chat_id}")
                except Exception as cache_err:
                    logger.warning(f"   ⚠️ Cache invalidation error: {cache_err}")

                logger.info(f"   ✅ Successfully updated group_security for chat_id={chat_id}")
                return True
            else:
                logger.error(f"   ❌ UPDATE returned negative: {result}")
                return False

        except Exception as e:
            logger.error(
                f"   ❌ UPDATE failed for chat_id={chat_id}: {e}",
                exc_info=True
            )
            return False

    # =====================================================================
    # 7) التحذيرات (Warnings)
    # =====================================================================

    async def get_user_warnings(self, user_id: int, chat_id: int) -> int:
        return await self.fetchval(
            "SELECT warnings FROM user_warnings WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id), default=0,
        )

    async def add_user_warning(self, user_id: int, chat_id: int) -> int:
        await self.execute(
            """INSERT INTO user_warnings (user_id, chat_id, warnings)
               VALUES (?,?,1)
               ON CONFLICT(user_id, chat_id) DO UPDATE SET warnings = warnings + 1""",
            (user_id, chat_id),
        )
        return await self.get_user_warnings(user_id, chat_id)

    async def reset_user_warnings(self, user_id: int, chat_id: int) -> bool:
        return await self.execute(
            "UPDATE user_warnings SET warnings = 0 WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        ) > 0

    # =====================================================================
    # 8) سجلات المشرفين (Admin Logs)
    # =====================================================================

    async def add_admin_log(self, chat_id: int, admin_id: int, action: str,
                             target_id: int = None, reason: str = "") -> bool:
        return await self.execute(
            "INSERT INTO admin_logs (chat_id, admin_id, action, target_id, reason, created_at) VALUES (?,?,?,?,?,?)",
            (chat_id, admin_id, action, target_id, reason, self.TimeUtils.utc_now()),
        ) > 0

    async def get_admin_logs(self, chat_id: int, limit: int = 20) -> List[Dict]:
        return await self.fetchall(
            "SELECT admin_id, action, target_id, reason, created_at FROM admin_logs WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        )

    # =====================================================================
    # 9) الردود التلقائية (Auto Replies)
    # =====================================================================

    async def get_auto_reply_settings(self, chat_id: int) -> Dict:
        if self.CACHE_AVAILABLE:
            cached = await self.settings_cache.get_auto_reply_settings(chat_id)
            if cached is not None:
                return cached
        settings = await self.fetchone("SELECT * FROM auto_reply_settings WHERE chat_id = ?", (chat_id,))
        if not settings:
            await self.execute("INSERT OR IGNORE INTO auto_reply_settings (chat_id) VALUES (?)", (chat_id,))
            settings = await self.fetchone("SELECT * FROM auto_reply_settings WHERE chat_id = ?", (chat_id,))
        if settings and self.CACHE_AVAILABLE:
            await self.settings_cache.set_auto_reply_settings(chat_id, settings)
        return settings if settings else {"enabled": 0, "only_admins": 0, "ignore_bots": 1}

    async def update_auto_reply_settings(self, chat_id: int, **kwargs) -> bool:
        if not kwargs:
            return False
        await self.execute("INSERT OR IGNORE INTO auto_reply_settings (chat_id) VALUES (?)", (chat_id,))
        allowed_columns = {"enabled", "only_admins", "ignore_bots", "updated_at"}
        for key in kwargs:
            if key not in allowed_columns:
                logger.error(f"❌ Invalid column: {key}")
                return False
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = self.TimeUtils.utc_now()
        updates = [f"{key} = ?" for key in kwargs]
        values = list(kwargs.values()) + [chat_id]
        query = f"UPDATE auto_reply_settings SET {', '.join(updates)} WHERE chat_id = ?"
        result = await self.execute(query, tuple(values)) > 0
        if result and self.CACHE_AVAILABLE:
            await self.settings_cache.invalidate_auto_reply(chat_id)
        return result

    async def add_auto_reply(self, chat_id: int, keyword: str, reply: str,
                             reply_type: str = "text", media_id: str = None,
                             buttons: str = None) -> bool:
        keyword = keyword.lower().strip()
        if reply_type not in self.VALID_REPLY_TYPES:
            logger.error(f"❌ Invalid reply_type: {reply_type}")
            return False
        try:
            async with self.connection() as conn:
                if self.USE_POSTGRES:
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO auto_replies (chat_id, keyword, reply, reply_type, reply_media_id, reply_buttons, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                        chat_id, keyword, reply, reply_type, media_id, buttons, self.TimeUtils.utc_now(),
                    )
                elif self.USE_MYSQL:
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO auto_replies (chat_id, keyword, reply, reply_type, reply_media_id, reply_buttons, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        chat_id, keyword, reply, reply_type, media_id, buttons, self.TimeUtils.sql_iso(),
                    )
                else:
                    await self._execute_with_conn(
                        conn,
                        "INSERT INTO auto_replies (chat_id, keyword, reply, reply_type, reply_media_id, reply_buttons, created_at) VALUES (?,?,?,?,?,?,?)",
                        chat_id, keyword, reply, reply_type, media_id, buttons, self.TimeUtils.sql_iso(),
                    )
            return True
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                return await self.execute(
                    "UPDATE auto_replies SET reply = ?, reply_type = ?, reply_media_id = ?, reply_buttons = ?, created_at = ? WHERE chat_id = ? AND keyword = ?",
                    (reply, reply_type, media_id, buttons, self.TimeUtils.sql_iso(), chat_id, keyword),
                ) > 0
            logger.error(f"❌ Error in add_auto_reply: {e}", exc_info=True)
            return False

    async def remove_auto_reply(self, chat_id: int, keyword: str) -> bool:
        keyword = keyword.lower().strip()
        try:
            async with self.connection() as conn:
                deleted = await self._execute_with_conn(
                    conn, "DELETE FROM auto_replies WHERE chat_id = ? AND keyword = ?",
                    chat_id, keyword
                )
                return deleted > 0
        except Exception as e:
            logger.error(f"❌ Error in remove_auto_reply: {e}", exc_info=True)
            return False

    async def _increment_usage_count(self, chat_id: int, keyword: str):
        try:
            await self.execute(
                "UPDATE auto_replies SET usage_count = usage_count + 1 WHERE chat_id = ? AND keyword = ?",
                (chat_id, keyword),
            )
        except Exception:
            pass

    async def get_auto_reply(self, keyword: str, chat_id: int) -> Optional[Dict]:
        keyword = keyword.lower().strip()
        if not keyword:
            return None
        row = await self.fetchone(
            """SELECT reply, reply_type, reply_media_id, reply_buttons
               FROM auto_replies
               WHERE keyword = ? AND is_active = 1 AND (chat_id = ? OR chat_id = -1)
               ORDER BY CASE WHEN chat_id = ? THEN 0 ELSE 1 END
               LIMIT 1""",
            (keyword, chat_id, chat_id),
        )
        if row:
            def _log_task_exc(t: asyncio.Task):
                if not t.cancelled() and t.exception():
                    logger.debug(f"increment_usage_count: {t.exception()}")
            task = asyncio.create_task(self._increment_usage_count(chat_id, keyword))
            task.add_done_callback(_log_task_exc)
            return row
        return None

    async def get_auto_reply_stats(self, chat_id: int, limit: int = 20) -> List[Dict]:
        return await self.fetchall(
            """SELECT keyword, usage_count,
                      CASE WHEN chat_id = -1 THEN 'global' ELSE 'group' END as source
               FROM auto_replies
               WHERE chat_id = ? OR chat_id = -1
               ORDER BY usage_count DESC LIMIT ?""",
            (chat_id, limit),
        )

    async def reset_auto_replies(self, chat_id: int) -> bool:
        return await self.execute("DELETE FROM auto_replies WHERE chat_id = ?", (chat_id,)) > 0

    async def export_auto_replies_to_file(self) -> Optional[str]:
        try:
            rows = await self.fetchall("SELECT * FROM auto_replies")
            if not rows:
                return None
            timestamp = self.TimeUtils.utc_now().strftime("%Y%m%d_%H%M%S")
            file_path = self.PATHS.BACKUPS / f"auto_replies_export_{timestamp}.json"
            file_path.parent.mkdir(parents=True, exist_ok=True)

            def _write():
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump([dict(r) for r in rows], f, ensure_ascii=False, indent=2)

            await asyncio.to_thread(_write)
            return str(file_path)
        except Exception as e:
            logger.error(f"❌ Error in export_auto_replies_to_file: {e}", exc_info=True)
            return None

    async def import_auto_replies_from_file(self, file_path: str) -> int:
        try:
            def _read():
                with open(file_path, "r", encoding="utf-8") as f:
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
                            """INSERT OR IGNORE INTO auto_replies
                               (chat_id, keyword, reply, reply_type, reply_media_id, reply_buttons, created_at, is_active, usage_count)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            item.get("chat_id", -1),
                            item.get("keyword", "").lower(),
                            item.get("reply", ""),
                            item.get("reply_type", "text"),
                            item.get("reply_media_id"),
                            item.get("reply_buttons"),
                            item.get("created_at", self.TimeUtils.utc_now()),
                            item.get("is_active", 1),
                            item.get("usage_count", 0),
                        )
                        imported += 1
                    except Exception as e:
                        logger.warning(f"⚠️ فشل استيراد رد: {e}")
            return imported
        except Exception as e:
            logger.error(f"❌ Error in import_auto_replies_from_file: {e}", exc_info=True)
            return 0

    # =====================================================================
    # 10) الكلمات المحظورة (Banned Words)
    # =====================================================================

    async def _load_global_banned_words(self) -> List[str]:
        if self._global_banned_words_loaded:
            return self._global_banned_words_cache
        async with self._global_words_lock:
            if self._global_banned_words_loaded:
                return self._global_banned_words_cache
            rows = await self.fetchall(
                "SELECT DISTINCT word FROM banned_words WHERE chat_id = -1"
            )
            self._global_banned_words_cache = [row["word"] for row in rows]
            self._global_banned_words_loaded = True
            return self._global_banned_words_cache

    async def get_banned_words(self, chat_id: int) -> List[str]:
        if self.CACHE_AVAILABLE:
            cached = await self.banned_words_cache.get(chat_id)
            if cached is not None:
                return cached
        cached_local = await self._get_banned_words_from_local_cache(chat_id)
        if cached_local is not None:
            return cached_local

        global_words = await self._load_global_banned_words()
        specific = await self.fetchall(
            "SELECT word FROM banned_words WHERE chat_id = ?", (chat_id,)
        )
        specific_words = [row["word"] for row in specific]
        result = list(set(global_words + specific_words))

        await self._set_banned_words_local_cache(chat_id, result)
        if self.CACHE_AVAILABLE:
            await self.banned_words_cache.set(chat_id, result)
        return result

    async def add_banned_word(self, word: str, chat_id: int,
                               added_by: int) -> Tuple[bool, bool]:
        try:
            word = word.strip().lower()
            if not word:
                return False, False
            async with self.transaction() as conn:
                if chat_id == -1:
                    count = await self._fetchval_with_conn(
                        conn, "SELECT COUNT(*) FROM banned_words WHERE chat_id = -1", default=0
                    )
                    if count >= getattr(self.CONFIG, "MAX_GLOBAL_BANNED_WORDS", 500):
                        return False, False
                try:
                    if self.USE_POSTGRES:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO banned_words (word, chat_id, added_by, added_at) VALUES ($1, $2, $3, $4)",
                            word, chat_id, added_by, self.TimeUtils.utc_now(),
                        )
                    elif self.USE_MYSQL:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO banned_words (word, chat_id, added_by, added_at) VALUES (%s, %s, %s, %s)",
                            word, chat_id, added_by, self.TimeUtils.sql_iso(),
                        )
                    else:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO banned_words (word, chat_id, added_by, added_at) VALUES (?,?,?,?)",
                            word, chat_id, added_by, self.TimeUtils.sql_iso(),
                        )
                    await self._invalidate_banned_words_local_cache(chat_id)
                    if self.CACHE_AVAILABLE:
                        await self.banned_words_cache.invalidate(chat_id)
                    return True, False
                except Exception as e:
                    if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                        return False, True
                    raise
        except Exception as e:
            logger.error(f"❌ Error in add_banned_word: {e}", exc_info=True)
            return False, False

    async def remove_banned_word(self, word: str, chat_id: int) -> bool:
        word = word.strip().lower()
        try:
            async with self.connection() as conn:
                deleted = await self._execute_with_conn(
                    conn, "DELETE FROM banned_words WHERE word = ? AND chat_id = ?",
                    word, chat_id
                )
                if deleted > 0:
                    await self._invalidate_banned_words_local_cache(chat_id)
                    if self.CACHE_AVAILABLE:
                        await self.banned_words_cache.invalidate(chat_id)
                return deleted > 0
        except Exception as e:
            logger.error(f"❌ Error in remove_banned_word: {e}", exc_info=True)
            return False

    async def reload_banned_words(self) -> bool:
        try:
            import importlib
            import banned_words
            importlib.reload(banned_words)
            BANNED_WORDS = getattr(banned_words, "BANNED_WORDS", [])
            if not BANNED_WORDS:
                return True
            owner_id = getattr(self.CONFIG, "PRIMARY_OWNER_ID", None) or 1
            async with self.transaction() as conn:
                await self._execute_with_conn(conn, "DELETE FROM banned_words WHERE chat_id = -1")
                words_to_insert = []
                for word in BANNED_WORDS:
                    word = str(word).strip().lower()
                    if len(word) >= 2:
                        words_to_insert.append((word, -1, owner_id, self.TimeUtils.utc_now()))
                if words_to_insert:
                    await self._executemany_with_conn(
                        conn,
                        "INSERT OR IGNORE INTO banned_words (word, chat_id, added_by, added_at) VALUES (?,?,?,?)",
                        words_to_insert,
                    )
            await self._invalidate_banned_words_local_cache()
            if self.CACHE_AVAILABLE:
                await self.banned_words_cache.invalidate()
            logger.info(f"✅ تم إعادة تحميل {len(words_to_insert)} كلمة محظورة")
            return True
        except ImportError:
            logger.warning("⚠️ ملف banned_words.py غير موجود")
            return False
        except Exception as e:
            logger.error(f"❌ فشل إعادة تحميل الكلمات المحظورة: {e}")
            return False

    # =====================================================================
    # 11) إعدادات العقوبات (Penalty Settings)
    # =====================================================================

    async def get_penalty_settings(self, chat_id: int) -> Dict:
        await self.execute("INSERT OR IGNORE INTO group_security (chat_id) VALUES (?)", (chat_id,))
        return await self.fetchone(
            """SELECT mute_default_duration, ban_default_duration,
                      warn_default_duration, restrict_default_duration,
                      enable_timed_penalties, auto_remove_penalties
               FROM group_security WHERE chat_id = ?""",
            (chat_id,),
        ) or {}

    async def update_penalty_settings(self, chat_id: int, **kwargs) -> bool:
        if not kwargs:
            return False
        await self.execute("INSERT OR IGNORE INTO group_security (chat_id) VALUES (?)", (chat_id,))
        allowed_columns = {
            "mute_default_duration", "ban_default_duration", "warn_default_duration",
            "restrict_default_duration", "enable_timed_penalties", "auto_remove_penalties",
        }
        for key in kwargs:
            if key not in allowed_columns:
                logger.error(f"❌ Invalid column: {key}")
                return False
        updates = [f"{key} = ?" for key in kwargs]
        values = list(kwargs.values()) + [chat_id]
        query = f"UPDATE group_security SET {', '.join(updates)} WHERE chat_id = ?"
        result = await self.execute(query, tuple(values)) > 0
        if result and self.CACHE_AVAILABLE:
            await self.settings_cache.invalidate_security(chat_id)
        return result

    # =====================================================================
    # 12) المخالفات (Violations)
    # =====================================================================

    async def get_violation_penalty(self, chat_id: int, violation_type: str) -> Dict:
        result = await self.fetchone(
            "SELECT penalty_type, duration_seconds FROM violation_penalties WHERE chat_id = ? AND violation_type = ?",
            (chat_id, violation_type),
        )
        if result:
            return result
        settings = await self.get_security_settings(chat_id)
        return {
            "penalty_type": settings.get("auto_penalty", "mute"),
            "duration_seconds": settings.get("auto_mute_duration", 3600),
        }

    async def set_violation_penalty(self, chat_id: int, violation_type: str,
                                     penalty_type: str, duration_seconds: int) -> bool:
        if violation_type not in self.VALID_VIOLATION_TYPES:
            logger.error(f"❌ Invalid violation_type: {violation_type}")
            return False
        if penalty_type not in self.VALID_PENALTY_TYPES:
            logger.error(f"❌ Invalid penalty_type: {penalty_type}")
            return False
        if duration_seconds < 0:
            duration_seconds = 0
        if duration_seconds > self.MAX_PENALTY_DURATION:
            duration_seconds = self.MAX_PENALTY_DURATION
        return await self.execute(
            """INSERT OR REPLACE INTO violation_penalties
               (chat_id, violation_type, penalty_type, duration_seconds)
               VALUES (?,?,?,?)""",
            (chat_id, violation_type, penalty_type, duration_seconds),
        ) > 0

    async def get_all_violation_penalties(self, chat_id: int) -> Dict[str, Dict]:
        penalties = await self.fetchall(
            "SELECT violation_type, penalty_type, duration_seconds FROM violation_penalties WHERE chat_id = ?",
            (chat_id,),
        )
        result = {}
        for penalty in penalties:
            result[penalty["violation_type"]] = {
                "penalty_type": penalty["penalty_type"],
                "duration_seconds": penalty["duration_seconds"],
            }
        return result

    async def get_violation_count(self, user_id: int, chat_id: int) -> int:
        violation = await self.fetchone(
            "SELECT violation_count, last_violation_time FROM user_violations WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        )
        if not violation:
            return 0
        last_time = self.TimeUtils.safe_parse_iso(violation["last_violation_time"])
        if last_time:
            if self.TimeUtils.utc_now() - last_time > timedelta(hours=24):
                await self.execute(
                    "UPDATE user_violations SET violation_count = 0 WHERE user_id = ? AND chat_id = ?",
                    (user_id, chat_id),
                )
                return 0
        return violation["violation_count"]

    async def increment_violation_count(self, user_id: int, chat_id: int) -> int:
        async with self._lock:
            async with self.transaction() as conn:
                last_time_str = await self._fetchval_with_conn(
                    conn,
                    "SELECT last_violation_time FROM user_violations WHERE user_id = ? AND chat_id = ?",
                    user_id, chat_id,
                )
                dt = None
                if last_time_str:
                    dt = self.TimeUtils.safe_parse_iso(last_time_str)
                if dt and self.TimeUtils.utc_now() - dt > timedelta(hours=24):
                    await self._execute_with_conn(
                        conn,
                        "UPDATE user_violations SET violation_count = 0, last_violation_time = NULL WHERE user_id = ? AND chat_id = ?",
                        user_id, chat_id,
                    )
                current = await self._fetchval_with_conn(
                    conn,
                    "SELECT violation_count FROM user_violations WHERE user_id = ? AND chat_id = ?",
                    user_id, chat_id, default=0,
                )
                new_count = current + 1
                now = self.TimeUtils.utc_now()
                await self._execute_with_conn(
                    conn,
                    "INSERT INTO user_violations (user_id, chat_id, violation_count, last_violation_time) VALUES (?,?,?,?) ON CONFLICT(user_id, chat_id) DO UPDATE SET violation_count = excluded.violation_count, last_violation_time = excluded.last_violation_time",
                    user_id, chat_id, new_count, now,
                )
                return new_count

    async def reset_violation_count(self, user_id: int, chat_id: int) -> bool:
        return await self.execute(
            "UPDATE user_violations SET violation_count = 0, last_violation_time = NULL WHERE user_id = ? AND chat_id = ?",
            (user_id, chat_id),
        ) > 0