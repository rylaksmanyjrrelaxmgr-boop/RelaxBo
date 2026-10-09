#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
database_channels_posts.py - دوال القنوات والمنشورات (Mixin)
================================================================================
🆕 v7.5.28 (REVIEW-FIXES-2026):
    🔴 FIX-NEW-1: إضافة `add_post` (مفرد) — كانت مفقودة، وهذا سبب فشل
       حفظ منشور واحد من حالة ADDING_POSTS.
    🟡 FIX-NEW-2: `add_post` تُعيد post_id (int) عند النجاح، None عند الفشل.
    🟡 FIX-NEW-3: توثيق صريح لـ add_posts أنها للدفعات فقط.
    🟢 FIX-NEW-4: توحيد أسلوب الفحوصات.

🆕 v7.5.27 (SOFT-DELETE-CONSISTENCY):
    🔒 GAP-1..4: فحوصات removed_at IS NULL في add_posts/reset_posts/
                  delete_post/get_user_posts.

🆕 v7.5.26 (CACHE-RACE-FIXES):
    🎯 FIX-A: increment_post_fail — إبطال كاش القناة بعد كل فشل
    🎯 FIX-B: mark_post_published — إبطال كاش القناة بدل الكاش العام
    🎯 FIX-E: mark_post_published — UPDATE شرطي لمنع النشر المزدوج

🆕 v7.5.25 (PRECISION-FIXES):
    🔧 FIX-1..7: تفاصيل في الأسفل

🆕 v7.5.24 (DEVELOPER-BYPASS-FIX):
    🔴 DEV-FIX-1: add_channel — تجاوز فحص max_channels للمطور
    🔴 DEV-FIX-2: add_posts — تجاوز فحص max_posts للمطور

