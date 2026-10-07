#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_message.py - v7.18.8
(متوافق مع detectors v4.0.2 ASYNC-NATIVE — 14 Layers)
=============================================================================
🆕 v7.18.8 — ASYNC-NATIVE INTEGRATION (تكامل مع detectors v4.0.2):
    🔴 FIX-ASYNC-1: استخدام analyze_message_full_async بدل analyze_message_full
                    → لا حجب event loop أثناء:
                      - URL enrichment (Safe Browsing + WHOIS + Expansion)
                      - OCR على الصور الكبيرة
                      - Audio transcription (Whisper/Google)
                      - Video frame extraction + OCR
                      - NSFW classification
                      - Steganography LSB scan
    🔴 FIX-ASYNC-2: import احتياطي (fallback) لـ analyze_message_full
                    في حال عدم توفر النسخة async → يعمل عبر to_thread
    🟠 FIX-ASYNC-3: توحيد Wrapper _run_multilayer_analysis
                    لتبسيط منطق الاستدعاء + fallback واضح
    🟠 FIX-ASYNC-4: TypeError عند عدم دعم bot kwarg → fallback
                    عبر asyncio.to_thread(analyze_message_full, message, bot)
    🟡 FIX-ASYNC-5: قياس زمن التحليل (DEBUG فقط) + log عند > 3s
    🟢 FIX-ASYNC-6: توثيق واضح لكل مسار (async → sync → thread)

🆕 v7.18.7 — CORRECTIVE RELEASE (بعد مراجعتين دقيقتين):
    🔴 FIX-1: _apply_ban_add_rate_limit — args معكوسة في _check_flood
    🟠 FIX-2: _lazy_init_columns — PG ALTER monolithic + fallback فردي
    🟠 FIX-3: توحيد _POSTBOT_RAW_IDS + _normalize_tg_id
    🟡 FIX-4: _resolve_penalty — تبسيط منطق try/except المزدوج
    🟡 FIX-5: _private_handler_signature_cache — سقف 128 إدخال
    🟢 FIX-6: توثيق سياسة _detect_and_translate صراحةً
    🟢 FIX-7: MessageOriginHiddenUser — fallback "Hidden User"
    🟢 FIX-8: _POSTBOT_CHANNEL_IDS — alias deprecated للتوافق
    📝 FIX-9: log error عند فشل PG migration fallback

🆕 v7.18.6 — PERFORMANCE HARDENING (تقليل round-trips):
    🟠 PERF-1: cache محلي لـ notify_group_log — 60s TTL لكل chat_id
    🟠 PERF-2: cache محلي مزدوج لـ get_security_settings_cached (5s)
    🟠 PERF-3: حماية من قيم غير dict من DB (Normalization)
    🟠 PERF-5: _resolve_penalty — دعم dict + asyncpg.Record + MySQL Row
    🟠 PERF-6: notify_group_log — إبطال cache عند تغيير إعدادات المجموعة
    🟡 PERF-7: _check_admin_in_chat — cache 30s لنتيجة group_admins
    🟡 PERF-9: _lazy_init_columns — دمج ALTER على PostgreSQL
    🟢 PERF-10: توثيق واضح لكل cache مع TTL وحد أقصى للحجم
    ✅ PERF-4-RESTORED: احتُفظ بالسلوك الأصلي لـ reset_violation_count

🆕 v7.18.5 — حماية المستخدمين من الحجب التلقائي:
    🛡️ عدم إضافة users/hidden_users للقائمة السوداء
    🛡️ فحص positive-ID كحماية إضافية
    📝 لوج SKIP-BLACKLIST-USER و SKIP-BLACKLIST-POSITIVE-ID

🆕 v7.18.4 — إصلاحات شاملة:
    🔧 إزالة كود ميت، نقل _private_handler_signature_cache، تبسيط regex
    🔧 نوع _flood_tracker → DefaultDict، cooldown لتنظيف bot_data
    🔧 حماية escape(translated) من None

🆕 v7.18.3 — Auto-Block Sources + Post Bot Detection:
    🔥 تكامل كامل مع database_auto_block
    🔥 get_forward_info() — دالة موحّدة
    🔥 /autoblocked command

