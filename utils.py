#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
utils.py - الأدوات المساعدة للبوت (v7.8.3 - Resilient Banned-Words Cache)
=================================================================================
🧠 v7.8.3 (حماية مزدوجة للكلمات المحظورة):
    ✅ get_banned_words_cached: عند فشل DB، أرجِع الكاش القديم بدل []
       (يمنع تعطّل فلتر الكلمات المحظورة عند أي خطأ عابر)
    ✅ _get_global_words_cached: نفس الحماية للكلمات العامة
    ✅ invalidate_banned_words_cache: يُبطل كاش Database أيضاً
       (_banned_words_cache + _banned_words_cache_time)
    ✅ warmup_all: يشمل warmed up للكاش المحلي في Database
    ✅ التعامل مع AttributeError من DB بأمان (getattr fallback)

🧠 v7.8.2 (دمج سجل قناة المجموعات):
    ✅ KeyboardFactory._default_texts: إضافة 9 مفاتيح log_channel_*
    ✅ التوافق مع group_log.py + handlers_callback.py v9.2.0

🧠 v7.8.1 (حماية من thundering herd + batch subscriptions):
    ✅ SmartCache.get_or_set(): dedup للمفاتيح المتزامنة
    ✅ BackgroundTasks._publish_single_channel: يقبل has_sub مسبقاً
    ✅ BackgroundTasks.auto_publish: batch subscription check
    ✅ Semaphore limit 8 (بدل 20) — ضغط أقل على Pool
    ✅ تأخير بين المهام 0.3s (بدل 0.5s) — لكن أسرع عملياً

🧠 v7.8.0 (تحسينات ذكية شاملة):
    ✅ PenaltyFactory: Singleton strategies
    ✅ KeyboardFactory: Preload كل اللغات + Warmup
    ✅ TranslationManager: Preload + Async warmup
    ✅ StateManager: TTLCache (تنظيف تلقائي)
    ✅ RateLimiter: Adaptive (429-aware)
    ✅ _group_admins_cache: TTL متكيّف
    ✅ _get_security_stats: dedup cache (5s)
    ✅ _auth_cache: negative cache + ttl ذكي
    ✅ safe_send: Exponential backoff للـ429
    ✅ _banned_words_cache: Global batching
    ✅ warmup_all(): Preload at startup
    ✅ _query_cache: كاش موحّد للاستعلامات المتكررة

📌 v7.7.3: _do_auth_check: Telegram API أولاً
📌 v7.7.2: تصحيحات أمنية + تنظيف
📌 v7.7.1: _get_security_stats متوازي
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
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Tuple, Any, Union, Callable, Awaitable
from enum import Enum, auto
from collections import OrderedDict, deque, defaultdict
from abc import ABC, abstractmethod
from contextlib import suppress

try:
    import psutil
except ImportError:
    psutil = None

import aiohttp
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ChatPermissions, Update
from telegram.error import BadRequest, TimedOut, RetryAfter
from telegram.ext import ContextTypes
from cachetools import TTLCache

import aiohttp.web as web

from config import CONFIG, PATHS
from database import DB

logger = logging.getLogger(__name__)

# =====================================================================
# 0. 🧠 SmartCache — كاش موحّد مع dedup
# =====================================================================

class SmartCache:
    """
    🧠 v7.8.1: كاش موحّد async-safe مع حماية من thundering herd.

    - get_or_set: يضمن استدعاء واحد فقط لكل مفتاح حتى مع 50 كوروتين متزامنة
    - LRU eviction عند الوصول للحد
    - TTL قابل للتخصيص لكل مفتاح
    """
    __slots__ = ('_cache', '_ttl_default', '_max_size', '_lock', '_stampede_locks')

    def __init__(self, ttl: int = 60, max_size: int = 5000):
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._ttl_default = ttl
        self._max_size = max_size
        self._lock = asyncio.Lock()
        self._stampede_locks: Dict[str, asyncio.Lock] = {}

    async def get(self, key: str, default=None):
        async with self._lock:
            item = self._cache.get(key)
            if item is None:
                return default
            value, exp = item
            if time.time() > exp:
                del self._cache[key]
                return default
            return value

    async def get_or_set(
        self,
        key: str,
        loader: Callable[[], Awaitable[Any]],
        ttl: int = None,
    ) -> Any:
        """
        🧠 v7.8.1: حماية من thundering herd.

        لو N كوروتين طلبت نفس المفتاح في نفس اللحظة → استدعاء DB واحد فقط.
        """
        # محاولة أولى سريعة
        value = await self.get(key)
        if value is not None:
            return value

        # حماية: قفل per-key
        async with self._lock:
            lock = self._stampede_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._stampede_locks[key] = lock

        async with lock:
            # إعادة فحص — ربما امتلأ المفتاح أثناء انتظار القفل
            value = await self.get(key)
            if value is not None:
                return value

            loaded = await loader()
            if loaded is not None:
                await self.set(key, loaded, ttl)

            async with self._lock:
                self._stampede_locks.pop(key, None)
            return loaded

    async def set(self, key: str, value, ttl: int = None):
        effective_ttl = ttl if ttl is not None else self._ttl_default
        async with self._lock:
            if len(self._cache) >= self._max_size and key not in self._cache:
                # LRU eviction — الأقدم أولاً
                for k in list(self._cache.keys())[: self._max_size // 4]:
                    self._cache.pop(k, None)
            self._cache[key] = (value, time.time() + effective_ttl)

    async def delete(self, key: str):
        async with self._lock:
            self._cache.pop(key, None)

    async def delete_prefix(self, prefix: str) -> int:
        async with self._lock:
            keys = [k for k in self._cache if k.startswith(prefix)]
            for k in keys:
                del self._cache[k]
            return len(keys)

    async def clear(self):
        async with self._lock:
            self._cache.clear()

    async def size(self) -> int:
        async with self._lock:
            return len(self._cache)


# الكاشات العامة
_auth_cache_smart = SmartCache(ttl=60, max_size=2000)   # positives
_auth_neg_cache = SmartCache(ttl=15, max_size=1000)     # negatives
_security_stats_cache = SmartCache(ttl=5, max_size=500) # dedup 5s

# =====================================================================
# 1. أدوات الوقت
# =====================================================================

class TimeUtils:
    """أدوات الوقت والتاريخ."""
    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def mecca_now() -> datetime:
        return TimeUtils.utc_now() + timedelta(hours=3)

    @staticmethod
    def utc_iso() -> str:
        return TimeUtils.utc_now().isoformat() + "+00:00"

    @staticmethod
    def mecca_iso() -> str:
        return TimeUtils.mecca_now().isoformat()

    @staticmethod
    def sql_iso() -> str:
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
# 3. Rate Limiter — Adaptive
# =====================================================================

class RateLimiter:
    """
    🧠 v7.8.0: محدد معدل ذكي — يبطئ تلقائياً عند ضغط Telegram (429).
    """
    def __init__(self, max_concurrent: int = 10, max_per_second: int = 30):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._last_calls = deque(maxlen=max_per_second * 2)
        self._lock = asyncio.Lock()
        self.max_per_second = max_per_second
        self._base_max = max_per_second
        self._throttle_factor = 1.0
        self._last_429 = 0.0
        self._429_count = 0

    def report_429(self):
        """يُستدعى عند استقبال 429 من Telegram."""
        self._429_count += 1
        self._last_429 = time.time()
        self._throttle_factor = min(self._throttle_factor * 1.5, 5.0)
        logger.warning(
            f"🚨 RateLimiter: 429 detected — throttle_factor={self._throttle_factor:.2f}"
        )

    def _get_effective_rate(self) -> int:
        if time.time() - self._last_429 > 60:
            self._throttle_factor = 1.0
        return max(1, int(self._base_max / self._throttle_factor))

    async def acquire(self, *args, **kwargs):
        while True:
            wait_time = 0.0
            effective_rate = self._get_effective_rate()
            async with self.semaphore:
                async with self._lock:
                    now = time.time()
                    while self._last_calls and now - self._last_calls[0] > 1:
                        self._last_calls.popleft()
                    if len(self._last_calls) < effective_rate:
                        self._last_calls.append(now)
                        return
                    wait_time = 1 - (now - self._last_calls[0])
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            else:
                await asyncio.sleep(0.01)


RATE_LIMITER = RateLimiter(max_concurrent=15, max_per_second=30)
PUBLISH_RATE_LIMITER = RateLimiter(max_concurrent=5, max_per_second=10)

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
    """🧠 v7.8.0: كاش للردود التلقائية — يستخدم cachetools.TTLCache."""
    def __init__(self, maxsize: int = 300, ttl: int = 300):
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)

    def get(self, key: str):
        return self._cache.get(key)

    def set(self, key: str, value: dict):
        self._cache[key] = value

    def invalidate(self, key: str = None):
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    def clear(self):
        self._cache.clear()


_auto_reply_cache = AutoReplyCache(maxsize=300, ttl=300)

# =====================================================================
# 6. الترجمات — Preload + Warmup
# =====================================================================

