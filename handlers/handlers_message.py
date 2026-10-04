#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_message.py - v7.10.8 (AUTO-DETECT SPAM - No Config Needed)
=============================================================================
🆕 v7.10.8:
    ✅ كشف تلقائي عبر spam_score (5+ نقاط = حذف)
    ✅ لا يحتاج أي إعداد (يعمل مباشرة)
    ✅ يميز Post Bot ورسائل Spam المشابهة
    ✅ يدمج كل الطبقات السابقة
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
import ipaddress
import unicodedata
from pathlib import Path
from html import escape
from typing import Optional, Dict, Any, List, Tuple, Coroutine
from datetime import datetime
from urllib.parse import urlparse
from collections import defaultdict, deque

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
    analyze_sentiment = None

try:
    from telegram import (
        MessageOriginUser, MessageOriginHiddenUser,
        MessageOriginChat, MessageOriginChannel,
    )
    _HAS_MESSAGE_ORIGIN = True
except ImportError:
    MessageOriginUser = MessageOriginHiddenUser = None
    MessageOriginChat = MessageOriginChannel = None
    _HAS_MESSAGE_ORIGIN = False

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Unicode Normalization
# ═══════════════════════════════════════════════════════════════════

_HIDDEN_CHARS = (
    '\u200b', '\u200c', '\u200d', '\u200e', '\u200f',
    '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
    '\u2060', '\u2061', '\u2062', '\u2063', '\u2064', '\ufeff',
)


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    try:
        text = unicodedata.normalize('NFKC', text)
    except Exception:
        pass
    for c in _HIDDEN_CHARS:
        if c in text:
            text = text.replace(c, '')
    text = re.sub(
        r'[\s\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+',
        ' ', text)
    return text.strip()

# ═══════════════════════════════════════════════════════════════════
# 🆕 v7.10.8: Auto Spam Detection via Score
# ═══════════════════════════════════════════════════════════════════

_SPAM_KEYWORDS = (
    'leak', 'viral', 'pack', 'clip', 'clips',
    'uncensored', 'collection', 'archive', 'drop',
    'check', 'tap', 'click', 'view', 'open',
    'xxx', 'nsfw', 'porn', 'sex',
    'hot', 'nude', 'nudes', 'sexy',
    'mega', 'wild', 'fresh', 'best',
    'teen', 'teenager', 'milf', 'dilf',
    'bj', 'mfm', 'cartoon', 'korean',
    'colombian', 'pierced', 'petite',
    'busty', 'taboo', 'step', 'mom',
)

_SPAM_EMOJIS = (
    '⭐', '💀', '🔥', '✨', '🍑', '🔞', '🚨', '💎',
    '🎁', '🎉', '🌟', '💥', '⚡', '🌸', '🌺', '💋',
    '👑', '🥇', '🏆', '🎯', '💯', '🆕', '🆗',
    '🔴', '🟢', '🔵', '🟡', '🟣', '🟠',
)

_URL_RE = re.compile(r'https?://[^\s<>"]+', re.IGNORECASE)


def _compute_spam_score(message) -> Tuple[int, List[str]]:
    """
    v7.10.8: يحسب نقاط spam تلقائياً.
    Returns: (score, reasons)
    """
    score = 0
    reasons: List[str] = []

    try:
        text = (message.text or message.caption or "")
        normalized = _normalize_text(text)
        text_lower = normalized.lower()

        # 1) عدد الأزرار
        urls: List[str] = []
        button_count = 0
        try:
            markup = getattr(message, 'reply_markup', None)
            if markup is not None:
                kb = getattr(markup, 'inline_keyboard', None)
                if kb:
                    for row in kb:
                        for btn in row:
                            button_count += 1
                            u = getattr(btn, 'url', None)
                            if u and isinstance(u, str):
                                urls.append(u)
        except Exception:
            pass

        if button_count >= 3:
            score += 3
            reasons.append(f"buttons={button_count}")
        elif button_count == 2:
            score += 1
            reasons.append("buttons=2")

        # 2) صورة + أزرار
        if message.photo and button_count >= 1:
            score += 2
            reasons.append("photo+buttons")
        elif message.video and button_count >= 1:
            score += 2
            reasons.append("video+buttons")

        # 3) إيموجي spam
        emoji_count = 0
        for e in _SPAM_EMOJIS:
            if e in text:
                emoji_count += text.count(e)
        if emoji_count >= 2:
            score += 2
            reasons.append(f"emoji={emoji_count}")
        elif emoji_count >= 1:
            score += 1

        # 4) كلمات مفتاحية
        kw_matches = sum(1 for kw in _SPAM_KEYWORDS if kw in text_lower)
        if kw_matches >= 3:
            score += 3
            reasons.append(f"keywords={kw_matches}")
        elif kw_matches >= 2:
            score += 2
            reasons.append(f"keywords={kw_matches}")
        elif kw_matches >= 1:
            score += 1

        # 5) CAPS WORDS (كلمات كبيرة متعددة)
        caps_words = re.findall(r'\b[A-Z]{4,}\b', normalized)
        if len(caps_words) >= 4:
            score += 2
            reasons.append(f"CAPS={len(caps_words)}")
        elif len(caps_words) >= 2:
            score += 1
            reasons.append(f"CAPS={len(caps_words)}")

        # 6) روابط t.me في الأزرار
        tme_count = sum(1 for u in urls if 't.me/' in u.lower())
        if tme_count >= 2:
            score += 2
            reasons.append(f"tme_buttons={tme_count}")
        elif tme_count >= 1:
            score += 1
            reasons.append(f"tme_buttons={tme_count}")

        # 7) روابط في النص
        text_urls = _URL_RE.findall(text)
        if len(text_urls) >= 2:
            score += 2
            reasons.append(f"text_urls={len(text_urls)}")
        elif len(text_urls) >= 1:
            score += 1

        # 8) طول النص قصير جداً + أزرار (مؤشر)
        if len(normalized) < 30 and button_count >= 2:
            score += 1
            reasons.append("short_text+buttons")

    except Exception as e:
        logger.debug(f"_compute_spam_score: {e}")

    return score, reasons


# ═══════════════════════════════════════════════════════════════════
# Post Bot Pattern (legacy - kept for compatibility)
# ═══════════════════════════════════════════════════════════════════

_POSTBOT_EMOJI = r'[⭐💀🔥✨🍑🔞🚨💎🎁🎉🌟💥⚡🌸🌺💋👑🥇🏆🎯💯🆕🆗🔴🟢🔵🟡🟣🟠]'
_POSTBOT_PATTERN = re.compile(
    _POSTBOT_EMOJI + r'.{0,10}' +
    r'\b[A-Z]{4,}(?:\s+[A-Z]{4,}){1,}' +
    r'.{0,10}' + _POSTBOT_EMOJI, re.UNICODE
)
_POSTBOT_PATTERN_LOOSE = re.compile(
    _POSTBOT_EMOJI + r'.{0,5}' +
    r'\b[A-Z]{4,}(?:\s+[A-Z]{4,}){2,}', re.UNICODE
)


