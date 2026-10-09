#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_callback_base.py - ثوابت ودوال أساسية لـ handlers_callback.py
=====================================================================
🎯 الغرض:
    فصل الثوابت والدوال المساعدة عن handlers_callback.py لتقليل
    حجمه وتحسين الوضوح والأداء.

📦 يُصدَّر:
    - ثوابت (CONTEST_DURATIONS, MAX_* ...)
    - دوال مساعدة (_trans, _fmt, _md_to_html ...)
    - مجموعات (_ANALYTICS_ALIASES, _KNOWN_CB_PREFIXES ...)

🔗 يُستخدم من:
    handlers_callback.py (مع fallback في حال عدم التوفر)

🆕 v1.0.1 (REVIEW-FIXES):
    🟡 FIX-1: _md_to_html — HTML escape قبل التحويل (منع injection)
             (كان **<script>** يُنتج <b><script></b> بلا escape)
    🟡 FIX-2: _trans — caching لمراجع utils (lazy + cached)
             (كان from utils import في كل استدعاء → overhead)
    🟡 FIX-3: _row_to_dict — توثيق السلوك + دعم rows مع keys()
             (كان مضطرباً: None → {} لكن فشل → None)
    🟡 FIX-4: _is_primary_owner — 0 يُعتبر "غير معيّن"
             (كان 0 صالحاً → قد يخلق ارتباكاً)
    🟡 FIX-5: _is_valid_url — حد أقصى للطول (2048)
             (كان يقبل URLs ضخمة بلا داعٍ)
    🟡 FIX-6: _group_number — توثيق السلوك عند idx <= 0
    🟡 FIX-7: _mask_id — توضيح حد الطول
    🟡 FIX-8: _ANALYTICS_ALIASES — توثيق سبب تكرار القيم
