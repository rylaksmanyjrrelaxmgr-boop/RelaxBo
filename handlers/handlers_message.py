#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_message.py - معالجات الرسائل (v7.9.27 - Group Log Notify)
=============================================================================
🆕 v7.9.27 (GROUP-LOG-NOTIFY):
    ✅ FIX-1: إرسال إشعار قناة السجل الخاصة بالمجموعة عند كل حذف
             - يُرسل إلى DB.get_group_log_channel(chat_id)
             - يتضمن: نوع الحذف، المستخدم، المصدر (لو كان forward)
             - لا يؤثر على إشعار المالك في الخاص (يبقى كما هو)
    ✅ FIX-2: دالة notify_group_log عامة وقابلة للاستدعاء من أي مكان
    ✅ FIX-3: تشخيص logging واضح لكل خطوة

التحسينات الموروثة من v7.9.26:
    ✅ FIX (CRITICAL): forwarded له الأولوية قبل links/mentions/banned_words
    ✅ logging "PRIORITY" واضح
    ✅ get_forward_detection_reason() للتشخيص

التحسينات الموروثة من v7.9.25 / v7.9.24 / v7.9.23:
    ✅ _safe_delete_message لا يُخفي فشل الحذف
    ✅ تشخيص كامل لكل خطوة
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
    logging.getLogger(__name__).warning("⚠️ replies.py not found")
    analyze_sentiment = None

# ═══════════════════════════════════════════════════════════════════
# استيراد أنواع MessageOrigin (Bot API 7.0+)
# ═══════════════════════════════════════════════════════════════════
try:
    from telegram import (
        MessageOriginUser,
        MessageOriginHiddenUser,
        MessageOriginChat,
        MessageOriginChannel,
    )
    _HAS_MESSAGE_ORIGIN = True
except ImportError:
    MessageOriginUser = None
    MessageOriginHiddenUser = None
    MessageOriginChat = None
    MessageOriginChannel = None
    _HAS_MESSAGE_ORIGIN = False


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

_FORWARD_NOTIFY_COOLDOWN_SECONDS = 300.0

# 🆕 v7.9.27: حجم المعاينة في إشعار قناة السجل
_GROUP_LOG_PREVIEW_LENGTH = 150

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


# =====================================================================
# إشعار قناة سجل المطور
# =====================================================================

async def _notify_dev_log(context, text: str) -> None:
    try:
        log_ch = await DB.get_log_channel()
        logger.debug(f"🔔 log_ch from DB = {log_ch!r}")
        if not log_ch:
            logger.debug("🔔 log_ch EMPTY → abort")
            return
        ch_str = str(log_ch).strip()
        if not ch_str:
            logger.debug("🔔 log_ch is whitespace → abort")
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
            chat_id=target,
            text=text,
            parse_mode='HTML',
            disable_web_page_preview=True,
        )
        logger.debug(f"🔔 _notify_dev_log SUCCESS → {target}")

    except Exception as e:
        logger.warning(f"🔔 _notify_dev_log FAILED: {e}", exc_info=True)


# ═══════════════════════════════════════════════════════════════════
# 🆕 v7.9.27: إشعار قناة السجل الخاصة بالمجموعة
# ═══════════════════════════════════════════════════════════════════

_VIOLATION_LABELS_AR = {
    'forwarded': '↩️ رسالة معاد توجيهها',
    'link': '🔗 رابط',
    'mention': '📢 منشن',
    'banned_word': '🚫 كلمة محظورة',
    'max_len': '📏 طول زائد',
    'video': '🎬 فيديو',
    'photo': '📷 صورة',
    'audio': '🎵 صوت',
    'voice': '🎤 فويس',
    'sticker': '🖼️ ملصق',
    'document': '📄 ملف',
    'animation': '🎞️ أنيميشن',
    'video_note': '🎥 فيديو نوت',
}

_FORWARD_TYPE_LABELS_AR = {
    'user': '👤 مستخدم',
    'hidden_user': '👻 مستخدم مخفي',
    'chat': '👥 مجموعة',
    'channel': '📢 قناة',
}


async def notify_group_log(
    context,
    chat_id: int,
    text: str,
    disable_preview: bool = True,
) -> bool:
    """
    🆕 v7.9.27: يُرسل إشعاراً لقناة السجل الخاصة بهذه المجموعة.

    Args:
        context: ContextTypes
        chat_id: معرّف المجموعة (للقراءة من DB.get_group_log_channel)
        text: نص الإشعار (HTML)
        disable_preview: تعطيل معاينة الروابط

    Returns:
        True إذا نجح الإرسال، False خلاف ذلك.
    """
    try:
        getter = getattr(DB, 'get_group_log_channel', None)
        if not callable(getter):
            logger.debug("ℹ️ DB.get_group_log_channel غير موجود")
            return False

        channel_id = await getter(chat_id)
        if not channel_id:
            logger.debug(f"ℹ️ لا توجد قناة سجل للمجموعة {chat_id}")
            return False

        # تحويل القيمة إلى int إن كانت نصاً رقمياً
        if isinstance(channel_id, str) and channel_id.lstrip('-').isdigit():
            channel_id = int(channel_id)

        await context.bot.send_message(
            chat_id=channel_id,
            text=text,
            parse_mode='HTML',
            disable_web_page_preview=disable_preview,
        )
        logger.info(
            f"✅ notify_group_log OK | group={chat_id} → "
            f"channel={channel_id}"
        )
        return True

    except BadRequest as e:
        err = str(e).lower()
        if "chat not found" in err:
            logger.error(
                f"❌ notify_group_log: القناة غير موجودة | group={chat_id} "
                f"| تأكد أن البوت مضاف كعضو/مشرف في القناة"
            )
        elif "not enough rights" in err or "bot is not a member" in err:
            logger.error(
                f"❌ notify_group_log: البوت ليس عضواً/مشرفاً | group={chat_id}"
            )
        else:
            logger.warning(
                f"⚠️ notify_group_log BadRequest | group={chat_id}: {e}"
            )
        return False
    except Exception as e:
        logger.error(
            f"❌ notify_group_log FAILED | group={chat_id}: {e}",
            exc_info=True,
        )
        return False