🆕 v7.18.2b — Post Bot من قنوات خاصة
🆕 v7.18.2 — Post Bot detection بالاسم
🆕 v7.18.1 — FORCE_DELETE_BUTTON_LINKS
🆕 v7.18.0 — Multi-Layer (7 layers)
🆕 v7.17.2 — return_diagnostics
🆕 v7.17.1 — 8 FIX
=============================================================================
"""

import asyncio
import logging
import time
import os
import re
import inspect
import ipaddress
from html import escape
from functools import partial
from typing import (
    Optional, Dict, Any, List, Tuple, Callable, Awaitable, DefaultDict,
)
from datetime import datetime
from urllib.parse import urlparse
from collections import defaultdict, deque, OrderedDict

from telegram.error import BadRequest

from config import CONFIG
from database import DB, TimeUtils, internal_cache
from utils import (
    TextUtils, safe_send, is_authorized_in_group,
    apply_penalty, METRICS, get_text, StateManager,
    RateLimiter,
    get_banned_words_cached,
    get_reply_from_file,
    _increment_usage_async,
    TranslationManager,
)
from cache import settings_cache, posts_cache


logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# استيراد محرك الكشف v4.0.2 ASYNC-NATIVE
# ═════════════════════════════════════════════════════════════════════

try:
    from handlers.handlers_message_detectors import (
        DEBUG_DIAG, DEBUG_SPAM,
        SPAM_SCORE_THRESHOLD, POSTBOT_AUTO_BLOCK_CONFIDENCE,
        SPAM_HARD_THRESHOLD, SPAM_CRITICAL_THRESHOLD,
        ANTIEVASION_COMPACT_WORDS,
        _MessageContext,
        _strip_combining_marks, _deleet, _apply_homoglyphs_safe,
        _normalize_text, _strip_emoji_for_domain,
        _has_hidden_chars, _merge_split_urls,
        _extract_entity_urls, _has_link_entity,
        _extract_url_from_button, _button_is_external,
        _extract_button_context, _extract_vcard_urls,
        _extract_venue_url, _extract_poll_text,
        _get_message_button_data, _get_message_button_texts,
        _get_message_analysis_text,
        _has_domain_pattern, _contains_link_enhanced,
        _contains_email, _contains_at_channel, _contains_tg_scheme,
        _has_button_link, _extract_button_link_urls,
        _extract_spam_words, _count_unique_matches, _count_text_urls,
        _compute_spam_score, _is_postbot_pattern, _postbot_pattern_confidence,
        analyze_message, get_spam_diagnostics,
        is_spam, is_high_confidence_spam, is_critical_spam,
        should_ignore_as_low_signal,
    )
except ImportError:
    try:
        from handlers_message_detectors import (
            DEBUG_DIAG, DEBUG_SPAM,
            SPAM_SCORE_THRESHOLD, POSTBOT_AUTO_BLOCK_CONFIDENCE,
            SPAM_HARD_THRESHOLD, SPAM_CRITICAL_THRESHOLD,
            ANTIEVASION_COMPACT_WORDS,
            _MessageContext,
            _strip_combining_marks, _deleet, _apply_homoglyphs_safe,
            _normalize_text, _strip_emoji_for_domain,
            _has_hidden_chars, _merge_split_urls,
            _extract_entity_urls, _has_link_entity,
            _extract_url_from_button, _button_is_external,
            _extract_button_context, _extract_vcard_urls,
            _extract_venue_url, _extract_poll_text,
            _get_message_button_data, _get_message_button_texts,
            _get_message_analysis_text,
            _has_domain_pattern, _contains_link_enhanced,
            _contains_email, _contains_at_channel, _contains_tg_scheme,
            _has_button_link, _extract_button_link_urls,
            _extract_spam_words, _count_unique_matches, _count_text_urls,
            _compute_spam_score, _is_postbot_pattern,
            _postbot_pattern_confidence,
            analyze_message, get_spam_diagnostics,
            is_spam, is_high_confidence_spam, is_critical_spam,
            should_ignore_as_low_signal,
        )
    except ImportError:
        from .handlers_message_detectors import (
            DEBUG_DIAG, DEBUG_SPAM,
            SPAM_SCORE_THRESHOLD, POSTBOT_AUTO_BLOCK_CONFIDENCE,
            SPAM_HARD_THRESHOLD, SPAM_CRITICAL_THRESHOLD,
            ANTIEVASION_COMPACT_WORDS,
            _MessageContext,
            _strip_combining_marks, _deleet, _apply_homoglyphs_safe,
            _normalize_text, _strip_emoji_for_domain,
            _has_hidden_chars, _merge_split_urls,
            _extract_entity_urls, _has_link_entity,
            _extract_url_from_button, _button_is_external,
            _extract_button_context, _extract_vcard_urls,
            _extract_venue_url, _extract_poll_text,
            _get_message_button_data, _get_message_button_texts,
            _get_message_analysis_text,
            _has_domain_pattern, _contains_link_enhanced,
            _contains_email, _contains_at_channel, _contains_tg_scheme,
            _has_button_link, _extract_button_link_urls,
            _extract_spam_words, _count_unique_matches, _count_text_urls,
            _compute_spam_score, _is_postbot_pattern,
            _postbot_pattern_confidence,
            analyze_message, get_spam_diagnostics,
            is_spam, is_high_confidence_spam, is_critical_spam,
            should_ignore_as_low_signal,
        )


_HAS_MULTILAYER = False
analyze_message_full = None
analyze_message_full_async = None  # 🆕 v7.18.8
SpamVerdict = None
FINAL_THRESHOLD = 5
LAYER_WEIGHTS: Dict[str, float] = {}

try:
    from handlers.handlers_message_detectors import (
        analyze_message_full as _amf,
        analyze_message_full_async as _amfa,  # 🆕 v7.18.8
        SpamVerdict as _SV,
        FINAL_THRESHOLD as _FT,
        LAYER_WEIGHTS as _LW,
        TEXT_LAYER_ENABLED as _TLE,
        OCR_LAYER_ENABLED as _OLE,
        AUDIO_LAYER_ENABLED as _ALE,
        URL_LAYER_ENABLED as _ULE,
        METADATA_LAYER_ENABLED as _MLE,
        OBFUSCATION_LAYER_ENABLED as _OBLE,
        BEHAVIORAL_LAYER_ENABLED as _BLE,
    )
    analyze_message_full = _amf
    analyze_message_full_async = _amfa
    SpamVerdict = _SV
    FINAL_THRESHOLD = _FT
    LAYER_WEIGHTS = _LW
    TEXT_LAYER_ENABLED = _TLE
    OCR_LAYER_ENABLED = _OLE
    AUDIO_LAYER_ENABLED = _ALE
    URL_LAYER_ENABLED = _ULE
    METADATA_LAYER_ENABLED = _MLE
    OBFUSCATION_LAYER_ENABLED = _OBLE
    BEHAVIORAL_LAYER_ENABLED = _BLE
    _HAS_MULTILAYER = True
except ImportError:
    try:
        from handlers_message_detectors import (
            analyze_message_full as _amf,
            analyze_message_full_async as _amfa,
            SpamVerdict as _SV,
            FINAL_THRESHOLD as _FT,
            LAYER_WEIGHTS as _LW,
            TEXT_LAYER_ENABLED as _TLE,
            OCR_LAYER_ENABLED as _OLE,
            AUDIO_LAYER_ENABLED as _ALE,
            URL_LAYER_ENABLED as _ULE,
            METADATA_LAYER_ENABLED as _MLE,
            OBFUSCATION_LAYER_ENABLED as _OBLE,
            BEHAVIORAL_LAYER_ENABLED as _BLE,
        )
        analyze_message_full = _amf
        analyze_message_full_async = _amfa
        SpamVerdict = _SV
        FINAL_THRESHOLD = _FT
        LAYER_WEIGHTS = _LW
        TEXT_LAYER_ENABLED = _TLE
        OCR_LAYER_ENABLED = _OLE
        AUDIO_LAYER_ENABLED = _ALE
        URL_LAYER_ENABLED = _ULE
        METADATA_LAYER_ENABLED = _MLE
        OBFUSCATION_LAYER_ENABLED = _OBLE
        BEHAVIORAL_LAYER_ENABLED = _BLE
        _HAS_MULTILAYER = True
    except ImportError:
        try:
            from .handlers_message_detectors import (
                analyze_message_full as _amf,
                analyze_message_full_async as _amfa,
                SpamVerdict as _SV,
                FINAL_THRESHOLD as _FT,
                LAYER_WEIGHTS as _LW,
                TEXT_LAYER_ENABLED as _TLE,
                OCR_LAYER_ENABLED as _OLE,
                AUDIO_LAYER_ENABLED as _ALE,
                URL_LAYER_ENABLED as _ULE,
                METADATA_LAYER_ENABLED as _MLE,
                OBFUSCATION_LAYER_ENABLED as _OBLE,
                BEHAVIORAL_LAYER_ENABLED as _BLE,
            )
            analyze_message_full = _amf
            analyze_message_full_async = _amfa
            SpamVerdict = _SV
            FINAL_THRESHOLD = _FT
            LAYER_WEIGHTS = _LW
            TEXT_LAYER_ENABLED = _TLE
            OCR_LAYER_ENABLED = _OLE
            AUDIO_LAYER_ENABLED = _ALE
            URL_LAYER_ENABLED = _ULE
            METADATA_LAYER_ENABLED = _MLE
            OBFUSCATION_LAYER_ENABLED = _OBLE
            BEHAVIORAL_LAYER_ENABLED = _BLE
            _HAS_MULTILAYER = True
        except ImportError:
            _HAS_MULTILAYER = False
            analyze_message_full = None
            analyze_message_full_async = None
            SpamVerdict = None
            TEXT_LAYER_ENABLED = False
            OCR_LAYER_ENABLED = False
            AUDIO_LAYER_ENABLED = False
            URL_LAYER_ENABLED = False
            METADATA_LAYER_ENABLED = False
            OBFUSCATION_LAYER_ENABLED = False
            BEHAVIORAL_LAYER_ENABLED = False


# 🆕 v7.18.3: Auto-block database integration
try:
    from database_auto_block import (
        ensure_table as _ensure_autoblock_table,
        is_blocked as _is_source_blocked,
        add_source as _add_blocked_source,
        list_blocked as _list_blocked_sources,
        remove_source as _remove_blocked_source,
    )
    _HAS_AUTO_BLOCK = True
except ImportError as _e_ab:
    _HAS_AUTO_BLOCK = False
    logger.debug("database_auto_block import failed: %s", _e_ab)

    async def _ensure_autoblock_table() -> bool:
        return False

    async def _is_source_blocked(source_id) -> bool:
        return False

    async def _add_blocked_source(*args, **kwargs) -> bool:
        return False

    async def _list_blocked_sources(limit: int = 100):
        return []

    async def _remove_blocked_source(source_id: int) -> bool:
        return False


try:
    from replies import analyze_sentiment  # noqa: F401
except ImportError:
    analyze_sentiment = None


try:
    from telegram import (
        MessageOriginUser, MessageOriginHiddenUser,
        MessageOriginChat, MessageOriginChannel,
    )
    _HAS_MESSAGE_ORIGIN = True
except ImportError:
    MessageOriginUser = MessageOriginHiddenUser = None
    MessageOriginChat = MessageOriginChannel = None
    _HAS_MESSAGE_ORIGIN = False


# ═══════════════════════════════════════════════════════════════════
# Local helpers
# ═══════════════════════════════════════════════════════════════════

def _env_flag(name: str, default: bool = True) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


_TRUE_STRINGS = frozenset({
    "1", "true", "yes", "on", "enabled", "enable", "y",
    "نعم", "مفعل", "مفعّل",
})
_FALSE_STRINGS = frozenset({
    "0", "false", "no", "off", "disabled", "disable", "n",
    "لا", "غير مفعل", "غير مفعّل",
})


def _as_bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _TRUE_STRINGS:
            return True
        if v in _FALSE_STRINGS:
            return False
    return default


def _row_to_dict_local(row) -> Optional[Dict[str, Any]]:
    """
    🆕 v7.18.6 PERF-5: تحويل موحّد لأي صف من DB إلى dict.

    يدعم:
        • asyncpg.Record (يدعم [] و .get عبر __getitem__)
        • MySQL aiomysql/asyncmy Row (يدعم [])
        • sqlite3.Row (يدعم [])
        • dict أصلي
    """
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    try:
        if hasattr(row, 'keys'):
            return {k: row[k] for k in row.keys()}
    except Exception:
        pass
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════════
# Environment Flags
# ═══════════════════════════════════════════════════════════════════

_ANTIFLOOD_ENABLED = _env_flag("ANTIFLOOD_ENABLED", True)
_SLOW_MODE_AUTO = _env_flag("SLOW_MODE_AUTO", True)

_MULTILAYER_ENABLED = (
    _env_flag("MULTILAYER_ENABLED", True) and _HAS_MULTILAYER
)

_FORCE_DELETE_BUTTON_LINKS = _env_flag("FORCE_DELETE_BUTTON_LINKS", True)
_FORCE_DELETE_POSTBOT_FORWARDS = _env_flag(
    "FORCE_DELETE_POSTBOT_FORWARDS", True
)

_BAN_ADD_RATE_LIMIT = _env_flag("BAN_ADD_RATE_LIMIT", True)
_BAN_ADD_RATE_MAX = 10
_BAN_ADD_RATE_WINDOW = 60.0
_BOT_DATA_SLOW_MODE_PRUNE_THRESHOLD = 10000
_BOT_DATA_SLOW_MODE_PRUNE_COOLDOWN = 300.0

# 🆕 v7.18.8: قياس زمن التحليل (للتشخيص فقط)
_ANALYZE_SLOW_THRESHOLD_SEC = 3.0


# ═══════════════════════════════════════════════════════════════════
# 🆕 v7.18.3 / v7.18.7: Post Bot Detection
# ═══════════════════════════════════════════════════════════════════

_POSTBOT_CHANNEL_NAMES = frozenset({
    # القنوات المعروفة
    "news",
    "news post bot",
    "news (post bot)",
    # English
    "post bot", "postbot", "post-bot", "post_bot",
    "news postbot", "news post-bot", "news post_bot",
    "post bot news", "postbotnews", "postbot news",
    "post news", "news bot", "newsbot",
    # Arabic
    "بوت النشر", "بوت نشر", "بوست بوت", "بوستبوت",
    "نشر بوت", "أخبار بوت", "بوت الأخبار",
    "قناة النشر", "قناة نشر",
})

# 🆕 v7.18.7: ID خام واحد فقط — لا حاجة لثلاث صيغ
_POSTBOT_RAW_IDS: set = {
    3826578265,  # raw ID (بدون بادئة -100 أو إشارة)
}

# 🆕 v7.18.7: alias deprecated للتوافق مع الإصدارات السابقة
# ⚠️ deprecated — استخدم _POSTBOT_RAW_IDS + _normalize_tg_id
_POSTBOT_CHANNEL_IDS: frozenset = frozenset({
    3826578265, -3826578265, -1003826578265,
})

# 🔧 v7.18.4: regex مبسّط (إزالة تكرار "postbot")
_POSTBOT_NAME_REGEX = re.compile(
    r"(?i)(?:"
    r"post[\s\-_]*bot"
    r"|news[\s\-_]*post"
    r"|post[\s\-_]*news"
    r"|newsbot"
    r"|بوست[\s\-_]*بوت"
    r"|بوت[\s\-_]*(?:نشر|بوست|أخبار)"
    r"|نشر[\s\-_]*بوت"
    r"|أخبار[\s\-_]*بوت"
    r")"
)


def _normalize_tg_id(cid) -> Optional[int]:
    """
    🆕 v7.18.7 FIX-3: يحوّل أي صيغة من Telegram ID إلى ID خام موجب.

    Examples:
        3826578265       → 3826578265
        -3826578265      → 3826578265
        -1003826578265   → 3826578265
        None             → None
        "abc"            → None
    """
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return None
    cid = abs(cid)
    # إزالة بادئة -100 لـ supergroups/channels
    if cid >= 10**12:
        cid = cid - 10**12
    return cid


def _is_postbot_channel_name(name: str) -> bool:
    """v7.18.3: كشف مرن — user + channel + Arabic."""
    if not name:
        return False
    try:
        name_lower = str(name).lower().strip()
        for candidate in _POSTBOT_CHANNEL_NAMES:
            if candidate in name_lower:
                return True
        if _POSTBOT_NAME_REGEX.search(name_lower):
            return True
        has_post = "post" in name_lower or "بوست" in name_lower
        has_bot = "bot" in name_lower or "بوت" in name_lower
        if has_post and has_bot:
            return True
        if "news" in name_lower and ("post" in name_lower or "bot" in name_lower):
            return True
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

LOG_RATE_LIMIT_PER_MIN = 30
LOG_RATE_WINDOW_SEC = 60.0
LOG_RETRY_ATTEMPTS = 3
LOG_RETRY_BASE_DELAY = 0.5

DEV_LOG_CACHE_TTL = 300.0
CACHE_CLEANUP_INTERVAL = 3600
MAX_GROUP_LIMITERS_CACHE = 1000
MAX_COMPILED_BANNED_PATTERNS = 5000

TRANSLATION_REPLY_DELETE_DELAY = 30
TRANSLATION_MIN_TEXT_LENGTH = 2
PENALTY_MESSAGE_DELETE_DELAY = 10

_FORWARD_NOTIFY_COOLDOWN_SECONDS = 300.0
_FORWARD_NOTIFY_MAX_KEYS = 5000
_GROUP_LOG_PREVIEW_LENGTH = 150
_COLUMNS_RETRY_COOLDOWN_SEC = 300.0
_DELETE_FAILURE_NOTIFY_THRESHOLD = 3
_DELETE_FAILURE_NOTIFY_WINDOW = 60.0

_FLOOD_TRACKER_MAX_KEYS = 5000
_FLOOD_TRACKER_STALE_SEC = 300.0
_FLOOD_MAX_MESSAGES_LIMIT = 100
_FLOOD_MAX_WINDOW_SEC = 3600
_FLOOD_MIN_WINDOW_SEC = 1
_FLOOD_MIN_DURATION_SEC = 60
_FLOOD_DEFAULT_MESSAGES = 5
_FLOOD_DEFAULT_WINDOW = 10
_FLOOD_DEFAULT_PENALTY = "mute"
_FLOOD_DEFAULT_DURATION = 3600

_BAN_WORD_MIN_LEN = 2
_BAN_WORD_MAX_LEN = 100

# 🆕 v7.18.7 FIX-5: سقف cache الـ signature
_PRIVATE_SIG_CACHE_MAX = 128

FEATURE_LOG_DELETIONS = _env_flag("LOG_DELETIONS", True)
FEATURE_LOG_PENALTIES = _env_flag("LOG_PENALTIES", True)
FEATURE_LOG_GIFTS = _env_flag("LOG_GIFTS", True)
FEATURE_LOG_ADMIN_CHANGES = _env_flag("LOG_ADMIN_CHANGES", True)

_DEBUG_DIAG = DEBUG_DIAG
_DEBUG_SPAM = DEBUG_SPAM


# ═══════════════════════════════════════════════════════════════════
# 🆕 v7.18.6 PERF-1/2/7: Caches محلية لتقليل round-trips
# ═══════════════════════════════════════════════════════════════════

# 🟠 PERF-1: cache لـ group log channel
_GROUP_LOG_CHANNEL_CACHE_TTL = 60.0
_GROUP_LOG_CHANNEL_CACHE_MAX = 2000
_group_log_channel_cache: Dict[int, Tuple[Any, float]] = {}


def _invalidate_group_log_cache(chat_id: Optional[int] = None) -> None:
    """🆕 v7.18.6 PERF-6: إبطال cache قناة السجل."""
    try:
        if chat_id is None:
            _group_log_channel_cache.clear()
        else:
            _group_log_channel_cache.pop(int(chat_id), None)
    except Exception:
        pass


async def _get_group_log_channel_cached(chat_id: int):
    """🟠 PERF-1: قراءة cache قناة السجل مع fallback لـ DB."""
    now = time.monotonic()
    try:
        entry = _group_log_channel_cache.get(int(chat_id))
    except (TypeError, ValueError):
        entry = None

    if entry is not None:
        cached_value, cached_at = entry
        if now - cached_at < _GROUP_LOG_CHANNEL_CACHE_TTL:
            return cached_value

    getter = getattr(DB, 'get_group_log_channel', None)
    if not callable(getter):
        return None

    try:
        value = await getter(chat_id)
    except Exception as e:
        logger.debug(
            "_get_group_log_channel_cached(%s): %s", chat_id, e,
        )
        if entry is not None:
            return entry[0]
        return None

    if len(_group_log_channel_cache) >= _GROUP_LOG_CHANNEL_CACHE_MAX:
        try:
            oldest = sorted(
                _group_log_channel_cache.items(),
                key=lambda kv: kv[1][1],
            )[: max(1, _GROUP_LOG_CHANNEL_CACHE_MAX // 5)]
            for k, _ in oldest:
                _group_log_channel_cache.pop(k, None)
        except Exception:
            pass

    _group_log_channel_cache[int(chat_id)] = (value, now)
    return value


# 🟠 PERF-2: cache محلي قصير لـ security settings (5s)
_SEC_SETTINGS_LOCAL_TTL = 5.0
_SEC_SETTINGS_LOCAL_MAX = 3000
_sec_settings_local_cache: Dict[int, Tuple[Dict[str, Any], float]] = {}


def _invalidate_sec_settings_local(chat_id: Optional[int] = None) -> None:
    """🟠 PERF-2: إبطال cache محلي."""
    try:
        if chat_id is None:
            _sec_settings_local_cache.clear()
        else:
            _sec_settings_local_cache.pop(int(chat_id), None)
    except Exception:
        pass


# 🟡 PERF-7: cache لنتيجة _check_admin_in_chat (30s)
_ADMIN_CHECK_CACHE_TTL = 30.0
_ADMIN_CHECK_CACHE_MAX = 3000
_admin_check_cache: Dict[Tuple[int, int], Tuple[bool, float]] = {}


def _invalidate_admin_check_cache(
    chat_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> None:
    """🟡 PERF-7: إبطال cache _check_admin_in_chat."""
    try:
        if chat_id is None:
            _admin_check_cache.clear()
            return
        if user_id is None:
            to_del = [
                k for k in _admin_check_cache
                if k[0] == int(chat_id)
            ]
            for k in to_del:
                _admin_check_cache.pop(k, None)
        else:
            _admin_check_cache.pop((int(chat_id), int(user_id)), None)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# 🔧 v7.18.4: private-handler signature cache
# ═══════════════════════════════════════════════════════════════════

_private_handler_signature_cache: Dict[str, bool] = {}


# ═══════════════════════════════════════════════════════════════════
# Flood Tracker
# ═══════════════════════════════════════════════════════════════════

_flood_tracker: DefaultDict[Tuple[int, int], deque] = defaultdict(
    lambda: deque(maxlen=_FLOOD_MAX_MESSAGES_LIMIT + 5)
)
_flood_lock = asyncio.Lock()
_flood_last_cleanup = 0.0


async def _check_flood(
    chat_id: int, user_id: int, max_messages: int, window_sec: float,
) -> bool:
    try:
        max_messages = max(1, min(int(max_messages), _FLOOD_MAX_MESSAGES_LIMIT))
    except (TypeError, ValueError):
        max_messages = _FLOOD_DEFAULT_MESSAGES
    try:
        window_sec = max(
            float(_FLOOD_MIN_WINDOW_SEC),
            min(float(window_sec), float(_FLOOD_MAX_WINDOW_SEC)),
        )
    except (TypeError, ValueError):
        window_sec = float(_FLOOD_DEFAULT_WINDOW)
    now = time.monotonic()
    key = (chat_id, user_id)
    async with _flood_lock:
        tracker = _flood_tracker[key]
        while tracker and now - tracker[0] > window_sec:
            tracker.popleft()
        tracker.append(now)
        exceeded = len(tracker) > max_messages
        if exceeded:
            tracker.clear()
            return True
        return False


async def _cleanup_flood_tracker(force: bool = False) -> int:
    global _flood_last_cleanup
    now = time.monotonic()
    if not force and now - _flood_last_cleanup < 60.0:
        return 0
    removed = 0
    overflow_snapshot: List[Tuple[Tuple[int, int], deque]] = []
    async with _flood_lock:
        _flood_last_cleanup = now
        stale_keys = [
            k for k, dq in _flood_tracker.items()
            if not dq or now - dq[-1] > _FLOOD_TRACKER_STALE_SEC
        ]
        for k in stale_keys:
            _flood_tracker.pop(k, None)
            removed += 1
        if len(_flood_tracker) > _FLOOD_TRACKER_MAX_KEYS:
            overflow_snapshot = list(_flood_tracker.items())
    if overflow_snapshot:
        oldest = sorted(
            overflow_snapshot, key=lambda kv: kv[1][-1] if kv[1] else 0.0,
        )
        async with _flood_lock:
            current_size = len(_flood_tracker)
            if current_size > _FLOOD_TRACKER_MAX_KEYS:
                target_size = _FLOOD_TRACKER_MAX_KEYS * 3 // 4
                to_del = current_size - target_size
                for k, _ in oldest[:max(1, to_del)]:
                    if k in _flood_tracker:
                        _flood_tracker.pop(k, None)
                        removed += 1
    return removed


def _flood_tracker_stats() -> Dict[str, int]:
    try:
        return {
            "keys": len(_flood_tracker),
            "max_keys": _FLOOD_TRACKER_MAX_KEYS,
            "stale_sec": int(_FLOOD_TRACKER_STALE_SEC),
        }
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════
# Shutdown State
# ═══════════════════════════════════════════════════════════════════

_shutdown_started: bool = False


def _mark_shutdown_started():
    global _shutdown_started
    _shutdown_started = True


def _is_shutting_down() -> bool:
    return _shutdown_started


def _reset_shutdown_for_tests():
    global _shutdown_started
    _shutdown_started = False
    try:
        _private_handler_signature_cache.clear()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# Database Migration
# ═══════════════════════════════════════════════════════════════════

_columns_initialized = False
_columns_init_lock = asyncio.Lock()
_columns_last_attempt_ts = 0.0


async def _lazy_init_columns():
    global _columns_initialized, _columns_last_attempt_ts

    if _columns_initialized:
        return

    async with _columns_init_lock:
        if _columns_initialized:
            return

        now = time.monotonic()
        if (
            _columns_last_attempt_ts > 0
            and now - _columns_last_attempt_ts < _COLUMNS_RETRY_COOLDOWN_SEC
        ):
            return
        _columns_last_attempt_ts = now

        db_type = getattr(DB, "DB_TYPE", "sqlite")
        logger.info("🔧 v7.18.8: Auto-migration (DB_TYPE=%s)", db_type)

        cols = [
            ("delete_protected_any", "INTEGER DEFAULT 0", "TINYINT(1) DEFAULT 0"),
            ("delete_postbot_pattern", "INTEGER DEFAULT 0", "TINYINT(1) DEFAULT 0"),
            ("delete_spam_score", "INTEGER DEFAULT 1", "TINYINT(1) DEFAULT 1"),
            ("delete_at_channel", "INTEGER DEFAULT 0", "TINYINT(1) DEFAULT 0"),
            ("delete_tg_scheme", "INTEGER DEFAULT 1", "TINYINT(1) DEFAULT 1"),
            ("delete_button_links", "INTEGER DEFAULT 1", "TINYINT(1) DEFAULT 1"),
            ("delete_emails", "INTEGER DEFAULT 0", "TINYINT(1) DEFAULT 0"),
            ("delete_polls", "INTEGER DEFAULT 0", "TINYINT(1) DEFAULT 0"),
        ]

        migration_ok = True
        unexpected_failures: List[str] = []

        # 🆕 v7.18.7 FIX-2: PG — bulk أولاً، fallback فردي عند الفشل
        if db_type == "postgres":
            try:
                additions = ", ".join(
                    f"ADD COLUMN IF NOT EXISTS {col} {sqlite_def}"
                    for col, sqlite_def, _ in cols
                )
                await DB.execute(
                    f"ALTER TABLE group_security {additions}"
                )
                logger.info(
                    "✅ PERF-9: عمود %d أُضيفوا في ALTER واحد (PG)",
                    len(cols),
                )
            except Exception as bulk_e:
                logger.warning(
                    "⚠️ PG bulk ALTER فشل — fallback فردي: %s", bulk_e,
                )
                for col_name, sqlite_def, _ in cols:
                    try:
                        await DB.execute(
                            f"ALTER TABLE group_security "
                            f"ADD COLUMN IF NOT EXISTS "
                            f"{col_name} {sqlite_def}"
                        )
                    except Exception as col_e:
                        m = str(col_e).lower()
                        if (
                            "already exists" not in m
                            and "duplicate" not in m
                        ):
                            migration_ok = False
                            unexpected_failures.append(
                                f"{col_name}: {col_e}"
                            )
        else:
            # MySQL + SQLite — ALTER منفصل لكل عمود
            for col_name, sqlite_def, mysql_def in cols:
                try:
                    if db_type == "mysql":
                        try:
                            await DB.execute(
                                "ALTER TABLE group_security "
                                f"ADD COLUMN {col_name} {mysql_def}"
                            )
                        except Exception as e:
                            m = str(e).lower()
                            if (
                                "duplicate" not in m
                                and "already exists" not in m
                            ):
                                migration_ok = False
                                unexpected_failures.append(
                                    f"{col_name}: {e}"
                                )
                    else:
                        try:
                            await DB.execute(
                                "ALTER TABLE group_security "
                                f"ADD COLUMN {col_name} {sqlite_def}"
                            )
                        except Exception as e:
                            m = str(e).lower()
                            if (
                                "duplicate" not in m
                                and "already exists" not in m
                            ):
                                migration_ok = False
                                unexpected_failures.append(
                                    f"{col_name}: {e}"
                                )
                except Exception as e:
                    migration_ok = False
                    unexpected_failures.append(f"{col_name}: {e}")

        # 🆕 v7.18.3: إنشاء جدول auto_blocked_sources
        if _HAS_AUTO_BLOCK:
            try:
                await _ensure_autoblock_table()
            except Exception as e:
                logger.debug("auto_block table init: %s", e)

        try:
            await internal_cache.clear()
            logger.info("✅ internal_cache cleared")
        except Exception:
            pass

        # 🆕 v7.18.6: إبطال caches المحلية عند الـ migration
        _invalidate_group_log_cache()
        _invalidate_sec_settings_local()
        _invalidate_admin_check_cache()

        if migration_ok:
            _columns_initialized = True
        elif unexpected_failures:
            # 🆕 v7.18.7 FIX-9: log error واضح عند فشل الـ migration
            logger.error(
                "❌ migration_ok=False — فشل %d عمود: %s",
                len(unexpected_failures),
                "; ".join(unexpected_failures[:5]),
            )
            logger.error(
                "⚠️ المخطط غير متزامن — قد تفشل عمليات القراءة/الكتابة "
                "على group_security. راجع سجلات DB."
            )


# ═══════════════════════════════════════════════════════════════════
# Developer Log Cache
# ═══════════════════════════════════════════════════════════════════

_dev_log_cache = None
_dev_log_cache_ts = 0.0
_dev_log_cache_lock = asyncio.Lock()


async def _get_dev_log_channel_cached():
    global _dev_log_cache, _dev_log_cache_ts
    now = time.monotonic()
    if _dev_log_cache is not None and now - _dev_log_cache_ts < DEV_LOG_CACHE_TTL:
        return _dev_log_cache
    async with _dev_log_cache_lock:
        now = time.monotonic()
        if _dev_log_cache is not None and now - _dev_log_cache_ts < DEV_LOG_CACHE_TTL:
            return _dev_log_cache
        try:
            ch = await DB.get_log_channel()
            _dev_log_cache = ch
            _dev_log_cache_ts = now
            return ch
        except Exception as e:
            logger.warning("get_dev_log_channel_cached: %s", e)
            return _dev_log_cache


def _invalidate_dev_log_cache():
    global _dev_log_cache, _dev_log_cache_ts
    _dev_log_cache = None
    _dev_log_cache_ts = 0.0


# ═══════════════════════════════════════════════════════════════════
# Log Rate Limit
# ═══════════════════════════════════════════════════════════════════

_log_rate_tracker = defaultdict(lambda: deque(maxlen=LOG_RATE_LIMIT_PER_MIN))
_log_rate_lock = asyncio.Lock()
_log_rate_warn_last: Dict[Any, float] = {}
_LOG_RATE_WARN_COOLDOWN = 300.0

_dev_log_rate_tracker: deque = deque(maxlen=LOG_RATE_LIMIT_PER_MIN)
_dev_log_rate_lock = asyncio.Lock()


async def _can_send_log(chat_id) -> bool:
    async with _log_rate_lock:
        now = time.monotonic()
        tracker = _log_rate_tracker[chat_id]
        if (
            len(tracker) >= LOG_RATE_LIMIT_PER_MIN
            and now - tracker[0] < LOG_RATE_WINDOW_SEC
        ):
            last = _log_rate_warn_last.get(chat_id, 0.0)
            if now - last >= _LOG_RATE_WARN_COOLDOWN:
                _log_rate_warn_last[chat_id] = now
            return False
        tracker.append(now)
        return True


async def _can_send_dev_log() -> bool:
    async with _dev_log_rate_lock:
        now = time.monotonic()
        if (
            len(_dev_log_rate_tracker) >= LOG_RATE_LIMIT_PER_MIN
            and now - _dev_log_rate_tracker[0] < LOG_RATE_WINDOW_SEC
        ):
            return False
        _dev_log_rate_tracker.append(now)
        return True


async def _cleanup_log_rate_tracker():
    async with _log_rate_lock:
        now = time.monotonic()
        cutoff = LOG_RATE_WINDOW_SEC * 5
        stale = [
            cid for cid, dq in _log_rate_tracker.items()
            if (not dq) or (now - dq[-1] > cutoff)
        ]
        for cid in stale:
            _log_rate_tracker.pop(cid, None)
        stale_warn = [
            cid for cid, ts in _log_rate_warn_last.items()
            if now - ts > _LOG_RATE_WARN_COOLDOWN * 2
        ]
        for cid in stale_warn:
            _log_rate_warn_last.pop(cid, None)
        return len(stale)


async def _notify_dev_log(context, text):
    try:
        if not await _can_send_dev_log():
            return
    except Exception:
        pass
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
        elif ch_str.startswith(('https://', 'http://')):
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
            chat_id=target, text=text, parse_mode='HTML',
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning("🔔 _notify_dev_log FAILED: %s", e)


# ═══════════════════════════════════════════════════════════════════
# Dispatch Log
# ═══════════════════════════════════════════════════════════════════

_running_log_tasks: set = set()
_log_dispatch_failures: int = 0


async def _dispatch_log(
    factory: Callable[[], Awaitable[Any]],
    label: str,
    *,
    retries: int = LOG_RETRY_ATTEMPTS,
):
    if _is_shutting_down():
        if inspect.iscoroutine(factory):
            try:
                factory.close()
            except Exception:
                pass
        return
    if not callable(factory):
        if inspect.iscoroutine(factory):
            try:
                factory.close()
            except Exception:
                pass
        return

    async def _runner():
        global _log_dispatch_failures
        attempt = 0
        last_exc = None
        while attempt <= max(0, retries):
            try:
                await factory()
                return
            except asyncio.CancelledError:
                return
            except Exception as e:
                last_exc = e
                if attempt < retries:
                    delay = LOG_RETRY_BASE_DELAY * (attempt + 1)
                    try:
                        await asyncio.sleep(delay)
                    except asyncio.CancelledError:
                        return
                    attempt += 1
                    continue
                break
        _log_dispatch_failures += 1
        logger.error(
            "❌ [%s] failed بعد %d محاولات: %s",
            label, retries + 1, last_exc,
        )

    task = asyncio.create_task(_runner())
    _running_log_tasks.add(task)

    def _cleanup(t):
        _running_log_tasks.discard(t)

    task.add_done_callback(_cleanup)


async def shutdown_log_dispatcher(timeout: float = 5.0):
    _mark_shutdown_started()
    if not _running_log_tasks:
        return
    tasks = list(_running_log_tasks)
    for t in tasks:
        if not t.done():
            t.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=timeout,
        )
    except Exception:
        pass
    _running_log_tasks.clear()


_running_bg_tasks: set = set()


def _spawn_tracked_task(coro, *, label: str = "bg-task"):
    if _is_shutting_down():
        try:
            if inspect.iscoroutine(coro):
                coro.close()
        except Exception:
            pass
        return None
    try:
        task = asyncio.create_task(coro)
    except Exception:
        return None
    _running_bg_tasks.add(task)

    def _cleanup(t):
        _running_bg_tasks.discard(t)

    task.add_done_callback(_cleanup)
    return task


async def shutdown_bg_tasks(timeout: float = 3.0):
    _mark_shutdown_started()
    if not _running_bg_tasks:
        return
    tasks = list(_running_bg_tasks)
    for t in tasks:
        if not t.done():
            t.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=timeout,
        )
    except Exception:
        pass
    _running_bg_tasks.clear()


_running_delete_tasks: set = set()


async def _delete_after_delay(bot, chat_id, message_id, delay=10, context=None):
    try:
        if delay > 0:
            await asyncio.sleep(delay)
        await _safe_delete_message(
            bot, chat_id, message_id, context=context, notify_owner=False,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


def _spawn_delete_after_delay(bot, chat_id, message_id, delay=10, context=None):
    if _is_shutting_down():
        return
    try:
        d = float(delay)
    except (TypeError, ValueError):
        d = 0.0
    if d < 0:
        d = 0.0
    task = asyncio.create_task(
        _delete_after_delay(bot, chat_id, message_id, d, context=context)
    )
    _running_delete_tasks.add(task)

    def _cleanup(t):
        _running_delete_tasks.discard(t)

    task.add_done_callback(_cleanup)


async def shutdown_delete_tasks(timeout: float = 3.0):
    _mark_shutdown_started()
    if not _running_delete_tasks:
        return
    tasks = list(_running_delete_tasks)
    for t in tasks:
        if not t.done():
            t.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), timeout=timeout,
        )
    except Exception:
        pass
    _running_delete_tasks.clear()


def register_shutdown_handlers(application):
    if getattr(application, '_msh_shutdown_registered', False):
        return
    try:
        original_post_shutdown = getattr(application, 'post_shutdown', None)

        async def _post_shutdown(app):
            _mark_shutdown_started()
            try:
                await shutdown_log_dispatcher(timeout=5.0)
            except Exception:
                pass
            try:
                await shutdown_bg_tasks(timeout=3.0)
            except Exception:
                pass
            try:
                await shutdown_delete_tasks(timeout=3.0)
            except Exception:
                pass
            if callable(original_post_shutdown):
                try:
                    await original_post_shutdown(app)
                except Exception:
                    pass

        application.post_shutdown = _post_shutdown
        application._msh_shutdown_registered = True
    except Exception as e:
        logger.warning("register_shutdown_handlers: %s", e)


# ═══════════════════════════════════════════════════════════════════
# Cache Helpers
# ═══════════════════════════════════════════════════════════════════

async def _safe_invalidate(*keys):
    for key in keys:
        if not key:
            continue
        try:
            await internal_cache.invalidate(key)
        except Exception:
            pass


async def _invalidate_banned_words_cache(chat_id=None) -> bool:
    try:
        from utils import invalidate_banned_words_cache_async as _inv
        result = _inv(chat_id)
        if asyncio.iscoroutine(result):
            await result
        return True
    except Exception:
        pass
    try:
        from utils import invalidate_banned_words_cache as _inv2
        result = _inv2(chat_id) if chat_id is not None else _inv2()
        if asyncio.iscoroutine(result):
            await result
        return True
    except Exception:
        pass
    try:
        from cache import banned_words_cache
        if hasattr(banned_words_cache, 'invalidate'):
            result = banned_words_cache.invalidate(chat_id)
            if asyncio.iscoroutine(result):
                await result
            return True
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════════════════
# 🆕 v7.18.8: Multi-layer analysis wrapper (async-native)
# ═══════════════════════════════════════════════════════════════════

async def _run_multilayer_analysis(
    message: Any,
    bot: Any,
    *,
    label: str = "multilayer",
) -> Optional[Any]:
    """
    🆕 v7.18.8 FIX-ASYNC-1/2/3/4:
    Wrapper موحّد لاستدعاء محرك كشف الطبقات المتعددة بشكل async.

    الأولويات:
        1) analyze_message_full_async (v4.0.2) — async native، لا حجب
        2) analyze_message_full في asyncio.to_thread — fallback آمن
        3) None — إذا لم يتوفر أي منهما

    يُعيد SpamVerdict أو None عند الفشل.
    """
    if not _MULTILAYER_ENABLED:
        return None

    t0 = time.monotonic()
    verdict = None
    mode = None

    # المسار 1: async native (v4.0.2)
    if analyze_message_full_async is not None:
        try:
            verdict = await analyze_message_full_async(message, bot=bot)
            mode = "async-native"
        except TypeError:
            # احتمال: النسخة القديمة لا تدعم bot kwarg
            try:
                verdict = await analyze_message_full_async(message)
                mode = "async-native-no-bot"
            except Exception as e:
                logger.debug(
                    "[%s] analyze_message_full_async(no-bot) failed: %s",
                    label, e,
                )
                verdict = None
        except Exception as e:
            logger.debug(
                "[%s] analyze_message_full_async failed: %s", label, e,
            )
            verdict = None

    # المسار 2: sync في thread pool (آمن — لا يحجب event loop)
    if verdict is None and analyze_message_full is not None:
        try:
            verdict = await asyncio.to_thread(
                analyze_message_full, message, bot,
            )
            mode = "sync-thread"
        except TypeError:
            try:
                verdict = await asyncio.to_thread(
                    analyze_message_full, message,
                )
                mode = "sync-thread-no-bot"
            except Exception as e:
                logger.debug(
                    "[%s] analyze_message_full(thread, no-bot) failed: %s",
                    label, e,
                )
                verdict = None
        except Exception as e:
            logger.debug(
                "[%s] analyze_message_full(thread) failed: %s", label, e,
            )
            verdict = None

    # قياس الزمن
    elapsed = time.monotonic() - t0
    if verdict is not None and elapsed >= _ANALYZE_SLOW_THRESHOLD_SEC:
        logger.warning(
            "⏱️ SLOW-ANALYSIS | %s | mode=%s | %.2fs | "
            "layers=%s | total=%.1f",
            label, mode, elapsed,
            getattr(verdict, "layer_scores", {}),
            float(getattr(verdict, "total_score", 0.0)),
        )
    elif _DEBUG_DIAG and verdict is not None:
        logger.debug(
            "⏱️ ANALYSIS | %s | mode=%s | %.3fs",
            label, mode, elapsed,
        )

    return verdict


# ═══════════════════════════════════════════════════════════════════
# Labels
# ═══════════════════════════════════════════════════════════════════

_VIOLATION_LABELS_AR = {
    'forwarded': '↩️ رسالة مُعاد توجيهها',
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
    'postbot_forward': '📰 Post Bot (محوّل)',
    'spam_score': '🚫 رسالة Spam',
    'at_channel': '📢 منشن قناة',
    'tg_scheme': '🔗 رابط Telegram',
    'button_link': '🔘 زر برابط',
    'vcard_url': '📇 بطاقة اتصال',
    'venue_url': '📍 موقع',
    'email': '📧 بريد إلكتروني',
    'poll_link': '📊 رابط في استفتاء',
    'antiflood': '🌊 فيضان رسائل',
    'flood': '🌊 فيضان رسائل',
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
    'ban': '🚫 حظر', 'mute': '🔇 كتم', 'kick': '👢 طرد',
    'restrict': '🔒 تقييد', 'warn': '⚠️ تحذير', 'unban': '✅ فك حظر',
}

_DEFAULT_VIOLATION_MESSAGES = {
    'link': '🚫 يُمنع إرسال الروابط في هذه المجموعة',
    'mention': '🚫 يُمنع المنشن في هذه المجموعة',
    'banned_word': '🚫 تحتوي رسالتك على كلمة محظورة',
    'max_len': '📏 رسالتك تتجاوز الحد الأقصى للطول',
    'forwarded': '↩️ يُمنع إعادة توجيه الرسائل هنا',
    'video': '🎬 يُمنع إرسال مقاطع الفيديو هنا',
    'audio': '🎵 يُمنع إرسال الملفات الصوتية هنا',
    'voice': '🎤 يُمنع إرسال الرسائل الصوتية هنا',
    'animation': '🎞️ يُمنع إرسال الأنيميشن هنا',
    'document': '📄 يُمنع إرسال الملفات هنا',
    'sticker': '🖼️ يُمنع إرسال الملصقات هنا',
    'photo': '📷 يُمنع إرسال الصور هنا',
    'video_note': '🎥 يُمنع إرسال فيديو نوت هنا',
    'postbot_pattern': '🤖 رُصدت رسالتك كنمط Post Bot مزعج',
    'postbot_forward': '📰 يُمنع نشر رسائل Post Bot',
    'spam_score': '🚫 رُصدت رسالتك كرسالة دعائية/Spam',
    'service': '🗑️ رسائل الخدمة محذوفة تلقائياً',
    'at_channel': '📢 يُمنع منشن القنوات هنا',
    'tg_scheme': '🔗 يُمنع إرسال روابط Telegram هنا',
    'button_link': '🔘 يُمنع إرسال أزرار بروابط',
    'vcard_url': '📇 يُمنع إرسال بطاقات اتصال تحوي روابط',
    'venue_url': '📍 يُمنع إرسال المواقع الجغرافية',
    'email': '📧 يُمنع إرسال البريد الإلكتروني هنا',
    'poll_link': '📊 يُمنع إرسال استفتاءات بروابط',
    'antiflood': '🌊 يُمنع إرسال رسائل بسرعة (فيضان)',
    'flood': '🌊 يُمنع إرسال رسائل بسرعة (فيضان)',
}


def _format_duration(seconds):
    if not seconds or seconds <= 0:
        return "دائم"
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "—"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days:
        parts.append(f"{days} يوم")
    if hours:
        parts.append(f"{hours} ساعة")
    if minutes:
        parts.append(f"{minutes} دقيقة")
    if secs and not parts:
        parts.append(f"{secs} ثانية")
    return " و ".join(parts) if parts else f"{seconds} ثانية"


# ═══════════════════════════════════════════════════════════════════
# Group Log
# 🟠 PERF-1: cache محلي بـ 60s TTL
# ═══════════════════════════════════════════════════════════════════

async def notify_group_log(context, chat_id, text, disable_preview=True):
    """
    🟠 PERF-1 (v7.18.6): استخدام cache محلي بدل DB query لكل رسالة.

    قبل v7.18.6:
        channel_id = await DB.get_group_log_channel(chat_id)  ← DB query
    بعد v7.18.6:
        channel_id = await _get_group_log_channel_cached(chat_id)  ← memory
        (DB query فقط كل 60s لكل chat_id)

    ⚠️ يجب استدعاء _invalidate_group_log_cache(chat_id) عند تغيير
        قناة السجل من handlers_callback.
    """
    try:
        channel_id = await _get_group_log_channel_cached(chat_id)
        if not channel_id:
            return False
        if isinstance(channel_id, str) and channel_id.lstrip('-').isdigit():
            channel_id = int(channel_id)
        await context.bot.send_message(
            chat_id=channel_id, text=text, parse_mode='HTML',
            disable_web_page_preview=disable_preview,
        )
        return True
    except BadRequest as e:
        err = str(e).lower()
        if "chat not found" in err:
            logger.error("❌ group_log: قناة غير موجودة | %s", chat_id)
            _invalidate_group_log_cache(chat_id)
        elif "not enough rights" in err or "bot is not a member" in err:
            logger.error("❌ group_log: البوت ليس عضواً | %s", chat_id)
            _invalidate_group_log_cache(chat_id)
        return False
    except Exception as e:
        logger.error("❌ group_log FAILED: %s", e)
        return False


def _build_delete_log_text(
    chat_id, user_id, user_first_name, user_username,
    violation_type, forward_info=None, message_preview=None,
    is_anonymous=False,
):
    label = _VIOLATION_LABELS_AR.get(violation_type, violation_type)
    if is_anonymous:
        user_display_lnk = "👻 <b>مشرف مجهول</b>"
    else:
        user_display = escape(user_first_name or 'User')
        if user_username:
            user_display_lnk = (
                f"<a href='tg://user?id={user_id}'>"
                f"{user_display}</a> (@{escape(user_username)})"
            )
        else:
            user_display_lnk = (
                f"<a href='tg://user?id={user_id}'>{user_display}</a>"
            )
    lines = [
        "🗑️ <b>حذف رسالة</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📌 النوع: {label}",
        f"👤 المستخدم: {user_display_lnk}",
    ]
    if is_anonymous:
        lines.append(f"🆔 مصدر الإرسال: <code>{user_id}</code>")
        lines.append(f"🆔 المجموعة: <code>{chat_id}</code>")
    else:
        lines.append(f"🆔 المعرّف: <code>{user_id}</code>")
    if message_preview:
        preview = message_preview.strip().replace("\n", " ")
        if len(preview) > _GROUP_LOG_PREVIEW_LENGTH:
            preview = preview[:_GROUP_LOG_PREVIEW_LENGTH] + "…"
        lines.append(f"💬 النص: <i>{escape(preview)}</i>")
    if forward_info:
        ftype = forward_info.get('type') or '؟'
        ftype_label = _FORWARD_TYPE_LABELS_AR.get(ftype, ftype)
        lines.append("")
        lines.append("📤 <b>المصدر:</b>")
        lines.append(f"   • النوع: {ftype_label}")
        fname = forward_info.get('name')
        if fname:
            fname_str = str(fname)
            if len(fname_str) > 60:
                fname_str = fname_str[:60] + "…"
            lines.append(f"   • الاسم: {escape(fname_str)}")
        if forward_info.get('id'):
            lines.append(f"   • المعرّف: <code>{forward_info['id']}</code>")
    try:
        now_str = TimeUtils.mecca_now().strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    lines.append("")
    lines.append(f"🕐 {now_str}")
    return "\n".join(lines)


def _build_penalty_log_text(
    chat_id, target_user_id, target_first_name, target_username,
    penalty_type, duration_seconds, source="auto",
    violation_type=None, moderator_id=None, moderator_name=None,
):
    ptype_label = _PENALTY_LABELS_AR.get(penalty_type, penalty_type)
    target_display = escape(target_first_name or 'User')
    if target_username:
        target_lnk = (
            f"<a href='tg://user?id={target_user_id}'>"
            f"{target_display}</a> (@{escape(target_username)})"
        )
    else:
        target_lnk = (
            f"<a href='tg://user?id={target_user_id}'>{target_display}</a>"
        )
    source_label = "🤖 تلقائي" if source == "auto" else "👮 يدوي"
    lines = [
        ptype_label,
        "━━━━━━━━━━━━━━━━━━━━",
        f"🎯 العقوبة: <b>{ptype_label}</b>",
        f"⏱️ المدة: {_format_duration(duration_seconds)}",
        f"📊 المصدر: {source_label}",
        "",
        f"👤 المستهدف: {target_lnk}",
        f"🆔 المعرّف: <code>{target_user_id}</code>",
    ]
    if source == "auto" and violation_type:
        vlabel = _VIOLATION_LABELS_AR.get(violation_type, violation_type)
        lines.append(f"⚠️ المخالفة: {vlabel}")
    if source == "manual" and moderator_id:
        mod_display = escape(moderator_name or "Admin")
        lines.append("")
        lines.append(
            f"👮 المشرف: <a href='tg://user?id={moderator_id}'>"
            f"{mod_display}</a>"
        )
    lines.append(f"💬 المجموعة: <code>{chat_id}</code>")
    try:
        now_str = TimeUtils.mecca_now().strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    lines.append("")
    lines.append(f"🕐 {now_str}")
    return "\n".join(lines)


async def _notify_group_log_penalty(
    context, chat_id, target_user_id, target_first_name, target_username,
    penalty_type, duration_seconds, source="auto",
    violation_type=None, moderator_id=None, moderator_name=None,
):
    if not FEATURE_LOG_PENALTIES:
        return
    try:
        if not await _can_send_log(chat_id):
            return
    except Exception:
        return
    try:
        text = _build_penalty_log_text(
            chat_id, target_user_id, target_first_name,
            target_username, penalty_type, duration_seconds,
            source, violation_type, moderator_id, moderator_name,
        )
        await _dispatch_log(
            partial(notify_group_log, context, chat_id, text),
            label=f"penalty-{penalty_type}",
        )
    except Exception as e:
        logger.warning("⚠️ _notify_group_log_penalty: %s", e)


# ═══════════════════════════════════════════════════════════════════
# Delete Failure Notifier
# ═══════════════════════════════════════════════════════════════════

_delete_failure_counter: Dict[int, Tuple[int, float]] = {}
_delete_failure_counter_lock = asyncio.Lock()

_delete_failure_notified: Dict[int, float] = {}
_DELETE_FAILURE_NOTIFY_COOLDOWN = 3600.0
_delete_failure_notify_lock = asyncio.Lock()

_DELETE_IGNORED_PATTERNS = (
    "message to delete not found",
    "message identifier is not specified",
    "message is not found",
)

_DELETE_PERMISSION_PATTERNS = (
    "not enough rights",
    "have no rights",
    "bot is not a member",
    "chat_admin_required",
    "message can't be deleted",
)

_MEDIA_SETTINGS_MAP = (
    ('video', 'delete_videos', 'video'),
    ('audio', 'delete_audio', 'audio'),
    ('voice', 'delete_voice', 'voice'),
    ('animation', 'delete_animation', 'animation'),
    ('document', 'delete_documents', 'document'),
    ('sticker', 'delete_stickers', 'sticker'),
    ('photo', 'delete_photos', 'photo'),
    ('video_note', 'delete_video_note', 'video_note'),
)


def _is_delete_ignore_error(exc) -> bool:
    try:
        s = str(exc).lower()
        return any(p in s for p in _DELETE_IGNORED_PATTERNS)
    except Exception:
        return False


def _is_delete_permission_error(exc) -> bool:
    try:
        s = str(exc).lower()
        return any(p in s for p in _DELETE_PERMISSION_PATTERNS)
    except Exception:
        return False


async def _record_delete_failure(chat_id) -> bool:
    try:
        async with _delete_failure_counter_lock:
            now = time.monotonic()
            cnt, first_ts = _delete_failure_counter.get(chat_id, (0, now))
            if now - first_ts > _DELETE_FAILURE_NOTIFY_WINDOW:
                cnt = 0
                first_ts = now
            cnt += 1
            _delete_failure_counter[chat_id] = (cnt, first_ts)
            if len(_delete_failure_counter) > 5000:
                stale = [
                    k for k, (_, ts) in _delete_failure_counter.items()
                    if now - ts > _DELETE_FAILURE_NOTIFY_WINDOW * 2
                ]
                for k in stale:
                    _delete_failure_counter.pop(k, None)
            return cnt >= _DELETE_FAILURE_NOTIFY_THRESHOLD
    except Exception:
        return False


async def _notify_delete_permission_failure(context, chat_id):
    try:
        async with _delete_failure_notify_lock:
            now = time.monotonic()
            last = _delete_failure_notified.get(chat_id, 0.0)
            if now - last < _DELETE_FAILURE_NOTIFY_COOLDOWN:
                return
            _delete_failure_notified[chat_id] = now
        owner_id = int(getattr(CONFIG, 'PRIMARY_OWNER_ID', 0) or 0)
        if not owner_id:
            return
        msg = (
            "⚠️ <b>تحذير — تعذّر حذف الرسائل!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"البوت لا يستطيع حذف الرسائل في المجموعة "
            f"<code>{chat_id}</code>.\n\n"
            "🔴 <b>عقوبات الحماية لن تُطبَّق فعلياً</b> — "
            "لأن الرسالة المخالفة تبقى قائمة.\n\n"
            "✅ <b>الحل:</b>\n"
            "1. ارفع البوت لمشرف في المجموعة\n"
            "2. امنحه صلاحية <code>can_delete_messages</code>\n"
            "3. تأكد من أن البوت عضو في المجموعة\n"
        )
        try:
            await safe_send(context.bot, owner_id, msg, parse_mode='HTML')
        except Exception as e:
            logger.warning("_notify_delete_permission_failure: %s", e)
    except Exception:
        pass


async def _safe_delete_message(
    bot, chat_id, message_id, *,
    context=None, notify_owner=True,
) -> bool:
    try:
        await bot.delete_message(chat_id, message_id)
        logger.debug("✅ DELETE OK | chat=%s msg=%s", chat_id, message_id)
        return True
    except BadRequest as e:
        if _is_delete_permission_error(e):
            logger.error(
                "❌ DELETE FAILED (perm) | chat=%s msg=%s",
                chat_id, message_id,
            )
            if notify_owner and context is not None:
                try:
                    should_notify = await _record_delete_failure(chat_id)
                    if should_notify:
                        _spawn_tracked_task(
                            _notify_delete_permission_failure(context, chat_id),
                            label="delete-perm-notify",
                        )
                except Exception:
                    pass
            return False
        if _is_delete_ignore_error(e):
            return True
        logger.warning("⚠️ DELETE failed | chat=%s msg=%s", chat_id, message_id)
        return False
    except asyncio.CancelledError:
        raise
    except Exception as e:
        if _is_delete_permission_error(e):
            if notify_owner and context is not None:
                try:
                    should_notify = await _record_delete_failure(chat_id)
                    if should_notify:
                        _spawn_tracked_task(
                            _notify_delete_permission_failure(context, chat_id),
                            label="delete-perm-notify",
                        )
                except Exception:
                    pass
            return False
        if _is_delete_ignore_error(e):
            return True
        logger.warning(
            "⚠️ DELETE failed | chat=%s msg=%s | %s", chat_id, message_id, e,
        )
        return False


# ═══════════════════════════════════════════════════════════════════
# Forward Detection
# ═══════════════════════════════════════════════════════════════════

_PROTECTED_FORWARD_HINTS = (
    "محولة من", "محوّل من", "محوله من",
    "تم التحويل من", "المعاد توجيهها من",
    "Forwarded from", "من قناة",
)


def _has_forward_hint(text) -> bool:
    if not text:
        return False
    head = text[:250]
    tail = text[-250:] if len(text) > 250 else text
    for hint in _PROTECTED_FORWARD_HINTS:
        if hint in head or hint in tail:
            return True
    return False


def is_forwarded(
    message, *, allow_protected_fallback=False, allow_protected_any=False,
) -> bool:
    if message is None:
        return False
    for attr in (
        'forward_origin', 'forward_date', 'forward_from',
        'forward_from_chat', 'forward_sender_name',
    ):
        if getattr(message, attr, None) is not None:
            return True
    is_protected = _as_bool(
        getattr(message, 'has_protected_content', False), False,
    )
    is_auto = _as_bool(getattr(message, 'is_automatic_forward', False), False)
    if allow_protected_any and is_protected and not is_auto:
        return True
    if allow_protected_fallback and is_protected:
        caption = (
            getattr(message, 'caption', None)
            or getattr(message, 'text', None)
            or ""
        )
        if _has_forward_hint(caption):
            return True
    return False


def get_forward_detection_reason(message) -> Dict[str, Any]:
    if message is None:
        return {"error": "message is None"}
    fields = {}
    for name in (
        'forward_origin', 'forward_date', 'forward_from',
        'forward_from_chat', 'forward_sender_name',
    ):
        value = getattr(message, name, None)
        fields[name] = {
            "present": value is not None,
            "type": type(value).__name__ if value is not None else None,
            "repr_short": str(value)[:80] if value is not None else None,
        }
    any_present = any(f["present"] for f in fields.values())
    protected = _as_bool(
        getattr(message, 'has_protected_content', False), False,
    )
    caption = (
        getattr(message, 'caption', None)
        or getattr(message, 'text', None)
        or ""
    )
    hint = _has_forward_hint(caption) if protected else False
    auto_fwd = _as_bool(
        getattr(message, 'is_automatic_forward', False), False,
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
        fwd_from = getattr(message, 'forward_from', None)
        fwd_from_chat = getattr(message, 'forward_from_chat', None)
        fwd_sender_name = getattr(message, 'forward_sender_name', None)
        fwd_date = getattr(message, 'forward_date', None)
        fwd_signature = getattr(message, 'forward_signature', None)
        if fwd_from is not None:
            try:
                full_name = (
                    getattr(fwd_from, 'full_name', None)
                    or getattr(fwd_from, 'first_name', None)
                    or ""
                )
            except Exception:
                full_name = ""
            return {
                'type': 'user',
                'id': getattr(fwd_from, 'id', None),
                'name': full_name or str(getattr(fwd_from, 'id', 'User')),
                'date': fwd_date, 'signature': None, 'message_id': None,
            }
        if fwd_from_chat is not None:
            chat_type = getattr(fwd_from_chat, 'type', '') or ''
            is_channel = chat_type == 'channel'
            return {
                'type': 'channel' if is_channel else 'chat',
                'id': getattr(fwd_from_chat, 'id', None),
                'name': (
                    getattr(fwd_from_chat, 'title', None)
                    or getattr(fwd_from_chat, 'username', None)
                    or str(getattr(fwd_from_chat, 'id', 'Chat'))
                ),
                'date': fwd_date, 'signature': fwd_signature,
                'message_id': None,
            }
        if fwd_sender_name:
            return {
                'type': 'hidden_user', 'id': None,
                'name': str(fwd_sender_name), 'date': fwd_date,
                'signature': None, 'message_id': None,
            }
    except Exception:
        pass
    return None


def extract_forward_info(message):
    if message is None:
        return None
    origin = getattr(message, 'forward_origin', None)
    if origin is not None and _HAS_MESSAGE_ORIGIN:
        try:
            if isinstance(origin, MessageOriginUser):
                user = origin.sender_user
                try:
                    name = (
                        getattr(user, 'full_name', None)
                        or getattr(user, 'first_name', None)
                        or str(getattr(user, 'id', 'User'))
                    )
                except Exception:
                    name = str(getattr(user, 'id', 'User'))
                return {
                    'type': 'user', 'id': getattr(user, 'id', None),
                    'name': name, 'date': getattr(origin, 'date', None),
                    'signature': None, 'message_id': None,
                }
            if isinstance(origin, MessageOriginHiddenUser):
                # 🆕 v7.18.7 FIX-7: fallback "Hidden User" عند None
                name = (
                    getattr(origin, 'sender_user_name', None)
                    or "Hidden User"
                )
                return {
                    'type': 'hidden_user', 'id': None,
                    'name': name,
                    'date': getattr(origin, 'date', None),
                    'signature': None, 'message_id': None,
                }
            if isinstance(origin, MessageOriginChat):
                chat = origin.sender_chat
                return {
                    'type': 'chat', 'id': getattr(chat, 'id', None),
                    'name': (
                        getattr(chat, 'title', None)
                        or getattr(chat, 'username', None)
                        or str(getattr(chat, 'id', 'Chat'))
                    ),
                    'date': getattr(origin, 'date', None),
                    'signature': getattr(origin, 'author_signature', None),
                    'message_id': None,
                }
            if isinstance(origin, MessageOriginChannel):
                chat = origin.chat
                return {
                    'type': 'channel', 'id': getattr(chat, 'id', None),
                    'name': (
                        getattr(chat, 'title', None)
                        or getattr(chat, 'username', None)
                        or str(getattr(chat, 'id', 'Channel'))
                    ),
                    'date': getattr(origin, 'date', None),
                    'signature': getattr(origin, 'author_signature', None),
                    'message_id': getattr(origin, 'message_id', None),
                }
        except Exception:
            pass
    info = _extract_legacy_forward_info(message)
    if info:
        return info
    is_protected = _as_bool(
        getattr(message, 'has_protected_content', False), False,
    )
    if is_protected:
        caption = (
            getattr(message, 'caption', None)
            or getattr(message, 'text', None)
            or ""
        )
        if _has_forward_hint(caption):
            return {
                'type': 'protected', 'id': None,
                'name': '🛡️ محتوى محمي (forward مخفي)',
                'date': None, 'signature': None, 'message_id': None,
            }
        return {
            'type': 'protected_any', 'id': None, 'name': '🛡️ محتوى محمي',
            'date': None, 'signature': None, 'message_id': None,
        }
    return None


# ═══════════════════════════════════════════════════════════════════
# 🆕 v7.18.3: get_forward_info + _is_postbot_forward
# ═══════════════════════════════════════════════════════════════════

def get_forward_info(message) -> Dict[str, Any]:
    """v7.18.3: استخراج موحّد لمعلومات الرسالة المحوّلة."""
    result: Dict[str, Any] = {
        "is_forwarded": False,
        "origin_type": None,
        "original_chat_id": None,
        "original_message_id": None,
        "original_user_id": None,
        "original_username": None,
        "original_name": None,
        "origin_date": None,
        "sender_chat_id": None,
        "sender_chat_title": None,
        "is_automatic_forward": False,
    }

    if message is None:
        return result

    try:
        sender_chat = getattr(message, "sender_chat", None)
        if sender_chat is not None:
            result["sender_chat_id"] = getattr(sender_chat, "id", None)
            result["sender_chat_title"] = (
                getattr(sender_chat, "title", None)
                or getattr(sender_chat, "username", None)
            )

        result["is_automatic_forward"] = bool(
            getattr(message, "is_automatic_forward", False)
        )

        origin = getattr(message, "forward_origin", None)
        if origin is None:
            legacy = _extract_legacy_forward_info(message)
            if legacy:
                result["is_forwarded"] = True
                result["origin_type"] = legacy.get("type")
                result["original_user_id"] = legacy.get("id")
                result["original_name"] = legacy.get("name")
                result["origin_date"] = legacy.get("date")
            return result

        result["is_forwarded"] = True
        result["origin_date"] = getattr(origin, "date", None)

        if isinstance(origin, MessageOriginChannel):
            result["origin_type"] = "channel"
            result["original_chat_id"] = getattr(origin.chat, "id", None)
            result["original_message_id"] = getattr(origin, "message_id", None)
            result["original_username"] = getattr(origin.chat, "username", None)
            result["original_name"] = getattr(origin.chat, "title", None)
        elif isinstance(origin, MessageOriginUser):
            result["origin_type"] = "user"
            user = origin.sender_user
            result["original_user_id"] = getattr(user, "id", None)
            result["original_username"] = getattr(user, "username", None)
            result["original_name"] = (
                getattr(user, "full_name", None)
                or getattr(user, "first_name", None)
            )
        elif isinstance(origin, MessageOriginChat):
            result["origin_type"] = "chat"
            chat = origin.sender_chat
            result["original_chat_id"] = getattr(chat, "id", None)
            result["original_name"] = (
                getattr(chat, "title", None)
                or getattr(chat, "username", None)
            )
        elif isinstance(origin, MessageOriginHiddenUser):
            result["origin_type"] = "hidden_user"
            # 🆕 v7.18.7 FIX-7: fallback "Hidden User"
            result["original_name"] = (
                getattr(origin, "sender_user_name", None)
                or "Hidden User"
            )
        else:
            result["origin_type"] = type(origin).__name__
    except Exception as e:
        logger.debug("get_forward_info error: %s", e)

    return result


def _is_postbot_forward(message) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    v7.18.3: كشف Post Bot (يشمل القنوات الخاصة).
    🆕 v7.18.7 FIX-3: استخدام _normalize_tg_id + _POSTBOT_RAW_IDS.
    """
    if message is None or not _FORCE_DELETE_POSTBOT_FORWARDS:
        return False, None
    try:
        info = get_forward_info(message)

        if not info.get("is_forwarded") and not info.get("sender_chat_id"):
            return False, None

        # sender_chat
        sender_id = info.get("sender_chat_id")
        if sender_id is not None:
            if _normalize_tg_id(sender_id) in _POSTBOT_RAW_IDS:
                return True, {
                    "type": "channel", "id": sender_id,
                    "name": info.get("sender_chat_title"),
                }
        sender_title = info.get("sender_chat_title") or ""
        if _is_postbot_channel_name(sender_title):
            return True, {
                "type": "channel", "id": sender_id,
                "name": sender_title,
            }

        # forward_origin
        ftype = (info.get("origin_type") or "").lower()
        if ftype not in (
            "channel", "chat", "user", "hidden_user",
            "protected", "protected_any",
        ):
            return False, None

        for id_key in ("original_chat_id", "original_user_id"):
            oid = info.get(id_key)
            if oid is None:
                continue
            if _normalize_tg_id(oid) in _POSTBOT_RAW_IDS:
                return True, {
                    "type": ftype, "id": oid,
                    "name": info.get("original_name"),
                    "message_id": info.get("original_message_id"),
                }

        name = info.get("original_name") or ""
        if _is_postbot_channel_name(name):
            return True, {
                "type": ftype,
                "id": (
                    info.get("original_chat_id")
                    or info.get("original_user_id")
                ),
                "name": name,
                "message_id": info.get("original_message_id"),
            }
    except Exception as e:
        logger.debug("_is_postbot_forward error: %s", e)
    return False, None


