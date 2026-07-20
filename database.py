#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
دوال قاعدة البيانات - كاملة
"""

import sqlite3
import json
import asyncio
import hashlib
import time as time_module
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Callable, Tuple
from pathlib import Path

import aiosqlite

from constants import (
    DB_PATH, DB_TIMEOUT, MAX_CONNECTIONS, LEVEL_REQUIREMENTS,
    PRIMARY_OWNER_ID, DEFAULT_PUBLISH_INTERVAL_SECONDS,
    user_language
)
from utils import (
    utc_now, utc_now_iso, safe_int, mecca_now, mecca_now_iso,
    to_naive, utc_to_mecca, sanitize_text, parse_days_of_week_safe,
    parse_dates_safe, log_error
)

# ===================== Pool اتصالات قاعدة البيانات =====================
class DatabasePool:
    def __init__(self, max_connections: int = 10):
        self._pool = None
        self._max_connections = max_connections
        self._lock = asyncio.Lock()

    async def initialize(self):
        async with self._lock:
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

    async def execute(self, query: str, params: tuple = None):
        conn = await self.get_connection()
        async with conn.execute(query, params or ()) as cursor:
            return await cursor.fetchall()

    async def execute_many(self, queries: List[tuple]):
        conn = await self.get_connection()
        async with conn:
            for query, params in queries:
                await conn.execute(query, params)
            await conn.commit()

    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None

db_pool = DatabasePool(max_connections=MAX_CONNECTIONS)

async def execute_db(func: Callable):
    conn = await db_pool.get_connection()
    try:
        return await func(conn)
    except Exception as e:
        raise
    finally:
        pass

async def execute_transaction(queries: List[Tuple[str, tuple]]) -> Any:
    conn = await db_pool.get_connection()
    try:
        async with conn:
            results = []
            for query, params in queries:
                cur = await conn.execute(query, params)
                if query.strip().upper().startswith('SELECT'):
                    results.append(await cur.fetchall())
            await conn.commit()
            return results if len(results) > 1 else (results[0] if results else None)
    except Exception as e:
        await conn.rollback()
        raise

# ===================== دوال المستخدمين =====================
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
        await conn.execute("INSERT OR REPLACE INTO users_cache (user_id, username, first_name, last_updated) VALUES (?, ?, ?, ?)",
                          (user_id, username or "", first_name or "", utc_now_iso()))
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
        current_end = None
        if row and row[0]:
            try:
                current_end = datetime.fromisoformat(row[0])
            except:
                current_end = None
        if current_end and current_end > utc_now():
            new_end = current_end + timedelta(days=days)
        else:
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

# ===================== دوال القنوات =====================
async def db_add_channel(user_id: int, channel_id: str, channel_name: str) -> int:
    async def _add(conn):
        cur = await conn.execute("SELECT id FROM user_channels WHERE user_id=? AND channel_id=?", (user_id, channel_id))
        if await cur.fetchone():
            return None
        cur = await conn.execute("INSERT INTO user_channels (user_id, channel_id, channel_name, created_at) VALUES (?, ?, ?, ?) RETURNING id",
                                (user_id, channel_id, channel_name, utc_now_iso()))
        row = await cur.fetchone()
        await conn.commit()
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
                        ch_id = row[0] if row[0] is not None else 0
                        ch_tele_id = row[1] if row[1] is not None else "unknown"
                        ch_name = row[2] if row[2] is not None else ch_tele_id
                        banned = row[3] if row[3] is not None else 0
                        safe_rows.append((ch_id, ch_tele_id, ch_name, banned))
                except:
                    continue
            return safe_rows
        except Exception as e:
            return []
    return await execute_db(_get)

async def db_get_channel_info(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT channel_id, channel_name FROM user_channels WHERE id=?", (channel_db_id,))
        row = await cur.fetchone()
        if row:
            return {'channel_id': row[0], 'channel_name': row[1]}
        return {'channel_id': None, 'channel_name': None}
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
        await conn.execute("INSERT INTO bot_channels (channel_id, channel_name, added_by, added_at) VALUES (?, ?, ?, ?)",
                          (channel_id, channel_name, added_by, utc_now_iso()))
        await conn.commit()
        return True
    return await execute_db(_register)

async def db_get_all_bot_channels(only_banned: bool = False, limit: int = 500):
    async def _get(conn):
        if only_banned:
            cur = await conn.execute("SELECT channel_id, channel_name, added_by, added_at, banned FROM bot_channels WHERE banned=1 ORDER BY added_at DESC LIMIT ?", (limit,))
        else:
            cur = await conn.execute("SELECT channel_id, channel_name, added_by, added_at, banned FROM bot_channels ORDER BY added_at DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

# ===================== دوال المنشورات =====================
async def db_save_posts(channel_db_id: int, posts: list) -> int:
    async def _save(conn):
        values = []
        for text_content, media_type, media_file_id in posts:
            values.append((channel_db_id, sanitize_text(text_content), media_type, media_file_id, utc_now_iso()))
        await conn.executemany(
            "INSERT INTO posts (channel_db_id, text, media_type, media_file_id, created_at) VALUES (?, ?, ?, ?, ?)",
            values
        )
        await conn.commit()
        return len(values)
    return await execute_db(_save)

async def db_get_next_post(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT id, text, media_type, media_file_id FROM posts WHERE channel_db_id=? AND published=0 AND (fail_count IS NULL OR fail_count < 3) ORDER BY id LIMIT 1", (channel_db_id,))
        row = await cur.fetchone()
        if row:
            return {'id': row[0], 'text': row[1], 'media_type': row[2], 'media_file_id': row[3]}
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

async def db_should_auto_recycle(channel_db_id: int) -> bool:
    total = await db_get_posts_count(channel_db_id)
    published = await db_get_published_count(channel_db_id)
    return total > 0 and published >= total

async def db_reset_posts_to_unpublished(channel_db_id: int, user_id: int = None):
    async def _reset(conn):
        await conn.execute("UPDATE posts SET published=0, fail_count=0 WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
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
            await conn.execute(
                "UPDATE posts SET views_count = ?, last_view_time = ? WHERE id = ?",
                (views_count, utc_now_iso(), post_id)
            )
        else:
            await conn.execute(
                "UPDATE posts SET views_count = views_count + 1, last_view_time = ? WHERE id = ?",
                (utc_now_iso(), post_id)
            )
        await conn.commit()
    await execute_db(_update_views)

# ===================== دوال المجموعات =====================
async def db_register_group(chat_id: int, chat_name: str, added_by: int, username: str = None) -> bool:
    async def _register(conn):
        cur = await conn.execute("SELECT chat_id FROM bot_groups WHERE chat_id=?", (chat_id,))
        if await cur.fetchone():
            await conn.execute("UPDATE bot_groups SET chat_name=?, username=?, added_by=? WHERE chat_id=?", (chat_name, username, added_by, chat_id))
            await conn.commit()
            return False
        await conn.execute("INSERT INTO bot_groups (chat_id, chat_name, username, added_by, added_at) VALUES (?, ?, ?, ?, ?)",
                          (chat_id, chat_name, username, added_by, utc_now_iso()))
        await conn.execute("INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?, ?)", (added_by, chat_id))
        await conn.execute("INSERT OR IGNORE INTO group_admins (chat_id, user_id) VALUES (?, ?)", (chat_id, added_by))
        await conn.commit()
        return True
    return await execute_db(_register)

async def db_get_user_groups(user_id: int):
    async def _get(conn):
        try:
            query = """
                SELECT DISTINCT bg.chat_id, bg.chat_name, bg.username, bg.banned
                FROM bot_groups bg
                LEFT JOIN hidden_owner_groups hog ON bg.chat_id = hog.chat_id AND hog.owner_id = ?
                LEFT JOIN group_admins ga ON bg.chat_id = ga.chat_id AND ga.user_id = ?
                LEFT JOIN user_groups_link ugl ON bg.chat_id = ugl.chat_id AND ugl.user_id = ?
                WHERE (hog.owner_id IS NOT NULL)
                   OR (ga.user_id IS NOT NULL)
                   OR (ugl.user_id IS NOT NULL)
                ORDER BY bg.chat_name
            """
            cur = await conn.execute(query, (user_id, user_id, user_id))
            rows = await cur.fetchall()
            hidden_admin_query = "SELECT chat_id FROM hidden_admins WHERE admin_id = ?"
            hidden_admin_cur = await conn.execute(hidden_admin_query, (user_id,))
            hidden_admin_chats = {row[0] for row in await hidden_admin_cur.fetchall()}
            visible_groups = []
            for row in rows:
                chat_id = row[0]
                if chat_id in hidden_admin_chats:
                    continue
                visible_groups.append(row)
            return visible_groups
        except Exception as e:
            return []
    return await execute_db(_get)

async def db_get_user_groups_count(user_id: int) -> int:
    async def _get(conn):
        try:
            groups = await db_get_user_groups(user_id)
            return len(groups)
        except:
            return 0
    return await execute_db(_get)

async def db_get_all_groups(only_banned: bool = False, limit: int = 500):
    async def _get(conn):
        if only_banned:
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups WHERE banned=1 ORDER BY added_at DESC LIMIT ?", (limit,))
        else:
            cur = await conn.execute("SELECT chat_id, chat_name, username, added_by, added_at, banned FROM bot_groups ORDER BY added_at DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

# ===================== دوال الأمان =====================
async def ensure_security_columns(conn):
    cur = await conn.execute("PRAGMA table_info(group_security)")
    columns = [row[1] for row in await cur.fetchall()]
    if 'delete_stickers' not in columns:
        await conn.execute("ALTER TABLE group_security ADD COLUMN delete_stickers INTEGER DEFAULT 0")
    if 'delete_videos' not in columns:
        await conn.execute("ALTER TABLE group_security ADD COLUMN delete_videos INTEGER DEFAULT 0")
    if 'delete_service_messages' not in columns:
        await conn.execute("ALTER TABLE group_security ADD COLUMN delete_service_messages INTEGER DEFAULT 0")
    await conn.commit()

async def db_get_security_settings(chat_id: int):
    default_settings = {
        'links': False, 'mentions': False, 'warn': True, 'slow_mode': False,
        'slow_mode_seconds': 5, 'welcome_enabled': False,
        'welcome_text': "مرحباً {user} في {chat} 🤍",
        'goodbye_enabled': False, 'goodbye_text': "وداعاً {user} 👋",
        'delete_banned_words': False, 'auto_penalty': 'none', 'auto_mute_duration': 60,
        'delete_stickers': False, 'delete_videos': False,
        'delete_service_messages': False
    }
    try:
        async def _get(conn):
            await ensure_security_columns(conn)
            cur = await conn.execute(
                """SELECT delete_links, delete_mentions, warn_message, slow_mode,
                          slow_mode_seconds, welcome_enabled, welcome_text,
                          goodbye_enabled, goodbye_text, delete_banned_words,
                          auto_penalty, auto_mute_duration,
                          delete_stickers, delete_videos,
                          delete_service_messages
                   FROM group_security WHERE chat_id=?""",
                (chat_id,)
            )
            row = await cur.fetchone()
            if row:
                settings = {
                    'links': row[0] == 1,
                    'mentions': row[1] == 1,
                    'warn': row[2] == 1,
                    'slow_mode': row[3] == 1,
                    'slow_mode_seconds': row[4] if row[4] is not None else 5,
                    'welcome_enabled': row[5] == 1,
                    'welcome_text': row[6] if row[6] else default_settings['welcome_text'],
                    'goodbye_enabled': row[7] == 1,
                    'goodbye_text': row[8] if row[8] else default_settings['goodbye_text'],
                    'delete_banned_words': row[9] == 1,
                    'auto_penalty': row[10] if row[10] else 'none',
                    'auto_mute_duration': row[11] if row[11] is not None else 60,
                    'delete_stickers': row[12] == 1 if len(row) > 12 else False,
                    'delete_videos': row[13] == 1 if len(row) > 13 else False,
                    'delete_service_messages': row[14] == 1 if len(row) > 14 else False
                }
                return settings
            await conn.execute(
                """INSERT INTO group_security
                   (chat_id, delete_links, delete_mentions, warn_message, slow_mode,
                    slow_mode_seconds, welcome_enabled, welcome_text, goodbye_enabled,
                    goodbye_text, delete_banned_words, auto_penalty, auto_mute_duration,
                    delete_stickers, delete_videos, delete_service_messages)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (chat_id, 0, 0, 1, 0, 5, default_settings['welcome_text'],
                 0, default_settings['goodbye_text'], 0, 'none', 60, 0, 0, 0)
            )
            await conn.commit()
            return default_settings
        return await execute_db(_get)
    except Exception as e:
        return default_settings

