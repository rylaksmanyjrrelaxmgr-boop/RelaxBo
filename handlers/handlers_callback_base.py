#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_callback_base.py — ثوابت ودوال مساعدة لـ handlers_callback
=====================================================================
هذا الملف جزء من تقسيم handlers_callback.py (v9.4.32 → v9.7.x)

المحتوى:
    • ثوابت رقمية/نصية للاستخدام في كل الوحدات
    • قوائم القوائم (CONTEST_DURATIONS, _ANALYTICS_ALIASES ...)
    • دوال نقية بلا حالة:
        _trans, _fmt, _group_number, _row_to_dict,
        _coerce_int, _coerce_float, _safe_str,
        _md_to_html, _is_valid_url, _mask_id,
        _log_channel_cache_key, _make_user_cache_keys,
        _is_primary_owner, _strip_html, _truncate

⚠️ لا تنقل هنا أي شيء يعتمد على:
    - ACTIVE_TASKS / _publish_semaphore
    - _sec_auth_cache / _post_count_cache / _security_stats_cache_local
    - context / update / query
هذه تبقى في handlers_callback.py (أو تُنقل في ملفات لاحقة).

🆕 v9.7.0-base:
    ✅ _KNOWN_CB_PREFIXES — تسجيل عدد المفاتيح المُولّدة
    ✅ _strip_html — مساعد جديد لتنظيف HTML قبل العرض
    ✅ _truncate — مساعد جديد للاقتطاع الآمن
    ✅ توثيق أوضح لـ _make_user_cache_keys
    ✅ تحسين _md_to_html لمعالجة `**` بدون إغلاق
    ✅ type hints أكثر صرامة
