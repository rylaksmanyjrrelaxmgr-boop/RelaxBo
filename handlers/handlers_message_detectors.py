#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_message_detectors.py
===============================================================================
🛡️ Relax Manager — Advanced Spam / Anti-Evasion Detection Engine
Version: 4.0.9 (ARABIC-SHORT-WHITELIST)

🆕 v4.0.9 — إصلاح الرسائل العربية القصيرة (CRITICAL):
    🔴 FIX-AR-1: _ARABIC_GREETINGS whitelist — تحيات عربية (لن تُحذف)
    🔴 FIX-AR-2: _looks_like_normal_conversation — تحسين كشف العربية
    🔴 FIX-AR-3: analyze_context_window — استثناء النصوص العربية القصيرة
    🟡 FIX-AR-4: _compute_spam_score — early-exit للنصوص العربية القصيرة
    🟡 FIX-AR-5: FINAL_THRESHOLD قابل للضبط عبر ENV
    🟢 FIX-AR-6: _is_arabic_dominant() helper جديدة
    🟢 FIX-AR-7: توثيق التغييرات

🆕 v4.0.8.1 — إصلاح توثيقي:
    🟡 FIX-DOC-1: Load Beacon — "14 Layers" → "15 Layers"

🆕 v4.0.8 — إصلاحات v4.0.7:
    🔴 FIX-A: _run_in_pool يقبل **kwargs
    🟠 FIX-B: install_default_executor — إصلاح API deprecated
    🟠 FIX-C: NSFW lazy load — تقليل احتجاز pool workers
    🟠 FIX-D: _URL_SIGNATURES — TLD-aware regex
    🟠 FIX-E: _EMOJI_STRIP_RE — ZWJ sequences + modifiers
    🟡 FIX-G: _analyze_message_full_async — تعليق دقيق
    🟡 FIX-I: type annotations لـ_se_last_failure_ts
    🟡 FIX-J: Lock بدل RLock لـ_BEHAVIOR_LOCK
    🟡 FIX-K: _context_buffers معرّف قبل cleanup_old_data
    🟡 FIX-N: shutdown_default_executor() helper
    🟡 FIX-O: _domain_rep_cache_get يعيد نسخة
    🟡 FIX-R: _run_in_pool timeout اختياري