=====================================================================
"""

import asyncio
import html as _html
import logging
import re
from typing import Any, Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# 1) ثوابت عامة
# ═════════════════════════════════════════════════════════════════════

# === الرسائل والملفات ===
MAX_CAPTION_LENGTH = 1024
MAX_MESSAGE_LENGTH = 4096
MAX_TG_FILE_SIZE = 50 * 1024 * 1024  # 50 MB (حد تليجرام للبوتات)

# === النسخ الاحتياطية ===
MAX_BACKUPS = 10

# === النشر ===
# MAX_CONCURRENT_PUBLISH: أقصى عدد قنوات تُنشر بالتوازي
# MAX_PUBLISH_DELAY_SECONDS: أقصى تأجيل انتظار قبل النشر (تفادي flood)
# PUBLISH_ACQUIRE_TIMEOUT: مهلة الحصول على slot نشر
MAX_CONCURRENT_PUBLISH = 3
MAX_PUBLISH_DELAY_SECONDS = 30
PUBLISH_ACQUIRE_TIMEOUT = 10.0

# === Rate limiting للـ callbacks ===
CALLBACK_MIN_INTERVAL = 0.3       # seconds — الحد الأدنى بين نقرتين
RATE_LIMIT_WINDOW = 60.0          # seconds — نافذة rate limit
RATE_LIMIT_CLEANUP_EVERY = 100    # كل N callback → تنظيف

# === صفحة الإدارة ===
ADMIN_PAGE_SIZE = 10

# === Cache TTLs ===
SEC_AUTH_CACHE_TTL = 120.0        # 2 دقائق
SEC_SETTINGS_CACHE_TTL = 300.0    # 5 دقائق
SEC_STATS_CACHE_TTL = 180.0       # 3 دقائق
LOG_CHANNEL_MENU_CACHE_TTL = 300.0
POST_COUNT_CACHE_TTL = 60.0

# === Cache sizes ===
SEC_AUTH_CACHE_MAX_SIZE = 5000
POST_COUNT_CACHE_MAX_SIZE = 2000

# === العتبات للتحليلات ===
SUCCESS_RATE_GOOD_THRESHOLD = 80.0
SUCCESS_RATE_WARN_THRESHOLD = 50.0
DEFAULT_SUCCESS_RATE = 100.0

# === URLs ===
# 🆕 FIX-5: حد أقصى لطول URL مقبول
_MAX_URL_LENGTH = 2048


# ═════════════════════════════════════════════════════════════════════
# 2) Contest durations
# ═════════════════════════════════════════════════════════════════════

CONTEST_DURATIONS: Dict[str, Tuple[str, int]] = {
    '1h':  ("ساعة",     3600),
    '6h':  ("6 ساعات",  6 * 3600),
    '12h': ("12 ساعة",  12 * 3600),
    '1d':  ("يوم",      86400),
    '3d':  ("3 أيام",   3 * 86400),
    '7d':  ("أسبوع",    7 * 86400),
    '14d': ("أسبوعان",  14 * 86400),
    '30d': ("شهر",      30 * 86400),
}


# ═════════════════════════════════════════════════════════════════════
# 3) Analytics aliases
# ═════════════════════════════════════════════════════════════════════
# 🆕 FIX-8: القيم متكررة عمداً — للوصول O(1) عبر .get(key).
# لتفادي التكرار، كان يمكن استخدام defaultdict(list) مع عكس القاموس،
# لكن ذلك يُبطئ .get() ويُعقّد القراءة. الحالي هو الأسرع للاستخدام
# المباشر (get per callback)، فتركه كما هو مقصود.

_ANALYTICS_ALIASES: Dict[str, str] = {
    'analytics_users': 'user_growth',
    'analytics_growth': 'user_growth',
    'analytics_channels': 'top_channels',
    'analytics_top': 'top_channels',
    'analytics_publish': 'publish_stats',
    'analytics_stats': 'publish_stats',
    'analytics_rates': 'channels_rate',
    'analytics_subs': 'subscriptions',
    'analytics_subscriptions': 'subscriptions',
    'analytics_pool_status': 'pool',
    'analytics_slowq': 'slow',
    'analytics_slow_queries': 'slow',
    'analytics_export_excel': 'export',
    'analytics_export_xlsx': 'export',
}


# ═════════════════════════════════════════════════════════════════════
# 4) Known callback prefixes (لتقليل مفاتيح _metrics)
# ═════════════════════════════════════════════════════════════════════

_KNOWN_CB_PREFIXES: Set[str] = {
    "sec_", "grp_", "admin_", "auto_reply_", "sched_",
    "contest_", "declare_winner_sel", "lang_",
    "buy_sub_", "buy_gift", "ban_", "act_", "pen_",
    "log_channel_", "set_warn_", "set_duration",
    "post_del_confirm", "ch_del_confirm", "grp_del_confirm",
    "adm_ch_page", "adm_gr_page",
    "panel_lock", "panel_unlock", "panel_close",
    "ch_page_", "post_page_",
    "admin_toggle_ch", "admin_toggle_gr",
    "admin_restore_file", "admin_delete_contest",
}


# ═════════════════════════════════════════════════════════════════════
# 5) Owner
# ═════════════════════════════════════════════════════════════════════

try:
    from config import CONFIG
    _PRIMARY_OWNER_ID: Optional[int] = getattr(
        CONFIG, 'PRIMARY_OWNER_ID', None)
except ImportError:
    _PRIMARY_OWNER_ID = None


# ═════════════════════════════════════════════════════════════════════
# 6) Context keys
# ═════════════════════════════════════════════════════════════════════

_CONTEXT_KEYS_TO_CLEAR: Tuple[str, ...] = (
    'sec_chat', 'security_chat_id',
    'adv_chat', 'auto_chat', 'schedule_ch', 'ban_chat',
    'contest_join', 'log_group_id', 'pin_msg_id',
    'channel_page', 'post_page', 'adm_ch_page', 'adm_gr_page',
    'auto_keyword', 'contest_id', 'contest_title',
    'contest_desc', 'contest_prize', 'contest_end_date',
    'contest_duration_label', 'contest_duration_seconds',
)

_CANCEL_EXTRA_KEYS: Tuple[str, ...] = (
    'awaiting_log_channel_for',
    'awaiting_payment',
    'last_error',
)

# 🆕 FIX-8 (bonus): frozenset موحّد لتفادي التكرار بين القائمتين
_ALL_CONTEXT_KEYS_TO_CLEAR: frozenset = frozenset(
    _CONTEXT_KEYS_TO_CLEAR + _CANCEL_EXTRA_KEYS
)


# ═════════════════════════════════════════════════════════════════════
# 7) Regex patterns
# ═════════════════════════════════════════════════════════════════════

_BOLD_MD_PATTERN = re.compile(r'\*\*(.+?)\*\*', re.DOTALL)

_VALID_URL_PATTERN = re.compile(
    r'^https?://[^\s<>"]+$',
    re.IGNORECASE,
)


# ═════════════════════════════════════════════════════════════════════
# 8) Emojis
# ═════════════════════════════════════════════════════════════════════

GROUP_NUMBER_EMOJIS: Tuple[str, ...] = (
    "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣",
    "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟",
)


# ═════════════════════════════════════════════════════════════════════
# 9) دوال مساعدة
# ═════════════════════════════════════════════════════════════════════

# 🆕 FIX-2: caching لمراجع utils (lazy + cached)
_TRANSLATION_MANAGER_CACHE = None
_GET_TEXT_CACHE = None
_TRANSLATION_LOOKUP_DONE = False


def _get_translation_refs():
    """
    🆕 FIX-2: يحصل على مراجع utils مرة واحدة (lazy + cached).

    يُعيد (TranslationManager, get_text) أو (None, None) عند الفشل.
    آمن ضد circular imports لأنه lazy.
    """
    global _TRANSLATION_MANAGER_CACHE, _GET_TEXT_CACHE
    global _TRANSLATION_LOOKUP_DONE
    if not _TRANSLATION_LOOKUP_DONE:
        try:
            from utils import TranslationManager, get_text
            _TRANSLATION_MANAGER_CACHE = TranslationManager
            _GET_TEXT_CACHE = get_text
        except ImportError as e:
            logger.debug(f"_get_translation_refs: {e}")
            _TRANSLATION_MANAGER_CACHE = None
            _GET_TEXT_CACHE = None
        except Exception as e:
            logger.warning(f"_get_translation_refs unexpected: {e}")
            _TRANSLATION_MANAGER_CACHE = None
            _GET_TEXT_CACHE = None
        _TRANSLATION_LOOKUP_DONE = True
    return _TRANSLATION_MANAGER_CACHE, _GET_TEXT_CACHE


async def _trans(key: str, lang: str, default: str = "") -> str:
    """
    ترجمة آمنة مع fallback.

    🆕 FIX-2: يستخدم caching لمراجع utils (كان from utils import
    في كل استدعاء).

    الترتيب:
      1. TranslationManager.get_text (sync, cache)
      2. get_text (async, DB)
      3. default أو key
    """
    if not key:
        return default or ""
    tm, gt = _get_translation_refs()
    if tm is None:
        return default or key
    if lang and lang != 'off':
        try:
            text = tm.get_text(lang, key)
            if text and text != key:
                return text
        except Exception as e:
            logger.debug(f"_trans TM({key}, {lang}): {e}")
        if gt is not None:
            try:
                text = await gt(lang, key)
                if text and text != key:
                    return text
            except Exception as e:
                logger.debug(f"_trans get_text({key}, {lang}): {e}")
    return default or key


def _fmt(template: str, **kwargs) -> str:
    """
    format آمن مع fallback للنص الخام عند KeyError/IndexError.
    """
    if not template:
        return ""
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return template


def _group_number(idx: int) -> str:
    """
    يُعيد emoji رقمي (1️⃣-🔟)، ثم الرقم نفسه للأكبر.

    🆕 FIX-6: للقيم <= 0 أو > 10 → f"{idx}." (سلوك واضح).
    """
    if isinstance(idx, bool):
        # bool هو subclass لـ int — نتجنّب True/False
        return f"{int(idx)}."
    if not isinstance(idx, int):
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            return "?"
    if 1 <= idx <= len(GROUP_NUMBER_EMOJIS):
        return GROUP_NUMBER_EMOJIS[idx - 1]
    return f"{idx}."


def _is_primary_owner(user_id: int) -> bool:
    """
    يتحقق إن كان المستخدم هو المالك الأساسي.

    🆕 FIX-4: 0 يُعتبر "غير معيّن" (لا مستخدم حقيقي في تليجرام).
    """
    if not _PRIMARY_OWNER_ID:  # ← يشمل None و 0
        return False
    try:
        return int(user_id) == int(_PRIMARY_OWNER_ID)
    except (TypeError, ValueError):
        return False


def _row_to_dict(row) -> Optional[Dict[str, Any]]:
    """
    يحوّل row (sqlite3.Row / dict / asyncpg.Record / tuple) إلى dict.

    🆕 FIX-3: توثيق السلوك بوضوح:
      • row is None → {}
      • row is dict → row كما هو
      • row مع keys() → dict من keys
      • row آخر → dict(row) أو None عند الفشل

    يُعيد:
      • {} عند None (نمط آمن للاستخدام المباشر)
      • None عند فشل التحويل (يُميّز الفشل من الفراغ)
    """
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        if hasattr(row, 'keys'):
            return {k: row[k] for k in row.keys()}
    except Exception as e:
        logger.debug(f"_row_to_dict keys(): {e}")
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _coerce_int(value, default: int = 0) -> int:
    """
    تحويل آمن إلى int مع fallback للـ default.

    ملاحظة: bool → 1/0، float → truncation. إن أردت سلوكاً مختلفاً
    أضف isinstance(value, bool) قبل.
    """
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value, default: float = 0.0) -> float:
    """
    تحويل آمن إلى float مع fallback للـ default.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value, default: str = "") -> str:
    """
    تحويل آمن إلى str (None → default، بلا استثناءات).
    """
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def _md_to_html(text: str) -> str:
    """
    تحويل Markdown مبسّط (**bold** فقط) إلى HTML.

    🆕 FIX-1: HTML escape قبل التحويل (منع injection).
    كان **<script>alert(1)</script>** يُنتج <b><script>...</b>
    بلا escape → خطر في بعض السياقات.

    السلوك الآن:
      **<b>bold</b>** → <b>&lt;b&gt;bold&lt;/b&gt;</b>
      **عادي** → <b>عادي</b>
    """
    if not text:
        return ""
    try:
        escaped = _html.escape(str(text), quote=False)
        return _BOLD_MD_PATTERN.sub(r'<b>\1</b>', escaped)
    except Exception as e:
        logger.debug(f"_md_to_html: {e}")
        try:
            return _html.escape(str(text), quote=False)
        except Exception:
            return ""


