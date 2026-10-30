#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
managed_bots_storage.py — طبقة I/O (v5.7.11 - PRIVATE-TOGGLE)
=================================================================================
🆕 v5.7.11 (PRIVATE-TOGGLE):
    🟢 FEATURE-PRIVATE-TOGGLE: عمود `respond_in_private` في `managed_bots`.

    • الحالة الافتراضية: 1 (مفعّل) — توافق كامل مع الأصلي.
    • migration تلقائي لـ DBs القديمة.
    • يُستخدم من زر 💬 في اللوحة (hot-toggle بدون restart).

✅ محفوظ من v5.7.10: SPLIT-REPLIES + GROUPS-TOGGLE.
✅ محفوظ من v5.7.9: FIX-CHURN-1.
=================================================================================
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from config import CONFIG
from database import DB

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 1. ReentrantLock
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
# 3. أدوات الكلمات
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_keyword_entry(entry: Any) -> Dict[str, str]:
    if isinstance(entry, dict):
        return {
            "private_reply": str(entry.get("private_reply", "") or ""),
            "group_reply":   str(entry.get("group_reply",   "") or ""),
        }
    if entry is None:
        return {"private_reply": "", "group_reply": ""}
    s = str(entry)
    return {"private_reply": s, "group_reply": s}


def _parse_keyword_reply(raw: Any) -> Optional[Any]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        norm = _normalize_keyword_entry(raw)
        if not norm["private_reply"] and not norm["group_reply"]:
            return None
        return norm
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        if s.startswith("{"):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, dict):
                    norm = _normalize_keyword_entry(parsed)
                    if not norm["private_reply"] and not norm["group_reply"]:
                        return None
                    return norm
            except (json.JSONDecodeError, ValueError):
                pass
        return s
    try:
        s = str(raw).strip()
        return s or None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 4. إنشاء الجداول + Migrations
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
                added_at TEXT,
                respond_in_groups INTEGER DEFAULT 0,
                respond_in_private INTEGER DEFAULT 1
            )
        """)

        # Migration 1: respond_in_groups (v5.7.10)
        try:
            await DB.execute(
                "ALTER TABLE managed_bots "
                "ADD COLUMN respond_in_groups INTEGER DEFAULT 0"
            )
            logger.info(
                "✅ managed_bots: أُضيف عمود respond_in_groups (migration)"
            )
        except Exception as _mig_e:
            _mig_err = str(_mig_e).lower()
            if not ("duplicate" in _mig_err
                    or "already exists" in _mig_err
                    or "duplicate column" in _mig_err):
                logger.warning(
                    "⚠️ ALTER respond_in_groups: %s", _mig_e,
                )

        # 🆕 Migration 2: respond_in_private (v5.7.11)
        try:
            await DB.execute(
                "ALTER TABLE managed_bots "
                "ADD COLUMN respond_in_private INTEGER DEFAULT 1"
            )
            logger.info(
                "✅ managed_bots: أُضيف عمود respond_in_private (migration)"
            )
        except Exception as _mig_e:
            _mig_err = str(_mig_e).lower()
            if not ("duplicate" in _mig_err
                    or "already exists" in _mig_err
                    or "duplicate column" in _mig_err):
                logger.warning(
                    "⚠️ ALTER respond_in_private: %s", _mig_e,
                )

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
            "✅ managed_bots v5.7.11: 4 جداول جاهزة | "
            "respond_in_groups=✅ | respond_in_private=✅ | "
            "split_replies=✅"
        )
    except Exception as e:
        logger.error(
            "❌ managed_bots: فشل إنشاء الجداول: %s", e, exc_info=True
        )


# ═══════════════════════════════════════════════════════════════════════════
# 5. البوتات
# ═══════════════════════════════════════════════════════════════════════════

async def load_managed_bots() -> Dict[int, Dict[str, Any]]:
    await _ensure_tables()
    result: Dict[int, Dict[str, Any]] = {}
    try:
        rows = await DB.fetchall("SELECT * FROM managed_bots")
        for r in rows:
            rd = dict(r) if not isinstance(r, dict) else r
            bid = int(rd.get("bot_id"))

            # groups
            _rig_raw = rd.get("respond_in_groups", 0)
            try:
                _rig_val = bool(int(_rig_raw)) if _rig_raw is not None else False
            except (TypeError, ValueError):
                _rig_val = bool(_rig_raw)

            # 🆕 private — افتراضي True
            _rip_raw = rd.get("respond_in_private", 1)
            try:
                _rip_val = bool(int(_rip_raw)) if _rip_raw is not None else True
            except (TypeError, ValueError):
                _rip_val = True if _rip_raw is None else bool(_rip_raw)

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
                "respond_in_groups": _rig_val,
                "respond_in_private": _rip_val,  # 🆕
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
                _rig = 1 if info.get("respond_in_groups", False) else 0
                _rip = 1 if info.get("respond_in_private", True) else 0
                await DB.execute(
                    """INSERT INTO managed_bots 
                       (bot_id, token, name, msg_start, msg_reply, 
                        msg_third, msg_fourth, added_at, 
                        respond_in_groups, respond_in_private) 
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        int(bid), info["token"], info.get("name", ""),
                        msgs["start"], msgs["reply"],
                        msgs["third"], msgs["fourth"],
                        info.get("added_at", ""),
                        _rig, _rip,
                    )
                )
        return True
    except Exception as e:
        logger.error("❌ save_managed_bots: %s", e, exc_info=True)
        return False


