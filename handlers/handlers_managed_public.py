#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers/handlers_managed_public.py — معالجات البوتات المُدارة (v5.7.16)
=================================================================================
🆕 v5.7.16 (TARGETED-PERSIST-FIX) — CRITICAL:
    🔴 FIX-CHURN-1: استخدام `update_managed_user_state()` بدلاً من
       `save_managed_state()`.
    
    المشكلة:
        `_persist()` القديمة كانت تستدعي `save_managed_state()` التي
        تُنفّذ UPSERT على **كل** صفوف المستخدمين في كل مرة.
        مع 8 بوتات × 130 مستخدم = 1,040 UPSERT **لكل رسالة**.
        النتيجة: churn كارثي على `managed_bot_users` (~1,040 dead tuple/رسالة).

    الحل:
        `_persist_user()` الجديدة تستدعي `update_managed_user_state()`
        التي تُحدّث **صفاً واحداً فقط** عبر UPSERT مباشر.
        تقليل الـ churn بنسبة ~1,000×.

    `_persist()` القديمة محفوظة (deprecated) للتوافق فقط.

🆕 v5.7.15 (SEQUENCE-DELAY-5S) — محفوظ.
🆕 v5.7.14 (SEQUENCE-DELAY-AFTER-KEYWORD) — محفوظ.
🆕 v5.7.13 (KEYWORD-THEN-SEQUENCE) — محفوظ.
🆕 v5.7.12 (SMART-ARABIC-MATCH) — محفوظ.
🆕 v5.7.9 (KEYWORD-DELAY-5S) — محفوظ.
🆕 v5.7.8 (ONE-TIME-KEYWORD) — محفوظ.
=================================================================================
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable, Dict, List, Tuple

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
    # 🆕 v5.7.16 FIX-CHURN-1
    update_managed_user_state,
)

logger = logging.getLogger(__name__)

_FIELDS: Tuple[str, str, str, str] = ("start", "reply", "third", "fourth")
_NUM_LOCK_STRIPES = 64

# 🆕 v5.7.9: تأخير رد الكلمة المفتاحية (بالثواني)
_KEYWORD_REPLY_DELAY_SEC = 5.0

# 🆕 v5.7.15: تأخير بين رد الكلمة والرسالة التالية (بالثواني)
_SEQUENCE_DELAY_SEC = 5.0


# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v5.7.12: مطابقة عربية ذكية (FIX-MATCH-1)
# ═══════════════════════════════════════════════════════════════════════════

_ARABIC_DIACRITICS_RE = re.compile(r'[\u064B-\u065F\u0670\u06D6-\u06ED]')
_ARABIC_HAMZA_RE = re.compile(r'[إأآٱ]')
_ARABIC_BOUNDARY_BEFORE = r'(?:^|[\s،.!?؟؛:()\[\]"\'«»\-])'
_ARABIC_BOUNDARY_AFTER = r'(?=[\s،.!?؟؛:()\[\]"\'«»\-]|$)'
_ARABIC_PREFIX = r'(?:يا\s?)?(?:[وفبلك]?(?:ال)?)?'


def _normalize_arabic(text: str) -> str:
    """تطبيع النص العربي: إزالة التشكيل، توحيد الهمزات والتاء المربوطة."""
    if not text:
        return ""
    text = _ARABIC_DIACRITICS_RE.sub('', text)
    text = _ARABIC_HAMZA_RE.sub('ا', text)
    text = text.replace('ة', 'ه')
    return text.strip().lower()


def _smart_match_arabic(keyword: str, text: str) -> bool:
    """مطابقة كلمة عربية كاملة داخل نص (مع دعم البادئات الشائعة)."""
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


def _get_keywords(app: Application) -> Dict[str, str]:
    kws = app.bot_data.get("managed_keywords")
    if not isinstance(kws, dict):
        return {}
    return kws


# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v5.7.16 FIX-CHURN-1: تحديث صف واحد فقط (بدل UPSERT كل الجداول)
# ═══════════════════════════════════════════════════════════════════════════

