#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_message_detectors.py
===============================================================================
🛡️ Relax Manager — Advanced Spam / Anti-Evasion Detection Engine
Version: 2.2.0 HARDENED+

محرك كشف مستقل عن handlers_message.py.

v2.2.0:
    ✅ الحفاظ على API والدوال العامة الموجودة في v2.1.x
    ✅ Unicode normalization + casefold
    ✅ كشف Zero-width / Bidi / control characters
    ✅ كشف Homoglyph / Leetspeak
    ✅ إعادة بناء الروابط المفككة
    ✅ كشف hxxp / spaced schemes / dot obfuscation
    ✅ كشف Telegram links / usernames / invites
    ✅ تحليل Entity URLs / Button URLs / WebApp / LoginURL
    ✅ تحليل Poll / vCard / forwarded messages
    ✅ Contextual spam scoring
    ✅ Multi-signal scoring
    ✅ URL-density analysis
    ✅ CTA-density analysis
    ✅ character / digit / symbol density
    ✅ repeated-token detection
    ✅ split-word evasion
    ✅ suspicious-script detection
    ✅ compact/fingerprint-style evasion detection
    ✅ false-positive guards
    ✅ fail-safe exception handling
    ✅ v2.2.0.b: سطر تشخيصي عند التحميل (Load beacon)

مهم:
    هذا الملف لا يحذف ولا يحظر المستخدم.
    هو محرك تحليل فقط.

التوافق:
    يحافظ على أسماء الدوال العامة الموجودة في v2.0/v2.1.