# ═══════════════════════════════════════════════════════════════════════════
# 6. المستخدمون
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


async def update_managed_user_state(
    bid: int, user_id: int, user_state: Dict[str, bool],
) -> bool:
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
# 7. الكلمات المفتاحية
# ═══════════════════════════════════════════════════════════════════════════

async def _load_raw_keyword(bid: int, keyword: str) -> Optional[Any]:
    await _ensure_tables()
    try:
        row = await DB.fetchone(
            "SELECT reply FROM managed_bot_keywords "
            "WHERE bot_id = ? AND keyword = ?",
            (int(bid), keyword),
        )
        if row is None:
            return None
        rd = dict(row) if not isinstance(row, dict) else row
        return _parse_keyword_reply(rd.get("reply"))
    except Exception as e:
        logger.error("_load_raw_keyword(#%s): %s", bid, e)
        return None


async def load_managed_keywords(bid: int) -> Dict[str, Any]:
    await _ensure_tables()
    result: Dict[str, Any] = {}
    try:
        rows = await DB.fetchall(
            "SELECT keyword, reply FROM managed_bot_keywords "
            "WHERE bot_id = ?",
            (int(bid),)
        )
        for r in rows:
            rd = dict(r) if not isinstance(r, dict) else r
            kw = (rd.get("keyword") or "").strip()
            if not kw:
                continue
            parsed = _parse_keyword_reply(rd.get("reply"))
            if parsed is None:
                continue
            result[kw] = parsed
    except Exception as e:
        logger.error("❌ load_managed_keywords(#%s): %s", bid, e)
    return result


async def load_all_keywords() -> Dict[int, Dict[str, Any]]:
    await _ensure_tables()
    result: Dict[int, Dict[str, Any]] = {}
    try:
        rows = await DB.fetchall(
            "SELECT bot_id, keyword, reply FROM managed_bot_keywords"
        )
        for r in rows:
            rd = dict(r) if not isinstance(r, dict) else r
            bid = int(rd.get("bot_id"))
            kw = (rd.get("keyword") or "").strip()
            if not kw:
                continue
            parsed = _parse_keyword_reply(rd.get("reply"))
            if parsed is None:
                continue
            result.setdefault(bid, {})[kw] = parsed
    except Exception as e:
        logger.error("❌ load_all_keywords: %s", e)
    return result


