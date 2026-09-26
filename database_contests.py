#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_contests.py - دوال المسابقات (v7.4.4)
================================================================================
ContestsMixin:
  - create_contest                 : إنشاء مسابقة جديدة
  - get_active_contests            : جلب المسابقات النشطة
  - join_contest                   : مشاركة في مسابقة
  - declare_winner                 : إعلان الفائز (يدوي/ذرّي)
  - get_contest_winners            : جلب الفائزين السابقين
  - delete_contest                 : حذف مسابقة
  - cancel_contest                 : إلغاء مسابقة
  - auto_declare_expired_contests  : إعلان فائزين تلقائي (جديد v7.4.4)
  - check_contest_joined           : التحقق من المشاركة
  - get_contest_by_id              : جلب مسابقة بالمعرف
  - get_contest_participants       : جلب قائمة المشاركين
  - get_contest_stats              : إحصائيات سريعة

🆕 v7.4.4 — إعلان الفائز تلقائيًا:
  ✅ auto_declare_expired_contests() — دالة جديدة
       • تجلب المسابقات المنتهية (status='active' AND end_date<=now)
       • لكل مسابقة:
           - إذا فيها مشاركون → random.choice → declare_winner → 'closed'
           - إذا لا مشاركون  → cancel_contest → 'cancelled'
       • تُرجع قائمة الفائزين للإشعار من main.py
       • تعتمد على declare_winner الذرّي (v7.4.3) لمنع race
  ✅ أُزيلت close_expired_contests (استُبدِلت)
  ✅ import random أعلى الملف

🆕 v7.4.3 — إصلاحات جذرية:
  ✅ declare_winner() — UPDATE ذرّي (WHERE status='active')
       • يمنع race condition عند ضغطتين متزامنتين
       • لا تسجيل فائزين متعددين على PostgreSQL/SQLite/MySQL
  ✅ join_contest() — end_date <= now (اتساق مع get_active_contests)
  ✅ VALID_CONTEST_TYPES — توحيد القيم المسموحة للأنواع
  ✅ توثيق أن quiz غير مُتحقق منه (يحتاج correct_answer — مؤجل)

🆕 v7.4.2 — إصلاحات سابقة:
  ✅ declare_winner() يستخدم _fetchval_with_conn
  ✅ MySQL created_at بصيغة صحيحة
  ✅ get_contest_winners() يستخدم LEFT JOIN
  ✅ join_contest() يستخدم INSERT OR IGNORE
  ✅ join_contest() يعالج NULL end_date
  ✅ create_contest() يتحقق من end_date > now
  ✅ delete_contest() يدعم is_admin
  ✅ get_contest_by_id() يُرجع عدد المشاركين
  ✅ answer محدود بـ 2000 حرف
  ✅ get_active_contests() مع try/except
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

# ✅ v7.4.2: حد أقصى لطول الإجابة
MAX_ANSWER_LENGTH = 2000

# ✅ v7.4.2: القيم المسموحة لحالة المسابقة
VALID_CONTEST_STATUSES = {"active", "closed", "cancelled"}

# ✅ v7.4.3: أنواع المسابقات المسموحة
# ملاحظة: 'quiz' مدعوم في المخطط لكن التحقق من الإجابة
# لم يُنفَّذ بعد (يحتاج عمود correct_answer). يُستخدم حاليًا
# كـ 'raffle' فعليًا (اختيار عشوائي).
VALID_CONTEST_TYPES = ("raffle", "quiz", "other")