🆕 v7.5.23 (SOFT-DELETE-INTEGRATION)
================================================================================
"""

import random
import logging
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ChannelsPostsMixin:
    """
    Mixin يجمع دوال القنوات والمنشورات.
    """

    # ✅ v7.5.25 FIX-1: كاش على مستوى الـ instance (لا global)
    _removed_col_cache: Optional[bool] = None

    def _is_dev_user(self, user_id: int) -> bool:
        """
        ✅ v7.5.24 DEV-FIX: هل المستخدم مطور/مالك؟
        يُستخدم لتجاوز فحوصات الحدود (max_channels, max_posts).
        """
        try:
            cfg = getattr(self, "CONFIG", None)
            if cfg is None:
                return False
            fn = getattr(cfg, "is_developer", None)
            if callable(fn):
                return bool(fn(user_id))
            owner = getattr(cfg, "PRIMARY_OWNER_ID", 0) or 0
            devs = getattr(cfg, "DEVELOPER_IDS", ()) or ()
            return user_id == owner or user_id in devs
        except Exception as e:
            logger.debug(f"_is_dev_user: {e}")
            return False

    # ═════════════════════════════════════════════════════════════════
    #          ✅ v7.5.23: فحص وجود عمود removed_at (cached)
    # ═════════════════════════════════════════════════════════════════

    async def _has_removed_at_column(self) -> bool:
        cached = getattr(self, "_removed_col_cache", None)
        if cached is not None:
            return cached

        try:
            from database import USE_POSTGRES, USE_MYSQL

            if USE_POSTGRES:
                exists = await self.fetchval(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'user_channels' "
                    "AND column_name = 'removed_at' "
                    "AND table_schema = current_schema()"
                )
            elif USE_MYSQL:
                exists = await self.fetchval(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE TABLE_SCHEMA = DATABASE() "
                    "AND TABLE_NAME = 'user_channels' "
                    "AND COLUMN_NAME = 'removed_at'"
                )
            else:
                cursor = await self.execute(
                    "PRAGMA table_info(user_channels)"
                )
                try:
                    rows = await cursor.fetchall()
                    exists = any(
                        (r[1] if isinstance(r, tuple) else r.get('name'))
                        == 'removed_at'
                        for r in rows
                    )
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass

            self._removed_col_cache = bool(exists)
            if self._removed_col_cache:
                logger.info(
                    "✅ user_channels.removed_at موجود — "
                    "Soft Delete مُفعَّل"
                )
            else:
                logger.info(
                    "ℹ️ user_channels.removed_at غير موجود — "
                    "ترقية database_tables.py مطلوبة"
                )
            return self._removed_col_cache

        except Exception as e:
            logger.debug(f"_has_removed_at_column: {e}")
            self._removed_col_cache = False
            return False

    # ═════════════════════════════════════════════════════════════════
    #     ✅ v7.5.26: Helper لإبطال كاش القناة الخاصة بمنشور
    # ═════════════════════════════════════════════════════════════════

    async def _invalidate_post_cache(self, post_id: int) -> None:
        """
        ✅ v7.5.26 FIX-A/B: إبطال كاش القناة الخاصة بالمنشور فقط.
        """
        from database import CACHE_AVAILABLE, posts_cache

        if not CACHE_AVAILABLE:
            return

        try:
            channel_db_id = await self.fetchval(
                "SELECT channel_db_id FROM posts WHERE id = ?",
                (post_id,),
            )
            if channel_db_id is not None:
                try:
                    await posts_cache.invalidate(channel_db_id)
                except TypeError:
                    await posts_cache.invalidate()
            else:
                await posts_cache.invalidate()
        except Exception as e:
            logger.debug(
                f"_invalidate_post_cache({post_id}): "
                f"{type(e).__name__}: {e}"
            )

    # ═════════════════════════════════════════════════════════════════
    #                    🎬 دوال القنوات
    # ═════════════════════════════════════════════════════════════════

    async def add_channel(
        self, user_id: int, channel_id: int, channel_name: str,
        set_active: bool = True
    ) -> Optional[Dict]:
        """
        إضافة قناة جديدة.

        ✅ v7.5.24 DEV-FIX-1: تجاوز فحص max_channels للمطور/المالك.

        Returns:
            dict: {id, channel_id, channel_name, posts_count}
            None: في حال الفشل
        """
        from database import USE_POSTGRES, USE_MYSQL, TimeUtils
        from database import internal_cache, CACHE_AVAILABLE
        from database import invalidate_user_cache, channels_cache

        try:
            channel_id = int(channel_id)
            is_dev = self._is_dev_user(user_id)

            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    # ─── 1) فحص حدود الباقة ───
                    if not is_dev:
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
                                f"⚠️ المستخدم {user_id} تجاوز الحد "
                                f"الأقصى للقنوات ({max_channels})"
                            )
                            return None

                    # ─── 2) إدراج أو تحديث القناة ───
                    # 📝 ملاحظة مقصودة: لا فلترة removed_at هنا —
                    #    نُريد إيجاد القناة المُزالة لاسترجاعها.
                    existing = await self._fetchone_with_conn(
                        conn,
                        "SELECT id FROM user_channels "
                        "WHERE user_id = ? AND channel_id = ?",
                        user_id, channel_id,
                    )
                    if existing:
                        ch_db_id = existing["id"]
                        if await self._has_removed_at_column():
                            await self._execute_with_conn(
                                conn,
                                "UPDATE user_channels "
                                "SET channel_name = ?, banned = 0, "
                                "    removed_at = NULL, "
                                "    removal_reason = NULL "
                                "WHERE id = ?",
                                channel_name, ch_db_id,
                            )
                            logger.info(
                                f"♻️ استرجاع القناة {ch_db_id} "
                                f"(user={user_id}, ch_id={channel_id})"
                            )
                        else:
                            await self._execute_with_conn(
                                conn,
                                "UPDATE user_channels "
                                "SET channel_name = ?, banned = 0 "
                                "WHERE id = ?",
                                channel_name, ch_db_id,
                            )
                        is_new = False
                    else:
                        if USE_POSTGRES:
                            row = await self._fetchone_with_conn(
                                conn,
                                "INSERT INTO user_channels "
                                "(user_id, channel_id, channel_name, created_at) "
                                "VALUES ($1, $2, $3, $4) RETURNING id",
                                user_id, channel_id, channel_name,
                                TimeUtils.utc_now(),
                            )
                            ch_db_id = row["id"]
                        elif USE_MYSQL:
                            cursor = await conn.cursor()
                            await cursor.execute(
                                "INSERT INTO user_channels "
                                "(user_id, channel_id, channel_name, created_at) "
                                "VALUES (%s, %s, %s, %s)",
                                (user_id, channel_id, channel_name,
                                 TimeUtils.sql_iso()),
                            )
                            ch_db_id = cursor.lastrowid
                            await cursor.close()
                        else:
                            cursor = await conn.execute(
                                "INSERT INTO user_channels "
                                "(user_id, channel_id, channel_name, created_at) "
                                "VALUES (?,?,?,?)",
                                (user_id, channel_id, channel_name,
                                 TimeUtils.sql_iso()),
                            )
                            ch_db_id = cursor.lastrowid
                        is_new = True

                    # ─── 3) تعيين القناة النشطة ───
                    if set_active:
                        await self._execute_with_conn(
                            conn,
                            "UPDATE users SET active_channel = ? "
                            "WHERE user_id = ?",
                            ch_db_id, user_id,
                        )

                    # ─── 4) إعداد الجدولة ───
                    delay_seconds = random.randint(5, 30) + (user_id % 10)
                    next_publish = (
                        TimeUtils.utc_now()
                        + timedelta(seconds=delay_seconds)
                    )

                    if USE_POSTGRES:
                        await self._execute_with_conn(
                            conn,
                            """INSERT INTO schedule
                               (channel_db_id, schedule_type,
                                interval_minutes, next_publish_date)
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
                            """INSERT INTO schedule
                               (channel_db_id, schedule_type,
                                interval_minutes, next_publish_date)
                               VALUES (%s, 'interval_minutes', 12, %s)
                               ON DUPLICATE KEY UPDATE
                                   schedule_type = VALUES(schedule_type),
                                   interval_minutes = VALUES(interval_minutes),
                                   next_publish_date = VALUES(next_publish_date)""",
                            ch_db_id,
                            next_publish.strftime("%Y-%m-%d %H:%M:%S"),
                        )
                    else:
                        await self._execute_with_conn(
                            conn,
                            """INSERT INTO schedule
                               (channel_db_id, schedule_type,
                                interval_minutes, next_publish_date)
                               VALUES (?, 'interval_minutes', 12, ?)
                               ON CONFLICT(channel_db_id) DO UPDATE SET
                                   schedule_type = excluded.schedule_type,
                                   interval_minutes = excluded.interval_minutes,
                                   next_publish_date = excluded.next_publish_date""",
                            ch_db_id,
                            next_publish.strftime("%Y-%m-%d %H:%M:%S"),
                        )

                    # ─── 5) last_publish ───
                    if USE_POSTGRES:
                        await self._execute_with_conn(
                            conn,
                            "INSERT INTO last_publish "
                            "(channel_db_id, last_publish_time) "
                            "VALUES ($1, $2) "
                            "ON CONFLICT (channel_db_id) DO NOTHING",
                            ch_db_id, next_publish,
                        )
                    elif USE_MYSQL:
                        await self._execute_with_conn(
                            conn,
                            "INSERT IGNORE INTO last_publish "
                            "(channel_db_id, last_publish_time) "
                            "VALUES (%s, %s)",
                            ch_db_id,
                            next_publish.strftime("%Y-%m-%d %H:%M:%S"),
                        )
                    else:
                        await self._execute_with_conn(
                            conn,
                            "INSERT OR IGNORE INTO last_publish "
                            "(channel_db_id, last_publish_time) "
                            "VALUES (?, ?)",
                            ch_db_id,
                            next_publish.strftime("%Y-%m-%d %H:%M:%S"),
                        )

                    # ─── 6) منح نقاط ───
                    if is_new:
                        if USE_POSTGRES:
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO user_points "
                                "(user_id, points, last_updated) "
                                "VALUES ($1, 10, $2) "
                                "ON CONFLICT (user_id) DO UPDATE SET "
                                "points = user_points.points + 10, "
                                "last_updated = $2",
                                user_id, TimeUtils.utc_now(),
                            )
                        elif USE_MYSQL:
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO user_points "
                                "(user_id, points, last_updated) "
                                "VALUES (%s, 10, %s) "
                                "ON DUPLICATE KEY UPDATE "
                                "points = points + 10, last_updated = %s",
                                user_id, TimeUtils.sql_iso(),
                                TimeUtils.sql_iso(),
                            )
                        else:
                            await self._execute_with_conn(
                                conn,
                                "INSERT INTO user_points "
                                "(user_id, points, last_updated) "
                                "VALUES (?,10,?) "
                                "ON CONFLICT(user_id) DO UPDATE SET "
                                "points = points + 10, last_updated = ?",
                                user_id, TimeUtils.sql_iso(),
                                TimeUtils.sql_iso(),
                            )

                    # ─── 7) عدد المنشورات ───
                    posts_count = await self._fetchval_with_conn(
                        conn,
                        "SELECT COUNT(*) FROM posts "
                        "WHERE channel_db_id = ? AND published = 0",
                        ch_db_id, default=0,
                    )

                    # ─── 8) إبطال الكاش ───
                    await internal_cache.invalidate(f"user_{user_id}")
                    await internal_cache.invalidate(
                        f"channel_info_{ch_db_id}"
                    )
                    await internal_cache.invalidate(
                        f"start_data_{user_id}"
                    )
                    if CACHE_AVAILABLE:
                        await invalidate_user_cache(user_id)
                        await channels_cache.invalidate(user_id)

                    return {
                        "id": ch_db_id,
                        "channel_id": channel_id,
                        "channel_name": channel_name,
                        "posts_count": posts_count,
                    }
        except Exception as e:
            logger.error(
                f"❌ Error in add_channel: {e}", exc_info=True
            )
            return None

    async def get_active_channel(self, user_id: int) -> Optional[int]:
        has_removed = await self._has_removed_at_column()

        result = await self.fetchval(
            "SELECT active_channel FROM users WHERE user_id = ?",
            (user_id,),
        )
        if result:
            if has_removed:
                banned = await self.fetchval(
                    "SELECT banned FROM user_channels "
                    "WHERE id = ? AND user_id = ? "
                    "AND removed_at IS NULL",
                    (result, user_id), default=1,
                )
            else:
                banned = await self.fetchval(
                    "SELECT banned FROM user_channels "
                    "WHERE id = ? AND user_id = ?",
                    (result, user_id), default=1,
                )
            if banned == 0:
                return result

        if has_removed:
            return await self.fetchval(
                "SELECT id FROM user_channels "
                "WHERE user_id = ? AND banned = 0 "
                "AND removed_at IS NULL "
                "ORDER BY id LIMIT 1",
                (user_id,),
            )
        return await self.fetchval(
            "SELECT id FROM user_channels "
            "WHERE user_id = ? AND banned = 0 ORDER BY id LIMIT 1",
            (user_id,),
        )

    async def set_active_channel(
        self, user_id: int, channel_db_id: int
    ) -> bool:
        from database import internal_cache, CACHE_AVAILABLE
        from database import invalidate_user_cache, channels_cache

        if await self._has_removed_at_column():
            exists = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id = ? AND user_id = ? AND banned = 0 "
                "AND removed_at IS NULL",
                (channel_db_id, user_id),
            )
        else:
            exists = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id = ? AND user_id = ? AND banned = 0",
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
            await internal_cache.invalidate(
                f"channel_info_{channel_db_id}"
            )
            await internal_cache.invalidate(f"start_data_{user_id}")
            if CACHE_AVAILABLE:
                await invalidate_user_cache(user_id)
                await channels_cache.invalidate(user_id)
        return result

    async def get_user_channels(self, user_id: int) -> List[Dict]:
        from database import internal_cache, CACHE_AVAILABLE
        from database import channels_cache

        if CACHE_AVAILABLE:
            cached = await channels_cache.get(user_id)
            if cached is not None:
                return cached
        cached = await internal_cache.get(f"channels_{user_id}")
        if cached is not None:
            return cached

        if await self._has_removed_at_column():
            channels = await self.fetchall(
                "SELECT id, channel_id, channel_name, banned, created_at "
                "FROM user_channels WHERE user_id = ? "
                "AND removed_at IS NULL "
                "ORDER BY created_at DESC",
                (user_id,),
            )
        else:
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

    async def get_channel_info(
        self, user_id: int, channel_db_id: int
    ) -> Optional[Dict]:
        from database import internal_cache, CACHE_AVAILABLE
        from database import channels_cache

        if CACHE_AVAILABLE:
            cached = await channels_cache.get_channel_info(channel_db_id)
            if cached is not None:
                return cached
        cached = await internal_cache.get(
            f"channel_info_{channel_db_id}"
        )
        if cached is not None:
            return cached

        if await self._has_removed_at_column():
            result = await self.fetchone(
                "SELECT * FROM user_channels "
                "WHERE id = ? AND user_id = ? AND removed_at IS NULL",
                (channel_db_id, user_id),
            )
        else:
            result = await self.fetchone(
                "SELECT * FROM user_channels "
                "WHERE id = ? AND user_id = ?",
                (channel_db_id, user_id),
            )

        if result:
            await internal_cache.set(
                f"channel_info_{channel_db_id}", result
            )
            if CACHE_AVAILABLE:
                await channels_cache.set_channel_info(
                    channel_db_id, result
                )
        return result

    async def get_channel_stats(
        self, user_id: int, channel_db_id: int
    ) -> Dict:
        # ✅ v7.5.25 FIX-3: احترام removed_at
        if await self._has_removed_at_column():
            exists = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id = ? AND user_id = ? AND removed_at IS NULL",
                (channel_db_id, user_id),
            )
        else:
            exists = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id = ? AND user_id = ?",
                (channel_db_id, user_id),
            )
        if not exists:
            return {"total": 0, "published": 0, "unpublished": 0}

        total = await self.fetchval(
            "SELECT COUNT(*) FROM posts WHERE channel_db_id = ?",
            (channel_db_id,), default=0,
        )
        published = await self.fetchval(
            "SELECT COUNT(*) FROM posts "
            "WHERE channel_db_id = ? AND published = 1",
            (channel_db_id,), default=0,
        )
        return {
            "total": total,
            "published": published,
            "unpublished": total - published,
        }

    async def get_unpublished_posts_count(
        self, user_id: int, channel_db_id: int
    ) -> int:
        if await self._has_removed_at_column():
            owner = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id=? AND user_id=? AND removed_at IS NULL",
                (channel_db_id, user_id), default=0,
            )
        else:
            owner = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id=? AND user_id=?",
                (channel_db_id, user_id), default=0,
            )
        if not owner:
            return 0
        return await self.fetchval(
            "SELECT COUNT(*) FROM posts "
            "WHERE channel_db_id=? AND published=0",
            (channel_db_id,), default=0,
        )

    async def get_channel_by_user(
        self, user_id: int, channel_id: int
    ) -> Optional[Dict]:
        """
        جلب قناة عبر Telegram channel_id (المُعرّف الرقمي للقناة).

        ⚠️ v7.5.27: لا تُفلتر removed_at بشكل مقصود — لأن هذه الدالة
        تُستخدم في منطق الاسترجاع (add_channel).
        """
        return await self.fetchone(
            "SELECT * FROM user_channels "
            "WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        )

    async def get_channel_by_id(
        self, user_id: int, channel_id: int
    ) -> Optional[Dict]:
        """
        ✅ v7.5.25 FIX-7: alias فعلي لـ get_channel_by_user.
        """
        return await self.fetchone(
            "SELECT * FROM user_channels "
            "WHERE user_id = ? AND channel_id = ?",
            (user_id, channel_id),
        )

    async def delete_channel(
        self, user_id: int, channel_db_id: int
    ) -> bool:
        from database import internal_cache, CACHE_AVAILABLE
        from database import invalidate_user_cache, channels_cache
        from database import posts_cache

        try:
            async with self.transaction() as conn:
                current_active = await self._fetchval_with_conn(
                    conn,
                    "SELECT active_channel FROM users "
                    "WHERE user_id = ?",
                    user_id,
                )
                was_active = False
                if current_active is not None:
                    try:
                        was_active = (
                            int(current_active) == int(channel_db_id)
                        )
                    except (TypeError, ValueError):
                        was_active = False

                deleted = await self._execute_with_conn(
                    conn,
                    "DELETE FROM user_channels "
                    "WHERE id = ? AND user_id = ?",
                    channel_db_id, user_id,
                )
                if deleted <= 0:
                    return False

                # ✅ v7.5.25 FIX-2: تنظيف صريح للجداول المرتبطة
                try:
                    await self._execute_with_conn(
                        conn,
                        "DELETE FROM schedule WHERE channel_db_id = ?",
                        channel_db_id,
                    )
                except Exception as _e:
                    logger.debug(
                        f"delete_channel: تنظيف schedule فشل "
                        f"(محتمل CASCADE): {_e}"
                    )
                try:
                    await self._execute_with_conn(
                        conn,
                        "DELETE FROM last_publish WHERE channel_db_id = ?",
                        channel_db_id,
                    )
                except Exception as _e:
                    logger.debug(
                        f"delete_channel: تنظيف last_publish فشل "
                        f"(محتمل CASCADE): {_e}"
                    )
                try:
                    await self._execute_with_conn(
                        conn,
                        "DELETE FROM posts WHERE channel_db_id = ?",
                        channel_db_id,
                    )
                except Exception as _e:
                    logger.debug(
                        f"delete_channel: تنظيف posts فشل "
                        f"(محتمل CASCADE): {_e}"
                    )

                if was_active:
                    if await self._has_removed_at_column():
                        next_row = await self._fetchone_with_conn(
                            conn,
                            "SELECT id, channel_name FROM user_channels "
                            "WHERE user_id = ? AND banned = 0 "
                            "AND removed_at IS NULL "
                            "ORDER BY created_at DESC LIMIT 1",
                            user_id,
                        )
                    else:
                        next_row = await self._fetchone_with_conn(
                            conn,
                            "SELECT id, channel_name FROM user_channels "
                            "WHERE user_id = ? AND banned = 0 "
                            "ORDER BY created_at DESC LIMIT 1",
                            user_id,
                        )
                    new_active_id = (
                        next_row["id"] if next_row else None
                    )

                    await self._execute_with_conn(
                        conn,
                        "UPDATE users SET active_channel = ? "
                        "WHERE user_id = ?",
                        new_active_id, user_id,
                    )

                    if new_active_id:
                        new_name = (
                            next_row.get("channel_name")
                            if isinstance(next_row, dict)
                            else None
                        ) or f"#{new_active_id}"
                        logger.info(
                            f"🔄 المستخدم {user_id}: حذف القناة "
                            f"النشطة {channel_db_id} → تحويل "
                            f"تلقائي إلى '{new_name}' "
                            f"(id={new_active_id})"
                        )
                    else:
                        logger.info(
                            f"🔄 المستخدم {user_id}: حذف آخر "
                            f"قناة نشطة → active_channel = NULL"
                        )
                else:
                    await self._execute_with_conn(
                        conn,
                        "UPDATE users SET active_channel = NULL "
                        "WHERE user_id = ? AND active_channel = ?",
                        user_id, channel_db_id,
                    )

                await internal_cache.invalidate(f"user_{user_id}")
                await internal_cache.invalidate(f"channels_{user_id}")
                await internal_cache.invalidate(
                    f"channel_info_{channel_db_id}"
                )
                await internal_cache.invalidate(
                    f"start_data_{user_id}"
                )
                await internal_cache.invalidate(f"user_{user_id}_True")
                await internal_cache.invalidate(f"user_{user_id}_False")

                if CACHE_AVAILABLE:
                    await invalidate_user_cache(user_id)
                    await channels_cache.invalidate(user_id)
                    try:
                        await posts_cache.invalidate(channel_db_id)
                    except Exception:
                        pass

                return True
        except Exception as e:
            logger.error(
                f"❌ Error in delete_channel: {e}", exc_info=True
            )
            return False

    # ═════════════════════════════════════════════════════════════════
    #          ✅ v7.5.23: دوال Soft Delete
    # ═════════════════════════════════════════════════════════════════

    async def soft_delete_channel(
        self, channel_db_id: int, reason: str = "unknown",
    ) -> bool:
        if not await self._has_removed_at_column():
            logger.warning(
                "⚠️ soft_delete_channel: العمود removed_at غير موجود"
            )
            return False

        if not channel_db_id:
            return False

        try:
            from database import TimeUtils

            result = await self.execute(
                "UPDATE user_channels "
                "SET removed_at = ?, removal_reason = ? "
                "WHERE id = ? AND removed_at IS NULL",
                (TimeUtils.utc_now(), reason, channel_db_id),
            )

            if isinstance(result, int) and result > 0:
                logger.info(
                    f"📌 Soft delete: القناة {channel_db_id} "
                    f"(reason={reason})"
                )
                return True

            return False

        except Exception as e:
            logger.error(
                f"❌ soft_delete_channel({channel_db_id}): "
                f"{type(e).__name__}: {e}"
            )
            return False

    async def restore_channel(self, channel_db_id: int) -> bool:
        if not await self._has_removed_at_column():
            return False

        if not channel_db_id:
            return False

        try:
            result = await self.execute(
                "UPDATE user_channels "
                "SET removed_at = NULL, removal_reason = NULL "
                "WHERE id = ? AND removed_at IS NOT NULL",
                (channel_db_id,),
            )

            if isinstance(result, int) and result > 0:
                logger.info(
                    f"♻️ استُرجعت القناة {channel_db_id}"
                )
                return True

            return False

        except Exception as e:
            logger.error(
                f"❌ restore_channel({channel_db_id}): "
                f"{type(e).__name__}: {e}"
            )
            return False

    async def get_removed_channels(
        self, user_id: int, limit: int = 50
    ) -> List[Dict]:
        if not await self._has_removed_at_column():
            return []

        try:
            return await self.fetchall(
                "SELECT id, channel_id, channel_name, "
                "       removed_at, removal_reason "
                "FROM user_channels "
                "WHERE user_id = ? AND removed_at IS NOT NULL "
                "ORDER BY removed_at DESC LIMIT ?",
                (user_id, limit),
            )
        except Exception as e:
            logger.error(f"❌ get_removed_channels: {e}")
            return []

    async def hard_delete_removed_channels_before(
        self, cutoff_dt
    ) -> int:
        if not await self._has_removed_at_column():
            return 0

        try:
            result = await self.execute(
                "DELETE FROM user_channels "
                "WHERE removed_at IS NOT NULL "
                "AND removed_at < ?",
                (cutoff_dt,),
            )

            if isinstance(result, int) and result > 0:
                logger.info(
                    f"🧹 حذف نهائي: {result} قناة مهجورة "
                    f"(مُزالة قبل {cutoff_dt})"
                )
                return result
            return 0

        except Exception as e:
            logger.error(
                f"❌ hard_delete_removed_channels_before: {e}",
                exc_info=True,
            )
            return 0

    async def is_channel_owner(
        self, user_id: int, channel_db_id: int
    ) -> bool:
        if await self._has_removed_at_column():
            result = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id = ? AND user_id = ? "
                "AND removed_at IS NULL",
                (channel_db_id, user_id),
            )
        else:
            result = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id = ? AND user_id = ?",
                (channel_db_id, user_id),
            )
        return result is not None

    async def count_user_posts(
        self, user_id: int, channel_db_id: int
    ) -> int:
        """
        عدد منشورات القناة (مع فحص الملكية).
        ✅ v7.5.25 FIX-4: كانت user_id مُهمَلة تماماً.
        """
        if await self._has_removed_at_column():
            owner = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id = ? AND user_id = ? "
                "AND removed_at IS NULL",
                (channel_db_id, user_id), default=0,
            )
        else:
            owner = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id = ? AND user_id = ?",
                (channel_db_id, user_id), default=0,
            )
        if not owner:
            return 0
        return await self.fetchval(
            "SELECT COUNT(*) FROM posts WHERE channel_db_id = ?",
            (channel_db_id,), default=0,
        )

    # ═════════════════════════════════════════════════════════════════
    #                    📝 دوال المنشورات
    # ═════════════════════════════════════════════════════════════════

    # 🆕 v7.5.28 FIX-NEW-1 + FIX-NEW-2: دالة حفظ منشور واحد
    async def add_post(
        self,
        user_id: int,
        channel_db_id: int,
        text: str = "",
        media_type: Optional[str] = None,
        media_file_id: Optional[str] = None,
    ) -> Optional[int]:
        """
        🆕 v7.5.28 FIX-NEW-1: إضافة منشور واحد.

        كانت مفقودة — ولهذا فشل معالج ADDING_POSTS في العثور على دالة
        لحفظ منشور واحد.

        Args:
            user_id: معرّف المستخدم (المالك)
            channel_db_id: معرّف القناة الداخلي (user_channels.id)
            text: نص المنشور
            media_type: نوع الوسيط (photo/video/document/voice/audio/animation)
            media_file_id: معرّف الملف في تلغرام

        Returns:
            post_id (int) عند النجاح
            None عند الفشل (لا ملكية، لا اشتراك، حد أقصى، تكرار...)
        """
        from database import USE_POSTGRES, USE_MYSQL, TimeUtils
        from database import internal_cache, CACHE_AVAILABLE
        from database import invalidate_user_cache, posts_cache
        from database import channels_cache

        try:
            # ─── تطبيع ───
            text = text or ""
            if self._max_post_text_length > 0:
                text = text[: self._max_post_text_length]
            else:
                text = text[:4096]

            media_type = media_type or ""
            media_file_id = media_file_id or ""

            # ─── التحقق من وجود محتوى ───
            if not text and not media_file_id:
                logger.debug(
                    f"add_post: لا نص ولا وسائط "
                    f"(user={user_id}, ch={channel_db_id})"
                )
                return None

            is_dev = self._is_dev_user(user_id)
            has_removed = await self._has_removed_at_column()

            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    # ─── 1) فحص الملكية ───
                    if has_removed:
                        row = await self._fetchone_with_conn(
                            conn,
                            "SELECT 1 FROM user_channels "
                            "WHERE id = ? AND user_id = ? "
                            "AND banned = 0 AND removed_at IS NULL",
                            channel_db_id, user_id,
                        )
                    else:
                        row = await self._fetchone_with_conn(
                            conn,
                            "SELECT 1 FROM user_channels "
                            "WHERE id = ? AND user_id = ? AND banned = 0",
                            channel_db_id, user_id,
                        )
                    if not row:
                        logger.debug(
                            f"add_post: القناة {channel_db_id} "
                            f"غير متاحة للمستخدم {user_id}"
                        )
                        return None

                    # ─── 2) فحص الحد الأقصى ───
                    if is_dev:
                        max_posts = 10**9
                    else:
                        if USE_POSTGRES:
                            plan_row = await self._fetchone_with_conn(
                                conn,
                                """SELECT (SELECT max_posts FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                                          WHERE s.user_id = $1 AND s.status = 'active' AND s.end_date > $2
                                          ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1) as max_posts,
                                          (SELECT COUNT(*) FROM posts WHERE channel_db_id = $3 AND published = 0) as cnt""",
                                user_id, TimeUtils.utc_now(),
                                channel_db_id,
                            )
                        elif USE_MYSQL:
                            plan_row = await self._fetchone_with_conn(
                                conn,
                                """SELECT (SELECT max_posts FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                                          WHERE s.user_id = %s AND s.status = 'active' AND s.end_date > %s
                                          ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1) as max_posts,
                                          (SELECT COUNT(*) FROM posts WHERE channel_db_id = %s AND published = 0) as cnt""",
                                user_id, TimeUtils.sql_iso(),
                                channel_db_id,
                            )
                        else:
                            plan_row = await self._fetchone_with_conn(
                                conn,
                                """SELECT (SELECT max_posts FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                                          WHERE s.user_id = ? AND s.status = 'active' AND s.end_date > ?
                                          ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1) as max_posts,
                                          (SELECT COUNT(*) FROM posts WHERE channel_db_id = ? AND published = 0) as cnt""",
                                user_id, TimeUtils.sql_iso(),
                                channel_db_id,
                            )
                        if not plan_row:
                            return None
                        max_posts = plan_row["max_posts"] or 0
                        current_count = plan_row["cnt"] or 0
                        if current_count >= max_posts:
                            logger.warning(
                                f"⚠️ add_post: المستخدم {user_id} "
                                f"وصل الحد الأقصى للمنشورات "
                                f"({current_count}/{max_posts})"
                            )
                            return None

                    # ─── 3) فحص وجود text_hash ───
                    has_text_hash = await self._ensure_text_hash_column(
                        conn
                    )

                    # ─── 4) فحص التكرار ───
                    if has_text_hash:
                        text_hash = self._compute_text_hash(text)
                        exists = await self._fetchone_with_conn(
                            conn,
                            "SELECT 1 FROM posts "
                            "WHERE channel_db_id = ? "
                            "AND text_hash = ? "
                            "AND media_type = ? "
                            "AND media_file_id = ? LIMIT 1",
                            channel_db_id, text_hash,
                            media_type, media_file_id,
                        )
                    else:
                        exists = await self._fetchone_with_conn(
                            conn,
                            "SELECT 1 FROM posts "
                            "WHERE channel_db_id = ? "
                            "AND text = ? "
                            "AND media_type = ? "
                            "AND media_file_id = ? LIMIT 1",
                            channel_db_id, text,
                            media_type, media_file_id,
                        )
                    if exists:
                        logger.info(
                            f"ℹ️ add_post: منشور مكرر "
                            f"(ch={channel_db_id}, text_len={len(text)})"
                        )
                        return None

                    # ─── 5) INSERT (مع RETURNING id) ───
                    post_id: Optional[int] = None
                    now = TimeUtils.utc_now()

                    if USE_POSTGRES:
                        if has_text_hash:
                            row = await self._fetchone_with_conn(
                                conn,
                                "INSERT INTO posts "
                                "(channel_db_id, text, text_hash, "
                                "media_type, media_file_id, created_at) "
                                "VALUES ($1, $2, $3, $4, $5, $6) "
                                "RETURNING id",
                                channel_db_id, text, text_hash,
                                media_type, media_file_id, now,
                            )
                        else:
                            row = await self._fetchone_with_conn(
                                conn,
                                "INSERT INTO posts "
                                "(channel_db_id, text, "
                                "media_type, media_file_id, created_at) "
                                "VALUES ($1, $2, $3, $4, $5) "
                                "RETURNING id",
                                channel_db_id, text,
                                media_type, media_file_id, now,
                            )
                        post_id = row["id"] if row else None

                    elif USE_MYSQL:
                        cursor = await conn.cursor()
                        try:
                            if has_text_hash:
                                await cursor.execute(
                                    "INSERT INTO posts "
                                    "(channel_db_id, text, text_hash, "
                                    "media_type, media_file_id, created_at) "
                                    "VALUES (%s, %s, %s, %s, %s, %s)",
                                    (channel_db_id, text, text_hash,
                                     media_type, media_file_id,
                                     now.strftime("%Y-%m-%d %H:%M:%S")),
                                )
                            else:
                                await cursor.execute(
                                    "INSERT INTO posts "
                                    "(channel_db_id, text, "
                                    "media_type, media_file_id, created_at) "
                                    "VALUES (%s, %s, %s, %s, %s)",
                                    (channel_db_id, text,
                                     media_type, media_file_id,
                                     now.strftime("%Y-%m-%d %H:%M:%S")),
                                )
                            post_id = cursor.lastrowid
                        finally:
                            await cursor.close()

                    else:
                        # SQLite
                        if has_text_hash:
                            cursor = await conn.execute(
                                "INSERT INTO posts "
                                "(channel_db_id, text, text_hash, "
                                "media_type, media_file_id, created_at) "
                                "VALUES (?,?,?,?,?,?)",
                                (channel_db_id, text, text_hash,
                                 media_type, media_file_id,
                                 now.strftime("%Y-%m-%d %H:%M:%S")),
                            )
                        else:
                            cursor = await conn.execute(
                                "INSERT INTO posts "
                                "(channel_db_id, text, "
                                "media_type, media_file_id, created_at) "
                                "VALUES (?,?,?,?,?)",
                                (channel_db_id, text,
                                 media_type, media_file_id,
                                 now.strftime("%Y-%m-%d %H:%M:%S")),
                            )
                        post_id = cursor.lastrowid

                    # ─── 6) إبطال الكاش ───
                    if post_id:
                        await internal_cache.invalidate(
                            f"user_{user_id}"
                        )
                        await internal_cache.invalidate(
                            f"channel_info_{channel_db_id}"
                        )
                        await internal_cache.invalidate(
                            f"start_data_{user_id}"
                        )
                        if CACHE_AVAILABLE:
                            await invalidate_user_cache(user_id)
                            try:
                                await posts_cache.invalidate(
                                    channel_db_id)
                            except Exception:
                                pass
                            try:
                                await channels_cache.invalidate(user_id)
                            except Exception:
                                pass

                    logger.info(
                        f"✅ add_post: post_id={post_id} "
                        f"(user={user_id}, ch={channel_db_id}, "
                        f"media={media_type or 'text'})"
                    )
                    return post_id

        except Exception as e:
            logger.error(
                f"❌ Error in add_post: {e}", exc_info=True
            )
            return None

    async def add_posts(
        self, user_id: int, channel_db_id: int,
        posts: List[Tuple[str, str, str]]
    ) -> int:
        """
        إضافة منشورات للقناة (دفعة).

        ⚠️ v7.5.28 FIX-NEW-3: هذه الدالة للدفعات فقط.
        لحفظ منشور واحد من معالج رسالة، استخدم add_post() (المفرد).

        ✅ v7.5.24 DEV-FIX-2: تجاوز فحص max_posts للمطور/المالك.
        ✅ v7.5.25 FIX-5: للمطور — current_count الحقيقي.
        ✅ v7.5.27 GAP-1: فحص removed_at IS NULL في الملكية.
        """
        from database import USE_POSTGRES, USE_MYSQL, TimeUtils
        from database import internal_cache, CACHE_AVAILABLE
        from database import invalidate_user_cache, posts_cache
        from database import channels_cache

        try:
            if not posts:
                return 0

            is_dev = self._is_dev_user(user_id)
            has_removed = await self._has_removed_at_column()

            async with await self._get_user_lock(user_id):
                async with self.transaction() as conn:
                    # ─── 1) فحص الملكية ───
                    # 🔒 v7.5.27 GAP-1: فلترة removed_at إن وُجد العمود
                    if has_removed:
                        row = await self._fetchone_with_conn(
                            conn,
                            "SELECT 1 FROM user_channels "
                            "WHERE id = ? AND user_id = ? "
                            "AND banned = 0 AND removed_at IS NULL",
                            channel_db_id, user_id,
                        )
                    else:
                        row = await self._fetchone_with_conn(
                            conn,
                            "SELECT 1 FROM user_channels "
                            "WHERE id = ? AND user_id = ? AND banned = 0",
                            channel_db_id, user_id,
                        )
                    if not row:
                        logger.debug(
                            f"add_posts: القناة {channel_db_id} "
                            f"غير متاحة للمستخدم {user_id} "
                            f"(ملكية/حظر/soft-delete)"
                        )
                        return 0

                    # ─── 2) فحص حدود الباقة ───
                    if is_dev:
                        max_posts = 10**9  # بلا حد
                        # ✅ v7.5.25 FIX-5: القيمة الحقيقية
                        current_count = await self._fetchval_with_conn(
                            conn,
                            "SELECT COUNT(*) FROM posts "
                            "WHERE channel_db_id = ? AND published = 0",
                            channel_db_id,
                            default=0,
                        )
                        has_text_hash = (
                            await self._ensure_text_hash_column(conn)
                        )
                    else:
                        if USE_POSTGRES:
                            plan_row = await self._fetchone_with_conn(
                                conn,
                                """SELECT (SELECT max_posts FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                                          WHERE s.user_id = $1 AND s.status = 'active' AND s.end_date > $2
                                          ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1) as max_posts,
                                          (SELECT COUNT(*) FROM posts WHERE channel_db_id = $3 AND published = 0) as cnt""",
                                user_id, TimeUtils.utc_now(),
                                channel_db_id,
                            )
                        elif USE_MYSQL:
                            plan_row = await self._fetchone_with_conn(
                                conn,
                                """SELECT (SELECT max_posts FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                                          WHERE s.user_id = %s AND s.status = 'active' AND s.end_date > %s
                                          ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1) as max_posts,
                                          (SELECT COUNT(*) FROM posts WHERE channel_db_id = %s AND published = 0) as cnt""",
                                user_id, TimeUtils.sql_iso(),
                                channel_db_id,
                            )
                        else:
                            plan_row = await self._fetchone_with_conn(
                                conn,
                                """SELECT (SELECT max_posts FROM subscriptions s JOIN plans p ON s.plan_id = p.id
                                          WHERE s.user_id = ? AND s.status = 'active' AND s.end_date > ?
                                          ORDER BY p.max_channels DESC, p.max_posts DESC, s.end_date DESC LIMIT 1) as max_posts,
                                          (SELECT COUNT(*) FROM posts WHERE channel_db_id = ? AND published = 0) as cnt""",
                                user_id, TimeUtils.sql_iso(),
                                channel_db_id,
                            )
                        if not plan_row:
                            return 0
                        max_posts = plan_row["max_posts"] or 0
                        current_count = plan_row["cnt"] or 0
                        has_text_hash = (
                            await self._ensure_text_hash_column(conn)
                        )

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
                                "SELECT 1 FROM posts "
                                "WHERE channel_db_id = ? "
                                "AND text_hash = ? "
                                "AND media_type = ? "
                                "AND media_file_id = ? LIMIT 1",
                                channel_db_id, text_hash,
                                media_type, media_file_id,
                            )
                        else:
                            exists = await self._fetchone_with_conn(
                                conn,
                                "SELECT 1 FROM posts "
                                "WHERE channel_db_id = ? "
                                "AND text = ? "
                                "AND media_type = ? "
                                "AND media_file_id = ? LIMIT 1",
                                channel_db_id, text_clean,
                                media_type, media_file_id,
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
                                text = text[
                                    : self._max_post_text_length
                                ]
                            if has_text_hash:
                                text_hash = self._compute_text_hash(
                                    text
                                )
                                vals.append((
                                    channel_db_id, text, text_hash,
                                    m, f, TimeUtils.utc_now(),
                                ))
                            else:
                                vals.append((
                                    channel_db_id, text,
                                    m, f, TimeUtils.utc_now(),
                                ))

                        if has_text_hash:
                            inserted = await self._executemany_with_conn(
                                conn,
                                "INSERT INTO posts "
                                "(channel_db_id, text, text_hash, "
                                "media_type, media_file_id, created_at) "
                                "VALUES (?, ?, ?, ?, ?, ?)",
                                vals,
                            )
                        else:
                            inserted = await self._executemany_with_conn(
                                conn,
                                "INSERT INTO posts "
                                "(channel_db_id, text, "
                                "media_type, media_file_id, created_at) "
                                "VALUES (?, ?, ?, ?, ?)",
                                vals,
                            )
                        total += inserted

                    # ─── 7) إبطال الكاش ───
                    if total > 0:
                        await internal_cache.invalidate(
                            f"user_{user_id}"
                        )
                        await internal_cache.invalidate(
                            f"channel_info_{channel_db_id}"
                        )
                        await internal_cache.invalidate(
                            f"start_data_{user_id}"
                        )
                        if CACHE_AVAILABLE:
                            await invalidate_user_cache(user_id)
                            await posts_cache.invalidate(channel_db_id)
                            await channels_cache.invalidate(user_id)
                    return total
        except Exception as e:
            logger.error(
                f"❌ Error in add_posts: {e}", exc_info=True
            )
            return 0

    async def get_next_post(
        self, channel_db_id: int
    ) -> Tuple[Optional[Dict], bool]:
        """
        جلب المنشور التالي للنشر.

        Returns:
            (post_dict, was_recycled)
        """
        from database import CACHE_AVAILABLE, posts_cache

        async with await self._get_channel_lock(channel_db_id):
            if CACHE_AVAILABLE:
                cached = await posts_cache.get_next_post(channel_db_id)
                if cached:
                    return cached, False

            post_row = await self.fetchone(
                """SELECT p.id, p.text, p.media_type,
                          p.media_file_id, p.fail_count
                   FROM posts p
                   WHERE p.channel_db_id = ? AND p.published = 0
                     AND (p.fail_count IS NULL OR p.fail_count < 3)
                   ORDER BY p.id ASC LIMIT 1""",
                (channel_db_id,),
            )
            if post_row:
                if CACHE_AVAILABLE:
                    await posts_cache.set_next_post(
                        channel_db_id, post_row
                    )
                return post_row, False

            # ✅ v7.5.25 FIX-6: default=0
            auto_recycle = await self.fetchval(
                """SELECT u.auto_recycle FROM users u
                   JOIN user_channels uc ON u.user_id = uc.user_id
                   WHERE uc.id = ?""",
                (channel_db_id,), default=0,
            )
            if auto_recycle != 1:
                return None, False

            await self.execute(
                "UPDATE posts SET published = 0, "
                "published_at = NULL, fail_count = 0 "
                "WHERE channel_db_id = ? AND published = 1",
                (channel_db_id,),
            )

            if CACHE_AVAILABLE:
                try:
                    await posts_cache.invalidate(channel_db_id)
                except TypeError:
                    await posts_cache.invalidate()

            post_row = await self.fetchone(
                """SELECT p.id, p.text, p.media_type,
                          p.media_file_id, p.fail_count
                   FROM posts p
                   WHERE p.channel_db_id = ? AND p.published = 0
                   ORDER BY p.id ASC LIMIT 1""",
                (channel_db_id,),
            )
            if post_row:
                if CACHE_AVAILABLE:
                    await posts_cache.set_next_post(
                        channel_db_id, post_row
                    )
                return post_row, True
            return None, False

    async def mark_post_published(self, post_id: int) -> bool:
        """
        وسم منشور كمنشور.

        ✅ v7.5.26 FIX-E: UPDATE شرطي (WHERE published = 0).
        ✅ v7.5.26 FIX-B: إبطال كاش القناة فقط.
        """
        from database import TimeUtils

        affected = await self.execute(
            "UPDATE posts SET published = 1, published_at = ?, "
            "fail_count = 0 WHERE id = ? AND published = 0",
            (TimeUtils.utc_now(), post_id),
        )

        if affected <= 0:
            exists = await self.fetchval(
                "SELECT 1 FROM posts WHERE id = ?",
                (post_id,),
            )
            if not exists:
                return False
            logger.debug(
                f"mark_post_published({post_id}): "
                f"already published (idempotent)"
            )

        await self._invalidate_post_cache(post_id)
        return True

    async def increment_post_fail(self, post_id: int) -> bool:
        """
        زيادة عدّاد فشل المنشور.
        ✅ v7.5.26 FIX-A: إبطال كاش القناة بعد الزيادة.
        """
        result = await self.execute(
            "UPDATE posts SET fail_count = fail_count + 1 "
            "WHERE id = ?",
            (post_id,),
        ) > 0

        if result:
            await self._invalidate_post_cache(post_id)

        return result

    async def delete_post(
        self, user_id: int, post_id: int, channel_db_id: int
    ) -> bool:
        """
        حذف منشور.
        ✅ v7.5.27 GAP-3: فحص removed_at IS NULL.
        """
        from database import internal_cache, CACHE_AVAILABLE
        from database import invalidate_user_cache, posts_cache
        from database import channels_cache

        if await self._has_removed_at_column():
            exists = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id = ? AND user_id = ? "
                "AND removed_at IS NULL",
                (channel_db_id, user_id),
            )
        else:
            exists = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id = ? AND user_id = ?",
                (channel_db_id, user_id),
            )
        if not exists:
            return False

        result = await self.execute(
            "DELETE FROM posts "
            "WHERE id = ? AND channel_db_id = ?",
            (post_id, channel_db_id),
        ) > 0

        if result:
            await internal_cache.invalidate(f"user_{user_id}")
            await internal_cache.invalidate(
                f"channel_info_{channel_db_id}"
            )
            await internal_cache.invalidate(
                f"start_data_{user_id}"
            )
            if CACHE_AVAILABLE:
                await invalidate_user_cache(user_id)
                await posts_cache.invalidate(channel_db_id)
                await channels_cache.invalidate(user_id)
        return result

    async def reset_posts(
        self, user_id: int, channel_db_id: int
    ) -> int:
        """
        إعادة تعيين كل منشورات القناة (published=0).
        ✅ v7.5.27 GAP-2: فحص removed_at IS NULL.
        """
        from database import internal_cache, CACHE_AVAILABLE
        from database import invalidate_user_cache, posts_cache
        from database import channels_cache

        try:
            async with self.transaction() as conn:
                if await self._has_removed_at_column():
                    owns = await self._fetchval_with_conn(
                        conn,
                        "SELECT 1 FROM user_channels "
                        "WHERE id = ? AND user_id = ? AND banned = 0 "
                        "AND removed_at IS NULL",
                        channel_db_id, user_id,
                    )
                else:
                    owns = await self._fetchval_with_conn(
                        conn,
                        "SELECT 1 FROM user_channels "
                        "WHERE id = ? AND user_id = ? AND banned = 0",
                        channel_db_id, user_id,
                    )
                if not owns:
                    logger.warning(
                        f"⚠️ reset_posts: المستخدم {user_id} "
                        f"لا يملك القناة {channel_db_id} "
                        f"(أو مُزالة/محظورة)"
                    )
                    return 0

                await self._execute_with_conn(
                    conn,
                    "UPDATE posts SET published = 0, fail_count = 0 "
                    "WHERE channel_db_id = ?",
                    channel_db_id,
                )

                count = await self._fetchval_with_conn(
                    conn,
                    "SELECT COUNT(*) FROM posts "
                    "WHERE channel_db_id = ? AND published = 0",
                    channel_db_id,
                    default=0,
                )

                await internal_cache.invalidate(f"user_{user_id}")
                await internal_cache.invalidate(
                    f"channel_info_{channel_db_id}"
                )
                await internal_cache.invalidate(
                    f"start_data_{user_id}"
                )
                if CACHE_AVAILABLE:
                    await invalidate_user_cache(user_id)
                    await posts_cache.invalidate(channel_db_id)
                    await channels_cache.invalidate(user_id)

                logger.info(
                    f"♻️ إعادة تدوير: {count} منشور "
                    f"للقناة {channel_db_id}"
                )
                return count

        except Exception as e:
            logger.error(
                f"❌ Error in reset_posts: {e}", exc_info=True
            )
            return 0

    async def get_user_posts(
        self, user_id: int, channel_db_id: int, limit: int = 10
    ) -> List[Dict]:
        """
        جلب آخر منشورات القناة.
        ✅ v7.5.27 GAP-4: فحص removed_at IS NULL.
        """
        from database import CACHE_AVAILABLE, posts_cache

        if await self._has_removed_at_column():
            exists = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id = ? AND user_id = ? "
                "AND removed_at IS NULL",
                (channel_db_id, user_id),
            )
        else:
            exists = await self.fetchval(
                "SELECT 1 FROM user_channels "
                "WHERE id = ? AND user_id = ?",
                (channel_db_id, user_id),
            )
        if not exists:
            return []

        if CACHE_AVAILABLE:
            cached = await posts_cache.get_posts(
                channel_db_id, limit
            )
            if cached is not None:
                return cached

        posts = await self.fetchall(
            """SELECT id, text, media_type, published,
                      fail_count, created_at
               FROM posts WHERE channel_db_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (channel_db_id, limit),
        )
        if CACHE_AVAILABLE:
            await posts_cache.set_posts(channel_db_id, posts, limit)
        return posts