=====================================================================
"""

import logging
import re
from typing import Dict, List, Optional, Tuple, Any, Set

from config import CONFIG

try:
    from utils import (
        get_text, CB, TranslationManager,
    )
except ImportError:
    from .utils import (
        get_text, CB, TranslationManager,
    )

logger = logging.getLogger(__name__)


# =====================================================================
# خريطة أسماء أزرار التحليلات
# =====================================================================

_ANALYTICS_ALIASES: Dict[str, str] = {
    "growth_30d_btn": "user_growth",
    "top_channels_btn": "top_channels",
    "publish_stats_btn": "publish_stats",
    "channels_rate_btn": "channels_rate",
    "subscriptions_btn": "subscriptions",
    "pool_live_btn": "pool",
    "slow_queries_btn": "slow",
    "export_excel_btn": "export",
    "user_growth": "user_growth",
    "top_channels": "top_channels",
    "publish_stats": "publish_stats",
    "channels_rate": "channels_rate",
    "subscriptions": "subscriptions",
    "pool": "pool",
    "slow": "slow",
    "export": "export",
}


# =====================================================================
# مدد المسابقات الجاهزة (key, fallback_label, seconds)
# =====================================================================

CONTEST_DURATIONS: Dict[str, Tuple[str, int]] = {
    "1h":  ("⏰ ساعة واحدة",  1 * 3600),
    "6h":  ("🕐 6 ساعات",     6 * 3600),
    "1d":  ("📅 يوم واحد",    1 * 86400),
    "3d":  ("📅 3 أيام",      3 * 86400),
    "1w":  ("📅 أسبوع",       7 * 86400),
    "2w":  ("📅 أسبوعان",     14 * 86400),
    "1mo": ("📅 شهر",         30 * 86400),
    "2mo": ("📅 شهران",       60 * 86400),
    "3mo": ("📅 3 أشهر",      90 * 86400),
    "6mo": ("📅 6 أشهر",      180 * 86400),
    "1y":  ("📅 سنة",         365 * 86400),
}


# =====================================================================
# ثوابت عامة
# =====================================================================

MAX_CAPTION_LENGTH = 1024
MAX_MESSAGE_LENGTH = 4096
MAX_BACKUPS = getattr(CONFIG, "MAX_BACKUPS", 10)
MAX_CONCURRENT_PUBLISH = 2
MAX_PUBLISH_DELAY_SECONDS = 60
MAX_TG_FILE_SIZE = 49 * 1024 * 1024
CALLBACK_MIN_INTERVAL = 0.5
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_CLEANUP_EVERY = 100
ADMIN_PAGE_SIZE = 10
SEC_AUTH_CACHE_TTL = 300
PUBLISH_ACQUIRE_TIMEOUT = 30
SEC_SETTINGS_CACHE_TTL = 5
SEC_STATS_CACHE_TTL = 30
LOG_CHANNEL_MENU_CACHE_TTL = 30
SUCCESS_RATE_GOOD_THRESHOLD = 70
SUCCESS_RATE_WARN_THRESHOLD = 30
DEFAULT_SUCCESS_RATE = 100.0

SEC_AUTH_CACHE_MAX_SIZE = 5000
POST_COUNT_CACHE_TTL = 5
POST_COUNT_CACHE_MAX_SIZE = 200

_BOLD_MD_PATTERN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
# ✅ v9.7.0: نمط أقوى يقبل `**` مغلقة فقط
_BOLD_MD_STRICT_PATTERN = re.compile(r"\*\*([^*]+?)\*\*")
_VALID_URL_PATTERN = re.compile(r'^https?://[^\s]+$')

# ✅ v9.7.0: نمط HTML للتنظيف (وسوم بسيطة)
_HTML_TAG_PATTERN = re.compile(r'<[^>]+>')


# =====================================================================
# PRIMARY_OWNER_ID — log critical عند الفشل
# =====================================================================

try:
    _PRIMARY_OWNER_ID = int(CONFIG.PRIMARY_OWNER_ID)
    if _PRIMARY_OWNER_ID <= 0:
        raise ValueError(
            f"PRIMARY_OWNER_ID must be positive (got {_PRIMARY_OWNER_ID})"
        )
except (TypeError, ValueError, AttributeError) as _poe:
    logger.critical(
        f"❌ PRIMARY_OWNER_ID غير صالح: {_poe} — "
        f"المالك سيفقد صلاحياته كاملة! "
        f"تحقق من CONFIG.PRIMARY_OWNER_ID"
    )
    _PRIMARY_OWNER_ID = None


# =====================================================================
# مفاتيح السياق التي تُنظَّف عند إلغاء الحالة
# =====================================================================

_CONTEXT_KEYS_TO_CLEAR = (
    'security_chat_id', 'auto_chat', 'adv_chat', 'schedule_ch',
    'ban_chat', 'contest_join', 'channel_page', 'post_page', 'sec_chat',
    'contest_title', 'contest_desc', 'contest_prize',
    'contest_end_date', 'contest_duration_label',
    'contest_duration_seconds',
)
_CANCEL_EXTRA_KEYS = ('pin_msg_id',)


GROUP_NUMBER_EMOJIS = [
    "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣",
    "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟",
]


# =====================================================================
# _KNOWN_CB_PREFIXES — توليد ديناميكي من CB.* + إضافات صريحة
# =====================================================================

_KNOWN_CB_PREFIXES: Set[str] = set()
try:
    _cb_attrs_scanned = 0
    for _attr_name in dir(CB):
        if _attr_name.startswith('_'):
            continue
        try:
            _val = getattr(CB, _attr_name)
        except Exception:
            continue
        if isinstance(_val, str) and _val:
            _KNOWN_CB_PREFIXES.add(_val)
            _cb_attrs_scanned += 1

    # ✅ v9.7.0: تسجيل عدد المفاتيح المُولّدة للتشخيص
    logger.debug(
        f"✅ _KNOWN_CB_PREFIXES: {_cb_attrs_scanned} مفتاح من CB.*"
    )
except Exception as _e_cb:
    logger.warning(f"⚠️ _KNOWN_CB_PREFIXES build from CB.* failed: {_e_cb}")

# ✅ إضافات صريحة (مفاتيح نصية ليست في CB.*)
_KNOWN_CB_PREFIXES.update({
    "finish_posts",
    "gift_plans",
    "redeem_gift",
    "updates_channel_btn",
    "admin_analytics",
    "refresh_btn",
})

if not _KNOWN_CB_PREFIXES:
    logger.warning(
        "⚠️ _KNOWN_CB_PREFIXES فارغة — قد تفشل قراءة بعض الأزرار"
    )


# =====================================================================
# الترجمة الموحدة
# =====================================================================

async def _trans(key: str, lang: str, default: str = "") -> str:
    """
    ترجمة موحّدة مع سلسلة fallback:
      1) TranslationManager.get_text (متزامن)
      2) get_text (async — قد يقرأ من DB)
      3) default المُمرَّر
      4) key نفسه
    """
    if not key:
        return default or ""

    try:
        if lang and lang != 'off':
            text = TranslationManager.get_text(lang, key)
            if text and text != key:
                return text
    except Exception as e:
        logger.debug(f"_trans({key},{lang}) TM: {e}")

    try:
        if lang and lang != 'off':
            text = await get_text(lang, key)
            if text and text != key:
                return text
    except Exception as e:
        logger.debug(f"_trans({key},{lang}) get_text: {e}")

    return default or key


def _fmt(text: str, **kwargs) -> str:
    """آمن: لا يرفع استثناء عند مفاتيح ناقصة."""
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text


# =====================================================================
# دوال مساعدة نقية
# =====================================================================

def _group_number(index: int) -> str:
    """
    يُعيد إيموجي رقم (1️⃣ → 🔟) للأرقام 1-10.
    للأرقام > 10 يُعيد "N." .
    """
    if 1 <= index <= len(GROUP_NUMBER_EMOJIS):
        return GROUP_NUMBER_EMOJIS[index - 1]
    return f"{index}."


def _is_primary_owner(user_id: int) -> bool:
    """فحص صريح وآمن لصلاحية المالك."""
    return _PRIMARY_OWNER_ID is not None and user_id == _PRIMARY_OWNER_ID


def _row_to_dict(row) -> Optional[Dict[str, Any]]:
    """تحويل صف DB إلى dict. يُعيد None عند الفشل."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _coerce_int(value, default=0) -> int:
    """تحويل آمن إلى int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value, default=0.0) -> float:
    """تحويل آمن إلى float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value, default='?') -> str:
    """تحويل آمن إلى str مع fallback."""
    if value is None:
        return default
    s = str(value)
    return s if s.strip() else default


