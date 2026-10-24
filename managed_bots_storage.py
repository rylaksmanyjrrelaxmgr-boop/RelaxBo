#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
managed_bots_storage.py — طبقة I/O (v5.7.9 - TARGETED-UPDATE-FIX)
=================================================================================
🆕 v5.7.9 (TARGETED-UPDATE-FIX) — CRITICAL:
    🔴 FIX-CHURN-1: إضافة `update_managed_user_state(bid, user_id, state)`.
    
    المشكلة:
        `save_managed_state()` كانت تُنفّذ UPSERT على **كل** صفوف المستخدمين
        في كل مرة. مع 8 بوتات × 130 مستخدم = 1,040 UPSERT **لكل رسالة**.
        النتيجة: churn كارثي على `managed_bot_users` (~1,040 dead tuple/رسالة).
        AV لم يستطع اللحاق → 312 dead tuple متراكمة.

    الحل:
        دالة جديدة `update_managed_user_state()` تُحدّث **صفاً واحداً فقط**
        عبر UPSERT مباشر. تُقلّل الـ churn بنسبة 99.9%.
        `save_managed_state()` محفوظة للاستخدام الإداري (حذف بوت/إعادة تعيين).

🆕 v5.7.8 (ONE-TIME-KEYWORD) — محفوظ:
    • جدول managed_bot_keyword_replied.
    • كل مستخدم يستلم الرد مرة واحدة فقط لكل كلمة.
=================================================================================
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from config import CONFIG
from database import DB

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 1. ReentrantLock — يمنع deadlock
# ═══════════════════════════════════════════════════════════════════════════

class ReentrantLock:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._owner: Optional[asyncio.Task] = None
        self._depth: int = 0

    async def acquire(self):
        current = asyncio.current_task()
        if self._owner is current:
            self._depth += 1
            return
        await self._lock.acquire()
        self._owner = current
        self._depth = 1

    def release(self):
        current = asyncio.current_task()
        if self._owner is not current:
            raise RuntimeError("ReentrantLock released by non-owner task")
        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            self._lock.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        self.release()


_io_lock: Optional[ReentrantLock] = None
_tables_created = False


def get_lock() -> ReentrantLock:
    global _io_lock
    if _io_lock is None:
        _io_lock = ReentrantLock()
    return _io_lock


# ═══════════════════════════════════════════════════════════════════════════
# 2. الرسائل الافتراضية
# ═══════════════════════════════════════════════════════════════════════════

_FALLBACK_MESSAGES: Dict[str, str] = {
    "start":  "👋 أهلاً بك!",
    "reply":  "📩 تم استلام رسالتك.",
    "third":  "✅ شكرًا لتواصلك.",
    "fourth": "🙏 نتمنى لك يومًا سعيدًا.",
}