async def save_managed_keywords(
    bid: int, keywords: Dict[str, Any],
) -> bool:
    await _ensure_tables()
    try:
        async with get_lock():
            await DB.execute(
                "DELETE FROM managed_bot_keywords WHERE bot_id = ?",
                (int(bid),)
            )
            now = datetime.now(timezone.utc)
            for kw, entry in keywords.items():
                kw_clean = (kw or "").strip()
                if not kw_clean:
                    continue
                if isinstance(entry, dict):
                    norm = _normalize_keyword_entry(entry)
                    if not norm["private_reply"] and not norm["group_reply"]:
                        continue
                    payload = json.dumps(norm, ensure_ascii=False)
                else:
                    rp_clean = (entry or "").strip() if isinstance(entry, str) else ""
                    if not rp_clean:
                        continue
                    payload = rp_clean

                await DB.execute(
                    """INSERT INTO managed_bot_keywords 
                       (bot_id, keyword, reply, created_at) 
                       VALUES (?, ?, ?, ?)""",
                    (int(bid), kw_clean, payload, now)
                )
        return True
    except Exception as e:
        logger.error(
            "❌ save_managed_keywords(#%s): %s", bid, e, exc_info=True
        )
        return False


async def add_managed_keyword(
    bid: int,
    keyword: str,
    reply: Optional[str] = None,
    *,
    private_reply: Optional[str] = None,
    group_reply: Optional[str] = None,
) -> bool:
    await _ensure_tables()
    kw_clean = (keyword or "").strip()
    if not kw_clean:
        return False

    if private_reply is not None or group_reply is not None:
        norm = {
            "private_reply": str(private_reply or ""),
            "group_reply":   str(group_reply   or ""),
        }
        if not norm["private_reply"] and not norm["group_reply"]:
            return False
        payload = json.dumps(norm, ensure_ascii=False)
    elif reply is not None:
        rp_clean = (reply or "").strip()
        if not rp_clean:
            return False
        payload = rp_clean
    else:
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
                (int(bid), kw_clean, payload, now)
            )
        return True
    except Exception as e:
        logger.error(
            "❌ add_managed_keyword(#%s, %r): %s",
            bid, kw_clean[:30], e, exc_info=True
        )
        return False


async def update_managed_keyword_reply(
    bid: int,
    keyword: str,
    private_reply: Optional[str] = None,
    group_reply: Optional[str] = None,
) -> bool:
    kw_clean = (keyword or "").strip()
    if not kw_clean:
        return False
    if private_reply is None and group_reply is None:
        return False

    await _ensure_tables()
    try:
        current = await _load_raw_keyword(bid, kw_clean)
        if current is None:
            return False

        norm = _normalize_keyword_entry(current)
        if private_reply is not None:
            norm["private_reply"] = str(private_reply)
        if group_reply is not None:
            norm["group_reply"] = str(group_reply)

        if not norm["private_reply"] and not norm["group_reply"]:
            return False

        payload = json.dumps(norm, ensure_ascii=False)

        async with get_lock():
            now = datetime.now(timezone.utc)
            await DB.execute(
                """INSERT INTO managed_bot_keywords 
                   (bot_id, keyword, reply, created_at) 
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT (bot_id, keyword) DO UPDATE SET
                   reply = EXCLUDED.reply,
                   created_at = EXCLUDED.created_at""",
                (int(bid), kw_clean, payload, now)
            )
        return True
    except Exception as e:
        logger.error(
            "❌ update_managed_keyword_reply(#%s, %r): %s",
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
# 8. تتبع الردود
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
# 9. أدوات
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
# 10. __all__
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    "get_default_messages",
    "get_lock",
    "load_managed_bots",
    "save_managed_bots",
    "load_managed_state",
    "save_managed_state",
    "update_managed_user_state",
    "load_managed_keywords",
    "load_all_keywords",
    "save_managed_keywords",
    "add_managed_keyword",
    "update_managed_keyword_reply",
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
    "_normalize_keyword_entry",
]


try:
    logger.debug(
        "🛡️ managed_bots_storage v5.7.11 "
        "(PRIVATE-TOGGLE) loaded | "
        "tables=bots,users,keywords,keyword_replied | "
        "lock=reentrant | churn_fix=targeted | "
        "split_replies=JSON-in-text(backward_compat) | "
        "respond_in_groups=INTEGER(0/1) | "
        "respond_in_private=INTEGER(0/1, default=1)"
    )
except Exception:
    pass