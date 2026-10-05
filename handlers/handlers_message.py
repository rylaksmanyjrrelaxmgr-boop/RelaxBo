#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_message.py - v7.14.0 (ZERO-EVASION HARDENED)
=============================================================================
🆕 v7.14.0 — إغلاق 17 ثغرة تجاوز مُكتشفة في v7.13.0:

    🔴 CRITICAL:
        #1  web_app / login_url داخل الأزرار — كان لا يُفحص.
        #2  @username / tg:// / البريد الإلكتروني — كان لا يُفحص.
        #3  TLDs ناقصة (.ly, .at, .gg, .gy, cutt.ly, ...).
        #4  روابط مقسّمة على أسطر (https://evil.\ncom/x).
        #5  فشل الحذف الصامت — لا يُنبَّه المالك عند فقدان الصلاحيات.

    🟠 HIGH:
        #6  Leetspeak (p0rn, v1ral, n00ds).
        #7  Hidden chars ناقصة (U+2066-2069, U+3164, U+2800, ...).
        #8  Homoglyphs سيريلية/يونانية ناقصة.
        #9  reply_to_message.entities غير مفحوصة (G10 وهمي سابقاً).
        #10 FP في schemeless — تم اشتراط سياق (path/فاصلة).
        #11 Punycode/IDN (xn--*).
        #12 IPv4 scheme-less (1.2.3.4/admin).
        #13 vCard يحتوي URL.
        #14 Venue يحتوي URL.
        #16 ReDoS في _get_spaced_banned_pattern.
        #17 منطق _extract_spam_words معطوب (helloworld bug).

    ✅ الحفاظ الكامل على وظائف v7.13.0.

🆕 Feature Flags (كل التحسينات مُفعَّلة افتراضياً):
    ANTIEVASION_ENTITY_LINK       = True
    ANTIEVASION_BUTTON_LINK       = True
    ANTIEVASION_BUTTON_WEBAPP     = True   # جديد #1
    ANTIEVASION_BUTTON_LOGINURL   = True   # جديد #1
    ANTIEVASION_SCHEMELESS_URL    = True
    ANTIEVASION_HOMOGLYPH         = True
    ANTIEVASION_COMBINING         = True
    ANTIEVASION_COMPACT_WORDS     = True
    ANTIEVASION_EMOJI_SEPARATOR   = True
    ANTIEVASION_LEETSPEAK         = True   # جديد #6
    ANTIEVASION_TG_SCHEME         = True   # جديد #2
    ANTIEVASION_AT_CHANNEL        = True   # جديد #2 (قد يُنتج FP)
    ANTIEVASION_EMAIL             = True   # جديد #2
    ANTIEVASION_PUNYCODE          = True   # جديد #11
    ANTIEVASION_IPV4_SCHEMELESS   = True   # جديد #12
    ANTIEVASION_MULTILINE_URL     = True   # جديد #4
    ANTIEVASION_VENUE_VCARD       = True   # جديد #13/#14