class TranslationManager:
    """
    🧠 v7.8.0: إدارة الترجمات مع preload + warmup.
    """
    _translations: Dict[str, Dict] = {}
    _locales_dir: str = str(Path(__file__).resolve().parent / "locales")
    _default_lang: str = "ar"
    _load_lock = threading.Lock()

    @classmethod
    def _load_translation_cached(cls, lang: str) -> Dict:
        if lang == 'off':
            lang = cls._default_lang
        if lang in cls._translations:
            return cls._translations[lang]

        with cls._load_lock:
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
    def preload_all(cls) -> int:
        """🧠 v7.8.0: preload كل اللغات المتاحة."""
        langs = list(cls.get_available_languages().keys())
        count = 0
        for lang in langs:
            try:
                cls._load_translation_cached(lang)
                count += 1
            except Exception as e:
                logger.debug(f"preload {lang}: {e}")
        return count

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
            "ar": "العربية 🇸🇦", "en": "English 🇬🇧", "fr": "Français 🇫🇷",
            "tr": "Türkçe 🇹🇷", "zh": "中文 🇨🇳", "ru": "Русский 🇷🇺",
            "de": "Deutsch 🇩🇪", "es": "Español 🇪🇸", "it": "Italiano 🇮🇹",
            "pt": "Português 🇵🇹", "ja": "日本語 🇯🇵", "ko": "한국어 🇰🇷",
            "fa": "فارسی 🇮🇷", "ur": "اردو 🇵🇰", "nl": "Nederlands 🇳🇱",
            "pl": "Polski 🇵🇱", "hi": "हिन्दी 🇮🇳"
        }


async def get_text(lang: str, key: str, **kwargs) -> str:
    return TranslationManager.get_text(lang, key, **kwargs)

# =====================================================================
# 7. إدارة الحالات — TTLCache
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
    WAIT_BAN_USER_ID = auto()
    WAIT_UNBAN_USER_ID = auto()


class StateManager:
    """🧠 v7.8.0: إدارة الحالات بـ TTLCache (تنظيف تلقائي)."""
    _cache: TTLCache = TTLCache(maxsize=10000, ttl=300)
    _lock = threading.Lock()

    @classmethod
    def get(cls, user_id: int) -> UserState:
        with cls._lock:
            return cls._cache.get(user_id, UserState.NONE)

    @classmethod
    def set(cls, user_id: int, state: UserState) -> None:
        with cls._lock:
            cls._cache[user_id] = state

    @classmethod
    def clear(cls, user_id: int) -> None:
        with cls._lock:
            cls._cache.pop(user_id, None)

    @classmethod
    def is_expired(cls, user_id: int, timeout: int = None) -> bool:
        """يرجع True إن لم يكن موجوداً."""
        with cls._lock:
            return user_id not in cls._cache

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
    ADMIN_BAN_USER = "admin_ban_user"
    ADMIN_UNBAN_USER = "admin_unban_user"

    AUTO_REPLY_MENU = "auto_reply_menu"
    AUTO_REPLY_TOGGLE = "auto_reply_toggle"
    AUTO_REPLY_ADMINS = "auto_reply_admins"
    AUTO_REPLY_RESET = "auto_reply_reset"
    AUTO_REPLY_STATS = "auto_reply_stats"
    AUTO_REPLY_ADD = "auto_reply_add"
    AUTO_REPLY_DEL = "auto_reply_del"
    AUTO_REPLY_LIST = "auto_reply_list"

# =====================================================================
# 9. مصنع الكيبوردات — Preload
# =====================================================================

