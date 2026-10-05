#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_message_detectors.py
===============================================================================
🛡️ Relax Manager — Advanced Spam / Anti-Evasion Detection Engine
Version: 3.0.1 UNIFIED (7 Layers)

محرك كشف مستقل عن handlers_message.py.

===============================================================================
🆕 v3.0.1 (BUTTON-LINK-DETECTION-FIX):
    🔴 FIX-1: _extract_url_from_button يدعم الآن:
              url / web_app / login_url / copy_text /
              switch_inline_query / callback_data
    🔴 FIX-2: _compute_spam_score — لا يُقصّ score إلى 4 عندما
              الروابط موجودة كأزرار (is_button_only_case)
    🔴 FIX-3: _MessageContext._populate — كشف أوسع للأزرار
              (فحص مباشر لـ reply_markup.inline_keyboard[*].url)
    🟢 FIX-4: Log تشخيصي 🔘 BUTTONS_DETECTED في _populate
===============================================================================
    Layer 0: TEXT         — نصوص + روابط + Unicode evasion
    Layer 1: OCR          — Tesseract + QR codes
    Layer 2: AUDIO        — Whisper / Google Speech-to-Text
    Layer 3: URL          — Safe Browsing + WHOIS + expansion
    Layer 4: METADATA     — Bio / Channel / Name
    Layer 5: OBFUSCATION  — Base64 / ROT13 / Hex / URL encode
    Layer 6: BEHAVIORAL   — Rate limit + Cross-message + Edits
