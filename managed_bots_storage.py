#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
managed_bots_storage.py — طبقة I/O ذرية للبوتات المُدارة (v5.7.3 - DB-MIGRATION)
=================================================================================
📌 المسؤولية:
    • حفظ التوكنات والرسائل في جداول قاعدة البيانات (managed_bots).
    • حفظ تقدم المستخدمين في جدول (managed_bot_users).
    • إزالة الاعتماد على ملفات JSON لضمان عدم فقدان البيانات
      عند إعادة النشر على منصات مثل Render.

🎯 التغيير الأساسي عن v5.7.0:
    • كل الدوال الأربع الرئيسية أصبحت async (لأن DB غير متزامن).
    • لا ملفات JSON. لا .bak. لا chmod 0600.
    • الجداول تُنشأ تلقائياً عند أول استدعاء (_ensure_tables).
=================================================================================
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from config import CONFIG
from database import DB

logger = logging.getLogger(__name__)

_io_lock: Optional[asyncio.Lock] = None
_tables_created = False


def get_lock() -> asyncio.Lock:
    """Lazy init — آمن عند الاستيراد قبل وجود event loop."""
    global _io_lock
    if _io_lock is None:
        _io_lock = asyncio.Lock()
    return _io_lock


_FALLBACK_MESSAGES: Dict[str, str] = {
    "start":  "👋 أهلاً بك!",
    "reply":  "📩 تم استلام رسالتك.",
    "third":  "✅ شكرًا لتواصلك.",
    "fourth": "🙏 نتمنى لك يومًا سعيدًا.",
}


def get_default_messages() -> Dict[str, str]:
    """أولويات: 1) CONFIG 2) القيمة الافتراضية"""
    return {
        k: str(getattr(CONFIG, f"MANAGED_{k.upper()}_MESSAGE", None)
               or _FALLBACK_MESSAGES[k])
        for k in ("start", "reply", "third", "fourth")
    }


async def _ensure_tables():
    """
    إنشاء الجداول تلقائياً عند أول استخدام.
    آمنة للاستدعاء المتكرر (IF NOT EXISTS).
    """
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
        _tables_created = True
        logger.info("✅ managed_bots: تم التأكد من إنشاء الجداول في DB")
    except Exception as e:
        logger.error(
            "❌ managed_bots: فشل إنشاء الجداول: %s", e, exc_info=True
        )


async def load_managed_bots() -> Dict[int, Dict[str, Any]]:
    """يقرأ جميع البوتات من قاعدة البيانات."""
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
                    "start": str(rd.get("msg_start") or _FALLBACK_MESSAGES["start"]),
                    "reply": str(rd.get("msg_reply") or _FALLBACK_MESSAGES["reply"]),
                    "third": str(rd.get("msg_third") or _FALLBACK_MESSAGES["third"]),
                    "fourth": str(rd.get("msg_fourth") or _FALLBACK_MESSAGES["fourth"]),
                },
                "added_at": str(rd.get("added_at") or ""),
            }
    except Exception as e:
        logger.error("❌ load_managed_bots: %s", e)
    return result


async def save_managed_bots(bots: Dict[int, Dict[str, Any]]) -> bool:
    """
    يحفظ القاموس كاملاً (DELETE + INSERT لضمان التطابق التام).
    عدد البوتات عادة صغير (< 50)، لذلك DELETE+INSERT آمن وسريع.
    """
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
                        msgs["start"], msgs["reply"], msgs["third"], msgs["fourth"],
                        info.get("added_at", "")
                    )
                )
        return True
    except Exception as e:
        logger.error("❌ save_managed_bots: %s", e, exc_info=True)
        return False


async def load_managed_state() -> Dict[int, Dict[int, Dict[str, bool]]]:
    """يقرأ حالة جميع المستخدمين من قاعدة البيانات."""
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
                "start": bool(rd.get("started")),
                "reply": bool(rd.get("replied")),
                "third": bool(rd.get("third")),
                "fourth": bool(rd.get("fourth")),
            }
    except Exception as e:
        logger.error("❌ load_managed_state: %s", e)
    return result


async def save_managed_state(
    state: Dict[int, Dict[int, Dict[str, bool]]],
) -> bool:
    """
    يحفظ حالة المستخدمين.
    استراتيجية:
      - حذف البوتات التي أُزيلت من state.
      - UPSERT لكل مستخدم (ON CONFLICT DO UPDATE).
    """
    await _ensure_tables()
    try:
        async with get_lock():
            # حذف البوتات التي لم تعد موجودة
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

            # UPSERT لكل مستخدم
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
                            st.get("start", False), st.get("reply", False),
                            st.get("third", False), st.get("fourth", False),
                            now
                        )
                    )
        return True
    except Exception as e:
        logger.error("❌ save_managed_state: %s", e, exc_info=True)
        return False


def next_managed_bot_id(existing: Dict[int, Any]) -> int:
    """أول رقم موجب غير مستخدم."""
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
    """حالة مستخدم جديد."""
    return {"start": False, "reply": False, "third": False, "fourth": False}


def get_stats(
    bots: Dict[int, Dict[str, Any]],
    state: Dict[int, Dict[int, Dict[str, bool]]],
) -> Dict[str, int]:
    """إحصاء سريع للعرض في اللوحة."""
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
    """للتوافق فقط. التخزين الآن في قاعدة البيانات."""
    return {"db_migration": True, "status": "ok"}


__all__ = [
    "get_default_messages",
    "get_lock",
    "load_managed_bots",
    "save_managed_bots",
    "load_managed_state",
    "save_managed_state",
    "next_managed_bot_id",
    "ensure_default_state",
    "get_stats",
    "health_check",
]


# ═══════════════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═══════════════════════════════════════════════════════════════════════════

try:
    logger.debug(
        "🛡️ managed_bots_storage v5.7.3 (DB-MIGRATION) loaded | "
        "tables=managed_bots,managed_bot_users | "
        "lazy_create=True | lock=lazy"
    )
except Exception:
    pass