=============================================================================
"""

import asyncio
import logging
import time
import os
import re
import inspect
import ipaddress
import unicodedata
from html import escape
from functools import partial
from typing import Optional, Dict, Any, List, Tuple, Callable, Awaitable
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


try:
    from replies import analyze_sentiment  # noqa: F401
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
# Environment Flags
# ═══════════════════════════════════════════════════════════════════

def _env_flag(name: str, default: bool = True) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


_DEBUG_DIAG = _env_flag("DEBUG_DIAG", False)
_DEBUG_SPAM = _env_flag("DEBUG_SPAM", False)

# v7.13.0 flags
_ANTIEVASION_ENTITY_LINK = _env_flag("ANTIEVASION_ENTITY_LINK", True)
_ANTIEVASION_BUTTON_LINK = _env_flag("ANTIEVASION_BUTTON_LINK", True)
_ANTIEVASION_SCHEMELESS_URL = _env_flag("ANTIEVASION_SCHEMELESS_URL", True)
_ANTIEVASION_HOMOGLYPH = _env_flag("ANTIEVASION_HOMOGLYPH", True)
_ANTIEVASION_COMBINING = _env_flag("ANTIEVASION_COMBINING", True)
_ANTIEVASION_COMPACT_WORDS = _env_flag("ANTIEVASION_COMPACT_WORDS", True)
_ANTIEVASION_EMOJI_SEPARATOR = _env_flag("ANTIEVASION_EMOJI_SEPARATOR", True)

# v7.14.0 NEW flags
_ANTIEVASION_BUTTON_WEBAPP = _env_flag("ANTIEVASION_BUTTON_WEBAPP", True)
_ANTIEVASION_BUTTON_LOGINURL = _env_flag("ANTIEVASION_BUTTON_LOGINURL", True)
_ANTIEVASION_LEETSPEAK = _env_flag("ANTIEVASION_LEETSPEAK", True)
_ANTIEVASION_TG_SCHEME = _env_flag("ANTIEVASION_TG_SCHEME", True)
_ANTIEVASION_AT_CHANNEL = _env_flag("ANTIEVASION_AT_CHANNEL", True)
_ANTIEVASION_EMAIL = _env_flag("ANTIEVASION_EMAIL", True)
_ANTIEVASION_PUNYCODE = _env_flag("ANTIEVASION_PUNYCODE", True)
_ANTIEVASION_IPV4_SCHEMELESS = _env_flag("ANTIEVASION_IPV4_SCHEMELESS", True)
_ANTIEVASION_MULTILINE_URL = _env_flag("ANTIEVASION_MULTILINE_URL", True)
_ANTIEVASION_VENUE_VCARD = _env_flag("ANTIEVASION_VENUE_VCARD", True)


# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

SPAM_SCORE_THRESHOLD = 5

LOG_RATE_LIMIT_PER_MIN = 30
LOG_RATE_WINDOW_SEC = 60.0
LOG_RETRY_ATTEMPTS = 3
LOG_RETRY_BASE_DELAY = 0.5

DEV_LOG_CACHE_TTL = 300.0

CACHE_CLEANUP_INTERVAL = 3600
SEC_AUTH_CACHE_TTL = 300
MAX_SEC_AUTH_CACHE_SIZE = 5000
MAX_GROUP_LIMITERS_CACHE = 1000
MAX_COMPILED_BANNED_PATTERNS = 5000

TRANSLATION_REPLY_DELETE_DELAY = 30
TRANSLATION_MIN_TEXT_LENGTH = 2
PENALTY_MESSAGE_DELETE_DELAY = 10

_FORWARD_NOTIFY_COOLDOWN_SECONDS = 300.0
_FORWARD_NOTIFY_MAX_KEYS = 5000
_GROUP_LOG_PREVIEW_LENGTH = 150

_COLUMNS_RETRY_COOLDOWN_SEC = 300.0


FEATURE_LOG_DELETIONS = _env_flag("LOG_DELETIONS", True)
FEATURE_LOG_PENALTIES = _env_flag("LOG_PENALTIES", True)
FEATURE_LOG_GIFTS = _env_flag("LOG_GIFTS", True)
FEATURE_LOG_ADMIN_CHANGES = _env_flag("LOG_ADMIN_CHANGES", True)


# ═══════════════════════════════════════════════════════════════════
# _MessageContext
# ═══════════════════════════════════════════════════════════════════

class _MessageContext:
    """يجمع كل بيانات الرسالة في كائن واحد لتفادي الاستخراج المتكرر."""
    __slots__ = (
        'text', 'caption', 'full_text', 'normalized_text',
        'analysis_text',
        'button_count', 'button_urls', 'button_texts', 'button_urls_raw',
        'is_forwarded', 'is_protected', 'has_hint', 'is_auto_fwd',
        'entity_urls', 'has_link_entity', 'button_link_urls',
        'has_any_link', 'has_button_link',
        # v7.14.0 new
        'vcard_urls', 'venue_url', 'has_hidden_chars',
    )

    def __init__(self):
        self.text = ""
        self.caption = ""
        self.full_text = ""
        self.normalized_text = ""
        self.analysis_text = ""
        self.button_count = 0
        self.button_urls: List[str] = []
        self.button_urls_raw: List[str] = []
        self.button_texts: List[str] = []
        self.is_forwarded = False
        self.is_protected = False
        self.has_hint = False
        self.is_auto_fwd = False
        self.entity_urls: List[str] = []
        self.has_link_entity = False
        self.button_link_urls: List[str] = []
        self.has_any_link = False
        self.has_button_link = False
        # v7.14.0
        self.vcard_urls: List[str] = []
        self.venue_url: str = ""
        self.has_hidden_chars = False


# ═══════════════════════════════════════════════════════════════════
# Unicode Normalization — v7.14.0 (Hidden + Homoglyph + Leet + Combining)
# ═══════════════════════════════════════════════════════════════════

# v7.14.0 #7: قائمة موسّعة للمحارف المخفية
_HIDDEN_CHARS = (
    '\u200b', '\u200c', '\u200d', '\u200e', '\u200f',
    '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
    '\u2060', '\u2061', '\u2062', '\u2063', '\u2064',
    '\u2066', '\u2067', '\u2068', '\u2069',   # LRI/RLI/FSI/PDI
    '\u180e',                                  # Mongolian Vowel Sep
    '\u3164',                                  # Hangul Filler
    '\u2800',                                  # Braille Blank
    '\u115f', '\u1160',                        # Hangul Fillers
    '\u00ad',                                  # Soft Hyphen
    '\u034f',                                  # Combining Grapheme Joiner
    '\ufeff',
)

_HIDDEN_TRANSLATE_TABLE = {ord(c): None for c in _HIDDEN_CHARS}

_WS_RE = re.compile(
    r'[\s\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+'
)

# v7.14.0 #8: Homoglyphs موسّعة (Cyrillic + Greek → Latin)
_HOMOGLYPH_MAP = str.maketrans({
    # ─── Cyrillic → Latin (lowercase) ───
    '\u0430': 'a',   # а
    '\u0431': 'b',   # б
    '\u0432': 'b',   # в
    '\u0433': 'r',   # г  (بصرياً)
    '\u0434': 'a',   # д  (في بعض الخطوط)
    '\u0435': 'e',   # е
    '\u0436': 'x',   # ж
    '\u0437': '3',   # з
    '\u0438': 'u',   # и
    '\u0439': 'u',   # й
    '\u043A': 'k',   # к
    '\u043B': 'n',   # л
    '\u043C': 'm',   # м
    '\u043D': 'h',   # н
    '\u043E': 'o',   # о
    '\u043F': 'n',   # п
    '\u0440': 'p',   # р
    '\u0441': 'c',   # с
    '\u0442': 't',   # т
    '\u0443': 'y',   # у
    '\u0444': 'f',   # ф
    '\u0445': 'x',   # х
    '\u0446': 'u',   # ц
    '\u0447': 'y',   # ч
    '\u0448': 'w',   # ш
    '\u0449': 'w',   # щ
    '\u044A': 'b',   # ъ
    '\u044B': 'b',   # ы
    '\u044C': 'b',   # ь
    '\u044D': 'e',   # э
    '\u044E': 'o',   # ю
    '\u044F': 'r',   # я
    '\u0456': 'i',   # і (Ukrainian i)
    '\u0455': 's',   # ѕ
    '\u0458': 'j',   # ј
    '\u0457': 'i',   # ї
    '\u0451': 'e',   # ё

    # ─── Cyrillic → Latin (uppercase) ───
    '\u0410': 'A',   # А
    '\u0411': 'B',   # Б
    '\u0412': 'B',   # В
    '\u0413': 'R',   # Г
    '\u0414': 'A',   # Д
    '\u0415': 'E',   # Е
    '\u0416': 'X',   # Ж
    '\u0417': '3',   # З
    '\u0418': 'U',   # И
    '\u0419': 'U',   # Й
    '\u041A': 'K',   # К
    '\u041B': 'N',   # Л
    '\u041C': 'M',   # М
    '\u041D': 'H',   # Н
    '\u041E': 'O',   # О
    '\u041F': 'N',   # П
    '\u0420': 'P',   # Р
    '\u0421': 'C',   # С
    '\u0422': 'T',   # Т
    '\u0423': 'Y',   # У
    '\u0424': 'F',   # Ф
    '\u0425': 'X',   # Х
    '\u0426': 'U',   # Ц
    '\u0427': 'Y',   # Ч
    '\u0428': 'W',   # Ш
    '\u0429': 'W',   # Щ
    '\u042A': 'B',   # Ъ
    '\u042B': 'B',   # Ы
    '\u042C': 'B',   # Ь
    '\u042D': 'E',   # Э
    '\u042E': 'O',   # Ю
    '\u042F': 'R',   # Я
    '\u0406': 'I',   # І
    '\u0407': 'I',   # Ї
    '\u0405': 'S',   # Ѕ
    '\u0408': 'J',   # Ј
    '\u0401': 'E',   # Ё

    # ─── Greek → Latin (lowercase) ───
    '\u03B1': 'a',   # α
    '\u03B2': 'b',   # β
    '\u03B3': 'y',   # γ
    '\u03B4': 'd',   # δ
    '\u03B5': 'e',   # ε
    '\u03B6': 'z',   # ζ
    '\u03B7': 'n',   # η
    '\u03B8': 'o',   # θ
    '\u03B9': 'i',   # ι
    '\u03BA': 'k',   # κ
    '\u03BB': 'l',   # λ
    '\u03BC': 'u',   # μ
    '\u03BD': 'v',   # ν
    '\u03BE': 'e',   # ξ
    '\u03BF': 'o',   # ο
    '\u03C0': 'n',   # π
    '\u03C1': 'p',   # ρ
    '\u03C2': 's',   # ς
    '\u03C3': 'o',   # σ
    '\u03C4': 't',   # τ
    '\u03C5': 'u',   # υ
    '\u03C6': 'f',   # φ
    '\u03C7': 'x',   # χ
    '\u03C8': 'y',   # ψ
    '\u03C9': 'w',   # ω

    # ─── Greek → Latin (uppercase) ───
    '\u0391': 'A',   # Α
    '\u0392': 'B',   # Β
    '\u0393': 'Y',   # Γ
    '\u0394': 'A',   # Δ
    '\u0395': 'E',   # Ε
    '\u0396': 'Z',   # Ζ
    '\u0397': 'H',   # Η
    '\u0398': 'O',   # Θ
    '\u0399': 'I',   # Ι
    '\u039A': 'K',   # Κ
    '\u039B': 'L',   # Λ
    '\u039C': 'M',   # Μ
    '\u039D': 'N',   # Ν
    '\u039E': 'E',   # Ξ
    '\u039F': 'O',   # Ο
    '\u03A0': 'N',   # Π
    '\u03A1': 'P',   # Ρ
    '\u03A3': 'S',   # Σ
    '\u03A4': 'T',   # Τ
    '\u03A5': 'Y',   # Υ
    '\u03A6': 'F',   # Φ
    '\u03A7': 'X',   # Χ
    '\u03A8': 'Y',   # Ψ
    '\u03A9': 'W',   # Ω
})

# v7.14.0 #6: Leetspeak — تُطبَّق فقط على "كلمات تحتوي حروفاً+أرقام"
_LEET_TRANSLATE = str.maketrans({
    '0': 'o',
    '1': 'i',
    '3': 'e',
    '4': 'a',
    '5': 's',
    '7': 't',
    '8': 'b',
    '9': 'g',
    '@': 'a',
    '$': 's',
    '!': 'i',
})

# كلمة تحتوي حرفاً وأرقاماً/رموزاً (وليس رقماً صرفاً)
_LEET_CANDIDATE_RE = re.compile(
    r'\b(?=[a-z0-9@$!]*[a-z])'
    r'(?=[a-z0-9@$!]*[0-9@$!])'
    r'[a-z0-9@$!]{3,}\b',
    re.IGNORECASE,
)

# v7.14.0 #7: Combining Diacritical Marks (Latin) — فقط هذه الكتلة
_COMBINING_MARKS_RANGE = frozenset(range(0x0300, 0x0370))


def _strip_combining_marks(text: str) -> str:
    """يحذف Combining Marks في كتلة U+0300–U+036F."""
    if not text:
        return text
    return ''.join(
        c for c in text
        if ord(c) not in _COMBINING_MARKS_RANGE
    )


def _deleet(text: str) -> str:
    """
    v7.14.0 #6: يحوّل leetspeak للاتينية.
    مثال: "p0rn v1ral n00ds" → "porn viral noods".
    ✅ آمن للأرقام الصرفة (تواريخ/هواتف) — لا يلمسها.
    """
    if not text:
        return text
    try:
        def _replace(m):
            return m.group(0).lower().translate(_LEET_TRANSLATE)
        return _LEET_CANDIDATE_RE.sub(_replace, text)
    except Exception:
        return text


def _normalize_text(text: str) -> str:
    """
    v7.14.0:
      1) NFKC normalize
      2) إزالة المحارف المخفية (موسّعة)
      3) تحويل Homoglyphs (Cyrillic/Greek → Latin)
      4) إزالة Combining Marks
      5) Leetspeak → Latin
    """
    if not text:
        return ""

    try:
        text = unicodedata.normalize('NFKC', text)
    except Exception:
        pass

    text = text.translate(_HIDDEN_TRANSLATE_TABLE)

    if _ANTIEVASION_HOMOGLYPH:
        try:
            text = text.translate(_HOMOGLYPH_MAP)
        except Exception:
            pass

    if _ANTIEVASION_COMBINING:
        try:
            text = _strip_combining_marks(text)
        except Exception:
            pass

    if _ANTIEVASION_LEETSPEAK:
        try:
            text = _deleet(text)
        except Exception:
            pass

    return _WS_RE.sub(' ', text).strip()


def _has_hidden_chars(text: str) -> bool:
    if not text:
        return False
    try:
        return any(c in text for c in _HIDDEN_CHARS)
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
# Boolean Helper
# ═══════════════════════════════════════════════════════════════════

_TRUE_STRINGS = frozenset({
    "1", "true", "yes", "on",
    "enabled", "enable", "y",
    "نعم", "مفعل", "مفعّل",
})

_FALSE_STRINGS = frozenset({
    "0", "false", "no", "off",
    "disabled", "disable", "n",
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


# ═══════════════════════════════════════════════════════════════════
# Link detection — v7.14.0 (ALL GAPS CLOSED)
# ═══════════════════════════════════════════════════════════════════

_URL_RE = re.compile(r'https?://[^\s<>"]+', re.IGNORECASE)
_DOMAIN_HTTP_RE = re.compile(
    r'(?:https?://|www\.|t\.me/|telegram\.me/)\S+',
    re.IGNORECASE,
)

# v7.14.0 #2: Telegram scheme
_TG_SCHEME_RE = re.compile(
    r'\btg://\S+',
    re.IGNORECASE,
)

# v7.14.0 #2: @channel mention (يحتاج سياق — ليس @user)
_AT_CHANNEL_RE = re.compile(
    r'(?<![\w@/])@([A-Za-z][A-Za-z0-9_]{3,31})(?![\w@])',
)

# v7.14.0 #2: Email
_EMAIL_RE = re.compile(
    r'(?<![\w.\-])'
    r'[\w.\-+]{1,64}@'
    r'(?:[a-z0-9\-]{1,63}\.)+'
    r'[a-z]{2,24}'
    r'(?![\w\-])',
    re.IGNORECASE,
)

# v7.14.0 #11: Punycode
_PUNYCODE_RE = re.compile(
    r'(?<![\w\-])'
    r'xn--[a-z0-9\-]{2,}(?:\.[a-z0-9\-]+)*',
    re.IGNORECASE,
)

# v7.14.0 #12: IPv4 scheme-less
_IPV4_SCHEMELESS_RE = re.compile(
    r'(?<![\w.\-])'
    r'(?:\d{1,3}\.){3}\d{1,3}'
    r'(?::\d{1,5})?'
    r'(?:/[^\s<>"\']*)?',
)

# v7.14.0 #3: امتدادات ملفات شائعة (لتقليل FP)
_COMMON_FILE_EXTS = frozenset({
    'txt', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz',
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg', 'webp', 'ico',
    'mp3', 'mp4', 'wav', 'ogg', 'flac', 'avi', 'mkv', 'mov', 'webm',
    'py', 'js', 'ts', 'java', 'cpp', 'c', 'h', 'rb', 'go', 'rs', 'php',
    'html', 'css', 'scss', 'json', 'xml', 'yaml', 'yml', 'toml', 'ini', 'cfg',
    'md', 'rst', 'csv', 'tsv', 'log', 'bat', 'ps1',
    'exe', 'dll', 'so', 'dylib', 'apk', 'ipa', 'deb', 'rpm',
})

# v7.14.0 #3: قائمة موسّعة جداً للـTLDs
_TLD_PATTERN = (
    # Generic / sponsored
    r'com|net|org|edu|gov|mil|int|info|biz|name|mobi|asia|xxx|tel|'
    r'travel|jobs|cat|coop|aero|pro|museum|'
    # Tech / popular
    r'io|ai|co|me|tv|cc|app|dev|xyz|top|site|website|space|store|club|'
    r'live|life|world|online|shop|blog|wiki|win|cloud|host|tech|fun|'
    r'link|click|work|today|news|media|agency|company|solutions|'
    # URL shorteners
    r'ly|at|gg|gy|sh|to|so|pw|su|gd|vc|ws|tk|ml|ga|cf|gq|fyi|zip|mov|'
    r're|yt|be|gd|nu|im|st|am|is|it|me|'
    # Crypto / new
    r'crypto|nft|dao|eth|blockchain|exchange|finance|money|'
    # Country codes (extensive)
    r'ru|uk|de|fr|it|es|nl|pl|tr|jp|cn|in|br|mx|ar|ir|sa|ae|eg|ma|dz|'
    r'pk|bd|id|th|vn|ph|my|sg|hk|kr|tw|'
    r'us|ca|au|nz|za|ng|ke|gh|tz|ug|zw|zm|'
    r'be|ch|se|no|dk|fi|is|ie|pt|gr|cz|sk|hu|ro|bg|hr|si|rs|ua|by|'
    r'lt|lv|ee|md|al|mk|ba|'
    r'il|jo|lb|sy|iq|kw|qa|bh|om|ye|sd|tn|'
    r'mr|ne|td|cm|ci|sn|bf|bj|tg|gn|sl|lr|gm|gw|cv|st'
)

# v7.14.0 #3 + #10: schemeless مع اشتراط سياق (path أو فاصلة)
_SCHEMELESS_DOMAIN_RE = re.compile(
    r'(?<![\w@/])'
    r'(?:'
    r'[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?'
    r'\.'
    r'(?:' + _TLD_PATTERN + r')'
    r'(?::\d{1,5})?'
    r'(?:/[^\s<>"\']+|(?=\s|$|[,،.!?;:\)\]]))'
    r')',
    re.IGNORECASE,
)

# v7.14.0 #4: روابط مقسّمة على أسطر
_SPLIT_URL_RE = re.compile(
    r'(https?://[^\s]+?)\s*\n\s*([a-z0-9\.\-/][^\s]*)',
    re.IGNORECASE,
)


def _merge_split_urls(text: str) -> str:
    """v7.14.0 #4: يدمج روابط مقطوعة على أسطر."""
    if not text or not _ANTIEVASION_MULTILINE_URL:
        return text
    if '\n' not in text:
        return text
    try:
        # كرر مرتين لالتقاط حالات متعددة
        for _ in range(2):
            new_text = _SPLIT_URL_RE.sub(r'\1\2', text)
            if new_text == text:
                break
            text = new_text
    except Exception:
        pass
    return text


# ─── Entity types ───
_ENTITY_LINK_TYPES = frozenset({'url', 'text_link'})
_ENTITY_URL_TYPES = frozenset({'url', 'text_link'})