async def _notify_admin_about_forward(context, admin_id, info):
    if not info or not admin_id:
        return
    try:
        type_labels = {
            'user': '👤 مستخدم', 'hidden_user': '👻 مستخدم مخفي',
            'chat': '👥 مجموعة', 'channel': '📢 قناة',
            'protected': '🛡️ محتوى محمي', 'protected_any': '🛡️ محتوى محمي',
        }
        label = type_labels.get(info.get('type', ''), f"❔ {info.get('type')}")
        lines = ["↩️ <b>رسالة مُعاد توجيهها</b>", "", f"📌 النوع: {label}"]
        if info.get('id'):
            lines.append(f"🆔 المصدر: <code>{info['id']}</code>")
        if info.get('name'):
            lines.append(f"📛 الاسم: {escape(str(info['name']))}")
        if info.get('message_id'):
            lines.append(f"🔢 رقم الرسالة: <code>{info['message_id']}</code>")
        if info.get('date'):
            lines.append(f"📅 التاريخ: <code>{info['date']}</code>")
        await safe_send(
            context.bot, admin_id, "\n".join(lines), parse_mode='HTML',
        )
    except Exception:
        pass


def _should_notify_forward(context, chat_id) -> bool:
    try:
        bot_data = getattr(context, 'bot_data', None)
        if not isinstance(bot_data, dict):
            return False
        key = f"_forward_notify_{chat_id}"
        now = time.monotonic()
        last = bot_data.get(key, 0.0)
        if not isinstance(last, (int, float)):
            last = 0.0
        if now - last < _FORWARD_NOTIFY_COOLDOWN_SECONDS:
            return False
        fwd_keys = [
            k for k in bot_data.keys()
            if isinstance(k, str) and k.startswith("_forward_notify_")
        ]
        if len(fwd_keys) >= _FORWARD_NOTIFY_MAX_KEYS:
            remove_count = max(1, len(fwd_keys) // 2)
            for k in fwd_keys[:remove_count]:
                bot_data.pop(k, None)
        bot_data[key] = now
        return True
    except Exception:
        return False


async def _invalidate_after_channel_change(
    user_id, channel_db_id=None, invalidate_posts=True,
):
    keys = [
        f"start_data_{user_id}", f"user_{user_id}",
        f"user_{user_id}_True", f"user_{user_id}_False",
        f"channels_{user_id}",
    ]
    if channel_db_id is not None:
        keys.append(f"channel_info_{channel_db_id}")
    await _safe_invalidate(*keys)
    try:
        from cache import invalidate_user_cache
        await invalidate_user_cache(user_id)
    except Exception:
        pass
    if invalidate_posts and channel_db_id is not None:
        try:
            await posts_cache.invalidate(channel_db_id)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# Group Rate Limiter
# ═══════════════════════════════════════════════════════════════════

class GroupRateLimiterManager:
    _limiters: Dict[int, Any] = {}
    _last_access: Dict[int, float] = {}
    _lock = asyncio.Lock()
    MAX_SIZE = MAX_GROUP_LIMITERS_CACHE

    @classmethod
    async def get(cls, chat_id):
        async with cls._lock:
            now = time.time()
            if len(cls._limiters) >= cls.MAX_SIZE and chat_id not in cls._limiters:
                sorted_items = sorted(
                    cls._last_access.items(), key=lambda item: item[1],
                )
                to_remove = sorted_items[: max(1, cls.MAX_SIZE // 5)]
                for cid, _ in to_remove:
                    cls._limiters.pop(cid, None)
                    cls._last_access.pop(cid, None)
            if chat_id not in cls._limiters:
                cls._limiters[chat_id] = RateLimiter(
                    max_concurrent=5, max_per_second=10,
                )
            cls._last_access[chat_id] = now
            return cls._limiters[chat_id]

    @classmethod
    async def periodic_cleanup_task(cls):
        while True:
            try:
                await asyncio.sleep(CACHE_CLEANUP_INTERVAL)
                now = time.time()
                async with cls._lock:
                    to_remove = [
                        cid for cid, ts in cls._last_access.items()
                        if now - ts > 7200
                    ]
                    for cid in to_remove:
                        cls._limiters.pop(cid, None)
                        cls._last_access.pop(cid, None)
                await _cleanup_log_rate_tracker()
                await _cleanup_delete_failure_counter()
                try:
                    await _cleanup_flood_tracker(force=True)
                except Exception:
                    pass
                # 🆕 v7.18.6: تنظيف caches PERF
                try:
                    _prune_perf_caches()
                except Exception:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("❌ periodic_cleanup: %s", e)


def _prune_perf_caches() -> int:
    """
    🆕 v7.18.6: تنظيف دوري للـ caches المحلية (PERF-1/2/7).
    يعيد العدد الكلي للمُزال.
    """
    removed = 0
    now = time.monotonic()

    try:
        stale = [
            k for k, (_, ts) in _group_log_channel_cache.items()
            if now - ts > _GROUP_LOG_CHANNEL_CACHE_TTL * 5
        ]
        for k in stale:
            _group_log_channel_cache.pop(k, None)
        removed += len(stale)
    except Exception:
        pass

    try:
        stale = [
            k for k, (_, ts) in _sec_settings_local_cache.items()
            if now - ts > _SEC_SETTINGS_LOCAL_TTL * 5
        ]
        for k in stale:
            _sec_settings_local_cache.pop(k, None)
        removed += len(stale)
    except Exception:
        pass

    try:
        stale = [
            k for k, (_, ts) in _admin_check_cache.items()
            if now - ts > _ADMIN_CHECK_CACHE_TTL * 5
        ]
        for k in stale:
            _admin_check_cache.pop(k, None)
        removed += len(stale)
    except Exception:
        pass

    if removed > 0:
        logger.debug("🧹 _prune_perf_caches: حُذف %d إدخال", removed)
    return removed


async def _cleanup_delete_failure_counter():
    try:
        async with _delete_failure_counter_lock:
            now = time.monotonic()
            stale = [
                k for k, (_, ts) in _delete_failure_counter.items()
                if now - ts > _DELETE_FAILURE_NOTIFY_WINDOW * 5
            ]
            for k in stale:
                _delete_failure_counter.pop(k, None)
    except Exception:
        pass


async def _acquire_group_limiter(chat_id):
    try:
        limiter = await GroupRateLimiterManager.get(chat_id)
        await limiter.acquire()
        return limiter, True
    except Exception as e:
        logger.warning("⚠️ group limiter acquire: %s", e)
        return None, False


async def _release_group_limiter(limiter, acquired):
    if not limiter or not acquired:
        return
    try:
        release = getattr(limiter, 'release', None)
        if callable(release):
            result = release()
            if asyncio.iscoroutine(result):
                await result
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# Translation Helpers
# ═══════════════════════════════════════════════════════════════════

async def _trans(key, lang, default=""):
    if not key:
        return default or ""
    try:
        if lang and lang != 'off':
            text = TranslationManager.get_text(lang, key)
            if text and text != key:
                return text
    except Exception:
        pass
    try:
        if lang and lang != 'off':
            text = await get_text(lang, key)
            if text and text != key:
                return text
    except Exception:
        pass
    return default or key


def _fmt(template, **kwargs) -> str:
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


async def _ensure_lang(update, context) -> str:
    lang = context.user_data.get('lang')
    if lang:
        return lang
    try:
        user_id = (
            update.effective_user.id
            if update and update.effective_user else None
        )
    except Exception:
        user_id = None
    if user_id:
        try:
            from cache import user_cache
            cached = await user_cache.get(user_id)
            if cached and cached.get('language'):
                lang = cached['language']
                context.user_data['lang'] = lang
                return lang
        except Exception:
            pass
        try:
            lang = await asyncio.wait_for(
                DB.get_user_language(user_id), timeout=2.0,
            ) or 'ar'
            context.user_data['lang'] = lang
            return lang
        except Exception:
            pass
    return 'ar'


def clear_lang_cache(context):
    try:
        context.user_data.pop('lang', None)
        context.user_data.pop('translation_cache', None)
        context.user_data.pop('cached_translations', None)
        context.user_data.pop('last_translation', None)
    except Exception:
        pass


async def get_security_settings_cached(chat_id) -> dict:
    """
    🟠 PERF-2 (v7.18.6): طبقتان من cache لتقليل ضغط DB.

    قبل v7.18.6:
        كل رسالة → settings_cache.get_security → DB query (أحياناً)

    بعد v7.18.6:
        كل رسالة → _sec_settings_local_cache (5s TTL، ذاكرة)
        كل 5s → settings_cache.get_security (طبقة ثانية)
        كل انتهاء settings_cache TTL → DB query

    ⚠️ يُنصح باستدعاء _invalidate_sec_settings_local(chat_id)
        عند تعديل أي إعداد أمان من handlers_callback.
    """
    now = time.monotonic()

    try:
        entry = _sec_settings_local_cache.get(int(chat_id))
    except (TypeError, ValueError):
        entry = None

    if entry is not None:
        cached_value, cached_at = entry
        if now - cached_at < _SEC_SETTINGS_LOCAL_TTL:
            return cached_value

    settings = None
    try:
        settings = await settings_cache.get_security(chat_id)
    except Exception as e:
        logger.debug("settings_cache.get_security(%s): %s", chat_id, e)

    if settings is None or not isinstance(settings, dict):
        try:
            settings = await DB.get_security_settings(chat_id)
        except Exception as e:
            logger.debug("DB.get_security_settings(%s): %s", chat_id, e)
            settings = None

        settings = _row_to_dict_local(settings) or {}
        try:
            await settings_cache.set_security(chat_id, settings)
        except Exception:
            pass

    if len(_sec_settings_local_cache) >= _SEC_SETTINGS_LOCAL_MAX:
        try:
            oldest = sorted(
                _sec_settings_local_cache.items(),
                key=lambda kv: kv[1][1],
            )[: max(1, _SEC_SETTINGS_LOCAL_MAX // 5)]
            for k, _ in oldest:
                _sec_settings_local_cache.pop(k, None)
        except Exception:
            pass

    try:
        _sec_settings_local_cache[int(chat_id)] = (settings, now)
    except (TypeError, ValueError):
        pass

    return settings


async def get_auto_reply_settings_cached(chat_id) -> dict:
    cached = await settings_cache.get_auto_reply_settings(chat_id)
    if cached is not None and isinstance(cached, dict):
        return cached
    settings = await DB.get_auto_reply_settings(chat_id)
    settings = _row_to_dict_local(settings) or {}
    try:
        await settings_cache.set_auto_reply_settings(chat_id, settings)
    except Exception:
        pass
    return settings


async def invalidate_security_cache(chat_id=None):
    await settings_cache.invalidate_security(chat_id)
    _invalidate_sec_settings_local(chat_id)


async def invalidate_auto_reply_cache(chat_id=None):
    await settings_cache.invalidate_auto_reply(chat_id)


async def _detect_and_translate(update, context, chat_id, user_id, text):
    """
    🆕 v7.18.7 FIX-6: كشف اللغة + ترجمة.

    سياسة الترجمة (قرار تصميمي صريح):
        • lang='ar' + نص عربي   → لا ترجمة (نفس اللغة)
        • lang='ar' + نص أجنبي  → ترجم إلى عربي
        • lang≠'ar' + نص عربي   → ترجم إلى لغة المستخدم
        • lang≠'ar' + نص أجنبي  → لا ترجمة (اللغتان غير عربية)

    ⚠️ لا يُترجم بين لغتين أجنبيتين (مثلاً: إنجليزي → فرنسي)
       لأن TranslationManager مصمم للعربية كمحور مركزي.
    """
    if not text or len(text.strip()) < TRANSLATION_MIN_TEXT_LENGTH:
        return None
    try:
        lang = await _ensure_lang(update, context)
        if not lang or lang == 'off':
            return None
        if text.startswith('/'):
            return None
        stripped = text.strip()
        if stripped.startswith(('http://', 'https://', 'www.')):
            return None
        is_arabic = TranslationManager.detect_arabic(text)
        if lang == 'ar' and is_arabic:
            return None
        if lang != 'ar' and not is_arabic:
            return None
        translated = TranslationManager.translate(text, lang)
        if translated and translated != text:
            return translated
    except Exception:
        pass
    return None


async def _send_translation_reply(
    bot, chat_id, original_message_id, translated, lang, context=None,
):
    if not translated:
        return
    try:
        label = (
            TranslationManager.get_text(lang, "translation_label")
            or "🌐 <b>Translation:</b>"
        )
    except Exception:
        label = "🌐 <b>Translation:</b>"
    try:
        translated_safe = escape(str(translated))
        kwargs = {
            "chat_id": chat_id,
            "text": f"{label}\n{translated_safe}",
            "parse_mode": "HTML",
        }
        if original_message_id:
            kwargs["reply_to_message_id"] = original_message_id
        sent = await bot.send_message(**kwargs)
        if sent and getattr(sent, 'message_id', None):
            _spawn_delete_after_delay(
                bot, chat_id, sent.message_id,
                TRANSLATION_REPLY_DELETE_DELAY,
                context=context,
            )
    except Exception:
        pass


async def apply_violation_penalty(
    update, context, chat_id, user_id,
    violation_type, penalty_type, duration_seconds, lang='ar',
):
    try:
        username = ""
        first_name = ""
        chat_name = ""
        try:
            if update and update.effective_user:
                username = update.effective_user.username or ""
                first_name = update.effective_user.first_name or ""
            if update and update.effective_chat:
                chat_name = update.effective_chat.title or ""
        except Exception:
            pass
        return await apply_penalty(
            context.bot, chat_id, user_id, penalty_type, duration_seconds,
            f"violation: {violation_type}",
            moderator=context.bot.id,
            username=username, first_name=first_name, chat_name=chat_name,
            lang=lang,
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error("❌ apply_violation_penalty: %s", e)
        return False, str(e)[:100]


# ═══════════════════════════════════════════════════════════════════
# Admin Helpers
# ═══════════════════════════════════════════════════════════════════

_BLOCKED_HOST_PATTERNS = (
    "localhost", "127.", "0.0.0.0", "::1",
    "10.", "192.168.", "169.254.", "metadata.google",
)


def _is_safe_url(url) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        if any(ord(c) > 127 for c in host):
            return False
        try:
            ip = ipaddress.ip_address(host)
            if (ip.is_private or ip.is_loopback or ip.is_reserved
                    or ip.is_link_local or ip.is_multicast):
                return False
        except ValueError:
            pass
        for pattern in _BLOCKED_HOST_PATTERNS:
            if host.startswith(pattern) or host == pattern.rstrip("."):
                return False
        return True
    except Exception:
        return False


def _parse_contest_date(date_str):
    if not date_str:
        return None
    date_str = date_str.strip()
    if date_str.endswith(("Z", "z")):
        date_str = date_str[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(date_str.replace(" ", "T"))
    except (ValueError, TypeError):
        pass
    for fmt in (
        "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d", "%d-%m-%Y %H:%M", "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


async def _check_admin_in_chat(context, chat_id, user_id) -> bool:
    """
    🟡 PERF-7 (v7.18.6): cache 30s لنتيجة فحص الأدمن.

    قبل v7.18.6:
        كل استدعاء → is_authorized_in_group (cache) + DB query
    بعد v7.18.6:
        كل استدعاء → cache محلي (30s)
        كل 30s → is_authorized_in_group + DB query

    ⚠️ يُنصح باستدعاء _invalidate_admin_check_cache(chat_id, user_id)
        عند تغيير صلاحيات المشرفين.
    """
    if user_id == CONFIG.PRIMARY_OWNER_ID:
        return True

    try:
        cache_key = (int(chat_id), int(user_id))
    except (TypeError, ValueError):
        cache_key = None

    if cache_key is not None:
        now = time.monotonic()
        entry = _admin_check_cache.get(cache_key)
        if entry is not None:
            cached_value, cached_at = entry
            if now - cached_at < _ADMIN_CHECK_CACHE_TTL:
                return cached_value

    result = False
    try:
        if await is_authorized_in_group(context.bot, chat_id, user_id):
            result = True
    except Exception:
        pass

    if not result:
        try:
            db_type = getattr(DB, "DB_TYPE", "sqlite")
            if db_type == "postgres":
                sql = ("SELECT 1 FROM group_admins "
                       "WHERE chat_id = $1 AND user_id = $2 LIMIT 1")
            else:
                sql = ("SELECT 1 FROM group_admins "
                       "WHERE chat_id = ? AND user_id = ? LIMIT 1")
            row = await DB.fetchval(sql, (chat_id, user_id))
            result = row is not None
        except Exception:
            result = False

    if cache_key is not None:
        if len(_admin_check_cache) >= _ADMIN_CHECK_CACHE_MAX:
            try:
                oldest = sorted(
                    _admin_check_cache.items(),
                    key=lambda kv: kv[1][1],
                )[: max(1, _ADMIN_CHECK_CACHE_MAX // 5)]
                for k, _ in oldest:
                    _admin_check_cache.pop(k, None)
            except Exception:
                pass
        try:
            _admin_check_cache[cache_key] = (result, time.monotonic())
        except Exception:
            pass

    return result


async def _verify_bot_in_log_channel(context, channel_id):
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
            context.bot.get_chat_member(channel_id, bot_id), timeout=10.0,
        )
    except asyncio.TimeoutError:
        return False, "timeout"
    except BadRequest as e:
        err = str(e).lower()
        if any(x in err for x in (
            "chat not found", "bot is not a member",
            "member not found", "user not found",
        )):
            return False, "bot_not_member"
        if "chat_admin_required" in err or "not enough rights" in err:
            return False, "need_admin_rights"
        return False, "bad_request"
    except Exception as e:
        logger.warning("_verify_bot_in_log_channel: %s", e)
        return False, "unknown_error"
    status = getattr(member, "status", None)
    if status not in ("administrator", "creator"):
        return False, "not_admin"
    if getattr(member, "can_post_messages", None) is False:
        return False, "no_post_permission"
    return True, ""


def _verify_bot_in_log_channel_error_text(reason, lang) -> str:
    _ = lang
    mapping = {
        "invalid_channel_id": "❌ معرّف القناة غير صالح.",
        "timeout": "⏱️ انتهت مهلة الاتصال.",
        "bot_not_member": "❌ البوت ليس عضواً في القناة.",
        "need_admin_rights": "❌ البوت يحتاج صلاحيات مشرف.",
        "not_admin": "❌ البوت ليس مشرفاً.",
        "no_post_permission": "❌ البوت لا يملك صلاحية النشر.",
        "bad_request": "❌ تعذّر الوصول للقناة.",
    }
    return mapping.get(reason, "❌ تعذّر التحقق من قناة السجل.")


try:
    from database_settings import _is_valid_channel_ref  # noqa: F401
except ImportError:
    _TG_USERNAME_RE_FALLBACK = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{3,31}$')

    def _is_valid_channel_ref(value):
        if value is None:
            return True
        value_str = str(value).strip()
        if not value_str:
            return True
        if value_str.lstrip('-').isdigit():
            return True
        if value_str.startswith('@'):
            return bool(_TG_USERNAME_RE_FALLBACK.match(value_str[1:]))
        if _TG_USERNAME_RE_FALLBACK.match(value_str):
            return True
        return False


# ═══════════════════════════════════════════════════════════════════
# Banned Word Matching
# ═══════════════════════════════════════════════════════════════════

_compiled_banned_patterns: "OrderedDict[str, re.Pattern]" = OrderedDict()
_compiled_spaced_patterns: "OrderedDict[str, re.Pattern]" = OrderedDict()

_WORD_SEP_CLASS = r'[\s\-_.|/*+=~^´`°•●○◦▪▫■□♦♢※]'


def _get_banned_pattern(banned_word: str) -> Optional[re.Pattern]:
    cached = _compiled_banned_patterns.get(banned_word)
    if cached is not None:
        _compiled_banned_patterns.move_to_end(banned_word)
        return cached
    try:
        escaped = re.escape(banned_word).replace(r'\ ', r'\s+')
        pattern = re.compile(
            rf'(?<!\w){escaped}(?!\w)', re.IGNORECASE | re.UNICODE,
        )
    except Exception:
        return None
    _compiled_banned_patterns[banned_word] = pattern
    if len(_compiled_banned_patterns) > MAX_COMPILED_BANNED_PATTERNS:
        _compiled_banned_patterns.popitem(last=False)
    return pattern


def _get_spaced_banned_pattern(banned_word: str) -> Optional[re.Pattern]:
    cached = _compiled_spaced_patterns.get(banned_word)
    if cached is not None:
        _compiled_spaced_patterns.move_to_end(banned_word)
        return cached
    try:
        if len(banned_word) < 3 or len(banned_word) > 15:
            return None
        chars = list(banned_word)
        body = r'[\s\-_.|/*+=~^`•●○▪▫■□♦♢※]{1,2}'.join(
            re.escape(c) for c in chars
        )
        pattern = re.compile(
            rf'(?<!\w){body}(?!\w)', re.IGNORECASE | re.UNICODE,
        )
    except Exception:
        return None
    _compiled_spaced_patterns[banned_word] = pattern
    if len(_compiled_spaced_patterns) > MAX_COMPILED_BANNED_PATTERNS:
        _compiled_spaced_patterns.popitem(last=False)
    return pattern


def _contains_banned_word(text, banned_word) -> bool:
    if not text or not banned_word:
        return False
    if len(text) > 4000:
        text = text[:4000]
    try:
        normalized_text = _normalize_text(text).lower()
        normalized_word = _normalize_text(str(banned_word)).lower()
        if not normalized_word:
            return False
        pattern = _get_banned_pattern(normalized_word)
        if pattern is not None and pattern.search(normalized_text):
            return True
        if ANTIEVASION_COMPACT_WORDS and len(normalized_word) >= 3:
            compact_text = re.sub(_WORD_SEP_CLASS, '', normalized_text)
            compact_word = re.sub(_WORD_SEP_CLASS, '', normalized_word)
            if compact_word and compact_word in compact_text:
                return True
            spaced_pattern = _get_spaced_banned_pattern(normalized_word)
            if spaced_pattern is not None:
                if spaced_pattern.search(normalized_text):
                    return True
        return False
    except Exception:
        try:
            return (
                str(banned_word).strip().lower()
                == str(text).strip().lower()
            )
        except Exception:
            return False


def _accepts_state_arg(handler, handler_name: str) -> bool:
    """
    🆕 v7.18.7 FIX-5: مع سقف 128 إدخال (Python 3.7+ يحفظ ترتيب الإدراج).
    """
    cached = _private_handler_signature_cache.get(handler_name)
    if cached is not None:
        return cached
    try:
        sig = inspect.signature(handler)
        params = [
            p for p in sig.parameters.values()
            if p.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        result = len(params) >= 3
    except (TypeError, ValueError):
        result = False

    if len(_private_handler_signature_cache) >= _PRIVATE_SIG_CACHE_MAX:
        try:
            _private_handler_signature_cache.pop(
                next(iter(_private_handler_signature_cache))
            )
        except (StopIteration, KeyError):
            pass

    _private_handler_signature_cache[handler_name] = result
    return result


# ═══════════════════════════════════════════════════════════════════
# MessageHandlers
# ═══════════════════════════════════════════════════════════════════

class MessageHandlers:

    _PRIVATE_HANDLERS_MAP: Dict[Any, str] = {
        "WAIT_GROUP_BAN": "handle_add_banned_word",
        "WAIT_GLOBAL_BAN": "handle_add_global_banned_word",
        "WAIT_REM_GROUP_BAN": "handle_remove_banned_word",
        "WAIT_REM_GLOBAL_BAN": "handle_remove_global_banned_word",
    }

    @staticmethod
    async def handle_group(update, context):
        if (not update or not update.effective_chat
                or not update.effective_message):
            return
        chat_id = update.effective_chat.id
        limiter = None
        limiter_acquired = False
        try:
            limiter, limiter_acquired = await _acquire_group_limiter(chat_id)
            await MessageHandlers._handle_group_impl(update, context)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("❌ handle_group unexpected error")
        finally:
            await _release_group_limiter(limiter, limiter_acquired)

    @staticmethod
    async def handle_edited(update, context):
        if (not update or not update.effective_chat
                or not update.edited_message):
            return
        chat_id = update.effective_chat.id
        limiter = None
        limiter_acquired = False
        try:
            limiter, limiter_acquired = await _acquire_group_limiter(chat_id)
            if update.effective_message is None:
                return
            await MessageHandlers._handle_group_impl(update, context)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("❌ handle_edited error")
        finally:
            await _release_group_limiter(limiter, limiter_acquired)

    @staticmethod
    async def _apply_slow_mode(context, chat_id, settings):
        if not _SLOW_MODE_AUTO:
            return
        try:
            slow_on = _as_bool(settings.get('slow_mode', 0), False)
            try:
                slow_secs = int(settings.get('slow_mode_seconds', 0) or 0)
            except (TypeError, ValueError):
                slow_secs = 0

            bd = context.bot_data
            if isinstance(bd, dict) and len(bd) > _BOT_DATA_SLOW_MODE_PRUNE_THRESHOLD:
                now_ts = time.monotonic()
                last_prune = bd.get("_slow_prune_last_ts", 0.0)
                if not isinstance(last_prune, (int, float)):
                    last_prune = 0.0
                if now_ts - last_prune >= _BOT_DATA_SLOW_MODE_PRUNE_COOLDOWN:
                    prefix = "_slow_applied_"
                    stale = [
                        k for k in list(bd.keys())
                        if isinstance(k, str) and k.startswith(prefix)
                    ]
                    for k in stale[:max(1, len(stale) // 2)]:
                        bd.pop(k, None)
                    bd["_slow_prune_last_ts"] = now_ts

            cache_key = f"_slow_applied_{chat_id}"

            try:
                if isinstance(bd, dict):
                    last_applied = bd.get(cache_key, -1)
                else:
                    last_applied = -1
            except Exception:
                last_applied = -1

            target = slow_secs if (slow_on and slow_secs > 0) else 0
            if target < 0:
                target = 0
            if target > 3600:
                target = 3600

            if target == last_applied:
                return
            if target == 0 and last_applied in (0, -1):
                return

            try:
                await context.bot.set_chat_slow_mode(chat_id, target)
                try:
                    if isinstance(context.bot_data, dict):
                        context.bot_data[cache_key] = target
                except Exception:
                    pass
                logger.info(
                    "🐌 SLOW-MODE | chat=%s seconds=%d",
                    chat_id, target,
                )
            except Exception as e:
                logger.debug(
                    "set_chat_slow_mode(%s, %d): %s",
                    chat_id, target, e,
                )
        except Exception as e:
            logger.debug("_apply_slow_mode: %s", e)

    @staticmethod
    async def _handle_group_impl(update, context):
        if not update.effective_chat or not update.effective_message:
            return
        chat_id = update.effective_chat.id
        await _lazy_init_columns()

        message = update.effective_message

        is_anonymous = False
        if update.effective_user:
            user_id = update.effective_user.id
        elif getattr(message, 'sender_chat', None) is not None:
            user_id = message.sender_chat.id
            is_anonymous = True
        else:
            return

        try:
            ctx = _MessageContext(message)
        except Exception as e:
            logger.debug("_MessageContext build failed: %s", e)
            return

        try:
            METRICS.increment_messages()
        except Exception:
            pass

        settings = await get_security_settings_cached(chat_id)
        if not isinstance(settings, dict):
            settings = {}

        _df_raw = settings.get('delete_forwarded')
        _df_bool = _as_bool(_df_raw, False)
        _protected_fb = _as_bool(
            settings.get('delete_protected_forward'), False,
        )
        _protected_any = _as_bool(settings.get('delete_protected_any'), False)
        _spam_enabled = _as_bool(
            settings.get('delete_spam_score', True), True,
        )
        _postbot_enabled = _as_bool(
            settings.get('delete_postbot_pattern', 0), False,
        )
        _at_channel_enabled = _as_bool(
            settings.get('delete_at_channel', 0), False,
        )
        _tg_scheme_enabled = _as_bool(
            settings.get('delete_tg_scheme', 1), True,
        )
        _button_links_enabled = (
            _FORCE_DELETE_BUTTON_LINKS
            or _as_bool(settings.get('delete_button_links', 1), True)
        )
        _emails_enabled = _as_bool(settings.get('delete_emails', 0), False)
        _polls_enabled = _as_bool(settings.get('delete_polls', 0), False)

        _antiflood_enabled = _as_bool(
            settings.get('antiflood_enabled', 0), False,
        )
        if _antiflood_enabled and _ANTIFLOOD_ENABLED and not is_anonymous:
            try:
                _af_max_raw = settings.get(
                    'antiflood_messages', _FLOOD_DEFAULT_MESSAGES,
                )
                _af_win_raw = settings.get(
                    'antiflood_seconds', _FLOOD_DEFAULT_WINDOW,
                )
                try:
                    _af_max = int(_af_max_raw or _FLOOD_DEFAULT_MESSAGES)
                except (TypeError, ValueError):
                    _af_max = _FLOOD_DEFAULT_MESSAGES
                try:
                    _af_win = float(_af_win_raw or _FLOOD_DEFAULT_WINDOW)
                except (TypeError, ValueError):
                    _af_win = float(_FLOOD_DEFAULT_WINDOW)

                _is_flood = await _check_flood(
                    chat_id, user_id, _af_max, _af_win,
                )
                if _is_flood:
                    if _DEBUG_DIAG:
                        logger.warning(
                            "🌊 FLOOD | chat=%s user=%s max=%d win=%.1fs",
                            chat_id, user_id, _af_max, _af_win,
                        )
                    await MessageHandlers._delete_and_warn(
                        update, context, chat_id, user_id,
                        "antiflood", settings, is_anonymous=False,
                    )
                    return
            except Exception as e:
                logger.debug("flood check: %s", e)

        try:
            await MessageHandlers._apply_slow_mode(
                context, chat_id, settings,
            )
        except Exception as e:
            logger.debug("slow_mode apply: %s", e)

        det = get_forward_detection_reason(message)
        ctx.is_forwarded = _as_bool(det.get('is_forwarded', False), False)
        ctx.is_protected = _as_bool(det.get('is_protected', False), False)
        forward_hint = _as_bool(det.get('has_hint', False), False)
        ctx.is_auto_fwd = _as_bool(
            det.get('has_automatic_forward', False), False,
        )

        is_protected_forward = (
            _protected_fb and ctx.is_protected and forward_hint
            and not ctx.is_forwarded
        )
        is_protected_any_fwd = (
            _protected_any and ctx.is_protected and not ctx.is_forwarded
            and not is_protected_forward
        )

        # 🆕 v7.18.8: Multi-Layer Analysis — ASYNC NATIVE
        _spam_score = 0
        _spam_reasons: List[str] = []
        _spam_layer_scores: Dict[str, float] = {}
        _verdict = None
        _analysis_mode = "text-only"

        if _spam_enabled:
            if _MULTILAYER_ENABLED:
                # 🆕 v7.18.8 FIX-ASYNC-1/2/3/4: wrapper async موحّد
                _verdict = await _run_multilayer_analysis(
                    message,
                    context.bot,
                    label=f"chat={chat_id} msg={message.message_id}",
                )
                if _verdict is not None:
                    _spam_score = int(
                        getattr(_verdict, "total_score", 0) or 0
                    )
                    _spam_layer_scores = dict(
                        getattr(_verdict, "layer_scores", {}) or {}
                    )
                    try:
                        for _layer, _reasons in (
                            getattr(_verdict, "layer_reasons", {}) or {}
                        ).items():
                            for _r in (_reasons or []):
                                _spam_reasons.append(f"{_layer}:{_r}")
                    except Exception:
                        pass
                    _analysis_mode = "multilayer"

            if _verdict is None:
                # fallback: text-only scoring (sync سريع، لا شبكة)
                try:
                    _spam_score, _spam_reasons = _compute_spam_score(ctx)
                    _analysis_mode = "text-only"
                except Exception as e:
                    logger.debug("spam_score: %s", e)

        _is_spam = _spam_enabled and _spam_score >= SPAM_SCORE_THRESHOLD

        _postbot_hard_conf = 0
        try:
            _postbot_hard_conf = _postbot_pattern_confidence(
                ctx.analysis_text,
                button_count=ctx.button_count,
                button_urls=ctx.button_urls,
            )
        except Exception as e:
            logger.debug("postbot confidence: %s", e)
            _postbot_hard_conf = 0

        _postbot_hard_block = (
            _postbot_hard_conf >= POSTBOT_AUTO_BLOCK_CONFIDENCE
        )

        _postbot_match = False
        if _postbot_enabled:
            if _postbot_hard_block:
                _postbot_match = True
            else:
                try:
                    _postbot_match = _is_postbot_pattern(
                        ctx.analysis_text,
                        button_count=ctx.button_count,
                        button_urls=ctx.button_urls,
                    )
                except Exception:
                    _postbot_match = False

        if _postbot_hard_block:
            logger.warning(
                "🤖 POSTBOT-HARD-BLOCK | chat=%s user=%s msg=%s "
                "conf=%d/%d | buttons=%d strong=%d promo=%d cta=%d "
                "spam_emoji=%d | mode=%s",
                chat_id, user_id, message.message_id,
                _postbot_hard_conf, POSTBOT_AUTO_BLOCK_CONFIDENCE,
                ctx.button_count, ctx.strong_word_count,
                ctx.promo_word_count, ctx.cta_count,
                ctx.spam_emoji_count, _analysis_mode,
            )

        if _analysis_mode == "multilayer" and _spam_layer_scores:
            logger.info(
                "🛡️ SHIELD | chat=%s user=%s msg=%s | "
                "total=%.1f | layers=%s",
                chat_id, user_id, message.message_id,
                float(_spam_score),
                {k: round(v, 1)
                 for k, v in _spam_layer_scores.items() if v > 0},
            )

        if _DEBUG_DIAG:
            will_delete_fwd = _df_bool and (
                ctx.is_forwarded or ctx.is_auto_fwd
                or is_protected_forward or is_protected_any_fwd
            )
            _log_level = (
                logging.WARNING
                if (will_delete_fwd or _is_spam or _postbot_match
                    or _postbot_hard_block)
                else logging.INFO
            )
            logger.log(
                _log_level,
                "🚨 DIAG | chat=%s user=%s msg=%s%s | "
                "txt=%s cap=%s poll=%d analysis=%d | "
                "photo=%s video=%s btns=%d | "
                "prot=%s auto_fwd=%s | df=%r/%s | "
                "spam_en=%s score=%d is_spam=%s mode=%s | "
                "postbot_en=%s match=%s hard_conf=%d hard_block=%s | "
                "has_link=%s btn_links=%d ent_links=%d | "
                "vcard=%d venue=%s poll_urls=%d hidden=%d bidi=%d | "
                "mixed_scripts=%s | "
                "url_count=%d tg_links=%d strong=%d medium=%d | "
                "arabic=%d cta=%d | antiflood_en=%s",
                chat_id, user_id, message.message_id,
                " [ANON]" if is_anonymous else "",
                bool(ctx.text), bool(ctx.caption),
                ctx.poll_options_count, len(ctx.analysis_text),
                bool(getattr(message, 'photo', None)),
                bool(getattr(message, 'video', None)),
                ctx.button_count,
                ctx.is_protected, ctx.is_auto_fwd,
                _df_raw, _df_bool,
                _spam_enabled, _spam_score, _is_spam, _analysis_mode,
                _postbot_enabled, _postbot_match,
                _postbot_hard_conf, _postbot_hard_block,
                ctx.has_any_link,
                len(ctx.button_link_urls),
                len(ctx.entity_urls),
                len(ctx.vcard_urls),
                bool(ctx.venue_url),
                len(ctx.poll_urls),
                ctx.hidden_char_count,
                ctx.bidi_count,
                ctx.mixed_scripts,
                ctx.url_count,
                ctx.telegram_link_count,
                ctx.strong_word_count,
                ctx.medium_word_count,
                ctx.arabic_spam_count,
                ctx.cta_count,
                _antiflood_enabled,
            )
            if ctx.button_texts:
                logger.info("   🔘 BTN | %s", ctx.button_texts[:12])
            if ctx.button_urls:
                logger.info("   🔗 URL | %s", ctx.button_urls[:5])
            if ctx.entity_urls:
                logger.info("   🎭 ENT | %s", ctx.entity_urls[:5])
            if _spam_score > 0:
                logger.warning("   🎯 SPAM=%d | %s",
                               _spam_score, _spam_reasons[:10])

        # ═════════════════════════════════════════════════════════════
        # 0) Service
        # ═════════════════════════════════════════════════════════════
        if _as_bool(settings.get('delete_service'), False):
            if message.new_chat_members or message.left_chat_member:
                await _safe_delete_message(
                    context.bot, chat_id, message.message_id, context=context,
                )
                return

        # ═════════════════════════════════════════════════════════════
        # 🆕 v7.18.3: 0.1) Auto-blocked source detection
        # ═════════════════════════════════════════════════════════════
        if _HAS_AUTO_BLOCK:
            try:
                _fwd_ab = get_forward_info(message)
                _source_id = (
                    _fwd_ab.get("original_chat_id")
                    or _fwd_ab.get("original_user_id")
                    or _fwd_ab.get("sender_chat_id")
                )
                if _source_id is not None:
                    if await _is_source_blocked(_source_id):
                        logger.warning(
                            "🚫 AUTO-BLOCKED-SOURCE | chat=%s msg=%s | "
                            "source_id=%s name=%r",
                            chat_id, message.message_id,
                            _source_id, _fwd_ab.get("original_name"),
                        )
                        await MessageHandlers._delete_and_warn(
                            update, context, chat_id, user_id,
                            "postbot_forward", settings,
                            is_anonymous=is_anonymous,
                        )
                        return
            except Exception as e:
                logger.debug("auto-block check: %s", e)

        # ═════════════════════════════════════════════════════════════
        # 🆕 v7.18.3: 0.2) Post Bot forwarded detection
        # ═════════════════════════════════════════════════════════════
        if _FORCE_DELETE_POSTBOT_FORWARDS:
            try:
                _fwd = get_forward_info(message)

                if _fwd.get("is_forwarded") or _fwd.get("sender_chat_id"):
                    logger.info(
                        "🔍 FWD-CHECK | chat=%s msg=%s | "
                        "type=%s name=%r | "
                        "orig_chat_id=%s orig_msg_id=%s orig_user_id=%s | "
                        "sender_chat_id=%s sender_title=%r | "
                        "auto_fwd=%s",
                        chat_id, message.message_id,
                        _fwd.get("origin_type"),
                        _fwd.get("original_name"),
                        _fwd.get("original_chat_id"),
                        _fwd.get("original_message_id"),
                        _fwd.get("original_user_id"),
                        _fwd.get("sender_chat_id"),
                        _fwd.get("sender_chat_title"),
                        _fwd.get("is_automatic_forward"),
                    )

                _is_pb, _pb_info = _is_postbot_forward(message)
                if _is_pb:
                    logger.warning(
                        "📰 POSTBOT-FORWARD-DELETE | chat=%s user=%s msg=%s "
                        "| from=%r id=%s type=%s orig_msg_id=%s",
                        chat_id, user_id, message.message_id,
                        (_pb_info or {}).get("name"),
                        (_pb_info or {}).get("id"),
                        (_pb_info or {}).get("type"),
                        (_pb_info or {}).get("message_id"),
                    )
                    await MessageHandlers._delete_and_warn(
                        update, context, chat_id, user_id,
                        "postbot_forward", settings,
                        is_anonymous=is_anonymous,
                    )
                    return
            except Exception as e:
                logger.debug("postbot forward check: %s", e)

        # ═════════════════════════════════════════════════════════════
        # 0.4) Force delete any button link
        # ═════════════════════════════════════════════════════════════
        if _button_links_enabled and ctx.has_button_link:
            logger.warning(
                "🔘 BUTTON-LINK-DELETE | chat=%s user=%s msg=%s | "
                "buttons=%d | urls=%s",
                chat_id, user_id, message.message_id,
                ctx.button_count,
                ctx.button_link_urls[:3],
            )
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id,
                "button_link", settings, is_anonymous=is_anonymous,
            )
            return

        # 0.5) PostBot HARD-BLOCK
        if _postbot_hard_block:
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id,
                "postbot_pattern", settings, is_anonymous=is_anonymous,
            )
            return

        # 1) Forwarded
        if _df_bool:
            effective_forwarded = (
                ctx.is_forwarded or ctx.is_auto_fwd
                or is_protected_forward or is_protected_any_fwd
            )
            if effective_forwarded:
                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id,
                    "forwarded", settings, is_anonymous=is_anonymous,
                )
                return

        # 2) Spam Score
        if _is_spam:
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id,
                "spam_score", settings, is_anonymous=is_anonymous,
            )
            return

        # 3) PostBot Pattern (legacy)
        if _postbot_enabled and _postbot_match:
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id,
                "postbot_pattern", settings, is_anonymous=is_anonymous,
            )
            return

        # 3b) Poll links
        if _polls_enabled and ctx.poll_urls:
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id,
                "poll_link", settings, is_anonymous=is_anonymous,
            )
            return

        # 4) Links
        if _as_bool(settings.get('delete_links'), False):
            if ctx.has_any_link:
                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id,
                    "link", settings, is_anonymous=is_anonymous,
                )
                return

        # 4b) @channel
        if _at_channel_enabled and _contains_at_channel(ctx.normalized_text):
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id,
                "at_channel", settings, is_anonymous=is_anonymous,
            )
            return

        # 4c) tg://
        if _tg_scheme_enabled and _contains_tg_scheme(ctx.normalized_text):
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id,
                "tg_scheme", settings, is_anonymous=is_anonymous,
            )
            return

        # 4e) Emails
        if _emails_enabled and _contains_email(ctx.normalized_text):
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id,
                "email", settings, is_anonymous=is_anonymous,
            )
            return

        # 5) Mentions
        if _as_bool(settings.get('mentions'), False):
            try:
                has_mention = TextUtils.contains_mention(ctx.normalized_text)
            except Exception:
                has_mention = False
            if has_mention:
                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id,
                    "mention", settings, is_anonymous=is_anonymous,
                )
                return

        # 6) Banned Words
        if _as_bool(settings.get('delete_banned_words'), False):
            banned_words = await get_banned_words_cached(chat_id)
            if banned_words:
                matched = None
                for bw in banned_words:
                    if _contains_banned_word(ctx.analysis_text, bw):
                        matched = bw
                        break
                if matched:
                    await MessageHandlers._delete_and_warn(
                        update, context, chat_id, user_id,
                        "banned_word", settings, is_anonymous=is_anonymous,
                    )
                    return

        # 7) Max Length
        try:
            max_len = int(settings.get('max_message_length', 0) or 0)
        except (TypeError, ValueError):
            max_len = 0
        if max_len > 0 and len(ctx.normalized_text) > max_len:
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id,
                "max_len", settings, is_anonymous=is_anonymous,
            )
            return

        # 8) Media
        for attr, setting_key, vtype in _MEDIA_SETTINGS_MAP:
            media = getattr(message, attr, None)
            if not media:
                continue
            if not _as_bool(settings.get(setting_key), False):
                continue
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id,
                vtype, settings, is_anonymous=is_anonymous,
            )
            return

        # 9) Translation
        translate_source = ctx.text or ctx.caption
        if translate_source and not is_anonymous:
            try:
                translated = await _detect_and_translate(
                    update, context, chat_id, user_id, translate_source,
                )
                if translated:
                    lang = await _ensure_lang(update, context)
                    await _send_translation_reply(
                        context.bot, chat_id,
                        message.message_id, translated, lang,
                        context=context,
                    )
            except Exception:
                pass

        # 10) Auto Reply
        if ctx.text:
            await MessageHandlers._process_auto_reply(
                update, context, chat_id, ctx.text, user_id,
            )

    @staticmethod
    def _get_penalty_duration(settings, violation_type):
        try:
            if violation_type in ('flood', 'antiflood'):
                raw = settings.get(
                    'antiflood_penalty_duration', _FLOOD_DEFAULT_DURATION,
                )
                return max(_FLOOD_MIN_DURATION_SEC,
                           int(raw or _FLOOD_DEFAULT_DURATION))
            if violation_type in ('night', 'night_mode'):
                raw = settings.get('night_mode_action_duration', 3600)
                return max(_FLOOD_MIN_DURATION_SEC, int(raw or 3600))
            raw = settings.get('auto_mute_duration', 3600)
            return max(_FLOOD_MIN_DURATION_SEC, int(raw or 3600))
        except (TypeError, ValueError):
            return _FLOOD_DEFAULT_DURATION

    @staticmethod
    async def _get_violation_message(violation_type, lang):
        trans_key = f"violation_{violation_type}"
        default = _DEFAULT_VIOLATION_MESSAGES.get(
            violation_type, f"🚫 {violation_type}",
        )
        return await _trans(trans_key, lang, default)

    @staticmethod
    async def _send_anonymous_warning(context, chat_id, violation_type, lang):
        try:
            vm = await MessageHandlers._get_violation_message(
                violation_type, lang,
            )
            warn_title = await _trans('violation_warning_title', lang, "⚠️")
            sent_msg = await safe_send(
                context.bot, chat_id,
                f"{warn_title}\n{vm}\n👻 <b>مشرف مجهول</b>",
                parse_mode='HTML',
            )
            if sent_msg and getattr(sent_msg, 'message_id', None):
                _spawn_delete_after_delay(
                    context.bot, chat_id, sent_msg.message_id,
                    PENALTY_MESSAGE_DELETE_DELAY, context=context,
                )
        except Exception:
            pass

    @staticmethod
    async def _send_user_warning(
        context, chat_id, user_name,
        violation_type, lang, violation_count,
    ):
        try:
            vm = await MessageHandlers._get_violation_message(
                violation_type, lang,
            )
            warn_title = await _trans('violation_warning_title', lang, "⚠️")
            count_label = await _trans('violation_count_label', lang, "📊")
            delete_notice = await _trans(
                'violation_delete_notice', lang, "⏳",
            )
            sent_msg = await safe_send(
                context.bot, chat_id,
                f"{warn_title}\n{vm}\n👤 {user_name}\n"
                f"{count_label}: {violation_count}\n{delete_notice}",
                parse_mode='HTML',
            )
            if sent_msg and getattr(sent_msg, 'message_id', None):
                _spawn_delete_after_delay(
                    context.bot, chat_id, sent_msg.message_id,
                    PENALTY_MESSAGE_DELETE_DELAY, context=context,
                )
        except Exception:
            pass

    @staticmethod
    async def _resolve_penalty(chat_id, violation_type, settings):
        """
        🟠 PERF-5 (v7.18.6): دعم dict + asyncpg.Record + MySQL Row.
        🆕 v7.18.7 FIX-4: تبسيط منطق try/except المزدوج.
        """
        penalty_rule = None
        try:
            penalty_rule = await DB.get_violation_penalty(
                chat_id, violation_type,
            )
        except Exception:
            pass

        # 🟠 PERF-5: توحيد النوع (dict دائماً)
        penalty_rule = _row_to_dict_local(penalty_rule)

        if penalty_rule:
            # 🆕 v7.18.7 FIX-4: dict يضمن .get()
            ptype = penalty_rule.get('penalty_type')
            if ptype == 'none':
                return None, 0
            if ptype in ('mute', 'ban', 'restrict', 'kick', 'warn'):
                try:
                    dur = int(
                        penalty_rule.get('duration_seconds') or 0,
                    )
                except (TypeError, ValueError):
                    dur = 0
                return ptype, dur

        if violation_type in ('flood', 'antiflood'):
            ptype = settings.get(
                'antiflood_penalty', _FLOOD_DEFAULT_PENALTY,
            )
        elif violation_type in ('night', 'night_mode'):
            ptype = settings.get('night_mode_action', 'mute')
        elif violation_type in ('violation', 'violation_penalty'):
            ptype = settings.get(
                'violation_penalty',
                settings.get('auto_penalty', 'none'),
            )
        elif violation_type == 'delete_penalty':
            ptype = settings.get('delete_penalty', 'none')
        elif violation_type == 'warn_penalty':
            ptype = settings.get('warn_penalty', 'mute')
        elif violation_type == 'postbot_pattern':
            ptype = settings.get(
                'postbot_pattern_penalty',
                settings.get('auto_penalty', 'none'),
            )
        else:
            ptype = settings.get('auto_penalty', 'none')

        if ptype == 'none' or ptype is None:
            return None, 0
        if ptype not in ('mute', 'ban', 'restrict', 'kick', 'warn'):
            ptype = 'mute'
        duration = MessageHandlers._get_penalty_duration(
            settings, violation_type,
        )
        return ptype, duration

    @staticmethod
    async def _delete_and_warn(
        update, context, chat_id, user_id,
        violation_type, settings, is_anonymous=False,
    ):
        lang = await _ensure_lang(update, context)
        message = update.effective_message
        if message is None:
            logger.warning(
                "⚠️ _delete_and_warn(%s): effective_message is None",
                violation_type,
            )
            return
        message_preview = None
        try:
            message_preview = (
                (message.text or message.caption or "").strip() or None
            )
        except Exception:
            pass
        forward_info = None
        if violation_type in ('forwarded', 'postbot_forward'):
            try:
                forward_info = extract_forward_info(message)
            except Exception:
                pass

        delete_ok = False
        try:
            if message.message_id:
                delete_ok = await _safe_delete_message(
                    context.bot, chat_id, message.message_id,
                    context=context, notify_owner=True,
                )
        except Exception as e:
            logger.error("delete exception: %s", e)
            delete_ok = False

        if not delete_ok:
            logger.error("⏭️ توقف — الحذف فشل (%s)", violation_type)
            try:
                should_notify = await _record_delete_failure(chat_id)
                if should_notify:
                    _spawn_tracked_task(
                        _notify_delete_permission_failure(context, chat_id),
                        label="delete-perm-notify",
                    )
            except Exception:
                pass
            return

        # 🆕 v7.18.5: إضافة المصدر للقائمة السوداء — فقط القنوات/المجموعات
        if _HAS_AUTO_BLOCK and violation_type in (
            'postbot_forward', 'forwarded', 'spam_score',
        ):
            try:
                _fwd = get_forward_info(message)
                _origin_type = (_fwd.get("origin_type") or "").lower()

                # 🆕 v7.18.5: لا نضيف users للقائمة السوداء
                if _origin_type in ("user", "hidden_user"):
                    logger.debug(
                        "SKIP-BLACKLIST-USER | type=%s name=%r",
                        _origin_type, _fwd.get("original_name"),
                    )
                else:
                    _source_id = (
                        _fwd.get("original_chat_id")
                        or _fwd.get("sender_chat_id")
                        or _fwd.get("original_user_id")
                    )
                    # 🆕 v7.18.5: حماية — تجاهل ID موجب
                    if _source_id is not None and int(_source_id) > 0:
                        logger.debug(
                            "SKIP-BLACKLIST-POSITIVE-ID | id=%s type=%s",
                            _source_id, _origin_type,
                        )
                    elif _source_id is not None:
                        await _add_blocked_source(
                            source_id=_source_id,
                            source_type=_origin_type or "channel",
                            source_name=_fwd.get("original_name") or "",
                            reason=f"auto:{violation_type}",
                        )
                        logger.info(
                            "📝 AUTO-ADDED-TO-BLACKLIST | "
                            "source_id=%s name=%r type=%s",
                            _source_id,
                            _fwd.get("original_name"),
                            _origin_type,
                        )
            except Exception as e:
                logger.debug("auto-add blacklist: %s", e)

        if FEATURE_LOG_DELETIONS:
            try:
                if await _can_send_log(chat_id):
                    if is_anonymous:
                        user_first = "مشرف مجهول"
                        user_username = None
                    elif update.effective_user:
                        user_first = (
                            getattr(update.effective_user, 'first_name', None)
                            or "User"
                        )
                        user_username = getattr(
                            update.effective_user, 'username', None,
                        )
                    else:
                        user_first = "Unknown"
                        user_username = None
                    log_text = _build_delete_log_text(
                        chat_id=chat_id, user_id=user_id,
                        user_first_name=user_first,
                        user_username=user_username,
                        violation_type=violation_type,
                        forward_info=forward_info,
                        message_preview=message_preview,
                        is_anonymous=is_anonymous,
                    )
                    await _dispatch_log(
                        partial(
                            notify_group_log, context, chat_id, log_text,
                        ),
                        label=f"delete-{violation_type}",
                    )
            except Exception as e:
                logger.warning("group_log spawn: %s", e)

        if (
            forward_info
            and not is_anonymous
            and _should_notify_forward(context, chat_id)
        ):
            try:
                owner_id = int(
                    getattr(CONFIG, 'PRIMARY_OWNER_ID', 0) or 0,
                )
                if owner_id:
                    _spawn_tracked_task(
                        _notify_admin_about_forward(
                            context, owner_id, forward_info,
                        ),
                        label="forward-notify",
                    )
            except Exception as e:
                logger.debug("forward notify spawn: %s", e)

        if is_anonymous:
            await MessageHandlers._send_anonymous_warning(
                context, chat_id, violation_type, lang,
            )
            return

        try:
            violation_count = await DB.increment_violation_count(
                user_id, chat_id,
            )
        except Exception:
            violation_count = 1

        penalty_type, duration_seconds = await MessageHandlers._resolve_penalty(
            chat_id, violation_type, settings,
        )

        try:
            await DB.add_admin_log(
                chat_id, context.bot.id,
                f"violation_{violation_type}", user_id,
            )
        except Exception:
            pass

        eff_user = update.effective_user
        first_name = getattr(eff_user, 'first_name', None) if eff_user else None
        user_name = escape(first_name or "User")

        await MessageHandlers._send_user_warning(
            context, chat_id, user_name,
            violation_type, lang, violation_count,
        )

        if not penalty_type:
            return

        try:
            max_strikes = int(
                settings.get('violation_strikes')
                or settings.get('max_warnings')
                or 3,
            )
        except (TypeError, ValueError):
            max_strikes = 3
        max_strikes = max(1, max_strikes)

        if violation_count < max_strikes:
            return

        success, msg = await apply_violation_penalty(
            update, context, chat_id, user_id,
            violation_type, penalty_type, duration_seconds, lang=lang,
        )
        if not success:
            return

        try:
            target_first = ""
            target_username = None
            if update.effective_user:
                target_first = update.effective_user.first_name or ""
                target_username = update.effective_user.username
            await _notify_group_log_penalty(
                context,
                chat_id=chat_id, target_user_id=user_id,
                target_first_name=target_first,
                target_username=target_username,
                penalty_type=penalty_type,
                duration_seconds=duration_seconds,
                source="auto", violation_type=violation_type,
            )
        except Exception:
            pass

        try:
            msg_prefix = await _trans(
                'violation_penalty_applied', lang, "🚨 {msg}",
            )
            sent_penalty = await safe_send(
                context.bot, chat_id, _fmt(msg_prefix, msg=msg),
                parse_mode='HTML',
            )
            if (sent_penalty is not None
                    and getattr(sent_penalty, 'message_id', None)):
                _spawn_delete_after_delay(
                    context.bot, chat_id, sent_penalty.message_id,
                    PENALTY_MESSAGE_DELETE_DELAY, context=context,
                )
            # ✅ v7.18.6-PERF-4-RESTORED: السلوك الأصلي محفوظ
            await DB.reset_violation_count(user_id, chat_id)
        except Exception:
            pass

    @staticmethod
    async def _process_auto_reply(update, context, chat_id, text, user_id=None):
        try:
            ars = await get_auto_reply_settings_cached(chat_id)
            if not _as_bool(ars.get('enabled', False), False):
                return False
            if _as_bool(ars.get('ignore_bots', True), True):
                eff_user = getattr(update, 'effective_user', None)
                if eff_user and getattr(eff_user, 'is_bot', False):
                    return False
            if _as_bool(ars.get('only_admins', False), False):
                if not await is_authorized_in_group(
                    context.bot, chat_id, user_id or 0,
                ):
                    return False
            reply = await DB.get_auto_reply(text, chat_id)
            if reply:
                reply_text = reply.get('reply', '') or ''
                if reply_text:
                    await safe_send(context.bot, chat_id, reply_text)
                await _increment_usage_async(chat_id, text)
                return True
            file_reply = get_reply_from_file(text)
            if file_reply:
                await safe_send(context.bot, chat_id, file_reply)
                return True
            return False
        except Exception as e:
            logger.error("❌ auto_reply: %s", e)
            return False

    @staticmethod
    async def handle_private(update, context):
        try:
            if not update.effective_user:
                return
            user_id = update.effective_user.id
            state = StateManager.get(user_id)
            if state is None:
                return

            handler_name = MessageHandlers._PRIVATE_HANDLERS_MAP.get(state)
            if not handler_name:
                for candidate in (
                    getattr(state, 'name', None),
                    getattr(state, 'value', None),
                    str(state),
                ):
                    if candidate is None:
                        continue
                    handler_name = MessageHandlers._PRIVATE_HANDLERS_MAP.get(
                        candidate,
                    )
                    if handler_name:
                        break
            if not handler_name:
                return

            handler = getattr(MessageHandlers, handler_name, None)
            if handler is None:
                logger.warning(
                    "⚠️ _PRIVATE_HANDLERS_MAP يشير إلى %s غير موجود",
                    handler_name,
                )
                return

            if _accepts_state_arg(handler, handler_name):
                await handler(update, context, state)
            else:
                await handler(update, context)
        except Exception:
            logger.exception("handle_private error")

    @staticmethod
    async def handle_cancel(update, context):
        try:
            if not update.effective_user:
                return
            user_id = update.effective_user.id
            StateManager.clear(user_id)
            context.user_data.pop('ban_chat', None)
            lang = await _ensure_lang(update, context)
            msg = await _trans(
                'action_cancelled', lang, "✅ تم إلغاء العملية.",
            )
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.debug("handle_cancel: %s", e)

    @staticmethod
    async def _validate_and_get_word(update, context, lang):
        message = update.effective_message
        if not message or not message.text:
            return None, True
        word = (message.text or "").strip()
        if not word:
            return None, True
        if len(word) < _BAN_WORD_MIN_LEN or len(word) > _BAN_WORD_MAX_LEN:
            user_id = update.effective_user.id
            try:
                err = await _trans(
                    'ban_word_invalid_length',
                    lang,
                    f"❌ يجب أن تكون الكلمة بين {_BAN_WORD_MIN_LEN} "
                    f"و {_BAN_WORD_MAX_LEN} حرف.",
                )
                await safe_send(context.bot, user_id, err)
            except Exception:
                pass
            return None, True
        return word, False

    @staticmethod
    async def _apply_ban_add_rate_limit(update, context, lang) -> bool:
        """
        🆕 v7.18.7 FIX-1: args معكوسة في _check_flood.

        _check_flood signature: (chat_id, user_id, max_messages, window_sec)

        قبل v7.18.7 (خطأ):
            _check_flood(user_id, -1, ...)  ← كان يخلط المعاملين

        بعد v7.18.7 (صحيح):
            _check_flood(-1, user_id, ...)
            - chat_id=-1 → يميّز rate-limiting القائمة السوداء
              عن rate-limiting الرسائل في المجموعات
            - user_id=user_id → مفتاح فريد لكل مستخدم
        """
        if not _BAN_ADD_RATE_LIMIT:
            return False
        try:
            user_id = update.effective_user.id
            exceeded = await _check_flood(
                -1, user_id, _BAN_ADD_RATE_MAX, _BAN_ADD_RATE_WINDOW,
            )
            if exceeded:
                msg = await _trans(
                    'ban_word_rate_limited',
                    lang,
                    "⏱️ تمهّل قليلاً — تجاوزت الحد المسموح.",
                )
                try:
                    await safe_send(context.bot, user_id, msg)
                except Exception:
                    pass
                return True
        except Exception as e:
            logger.debug("ban_add rate limit: %s", e)
        return False

    @staticmethod
    async def _finalize_ban_add(context, user_id, success: bool):
        if not success:
            return
        try:
            StateManager.clear(user_id)
        except Exception:
            pass
        try:
            context.user_data.pop('ban_chat', None)
        except Exception:
            pass

    @staticmethod
    async def handle_add_banned_word(update, context):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return
        message = update.effective_message
        if not message or not message.text:
            return
        lang = await _ensure_lang(update, context)

        chat_id = context.user_data.get('ban_chat')
        if chat_id is None:
            StateManager.clear(user_id)
            return

        if chat_id == -1:
            return await MessageHandlers.handle_add_global_banned_word(
                update, context,
            )

        try:
            is_admin = await _check_admin_in_chat(context, chat_id, user_id)
        except Exception:
            is_admin = False
        if not is_admin:
            try:
                msg = await _trans(
                    'ban_add_no_perms', lang,
                    "❌ لم تعد مشرفاً في هذه المجموعة.",
                )
                await safe_send(context.bot, user_id, msg)
            except Exception:
                pass
            StateManager.clear(user_id)
            context.user_data.pop('ban_chat', None)
            return

        if await MessageHandlers._apply_ban_add_rate_limit(
            update, context, lang,
        ):
            return

        word, err = await MessageHandlers._validate_and_get_word(
            update, context, lang,
        )
        if err:
            return

        success = False
        try:
            added = await DB.add_banned_word(chat_id, word, user_id)
            if added:
                await _invalidate_banned_words_cache(chat_id)
                tmpl = await _trans(
                    'ban_word_added', lang,
                    "✅ تمت إضافة الكلمة: <code>{word}</code>",
                )
                await safe_send(
                    context.bot, user_id,
                    _fmt(tmpl, word=escape(word)),
                    parse_mode='HTML',
                )
                success = True
            else:
                msg = await _trans(
                    'ban_word_duplicate', lang,
                    "❌ الكلمة موجودة مسبقاً.",
                )
                await safe_send(context.bot, user_id, msg)
                success = True
        except Exception as e:
            logger.error("add_banned_word(%s): %s", chat_id, e)
            try:
                msg = await _trans(
                    'ban_word_add_failed', lang,
                    "❌ فشل الحفظ — حاول مجدداً.",
                )
                await safe_send(context.bot, user_id, msg)
            except Exception:
                pass
        finally:
            await MessageHandlers._finalize_ban_add(
                context, user_id, success,
            )

    @staticmethod
    async def handle_add_global_banned_word(update, context):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return
        lang = await _ensure_lang(update, context)

        try:
            is_dev = False
            for attr in ('is_developer', 'is_dev', 'is_owner'):
                fn = getattr(CONFIG, attr, None)
                if callable(fn) and fn(user_id):
                    is_dev = True
                    break
            if not is_dev and user_id == getattr(CONFIG, 'PRIMARY_OWNER_ID', -1):
                is_dev = True
        except Exception:
            is_dev = False

        if not is_dev:
            try:
                msg = await _trans(
                    'ban_add_no_perms', lang,
                    "❌ صلاحيات غير كافية.",
                )
                await safe_send(context.bot, user_id, msg)
            except Exception:
                pass
            StateManager.clear(user_id)
            context.user_data.pop('ban_chat', None)
            return

        if await MessageHandlers._apply_ban_add_rate_limit(
            update, context, lang,
        ):
            return

        word, err = await MessageHandlers._validate_and_get_word(
            update, context, lang,
        )
        if err:
            return

        success = False
        try:
            added = await DB.add_banned_word(-1, word, user_id)
            if added:
                await _invalidate_banned_words_cache(None)
                tmpl = await _trans(
                    'ban_word_added_global', lang,
                    "✅ تمت إضافة الكلمة العالمية: <code>{word}</code>",
                )
                await safe_send(
                    context.bot, user_id,
                    _fmt(tmpl, word=escape(word)),
                    parse_mode='HTML',
                )
                success = True
            else:
                msg = await _trans(
                    'ban_word_duplicate', lang,
                    "❌ الكلمة موجودة مسبقاً.",
                )
                await safe_send(context.bot, user_id, msg)
                success = True
        except Exception as e:
            logger.error("add_global_banned_word: %s", e)
            try:
                msg = await _trans(
                    'ban_word_add_failed', lang,
                    "❌ فشل الحفظ — حاول مجدداً.",
                )
                await safe_send(context.bot, user_id, msg)
            except Exception:
                pass
        finally:
            await MessageHandlers._finalize_ban_add(
                context, user_id, success,
            )

    @staticmethod
    async def handle_remove_banned_word(update, context):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return
        message = update.effective_message
        if not message or not message.text:
            return
        lang = await _ensure_lang(update, context)

        chat_id = context.user_data.get('ban_chat')
        if chat_id is None:
            StateManager.clear(user_id)
            return

        if chat_id == -1:
            return await MessageHandlers.handle_remove_global_banned_word(
                update, context,
            )

        try:
            is_admin = await _check_admin_in_chat(context, chat_id, user_id)
        except Exception:
            is_admin = False
        if not is_admin:
            try:
                msg = await _trans(
                    'ban_add_no_perms', lang,
                    "❌ لم تعد مشرفاً في هذه المجموعة.",
                )
                await safe_send(context.bot, user_id, msg)
            except Exception:
                pass
            StateManager.clear(user_id)
            context.user_data.pop('ban_chat', None)
            return

        if await MessageHandlers._apply_ban_add_rate_limit(
            update, context, lang,
        ):
            return

        word, err = await MessageHandlers._validate_and_get_word(
            update, context, lang,
        )
        if err:
            return

        success = False
        try:
            removed = False
            for method_name in (
                'remove_banned_word', 'delete_banned_word',
                'remove_banned_word_by_text',
            ):
                fn = getattr(DB, method_name, None)
                if not callable(fn):
                    continue
                try:
                    result = fn(chat_id, word)
                    if asyncio.iscoroutine(result):
                        result = await result
                    removed = bool(result)
                    break
                except Exception as e:
                    logger.debug("DB.%s failed: %s", method_name, e)
                    continue

            if removed:
                await _invalidate_banned_words_cache(chat_id)
                tmpl = await _trans(
                    'ban_word_removed', lang,
                    "✅ تمت إزالة الكلمة: <code>{word}</code>",
                )
                await safe_send(
                    context.bot, user_id,
                    _fmt(tmpl, word=escape(word)),
                    parse_mode='HTML',
                )
                success = True
            else:
                msg = await _trans(
                    'ban_word_not_found', lang,
                    "❌ الكلمة غير موجودة في القائمة.",
                )
                await safe_send(context.bot, user_id, msg)
                success = True
        except Exception as e:
            logger.error("remove_banned_word(%s): %s", chat_id, e)
            try:
                msg = await _trans(
                    'ban_word_remove_failed', lang,
                    "❌ فشلت الإزالة — حاول مجدداً.",
                )
                await safe_send(context.bot, user_id, msg)
            except Exception:
                pass
        finally:
            await MessageHandlers._finalize_ban_add(
                context, user_id, success,
            )

    @staticmethod
    async def handle_remove_global_banned_word(update, context):
        user_id = update.effective_user.id if update.effective_user else None
        if not user_id:
            return
        lang = await _ensure_lang(update, context)

        try:
            is_dev = False
            for attr in ('is_developer', 'is_dev', 'is_owner'):
                fn = getattr(CONFIG, attr, None)
                if callable(fn) and fn(user_id):
                    is_dev = True
                    break
            if not is_dev and user_id == getattr(CONFIG, 'PRIMARY_OWNER_ID', -1):
                is_dev = True
        except Exception:
            is_dev = False

        if not is_dev:
            try:
                msg = await _trans(
                    'ban_add_no_perms', lang,
                    "❌ صلاحيات غير كافية.",
                )
                await safe_send(context.bot, user_id, msg)
            except Exception:
                pass
            StateManager.clear(user_id)
            context.user_data.pop('ban_chat', None)
            return

        if await MessageHandlers._apply_ban_add_rate_limit(
            update, context, lang,
        ):
            return

        word, err = await MessageHandlers._validate_and_get_word(
            update, context, lang,
        )
        if err:
            return

        success = False
        try:
            removed = False
            for method_name in (
                'remove_banned_word', 'delete_banned_word',
                'remove_banned_word_by_text',
            ):
                fn = getattr(DB, method_name, None)
                if not callable(fn):
                    continue
                try:
                    result = fn(-1, word)
                    if asyncio.iscoroutine(result):
                        result = await result
                    removed = bool(result)
                    break
                except Exception:
                    continue

            if removed:
                await _invalidate_banned_words_cache(None)
                tmpl = await _trans(
                    'ban_word_removed_global', lang,
                    "✅ تمت إزالة الكلمة العالمية: <code>{word}</code>",
                )
                await safe_send(
                    context.bot, user_id,
                    _fmt(tmpl, word=escape(word)),
                    parse_mode='HTML',
                )
                success = True
            else:
                msg = await _trans(
                    'ban_word_not_found', lang,
                    "❌ الكلمة غير موجودة في القائمة.",
                )
                await safe_send(context.bot, user_id, msg)
                success = True
        except Exception as e:
            logger.error("remove_global_banned_word: %s", e)
            try:
                msg = await _trans(
                    'ban_word_remove_failed', lang,
                    "❌ فشلت الإزالة — حاول مجدداً.",
                )
                await safe_send(context.bot, user_id, msg)
            except Exception:
                pass
        finally:
            await MessageHandlers._finalize_ban_add(
                context, user_id, success,
            )

    @staticmethod
    async def handle_service(update, context):
        if not update.effective_chat or not update.effective_message:
            return
        chat_id = update.effective_chat.id
        message = update.effective_message
        is_service = any([
            message.new_chat_members,
            message.left_chat_member,
            message.new_chat_title,
            message.new_chat_photo,
            message.delete_chat_photo,
            message.pinned_message,
            getattr(message, 'video_chat_started', None),
            getattr(message, 'video_chat_ended', None),
            getattr(message, 'video_chat_scheduled', None),
            getattr(message, 'video_chat_participants_invited', None),
            getattr(message, 'forum_topic_created', None),
            getattr(message, 'forum_topic_closed', None),
            getattr(message, 'forum_topic_reopened', None),
            getattr(message, 'general_forum_topic_hidden', None),
            getattr(message, 'general_forum_topic_unhidden', None),
        ])
        if not is_service:
            return
        try:
            settings = await get_security_settings_cached(chat_id)
            if _as_bool(settings.get('delete_service'), False):
                await _safe_delete_message(
                    context.bot, chat_id, message.message_id, context=context,
                )
        except Exception:
            pass

    @staticmethod
    async def handle_join_request(update, context):
        if not update.effective_chat or not update.effective_user:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        settings = await get_security_settings_cached(chat_id)
        if _as_bool(settings.get('auto_reject_join'), False):
            try:
                await asyncio.sleep(0.05)
                await context.bot.decline_chat_join_request(chat_id, user_id)
                return
            except Exception as e:
                logger.warning("decline join: %s", e)
        if _as_bool(settings.get('auto_approve_join'), False):
            try:
                await asyncio.sleep(0.05)
                await context.bot.approve_chat_join_request(chat_id, user_id)
            except Exception as e:
                logger.warning("approve join: %s", e)