def _md_to_html(text: str) -> str:
    """
    تحويل Markdown بسيط (`**bold**`) إلى HTML (`<b>bold</b>`).

    ✅ v9.7.0: استخدام النمط الصارم (يقبل `**` مغلقة فقط).
    """
    if not text or '**' not in text:
        return text
    return _BOLD_MD_STRICT_PATTERN.sub(r"<b>\1</b>", text)


def _strip_html(text: str) -> str:
    """
    ✅ v9.7.0: إزالة وسوم HTML البسيطة.

    مفيد عند إعادة استخدام نص في سياق لا يقبل HTML.
    """
    if not text:
        return ""
    try:
        return _HTML_TAG_PATTERN.sub('', text)
    except Exception:
        return text


def _truncate(text: str, max_len: int, ellipsis: str = "…") -> str:
    """
    ✅ v9.7.0: اقتطاع آمن مع إضافة ellipsis.

    Args:
        text: النص الأصلي
        max_len: أقصى طول (بما فيه ellipsis)
        ellipsis: السلسلة المُضافة عند الاقتطاع
    """
    if not text:
        return ""
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= len(ellipsis):
        return ellipsis[:max_len]
    return text[:max_len - len(ellipsis)].rstrip() + ellipsis


def _log_channel_cache_key(chat_id: int) -> str:
    """مفتاح الكاش الموحّد لقائمة قناة السجل."""
    return f"log_ch_menu_{chat_id}"