def _is_postbot_pattern(text: str) -> bool:
    if not text or len(text) < 15:
        return False
    try:
        if _POSTBOT_PATTERN.search(text):
            return True
        if _POSTBOT_PATTERN_LOOSE.search(text):
            return True
    except Exception:
        pass
    return False


def _env_flag(name: str, default: bool = True) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


FEATURE_LOG_DELETIONS = _env_flag("LOG_DELETIONS", True)
FEATURE_LOG_PENALTIES = _env_flag("LOG_PENALTIES", True)
FEATURE_LOG_GIFTS = _env_flag("LOG_GIFTS", True)
FEATURE_LOG_ADMIN_CHANGES = _env_flag("LOG_ADMIN_CHANGES", True)

MAX_PENALTY_MINUTES = 30 * 24 * 60
LOG_RATE_LIMIT_PER_MIN = 30
LOG_RATE_WINDOW_SEC = 60.0
LOG_RETRY_ATTEMPTS = 3
LOG_RETRY_BASE_DELAY = 0.5
DEV_LOG_CACHE_TTL = 300.0
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

_FORWARD_NOTIFY_COOLDOWN_SECONDS = 300.0
_GROUP_LOG_PREVIEW_LENGTH = 150

_PROTECTED_FORWARD_HINTS = (
    "محولة من", "محوّل من", "محوله من",
    "تم التحويل من", "المعاد توجيهها من",
    "Forwarded from", "من قناة",
)

_DELETE_IGNORED_PATTERNS = (
    "message to delete not found",
    "message identifier is not specified",
    "message is not found",
)
_DELETE_PERMISSION_ERROR = "message can't be deleted"

_MEDIA_REPLY_TYPES = frozenset({
    'photo', 'video', 'document', 'audio',
    'animation', 'voice', 'sticker', 'video_note',
})

TRANSLATION_REPLY_DELETE_DELAY = 30
TRANSLATION_MIN_TEXT_LENGTH = 2
PENALTY_MESSAGE_DELETE_DELAY = 10

# threshold
SPAM_SCORE_THRESHOLD = 5

_columns_initialized = False


async def _lazy_init_columns():
    global _columns_initialized
    if _columns_initialized:
        return
    _columns_initialized = True
    db_type = getattr(DB, "DB_TYPE", "sqlite")
    logger.info(f"🔧 v7.10.8: Auto-migration يبدأ (DB_TYPE={db_type})")

    cols = [
        ("delete_protected_any", "INTEGER DEFAULT 0", "TINYINT(1) DEFAULT 0"),
        ("delete_postbot_pattern", "INTEGER DEFAULT 0", "TINYINT(1) DEFAULT 0"),
        ("delete_spam_score", "INTEGER DEFAULT 1", "TINYINT(1) DEFAULT 1"),
    ]
    for col_name, pg_def, mysql_def in cols:
        try:
            if db_type == "postgres":
                await DB.execute(
                    f"ALTER TABLE group_security "
                    f"ADD COLUMN IF NOT EXISTS {col_name} {pg_def}")
                logger.info(f"✅ PG: {col_name} جاهز")
            elif db_type == "mysql":
                try:
                    await DB.execute(
                        f"ALTER TABLE group_security ADD COLUMN {col_name} {mysql_def}")
                    logger.info(f"✅ MySQL: {col_name} جاهز")
                except Exception as e:
                    m = str(e).lower()
                    if "duplicate" in m or "already exists" in m:
                        logger.info(f"ℹ️ MySQL: {col_name} موجود")
                    else:
                        logger.warning(f"⚠️ MySQL {col_name}: {e}")
            else:
                try:
                    await DB.execute(
                        f"ALTER TABLE group_security ADD COLUMN {col_name} {pg_def}")
                    logger.info(f"✅ SQLite: {col_name} جاهز")
                except Exception as e:
                    m = str(e).lower()
                    if "duplicate" in m or "already exists" in m:
                        logger.info(f"ℹ️ SQLite: {col_name} موجود")
                    else:
                        logger.warning(f"⚠️ SQLite {col_name}: {e}")
        except Exception as e:
            logger.warning(f"⚠️ auto-migration {col_name}: {e}")

    try:
        await DB.execute(
            "UPDATE group_security SET delete_protected_any = 1 "
            "WHERE delete_forwarded = 1 "
            "  AND (delete_protected_any IS NULL OR delete_protected_any = 0)")
        logger.info("✅ تم تفعيل delete_protected_any")
    except Exception as e:
        logger.warning(f"⚠️ UPDATE: {e}")

    try:
        await internal_cache.clear()
        logger.info("✅ internal_cache cleared")
    except Exception as e:
        logger.debug(f"cache clear: {e}")


_dev_log_cache = None
_dev_log_cache_ts = 0.0
_dev_log_cache_lock = asyncio.Lock()


async def _get_dev_log_channel_cached():
    global _dev_log_cache, _dev_log_cache_ts
    now = time.monotonic()
    if (_dev_log_cache is not None
            and now - _dev_log_cache_ts < DEV_LOG_CACHE_TTL):
        return _dev_log_cache
    async with _dev_log_cache_lock:
        now = time.monotonic()
        if (_dev_log_cache is not None
                and now - _dev_log_cache_ts < DEV_LOG_CACHE_TTL):
            return _dev_log_cache
        try:
            ch = await DB.get_log_channel()
            _dev_log_cache = ch
            _dev_log_cache_ts = now
            return ch
        except Exception as e:
            logger.warning(f"get_dev_log_channel_cached: {e}")
            return _dev_log_cache


def _invalidate_dev_log_cache():
    global _dev_log_cache, _dev_log_cache_ts
    _dev_log_cache = None
    _dev_log_cache_ts = 0.0


async def _notify_dev_log(context, text):
    try:
        log_ch = await _get_dev_log_channel_cached()
        if not log_ch:
            return
        ch_str = str(log_ch).strip()
        if not ch_str:
            return
        if ch_str.lstrip('-').isdigit():
            target = int(ch_str)
        elif ch_str.startswith('@'):
            target = ch_str
        elif ch_str.startswith(('https://', 'http://')):
            tail = ch_str.rstrip('/').split('/')[-1]
            if tail.startswith('@'):
                tail = tail[1:]
            target = f"@{tail}" if not tail.lstrip('-').isdigit() else int(tail)
        else:
            target = f"@{ch_str}"
        await context.bot.send_message(
            chat_id=target, text=text,
            parse_mode='HTML', disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"🔔 _notify_dev_log FAILED: {e}")