class KeyboardFactory:
    """🧠 v7.8.2: مصنع لوحات المفاتيح مع preload + log_channel_* keys."""
    _configs: Dict[str, Dict] = {}
    _default_lang: str = "ar"
    _config_path_template: str = str(Path(__file__).resolve().parent / "buttons_config_{lang}.json")
    _load_lock = threading.Lock()

    _NO_CHAT_ID_BUTTONS = {
        "sec_close", "panel_close", "back", "main", "cancel",
        "help", "settings", "language", "check_sub",
        "toggle_auto", "toggle_rec", "plans", "subscribe",
        "support", "support_ticket", "developer", "trial",
        "contests", "contest_winners", "referral", "ref_claim",
        "ref_list", "reminder", "rem_sub", "rem_daily",
        "rem_weekly", "rem_days", "translation", "trans_off",
        "invoices", "groups", "admin",
        "pub_all", "post_add", "post_pub", "post_list", "post_rec",
        "post_clear", "finish_posts",
        "admin_uptime", "admin_ban_user", "admin_unban_user",
        "admin_users", "admin_banned", "admin_unban_all",
        "admin_channels", "admin_banned_ch", "admin_activate_ch",
        "admin_groups", "admin_banned_gr", "admin_unban_gr",
        "admin_add_admin", "admin_rem_admin", "admin_list_admins",
        "admin_ram", "admin_stats", "admin_metrics",
        "admin_backup", "admin_restore", "admin_restore_sel",
        "admin_show_backups", "admin_upload_backup",
        "admin_send_update", "admin_set_update_ch", "admin_show_update",
        "admin_force_sub", "admin_set_force", "admin_disable_force",
        "admin_broadcast", "admin_tickets", "admin_del_tickets",
        "admin_log_ch", "admin_set_log_ch",
        "admin_replies", "admin_add_reply", "admin_list_replies", "admin_del_reply",
        "admin_banned_words", "admin_add_banned", "admin_list_banned", "admin_rem_banned",
        "admin_create_contest", "admin_declare_winner",
        "admin_export_replies", "admin_import_replies", "admin_import_github",
        "admin_refresh_cache", "admin_invoices", "admin_payment_logs",
        "admin_grant_free", "admin_del_contest",
    }

    _default_texts = {
        "back": "🔙 رجوع",
        "main": "🌿 الرئيسية",
        "cancel": "❌ إلغاء",
        "add_group_button": "➕ أضف البوت لمجموعة",
        "security_button": "⚙️ أمان {name}",
        "ch_add": "➕ إضافة قناة",
        "ch_list": "📡 قنواتي",
        "ch_stats": "📊 إحصائيات",
        "ch_del": "🗑️ حذف",
        "ch_sel": "📌 اختيار",
        "sched_btn": "📅 الجدولة",
        "groups": "👥 مجموعاتي",

        # 🆕 v7.8.2: سجل قناة المجموعات
        "log_channel_btn": "📢 قناة السجل",
        "log_channel_set": "🔗 تعيين قناة السجل",
        "log_channel_remove": "🗑️ إزالة قناة السجل",
        "log_channel_current": "الحالية",
        "log_channel_none": "❌ لا توجد قناة سجل",
        "log_channel_help": "أضف البوت كمشرف في القناة ثم أرسل معرّفها أو أعد توجيه رسالة منها",
        "log_channel_saved": "✅ تم تعيين قناة السجل",
        "log_channel_removed": "🗑️ تمت إزالة قناة السجل",
        "log_channel_test": "🧪 رسالة اختبار — قناة السجل تعمل بنجاح!",

        "post_add": "📥 إضافة منشورات",
        "post_pub": "📤 نشر منشور",
        "post_list": "📋 منشوراتي",
        "post_rec": "♻️ إعادة التدوير",
        "post_del": "🗑️ حذف منشور",
        "post_clear": "🧹 مسح الكل",
        "pub_all": "📤 نشر الكل",
        "finish_posts": "✅ إنهاء",
        "settings": "⚙️ الإعدادات",
        "toggle_auto": "📤 النشر التلقائي",
        "toggle_rec": "♻️ إعادة التدوير",
        "plans": "💎 الباقات",
        "subscribe": "💎 اشتراك",
        "gift_plans": "🎁 شراء كود هدية",
        "redeem_gift": "🎟️ استخدام كود هدية",
        "support": "📞 دعم فني",
        "support_ticket": "📝 تذكرة دعم",
        "developer": "👨‍💻 المطور",
        "help": "📚 مساعدة",
        "language": "🌐 اللغة",
        "trial": "🎁 تجربة مجانية",
        "admin_panel_btn": "👑 لوحة الأدمن",

        "sec_links": "🔗 روابط",
        "sec_mentions": "👤 منشن",
        "sec_slow": "🐌 بطيء",
        "sec_slow_mode_seconds": "⏱️ مدة بطيء",
        "sec_flood": "🌊 فيضان",
        "sec_video": "🎬 فيديو",
        "sec_audio": "🎤 صوت",
        "sec_anim": "🎞️ متحرك",
        "sec_service": "🗑️ خدمة",
        "sec_doc": "📄 ملف",
        "sec_sticker": "🖼️ ملصق",
        "sec_forward": "📨 معاد",
        "sec_poll": "📊 تصويت",
        "sec_game": "🎮 لعبة",
        "sec_voice": "🎤 صوتي",
        "sec_videonote": "🎥 فيديو نوت",
        "sec_banned_words": "🚫 كلمات محظورة",
        "sec_toggle_banned_words": "✅ تفعيل الحذف / ❌ تعطيل الحذف",
        "sec_welcome": "🎯 ترحيب",
        "sec_welcome_text": "📝 نص ترحيب",
        "sec_goodbye": "👋 وداع",
        "sec_goodbye_text": "📝 نص وداع",
        "sec_night": "🌙 ليلي",
        "sec_approve_join": "✅ موافقة الانضمام",
        "sec_reject_join": "❌ رفض الانضمام",
        "sec_nsfw": "🔞 NSFW",
        "sec_maxlen": "📏 الحد الأقصى للطول",
        "sec_warn": "⚠️ تحذيرات",
        "sec_warn_count": "🔢 عدد التحذيرات",
        "sec_warn_penalty": "⚖️ عقوبة التحذير",
        "sec_warn_penalty_duration": "⏱️ مدة عقوبة التحذير",
        "sec_penalty": "⚖️ العقوبات",
        "sec_del_pen": "⚖️ عقوبة الحذف",
        "sec_adv_act": "🛠️ إجراءات متقدمة",
        "sec_act_log": "📜 السجل",
        "sec_auto_reply_menu": "📝 الردود",
        "sec_antiflood_settings": "🌊 إعدادات الفيضان",
        "sec_night_settings": "🌙 إعدادات الليل",
        "sec_penalty_durations": "⏳ مدد العقوبات",
        "sec_violation_settings": "⚖️ عقوبات المخالفات",
        "sec_violation_penalties": "🚨 عقوبات المخالفات",
        "sec_activate_all": "✅ تفعيل الكل",
        "sec_deactivate_all": "❌ تعطيل الكل",
        "sec_enable_all": "✅ تفعيل الكل",
        "sec_disable_all": "❌ تعطيل الكل",
        "sec_close": "❌ إغلاق",
        "sec_set_antiflood_messages": "🔢 عدد الرسائل",
        "sec_set_antiflood_seconds": "⏱️ الثواني",
        "sec_set_night_start": "🌙 وقت البدء",
        "sec_set_night_end": "🌙 وقت النهاية",
        "sec_set_violation_strikes": "📊 عدد المخالفات",
        "sec_set_violation_duration": "⏱️ مدة عقوبة المخالفة",
        "sec_antiflood_duration": "⏱️ مدة عقوبة الفيضان",
        "sec_night_duration": "⏱️ مدة إجراء الليل",
        "sec_set_antiflood_penalty": "🚫 نوع عقوبة الفيضان",
        "sec_set_night_action": "🌙 إجراء الليل",
        "sec_penalty_none": "🚫 بدون عقوبة",
        "sec_penalty_ban": "🚫 حظر",
        "sec_penalty_mute": "🔇 كتم",
        "sec_penalty_kick": "👢 طرد",
        "sec_penalty_restrict": "🔒 تقييد",

        "act_ban": "🚫 حظر",
        "act_mute": "🔇 كتم",
        "act_warn": "⚠️ تحذير",
        "act_kick": "👢 طرد",
        "act_restrict": "🔒 تقييد",
        "act_unban": "🔓 فك حظر",
        "act_pin": "📌 تثبيت",
        "act_log": "📋 سجل",

        "ban_add": "➕ إضافة كلمة",
        "ban_list": "📋 قائمة الكلمات",
        "ban_rem": "🗑️ حذف كلمة",

        "pen_ban": "🚫 حظر",
        "pen_mute": "🔇 كتم",
        "pen_kick": "👢 طرد",
        "pen_warn": "⚠️ تحذير",

        "auto_reply": "📝 الردود التلقائية",
        "auto_reply_toggle": "🔄 تشغيل/إيقاف",
        "auto_reply_admins": "👤 للمشرفين فقط",
        "auto_reply_add": "➕ إضافة رد",
        "auto_reply_del": "🗑️ حذف رد",
        "auto_reply_list": "📋 قائمة الردود",
        "auto_reply_stats": "📊 إحصائيات",
        "auto_reply_reset": "🗑️ حذف الكل",
        "auto_reply_menu": "📝 الردود التلقائية",

        "panel_lock": "🔒 قفل المجموعة",
        "panel_unlock": "🔓 فتح المجموعة",
        "panel_close": "❌ إغلاق اللوحة",

        "sched_min": "⏱️ بالدقائق",
        "sched_hour": "🕐 بالساعات",
        "sched_day": "📅 بالأيام",
        "sched_time": "🕒 وقت محدد",

        "referral": "🔗 الإحالات",
        "ref_claim": "🎁 صرف المكافأة",
        "ref_list": "📋 قائمة المُحالين",
        "reminder": "⏰ التذكيرات",
        "rem_sub": "🔔 تذكير الاشتراك",
        "rem_daily": "📊 التقرير اليومي",
        "rem_weekly": "📈 التقرير الأسبوعي",
        "rem_days": "📅 عدد الأيام",
        "translation": "🌐 الترجمة",
        "trans_off": "❌ إيقاف الترجمة",
        "invoices": "🧾 فواتيري",
        "contests": "🏆 المسابقات",
        "contest_winners": "🏆 الفائزون",
        "contest_join": "✍️ المشاركة",
        "buy_sub_1": "🗓️ يوم واحد",
        "buy_sub_7": "🗓️ أسبوع",
        "buy_sub_30": "🗓️ شهر",
        "buy_sub_90": "🗓️ 3 أشهر",
        "buy_sub_365": "🗓️ سنة",
    }

    @classmethod
    def _load_config_for_lang(cls, lang: str) -> Dict:
        if lang == 'off':
            lang = cls._default_lang
        if lang in cls._configs:
            return cls._configs[lang]

        with cls._load_lock:
            if lang in cls._configs:
                return cls._configs[lang]

            file_path = cls._config_path_template.format(lang=lang)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    cls._configs[lang] = config
                    logger.info(
                        f"✅ تم تحميل buttons_config_{lang}.json: "
                        f"{len(config.get('texts', {}))} مفتاح"
                    )
                    return config
            except FileNotFoundError:
                if lang != cls._default_lang:
                    logger.warning(
                        f"⚠️ buttons_config_{lang}.json غير موجود، الافتراضية"
                    )
                    return cls._load_config_for_lang(cls._default_lang)
                logger.warning(
                    "⚠️ buttons_config_ar.json غير موجود، استخدام افتراضية"
                )
                default_config = {"texts": cls._default_texts, "menus": {}}
                cls._configs[cls._default_lang] = default_config
                return default_config
            except Exception as e:
                logger.error(f"❌ خطأ في قراءة buttons_config_{lang}.json: {e}")
                if lang != cls._default_lang:
                    return cls._load_config_for_lang(cls._default_lang)
                default_config = {"texts": cls._default_texts, "menus": {}}
                cls._configs[cls._default_lang] = default_config
                return default_config

    @classmethod
    def load_config(cls):
        cls._load_config_for_lang(cls._default_lang)

    @classmethod
    def preload_all(cls) -> int:
        """🧠 v7.8.0: preload كل اللغات."""
        langs = list(TranslationManager.get_available_languages().keys())
        count = 0
        for lang in langs:
            try:
                cls._load_config_for_lang(lang)
                count += 1
            except Exception:
                pass
        return count

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
    def build(cls, menu_name: str, chat_id: int = None, extra_data: Dict = None,
              lang: str = None) -> InlineKeyboardMarkup:
        rows = cls.get_menu(menu_name, lang)

        if not rows:
            default_menus = cls._get_default_menus()
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
            keyboard = [[
                InlineKeyboardButton(cls.get_text("back", lang), callback_data="back")
            ]]

        return InlineKeyboardMarkup(keyboard)

    @classmethod
    def _get_default_menus(cls) -> Dict[str, List[List[str]]]:
        return {
            "main_menu": [
                ["ch_list", "groups"], ["post_add", "post_pub"],
                ["post_list", "post_rec"], ["pub_all"],
                ["plans", "subscribe"], ["gift_plans", "redeem_gift"],
                ["support", "developer"], ["help", "language"],
                ["trial", "contests"], ["settings"],
            ],
            "settings": [
                ["toggle_auto", "toggle_rec"],
                ["translation", "reminder"],
                ["referral", "invoices"],
                ["back"],
            ],
            "plans": [
                ["buy_sub_1", "buy_sub_7"], ["buy_sub_30", "buy_sub_90"],
                ["buy_sub_365"], ["gift_plans", "redeem_gift"], ["back"],
            ],
            "support": [["support_ticket"], ["back"]],
            "reminder": [
                ["rem_sub", "rem_daily"], ["rem_weekly", "rem_days"], ["back"],
            ],
            "translation": [["trans_off"], ["back"]],
            "referral": [["ref_claim", "ref_list"], ["back"]],
            "contests": [["contest_winners"], ["back"]],
            "security": [
                ["sec_links", "sec_mentions", "sec_forward"],
                ["sec_video", "sec_audio", "sec_anim"],
                ["sec_doc", "sec_sticker", "sec_service"],
                ["sec_poll", "sec_game", "sec_videonote"],
                ["sec_flood", "sec_slow", "sec_night"],
                ["sec_slow_mode_seconds"],
                ["sec_welcome", "sec_goodbye"],
                ["sec_welcome_text", "sec_goodbye_text"],
                ["sec_approve_join", "sec_reject_join"],
                ["sec_banned_words", "sec_nsfw"],
                ["sec_maxlen", "sec_warn"],
                ["sec_warn_count"],
                ["sec_warn_penalty", "sec_warn_penalty_duration"],
                ["sec_violation_penalties"],
                ["sec_penalty", "sec_del_pen"],
                ["sec_penalty_durations"],
                ["sec_adv_act", "sec_act_log"],
                ["sec_auto_reply_menu"],
                ["sec_antiflood_settings", "sec_night_settings"],
                ["sec_enable_all", "sec_disable_all"],
                ["sec_close"],
            ],
            "banned_words": [
                ["ban_add", "ban_list"], ["ban_rem"],
                ["sec_toggle_banned_words"], ["back"],
            ],
            "penalty": [
                ["pen_ban", "pen_mute"], ["pen_kick", "pen_warn"], ["back"],
            ],
            "advanced_actions": [
                ["act_ban", "act_mute"], ["act_warn", "act_kick"],
                ["act_restrict", "act_unban"], ["act_pin"], ["act_log"],
                ["back"],
            ],
            "auto_reply": [
                ["auto_reply_toggle", "auto_reply_admins"],
                ["auto_reply_add", "auto_reply_del"],
                ["auto_reply_list", "auto_reply_stats"],
                ["auto_reply_reset"], ["back"],
            ],
            "auto_reply_manage": [
                ["auto_reply_toggle", "auto_reply_admins"],
                ["auto_reply_add", "auto_reply_del"],
                ["auto_reply_list", "auto_reply_stats"],
                ["auto_reply_reset"], ["back"],
            ],
            "panel": [["panel_lock", "panel_unlock"], ["panel_close"]],
            "channel_settings": [
                ["sched_min", "sched_hour"],
                ["sched_day", "sched_time"],
                ["back"],
            ],
            "antiflood_settings": [
                ["sec_set_antiflood_messages", "sec_set_antiflood_seconds"],
                ["sec_set_antiflood_penalty"],
                ["sec_antiflood_duration"],
                ["back"],
            ],
            "night_settings": [
                ["sec_set_night_start", "sec_set_night_end"],
                ["sec_set_night_action"],
                ["sec_night_duration"],
                ["back"],
            ],
            "violation_penalties": [
                ["sec_set_violation_strikes", "sec_set_violation_duration"],
                ["back"],
            ],
            "admin_panel": [
                ["admin_users", "admin_banned"], ["admin_unban_all"],
                ["admin_ban_user", "admin_unban_user"],
                ["admin_channels", "admin_banned_ch"],
                ["admin_activate_ch"],
                ["admin_groups", "admin_banned_gr"],
                ["admin_unban_gr"],
                ["admin_add_admin", "admin_rem_admin"],
                ["admin_list_admins"],
                ["admin_ram", "admin_stats"],
                ["admin_uptime"],
                ["admin_metrics"],
                ["admin_backup", "admin_restore"],
                ["admin_upload_backup", "admin_show_backups"],
                ["admin_send_update", "admin_set_update_ch"],
                ["admin_show_update"],
                ["admin_force_sub", "admin_set_force"],
                ["admin_disable_force"],
                ["admin_broadcast"],
                ["admin_tickets", "admin_del_tickets"],
                ["admin_log_ch", "admin_set_log_ch"],
                ["admin_replies"],
                ["admin_add_reply", "admin_list_replies"],
                ["admin_del_reply"],
                ["admin_banned_words", "admin_add_banned"],
                ["admin_list_banned", "admin_rem_banned"],
                ["admin_create_contest", "admin_declare_winner"],
                ["admin_export_replies", "admin_import_replies"],
                ["admin_import_github"],
                ["admin_refresh_cache"],
                ["admin_invoices", "admin_payment_logs"],
                ["admin_grant_free"],
                ["back"],
            ],
            "admin": [
                ["admin_users", "admin_banned"], ["admin_unban_all"],
                ["admin_channels", "admin_groups"],
                ["admin_ban_user", "admin_unban_user"],
                ["admin_grant_free", "admin_add_admin"],
                ["admin_broadcast", "admin_invoices"],
                ["admin_backup", "admin_restore"],
                ["admin_ram", "admin_metrics"], ["back"],
            ],
        }

    @classmethod
    def _status_icon(cls, value: bool) -> str:
        return "✅" if value else "❌"

    @classmethod
    def _dot(cls, enabled: bool) -> str:
        return "🟢" if enabled else "⚫"

    @classmethod
    def _fmt_dur(cls, seconds: int) -> str:
        try:
            seconds = int(seconds)
        except (ValueError, TypeError):
            return "—"
        if seconds <= 0:
            return "∞"
        if seconds < 60:
            return f"{seconds}ث"
        if seconds < 3600:
            return f"{seconds // 60}د"
        if seconds < 86400:
            h = seconds // 3600
            m = (seconds % 3600) // 60
            return f"{h}س" if m == 0 else f"{h}س{m}د"
        if seconds < 2592000:
            return f"{seconds // 86400}ي"
        return f"{seconds // 2592000}ش"

    @classmethod
    async def _get_security_stats(cls, chat_id: int) -> dict:
        """🧠 v7.8.0: dedup cache (5s)."""
        cache_key = f"sec_stats_{chat_id}"
        cached = await _security_stats_cache.get(cache_key)
        if cached is not None:
            return cached

        stats = {
            'penalties_today': 0, 'mutes_today': 0, 'bans_today': 0,
            'kicks_today': 0, 'warns_today': 0,
            'photos_deleted': 0, 'videos_deleted': 0, 'stickers_deleted': 0,
            'files_deleted': 0, 'links_deleted': 0, 'forwards_deleted': 0,
            'active_warnings': 0, 'total_violations': 0,
            'banned_words': 0, 'auto_replies': 0,
        }

        try:
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0, tzinfo=None
            )

            async def safe_fetch(sql, params, default=None):
                try:
                    return await asyncio.wait_for(
                        DB.fetchone(sql, params), timeout=2.0
                    )
                except Exception:
                    return default

            (penalties_row, deleted_row, warns_row,
             words_row, replies_row, viols_row) = await asyncio.gather(
                safe_fetch(
                    "SELECT "
                    "  SUM(CASE WHEN penalty_type='mute' THEN 1 ELSE 0 END) as mutes, "
                    "  SUM(CASE WHEN penalty_type='ban' THEN 1 ELSE 0 END) as bans, "
                    "  SUM(CASE WHEN penalty_type='kick' THEN 1 ELSE 0 END) as kicks, "
                    "  SUM(CASE WHEN penalty_type='warn' THEN 1 ELSE 0 END) as warns, "
                    "  COUNT(*) as total "
                    "FROM user_penalties WHERE chat_id = ? AND created_at >= ?",
                    (chat_id, today_start)
                ),
                safe_fetch(
                    "SELECT "
                    "  SUM(CASE WHEN action LIKE '%photo%' THEN 1 ELSE 0 END) as photos, "
                    "  SUM(CASE WHEN action LIKE '%video%' THEN 1 ELSE 0 END) as videos, "
                    "  SUM(CASE WHEN action LIKE '%sticker%' THEN 1 ELSE 0 END) as stickers, "
                    "  SUM(CASE WHEN action LIKE '%document%' THEN 1 ELSE 0 END) as files, "
                    "  SUM(CASE WHEN action LIKE '%link%' THEN 1 ELSE 0 END) as links, "
                    "  SUM(CASE WHEN action LIKE '%forward%' THEN 1 ELSE 0 END) as forwards "
                    "FROM admin_logs WHERE chat_id = ? AND created_at >= ? "
                    "  AND action LIKE 'violation_%'",
                    (chat_id, today_start)
                ),
                safe_fetch("SELECT COUNT(*) as cnt FROM user_warnings WHERE chat_id = ?", (chat_id,)),
                safe_fetch("SELECT COUNT(*) as cnt FROM banned_words WHERE chat_id = ?", (chat_id,)),
                safe_fetch(
                    "SELECT COUNT(*) as cnt FROM auto_replies "
                    "WHERE chat_id = ? AND is_active = 1", (chat_id,)
                ),
                safe_fetch(
                    "SELECT SUM(violation_count) as total FROM user_violations "
                    "WHERE chat_id = ?", (chat_id,)
                ),
                return_exceptions=True,
            )

            if isinstance(penalties_row, dict):
                stats['mutes_today'] = penalties_row.get('mutes', 0) or 0
                stats['bans_today'] = penalties_row.get('bans', 0) or 0
                stats['kicks_today'] = penalties_row.get('kicks', 0) or 0
                stats['warns_today'] = penalties_row.get('warns', 0) or 0
                stats['penalties_today'] = penalties_row.get('total', 0) or 0
            if isinstance(deleted_row, dict):
                stats['photos_deleted'] = deleted_row.get('photos', 0) or 0
                stats['videos_deleted'] = deleted_row.get('videos', 0) or 0
                stats['stickers_deleted'] = deleted_row.get('stickers', 0) or 0
                stats['files_deleted'] = deleted_row.get('files', 0) or 0
                stats['links_deleted'] = deleted_row.get('links', 0) or 0
                stats['forwards_deleted'] = deleted_row.get('forwards', 0) or 0
            if isinstance(warns_row, dict):
                stats['active_warnings'] = warns_row.get('cnt', 0) or 0
            if isinstance(words_row, dict):
                stats['banned_words'] = words_row.get('cnt', 0) or 0
            if isinstance(replies_row, dict):
                stats['auto_replies'] = replies_row.get('cnt', 0) or 0
            if isinstance(viols_row, dict):
                stats['total_violations'] = viols_row.get('total', 0) or 0

        except Exception as e:
            logger.debug(f"_get_security_stats: {e}")

        await _security_stats_cache.set(cache_key, stats, ttl=5)
        return stats

    @classmethod
    def _format_security_text(cls, settings: dict, stats: dict = None) -> str:
        d = cls._dot
        f = cls._fmt_dur

        links = d(settings.get('delete_links', 0))
        mentions = d(settings.get('mentions', 0))
        video = d(settings.get('delete_videos', 0))
        audio = d(settings.get('delete_voice', 0))
        stickers = d(settings.get('delete_stickers', 0))
        files = d(settings.get('delete_documents', 0))
        anim = d(settings.get('delete_animation', 0))
        fwd = d(settings.get('delete_forwarded', 0))
        polls = d(settings.get('delete_polls', 0))
        service = d(settings.get('delete_service', 0))

        flood_on = d(settings.get('antiflood_enabled', 0))
        flood_n = settings.get('antiflood_messages', 5)
        flood_s = settings.get('antiflood_seconds', 10)

        night_on = d(settings.get('night_mode_enabled', 0))
        night_a = settings.get('night_mode_start', '—') or '—'
        night_b = settings.get('night_mode_end', '—') or '—'

        maxlen = settings.get('max_message_length', 0) or '∞'
        nsfw = d(settings.get('nsfw_enabled', 0))

        welcome = d(settings.get('welcome_enabled', 0))
        goodbye = d(settings.get('goodbye_enabled', 0))
        approve = d(settings.get('auto_approve_join', 0))
        reject = d(settings.get('auto_reject_join', 0))

        warn = d(settings.get('warn_enabled', 0))
        warn_max = settings.get('max_warnings', 3)
        viol_s = settings.get('violation_strikes', 3)
        viol_d = f(settings.get('violation_duration', 60))

        mute_d = f(settings.get('mute_default_duration', 3600))
        ban_d = f(settings.get('ban_default_duration', 0))
        restrict_d = f(settings.get('restrict_default_duration', 1800))
        warn_pd = f(settings.get('warn_penalty_duration', 3600))
        flood_pd = f(settings.get('antiflood_penalty_duration', 3600))
        night_pd = f(settings.get('night_mode_action_duration', 3600))

        stats_section = ""
        if stats:
            pen = stats.get('penalties_today', 0)
            warns_c = stats.get('active_warnings', 0)
            viols = stats.get('total_violations', 0)
            words = stats.get('banned_words', 0)
            replies = stats.get('auto_replies', 0)

            photos = stats.get('photos_deleted', 0)
            videos = stats.get('videos_deleted', 0)
            sticks = stats.get('stickers_deleted', 0)
            files_del = stats.get('files_deleted', 0)
            links_del = stats.get('links_deleted', 0)

            stats_section = (
                f"\n"
                f"📊 <b>الإحصائيات</b>\n"
                f"  🚫 عقوبات {pen}      ⚠️ تحذيرات {warns_c}\n"
                f"  🚨 مخالفات {viols}      🔒 كلمات {words}\n"
                f"  💬 ردود {replies}\n"
                f"\n"
                f"📸 <b>حذف اليوم</b>\n"
                f"  🖼️ صور {photos}      🎬 فيديو {videos}\n"
                f"  🖼️ ملصق {sticks}      📄 ملف {files_del}\n"
                f"  🔗 روابط {links_del}\n"
            )

        return (
            f"🔐 <b>الأمان</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"🗑️ <b>الحذف التلقائي</b>\n"
            f"  🔗 روابط {links}      👤 منشن {mentions}\n"
            f"  🎬 فيديو {video}      🎤 صوت {audio}\n"
            f"  🖼️ ملصق {stickers}      📄 ملف {files}\n"
            f"  🎞️ متحرك {anim}      📨 معاد {fwd}\n"
            f"  📊 تصويت {polls}      🗑️ خدمة {service}\n"
            f"\n"
            f"⚙️ <b>الأمان المتقدم</b>\n"
            f"  🌊 فيضان {flood_on}      ({flood_n}ر / {flood_s}ث)\n"
            f"  🌙 ليلي {night_on}      ({night_a} ← {night_b})\n"
            f"  📏 طول {maxlen}      🔞 NSFW {nsfw}\n"
            f"\n"
            f"👋 <b>الترحيب</b>\n"
            f"  🎯 ترحيب {welcome}      👋 وداع {goodbye}\n"
            f"  ✅ موافق {approve}      ❌ رفض {reject}\n"
            f"\n"
            f"⚠️ <b>التحذيرات</b>\n"
            f"  ⚠️ مفعل {warn}      حد {warn_max}\n"
            f"  🚨 مخالفات {viol_s}      مدة {viol_d}\n"
            f"\n"
            f"⏱️ <b>مدد العقوبات</b>\n"
            f"  🔇 كتم {mute_d}      🚫 حظر {ban_d}\n"
            f"  🔒 تقييد {restrict_d}      ⚠️ تحذير {warn_pd}\n"
            f"  🌊 فيضان {flood_pd}      🌙 ليلي {night_pd}\n"
            f"{stats_section}"
            f"\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>🟢 مفعّل  •  ⚫ معطّل</i>"
        )

