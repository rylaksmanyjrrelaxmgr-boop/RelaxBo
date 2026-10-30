#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers/handlers_managed_public.py — معالجات البوتات المُدارة (v5.7.19)
=================================================================================
🆕 v5.7.19 (PRIVATE-TOGGLE):
    🟢 FEATURE-PRIVATE-TOGGLE: زر 💬 يوقف/يشغّل كل شيء في الخاص.
    • `_get_respond_in_private()` يقرأ `bot_data["respond_in_private"]`.
    • عند 🔴: on_start يعود + on_text في الخاص يعود (لا كلمات ولا تسلسل).
    • عند 🟢 (افتراضي): كل شيء يعمل كما في v5.7.16.

✅ محفوظ من v5.7.18: SPLIT-REPLIES-ALWAYS-IN-GROUPS.
✅ محفوظ من v5.7.16: FIX-CHURN-1.
=================================================================================
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from telegram import BotCommandScopeDefault
from telegram.ext import Application

from config import CONFIG
from utils import safe_send
from managed_bots_storage import (
    get_default_messages,
    get_lock,
    is_keyword_already_replied,
    load_managed_state,
    mark_keyword_as_replied,
    save_managed_state,
    update_managed_user_state,
)

logger = logging.getLogger(__name__)

_FIELDS: Tuple[str, str, str, str] = ("start", "reply", "third", "fourth")
_NUM_LOCK_STRIPES = 64

_KEYWORD_REPLY_DELAY_SEC = 5.0
_SEQUENCE_DELAY_SEC = 5.0


# ═══════════════════════════════════════════════════════════════════════════
# مطابقة عربية ذكية
# ═══════════════════════════════════════════════════════════════════════════

_ARABIC_DIACRITICS_RE = re.compile(r'[\u064B-\u065F\u0670\u06D6-\u06ED]')
_ARABIC_HAMZA_RE = re.compile(r'[إأآٱ]')
_ARABIC_BOUNDARY_BEFORE = r'(?:^|[\s،.!?؟؛:()\[\]"\'«»\-])'
_ARABIC_BOUNDARY_AFTER = r'(?=[\s،.!?؟؛:()\[\]"\'«»\-]|$)'
_ARABIC_PREFIX = r'(?:يا\s?)?(?:[وفبلك]?(?:ال)?)?'


def _normalize_arabic(text: str) -> str:
    if not text:
        return ""
    text = _ARABIC_DIACRITICS_RE.sub('', text)
    text = _ARABIC_HAMZA_RE.sub('ا', text)
    text = text.replace('ة', 'ه')
    return text.strip().lower()


def _smart_match_arabic(keyword: str, text: str) -> bool:
    if not keyword or not text:
        return False
    norm_kw = _normalize_arabic(keyword.strip())
    norm_text = _normalize_arabic(text.strip())
    if not norm_kw or not norm_text:
        return False
    kw_escaped = re.escape(norm_kw)
    pattern = (
        f'{_ARABIC_BOUNDARY_BEFORE}'
        f'{_ARABIC_PREFIX}'
        f'{kw_escaped}'
        f'{_ARABIC_BOUNDARY_AFTER}'
    )
    try:
        return bool(re.search(pattern, norm_text, re.UNICODE))
    except re.error as _re_err:
        logger.warning(
            "_smart_match_arabic: regex error for %r: %s",
            keyword, _re_err,
        )
        return False


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


# ═══════════════════════════════════════════════════════════════════════════
# أدوات داخلية
# ═══════════════════════════════════════════════════════════════════════════

def _is_privileged(user_id: int) -> bool:
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
    stripes = app.bot_data.get("_user_locks")
    if stripes is None:
        stripes = [asyncio.Lock() for _ in range(_NUM_LOCK_STRIPES)]
        app.bot_data["_user_locks"] = stripes
    return stripes


def _lock_for_user(app: Application, user_id: int) -> asyncio.Lock:
    return _stripes(app)[int(user_id) % _NUM_LOCK_STRIPES]


async def _get_state(
    app: Application, bid: int,
) -> Dict[int, Dict[str, bool]]:
    state = app.bot_data.get("_managed_state")
    if state is None:
        full = await load_managed_state()
        state = full.get(bid, {})
        app.bot_data["_managed_state"] = state
    return state


def _get_messages(app: Application) -> Dict[str, str]:
    msgs = app.bot_data.get("managed_messages")
    if not isinstance(msgs, dict):
        return get_default_messages()
    return msgs


def _get_keywords(app: Application) -> Dict[str, Any]:
    kws = app.bot_data.get("managed_keywords")
    if not isinstance(kws, dict):
        return {}
    return kws


def _get_respond_in_groups(app: Application) -> bool:
    try:
        return bool(app.bot_data.get("respond_in_groups", False))
    except Exception:
        return False


# 🆕 v5.7.19
def _get_respond_in_private(app: Application) -> bool:
    """
    🆕 v5.7.19: هل الردود في الخاص مفعّلة؟
    الافتراضي: True (توافق كامل مع الأصلي).
    """
    try:
        return bool(app.bot_data.get("respond_in_private", True))
    except Exception:
        return True


# ═══════════════════════════════════════════════════════════════════════════
# persist
# ═══════════════════════════════════════════════════════════════════════════

async def _persist_user(
    app: Application,
    bid: int,
    user_id: int,
    user_state: Dict[str, bool],
) -> None:
    try:
        await update_managed_user_state(bid, user_id, user_state)
    except Exception as e:
        logger.warning(
            "managed_bot #%s: persist user %s: %s",
            bid, user_id, e,
        )


