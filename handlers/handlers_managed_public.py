#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers/handlers_managed_public.py — معالجات البوتات المُدارة (v5.7.18)
=================================================================================
🆕 v5.7.18 (SPLIT-REPLIES-ALWAYS-IN-GROUPS):
    🟢 FEATURE-SPLIT-1: ردود منفصلة للخاص والمجموعات.
    🟢 FEATURE-ALWAYS-1: في المجموعات، يرد كل مرة تُذكر الكلمة.

    السلوك النهائي:
        • الخاص (chat.type == "private"):
            - /start → تسلسل 4 رسائل (بدون تغيير عن v5.7.16)
            - كلمة  → رد `private_reply` (مرة واحدة لكل مستخدم/كلمة)
            - بعد الكلمة → تأخير 5s → تسلسل (reply→third→fourth)

        • المجموعات (chat.type == "group"|"supergroup"):
            - /start → يتجاهل (لا CommandHandler)
            - كلمة  → رد `group_reply` (كل مرة تذكر)
            - لا تسلسل بعد الكلمة

        • التفعيل:
            - `_get_respond_in_groups(app)` يقرأ
              `app.bot_data["respond_in_groups"]`
            - يُضبط في `start_one()` من `managed_bots_runner`
            - يُغيَّر hot من زر 📢 (بدون restart)

    البنية الجديدة للكلمات:
        keywords = {
            "اليمن": {
                "private_reply": "أهلاً يا يمني 🇾🇪",
                "group_reply":   "🇾🇪 صنعاء عاصمة اليمن",
            },
        }

    توافق رجعي:
        الكلمات القديمة (str) → private=group=str
        عبر `_normalize_keyword_entry()`

✅ محفوظ من v5.7.16: FIX-CHURN-1 (targeted persist).
✅ محفوظ من v5.7.15: SEQUENCE-DELAY-5S.
✅ محفوظ من v5.7.14: SEQUENCE-DELAY-AFTER-KEYWORD.
✅ محفوظ من v5.7.13: KEYWORD-THEN-SEQUENCE.
✅ محفوظ من v5.7.12: SMART-ARABIC-MATCH.
✅ محفوظ من v5.7.9: KEYWORD-DELAY-5S.
✅ محفوظ من v5.7.8: ONE-TIME-KEYWORD.
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
    # v5.7.16 FIX-CHURN-1
    update_managed_user_state,
)

logger = logging.getLogger(__name__)

_FIELDS: Tuple[str, str, str, str] = ("start", "reply", "third", "fourth")
_NUM_LOCK_STRIPES = 64

# v5.7.9: تأخير رد الكلمة المفتاحية (بالثواني)
_KEYWORD_REPLY_DELAY_SEC = 5.0

# v5.7.15: تأخير بين رد الكلمة والرسالة التالية (بالثواني)
_SEQUENCE_DELAY_SEC = 5.0


# ═══════════════════════════════════════════════════════════════════════════
# v5.7.12: مطابقة عربية ذكية (FIX-MATCH-1)
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
# 🆕 v5.7.18: normalize keyword entry (توافق رجعي كامل)
# ═══════════════════════════════════════════════════════════════════════════

def _normalize_keyword_entry(entry: Any) -> Dict[str, str]:
    """
    🆕 v5.7.18: يحوّل أي شكل للشكل الجديد.

    • dict جديد {private_reply, group_reply} → كما هو
    • str قديم → private=group=str (توافق رجعي)
    • None/فارغ → {"private_reply": "", "group_reply": ""}
    """
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


# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v5.7.18: قراءة حالة الردود في المجموعات (Hot-toggle)
# ═══════════════════════════════════════════════════════════════════════════

def _get_respond_in_groups(app: Application) -> bool:
    """
    🆕 v5.7.18: هل الردود في المجموعات مفعّلة لهذا البوت؟

    تُقرأ من `app.bot_data["respond_in_groups"]` التي يضبطها الـ runner
    عند `start_one(bid, token)` بناءً على `bot_info["respond_in_groups"]`.

    الافتراضي: False (معطّل — سلوك متوافق مع v5.7.16).

    ⚠️ Hot-toggle: `set_respond_in_groups()` في runner تُحدّث هذه القيمة
    في الذاكرة فوراً — بدون إعادة تشغيل البوت.
    """
    try:
        return bool(app.bot_data.get("respond_in_groups", False))
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# v5.7.16 FIX-CHURN-1: targeted persist (بدل UPSERT كل الجداول)
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


# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v5.7.18: مطابقة مع اختيار الرد المناسب حسب chat_type
# ═══════════════════════════════════════════════════════════════════════════

def _find_keyword_match(
    user_text: str,
    keywords: Dict[str, Any],
    chat_type: str = "private",
) -> Tuple[str, str]:
    """
    🆕 v5.7.18: مطابقة ذكية + اختيار الرد المناسب.

    Args:
        user_text: نص المستخدم
        keywords: dict {kw: str-or-dict}
        chat_type: "private" أو "group"

    Returns:
        (matched_keyword, reply_text) أو ("", "") إذا لا مطابقة

    ملاحظة:
        - يبحث من الأطول إلى الأقصر (لتجنب تفضيل كلمات قصيرة).
        - إذا كان الحقل المطلوب فارغاً (مثلاً group_reply=""), 
          يتخطى الكلمة ويبحث عن التالية.
    """
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
        # إذا لا رد لهذا النوع — جرب الكلمة التالية
    return "", ""