def _extract_entity_urls(message, depth: int = 0) -> List[str]:
    """
    v7.14.0:
      - يفحص message.entities + caption_entities
      - ✅ #9: يعبر reply_to_message حتى عمق 2
    """
    urls: List[str] = []
    if message is None or depth > 2:
        return urls

    try:
        for attr in ('entities', 'caption_entities'):
            ents = getattr(message, attr, None) or []
            for e in ents:
                try:
                    et = getattr(e, 'type', None)
                    if et not in _ENTITY_LINK_TYPES:
                        continue
                    u = getattr(e, 'url', None)
                    if isinstance(u, str) and u:
                        urls.append(u)
                except Exception:
                    continue
    except Exception:
        pass

    # v7.14.0 #9
    if depth < 2:
        try:
            rtm = getattr(message, 'reply_to_message', None)
            if rtm is not None:
                urls.extend(_extract_entity_urls(rtm, depth + 1))
        except Exception:
            pass

    return urls


def _has_link_entity(message) -> bool:
    if not _ANTIEVASION_ENTITY_LINK:
        return False
    if message is None:
        return False
    try:
        for attr in ('entities', 'caption_entities'):
            ents = getattr(message, attr, None) or []
            for e in ents:
                try:
                    if getattr(e, 'type', None) in _ENTITY_URL_TYPES:
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


# v7.14.0 #1: استخراج شامل من زر واحد
def _extract_url_from_button(button) -> List[str]:
    """v7.14.0 #1: url + web_app.url + login_url.url + callback_game."""
    urls: List[str] = []
    if button is None:
        return urls

    try:
        u = getattr(button, 'url', None)
        if isinstance(u, str) and u:
            urls.append(u)
    except Exception:
        pass

    if _ANTIEVASION_BUTTON_WEBAPP:
        try:
            wa = getattr(button, 'web_app', None)
            if wa is not None:
                wau = getattr(wa, 'url', None)
                if isinstance(wau, str) and wau:
                    urls.append(wau)
        except Exception:
            pass

    if _ANTIEVASION_BUTTON_LOGINURL:
        try:
            lu = getattr(button, 'login_url', None)
            if lu is not None:
                luu = getattr(lu, 'url', None)
                if isinstance(luu, str) and luu:
                    urls.append(luu)
        except Exception:
            pass

    return urls


def _extract_button_context(message) -> Tuple[int, List[str], List[str]]:
    """v7.14.0: يعيد (count, urls, texts) — يشمل web_app/login_url."""
    if message is None:
        return 0, [], []

    count = 0
    urls: List[str] = []
    texts: List[str] = []

    try:
        markup = getattr(message, 'reply_markup', None)
        if not markup:
            return 0, [], []

        keyboard = getattr(markup, 'inline_keyboard', None)
        if not keyboard:
            return 0, [], []

        for row in keyboard:
            if not row:
                continue
            for button in row:
                if button is None:
                    continue

                count += 1

                try:
                    b_text = getattr(button, 'text', None)
                    if isinstance(b_text, str):
                        b_text = b_text.strip()
                        if b_text:
                            texts.append(b_text)
                except Exception:
                    pass

                # v7.14.0 #1
                try:
                    urls.extend(_extract_url_from_button(button))
                except Exception:
                    pass

    except Exception:
        pass

    return count, urls, texts


# v7.14.0 #13/#14: استخراج من vCard + Venue
def _extract_vcard_urls(message) -> List[str]:
    if not _ANTIEVASION_VENUE_VCARD:
        return []
    urls: List[str] = []
    try:
        contact = getattr(message, 'contact', None)
        if contact is None:
            return urls
        vcard = getattr(contact, 'vcard', None)
        if not vcard or not isinstance(vcard, str):
            return urls
        for match in re.findall(
            r'(?:URL|url)[:;]([^\r\n;]+)', vcard, re.IGNORECASE
        ):
            u = match.strip()
            if u:
                urls.append(u)
    except Exception:
        pass
    return urls


def _extract_venue_url(message) -> str:
    if not _ANTIEVASION_VENUE_VCARD:
        return ""
    try:
        venue = getattr(message, 'venue', None)
        if venue is None:
            return ""
        # بعض الإصدارات تحوي venue.url
        u = getattr(venue, 'url', None)
        if isinstance(u, str) and u:
            return u
    except Exception:
        pass
    return ""


def _has_domain_pattern(text: str) -> bool:
    """v7.14.0 #3+#10: كشف schemeless مع تقليل FP."""
    if not text:
        return False
    try:
        for m in _SCHEMELESS_DOMAIN_RE.finditer(text):
            full = m.group(0).lower()
            # لو كانت نهاية الملف (بدون path)، تحقق من الامتداد
            if '/' not in full and ':' not in full:
                ext = full.rsplit('.', 1)[-1].split('?')[0]
                if ext in _COMMON_FILE_EXTS:
                    continue
            return True
    except Exception:
        pass
    return False


def _contains_link_enhanced(text: str) -> bool:
    """
    v7.14.0: كشف شامل للروابط:
      - http(s)://
      - www.
      - schemeless domains
      - tg://
      - @channel
      - email
      - punycode
      - IPv4 schemeless
    """
    if not text:
        return False
    try:
        # 1) نمط HTTP الأصلي
        if _DOMAIN_HTTP_RE.search(text):
            return True

        # 2) schemeless domains
        if _ANTIEVASION_SCHEMELESS_URL:
            if _has_domain_pattern(text):
                return True

        # 3) tg:// scheme (#2)
        if _ANTIEVASION_TG_SCHEME:
            if _TG_SCHEME_RE.search(text):
                return True

        # 4) @channel (#2) — قد يُنتج FP
        if _ANTIEVASION_AT_CHANNEL:
            if _AT_CHANNEL_RE.search(text):
                return True

        # 5) Email (#2)
        if _ANTIEVASION_EMAIL:
            if _EMAIL_RE.search(text):
                return True

        # 6) Punycode (#11)
        if _ANTIEVASION_PUNYCODE:
            if _PUNYCODE_RE.search(text):
                return True

        # 7) IPv4 (#12)
        if _ANTIEVASION_IPV4_SCHEMELESS:
            for m in _IPV4_SCHEMELESS_RE.finditer(text):
                try:
                    ip_str = m.group(0).split('/')[0].split(':')[0]
                    ipaddress.ip_address(ip_str)
                    return True
                except Exception:
                    continue

    except Exception:
        pass
    return False


def _has_button_link(ctx: "_MessageContext") -> bool:
    if not _ANTIEVASION_BUTTON_LINK:
        return False
    try:
        for url in ctx.button_urls_raw:
            if not isinstance(url, str) or not url:
                continue
            if _DOMAIN_HTTP_RE.search(url):
                return True
            if _ANTIEVASION_SCHEMELESS_URL and _has_domain_pattern(url):
                return True
            if _ANTIEVASION_TG_SCHEME and _TG_SCHEME_RE.search(url):
                return True
    except Exception:
        pass
    return False


def _extract_button_link_urls(ctx: "_MessageContext") -> List[str]:
    if not _ANTIEVASION_BUTTON_LINK:
        return []
    result: List[str] = []
    try:
        for url in ctx.button_urls_raw:
            if not isinstance(url, str) or not url:
                continue
            if _DOMAIN_HTTP_RE.search(url):
                result.append(url)
            elif _ANTIEVASION_SCHEMELESS_URL and _has_domain_pattern(url):
                result.append(url)
            elif _ANTIEVASION_TG_SCHEME and _TG_SCHEME_RE.search(url):
                result.append(url)
    except Exception:
        pass
    return result


# ═══════════════════════════════════════════════════════════════════
# Spam Detection
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

_EMOJI_SEP_RE = re.compile(
    r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF'
    r'\U0001F000-\U0001F2FF\U000024C2-\U0001F251]',
    re.UNICODE,
)

_WORD_SEP_CLASS = r'[\s\-_.|/*+=~^´`°•●○◦▪▫■□♦♢※]'

_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]*", re.IGNORECASE)
_CAPS_WORD_RE = re.compile(r'\b[A-Z]{4,}\b')


_SPAM_CONTEXT_PATTERNS = (
    (re.compile(
        r'\buncensored\s+(?:best\s+)?'
        r'(?:collection|archive|pack|clips?)\b',
        re.IGNORECASE
    ), 4, "uncensored+collection"),

    (re.compile(
        r'\b(?:xxx|nsfw|porn)\s+'
        r'(?:collection|archive|pack|clips?)\b',
        re.IGNORECASE
    ), 4, "adult+collection"),

    (re.compile(
        r'\b(?:leak|leaked)\s+'
        r'(?:pack|archive|collection|clips?)\b',
        re.IGNORECASE
    ), 4, "leak+pack"),

    (re.compile(
        r'\b(?:click|tap|check|view|open)\s+'
        r'(?:here|now|below)\b',
        re.IGNORECASE
    ), 2, "cta_phrase"),

    (re.compile(
        r'\b(?:best|fresh|hot|wild|viral)\s+'
        r'(?:collection|clips?|pack|archive)\b',
        re.IGNORECASE
    ), 3, "promo_collection"),

    (re.compile(
        r'\b(?:mega|huge|massive)\s+'
        r'(?:pack|archive|collection|drop)\b',
        re.IGNORECASE
    ), 3, "mega_promo"),

    (re.compile(
        r'\b(?:viral|leak|leaked)\b.{0,35}'
        r'\b(?:view|open|click|tap|check)\b',
        re.IGNORECASE
    ), 3, "viral/leak+cta"),
)


_POSTBOT_EMOJI = (
    r'[⭐💀🔥✨🍑🔞🚨💎🎁🎉🌟💥⚡🌸🌺💋👑🥇🏆🎯💯🆕🆗'
    r'🔴🟢🔵🟡🟣🟠💦👉]'
)

_POSTBOT_PATTERN = re.compile(
    _POSTBOT_EMOJI + r'.{0,15}'
    + r'\b[A-Z]{4,}(?:\s+[A-Z]{4,}){1,}' + r'.{0,20}'
    + r'(?:' + _POSTBOT_EMOJI + r'|\d{2,})',
    re.UNICODE
)

_POSTBOT_PATTERN_LOOSE = re.compile(
    _POSTBOT_EMOJI + r'.{0,10}'
    + r'\b[A-Z]{4,}(?:\s+[A-Z]{4,}){1,}',
    re.UNICODE
)

_POSTBOT_BUTTON_PATTERN = re.compile(
    r'\b(?:view|open|watch|click|tap|viral|leak|'
    r'content|download|join|subscribe)\b',
    re.IGNORECASE
)

_POSTBOT_HARD_KEYWORDS = re.compile(
    r'\b(?:viral|leak|mega|pack|clips?|uncensored|nsfw)\b',
    re.IGNORECASE
)


def _extract_spam_words(text: str) -> List[str]:
    """
    v7.14.0 #17: إصلاح منطق compact.
      - نستخرج كلمات من النص الأصلي
      - + نسخة مضغوطة كاملة (v🔥i🔥r🔥a🔥l → viral)
      - + نسخة مضغوطة بمسافات (hello world → hello, world)
    """
    if not text:
        return []

    try:
        regular = [m.group(0).lower() for m in _WORD_RE.finditer(text)]

        if not _ANTIEVASION_EMOJI_SEPARATOR:
            return list(set(regular))

        # 1) إزالة الإيموجي
        no_emoji = _EMOJI_SEP_RE.sub('', text)

        # 2) نسخة مضغوطة بالكامل (بلا أي فاصل)
        fully_compact = re.sub(r'[^a-zA-Z0-9]', '', no_emoji).lower()
        compact_words = re.findall(r'[a-z]{3,}', fully_compact)

        # 3) نسخة مضغوطة بمسافات (لاستخراج كلمات منفصلة)
        spaced_compact = re.sub(_WORD_SEP_CLASS, ' ', no_emoji)
        spaced_compact = re.sub(r'[^a-zA-Z0-9 ]', ' ', spaced_compact)
        spaced_words = [
            w.lower() for w in spaced_compact.split() if len(w) >= 3
        ]

        return list(set(regular + compact_words + spaced_words))
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


# ═══ Backward-compat wrappers ═══

def _get_message_button_data(message):
    count, urls, _ = _extract_button_context(message)
    return count, urls


def _get_message_button_texts(message):
    _, _, texts = _extract_button_context(message)
    return texts