async def _persist(
    app: Application,
    bid: int,
    state: Dict[int, Dict[str, bool]],
) -> None:
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


def _find_keyword_match(
    user_text: str,
    keywords: Dict[str, Any],
    chat_type: str = "private",
) -> Tuple[str, str]:
    if not user_text or not keywords:
        return "", ""
    sorted_kws = sorted(keywords.items(), key=lambda x: -len(x[0]))
    for kw, entry in sorted_kws:
        if not _smart_match_arabic(kw, user_text):
            continue
        norm = _normalize_keyword_entry(entry)
        if chat_type == "group":
            reply = norm["group_reply"]
        else:
            reply = norm["private_reply"]
        if reply:
            return kw, reply
    return "", ""


# ═══════════════════════════════════════════════════════════════════════════
# make_managed_handlers
# ═══════════════════════════════════════════════════════════════════════════

def make_managed_handlers(bid: int) -> Tuple[Callable, Callable]:
    """
    🆕 v5.7.19:
        • on_start: خاص فقط + فحص respond_in_private
        • on_text:  خاص (كلمات+تسلسل، فحص respond_in_private)
                    مجموعات (كلمات فقط، فحص respond_in_groups)
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

            # 🆕 v5.7.19: فحص hot — إن كان الخاص معطّلاً، لا نرد
            if not _get_respond_in_private(app):
                return

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
                await _persist_user(app, bid, user.id, user_state)

        except Exception as e:
            logger.exception("managed_bot #%s on_start: %s", bid, e)

    async def on_text(update: Any, context: Any) -> None:
        try:
            chat = update.effective_chat
            if chat is None:
                return
            msg = update.message
            user = update.effective_user
            if msg is None or user is None or not msg.text:
                return
            if _is_privileged(user.id):
                return

            is_private = chat.type == "private"
            is_group = chat.type in ("group", "supergroup")

            if not is_private and not is_group:
                return

            app = context.application

            # 🆕 v5.7.19: فحص الخاص أولاً
            if is_private and not _get_respond_in_private(app):
                return

            # v5.7.18: فحص المجموعات
            if is_group and not _get_respond_in_groups(app):
                return

            lock = _lock_for_user(app, user.id)

            async with lock:
                keyword_sent = False

                keywords = _get_keywords(app)
                if keywords:
                    kw_matched, reply = _find_keyword_match(
                        msg.text, keywords,
                        chat_type=("group" if is_group else "private"),
                    )
                    if kw_matched and reply:
                        if is_private:
                            already = await is_keyword_already_replied(
                                bid, user.id, kw_matched
                            )
                            if already:
                                logger.debug(
                                    "managed_bot #%s: keyword '%s' "
                                    "already replied to user %s — silent",
                                    bid, kw_matched[:30], user.id,
                                )
                                return

                        logger.debug(
                            "managed_bot #%s: delaying keyword reply "
                            "%.1fs for user %s (chat_type=%s)",
                            bid, _KEYWORD_REPLY_DELAY_SEC, user.id,
                            chat.type,
                        )
                        await asyncio.sleep(_KEYWORD_REPLY_DELAY_SEC)

                        sent = await safe_send(
                            context.bot, chat.id, reply
                        )
                        if sent is None:
                            return

                        if is_private:
                            await mark_keyword_as_replied(
                                bid, user.id, kw_matched
                            )

                        keyword_sent = True
                        logger.debug(
                            "managed_bot #%s: keyword '%s' replied "
                            "(chat_type=%s, once=%s)",
                            bid, kw_matched[:30], chat.type,
                            is_private,
                        )

                if is_group:
                    return

                if keyword_sent:
                    logger.debug(
                        "managed_bot #%s: delaying %.1fs before "
                        "sequence for user %s",
                        bid, _SEQUENCE_DELAY_SEC, user.id,
                    )
                    await asyncio.sleep(_SEQUENCE_DELAY_SEC)

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
                    await _persist_user(app, bid, user.id, user_state)
                    return

        except Exception as e:
            logger.exception("managed_bot #%s on_text: %s", bid, e)

    return on_start, on_text


async def post_init_managed(app: Application) -> None:
    try:
        await app.bot.set_my_commands(
            commands=[],
            scope=BotCommandScopeDefault(),
        )
        bid = app.bot_data.get("managed_bid", "?")
        name = app.bot_data.get("managed_name", "")
        groups_on = bool(app.bot_data.get("respond_in_groups", False))
        private_on = bool(app.bot_data.get("respond_in_private", True))
        logger.info(
            "✅ managed_bot #%s (@%s): commands cleared | "
            "groups=%s | private=%s",
            bid, name or "?", groups_on, private_on,
        )
    except Exception as e:
        logger.warning("post_init_managed: %s", e)


__all__ = ["make_managed_handlers", "post_init_managed"]


try:
    logger.debug(
        "🛡️ handlers_managed_public v5.7.19 "
        "(PRIVATE-TOGGLE) loaded | "
        "keyword_delay=%.1fs | sequence_delay=%.1fs | "
        "flow_private=keywords(once,smart)+sequence (if_enabled, default_on) | "
        "flow_groups=keywords(always,smart,if_enabled) | "
        "locks=striped(%d) | churn_fix=persist_user(targeted)",
        _KEYWORD_REPLY_DELAY_SEC,
        _SEQUENCE_DELAY_SEC,
        _NUM_LOCK_STRIPES,
    )
except Exception:
    pass