🆕 v4.0.7: FIX-AA..II (FULL-AUDIT-V3)
🆕 v4.0.5/4.0.6: FIX-R,S,T,U,V,W,X (SHUTDOWN + ASYNC hardening)
🆕 v4.0.4: FIX-A..Q
===============================================================================
"""

from __future__ import annotations

import asyncio
import base64
import codecs
import concurrent.futures
import datetime
import functools
import html
import io
import logging
import math
import os
import re
import tempfile
import threading
import time
import unicodedata
import urllib.parse
from collections import Counter, defaultdict, deque, OrderedDict
from dataclasses import dataclass, field
from typing import (
    Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple,
)

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse  # type: ignore


# =============================================================================
# LOAD BEACON
# =============================================================================

logger = logging.getLogger(__name__)

_DETECTORS_VERSION = "4.0.9 ARABIC-SHORT-WHITELIST"
_DETECTORS_VERSION_CLEAN = "4.0.9"


def _version_semver(version: str) -> str:
    m = re.match(r"(\d+\.\d+\.\d+)", str(version or ""))
    return m.group(1) if m else str(version or "0.0.0")


# =============================================================================
# ENVIRONMENT
# =============================================================================

def _env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
        return True
    if value in {"0", "false", "no", "n", "off", "disable", "disabled"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


DEBUG_DIAG = _env_bool("DEBUG_DIAG", False)
DEBUG_SPAM = _env_bool("DEBUG_SPAM", False)

TEXT_LAYER_ENABLED = _env_bool("TEXT_LAYER_ENABLED", True)
OCR_LAYER_ENABLED = _env_bool("OCR_LAYER_ENABLED", True)
AUDIO_LAYER_ENABLED = _env_bool("AUDIO_LAYER_ENABLED", True)
URL_LAYER_ENABLED = _env_bool("URL_LAYER_ENABLED", True)
METADATA_LAYER_ENABLED = _env_bool("METADATA_LAYER_ENABLED", True)
OBFUSCATION_LAYER_ENABLED = _env_bool("OBFUSCATION_LAYER_ENABLED", True)
BEHAVIORAL_LAYER_ENABLED = _env_bool("BEHAVIORAL_LAYER_ENABLED", True)
VIDEO_LAYER_ENABLED = _env_bool("VIDEO_LAYER_ENABLED", True)
NSFW_LAYER_ENABLED = _env_bool("NSFW_LAYER_ENABLED", True)
STICKER_LAYER_ENABLED = _env_bool("STICKER_LAYER_ENABLED", True)
REACTIONS_LAYER_ENABLED = _env_bool("REACTIONS_LAYER_ENABLED", True)
CONTEXT_LAYER_ENABLED = _env_bool("CONTEXT_LAYER_ENABLED", True)
CIPHER_LAYER_ENABLED = _env_bool("CIPHER_LAYER_ENABLED", True)
STEGO_LAYER_ENABLED = _env_bool("STEGO_LAYER_ENABLED", True)
DOMAIN_REP_LAYER_ENABLED = _env_bool("DOMAIN_REP_LAYER_ENABLED", True)

ASYNC_NETWORK_ENABLED = _env_bool("ASYNC_NETWORK_ENABLED", True)
ASYNC_NETWORK_TIMEOUT = _env_float("ASYNC_NETWORK_TIMEOUT", 5.0)

ANTIEVASION_ENTITY_LINK = _env_bool("ANTIEVASION_ENTITY_LINK", True)
ANTIEVASION_BUTTON_LINK = _env_bool("ANTIEVASION_BUTTON_LINK", True)
ANTIEVASION_SCHEMELESS_URL = _env_bool("ANTIEVASION_SCHEMELESS_URL", True)
ANTIEVASION_HOMOGLYPH = _env_bool("ANTIEVASION_HOMOGLYPH", True)
ANTIEVASION_COMBINING = _env_bool("ANTIEVASION_COMBINING", True)
ANTIEVASION_COMPACT_WORDS = _env_bool("ANTIEVASION_COMPACT_WORDS", True)
ANTIEVASION_EMOJI_SEPARATOR = _env_bool("ANTIEVASION_EMOJI_SEPARATOR", True)
ANTIEVASION_BUTTON_WEBAPP = _env_bool("ANTIEVASION_BUTTON_WEBAPP", True)
ANTIEVASION_BUTTON_LOGINURL = _env_bool("ANTIEVASION_BUTTON_LOGINURL", True)
ANTIEVASION_LEETSPEAK = _env_bool("ANTIEVASION_LEETSPEAK", True)
ANTIEVASION_TG_SCHEME = _env_bool("ANTIEVASION_TG_SCHEME", True)
ANTIEVASION_AT_CHANNEL = _env_bool("ANTIEVASION_AT_CHANNEL", True)
ANTIEVASION_EMAIL = _env_bool("ANTIEVASION_EMAIL", True)
ANTIEVASION_PUNYCODE = _env_bool("ANTIEVASION_PUNYCODE", True)
ANTIEVASION_IPV4_SCHEMELESS = _env_bool("ANTIEVASION_IPV4_SCHEMELESS", True)
ANTIEVASION_MULTILINE_URL = _env_bool("ANTIEVASION_MULTILINE_URL", True)
ANTIEVASION_VENUE_VCARD = _env_bool("ANTIEVASION_VENUE_VCARD", True)
ANTIEVASION_POLL = _env_bool("ANTIEVASION_POLL", True)
ANTIEVASION_EMOJI_IN_DOMAIN = _env_bool("ANTIEVASION_EMOJI_IN_DOMAIN", True)
ANTIEVASION_UNICODE_DOTS = _env_bool("ANTIEVASION_UNICODE_DOTS", True)
ANTIEVASION_EXTENDED_COMBINING = _env_bool("ANTIEVASION_EXTENDED_COMBINING", True)
ANTIEVASION_EXTRA_SCRIPTS = _env_bool("ANTIEVASION_EXTRA_SCRIPTS", True)
ANTIEVASION_ALT_SCHEMES = _env_bool("ANTIEVASION_ALT_SCHEMES", True)
ANTIEVASION_RANDOM_DOMAIN = _env_bool("ANTIEVASION_RANDOM_DOMAIN", True)

# 🆕 v4.0.9: whitelist للرسائل العربية القصيرة
ARABIC_SHORT_WHITELIST_ENABLED = _env_bool(
    "ARABIC_SHORT_WHITELIST_ENABLED", True
)
ARABIC_SHORT_MAX_CHARS = _env_int("ARABIC_SHORT_MAX_CHARS", 40)
ARABIC_SHORT_MAX_WORDS = _env_int("ARABIC_SHORT_MAX_WORDS", 6)
ARABIC_DOMINANCE_RATIO = _env_float("ARABIC_DOMINANCE_RATIO", 0.6)

SAFE_BROWSING_API_KEY = os.getenv("SAFE_BROWSING_API_KEY", "")
URL_ENRICH_ENABLED = _env_bool("URL_ENRICH_ENABLED", True)
URL_EXPAND_TIMEOUT = _env_int("URL_EXPAND_TIMEOUT", 5)
URL_EXPAND_CONNECT_TIMEOUT = _env_float("URL_EXPAND_CONNECT_TIMEOUT", 3.0)
URL_EXPAND_READ_TIMEOUT = _env_float("URL_EXPAND_READ_TIMEOUT", 5.0)
URL_EXPAND_MAX_HOPS = _env_int("URL_EXPAND_MAX_HOPS", 5)
URL_ENRICH_MAX_URLS = _env_int("URL_ENRICH_MAX_URLS", 5)
WHOIS_ENABLED = _env_bool("WHOIS_ENABLED", True)
WHOIS_NEW_DOMAIN_DAYS = _env_int("WHOIS_NEW_DOMAIN_DAYS", 30)

AUDIO_USE_WHISPER = _env_bool("AUDIO_USE_WHISPER", False)
AUDIO_NOISE_REDUCE = _env_bool("AUDIO_NOISE_REDUCE", True)

VIDEO_MAX_FRAMES = _env_int("VIDEO_MAX_FRAMES", 8)
VIDEO_FRAME_INTERVAL_SEC = _env_float("VIDEO_FRAME_INTERVAL_SEC", 2.0)

NSFW_MODEL_ENABLED = _env_bool("NSFW_MODEL_ENABLED", False)
NSFW_THRESHOLD = _env_float("NSFW_THRESHOLD", 0.65)
NSFW_SIGHTENGINE_MAX_BYTES = _env_int("NSFW_SIGHTENGINE_MAX_BYTES", 10 * 1024 * 1024)

NORMALIZE_CACHE_MAX = _env_int("NORMALIZE_CACHE_MAX", 512)

SE_CIRCUIT_FAILURE_THRESHOLD = _env_int("SE_CIRCUIT_FAILURE_THRESHOLD", 5)
SE_CIRCUIT_OPEN_SEC = _env_float("SE_CIRCUIT_OPEN_SEC", 60.0)

POOL_TASK_TIMEOUT = _env_float("POOL_TASK_TIMEOUT", 60.0)


# =============================================================================
# SHARED THREAD POOL
# =============================================================================

_THREAD_POOL_EXECUTOR: Optional[concurrent.futures.ThreadPoolExecutor] = None
_THREAD_POOL_LOCK = threading.Lock()
_POOL_MAX_WORKERS = _env_int("DETECTOR_POOL_WORKERS", 8)


def _get_shared_pool() -> concurrent.futures.ThreadPoolExecutor:
    global _THREAD_POOL_EXECUTOR
    if _THREAD_POOL_EXECUTOR is None:
        with _THREAD_POOL_LOCK:
            if _THREAD_POOL_EXECUTOR is None:
                _THREAD_POOL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                    max_workers=_POOL_MAX_WORKERS,
                    thread_name_prefix="detector-io",
                )
                logger.debug(
                    "✅ detectors shared pool created (workers=%d)",
                    _POOL_MAX_WORKERS,
                )
    return _THREAD_POOL_EXECUTOR


def _shutdown_shared_pool() -> None:
    """إغلاق thread pool. idempotent — آمن للاستدعاء المتكرر."""
    global _THREAD_POOL_EXECUTOR
    with _THREAD_POOL_LOCK:
        if _THREAD_POOL_EXECUTOR is None:
            return
        pool = _THREAD_POOL_EXECUTOR
        _THREAD_POOL_EXECUTOR = None
    try:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)
        logger.info("✅ detectors shared pool: shutdown complete")
    except Exception as _e:
        logger.debug("_shutdown_shared_pool: %s", _e)


async def _run_in_pool(
    fn: Callable[..., Any],
    *args: Any,
    timeout: Optional[float] = None,
    **kwargs: Any,
) -> Any:
    """
    ✅ v4.0.8 FIX-A: يدعم keyword arguments عبر functools.partial.
    ✅ v4.0.8 FIX-R: timeout اختياري (افتراضي POOL_TASK_TIMEOUT).
    """
    if kwargs:
        fn = functools.partial(fn, **kwargs)

    loop = asyncio.get_running_loop()
    pool = _get_shared_pool()

    if timeout is None:
        timeout = POOL_TASK_TIMEOUT

    fut = loop.run_in_executor(pool, fn, *args)
    if timeout and timeout > 0:
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "_run_in_pool: timeout after %.1fs — fn=%s",
                timeout, getattr(fn, "__name__", repr(fn)),
            )
            raise
    return await fut


def install_default_executor(loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
    """
    ✅ v4.0.8 FIX-B: إصلاح asyncio.get_event_loop() deprecated.
    """
    try:
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                try:
                    policy = asyncio.get_event_loop_policy()
                    loop = policy.get_event_loop()
                except Exception as exc:
                    logger.warning(
                        "install_default_executor: no loop available — %r",
                        exc,
                    )
                    return

        pool = _get_shared_pool()
        loop.set_default_executor(pool)
        logger.info(
            "✅ detectors shared pool installed as default executor "
            "(workers=%d)",
            _POOL_MAX_WORKERS,
        )
    except Exception as exc:
        logger.warning("install_default_executor: %r", exc)


async def shutdown_default_executor(
    loop: Optional[asyncio.AbstractEventLoop] = None,
    timeout: float = 3.0,
) -> None:
    """
    ✅ v4.0.8 FIX-N: يُغلق default executor الخاص بالحلقة ثم pool الداخلي.
    """
    try:
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

        if loop is not None and not loop.is_closed():
            try:
                shutdown_method = getattr(
                    loop, "shutdown_default_executor", None,
                )
                if callable(shutdown_method):
                    try:
                        await asyncio.wait_for(
                            shutdown_method(), timeout=timeout,
                        )
                    except (asyncio.TimeoutError, TypeError, AttributeError):
                        try:
                            await shutdown_method()
                        except Exception:
                            pass
            except Exception as _e:
                logger.debug("shutdown_default_executor (loop): %s", _e)

        _shutdown_shared_pool()
    except Exception as exc:
        logger.debug("shutdown_default_executor: %r", exc)


# =============================================================================
# OPTIONAL DEPENDENCIES
# =============================================================================

_PIL_AVAILABLE = False
try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageStat  # type: ignore
    _PIL_AVAILABLE = True
except ImportError:
    pass

_OCR_AVAILABLE = False
try:
    import pytesseract  # type: ignore
    if _PIL_AVAILABLE:
        _OCR_AVAILABLE = True
except ImportError:
    pass

_QR_AVAILABLE = False
try:
    from pyzbar.pyzbar import decode as _qr_decode  # type: ignore
    if _PIL_AVAILABLE:
        _QR_AVAILABLE = True
except ImportError:
    pass

_AUDIO_AVAILABLE = False
_WHISPER_AVAILABLE = False
_REQUESTS_AVAILABLE = False
_WHOIS_AVAILABLE = False
_CV2_AVAILABLE = False
_NUMPY_AVAILABLE = False
_FFMPEG_AVAILABLE = False
_NSFW_MODEL_AVAILABLE = False

try:
    import speech_recognition as _sr  # type: ignore
    from pydub import AudioSegment as _AudioSegment  # type: ignore
    from pydub.effects import normalize as _pydub_normalize  # type: ignore
    _AUDIO_AVAILABLE = True
except ImportError:
    pass

try:
    import whisper as _whisper  # type: ignore
    _WHISPER_AVAILABLE = True
except ImportError:
    pass

try:
    import requests as _requests  # type: ignore
    _REQUESTS_AVAILABLE = True
except ImportError:
    pass

try:
    import whois as _whois  # type: ignore
    _WHOIS_AVAILABLE = True
except ImportError:
    pass

try:
    import cv2  # type: ignore
    _CV2_AVAILABLE = True
except ImportError:
    pass

try:
    import numpy as _np  # type: ignore
    _NUMPY_AVAILABLE = True
except ImportError:
    pass

try:
    import subprocess as _subprocess
    _ffmpeg_test = _subprocess.run(
        ["ffmpeg", "-version"], capture_output=True, timeout=3,
    )
    _FFMPEG_AVAILABLE = _ffmpeg_test.returncode == 0
except Exception:
    _FFMPEG_AVAILABLE = False

_nsfw_classifier = None
_nsfw_load_lock = threading.Lock()
_nsfw_load_attempted = False


def _load_nsfw_classifier() -> Any:
    """✅ v4.0.8 FIX-C: تحميل كسول محسّن مع cache فشل."""
    global _nsfw_classifier, _NSFW_MODEL_AVAILABLE, _nsfw_load_attempted

    if _nsfw_classifier is not None:
        return _nsfw_classifier
    if not NSFW_MODEL_ENABLED:
        return None
    if _nsfw_load_attempted and _nsfw_classifier is None:
        return None

    with _nsfw_load_lock:
        if _nsfw_classifier is not None:
            return _nsfw_classifier
        if _nsfw_load_attempted and _nsfw_classifier is None:
            return None

        _nsfw_load_attempted = True
        try:
            from transformers import pipeline  # type: ignore
            _nsfw_classifier = pipeline(
                "image-classification",
                model="Falconsai/nsfw_image_detection",
                device=-1,
            )
            _NSFW_MODEL_AVAILABLE = True
            logger.info("✅ NSFW classifier loaded (local model)")
            return _nsfw_classifier
        except Exception as exc:
            logger.warning("NSFW model load failed: %r", exc)
            _NSFW_MODEL_AVAILABLE = False
            return None


# =============================================================================
# THRESHOLDS
# =============================================================================

SPAM_SCORE_THRESHOLD = 5
POSTBOT_AUTO_BLOCK_CONFIDENCE = 3
SPAM_HARD_THRESHOLD = 10
SPAM_CRITICAL_THRESHOLD = 15
MAX_SPAM_SCORE = 40

MAX_ANALYSIS_TEXT_LENGTH = 12000
MAX_REASON_COUNT = 80

RANDOM_DOMAIN_MIN_LENGTH = 10
RANDOM_DOMAIN_MAX_VOWEL_RATIO = 0.35

_MAX_EXTRACTED_URLS = 50

OCR_MAX_IMAGE_SIZE = (2000, 2000)
OCR_LANGUAGES = os.getenv("OCR_LANGUAGES", "ara+eng+fas+rus")

RATE_WINDOW_SECONDS = 60
RATE_MAX_MESSAGES = 15
RATE_MAX_URLS = 5
CROSS_MSG_WINDOW = 30

_CONTEXT_WINDOW_SEC = 120

# 🆕 v4.0.9 FIX-AR-5: FINAL_THRESHOLD قابل للتعديل عبر ENV
FINAL_THRESHOLD = _env_int("FINAL_THRESHOLD", 5)

LAYER_WEIGHTS = {
    "text": 1.0, "ocr": 1.2, "audio": 1.1, "url": 1.5,
    "metadata": 0.8, "obfuscation": 1.3, "behavioral": 1.0,
    "video": 1.3, "nsfw": 1.4, "sticker": 0.9,
    "reactions": 0.7, "context": 1.1, "cipher": 1.2,
    "stego": 1.2, "domain_rep": 1.4,
}

LAYER_SCORE_CAPS = {
    "text": 40, "ocr": 30, "audio": 25, "url": 30,
    "metadata": 20, "obfuscation": 30, "behavioral": 20,
    "video": 30, "nsfw": 25, "sticker": 15,
    "reactions": 15, "context": 25, "cipher": 25,
    "stego": 25, "domain_rep": 25,
}

MAX_TOTAL_SCORE = 120

_SCORE_CAP_LINK = 8
_SCORE_CAP_CONTENT = 9
_SCORE_CAP_CTA = 5
_SCORE_CAP_EVASION = 8
_SCORE_CAP_STRUCTURE = 6
_SCORE_CAP_CONTEXT = 8


# =============================================================================
# TLD WHITELIST
# =============================================================================

_COMMON_TLDS = frozenset({
    "com", "net", "org", "io", "me", "co", "cc",
    "info", "gov", "edu", "biz", "name", "mobi", "asia", "tel",
    "xyz", "top", "site", "online", "live", "vip", "pro",
    "tv", "app", "dev", "link", "click", "shop", "store",
    "club", "work", "space", "website", "fun", "art",
    "wiki", "buzz", "today", "email", "cloud", "host",
    "press", "rocks", "social", "agency",
    "digital", "life", "world", "network", "solutions",
    "company", "media", "download", "stream", "review",
    "science", "guru", "expert", "center", "money",
    "finance", "capital", "casino", "bet", "poker",
    "games", "game", "play", "chat", "blog", "news",
    "photography", "pics", "video", "tube", "cam",
    "date", "dating", "sexy", "adult", "sex", "porn",
    "xxx", "one", "bio", "page", "quest", "monster",
    "lol", "wtf", "rip", "rest", "bar", "cafe",
    "pizza", "beer", "coffee", "love", "family",
    "baby", "kids", "school", "university", "academy",
    "courses", "study", "degree", "career", "jobs",
    "market", "business", "industries",
    "supplies", "tools", "parts", "gallery", "photos",
    "audio", "music", "band", "concert",
    "theater", "studio", "productions", "director",
    "support", "help", "service", "services",
    "systems", "tech", "technology",
    "software", "codes", "run", "mobile",
    "icu", "bond", "cyou", "zip", "mov",
    "ru", "cn", "de", "fr", "uk", "us",
    "eg", "sa", "ae", "kw", "qa", "bh",
    "om", "jo", "lb", "sy", "iq", "ma",
    "dz", "tn", "ly", "sd", "ye", "ir",
    "tr", "pk", "in", "bd", "id", "my",
    "th", "vn", "ph", "sg", "hk", "tw",
    "kr", "jp", "it", "es", "pt", "nl",
    "be", "ch", "at", "se", "no", "dk",
    "fi", "pl", "cz", "sk", "hu", "ro",
    "bg", "gr", "hr", "rs", "ua", "br",
    "mx", "ar", "cl", "pe", "ve", "uy",
    "py", "bo", "ec", "au", "nz", "za",
    "ng", "ke", "gh", "tz", "ug", "et",
    "fm", "am", "gg", "tk", "ml", "ga",
    "cf", "to", "ws", "gs",
})

_TLD_PATTERN = "|".join(sorted(_COMMON_TLDS, key=len, reverse=True))


# =============================================================================
# UNICODE / HIDDEN
# =============================================================================

_HIDDEN_CHARS = {
    "\x00", "\x01", "\x02", "\x03", "\x04", "\x05", "\x06", "\x07",
    "\x08", "\x0b", "\x0c", "\x0e", "\x0f", "\x10", "\x11", "\x12",
    "\x13", "\x14", "\x15", "\x16", "\x17", "\x18", "\x19", "\x1a",
    "\x1b", "\x1c", "\x1d", "\x1e", "\x1f", "\x7f",
    "\u061c", "\u115f", "\u1160", "\u17b4", "\u17b5", "\u180e",
    "\u200b", "\u200c", "\u200d", "\u200e", "\u200f",
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
    "\u2060", "\u2061", "\u2062", "\u2063", "\u2064", "\u2065",
    "\u2066", "\u2067", "\u2068", "\u2069",
    "\u206a", "\u206b", "\u206c", "\u206d", "\u206e", "\u206f",
    "\ufeff",
}

_BIDI_CHARS = {
    "\u061c", "\u200e", "\u200f",
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
    "\u2066", "\u2067", "\u2068", "\u2069",
}

_COMBINING_RANGES = (
    (0x0300, 0x036F), (0x1AB0, 0x1AFF), (0x1DC0, 0x1DFF),
    (0x20D0, 0x20FF), (0xFE20, 0xFE2F),
)

_HOMOGLYPH_MAP = {
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "І": "I",
    "Ј": "J", "К": "K", "М": "M", "О": "O", "Р": "P", "Ѕ": "S",
    "Т": "T", "Х": "X", "Ү": "Y",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y",
    "х": "x", "і": "i", "ј": "j", "к": "k", "м": "m", "т": "t",
    "Α": "A", "Β": "B", "Ε": "E", "Η": "H", "Ι": "I", "Κ": "K",
    "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Χ": "X",
    "Υ": "Y", "Ζ": "Z",
    "α": "a", "β": "b", "ε": "e", "η": "h", "ι": "i", "κ": "k",
    "μ": "m", "ν": "n", "ο": "o", "ρ": "p", "τ": "t", "χ": "x",
    "υ": "y", "ζ": "z",
}

_LEET_MAP = str.maketrans({
    "0": "o", "1": "i", "2": "z", "3": "e", "4": "a",
    "5": "s", "6": "g", "7": "t", "8": "b", "9": "g",
    "@": "a", "$": "s",
})

_LEET_TARGETS = frozenset({
    "spam", "scam", "porn", "porno", "xxx",
    "nude", "nudes", "leak", "leaked", "leaks",
    "viral", "mega", "megapack", "pack", "packs",
    "premium", "private", "secret", "hidden",
    "uncensored", "uncut", "download", "click",
    "watch", "open", "join", "subscribe",
    "unlock", "exclusive",
    "free", "bonus", "winner", "prize", "gift",
    "cash", "money", "eth", "btc", "usdt", "bnb",
    "crypto", "airdrop", "airdrops", "invest",
    "profit", "hack", "hacked",
    "claim", "reward", "rewards",
    "doubling", "doubler", "mining", "staking",
    "presale", "whitelist", "launchpad",
    "wallet", "metamask", "trustwallet",
    "elon", "musk", "tesla", "spacex",
    "giveaway", "lottery", "jackpot",
    "casino", "betting", "bet", "poker", "roulette",
    "trading", "signals", "forex", "pump",
})


# =============================================================================
# 🆕 v4.0.9 FIX-AR-1: Arabic Short Whitelist
# =============================================================================

_ARABIC_GREETINGS = frozenset({
    # تحيات صباحية/مسائية
    "صباح", "صباحا", "صباحاً", "صباحو", "صباحي", "صبحك",
    "مساء", "مساءا", "مساءاً", "مساءو", "مسائي", "مساك",
    "صبح", "مسا",
    # تحيات عامة
    "اهلا", "أهلا", "اهلاوسهلا", "أهلاوسهلا", "اهلاً", "أهلاً",
    "مرحبا", "مرحباً", "مرحبتين", "هلا", "هلاوالله", "هلاوسهلا",
    "السلام", "سلام", "سلامو", "سلاما", "سلاماً", "سلامي",
    "عليكم", "عليكمالسلام", "عليكمورحمة", "عليكمورحمةالله",
    # كلمات polite / small-talk
    "شكرا", "شكراً", "شكرالك", "شكراكتير", "شكراكتير",
    "مشكور", "مشكورة", "مشكورين", "مشكوره",
    "عفوا", "عفواً", "العفو",
    "تسلم", "تسلمي", "تسلملي", "تسلموا",
    "جزاك", "جزاكالله", "جزاكم", "جزاكمالله",
    "بارك", "باركالله", "باركك",
    "تحياتي", "تحيات", "تحية", "تحياتنا",
    "خير", "بخير", "الحمدلله", "الحمد",
    "كيف", "كيفك", "كيفكم", "كيفحالك", "كيفحالكم", "شلونك",
    "شلونكم", "شخبارك", "شخباركم",
    "نورت", "نورتي", "نورتوا",
    "الود", "الورد", "ورد", "زهر", "زهور",
    "الخير", "الخيرات", "الخيروالبركة",
    "التوفيق", "بالنجاح", "بالتوفيق",
    "الرحمة", "الرحمن", "الرحيم", "المغفرة",
    "الجميل", "الجميلة", "الحلو", "الحلوة",
    "الطيب", "الطيبة", "الكريم", "الكريمة",
    "الحبيب", "الحبيبة", "الغالي", "الغالية",
    "الله", "سبحان", "الحمدلله", "لاالهالاالله",
    "انشاءالله", "إنشاءالله", "مافيه", "ماشاءالله",
    "يعطيك", "يعطيكالعافية", "يعطيكم", "يعطيكمالعافية",
    "اللهيعطيك", "اللهيعافيك",
    # ردود قصيرة
    "تمام", "تم", "طيب", "اوك", "اوكي", "اوكيه",
    "حسناً", "حسنا", "زين", "طيبين", "بخير",
    "نعم", "لا", "اكيد", "بالتاكيد", "بالتأكيد",
    "احسنت", "احسنتي", "برافو", "ممتاز", "رائع", "رائعة",
    "جميل", "جميلة", "حلو", "حلوة",
})

# كلمات spam العربية التي **يجب** أن تُبطل whitelist (لا تُعامل كتحية)
_ARABIC_SPAM_OVERRIDE = frozenset({
    "تسريب", "تسريبات", "مسرب", "مسربة", "مسرّب", "مسرّبة",
    "حصري", "حصريه", "حصرية", "فيديو", "فيديوهات",
    "مقاطع", "مقطع", "صور", "ممنوع", "ممنوعة",
    "جنس", "جنسي", "جنسية", "اباحي", "إباحي", "اباحية", "إباحية",
    "بورن", "سكس", "نيك", "عاري", "عاري", "عارية",
    "ربح", "ارباح", "أرباح", "استثمار", "تداول", "محفظة",
    "بيتكوين", "اثيريوم", "كريبتو", "عملات", "عملة",
    "كازينو", "مراهنات", "بوكر", "يانصيب", "جوائز",
    "رابط", "روابط", "رابطمباشر", "رابطالقناة",
    "اضغط", "شاهد", "مشاهدة", "شوف", "ادخل", "دخول",
    "انضم", "اشترك", "تحميل", "حمل", "حمّل",
    "احصل", "اربح", "استلم", "استقبل", "اطلب",
    "مجاناً", "مجانا", "مجانية", "مجاني",
    "هدية", "جوائز", "جائزة", "بونص", "بونوس",
    "خصم", "عرض", "تخفيض", "متجر", "شراء",
    "مليونير", "ثري", "مضاعفة", "مضاعف",
})


def _arabic_char_ratio(text: str) -> float:
    """🆕 v4.0.9: نسبة الحروف العربية من إجمالي الحروف."""
    if not text:
        return 0.0
    arabic = 0
    total_letters = 0
    for ch in text:
        if ch.isalpha():
            total_letters += 1
            if "\u0600" <= ch <= "\u06FF" or "\u0750" <= ch <= "\u077F":
                arabic += 1
    if total_letters == 0:
        return 0.0
    return arabic / total_letters


def _is_arabic_dominant(text: str) -> bool:
    """
    🆕 v4.0.9 FIX-AR-6: هل النص عربي غالباً؟
    """
    if not text:
        return False
    return _arabic_char_ratio(text) >= ARABIC_DOMINANCE_RATIO


def _strip_arabic_diacritics(text: str) -> str:
    """🆕 v4.0.9: إزالة التشكيل العربي للمقارنة."""
    if not text:
        return ""
    # Arabic diacritics: Fatha, Damma, Kasra, Shadda, Sukun, Tanwin, etc.
    diacritics = re.compile(
        r"[\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E8"
        r"\u06EA-\u06ED\u0640]"
    )
    return diacritics.sub("", text)


def _normalize_arabic_for_compare(text: str) -> str:
    """🆕 v4.0.9: تطبيع للعربية للمقارنة (للـwhitelist)."""
    if not text:
        return ""
    # 1. إزالة التشكيل
    s = _strip_arabic_diacritics(text)
    # 2. إزالة "ال" التعريف من البداية لكل كلمة
    s = re.sub(r"(?<!\S)ال", "", s)
    # 3. إزالة علامات الترقيم والرموز
    s = re.sub(r"[^\u0600-\u06FF\s]", "", s)
    # 4. تطبيع الهمزات
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    # 5. تطبيع ى → ي، ة → ه
    s = s.replace("ى", "ي").replace("ة", "ه")
    # 6. تبسيط المسافات
    s = re.sub(r"\s+", "", s)
    return s.strip()


def _is_arabic_short_whitelisted(text: str) -> bool:
    """
    🆕 v4.0.9 FIX-AR-1: هل النص رسالة عربية قصيرة طبيعية (تحية/ردود)؟

    الشروط:
        1. ARABIC_SHORT_WHITELIST_ENABLED مفعّل
        2. النص عربي غالباً (_is_arabic_dominant)
        3. عدد الأحرف ≤ ARABIC_SHORT_MAX_CHARS (40 افتراضي)
        4. عدد الكلمات ≤ ARABIC_SHORT_MAX_WORDS (6 افتراضي)
        5. كل كلمات النص في _ARABIC_GREETINGS (بعد التطبيع)
        6. النص لا يحتوي على أي كلمة من _ARABIC_SPAM_OVERRIDE
        7. لا يحتوي على روابط (@, http, t.me)

    Returns:
        True إذا كان whitelisted (يجب عدم حذفه)
    """
    if not ARABIC_SHORT_WHITELIST_ENABLED:
        return False
    if not text:
        return False

    text = text.strip()
    if not text:
        return False

    # 1. الطول
    if len(text) > ARABIC_SHORT_MAX_CHARS:
        return False

    # 2. عدد الكلمات
    words = re.findall(r"[^\s]+", text)
    if len(words) > ARABIC_SHORT_MAX_WORDS:
        return False

    # 3. عربي غالباً
    if not _is_arabic_dominant(text):
        return False

    # 4. لا يوجد روابط/منشن/إيميل
    if re.search(r"(?:https?://|www\.|t\.me/|@[A-Za-z0-9_])", text):
        return False

    # 5. تطبيع للمقارنة
    normalized_full = _normalize_arabic_for_compare(text)
    if not normalized_full:
        return False

    # 6. فحص كل كلمة
    for word in words:
        word_norm = _normalize_arabic_for_compare(word)
        if not word_norm:
            continue
        # 6a. spam override؟
        if word_norm in _ARABIC_SPAM_OVERRIDE:
            return False
        # 6b. التحقق من subwords (كلمة "مساءالورد" بدون مسافة)
        # نبحث عن أي تطابق في _ARABIC_GREETINGS
        found_greeting = False
        for greeting in _ARABIC_GREETINGS:
            greeting_norm = _normalize_arabic_for_compare(greeting)
            if greeting_norm and greeting_norm in word_norm:
                found_greeting = True
                break
        if not found_greeting:
            return False

    # 7. فحص spam override في النص الكامل
    for spam_word in _ARABIC_SPAM_OVERRIDE:
        spam_norm = _normalize_arabic_for_compare(spam_word)
        if spam_norm and spam_norm in normalized_full:
            return False

    return True


# =============================================================================
# TRANSLATION TABLES
# =============================================================================

_WS_TRANSLATE_TABLE = str.maketrans({
    **{chr(c): " " for c in range(0x2000, 0x200B)},
    "\u00a0": " ",
    "\u2028": " ",
    "\u2029": " ",
    "\u202f": " ",
    "\u205f": " ",
    "\u3000": " ",
})

_UNICODE_DOT_TABLE = str.maketrans({
    "\u2024": ".", "\u2025": ".", "\u2026": ".",
    "\u3002": ".", "\uFE52": ".", "\uFF0E": ".", "\uFF61": ".",
})


_EMOJI_STRIP_RE = re.compile(
    r"(?:"
    r"(?:[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF]"
    r"[\U0001F3FB-\U0001F3FF]?"
    r"(?:\u200d[\U0001F000-\U0001FAFF]"
    r"[\U0001F3FB-\U0001F3FF]?)*)"
    r"|[\U0001F1E6-\U0001F1FF]{2}"
    r"|[0-9#*]\uFE0F?\u20E3"
    r")"
)


# =============================================================================
# REGEX — TEXT
# =============================================================================

_URL_RE = re.compile(r"(?i)\b(?:https?|ftp)://[^\s<>()\"']+")
_DOMAIN_RE = re.compile(
    r"(?i)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}"
)
_DOMAIN_HTTP_RE = re.compile(
    r"(?i)\b(?:https?://)?(?:www\.)?(?:[a-z0-9-]+\.)+[a-z]{2,63}(?:/[^\s<>()]*)?"
)
_EMAIL_RE = re.compile(
    r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,63}\b"
)
_IPV4_RE = re.compile(
    r"\b(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b"
)
_PUNYCODE_RE = re.compile(r"(?i)\bxn--[a-z0-9-]+")
_TG_SCHEME_RE = re.compile(r"(?i)\b(?:tg|telegram):(?:/[^\s]+|[^\s]+)")
_TG_URL_RE = re.compile(
    r"(?i)(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)(?:/[^\s<>()]+)?"
)
_TG_INVITE_RE = re.compile(r"(?i)(?:t\.me/)?(?:joinchat/|\+)[A-Za-z0-9_-]{4,}")
_TG_USERNAME_RE = re.compile(r"(?<![\w@])@(?:[A-Za-z0-9_]{5,32})(?!\w)")
_ALT_SCHEME_RE = re.compile(
    r"(?i)\b(?:hxxp|hxxps|ttp|ttps|htp|httpx|httpsx)[:/\\]+"
)
_SPACED_SCHEME_RE = re.compile(r"(?i)\bh\s*t\s*t\s*p\s*s?\s*[:./\\]")
_COLON_SLASH_SCHEME_RE = re.compile(
    r"(?i)\b(?:https?|hxxps?|ftp)\s*[\[\(\{]?\s*:\s*[\]\)\}]?\s*/\s*/"
)
_SPACED_TG_RE = re.compile(
    r"(?i)\bt[ \t]{0,3}[\.\[\(\{]{0,1}[ \t]{0,3}m[ \t]{0,3}"
    r"[\.\]\)\}]{0,1}[ \t]{0,3}e\b"
)
_DOT_DOMAIN_RE = re.compile(
    rf"(?i)\b[a-z0-9_-]{{2,50}}"
    rf"(?:\s*(?:dot|\[\.\]|\(\.\)|\{{\.\}})\s*)"
    rf"(?:{_TLD_PATTERN})(?!\w)"
)
_SPACED_DOMAIN_RE = re.compile(
    rf"(?i)\b[a-z0-9_-]{{2,50}}"
    rf"(?:\s*[.\u2024\u2025\u2026\u3002\uFE52\uFF0E]\s*)"
    rf"(?:{_TLD_PATTERN})(?!\w)"
)
_MULTILINE_DOMAIN_RE = re.compile(
    rf"(?is)\b[a-z0-9_-]{{2,50}}"
    rf"[ \t]{{0,8}}[\r\n]{{1,4}}[ \t]{{0,8}}"
    rf"(?:\.\s{{0,4}}[\r\n]{{1,4}}\s{{0,4}}"
    rf"|\u2024|\u3002|\.)"
    rf"[ \t]{{0,8}}"
    rf"(?:{_TLD_PATTERN})(?!\w)"
)
_DOT_LIKE_RE = re.compile(
    r"(?i)(?:\[\s*\.\s*\]|\(\s*\.\s*\)|\{\s*\.\s*\}"
    r"|\[\s*dot\s*\]|\(\s*dot\s*\)|\{\s*dot\s*\})"
)
_DOT_WORD_RE = re.compile(
    rf"(?i)\b[a-z0-9_-]{{2,50}}"
    rf"\s+(?:dot|\[\s*dot\s*\]|\(\s*dot\s*\)|\{{\s*dot\s*\}})"
    rf"\s+(?:{_TLD_PATTERN})(?!\w)"
)
_NUMBER_PROMO_RE = re.compile(
    r"(?i)(?:\d{2,7}\s*\+?\s*"
    r"(?:clips?|videos?|pics?|photos?|files?|items?|"
    r"مقطع|مقاطع|فيديوهات?))"
)
_PACK_RE = re.compile(
    r"(?i)\b(?:mega|huge|massive|full|exclusive)?[\s_-]*pack(?:age|s)?\b"
)
_REPEATED_CHAR_RE = re.compile(r"(.)\1{4,}", re.UNICODE)
_REPEATED_WORD_RE = re.compile(r"(?i)\b(\w{2,40})(?:\s+\1){2,}\b")
_SEPARATOR_RE = re.compile(
    r"(?:[\W_]{4,}|(?:[a-z]\W){4,}[a-z])", re.IGNORECASE
)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,18}\d)(?!\d)")

_MULTISPACE_SPLIT_RE = re.compile(
    r"(?i)\b(?:[a-z][ \t]{1,3}){3,}[a-z]\b"
)
_EMOJI_SPLIT_RE = re.compile(
    r"(?i)\b(?:[a-z][ \t]{0,3}[\U0001F000-\U0001FAFF][ \t]{0,3}){3,}[a-z]\b"
)
_LONG_DOMAIN_LABEL_RE = re.compile(r"(?i)\b[a-z0-9-]{35,}\.[a-z]{2,63}\b")
_MULTILINE_URL_SCHEME_RE = re.compile(
    r"(?is)\b(?:h[ \t]{0,3}t[ \t]{0,3}t[ \t]{0,3}p[ \t]{0,3}s?"
    r"|hxxps?|ftp)\s*[:]\s*[/\\]\s*[/\\]"
)


# =============================================================================
# REGEX — OBFUSCATION / URL
# =============================================================================

_BASE64_RE = re.compile(r"^[A-Za-z0-9+/]{16,}={0,2}$")
_BASE64_URLSAFE_RE = re.compile(r"^[A-Za-z0-9_-]{16,}={0,2}$")

_URL_SIGNATURE_RE = re.compile(
    r"(?i)(?:"
    r"https?://"
    r"|www\."
    r"|t\.me/"
    r"|telegram\.me/"
    r"|\.(?:com|net|org|io|xyz|digital)(?![\w])"
    r")"
)

_URL_IN_TEXT_RE = re.compile(
    r"(?i)\b(?:https?://|www\.|t\.me/|telegram\.me/)\S+"
)

_SUSPICIOUS_NAME_PATTERNS = [
    re.compile(r"(?i)https?://"),
    re.compile(r"(?i)www\."),
    re.compile(r"(?i)t\.me/"),
    re.compile(r"(?i)\b\d{5,}\b"),
    re.compile(r"(?i)\+?\d[\d\s().-]{8,}"),
    re.compile(r"(?i)@[A-Za-z0-9_]{4,}"),
    re.compile(r"(?i)(?:bit\.ly|tinyurl|cutt\.ly)"),
]

_SHORTENER_DOMAINS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly",
    "cutt.ly", "rb.gy", "shorturl.at", "is.gd", "buff.ly",
    "soo.gd", "s2r.co", "clicky.me", "v.gd", "mcaf.ee",
    "su.pr", "ht.ly", "qr.ae", "j.mp", "snip.ly",
    "shorte.st", "adf.ly", "bc.vc", "linkbucks.com",
    "tiny.cc", "x.co", "lnkd.in", "db.tt",
}


# =============================================================================
# VOCABULARY
# =============================================================================

_STRONG_SPAM_WORDS = {
    "uncensored", "xxx", "nsfw", "porn", "porno",
    "nude", "nudes", "nudity", "leak", "leaked",
    "leaks", "viral", "archive", "drop", "mega",
    "megapack", "mega-pack", "packs", "pack",
    "clips", "exclusive", "premium", "private",
    "secret", "hidden", "uncut", "download",
}

_MEDIUM_SPAM_WORDS = {
    "collection", "collections", "footage", "scene",
    "scenes", "fresh", "wild", "best", "hot",
    "sexy", "milf", "dilf", "teen", "teenager",
    "taboo", "busty", "pierced", "petite",
    "cartoon", "korean", "colombian", "stepmom",
    "stepsis", "mfm", "bj", "mature",
}

_CTA_WORDS = {
    "check", "tap", "click", "view", "open",
    "join", "subscribe", "download", "watch",
    "see", "visit", "enter", "access", "claim",
    "get", "unlock", "follow", "now", "here",
}

_PROMO_WORDS = {
    "mega", "pack", "collection", "archive",
    "exclusive", "premium", "private", "content",
    "clips", "drop", "leak", "viral", "fresh", "new",
}

_ARABIC_SPAM_WORDS = {
    "تسريب", "تسريبات", "مسرب", "مسربة",
    "مسرّب", "مسرّبة", "محتوى", "حصري",
    "حصريه", "حصرية", "خاص", "خاصه", "خاصة",
    "ممنوع", "ممنوعة", "فيديوهات", "فيديو",
    "صور", "مقاطع", "مقطع", "باك", "باكج",
    "حزمة", "مجموعة", "ارشيف", "أرشيف",
    "جديد", "جديده", "جديدة", "فيرال", "ترند",
    "عملات", "عملة", "تداول", "استثمار", "ربح",
    "جوائز", "جائزة", "مجاناً", "مجانا", "مجانية",
    "كازينو", "مراهنات", "بوكر", "يانصيب",
    "متجر", "شراء", "خصم", "عرض", "تخفيض",
    "مليونير", "ثري", "أرباح", "مضاعفة", "مضاعف",
    "بيتكوين", "اثيريوم", "كريبتو", "محفظة",
}

_ARABIC_CTA_WORDS = {
    "اضغط", "شاهد", "مشاهدة", "شوف", "ادخل",
    "دخول", "افتح", "انضم", "اشترك", "تحميل",
    "حمل", "حمّل", "الرابط", "هنا", "اضغطهنا",
    "سجل", "سجّل", "اشترك", "فعّل", "فعل",
    "احصل", "اربح", "استلم", "استقبل", "اطلب",
}

_EXTRA_SCRIPT_SPAM_WORDS = {
    "فروش", "دانلود", "رایگان", "خصوصی",
    "محرمانه", "ویدیو", "ویدئو", "تصاویر",
    "لینک", "کلیپ",
    "سرمایه", "سود", "پول", "ارز", "دیجیتال",
    "بونوس", "جایزه", "برنده",
}

_FINANCIAL_SCAM_WORDS = {
    "giveaway", "airdrop", "presale", "whitelist",
    "launchpad", "staking", "mining", "yield",
    "roi", "apy", "apr", "100x", "1000x",
    "doubling", "doubler", "bitcoin", "ethereum",
    "btc", "eth", "usdt", "bnb", "sol", "usdc",
    "metamask", "trustwallet", "phantom",
    "elon", "musk", "spacex", "tesla",
    "winner", "jackpot", "lottery", "bonus",
    "prize", "cash", "usd", "eur",
}

_GENERIC_WORDS = {
    "new", "content", "best", "watch", "click",
    "open", "view", "here", "fresh", "full",
    "see", "join", "video", "photos", "photo",
}

_SPAM_EMOJIS = {
    "🔥", "💥", "🚀", "👉", "👈", "👇",
    "☝️", "💦", "💋", "🍑", "🍆", "😈",
    "😏", "🔞", "⚡", "💎", "🎁", "🤑", "💯",
    "💰", "💵", "💸", "🪙", "🏆", "🥇", "🎰",
}

_SPAM_EMOJI_SINGLE = frozenset(e for e in _SPAM_EMOJIS if len(e) == 1)
_SPAM_EMOJI_MULTI = tuple(e for e in _SPAM_EMOJIS if len(e) > 1)

_SPAM_REACTIONS = frozenset({
    "👍", "🔥", "❤", "❤️", "💯", "😁", "😂",
    "🎉", "👏", "🙏", "⚡", "💥",
})


# =============================================================================
# CONTEXT PATTERNS
# =============================================================================

_PROMO_CONTEXT_PATTERNS = [
    re.compile(r"(?i)\b(?:mega|huge|massive|exclusive)\s*[- ]?\s*pack\b"),
    re.compile(r"(?i)\b\d{2,7}\s*\+\s*(?:clips?|videos?|pics?|photos?)\b"),
    re.compile(
        r"(?i)\b(?:viral|leak(?:ed)?|exclusive)\b.{0,100}"
        r"\b(?:content|clips?|pack|collection|archive)\b"
    ),
    re.compile(
        r"(?i)\b(?:view|open|click|tap|watch|check)\b.{0,70}"
        r"\b(?:leak|content|pack|collection|archive)\b"
    ),
    re.compile(
        r"(?i)\b(?:join|subscribe|download|unlock)\b.{0,70}"
        r"\b(?:private|exclusive|premium|content)\b"
    ),
    re.compile(
        r"(?:اضغط|شاهد|ادخل|افتح|تحميل).{0,70}"
        r"(?:محتوى|تسريب|حصري|مجموعة|فيديو|مقاطع)"
    ),
    re.compile(
        r"(?i)\b(?:giveaway|airdrop|presale|whitelist)\b.{0,80}"
        r"\b(?:claim|join|free|win|bonus)\b"
    ),
    re.compile(
        r"(?i)\b(?:100x|1000x|10x|50x)\b.{0,60}"
        r"\b(?:profit|gain|roi|bonus|free)\b"
    ),
]

_POSTBOT_REGEXES = [
    re.compile(
        r"(?i)(?:🔥|💥|🚀|👉|💦|🔞|⚡).{0,40}"
        r"\b(?:view|open|click|tap|watch)\b"
    ),
    re.compile(
        r"(?i)\b(?:mega|exclusive|viral|leak|premium)\b.{0,70}"
        r"(?:🔥|💥|👉|💦|🔞)"
    ),
    re.compile(r"(?i)\b(?:mega\s*pack|pack)\b.{0,70}\b\d{2,7}\+?\b"),
]


# =============================================================================
# RANDOM DOMAIN
# =============================================================================

_NATURAL_VOWEL_SEQUENCES = (
    "ae", "ea", "ou", "ie", "ai", "au", "ei",
    "oi", "ui", "oo", "ee", "aa", "io", "ia",
)

_COMMON_BRAND_PATTERNS = (
    re.compile(
        r"(?i)(?:app|dev|cloud|host|live|shop|store|tech|"
        r"media|news|blog|chat|tube)"
    ),
    re.compile(
        r"(?i)(?:telegram|whatsapp|youtube|google|amazon|"
        r"facebook|instagram|twitter|tiktok)"
    ),
)


def _shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    text = text.casefold()
    length = len(text)
    freq = Counter(text)
    entropy = 0.0
    for count in freq.values():
        p = count / length
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


def _is_random_domain(domain: str) -> bool:
    if not domain or not ANTIEVASION_RANDOM_DOMAIN:
        return False
    try:
        domain = str(domain).strip().lower()
        domain = re.sub(r"^https?://", "", domain)
        domain = domain.split("/", 1)[0].split(":", 1)[0]
        parts = domain.split(".")
        if len(parts) < 2:
            return False
        tld = parts[-1]
        if not re.match(r"^[a-z]{2,24}$", tld):
            return False
        label = parts[-2]
        if len(label) < RANDOM_DOMAIN_MIN_LENGTH:
            return False
        if "-" in label or any(ch.isdigit() for ch in label):
            return False
        if any(seq in label for seq in _NATURAL_VOWEL_SEQUENCES):
            return False
        if any(p.search(label) for p in _COMMON_BRAND_PATTERNS):
            return False
        vowels = sum(1 for ch in label if ch in "aeiouy")
        vowel_ratio = vowels / max(len(label), 1)
        if vowel_ratio <= RANDOM_DOMAIN_MAX_VOWEL_RATIO:
            return True
        if len(label) >= 12 and _shannon_entropy(label) >= 3.2:
            return True
    except Exception:
        return False
    return False


def _has_random_domain(text: str, *, merged: Optional[str] = None) -> bool:
    if not text or not ANTIEVASION_RANDOM_DOMAIN:
        return False
    try:
        if merged is None:
            merged = _merge_split_urls(_normalize_text(text))
        for match in _DOMAIN_RE.finditer(merged):
            if _is_random_domain(match.group(0)):
                return True
    except Exception:
        pass
    return False


def _extract_random_domains_from_merged(merged: str) -> List[str]:
    if not merged or not ANTIEVASION_RANDOM_DOMAIN:
        return []
    found: List[str] = []
    try:
        for match in _DOMAIN_RE.finditer(merged):
            domain = match.group(0)
            if _is_random_domain(domain):
                found.append(domain)
    except Exception:
        pass
    return _unique_strings(found)


def _extract_random_domains(text: str) -> List[str]:
    if not text or not ANTIEVASION_RANDOM_DOMAIN:
        return []
    try:
        merged = _merge_split_urls(_normalize_text(text))
    except Exception:
        return []
    return _extract_random_domains_from_merged(merged)


# =============================================================================
# GENERIC HELPERS
# =============================================================================

def _unique_strings(values: Iterable[Any]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value is None:
            continue
        value = str(value).strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _extract_words(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r"[^\W\d_][\w'-]{1,40}", text, flags=re.UNICODE)


_WORD_RE_CACHE: "OrderedDict[frozenset, re.Pattern]" = OrderedDict()
_WORD_RE_CACHE_MAX = 512
_WORD_RE_CACHE_LOCK = threading.Lock()


def _vocab_regex(vocabulary: Iterable[str]) -> re.Pattern:
    key = frozenset(str(w).casefold() for w in vocabulary if w)
    with _WORD_RE_CACHE_LOCK:
        cached = _WORD_RE_CACHE.get(key)
        if cached is not None:
            _WORD_RE_CACHE.move_to_end(key)
            return cached
    if not key:
        pat = re.compile(r"(?!)")
    else:
        parts = sorted(key, key=len, reverse=True)
        pat = re.compile(
            r"(?<![\w\-])(?:" + "|".join(re.escape(p) for p in parts)
            + r")(?![\w\-])",
            flags=re.UNICODE,
        )
    with _WORD_RE_CACHE_LOCK:
        if len(_WORD_RE_CACHE) >= _WORD_RE_CACHE_MAX:
            _WORD_RE_CACHE.popitem(last=False)
        _WORD_RE_CACHE[key] = pat
    return pat


def _count_word_matches(
    text: str,
    vocabulary: Iterable[str],
    *,
    already_normalized: bool = False,
) -> int:
    if not text:
        return 0
    normalized = text if already_normalized else _normalize_text(text)
    if not normalized:
        return 0
    pattern = _vocab_regex(vocabulary)
    try:
        return len(pattern.findall(normalized))
    except Exception:
        return 0


def _count_emojis(text: str) -> int:
    if not text:
        return 0
    return sum(
        1 for ch in text
        if 0x1F000 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF
    )


def _count_spam_emojis(text: str) -> int:
    if not text:
        return 0
    count = sum(1 for ch in text if ch in _SPAM_EMOJI_SINGLE)
    for emoji in _SPAM_EMOJI_MULTI:
        count += text.count(emoji)
    return count


def _count_separators(text: str) -> int:
    if not text:
        return 0
    cleaned = _EMOJI_STRIP_RE.sub("", text)
    if not cleaned:
        return 0
    return len(_SEPARATOR_RE.findall(cleaned))


def _count_unique_matches(text: str, patterns: Iterable[re.Pattern]) -> int:
    if not text:
        return 0
    count = 0
    for pattern in patterns:
        try:
            if pattern.search(text):
                count += 1
        except Exception:
            continue
    return count


def _cap_score(current: int, added: int, cap: int) -> int:
    if added <= 0:
        return current
    return min(cap, current + added)


def _cap_layer_score(score: float, layer: str) -> float:
    cap = LAYER_SCORE_CAPS.get(layer, 40)
    return max(0.0, min(float(cap), float(score)))


# =============================================================================
# SCRIPT DETECTION
# =============================================================================

def _script_counts(text: str) -> Counter:
    counts: Counter = Counter()
    for ch in text or "":
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if "LATIN" in name:
            counts["latin"] += 1
        elif "ARABIC" in name:
            counts["arabic"] += 1
        elif "CYRILLIC" in name:
            counts["cyrillic"] += 1
        elif "GREEK" in name:
            counts["greek"] += 1
        elif "HEBREW" in name:
            counts["hebrew"] += 1
        elif "DEVANAGARI" in name:
            counts["devanagari"] += 1
        elif "HIRAGANA" in name or "KATAKANA" in name:
            counts["japanese"] += 1
        elif "HANGUL" in name:
            counts["korean"] += 1
        elif "CJK" in name or "IDEOGRAPH" in name:
            counts["cjk"] += 1
        else:
            counts["other"] += 1
    return counts


def _has_mixed_suspicious_scripts(
    text: str,
    counts: Optional[Counter] = None,
) -> bool:
    if counts is None:
        counts = _script_counts(text)
    latin = counts["latin"]
    cyr = counts["cyrillic"]
    greek = counts["greek"]
    if latin >= 3 and (cyr >= 1 or greek >= 1):
        return True
    if not ANTIEVASION_EXTRA_SCRIPTS:
        return False
    major_scripts = sum(
        1 for key, value in counts.items()
        if value >= 2 and key not in {"latin", "arabic"}
    )
    return major_scripts >= 2 and latin >= 2


# =============================================================================
# NORMALIZATION
# =============================================================================

def _strip_combining_marks(text: str) -> str:
    if not text:
        return ""
    result: List[str] = []
    for ch in unicodedata.normalize("NFD", text):
        code = ord(ch)
        in_range = any(start <= code <= end for start, end in _COMBINING_RANGES)
        if in_range:
            continue
        if unicodedata.category(ch) == "Mn":
            continue
        result.append(ch)
    return "".join(result)


def _remove_hidden_chars(text: str) -> str:
    if not text:
        return ""
    return "".join(ch for ch in text if ch not in _HIDDEN_CHARS)


def _deleet(text: str) -> str:
    if not text or not ANTIEVASION_LEETSPEAK:
        return text or ""

    def repl(match: re.Match) -> str:
        token = match.group(0)
        if not re.search(r"[A-Za-z]", token):
            return token
        if not re.search(r"\d|[@$]", token):
            return token
        letters = len(re.findall(r"[A-Za-z]", token))
        if letters < 2:
            return token
        candidate = token.translate(_LEET_MAP).casefold()
        compact_candidate = re.sub(r"[^a-z]+", "", candidate)
        if compact_candidate in _LEET_TARGETS:
            return candidate
        return token

    return re.sub(r"[A-Za-z0-9@$]{3,}", repl, text)


def _apply_homoglyphs_safe(text: str) -> str:
    if not text or not ANTIEVASION_HOMOGLYPH:
        return text or ""
    return "".join(_HOMOGLYPH_MAP.get(ch, ch) for ch in text)


def _normalize_unicode_dots(text: str) -> str:
    if not text or not ANTIEVASION_UNICODE_DOTS:
        return text or ""
    return text.translate(_UNICODE_DOT_TABLE)


def _do_normalize(text: str) -> str:
    """التنفيذ الفعلي للـnormalization — بدون cache."""
    value = html.unescape(str(text))
    value = unicodedata.normalize("NFKC", value).casefold()
    if ANTIEVASION_COMBINING or ANTIEVASION_EXTENDED_COMBINING:
        value = _strip_combining_marks(value)
    value = _remove_hidden_chars(value)
    value = _normalize_unicode_dots(value)
    if ANTIEVASION_HOMOGLYPH:
        value = _apply_homoglyphs_safe(value)
    if ANTIEVASION_LEETSPEAK:
        value = _deleet(value)
    value = unicodedata.normalize("NFKC", value)
    value = value.translate(_WS_TRANSLATE_TABLE)
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    return value.strip()


@functools.lru_cache(maxsize=NORMALIZE_CACHE_MAX)
def _normalize_text_cached(text: str) -> str:
    return _do_normalize(text)


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return ""
    if len(text) <= MAX_ANALYSIS_TEXT_LENGTH:
        try:
            return _normalize_text_cached(text)
        except Exception:
            pass
    try:
        return _do_normalize(text)
    except Exception:
        return ""


def _strip_emoji_for_domain(text: str) -> str:
    if not text:
        return ""
    if not ANTIEVASION_EMOJI_IN_DOMAIN:
        return text
    return _EMOJI_STRIP_RE.sub("", text)


def _has_hidden_chars(text: str) -> bool:
    return bool(text and any(ch in _HIDDEN_CHARS for ch in text))


def _hidden_char_count(text: str) -> int:
    if not text:
        return 0
    return sum(ch in _HIDDEN_CHARS for ch in text)


def _bidi_count(text: str) -> int:
    if not text:
        return 0
    return sum(ch in _BIDI_CHARS for ch in text)


# =============================================================================
# MERGE SPLIT URLS
# =============================================================================

def _scheme_replacement(match: re.Match) -> str:
    raw = match.group(0)
    compact = re.sub(r"\s+", "", raw).lower()
    scheme = re.split(r"[:/\\]", compact, maxsplit=1)[0]
    if scheme in (
        "https", "hxxps", "httpsx", "ttps", "htps",
        "httpx", "htxps", "hxxpx", "httpsxx",
    ):
        return "https://"
    if scheme in ("ftp", "ftps"):
        return "ftp://"
    return "http://"


def _tld_aware_dot_repl(match: re.Match) -> str:
    left, right = match.group(1), match.group(2)
    if right in _COMMON_TLDS:
        return f"{left}.{right}"
    return match.group(0)


def _tld_aware_dot_word_repl(match: re.Match) -> str:
    left, right = match.group(1), match.group(2)
    if right in _COMMON_TLDS:
        return f"{left}.{right}"
    return match.group(0)


def _tld_aware_multiline_repl(match: re.Match) -> str:
    left, right = match.group(1), match.group(2)
    if right in _COMMON_TLDS:
        return f"{left}.{right}"
    return match.group(0)


def _merge_split_urls(text: str) -> str:
    if not text:
        return ""
    value = str(text)
    value = re.sub(
        r"(?i)\b(?:h\s*t\s*t\s*p\s*s?\s*x?|h\s*x\s*x\s*p\s*s?|f\s*t\s*p)"
        r"\s*[:]\s*/\s*/",
        _scheme_replacement,
        value,
    )
    value = re.sub(r"(?i)\bhxxps?\s*:\s*/\s*/", _scheme_replacement, value)
    value = re.sub(r"(?i)\bhttpsx\s*:\s*/\s*/", _scheme_replacement, value)
    value = re.sub(r"(?i)\bhttpx\s*:\s*/\s*/", _scheme_replacement, value)
    value = re.sub(
        r"(?i)\bt\s*[\.\[\(\{]?\s*m\s*[\.\]\)\}]?\s*e",
        "t.me",
        value,
    )
    value = _DOT_LIKE_RE.sub(".", value)
    value = re.sub(
        r"(?i)\b([a-z0-9_-]{2,50})\s+dot\s+([a-z]{2,63})\b",
        _tld_aware_dot_word_repl,
        value,
    )
    value = _normalize_unicode_dots(value)
    value = re.sub(
        r"(?i)([a-z0-9_-]{2,50})\s*\.\s*([a-z]{2,63})",
        _tld_aware_dot_repl,
        value,
    )
    value = re.sub(r"[ \t]+/[ \t]+", "/", value)
    if ANTIEVASION_MULTILINE_URL:
        value = re.sub(
            r"(?i)([a-z0-9_-]{2,50})\s*\r?\n\s*\.\s*\r?\n\s*([a-z]{2,63})\b",
            _tld_aware_multiline_repl,
            value,
        )
    return value


# =============================================================================
# URL EXTRACTION
# =============================================================================

def _extract_possible_urls(text: str) -> List[str]:
    if not text:
        return []
    merged = _merge_split_urls(str(text))
    candidates: List[str] = []
    candidates.extend(_URL_RE.findall(merged))
    if ANTIEVASION_SCHEMELESS_URL:
        candidates.extend(_DOMAIN_HTTP_RE.findall(merged))
    if ANTIEVASION_IPV4_SCHEMELESS:
        candidates.extend(_IPV4_RE.findall(merged))
    if ANTIEVASION_PUNYCODE:
        candidates.extend(_PUNYCODE_RE.findall(merged))
    if ANTIEVASION_TG_SCHEME:
        candidates.extend(_TG_SCHEME_RE.findall(merged))
        candidates.extend(_TG_URL_RE.findall(merged))
        candidates.extend(_TG_INVITE_RE.findall(merged))
    return _unique_strings(candidates)[:_MAX_EXTRACTED_URLS]


# =============================================================================
# LINK DETECTION
# =============================================================================

def _has_domain_pattern(text: str) -> bool:
    if not text:
        return False
    value = _merge_split_urls(_strip_emoji_for_domain(_normalize_text(text)))
    if _DOMAIN_RE.search(value):
        return True
    if _SPACED_DOMAIN_RE.search(value):
        return True
    if _DOT_DOMAIN_RE.search(value):
        return True
    if ANTIEVASION_MULTILINE_URL and _MULTILINE_DOMAIN_RE.search(text):
        return True
    if ANTIEVASION_PUNYCODE and _PUNYCODE_RE.search(value):
        return True
    if ANTIEVASION_IPV4_SCHEMELESS and _IPV4_RE.search(value):
        return True
    return False


def _contains_link_enhanced(
    text: str,
    *,
    include_usernames: bool = True,
    already_normalized: bool = False,
) -> bool:
    if not text:
        return False
    raw = str(text)
    normalized = raw if already_normalized else _normalize_text(raw)
    merged = _merge_split_urls(normalized)
    domain_text = _strip_emoji_for_domain(merged)

    if _URL_RE.search(raw):
        return True
    if _DOMAIN_HTTP_RE.search(raw):
        return True
    if _DOMAIN_RE.search(domain_text):
        return True
    if _SPACED_DOMAIN_RE.search(domain_text):
        return True
    if _DOT_DOMAIN_RE.search(domain_text):
        return True
    if ANTIEVASION_MULTILINE_URL and _MULTILINE_DOMAIN_RE.search(raw):
        return True
    if ANTIEVASION_TG_SCHEME and (
        _TG_SCHEME_RE.search(merged)
        or _TG_URL_RE.search(merged)
        or _TG_INVITE_RE.search(merged)
        or _SPACED_TG_RE.search(normalized)
    ):
        return True
    if ANTIEVASION_ALT_SCHEMES:
        if _ALT_SCHEME_RE.search(raw):
            return True
        if _SPACED_SCHEME_RE.search(raw):
            return True
        if _COLON_SLASH_SCHEME_RE.search(raw):
            return True
        if _MULTILINE_URL_SCHEME_RE.search(raw):
            return True
    if ANTIEVASION_EMAIL and _EMAIL_RE.search(normalized):
        return True
    if ANTIEVASION_PUNYCODE and _PUNYCODE_RE.search(normalized):
        return True
    if ANTIEVASION_IPV4_SCHEMELESS and _IPV4_RE.search(normalized):
        return True
    if (
        include_usernames
        and ANTIEVASION_AT_CHANNEL
        and _TG_USERNAME_RE.search(normalized)
    ):
        return True
    return False


def _contains_email(text: str, *, already_normalized: bool = False) -> bool:
    if not text or not ANTIEVASION_EMAIL:
        return False
    normalized = text if already_normalized else _normalize_text(text)
    without_urls = _URL_RE.sub(" ", normalized)
    return bool(_EMAIL_RE.search(without_urls))


def _contains_at_channel(text: str, *, already_normalized: bool = False) -> bool:
    if not text or not ANTIEVASION_AT_CHANNEL:
        return False
    normalized = text if already_normalized else _normalize_text(text)
    return bool(_TG_USERNAME_RE.search(normalized))


def _contains_tg_scheme(text: str, *, already_normalized: bool = False) -> bool:
    if not text or not ANTIEVASION_TG_SCHEME:
        return False
    normalized = text if already_normalized else _normalize_text(text)
    merged = _merge_split_urls(normalized)
    return bool(
        _TG_SCHEME_RE.search(merged)
        or _TG_URL_RE.search(merged)
        or _TG_INVITE_RE.search(merged)
        or _SPACED_TG_RE.search(normalized)
    )


# =============================================================================
# ENTITY / BUTTON EXTRACTION
# =============================================================================

def _entity_type_str(entity: Any) -> str:
    et = getattr(entity, "type", None)
    if et is None:
        return ""
    if hasattr(et, "value"):
        try:
            return str(et.value).lower()
        except Exception:
            pass
    return str(et).lower()


def _extract_entity_urls(message: Any, _depth: int = 0) -> List[str]:
    if message is None or _depth > 4:
        return []
    urls: List[str] = []
    try:
        text = getattr(message, "text", None) or ""
        entities = getattr(message, "entities", None) or []
        for entity in entities:
            try:
                entity_type = _entity_type_str(entity)
                if entity_type == "text_link":
                    url = getattr(entity, "url", None)
                    if url:
                        urls.append(str(url))
                elif entity_type == "url":
                    offset = int(getattr(entity, "offset", 0) or 0)
                    length = int(getattr(entity, "length", 0) or 0)
                    if text and length > 0:
                        part = text[offset:offset + length]
                        if part:
                            urls.append(str(part))
            except Exception:
                continue

        caption = getattr(message, "caption", None) or ""
        caption_entities = getattr(message, "caption_entities", None) or []
        for entity in caption_entities:
            try:
                entity_type = _entity_type_str(entity)
                if entity_type == "text_link":
                    url = getattr(entity, "url", None)
                    if url:
                        urls.append(str(url))
                elif entity_type == "url":
                    offset = int(getattr(entity, "offset", 0) or 0)
                    length = int(getattr(entity, "length", 0) or 0)
                    if caption and length > 0:
                        part = caption[offset:offset + length]
                        if part:
                            urls.append(str(part))
            except Exception:
                continue

        reply = getattr(message, "reply_to_message", None)
        if reply is not None:
            urls.extend(_extract_entity_urls(reply, _depth + 1))

        story = getattr(message, "story", None)
        if story is not None:
            try:
                chat = getattr(story, "chat", None)
                if chat is not None:
                    username = getattr(chat, "username", None)
                    if username:
                        urls.append(f"https://t.me/{username}")
            except Exception:
                pass
    except Exception:
        pass
    return _unique_strings(urls)


def _has_link_entity(message: Any) -> bool:
    return bool(_extract_entity_urls(message))


def _extract_url_from_button(button: Any) -> Optional[str]:
    if button is None:
        return None
    try:
        url = getattr(button, "url", None)
        if url:
            return str(url)
        web_app = getattr(button, "web_app", None)
        if web_app is not None:
            web_url = getattr(web_app, "url", None)
            if web_url:
                return str(web_url)
            return "web_app://button"
        login_url = getattr(button, "login_url", None)
        if login_url is not None:
            login_web_url = getattr(login_url, "url", None)
            if login_web_url:
                return str(login_web_url)
            return "login_url://button"
        copy_text = getattr(button, "copy_text", None)
        if copy_text is not None:
            text = getattr(copy_text, "text", None)
            if not text and isinstance(copy_text, str):
                text = copy_text
            if text and _URL_IN_TEXT_RE.search(str(text)):
                return str(text)
        switch_q = getattr(button, "switch_inline_query", None)
        if switch_q and _URL_IN_TEXT_RE.search(str(switch_q)):
            return str(switch_q)
        switch_q_cc = getattr(
            button, "switch_inline_query_current_chat", None
        )
        if switch_q_cc and _URL_IN_TEXT_RE.search(str(switch_q_cc)):
            return str(switch_q_cc)
        cb = getattr(button, "callback_data", None)
        if cb and isinstance(cb, str) and _URL_IN_TEXT_RE.search(cb):
            return cb
        if getattr(button, "callback_game", None) is not None:
            return "callback_game://button"
        if getattr(button, "pay", None):
            return "pay://button"
    except Exception:
        pass
    return None


def _button_is_external(button: Any) -> bool:
    if button is None:
        return False
    try:
        return bool(
            getattr(button, "url", None)
            or getattr(button, "web_app", None) is not None
            or getattr(button, "login_url", None) is not None
            or getattr(button, "copy_text", None) is not None
        )
    except Exception:
        return False


def _extract_button_context(
    message: Any,
) -> Tuple[int, List[str], List[str], List[str]]:
    button_count = 0
    button_urls_external: List[str] = []
    button_texts: List[str] = []
    button_urls_raw: List[str] = []
    try:
        markup = getattr(message, "reply_markup", None)
        if markup is None:
            return 0, [], [], []
        rows = getattr(markup, "inline_keyboard", None)
        if rows is None:
            return 0, [], [], []
        for row in rows or []:
            for button in row or []:
                button_count += 1
                text = getattr(button, "text", None)
                if text:
                    button_texts.append(str(text))
                url = _extract_url_from_button(button)
                if url:
                    url_str = str(url)
                    button_urls_raw.append(url_str)
                    if not url_str.endswith("://button"):
                        button_urls_external.append(url_str)
    except Exception:
        pass
    return (
        button_count,
        _unique_strings(button_urls_external),
        button_texts,
        _unique_strings(button_urls_raw),
    )


def _extract_vcard_urls(message: Any) -> List[str]:
    if message is None:
        return []
    urls: List[str] = []
    try:
        contact = getattr(message, "contact", None)
        if contact is not None:
            website = getattr(contact, "website", None)
            if website:
                urls.append(str(website))
    except Exception:
        pass
    return _unique_strings(urls)


def _extract_venue_url(message: Any) -> Optional[str]:
    if message is None or not ANTIEVASION_VENUE_VCARD:
        return None
    try:
        venue = getattr(message, "venue", None)
        if venue is None:
            return None
        for attr in ("title", "address"):
            val = getattr(venue, attr, None)
            if not val:
                continue
            s = str(val)
            m = _URL_IN_TEXT_RE.search(s)
            if m:
                return m.group(0)
            normalized = _normalize_text(s)
            m = _DOMAIN_RE.search(normalized)
            if m and not _is_random_domain(m.group(0)):
                return m.group(0)
            if _TG_URL_RE.search(s):
                return s
            if _TG_USERNAME_RE.search(s):
                return s
        return None
    except Exception:
        return None


def _extract_poll_text(
    message: Any,
) -> Tuple[str, int, List[str]]:
    if message is None:
        return "", 0, []
    try:
        poll = getattr(message, "poll", None)
        if poll is None:
            return "", 0, []
        question = str(getattr(poll, "question", None) or "")
        options = getattr(poll, "options", None) or []
        option_texts: List[str] = []
        for option in options:
            option_text = getattr(option, "text", None)
            if option_text:
                option_texts.append(str(option_text))
        full = " ".join([question] + option_texts).strip()
        return full, len(option_texts), _extract_possible_urls(full)
    except Exception:
        return "", 0, []


def _get_message_button_data(
    message: Any,
) -> Tuple[int, List[str], List[str], List[str]]:
    return _extract_button_context(message)


def _get_message_button_texts(message: Any) -> List[str]:
    try:
        return _extract_button_context(message)[2]
    except Exception:
        return []


def _get_message_analysis_text(message: Any) -> str:
    if message is None:
        return ""
    parts: List[str] = []
    try:
        text = getattr(message, "text", None)
        if text:
            parts.append(str(text))
        caption = getattr(message, "caption", None)
        if caption:
            parts.append(str(caption))
        parts.extend(_get_message_button_texts(message))
        poll_text, _, _ = _extract_poll_text(message)
        if poll_text:
            parts.append(poll_text)
    except Exception:
        pass
    return "\n".join(x for x in parts if x).strip()[:MAX_ANALYSIS_TEXT_LENGTH]


# =============================================================================
# LAYER 0: TEXT CONTEXT
# =============================================================================

class _MessageContext:

    __slots__ = (
        "__weakref__",
        "text", "caption", "full_text", "normalized_text", "analysis_text",
        "button_count", "button_urls", "button_texts", "button_urls_raw",
        "is_forwarded", "is_protected", "is_auto_fwd",
        "entity_urls", "has_link_entity", "button_link_urls",
        "has_any_link", "has_button_link",
        "vcard_urls", "venue_url", "has_hidden_chars",
        "poll_text", "poll_options_count", "poll_urls",
        "hidden_char_count", "bidi_count", "script_counts", "mixed_scripts",
        "normalized_compact", "normalized_url_text",
        "emoji_count", "spam_emoji_count",
        "url_count", "domain_count", "telegram_link_count",
        "cta_count", "strong_word_count", "medium_word_count",
        "promo_word_count", "arabic_spam_count", "generic_word_count",
        "suspicious_separator_count", "repeated_char_count",
        "repeated_word_count",
        "forward_hint",
        "random_domains", "has_random_domain",
        "possible_urls",
        "financial_word_count",
        "ai_generated_score",
        "has_video", "has_nsfw_media", "has_sticker",
        "sticker_emoji", "reactions_count", "message_id", "chat_id",
        # 🆕 v4.0.9: Arabic short whitelist flag
        "is_arabic_short_whitelisted",
    )

    def __init__(self, message: Any = None, **kwargs: Any) -> None:
        self.text = ""
        self.caption = ""
        self.full_text = ""
        self.normalized_text = ""
        self.analysis_text = ""
        self.button_count = 0
        self.button_urls = []
        self.button_texts = []
        self.button_urls_raw = []
        self.is_forwarded = False
        self.is_protected = False
        self.is_auto_fwd = False
        self.entity_urls = []
        self.has_link_entity = False
        self.button_link_urls = []
        self.has_any_link = False
        self.has_button_link = False
        self.vcard_urls = []
        self.venue_url = None
        self.has_hidden_chars = False
        self.poll_text = ""
        self.poll_options_count = 0
        self.poll_urls = []
        self.hidden_char_count = 0
        self.bidi_count = 0
        self.script_counts = Counter()
        self.mixed_scripts = False
        self.normalized_compact = ""
        self.normalized_url_text = ""
        self.emoji_count = 0
        self.spam_emoji_count = 0
        self.url_count = 0
        self.domain_count = 0
        self.telegram_link_count = 0
        self.cta_count = 0
        self.strong_word_count = 0
        self.medium_word_count = 0
        self.promo_word_count = 0
        self.arabic_spam_count = 0
        self.generic_word_count = 0
        self.suspicious_separator_count = 0
        self.repeated_char_count = 0
        self.repeated_word_count = 0
        self.forward_hint = False
        self.random_domains = []
        self.has_random_domain = False
        self.possible_urls = []
        self.financial_word_count = 0
        self.ai_generated_score = 0
        self.has_video = False
        self.has_nsfw_media = False
        self.has_sticker = False
        self.sticker_emoji = ""
        self.reactions_count = 0
        self.message_id = 0
        self.chat_id = 0
        # 🆕 v4.0.9
        self.is_arabic_short_whitelisted = False

        for key, value in kwargs.items():
            if key in self.__slots__:
                setattr(self, key, value)

        if message is not None:
            self._populate(message)

    @classmethod
    def from_text(cls, text: str) -> "_MessageContext":
        ctx = cls()
        text = text or ""
        ctx.text = text
        ctx.full_text = text
        ctx.analysis_text = text[:MAX_ANALYSIS_TEXT_LENGTH]
        ctx.normalized_text = _normalize_text(ctx.analysis_text)
        ctx.normalized_compact = re.sub(
            r"[\W_]+", "", ctx.normalized_text, flags=re.UNICODE
        )
        ctx.normalized_url_text = _merge_split_urls(ctx.normalized_text)
        ctx.hidden_char_count = _hidden_char_count(text)
        ctx.bidi_count = _bidi_count(text)
        ctx.has_hidden_chars = ctx.hidden_char_count > 0
        ctx.script_counts = _script_counts(text)
        ctx.mixed_scripts = _has_mixed_suspicious_scripts(
            text, counts=ctx.script_counts
        )
        ctx.emoji_count = _count_emojis(text)
        ctx.spam_emoji_count = _count_spam_emojis(text)
        ctx.url_count = _count_text_urls(text)
        ctx.domain_count = len(_DOMAIN_RE.findall(ctx.normalized_url_text))
        ctx.telegram_link_count = len(
            _TG_URL_RE.findall(ctx.normalized_url_text)
        )
        ctx.cta_count = _count_word_matches(
            ctx.normalized_text, _CTA_WORDS, already_normalized=True
        )
        ctx.strong_word_count = _count_word_matches(
            ctx.normalized_text, _STRONG_SPAM_WORDS, already_normalized=True
        )
        ctx.medium_word_count = _count_word_matches(
            ctx.normalized_text, _MEDIUM_SPAM_WORDS, already_normalized=True
        )
        ctx.promo_word_count = _count_word_matches(
            ctx.normalized_text, _PROMO_WORDS, already_normalized=True
        )
        ctx.arabic_spam_count = _count_word_matches(
            ctx.normalized_text,
            (_ARABIC_SPAM_WORDS | _ARABIC_CTA_WORDS
             | _EXTRA_SCRIPT_SPAM_WORDS),
            already_normalized=True,
        )
        ctx.generic_word_count = _count_word_matches(
            ctx.normalized_text, _GENERIC_WORDS, already_normalized=True
        )
        ctx.financial_word_count = _count_word_matches(
            ctx.normalized_text, _FINANCIAL_SCAM_WORDS,
            already_normalized=True,
        )
        ctx.suspicious_separator_count = _count_separators(text)
        ctx.repeated_char_count = len(_REPEATED_CHAR_RE.findall(text))
        ctx.repeated_word_count = len(
            _REPEATED_WORD_RE.findall(ctx.normalized_text)
        )
        ctx.random_domains = _extract_random_domains_from_merged(
            ctx.normalized_url_text
        )
        ctx.has_random_domain = bool(ctx.random_domains)
        ctx.possible_urls = _extract_possible_urls(ctx.normalized_url_text)
        ctx.ai_generated_score = _compute_ai_generated_score(
            ctx.normalized_text
        )
        ctx.has_any_link = _contains_link_enhanced(
            ctx.analysis_text, include_usernames=False
        )
        # 🆕 v4.0.9: فحص whitelist
        ctx.is_arabic_short_whitelisted = _is_arabic_short_whitelisted(
            ctx.analysis_text
        )
        return ctx

    def _populate(self, message: Any) -> None:
        try:
            self.text = str(getattr(message, "text", None) or "")
            self.caption = str(getattr(message, "caption", None) or "")
            self.full_text = "\n".join(
                x for x in (self.text, self.caption) if x
            ).strip()
            self.analysis_text = _get_message_analysis_text(message)
            self.normalized_text = _normalize_text(self.analysis_text)
            self.normalized_compact = re.sub(
                r"[\W_]+", "", self.normalized_text, flags=re.UNICODE
            )
            self.normalized_url_text = _merge_split_urls(
                self.normalized_text
            )
            (
                self.button_count,
                self.button_urls,
                self.button_texts,
                self.button_urls_raw,
            ) = _extract_button_context(message)
            self.button_link_urls = list(self.button_urls)
            self.entity_urls = _extract_entity_urls(message)
            self.has_link_entity = bool(self.entity_urls)
            self.vcard_urls = _extract_vcard_urls(message)
            self.venue_url = _extract_venue_url(message)
            (
                self.poll_text,
                self.poll_options_count,
                self.poll_urls,
            ) = _extract_poll_text(message)
            self.has_hidden_chars = _has_hidden_chars(self.analysis_text)
            self.hidden_char_count = _hidden_char_count(self.analysis_text)
            self.bidi_count = _bidi_count(self.analysis_text)
            self.script_counts = _script_counts(self.analysis_text)
            self.mixed_scripts = _has_mixed_suspicious_scripts(
                self.analysis_text, counts=self.script_counts
            )
            self.emoji_count = _count_emojis(self.analysis_text)
            self.spam_emoji_count = _count_spam_emojis(self.analysis_text)
            self.url_count = _count_text_urls(self.analysis_text)
            self.domain_count = len(
                _DOMAIN_RE.findall(self.normalized_url_text)
            )
            self.telegram_link_count = len(
                _TG_URL_RE.findall(self.normalized_url_text)
            )
            self.cta_count = _count_word_matches(
                self.normalized_text, _CTA_WORDS, already_normalized=True
            )
            self.strong_word_count = _count_word_matches(
                self.normalized_text, _STRONG_SPAM_WORDS,
                already_normalized=True,
            )
            self.medium_word_count = _count_word_matches(
                self.normalized_text, _MEDIUM_SPAM_WORDS,
                already_normalized=True,
            )
            self.promo_word_count = _count_word_matches(
                self.normalized_text, _PROMO_WORDS,
                already_normalized=True,
            )
            self.arabic_spam_count = _count_word_matches(
                self.normalized_text,
                (_ARABIC_SPAM_WORDS | _ARABIC_CTA_WORDS
                 | _EXTRA_SCRIPT_SPAM_WORDS),
                already_normalized=True,
            )
            self.generic_word_count = _count_word_matches(
                self.normalized_text, _GENERIC_WORDS,
                already_normalized=True,
            )
            self.financial_word_count = _count_word_matches(
                self.normalized_text, _FINANCIAL_SCAM_WORDS,
                already_normalized=True,
            )
            self.suspicious_separator_count = _count_separators(
                self.analysis_text
            )
            self.repeated_char_count = len(
                _REPEATED_CHAR_RE.findall(self.analysis_text)
            )
            self.repeated_word_count = len(
                _REPEATED_WORD_RE.findall(self.normalized_text)
            )
            self.random_domains = _extract_random_domains_from_merged(
                self.normalized_url_text
            )
            self.has_random_domain = bool(self.random_domains)
            self.possible_urls = _extract_possible_urls(
                self.normalized_url_text
            )
            self.ai_generated_score = _compute_ai_generated_score(
                self.normalized_text
            )

            direct_button_urls = False
            try:
                _markup = getattr(message, "reply_markup", None)
                _rows = getattr(_markup, "inline_keyboard", None) or []
                for _row in _rows:
                    for _b in (_row or []):
                        _u = getattr(_b, "url", None)
                        if isinstance(_u, str) and _u.strip():
                            direct_button_urls = True
                            break
                    if direct_button_urls:
                        break
            except Exception:
                pass

            self.has_button_link = bool(
                self.button_link_urls
                or any(
                    "://button" in str(x) for x in self.button_urls_raw
                )
                or direct_button_urls
            )

            self.has_any_link = bool(
                self.has_link_entity
                or self.has_button_link
                or self.entity_urls
                or self.button_urls
                or self.vcard_urls
                or self.poll_urls
                or self.url_count
                or _contains_link_enhanced(
                    self.analysis_text, include_usernames=False
                )
            )
            self.is_forwarded = bool(
                getattr(message, "forward_origin", None)
                or getattr(message, "forward_from", None)
                or getattr(message, "forward_from_chat", None)
                or getattr(message, "forward_date", None)
                or getattr(message, "forward_sender_name", None)
                or getattr(message, "is_automatic_forward", False)
            )
            self.is_auto_fwd = bool(
                getattr(message, "is_automatic_forward", False)
            )
            self.is_protected = bool(
                getattr(message, "has_protected_content", False)
            )
            self.forward_hint = bool(
                getattr(message, "has_protected_content", False)
                and (
                    "محولة من" in self.full_text
                    or "محوّل من" in self.full_text
                    or "Forwarded from" in self.full_text
                )
            )

            self.has_video = bool(getattr(message, "video", None))
            self.has_sticker = bool(getattr(message, "sticker", None))
            sticker = getattr(message, "sticker", None)
            if sticker is not None:
                self.sticker_emoji = str(
                    getattr(sticker, "emoji", "") or ""
                )
            self.message_id = int(getattr(message, "message_id", 0) or 0)
            chat = getattr(message, "chat", None)
            if chat is not None:
                self.chat_id = int(getattr(chat, "id", 0) or 0)

            try:
                reactions = getattr(message, "reactions", None)
                if reactions is not None:
                    rlist = getattr(reactions, "reactions", None) or []
                    self.reactions_count = sum(
                        int(getattr(r, "total_count", 0) or 0)
                        for r in rlist
                    )
            except Exception:
                pass

            # 🆕 v4.0.9 FIX-AR-1: فحص whitelist للعربية القصيرة
            try:
                self.is_arabic_short_whitelisted = (
                    _is_arabic_short_whitelisted(self.analysis_text)
                )
            except Exception:
                self.is_arabic_short_whitelisted = False

            if DEBUG_DIAG and self.button_count > 0:
                try:
                    logger.info(
                        "🔘 BUTTONS_DETECTED | count=%d "
                        "urls=%d raw=%d has_link=%s texts=%s",
                        self.button_count,
                        len(self.button_urls),
                        len(self.button_urls_raw),
                        self.has_button_link,
                        self.button_texts[:5],
                    )
                except Exception:
                    pass

        except Exception as exc:
            if DEBUG_DIAG:
                try:
                    logger.debug("[DETECTOR] context error: %r", exc)
                except Exception:
                    pass


# =============================================================================
# HELPERS — AI-Generated Text Heuristic
# =============================================================================

def _compute_ai_generated_score(text: str) -> int:
    if not text or len(text) < 40:
        return 0

    score = 0
    words = _extract_words(text)

    if not words:
        return 0

    unique_ratio = len(set(w.lower() for w in words)) / len(words)
    if unique_ratio >= 0.75 and len(words) >= 30:
        score += 1
    if unique_ratio >= 0.85 and len(words) >= 50:
        score += 1

    sentences = re.split(r"[.!?]+\s+", text)
    if len(sentences) >= 4:
        lens = [len(s.split()) for s in sentences if s.strip()]
        if lens:
            mean_len = sum(lens) / len(lens)
            var = sum((x - mean_len) ** 2 for x in lens) / len(lens)
            if var < 5 and 8 <= mean_len <= 25:
                score += 1

    if not re.search(r"(?:lol|omg|wtf|خخخ|هههه|😂)", text.lower()):
        if len(words) >= 40:
            score += 1

    bullets = len(re.findall(r"(?:^|\n)\s*(?:[-•*]|\d+\.)\s", text))
    if bullets >= 3:
        score += 2

    return min(score, 4)


# =============================================================================
# BUTTON HELPERS
# =============================================================================

def _has_button_link(message_or_context: Any) -> bool:
    if isinstance(message_or_context, _MessageContext):
        return bool(
            message_or_context.has_button_link
            or message_or_context.button_link_urls
        )
    try:
        return bool(_extract_button_context(message_or_context)[1])
    except Exception:
        return False


def _extract_button_link_urls(message_or_context: Any) -> List[str]:
    if isinstance(message_or_context, _MessageContext):
        return list(message_or_context.button_link_urls)
    try:
        return list(_extract_button_context(message_or_context)[1])
    except Exception:
        return []


# =============================================================================
# SPAM WORD EXTRACTION
# =============================================================================

def _extract_spam_words(text: str) -> List[str]:
    if not text:
        return []
    normalized = _normalize_text(text)
    if not normalized:
        return []
    found: List[str] = []
    vocabularies = (
        _STRONG_SPAM_WORDS, _MEDIUM_SPAM_WORDS, _CTA_WORDS,
        _PROMO_WORDS, _ARABIC_SPAM_WORDS, _ARABIC_CTA_WORDS,
        _EXTRA_SCRIPT_SPAM_WORDS, _FINANCIAL_SCAM_WORDS,
    )
    for vocabulary in vocabularies:
        try:
            pattern = _vocab_regex(vocabulary)
            matches = pattern.findall(normalized)
            if matches:
                found.extend(str(m) for m in matches)
        except Exception:
            continue

    compact = re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)
    compact_candidates = {
        "megapack", "megapacks", "viralcontent", "openhere",
        "viewleak", "checkthis", "clickhere", "watchnow",
        "exclusivecontent", "freecrypto", "airdropclaim",
    }
    for word in compact_candidates:
        if _compact_target_present(compact, word):
            found.append(word)
    return _unique_strings(found)


# =============================================================================
# EVASION
# =============================================================================

def _compact_evasion_variants(
    text: str,
    *,
    already_normalized: bool = False,
) -> List[str]:
    if not text:
        return []
    normalized = text if already_normalized else _normalize_text(text)
    variants = [normalized]
    compact = re.sub(r"[^\w]+", "", normalized, flags=re.UNICODE)
    if compact != normalized:
        variants.append(compact)
    no_emoji = re.sub(r"\s+", "", _EMOJI_STRIP_RE.sub("", normalized))
    if no_emoji != normalized:
        variants.append(no_emoji)
    return _unique_strings(variants)


def _compact_target_present(compact_text: str, target: str) -> bool:
    if not compact_text or not target:
        return False
    if compact_text == target:
        return True
    if compact_text.startswith(target) or compact_text.endswith(target):
        return True
    return bool(
        re.search(
            rf"(?:^|(?:click|watch|view|open|check|"
            rf"exclusive|mega|viral|content|pack|"
            rf"free|crypto|claim|win|bonus))"
            rf"{re.escape(target)}"
            rf"(?:$|(?:now|here|content|pack|clips?|bonus))",
            compact_text,
            flags=re.IGNORECASE,
        )
    )


def _detect_split_spam_words(
    text: str,
    *,
    already_normalized: bool = False,
) -> List[str]:
    if not text or not ANTIEVASION_COMPACT_WORDS:
        return []
    variants = _compact_evasion_variants(
        text, already_normalized=already_normalized
    )
    targets = (
        set(_STRONG_SPAM_WORDS)
        | set(_PROMO_WORDS)
        | set(_FINANCIAL_SCAM_WORDS)
        | {
            "viralcontent", "megapack", "openhere",
            "viewleak", "watchnow", "clickhere", "exclusivecontent",
            "freecrypto", "airdropclaim",
        }
    )
    compact_targets = {
        re.sub(r"[\W_]+", "", str(x).casefold()) for x in targets
    }
    found: List[str] = []
    for variant in variants:
        compact_variant = re.sub(
            r"[\W_]+", "", variant.casefold(), flags=re.UNICODE
        )
        for target in compact_targets:
            if len(target) < 4:
                continue
            if _compact_target_present(compact_variant, target):
                found.append(target)
    return _unique_strings(found)


def _detect_url_obfuscation(
    text: str,
    *,
    already_normalized: bool = False,
    merged: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    if not text:
        return False, []
    raw = str(text)
    normalized = raw if already_normalized else _normalize_text(raw)
    reasons: List[str] = []
    if _SPACED_SCHEME_RE.search(raw):
        reasons.append("spaced_url_scheme")
    if _ALT_SCHEME_RE.search(raw):
        reasons.append("alternate_url_scheme")
    if _COLON_SLASH_SCHEME_RE.search(raw):
        reasons.append("obfuscated_scheme")
    if _MULTILINE_URL_SCHEME_RE.search(raw):
        reasons.append("multiline_scheme")
    if _SPACED_TG_RE.search(normalized):
        reasons.append("obfuscated_telegram_domain")
    if _DOT_DOMAIN_RE.search(normalized):
        reasons.append("dot_domain")
    if _DOT_WORD_RE.search(normalized):
        reasons.append("dot_word_domain")
    if _SPACED_DOMAIN_RE.search(normalized):
        reasons.append("spaced_domain")
    if ANTIEVASION_MULTILINE_URL and _MULTILINE_DOMAIN_RE.search(raw):
        reasons.append("multiline_domain")
    if _DOT_LIKE_RE.search(raw):
        reasons.append("bracketed_dot")
    if ANTIEVASION_PUNYCODE and _PUNYCODE_RE.search(normalized):
        reasons.append("punycode")
    if ANTIEVASION_IPV4_SCHEMELESS and _IPV4_RE.search(normalized):
        reasons.append("ipv4")
    if ANTIEVASION_EMAIL and _contains_email(
        normalized, already_normalized=True
    ):
        reasons.append("email")
    if _MULTISPACE_SPLIT_RE.search(normalized):
        reasons.append("split_scheme_or_domain")
    if ANTIEVASION_RANDOM_DOMAIN and _has_random_domain(
        normalized, merged=merged
    ):
        reasons.append("random_domain")
    return bool(reasons), _unique_strings(reasons)


def _detect_unicode_evasion(
    text: str,
    *,
    script_counts: Optional[Counter] = None,
) -> Tuple[int, List[str]]:
    if not text:
        return 0, []
    score = 0
    reasons: List[str] = []
    hidden = _hidden_char_count(text)
    bidi = _bidi_count(text)
    if hidden:
        score += min(4, 1 + hidden // 2)
        reasons.append(f"hidden_chars:{hidden}")
    if bidi:
        score += min(4, 1 + bidi // 2)
        reasons.append(f"bidi_chars:{bidi}")
    if _has_mixed_suspicious_scripts(text, counts=script_counts):
        score += 2
        reasons.append("mixed_scripts")
    if ANTIEVASION_COMBINING or ANTIEVASION_EXTENDED_COMBINING:
        combining = sum(
            1 for ch in text if unicodedata.category(ch) == "Mn"
        )
        if combining >= 3:
            score += min(3, 1 + combining // 5)
            reasons.append(f"combining_marks:{combining}")
    return min(score, 8), reasons


def _postbot_pattern_confidence(
    text: str,
    *,
    button_count: int = 0,
    button_urls: Optional[Sequence[str]] = None,
    already_normalized: bool = False,
    merged: Optional[str] = None,
) -> int:
    if not text:
        return 0
    normalized = text if already_normalized else _normalize_text(text)
    if merged is None:
        merged = _merge_split_urls(normalized)
    confidence = 0
    strong = _count_word_matches(
        normalized, _STRONG_SPAM_WORDS, already_normalized=True
    )
    promo = _count_word_matches(
        normalized, _PROMO_WORDS, already_normalized=True
    )
    cta = _count_word_matches(
        normalized, _CTA_WORDS, already_normalized=True
    )
    spam_emojis = _count_spam_emojis(text)
    context_hits = _count_unique_matches(merged, _PROMO_CONTEXT_PATTERNS)
    if strong >= 2:
        confidence += 2
    elif strong == 1:
        confidence += 1
    if promo >= 2:
        confidence += 1
    if cta >= 1:
        confidence += 1
    if button_count >= 2:
        confidence += 1
    if button_count >= 3:
        confidence += 1
    if button_urls and len(button_urls) >= 2:
        confidence += 1
    if spam_emojis >= 2:
        confidence += 1
    if _NUMBER_PROMO_RE.search(merged):
        confidence += 2
    if _PACK_RE.search(merged):
        confidence += 1
    if context_hits:
        confidence += 1
    if promo >= 2 and cta >= 1 and button_count >= 2:
        confidence += 2
    if ANTIEVASION_RANDOM_DOMAIN and _has_random_domain(
        normalized, merged=merged
    ):
        confidence += 2
    return min(confidence, 10)


def _is_postbot_pattern(
    text: str,
    *,
    button_count: int = 0,
    button_urls: Optional[Sequence[str]] = None,
    already_normalized: bool = False,
) -> bool:
    if not text:
        return False
    normalized = text if already_normalized else _normalize_text(text)
    merged = _merge_split_urls(normalized)
    confidence = _postbot_pattern_confidence(
        normalized,
        button_count=button_count,
        button_urls=button_urls,
        already_normalized=True,
        merged=merged,
    )
    if confidence >= POSTBOT_AUTO_BLOCK_CONFIDENCE:
        return True
    return any(pattern.search(merged) for pattern in _POSTBOT_REGEXES)


def _count_text_urls(text: str, *, already_normalized: bool = False) -> int:
    if not text:
        return 0
    normalized = text if already_normalized else _normalize_text(text)
    merged = _merge_split_urls(normalized)
    urls = _extract_possible_urls(merged)
    if not urls and _has_domain_pattern(normalized):
        return 1
    return len(urls)


def _message_has_media(context_or_message: Any) -> bool:
    if context_or_message is None:
        return False
    if isinstance(context_or_message, _MessageContext):
        return bool(context_or_message.caption)
    attrs = (
        "photo", "video", "animation", "document", "audio", "voice",
        "video_note", "sticker", "contact", "location", "venue",
    )
    for attr in attrs:
        try:
            if getattr(context_or_message, attr, None):
                return True
        except Exception:
            continue
    return False


def _text_density_signals(text: str) -> Tuple[int, List[str]]:
    if not text:
        return 0, []
    length = len(text)
    if length < 8:
        return 0, []
    score = 0
    reasons: List[str] = []
    digits = sum(ch.isdigit() for ch in text)
    letters = sum(ch.isalpha() for ch in text)
    symbols = sum(not ch.isalnum() and not ch.isspace() for ch in text)
    digit_ratio = digits / max(length, 1)
    symbol_ratio = symbols / max(length, 1)
    if length >= 40 and digit_ratio >= 0.45:
        score += 2
        reasons.append("high_digit_density")
    elif length >= 25 and digit_ratio >= 0.65:
        score += 2
        reasons.append("very_high_digit_density")
    if length >= 40 and symbol_ratio >= 0.45:
        score += 2
        reasons.append("high_symbol_density")
    if len(text.split()) <= 3 and (digits >= 8 or symbols >= 8):
        score += 1
        reasons.append("short_symbol_numeric_payload")
    if letters >= 8:
        upper = sum(ch.isupper() for ch in text)
        if upper / max(letters, 1) >= 0.85:
            score += 1
            reasons.append("excessive_caps")
    return min(score, 4), reasons


def _detect_phone_or_contact_evasion(
    text: str,
    *,
    already_normalized: bool = False,
) -> Tuple[int, List[str]]:
    if not text:
        return 0, []
    reasons: List[str] = []
    score = 0
    normalized = text if already_normalized else _normalize_text(text)
    has_phone = bool(_PHONE_RE.search(normalized))
    if has_phone:
        score += 1
        reasons.append("phone_like_sequence")
    if has_phone and (
        _count_word_matches(
            normalized, _CTA_WORDS, already_normalized=True
        )
        or _contains_link_enhanced(
            normalized, include_usernames=False,
            already_normalized=True,
        )
    ):
        score += 2
        reasons.append("contact_with_promotion")
    return min(score, 3), reasons


def _detect_structural_evasion(
    text: str,
    *,
    already_normalized: bool = False,
) -> Tuple[int, List[str]]:
    if not text:
        return 0, []
    score = 0
    reasons: List[str] = []
    if _MULTISPACE_SPLIT_RE.search(text):
        score += 1
        reasons.append("character_split")
    if ANTIEVASION_EMOJI_SEPARATOR and _EMOJI_SPLIT_RE.search(text):
        score += 2
        reasons.append("emoji_character_split")
    if ANTIEVASION_MULTILINE_URL and _MULTILINE_DOMAIN_RE.search(text):
        score += 2
        reasons.append("multiline_url")
    if _LONG_DOMAIN_LABEL_RE.search(_merge_split_urls(text)):
        score += 2
        reasons.append("long_domain_label")
    return min(score, 4), reasons


# =============================================================================
# 🆕 v4.0.9 FIX-AR-2: _looks_like_normal_conversation — Enhanced
# =============================================================================

def _looks_like_normal_conversation(text: str) -> bool:
    """
    🆕 v4.0.9 FIX-AR-2: تحسين كشف المحادثات الطبيعية، خاصة العربية القصيرة.
    """
    if not text:
        return True

    # 🆕 v4.0.9: فحص العربية القصيرة أولاً
    if _is_arabic_short_whitelisted(text):
        return True

    normalized = _normalize_text(text)
    words = _extract_words(normalized)
    if not words:
        return True
    generic_hits = sum(word in _GENERIC_WORDS for word in words)
    strong_hits = _count_word_matches(
        normalized, _STRONG_SPAM_WORDS, already_normalized=True
    )
    promo_hits = _count_word_matches(
        normalized, _PROMO_WORDS, already_normalized=True
    )
    financial_hits = _count_word_matches(
        normalized, _FINANCIAL_SCAM_WORDS, already_normalized=True
    )
    link = _contains_link_enhanced(
        normalized, include_usernames=False, already_normalized=True
    )
    # 🆕 v4.0.9: رسائل عربية قصيرة بدون spam
    if (
        _is_arabic_dominant(text)
        and len(text) <= ARABIC_SHORT_MAX_CHARS
        and len(words) <= ARABIC_SHORT_MAX_WORDS
        and strong_hits == 0
        and promo_hits == 0
        and financial_hits == 0
        and not link
    ):
        return True

    if (
        generic_hits >= 1 and strong_hits == 0
        and promo_hits <= 1 and financial_hits == 0
        and not link and len(words) <= 12
    ):
        return True
    if (
        len(words) >= 8 and strong_hits == 0
        and promo_hits <= 1 and financial_hits == 0
        and not link
    ):
        return True
    return False


# =============================================================================
# TEXT LAYER SCORING (LAYER 0)
# =============================================================================

def _compute_spam_score(
    context_or_message: Any,
    *,
    return_diagnostics: bool = False,
) -> Any:
    try:
        if isinstance(context_or_message, _MessageContext):
            ctx = context_or_message
        else:
            ctx = _MessageContext(context_or_message)

        text = ctx.analysis_text or ""
        normalized = ctx.normalized_text or ""

        if not text:
            result = {
                "score": 0, "reasons": [], "confidence": "none",
                "hard": False, "critical": False,
                "postbot_confidence": 0,
                "signal_categories": [], "independent_signals": 0,
                "random_domains": [], "has_random_domain": False,
                "is_button_only_case": False,
            }
            return result if return_diagnostics else (0, [])

        # 🆕 v4.0.9 FIX-AR-4: EARLY EXIT للرسائل العربية القصيرة
        if getattr(ctx, "is_arabic_short_whitelisted", False):
            if DEBUG_SPAM:
                try:
                    logger.debug(
                        "[SPAM] score=0 (arabic_short_whitelist) "
                        "text=%r",
                        text[:60],
                    )
                except Exception:
                    pass
            result = {
                "score": 0, "reasons": ["arabic_short_whitelist"],
                "confidence": "none", "hard": False, "critical": False,
                "postbot_confidence": 0,
                "signal_categories": ["whitelist"],
                "independent_signals": 0,
                "random_domains": [], "has_random_domain": False,
                "is_button_only_case": False,
                "category_scores": {},
            }
            return result if return_diagnostics else (0, ["arabic_short_whitelist"])

        merged_text = ctx.normalized_url_text or _merge_split_urls(normalized)

        reasons: List[str] = []
        link_score = 0
        content_score = 0
        cta_score = 0
        evasion_score = 0
        structure_score = 0
        context_score = 0
        independent_categories = set()

        link_detected = _contains_link_enhanced(
            normalized, include_usernames=False, already_normalized=True
        )
        text_url_count = ctx.url_count
        url_obfuscated, url_reasons = _detect_url_obfuscation(
            normalized, already_normalized=True, merged=merged_text
        )

        if ANTIEVASION_ENTITY_LINK and ctx.has_link_entity:
            link_score = _cap_score(link_score, 3, _SCORE_CAP_LINK)
            reasons.append("link_entity")

        external_buttons = len(ctx.button_link_urls)
        if ANTIEVASION_BUTTON_LINK and external_buttons:
            if external_buttons >= 3:
                added, reason = 5, f"external_buttons:{external_buttons}"
            elif external_buttons == 2:
                added, reason = 4, "external_buttons:2"
            else:
                added, reason = 2, "external_button"
            link_score = _cap_score(link_score, added, _SCORE_CAP_LINK)
            reasons.append(reason)

        if ANTIEVASION_BUTTON_WEBAPP and any(
            "web_app://button" in str(x) for x in ctx.button_urls_raw
        ):
            link_score = _cap_score(link_score, 2, _SCORE_CAP_LINK)
            reasons.append("webapp_button")

        if ANTIEVASION_BUTTON_LOGINURL and any(
            "login_url://button" in str(x) for x in ctx.button_urls_raw
        ):
            link_score = _cap_score(link_score, 2, _SCORE_CAP_LINK)
            reasons.append("loginurl_button")

        if any(
            "callback_game://button" in str(x)
            or "pay://button" in str(x)
            for x in ctx.button_urls_raw
        ):
            link_score = _cap_score(link_score, 2, _SCORE_CAP_LINK)
            reasons.append("callback_game_or_pay")

        if link_detected:
            link_score = _cap_score(link_score, 3, _SCORE_CAP_LINK)
            reasons.append("link_detected")

        if text_url_count >= 3:
            link_score = _cap_score(link_score, 4, _SCORE_CAP_LINK)
            reasons.append(f"text_urls:{text_url_count}")
        elif text_url_count == 2:
            link_score = _cap_score(link_score, 3, _SCORE_CAP_LINK)
            reasons.append("text_urls:2")
        elif text_url_count == 1:
            link_score = _cap_score(link_score, 1, _SCORE_CAP_LINK)
            reasons.append("text_url")

        if _contains_tg_scheme(normalized, already_normalized=True):
            link_score = _cap_score(link_score, 3, _SCORE_CAP_LINK)
            reasons.append("telegram_link")

        if _contains_email(normalized, already_normalized=True):
            link_score = _cap_score(link_score, 1, _SCORE_CAP_LINK)
            reasons.append("email_link")

        if ANTIEVASION_PUNYCODE and _PUNYCODE_RE.search(normalized):
            link_score = _cap_score(link_score, 2, _SCORE_CAP_LINK)
            reasons.append("punycode_domain")

        if ANTIEVASION_IPV4_SCHEMELESS and _IPV4_RE.search(normalized):
            link_score = _cap_score(link_score, 2, _SCORE_CAP_LINK)
            reasons.append("ipv4_link")

        if ANTIEVASION_RANDOM_DOMAIN and ctx.has_random_domain:
            link_score = _cap_score(link_score, 3, _SCORE_CAP_LINK)
            reasons.append(
                "random_domain:" + ",".join(ctx.random_domains[:3])
            )

        if _contains_at_channel(normalized, already_normalized=True):
            reasons.append("telegram_username")

        if link_score > 0 or ctx.has_link_entity or ctx.has_button_link:
            independent_categories.add("link")

        if ctx.button_count >= 4:
            cta_score = _cap_score(cta_score, 2, _SCORE_CAP_CTA)
            reasons.append(f"many_buttons:{ctx.button_count}")
        elif ctx.button_count == 3:
            cta_score = _cap_score(cta_score, 1, _SCORE_CAP_CTA)
            reasons.append("three_buttons")
        elif ctx.button_count == 2:
            cta_score = _cap_score(cta_score, 1, _SCORE_CAP_CTA)
            reasons.append("two_buttons")

        button_text = " ".join(ctx.button_texts)
        button_cta_count = _count_word_matches(button_text, _CTA_WORDS)
        if button_cta_count >= 3:
            cta_score = _cap_score(cta_score, 3, _SCORE_CAP_CTA)
            reasons.append(f"button_cta:{button_cta_count}")
        elif button_cta_count >= 2:
            cta_score = _cap_score(cta_score, 2, _SCORE_CAP_CTA)
            reasons.append("button_cta:2")
        elif button_cta_count == 1:
            cta_score = _cap_score(cta_score, 1, _SCORE_CAP_CTA)
            reasons.append("button_cta")

        strong = ctx.strong_word_count
        medium = ctx.medium_word_count
        promo = ctx.promo_word_count
        arabic = ctx.arabic_spam_count
        cta = ctx.cta_count
        financial = ctx.financial_word_count

        if strong >= 4:
            content_score = _cap_score(content_score, 6, _SCORE_CAP_CONTENT)
            reasons.append(f"strong_spam_words:{strong}")
        elif strong == 3:
            content_score = _cap_score(content_score, 5, _SCORE_CAP_CONTENT)
            reasons.append("strong_spam_words:3")
        elif strong == 2:
            content_score = _cap_score(content_score, 3, _SCORE_CAP_CONTENT)
            reasons.append("strong_spam_words:2")
        elif strong == 1:
            content_score = _cap_score(content_score, 1, _SCORE_CAP_CONTENT)
            reasons.append("strong_spam_word")

        if medium >= 4:
            content_score = _cap_score(content_score, 3, _SCORE_CAP_CONTENT)
            reasons.append(f"medium_spam_words:{medium}")
        elif medium >= 2:
            content_score = _cap_score(content_score, 2, _SCORE_CAP_CONTENT)
            reasons.append(f"medium_spam_words:{medium}")

        if promo >= 4:
            content_score = _cap_score(content_score, 4, _SCORE_CAP_CONTENT)
            reasons.append(f"promo_words:{promo}")
        elif promo >= 2:
            content_score = _cap_score(content_score, 2, _SCORE_CAP_CONTENT)
            reasons.append(f"promo_words:{promo}")

        if arabic >= 4:
            content_score = _cap_score(content_score, 4, _SCORE_CAP_CONTENT)
            reasons.append(f"arabic_spam_words:{arabic}")
        elif arabic >= 2:
            content_score = _cap_score(content_score, 2, _SCORE_CAP_CONTENT)
            reasons.append(f"arabic_spam_words:{arabic}")

        if financial >= 3:
            content_score = _cap_score(content_score, 4, _SCORE_CAP_CONTENT)
            reasons.append(f"financial_scam_words:{financial}")
        elif financial >= 1:
            content_score = _cap_score(content_score, 2, _SCORE_CAP_CONTENT)
            reasons.append(f"financial_words:{financial}")

        if cta >= 4:
            cta_score = _cap_score(cta_score, 3, _SCORE_CAP_CTA)
            reasons.append(f"cta_words:{cta}")
        elif cta >= 2:
            cta_score = _cap_score(cta_score, 2, _SCORE_CAP_CTA)
            reasons.append(f"cta_words:{cta}")

        if content_score > 0:
            independent_categories.add("content")
        if cta_score > 0:
            independent_categories.add("cta")

        has_number_pack = bool(_NUMBER_PROMO_RE.search(merged_text))
        has_pack = bool(_PACK_RE.search(merged_text))
        if has_number_pack:
            context_score = _cap_score(context_score, 3, _SCORE_CAP_CONTEXT)
            reasons.append("large_pack_number")
        if has_pack:
            context_score = _cap_score(context_score, 1, _SCORE_CAP_CONTEXT)
            reasons.append("pack_pattern")

        context_hits = _count_unique_matches(
            merged_text, _PROMO_CONTEXT_PATTERNS
        )
        if context_hits >= 3:
            context_score = _cap_score(context_score, 5, _SCORE_CAP_CONTEXT)
            reasons.append(f"promo_context:{context_hits}")
        elif context_hits == 2:
            context_score = _cap_score(context_score, 3, _SCORE_CAP_CONTEXT)
            reasons.append("promo_context:2")
        elif context_hits == 1:
            context_score = _cap_score(context_score, 1, _SCORE_CAP_CONTEXT)
            reasons.append("promo_context")
        if context_score > 0:
            independent_categories.add("context")

        postbot_confidence = _postbot_pattern_confidence(
            normalized,
            button_count=ctx.button_count,
            button_urls=ctx.button_urls,
            already_normalized=True,
            merged=merged_text,
        )
        if postbot_confidence >= 6:
            context_score = _cap_score(context_score, 3, _SCORE_CAP_CONTEXT)
            reasons.append(f"postbot:very_high:{postbot_confidence}")
        elif postbot_confidence >= 4:
            context_score = _cap_score(context_score, 2, _SCORE_CAP_CONTEXT)
            reasons.append(f"postbot:high:{postbot_confidence}")
        elif postbot_confidence >= 2:
            context_score = _cap_score(context_score, 1, _SCORE_CAP_CONTEXT)
            reasons.append(f"postbot:{postbot_confidence}")

        spam_emojis = ctx.spam_emoji_count
        if spam_emojis >= 6:
            cta_score = _cap_score(cta_score, 2, _SCORE_CAP_CTA)
            reasons.append(f"spam_emojis:{spam_emojis}")
        elif spam_emojis >= 3:
            cta_score = _cap_score(cta_score, 1, _SCORE_CAP_CTA)
            reasons.append(f"spam_emojis:{spam_emojis}")

        split_words = _detect_split_spam_words(
            normalized, already_normalized=True
        )
        if split_words:
            evasion_score = _cap_score(
                evasion_score,
                min(4, 1 + len(split_words)),
                _SCORE_CAP_EVASION,
            )
            reasons.append(
                "split_spam_words:" + ",".join(split_words[:5])
            )

        if url_obfuscated:
            evasion_score = _cap_score(
                evasion_score,
                min(5, 1 + len(url_reasons)),
                _SCORE_CAP_EVASION,
            )
            reasons.extend("url_evasion:" + x for x in url_reasons)

        unicode_score, unicode_reasons = _detect_unicode_evasion(
            text, script_counts=ctx.script_counts
        )
        if unicode_score:
            evasion_score = _cap_score(
                evasion_score, unicode_score, _SCORE_CAP_EVASION
            )
            reasons.extend(
                "unicode_evasion:" + x for x in unicode_reasons
            )
        if ctx.mixed_scripts:
            evasion_score = _cap_score(
                evasion_score, 2, _SCORE_CAP_EVASION
            )
            reasons.append("suspicious_mixed_scripts")

        structural_score, structural_reasons = _detect_structural_evasion(
            text, already_normalized=True
        )
        if structural_score:
            structure_score = _cap_score(
                structure_score, structural_score, _SCORE_CAP_STRUCTURE
            )
            reasons.extend(
                "structural_evasion:" + x for x in structural_reasons
            )

        density_score, density_reasons = _text_density_signals(text)
        if density_score:
            structure_score = _cap_score(
                structure_score, density_score, _SCORE_CAP_STRUCTURE
            )
            reasons.extend("density:" + x for x in density_reasons)

        contact_score, contact_reasons = _detect_phone_or_contact_evasion(
            normalized, already_normalized=True
        )
        if contact_score:
            context_score = _cap_score(
                context_score, contact_score, _SCORE_CAP_CONTEXT
            )
            reasons.extend("contact:" + x for x in contact_reasons)

        if ctx.suspicious_separator_count >= 2:
            structure_score = _cap_score(
                structure_score, 1, _SCORE_CAP_STRUCTURE
            )
            reasons.append("separator_evasion")
        if ctx.repeated_char_count:
            structure_score = _cap_score(
                structure_score, 1, _SCORE_CAP_STRUCTURE
            )
            reasons.append("repeated_characters")
        if ctx.repeated_word_count:
            structure_score = _cap_score(
                structure_score, 1, _SCORE_CAP_STRUCTURE
            )
            reasons.append("repeated_words")

        has_media = _message_has_media(context_or_message)
        if has_media and (ctx.button_count >= 2 or cta >= 2):
            context_score = _cap_score(
                context_score, 2, _SCORE_CAP_CONTEXT
            )
            reasons.append("media_plus_promotion")

        if ANTIEVASION_POLL and ctx.poll_urls:
            link_score = _cap_score(link_score, 2, _SCORE_CAP_LINK)
            reasons.append("poll_with_url")
        if ANTIEVASION_VENUE_VCARD:
            if ctx.vcard_urls:
                link_score = _cap_score(link_score, 1, _SCORE_CAP_LINK)
                reasons.append("vcard_url")
            if ctx.venue_url:
                link_score = _cap_score(link_score, 1, _SCORE_CAP_LINK)
                reasons.append("venue_url")

        preliminary_score = (
            link_score + content_score + cta_score
            + evasion_score + structure_score + context_score
        )
        if ctx.is_forwarded and preliminary_score >= 5:
            context_score = _cap_score(
                context_score, 1, _SCORE_CAP_CONTEXT
            )
            reasons.append("forwarded_spam_context")

        if (
            (promo >= 2 or strong >= 2)
            and cta >= 1
            and (ctx.button_link_urls or text_url_count)
        ):
            context_score = _cap_score(
                context_score, 3, _SCORE_CAP_CONTEXT
            )
            reasons.append("high_confidence_marketing_spam")

        if (
            has_pack and has_number_pack
            and (ctx.button_link_urls or link_detected)
        ):
            context_score = _cap_score(
                context_score, 4, _SCORE_CAP_CONTEXT
            )
            reasons.append("pack_number_external_cta")

        category_hits = _count_word_matches(
            normalized,
            {
                "mfm", "dilf", "busty", "milf", "bj",
                "xxx", "nsfw", "porn", "nude", "leak", "clips",
            },
            already_normalized=True,
        )
        if category_hits >= 4 and (
            ctx.button_link_urls or cta >= 1 or text_url_count
        ):
            content_score = _cap_score(
                content_score, 4, _SCORE_CAP_CONTENT
            )
            reasons.append("multiple_spam_categories")

        if url_obfuscated and (strong >= 1 or promo >= 1 or cta >= 1):
            evasion_score = _cap_score(
                evasion_score, 2, _SCORE_CAP_EVASION
            )
            reasons.append("obfuscated_promotion")

        if ctx.has_hidden_chars and (
            link_detected or strong >= 1 or promo >= 1
        ):
            evasion_score = _cap_score(
                evasion_score, 2, _SCORE_CAP_EVASION
            )
            reasons.append("hidden_evasion_with_spam")

        if (
            _contains_at_channel(normalized, already_normalized=True)
            and (cta >= 1 or promo >= 1 or strong >= 1)
        ):
            cta_score = _cap_score(cta_score, 1, _SCORE_CAP_CTA)
            reasons.append("telegram_username_with_promotion")

        if (
            ANTIEVASION_RANDOM_DOMAIN and ctx.has_random_domain
            and (cta >= 1 or promo >= 1 or strong >= 1)
        ):
            context_score = _cap_score(
                context_score, 3, _SCORE_CAP_CONTEXT
            )
            reasons.append("random_domain_with_promotion")

        if ctx.ai_generated_score >= 3 and (
            cta >= 1 or promo >= 1 or link_detected
        ):
            context_score = _cap_score(
                context_score, 2, _SCORE_CAP_CONTEXT
            )
            reasons.append(
                f"ai_generated_pattern:{ctx.ai_generated_score}"
            )

        if (
            financial >= 2
            and (link_detected or ctx.button_link_urls)
            and (cta >= 1 or promo >= 1)
        ):
            context_score = _cap_score(
                context_score, 4, _SCORE_CAP_CONTEXT
            )
            reasons.append("financial_scam_combo")

        if evasion_score > 0:
            independent_categories.add("evasion")
        if structure_score > 0:
            independent_categories.add("structure")
        if postbot_confidence >= 4 and context_score > 0:
            independent_categories.add("postbot")

        score = (
            link_score + content_score + cta_score
            + evasion_score + structure_score + context_score
        )

        independent_signals = len(independent_categories)
        if independent_signals >= 4 and (
            link_score > 0 or content_score > 0
        ):
            score += 2
            reasons.append("multi_category_evidence")
        elif independent_signals >= 3:
            score += 1
            reasons.append("independent_evidence")

        only_weak_username = (
            _contains_at_channel(normalized, already_normalized=True)
            and not link_detected
            and strong == 0
            and promo == 0
            and cta == 0
            and not ctx.button_link_urls
            and not url_obfuscated
        )
        if only_weak_username:
            score = min(score, 1)

        is_button_only_case = bool(
            link_score > 0
            and ctx.has_button_link
            and not link_detected
        )

        if (
            link_score > 0
            and content_score == 0
            and cta_score == 0
            and evasion_score == 0
            and context_score == 0
            and structure_score == 0
            and not is_button_only_case
        ):
            score = min(score, 4)
            reasons.append("link_only_capped")

        score = max(0, min(MAX_SPAM_SCORE, int(score)))
        reasons = _unique_strings(reasons)[:MAX_REASON_COUNT]

        if score >= SPAM_CRITICAL_THRESHOLD:
            confidence = "critical"
        elif score >= SPAM_HARD_THRESHOLD:
            confidence = "very_high"
        elif score >= SPAM_SCORE_THRESHOLD:
            confidence = "high"
        elif score >= 3:
            confidence = "medium"
        elif score >= 1:
            confidence = "low"
        else:
            confidence = "none"

        hard = bool(
            score >= SPAM_HARD_THRESHOLD
            and (
                independent_signals >= 2
                or (strong >= 2 and cta >= 1)
                or (
                    url_obfuscated
                    and (promo >= 1 or strong >= 1 or cta >= 1)
                )
                or (
                    ANTIEVASION_RANDOM_DOMAIN
                    and ctx.has_random_domain
                    and (cta >= 1 or promo >= 1)
                )
                or (
                    is_button_only_case
                    and external_buttons >= 3
                )
                or financial >= 2
            )
        )

        critical = bool(
            score >= SPAM_CRITICAL_THRESHOLD
            and (
                independent_signals >= 3
                or (strong >= 3 and (link_detected or cta >= 1))
                or (url_obfuscated and strong >= 2)
                or (
                    ANTIEVASION_RANDOM_DOMAIN
                    and ctx.has_random_domain
                    and (ctx.button_link_urls or strong >= 2)
                )
            )
        )

        if DEBUG_SPAM:
            try:
                logger.debug(
                    "[SPAM] score=%s confidence=%s categories=%s "
                    "button_only=%s reasons=%s",
                    score, confidence,
                    sorted(independent_categories),
                    is_button_only_case,
                    reasons,
                )
            except Exception:
                pass

        if score >= SPAM_HARD_THRESHOLD:
            try:
                logger.info(
                    "🛡️ SPAM_DETECTED | score=%d conf=%s "
                    "cats=%s buttons=%d reasons=%s",
                    score, confidence,
                    sorted(independent_categories),
                    ctx.button_count,
                    reasons[:5],
                )
            except Exception:
                pass

        result = {
            "score": score,
            "reasons": reasons,
            "confidence": confidence,
            "hard": hard,
            "critical": critical,
            "postbot_confidence": postbot_confidence,
            "signal_categories": sorted(independent_categories),
            "independent_signals": independent_signals,
            "category_scores": {
                "link": link_score, "content": content_score,
                "cta": cta_score, "evasion": evasion_score,
                "structure": structure_score, "context": context_score,
            },
            "random_domains": list(ctx.random_domains),
            "has_random_domain": ctx.has_random_domain,
            "is_button_only_case": is_button_only_case,
            "ai_generated_score": ctx.ai_generated_score,
            "financial_words": financial,
        }

        return result if return_diagnostics else (score, reasons)

    except Exception as exc:
        if DEBUG_DIAG:
            try:
                logger.debug("[DETECTOR] scoring error: %r", exc)
            except Exception:
                pass
        if return_diagnostics:
            return {
                "score": 0, "reasons": ["detector_error"],
                "confidence": "none", "hard": False, "critical": False,
                "postbot_confidence": 0, "signal_categories": [],
                "independent_signals": 0,
                "random_domains": [], "has_random_domain": False,
                "is_button_only_case": False,
            }
        return 0, []


# =============================================================================
# LAYER 1: OCR
# =============================================================================

def _preprocess_image(image: Any) -> Any:
    try:
        if (image.width > OCR_MAX_IMAGE_SIZE[0]
                or image.height > OCR_MAX_IMAGE_SIZE[1]):
            image.thumbnail(OCR_MAX_IMAGE_SIZE, Image.LANCZOS)
        if image.width < 400:
            scale = 400 / image.width
            image = image.resize(
                (int(image.width * scale), int(image.height * scale)),
                Image.LANCZOS,
            )
        if image.mode != "L":
            image = image.convert("L")
        image = ImageEnhance.Contrast(image).enhance(1.8)
        image = image.point(lambda p: 255 if p > 140 else 0)
        return image
    except Exception as exc:
        logger.debug("preprocess error: %r", exc)
        return image


def extract_text_from_image(
    image_bytes: bytes,
    *,
    languages: str = OCR_LANGUAGES,
) -> str:
    if not _OCR_AVAILABLE or not image_bytes:
        return ""
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image = _preprocess_image(image)
        text = pytesseract.image_to_string(
            image, lang=languages, config="--psm 6"
        )
        if len(text.strip()) < 5:
            text2 = pytesseract.image_to_string(
                image, lang=languages, config="--psm 11"
            )
            if len(text2.strip()) > len(text.strip()):
                text = text2
        return text.strip()
    except Exception as exc:
        logger.debug("OCR error: %r", exc)
        return ""


def extract_qr_codes(image_bytes: bytes) -> List[str]:
    if not _QR_AVAILABLE or not _PIL_AVAILABLE or not image_bytes:
        return []
    results: List[str] = []
    try:
        image = Image.open(io.BytesIO(image_bytes))
        for obj in _qr_decode(image):
            try:
                data = obj.data.decode("utf-8", errors="ignore")
                if data:
                    results.append(data)
            except Exception:
                continue
    except Exception as exc:
        logger.debug("QR decode error: %r", exc)
    return results


async def _do_download_telegram_file(
    file_id: str, bot: Any
) -> Optional[bytes]:
    """التنفيذ الفعلي للتنزيل — يُستدعى من sync و async."""
    try:
        file_obj = await asyncio.wait_for(
            bot.get_file(file_id), timeout=30.0
        )
        if file_obj is None:
            return None
        data = await asyncio.wait_for(
            file_obj.download_as_bytearray(), timeout=60.0
        )
        if data is None:
            return None
        return bytes(data)
    except asyncio.TimeoutError:
        logger.debug("download timeout: %s", file_id)
        return None
    except Exception as _e:
        logger.debug("download inner error: %r", _e)
        return None


async def _download_telegram_file_async(
    file_id: str, bot: Any = None
) -> Optional[bytes]:
    if not file_id:
        return None
    if bot is None:
        try:
            from telegram_bot_singleton import get_bot  # type: ignore
            bot = get_bot()
        except Exception:
            return None
    if bot is None:
        return None
    return await _do_download_telegram_file(file_id, bot)


def _download_telegram_file(file_id: str, bot: Any = None) -> Optional[bytes]:
    if not file_id:
        return None
    if bot is None:
        try:
            from telegram_bot_singleton import get_bot  # type: ignore
            bot = get_bot()
        except Exception:
            return None
    if bot is None:
        return None

    try:
        asyncio.get_running_loop()
        logger.warning(
            "_download_telegram_file: running loop detected — "
            "استخدم النسخة async"
        )
        return None
    except RuntimeError:
        pass

    try:
        return asyncio.run(_do_download_telegram_file(file_id, bot))
    except Exception as exc:
        logger.debug("download error: %r", exc)
        return None


async def extract_image_content_async(
    message: Any,
    bot: Any = None,
) -> Tuple[str, List[str]]:
    if not OCR_LAYER_ENABLED or not _OCR_AVAILABLE:
        return "", []
    text_parts: List[str] = []
    qr_parts: List[str] = []
    try:
        photo = getattr(message, "photo", None)
        if photo:
            try:
                largest = max(
                    photo, key=lambda p: getattr(p, "file_size", 0)
                )
                file_id = getattr(largest, "file_id", None)
                if file_id:
                    image_bytes = await _download_telegram_file_async(
                        file_id, bot
                    )
                    if image_bytes:
                        text = await _run_in_pool(
                            extract_text_from_image, image_bytes
                        )
                        if text:
                            text_parts.append(text)
                        qr = await _run_in_pool(
                            extract_qr_codes, image_bytes
                        )
                        if qr:
                            qr_parts.extend(qr)
            except Exception as exc:
                logger.debug("photo extract error: %r", exc)

        document = getattr(message, "document", None)
        if document:
            mime = getattr(document, "mime_type", "") or ""
            if mime.startswith("image/"):
                file_id = getattr(document, "file_id", None)
                if file_id:
                    image_bytes = await _download_telegram_file_async(
                        file_id, bot
                    )
                    if image_bytes:
                        text = await _run_in_pool(
                            extract_text_from_image, image_bytes
                        )
                        if text:
                            text_parts.append(text)
                        qr = await _run_in_pool(
                            extract_qr_codes, image_bytes
                        )
                        if qr:
                            qr_parts.extend(qr)
    except Exception as exc:
        logger.debug("extract_image_content_async error: %r", exc)
    return "\n".join(text_parts), qr_parts


def extract_image_content(
    message: Any,
    bot: Any = None,
) -> Tuple[str, List[str]]:
    if not OCR_LAYER_ENABLED or not _OCR_AVAILABLE:
        return "", []
    text_parts: List[str] = []
    qr_parts: List[str] = []
    try:
        photo = getattr(message, "photo", None)
        if photo:
            try:
                largest = max(
                    photo, key=lambda p: getattr(p, "file_size", 0)
                )
                file_id = getattr(largest, "file_id", None)
                if file_id:
                    image_bytes = _download_telegram_file(file_id, bot)
                    if image_bytes:
                        text = extract_text_from_image(image_bytes)
                        if text:
                            text_parts.append(text)
                        qr = extract_qr_codes(image_bytes)
                        if qr:
                            qr_parts.extend(qr)
            except Exception as exc:
                logger.debug("photo extract error: %r", exc)

        document = getattr(message, "document", None)
        if document:
            mime = getattr(document, "mime_type", "") or ""
            if mime.startswith("image/"):
                file_id = getattr(document, "file_id", None)
                if file_id:
                    image_bytes = _download_telegram_file(file_id, bot)
                    if image_bytes:
                        text = extract_text_from_image(image_bytes)
                        if text:
                            text_parts.append(text)
                        qr = extract_qr_codes(image_bytes)
                        if qr:
                            qr_parts.extend(qr)
    except Exception as exc:
        logger.debug("extract_image_content error: %r", exc)
    return "\n".join(text_parts), qr_parts


# =============================================================================
# LAYER 2: AUDIO STT
# =============================================================================

_whisper_model = None
_whisper_model_lock = threading.Lock()


def _get_whisper_model() -> Any:
    global _whisper_model
    if _whisper_model is None and _WHISPER_AVAILABLE:
        with _whisper_model_lock:
            if _whisper_model is None:
                try:
                    _whisper_model = _whisper.load_model("base")
                except Exception as exc:
                    logger.warning("whisper load error: %r", exc)
    return _whisper_model


def _ogg_to_wav_bytes(ogg_bytes: bytes) -> Optional[bytes]:
    if not _AUDIO_AVAILABLE:
        return None
    try:
        audio = _AudioSegment.from_ogg(io.BytesIO(ogg_bytes))
        if AUDIO_NOISE_REDUCE:
            try:
                audio = _pydub_normalize(audio)
                audio = audio.high_pass_filter(200)
                audio = audio.low_pass_filter(4000)
            except Exception:
                pass
        wav_buf = io.BytesIO()
        audio.export(wav_buf, format="wav")
        return wav_buf.getvalue()
    except Exception as exc:
        logger.debug("ogg→wav error: %r", exc)
        return None


def _transcribe_with_whisper(wav_bytes: bytes) -> str:
    model = _get_whisper_model()
    if model is None:
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name
        try:
            result = model.transcribe(tmp_path, language=None)
            return result.get("text", "").strip()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception as exc:
        logger.debug("whisper transcribe error: %r", exc)
        return ""


def _transcribe_with_google(wav_bytes: bytes) -> str:
    if not _AUDIO_AVAILABLE:
        return ""
    try:
        recognizer = _sr.Recognizer()
        with _sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio = recognizer.record(source)
        for lang in ("ar-SA", "en-US", "fa-IR", "ru-RU"):
            try:
                return recognizer.recognize_google(audio, language=lang)
            except Exception:
                continue
    except Exception as exc:
        logger.debug("google stt error: %r", exc)
    return ""


def transcribe_audio(audio_bytes: bytes, *, use_whisper: bool = False) -> str:
    if not audio_bytes:
        return ""
    wav_bytes = _ogg_to_wav_bytes(audio_bytes)
    if not wav_bytes:
        return ""
    if use_whisper:
        text = _transcribe_with_whisper(wav_bytes)
        if text:
            return text
    return _transcribe_with_google(wav_bytes)


async def extract_audio_content_async(
    message: Any, bot: Any = None
) -> str:
    if not AUDIO_LAYER_ENABLED or not _AUDIO_AVAILABLE:
        return ""
    text_parts: List[str] = []
    try:
        for attr in ("voice", "audio", "video_note"):
            obj = getattr(message, attr, None)
            if not obj:
                continue
            file_id = getattr(obj, "file_id", None)
            if not file_id:
                continue
            audio_bytes = await _download_telegram_file_async(
                file_id, bot
            )
            if not audio_bytes:
                continue
            text = await _run_in_pool(
                transcribe_audio,
                audio_bytes,
                use_whisper=AUDIO_USE_WHISPER,
            )
            if text:
                text_parts.append(text)
    except Exception as exc:
        logger.debug("extract_audio_content_async error: %r", exc)
    return "\n".join(text_parts)


def extract_audio_content(message: Any, bot: Any = None) -> str:
    if not AUDIO_LAYER_ENABLED or not _AUDIO_AVAILABLE:
        return ""
    text_parts: List[str] = []
    try:
        for attr in ("voice", "audio", "video_note"):
            obj = getattr(message, attr, None)
            if not obj:
                continue
            file_id = getattr(obj, "file_id", None)
            if not file_id:
                continue
            audio_bytes = _download_telegram_file(file_id, bot)
            if not audio_bytes:
                continue
            text = transcribe_audio(
                audio_bytes, use_whisper=AUDIO_USE_WHISPER
            )
            if text:
                text_parts.append(text)
    except Exception as exc:
        logger.debug("extract_audio_content error: %r", exc)
    return "\n".join(text_parts)


# =============================================================================
# LAYER 3: URL ENRICHMENT
# =============================================================================

_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})

_REQ_TIMEOUT_TUPLE = (URL_EXPAND_CONNECT_TIMEOUT, URL_EXPAND_READ_TIMEOUT)


def expand_url(url: str, *, max_hops: int = URL_EXPAND_MAX_HOPS) -> str:
    if not _REQUESTS_AVAILABLE or not url:
        return url
    current = url
    visited = set()
    try:
        for _ in range(max_hops):
            if current in visited:
                break
            visited.add(current)
            parsed = urlparse(current)
            if parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES:
                logger.debug("expand_url: rejected scheme %r", parsed.scheme)
                break
            response = _requests.head(
                current, allow_redirects=False,
                timeout=_REQ_TIMEOUT_TUPLE,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    break
                loc_parsed = urlparse(location)
                if (
                    loc_parsed.scheme
                    and loc_parsed.scheme.lower() not in _ALLOWED_URL_SCHEMES
                ):
                    logger.debug(
                        "expand_url: rejected redirect scheme %r",
                        loc_parsed.scheme,
                    )
                    break
                current = location
            else:
                break
    except Exception as exc:
        logger.debug("expand_url error: %r", exc)
    return current


def is_shortener(url: str) -> bool:
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        domain = re.sub(r"^www\.", "", domain).split(":")[0]
        if domain in _SHORTENER_DOMAINS:
            return True
        for shortener in _SHORTENER_DOMAINS:
            if domain.endswith("." + shortener):
                return True
        return False
    except Exception:
        return False


def check_safe_browsing(url: str) -> Dict[str, Any]:
    if not SAFE_BROWSING_API_KEY or not _REQUESTS_AVAILABLE:
        return {"safe": True, "checked": False, "reason": "no_api_key"}
    try:
        payload = {
            "client": {
                "clientId": "relax-manager",
                "clientVersion": _DETECTORS_VERSION_CLEAN,
            },
            "threatInfo": {
                "threatTypes": [
                    "MALWARE", "SOCIAL_ENGINEERING",
                    "UNWANTED_SOFTWARE",
                    "POTENTIALLY_HARMFUL_APPLICATION",
                ],
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": url}],
            },
        }
        response = _requests.post(
            f"https://safebrowsing.googleapis.com/v4/threatMatches:find"
            f"?key={SAFE_BROWSING_API_KEY}",
            json=payload,
            timeout=_REQ_TIMEOUT_TUPLE,
        )
        if response.status_code != 200:
            return {
                "safe": True, "checked": False,
                "reason": f"http_{response.status_code}",
            }
        data = response.json()
        if data.get("matches"):
            return {
                "safe": False, "checked": True,
                "threats": [
                    m.get("threatType") for m in data["matches"]
                ],
            }
        return {"safe": True, "checked": True}
    except Exception as exc:
        logger.debug("safe_browsing error: %r", exc)
        return {"safe": True, "checked": False, "reason": "error"}


def get_domain_age_days(url: str) -> Optional[int]:
    if not _WHOIS_AVAILABLE or not WHOIS_ENABLED:
        return None
    try:
        domain = urlparse(url).netloc
        domain = re.sub(r"^www\.", "", domain).split(":")[0]
        info = _whois.whois(domain)
        creation = info.get("creation_date")
        if isinstance(creation, list):
            creation = creation[0] if creation else None
        if creation is None:
            return None
        if isinstance(creation, str):
            try:
                creation = datetime.datetime.fromisoformat(creation)
            except ValueError:
                return None
        return (datetime.datetime.now() - creation).days
    except Exception as exc:
        logger.debug("whois error: %r", exc)
        return None


def analyze_url(url: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "original": url,
        "is_shortener": is_shortener(url),
        "expanded": url,
        "safe_browsing": {"safe": True, "checked": False},
        "domain_age_days": None,
        "suspicious": False,
        "reasons": [],
    }
    if not URL_ENRICH_ENABLED:
        return result
    try:
        if result["is_shortener"]:
            expanded = expand_url(url)
            result["expanded"] = expanded
            if expanded != url:
                result["reasons"].append("shortener_expanded")
        sb = check_safe_browsing(result["expanded"])
        result["safe_browsing"] = sb
        if not sb.get("safe", True):
            result["suspicious"] = True
            result["reasons"].append(
                f"safe_browsing:{sb.get('threats')}"
            )
        age = get_domain_age_days(result["expanded"])
        result["domain_age_days"] = age
        if age is not None and age < WHOIS_NEW_DOMAIN_DAYS:
            result["suspicious"] = True
            result["reasons"].append(f"new_domain:{age}d")
    except Exception as exc:
        logger.debug("analyze_url error: %r", exc)
    return result


def analyze_urls(urls: List[str]) -> List[Dict[str, Any]]:
    return [analyze_url(u) for u in urls[:URL_ENRICH_MAX_URLS]]


async def analyze_urls_async(
    urls: List[str],
) -> List[Dict[str, Any]]:
    if not urls or not ASYNC_NETWORK_ENABLED:
        return []
    selected = urls[:URL_ENRICH_MAX_URLS]
    try:
        tasks = [
            asyncio.wait_for(
                _run_in_pool(analyze_url, u),
                timeout=ASYNC_NETWORK_TIMEOUT * 3,
            )
            for u in selected
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: List[Dict[str, Any]] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.debug("analyze_urls_async[%d] error: %r", i, r)
                out.append({
                    "original": selected[i],
                    "is_shortener": False, "expanded": selected[i],
                    "safe_browsing": {"safe": True, "checked": False},
                    "domain_age_days": None,
                    "suspicious": False, "reasons": ["async_error"],
                })
            else:
                out.append(r)
        return out
    except Exception as exc:
        logger.debug("analyze_urls_async error: %r", exc)
        return []


# =============================================================================
# LAYER 4: METADATA
# =============================================================================

def extract_metadata_text(message: Any) -> str:
    parts: List[str] = []
    try:
        from_user = getattr(message, "from_user", None)
        if from_user is not None:
            for attr in ("first_name", "last_name", "username", "bio"):
                val = getattr(from_user, attr, None)
                if val:
                    parts.append(str(val))
        sender_chat = getattr(message, "sender_chat", None)
        if sender_chat is not None:
            for attr in ("title", "username", "description"):
                val = getattr(sender_chat, attr, None)
                if val:
                    parts.append(str(val))
        fwd_chat = getattr(message, "forward_from_chat", None)
        if fwd_chat is not None:
            for attr in ("title", "username", "description"):
                val = getattr(fwd_chat, attr, None)
                if val:
                    parts.append(str(val))
        reply = getattr(message, "reply_to_message", None)
        if reply is not None and reply is not message:
            parts.append(extract_metadata_text(reply))
    except Exception as exc:
        logger.debug("metadata extract error: %r", exc)
    return "\n".join(p for p in parts if p)


def metadata_has_suspicious_content(message: Any) -> bool:
    text = extract_metadata_text(message)
    if not text:
        return False
    for pattern in _SUSPICIOUS_NAME_PATTERNS:
        if pattern.search(text):
            return True
    return False


def extract_metadata_urls(message: Any) -> List[str]:
    text = extract_metadata_text(message)
    if not text:
        return []
    return _URL_IN_TEXT_RE.findall(text)


# =============================================================================
# LAYER 5: OBFUSCATION
# =============================================================================

def _looks_like_text(text: str) -> bool:
    if not text or len(text) < 4:
        return False
    printable = sum(1 for c in text if c.isprintable() or c.isspace())
    return (printable / len(text)) >= 0.85


def _has_url_signature(text: str) -> bool:
    if not text:
        return False
    return bool(_URL_SIGNATURE_RE.search(text))


def _b64_pad(text: str) -> str:
    if not text:
        return text
    pad = (-len(text)) % 4
    return text + ("=" * pad)


def try_decode_base64(text: str) -> str:
    if not text:
        return ""
    for pattern in (_BASE64_RE, _BASE64_URLSAFE_RE):
        if not pattern.match(text):
            continue
        try:
            padded = _b64_pad(text)
            if "-" in text or "_" in text:
                decoded = base64.urlsafe_b64decode(padded)
            else:
                decoded = base64.b64decode(padded)
            result = decoded.decode("utf-8", errors="strict")
            if _looks_like_text(result):
                return result
        except Exception:
            continue
    return ""


def try_decode_rot13(text: str) -> str:
    try:
        decoded = codecs.decode(text, "rot_13")
        if _looks_like_text(decoded) and _has_url_signature(decoded):
            return decoded
    except Exception:
        pass
    return ""


def try_decode_hex(text: str) -> str:
    cleaned = re.sub(r"[\s:,-]", "", text)
    if len(cleaned) < 16 or len(cleaned) % 2 != 0:
        return ""
    if not re.match(r"^[0-9a-fA-F]+$", cleaned):
        return ""
    try:
        decoded = bytes.fromhex(cleaned).decode("utf-8", errors="strict")
        if _looks_like_text(decoded):
            return decoded
    except Exception:
        pass
    return ""


def try_decode_url(text: str) -> str:
    if "%" not in text:
        return ""
    try:
        decoded = urllib.parse.unquote(text)
        if decoded != text and _looks_like_text(decoded):
            return decoded
    except Exception:
        pass
    return ""


def try_decode_reverse(text: str) -> str:
    if len(text) < 10:
        return ""
    reversed_text = text[::-1]
    if _has_url_signature(reversed_text):
        return reversed_text
    return ""


def find_obfuscated_payloads(text: str) -> List[Tuple[str, str]]:
    results: List[Tuple[str, str]] = []
    if not text:
        return results
    tokens = re.findall(r"\S{16,}", text)
    for token in tokens:
        decoded = try_decode_base64(token)
        if decoded:
            results.append(("base64", decoded))
            continue
        decoded = try_decode_hex(token)
        if decoded:
            results.append(("hex", decoded))
            continue
    decoded = try_decode_rot13(text)
    if decoded:
        results.append(("rot13", decoded))
    decoded = try_decode_url(text)
    if decoded:
        results.append(("url_encode", decoded))
    decoded = try_decode_reverse(text)
    if decoded:
        results.append(("reverse", decoded))
    return results


def has_any_obfuscation(text: str) -> bool:
    return bool(find_obfuscated_payloads(text))


# =============================================================================
# LAYER 6: BEHAVIORAL
# =============================================================================

_BEHAVIOR_LOCK = threading.Lock()

_user_message_times: Dict[int, deque] = defaultdict(lambda: deque(maxlen=20))
_user_short_messages: Dict[int, deque] = defaultdict(lambda: deque(maxlen=20))
_user_url_count: Dict[int, deque] = defaultdict(lambda: deque(maxlen=10))
_user_edit_times: Dict[int, deque] = defaultdict(lambda: deque(maxlen=20))

_edited_messages: Dict[Tuple[int, int], Dict[str, Any]] = {}

_context_buffers: Dict[int, deque] = defaultdict(lambda: deque(maxlen=10))

_last_cleanup = 0.0
_last_cleanup_lock = threading.Lock()
CLEANUP_INTERVAL = 300


def record_message(user_id: int, text: str, has_url: bool = False) -> None:
    now = time.time()
    with _BEHAVIOR_LOCK:
        _user_message_times[user_id].append(now)
        if len(text) < 20:
            _user_short_messages[user_id].append((now, text))
        if has_url:
            _user_url_count[user_id].append(now)


def check_rate_limit(user_id: int) -> Tuple[bool, Optional[str]]:
    now = time.time()
    cutoff = now - RATE_WINDOW_SECONDS
    with _BEHAVIOR_LOCK:
        times = list(_user_message_times[user_id])
        url_times = list(_user_url_count[user_id])
    recent = [t for t in times if t > cutoff]
    if len(recent) > RATE_MAX_MESSAGES:
        return True, f"rate_limit:{len(recent)}/min"
    recent_urls = [t for t in url_times if t > cutoff]
    if len(recent_urls) > RATE_MAX_URLS:
        return True, f"url_flood:{len(recent_urls)}/min"
    return False, None


def check_split_url_pattern(
    user_id: int, current_text: str
) -> Tuple[bool, Optional[str]]:
    now = time.time()
    cutoff = now - CROSS_MSG_WINDOW
    with _BEHAVIOR_LOCK:
        recent = list(_user_short_messages[user_id])
    recent_texts = [t for (ts, t) in recent if ts > cutoff]
    if len(recent_texts) < 2:
        return False, None
    combined = " ".join(recent_texts[-3:] + [current_text])
    domain_parts = re.findall(
        r"\b[a-z0-9-]{3,}\s*\.\s*"
        r"(?:com|net|org|digital|xyz|io|me|t\.me)",
        combined.lower(),
    )
    if domain_parts:
        return True, "split_url_detected"
    return False, None


def track_edit(
    user_id: int,
    chat_id: int,
    message_id: int,
    original_text: str,
    new_text: str,
) -> Tuple[bool, Optional[str]]:
    if original_text == new_text:
        return False, None
    key = (chat_id, message_id)
    now = time.time()
    with _BEHAVIOR_LOCK:
        _user_edit_times[user_id].append(now)

        cutoff = now - 60
        recent_edits = [t for t in _user_edit_times[user_id] if t > cutoff]
        if len(recent_edits) > 5:
            return True, f"edit_flood:{len(recent_edits)}/min"

        if key in _edited_messages:
            prev = _edited_messages[key]
            prev_text = prev.get("text", "")
            if len(prev_text) < 30 and len(new_text) > len(prev_text) * 3:
                return True, "suspicious_edit"
        _edited_messages[key] = {
            "user_id": user_id, "text": new_text, "time": now,
        }
    return False, None


def cleanup_old_data(force: bool = False) -> None:
    global _last_cleanup
    now = time.time()
    with _last_cleanup_lock:
        if not force and now - _last_cleanup < CLEANUP_INTERVAL:
            return
        _last_cleanup = now

    cutoff = now - 600
    context_cutoff = now - (_CONTEXT_WINDOW_SEC * 2)

    with _BEHAVIOR_LOCK:
        for uid in list(_user_message_times.keys()):
            dq = _user_message_times[uid]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if not dq:
                _user_message_times.pop(uid, None)

        for uid in list(_user_short_messages.keys()):
            dq = _user_short_messages[uid]
            while dq and dq[0][0] < cutoff:
                dq.popleft()
            if not dq:
                _user_short_messages.pop(uid, None)

        for uid in list(_user_url_count.keys()):
            dq = _user_url_count[uid]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if not dq:
                _user_url_count.pop(uid, None)

        for uid in list(_user_edit_times.keys()):
            dq = _user_edit_times[uid]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if not dq:
                _user_edit_times.pop(uid, None)

        for key in list(_edited_messages.keys()):
            entry = _edited_messages.get(key)
            if entry is None:
                continue
            if entry.get("time", 0) < cutoff:
                _edited_messages.pop(key, None)

        for uid in list(_context_buffers.keys()):
            dq = _context_buffers[uid]
            while dq and dq[0].get("ts", 0) < context_cutoff:
                dq.popleft()
            if not dq:
                _context_buffers.pop(uid, None)


# =============================================================================
# LAYER 7: VIDEO (frames → OCR)
# =============================================================================

def _extract_video_frames(
    video_bytes: bytes,
    max_frames: int = VIDEO_MAX_FRAMES,
    interval_sec: float = VIDEO_FRAME_INTERVAL_SEC,
) -> List[bytes]:
    frames: List[bytes] = []

    if _CV2_AVAILABLE and _NUMPY_AVAILABLE:
        tmp_path: Optional[str] = None
        cap = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
                f.write(video_bytes)
                tmp_path = f.name
            cap = cv2.VideoCapture(tmp_path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frame_interval = int(fps * interval_sec) or 1
            count = 0
            idx = 0
            max_iterations = 100_000
            iterations = 0
            while count < max_frames and iterations < max_iterations:
                iterations += 1
                ret, frame = cap.read()
                if not ret:
                    break
                if idx % frame_interval == 0:
                    ok, buf = cv2.imencode(".jpg", frame)
                    if ok:
                        frames.append(buf.tobytes())
                        count += 1
                idx += 1
            if frames:
                return frames
        except Exception as exc:
            logger.debug("cv2 frame extract error: %r", exc)
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    if _FFMPEG_AVAILABLE:
        try:
            import subprocess
            with tempfile.TemporaryDirectory() as tmpdir:
                inp = os.path.join(tmpdir, "in.mp4")
                with open(inp, "wb") as f:
                    f.write(video_bytes)
                out_pattern = os.path.join(tmpdir, "frame_%03d.jpg")
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-i", inp,
                        "-vf", f"fps=1/{interval_sec}",
                        "-frames:v", str(max_frames),
                        out_pattern,
                    ],
                    capture_output=True,
                    timeout=30,
                )
                for name in sorted(os.listdir(tmpdir)):
                    if name.startswith("frame_") and name.endswith(".jpg"):
                        path = os.path.join(tmpdir, name)
                        with open(path, "rb") as f:
                            frames.append(f.read())
            return frames
        except Exception as exc:
            logger.debug("ffmpeg frame extract error: %r", exc)

    return frames


async def extract_video_content_async(
    message: Any,
    bot: Any = None,
) -> Tuple[str, List[str]]:
    if not VIDEO_LAYER_ENABLED or not _OCR_AVAILABLE:
        return "", []

    video = getattr(message, "video", None)
    if not video:
        return "", []

    file_id = getattr(video, "file_id", None)
    if not file_id:
        return "", []

    video_bytes = await _download_telegram_file_async(file_id, bot)
    if not video_bytes:
        return "", []

    frames = await _run_in_pool(_extract_video_frames, video_bytes)
    if not frames:
        return "", []

    text_parts: List[str] = []
    qr_parts: List[str] = []

    for frame_bytes in frames:
        try:
            text = await _run_in_pool(
                extract_text_from_image, frame_bytes
            )
            if text:
                text_parts.append(text)
            qr = await _run_in_pool(extract_qr_codes, frame_bytes)
            if qr:
                qr_parts.extend(qr)
        except Exception:
            continue

    return "\n".join(text_parts), _unique_strings(qr_parts)


def extract_video_content(
    message: Any,
    bot: Any = None,
) -> Tuple[str, List[str]]:
    if not VIDEO_LAYER_ENABLED or not _OCR_AVAILABLE:
        return "", []

    video = getattr(message, "video", None)
    if not video:
        return "", []

    file_id = getattr(video, "file_id", None)
    if not file_id:
        return "", []

    video_bytes = _download_telegram_file(file_id, bot)
    if not video_bytes:
        return "", []

    frames = _extract_video_frames(video_bytes)
    if not frames:
        return "", []

    text_parts: List[str] = []
    qr_parts: List[str] = []

    for frame_bytes in frames:
        try:
            text = extract_text_from_image(frame_bytes)
            if text:
                text_parts.append(text)
            qr = extract_qr_codes(frame_bytes)
            if qr:
                qr_parts.extend(qr)
        except Exception:
            continue

    return "\n".join(text_parts), _unique_strings(qr_parts)


# =============================================================================
# NSFW Detection — 3 Providers + Circuit Breaker
# =============================================================================

def _detect_image_mime(image_bytes: bytes) -> str:
    if not image_bytes or len(image_bytes) < 12:
        return "image/jpeg"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes[:2] == b"BM":
        return "image/bmp"
    return "image/jpeg"


_se_failure_count: int = 0
_se_last_failure_ts: float = 0.0
_se_circuit_lock = threading.Lock()


def _se_circuit_is_open() -> bool:
    global _se_failure_count
    with _se_circuit_lock:
        if _se_failure_count < SE_CIRCUIT_FAILURE_THRESHOLD:
            return False
        if time.time() - _se_last_failure_ts < SE_CIRCUIT_OPEN_SEC:
            return True
        _se_failure_count = 0
        return False


def _se_record_failure() -> None:
    global _se_failure_count, _se_last_failure_ts
    with _se_circuit_lock:
        _se_failure_count += 1
        _se_last_failure_ts = time.time()
        if _se_failure_count == SE_CIRCUIT_FAILURE_THRESHOLD:
            logger.warning(
                "🟡 Sightengine circuit breaker OPEN "
                "(failures=%d, cooldown=%ds)",
                _se_failure_count, int(SE_CIRCUIT_OPEN_SEC),
            )


def _se_reset_circuit() -> None:
    global _se_failure_count
    with _se_circuit_lock:
        if _se_failure_count > 0:
            logger.info("🟢 Sightengine circuit breaker CLOSED (recovered)")
        _se_failure_count = 0


def _check_nsfw_via_sightengine(
    image_bytes: bytes,
) -> Tuple[bool, float, List[str]]:
    if not _REQUESTS_AVAILABLE or not image_bytes:
        return False, 0.0, []

    se_user = os.getenv("SIGHTENGINE_API_USER", "").strip()
    se_secret = os.getenv("SIGHTENGINE_API_SECRET", "").strip()
    if not se_user or not se_secret:
        return False, 0.0, []

    if _se_circuit_is_open():
        logger.debug("sightengine: circuit open, skipping call")
        return False, 0.0, []

    if len(image_bytes) > NSFW_SIGHTENGINE_MAX_BYTES:
        logger.debug(
            "sightengine: image too large (%d > %d)",
            len(image_bytes), NSFW_SIGHTENGINE_MAX_BYTES,
        )
        return False, 0.0, []

    threshold = NSFW_THRESHOLD

    try:
        url = "https://api.sightengine.com/1.0/check.json"
        mime = _detect_image_mime(image_bytes)
        ext = mime.split("/")[-1]
        files = {"media": (f"image.{ext}", image_bytes, mime)}
        data = {
            "models": "nudity-2.0,gore-2.0,offensive-2.0",
            "api_user": se_user,
            "api_secret": se_secret,
        }

        resp = _requests.post(
            url, data=data, files=files,
            timeout=(5.0, 15.0),
        )
        if resp.status_code != 200:
            logger.debug("sightengine HTTP %d", resp.status_code)
            if resp.status_code >= 500 or resp.status_code == 429:
                _se_record_failure()
            return False, 0.0, []

        result = resp.json()
        if result.get("status") != "success":
            logger.debug("sightengine: %s", result.get("error"))
            _se_record_failure()
            return False, 0.0, []

        _se_reset_circuit()

        nudity = result.get("nudity", {}) or {}
        scores = {
            "sexual_activity": float(nudity.get("sexual_activity", 0) or 0),
            "sexual_display": float(nudity.get("sexual_display", 0) or 0),
            "erotica": float(nudity.get("erotica", 0) or 0),
            "very_suggestive": float(nudity.get("very_suggestive", 0) or 0),
        }

        max_bad = max(scores.values()) if scores else 0.0

        if max_bad >= threshold:
            reasons = [
                f"sightengine:{k}={v:.2f}"
                for k, v in scores.items()
                if v >= threshold
            ]
            return True, max_bad, reasons

        return False, max_bad, []
    except Exception as exc:
        logger.debug("sightengine error: %r", exc)
        _se_record_failure()
        return False, 0.0, []


def _analyze_nsfw_image(image_bytes: bytes) -> Tuple[bool, float, List[str]]:
    if not image_bytes:
        return False, 0.0, []

    if NSFW_MODEL_ENABLED and _PIL_AVAILABLE:
        classifier = _load_nsfw_classifier()
        if classifier is not None:
            try:
                image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                results = classifier(image)
                for r in results:
                    label = str(r.get("label", "")).lower()
                    score = float(r.get("score", 0.0))
                    if "nsfw" in label and score >= NSFW_THRESHOLD:
                        return True, score, [f"local:nsfw={score:.2f}"]
                    if "porn" in label and score >= NSFW_THRESHOLD:
                        return True, score, [f"local:porn={score:.2f}"]
            except Exception as exc:
                logger.debug("local nsfw model error: %r", exc)

    return _check_nsfw_via_sightengine(image_bytes)


def _has_any_nsfw_provider() -> bool:
    if NSFW_MODEL_ENABLED and _PIL_AVAILABLE:
        return True
    se_user = os.getenv("SIGHTENGINE_API_USER", "").strip()
    se_secret = os.getenv("SIGHTENGINE_API_SECRET", "").strip()
    return bool(se_user and se_secret)


async def extract_nsfw_from_message_async(
    message: Any, bot: Any = None
) -> Tuple[bool, List[str]]:
    if not NSFW_LAYER_ENABLED or not _has_any_nsfw_provider():
        return False, []

    reasons: List[str] = []
    try:
        photo = getattr(message, "photo", None)
        if photo:
            try:
                largest = max(photo, key=lambda p: getattr(p, "file_size", 0))
                file_id = getattr(largest, "file_id", None)
                if file_id:
                    img_bytes = await _download_telegram_file_async(
                        file_id, bot
                    )
                    if img_bytes:
                        is_nsfw, _, rs = await _run_in_pool(
                            _analyze_nsfw_image, img_bytes
                        )
                        if is_nsfw:
                            reasons.extend(rs)
            except Exception:
                pass

        document = getattr(message, "document", None)
        if document:
            mime = getattr(document, "mime_type", "") or ""
            if mime.startswith("image/"):
                file_id = getattr(document, "file_id", None)
                if file_id:
                    img_bytes = await _download_telegram_file_async(
                        file_id, bot
                    )
                    if img_bytes:
                        is_nsfw, _, rs = await _run_in_pool(
                            _analyze_nsfw_image, img_bytes
                        )
                        if is_nsfw:
                            reasons.extend(rs)
    except Exception as exc:
        logger.debug("nsfw extract error: %r", exc)

    return bool(reasons), _unique_strings(reasons)


def extract_nsfw_from_message(
    message: Any, bot: Any = None
) -> Tuple[bool, List[str]]:
    if not NSFW_LAYER_ENABLED or not _has_any_nsfw_provider():
        return False, []

    reasons: List[str] = []
    try:
        photo = getattr(message, "photo", None)
        if photo:
            try:
                largest = max(photo, key=lambda p: getattr(p, "file_size", 0))
                file_id = getattr(largest, "file_id", None)
                if file_id:
                    img_bytes = _download_telegram_file(file_id, bot)
                    if img_bytes:
                        is_nsfw, _, rs = _analyze_nsfw_image(img_bytes)
                        if is_nsfw:
                            reasons.extend(rs)
            except Exception:
                pass

        document = getattr(message, "document", None)
        if document:
            mime = getattr(document, "mime_type", "") or ""
            if mime.startswith("image/"):
                file_id = getattr(document, "file_id", None)
                if file_id:
                    img_bytes = _download_telegram_file(file_id, bot)
                    if img_bytes:
                        is_nsfw, _, rs = _analyze_nsfw_image(img_bytes)
                        if is_nsfw:
                            reasons.extend(rs)
    except Exception as exc:
        logger.debug("nsfw extract error: %r", exc)

    return bool(reasons), _unique_strings(reasons)


# =============================================================================
# LAYER 9: STICKER-OCR
# =============================================================================

def _extract_sticker_text_sync(
    message: Any, bot: Any = None
) -> Tuple[str, int]:
    if not STICKER_LAYER_ENABLED:
        return "", 0
    try:
        sticker = getattr(message, "sticker", None)
        if sticker is None:
            return "", 0
        emoji = getattr(sticker, "emoji", "") or ""
        spam_count = _count_spam_emojis(emoji) if emoji else 0
        text_parts: List[str] = []
        if emoji:
            text_parts.append(emoji)
        thumb = getattr(sticker, "thumbnail", None)
        if thumb and _OCR_AVAILABLE:
            file_id = getattr(thumb, "file_id", None)
            if file_id:
                img_bytes = _download_telegram_file(file_id, bot)
                if img_bytes:
                    t = extract_text_from_image(img_bytes)
                    if t:
                        text_parts.append(t)
        return "\n".join(text_parts), spam_count
    except Exception as exc:
        logger.debug("sticker extract error: %r", exc)
        return "", 0


def _extract_sticker_text(message: Any, bot: Any = None) -> Tuple[str, int]:
    return _extract_sticker_text_sync(message, bot)


async def _extract_sticker_text_async(
    message: Any, bot: Any = None
) -> Tuple[str, int]:
    if not STICKER_LAYER_ENABLED:
        return "", 0
    try:
        sticker = getattr(message, "sticker", None)
        if sticker is None:
            return "", 0
        emoji = getattr(sticker, "emoji", "") or ""
        spam_count = _count_spam_emojis(emoji) if emoji else 0
        text_parts: List[str] = []
        if emoji:
            text_parts.append(emoji)
        thumb = getattr(sticker, "thumbnail", None)
        if thumb and _OCR_AVAILABLE:
            file_id = getattr(thumb, "file_id", None)
            if file_id:
                img_bytes = await _download_telegram_file_async(
                    file_id, bot
                )
                if img_bytes:
                    t = await _run_in_pool(
                        extract_text_from_image, img_bytes
                    )
                    if t:
                        text_parts.append(t)
        return "\n".join(text_parts), spam_count
    except Exception as exc:
        logger.debug("sticker extract error: %r", exc)
        return "", 0


# =============================================================================
# LAYER 10: REACTIONS
# =============================================================================

def analyze_reactions(message: Any) -> Tuple[int, List[str]]:
    if not REACTIONS_LAYER_ENABLED:
        return 0, []

    reasons: List[str] = []
    score = 0

    try:
        reactions = getattr(message, "reactions", None)
        if reactions is None:
            return 0, []

        rlist = getattr(reactions, "reactions", None) or []

        total = 0
        spam_emoji_total = 0

        for r in rlist:
            try:
                count = int(getattr(r, "total_count", 0) or 0)
                total += count
                emoji_obj = getattr(r, "emoji", None)
                emoji = ""
                if emoji_obj is not None:
                    if isinstance(emoji_obj, str):
                        emoji = emoji_obj
                    else:
                        _e = getattr(emoji_obj, "emoji", None)
                        if isinstance(_e, str):
                            emoji = _e
                if emoji and emoji in _SPAM_REACTIONS:
                    spam_emoji_total += count
            except Exception:
                continue

        has_text = bool(
            getattr(message, "text", None)
            or getattr(message, "caption", None)
        )

        if not has_text and total >= 5:
            score += 3
            reasons.append(f"reactions_only:{total}")

        if spam_emoji_total >= 10:
            score += 4
            reasons.append(f"spam_reactions:{spam_emoji_total}")
        elif spam_emoji_total >= 5:
            score += 2
            reasons.append(f"spam_reactions:{spam_emoji_total}")

        if has_text and spam_emoji_total >= 8:
            score += 2
            reasons.append(f"text_with_spam_reactions:{spam_emoji_total}")

    except Exception as exc:
        logger.debug("reactions analyze error: %r", exc)

    return min(score, 8), reasons


# =============================================================================
# LAYER 11: CONTEXT (cross-message)
# =============================================================================

def record_context_message(user_id: int, text: str, has_url: bool) -> None:
    with _BEHAVIOR_LOCK:
        _context_buffers[user_id].append(
            {"text": text, "has_url": has_url, "ts": time.time()}
        )


# =============================================================================
# 🆕 v4.0.9 FIX-AR-3: analyze_context_window — استثناء العربية القصيرة
# =============================================================================

def analyze_context_window(user_id: int) -> Tuple[int, List[str]]:
    if not CONTEXT_LAYER_ENABLED:
        return 0, []

    now = time.time()
    cutoff = now - _CONTEXT_WINDOW_SEC

    with _BEHAVIOR_LOCK:
        recent = [
            m for m in _context_buffers[user_id]
            if m["ts"] > cutoff
        ]

    if len(recent) < 3:
        return 0, []

    score = 0
    reasons: List[str] = []

    # 🆕 v4.0.9 FIX-AR-3: إذا كل الرسائل عربية قصيرة → تجاهل السياق
    all_arabic_short = all(
        _is_arabic_dominant(m.get("text", ""))
        and len(m.get("text", "")) <= ARABIC_SHORT_MAX_CHARS
        and not m.get("has_url", False)
        for m in recent
        if m.get("text")
    )
    if all_arabic_short and len(recent) > 0:
        return 0, []

    if len(recent) >= 10:
        score += 3
        reasons.append(f"context_flood:{len(recent)}")

    short_count = sum(1 for m in recent if len(m["text"]) < 20)
    if short_count >= 5:
        # 🆕 v4.0.9: تخفيف إذا كل قصيرة عربية
        arabic_short_count = sum(
            1 for m in recent
            if _is_arabic_dominant(m.get("text", ""))
            and len(m.get("text", "")) < 20
        )
        if arabic_short_count >= short_count * 0.8:
            # معظمها عربية قصيرة → تجاهل
            pass
        else:
            score += 2
            reasons.append(f"context_short:{short_count}")

    url_count = sum(1 for m in recent if m["has_url"])
    if url_count >= 5:
        score += 3
        reasons.append(f"context_urls:{url_count}")

    texts = [m["text"].lower() for m in recent if m["text"]]
    if len(texts) >= 3:
        unique_ratio = len(set(texts)) / len(texts)
        if unique_ratio < 0.4:
            # 🆕 v4.0.9: تجاهل التكرار إذا كل الرسائل عربية قصيرة (وهذا طبيعي في المحادثات)
            arabic_short_repeats = sum(
                1 for t in texts
                if _is_arabic_dominant(t) and len(t) < 30
            )
            if arabic_short_repeats < len(texts) * 0.7:
                score += 3
                reasons.append("context_repetition")

    return min(score, 10), reasons


# =============================================================================
# LAYER 12: CIPHER
# =============================================================================

def try_decode_multi_base64(text: str, max_depth: int = 3) -> str:
    current = text.strip()
    for _ in range(max_depth):
        decoded = try_decode_base64(current)
        if not decoded or decoded == current:
            break
        current = decoded
    return current if current != text else ""


def try_decode_caesar(text: str) -> List[Tuple[int, str]]:
    results: List[Tuple[int, str]] = []
    alpha = "abcdefghijklmnopqrstuvwxyz"
    lower = text.lower()

    if len(text) < 8:
        return results

    for shift in range(1, 26):
        translated = str.maketrans(
            alpha, alpha[shift:] + alpha[:shift],
        )
        candidate = lower.translate(translated)
        if _has_url_signature(candidate) or _has_url_signature(
            candidate.upper()
        ):
            results.append((shift, candidate))

    return results


def try_decode_xor(text: str) -> List[Tuple[int, str]]:
    results: List[Tuple[int, str]] = []
    if not text or len(text) < 8:
        return results

    try:
        raw = text.encode("utf-8", errors="ignore")
    except Exception:
        return results

    encodings = ("utf-8", "utf-16-le", "utf-16-be", "latin-1")

    for key in range(1, 128):
        decoded_bytes = bytes(b ^ key for b in raw)
        matched = False
        for enc in encodings:
            try:
                s = decoded_bytes.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
            if _has_url_signature(s):
                results.append((key, s))
                matched = True
                break
        if matched and len(results) >= 3:
            break

    return results


def _find_encoded_payloads(text: str) -> List[Tuple[str, str]]:
    if not text or not CIPHER_LAYER_ENABLED:
        return []

    results: List[Tuple[str, str]] = []

    multi = try_decode_multi_base64(text)
    if multi:
        results.append(("multi_base64", multi))

    caesar_results = try_decode_caesar(text)
    for shift, decoded in caesar_results[:2]:
        results.append((f"caesar_{shift}", decoded))

    xor_results = try_decode_xor(text)
    for key, decoded in xor_results[:2]:
        results.append((f"xor_{key}", decoded))

    return results


# =============================================================================
# LAYER 13: STEGANOGRAPHY
# =============================================================================

def _lsb_extract_text(image_bytes: bytes, max_bytes: int = 500) -> str:
    if not _NUMPY_AVAILABLE or not _PIL_AVAILABLE:
        return ""

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        if image.width * image.height < 100:
            return ""

        arr = _np.array(image, dtype=_np.uint8)
        flat = arr.flatten()

        bits = (flat & 1).astype(_np.uint8)

        n_bytes = min(len(bits) // 8, max_bytes)
        if n_bytes < 8:
            return ""

        bits = bits[: n_bytes * 8].reshape(-1, 8)
        weights = _np.array(
            [128, 64, 32, 16, 8, 4, 2, 1], dtype=_np.uint8
        )
        byte_values = bits.dot(weights)
        raw = bytes(byte_values.astype(_np.uint8))

        try:
            text = raw.decode("utf-8", errors="ignore")
            printable = sum(
                1 for c in text if c.isprintable() or c.isspace()
            )
            if printable / max(len(text), 1) >= 0.85:
                if _has_url_signature(text) or _looks_like_text(text):
                    return text.strip()
        except Exception:
            pass
    except Exception as exc:
        logger.debug("lsb error: %r", exc)

    return ""


async def extract_stego_content_async(
    message: Any, bot: Any = None
) -> Tuple[str, List[str]]:
    if not STEGO_LAYER_ENABLED:
        return "", []

    text_parts: List[str] = []

    try:
        photo = getattr(message, "photo", None)
        if photo:
            try:
                largest = max(
                    photo, key=lambda p: getattr(p, "file_size", 0)
                )
                file_id = getattr(largest, "file_id", None)
                if file_id:
                    img_bytes = await _download_telegram_file_async(
                        file_id, bot
                    )
                    if img_bytes:
                        text = await _run_in_pool(
                            _lsb_extract_text, img_bytes
                        )
                        if text:
                            text_parts.append(text)
            except Exception:
                pass
    except Exception:
        pass

    return "\n".join(text_parts), []


def extract_stego_content(
    message: Any, bot: Any = None
) -> Tuple[str, List[str]]:
    if not STEGO_LAYER_ENABLED:
        return "", []

    text_parts: List[str] = []

    try:
        photo = getattr(message, "photo", None)
        if photo:
            try:
                largest = max(
                    photo, key=lambda p: getattr(p, "file_size", 0)
                )
                file_id = getattr(largest, "file_id", None)
                if file_id:
                    img_bytes = _download_telegram_file(file_id, bot)
                    if img_bytes:
                        text = _lsb_extract_text(img_bytes)
                        if text:
                            text_parts.append(text)
            except Exception:
                pass
    except Exception:
        pass

    return "\n".join(text_parts), []


# =============================================================================
# LAYER 14: DOMAIN REPUTATION
# =============================================================================

_domain_reputation_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_DOMAIN_REP_CACHE_MAX = 5000
_DOMAIN_REP_LOCK = threading.Lock()


def _domain_rep_cache_set(domain: str, entry: Dict[str, Any]) -> None:
    with _DOMAIN_REP_LOCK:
        _domain_reputation_cache[domain] = entry
        _domain_reputation_cache.move_to_end(domain)
        while len(_domain_reputation_cache) > _DOMAIN_REP_CACHE_MAX:
            _domain_reputation_cache.popitem(last=False)


def _domain_rep_cache_get(domain: str) -> Optional[Dict[str, Any]]:
    with _DOMAIN_REP_LOCK:
        entry = _domain_reputation_cache.get(domain)
        if entry is None:
            return None
        _domain_reputation_cache.move_to_end(domain)
        return dict(entry)


def _domain_heuristic_analysis(domain: str) -> Tuple[int, List[str]]:
    if not domain:
        return 0, []

    domain = domain.lower().strip()
    parts = domain.split(".")
    if len(parts) < 2:
        return 0, []

    label = parts[0]
    tld = parts[-1]

    score = 0
    reasons: List[str] = []

    if len(label) >= 15:
        score += 2
        reasons.append(f"very_long_label:{len(label)}")
    elif len(label) >= 12:
        score += 1
        reasons.append(f"long_label:{len(label)}")

    digit_count = sum(1 for ch in label if ch.isdigit())
    if digit_count >= 4:
        score += 2
        reasons.append(f"many_digits:{digit_count}")

    dash_count = label.count("-")
    if dash_count >= 3:
        score += 2
        reasons.append(f"many_dashes:{dash_count}")

    _suspicious_tlds = {
        "tk", "ml", "ga", "cf", "gq", "icu", "cyou",
        "bond", "click", "download", "stream", "review",
        "top", "xyz", "buzz", "lol", "zip", "mov",
    }
    if tld in _suspicious_tlds:
        score += 2
        reasons.append(f"suspicious_tld:{tld}")

    if len(parts) >= 4:
        score += 2
        reasons.append(f"deep_subdomains:{len(parts)}")

    if len(parts) >= 3 and parts[0].isdigit():
        score += 1
        reasons.append("numeric_subdomain")

    if re.search(
        r"(?i)(?:free|win|prize|bonus|casino|porn|xxx|sex|bet|dating)",
        domain,
    ):
        score += 2
        reasons.append("spam_keyword_in_domain")

    if re.match(r"^\d+\.\d+\.\d+\.\d+", domain):
        score += 3
        reasons.append("raw_ip_domain")

    return min(score, 8), reasons


def analyze_domain_reputation(url: str) -> Tuple[int, List[str]]:
    if not DOMAIN_REP_LAYER_ENABLED or not url:
        return 0, []

    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
        domain = parsed.netloc.lower()
        domain = re.sub(r"^www\.", "", domain).split(":")[0]

        if not domain:
            return 0, []

        entry = _domain_rep_cache_get(domain)
        if entry is not None:
            age = time.time() - entry["ts"]
            if age < 3600:
                return entry["score"], entry["reasons"]

        score, reasons = _domain_heuristic_analysis(domain)

        _domain_rep_cache_set(domain, {
            "ts": time.time(),
            "score": score,
            "reasons": reasons,
        })

        return score, reasons
    except Exception as exc:
        logger.debug("domain rep error: %r", exc)
        return 0, []


# =============================================================================
# ORCHESTRATOR (15 layers)
# =============================================================================

@dataclass
class SpamVerdict:
    is_spam: bool
    total_score: float
    confidence: str
    layer_scores: Dict[str, float] = field(default_factory=dict)
    layer_reasons: Dict[str, List[str]] = field(default_factory=dict)
    extracted_content: Dict[str, str] = field(default_factory=dict)
    url_analysis: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_spam": self.is_spam,
            "total_score": self.total_score,
            "confidence": self.confidence,
            "layer_scores": dict(self.layer_scores),
            "layer_reasons": {
                k: list(v) for k, v in self.layer_reasons.items()
            },
            "extracted_content": dict(self.extracted_content),
            "url_analysis": list(self.url_analysis),
        }


def _empty_text_result() -> Dict[str, Any]:
    return {
        "score": 0, "reasons": [], "confidence": "none",
        "hard": False, "critical": False,
        "text": "", "has_link": False, "has_button_link": False,
        "button_count": 0, "button_urls": [],
        "entity_urls": [], "possible_urls": [],
        "vcard_urls": [], "poll_urls": [], "venue_url": None,
        "is_forwarded": False, "is_auto_forwarded": False,
        "hidden_char_count": 0, "bidi_count": 0,
        "mixed_scripts": False, "script_counts": {},
        "url_count": 0, "telegram_link_count": 0,
        "spam_emoji_count": 0, "strong_word_count": 0,
        "medium_word_count": 0, "promo_word_count": 0,
        "arabic_spam_count": 0, "cta_count": 0,
        "financial_word_count": 0, "ai_generated_score": 0,
        "random_domains": [], "has_random_domain": False,
        "user_id": 0,
    }


def _run_text_layer(message: Any, verdict: SpamVerdict) -> Dict[str, Any]:
    if not TEXT_LAYER_ENABLED:
        return _empty_text_result()
    try:
        ctx = _MessageContext(message)
        score_info = _compute_spam_score(ctx, return_diagnostics=True)

        text_result: Dict[str, Any] = {
            **score_info,
            "text": ctx.analysis_text,
            "has_link": ctx.has_any_link,
            "has_button_link": ctx.has_button_link,
            "button_count": ctx.button_count,
            "button_urls": list(ctx.button_urls),
            "entity_urls": list(ctx.entity_urls),
            "possible_urls": list(ctx.possible_urls),
            "vcard_urls": list(ctx.vcard_urls),
            "poll_urls": list(ctx.poll_urls),
            "venue_url": ctx.venue_url,
            "is_forwarded": ctx.is_forwarded,
            "is_auto_forwarded": ctx.is_auto_fwd,
            "hidden_char_count": ctx.hidden_char_count,
            "bidi_count": ctx.bidi_count,
            "mixed_scripts": ctx.mixed_scripts,
            "script_counts": dict(ctx.script_counts),
            "url_count": ctx.url_count,
            "telegram_link_count": ctx.telegram_link_count,
            "spam_emoji_count": ctx.spam_emoji_count,
            "strong_word_count": ctx.strong_word_count,
            "medium_word_count": ctx.medium_word_count,
            "promo_word_count": ctx.promo_word_count,
            "arabic_spam_count": ctx.arabic_spam_count,
            "cta_count": ctx.cta_count,
            "financial_word_count": ctx.financial_word_count,
            "ai_generated_score": ctx.ai_generated_score,
            "random_domains": list(ctx.random_domains),
            "has_random_domain": ctx.has_random_domain,
            "user_id": (
                getattr(getattr(message, "from_user", None), "id", 0) or 0
            ),
        }

        verdict.layer_scores["text"] = score_info.get("score", 0)
        verdict.layer_reasons["text"] = score_info.get("reasons", [])
        return text_result
    except Exception as exc:
        logger.warning("L0 text layer failed: %r", exc)
        return _empty_text_result()


def _run_metadata_layer(message: Any, verdict: SpamVerdict) -> None:
    if not METADATA_LAYER_ENABLED:
        return
    try:
        meta_text = extract_metadata_text(message)
        if not meta_text:
            return
        verdict.extracted_content["metadata"] = meta_text
        meta_ctx = _MessageContext.from_text(meta_text)
        meta_result = _compute_spam_score(meta_ctx, return_diagnostics=True)
        verdict.layer_scores["metadata"] = meta_result.get("score", 0)
        verdict.layer_reasons["metadata"] = meta_result.get("reasons", [])
    except Exception as exc:
        logger.debug("L4 error: %r", exc)


def _run_obfuscation_layer(message: Any, verdict: SpamVerdict) -> None:
    if not OBFUSCATION_LAYER_ENABLED:
        return
    try:
        raw_text = _get_message_analysis_text(message)
        payloads = find_obfuscated_payloads(raw_text)
        if not payloads:
            return
        obf_score = 0
        obf_reasons: List[str] = []
        for method, decoded in payloads:
            obf_reasons.append(f"decoded_{method}")
            dec_ctx = _MessageContext.from_text(decoded)
            dec_result = _compute_spam_score(dec_ctx, return_diagnostics=True)
            obf_score += dec_result.get("score", 0)
        verdict.layer_scores["obfuscation"] = obf_score
        verdict.layer_reasons["obfuscation"] = obf_reasons
    except Exception as exc:
        logger.debug("L5 error: %r", exc)


def _run_behavioral_layer(
    message: Any,
    text_result: Dict[str, Any],
    verdict: SpamVerdict,
) -> None:
    if not BEHAVIORAL_LAYER_ENABLED:
        return
    try:
        user_id = int(text_result.get("user_id", 0) or 0)
        if not user_id:
            user = getattr(message, "from_user", None)
            user_id = getattr(user, "id", 0) if user else 0
        if not user_id:
            return
        text = getattr(message, "text", None) or ""
        has_url = bool(text_result.get("has_link", False))
        record_message(user_id, text, has_url)
        behav_score = 0
        behav_reasons: List[str] = []
        is_rate, rate_reason = check_rate_limit(user_id)
        if is_rate:
            behav_score += 4
            behav_reasons.append(rate_reason or "rate_limit")
        is_split, split_reason = check_split_url_pattern(user_id, text)
        if is_split:
            behav_score += 5
            behav_reasons.append(split_reason or "split_url")
        verdict.layer_scores["behavioral"] = behav_score
        verdict.layer_reasons["behavioral"] = behav_reasons
    except Exception as exc:
        logger.debug("L6 error: %r", exc)


def _run_reactions_layer(message: Any, verdict: SpamVerdict) -> None:
    if not REACTIONS_LAYER_ENABLED:
        return
    try:
        score, reasons = analyze_reactions(message)
        if score <= 0:
            return
        verdict.layer_scores["reactions"] = score
        verdict.layer_reasons["reactions"] = reasons
    except Exception as exc:
        logger.debug("L10 error: %r", exc)


def _run_context_layer(
    text_result: Dict[str, Any],
    verdict: SpamVerdict,
) -> None:
    if not CONTEXT_LAYER_ENABLED:
        return
    try:
        user_id = int(text_result.get("user_id", 0) or 0)
        if not user_id:
            return
        text = str(text_result.get("text", "") or "")
        has_url = bool(text_result.get("has_link", False))
        record_context_message(user_id, text, has_url)

        score, reasons = analyze_context_window(user_id)
        if score <= 0:
            return
        verdict.layer_scores["context"] = score
        verdict.layer_reasons["context"] = reasons
    except Exception as exc:
        logger.debug("L11 error: %r", exc)


def _run_cipher_layer(message: Any, verdict: SpamVerdict) -> None:
    if not CIPHER_LAYER_ENABLED:
        return
    try:
        raw_text = _get_message_analysis_text(message)
        payloads = _find_encoded_payloads(raw_text)
        if not payloads:
            return
        cipher_score = 0
        reasons: List[str] = []
        for method, decoded in payloads:
            reasons.append(f"decoded_{method}")
            dec_ctx = _MessageContext.from_text(decoded)
            dec_result = _compute_spam_score(dec_ctx, return_diagnostics=True)
            cipher_score += dec_result.get("score", 0)
        if cipher_score > 0:
            verdict.layer_scores["cipher"] = cipher_score
            verdict.layer_reasons["cipher"] = reasons
    except Exception as exc:
        logger.debug("L12 error: %r", exc)


def _run_domain_rep_layer(
    text_result: Dict[str, Any],
    verdict: SpamVerdict,
) -> None:
    if not DOMAIN_REP_LAYER_ENABLED:
        return
    try:
        all_urls = _unique_strings(
            text_result.get("entity_urls", [])
            + text_result.get("button_urls", [])
            + text_result.get("possible_urls", [])
        )
        if not all_urls:
            return

        total_score = 0
        reasons: List[str] = []
        for url in all_urls[:5]:
            score, rs = analyze_domain_reputation(url)
            total_score += score
            reasons.extend(rs)

        if total_score > 0:
            verdict.layer_scores["domain_rep"] = total_score
            verdict.layer_reasons["domain_rep"] = _unique_strings(reasons)
    except Exception as exc:
        logger.debug("L14 error: %r", exc)


# ─── Async Layers ────────────────────────────────────────────────────────────

async def _run_ocr_layer_async(
    message: Any, bot: Any, verdict: SpamVerdict
) -> None:
    if not OCR_LAYER_ENABLED or not _OCR_AVAILABLE:
        return
    try:
        ocr_text, qr_codes = await extract_image_content_async(message, bot)
        if not ocr_text and not qr_codes:
            return
        combined = "\n".join(filter(None, [ocr_text] + qr_codes))
        verdict.extracted_content["ocr"] = combined
        ocr_ctx = _MessageContext.from_text(combined)
        ocr_result = _compute_spam_score(ocr_ctx, return_diagnostics=True)
        verdict.layer_scores["ocr"] = ocr_result.get("score", 0)
        verdict.layer_reasons["ocr"] = ocr_result.get("reasons", [])
    except Exception as exc:
        logger.debug("L1 error: %r", exc)


async def _run_audio_layer_async(
    message: Any, bot: Any, verdict: SpamVerdict
) -> None:
    if not AUDIO_LAYER_ENABLED or not _AUDIO_AVAILABLE:
        return
    try:
        audio_text = await extract_audio_content_async(message, bot)
        if not audio_text:
            return
        verdict.extracted_content["audio"] = audio_text
        audio_ctx = _MessageContext.from_text(audio_text)
        audio_result = _compute_spam_score(audio_ctx, return_diagnostics=True)
        verdict.layer_scores["audio"] = audio_result.get("score", 0)
        verdict.layer_reasons["audio"] = audio_result.get("reasons", [])
    except Exception as exc:
        logger.debug("L2 error: %r", exc)


async def _run_url_layer_async(
    text_result: Dict[str, Any], verdict: SpamVerdict
) -> None:
    if not URL_LAYER_ENABLED or not URL_ENRICH_ENABLED:
        return
    try:
        venue = text_result.get("venue_url")
        venue_list = [venue] if venue else []

        all_urls = _unique_strings(
            text_result.get("entity_urls", [])
            + text_result.get("button_urls", [])
            + text_result.get("possible_urls", [])
            + text_result.get("vcard_urls", [])
            + text_result.get("poll_urls", [])
            + venue_list
        )

        if not all_urls:
            return

        if ASYNC_NETWORK_ENABLED:
            url_analysis = await analyze_urls_async(all_urls)
        else:
            url_analysis = await _run_in_pool(analyze_urls, all_urls)

        verdict.url_analysis = url_analysis
        url_score = 0
        url_reasons: List[str] = []
        for ua in url_analysis:
            if ua.get("suspicious"):
                url_score += 5
                url_reasons.extend(ua.get("reasons", []))
            if ua.get("is_shortener"):
                url_score += 2
                url_reasons.append("shortener")
            age = ua.get("domain_age_days")
            if age is not None and age < 7:
                url_score += 3
                url_reasons.append(f"very_new:{age}d")
        verdict.layer_scores["url"] = url_score
        verdict.layer_reasons["url"] = url_reasons
    except Exception as exc:
        logger.debug("L3 error: %r", exc)


async def _run_video_layer_async(
    message: Any, bot: Any, verdict: SpamVerdict
) -> None:
    if not VIDEO_LAYER_ENABLED or not _OCR_AVAILABLE:
        return
    try:
        video_text, qr_codes = await extract_video_content_async(
            message, bot
        )
        if not video_text and not qr_codes:
            return
        combined = "\n".join(filter(None, [video_text] + qr_codes))
        verdict.extracted_content["video"] = combined
        video_ctx = _MessageContext.from_text(combined)
        video_result = _compute_spam_score(video_ctx, return_diagnostics=True)
        verdict.layer_scores["video"] = video_result.get("score", 0)
        verdict.layer_reasons["video"] = video_result.get("reasons", [])
    except Exception as exc:
        logger.debug("L7 error: %r", exc)


async def _run_nsfw_layer_async(
    message: Any, bot: Any, verdict: SpamVerdict
) -> None:
    if not NSFW_LAYER_ENABLED:
        return
    try:
        is_nsfw, reasons = await extract_nsfw_from_message_async(
            message, bot
        )
        if not is_nsfw:
            return
        verdict.layer_scores["nsfw"] = 15
        verdict.layer_reasons["nsfw"] = reasons or ["nsfw_detected"]
    except Exception as exc:
        logger.debug("L8 error: %r", exc)


async def _run_sticker_layer_async(
    message: Any, bot: Any, verdict: SpamVerdict
) -> None:
    if not STICKER_LAYER_ENABLED:
        return
    try:
        sticker_text, spam_emojis = await _extract_sticker_text_async(
            message, bot
        )
        if not sticker_text and spam_emojis == 0:
            return

        sticker_score = 0
        reasons: List[str] = []

        if spam_emojis >= 1:
            sticker_score += 2
            reasons.append(f"spam_sticker_emoji:{spam_emojis}")

        if sticker_text:
            verdict.extracted_content["sticker"] = sticker_text
            st_ctx = _MessageContext.from_text(sticker_text)
            st_result = _compute_spam_score(st_ctx, return_diagnostics=True)
            sticker_score += st_result.get("score", 0)
            reasons.extend(st_result.get("reasons", []))

        if sticker_score > 0:
            verdict.layer_scores["sticker"] = sticker_score
            verdict.layer_reasons["sticker"] = reasons
    except Exception as exc:
        logger.debug("L9 error: %r", exc)


async def _run_stego_layer_async(
    message: Any, bot: Any, verdict: SpamVerdict
) -> None:
    if not STEGO_LAYER_ENABLED:
        return
    try:
        stego_text, _ = await extract_stego_content_async(message, bot)
        if not stego_text:
            return
        verdict.extracted_content["stego"] = stego_text
        stego_ctx = _MessageContext.from_text(stego_text)
        stego_result = _compute_spam_score(stego_ctx, return_diagnostics=True)
        if stego_result.get("score", 0) > 0:
            verdict.layer_scores["stego"] = stego_result.get("score", 0)
            verdict.layer_reasons["stego"] = stego_result.get("reasons", [])
    except Exception as exc:
        logger.debug("L13 error: %r", exc)


# ─── Sync Layers ─────────────────────────────────────────────────────────────

def _run_ocr_layer(message: Any, bot: Any, verdict: SpamVerdict) -> None:
    if not OCR_LAYER_ENABLED or not _OCR_AVAILABLE:
        return
    try:
        ocr_text, qr_codes = extract_image_content(message, bot)
        if not ocr_text and not qr_codes:
            return
        combined = "\n".join(filter(None, [ocr_text] + qr_codes))
        verdict.extracted_content["ocr"] = combined
        ocr_ctx = _MessageContext.from_text(combined)
        ocr_result = _compute_spam_score(ocr_ctx, return_diagnostics=True)
        verdict.layer_scores["ocr"] = ocr_result.get("score", 0)
        verdict.layer_reasons["ocr"] = ocr_result.get("reasons", [])
    except Exception as exc:
        logger.debug("L1 error: %r", exc)


def _run_audio_layer(message: Any, bot: Any, verdict: SpamVerdict) -> None:
    if not AUDIO_LAYER_ENABLED or not _AUDIO_AVAILABLE:
        return
    try:
        audio_text = extract_audio_content(message, bot)
        if not audio_text:
            return
        verdict.extracted_content["audio"] = audio_text
        audio_ctx = _MessageContext.from_text(audio_text)
        audio_result = _compute_spam_score(audio_ctx, return_diagnostics=True)
        verdict.layer_scores["audio"] = audio_result.get("score", 0)
        verdict.layer_reasons["audio"] = audio_result.get("reasons", [])
    except Exception as exc:
        logger.debug("L2 error: %r", exc)


def _run_url_layer(text_result: Dict[str, Any], verdict: SpamVerdict) -> None:
    if not URL_LAYER_ENABLED or not URL_ENRICH_ENABLED:
        return
    try:
        venue = text_result.get("venue_url")
        venue_list = [venue] if venue else []

        all_urls = _unique_strings(
            text_result.get("entity_urls", [])
            + text_result.get("button_urls", [])
            + text_result.get("possible_urls", [])
            + text_result.get("vcard_urls", [])
            + text_result.get("poll_urls", [])
            + venue_list
        )

        if not all_urls:
            return

        url_analysis = analyze_urls(all_urls)
        verdict.url_analysis = url_analysis
        url_score = 0
        url_reasons: List[str] = []
        for ua in url_analysis:
            if ua.get("suspicious"):
                url_score += 5
                url_reasons.extend(ua.get("reasons", []))
            if ua.get("is_shortener"):
                url_score += 2
                url_reasons.append("shortener")
            age = ua.get("domain_age_days")
            if age is not None and age < 7:
                url_score += 3
                url_reasons.append(f"very_new:{age}d")
        verdict.layer_scores["url"] = url_score
        verdict.layer_reasons["url"] = url_reasons
    except Exception as exc:
        logger.debug("L3 error: %r", exc)


def _run_video_layer(message: Any, bot: Any, verdict: SpamVerdict) -> None:
    if not VIDEO_LAYER_ENABLED or not _OCR_AVAILABLE:
        return
    try:
        video_text, qr_codes = extract_video_content(message, bot)
        if not video_text and not qr_codes:
            return
        combined = "\n".join(filter(None, [video_text] + qr_codes))
        verdict.extracted_content["video"] = combined
        video_ctx = _MessageContext.from_text(combined)
        video_result = _compute_spam_score(video_ctx, return_diagnostics=True)
        verdict.layer_scores["video"] = video_result.get("score", 0)
        verdict.layer_reasons["video"] = video_result.get("reasons", [])
    except Exception as exc:
        logger.debug("L7 error: %r", exc)


def _run_nsfw_layer(message: Any, bot: Any, verdict: SpamVerdict) -> None:
    if not NSFW_LAYER_ENABLED:
        return
    try:
        is_nsfw, reasons = extract_nsfw_from_message(message, bot)
        if not is_nsfw:
            return
        verdict.layer_scores["nsfw"] = 15
        verdict.layer_reasons["nsfw"] = reasons or ["nsfw_detected"]
    except Exception as exc:
        logger.debug("L8 error: %r", exc)


def _run_sticker_layer(message: Any, bot: Any, verdict: SpamVerdict) -> None:
    if not STICKER_LAYER_ENABLED:
        return
    try:
        sticker_text, spam_emojis = _extract_sticker_text_sync(message, bot)
        if not sticker_text and spam_emojis == 0:
            return

        sticker_score = 0
        reasons: List[str] = []

        if spam_emojis >= 1:
            sticker_score += 2
            reasons.append(f"spam_sticker_emoji:{spam_emojis}")

        if sticker_text:
            verdict.extracted_content["sticker"] = sticker_text
            st_ctx = _MessageContext.from_text(sticker_text)
            st_result = _compute_spam_score(st_ctx, return_diagnostics=True)
            sticker_score += st_result.get("score", 0)
            reasons.extend(st_result.get("reasons", []))

        if sticker_score > 0:
            verdict.layer_scores["sticker"] = sticker_score
            verdict.layer_reasons["sticker"] = reasons
    except Exception as exc:
        logger.debug("L9 error: %r", exc)


def _run_stego_layer(message: Any, bot: Any, verdict: SpamVerdict) -> None:
    if not STEGO_LAYER_ENABLED:
        return
    try:
        stego_text, _ = extract_stego_content(message, bot)
        if not stego_text:
            return
        verdict.extracted_content["stego"] = stego_text
        stego_ctx = _MessageContext.from_text(stego_text)
        stego_result = _compute_spam_score(stego_ctx, return_diagnostics=True)
        if stego_result.get("score", 0) > 0:
            verdict.layer_scores["stego"] = stego_result.get("score", 0)
            verdict.layer_reasons["stego"] = stego_result.get("reasons", [])
    except Exception as exc:
        logger.debug("L13 error: %r", exc)


def _aggregate_verdict(verdict: SpamVerdict) -> None:
    total = 0.0
    for layer, score in verdict.layer_scores.items():
        weight = LAYER_WEIGHTS.get(layer, 1.0)
        capped = _cap_layer_score(score, layer)
        total += capped * weight

    total = min(total, MAX_TOTAL_SCORE)
    verdict.total_score = round(total, 2)

    if total >= 20:
        verdict.confidence = "critical"
    elif total >= 12:
        verdict.confidence = "very_high"
    elif total >= FINAL_THRESHOLD:
        verdict.confidence = "high"
    elif total >= 3:
        verdict.confidence = "medium"
    elif total >= 1:
        verdict.confidence = "low"
    else:
        verdict.confidence = "none"

    verdict.is_spam = total >= FINAL_THRESHOLD


def _post_analysis_cleanup() -> None:
    try:
        cleanup_old_data()
    except Exception:
        pass


def analyze_message_full(message: Any, bot: Any = None) -> SpamVerdict:
    verdict = SpamVerdict(
        is_spam=False, total_score=0.0, confidence="none"
    )

    text_result = _run_text_layer(message, verdict)
    _run_ocr_layer(message, bot, verdict)
    _run_audio_layer(message, bot, verdict)
    _run_url_layer(text_result, verdict)
    _run_metadata_layer(message, verdict)
    _run_obfuscation_layer(message, verdict)
    _run_behavioral_layer(message, text_result, verdict)
    _run_video_layer(message, bot, verdict)
    _run_nsfw_layer(message, bot, verdict)
    _run_sticker_layer(message, bot, verdict)
    _run_reactions_layer(message, verdict)
    _run_context_layer(text_result, verdict)
    _run_cipher_layer(message, verdict)
    _run_stego_layer(message, bot, verdict)
    _run_domain_rep_layer(text_result, verdict)

    _aggregate_verdict(verdict)
    _post_analysis_cleanup()

    if DEBUG_SPAM:
        try:
            logger.debug(
                "[SHIELD] layers=%s total=%.1f confidence=%s",
                verdict.layer_scores,
                verdict.total_score,
                verdict.confidence,
            )
        except Exception:
            pass

    return verdict


async def analyze_message_full_async(
    message: Any, bot: Any = None
) -> SpamVerdict:
    """
    ✅ v4.0.8 FIX-G: تعليق دقيق حول الترتيب.

    الترتيب:
      1) text layer (sync سريعة) — تُنتج text_result.
      2) sync سريعة (behavioral, context, reactions, ...) — تسجّل سلوك
         المستخدم بأسرع وقت قبل أي I/O.
      3) async I/O layers — بالتوازي عبر asyncio.gather مع Semaphore(6).
    """
    verdict = SpamVerdict(
        is_spam=False, total_score=0.0, confidence="none"
    )

    text_result = _run_text_layer(message, verdict)

    _run_metadata_layer(message, verdict)
    _run_obfuscation_layer(message, verdict)
    _run_behavioral_layer(message, text_result, verdict)
    _run_reactions_layer(message, verdict)
    _run_context_layer(text_result, verdict)
    _run_cipher_layer(message, verdict)
    _run_domain_rep_layer(text_result, verdict)

    sem = asyncio.Semaphore(6)

    async def _guarded(coro_fn, *args):
        async with sem:
            try:
                return await coro_fn(*args)
            except Exception as exc:
                logger.debug("guarded layer error: %r", exc)
                return None

    await asyncio.gather(
        _guarded(_run_ocr_layer_async, message, bot, verdict),
        _guarded(_run_audio_layer_async, message, bot, verdict),
        _guarded(_run_url_layer_async, text_result, verdict),
        _guarded(_run_video_layer_async, message, bot, verdict),
        _guarded(_run_nsfw_layer_async, message, bot, verdict),
        _guarded(_run_sticker_layer_async, message, bot, verdict),
        _guarded(_run_stego_layer_async, message, bot, verdict),
        return_exceptions=True,
    )

    _aggregate_verdict(verdict)
    _post_analysis_cleanup()

    if DEBUG_SPAM:
        try:
            logger.debug(
                "[SHIELD-ASYNC] layers=%s total=%.1f confidence=%s",
                verdict.layer_scores,
                verdict.total_score,
                verdict.confidence,
            )
        except Exception:
            pass

    return verdict


def analyze_message(message: Any) -> Dict[str, Any]:
    ctx = _MessageContext(message)
    result = _compute_spam_score(ctx, return_diagnostics=True)
    result.update({
        "text": ctx.analysis_text,
        "has_link": ctx.has_any_link,
        "has_button_link": ctx.has_button_link,
        "button_count": ctx.button_count,
        "button_urls": list(ctx.button_urls),
        "entity_urls": list(ctx.entity_urls),
        "possible_urls": list(ctx.possible_urls),
        "vcard_urls": list(ctx.vcard_urls),
        "poll_urls": list(ctx.poll_urls),
        "venue_url": ctx.venue_url,
        "is_forwarded": ctx.is_forwarded,
        "is_auto_forwarded": ctx.is_auto_fwd,
        "hidden_char_count": ctx.hidden_char_count,
        "bidi_count": ctx.bidi_count,
        "mixed_scripts": ctx.mixed_scripts,
        "script_counts": dict(ctx.script_counts),
        "url_count": ctx.url_count,
        "telegram_link_count": ctx.telegram_link_count,
        "spam_emoji_count": ctx.spam_emoji_count,
        "strong_word_count": ctx.strong_word_count,
        "medium_word_count": ctx.medium_word_count,
        "promo_word_count": ctx.promo_word_count,
        "arabic_spam_count": ctx.arabic_spam_count,
        "cta_count": ctx.cta_count,
        "financial_word_count": ctx.financial_word_count,
        "ai_generated_score": ctx.ai_generated_score,
        "random_domains": list(ctx.random_domains),
        "has_random_domain": ctx.has_random_domain,
        "is_arabic_short_whitelisted": ctx.is_arabic_short_whitelisted,
    })
    return result


def is_spam(message: Any) -> bool:
    score, _ = _compute_spam_score(message)
    return score >= SPAM_SCORE_THRESHOLD


def is_high_confidence_spam(message: Any) -> bool:
    score, _ = _compute_spam_score(message)
    return score >= SPAM_HARD_THRESHOLD


def is_critical_spam(message: Any) -> bool:
    score, _ = _compute_spam_score(message)
    return score >= SPAM_CRITICAL_THRESHOLD


def should_ignore_as_low_signal(message: Any) -> bool:
    try:
        ctx = _MessageContext(message)
        if not ctx.analysis_text:
            return True
        if _looks_like_normal_conversation(ctx.analysis_text):
            score, _ = _compute_spam_score(ctx)
            return score < SPAM_SCORE_THRESHOLD
    except Exception:
        return False
    return False


def get_spam_diagnostics(message: Any) -> Dict[str, Any]:
    try:
        ctx = _MessageContext(message)
        score_info = _compute_spam_score(ctx, return_diagnostics=True)
        split_words = _detect_split_spam_words(
            ctx.normalized_text, already_normalized=True
        )
        url_obfuscated, url_reasons = _detect_url_obfuscation(
            ctx.normalized_text, already_normalized=True
        )
        unicode_score, unicode_reasons = _detect_unicode_evasion(
            ctx.analysis_text, script_counts=ctx.script_counts
        )
        density_score, density_reasons = _text_density_signals(
            ctx.analysis_text
        )
        structural_score, structural_reasons = _detect_structural_evasion(
            ctx.analysis_text, already_normalized=True
        )
        contact_score, contact_reasons = _detect_phone_or_contact_evasion(
            ctx.normalized_text, already_normalized=True
        )
        return {
            **score_info,
            "text": ctx.analysis_text,
            "detector_version": _DETECTORS_VERSION,
            "full_text": ctx.full_text,
            "normalized_text": ctx.normalized_text,
            "normalized_compact": ctx.normalized_compact,
            "normalized_url_text": ctx.normalized_url_text,
            "buttons": {
                "count": ctx.button_count,
                "urls": list(ctx.button_urls),
                "texts": list(ctx.button_texts),
                "has_external": ctx.has_button_link,
            },
            "links": {
                "entity": list(ctx.entity_urls),
                "button": list(ctx.button_link_urls),
                "possible": list(ctx.possible_urls),
                "vcard": list(ctx.vcard_urls),
                "poll": list(ctx.poll_urls),
                "venue": ctx.venue_url,
                "detected": ctx.has_any_link,
                "count": ctx.url_count,
                "telegram_count": ctx.telegram_link_count,
                "email": _contains_email(
                    ctx.normalized_text, already_normalized=True
                ),
                "username": _contains_at_channel(
                    ctx.normalized_text, already_normalized=True
                ),
                "random_domains": list(ctx.random_domains),
                "has_random_domain": ctx.has_random_domain,
            },
            "evasion": {
                "hidden_chars": ctx.hidden_char_count,
                "bidi_chars": ctx.bidi_count,
                "mixed_scripts": ctx.mixed_scripts,
                "unicode_score": unicode_score,
                "unicode_reasons": unicode_reasons,
                "url_obfuscation": url_obfuscated,
                "url_reasons": url_reasons,
                "split_spam_words": split_words,
                "structural_score": structural_score,
                "structural_reasons": structural_reasons,
            },
            "density": {
                "score": density_score, "reasons": density_reasons,
            },
            "contact": {
                "score": contact_score, "reasons": contact_reasons,
            },
            "vocabulary": {
                "strong": ctx.strong_word_count,
                "medium": ctx.medium_word_count,
                "promo": ctx.promo_word_count,
                "arabic": ctx.arabic_spam_count,
                "cta": ctx.cta_count,
                "financial": ctx.financial_word_count,
            },
            "ai_generated": {
                "score": ctx.ai_generated_score,
            },
            "postbot": {
                "is_pattern": _is_postbot_pattern(
                    ctx.normalized_text,
                    button_count=ctx.button_count,
                    button_urls=ctx.button_urls,
                    already_normalized=True,
                ),
                "confidence": score_info["postbot_confidence"],
            },
            # 🆕 v4.0.9
            "arabic_short_whitelist": {
                "enabled": ARABIC_SHORT_WHITELIST_ENABLED,
                "is_whitelisted": ctx.is_arabic_short_whitelisted,
                "max_chars": ARABIC_SHORT_MAX_CHARS,
                "max_words": ARABIC_SHORT_MAX_WORDS,
            },
        }
    except Exception as exc:
        return {
            "score": 0, "reasons": ["diagnostic_error"],
            "confidence": "none", "hard": False, "critical": False,
            "error": repr(exc), "detector_version": _DETECTORS_VERSION,
        }


# =============================================================================
# __all__
# =============================================================================

__all__ = [
    # Configuration
    "DEBUG_DIAG", "DEBUG_SPAM",
    "TEXT_LAYER_ENABLED", "OCR_LAYER_ENABLED", "AUDIO_LAYER_ENABLED",
    "URL_LAYER_ENABLED", "METADATA_LAYER_ENABLED",
    "OBFUSCATION_LAYER_ENABLED", "BEHAVIORAL_LAYER_ENABLED",
    "VIDEO_LAYER_ENABLED", "NSFW_LAYER_ENABLED", "STICKER_LAYER_ENABLED",
    "REACTIONS_LAYER_ENABLED", "CONTEXT_LAYER_ENABLED",
    "CIPHER_LAYER_ENABLED", "STEGO_LAYER_ENABLED",
    "DOMAIN_REP_LAYER_ENABLED",
    "ASYNC_NETWORK_ENABLED", "ASYNC_NETWORK_TIMEOUT",
    "SAFE_BROWSING_API_KEY", "URL_ENRICH_ENABLED",
    "AUDIO_USE_WHISPER", "NSFW_MODEL_ENABLED", "NSFW_THRESHOLD",
    "NSFW_SIGHTENGINE_MAX_BYTES", "NORMALIZE_CACHE_MAX",
    "SE_CIRCUIT_FAILURE_THRESHOLD", "SE_CIRCUIT_OPEN_SEC",
    "URL_EXPAND_CONNECT_TIMEOUT", "URL_EXPAND_READ_TIMEOUT",
    "URL_EXPAND_TIMEOUT", "URL_EXPAND_MAX_HOPS", "URL_ENRICH_MAX_URLS",
    "_POOL_MAX_WORKERS", "POOL_TASK_TIMEOUT",

    # 🆕 v4.0.9: Arabic short whitelist
    "ARABIC_SHORT_WHITELIST_ENABLED", "ARABIC_SHORT_MAX_CHARS",
    "ARABIC_SHORT_MAX_WORDS", "ARABIC_DOMINANCE_RATIO",
    "_ARABIC_GREETINGS", "_ARABIC_SPAM_OVERRIDE",
    "_is_arabic_dominant", "_is_arabic_short_whitelisted",
    "_arabic_char_ratio", "_normalize_arabic_for_compare",
    "_strip_arabic_diacritics",

    # Anti-evasion toggles
    "ANTIEVASION_ENTITY_LINK", "ANTIEVASION_BUTTON_LINK",
    "ANTIEVASION_SCHEMELESS_URL", "ANTIEVASION_HOMOGLYPH",
    "ANTIEVASION_COMBINING", "ANTIEVASION_COMPACT_WORDS",
    "ANTIEVASION_EMOJI_SEPARATOR", "ANTIEVASION_BUTTON_WEBAPP",
    "ANTIEVASION_BUTTON_LOGINURL", "ANTIEVASION_LEETSPEAK",
    "ANTIEVASION_TG_SCHEME", "ANTIEVASION_AT_CHANNEL",
    "ANTIEVASION_EMAIL", "ANTIEVASION_PUNYCODE",
    "ANTIEVASION_IPV4_SCHEMELESS", "ANTIEVASION_MULTILINE_URL",
    "ANTIEVASION_VENUE_VCARD", "ANTIEVASION_POLL",
    "ANTIEVASION_EMOJI_IN_DOMAIN", "ANTIEVASION_UNICODE_DOTS",
    "ANTIEVASION_EXTENDED_COMBINING", "ANTIEVASION_EXTRA_SCRIPTS",
    "ANTIEVASION_ALT_SCHEMES", "ANTIEVASION_RANDOM_DOMAIN",

    # Thresholds
    "SPAM_SCORE_THRESHOLD", "POSTBOT_AUTO_BLOCK_CONFIDENCE",
    "SPAM_HARD_THRESHOLD", "SPAM_CRITICAL_THRESHOLD",
    "RANDOM_DOMAIN_MIN_LENGTH", "RANDOM_DOMAIN_MAX_VOWEL_RATIO",
    "FINAL_THRESHOLD", "LAYER_WEIGHTS", "LAYER_SCORE_CAPS",
    "MAX_TOTAL_SCORE", "_MAX_EXTRACTED_URLS", "_CONTEXT_WINDOW_SEC",

    # Classes
    "SpamVerdict", "_MessageContext",

    # Core helpers
    "_strip_combining_marks", "_deleet", "_apply_homoglyphs_safe",
    "_normalize_text", "_do_normalize", "_normalize_text_cached",
    "_strip_emoji_for_domain", "_has_hidden_chars", "_merge_split_urls",
    "_compute_ai_generated_score",

    "_extract_entity_urls", "_has_link_entity",
    "_extract_url_from_button", "_button_is_external",
    "_extract_button_context", "_extract_vcard_urls",
    "_extract_venue_url", "_extract_poll_text",

    "_get_message_button_data", "_get_message_button_texts",
    "_get_message_analysis_text",

    "_has_domain_pattern", "_contains_link_enhanced",
    "_contains_email", "_contains_at_channel", "_contains_tg_scheme",

    "_has_button_link", "_extract_button_link_urls",

    "_extract_spam_words", "_count_unique_matches",
    "_count_text_urls", "_compute_spam_score",

    "_is_postbot_pattern", "_postbot_pattern_confidence",

    "_is_random_domain", "_has_random_domain",
    "_extract_random_domains", "_extract_random_domains_from_merged",
    "_shannon_entropy",

    # Extractors
    "extract_text_from_image", "extract_qr_codes",
    "extract_image_content", "extract_image_content_async",
    "transcribe_audio", "extract_audio_content",
    "extract_audio_content_async",
    "expand_url", "is_shortener", "check_safe_browsing",
    "get_domain_age_days", "analyze_url", "analyze_urls",
    "analyze_urls_async",
    "extract_metadata_text", "metadata_has_suspicious_content",
    "extract_metadata_urls",
    "try_decode_base64", "try_decode_rot13", "try_decode_hex",
    "try_decode_url", "try_decode_reverse",
    "find_obfuscated_payloads", "has_any_obfuscation",
    "record_message", "check_rate_limit",
    "check_split_url_pattern", "track_edit", "cleanup_old_data",
    "_extract_video_frames", "extract_video_content",
    "extract_video_content_async",

    # NSFW
    "_check_nsfw_via_sightengine", "_analyze_nsfw_image",
    "_load_nsfw_classifier", "_has_any_nsfw_provider",
    "_detect_image_mime",
    "extract_nsfw_from_message", "extract_nsfw_from_message_async",

    # Other layers
    "_extract_sticker_text", "_extract_sticker_text_async",
    "analyze_reactions",
    "record_context_message", "analyze_context_window",
    "try_decode_multi_base64", "try_decode_caesar", "try_decode_xor",
    "_find_encoded_payloads",
    "_lsb_extract_text", "extract_stego_content",
    "extract_stego_content_async",
    "_domain_heuristic_analysis", "analyze_domain_reputation",

    # Public API
    "analyze_message_full", "analyze_message_full_async",
    "analyze_message", "get_spam_diagnostics",
    "is_spam", "is_high_confidence_spam", "is_critical_spam",
    "should_ignore_as_low_signal",

    # Utilities
    "_version_semver",
    "_download_telegram_file", "_download_telegram_file_async",

    # Pool APIs
    "_get_shared_pool", "_shutdown_shared_pool",
    "_run_in_pool", "install_default_executor",
    "shutdown_default_executor",
]


# =============================================================================
# LOAD BEACON
# =============================================================================

try:
    _se_user = os.getenv("SIGHTENGINE_API_USER", "")
    _se_ok = bool(_se_user)
    _nsfw_local_ok = bool(NSFW_MODEL_ENABLED and _PIL_AVAILABLE)

    logger.info(
        "🛡️ handlers_message_detectors %s loaded | "
        "15 Layers ASYNC-NATIVE | "
        "Text=%s OCR=%s(PIL=%s) Audio=%s(%s) URL=%s(%s) "
        "Meta=%s Obf=%s Behav=%s Video=%s(%s) NSFW=%s(local_cfg=%s,se=%s) "
        "Sticker=%s Reactions=%s Context=%s Cipher=%s "
        "Stego=%s(numpy=%s,pil=%s) DomainRep=%s | "
        "SPAM_THRESHOLD=%d HARD=%d CRITICAL=%d | "
        "TLDs=%d RANDOM_DOMAIN=%s ASYNC_NET=%s POOL=%d "
        "SE_CIRCUIT=%d/%ds TIMEOUT=%.1fs | "
        "AR_SHORT_WHITELIST=%s (max=%d chars/%d words, ratio=%.2f)",
        _DETECTORS_VERSION,
        TEXT_LAYER_ENABLED,
        OCR_LAYER_ENABLED, _PIL_AVAILABLE,
        AUDIO_LAYER_ENABLED, _AUDIO_AVAILABLE,
        URL_LAYER_ENABLED, bool(SAFE_BROWSING_API_KEY),
        METADATA_LAYER_ENABLED,
        OBFUSCATION_LAYER_ENABLED,
        BEHAVIORAL_LAYER_ENABLED,
        VIDEO_LAYER_ENABLED, (_CV2_AVAILABLE or _FFMPEG_AVAILABLE),
        NSFW_LAYER_ENABLED, _nsfw_local_ok, _se_ok,
        STICKER_LAYER_ENABLED,
        REACTIONS_LAYER_ENABLED,
        CONTEXT_LAYER_ENABLED,
        CIPHER_LAYER_ENABLED,
        STEGO_LAYER_ENABLED, _NUMPY_AVAILABLE, _PIL_AVAILABLE,
        DOMAIN_REP_LAYER_ENABLED,
        SPAM_SCORE_THRESHOLD,
        SPAM_HARD_THRESHOLD,
        SPAM_CRITICAL_THRESHOLD,
        len(_COMMON_TLDS),
        ANTIEVASION_RANDOM_DOMAIN,
        ASYNC_NETWORK_ENABLED,
        _POOL_MAX_WORKERS,
        SE_CIRCUIT_FAILURE_THRESHOLD,
        int(SE_CIRCUIT_OPEN_SEC),
        POOL_TASK_TIMEOUT,
        ARABIC_SHORT_WHITELIST_ENABLED,
        ARABIC_SHORT_MAX_CHARS,
        ARABIC_SHORT_MAX_WORDS,
        ARABIC_DOMINANCE_RATIO,
    )
except Exception:
    pass