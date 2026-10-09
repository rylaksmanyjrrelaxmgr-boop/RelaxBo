#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers/messages/banned_words_manager.py
===============================================================================
🛡️ Banned Words Manager v1.2.0 — Dual-Path System + Integration Docs
===============================================================================

🎯 المساران المنفصلان:
    1. GlobalBannedWordsPath  (chat_id = -1)     → للمطور
    2. GroupBannedWordsPath   (chat_id = group)  → لمشرف المجموعة

🆕 v1.2.0 (REVIEW-FIXES-2026):
    🔴 FIX-ORDER-1: نقل _MIN_LEN_FOR_SUBSTRING_MATCH إلى قسم الثوابت
                    (كان معرَّفاً بعد is_arabic_greeting — خطر إذا
                    استُدعيت الدالة أثناء التحميل).
    🔴 FIX-ORDER-2: تعريف _invalidate_merged_cache **قبل** _invalidate_cache.
    🔴 FIX-CACHE-1: get_words_for_filtering يُعيد نسخة من القائمة
                    (list(cached_words)) بدل المرجع القابل للتعديل.
    🔴 FIX-CACHE-2: _evict_merged_cache_if_needed تحمي مدخل GLOBAL_CHAT_ID
                    من الطرد تحت الضغط.
    🔴 FIX-PATTERN-1: _get_pattern و _get_spaced_pattern يُخزّنان
                      حالات الفشل (None) لتفادي إعادة المحاولة.
    🔴 FIX-GREET-2: is_arabic_greeting يستخدم عدد الكلمات **العربية**
                    في المقام، بدل len(words) الكلي.
    🔴 FIX-BOUNDARY-1: _compact_boundary_ok يفحص كل مواضع المطابقة
                       بدل أول موضع فقط.
    🟡 FIX-INV-2: _invalidate_cache يُرجع True إذا نجح أي مسار
                  (بما فيه merged).
    🟡 FIX-TRUNC-1: contains_banned_word يقطع النص على حدود كلمة.
    🟡 FIX-TYPE-1: get_words_for_filtering يوحّد نوع chat_id مبكراً.
    🟡 FIX-EXPORT-1: إزالة الأسماء الداخلية من __all__ (تُصدَّر عبر
                     public aliases في handlers/messages/__init__.py).

🆕 v1.1.1 (INTEGRATION-DOCS + FALLBACK-CONSISTENCY):
    ✅ توثيق التكامل مع detectors v4.1.0 و handlers_message v7.18.17.
    🔴 FIX-FALLBACK-1: fallback _normalize_arabic_for_compare يطابق
                       الآن detectors v4.1.0 (حماية "الله" من إزالة "ال").
    📌 INTEG-1: يُستدعى من handlers_message.py v7.18.17 عبر
       BannedWordsManager.check_message() — لا تُغيِّر التوقيع.
    📌 INTEG-2: cache القائمة المُدمجة (_merged_words_cache)
       صالح لمدة 30s (_MERGED_CACHE_TTL). التغييرات على الكلمات
       المحظورة (add/remove) تُبطِل الـ cache فوراً.
    📌 INTEG-3: يعتمد على detectors v4.1.0 لاستيراد
       _normalize_text, _normalize_arabic_for_compare, _is_arabic_dominant.

🆕 v1.1.0 (PERFORMANCE + SAFETY FIXES):
    🔴 FIX-GREET-1: is_arabic_greeting — تقييد substring-match
    🔴 FIX-PERF-1:  contains_banned_word — skip_greeting_check
    🔴 FIX-PERF-2:  get_words_for_filtering — cache محلي بـ TTL 30s
    🔴 FIX-INV-1:   إبطال cache المُدمج في add/remove