_log_rate_tracker = defaultdict(lambda: deque(maxlen=LOG_RATE_LIMIT_PER_MIN))
_log_rate_lock = asyncio.Lock()


async def _can_send_log(chat_id):
    async with _log_rate_lock:
        now = time.monotonic()
        tracker = _log_rate_tracker[chat_id]
        if (len(tracker) >= LOG_RATE_LIMIT_PER_MIN
                and now - tracker[0] < LOG_RATE_WINDOW_SEC):
            logger.warning(f"🚫 LOG-RATE-LIMIT | chat={chat_id}")
            return False
        tracker.append(now)
        return True


async def _dispatch_log(coro, label, *, retries=LOG_RETRY_ATTEMPTS):
    async def _runner():
        for attempt in range(retries):
            try:
                await coro
                return
            except asyncio.CancelledError:
                return
            except Exception as e:
                if attempt == retries - 1:
                    logger.error(f"❌ [{label}] failed: {e}")
                    return
                await asyncio.sleep(LOG_RETRY_BASE_DELAY * (2 ** attempt))
    task = asyncio.create_task(_runner())
    task.add_done_callback(
        lambda t: (t.exception() if not t.cancelled() and t.exception() else None))


async def _safe_invalidate(*keys):
    for k in keys:
        if not k:
            continue
        try:
            await internal_cache.invalidate(k)
        except Exception:
            pass


_VIOLATION_LABELS_AR = {
    'forwarded': '↩️ رسالة معاد توجيهها',
    'link': '🔗 رابط', 'mention': '📢 منشن',
    'banned_word': '🚫 كلمة محظورة', 'max_len': '📏 طول زائد',
    'video': '🎬 فيديو', 'photo': '📷 صورة', 'audio': '🎵 صوت',
    'voice': '🎤 فويس', 'sticker': '🖼️ ملصق', 'document': '📄 ملف',
    'animation': '🎞️ أنيميشن', 'video_note': '🎥 فيديو نوت',
    'postbot_pattern': '🤖 نمط Post Bot',
    'spam_score': '🚫 رسالة Spam',
}

_FORWARD_TYPE_LABELS_AR = {
    'user': '👤 مستخدم', 'hidden_user': '👻 مستخدم مخفي',
    'chat': '👥 مجموعة', 'channel': '📢 قناة',
    'protected': '🛡️ محتوى محمي',
    'protected_any': '🛡️ forward من قناة محمية',
}

_PENALTY_LABELS_AR = {
    'ban': '🚫 حظر', 'mute': '🔇 كتم', 'kick': '👢 طرد',
    'restrict': '🔒 تقييد', 'warn': '⚠️ تحذير', 'unban': '✅ فك حظر',
}


def _format_duration(seconds):
    if not seconds or seconds <= 0:
        return "دائم"
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "—"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    parts = []
    if days: parts.append(f"{days} يوم")
    if hours: parts.append(f"{hours} ساعة")
    if minutes: parts.append(f"{minutes} دقيقة")
    if secs and not parts: parts.append(f"{secs} ثانية")
    return " و ".join(parts) if parts else f"{seconds} ثانية"


async def notify_group_log(context, chat_id, text, disable_preview=True):
    try:
        getter = getattr(DB, 'get_group_log_channel', None)
        if not callable(getter):
            return False
        channel_id = await getter(chat_id)
        if not channel_id:
            return False
        if isinstance(channel_id, str) and channel_id.lstrip('-').isdigit():
            channel_id = int(channel_id)
        await context.bot.send_message(
            chat_id=channel_id, text=text,
            parse_mode='HTML',
            disable_web_page_preview=disable_preview)
        return True
    except BadRequest as e:
        err = str(e).lower()
        if "chat not found" in err:
            logger.error(f"❌ group_log: قناة غير موجودة | {chat_id}")
        elif "not enough rights" in err or "bot is not a member" in err:
            logger.error(f"❌ group_log: البوت ليس عضواً | {chat_id}")
        return False
    except Exception as e:
        logger.error(f"❌ group_log FAILED: {e}")
        return False


def _build_delete_log_text(chat_id, user_id, user_first_name, user_username,
                            violation_type, forward_info=None,
                            message_preview=None, is_anonymous=False):
    label = _VIOLATION_LABELS_AR.get(violation_type, violation_type)
    if is_anonymous:
        user_display_lnk = "👻 <b>مشرف مجهول</b>"
    else:
        user_display = escape(user_first_name or 'User')
        if user_username:
            user_display_lnk = (
                f"<a href='tg://user?id={user_id}'>{user_display}</a> "
                f"(@{escape(user_username)})")
        else:
            user_display_lnk = (
                f"<a href='tg://user?id={user_id}'>{user_display}</a>")
    lines = [
        "🗑️ <b>حذف رسالة</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📌 النوع: {label}",
        f"👤 المستخدم: {user_display_lnk}",
    ]
    if not is_anonymous:
        lines.append(f"🆔 المعرّف: <code>{user_id}</code>")
    else:
        lines.append(f"🆔 المجموعة: <code>{chat_id}</code>")
    if message_preview:
        preview = message_preview.strip().replace("\n", " ")
        if len(preview) > _GROUP_LOG_PREVIEW_LENGTH:
            preview = preview[:_GROUP_LOG_PREVIEW_LENGTH] + "…"
        lines.append(f"💬 النص: <i>{escape(preview)}</i>")
    if forward_info:
        ftype = forward_info.get('type') or '؟'
        ftype_label = _FORWARD_TYPE_LABELS_AR.get(ftype, ftype)
        lines.append("")
        lines.append("📤 <b>المصدر:</b>")
        lines.append(f"   • النوع: {ftype_label}")
        fname = forward_info.get('name')
        if fname:
            fname_str = str(fname)
            if len(fname_str) > 60:
                fname_str = fname_str[:60] + "…"
            lines.append(f"   • الاسم: {escape(fname_str)}")
        if forward_info.get('id'):
            lines.append(f"   • المعرّف: <code>{forward_info['id']}</code>")
    try:
        now_str = TimeUtils.mecca_now().strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    lines.append("")
    lines.append(f"🕐 {now_str}")
    return "\n".join(lines)


