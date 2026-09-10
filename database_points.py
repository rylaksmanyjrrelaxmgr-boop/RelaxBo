#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_points.py - دوال النقاط والمستويات (v7.4.5)
================================================================================
PointsMixin:
  - add_points        : إضافة نقاط لمستخدم
  - get_user_points   : جلب نقاط مستخدم
  - get_user_level    : حساب مستوى مستخدم
  - get_top_users     : قائمة أعلى المستخدمين نقاطاً

📌 مطابق 100% للسلوك الأصلي في database.py (بدون أي إضافة أو تعديل)

📌 يفترض أن الـ Database يوفّر:
  - self.execute / self.fetchval / self.fetchall
  - self.TimeUtils
================================================================================
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


class PointsMixin:
    """Mixin يحتوي كل دوال النقاط والمستويات"""

    # =====================================================================
    # 1) إضافة نقاط
    # =====================================================================

    async def add_points(self, user_id: int, points: int) -> int:
        await self.execute(
            """INSERT INTO user_points (user_id, points, last_updated)
               VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET points = points + ?, last_updated = ?""",
            (user_id, points, self.TimeUtils.utc_now(), points, self.TimeUtils.utc_now()),
        )
        return await self.get_user_points(user_id)

    # =====================================================================
    # 2) جلب نقاط مستخدم
    # =====================================================================

    async def get_user_points(self, user_id: int) -> int:
        return await self.fetchval(
            "SELECT points FROM user_points WHERE user_id = ?",
            (user_id,),
            default=0,
        )

    # =====================================================================
    # 3) حساب مستوى مستخدم
    # =====================================================================

    async def get_user_level(self, user_id: int) -> int:
        points = await self.get_user_points(user_id)
        return (points // 100) + 1

    # =====================================================================
    # 4) قائمة أعلى المستخدمين
    # =====================================================================

    async def get_top_users(self, limit: int = 10) -> List[Dict]:
        return await self.fetchall(
            """SELECT u.user_id, u.username, u.first_name, COALESCE(up.points, 0) as points
               FROM users u
               LEFT JOIN user_points up ON u.user_id = up.user_id
               ORDER BY points DESC LIMIT ?""",
            (limit,),
        )