def _build_delete_log_text(
    chat_id: int,
    user_id: int,
    user_first_name: str,
    user_username: Optional[str],
    violation_type: str,
    forward_info: Optional[Dict[str, Any]] = None,
    message_preview: Optional[str] = None,
) -> str:
    """
    🆕 v7.9.27: يبني نص إشعار الحذف لقناة السجل.
    """
    label = _VIOLATION_LABELS_AR.get(violation_type, violation_type)

    user_display = escape(user_first_name or 'User')
    if user_username:
        user_display_lnk = (
            f"<a href='tg://user?id={user_id}'>{user_display}</a> "
            f"(@{escape(user_username)})"
        )
    else:
        user_display_lnk = (
            f"<a href='tg://user?id={user_id}'>{user_display}</a>"
        )

    lines = [
        "🗑️ <b>حذف رسالة</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📌 النوع: {label}",
        f"👤 المستخدم: {user_display_lnk}",
        f"🆔 المعرّف: <code>{user_id}</code>",
    ]

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
        fid = forward_info.get('id')
        if fid:
            lines.append(f"   • المعرّف: <code>{fid}</code>")
        if forward_info.get('signature'):
            lines.append(
                f"   • التوقيع: {escape(str(forward_info['signature']))}"
            )
        if forward_info.get('message_id'):
            lines.append(
                f"   • رقم الرسالة الأصلية: "
                f"<code>{forward_info['message_id']}</code>"
            )

    try:
        now_str = TimeUtils.mecca_now().strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    lines.append("")
    lines.append(f"🕐 {now_str}")

    return "\n".join(lines)


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


def _is_delete_permission_error(exc: Exception) -> bool:
    try:
        err = str(exc).lower()
        return _DELETE_PERMISSION_ERROR in err
    except Exception:
        return False


async def _safe_delete_message(bot, chat_id: int, message_id: int) -> bool:
    """
    ✅ v7.9.24: لا يُخفي فشل الحذف.
    ✅ v7.9.25: logging مفصّل مع السبب.
    """
    try:
        await bot.delete_message(chat_id, message_id)
        logger.info(
            f"✅ DELETE OK | chat={chat_id} msg={message_id}"
        )
        return True
    except BadRequest as e:
        err_str = str(e)
        if _is_delete_permission_error(e):
            logger.error(
                f"❌ DELETE FAILED (permission) | "
                f"chat={chat_id} msg={message_id} | "
                f"السبب: البوت لا يملك صلاحية can_delete_messages "
                f"أو الرسالة محمية | "
                f"raw_error={err_str!r}"
            )
            return False
        if _is_delete_ignore_error(e):
            logger.info(
                f"ℹ️ DELETE ignored | chat={chat_id} msg={message_id} | "
                f"raw_error={err_str!r}"
            )
            return True
        logger.warning(
            f"⚠️ DELETE failed (BadRequest) | "
            f"chat={chat_id} msg={message_id} | raw_error={err_str!r}"
        )
        return False
    except Exception as e:
        err_str = str(e)
        if _is_delete_permission_error(e):
            logger.error(
                f"❌ DELETE FAILED (permission, non-BadRequest) | "
                f"chat={chat_id} msg={message_id} | raw_error={err_str!r}"
            )
            return False
        if _is_delete_ignore_error(e):
            logger.info(
                f"ℹ️ DELETE ignored (non-BadRequest) | "
                f"chat={chat_id} msg={message_id} | raw_error={err_str!r}"
            )
            return True
        logger.warning(
            f"⚠️ DELETE failed (unexpected) | "
            f"chat={chat_id} msg={message_id} | "
            f"exc_type={type(e).__name__} | raw_error={err_str!r}"
        )
        return False


# ═══════════════════════════════════════════════════════════════════
# أدوات كشف الرسائل المُعاد توجيهها
# ═══════════════════════════════════════════════════════════════════

def is_forwarded(message) -> bool:
    if message is None:
        return False
    return (
        getattr(message, 'forward_origin', None) is not None
        or getattr(message, 'forward_date', None) is not None
        or getattr(message, 'forward_from', None) is not None
        or getattr(message, 'forward_from_chat', None) is not None
        or getattr(message, 'forward_sender_name', None) is not None
    )