def _build_penalty_log_text(chat_id, target_user_id, target_first_name,
                             target_username, penalty_type, duration_seconds,
                             source="auto", violation_type=None,
                             moderator_id=None, moderator_name=None):
    ptype_label = _PENALTY_LABELS_AR.get(penalty_type, penalty_type)
    target_display = escape(target_first_name or 'User')
    if target_username:
        target_lnk = (f"<a href='tg://user?id={target_user_id}'>"
                      f"{target_display}</a> (@{escape(target_username)})")
    else:
        target_lnk = f"<a href='tg://user?id={target_user_id}'>{target_display}</a>"
    source_label = "🤖 تلقائي" if source == "auto" else "👮 يدوي"
    lines = [
        f"{ptype_label}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🎯 العقوبة: <b>{ptype_label}</b>",
        f"⏱️ المدة: {_format_duration(duration_seconds)}",
        f"📊 المصدر: {source_label}",
        "",
        f"👤 المستهدف: {target_lnk}",
        f"🆔 المعرّف: <code>{target_user_id}</code>",
    ]
    if source == "auto" and violation_type:
        vlabel = _VIOLATION_LABELS_AR.get(violation_type, violation_type)
        lines.append(f"⚠️ المخالفة: {vlabel}")
    if source == "manual" and moderator_id:
        mod_display = escape(moderator_name or "Admin")
        lines.append("")
        lines.append(f"👮 المشرف: "
                     f"<a href='tg://user?id={moderator_id}'>{mod_display}</a>")
    lines.append(f"💬 المجموعة: <code>{chat_id}</code>")
    try:
        now_str = TimeUtils.mecca_now().strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    lines.append("")
    lines.append(f"🕐 {now_str}")
    return "\n".join(lines)


async def _notify_group_log_penalty(context, chat_id, target_user_id,
                                     target_first_name, target_username,
                                     penalty_type, duration_seconds,
                                     source="auto", violation_type=None,
                                     moderator_id=None, moderator_name=None):
    if not FEATURE_LOG_PENALTIES:
        return
    if not await _can_send_log(chat_id):
        return
    try:
        text = _build_penalty_log_text(
            chat_id, target_user_id, target_first_name, target_username,
            penalty_type, duration_seconds, source, violation_type,
            moderator_id, moderator_name)
        await _dispatch_log(
            notify_group_log(context, chat_id, text),
            label=f"penalty-{penalty_type}")
    except Exception as e:
        logger.warning(f"⚠️ _notify_group_log_penalty: {e}")


_sec_auth_cache = {}
_sec_auth_cache_lock = asyncio.Lock()


async def _sec_auth_cache_cleanup():
    async with _sec_auth_cache_lock:
        now = time.monotonic()
        expired = [k for k, (_, ts) in _sec_auth_cache.items()
                   if now - ts > SEC_AUTH_CACHE_TTL]
        for k in expired:
            del _sec_auth_cache[k]
        return len(expired)


def _is_delete_ignore_error(exc):
    try:
        return any(p in str(exc).lower() for p in _DELETE_IGNORED_PATTERNS)
    except Exception:
        return False


def _is_delete_permission_error(exc):
    try:
        return _DELETE_PERMISSION_ERROR in str(exc).lower()
    except Exception:
        return False


async def _safe_delete_message(bot, chat_id, message_id):
    try:
        await bot.delete_message(chat_id, message_id)
        logger.info(f"✅ DELETE OK | chat={chat_id} msg={message_id}")
        return True
    except BadRequest as e:
        err_str = str(e)
        if _is_delete_permission_error(e):
            logger.error(f"❌ DELETE FAILED (permission) | "
                         f"chat={chat_id} msg={message_id}")
            return False
        if _is_delete_ignore_error(e):
            return True
        logger.warning(f"⚠️ DELETE failed | chat={chat_id} msg={message_id}")
        return False
    except asyncio.CancelledError:
        raise
    except Exception as e:
        if _is_delete_permission_error(e):
            return False
        if _is_delete_ignore_error(e):
            return True
        logger.warning(f"⚠️ DELETE failed | chat={chat_id} msg={message_id} | {e}")
        return False


def _has_forward_hint(text):
    if not text:
        return False
    tail = text[-200:] if len(text) > 200 else text
    for hint in _PROTECTED_FORWARD_HINTS:
        if hint in tail:
            return True
    return False


def is_forwarded(message, *, allow_protected_fallback=False,
                 allow_protected_any=False):
    if message is None:
        return False
    if getattr(message, 'forward_origin', None) is not None:
        return True
    if getattr(message, 'forward_date', None) is not None:
        return True
    if getattr(message, 'forward_from', None) is not None:
        return True
    if getattr(message, 'forward_from_chat', None) is not None:
        return True
    if getattr(message, 'forward_sender_name', None) is not None:
        return True
    is_protected = bool(getattr(message, 'has_protected_content', False) or False)
    is_auto = bool(getattr(message, 'is_automatic_forward', False) or False)
    if allow_protected_any and is_protected and not is_auto:
        return True
    if allow_protected_fallback and is_protected:
        caption = (message.caption or message.text or "")
        if _has_forward_hint(caption):
            return True
    return False


def get_forward_detection_reason(message):
    if message is None:
        return {"error": "message is None"}
    fields = {}
    for name in ('forward_origin', 'forward_date', 'forward_from',
                 'forward_from_chat', 'forward_sender_name'):
        val = getattr(message, name, None)
        fields[name] = {
            "present": val is not None,
            "type": type(val).__name__ if val is not None else None,
            "repr_short": (str(val)[:80] if val is not None else None),
        }
    any_present = any(f["present"] for f in fields.values())
    protected = bool(getattr(message, 'has_protected_content', False) or False)
    caption = (message.caption or message.text or "")
    hint = _has_forward_hint(caption) if protected else False
    auto_fwd = bool(getattr(message, 'is_automatic_forward', False) or False)
    return {
        "is_forwarded": any_present,
        "is_protected": protected,
        "has_hint": hint,
        "has_automatic_forward": auto_fwd,
        "fields": fields,
        "has_message_origin_module": _HAS_MESSAGE_ORIGIN,
    }


def _extract_legacy_forward_info(message):
    try:
        fwd_from = getattr(message, 'forward_from', None)
        fwd_from_chat = getattr(message, 'forward_from_chat', None)
        fwd_sender_name = getattr(message, 'forward_sender_name', None)
        fwd_date = getattr(message, 'forward_date', None)
        fwd_signature = getattr(message, 'forward_signature', None)
        if fwd_from is not None:
            try:
                full_name = (getattr(fwd_from, 'full_name', None)
                             or getattr(fwd_from, 'first_name', None) or "")
            except Exception:
                full_name = ""
            return {
                'type': 'user', 'id': getattr(fwd_from, 'id', None),
                'name': full_name or str(getattr(fwd_from, 'id', 'User')),
                'date': fwd_date, 'signature': None, 'message_id': None,
            }
        if fwd_from_chat is not None:
            chat_type = getattr(fwd_from_chat, 'type', '') or ''
            is_channel = chat_type == 'channel'
            return {
                'type': 'channel' if is_channel else 'chat',
                'id': getattr(fwd_from_chat, 'id', None),
                'name': (getattr(fwd_from_chat, 'title', None)
                         or getattr(fwd_from_chat, 'username', None)
                         or str(getattr(fwd_from_chat, 'id', 'Chat'))),
                'date': fwd_date, 'signature': fwd_signature,
                'message_id': None,
            }
        if fwd_sender_name:
            return {
                'type': 'hidden_user', 'id': None,
                'name': str(fwd_sender_name),
                'date': fwd_date, 'signature': None, 'message_id': None,
            }
    except Exception:
        pass
    return None


