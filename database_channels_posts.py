#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
database_channels_posts.py - دوال القنوات والمنشورات (Mixin)
================================================================================
يُستخدم مع Database عبر الوراثة المتعددة (Mixin).

🆕 v7.2: استخراج من database.py
- 12 دالة قنوات (Channels)
- 7 دوال منشورات (Posts)

📌 كل الدوال تعمل بنفس السلوك السابق — لا تغيير في الميزات.
"""

import random
import logging
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ChannelsPostsMixin:
    """
    Mixin يجمع دوال القنوات والمنشورات.

    يفترض أن الفئة الأم (Database) تحتوي على:
    - _get_user_lock, _get_channel_lock
    - transaction, connection
    - _execute_with_conn, _fetchone_with_conn, _fetchall_with_conn,
      _fetchval_with_conn, _executemany_with_conn
    - _ensure_text_hash_column, _compute_text_hash
    - _posts_batch_size, _max_post_text_length
    - fetchval, fetchone, fetchall, execute
    """

    # ═════════════════════════════════════════════════════════════════
    #                    🎬 دوال القنوات (12 دالة)
    # ═════════════════════════════════════════════════════════════════

    async def add_channel(
        self, user_id: int, channel_id: int, channel_name: str, set_active: bool = True
    ) -> Optional[Dict]:
        """
        إضافة قناة جديدة للمستخدم.

        يتحقق من:
        - حدود الباقة (max_channels)
        - عدم وجود القناة مسبقاً
        - إعداد الجدولة تلقائياً (12 دقيقة)
        - منح 10 نقاط للقناة الجديدة

        Returns:
            dict: {id, channel_id, channel_name, posts_count}
            None: في حال الفشل
        """
        from database import USE_POSTGRES, USE_MYSQL, TimeUtils
        from database import internal_cache, CACHE_AVAILABLE
        from database import invalidate_user_cache, channels_cache

        try:
            channel_id = int(channel_id)
            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    # ─── 1) فحص حدود الباقة ───
                    if USE_POSTGRES:
                        plan_row = await self._fetchone_with_conn(
                            conn,
                            """SELECT (SELECT max_channels FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                                      WHERE s.user_id = $1 AND s.status = 'active' AND s.end_date > $2
                                      ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1) as max_channels,
                                      (SELECT COUNT(*) FROM user_channels WHERE user_id = $1 AND banned = 0) as cnt""",
                            user_id, TimeUtils.utc_now(),
                        )
                    elif USE_MYSQL:
                        plan_row = await self._fetchone_with_conn(
                            conn,
                            """SELECT (SELECT max_channels FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                                      WHERE s.user_id = %s AND s.status = 'active' AND s.end_date > %s
                                      ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1) as max_channels,
                                      (SELECT COUNT(*) FROM user_channels WHERE user_id = %s AND banned = 0) as cnt""",
                            user_id, TimeUtils.sql_iso(), user_id,
                        )
                    else:
                        plan_row = await self._fetchone_with_conn(
                            conn,
                            """SELECT (SELECT max_channels FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                                      WHERE s.user_id = ? AND s.status = 'active' AND s.end_date > ?
                                      ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1) as max_channels,
                                      (SELECT COUNT(*) FROM user_channels WHERE user_id = ? AND banned = 0) as cnt""",
                            user_id, TimeUtils.sql_iso(), user_id,
                        )

                    if not plan_row:
                        return None
                    max_channels = plan_row["max_channels"] or 0
                    current_count = plan_row["cnt"] or 0
                    if current_count >= max_channels:
                        logger.warning(
                            f"⚠️ المستخدم {user_id} تجاوز الحد الأقصى للقنوات ({max_channels})"
                        )
                        return None

                    # ─── 2) إدراج أو تحديث القناة ───
                    existing = await self._fetchone_with_conn(
                        conn,
                        "SELECT id FROM user_channels WHERE user_id = ? AND channel_id = ?",
                        user_id, channel_id,
                    )
                    if existing:
                        ch_db_id = existing["id"]
                        await self._execute_with_conn(
                            conn,
                            "UPDATE user_channels SET channel_name = ?, banned = 0 WHERE id = ?",
                            channel_name, ch_db_id,
                        )
                        is_new = False
                    else:
                        if USE_POSTGRES:
                            row = await self._fetchone_with_conn(
                                conn,
                                "INSERT INTO user_channels (user_id, channel_id, channel_name, created_at) "
                                "VALUES ($1, $2, $3, $4) RETURNING id",
                                user_id, channel_id, channel_name, TimeUtils.utc_now(),
                            )
                            ch_db_id = row["id"]
                        elif USE_MYSQL:
                            cursor = await conn.cursor()
                            await cursor.execute(
                                "INSERT INTO user_channels (user_id, channel_id, channel_name, created_at) "
                                "VALUES (%s, %s, %s, %s)",
                                (user_id, channel_id, channel_name, TimeUtils.sql_iso()),
                            )
                            ch_db_id = cursor.lastrowid
                            await cursor.close()
                        else:
                            cursor = await conn.execute(
                                "INSERT INTO user_channels (user_id, channel_id, channel_name, created_at) "
                                "VALUES (?,?,?,?)",
                                (user_id, channel_id, channel_name, TimeUtils.sql_iso()),
                            )
                            ch_db_id = cursor.lastrowid
                        is_new = True

                    # ─── 3) تعيين القناة النشطة ───
                    if set_active:
                        await self._execute_with_conn(
                            conn, "UPDATE users SET active_channel = ? WHERE user_id = ?",
                            ch_db_id, user_id,
                        )

                    # ─── 4) إعداد الجدولة ───
                    delay_seconds = random.randint(5, 30) + (user_id % 10)
                    next_publish = TimeUtils.utc_now() + timedelta(seconds=delay_seconds)

                    if USE_POSTGRES:
                        await self._execute_with_conn(
                            conn,
                            """INSERT INTO schedule (channel_db_id, schedule_type, interval_minutes, next_publish_date)
                               VALUES ($1, 'interval_minutes', 12, $2)
                               ON CONFLICT (channel_db_id) DO UPDATE SET
                                   schedule_type = EXCLUDED.schedule_type,
                                   interval_minutes = EXCLUDED.interval_minutes,
                                   next_publish_date = EXCLUDED.next_publish_date""",
                            ch_db_id, next_publish,
                        )
                    elif USE_MYSQL:
                        await self._execute_with_conn(
                            conn,
                            """INSERT INTO schedule (channel_db_id, schedule_type, interval_minutes, next_publish_date)
                               VALUES (%s, 'interval_minutes', 12, %s)
                               ON DUPLICATE KEY UPDATE
                                   schedule_type = VALUES(schedule_type),
                                   interval_minutes = VALUES(interval_minutes),
                                   next_publish_date = VALUES(next_publish_date)""",
                            ch_db_id, next_publish.strftime("%Y-%m-%d %H:%M:%S"),
                        )
                    else:
                        await self._execute_with_conn(
                            conn,
                            """INSERT INTO schedule (channel_db_id, schedule_type, interval_minutes, next_publish_date)
                               VALUES (?, 'interval_minutes', 12, ?)
                               ON CONFLICT(channel_db_id) DO UPDATE SET
                                   schedule_type = excluded.schedule_type,
                                   interval_minutes = excluded.interval_minutes,
                                   next_publish_date = excluded.next_publish_date""",
                            ch_db_id, next_publish.strftime("%Y-%m-%d %H:%M:%S"),
                        )

                    # ─── 5) last_publish ───
                    if USE_POSTGRES:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO last_publish (channel_db_id, last_publish_time) "
                            "VALUES ($1, $2) ON CONFLICT (channel_db_id) DO NOTHING",
                            ch_db_id, next_publish,
                        )
                    elif USE_MYSQL:
                        await self._execute_with_conn(
                            conn,
                            "INSERT IGNORE INTO last_publish (channel_db_id, last_publish_time) "
                            "VALUES (%s, %s)",
                            ch_db_id, next_publish.strftime("%Y-%m-%d %H:%M:%S"),
                        )
                    else:
                        await self._execute_with_conn(
                            conn,
                            "INSERT OR IGNORE INTO last_publish (channel_db_id, last_publish_time) "
                            "VALUES (?, ?)",
                            ch_db_id, next_publish.strftime("%Y-%m-%d %H:%M:%S"),
                        )

                    # ─── 6) منح نقاط ───
                    if is_new:
                        if USE_POSTGRES:
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO user_points (user_id, points, last_updated) "
                                "VALUES ($1, 10, $2) "
                                "ON CONFLICT (user_id) DO UPDATE SET "
                                "points = user_points.points + 10, last_updated = $2",
                                user_id, TimeUtils.utc_now(),
                            )
                        elif USE_MYSQL:
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO user_points (user_id, points, last_updated) "
                                "VALUES (%s, 10, %s) "
                                "ON DUPLICATE KEY UPDATE points = points + 10, last_updated = %s",
                                user_id, TimeUtils.sql_iso(), TimeUtils.sql_iso(),
                            )
                        else:
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO user_points (user_id, points, last_updated) "
                                "VALUES (?,10,?) "
                                "ON CONFLICT(user_id) DO UPDATE SET "
                                "points = points + 10, last_updated = ?",
                                user_id, TimeUtils.sql_iso(), TimeUtils.sql_iso(),
                            )

                    # ─── 7) عدد المنشورات ───
                    posts_count = await self._fetchval_with_conn(
                        conn,
                        "SELECT COUNT(*) FROM posts WHERE channel_db_id = ? AND published = 0",
                        ch_db_id, default=0,
                    )

                    # ─── 8) إبطال الكاش ───
                    await internal_cache.invalidate(f"user_{user_id}")
                    await internal_cache.invalidate(f"channel_info_{ch_db_id}")
                    if CACHE_AVAILABLE:
                        await invalidate_user_cache(user_id)
                        await channels_cache.invalidate(user_id)
                        if hasattr(channels_cache, "invalidate_channel_info"):
                            await channels_cache.invalidate_channel_info(ch_db_id)

                    return {
                        "id": ch_db_id,
                        "channel_id": channel_id,
                        "channel_name": channel_name,
                        "posts_count": posts_count,
                    }
        except Exception as e:
            logger.error(f"❌ Error in add_channel: {e}", exc_info=True)
            return None

    async def get_active_channel(self, user_id: int) -> Optional[int]:
        """جلب القناة النشطة (مع التحقق من عدم الحظر)"""
        result = await self.fetchval(
            "SELECT active_channel FROM users WHERE user_id = ?", (user_id,)
        )
        if result:
            banned = await self.fetchval(
                "SELECT banned FROM user_channels WHERE id = ? AND user_id = ?",
                (result, user_id), default=1,
            )
            if banned == 0:
                return result
        return await self.fetchval(
            "SELECT id FROM user_channels WHERE user_id = ? AND banned = 0 ORDER BY id LIMIT 1",
            (user_id,),
        )

    async def set_active_channel(self, user_id: int, channel_db_id: int) -> bool:
        """تعيين القناة النشطة"""
        from database import internal_cache, CACHE_AVAILABLE, invalidate_user_cache

        exists = await self.fetchval(
            "SELECT 1 FROM user_channels WHERE id = ? AND user_id = ? AND banned = 0",
            (channel_db_id, user_id),
        )
        if not exists:
            return False

        result = await self.execute(
            "UPDATE users SET active_channel = ? WHERE user_id = ?",
            (channel_db_id, user_id),
        ) > 0

        if result:
            await internal_cache.invalidate(f"user_{user_id}")
            await internal_cache.invalidate(f"channel_info_{channel_db_id}")
            if CACHE_AVAILABLE:
                await invalidate_user_cache(user_id)
        return result

    async def get_user_channels(self, user_id: int) -> List[Dict]:
        """جلب كل قنوات المستخدم (مع كاش)"""
        from database import internal_cache, CACHE_AVAILABLE, channels_cache

        if CACHE_AVAILABLE:
            cached = await channels_cache.get(user_id)
            if cached is not None:
                return cached
        cached = await internal_cache.get(f"channels_{user_id}")
        if cached is not None:
            return cached

        channels = await self.fetchall(
            "SELECT id, channel_id, channel_name, banned, created_at "
            "FROM user_channels WHERE user_id = ? "
            "ORDER BY created_at DESC",
            (user_id,),
        )
        await internal_cache.set(f"channels_{user_id}", channels)
        if CACHE_AVAILABLE:
            await channels_cache.set(user_id, channels)
        return channels

    async def get_channel_info(self, user_id: int, channel_db_id: int) -> Optional[Dict]:
        """جلب معلومات قناة (مع التحقق من الملكية + كاش)"""
        from database import internal_cache, CACHE_AVAILABLE, channels_cache

        if CACHE_AVAILABLE:
            cached = await channels_cache.get_channel_info(channel_db_id)
            if cached is not None:
                return cached
        cached = await internal_cache.get(f"channel_info_{channel_db_id}")
        if cached is not None:
            return cached

        result = await self.fetchone(
            "SELECT * FROM user_channels WHERE id = ? AND user_id = ?",
            (channel_db_id, user_id),
        )
        if result:
            await internal_cache.set(f"channel_info_{channel_db_id}", result)
            if CACHE_AVAILABLE:
                await channels_cache.set_channel_info(channel_db_id, result)
        return result

    async def get_channel_stats(self, user_id: int, channel_db_id: int) -> Dict:
        """إحصائيات القناة"""
        exists = await self.fetchval(
            "SELECT 1 FROM user_channels WHERE id = ? AND user_id = ?",
            (channel_db_id, user_id),
        )
        if not exists:
            return {"total": 0, "published": 0, "unpublished": 0}

        total = await self.fetchval(
            "SELECT COUNT(*) FROM posts WHERE channel_db_id = ?",
            (channel_db_id,), default=0,
        )
        published = await self.fetchval(
            "SELECT COUNT(*) FROM posts WHERE channel_db_id = ? AND published = 1",
            (channel_db_id,), default=0,
        )
        return {"total": total, "published": published, "unpublished": total - published}

    async def get_unpublished_posts_count(self, user_id: int, channel_db_id: int) -> int:
        """عدد المنشورات غير المنشورة"""
        owner = await self.fetchval(
            "SELECT 1 FROM user_channels WHERE id=? AND user_id=?",
            (channel_db_id, user_id), default=0,
        )
        if not owner:
            return 0
        return await self.fetchval(
            "SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0",
            (channel_db_id,), default=0,
        )

    async def get_channel_by_user(self, user_id: int, channel_id: int) -> Optional[Dict]:
        """جلب قناة بواسطة user_id + channel_id (Telegram ID)"""
        return await self.fetchone(
            "SELECT * FROM user_channels WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        )

    async def get_channel_by_id(self, user_id: int, channel_id: int) -> Optional[Dict]:
        """اسم بديل لـ get_channel_by_user"""
        return await self.fetchone(
            "SELECT * FROM user_channels WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        )

    async def delete_channel(self, user_id: int, channel_db_id: int) -> bool:
        """حذف قناة + تنظيف active_channel"""
        from database import internal_cache, CACHE_AVAILABLE
        from database import invalidate_user_cache, channels_cache

        try:
            async with self.transaction() as conn:
                deleted = await self._execute_with_conn(
                    conn, "DELETE FROM user_channels WHERE id = ? AND user_id = ?",
                    channel_db_id, user_id,
                )
                if deleted > 0:
                    await self._execute_with_conn(
                        conn,
                        "UPDATE users SET active_channel = NULL "
                        "WHERE user_id = ? AND active_channel = ?",
                        user_id, channel_db_id,
                    )
                    await internal_cache.invalidate(f"user_{user_id}")
                    await internal_cache.invalidate(f"channels_{user_id}")
                    await internal_cache.invalidate(f"channel_info_{channel_db_id}")
                    if CACHE_AVAILABLE:
                        await invalidate_user_cache(user_id)
                        await channels_cache.invalidate(user_id)
                    return True
                return False
        except Exception as e:
            logger.error(f"❌ Error in delete_channel: {e}", exc_info=True)
            return False

    async def is_channel_owner(self, user_id: int, channel_db_id: int) -> bool:
        """هل المستخدم مالك القناة؟"""
        result = await self.fetchval(
            "SELECT 1 FROM user_channels WHERE id = ? AND user_id = ?",
            (channel_db_id, user_id),
        )
        return result is not None

    async def count_user_posts(self, user_id: int, channel_db_id: int) -> int:
        """عدد منشورات القناة"""
        return await self.fetchval(
            "SELECT COUNT(*) FROM posts WHERE channel_db_id = ?",
            (channel_db_id,), default=0,
        )

    # ═════════════════════════════════════════════════════════════════
    #                    📝 دوال المنشورات (7 دوال)
    # ═════════════════════════════════════════════════════════════════

    async def add_posts(
        self, user_id: int, channel_db_id: int, posts: List[Tuple[str, str, str]]
    ) -> int:
        """
        إضافة منشورات للقناة.

        - إزالة التكرار المحلي (seen_local)
        - إزالة التكرار في DB (text_hash)
        - فحص حدود الباقة (max_posts)
        - إدراج بدفعات (batch_size)
        - منح نقاط تلقائية (عبر user_points)

        Returns:
            عدد المنشورات المُضافة فعلياً
        """
        from database import USE_POSTGRES, USE_MYSQL, TimeUtils
        from database import internal_cache, CACHE_AVAILABLE
        from database import invalidate_user_cache, posts_cache

        try:
            if not posts:
                return 0

            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    # ─── 1) فحص الملكية ───
                    row = await self._fetchone_with_conn(
                        conn,
                        "SELECT 1 FROM user_channels WHERE id = ? AND user_id = ? AND banned = 0",
                        channel_db_id, user_id,
                    )
                    if not row:
                        return 0

                    # ─── 2) فحص حدود الباقة ───
                    if USE_POSTGRES:
                        plan_row = await self._fetchone_with_conn(
                            conn,
                            """SELECT (SELECT max_posts FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                                      WHERE s.user_id = $1 AND s.status = 'active' AND s.end_date > $2
                                      ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1) as max_posts,
                                      (SELECT COUNT(*) FROM posts WHERE channel_db_id = $3 AND published = 0) as cnt""",
                            user_id, TimeUtils.utc_now(), channel_db_id,
                        )
                    elif USE_MYSQL:
                        plan_row = await self._fetchone_with_conn(
                            conn,
                            """SELECT (SELECT max_posts FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                                      WHERE s.user_id = %s AND s.status = 'active' AND s.end_date > %s
                                      ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1) as max_posts,
                                      (SELECT COUNT(*) FROM posts WHERE channel_db_id = %s AND published = 0) as cnt""",
                            user_id, TimeUtils.sql_iso(), channel_db_id,
                        )
                    else:
                        plan_row = await self._fetchone_with_conn(
                            conn,
                            """SELECT (SELECT max_posts FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                                      WHERE s.user_id = ? AND s.status = 'active' AND s.end_date > ?
                                      ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1) as max_posts,
                                      (SELECT COUNT(*) FROM posts WHERE channel_db_id = ? AND published = 0) as cnt""",
                            user_id, TimeUtils.sql_iso(), channel_db_id,
                        )
                    if not plan_row:
                        return 0
                    max_posts = plan_row["max_posts"] or 0
                    current_count = plan_row["cnt"] or 0
                    has_text_hash = await self._ensure_text_hash_column(conn)

                    # ─── 3) إزالة التكرار المحلي ───
                    unique_posts = []
                    seen_local = set()
                    for t, m, f in posts:
                        text = t or ""
                        if self._max_post_text_length > 0:
                            text = text[: self._max_post_text_length]
                        key = (text, m or "", f or "")
                        if key not in seen_local:
                            seen_local.add(key)
                            unique_posts.append((text, m, f))

                    # ─── 4) إزالة التكرار في DB ───
                    final_posts = []
                    for t, m, f in unique_posts:
                        text_clean = (
                            (t or "")[:4096]
                            if self._max_post_text_length == 0
                            else (t or "")[: self._max_post_text_length]
                        )
                        media_type = m or ""
                        media_file_id = f or ""
                        if has_text_hash:
                            text_hash = self._compute_text_hash(text_clean)
                            exists = await self._fetchone_with_conn(
                                conn,
                                "SELECT 1 FROM posts WHERE channel_db_id = ? "
                                "AND text_hash = ? AND media_type = ? AND media_file_id = ? LIMIT 1",
                                channel_db_id, text_hash, media_type, media_file_id,
                            )
                        else:
                            exists = await self._fetchone_with_conn(
                                conn,
                                "SELECT 1 FROM posts WHERE channel_db_id = ? "
                                "AND text = ? AND media_type = ? AND media_file_id = ? LIMIT 1",
                                channel_db_id, text_clean, media_type, media_file_id,
                            )
                        if not exists:
                            final_posts.append((t, m, f))

                    if not final_posts:
                        return 0

                    # ─── 5) قص إذا تجاوز الحد ───
                    if current_count + len(final_posts) > max_posts:
                        allowed = max(0, max_posts - current_count)
                        if allowed == 0:
                            return 0
                        final_posts = final_posts[:allowed]

                    # ─── 6) إدراج بدفعات ───
                    total = 0
                    batch_size = self._posts_batch_size
                    for i in range(0, len(final_posts), batch_size):
                        batch = final_posts[i : i + batch_size]
                        vals = []
                        for t, m, f in batch:
                            text = t or ""
                            if self._max_post_text_length > 0:
                                text = text[: self._max_post_text_length]
                            if has_text_hash:
                                text_hash = self._compute_text_hash(text)
                                vals.append((
                                    channel_db_id, text, text_hash, m, f, TimeUtils.utc_now(),
                                ))
                            else:
                                vals.append((
                                    channel_db_id, text, m, f, TimeUtils.utc_now(),
                                ))

                        if has_text_hash:
                            inserted = await self._executemany_with_conn(
                                conn,
                                "INSERT INTO posts "
                                "(channel_db_id, text, text_hash, media_type, media_file_id, created_at) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                vals,
                            )
                        else:
                            inserted = await self._executemany_with_conn(
                                conn,
                                "INSERT INTO posts "
                                "(channel_db_id, text, media_type, media_file_id, created_at) "
                                "VALUES (?, ?, ?, ?, ?)",
                                vals,
                            )
                        total += inserted

                    # ─── 7) إبطال الكاش ───
                    if total > 0:
                        await internal_cache.invalidate(f"user_{user_id}")
                        await internal_cache.invalidate(f"channel_info_{channel_db_id}")
                        if CACHE_AVAILABLE:
                            await invalidate_user_cache(user_id)
                            await posts_cache.invalidate(channel_db_id)
                    return total
        except Exception as e:
            logger.error(f"❌ Error in add_posts: {e}", exc_info=True)
            return 0

    async def get_next_post(self, channel_db_id: int) -> Tuple[Optional[Dict], bool]:
        """
        جلب المنشور التالي للنشر.

        Returns:
            (post_dict, was_recycled):
            - post_dict: بيانات المنشور أو None
            - was_recycled: True إذا تم إعادة تدوير المنشورات
        """
        from database import CACHE_AVAILABLE, posts_cache

        async with await self._get_channel_lock(channel_db_id):
            # ─── 1) من الكاش ───
            if CACHE_AVAILABLE:
                cached = await posts_cache.get_next_post(channel_db_id)
                if cached:
                    return cached, False

            # ─── 2) من DB ───
            post_row = await self.fetchone(
                """SELECT p.id, p.text, p.media_type, p.media_file_id, p.fail_count
                   FROM posts p
                   JOIN user_channels uc ON p.channel_db_id = uc.id
                   WHERE p.channel_db_id = ? AND p.published = 0
                     AND (p.fail_count IS NULL OR p.fail_count < 3)
                     AND uc.banned = 0
                   ORDER BY p.fail_count ASC, p.created_at ASC LIMIT 1""",
                (channel_db_id,),
            )
            if post_row:
                if CACHE_AVAILABLE:
                    await posts_cache.set_next_post(channel_db_id, post_row)
                return post_row, False

            # ─── 3) فحص auto_recycle ───
            auto_recycle = await self.fetchval(
                """SELECT u.auto_recycle FROM users u
                   JOIN user_channels uc ON u.user_id = uc.user_id
                   WHERE uc.id = ?""",
                (channel_db_id,), default=1,
            )
            if auto_recycle != 1:
                return None, False

            # ─── 4) إعادة تدوير ───
            await self.execute(
                "UPDATE posts SET published = 0, published_at = NULL, fail_count = 0 "
                "WHERE channel_db_id = ? AND published = 1",
                (channel_db_id,),
            )

            post_row = await self.fetchone(
                """SELECT p.id, p.text, p.media_type, p.media_file_id, p.fail_count
                   FROM posts p
                   WHERE p.channel_db_id = ? AND p.published = 0
                   ORDER BY p.fail_count ASC, p.created_at ASC LIMIT 1""",
                (channel_db_id,),
            )
            if post_row:
                if CACHE_AVAILABLE:
                    await posts_cache.set_next_post(channel_db_id, post_row)
                return post_row, True
            return None, False

    async def mark_post_published(self, post_id: int) -> bool:
        """تعليم منشور كمنشور (published=1)"""
        from database import TimeUtils, CACHE_AVAILABLE, posts_cache

        result = await self.execute(
            "UPDATE posts SET published = 1, published_at = ?, fail_count = 0 WHERE id = ?",
            (TimeUtils.utc_now(), post_id),
        ) > 0
        if result and CACHE_AVAILABLE:
            await posts_cache.invalidate()
        return result

    async def increment_post_fail(self, post_id: int) -> bool:
        """زيادة عدّاد فشل المنشور"""
        return await self.execute(
            "UPDATE posts SET fail_count = fail_count + 1 WHERE id = ?",
            (post_id,),
        ) > 0

    async def delete_post(self, user_id: int, post_id: int, channel_db_id: int) -> bool:
        """حذف منشور (مع التحقق من الملكية)"""
        from database import internal_cache, CACHE_AVAILABLE
        from database import invalidate_user_cache, posts_cache

        exists = await self.fetchval(
            "SELECT 1 FROM user_channels WHERE id = ? AND user_id = ?",
            (channel_db_id, user_id),
        )
        if not exists:
            return False

        result = await self.execute(
            "DELETE FROM posts WHERE id = ? AND channel_db_id = ?",
            (post_id, channel_db_id),
        ) > 0

        if result:
            await internal_cache.invalidate(f"user_{user_id}")
            await internal_cache.invalidate(f"channel_info_{channel_db_id}")
            if CACHE_AVAILABLE:
                await invalidate_user_cache(user_id)
                await posts_cache.invalidate(channel_db_id)
        return result

    async def reset_posts(self, user_id: int, channel_db_id: int) -> int:
        """إعادة تعيين كل المنشورات (published=0, fail_count=0)"""
        from database import internal_cache, CACHE_AVAILABLE
        from database import invalidate_user_cache, posts_cache

        try:
            async with self.transaction() as conn:
                cursor = await conn.execute(
                    "SELECT 1 FROM user_channels WHERE id = ? AND user_id = ? AND banned = 0",
                    (channel_db_id, user_id),
                )
                if not await cursor.fetchone():
                    return 0

                await self._execute_with_conn(
                    conn,
                    "UPDATE posts SET published = 0, fail_count = 0 WHERE channel_db_id = ?",
                    channel_db_id,
                )
                count = await self._fetchval_with_conn(
                    conn,
                    "SELECT COUNT(*) FROM posts WHERE channel_db_id = ? AND published = 0",
                    channel_db_id, default=0,
                )

                await internal_cache.invalidate(f"user_{user_id}")
                await internal_cache.invalidate(f"channel_info_{channel_db_id}")
                if CACHE_AVAILABLE:
                    await invalidate_user_cache(user_id)
                    await posts_cache.invalidate(channel_db_id)
                return count
        except Exception as e:
            logger.error(f"❌ Error in reset_posts: {e}", exc_info=True)
            return 0

    async def get_user_posts(
        self, user_id: int, channel_db_id: int, limit: int = 10
    ) -> List[Dict]:
        """جلب آخر منشورات القناة"""
        from database import CACHE_AVAILABLE, posts_cache

        exists = await self.fetchval(
            "SELECT 1 FROM user_channels WHERE id = ? AND user_id = ?",
            (channel_db_id, user_id),
        )
        if not exists:
            return []

        if CACHE_AVAILABLE:
            cached = await posts_cache.get_posts(channel_db_id, limit)
            if cached is not None:
                return cached

        posts = await self.fetchall(
            """SELECT id, text, media_type, published, fail_count, created_at
               FROM posts WHERE channel_db_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (channel_db_id, limit),
        )
        if CACHE_AVAILABLE:
            await posts_cache.set_posts(channel_db_id, posts, limit)
        return posts