# ═══════════════════════════════════════════════════════════════════
# 🆕 v7.18.3: /autoblocked command
# ═══════════════════════════════════════════════════════════════════

async def handle_autoblocked_command(update, context):
    """🆕 v7.18.3: عرض / إدارة القائمة السوداء التلقائية"""
    if not update.effective_user or not update.effective_message:
        return
    user_id = update.effective_user.id
    owner_id = int(getattr(CONFIG, 'PRIMARY_OWNER_ID', 0) or 0)
    if user_id != owner_id:
        return

    if not _HAS_AUTO_BLOCK:
        await safe_send(
            context.bot, update.effective_chat.id,
            "❌ نظام auto-block غير مفعّل",
        )
        return

    args = list(context.args or [])
    chat_id = update.effective_chat.id

    if args and args[0].lower() in ("remove", "del", "delete") and len(args) > 1:
        try:
            src_id = int(args[1])
            ok = await _remove_blocked_source(src_id)
            if ok:
                await safe_send(
                    context.bot, chat_id,
                    f"✅ أُزيل المصدر: <code>{src_id}</code>",
                    parse_mode='HTML',
                )
            else:
                await safe_send(
                    context.bot, chat_id,
                    f"⚠️ لم يُوجَد: <code>{src_id}</code>",
                    parse_mode='HTML',
                )
        except (ValueError, TypeError):
            await safe_send(
                context.bot, chat_id,
                "❌ استخدام: <code>/autoblocked remove ID</code>",
                parse_mode='HTML',
            )
        return

    sources = await _list_blocked_sources(limit=50)
    if not sources:
        await safe_send(
            context.bot, chat_id,
            "✨ القائمة السوداء التلقائية فارغة",
        )
        return

    lines = [
        "🚫 <b>المصادر المحجوبة تلقائياً</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    for s in sources:
        try:
            sid = s.get('source_id')
            name = str(s.get('source_name') or '')[:30]
            hits = s.get('hit_count', 0)
            stype = s.get('source_type', '?')
            reason = str(s.get('reason', ''))[:20]
            lines.append(
                f"• <code>{sid}</code> "
                f"<b>{escape(name)}</b> "
                f"({hits}×, {stype}, {reason})"
            )
        except Exception:
            continue
    lines.append("")
    lines.append(
        "🗑️ للحذف: <code>/autoblocked remove ID</code>"
    )
    await safe_send(
        context.bot, chat_id,
        "\n".join(lines),
        parse_mode='HTML',
    )


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

__all__ = [
    "MessageHandlers", "GroupRateLimiterManager",
    "clear_lang_cache", "get_security_settings_cached",
    "get_auto_reply_settings_cached", "invalidate_security_cache",
    "invalidate_auto_reply_cache", "apply_violation_penalty",
    "is_forwarded", "extract_forward_info", "get_forward_detection_reason",
    "get_forward_info",
    "notify_group_log", "shutdown_log_dispatcher", "shutdown_delete_tasks",
    "shutdown_bg_tasks", "register_shutdown_handlers",
    "_lazy_init_columns", "_reset_shutdown_for_tests",
    "FEATURE_LOG_DELETIONS", "FEATURE_LOG_PENALTIES",
    "FEATURE_LOG_GIFTS", "FEATURE_LOG_ADMIN_CHANGES",
    "SPAM_SCORE_THRESHOLD", "POSTBOT_AUTO_BLOCK_CONFIDENCE",
    "SPAM_HARD_THRESHOLD", "SPAM_CRITICAL_THRESHOLD",
    "DEBUG_DIAG", "DEBUG_SPAM", "ANTIEVASION_COMPACT_WORDS",
    "_MessageContext", "_normalize_text",
    "_strip_combining_marks", "_deleet", "_apply_homoglyphs_safe",
    "_strip_emoji_for_domain", "_has_hidden_chars", "_merge_split_urls",
    "_extract_entity_urls", "_has_link_entity", "_extract_url_from_button",
    "_button_is_external", "_extract_button_context",
    "_extract_vcard_urls", "_extract_venue_url", "_extract_poll_text",
    "_get_message_button_data", "_get_message_button_texts",
    "_get_message_analysis_text",
    "_has_domain_pattern", "_contains_link_enhanced", "_contains_email",
    "_contains_at_channel", "_contains_tg_scheme",
    "_has_button_link", "_extract_button_link_urls",
    "_extract_spam_words", "_count_unique_matches", "_count_text_urls",
    "_compute_spam_score", "_is_postbot_pattern",
    "_postbot_pattern_confidence",
    "analyze_message", "get_spam_diagnostics", "is_spam",
    "is_high_confidence_spam", "is_critical_spam",
    "should_ignore_as_low_signal",
    "_as_bool", "_env_flag", "_check_flood", "_cleanup_flood_tracker",
    "_flood_tracker_stats", "_flood_tracker", "_flood_lock",
    "_invalidate_banned_words_cache", "_check_admin_in_chat",
    "_private_handler_signature_cache", "_accepts_state_arg",
    "_notify_dev_log", "_safe_delete_message",
    "_invalidate_after_channel_change",
    "_FLOOD_TRACKER_MAX_KEYS", "_FLOOD_TRACKER_STALE_SEC",
    "_FLOOD_DEFAULT_MESSAGES", "_FLOOD_DEFAULT_WINDOW",
    "_FLOOD_DEFAULT_PENALTY", "_FLOOD_DEFAULT_DURATION",
    "_BAN_WORD_MIN_LEN", "_BAN_WORD_MAX_LEN",
    "_BAN_ADD_RATE_LIMIT", "_BAN_ADD_RATE_MAX", "_BAN_ADD_RATE_WINDOW",
    "_DEFAULT_VIOLATION_MESSAGES",
    "_notify_delete_permission_failure", "analyze_sentiment",
    "_MULTILAYER_ENABLED", "_HAS_MULTILAYER",
    "analyze_message_full", "analyze_message_full_async",
    "SpamVerdict",
    "_FORCE_DELETE_BUTTON_LINKS",
    "_FORCE_DELETE_POSTBOT_FORWARDS",
    "_is_postbot_forward", "_is_postbot_channel_name",
    "_POSTBOT_CHANNEL_NAMES", "_POSTBOT_CHANNEL_IDS",
    "_POSTBOT_RAW_IDS",
    "_POSTBOT_NAME_REGEX",
    "_normalize_tg_id",
    "_HAS_AUTO_BLOCK",
    "handle_autoblocked_command",

    # 🆕 v7.18.6 — PERF caches + invalidation
    "_GROUP_LOG_CHANNEL_CACHE_TTL",
    "_GROUP_LOG_CHANNEL_CACHE_MAX",
    "_group_log_channel_cache",
    "_get_group_log_channel_cached",
    "_invalidate_group_log_cache",
    "_SEC_SETTINGS_LOCAL_TTL",
    "_SEC_SETTINGS_LOCAL_MAX",
    "_sec_settings_local_cache",
    "_invalidate_sec_settings_local",
    "_ADMIN_CHECK_CACHE_TTL",
    "_ADMIN_CHECK_CACHE_MAX",
    "_admin_check_cache",
    "_invalidate_admin_check_cache",
    "_row_to_dict_local",
    "_prune_perf_caches",

    # 🆕 v7.18.7 — FIX caches / helpers
    "_PRIVATE_SIG_CACHE_MAX",

    # 🆕 v7.18.8 — ASYNC-NATIVE integration
    "_run_multilayer_analysis",
    "_ANALYZE_SLOW_THRESHOLD_SEC",
]