def extract_forward_info(message):
    if message is None:
        return None
    origin = getattr(message, 'forward_origin', None)
    if origin is not None and _HAS_MESSAGE_ORIGIN:
        try:
            if isinstance(origin, MessageOriginUser):
                u = origin.sender_user
                try:
                    name = (getattr(u, 'full_name', None)
                            or getattr(u, 'first_name', None)
                            or str(getattr(u, 'id', 'User')))
                except Exception:
                    name = str(getattr(u, 'id', 'User'))
                return {'type': 'user', 'id': getattr(u, 'id', None),
                        'name': name, 'date': getattr(origin, 'date', None),
                        'signature': None, 'message_id': None}
            if isinstance(origin, MessageOriginHiddenUser):
                return {'type': 'hidden_user', 'id': None,
                        'name': getattr(origin, 'sender_user_name', None) or 'Hidden',
                        'date': getattr(origin, 'date', None),
                        'signature': None, 'message_id': None}
            if isinstance(origin, MessageOriginChat):
                c = origin.sender_chat
                return {'type': 'chat', 'id': getattr(c, 'id', None),
                        'name': (getattr(c, 'title', None)
                                 or getattr(c, 'username', None)
                                 or str(getattr(c, 'id', 'Chat'))),
                        'date': getattr(origin, 'date', None),
                        'signature': getattr(origin, 'author_signature', None),
                        'message_id': None}
            if isinstance(origin, MessageOriginChannel):
                c = origin.chat
                return {'type': 'channel', 'id': getattr(c, 'id', None),
                        'name': (getattr(c, 'title', None)
                                 or getattr(c, 'username', None)
                                 or str(getattr(c, 'id', 'Channel'))),
                        'date': getattr(origin, 'date', None),
                        'signature': getattr(origin, 'author_signature', None),
                        'message_id': getattr(origin, 'message_id', None)}
        except Exception:
            pass
    info = _extract_legacy_forward_info(message)
    if info:
        return info
    is_protected = bool(getattr(message, 'has_protected_content', False) or False)
    if is_protected:
        caption = (message.caption or message.text or "")
        if _has_forward_hint(caption):
            return {'type': 'protected', 'id': None,
                    'name': '🛡️ محتوى محمي (forward مخفي)',
                    'date': None, 'signature': None, 'message_id': None}
        return {'type': 'protected_any', 'id': None,
                'name': '🛡️ forward من قناة محمية',
                'date': None, 'signature': None, 'message_id': None}
    return None


async def _notify_admin_about_forward(context, admin_id, info):
    if not info or not admin_id:
        return
    try:
        type_labels = {
            'user': '👤 مستخدم', 'hidden_user': '👻 مستخدم مخفي',
            'chat': '👥 مجموعة', 'channel': '📢 قناة',
            'protected': '🛡️ محتوى محمي',
            'protected_any': '🛡️ forward من قناة محمية',
        }
        label = type_labels.get(info.get('type', ''), f"❔ {info.get('type')}")
        lines = ["↩️ <b>رسالة معاد توجيهها</b>", "", f"📌 النوع: {label}"]
        if info.get('id'):
            lines.append(f"🆔 المصدر: <code>{info['id']}</code>")
        if info.get('name'):
            lines.append(f"📛 الاسم: {escape(str(info['name']))}")
        if info.get('message_id'):
            lines.append(f"🔢 رقم الرسالة: <code>{info['message_id']}</code>")
        if info.get('date'):
            lines.append(f"📅 التاريخ: <code>{info['date']}</code>")
        await safe_send(context.bot, admin_id, "\n".join(lines), parse_mode='HTML')
    except Exception:
        pass


def _should_notify_forward(context, chat_id):
    try:
        bot_data = getattr(context, 'bot_data', None)
        if not isinstance(bot_data, dict):
            return False
        key = f"_forward_notify_{chat_id}"
        now = time.monotonic()
        last = bot_data.get(key, 0.0)
        if not isinstance(last, (int, float)):
            last = 0.0
        if now - last < _FORWARD_NOTIFY_COOLDOWN_SECONDS:
            return False
        bot_data[key] = now
        return True
    except Exception:
        return False


async def _refresh_admin_commands_safe(bot, user_id, is_admin):
    if not user_id:
        return False
    try:
        from main import refresh_admin_commands
    except ImportError:
        return False
    try:
        return bool(await refresh_admin_commands(bot, user_id, is_admin))
    except Exception:
        return False


async def _invalidate_after_channel_change(user_id, channel_db_id=None,
                                            invalidate_posts=True):
    keys = [f"start_data_{user_id}", f"user_{user_id}",
            f"user_{user_id}_True", f"user_{user_id}_False",
            f"channels_{user_id}"]
    if channel_db_id is not None:
        keys.append(f"channel_info_{channel_db_id}")
    await _safe_invalidate(*keys)
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


class GroupRateLimiterManager:
    _limiters = {}
    _last_access = {}
    _lock = asyncio.Lock()
    MAX_SIZE = MAX_GROUP_LIMITERS_CACHE

    @classmethod
    async def get(cls, chat_id):
        async with cls._lock:
            now = time.time()
            if (len(cls._limiters) >= cls.MAX_SIZE
                    and chat_id not in cls._limiters):
                sorted_items = sorted(cls._last_access.items(), key=lambda x: x[1])
                to_remove = sorted_items[: cls.MAX_SIZE // 5]
                for cid, _ in to_remove:
                    cls._limiters.pop(cid, None)
                    cls._last_access.pop(cid, None)
            if chat_id not in cls._limiters:
                cls._limiters[chat_id] = RateLimiter(
                    max_concurrent=5, max_per_second=10)
            cls._last_access[chat_id] = now
            return cls._limiters[chat_id]

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
                await _sec_auth_cache_cleanup()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"❌ periodic_cleanup: {e}")


async def _trans(key, lang, default=""):
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


def _fmt(template, **kwargs):
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


async def _ensure_lang(update, context):
    lang = context.user_data.get('lang')
    if lang:
        return lang
    try:
        user_id = update.effective_user.id if update and update.effective_user else None
    except Exception:
        user_id = None
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


def clear_lang_cache(context):
    try:
        context.user_data.pop('lang', None)
        context.user_data.pop('translation_cache', None)
        context.user_data.pop('cached_translations', None)
        context.user_data.pop('last_translation', None)
    except Exception:
        pass


async def get_security_settings_cached(chat_id):
    cached = await settings_cache.get_security(chat_id)
    if cached is not None:
        return cached
    settings = await DB.get_security_settings(chat_id)
    await settings_cache.set_security(chat_id, settings)
    return settings