def get_default_messages() -> Dict[str, str]:
    return {
        k: str(getattr(CONFIG, f"MANAGED_{k.upper()}_MESSAGE", None)
               or _FALLBACK_MESSAGES[k])
        for k in ("start", "reply", "third", "fourth")
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3. إنشاء الجداول
# ═══════════════════════════════════════════════════════════════════════════

async def _ensure_tables():
    global _tables_created
    if _tables_created:
        return
    try:
        await DB.execute("""
            CREATE TABLE IF NOT EXISTS managed_bots (
                bot_id INTEGER PRIMARY KEY,
                token TEXT UNIQUE NOT NULL,
                name TEXT,
                msg_start TEXT,
                msg_reply TEXT,
                msg_third TEXT,
                msg_fourth TEXT,
                added_at TEXT
            )
        """)
        await DB.execute("""
            CREATE TABLE IF NOT EXISTS managed_bot_users (
                bot_id INTEGER,
                user_id BIGINT,
                started BOOLEAN DEFAULT FALSE,
                replied BOOLEAN DEFAULT FALSE,
                third BOOLEAN DEFAULT FALSE,
                fourth BOOLEAN DEFAULT FALSE,
                updated_at TIMESTAMP,
                PRIMARY KEY (bot_id, user_id)
            )
        """)
        await DB.execute("""
            CREATE TABLE IF NOT EXISTS managed_bot_keywords (
                bot_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                reply TEXT NOT NULL,
                created_at TIMESTAMP,
                PRIMARY KEY (bot_id, keyword)
            )
        """)
        await DB.execute("""
            CREATE TABLE IF NOT EXISTS managed_bot_keyword_replied (
                bot_id INTEGER NOT NULL,
                user_id BIGINT NOT NULL,
                keyword TEXT NOT NULL,
                replied_at TIMESTAMP,
                PRIMARY KEY (bot_id, user_id, keyword)
            )
        """)
        _tables_created = True
        logger.info(
            "✅ managed_bots: تم التأكد من إنشاء 4 جداول في DB "
            "(bots, users, keywords, keyword_replied)"
        )
    except Exception as e:
        logger.error(
            "❌ managed_bots: فشل إنشاء الجداول: %s", e, exc_info=True
        )


# ═══════════════════════════════════════════════════════════════════════════
# 4. البوتات
# ═══════════════════════════════════════════════════════════════════════════

async def load_managed_bots() -> Dict[int, Dict[str, Any]]:
    await _ensure_tables()
    result: Dict[int, Dict[str, Any]] = {}
    try:
        rows = await DB.fetchall("SELECT * FROM managed_bots")
        for r in rows:
            rd = dict(r) if not isinstance(r, dict) else r
            bid = int(rd.get("bot_id"))
            result[bid] = {
                "token": str(rd.get("token")),
                "name": str(rd.get("name") or ""),
                "messages": {
                    "start":  str(rd.get("msg_start") or _FALLBACK_MESSAGES["start"]),
                    "reply":  str(rd.get("msg_reply") or _FALLBACK_MESSAGES["reply"]),
                    "third":  str(rd.get("msg_third") or _FALLBACK_MESSAGES["third"]),
                    "fourth": str(rd.get("msg_fourth") or _FALLBACK_MESSAGES["fourth"]),
                },
                "added_at": str(rd.get("added_at") or ""),
            }
    except Exception as e:
        logger.error("❌ load_managed_bots: %s", e)
    return result


async def save_managed_bots(bots: Dict[int, Dict[str, Any]]) -> bool:
    await _ensure_tables()
    try:
        async with get_lock():
            await DB.execute("DELETE FROM managed_bots")
            for bid, info in bots.items():
                if not isinstance(info, dict) or "token" not in info:
                    continue
                msgs = info.get("messages") or get_default_messages()
                await DB.execute(
                    """INSERT INTO managed_bots 
                       (bot_id, token, name, msg_start, msg_reply, 
                        msg_third, msg_fourth, added_at) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        int(bid), info["token"], info.get("name", ""),
                        msgs["start"], msgs["reply"],
                        msgs["third"], msgs["fourth"],
                        info.get("added_at", "")
                    )
                )
        return True
    except Exception as e:
        logger.error("❌ save_managed_bots: %s", e, exc_info=True)
        return False


# ═══════════════════════════════════════════════════════════════════════════
# 5. المستخدمون
# ═══════════════════════════════════════════════════════════════════════════

async def load_managed_state() -> Dict[int, Dict[int, Dict[str, bool]]]:
    await _ensure_tables()
    result: Dict[int, Dict[int, Dict[str, bool]]] = {}
    try:
        rows = await DB.fetchall("SELECT * FROM managed_bot_users")
        for r in rows:
            rd = dict(r) if not isinstance(r, dict) else r
            bid = int(rd.get("bot_id"))
            uid = int(rd.get("user_id"))
            if bid not in result:
                result[bid] = {}
            result[bid][uid] = {
                "start":  bool(rd.get("started")),
                "reply":  bool(rd.get("replied")),
                "third":  bool(rd.get("third")),
                "fourth": bool(rd.get("fourth")),
            }
    except Exception as e:
        logger.error("❌ load_managed_state: %s", e)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v5.7.9 FIX-CHURN-1: تحديث صف واحد فقط (بدل UPSERT كل الجداول)
# ═══════════════════════════════════════════════════════════════════════════

async def update_managed_user_state(
    bid: int, user_id: int, user_state: Dict[str, bool],
) -> bool:
    """
    🆕 v5.7.9 FIX-CHURN-1: تحديث/إدراج صف مستخدم واحد فقط.

    بدل `save_managed_state()` التي تُنفّذ ~1,040 UPSERT لكل رسالة،
    هذه الدالة تُنفّذ UPSERT واحدة فقط → تقليل churn بـ 1000×.

    الاستخدام:
        await update_managed_user_state(bid, user_id, {
            "start": True, "reply": False, "third": False, "fourth": False
        })

    Returns:
        True: نجح التحديث
        False: خطأ في DB
    """
    await _ensure_tables()
    try:
        now = datetime.now(timezone.utc)
        await DB.execute(
            """INSERT INTO managed_bot_users 
               (bot_id, user_id, started, replied, third, fourth, updated_at) 
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (bot_id, user_id) DO UPDATE SET
               started = EXCLUDED.started,
               replied = EXCLUDED.replied,
               third = EXCLUDED.third,
               fourth = EXCLUDED.fourth,
               updated_at = EXCLUDED.updated_at""",
            (
                int(bid), int(user_id),
                bool(user_state.get("start", False)),
                bool(user_state.get("reply", False)),
                bool(user_state.get("third", False)),
                bool(user_state.get("fourth", False)),
                now
            )
        )
        return True
    except Exception as e:
        logger.error(
            "❌ update_managed_user_state(#%s, %s): %s",
            bid, user_id, e, exc_info=True
        )
        return False


async def save_managed_state(
    state: Dict[int, Dict[int, Dict[str, bool]]],
) -> bool:
    """
    ⚠️ للاستخدام الإداري فقط (حذف بوت/إعادة تعيين كاملة).

    ❌ لا تستخدمها في معالجة الرسائل — استخدم `update_managed_user_state`
       بدلاً منها لتجنّب churn كارثي (1,040 UPSERT/رسالة).
    """
    await _ensure_tables()
    try:
        async with get_lock():
            db_bots = await DB.fetchall(
                "SELECT DISTINCT bot_id FROM managed_bot_users"
            )
            current_bots = {
                int(r['bot_id'] if isinstance(r, dict) else r[0])
                for r in db_bots
            }
            for bid in current_bots:
                if bid not in state:
                    await DB.execute(
                        "DELETE FROM managed_bot_users WHERE bot_id = ?",
                        (bid,)
                    )

            now = datetime.now(timezone.utc)
            for bid, users in state.items():
                for uid, st in users.items():
                    await DB.execute(
                        """INSERT INTO managed_bot_users 
                           (bot_id, user_id, started, replied, third, 
                            fourth, updated_at) 
                           VALUES (?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT (bot_id, user_id) DO UPDATE SET
                           started = EXCLUDED.started,
                           replied = EXCLUDED.replied,
                           third = EXCLUDED.third,
                           fourth = EXCLUDED.fourth,
                           updated_at = EXCLUDED.updated_at""",
                        (
                            int(bid), int(uid),
                            st.get("start", False),
                            st.get("reply", False),
                            st.get("third", False),
                            st.get("fourth", False),
                            now
                        )
                    )
        return True
    except Exception as e:
        logger.error("❌ save_managed_state: %s", e, exc_info=True)
        return False


# ═══════════════════════════════════════════════════════════════════════════
# 6. الكلمات المفتاحية
# ═══════════════════════════════════════════════════════════════════════════

async def load_managed_keywords(bid: int) -> Dict[str, str]:
    await _ensure_tables()
    result: Dict[str, str] = {}
    try:
        rows = await DB.fetchall(
            "SELECT keyword, reply FROM managed_bot_keywords "
            "WHERE bot_id = ?",
            (int(bid),)
        )
        for r in rows:
            rd = dict(r) if not isinstance(r, dict) else r
            kw = (rd.get("keyword") or "").strip()
            rp = (rd.get("reply") or "").strip()
            if kw and rp:
                result[kw] = rp
    except Exception as e:
        logger.error("❌ load_managed_keywords(#%s): %s", bid, e)
    return result


async def load_all_keywords() -> Dict[int, Dict[str, str]]:
    await _ensure_tables()
    result: Dict[int, Dict[str, str]] = {}
    try:
        rows = await DB.fetchall(
            "SELECT bot_id, keyword, reply FROM managed_bot_keywords"
        )
        for r in rows:
            rd = dict(r) if not isinstance(r, dict) else r
            bid = int(rd.get("bot_id"))
            kw = (rd.get("keyword") or "").strip()
            rp = (rd.get("reply") or "").strip()
            if kw and rp:
                result.setdefault(bid, {})[kw] = rp
    except Exception as e:
        logger.error("❌ load_all_keywords: %s", e)
    return result


async def save_managed_keywords(
    bid: int, keywords: Dict[str, str],
) -> bool:
    await _ensure_tables()
    try:
        async with get_lock():
            await DB.execute(
                "DELETE FROM managed_bot_keywords WHERE bot_id = ?",
                (int(bid),)
            )
            now = datetime.now(timezone.utc)
            for kw, rp in keywords.items():
                kw_clean = (kw or "").strip()
                rp_clean = (rp or "").strip()
                if not kw_clean or not rp_clean:
                    continue
                await DB.execute(
                    """INSERT INTO managed_bot_keywords 
                       (bot_id, keyword, reply, created_at) 
                       VALUES (?, ?, ?, ?)""",
                    (int(bid), kw_clean, rp_clean, now)
                )
        return True
    except Exception as e:
        logger.error(
            "❌ save_managed_keywords(#%s): %s", bid, e, exc_info=True
        )
        return False


async def add_managed_keyword(
    bid: int, keyword: str, reply: str,
) -> bool:
    await _ensure_tables()
    kw_clean = (keyword or "").strip()
    rp_clean = (reply or "").strip()
    if not kw_clean or not rp_clean:
        return False
    try:
        async with get_lock():
            now = datetime.now(timezone.utc)
            await DB.execute(
                """INSERT INTO managed_bot_keywords 
                   (bot_id, keyword, reply, created_at) 
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT (bot_id, keyword) DO UPDATE SET
                   reply = EXCLUDED.reply,
                   created_at = EXCLUDED.created_at""",
                (int(bid), kw_clean, rp_clean, now)
            )
        return True
    except Exception as e:
        logger.error(
            "❌ add_managed_keyword(#%s, %r): %s",
            bid, kw_clean[:30], e, exc_info=True
        )
        return False


async def delete_managed_keyword(bid: int, keyword: str) -> bool:
    await _ensure_tables()
    kw_clean = (keyword or "").strip()
    if not kw_clean:
        return False
    try:
        async with get_lock():
            await DB.execute(
                "DELETE FROM managed_bot_keywords "
                "WHERE bot_id = ? AND keyword = ?",
                (int(bid), kw_clean)
            )
            await DB.execute(
                "DELETE FROM managed_bot_keyword_replied "
                "WHERE bot_id = ? AND keyword = ?",
                (int(bid), kw_clean)
            )
        return True
    except Exception as e:
        logger.error(
            "❌ delete_managed_keyword(#%s): %s", bid, e
        )
        return False


async def delete_all_keywords_for_bot(bid: int) -> bool:
    await _ensure_tables()
    try:
        await DB.execute(
            "DELETE FROM managed_bot_keywords WHERE bot_id = ?",
            (int(bid),)
        )
        await DB.execute(
            "DELETE FROM managed_bot_keyword_replied WHERE bot_id = ?",
            (int(bid),)
        )
        return True
    except Exception as e:
        logger.error(
            "❌ delete_all_keywords_for_bot(#%s): %s", bid, e
        )
        return False


async def get_keyword_count(bid: int) -> int:
    await _ensure_tables()
    try:
        val = await DB.fetchval(
            "SELECT COUNT(*) FROM managed_bot_keywords WHERE bot_id = ?",
            (int(bid),), default=0
        )
        return int(val or 0)
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# 7. تتبع الردود (منع التكرار)
# ═══════════════════════════════════════════════════════════════════════════

async def is_keyword_already_replied(
    bid: int, user_id: int, keyword: str,
) -> bool:
    await _ensure_tables()
    kw_clean = (keyword or "").strip()
    if not kw_clean:
        return False
    try:
        val = await DB.fetchval(
            "SELECT 1 FROM managed_bot_keyword_replied "
            "WHERE bot_id = ? AND user_id = ? AND keyword = ?",
            (int(bid), int(user_id), kw_clean), default=None
        )
        return val is not None
    except Exception as e:
        logger.error("is_keyword_already_replied: %s", e)
        return False


async def mark_keyword_as_replied(
    bid: int, user_id: int, keyword: str,
) -> bool:
    await _ensure_tables()
    kw_clean = (keyword or "").strip()
    if not kw_clean:
        return False
    try:
        now = datetime.now(timezone.utc)
        await DB.execute(
            """INSERT INTO managed_bot_keyword_replied 
               (bot_id, user_id, keyword, replied_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (bot_id, user_id, keyword) DO NOTHING""",
            (int(bid), int(user_id), kw_clean, now)
        )
        return True
    except Exception as e:
        logger.error("mark_keyword_as_replied: %s", e)
        return False


# ═══════════════════════════════════════════════════════════════════════════
# 8. أدوات
# ═══════════════════════════════════════════════════════════════════════════

def next_managed_bot_id(existing: Dict[int, Any]) -> int:
    used: Set[int] = set()
    for k in existing.keys():
        try:
            used.add(int(k))
        except (ValueError, TypeError):
            continue
    n = 1
    while n in used:
        n += 1
    return n


def ensure_default_state() -> Dict[str, bool]:
    return {"start": False, "reply": False, "third": False, "fourth": False}


def get_stats(
    bots: Dict[int, Dict[str, Any]],
    state: Dict[int, Dict[int, Dict[str, bool]]],
) -> Dict[str, int]:
    total_users = 0
    completed = 0
    for users in state.values():
        total_users += len(users)
        for st in users.values():
            if all(st.get(f) for f in ("start", "reply", "third", "fourth")):
                completed += 1
    return {
        "bots": len(bots),
        "users": total_users,
        "completed": completed,
    }


def health_check() -> Dict[str, Any]:
    return {"db_migration": True, "status": "ok"}


# ═══════════════════════════════════════════════════════════════════════════
# 9. __all__
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    "get_default_messages",
    "get_lock",
    "load_managed_bots",
    "save_managed_bots",
    "load_managed_state",
    "save_managed_state",
    # 🆕 v5.7.9
    "update_managed_user_state",
    "load_managed_keywords",
    "load_all_keywords",
    "save_managed_keywords",
    "add_managed_keyword",
    "delete_managed_keyword",
    "delete_all_keywords_for_bot",
    "get_keyword_count",
    "is_keyword_already_replied",
    "mark_keyword_as_replied",
    "next_managed_bot_id",
    "ensure_default_state",
    "get_stats",
    "health_check",
    "ReentrantLock",
]


try:
    logger.debug(
        "🛡️ managed_bots_storage v5.7.9 (TARGETED-UPDATE-FIX) loaded | "
        "tables=bots,users,keywords,keyword_replied | lock=reentrant | "
        "churn_fix=update_managed_user_state"
    )
except Exception:
    pass