def get_forward_detection_reason(message) -> Dict[str, Any]:
    """
    ✅ v7.9.25: يُرجع dict يشرح بالضبط لماذا is_forwarded أعاد True/False.
    """
    if message is None:
        return {"error": "message is None"}

    fields = {}
    for name in (
        'forward_origin', 'forward_date',
        'forward_from', 'forward_from_chat', 'forward_sender_name',
    ):
        val = getattr(message, name, None)
        fields[name] = {
            "present": val is not None,
            "type": type(val).__name__ if val is not None else None,
            "repr_short": (str(val)[:80] if val is not None else None),
        }

    any_present = any(f["present"] for f in fields.values())

    return {
        "is_forwarded": any_present,
        "fields": fields,
        "has_message_origin_module": _HAS_MESSAGE_ORIGIN,
    }


def _extract_legacy_forward_info(message) -> Optional[Dict[str, Any]]:
    try:
        fwd_from = getattr(message, 'forward_from', None)
        fwd_from_chat = getattr(message, 'forward_from_chat', None)
        fwd_sender_name = getattr(message, 'forward_sender_name', None)
        fwd_date = getattr(message, 'forward_date', None)
        fwd_signature = getattr(message, 'forward_signature', None)

        if fwd_from is not None:
            full_name = ""
            try:
                full_name = (getattr(fwd_from, 'full_name', None)
                             or getattr(fwd_from, 'first_name', None)
                             or "")
            except Exception:
                full_name = ""
            return {
                'type': 'user',
                'id': getattr(fwd_from, 'id', None),
                'name': full_name or str(getattr(fwd_from, 'id', 'User')),
                'date': fwd_date,
                'signature': None,
                'message_id': None,
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
                'date': fwd_date,
                'signature': fwd_signature,
                'message_id': None,
            }

        if fwd_sender_name:
            return {
                'type': 'hidden_user',
                'id': None,
                'name': str(fwd_sender_name),
                'date': fwd_date,
                'signature': None,
                'message_id': None,
            }
    except Exception as e:
        logger.debug(f"_extract_legacy_forward_info: {e}")

    return None


def extract_forward_info(message) -> Optional[Dict[str, Any]]:
    if message is None:
        return None

    origin = getattr(message, 'forward_origin', None)

    if origin is not None and _HAS_MESSAGE_ORIGIN:
        try:
            if isinstance(origin, MessageOriginUser):
                u = origin.sender_user
                name = ""
                try:
                    name = (getattr(u, 'full_name', None)
                            or getattr(u, 'first_name', None)
                            or str(getattr(u, 'id', 'User')))
                except Exception:
                    name = str(getattr(u, 'id', 'User'))
                return {
                    'type': 'user',
                    'id': getattr(u, 'id', None),
                    'name': name,
                    'date': getattr(origin, 'date', None),
                    'signature': None,
                    'message_id': None,
                }

            if isinstance(origin, MessageOriginHiddenUser):
                return {
                    'type': 'hidden_user',
                    'id': None,
                    'name': (getattr(origin, 'sender_user_name', None)
                             or 'Hidden'),
                    'date': getattr(origin, 'date', None),
                    'signature': None,
                    'message_id': None,
                }

            if isinstance(origin, MessageOriginChat):
                c = origin.sender_chat
                return {
                    'type': 'chat',
                    'id': getattr(c, 'id', None),
                    'name': (getattr(c, 'title', None)
                             or getattr(c, 'username', None)
                             or str(getattr(c, 'id', 'Chat'))),
                    'date': getattr(origin, 'date', None),
                    'signature': getattr(origin, 'author_signature', None),
                    'message_id': None,
                }

            if isinstance(origin, MessageOriginChannel):
                c = origin.chat
                return {
                    'type': 'channel',
                    'id': getattr(c, 'id', None),
                    'name': (getattr(c, 'title', None)
                             or getattr(c, 'username', None)
                             or str(getattr(c, 'id', 'Channel'))),
                    'date': getattr(origin, 'date', None),
                    'signature': getattr(origin, 'author_signature', None),
                    'message_id': getattr(origin, 'message_id', None),
                }
        except Exception as e:
            logger.debug(f"extract_forward_info(origin): {e}")

    return _extract_legacy_forward_info(message)


async def _notify_admin_about_forward(context, admin_id: int, info: Dict[str, Any]) -> None:
    if not info or not admin_id:
        return
    try:
        type_labels = {
            'user': '👤 مستخدم',
            'hidden_user': '👻 مستخدم مخفي',
            'chat': '👥 مجموعة',
            'channel': '📢 قناة',
        }
        label = type_labels.get(info.get('type', ''), f"❔ {info.get('type')}")

        lines = ["↩️ <b>رسالة معاد توجيهها</b>", ""]
        lines.append(f"📌 النوع: {label}")
        if info.get('id'):
            lines.append(f"🆔 المصدر: <code>{info['id']}</code>")
        if info.get('name'):
            lines.append(f"📛 الاسم: {escape(str(info['name']))}")
        if info.get('signature'):
            lines.append(f"✍️ التوقيع: {escape(str(info['signature']))}")
        if info.get('message_id'):
            lines.append(f"🔢 رقم الرسالة الأصلية: <code>{info['message_id']}</code>")
        if info.get('date'):
            lines.append(f"📅 تاريخ الإعادة: <code>{info['date']}</code>")

        await safe_send(
            context.bot, admin_id,
            "\n".join(lines),
            parse_mode='HTML',
        )
    except Exception as e:
        logger.debug(f"_notify_admin_about_forward: {e}")