# =====================================================================
# 10. كاش الكلمات المحظورة — Global batching + Resilient Fallback
# =====================================================================

_banned_words_cache: Dict[int, List[str]] = {}
_banned_words_cache_time: Dict[int, float] = {}
_banned_words_locks: Dict[int, asyncio.Lock] = {}
_BANNED_WORDS_CACHE_TTL = getattr(CONFIG, 'BANNED_WORDS_CACHE_TTL', 60)
_ENABLE_BANNED_WORDS_CACHE = getattr(CONFIG, 'ENABLE_BANNED_WORDS_CACHE', True)

_global_words_cache: List[str] = []
_global_words_loaded_at: float = 0.0
_GLOBAL_WORDS_TTL = 120


def _normalize_word(word: Any) -> Optional[str]:
    if not isinstance(word, str):
        return None
    word = word.strip().lower()
    return word if word else None


async def _get_global_words_cached() -> List[str]:
    """
    🧠 v7.8.3: جلب الكلمات العامة مرة واحدة لكل TTL.
    ✅ عند فشل DB، أرجِع الكاش القديم (لا تُفرغه).
    """
    global _global_words_cache, _global_words_loaded_at
    now = time.time()
    if _global_words_cache and now - _global_words_loaded_at < _GLOBAL_WORDS_TTL:
        return _global_words_cache
    try:
        raw = await DB.get_banned_words(-1) or []
        normalized = set()
        for w in raw:
            n = _normalize_word(w)
            if n is not None:
                normalized.add(n)
        _global_words_cache = list(normalized)
        _global_words_loaded_at = now
        return _global_words_cache
    except Exception as e:
        logger.error(f"❌ فشل جلب الكلمات العامة: {e}")
        # ✅ v7.8.3: أرجِع الكاش القديم بدل []
        return _global_words_cache or []


