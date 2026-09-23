#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_message.py - معالجات الرسائل (v7.9.12 - Refresh admin commands)
=====================================================================
🆕 v7.9.12 (تحديث أوامر الأدمن عند إضافة/إزالة):
    ✅ _handle_admin_add_input: بعد نجاح الإضافة → refresh_admin_commands(True)
    ✅ _handle_admin_rem_input: بعد نجاح الإزالة → refresh_admin_commands(False)
    ✅ _refresh_admin_commands_safe: lazy import آمن (لا circular import)
    ✅ فشل التحديث لا يُفشل العملية الأساسية (try/except)

🆕 v7.9.11 (حذف رسالة العقوبة تلقائياً بعد 10 ثواني):
    ✅ _delete_and_warn: رسالة العقوبة (🚨) تُحذف بعد 10 ثواني

🆕 v7.9.10 (إصلاح _fmt TypeError):
    ✅ _fmt: اسم البارامتر `template` بدل `text`

🆕 v7.9.9: apply_penalty: بدون سطر @username (utils.py)
🆕 v7.9.8: apply_violation_penalty: يقبل lang ويعيد رسالة كاملة
🆕 v7.9.3: _handle_redeem_gift_input: send_code_empty
🆕 v7.9.2: handle_log_group_input + _do_db_restore: حذف WAL/SHM
=====================================================================
"""

import asyncio
import logging
import time
import os
import re
import json
import shutil
import tempfile
from pathlib import Path
from html import escape
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from urllib.parse import urlparse

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut

from config import CONFIG, PATHS
from database import DB, TimeUtils, internal_cache
from utils import (
    TextUtils, safe_send, is_authorized_in_group,
    check_bot_permissions, invalidate_auth_cache, apply_penalty,
    RATE_LIMITER, METRICS, get_text, StateManager, UserState,
    KeyboardFactory, CB, RateLimiter,
    get_banned_words_cached, invalidate_banned_words_cache,
    _auto_reply_cache, get_reply_from_file, _REPLIES_FROM_FILE,
    reload_replies_from_file, _increment_usage_async,
    fetch_json_from_url, import_auto_replies,
    ban_user_by_id, unban_user_by_id,
    TranslationManager,
)
from cache import settings_cache, banned_words_cache, auth_cache, posts_cache

try:
    from replies import analyze_sentiment
except ImportError:
    logging.getLogger(__name__).warning("⚠️ replies.py not found")
    analyze_sentiment = None

logger = logging.getLogger(__name__)


# =====================================================================
# استيراد أداة التحقق من database_settings
# =====================================================================

try:
    from database_settings import _is_valid_channel_ref
except ImportError:
    _TG_USERNAME_RE_FALLBACK = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{3,31}$')

    def _is_valid_channel_ref(value) -> bool:
        if value is None:
            return True
        v = str(value).strip()
        if not v:
            return True
        if v.lstrip('-').isdigit():
            return True
        if v.startswith('@'):
            return bool(_TG_USERNAME_RE_FALLBACK.match(v[1:]))
        if _TG_USERNAME_RE_FALLBACK.match(v):
            return True
        lower = v.lower()
        for prefix in (
            'https://t.me/', 'http://t.me/',
            'https://telegram.me/', 'http://telegram.me/',
            't.me/', 'telegram.me/',
        ):
            if lower.startswith(prefix):
                username = v[len(prefix):].split('/')[0].split('?')[0]
                if username.startswith('@'):
                    username = username[1:]
                if _TG_USERNAME_RE_FALLBACK.match(username):
                    return True
                if username.startswith('+'):
                    return True
                if username.lower() == 'joinchat':
                    return True
                return False
        return False


# =====================================================================
# ثوابت
# =====================================================================

MAX_SUPPORT_MESSAGE_LENGTH = 4000
MAX_BROADCAST_MESSAGE_LENGTH = 4000
MAX_IMPORT_FILE_SIZE = 5 * 1024 * 1024
MAX_GIFT_CODE_LENGTH = 50
MAX_VIOLATION_STRIKES = 100
MAX_ADMIN_BROADCAST_TARGETS = 100_000
BROADCAST_DELAY_SECONDS = 0.1
MAX_GROUP_LIMITERS_CACHE = 1000

MAX_SEC_AUTH_CACHE_SIZE = 5000
SEC_AUTH_CACHE_TTL = 300
CACHE_CLEANUP_INTERVAL = 3600

_DELETE_IGNORED_PATTERNS = (
    "message to delete not found",
    "message can't be deleted",
    "message identifier is not specified",
    "message is not found",
)

_MEDIA_REPLY_TYPES = frozenset({
    'photo', 'video', 'document', 'audio',
    'animation', 'voice', 'sticker', 'video_note',
})

TRANSLATION_REPLY_DELETE_DELAY = 30
TRANSLATION_MIN_TEXT_LENGTH = 2

# ✅ v7.9.11: مدة بقاء رسالة العقوبة قبل الحذف
PENALTY_MESSAGE_DELETE_DELAY = 10


# =====================================================================
# كاش الصلاحيات
# =====================================================================

_sec_auth_cache: Dict[Tuple[int, int], Tuple[bool, float]] = {}
_sec_auth_cache_lock = asyncio.Lock()


async def _sec_auth_cache_get(user_id: int, chat_id: int) -> Optional[bool]:
    key = (user_id, chat_id)
    entry = _sec_auth_cache.get(key)
    if entry is None:
        return None
    result, ts = entry
    if time.monotonic() - ts > SEC_AUTH_CACHE_TTL:
        _sec_auth_cache.pop(key, None)
        return None
    return result


async def _sec_auth_cache_set(user_id: int, chat_id: int, result: bool) -> None:
    key = (user_id, chat_id)
    async with _sec_auth_cache_lock:
        if len(_sec_auth_cache) >= MAX_SEC_AUTH_CACHE_SIZE and key not in _sec_auth_cache:
            sorted_items = sorted(_sec_auth_cache.items(), key=lambda x: x[1][1])
            to_remove = len(_sec_auth_cache) // 4
            for k, _ in sorted_items[:to_remove]:
                _sec_auth_cache.pop(k, None)
        _sec_auth_cache[key] = (result, time.monotonic())


async def _sec_auth_cache_cleanup() -> int:
    async with _sec_auth_cache_lock:
        now = time.monotonic()
        expired = [k for k, (_, ts) in _sec_auth_cache.items()
                   if now - ts > SEC_AUTH_CACHE_TTL]
        for k in expired:
            del _sec_auth_cache[k]
        return len(expired)


def _is_delete_ignore_error(exc: Exception) -> bool:
    try:
        err = str(exc).lower()
        return any(p in err for p in _DELETE_IGNORED_PATTERNS)
    except Exception:
        return False


async def _safe_delete_message(bot, chat_id: int, message_id: int) -> bool:
    try:
        await bot.delete_message(chat_id, message_id)
        return True
    except BadRequest as e:
        if _is_delete_ignore_error(e):
            return True
        logger.warning(f"delete failed: {e}")
        return False
    except Exception as e:
        if _is_delete_ignore_error(e):
            return True
        logger.warning(f"delete failed: {e}")
        return False


# =====================================================================
# 🆕 v7.9.12: تحديث أوامر الأدمن (lazy import — لا circular)
# =====================================================================

async def _refresh_admin_commands_safe(bot, user_id: int, is_admin: bool) -> bool:
    """
    🆕 v7.9.12: يستدعي main.refresh_admin_commands بشكل آمن.

    السبب:
      - main.py يستورد من handlers_message.py
      - استيراد main في الأعلى = circular import
      - الحل: lazy import داخل الدالة

    السلوك:
      - فشل الاستيراد أو الاستدعاء → تحذير بسيط، لا يُفشل العملية
      - النجاح → True | الفشل → False
    """
    if not user_id:
        return False
    try:
        from main import refresh_admin_commands
    except ImportError as e:
        logger.debug(f"refresh_admin_commands import: {e}")
        return False
    except Exception as e:
        logger.warning(f"⚠️ refresh_admin_commands import: {e}")
        return False

    try:
        result = await refresh_admin_commands(bot, user_id, is_admin)
        if result:
            logger.info(
                f"✅ أوامر الأدمن حُدِّثت: user={user_id} "
                f"is_admin={is_admin}"
            )
        else:
            logger.warning(
                f"⚠️ refresh_admin_commands أعاد False: "
                f"user={user_id} is_admin={is_admin}"
            )
        return bool(result)
    except Exception as e:
        logger.warning(
            f"⚠️ refresh_admin_commands({user_id}, {is_admin}): {e}"
        )
        return False


# =====================================================================
# إبطال الكاش
# =====================================================================

async def _invalidate_after_channel_change(
    user_id: int,
    channel_db_id: Optional[int] = None,
    invalidate_posts: bool = True,
) -> None:
    keys = [
        f"start_data_{user_id}",
        f"user_{user_id}",
        f"user_{user_id}_True",
        f"user_{user_id}_False",
        f"channels_{user_id}",
    ]
    if channel_db_id is not None:
        keys.append(f"channel_info_{channel_db_id}")
    for k in keys:
        try:
            await internal_cache.invalidate(k)
        except Exception:
            pass
    try:
        from cache import invalidate_user_cache
        await invalidate_user_cache(user_id)
    except Exception:
        pass
    if invalidate_posts and channel_db_id is not None:
        try:
            await posts_cache.invalidate(channel_db_id)
        except Exception:
            pass


# =====================================================================
# Rate Limiter Manager
# =====================================================================

class GroupRateLimiterManager:
    _limiters: Dict[int, RateLimiter] = {}
    _last_access: Dict[int, float] = {}
    _lock = asyncio.Lock()
    MAX_SIZE = MAX_GROUP_LIMITERS_CACHE

    @classmethod
    async def get(cls, chat_id: int) -> RateLimiter:
        async with cls._lock:
            now = time.time()
            if len(cls._limiters) >= cls.MAX_SIZE and chat_id not in cls._limiters:
                sorted_items = sorted(cls._last_access.items(), key=lambda x: x[1])
                to_remove = sorted_items[: cls.MAX_SIZE // 5]
                for cid, _ in to_remove:
                    cls._limiters.pop(cid, None)
                    cls._last_access.pop(cid, None)
            if chat_id not in cls._limiters:
                cls._limiters[chat_id] = RateLimiter(max_concurrent=5, max_per_second=10)
            cls._last_access[chat_id] = now
            return cls._limiters[chat_id]

    @classmethod
    def cleanup(cls) -> int:
        n = len(cls._limiters)
        cls._limiters.clear()
        cls._last_access.clear()
        return n

    @classmethod
    async def periodic_cleanup_task(cls):
        while True:
            try:
                await asyncio.sleep(CACHE_CLEANUP_INTERVAL)
                now = time.time()
                async with cls._lock:
                    to_remove = [cid for cid, ts in cls._last_access.items()
                                 if now - ts > 7200]
                    for cid in to_remove:
                        cls._limiters.pop(cid, None)
                        cls._last_access.pop(cid, None)
                cleaned = await _sec_auth_cache_cleanup()
                if cleaned > 0:
                    logger.debug(f"🧹 sec_auth_cache: {cleaned}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"❌ periodic_cleanup: {e}")


# =====================================================================
# الترجمة
# =====================================================================

async def _trans(key: str, lang: str, default: str = "") -> str:
    """ترجمة آمنة"""
    if not key:
        return default or ""
    try:
        if lang and lang != 'off':
            text = TranslationManager.get_text(lang, key)
            if text and text != key:
                return text
    except Exception:
        pass
    try:
        if lang and lang != 'off':
            text = await get_text(lang, key)
            if text and text != key:
                return text
    except Exception:
        pass
    return default or key


# ═══════════════════════════════════════════════════════════════════
# ✅ v7.9.10: _fmt مُصلَح — اسم البارامتر template بدل text
# ═══════════════════════════════════════════════════════════════════
def _fmt(template: str, **kwargs) -> str:
    """
    ✅ v7.9.10: اسم البارامتر `template` بدل `text`.

    كان الخطأ:
      def _fmt(text: str, **kwargs):
      _fmt(await _trans('set_success', lang, "✅ {text}"), text=escape(text))
      → TypeError: _fmt() got multiple values for argument 'text'
    """
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


async def _ensure_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    lang = context.user_data.get('lang')
    if lang:
        return lang
    user_id = None
    try:
        user_id = update.effective_user.id if update and update.effective_user else None
    except Exception:
        pass
    if user_id:
        try:
            from cache import user_cache
            cached = await user_cache.get(user_id)
            if cached and cached.get('language'):
                lang = cached['language']
                context.user_data['lang'] = lang
                return lang
        except Exception:
            pass
        try:
            lang = await asyncio.wait_for(
                DB.get_user_language(user_id), timeout=2.0) or 'ar'
            context.user_data['lang'] = lang
            return lang
        except Exception:
            pass
    return 'ar'


def clear_lang_cache(context: ContextTypes.DEFAULT_TYPE) -> None:
    """يمسح كاش اللغة"""
    try:
        context.user_data.pop('lang', None)
        context.user_data.pop('translation_cache', None)
        context.user_data.pop('cached_translations', None)
        context.user_data.pop('last_translation', None)
    except Exception as e:
        logger.debug(f"clear_lang_cache: {e}")


# =====================================================================
# دوال مساعدة
# =====================================================================

async def get_security_settings_cached(chat_id: int) -> dict:
    cached = await settings_cache.get_security(chat_id)
    if cached is not None:
        return cached
    settings = await DB.get_security_settings(chat_id)
    await settings_cache.set_security(chat_id, settings)
    return settings


async def get_auto_reply_settings_cached(chat_id: int) -> dict:
    cached = await settings_cache.get_auto_reply_settings(chat_id)
    if cached is not None:
        return cached
    settings = await DB.get_auto_reply_settings(chat_id)
    await settings_cache.set_auto_reply_settings(chat_id, settings)
    return settings


async def invalidate_security_cache(chat_id: int = None) -> None:
    await settings_cache.invalidate_security(chat_id)


async def invalidate_auto_reply_cache(chat_id: int = None) -> None:
    await settings_cache.invalidate_auto_reply(chat_id)


async def _delete_after_delay(bot, chat_id: int, message_id: int, delay: int = 10):
    """
    ✅ حذف رسالة بعد تأخير محدد (افتراضياً 10 ثواني).
    """
    await asyncio.sleep(delay)
    await _safe_delete_message(bot, chat_id, message_id)


# =====================================================================
# الترجمة التلقائية
# =====================================================================

async def _detect_and_translate(update, context, chat_id, user_id, text) -> Optional[str]:
    if not text or len(text.strip()) < TRANSLATION_MIN_TEXT_LENGTH:
        return None
    try:
        lang = await _ensure_lang(update, context)
        if not lang or lang == 'off':
            return None
        if text.startswith('/'):
            return None
        stripped = text.strip()
        if stripped.startswith(('http://', 'https://', 'www.')):
            return None
        is_arabic = TranslationManager.detect_arabic(text)
        if lang == 'ar' and is_arabic:
            return None
        if lang != 'ar' and not is_arabic:
            return None
        translated = TranslationManager.translate(text, lang)
        if translated and translated != text:
            return translated
    except Exception as e:
        logger.debug(f"_detect_and_translate: {e}")
    return None


async def _send_translation_reply(bot, chat_id, original_message_id, translated, lang):
    try:
        label = TranslationManager.get_text(lang, "translation_label") or "🌐 <b>Translation:</b>"
    except Exception:
        label = "🌐 <b>Translation:</b>"
    try:
        kwargs = {
            "chat_id": chat_id,
            "text": f"{label}\n{escape(translated)}",
            "parse_mode": 'HTML',
        }
        if original_message_id:
            kwargs["reply_to_message_id"] = original_message_id
        sent = await bot.send_message(**kwargs)
        asyncio.create_task(
            _delete_after_delay(bot, chat_id, sent.message_id,
                                TRANSLATION_REPLY_DELETE_DELAY))
    except Exception as e:
        logger.debug(f"_send_translation_reply: {e}")


# ═══════════════════════════════════════════════════════════════════
# apply_violation_penalty — يقبل lang
# ═══════════════════════════════════════════════════════════════════

async def apply_violation_penalty(update, context, chat_id, user_id,
                                   violation_type, penalty_type,
                                   duration_seconds,
                                   lang: str = 'ar') -> Tuple[bool, str]:
    """✅ v7.9.8: تدعم تمرير lang."""
    try:
        username = first_name = chat_name = ""
        try:
            if update and update.effective_user:
                username = update.effective_user.username or ""
                first_name = update.effective_user.first_name or ""
            if update and update.effective_chat:
                chat_name = update.effective_chat.title or ""
        except Exception:
            pass

        success, msg = await apply_penalty(
            context.bot, chat_id, user_id, penalty_type, duration_seconds,
            f"violation: {violation_type}", moderator=context.bot.id,
            username=username, first_name=first_name, chat_name=chat_name,
            lang=lang,
        )
        return success, msg
    except Exception as e:
        logger.error(f"❌ apply_violation_penalty: {e}")
        return False, str(e)[:100]


def _is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        blocked = ("localhost", "127.", "0.0.0.0", "::1",
                   "10.", "192.168.", "172.16.", "172.17.", "172.18.",
                   "172.19.", "172.2", "172.30.", "172.31.",
                   "169.254.", "metadata.google")
        for pattern in blocked:
            if host.startswith(pattern) or host == pattern.rstrip("."):
                return False
        return True
    except Exception:
        return False


def _parse_contest_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    date_str = date_str.strip()
    try:
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        pass
    try:
        return datetime.fromisoformat(date_str.replace(" ", "T"))
    except (ValueError, TypeError):
        pass
    formats = ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
               "%d-%m-%Y %H:%M", "%d-%m-%Y")
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


async def _check_admin_in_chat(context, chat_id: int, user_id: int) -> bool:
    if user_id == CONFIG.PRIMARY_OWNER_ID:
        return True
    try:
        result = await is_authorized_in_group(context.bot, chat_id, user_id)
        if result:
            return True
    except Exception:
        pass
    try:
        row = await DB.fetchval(
            "SELECT 1 FROM group_admins WHERE chat_id = ? AND user_id = ? LIMIT 1",
            (chat_id, user_id))
        return row is not None
    except Exception:
        return False


async def _is_postgres_db() -> bool:
    try:
        return getattr(DB, "DB_TYPE", "sqlite") == "postgres"
    except Exception:
        return False


async def _is_mysql_db() -> bool:
    try:
        return getattr(DB, "DB_TYPE", "sqlite") == "mysql"
    except Exception:
        return False


# =====================================================================
# MessageHandlers
# =====================================================================

class MessageHandlers:

    _PRIVATE_HANDLERS_MAP: Dict[UserState, str] = {
        UserState.WAIT_CHANNEL: "_handle_channel_input",
        UserState.ADDING_POSTS: "_handle_adding_posts",
        UserState.SUPPORT_MODE: "_handle_support_message",
        UserState.WAIT_BROADCAST: "_handle_broadcast_input",
        UserState.WAIT_UPDATE: "_handle_update_input",
        UserState.WAIT_UPDATE_CH: "_handle_update_ch_input",
        UserState.WAIT_FORCE: "_handle_force_input",
        UserState.WAIT_LOG_CH: "_handle_log_ch_input",
        UserState.WAIT_ADMIN_ADD: "_handle_admin_add_input",
        UserState.WAIT_ADMIN_REM: "_handle_admin_rem_input",
        UserState.WAIT_KEYWORD: "_handle_keyword_input",
        UserState.WAIT_REPLY: "_handle_reply_input",
        UserState.WAIT_GLOBAL_BAN: "_handle_global_ban_input",
        UserState.WAIT_REM_GLOBAL_BAN: "_handle_rem_global_ban_input",
        UserState.WAIT_GROUP_BAN: "_handle_group_ban_input",
        UserState.WAIT_REM_GROUP_BAN: "_handle_rem_group_ban_input",
        UserState.WAIT_CONTEST_TITLE: "_handle_contest_title",
        UserState.WAIT_CONTEST_DESC: "_handle_contest_desc",
        UserState.WAIT_CONTEST_PRIZE: "_handle_contest_prize",
        UserState.WAIT_CONTEST_DATE: "_handle_contest_date",
        UserState.WAIT_CONTEST_ANSWER: "_handle_contest_answer",
        UserState.WAIT_AUTO_KEY: "_handle_auto_key",
        UserState.WAIT_AUTO_REPLY: "_handle_auto_reply_input",
        UserState.WAIT_AUTO_DEL: "_handle_auto_del",
        UserState.WAIT_IMPORT_FILE: "_handle_import_file",
        UserState.WAIT_GITHUB_URL: "_handle_github_url",
        UserState.WAIT_GRANT_FREE: "_handle_grant_free",
        UserState.WAIT_MIN: "_handle_min_input",
        UserState.WAIT_HOUR: "_handle_hour_input",
        UserState.WAIT_DAY: "_handle_day_input",
        UserState.WAIT_PUB_TIME: "_handle_pub_time_input",
        UserState.WAIT_REM_DAYS: "_handle_rem_days_input",
        UserState.WAIT_MAX_LEN: "_handle_max_len_input",
        UserState.WAIT_WARN_COUNT: "_handle_warn_count_input",
        UserState.WAIT_WELCOME_TEXT: "_handle_welcome_text_input",
        UserState.WAIT_GOODBYE_TEXT: "_handle_goodbye_text_input",
        UserState.WAIT_SLOW_MODE_SECONDS: "_handle_slow_mode_input",
        UserState.WAIT_ANTIFLOOD_MESSAGES: "_handle_antiflood_messages_input",
        UserState.WAIT_ANTIFLOOD_SECONDS: "_handle_antiflood_seconds_input",
        UserState.WAIT_NIGHT_START: "_handle_night_start_input",
        UserState.WAIT_NIGHT_END: "_handle_night_end_input",
        UserState.WAIT_BAN: "_handle_ban_input",
        UserState.WAIT_MUTE: "_handle_mute_input",
        UserState.WAIT_WARN: "_handle_warn_input",
        UserState.WAIT_KICK: "_handle_kick_input",
        UserState.WAIT_RESTRICT: "_handle_restrict_input",
        UserState.WAIT_UNBAN: "_handle_unban_input",
        UserState.WAIT_PIN: "_handle_pin_input",
        UserState.WAIT_PENALTY_DURATION: "_handle_penalty_duration_input",
        UserState.WAIT_VIOLATION_STRIKES: "_handle_violation_strikes_input",
        UserState.WAIT_VIOLATION_DURATION: "_handle_violation_duration_input",
        UserState.WAIT_REDEEM_GIFT: "_handle_redeem_gift_input",
        UserState.WAIT_RESTORE: "_handle_restore_input",
        UserState.WAIT_BACKUP_FILE: "_handle_backup_file_input",
        UserState.WAIT_BAN_USER_ID: "_handle_ban_user_input",
        UserState.WAIT_UNBAN_USER_ID: "_handle_unban_user_input",
        UserState.WAIT_PENALTY_DEFAULT_DURATION: "_handle_penalty_default_duration",
        UserState.WAIT_CONTEST_WINNER: "_handle_contest_winner",
        UserState.WAIT_PENALTY_MUTE_DURATION: "_handle_penalty_mute_duration",
        UserState.WAIT_PENALTY_BAN_DURATION: "_handle_penalty_ban_duration",
        UserState.WAIT_PENALTY_RESTRICT_DURATION: "_handle_penalty_restrict_duration",
    }

    # =================================================================
    # الرسائل الخاصة
    # =================================================================

    @staticmethod
    async def handle_private(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        lang = 'ar'
        try:
            user_id = update.effective_user.id
            state = StateManager.get(user_id)

            if state == UserState.WAIT_LOG_CH and context.user_data.get('log_group_id'):
                handled = await MessageHandlers.handle_log_group_input(update, context)
                if handled:
                    return

            lang = await _ensure_lang(update, context)

            if state == UserState.WAIT_MOOD:
                if analyze_sentiment is None:
                    msg = await _trans('mood_service_unavailable', lang, "❌")
                    await safe_send(context.bot, user_id, msg)
                    StateManager.clear(user_id)
                    return
                text = update.effective_message.text or ""
                result = analyze_sentiment(text)
                title = await _trans('mood_analysis', lang, "🎭")
                text_l = await _trans('mood_text', lang, "📝")
                result_l = await _trans('mood_result', lang, "🎯")
                pos_l = await _trans('mood_positive', lang, "😊")
                neg_l = await _trans('mood_negative', lang, "😔")
                words_l = await _trans('mood_words', lang, "📊")
                response = (
                    f"{result['emoji']} <b>{title}</b>\n\n"
                    f"{text_l}: <code>{escape(text[:100])}</code>\n"
                    f"{result_l}: <b>{escape(result['sentiment'])}</b>\n\n"
                    f"{pos_l}: {result['positive_percent']:.0f}%\n"
                    f"{neg_l}: {result['negative_percent']:.0f}%\n"
                    f"{words_l}: {result['total_words']}"
                )
                await safe_send(context.bot, user_id, response, parse_mode='HTML')
                StateManager.clear(user_id)
                return

            if (state is None or state == UserState.NONE) and lang != 'off':
                try:
                    msg_obj = update.effective_message
                    user_text = ""
                    if msg_obj:
                        user_text = msg_obj.text or msg_obj.caption or ""
                    if user_text and not user_text.startswith('/'):
                        translated = TranslationManager.translate(user_text, lang)
                        if translated and translated != user_text:
                            label = TranslationManager.get_text(
                                lang, "translation_label"
                            ) or "🌐 <b>Translation:</b>"
                            await safe_send(
                                context.bot, user_id,
                                f"{label}\n{escape(translated)}",
                                parse_mode='HTML')
                except Exception as e:
                    logger.debug(f"private translation: {e}")

            handler_name = MessageHandlers._PRIVATE_HANDLERS_MAP.get(state)
            if handler_name:
                handler = getattr(MessageHandlers, handler_name, None)
                if handler:
                    await handler(update, context)
                else:
                    logger.warning(f"⚠️ handler not found: {handler_name}")
        except Exception as e:
            logger.exception("handle_private error")
            try:
                msg = await _trans('unexpected_error', lang, "❌")
                await safe_send(context.bot, update.effective_user.id, msg)
            except Exception:
                pass

    # =================================================================
    # handle_log_group_input
    # =================================================================

    @staticmethod
    async def handle_log_group_input(update, context) -> bool:
        """✅ v7.9.2: معالج إدخال قناة سجل لمجموعة معيّنة."""
        user_id = update.effective_user.id
        log_group_id = context.user_data.get('log_group_id')
        if not log_group_id:
            return False

        lang = await _ensure_lang(update, context)

        if not await _check_admin_in_chat(context, log_group_id, user_id):
            msg = await _trans('no_permission', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            context.user_data.pop('log_group_id', None)
            return True

        text = (update.effective_message.text or "").strip()

        if text.lower() in ('none', 'cancel', 'remove', '-'):
            try:
                ok = await DB.remove_group_log_channel(log_group_id)
            except Exception as e:
                logger.error(f"remove_group_log_channel: {e}", exc_info=True)
                ok = False
            msg = (await _trans('log_channel_removed', lang, "🗑️")
                   if ok else await _trans('delete_failed', lang, "❌"))
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            context.user_data.pop('log_group_id', None)
            return True

        if not _is_valid_channel_ref(text):
            preview = text[:50] if text else ""
            logger.warning(
                f"⚠️ v7.9.2: رفض log_channel_ref غير صالح "
                f"من {user_id}: {preview!r}"
            )
            msg = await _trans(
                'invalid_channel_ref', lang,
                "❌ <b>قيمة غير صالحة</b>\n\n"
                "أرسل:\n"
                "• معرّف رقمي: <code>-1001234567890</code>\n"
                "• أو @username\n"
                "• أو رابط: <code>https://t.me/username</code>\n\n"
                "أو أرسل <code>none</code> للإزالة."
            )
            await safe_send(context.bot, user_id, msg, parse_mode='HTML')
            return True

        channel_int = None
        try:
            if text.lstrip('-').isdigit():
                channel_int = int(text)
            else:
                chat = await context.bot.get_chat(text)
                channel_int = chat.id
        except Exception as e:
            logger.warning(f"resolve log channel {text!r}: {e}")
            channel_int = None

        if channel_int is None:
            msg = await _trans('channel_not_found', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            return True

        try:
            ok = await DB.set_group_log_channel(log_group_id, channel_int)
        except Exception as e:
            logger.error(f"set_group_log_channel: {e}", exc_info=True)
            ok = False

        if ok:
            try:
                await internal_cache.invalidate(f"log_ch_menu_{log_group_id}")
                await internal_cache.invalidate(f"group_log_{log_group_id}")
            except Exception:
                pass
            msg = _fmt(
                await _trans('log_channel_saved', lang, "✅ {text}"),
                text=escape(text)
            )
            await safe_send(context.bot, user_id, msg)
        else:
            msg = await _trans('save_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)

        StateManager.clear(user_id)
        context.user_data.pop('log_group_id', None)
        return True

    # =================================================================
    # حظر / فك حظر
    # =================================================================

    @staticmethod
    async def _handle_ban_user_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            msg = await _trans('unauthorized', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        text = (update.effective_message.text or "").strip()
        try:
            target_id = int(text)
        except (ValueError, AttributeError):
            msg = await _trans('invalid_user_id', lang, "❌")
            await safe_send(context.bot, user_id, msg, parse_mode='HTML')
            return
        if target_id == user_id:
            msg = await _trans('cant_ban_self', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        success, msg = await ban_user_by_id(target_id)
        await safe_send(context.bot, user_id, msg)
        if success:
            try:
                await context.bot.send_message(target_id, "🚫")
            except Exception:
                pass
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_unban_user_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            msg = await _trans('unauthorized', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        text = (update.effective_message.text or "").strip()
        try:
            target_id = int(text)
        except (ValueError, AttributeError):
            msg = await _trans('invalid_user_id', lang, "❌")
            await safe_send(context.bot, user_id, msg, parse_mode='HTML')
            return
        success, msg = await unban_user_by_id(target_id)
        await safe_send(context.bot, user_id, msg)
        if success:
            try:
                await context.bot.send_message(target_id, "✅")
            except Exception:
                pass
        StateManager.clear(user_id)

    # =================================================================
    # المعالجات الخمسة
    # =================================================================

    @staticmethod
    async def _handle_penalty_default_duration(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = (context.user_data.get('adv_chat')
                   or context.user_data.get('sec_chat')
                   or context.user_data.get('security_chat_id'))
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if not await _check_admin_in_chat(context, chat_id, user_id):
            msg = await _trans('not_admin_in_group', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            minutes = int((update.effective_message.text or "").strip())
            if minutes <= 0 or minutes > 43200:
                raise ValueError("out of range")
            duration_seconds = minutes * 60
            await DB.update_security_settings(
                chat_id,
                mute_default_duration=duration_seconds,
                ban_default_duration=duration_seconds,
                restrict_default_duration=duration_seconds)
            await invalidate_security_cache(chat_id)
            msg = await _trans('duration_set_success', lang, "✅")
            msg = _fmt(msg, duration=minutes * 60)
            await safe_send(context.bot, user_id, msg)
        except (ValueError, AttributeError):
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"default_duration: {e}", exc_info=True)
            msg = await _trans('execution_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_contest_winner(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            msg = await _trans('unauthorized', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        contest_id = (context.user_data.get('contest_join')
                      or context.user_data.get('contest_id'))
        if not contest_id:
            msg = await _trans('no_active_contest', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            winner_id = int((update.effective_message.text or "").strip())
            if winner_id <= 0:
                raise ValueError
        except (ValueError, AttributeError):
            msg = await _trans('invalid_user_id', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            return
        try:
            success = await DB.declare_winner(contest_id, winner_id)
            if success:
                msg = _fmt(await _trans('winner_announced', lang,
                                         "✅ {winner_id}"), winner_id=winner_id)
                await safe_send(context.bot, user_id, msg, parse_mode='HTML')
                try:
                    congrats = await _trans('congrats_winner_full', lang, "🎉")
                    await context.bot.send_message(winner_id, congrats)
                except Exception:
                    pass
            else:
                msg = await _trans('declare_failed', lang, "❌")
                await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"contest_winner: {e}", exc_info=True)
            msg = await _trans('execution_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_penalty_mute_duration(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = (context.user_data.get('sec_chat')
                   or context.user_data.get('security_chat_id'))
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            minutes = int((update.effective_message.text or "").strip())
            if minutes < 0 or minutes > 43200:
                raise ValueError
            duration_seconds = minutes * 60
            await DB.update_security_settings(
                chat_id, mute_default_duration=duration_seconds)
            await invalidate_security_cache(chat_id)
            msg = await _trans('mute_duration_set', lang, "✅")
            msg = _fmt(msg, duration=minutes)
            await safe_send(context.bot, user_id, msg)
        except (ValueError, AttributeError):
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"mute_duration: {e}", exc_info=True)
            msg = await _trans('execution_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_penalty_ban_duration(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = (context.user_data.get('sec_chat')
                   or context.user_data.get('security_chat_id'))
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            minutes = int((update.effective_message.text or "").strip())
            if minutes < 0 or minutes > 43200:
                raise ValueError
            duration_seconds = minutes * 60
            await DB.update_security_settings(
                chat_id, ban_default_duration=duration_seconds)
            await invalidate_security_cache(chat_id)
            msg = await _trans('ban_duration_set', lang, "✅")
            msg = _fmt(msg, duration=minutes)
            await safe_send(context.bot, user_id, msg)
        except (ValueError, AttributeError):
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"ban_duration: {e}", exc_info=True)
            msg = await _trans('execution_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_penalty_restrict_duration(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = (context.user_data.get('sec_chat')
                   or context.user_data.get('security_chat_id'))
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            minutes = int((update.effective_message.text or "").strip())
            if minutes < 0 or minutes > 43200:
                raise ValueError
            duration_seconds = minutes * 60
            await DB.update_security_settings(
                chat_id, restrict_default_duration=duration_seconds)
            await invalidate_security_cache(chat_id)
            msg = await _trans('restrict_duration_set', lang, "✅")
            msg = _fmt(msg, duration=minutes)
            await safe_send(context.bot, user_id, msg)
        except (ValueError, AttributeError):
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"restrict_duration: {e}", exc_info=True)
            msg = await _trans('execution_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    # =================================================================
    # رسائل المجموعات
    # =================================================================

    @staticmethod
    async def handle_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or not update.effective_message:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        message = update.effective_message

        try:
            limiter = await GroupRateLimiterManager.get(chat_id)
            await limiter.acquire()
        except Exception:
            pass

        msg_text = message.text or ""
        msg_caption = message.caption or ""
        full_text = (msg_text + " " + msg_caption).strip()

        METRICS.increment_messages()
        settings = await get_security_settings_cached(chat_id)

        if settings.get('delete_service'):
            if message.new_chat_members or message.left_chat_member:
                await _safe_delete_message(context.bot, chat_id, message.message_id)
                return

        if settings.get('delete_links'):
            if TextUtils.contains_link(full_text):
                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id, "link", settings)
                return

        if settings.get('mentions'):
            if TextUtils.contains_mention(full_text):
                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id, "mention", settings)
                return

        if settings.get('delete_banned_words'):
            banned_words = await get_banned_words_cached(chat_id)
            if banned_words:
                text_lower = full_text.lower()
                for word in banned_words:
                    if word in text_lower:
                        await MessageHandlers._delete_and_warn(
                            update, context, chat_id, user_id,
                            "banned_word", settings)
                        return

        max_len = settings.get('max_message_length', 0)
        if max_len > 0 and len(full_text) > max_len:
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id, "max_len", settings)
            return

        if getattr(message, 'forward_origin', None) and settings.get('delete_forwarded'):
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id, "forwarded", settings)
            return

        media_checks = [
            (message.video, 'delete_videos', 'video'),
            (message.audio, 'delete_audio', 'audio'),
            (message.voice, 'delete_voice', 'voice'),
            (message.animation, 'delete_animation', 'animation'),
            (message.document, 'delete_documents', 'document'),
            (message.sticker, 'delete_stickers', 'sticker'),
            (message.photo, 'delete_photos', 'photo'),
            (message.video_note, 'delete_video_note', 'video_note'),
        ]
        for media, setting_key, violation_type in media_checks:
            if media and settings.get(setting_key):
                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id, violation_type, settings)
                return

        if msg_text:
            try:
                translated = await _detect_and_translate(
                    update, context, chat_id, user_id, msg_text)
                if translated:
                    lang = await _ensure_lang(update, context)
                    await _send_translation_reply(
                        context.bot, chat_id, message.message_id,
                        translated, lang)
            except Exception:
                pass

        if msg_text:
            await MessageHandlers._process_auto_reply(
                update, context, chat_id, msg_text, user_id)

    @staticmethod
    def _get_penalty_duration(settings: dict, violation_type: str) -> int:
        if violation_type in ('flood', 'antiflood'):
            return settings.get('antiflood_penalty_duration', 3600)
        elif violation_type in ('night', 'night_mode'):
            return settings.get('night_mode_action_duration', 3600)
        elif violation_type in ('warn_penalty', 'warn'):
            return settings.get('warn_penalty_duration', 3600)
        return settings.get('auto_mute_duration', 3600)

    @staticmethod
    async def _get_violation_message(violation_type: str, lang: str) -> str:
        trans_key = f"violation_{violation_type}"
        default_messages = {
            'link': '🚫', 'mention': '🚫', 'banned_word': '🚫',
            'max_len': '📏', 'forwarded': '↩️', 'video': '🎬',
            'audio': '🎵', 'voice': '🎤', 'animation': '🎞️',
            'document': '📄', 'sticker': '🖼️', 'photo': '📷',
            'video_note': '🎥',
        }
        default = default_messages.get(violation_type, f'🚫 {violation_type}')
        return await _trans(trans_key, lang, default)

    @staticmethod
    async def _delete_and_warn(update, context, chat_id, user_id,
                                violation_type, settings):
        """
        ✅ v7.9.11: كلتا الرسالتين (⚠️ التحذير و 🚨 العقوبة)
                    تُحذفان تلقائياً بعد 10 ثواني.
        """
        lang = await _ensure_lang(update, context)

        # ═══ حذف رسالة المخالفة الأصلية ═══
        try:
            msg_obj = update.effective_message
            if msg_obj and msg_obj.message_id:
                await _safe_delete_message(context.bot, chat_id, msg_obj.message_id)
        except Exception as e:
            if not _is_delete_ignore_error(e):
                logger.warning(f"delete failed: {e}")

        # ═══ عدّاد المخالفات ═══
        try:
            violation_count = await DB.increment_violation_count(user_id, chat_id)
        except Exception:
            violation_count = 1

        # ═══ قراءة قاعدة العقوبة ═══
        penalty_rule = None
        try:
            penalty_rule = await DB.get_violation_penalty(chat_id, violation_type)
        except Exception:
            pass

        if penalty_rule:
            penalty_type = penalty_rule['penalty_type']
            if penalty_type == 'none':
                penalty_type = None
                duration_seconds = 0
            else:
                duration_seconds = penalty_rule['duration_seconds']
        else:
            penalty_type = settings.get('auto_penalty', 'none')
            if penalty_type == 'none':
                penalty_type = None
                duration_seconds = 0
            elif penalty_type not in ['mute', 'ban', 'restrict', 'kick', 'warn']:
                penalty_type = 'mute'
                duration_seconds = MessageHandlers._get_penalty_duration(
                    settings, violation_type)
            else:
                duration_seconds = MessageHandlers._get_penalty_duration(
                    settings, violation_type)

        try:
            await DB.add_admin_log(
                chat_id, context.bot.id, f"violation_{violation_type}", user_id)
        except Exception:
            pass

        violation_message = await MessageHandlers._get_violation_message(
            violation_type, lang)

        # ═══════════════════════════════════════════════════════════════
        # ⚠️ رسالة التحذير — تُحذف بعد 10 ثواني
        # ═══════════════════════════════════════════════════════════════
        try:
            user_name = escape(update.effective_user.first_name or "User")
            warn_title = await _trans('violation_warning_title', lang, "⚠️")
            count_label = await _trans('violation_count_label', lang, "📊")
            delete_notice = await _trans('violation_delete_notice', lang, "⏳")

            message_text = (
                f"{warn_title}\n{violation_message}\n"
                f"👤 {user_name}\n{count_label}: {violation_count}\n{delete_notice}"
            )
            sent_msg = await context.bot.send_message(
                chat_id, message_text, parse_mode='HTML')
            asyncio.create_task(_delete_after_delay(
                context.bot, chat_id, sent_msg.message_id,
                PENALTY_MESSAGE_DELETE_DELAY))
        except Exception as e:
            logger.warning(f"violation message: {e}")

        # ═══════════════════════════════════════════════════════════════
        # 🚨 رسالة العقوبة — تُحذف بعد 10 ثواني (v7.9.11)
        # ═══════════════════════════════════════════════════════════════
        if penalty_type:
            max_strikes = (settings.get('violation_strikes')
                           or settings.get('max_warnings') or 3)
            if violation_count >= max_strikes:
                success, msg = await apply_violation_penalty(
                    update, context, chat_id, user_id,
                    violation_type, penalty_type, duration_seconds,
                    lang=lang)
                if success:
                    try:
                        msg_prefix = await _trans(
                            'violation_penalty_applied', lang, "🚨 {msg}")
                        sent_penalty = await safe_send(
                            context.bot, chat_id,
                            _fmt(msg_prefix, msg=msg),
                            parse_mode='HTML')
                        # ✅ v7.9.11: حذف تلقائي بعد 10 ثواني
                        if sent_penalty is not None and getattr(
                                sent_penalty, 'message_id', None):
                            asyncio.create_task(_delete_after_delay(
                                context.bot, chat_id,
                                sent_penalty.message_id,
                                PENALTY_MESSAGE_DELETE_DELAY))
                        await DB.reset_violation_count(user_id, chat_id)
                    except Exception as e:
                        logger.debug(f"penalty send/delete: {e}")

    @staticmethod
    async def _process_auto_reply(update, context, chat_id, text, user_id=None):
        try:
            ars = await get_auto_reply_settings_cached(chat_id)
            if not ars.get('enabled', False):
                return False
            if ars.get('ignore_bots', True) and update.effective_user.is_bot:
                return False
            if ars.get('only_admins', False):
                if not await is_authorized_in_group(
                    context.bot, chat_id, user_id or update.effective_user.id):
                    return False

            reply = await DB.get_auto_reply(text, chat_id)
            if reply:
                reply_text = reply.get('reply', '') or ''
                reply_type = reply.get('reply_type', 'text') or 'text'
                media_id = reply.get('reply_media_id')

                if reply_type in _MEDIA_REPLY_TYPES:
                    if not media_id:
                        if reply_text:
                            await safe_send(context.bot, chat_id, reply_text)
                    else:
                        try:
                            if reply_type == 'voice':
                                await safe_send(context.bot, chat_id,
                                                reply_text or "", voice=media_id)
                            elif reply_type == 'sticker':
                                await safe_send(context.bot, chat_id,
                                                reply_text or "", sticker=media_id)
                            elif reply_type == 'video_note':
                                await safe_send(context.bot, chat_id,
                                                reply_text or "", video_note=media_id)
                            else:
                                await safe_send(
                                    context.bot, chat_id, reply_text,
                                    **{reply_type: media_id})
                        except Exception:
                            if reply_text:
                                await safe_send(context.bot, chat_id, reply_text)
                else:
                    if reply_text:
                        await safe_send(context.bot, chat_id, reply_text)

                await _increment_usage_async(chat_id, text)
                return True

            file_reply = get_reply_from_file(text)
            if file_reply:
                await safe_send(context.bot, chat_id, file_reply)
                return True
            return False
        except Exception as e:
            logger.error(f"❌ auto_reply: {e}")
            return False

    # =================================================================
    # إضافة القناة
    # =================================================================

    @staticmethod
    async def _handle_channel_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        text = (update.effective_message.text or "").strip()

        if user_id != CONFIG.PRIMARY_OWNER_ID:
            if not await DB.has_active_subscription(user_id):
                msg = await _trans('subscription_required', lang, "❌")
                await safe_send(context.bot, user_id, msg, parse_mode='HTML')
                StateManager.clear(user_id)
                return

        try:
            chat_obj = None
            channel_id = None

            if text.lstrip('-').isdigit():
                channel_id = int(text)
                try:
                    chat_obj = await context.bot.get_chat(channel_id)
                except Exception:
                    chat_obj = None
            else:
                try:
                    chat_obj = await context.bot.get_chat(text)
                    channel_id = chat_obj.id
                except Exception:
                    msg = await _trans('channel_not_found', lang, "❌")
                    await safe_send(context.bot, user_id, msg)
                    StateManager.clear(user_id)
                    return

            if chat_obj:
                channel_name = chat_obj.title or chat_obj.username or f"Channel {channel_id}"
            else:
                channel_name = f"Channel {channel_id}"

            try:
                bot_member = await context.bot.get_chat_member(
                    channel_id, context.bot.id)
                if bot_member.status not in ['administrator', 'creator']:
                    msg = await _trans('bot_not_admin', lang, "❌")
                    await safe_send(context.bot, user_id, msg)
                    StateManager.clear(user_id)
                    return
            except BadRequest:
                msg = await _trans('verify_failed', lang, "❌")
                await safe_send(context.bot, user_id, msg)
                StateManager.clear(user_id)
                return
            except Exception:
                msg = await _trans('verify_error', lang, "❌")
                await safe_send(context.bot, user_id, msg)
                StateManager.clear(user_id)
                return

            if user_id != CONFIG.PRIMARY_OWNER_ID:
                try:
                    user_member = await context.bot.get_chat_member(channel_id, user_id)
                    if user_member.status not in ['creator', 'administrator']:
                        msg = await _trans('must_be_admin', lang, "❌")
                        await safe_send(context.bot, user_id, msg)
                        StateManager.clear(user_id)
                        return
                except Exception:
                    msg = await _trans('user_verify_failed', lang, "❌")
                    await safe_send(context.bot, user_id, msg)
                    StateManager.clear(user_id)
                    return

            ch_db_id = await DB.add_channel(user_id, channel_id, channel_name)
            if ch_db_id:
                await _invalidate_after_channel_change(user_id, ch_db_id)
                msg = _fmt(await _trans('channel_added', lang, "✅ {channel_name}"),
                           channel_name=escape(channel_name))
                await safe_send(context.bot, user_id, msg)
            else:
                msg = await _trans('channel_add_failed', lang, "❌")
                await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.exception("channel add error")
            await safe_send(context.bot, user_id, f"❌ {escape(str(e)[:100])}")
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_adding_posts(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        channel_db_id = await DB.get_active_channel(user_id)

        if not channel_db_id:
            StateManager.clear(user_id)
            msg = await _trans('no_active_channel', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            return

        msg = update.effective_message
        if not msg:
            return

        media_type = 'text'
        media_file_id = ''
        text = msg.text or msg.caption or ""

        if msg.photo:
            media_type = 'photo'
            media_file_id = msg.photo[-1].file_id
            text = msg.caption or ""
        elif msg.video:
            media_type = 'video'
            media_file_id = msg.video.file_id
            text = msg.caption or ""
        elif msg.document:
            media_type = 'document'
            media_file_id = msg.document.file_id
            text = msg.caption or ""
        elif msg.audio:
            media_type = 'audio'
            media_file_id = msg.audio.file_id
            text = msg.caption or ""
        elif msg.voice:
            media_type = 'voice'
            media_file_id = msg.voice.file_id
        elif msg.animation:
            media_type = 'animation'
            media_file_id = msg.animation.file_id
            text = msg.caption or ""
        elif msg.sticker:
            media_type = 'sticker'
            media_file_id = msg.sticker.file_id
        elif msg.video_note:
            media_type = 'video_note'
            media_file_id = msg.video_note.file_id

        if not text and not media_file_id:
            msg = await _trans('empty_message', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            return

        posts = [(text, media_type, media_file_id)]
        try:
            count = await DB.add_posts(user_id, channel_db_id, posts)
        except Exception as e:
            logger.error(f"❌ add_posts: {e}", exc_info=True)
            await safe_send(context.bot, user_id, f"❌ {str(e)[:80]}")
            return

        if count > 0:
            await _invalidate_after_channel_change(user_id, channel_db_id)
            msg = await _trans('post_added', lang, "✅")
            await safe_send(context.bot, user_id, msg)
        else:
            msg = await _trans('post_add_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)

    # =================================================================
    # الدعم
    # =================================================================

    @staticmethod
    async def _handle_support_message(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        content = (update.effective_message.text or "")[:MAX_SUPPORT_MESSAGE_LENGTH]
        username = update.effective_user.username or ""

        try:
            ticket_number = await DB.create_ticket(user_id, username, content)
        except Exception as e:
            logger.error(f"❌ create_ticket: {e}", exc_info=True)
            ticket_number = None

        StateManager.clear(user_id)

        if not ticket_number:
            msg = await _trans('ticket_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            return

        msg = _fmt(await _trans('ticket_received', lang, "✅ {ticket_number}"),
                   ticket_number=ticket_number)
        await safe_send(context.bot, user_id, msg)

    # =================================================================
    # البث
    # =================================================================

    @staticmethod
    async def _handle_broadcast_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return

        content = (update.effective_message.text or "")[:MAX_BROADCAST_MESSAGE_LENGTH]
        if not content:
            msg = await _trans('empty_message', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return

        sent_count = failed_count = skipped_count = processed = 0

        try:
            iterator = None
            if hasattr(DB, 'iter_all_users'):
                iterator = DB.iter_all_users(batch_size=500)
            else:
                users = await DB.get_all_users(limit=MAX_ADMIN_BROADCAST_TARGETS)
                iterator = iter(users)

            if hasattr(iterator, '__aiter__'):
                async for user in iterator:
                    if processed >= MAX_ADMIN_BROADCAST_TARGETS:
                        break
                    processed += 1
                    if not isinstance(user, dict):
                        skipped_count += 1
                        continue
                    target_id = user.get('user_id')
                    banned = user.get('banned', 0)
                    if not target_id or banned:
                        skipped_count += 1
                        continue
                    try:
                        result = await safe_send(context.bot, target_id, content)
                        if result is not None:
                            sent_count += 1
                        else:
                            failed_count += 1
                        await asyncio.sleep(BROADCAST_DELAY_SECONDS)
                    except Exception:
                        failed_count += 1
            else:
                for user in iterator:
                    if processed >= MAX_ADMIN_BROADCAST_TARGETS:
                        break
                    processed += 1
                    if not isinstance(user, dict):
                        skipped_count += 1
                        continue
                    target_id = user.get('user_id')
                    banned = user.get('banned', 0)
                    if not target_id or banned:
                        skipped_count += 1
                        continue
                    try:
                        result = await safe_send(context.bot, target_id, content)
                        if result is not None:
                            sent_count += 1
                        else:
                            failed_count += 1
                        await asyncio.sleep(BROADCAST_DELAY_SECONDS)
                    except Exception:
                        failed_count += 1
        except Exception as e:
            logger.error(f"broadcast: {e}", exc_info=True)
            msg = await _trans('broadcast_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return

        msg = _fmt(await _trans('broadcast_success', lang,
                                 "✅ {sent} ❌ {failed} ⏭️ {skipped}"),
                   sent=sent_count, failed=failed_count, skipped=skipped_count)
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    # =================================================================
    # تحديثات وإعدادات
    # =================================================================

    @staticmethod
    async def _handle_update_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return
        content = (update.effective_message.text or "")[:MAX_BROADCAST_MESSAGE_LENGTH]
        update_ch = await DB.get_updates_channel()
        if update_ch:
            try:
                await safe_send(context.bot, update_ch, content)
                msg = await _trans('update_sent', lang, "✅")
                await safe_send(context.bot, user_id, msg)
            except Exception:
                msg = await _trans('send_failed', lang, "❌")
                await safe_send(context.bot, user_id, msg)
        else:
            msg = await _trans('no_update_channel', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    # ═════════════════════════════════════════════════════════════════
    # ✅ v7.9.10: _handle_update_ch_input — يحفظ فقط في settings
    # ═════════════════════════════════════════════════════════════════
    @staticmethod
    async def _handle_update_ch_input(update, context):
        """
        ✅ v7.9.10: يحفظ في settings.updates_channel فقط.
        """
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return

        text = (update.effective_message.text or "").strip()

        # ═══════ حذف القناة ═══════
        if not text or text.lower() in ('none', 'cancel', 'remove', '-'):
            try:
                ok = await DB.set_setting('updates_channel', '')
            except Exception as e:
                logger.error(f"❌ clear updates_channel: {e}", exc_info=True)
                ok = False
            if ok:
                msg = await _trans('log_channel_removed_success', lang, "🗑️")
            else:
                msg = await _trans('save_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return

        # ═══════ تحقق من الصيغة ═══════
        if not _is_valid_channel_ref(text):
            preview = text[:50]
            logger.warning(
                f"⚠️ v7.9.10: رفض updates_channel غير صالح "
                f"من {user_id}: {preview!r}"
            )
            msg = await _trans(
                'invalid_channel_ref', lang,
                "❌ <b>قيمة غير صالحة</b>\n\n"
                "أرسل:\n"
                "• معرّف رقمي: <code>-1001234567890</code>\n"
                "• أو @username\n"
                "• أو رابط: <code>https://t.me/username</code>\n\n"
                "أو أرسل <code>none</code> للإزالة."
            )
            await safe_send(context.bot, user_id, msg, parse_mode='HTML')
            return

        # ═══════ حفظ في settings.updates_channel فقط ═══════
        try:
            ok = await DB.set_setting('updates_channel', text)
        except Exception as e:
            logger.error(f"❌ set updates_channel: {e}", exc_info=True)
            ok = False

        if ok:
            msg = _fmt(await _trans('set_success', lang, "✅ {text}"),
                       text=escape(text))
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
        else:
            msg = await _trans('save_failed', lang, "❌ فشل الحفظ")
            await safe_send(context.bot, user_id, msg)

    @staticmethod
    async def _handle_force_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return
        text = (update.effective_message.text or "").strip()
        if text.lower() == 'none':
            await DB.set_setting('force_subscribe_channel', '')
            msg = await _trans('force_disabled', lang, "✅")
            await safe_send(context.bot, user_id, msg)
        else:
            try:
                chat = await context.bot.get_chat(text)
                chat_id = chat.id
                try:
                    bot_member = await context.bot.get_chat_member(
                        chat_id, context.bot.id)
                    if bot_member.status not in ['administrator', 'creator']:
                        msg = await _trans('bot_not_admin_force', lang, "❌")
                        await safe_send(context.bot, user_id, msg)
                        StateManager.clear(user_id)
                        return
                except Exception:
                    msg = await _trans('bot_not_in_force_channel', lang, "❌")
                    await safe_send(context.bot, user_id, msg)
                    StateManager.clear(user_id)
                    return
                await DB.set_setting('force_subscribe_channel', str(chat_id))
                msg = _fmt(await _trans('force_enabled', lang,
                                         "✅ {channel_name}"),
                           channel_name=escape(chat.title or text))
                await safe_send(context.bot, user_id, msg)
            except Exception:
                msg = await _trans('invalid_channel', lang, "❌")
                await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    # =================================================================
    # log channel input
    # =================================================================

    @staticmethod
    async def _handle_log_ch_input(update, context):
        """يتحقق من صحة الإدخال قبل الحفظ."""
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return

        if context.user_data.get('log_group_id'):
            await MessageHandlers.handle_log_group_input(update, context)
            return

        text = (update.effective_message.text or "").strip()

        if not _is_valid_channel_ref(text):
            preview = text[:50] if text else ""
            logger.warning(
                f"⚠️ v7.9.1: رفض log_channel_id غير صالح "
                f"من المستخدم {user_id} | القيمة: {preview!r}"
            )
            msg = await _trans(
                'invalid_channel_ref', lang,
                "❌ <b>قيمة غير صالحة</b>\n\n"
                "أرسل:\n"
                "• معرّف رقمي مثل: <code>-1001234567890</code>\n"
                "• أو @username\n"
                "• أو رابط: <code>https://t.me/username</code>\n\n"
                "أو أرسل <code>none</code> للإلغاء."
            )
            await safe_send(context.bot, user_id, msg, parse_mode='HTML')
            return

        try:
            ok = await DB.set_setting('log_channel_id', text)
        except Exception as e:
            logger.error(f"❌ set log_channel failed: {e}", exc_info=True)
            ok = False

        if not ok:
            msg = await _trans(
                'save_failed', lang,
                "❌ فشل الحفظ. تأكد من صحة المعرّف."
            )
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return

        if text:
            msg = _fmt(await _trans('set_success', lang, "✅ {text}"),
                       text=escape(text))
        else:
            msg = await _trans(
                'log_channel_removed_success', lang,
                "🗑️ تمت إزالة قناة السجل"
            )
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    # =================================================================
    # المشرفين — 🆕 v7.9.12: +refresh_admin_commands
    # =================================================================

    @staticmethod
    async def _handle_admin_add_input(update, context):
        """
        🆕 v7.9.12: بعد نجاح DB.add_admin، يُحدَّث scope أوامر الأدمن فوراً.
        """
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return
        text = (update.effective_message.text or "").strip()
        try:
            admin_id = int(text)
            if admin_id <= 0:
                raise ValueError
            user_exists = await DB.fetchval(
                "SELECT 1 FROM users WHERE user_id = ?", (admin_id,))
            if not user_exists:
                msg = await _trans('user_not_found', lang, "⚠️")
                await safe_send(context.bot, user_id, msg)
            success = await DB.add_admin(admin_id, user_id)
            if success:
                # 🆕 v7.9.12: تحديث scope أوامر الأدمن فوراً
                await _refresh_admin_commands_safe(
                    context.bot, admin_id, is_admin=True
                )
                msg = await _trans('added_success', lang, "✅")
                await safe_send(context.bot, user_id, msg)
            else:
                admins = await DB.get_admin_list()
                if any(a['user_id'] == admin_id for a in admins):
                    msg = await _trans('already_admin', lang, "ℹ️")
                    await safe_send(context.bot, user_id, msg)
                else:
                    msg = await _trans('add_failed', lang, "❌")
                    await safe_send(context.bot, user_id, msg)
        except ValueError:
            msg = await _trans('invalid_id', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        except Exception:
            msg = await _trans('error_occurred', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_admin_rem_input(update, context):
        """
        🆕 v7.9.12: بعد نجاح DB.remove_admin، يُعاد scope المستخدم للعام فقط.
        """
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return
        text = (update.effective_message.text or "").strip()
        try:
            admin_id = int(text)
            if admin_id <= 0:
                raise ValueError
            success = await DB.remove_admin(admin_id)
            if success:
                # 🆕 v7.9.12: إعادة scope المستخدم للعام
                await _refresh_admin_commands_safe(
                    context.bot, admin_id, is_admin=False
                )
                msg = await _trans('removed_success', lang, "✅")
                await safe_send(context.bot, user_id, msg)
            else:
                msg = await _trans('not_admin', lang, "ℹ️")
                await safe_send(context.bot, user_id, msg)
        except ValueError:
            msg = await _trans('invalid_id', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        except Exception:
            msg = await _trans('error_occurred', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    # =================================================================
    # الردود التلقائية
    # =================================================================

    @staticmethod
    async def _handle_keyword_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        keyword = (update.effective_message.text or "").strip().lower()
        context.user_data['auto_keyword'] = keyword
        context.user_data['auto_chat'] = -1
        StateManager.set(user_id, UserState.WAIT_REPLY)
        msg = await _trans('send_reply_prompt', lang, "📝")
        await safe_send(context.bot, user_id,
                        f"✅ {escape(keyword)}\n{msg}")

    @staticmethod
    async def _save_auto_reply_from_message(update, context, user_id, lang,
                                             chat_id, keyword):
        if not keyword:
            msg = await _trans('empty_keyword', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            return False
        msg = update.effective_message
        reply_text = msg.text or msg.caption or ""
        media_type = 'text'
        media_file_id = None

        if msg.photo:
            media_type, media_file_id = 'photo', msg.photo[-1].file_id
        elif msg.video:
            media_type, media_file_id = 'video', msg.video.file_id
        elif msg.document:
            media_type, media_file_id = 'document', msg.document.file_id
        elif msg.audio:
            media_type, media_file_id = 'audio', msg.audio.file_id
        elif msg.voice:
            media_type, media_file_id = 'voice', msg.voice.file_id
        elif msg.animation:
            media_type, media_file_id = 'animation', msg.animation.file_id
        elif msg.sticker:
            media_type, media_file_id = 'sticker', msg.sticker.file_id
        elif msg.video_note:
            media_type, media_file_id = 'video_note', msg.video_note.file_id

        try:
            await DB.add_auto_reply(chat_id, keyword, reply_text,
                                    reply_type=media_type,
                                    media_id=media_file_id)
            await invalidate_auto_reply_cache(chat_id)
            msg = await _trans('added_success', lang, "✅")
            await safe_send(context.bot, user_id, msg)
            return True
        except Exception:
            msg = await _trans('add_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            return False

    @staticmethod
    async def _handle_reply_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        keyword = context.user_data.get('auto_keyword', '')
        if not keyword:
            msg = await _trans('empty_keyword', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        chat_id = context.user_data.get('auto_chat', -1)
        await MessageHandlers._save_auto_reply_from_message(
            update, context, user_id, lang, chat_id, keyword)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_auto_key(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        keyword = (update.effective_message.text or "").strip().lower()
        context.user_data['auto_keyword'] = keyword
        if 'auto_chat' not in context.user_data:
            context.user_data['auto_chat'] = -1
        StateManager.set(user_id, UserState.WAIT_AUTO_REPLY)
        msg = await _trans('send_reply_prompt', lang, "📝")
        await safe_send(context.bot, user_id,
                        f"✅ {escape(keyword)}\n{msg}")

    @staticmethod
    async def _handle_auto_reply_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('auto_chat', -1)
        keyword = context.user_data.get('auto_keyword', '')
        if not keyword:
            msg = await _trans('empty_keyword', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        await MessageHandlers._save_auto_reply_from_message(
            update, context, user_id, lang, chat_id, keyword)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_auto_del(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('auto_chat', -1)
        keyword = (update.effective_message.text or "").strip().lower()
        await DB.remove_auto_reply(chat_id, keyword)
        await invalidate_auto_reply_cache(chat_id)
        msg = await _trans('deleted_success', lang, "✅")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    # =================================================================
    # الكلمات المحظورة
    # =================================================================

    @staticmethod
    async def _handle_global_ban_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        word = (update.effective_message.text or "").strip().lower()
        success, duplicate = await DB.add_banned_word(word, -1, user_id)
        if success:
            invalidate_banned_words_cache(-1)
            msg = _fmt(await _trans('word_added', lang, "✅ {word}"),
                       word=escape(word))
            await safe_send(context.bot, user_id, msg)
        elif duplicate:
            msg = await _trans('word_exists', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        else:
            msg = await _trans('add_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_rem_global_ban_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        word = (update.effective_message.text or "").strip().lower()
        await DB.remove_banned_word(word, -1)
        invalidate_banned_words_cache(-1)
        msg = await _trans('removed_success', lang, "✅")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_group_ban_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('ban_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        word = (update.effective_message.text or "").strip().lower()
        success, duplicate = await DB.add_banned_word(word, chat_id, user_id)
        if success:
            invalidate_banned_words_cache(chat_id)
            msg = _fmt(await _trans('word_added', lang, "✅ {word}"),
                       word=escape(word))
            await safe_send(context.bot, user_id, msg)
        elif duplicate:
            msg = await _trans('word_exists', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        else:
            msg = await _trans('add_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_rem_group_ban_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('ban_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        word = (update.effective_message.text or "").strip().lower()
        await DB.remove_banned_word(word, chat_id)
        invalidate_banned_words_cache(chat_id)
        msg = await _trans('removed_success', lang, "✅")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    # =================================================================
    # المسابقات
    # =================================================================

    @staticmethod
    async def _handle_contest_title(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        context.user_data['contest_title'] = update.effective_message.text or ""
        StateManager.set(user_id, UserState.WAIT_CONTEST_DESC)
        msg = await _trans('send_description_prompt', lang, "📝")
        await safe_send(context.bot, user_id, msg)

    @staticmethod
    async def _handle_contest_desc(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        context.user_data['contest_desc'] = update.effective_message.text or ""
        StateManager.set(user_id, UserState.WAIT_CONTEST_PRIZE)
        msg = await _trans('send_prize_prompt', lang, "🎁")
        await safe_send(context.bot, user_id, msg)

    @staticmethod
    async def _handle_contest_prize(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        context.user_data['contest_prize'] = update.effective_message.text or ""
        StateManager.set(user_id, UserState.WAIT_CONTEST_DATE)
        msg = await _trans('send_date_prompt', lang, "📅")
        await safe_send(context.bot, user_id, msg)

    @staticmethod
    async def _handle_contest_date(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        title = context.user_data.get('contest_title', '')
        desc = context.user_data.get('contest_desc', '')
        prize = context.user_data.get('contest_prize', '')
        date = update.effective_message.text or ""
        parsed = _parse_contest_date(date)
        if not parsed:
            msg = await _trans('invalid_date', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        contest_id = await DB.create_contest(user_id, title, desc, prize, date)
        if contest_id:
            await safe_send(context.bot, user_id, f"✅ #{contest_id}")
        else:
            msg = await _trans('execution_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_contest_answer(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        contest_id = context.user_data.get('contest_join')
        answer = (update.effective_message.text or "")[:2000]
        if contest_id:
            joined = await DB.join_contest(contest_id, user_id, answer)
            if joined:
                await safe_send(context.bot, user_id,
                                await _trans('added_success', lang, "✅"))
            else:
                await safe_send(context.bot, user_id,
                                await _trans('execution_failed', lang, "❌"))
        else:
            await safe_send(context.bot, user_id,
                            await _trans('no_active_contest', lang, "❌"))
        StateManager.clear(user_id)

    # =================================================================
    # الاستيراد
    # =================================================================

    @staticmethod
    async def _handle_import_file(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        doc = update.effective_message.document
        if not doc:
            msg = await _trans('send_json', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if doc.file_size and doc.file_size > MAX_IMPORT_FILE_SIZE:
            msg = _fmt(await _trans('file_too_large', lang, "❌ {max_size}"),
                       max_size=MAX_IMPORT_FILE_SIZE // 1024)
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            file = await doc.get_file()
            file_path = await file.download_to_drive()
            count = await import_auto_replies(-1, str(file_path))
            try:
                os.remove(file_path)
            except OSError:
                pass
            msg = _fmt(await _trans('import_success', lang, "✅ {count}"),
                       count=count)
            await safe_send(context.bot, user_id, msg)
        except Exception:
            await safe_send(context.bot, user_id,
                            await _trans('error_occurred', lang, "❌"))
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_github_url(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        url = (update.effective_message.text or "").strip()
        if not _is_safe_url(url):
            msg = await _trans('invalid_url', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        tmp_path = None
        try:
            data = await fetch_json_from_url(url)
            if not data:
                msg = await _trans('fetch_failed', lang, "❌")
                await safe_send(context.bot, user_id, msg)
                StateManager.clear(user_id)
                return
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.json', delete=False, encoding='utf-8') as tmp:
                json.dump(data, tmp, ensure_ascii=False)
                tmp_path = tmp.name
            count = await import_auto_replies(-1, tmp_path)
            msg = _fmt(await _trans('import_success', lang, "✅ {count}"),
                       count=count)
            await safe_send(context.bot, user_id, msg)
        except Exception as e:
            logger.error(f"github import: {e}")
            msg = await _trans('grant_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        StateManager.clear(user_id)

    # =================================================================
    # منح اشتراك
    # =================================================================

    @staticmethod
    async def _handle_grant_free(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return
        parts = (update.effective_message.text or "").strip().split()
        if len(parts) >= 2:
            try:
                target_id = int(parts[0])
                days = int(parts[1])
                if target_id <= 0 or days <= 0:
                    raise ValueError
                await DB.grant_subscription_days(target_id, days)
                msg = await _trans('grant_success', lang, "✅")
                await safe_send(context.bot, user_id, msg)
            except ValueError:
                msg = await _trans('invalid_format', lang, "❌")
                await safe_send(context.bot, user_id, msg)
            except Exception:
                msg = await _trans('grant_failed', lang, "❌")
                await safe_send(context.bot, user_id, msg)
        else:
            msg = await _trans('usage_format', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    # =================================================================
    # الجدولة
    # =================================================================

    @staticmethod
    async def _handle_min_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        ch_id = context.user_data.get('schedule_ch')
        if not ch_id:
            msg = await _trans('channel_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            minutes = int(update.effective_message.text or "0")
            if minutes > 0:
                await DB.update_schedule(ch_id, interval_minutes=minutes,
                                         schedule_type='interval_minutes')
                await safe_send(context.bot, user_id, f"✅ {minutes}")
            else:
                await safe_send(context.bot, user_id,
                                await _trans('invalid_number', lang, "❌"))
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_hour_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        ch_id = context.user_data.get('schedule_ch')
        if not ch_id:
            msg = await _trans('channel_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            hours = int(update.effective_message.text or "0")
            if hours > 0:
                await DB.update_schedule(ch_id, interval_hours=hours,
                                         schedule_type='interval_hours')
                await safe_send(context.bot, user_id, f"✅ {hours}")
            else:
                await safe_send(context.bot, user_id,
                                await _trans('invalid_number', lang, "❌"))
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_day_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        ch_id = context.user_data.get('schedule_ch')
        if not ch_id:
            msg = await _trans('channel_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            days = int(update.effective_message.text or "0")
            if days > 0:
                await DB.update_schedule(ch_id, interval_days=days,
                                         schedule_type='interval_days')
                await safe_send(context.bot, user_id, f"✅ {days}")
            else:
                await safe_send(context.bot, user_id,
                                await _trans('invalid_number', lang, "❌"))
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_pub_time_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        ch_id = context.user_data.get('schedule_ch')
        if not ch_id:
            msg = await _trans('channel_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        time_val = (update.effective_message.text or "").strip()
        if not re.match(r'^\d{1,2}:\d{2}$', time_val):
            msg = _fmt(await _trans('invalid_time_format', lang, "❌ {time}"),
                       time="HH:MM")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        await DB.update_schedule(ch_id, publish_time=time_val)
        await safe_send(context.bot, user_id, f"✅ {time_val}")
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_rem_days_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        try:
            days = int(update.effective_message.text or "3")
            if 1 <= days <= 30:
                await DB.update_reminder_settings(
                    user_id, reminder_days_before=days)
                await safe_send(context.bot, user_id, f"✅ {days}")
            else:
                msg = await _trans('range_1_30', lang, "❌")
                await safe_send(context.bot, user_id, msg)
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    # =================================================================
    # إعدادات الأمان
    # =================================================================

    @staticmethod
    async def _handle_max_len_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            max_len = int(update.effective_message.text or "0")
            if max_len < 0:
                raise ValueError
            await DB.update_security_settings(chat_id, max_message_length=max_len)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ {max_len}")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_warn_count_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            count = int(update.effective_message.text or "3")
            if count <= 0 or count > MAX_VIOLATION_STRIKES:
                raise ValueError
            await DB.update_security_settings(
                chat_id, max_warnings=count, violation_strikes=count)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ {count}")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_welcome_text_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        text = update.effective_message.text or ""
        await DB.update_security_settings(chat_id, welcome_text=text)
        await invalidate_security_cache(chat_id)
        msg = await _trans('saved_success', lang, "✅")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_goodbye_text_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        text = update.effective_message.text or ""
        await DB.update_security_settings(chat_id, goodbye_text=text)
        await invalidate_security_cache(chat_id)
        msg = await _trans('saved_success', lang, "✅")
        await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_slow_mode_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            seconds = int(update.effective_message.text or "0")
            if seconds < 0:
                raise ValueError
            await DB.update_security_settings(chat_id, slow_mode_seconds=seconds)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ {seconds}")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_antiflood_messages_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            count = int(update.effective_message.text or "5")
            if count <= 0:
                raise ValueError
            await DB.update_security_settings(chat_id, antiflood_messages=count)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ {count}")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_antiflood_seconds_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            seconds = int(update.effective_message.text or "10")
            if seconds <= 0:
                raise ValueError
            await DB.update_security_settings(chat_id, antiflood_seconds=seconds)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ {seconds}")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_night_start_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        time_val = (update.effective_message.text or "").strip()
        if not re.match(r'^\d{1,2}:\d{2}$', time_val):
            msg = _fmt(await _trans('invalid_time_format', lang, "❌ {time}"),
                       time="HH:MM")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        await DB.update_security_settings(chat_id, night_mode_start=time_val)
        await invalidate_security_cache(chat_id)
        await safe_send(context.bot, user_id, f"✅ {time_val}")
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_night_end_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        time_val = (update.effective_message.text or "").strip()
        if not re.match(r'^\d{1,2}:\d{2}$', time_val):
            msg = _fmt(await _trans('invalid_time_format', lang, "❌ {time}"),
                       time="HH:MM")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        await DB.update_security_settings(chat_id, night_mode_end=time_val)
        await invalidate_security_cache(chat_id)
        await safe_send(context.bot, user_id, f"✅ {time_val}")
        StateManager.clear(user_id)

    # =================================================================
    # العقوبات
    # =================================================================

    @staticmethod
    async def _handle_ban_input(update, context):
        await MessageHandlers._handle_penalty_input(
            update, context, 'ban', needs_duration=True)

    @staticmethod
    async def _handle_mute_input(update, context):
        await MessageHandlers._handle_penalty_input(
            update, context, 'mute', needs_duration=True)

    @staticmethod
    async def _handle_warn_input(update, context):
        await MessageHandlers._handle_penalty_input(
            update, context, 'warn', needs_duration=False)

    @staticmethod
    async def _handle_kick_input(update, context):
        await MessageHandlers._handle_penalty_input(
            update, context, 'kick', needs_duration=False)

    @staticmethod
    async def _handle_restrict_input(update, context):
        await MessageHandlers._handle_penalty_input(
            update, context, 'restrict', needs_duration=True)

    @staticmethod
    async def _handle_unban_input(update, context):
        await MessageHandlers._handle_penalty_input(
            update, context, 'unban', needs_duration=False)

    @staticmethod
    async def _handle_penalty_input(update, context, action, needs_duration):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('adv_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if not await _check_admin_in_chat(context, chat_id, user_id):
            msg = await _trans('not_admin_in_group', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return

        parts = (update.effective_message.text or "").strip().split()
        if not parts:
            msg = await _trans('send_user_id', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            target = int(parts[0])
            if target <= 0:
                raise ValueError("target out of range")

            duration = 0
            if needs_duration and len(parts) > 1:
                try:
                    duration = int(parts[1]) * 60
                except (ValueError, TypeError):
                    msg = await _trans('invalid_number', lang, "❌")
                    await safe_send(context.bot, user_id, msg)
                    StateManager.clear(user_id)
                    return
            if duration < 0:
                raise ValueError("negative duration")

            success, msg = await apply_penalty(
                context.bot, chat_id, target, action, duration, "", user_id)
            await safe_send(context.bot, user_id, msg if success else f"❌ {msg}")
        except ValueError:
            msg = await _trans('invalid_format', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        except Exception:
            msg = await _trans('execution_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_pin_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('adv_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if not await _check_admin_in_chat(context, chat_id, user_id):
            msg = await _trans('not_admin_in_group', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if update.effective_message.reply_to_message:
            try:
                await context.bot.pin_chat_message(
                    chat_id, update.effective_message.reply_to_message.message_id)
                msg = await _trans('pinned_full', lang, "📌")
                await safe_send(context.bot, user_id, msg)
            except Exception:
                msg = await _trans('pin_failed', lang, "❌")
                await safe_send(context.bot, user_id, msg)
        else:
            msg = await _trans('reply_to_pin', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    # =================================================================
    # معالجات إضافية
    # =================================================================

    @staticmethod
    async def _handle_penalty_duration_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = (context.user_data.get('adv_chat')
                   or context.user_data.get('sec_chat'))
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            minutes = int(update.effective_message.text or "1")
            if minutes <= 0:
                raise ValueError
            duration_seconds = minutes * 60
            await DB.update_security_settings(
                chat_id, violation_duration=duration_seconds)
            await invalidate_security_cache(chat_id)
            msg = _fmt(await _trans('duration_set', lang, "✅ {duration}"),
                       duration=minutes)
            await safe_send(context.bot, user_id, msg)
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        except Exception:
            msg = await _trans('execution_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_violation_strikes_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            strikes = int(update.effective_message.text or "3")
            if strikes <= 0 or strikes > MAX_VIOLATION_STRIKES:
                raise ValueError
            await DB.update_security_settings(chat_id, violation_strikes=strikes)
            await invalidate_security_cache(chat_id)
            await safe_send(context.bot, user_id, f"✅ {strikes}")
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        except Exception:
            msg = await _trans('execution_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_violation_duration_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        chat_id = context.user_data.get('sec_chat')
        if not chat_id:
            msg = await _trans('group_not_specified', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            minutes = int(update.effective_message.text or "1")
            if minutes <= 0:
                raise ValueError
            duration_seconds = minutes * 60
            await DB.update_security_settings(
                chat_id, violation_duration=duration_seconds)
            await invalidate_security_cache(chat_id)
            msg = _fmt(await _trans('duration_set', lang, "✅ {duration}"),
                       duration=minutes)
            await safe_send(context.bot, user_id, msg)
        except ValueError:
            msg = await _trans('invalid_number', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        except Exception:
            msg = await _trans('execution_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_redeem_gift_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        code = (update.effective_message.text or "").strip()[:MAX_GIFT_CODE_LENGTH]
        if not code:
            msg = await _trans('send_code_empty', lang, "❌ أرسل الكود")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        try:
            result = await DB.redeem_gift_code(user_id, code)
        except Exception:
            msg = await _trans('execution_failed', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        if isinstance(result, tuple):
            success, days = result
        elif isinstance(result, bool):
            success, days = result, 0
        else:
            success, days = bool(result), 0
        if success and days > 0:
            msg = _fmt(await _trans('gift_redeemed', lang, "🎁 {days}"),
                       days=days)
            await safe_send(context.bot, user_id, msg)
        elif days == -1:
            msg = await _trans('own_code', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        else:
            msg = await _trans('invalid_code', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        StateManager.clear(user_id)

    # =================================================================
    # استعادة قاعدة البيانات
    # =================================================================

    @staticmethod
    async def _do_db_restore(update, context, user_id, lang):
        if await _is_postgres_db():
            msg = await _trans('restore_postgres_unsupported', lang, "⚠️")
            await safe_send(context.bot, user_id, msg)
            return
        if await _is_mysql_db():
            msg = await _trans('restore_mysql_unsupported', lang, "⚠️")
            await safe_send(context.bot, user_id, msg)
            return

        doc = update.effective_message.document
        if not doc:
            msg = await _trans('send_db', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            return
        if not doc.file_name.endswith('.db'):
            msg = await _trans('db_extension', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            return
        if doc.file_size and doc.file_size > 100 * 1024 * 1024:
            msg = _fmt(await _trans('file_too_large', lang, "❌ {max_size}"),
                       max_size=100 * 1024)
            await safe_send(context.bot, user_id, msg)
            return

        tmp_path = None
        db_closed = False
        success_restore = False
        restore_error = None
        try:
            file = await doc.get_file()
            tmp_path = os.path.join(
                tempfile.gettempdir(),
                f"restore_{user_id}_{int(time.time())}.db")
            await file.download_to_drive(tmp_path)

            PATHS.BACKUPS.mkdir(parents=True, exist_ok=True)
            pre_restore = PATHS.BACKUPS / (
                f"pre_restore_{TimeUtils.mecca_now().strftime('%Y%m%d_%H%M%S')}.db")
            try:
                shutil.copy2(PATHS.DB, pre_restore)
            except Exception:
                pass

            try:
                close_fn = getattr(DB, 'close', None)
                if callable(close_fn):
                    await close_fn()
                    db_closed = True
            except Exception:
                pass

            try:
                temp_target = str(PATHS.DB) + ".restoring"
                shutil.copy2(tmp_path, temp_target)
                os.replace(temp_target, PATHS.DB)
                success_restore = True
            except Exception:
                try:
                    shutil.copy2(tmp_path, PATHS.DB)
                    success_restore = True
                except Exception as e2:
                    restore_error = e2

            if success_restore:
                for suffix in ('-wal', '-shm', '-journal'):
                    stale = Path(str(PATHS.DB) + suffix)
                    try:
                        if stale.exists():
                            stale.unlink()
                            logger.info(f"🧹 حُذف {stale.name}")
                    except Exception as e:
                        logger.warning(f"⚠️ فشل حذف {stale.name}: {e}")

                try:
                    from cache import clear_all_caches
                    await clear_all_caches()
                except Exception:
                    pass
        except Exception as e:
            restore_error = e
        finally:
            if db_closed:
                try:
                    reconnect_fn = getattr(DB, 'reconnect', None)
                    if callable(reconnect_fn):
                        await reconnect_fn()
                    else:
                        init_fn = getattr(DB, 'initialize_db', None)
                        if callable(init_fn):
                            await init_fn()
                        else:
                            init_fn = getattr(DB, 'initialize', None)
                            if callable(init_fn):
                                await init_fn()
                except Exception:
                    pass
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        if success_restore:
            msg = await _trans('restore_success', lang, "✅")
            await safe_send(context.bot, user_id, msg)
        else:
            err_text = str(restore_error)[:100] if restore_error else "?"
            await safe_send(context.bot, user_id, f"❌ {err_text}")

    @staticmethod
    async def _handle_restore_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            msg = await _trans('unauthorized', lang, "❌")
            await safe_send(context.bot, user_id, msg)
            StateManager.clear(user_id)
            return
        await MessageHandlers._do_db_restore(update, context, user_id, lang)
        StateManager.clear(user_id)

    @staticmethod
    async def _handle_backup_file_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            await safe_send(context.bot, user_id,
                            await _trans('unauthorized', lang, "❌"))
            StateManager.clear(user_id)
            return
        await MessageHandlers._do_db_restore(update, context, user_id, lang)
        StateManager.clear(user_id)

    # =================================================================
    # handle_service
    # =================================================================

    @staticmethod
    async def handle_service(update, context) -> None:
        if not update.effective_chat or not update.effective_message:
            return
        chat_id = update.effective_chat.id
        message = update.effective_message

        is_service = any([
            message.new_chat_members,
            message.left_chat_member,
            message.new_chat_title,
            message.new_chat_photo,
            message.delete_chat_photo,
            message.pinned_message,
            getattr(message, 'video_chat_started', None),
            getattr(message, 'video_chat_ended', None),
            getattr(message, 'video_chat_scheduled', None),
            getattr(message, 'video_chat_participants_invited', None),
            getattr(message, 'forum_topic_created', None),
            getattr(message, 'forum_topic_closed', None),
            getattr(message, 'forum_topic_reopened', None),
            getattr(message, 'general_forum_topic_hidden', None),
            getattr(message, 'general_forum_topic_unhidden', None),
        ])
        if not is_service:
            return

        try:
            settings = await get_security_settings_cached(chat_id)
            if settings.get('delete_service'):
                await _safe_delete_message(context.bot, chat_id, message.message_id)
        except Exception:
            pass

    @staticmethod
    async def handle_join_request(update, context) -> None:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        settings = await get_security_settings_cached(chat_id)

        if settings.get('auto_reject_join'):
            try:
                await asyncio.sleep(0.05)
                await context.bot.decline_chat_join_request(chat_id, user_id)
                return
            except Exception as e:
                logger.warning(f"decline join: {e}")

        if settings.get('auto_approve_join'):
            try:
                await asyncio.sleep(0.05)
                await context.bot.approve_chat_join_request(chat_id, user_id)
            except Exception as e:
                error_msg = str(e)
                if ("User_already_participant" in error_msg or
                        "already participant" in error_msg.lower()):
                    pass
                else:
                    logger.warning(f"approve join: {e}")


__all__ = [
    "MessageHandlers",
    "GroupRateLimiterManager",
    "clear_lang_cache",
    "_safe_delete_message",
    "_is_delete_ignore_error",
    "_invalidate_after_channel_change",
    "_detect_and_translate",
    "_send_translation_reply",
    "apply_violation_penalty",
]