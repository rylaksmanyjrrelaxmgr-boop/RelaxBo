#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_callback_base.py — ثوابت ودوال مساعدة لـ handlers_callback
=====================================================================
هذا الملف جزء من تقسيم handlers_callback.py (v9.4.32 → v9.7.8)

المحتوى:
    • ثوابت رقمية/نصية للاستخدام في كل الوحدات
    • قوائم القوائم (CONTEST_DURATIONS, _ANALYTICS_ALIASES ...)
    • دوال نقية بلا حالة:
        _trans, _fmt, _group_number, _row_to_dict,
        _coerce_int, _coerce_float, _safe_str,
        _md_to_html, _is_valid_url, _mask_id,
        _log_channel_cache_key, _make_user_cache_keys,
        _is_primary_owner

⚠️ لا تنقل هنا أي شيء يعتمد على:
    - ACTIVE_TASKS / _publish_semaphore
    - _sec_auth_cache / _post_count_cache / _security_stats_cache_local
    - context / update / query
هذه تبقى في handlers_callback.py (أو تُنقل في ملفات لاحقة).

=====================================================================
🆕 v9.7.8 (SECURITY-PREFIXES-FIX):
    🔴 FIX-1: إضافة _SECURITY_PREFIXES صريحة (22+ زر)
             السبب: dir(CB) قد لا يلتقط كل sec_* إذا لم تكن
             معرّفة في utils.CB.
    🔴 FIX-2: إضافة _SECURITY_SUB_PREFIXES (set_, sec_set_, sec_penalty_)
             السبب: الأزرار الفرعية تحتاج prefix لتوجيهها.
    🔴 FIX-3: إضافة _ACTION_PREFIXES (ban_, act_, pen_)
             السبب: أزرار الإجراءات تحتاج توجيه.
    🟠 FIX-4: إضافة _CONFIRM_SUFFIXES لتوجيه التأكيدات.
    🟠 FIX-5: إضافة _MENU_PREFIXES (auto_reply_, sched_, analytics_).
    🟢 NEW:   _ALL_KNOWN_PREFIXES = union of everything
    🟢 NEW:   دالة _is_known_prefix(data) للفحص السريع

🆕 v9.5.x:
    • تقسيم handlers_callback.py إلى وحدات
    • دوال مساعدة نقية
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
_VALID_URL_PATTERN = re.compile(r'^https?://[^\s]+$')


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
# 🆕 v9.7.8: قوائم prefixes صريحة
# =====================================================================

# ─── 1. أزرار الأمان الرئيسية ───
_SECURITY_PREFIXES: Set[str] = {
    # 🆕 v7.10.0 — الأزرار الستة الجديدة
    "sec_at_channel",
    "sec_tg_scheme",
    "sec_button_links",
    "sec_emails",
    "sec_protected_any",
    "sec_postbot",

    # الأزرار الأساسية
    "sec_links",
    "sec_mentions",
    "sec_forward",
    "sec_video",
    "sec_audio",
    "sec_anim",
    "sec_doc",
    "sec_sticker",
    "sec_service",
    "sec_poll",
    "sec_game",
    "sec_voice",
    "sec_videonote",
    "sec_nsfw",
    "sec_flood",
    "sec_slow",
    "sec_night",
    "sec_welcome",
    "sec_goodbye",
    "sec_approve_join",
    "sec_reject_join",
    "sec_banned_words",
    "sec_warn",

    # أزرار المجموعة
    "sec_welcome_text",
    "sec_goodbye_text",
    "sec_slow_mode_seconds",
    "sec_maxlen",
    "sec_penalty",
    "sec_del_pen",
    "sec_adv_act",
    "sec_act_log",
    "sec_auto_reply_menu",
    "sec_antiflood_settings",
    "sec_night_settings",
    "sec_violation_penalties",
    "sec_violation_settings",
    "sec_penalty_durations",
    "sec_warn_count",
    "sec_warn_penalty",
    "sec_warn_penalty_duration",
    "sec_warn_toggle",

    # أوامر التفعيل/التعطيل
    "sec_activate_all",
    "sec_deactivate_all",
    "sec_enable_all",
    "sec_disable_all",
    "sec_activate_all_confirm",
    "sec_deactivate_all_confirm",

    # إغلاق ورجوع
    "sec_close",
    "sec_back",
}