async def db_set_security_settings(chat_id: int, **kwargs):
    async def _set(conn):
        await ensure_security_columns(conn)
        cur = await conn.execute("SELECT 1 FROM group_security WHERE chat_id=?", (chat_id,))
        exists = await cur.fetchone()
        if exists:
            updates = []
            values = []
            for key, value in kwargs.items():
                if key == 'links':
                    updates.append("delete_links=?")
                    values.append(1 if value else 0)
                elif key == 'mentions':
                    updates.append("delete_mentions=?")
                    values.append(1 if value else 0)
                elif key == 'warn':
                    updates.append("warn_message=?")
                    values.append(1 if value else 0)
                elif key == 'slow_mode':
                    updates.append("slow_mode=?")
                    values.append(1 if value else 0)
                elif key == 'slow_mode_seconds':
                    updates.append("slow_mode_seconds=?")
                    values.append(value)
                elif key == 'welcome_enabled':
                    updates.append("welcome_enabled=?")
                    values.append(1 if value else 0)
                elif key == 'welcome_text':
                    updates.append("welcome_text=?")
                    values.append(value)
                elif key == 'goodbye_enabled':
                    updates.append("goodbye_enabled=?")
                    values.append(1 if value else 0)
                elif key == 'goodbye_text':
                    updates.append("goodbye_text=?")
                    values.append(value)
                elif key == 'delete_banned_words':
                    updates.append("delete_banned_words=?")
                    values.append(1 if value else 0)
                elif key == 'auto_penalty':
                    updates.append("auto_penalty=?")
                    values.append(value)
                elif key == 'auto_mute_duration':
                    updates.append("auto_mute_duration=?")
                    values.append(value)
                elif key == 'delete_stickers':
                    updates.append("delete_stickers=?")
                    values.append(1 if value else 0)
                elif key == 'delete_videos':
                    updates.append("delete_videos=?")
                    values.append(1 if value else 0)
                elif key == 'delete_service_messages':
                    updates.append("delete_service_messages=?")
                    values.append(1 if value else 0)
            if updates:
                query = f"UPDATE group_security SET {', '.join(updates)} WHERE chat_id=?"
                values.append(chat_id)
                await conn.execute(query, values)
        else:
            await conn.execute(
                """INSERT INTO group_security
                   (chat_id, delete_links, delete_mentions, warn_message, slow_mode,
                    slow_mode_seconds, welcome_enabled, welcome_text, goodbye_enabled,
                    goodbye_text, delete_banned_words, auto_penalty, auto_mute_duration,
                    delete_stickers, delete_videos, delete_service_messages)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (chat_id,
                 1 if kwargs.get('links', False) else 0,
                 1 if kwargs.get('mentions', False) else 0,
                 1 if kwargs.get('warn', True) else 0,
                 1 if kwargs.get('slow_mode', False) else 0,
                 kwargs.get('slow_mode_seconds', 5),
                 1 if kwargs.get('welcome_enabled', False) else 0,
                 kwargs.get('welcome_text', "مرحباً {user} في {chat} 🤍"),
                 1 if kwargs.get('goodbye_enabled', False) else 0,
                 kwargs.get('goodbye_text', "وداعاً {user} 👋"),
                 1 if kwargs.get('delete_banned_words', False) else 0,
                 kwargs.get('auto_penalty', 'none'),
                 kwargs.get('auto_mute_duration', 60),
                 1 if kwargs.get('delete_stickers', False) else 0,
                 1 if kwargs.get('delete_videos', False) else 0,
                 1 if kwargs.get('delete_service_messages', False) else 0)
            )
        await conn.commit()
    return await execute_db(_set)

async def db_check_slow_mode(chat_id: int, user_id: int) -> bool:
    settings = await db_get_security_settings(chat_id)
    if not settings['slow_mode']:
        return True
    seconds = settings.get('slow_mode_seconds', 5)
    async def _check(conn):
        cur = await conn.execute("SELECT message_time FROM user_messages WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        row = await cur.fetchone()
        now = utc_now()
        if row:
            try:
                last_time = datetime.fromisoformat(row[0])
                if (now - last_time).total_seconds() < seconds:
                    return False
            except:
                pass
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

# ===================== دوال المالك والمشرفين المخفيين =====================
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
        except:
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
        return [{'admin_id': row[0], 'added_by': row[1], 'added_at': row[2]} for row in rows]
    return await execute_db(_get)

async def db_should_hide_group_from_user(chat_id: int, user_id: int) -> bool:
    async def _check(conn):
        if await db_is_hidden_owner(chat_id, user_id):
            return False
        if await db_is_hidden_admin(chat_id, user_id):
            return True
        return False
    return await execute_db(_check)

# ===================== دوال المشرفين =====================
async def db_sync_group_admins(chat_id: int, bot, owner_id: int = None) -> int:
    try:
        admins = await bot.get_chat_administrators(chat_id)
        admin_ids = [admin.user.id for admin in admins]
        if owner_id and owner_id not in admin_ids:
            admin_ids.append(owner_id)
        async def _update(conn):
            await conn.execute("DELETE FROM group_admins WHERE chat_id=?", (chat_id,))
            if admin_ids:
                values = [(chat_id, uid) for uid in admin_ids]
                await conn.executemany("INSERT INTO group_admins (chat_id, user_id) VALUES (?, ?)", values)
                await conn.commit()
            return len(admin_ids)
        return await execute_db(_update)
    except Exception as e:
        return 0

async def db_is_real_admin(chat_id: int, user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM group_admins WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        return await cur.fetchone() is not None
    return await execute_db(_check)

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

# ===================== دوال الجدولة =====================
async def db_save_schedule(channel_db_id: int, schedule_type: str, interval_minutes: int = None, interval_hours: int = None, interval_days: int = None, days_of_week: str = None, specific_dates: str = None, publish_time: str = None, cron_expression: str = None):
    async def _save(conn):
        await conn.execute("""
            INSERT OR REPLACE INTO schedule (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, cron_expression, next_publish_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """, (channel_db_id, schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time or "00:00", cron_expression))
        await conn.commit()
    return await execute_db(_save)

async def db_get_schedule(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT schedule_type, interval_minutes, interval_hours, interval_days, days_of_week, specific_dates, publish_time, cron_expression, next_publish_date FROM schedule WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        if row:
            return {
                'type': row[0] or 'interval_minutes',
                'interval_minutes': row[1] or 12,
                'interval_hours': row[2] or 0,
                'interval_days': row[3] or 0,
                'days_of_week': row[4] or '[]',
                'specific_dates': row[5] or '[]',
                'publish_time': row[6] or '00:00',
                'cron_expression': row[7],
                'next_publish_date': row[8]
            }
        return {'type': 'interval_minutes', 'interval_minutes': 12, 'interval_hours': 0, 'interval_days': 0, 'days_of_week': '[]', 'specific_dates': '[]', 'publish_time': '00:00', 'cron_expression': None, 'next_publish_date': None}
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
        if last_row:
            try:
                last_time = datetime.fromisoformat(last_row[0])
            except:
                last_time = utc_now()
        else:
            last_time = utc_now()
        schedule_type = schedule['type']
        publish_time_str = schedule.get('publish_time', '00:00')
        if ':' not in publish_time_str:
            publish_time_str = '00:00'
        try:
            hour, minute = map(int, publish_time_str.split(':'))
        except:
            hour, minute = 0, 0
        next_date = None
        if schedule_type == 'interval_minutes':
            minutes = schedule.get('interval_minutes', 12)
            next_date = last_time + timedelta(minutes=minutes)
        elif schedule_type == 'interval_hours':
            hours = schedule.get('interval_hours', 1)
            next_date = last_time + timedelta(hours=hours)
        elif schedule_type == 'interval_days':
            days = schedule.get('interval_days', 1)
            next_date = last_time + timedelta(days=days)
        elif schedule_type == 'days':
            days_of_week = parse_days_of_week_safe(schedule.get('days_of_week', '[]'))
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
        elif schedule_type == 'dates':
            specific_dates = parse_dates_safe(schedule.get('specific_dates', '[]'))
            if specific_dates:
                target_date = last_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                for date_str in sorted(specific_dates):
                    try:
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d').replace(hour=hour, minute=minute, second=0, microsecond=0)
                        if date_obj > last_time:
                            next_date = date_obj
                            break
                    except:
                        continue
                if not next_date:
                    try:
                        next_date = datetime.strptime(specific_dates[0], '%Y-%m-%d').replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=365)
                    except:
                        next_date = utc_now() + timedelta(days=1)
            else:
                next_date = utc_now() + timedelta(days=1)
        elif schedule_type == 'cron':
            cron_expr = schedule.get('cron_expression', '0 0 * * *')
            try:
                import croniter
                base = last_time
                cron = croniter.croniter(cron_expr, base)
                next_date = cron.get_next(datetime)
            except:
                next_date = utc_now() + timedelta(days=1)
        else:
            next_date = utc_now() + timedelta(minutes=schedule.get('interval_minutes', 12))
        if next_date:
            await conn.execute("UPDATE schedule SET next_publish_date=? WHERE channel_db_id=?", (next_date.isoformat(), channel_db_id))
            await conn.commit()
    return await execute_db(_update)

async def db_set_publish_time(channel_db_id: int, time_str: str):
    async def _set(conn):
        await conn.execute("UPDATE schedule SET publish_time=? WHERE channel_db_id=?", (time_str, channel_db_id))
        await conn.commit()
    return await execute_db(_set)

# ===================== دوال المنشورات المجدولة =====================
async def db_add_scheduled_post(chat_id: int, text: str, publish_time: datetime):
    async def _add(conn):
        await conn.execute("INSERT INTO scheduled_posts (chat_id, text, publish_time, fail_count) VALUES (?, ?, ?, 0)", (chat_id, sanitize_text(text), publish_time.isoformat()))
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

# ===================== دوال الإعدادات العامة =====================
async def db_get_publish_interval() -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='publish_interval'")
        row = await cur.fetchone()
        return safe_int(row[0] if row else DEFAULT_PUBLISH_INTERVAL_SECONDS, DEFAULT_PUBLISH_INTERVAL_SECONDS)
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
            if channel.startswith('@'):
                channel = channel[1:]
            return channel if channel else None
        return None
    return await execute_db(_get)

async def db_set_updates_channel(channel: str):
    if not channel:
        return False
    channel = channel.strip()
    if channel.startswith('@'):
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
        return row and row[0] == '1'
    return await execute_db(_get)

async def db_set_force_subscribe_status(enabled: bool):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('force_subscribe_enabled', ?)", ('1' if enabled else '0',))
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
        return row and row[0] == '1'
    return await execute_db(_get)

async def db_set_auto_backup(enabled: bool):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('auto_backup', ?)", ('1' if enabled else '0',))
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

async def db_set_allowed_sendcode_user(user_id: int):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO allowed_sendcode_user (id, user_id) VALUES (1, ?)", (user_id,))
        await conn.commit()
    return await execute_db(_set)

# ===================== دوال التذاكر =====================
async def db_get_next_ticket_number():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='last_ticket_number'")
        row = await cur.fetchone()
        return int(row[0]) if row else 0
    return await execute_db(_get)

async def db_save_ticket(user_id, username, message, ticket_num):
    async def _save(conn):
        created_at = utc_now_iso()
        await conn.execute("INSERT INTO support_tickets (user_id, username, message, ticket_number, status, created_at) VALUES (?,?,?,?,?,?)", (user_id, username, sanitize_text(message), ticket_num, 'pending', created_at))
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
        await conn.execute("DELETE FROM support_tickets")
        await conn.execute("UPDATE settings SET value='0' WHERE key='last_ticket_number'")
        await conn.commit()
        return True
    return await execute_db(_delete)

# ===================== دوال الإحالات =====================
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
        code_hash = hashlib.md5(f"{user_id}{time_module.time()}".encode()).hexdigest()[:8]
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
        max_per_day = safe_int(settings.get('max_referrals_per_day', '5'), 5)
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
        reward_days = safe_int(settings.get('reward_days_per_referral', '3'), 3)
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
            'total_referrals': total_referrals,
            'referral_count': row[0] if row else 0,
            'total_reward_days': row[1] if row else 0,
            'claimed_reward_days': row[2] if row else 0,
            'available_days': (row[1] if row else 0) - (row[2] if row else 0)
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
    return safe_int(settings.get('welcome_bonus_points', '10'), 10)

# ===================== دوال التذكيرات =====================
async def db_get_user_reminder_settings(user_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute("SELECT subscription_reminder, daily_stats_reminder, weekly_report, reminder_days_before, last_reminder_sent, notification_lang FROM user_reminder_settings WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row:
            return {
                'subscription_reminder': row[0] == 1,
                'daily_stats_reminder': row[1] == 1,
                'weekly_report': row[2] == 1,
                'reminder_days_before': row[3] if row[3] is not None else 3,
                'last_reminder_sent': row[4] if row[4] else 0,
                'notification_lang': row[5] if row[5] else 'ar'
            }
        else:
            await conn.execute("INSERT INTO user_reminder_settings (user_id, subscription_reminder, daily_stats_reminder, weekly_report, reminder_days_before, last_reminder_sent, notification_lang) VALUES (?, 1, 0, 1, 3, 0, 'ar')", (user_id,))
            await conn.commit()
            return {'subscription_reminder': True, 'daily_stats_reminder': False, 'weekly_report': True, 'reminder_days_before': 3, 'last_reminder_sent': 0, 'notification_lang': 'ar'}
    return await execute_db(_get)

async def db_update_reminder_settings(user_id: int, **kwargs):
    async def _update(conn):
        fields, values = [], []
        for key, value in kwargs.items():
            if key == 'subscription_reminder':
                fields.append("subscription_reminder=?")
                values.append(1 if value else 0)
            elif key == 'daily_stats_reminder':
                fields.append("daily_stats_reminder=?")
                values.append(1 if value else 0)
            elif key == 'weekly_report':
                fields.append("weekly_report=?")
                values.append(1 if value else 0)
            elif key == 'reminder_days_before':
                fields.append("reminder_days_before=?")
                values.append(value)
            elif key == 'notification_lang':
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
        now_timestamp = int(time_module.time())
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
                if settings['subscription_reminder']:
                    reminder_days = settings['reminder_days_before']
                    last_sent = settings['last_reminder_sent']
                    now_timestamp = int(time_module.time())
                    need_reminder = False
                    if 0 < days_left <= reminder_days:
                        if last_sent == 0:
                            need_reminder = True
                        elif (now_timestamp - last_sent) > (3 * 24 * 60 * 60):
                            need_reminder = True
                    if need_reminder:
                        users.append({'user_id': user_id, 'days_left': days_left, 'notification_lang': settings['notification_lang']})
            except:
                continue
        return users
    return await execute_db(_get)

# ===================== دوال المستويات =====================
async def db_get_user_level(user_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT points, level FROM user_levels WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row:
            return {'points': row[0], 'level': row[1]}
        return {'points': 0, 'level': 1}
    return await execute_db(_get)

async def db_update_user_level(user_id: int, points: int, level: int):
    async def _update(conn):
        await conn.execute("INSERT OR REPLACE INTO user_levels (user_id, points, level) VALUES (?,?,?)", (user_id, points, level))
        await conn.commit()
    return await execute_db(_update)

async def get_top_users(limit: int = 10):
    async def _get(conn):
        cur = await conn.execute("SELECT user_id, points, level FROM user_levels ORDER BY points DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

# ===================== دوال المسابقات =====================
async def db_get_active_contests_with_participants(limit: int = 10):
    async def _get(conn):
        cur = await conn.execute("""
            SELECT c.id, c.title, c.description, c.prize, c.end_date,
                   (SELECT COUNT(*) FROM contest_participants WHERE contest_id = c.id) as participants_count,
                   c.contest_type
            FROM contests c
            WHERE c.status = 'active'
            ORDER BY c.end_date ASC
            LIMIT ?
        """, (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_user_participation(user_id: int, contest_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT id FROM contest_participants WHERE user_id=? AND contest_id=?", (user_id, contest_id))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_get_contest(contest_id: int) -> dict | None:
    async def _get(conn):
        cur = await conn.execute("SELECT id, creator_id, title, description, prize, end_date, status, winner_id, created_at, contest_type FROM contests WHERE id=?", (contest_id,))
        row = await cur.fetchone()
        if row:
            return dict(row)
        return None
    return await execute_db(_get)

async def db_get_random_participant(contest_id: int) -> int | None:
    async def _get(conn):
        cur = await conn.execute("SELECT user_id FROM contest_participants WHERE contest_id=? ORDER BY RANDOM() LIMIT 1", (contest_id,))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_set_contest_winner(contest_id: int, winner_id: int) -> bool:
    async def _set(conn):
        await conn.execute("UPDATE contests SET status='finished', winner_id=? WHERE id=?", (winner_id, contest_id))
        await conn.execute("INSERT INTO contest_winners (contest_id, winner_id, announced_at) VALUES (?, ?, ?)", (contest_id, winner_id, utc_now_iso()))
        await conn.commit()
        return True
    return await execute_db(_set)

async def db_get_contest_winners(limit: int = 10):
    async def _get(conn):
        cur = await conn.execute("""
            SELECT cw.contest_id, c.title, c.prize, cw.winner_id, cw.announced_at
            FROM contest_winners cw
            JOIN contests c ON cw.contest_id = c.id
            ORDER BY cw.announced_at DESC
            LIMIT ?
        """, (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

# ===================== دوال الترجمة =====================
async def get_user_translation_language(user_id: int) -> str:
    async def _get(conn):
        cur = await conn.execute("SELECT lang FROM user_translation WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 'off'
    return await execute_db(_get)

async def set_user_translation_language(user_id: int, lang: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO user_translation (user_id, lang) VALUES (?, ?)", (user_id, lang))
        await conn.commit()
    await execute_db(_set)

# ===================== دوال الردود =====================
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

# ===================== دوال الردود التلقائية =====================
async def db_get_auto_reply_settings(chat_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute(
            "SELECT enabled, only_admins, ignore_bots FROM auto_reply_settings WHERE chat_id=?",
            (chat_id,)
        )
        row = await cur.fetchone()
        if row:
            return {
                'enabled': row[0] == 1,
                'only_admins': row[1] == 1,
                'ignore_bots': row[2] == 1
            }
        return {'enabled': True, 'only_admins': False, 'ignore_bots': True}
    return await execute_db(_get)

async def db_set_auto_reply_enabled(chat_id: int, enabled: bool):
    async def _set(conn):
        await conn.execute("""
            INSERT OR REPLACE INTO auto_reply_settings (chat_id, enabled, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (chat_id, 1 if enabled else 0))
        await conn.commit()
    return await execute_db(_set)

async def db_set_auto_reply_only_admins(chat_id: int, only_admins: bool):
    async def _set(conn):
        await conn.execute("""
            UPDATE auto_reply_settings SET only_admins=?, updated_at=CURRENT_TIMESTAMP
            WHERE chat_id=?
        """, (1 if only_admins else 0, chat_id))
        await conn.commit()
    return await execute_db(_set)

async def db_toggle_auto_reply(chat_id: int) -> bool:
    settings = await db_get_auto_reply_settings(chat_id)
    new_status = not settings['enabled']
    await db_set_auto_reply_enabled(chat_id, new_status)
    return new_status

async def db_get_user_auto_reply_status(user_id: int) -> bool:
    async def _get(conn):
        cur = await conn.execute(
            "SELECT auto_reply_enabled FROM users WHERE user_id=?",
            (user_id,)
        )
        row = await cur.fetchone()
        return row[0] == 1 if row else True
    return await execute_db(_get)

async def db_set_user_auto_reply_status(user_id: int, enabled: bool):
    async def _set(conn):
        await conn.execute(
            "UPDATE users SET auto_reply_enabled=? WHERE user_id=?",
            (1 if enabled else 0, user_id)
        )
        await conn.commit()
    return await execute_db(_set)

# ===================== دوال القفل =====================
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

# ===================== دوال الإحصائيات =====================
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

# ===================== دوال إحصائيات القنوات =====================
async def db_get_channel_stats(channel_db_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute("""
            SELECT 
                (SELECT COUNT(*) FROM posts WHERE channel_db_id=?) as total_posts,
                (SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=1) as published_posts,
                (SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0) as unpublished_posts,
                (SELECT COALESCE(SUM(views_count), 0) FROM posts WHERE channel_db_id=?) as total_views,
                (SELECT AVG(views_count) FROM posts WHERE channel_db_id=? AND views_count > 0) as avg_views,
                (SELECT created_at FROM posts WHERE channel_db_id=? ORDER BY created_at LIMIT 1) as first_post_time,
                (SELECT created_at FROM posts WHERE channel_db_id=? ORDER BY created_at DESC LIMIT 1) as last_post_time,
                (SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND DATE(created_at) = DATE('now')) as published_today,
                (SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND DATE(created_at) >= DATE('now', '-7 days')) as published_this_week,
                (SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND DATE(created_at) >= DATE('now', '-30 days')) as published_this_month
        """, (channel_db_id, channel_db_id, channel_db_id, channel_db_id, channel_db_id, channel_db_id, channel_db_id, channel_db_id, channel_db_id, channel_db_id))
        row = await cur.fetchone()
        if not row:
            return {'total_posts': 0, 'published_posts': 0, 'unpublished_posts': 0, 'total_views': 0, 'avg_views': 0, 'first_post_time': None, 'last_post_time': None, 'published_today': 0, 'published_this_week': 0, 'published_this_month': 0}
        stats = {
            'total_posts': row[0] or 0,
            'published_posts': row[1] or 0,
            'unpublished_posts': row[2] or 0,
            'total_views': row[3] or 0,
            'avg_views': round(row[4] or 0, 2),
            'first_post_time': row[5],
            'last_post_time': row[6],
            'published_today': row[7] or 0,
            'published_this_week': row[8] or 0,
            'published_this_month': row[9] or 0,
            'most_viewed_post': None,
            'least_viewed_post': None,
            'avg_time_between_posts': 0,
            'best_publish_hour': 0,
            'best_publish_day': 0
        }
        cur = await conn.execute("SELECT id, text, views_count FROM posts WHERE channel_db_id=? AND published=1 ORDER BY views_count DESC LIMIT 1", (channel_db_id,))
        most = await cur.fetchone()
        if most:
            stats['most_viewed_post'] = {'id': most[0], 'text': most[1][:100], 'views': most[2]}
        cur = await conn.execute("SELECT id, text, views_count FROM posts WHERE channel_db_id=? AND published=1 AND views_count > 0 ORDER BY views_count ASC LIMIT 1", (channel_db_id,))
        least = await cur.fetchone()
        if least:
            stats['least_viewed_post'] = {'id': least[0], 'text': least[1][:100], 'views': least[2]}
        return stats
    return await execute_db(_get)

async def db_get_channel_growth(channel_db_id: int, days: int = 30) -> dict:
    async def _get(conn):
        start_date = (utc_now() - timedelta(days=days)).isoformat()
        cur = await conn.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as count, COALESCE(SUM(views_count), 0) as views
            FROM posts
            WHERE channel_db_id=? AND created_at >= ?
            GROUP BY DATE(created_at)
            ORDER BY date
        """, (channel_db_id, start_date))
        rows = await cur.fetchall()
        dates = []
        counts = []
        views = []
        total_posts = 0
        total_views = 0
        for row in rows:
            dates.append(row[0])
            counts.append(row[1])
            views.append(row[2])
            total_posts += row[1]
            total_views += row[2]
        return {
            'dates': dates,
            'counts': counts,
            'views': views,
            'total_posts': total_posts,
            'total_views': total_views,
            'total_days': len(dates)
        }
    return await execute_db(_get)

async def db_get_channel_stats_summary(user_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute("""
            SELECT 
                COUNT(DISTINCT uc.id) as total_channels,
                SUM(CASE WHEN uc.banned=0 THEN 1 ELSE 0 END) as active_channels,
                COUNT(p.id) as total_posts,
                SUM(CASE WHEN p.published=1 THEN 1 ELSE 0 END) as total_published,
                COALESCE(SUM(p.views_count), 0) as total_views
            FROM user_channels uc
            LEFT JOIN posts p ON uc.id = p.channel_db_id
            WHERE uc.user_id=?
        """, (user_id,))
        row = await cur.fetchone()
        if not row or row[0] == 0:
            return None
        result = {
            'total_channels': row[0] or 0,
            'active_channels': row[1] or 0,
            'total_posts': row[2] or 0,
            'total_published': row[3] or 0,
            'total_views': row[4] or 0,
            'avg_views_per_channel': 0,
            'best_channel': None
        }
        if result['total_channels'] > 0:
            result['avg_views_per_channel'] = round(result['total_views'] / result['total_channels'], 2)
        cur = await conn.execute("""
            SELECT uc.channel_name, COALESCE(SUM(p.views_count), 0) as views, COUNT(p.id) as posts, COALESCE(AVG(p.views_count), 0) as avg_views
            FROM user_channels uc
            LEFT JOIN posts p ON uc.id = p.channel_db_id
            WHERE uc.user_id=?
            GROUP BY uc.id
            ORDER BY views DESC
            LIMIT 1
        """, (user_id,))
        best = await cur.fetchone()
        if best:
            result['best_channel'] = {
                'name': best[0] or 'بدون اسم',
                'views': best[1] or 0,
                'posts': best[2] or 0,
                'avg_views': round(best[3] or 0, 2)
            }
        return result
    return await execute_db(_get)

# ===================== دوال اللغة =====================
async def set_user_language(user_id: int, lang: str):
    user_language[user_id] = lang
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO user_language (user_id, lang) VALUES (?, ?)", (user_id, lang))
        await conn.commit()
    await execute_db(_set)

# ===================== دوال تهيئة قاعدة البيانات =====================
async def init_db_improved():
    """تهيئة قاعدة البيانات مع جميع الجداول والفهارس والتحسينات"""
    import aiosqlite
    from constants import DB_PATH, DB_TIMEOUT, PRIMARY_OWNER_ID, DEFAULT_PUBLISH_INTERVAL_SECONDS
    from utils import utc_now_iso
    
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

        # ========== إنشاء الجداول ==========
        
        # جدول المستخدمين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                auto_publish INTEGER DEFAULT 1,
                banned INTEGER DEFAULT 0,
                trial_used INTEGER DEFAULT 0,
                subscription_end TEXT DEFAULT NULL,
                referral_code TEXT DEFAULT NULL,
                referred_by INTEGER DEFAULT NULL,
                active_channel INTEGER DEFAULT NULL,
                auto_reply_enabled INTEGER DEFAULT 1,
                auto_recycle INTEGER DEFAULT 1,
                last_daily_reward TEXT DEFAULT NULL,
                last_weekly_reward TEXT DEFAULT NULL,
                achievements TEXT DEFAULT '[]'
            )
        """)
        
        # جدول قنوات المستخدمين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id TEXT,
                channel_name TEXT,
                created_at TIMESTAMP,
                banned INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        # جدول المنشورات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_db_id INTEGER,
                text TEXT,
                media_type TEXT DEFAULT 'text',
                media_file_id TEXT,
                published INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                views_count INTEGER DEFAULT 0,
                last_view_time TIMESTAMP,
                created_at TIMESTAMP,
                FOREIGN KEY(channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
            )
        """)
        
        # جدول الإعدادات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # جدول ردود المجموعة
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_replies (
                keyword TEXT PRIMARY KEY,
                reply TEXT
            )
        """)
        
        # جدول أمان المجموعة
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_security (
                chat_id INTEGER PRIMARY KEY,
                delete_links INTEGER DEFAULT 0,
                delete_mentions INTEGER DEFAULT 0,
                warn_message INTEGER DEFAULT 1,
                slow_mode INTEGER DEFAULT 0,
                slow_mode_seconds INTEGER DEFAULT 5,
                welcome_enabled INTEGER DEFAULT 0,
                welcome_text TEXT DEFAULT 'مرحباً {user} في {chat} 🤍',
                goodbye_enabled INTEGER DEFAULT 0,
                goodbye_text TEXT DEFAULT 'وداعاً {user} 👋',
                delete_banned_words INTEGER DEFAULT 0,
                auto_penalty TEXT DEFAULT 'none',
                auto_mute_duration INTEGER DEFAULT 60,
                delete_stickers INTEGER DEFAULT 0,
                delete_videos INTEGER DEFAULT 0,
                delete_service_messages INTEGER DEFAULT 0
            )
        """)
        
        # جدول إعدادات المجموعة
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_settings (
                chat_id INTEGER PRIMARY KEY,
                anti_links INTEGER DEFAULT 0,
                anti_badwords INTEGER DEFAULT 0,
                welcome_msg INTEGER DEFAULT 1,
                mute_all INTEGER DEFAULT 0
            )
        """)
        
        # جدول مشرفي البوت
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        
        # جدول مجموعات البوت
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_groups (
                chat_id INTEGER PRIMARY KEY,
                chat_name TEXT,
                username TEXT,
                added_by INTEGER,
                added_at TIMESTAMP,
                banned INTEGER DEFAULT 0
            )
        """)
        
        # جدول قنوات البوت
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_channels (
                channel_id INTEGER PRIMARY KEY,
                channel_name TEXT,
                added_by INTEGER,
                added_at TIMESTAMP,
                banned INTEGER DEFAULT 0
            )
        """)
        
        # جدول رسائل المستخدمين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_messages (
                user_id INTEGER,
                chat_id INTEGER,
                message_time TIMESTAMP,
                PRIMARY KEY (user_id, chat_id)
            )
        """)
        
        # جدول كاش المستخدمين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users_cache (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_updated TEXT
            )
        """)
        
        # جدول تحذيرات المستخدمين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_warnings (
                user_id INTEGER,
                chat_id INTEGER,
                warnings INTEGER DEFAULT 0,
                PRIMARY KEY(user_id, chat_id)
            )
        """)
        
        # جدول الكلمات المحظورة
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS banned_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT,
                chat_id INTEGER,
                added_by INTEGER,
                added_at TIMESTAMP,
                UNIQUE(word, chat_id)
            )
        """)
        
        # جدول المالكين المخفيين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hidden_owner_groups (
                chat_id INTEGER PRIMARY KEY,
                owner_id INTEGER,
                is_hidden INTEGER DEFAULT 1
            )
        """)
        
        # جدول المشرفين المخفيين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hidden_admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                admin_id INTEGER NOT NULL,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, admin_id)
            )
        """)
        
        # جدول رابط المستخدمين بالمجموعات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_groups_link (
                user_id INTEGER,
                chat_id INTEGER,
                PRIMARY KEY(user_id, chat_id)
            )
        """)
        
        # جدول مشرفي المجموعة
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_admins (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY(chat_id, user_id)
            )
        """)
        
        # جدول مستويات المستخدمين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_levels (
                user_id INTEGER PRIMARY KEY,
                points INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1
            )
        """)
        
        # جدول تذاكر الدعم
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                message TEXT,
                ticket_number INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP,
                replied INTEGER DEFAULT 0
            )
        """)
        
        # جدول قفل المجموعات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_locks (
                chat_id INTEGER PRIMARY KEY,
                locked INTEGER DEFAULT 0,
                locked_at TIMESTAMP,
                locked_by INTEGER
            )
        """)
        
        # جدول الجدولة
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schedule (
                channel_db_id INTEGER PRIMARY KEY,
                schedule_type TEXT DEFAULT 'interval_minutes',
                interval_minutes INTEGER DEFAULT 12,
                interval_hours INTEGER DEFAULT 0,
                interval_days INTEGER DEFAULT 0,
                days_of_week TEXT DEFAULT '',
                specific_dates TEXT DEFAULT '',
                publish_time TEXT DEFAULT '00:00',
                cron_expression TEXT DEFAULT NULL,
                next_publish_date TEXT,
                FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
            )
        """)
        
        # جدول آخر نشر
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS last_publish (
                channel_db_id INTEGER PRIMARY KEY,
                last_publish_time TIMESTAMP,
                FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
            )
        """)
        
        # جدول المنشورات المجدولة
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                publish_time TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                fail_count INTEGER DEFAULT 0
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_time ON scheduled_posts(publish_time)")
        
        # جدول مستخدم /sendcode
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS allowed_sendcode_user (
                id INTEGER PRIMARY KEY CHECK (id=1),
                user_id INTEGER
            )
        """)
        
        # جدول الإحالات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                referred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_rewarded INTEGER DEFAULT 0,
                UNIQUE(referred_id)
            )
        """)
        
        # جدول مكافآت الإحالات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referral_rewards (
                user_id INTEGER PRIMARY KEY,
                referral_count INTEGER DEFAULT 0,
                total_reward_days INTEGER DEFAULT 0,
                claimed_reward_days INTEGER DEFAULT 0
            )
        """)
        
        # جدول إعدادات الإحالات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referral_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # جدول إعدادات التذكيرات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_reminder_settings (
                user_id INTEGER PRIMARY KEY,
                subscription_reminder INTEGER DEFAULT 1,
                daily_stats_reminder INTEGER DEFAULT 0,
                weekly_report INTEGER DEFAULT 1,
                reminder_days_before INTEGER DEFAULT 3,
                last_reminder_sent INTEGER DEFAULT 0,
                notification_lang TEXT DEFAULT 'ar'
            )
        """)
        
        # جدول سجل الإجراءات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS moderation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                action TEXT,
                duration_minutes INTEGER,
                moderator_id INTEGER,
                reason TEXT,
                created_at TIMESTAMP
            )
        """)
        
        # جدول ترجمة المستخدمين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_translation (
                user_id INTEGER PRIMARY KEY,
                lang TEXT DEFAULT 'off'
            )
        """)
        
        # جدول إحصائيات القنوات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS channel_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_db_id INTEGER NOT NULL,
                total_posts INTEGER DEFAULT 0,
                published_posts INTEGER DEFAULT 0,
                unpublished_posts INTEGER DEFAULT 0,
                total_views INTEGER DEFAULT 0,
                avg_views_per_post REAL DEFAULT 0,
                last_post_time TIMESTAMP,
                avg_time_between_posts REAL DEFAULT 0,
                best_publish_hour INTEGER DEFAULT 0,
                best_publish_day INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE,
                UNIQUE(channel_db_id)
            )
        """)
        
        # جدول جلسات الويب
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS web_sessions (
                session_id TEXT PRIMARY KEY,
                user_data TEXT,
                expires INTEGER
            )
        """)
        
        # جدول المسابقات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER,
                title TEXT,
                description TEXT,
                prize TEXT,
                end_date TEXT,
                status TEXT DEFAULT 'active',
                winner_id INTEGER,
                created_at TIMESTAMP,
                contest_type TEXT DEFAULT 'raffle'
            )
        """)
        
        # جدول مشاركي المسابقات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contest_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                contest_id INTEGER,
                answer TEXT,
                joined_at TIMESTAMP,
                UNIQUE(user_id, contest_id)
            )
        """)
        
        # جدول فائزي المسابقات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contest_winners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contest_id INTEGER,
                winner_id INTEGER,
                announced_at TIMESTAMP
            )
        """)
        
        # جدول إعدادات الردود التلقائية
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS auto_reply_settings (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                only_admins INTEGER DEFAULT 0,
                ignore_bots INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # جدول قوانين المجموعة
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_rules (
                chat_id INTEGER PRIMARY KEY,
                rules_text TEXT,
                set_by INTEGER,
                set_at TIMESTAMP
            )
        """)
        
        # جدول لغة المستخدمين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_language (
                user_id INTEGER PRIMARY KEY,
                lang TEXT DEFAULT 'ar'
            )
        """)
        
        # ========== إنشاء الفهارس ==========
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
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_group_admins_chat ON group_admins(chat_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_group_admins_user ON group_admins(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_group_rules_chat ON group_rules(chat_id)")

        # ========== تحديث الجداول القديمة ==========
        try:
            cursor = await conn.execute("PRAGMA table_info(group_security)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if 'auto_penalty' not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN auto_penalty TEXT DEFAULT 'none'")
            if 'auto_mute_duration' not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN auto_mute_duration INTEGER DEFAULT 60")
            if 'delete_stickers' not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN delete_stickers INTEGER DEFAULT 0")
            if 'delete_videos' not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN delete_videos INTEGER DEFAULT 0")
            if 'delete_service_messages' not in column_names:
                await conn.execute("ALTER TABLE group_security ADD COLUMN delete_service_messages INTEGER DEFAULT 0")
        except Exception as e:
            print(f"خطأ في تحديث group_security: {e}")

        try:
            cursor = await conn.execute("PRAGMA table_info(users)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if 'active_channel' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN active_channel INTEGER DEFAULT NULL")
            if 'referral_code' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN referral_code TEXT DEFAULT NULL")
            if 'auto_reply_enabled' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN auto_reply_enabled INTEGER DEFAULT 1")
            if 'auto_recycle' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN auto_recycle INTEGER DEFAULT 1")
            if 'last_daily_reward' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN last_daily_reward TEXT DEFAULT NULL")
            if 'last_weekly_reward' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN last_weekly_reward TEXT DEFAULT NULL")
            if 'achievements' not in column_names:
                await conn.execute("ALTER TABLE users ADD COLUMN achievements TEXT DEFAULT '[]'")
        except Exception as e:
            print(f"خطأ في تحديث users: {e}")

        try:
            cursor = await conn.execute("PRAGMA table_info(posts)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if 'views_count' not in column_names:
                await conn.execute("ALTER TABLE posts ADD COLUMN views_count INTEGER DEFAULT 0")
            if 'last_view_time' not in column_names:
                await conn.execute("ALTER TABLE posts ADD COLUMN last_view_time TIMESTAMP")
        except Exception as e:
            print(f"خطأ في تحديث posts: {e}")

        try:
            cursor = await conn.execute("PRAGMA table_info(contests)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if 'contest_type' not in column_names:
                await conn.execute("ALTER TABLE contests ADD COLUMN contest_type TEXT DEFAULT 'raffle'")
        except Exception as e:
            print(f"خطأ في تحديث contests: {e}")

        try:
            cursor = await conn.execute("PRAGMA table_info(schedule)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            if 'cron_expression' not in column_names:
                await conn.execute("ALTER TABLE schedule ADD COLUMN cron_expression TEXT DEFAULT NULL")
        except Exception as e:
            print(f"خطأ في تحديث schedule: {e}")

        # ========== البيانات الافتراضية ==========
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
    
    # تهيئة pool الاتصالات
    await db_pool.initialize()
    
    print("✅ قاعدة البيانات جاهزة مع جميع الجداول والتحسينات")
