#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers.messages — حزمة مسارات الرسائل المنفصلة
===============================================================================
🆕 v1.1.1 (EXPORTS-UPDATE):
    ✅ إعادة تصدير العناصر الجديدة من banned_words_manager v1.1.1:
       - _invalidate_merged_cache   (إبطال cache يدوي)
       - _merged_words_cache        (للاختبارات/التشخيص)
       - _MERGED_CACHE_TTL          (ثابت TTL)
       - _MERGED_CACHE_MAX          (حد الحجم)
    📌 سبب التصدير: يسمح لـ handlers_message.py و handlers_callback.py
       بإبطال الـ cache يدوياً أو قراءة حجمه.
    📌 ملاحظة: العناصر تبدأ بـ "_" لأنها للاستخدام الداخلي/التشخيص،
       لكن تصديرها عبر __init__ يجعل الوصول أنظف:
           from handlers.messages import _invalidate_merged_cache
===============================================================================
"""

from .banned_words_manager import (
    # ─── Public API ───
    BannedWordsManager,
    GlobalBannedWordsPath,
    GroupBannedWordsPath,
    BannedScope,
    OpReason,
    GLOBAL_CHAT_ID,
    MIN_WORD_LEN,
    MAX_WORD_LEN,
    is_developer,
    is_group_admin,
    normalize_banned_word,
    contains_banned_word,
    is_arabic_greeting,
    # ─── Version ───
    __version__,
    # ─── 🆕 v1.1.1: Internal utilities ───
    _invalidate_merged_cache,
    _merged_words_cache,
    _MERGED_CACHE_TTL,
    _MERGED_CACHE_MAX,
)

__all__ = [
    # ─── Public API ───
    "BannedWordsManager",
    "GlobalBannedWordsPath",
    "GroupBannedWordsPath",
    "BannedScope",
    "OpReason",
    "GLOBAL_CHAT_ID",
    "MIN_WORD_LEN",
    "MAX_WORD_LEN",
    "is_developer",
    "is_group_admin",
    "normalize_banned_word",
    "contains_banned_word",
    "is_arabic_greeting",
    "__version__",
    # ─── 🆕 v1.1.1 ───
    "_invalidate_merged_cache",
    "_merged_words_cache",
    "_MERGED_CACHE_TTL",
    "_MERGED_CACHE_MAX",
]