def _get_message_analysis_text(message) -> str:
    if message is None:
        return ""

    parts: List[str] = []

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
        _, _, button_texts = _extract_button_context(message)
        if button_texts:
            parts.extend(button_texts)
    except Exception:
        pass

    try:
        for u in _extract_entity_urls(message):
            parts.append(str(u))
    except Exception:
        pass

    # v7.14.0 #13/#14
    try:
        for u in _extract_vcard_urls(message):
            parts.append(str(u))
    except Exception:
        pass

    try:
        vu = _extract_venue_url(message)
        if vu:
            parts.append(vu)
    except Exception:
        pass

    return _normalize_text(" ".join(parts))


def _compute_spam_score(
    message,
    *,
    _button_count: Optional[int] = None,
    _button_urls: Optional[List[str]] = None,
    _button_texts: Optional[List[str]] = None,
    _normalized: Optional[str] = None,
    _analysis_text: Optional[str] = None,
    _entity_urls: Optional[List[str]] = None,
) -> Tuple[int, List[str]]:
    if message is None:
        return 0, []

    if (
        _button_count is not None
        and _button_urls is not None
        and _button_texts is not None
    ):
        button_count = _button_count
        button_urls = _button_urls
        button_texts = _button_texts
    else:
        button_count, button_urls, button_texts = _extract_button_context(message)

    if _normalized is not None:
        normalized = _normalized
    else:
        try:
            body_text = (
                getattr(message, 'text', None)
                or getattr(message, 'caption', None)
                or ""
            )
        except Exception:
            body_text = ""
        normalized = _normalize_text(body_text) if body_text else ""

    if not normalized and not button_urls and not button_texts:
        return 0, []

    if _analysis_text is not None:
        analysis_text = _analysis_text
    elif button_texts:
        button_text_joined = _normalize_text(" ".join(button_texts))
        analysis_text = (
            f"{normalized} {button_text_joined}".strip()
            if normalized
            else button_text_joined
        )
    else:
        analysis_text = normalized

    if not analysis_text and not button_urls:
        return 0, []

    if _entity_urls is None:
        _entity_urls = _extract_entity_urls(message)

    score = 0
    reasons: List[str] = []
    text_lower = analysis_text.lower()

    try:
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

        emoji_count = 0
        for emoji in _SPAM_EMOJIS:
            emoji_count += analysis_text.count(emoji)

        if emoji_count >= 8:
            score += 3
            reasons.append(f"emoji={emoji_count}")
        elif emoji_count >= 6:
            score += 2
            reasons.append(f"emoji={emoji_count}")
        elif emoji_count >= 3:
            score += 1
            reasons.append(f"emoji={emoji_count}")

        words = _extract_spam_words(analysis_text)

        strong_matches = _count_unique_matches(words, _SPAM_STRONG_KEYWORDS)
        medium_matches = _count_unique_matches(words, _SPAM_MEDIUM_KEYWORDS)
        context_matches = _count_unique_matches(words, _SPAM_CONTEXT_KEYWORDS)
        cta_matches = _count_unique_matches(words, _CTA_KEYWORDS)

        context_only_matches = [
            w for w in context_matches
            if w not in strong_matches and w not in medium_matches
        ]

        if strong_matches:
            score += min(5, len(strong_matches) * 2)
            reasons.append("strong=" + ",".join(strong_matches[:8]))

        if medium_matches:
            score += min(4, len(medium_matches))
            reasons.append("medium=" + ",".join(medium_matches[:8]))

        if context_only_matches and (strong_matches or medium_matches):
            score += min(2, len(context_only_matches))
            reasons.append("context=" + ",".join(context_only_matches[:8]))

        cta_only_matches = [
            w for w in cta_matches
            if w not in strong_matches and w not in medium_matches
        ]

        if cta_only_matches and (strong_matches or medium_matches):
            score += 1
            reasons.append("cta=" + ",".join(cta_only_matches[:6]))

        matched_patterns: List[str] = []
        for pattern, weight, label in _SPAM_CONTEXT_PATTERNS:
            if pattern.search(text_lower):
                score += weight
                matched_patterns.append(label)

        if matched_patterns:
            reasons.append("patterns=" + ",".join(matched_patterns))

        button_cta_matches: List[str] = []
        for bt in button_texts:
            if _POSTBOT_BUTTON_PATTERN.search(bt):
                button_cta_matches.append(_normalize_text(bt))

        if button_cta_matches and (
            strong_matches or medium_matches or matched_patterns
        ):
            score += min(3, len(button_cta_matches))
            reasons.append("button_cta=" + ",".join(button_cta_matches[:4]))

        tme_button_count = 0
        external_button_count = 0

        for url in button_urls:
            try:
                parsed = urlparse(url)
                host = (parsed.hostname or "").lower()
                if host == "t.me" or host.endswith(".t.me"):
                    tme_button_count += 1
                elif host:
                    external_button_count += 1
            except Exception:
                continue

        if tme_button_count >= 4:
            score += 4
            reasons.append(f"tme_buttons={tme_button_count}")
        elif tme_button_count >= 3:
            score += 3
            reasons.append(f"tme_buttons={tme_button_count}")
        elif tme_button_count >= 2:
            score += 2
            reasons.append(f"tme_buttons={tme_button_count}")
        elif tme_button_count >= 1 and (
            strong_matches or medium_matches or matched_patterns
        ):
            score += 1
            reasons.append(f"tme_buttons={tme_button_count}")

        if external_button_count >= 3:
            score += 2
            reasons.append(f"external_buttons={external_button_count}")
        elif external_button_count >= 1 and (
            strong_matches or medium_matches or matched_patterns
            or button_cta_matches
        ):
            score += 1
            reasons.append(f"external_buttons={external_button_count}")

        if _entity_urls:
            entity_count = len(_entity_urls)
            if entity_count >= 3:
                score += 3
                reasons.append(f"entity_urls={entity_count}")
            elif entity_count >= 2:
                score += 2
                reasons.append(f"entity_urls={entity_count}")
            elif entity_count >= 1:
                score += 1
                reasons.append(f"entity_urls={entity_count}")

        text_urls = _count_text_urls(normalized)
        schemeless_hit = False
        if _ANTIEVASION_SCHEMELESS_URL and not text_urls:
            try:
                if _has_domain_pattern(normalized):
                    schemeless_hit = True
            except Exception:
                pass

        effective_text_url_count = len(text_urls) + (1 if schemeless_hit else 0)
        if effective_text_url_count >= 3:
            score += 3
            reasons.append(f"text_urls={effective_text_url_count}")
        elif effective_text_url_count >= 2:
            score += 2
            reasons.append(f"text_urls={effective_text_url_count}")
        elif effective_text_url_count == 1 and (
            strong_matches or medium_matches or matched_patterns
        ):
            score += 1
            reasons.append("text_urls=1")
        elif schemeless_hit:
            reasons.append("text_urls=scheme-less")

        body_len = len(normalized)
        if body_len < 60 and button_count >= 5 and (
            strong_matches or medium_matches or matched_patterns
        ):
            score += 2
            reasons.append("short_promo+many_buttons")
        elif body_len < 50 and button_count >= 3 and (
            strong_matches or medium_matches or matched_patterns
        ):
            score += 2
            reasons.append("short_promo+buttons")
        elif body_len < 30 and button_count >= 2 and (
            strong_matches or matched_patterns
        ):
            score += 1
            reasons.append("short_text+buttons")

        caps_n = len(_CAPS_WORD_RE.findall(analysis_text))
        if caps_n >= 8 and (
            strong_matches or medium_matches or matched_patterns
        ):
            score += 3
            reasons.append(f"CAPS={caps_n}")
        elif caps_n >= 6 and (
            strong_matches or medium_matches or matched_patterns
        ):
            score += 2
            reasons.append(f"CAPS={caps_n}")
        elif caps_n >= 4 and (strong_matches or matched_patterns):
            score += 1
            reasons.append(f"CAPS={caps_n}")

        promo_count = (
            len(strong_matches) + len(medium_matches) + len(cta_only_matches)
        )
        if promo_count >= 8:
            score += 3
            reasons.append(f"promo_density={promo_count}")
        elif promo_count >= 6:
            score += 2
            reasons.append(f"promo_density={promo_count}")
        elif promo_count >= 4:
            score += 1
            reasons.append(f"promo_density={promo_count}")

        if len(strong_matches) >= 2 and (
            button_count >= 2 or cta_only_matches or button_cta_matches
        ):
            score += 3
            reasons.append("strong+cta/buttons")

        if 'leak' in strong_matches and (
            'viral' in strong_matches or 'mega' in strong_matches
        ):
            score += 2
            reasons.append("leak+viral/mega")

        if 'viral' in strong_matches and button_cta_matches:
            score += 2
            reasons.append("viral+button_cta")

        if _entity_urls and (strong_matches or matched_patterns):
            score += 2
            reasons.append("entity_url+keywords")

        # Anti-FP guard
        if (
            not strong_matches
            and not medium_matches
            and not matched_patterns
            and not text_urls
            and not schemeless_hit
            and tme_button_count == 0
            and external_button_count == 0
            and not button_cta_matches
            and not _entity_urls
        ):
            score = 0
            reasons = []

        score = min(max(score, 0), 20)

    except Exception as e:
        logger.debug("_compute_spam_score: %s", e)
        return 0, []

    return score, reasons


def _is_postbot_pattern(
    text: str,
    *,
    button_count: int = 0,
    has_urls: bool = False
) -> bool:
    if not text or len(text) < 10:
        return False

    hard_match = bool(_POSTBOT_HARD_KEYWORDS.search(text))
    if not hard_match and not has_urls and button_count < 2:
        return False

    try:
        if _POSTBOT_PATTERN.search(text):
            if hard_match or has_urls or button_count >= 2:
                return True

        if (
            hard_match
            and (has_urls or button_count >= 2)
            and _POSTBOT_PATTERN_LOOSE.search(text)
        ):
            return True

        if (
            len(text) < 200
            and hard_match
            and (has_urls or button_count >= 2)
            and _POSTBOT_BUTTON_PATTERN.search(text)
        ):
            return True

    except Exception:
        pass

    return False


# ═══════════════════════════════════════════════════════════════════
# Feature constants
# ═══════════════════════════════════════════════════════════════════

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