def _should_notify_forward(context, chat_id: int) -> bool:
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


# =====================================================================
# تحديث أوامر الأدمن
# =====================================================================

async def _refresh_admin_commands_safe(bot, user_id: int, is_admin: bool) -> bool:
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


def _fmt(template: str, **kwargs) -> str:
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
# apply_violation_penalty
# ═══════════════════════════════════════════════════════════════════

async def apply_violation_penalty(update, context, chat_id, user_id,
                                   violation_type, penalty_type,
                                   duration_seconds,
                                   lang: str = 'ar') -> Tuple[bool, str]:
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
# التحقق من صلاحيات البوت في قناة السجل
# =====================================================================

async def _verify_bot_in_log_channel(context, channel_id: int) -> Tuple[bool, str]:
    if not channel_id:
        return False, "invalid_channel_id"

    bot_id = None
    try:
        bot_id = context.bot.id
    except Exception:
        return False, "bot_id_unavailable"

    if not bot_id:
        return False, "bot_id_missing"

    try:
        member = await asyncio.wait_for(
            context.bot.get_chat_member(channel_id, bot_id),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        return False, "timeout"
    except BadRequest as e:
        err = str(e).lower()
        if ("chat not found" in err
                or "bot is not a member" in err
                or "member not found" in err
                or "user not found" in err):
            return False, "bot_not_member"
        if ("chat_admin_required" in err
                or "not enough rights" in err):
            return False, "need_admin_rights"
        logger.warning(f"_verify_bot_in_log_channel BadRequest: {e}")
        return False, "bad_request"
    except Exception as e:
        logger.warning(f"_verify_bot_in_log_channel: {e}")
        return False, "unknown_error"

    status = getattr(member, "status", None)
    if status not in ("administrator", "creator"):
        return False, "not_admin"

    can_post = getattr(member, "can_post_messages", None)
    if can_post is False:
        return False, "no_post_permission"

    return True, ""


def _verify_bot_in_log_channel_error_text(reason: str, lang: str) -> str:
    mapping = {
        "invalid_channel_id": "❌ معرّف القناة غير صالح.",
        "bot_id_unavailable": "❌ لا يمكن تحديد معرّف البوت.",
        "bot_id_missing": "❌ لا يمكن تحديد معرّف البوت.",
        "timeout": "⏱️ انتهت مهلة الاتصال بـ Telegram. حاول مجدداً.",
        "bot_not_member": "❌ البوت ليس عضواً في القناة. أضفه أولاً.",
        "need_admin_rights": "❌ البوت يحتاج صلاحيات مشرف في القناة.",
        "not_admin": "❌ البوت ليس مشرفاً في القناة. رقّه أولاً.",
        "no_post_permission": "❌ البوت لا يملك صلاحية النشر في القناة.",
        "bad_request": "❌ تعذّر الوصول للقناة. تحقق من المعرّف.",
        "unknown_error": "❌ خطأ غير متوقع أثناء التحقق من القناة.",
    }
    return mapping.get(reason, "❌ تعذّر التحقق من صلاحيات البوت في القناة.")


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
        UserState.WAIT_CONTEST_QUESTION: "_handle_contest_question",
        UserState.WAIT_CONTEST_CORRECT_ANSWER: "_handle_contest_correct_answer",
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
            msg = await _trans('channel_not_found', lang,
                               "❌ لم يتم العثور على القناة.")
            await safe_send(context.bot, user_id, msg)
            return True

        try:
            verified, reason = await _verify_bot_in_log_channel(
                context, channel_int
            )
        except Exception as e:
            logger.error(
                f"❌ _verify_bot_in_log_channel({channel_int}): {e}",
                exc_info=True,
            )
            verified, reason = False, "unknown_error"

        if not verified:
            error_text = _verify_bot_in_log_channel_error_text(reason, lang)
            full_msg = (
                f"{error_text}\n\n"
                f"💡 <b>خطوات الحل:</b>\n"
                f"1️⃣ أضف البوت إلى القناة\n"
                f"2️⃣ رقّيه كمشرف\n"
                f"3️⃣ فعّل صلاحية 'نشر الرسائل' (إن كانت قناة)\n"
                f"4️⃣ أعد الإرسال هنا"
            )
            logger.warning(
                f"⚠️ v7.9.13: رفض قناة السجل {channel_int} "
                f"للمجموعة {log_group_id} — السبب: {reason}"
            )
            await safe_send(context.bot, user_id, full_msg, parse_mode='HTML')
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
            msg = await _trans('save_failed', lang, "❌ فشل الحفظ.")
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
    # 🆕 v7.9.26: رسائل المجموعات — Forward Priority Fix
    # 🆕 v7.9.27: إرسال إشعار لقناة السجل الخاصة بالمجموعة
    # =================================================================

    @staticmethod
    async def handle_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        ✅ v7.9.26: فحص forwarded له الأولوية القصوى.
        ✅ v7.9.27: إرسال إشعار لقناة السجل عند الحذف.

        الترتيب:
          1. service (delete_service)
          2. 🎯 FORWARDED (delete_forwarded) ← الأولوية القصوى
          3. links (delete_links)
          4. mentions
          5. banned_words
          6. max_len
          7. media (photos/videos/...)
          8. translation
          9. auto_reply
        """
        if not update.effective_chat or not update.effective_message:
            return

        if not update.effective_user:
            logger.debug(
                "handle_group: effective_user=None — تخطي "
                "(channel post / anonymous)"
            )
            return

        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        message = update.effective_message
        msg_id = getattr(message, 'message_id', None)

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

        # ═══════════════════════════════════════════════════════════════
        # DIAGNOSTIC BLOCK
        # ═══════════════════════════════════════════════════════════════
        _df_raw = settings.get('delete_forwarded')
        _df_bool = bool(_df_raw)

        _det = get_forward_detection_reason(message)
        _is_fwd = _det.get('is_forwarded', False)

        _fwd_active = _is_fwd and _df_bool
        _log_level = logging.WARNING if _fwd_active else logging.INFO

        logger.log(
            _log_level,
            f"🔍 FWD-CHECK | "
            f"chat={chat_id} user={user_id} msg={msg_id} | "
            f"delete_forwarded={_df_raw!r} (bool={_df_bool}) | "
            f"is_forwarded={_is_fwd} | "
            f"module_supports_origin={_det.get('has_message_origin_module')} | "
            f"has_text={bool(msg_text)} has_caption={bool(msg_caption)}"
        )

        for _fname, _finfo in _det.get('fields', {}).items():
            logger.log(
                _log_level,
                f"   ↳ {_fname}: present={_finfo['present']} "
                f"type={_finfo['type']} "
                f"val={_finfo['repr_short']}"
            )

        if _is_fwd:
            _info = extract_forward_info(message)
            if _info:
                logger.log(
                    _log_level,
                    f"   ✅ forward_info: "
                    f"type={_info.get('type')} "
                    f"id={_info.get('id')} "
                    f"name={_info.get('name')!r} "
                    f"orig_msg_id={_info.get('message_id')} "
                    f"date={_info.get('date')}"
                )
            else:
                logger.log(
                    _log_level,
                    f"   ⚠️ is_forwarded=True لكن "
                    f"extract_forward_info=None "
                    f"(نوع غير معروف — راجع Bot API)"
                )

        if not _df_bool:
            logger.info(
                f"   ⏭️ SKIP: delete_forwarded=0/None "
                f"(chat={chat_id}) — التفعيل غير مفعّل"
            )
        # ═══════════════════════════════════════════════════════════════

        # ─── 1) الخدمة ───
        if settings.get('delete_service'):
            if message.new_chat_members or message.left_chat_member:
                await _safe_delete_message(context.bot, chat_id, message.message_id)
                return

        # ═══════════════════════════════════════════════════════════════
        # 2) 🎯 FORWARDED — الأولوية القصوى
        # ═══════════════════════════════════════════════════════════════
        if settings.get('delete_forwarded'):
            if is_forwarded(message):
                logger.warning(
                    f"🎯 HANDLE-FWD (PRIORITY) | "
                    f"chat={chat_id} user={user_id} msg={msg_id} | "
                    f"يُعالَج كـ forwarded قبل link/mention/banned_words"
                )

                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id, "forwarded", settings)

                logger.warning(
                    f"🎯 HANDLE-FWD | انتهى _delete_and_warn | "
                    f"chat={chat_id} msg={msg_id}"
                )
                return

        # ─── 3) الروابط ───
        if settings.get('delete_links'):
            if TextUtils.contains_link(full_text):
                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id, "link", settings)
                return

        # ─── 4) المنشن ───
        if settings.get('mentions'):
            if TextUtils.contains_mention(full_text):
                await MessageHandlers._delete_and_warn(
                    update, context, chat_id, user_id, "mention", settings)
                return

        # ─── 5) الكلمات المحظورة ───
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

        # ─── 6) الطول ───
        max_len = settings.get('max_message_length', 0)
        if max_len > 0 and len(full_text) > max_len:
            await MessageHandlers._delete_and_warn(
                update, context, chat_id, user_id, "max_len", settings)
            return

        # ─── 7) الوسائط ───
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

        # ─── 8) الترجمة التلقائية ───
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

        # ─── 9) الردود التلقائية ───
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
        ✅ v7.9.25: تشخيص كامل — يطبع كل خطوة.
        ✅ v7.9.27: إرسال إشعار لقناة السجل الخاصة بالمجموعة عند نجاح الحذف.
        """
        logger.warning(
            f"🔧 DELETE-WARN | start | "
            f"chat={chat_id} user={user_id} "
            f"violation={violation_type}"
        )

        lang = await _ensure_lang(update, context)

        # ═══════════════════════════════════════════════════════════
        # استخراج forward_info قبل الحذف (لو الرسالة معاد توجيهها)
        # ═══════════════════════════════════════════════════════════
        forward_info: Optional[Dict[str, Any]] = None
        if violation_type == 'forwarded':
            try:
                _msg_pre = update.effective_message
                if _msg_pre is not None:
                    forward_info = extract_forward_info(_msg_pre)
                    logger.warning(
                        f"🔧 DELETE-WARN | forward_info قبل الحذف: "
                        f"{forward_info}"
                    )
                else:
                    logger.warning(
                        f"🔧 DELETE-WARN | effective_message=None — "
                        f"لا يمكن استخراج forward_info"
                    )
            except Exception as e:
                logger.warning(
                    f"🔧 DELETE-WARN | extract_forward_info فشل: {e}",
                    exc_info=True,
                )

        # ═══════════════════════════════════════════════════════════
        # حفظ معاينة النص قبل الحذف (لقناة السجل)
        # ═══════════════════════════════════════════════════════════
        message_preview: Optional[str] = None
        try:
            _m = update.effective_message
            if _m is not None:
                message_preview = (
                    _m.text or _m.caption or ""
                ).strip() or None
        except Exception:
            pass

        # ═══════════════════════════════════════════════════════════
        # تنفيذ الحذف
        # ═══════════════════════════════════════════════════════════
        delete_ok = False
        _msg_id_to_delete = None
        try:
            msg_obj = update.effective_message
            if msg_obj and msg_obj.message_id:
                _msg_id_to_delete = msg_obj.message_id
                logger.warning(
                    f"🔧 DELETE-WARN | محاولة حذف msg={_msg_id_to_delete} "
                    f"من chat={chat_id}"
                )
                delete_ok = await _safe_delete_message(
                    context.bot, chat_id, msg_obj.message_id
                )
                logger.warning(
                    f"🔧 DELETE-WARN | نتيجة الحذف: "
                    f"{'✅ نجح' if delete_ok else '❌ فشل'} | "
                    f"chat={chat_id} msg={_msg_id_to_delete}"
                )
            else:
                logger.warning(
                    f"🔧 DELETE-WARN | لا يوجد message_id للحذف"
                )
        except Exception as e:
            logger.error(
                f"🔧 DELETE-WARN | استثناء أثناء الحذف: {e}",
                exc_info=True,
            )
            delete_ok = False

        # ═══════════════════════════════════════════════════════════
        # 🆕 v7.9.27: إشعار قناة السجل الخاصة بالمجموعة
        # ═══════════════════════════════════════════════════════════
        if delete_ok:
            try:
                user_obj = update.effective_user
                user_first = (
                    getattr(user_obj, 'first_name', None) or "User"
                ) if user_obj else "User"
                user_username = (
                    getattr(user_obj, 'username', None)
                ) if user_obj else None

                log_text = _build_delete_log_text(
                    chat_id=chat_id,
                    user_id=user_id,
                    user_first_name=user_first,
                    user_username=user_username,
                    violation_type=violation_type,
                    forward_info=forward_info,
                    message_preview=message_preview,
                )

                # إرسال غير متزامن حتى لا يُعطّل المعالجة
                _log_task = asyncio.create_task(
                    notify_group_log(context, chat_id, log_text)
                )
                _log_task.add_done_callback(
                    lambda t: (
                        t.exception() if not t.cancelled() else None
                    )
                )
                logger.info(
                    f"📢 group_log notify spawned | "
                    f"chat={chat_id} violation={violation_type}"
                )
            except Exception as e:
                logger.warning(
                    f"⚠️ group_log notify spawn فشل: {e}",
                    exc_info=True,
                )

        # ═══════════════════════════════════════════════════════════
        # إشعار المالك في الخاص (لو الرسالة معاد توجيهها)
        # ═══════════════════════════════════════════════════════════
        if forward_info and _should_notify_forward(context, chat_id):
            try:
                owner_id = int(getattr(CONFIG, 'PRIMARY_OWNER_ID', 0) or 0)
                if owner_id:
                    _notify_task = asyncio.create_task(
                        _notify_admin_about_forward(context, owner_id, forward_info)
                    )
                    _notify_task.add_done_callback(
                        lambda t: (
                            t.exception() if not t.cancelled()
                            else None
                        )
                    )
                    logger.info(
                        f"↩️ forward notify spawned "
                        f"(chat={chat_id}, owner={owner_id})"
                    )
            except Exception as e:
                logger.debug(f"forward notify spawn: {e}")

        if not delete_ok and violation_type == 'forwarded':
            logger.error(
                f"⏭️ DELETE-WARN | توقف — الحذف فشل | "
                f"chat={chat_id} msg={_msg_id_to_delete} | "
                f"السبب الأرجح: البوت لا يملك can_delete_messages "
                f"أو ليس admin"
            )
            return

        # ═══════════════════════════════════════════════════════════
        # العقوبات والتحذير
        # ═══════════════════════════════════════════════════════════
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
            await DB.add_admin_log(
                chat_id, context.bot.id, f"violation_{violation_type}", user_id)
        except Exception:
            pass

        violation_message = await MessageHandlers._get_violation_message(
            violation_type, lang)

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

    @staticmethod
    async def _handle_update_ch_input(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)
        if not CONFIG.is_developer(user_id):
            StateManager.clear(user_id)
            return

        text = (update.effective_message.text or "").strip()

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
    # المشرفين
    # =================================================================

    @staticmethod
    async def _handle_admin_add_input(update, context):
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

        try:
            result = await DB.add_banned_word(word, -1, user_id)
            if isinstance(result, tuple) and len(result) >= 2:
                success, duplicate = bool(result[0]), bool(result[1])
            else:
                success = bool(result)
                duplicate = False
        except Exception as e:
            logger.error(
                f"❌ add_banned_word (global) exception: {e}",
                exc_info=True,
            )
            success, duplicate = False, False

        if success:
            invalidate_banned_words_cache(-1)
            msg = _fmt(await _trans('word_added', lang, "✅ {word}"),
                       word=escape(word))
            await safe_send(context.bot, user_id, msg)
        elif duplicate:
            msg = await _trans('word_exists', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        else:
            logger.warning(
                f"⚠️ add_banned_word فشل (global): "
                f"word={word!r}, user={user_id} — "
                f"راجع سجل database_groups للتفاصيل"
            )
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

        try:
            result = await DB.add_banned_word(word, chat_id, user_id)
            if isinstance(result, tuple) and len(result) >= 2:
                success, duplicate = bool(result[0]), bool(result[1])
            else:
                success = bool(result)
                duplicate = False
        except Exception as e:
            logger.error(
                f"❌ add_banned_word (group) exception: {e}",
                exc_info=True,
            )
            success, duplicate = False, False

        if success:
            invalidate_banned_words_cache(chat_id)
            msg = _fmt(await _trans('word_added', lang, "✅ {word}"),
                       word=escape(word))
            await safe_send(context.bot, user_id, msg)
        elif duplicate:
            msg = await _trans('word_exists', lang, "❌")
            await safe_send(context.bot, user_id, msg)
        else:
            logger.warning(
                f"⚠️ add_banned_word فشل (group): "
                f"word={word!r}, chat_id={chat_id}, user={user_id} — "
                f"راجع سجل database_groups للتفاصيل"
            )
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

    # ═════════════════════════════════════════════════════════════════
    # المسابقات
    # ═════════════════════════════════════════════════════════════════

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

        StateManager.set(user_id, UserState.WAIT_CONTEST_DURATION)

        duration_keys = [
            ("1h",  "contest_duration_1h",  "⏰ ساعة"),
            ("6h",  "contest_duration_6h",  "🕐 6 ساعات"),
            ("1d",  "contest_duration_1d",  "📅 يوم"),
            ("3d",  "contest_duration_3d",  "📅 3 أيام"),
            ("1w",  "contest_duration_1w",  "📅 أسبوع"),
            ("2w",  "contest_duration_2w",  "📅 أسبوعان"),
            ("1mo", "contest_duration_1mo", "📅 شهر"),
            ("2mo", "contest_duration_2mo", "📅 شهران"),
            ("3mo", "contest_duration_3mo", "📅 3 أشهر"),
            ("6mo", "contest_duration_6mo", "📅 6 أشهر"),
            ("1y",  "contest_duration_1y",  "📅 سنة"),
        ]

        kb_rows = []
        row = []
        for key, trans_key, fallback in duration_keys:
            label = await _trans(trans_key, lang, fallback)
            row.append(InlineKeyboardButton(
                label, callback_data=f"contest_duration:{key}"))
            if len(row) == 2:
                kb_rows.append(row)
                row = []
        if row:
            kb_rows.append(row)

        prompt = await _trans(
            'contest_duration_pick', lang,
            "📅 <b>اختر مدة المسابقة:</b>\n"
            "<i>سيُحسب تاريخ الانتهاء تلقائياً.</i>"
        )

        await safe_send(
            context.bot, user_id,
            prompt,
            reply_markup=InlineKeyboardMarkup(kb_rows),
            parse_mode='HTML',
        )

    @staticmethod
    async def _handle_contest_question(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)

        question = (update.effective_message.text or "").strip()[:1000]
        if not question:
            await safe_send(context.bot, user_id,
                            await _trans('empty_message', lang, "❌"))
            return

        context.user_data['contest_question'] = question
        StateManager.set(user_id, UserState.WAIT_CONTEST_CORRECT_ANSWER)

        prompt = await _trans(
            'contest_correct_answer_prompt', lang,
            "✅ <b>الإجابة الصحيحة؟</b>\n"
            "<i>ستُقارَن بإجابات المشاركين (غير حساسة لحالة الأحرف).</i>"
        )
        await safe_send(context.bot, user_id, prompt, parse_mode='HTML')

    @staticmethod
    async def _handle_contest_correct_answer(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)

        correct_answer = (update.effective_message.text or "").strip()[:500]
        if not correct_answer:
            await safe_send(context.bot, user_id,
                            await _trans('empty_message', lang, "❌"))
            return

        title = (context.user_data.get('contest_title') or '').strip()
        description = (context.user_data.get('contest_desc') or '').strip()
        prize = (context.user_data.get('contest_prize') or '').strip()
        end_date = context.user_data.get('contest_end_date', '')
        question = (context.user_data.get('contest_question') or '').strip()
        duration_label = (context.user_data.get('contest_duration_label') or '').strip()

        try:
            cid = await DB.create_contest(
                creator_id=user_id,
                title=title,
                description=description,
                prize=prize,
                end_date=end_date,
                contest_type='quiz',
                question=question,
                correct_answer=correct_answer,
            )
        except Exception as e:
            logger.error(f"❌ create quiz contest: {e}", exc_info=True)
            cid = 0

        if cid:
            title_line = escape(title) if title else "—"
            prize_line = escape(prize) if prize else "—"
            duration_line = duration_label if duration_label else "—"

            text = _fmt(
                await _trans('contest_created_quiz', lang,
                    "✅ <b>أُنشئت المسابقة!</b>\n\n"
                    "🏆 <b>{title}</b>\n"
                    "🆔 <code>#{id}</code>\n"
                    "🎁 الجائزة: {prize}\n"
                    "❓ النوع: سؤال وجواب\n"
                    "⏱️ المدة: {duration}\n"
                    "📝 السؤال: {question}\n"
                    "✅ الإجابة: <tg-spoiler>{answer}</tg-spoiler>"),
                title=title_line,
                id=cid,
                prize=prize_line,
                duration=duration_line,
                question=escape(question),
                answer=escape(correct_answer),
            )
            await safe_send(context.bot, user_id, text, parse_mode='HTML')
        else:
            await safe_send(
                context.bot, user_id,
                await _trans('contest_create_failed', lang,
                             "❌ فشل الإنشاء"),
            )

        StateManager.clear(user_id)

    @staticmethod
    async def _handle_contest_date(update, context):
        user_id = update.effective_user.id
        lang = await _ensure_lang(update, context)

        title = (context.user_data.get('contest_title') or '').strip()
        desc = (context.user_data.get('contest_desc') or '').strip()
        prize = (context.user_data.get('contest_prize') or '').strip()
        date = (update.effective_message.text or "").strip()

        parsed = _parse_contest_date(date)
        if not parsed:
            await safe_send(context.bot, user_id,
                            await _trans('invalid_date', lang, "❌"))
            StateManager.clear(user_id)
            return

        try:
            contest_id = await DB.create_contest(
                creator_id=user_id,
                title=title,
                description=desc,
                prize=prize,
                end_date=date,
                contest_type='raffle',
            )
        except Exception as e:
            logger.error(f"❌ create raffle contest: {e}", exc_info=True)
            contest_id = 0

        if contest_id:
            title_line = escape(title) if title else "—"
            prize_line = escape(prize) if prize else "—"

            end_line = _fmt(
                await _trans('contest_end_line', lang,
                             "🕐 <b>ينتهي:</b> <code>{end}</code>\n"),
                end=escape(date))
            type_line = await _trans('contest_type_raffle_label', lang,
                                     "🎲 النوع: سحب عشوائي")

            text = _fmt(
                await _trans('contest_created_raffle', lang,
                    "✅ <b>أُنشئت المسابقة!</b>\n\n"
                    "🏆 <b>{title}</b>\n"
                    "🆔 <code>#{id}</code>\n"
                    "🎁 الجائزة: {prize}\n"
                    "{type_line}\n"
                    "⏱️ المدة: {duration}\n"
                    "{end_line}"
                    "👥 المشاركون: 0"),
                title=title_line,
                id=contest_id,
                prize=prize_line,
                type_line=type_line,
                duration="—",
                end_line=end_line,
            )
            await safe_send(context.bot, user_id, text, parse_mode='HTML')
        else:
            await safe_send(context.bot, user_id,
                            await _trans('execution_failed', lang, "❌"))

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
                context.bot, chat_id, target, action, duration, "", user_id,
                lang=lang)
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

        logger.info(f"🔔 redeem_gift_code (msg) result={result!r} user={user_id}")

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

            try:
                uname = update.effective_user.username or ""
                fname = update.effective_user.first_name or ""
                username_display = f"@{uname}" if uname else "❌ لا يوجد"
                await _notify_dev_log(
                    context,
                    f"🎁 <b>استخدام كود هدية</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 <b>الاسم:</b> {escape(str(fname or '—'))}\n"
                    f"🔗 <b>المعرف:</b> {escape(username_display)}\n"
                    f"🆔 <b>الرقم التعريفي:</b> <code>{user_id}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎟️ <b>الكود:</b> <code>{escape(code)}</code>\n"
                    f"⏱️ <b>المدة المُمنوحة:</b> {days} يوم\n"
                    f"📅 <b>الوقت:</b> {TimeUtils.mecca_iso()}",
                )
            except Exception as e:
                logger.warning(
                    f"🔔 notify dev log (gift input) raised: {e}",
                    exc_info=True,
                )

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
    "_is_delete_permission_error",
    "_invalidate_after_channel_change",
    "_detect_and_translate",
    "_send_translation_reply",
    "apply_violation_penalty",
    "_verify_bot_in_log_channel",
    "_notify_dev_log",
    "is_forwarded",
    "extract_forward_info",
    "get_forward_detection_reason",
    "_extract_legacy_forward_info",
    "_notify_admin_about_forward",
    "_should_notify_forward",
    "notify_group_log",
    "_build_delete_log_text",
]