===============================================================================
"""

from __future__ import annotations

import html
import logging
import os
import re
import unicodedata
from collections import Counter
from typing import Any, Iterable, List, Optional, Sequence, Tuple


# =============================================================================
# LOAD BEACON (v2.2.0.b)
# =============================================================================

logger = logging.getLogger(__name__)

_DETECTORS_VERSION = "2.2.0 HARDENED+"


# =============================================================================
# ENVIRONMENT
# =============================================================================

def _env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None:
        return default

    value = value.strip().lower()

    if value in {
        "1", "true", "yes", "y", "on",
        "enable", "enabled",
    }:
        return True

    if value in {
        "0", "false", "no", "n", "off",
        "disable", "disabled",
    }:
        return False

    return default


DEBUG_DIAG = _env_bool("DEBUG_DIAG", False)
DEBUG_SPAM = _env_bool("DEBUG_SPAM", False)

ANTIEVASION_ENTITY_LINK = _env_bool(
    "ANTIEVASION_ENTITY_LINK", True
)
ANTIEVASION_BUTTON_LINK = _env_bool(
    "ANTIEVASION_BUTTON_LINK", True
)
ANTIEVASION_SCHEMELESS_URL = _env_bool(
    "ANTIEVASION_SCHEMELESS_URL", True
)
ANTIEVASION_HOMOGLYPH = _env_bool(
    "ANTIEVASION_HOMOGLYPH", True
)
ANTIEVASION_COMBINING = _env_bool(
    "ANTIEVASION_COMBINING", True
)
ANTIEVASION_COMPACT_WORDS = _env_bool(
    "ANTIEVASION_COMPACT_WORDS", True
)
ANTIEVASION_EMOJI_SEPARATOR = _env_bool(
    "ANTIEVASION_EMOJI_SEPARATOR", True
)
ANTIEVASION_BUTTON_WEBAPP = _env_bool(
    "ANTIEVASION_BUTTON_WEBAPP", True
)
ANTIEVASION_BUTTON_LOGINURL = _env_bool(
    "ANTIEVASION_BUTTON_LOGINURL", True
)
ANTIEVASION_LEETSPEAK = _env_bool(
    "ANTIEVASION_LEETSPEAK", True
)
ANTIEVASION_TG_SCHEME = _env_bool(
    "ANTIEVASION_TG_SCHEME", True
)
ANTIEVASION_AT_CHANNEL = _env_bool(
    "ANTIEVASION_AT_CHANNEL", True
)
ANTIEVASION_EMAIL = _env_bool(
    "ANTIEVASION_EMAIL", True
)
ANTIEVASION_PUNYCODE = _env_bool(
    "ANTIEVASION_PUNYCODE", True
)
ANTIEVASION_IPV4_SCHEMELESS = _env_bool(
    "ANTIEVASION_IPV4_SCHEMELESS", True
)
ANTIEVASION_MULTILINE_URL = _env_bool(
    "ANTIEVASION_MULTILINE_URL", True
)
ANTIEVASION_VENUE_VCARD = _env_bool(
    "ANTIEVASION_VENUE_VCARD", True
)
ANTIEVASION_POLL = _env_bool(
    "ANTIEVASION_POLL", True
)
ANTIEVASION_EMOJI_IN_DOMAIN = _env_bool(
    "ANTIEVASION_EMOJI_IN_DOMAIN", True
)
ANTIEVASION_UNICODE_DOTS = _env_bool(
    "ANTIEVASION_UNICODE_DOTS", True
)
ANTIEVASION_EXTENDED_COMBINING = _env_bool(
    "ANTIEVASION_EXTENDED_COMBINING", True
)
ANTIEVASION_EXTRA_SCRIPTS = _env_bool(
    "ANTIEVASION_EXTRA_SCRIPTS", True
)
ANTIEVASION_ALT_SCHEMES = _env_bool(
    "ANTIEVASION_ALT_SCHEMES", True
)


# =============================================================================
# THRESHOLDS
# =============================================================================

SPAM_SCORE_THRESHOLD = 5
POSTBOT_AUTO_BLOCK_CONFIDENCE = 3
SPAM_HARD_THRESHOLD = 10
SPAM_CRITICAL_THRESHOLD = 15
MAX_SPAM_SCORE = 40

# v2.2 additional safety limits
MAX_ANALYSIS_TEXT_LENGTH = 12000
MAX_REASON_COUNT = 80


# =============================================================================
# HIDDEN / BIDI / UNICODE
# =============================================================================

_HIDDEN_CHARS = {
    "\x00", "\x01", "\x02", "\x03",
    "\x04", "\x05", "\x06", "\x07",
    "\x08", "\x0b", "\x0c", "\x0e",
    "\x0f", "\x10", "\x11", "\x12",
    "\x13", "\x14", "\x15", "\x16",
    "\x17", "\x18", "\x19", "\x1a",
    "\x1b", "\x1c", "\x1d", "\x1e",
    "\x1f", "\x7f",

    "\u061c",
    "\u115f",
    "\u1160",
    "\u17b4",
    "\u17b5",
    "\u180e",

    "\u200b", "\u200c", "\u200d",
    "\u200e", "\u200f",

    "\u202a", "\u202b", "\u202c",
    "\u202d", "\u202e",

    "\u2060", "\u2061", "\u2062",
    "\u2063", "\u2064", "\u2065",
    "\u2066", "\u2067", "\u2068",
    "\u2069",

    "\u206a", "\u206b", "\u206c",
    "\u206d", "\u206e", "\u206f",

    "\ufeff",
}

_BIDI_CHARS = {
    "\u061c",
    "\u200e",
    "\u200f",
    "\u202a",
    "\u202b",
    "\u202c",
    "\u202d",
    "\u202e",
    "\u2066",
    "\u2067",
    "\u2068",
    "\u2069",
}

_COMBINING_RANGES = (
    (0x0300, 0x036F),
    (0x1AB0, 0x1AFF),
    (0x1DC0, 0x1DFF),
    (0x20D0, 0x20FF),
    (0xFE20, 0xFE2F),
)


# =============================================================================
# HOMOGLYPHS
# =============================================================================

_HOMOGLYPH_MAP = {
    "А": "A", "В": "B", "С": "C",
    "Е": "E", "Н": "H", "І": "I",
    "Ј": "J", "К": "K", "М": "M",
    "О": "O", "Р": "P", "Ѕ": "S",
    "Т": "T", "Х": "X", "Ү": "Y",

    "а": "a", "е": "e", "о": "o",
    "р": "p", "с": "c", "у": "y",
    "х": "x", "і": "i", "ј": "j",
    "к": "k", "м": "m", "т": "t",

    "Α": "A", "Β": "B", "Ε": "E",
    "Η": "H", "Ι": "I", "Κ": "K",
    "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Χ": "X",
    "Υ": "Y", "Ζ": "Z",

    "α": "a", "β": "b", "ε": "e",
    "η": "h", "ι": "i", "κ": "k",
    "μ": "m", "ν": "n", "ο": "o",
    "ρ": "p", "τ": "t", "χ": "x",
    "υ": "y", "ζ": "z",
}


# =============================================================================
# LEETSPEAK
# =============================================================================

_LEET_MAP = str.maketrans({
    "0": "o",
    "1": "i",
    "2": "z",
    "3": "e",
    "4": "a",
    "5": "s",
    "6": "g",
    "7": "t",
    "8": "b",
    "9": "g",
    "@": "a",
    "$": "s",
})


# =============================================================================
# REGEX
# =============================================================================

_URL_RE = re.compile(
    r"(?i)\b(?:https?|ftp)://[^\s<>()\"']+"
)

_DOMAIN_RE = re.compile(
    r"(?i)"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}"
)

_DOMAIN_HTTP_RE = re.compile(
    r"(?i)\b(?:https?://)?"
    r"(?:www\.)?"
    r"(?:[a-z0-9-]+\.)+[a-z]{2,63}"
    r"(?:/[^\s<>()]*)?"
)

_EMAIL_RE = re.compile(
    r"(?i)\b"
    r"[a-z0-9._%+\-]+"
    r"@"
    r"[a-z0-9.\-]+"
    r"\.[a-z]{2,63}\b"
)

_IPV4_RE = re.compile(
    r"\b"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}"
    r"\b"
)

_PUNYCODE_RE = re.compile(
    r"(?i)\bxn--[a-z0-9-]+"
)

_TG_SCHEME_RE = re.compile(
    r"(?i)\b(?:tg|telegram):(?:/[^\s]+|[^\s]+)"
)

_TG_URL_RE = re.compile(
    r"(?i)"
    r"(?:https?://)?(?:www\.)?"
    r"(?:t\.me|telegram\.me|telegram\.dog)"
    r"(?:/[^\s<>()]+)?"
)

_TG_INVITE_RE = re.compile(
    r"(?i)"
    r"(?:t\.me/)?"
    r"(?:joinchat/|\+)[A-Za-z0-9_-]{4,}"
)

_TG_USERNAME_RE = re.compile(
    r"(?<![\w@])@(?:[A-Za-z0-9_]{5,32})(?!\w)"
)

_ALT_SCHEME_RE = re.compile(
    r"(?i)\b"
    r"(?:hxxp|hxxps|ttp|ttps|htp|httpx|httpsx)"
    r"[:/\\]+"
)

_SPACED_SCHEME_RE = re.compile(
    r"(?i)\bh\s*t\s*t\s*p\s*s?\s*[:./\\]"
)

_SPACED_TG_RE = re.compile(
    r"(?i)"
    r"\bt\s*[\.\[\(\{]?\s*m\s*"
    r"[\.\]\)\}]?\s*e\b"
)

_DOT_DOMAIN_RE = re.compile(
    r"(?i)"
    r"\b[a-z0-9_-]{2,50}"
    r"(?:\s*(?:dot|\[\.\]|\(\.\)|\{\.\})\s*)"
    r"(?:com|net|org|io|me|co|cc|xyz|top|site|online|live|vip|pro|info)\b"
)

_SPACED_DOMAIN_RE = re.compile(
    r"(?i)"
    r"\b[a-z0-9_-]{2,50}"
    r"(?:\s*[.\u2024\u2025\u2026\u3002\uFE52\uFF0E]\s*)"
    r"[a-z]{2,63}\b"
)

_DOT_LIKE_RE = re.compile(
    r"(?i)"
    r"(?:\[\s*\.\s*\]"
    r"|\(\s*\.\s*\)"
    r"|\{\s*\.\s*\}"
    r"|\[\s*dot\s*\]"
    r"|\(\s*dot\s*\)"
    r"|\{\s*dot\s*\})"
)

_NUMBER_PROMO_RE = re.compile(
    r"(?i)\b"
    r"(?:\d{2,7}\s*\+?\s*"
    r"(?:clips?|videos?|pics?|photos?|files?|items?|مقطع|مقاطع|فيديوهات?))"
    r"\b"
)

_PACK_RE = re.compile(
    r"(?i)\b"
    r"(?:mega|huge|massive|full|exclusive)?"
    r"[\s_-]*pack(?:age|s)?\b"
)

_REPEATED_CHAR_RE = re.compile(
    r"(.)\1{4,}",
    re.UNICODE,
)

_REPEATED_WORD_RE = re.compile(
    r"(?i)\b(\w{2,40})(?:\s+\1){2,}\b"
)

_SEPARATOR_RE = re.compile(
    r"(?:"
    r"[\W_]{4,}"
    r"|(?:[a-z]\W){4,}[a-z]"
    r")",
    re.IGNORECASE,
)

# New v2.2 patterns
_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:\+?\d[\d\s().-]{7,18}\d)"
    r"(?!\d)"
)

_PERCENT_SYMBOL_RE = re.compile(
    r"[^\w\s]{6,}",
    re.UNICODE,
)

_MULTISPACE_SPLIT_RE = re.compile(
    r"(?i)"
    r"\b(?:[a-z]\s+){3,}[a-z]\b"
)

_EMOJI_SPLIT_RE = re.compile(
    r"(?i)"
    r"\b(?:[a-z]\s*[\U0001F000-\U0001FAFF]\s*){3,}[a-z]\b"
)

# Very long domain labels can be suspicious.
_LONG_DOMAIN_LABEL_RE = re.compile(
    r"(?i)"
    r"\b[a-z0-9-]{35,}\.[a-z]{2,63}\b"
)


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
    "clips", "drop", "leak", "viral", "fresh",
    "new",
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
    "😏", "🔞", "⚡", "💎", "🎁", "🤑",
    "💯",
}


# =============================================================================
# CONTEXT PATTERNS
# =============================================================================

_PROMO_CONTEXT_PATTERNS = [
    re.compile(
        r"(?i)\b(?:mega|huge|massive|exclusive)"
        r"\s*[- ]?\s*pack\b"
    ),
    re.compile(
        r"(?i)\b\d{2,7}\s*\+\s*"
        r"(?:clips?|videos?|pics?|photos?)\b"
    ),
    re.compile(
        r"(?i)\b(?:viral|leak(?:ed)?|exclusive)\b"
        r".{0,100}"
        r"\b(?:content|clips?|pack|collection|archive)\b"
    ),
    re.compile(
        r"(?i)\b(?:view|open|click|tap|watch|check)\b"
        r".{0,70}"
        r"\b(?:leak|content|pack|collection|archive)\b"
    ),
    re.compile(
        r"(?i)\b(?:join|subscribe|download|unlock)\b"
        r".{0,70}"
        r"\b(?:private|exclusive|premium|content)\b"
    ),
    re.compile(
        r"(?:اضغط|شاهد|ادخل|افتح|تحميل)"
        r".{0,70}"
        r"(?:محتوى|تسريب|حصري|مجموعة|فيديو|مقاطع)"
    ),
]


_POSTBOT_REGEXES = [
    re.compile(
        r"(?i)"
        r"(?:🔥|💥|🚀|👉|💦|🔞|⚡)"
        r".{0,40}"
        r"\b(?:view|open|click|tap|watch)\b"
    ),
    re.compile(
        r"(?i)"
        r"\b(?:mega|exclusive|viral|leak|premium)\b"
        r".{0,70}"
        r"(?:🔥|💥|👉|💦|🔞)"
    ),
    re.compile(
        r"(?i)"
        r"\b(?:mega\s*pack|pack)\b"
        r".{0,70}"
        r"\b\d{2,7}\+?\b"
    ),
]


# =============================================================================
# GENERIC HELPERS
# =============================================================================

def _unique_strings(
    values: Iterable[Any],
) -> List[str]:

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


def _extract_words(
    text: str,
) -> List[str]:

    if not text:
        return []

    return re.findall(
        r"[^\W\d_][\w'-]{1,40}",
        text,
        flags=re.UNICODE,
    )


def _count_word_matches(
    text: str,
    vocabulary: Iterable[str],
) -> int:

    if not text:
        return 0

    normalized = _normalize_text(text)

    if not normalized:
        return 0

    words = set(
        _extract_words(normalized)
    )

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
        1
        for ch in text
        if (
            0x1F000 <= ord(ch) <= 0x1FAFF
            or 0x2600 <= ord(ch) <= 0x27BF
        )
    )


def _count_spam_emojis(text: str) -> int:

    if not text:
        return 0

    return sum(
        text.count(emoji)
        for emoji in _SPAM_EMOJIS
    )


def _count_unique_matches(
    text: str,
    patterns: Iterable[re.Pattern],
) -> int:

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


def _has_mixed_suspicious_scripts(text: str) -> bool:

    counts = _script_counts(text)

    latin = counts["latin"]
    cyr = counts["cyrillic"]
    greek = counts["greek"]

    return latin >= 3 and (cyr >= 1 or greek >= 1)


# =============================================================================
# NORMALIZATION
# =============================================================================

def _strip_combining_marks(text: str) -> str:

    if not text:
        return ""

    result: List[str] = []

    for ch in unicodedata.normalize("NFD", text):
        code = ord(ch)

        in_range = any(
            start <= code <= end
            for start, end in _COMBINING_RANGES
        )

        if in_range:
            continue

        if unicodedata.category(ch) == "Mn":
            continue

        result.append(ch)

    return "".join(result)


def _remove_hidden_chars(text: str) -> str:

    if not text:
        return ""

    return "".join(
        ch
        for ch in text
        if ch not in _HIDDEN_CHARS
    )


def _deleet(text: str) -> str:

    if not text:
        return ""

    def repl(match: re.Match) -> str:
        token = match.group(0)

        # لا نلمس token رقمي بالكامل.
        if not re.search(r"[A-Za-z]", token):
            return token

        if not re.search(r"\d|[@$]", token):
            return token

        # يجب أن يحتوي token على حروف كافية
        # حتى لا نعتبر أرقامًا عادية تحايلاً.
        letters = len(
            re.findall(r"[A-Za-z]", token)
        )

        if letters < 2:
            return token

        return token.translate(_LEET_MAP)

    return re.sub(
        r"[A-Za-z0-9@$]{3,}",
        repl,
        text,
    )


def _apply_homoglyphs_safe(text: str) -> str:

    if not text or not ANTIEVASION_HOMOGLYPH:
        return text or ""

    return "".join(
        _HOMOGLYPH_MAP.get(ch, ch)
        for ch in text
    )


def _normalize_unicode_dots(text: str) -> str:

    if not text or not ANTIEVASION_UNICODE_DOTS:
        return text or ""

    replacements = {
        "\u2024": ".",
        "\u2025": ".",
        "\u2026": ".",
        "\u3002": ".",
        "\uFE52": ".",
        "\uFF0E": ".",
        "\uFF61": ".",
    }

    return "".join(
        replacements.get(ch, ch)
        for ch in text
    )


def _normalize_text(text: str) -> str:

    if not text:
        return ""

    value = html.unescape(str(text))

    # NFKC handles compatibility forms.
    value = unicodedata.normalize(
        "NFKC",
        value,
    )

    # casefold أقوى من lower في المقارنات النصية.
    value = value.casefold()

    if (
        ANTIEVASION_COMBINING
        or ANTIEVASION_EXTENDED_COMBINING
    ):
        value = _strip_combining_marks(value)

    value = _remove_hidden_chars(value)
    value = _normalize_unicode_dots(value)

    if ANTIEVASION_HOMOGLYPH:
        value = _apply_homoglyphs_safe(value)

    if ANTIEVASION_LEETSPEAK:
        value = _deleet(value)

    # إعادة تطبيق التطبيع بعد التحويلات.
    value = unicodedata.normalize(
        "NFKC",
        value,
    )

    for code in range(0x2000, 0x200B):
        value = value.replace(chr(code), " ")

    value = value.replace("\u00a0", " ")

    value = re.sub(
        r"[ \t\r\f\v]+",
        " ",
        value,
    )

    return value.strip()


def _strip_emoji_for_domain(text: str) -> str:

    if not text:
        return ""

    if not ANTIEVASION_EMOJI_IN_DOMAIN:
        return text

    return re.sub(
        r"[\U0001F000-\U0001FAFF]",
        "",
        text,
    )


def _has_hidden_chars(text: str) -> bool:

    return bool(
        text
        and any(
            ch in _HIDDEN_CHARS
            for ch in text
        )
    )


def _hidden_char_count(text: str) -> int:

    if not text:
        return 0

    return sum(
        ch in _HIDDEN_CHARS
        for ch in text
    )


def _bidi_count(text: str) -> int:

    if not text:
        return 0

    return sum(
        ch in _BIDI_CHARS
        for ch in text
    )


def _merge_split_urls(text: str) -> str:

    if not text:
        return ""

    value = str(text)

    value = re.sub(
        r"(?i)"
        r"h\s*t\s*t\s*p\s*s?"
        r"\s*:\s*/\s*/",
        "https://",
        value,
    )

    value = re.sub(
        r"(?i)"
        r"\bh\s*t\s*t\s*p\s*s?"
        r"\s*[:/\\]+",
        "https://",
        value,
    )

    value = re.sub(
        r"(?i)"
        r"\bt\s*[\.\[\(\{]?\s*m\s*"
        r"[\.\]\)\}]\s*e",
        "t.me",
        value,
    )

    value = _DOT_LIKE_RE.sub(".", value)

    value = re.sub(
        r"(?i)\bdot\b",
        ".",
        value,
    )

    value = re.sub(
        r"\s*\.\s*",
        ".",
        value,
    )

    value = re.sub(
        r"\s*/\s*",
        "/",
        value,
    )

    return value


# =============================================================================
# URL EXTRACTION
# =============================================================================

def _extract_possible_urls(
    text: str,
) -> List[str]:

    if not text:
        return []

    raw = str(text)

    normalized = _normalize_unicode_dots(raw)
    normalized = _merge_split_urls(normalized)

    candidates: List[str] = []

    candidates.extend(
        _URL_RE.findall(normalized)
    )

    if ANTIEVASION_SCHEMELESS_URL:
        candidates.extend(
            _DOMAIN_HTTP_RE.findall(normalized)
        )

    if ANTIEVASION_EMAIL:
        candidates.extend(
            _EMAIL_RE.findall(normalized)
        )

    if ANTIEVASION_IPV4_SCHEMELESS:
        candidates.extend(
            _IPV4_RE.findall(normalized)
        )

    if ANTIEVASION_PUNYCODE:
        candidates.extend(
            _PUNYCODE_RE.findall(normalized)
        )

    if ANTIEVASION_TG_SCHEME:
        candidates.extend(
            _TG_SCHEME_RE.findall(normalized)
        )
        candidates.extend(
            _TG_URL_RE.findall(normalized)
        )
        candidates.extend(
            _TG_INVITE_RE.findall(normalized)
        )

    return _unique_strings(candidates)


# =============================================================================
# ENHANCED LINK DETECTION
# =============================================================================

def _has_domain_pattern(text: str) -> bool:

    if not text:
        return False

    value = _merge_split_urls(
        _strip_emoji_for_domain(
            _normalize_text(text)
        )
    )

    return bool(
        _DOMAIN_RE.search(value)
        or _SPACED_DOMAIN_RE.search(value)
        or _DOT_DOMAIN_RE.search(value)
        or (
            ANTIEVASION_PUNYCODE
            and _PUNYCODE_RE.search(value)
        )
        or (
            ANTIEVASION_IPV4_SCHEMELESS
            and _IPV4_RE.search(value)
        )
    )


def _contains_link_enhanced(
    text: str,
    *,
    include_usernames: bool = True,
) -> bool:

    if not text:
        return False

    raw = str(text)
    normalized = _normalize_text(raw)
    merged = _merge_split_urls(normalized)

    if _URL_RE.search(raw):
        return True

    if _DOMAIN_HTTP_RE.search(raw):
        return True

    if _DOMAIN_RE.search(merged):
        return True

    if _SPACED_DOMAIN_RE.search(normalized):
        return True

    if _DOT_DOMAIN_RE.search(normalized):
        return True

    if (
        ANTIEVASION_TG_SCHEME
        and (
            _TG_SCHEME_RE.search(merged)
            or _TG_URL_RE.search(merged)
            or _TG_INVITE_RE.search(merged)
            or _SPACED_TG_RE.search(normalized)
        )
    ):
        return True

    if ANTIEVASION_ALT_SCHEMES:
        if _ALT_SCHEME_RE.search(raw):
            return True

        if _SPACED_SCHEME_RE.search(raw):
            return True

    if (
        ANTIEVASION_EMAIL
        and _EMAIL_RE.search(normalized)
    ):
        return True

    if (
        ANTIEVASION_PUNYCODE
        and _PUNYCODE_RE.search(normalized)
    ):
        return True

    if (
        ANTIEVASION_IPV4_SCHEMELESS
        and _IPV4_RE.search(normalized)
    ):
        return True

    if (
        include_usernames
        and ANTIEVASION_AT_CHANNEL
        and _TG_USERNAME_RE.search(normalized)
    ):
        return True

    return False


def _contains_email(text: str) -> bool:

    if not text or not ANTIEVASION_EMAIL:
        return False

    return bool(
        _EMAIL_RE.search(
            _normalize_text(text)
        )
    )


def _contains_at_channel(text: str) -> bool:

    if not text or not ANTIEVASION_AT_CHANNEL:
        return False

    return bool(
        _TG_USERNAME_RE.search(
            _normalize_text(text)
        )
    )


def _contains_tg_scheme(text: str) -> bool:

    if not text or not ANTIEVASION_TG_SCHEME:
        return False

    normalized = _merge_split_urls(
        _normalize_text(text)
    )

    return bool(
        _TG_SCHEME_RE.search(normalized)
        or _TG_URL_RE.search(normalized)
        or _TG_INVITE_RE.search(normalized)
        or _SPACED_TG_RE.search(normalized)
    )


# =============================================================================
# ENTITY / BUTTON EXTRACTION
# =============================================================================

def _extract_entity_urls(
    message: Any,
    _depth: int = 0,
) -> List[str]:

    if message is None or _depth > 4:
        return []

    urls: List[str] = []

    try:
        text = getattr(message, "text", None) or ""
        entities = getattr(message, "entities", None) or []

        for entity in entities:
            try:
                entity_type = str(
                    getattr(entity, "type", "") or ""
                ).lower()

                if entity_type == "text_link":
                    url = getattr(entity, "url", None)
                    if url:
                        urls.append(str(url))

                elif entity_type == "url":
                    offset = int(
                        getattr(entity, "offset", 0) or 0
                    )
                    length = int(
                        getattr(entity, "length", 0) or 0
                    )

                    if text and length > 0:
                        part = text[
                            offset:offset + length
                        ]
                        if part:
                            urls.append(str(part))

            except Exception:
                continue

        caption = getattr(
            message,
            "caption",
            None,
        ) or ""

        caption_entities = getattr(
            message,
            "caption_entities",
            None,
        ) or []

        for entity in caption_entities:
            try:
                entity_type = str(
                    getattr(entity, "type", "") or ""
                ).lower()

                if entity_type == "text_link":
                    url = getattr(entity, "url", None)
                    if url:
                        urls.append(str(url))

                elif entity_type == "url":
                    offset = int(
                        getattr(entity, "offset", 0) or 0
                    )
                    length = int(
                        getattr(entity, "length", 0) or 0
                    )

                    if caption and length > 0:
                        part = caption[
                            offset:offset + length
                        ]
                        if part:
                            urls.append(str(part))

            except Exception:
                continue

        reply = getattr(
            message,
            "reply_to_message",
            None,
        )

        if reply is not None:
            urls.extend(
                _extract_entity_urls(
                    reply,
                    _depth + 1,
                )
            )

    except Exception:
        pass

    return _unique_strings(urls)


def _has_link_entity(message: Any) -> bool:
    return bool(_extract_entity_urls(message))


def _extract_url_from_button(
    button: Any,
) -> Optional[str]:

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
            login_web_url = getattr(
                login_url,
                "url",
                None,
            )

            if login_web_url:
                return str(login_web_url)

            return "login_url://button"

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
        markup = getattr(
            message,
            "reply_markup",
            None,
        )

        if markup is None:
            return 0, [], [], []

        rows = getattr(
            markup,
            "inline_keyboard",
            None,
        )

        if rows is None:
            return 0, [], [], []

        for row in rows or []:
            for button in row or []:
                button_count += 1

                text = getattr(
                    button,
                    "text",
                    None,
                )

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
            website = getattr(
                contact,
                "website",
                None,
            )

            if website:
                urls.append(str(website))

    except Exception:
        pass

    return _unique_strings(urls)


def _extract_venue_url(message: Any) -> Optional[str]:
    # Telegram Venue لا يحتوي عادةً على web URL.
    # الدالة محفوظة للتوافق.
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

        question = str(
            getattr(poll, "question", None) or ""
        )

        options = getattr(
            poll,
            "options",
            None,
        ) or []

        option_texts: List[str] = []

        for option in options:
            option_text = getattr(
                option,
                "text",
                None,
            )

            if option_text:
                option_texts.append(str(option_text))

        full = " ".join(
            [question] + option_texts
        ).strip()

        return (
            full,
            len(option_texts),
            _extract_possible_urls(full),
        )

    except Exception:
        return "", 0, []


# =============================================================================
# MESSAGE HELPERS
# =============================================================================

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

        parts.extend(
            _get_message_button_texts(message)
        )

        poll_text, _, _ = _extract_poll_text(message)

        if poll_text:
            parts.append(poll_text)

    except Exception:
        pass

    result = "\n".join(
        x for x in parts if x
    ).strip()

    return result[:MAX_ANALYSIS_TEXT_LENGTH]


# =============================================================================
# CONTEXT OBJECT
# =============================================================================

class _MessageContext:

    __slots__ = (
        "__weakref__",
        "text", "caption", "full_text",
        "normalized_text", "analysis_text",
        "button_count", "button_urls",
        "button_texts", "button_urls_raw",
        "is_forwarded", "is_protected",
        "has_hint", "is_auto_fwd",
        "entity_urls", "has_link_entity",
        "button_link_urls", "has_any_link",
        "has_button_link", "vcard_urls",
        "venue_url", "has_hidden_chars",
        "poll_text", "poll_options_count",
        "poll_urls", "hidden_char_count",
        "bidi_count", "script_counts",
        "mixed_scripts", "normalized_compact",
        "normalized_url_text", "emoji_count",
        "spam_emoji_count", "url_count",
        "domain_count", "telegram_link_count",
        "cta_count", "strong_word_count",
        "medium_word_count", "promo_word_count",
        "arabic_spam_count", "generic_word_count",
        "suspicious_separator_count",
        "repeated_char_count", "repeated_word_count",
        "forward_hint",
    )

    def __init__(
        self,
        message: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:

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

        # v2.2.0.b: حقل منفصل للتلميح الأمامي (لا يتعارض مع has_hint)
        self.forward_hint = False

        for key, value in kwargs.items():
            if key in self.__slots__:
                setattr(self, key, value)

        if message is not None:
            self._populate(message)

    def _populate(self, message: Any) -> None:

        try:
            self.text = str(
                getattr(message, "text", None) or ""
            )

            self.caption = str(
                getattr(message, "caption", None) or ""
            )

            self.full_text = "\n".join(
                x
                for x in (
                    self.text,
                    self.caption,
                )
                if x
            ).strip()

            self.analysis_text = (
                _get_message_analysis_text(message)
            )

            self.normalized_text = _normalize_text(
                self.analysis_text
            )

            self.normalized_compact = re.sub(
                r"[\W_]+",
                "",
                self.normalized_text,
                flags=re.UNICODE,
            )

            self.normalized_url_text = (
                _merge_split_urls(
                    self.normalized_text
                )
            )

            (
                self.button_count,
                self.button_urls,
                self.button_texts,
                self.button_urls_raw,
            ) = _extract_button_context(message)

            self.button_link_urls = list(
                self.button_urls
            )

            self.entity_urls = _extract_entity_urls(message)
            self.has_link_entity = bool(self.entity_urls)

            self.vcard_urls = _extract_vcard_urls(message)
            self.venue_url = _extract_venue_url(message)

            (
                self.poll_text,
                self.poll_options_count,
                self.poll_urls,
            ) = _extract_poll_text(message)

            self.has_hidden_chars = _has_hidden_chars(
                self.analysis_text
            )

            self.hidden_char_count = _hidden_char_count(
                self.analysis_text
            )

            self.bidi_count = _bidi_count(
                self.analysis_text
            )

            self.script_counts = _script_counts(
                self.analysis_text
            )

            self.mixed_scripts = (
                _has_mixed_suspicious_scripts(
                    self.analysis_text
                )
            )

            self.emoji_count = _count_emojis(
                self.analysis_text
            )

            self.spam_emoji_count = _count_spam_emojis(
                self.analysis_text
            )

            self.url_count = _count_text_urls(
                self.analysis_text
            )

            self.domain_count = len(
                _DOMAIN_RE.findall(
                    self.normalized_url_text
                )
            )

            self.telegram_link_count = len(
                _TG_URL_RE.findall(
                    self.normalized_url_text
                )
            )

            self.cta_count = _count_word_matches(
                self.normalized_text,
                _CTA_WORDS,
            )

            self.strong_word_count = _count_word_matches(
                self.normalized_text,
                _STRONG_SPAM_WORDS,
            )

            self.medium_word_count = _count_word_matches(
                self.normalized_text,
                _MEDIUM_SPAM_WORDS,
            )

            self.promo_word_count = _count_word_matches(
                self.normalized_text,
                _PROMO_WORDS,
            )

            self.arabic_spam_count = _count_word_matches(
                self.normalized_text,
                (
                    _ARABIC_SPAM_WORDS
                    | _ARABIC_CTA_WORDS
                    | _EXTRA_SCRIPT_SPAM_WORDS
                ),
            )

            self.generic_word_count = _count_word_matches(
                self.normalized_text,
                _GENERIC_WORDS,
            )

            self.suspicious_separator_count = len(
                _SEPARATOR_RE.findall(
                    self.analysis_text
                )
            )

            self.repeated_char_count = len(
                _REPEATED_CHAR_RE.findall(
                    self.analysis_text
                )
            )

            self.repeated_word_count = len(
                _REPEATED_WORD_RE.findall(
                    self.normalized_text
                )
            )

            self.has_button_link = bool(
                self.button_link_urls
                or any(
                    "://button" in str(x)
                    for x in self.button_urls_raw
                )
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
                    self.analysis_text,
                    include_usernames=False,
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
                getattr(
                    message,
                    "is_automatic_forward",
                    False,
                )
            )

            self.is_protected = bool(
                getattr(
                    message,
                    "has_protected_content",
                    False,
                )
            )

            self.has_hint = bool(
                self.button_count
                or self.has_any_link
                or self.has_link_entity
            )

            # forward_hint: تلميح نصي لرسالة forward مخفية
            self.forward_hint = bool(
                getattr(message, "has_protected_content", False)
                and (
                    "محولة من" in self.full_text
                    or "محوّل من" in self.full_text
                    or "Forwarded from" in self.full_text
                )
            )

        except Exception as exc:
            if DEBUG_DIAG:
                try:
                    print(
                        "[DETECTOR] context error:",
                        repr(exc),
                    )
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
        return bool(
            _extract_button_context(
                message_or_context
            )[1]
        )
    except Exception:
        return False


def _extract_button_link_urls(
    message_or_context: Any,
) -> List[str]:

    if isinstance(message_or_context, _MessageContext):
        return list(
            message_or_context.button_link_urls
        )

    try:
        return list(
            _extract_button_context(
                message_or_context
            )[1]
        )
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
        _STRONG_SPAM_WORDS,
        _MEDIUM_SPAM_WORDS,
        _CTA_WORDS,
        _PROMO_WORDS,
        _ARABIC_SPAM_WORDS,
        _ARABIC_CTA_WORDS,
        _EXTRA_SCRIPT_SPAM_WORDS,
    )

    for vocabulary in vocabularies:
        for word in vocabulary:
            if re.search(
                rf"(?<![\w-])"
                rf"{re.escape(str(word).casefold())}"
                rf"(?![\w-])",
                normalized,
                flags=re.IGNORECASE,
            ):
                found.append(str(word))

    compact = re.sub(
        r"[\W_]+",
        "",
        normalized,
        flags=re.UNICODE,
    )

    compact_candidates = {
        "megapack",
        "megapacks",
        "viralcontent",
        "openhere",
        "viewleak",
        "checkthis",
        "clickhere",
        "watchnow",
        "exclusivecontent",
    }

    for word in compact_candidates:
        if word in compact:
            found.append(word)

    return _unique_strings(found)


# =============================================================================
# EVASION
# =============================================================================

def _compact_evasion_variants(text: str) -> List[str]:

    if not text:
        return []

    normalized = _normalize_text(text)

    variants = [normalized]

    compact = re.sub(
        r"[^\w]+",
        "",
        normalized,
        flags=re.UNICODE,
    )

    if compact != normalized:
        variants.append(compact)

    no_emoji = re.sub(
        r"[\U0001F000-\U0001FAFF]",
        "",
        normalized,
    )

    no_emoji = re.sub(r"\s+", "", no_emoji)

    if no_emoji != normalized:
        variants.append(no_emoji)

    return _unique_strings(variants)


def _detect_split_spam_words(text: str) -> List[str]:

    if (
        not text
        or not ANTIEVASION_COMPACT_WORDS
    ):
        return []

    variants = _compact_evasion_variants(text)

    targets = (
        set(_STRONG_SPAM_WORDS)
        | set(_PROMO_WORDS)
        | {
            "viralcontent",
            "megapack",
            "openhere",
            "viewleak",
            "watchnow",
            "clickhere",
            "exclusivecontent",
        }
    )

    compact_targets = {
        re.sub(
            r"[\W_]+",
            "",
            str(x).casefold(),
        )
        for x in targets
    }

    found: List[str] = []

    for variant in variants:
        compact_variant = re.sub(
            r"[\W_]+",
            "",
            variant.casefold(),
            flags=re.UNICODE,
        )

        for target in compact_targets:
            if len(target) < 4:
                continue

            if target in compact_variant:
                found.append(target)

    return _unique_strings(found)


def _detect_url_obfuscation(
    text: str,
) -> Tuple[bool, List[str]]:

    if not text:
        return False, []

    raw = str(text)
    normalized = _normalize_text(raw)

    reasons: List[str] = []

    if _SPACED_SCHEME_RE.search(raw):
        reasons.append("spaced_url_scheme")

    if _ALT_SCHEME_RE.search(raw):
        reasons.append("alternate_url_scheme")

    if _SPACED_TG_RE.search(normalized):
        reasons.append("obfuscated_telegram_domain")

    if _DOT_DOMAIN_RE.search(normalized):
        reasons.append("dot_domain")

    if _SPACED_DOMAIN_RE.search(normalized):
        reasons.append("spaced_domain")

    if _DOT_LIKE_RE.search(raw):
        reasons.append("bracketed_dot")

    if (
        ANTIEVASION_PUNYCODE
        and _PUNYCODE_RE.search(normalized)
    ):
        reasons.append("punycode")

    if (
        ANTIEVASION_IPV4_SCHEMELESS
        and _IPV4_RE.search(normalized)
    ):
        reasons.append("ipv4")

    if (
        ANTIEVASION_EMAIL
        and _EMAIL_RE.search(normalized)
    ):
        reasons.append("email")

    if _MULTISPACE_SPLIT_RE.search(normalized):
        reasons.append("split_scheme_or_domain")

    return bool(reasons), _unique_strings(reasons)


def _detect_unicode_evasion(
    text: str,
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

    if _has_mixed_suspicious_scripts(text):
        score += 2
        reasons.append("mixed_scripts")

    if ANTIEVASION_COMBINING:
        combining = sum(
            1
            for ch in text
            if unicodedata.category(ch) == "Mn"
        )

        if combining >= 3:
            score += min(
                3,
                1 + combining // 5,
            )
            reasons.append(
                f"combining_marks:{combining}"
            )

    return min(score, 8), reasons


# =============================================================================
# POSTBOT
# =============================================================================

def _postbot_pattern_confidence(
    text: str,
    *,
    button_count: int = 0,
    button_urls: Optional[Sequence[str]] = None,
) -> int:

    if not text:
        return 0

    normalized = _normalize_text(text)
    merged = _merge_split_urls(normalized)

    confidence = 0

    strong = _count_word_matches(
        normalized,
        _STRONG_SPAM_WORDS,
    )

    promo = _count_word_matches(
        normalized,
        _PROMO_WORDS,
    )

    cta = _count_word_matches(
        normalized,
        _CTA_WORDS,
    )

    spam_emojis = _count_spam_emojis(text)

    context_hits = _count_unique_matches(
        merged,
        _PROMO_CONTEXT_PATTERNS,
    )

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

    if (
        promo >= 2
        and cta >= 1
        and button_count >= 2
    ):
        confidence += 2

    return min(confidence, 10)


def _is_postbot_pattern(
    text: str,
    *,
    button_count: int = 0,
    button_urls: Optional[Sequence[str]] = None,
) -> bool:

    if not text:
        return False

    normalized = _normalize_text(text)
    merged = _merge_split_urls(normalized)

    confidence = _postbot_pattern_confidence(
        normalized,
        button_count=button_count,
        button_urls=button_urls,
    )

    if confidence >= POSTBOT_AUTO_BLOCK_CONFIDENCE:
        return True

    return any(
        pattern.search(merged)
        for pattern in _POSTBOT_REGEXES
    )


# =============================================================================
# URL COUNT
# =============================================================================

def _count_text_urls(text: str) -> int:

    if not text:
        return 0

    normalized = _merge_split_urls(
        _normalize_text(text)
    )

    urls = _extract_possible_urls(normalized)

    if not urls and _has_domain_pattern(normalized):
        return 1

    return len(urls)


# =============================================================================
# MEDIA
# =============================================================================

def _message_has_media(
    context_or_message: Any,
) -> bool:

    if context_or_message is None:
        return False

    if isinstance(
        context_or_message,
        _MessageContext,
    ):
        return bool(
            context_or_message.caption
        )

    attrs = (
        "photo",
        "video",
        "animation",
        "document",
        "audio",
        "voice",
        "video_note",
        "sticker",
        "contact",
        "location",
        "venue",
    )

    for attr in attrs:
        try:
            if getattr(
                context_or_message,
                attr,
                None,
            ):
                return True
        except Exception:
            continue

    return False


# =============================================================================
# v2.2 ADDITIONAL SIGNALS
# =============================================================================

def _text_density_signals(
    text: str,
) -> Tuple[int, List[str]]:

    if not text:
        return 0, []

    length = len(text)

    if length < 8:
        return 0, []

    score = 0
    reasons: List[str] = []

    digits = sum(ch.isdigit() for ch in text)
    letters = sum(ch.isalpha() for ch in text)
    symbols = sum(
        not ch.isalnum() and not ch.isspace()
        for ch in text
    )

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

    if len(text.split()) <= 3 and (
        digits >= 8 or symbols >= 8
    ):
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
) -> Tuple[int, List[str]]:

    if not text:
        return 0, []

    reasons: List[str] = []
    score = 0

    normalized = _normalize_text(text)

    if _PHONE_RE.search(normalized):
        score += 1
        reasons.append("phone_like_sequence")

    # Deliberately only scores strongly when combined with promotion.
    if (
        _PHONE_RE.search(normalized)
        and (
            _count_word_matches(
                normalized,
                _CTA_WORDS,
            )
            or _contains_link_enhanced(
                normalized,
                include_usernames=False,
            )
        )
    ):
        score += 2
        reasons.append("contact_with_promotion")

    return min(score, 3), reasons


def _detect_structural_evasion(
    text: str,
) -> Tuple[int, List[str]]:

    if not text:
        return 0, []

    score = 0
    reasons: List[str] = []

    if _MULTISPACE_SPLIT_RE.search(text):
        score += 1
        reasons.append("character_split")

    if (
        ANTIEVASION_EMOJI_SEPARATOR
        and _EMOJI_SPLIT_RE.search(text)
    ):
        score += 2
        reasons.append("emoji_character_split")

    if _LONG_DOMAIN_LABEL_RE.search(
        _merge_split_urls(text)
    ):
        score += 2
        reasons.append("long_domain_label")

    return min(score, 4), reasons


# =============================================================================
# SCORING ENGINE
# =============================================================================

def _compute_spam_score(
    context_or_message: Any,
    *,
    return_diagnostics: bool = False,
) -> Any:

    try:
        if isinstance(
            context_or_message,
            _MessageContext,
        ):
            ctx = context_or_message
        else:
            ctx = _MessageContext(
                context_or_message
            )

        text = ctx.analysis_text or ""
        normalized = ctx.normalized_text or ""

        if not text:
            result = {
                "score": 0,
                "reasons": [],
                "confidence": "none",
                "hard": False,
                "critical": False,
                "postbot_confidence": 0,
            }

            return result if return_diagnostics else (0, [])

        score = 0
        reasons: List[str] = []

        # ------------------------------------------------------------------
        # ENTITY LINKS
        # ------------------------------------------------------------------

        if (
            ANTIEVASION_ENTITY_LINK
            and ctx.has_link_entity
        ):
            score += 3
            reasons.append("link_entity")

        # ------------------------------------------------------------------
        # BUTTON LINKS
        # ------------------------------------------------------------------

        external_buttons = len(
            ctx.button_link_urls
        )

        if (
            ANTIEVASION_BUTTON_LINK
            and external_buttons
        ):
            if external_buttons >= 3:
                score += 5
                reasons.append(
                    f"external_buttons:{external_buttons}"
                )
            elif external_buttons == 2:
                score += 4
                reasons.append("external_buttons:2")
            else:
                score += 2
                reasons.append("external_button")

        if (
            ANTIEVASION_BUTTON_WEBAPP
            and any(
                "web_app://button" in str(x)
                for x in ctx.button_urls_raw
            )
        ):
            score += 3
            reasons.append("webapp_button")

        if (
            ANTIEVASION_BUTTON_LOGINURL
            and any(
                "login_url://button" in str(x)
                for x in ctx.button_urls_raw
            )
        ):
            score += 3
            reasons.append("loginurl_button")

        # ------------------------------------------------------------------
        # LINKS
        # ------------------------------------------------------------------

        link_detected = _contains_link_enhanced(
            text,
            include_usernames=False,
        )

        if link_detected:
            score += 3
            reasons.append("link_detected")

        url_obfuscated, url_reasons = (
            _detect_url_obfuscation(text)
        )

        if url_obfuscated:
            score += min(
                5,
                2 + len(url_reasons),
            )
            reasons.extend(
                "url_evasion:" + x
                for x in url_reasons
            )

        text_url_count = _count_text_urls(text)

        if text_url_count >= 3:
            score += 4
            reasons.append(
                f"text_urls:{text_url_count}"
            )
        elif text_url_count == 2:
            score += 3
            reasons.append("text_urls:2")
        elif text_url_count == 1:
            score += 1
            reasons.append("text_url")

        if _contains_tg_scheme(text):
            score += 3
            reasons.append("telegram_link")

        if _contains_email(text):
            score += 2
            reasons.append("email_link")

        if _contains_at_channel(text):
            # Username alone is weak evidence.
            score += 1
            reasons.append("telegram_username")

        if (
            ANTIEVASION_PUNYCODE
            and _PUNYCODE_RE.search(normalized)
        ):
            score += 3
            reasons.append("punycode_domain")

        if (
            ANTIEVASION_IPV4_SCHEMELESS
            and _IPV4_RE.search(normalized)
        ):
            score += 3
            reasons.append("ipv4_link")

        # ------------------------------------------------------------------
        # BUTTON STRUCTURE
        # ------------------------------------------------------------------

        if ctx.button_count >= 4:
            score += 3
            reasons.append(
                f"many_buttons:{ctx.button_count}"
            )
        elif ctx.button_count == 3:
            score += 2
            reasons.append("three_buttons")
        elif ctx.button_count == 2:
            score += 1
            reasons.append("two_buttons")

        button_text = " ".join(ctx.button_texts)

        button_cta_count = _count_word_matches(
            button_text,
            _CTA_WORDS,
        )

        if button_cta_count >= 3:
            score += 3
            reasons.append(
                f"button_cta:{button_cta_count}"
            )
        elif button_cta_count >= 2:
            score += 2
            reasons.append("button_cta:2")
        elif button_cta_count == 1:
            score += 1
            reasons.append("button_cta")

        # ------------------------------------------------------------------
        # VOCABULARY
        # ------------------------------------------------------------------

        strong = ctx.strong_word_count
        medium = ctx.medium_word_count
        promo = ctx.promo_word_count
        arabic = ctx.arabic_spam_count
        cta = ctx.cta_count

        if strong >= 4:
            score += 6
            reasons.append(
                f"strong_spam_words:{strong}"
            )
        elif strong == 3:
            score += 5
            reasons.append("strong_spam_words:3")
        elif strong == 2:
            score += 3
            reasons.append("strong_spam_words:2")
        elif strong == 1:
            score += 1
            reasons.append("strong_spam_word")

        if medium >= 4:
            score += 4
            reasons.append(
                f"medium_spam_words:{medium}"
            )
        elif medium >= 2:
            score += 2
            reasons.append(
                f"medium_spam_words:{medium}"
            )

        if promo >= 4:
            score += 4
            reasons.append(
                f"promo_words:{promo}"
            )
        elif promo >= 2:
            score += 2
            reasons.append(
                f"promo_words:{promo}"
            )

        if arabic >= 4:
            score += 4
            reasons.append(
                f"arabic_spam_words:{arabic}"
            )
        elif arabic >= 2:
            score += 2
            reasons.append(
                f"arabic_spam_words:{arabic}"
            )

        if cta >= 4:
            score += 4
            reasons.append(
                f"cta_words:{cta}"
            )
        elif cta >= 2:
            score += 2
            reasons.append(
                f"cta_words:{cta}"
            )

        # ------------------------------------------------------------------
        # PACK / NUMBER
        # ------------------------------------------------------------------

        has_number_pack = bool(
            _NUMBER_PROMO_RE.search(normalized)
        )

        has_pack = bool(
            _PACK_RE.search(normalized)
        )

        if has_number_pack:
            score += 4
            reasons.append("large_pack_number")

        if has_pack:
            score += 2
            reasons.append("pack_pattern")

        # ------------------------------------------------------------------
        # CONTEXT
        # ------------------------------------------------------------------

        context_hits = _count_unique_matches(
            normalized,
            _PROMO_CONTEXT_PATTERNS,
        )

        if context_hits >= 3:
            score += 6
            reasons.append(
                f"promo_context:{context_hits}"
            )
        elif context_hits == 2:
            score += 4
            reasons.append("promo_context:2")
        elif context_hits == 1:
            score += 2
            reasons.append("promo_context")

        # ------------------------------------------------------------------
        # POSTBOT
        # ------------------------------------------------------------------

        postbot_confidence = (
            _postbot_pattern_confidence(
                normalized,
                button_count=ctx.button_count,
                button_urls=ctx.button_urls,
            )
        )

        if postbot_confidence >= 6:
            score += 6
            reasons.append(
                f"postbot:very_high:{postbot_confidence}"
            )
        elif postbot_confidence >= 4:
            score += 4
            reasons.append(
                f"postbot:high:{postbot_confidence}"
            )
        elif postbot_confidence >= 2:
            score += 2
            reasons.append(
                f"postbot:{postbot_confidence}"
            )

        # ------------------------------------------------------------------
        # EMOJI
        # ------------------------------------------------------------------

        spam_emojis = ctx.spam_emoji_count

        if spam_emojis >= 6:
            score += 3
            reasons.append(
                f"spam_emojis:{spam_emojis}"
            )
        elif spam_emojis >= 3:
            score += 2
            reasons.append(
                f"spam_emojis:{spam_emojis}"
            )

        # ------------------------------------------------------------------
        # SPLIT WORDS
        # ------------------------------------------------------------------

        split_words = _detect_split_spam_words(text)

        if split_words:
            score += min(
                5,
                2 + len(split_words),
            )
            reasons.append(
                "split_spam_words:"
                + ",".join(split_words[:5])
            )

        # ------------------------------------------------------------------
        # UNICODE
        # ------------------------------------------------------------------

        unicode_score, unicode_reasons = (
            _detect_unicode_evasion(text)
        )

        if unicode_score:
            score += unicode_score
            reasons.extend(
                "unicode_evasion:" + x
                for x in unicode_reasons
            )

        if ctx.mixed_scripts:
            score += 2
            reasons.append(
                "suspicious_mixed_scripts"
            )

        # ------------------------------------------------------------------
        # STRUCTURAL EVASION
        # ------------------------------------------------------------------

        structural_score, structural_reasons = (
            _detect_structural_evasion(text)
        )

        if structural_score:
            score += structural_score
            reasons.extend(
                "structural_evasion:" + x
                for x in structural_reasons
            )

        # ------------------------------------------------------------------
        # DENSITY
        # ------------------------------------------------------------------

        density_score, density_reasons = (
            _text_density_signals(text)
        )

        if density_score:
            score += density_score
            reasons.extend(
                "density:" + x
                for x in density_reasons
            )

        # ------------------------------------------------------------------
        # CONTACT / PHONE
        # ------------------------------------------------------------------

        contact_score, contact_reasons = (
            _detect_phone_or_contact_evasion(text)
        )

        if contact_score:
            score += contact_score
            reasons.extend(
                "contact:" + x
                for x in contact_reasons
            )

        # ------------------------------------------------------------------
        # SEPARATORS / REPETITION
        # ------------------------------------------------------------------

        if ctx.suspicious_separator_count >= 2:
            score += 2
            reasons.append("separator_evasion")

        if ctx.repeated_char_count:
            score += 1
            reasons.append("repeated_characters")

        if ctx.repeated_word_count:
            score += 2
            reasons.append("repeated_words")

        # ------------------------------------------------------------------
        # MEDIA + PROMOTION
        # ------------------------------------------------------------------

        has_media = _message_has_media(
            context_or_message
        )

        if (
            has_media
            and (
                ctx.button_count >= 2
                or cta >= 2
            )
        ):
            score += 3
            reasons.append("media_plus_promotion")

        # ------------------------------------------------------------------
        # POLL / VCARD
        # ------------------------------------------------------------------

        if (
            ANTIEVASION_POLL
            and ctx.poll_urls
        ):
            score += 3
            reasons.append("poll_with_url")

        if ANTIEVASION_VENUE_VCARD:
            if ctx.vcard_urls:
                score += 2
                reasons.append("vcard_url")

            if ctx.venue_url:
                score += 2
                reasons.append("venue_url")

        # ------------------------------------------------------------------
        # FORWARDED
        # ------------------------------------------------------------------

        if (
            ctx.is_forwarded
            and score >= 5
        ):
            score += 2
            reasons.append("forwarded_spam_context")

        # ------------------------------------------------------------------
        # HIGH CONFIDENCE MARKETING
        # ------------------------------------------------------------------

        if (
            (
                promo >= 2
                or strong >= 2
            )
            and cta >= 1
            and (
                ctx.button_link_urls
                or text_url_count
            )
        ):
            score += 5
            reasons.append(
                "high_confidence_marketing_spam"
            )

        # ------------------------------------------------------------------
        # PACK + NUMBER + EXTERNAL
        # ------------------------------------------------------------------

        if (
            has_pack
            and has_number_pack
            and (
                ctx.button_link_urls
                or _contains_link_enhanced(
                    text,
                    include_usernames=False,
                )
            )
        ):
            score += 7
            reasons.append(
                "pack_number_external_cta"
            )

        # ------------------------------------------------------------------
        # CATEGORY STACK
        # ------------------------------------------------------------------

        category_hits = _count_word_matches(
            normalized,
            {
                "mfm",
                "dilf",
                "busty",
                "milf",
                "bj",
                "xxx",
                "nsfw",
                "porn",
                "nude",
                "leak",
                "clips",
            },
        )

        if (
            category_hits >= 4
            and (
                ctx.button_link_urls
                or cta >= 1
                or text_url_count
            )
        ):
            score += 6
            reasons.append(
                "multiple_spam_categories"
            )

        # ------------------------------------------------------------------
        # OBFUSCATION + PROMOTION
        # ------------------------------------------------------------------

        if (
            url_obfuscated
            and (
                strong >= 1
                or promo >= 1
                or cta >= 1
            )
        ):
            score += 4
            reasons.append(
                "obfuscated_promotion"
            )

        # ------------------------------------------------------------------
        # HIDDEN + LINK/SPAM
        # ------------------------------------------------------------------

        if (
            ctx.has_hidden_chars
            and (
                link_detected
                or strong >= 1
                or promo >= 1
            )
        ):
            score += 3
            reasons.append(
                "hidden_evasion_with_spam"
            )

        # ------------------------------------------------------------------
        # USERNAME + PROMOTION
        # ------------------------------------------------------------------

        if (
            _contains_at_channel(text)
            and (
                cta >= 1
                or promo >= 1
                or strong >= 1
            )
        ):
            score += 2
            reasons.append(
                "telegram_username_with_promotion"
            )

        # ------------------------------------------------------------------
        # FINAL
        # ------------------------------------------------------------------

        score = max(
            0,
            min(
                MAX_SPAM_SCORE,
                int(score),
            ),
        )

        reasons = _unique_strings(
            reasons
        )[:MAX_REASON_COUNT]

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

        if DEBUG_SPAM:
            try:
                print(
                    "[SPAM]"
                    f" score={score}"
                    f" confidence={confidence}"
                    f" reasons={reasons}"
                )
            except Exception:
                pass

        result = {
            "score": score,
            "reasons": reasons,
            "confidence": confidence,
            "hard": score >= SPAM_HARD_THRESHOLD,
            "critical": score >= SPAM_CRITICAL_THRESHOLD,
            "postbot_confidence": postbot_confidence,
        }

        if return_diagnostics:
            return result

        return score, reasons

    except Exception as exc:

        if DEBUG_DIAG:
            try:
                print(
                    "[DETECTOR] scoring error:",
                    repr(exc),
                )
            except Exception:
                pass

        if return_diagnostics:
            return {
                "score": 0,
                "reasons": ["detector_error"],
                "confidence": "none",
                "hard": False,
                "critical": False,
                "postbot_confidence": 0,
            }

        return 0, []


# =============================================================================
# FALSE POSITIVE GUARDS
# =============================================================================

def _looks_like_normal_conversation(
    text: str,
) -> bool:

    if not text:
        return True

    normalized = _normalize_text(text)
    words = _extract_words(normalized)

    if not words:
        return True

    generic_hits = sum(
        word in _GENERIC_WORDS
        for word in words
    )

    strong_hits = _count_word_matches(
        normalized,
        _STRONG_SPAM_WORDS,
    )

    promo_hits = _count_word_matches(
        normalized,
        _PROMO_WORDS,
    )

    link = _contains_link_enhanced(
        normalized,
        include_usernames=False,
    )

    # الكلمات العامة وحدها لا تكفي.
    if (
        generic_hits >= 1
        and strong_hits == 0
        and promo_hits <= 1
        and not link
        and len(words) <= 12
    ):
        return True

    # رسالة طويلة طبيعية بلا روابط ولا مؤشرات قوية.
    if (
        len(words) >= 8
        and strong_hits == 0
        and promo_hits <= 1
        and not link
    ):
        return True

    return False


def should_ignore_as_low_signal(
    message: Any,
) -> bool:

    try:
        ctx = _MessageContext(message)

        if not ctx.analysis_text:
            return True

        if _looks_like_normal_conversation(
            ctx.analysis_text
        ):
            score, _ = _compute_spam_score(ctx)

            return score < SPAM_SCORE_THRESHOLD

    except Exception:
        return False

    return False


# =============================================================================
# HIGH LEVEL API
# =============================================================================

def analyze_message(message: Any) -> dict:

    ctx = _MessageContext(message)

    result = _compute_spam_score(
        ctx,
        return_diagnostics=True,
    )

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


# =============================================================================
# DIAGNOSTICS
# =============================================================================

def get_spam_diagnostics(message: Any) -> dict:

    try:
        ctx = _MessageContext(message)

        score_info = _compute_spam_score(
            ctx,
            return_diagnostics=True,
        )

        split_words = _detect_split_spam_words(
            ctx.analysis_text
        )

        url_obfuscated, url_reasons = (
            _detect_url_obfuscation(
                ctx.analysis_text
            )
        )

        unicode_score, unicode_reasons = (
            _detect_unicode_evasion(
                ctx.analysis_text
            )
        )

        density_score, density_reasons = (
            _text_density_signals(
                ctx.analysis_text
            )
        )

        structural_score, structural_reasons = (
            _detect_structural_evasion(
                ctx.analysis_text
            )
        )

        return {
            **score_info,

            "text": ctx.full_text,
            "normalized_text": ctx.normalized_text,

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
                "score": density_score,
                "reasons": density_reasons,
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
                    ctx.analysis_text,
                    button_count=ctx.button_count,
                    button_urls=ctx.button_urls,
                ),
                "confidence": score_info[
                    "postbot_confidence"
                ],
            },
        }

    except Exception as exc:
        return {
            "score": 0,
            "reasons": ["diagnostic_error"],
            "confidence": "none",
            "hard": False,
            "critical": False,
            "error": repr(exc),
        }


# =============================================================================
# COMPATIBILITY EXPORTS
# =============================================================================

__all__ = [
    "DEBUG_DIAG",
    "DEBUG_SPAM",

    "ANTIEVASION_ENTITY_LINK",
    "ANTIEVASION_BUTTON_LINK",
    "ANTIEVASION_SCHEMELESS_URL",
    "ANTIEVASION_HOMOGLYPH",
    "ANTIEVASION_COMBINING",
    "ANTIEVASION_COMPACT_WORDS",
    "ANTIEVASION_EMOJI_SEPARATOR",
    "ANTIEVASION_BUTTON_WEBAPP",
    "ANTIEVASION_BUTTON_LOGINURL",
    "ANTIEVASION_LEETSPEAK",
    "ANTIEVASION_TG_SCHEME",
    "ANTIEVASION_AT_CHANNEL",
    "ANTIEVASION_EMAIL",
    "ANTIEVASION_PUNYCODE",
    "ANTIEVASION_IPV4_SCHEMELESS",
    "ANTIEVASION_MULTILINE_URL",
    "ANTIEVASION_VENUE_VCARD",
    "ANTIEVASION_POLL",
    "ANTIEVASION_EMOJI_IN_DOMAIN",
    "ANTIEVASION_UNICODE_DOTS",
    "ANTIEVASION_EXTENDED_COMBINING",
    "ANTIEVASION_EXTRA_SCRIPTS",
    "ANTIEVASION_ALT_SCHEMES",

    "SPAM_SCORE_THRESHOLD",
    "POSTBOT_AUTO_BLOCK_CONFIDENCE",
    "SPAM_HARD_THRESHOLD",
    "SPAM_CRITICAL_THRESHOLD",

    "_MessageContext",

    "_strip_combining_marks",
    "_deleet",
    "_apply_homoglyphs_safe",
    "_normalize_text",
    "_strip_emoji_for_domain",
    "_has_hidden_chars",
    "_merge_split_urls",

    "_extract_entity_urls",
    "_has_link_entity",
    "_extract_url_from_button",
    "_button_is_external",
    "_extract_button_context",
    "_extract_vcard_urls",
    "_extract_venue_url",
    "_extract_poll_text",

    "_get_message_button_data",
    "_get_message_button_texts",
    "_get_message_analysis_text",

    "_has_domain_pattern",
    "_contains_link_enhanced",
    "_contains_email",
    "_contains_at_channel",
    "_contains_tg_scheme",
    "_has_button_link",
    "_extract_button_link_urls",

    "_extract_spam_words",
    "_count_unique_matches",
    "_count_text_urls",
    "_compute_spam_score",

    "_is_postbot_pattern",
    "_postbot_pattern_confidence",

    "analyze_message",
    "get_spam_diagnostics",
    "is_spam",
    "is_high_confidence_spam",
    "is_critical_spam",
    "should_ignore_as_low_signal",
]


# =============================================================================
# LOAD BEACON — سطر تشخيصي يُسجَّل عند تحميل الملف (v2.2.0.b)
# =============================================================================
try:
    logger.info(
        "🛡️ handlers_message_detectors %s loaded | "
        "SPAM_THRESHOLD=%d POSTBOT_CONF=%d HARD=%d CRITICAL=%d",
        _DETECTORS_VERSION,
        SPAM_SCORE_THRESHOLD,
        POSTBOT_AUTO_BLOCK_CONFIDENCE,
        SPAM_HARD_THRESHOLD,
        SPAM_CRITICAL_THRESHOLD,
    )
except Exception:
    pass