_DELETE_PERMISSION_ERROR = "message can't be deleted"

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
    logger.debug("🧪 _shutdown_started reset (test mode)")


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
            logger.debug(
                "⏸️ _lazy_init_columns: في cooldown (آخر محاولة قبل %.1fs)",
                now - _columns_last_attempt_ts,
            )
            return

        _columns_last_attempt_ts = now

        db_type = getattr(DB, "DB_TYPE", "sqlite")
        logger.info("🔧 v7.14.0: Auto-migration (DB_TYPE=%s)", db_type)

        cols = [
            ("delete_protected_any", "INTEGER DEFAULT 0", "TINYINT(1) DEFAULT 0"),
            ("delete_postbot_pattern", "INTEGER DEFAULT 0", "TINYINT(1) DEFAULT 0"),
            ("delete_spam_score", "INTEGER DEFAULT 1", "TINYINT(1) DEFAULT 1"),
            # v7.14.0: new settings
            ("delete_at_channel", "INTEGER DEFAULT 0", "TINYINT(1) DEFAULT 0"),
            ("delete_tg_scheme", "INTEGER DEFAULT 1", "TINYINT(1) DEFAULT 1"),
            ("delete_button_links", "INTEGER DEFAULT 1", "TINYINT(1) DEFAULT 1"),
        ]

        migration_ok = True

        for col_name, sqlite_def, mysql_def in cols:
            try:
                if db_type == "postgres":
                    await DB.execute(
                        "ALTER TABLE group_security "
                        "ADD COLUMN IF NOT EXISTS "
                        f"{col_name} {sqlite_def}"
                    )
                elif db_type == "mysql":
                    try:
                        await DB.execute(
                            "ALTER TABLE group_security "
                            f"ADD COLUMN {col_name} {mysql_def}"
                        )
                    except Exception as e:
                        m = str(e).lower()
                        if "duplicate" not in m and "already exists" not in m:
                            migration_ok = False
                            logger.warning("⚠️ MySQL %s: %s", col_name, e)
                else:
                    try:
                        await DB.execute(
                            "ALTER TABLE group_security "
                            f"ADD COLUMN {col_name} {sqlite_def}"
                        )
                    except Exception as e:
                        m = str(e).lower()
                        if "duplicate" not in m and "already exists" not in m:
                            migration_ok = False
                            logger.warning("⚠️ SQLite %s: %s", col_name, e)
            except Exception as e:
                migration_ok = False
                logger.warning("⚠️ auto-migration %s: %s", col_name, e)

        for update_sql, label in (
            (
                "UPDATE group_security SET delete_protected_any = 1 "
                "WHERE delete_forwarded = 1 "
                "AND (delete_protected_any IS NULL OR delete_protected_any = 0)",
                "delete_protected_any",
            ),
            (
                "UPDATE group_security SET delete_postbot_pattern = 1 "
                "WHERE delete_forwarded = 1 "
                "AND (delete_postbot_pattern IS NULL OR delete_postbot_pattern = 0)",
                "delete_postbot_pattern",
            ),
        ):
            try:
                await DB.execute(update_sql)
                logger.info("✅ %s", label)
            except Exception as e:
                migration_ok = False
                logger.warning("⚠️ UPDATE %s: %s", label, e)

        try:
            await internal_cache.clear()
            logger.info("✅ internal_cache cleared")
        except Exception as e:
            logger.debug("cache clear: %s", e)

        if migration_ok:
            _columns_initialized = True
        else:
            logger.warning(
                "⚠️ Auto-migration لم يكتمل — ستُعاد المحاولة بعد %ds",
                int(_COLUMNS_RETRY_COOLDOWN_SEC),
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
            logger.warning("get_dev_log_channel_cached: %s", e)
            return _dev_log_cache


def _invalidate_dev_log_cache():
    global _dev_log_cache, _dev_log_cache_ts
    _dev_log_cache = None
    _dev_log_cache_ts = 0.0


# ═══════════════════════════════════════════════════════════════════
# Log Rate Limit
# ═══════════════════════════════════════════════════════════════════

_log_rate_tracker = defaultdict(
    lambda: deque(maxlen=LOG_RATE_LIMIT_PER_MIN)
)
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
                logger.warning("🚫 LOG-RATE-LIMIT | chat=%s", chat_id)
            else:
                logger.debug("🚫 LOG-RATE-LIMIT (silent) | chat=%s", chat_id)
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
            logger.debug("🚫 DEV-LOG-RATE-LIMIT")
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
            chat_id=target,
            text=text,
            parse_mode='HTML',
            disable_web_page_preview=True
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
    retries: int = LOG_RETRY_ATTEMPTS
):
    if _is_shutting_down():
        if inspect.iscoroutine(factory):
            logger.warning(
                "⚠️ _dispatch_log[%s]: shutdown + coroutine مباشر. سيُغلق.",
                label,
            )
            try:
                factory.close()
            except Exception:
                pass
        else:
            logger.debug(
                "⏭️ _dispatch_log[%s]: shutdown — تجاهل", label
            )
        return

    if not callable(factory):
        _factory_type = type(factory).__name__
        if inspect.iscoroutine(factory):
            try:
                factory.close()
            except Exception:
                pass
        logger.error(
            "❌ _dispatch_log: متوقع factory (callable) — "
            "وُجد %s. استخدم partial(...) أو lambda: coro().",
            _factory_type,
        )
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
                    logger.warning(
                        "⚠️ [%s] attempt %d فشل: %s — إعادة بعد %.1fs",
                        label, attempt + 1, e, delay,
                    )
                    try:
                        await asyncio.sleep(delay)
                    except asyncio.CancelledError:
                        return
                    attempt += 1
                    continue
                break

        _log_dispatch_failures += 1
        logger.error(
            "❌ [%s] failed بعد %d محاولات (total_failures=%d): %s",
            label, retries + 1, _log_dispatch_failures, last_exc,
        )

    task = asyncio.create_task(_runner())
    _running_log_tasks.add(task)

    def _cleanup(t):
        _running_log_tasks.discard(t)
        try:
            if not t.cancelled() and t.exception():
                logger.error(
                    "❌ [%s] background task failed: %s",
                    label, t.exception()
                )
        except Exception:
            pass

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
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("⏱️ shutdown_log_dispatcher: مهلة انتهت")
    except Exception as e:
        logger.debug("shutdown_log_dispatcher: %s", e)

    _running_log_tasks.clear()


# ═══════════════════════════════════════════════════════════════════
# General Tracked Background Tasks
# ═══════════════════════════════════════════════════════════════════

_running_bg_tasks: set = set()


def _spawn_tracked_task(coro, *, label: str = "bg-task"):
    if _is_shutting_down():
        try:
            if inspect.iscoroutine(coro):
                coro.close()
        except Exception:
            pass
        logger.debug("⏭️ _spawn_tracked_task[%s]: shutdown — تجاهل", label)
        return None

    try:
        task = asyncio.create_task(coro)
    except Exception as e:
        logger.debug("_spawn_tracked_task(%s) فشل الإنشاء: %s", label, e)
        try:
            if inspect.iscoroutine(coro):
                coro.close()
        except Exception:
            pass
        return None

    _running_bg_tasks.add(task)

    def _cleanup(t):
        _running_bg_tasks.discard(t)
        try:
            if not t.cancelled() and t.exception():
                logger.debug("[%s] failed: %s", label, t.exception())
        except Exception:
            pass

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
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.debug("⏱️ shutdown_bg_tasks: مهلة انتهت")
    except Exception:
        pass

    _running_bg_tasks.clear()


# ═══════════════════════════════════════════════════════════════════
# Delayed Delete Task Tracker
# ═══════════════════════════════════════════════════════════════════

_running_delete_tasks: set = set()


async def _delete_after_delay(bot, chat_id, message_id, delay=10):
    try:
        if delay > 0:
            await asyncio.sleep(delay)
        await _safe_delete_message(bot, chat_id, message_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


def _spawn_delete_after_delay(bot, chat_id, message_id, delay=10):
    if _is_shutting_down():
        logger.debug(
            "⏭️ _spawn_delete_after_delay: shutdown — تجاهل"
        )
        return

    try:
        d = float(delay)
    except (TypeError, ValueError):
        d = 0.0
    if d < 0:
        d = 0.0

    task = asyncio.create_task(
        _delete_after_delay(bot, chat_id, message_id, d)
    )
    _running_delete_tasks.add(task)

    def _cleanup(t):
        _running_delete_tasks.discard(t)
        try:
            if not t.cancelled() and t.exception():
                logger.debug(
                    "delayed_delete task failed: %s", t.exception()
                )
        except Exception:
            pass

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
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        pass
    except Exception:
        pass

    _running_delete_tasks.clear()


def register_shutdown_handlers(application):
    if getattr(application, '_msh_shutdown_registered', False):
        logger.debug(
            "register_shutdown_handlers: مُسجَّل مسبقاً — تخطي"
        )
        return

    try:
        original_post_shutdown = getattr(
            application, 'post_shutdown', None
        )

        async def _post_shutdown(app):
            _mark_shutdown_started()

            try:
                await shutdown_log_dispatcher(timeout=5.0)
            except Exception as e:
                logger.debug("shutdown log: %s", e)
            try:
                await shutdown_bg_tasks(timeout=3.0)
            except Exception as e:
                logger.debug("shutdown bg: %s", e)
            try:
                await shutdown_delete_tasks(timeout=3.0)
            except Exception as e:
                logger.debug("shutdown del: %s", e)

            if callable(original_post_shutdown):
                try:
                    await original_post_shutdown(app)
                except Exception as e:
                    logger.debug("original post_shutdown: %s", e)

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
    'at_channel': '📢 منشن قناة',
    'tg_scheme': '🔗 رابط Telegram',
    'button_link': '🔘 زر برابط',
    'vcard_url': '📇 بطاقة اتصال',
    'venue_url': '📍 موقع',
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

_DEFAULT_VIOLATION_MESSAGES = {
    'link': '🚫 يُمنع إرسال الروابط في هذه المجموعة',
    'mention': '🚫 يُمنع المنشن في هذه المجموعة',
    'banned_word': '🚫 تحتوي رسالتك على كلمة محظورة',
    'max_len': '📏 رسالتك تتجاوز الحد الأقصى للطول المسموح',
    'forwarded': '↩️ يُمنع إعادة توجيه الرسائل في هذه المجموعة',
    'video': '🎬 يُمنع إرسال مقاطع الفيديو هنا',
    'audio': '🎵 يُمنع إرسال الملفات الصوتية هنا',
    'voice': '🎤 يُمنع إرسال الرسائل الصوتية هنا',
    'animation': '🎞️ يُمنع إرسال الأنيميشن هنا',
    'document': '📄 يُمنع إرسال الملفات هنا',
    'sticker': '🖼️ يُمنع إرسال الملصقات هنا',
    'photo': '📷 يُمنع إرسال الصور هنا',
    'video_note': '🎥 يُمنع إرسال فيديو نوت هنا',
    'postbot_pattern': '🤖 رُصدت رسالتك كنمط Post Bot مزعج',
    'spam_score': '🚫 رُصدت رسالتك كرسالة دعائية/Spam',
    'service': '🗑️ رسائل الخدمة محذوفة تلقائياً',
    'at_channel': '📢 يُمنع منشن القنوات هنا',
    'tg_scheme': '🔗 يُمنع إرسال روابط Telegram هنا',
    'button_link': '🔘 يُمنع إرسال أزرار بروابط',
    'vcard_url': '📇 يُمنع إرسال بطاقات اتصال تحوي روابط',
    'venue_url': '📍 يُمنع إرسال مواقع',
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
# Logging
# ═══════════════════════════════════════════════════════════════════

async def notify_group_log(context, chat_id, text, disable_preview=True):
    try:
        getter = getattr(DB, 'get_group_log_channel', None)
        if not callable(getter):
            return False

        channel_id = await getter(chat_id)
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
            logger.error("❌ group_log: قناة غير موجودة | %s", chat_id)
        elif "not enough rights" in err or "bot is not a member" in err:
            logger.error("❌ group_log: البوت ليس عضواً | %s", chat_id)
        return False

    except Exception as e:
        logger.error("❌ group_log FAILED: %s", e)
        return False


def _build_delete_log_text(
    chat_id, user_id, user_first_name, user_username,
    violation_type, forward_info=None, message_preview=None,
    is_anonymous=False
):
    label = _VIOLATION_LABELS_AR.get(violation_type, violation_type)

    if is_anonymous:
        user_display_lnk = "👻 <b>مشرف مجهول</b>"
    else:
        user_display = escape(user_first_name or 'User')
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
        lines.append(f"🆔 المعرّف: <code>{user_id}</code>")
    else:
        lines.append(f"🆔 المجموعة: <code>{chat_id}</code>")

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
            lines.append(
                f"   • المعرّف: <code>{forward_info['id']}</code>"
            )

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
    violation_type=None, moderator_id=None, moderator_name=None
):
    ptype_label = _PENALTY_LABELS_AR.get(penalty_type, penalty_type)
    target_display = escape(target_first_name or 'User')

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

    source_label = "🤖 تلقائي" if source == "auto" else "👮 يدوي"

    lines = [
        f"{ptype_label}",
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
    violation_type=None, moderator_id=None, moderator_name=None
):
    if not FEATURE_LOG_PENALTIES:
        return

    try:
        if not await _can_send_log(chat_id):
            return
    except Exception as e:
        logger.debug("_notify_group_log_penalty rate-check: %s", e)
        return

    try:
        text = _build_penalty_log_text(
            chat_id, target_user_id, target_first_name,
            target_username, penalty_type, duration_seconds,
            source, violation_type, moderator_id, moderator_name
        )
        await _dispatch_log(
            partial(notify_group_log, context, chat_id, text),
            label=f"penalty-{penalty_type}"
        )
    except Exception as e:
        logger.warning("⚠️ _notify_group_log_penalty: %s", e)


# ═══════════════════════════════════════════════════════════════════
# Security Auth Cache + Delete Failure Notifier (v7.14.0 #5)
# ═══════════════════════════════════════════════════════════════════

_sec_auth_cache: Dict[Any, Tuple[Any, float]] = {}
_sec_auth_cache_lock = asyncio.Lock()


async def _sec_auth_cache_cleanup():
    async with _sec_auth_cache_lock:
        now = time.monotonic()

        expired = [
            key for key, (_, ts) in _sec_auth_cache.items()
            if now - ts > SEC_AUTH_CACHE_TTL
        ]
        for key in expired:
            _sec_auth_cache.pop(key, None)

        if len(_sec_auth_cache) > MAX_SEC_AUTH_CACHE_SIZE:
            extra = len(_sec_auth_cache) - MAX_SEC_AUTH_CACHE_SIZE
            oldest = sorted(
                _sec_auth_cache.items(),
                key=lambda item: item[1][1]
            )[:extra]
            for key, _ in oldest:
                _sec_auth_cache.pop(key, None)

        return len(expired)


def _is_delete_ignore_error(exc) -> bool:
    try:
        s = str(exc).lower()
        return any(p in s for p in _DELETE_IGNORED_PATTERNS)
    except Exception:
        return False


def _is_delete_permission_error(exc) -> bool:
    try:
        return _DELETE_PERMISSION_ERROR in str(exc).lower()
    except Exception:
        return False


# v7.14.0 #5: قائمة تجنّب إرسال التنبيه أكثر من مرة لكل مجموعة
_delete_failure_notified: Dict[int, float] = {}
_DELETE_FAILURE_NOTIFY_COOLDOWN = 3600.0
_delete_failure_notify_lock = asyncio.Lock()


async def _notify_delete_permission_failure(context, chat_id):
    """
    v7.14.0 #5: يُنبّه المالك مرة واحدة عند فشل الحذف بسبب الصلاحيات.
    يمنع تكرار التنبيه لمدّة ساعة.
    """
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
            "⚠️ <b>تحذير حرج — الحماية معطّلة!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"البوت لا يستطيع حذف الرسائل في المجموعة "
            f"<code>{chat_id}</code>.\n\n"
            "🔴 <b>جميع إعدادات الحماية معطّلة فعلياً</b> — "
            "أي رسالة مخالفة لن تُحذف!\n\n"
            "✅ <b>الحل:</b>\n"
            "1. ارفع البوت لمشرف في المجموعة\n"
            "2. امنحه صلاحية <code>can_delete_messages</code>\n"
            "3. تأكد من أن البوت عضو في المجموعة\n"
        )

        try:
            await safe_send(context.bot, owner_id, msg, parse_mode='HTML')
        except Exception as e:
            logger.warning("_notify_delete_permission_failure send: %s", e)
    except Exception as e:
        logger.debug("_notify_delete_permission_failure: %s", e)