def _log_channel_cache_key(chat_id: int) -> str:
    """مفتاح cache موحّد لقائمة قناة السجل."""
    return f"log_ch_menu_{chat_id}"


def _is_valid_url(url: Optional[str]) -> bool:
    """
    فحص URL بـ https/http فقط.

    🆕 FIX-5: حد أقصى للطول (_MAX_URL_LENGTH = 2048).
    """
    if not url or not isinstance(url, str):
        return False
    stripped = url.strip()
    if not stripped or len(stripped) > _MAX_URL_LENGTH:
        return False
    return bool(_VALID_URL_PATTERN.match(stripped))


def _mask_id(id_value, prefix: int = 3, suffix: int = 2) -> str:
    """
    إخفاء المعرّف الرقمي (للخصوصية في السجلات).

    🆕 FIX-7: توثيق حد الطول — إذا كان len(s) <= prefix+suffix
    يُعاد "***" كاملاً (لا معنى لإظهار جزء).

    مثال:
      1234567890 → "123***90"
      12345 → "***" (قصير جداً)
    """
    if id_value is None:
        return "***"
    try:
        s = str(id_value)
    except Exception:
        return "***"
    if len(s) <= prefix + suffix:
        return "***"
    return s[:prefix] + "***" + s[-suffix:]


