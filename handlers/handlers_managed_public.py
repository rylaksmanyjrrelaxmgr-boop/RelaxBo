#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers/handlers_managed_public.py — معالجات البوتات المُدارة (v5.7.7 - KEYWORDS)
=================================================================================
📌 المسؤولية:
    • بناء (on_start, on_text) لكل بوت مُدار (bid).
    • مطابقة الكلمات المفتاحية في on_text (قبل التسلسل).
    • إذا وُجدت كلمة → يرد بها (لا يتقدم التسلسل).
    • إذا لم توجد → يكمل التسلسل (reply → third → fourth).
    • إدارة حالة المستخدم في الذاكرة + حفظها في قاعدة البيانات.
    • قفل per-user (lock striping) لتجنب race على double-tap.

🆕 v5.7.7 (KEYWORDS):
    • إضافة دالة _find_keyword_match للبحث عن الكلمات.
    • مطابقة ذكية: تبحث عن الكلمة داخل نص المستخدم (سواء في البداية أو الوسط).
    • الأولوية للكلمات الأطول (أكثر تحديداً).
    • في الخاص فقط: البوت يتجاهل المجموعات تماماً.
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
    """قفل per-user (striped)."""
    return _stripes(app)[int(user_id) % _NUM_LOCK_STRIPES]


async def _get_state(
    app: Application, bid: int,
) -> Dict[int, Dict[str, bool]]:
    """يحمل حالة هذا البوت مرة واحدة إلى bot_data."""
    state = app.bot_data.get("_managed_state")
    if state is None:
        full = await load_managed_state()
        state = full.get(bid, {})
        app.bot_data["_managed_state"] = state
    return state


def _get_messages(app: Application) -> Dict[str, str]:
    """رسائل البوت من bot_data."""
    msgs = app.bot_data.get("managed_messages")
    if not isinstance(msgs, dict):
        return get_default_messages()
    return msgs


def _get_keywords(app: Application) -> Dict[str, str]:
    """🆕 v5.7.7: كلمات هذا البوت من bot_data."""
    kws = app.bot_data.get("managed_keywords")
    if not isinstance(kws, dict):
        return {}
    return kws


async def _persist(
    app: Application,
    bid: int,
    state: Dict[int, Dict[str, bool]],
) -> None:
    """حفظ حالة هذا البوت (read-modify-write)."""
    try:
        async with get_lock():
            full = await load_managed_state()
            full[bid] = state
            await save_managed_state(full)
    except Exception as e:
        logger.warning("managed_bot #%s: persist state: %s", bid, e)


def _ensure_fields(user_state: Dict[str, bool]) -> None:
    for f in _FIELDS:
        user_state.setdefault(f, False)


# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v5.7.7: مطابقة الكلمات المفتاحية
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_for_match(text: str) -> str:
    """تطبيع النص للمطابقة (trim + lowercase)."""
    if not text:
        return ""
    return text.strip().lower()


def _find_keyword_match(
    user_text: str, keywords: Dict[str, str],
) -> Tuple[str, str]:
    """
    يبحث عن أول كلمة مفتاحية موجودة في نص المستخدم.
    
    Returns: (keyword, reply) أو ("", "") إذا لم يوجد.
    
    💡 الأولوية: الكلمات الأطول أولاً (أكثر تحديداً).
       مثال: لو أضفت "اليمن" و "أنا من اليمن"،
              فالبوت سيفضل "أنا من اليمن" عند مطابقتها.
    """
    if not user_text or not keywords:
        return "", ""

    text_norm = _normalize_for_match(user_text)
    if not text_norm:
        return "", ""

    # ترتيب الكلمات بالأطول أولاً
    sorted_kws = sorted(keywords.items(), key=lambda x: -len(x[0]))
    for kw, reply in sorted_kws:
        kw_norm = _normalize_for_match(kw)
        if kw_norm and kw_norm in text_norm:
            return kw, reply

    return "", ""


# ═══════════════════════════════════════════════════════════════════════════
# 3. make_managed_handlers
# ═══════════════════════════════════════════════════════════════════════════

def make_managed_handlers(bid: int) -> Tuple[Callable, Callable]:
    """
    يبني (on_start, on_text) لبوت محدد.

    المنطق:
        /start  → رسالة "start" (مرة واحدة)
        
        نص:
          1. ابحث في الكلمات المفتاحية → إذا وُجدت → رد بها (لا يتقدم التسلسل)
          2. إذا لم تُوجد → أكمل التسلسل (reply → third → fourth)
        
        ⚠️ في الخاص فقط (المجموعات تُتجاهل تماماً).
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
                state = await _get_state(app, bid)
                user_state = state.get(user.id, {})
                _ensure_fields(user_state)

                if user_state.get("start", False):
                    return

                msgs = _get_messages(app)
                text = msgs.get("start", "")
                if not text:
                    return

                sent = await safe_send(context.bot, chat.id, text)
                if sent is None:
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
            # ⚠️ في الخاص فقط — المجموعات تُتجاهل تماماً
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
                # ═══ 1. الكلمات المفتاحية أولاً ═══
                keywords = _get_keywords(app)
                if keywords:
                    kw_matched, reply = _find_keyword_match(
                        msg.text, keywords
                    )
                    if kw_matched and reply:
                        sent = await safe_send(
                            context.bot, chat.id, reply
                        )
                        if sent is not None:
                            logger.debug(
                                "managed_bot #%s: keyword '%s' "
                                "matched for user %s",
                                bid, kw_matched[:30], user.id,
                            )
                            return  # ✅ لا يتقدم التسلسل

                # ═══ 2. التسلسل الأربع ═══
                state = await _get_state(app, bid)
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
        "🛡️ handlers_managed_public v5.7.7 (KEYWORDS) loaded | "
        "flow=keywords→reply→third→fourth | "
        "locks=striped(%d) | private_only=True",
        _NUM_LOCK_STRIPES,
    )
except Exception:
    pass