async def _safe_delete_message(
    bot, chat_id, message_id, *,
    context=None, notify_owner=True
) -> bool:
    try:
        await bot.delete_message(chat_id, message_id)
        logger.debug("✅ DELETE OK | chat=%s msg=%s", chat_id, message_id)
        return True

    except BadRequest as e:
        if _is_delete_permission_error(e):
            logger.error(
                "❌ DELETE FAILED (permission) | chat=%s msg=%s",
                chat_id, message_id,
            )
            # v7.14.0 #5
            if notify_owner and context is not None:
                try:
                    _spawn_tracked_task(
                        _notify_delete_permission_failure(context, chat_id),
                        label="delete-perm-notify"
                    )
                except Exception:
                    pass
            return False

        if _is_delete_ignore_error(e):
            return True

        logger.warning(
            "⚠️ DELETE failed | chat=%s msg=%s", chat_id, message_id
        )
        return False

    except asyncio.CancelledError:
        raise

    except Exception as e:
        if _is_delete_permission_error(e):
            if notify_owner and context is not None:
                try:
                    _spawn_tracked_task(
                        _notify_delete_permission_failure(context, chat_id),
                        label="delete-perm-notify"
                    )
                except Exception:
                    pass
            return False
        if _is_delete_ignore_error(e):
            return True

        logger.warning(
            "⚠️ DELETE failed | chat=%s msg=%s | %s",
            chat_id, message_id, e,
        )
        return False


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
    message,
    *,
    allow_protected_fallback=False,
    allow_protected_any=False
) -> bool:
    if message is None:
        return False

    for attr in (
        'forward_origin', 'forward_date', 'forward_from',
        'forward_from_chat', 'forward_sender_name'
    ):
        if getattr(message, attr, None) is not None:
            return True

    is_protected = _as_bool(
        getattr(message, 'has_protected_content', False), False
    )
    is_auto = _as_bool(
        getattr(message, 'is_automatic_forward', False), False
    )

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
        'forward_from_chat', 'forward_sender_name'
    ):
        value = getattr(message, name, None)
        fields[name] = {
            "present": value is not None,
            "type": type(value).__name__ if value is not None else None,
            "repr_short": str(value)[:80] if value is not None else None,
        }

    any_present = any(f["present"] for f in fields.values())
    protected = _as_bool(
        getattr(message, 'has_protected_content', False), False
    )
    caption = (
        getattr(message, 'caption', None)
        or getattr(message, 'text', None)
        or ""
    )
    hint = _has_forward_hint(caption) if protected else False
    auto_fwd = _as_bool(
        getattr(message, 'is_automatic_forward', False), False
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
                'date': fwd_date,
                'signature': None,
                'message_id': None,
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
                'date': fwd_date,
                'signature': fwd_signature,
                'message_id': None,
            }

        if fwd_sender_name:
            return {
                'type': 'hidden_user',
                'id': None,
                'name': str(fwd_sender_name),
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
                    'type': 'user',
                    'id': getattr(user, 'id', None),
                    'name': name,
                    'date': getattr(origin, 'date', None),
                    'signature': None,
                    'message_id': None,
                }

            if isinstance(origin, MessageOriginHiddenUser):
                return {
                    'type': 'hidden_user',
                    'id': None,
                    'name': (
                        getattr(origin, 'sender_user_name', None) or 'Hidden'
                    ),
                    'date': getattr(origin, 'date', None),
                    'signature': None,
                    'message_id': None,
                }

            if isinstance(origin, MessageOriginChat):
                chat = origin.sender_chat
                return {
                    'type': 'chat',
                    'id': getattr(chat, 'id', None),
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
                    'type': 'channel',
                    'id': getattr(chat, 'id', None),
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
        getattr(message, 'has_protected_content', False), False
    )

    if is_protected:
        caption = (
            getattr(message, 'caption', None)
            or getattr(message, 'text', None)
            or ""
        )

        if _has_forward_hint(caption):
            return {
                'type': 'protected',
                'id': None,
                'name': '🛡️ محتوى محمي (forward مخفي)',
                'date': None,
                'signature': None,
                'message_id': None,
            }

        return {
            'type': 'protected_any',
            'id': None,
            'name': '🛡️ محتوى محمي',
            'date': None,
            'signature': None,
            'message_id': None,
        }

    return None


