#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers/handlers_managed_public.py — معالجات البوتات المُدارة (v5.7.0)
=================================================================================
📌 المسؤولية:
    • بناء (on_start, on_text) لكل بوت مُدار (bid).
    • منطق الرسائل الأربع المتتالية (start → reply → third → fourth).
    • إدارة حالة المستخدم في الذاكرة + حفظها في managed_bots_state.json.
    • منع الأدمن/المطور من استهلاك دورة الرسائل (للاختبار).
    • قفل per-user (lock striping بـ 64) لتجنب race على double-tap.

🎯 العقد:
    managed_bots_runner.start_one() → يستورد:
        • make_managed_handlers(bid) → (on_start, on_text)
        • post_init_managed(app) → coroutine

    يعتمد على:
        • utils.safe_send — إرسال آمن مع retry
        • managed_bots_storage.load/save_managed_state + get_lock
        • config.CONFIG.PRIMARY_OWNER_ID / DEVELOPER_IDS (skip)

🚫 لا يحتوي:
    • تشغيل/إيقاف البوتات (مكانه: managed_bots_runner.py)
    • لوحة الإدارة (مكانه: handlers_managed_bots.py)
=================================================================================
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Tuple

from telegram import BotCommandScopeDefault
from telegram.ext import Application

from config import CONFIG
from utils import safe_send
from managed_bots_storage import (
    get_default_messages,
    get_lock,
    load_managed_state,
    save_managed_state,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 1. ثوابت
# ═══════════════════════════════════════════════════════════════════════════

_FIELDS: Tuple[str, str, str, str] = ("start", "reply", "third", "fourth")

# عدد stripes للأقفال (per-user lock via hashing) — لا ننشئ 10K lock
_NUM_LOCK_STRIPES = 64


# ═══════════════════════════════════════════════════════════════════════════
# 2. أدوات داخلية
# ═══════════════════════════════════════════════════════════════════════════

def _is_privileged(user_id: int) -> bool:
    """True للأدمن/المطور/المالك — نتجاهلهم (لا يستهلكون الرسائل)."""
    try:
        owner = int(getattr(CONFIG, "PRIMARY_OWNER_ID", 0) or 0)
        if owner and user_id == owner:
            return True
    except (TypeError, ValueError):
        pass

    try:
        devs = getattr(CONFIG, "DEVELOPER_IDS", []) or []
        for d in devs:
            try:
                if int(d) == user_id:
                    return True
            except (TypeError, ValueError):
                continue
    except Exception:
        pass
    return False


def _stripes(app: Application) -> List[asyncio.Lock]:
    """يُنشئ (lazy) قائمة أقفال مشتركة لـ app."""
    stripes = app.bot_data.get("_user_locks")
    if stripes is None:
        stripes = [asyncio.Lock() for _ in range(_NUM_LOCK_STRIPES)]
        app.bot_data["_user_locks"] = stripes
    return stripes


def _lock_for_user(app: Application, user_id: int) -> asyncio.Lock:
    """قفل per-user (striped) — يمنع race على double-tap."""
    return _stripes(app)[int(user_id) % _NUM_LOCK_STRIPES]


def _get_state(app: Application, bid: int) -> Dict[int, Dict[str, bool]]:
    """يحمل حالة هذا البوت مرة واحدة إلى bot_data."""
    state = app.bot_data.get("_managed_state")
    if state is None:
        full = load_managed_state()
        state = full.get(bid, {})
        app.bot_data["_managed_state"] = state
    return state


def _get_messages(app: Application) -> Dict[str, str]:
    """رسائل البوت من bot_data (fallback إلى الافتراضي)."""
    msgs = app.bot_data.get("managed_messages")
    if not isinstance(msgs, dict):
        return get_default_messages()
    return msgs


async def _persist(
    app: Application,
    bid: int,
    state: Dict[int, Dict[str, bool]],
) -> None:
    """حفظ حالة هذا البوت (read-modify-write مع قفل مشترك)."""
    try:
        async with get_lock():
            full = load_managed_state()
            full[bid] = state
            save_managed_state(full)
    except Exception as e:
        logger.warning("managed_bot #%s: persist state: %s", bid, e)


def _ensure_fields(user_state: Dict[str, bool]) -> None:
    """يضمن وجود المفاتيح الأربعة."""
    for f in _FIELDS:
        user_state.setdefault(f, False)


# ═══════════════════════════════════════════════════════════════════════════
# 3. make_managed_handlers — المصنع
# ═══════════════════════════════════════════════════════════════════════════

def make_managed_handlers(bid: int) -> Tuple[Callable, Callable]:
    """
    يبني (on_start, on_text) لبوت محدد.

    المنطق:
        /start  → رسالة "start" (مرة واحدة) → mark start=True
        نص 1    → رسالة "reply"              → mark reply=True
        نص 2    → رسالة "third"              → mark third=True
        نص 3    → رسالة "fourth"             → mark fourth=True
        نص 4+   → صمت (اكتملت الدورة)
        /start#2 → صمت (start=True)
    """

    async def on_start(update: Any, context: Any) -> None:
        try:
            chat = update.effective_chat
            if chat is None or chat.type != "private":
                return
            msg = update.message
            user = update.effective_user
            if msg is None or user is None:
                return
            if _is_privileged(user.id):
                return

            app = context.application
            lock = _lock_for_user(app, user.id)

            async with lock:
                state = _get_state(app, bid)
                user_state = state.get(user.id, {})
                _ensure_fields(user_state)

                if user_state.get("start", False):
                    return  # صمت — بدأ مسبقاً

                msgs = _get_messages(app)
                text = msgs.get("start", "")
                if not text:
                    return

                sent = await safe_send(context.bot, chat.id, text)
                if sent is None:
                    logger.debug(
                        "managed_bot #%s: send 'start' failed for %s",
                        bid, user.id,
                    )
                    return

                user_state = state.setdefault(user.id, {})
                _ensure_fields(user_state)
                user_state["start"] = True
                await _persist(app, bid, state)

        except Exception as e:
            logger.exception("managed_bot #%s on_start: %s", bid, e)

    async def on_text(update: Any, context: Any) -> None:
        try:
            chat = update.effective_chat
            if chat is None or chat.type != "private":
                return
            msg = update.message
            user = update.effective_user
            if msg is None or user is None or not msg.text:
                return
            if _is_privileged(user.id):
                return

            app = context.application
            lock = _lock_for_user(app, user.id)

            async with lock:
                state = _get_state(app, bid)
                user_state = state.get(user.id, {})
                _ensure_fields(user_state)

                msgs = _get_messages(app)

                for field in ("reply", "third", "fourth"):
                    if user_state.get(field, False):
                        continue

                    text = msgs.get(field, "")
                    if not text:
                        return

                    sent = await safe_send(context.bot, chat.id, text)
                    if sent is None:
                        logger.debug(
                            "managed_bot #%s: send '%s' failed for %s",
                            bid, field, user.id,
                        )
                        return

                    user_state = state.setdefault(user.id, {})
                    _ensure_fields(user_state)
                    user_state[field] = True
                    await _persist(app, bid, state)
                    return

                # كل الحقول مفعّلة → صمت

        except Exception as e:
            logger.exception("managed_bot #%s on_text: %s", bid, e)

    return on_start, on_text


# ═══════════════════════════════════════════════════════════════════════════
# 4. post_init_managed
# ═══════════════════════════════════════════════════════════════════════════

async def post_init_managed(app: Application) -> None:
    """
    يمسح أوامر Telegram للبوت المُدار (لا /help، لا /start preview).
    يُستدعى يدوياً من runner بعد app.start().
    """
    try:
        await app.bot.set_my_commands(
            commands=[],
            scope=BotCommandScopeDefault(),
        )
        bid = app.bot_data.get("managed_bid", "?")
        name = app.bot_data.get("managed_name", "")
        logger.info(
            "✅ managed_bot #%s (@%s): commands cleared",
            bid, name or "?",
        )
    except Exception as e:
        logger.warning("post_init_managed: %s", e)


# ═══════════════════════════════════════════════════════════════════════════
# 5. __all__
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    "make_managed_handlers",
    "post_init_managed",
]


# ═══════════════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═══════════════════════════════════════════════════════════════════════════

try:
    logger.debug(
        "🛡️ handlers_managed_public v5.7.0 loaded | "
        "flow=start→reply→third→fourth | "
        "locks=striped(%d) | persist=atomic",
        _NUM_LOCK_STRIPES,
    )
except Exception:
    pass