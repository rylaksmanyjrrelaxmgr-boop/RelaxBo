#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_message_detectors.py - كاشفات ومحلّلات الرسائل (v1.0.0)
================================================================================
استُخرجت من handlers_message.py v7.16.1 لتقليل حجمه.

المحتوى:
    1. Environment flags (ANTIEVASION_*, SPAM, DEBUG)
    2. _MessageContext         — كائن يجمع بيانات الرسالة
    3. Constants               — كل الـ regex patterns والـ keyword sets
    4. Normalizers             — تطبيع النص (homoglyph, combining, leet)
    5. Extractors              — استخراج URLs/buttons/polls/vcards/venues
    6. Link Detection          — كشف الروابط (URL, email, tg://, @channel)
    7. Spam Scoring            — حساب spam score + PostBot detection

⚠️ هذا الملف **لا يستورد** من handlers_message.py (تفادي circular imports).
⚠️ كل الدوال نقية (pure functions) — لا تعتمد على DB/cache/context.
================================================================================
"""

import os
import re
import ipaddress
import unicodedata
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse


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

_ANTIEVASION_ENTITY_LINK = _env_flag("ANTIEVASION_ENTITY_LINK", True)
_ANTIEVASION_BUTTON_LINK = _env_flag("ANTIEVASION_BUTTON_LINK", True)
_ANTIEVASION_SCHEMELESS_URL = _env_flag("ANTIEVASION_SCHEMELESS_URL", True)
_ANTIEVASION_HOMOGLYPH = _env_flag("ANTIEVASION_HOMOGLYPH", True)
_ANTIEVASION_COMBINING = _env_flag("ANTIEVASION_COMBINING", True)
_ANTIEVASION_COMPACT_WORDS = _env_flag("ANTIEVASION_COMPACT_WORDS", True)
_ANTIEVASION_EMOJI_SEPARATOR = _env_flag("ANTIEVASION_EMOJI_SEPARATOR", True)
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
_ANTIEVASION_POLL = _env_flag("ANTIEVASION_POLL", True)
_ANTIEVASION_EMOJI_IN_DOMAIN = _env_flag("ANTIEVASION_EMOJI_IN_DOMAIN", True)
_ANTIEVASION_UNICODE_DOTS = _env_flag("ANTIEVASION_UNICODE_DOTS", True)
_ANTIEVASION_EXTENDED_COMBINING = _env_flag("ANTIEVASION_EXTENDED_COMBINING", True)
_ANTIEVASION_EXTRA_SCRIPTS = _env_flag("ANTIEVASION_EXTRA_SCRIPTS", True)
_ANTIEVASION_ALT_SCHEMES = _env_flag("ANTIEVASION_ALT_SCHEMES", True)


# ═══════════════════════════════════════════════════════════════════
# Public Constants (يستخدمها handlers_message.py)
# ═══════════════════════════════════════════════════════════════════

SPAM_SCORE_THRESHOLD = 5

# 🆕 حجب تلقائي لعينة PostBot عالية الثقة (0-4)
#    ≥ POSTBOT_AUTO_BLOCK_CONFIDENCE → حجب فوري بغض النظر عن الإعداد
POSTBOT_AUTO_BLOCK_CONFIDENCE = 3


# ═══════════════════════════════════════════════════════════════════
# _MessageContext
# ═══════════════════════════════════════════════════════════════════

class _MessageContext:
    """يجمع كل بيانات الرسالة في كائن واحد."""
    __slots__ = (
        'text', 'caption', 'full_text', 'normalized_text',
        'analysis_text',
        'button_count', 'button_urls', 'button_texts', 'button_urls_raw',
        'is_forwarded', 'is_protected', 'has_hint', 'is_auto_fwd',
        'entity_urls', 'has_link_entity', 'button_link_urls',
        'has_any_link', 'has_button_link',
        'vcard_urls', 'venue_url', 'has_hidden_chars',
        'poll_text', 'poll_options_count', 'poll_urls',
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
        self.vcard_urls: List[str] = []
        self.venue_url: str = ""
        self.has_hidden_chars = False
        self.poll_text: str = ""
        self.poll_options_count: int = 0
        self.poll_urls: List[str] = []


# ═══════════════════════════════════════════════════════════════════
# Regex Constants
# ═══════════════════════════════════════════════════════════════════

_EMOJI_SEP_RE = re.compile(
    r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF'
    r'\U0001F000-\U0001F2FF\U000024C2-\U0001F251'
    r'\U0001F900-\U0001F9FF\U0001FA70-\U0001FAFF'
    r'\U00002190-\U000021FF\U00002B00-\U00002BFF'
    r'\U0000FE00-\U0000FE0F\U0001F1E6-\U0001F1FF]',
    re.UNICODE,
)

_HIDDEN_CHARS = (
    '\u200b', '\u200c', '\u200d', '\u200e', '\u200f',
    '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
    '\u2060', '\u2061', '\u2062', '\u2063', '\u2064',
    '\u2066', '\u2067', '\u2068', '\u2069',
    '\u206a', '\u206b', '\u206c', '\u206d', '\u206e', '\u206f',
    '\u180e', '\u3164', '\u2800', '\u115f', '\u1160',
    '\u00ad', '\u034f', '\u17b4', '\u17b5', '\ufeff',
)

_HIDDEN_TRANSLATE_TABLE = {ord(c): None for c in _HIDDEN_CHARS}

_UNICODE_DOT_TABLE = str.maketrans({
    '\u3002': '.', '\uff61': '.', '\uff0e': '.',
    '\ufe52': '.', '\u2024': '.',
})

_WS_RE = re.compile(
    r'[\s\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+'
)

_HOMOGLYPH_MAP = str.maketrans({
    '\u0430': 'a', '\u0431': 'b', '\u0432': 'b', '\u0433': 'r',
    '\u0434': 'd', '\u0435': 'e', '\u0436': 'x', '\u0437': '3',
    '\u0438': 'u', '\u0439': 'u', '\u043a': 'k', '\u043b': 'n',
    '\u043c': 'm', '\u043d': 'h', '\u043e': 'o', '\u043f': 'n',
    '\u0440': 'p', '\u0441': 'c', '\u0442': 't', '\u0443': 'y',
    '\u0444': 'f', '\u0445': 'x', '\u0446': 'u', '\u0447': 'y',
    '\u0448': 'w', '\u0449': 'w', '\u044a': 'b', '\u044b': 'b',
    '\u044c': 'b', '\u044d': 'e', '\u044e': 'o', '\u044f': 'r',
    '\u0456': 'i', '\u0455': 's', '\u0458': 'j', '\u0457': 'i',
    '\u0451': 'e',
    '\u0410': 'A', '\u0411': 'B', '\u0412': 'B', '\u0413': 'R',
    '\u0414': 'D', '\u0415': 'E', '\u0416': 'X', '\u0417': '3',
    '\u0418': 'U', '\u0419': 'U', '\u041a': 'K', '\u041b': 'N',
    '\u041c': 'M', '\u041d': 'H', '\u041e': 'O', '\u041f': 'N',
    '\u0420': 'P', '\u0421': 'C', '\u0422': 'T', '\u0423': 'Y',
    '\u0424': 'F', '\u0425': 'X', '\u0426': 'U', '\u0427': 'Y',
    '\u0428': 'W', '\u0429': 'W', '\u042a': 'B', '\u042b': 'B',
    '\u042c': 'B', '\u042d': 'E', '\u042e': 'O', '\u042f': 'R',
    '\u0406': 'I', '\u0407': 'I', '\u0405': 'S', '\u0408': 'J',
    '\u0401': 'E',
    '\u03b1': 'a', '\u03b2': 'b', '\u03b3': 'y', '\u03b4': 'd',
    '\u03b5': 'e', '\u03b6': 'z', '\u03b7': 'n', '\u03b8': 'o',
    '\u03b9': 'i', '\u03ba': 'k', '\u03bb': 'l', '\u03bc': 'u',
    '\u03bd': 'v', '\u03be': 'e', '\u03bf': 'o', '\u03c0': 'n',
    '\u03c1': 'p', '\u03c2': 's', '\u03c3': 'o', '\u03c4': 't',
    '\u03c5': 'u', '\u03c6': 'f', '\u03c7': 'x', '\u03c8': 'y',
    '\u03c9': 'w',
    '\u0391': 'A', '\u0392': 'B', '\u0393': 'Y', '\u0394': 'A',
    '\u0395': 'E', '\u0396': 'Z', '\u0397': 'H', '\u0398': 'O',
    '\u0399': 'I', '\u039a': 'K', '\u039b': 'L', '\u039c': 'M',
    '\u039d': 'N', '\u039e': 'E', '\u039f': 'O', '\u03a0': 'N',
    '\u03a1': 'P', '\u03a3': 'S', '\u03a4': 'T', '\u03a5': 'Y',
    '\u03a6': 'F', '\u03a7': 'X', '\u03a8': 'Y', '\u03a9': 'W',
})

_LEET_TRANSLATE = str.maketrans({
    '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's',
    '7': 't', '8': 'b', '9': 'g',
})

_LEET_CANDIDATE_RE = re.compile(
    r'\b(?=[a-z0-9]*[a-z])(?=[a-z0-9]*[0-9])[a-z0-9]{3,}\b',
    re.IGNORECASE,
)

_COMBINING_MARKS_RANGE = frozenset(
    list(range(0x0300, 0x0370))
    + list(range(0x1AB0, 0x1B00))
    + list(range(0x1DC0, 0x1E00))
    + list(range(0x20D0, 0x2100))
    + list(range(0xFE20, 0xFE30))
)

_LATIN_RANGE = frozenset(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
)

_TRUE_STRINGS = frozenset({
    "1", "true", "yes", "on", "enabled", "enable", "y",
    "نعم", "مفعل", "مفعّل",
})

_FALSE_STRINGS = frozenset({
    "0", "false", "no", "off", "disabled", "disable", "n",
    "لا", "غير مفعل", "غير مفعّل",
})


# ═══════════════════════════════════════════════════════════════════
# Link Regex Constants
# ═══════════════════════════════════════════════════════════════════

_URL_RE = re.compile(r'https?://[^\s<>"]+', re.IGNORECASE)

_ALT_SCHEME_RE = re.compile(
    r'\b(?:hxxps?|ftps?|magnet|mailto|tel|sms|file):[^\s<>"]+',
    re.IGNORECASE,
)

_DOMAIN_HTTP_RE = re.compile(
    r'(?:https?://|hxxps?://|ftps?://|www\.|t\.me/|telegram\.me/)\S+',
    re.IGNORECASE,
)

_TG_SCHEME_RE = re.compile(r'\btg://\S+', re.IGNORECASE)

_AT_CHANNEL_RE = re.compile(
    r'(?<![\w@/])@([A-Za-z][A-Za-z0-9_]{4,31})(?![\w@])',
)

_EMAIL_RE = re.compile(
    r'(?<![\w.\-])[\w.\-+]{1,64}@'
    r'(?:[a-z0-9\-]{1,63}\.)+[a-z]{2,24}(?![\w\-])',
    re.IGNORECASE,
)

_PUNYCODE_RE = re.compile(
    r'(?<![\w\-])xn--[a-z0-9\-]{2,}(?:\.[a-z0-9\-]+)*',
    re.IGNORECASE,
)

_IPV4_SCHEMELESS_RE = re.compile(
    r'(?<![\w.\-])(?:\d{1,3}\.){3}\d{1,3}'
    r'(?::\d{1,5})?(?:/[^\s<>"\']*)?(?![\w.\-])',
)

_TLD_PATTERN = (
    r'com|net|org|edu|gov|mil|int|info|biz|name|mobi|asia|xxx|tel|'
    r'travel|jobs|cat|coop|aero|pro|museum|'
    r'io|ai|co|me|tv|cc|app|dev|xyz|top|site|website|space|store|club|'
    r'live|life|world|online|shop|blog|wiki|win|cloud|host|tech|fun|'
    r'link|click|work|today|news|media|agency|company|solutions|'
    r'fyi|zip|mov|re|yt|be|nu|im|st|am|is|it|'
    r'ly|at|gg|gy|sh|to|so|pw|su|gd|vc|ws|tk|ml|ga|cf|gq|'
    r'ru|uk|de|fr|es|nl|pl|tr|jp|cn|in|br|mx|ar|ir|sa|ae|eg|ma|dz|'
    r'pk|bd|id|th|vn|ph|my|sg|hk|kr|tw|'
    r'us|ca|au|nz|za|ng|ke|gh|tz|ug|zw|zm|'
    r'ch|se|no|dk|fi|ie|pt|gr|cz|sk|hu|ro|bg|hr|si|rs|ua|by|'
    r'lt|lv|ee|md|al|mk|ba|il|jo|lb|sy|iq|kw|qa|bh|om|ye|sd|tn'
)

_COMMON_FILE_EXTS = frozenset({
    'txt', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz',
    'png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg', 'webp', 'ico',
    'mp3', 'mp4', 'wav', 'ogg', 'flac', 'avi', 'mkv', 'mov', 'webm',
    'py', 'js', 'ts', 'java', 'cpp', 'c', 'h', 'rb', 'go', 'rs', 'php',
    'html', 'css', 'scss', 'json', 'xml', 'yaml', 'yml', 'toml', 'ini',
    'md', 'rst', 'csv', 'tsv', 'log', 'bat', 'ps1',
    'exe', 'dll', 'so', 'dylib', 'apk', 'ipa', 'deb', 'rpm',
})

_SCHEMELESS_DOMAIN_RE = re.compile(
    r'(?<![\w@/])'
    r'(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?'
    r'\.(?:' + _TLD_PATTERN + r')'
    r'(?::\d{1,5})?'
    r'(?:/[^\s<>"\']+|(?=\s|$|[,،.!?;:\)\]])))',
    re.IGNORECASE,
)

_SPLIT_URL_RE = re.compile(
    r'((?:https?://|hxxps?://|www\.)?'
    r'[a-z0-9][a-z0-9\-\.]*?)'
    r'\s*\n\s*'
    r'(\.[a-z0-9\-][a-z0-9\-\.]*(?:/[^\s<>"\']*)?)',
    re.IGNORECASE,
)

_ENTITY_LINK_TYPES = frozenset({'url', 'text_link'})
_ENTITY_URL_TYPES = frozenset({'url', 'text_link'})


# ═══════════════════════════════════════════════════════════════════
# Spam Constants
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

_WORD_SEP_CLASS = r'[\s\-_.|/*+=~^´`°•●○◦▪▫■□♦♢※]'
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]*", re.IGNORECASE)
_CAPS_WORD_RE = re.compile(r'\b[A-Z]{4,}\b')

_SPAM_CONTEXT_PATTERNS = (
    (re.compile(
        r'\buncensored\s+(?:best\s+)?(?:collection|archive|pack|clips?)\b',
        re.IGNORECASE,
    ), 4, "uncensored+collection"),
    (re.compile(
        r'\b(?:xxx|nsfw|porn)\s+(?:collection|archive|pack|clips?)\b',
        re.IGNORECASE,
    ), 4, "adult+collection"),
    (re.compile(
        r'\b(?:leak|leaked)\s+(?:pack|archive|collection|clips?)\b',
        re.IGNORECASE,
    ), 4, "leak+pack"),
    (re.compile(
        r'\b(?:click|tap|check|view|open)\s+(?:here|now|below)\b',
        re.IGNORECASE,
    ), 2, "cta_phrase"),
    (re.compile(
        r'\b(?:best|fresh|hot|wild|viral)\s+'
        r'(?:collection|clips?|pack|archive)\b',
        re.IGNORECASE,
    ), 3, "promo_collection"),
    (re.compile(
        r'\b(?:mega|huge|massive)\s+(?:pack|archive|collection|drop)\b',
        re.IGNORECASE,
    ), 3, "mega_promo"),
    (re.compile(
        r'\b(?:viral|leak|leaked)\b.{0,35}\b(?:view|open|click|tap|check)\b',
        re.IGNORECASE,
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
    re.UNICODE,
)

_POSTBOT_PATTERN_LOOSE = re.compile(
    _POSTBOT_EMOJI + r'.{0,10}'
    + r'\b[A-Z]{4,}(?:\s+[A-Z]{4,}){1,}',
    re.UNICODE,
)

_POSTBOT_BUTTON_PATTERN = re.compile(
    r'\b(?:view|open|watch|click|tap|viral|leak|'
    r'content|download|join|subscribe)\b',
    re.IGNORECASE,
)

_POSTBOT_HARD_KEYWORDS = re.compile(
    r'\b(?:viral|leak|mega|pack|clips?|uncensored|nsfw)\b',
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

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
# Normalizers
# ═══════════════════════════════════════════════════════════════════

def _strip_combining_marks(text: str) -> str:
    if not text:
        return text
    try:
        return ''.join(c for c in text if ord(c) not in _COMBINING_MARKS_RANGE)
    except Exception:
        return text


def _deleet(text: str) -> str:
    if not text:
        return text
    try:
        def _replace(m):
            return m.group(0).lower().translate(_LEET_TRANSLATE)
        return _LEET_CANDIDATE_RE.sub(_replace, text)
    except Exception:
        return text


def _apply_homoglyphs_safe(text: str) -> str:
    if not text or not _ANTIEVASION_HOMOGLYPH:
        return text
    try:
        has_latin = any(c in _LATIN_RANGE for c in text)
        has_cyr = any('\u0400' <= c <= '\u04FF' for c in text)
        has_grk = any('\u0370' <= c <= '\u03FF' for c in text)
        if has_latin and (has_cyr or has_grk):
            return text.translate(_HOMOGLYPH_MAP)
        return text
    except Exception:
        return text


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    try:
        text = unicodedata.normalize('NFKC', text)
    except Exception:
        pass
    if _ANTIEVASION_UNICODE_DOTS:
        try:
            text = text.translate(_UNICODE_DOT_TABLE)
        except Exception:
            pass
    text = text.translate(_HIDDEN_TRANSLATE_TABLE)
    try:
        text = _apply_homoglyphs_safe(text)
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


def _strip_emoji_for_domain(text: str) -> str:
    if not text or not _ANTIEVASION_EMOJI_IN_DOMAIN:
        return text
    try:
        return _EMOJI_SEP_RE.sub('', text)
    except Exception:
        return text


def _has_hidden_chars(text: str) -> bool:
    if not text:
        return False
    try:
        return any(c in text for c in _HIDDEN_CHARS)
    except Exception:
        return False


def _merge_split_urls(text: str) -> str:
    if not text or not _ANTIEVASION_MULTILINE_URL:
        return text
    if '\n' not in text:
        return text
    try:
        for _ in range(3):
            new_text = _SPLIT_URL_RE.sub(r'\1\2', text)
            if new_text == text:
                break
            text = new_text
    except Exception:
        pass
    return text


# ═══════════════════════════════════════════════════════════════════
# Extractors
# ═══════════════════════════════════════════════════════════════════

def _extract_entity_urls(message, depth: int = 0) -> List[str]:
    urls: List[str] = []
    if message is None or depth > 4:
        return urls
    try:
        for attr in ('entities', 'caption_entities'):
            ents = getattr(message, attr, None) or []
            for e in ents:
                try:
                    if getattr(e, 'type', None) not in _ENTITY_LINK_TYPES:
                        continue
                    u = getattr(e, 'url', None)
                    if isinstance(u, str) and u:
                        urls.append(u)
                except Exception:
                    continue
    except Exception:
        pass
    if depth < 4:
        try:
            rtm = getattr(message, 'reply_to_message', None)
            if rtm is not None:
                urls.extend(_extract_entity_urls(rtm, depth + 1))
        except Exception:
            pass
    return urls


def _has_link_entity(message) -> bool:
    if not _ANTIEVASION_ENTITY_LINK or message is None:
        return False
    try:
        for attr in ('entities', 'caption_entities'):
            for e in (getattr(message, attr, None) or []):
                try:
                    if getattr(e, 'type', None) in _ENTITY_URL_TYPES:
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def _extract_url_from_button(button) -> List[str]:
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
                try:
                    urls.extend(_extract_url_from_button(button))
                except Exception:
                    pass
    except Exception:
        pass
    return count, urls, texts


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
        for m in re.finditer(
            r'(?im)^URL(?:;[^:\r\n]*)?[:;]\s*([^\r\n]+)$', vcard,
        ):
            u = m.group(1).strip()
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
        u = getattr(venue, 'url', None)
        if isinstance(u, str) and u:
            return u
        for field in ('title', 'address'):
            v = getattr(venue, field, None)
            if isinstance(v, str) and v:
                if _DOMAIN_HTTP_RE.search(v):
                    return v
                if _has_domain_pattern(v):
                    return v
    except Exception:
        pass
    return ""


def _extract_poll_text(message) -> Tuple[str, int, List[str]]:
    if not _ANTIEVASION_POLL:
        return "", 0, []
    try:
        poll = getattr(message, 'poll', None)
        if poll is None:
            return "", 0, []
        parts: List[str] = []
        urls: List[str] = []
        q = getattr(poll, 'question', None)
        if q:
            parts.append(str(q))
            if _DOMAIN_HTTP_RE.search(str(q)):
                urls.append(str(q))
        opts = getattr(poll, 'options', None) or []
        for o in opts:
            t = getattr(o, 'text', None)
            if t:
                parts.append(str(t))
                if _DOMAIN_HTTP_RE.search(str(t)):
                    urls.append(str(t))
        expl = getattr(poll, 'explanation', None)
        if expl:
            parts.append(str(expl))
            if _DOMAIN_HTTP_RE.search(str(expl)):
                urls.append(str(expl))
        return " ".join(parts), len(opts), urls
    except Exception:
        return "", 0, []


def _extract_spam_words(text: str) -> List[str]:
    if not text:
        return []
    try:
        regular = [m.group(0).lower() for m in _WORD_RE.finditer(text)]
        if not _ANTIEVASION_EMOJI_SEPARATOR:
            return list(set(regular))
        no_emoji = _EMOJI_SEP_RE.sub('', text)
        fully_compact = re.sub(r'[^a-zA-Z0-9]', '', no_emoji).lower()
        compact_words = re.findall(r'[a-z]{3,}', fully_compact)
        spaced_compact = re.sub(_WORD_SEP_CLASS, ' ', no_emoji)
        spaced_compact = re.sub(r'[^a-zA-Z0-9 ]', ' ', spaced_compact)
        spaced_words = [
            w.lower() for w in spaced_compact.split() if len(w) >= 3
        ]
        return list(set(regular + compact_words + spaced_words))
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════
# Link Detection
# ═══════════════════════════════════════════════════════════════════

def _has_domain_pattern(text: str) -> bool:
    if not text:
        return False
    try:
        cleaned = _strip_emoji_for_domain(text)
        cleaned = cleaned.translate(_HIDDEN_TRANSLATE_TABLE)
        for m in _SCHEMELESS_DOMAIN_RE.finditer(cleaned):
            full = m.group(0).lower()
            if '/' not in full and ':' not in full:
                ext = full.rsplit('.', 1)[-1].split('?')[0]
                if ext in _COMMON_FILE_EXTS:
                    continue
            return True
    except Exception:
        pass
    return False


def _contains_link_enhanced(text: str) -> bool:
    if not text:
        return False
    try:
        if _DOMAIN_HTTP_RE.search(text):
            return True
        if _ANTIEVASION_ALT_SCHEMES:
            if _ALT_SCHEME_RE.search(text):
                return True
        if _ANTIEVASION_SCHEMELESS_URL:
            if _has_domain_pattern(text):
                return True
        if _ANTIEVASION_TG_SCHEME:
            if _TG_SCHEME_RE.search(text):
                return True
        if _ANTIEVASION_PUNYCODE:
            if _PUNYCODE_RE.search(text):
                return True
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


def _contains_email(text: str) -> bool:
    if not text or not _ANTIEVASION_EMAIL:
        return False
    try:
        return bool(_EMAIL_RE.search(text))
    except Exception:
        return False


def _contains_at_channel(text: str) -> bool:
    if not text or not _ANTIEVASION_AT_CHANNEL:
        return False
    try:
        return bool(_AT_CHANNEL_RE.search(text))
    except Exception:
        return False


def _contains_tg_scheme(text: str) -> bool:
    if not text or not _ANTIEVASION_TG_SCHEME:
        return False
    try:
        return bool(_TG_SCHEME_RE.search(text))
    except Exception:
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
            if _ANTIEVASION_ALT_SCHEMES and _ALT_SCHEME_RE.search(url):
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
            elif _ANTIEVASION_ALT_SCHEMES and _ALT_SCHEME_RE.search(url):
                result.append(url)
    except Exception:
        pass
    return result


# ═══════════════════════════════════════════════════════════════════
# Analysis Text Builders
# ═══════════════════════════════════════════════════════════════════

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
    for attr in ('text', 'caption'):
        try:
            v = getattr(message, attr, None)
            if v:
                parts.append(str(v))
        except Exception:
            pass
    try:
        _, _, bts = _extract_button_context(message)
        if bts:
            parts.extend(bts)
    except Exception:
        pass
    try:
        for u in _extract_entity_urls(message):
            parts.append(str(u))
    except Exception:
        pass
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
    try:
        pt, _, _ = _extract_poll_text(message)
        if pt:
            parts.append(pt)
    except Exception:
        pass
    return _normalize_text(" ".join(parts))


# ═══════════════════════════════════════════════════════════════════
# Spam Scoring
# ═══════════════════════════════════════════════════════════════════

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
    if _analysis_text is not None:
        analysis_text = _analysis_text
    elif button_texts:
        button_text_joined = _normalize_text(" ".join(button_texts))
        analysis_text = (
            f"{normalized} {button_text_joined}".strip()
            if normalized else button_text_joined
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

    # PostBot boost BEFORE other scoring
    try:
        _pb_conf = _postbot_pattern_confidence(
            analysis_text,
            button_count=button_count,
            has_urls=bool(button_urls) or bool(_entity_urls),
        )
        if _pb_conf >= 2:
            _pb_boost = _pb_conf * 2
            score += _pb_boost
            reasons.append(f"postbot_conf={_pb_conf}(+{_pb_boost})")
    except Exception:
        pass

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
        score = min(max(score, 0), 30)
    except Exception:
        return 0, []
    return score, reasons


# ═══════════════════════════════════════════════════════════════════
# PostBot Detection
# ═══════════════════════════════════════════════════════════════════

def _is_postbot_pattern(
    text: str, *, button_count: int = 0, has_urls: bool = False
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


def _postbot_pattern_confidence(
    text: str, *, button_count: int = 0, has_urls: bool = False
) -> int:
    """
    قياس شدة مطابقة PostBot (0-4).

    0 = لا تطابق
    1 = ضعيف (تجاهل)
    2 = متوسط (boost في spam_score)
    3 = قوي (auto-block حتى لو الإعداد معطّل)
    4 = قوي جداً (auto-block مضمون)
    """
    if not text or len(text) < 10:
        return 0

    confidence = 0

    # +1 لو طابق النمط الأساسي
    try:
        if _POSTBOT_PATTERN.search(text):
            confidence += 1
    except Exception:
        pass

    # +1 لو طابق النمط المرن
    try:
        if _POSTBOT_PATTERN_LOOSE.search(text):
            confidence += 1
    except Exception:
        pass

    # +1 لو كلمات hard موجودة
    try:
        hard_matches = _POSTBOT_HARD_KEYWORDS.findall(text)
        if len(hard_matches) >= 2:
            confidence += 1
        elif len(hard_matches) >= 1 and button_count >= 2:
            confidence += 1
    except Exception:
        pass

    # +1 لو CAPS words كثيرة
    try:
        caps_matches = _CAPS_WORD_RE.findall(text)
        if len(caps_matches) >= 3:
            confidence += 1
        elif len(caps_matches) >= 2 and button_count >= 2:
            confidence += 1
    except Exception:
        pass

    # +1 لو أزرار كثيرة
    if button_count >= 3:
        confidence += 1
    elif button_count >= 2 and has_urls:
        confidence += 1

    return min(confidence, 4)


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

__all__ = [
    # Constants
    "SPAM_SCORE_THRESHOLD",
    "POSTBOT_AUTO_BLOCK_CONFIDENCE",
    # Context
    "_MessageContext",
    # Env flags (للاستخدام الاختياري)
    "_DEBUG_DIAG",
    "_DEBUG_SPAM",
    # Helpers
    "_env_flag",
    "_as_bool",
    # Normalizers
    "_strip_combining_marks",
    "_deleet",
    "_apply_homoglyphs_safe",
    "_normalize_text",
    "_strip_emoji_for_domain",
    "_has_hidden_chars",
    "_merge_split_urls",
    # Extractors
    "_extract_entity_urls",
    "_has_link_entity",
    "_extract_url_from_button",
    "_extract_button_context",
    "_extract_vcard_urls",
    "_extract_venue_url",
    "_extract_poll_text",
    "_extract_spam_words",
    # Link detection
    "_has_domain_pattern",
    "_contains_link_enhanced",
    "_contains_email",
    "_contains_at_channel",
    "_contains_tg_scheme",
    "_has_button_link",
    "_extract_button_link_urls",
    # Analysis text
    "_get_message_button_data",
    "_get_message_button_texts",
    "_get_message_analysis_text",
    # Spam scoring
    "_count_unique_matches",
    "_count_text_urls",
    "_compute_spam_score",
    # PostBot
    "_is_postbot_pattern",
    "_postbot_pattern_confidence",
    # Constants for reuse
    "_HOMOGLYPH_MAP",
    "_HIDDEN_CHARS",
    "_HIDDEN_TRANSLATE_TABLE",
    "_UNICODE_DOT_TABLE",
    "_LEET_TRANSLATE",
    "_TG_SCHEME_RE",
    "_AT_CHANNEL_RE",
    "_EMAIL_RE",
    "_PUNYCODE_RE",
    "_IPV4_SCHEMELESS_RE",
    "_ALT_SCHEME_RE",
    "_POSTBOT_PATTERN",
    "_POSTBOT_PATTERN_LOOSE",
    "_POSTBOT_HARD_KEYWORDS",
    "_EMOJI_SEP_RE",
    "_TLD_PATTERN",
    "_COMMON_FILE_EXTS",
    "_SPAM_EMOJIS",
    "_SPAM_STRONG_KEYWORDS",
    "_SPAM_MEDIUM_KEYWORDS",
    "_SPAM_CONTEXT_KEYWORDS",
    "_CTA_KEYWORDS",
    "_SPAM_CONTEXT_PATTERNS",
]