# ═══════════════════════════════════════════════════════════════════════════
# make_managed_handlers
# ═══════════════════════════════════════════════════════════════════════════

def make_managed_handlers(bid: int) -> Tuple[Callable, Callable]:
    """
    يبني (on_start, on_text) لبوت محدد.

    🆕 v5.7.18:
        • on_start: خاص فقط (بدون تغيير — /start في مجموعة يُتجاهل)
        • on_text:  خاص ← كلمات + تسلسل (بدون تغيير)
                    مجموعة ← كلمات فقط (شرطياً حسب respond_in_groups)
    """

    async def on_start(update: Any, context: Any) -> None:
        """يستجيب /start في الخاص فقط. لا تغيير عن v5.7.16."""
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
                # v5.7.16 FIX-CHURN-1: صف واحد فقط
                await _persist_user(app, bid, user.id, user_state)

        except Exception as e:
            logger.exception("managed_bot #%s on_start: %s", bid, e)

    async def on_text(update: Any, context: Any) -> None:
        """
        🆕 v5.7.18: يدعم الخاص + المجموعات (شرطياً).

        • الخاص:      كلمات مفتاحية + تسلسل (بدون تغيير)
        • المجموعات:  كلمات مفتاحية فقط (عند التفعيل)
        """
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

            # 🆕 v5.7.18: تحديد نوع المحادثة
            is_private = chat.type == "private"
            is_group = chat.type in ("group", "supergroup")

            if not is_private and not is_group:
                return

            app = context.application

            # 🆕 v5.7.18: في المجموعات — نستمر فقط إذا كان التفعيل مفتوحاً
            # ملاحظة: هذا الفحص hot — يقرأ bot_data في الذاكرة.
            # تغييره من زر 📢 لا يتطلب restart.
            if is_group:
                if not _get_respond_in_groups(app):
                    return

            lock = _lock_for_user(app, user.id)

            async with lock:
                keyword_sent = False

                # ═══ 1. الكلمات المفتاحية ═══
                keywords = _get_keywords(app)
                if keywords:
                    kw_matched, reply = _find_keyword_match(
                        msg.text, keywords,
                        chat_type=("group" if is_group else "private"),
                    )
                    if kw_matched and reply:
                        # 🆕 v5.7.18: فحص "مرة واحدة" في الخاص فقط
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
                        # في المجموعات: لا فحص — يرد كل مرة

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

                        # 🆕 v5.7.18: تعليم "تم الرد" في الخاص فقط
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

                # 🆕 v5.7.18: في المجموعات — توقف هنا (لا تسلسل)
                if is_group:
                    return

                # 🆕 v5.7.15 FIX-FLOW-3: تأخير 5s قبل التسلسل (الخاص فقط)
                if keyword_sent:
                    logger.debug(
                        "managed_bot #%s: delaying %.1fs before "
                        "sequence for user %s",
                        bid, _SEQUENCE_DELAY_SEC, user.id,
                    )
                    await asyncio.sleep(_SEQUENCE_DELAY_SEC)

                # ═══ 2. التسلسل الأربع (الخاص فقط) ═══
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
                    # v5.7.16 FIX-CHURN-1: صف واحد فقط
                    await _persist_user(app, bid, user.id, user_state)
                    return

        except Exception as e:
            logger.exception("managed_bot #%s on_text: %s", bid, e)

    return on_start, on_text


# ═══════════════════════════════════════════════════════════════════════════
# post_init_managed
# ═══════════════════════════════════════════════════════════════════════════

async def post_init_managed(app: Application) -> None:
    try:
        await app.bot.set_my_commands(
            commands=[],
            scope=BotCommandScopeDefault(),
        )
        bid = app.bot_data.get("managed_bid", "?")
        name = app.bot_data.get("managed_name", "")
        groups_on = bool(app.bot_data.get("respond_in_groups", False))
        logger.info(
            "✅ managed_bot #%s (@%s): commands cleared | "
            "respond_in_groups=%s",
            bid, name or "?", groups_on,
        )
    except Exception as e:
        logger.warning("post_init_managed: %s", e)


__all__ = ["make_managed_handlers", "post_init_managed"]


try:
    logger.debug(
        "🛡️ handlers_managed_public v5.7.18 "
        "(SPLIT-REPLIES-ALWAYS-IN-GROUPS) loaded | "
        "keyword_delay=%.1fs | sequence_delay=%.1fs | "
        "flow_private=keywords(once,smart)→sleep→reply→third→fourth | "
        "flow_groups=keywords(once,smart,if_enabled)→sleep→reply | "
        "locks=striped(%d) | private_only_on_start=True | "
        "match=word_boundary+arabic_norm | "
        "churn_fix=persist_user(targeted)",
        _KEYWORD_REPLY_DELAY_SEC,
        _SEQUENCE_DELAY_SEC,
        _NUM_LOCK_STRIPES,
    )
except Exception:
    pass