async def get_auto_reply_settings_cached(chat_id):
    cached = await settings_cache.get_auto_reply_settings(chat_id)
    if cached is not None:
        return cached
    settings = await DB.get_auto_reply_settings(chat_id)
    await settings_cache.set_auto_reply_settings(chat_id, settings)
    return settings


async def invalidate_security_cache(chat_id=None):
    await settings_cache.invalidate_security(chat_id)


async def invalidate_auto_reply_cache(chat_id=None):
    await settings_cache.invalidate_auto_reply(chat_id)


async def _delete_after_delay(bot, chat_id, message_id, delay=10):
    await asyncio.sleep(delay)
    await _safe_delete_message(bot, chat_id, message_id)


async def _detect_and_translate(update, context, chat_id, user_id, text):
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
    except Exception:
        pass
    return None


async def _send_translation_reply(bot, chat_id, original_message_id,
                                   translated, lang):
    try:
        label = TranslationManager.get_text(
            lang, "translation_label") or "🌐 <b>Translation:</b>"
    except Exception:
        label = "🌐 <b>Translation:</b>"
    try:
        kwargs = {"chat_id": chat_id,
                  "text": f"{label}\n{escape(translated)}",
                  "parse_mode": 'HTML'}
        if original_message_id:
            kwargs["reply_to_message_id"] = original_message_id
        sent = await bot.send_message(**kwargs)
        asyncio.create_task(_delete_after_delay(
            bot, chat_id, sent.message_id, TRANSLATION_REPLY_DELETE_DELAY))
    except Exception:
        pass


async def apply_violation_penalty(update, context, chat_id, user_id,
                                   violation_type, penalty_type,
                                   duration_seconds, lang='ar'):
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
        return await apply_penalty(
            context.bot, chat_id, user_id, penalty_type, duration_seconds,
            f"violation: {violation_type}", moderator=context.bot.id,
            username=username, first_name=first_name, chat_name=chat_name,
            lang=lang)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"❌ apply_violation_penalty: {e}")
        return False, str(e)[:100]


def _is_safe_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        if any(ord(c) > 127 for c in host):
            return False
        try:
            ip = ipaddress.ip_address(host)
            if (ip.is_private or ip.is_loopback or ip.is_reserved
                    or ip.is_link_local or ip.is_multicast):
                return False
        except ValueError:
            pass
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


def _parse_contest_date(date_str):
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
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                "%d-%m-%Y %H:%M", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


async def _check_admin_in_chat(context, chat_id, user_id):
    if user_id == CONFIG.PRIMARY_OWNER_ID:
        return True
    try:
        if await is_authorized_in_group(context.bot, chat_id, user_id):
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


async def _is_postgres_db():
    try:
        return getattr(DB, "DB_TYPE", "sqlite") == "postgres"
    except Exception:
        return False


async def _is_mysql_db():
    try:
        return getattr(DB, "DB_TYPE", "sqlite") == "mysql"
    except Exception:
        return False


async def _verify_bot_in_log_channel(context, channel_id):
    if not channel_id:
        return False, "invalid_channel_id"
    try:
        bot_id = context.bot.id
    except Exception:
        return False, "bot_id_unavailable"
    if not bot_id:
        return False, "bot_id_missing"
    try:
        member = await asyncio.wait_for(
            context.bot.get_chat_member(channel_id, bot_id), timeout=10.0)
    except asyncio.TimeoutError:
        return False, "timeout"
    except BadRequest as e:
        err = str(e).lower()
        if ("chat not found" in err or "bot is not a member" in err
                or "member not found" in err or "user not found" in err):
            return False, "bot_not_member"
        if "chat_admin_required" in err or "not enough rights" in err:
            return False, "need_admin_rights"
        return False, "bad_request"
    except Exception as e:
        logger.warning(f"_verify_bot_in_log_channel: {e}")
        return False, "unknown_error"
    status = getattr(member, "status", None)
    if status not in ("administrator", "creator"):
        return False, "not_admin"
    if getattr(member, "can_post_messages", None) is False:
        return False, "no_post_permission"
    return True, ""


def _verify_bot_in_log_channel_error_text(reason, lang):
    mapping = {
        "invalid_channel_id": "❌ معرّف القناة غير صالح.",
        "timeout": "⏱️ انتهت مهلة الاتصال.",
        "bot_not_member": "❌ البوت ليس عضواً في القناة.",
        "need_admin_rights": "❌ البوت يحتاج صلاحيات مشرف.",
        "not_admin": "❌ البوت ليس مشرفاً.",
        "no_post_permission": "❌ البوت لا يملك صلاحية النشر.",
        "bad_request": "❌ تعذّر الوصول للقناة.",
    }
    return mapping.get(reason, "❌ تعذّر التحقق من قناة السجل.")


try:
    from database_settings import _is_valid_channel_ref
except ImportError:
    _TG_USERNAME_RE_FALLBACK = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{3,31}$')

    def _is_valid_channel_ref(value):
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
        return False


