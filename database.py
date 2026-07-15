import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import aiosqlite
from config import (
    DB_PATH, DB_TIMEOUT, MAX_UNPUBLISHED_POSTS, MAX_CHANNELS_PER_CYCLE,
    utc_now, utc_now_iso, mecca_now, PRIMARY_OWNER_ID, DEFAULT_PUBLISH_INTERVAL_SECONDS
)
import logging

logger = logging.getLogger(__name__)

class DatabasePool:
    def __init__(self, max_connections: int = 10):
        self._pool = None
        self._max_connections = max_connections

    async def initialize(self):
        if self._pool is None:
            self._pool = await aiosqlite.connect(str(DB_PATH), timeout=DB_TIMEOUT)
            await self._pool.execute("PRAGMA journal_mode=WAL")
            await self._pool.execute("PRAGMA synchronous=NORMAL")
            await self._pool.execute("PRAGMA foreign_keys=ON")
            await self._pool.execute("PRAGMA cache_size=-64000")
            await self._pool.execute("PRAGMA max_page_count=1000000")
            await self._pool.execute("PRAGMA secure_delete=ON")
            self._pool.row_factory = aiosqlite.Row

    async def get_connection(self):
        if self._pool is None:
            await self.initialize()
        return self._pool

    async def execute(self, query: str, params: tuple = ()):
        conn = await self.get_connection()
        async with conn.execute(query, params) as cursor:
            return await cursor.fetchall()

    async def execute_many(self, queries: List[Tuple[str, tuple]]):
        conn = await self.get_connection()
        async with conn:
            for query, params in queries:
                await conn.execute(query, params)
            await conn.commit()

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None

db_pool = DatabasePool(max_connections=10)

async def execute_db(func):
    conn = await db_pool.get_connection()
    try:
        return await func(conn)
    except Exception as e:
        logger.error(f"Database error: {e}")
        raise

async def execute_transaction(queries: List[Tuple[str, tuple]]) -> Any:
    conn = await db_pool.get_connection()
    try:
        async with conn:
            results = []
            for query, params in queries:
                cur = await conn.execute(query, params)
                if query.strip().upper().startswith("SELECT"):
                    results.append(await cur.fetchall())
            await conn.commit()
            return results if len(results) > 1 else (results[0] if results else None)
    except Exception as e:
        await conn.rollback()
        raise

async def db_register_user(user_id: int) -> bool:
    async def _register(conn):
        cur = await conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if await cur.fetchone():
            return False
        await conn.execute("INSERT INTO users (user_id, auto_publish, banned, trial_used, auto_reply_enabled, auto_recycle) VALUES (?, 1, 0, 0, 1, 1)", (user_id,))
        await conn.commit()
        return True
    return await execute_db(_register)

async def db_get_all_users():
    async def _get(conn):
        cur = await conn.execute("SELECT user_id, banned FROM users ORDER BY user_id")
        return await cur.fetchall()
    return await execute_db(_get)

async def db_update_user_cache(user_id: int, username: str, first_name: str):
    async def _update(conn):
        await conn.execute("INSERT OR REPLACE INTO users_cache (user_id, username, first_name, last_updated) VALUES (?, ?, ?, ?)", (user_id, username or "", first_name or "", utc_now_iso()))
        await conn.commit()
    return await execute_db(_update)

async def db_is_banned(user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT banned FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_check)

async def db_set_ban(user_id: int, banned: bool):
    async def _set(conn):
        await conn.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, user_id))
        await conn.commit()
    return await execute_db(_set)

async def db_has_used_trial(user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT trial_used FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_check)

async def db_activate_trial(user_id: int) -> int:
    async def _activate(conn):
        cur = await conn.execute("SELECT trial_used FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0] == 1:
            return 0
        end_date = (utc_now() + timedelta(days=30)).isoformat()
        await conn.execute("UPDATE users SET trial_used=1, subscription_end=? WHERE user_id=?", (end_date, user_id))
        await conn.commit()
        return 30
    return await execute_db(_activate)

async def db_activate_subscription(user_id: int, days: int):
    async def _activate(conn):
        cur = await conn.execute("SELECT subscription_end FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        try:
            if row and row[0]:
                current_end = datetime.fromisoformat(row[0])
                if current_end > utc_now():
                    new_end = current_end + timedelta(days=days)
                else:
                    new_end = utc_now() + timedelta(days=days)
            else:
                new_end = utc_now() + timedelta(days=days)
        except:
            new_end = utc_now() + timedelta(days=days)
        await conn.execute("UPDATE users SET subscription_end=? WHERE user_id=?", (new_end.isoformat(), user_id))
        await conn.commit()
    return await execute_db(_activate)

async def db_has_active_subscription(user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT subscription_end FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0]:
            try:
                end_date = datetime.fromisoformat(row[0])
                return end_date > utc_now()
            except:
                return False
        return False
    return await execute_db(_check)

async def db_get_subscription_days_left(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT subscription_end FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0]:
            try:
                end_date = datetime.fromisoformat(row[0])
                days = (end_date - utc_now()).days
                return max(0, days)
            except:
                return 0
        return 0
    return await execute_db(_get)

async def db_auto_status(user_id: int) -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT auto_publish FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_get)

async def db_set_auto(user_id: int, enabled: bool):
    async def _set(conn):
        await conn.execute("UPDATE users SET auto_publish=? WHERE user_id=?", (1 if enabled else 0, user_id))
        await conn.commit()
    return await execute_db(_set)

async def db_get_auto_recycle(user_id: int) -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT auto_recycle FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_get)

async def db_set_auto_recycle(user_id: int, enabled: bool):
    async def _set(conn):
        await conn.execute("UPDATE users SET auto_recycle=? WHERE user_id=?", (1 if enabled else 0, user_id))
        await conn.commit()
    return await execute_db(_set)

async def db_add_channel(user_id: int, channel_id: str, channel_name: str) -> int:
    async def _add(conn):
        cur = await conn.execute("SELECT id FROM user_channels WHERE user_id=? AND channel_id=?", (user_id, channel_id))
        if await cur.fetchone():
            return None
        cur = await conn.execute("INSERT INTO user_channels (user_id, channel_id, channel_name, created_at) VALUES (?, ?, ?, ?) RETURNING id", (user_id, channel_id, channel_name, utc_now_iso()))
        row = await cur.fetchone()
        await conn.commit()
        if row:
            new_id = row[0]
            await db_set_next_publish_date(new_id, utc_now() + timedelta(minutes=1))
        return row[0] if row else None
    return await execute_db(_add)

async def db_get_channels(user_id: int):
    async def _get(conn):
        try:
            cur = await conn.execute("SELECT id, channel_id, channel_name, banned FROM user_channels WHERE user_id=? ORDER BY id", (user_id,))
            rows = await cur.fetchall()
            safe_rows = []
            for row in rows:
                try:
                    if len(row) >= 4:
                        safe_rows.append((row[0], row[1] or "unknown", row[2] or str(row[0]), row[3] if row[3] is not None else 0))
                except:
                    continue
            return safe_rows
        except Exception as e:
            logger.error(f"Error getting channels for user {user_id}: {e}")
            return []
    return await execute_db(_get)

