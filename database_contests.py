#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_contests.py - دوال المسابقات (v7.4.5)
================================================================================
🆕 v7.4.5 — مسابقة سؤال وجواب:
  ✅ create_contest() — params جديدة: question, correct_answer
  ✅ _normalize_answer() — تطبيع الإجابة للمقارنة (trim + lowercase)
  ✅ get_correct_answerers() — جلب من أجاب صحيحًا فقط
  ✅ auto_declare_expired_contests() — يختار من الإجابات الصحيحة
  ✅ أنواع المسابقات:
       - raffle: جميع المشاركين مؤهلون
       - quiz:   فقط من أجاب صحيحًا مؤهل
       - other:  مثل raffle

🆕 v7.4.4:
  ✅ auto_declare_expired_contests() — إعلان تلقائي كل ساعة
  ✅ import random

🆕 v7.4.3:
  ✅ declare_winner() — UPDATE ذرّي (ضد race)
  ✅ join_contest() — end_date <= now
  ✅ VALID_CONTEST_TYPES — توحيد القيم

🆕 v7.4.2:
  ✅ declare_winner() يستخدم _fetchval_with_conn
  ✅ MySQL created_at بصيغة صحيحة
  ✅ get_contest_winners() LEFT JOIN
  ✅ join_contest() INSERT OR IGNORE
  ✅ create_contest() يتحقق من end_date > now
  ✅ delete_contest() يدعم is_admin
  ✅ get_contest_by_id() يُرجع عدد المشاركين
  ✅ answer محدود بـ 2000 حرف
  ✅ _normalize_datetime() مساعدة
  ✅ check_contest_joined() يدعم include_finished
  ✅ cancel_contest() و get_contest_participants()

📌 يفترض أن الـ Database يوفّر:
  - self.connection() / self.transaction()
  - self._fetchone_with_conn / self._fetchall_with_conn
  - self._execute_with_conn / self._fetchval_with_conn
  - self.fetchall / self.fetchone / self.fetchval
  - self.TimeUtils
  - self.USE_POSTGRES / self.USE_MYSQL