class MessageHandlers:

    _PRIVATE_HANDLERS_MAP = {}

    @staticmethod
    async def handle_group(update, context):
        if not update.effective_chat or not update.effective_message:
            return

        chat_id = update.effective_chat.id
        await _lazy_init_columns()

        message = update.effective_message
        msg_id = getattr(message, 'message_id', None)

        if getattr(message, 'is_automatic_forward', False):
            logger.debug(f"⏭️ AUTO-FORWARD-SKIP | chat={chat_id}")
            return

        is_anonymous = False
        if update.effective_user:
            user_id = update.effective_user.id
        elif message.sender_chat is not None:
            user_id = message.sender_chat.id
            is_anonymous = True
        else:
            return

        try:
            limiter = await GroupRateLimiterManager.get(chat_id)
            await limiter.acquire()
        except Exception:
            pass

        msg_text = message.text or ""
        msg_caption = message.caption or ""
        full_text = (msg_text + " " + msg_caption).strip()
        normalized_text = _normalize_text(full_text)

        METRICS.increment_messages()
        settings = await get_security_settings_cached(chat_id)

        _df_raw = settings.get('delete_forwarded')
        _df_bool = bool(_df_raw)
        _protected_fb = bool(settings.get('delete_protected_forward') or False)
        _protected_any = bool(settings.get('delete_protected_any') or False)
        _spam_enabled = bool(settings.get('delete_spam_score', 1))

        _det = get_forward_detection_reason(message)
        _is_fwd = _det.get('is_forwarded', False)
        _is_protected = _det.get('is_protected', False)
        _has_hint = _det.get('has_hint', False)
        _is_auto_fwd = _det.get('has_automatic_forward', False)

        _is_protected_forward = (_protected_fb and _is_protected
                                  and _has_hint and not _is_fwd)
        _is_protected_any_fwd = (_protected_any and _is_protected
                                  and not _is_auto_fwd and not _is_fwd
                                  and not _is_protected_forward)

        # 🆕 spam_score
        _spam_score = 0
        _spam_reasons = []
        if _spam_enabled:
            try:
                _spam_score, _spam_reasons = _compute_spam_score(message)
            except Exception as e:
                logger.debug(f"spam_score: {e}")

        _is_spam = _spam_enabled and _spam_score >= SPAM_SCORE_THRESHOLD

        _fwd_active = (_is_fwd or _is_protected_forward
                       or _is_protected_any_fwd) and _df_bool
        _log_level = logging.WARNING if (_fwd_active or _is_spam) else logging.INFO

        logger.log(
            _log_level,
            f"🚨 HARD-DIAG | chat={chat_id} user={user_id} msg={msg_id} "
            f"{'[ANON]' if is_anonymous else ''} | "
            f"has_photo={bool(message.photo)} has_caption={bool(message.caption)} | "
            f"has_protected={_is_protected} is_auto_fwd={_is_auto_fwd} | "
            f"delete_forwarded={_df_raw!r} "
            f"protected_fb={_protected_fb} protected_any={_protected_any} | "
            f"spam_enabled={_spam_enabled} spam_score={_spam_score} "
            f"is_spam={_is_spam} | "
            f"is_forwarded={_is_fwd} | "
            f"protected_any_forward={_is_protected_any_fwd}"
        )

        if _spam_score > 0:
            logger.log(_log_level,
                       f"   🎯 SPAM-SCORE={_spam_score} | "
                       f"reasons={_spam_reasons}")

        if normalized_text and normalized_text != full_text:
            logger.info(
                f"   🧹 NORMALIZED | raw_len={len(full_text)} "
                f"norm_len={len(normalized_text)}")

        # service
        if settings.get('delete_service'):
            if message.new_chat_members or message.left_chat_member:
                await _safe_delete_message(context.bot, chat_id,
                                            message.message_id)
                return

        # 1) Forwarded priority
        if settings.get('delete_forwarded'):
            effective_forwarded = is_forwarded(
                message,
                allow_protected_fallback=_protected_fb,
                allow_protected_any=_protected_any)
            if effective_forwarded:
                tag = ""
                if _is_protected_any_fwd:
                    tag = " [PROTECTED-ANY]"
                elif _is_protected_forward:
                    tag = " [PROTECTED-FB]"
                logger.warning(
                    f"🎯 HANDLE-FWD | chat={chat_id} user={user_id} "
                    f"msg={msg_id}{tag}")
                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id, "forwarded",
                    settings, is_anonymous=is_anonymous)
                return

        # 2) Spam score (تلقائي)
        if _is_spam:
            logger.warning(
                f"🚫 HANDLE-SPAM | chat={chat_id} user={user_id} "
                f"msg={msg_id} | score={_spam_score} reasons={_spam_reasons}")
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id, "spam_score",
                settings, is_anonymous=is_anonymous)
            return

        # 3) links
        if settings.get('delete_links'):
            if TextUtils.contains_link(normalized_text):
                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id, "link",
                    settings, is_anonymous=is_anonymous)
                return

        # 4) mentions
        if settings.get('mentions'):
            if TextUtils.contains_mention(normalized_text):
                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id, "mention",
                    settings, is_anonymous=is_anonymous)
                return

        # 5) banned words
        if settings.get('delete_banned_words'):
            banned_words = await get_banned_words_cached(chat_id)
            if banned_words:
                text_lower = normalized_text.lower()
                for word in banned_words:
                    word_norm = _normalize_text(word).lower()
                    if not word_norm:
                        continue
                    if word_norm in text_lower:
                        logger.info(f"   🎯 BANNED-MATCH | word={word!r}")
                        await MessageHandlers._delete_and_warn(
                            update, context, chat_id, user_id,
                            "banned_word", settings,
                            is_anonymous=is_anonymous)
                        return

        # 6) max length
        max_len = settings.get('max_message_length', 0)
        if max_len > 0 and len(normalized_text) > max_len:
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id, "max_len",
                settings, is_anonymous=is_anonymous)
            return

        # 7) media
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
        for media, setting_key, vtype in media_checks:
            if media and settings.get(setting_key):
                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id, vtype,
                    settings, is_anonymous=is_anonymous)
                return

        # 8) translation
        if msg_text and not is_anonymous:
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

        # 9) auto reply
        if msg_text:
            await MessageHandlers._process_auto_reply(
                update, context, chat_id, msg_text, user_id)

    @staticmethod
    def _get_penalty_duration(settings, violation_type):
        if violation_type in ('flood', 'antiflood'):
            return settings.get('antiflood_penalty_duration', 3600)
        if violation_type in ('night', 'night_mode'):
            return settings.get('night_mode_action_duration', 3600)
        if violation_type in ('warn_penalty', 'warn'):
            return settings.get('warn_penalty_duration', 3600)
        return settings.get('auto_mute_duration', 3600)

    @staticmethod
    async def _get_violation_message(violation_type, lang):
        trans_key = f"violation_{violation_type}"
        default_messages = {
            'link': '🚫', 'mention': '🚫', 'banned_word': '🚫',
            'max_len': '📏', 'forwarded': '↩️', 'video': '🎬',
            'audio': '🎵', 'voice': '🎤', 'animation': '🎞️',
            'document': '📄', 'sticker': '🖼️', 'photo': '📷',
            'video_note': '🎥', 'spam_score': '🚫',
        }
        default = default_messages.get(violation_type, f'🚫 {violation_type}')
        return await _trans(trans_key, lang, default)

    @staticmethod
    async def _delete_and_warn(update, context, chat_id, user_id,
                                violation_type, settings,
                                is_anonymous=False):
        logger.warning(
            f"🔧 DELETE-WARN | chat={chat_id} user={user_id} "
            f"violation={violation_type}")

        lang = await _ensure_lang(update, context)

        forward_info = None
        if violation_type == 'forwarded':
            try:
                _m = update.effective_message
                if _m is not None:
                    forward_info = extract_forward_info(_m)
            except Exception:
                pass

        message_preview = None
        try:
            _m = update.effective_message
            if _m is not None:
                message_preview = (_m.text or _m.caption or "").strip() or None
        except Exception:
            pass

        delete_ok = False
        _msg_id = None
        try:
            msg_obj = update.effective_message
            if msg_obj and msg_obj.message_id:
                _msg_id = msg_obj.message_id
                delete_ok = await _safe_delete_message(
                    context.bot, chat_id, msg_obj.message_id)
        except Exception as e:
            logger.error(f"delete exception: {e}")
            delete_ok = False

        if delete_ok and FEATURE_LOG_DELETIONS:
            if await _can_send_log(chat_id):
                try:
                    if is_anonymous:
                        user_first = "مشرف مجهول"
                        user_username = None
                    elif update.effective_user:
                        user_first = getattr(update.effective_user,
                                              'first_name', None) or "User"
                        user_username = getattr(update.effective_user,
                                                'username', None)
                    else:
                        user_first = "Unknown"
                        user_username = None
                    log_text = _build_delete_log_text(
                        chat_id=chat_id, user_id=user_id,
                        user_first_name=user_first,
                        user_username=user_username,
                        violation_type=violation_type,
                        forward_info=forward_info,
                        message_preview=message_preview,
                        is_anonymous=is_anonymous)
                    await _dispatch_log(
                        notify_group_log(context, chat_id, log_text),
                        label=f"delete-{violation_type}")
                except Exception as e:
                    logger.warning(f"group_log spawn: {e}")

        if (forward_info and not is_anonymous
                and _should_notify_forward(context, chat_id)):
            try:
                owner_id = int(getattr(CONFIG, 'PRIMARY_OWNER_ID', 0) or 0)
                if owner_id:
                    _t = asyncio.create_task(
                        _notify_admin_about_forward(context, owner_id, forward_info))
                    _t.add_done_callback(
                        lambda t: (t.exception()
                                   if not t.cancelled() and t.exception()
                                   else None))
            except Exception:
                pass

        if not delete_ok and violation_type in ('forwarded', 'spam_score'):
            logger.error(f"⏭️ توقف — الحذف فشل")
            return

        if is_anonymous:
            try:
                vm = await MessageHandlers._get_violation_message(
                    violation_type, lang)
                warn_title = await _trans('violation_warning_title', lang, "⚠️")
                anon_notice = "👻 <b>مشرف مجهول</b>"
                sent_msg = await context.bot.send_message(
                    chat_id, f"{warn_title}\n{vm}\n{anon_notice}",
                    parse_mode='HTML')
                asyncio.create_task(_delete_after_delay(
                    context.bot, chat_id, sent_msg.message_id,
                    PENALTY_MESSAGE_DELETE_DELAY))
            except Exception:
                pass
            return

        try:
            violation_count = await DB.increment_violation_count(user_id, chat_id)
        except Exception:
            violation_count = 1

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
            await DB.add_admin_log(chat_id, context.bot.id,
                                    f"violation_{violation_type}", user_id)
        except Exception:
            pass

        vm = await MessageHandlers._get_violation_message(violation_type, lang)

        try:
            user_name = escape(update.effective_user.first_name or "User")
            warn_title = await _trans('violation_warning_title', lang, "⚠️")
            count_label = await _trans('violation_count_label', lang, "📊")
            delete_notice = await _trans('violation_delete_notice', lang, "⏳")
            sent_msg = await context.bot.send_message(
                chat_id,
                f"{warn_title}\n{vm}\n👤 {user_name}\n"
                f"{count_label}: {violation_count}\n{delete_notice}",
                parse_mode='HTML')
            asyncio.create_task(_delete_after_delay(
                context.bot, chat_id, sent_msg.message_id,
                PENALTY_MESSAGE_DELETE_DELAY))
        except Exception:
            pass

        if penalty_type:
            max_strikes = (settings.get('violation_strikes')
                           or settings.get('max_warnings') or 3)
            if violation_count >= max_strikes:
                success, msg = await apply_violation_penalty(
                    update, context, chat_id, user_id,
                    violation_type, penalty_type, duration_seconds, lang=lang)
                if success:
                    try:
                        target_first = ""
                        target_username = None
                        if update.effective_user:
                            target_first = update.effective_user.first_name or ""
                            target_username = update.effective_user.username
                        await _notify_group_log_penalty(
                            context, chat_id=chat_id, target_user_id=user_id,
                            target_first_name=target_first,
                            target_username=target_username,
                            penalty_type=penalty_type,
                            duration_seconds=duration_seconds,
                            source="auto", violation_type=violation_type)
                    except Exception:
                        pass
                    try:
                        msg_prefix = await _trans(
                            'violation_penalty_applied', lang, "🚨 {msg}")
                        sent_penalty = await safe_send(
                            context.bot, chat_id,
                            _fmt(msg_prefix, msg=msg), parse_mode='HTML')
                        if (sent_penalty is not None
                                and getattr(sent_penalty, 'message_id', None)):
                            asyncio.create_task(_delete_after_delay(
                                context.bot, chat_id, sent_penalty.message_id,
                                PENALTY_MESSAGE_DELETE_DELAY))
                        await DB.reset_violation_count(user_id, chat_id)
                    except Exception:
                        pass

    @staticmethod
    async def _process_auto_reply(update, context, chat_id, text, user_id=None):
        try:
            ars = await get_auto_reply_settings_cached(chat_id)
            if not ars.get('enabled', False):
                return False
            if ars.get('ignore_bots', True):
                eff_user = getattr(update, 'effective_user', None)
                if eff_user and getattr(eff_user, 'is_bot', False):
                    return False
            if ars.get('only_admins', False):
                if not await is_authorized_in_group(
                        context.bot, chat_id, user_id or 0):
                    return False
            reply = await DB.get_auto_reply(text, chat_id)
            if reply:
                reply_text = reply.get('reply', '') or ''
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

    @staticmethod
    async def handle_private(update, context):
        try:
            user_id = update.effective_user.id
            state = StateManager.get(user_id)
            handler_name = MessageHandlers._PRIVATE_HANDLERS_MAP.get(state)
            if handler_name:
                handler = getattr(MessageHandlers, handler_name, None)
                if handler:
                    await handler(update, context)
        except Exception as e:
            logger.exception("handle_private error")

    @staticmethod
    async def handle_service(update, context):
        if not update.effective_chat or not update.effective_message:
            return
        chat_id = update.effective_chat.id
        message = update.effective_message
        is_service = any([
            message.new_chat_members, message.left_chat_member,
            message.new_chat_title, message.new_chat_photo,
            message.delete_chat_photo, message.pinned_message,
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
    async def handle_join_request(update, context):
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
                logger.warning(f"approve join: {e}")


__all__ = [
    "MessageHandlers",
    "GroupRateLimiterManager",
    "clear_lang_cache",
    "_safe_delete_message",
    "_invalidate_after_channel_change",
    "apply_violation_penalty",
    "_notify_dev_log",
    "is_forwarded",
    "extract_forward_info",
    "get_forward_detection_reason",
    "notify_group_log",
    "_lazy_init_columns",
    "_normalize_text",
    "_compute_spam_score",
    "_is_postbot_pattern",
    "FEATURE_LOG_DELETIONS",
    "FEATURE_LOG_PENALTIES",
    "FEATURE_LOG_GIFTS",
    "FEATURE_LOG_ADMIN_CHANGES",
    "SPAM_SCORE_THRESHOLD",
]