# ─── 2. الأزرار الفرعية (set_*, sec_set_*, sec_penalty_*) ───
_SECURITY_SUB_PREFIXES: Set[str] = {
    "set_warn_count",
    "set_duration",
    "set_warn_penalty",
    "set_antiflood_messages",
    "set_antiflood_seconds",
    "sec_set_mute_duration",
    "sec_set_ban_duration",
    "sec_set_restrict_duration",
    "sec_set_del_penalty",
    "sec_set_del_penalty_duration",
    "sec_set_violation_strikes",
    "sec_set_violation_duration",
    "sec_set_violation_penalty",
    "sec_set_antiflood_messages",
    "sec_set_antiflood_seconds",
    "sec_set_antiflood_penalty",
    "sec_set_night_start",
    "sec_set_night_end",
    "sec_set_night_action",
    "sec_antiflood_penalty",
    "sec_antiflood_duration",
    "sec_night_action",
    "sec_night_duration",
    "sec_penalty_ban",
    "sec_penalty_mute",
    "sec_penalty_kick",
    "sec_penalty_restrict",
    "sec_penalty_none",
    "sec_violation_penalty",
    "sec_toggle_banned_words",
}


# ─── 3. أزرار الإجراءات (ban_*, act_*, pen_*) ───
_ACTION_PREFIXES: Set[str] = {
    "ban_add",
    "ban_list",
    "ban_rem",
    "act_ban",
    "act_mute",
    "act_warn",
    "act_kick",
    "act_restrict",
    "act_unban",
    "act_pin",
    "act_log",
    "pen_ban",
    "pen_mute",
    "pen_kick",
    "pen_warn",
    "pen_restrict",
}


# ─── 4. القوائم الفرعية ───
_MENU_PREFIXES: Set[str] = {
    # auto_reply
    "auto_reply_menu",
    "auto_reply_toggle",
    "auto_reply_admins",
    "auto_reply_add",
    "auto_reply_del",
    "auto_reply_list",
    "auto_reply_stats",
    "auto_reply_reset",
    "auto_reply_reset_confirm",
    "auto_reply_manage",

    # schedule
    "sched_open",
    "sched_min",
    "sched_hour",
    "sched_day",
    "sched_time",

    # log channel
    "log_channel_menu",
    "log_channel_set",
    "log_channel_test",
    "log_channel_remove",
    "log_channel_btn",
    "log_channel_change",

    # analytics
    "analytics_user_growth",
    "analytics_top_channels",
    "analytics_publish_stats",
    "analytics_channels_rate",
    "analytics_subscriptions",
    "analytics_pool",
    "analytics_slow",
    "analytics_export",
}


# ─── 5. أزرار التأكيد ───
_CONFIRM_SUFFIXES: Set[str] = {
    "ch_del_confirm",
    "post_del_confirm",
    "grp_del_confirm",
    "delete_post_confirm",
    "post_clear_confirm",
}


# ─── 6. أزرار المسابقات ───
_CONTEST_PREFIXES: Set[str] = {
    "contest_duration",
    "contest_type_raffle",
    "contest_type_quiz",
    "contest_join",
    "contest_winners",
    "declare_winner_sel",
    "admin_declare_winner_sel",
    "admin_delete_contest",
}


# ─── 7. أزرار الإدارة ───
_ADMIN_PREFIXES: Set[str] = {
    "admin_toggle_ch",
    "admin_toggle_gr",
    "admin_restore_file",
    "admin_delete_contest",
    "adm_ch_page",
    "adm_gr_page",
}


# =====================================================================
# 🆕 v9.7.8: _KNOWN_CB_PREFIXES — توليد ديناميكي + صريح
# =====================================================================

_KNOWN_CB_PREFIXES: Set[str] = set()

