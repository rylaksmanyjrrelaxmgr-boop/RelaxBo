#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
utils.py - الأدوات المساعدة للبوت (v7.5.1 — مُصلَّح)
=================================================================================
- جميع الدوال والفئات الموجودة سابقًا باقية كما هي
- تحسينات إضافية لا تؤثر على السلوك الحالي
- ✅ v7.5.1 إصلاحات جوهرية:
    * RateLimiter.acquire — نقل sleep خارج القفل (توازٍ حقيقي)
    * apply_penalty — إضافة username/first_name/chat_name (إصلاح "المستخدم غير موجود")
    * _do_backup — يستخدم DB.backup_database مع fallback SQLite
    * cleanup_old_data — يستخدم TimeUtils بدل SQLite-specific syntax
    * reminders — يستخدم RemindersMixin.send_subscription_reminders
    * _publish_single_channel — فحص tuple + user_id آمن
    * invalidate_auth_cache — يدعم الاستدعاء من ChatMemberHandler
    * TimeUtils.sql_iso — توحيد مع database.py
    * _group_admins_cache — حد أقصى للحجم
    * ErrorHandler — إشعار log_channel
=================================================================================
"""

import asyncio
import re
import json
import time
import html
import logging
import random
import importlib
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Tuple, Any, Union, Callable, Awaitable
from enum import Enum, auto
from collections import OrderedDict, deque, defaultdict
from abc import ABC, abstractmethod
from functools import lru_cache
from contextlib import suppress

try:
    import psutil
except ImportError:
    psutil = None

import aiohttp

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions, Update
from telegram.error import BadRequest, TimedOut
from telegram.ext import ContextTypes
from cachetools import TTLCache

import aiohttp.web as web

from config import CONFIG, PATHS
from database import DB

# استيراد اختياري للكاش الموحد (لا يؤثر إن لم يوجد)
try:
    from cache import settings_cache, banned_words_cache, auth_cache
    _HAS_UNIFIED_CACHE = True
except ImportError:
    _HAS_UNIFIED_CACHE = False

logger = logging.getLogger(__name__)


# =====================================================================
# 1. أدوات الوقت
# =====================================================================

class TimeUtils:
    """
    أدوات الوقت والتاريخ.

    ✅ v7.5.1: `sql_iso()` أصبحت بدون `+00:00` لتتوافق مع MySQL.
                `utc_iso()` تُرجع صيغة ISO كاملة مع timezone.
    """
    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def mecca_now() -> datetime:
        return TimeUtils.utc_now() + timedelta(hours=3)

    @staticmethod
    def utc_iso() -> str:
        """صيغة ISO كاملة (مع +00:00) — للاستخدامات العامة."""
        return TimeUtils.utc_now().isoformat() + "+00:00"

    @staticmethod
    def mecca_iso() -> str:
        return TimeUtils.mecca_now().isoformat()

    @staticmethod
    def sql_iso() -> str:
        """✅ v7.5.1: صيغة SQL بدون +00:00 (متوافقة مع MySQL DATETIME)."""
        return TimeUtils.utc_now().strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def mecca_to_utc(dt: Optional[datetime]) -> Optional[datetime]:
        return dt - timedelta(hours=3) if dt else None

    @staticmethod
    def utc_to_mecca(dt: Optional[datetime]) -> Optional[datetime]:
        return dt + timedelta(hours=3) if dt else None

    @staticmethod
    def safe_parse_iso(date_str: Optional[str]) -> Optional[datetime]:
        if not date_str:
            return None
        if isinstance(date_str, datetime):
            if date_str.tzinfo is not None:
                return date_str.astimezone(timezone.utc).replace(tzinfo=None)
            return date_str
        try:
            return datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            pass
        try:
            return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            pass
        try:
            return datetime.strptime(date_str, '%Y-%m-%d')
        except (ValueError, TypeError):
            return None


# =====================================================================
# 2. أدوات النصوص
# =====================================================================

class TextUtils:
    """أدوات معالجة النصوص."""
    @staticmethod
    def contains_link(text: Optional[str]) -> bool:
        if not text:
            return False
        return bool(re.search(r'(?:https?://|www\.|t\.me/|telegram\.me/)\S+', text, re.IGNORECASE))

    @staticmethod
    def contains_mention(text: Optional[str]) -> bool:
        return bool(re.search(r'@\w+', text)) if text else False

    @staticmethod
    def sanitize(text: str, max_len: int = 4096) -> str:
        if not text:
            return ""
        text = re.sub(r'[\u200b\u200c\u200d\u2060\uFEFF]', '', text)
        return text[:max_len]

    @staticmethod
    def escape_markdown_v2(text: str) -> str:
        if not text:
            return ""
        # ✅ v7.5.1: إزالة المتغير غير المستخدم
        return re.sub(r'([_*\[\]()~`>#+\-=|{}.!\\\'])', r'\\\1', text)

    @staticmethod
    def escape_html(text: str) -> str:
        if not text:
            return ""
        return html.escape(text)

    @staticmethod
    def truncate(text: str, max_len: int = 200) -> str:
        return text[:max_len] + ("..." if len(text) > max_len else "")


# =====================================================================
# 3. Rate Limiter
# =====================================================================

class RateLimiter:
    """
    محدد معدل الإرسال.

    ✅ v7.5.1: نقل `sleep` خارج `self._lock` لتوازٍ حقيقي.
    """
    def __init__(self, max_concurrent: int = 10, max_per_second: int = 30):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._last_calls = deque(maxlen=max_per_second * 2)
        self._lock = asyncio.Lock()
        self.max_per_second = max_per_second

    async def acquire(self, *args, **kwargs):
        """✅ v7.5.1: اكتساب إذن الإرسال مع احترام الحد الأقصى — بدون حجب متسلسل."""
        async with self.semaphore:
            while True:
                wait_time = 0.0
                async with self._lock:
                    now = time.time()
                    # إزالة الطلبات القديمة (> 1 ثانية)
                    while self._last_calls and now - self._last_calls[0] > 1:
                        self._last_calls.popleft()

                    if len(self._last_calls) < self.max_per_second:
                        self._last_calls.append(now)
                        return  # ✅ مسموح

                    # احتساب وقت الانتظار
                    wait_time = 1 - (now - self._last_calls[0])

                # ✅ النوم خارج القفل
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                else:
                    await asyncio.sleep(0.01)


RATE_LIMITER = RateLimiter(max_concurrent=15, max_per_second=30)


# =====================================================================
# 4. مقاييس الأداء
# =====================================================================

class MetricsCollector:
    """جمع إحصائيات الأداء."""
    def __init__(self):
        self.api_calls = deque(maxlen=1000)
        self.errors = deque(maxlen=1000)
        self.messages_processed = 0
        self.start_time = time.time()

    def record_api_call(self, method: str, duration: float):
        self.api_calls.append((time.time(), method, duration))

    def record_error(self, error_type: str, context: str = ""):
        self.errors.append((time.time(), error_type, context))

    def get_stats(self) -> dict:
        now = time.time()
        return {
            'api_calls_last_hour': sum(1 for t, _, _ in self.api_calls if now - t < 3600),
            'errors_last_hour': sum(1 for t, _, _ in self.errors if now - t < 3600),
            'uptime_seconds': int(now - self.start_time),
            'messages_processed': self.messages_processed,
            'total_api_calls': len(self.api_calls),
            'total_errors': len(self.errors)
        }

    def increment_messages(self):
        self.messages_processed += 1


METRICS = MetricsCollector()


# =====================================================================
# 5. كاش الردود
# =====================================================================

class AutoReplyCache:
    """كاش للردود التلقائية مع TTL."""
    def __init__(self, maxsize: int = 300, ttl: int = 300):
        self.cache = OrderedDict()
        self.maxsize = maxsize
        self.ttl = ttl

    def get(self, key: str):
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp > self.ttl:
                del self.cache[key]
                return None
            self.cache.move_to_end(key)
            return value
        return None

    def set(self, key: str, value: dict):
        self.cache[key] = (value, time.time())
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)

    def invalidate(self, key: str = None):
        if key:
            self.cache.pop(key, None)
        else:
            self.cache.clear()

    def clear(self):
        self.cache.clear()


_auto_reply_cache = AutoReplyCache(maxsize=300, ttl=300)

_security_settings_cache = {}
_security_settings_time = {}
_auto_reply_settings_cache = {}
_auto_reply_settings_time = {}


# =====================================================================
# 6. الترجمات
# =====================================================================

class TranslationManager:
    """إدارة الترجمات متعددة اللغات."""
    _translations: Dict[str, Dict] = {}
    _locales_dir: str = str(Path(__file__).resolve().parent / "locales")
    _default_lang: str = "ar"

    @classmethod
    def _load_translation_cached(cls, lang: str) -> Dict:
        """✅ v7.5.1: إزالة lru_cache — الاعتماد على cls._translations فقط."""
        if lang == 'off':
            lang = cls._default_lang
        if lang in cls._translations:
            return cls._translations[lang]

        file_path = Path(cls._locales_dir) / f"{lang}.json"
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                cls._translations[lang] = json.load(f)
                return cls._translations[lang]
        except FileNotFoundError:
            if lang != cls._default_lang:
                return cls._load_translation_cached(cls._default_lang)
            cls._translations[lang] = {}
            return {}
        except Exception as e:
            logger.error(f"❌ فشل قراءة ملف الترجمة {lang}: {e}")
            if lang != cls._default_lang:
                return cls._load_translation_cached(cls._default_lang)
            cls._translations[lang] = {}
            return {}

    @classmethod
    def load_translation(cls, lang: str) -> Dict:
        return cls._load_translation_cached(lang)

    @classmethod
    def get_text(cls, lang: str, key: str, **kwargs) -> str:
        translations = cls.load_translation(lang)
        template = translations.get(key)
        if template is None and lang != cls._default_lang:
            template = cls.load_translation(cls._default_lang).get(key)
        if template is None:
            template = key
        try:
            return template.format_map(kwargs)
        except KeyError:
            return template.format_map(defaultdict(str, kwargs))
        except Exception:
            return template

    @classmethod
    def get_available_languages(cls) -> Dict[str, str]:
        return {
            "ar": "العربية 🇸🇦",
            "en": "English 🇬🇧",
            "fr": "Français 🇫🇷",
            "tr": "Türkçe 🇹🇷",
            "zh": "中文 🇨🇳",
            "ru": "Русский 🇷🇺",
            "de": "Deutsch 🇩🇪",
            "es": "Español 🇪🇸",
            "it": "Italiano 🇮🇹",
            "pt": "Português 🇵🇹",
            "ja": "日本語 🇯🇵",
            "ko": "한국어 🇰🇷",
            "fa": "فارسی 🇮🇷",
            "ur": "اردو 🇵🇰",
            "nl": "Nederlands 🇳🇱",
            "pl": "Polski 🇵🇱",
            "hi": "हिन्दी 🇮🇳"
        }


async def get_text(lang: str, key: str, **kwargs) -> str:
    return TranslationManager.get_text(lang, key, **kwargs)


# =====================================================================
# 7. إدارة الحالات
# =====================================================================

class UserState(Enum):
    """حالات المستخدم."""
    NONE = auto()
    ADDING_POSTS = auto()
    WAIT_CHANNEL = auto()
    WAIT_MIN = auto()
    WAIT_HOUR = auto()
    WAIT_DAY = auto()
    WAIT_PUB_TIME = auto()
    WAIT_ADMIN_ADD = auto()
    WAIT_ADMIN_REM = auto()
    WAIT_BROADCAST = auto()
    WAIT_UPDATE = auto()
    WAIT_UPDATE_CH = auto()
    WAIT_FORCE = auto()
    WAIT_REM_DAYS = auto()
    WAIT_BAN = auto()
    WAIT_MUTE = auto()
    WAIT_WARN = auto()
    WAIT_KICK = auto()
    WAIT_RESTRICT = auto()
    WAIT_UNBAN = auto()
    WAIT_PIN = auto()
    WAIT_GROUP_BAN = auto()
    WAIT_REM_GROUP_BAN = auto()
    WAIT_GLOBAL_BAN = auto()
    WAIT_REM_GLOBAL_BAN = auto()
    WAIT_KEYWORD = auto()
    WAIT_REPLY = auto()
    WAIT_LOG_CH = auto()
    WAIT_CONTEST_TITLE = auto()
    WAIT_CONTEST_DESC = auto()
    WAIT_CONTEST_PRIZE = auto()
    WAIT_CONTEST_DATE = auto()
    WAIT_CONTEST_ANSWER = auto()
    WAIT_MAX_LEN = auto()
    WAIT_WARN_COUNT = auto()
    WAIT_AUTO_KEY = auto()
    WAIT_AUTO_REPLY = auto()
    WAIT_AUTO_DEL = auto()
    WAIT_IMPORT_FILE = auto()
    WAIT_GITHUB_URL = auto()
    WAIT_GRANT_FREE = auto()
    WAIT_PENALTY_DURATION = auto()
    WAIT_VIOLATION_STRIKES = auto()
    WAIT_VIOLATION_DURATION = auto()
    SUPPORT_MODE = auto()
    WAIT_REDEEM_GIFT = auto()
    WAIT_ANTIFLOOD_MESSAGES = auto()
    WAIT_ANTIFLOOD_SECONDS = auto()
    WAIT_NIGHT_START = auto()
    WAIT_NIGHT_END = auto()
    WAIT_WELCOME_TEXT = auto()
    WAIT_GOODBYE_TEXT = auto()
    WAIT_SLOW_MODE_SECONDS = auto()
    WAIT_PENALTY_DEFAULT_DURATION = auto()
    WAIT_CONTEST_WINNER = auto()
    WAIT_PENALTY_MUTE_DURATION = auto()
    WAIT_PENALTY_BAN_DURATION = auto()
    WAIT_PENALTY_RESTRICT_DURATION = auto()
    WAIT_MOOD = auto()
    WAIT_RESTORE = auto()
    WAIT_BACKUP_FILE = auto()


class StateManager:
    """إدارة حالات المستخدم مع مهلة زمنية."""
    _states: Dict[int, UserState] = {}
    _timestamps: Dict[int, float] = {}
    _timeout = 300

    @classmethod
    def get(cls, user_id: int) -> UserState:
        if user_id in cls._timestamps:
            if time.time() - cls._timestamps[user_id] > cls._timeout:
                cls.clear(user_id)
        return cls._states.get(user_id, UserState.NONE)

    @classmethod
    def set(cls, user_id: int, state: UserState) -> None:
        cls._states[user_id] = state
        cls._timestamps[user_id] = time.time()

    @classmethod
    def clear(cls, user_id: int) -> None:
        cls._states.pop(user_id, None)
        cls._timestamps.pop(user_id, None)

    @classmethod
    def is_expired(cls, user_id: int, timeout: int = None) -> bool:
        if user_id not in cls._timestamps:
            return False
        ttl = timeout or cls._timeout
        return time.time() - cls._timestamps[user_id] > ttl


# =====================================================================
# 8. تعريفات الأزرار (CB)
# =====================================================================

class CB:
    """ثوابت بيانات الأزرار."""
    MAIN = "main"
    BACK = "back"
    CANCEL = "cancel"
    HELP = "help"
    SETTINGS = "settings"
    LANGUAGE = "language"
    CHECK_SUB = "check_sub"

    CH_ADD = "ch_add"
    CH_LIST = "ch_list"
    CH_SEL = "ch_sel"
    CH_DEL = "ch_del"
    CH_STATS = "ch_stats"

    POST_ADD = "post_add"
    POST_PUB = "post_pub"
    POST_LIST = "post_list"
    POST_REC = "post_rec"
    POST_DEL = "post_del"
    POST_CLEAR = "post_clear"
    PUB_ALL = "pub_all"

    GROUPS = "groups"
    GRP_SET = "grp_set"

    TOGGLE_AUTO = "toggle_auto"
    TOGGLE_REC = "toggle_rec"

    SEC_CLOSE = "sec_close"
    SEC_ENABLE_ALL = "sec_enable_all"
    SEC_DISABLE_ALL = "sec_disable_all"
    SEC_NSFW = "sec_nsfw"
    SEC_DEL_PEN = "sec_del_pen"
    SEC_WARN = "sec_warn"
    SEC_VIOLATION_PENALTIES = "sec_violation_penalties"
    SEC_SET_VIOLATION_STRIKES = "sec_set_violation_strikes"
    SEC_SET_VIOLATION_DURATION = "sec_set_violation_duration"
    SEC_PENALTY_MUTE = "sec_penalty_mute"
    SEC_PENALTY_BAN = "sec_penalty_ban"
    SEC_PENALTY_RESTRICT = "sec_penalty_restrict"
    SEC_ANTIFLOOD_PENALTY = "sec_antiflood_penalty"
    SEC_NIGHT_ACTION = "sec_night_action"

    BAN_ADD = "ban_add"
    BAN_LIST = "ban_list"
    BAN_REM = "ban_rem"

    PENALTY = "penalty"
    PEN_BAN = "pen_ban"
    PEN_MUTE = "pen_mute"
    PEN_KICK = "pen_kick"
    PEN_WARN = "pen_warn"

    ADV_ACT = "adv_act"
    ACT_BAN = "act_ban"
    ACT_MUTE = "act_mute"
    ACT_WARN = "act_warn"
    ACT_KICK = "act_kick"
    ACT_RESTRICT = "act_restrict"
    ACT_PIN = "act_pin"
    ACT_LOG = "act_log"
    ACT_UNBAN = "act_unban"

    PANEL_LOCK = "panel_lock"
    PANEL_UNLOCK = "panel_unlock"
    PANEL_CLOSE = "panel_close"

    SUPPORT = "support"
    SUPPORT_TICKET = "support_ticket"

    TRIAL = "trial"
    SUBSCRIBE = "subscribe"
    PLANS = "plans"
    INVOICES = "invoices"

    DEVELOPER = "developer"

    REFERRAL = "referral"
    REF_CLAIM = "ref_claim"
    REF_LIST = "ref_list"

    REMINDER = "reminder"
    REM_TOGGLE_SUB = "rem_sub"
    REM_TOGGLE_DAILY = "rem_daily"
    REM_TOGGLE_WEEKLY = "rem_weekly"
    REM_SET_DAYS = "rem_days"
    REM_LANG = "rem_lang"

    TRANSLATION = "translation"
    TRANS_OFF = "trans_off"
    TRANS_SET = "trans_set"

    CONTESTS = "contests"
    CONTEST_JOIN = "contest_join"
    CONTEST_WINNERS = "contest_winners"
    DECLARE_WINNER_SEL = "declare_winner_sel"

    SCHED_MIN = "sched_min"
    SCHED_HOUR = "sched_hour"
    SCHED_DAY = "sched_day"
    SCHED_TIME = "sched_time"

    ADMIN = "admin"
    ADMIN_USERS = "admin_users"
    ADMIN_BANNED = "admin_banned"
    ADMIN_UNBAN_ALL = "admin_unban_all"
    ADMIN_CHANNELS = "admin_channels"
    ADMIN_BANNED_CH = "admin_banned_ch"
    ADMIN_ACTIVATE_CH = "admin_activate_ch"
    ADMIN_GROUPS = "admin_groups"
    ADMIN_BANNED_GR = "admin_banned_gr"
    ADMIN_UNBAN_GR = "admin_unban_gr"
    ADMIN_ADD_ADMIN = "admin_add_admin"
    ADMIN_REM_ADMIN = "admin_rem_admin"
    ADMIN_LIST_ADMINS = "admin_list_admins"
    ADMIN_RAM = "admin_ram"
    ADMIN_STATS = "admin_stats"
    ADMIN_METRICS = "admin_metrics"
    ADMIN_UPTIME = "admin_uptime"
    ADMIN_BACKUP = "admin_backup"
    ADMIN_RESTORE = "admin_restore"
    ADMIN_RESTORE_SEL = "admin_restore_sel"
    ADMIN_SEND_UPDATE = "admin_send_update"
    ADMIN_SET_UPDATE_CH = "admin_set_update_ch"
    ADMIN_SHOW_UPDATE = "admin_show_update"
    ADMIN_FORCE_SUB = "admin_force_sub"
    ADMIN_SET_FORCE = "admin_set_force"
    ADMIN_BROADCAST = "admin_broadcast"
    ADMIN_TICKETS = "admin_tickets"
    ADMIN_DEL_TICKETS = "admin_del_tickets"
    ADMIN_LOG_CH = "admin_log_ch"
    ADMIN_SET_LOG_CH = "admin_set_log_ch"
    ADMIN_REPLIES = "admin_replies"
    ADMIN_ADD_REPLY = "admin_add_reply"
    ADMIN_LIST_REPLIES = "admin_list_replies"
    ADMIN_DEL_REPLY = "admin_del_reply"
    ADMIN_BANNED_WORDS = "admin_banned_words"
    ADMIN_ADD_BANNED = "admin_add_banned"
    ADMIN_LIST_BANNED = "admin_list_banned"
    ADMIN_REM_BANNED = "admin_rem_banned"
    ADMIN_CREATE_CONTEST = "admin_create_contest"
    ADMIN_DECLARE_WINNER = "admin_declare_winner"
    ADMIN_DECLARE_WINNER_SEL = "admin_declare_winner_sel"
    ADMIN_DEL_CONTEST = "admin_del_contest"
    ADMIN_EXPORT_REPLIES = "admin_export_replies"
    ADMIN_IMPORT_REPLIES = "admin_import_replies"
    ADMIN_IMPORT_GITHUB = "admin_import_github"
    ADMIN_REFRESH_CACHE = "admin_refresh_cache"
    ADMIN_INVOICES = "admin_invoices"
    ADMIN_PAYMENT_LOGS = "admin_payment_logs"
    ADMIN_GRANT_FREE = "admin_grant_free"
    ADMIN_UPLOAD_BACKUP = "admin_upload_backup"
    ADMIN_DISABLE_FORCE = "admin_disable_force"

    AUTO_REPLY_MENU = "auto_reply_menu"
    AUTO_REPLY_TOGGLE = "auto_reply_toggle"
    AUTO_REPLY_ADMINS = "auto_reply_admins"
    AUTO_REPLY_RESET = "auto_reply_reset"
    AUTO_REPLY_STATS = "auto_reply_stats"
    AUTO_REPLY_ADD = "auto_reply_add"
    AUTO_REPLY_DEL = "auto_reply_del"
    AUTO_REPLY_LIST = "auto_reply_list"


# =====================================================================
# 9. مصنع الكيبوردات
# =====================================================================

class KeyboardFactory:
    """مصنع لوحات المفاتيح."""
    _configs: Dict[str, Dict] = {}
    _default_lang: str = "ar"
    _config_path_template: str = str(Path(__file__).resolve().parent / "buttons_config_{lang}.json")

    _NO_CHAT_ID_BUTTONS = {
        "sec_close", "panel_close", "back", "main", "cancel",
        "help", "settings", "language", "check_sub",
        "toggle_auto", "toggle_rec", "plans", "subscribe",
        "support", "support_ticket", "developer", "trial",
        "contests", "contest_winners", "referral", "ref_claim",
        "ref_list", "reminder", "rem_sub", "rem_daily",
        "rem_weekly", "rem_days", "translation", "trans_off",
        "invoices", "groups", "admin", "panel_close",
        "pub_all", "post_add", "post_pub", "post_list", "post_rec",
        "admin_uptime"
    }

    _default_texts = {
        "back": "🔙 رجوع",
        "main": "🌿 الرئيسية",
        "add_group_button": "➕ أضف البوت لمجموعة",
        "security_button": "⚙️ أمان {name}",
        "ch_add": "➕ إضافة قناة",
        "sec_links": "🔗 الروابط",
        "sec_mentions": "👤 المعرفات",
        "sec_slow": "🐢 بطيء",
        "sec_flood": "🌊 الفيضان",
        "sec_video": "🎬 فيديو",
        "sec_audio": "🎵 موسيقى",
        "sec_anim": "🎞️ متحرك",
        "sec_service": "🗑️ رسائل الخدمة",
        "sec_doc": "📄 ملفات",
        "sec_sticker": "🖼️ ملصقات",
        "sec_forward": "📨 مُعاد",
        "sec_poll": "📊 استطلاع",
        "sec_game": "🎮 ألعاب",
        "sec_voice": "🎤 صوتي",
        "sec_videonote": "🎥 فيديو نوت",
        "sec_banned_words": "🚫 كلمات محظورة",
        "sec_welcome": "🎯 ترحيب",
        "sec_goodbye": "👋 وداع",
        "sec_night": "🌙 وضع ليلي",
        "sec_approve_join": "✅ موافقة انضمام",
        "sec_reject_join": "❌ رفض انضمام",
        "sec_nsfw": "🔞 NSFW",
        "sec_maxlen": "📏 طول الرسالة",
        "sec_warn": "⚠️ تحذيرات",
        "sec_penalty": "🚫 العقوبات",
        "sec_del_pen": "🗑️ عقوبة الحذف",
        "sec_adv_act": "🛠️ إجراءات متقدمة",
        "sec_act_log": "📋 سجل المشرفين",
        "sec_auto_reply_menu": "🤖 الردود التلقائية",
        "sec_antiflood_settings": "🌊 إعدادات الفيضان",
        "sec_night_settings": "🌙 إعدادات الليل",
        "sec_penalty_durations": "⏱️ مدد العقوبات",
        "sec_violation_penalties": "🚨 المخالفات",
        "sec_enable_all": "✅ تفعيل الكل",
        "sec_disable_all": "❌ تعطيل الكل",
        "sec_close": "🔒 إغلاق",
        "auto_reply_toggle": "🔘 تفعيل/تعطيل",
        "auto_reply_admins": "👤 للمشرفين فقط",
        "auto_reply_add": "➕ إضافة",
        "auto_reply_del": "🗑️ حذف",
        "auto_reply_list": "📋 القائمة",
        "auto_reply_stats": "📊 إحصائيات",
        "auto_reply_reset": "🔄 إعادة تعيين",
        "act_ban": "🚫 حظر",
        "act_mute": "🔇 كتم",
        "act_warn": "⚠️ تحذير",
        "act_kick": "👢 طرد",
        "act_restrict": "🔒 تقييد",
        "act_unban": "🔓 فك حظر",
        "act_pin": "📌 تثبيت",
        "act_log": "📋 سجل",
        "pen_ban": "🚫 حظر",
        "pen_mute": "🔇 كتم",
        "pen_kick": "👢 طرد",
        "pen_warn": "⚠️ تحذير",
        "ban_add": "➕ إضافة كلمة",
        "ban_list": "📋 القائمة",
        "ban_rem": "🗑️ حذف كلمة",
        # ✅ v7.5.1: إضافة نصوص الأزرار الناقصة
        "buy_sub_1": "1 يوم ⭐",
        "buy_sub_7": "7 أيام ⭐",
        "buy_sub_30": "30 يوم ⭐",
        "buy_sub_90": "90 يوم ⭐",
        "buy_sub_365": "365 يوم ⭐",
        "gift_plans": "🎁 الهدايا",
        "redeem_gift": "🎟️ استبدال كود",
        "panel_close": "🔒 إغلاق",
        "sec_links_on": "🔗 الروابط ✅",
    }

    @classmethod
    def _load_config_for_lang(cls, lang: str) -> Dict:
        if lang == 'off':
            lang = cls._default_lang

        if lang in cls._configs:
            return cls._configs[lang]

        file_path = cls._config_path_template.format(lang=lang)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                cls._configs[lang] = config
                logger.info(f"✅ تم تحميل buttons_config_{lang}.json: {len(config.get('texts', {}))} مفتاح")
                return config
        except FileNotFoundError:
            if lang != cls._default_lang:
                logger.warning(f"⚠️ ملف buttons_config_{lang}.json غير موجود، سيتم استخدام اللغة الافتراضية")
                return cls._load_config_for_lang(cls._default_lang)
            else:
                logger.warning("⚠️ buttons_config_ar.json غير موجود، سيتم استخدام إعدادات افتراضية")
                default_config = {"texts": cls._default_texts, "menus": {}}
                cls._configs[cls._default_lang] = default_config
                return default_config
        except Exception as e:
            logger.error(f"❌ خطأ في قراءة buttons_config_{lang}.json: {e}")
            if lang != cls._default_lang:
                return cls._load_config_for_lang(cls._default_lang)
            else:
                default_config = {"texts": cls._default_texts, "menus": {}}
                cls._configs[cls._default_lang] = default_config
                return default_config

    @classmethod
    def load_config(cls):
        cls._load_config_for_lang(cls._default_lang)

    @classmethod
    def get_config(cls, lang: str = None) -> Dict:
        if not lang:
            lang = cls._default_lang
        return cls._load_config_for_lang(lang)

    @classmethod
    def get_text(cls, key: str, lang: str = None) -> str:
        config = cls.get_config(lang)
        text = config.get("texts", {}).get(key)
        if text is not None:
            return text
        return cls._default_texts.get(key, key)

    @classmethod
    def get_menu(cls, menu_name: str, lang: str = None) -> List[List[str]]:
        config = cls.get_config(lang)
        return config.get("menus", {}).get(menu_name, {}).get("rows", [])

    @classmethod
    def build(cls, menu_name: str, chat_id: int = None, extra_data: Dict = None, lang: str = None) -> InlineKeyboardMarkup:
        rows = cls.get_menu(menu_name, lang)

        if not rows:
            default_menus = {
                "banned_words": [["ban_add", "ban_list"], ["ban_rem"], ["back"]],
                "auto_reply_manage": [
                    ["auto_reply_toggle", "auto_reply_admins"],
                    ["auto_reply_add", "auto_reply_del"],
                    ["auto_reply_list", "auto_reply_stats"],
                    ["auto_reply_reset"], ["back"]
                ],
                "auto_reply": [
                    ["auto_reply_toggle", "auto_reply_admins"],
                    ["auto_reply_add", "auto_reply_del"],
                    ["auto_reply_list", "auto_reply_stats"],
                    ["auto_reply_reset"], ["back"]
                ],
                "security": [
                    ["sec_links", "sec_mentions"], ["sec_slow", "sec_flood"],
                    ["sec_video", "sec_audio"], ["sec_anim", "sec_service"],
                    ["sec_doc", "sec_sticker"], ["sec_forward", "sec_poll"],
                    ["sec_game", "sec_voice"], ["sec_videonote", "sec_banned_words"],
                    ["sec_welcome", "sec_goodbye"], ["sec_night", "sec_approve_join"],
                    ["sec_reject_join", "sec_nsfw"], ["sec_maxlen", "sec_warn"],
                    ["sec_penalty", "sec_del_pen"], ["sec_adv_act", "sec_act_log"],
                    ["sec_auto_reply_menu"], ["sec_antiflood_settings", "sec_night_settings"],
                    ["sec_penalty_durations"], ["sec_violation_penalties"],
                    ["sec_enable_all", "sec_disable_all"], ["sec_close"]
                ],
                "penalty": [["pen_ban", "pen_mute"], ["pen_kick", "pen_warn"], ["back"]],
                "advanced_actions": [
                    ["act_ban", "act_mute"], ["act_warn", "act_kick"],
                    ["act_restrict", "act_unban"], ["act_pin"], ["act_log"], ["back"]
                ],
                "violation_penalties": [["sec_set_violation_strikes", "sec_set_violation_duration"], ["back"]],
                "settings": [["toggle_auto", "toggle_rec"], ["reminder", "translation"], ["referral", "invoices"], ["back"]],
                "plans": [["buy_sub_1", "buy_sub_7"], ["buy_sub_30", "buy_sub_90"], ["buy_sub_365"], ["gift_plans", "redeem_gift"], ["back"]],
                "reminder": [["rem_sub", "rem_daily"], ["rem_weekly"], ["rem_days"], ["back"]],
                "translation": [["lang_ar", "lang_en"], ["trans_off"], ["back"]],
                "channel_settings": [["sched_min", "sched_hour"], ["sched_day", "sched_time"], ["back"]],
                "admin": [
                    ["admin_users", "admin_stats"], ["admin_banned", "admin_unban_all"],
                    ["admin_channels", "admin_groups"], ["admin_grant_free", "admin_add_admin"],
                    ["admin_broadcast", "admin_invoices"], ["admin_backup", "admin_restore"],
                    ["admin_ram", "admin_metrics"], ["back"]
                ]
            }
            if menu_name in default_menus:
                rows = default_menus[menu_name]
            else:
                logger.warning(f"⚠️ قائمة الأزرار '{menu_name}' غير معروفة")
                rows = []

        keyboard = []
        for row in rows:
            btn_row = []
            for item in row:
                if item.endswith("_url"):
                    key = item.replace("_url", "")
                    text = cls.get_text(key, lang)
                    url = f"https://t.me/{CONFIG.BOT_USERNAME}?startgroup"
                    btn_row.append(InlineKeyboardButton(text, url=url))
                else:
                    text = cls.get_text(item, lang)
                    callback = item
                    if chat_id and item not in cls._NO_CHAT_ID_BUTTONS:
                        callback = f"{item}:{chat_id}"
                    btn_row.append(InlineKeyboardButton(text, callback_data=callback))
            keyboard.append(btn_row)

        if not keyboard:
            keyboard = [[InlineKeyboardButton(cls.get_text("back", lang), callback_data="back")]]

        return InlineKeyboardMarkup(keyboard)

    @classmethod
    def _status_icon(cls, value: bool) -> str:
        return "✅" if value else "❌"

    @classmethod
    def _format_security_text(cls, settings: dict) -> str:
        st = cls._status_icon
        lines = [
            "🔐 إعدادات الأمان",
            "━━━━━━━━━━━━━━━━━━━━\n",
            f"🔗 روابط: {st(settings.get('delete_links', 0))} | 👤 معرفات: {st(settings.get('mentions', 0))}",
            f"🌊 فيضان: {st(settings.get('antiflood_enabled', 0))} | 📊 رسائل: {settings.get('antiflood_messages', 5)} | ⏱️ ثواني: {settings.get('antiflood_seconds', 10)}",
            f"📏 طول: {settings.get('max_message_length', 0)} | 🌙 ليلي: {st(settings.get('night_mode_enabled', 0))} | 🔞 NSFW: {st(settings.get('nsfw_enabled', 0))}",
            f"⚠️ تحذيرات: {st(settings.get('warn_enabled', 0))} | 📊 حد: {settings.get('max_warnings', 3)}\n",
            f"🎯 ترحيب: {st(settings.get('welcome_enabled', 0))} | 👋 وداع: {st(settings.get('goodbye_enabled', 0))}",
            f"🗑️ رسائل الخدمة: {st(settings.get('delete_service', 0))}",
            f"🎬 فيديو: {st(settings.get('delete_videos', 0))} | 🎤 صوتي: {st(settings.get('delete_voice', 0))} | 🖼️ ملصقات: {st(settings.get('delete_stickers', 0))}",
            f"📄 ملفات: {st(settings.get('delete_documents', 0))} | 📸 صور: {st(settings.get('delete_photos', 0))} | 🎞️ متحرك: {st(settings.get('delete_animation', 0))}",
            f"✅ موافقة: {st(settings.get('auto_approve_join', 0))} | ❌ رفض: {st(settings.get('auto_reject_join', 0))}\n",
            f"⏱️ كتم: {settings.get('mute_default_duration', 3600)}ث | 🚫 حظر: {settings.get('ban_default_duration', 0)}ث | 🔒 تقييد: {settings.get('restrict_default_duration', 1800)}ث",
            f"⚠️ مخالفات: {settings.get('violation_strikes', 3)} | ⏱️ مدة: {settings.get('violation_duration', 60)}ث",
            f"🌊 مدة الفيضان: {settings.get('antiflood_penalty_duration', 3600)}ث | 🌙 مدة الليل: {settings.get('night_mode_action_duration', 3600)}ث",
            f"⚖️ مدة عقوبة التحذير: {settings.get('warn_penalty_duration', 3600)}ث",
            "━━━━━━━━━━━━━━━━━━━━"
        ]
        return "\n".join(lines)


# =====================================================================
# 10. كاش الكلمات المحظورة
# =====================================================================

_banned_words_cache: Dict[int, List[str]] = {}
_banned_words_cache_time: Dict[int, float] = {}
_banned_words_locks: Dict[int, asyncio.Lock] = {}
_BANNED_WORDS_CACHE_TTL = getattr(CONFIG, 'BANNED_WORDS_CACHE_TTL', 60)
# ✅ v7.5.1: تفعيل الكاش افتراضيًا (كان False سابقًا)
_ENABLE_BANNED_WORDS_CACHE = getattr(CONFIG, 'ENABLE_BANNED_WORDS_CACHE', True)


def _normalize_word(word: Any) -> Optional[str]:
    if not isinstance(word, str):
        return None
    word = word.strip().lower()
    return word if word else None


async def get_banned_words_cached(chat_id: int) -> List[str]:
    if _ENABLE_BANNED_WORDS_CACHE:
        if chat_id not in _banned_words_locks:
            _banned_words_locks[chat_id] = asyncio.Lock()
        lock = _banned_words_locks[chat_id]

        async with lock:
            now = time.time()
            if chat_id in _banned_words_cache and (now - _banned_words_cache_time.get(chat_id, 0)) < _BANNED_WORDS_CACHE_TTL:
                return _banned_words_cache[chat_id]

            try:
                local_words = await DB.get_banned_words(chat_id) or []
                if chat_id != -1:
                    global_words = await DB.get_banned_words(-1) or []
                    combined = local_words + global_words
                else:
                    combined = local_words

                normalized_set = set()
                for w in combined:
                    normalized = _normalize_word(w)
                    if normalized is not None:
                        normalized_set.add(normalized)

                words = list(normalized_set)
                _banned_words_cache[chat_id] = words
                _banned_words_cache_time[chat_id] = time.time()
                return words
            except Exception as e:
                logger.error(f"❌ فشل جلب الكلمات المحظورة من قاعدة البيانات: {e}")
                return []
    else:
        try:
            local_words = await DB.get_banned_words(chat_id) or []
            if chat_id != -1:
                global_words = await DB.get_banned_words(-1) or []
                combined = local_words + global_words
            else:
                combined = local_words

            normalized_set = set()
            for w in combined:
                normalized = _normalize_word(w)
                if normalized is not None:
                    normalized_set.add(normalized)

            return list(normalized_set)
        except Exception as e:
            logger.error(f"❌ فشل جلب الكلمات المحظورة من قاعدة البيانات: {e}")
            return []


def invalidate_banned_words_cache(chat_id: int = None) -> None:
    if chat_id is None or chat_id == -1:
        _banned_words_cache.clear()
        _banned_words_cache_time.clear()
    else:
        _banned_words_cache.pop(chat_id, None)
        _banned_words_cache_time.pop(chat_id, None)


async def get_min_publish_interval() -> int:
    val = await DB.get_setting('min_publish_interval', str(CONFIG.MIN_PUBLISH_INTERVAL))
    try:
        return max(1, int(val))
    except (ValueError, TypeError):
        return CONFIG.MIN_PUBLISH_INTERVAL


# =====================================================================
# 11. دوال الصلاحيات
# =====================================================================

_auth_cache = TTLCache(
    maxsize=getattr(CONFIG, 'AUTH_CACHE_SIZE', 1000),
    ttl=getattr(CONFIG, 'AUTH_CACHE_TTL', 300),
)

async def is_authorized_in_group(bot, chat_id: int, user_id: int) -> bool:
    if user_id == CONFIG.PRIMARY_OWNER_ID:
        return True

    cache_key = f"auth_{chat_id}_{user_id}"
    if cache_key in _auth_cache:
        return _auth_cache[cache_key]

    authorized = False
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in ['administrator', 'creator']:
            authorized = True
    except Exception:
        pass

    if not authorized:
        row = await DB.fetchone("""
            SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?
            UNION ALL
            SELECT 1 FROM hidden_admins WHERE chat_id=? AND admin_id=?
            UNION ALL
            SELECT 1 FROM anonymous_admins WHERE chat_id=? AND (user_id=? OR (user_id IS NULL AND anonymous_id=?))
            LIMIT 1
        """, (chat_id, user_id, chat_id, user_id, chat_id, user_id, user_id))
        authorized = row is not None

    _auth_cache[cache_key] = authorized
    return authorized


def invalidate_auth_cache(chat_id: int = None, user_id: int = None) -> None:
    """
    ✅ v7.5.1: تُستدعى من ChatMemberHandler عند تغيير حالة المشرفين.
    """
    with suppress(Exception):
        if chat_id and user_id:
            _auth_cache.pop(f"auth_{chat_id}_{user_id}", None)
        elif chat_id:
            for k in list(_auth_cache.keys()):
                if k.startswith(f"auth_{chat_id}_"):
                    _auth_cache.pop(k, None)
        else:
            _auth_cache.clear()


async def check_bot_permissions(bot, chat_id: int) -> dict:
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        if me.status not in ['administrator', 'creator']:
            return {'can_act': False, 'reason': 'البوت ليس مشرفاً'}
        can_delete = getattr(me, 'can_delete_messages', False)
        can_restrict = getattr(me, 'can_restrict_members', False)
        can_pin = getattr(me, 'can_pin_messages', False)
        if not can_delete or not can_restrict:
            return {'can_act': False, 'reason': 'صلاحيات ناقصة'}
        return {'can_act': True, 'reason': '', 'can_pin': can_pin}
    except Exception as e:
        return {'can_act': False, 'reason': str(e)[:50]}


# =====================================================================
# 12. إرسال آمن
# =====================================================================

async def _send_media(bot, chat_id, media_type, media_file_id, caption=None, reply_markup=None, **kwargs):
    no_caption_types = {'voice', 'sticker', 'video_note'}

    if media_type == 'photo':
        return await bot.send_photo(chat_id, media_file_id, caption=caption, reply_markup=reply_markup, **kwargs)
    elif media_type == 'video':
        return await bot.send_video(chat_id, media_file_id, caption=caption, reply_markup=reply_markup, **kwargs)
    elif media_type == 'document':
        return await bot.send_document(chat_id, media_file_id, caption=caption, reply_markup=reply_markup, **kwargs)
    elif media_type == 'audio':
        return await bot.send_audio(chat_id, media_file_id, caption=caption, reply_markup=reply_markup, **kwargs)
    elif media_type == 'voice':
        sent = await bot.send_voice(chat_id, media_file_id, reply_markup=reply_markup, **kwargs)
        if caption:
            await bot.send_message(chat_id, caption)
        return sent
    elif media_type == 'animation':
        return await bot.send_animation(chat_id, media_file_id, caption=caption, reply_markup=reply_markup, **kwargs)
    elif media_type == 'sticker':
        sent = await bot.send_sticker(chat_id, media_file_id, reply_markup=reply_markup)
        if caption:
            await bot.send_message(chat_id, caption)
        return sent
    elif media_type == 'video_note':
        sent = await bot.send_video_note(chat_id, media_file_id, reply_markup=reply_markup)
        if caption:
            await bot.send_message(chat_id, caption)
        return sent
    else:
        return await bot.send_message(chat_id, caption or ".", reply_markup=reply_markup, **kwargs)


async def safe_send(bot, chat_id: int, text: str, reply_markup=None, parse_mode: str = None, **kwargs):
    if not text and not any(k in kwargs for k in ['photo', 'video', 'document', 'audio', 'voice', 'animation', 'sticker', 'video_note']):
        return None

    await RATE_LIMITER.acquire()
    # ✅ v7.5.1: sanitize دائماً (حتى عند parse_mode=None)
    text = TextUtils.sanitize(text, max_len=4096) if text else ""

    media_type = None
    media_file_id = None
    for mt in ['photo', 'video', 'document', 'audio', 'voice', 'animation', 'sticker', 'video_note']:
        if mt in kwargs:
            media_type = mt
            media_file_id = kwargs.pop(mt)
            break

    caption_text = text[:1024] if media_type else text

    try:
        if media_type:
            return await _send_media(bot, chat_id, media_type, media_file_id, caption=caption_text or None, reply_markup=reply_markup, **kwargs)
        else:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                **kwargs
            )
    except TimedOut:
        logger.warning("⚠️ Timed out، محاولة إعادة الإرسال...")
        try:
            await asyncio.sleep(1)
            if media_type:
                return await _send_media(bot, chat_id, media_type, media_file_id, caption=caption_text or None, reply_markup=reply_markup, **kwargs)
            else:
                return await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                    **kwargs
                )
        except Exception as e2:
            logger.error(f"❌ فشل الإرسال بعد المحاولة الثانية: {e2}")
            return None
    except BadRequest as e:
        error_msg = str(e).lower()
        if "can't parse entities" in error_msg or "parse" in error_msg:
            try:
                if media_type:
                    return await _send_media(bot, chat_id, media_type, media_file_id, caption=caption_text or None, reply_markup=reply_markup, **kwargs)
                else:
                    return await bot.send_message(
                        chat_id=chat_id,
                        text=text[:4096],
                        reply_markup=reply_markup,
                        parse_mode=None,
                        **kwargs
                    )
            except Exception as e2:
                logger.error(f"❌ فشل الإرسال النهائي: {e2}")
        return None
    except Exception as e:
        logger.warning(f"⚠️ فشل الإرسال: {e}")
        return None


def get_ram_usage() -> dict:
    if psutil is None:
        return {'total': 0, 'used': 0, 'percent': 0}
    try:
        mem = psutil.virtual_memory()
        return {
            'total': round(mem.total / (1024**3), 1),
            'used': round(mem.used / (1024**3), 1),
            'percent': mem.percent
        }
    except Exception as e:
        logger.error(f"❌ فشل جلب إحصائيات الرام: {e}")
        return {'total': 0, 'used': 0, 'percent': 0}


# =====================================================================
# 13. نظام العقوبات
# =====================================================================

class PenaltyStrategy(ABC):
    @abstractmethod
    async def apply(self, bot, chat_id: int, user_id: int, **kwargs) -> Tuple[bool, str]:
        pass


class BanPenalty(PenaltyStrategy):
    async def apply(self, bot, chat_id: int, user_id: int, **kwargs) -> Tuple[bool, str]:
        if user_id == bot.id:
            return False, "لا يمكن حظر البوت"
        duration = kwargs.get('duration', 0)
        until_date = TimeUtils.utc_now() + timedelta(seconds=duration) if duration > 0 else None
        try:
            await bot.ban_chat_member(chat_id, user_id, until_date=until_date)
            return True, "✅ تم الحظر"
        except Exception as e:
            return False, str(e)[:100]


class MutePenalty(PenaltyStrategy):
    async def apply(self, bot, chat_id: int, user_id: int, **kwargs) -> Tuple[bool, str]:
        if user_id == bot.id:
            return False, "لا يمكن كتم البوت"
        duration = kwargs.get('duration', 60)
        until_date = TimeUtils.utc_now() + timedelta(seconds=duration) if duration > 0 else None
        # ✅ v22: استخدام المعاملات الجديدة المفصلة
        permissions = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=False,
        )
        try:
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions,
                until_date=until_date
            )
            return True, "✅ تم الكتم"
        except Exception as e:
            return False, str(e)[:100]


class KickPenalty(PenaltyStrategy):
    async def apply(self, bot, chat_id: int, user_id: int, **kwargs) -> Tuple[bool, str]:
        if user_id == bot.id:
            return False, "لا يمكن طرد البوت"
        try:
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)
            return True, "✅ تم الطرد"
        except Exception as e:
            return False, str(e)[:100]


class WarnPenalty(PenaltyStrategy):
    async def apply(self, bot, chat_id: int, user_id: int, **kwargs) -> Tuple[bool, str]:
        if user_id == bot.id:
            return False, "لا يمكن تحذير البوت"
        try:
            w = await DB.add_user_warning(user_id, chat_id)
            return True, f"⚠️ تحذير {w}"
        except Exception as e:
            return False, str(e)[:100]


class RestrictPenalty(PenaltyStrategy):
    async def apply(self, bot, chat_id: int, user_id: int, **kwargs) -> Tuple[bool, str]:
        if user_id == bot.id:
            return False, "لا يمكن تقييد البوت"
        duration = kwargs.get('duration', 0)
        until_date = TimeUtils.utc_now() + timedelta(seconds=duration) if duration > 0 else None
        # ✅ v22: استخدام المعاملات الجديدة المفصلة
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=True,
            can_pin_messages=False,
        )
        try:
            await bot.restrict_chat_member(
                chat_id, user_id,
                permissions,
                until_date=until_date
            )
            return True, "✅ تم التقييد"
        except Exception as e:
            return False, str(e)[:100]


class UnbanPenalty(PenaltyStrategy):
    async def apply(self, bot, chat_id: int, user_id: int, **kwargs) -> Tuple[bool, str]:
        try:
            await bot.unban_chat_member(chat_id, user_id)
            return True, "✅ تم إلغاء الحظر"
        except Exception as e:
            return False, str(e)[:100]


class PenaltyFactory:
    @staticmethod
    def get_strategy(penalty_type: str):
        strategies = {
            'ban': BanPenalty(),
            'mute': MutePenalty(),
            'kick': KickPenalty(),
            'warn': WarnPenalty(),
            'restrict': RestrictPenalty(),
            'unban': UnbanPenalty()
        }
        return strategies.get(penalty_type)


async def apply_penalty(
    bot,
    chat_id: int,
    user_id: int,
    penalty: str,
    duration: int = 60,
    reason: str = "",
    moderator: int = None,
    username: str = "",
    first_name: str = "",
    chat_name: str = "",
) -> Tuple[bool, str]:
    """
    ✅ v7.5.1: تطبيق عقوبة على مستخدم + تسجيلها في DB.
    - يمرّر `username/first_name/chat_name` لـ`DB.add_penalty`
    - إذا لم تُمرَّر، يُحاول جلبها من تيليجرام تلقائيًا
    """
    if user_id == CONFIG.PRIMARY_OWNER_ID:
        return False, "لا يمكن معاملة المالك"
    if user_id == bot.id:
        return False, "لا يمكن معاملة البوت"
    if await is_authorized_in_group(bot, chat_id, user_id):
        return False, "لا يمكن معاملة مشرف"

    perms = await check_bot_permissions(bot, chat_id)
    if not perms['can_act']:
        return False, "الصلاحيات غير كافية"

    strategy = PenaltyFactory.get_strategy(penalty)
    if not strategy:
        return False, "نوع عقوبة غير معروف"

    success, msg = await strategy.apply(bot, chat_id, user_id, duration=duration)

    if success:
        # ✅ v7.5.1: محاولة جلب username/first_name إن لم تُمرَّر
        if not username or not first_name:
            try:
                member = await bot.get_chat_member(chat_id, user_id)
                tg_user = getattr(member, "user", None)
                if tg_user:
                    if not username:
                        username = tg_user.username or ""
                    if not first_name:
                        first_name = tg_user.first_name or ""
            except Exception as e:
                logger.debug(f"تعذر جلب بيانات المستخدم {user_id}: {e}")

        if not chat_name:
            try:
                chat = await bot.get_chat(chat_id)
                chat_name = getattr(chat, "title", "") or ""
            except Exception as e:
                logger.debug(f"تعذر جلب اسم المجموعة {chat_id}: {e}")

        if penalty in DB.VALID_PENALTY_TYPES:
            try:
                await DB.add_penalty(
                    user_id=user_id,
                    chat_id=chat_id,
                    penalty_type=penalty,
                    duration=duration,
                    reason=reason,
                    issued_by=moderator,
                    username=username,
                    first_name=first_name,
                    chat_name=chat_name,
                )
            except TypeError:
                # توافق مع نسخة add_penalty القديمة التي لا تقبل هذه الوسائط
                await DB.add_penalty(
                    user_id=user_id,
                    chat_id=chat_id,
                    penalty_type=penalty,
                    duration=duration,
                    reason=reason,
                    issued_by=moderator,
                )

        if moderator:
            try:
                await DB.add_admin_log(chat_id, moderator, penalty, user_id, reason)
            except Exception as e:
                logger.debug(f"تعذر تسجيل admin_log: {e}")

    return success, msg


# =====================================================================
# 14. الردود التلقائية
# =====================================================================

_usage_updates: Dict[Tuple[int, str], int] = {}
_USAGE_FLUSH_LIMIT = 50
_USAGE_FLUSH_INTERVAL = 60
_usage_lock = asyncio.Lock()


async def _increment_usage_async(chat_id: int, keyword: str):
    async with _usage_lock:
        key = (chat_id, keyword.lower())
        _usage_updates[key] = _usage_updates.get(key, 0) + 1
        should_flush = len(_usage_updates) >= _USAGE_FLUSH_LIMIT
    if should_flush:
        await _flush_usage_updates()


async def _flush_usage_updates():
    async with _usage_lock:
        if not _usage_updates:
            return
        data = list(_usage_updates.items())
        _usage_updates.clear()
    try:
        for (chat_id, keyword), count in data:
            await DB.execute(
                "UPDATE auto_replies SET usage_count = usage_count + ? WHERE chat_id=? AND keyword=?",
                (count, chat_id, keyword)
            )
    except Exception as e:
        logger.error(f"❌ فشل تحديث usage_count: {e}")
        async with _usage_lock:
            for key, count in data:
                _usage_updates[key] = _usage_updates.get(key, 0) + count


async def export_auto_replies(chat_id: int, file_path: str = None) -> int:
    rows = await DB.fetchall(
        "SELECT keyword, reply FROM auto_replies WHERE chat_id=? AND is_active=1",
        (chat_id,)
    )
    if not rows:
        return 0
    data = [dict(row) for row in rows]
    if file_path is None:
        file_path = f"auto_replies_{chat_id}.json"

    def _write():
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    await asyncio.to_thread(_write)
    return len(data)


async def import_auto_replies(chat_id: int, file_path_or_data: Union[str, List[Dict]], overwrite: bool = False) -> int:
    try:
        if isinstance(file_path_or_data, str):
            with open(file_path_or_data, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = file_path_or_data

        if not isinstance(data, list):
            return 0

        count = 0
        for item in data:
            if not isinstance(item, dict):
                continue
            keyword = item.get('keyword', '').strip().lower()
            reply = item.get('reply', '').strip()
            if not keyword or not reply:
                continue
            if overwrite:
                await DB.execute("DELETE FROM auto_replies WHERE chat_id=? AND keyword=?", (chat_id, keyword))
            reply_type = item.get('reply_type', 'text')
            media_id = item.get('media_file_id')
            buttons = item.get('buttons')
            await DB.add_auto_reply(
                chat_id, keyword, reply,
                reply_type=reply_type,
                media_id=media_id,
                buttons=json.dumps(buttons) if buttons else None
            )
            count += 1
        _auto_reply_cache.invalidate()
        return count
    except Exception as e:
        logger.error(f"❌ Import error: {e}")
        return 0


async def fetch_json_from_url(url: str) -> Optional[Union[list, dict]]:
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.json()
                if isinstance(data, (list, dict)):
                    return data
        return None
    except Exception as e:
        logger.error(f"❌ Fetch JSON error: {e}")
        return None


# =====================================================================
# 15. الردود من ملف
# =====================================================================

def load_replies_from_file() -> dict:
    try:
        import replies
        importlib.reload(replies)
        replies_data = replies.REPLIES
        if replies_data:
            logger.info(f"✅ تم تحميل ملف الردود: {len(replies_data)} رد تلقائي")
        else:
            logger.warning("⚠️ ملف replies.py موجود لكنه فارغ")
        return replies_data
    except ImportError:
        logger.info("ℹ️ لا يوجد replies.py - سيتم تخطي تحميل ملف الردود")
        return {}
    except Exception as e:
        logger.error(f"❌ خطأ في تحميل replies.py: {e}")
        return {}


_REPLIES_FROM_FILE = load_replies_from_file()

if _REPLIES_FROM_FILE:
    logger.info(f"✅ تم تحميل ملف الردود بنجاح: {len(_REPLIES_FROM_FILE)} رد متاح")
else:
    logger.info("ℹ️ لا توجد ردود محملة من ملف replies.py")


def get_reply_from_file(keyword: str) -> Optional[str]:
    if not _REPLIES_FROM_FILE or not keyword:
        return None
    keyword = keyword.lower().strip()

    lines = keyword.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line in _REPLIES_FROM_FILE:
            replies = _REPLIES_FROM_FILE[line]
            return random.choice(replies) if replies else None

        words = line.split()
        for word in words:
            if word in _REPLIES_FROM_FILE:
                replies = _REPLIES_FROM_FILE[word]
                return random.choice(replies) if replies else None

    for key, replies in _REPLIES_FROM_FILE.items():
        if not isinstance(replies, list) or not replies:
            continue
        if re.search(rf'\b{re.escape(key)}\b', keyword):
            return random.choice(replies)

    return None


def reload_replies_from_file() -> dict:
    global _REPLIES_FROM_FILE
    _REPLIES_FROM_FILE = load_replies_from_file()
    if _REPLIES_FROM_FILE:
        logger.info(f"✅ تم إعادة تحميل ملف الردود: {len(_REPLIES_FROM_FILE)} رد")
    return _REPLIES_FROM_FILE


# =====================================================================
# 16. المهام الخلفية
# =====================================================================

class BackgroundTasks:
    # ✅ v7.4.7: كاش لمشرفي المجموعات
    _group_admins_cache: Dict[int, Tuple[float, List[int]]] = {}
    _GROUP_ADMINS_CACHE_TTL = 600
    # ✅ v7.5.1: حد أقصى لحجم الكاش
    _GROUP_ADMINS_CACHE_MAX_SIZE = 5000

    @staticmethod
    async def _get_admin_ids_cached(bot, chat_id: int, force_refresh: bool = False) -> List[int]:
        now = time.time()

        if not force_refresh and chat_id in BackgroundTasks._group_admins_cache:
            cached_time, cached_ids = BackgroundTasks._group_admins_cache[chat_id]
            if now - cached_time < BackgroundTasks._GROUP_ADMINS_CACHE_TTL:
                return cached_ids

        try:
            admins = await bot.get_chat_administrators(chat_id)
            admin_ids = [
                a.user.id for a in admins
                if a.user and not a.user.is_bot
            ]
            # ✅ v7.5.1: تنظيف إن تجاوز الحد
            if len(BackgroundTasks._group_admins_cache) >= BackgroundTasks._GROUP_ADMINS_CACHE_MAX_SIZE:
                # حذف أقدم 20%
                sorted_items = sorted(
                    BackgroundTasks._group_admins_cache.items(),
                    key=lambda x: x[1][0],
                )
                for k, _ in sorted_items[: BackgroundTasks._GROUP_ADMINS_CACHE_MAX_SIZE // 5]:
                    BackgroundTasks._group_admins_cache.pop(k, None)

            BackgroundTasks._group_admins_cache[chat_id] = (now, admin_ids)
            return admin_ids
        except Exception as e:
            logger.debug(f"⚠️ فشل جلب مشرفي {chat_id}: {e}")
            if chat_id in BackgroundTasks._group_admins_cache:
                return BackgroundTasks._group_admins_cache[chat_id][1]
            return []

    @staticmethod
    async def _publish_post(bot, channel_id: int, post: dict) -> bool:
        try:
            text = post.get('text', '')
            media_type = post.get('media_type')
            media_file_id = post.get('media_file_id')
            caption = text[:1024] if text else None

            if media_type == 'photo' and media_file_id:
                await bot.send_photo(channel_id, media_file_id, caption=caption)
            elif media_type == 'video' and media_file_id:
                await bot.send_video(channel_id, media_file_id, caption=caption)
            elif media_type == 'document' and media_file_id:
                await bot.send_document(channel_id, media_file_id, caption=caption)
            elif media_type == 'audio' and media_file_id:
                await bot.send_audio(channel_id, media_file_id, caption=caption)
            elif media_type == 'voice' and media_file_id:
                await bot.send_voice(channel_id, media_file_id)
                if text:
                    try:
                        await bot.send_message(channel_id, text)
                    except Exception as e:
                        logger.warning(f"فشل إرسال النص المصاحب للصوت: {e}")
            elif media_type == 'animation' and media_file_id:
                await bot.send_animation(channel_id, media_file_id, caption=caption)
            elif media_type == 'sticker' and media_file_id:
                await bot.send_sticker(channel_id, media_file_id)
                if text:
                    try:
                        await bot.send_message(channel_id, text)
                    except Exception as e:
                        logger.warning(f"فشل إرسال النص المصاحب للملصق: {e}")
            elif media_type == 'video_note' and media_file_id:
                await bot.send_video_note(channel_id, media_file_id)
                if text:
                    try:
                        await bot.send_message(channel_id, text)
                    except Exception as e:
                        logger.warning(f"فشل إرسال النص المصاحب لفيديو نوت: {e}")
            else:
                if text and len(text) > 4096:
                    for i in range(0, len(text), 4096):
                        await bot.send_message(channel_id, text[i:i+4096])
                else:
                    await bot.send_message(channel_id, text if text else ".")
            return True
        except Exception as e:
            logger.error(f"❌ Publish error: {e}")
            return False

    @staticmethod
    def _unwrap_get_next_post(result) -> Tuple[Optional[Dict], bool]:
        """✅ v7.5.1: فك نتيجة get_next_post بأمان."""
        if result is None:
            return None, False
        if isinstance(result, tuple) and len(result) == 2:
            post_dict, was_recycled = result
            if post_dict is None or isinstance(post_dict, dict):
                return post_dict, bool(was_recycled)
            return None, False
        if isinstance(result, dict):
            return result, False
        return None, False

    @staticmethod
    async def _publish_single_channel(bot, ch, sleep_seconds, published_count):
        user_id = None
        try:
            user_id = ch.get('user_id') if isinstance(ch, dict) else None
            has_sub = await DB.has_active_subscription(user_id) if user_id else False
            if not has_sub:
                logger.info(f"⏭️ تخطي القناة {ch.get('id')} لانتهاء الاشتراك")
                return

            raw_result = await DB.get_next_post(ch['id'])
            post, recycled = BackgroundTasks._unwrap_get_next_post(raw_result)

            if not post:
                return

            success = await BackgroundTasks._publish_post(bot, ch['channel_id'], post)
            if success:
                await DB.mark_post_published(post['id'])
                await DB.update_last_publish(ch['id'])
                await DB.update_next_publish(ch['id'])
                logger.info(f"✅ قناة {ch['id']} نشرت. انتظار {sleep_seconds//60} دقيقة...")

                if published_count == 0 or recycled:
                    if user_id:
                        try:
                            await safe_send(bot, user_id, "✅ تم نشر منشور في قناتك")
                        except Exception as e:
                            logger.warning(f"تعذر إرسال إشعار النشر للمستخدم {user_id}: {e}")

                await asyncio.sleep(sleep_seconds)
            else:
                await DB.increment_post_fail(post['id'])

        except Exception as e:
            logger.error(f"❌ خطأ في قناة {ch.get('id', 'غير معروفة')}: {e}")

    @staticmethod
    async def auto_publish(bot) -> None:
        await asyncio.sleep(10)
        max_channels = getattr(CONFIG, 'MAX_CHANNELS_PER_CYCLE', 20)
        min_interval_minutes = await get_min_publish_interval()
        sleep_seconds = min_interval_minutes * 60
        publish_semaphore = asyncio.Semaphore(max_channels)
        active_tasks = {}

        while True:
            try:
                channels = await asyncio.wait_for(
                    DB.get_channels_to_publish(max_channels),
                    timeout=10
                )

                if not channels:
                    await asyncio.sleep(60)
                    continue

                for ch in channels:
                    channel_id = ch['id']
                    if channel_id in active_tasks and not active_tasks[channel_id].done():
                        continue

                    published_count = ch.get('published_count', 0)

                    async def run_publish(ch=ch, bot=bot, sleep_seconds=sleep_seconds, published_count=published_count):
                        async with publish_semaphore:
                            await BackgroundTasks._publish_single_channel(bot, ch, sleep_seconds, published_count)

                    task = asyncio.create_task(run_publish())
                    active_tasks[channel_id] = task
                    await asyncio.sleep(0.5)

                for cid in list(active_tasks.keys()):
                    if active_tasks[cid].done():
                        with suppress(Exception):
                            active_tasks[cid].result()
                        del active_tasks[cid]

                await asyncio.sleep(60)

            except asyncio.TimeoutError:
                logger.error("❌ استعلام القنوات استغرق أكثر من 10 ثوانٍ")
                await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"❌ خطأ في auto_publish: {e}")
                await asyncio.sleep(60)

    @staticmethod
    async def auto_backup() -> None:
        await asyncio.sleep(60)
        try:
            await BackgroundTasks._do_backup()
        except Exception as e:
            logger.error(f"❌ Initial backup failed: {e}")

        while True:
            await asyncio.sleep(86400)
            try:
                await BackgroundTasks._do_backup()
            except Exception as e:
                logger.error(f"❌ Backup error: {e}")

    @staticmethod
    async def _do_backup() -> None:
        """
        ✅ v7.5.1: النسخ الاحتياطي يعمل على 3 محركات.
        - يُحاول استخدام DB.backup_database (متوافق مع PostgreSQL/MySQL/SQLite).
        - fallback: SQLite المباشر.
        """
        if not await DB.get_auto_backup():
            return

        PATHS.BACKUPS.mkdir(parents=True, exist_ok=True)
        backup_file = PATHS.BACKUPS / f"backup_{TimeUtils.mecca_now().strftime('%Y%m%d_%H%M%S')}.db"

        success = False
        # محاولة 1: استخدام DB.backup_database
        if hasattr(DB, "backup_database"):
            try:
                success = await DB.backup_database(backup_file)
            except Exception as e:
                logger.warning(f"⚠️ DB.backup_database فشل: {e}")
                success = False

        # محاولة 2: SQLite المباشر
        if not success and getattr(DB, "DB_TYPE", "sqlite") == "sqlite":
            try:
                def _backup():
                    import sqlite3 as sqlite3_sync
                    source = sqlite3_sync.connect(str(PATHS.DB))
                    dest = sqlite3_sync.connect(str(backup_file))
                    with dest:
                        source.backup(dest)
                    dest.close()
                    source.close()
                await asyncio.to_thread(_backup)
                success = True
            except Exception as e:
                logger.error(f"❌ SQLite backup failed: {e}")
                success = False

        if success:
            await DB.set_setting('last_backup', TimeUtils.sql_iso())
            backups = sorted(PATHS.BACKUPS.glob("backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
            for old in backups[CONFIG.MAX_BACKUPS:]:
                with suppress(Exception):
                    old.unlink()
            logger.info(f"✅ نسخة احتياطية: {backup_file.name}")
        else:
            logger.error("❌ فشل النسخ الاحتياطي على كل المحركات")

    @staticmethod
    async def reminders(bot) -> None:
        """
        ✅ v7.5.1: يستخدم RemindersMixin.send_subscription_reminders.
        """
        while True:
            await asyncio.sleep(3600)
            try:
                # استخدام RemindersMixin إن وُجد
                if hasattr(DB, "send_subscription_reminders"):
                    async def send_impl(user_id: int, days_left: int, lang: str) -> bool:
                        try:
                            text = await get_text(
                                lang, 'reminder_subscription_expires', days=days_left
                            )
                            if text == 'reminder_subscription_expires':
                                text = f"⚠️ اشتراكك سينتهي بعد {days_left} يوم"
                            result = await safe_send(bot, user_id, text)
                            return result is not None
                        except Exception as e:
                            logger.debug(f"فشل إرسال تذكير لـ {user_id}: {e}")
                            return False

                    stats = await DB.send_subscription_reminders(send_impl)
                    if isinstance(stats, dict) and stats.get('sent', 0) > 0:
                        logger.info(f"📨 تم إرسال {stats['sent']} تذكير اشتراك")

                # fallback: DB.get_users_for_reminder (القديم)
                elif hasattr(DB, "get_users_for_reminder"):
                    users = await DB.get_users_for_reminder()
                    for u in users:
                        try:
                            try:
                                days = int(u['days_left'])
                            except (ValueError, TypeError, KeyError):
                                continue
                            lang = u.get('language', 'ar')
                            text = await get_text(lang, 'reminder_subscription_expires', days=days)
                            if text == 'reminder_subscription_expires':
                                text = f"⚠️ اشتراكك سينتهي بعد {days} يوم"
                            await safe_send(bot, u['user_id'], text)
                            await asyncio.sleep(0.1)
                        except Exception:
                            pass
                else:
                    logger.debug("ℹ️ لا توجد دوال تذكيرات متاحة")

            except Exception as e:
                logger.error(f"❌ Reminders: {e}")

    @staticmethod
    async def heartbeat(bot) -> None:
        while True:
            await asyncio.sleep(CONFIG.HEARTBEAT_INTERVAL)
            try:
                ram = get_ram_usage()
                msg = f"💓 **Heartbeat**\n\n🕐 {TimeUtils.mecca_iso()}\n💾 RAM: {ram['percent']}%"
                log_channel = await DB.get_log_channel()
                try:
                    if log_channel:
                        await safe_send(bot, log_channel, msg, parse_mode='Markdown')
                    else:
                        await safe_send(bot, CONFIG.PRIMARY_OWNER_ID, msg, parse_mode='Markdown')
                except Exception as e:
                    logger.error(f"❌ فشل إرسال heartbeat: {e}")
            except Exception as e:
                logger.error(f"❌ Heartbeat error: {e}")

    @staticmethod
    async def flush_usage_periodically() -> None:
        while True:
            await asyncio.sleep(_USAGE_FLUSH_INTERVAL)
            await _flush_usage_updates()

    @staticmethod
    async def expire_subscriptions() -> None:
        while True:
            await asyncio.sleep(3600)
            try:
                await DB.expire_expired_subscriptions()
            except Exception as e:
                logger.error(f"❌ Expire subs: {e}")

    @staticmethod
    async def sync_admins_periodically(bot) -> None:
        await asyncio.sleep(180)

        while True:
            try:
                # ✅ v7.5.1: فحص وجود DB.sync_group_admins
                if not hasattr(DB, "sync_group_admins"):
                    logger.debug("ℹ️ DB.sync_group_admins غير متاحة — تخطي المزامنة")
                    await asyncio.sleep(7200)
                    continue

                groups = await asyncio.wait_for(
                    DB.fetchall("SELECT chat_id FROM bot_groups WHERE banned=0"),
                    timeout=15
                )

                if not groups:
                    await asyncio.sleep(7200)
                    continue

                semaphore = asyncio.Semaphore(3)
                updated_count = 0

                async def sync_one(group_row):
                    nonlocal updated_count
                    async with semaphore:
                        try:
                            chat_id = (
                                group_row['chat_id']
                                if isinstance(group_row, dict)
                                else group_row[0]
                            )

                            admin_ids = await BackgroundTasks._get_admin_ids_cached(bot, chat_id)
                            if admin_ids:
                                await DB.sync_group_admins(chat_id, admin_ids)
                                updated_count += 1

                            await asyncio.sleep(1.0)

                        except Exception as e:
                            logger.debug(f"Sync admins {group_row}: {e}")

                await asyncio.gather(
                    *[sync_one(g) for g in groups],
                    return_exceptions=True
                )

                logger.info(
                    f"✅ تم تحديث مشرفي {updated_count}/{len(groups)} مجموعة"
                )

            except asyncio.TimeoutError:
                logger.error("❌ استعلام المجموعات استغرق أكثر من 15 ثانية")
            except Exception as e:
                logger.error(f"❌ Sync admins: {e}")

            await asyncio.sleep(7200)

    @staticmethod
    async def expire_penalties_periodically() -> None:
        await asyncio.sleep(60)
        while True:
            await asyncio.sleep(60)
            try:
                await DB.expire_penalties()
            except Exception as e:
                logger.error(f"❌ Expire penalties: {e}")

    @staticmethod
    async def cleanup_old_data() -> None:
        """
        ✅ v7.5.1: استخدام TimeUtils بدل SQLite-specific syntax.
        يعمل على 3 محركات.
        """
        while True:
            await asyncio.sleep(3600)
            try:
                _security_settings_cache.clear()
                _security_settings_time.clear()
                _auto_reply_settings_cache.clear()
                _auto_reply_settings_time.clear()
                _banned_words_cache.clear()
                _banned_words_cache_time.clear()
                _auto_reply_cache.clear()
                _auth_cache.clear()
                BackgroundTasks._group_admins_cache.clear()
                now = time.time()
                expired_users = [
                    uid for uid, ts in StateManager._timestamps.items()
                    if now - ts > StateManager._timeout
                ]
                for uid in expired_users:
                    StateManager.clear(uid)
                logger.info("✅ تم تنظيف الكاش المؤقت والحالات المنتهية")
            except Exception as e:
                logger.error(f"❌ فشل تنظيف الكاش: {e}")

            # ✅ v7.5.1: استخدام TimeUtils (يعمل على 3 محركات)
            try:
                cutoff_30 = TimeUtils.utc_now() - timedelta(days=30)
                cutoff_60 = TimeUtils.utc_now() - timedelta(days=60)
                cutoff_90 = TimeUtils.utc_now() - timedelta(days=90)

                await DB.execute(
                    "DELETE FROM admin_logs WHERE created_at < ?",
                    (cutoff_30,)
                )
                await DB.execute(
                    "DELETE FROM user_penalties WHERE created_at < ?",
                    (cutoff_60,)
                )
                await DB.execute(
                    "DELETE FROM payment_logs WHERE created_at < ?",
                    (cutoff_90,)
                )
                logger.info("✅ تم تنظيف البيانات القديمة")
            except Exception as e:
                logger.error(f"❌ فشل تنظيف قاعدة البيانات: {e}")


# =====================================================================
# 17. خادم الويب
# =====================================================================

_webhook_app = None

async def setup_webhook(app, port: int):
    global _webhook_app
    _webhook_app = app

    web_app = web.Application()
    web_app.router.add_get('/health', lambda r: web.Response(text="OK"))
    web_app.router.add_get('/', lambda r: web.Response(text="🌿 Relax Manager"))
    web_app.router.add_post(f"/{CONFIG.TOKEN}", webhook_handler)
    web_app.router.add_get('/{tail:.*}', lambda r: web.Response(text="OK", status=200))
    web_app.router.add_post('/{tail:.*}', lambda r: web.Response(text="OK", status=200))

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"✅ Webhook on port {port}")
    return runner


async def webhook_handler(request):
    global _webhook_app
    if _webhook_app is None or not hasattr(_webhook_app, 'bot'):
        logger.error("❌ Webhook app not initialized")
        return web.Response(status=503, text="Service Unavailable")
    try:
        if request.content_type != 'application/json':
            logger.warning("⚠️ Webhook request with non-JSON content")
            return web.Response(status=400, text="Bad Request")
        data = await request.json()
        await _webhook_app.process_update(Update.de_json(data, _webhook_app.bot))
        return web.Response(status=200, text="OK")
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return web.Response(status=500, text="ERROR")


# =====================================================================
# 18. معالج الأخطاء
# =====================================================================

class ErrorHandler:
    @staticmethod
    async def handle_error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        ✅ v7.5.1: يسجّل الخطأ + يُرسل إشعارًا لقناة السجلات (إن وُجدت).
        """
        try:
            error_msg = str(context.error)
            if update:
                logger.error(f"❌ خطأ في التحديث {update.update_id}: {context.error}", exc_info=True)
            else:
                logger.error(f"❌ خطأ: {context.error}", exc_info=True)

            # ✅ v7.5.1: إرسال إشعار لقناة السجلات
            try:
                log_channel = await DB.get_log_channel()
                if log_channel:
                    short_msg = (
                        f"❌ **خطأ في البوت**\n\n"
                        f"📝 {error_msg[:300]}\n"
                        f"🕐 {TimeUtils.mecca_iso()}"
                    )
                    if update and update.effective_user:
                        short_msg += f"\n👤 {update.effective_user.id}"
                    await safe_send(context.bot, log_channel, short_msg, parse_mode='Markdown')
            except Exception:
                pass

        except Exception:
            pass