async def get_banned_words_cached(chat_id: int) -> List[str]:
    """
    🧠 v7.8.3: كاش الكلمات المحظورة مع حماية مزدوجة.

    - عند فشل DB: أرجِع الكاش القديم بدل [] (يمنع تعطّل الفلتر)
    - dedup بـ lock per-chat لمنع thundering herd
    """
    if _ENABLE_BANNED_WORDS_CACHE:
        if chat_id not in _banned_words_locks:
            _banned_words_locks[chat_id] = asyncio.Lock()
        lock = _banned_words_locks[chat_id]
        async with lock:
            now = time.time()
            if chat_id in _banned_words_cache and \
               (now - _banned_words_cache_time.get(chat_id, 0)) < _BANNED_WORDS_CACHE_TTL:
                return _banned_words_cache[chat_id]
            try:
                local_words = await DB.get_banned_words(chat_id) or []
                if chat_id != -1:
                    global_words = await _get_global_words_cached()
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
                logger.error(f"❌ فشل جلب الكلمات المحظورة: {e}")
                # ✅ v7.8.3: أرجِع الكاش القديم بدل [] — يمنع تعطّل الفلتر
                return _banned_words_cache.get(chat_id, [])
    else:
        try:
            local_words = await DB.get_banned_words(chat_id) or []
            if chat_id != -1:
                global_words = await _get_global_words_cached()
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
            logger.error(f"❌ فشل جلب الكلمات المحظورة: {e}")
            # ✅ v7.8.3: fallback للكاش
            return _banned_words_cache.get(chat_id, [])


def invalidate_banned_words_cache(chat_id: int = None) -> None:
    """
    🧠 v7.8.3: إبطال كاش الكلمات المحظورة في utils و Database معاً.

    هذا يمنع عدم التزامن بين الطبقتين.
    """
    global _global_words_cache, _global_words_loaded_at

    # 1) كاش utils
    if chat_id is None or chat_id == -1:
        _banned_words_cache.clear()
        _banned_words_cache_time.clear()
        _global_words_cache = []
        _global_words_loaded_at = 0.0
    else:
        _banned_words_cache.pop(chat_id, None)
        _banned_words_cache_time.pop(chat_id, None)

    # 2) ✅ v7.8.3: كاش Database الداخلي (إن وُجد)
    try:
        if hasattr(DB, '_banned_words_cache') and DB._banned_words_cache is not None:
            if chat_id is None or chat_id == -1:
                DB._banned_words_cache.clear()
                if hasattr(DB, '_banned_words_cache_time'):
                    DB._banned_words_cache_time.clear()
                if hasattr(DB, '_global_banned_words_cache'):
                    DB._global_banned_words_cache = []
                if hasattr(DB, '_global_banned_words_loaded'):
                    DB._global_banned_words_loaded = False
            else:
                DB._banned_words_cache.pop(chat_id, None)
                if hasattr(DB, '_banned_words_cache_time'):
                    DB._banned_words_cache_time.pop(chat_id, None)
    except Exception as e:
        logger.debug(f"invalidate DB banned_words cache: {e}")