================================================================================
"""

import logging
import random
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

MAX_ANSWER_LENGTH = 2000
VALID_CONTEST_STATUSES = {"active", "closed", "cancelled"}

# ✅ v7.4.5: أنواع المسابقات
# - raffle: عشوائي من الجميع
# - quiz:   عشوائي من من أجاب صحيحًا
# - other:  مثل raffle
VALID_CONTEST_TYPES = ("raffle", "quiz", "other")


class ContestsMixin:
    """Mixin يحتوي كل دوال المسابقات"""

    # =====================================================================
    # دوال مساعدة
    # =====================================================================

    def _normalize_datetime(self, dt) -> Any:
        """✅ v7.4.2: تحويل datetime حسب المحرك."""
        if dt is None:
            return None
        if hasattr(dt, "strftime"):
            if getattr(self, "USE_POSTGRES", False):
                return dt
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return dt

    def _truncate_answer(self, answer: str) -> str:
        """✅ v7.4.2: قص الإجابة إلى الحد الأقصى."""
        if not answer:
            return ""
        if len(answer) > MAX_ANSWER_LENGTH:
            logger.warning(
                f"⚠️ الإجابة طويلة ({len(answer)} حرف)، سيتم قصها إلى {MAX_ANSWER_LENGTH}"
            )
            return answer[:MAX_ANSWER_LENGTH]
        return answer

    def _normalize_answer(self, text: str) -> str:
        """
        ✅ v7.4.5: تطبيع الإجابة للمقارنة.

        - trim
        - lowercase
        - تصغير المسافات المتعددة إلى واحدة
        - إزالة التشكيل العربي (اختياري)
        """
        if not text:
            return ""
        s = str(text).strip().lower()
        # تصغير المسافات
        s = " ".join(s.split())
        return s

    # =====================================================================
    # 1) إنشاء مسابقة
    # =====================================================================

    async def create_contest(
        self,
        creator_id: int,
        title: str,
        description: str,
        prize: str,
        end_date: str,
        contest_type: str = "raffle",
        question: str = "",
        correct_answer: str = "",
    ) -> int:
        """
        ✅ v7.4.5: إنشاء مسابقة.

        Args:
            question:       السؤال (فقط لـ quiz — يمكن أن يكون فارغًا)
            correct_answer: الإجابة الصحيحة (فقط لـ quiz)

        Returns:
            معرف المسابقة (int) عند النجاح، 0 عند الفشل.
        """
        try:
            dt = self.TimeUtils.safe_parse_iso(end_date)
            if dt is None:
                logger.error(f"❌ Invalid end_date format: {end_date}")
                return 0

            now = self.TimeUtils.utc_now()
            if dt <= now:
                logger.error(
                    f"❌ end_date ({dt}) يجب أن يكون في المستقبل (الآن: {now})"
                )
                return 0

            title = (title or "").strip()
            if not title:
                logger.error("❌ title فارغ")
                return 0
            title = title[:200]

            description = (description or "").strip()[:2000]
            prize = (prize or "").strip()[:200]

            if contest_type not in VALID_CONTEST_TYPES:
                contest_type = "raffle"

            # ✅ v7.4.5: معالجة question/correct_answer
            question = (question or "").strip()[:1000]
            correct_answer = (correct_answer or "").strip()[:500]

            # لو quiz بلا سؤال/إجابة → نعتبره raffle بأمان
            if contest_type == "quiz" and (
                not question or not correct_answer
            ):
                logger.warning(
                    "⚠️ quiz بدون question أو correct_answer → تحويل إلى raffle"
                )
                contest_type = "raffle"
                question = ""
                correct_answer = ""

            async with self.transaction() as conn:
                # PostgreSQL
                if self.USE_POSTGRES:
                    row = await self._fetchone_with_conn(
                        conn,
                        "INSERT INTO contests "
                        "(creator_id, title, description, prize, end_date, "
                        " status, contest_type, question, correct_answer, created_at) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) "
                        "RETURNING id",
                        creator_id, title, description, prize,
                        dt, "active", contest_type,
                        question, correct_answer, now,
                    )
                    if row:
                        cid = row.get("id", 0)
                        logger.info(
                            f"✅ أنشئت مسابقة جديدة #{cid} "
                            f"(type={contest_type}) بواسطة {creator_id}"
                        )
                        return cid
                    logger.error("❌ فشل RETURNING id في PostgreSQL")
                    return 0

                # MySQL
                elif self.USE_MYSQL:
                    cursor = await conn.cursor()
                    await cursor.execute(
                        "INSERT INTO contests "
                        "(creator_id, title, description, prize, end_date, "
                        " status, contest_type, question, correct_answer, created_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            creator_id, title, description, prize,
                            self._normalize_datetime(dt),
                            "active", contest_type,
                            question, correct_answer,
                            self._normalize_datetime(now),
                        ),
                    )
                    cid = cursor.lastrowid
                    await cursor.close()
                    if cid:
                        logger.info(
                            f"✅ أنشئت مسابقة جديدة #{cid} "
                            f"(type={contest_type}) بواسطة {creator_id}"
                        )
                        return cid
                    logger.error("❌ فشل lastrowid في MySQL")
                    return 0

                # SQLite
                else:
                    cursor = await conn.execute(
                        "INSERT INTO contests "
                        "(creator_id, title, description, prize, end_date, "
                        " status, contest_type, question, correct_answer, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            creator_id, title, description, prize,
                            self._normalize_datetime(dt),
                            "active", contest_type,
                            question, correct_answer,
                            self._normalize_datetime(now),
                        ),
                    )
                    cid = cursor.lastrowid if cursor and cursor.lastrowid else 0
                    if cid:
                        logger.info(
                            f"✅ أنشئت مسابقة جديدة #{cid} "
                            f"(type={contest_type}) بواسطة {creator_id}"
                        )
                        return cid
                    logger.error("❌ فشل lastrowid في SQLite")
                    return 0

        except Exception as e:
            logger.error(f"❌ Error in create_contest: {e}", exc_info=True)
            return 0

    # =====================================================================
    # 2) جلب المسابقات النشطة
    # =====================================================================

    async def get_active_contests(self, limit: int = 10) -> List[Dict]:
        """✅ v7.4.2: جلب المسابقات النشطة مع عدد المشاركين."""
        try:
            now = self.TimeUtils.utc_now()
            limit = max(1, min(limit, 100))

            return await self.fetchall(
                """SELECT c.*,
                          (SELECT COUNT(*) FROM contest_participants
                           WHERE contest_id = c.id) AS participants
                   FROM contests c
                   WHERE c.status = 'active' AND c.end_date > ?
                   ORDER BY c.end_date ASC
                   LIMIT ?""",
                (now, limit),
            )
        except Exception as e:
            logger.error(f"❌ Error in get_active_contests: {e}", exc_info=True)
            return []

    # =====================================================================
    # 3) المشاركة في مسابقة
    # =====================================================================

    async def join_contest(
        self, contest_id: int, user_id: int, answer: str = ""
    ) -> bool:
        """✅ v7.4.3: مشاركة في مسابقة."""
        try:
            answer = self._truncate_answer(answer or "")

            async with self.transaction() as conn:
                contest = await self._fetchone_with_conn(
                    conn,
                    "SELECT status, end_date FROM contests WHERE id = ?",
                    contest_id,
                )
                if not contest:
                    logger.debug(f"المسابقة {contest_id} غير موجودة")
                    return False

                if contest.get("status") != "active":
                    logger.debug(f"المسابقة {contest_id} ليست نشطة")
                    return False

                end_date = self.TimeUtils.safe_parse_iso(contest.get("end_date"))
                now = self.TimeUtils.utc_now()

                if end_date is None:
                    logger.warning(
                        f"⚠️ لا يمكن قراءة end_date للمسابقة {contest_id}"
                    )
                    return False

                if end_date <= now:
                    logger.debug(f"المسابقة {contest_id} انتهت")
                    return False

                inserted = await self._execute_with_conn(
                    conn,
                    "INSERT OR IGNORE INTO contest_participants "
                    "(contest_id, user_id, answer, joined_at) "
                    "VALUES (?,?,?,?)",
                    contest_id, user_id, answer, now,
                )

                if inserted and inserted > 0:
                    logger.info(
                        f"✅ المستخدم {user_id} شارك في المسابقة {contest_id}"
                    )
                    return True

                logger.debug(
                    f"المستخدم {user_id} شارك مسبقًا في المسابقة {contest_id}"
                )
                return False

        except Exception as e:
            err = str(e).lower()
            if "unique" in err or "duplicate" in err:
                return False
            logger.error(f"❌ Error in join_contest: {e}", exc_info=True)
            return False

    # =====================================================================
    # 3.1) جلب من أجابوا صحيحًا (جديد v7.4.5)
    # =====================================================================

    async def get_correct_answerers(
        self, contest_id: int, limit: int = 1000
    ) -> List[Dict]:
        """
        ✅ v7.4.5: جلب المشاركين الذين أجابوا إجابة صحيحة.

        - يجلب correct_answer من جدول contests
        - يُطبّع الإجابات للمقارنة (trim + lowercase)
        - يُرجع قائمة المشاركين المُطابقين
        - لو المسابقة غير quiz → يُرجع كل المشاركين (fallback)
        """
        try:
            limit = max(1, min(limit, 5000))

            # 1) جلب المسابقة
            contest = await self.fetchone(
                "SELECT contest_type, correct_answer "
                "FROM contests WHERE id = ?",
                (contest_id,),
            )
            if not contest:
                return []

            c = dict(contest) if not isinstance(contest, dict) else contest
            ctype = (c.get("contest_type") or "raffle").lower()
            correct_raw = c.get("correct_answer") or ""

            # 2) لو ليست quiz → كل المشاركين مؤهلون
            if ctype != "quiz" or not correct_raw:
                return await self.fetchall(
                    """SELECT cp.user_id, cp.answer, cp.joined_at
                       FROM contest_participants cp
                       WHERE cp.contest_id = ?
                       ORDER BY cp.joined_at ASC
                       LIMIT ?""",
                    (contest_id, limit),
                )

            # 3) quiz حقيقي — فلترة في Python (يعمل على 3 محركات)
            correct_norm = self._normalize_answer(correct_raw)
            all_participants = await self.fetchall(
                """SELECT cp.user_id, cp.answer, cp.joined_at
                   FROM contest_participants cp
                   WHERE cp.contest_id = ?
                   ORDER BY cp.joined_at ASC
                   LIMIT ?""",
                (contest_id, limit),
            )

            matched: List[Dict] = []
            for p in (all_participants or []):
                pd = dict(p) if not isinstance(p, dict) else p
                user_ans_norm = self._normalize_answer(
                    pd.get("answer") or ""
                )
                if user_ans_norm and user_ans_norm == correct_norm:
                    matched.append(pd)

            logger.info(
                f"🎯 get_correct_answerers(#{contest_id}): "
                f"{len(matched)}/{len(all_participants or [])} "
                f"أجابوا صحيحًا"
            )
            return matched

        except Exception as e:
            logger.error(
                f"❌ Error in get_correct_answerers: {e}", exc_info=True
            )
            return []

    # =====================================================================
    # 4) إعلان الفائز (يدوي)
    # =====================================================================

    async def declare_winner(self, contest_id: int, winner_id: int) -> bool:
        """
        ✅ v7.4.3: إعلان الفائز — UPDATE ذرّي لمنع race condition.
        """
        try:
            async with self.transaction() as conn:
                joined = await self._fetchval_with_conn(
                    conn,
                    "SELECT 1 FROM contest_participants "
                    "WHERE contest_id = ? AND user_id = ?",
                    contest_id, winner_id,
                )
                if not joined:
                    logger.debug(
                        f"المستخدم {winner_id} لم يشارك في المسابقة {contest_id}"
                    )
                    return False

                updated = await self._execute_with_conn(
                    conn,
                    "UPDATE contests SET status = 'closed', winner_id = ? "
                    "WHERE id = ? AND status = 'active'",
                    winner_id, contest_id,
                )
                if not updated:
                    logger.debug(
                        f"المسابقة {contest_id}: أُغلقت بالفعل أو غير نشطة"
                    )
                    return False

                await self._execute_with_conn(
                    conn,
                    "INSERT INTO contest_winners "
                    "(contest_id, winner_id, announced_at) VALUES (?,?,?)",
                    contest_id, winner_id, self.TimeUtils.utc_now(),
                )

                logger.info(
                    f"🏆 تم إعلان الفائز {winner_id} في المسابقة {contest_id}"
                )
                return True

        except Exception as e:
            logger.error(f"❌ Error in declare_winner: {e}", exc_info=True)
            return False

    # =====================================================================
    # 5) جلب الفائزين السابقين
    # =====================================================================

    async def get_contest_winners(self, limit: int = 10) -> List[Dict]:
        """✅ v7.4.2: LEFT JOIN لتجنب فقد الفائزين."""
        try:
            limit = max(1, min(limit, 100))
            return await self.fetchall(
                """SELECT
                       COALESCE(c.title, 'مسابقة محذوفة') AS title,
                       cw.winner_id,
                       COALESCE(u.username, '') AS username,
                       COALESCE(u.first_name, '') AS first_name,
                       cw.announced_at
                   FROM contest_winners cw
                   LEFT JOIN contests c ON cw.contest_id = c.id
                   LEFT JOIN users u ON cw.winner_id = u.user_id
                   ORDER BY cw.announced_at DESC
                   LIMIT ?""",
                (limit,),
            )
        except Exception as e:
            logger.error(f"❌ Error in get_contest_winners: {e}", exc_info=True)
            return []

    # =====================================================================
    # 6) حذف مسابقة
    # =====================================================================

    async def delete_contest(
        self, contest_id: int, user_id: int, is_admin: bool = False
    ) -> bool:
        """✅ v7.4.2: حذف مسابقة."""
        try:
            async with self.transaction() as conn:
                contest = await self._fetchone_with_conn(
                    conn,
                    "SELECT creator_id FROM contests WHERE id = ?",
                    contest_id,
                )
                if not contest:
                    return False

                if not is_admin and contest.get("creator_id") != user_id:
                    return False

                await self._execute_with_conn(
                    conn,
                    "DELETE FROM contest_participants WHERE contest_id = ?",
                    contest_id,
                )
                await self._execute_with_conn(
                    conn,
                    "DELETE FROM contest_winners WHERE contest_id = ?",
                    contest_id,
                )
                await self._execute_with_conn(
                    conn,
                    "DELETE FROM contests WHERE id = ?",
                    contest_id,
                )

                logger.info(
                    f"🗑️ تم حذف المسابقة {contest_id} بواسطة {user_id}"
                )
                return True

        except Exception as e:
            logger.error(f"❌ Error in delete_contest: {e}", exc_info=True)
            return False

    # =====================================================================
    # 6.1) إلغاء مسابقة
    # =====================================================================

    async def cancel_contest(
        self, contest_id: int, user_id: int, is_admin: bool = False
    ) -> bool:
        """✅ v7.4.2: إلغاء مسابقة."""
        try:
            async with self.transaction() as conn:
                contest = await self._fetchone_with_conn(
                    conn,
                    "SELECT creator_id, status FROM contests WHERE id = ?",
                    contest_id,
                )
                if not contest:
                    return False

                if not is_admin and contest.get("creator_id") != user_id:
                    return False

                if contest.get("status") != "active":
                    return False

                await self._execute_with_conn(
                    conn,
                    "UPDATE contests SET status = 'cancelled' WHERE id = ?",
                    contest_id,
                )
                logger.info(f"❌ تم إلغاء المسابقة {contest_id}")
                return True

        except Exception as e:
            logger.error(f"❌ Error in cancel_contest: {e}", exc_info=True)
            return False

    # =====================================================================
    # 6.2) إعلان فائزين تلقائي (v7.4.5)
    # =====================================================================

    async def auto_declare_expired_contests(self) -> List[Dict]:
        """
        ✅ v7.4.5: يعلن الفائزين تلقائيًا للمسابقات المنتهية.

        المنطق:
          1. جلب كل المسابقات (status='active' AND end_date <= now)
          2. لكل مسابقة:
             ├─ quiz: فقط من أجاب صحيحًا مؤهل
             │   └─ لو لا أحد أجاب صحيحًا → يُلغى (cancelled)
             └─ raffle/other: كل المشاركين مؤهلون
          3. random.choice من المؤهلين
          4. declare_winner (ذرّي)
          5. تجميع النتائج للإشعار من main.py

        Returns:
            [{'contest_id': int, 'winner_id': int, 'title': str}, ...]
        """
        results: List[Dict] = []

        try:
            now = self.TimeUtils.utc_now()

            expired_rows = await self.fetchall(
                """SELECT id, creator_id, title, contest_type
                   FROM contests
                   WHERE status = 'active' AND end_date <= ?
                   ORDER BY end_date ASC""",
                (now,),
            )

            if not expired_rows:
                return []

            logger.info(
                f"🔍 auto_declare: وجدت {len(expired_rows)} مسابقة منتهية"
            )

            for row in expired_rows:
                row_d = dict(row) if not isinstance(row, dict) else row
                cid = row_d.get("id")
                title = row_d.get("title") or ""
                ctype = (row_d.get("contest_type") or "raffle").lower()

                if cid is None:
                    continue

                try:
                    # ✅ v7.4.5: استخدام get_correct_answerers
                    #    - quiz: يُرجع فقط من أجاب صحيحًا
                    #    - raffle/other: يُرجع الجميع
                    eligible = await self.get_correct_answerers(cid)

                    user_ids: List[int] = []
                    for p in (eligible or []):
                        pd = dict(p) if not isinstance(p, dict) else p
                        uid = pd.get("user_id")
                        if uid is not None:
                            try:
                                user_ids.append(int(uid))
                            except (TypeError, ValueError):
                                continue

                    # ─── لا مؤهلين → إلغاء ───
                    if not user_ids:
                        await self.cancel_contest(cid, 0, is_admin=True)
                        if ctype == "quiz":
                            logger.info(
                                f"❌ auto_declare: أُلغيت المسابقة #{cid} "
                                f"(quiz — لا إجابات صحيحة)"
                            )
                        else:
                            logger.info(
                                f"❌ auto_declare: أُلغيت المسابقة #{cid} "
                                f"(بلا مشاركين)"
                            )
                        continue

                    # ─── اختيار فائز عشوائي من المؤهلين ───
                    winner_id = random.choice(user_ids)

                    success = await self.declare_winner(cid, winner_id)

                    if success:
                        results.append({
                            "contest_id": cid,
                            "winner_id": winner_id,
                            "title": title,
                            "contest_type": ctype,
                        })
                        logger.info(
                            f"🏆 auto_declare: مسابقة #{cid} ({ctype}) "
                            f"→ فائز {winner_id} "
                            f"(من {len(user_ids)} مؤهل)"
                        )
                    else:
                        logger.warning(
                            f"⚠️ auto_declare: فشل إعلان الفائز "
                            f"للمسابقة #{cid}"
                        )

                except Exception as inner_e:
                    logger.error(
                        f"❌ auto_declare: فشل معالجة المسابقة #{cid}: "
                        f"{inner_e}",
                        exc_info=True,
                    )
                    continue

            return results

        except Exception as e:
            logger.error(
                f"❌ Error in auto_declare_expired_contests: {e}",
                exc_info=True,
            )
            return results

    # =====================================================================
    # 7) التحقق من المشاركة
    # =====================================================================

    async def check_contest_joined(
        self, contest_id: int, user_id: int, include_finished: bool = False
    ) -> bool:
        """✅ v7.4.2: التحقق من مشاركة المستخدم."""
        try:
            if include_finished:
                result = await self.fetchval(
                    "SELECT 1 FROM contest_participants "
                    "WHERE contest_id = ? AND user_id = ?",
                    (contest_id, user_id),
                )
                return result is not None

            result = await self.fetchval(
                """SELECT 1 FROM contest_participants cp
                   JOIN contests c ON cp.contest_id = c.id
                   WHERE cp.contest_id = ?
                     AND cp.user_id = ?
                     AND c.status IN ('active', 'closed')
                   LIMIT 1""",
                (contest_id, user_id),
            )
            return result is not None
        except Exception as e:
            logger.error(f"❌ Error in check_contest_joined: {e}", exc_info=True)
            return False

    # =====================================================================
    # 8) جلب مسابقة بالمعرف
    # =====================================================================

    async def get_contest_by_id(self, contest_id: int) -> Optional[Dict]:
        """✅ v7.4.2: يُرجع بيانات المسابقة مع عدد المشاركين."""
        try:
            return await self.fetchone(
                """SELECT c.*,
                          (SELECT COUNT(*) FROM contest_participants
                           WHERE contest_id = c.id) AS participants
                   FROM contests c
                   WHERE c.id = ?""",
                (contest_id,),
            )
        except Exception as e:
            logger.error(f"❌ Error in get_contest_by_id: {e}", exc_info=True)
            return None

    # =====================================================================
    # 9) جلب قائمة المشاركين
    # =====================================================================

    async def get_contest_participants(
        self, contest_id: int, limit: int = 100
    ) -> List[Dict]:
        """✅ v7.4.2: جلب قائمة المشاركين في مسابقة."""
        try:
            limit = max(1, min(limit, 1000))
            return await self.fetchall(
                """SELECT cp.user_id, cp.answer, cp.joined_at,
                          COALESCE(u.username, '') AS username,
                          COALESCE(u.first_name, '') AS first_name
                   FROM contest_participants cp
                   LEFT JOIN users u ON cp.user_id = u.user_id
                   WHERE cp.contest_id = ?
                   ORDER BY cp.joined_at ASC
                   LIMIT ?""",
                (contest_id, limit),
            )
        except Exception as e:
            logger.error(f"❌ Error in get_contest_participants: {e}", exc_info=True)
            return []

    # =====================================================================
    # 10) إحصائيات
    # =====================================================================

    async def get_contest_stats(self, contest_id: int) -> Dict[str, Any]:
        """✅ v7.4.2: إحصائيات سريعة."""
        try:
            stats = await self.fetchone(
                """SELECT
                       (SELECT COUNT(*) FROM contest_participants WHERE contest_id = ?) AS participants,
                       (SELECT COUNT(*) FROM contest_winners WHERE contest_id = ?) AS winners,
                       c.status, c.end_date, c.winner_id, c.contest_type
                   FROM contests c
                   WHERE c.id = ?""",
                (contest_id, contest_id, contest_id),
            )
            return stats or {}
        except Exception as e:
            logger.error(f"❌ Error in get_contest_stats: {e}", exc_info=True)
            return {}