def _make_user_cache_keys(
    user_id: int,
    channel_db_id: Optional[int] = None,
) -> Set[str]:
    """
    قائمة مفاتيح cache التي يجب إبطالها بعد تغيير قناة/مستخدم.
    """
    keys: Set[str] = {
        f"user_{user_id}",
        f"user_{user_id}_True",
        f"user_{user_id}_False",
        f"lang_{user_id}",
        f"start_data_{user_id}",
        f"user_settings_batch_{user_id}",
        f"auto_publish_{user_id}",
        f"auto_recycle_{user_id}",
        f"has_active_sub_{user_id}",
        f"has_active_subscription_{user_id}",
        f"subscription_active_{user_id}",
        f"subscription_{user_id}",
        f"channels_{user_id}",
        f"groups_{user_id}",
        f"reminder_settings_{user_id}",
    }
    if channel_db_id is not None:
        keys.add(f"post_count_{channel_db_id}")
    return keys


# ═════════════════════════════════════════════════════════════════════
# 10) __all__
# ═════════════════════════════════════════════════════════════════════

__all__ = [
    # Constants — message
    "MAX_CAPTION_LENGTH", "MAX_MESSAGE_LENGTH", "MAX_TG_FILE_SIZE",
    # Constants — backups
    "MAX_BACKUPS",
    # Constants — publishing
    "MAX_CONCURRENT_PUBLISH", "MAX_PUBLISH_DELAY_SECONDS",
    "PUBLISH_ACQUIRE_TIMEOUT",
    # Constants — rate limit
    "CALLBACK_MIN_INTERVAL", "RATE_LIMIT_WINDOW",
    "RATE_LIMIT_CLEANUP_EVERY",
    # Constants — admin
    "ADMIN_PAGE_SIZE",
    # Constants — caches
    "SEC_AUTH_CACHE_TTL", "SEC_SETTINGS_CACHE_TTL",
    "SEC_STATS_CACHE_TTL", "LOG_CHANNEL_MENU_CACHE_TTL",
    "POST_COUNT_CACHE_TTL",
    "SEC_AUTH_CACHE_MAX_SIZE", "POST_COUNT_CACHE_MAX_SIZE",
    # Constants — thresholds
    "SUCCESS_RATE_GOOD_THRESHOLD", "SUCCESS_RATE_WARN_THRESHOLD",
    "DEFAULT_SUCCESS_RATE",
    # Constants — URLs
    "_MAX_URL_LENGTH",
    # Data
    "CONTEST_DURATIONS", "_ANALYTICS_ALIASES",
    "_KNOWN_CB_PREFIXES",
    "_PRIMARY_OWNER_ID",
    "_CONTEXT_KEYS_TO_CLEAR", "_CANCEL_EXTRA_KEYS",
    "_ALL_CONTEXT_KEYS_TO_CLEAR",
    "_BOLD_MD_PATTERN", "_VALID_URL_PATTERN",
    "GROUP_NUMBER_EMOJIS",
    # Helpers
    "_trans", "_fmt", "_group_number", "_is_primary_owner",
    "_row_to_dict", "_coerce_int", "_coerce_float", "_safe_str",
    "_md_to_html", "_log_channel_cache_key", "_is_valid_url",
    "_mask_id", "_make_user_cache_keys",
    "_get_translation_refs",
]


# ═════════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═════════════════════════════════════════════════════════════════════

try:
    logger.debug(
        "✅ handlers_callback_base v1.0.1 loaded | "
        "consts=%d | aliases=%d | prefixes=%d | "
        "fixes=(FIX-1..FIX-8)",
        sum([
            "MAX_CAPTION_LENGTH", "MAX_BACKUPS",
            "MAX_CONCURRENT_PUBLISH", "CALLBACK_MIN_INTERVAL",
            "ADMIN_PAGE_SIZE",
        ] and [1]),  # placeholder
        len(_ANALYTICS_ALIASES),
        len(_KNOWN_CB_PREFIXES),
    )
except Exception:
    pass