===============================================================================
"""

from __future__ import annotations

import asyncio
import logging
import re
import time as _time
from collections import OrderedDict
from enum import Enum
from typing import Any, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

__version__ = "1.2.0"


# ═════════════════════════════════════════════════════════════════════════════
# 1. ثوابت
# ═════════════════════════════════════════════════════════════════════════════
#
# 🆕 FIX-ORDER-1: جميع الثوابت المُستخدَمة في الدوال معرَّفة هنا
#                 قبل أي استخدام فعلي.
# ═════════════════════════════════════════════════════════════════════════════

GLOBAL_CHAT_ID: int = -1
MIN_WORD_LEN: int = 2
MAX_WORD_LEN: int = 100

# الحد الأدنى لطول الكلمة للفحص بالـ compact (بدون فواصل)
_COMPACT_MIN_LEN: int = 5

# الحد الأقصى لحجم caches الـ regex
_CACHE_MAX_PATTERNS: int = 5000

# 🆕 FIX-ORDER-1: الحد الأدنى للطول للسماح بالاحتواء bidir في
#                 فحص التحيات — مُعرَّف هنا قبل is_arabic_greeting.
_MIN_LEN_FOR_SUBSTRING_MATCH: int = 4

# ═════════════════════════════════════════════════════════════════════════════
# 1.1 ثوابت cache المُدمج (global + group)
# ═════════════════════════════════════════════════════════════════════════════

_MERGED_CACHE_TTL: float = 30.0
_MERGED_CACHE_MAX: int = 500

# 🆕 FIX-TRUNC-1: حدّ قطع النص قبل الفحص
_TEXT_TRUNCATE_LIMIT: int = 4000
_TEXT_TRUNCATE_LOOKBACK: int = 200   # ابحث عن مسافة في آخر 200 حرف


# ═════════════════════════════════════════════════════════════════════════════
# 2. Enums
# ═════════════════════════════════════════════════════════════════════════════

class BannedScope(str, Enum):
    GLOBAL = "global"
    GROUP = "group"

    def __str__(self) -> str:
        return self.value


class OpReason(str, Enum):
    ADDED = "added"
    REMOVED = "removed"
    DUPLICATE = "duplicate"
    NOT_FOUND = "not_found"
    NO_PERMS = "no_perms"
    INVALID = "invalid"
    DB_ERROR = "db_error"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return self.value


# ═════════════════════════════════════════════════════════════════════════════
# 3. استيرادات خارجية مع fallbacks
# ═════════════════════════════════════════════════════════════════════════════
#
# 📌 INTEG-3: يُفضَّل استخدام detectors v4.1.0+ لأنها تحوي حماية "الله"
# في _normalize_arabic_for_compare. الـ fallback أدناه يطابقها بعد
# FIX-FALLBACK-1.
# ═════════════════════════════════════════════════════════════════════════════

try:
    from handlers.handlers_message_detectors import (
        _normalize_text,
        _normalize_arabic_for_compare,
        _is_arabic_dominant,
    )
    _HAS_DETECTOR_HELPERS = True
except ImportError:
    try:
        from handlers_message_detectors import (
            _normalize_text,
            _normalize_arabic_for_compare,
            _is_arabic_dominant,
        )
        _HAS_DETECTOR_HELPERS = True
    except ImportError:
        _HAS_DETECTOR_HELPERS = False

        # 🆕 FIX-FALLBACK-1: حماية "الله" من إزالة "ال"
        # (يطابق detectors v4.1.0)
        _FALLBACK_KEEP_AL_WORDS = frozenset({
            "الله", "بالله", "تالله", "والله", "اللهم",
            "الذي", "التي", "الذين", "اللاتي", "اللواتي",
        })

        def _normalize_text(t: Any) -> str:
            return (str(t) if t is not None else "").lower().strip()

        def _normalize_arabic_for_compare(t: Any) -> str:
            """
            🔴 FIX-FALLBACK-1: يطابق detectors v4.1.0.

            ملاحظة: "الله" و"بالله" إلخ. لا تُفقد "ال" الخاصة بها.
            """
            if not t:
                return ""
            s = str(t)
            # إزالة التشكيل
            s = re.sub(
                r"[\u064B-\u065F\u0670\u06D6-\u06DC"
                r"\u06DF-\u06E8\u06EA-\u06ED\u0640]",
                "", s,
            )
            # إزالة غير العربي
            s = re.sub(r"[^\u0600-\u06FF\s]", "", s)
            # توحيد الألف/الياء/التاء
            s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
            s = s.replace("ى", "ي").replace("ة", "ه")
            # 🆕 FIX-FALLBACK-1: إزالة "ال" مع استثناء الكلمات المحفوظة
            words = s.split()
            result_words = []
            for w in words:
                if w in _FALLBACK_KEEP_AL_WORDS:
                    result_words.append(w)
                    continue
                if w.startswith("ال") and len(w) > 3:
                    result_words.append(w[2:])
                else:
                    result_words.append(w)
            s = "".join(result_words)
            s = re.sub(r"\s+", "", s)
            return s.strip()

        def _is_arabic_dominant(t: Any) -> bool:
            if not t:
                return False
            text = str(t)
            arabic = sum(1 for ch in text if "\u0600" <= ch <= "\u06FF")
            letters = sum(1 for ch in text if ch.isalpha())
            if letters == 0:
                return False
            return (arabic / letters) >= 0.6


try:
    from utils import get_banned_words_cached
    _HAS_BANNED_CACHE = True
except ImportError:
    _HAS_BANNED_CACHE = False

    async def get_banned_words_cached(chat_id: int) -> List[str]:
        try:
            from database import DB
            words = await DB.get_banned_words(chat_id)
            return list(words or [])
        except Exception:
            return []


try:
    from utils import invalidate_banned_words_cache_async as _inv_async
    _HAS_INV_ASYNC = True
except ImportError:
    _HAS_INV_ASYNC = False
    _inv_async = None


try:
    from utils import invalidate_banned_words_cache as _inv_sync
    _HAS_INV_SYNC = True
except ImportError:
    _HAS_INV_SYNC = False
    _inv_sync = None


try:
    from config import CONFIG
    _HAS_CONFIG = True
except ImportError:
    _HAS_CONFIG = False
    CONFIG = None


try:
    from database import DB
    _HAS_DB = True
except ImportError:
    _HAS_DB = False
    DB = None


# ═════════════════════════════════════════════════════════════════════════════
# 4. قائمة التحيات العربية
# ═════════════════════════════════════════════════════════════════════════════

_ARABIC_GREETINGS_RAW: frozenset = frozenset({
    "السلام عليكم", "سلام عليكم", "وعليكم السلام",
    "السلام عليكم ورحمة الله",
    "صباح الخير", "صباح النور", "صباح النور والسعادة",
    "مساء الخير", "مساء النور", "مساء الخير والسعادة",
    "كيف حالك", "كيف حالكم", "كيف الحال", "كيفكم", "كيفك",
    "شلونك", "شلونكم", "شخبارك", "شخباركم",
    "اهلا", "أهلا", "اهلا وسهلا", "أهلا وسهلا",
    "مرحبا", "مرحبتين", "هلا", "هلا والله", "هلاوسهلا",
    "يا هلا", "يا مرحبا",
    "شكرا", "شكراً", "مشكور", "مشكورة", "مشكورين",
    "جزاك الله", "جزاكم الله", "بارك الله", "بارك الله فيك",
    "الله يعطيك", "الله يعطيك العافية", "يعطيك العافية",
    "تسلم", "تسلمي", "تسلموا",
    "عفوا", "العفو", "على الرحب", "على الرحب والسعة",
    "تحياتي", "تحياتنا", "مع التحية",
    "الحمد لله", "الحمدلله", "بخير", "تمام", "زين",
    "طيب", "اوك", "اوكي", "ممتاز", "رائع", "جميل",
    "حلو", "حلوة", "زينة",
    "ياجماعه", "يا جماعة", "يا جماعه", "جماعة", "جماعه",
    "اخواني", "اخوان", "اخواتي", "اخوات",
    "شباب", "شبابنا", "بنات", "بناتنا",
    "تصبح على خير", "تصبحون على خير",
    "طابت ليلتكم", "طابت مساؤكم",
    "منورين", "منور", "نورت", "نورتي", "نورتوا",
    "الله يسعدك", "الله يسعدكم",
    "وفقك الله", "وفقكم الله",
    "بالتوفيق", "بالتوفيق للجميع",
})

_NORMALIZED_GREETINGS: frozenset = frozenset(
    _normalize_arabic_for_compare(g)
    for g in _ARABIC_GREETINGS_RAW
) - {""}


def is_arabic_greeting(text: str) -> bool:
    """
    هل النص تحية عربية طبيعية قصيرة؟

    🆕 v1.1.0 FIX-GREET-1:
        - تم تقييد الفحص بـ:
            • مساواة دقيقة كاملة (دائماً مسموحة)
            • احتواء bidir فقط إذا كان طول كل من الطرفين ≥ 4
        - سابقاً كان `w_norm in g_norm` يقبل كلمات قصيرة جداً
          مثل "با" (substring من "صباحخير") — مما يسمح بتجاوز
          فحص الكلمات المحظورة.

    🆕 v1.2.0 FIX-GREET-2:
        - المقام الآن = عدد الكلمات **العربية** فقط (بدل len(words)).
        - سابقاً: "السلام عليكم OK" → 3 كلمات، matched=2 → False.
        - الآن: يُهمَل "OK" غير العربي، matched=2/2 → True.

    📌 INTEG-3: التطبيع يستخدم _normalize_arabic_for_compare من
        detectors v4.1.0 (أو fallback مطابق بعد FIX-FALLBACK-1).
    """
    if not text:
        return False
    text = str(text).strip()
    if not text or len(text) > 40:
        return False
    if not _is_arabic_dominant(text):
        return False
    if re.search(r"(?:https?://|www\.|t\.me/|@\w+)", text):
        return False

    # 1. مساواة دقيقة كاملة (بعد التطبيع)
    normalized = _normalize_arabic_for_compare(text)
    if not normalized:
        return False
    if normalized in _NORMALIZED_GREETINGS:
        return True

    # 2. فحص كلمة-بكلمة (لنصوص متعددة الكلمات)
    words = re.findall(r"[^\s]+", text)
    if not words or len(words) > 4:
        return False

    # 🆕 FIX-GREET-2: اجمع فقط الكلمات التي لها تمثيل عربي
    #                 بعد التطبيع (غير فارغ).
    arabic_words: List[Tuple[str, str]] = []
    for w in words:
        w_norm = _normalize_arabic_for_compare(w)
        if w_norm:
            arabic_words.append((w, w_norm))

    if not arabic_words:
        return False

    matched = 0
    for _w_orig, w_norm in arabic_words:
        for g_norm in _NORMALIZED_GREETINGS:
            if not g_norm:
                continue

            # مساواة دقيقة — دائماً مقبولة
            if g_norm == w_norm:
                matched += 1
                break

            # 🆕 FIX-GREET-1: احتواء bidir مشروط بالطول
            if (
                len(w_norm) >= _MIN_LEN_FOR_SUBSTRING_MATCH
                and len(g_norm) >= _MIN_LEN_FOR_SUBSTRING_MATCH
            ):
                if g_norm in w_norm or w_norm in g_norm:
                    matched += 1
                    break

    # 🆕 FIX-GREET-2: المقام = عدد الكلمات العربية فقط
    return matched == len(arabic_words)


# ═════════════════════════════════════════════════════════════════════════════
# 5. تطبيع + فحص الكلمات المحظورة
# ═════════════════════════════════════════════════════════════════════════════

_WORD_SEP_CLASS = r'[\s\-_.|/*+=~^´`°•●○◦▪▫■□♦♢※]'


# 🆕 FIX-PATTERN-1: type جديد يقبل None كإشارة فشل.
#                   هذا يمنع إعادة محاولة compile لِنفس الكلمة الفاشلة.
_compiled_patterns: "OrderedDict[str, Optional[re.Pattern]]" = OrderedDict()
_compiled_spaced: "OrderedDict[str, Optional[re.Pattern]]" = OrderedDict()


def normalize_banned_word(word: Any) -> str:
    if not word:
        return ""
    return _normalize_text(str(word)).lower().strip()


def _get_pattern(word: str) -> Optional[re.Pattern]:
    """
    🆕 FIX-PATTERN-1: يُخزّن None عند فشل الترجمة، لتفادي إعادة المحاولة
    في كل استدعاء (كلمة واحدة فاشلة كانت تُعيد compile بلا نهاية).
    """
    # فحص مباشر — يشمل حالة القيمة None المخزَّنة
    if word in _compiled_patterns:
        _compiled_patterns.move_to_end(word)
        return _compiled_patterns[word]

    try:
        escaped = re.escape(word).replace(r'\ ', r'\s+')
        pat = re.compile(
            rf'(?<!\w){escaped}(?!\w)',
            re.IGNORECASE | re.UNICODE,
        )
    except Exception as e:
        logger.debug("_get_pattern(%r) compile failed: %s", word, e)
        # 🆕 خزّن None كإشارة "فشل سابق"
        _compiled_patterns[word] = None
        if len(_compiled_patterns) > _CACHE_MAX_PATTERNS:
            _compiled_patterns.popitem(last=False)
        return None

    _compiled_patterns[word] = pat
    if len(_compiled_patterns) > _CACHE_MAX_PATTERNS:
        _compiled_patterns.popitem(last=False)
    return pat


def _get_spaced_pattern(word: str) -> Optional[re.Pattern]:
    """
    🆕 FIX-PATTERN-1: نفس المعالجة — تخزين None عند الفشل أو الرفض.

    ملاحظة: كلمات أقصر من 3 أو أطول من 15 تُرفض كـ None وتُخزَّن.
    """
    if word in _compiled_spaced:
        _compiled_spaced.move_to_end(word)
        return _compiled_spaced[word]

    # شروط الرفض — تخزين None لتفادي إعادة الفحص
    if len(word) < 3 or len(word) > 15:
        _compiled_spaced[word] = None
        if len(_compiled_spaced) > _CACHE_MAX_PATTERNS:
            _compiled_spaced.popitem(last=False)
        return None

    try:
        chars = list(word)
        body = r'[\s\-_.|/*+=~^`•●○▪▫■□♦♢※]{1,2}'.join(
            re.escape(c) for c in chars
        )
        pat = re.compile(
            rf'(?<!\w){body}(?!\w)',
            re.IGNORECASE | re.UNICODE,
        )
    except Exception as e:
        logger.debug("_get_spaced_pattern(%r) compile failed: %s", word, e)
        _compiled_spaced[word] = None
        if len(_compiled_spaced) > _CACHE_MAX_PATTERNS:
            _compiled_spaced.popitem(last=False)
        return None

    _compiled_spaced[word] = pat
    if len(_compiled_spaced) > _CACHE_MAX_PATTERNS:
        _compiled_spaced.popitem(last=False)
    return pat


def _char_script(ch: str) -> str:
    if '\u0600' <= ch <= '\u06FF':
        return 'ar'
    if ch.isascii() and ch.isalpha():
        return 'lat'
    return 'other'


def _boundary_ok_at(
    compact_text: str,
    compact_word: str,
    idx: int,
) -> bool:
    """
    🆕 v1.2.0 FIX-BOUNDARY-1: فحص الحدود عند موضع معيّن فقط.

    يُستخدم من _compact_boundary_ok لكل موضع مطابقة.
    """
    if compact_word == compact_text:
        return True
    # الكلمات الطويلة (≥6) مقبولة بلا فحص حدود
    if len(compact_word) >= 6:
        return True

    end_idx = idx + len(compact_word)
    before = compact_text[idx - 1] if idx > 0 else ''
    after = compact_text[end_idx] if end_idx < len(compact_text) else ''

    if before and before.isalnum() and compact_word[0].isalnum():
        if _char_script(before) == _char_script(compact_word[0]):
            if _char_script(before) in ('ar', 'lat'):
                return False

    if after and after.isalnum() and compact_word[-1].isalnum():
        if _char_script(after) == _char_script(compact_word[-1]):
            if _char_script(after) in ('ar', 'lat'):
                return False

    return True


def _compact_boundary_ok(compact_text: str, compact_word: str) -> bool:
    """
    🆕 FIX-BOUNDARY-1: يفحص كل مواضع مطابقة compact_word في compact_text،
    ويقبل إذا كان **أي** موضع على حدود نظيفة.

    سابقاً: يفحص أول موضع فقط — قد يرفض مطابقة صحيحة لو أول
    ظهور محاط بحروف، بينما ظهور ثانٍ نظيف.
    """
    if not compact_text or not compact_word:
        return False
    try:
        start = 0
        # حماية من الحلقات اللانهائية + عدد مطابقات كبير
        max_iterations = 1000
        iterations = 0

        while iterations < max_iterations:
            iterations += 1
            idx = compact_text.find(compact_word, start)
            if idx == -1:
                return False

            if _boundary_ok_at(compact_text, compact_word, idx):
                return True

            # انتقل للموضع التالي
            start = idx + 1

        # لو تجاوزنا الحد — نرفض لأمان الأداء
        return False
    except Exception as e:
        logger.debug("_compact_boundary_ok error: %s", e)
        return True  # سلوك متسامح عند الخطأ (كما في v1.1.1)


def _truncate_at_word_boundary(text: str, limit: int) -> str:
    """
    🆕 FIX-TRUNC-1: يقطع النص عند حدود كلمة قدر الإمكان.

    يبحث عن آخر مسافة في آخر _TEXT_TRUNCATE_LOOKBACK حرف قبل
    الحد. إذا لم يجد، يقطع عنده مباشرةً.
    """
    if len(text) <= limit:
        return text

    lookback_start = max(0, limit - _TEXT_TRUNCATE_LOOKBACK)
    cutoff = text.rfind(" ", lookback_start, limit)

    if cutoff > 0:
        return text[:cutoff]

    # لا توجد مسافة — اقطع عند الحد
    return text[:limit]


def contains_banned_word(
    text: str,
    banned_word: str,
    *,
    skip_greeting_check: bool = False,
) -> bool:
    """
    هل النص يحتوي الكلمة؟ — يتخطى التحيات، يمنع substring القصير.

    🆕 v1.1.0 FIX-PERF-1:
        - معامل `skip_greeting_check` جديد.
        - عندما يُستدعى من `check_message` (الذي يفحص التحية مسبقاً)،
          مرّر skip_greeting_check=True لتجنّب فحص N+1.
        - الاستدعاء المباشر (خارج check_message) يبقى آمناً.

    🆕 v1.2.0 FIX-TRUNC-1:
        - قطع النص عند حدود كلمة بدل القطع الأعمى عند 4000 حرف.

    📌 INTEG-1: تُصدَّر هذه الدالة كـ `_bwm_contains` في
        handlers_message.py v7.18.17 (fallback فقط).
    """
    if not text or not banned_word:
        return False

    # 🆕 FIX-TRUNC-1: قطع على حدود كلمة
    if len(text) > _TEXT_TRUNCATE_LIMIT:
        text = _truncate_at_word_boundary(text, _TEXT_TRUNCATE_LIMIT)

    try:
        # 🆕 FIX-PERF-1: تخطّي الفحص إن طُلب صراحةً
        if not skip_greeting_check and is_arabic_greeting(text):
            return False

        norm_text = _normalize_text(text).lower()
        norm_word = normalize_banned_word(banned_word)
        if not norm_word:
            return False

        pat = _get_pattern(norm_word)
        if pat is not None and pat.search(norm_text):
            return True

        if len(norm_word) >= 3:
            spaced = _get_spaced_pattern(norm_word)
            if spaced is not None and spaced.search(norm_text):
                return True

        if len(norm_word) >= _COMPACT_MIN_LEN:
            compact_text = re.sub(_WORD_SEP_CLASS, '', norm_text)
            compact_word = re.sub(_WORD_SEP_CLASS, '', norm_word)
            if compact_word and compact_word in compact_text:
                if _compact_boundary_ok(compact_text, compact_word):
                    return True

        return False
    except Exception as e:
        logger.debug("contains_banned_word error: %s", e)
        return False


# ═════════════════════════════════════════════════════════════════════════════
# 6. cache المُدمج + إبطال الكاش
# ═════════════════════════════════════════════════════════════════════════════
#
# 🆕 FIX-ORDER-2: تعريف _invalidate_merged_cache **قبل** _invalidate_cache
#                 (سابقاً كان _invalidate_cache يستدعيه قبل أن يُعرَّف).
# ═════════════════════════════════════════════════════════════════════════════

# cache للقائمة المُدمجة (global + group) لكل chat_id
_merged_words_cache: "OrderedDict[int, Tuple[List[str], float]]" = OrderedDict()


def _invalidate_merged_cache(chat_id: Optional[int] = None) -> None:
    """
    🆕 v1.1.0 FIX-INV-1: إبطال cache القائمة المُدمجة.

    - chat_id=None           → مسح كل الـ cache.
    - chat_id=GLOBAL_CHAT_ID → مسح كل الـ cache (تغيير global يمسّ الجميع).
    - chat_id=<group_id>     → مسح إدخال المجموعة فقط.

    📌 INTEG-2: تُستدعى تلقائياً عند add/remove عبر _invalidate_cache.

    📌 v1.2.0: يبقى الاسم بصيغة "_" للتوافق الخلفي.
        تُصدَّر كـ public alias عبر handlers/messages/__init__.py.
    """
    try:
        if chat_id is None or chat_id == GLOBAL_CHAT_ID:
            _merged_words_cache.clear()
            return
        _merged_words_cache.pop(int(chat_id), None)
    except Exception as e:
        logger.debug("_invalidate_merged_cache(%r): %s", chat_id, e)


def _evict_merged_cache_if_needed() -> None:
    """
    🆕 FIX-CACHE-2: طرد الإدخالات الأقدم عند تجاوز الحد الأقصى،
    مع حماية **مدخل GLOBAL_CHAT_ID** (إن وُجد) من الطرد.

    سابقاً: `popitem(last=False)` قد يُخرج مدخل global تحت الضغط.
    """
    try:
        if len(_merged_words_cache) <= _MERGED_CACHE_MAX:
            return

        excess = len(_merged_words_cache) - _MERGED_CACHE_MAX
        if excess <= 0:
            return

        # اجمع المفاتيح القابلة للطرد (كل شيء عدا GLOBAL)
        victims = [
            k for k in _merged_words_cache.keys()
            if k != GLOBAL_CHAT_ID
        ]

        evicted = 0
        for k in victims:
            if evicted >= excess:
                break
            _merged_words_cache.pop(k, None)
            evicted += 1

        # إذا لم نُزِل العدد الكافي (كل المفاتيح كانت GLOBAL؟)،
        # احذف الأقدم قسراً — لكن في الواقع هذا لا يحدث.
    except Exception as e:
        logger.debug("_evict_merged_cache_if_needed: %s", e)


async def _invalidate_cache(scope_id: Optional[int] = None) -> bool:
    """
    إبطال كل الـ caches المتأثرة (المُدمج + الخارجي).

    🆕 FIX-INV-1 (v1.1.0): إبطال cache المُدمج أولاً.
    🆕 FIX-INV-2 (v1.2.0): يُرجع True إذا نجح **أي** مسار
        (سابقاً: يُرجع False حتى لو نجح إبطال المُدمج فقط).
    """
    merged_ok = True
    try:
        _invalidate_merged_cache(scope_id)
    except Exception as e:
        logger.debug("invalidate merged cache: %s", e)
        merged_ok = False

    external_ok = False

    if _HAS_INV_ASYNC and callable(_inv_async):
        try:
            r = _inv_async(scope_id) if scope_id is not None else _inv_async()
            if asyncio.iscoroutine(r):
                await r
            external_ok = True
        except Exception as e:
            logger.debug("invalidate async: %s", e)

    if not external_ok and _HAS_INV_SYNC and callable(_inv_sync):
        try:
            r = _inv_sync(scope_id) if scope_id is not None else _inv_sync()
            if asyncio.iscoroutine(r):
                await r
            external_ok = True
        except Exception as e:
            logger.debug("invalidate sync: %s", e)

    # 🆕 FIX-INV-2: نجاح أي مسار = True
    return merged_ok or external_ok


# ═════════════════════════════════════════════════════════════════════════════
# 7. الصلاحيات
# ═════════════════════════════════════════════════════════════════════════════

def is_developer(user_id: int) -> bool:
    if not user_id or not _HAS_CONFIG:
        return False

    try:
        owner = int(getattr(CONFIG, 'PRIMARY_OWNER_ID', 0) or 0)
        if owner and user_id == owner:
            return True
    except Exception:
        pass

    for attr in ('is_developer', 'is_dev', 'is_owner', 'is_super_admin'):
        fn = getattr(CONFIG, attr, None)
        if callable(fn):
            try:
                if fn(user_id):
                    return True
            except Exception:
                continue

    for attr in ('DEVELOPER_IDS', 'OWNER_IDS', 'ADMIN_IDS'):
        ids = getattr(CONFIG, attr, None)
        if ids:
            try:
                if user_id in ids:
                    return True
            except Exception:
                continue

    return False


async def is_group_admin(
    chat_id: int,
    user_id: int,
    bot: Any = None,
) -> bool:
    if not user_id:
        return False
    if is_developer(user_id):
        return True
    if not chat_id or chat_id == GLOBAL_CHAT_ID:
        return False

    if bot is not None:
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            status = getattr(member, 'status', None)
            if status in ('administrator', 'creator'):
                return True
        except Exception as e:
            logger.debug("get_chat_member(%s,%s): %s", chat_id, user_id, e)

    if _HAS_DB:
        try:
            db_type = getattr(DB, 'DB_TYPE', 'sqlite')
            if db_type == 'postgres':
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
            if row is not None:
                return True
        except Exception as e:
            logger.debug("check group_admin in DB: %s", e)

    return False


# ═════════════════════════════════════════════════════════════════════════════
# 8. Path 1 — Global (المطور)
# ═════════════════════════════════════════════════════════════════════════════

class GlobalBannedWordsPath:
    """مسار الكلمات المحظورة عالمياً (chat_id = -1)."""

    SCOPE_ID: int = GLOBAL_CHAT_ID

    @classmethod
    async def add(cls, word: str, user_id: int) -> Tuple[bool, str]:
        if not is_developer(user_id):
            return False, OpReason.NO_PERMS.value

        word = (word or "").strip()
        if not word or len(word) < MIN_WORD_LEN or len(word) > MAX_WORD_LEN:
            return False, OpReason.INVALID.value
        if not _HAS_DB:
            return False, OpReason.DB_ERROR.value

        try:
            result = await DB.add_banned_word(cls.SCOPE_ID, word, user_id)
        except Exception as e:
            logger.error(
                "Global.add(%r) DB error: %s", word, e, exc_info=True,
            )
            return False, OpReason.DB_ERROR.value

        added_ok, is_dup = (
            result if isinstance(result, tuple) and len(result) == 2
            else (bool(result), False)
        )

        if added_ok:
            await _invalidate_cache(cls.SCOPE_ID)
            logger.info("✅ GLOBAL-ADD | word=%r user=%s", word, user_id)
            return True, OpReason.ADDED.value
        if is_dup:
            return False, OpReason.DUPLICATE.value
        return False, OpReason.DB_ERROR.value

    @classmethod
    async def remove(cls, word: str, user_id: int) -> Tuple[bool, str]:
        if not is_developer(user_id):
            return False, OpReason.NO_PERMS.value

        word = (word or "").strip()
        if not word:
            return False, OpReason.INVALID.value
        if not _HAS_DB:
            return False, OpReason.DB_ERROR.value

        removed = False
        for method in (
            'remove_banned_word',
            'delete_banned_word',
            'remove_banned_word_by_text',
        ):
            fn = getattr(DB, method, None)
            if not callable(fn):
                continue
            try:
                r = fn(cls.SCOPE_ID, word)
                if asyncio.iscoroutine(r):
                    r = await r
                if r:
                    removed = True
                    break
            except Exception as e:
                logger.debug(
                    "DB.%s(%s,%r): %s", method, cls.SCOPE_ID, word, e,
                )
                continue

        if removed:
            await _invalidate_cache(cls.SCOPE_ID)
            logger.info("✅ GLOBAL-REMOVE | word=%r user=%s", word, user_id)
            return True, OpReason.REMOVED.value
        return False, OpReason.NOT_FOUND.value

    @classmethod
    async def list(cls) -> List[str]:
        try:
            words = await get_banned_words_cached(cls.SCOPE_ID)
            return list(words or [])
        except Exception as e:
            logger.debug("Global.list: %s", e)
            return []


# ═════════════════════════════════════════════════════════════════════════════
# 9. Path 2 — Group (مشرف المجموعة)
# ═════════════════════════════════════════════════════════════════════════════

class GroupBannedWordsPath:
    """مسار الكلمات المحظورة لمجموعة محددة."""

    @staticmethod
    async def add(
        chat_id: int,
        word: str,
        user_id: int,
        bot: Any = None,
    ) -> Tuple[bool, str]:
        if not chat_id or chat_id == GLOBAL_CHAT_ID:
            return False, OpReason.INVALID.value
        if not await is_group_admin(chat_id, user_id, bot=bot):
            return False, OpReason.NO_PERMS.value

        word = (word or "").strip()
        if not word or len(word) < MIN_WORD_LEN or len(word) > MAX_WORD_LEN:
            return False, OpReason.INVALID.value
        if not _HAS_DB:
            return False, OpReason.DB_ERROR.value

        try:
            result = await DB.add_banned_word(chat_id, word, user_id)
        except Exception as e:
            logger.error(
                "Group.add(%s, %r) DB error: %s",
                chat_id, word, e, exc_info=True,
            )
            return False, OpReason.DB_ERROR.value

        added_ok, is_dup = (
            result if isinstance(result, tuple) and len(result) == 2
            else (bool(result), False)
        )

        if added_ok:
            await _invalidate_cache(chat_id)
            logger.info(
                "✅ GROUP-ADD | chat=%s word=%r user=%s",
                chat_id, word, user_id,
            )
            return True, OpReason.ADDED.value
        if is_dup:
            return False, OpReason.DUPLICATE.value
        return False, OpReason.DB_ERROR.value

    @staticmethod
    async def remove(
        chat_id: int,
        word: str,
        user_id: int,
        bot: Any = None,
    ) -> Tuple[bool, str]:
        if not chat_id or chat_id == GLOBAL_CHAT_ID:
            return False, OpReason.INVALID.value
        if not await is_group_admin(chat_id, user_id, bot=bot):
            return False, OpReason.NO_PERMS.value

        word = (word or "").strip()
        if not word:
            return False, OpReason.INVALID.value
        if not _HAS_DB:
            return False, OpReason.DB_ERROR.value

        removed = False
        for method in (
            'remove_banned_word',
            'delete_banned_word',
            'remove_banned_word_by_text',
        ):
            fn = getattr(DB, method, None)
            if not callable(fn):
                continue
            try:
                r = fn(chat_id, word)
                if asyncio.iscoroutine(r):
                    r = await r
                if r:
                    removed = True
                    break
            except Exception as e:
                logger.debug("DB.%s(%s,%r): %s", method, chat_id, word, e)
                continue

        if removed:
            await _invalidate_cache(chat_id)
            logger.info(
                "✅ GROUP-REMOVE | chat=%s word=%r user=%s",
                chat_id, word, user_id,
            )
            return True, OpReason.REMOVED.value
        return False, OpReason.NOT_FOUND.value

    @staticmethod
    async def list(chat_id: int) -> List[str]:
        if not chat_id or chat_id == GLOBAL_CHAT_ID:
            return []
        try:
            words = await get_banned_words_cached(chat_id)
            return list(words or [])
        except Exception as e:
            logger.debug("Group.list(%s): %s", chat_id, e)
            return []


# ═════════════════════════════════════════════════════════════════════════════
# 10. BannedWordsManager (Router موحّد)
# ═════════════════════════════════════════════════════════════════════════════

class BannedWordsManager:

    @staticmethod
    async def add(
        word: str,
        user_id: int,
        scope: BannedScope,
        chat_id: Optional[int] = None,
        bot: Any = None,
    ) -> Tuple[bool, str]:
        """
        📌 INTEG-1: يُستدعى من handlers_message.py v7.18.17.
        توقيع ثابت — لا تكسره.
        """
        if scope == BannedScope.GLOBAL:
            success, reason = await GlobalBannedWordsPath.add(word, user_id)
        elif scope == BannedScope.GROUP:
            if not chat_id:
                return False, OpReason.INVALID.value
            success, reason = await GroupBannedWordsPath.add(
                chat_id, word, user_id, bot=bot,
            )
        else:
            return False, OpReason.INVALID.value

        logger.info(
            "📍 ROUTE-ADD | scope=%s chat=%s word=%r user=%s → %s",
            scope.value, chat_id, word, user_id,
            "OK" if success else f"FAIL({reason})",
        )
        return success, reason

    @staticmethod
    async def remove(
        word: str,
        user_id: int,
        scope: BannedScope,
        chat_id: Optional[int] = None,
        bot: Any = None,
    ) -> Tuple[bool, str]:
        """
        📌 INTEG-1: يُستدعى من handlers_message.py v7.18.17.
        توقيع ثابت — لا تكسره.
        """
        if scope == BannedScope.GLOBAL:
            success, reason = await GlobalBannedWordsPath.remove(word, user_id)
        elif scope == BannedScope.GROUP:
            if not chat_id:
                return False, OpReason.INVALID.value
            success, reason = await GroupBannedWordsPath.remove(
                chat_id, word, user_id, bot=bot,
            )
        else:
            return False, OpReason.INVALID.value

        logger.info(
            "📍 ROUTE-REMOVE | scope=%s chat=%s word=%r user=%s → %s",
            scope.value, chat_id, word, user_id,
            "OK" if success else f"FAIL({reason})",
        )
        return success, reason

    @staticmethod
    async def list(
        user_id: int,
        scope: BannedScope,
        chat_id: Optional[int] = None,
    ) -> List[str]:
        if scope == BannedScope.GLOBAL:
            return await GlobalBannedWordsPath.list()
        if scope == BannedScope.GROUP and chat_id:
            return await GroupBannedWordsPath.list(chat_id)
        return []

    @staticmethod
    async def get_words_for_filtering(chat_id: int) -> List[str]:
        """
        القائمة المُدمجة (global + group) للفلترة.

        🆕 v1.1.0 FIX-PERF-2:
            - cache محلي بـ TTL 30s لكل chat_id.
            - يُبطَل تلقائياً عند add/remove (عبر _invalidate_cache
              → _invalidate_merged_cache).

        🆕 v1.2.0 FIX-CACHE-1:
            - يُعيد نسخة (list copy) بدل المرجع المُخزَّن — يمنع
              المستدعين من العبث بالـ cache الداخلي.

        🆕 v1.2.0 FIX-TYPE-1:
            - يوحّد نوع chat_id (int) مبكراً لتجنّب تضارب cache-key
              مع type mismatch في DB.

        📌 INTEG-2: _MERGED_CACHE_TTL = 30s. بعد إضافة/إزالة كلمة،
            الـ cache يُبطَل فوراً — التغييرات تظهر خلال ثوانٍ.
        """
        # 🆕 FIX-TYPE-1: توحيد نوع chat_id
        try:
            cid_int = int(chat_id)
        except (TypeError, ValueError):
            logger.debug("get_words_for_filtering: chat_id غير صالح %r", chat_id)
            return []

        now = _time.monotonic()

        # فحص الـ cache
        entry = _merged_words_cache.get(cid_int)
        if entry is not None:
            cached_words, cached_at = entry
            if now - cached_at < _MERGED_CACHE_TTL:
                _merged_words_cache.move_to_end(cid_int)
                # 🆕 FIX-CACHE-1: إرجاع نسخة
                return list(cached_words)

        # بناء جديد
        result: List[str] = []
        seen: Set[str] = set()

        try:
            global_words = await get_banned_words_cached(GLOBAL_CHAT_ID)
            for w in global_words or []:
                n = normalize_banned_word(w)
                if n and n not in seen:
                    seen.add(n)
                    result.append(str(w))
        except Exception as e:
            logger.debug("get global words for filtering: %s", e)

        if cid_int and cid_int != GLOBAL_CHAT_ID:
            try:
                group_words = await get_banned_words_cached(cid_int)
                for w in group_words or []:
                    n = normalize_banned_word(w)
                    if n and n not in seen:
                        seen.add(n)
                        result.append(str(w))
            except Exception as e:
                logger.debug("get group words for filtering: %s", e)

        # خزّن النتيجة (نسخة مستقلة)
        try:
            _merged_words_cache[cid_int] = (list(result), now)
            _evict_merged_cache_if_needed()
        except Exception as e:
            logger.debug("cache store failed: %s", e)

        return result

    @staticmethod
    async def check_message(text: str, chat_id: int) -> Optional[str]:
        """
        فحص رسالة — يُرجع الكلمة المطابقة أو None.

        🆕 v1.1.0 FIX-PERF-1:
            - is_arabic_greeting تُستدعى مرة واحدة هنا.
            - contains_banned_word يُستدعى بـ skip_greeting_check=True
              (لأننا فحصنا مسبقاً).
            - سابقاً: N+1 استدعاء لـ is_arabic_greeting (N = عدد الكلمات).

        📌 INTEG-1: يُستدعى من handlers_message.py v7.18.17 في
            _handle_group_impl عبر BannedWordsManager.check_message().
            توقيع ثابت: (text, chat_id) → Optional[str].
        """
        if not text:
            return None
        if is_arabic_greeting(text):
            logger.debug(
                "AR-GREETING-SKIP | chat=%s text=%r",
                chat_id, text[:60],
            )
            return None

        words = await BannedWordsManager.get_words_for_filtering(chat_id)
        if not words:
            return None

        for bw in words:
            # 🆕 FIX-PERF-1: تخطّي فحص التحية (تمّ مسبقاً)
            if contains_banned_word(text, bw, skip_greeting_check=True):
                return bw
        return None

    @staticmethod
    def is_developer(user_id: int) -> bool:
        return is_developer(user_id)

    @staticmethod
    async def is_group_admin(
        chat_id: int,
        user_id: int,
        bot: Any = None,
    ) -> bool:
        return await is_group_admin(chat_id, user_id, bot=bot)

    @staticmethod
    async def invalidate_cache(scope_id: Optional[int] = None) -> bool:
        return await _invalidate_cache(scope_id)


# ═════════════════════════════════════════════════════════════════════════════
# 11. Public API
# ═════════════════════════════════════════════════════════════════════════════
#
# 🆕 FIX-EXPORT-1: __all__ لا يحتوي أسماء "_" بعد الآن.
#   الأسماء الداخلية لا تزال قابلة للاستيراد المباشر
#   (from X import _name), لكن غير مُصدَّرة عبر `from X import *`.
#
#   public aliases (invalidate_merged_cache, MERGED_CACHE_TTL, ...)
#   تُدار في handlers/messages/__init__.py.
# ═════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Classes
    "BannedWordsManager",
    "GlobalBannedWordsPath",
    "GroupBannedWordsPath",

    # Enums
    "BannedScope",
    "OpReason",

    # Constants
    "GLOBAL_CHAT_ID",
    "MIN_WORD_LEN",
    "MAX_WORD_LEN",

    # Functions
    "is_developer",
    "is_group_admin",
    "normalize_banned_word",
    "contains_banned_word",
    "is_arabic_greeting",

    # Version
    "__version__",
]


# ═════════════════════════════════════════════════════════════════════════════
# Load Beacon
# ═════════════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "✅ banned_words_manager v%s loaded | "
        "DUAL-PATH (global=%d, group) | "
        "greetings=%d | compact_min=%d | "
        "merged_cache_ttl=%.0fs | merged_cache_max=%d | "
        "detector_helpers=%s | db=%s | cache=%s | "
        "compat=(detectors=v4.1.0, handlers_message=v7.18.17)",
        __version__,
        GLOBAL_CHAT_ID,
        len(_ARABIC_GREETINGS_RAW),
        _COMPACT_MIN_LEN,
        _MERGED_CACHE_TTL,
        _MERGED_CACHE_MAX,
        "yes" if _HAS_DETECTOR_HELPERS else "no",
        "yes" if _HAS_DB else "no",
        "yes" if _HAS_BANNED_CACHE else "no",
    )
except Exception as _e_beacon:
    # 🆕 v1.2.0: بدل `pass` الصامت — سجّل السبب للـ debugging
    try:
        logger.debug("load beacon failed: %s", _e_beacon)
    except Exception:
        pass