async def db_get_channel_info(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT channel_id, channel_name FROM user_channels WHERE id=?", (channel_db_id,))
        return await cur.fetchone()
    return await execute_db(_get)

async def db_delete_channel_by_id(user_id: int, channel_db_id: int) -> bool:
    async def _delete(conn):
        await conn.execute("DELETE FROM user_channels WHERE id=? AND user_id=?", (channel_db_id, user_id))
        await conn.execute("DELETE FROM posts WHERE channel_db_id=?", (channel_db_id,))
        await conn.execute("DELETE FROM schedule WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
        return True
    return await execute_db(_delete)

async def db_get_active_channel(user_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT active_channel FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0] is not None:
            return row[0]
        cur = await conn.execute("SELECT id FROM user_channels WHERE user_id=? AND banned=0 ORDER BY id LIMIT 1", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_set_active_channel(user_id: int, channel_db_id: int):
    async def _set(conn):
        await conn.execute("UPDATE users SET active_channel=? WHERE user_id=?", (channel_db_id, user_id))
        await conn.commit()
    return await execute_db(_set)

async def db_get_user_channels_count(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM user_channels WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_get)

async def db_get_all_user_channels_no_limit():
    async def _get(conn):
        cur = await conn.execute("SELECT uc.user_id, uc.id, uc.channel_id, uc.channel_name, uc.banned FROM user_channels uc ORDER BY uc.id")
        return await cur.fetchall()
    return await execute_db(_get)

async def db_all_users_channels(only_banned: bool = False, limit: int = 500):
    async def _get(conn):
        if only_banned:
            cur = await conn.execute("SELECT user_id, id, channel_id, channel_name, banned FROM user_channels WHERE banned=1 LIMIT ?", (limit,))
        else:
            cur = await conn.execute("SELECT user_id, id, channel_id, channel_name, banned FROM user_channels LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_register_channel(channel_id: int, channel_name: str, added_by: int):
    async def _register(conn):
        cur = await conn.execute("SELECT channel_id FROM bot_channels WHERE channel_id=?", (channel_id,))
        if await cur.fetchone():
            await conn.execute("UPDATE bot_channels SET channel_name=?, added_by=? WHERE channel_id=?", (channel_name, added_by, channel_id))
            await conn.commit()
            return False
        await conn.execute("INSERT INTO bot_channels (channel_id, channel_name, added_by, added_at) VALUES (?, ?, ?, ?)", (channel_id, channel_name, added_by, utc_now_iso()))
        await conn.commit()
        return True
    return await execute_db(_register)

async def db_get_all_bot_channels(only_banned: bool = False):
    async def _get(conn):
        if only_banned:
            cur = await conn.execute("SELECT channel_id, channel_name, added_by, added_at, banned FROM bot_channels WHERE banned=1 ORDER BY added_at DESC")
        else:
            cur = await conn.execute("SELECT channel_id, channel_name, added_by, added_at, banned FROM bot_channels ORDER BY added_at DESC")
        return await cur.fetchall()
    return await execute_db(_get)

async def db_save_posts(channel_db_id: int, posts: list) -> int:
    async def _save(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0", (channel_db_id,))
        current_unpublished = (await cur.fetchone())[0]
        max_allowed = MAX_UNPUBLISHED_POSTS - current_unpublished
        if max_allowed <= 0:
            return 0
        posts_to_save = posts[:max_allowed]
        values = []
        for text_content, media_type, media_file_id in posts_to_save:
            values.append((channel_db_id, text_content or "", media_type, media_file_id, utc_now_iso()))
        await conn.executemany("INSERT INTO posts (channel_db_id, text, media_type, media_file_id, created_at) VALUES (?, ?, ?, ?, ?)", values)
        await conn.commit()
        return len(values)
    return await execute_db(_save)

async def db_get_next_post(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT id, text, media_type, media_file_id FROM posts WHERE channel_db_id=? AND published=0 AND (fail_count IS NULL OR fail_count < 3) ORDER BY id LIMIT 1", (channel_db_id,))
        row = await cur.fetchone()
        if row:
            return {"id": row[0], "text": row[1], "media_type": row[2], "media_file_id": row[3]}
        return None
    return await execute_db(_get)

async def db_mark_published(post_id: int):
    async def _mark(conn):
        await conn.execute("UPDATE posts SET published=1 WHERE id=?", (post_id,))
        await conn.commit()
    return await execute_db(_mark)

async def db_increment_fail_count(post_id: int):
    async def _inc(conn):
        await conn.execute("UPDATE posts SET fail_count = fail_count + 1 WHERE id=?", (post_id,))
        await conn.commit()
    return await execute_db(_inc)

async def db_get_posts_count(channel_db_id: int) -> int:
    async def _count(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_count)

async def db_get_published_count(channel_db_id: int) -> int:
    async def _count(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=1", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_count)

async def db_reset_all_posts_to_unpublished(channel_db_id: int) -> int:
    async def _reset(conn):
        await conn.execute("UPDATE posts SET published=0, fail_count=0 WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_reset)

async def db_get_user_posts_for_channel(channel_db_id: int, limit=15):
    async def _get(conn):
        cur = await conn.execute("SELECT id, text, media_type FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT ?", (channel_db_id, limit))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_delete_single_post(post_id: int, user_id: int, channel_db_id: int) -> bool:
    async def _delete(conn):
        cur = await conn.execute("SELECT 1 FROM posts p JOIN user_channels uc ON p.channel_db_id=uc.id WHERE p.id=? AND uc.user_id=?", (post_id, user_id))
        if not await cur.fetchone():
            return False
        await conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
        await conn.commit()
        return True
    return await execute_db(_delete)

async def db_get_user_unpublished_posts(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts p JOIN user_channels uc ON p.channel_db_id=uc.id WHERE uc.user_id=? AND p.published=0", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_get)

async def db_get_user_total_posts(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts p JOIN user_channels uc ON p.channel_db_id=uc.id WHERE uc.user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_get)

async def db_unpublished_count(channel_db_id: int) -> int:
    async def _count(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_count)

async def db_update_post_views(post_id: int, views_count: int = None):
    async def _update_views(conn):
        if views_count is not None:
            await conn.execute("UPDATE posts SET views_count = ?, last_view_time = ? WHERE id = ?", (views_count, utc_now_iso(), post_id))
        else:
            await conn.execute("UPDATE posts SET views_count = views_count + 1, last_view_time = ? WHERE id = ?", (utc_now_iso(), post_id))
        await conn.commit()
    return await execute_db(_update_views)

async def db_stats():
    async def _stats(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM users")
        total = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM users WHERE banned=1")
        banned = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE published=0")
        posts = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM bot_groups")
        groups = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM user_channels")
        channels = (await cur.fetchone())[0]
        return total, banned, posts, groups, channels
    return await execute_db(_stats)

async def db_register_group(chat_id: int, chat_name: str, added_by: int, username: str = None) -> bool:
    async def _register(conn):
        cur = await conn.execute("SELECT chat_id FROM bot_groups WHERE chat_id=?", (chat_id,))
        if await cur.fetchone():
            await conn.execute("UPDATE bot_groups SET chat_name=?, username=?, added_by=? WHERE chat_id=?", (chat_name, username, added_by, chat_id))
            await conn.commit()
            return False
        await conn.execute("INSERT INTO bot_groups (chat_id, chat_name, username, added_by, added_at) VALUES (?, ?, ?, ?, ?)", (chat_id, chat_name, username, added_by, utc_now_iso()))
        await conn.execute("INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?, ?)", (added_by, chat_id))
        await conn.commit()
        return True
    return await execute_db(_register)

async def db_get_user_groups(user_id: int):
    async def _get(conn):
        cur = await conn.execute("""
            SELECT bg.chat_id, bg.chat_name, bg.username, bg.banned
            FROM bot_groups bg
            WHERE bg.added_by = ?
               OR EXISTS (SELECT 1 FROM hidden_owner_groups hog WHERE hog.chat_id = bg.chat_id AND hog.owner_id = ?)
               OR EXISTS (SELECT 1 FROM hidden_admins ha WHERE ha.chat_id = bg.chat_id AND ha.admin_id = ?)
               OR EXISTS (SELECT 1 FROM user_groups_link ugl WHERE ugl.chat_id = bg.chat_id AND ugl.user_id = ?)
            ORDER BY bg.chat_name
        """, (user_id, user_id, user_id, user_id))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_user_groups_count(user_id: int) -> int:
    groups = await db_get_user_groups(user_id)
    return len(groups)

async def db_get_all_groups(only_banned: bool = False):
    async def _get(conn):
        if only_banned:
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups WHERE banned=1 ORDER BY added_at DESC")
        else:
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups ORDER BY added_at DESC")
        return await cur.fetchall()
    return await execute_db(_get)

async def db_set_chat_lock(chat_id: int, locked: bool, locked_by: int = None):
    async def _set(conn):
        if locked:
            await conn.execute("INSERT OR REPLACE INTO chat_locks (chat_id, locked, locked_at, locked_by) VALUES (?, 1, ?, ?)", (chat_id, utc_now_iso(), locked_by))
        else:
            await conn.execute("DELETE FROM chat_locks WHERE chat_id=?", (chat_id,))
        await conn.commit()
    return await execute_db(_set)

async def is_chat_locked(chat_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT locked FROM chat_locks WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_check)

async def db_get_security_settings(chat_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT delete_links, delete_mentions, warn_message, slow_mode, slow_mode_seconds, welcome_enabled, welcome_text, goodbye_enabled, goodbye_text, delete_banned_words, auto_penalty, auto_mute_duration FROM group_security WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        if row:
            settings = {
                "links": row[0] == 1,
                "mentions": row[1] == 1,
                "warn": row[2] == 1,
                "slow_mode": row[3] == 1,
                "slow_mode_seconds": row[4] if row[4] is not None else 5,
                "welcome_enabled": row[5] == 1,
                "welcome_text": row[6] if row[6] else "مرحباً {user} في {chat} 🤍",
                "goodbye_enabled": row[7] == 1,
                "goodbye_text": row[8] if row[8] else "وداعاً {user} 👋",
                "delete_banned_words": row[9] == 1,
                "auto_penalty": row[10] if row[10] else "none",
                "auto_mute_duration": row[11] if row[11] is not None else 60
            }
            return settings
        default_settings = {
            "links": False, "mentions": False, "warn": True, "slow_mode": False,
            "slow_mode_seconds": 5, "welcome_enabled": False, "welcome_text": "مرحباً {user} في {chat} 🤍",
            "goodbye_enabled": False, "goodbye_text": "وداعاً {user} 👋", "delete_banned_words": False,
            "auto_penalty": "none", "auto_mute_duration": 60
        }
        return default_settings
    return await execute_db(_get)

async def db_set_security_settings(chat_id: int, **kwargs):
    async def _set(conn):
        cur = await conn.execute("SELECT 1 FROM group_security WHERE chat_id=?", (chat_id,))
        exists = await cur.fetchone()
        if exists:
            updates = []
            values = []
            for key, value in kwargs.items():
                if key == "links":
                    updates.append("delete_links=?")
                    values.append(1 if value else 0)
                elif key == "mentions":
                    updates.append("delete_mentions=?")
                    values.append(1 if value else 0)
                elif key == "warn":
                    updates.append("warn_message=?")
                    values.append(1 if value else 0)
                elif key == "slow_mode":
                    updates.append("slow_mode=?")
                    values.append(1 if value else 0)
                elif key == "slow_mode_seconds":
                    updates.append("slow_mode_seconds=?")
                    values.append(value)
                elif key == "welcome_enabled":
                    updates.append("welcome_enabled=?")
                    values.append(1 if value else 0)
                elif key == "welcome_text":
                    updates.append("welcome_text=?")
                    values.append(value)
                elif key == "goodbye_enabled":
                    updates.append("goodbye_enabled=?")
                    values.append(1 if value else 0)
                elif key == "goodbye_text":
                    updates.append("goodbye_text=?")
                    values.append(value)
                elif key == "delete_banned_words":
                    updates.append("delete_banned_words=?")
                    values.append(1 if value else 0)
                elif key == "auto_penalty":
                    updates.append("auto_penalty=?")
                    values.append(value)
                elif key == "auto_mute_duration":
                    updates.append("auto_mute_duration=?")
                    values.append(value)
            if updates:
                query = f"UPDATE group_security SET {', '.join(updates)} WHERE chat_id=?"
                values.append(chat_id)
                await conn.execute(query, values)
        else:
            await conn.execute("""
                INSERT INTO group_security (chat_id, delete_links, delete_mentions, warn_message, slow_mode, slow_mode_seconds, welcome_enabled, welcome_text, goodbye_enabled, goodbye_text, delete_banned_words, auto_penalty, auto_mute_duration)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (chat_id,
                  1 if kwargs.get("links", False) else 0,
                  1 if kwargs.get("mentions", False) else 0,
                  1 if kwargs.get("warn", True) else 0,
                  1 if kwargs.get("slow_mode", False) else 0,
                  kwargs.get("slow_mode_seconds", 5),
                  1 if kwargs.get("welcome_enabled", False) else 0,
                  kwargs.get("welcome_text", "مرحباً {user} في {chat} 🤍"),
                  1 if kwargs.get("goodbye_enabled", False) else 0,
                  kwargs.get("goodbye_text", "وداعاً {user} 👋"),
                  1 if kwargs.get("delete_banned_words", False) else 0,
                  kwargs.get("auto_penalty", "none"),
                  kwargs.get("auto_mute_duration", 60)))
        await conn.commit()
    return await execute_db(_set)

async def db_check_slow_mode(chat_id: int, user_id: int) -> bool:
    settings = await db_get_security_settings(chat_id)
    if not settings["slow_mode"]:
        return True
    seconds = settings.get("slow_mode_seconds", 5)
    async def _check(conn):
        cur = await conn.execute("SELECT message_time FROM user_messages WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        row = await cur.fetchone()
        now = utc_now()
        if row:
            last_time = datetime.fromisoformat(row[0])
            if (now - last_time).total_seconds() < seconds:
                return False
        await conn.execute("INSERT OR REPLACE INTO user_messages (user_id, chat_id, message_time) VALUES (?, ?, ?)", (user_id, chat_id, now.isoformat()))
        await conn.commit()
        return True
    return await execute_db(_check)

async def db_add_banned_word(word: str, chat_id: int, added_by: int) -> bool:
    async def _add(conn):
        try:
            await conn.execute("INSERT OR IGNORE INTO banned_words (word, chat_id, added_by, added_at) VALUES (?, ?, ?, ?)", (word, chat_id, added_by, utc_now_iso()))
            await conn.commit()
            return True
        except:
            return False
    return await execute_db(_add)

async def db_remove_banned_word(word: str, chat_id: int) -> bool:
    async def _remove(conn):
        await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, chat_id))
        await conn.commit()
        return True
    return await execute_db(_remove)

async def db_get_banned_words(chat_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT word, added_by, added_at FROM banned_words WHERE chat_id=? OR chat_id=-1 ORDER BY word", (chat_id,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_contains_banned_word(text: str, chat_id: int) -> str:
    words = await db_get_banned_words(chat_id)
    text_lower = text.lower()
    for word, _, _ in words:
        if word in text_lower:
            return word
    return None

async def db_register_hidden_owner_group(chat_id: int, owner_id: int):
    async def _register(conn):
        await conn.execute("INSERT OR REPLACE INTO hidden_owner_groups (chat_id, owner_id, is_hidden) VALUES (?, ?, 1)", (chat_id, owner_id))
        await conn.execute("INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?, ?)", (owner_id, chat_id))
        await conn.commit()
    return await execute_db(_register)

async def db_is_hidden_owner(chat_id: int, user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?", (chat_id, user_id))
        return await cur.fetchone() is not None
    return await execute_db(_check)

async def db_add_hidden_admin(chat_id: int, admin_id: int, added_by: int) -> bool:
    async def _add(conn):
        try:
            await conn.execute("INSERT OR IGNORE INTO hidden_admins (chat_id, admin_id, added_by, added_at) VALUES (?, ?, ?, ?)", (chat_id, admin_id, added_by, utc_now_iso()))
            await conn.execute("INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?, ?)", (admin_id, chat_id))
            await conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding hidden admin: {e}")
            return False
    return await execute_db(_add)

async def db_remove_hidden_admin(chat_id: int, admin_id: int) -> bool:
    async def _remove(conn):
        await conn.execute("DELETE FROM hidden_admins WHERE chat_id=? AND admin_id=?", (chat_id, admin_id))
        await conn.execute("DELETE FROM user_groups_link WHERE user_id=? AND chat_id=?", (admin_id, chat_id))
        await conn.commit()
        return True
    return await execute_db(_remove)

async def db_is_hidden_admin(chat_id: int, user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM hidden_admins WHERE chat_id=? AND admin_id=?", (chat_id, user_id))
        return await cur.fetchone() is not None
    return await execute_db(_check)

async def db_get_hidden_admins(chat_id: int) -> List[Dict]:
    async def _get(conn):
        cur = await conn.execute("SELECT admin_id, added_by, added_at FROM hidden_admins WHERE chat_id=? ORDER BY added_at DESC", (chat_id,))
        rows = await cur.fetchall()
        return [{"admin_id": row[0], "added_by": row[1], "added_at": row[2]} for row in rows]
    return await execute_db(_get)

async def add_bot_admin(user_id: int):
    async def _add(conn):
        await conn.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (user_id,))
        await conn.commit()
    return await execute_db(_add)

async def remove_bot_admin(user_id: int):
    async def _remove(conn):
        await conn.execute("DELETE FROM bot_admins WHERE user_id=?", (user_id,))
        await conn.commit()
    return await execute_db(_remove)

async def is_bot_admin(user_id: int) -> bool:
    if user_id == PRIMARY_OWNER_ID:
        return True
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM bot_admins WHERE user_id=?", (user_id,))
        return await cur.fetchone() is not None
    return await execute_db(_check)

async def get_all_bot_admins():
    async def _get(conn):
        cur = await conn.execute("SELECT user_id FROM bot_admins")
        rows = await cur.fetchall()
        return [row[0] for row in rows]
    return await execute_db(_get)

async def db_save_schedule(channel_db_id: int, schedule_type: str, interval_minutes: int = None, interval_hours: int = None, interval_days: int = None, days_of_week: str = None, specific_dates: str = None, publish_time: str = None, cron_expression: str = None):
    async def _save(conn):
        await conn.execute("INSERT OR REPLACE INTO schedule (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, cron_expression, next_publish_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)", (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time or "00:00", cron_expression))
        await conn.commit()
    return await execute_db(_save)

async def db_get_schedule(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, cron_expression, next_publish_date FROM schedule WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        if row:
            return {
                "type": row[0] or "interval_minutes",
                "interval_minutes": row[1] or 12,
                "interval_hours": row[2] or 0,
                "interval_days": row[3] or 0,
                "days_of_week": row[4] or "[]",
                "specific_dates": row[5] or "[]",
                "publish_time": row[6] or "00:00",
                "cron_expression": row[7],
                "next_publish_date": row[8]
            }
        return {"type": "interval_minutes", "interval_minutes": 12, "interval_hours": 0, "interval_days": 0, "days_of_week": "[]", "specific_dates": "[]", "publish_time": "00:00", "cron_expression": None, "next_publish_date": None}
    return await execute_db(_get)

async def db_set_next_publish_date(channel_db_id: int, next_date: datetime):
    async def _set(conn):
        if next_date:
            await conn.execute("UPDATE schedule SET next_publish_date=? WHERE channel_db_id=?", (next_date.isoformat(), channel_db_id))
        else:
            await conn.execute("UPDATE schedule SET next_publish_date=NULL WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
    return await execute_db(_set)

async def db_set_last_publish(channel_db_id: int, publish_time: datetime):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO last_publish (channel_db_id, last_publish_time) VALUES (?, ?)", (channel_db_id, publish_time.isoformat()))
        await conn.commit()
    return await execute_db(_set)

async def schedule_cron(channel_db_id: int, cron_expression: str):
    async def _save(conn):
        await conn.execute("UPDATE schedule SET schedule_type='cron', cron_expression=?, next_publish_date=NULL WHERE channel_db_id=?", (cron_expression, channel_db_id))
        await conn.commit()
    return await execute_db(_save)

async def db_update_next_publish_date(channel_db_id: int):
    async def _update(conn):
        schedule = await db_get_schedule(channel_db_id)
        last_publish_cur = await conn.execute("SELECT last_publish_time FROM last_publish WHERE channel_db_id=?", (channel_db_id,))
        last_row = await last_publish_cur.fetchone()
        last_time = datetime.fromisoformat(last_row[0]) if last_row else utc_now()
        schedule_type = schedule["type"]
        publish_time_str = schedule.get("publish_time", "00:00")
        if ":" not in publish_time_str:
            publish_time_str = "00:00"
        try:
            hour, minute = map(int, publish_time_str.split(":"))
        except:
            hour, minute = 0, 0
        next_date = None
        now = utc_now()
        if schedule_type == "interval_minutes":
            minutes = schedule.get("interval_minutes", 12)
            next_date = last_time + timedelta(minutes=minutes)
        elif schedule_type == "interval_hours":
            hours = schedule.get("interval_hours", 1)
            next_date = last_time + timedelta(hours=hours)
        elif schedule_type == "interval_days":
            days = schedule.get("interval_days", 1)
            next_date = last_time + timedelta(days=days)
        elif schedule_type == "days":
            days_of_week = json.loads(schedule.get("days_of_week", "[]"))
            if days_of_week:
                target_date = last_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                found = False
                for i in range(1, 8):
                    check_date = target_date + timedelta(days=i)
                    if check_date.weekday() in days_of_week:
                        next_date = check_date
                        found = True
                        break
                if not found:
                    next_date = target_date + timedelta(days=7)
                    while next_date.weekday() not in days_of_week:
                        next_date += timedelta(days=1)
            else:
                next_date = last_time + timedelta(days=1)
        elif schedule_type == "dates":
            specific_dates = json.loads(schedule.get("specific_dates", "[]"))
            if specific_dates:
                target_date = last_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                for date_str in sorted(specific_dates):
                    try:
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, minute=minute, second=0, microsecond=0)
                        if date_obj > last_time:
                            next_date = date_obj
                            break
                    except:
                        continue
                if not next_date:
                    try:
                        next_date = datetime.strptime(specific_dates[0], "%Y-%m-%d").replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=365)
                    except:
                        next_date = utc_now() + timedelta(days=1)
            else:
                next_date = utc_now() + timedelta(days=1)
        elif schedule_type == "cron":
            cron_expr = schedule.get("cron_expression", "0 0 * * *")
            try:
                parts = cron_expr.split()
                if len(parts) >= 5:
                    minute_cron, hour_cron, day_cron, month_cron, weekday_cron = parts[:5]
                    next_date = last_time + timedelta(days=1)
                    for i in range(1, 31):
                        check_date = last_time + timedelta(days=i)
                        if check_date.hour == hour and check_date.minute == minute:
                            if day_cron == "*" or check_date.day == int(day_cron):
                                if month_cron == "*" or check_date.month == int(month_cron):
                                    if weekday_cron == "*" or check_date.weekday() == int(weekday_cron):
                                        next_date = check_date
                                        break
            except:
                next_date = utc_now() + timedelta(days=1)
        else:
            next_date = utc_now() + timedelta(minutes=schedule.get("interval_minutes", 12))
        if next_date:
            await conn.execute("UPDATE schedule SET next_publish_date=? WHERE channel_db_id=?", (next_date.isoformat(), channel_db_id))
            await conn.commit()
    return await execute_db(_update)

async def db_set_publish_time(channel_db_id: int, time_str: str):
    async def _set(conn):
        await conn.execute("UPDATE schedule SET publish_time=? WHERE channel_db_id=?", (time_str, channel_db_id))
        await conn.commit()
    return await execute_db(_set)

async def db_add_scheduled_post(chat_id: int, text: str, publish_time: datetime):
    async def _add(conn):
        await conn.execute("INSERT INTO scheduled_posts (chat_id, text, publish_time, fail_count) VALUES (?, ?, ?, 0)", (chat_id, text, publish_time.isoformat()))
        await conn.commit()
    return await execute_db(_add)

async def db_get_due_scheduled_posts(now: datetime):
    async def _get(conn):
        cur = await conn.execute("SELECT id, chat_id, text, fail_count FROM scheduled_posts WHERE publish_time <= ?", (now.isoformat(),))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_update_scheduled_post_fail(post_id: int, fail_count: int):
    async def _update(conn):
        await conn.execute("UPDATE scheduled_posts SET fail_count = ? WHERE id = ?", (fail_count, post_id))
        await conn.commit()
    return await execute_db(_update)

async def db_delete_scheduled_post(post_id: int):
    async def _delete(conn):
        await conn.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
        await conn.commit()
    return await execute_db(_delete)

async def db_add_reply(keyword, reply):
    async def _add(conn):
        await conn.execute("INSERT OR REPLACE INTO group_replies (keyword, reply) VALUES (?,?)", (keyword.lower(), reply))
        await conn.commit()
    return await execute_db(_add)

async def db_del_reply(keyword):
    async def _del(conn):
        await conn.execute("DELETE FROM group_replies WHERE keyword=?", (keyword.lower(),))
        await conn.commit()
    return await execute_db(_del)

async def db_get_reply(keyword):
    async def _get(conn):
        cur = await conn.execute("SELECT reply FROM group_replies WHERE keyword=?", (keyword.lower(),))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_get_all_replies():
    async def _get(conn):
        cur = await conn.execute("SELECT keyword, reply FROM group_replies ORDER BY keyword")
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_auto_reply_settings(chat_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute("SELECT enabled, only_admins, ignore_bots FROM auto_reply_settings WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        if row:
            return {"enabled": row[0] == 1, "only_admins": row[1] == 1, "ignore_bots": row[2] == 1}
        return {"enabled": True, "only_admins": False, "ignore_bots": True}
    return await execute_db(_get)

async def db_set_auto_reply_enabled(chat_id: int, enabled: bool) -> None:
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO auto_reply_settings (chat_id, enabled, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (chat_id, 1 if enabled else 0))
        await conn.commit()
    return await execute_db(_set)

async def db_set_auto_reply_only_admins(chat_id: int, only_admins: bool) -> None:
    async def _set(conn):
        await conn.execute("UPDATE auto_reply_settings SET only_admins=?, updated_at=CURRENT_TIMESTAMP WHERE chat_id=?", (1 if only_admins else 0, chat_id))
        await conn.commit()
    return await execute_db(_set)

async def db_toggle_auto_reply(chat_id: int) -> bool:
    settings = await db_get_auto_reply_settings(chat_id)
    new_status = not settings["enabled"]
    await db_set_auto_reply_enabled(chat_id, new_status)
    return new_status

async def db_get_user_auto_reply_status(user_id: int) -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT auto_reply_enabled FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] == 1 if row else True
    return await execute_db(_get)

async def db_set_user_auto_reply_status(user_id: int, enabled: bool) -> None:
    async def _set(conn):
        await conn.execute("UPDATE users SET auto_reply_enabled=? WHERE user_id=?", (1 if enabled else 0, user_id))
        await conn.commit()
    return await execute_db(_set)

async def db_get_next_ticket_number():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='last_ticket_number'")
        row = await cur.fetchone()
        return int(row[0]) if row else 0
    return await execute_db(_get)

async def db_save_ticket(user_id, username, message, ticket_num):
    async def _save(conn):
        created_at = utc_now_iso()
        await conn.execute("INSERT INTO support_tickets (user_id, username, message, ticket_number, status, created_at) VALUES (?,?,?,?,?,?)", (user_id, username, message, ticket_num, "pending", created_at))
        await conn.commit()
        return True
    return await execute_db(_save)

async def db_get_user_ticket(user_id):
    async def _get(conn):
        cur = await conn.execute("SELECT ticket_number, status, created_at FROM support_tickets WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        return await cur.fetchone()
    return await execute_db(_get)

async def db_get_all_tickets(limit=20):
    async def _get(conn):
        cur = await conn.execute("SELECT id, user_id, username, message, ticket_number, status, created_at FROM support_tickets ORDER BY id DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_last_ticket_id_for_user(user_id):
    async def _get(conn):
        cur = await conn.execute("SELECT id FROM support_tickets WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_mark_ticket_replied(ticket_id):
    async def _mark(conn):
        await conn.execute("UPDATE support_tickets SET status='replied', replied=1 WHERE id=?", (ticket_id,))
        await conn.commit()
    return await execute_db(_mark)

async def db_delete_all_tickets() -> int:
    async def _delete(conn):
        cur = await conn.execute("DELETE FROM support_tickets")
        count = cur.rowcount
        await conn.execute("UPDATE settings SET value='0' WHERE key='last_ticket_number'")
        await conn.commit()
        return count
    return await execute_db(_delete)

async def db_get_referral_settings() -> dict:
    async def _get(conn):
        settings = {}
        cur = await conn.execute("SELECT key, value FROM referral_settings")
        rows = await cur.fetchall()
        for key, value in rows:
            settings[key] = value
        return settings
    return await execute_db(_get)

async def db_get_referral_code(user_id: int) -> str:
    async def _get(conn):
        cur = await conn.execute("SELECT referral_code FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row and row[0] else None
    return await execute_db(_get)

async def db_generate_referral_code(user_id: int) -> str:
    async def _generate(conn):
        code_hash = hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:8]
        referral_code = f"REF{code_hash.upper()}"
        await conn.execute("UPDATE users SET referral_code=? WHERE user_id=?", (referral_code, user_id))
        await conn.commit()
        return referral_code
    return await execute_db(_generate)

async def db_get_user_by_referral_code(referral_code: str) -> int | None:
    async def _get(conn):
        cur = await conn.execute("SELECT user_id FROM users WHERE referral_code=?", (referral_code,))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_add_referral(referrer_id: int, referred_id: int) -> bool:
    async def _add(conn):
        if referrer_id == referred_id:
            return False
        cur = await conn.execute("SELECT 1 FROM referrals WHERE referred_id=?", (referred_id,))
        if await cur.fetchone():
            return False
        today_start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        cur = await conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND referred_at >= ?", (referrer_id, today_start))
        count_today = (await cur.fetchone())[0]
        settings = await db_get_referral_settings()
        max_per_day = int(settings.get("max_referrals_per_day", "5"))
        if count_today >= max_per_day:
            return False
        await conn.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, referred_id))
        await conn.execute("INSERT INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days) VALUES (?, 1, 0, 0) ON CONFLICT(user_id) DO UPDATE SET referral_count = referral_count + 1", (referrer_id,))
        await conn.commit()
        return True
    return await execute_db(_add)

async def db_auto_reward_referral(referrer_id: int, referred_id: int) -> int:
    async def _reward(conn):
        settings = await db_get_referral_settings()
        reward_days = int(settings.get("reward_days_per_referral", "3"))
        await conn.execute("INSERT INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days) VALUES (?, 0, ?, 0) ON CONFLICT(user_id) DO UPDATE SET total_reward_days = total_reward_days + ?", (referrer_id, reward_days, reward_days))
        await conn.execute("UPDATE referrals SET is_rewarded=1 WHERE referrer_id=? AND referred_id=?", (referrer_id, referred_id))
        await conn.commit()
        return reward_days
    return await execute_db(_reward)

async def db_get_referral_stats(user_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
        total_referrals = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT referral_count, total_reward_days, claimed_reward_days FROM referral_rewards WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return {
            "total_referrals": total_referrals,
            "referral_count": row[0] if row else 0,
            "total_reward_days": row[1] if row else 0,
            "claimed_reward_days": row[2] if row else 0,
            "available_days": (row[1] if row else 0) - (row[2] if row else 0)
        }
    return await execute_db(_get)

async def db_claim_referral_reward(user_id: int) -> int:
    async def _claim(conn):
        cur = await conn.execute("SELECT total_reward_days, claimed_reward_days FROM referral_rewards WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if not row:
            return 0
        total = row[0]
        claimed = row[1]
        available = total - claimed
        if available <= 0:
            return 0
        current_sub = await db_get_subscription_days_left(user_id)
        new_sub_days = current_sub + available
        end_date = (utc_now() + timedelta(days=new_sub_days)).isoformat()
        await conn.execute("UPDATE users SET subscription_end=? WHERE user_id=?", (end_date, user_id))
        await conn.execute("UPDATE referral_rewards SET claimed_reward_days = claimed_reward_days + ? WHERE user_id=?", (available, user_id))
        await conn.commit()
        return available
    return await execute_db(_claim)

async def db_get_welcome_bonus_points() -> int:
    settings = await db_get_referral_settings()
    return int(settings.get("welcome_bonus_points", "10"))

async def db_get_user_reminder_settings(user_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute("SELECT subscription_reminder, daily_stats_reminder, weekly_report, reminder_days_before, last_reminder_sent, notification_lang FROM user_reminder_settings WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row:
            return {
                "subscription_reminder": row[0] == 1,
                "daily_stats_reminder": row[1] == 1,
                "weekly_report": row[2] == 1,
                "reminder_days_before": row[3] if row[3] is not None else 3,
                "last_reminder_sent": row[4] if row[4] else 0,
                "notification_lang": row[5] if row[5] else "ar"
            }
        else:
            await conn.execute("INSERT INTO user_reminder_settings (user_id, subscription_reminder, daily_stats_reminder, weekly_report, reminder_days_before, last_reminder_sent, notification_lang) VALUES (?, 1, 0, 1, 3, 0, 'ar')", (user_id,))
            await conn.commit()
            return {"subscription_reminder": True, "daily_stats_reminder": False, "weekly_report": True, "reminder_days_before": 3, "last_reminder_sent": 0, "notification_lang": "ar"}
    return await execute_db(_get)

async def db_update_reminder_settings(user_id: int, **kwargs):
    async def _update(conn):
        fields, values = [], []
        for key, value in kwargs.items():
            if key == "subscription_reminder":
                fields.append("subscription_reminder=?")
                values.append(1 if value else 0)
            elif key == "daily_stats_reminder":
                fields.append("daily_stats_reminder=?")
                values.append(1 if value else 0)
            elif key == "weekly_report":
                fields.append("weekly_report=?")
                values.append(1 if value else 0)
            elif key == "reminder_days_before":
                fields.append("reminder_days_before=?")
                values.append(value)
            elif key == "notification_lang":
                fields.append("notification_lang=?")
                values.append(value)
        if fields:
            query = f"UPDATE user_reminder_settings SET {', '.join(fields)} WHERE user_id=?"
            values.append(user_id)
            await conn.execute(query, values)
            await conn.commit()
    return await execute_db(_update)

async def db_update_last_reminder_sent(user_id: int, reminder_type: str):
    async def _update(conn):
        now_timestamp = int(time.time())
        await conn.execute("UPDATE user_reminder_settings SET last_reminder_sent=? WHERE user_id=?", (now_timestamp, user_id))
        await conn.commit()
    return await execute_db(_update)

async def db_get_users_needing_reminder() -> list:
    async def _get(conn):
        now = utc_now()
        users = []
        cur = await conn.execute("SELECT user_id, subscription_end FROM users WHERE subscription_end IS NOT NULL AND banned=0")
        rows = await cur.fetchall()
        for user_id, subscription_end_str in rows:
            try:
                end_date = datetime.fromisoformat(subscription_end_str)
                days_left = (end_date - now).days
                if days_left < 0:
                    continue
                settings = await db_get_user_reminder_settings(user_id)
                if settings["subscription_reminder"]:
                    reminder_days = settings["reminder_days_before"]
                    last_sent = settings["last_reminder_sent"]
                    now_timestamp = int(time.time())
                    need_reminder = False
                    if 0 < days_left <= reminder_days:
                        if last_sent == 0:
                            need_reminder = True
                        elif (now_timestamp - last_sent) > (3 * 24 * 60 * 60):
                            need_reminder = True
                    if need_reminder:
                        users.append({"user_id": user_id, "days_left": days_left, "notification_lang": settings["notification_lang"]})
            except:
                continue
        return users
    return await execute_db(_get)

async def db_get_all_active_users_for_report() -> list:
    async def _get(conn):
        thirty_days_ago = (utc_now() - timedelta(days=30)).isoformat()
        cur = await conn.execute("SELECT user_id FROM users_cache WHERE last_updated >= ?", (thirty_days_ago,))
        return [row[0] for row in await cur.fetchall()]
    return await execute_db(_get)

LEVEL_REQUIREMENTS = {1: 0, 2: 100, 3: 250, 4: 500, 5: 1000, 6: 2000, 7: 3500, 8: 5000, 9: 7500, 10: 10000}

async def db_get_user_level(user_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT points, level FROM user_levels WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row:
            return {"points": row[0], "level": row[1]}
        return {"points": 0, "level": 1}
    return await execute_db(_get)

async def db_update_user_level(user_id: int, points: int, level: int):
    async def _update(conn):
        await conn.execute("INSERT OR REPLACE INTO user_levels (user_id, points, level) VALUES (?,?,?)", (user_id, points, level))
        await conn.commit()
    return await execute_db(_update)

async def add_points(user_id: int):
    now = utc_now()
    count, last_timestamp = user_points_last_hour.get(user_id, (0, 0.0))
    if last_timestamp > 0:
        last_time = datetime.fromtimestamp(last_timestamp)
        last_time = to_naive(last_time)
        if (now - last_time).total_seconds() < 3600:
            if count >= 20:
                return
            new_count = count + 1
        else:
            new_count = 1
    else:
        new_count = 1
    user_points_last_hour[user_id] = (new_count, now.timestamp())
    data = await db_get_user_level(user_id)
    old_level = data["level"]
    points = data["points"] + 1
    level = old_level
    new_levels = []
    for lvl, pts in LEVEL_REQUIREMENTS.items():
        if points >= pts and lvl > level:
            new_levels.append(lvl)
            level = lvl
    await db_update_user_level(user_id, points, level)

async def get_rank(user_id: int) -> dict:
    return await db_get_user_level(user_id)

async def get_top_users(limit: int = 10):
    async def _get(conn):
        cur = await conn.execute("SELECT user_id, points, level FROM user_levels ORDER BY points DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def daily_reward(user_id: int) -> int:
    today = utc_now().date()
    async def _check(conn):
        cur = await conn.execute("SELECT last_daily_reward FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0]:
            try:
                last_date = datetime.fromisoformat(row[0]).date()
                if last_date == today:
                    return 0
            except:
                pass
        await conn.execute("UPDATE users SET last_daily_reward=? WHERE user_id=?", (utc_now_iso(), user_id))
        await conn.commit()
        return 10
    reward = await execute_db(_check)
    if reward > 0:
        data = await db_get_user_level(user_id)
        await db_update_user_level(user_id, data["points"] + reward, data["level"])
    return reward

async def weekly_reward(user_id: int) -> int:
    week_start = (utc_now() - timedelta(days=utc_now().weekday())).date()
    async def _check(conn):
        cur = await conn.execute("SELECT last_weekly_reward FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0]:
            try:
                last_date = datetime.fromisoformat(row[0]).date()
                if last_date >= week_start:
                    return 0
            except:
                pass
        await conn.execute("UPDATE users SET last_weekly_reward=? WHERE user_id=?", (utc_now_iso(), user_id))
        await conn.commit()
        return 50
    reward = await execute_db(_check)
    if reward > 0:
        data = await db_get_user_level(user_id)
        await db_update_user_level(user_id, data["points"] + reward, data["level"])
    return reward

async def db_get_publish_interval() -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='publish_interval'")
        row = await cur.fetchone()
        return int(row[0]) if row else DEFAULT_PUBLISH_INTERVAL_SECONDS
    return await execute_db(_get)

async def db_get_publish_interval_seconds() -> int:
    return await db_get_publish_interval()

async def db_set_publish_interval_seconds(seconds: int, admin_id: int, is_admin: bool = False):
    if not is_admin and admin_id != PRIMARY_OWNER_ID:
        return False
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(seconds),))
        await conn.commit()
    await execute_db(_set)
    return True

async def db_get_updates_channel():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='updates_channel'")
        row = await cur.fetchone()
        if row and row[0]:
            channel = row[0].strip()
            if channel.startswith("@"):
                channel = channel[1:]
            return channel if channel else None
        return None
    return await execute_db(_get)

async def db_set_updates_channel(channel: str):
    if not channel:
        return False
    channel = channel.strip()
    if channel.startswith("@"):
        channel = channel[1:]
    if not channel:
        return False
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('updates_channel', ?)", (channel,))
        await conn.commit()
    await execute_db(_set)
    return True

async def db_get_force_subscribe_status() -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='force_subscribe_enabled'")
        row = await cur.fetchone()
        return row and row[0] == "1"
    return await execute_db(_get)

async def db_set_force_subscribe_status(enabled: bool):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_subscribe_enabled', ?)", ("1" if enabled else "0",))
        await conn.commit()
    return await execute_db(_set)

async def db_get_force_subscribe_channel():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='force_subscribe_channel'")
        row = await cur.fetchone()
        return row[0] if row and row[0] else None
    return await execute_db(_get)

async def db_set_force_subscribe_channel(channel: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_subscribe_channel', ?)", (channel,))
        await conn.commit()
    return await execute_db(_set)

async def db_get_log_channel_id():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='log_channel_id'")
        row = await cur.fetchone()
        return row[0] if row and row[0] else None
    return await execute_db(_get)

async def db_set_log_channel_id(channel_id: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('log_channel_id', ?)", (channel_id,))
        await conn.commit()
    return await execute_db(_set)

async def db_get_auto_backup() -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='auto_backup'")
        row = await cur.fetchone()
        return row and row[0] == "1"
    return await execute_db(_get)

async def db_set_auto_backup(enabled: bool) -> None:
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('auto_backup', ?)", ("1" if enabled else "0",))
        await conn.commit()
    return await execute_db(_set)

async def db_get_last_backup_time():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='last_backup'")
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_get_allowed_sendcode_user() -> int | None:
    async def _get(conn):
        cur = await conn.execute("SELECT user_id FROM allowed_sendcode_user WHERE id=1")
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_set_allowed_sendcode_user(user_id: int) -> None:
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO allowed_sendcode_user (id, user_id) VALUES (1, ?)", (user_id,))
        await conn.commit()
    return await execute_db(_set)

async def db_create_contest(creator_id: int, title: str, description: str, prize: str, end_date: datetime, contest_type: str = "raffle") -> int:
    async def _create(conn):
        if not isinstance(end_date, datetime):
            raise ValueError("end_date must be datetime object")
        end_date_str = end_date.isoformat()
        created_at_str = utc_now_iso()
        cur = await conn.execute("INSERT INTO contests (creator_id, title, description, prize, end_date, status, created_at, contest_type) VALUES (?, ?, ?, ?, ?, 'active', ?, ?) RETURNING id", (creator_id, title, description, prize, end_date_str, created_at_str, contest_type))
        row = await cur.fetchone()
        await conn.commit()
        return row[0] if row else None
    return await execute_db(_create)

async def db_get_contest(contest_id: int) -> dict | None:
    async def _get(conn):
        cur = await conn.execute("SELECT id, title, description, prize, end_date, status, winner_id, creator_id, created_at, contest_type FROM contests WHERE id = ?", (contest_id,))
        row = await cur.fetchone()
        if row:
            return {
                "id": row[0], "title": row[1], "description": row[2],
                "prize": row[3], "end_date": row[4], "status": row[5],
                "winner_id": row[6], "creator_id": row[7], "created_at": row[8],
                "contest_type": row[9] if len(row) > 9 else "raffle"
            }
        return None
    return await execute_db(_get)

async def db_participate_in_contest(user_id: int, contest_id: int, answer: str = "") -> bool:
    async def _participate(conn):
        try:
            await conn.execute("INSERT INTO contest_participants (user_id, contest_id, answer, joined_at) VALUES (?, ?, ?, ?)", (user_id, contest_id, answer, utc_now_iso()))
            await conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    return await execute_db(_participate)

async def db_get_user_participation(user_id: int, contest_id: int) -> dict | None:
    async def _get(conn):
        cur = await conn.execute("SELECT id, answer, joined_at FROM contest_participants WHERE user_id = ? AND contest_id = ?", (user_id, contest_id))
        row = await cur.fetchone()
        if row:
            return {"id": row[0], "answer": row[1], "joined_at": row[2]}
        return None
    return await execute_db(_get)

async def db_set_contest_winner(contest_id: int, winner_id: int) -> bool:
    async def _set(conn):
        await conn.execute("UPDATE contests SET status = 'finished', winner_id = ? WHERE id = ?", (winner_id, contest_id))
        await conn.execute("INSERT INTO contest_winners (contest_id, winner_id, announced_at) VALUES (?, ?, ?)", (contest_id, winner_id, utc_now_iso()))
        await conn.commit()
        return True
    return await execute_db(_set)

async def db_get_contest_winners(limit: int = 10) -> list:
    async def _get(conn):
        cur = await conn.execute("SELECT c.id, c.title, c.prize, cw.winner_id, cw.announced_at FROM contest_winners cw JOIN contests c ON cw.contest_id = c.id ORDER BY cw.announced_at DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_random_participant(contest_id: int) -> int | None:
    async def _get(conn):
        cur = await conn.execute("SELECT user_id FROM contest_participants WHERE contest_id = ? ORDER BY RANDOM() LIMIT 1", (contest_id,))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_get_channel_stats(channel_db_id: int) -> dict:
    async def _get_stats(conn):
        cur = await conn.execute("SELECT COUNT(*) as total_posts, SUM(CASE WHEN published = 1 THEN 1 ELSE 0 END) as published_posts, SUM(CASE WHEN published = 0 THEN 1 ELSE 0 END) as unpublished_posts, SUM(views_count) as total_views, AVG(views_count) as avg_views, MAX(created_at) as last_post_time, MIN(created_at) as first_post_time FROM posts WHERE channel_db_id = ?", (channel_db_id,))
        row = await cur.fetchone()
        if not row or row[0] == 0:
            return {"total_posts": 0, "published_posts": 0, "unpublished_posts": 0, "total_views": 0, "avg_views": 0, "last_post_time": None, "first_post_time": None, "avg_time_between_posts": 0, "best_publish_hour": 0, "best_publish_day": 0, "published_today": 0, "published_this_week": 0, "published_this_month": 0, "most_viewed_post": None, "least_viewed_post": None}
        total_posts = row[0] or 0
        published_posts = row[1] or 0
        unpublished_posts = row[2] or 0
        total_views = row[3] or 0
        avg_views = row[4] or 0
        last_post_time = row[5]
        first_post_time = row[6]
        avg_time_between = 0
        if published_posts > 1 and last_post_time and first_post_time:
            try:
                last_dt = datetime.fromisoformat(last_post_time)
                first_dt = datetime.fromisoformat(first_post_time)
                time_diff = (last_dt - first_dt).total_seconds()
                avg_time_between = time_diff / (published_posts - 1) if published_posts > 1 else 0
            except:
                avg_time_between = 0
        best_hour = 0
        best_day = 0
        if published_posts > 0:
            cur = await conn.execute("SELECT strftime('%H', created_at) as hour, COUNT(*) as count FROM posts WHERE channel_db_id = ? AND published = 1 GROUP BY hour ORDER BY count DESC LIMIT 1", (channel_db_id,))
            hour_row = await cur.fetchone()
            if hour_row:
                best_hour = int(hour_row[0])
            cur = await conn.execute("SELECT strftime('%w', created_at) as day, COUNT(*) as count FROM posts WHERE channel_db_id = ? AND published = 1 GROUP BY day ORDER BY count DESC LIMIT 1", (channel_db_id,))
            day_row = await cur.fetchone()
            if day_row:
                best_day = int(day_row[0])
        today = utc_now().date().isoformat()
        week_start = (utc_now() - timedelta(days=7)).isoformat()
        month_start = (utc_now() - timedelta(days=30)).isoformat()
        cur = await conn.execute("SELECT SUM(CASE WHEN date(created_at) = ? THEN 1 ELSE 0 END) as today_count, SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as week_count, SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as month_count FROM posts WHERE channel_db_id = ? AND published = 1", (today, week_start, month_start, channel_db_id))
        extra_row = await cur.fetchone()
        published_today = extra_row[0] or 0 if extra_row else 0
        published_this_week = extra_row[1] or 0 if extra_row else 0
        published_this_month = extra_row[2] or 0 if extra_row else 0
        most_viewed = None
        least_viewed = None
        cur = await conn.execute("SELECT id, text, views_count FROM posts WHERE channel_db_id = ? AND published = 1 ORDER BY views_count DESC LIMIT 1", (channel_db_id,))
        most_row = await cur.fetchone()
        if most_row:
            most_viewed = {"id": most_row[0], "text": most_row[1][:50] + "..." if most_row[1] and len(most_row[1]) > 50 else most_row[1], "views": most_row[2]}
        cur = await conn.execute("SELECT id, text, views_count FROM posts WHERE channel_db_id = ? AND published = 1 AND views_count > 0 ORDER BY views_count ASC LIMIT 1", (channel_db_id,))
        least_row = await cur.fetchone()
        if least_row:
            least_viewed = {"id": least_row[0], "text": least_row[1][:50] + "..." if least_row[1] and len(least_row[1]) > 50 else least_row[1], "views": least_row[2]}
        return {"total_posts": total_posts, "published_posts": published_posts, "unpublished_posts": unpublished_posts, "total_views": total_views, "avg_views": round(avg_views, 2) if avg_views else 0, "last_post_time": last_post_time, "first_post_time": first_post_time, "avg_time_between_posts": round(avg_time_between / 3600, 2) if avg_time_between else 0, "best_publish_hour": best_hour, "best_publish_day": best_day, "published_today": published_today, "published_this_week": published_this_week, "published_this_month": published_this_month, "most_viewed_post": most_viewed, "least_viewed_post": least_viewed}
    return await execute_db(_get_stats)

async def db_get_channel_stats_summary(user_id: int) -> dict:
    async def _get_summary(conn):
        channels = await db_get_channels(user_id)
        if not channels:
            return None
        total_posts = 0
        total_published = 0
        total_views = 0
        total_channels = len(channels)
        best_channel = None
        best_channel_views = 0
        active_channels = 0
        for ch_db_id, ch_tele_id, ch_name, banned in channels:
            if not banned:
                active_channels += 1
            stats = await db_get_channel_stats(ch_db_id)
            if stats and stats["total_posts"] > 0:
                total_posts += stats["total_posts"]
                total_published += stats["published_posts"]
                total_views += stats["total_views"]
                if stats["total_views"] > best_channel_views:
                    best_channel_views = stats["total_views"]
                    best_channel = {"name": ch_name, "views": stats["total_views"], "posts": stats["published_posts"], "avg_views": stats["avg_views"]}
        return {"total_channels": total_channels, "active_channels": active_channels, "total_posts": total_posts, "total_published": total_published, "total_views": total_views, "avg_views_per_channel": round(total_views / total_channels, 2) if total_channels > 0 else 0, "best_channel": best_channel}
    return await execute_db(_get_summary)

async def db_get_channel_growth(channel_db_id: int, days: int = 30) -> dict:
    async def _get_growth(conn):
        start_date = (utc_now() - timedelta(days=days)).isoformat()
        cur = await conn.execute("SELECT date(created_at) as post_date, COUNT(*) as count, SUM(views_count) as views FROM posts WHERE channel_db_id = ? AND created_at >= ? GROUP BY date(created_at) ORDER BY post_date", (channel_db_id, start_date))
        rows = await cur.fetchall()
        dates = []
        counts = []
        views = []
        for row in rows:
            dates.append(row[0])
            counts.append(row[1] or 0)
            views.append(row[2] or 0)
        return {"dates": dates, "counts": counts, "views": views, "total_days": len(dates), "total_posts": sum(counts), "total_views": sum(views)}
    return await execute_db(_get_growth)

async def init_db():
    async with aiosqlite.connect(str(DB_PATH), timeout=DB_TIMEOUT) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA cache_size=-64000")
        await conn.execute("PRAGMA temp_store=MEMORY")
        await conn.execute("PRAGMA wal_autocheckpoint=1000")
        await conn.execute("PRAGMA optimize")
        await conn.execute("PRAGMA max_page_count=1000000")
        await conn.execute("PRAGMA secure_delete=ON")
        await conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, auto_publish INTEGER DEFAULT 1, banned INTEGER DEFAULT 0, trial_used INTEGER DEFAULT 0, subscription_end TEXT DEFAULT NULL, referral_code TEXT DEFAULT NULL, referred_by INTEGER DEFAULT NULL, active_channel INTEGER DEFAULT NULL, auto_reply_enabled INTEGER DEFAULT 1, auto_recycle INTEGER DEFAULT 1, last_daily_reward TEXT DEFAULT NULL, last_weekly_reward TEXT DEFAULT NULL, achievements TEXT DEFAULT '[]')")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, channel_id TEXT, channel_name TEXT, created_at TIMESTAMP, banned INTEGER DEFAULT 0, FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE)")
        await conn.execute("CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_db_id INTEGER, text TEXT, media_type TEXT DEFAULT 'text', media_file_id TEXT, published INTEGER DEFAULT 0, fail_count INTEGER DEFAULT 0, views_count INTEGER DEFAULT 0, last_view_time TIMESTAMP, created_at TIMESTAMP, FOREIGN KEY(channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE)")
        await conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS group_replies (keyword TEXT PRIMARY KEY, reply TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS group_security (chat_id INTEGER PRIMARY KEY, delete_links INTEGER DEFAULT 0, delete_mentions INTEGER DEFAULT 0, warn_message INTEGER DEFAULT 1, slow_mode INTEGER DEFAULT 0, slow_mode_seconds INTEGER DEFAULT 5, welcome_enabled INTEGER DEFAULT 0, welcome_text TEXT DEFAULT 'مرحباً {user} في {chat} 🤍', goodbye_enabled INTEGER DEFAULT 0, goodbye_text TEXT DEFAULT 'وداعاً {user} 👋', delete_banned_words INTEGER DEFAULT 0, auto_penalty TEXT DEFAULT 'none', auto_mute_duration INTEGER DEFAULT 60)")
        await conn.execute("CREATE TABLE IF NOT EXISTS group_settings (chat_id INTEGER PRIMARY KEY, anti_links INTEGER DEFAULT 0, anti_badwords INTEGER DEFAULT 0, welcome_msg INTEGER DEFAULT 1, mute_all INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS bot_admins (user_id INTEGER PRIMARY KEY)")
        await conn.execute("CREATE TABLE IF NOT EXISTS bot_groups (chat_id INTEGER PRIMARY KEY, chat_name TEXT, username TEXT, added_by INTEGER, added_at TIMESTAMP, banned INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS bot_channels (channel_id INTEGER PRIMARY KEY, channel_name TEXT, added_by INTEGER, added_at TIMESTAMP, banned INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_messages (user_id INTEGER, chat_id INTEGER, message_time TIMESTAMP, PRIMARY KEY (user_id, chat_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS users_cache (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_updated TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_warnings (user_id INTEGER, chat_id INTEGER, warnings INTEGER DEFAULT 0, PRIMARY KEY(user_id, chat_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS banned_words (id INTEGER PRIMARY KEY AUTOINCREMENT, word TEXT, chat_id INTEGER, added_by INTEGER, added_at TIMESTAMP, UNIQUE(word, chat_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS hidden_owner_groups (chat_id INTEGER PRIMARY KEY, owner_id INTEGER, is_hidden INTEGER DEFAULT 1)")
        await conn.execute("CREATE TABLE IF NOT EXISTS hidden_admins (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, admin_id INTEGER NOT NULL, added_by INTEGER, added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(chat_id, admin_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_groups_link (user_id INTEGER, chat_id INTEGER, PRIMARY KEY(user_id, chat_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_levels (user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0, level INTEGER DEFAULT 1)")
        await conn.execute("CREATE TABLE IF NOT EXISTS support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, message TEXT, ticket_number INTEGER, status TEXT DEFAULT 'pending', created_at TIMESTAMP, replied INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS chat_locks (chat_id INTEGER PRIMARY KEY, locked INTEGER DEFAULT 0, locked_at TIMESTAMP, locked_by INTEGER)")
        await conn.execute("CREATE TABLE IF NOT EXISTS schedule (channel_db_id INTEGER PRIMARY KEY, schedule_type TEXT DEFAULT 'interval_minutes', interval_minutes INTEGER DEFAULT 12, interval_hours INTEGER DEFAULT 0, interval_days INTEGER DEFAULT 0, days_of_week TEXT DEFAULT '', specific_dates TEXT DEFAULT '', publish_time TEXT DEFAULT '00:00', cron_expression TEXT DEFAULT NULL, next_publish_date TEXT, FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE)")
        await conn.execute("CREATE TABLE IF NOT EXISTS last_publish (channel_db_id INTEGER PRIMARY KEY, last_publish_time TIMESTAMP, FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE)")
        await conn.execute("CREATE TABLE IF NOT EXISTS scheduled_posts (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, text TEXT NOT NULL, publish_time TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, fail_count INTEGER DEFAULT 0)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_time ON scheduled_posts(publish_time)")
        await conn.execute("CREATE TABLE IF NOT EXISTS allowed_sendcode_user (id INTEGER PRIMARY KEY CHECK (id=1), user_id INTEGER)")
        await conn.execute("CREATE TABLE IF NOT EXISTS referrals (id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER NOT NULL, referred_id INTEGER NOT NULL, referred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_rewarded INTEGER DEFAULT 0, UNIQUE(referred_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS referral_rewards (user_id INTEGER PRIMARY KEY, referral_count INTEGER DEFAULT 0, total_reward_days INTEGER DEFAULT 0, claimed_reward_days INTEGER DEFAULT 0)")
        await conn.execute("CREATE TABLE IF NOT EXISTS referral_settings (key TEXT PRIMARY KEY, value TEXT)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_reminder_settings (user_id INTEGER PRIMARY KEY, subscription_reminder INTEGER DEFAULT 1, daily_stats_reminder INTEGER DEFAULT 0, weekly_report INTEGER DEFAULT 1, reminder_days_before INTEGER DEFAULT 3, last_reminder_sent INTEGER DEFAULT 0, notification_lang TEXT DEFAULT 'ar')")
        await conn.execute("CREATE TABLE IF NOT EXISTS moderation_log (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER, user_id INTEGER, action TEXT, duration_minutes INTEGER, moderator_id INTEGER, reason TEXT, created_at TIMESTAMP)")
        await conn.execute("CREATE TABLE IF NOT EXISTS user_translation (user_id INTEGER PRIMARY KEY, lang TEXT DEFAULT 'off')")
        await conn.execute("CREATE TABLE IF NOT EXISTS channel_stats (id INTEGER PRIMARY KEY AUTOINCREMENT, channel_db_id INTEGER NOT NULL, total_posts INTEGER DEFAULT 0, published_posts INTEGER DEFAULT 0, unpublished_posts INTEGER DEFAULT 0, total_views INTEGER DEFAULT 0, avg_views_per_post REAL DEFAULT 0, last_post_time TIMESTAMP, avg_time_between_posts REAL DEFAULT 0, best_publish_hour INTEGER DEFAULT 0, best_publish_day INTEGER DEFAULT 0, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE, UNIQUE(channel_db_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS web_sessions (session_id TEXT PRIMARY KEY, user_data TEXT, expires INTEGER)")
        await conn.execute("CREATE TABLE IF NOT EXISTS contests (id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER, title TEXT, description TEXT, prize TEXT, end_date TEXT, status TEXT DEFAULT 'active', winner_id INTEGER, created_at TIMESTAMP, contest_type TEXT DEFAULT 'raffle')")
        await conn.execute("CREATE TABLE IF NOT EXISTS contest_participants (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, contest_id INTEGER, answer TEXT, joined_at TIMESTAMP, UNIQUE(user_id, contest_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS contest_winners (id INTEGER PRIMARY KEY AUTOINCREMENT, contest_id INTEGER, winner_id INTEGER, announced_at TIMESTAMP)")
        await conn.execute("CREATE TABLE IF NOT EXISTS auto_reply_settings (chat_id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 1, only_admins INTEGER DEFAULT 0, ignore_bots INTEGER DEFAULT 1, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_channel_published ON posts(channel_db_id, published)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_next ON schedule(next_publish_date)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_channels_user ON user_channels(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_banned_words_chat ON banned_words(chat_id, word)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_messages_time ON user_messages(message_time)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_channel_fail ON posts(channel_db_id, published, fail_count)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_subscription ON users(subscription_end)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_levels_points ON user_levels(points DESC)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_moderation_chat ON moderation_log(chat_id, created_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_channel_stats ON channel_stats(channel_db_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_views ON posts(views_count)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_published_views ON posts(published, views_count)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_contests_active ON contests(status, end_date)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_hidden_admins_chat ON hidden_admins(chat_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_cron ON schedule(cron_expression)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_last_daily ON users(last_daily_reward)")
        try:
            cursor = await conn.execute("PRAGMA table_info(group_security)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if "auto_penalty" not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN auto_penalty TEXT DEFAULT 'none'")
            if "auto_mute_duration" not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN auto_mute_duration INTEGER DEFAULT 60")
        except:
            pass
        try:
            cursor = await conn.execute("PRAGMA table_info(users)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if "active_channel" not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN active_channel INTEGER DEFAULT NULL")
            if "referral_code" not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN referral_code TEXT DEFAULT NULL")
            if "auto_reply_enabled" not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN auto_reply_enabled INTEGER DEFAULT 1")
            if "auto_recycle" not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN auto_recycle INTEGER DEFAULT 1")
            if "last_daily_reward" not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN last_daily_reward TEXT DEFAULT NULL")
            if "last_weekly_reward" not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN last_weekly_reward TEXT DEFAULT NULL")
            if "achievements" not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN achievements TEXT DEFAULT '[]'")
        except:
            pass
        try:
            cursor = await conn.execute("PRAGMA table_info(posts)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if "views_count" not in column_names:
                await conn.execute("ALTER TABLE posts ADD COLUMN views_count INTEGER DEFAULT 0")
            if "last_view_time" not in column_names:
                await conn.execute("ALTER TABLE posts ADD COLUMN last_view_time TIMESTAMP")
        except:
            pass
        try:
            cursor = await conn.execute("PRAGMA table_info(contests)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if "contest_type" not in column_names:
                await conn.execute("ALTER TABLE contests ADD COLUMN contest_type TEXT DEFAULT 'raffle'")
        except:
            pass
        try:
            cursor = await conn.execute("PRAGMA table_info(schedule)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if "cron_expression" not in column_names:
                await conn.execute("ALTER TABLE schedule ADD COLUMN cron_expression TEXT DEFAULT NULL")
        except:
            pass
        await conn.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (PRIMARY_OWNER_ID,))
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(DEFAULT_PUBLISH_INTERVAL_SECONDS),))
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('updates_channel', '')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('force_subscribe_enabled', '0')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('force_subscribe_channel', '')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_backup', '1')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_backup', '')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_ticket_number', '0')")
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('log_channel_id', '')")
        await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('reward_days_per_referral', '3')")
        await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('referral_bonus_points', '50')")
        await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('max_referrals_per_day', '5')")
        await conn.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('welcome_bonus_points', '10')")
        await conn.commit()
    await db_pool.initialize()