async def get_min_publish_interval() -> int:
    val = await DB.get_setting('min_publish_interval', str(CONFIG.MIN_PUBLISH_INTERVAL))
    try:
        return max(1, int(val))
    except (ValueError, TypeError):
        return CONFIG.MIN_PUBLISH_INTERVAL

# =====================================================================
# 11. دوال الصلاحيات — Smart cache
# =====================================================================

_auth_cache = TTLCache(
    maxsize=getattr(CONFIG, 'AUTH_CACHE_SIZE', 2000),
    ttl=30,
)

_auth_cache_legacy = _auth_cache


async def _do_auth_check(bot, chat_id: int, user_id: int) -> bool:
    """v7.7.3: Telegram API أولاً (أسرع 10x) ثم DB."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status in ('administrator', 'creator'):
            return True
    except Exception as e:
        logger.debug(f"Telegram API auth check failed: {e}")

    try:
        row = await DB.fetchone("""
            SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?
            UNION ALL
            SELECT 1 FROM hidden_admins WHERE chat_id=? AND admin_id=?
            UNION ALL
            SELECT 1 FROM anonymous_admins WHERE chat_id=? AND (user_id=? OR (user_id IS NULL AND anonymous_id=?))
            LIMIT 1
        """, (chat_id, user_id, chat_id, user_id, chat_id, user_id, user_id))
        if row is not None:
            return True
    except Exception as e:
        logger.debug(f"DB auth check failed: {e}")

    return False


async def is_authorized_in_group(bot, chat_id: int, user_id: int) -> bool:
    """🧠 v7.8.0: كاش مزدوج — positives (60s) و negatives (15s)."""
    try:
        primary_id = int(CONFIG.PRIMARY_OWNER_ID)
    except (TypeError, ValueError, AttributeError):
        primary_id = None
    if primary_id is not None and user_id == primary_id:
        return True

    cache_key = f"auth_{chat_id}_{user_id}"

    cached = _auth_cache.get(cache_key)
    if cached is not None:
        return cached

    pos = await _auth_cache_smart.get(cache_key)
    if pos is not None:
        return pos
    neg = await _auth_neg_cache.get(cache_key)
    if neg is not None:
        return neg

    authorized = await _do_auth_check(bot, chat_id, user_id)

    if authorized:
        _auth_cache[cache_key] = True
        await _auth_cache_smart.set(cache_key, True, ttl=60)
        await _auth_neg_cache.delete(cache_key)
    else:
        _auth_cache[cache_key] = False
        await _auth_neg_cache.set(cache_key, False, ttl=15)
        await _auth_cache_smart.delete(cache_key)

    return authorized


def invalidate_auth_cache(chat_id: int = None, user_id: int = None) -> None:
    """إبطال كاش الصلاحيات (sync)."""
    with suppress(Exception):
        if chat_id and user_id:
            _auth_cache.pop(f"auth_{chat_id}_{user_id}", None)
        elif chat_id:
            prefix = f"auth_{chat_id}_"
            for k in list(_auth_cache.keys()):
                if k.startswith(prefix):
                    _auth_cache.pop(k, None)
        else:
            _auth_cache.clear()


async def invalidate_auth_cache_async(
    chat_id: int = None, user_id: int = None
) -> None:
    """🧠 v7.8.0: نسخة async تُنظّف كل الكاشات."""
    invalidate_auth_cache(chat_id=chat_id, user_id=user_id)
    with suppress(Exception):
        if chat_id and user_id:
            await _auth_cache_smart.delete(f"auth_{chat_id}_{user_id}")
            await _auth_neg_cache.delete(f"auth_{chat_id}_{user_id}")
        elif chat_id:
            await _auth_cache_smart.delete_prefix(f"auth_{chat_id}_")
            await _auth_neg_cache.delete_prefix(f"auth_{chat_id}_")
        else:
            await _auth_cache_smart.clear()
            await _auth_neg_cache.clear()


async def check_bot_permissions(bot, chat_id: int) -> dict:
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        if me.status not in ('administrator', 'creator'):
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
# 12. إرسال آمن — Exponential backoff
# =====================================================================

async def _send_media(bot, chat_id, media_type, media_file_id,
                      caption=None, reply_markup=None, **kwargs):
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


async def safe_send(bot, chat_id: int, text: str, reply_markup=None,
                    parse_mode: str = None, **kwargs):
    """🧠 v7.8.0: إرسال آمن مع Exponential backoff للـ429."""
    if not text and not any(
        k in kwargs for k in ['photo', 'video', 'document', 'audio',
                              'voice', 'animation', 'sticker', 'video_note']
    ):
        return None

    try:
        await asyncio.wait_for(RATE_LIMITER.acquire(), timeout=2.0)
    except asyncio.TimeoutError:
        logger.debug("⚠️ RATE_LIMITER timeout")

    text = TextUtils.sanitize(text, max_len=4096) if text else ""
    media_type = None
    media_file_id = None
    for mt in ['photo', 'video', 'document', 'audio', 'voice',
               'animation', 'sticker', 'video_note']:
        if mt in kwargs:
            media_type = mt
            media_file_id = kwargs.pop(mt)
            break

    caption_text = text[:1024] if media_type else text

    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            if media_type:
                return await _send_media(
                    bot, chat_id, media_type, media_file_id,
                    caption=caption_text or None,
                    reply_markup=reply_markup, **kwargs
                )
            else:
                return await bot.send_message(
                    chat_id=chat_id, text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode, **kwargs
                )
        except RetryAfter as e:
            wait = int(getattr(e, 'retry_after', 1)) + 1
            RATE_LIMITER.report_429()
            logger.warning(f"⏳ RetryAfter {wait}s (attempt {attempt+1})")
            await asyncio.sleep(wait)
            continue
        except TimedOut:
            logger.warning(f"⚠️ TimedOut (attempt {attempt+1})")
            if attempt < max_attempts - 1:
                await asyncio.sleep(1)
                continue
            return None
        except BadRequest as e:
            error_msg = str(e).lower()
            if "can't parse entities" in error_msg or "parse" in error_msg:
                try:
                    if media_type:
                        return await _send_media(
                            bot, chat_id, media_type, media_file_id,
                            caption=caption_text or None,
                            reply_markup=reply_markup, **kwargs
                        )
                    else:
                        return await bot.send_message(
                            chat_id=chat_id, text=text[:4096],
                            reply_markup=reply_markup,
                            parse_mode=None, **kwargs
                        )
                except Exception as e2:
                    logger.error(f"❌ فشل الإرسال النهائي: {e2}")
            return None
        except Exception as e:
            logger.warning(f"⚠️ فشل الإرسال (attempt {attempt+1}): {e}")
            if attempt < max_attempts - 1:
                await asyncio.sleep(1 * (attempt + 1))
                continue
            return None

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
# 13. دوال حظر/فك حظر المستخدمين
# =====================================================================

async def ban_user_by_id(user_id: int) -> Tuple[bool, str]:
    """حظر مستخدم من استخدام البوت (بواسطة ID)."""
    try:
        try:
            if CONFIG.is_developer(user_id):
                return False, "لا يمكنك حظر مطور آخر!"
        except Exception:
            pass
        row = await DB.fetchone("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if row:
            await DB.execute("UPDATE users SET banned=1 WHERE user_id=?", (user_id,))
        else:
            try:
                await DB.execute(
                    "INSERT INTO users (user_id, banned, language, created_at) VALUES (?, 1, 'ar', ?)",
                    (user_id, TimeUtils.utc_now())
                )
            except Exception:
                await DB.execute(
                    "INSERT INTO users (user_id, banned, language) VALUES (?, 1, 'ar')",
                    (user_id,)
                )
        with suppress(Exception):
            from cache import invalidate_user_cache as _iuc
            await _iuc(user_id)
        invalidate_auth_cache(user_id=user_id)
        with suppress(Exception):
            await invalidate_auth_cache_async(user_id=user_id)
        return True, f"✅ تم حظر المستخدم: {user_id}"
    except Exception as e:
        logger.error(f"❌ ban_user_by_id({user_id}): {e}", exc_info=True)
        return False, f"❌ فشل الحظر: {str(e)[:100]}"


async def unban_user_by_id(user_id: int) -> Tuple[bool, str]:
    """فك حظر مستخدم (بواسطة ID)."""
    try:
        row = await DB.fetchone("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if not row:
            return False, f"⚠️ المستخدم {user_id} غير موجود"
        await DB.execute("UPDATE users SET banned=0 WHERE user_id=?", (user_id,))
        with suppress(Exception):
            from cache import invalidate_user_cache as _iuc
            await _iuc(user_id)
        invalidate_auth_cache(user_id=user_id)
        with suppress(Exception):
            await invalidate_auth_cache_async(user_id=user_id)
        return True, f"✅ تم فك حظر المستخدم: {user_id}"
    except Exception as e:
        logger.error(f"❌ unban_user_by_id({user_id}): {e}", exc_info=True)
        return False, f"❌ فشل فك الحظر: {str(e)[:100]}"

# =====================================================================
# 14. نظام العقوبات — Singleton strategies
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
        permissions = ChatPermissions(
            can_send_messages=False, can_send_audios=False, can_send_documents=False,
            can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
            can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False,
            can_add_web_page_previews=False, can_change_info=False,
            can_invite_users=True, can_pin_messages=False,
        )
        try:
            await bot.restrict_chat_member(chat_id, user_id, permissions, until_date=until_date)
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
        permissions = ChatPermissions(
            can_send_messages=True, can_send_audios=False, can_send_documents=False,
            can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
            can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False,
            can_add_web_page_previews=False, can_change_info=False,
            can_invite_users=True, can_pin_messages=False,
        )
        try:
            await bot.restrict_chat_member(chat_id, user_id, permissions, until_date=until_date)
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
    """🧠 v7.8.0: Singleton strategies."""
    _strategies: Dict[str, PenaltyStrategy] = {
        'ban': BanPenalty(),
        'mute': MutePenalty(),
        'kick': KickPenalty(),
        'warn': WarnPenalty(),
        'restrict': RestrictPenalty(),
        'unban': UnbanPenalty(),
    }

    @classmethod
    def get_strategy(cls, penalty_type: str) -> Optional[PenaltyStrategy]:
        return cls._strategies.get(penalty_type)


async def apply_penalty(bot, chat_id: int, user_id: int, penalty: str,
                        duration: int = 60, reason: str = "", moderator: int = None,
                        username: str = "", first_name: str = "",
                        chat_name: str = "") -> Tuple[bool, str]:
    try:
        primary_id = int(CONFIG.PRIMARY_OWNER_ID)
    except (TypeError, ValueError, AttributeError):
        primary_id = None
    if primary_id is not None and user_id == primary_id:
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
        if not username or not first_name:
            try:
                member = await bot.get_chat_member(chat_id, user_id)
                tg_user = getattr(member, "user", None)
                if tg_user:
                    if not username:
                        username = tg_user.username or ""
                    if not first_name:
                        first_name = tg_user.first_name or ""
            except Exception:
                pass
        if not chat_name:
            try:
                chat = await bot.get_chat(chat_id)
                chat_name = getattr(chat, "title", "") or ""
            except Exception:
                pass
        if penalty in DB.VALID_PENALTY_TYPES:
            try:
                await DB.add_penalty(
                    user_id=user_id, chat_id=chat_id, penalty_type=penalty,
                    duration=duration, reason=reason, issued_by=moderator,
                    username=username, first_name=first_name, chat_name=chat_name,
                )
            except TypeError:
                await DB.add_penalty(
                    user_id=user_id, chat_id=chat_id, penalty_type=penalty,
                    duration=duration, reason=reason, issued_by=moderator,
                )
        if moderator:
            try:
                await DB.add_admin_log(chat_id, moderator, penalty, user_id, reason)
            except Exception:
                pass
    return success, msg

# =====================================================================
# 15. الردود التلقائية — helpers
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
                "UPDATE auto_replies SET usage_count = usage_count + ? "
                "WHERE chat_id=? AND keyword=?",
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


async def import_auto_replies(chat_id: int,
                              file_path_or_data: Union[str, List[Dict]],
                              overwrite: bool = False) -> int:
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
                await DB.execute(
                    "DELETE FROM auto_replies WHERE chat_id=? AND keyword=?",
                    (chat_id, keyword)
                )
            reply_type = item.get('reply_type', 'text')
            media_id = item.get('media_file_id')
            buttons = item.get('buttons')
            await DB.add_auto_reply(
                chat_id, keyword, reply, reply_type=reply_type,
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
# 16. الردود من ملف
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
        logger.info("ℹ️ لا يوجد replies.py")
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
# 17. المهام الخلفية — Adaptive + Batch
# =====================================================================

class BackgroundTasks:
    """
    🧠 v7.8.1: كاش المشرفين بتكيّف TTL + batch subscriptions.
    """
    _group_admins_cache: Dict[int, Tuple[float, List[int]]] = {}
    _group_admins_access_count: Dict[int, int] = {}
    _BASE_TTL = 600
    _GROUP_ADMINS_CACHE_MAX_SIZE = 5000

    @staticmethod
    def _adaptive_ttl(chat_id: int) -> int:
        """🧠 TTL يتكيف حسب عدد الاستدعاءات."""
        access = BackgroundTasks._group_admins_access_count.get(chat_id, 0)
        if access >= 20:
            return BackgroundTasks._BASE_TTL * 2
        if access >= 10:
            return int(BackgroundTasks._BASE_TTL * 1.5)
        if access >= 5:
            return BackgroundTasks._BASE_TTL
        if access >= 1:
            return int(BackgroundTasks._BASE_TTL * 0.5)
        return 60

    @staticmethod
    async def _get_admin_ids_cached(bot, chat_id: int,
                                     force_refresh: bool = False) -> List[int]:
        now = time.time()
        if not force_refresh and chat_id in BackgroundTasks._group_admins_cache:
            cached_time, cached_ids = BackgroundTasks._group_admins_cache[chat_id]
            ttl = BackgroundTasks._adaptive_ttl(chat_id)
            if now - cached_time < ttl:
                BackgroundTasks._group_admins_access_count[chat_id] = \
                    BackgroundTasks._group_admins_access_count.get(chat_id, 0) + 1
                return cached_ids

        try:
            admins = await bot.get_chat_administrators(chat_id)
            admin_ids = [a.user.id for a in admins if a.user and not a.user.is_bot]

            if len(BackgroundTasks._group_admins_cache) >= BackgroundTasks._GROUP_ADMINS_CACHE_MAX_SIZE:
                sorted_items = sorted(
                    BackgroundTasks._group_admins_cache.items(),
                    key=lambda x: x[1][0],
                )
                for k, _ in sorted_items[: BackgroundTasks._GROUP_ADMINS_CACHE_MAX_SIZE // 5]:
                    BackgroundTasks._group_admins_cache.pop(k, None)
                    BackgroundTasks._group_admins_access_count.pop(k, None)

            BackgroundTasks._group_admins_cache[chat_id] = (now, admin_ids)
            BackgroundTasks._group_admins_access_count[chat_id] = 1
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
                    with suppress(Exception):
                        await bot.send_message(channel_id, text)
            elif media_type == 'animation' and media_file_id:
                await bot.send_animation(channel_id, media_file_id, caption=caption)
            elif media_type == 'sticker' and media_file_id:
                await bot.send_sticker(channel_id, media_file_id)
                if text:
                    with suppress(Exception):
                        await bot.send_message(channel_id, text)
            elif media_type == 'video_note' and media_file_id:
                await bot.send_video_note(channel_id, media_file_id)
                if text:
                    with suppress(Exception):
                        await bot.send_message(channel_id, text)
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
    async def _publish_single_channel(bot, ch, sleep_seconds, published_count,
                                       has_sub: bool = None):
        """
        🧠 v7.8.1: يقبل has_sub مسبقاً (batch check).
        """
        user_id = None
        try:
            user_id = ch.get('user_id') if isinstance(ch, dict) else None
            if has_sub is None:
                has_sub = (
                    await DB.has_active_subscription(user_id)
                    if user_id else False
                )
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
                logger.info(
                    f"✅ قناة {ch['id']} نشرت. انتظار {sleep_seconds//60} دقيقة..."
                )
                if published_count == 0 or recycled:
                    if user_id:
                        with suppress(Exception):
                            await safe_send(bot, user_id, "✅ تم نشر منشور في قناتك")
                await asyncio.sleep(sleep_seconds)
            else:
                await DB.increment_post_fail(post['id'])
        except Exception as e:
            logger.error(f"❌ خطأ في قناة {ch.get('id', 'غير معروفة')}: {e}")

    @staticmethod
    async def auto_publish(bot) -> None:
        """
        🧠 v7.8.1: batch subscription check + semaphore limit 8.
        """
        await asyncio.sleep(10)
        max_channels = getattr(CONFIG, 'MAX_CHANNELS_PER_CYCLE', 20)
        min_interval_minutes = await get_min_publish_interval()
        sleep_seconds = min_interval_minutes * 60

        def _get_semaphore_size(n: int) -> int:
            """🧠 v7.8.1: حد أقصى أقل لضغط Pool."""
            if n <= 5:
                return 3
            if n <= 10:
                return 5
            return 8

        active_tasks: Dict[int, asyncio.Task] = {}

        while True:
            try:
                channels = await asyncio.wait_for(
                    DB.get_channels_to_publish(max_channels), timeout=10
                )
                if not channels:
                    await asyncio.sleep(60)
                    continue

                # ✅ v7.8.1: batch check للاشتراكات (استعلام واحد)
                user_ids = list({
                    ch.get('user_id') for ch in channels
                    if ch.get('user_id')
                })
                subs_map: Dict[int, bool] = {}
                if user_ids:
                    try:
                        placeholders = ",".join(["?"] * len(user_ids))
                        rows = await DB.fetchall(
                            f"SELECT user_id FROM subscriptions "
                            f"WHERE user_id IN ({placeholders}) "
                            f"AND status = 'active' AND end_date > ?",
                            (*user_ids, TimeUtils.utc_now()),
                        )
                        for r in rows:
                            subs_map[r['user_id']] = True
                        logger.debug(
                            f"✅ batch subs: {len(subs_map)}/{len(user_ids)} نشط"
                        )
                    except Exception as e:
                        logger.warning(f"batch subs check failed: {e}")

                sem_size = _get_semaphore_size(len(channels))
                semaphore = asyncio.Semaphore(sem_size)

                for ch in channels:
                    channel_id = ch['id']
                    if channel_id in active_tasks and not active_tasks[channel_id].done():
                        continue
                    published_count = ch.get('published_count', 0)
                    has_sub = subs_map.get(ch.get('user_id'), False)

                    async def run_publish(ch=ch, bot=bot,
                                          sleep_seconds=sleep_seconds,
                                          published_count=published_count,
                                          semaphore=semaphore,
                                          has_sub=has_sub):
                        async with semaphore:
                            await BackgroundTasks._publish_single_channel(
                                bot, ch, sleep_seconds, published_count,
                                has_sub=has_sub,
                            )

                    task = asyncio.create_task(run_publish())
                    active_tasks[channel_id] = task
                    await asyncio.sleep(0.3)

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
        import time as _time
        t_start = _time.monotonic()
        try:
            if not await DB.get_auto_backup():
                return
            PATHS.BACKUPS.mkdir(parents=True, exist_ok=True)
            backup_file = (
                PATHS.BACKUPS /
                f"backup_{TimeUtils.mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
            )
            success = False
            if hasattr(DB, "backup_database"):
                try:
                    success = await DB.backup_database(backup_file)
                except Exception as e:
                    logger.warning(f"⚠️ DB.backup_database فشل: {e}")
                    success = False
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
                try:
                    await DB.set_setting('last_backup', TimeUtils.sql_iso())
                except Exception as e:
                    logger.warning(f"⚠️ فشل حفظ last_backup: {e}")
                backups = sorted(
                    PATHS.BACKUPS.glob("backup_*.db"),
                    key=lambda x: x.stat().st_mtime, reverse=True,
                )
                for old in backups[CONFIG.MAX_BACKUPS:]:
                    with suppress(Exception):
                        old.unlink()
                elapsed = _time.monotonic() - t_start
                logger.info(
                    f"✅ نسخة احتياطية: {backup_file.name} ({elapsed:.2f}s)"
                )
            else:
                logger.error("❌ فشل النسخ الاحتياطي")
        except Exception as e:
            logger.error(f"❌ _do_backup: {e}", exc_info=True)

    @staticmethod
    async def reminders(bot) -> None:
        while True:
            await asyncio.sleep(3600)
            try:
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
                        except Exception:
                            return False
                    stats = await DB.send_subscription_reminders(send_impl)
                    if isinstance(stats, dict) and stats.get('sent', 0) > 0:
                        logger.info(f"📨 تم إرسال {stats['sent']} تذكير اشتراك")
                elif hasattr(DB, "get_users_for_reminder"):
                    users = await DB.get_users_for_reminder()
                    for u in users:
                        try:
                            days = int(u['days_left'])
                            lang = u.get('language', 'ar')
                            text = await get_text(
                                lang, 'reminder_subscription_expires', days=days
                            )
                            if text == 'reminder_subscription_expires':
                                text = f"⚠️ اشتراكك سينتهي بعد {days} يوم"
                            await safe_send(bot, u['user_id'], text)
                            await asyncio.sleep(0.1)
                        except Exception:
                            pass
            except Exception as e:
                logger.error(f"❌ Reminders: {e}")

    @staticmethod
    async def heartbeat(bot) -> None:
        while True:
            await asyncio.sleep(CONFIG.HEARTBEAT_INTERVAL)
            try:
                ram = get_ram_usage()
                msg = (
                    f"💓 **Heartbeat**\n\n"
                    f"🕐 {TimeUtils.mecca_iso()}\n"
                    f"💾 RAM: {ram['percent']}%"
                )
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
                if not hasattr(DB, "sync_group_admins"):
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
                            chat_id = (group_row['chat_id']
                                       if isinstance(group_row, dict)
                                       else group_row[0])
                            admin_ids = await BackgroundTasks._get_admin_ids_cached(
                                bot, chat_id
                            )
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
        while True:
            await asyncio.sleep(3600)
            try:
                await _security_stats_cache.clear()
                _banned_words_cache.clear()
                _banned_words_cache_time.clear()
                _auto_reply_cache.clear()
                _auth_cache.clear()
                BackgroundTasks._group_admins_cache.clear()
                BackgroundTasks._group_admins_access_count.clear()
                logger.info("✅ تم تنظيف الكاش المؤقت")
            except Exception as e:
                logger.error(f"❌ فشل تنظيف الكاش: {e}")
            try:
                cutoff_30 = TimeUtils.utc_now() - timedelta(days=30)
                cutoff_60 = TimeUtils.utc_now() - timedelta(days=60)
                cutoff_90 = TimeUtils.utc_now() - timedelta(days=90)
                await DB.execute(
                    "DELETE FROM admin_logs WHERE created_at < ?", (cutoff_30,)
                )
                await DB.execute(
                    "DELETE FROM user_penalties WHERE created_at < ?", (cutoff_60,)
                )
                await DB.execute(
                    "DELETE FROM payment_logs WHERE created_at < ?", (cutoff_90,)
                )
                logger.info("✅ تم تنظيف البيانات القديمة")
            except Exception as e:
                logger.error(f"❌ فشل تنظيف قاعدة البيانات: {e}")

# =====================================================================
# 18. Warmup الشامل
# =====================================================================

async def warmup_all() -> Dict[str, Any]:
    """
    🧠 v7.8.3: تحميل كل الموارد في الذاكرة عند بدء التشغيل.
    يشمل: اللغات، الأزرار، الكلمات المحظورة (utils + Database)، الردود.
    """
    result = {
        'translations_loaded': 0,
        'buttons_loaded': 0,
        'banned_words_loaded': 0,
        'db_banned_words_loaded': 0,
        'replies_loaded': 0,
        'total_ms': 0,
    }
    t_start = time.monotonic()

    try:
        # 1) اللغات
        result['translations_loaded'] = TranslationManager.preload_all()

        # 2) الأزرار
        result['buttons_loaded'] = KeyboardFactory.preload_all()

        # 3) الكلمات المحظورة العامة (utils cache)
        try:
            words = await asyncio.wait_for(_get_global_words_cached(), timeout=5)
            result['banned_words_loaded'] = len(words)
        except Exception as e:
            logger.debug(f"warmup banned_words (utils): {e}")

        # 4) ✅ v7.8.3: الكلمات المحظورة في Database cache أيضاً
        try:
            if hasattr(DB, 'get_banned_words'):
                db_words = await asyncio.wait_for(
                    DB.get_banned_words(-1), timeout=5
                )
                result['db_banned_words_loaded'] = len(db_words or [])
        except Exception as e:
            logger.debug(f"warmup banned_words (DB): {e}")

        # 5) الردود
        result['replies_loaded'] = len(_REPLIES_FROM_FILE) if _REPLIES_FROM_FILE else 0

    except Exception as e:
        logger.error(f"❌ Warmup error: {e}", exc_info=True)

    result['total_ms'] = int((time.monotonic() - t_start) * 1000)
    logger.info(
        f"🔥 Warmup: {result['translations_loaded']} لغة + "
        f"{result['buttons_loaded']} أزرار + "
        f"{result['banned_words_loaded']} كلمة (utils) + "
        f"{result['db_banned_words_loaded']} كلمة (DB) + "
        f"{result['replies_loaded']} رد — "
        f"{result['total_ms']}ms"
    )
    return result

# =====================================================================
# 19. خادم الويب
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
# 20. معالج الأخطاء
# =====================================================================

class ErrorHandler:
    @staticmethod
    async def handle_error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            error_msg = str(context.error)
            if update:
                logger.error(
                    f"❌ خطأ في التحديث {update.update_id}: {context.error}",
                    exc_info=True,
                )
            else:
                logger.error(f"❌ خطأ: {context.error}", exc_info=True)
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
                    await safe_send(
                        context.bot, log_channel, short_msg,
                        parse_mode='Markdown'
                    )
            except Exception:
                pass
        except Exception:
            pass

# =====================================================================
# تصدير
# =====================================================================

__all__ = [
    'TimeUtils', 'TextUtils', 'RateLimiter', 'RATE_LIMITER',
    'PUBLISH_RATE_LIMITER', 'METRICS',
    'AutoReplyCache', 'TranslationManager', 'get_text',
    'UserState', 'StateManager', 'CB', 'KeyboardFactory',
    'get_banned_words_cached', 'invalidate_banned_words_cache',
    'get_min_publish_interval',
    'is_authorized_in_group', 'invalidate_auth_cache',
    'invalidate_auth_cache_async', 'check_bot_permissions',
    'safe_send', 'get_ram_usage',
    'ban_user_by_id', 'unban_user_by_id',
    'PenaltyStrategy', 'BanPenalty', 'MutePenalty', 'KickPenalty',
    'WarnPenalty', 'RestrictPenalty', 'UnbanPenalty', 'PenaltyFactory',
    'apply_penalty',
    'export_auto_replies', 'import_auto_replies', 'fetch_json_from_url',
    'load_replies_from_file', 'get_reply_from_file', 'reload_replies_from_file',
    'BackgroundTasks', 'setup_webhook', 'webhook_handler', 'ErrorHandler',
    'SmartCache', 'warmup_all',
]