def _is_valid_url(url: Optional[str]) -> bool:
    """
    فحص صحة URL بشكل صارم.

    يرفض: None، غير-string، نصوص تحتوي whitespace، URLs غير http(s).
    """
    if not url:
        return False
    if not isinstance(url, str):
        return False
    url_stripped = url.strip()
    if not url_stripped:
        return False
    if (
        ' ' in url_stripped
        or '\n' in url_stripped
        or '\t' in url_stripped
        or '\r' in url_stripped
    ):
        return False
    if not _VALID_URL_PATTERN.match(url_stripped):
        return False
    return True


def _mask_id(id_value, prefix=3, suffix=2) -> str:
    """
    إخفاء جزء من المعرّف لأغراض الخصوصية.
    مثال: 1234567 → "123***67"
    """
    if id_value is None:
        return "***"
    s = str(id_value)
    if len(s) <= 5:
        return "***"
    return s[:prefix] + "***" + s[-suffix:]


def _make_user_cache_keys(
    user_id: int,
    channel_db_id: Optional[int] = None,
) -> List[str]:
    """
    تُنشئ قائمة مفاتيح الكاش المرتبطة بمستخدم معيّن.

    ⚠️ تحذير الصيانة:
        أنماط المفاتيح هذه مُنسَّقة لتطابق cache.py.
        إذا تغيّر نمط المفاتيح هناك، يجب تحديث هذه الدالة.

    Example:
        >>> _make_user_cache_keys(12345)
        ['start_data_12345', 'user_12345',
         'user_12345_True', 'user_12345_False', 'channels_12345']

        >>> _make_user_cache_keys(12345, channel_db_id=42)
        ['start_data_12345', 'user_12345',
         'user_12345_True', 'user_12345_False',
         'channels_12345', 'channel_info_42']
    """
    keys = [
        f"start_data_{user_id}",
        f"user_{user_id}",
        f"user_{user_id}_True",
        f"user_{user_id}_False",
        f"channels_{user_id}",
    ]
    if channel_db_id is not None:
        keys.append(f"channel_info_{channel_db_id}")
    return keys


# =====================================================================
# __all__ — التصدير الصريح
# =====================================================================

__all__ = [
    # ─── ثوابت ───
    "MAX_CAPTION_LENGTH", "MAX_MESSAGE_LENGTH", "MAX_BACKUPS",
    "MAX_CONCURRENT_PUBLISH", "MAX_PUBLISH_DELAY_SECONDS",
    "MAX_TG_FILE_SIZE", "CALLBACK_MIN_INTERVAL", "RATE_LIMIT_WINDOW",
    "RATE_LIMIT_CLEANUP_EVERY", "ADMIN_PAGE_SIZE", "SEC_AUTH_CACHE_TTL",
    "PUBLISH_ACQUIRE_TIMEOUT", "SEC_SETTINGS_CACHE_TTL",
    "SEC_STATS_CACHE_TTL", "LOG_CHANNEL_MENU_CACHE_TTL",
    "SUCCESS_RATE_GOOD_THRESHOLD", "SUCCESS_RATE_WARN_THRESHOLD",
    "DEFAULT_SUCCESS_RATE", "SEC_AUTH_CACHE_MAX_SIZE",
    "POST_COUNT_CACHE_TTL", "POST_COUNT_CACHE_MAX_SIZE",
    "CONTEST_DURATIONS", "GROUP_NUMBER_EMOJIS",
    "_ANALYTICS_ALIASES", "_CONTEXT_KEYS_TO_CLEAR", "_CANCEL_EXTRA_KEYS",
    "_BOLD_MD_PATTERN", "_BOLD_MD_STRICT_PATTERN",
    "_VALID_URL_PATTERN", "_HTML_TAG_PATTERN",
    "_PRIMARY_OWNER_ID", "_KNOWN_CB_PREFIXES",

    # ─── دوال ───
    "_trans", "_fmt", "_group_number", "_is_primary_owner",
    "_row_to_dict", "_coerce_int", "_coerce_float", "_safe_str",
    "_md_to_html", "_strip_html", "_truncate",
    "_log_channel_cache_key", "_is_valid_url",
    "_mask_id", "_make_user_cache_keys",
]