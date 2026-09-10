#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_contests.py - دوال المسابقات (v7.4.1)
================================================================================
ContestsMixin:
  - create_contest         : إنشاء مسابقة جديدة
  - get_active_contests    : جلب المسابقات النشطة
  - join_contest           : مشاركة في مسابقة
  - declare_winner         : إعلان الفائز
  - get_contest_winners    : جلب الفائزين السابقين
  - delete_contest         : حذف مسابقة
  - check_contest_joined   : التحقق من المشاركة
  - get_contest_by_id      : جلب مسابقة بالمعرف

📌 مطابق 100% للسلوك الأصلي في database.py (بدون أي إضافة أو تعديل)

📌 يفترض أن الـ Database يوفّر:
  - self.connection() / self.transaction()
  - self._fetchone_with_conn / self._execute_with_conn
  - self.fetchall / self.fetchone / self.fetchval
  - self.TimeUtils
  - self.USE_POSTGRES / self.USE_MYSQL
================================================================================
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ContestsMixin:
    """Mixin يحتوي كل دوال المسابقات"""

    # =====================================================================
    # 1) إنشاء مسابقة
    # =====================================================================

    async def create_contest(self, creator_id: int, title: str, description: str,
                             prize: str, end_date: str) -> int:
        try:
            dt = self.TimeUtils.safe_parse_iso(end_date)
            if dt is None:
                logger.error(f"❌ Invalid end_date format: {end_date}")
                return 0
            async with self.connection() as conn:
                if self.USE_POSTGRES:
                    row = await self._fetchone_with_conn(
                        conn,
                        "INSERT INTO contests (creator_id, title, description, prize, end_date, created_at) VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
                        creator_id, title, description, prize, dt, self.TimeUtils.utc_now(),
                    )
                    return row["id"] if row else 0
                elif self.USE_MYSQL:
                    cursor = await conn.cursor()
                    await cursor.execute(
                        "INSERT INTO contests (creator_id, title, description, prize, end_date, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                        (creator_id, title, description, prize,
                         dt.strftime("%Y-%m-%d %H:%M:%S"), self.TimeUtils.sql_iso()),
                    )
                    cid = cursor.lastrowid
                    await cursor.close()
                    return cid
                else:
                    cursor = await conn.execute(
                        "INSERT INTO contests (creator_id, title, description, prize, end_date, created_at) VALUES (?,?,?,?,?,?)",
                        (creator_id, title, description, prize,
                         dt.strftime("%Y-%m-%d %H:%M:%S"), self.TimeUtils.sql_iso()),
                    )
                    return cursor.lastrowid if cursor.lastrowid else 0
        except Exception as e:
            logger.error(f"❌ Error in create_contest: {e}", exc_info=True)
            return 0

    # =====================================================================
    # 2) جلب المسابقات النشطة
    # =====================================================================

    async def get_active_contests(self, limit: int = 10) -> List[Dict]:
        return await self.fetchall(
            """SELECT c.*, (SELECT COUNT(*) FROM contest_participants WHERE contest_id = c.id) as participants
               FROM contests c
               WHERE c.status = 'active' AND c.end_date > ?
               ORDER BY c.end_date ASC LIMIT ?""",
            (self.TimeUtils.utc_now(), limit),
        )

    # =====================================================================
    # 3) المشاركة في مسابقة
    # =====================================================================

    async def join_contest(self, contest_id: int, user_id: int, answer: str = "") -> bool:
        try:
            async with self.transaction() as conn:
                contest = await self._fetchone_with_conn(
                    conn, "SELECT status, end_date FROM contests WHERE id = ?", contest_id
                )
                if not contest or contest["status"] != "active":
                    return False
                end_date = self.TimeUtils.safe_parse_iso(contest["end_date"])
                if end_date and end_date < self.TimeUtils.utc_now():
                    return False
                await self._execute_with_conn(
                    conn,
                    "INSERT INTO contest_participants (contest_id, user_id, answer, joined_at) VALUES (?,?,?,?)",
                    contest_id, user_id, answer, self.TimeUtils.utc_now(),
                )
                return True
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                return False
            logger.error(f"❌ Error in join_contest: {e}", exc_info=True)
            return False

    # =====================================================================
    # 4) إعلان الفائز
    # =====================================================================

    async def declare_winner(self, contest_id: int, winner_id: int) -> bool:
        try:
            async with self.transaction() as conn:
                cursor = await conn.execute(
                    "SELECT 1 FROM contest_participants WHERE contest_id = ? AND user_id = ?",
                    (contest_id, winner_id),
                )
                if not await cursor.fetchone():
                    return False
                contest = await self._fetchone_with_conn(
                    conn, "SELECT status FROM contests WHERE id = ?", contest_id
                )
                if not contest or contest["status"] != "active":
                    return False
                await self._execute_with_conn(
                    conn, "UPDATE contests SET status = 'closed', winner_id = ? WHERE id = ?",
                    winner_id, contest_id,
                )
                await self._execute_with_conn(
                    conn,
                    "INSERT INTO contest_winners (contest_id, winner_id, announced_at) VALUES (?,?,?)",
                    contest_id, winner_id, self.TimeUtils.utc_now(),
                )
                return True
        except Exception as e:
            logger.error(f"❌ Error in declare_winner: {e}", exc_info=True)
            return False

    # =====================================================================
    # 5) جلب الفائزين السابقين
    # =====================================================================

    async def get_contest_winners(self, limit: int = 10) -> List[Dict]:
        return await self.fetchall(
            """SELECT c.title, c.winner_id, u.username, cw.announced_at
               FROM contest_winners cw
               JOIN contests c ON cw.contest_id = c.id
               JOIN users u ON cw.winner_id = u.user_id
               ORDER BY cw.announced_at DESC LIMIT ?""",
            (limit,),
        )

    # =====================================================================
    # 6) حذف مسابقة
    # =====================================================================

    async def delete_contest(self, contest_id: int, user_id: int) -> bool:
        try:
            async with self.transaction() as conn:
                contest = await self._fetchone_with_conn(
                    conn, "SELECT creator_id FROM contests WHERE id = ?", contest_id
                )
                if not contest or contest["creator_id"] != user_id:
                    return False
                await self._execute_with_conn(conn, "DELETE FROM contest_participants WHERE contest_id = ?", contest_id)
                await self._execute_with_conn(conn, "DELETE FROM contest_winners WHERE contest_id = ?", contest_id)
                await self._execute_with_conn(conn, "DELETE FROM contests WHERE id = ?", contest_id)
                return True
        except Exception as e:
            logger.error(f"❌ Error in delete_contest: {e}", exc_info=True)
            return False

    # =====================================================================
    # 7) التحقق من المشاركة
    # =====================================================================

    async def check_contest_joined(self, contest_id: int, user_id: int) -> bool:
        result = await self.fetchval(
            "SELECT 1 FROM contest_participants WHERE contest_id = ? AND user_id = ?", (contest_id, user_id)
        )
        return result is not None

    # =====================================================================
    # 8) جلب مسابقة بالمعرف
    # =====================================================================

    async def get_contest_by_id(self, contest_id: int) -> Optional[Dict]:
        return await self.fetchone("SELECT * FROM contests WHERE id = ?", (contest_id,))