async def _persist_user(
    app: Application,
    bid: int,
    user_id: int,
    user_state: Dict[str, bool],
) -> None:
    """
    🆕 v5.7.16 FIX-CHURN-1: يحفظ صف مستخدم واحد فقط (churn fix).

    بدل `_persist()` القديمة التي كانت تُنفّذ ~1,040 UPSERT لكل رسالة،
    هذه الدالة تُنفّذ UPSERT واحدة فقط على `managed_bot_users`.

    Args:
        app: Application (غير مستخدم — للتوافق مع _persist القديمة)
        bid: bot_id
        user_id: Telegram user_id
        user_state: dict بحالة المستخدم {"start", "reply", "third", "fourth"}
    """
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
    """
    ⚠️ DEPRECATED (v5.7.16): استخدم `_persist_user()` بدلاً منها.

    محفوظة للتوافق مع أي كود قديم. في المسارات الحالية لم تعد
    تُستدعى — استُبدلت بـ `_persist_user()`.

    ❌ لا تستخدمها في معالجة الرسائل — تُنفّذ UPSERT على كل المستخدمين.
    """
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
    user_text: str, keywords: Dict[str, str],
) -> Tuple[str, str]:
    """مطابقة ذكية: يبحث عن أول كلمة مفتاحية (الأطول أولاً)."""
    if not user_text or not keywords:
        return "", ""

    sorted_kws = sorted(keywords.items(), key=lambda x: -len(x[0]))
    for kw, reply in sorted_kws:
        if _smart_match_arabic(kw, user_text):
            return kw, reply

    return "", ""


def make_managed_handlers(bid: int) -> Tuple[Callable, Callable]:
    """
    يبني (on_start, on_text) لبوت محدد.
    💡 في الخاص فقط.
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
                # 🆕 v5.7.16 FIX-CHURN-1: صف واحد فقط
                await _persist_user(app, bid, user.id, user_state)

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
                keyword_sent = False

                # ═══ 1. الكلمات المفتاحية ═══
                keywords = _get_keywords(app)
                if keywords:
                    kw_matched, reply = _find_keyword_match(
                        msg.text, keywords
                    )
                    if kw_matched and reply:
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
                            "%.1fs for user %s",
                            bid, _KEYWORD_REPLY_DELAY_SEC, user.id,
                        )
                        await asyncio.sleep(_KEYWORD_REPLY_DELAY_SEC)

                        sent = await safe_send(
                            context.bot, chat.id, reply
                        )
                        if sent is None:
                            return

                        await mark_keyword_as_replied(
                            bid, user.id, kw_matched
                        )
                        keyword_sent = True
                        logger.debug(
                            "managed_bot #%s: keyword '%s' "
                            "replied once (delayed) for user %s",
                            bid, kw_matched[:30], user.id,
                        )

                # 🆕 v5.7.15 FIX-FLOW-3: تأخير 5s قبل التسلسل
                if keyword_sent:
                    logger.debug(
                        "managed_bot #%s: delaying %.1fs before "
                        "sequence for user %s",
                        bid, _SEQUENCE_DELAY_SEC, user.id,
                    )
                    await asyncio.sleep(_SEQUENCE_DELAY_SEC)

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
                    # 🆕 v5.7.16 FIX-CHURN-1: صف واحد فقط
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
        logger.info(
            "✅ managed_bot #%s (@%s): commands cleared",
            bid, name or "?",
        )
    except Exception as e:
        logger.warning("post_init_managed: %s", e)


__all__ = ["make_managed_handlers", "post_init_managed"]


try:
    logger.debug(
        "🛡️ handlers_managed_public v5.7.16 "
        "(TARGETED-PERSIST-FIX) loaded | "
        "keyword_delay=%.1fs | sequence_delay=%.1fs | "
        "flow=keywords(once,smart)→sleep→reply→third→fourth | "
        "locks=striped(%d) | private_only=True | "
        "match=word_boundary+arabic_norm | "
        "churn_fix=persist_user(targeted)",
        _KEYWORD_REPLY_DELAY_SEC,
        _SEQUENCE_DELAY_SEC,
        _NUM_LOCK_STRIPES,
    )
except Exception:
    pass