class ContestsMixin:
    """Mixin يحتوي كل دوال المسابقات"""

    # =====================================================================
    # دوال مساعدة داخلية
    # =====================================================================

    def _normalize_datetime(self, dt) -> Any:
        """
        ✅ v7.4.2: تحويل datetime إلى صيغة مناسبة للمحرك الحالي.
        - PostgreSQL: يُرجع datetime كما هو
        - MySQL/SQLite: يُرجع str بالصيغة "YYYY-MM-DD HH:MM:SS"
        """
        if dt is None:
            return None
        if hasattr(dt, "strftime"):
            if getattr(self, "USE_POSTGRES", False):
                return dt
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return dt

    def _truncate_answer(self, answer: str) -> str:
        """✅ v7.4.2: قص الإجابة إلى الحد الأقصى"""
        if not answer:
            return ""
        if len(answer) > MAX_ANSWER_LENGTH:
            logger.warning(
                f"⚠️ الإجابة طويلة ({len(answer)} حرف)، سيتم قصها إلى {MAX_ANSWER_LENGTH}"
            )
            return answer[:MAX_ANSWER_LENGTH]
        return answer

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
    ) -> int:
        """
        ✅ v7.4.2: إنشاء مسابقة جديدة.

        Returns:
            معرف المسابقة (int) عند النجاح، 0 عند الفشل.
        """
        try:
            # التحقق من صحة end_date
            dt = self.TimeUtils.safe_parse_iso(end_date)
            if dt is None:
                logger.error(f"❌ Invalid end_date format: {end_date}")
                return 0

            # ✅ v7.4.2: التحقق من أن end_date في المستقبل
            now = self.TimeUtils.utc_now()
            if dt <= now:
                logger.error(
                    f"❌ end_date ({dt}) يجب أن يكون في المستقبل (الآن: {now})"
                )
                return 0

            # تنظيف المدخلات
            title = (title or "").strip()
            if not title:
                logger.error("❌ title فارغ")
                return 0
            title = title[:200]

            description = (description or "").strip()[:2000]
            prize = (prize or "").strip()[:200]

            # ✅ v7.4.3: استخدام VALID_CONTEST_TYPES الموحّد
            if contest_type not in VALID_CONTEST_TYPES:
                contest_type = "raffle"

            async with self.transaction() as conn:
                # PostgreSQL: RETURNING id
                if self.USE_POSTGRES:
                    row = await self._fetchone_with_conn(
                        conn,
                        "INSERT INTO contests "
                        "(creator_id, title, description, prize, end_date, status, contest_type, created_at) "
                        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id",
                        creator_id, title, description, prize,
                        dt, "active", contest_type, now,
                    )
                    if row:
                        cid = row.get("id", 0)
                        logger.info(f"✅ أنشئت مسابقة جديدة #{cid} بواسطة {creator_id}")
                        return cid
                    logger.error("❌ فشل RETURNING id في PostgreSQL")
                    return 0

                # MySQL: lastrowid
                elif self.USE_MYSQL:
                    cursor = await conn.cursor()
                    await cursor.execute(
                        "INSERT INTO contests "
                        "(creator_id, title, description, prize, end_date, status, contest_type, created_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            creator_id, title, description, prize,
                            self._normalize_datetime(dt),
                            "active", contest_type,
                            self._normalize_datetime(now),
                        ),
                    )
                    cid = cursor.lastrowid
                    await cursor.close()
                    if cid:
                        logger.info(f"✅ أنشئت مسابقة جديدة #{cid} بواسطة {creator_id}")
                        return cid
                    logger.error("❌ فشل lastrowid في MySQL")
                    return 0

                # SQLite: lastrowid
                else:
                    cursor = await conn.execute(
                        "INSERT INTO contests "
                        "(creator_id, title, description, prize, end_date, status, contest_type, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (
                            creator_id, title, description, prize,
                            self._normalize_datetime(dt),
                            "active", contest_type,
                            self._normalize_datetime(now),
                        ),
                    )
                    cid = cursor.lastrowid if cursor and cursor.lastrowid else 0
                    if cid:
                        logger.info(f"✅ أنشئت مسابقة جديدة #{cid} بواسطة {creator_id}")
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
        """
        ✅ v7.4.2: جلب المسابقات النشطة مع عدد المشاركين.
        """
        try:
            now = self.TimeUtils.utc_now()
            limit = max(1, min(limit, 100))  # حد أقصى 100

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
        """
        ✅ v7.4.3: مشاركة في مسابقة.

        Returns:
            True عند النجاح، False عند الفشل أو التكرار.
        """
        try:
            # ✅ قص الإجابة
            answer = self._truncate_answer(answer or "")

            async with self.transaction() as conn:
                # جلب حالة المسابقة
                contest = await self._fetchone_with_conn(
                    conn,
                    "SELECT status, end_date FROM contests WHERE id = ?",
                    contest_id,
                )
                if not contest:
                    logger.debug(f"المسابقة {contest_id} غير موجودة")
                    return False

                # ✅ v7.4.2: التحقق من الحالة
                if contest.get("status") != "active":
                    logger.debug(f"المسابقة {contest_id} ليست نشطة")
                    return False

                # ✅ v7.4.2: التحقق من end_date بحذر
                end_date = self.TimeUtils.safe_parse_iso(contest.get("end_date"))
                now = self.TimeUtils.utc_now()

                if end_date is None:
                    # لا يمكن قراءة التاريخ → نرفض بحذر
                    logger.warning(
                        f"⚠️ لا يمكن قراءة end_date للمسابقة {contest_id} — رفض المشاركة"
                    )
                    return False

                # ✅ v7.4.3: <= بدل < للاتساق مع get_active_contests
                # get_active_contests يستخدم end_date > now
                # لذا end_date == now يعني "منتهية" في الحالتين
                if end_date <= now:
                    logger.debug(f"المسابقة {contest_id} انتهت في {end_date}")
                    return False

                # ✅ v7.4.2: INSERT OR IGNORE (يعمل على 3 محركات عبر الإطار)
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

                # rowcount = 0 يعني موجود مسبقًا
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
    # 4) إعلان الفائز (يدوي)
    # =====================================================================

    async def declare_winner(self, contest_id: int, winner_id: int) -> bool:
        """
        ✅ v7.4.3: إعلان الفائز — UPDATE ذرّي لمنع race condition.

        المشكلة السابقة:
          SELECT status → فحص Python → UPDATE
          فجوة زمنية تسمح لطلبين متزامنين بالنجاح معًا.

        الحل الحالي:
          التحقق من المشاركة (لا يعدّل حالة) →
          UPDATE ذرّي مع WHERE status='active' →
          INSERT winners (نحن الوحيدون داخل transaction).

        على PostgreSQL/SQLite/MySQL: UPDATE مع WHERE ذرّي بشكل مضمون.

        Returns:
            True عند النجاح، False عند الفشل أو إذا أُغلقت المسابقة بالفعل.
        """
        try:
            async with self.transaction() as conn:
                # 1) التحقق من أن الفائز مشارك (لا يعدّل الحالة)
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

                # 2) ✅ v7.4.3: UPDATE ذرّي — الحجر الأساس لمنع race
                #    - rowcount > 0 → نحن الفائزون بالسباق
                #    - rowcount = 0 → طلب آخر أغلق المسابقة قبلاً
                updated = await self._execute_with_conn(
                    conn,
                    "UPDATE contests SET status = 'closed', winner_id = ? "
                    "WHERE id = ? AND status = 'active'",
                    winner_id, contest_id,
                )
                if not updated:
                    logger.debug(
                        f"المسابقة {contest_id}: أُغلقت بالفعل أو غير نشطة "
                        f"(race condition محجوب)"
                    )
                    return False

                # 3) تسجيل الفائز — آمن الآن (نحن الوحيدون)
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
        """
        ✅ v7.4.2: LEFT JOIN لتجنب فقد الفائزين عند حذف المستخدمين/المسابقات.
        """
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
        """
        ✅ v7.4.2: حذف مسابقة.
        - إذا is_admin=True، يمكن للمشرف العام الحذف.
        - وإلا، فقط المنشئ.
        """
        try:
            async with self.transaction() as conn:
                contest = await self._fetchone_with_conn(
                    conn,
                    "SELECT creator_id FROM contests WHERE id = ?",
                    contest_id,
                )
                if not contest:
                    logger.debug(f"المسابقة {contest_id} غير موجودة")
                    return False

                if not is_admin and contest.get("creator_id") != user_id:
                    logger.debug(
                        f"المستخدم {user_id} ليس منشئ المسابقة {contest_id} "
                        f"(المنشئ: {contest.get('creator_id')})"
                    )
                    return False

                # حذف بالترتيب (المشاركون ← الفائزون ← المسابقة)
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
                    f"🗑️ تم حذف المسابقة {contest_id} بواسطة {user_id} "
                    f"(is_admin={is_admin})"
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
        """
        ✅ v7.4.2: إلغاء مسابقة (تغيير الحالة بدل الحذف).
        """
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
                    logger.debug(
                        f"المسابقة {contest_id} ليست نشطة (الحالة: {contest.get('status')})"
                    )
                    return False

                await self._execute_with_conn(
                    conn,
                    "UPDATE contests SET status = 'cancelled' WHERE id = ?",
                    contest_id,
                )
                logger.info(
                    f"❌ تم إلغاء المسابقة {contest_id} بواسطة {user_id}"
                )
                return True

        except Exception as e:
            logger.error(f"❌ Error in cancel_contest: {e}", exc_info=True)
            return False

    # =====================================================================
    # 6.2) إعلان فائزين تلقائي (جديد v7.4.4)
    # =====================================================================

    async def auto_declare_expired_contests(self) -> List[Dict]:
        """
        ✅ v7.4.4: يعلن الفائزين تلقائيًا للمسابقات المنتهية.

        المنطق:
          1. جلب كل المسابقات (status='active' AND end_date <= now)
          2. لكل مسابقة:
             ├─ إذا فيها مشاركون → random.choice → declare_winner → 'closed'
             └─ إذا لا مشاركون   → cancel_contest → 'cancelled'
          3. تجميع نتائج الإعلانات الناجحة للإشعار

        المميزات:
          - يستخدم declare_winner (ذرّي) → آمن ضد race مع الأدمن اليدوي
          - random.choice على مجموعة user_ids (لا FK issues)
          - يتجاهل أي فشل فردي ويكمل الباقي
          - آمن عند التنفيذ المتكرر (المسابقات المُعلنة تُصبح 'closed'
            فلا تُلتقط في الدورة التالية)

        Returns:
            قائمة من dict:
              [{'contest_id': int, 'winner_id': int, 'title': str}, ...]
            للإشعار من main.py (نحن لا نُرسل رسائل من هنا).
        """
        results: List[Dict] = []

        try:
            now = self.TimeUtils.utc_now()

            # 1) جلب المسابقات المنتهية
            expired_rows = await self.fetchall(
                """SELECT id, creator_id, title
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

            # 2) لكل مسابقة
            for row in expired_rows:
                row_d = dict(row) if not isinstance(row, dict) else row
                cid = row_d.get("id")
                title = row_d.get("title") or ""

                if cid is None:
                    continue

                try:
                    # جلب المشاركين
                    participants = await self.fetchall(
                        "SELECT user_id FROM contest_participants "
                        "WHERE contest_id = ?",
                        (cid,),
                    )

                    user_ids: List[int] = []
                    for p in (participants or []):
                        pd = dict(p) if not isinstance(p, dict) else p
                        uid = pd.get("user_id")
                        if uid is not None:
                            try:
                                user_ids.append(int(uid))
                            except (TypeError, ValueError):
                                continue

                    # ─── لا مشاركون → إلغاء ───
                    if not user_ids:
                        await self.cancel_contest(cid, 0, is_admin=True)
                        logger.info(
                            f"❌ auto_declare: أُلغيت المسابقة #{cid} "
                            f"(بلا مشاركين)"
                        )
                        continue

                    # ─── اختيار فائز عشوائي ───
                    winner_id = random.choice(user_ids)

                    # ─── إعلان الفائز (ذرّي) ───
                    success = await self.declare_winner(cid, winner_id)

                    if success:
                        results.append({
                            "contest_id": cid,
                            "winner_id": winner_id,
                            "title": title,
                        })
                        logger.info(
                            f"🏆 auto_declare: مسابقة #{cid} "
                            f"→ فائز {winner_id} (من {len(user_ids)} مشارك)"
                        )
                    else:
                        # فشل الإعلان — قد يكون race مع إعلان يدوي، أو
                        # خطأ مؤقت. نترك المسابقة للدورة القادمة.
                        logger.warning(
                            f"⚠️ auto_declare: فشل إعلان الفائز "
                            f"للمسابقة #{cid} — ستُعالج في الدورة القادمة"
                        )

                except Exception as inner_e:
                    # نتجاهل الفشل الفردي ونكمل المسابقات الأخرى
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
        """
        ✅ v7.4.2: التحقق من مشاركة المستخدم.

        Args:
            include_finished: إذا True، يُرجع True حتى لو انتهت المسابقة.
        """
        try:
            if include_finished:
                result = await self.fetchval(
                    "SELECT 1 FROM contest_participants "
                    "WHERE contest_id = ? AND user_id = ?",
                    (contest_id, user_id),
                )
                return result is not None

            # التحقق مع حالة المسابقة
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
        """
        ✅ v7.4.2: يُرجع بيانات المسابقة مع عدد المشاركين.
        """
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
        """
        ✅ v7.4.2: جلب قائمة المشاركين في مسابقة.
        """
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
    # 10) إحصائيات سريعة
    # =====================================================================

    async def get_contest_stats(self, contest_id: int) -> Dict[str, Any]:
        """
        ✅ v7.4.2: إحصائيات سريعة عن المسابقة.
        """
        try:
            stats = await self.fetchone(
                """SELECT
                       (SELECT COUNT(*) FROM contest_participants WHERE contest_id = ?) AS participants,
                       (SELECT COUNT(*) FROM contest_winners WHERE contest_id = ?) AS winners,
                       c.status, c.end_date, c.winner_id
                   FROM contests c
                   WHERE c.id = ?""",
                (contest_id, contest_id, contest_id),
            )
            return stats or {}
        except Exception as e:
            logger.error(f"❌ Error in get_contest_stats: {e}", exc_info=True)
            return {}