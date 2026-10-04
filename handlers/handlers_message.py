#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_message.py - v7.10.12
=============================================================================
🆕 v7.10.12:
    ✅ Spam Analyzer يحلل:
       - message.text
       - message.caption
       - Inline Keyboard button text
       - Inline Keyboard URLs
    ✅ إصلاح الرسائل التي تحتوي على أزرار فقط
    ✅ إصلاح bool("0") التي كانت تُفسر True
    ✅ تحسين كشف Post Bot
    ✅ automatic_forward لا يتم تجاهله قبل Security Engine
    ✅ delete_forwarded يستطيع التعامل مع automatic forwards
    ✅ تشخيص Spam أكثر دقة
    ✅ الحفاظ على وظائف v7.10.11
=============================================================================
"""

import asyncio
import logging
import time
import os
import re
import json
import shutil
import tempfile
import ipaddress
import unicodedata
from pathlib import Path
from html import escape
from typing import Optional, Dict, Any, List, Tuple, Coroutine
from datetime import datetime
from urllib.parse import urlparse
from collections import defaultdict, deque

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut

from config import CONFIG, PATHS
from database import DB, TimeUtils, internal_cache
from utils import (
    TextUtils, safe_send, is_authorized_in_group,
    check_bot_permissions, invalidate_auth_cache, apply_penalty,
    RATE_LIMITER, METRICS, get_text, StateManager, UserState,
    KeyboardFactory, CB, RateLimiter,
    get_banned_words_cached, invalidate_banned_words_cache,
    _auto_reply_cache, get_reply_from_file, _REPLIES_FROM_FILE,
    reload_replies_from_file, _increment_usage_async,
    fetch_json_from_url, import_auto_replies,
    ban_user_by_id, unban_user_by_id,
    TranslationManager,
)
from cache import settings_cache, banned_words_cache, auth_cache, posts_cache


try:
    from replies import analyze_sentiment
except ImportError:
    analyze_sentiment = None


try:
    from telegram import (
        MessageOriginUser,
        MessageOriginHiddenUser,
        MessageOriginChat,
        MessageOriginChannel,
    )
    _HAS_MESSAGE_ORIGIN = True
except ImportError:
    MessageOriginUser = MessageOriginHiddenUser = None
    MessageOriginChat = MessageOriginChannel = None
    _HAS_MESSAGE_ORIGIN = False


logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Unicode Normalization
# ═══════════════════════════════════════════════════════════════════

_HIDDEN_CHARS = (
    '\u200b', '\u200c', '\u200d', '\u200e', '\u200f',
    '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
    '\u2060', '\u2061', '\u2062', '\u2063', '\u2064',
    '\ufeff',
)


def _normalize_text(text: str) -> str:
    if not text:
        return ""

    try:
        text = unicodedata.normalize('NFKC', text)
    except Exception:
        pass

    for c in _HIDDEN_CHARS:
        if c in text:
            text = text.replace(c, '')

    text = re.sub(
        r'[\s\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+',
        ' ',
        text
    )

    return text.strip()


# ═══════════════════════════════════════════════════════════════════
# Boolean Helper
# ═══════════════════════════════════════════════════════════════════

def _as_bool(value, default=False):
    """
    تحويل آمن للقيم القادمة من DB.

    مهم جدًا:
        bool("0") == True  ← خطأ
        _as_bool("0")      == False
    """
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        value = value.strip().lower()

        if value in (
            "1", "true", "yes", "on",
            "enabled", "enable", "y",
            "نعم", "مفعل", "مفعّل"
        ):
            return True

        if value in (
            "0", "false", "no", "off",
            "disabled", "disable", "n",
            "لا", "غير مفعل", "غير مفعّل"
        ):
            return False

    return default


# ═══════════════════════════════════════════════════════════════════
# Spam Detection v7.10.12
# ═══════════════════════════════════════════════════════════════════

_SPAM_STRONG_KEYWORDS = frozenset({
    'uncensored', 'xxx', 'nsfw', 'porn', 'nude', 'nudes',
    'leak', 'leaked', 'viral', 'archive', 'drop', 'mega',
})

_SPAM_MEDIUM_KEYWORDS = frozenset({
    'collection', 'clips', 'clip', 'footage', 'scenes', 'pack',
    'fresh', 'wild', 'best', 'hot', 'sexy', 'milf', 'dilf',
    'teen', 'teenager', 'taboo', 'busty', 'pierced', 'petite',
})

_SPAM_CONTEXT_KEYWORDS = frozenset({
    'check', 'tap', 'click', 'view', 'open',
    'cartoon', 'korean', 'colombian', 'step', 'mom',
    'euro', 'bj', 'mfm',
})

_CTA_KEYWORDS = frozenset({
    'check', 'tap', 'click', 'view', 'open',
    'join', 'subscribe', 'download', 'watch',
})

_SPAM_EMOJIS = (
    '⭐', '💀', '🔥', '✨', '🍑', '🔞', '🚨', '💎',
    '🎁', '🎉', '🌟', '💥', '⚡', '🌸', '🌺', '💋',
    '👑', '🥇', '🏆', '🎯', '💯', '🆕', '🆗',
    '🔴', '🟢', '🔵', '🟡', '🟣', '🟠',
)

_URL_RE = re.compile(
    r'https?://[^\s<>"]+',
    re.IGNORECASE
)

_WORD_RE = re.compile(
    r"[a-zA-Z][a-zA-Z0-9_-]*",
    re.IGNORECASE
)


_SPAM_CONTEXT_PATTERNS = (
    (
        re.compile(
            r'\buncensored\s+(?:best\s+)?'
            r'(?:collection|archive|pack|clips?)\b',
            re.IGNORECASE
        ),
        4,
        "uncensored+collection"
    ),

    (
        re.compile(
            r'\b(?:xxx|nsfw|porn)\s+'
            r'(?:collection|archive|pack|clips?)\b',
            re.IGNORECASE
        ),
        4,
        "adult+collection"
    ),

    (
        re.compile(
            r'\b(?:leak|leaked)\s+'
            r'(?:pack|archive|collection|clips?)\b',
            re.IGNORECASE
        ),
        4,
        "leak+pack"
    ),

    (
        re.compile(
            r'\b(?:click|tap|check|view|open)\s+'
            r'(?:here|now|below)\b',
            re.IGNORECASE
        ),
        2,
        "cta_phrase"
    ),

    (
        re.compile(
            r'\b(?:best|fresh|hot|wild|viral)\s+'
            r'(?:collection|clips?|pack|archive)\b',
            re.IGNORECASE
        ),
        3,
        "promo_collection"
    ),

    (
        re.compile(
            r'\b(?:mega|huge|massive)\s+'
            r'(?:pack|archive|collection|drop)\b',
            re.IGNORECASE
        ),
        3,
        "mega_promo"
    ),

    (
        re.compile(
            r'\b(?:viral|leak|leaked)\b.{0,35}'
            r'\b(?:view|open|click|tap|check)\b',
            re.IGNORECASE
        ),
        3,
        "viral/leak+cta"
    ),
)


_POSTBOT_EMOJI = (
    r'[⭐💀🔥✨🍑🔞🚨💎🎁🎉🌟💥⚡🌸🌺💋👑🥇🏆🎯💯🆕🆗'
    r'🔴🟢🔵🟡🟣🟠💦👉]'
)


_POSTBOT_PATTERN = re.compile(
    _POSTBOT_EMOJI +
    r'.{0,15}' +
    r'\b[A-Z]{4,}(?:\s+[A-Z]{4,}){1,}' +
    r'.{0,20}' +
    r'(?:' + _POSTBOT_EMOJI + r'|\d{2,})',
    re.UNICODE
)


_POSTBOT_PATTERN_LOOSE = re.compile(
    _POSTBOT_EMOJI +
    r'.{0,10}' +
    r'\b[A-Z]{4,}(?:\s+[A-Z]{4,}){1,}',
    re.UNICODE
)


_POSTBOT_BUTTON_PATTERN = re.compile(
    r'\b(?:view|open|watch|click|tap|viral|leak|'
    r'content|download|join|subscribe)\b',
    re.IGNORECASE
)


def _extract_spam_words(text: str) -> List[str]:
    if not text:
        return []

    try:
        return [
            m.group(0).lower()
            for m in _WORD_RE.finditer(text)
        ]
    except Exception:
        return []


def _count_unique_matches(words, keywords):
    try:
        return sorted(set(words).intersection(keywords))
    except Exception:
        return []


def _count_text_urls(text: str) -> List[str]:
    if not text:
        return []

    try:
        return _URL_RE.findall(text)
    except Exception:
        return []


def _get_message_button_data(message):
    """
    يحافظ على API القديم:
        return button_count, urls

    أما نصوص الأزرار فتؤخذ بواسطة:
        _get_message_button_texts()
    """
    button_count = 0
    urls = []

    try:
        markup = getattr(message, 'reply_markup', None)

        if not markup:
            return 0, []

        keyboard = getattr(markup, 'inline_keyboard', None)

        if not keyboard:
            return 0, []

        for row in keyboard:
            if not row:
                continue

            for button in row:
                if button is None:
                    continue

                button_count += 1

                url = getattr(button, 'url', None)

                if isinstance(url, str) and url:
                    urls.append(url)

    except Exception:
        pass

    return button_count, urls


def _get_message_button_texts(message):
    """
    استخراج نصوص أزرار Inline Keyboard.

    هذا هو الإصلاح الأساسي للمشكلة التي كانت تجعل:
        VIEW leak
        VIRAL content
        open here

    غير مرئية للـSpam detector.
    """
    texts = []

    try:
        markup = getattr(message, 'reply_markup', None)

        if not markup:
            return []

        keyboard = getattr(markup, 'inline_keyboard', None)

        if not keyboard:
            return []

        for row in keyboard:
            if not row:
                continue

            for button in row:
                if button is None:
                    continue

                text = getattr(button, 'text', None)

                if isinstance(text, str):
                    text = text.strip()

                    if text:
                        texts.append(text)

    except Exception:
        pass

    return texts


def _get_message_analysis_text(message):
    """
    النص الكامل الذي يستخدمه Spam Engine:

        message.text
        message.caption
        button labels
    """
    if message is None:
        return ""

    parts = []

    try:
        text = getattr(message, 'text', None)

        if text:
            parts.append(str(text))
    except Exception:
        pass

    try:
        caption = getattr(message, 'caption', None)

        if caption:
            parts.append(str(caption))
    except Exception:
        pass

    try:
        button_texts = _get_message_button_texts(message)

        if button_texts:
            parts.extend(button_texts)
    except Exception:
        pass

    return _normalize_text(" ".join(parts))


def _compute_spam_score(message):
    """
    Spam scoring engine.

    مهم:
    لا يعتمد على نص الرسالة فقط.
    يحلل أيضًا نصوص الأزرار وروابطها.
    """

    score = 0
    reasons = []

    try:
        if message is None:
            return 0, []

        body_text = ""

        try:
            body_text = (
                getattr(message, 'text', None)
                or getattr(message, 'caption', None)
                or ""
            )
        except Exception:
            body_text = ""

        normalized = _normalize_text(body_text)

        button_count, button_urls = _get_message_button_data(message)
        button_texts = _get_message_button_texts(message)

        button_text = _normalize_text(
            " ".join(button_texts)
        )

        analysis_text = _normalize_text(
            f"{normalized} {button_text}"
        )

        # لا نرجع صفر إذا كانت الرسالة بدون نص ولكن فيها أزرار.
        if not analysis_text and not button_urls:
            return 0, []

        text_lower = analysis_text.lower()

        # ═══════════════════════════════════════════════════════
        # 1) Buttons + URLs
        # ═══════════════════════════════════════════════════════

        if button_count >= 6:
            score += 3
            reasons.append(f"buttons={button_count}")

        elif button_count >= 5:
            score += 2
            reasons.append(f"buttons={button_count}")

        elif button_count >= 3:
            score += 1
            reasons.append(f"buttons={button_count}")

        has_photo = bool(getattr(message, 'photo', None))
        has_video = bool(getattr(message, 'video', None))

        if (has_photo or has_video) and button_count >= 1:
            score += 1
            reasons.append("media+buttons")

        # ═══════════════════════════════════════════════════════
        # 2) Emoji
        # ═══════════════════════════════════════════════════════

        emoji_count = 0

        for emoji in _SPAM_EMOJIS:
            try:
                emoji_count += analysis_text.count(emoji)
            except Exception:
                pass

        if emoji_count >= 8:
            score += 3
            reasons.append(f"emoji={emoji_count}")

        elif emoji_count >= 6:
            score += 2
            reasons.append(f"emoji={emoji_count}")

        elif emoji_count >= 3:
            score += 1
            reasons.append(f"emoji={emoji_count}")

        # ═══════════════════════════════════════════════════════
        # 3) Keywords
        # ═══════════════════════════════════════════════════════

        words = _extract_spam_words(analysis_text)

        strong_matches = _count_unique_matches(
            words,
            _SPAM_STRONG_KEYWORDS
        )

        medium_matches = _count_unique_matches(
            words,
            _SPAM_MEDIUM_KEYWORDS
        )

        context_matches = _count_unique_matches(
            words,
            _SPAM_CONTEXT_KEYWORDS
        )

        cta_matches = _count_unique_matches(
            words,
            _CTA_KEYWORDS
        )

        context_only_matches = [
            word for word in context_matches
            if word not in strong_matches
            and word not in medium_matches
        ]

        if strong_matches:
            strong_score = min(
                5,
                len(strong_matches) * 2
            )

            score += strong_score

            reasons.append(
                "strong=" + ",".join(strong_matches[:8])
            )

        if medium_matches:
            medium_score = min(
                4,
                len(medium_matches)
            )

            score += medium_score

            reasons.append(
                "medium=" + ",".join(medium_matches[:8])
            )

        if context_only_matches:
            if strong_matches or medium_matches:
                context_score = min(
                    2,
                    len(context_only_matches)
                )

                score += context_score

                reasons.append(
                    "context=" +
                    ",".join(context_only_matches[:8])
                )

        cta_only_matches = [
            word for word in cta_matches
            if word not in strong_matches
            and word not in medium_matches
        ]

        if cta_only_matches:
            if strong_matches or medium_matches:
                score += 1

                reasons.append(
                    "cta=" +
                    ",".join(cta_only_matches[:6])
                )

        # ═══════════════════════════════════════════════════════
        # 4) Contextual patterns
        # ═══════════════════════════════════════════════════════

        matched_patterns = []

        for pattern, weight, label in _SPAM_CONTEXT_PATTERNS:
            try:
                if pattern.search(text_lower):
                    score += weight
                    matched_patterns.append(label)
            except Exception:
                continue

        if matched_patterns:
            reasons.append(
                "patterns=" +
                ",".join(matched_patterns)
            )

        # ═══════════════════════════════════════════════════════
        # 5) Button labels with CTA
        # ═══════════════════════════════════════════════════════

        button_cta_matches = []

        for button_text_item in button_texts:
            try:
                if _POSTBOT_BUTTON_PATTERN.search(
                    button_text_item
                ):
                    button_cta_matches.append(
                        _normalize_text(button_text_item)
                    )
            except Exception:
                continue

        if button_cta_matches:
            if (
                strong_matches
                or medium_matches
                or matched_patterns
            ):
                score += min(
                    3,
                    len(button_cta_matches)
                )

                reasons.append(
                    "button_cta=" +
                    ",".join(button_cta_matches[:4])
                )

        # ═══════════════════════════════════════════════════════
        # 6) Telegram button URLs
        # ═══════════════════════════════════════════════════════

        tme_button_count = 0
        external_button_count = 0

        for url in button_urls:
            try:
                parsed = urlparse(url)
                host = (parsed.hostname or "").lower()

                if (
                    host == "t.me"
                    or host.endswith(".t.me")
                ):
                    tme_button_count += 1
                elif host:
                    external_button_count += 1

            except Exception:
                continue

        if tme_button_count >= 4:
            score += 4
            reasons.append(
                f"tme_buttons={tme_button_count}"
            )

        elif tme_button_count >= 3:
            score += 3
            reasons.append(
                f"tme_buttons={tme_button_count}"
            )

        elif tme_button_count >= 2:
            score += 2
            reasons.append(
                f"tme_buttons={tme_button_count}"
            )

        elif tme_button_count >= 1:
            if (
                strong_matches
                or medium_matches
                or matched_patterns
            ):
                score += 1
                reasons.append(
                    f"tme_buttons={tme_button_count}"
                )

        if external_button_count >= 3:
            score += 2
            reasons.append(
                f"external_buttons={external_button_count}"
            )

        # ═══════════════════════════════════════════════════════
        # 7) Text URLs
        # ═══════════════════════════════════════════════════════

        text_urls = _count_text_urls(
            normalized
        )

        if len(text_urls) >= 3:
            score += 3
            reasons.append(
                f"text_urls={len(text_urls)}"
            )

        elif len(text_urls) >= 2:
            score += 2
            reasons.append(
                f"text_urls={len(text_urls)}"
            )

        elif len(text_urls) == 1:
            if (
                strong_matches
                or medium_matches
                or matched_patterns
            ):
                score += 1
                reasons.append("text_urls=1")

        # ═══════════════════════════════════════════════════════
        # 8) Short promotional messages
        # ═══════════════════════════════════════════════════════

        body_len = len(normalized)

        if body_len < 60 and button_count >= 5:
            if (
                strong_matches
                or medium_matches
                or matched_patterns
            ):
                score += 2
                reasons.append(
                    "short_promo+many_buttons"
                )

        elif body_len < 50 and button_count >= 3:
            if (
                strong_matches
                or medium_matches
                or matched_patterns
            ):
                score += 2
                reasons.append(
                    "short_promo+buttons"
                )

        elif body_len < 30 and button_count >= 2:
            if (
                strong_matches
                or matched_patterns
            ):
                score += 1
                reasons.append(
                    "short_text+buttons"
                )

        # ═══════════════════════════════════════════════════════
        # 9) CAPS
        # ═══════════════════════════════════════════════════════

        caps_words = re.findall(
            r'\b[A-Z]{4,}\b',
            analysis_text
        )

        if len(caps_words) >= 8:
            if (
                strong_matches
                or medium_matches
                or matched_patterns
            ):
                score += 3
                reasons.append(
                    f"CAPS={len(caps_words)}"
                )

        elif len(caps_words) >= 6:
            if (
                strong_matches
                or medium_matches
                or matched_patterns
            ):
                score += 2
                reasons.append(
                    f"CAPS={len(caps_words)}"
                )

        elif len(caps_words) >= 4:
            if (
                strong_matches
                or matched_patterns
            ):
                score += 1
                reasons.append(
                    f"CAPS={len(caps_words)}"
                )

        # ═══════════════════════════════════════════════════════
        # 10) Promotional density
        # ═══════════════════════════════════════════════════════

        promo_count = (
            len(strong_matches)
            + len(medium_matches)
            + len(cta_only_matches)
        )

        if promo_count >= 8:
            score += 3
            reasons.append(
                f"promo_density={promo_count}"
            )

        elif promo_count >= 6:
            score += 2
            reasons.append(
                f"promo_density={promo_count}"
            )

        elif promo_count >= 4:
            score += 1
            reasons.append(
                f"promo_density={promo_count}"
            )

        # ═══════════════════════════════════════════════════════
        # 11) High-confidence combinations
        # ═══════════════════════════════════════════════════════

        if (
            len(strong_matches) >= 2
            and (
                button_count >= 2
                or cta_only_matches
                or button_cta_matches
            )
        ):
            score += 3
            reasons.append(
                "strong+cta/buttons"
            )

        if (
            'leak' in strong_matches
            and (
                'viral' in strong_matches
                or 'mega' in strong_matches
            )
        ):
            score += 2
            reasons.append(
                "leak+viral/mega"
            )

        if (
            'viral' in strong_matches
            and button_cta_matches
        ):
            score += 2
            reasons.append(
                "viral+button_cta"
            )

        # ═══════════════════════════════════════════════════════
        # 12) Anti false-positive guard
        # ═══════════════════════════════════════════════════════

        if (
            not strong_matches
            and not medium_matches
            and not matched_patterns
            and not text_urls
            and tme_button_count == 0
            and not button_cta_matches
        ):
            if score < SPAM_SCORE_THRESHOLD:
                score = 0
                reasons = []

        score = min(
            max(score, 0),
            20
        )

    except Exception as e:
        logger.debug(
            f"_compute_spam_score: {e}"
        )
        return 0, []

    return score, reasons


def _is_postbot_pattern(text):
    if not text or len(text) < 10:
        return False

    try:
        if _POSTBOT_PATTERN.search(text):
            return True

        if _POSTBOT_PATTERN_LOOSE.search(text):
            return True

        # نمط CTA شائع في منشورات Post Bot
        if (
            _POSTBOT_BUTTON_PATTERN.search(text)
            and re.search(
                r'\b(?:viral|leak|mega|pack|clips?|content)\b',
                text,
                re.IGNORECASE
            )
        ):
            return True

    except Exception:
        pass

    return False


def _env_flag(name, default=True):
    val = os.getenv(name)

    if val is None:
        return default

    return val.strip().lower() in (
        "1",
        "true",
        "yes",
        "on"
    )


FEATURE_LOG_DELETIONS = _env_flag(
    "LOG_DELETIONS",
    True
)

FEATURE_LOG_PENALTIES = _env_flag(
    "LOG_PENALTIES",
    True
)

FEATURE_LOG_GIFTS = _env_flag(
    "LOG_GIFTS",
    True
)

FEATURE_LOG_ADMIN_CHANGES = _env_flag(
    "LOG_ADMIN_CHANGES",
    True
)


MAX_PENALTY_MINUTES = 30 * 24 * 60
LOG_RATE_LIMIT_PER_MIN = 30
LOG_RATE_WINDOW_SEC = 60.0
LOG_RETRY_ATTEMPTS = 3
LOG_RETRY_BASE_DELAY = 0.5
DEV_LOG_CACHE_TTL = 300.0
MAX_SUPPORT_MESSAGE_LENGTH = 4000
MAX_BROADCAST_MESSAGE_LENGTH = 4000
MAX_IMPORT_FILE_SIZE = 5 * 1024 * 1024
MAX_GIFT_CODE_LENGTH = 50
MAX_VIOLATION_STRIKES = 100
MAX_ADMIN_BROADCAST_TARGETS = 100_000
BROADCAST_DELAY_SECONDS = 0.1
MAX_GROUP_LIMITERS_CACHE = 1000
MAX_SEC_AUTH_CACHE_SIZE = 5000
SEC_AUTH_CACHE_TTL = 300
CACHE_CLEANUP_INTERVAL = 3600

_FORWARD_NOTIFY_COOLDOWN_SECONDS = 300.0
_GROUP_LOG_PREVIEW_LENGTH = 150

_PROTECTED_FORWARD_HINTS = (
    "محولة من",
    "محوّل من",
    "محوله من",
    "تم التحويل من",
    "المعاد توجيهها من",
    "Forwarded from",
    "من قناة",
)

_DELETE_IGNORED_PATTERNS = (
    "message to delete not found",
    "message identifier is not specified",
    "message is not found",
)

_DELETE_PERMISSION_ERROR = (
    "message can't be deleted"
)

_MEDIA_REPLY_TYPES = frozenset({
    'photo',
    'video',
    'document',
    'audio',
    'animation',
    'voice',
    'sticker',
    'video_note',
})

TRANSLATION_REPLY_DELETE_DELAY = 30
TRANSLATION_MIN_TEXT_LENGTH = 2
PENALTY_MESSAGE_DELETE_DELAY = 10

SPAM_SCORE_THRESHOLD = 5

_columns_initialized = False
_columns_init_lock = asyncio.Lock()


# ═══════════════════════════════════════════════════════════════════
# Database Migration
# ═══════════════════════════════════════════════════════════════════

async def _lazy_init_columns():
    global _columns_initialized

    if _columns_initialized:
        return

    async with _columns_init_lock:
        if _columns_initialized:
            return

        db_type = getattr(
            DB,
            "DB_TYPE",
            "sqlite"
        )

        logger.info(
            f"🔧 v7.10.12: Auto-migration "
            f"يبدأ (DB_TYPE={db_type})"
        )

        cols = [
            (
                "delete_protected_any",
                "INTEGER DEFAULT 0",
                "TINYINT(1) DEFAULT 0"
            ),
            (
                "delete_postbot_pattern",
                "INTEGER DEFAULT 0",
                "TINYINT(1) DEFAULT 0"
            ),
            (
                "delete_spam_score",
                "INTEGER DEFAULT 1",
                "TINYINT(1) DEFAULT 1"
            ),
        ]

        migration_ok = True

        for col_name, pg_def, mysql_def in cols:
            try:
                if db_type == "postgres":
                    await DB.execute(
                        "ALTER TABLE group_security "
                        "ADD COLUMN IF NOT EXISTS "
                        f"{col_name} {pg_def}"
                    )

                elif db_type == "mysql":
                    try:
                        await DB.execute(
                            "ALTER TABLE group_security "
                            f"ADD COLUMN {col_name} "
                            f"{mysql_def}"
                        )
                    except Exception as e:
                        m = str(e).lower()

                        if (
                            "duplicate" not in m
                            and "already exists" not in m
                        ):
                            migration_ok = False
                            logger.warning(
                                f"⚠️ MySQL {col_name}: {e}"
                            )

                else:
                    try:
                        await DB.execute(
                            "ALTER TABLE group_security "
                            f"ADD COLUMN {col_name} "
                            f"{pg_def}"
                        )
                    except Exception as e:
                        m = str(e).lower()

                        if (
                            "duplicate" not in m
                            and "already exists" not in m
                        ):
                            migration_ok = False
                            logger.warning(
                                f"⚠️ SQLite {col_name}: {e}"
                            )

            except Exception as e:
                migration_ok = False

                logger.warning(
                    f"⚠️ auto-migration "
                    f"{col_name}: {e}"
                )

        # delete_protected_any
        try:
            await DB.execute(
                "UPDATE group_security "
                "SET delete_protected_any = 1 "
                "WHERE delete_forwarded = 1 "
                "AND (delete_protected_any IS NULL "
                "OR delete_protected_any = 0)"
            )

            logger.info(
                "✅ تم تفعيل delete_protected_any"
            )

        except Exception as e:
            migration_ok = False

            logger.warning(
                f"⚠️ UPDATE protected_any: {e}"
            )

        # delete_postbot_pattern
        try:
            await DB.execute(
                "UPDATE group_security "
                "SET delete_postbot_pattern = 1 "
                "WHERE delete_forwarded = 1 "
                "AND (delete_postbot_pattern IS NULL "
                "OR delete_postbot_pattern = 0)"
            )

            logger.info(
                "✅ v7.10.12: "
                "تم تفعيل delete_postbot_pattern تلقائياً"
            )

        except Exception as e:
            migration_ok = False

            logger.warning(
                f"⚠️ UPDATE postbot_pattern: {e}"
            )

        try:
            await internal_cache.clear()
            logger.info(
                "✅ internal_cache cleared"
            )
        except Exception as e:
            logger.debug(
                f"cache clear: {e}"
            )

        _columns_initialized = migration_ok


# ═══════════════════════════════════════════════════════════════════
# Developer Log Cache
# ═══════════════════════════════════════════════════════════════════

_dev_log_cache = None
_dev_log_cache_ts = 0.0
_dev_log_cache_lock = asyncio.Lock()


async def _get_dev_log_channel_cached():
    global _dev_log_cache
    global _dev_log_cache_ts

    now = time.monotonic()

    if (
        _dev_log_cache is not None
        and now - _dev_log_cache_ts < DEV_LOG_CACHE_TTL
    ):
        return _dev_log_cache

    async with _dev_log_cache_lock:
        now = time.monotonic()

        if (
            _dev_log_cache is not None
            and now - _dev_log_cache_ts < DEV_LOG_CACHE_TTL
        ):
            return _dev_log_cache

        try:
            ch = await DB.get_log_channel()

            _dev_log_cache = ch
            _dev_log_cache_ts = now

            return ch

        except Exception as e:
            logger.warning(
                f"get_dev_log_channel_cached: {e}"
            )

            return _dev_log_cache


def _invalidate_dev_log_cache():
    global _dev_log_cache
    global _dev_log_cache_ts

    _dev_log_cache = None
    _dev_log_cache_ts = 0.0


async def _notify_dev_log(context, text):
    try:
        log_ch = await _get_dev_log_channel_cached()

        if not log_ch:
            return

        ch_str = str(log_ch).strip()

        if not ch_str:
            return

        if ch_str.lstrip('-').isdigit():
            target = int(ch_str)

        elif ch_str.startswith('@'):
            target = ch_str

        elif ch_str.startswith((
            'https://',
            'http://'
        )):
            tail = ch_str.rstrip('/').split('/')[-1]

            if tail.startswith('@'):
                tail = tail[1:]

            target = (
                f"@{tail}"
                if not tail.lstrip('-').isdigit()
                else int(tail)
            )

        else:
            target = f"@{ch_str}"

        await context.bot.send_message(
            chat_id=target,
            text=text,
            parse_mode='HTML',
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.warning(
            f"🔔 _notify_dev_log FAILED: {e}"
        )


# ═══════════════════════════════════════════════════════════════════
# Log Rate Limit
# ═══════════════════════════════════════════════════════════════════

_log_rate_tracker = defaultdict(
    lambda: deque(
        maxlen=LOG_RATE_LIMIT_PER_MIN
    )
)

_log_rate_lock = asyncio.Lock()


async def _can_send_log(chat_id):
    async with _log_rate_lock:
        now = time.monotonic()

        tracker = _log_rate_tracker[chat_id]

        if (
            len(tracker) >= LOG_RATE_LIMIT_PER_MIN
            and now - tracker[0] < LOG_RATE_WINDOW_SEC
        ):
            logger.warning(
                f"🚫 LOG-RATE-LIMIT | chat={chat_id}"
            )

            return False

        tracker.append(now)

        return True


async def _dispatch_log(
    awaitable,
    label,
    *,
    retries=LOG_RETRY_ATTEMPTS
):
    async def _runner():
        try:
            await awaitable

        except asyncio.CancelledError:
            return

        except Exception as e:
            logger.error(
                f"❌ [{label}] failed: {e}"
            )

    task = asyncio.create_task(
        _runner()
    )

    def _done_callback(t):
        try:
            if (
                not t.cancelled()
                and t.exception()
            ):
                logger.error(
                    f"❌ [{label}] "
                    f"background task failed: "
                    f"{t.exception()}"
                )
        except Exception:
            pass

    task.add_done_callback(
        _done_callback
    )


# ═══════════════════════════════════════════════════════════════════
# Cache Helpers
# ═══════════════════════════════════════════════════════════════════

async def _safe_invalidate(*keys):
    for key in keys:
        if not key:
            continue

        try:
            await internal_cache.invalidate(
                key
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# Labels
# ═══════════════════════════════════════════════════════════════════

_VIOLATION_LABELS_AR = {
    'forwarded': '↩️ رسالة معاد توجيهها',
    'link': '🔗 رابط',
    'mention': '📢 منشن',
    'banned_word': '🚫 كلمة محظورة',
    'max_len': '📏 طول زائد',
    'video': '🎬 فيديو',
    'photo': '📷 صورة',
    'audio': '🎵 صوت',
    'voice': '🎤 فويس',
    'sticker': '🖼️ ملصق',
    'document': '📄 ملف',
    'animation': '🎞️ أنيميشن',
    'video_note': '🎥 فيديو نوت',
    'postbot_pattern': '🤖 نمط Post Bot',
    'spam_score': '🚫 رسالة Spam',
}

_FORWARD_TYPE_LABELS_AR = {
    'user': '👤 مستخدم',
    'hidden_user': '👻 مستخدم مخفي',
    'chat': '👥 مجموعة',
    'channel': '📢 قناة',
    'protected': '🛡️ محتوى محمي',
    'protected_any': '🛡️ محتوى محمي',
}

_PENALTY_LABELS_AR = {
    'ban': '🚫 حظر',
    'mute': '🔇 كتم',
    'kick': '👢 طرد',
    'restrict': '🔒 تقييد',
    'warn': '⚠️ تحذير',
    'unban': '✅ فك حظر',
}


def _format_duration(seconds):
    if not seconds or seconds <= 0:
        return "دائم"

    try:
        seconds = int(seconds)
    except (
        TypeError,
        ValueError
    ):
        return "—"

    days = seconds // 86400
    hours = (
        seconds % 86400
    ) // 3600

    minutes = (
        seconds % 3600
    ) // 60

    secs = seconds % 60

    parts = []

    if days:
        parts.append(
            f"{days} يوم"
        )

    if hours:
        parts.append(
            f"{hours} ساعة"
        )

    if minutes:
        parts.append(
            f"{minutes} دقيقة"
        )

    if secs and not parts:
        parts.append(
            f"{secs} ثانية"
        )

    return (
        " و ".join(parts)
        if parts
        else f"{seconds} ثانية"
    )


# ═══════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════

async def notify_group_log(
    context,
    chat_id,
    text,
    disable_preview=True
):
    try:
        getter = getattr(
            DB,
            'get_group_log_channel',
            None
        )

        if not callable(getter):
            return False

        channel_id = await getter(
            chat_id
        )

        if not channel_id:
            return False

        if (
            isinstance(channel_id, str)
            and channel_id.lstrip('-').isdigit()
        ):
            channel_id = int(channel_id)

        await context.bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode='HTML',
            disable_web_page_preview=disable_preview
        )

        return True

    except BadRequest as e:
        err = str(e).lower()

        if "chat not found" in err:
            logger.error(
                f"❌ group_log: قناة غير موجودة | {chat_id}"
            )

        elif (
            "not enough rights" in err
            or "bot is not a member" in err
        ):
            logger.error(
                f"❌ group_log: البوت ليس عضواً | {chat_id}"
            )

        return False

    except Exception as e:
        logger.error(
            f"❌ group_log FAILED: {e}"
        )

        return False


def _build_delete_log_text(
    chat_id,
    user_id,
    user_first_name,
    user_username,
    violation_type,
    forward_info=None,
    message_preview=None,
    is_anonymous=False
):
    label = _VIOLATION_LABELS_AR.get(
        violation_type,
        violation_type
    )

    if is_anonymous:
        user_display_lnk = (
            "👻 <b>مشرف مجهول</b>"
        )

    else:
        user_display = escape(
            user_first_name or 'User'
        )

        if user_username:
            user_display_lnk = (
                f"<a href='tg://user?id={user_id}'>"
                f"{user_display}</a> "
                f"(@{escape(user_username)})"
            )
        else:
            user_display_lnk = (
                f"<a href='tg://user?id={user_id}'>"
                f"{user_display}</a>"
            )

    lines = [
        "🗑️ <b>حذف رسالة</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📌 النوع: {label}",
        f"👤 المستخدم: {user_display_lnk}",
    ]

    if not is_anonymous:
        lines.append(
            f"🆔 المعرّف: <code>{user_id}</code>"
        )
    else:
        lines.append(
            f"🆔 المجموعة: <code>{chat_id}</code>"
        )

    if message_preview:
        preview = (
            message_preview
            .strip()
            .replace("\n", " ")
        )

        if len(preview) > _GROUP_LOG_PREVIEW_LENGTH:
            preview = (
                preview[
                    :_GROUP_LOG_PREVIEW_LENGTH
                ] + "…"
            )

        lines.append(
            f"💬 النص: <i>{escape(preview)}</i>"
        )

    if forward_info:
        ftype = (
            forward_info.get('type')
            or '؟'
        )

        ftype_label = _FORWARD_TYPE_LABELS_AR.get(
            ftype,
            ftype
        )

        lines.append("")
        lines.append(
            "📤 <b>المصدر:</b>"
        )

        lines.append(
            f"   • النوع: {ftype_label}"
        )

        fname = forward_info.get(
            'name'
        )

        if fname:
            fname_str = str(fname)

            if len(fname_str) > 60:
                fname_str = (
                    fname_str[:60]
                    + "…"
                )

            lines.append(
                f"   • الاسم: "
                f"{escape(fname_str)}"
            )

        if forward_info.get('id'):
            lines.append(
                f"   • المعرّف: "
                f"<code>{forward_info['id']}</code>"
            )

    try:
        now_str = (
            TimeUtils.mecca_now()
            .strftime('%Y-%m-%d %H:%M:%S')
        )

    except Exception:
        now_str = (
            datetime.utcnow()
            .strftime('%Y-%m-%d %H:%M:%S')
        )

    lines.append("")
    lines.append(
        f"🕐 {now_str}"
    )

    return "\n".join(lines)


def _build_penalty_log_text(
    chat_id,
    target_user_id,
    target_first_name,
    target_username,
    penalty_type,
    duration_seconds,
    source="auto",
    violation_type=None,
    moderator_id=None,
    moderator_name=None
):
    ptype_label = _PENALTY_LABELS_AR.get(
        penalty_type,
        penalty_type
    )

    target_display = escape(
        target_first_name or 'User'
    )

    if target_username:
        target_lnk = (
            f"<a href='tg://user?id={target_user_id}'>"
            f"{target_display}</a> "
            f"(@{escape(target_username)})"
        )
    else:
        target_lnk = (
            f"<a href='tg://user?id={target_user_id}'>"
            f"{target_display}</a>"
        )

    source_label = (
        "🤖 تلقائي"
        if source == "auto"
        else "👮 يدوي"
    )

    lines = [
        f"{ptype_label}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🎯 العقوبة: <b>{ptype_label}</b>",
        f"⏱️ المدة: "
        f"{_format_duration(duration_seconds)}",
        f"📊 المصدر: {source_label}",
        "",
        f"👤 المستهدف: {target_lnk}",
        f"🆔 المعرّف: "
        f"<code>{target_user_id}</code>",
    ]

    if (
        source == "auto"
        and violation_type
    ):
        vlabel = _VIOLATION_LABELS_AR.get(
            violation_type,
            violation_type
        )

        lines.append(
            f"⚠️ المخالفة: {vlabel}"
        )

    if (
        source == "manual"
        and moderator_id
    ):
        mod_display = escape(
            moderator_name or "Admin"
        )

        lines.append("")

        lines.append(
            f"👮 المشرف: "
            f"<a href='tg://user?id={moderator_id}'>"
            f"{mod_display}</a>"
        )

    lines.append(
        f"💬 المجموعة: <code>{chat_id}</code>"
    )

    try:
        now_str = (
            TimeUtils.mecca_now()
            .strftime('%Y-%m-%d %H:%M:%S')
        )

    except Exception:
        now_str = (
            datetime.utcnow()
            .strftime('%Y-%m-%d %H:%M:%S')
        )

    lines.append("")
    lines.append(
        f"🕐 {now_str}"
    )

    return "\n".join(lines)


async def _notify_group_log_penalty(
    context,
    chat_id,
    target_user_id,
    target_first_name,
    target_username,
    penalty_type,
    duration_seconds,
    source="auto",
    violation_type=None,
    moderator_id=None,
    moderator_name=None
):
    if not FEATURE_LOG_PENALTIES:
        return

    if not await _can_send_log(chat_id):
        return

    try:
        text = _build_penalty_log_text(
            chat_id,
            target_user_id,
            target_first_name,
            target_username,
            penalty_type,
            duration_seconds,
            source,
            violation_type,
            moderator_id,
            moderator_name
        )

        await _dispatch_log(
            notify_group_log(
                context,
                chat_id,
                text
            ),
            label=f"penalty-{penalty_type}"
        )

    except Exception as e:
        logger.warning(
            f"⚠️ _notify_group_log_penalty: {e}"
        )


# ═══════════════════════════════════════════════════════════════════
# Security Auth Cache
# ═══════════════════════════════════════════════════════════════════

_sec_auth_cache = {}
_sec_auth_cache_lock = asyncio.Lock()


async def _sec_auth_cache_cleanup():
    async with _sec_auth_cache_lock:
        now = time.monotonic()

        expired = [
            key
            for key, (_, ts)
            in _sec_auth_cache.items()
            if now - ts > SEC_AUTH_CACHE_TTL
        ]

        for key in expired:
            _sec_auth_cache.pop(
                key,
                None
            )

        if len(_sec_auth_cache) > MAX_SEC_AUTH_CACHE_SIZE:
            extra = (
                len(_sec_auth_cache)
                - MAX_SEC_AUTH_CACHE_SIZE
            )

            oldest = sorted(
                _sec_auth_cache.items(),
                key=lambda item: item[1][1]
            )[:extra]

            for key, _ in oldest:
                _sec_auth_cache.pop(
                    key,
                    None
                )

        return len(expired)


def _is_delete_ignore_error(exc):
    try:
        return any(
            pattern in str(exc).lower()
            for pattern in _DELETE_IGNORED_PATTERNS
        )
    except Exception:
        return False


def _is_delete_permission_error(exc):
    try:
        return (
            _DELETE_PERMISSION_ERROR
            in str(exc).lower()
        )
    except Exception:
        return False


async def _safe_delete_message(
    bot,
    chat_id,
    message_id
):
    try:
        await bot.delete_message(
            chat_id,
            message_id
        )

        logger.info(
            f"✅ DELETE OK | "
            f"chat={chat_id} "
            f"msg={message_id}"
        )

        return True

    except BadRequest as e:
        if _is_delete_permission_error(e):
            logger.error(
                f"❌ DELETE FAILED "
                f"(permission) | "
                f"chat={chat_id} "
                f"msg={message_id}"
            )

            return False

        if _is_delete_ignore_error(e):
            return True

        logger.warning(
            f"⚠️ DELETE failed | "
            f"chat={chat_id} "
            f"msg={message_id}"
        )

        return False

    except asyncio.CancelledError:
        raise

    except Exception as e:
        if _is_delete_permission_error(e):
            return False

        if _is_delete_ignore_error(e):
            return True

        logger.warning(
            f"⚠️ DELETE failed | "
            f"chat={chat_id} "
            f"msg={message_id} | "
            f"{e}"
        )

        return False


def _has_forward_hint(text):
    if not text:
        return False

    tail = (
        text[-200:]
        if len(text) > 200
        else text
    )

    for hint in _PROTECTED_FORWARD_HINTS:
        if hint in tail:
            return True

    return False


def is_forwarded(
    message,
    *,
    allow_protected_fallback=False,
    allow_protected_any=False
):
    if message is None:
        return False

    if getattr(
        message,
        'forward_origin',
        None
    ) is not None:
        return True

    if getattr(
        message,
        'forward_date',
        None
    ) is not None:
        return True

    if getattr(
        message,
        'forward_from',
        None
    ) is not None:
        return True

    if getattr(
        message,
        'forward_from_chat',
        None
    ) is not None:
        return True

    if getattr(
        message,
        'forward_sender_name',
        None
    ) is not None:
        return True

    is_protected = _as_bool(
        getattr(
            message,
            'has_protected_content',
            False
        ),
        False
    )

    is_auto = _as_bool(
        getattr(
            message,
            'is_automatic_forward',
            False
        ),
        False
    )

    if (
        allow_protected_any
        and is_protected
        and not is_auto
    ):
        return True

    if (
        allow_protected_fallback
        and is_protected
    ):
        caption = (
            getattr(
                message,
                'caption',
                None
            )
            or getattr(
                message,
                'text',
                None
            )
            or ""
        )

        if _has_forward_hint(caption):
            return True

    return False


def get_forward_detection_reason(message):
    if message is None:
        return {
            "error": "message is None"
        }

    fields = {}

    for name in (
        'forward_origin',
        'forward_date',
        'forward_from',
        'forward_from_chat',
        'forward_sender_name'
    ):
        value = getattr(
            message,
            name,
            None
        )

        fields[name] = {
            "present": value is not None,
            "type": (
                type(value).__name__
                if value is not None
                else None
            ),
            "repr_short": (
                str(value)[:80]
                if value is not None
                else None
            ),
        }

    any_present = any(
        field["present"]
        for field in fields.values()
    )

    protected = _as_bool(
        getattr(
            message,
            'has_protected_content',
            False
        ),
        False
    )

    caption = (
        getattr(
            message,
            'caption',
            None
        )
        or getattr(
            message,
            'text',
            None
        )
        or ""
    )

    hint = (
        _has_forward_hint(caption)
        if protected
        else False
    )

    auto_fwd = _as_bool(
        getattr(
            message,
            'is_automatic_forward',
            False
        ),
        False
    )

    return {
        "is_forwarded": any_present,
        "is_protected": protected,
        "has_hint": hint,
        "has_automatic_forward": auto_fwd,
        "fields": fields,
        "has_message_origin_module": _HAS_MESSAGE_ORIGIN,
    }


def _extract_legacy_forward_info(message):
    try:
        fwd_from = getattr(
            message,
            'forward_from',
            None
        )

        fwd_from_chat = getattr(
            message,
            'forward_from_chat',
            None
        )

        fwd_sender_name = getattr(
            message,
            'forward_sender_name',
            None
        )

        fwd_date = getattr(
            message,
            'forward_date',
            None
        )

        fwd_signature = getattr(
            message,
            'forward_signature',
            None
        )

        if fwd_from is not None:
            try:
                full_name = (
                    getattr(
                        fwd_from,
                        'full_name',
                        None
                    )
                    or getattr(
                        fwd_from,
                        'first_name',
                        None
                    )
                    or ""
                )

            except Exception:
                full_name = ""

            return {
                'type': 'user',
                'id': getattr(
                    fwd_from,
                    'id',
                    None
                ),
                'name': (
                    full_name
                    or str(
                        getattr(
                            fwd_from,
                            'id',
                            'User'
                        )
                    )
                ),
                'date': fwd_date,
                'signature': None,
                'message_id': None,
            }

        if fwd_from_chat is not None:
            chat_type = (
                getattr(
                    fwd_from_chat,
                    'type',
                    ''
                )
                or ''
            )

            is_channel = (
                chat_type == 'channel'
            )

            return {
                'type': (
                    'channel'
                    if is_channel
                    else 'chat'
                ),
                'id': getattr(
                    fwd_from_chat,
                    'id',
                    None
                ),
                'name': (
                    getattr(
                        fwd_from_chat,
                        'title',
                        None
                    )
                    or getattr(
                        fwd_from_chat,
                        'username',
                        None
                    )
                    or str(
                        getattr(
                            fwd_from_chat,
                            'id',
                            'Chat'
                        )
                    )
                ),
                'date': fwd_date,
                'signature': fwd_signature,
                'message_id': None,
            }

        if fwd_sender_name:
            return {
                'type': 'hidden_user',
                'id': None,
                'name': str(
                    fwd_sender_name
                ),
                'date': fwd_date,
                'signature': None,
                'message_id': None,
            }

    except Exception:
        pass

    return None


def extract_forward_info(message):
    if message is None:
        return None

    origin = getattr(
        message,
        'forward_origin',
        None
    )

    if (
        origin is not None
        and _HAS_MESSAGE_ORIGIN
    ):
        try:
            if isinstance(
                origin,
                MessageOriginUser
            ):
                user = origin.sender_user

                try:
                    name = (
                        getattr(
                            user,
                            'full_name',
                            None
                        )
                        or getattr(
                            user,
                            'first_name',
                            None
                        )
                        or str(
                            getattr(
                                user,
                                'id',
                                'User'
                            )
                        )
                    )

                except Exception:
                    name = str(
                        getattr(
                            user,
                            'id',
                            'User'
                        )
                    )

                return {
                    'type': 'user',
                    'id': getattr(
                        user,
                        'id',
                        None
                    ),
                    'name': name,
                    'date': getattr(
                        origin,
                        'date',
                        None
                    ),
                    'signature': None,
                    'message_id': None,
                }

            if isinstance(
                origin,
                MessageOriginHiddenUser
            ):
                return {
                    'type': 'hidden_user',
                    'id': None,
                    'name': (
                        getattr(
                            origin,
                            'sender_user_name',
                            None
                        )
                        or 'Hidden'
                    ),
                    'date': getattr(
                        origin,
                        'date',
                        None
                    ),
                    'signature': None,
                    'message_id': None,
                }

            if isinstance(
                origin,
                MessageOriginChat
            ):
                chat = origin.sender_chat

                return {
                    'type': 'chat',
                    'id': getattr(
                        chat,
                        'id',
                        None
                    ),
                    'name': (
                        getattr(
                            chat,
                            'title',
                            None
                        )
                        or getattr(
                            chat,
                            'username',
                            None
                        )
                        or str(
                            getattr(
                                chat,
                                'id',
                                'Chat'
                            )
                        )
                    ),
                    'date': getattr(
                        origin,
                        'date',
                        None
                    ),
                    'signature': getattr(
                        origin,
                        'author_signature',
                        None
                    ),
                    'message_id': None,
                }

            if isinstance(
                origin,
                MessageOriginChannel
            ):
                chat = origin.chat

                return {
                    'type': 'channel',
                    'id': getattr(
                        chat,
                        'id',
                        None
                    ),
                    'name': (
                        getattr(
                            chat,
                            'title',
                            None
                        )
                        or getattr(
                            chat,
                            'username',
                            None
                        )
                        or str(
                            getattr(
                                chat,
                                'id',
                                'Channel'
                            )
                        )
                    ),
                    'date': getattr(
                        origin,
                        'date',
                        None
                    ),
                    'signature': getattr(
                        origin,
                        'author_signature',
                        None
                    ),
                    'message_id': getattr(
                        origin,
                        'message_id',
                        None
                    ),
                }

        except Exception:
            pass

    info = _extract_legacy_forward_info(
        message
    )

    if info:
        return info

    is_protected = _as_bool(
        getattr(
            message,
            'has_protected_content',
            False
        ),
        False
    )

    if is_protected:
        caption = (
            getattr(
                message,
                'caption',
                None
            )
            or getattr(
                message,
                'text',
                None
            )
            or ""
        )

        if _has_forward_hint(caption):
            return {
                'type': 'protected',
                'id': None,
                'name': (
                    '🛡️ محتوى محمي '
                    '(forward مخفي)'
                ),
                'date': None,
                'signature': None,
                'message_id': None,
            }

        return {
            'type': 'protected_any',
            'id': None,
            'name': (
                '🛡️ محتوى محمي'
            ),
            'date': None,
            'signature': None,
            'message_id': None,
        }

    return None


async def _notify_admin_about_forward(
    context,
    admin_id,
    info
):
    if not info or not admin_id:
        return

    try:
        type_labels = {
            'user': '👤 مستخدم',
            'hidden_user': '👻 مستخدم مخفي',
            'chat': '👥 مجموعة',
            'channel': '📢 قناة',
            'protected': '🛡️ محتوى محمي',
            'protected_any': '🛡️ محتوى محمي',
        }

        label = type_labels.get(
            info.get('type', ''),
            f"❔ {info.get('type')}"
        )

        lines = [
            "↩️ <b>رسالة معاد توجيهها</b>",
            "",
            f"📌 النوع: {label}"
        ]

        if info.get('id'):
            lines.append(
                f"🆔 المصدر: "
                f"<code>{info['id']}</code>"
            )

        if info.get('name'):
            lines.append(
                f"📛 الاسم: "
                f"{escape(str(info['name']))}"
            )

        if info.get('message_id'):
            lines.append(
                f"🔢 رقم الرسالة: "
                f"<code>{info['message_id']}</code>"
            )

        if info.get('date'):
            lines.append(
                f"📅 التاريخ: "
                f"<code>{info['date']}</code>"
            )

        await safe_send(
            context.bot,
            admin_id,
            "\n".join(lines),
            parse_mode='HTML'
        )

    except Exception:
        pass


def _should_notify_forward(
    context,
    chat_id
):
    try:
        bot_data = getattr(
            context,
            'bot_data',
            None
        )

        if not isinstance(
            bot_data,
            dict
        ):
            return False

        key = (
            f"_forward_notify_{chat_id}"
        )

        now = time.monotonic()

        last = bot_data.get(
            key,
            0.0
        )

        if not isinstance(
            last,
            (int, float)
        ):
            last = 0.0

        if (
            now - last
            < _FORWARD_NOTIFY_COOLDOWN_SECONDS
        ):
            return False

        bot_data[key] = now

        return True

    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
# Main / Cache Helpers
# ═══════════════════════════════════════════════════════════════════

async def _refresh_admin_commands_safe(
    bot,
    user_id,
    is_admin
):
    if not user_id:
        return False

    try:
        from main import refresh_admin_commands
    except ImportError:
        return False

    try:
        return bool(
            await refresh_admin_commands(
                bot,
                user_id,
                is_admin
            )
        )

    except Exception:
        return False


async def _invalidate_after_channel_change(
    user_id,
    channel_db_id=None,
    invalidate_posts=True
):
    keys = [
        f"start_data_{user_id}",
        f"user_{user_id}",
        f"user_{user_id}_True",
        f"user_{user_id}_False",
        f"channels_{user_id}",
    ]

    if channel_db_id is not None:
        keys.append(
            f"channel_info_{channel_db_id}"
        )

    await _safe_invalidate(
        *keys
    )

    try:
        from cache import (
            invalidate_user_cache
        )

        await invalidate_user_cache(
            user_id
        )

    except Exception:
        pass

    if (
        invalidate_posts
        and channel_db_id is not None
    ):
        try:
            await posts_cache.invalidate(
                channel_db_id
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# Group Rate Limiter
# ═══════════════════════════════════════════════════════════════════

class GroupRateLimiterManager:
    _limiters = {}
    _last_access = {}
    _lock = asyncio.Lock()

    MAX_SIZE = MAX_GROUP_LIMITERS_CACHE

    @classmethod
    async def get(cls, chat_id):
        async with cls._lock:
            now = time.time()

            if (
                len(cls._limiters)
                >= cls.MAX_SIZE
                and chat_id not in cls._limiters
            ):
                sorted_items = sorted(
                    cls._last_access.items(),
                    key=lambda item: item[1]
                )

                to_remove = sorted_items[
                    :max(
                        1,
                        cls.MAX_SIZE // 5
                    )
                ]

                for cid, _ in to_remove:
                    cls._limiters.pop(
                        cid,
                        None
                    )

                    cls._last_access.pop(
                        cid,
                        None
                    )

            if chat_id not in cls._limiters:
                cls._limiters[chat_id] = RateLimiter(
                    max_concurrent=5,
                    max_per_second=10
                )

            cls._last_access[
                chat_id
            ] = now

            return cls._limiters[
                chat_id
            ]

    @classmethod
    async def periodic_cleanup_task(cls):
        while True:
            try:
                await asyncio.sleep(
                    CACHE_CLEANUP_INTERVAL
                )

                now = time.time()

                async with cls._lock:
                    to_remove = [
                        cid
                        for cid, ts
                        in cls._last_access.items()
                        if now - ts > 7200
                    ]

                    for cid in to_remove:
                        cls._limiters.pop(
                            cid,
                            None
                        )

                        cls._last_access.pop(
                            cid,
                            None
                        )

                await _sec_auth_cache_cleanup()

            except asyncio.CancelledError:
                raise

            except Exception as e:
                logger.error(
                    f"❌ periodic_cleanup: {e}"
                )


async def _acquire_group_limiter(
    chat_id
):
    try:
        limiter = await GroupRateLimiterManager.get(
            chat_id
        )

        await limiter.acquire()

        return limiter, True

    except Exception as e:
        logger.warning(
            f"⚠️ group limiter acquire: {e}"
        )

        return None, False


async def _release_group_limiter(
    limiter,
    acquired
):
    if not limiter or not acquired:
        return

    try:
        release = getattr(
            limiter,
            'release',
            None
        )

        if callable(release):
            result = release()

            if asyncio.iscoroutine(
                result
            ):
                await result

    except Exception as e:
        logger.debug(
            f"group limiter release: {e}"
        )


# ═══════════════════════════════════════════════════════════════════
# Translation
# ═══════════════════════════════════════════════════════════════════

async def _trans(
    key,
    lang,
    default=""
):
    if not key:
        return default or ""

    try:
        if lang and lang != 'off':
            text = TranslationManager.get_text(
                lang,
                key
            )

            if text and text != key:
                return text

    except Exception:
        pass

    try:
        if lang and lang != 'off':
            text = await get_text(
                lang,
                key
            )

            if text and text != key:
                return text

    except Exception:
        pass

    return default or key


def _fmt(
    template,
    **kwargs
):
    try:
        return template.format(
            **kwargs
        )
    except (
        KeyError,
        IndexError
    ):
        return template


async def _ensure_lang(
    update,
    context
):
    lang = context.user_data.get(
        'lang'
    )

    if lang:
        return lang

    try:
        user_id = (
            update.effective_user.id
            if update
            and update.effective_user
            else None
        )

    except Exception:
        user_id = None

    if user_id:
        try:
            from cache import user_cache

            cached = await user_cache.get(
                user_id
            )

            if (
                cached
                and cached.get('language')
            ):
                lang = cached[
                    'language'
                ]

                context.user_data[
                    'lang'
                ] = lang

                return lang

        except Exception:
            pass

        try:
            lang = await asyncio.wait_for(
                DB.get_user_language(
                    user_id
                ),
                timeout=2.0
            ) or 'ar'

            context.user_data[
                'lang'
            ] = lang

            return lang

        except Exception:
            pass

    return 'ar'


def clear_lang_cache(context):
    try:
        context.user_data.pop(
            'lang',
            None
        )

        context.user_data.pop(
            'translation_cache',
            None
        )

        context.user_data.pop(
            'cached_translations',
            None
        )

        context.user_data.pop(
            'last_translation',
            None
        )

    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# Security Settings Cache
# ═══════════════════════════════════════════════════════════════════

async def get_security_settings_cached(
    chat_id
):
    cached = await settings_cache.get_security(
        chat_id
    )

    if cached is not None:
        return cached

    settings = await DB.get_security_settings(
        chat_id
    )

    if settings is None:
        settings = {}

    await settings_cache.set_security(
        chat_id,
        settings
    )

    return settings


async def get_auto_reply_settings_cached(
    chat_id
):
    cached = (
        await settings_cache
        .get_auto_reply_settings(
            chat_id
        )
    )

    if cached is not None:
        return cached

    settings = (
        await DB.get_auto_reply_settings(
            chat_id
        )
    )

    if settings is None:
        settings = {}

    await settings_cache.set_auto_reply_settings(
        chat_id,
        settings
    )

    return settings


async def invalidate_security_cache(
    chat_id=None
):
    await settings_cache.invalidate_security(
        chat_id
    )


async def invalidate_auto_reply_cache(
    chat_id=None
):
    await settings_cache.invalidate_auto_reply(
        chat_id
    )


# ═══════════════════════════════════════════════════════════════════
# Delayed Delete
# ═══════════════════════════════════════════════════════════════════

async def _delete_after_delay(
    bot,
    chat_id,
    message_id,
    delay=10
):
    try:
        await asyncio.sleep(
            max(0, delay)
        )

        await _safe_delete_message(
            bot,
            chat_id,
            message_id
        )

    except asyncio.CancelledError:
        raise

    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# Translation Detection
# ═══════════════════════════════════════════════════════════════════

async def _detect_and_translate(
    update,
    context,
    chat_id,
    user_id,
    text
):
    if (
        not text
        or len(text.strip())
        < TRANSLATION_MIN_TEXT_LENGTH
    ):
        return None

    try:
        lang = await _ensure_lang(
            update,
            context
        )

        if not lang or lang == 'off':
            return None

        if text.startswith('/'):
            return None

        stripped = text.strip()

        if stripped.startswith((
            'http://',
            'https://',
            'www.'
        )):
            return None

        is_arabic = (
            TranslationManager
            .detect_arabic(text)
        )

        if (
            lang == 'ar'
            and is_arabic
        ):
            return None

        if (
            lang != 'ar'
            and not is_arabic
        ):
            return None

        translated = (
            TranslationManager.translate(
                text,
                lang
            )
        )

        if (
            translated
            and translated != text
        ):
            return translated

    except Exception:
        pass

    return None


async def _send_translation_reply(
    bot,
    chat_id,
    original_message_id,
    translated,
    lang
):
    try:
        label = (
            TranslationManager
            .get_text(
                lang,
                "translation_label"
            )
            or "🌐 <b>Translation:</b>"
        )

    except Exception:
        label = (
            "🌐 <b>Translation:</b>"
        )

    try:
        kwargs = {
            "chat_id": chat_id,
            "text": (
                f"{label}\n"
                f"{escape(translated)}"
            ),
            "parse_mode": "HTML",
        }

        if original_message_id:
            kwargs[
                "reply_to_message_id"
            ] = original_message_id

        sent = await bot.send_message(
            **kwargs
        )

        asyncio.create_task(
            _delete_after_delay(
                bot,
                chat_id,
                sent.message_id,
                TRANSLATION_REPLY_DELETE_DELAY
            )
        )

    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# Penalties
# ═══════════════════════════════════════════════════════════════════

async def apply_violation_penalty(
    update,
    context,
    chat_id,
    user_id,
    violation_type,
    penalty_type,
    duration_seconds,
    lang='ar'
):
    try:
        username = ""
        first_name = ""
        chat_name = ""

        try:
            if update and update.effective_user:
                username = (
                    update.effective_user.username
                    or ""
                )

                first_name = (
                    update.effective_user.first_name
                    or ""
                )

            if update and update.effective_chat:
                chat_name = (
                    update.effective_chat.title
                    or ""
                )

        except Exception:
            pass

        return await apply_penalty(
            context.bot,
            chat_id,
            user_id,
            penalty_type,
            duration_seconds,
            f"violation: {violation_type}",
            moderator=context.bot.id,
            username=username,
            first_name=first_name,
            chat_name=chat_name,
            lang=lang
        )

    except asyncio.CancelledError:
        raise

    except Exception as e:
        logger.error(
            f"❌ apply_violation_penalty: {e}"
        )

        return False, str(e)[:100]


# ═══════════════════════════════════════════════════════════════════
# URL / Date Helpers
# ═══════════════════════════════════════════════════════════════════

def _is_safe_url(url):
    try:
        parsed = urlparse(url)

        if parsed.scheme not in (
            "http",
            "https"
        ):
            return False

        host = (
            parsed.hostname
            or ""
        ).lower()

        if not host:
            return False

        if any(
            ord(c) > 127
            for c in host
        ):
            return False

        try:
            ip = ipaddress.ip_address(
                host
            )

            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_reserved
                or ip.is_link_local
                or ip.is_multicast
            ):
                return False

        except ValueError:
            pass

        blocked = (
            "localhost",
            "127.",
            "0.0.0.0",
            "::1",
            "10.",
            "192.168.",
            "172.16.",
            "172.17.",
            "172.18.",
            "172.19.",
            "172.2",
            "172.30.",
            "172.31.",
            "169.254.",
            "metadata.google",
        )

        for pattern in blocked:
            if (
                host.startswith(pattern)
                or host == pattern.rstrip(".")
            ):
                return False

        return True

    except Exception:
        return False


def _parse_contest_date(
    date_str
):
    if not date_str:
        return None

    date_str = date_str.strip()

    try:
        return datetime.fromisoformat(
            date_str
        )

    except (
        ValueError,
        TypeError
    ):
        pass

    try:
        return datetime.fromisoformat(
            date_str.replace(
                " ",
                "T"
            )
        )

    except (
        ValueError,
        TypeError
    ):
        pass

    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y"
    ):
        try:
            return datetime.strptime(
                date_str,
                fmt
            )

        except (
            ValueError,
            TypeError
        ):
            continue

    return None


# ═══════════════════════════════════════════════════════════════════
# Admin Helpers
# ═══════════════════════════════════════════════════════════════════

async def _check_admin_in_chat(
    context,
    chat_id,
    user_id
):
    if user_id == CONFIG.PRIMARY_OWNER_ID:
        return True

    try:
        if await is_authorized_in_group(
            context.bot,
            chat_id,
            user_id
        ):
            return True

    except Exception:
        pass

    try:
        row = await DB.fetchval(
            "SELECT 1 FROM group_admins "
            "WHERE chat_id = ? "
            "AND user_id = ? LIMIT 1",
            (
                chat_id,
                user_id
            )
        )

        return row is not None

    except Exception:
        return False


async def _is_postgres_db():
    try:
        return (
            getattr(
                DB,
                "DB_TYPE",
                "sqlite"
            )
            == "postgres"
        )

    except Exception:
        return False


async def _is_mysql_db():
    try:
        return (
            getattr(
                DB,
                "DB_TYPE",
                "sqlite"
            )
            == "mysql"
        )

    except Exception:
        return False


async def _verify_bot_in_log_channel(
    context,
    channel_id
):
    if not channel_id:
        return False, "invalid_channel_id"

    try:
        bot_id = context.bot.id

    except Exception:
        return False, "bot_id_unavailable"

    if not bot_id:
        return False, "bot_id_missing"

    try:
        member = await asyncio.wait_for(
            context.bot.get_chat_member(
                channel_id,
                bot_id
            ),
            timeout=10.0
        )

    except asyncio.TimeoutError:
        return False, "timeout"

    except BadRequest as e:
        err = str(e).lower()

        if (
            "chat not found" in err
            or "bot is not a member" in err
            or "member not found" in err
            or "user not found" in err
        ):
            return False, "bot_not_member"

        if (
            "chat_admin_required" in err
            or "not enough rights" in err
        ):
            return False, "need_admin_rights"

        return False, "bad_request"

    except Exception as e:
        logger.warning(
            f"_verify_bot_in_log_channel: {e}"
        )

        return False, "unknown_error"

    status = getattr(
        member,
        "status",
        None
    )

    if status not in (
        "administrator",
        "creator"
    ):
        return False, "not_admin"

    if getattr(
        member,
        "can_post_messages",
        None
    ) is False:
        return False, "no_post_permission"

    return True, ""


def _verify_bot_in_log_channel_error_text(
    reason,
    lang
):
    mapping = {
        "invalid_channel_id":
            "❌ معرّف القناة غير صالح.",
        "timeout":
            "⏱️ انتهت مهلة الاتصال.",
        "bot_not_member":
            "❌ البوت ليس عضواً في القناة.",
        "need_admin_rights":
            "❌ البوت يحتاج صلاحيات مشرف.",
        "not_admin":
            "❌ البوت ليس مشرفاً.",
        "no_post_permission":
            "❌ البوت لا يملك صلاحية النشر.",
        "bad_request":
            "❌ تعذّر الوصول للقناة.",
    }

    return mapping.get(
        reason,
        "❌ تعذّر التحقق من قناة السجل."
    )


# ═══════════════════════════════════════════════════════════════════
# Channel Reference Validation
# ═══════════════════════════════════════════════════════════════════

try:
    from database_settings import (
        _is_valid_channel_ref
    )

except ImportError:
    _TG_USERNAME_RE_FALLBACK = re.compile(
        r'^[a-zA-Z][a-zA-Z0-9_]{3,31}$'
    )

    def _is_valid_channel_ref(
        value
    ):
        if value is None:
            return True

        value_str = str(
            value
        ).strip()

        if not value_str:
            return True

        if value_str.lstrip('-').isdigit():
            return True

        if value_str.startswith('@'):
            return bool(
                _TG_USERNAME_RE_FALLBACK.match(
                    value_str[1:]
                )
            )

        if _TG_USERNAME_RE_FALLBACK.match(
            value_str
        ):
            return True

        return False


# ═══════════════════════════════════════════════════════════════════
# Banned Word Matching
# ═══════════════════════════════════════════════════════════════════

def _contains_banned_word(
    text,
    banned_word
):
    if not text or not banned_word:
        return False

    try:
        normalized_text = (
            _normalize_text(text)
            .lower()
        )

        normalized_word = (
            _normalize_text(
                str(banned_word)
            )
            .lower()
        )

        if not normalized_word:
            return False

        escaped = re.escape(
            normalized_word
        )

        escaped = re.sub(
            r'\\\s+',
            r'\\s+',
            escaped
        )

        pattern = re.compile(
            rf'(?<!\w){escaped}(?!\w)',
            re.IGNORECASE | re.UNICODE
        )

        return bool(
            pattern.search(
                normalized_text
            )
        )

    except Exception:
        try:
            return (
                normalized_word
                == normalized_text.strip()
            )

        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════════
# Message Handlers
# ═══════════════════════════════════════════════════════════════════

class MessageHandlers:

    _PRIVATE_HANDLERS_MAP = {}

    @staticmethod
    async def handle_group(
        update,
        context
    ):
        if (
            not update
            or not update.effective_chat
            or not update.effective_message
        ):
            return

        chat_id = (
            update.effective_chat.id
        )

        limiter = None
        limiter_acquired = False

        try:
            (
                limiter,
                limiter_acquired
            ) = await _acquire_group_limiter(
                chat_id
            )

            await MessageHandlers._handle_group_impl(
                update,
                context
            )

        except asyncio.CancelledError:
            raise

        except Exception:
            logger.exception(
                "❌ handle_group unexpected error"
            )

        finally:
            await _release_group_limiter(
                limiter,
                limiter_acquired
            )

    @staticmethod
    async def _handle_group_impl(
        update,
        context
    ):
        if (
            not update.effective_chat
            or not update.effective_message
        ):
            return

        chat_id = (
            update.effective_chat.id
        )

        await _lazy_init_columns()

        message = (
            update.effective_message
        )

        msg_id = getattr(
            message,
            'message_id',
            None
        )

        # =========================================================
        # لا نضع return هنا للـautomatic forward.
        #
        # الإصدار السابق كان يتجاهله بالكامل:
        #
        # if is_automatic_forward:
        #     return
        #
        # وهذا كان يمنع delete_forwarded وspam detector من الوصول
        # إلى الرسالة.
        # =========================================================

        is_automatic_forward = _as_bool(
            getattr(
                message,
                'is_automatic_forward',
                False
            ),
            False
        )

        is_anonymous = False

        if update.effective_user:
            user_id = (
                update.effective_user.id
            )

        elif getattr(
            message,
            'sender_chat',
            None
        ) is not None:
            user_id = (
                message.sender_chat.id
            )

            is_anonymous = True

        else:
            return

        msg_text = (
            message.text
            or ""
        )

        msg_caption = (
            message.caption
            or ""
        )

        full_text = (
            msg_text
            + " "
            + msg_caption
        ).strip()

        normalized_text = _normalize_text(
            full_text
        )

        # النص الكامل للتحليل، بما في ذلك أزرار Inline.
        analysis_text = (
            _get_message_analysis_text(
                message
            )
        )

        try:
            METRICS.increment_messages()

        except Exception:
            pass

        settings = (
            await get_security_settings_cached(
                chat_id
            )
        )

        if not isinstance(
            settings,
            dict
        ):
            settings = {}

        # =========================================================
        # Settings - safe bool
        # =========================================================

        _df_raw = settings.get(
            'delete_forwarded'
        )

        _df_bool = _as_bool(
            _df_raw,
            False
        )

        _protected_fb = _as_bool(
            settings.get(
                'delete_protected_forward'
            ),
            False
        )

        _protected_any = _as_bool(
            settings.get(
                'delete_protected_any'
            ),
            False
        )

        _spam_enabled = _as_bool(
            settings.get(
                'delete_spam_score',
                1
            ),
            True
        )

        _postbot_enabled = _as_bool(
            settings.get(
                'delete_postbot_pattern',
                0
            ),
            False
        )

        # =========================================================
        # Forward detection
        # =========================================================

        _det = get_forward_detection_reason(
            message
        )

        _is_fwd = _as_bool(
            _det.get(
                'is_forwarded',
                False
            ),
            False
        )

        _is_protected = _as_bool(
            _det.get(
                'is_protected',
                False
            ),
            False
        )

        _has_hint = _as_bool(
            _det.get(
                'has_hint',
                False
            ),
            False
        )

        _is_auto_fwd = _as_bool(
            _det.get(
                'has_automatic_forward',
                False
            ),
            False
        )

        _is_protected_forward = (
            _protected_fb
            and _is_protected
            and _has_hint
            and not _is_fwd
            and not _is_auto_fwd
        )

        _is_protected_any_fwd = (
            _protected_any
            and _is_protected
            and not _is_auto_fwd
            and not _is_fwd
            and not _is_protected_forward
        )

        # =========================================================
        # Spam score
        # =========================================================

        _spam_score = 0
        _spam_reasons = []

        if _spam_enabled:
            try:
                (
                    _spam_score,
                    _spam_reasons
                ) = _compute_spam_score(
                    message
                )

            except Exception as e:
                logger.debug(
                    f"spam_score: {e}"
                )

        _is_spam = (
            _spam_enabled
            and _spam_score
            >= SPAM_SCORE_THRESHOLD
        )

        # =========================================================
        # PostBot detection
        # =========================================================

        _postbot_match = False

        if _postbot_enabled:
            try:
                _postbot_match = (
                    _is_postbot_pattern(
                        analysis_text
                    )
                )

            except Exception:
                _postbot_match = False

        (
            _btn_count,
            _btn_urls_raw
        ) = _get_message_button_data(
            message
        )

        _btn_texts = (
            _get_message_button_texts(
                message
            )
        )

        _btn_urls = [
            str(url)[:120]
            for url in _btn_urls_raw[:10]
        ]

        _btn_labels = [
            _normalize_text(text)[:100]
            for text in _btn_texts[:12]
        ]

        # =========================================================
        # Forward active
        # =========================================================

        _fwd_active = (
            (
                _is_fwd
                or _is_auto_fwd
                or _is_protected_forward
                or _is_protected_any_fwd
            )
            and _df_bool
        )

        _log_level = (
            logging.WARNING
            if (
                _fwd_active
                or _is_spam
                or _postbot_match
            )
            else logging.INFO
        )

        logger.log(
            _log_level,
            f"🚨 HARD-DIAG | "
            f"chat={chat_id} "
            f"user={user_id} "
            f"msg={msg_id} "
            f"{'[ANON]' if is_anonymous else ''} | "
            f"has_text={bool(msg_text)} "
            f"has_caption={bool(msg_caption)} "
            f"text_len={len(full_text)} | "
            f"analysis_len={len(analysis_text)} | "
            f"has_photo={bool(message.photo)} "
            f"has_video={bool(message.video)} | "
            f"buttons={_btn_count} | "
            f"has_protected={_is_protected} "
            f"is_auto_fwd={_is_auto_fwd} | "
            f"delete_forwarded={_df_raw!r} "
            f"delete_forwarded_bool={_df_bool} "
            f"protected_fb={_protected_fb} "
            f"protected_any={_protected_any} | "
            f"spam_enabled={_spam_enabled} "
            f"spam_score={_spam_score} "
            f"is_spam={_is_spam} | "
            f"postbot_enabled={_postbot_enabled} "
            f"postbot_match={_postbot_match} | "
            f"is_forwarded={_is_fwd} | "
            f"protected_fb_forward="
            f"{_is_protected_forward} "
            f"protected_any_forward="
            f"{_is_protected_any_fwd}"
        )

        if full_text:
            logger.info(
                f"   📝 TEXT | "
                f"{full_text[:250]!r}"
            )

        else:
            logger.info(
                "   📝 TEXT | (empty)"
            )

        if _btn_labels:
            logger.info(
                f"   🔘 BTN_TEXTS | "
                f"{_btn_labels}"
            )

        if _btn_urls:
            logger.info(
                f"   🔗 BTN_URLS | "
                f"{_btn_urls[:5]}"
            )

        if _spam_score > 0:
            logger.warning(
                f"   🎯 SPAM-SCORE="
                f"{_spam_score} | "
                f"reasons={_spam_reasons}"
            )

        elif _spam_enabled:
            logger.info(
                "   ⏭️ SPAM-SCORE=0 | "
                "no matches"
            )

        if _postbot_match:
            logger.warning(
                f"   🤖 POSTBOT-MATCH | "
                f"enabled={_postbot_enabled}"
            )

        if (
            normalized_text
            and normalized_text
            != full_text
        ):
            logger.info(
                f"   🧹 NORMALIZED | "
                f"raw_len={len(full_text)} "
                f"norm_len={len(normalized_text)}"
            )

        # =========================================================
        # 0) Service
        # =========================================================

        if _as_bool(
            settings.get(
                'delete_service'
            ),
            False
        ):
            if (
                message.new_chat_members
                or message.left_chat_member
            ):
                await _safe_delete_message(
                    context.bot,
                    chat_id,
                    message.message_id
                )

                return

        # =========================================================
        # 1) Forwarded
        # =========================================================

        if _df_bool:
            effective_forwarded = (
                _is_fwd
                or _is_auto_fwd
                or _is_protected_forward
                or _is_protected_any_fwd
            )

            if effective_forwarded:
                tag = ""

                if _is_auto_fwd:
                    tag = " [AUTO-FORWARD]"

                elif _is_protected_any_fwd:
                    tag = " [PROTECTED-ANY]"

                elif _is_protected_forward:
                    tag = " [PROTECTED-FB]"

                logger.warning(
                    f"🎯 HANDLE-FWD | "
                    f"chat={chat_id} "
                    f"user={user_id} "
                    f"msg={msg_id}"
                    f"{tag}"
                )

                await MessageHandlers._delete_and_warn(
                    update,
                    context,
                    chat_id,
                    user_id,
                    "forwarded",
                    settings,
                    is_anonymous=is_anonymous
                )

                return

        # =========================================================
        # 2) Spam Score
        # =========================================================

        if _is_spam:
            logger.warning(
                f"🚫 HANDLE-SPAM | "
                f"chat={chat_id} "
                f"user={user_id} "
                f"msg={msg_id} | "
                f"score={_spam_score} "
                f"reasons={_spam_reasons}"
            )

            await MessageHandlers._delete_and_warn(
                update,
                context,
                chat_id,
                user_id,
                "spam_score",
                settings,
                is_anonymous=is_anonymous
            )

            return

        # =========================================================
        # 3) PostBot Pattern
        # =========================================================

        if (
            _postbot_enabled
            and _postbot_match
        ):
            logger.warning(
                f"🤖 HANDLE-POSTBOT | "
                f"chat={chat_id} "
                f"user={user_id} "
                f"msg={msg_id}"
            )

            await MessageHandlers._delete_and_warn(
                update,
                context,
                chat_id,
                user_id,
                "postbot_pattern",
                settings,
                is_anonymous=is_anonymous
            )

            return

        # =========================================================
        # 4) Links
        # =========================================================

        if _as_bool(
            settings.get(
                'delete_links'
            ),
            False
        ):
            try:
                has_link = (
                    TextUtils.contains_link(
                        normalized_text
                    )
                )

            except Exception:
                has_link = False

            if has_link:
                await MessageHandlers._delete_and_warn(
                    update,
                    context,
                    chat_id,
                    user_id,
                    "link",
                    settings,
                    is_anonymous=is_anonymous
                )

                return

        # =========================================================
        # 5) Mentions
        # =========================================================

        if _as_bool(
            settings.get(
                'mentions'
            ),
            False
        ):
            try:
                has_mention = (
                    TextUtils.contains_mention(
                        normalized_text
                    )
                )

            except Exception:
                has_mention = False

            if has_mention:
                await MessageHandlers._delete_and_warn(
                    update,
                    context,
                    chat_id,
                    user_id,
                    "mention",
                    settings,
                    is_anonymous=is_anonymous
                )

                return

        # =========================================================
        # 6) Banned Words
        # =========================================================

        if _as_bool(
            settings.get(
                'delete_banned_words'
            ),
            False
        ):
            banned_words = (
                await get_banned_words_cached(
                    chat_id
                )
            )

            if banned_words:
                matched_banned_word = None

                # نفحص النص والأزرار معًا
                banned_scan_text = (
                    analysis_text
                )

                for banned_word in banned_words:
                    if _contains_banned_word(
                        banned_scan_text,
                        banned_word
                    ):
                        matched_banned_word = (
                            banned_word
                        )

                        break

                if matched_banned_word:
                    logger.info(
                        f"   🎯 BANNED-MATCH | "
                        f"word={matched_banned_word!r}"
                    )

                    await MessageHandlers._delete_and_warn(
                        update,
                        context,
                        chat_id,
                        user_id,
                        "banned_word",
                        settings,
                        is_anonymous=is_anonymous
                    )

                    return

        # =========================================================
        # 7) Max Length
        # =========================================================

        max_len_raw = settings.get(
            'max_message_length',
            0
        )

        try:
            max_len = int(
                max_len_raw or 0
            )

        except (
            TypeError,
            ValueError
        ):
            max_len = 0

        if (
            max_len > 0
            and len(normalized_text)
            > max_len
        ):
            await MessageHandlers._delete_and_warn(
                update,
                context,
                chat_id,
                user_id,
                "max_len",
                settings,
                is_anonymous=is_anonymous
            )

            return

        # =========================================================
        # 8) Media
        # =========================================================

        media_checks = [
            (
                message.video,
                'delete_videos',
                'video'
            ),
            (
                message.audio,
                'delete_audio',
                'audio'
            ),
            (
                message.voice,
                'delete_voice',
                'voice'
            ),
            (
                message.animation,
                'delete_animation',
                'animation'
            ),
            (
                message.document,
                'delete_documents',
                'document'
            ),
            (
                message.sticker,
                'delete_stickers',
                'sticker'
            ),
            (
                message.photo,
                'delete_photos',
                'photo'
            ),
            (
                message.video_note,
                'delete_video_note',
                'video_note'
            ),
        ]

        for media, setting_key, vtype in media_checks:
            if (
                media
                and _as_bool(
                    settings.get(
                        setting_key
                    ),
                    False
                )
            ):
                await MessageHandlers._delete_and_warn(
                    update,
                    context,
                    chat_id,
                    user_id,
                    vtype,
                    settings,
                    is_anonymous=is_anonymous
                )

                return

        # =========================================================
        # 9) Translation
        # =========================================================

        if msg_text and not is_anonymous:
            try:
                translated = (
                    await _detect_and_translate(
                        update,
                        context,
                        chat_id,
                        user_id,
                        msg_text
                    )
                )

                if translated:
                    lang = await _ensure_lang(
                        update,
                        context
                    )

                    await _send_translation_reply(
                        context.bot,
                        chat_id,
                        message.message_id,
                        translated,
                        lang
                    )

            except Exception:
                pass

        # =========================================================
        # 10) Auto Reply
        # =========================================================

        if msg_text:
            await MessageHandlers._process_auto_reply(
                update,
                context,
                chat_id,
                msg_text,
                user_id
            )

    @staticmethod
    def _get_penalty_duration(
        settings,
        violation_type
    ):
        if violation_type in (
            'flood',
            'antiflood'
        ):
            return settings.get(
                'antiflood_penalty_duration',
                3600
            )

        if violation_type in (
            'night',
            'night_mode'
        ):
            return settings.get(
                'night_mode_action_duration',
                3600
            )

        if violation_type in (
            'warn_penalty',
            'warn'
        ):
            return settings.get(
                'warn_penalty_duration',
                3600
            )

        return settings.get(
            'auto_mute_duration',
            3600
        )

    @staticmethod
    async def _get_violation_message(
        violation_type,
        lang
    ):
        trans_key = (
            f"violation_{violation_type}"
        )

        default_messages = {
            'link': '🚫',
            'mention': '🚫',
            'banned_word': '🚫',
            'max_len': '📏',
            'forwarded': '↩️',
            'video': '🎬',
            'audio': '🎵',
            'voice': '🎤',
            'animation': '🎞️',
            'document': '📄',
            'sticker': '🖼️',
            'photo': '📷',
            'video_note': '🎥',
            'postbot_pattern': '🤖',
            'spam_score': '🚫',
        }

        default = default_messages.get(
            violation_type,
            f'🚫 {violation_type}'
        )

        return await _trans(
            trans_key,
            lang,
            default
        )

    @staticmethod
    async def _delete_and_warn(
        update,
        context,
        chat_id,
        user_id,
        violation_type,
        settings,
        is_anonymous=False
    ):
        logger.warning(
            f"🔧 DELETE-WARN | "
            f"chat={chat_id} "
            f"user={user_id} "
            f"violation={violation_type}"
        )

        lang = await _ensure_lang(
            update,
            context
        )

        forward_info = None

        if violation_type == 'forwarded':
            try:
                message = (
                    update.effective_message
                )

                if message is not None:
                    forward_info = (
                        extract_forward_info(
                            message
                        )
                    )

            except Exception:
                pass

        message_preview = None

        try:
            message = (
                update.effective_message
            )

            if message is not None:
                message_preview = (
                    message.text
                    or message.caption
                    or ""
                ).strip() or None

        except Exception:
            pass

        delete_ok = False
        _msg_id = None

        try:
            message = (
                update.effective_message
            )

            if (
                message
                and message.message_id
            ):
                _msg_id = (
                    message.message_id
                )

                delete_ok = (
                    await _safe_delete_message(
                        context.bot,
                        chat_id,
                        message.message_id
                    )
                )

        except Exception as e:
            logger.error(
                f"delete exception: {e}"
            )

            delete_ok = False

        if (
            delete_ok
            and FEATURE_LOG_DELETIONS
        ):
            if await _can_send_log(
                chat_id
            ):
                try:
                    if is_anonymous:
                        user_first = (
                            "مشرف مجهول"
                        )

                        user_username = None

                    elif update.effective_user:
                        user_first = (
                            getattr(
                                update.effective_user,
                                'first_name',
                                None
                            )
                            or "User"
                        )

                        user_username = getattr(
                            update.effective_user,
                            'username',
                            None
                        )

                    else:
                        user_first = (
                            "Unknown"
                        )

                        user_username = None

                    log_text = (
                        _build_delete_log_text(
                            chat_id=chat_id,
                            user_id=user_id,
                            user_first_name=user_first,
                            user_username=user_username,
                            violation_type=violation_type,
                            forward_info=forward_info,
                            message_preview=message_preview,
                            is_anonymous=is_anonymous
                        )
                    )

                    await _dispatch_log(
                        notify_group_log(
                            context,
                            chat_id,
                            log_text
                        ),
                        label=(
                            f"delete-{violation_type}"
                        )
                    )

                except Exception as e:
                    logger.warning(
                        f"group_log spawn: {e}"
                    )

        if (
            forward_info
            and not is_anonymous
            and _should_notify_forward(
                context,
                chat_id
            )
        ):
            try:
                owner_id = int(
                    getattr(
                        CONFIG,
                        'PRIMARY_OWNER_ID',
                        0
                    )
                    or 0
                )

                if owner_id:
                    task = asyncio.create_task(
                        _notify_admin_about_forward(
                            context,
                            owner_id,
                            forward_info
                        )
                    )

                    def _forward_done(t):
                        try:
                            if (
                                not t.cancelled()
                                and t.exception()
                            ):
                                logger.debug(
                                    "forward notify "
                                    "task failed: "
                                    f"{t.exception()}"
                                )

                        except Exception:
                            pass

                    task.add_done_callback(
                        _forward_done
                    )

            except Exception:
                pass

        if (
            not delete_ok
            and violation_type in (
                'forwarded',
                'spam_score',
                'postbot_pattern'
            )
        ):
            logger.error(
                "⏭️ توقف — الحذف فشل"
            )

            return

        if is_anonymous:
            try:
                vm = (
                    await MessageHandlers
                    ._get_violation_message(
                        violation_type,
                        lang
                    )
                )

                warn_title = await _trans(
                    'violation_warning_title',
                    lang,
                    "⚠️"
                )

                anon_notice = (
                    "👻 <b>مشرف مجهول</b>"
                )

                sent_msg = (
                    await context.bot.send_message(
                        chat_id,
                        f"{warn_title}\n"
                        f"{vm}\n"
                        f"{anon_notice}",
                        parse_mode='HTML'
                    )
                )

                asyncio.create_task(
                    _delete_after_delay(
                        context.bot,
                        chat_id,
                        sent_msg.message_id,
                        PENALTY_MESSAGE_DELETE_DELAY
                    )
                )

            except Exception:
                pass

            return

        try:
            violation_count = (
                await DB.increment_violation_count(
                    user_id,
                    chat_id
                )
            )

        except Exception:
            violation_count = 1

        penalty_rule = None

        try:
            penalty_rule = (
                await DB.get_violation_penalty(
                    chat_id,
                    violation_type
                )
            )

        except Exception:
            pass

        if penalty_rule:
            penalty_type = (
                penalty_rule['penalty_type']
            )

            if penalty_type == 'none':
                penalty_type = None
                duration_seconds = 0

            else:
                duration_seconds = (
                    penalty_rule[
                        'duration_seconds'
                    ]
                )

        else:
            penalty_type = settings.get(
                'auto_penalty',
                'none'
            )

            if penalty_type == 'none':
                penalty_type = None
                duration_seconds = 0

            elif penalty_type not in (
                'mute',
                'ban',
                'restrict',
                'kick',
                'warn'
            ):
                penalty_type = 'mute'

                duration_seconds = (
                    MessageHandlers
                    ._get_penalty_duration(
                        settings,
                        violation_type
                    )
                )

            else:
                duration_seconds = (
                    MessageHandlers
                    ._get_penalty_duration(
                        settings,
                        violation_type
                    )
                )

        try:
            await DB.add_admin_log(
                chat_id,
                context.bot.id,
                f"violation_{violation_type}",
                user_id
            )

        except Exception:
            pass

        vm = (
            await MessageHandlers
            ._get_violation_message(
                violation_type,
                lang
            )
        )

        try:
            user_name = escape(
                update.effective_user.first_name
                or "User"
            )

            warn_title = await _trans(
                'violation_warning_title',
                lang,
                "⚠️"
            )

            count_label = await _trans(
                'violation_count_label',
                lang,
                "📊"
            )

            delete_notice = await _trans(
                'violation_delete_notice',
                lang,
                "⏳"
            )

            sent_msg = (
                await context.bot.send_message(
                    chat_id,
                    f"{warn_title}\n"
                    f"{vm}\n"
                    f"👤 {user_name}\n"
                    f"{count_label}: "
                    f"{violation_count}\n"
                    f"{delete_notice}",
                    parse_mode='HTML'
                )
            )

            asyncio.create_task(
                _delete_after_delay(
                    context.bot,
                    chat_id,
                    sent_msg.message_id,
                    PENALTY_MESSAGE_DELETE_DELAY
                )
            )

        except Exception:
            pass

        if penalty_type:
            max_strikes = (
                settings.get(
                    'violation_strikes'
                )
                or settings.get(
                    'max_warnings'
                )
                or 3
            )

            try:
                max_strikes = max(
                    1,
                    int(max_strikes)
                )

            except (
                TypeError,
                ValueError
            ):
                max_strikes = 3

            if (
                violation_count
                >= max_strikes
            ):
                (
                    success,
                    msg
                ) = await apply_violation_penalty(
                    update,
                    context,
                    chat_id,
                    user_id,
                    violation_type,
                    penalty_type,
                    duration_seconds,
                    lang=lang
                )

                if success:
                    try:
                        target_first = ""
                        target_username = None

                        if update.effective_user:
                            target_first = (
                                update.effective_user.first_name
                                or ""
                            )

                            target_username = (
                                update.effective_user.username
                            )

                        await _notify_group_log_penalty(
                            context,
                            chat_id=chat_id,
                            target_user_id=user_id,
                            target_first_name=target_first,
                            target_username=target_username,
                            penalty_type=penalty_type,
                            duration_seconds=duration_seconds,
                            source="auto",
                            violation_type=violation_type
                        )

                    except Exception:
                        pass

                    try:
                        msg_prefix = await _trans(
                            'violation_penalty_applied',
                            lang,
                            "🚨 {msg}"
                        )

                        sent_penalty = (
                            await safe_send(
                                context.bot,
                                chat_id,
                                _fmt(
                                    msg_prefix,
                                    msg=msg
                                ),
                                parse_mode='HTML'
                            )
                        )

                        if (
                            sent_penalty is not None
                            and getattr(
                                sent_penalty,
                                'message_id',
                                None
                            )
                        ):
                            asyncio.create_task(
                                _delete_after_delay(
                                    context.bot,
                                    chat_id,
                                    sent_penalty.message_id,
                                    PENALTY_MESSAGE_DELETE_DELAY
                                )
                            )

                        await DB.reset_violation_count(
                            user_id,
                            chat_id
                        )

                    except Exception:
                        pass

    @staticmethod
    async def _process_auto_reply(
        update,
        context,
        chat_id,
        text,
        user_id=None
    ):
        try:
            ars = (
                await get_auto_reply_settings_cached(
                    chat_id
                )
            )

            if not _as_bool(
                ars.get(
                    'enabled',
                    False
                ),
                False
            ):
                return False

            if _as_bool(
                ars.get(
                    'ignore_bots',
                    True
                ),
                True
            ):
                effective_user = getattr(
                    update,
                    'effective_user',
                    None
                )

                if (
                    effective_user
                    and getattr(
                        effective_user,
                        'is_bot',
                        False
                    )
                ):
                    return False

            if _as_bool(
                ars.get(
                    'only_admins',
                    False
                ),
                False
            ):
                if not await is_authorized_in_group(
                    context.bot,
                    chat_id,
                    user_id or 0
                ):
                    return False

            reply = await DB.get_auto_reply(
                text,
                chat_id
            )

            if reply:
                reply_text = (
                    reply.get(
                        'reply',
                        ''
                    )
                    or ''
                )

                if reply_text:
                    await safe_send(
                        context.bot,
                        chat_id,
                        reply_text
                    )

                await _increment_usage_async(
                    chat_id,
                    text
                )

                return True

            file_reply = get_reply_from_file(
                text
            )

            if file_reply:
                await safe_send(
                    context.bot,
                    chat_id,
                    file_reply
                )

                return True

            return False

        except Exception as e:
            logger.error(
                f"❌ auto_reply: {e}"
            )

            return False

    @staticmethod
    async def handle_private(
        update,
        context
    ):
        try:
            if not update.effective_user:
                return

            user_id = (
                update.effective_user.id
            )

            state = StateManager.get(
                user_id
            )

            handler_name = (
                MessageHandlers
                ._PRIVATE_HANDLERS_MAP
                .get(state)
            )

            if handler_name:
                handler = getattr(
                    MessageHandlers,
                    handler_name,
                    None
                )

                if handler:
                    await handler(
                        update,
                        context
                    )

        except Exception:
            logger.exception(
                "handle_private error"
            )

    @staticmethod
    async def handle_service(
        update,
        context
    ):
        if (
            not update.effective_chat
            or not update.effective_message
        ):
            return

        chat_id = (
            update.effective_chat.id
        )

        message = (
            update.effective_message
        )

        is_service = any([
            message.new_chat_members,
            message.left_chat_member,
            message.new_chat_title,
            message.new_chat_photo,
            message.delete_chat_photo,
            message.pinned_message,
            getattr(
                message,
                'video_chat_started',
                None
            ),
            getattr(
                message,
                'video_chat_ended',
                None
            ),
            getattr(
                message,
                'video_chat_scheduled',
                None
            ),
            getattr(
                message,
                'video_chat_participants_invited',
                None
            ),
            getattr(
                message,
                'forum_topic_created',
                None
            ),
            getattr(
                message,
                'forum_topic_closed',
                None
            ),
            getattr(
                message,
                'forum_topic_reopened',
                None
            ),
            getattr(
                message,
                'general_forum_topic_hidden',
                None
            ),
            getattr(
                message,
                'general_forum_topic_unhidden',
                None
            ),
        ])

        if not is_service:
            return

        try:
            settings = (
                await get_security_settings_cached(
                    chat_id
                )
            )

            if _as_bool(
                settings.get(
                    'delete_service'
                ),
                False
            ):
                await _safe_delete_message(
                    context.bot,
                    chat_id,
                    message.message_id
                )

        except Exception:
            pass

    @staticmethod
    async def handle_join_request(
        update,
        context
    ):
        if (
            not update.effective_chat
            or not update.effective_user
        ):
            return

        chat_id = (
            update.effective_chat.id
        )

        user_id = (
            update.effective_user.id
        )

        settings = (
            await get_security_settings_cached(
                chat_id
            )
        )

        if _as_bool(
            settings.get(
                'auto_reject_join'
            ),
            False
        ):
            try:
                await asyncio.sleep(
                    0.05
                )

                await context.bot.decline_chat_join_request(
                    chat_id,
                    user_id
                )

                return

            except Exception as e:
                logger.warning(
                    f"decline join: {e}"
                )

        if _as_bool(
            settings.get(
                'auto_approve_join'
            ),
            False
        ):
            try:
                await asyncio.sleep(
                    0.05
                )

                await context.bot.approve_chat_join_request(
                    chat_id,
                    user_id
                )

            except Exception as e:
                logger.warning(
                    f"approve join: {e}"
                )


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

__all__ = [
    "MessageHandlers",
    "GroupRateLimiterManager",
    "clear_lang_cache",
    "_safe_delete_message",
    "_invalidate_after_channel_change",
    "apply_violation_penalty",
    "_notify_dev_log",
    "is_forwarded",
    "extract_forward_info",
    "get_forward_detection_reason",
    "notify_group_log",
    "_lazy_init_columns",
    "_normalize_text",
    "_compute_spam_score",
    "_is_postbot_pattern",
    "_get_message_button_data",
    "_get_message_button_texts",
    "_get_message_analysis_text",
    "_as_bool",
    "FEATURE_LOG_DELETIONS",
    "FEATURE_LOG_PENALTIES",
    "FEATURE_LOG_GIFTS",
    "FEATURE_LOG_ADMIN_CHANGES",
    "SPAM_SCORE_THRESHOLD",
]