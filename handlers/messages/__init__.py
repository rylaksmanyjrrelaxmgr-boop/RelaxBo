#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers.messages — حزمة مسارات الرسائل المنفصلة
===============================================================================
🆕 v1.2.0 (EXPORTS-REFINED):
    ✅ تصدير بأسماء عامة نظيفة (public aliases) للعناصر الداخلية،
       بدلاً من تصدير أسماء تبدأ بـ "_" عبر __all__.
    ✅ توافق خلفي: الأسماء الداخلية القديمة (_invalidate_merged_cache,
       _merged_words_cache, _MERGED_CACHE_TTL, _MERGED_CACHE_MAX)
       لا تزال قابلة للاستيراد المباشر (لكنها خارج __all__).
    ✅ إعادة ترتيب __all__ حسب النوع:
       Classes → Constants → Functions → Version → Internal (public aliases).
    ✅ إضافة دالة قراءة للـ cache (get_merged_cache_snapshot) بدل تصدير
       الكائن القابل للتعديل مباشرةً.
    ✅ guard يفحص أن كل اسم في __all__ مُعرَّف فعلاً — يمنع crash
       بصمت مثل ما حدث سابقاً (خطأ سيريلي في _CANCEL_EXTRA_KEYS).

📌 دلالات الأسماء:
    • الأسماء العامة (بدون "_") هي الواجهة المُوصى بها.
    • الأسماء الداخلية (بـ "_") تبقى للتوافق الخلفي فقط.

📌 الاستخدام المُوصى به:
    # الواجهة العامة
    from handlers.messages import (
        BannedWordsManager,
        invalidate_merged_cache,      # ← جديد (public alias)
        get_merged_cache_snapshot,    # ← جديد (read-only)
    )

    # توافق خلفي
    from handlers.messages import _invalidate_merged_cache  # لا يزال يعمل
===============================================================================
"""

import logging as _logging
from typing import Any as _Any, Dict as _Dict

# ═════════════════════════════════════════════════════════════════════
# الاستيراد الأساسي (نفس المصادر مع aliases عامة)
# ═════════════════════════════════════════════════════════════════════

from .banned_words_manager import (
    # ─── Classes ───
    BannedWordsManager,
    GlobalBannedWordsPath,
    GroupBannedWordsPath,
    BannedScope,
    OpReason,

    # ─── Constants ───
    GLOBAL_CHAT_ID,
    MIN_WORD_LEN,
    MAX_WORD_LEN,

    # ─── Functions ───
    is_developer,
    is_group_admin,
    normalize_banned_word,
    contains_banned_word,
    is_arabic_greeting,

    # ─── Version ───
    __version__,

    # ─── Internal utilities → public aliases ───
    _invalidate_merged_cache as invalidate_merged_cache,
    _MERGED_CACHE_TTL as MERGED_CACHE_TTL,
    _MERGED_CACHE_MAX as MERGED_CACHE_MAX,

    # ─── Internal cache object (يُبقى للتوافق الخلفي، لا يُصدَّر عاماً) ───
    _merged_words_cache,
    _invalidate_merged_cache,
    _MERGED_CACHE_TTL,
    _MERGED_CACHE_MAX,
)

_logger = _logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# 🆕 v1.2.0: قراءة آمنة للـ cache (بدل تسريب الكائن القابل للتعديل)
# ═════════════════════════════════════════════════════════════════════

def get_merged_cache_snapshot() -> _Dict[int, _Any]:
    """
    يعيد نسخة (snapshot) من _merged_words_cache للقراءة فقط.

    يمنع المستدعين من العبث بالـ cache الداخلي. للاستخدام في
    التشخيص / الاختبارات / /cache_stats.

    Returns:
        dict: {chat_id: (words_list_copy, cached_at_monotonic)}
    """
    try:
        # نسخة عميقة بسيطة: النص (dict) جديد + نسخة من القائمة لكل إدخال
        return {
            int(cid): (list(words) if words else [], float(ts))
            for cid, (words, ts) in _merged_words_cache.items()
        }
    except Exception as e:
        _logger.debug("get_merged_cache_snapshot: %s", e)
        return {}


def get_merged_cache_size() -> int:
    """عدد الإدخالات في _merged_words_cache (للتشخيص)."""
    try:
        return len(_merged_words_cache)
    except Exception:
        return 0


# ═════════════════════════════════════════════════════════════════════
# __all__ — مرتَّب حسب النوع، أسماء عامة فقط
# ═════════════════════════════════════════════════════════════════════

__all__ = [
    # ─── Classes ───
    "BannedWordsManager",
    "GlobalBannedWordsPath",
    "GroupBannedWordsPath",
    "BannedScope",
    "OpReason",

    # ─── Constants ───
    "GLOBAL_CHAT_ID",
    "MIN_WORD_LEN",
    "MAX_WORD_LEN",
    "MERGED_CACHE_TTL",      # ← public alias
    "MERGED_CACHE_MAX",      # ← public alias

    # ─── Functions ───
    "is_developer",
    "is_group_admin",
    "normalize_banned_word",
    "contains_banned_word",
    "is_arabic_greeting",
    "invalidate_merged_cache",       # ← public alias
    "get_merged_cache_snapshot",     # ← جديد
    "get_merged_cache_size",         # ← جديد

    # ─── Version ───
    "__version__",
]


# ═════════════════════════════════════════════════════════════════════
# 🆕 v1.2.0: Guard — يمنع crash صامت إذا نُسي اسم في __all__
# ═════════════════════════════════════════════════════════════════════
#
# السبب: في v9.7.9 من handlers_callback_base.py، خطأ سيريلي
#       ("_CANвCANCEL_EXTRA_KEYS" بدل "_CANCEL_EXTRA_KEYS") جعل
#       __all__ يحتوي اسماً غير معرَّف → crash عند `from ... import *`.
#       هذا الـ guard يحوّل الخطأ إلى تحذير + يُسقط الاسم من __all__.
#
try:
    _missing_in_all = [name for name in __all__ if name not in globals()]
    if _missing_in_all:
        _logger.error(
            "🚨 handlers.messages __all__ يحتوي أسماء غير معرَّفة: %s "
            "— تمت إزالتها ديناميكياً لتفادي crash.",
            _missing_in_all,
        )
        __all__ = [name for name in __all__ if name in globals()]
except Exception as _e_guard:
    try:
        _logger.debug("__all__ guard failed: %s", _e_guard)
    except Exception:
        pass