async def _notify_admin_about_forward(context, admin_id, info):
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

        label = type_labels.get(info.get('type', ''), f"❔ {info.get('type')}")

        lines = [
            "↩️ <b>رسالة معاد توجيهها</b>",
            "",
            f"📌 النوع: {label}"
        ]

        if info.get('id'):
            lines.append(f"🆔 المصدر: <code>{info['id']}</code>")
        if info.get('name'):
            lines.append(f"📛 الاسم: {escape(str(info['name']))}")
        if info.get('message_id'):
            lines.append(
                f"🔢 رقم الرسالة: <code>{info['message_id']}</code>"
            )
        if info.get('date'):
            lines.append(f"📅 التاريخ: <code>{info['date']}</code>")

        await safe_send(
            context.bot, admin_id, "\n".join(lines), parse_mode='HTML'
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
            logger.debug(
                "🧹 _forward_notify keys cleanup: أُزيل %d (متبقٍ %d)",
                remove_count, len(fwd_keys) - remove_count,
            )

        bot_data[key] = now
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
# Cache invalidation helper
# ═══════════════════════════════════════════════════════════════════

async def _invalidate_after_channel_change(
    user_id, channel_db_id=None, invalidate_posts=True
):
    keys = [
        f"start_data_{user_id}",
        f"user_{user_id}",
        f"user_{user_id}_True",
        f"user_{user_id}_False",
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

            if (
                len(cls._limiters) >= cls.MAX_SIZE
                and chat_id not in cls._limiters
            ):
                sorted_items = sorted(
                    cls._last_access.items(), key=lambda item: item[1]
                )
                to_remove = sorted_items[: max(1, cls.MAX_SIZE // 5)]
                for cid, _ in to_remove:
                    cls._limiters.pop(cid, None)
                    cls._last_access.pop(cid, None)

            if chat_id not in cls._limiters:
                cls._limiters[chat_id] = RateLimiter(
                    max_concurrent=5, max_per_second=10
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

                await _sec_auth_cache_cleanup()
                await _cleanup_log_rate_tracker()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("❌ periodic_cleanup: %s", e)


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
    except Exception as e:
        logger.debug("group limiter release: %s", e)


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
            if update and update.effective_user
            else None
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
                DB.get_user_language(user_id), timeout=2.0
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


# ═══════════════════════════════════════════════════════════════════
# Security Settings Cache
# ═══════════════════════════════════════════════════════════════════

async def get_security_settings_cached(chat_id) -> dict:
    cached = await settings_cache.get_security(chat_id)
    if cached is not None:
        return cached

    settings = await DB.get_security_settings(chat_id)
    if settings is None:
        settings = {}

    await settings_cache.set_security(chat_id, settings)
    return settings


async def get_auto_reply_settings_cached(chat_id) -> dict:
    cached = await settings_cache.get_auto_reply_settings(chat_id)
    if cached is not None:
        return cached

    settings = await DB.get_auto_reply_settings(chat_id)
    if settings is None:
        settings = {}

    await settings_cache.set_auto_reply_settings(chat_id, settings)
    return settings


async def invalidate_security_cache(chat_id=None):
    await settings_cache.invalidate_security(chat_id)


async def invalidate_auto_reply_cache(chat_id=None):
    await settings_cache.invalidate_auto_reply(chat_id)


# ═══════════════════════════════════════════════════════════════════
# Translation Detection
# ═══════════════════════════════════════════════════════════════════

async def _detect_and_translate(update, context, chat_id, user_id, text):
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
    bot, chat_id, original_message_id, translated, lang
):
    try:
        label = (
            TranslationManager.get_text(lang, "translation_label")
            or "🌐 <b>Translation:</b>"
        )
    except Exception:
        label = "🌐 <b>Translation:</b>"

    try:
        kwargs = {
            "chat_id": chat_id,
            "text": f"{label}\n{escape(translated)}",
            "parse_mode": "HTML",
        }
        if original_message_id:
            kwargs["reply_to_message_id"] = original_message_id

        sent = await bot.send_message(**kwargs)

        if sent and getattr(sent, 'message_id', None):
            _spawn_delete_after_delay(
                bot, chat_id, sent.message_id,
                TRANSLATION_REPLY_DELETE_DELAY
            )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# Penalties
# ═══════════════════════════════════════════════════════════════════

async def apply_violation_penalty(
    update, context, chat_id, user_id,
    violation_type, penalty_type, duration_seconds, lang='ar'
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
            context.bot, chat_id, user_id, penalty_type,
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
        logger.error("❌ apply_violation_penalty: %s", e)
        return False, str(e)[:100]


# ═══════════════════════════════════════════════════════════════════
# URL / Date Helpers
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
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M",
        "%d-%m-%Y"
    ):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue

    return None


# ═══════════════════════════════════════════════════════════════════
# Admin Helpers
# ═══════════════════════════════════════════════════════════════════

async def _check_admin_in_chat(context, chat_id, user_id) -> bool:
    if user_id == CONFIG.PRIMARY_OWNER_ID:
        return True

    try:
        if await is_authorized_in_group(context.bot, chat_id, user_id):
            return True
    except Exception:
        pass

    try:
        db_type = getattr(DB, "DB_TYPE", "sqlite")
        if db_type == "postgres":
            sql = (
                "SELECT 1 FROM group_admins "
                "WHERE chat_id = $1 AND user_id = $2 LIMIT 1"
            )
        else:
            sql = (
                "SELECT 1 FROM group_admins "
                "WHERE chat_id = ? AND user_id = ? LIMIT 1"
            )

        row = await DB.fetchval(sql, (chat_id, user_id))
        return row is not None
    except Exception:
        return False


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
            context.bot.get_chat_member(channel_id, bot_id),
            timeout=10.0
        )
    except asyncio.TimeoutError:
        return False, "timeout"
    except BadRequest as e:
        err = str(e).lower()
        if any(x in err for x in (
            "chat not found", "bot is not a member",
            "member not found", "user not found"
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


# ═══════════════════════════════════════════════════════════════════
# Channel Reference Validation
# ═══════════════════════════════════════════════════════════════════

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
# Banned Word Matching — v7.14.0 (C1 + G7 + #16 ReDoS fix)
# ═══════════════════════════════════════════════════════════════════

_compiled_banned_patterns: "OrderedDict[str, re.Pattern]" = OrderedDict()
_compiled_spaced_patterns: "OrderedDict[str, re.Pattern]" = OrderedDict()


def _get_banned_pattern(banned_word: str) -> Optional[re.Pattern]:
    cached = _compiled_banned_patterns.get(banned_word)
    if cached is not None:
        _compiled_banned_patterns.move_to_end(banned_word)
        return cached

    try:
        escaped = re.escape(banned_word).replace(r'\ ', r'\s+')
        pattern = re.compile(
            rf'(?<!\w){escaped}(?!\w)',
            re.IGNORECASE | re.UNICODE
        )
    except Exception:
        return None

    _compiled_banned_patterns[banned_word] = pattern
    if len(_compiled_banned_patterns) > MAX_COMPILED_BANNED_PATTERNS:
        _compiled_banned_patterns.popitem(last=False)

    return pattern


def _get_spaced_banned_pattern(banned_word: str) -> Optional[re.Pattern]:
    """
    v7.14.0 #16: مقيّد بشدة لمنع ReDoS.
      - حد أقصى 15 حرفاً.
      - الفاصل بين الحروف {1,2} فقط (لا {0,3}).
      - لا يُطبَّق على نصوص أطول من 4000 حرف.
    """
    cached = _compiled_spaced_patterns.get(banned_word)
    if cached is not None:
        _compiled_spaced_patterns.move_to_end(banned_word)
        return cached

    try:
        if len(banned_word) < 3 or len(banned_word) > 15:
            return None
        chars = list(banned_word)
        # v7.14.0 #16: {1,2} فقط بين الحروف
        body = r'[\s\-_.|/*+=~^`•●○▪▫■□♦♢※]{1,2}'.join(
            re.escape(c) for c in chars
        )
        pattern = re.compile(
            rf'(?<!\w){body}(?!\w)',
            re.IGNORECASE | re.UNICODE
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

    # v7.14.0 #16: حماية ضد ReDoS
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

        if _ANTIEVASION_COMPACT_WORDS and len(normalized_word) >= 3:
            compact_text = re.sub(
                _WORD_SEP_CLASS, '', normalized_text
            )
            compact_word = re.sub(
                _WORD_SEP_CLASS, '', normalized_word
            )
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


# ═══════════════════════════════════════════════════════════════════
# Message Handlers
# ═══════════════════════════════════════════════════════════════════

_private_handler_signature_cache: Dict[str, bool] = {}


def _accepts_state_arg(handler, handler_name: str) -> bool:
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

    _private_handler_signature_cache[handler_name] = result
    return result


class MessageHandlers:

    _PRIVATE_HANDLERS_MAP: Dict[Any, str] = {}

    @staticmethod
    async def handle_group(update, context):
        if (
            not update
            or not update.effective_chat
            or not update.effective_message
        ):
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
    async def _handle_group_impl(update, context):
        if (
            not update.effective_chat
            or not update.effective_message
        ):
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

        # ═══ بناء _MessageContext ═══
        ctx = _MessageContext()
        ctx.text = message.text or ""
        ctx.caption = message.caption or ""
        ctx.full_text = f"{ctx.text} {ctx.caption}".strip()

        # v7.14.0 #4: دمج روابط مقطوعة قبل التطبيع
        merged_text = _merge_split_urls(ctx.full_text)
        ctx.normalized_text = _normalize_text(merged_text)
        ctx.has_hidden_chars = _has_hidden_chars(ctx.full_text)

        (
            ctx.button_count,
            ctx.button_urls_raw,
            ctx.button_texts,
        ) = _extract_button_context(message)

        ctx.entity_urls = _extract_entity_urls(message)
        ctx.has_link_entity = _has_link_entity(message)
        ctx.button_link_urls = _extract_button_link_urls(ctx)
        ctx.has_button_link = bool(ctx.button_link_urls)

        # v7.14.0 #13/#14
        ctx.vcard_urls = _extract_vcard_urls(message)
        ctx.venue_url = _extract_venue_url(message)

        # has_any_link — تحقّق موحَّد شامل
        has_text_link = _contains_link_enhanced(ctx.normalized_text)
        ctx.has_any_link = bool(
            has_text_link
            or ctx.has_link_entity
            or ctx.has_button_link
            or ctx.entity_urls
            or ctx.vcard_urls
            or ctx.venue_url
        )

        if ctx.button_texts:
            btn_joined = _normalize_text(" ".join(ctx.button_texts))
            ctx.analysis_text = (
                f"{ctx.normalized_text} {btn_joined}".strip()
                if ctx.normalized_text
                else btn_joined
            )
        else:
            ctx.analysis_text = ctx.normalized_text

        if ctx.entity_urls:
            ent_joined = _normalize_text(" ".join(
                str(u)[:200] for u in ctx.entity_urls[:10]
            ))
            if ent_joined:
                ctx.analysis_text = (
                    f"{ctx.analysis_text} {ent_joined}".strip()
                    if ctx.analysis_text else ent_joined
                )

        if ctx.vcard_urls:
            vc_joined = _normalize_text(" ".join(ctx.vcard_urls[:5]))
            if vc_joined:
                ctx.analysis_text = (
                    f"{ctx.analysis_text} {vc_joined}".strip()
                )

        if ctx.venue_url:
            ctx.analysis_text = (
                f"{ctx.analysis_text} {ctx.venue_url}".strip()
            )

        ctx.button_urls = [str(u)[:120] for u in ctx.button_urls_raw[:10]]

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
            settings.get('delete_protected_forward'), False
        )
        _protected_any = _as_bool(
            settings.get('delete_protected_any'), False
        )
        _spam_enabled = _as_bool(
            settings.get('delete_spam_score', True), True
        )
        _postbot_enabled = _as_bool(
            settings.get('delete_postbot_pattern', 0), False
        )
        # v7.14.0 new settings
        _at_channel_enabled = _as_bool(
            settings.get('delete_at_channel', 0), False
        )
        _tg_scheme_enabled = _as_bool(
            settings.get('delete_tg_scheme', 1), True
        )
        _button_links_enabled = _as_bool(
            settings.get('delete_button_links', 1), True
        )

        det = get_forward_detection_reason(message)
        ctx.is_forwarded = _as_bool(det.get('is_forwarded', False), False)
        ctx.is_protected = _as_bool(det.get('is_protected', False), False)
        ctx.has_hint = _as_bool(det.get('has_hint', False), False)
        ctx.is_auto_fwd = _as_bool(
            det.get('has_automatic_forward', False), False
        )

        is_protected_forward = (
            _protected_fb
            and ctx.is_protected
            and ctx.has_hint
            and not ctx.is_forwarded
        )

        is_protected_any_fwd = (
            _protected_any
            and ctx.is_protected
            and not ctx.is_forwarded
            and not is_protected_forward
        )

        # ═══ Spam score ═══
        _spam_score = 0
        _spam_reasons: List[str] = []

        if _spam_enabled:
            try:
                _spam_score, _spam_reasons = _compute_spam_score(
                    message,
                    _button_count=ctx.button_count,
                    _button_urls=ctx.button_urls_raw,
                    _button_texts=ctx.button_texts,
                    _normalized=ctx.normalized_text,
                    _analysis_text=ctx.analysis_text,
                    _entity_urls=ctx.entity_urls,
                )
            except Exception as e:
                logger.debug("spam_score: %s", e)

        _is_spam = _spam_enabled and _spam_score >= SPAM_SCORE_THRESHOLD

        _postbot_match = False
        if _postbot_enabled:
            try:
                _postbot_match = _is_postbot_pattern(
                    ctx.analysis_text,
                    button_count=ctx.button_count,
                    has_urls=bool(ctx.button_urls_raw) or bool(ctx.entity_urls),
                )
            except Exception:
                _postbot_match = False

        if _DEBUG_DIAG:
            will_delete_fwd = _df_bool and (
                ctx.is_forwarded or ctx.is_auto_fwd
                or is_protected_forward or is_protected_any_fwd
            )
            _log_level = (
                logging.WARNING
                if (will_delete_fwd or _is_spam or _postbot_match)
                else logging.INFO
            )

            logger.log(
                _log_level,
                "🚨 DIAG | chat=%s user=%s msg=%s%s | "
                "txt=%s cap=%s analysis_len=%d | "
                "photo=%s video=%s | btns=%d | "
                "prot=%s auto_fwd=%s | df=%r/%s | "
                "spam_en=%s score=%d is_spam=%s | "
                "postbot_en=%s match=%s | "
                "has_link=%s btn_links=%d ent_links=%d | "
                "vcard=%d venue=%s hidden=%s",
                chat_id, user_id, message.message_id,
                " [ANON]" if is_anonymous else "",
                bool(ctx.text), bool(ctx.caption),
                len(ctx.analysis_text),
                bool(message.photo), bool(message.video),
                ctx.button_count,
                ctx.is_protected, ctx.is_auto_fwd,
                _df_raw, _df_bool,
                _spam_enabled, _spam_score, _is_spam,
                _postbot_enabled, _postbot_match,
                ctx.has_any_link,
                len(ctx.button_link_urls),
                len(ctx.entity_urls),
                len(ctx.vcard_urls),
                bool(ctx.venue_url),
                ctx.has_hidden_chars,
            )

            if ctx.button_texts:
                logger.info("   🔘 BTN | %s", ctx.button_texts[:12])
            if ctx.button_urls:
                logger.info("   🔗 URL | %s", ctx.button_urls[:5])
            if ctx.entity_urls:
                logger.info("   🎭 ENT | %s", ctx.entity_urls[:5])
            if _spam_score > 0:
                logger.warning("   🎯 SPAM=%d | %s", _spam_score, _spam_reasons)

        # 0) Service
        if _as_bool(settings.get('delete_service'), False):
            if message.new_chat_members or message.left_chat_member:
                await _safe_delete_message(
                    context.bot, chat_id, message.message_id,
                    context=context,
                )
                return

        # 1) Forwarded
        if _df_bool:
            effective_forwarded = (
                ctx.is_forwarded or ctx.is_auto_fwd
                or is_protected_forward or is_protected_any_fwd
            )

            if effective_forwarded:
                if _DEBUG_DIAG:
                    tag = (
                        " [AUTO-FWD]" if ctx.is_auto_fwd
                        else " [PROT-ANY]" if is_protected_any_fwd
                        else " [PROT-FB]" if is_protected_forward
                        else ""
                    )
                    logger.warning(
                        "🎯 HANDLE-FWD | chat=%s user=%s msg=%s%s",
                        chat_id, user_id, message.message_id, tag,
                    )

                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id,
                    "forwarded", settings, is_anonymous=is_anonymous
                )
                return

        # 2) Spam Score
        if _is_spam:
            if _DEBUG_SPAM:
                logger.warning(
                    "🚫 SPAM | chat=%s user=%s score=%d reasons=%s",
                    chat_id, user_id, _spam_score, _spam_reasons,
                )

            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id,
                "spam_score", settings, is_anonymous=is_anonymous
            )
            return

        # 3) PostBot Pattern
        if _postbot_enabled and _postbot_match:
            if _DEBUG_SPAM:
                logger.warning(
                    "🤖 POSTBOT | chat=%s user=%s", chat_id, user_id
                )

            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id,
                "postbot_pattern", settings, is_anonymous=is_anonymous
            )
            return

        # ═══ 4) Links — v7.14.0: فحص شامل ═══
        if _as_bool(settings.get('delete_links'), False):
            if ctx.has_any_link:
                # v7.14.0: قد نفرّق حسب النوع للتنبيه الدقيق
                if _DEBUG_DIAG:
                    logger.warning(
                        "🔗 LINK-DELETE | chat=%s user=%s | "
                        "text=%s btns=%d entities=%d vcard=%d venue=%s",
                        chat_id, user_id, has_text_link,
                        len(ctx.button_link_urls),
                        len(ctx.entity_urls),
                        len(ctx.vcard_urls),
                        bool(ctx.venue_url),
                    )

                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id,
                    "link", settings, is_anonymous=is_anonymous
                )
                return

        # 4b) @channel (منفصل) — v7.14.0
        if _at_channel_enabled and _ANTIEVASION_AT_CHANNEL:
            try:
                if _AT_CHANNEL_RE.search(ctx.normalized_text):
                    await MessageHandlers._delete_and_warn(
                        update, context, chat_id, user_id,
                        "at_channel", settings, is_anonymous=is_anonymous
                    )
                    return
            except Exception:
                pass

        # 4c) tg:// scheme (منفصل) — v7.14.0
        if _tg_scheme_enabled and _ANTIEVASION_TG_SCHEME:
            try:
                if _TG_SCHEME_RE.search(ctx.normalized_text):
                    await MessageHandlers._delete_and_warn(
                        update, context, chat_id, user_id,
                        "tg_scheme", settings, is_anonymous=is_anonymous
                    )
                    return
            except Exception:
                pass

        # 4d) Button links (منفصل) — v7.14.0
        if _button_links_enabled and ctx.has_button_link:
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id,
                "button_link", settings, is_anonymous=is_anonymous
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
                    "mention", settings, is_anonymous=is_anonymous
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
                    if _DEBUG_SPAM:
                        logger.info("   🎯 BANNED | %r", matched)

                    await MessageHandlers._delete_and_warn(
                        update, context, chat_id, user_id,
                        "banned_word", settings, is_anonymous=is_anonymous
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
                "max_len", settings, is_anonymous=is_anonymous
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
                vtype, settings, is_anonymous=is_anonymous
            )
            return

        # 9) Translation
        translate_source = ctx.text or ctx.caption
        if translate_source and not is_anonymous:
            try:
                translated = await _detect_and_translate(
                    update, context, chat_id, user_id, translate_source
                )
                if translated:
                    lang = await _ensure_lang(update, context)
                    await _send_translation_reply(
                        context.bot, chat_id,
                        message.message_id, translated, lang
                    )
            except Exception:
                pass

        # 10) Auto Reply
        if ctx.text:
            await MessageHandlers._process_auto_reply(
                update, context, chat_id, ctx.text, user_id
            )

    @staticmethod
    def _get_penalty_duration(settings, violation_type):
        if violation_type in ('flood', 'antiflood'):
            return settings.get('antiflood_penalty_duration', 3600)
        if violation_type in ('night', 'night_mode'):
            return settings.get('night_mode_action_duration', 3600)
        return settings.get('auto_mute_duration', 3600)

    @staticmethod
    async def _get_violation_message(violation_type, lang):
        trans_key = f"violation_{violation_type}"
        default = _DEFAULT_VIOLATION_MESSAGES.get(
            violation_type, f"🚫 {violation_type}"
        )
        return await _trans(trans_key, lang, default)

    @staticmethod
    async def _send_anonymous_warning(context, chat_id, violation_type, lang):
        try:
            vm = await MessageHandlers._get_violation_message(
                violation_type, lang
            )
            warn_title = await _trans(
                'violation_warning_title', lang, "⚠️"
            )

            sent_msg = await safe_send(
                context.bot, chat_id,
                f"{warn_title}\n{vm}\n👻 <b>مشرف مجهول</b>",
                parse_mode='HTML'
            )

            if sent_msg and getattr(sent_msg, 'message_id', None):
                _spawn_delete_after_delay(
                    context.bot, chat_id, sent_msg.message_id,
                    PENALTY_MESSAGE_DELETE_DELAY
                )
        except Exception:
            pass

    @staticmethod
    async def _send_user_warning(
        context, chat_id, user_name,
        violation_type, lang, violation_count
    ):
        try:
            vm = await MessageHandlers._get_violation_message(
                violation_type, lang
            )
            warn_title = await _trans(
                'violation_warning_title', lang, "⚠️"
            )
            count_label = await _trans(
                'violation_count_label', lang, "📊"
            )
            delete_notice = await _trans(
                'violation_delete_notice', lang, "⏳"
            )

            sent_msg = await safe_send(
                context.bot, chat_id,
                f"{warn_title}\n{vm}\n👤 {user_name}\n"
                f"{count_label}: {violation_count}\n{delete_notice}",
                parse_mode='HTML'
            )

            if sent_msg and getattr(sent_msg, 'message_id', None):
                _spawn_delete_after_delay(
                    context.bot, chat_id, sent_msg.message_id,
                    PENALTY_MESSAGE_DELETE_DELAY
                )
        except Exception:
            pass

    @staticmethod
    async def _resolve_penalty(
        chat_id, violation_type, settings
    ) -> Tuple[Optional[str], int]:
        penalty_rule = None
        try:
            penalty_rule = await DB.get_violation_penalty(
                chat_id, violation_type
            )
        except Exception:
            pass

        if penalty_rule:
            ptype = penalty_rule['penalty_type']
            if ptype == 'none':
                return None, 0
            return ptype, penalty_rule['duration_seconds']

        ptype = settings.get('auto_penalty', 'none')
        if ptype == 'none':
            return None, 0

        if ptype not in ('mute', 'ban', 'restrict', 'kick', 'warn'):
            ptype = 'mute'

        duration = MessageHandlers._get_penalty_duration(
            settings, violation_type
        )
        return ptype, duration

    @staticmethod
    async def _delete_and_warn(
        update, context, chat_id, user_id,
        violation_type, settings, is_anonymous=False
    ):
        lang = await _ensure_lang(update, context)

        message = update.effective_message
        if message is None:
            return

        message_preview = None
        try:
            message_preview = (
                (message.text or message.caption or "").strip() or None
            )
        except Exception:
            pass

        forward_info = None
        if violation_type == 'forwarded':
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
            logger.error(
                "⏭️ توقف — الحذف فشل (%s)", violation_type
            )
            return

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
                            update.effective_user, 'username', None
                        )
                    else:
                        user_first = "Unknown"
                        user_username = None

                    log_text = _build_delete_log_text(
                        chat_id=chat_id,
                        user_id=user_id,
                        user_first_name=user_first,
                        user_username=user_username,
                        violation_type=violation_type,
                        forward_info=forward_info,
                        message_preview=message_preview,
                        is_anonymous=is_anonymous
                    )

                    await _dispatch_log(
                        partial(
                            notify_group_log, context, chat_id, log_text
                        ),
                        label=f"delete-{violation_type}"
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
                    getattr(CONFIG, 'PRIMARY_OWNER_ID', 0) or 0
                )
                if owner_id:
                    _spawn_tracked_task(
                        _notify_admin_about_forward(
                            context, owner_id, forward_info
                        ),
                        label="forward-notify"
                    )
            except Exception as e:
                logger.debug("forward notify spawn: %s", e)

        if is_anonymous:
            await MessageHandlers._send_anonymous_warning(
                context, chat_id, violation_type, lang
            )
            return

        try:
            violation_count = await DB.increment_violation_count(
                user_id, chat_id
            )
        except Exception:
            violation_count = 1

        penalty_type, duration_seconds = await MessageHandlers._resolve_penalty(
            chat_id, violation_type, settings
        )

        try:
            await DB.add_admin_log(
                chat_id, context.bot.id,
                f"violation_{violation_type}", user_id
            )
        except Exception:
            pass

        eff_user = update.effective_user
        first_name = getattr(eff_user, 'first_name', None) if eff_user else None
        user_name = escape(first_name or "User")

        await MessageHandlers._send_user_warning(
            context, chat_id, user_name,
            violation_type, lang, violation_count
        )

        if not penalty_type:
            return

        try:
            max_strikes = int(
                settings.get('violation_strikes')
                or settings.get('max_warnings')
                or 3
            )
        except (TypeError, ValueError):
            max_strikes = 3

        max_strikes = max(1, max_strikes)

        if violation_count < max_strikes:
            return

        success, msg = await apply_violation_penalty(
            update, context, chat_id, user_id,
            violation_type, penalty_type,
            duration_seconds, lang=lang
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
                'violation_penalty_applied', lang, "🚨 {msg}"
            )

            sent_penalty = await safe_send(
                context.bot, chat_id,
                _fmt(msg_prefix, msg=msg),
                parse_mode='HTML'
            )

            if (sent_penalty is not None
                    and getattr(sent_penalty, 'message_id', None)):
                _spawn_delete_after_delay(
                    context.bot, chat_id,
                    sent_penalty.message_id,
                    PENALTY_MESSAGE_DELETE_DELAY
                )

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
                    context.bot, chat_id, user_id or 0
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
            handler_name = MessageHandlers._PRIVATE_HANDLERS_MAP.get(state)

            if not handler_name:
                return

            handler = getattr(MessageHandlers, handler_name, None)
            if handler is None:
                return

            if _accepts_state_arg(handler, handler_name):
                await handler(update, context, state)
            else:
                await handler(update, context)
        except Exception:
            logger.exception("handle_private error")

    @staticmethod
    async def handle_service(update, context):
        if (
            not update.effective_chat
            or not update.effective_message
        ):
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
                    context.bot, chat_id, message.message_id,
                    context=context,
                )
        except Exception:
            pass

    @staticmethod
    async def handle_join_request(update, context):
        if (
            not update.effective_chat
            or not update.effective_user
        ):
            return

        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        settings = await get_security_settings_cached(chat_id)

        if _as_bool(settings.get('auto_reject_join'), False):
            try:
                await asyncio.sleep(0.05)
                await context.bot.decline_chat_join_request(
                    chat_id, user_id
                )
                return
            except Exception as e:
                logger.warning("decline join: %s", e)

        if _as_bool(settings.get('auto_approve_join'), False):
            try:
                await asyncio.sleep(0.05)
                await context.bot.approve_chat_join_request(
                    chat_id, user_id
                )
            except Exception as e:
                logger.warning("approve join: %s", e)


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
    "_cleanup_log_rate_tracker",
    "shutdown_log_dispatcher",
    "shutdown_delete_tasks",
    "shutdown_bg_tasks",
    "register_shutdown_handlers",
    "FEATURE_LOG_DELETIONS",
    "FEATURE_LOG_PENALTIES",
    "FEATURE_LOG_GIFTS",
    "FEATURE_LOG_ADMIN_CHANGES",
    "SPAM_SCORE_THRESHOLD",
    "_DEFAULT_VIOLATION_MESSAGES",
    "_DEBUG_DIAG",
    "_DEBUG_SPAM",
    "analyze_sentiment",
    "_reset_shutdown_for_tests",
    # v7.14.0 exports
    "_extract_entity_urls",
    "_has_link_entity",
    "_contains_link_enhanced",
    "_has_button_link",
    "_extract_button_link_urls",
    "_extract_url_from_button",
    "_extract_vcard_urls",
    "_extract_venue_url",
    "_strip_combining_marks",
    "_deleet",
    "_merge_split_urls",
    "_has_hidden_chars",
    "_has_domain_pattern",
    "_HOMOGLYPH_MAP",
    "_HIDDEN_CHARS",
    "_LEET_TRANSLATE",
    "_TG_SCHEME_RE",
    "_AT_CHANNEL_RE",
    "_EMAIL_RE",
    "_PUNYCODE_RE",
    "_IPV4_SCHEMELESS_RE",
    "_notify_delete_permission_failure",
]