# ─── 1. من CB.* (تلقائي) ───
try:
    for _attr_name in dir(CB):
        if _attr_name.startswith('_'):
            continue
        try:
            _val = getattr(CB, _attr_name)
        except Exception:
            continue
        if isinstance(_val, str) and _val:
            _KNOWN_CB_PREFIXES.add(_val)
except Exception as _e_cb:
    logger.warning(f"⚠️ _KNOWN_CB_PREFIXES build from CB.* failed: {_e_cb}")


# ─── 2. إضافات صريحة (v9.5.x القديمة) ───
_KNOWN_CB_PREFIXES.update({
    "finish_posts",
    "gift_plans",
    "redeem_gift",
    "updates_channel_btn",
    "admin_analytics",
    "refresh_btn",
})


# ─── 3. 🆕 v9.7.8: أزرار الأمان ───
_KNOWN_CB_PREFIXES.update(_SECURITY_PREFIXES)
_KNOWN_CB_PREFIXES.update(_SECURITY_SUB_PREFIXES)


# ─── 4. 🆕 v9.7.8: أزرار الإجراءات ───
_KNOWN_CB_PREFIXES.update(_ACTION_PREFIXES)


# ─── 5. 🆕 v9.7.8: القوائم الفرعية ───
_KNOWN_CB_PREFIXES.update(_MENU_PREFIXES)


# ─── 6. 🆕 v9.7.8: أزرار التأكيد ───
_KNOWN_CB_PREFIXES.update(_CONFIRM_SUFFIXES)


# ─── 7. 🆕 v9.7.8: المسابقات ───
_KNOWN_CB_PREFIXES.update(_CONTEST_PREFIXES)


# ─── 8. 🆕 v9.7.8: الإدارة ───
_KNOWN_CB_PREFIXES.update(_ADMIN_PREFIXES)


# ─── 9. 🆕 v9.7.8: أزرار عامة إضافية ───
_KNOWN_CB_PREFIXES.update({
    # Buy subscription
    "buy_sub",
    "buy_gift",

    # Channel/Group management
    "ch_page",
    "post_page",
    "grp_del",
    "grp_set",

    # Gift
    "gift",

    # Referral
    "ref_claim",
    "ref_list",

    # Support
    "support_ticket",

    # Panel
    "panel_lock",
    "panel_unlock",
    "panel_close",
})


# ─── Union موحّد للسريع ───
_ALL_KNOWN_PREFIXES: Set[str] = set(_KNOWN_CB_PREFIXES)


# =====================================================================
# 🆕 v9.7.8: دالة الفحص السريع
# =====================================================================

def _is_known_prefix(data: str) -> bool:
    """
    فحص سريع: هل data يبدأ بـ prefix معروف؟

    الاستخدام:
        if _is_known_prefix(data):
            # طابق base_data = parts[0]
        else:
            # استخدم data كاملاً
    """
    if not data:
        return False

    # فحص مباشر
    if data in _ALL_KNOWN_PREFIXES:
        return True

    # فحص إذا كان هناك ':' → اختبر الجزء قبلها
    if ':' in data:
        prefix = data.split(':', 1)[0]
        return prefix in _ALL_KNOWN_PREFIXES

    return False


def _get_base_prefix(data: str) -> str:
    """
    استخراج الـ base prefix من data.

    مثلاً:
        "sec_forward:-100123"  → "sec_forward"
        "sec_close"            → "sec_close"
        "unknown_xyz:99"       → "unknown_xyz:99" (كاملاً)
    """
    if not data:
        return data

    if data in _ALL_KNOWN_PREFIXES:
        return data

    if ':' in data:
        prefix = data.split(':', 1)[0]
        if prefix in _ALL_KNOWN_PREFIXES:
            return prefix

    return data


# =====================================================================
# الترجمة الموحدة
# =====================================================================

async def _trans(key: str, lang: str, default: str = "") -> str:
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
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text


# =====================================================================
# دوال مساعدة نقية
# =====================================================================