===============================================================================
"""

from __future__ import annotations

import base64
import codecs
import html
import io
import logging
import math
import os
import re
import time
import unicodedata
import urllib.parse
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse  # type: ignore


# =============================================================================
# LOAD BEACON
# =============================================================================

logger = logging.getLogger(__name__)

_DETECTORS_VERSION = "3.0.1 UNIFIED"


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


DEBUG_DIAG = _env_bool("DEBUG_DIAG", False)
DEBUG_SPAM = _env_bool("DEBUG_SPAM", False)

# Layer toggles
TEXT_LAYER_ENABLED = _env_bool("TEXT_LAYER_ENABLED", True)
OCR_LAYER_ENABLED = _env_bool("OCR_LAYER_ENABLED", True)
AUDIO_LAYER_ENABLED = _env_bool("AUDIO_LAYER_ENABLED", True)
URL_LAYER_ENABLED = _env_bool("URL_LAYER_ENABLED", True)
METADATA_LAYER_ENABLED = _env_bool("METADATA_LAYER_ENABLED", True)
OBFUSCATION_LAYER_ENABLED = _env_bool("OBFUSCATION_LAYER_ENABLED", True)
BEHAVIORAL_LAYER_ENABLED = _env_bool("BEHAVIORAL_LAYER_ENABLED", True)

# Text-layer antievasion
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

# URL enrichment
SAFE_BROWSING_API_KEY = os.getenv("SAFE_BROWSING_API_KEY", "")
URL_ENRICH_ENABLED = _env_bool("URL_ENRICH_ENABLED", True)
URL_EXPAND_TIMEOUT = int(os.getenv("URL_EXPAND_TIMEOUT", "5"))
URL_EXPAND_MAX_HOPS = int(os.getenv("URL_EXPAND_MAX_HOPS", "5"))
URL_ENRICH_MAX_URLS = int(os.getenv("URL_ENRICH_MAX_URLS", "5"))
WHOIS_ENABLED = _env_bool("WHOIS_ENABLED", True)
WHOIS_NEW_DOMAIN_DAYS = int(os.getenv("WHOIS_NEW_DOMAIN_DAYS", "30"))

# Audio
AUDIO_USE_WHISPER = _env_bool("AUDIO_USE_WHISPER", False)


# =============================================================================
# OPTIONAL DEPENDENCIES
# =============================================================================

_OCR_AVAILABLE = False
_QR_AVAILABLE = False
_AUDIO_AVAILABLE = False
_WHISPER_AVAILABLE = False
_REQUESTS_AVAILABLE = False
_WHOIS_AVAILABLE = False

try:
    import pytesseract  # type: ignore
    from PIL import Image, ImageEnhance  # type: ignore
    _OCR_AVAILABLE = True
except ImportError:
    pass

try:
    from pyzbar.pyzbar import decode as _qr_decode  # type: ignore
    _QR_AVAILABLE = True
except ImportError:
    pass

try:
    import speech_recognition as _sr  # type: ignore
    from pydub import AudioSegment as _AudioSegment  # type: ignore
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

# OCR
OCR_MIN_CONFIDENCE = 40
OCR_MAX_IMAGE_SIZE = (2000, 2000)
OCR_LANGUAGES = os.getenv("OCR_LANGUAGES", "ara+eng+fas+rus")

# Behavioral
RATE_WINDOW_SECONDS = 60
RATE_MAX_MESSAGES = 15
RATE_MAX_SHORT = 10
RATE_MAX_URLS = 5
CROSS_MSG_WINDOW = 30
CROSS_MSG_MAX_PARTS = 3

# Aggregation
FINAL_THRESHOLD = 5

LAYER_WEIGHTS = {
    "text": 1.0,
    "ocr": 1.2,
    "audio": 1.1,
    "url": 1.5,
    "metadata": 0.8,
    "obfuscation": 1.3,
    "behavioral": 1.0,
}

# Category caps
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
    "info", "gov", "edu", "biz", "name", "mobi",
    "asia", "tel",
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
# HIDDEN / BIDI / UNICODE
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


# =============================================================================
# HOMOGLYPHS / LEETSPEAK
# =============================================================================

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

_LEET_TARGETS = {
    "spam", "scam", "porn", "porno", "xxx",
    "nude", "nudes", "leak", "leaked", "leaks",
    "viral", "mega", "megapack", "pack", "packs",
    "premium", "private", "secret", "hidden",
    "uncensored", "uncut", "download", "click",
    "watch", "open", "join", "subscribe",
    "unlock", "exclusive",
}


# =============================================================================
# TRANSLATION TABLES
# =============================================================================

_WS_TRANSLATE_TABLE = str.maketrans({
    **{chr(c): " " for c in range(0x2000, 0x200B)},
    "\u00a0": " ",
})

_UNICODE_DOT_TABLE = str.maketrans({
    "\u2024": ".", "\u2025": ".", "\u2026": ".",
    "\u3002": ".", "\uFE52": ".", "\uFF0E": ".", "\uFF61": ".",
})

_EMOJI_STRIP_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]")


# =============================================================================
# REGEX — TEXT LAYER
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
    r"(?i)\bt\s*[\.\[\(\{]?\s*m\s*[\.\]\)\}]?\s*e\b"
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
    rf"(?is)\b[a-z0-9_-]{{2,50}}\s*[\r\n]+\s*"
    rf"(?:\.\s*[\r\n]+\s*|\u2024|\u3002|\.)\s*[\r\n]*"
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
    r"(?i)\b(?:\d{2,7}\s*\+?\s*"
    r"(?:clips?|videos?|pics?|photos?|files?|items?|"
    r"مقطع|مقاطع|فيديوهات?))\b"
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
_MULTISPACE_SPLIT_RE = re.compile(r"(?i)\b(?:[a-z]\s+){3,}[a-z]\b")
_EMOJI_SPLIT_RE = re.compile(
    r"(?i)\b(?:[a-z]\s*[\U0001F000-\U0001FAFF]\s*){3,}[a-z]\b"
)
_LONG_DOMAIN_LABEL_RE = re.compile(r"(?i)\b[a-z0-9-]{35,}\.[a-z]{2,63}\b")
_MULTILINE_URL_SCHEME_RE = re.compile(
    r"(?is)\b(?:h\s*t\s*t\s*p\s*s?|hxxps?|ftp)\s*[:]\s*[/\\]\s*[/\\]"
)


# =============================================================================
# REGEX — OBFUSCATION / URL
# =============================================================================

_BASE64_RE = re.compile(r"^[A-Za-z0-9+/]{16,}={0,2}$")
_BASE64_URLSAFE_RE = re.compile(r"^[A-Za-z0-9_-]{16,}={0,2}$")

_URL_SIGNATURES = (
    "http://", "https://", "www.", "t.me/", "telegram.me/",
    ".com", ".net", ".org", ".io", ".xyz", ".digital",
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
}

_ARABIC_CTA_WORDS = {
    "اضغط", "شاهد", "مشاهدة", "شوف", "ادخل",
    "دخول", "افتح", "انضم", "اشترك", "تحميل",
    "حمل", "حمّل", "الرابط", "هنا", "اضغطهنا",
}

_EXTRA_SCRIPT_SPAM_WORDS = {
    "فروش", "دانلود", "رایگان", "خصوصی",
    "محرمانه", "ویدیو", "ویدئو", "تصاویر",
    "لینک", "کلیپ",
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
}

_SPAM_EMOJI_SINGLE = frozenset(e for e in _SPAM_EMOJIS if len(e) == 1)
_SPAM_EMOJI_MULTI = tuple(e for e in _SPAM_EMOJIS if len(e) > 1)


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
# RANDOM DOMAIN HEURISTIC
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
        if parts[-1] not in _COMMON_TLDS:
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


def _has_random_domain(text: str) -> bool:
    if not text or not ANTIEVASION_RANDOM_DOMAIN:
        return False
    try:
        merged = _merge_split_urls(_normalize_text(text))
        for match in _DOMAIN_RE.finditer(merged):
            if _is_random_domain(match.group(0)):
                return True
    except Exception:
        pass
    return False


def _extract_random_domains(text: str) -> List[str]:
    if not text or not ANTIEVASION_RANDOM_DOMAIN:
        return []
    found: List[str] = []
    try:
        merged = _merge_split_urls(_normalize_text(text))
        for match in _DOMAIN_RE.finditer(merged):
            domain = match.group(0)
            if _is_random_domain(domain):
                found.append(domain)
    except Exception:
        pass
    return _unique_strings(found)


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
    words = set(_extract_words(normalized))
    count = 0
    for word in vocabulary:
        w = str(word).casefold()
        if w in words:
            count += 1
            continue
        if re.search(
            rf"(?<!\w){re.escape(w)}(?!\w)",
            normalized,
            flags=re.IGNORECASE,
        ):
            count += 1
    return count


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
        for target in _LEET_TARGETS:
            if (
                compact_candidate == target
                or compact_candidate.startswith(target)
                or compact_candidate.endswith(target)
            ):
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


def _normalize_text(text: str) -> str:
    if not text:
        return ""
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
    if scheme in ("https", "hxxps", "httpsx", "ttps", "htps"):
        return "https://"
    if scheme == "ftp":
        return "ftp://"
    return "http://"


def _tld_aware_dot_repl(match: re.Match) -> str:
    left, right = match.group(1), match.group(2)
    if right.lower() in _COMMON_TLDS:
        return f"{left}.{right}"
    return match.group(0)


def _tld_aware_dot_word_repl(match: re.Match) -> str:
    left, right = match.group(1), match.group(2)
    if right.lower() in _COMMON_TLDS:
        return f"{left}.{right}"
    return match.group(0)


def _tld_aware_multiline_repl(match: re.Match) -> str:
    left, right = match.group(1), match.group(2)
    if right.lower() in _COMMON_TLDS:
        return f"{left}.{right}"
    return match.group(0)


def _merge_split_urls(text: str) -> str:
    if not text:
        return ""
    value = str(text)
    value = re.sub(
        r"(?i)\b(?:h\s*t\s*t\s*p\s*s?|h\s*x\s*x\s*p\s*s?|f\s*t\s*p)"
        r"\s*[:]\s*/\s*/",
        _scheme_replacement,
        value,
    )
    value = re.sub(r"(?i)\bhxxps?\s*:\s*/\s*/", _scheme_replacement, value)
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
    return _unique_strings(candidates)


# =============================================================================
# ENHANCED LINK DETECTION
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

def _extract_entity_urls(message: Any, _depth: int = 0) -> List[str]:
    if message is None or _depth > 4:
        return []
    urls: List[str] = []
    try:
        text = getattr(message, "text", None) or ""
        entities = getattr(message, "entities", None) or []
        for entity in entities:
            try:
                entity_type = str(getattr(entity, "type", "") or "").lower()
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
                entity_type = str(getattr(entity, "type", "") or "").lower()
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


# ═══════════════════════════════════════════════════════════════════
# 🆕 v3.0.1 FIX-1: زر شامل — يدعم كل الأنواع
# ═══════════════════════════════════════════════════════════════════

def _extract_url_from_button(button: Any) -> Optional[str]:
    """
    v3.0.1: يدعم كل أنواع أزرار PTB التي قد تحتوي على رابط:
      - url           (InlineKeyboardButton الأساسي)
      - web_app       (WebAppInfo.url)
      - login_url     (LoginUrl.url)
      - copy_text     (v20.8+ — الزر ينسخ نصاً)
      - switch_inline_query
      - callback_data (نادراً ما يخفي رابطاً)
    """
    if button is None:
        return None
    try:
        # 1) url مباشر (الأكثر شيوعاً)
        url = getattr(button, "url", None)
        if url:
            return str(url)

        # 2) web_app
        web_app = getattr(button, "web_app", None)
        if web_app is not None:
            web_url = getattr(web_app, "url", None)
            if web_url:
                return str(web_url)
            return "web_app://button"

        # 3) login_url
        login_url = getattr(button, "login_url", None)
        if login_url is not None:
            login_web_url = getattr(login_url, "url", None)
            if login_web_url:
                return str(login_web_url)
            return "login_url://button"

        # 4) copy_text (v20.8+)
        copy_text = getattr(button, "copy_text", None)
        if copy_text is not None:
            text = getattr(copy_text, "text", None)
            if text and _URL_IN_TEXT_RE.search(str(text)):
                return str(text)

        # 5) switch_inline_query
        switch_q = getattr(button, "switch_inline_query", None)
        if switch_q and _URL_IN_TEXT_RE.search(str(switch_q)):
            return str(switch_q)

        # 6) callback_data (نادر)
        cb = getattr(button, "callback_data", None)
        if cb and isinstance(cb, str) and _URL_IN_TEXT_RE.search(cb):
            return cb

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
    button_urls: List[str] = []
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
                    button_urls_raw.append(str(url))
                    if not str(url).endswith("://button"):
                        button_urls.append(str(url))
    except Exception:
        pass
    return (
        button_count,
        _unique_strings(button_urls),
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
        "is_forwarded", "is_protected", "has_hint", "is_auto_fwd",
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
        self.has_hint = False
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
            (_ARABIC_SPAM_WORDS | _ARABIC_CTA_WORDS | _EXTRA_SCRIPT_SPAM_WORDS),
            already_normalized=True,
        )
        ctx.generic_word_count = _count_word_matches(
            ctx.normalized_text, _GENERIC_WORDS, already_normalized=True
        )
        ctx.suspicious_separator_count = _count_separators(text)
        ctx.repeated_char_count = len(_REPEATED_CHAR_RE.findall(text))
        ctx.repeated_word_count = len(
            _REPEATED_WORD_RE.findall(ctx.normalized_text)
        )
        ctx.random_domains = _extract_random_domains(text)
        ctx.has_random_domain = bool(ctx.random_domains)
        ctx.has_any_link = _contains_link_enhanced(
            ctx.analysis_text, include_usernames=False
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
            self.suspicious_separator_count = _count_separators(
                self.analysis_text
            )
            self.repeated_char_count = len(
                _REPEATED_CHAR_RE.findall(self.analysis_text)
            )
            self.repeated_word_count = len(
                _REPEATED_WORD_RE.findall(self.normalized_text)
            )
            self.random_domains = _extract_random_domains(
                self.analysis_text
            )
            self.has_random_domain = bool(self.random_domains)

            # ═══════════════════════════════════════════════════════
            # 🆕 v3.0.1 FIX-3: كشف أوسع للأزرار
            # ═══════════════════════════════════════════════════════
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
            self.has_hint = bool(
                self.button_count or self.has_any_link
                or self.has_link_entity
            )
            self.forward_hint = bool(
                getattr(message, "has_protected_content", False)
                and (
                    "محولة من" in self.full_text
                    or "محوّل من" in self.full_text
                    or "Forwarded from" in self.full_text
                )
            )

            # 🆕 v3.0.1 FIX-4: تشخيص فوري للأزرار
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
    found: List[str] = []
    vocabularies = (
        _STRONG_SPAM_WORDS, _MEDIUM_SPAM_WORDS, _CTA_WORDS,
        _PROMO_WORDS, _ARABIC_SPAM_WORDS, _ARABIC_CTA_WORDS,
        _EXTRA_SCRIPT_SPAM_WORDS,
    )
    for vocabulary in vocabularies:
        for word in vocabulary:
            if re.search(
                rf"(?<![\w-]){re.escape(str(word).casefold())}(?![\w-])",
                normalized,
                flags=re.IGNORECASE,
            ):
                found.append(str(word))
    compact = re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)
    compact_candidates = {
        "megapack", "megapacks", "viralcontent", "openhere",
        "viewleak", "checkthis", "clickhere", "watchnow",
        "exclusivecontent",
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
            rf"exclusive|mega|viral|content|pack))"
            rf"{re.escape(target)}"
            rf"(?:$|(?:now|here|content|pack|clips?))",
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
        | {
            "viralcontent", "megapack", "openhere",
            "viewleak", "watchnow", "clickhere", "exclusivecontent",
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
    if ANTIEVASION_RANDOM_DOMAIN and _has_random_domain(normalized):
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
) -> int:
    if not text:
        return 0
    normalized = text if already_normalized else _normalize_text(text)
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
    if ANTIEVASION_RANDOM_DOMAIN and _has_random_domain(normalized):
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


def _looks_like_normal_conversation(text: str) -> bool:
    if not text:
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
    link = _contains_link_enhanced(
        normalized, include_usernames=False, already_normalized=True
    )
    if (
        generic_hits >= 1 and strong_hits == 0
        and promo_hits <= 1 and not link and len(words) <= 12
    ):
        return True
    if (
        len(words) >= 8 and strong_hits == 0
        and promo_hits <= 1 and not link
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

        reasons: List[str] = []
        link_score = 0
        content_score = 0
        cta_score = 0
        evasion_score = 0
        structure_score = 0
        context_score = 0
        independent_categories = set()

        # ---- LINK ----
        link_detected = _contains_link_enhanced(
            normalized, include_usernames=False, already_normalized=True
        )
        text_url_count = ctx.url_count
        url_obfuscated, url_reasons = _detect_url_obfuscation(
            normalized, already_normalized=True
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

        # ---- BUTTON / CTA ----
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

        # ---- VOCABULARY ----
        strong = ctx.strong_word_count
        medium = ctx.medium_word_count
        promo = ctx.promo_word_count
        arabic = ctx.arabic_spam_count
        cta = ctx.cta_count

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

        # ---- PACK / NUMBER ----
        has_number_pack = bool(_NUMBER_PROMO_RE.search(normalized))
        has_pack = bool(_PACK_RE.search(normalized))
        if has_number_pack:
            context_score = _cap_score(context_score, 3, _SCORE_CAP_CONTEXT)
            reasons.append("large_pack_number")
        if has_pack:
            context_score = _cap_score(context_score, 1, _SCORE_CAP_CONTEXT)
            reasons.append("pack_pattern")

        # ---- PROMO CONTEXT ----
        context_hits = _count_unique_matches(
            normalized, _PROMO_CONTEXT_PATTERNS
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

        # ---- POSTBOT ----
        postbot_confidence = _postbot_pattern_confidence(
            normalized,
            button_count=ctx.button_count,
            button_urls=ctx.button_urls,
            already_normalized=True,
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

        # ---- EMOJI ----
        spam_emojis = ctx.spam_emoji_count
        if spam_emojis >= 6:
            cta_score = _cap_score(cta_score, 2, _SCORE_CAP_CTA)
            reasons.append(f"spam_emojis:{spam_emojis}")
        elif spam_emojis >= 3:
            cta_score = _cap_score(cta_score, 1, _SCORE_CAP_CTA)
            reasons.append(f"spam_emojis:{spam_emojis}")

        # ---- SPLIT WORDS ----
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

        # ---- URL EVASION ----
        if url_obfuscated:
            evasion_score = _cap_score(
                evasion_score,
                min(5, 1 + len(url_reasons)),
                _SCORE_CAP_EVASION,
            )
            reasons.extend("url_evasion:" + x for x in url_reasons)

        # ---- UNICODE EVASION ----
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

        # ---- STRUCTURAL EVASION ----
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

        # ---- DENSITY ----
        density_score, density_reasons = _text_density_signals(text)
        if density_score:
            structure_score = _cap_score(
                structure_score, density_score, _SCORE_CAP_STRUCTURE
            )
            reasons.extend("density:" + x for x in density_reasons)

        # ---- CONTACT ----
        contact_score, contact_reasons = _detect_phone_or_contact_evasion(
            normalized, already_normalized=True
        )
        if contact_score:
            context_score = _cap_score(
                context_score, contact_score, _SCORE_CAP_CONTEXT
            )
            reasons.extend("contact:" + x for x in contact_reasons)

        # ---- REPETITION ----
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

        # ---- MEDIA + PROMOTION ----
        has_media = _message_has_media(context_or_message)
        if has_media and (ctx.button_count >= 2 or cta >= 2):
            context_score = _cap_score(
                context_score, 2, _SCORE_CAP_CONTEXT
            )
            reasons.append("media_plus_promotion")

        # ---- POLL / VCARD ----
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

        # ---- FORWARDED ----
        preliminary_score = (
            link_score + content_score + cta_score
            + evasion_score + structure_score + context_score
        )
        if ctx.is_forwarded and preliminary_score >= 5:
            context_score = _cap_score(
                context_score, 1, _SCORE_CAP_CONTEXT
            )
            reasons.append("forwarded_spam_context")

        # ---- HIGH-CONFIDENCE MARKETING ----
        if (
            (promo >= 2 or strong >= 2)
            and cta >= 1
            and (ctx.button_link_urls or text_url_count)
        ):
            context_score = _cap_score(
                context_score, 3, _SCORE_CAP_CONTEXT
            )
            reasons.append("high_confidence_marketing_spam")

        # ---- PACK + NUMBER + EXTERNAL ----
        if (
            has_pack and has_number_pack
            and (ctx.button_link_urls or link_detected)
        ):
            context_score = _cap_score(
                context_score, 4, _SCORE_CAP_CONTEXT
            )
            reasons.append("pack_number_external_cta")

        # ---- CATEGORY STACK ----
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

        # ---- OBFUSCATION + PROMOTION ----
        if url_obfuscated and (strong >= 1 or promo >= 1 or cta >= 1):
            evasion_score = _cap_score(
                evasion_score, 2, _SCORE_CAP_EVASION
            )
            reasons.append("obfuscated_promotion")

        # ---- HIDDEN + LINK/SPAM ----
        if ctx.has_hidden_chars and (
            link_detected or strong >= 1 or promo >= 1
        ):
            evasion_score = _cap_score(
                evasion_score, 2, _SCORE_CAP_EVASION
            )
            reasons.append("hidden_evasion_with_spam")

        # ---- USERNAME + PROMOTION ----
        if (
            _contains_at_channel(normalized, already_normalized=True)
            and (cta >= 1 or promo >= 1 or strong >= 1)
        ):
            cta_score = _cap_score(cta_score, 1, _SCORE_CAP_CTA)
            reasons.append("telegram_username_with_promotion")

        # ---- RANDOM DOMAIN + PROMOTION ----
        if (
            ANTIEVASION_RANDOM_DOMAIN and ctx.has_random_domain
            and (cta >= 1 or promo >= 1 or strong >= 1)
        ):
            context_score = _cap_score(
                context_score, 3, _SCORE_CAP_CONTEXT
            )
            reasons.append("random_domain_with_promotion")

        # ---- INDEPENDENT CATEGORIES ----
        if evasion_score > 0:
            independent_categories.add("evasion")
        if structure_score > 0:
            independent_categories.add("structure")
        if postbot_confidence >= 4 and context_score > 0:
            independent_categories.add("postbot")

        # ---- RAW SCORE ----
        score = (
            link_score + content_score + cta_score
            + evasion_score + structure_score + context_score
        )

        # ---- BONUS ----
        independent_signals = len(independent_categories)
        if independent_signals >= 4 and (
            link_score > 0 or content_score > 0
        ):
            score += 2
            reasons.append("multi_category_evidence")
        elif independent_signals >= 3:
            score += 1
            reasons.append("independent_evidence")

        # ---- GATES ----
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

        # ═══════════════════════════════════════════════════════════
        # 🆕 v3.0.1 FIX-2: لا نُطبّق سقف "الرابط فقط" على الأزرار
        # ═══════════════════════════════════════════════════════════
        #
        # قبل: كان السقف يُطبّق حتى على الرسائل التي تحتوي 3 أزرار
        #       بروابط → score=4 → لا يُحذف.
        #
        # بعد: نستثني الحالة التي تكون الروابط فيها أزراراً
        #      (is_button_only_case) — الأزرار دليل قوي بحد ذاتها.
        #
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
            and not is_button_only_case  # ← الاستثناء الجديد
        ):
            score = min(score, 4)
            reasons.append("link_only_capped")

        # ---- CLAMP ----
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

        # ---- HARD / CRITICAL ----
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
                    # 🆕 v3.0.1: أزرار كثيرة = evidence كافٍ
                    is_button_only_case
                    and external_buttons >= 3
                )
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
        if image.width > OCR_MAX_IMAGE_SIZE[0] or image.height > OCR_MAX_IMAGE_SIZE[1]:
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
    if not _QR_AVAILABLE or not image_bytes:
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


def _download_telegram_file(file_id: str, bot: Any = None) -> Optional[bytes]:
    if bot is None:
        try:
            from telegram_bot_singleton import get_bot  # type: ignore
            bot = get_bot()
        except Exception:
            return None
    if bot is None:
        return None
    try:
        file = bot.get_file(file_id)
        return bytes(file.download_as_bytearray())
    except Exception as exc:
        logger.debug("download error: %r", exc)
        return None


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

        sticker = getattr(message, "sticker", None)
        if sticker:
            emoji = getattr(sticker, "emoji", None)
            if emoji:
                text_parts.append(str(emoji))
    except Exception as exc:
        logger.debug("extract_image_content error: %r", exc)
    return "\n".join(text_parts), qr_parts


# =============================================================================
# LAYER 2: AUDIO STT
# =============================================================================

_whisper_model = None


def _get_whisper_model() -> Any:
    global _whisper_model
    if _whisper_model is None and _WHISPER_AVAILABLE:
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
        wav_buf = io.BytesIO()
        audio.export(wav_buf, format="wav")
        return wav_buf.getvalue()
    except Exception as exc:
        logger.debug("ogg→wav error: %r", exc)
        return None


def _transcribe_with_whisper(wav_bytes: bytes) -> str:
    import tempfile
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
            os.unlink(tmp_path)
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
            response = _requests.head(
                current, allow_redirects=False,
                timeout=URL_EXPAND_TIMEOUT,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    break
                current = location
            else:
                break
    except Exception as exc:
        logger.debug("expand_url error: %r", exc)
    return current


def is_shortener(url: str) -> bool:
    try:
        domain = urlparse(url).netloc.lower()
        domain = re.sub(r"^www\.", "", domain)
        return domain in _SHORTENER_DOMAINS
    except Exception:
        return False


def check_safe_browsing(url: str) -> Dict[str, Any]:
    if not SAFE_BROWSING_API_KEY or not _REQUESTS_AVAILABLE:
        return {"safe": True, "checked": False, "reason": "no_api_key"}
    try:
        payload = {
            "client": {
                "clientId": "relax-manager",
                "clientVersion": _DETECTORS_VERSION,
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
            timeout=URL_EXPAND_TIMEOUT,
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
        import datetime
        if isinstance(creation, str):
            creation = datetime.datetime.fromisoformat(creation)
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
    lower = text.lower()
    return any(sig in lower for sig in _URL_SIGNATURES)


def try_decode_base64(text: str) -> str:
    for pattern in (_BASE64_RE, _BASE64_URLSAFE_RE):
        if not pattern.match(text):
            continue
        try:
            if "-" in text or "_" in text:
                decoded = base64.urlsafe_b64decode(text + "==")
            else:
                decoded = base64.b64decode(text + "==")
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

_user_message_times: Dict[int, deque] = defaultdict(
    lambda: deque(maxlen=20)
)
_user_short_messages: Dict[int, deque] = defaultdict(
    lambda: deque(maxlen=20)
)
_user_url_count: Dict[int, deque] = defaultdict(
    lambda: deque(maxlen=10)
)

_edited_messages: Dict[Tuple[int, int], Dict[str, Any]] = {}

_last_cleanup = 0.0
CLEANUP_INTERVAL = 300


def record_message(user_id: int, text: str, has_url: bool = False) -> None:
    now = time.time()
    _user_message_times[user_id].append(now)
    if len(text) < 20:
        _user_short_messages[user_id].append((now, text))
    if has_url:
        _user_url_count[user_id].append(now)


def check_rate_limit(user_id: int) -> Tuple[bool, Optional[str]]:
    now = time.time()
    cutoff = now - RATE_WINDOW_SECONDS
    times = _user_message_times[user_id]
    recent = [t for t in times if t > cutoff]
    if len(recent) > RATE_MAX_MESSAGES:
        return True, f"rate_limit:{len(recent)}/min"
    url_times = _user_url_count[user_id]
    recent_urls = [t for t in url_times if t > cutoff]
    if len(recent_urls) > RATE_MAX_URLS:
        return True, f"url_flood:{len(recent_urls)}/min"
    return False, None


def check_split_url_pattern(
    user_id: int, current_text: str
) -> Tuple[bool, Optional[str]]:
    now = time.time()
    cutoff = now - CROSS_MSG_WINDOW
    recent = _user_short_messages[user_id]
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
    key = (chat_id, message_id)
    now = time.time()
    if key in _edited_messages:
        prev = _edited_messages[key]
        prev_text = prev.get("text", "")
        if len(prev_text) < 30 and len(new_text) > len(prev_text) * 3:
            return True, "suspicious_edit"
    _edited_messages[key] = {
        "user_id": user_id, "text": new_text, "time": now,
    }
    return False, None


def cleanup_old_data() -> None:
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    cutoff = now - 600
    for uid in list(_user_message_times.keys()):
        _user_message_times[uid] = deque(
            (t for t in _user_message_times[uid] if t > cutoff),
            maxlen=20,
        )
    for key in list(_edited_messages.keys()):
        if _edited_messages[key]["time"] < cutoff:
            del _edited_messages[key]


# =============================================================================
# ORCHESTRATOR (v3.0.1)
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


def _run_text_layer(message: Any, verdict: SpamVerdict) -> Dict[str, Any]:
    if not TEXT_LAYER_ENABLED:
        return {}
    try:
        text_result = analyze_message(message)
        verdict.layer_scores["text"] = text_result.get("score", 0)
        verdict.layer_reasons["text"] = text_result.get("reasons", [])
        return text_result
    except Exception as exc:
        logger.debug("L0 error: %r", exc)
        return {}


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
        all_urls = (
            text_result.get("entity_urls", [])
            + text_result.get("button_urls", [])
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
        cleanup_old_data()
    except Exception as exc:
        logger.debug("L6 error: %r", exc)


def _aggregate_verdict(verdict: SpamVerdict) -> None:
    total = 0.0
    for layer, score in verdict.layer_scores.items():
        weight = LAYER_WEIGHTS.get(layer, 1.0)
        total += score * weight
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
    _aggregate_verdict(verdict)

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


# =============================================================================
# HIGH LEVEL API
# =============================================================================

def analyze_message(message: Any) -> Dict[str, Any]:
    ctx = _MessageContext(message)
    result = _compute_spam_score(ctx, return_diagnostics=True)
    result.update({
        "has_link": ctx.has_any_link,
        "has_button_link": ctx.has_button_link,
        "button_count": ctx.button_count,
        "button_urls": list(ctx.button_urls),
        "entity_urls": list(ctx.entity_urls),
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
        "random_domains": list(ctx.random_domains),
        "has_random_domain": ctx.has_random_domain,
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
            "detector_version": _DETECTORS_VERSION,
            "text": ctx.full_text,
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
        }
    except Exception as exc:
        return {
            "score": 0, "reasons": ["diagnostic_error"],
            "confidence": "none", "hard": False, "critical": False,
            "error": repr(exc), "detector_version": _DETECTORS_VERSION,
        }


# =============================================================================
# COMPATIBILITY EXPORTS
# =============================================================================

__all__ = [
    "DEBUG_DIAG", "DEBUG_SPAM",
    "TEXT_LAYER_ENABLED", "OCR_LAYER_ENABLED", "AUDIO_LAYER_ENABLED",
    "URL_LAYER_ENABLED", "METADATA_LAYER_ENABLED",
    "OBFUSCATION_LAYER_ENABLED", "BEHAVIORAL_LAYER_ENABLED",
    "SAFE_BROWSING_API_KEY", "URL_ENRICH_ENABLED",
    "AUDIO_USE_WHISPER",

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

    "SPAM_SCORE_THRESHOLD", "POSTBOT_AUTO_BLOCK_CONFIDENCE",
    "SPAM_HARD_THRESHOLD", "SPAM_CRITICAL_THRESHOLD",
    "RANDOM_DOMAIN_MIN_LENGTH", "RANDOM_DOMAIN_MAX_VOWEL_RATIO",
    "FINAL_THRESHOLD", "LAYER_WEIGHTS",

    "SpamVerdict",
    "_MessageContext",

    "_strip_combining_marks", "_deleet", "_apply_homoglyphs_safe",
    "_normalize_text", "_strip_emoji_for_domain",
    "_has_hidden_chars", "_merge_split_urls",

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
    "_extract_random_domains", "_shannon_entropy",

    "extract_text_from_image", "extract_qr_codes",
    "extract_image_content",

    "transcribe_audio", "extract_audio_content",

    "expand_url", "is_shortener", "check_safe_browsing",
    "get_domain_age_days", "analyze_url", "analyze_urls",

    "extract_metadata_text", "metadata_has_suspicious_content",
    "extract_metadata_urls",

    "try_decode_base64", "try_decode_rot13", "try_decode_hex",
    "try_decode_url", "try_decode_reverse",
    "find_obfuscated_payloads", "has_any_obfuscation",

    "record_message", "check_rate_limit",
    "check_split_url_pattern", "track_edit", "cleanup_old_data",

    "analyze_message_full",
    "analyze_message",
    "get_spam_diagnostics",
    "is_spam",
    "is_high_confidence_spam",
    "is_critical_spam",
    "should_ignore_as_low_signal",
]


# =============================================================================
# LOAD BEACON
# =============================================================================

try:
    logger.info(
        "🛡️ handlers_message_detectors %s loaded | "
        "Text=%s OCR=%s(%s) Audio=%s(%s) URL=%s(%s) "
        "Meta=%s Obf=%s Behav=%s | "
        "SPAM_THRESHOLD=%d HARD=%d CRITICAL=%d | "
        "TLDs=%d RANDOM_DOMAIN=%s",
        _DETECTORS_VERSION,
        TEXT_LAYER_ENABLED,
        OCR_LAYER_ENABLED, _OCR_AVAILABLE,
        AUDIO_LAYER_ENABLED, _AUDIO_AVAILABLE,
        URL_LAYER_ENABLED, bool(SAFE_BROWSING_API_KEY),
        METADATA_LAYER_ENABLED,
        OBFUSCATION_LAYER_ENABLED,
        BEHAVIORAL_LAYER_ENABLED,
        SPAM_SCORE_THRESHOLD,
        SPAM_HARD_THRESHOLD,
        SPAM_CRITICAL_THRESHOLD,
        len(_COMMON_TLDS),
        ANTIEVASION_RANDOM_DOMAIN,
    )
except Exception:
    pass