def _group_number(index: int) -> str:
    if 1 <= index <= len(GROUP_NUMBER_EMOJIS):
        return GROUP_NUMBER_EMOJIS[index - 1]
    return f"{index}."


def _is_primary_owner(user_id: int) -> bool:
    return _PRIMARY_OWNER_ID is not None and user_id == _PRIMARY_OWNER_ID


def _row_to_dict(row) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _coerce_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value, default='?') -> str:
    if value is None:
        return default
    s = str(value)
    return s if s.strip() else default


def _md_to_html(text: str) -> str:
    if not text or '**' not in text:
        return text
    return _BOLD_MD_PATTERN.sub(r"<b>\1</b>", text)


def _log_channel_cache_key(chat_id: int) -> str:
    return f"log_ch_menu_{chat_id}"


def _is_valid_url(url: Optional[str]) -> bool:
    if not url:
        return False
    if not isinstance(url, str):
        return False
    url_stripped = url.strip()
    if not url_stripped:
        return False
    if ' ' in url_stripped or '\n' in url_stripped or '\t' in url_stripped:
        return False
    if not _VALID_URL_PATTERN.match(url_stripped):
        return False
    return True


def _mask_id(id_value, prefix=3, suffix=2) -> str:
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
# 🆕 v9.7.8: diagnostics
# =====================================================================

def _log_prefixes_status() -> None:
    """يُسجّل عدد الـ prefixes المعروفة عند الإقلاع."""
    logger.info(
        "📋 _KNOWN_CB_PREFIXES: %d إجمالي | "
        "security=%d sub=%d action=%d menu=%d confirm=%d "
        "contest=%d admin=%d",
        len(_KNOWN_CB_PREFIXES),
        len(_SECURITY_PREFIXES),
        len(_SECURITY_SUB_PREFIXES),
        len(_ACTION_PREFIXES),
        len(_MENU_PREFIXES),
        len(_CONFIRM_SUFFIXES),
        len(_CONTEST_PREFIXES),
        len(_ADMIN_PREFIXES),
    )
    # تحقق من وجود الأزرار الحرجة
    critical = [
        "sec_forward", "sec_links", "sec_mentions",
        "sec_at_channel", "sec_tg_scheme", "sec_button_links",
        "sec_emails", "sec_protected_any", "sec_postbot",
    ]
    missing = [p for p in critical if p not in _KNOWN_CB_PREFIXES]
    if missing:
        logger.warning(
            "⚠️ _KNOWN_CB_PREFIXES: مفقود حرج: %s", missing
        )
    else:
        logger.debug("✅ كل prefixes الحرجة موجودة")


# استدعاء التشخيص عند الاستيراد (log level INFO)
try:
    _log_prefixes_status()
except Exception as _e:
    logger.debug(f"_log_prefixes_status: {_e}")


__all__ = [
    # ثوابت
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
    "_ANALYTICS_ALIASES", "_CONTEXT_KEYS_TO_CLEAR", "_CANвCANCEL_EXTRA_KEYS",
    "_BOLD_MD_PATTERN", "_VALID_URL_PATTERN",
    "_PRIMARY_OWNER_ID", "_KNOWN_CB_PREFIXES",

    # 🆕 v9.7.8 — قوائم prefixes
    "_SECURITY_PREFIXES",
    "_SECURITY_SUB_PREFIXES",
    "_ACTION_PREFIXES",
    "_MENU_PREFIXES",
    "_CONFIRM_SUFFIXES",
    "_CONTEST_PREFIXES",
    "_ADMIN_PREFIXES",
    "_ALL_KNOWN_PREFIXES",

    # دوال
    "_trans", "_fmt", "_group_number", "_is_primary_owner",
    "_row_to_dict", "_coerce_int", "_coerce_float", "_safe_str",
    "_md_to_html", "_log_channel_cache_key", "_is_valid_url",
    "_mask_id", "_make_user_cache_keys",

    # 🆕 v9.7.8 — دوال الفحص
    "_is_known_prefix",
    "_get_base_prefix",
    "_log_prefixes_status",
]