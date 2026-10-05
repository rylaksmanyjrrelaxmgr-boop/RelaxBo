#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_command.py - معالجات الأوامر (CommandHandlers) - v7.6.5
===================================================================================
🆕 v7.6.5 (R6 REVIEW FIXES — FULL):
    🔴 Critical:
        ✅ F1  _send_long_report: strip HTML من body قبل plain_full
               (كانت <b>...</b> تظهر حرفياً عند fallback)
        ✅ F2  redeem_gift: معالجة (True, 0) كنجاح (بدون أيام)
               (كانت تُعرض كـ"كود غير صالح" رغم قبول DB)

    🟠 Medium:
        ✅ F3  _notify_dev_log: تقليم ?query و #fragment من URLs
               + دعم روابط المنشورات t.me/chan/123
        ✅ F4  _split_text_for_telegram: regex لوسوم HTML فعلية
               + إزالة شرط half_limit (مع floor معقول)
        ✅ F5  language(): try/except حول get_available_languages
        ✅ F6  _safe_edit_or_send: strip HTML في fallback + تضييق كشف الأخطاء
        ✅ F7  _resolve_target_id: query.message.chat_id للـcallbacks
               (كانت ردود callbacks في المجموعة تذهب لـPM)
        ✅ F8  start(): escape(ch_display) + guard ref_code فارغ
        ✅ F9  developer(): escape الترجمات
        ✅ F10 mood(): asyncio.to_thread + escape emoji
        ✅ F11 syncgroup: perms.get('can_act', False) بدل perms['can_act']
        ✅ F12 db_diag/db_vacuum: توحيد وجهة الرسائل (target_chat)

    🟡 Cleanup:
        ✅ C1  _normalize_force_ch: removeprefix('@') بدل lstrip('@')
        ✅ C2  _no_preview_kwargs: PTB v20+ LinkPreviewOptions (متوافق)
        ✅ C3  _mask_id: حد أوضح (prefix+suffix)
        ✅ C4  _clear_stale_state: حماية user_data=None
        ✅ C5  _spawn_notify_dev_log: warning عند فشل create_task
        ✅ C6  help_command: try/except للترجمات (استقرار)
        ✅ C7  _spawn_auto_delete: warning بدل debug (توحيد)

🆕 v7.6.4:
    ✅ R1-R9 + C1-C5 (see git history)

🆕 v7.6.3:
    ✅ C1 _resolve_target_id, C2 _spawn_notify_dev_log, M1-M6, m1-m17
===================================================================================
"""

import asyncio
import re
import time
import logging
from typing import Optional, List, Set, Tuple
from html import escape, unescape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut

# ✅ C2: دعم LinkPreviewOptions في PTB v20+ (مع fallback للأقدم)
try:
    from telegram import LinkPreviewOptions
    _HAS_LINK_PREVIEW_OPTIONS = True
except ImportError:
    LinkPreviewOptions = None
    _HAS_LINK_PREVIEW_OPTIONS = False

from config import CONFIG, PATHS
from database import DB, TimeUtils
from utils import (
    is_authorized_in_group,
    check_bot_permissions, invalidate_auth_cache, apply_penalty,
    get_text, StateManager, UserState,
    KeyboardFactory, TranslationManager, CB,
    export_auto_replies,
)
from cache import user_cache

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# ثوابت
# ═══════════════════════════════════════════════════════════════════

ANONYMOUS_BOT_ID = 1087968824
CHANNEL_BOT_ID = 136817688

# ✅ R5: بوتات تليجرام التي لا يجب أن تكون وجهة رسائل
_BOT_SENDER_IDS = frozenset({ANONYMOUS_BOT_ID, CHANNEL_BOT_ID})

TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_BUTTON_TEXT_LIMIT = 64
DB_DIAG_SPLIT_DELAY = 0.35

SEND_READ_TIMEOUT = 20.0
SEND_WRITE_TIMEOUT = 20.0
SEND_CONNECT_TIMEOUT = 15.0
SEND_POOL_TIMEOUT = 10.0
SEND_MAX_RETRIES = 2
SEND_RETRY_DELAY = 1.5

# ✅ M5: dict ثابت
_SEND_TIMEOUT_KWARGS = {
    "read_timeout": SEND_READ_TIMEOUT,
    "write_timeout": SEND_WRITE_TIMEOUT,
    "connect_timeout": SEND_CONNECT_TIMEOUT,
    "pool_timeout": SEND_POOL_TIMEOUT,
}

CONTEST_DESC_DISPLAY_MAX = 80
CONTEST_QUESTION_DISPLAY_MAX = 60

# ✅ M6: سلوك فشل فحص الاشتراك
_FORCE_SUB_FAILS_OPEN = True

# ✅ F4: regex لوسوم HTML الفعلية (لا يقبل "< 3")
_HTML_TAG_RE = re.compile(r'</?[a-zA-Z][a-zA-Z0-9]*(\s[^<>]*)?/?>')
# ✅ F1: regex لStrip HTML
_HTML_STRIP_RE = re.compile(r'<[^>]+>')

# ✅ F6: كلمات مفتاحية لأخطاء parse في Telegram
_PARSE_ERROR_KEYWORDS = (
    "can't parse",
    "can't find end tag",
    "unsupported start tag",
    "unclosed tag",
    "invalid entity",
)

# ✅ F9: نفس المنطق لـ _safe_edit_or_send
def _is_parse_error(err_str: str) -> bool:
    low = (err_str or "").lower()
    return any(k in low for k in _PARSE_ERROR_KEYWORDS)


def _strip_html_tags(s: str) -> str:
    """✅ F1/F6: يزيل وسوم HTML ويُفكّ الكيانات المُهرَّبة."""
    if not s:
        return s
    try:
        return unescape(_HTML_STRIP_RE.sub('', s))
    except Exception:
        return s


def _find_last_unclosed_lt(s: str) -> int:
    """
    ✅ F4: يرجع موضع '<' لآخر وسم HTML غير مغلق (سواء:
        - نُسي إغلاقه: <b>text
        - قُطع في المنتصف: <a href="http:
    أو -1 إن لم يوجد.

    لا يخطئ في حالة '5 < 3' (لأن ما بعد < ليس اسم وسم).
    """
    if not s:
        return -1

    depth = 0
    last_open = -1
    try:
        for m in _HTML_TAG_RE.finditer(s):
            tag = m.group(0)
            if tag.startswith('</'):
                depth = max(0, depth - 1)
            elif tag.endswith('/>'):
                continue
            else:
                depth += 1
                last_open = m.start()
    except Exception:
        return -1

    if depth > 0:
        return last_open

    # ✅ fallback: وسم مقطوع في النهاية (لم يُغلق أبداً)
    last_lt = s.rfind('<')
    if last_lt >= 0 and s.find('>', last_lt) < 0:
        frag = s[last_lt:last_lt + 30]
        if re.match(r'</?[a-zA-Z]', frag):
            return last_lt

    return -1


def _no_preview_kwargs() -> dict:
    """
    ✅ C2: kwargs لتعطيل معاينة الرابط.
    - PTB v20+ → LinkPreviewOptions(is_disabled=True)
    - PTB الأقدم → disable_web_page_preview=True
    """
    if _HAS_LINK_PREVIEW_OPTIONS:
        try:
            return {"link_preview_options": LinkPreviewOptions(is_disabled=True)}
        except Exception:
            pass
    return {"disable_web_page_preview": True}


# ✅ v7.5.27: import دالة تحليل المشاعر
try:
    from handlers.handlers_message import analyze_sentiment
    _MOOD_AVAILABLE = True
except ImportError:
    try:
        from handlers_message import analyze_sentiment
        _MOOD_AVAILABLE = True
    except ImportError:
        analyze_sentiment = None
        _MOOD_AVAILABLE = False

# ✅ C1: 'last_cb_' أُزيل — loop يمسح last_cb_<*> عبر startswith
_STALE_KEYS_ON_START = (
    'sec_chat', 'security_chat_id', 'adv_chat', 'auto_chat',
    'schedule_ch', 'ban_chat', 'contest_join', 'log_group_id',
    'pin_msg_id', 'channel_page', 'post_page', 'adm_ch_page',
    'adm_gr_page', 'auto_keyword', 'contest_id', 'contest_title',
    'contest_desc', 'contest_prize',
)


def _clear_stale_state(user_id: int, context) -> None:
    """
    ✅ v7.5.26: يمسح الحالة المعلقة عند /start.
    ✅ C4: حماية context.user_data=None.
    """
    try:
        StateManager.clear(user_id)
    except Exception as e:
        logger.debug(f"StateManager.clear({user_id}): {e}")

    # ✅ C4: حماية None
    ud = getattr(context, 'user_data', None)
    if ud is None:
        return

    try:
        for k in _STALE_KEYS_ON_START:
            try:
                ud.pop(k, None)
            except Exception:
                pass
        for k in list(ud.keys()):
            if isinstance(k, str) and k.startswith('last_cb_'):
                ud.pop(k, None)
    except Exception as e:
        logger.debug(f"_clear_stale_state user_data: {e}")


# ═══════════════════════════════════════════════════════════════════
# متتبّعات مهام الخلفية
# ═══════════════════════════════════════════════════════════════════

_NOTIFY_TASKS: Set[asyncio.Task] = set()
_AUTO_DELETE_TASKS: Set[asyncio.Task] = set()


def _spawn_notify_dev_log(context, text: str) -> None:
    """
    ✅ C2: تشغيل _notify_dev_log في الخلفية.
    ✅ R7: logger.warning عند فشل المهمة.
    ✅ C5: warning عند فشل create_task نفسه.
    """
    try:
        task = asyncio.create_task(_notify_dev_log(context, text))
        _NOTIFY_TASKS.add(task)

        def _cleanup(t: asyncio.Task) -> None:
            _NOTIFY_TASKS.discard(t)
            try:
                if not t.cancelled() and t.exception():
                    logger.warning(
                        "notify_dev_log task failed: %s", t.exception()
                    )
            except Exception:
                pass

        task.add_done_callback(_cleanup)
    except Exception as _e:
        # ✅ C5: warning بدل debug
        logger.warning("_spawn_notify_dev_log create_task failed: %s", _e)


# ═══════════════════════════════════════════════════════════════════
# دوال مساعدة
# ═══════════════════════════════════════════════════════════════════

def _safe_mtime(p):
    try:
        return p.stat().st_mtime
    except (OSError, FileNotFoundError):
        return 0


def _get_field(row, key, default=None):
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row.get(key, default)
    except AttributeError:
        pass
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return default


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except (TypeError, ValueError):
        return {}


def _mask_id(id_value, prefix=3, suffix=2):
    """
    ✅ C3: حد أوضح (prefix + suffix).
    """
    if id_value is None:
        return "***"
    s = str(id_value)
    if len(s) <= prefix + suffix:
        return "***"
    return s[:prefix] + "***" + s[-suffix:]


def _is_anonymous_sender(update: Update) -> bool:
    if not update or not update.effective_user:
        return False
    return (
        update.effective_user.id == ANONYMOUS_BOT_ID
        and getattr(update.effective_user, 'is_bot', False)
    )


def _resolve_target_id(
    update, context, *, prefer_chat: bool = False
) -> Optional[int]:
    """
    ✅ C1: استخراج معرف الهدف الآمن.
    ✅ R5: تجاهل ANONYMOUS_BOT_ID/CHANNEL_BOT_ID.
    ✅ F7: للـcallbacks، استخدم query.message.chat_id
           (حتى تظهر الردود في مكان الزر، لا في PM).

    الأولوية:
        prefer_chat=True (أوامر عادية):
            1. effective_chat.id
            2. effective_user.id (لو ليس بوت)
            3. (احتياطي) effective_chat.id
        prefer_chat=False (callbacks):
            1. query.message.chat.id  ← F7
            2. effective_user.id (لو ليس بوت)
            3. effective_chat.id
    """
    # ✅ F7: للـcallbacks، chat_id من الرسالة الأصلية
    if not prefer_chat:
        try:
            q = getattr(update, 'callback_query', None) if update else None
            if q and getattr(q, 'message', None):
                msg_chat = q.message.chat
                if msg_chat and getattr(msg_chat, 'id', None):
                    return msg_chat.id
        except Exception:
            pass

    if prefer_chat:
        try:
            if update and update.effective_chat and update.effective_chat.id:
                return update.effective_chat.id
        except Exception:
            pass

    try:
        if update and update.effective_user and update.effective_user.id:
            uid = update.effective_user.id
            # ✅ R5: تجاهل IDs بوتات تليجرام
            if uid not in _BOT_SENDER_IDS:
                return uid
    except Exception:
        pass

    try:
        if update and update.effective_chat and update.effective_chat.id:
            return update.effective_chat.id
    except Exception:
        pass

    return None


# ═══════════════════════════════════════════════════════════════════
# إرسال آمن
# ═══════════════════════════════════════════════════════════════════

async def _safe_send_message(bot, chat_id, text, **extra):
    """
    إرسال مع retry + timeout.
    ✅ C4: extra قد يطغى على قيم _SEND_TIMEOUT_KWARGS (مقصود).
    """
    for attempt in range(SEND_MAX_RETRIES + 1):
        try:
            kwargs = dict(_SEND_TIMEOUT_KWARGS)
            kwargs.update(extra)
            return await bot.send_message(
                chat_id=chat_id, text=text, **kwargs
            )
        except TimedOut as e:
            if attempt < SEND_MAX_RETRIES:
                wait = SEND_RETRY_DELAY * (attempt + 1)
                logger.warning(
                    f"⏱️ send_message timed out "
                    f"(attempt {attempt+1}/{SEND_MAX_RETRIES+1}), "
                    f"retrying in {wait:.1f}s..."
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    f"❌ send_message FAILED after "
                    f"{SEND_MAX_RETRIES+1} attempts: {e}"
                )
        except Exception as e:
            logger.error(f"❌ send_message error (non-timeout): {e}")
            return None
    return None


# ═══════════════════════════════════════════════════════════════════
# إشعار قناة سجل المطور
# ═══════════════════════════════════════════════════════════════════

async def _notify_dev_log(context, text: str) -> None:
    """
    ✅ v7.6.0: يرسل إشعاراً لقناة سجل المطور.
    ✅ R8: رفض URLs غير صالحة (+invite، t.me مجردة).
    ✅ F3: تقليم ?query و #fragment + دعم روابط المنشورات.
    """
    try:
        log_ch = ''
        try:
            if hasattr(DB, 'get_dev_log_channel'):
                log_ch = await DB.get_dev_log_channel()
        except Exception as e:
            logger.debug(f"get_dev_log_channel failed: {e}")

        if not log_ch:
            try:
                log_ch = await DB.get_log_channel()
            except Exception as e:
                logger.debug(f"get_log_channel failed: {e}")

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
            # ✅ F3: تنظيف URL (query + fragment + trailing slash)
            cleaned = ch_str.split('?', 1)[0].split('#', 1)[0].rstrip('/')
            parts = cleaned.split('/')

            # https://t.me/<username> أو https://t.me/<username>/<post_id>
            if len(parts) < 4:
                logger.debug(
                    "notify_dev_log: URL قصير جداً | %s", ch_str
                )
                return

            host = parts[2].lower()
            if host not in ('t.me', 'telegram.me'):
                logger.debug(
                    "notify_dev_log: host غير مدعوم (%s) | %s",
                    host, ch_str,
                )
                return

            # ✅ F3: لو رابط منشور (t.me/chan/123) → chan
            if len(parts) >= 5:
                tail = parts[-2]
            else:
                tail = parts[-1]

            # رفض invite links (+hash) و الفراغات
            if not tail or tail.startswith('+'):
                logger.debug(
                    "notify_dev_log: invite أو فارغ | %s", ch_str
                )
                return

            if tail.startswith('@'):
                tail = tail[1:]

            target = (
                f"@{tail}"
                if not tail.lstrip('-').isdigit()
                else int(tail)
            )
        else:
            target = f"@{ch_str}"

        # ✅ C2: kwargs متوافقة مع PTB v20+
        kwargs = {"parse_mode": 'HTML'}
        kwargs.update(_no_preview_kwargs())

        await _safe_send_message(context.bot, target, text, **kwargs)
    except Exception as e:
        logger.warning(f"notify_dev_log FAILED: {e}", exc_info=True)


# ═══════════════════════════════════════════════════════════════════
# الترجمة
# ═══════════════════════════════════════════════════════════════════

async def _trans(key: str, lang: str, default: str = "") -> str:
    """ترجمة آمنة مع fallback عربي."""
    if not key:
        return default or ""

    try:
        if lang and lang != 'off':
            text = TranslationManager.get_text(lang, key)
            if text and text != key:
                return text
    except Exception as e:
        logger.warning(f"_trans({key}, {lang}) TranslationManager: {e}")

    try:
        if lang and lang != 'off':
            text = await get_text(lang, key)
            if text and text != key:
                return text
    except Exception as e:
        logger.warning(f"_trans({key}, {lang}) get_text: {e}")

    return default or key


async def _get_lang(user_id: int) -> str:
    """✅ M1: cache أولاً، ثم DB."""
    try:
        data = await user_cache.get_or_load(user_id, DB)
        if data and isinstance(data, dict):
            lang = data.get('language')
            if lang:
                return lang
    except Exception as e:
        logger.debug(f"user_cache.get_or_load({user_id}): {e}")

    try:
        return await DB.get_user_language(user_id) or 'ar'
    except Exception as e:
        logger.debug(f"get_user_language({user_id}): {e}")
        return 'ar'


# ═══════════════════════════════════════════════════════════════════
# حذف تلقائي
# ═══════════════════════════════════════════════════════════════════

async def _delete_message_after(bot, chat_id: int, message_id: int, delay: int = 10):
    try:
        safe_delay = max(0, int(delay))
        if safe_delay > 0:
            await asyncio.sleep(safe_delay)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.debug(f"حذف تلقائي فشل: {e}")


def _spawn_auto_delete(bot, chat_id: int, message_id: int, delay: int) -> None:
    """
    ✅ C7: warning بدل debug (توحيد مع _spawn_notify_dev_log).
    """
    try:
        task = asyncio.create_task(
            _delete_message_after(bot, chat_id, message_id, delay)
        )
        _AUTO_DELETE_TASKS.add(task)

        def _cleanup(t):
            _AUTO_DELETE_TASKS.discard(t)
            try:
                if not t.cancelled() and t.exception():
                    logger.warning("auto_delete task failed: %s", t.exception())
            except Exception:
                pass

        task.add_done_callback(_cleanup)
    except Exception as e:
        logger.warning(f"_spawn_auto_delete create_task failed: {e}")


async def _send_and_auto_delete(
    context, chat_id: int, text: str,
    reply_markup=None, parse_mode=None, delay: int = 10,
):
    """إرسال مع auto-delete + retry."""
    msg = await _safe_send_message(
        context.bot, chat_id, text,
        reply_markup=reply_markup, parse_mode=parse_mode,
    )

    if msg is None and parse_mode:
        logger.warning(
            f"⚠️ _send_and_auto_delete: fallback without parse_mode "
            f"(chat={chat_id})"
        )
        # ✅ F6: استخدم نصاً بدون وسوم
        plain_text = _strip_html_tags(text)
        msg = await _safe_send_message(
            context.bot, chat_id, plain_text,
            reply_markup=reply_markup, parse_mode=None,
        )

    if msg is None:
        logger.error(
            f"❌ _send_and_auto_delete: فشل كامل "
            f"(chat={chat_id}, parse_mode={parse_mode})"
        )
        return None

    _spawn_auto_delete(context.bot, chat_id, msg.message_id, delay)
    return msg


# ═══════════════════════════════════════════════════════════════════
# _safe_edit_or_send
# ═══════════════════════════════════════════════════════════════════

async def _safe_edit_or_send(update, context, text, reply_markup=None, parse_mode=None):
    """
    إرسال/تعديل مع retry + fallback.
    ✅ C1: prefer_chat للأوامر.
    ✅ R5: يتجاهل ANONYMOUS_BOT_ID.
    ✅ F6: strip HTML في fallback + تضييق كشف أخطاء parse.
    ✅ F7: callbacks → chat_id من رسالة الزر.
    """
    query = update.callback_query
    prefer_chat = query is None
    target = _resolve_target_id(
        update, context, prefer_chat=prefer_chat
    )

    if target is None:
        logger.error(
            "❌ _safe_edit_or_send: لا يمكن تحديد chat_id"
        )
        return False

    # محاولة تعديل (للـcallbacks)
    if query and query.message:
        for attempt in range(SEND_MAX_RETRIES + 1):
            try:
                kwargs = dict(_SEND_TIMEOUT_KWARGS)
                await query.edit_message_text(
                    text, reply_markup=reply_markup,
                    parse_mode=parse_mode, **kwargs
                )
                return True
            except BadRequest as e:
                err = str(e).lower()
                if "message is not modified" in err:
                    return True
                # ✅ F6: كشف دقيق لأخطاء parse
                if _is_parse_error(err):
                    try:
                        # ✅ F6: strip HTML قبل fallback
                        plain_text = _strip_html_tags(text)
                        await query.edit_message_text(
                            plain_text, reply_markup=reply_markup,
                            parse_mode=None,
                            **dict(_SEND_TIMEOUT_KWARGS)
                        )
                        return True
                    except Exception:
                        pass
                logger.debug(f"edit فشل: {e}")
                break
            except TimedOut:
                if attempt < SEND_MAX_RETRIES:
                    wait = SEND_RETRY_DELAY * (attempt + 1)
                    logger.warning(
                        f"⏱️ edit_message_text timed out "
                        f"(attempt {attempt+1}/{SEND_MAX_RETRIES+1}), "
                        f"retry in {wait:.1f}s"
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.warning("⏱️ edit timed out — fallback to send")
                break
            except Exception as e:
                logger.debug(f"edit error: {e}")
                break

    # إرسال جديد
    msg = await _safe_send_message(
        context.bot, target, text,
        reply_markup=reply_markup, parse_mode=parse_mode,
    )
    if msg:
        return True

    if parse_mode:
        # ✅ F6: strip HTML
        plain_text = _strip_html_tags(text)
        msg = await _safe_send_message(
            context.bot, target, plain_text,
            reply_markup=reply_markup, parse_mode=None,
        )
        if msg:
            return True

    logger.error(f"❌ _safe_edit_or_send: فشل كامل target={target}")
    return False


# ═══════════════════════════════════════════════════════════════════
# كاش الاشتراك الإجباري
# ═══════════════════════════════════════════════════════════════════

_force_sub_cache: dict = {}
_FORCE_SUB_CACHE_TTL = 180
_FORCE_SUB_CACHE_MAX = 10_000

_force_channel_cache: dict = {}
_FORCE_CHANNEL_CACHE_TTL = 600
_FORCE_CHANNEL_CACHE_MAX = 500


def _normalize_force_ch(force_ch: str) -> str:
    """
    ✅ C5 + R3 + C1: تطبيع قيمة force_channel.
    - يُزيل مسافات
    - يُزيل @ البادئة (واحد فقط)
    """
    if not force_ch:
        return ""
    s = str(force_ch).strip()
    # ✅ C1: removeprefix بدل lstrip
    if s.startswith('@'):
        s = s[1:]
    return s


def _force_sub_cache_set(key, value):
    """✅ M2: LRU عند التجاوز."""
    if (
        key not in _force_sub_cache
        and len(_force_sub_cache) >= _FORCE_SUB_CACHE_MAX
    ):
        try:
            oldest = sorted(
                _force_sub_cache.items(),
                key=lambda x: x[1][0]
            )
            remove_n = max(1, len(oldest) // 4)
            for k, _ in oldest[:remove_n]:
                _force_sub_cache.pop(k, None)
        except Exception:
            _force_sub_cache.clear()
    _force_sub_cache[key] = value


def _force_channel_cache_set(key, value):
    """✅ M2: cap على كاش القنوات."""
    if (
        key not in _force_channel_cache
        and len(_force_channel_cache) >= _FORCE_CHANNEL_CACHE_MAX
    ):
        try:
            oldest = sorted(
                _force_channel_cache.items(),
                key=lambda x: x[1][0]
            )
            remove_n = max(1, len(oldest) // 4)
            for k, _ in oldest[:remove_n]:
                _force_channel_cache.pop(k, None)
        except Exception:
            _force_channel_cache.clear()
    _force_channel_cache[key] = value


async def _get_force_channel_cached(bot, force_ch: str):
    """✅ R3: يستخدم _normalize_force_ch."""
    norm = _normalize_force_ch(force_ch)
    if not norm:
        return None

    now = time.time()
    cached = _force_channel_cache.get(norm)
    if cached:
        ts, chat = cached
        if now - ts < _FORCE_CHANNEL_CACHE_TTL:
            return chat

    try:
        if norm.lstrip('-').isdigit():
            chat = await bot.get_chat(int(norm))
        else:
            chat = await bot.get_chat(f"@{norm}")
        _force_channel_cache_set(norm, (now, chat))
        return chat
    except Exception as e:
        logger.debug(f"⚠️ get_chat فشل ({norm}): {e}")
        if cached:
            return cached[1]
        return None


async def _check_force_subscription_cached(bot, user_id: int, force_ch: str) -> bool:
    """
    ✅ R3: يستخدم _normalize_force_ch.
    ✅ M6: _FORCE_SUB_FAILS_OPEN يتحكم بسلوك الفشل.
    """
    norm = _normalize_force_ch(force_ch)
    if not norm:
        return _FORCE_SUB_FAILS_OPEN

    now = time.time()
    cache_key = (user_id, norm)
    cached = _force_sub_cache.get(cache_key)
    if cached:
        ts, is_subscribed = cached
        if now - ts < _FORCE_SUB_CACHE_TTL:
            return is_subscribed

    try:
        if norm.lstrip('-').isdigit():
            target = int(norm)
        else:
            target = f"@{norm}"
        member = await bot.get_chat_member(target, user_id)
        is_subscribed = member.status in ('member', 'administrator', 'creator')
        _force_sub_cache_set(cache_key, (now, is_subscribed))
        return is_subscribed
    except Exception as e:
        logger.debug(f"⚠️ get_chat_member فشل ({norm}): {e}")
        return _FORCE_SUB_FAILS_OPEN


def _invalidate_force_sub_cache(user_id: int = None):
    if user_id is None:
        _force_sub_cache.clear()
        _force_channel_cache.clear()
    else:
        keys_to_del = [k for k in _force_sub_cache if k[0] == user_id]
        for k in keys_to_del:
            _force_sub_cache.pop(k, None)


# ═══════════════════════════════════════════════════════════════════
# ✅ F1: مُرسِل التقرير المُقسَّم (strip HTML عند fallback)
# ═══════════════════════════════════════════════════════════════════

async def _send_long_report(
    context,
    chat_id: int,
    text: str,
    parse_mode: Optional[str] = 'HTML',
    limit: int = TELEGRAM_MESSAGE_LIMIT,
    split_delay: float = DB_DIAG_SPLIT_DELAY,
) -> int:
    """
    ✅ F1: عند fallback بدون parse_mode، يُرسل النص مع إزالة وسوم HTML
    من body (كانت <b>...</b> تظهر حرفياً).
    """
    if not text:
        return 0

    safe_limit = max(1, limit - 200)

    # مسار النص القصير
    if len(text) <= safe_limit:
        msg = await _safe_send_message(
            context.bot, chat_id, text, parse_mode=parse_mode,
        )
        if msg:
            return 1
        if parse_mode:
            # ✅ F1: strip HTML في الـfallback
            plain_text = _strip_html_tags(text)
            msg = await _safe_send_message(
                context.bot, chat_id, plain_text, parse_mode=None,
            )
            if msg:
                return 1
        return 0

    parts = _split_text_for_telegram(text, limit=limit)
    total = len(parts)
    sent = 0

    for i, part in enumerate(parts, 1):
        html_header = f"<i>({i}/{total})</i>\n"
        plain_header = f"({i}/{total})\n"

        body = part
        # ✅ F1: القطع بأمان (لا يقطع وسماً مفتوحاً)
        max_body_len = limit - len(html_header) - 10
        if len(body) > max_body_len:
            cut = max_body_len
            unclosed = _find_last_unclosed_lt(body[:cut])
            if unclosed > 0:
                cut = unclosed
            body = body[:cut].rstrip()

        html_full = f"{html_header}{body}"
        # ✅ F1: rebuild plain_full بدون وسوم HTML
        plain_body = _strip_html_tags(body)
        plain_full = f"{plain_header}{plain_body}"

        msg = await _safe_send_message(
            context.bot, chat_id, html_full, parse_mode=parse_mode,
        )
        if msg:
            sent += 1
        elif parse_mode:
            # ✅ F1: plain_full نظيف
            msg = await _safe_send_message(
                context.bot, chat_id, plain_full, parse_mode=None,
            )
            if msg:
                sent += 1

        if i < total:
            await asyncio.sleep(split_delay)

    return sent


def _split_text_for_telegram(
    text: str,
    limit: int = TELEGRAM_MESSAGE_LIMIT,
) -> List[str]:
    """
    يقسم نصاً طويلاً (HTML-aware).
    ✅ F4: يستخدم _find_last_unclosed_lt (regex للوسوم الفعلية).
    """
    if not text:
        return [""]

    if len(text) <= limit:
        return [text]

    safe_limit = max(1, limit - 200)

    parts: List[str] = []
    remaining = text

    while len(remaining) > safe_limit:
        cut = remaining.rfind("\n", 0, safe_limit)
        if cut < safe_limit // 2:
            cut = remaining.rfind(" ", 0, safe_limit)
        if cut < safe_limit // 2:
            cut = safe_limit

        # ✅ F4: إن كان القطع داخل وسم HTML مفتوح، ارجع لبدايته
        head = remaining[:cut]
        last_unclosed = _find_last_unclosed_lt(head)
        if last_unclosed > 0:
            # ✅ F4: حد أدنى معقول (10% من safe_limit)
            min_acceptable = max(50, safe_limit // 10)
            if last_unclosed >= min_acceptable:
                cut = last_unclosed
            # لو الوسم قريب جداً من البداية، نقبل القطع
            # (سيعالجه fallback في _send_long_report)

        part = remaining[:cut].rstrip()
        if part:
            parts.append(part)
        remaining = remaining[cut:].lstrip("\n")

    if remaining:
        parts.append(remaining.rstrip())

    return parts or [text]


# ═══════════════════════════════════════════════════════════════════
# ✅ R6: مساعد قطع نص الزر
# ═══════════════════════════════════════════════════════════════════

_ZWJ = '\u200d'
_EMOJI_MODIFIERS = frozenset((
    '\ufe0f', '\ufe0e',
    '\U0001f3fb', '\U0001f3fc', '\U0001f3fd',
    '\U0001f3fe', '\U0001f3ff',
))


def _safe_truncate_button_title(
    raw_title: str,
    join_text: str,
    max_len: int = TELEGRAM_BUTTON_TEXT_LIMIT,
) -> str:
    """
    ✅ R6: قطع آمن — يضمن len(button_label) ≤ max_len.
    """
    if not raw_title:
        return ""

    reserved = len(join_text) + 1
    available = max_len - reserved

    if available <= 0:
        return ""

    if len(raw_title) <= available:
        return raw_title

    cut = available
    while cut > 0:
        ch = raw_title[cut - 1]
        nxt = raw_title[cut] if cut < len(raw_title) else ''
        if ch == _ZWJ or ch in _EMOJI_MODIFIERS or nxt == _ZWJ:
            cut -= 1
        else:
            break

    if cut <= 0:
        cut = available

    return raw_title[:cut].rstrip()


# ═══════════════════════════════════════════════════════════════════
# CommandHandlers
# ═══════════════════════════════════════════════════════════════════

class CommandHandlers:

    # ═══════════════════════════════════════════════════════════════
    # start
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        username = update.effective_user.username or ""
        first_name = update.effective_user.first_name or ""

        _clear_stale_state(user_id, context)

        try:
            user_exists = await DB.fetchval(
                "SELECT 1 FROM users WHERE user_id = ?", (user_id,)
            )
            if not user_exists:
                await DB.register_user(user_id, username, first_name)
        except Exception as e:
            logger.warning(f"register_user check failed: {e}")
            try:
                await DB.register_user(user_id, username, first_name)
            except Exception:
                pass

        args = context.args or []
        if args and args[0].startswith('ref_'):
            # ✅ F8: guard ref_code فارغ
            ref_code = args[0][4:]
            if not ref_code:
                pass  # نتجاهل ref_ الفارغ
            else:
                referrer = await DB.get_user_by_referral_code(ref_code)
                if referrer and referrer != user_id and not await DB.is_user_banned(referrer):
                    existing = await DB.fetchone(
                        "SELECT 1 FROM referrals WHERE referred_id=?", (user_id,)
                    )
                    if not existing:
                        if await DB.add_referral(referrer, user_id):
                            reward = await DB.get_referral_stats(referrer)
                            try:
                                ref_lang = await _get_lang(referrer)
                                ref_msg = await _trans(
                                    'referral_notification', ref_lang,
                                    "🎁 تمت إحالة {referred}. لديك {available} يوم متاح للصرف."
                                )
                                # ✅ R1: HTML code + parse_mode
                                ref_msg = ref_msg.format(
                                    referred=f"<code>{_mask_id(user_id)}</code>",
                                    available=reward.get('available', 0)
                                )
                                await _safe_send_message(
                                    context.bot, referrer, ref_msg,
                                    parse_mode='HTML',
                                )
                            except Exception as e:
                                logger.warning(f"⚠️ فشل إرسال إشعار الإحالة: {e}")

                            try:
                                username_display = (
                                    f"@{username}" if username else "❌ لا يوجد"
                                )
                                _spawn_notify_dev_log(
                                    context,
                                    f"🔗 <b>دخول بكود إحالة</b>\n"
                                    f"━━━━━━━━━━━━━━━━━━━━\n"
                                    f"👤 <b>الاسم:</b> {escape(str(first_name or '—'))}\n"
                                    f"🔗 <b>المعرف:</b> {escape(username_display)}\n"
                                    f"🆔 <b>الرقم التعريفي:</b> <code>{user_id}</code>\n"
                                    f"━━━━━━━━━━━━━━━━━━━━\n"
                                    f"🎟️ <b>الكود:</b> <code>{escape(ref_code)}</code>\n"
                                    f"👥 <b>المُحيل:</b> <code>{referrer}</code>\n"
                                    f"🎁 <b>مكافآت المُحيل:</b> {reward.get('available', 0)} يوم\n"
                                    f"📅 <b>الوقت:</b> {TimeUtils.mecca_iso()}",
                                )
                            except Exception as e:
                                logger.warning(
                                    f"spawn notify dev log (ref) raised: {e}",
                                    exc_info=True,
                                )

        force_ch = await DB.get_force_subscribe_channel()
        if force_ch and user_id != CONFIG.PRIMARY_OWNER_ID:
            try:
                is_subscribed = await _check_force_subscription_cached(
                    context.bot, user_id, force_ch
                )
                if not is_subscribed:
                    chat = await _get_force_channel_cached(context.bot, force_ch)
                    invite_link = None
                    if chat:
                        try:
                            invite_link = await context.bot.export_chat_invite_link(chat.id)
                        except Exception:
                            pass

                    lang = await _get_lang(user_id)
                    subscribe_text = await _trans('subscribe_btn', lang, "📢 اشترك")
                    check_text = await _trans('check_sub_btn', lang, "✅ تحقق")

                    if invite_link:
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton(subscribe_text, url=invite_link),
                            InlineKeyboardButton(check_text, callback_data=CB.CHECK_SUB)
                        ]])
                    else:
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton(check_text, callback_data=CB.CHECK_SUB)
                        ]])

                    force_msg = await _trans(
                        'force_sub_message', lang,
                        "⚠️ اشترك في القناة أولاً"
                    )
                    await _safe_edit_or_send(
                        update, context, force_msg,
                        reply_markup=kb, parse_mode=None,
                    )
                    return
            except Exception as e:
                logger.error(f"❌ خطأ في التحقق من الاشتراك الإجباري: {e}")

        user_data = await user_cache.get_or_load(user_id, DB)
        lang = user_data.get('language', 'ar') or 'ar'
        channel_info = user_data.get('channel_info')
        unpublished_posts = user_data.get('unpublished_posts', 0)
        groups_count = user_data.get('groups_count', 0)
        has_sub = user_data.get('has_subscription', False)
        auto = user_data.get('auto_publish', True)
        recycle = user_data.get('auto_recycle', True)

        ch_display = await _trans('no_active_channel', lang, "لا توجد قنوات")
        if channel_info and isinstance(channel_info, dict):
            ch_name = channel_info.get('channel_name')
            if ch_name:
                # ✅ F8: escape اسم القناة (مصدره Telegram API)
                ch_display = escape(str(ch_name))

        sub_text = await _trans('subscription_active', lang, "✅ مفعل") if has_sub \
            else await _trans('subscription_inactive', lang, "❌ غير مفعل")
        auto_text = await _trans('enabled', lang, "مفعل") if auto \
            else await _trans('disabled', lang, "معطل")
        recycle_text = await _trans('enabled', lang, "مفعل") if recycle \
            else await _trans('disabled', lang, "معطل")

        kb_rows = KeyboardFactory.get_menu("main_menu", lang)
        keyboard = []
        for row in kb_rows:
            btn_row = []
            for item in row:
                if item == "admin_panel_btn":
                    if CONFIG.is_developer(user_id):
                        text_btn = KeyboardFactory.get_text("admin_panel_btn", lang) or "👑"
                        btn_row.append(InlineKeyboardButton(text_btn, callback_data=CB.ADMIN))
                else:
                    text_btn = KeyboardFactory.get_text(item, lang) or item
                    if item.endswith("_url"):
                        url = f"https://t.me/{CONFIG.BOT_USERNAME}?startgroup"
                        btn_row.append(InlineKeyboardButton(text_btn, url=url))
                    else:
                        btn_row.append(InlineKeyboardButton(text_btn, callback_data=item))
            if btn_row:
                keyboard.append(btn_row)

        if CONFIG.is_developer(user_id):
            admin_text = KeyboardFactory.get_text("admin_panel_btn", lang) or "👑"
            if not any(btn.callback_data == CB.ADMIN for row in keyboard for btn in row):
                keyboard.append([InlineKeyboardButton(admin_text, callback_data=CB.ADMIN)])

        kb = InlineKeyboardMarkup(keyboard)
        title = await get_text(
            lang, 'main_menu',
            user_name=f"<code>{user_id}</code>",
            groups_count=groups_count,
            active_channel=ch_display,
            unpublished_posts=unpublished_posts,
            auto_publish=auto_text,
            auto_recycle=recycle_text,
            subscription_status=sub_text
        )
        await _safe_edit_or_send(update, context, title, reply_markup=kb, parse_mode='HTML')

    @staticmethod
    async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        ✅ C6: try/except للترجمات.
        ✅ C3 (v7.6.4): parse_mode='HTML'.
        """
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        try:
            help_text = await _trans('help_text', lang, "❓ المساعدة")
        except Exception as e:
            logger.warning(f"help_command _trans failed: {e}")
            help_text = "❓ المساعدة"
        await _safe_edit_or_send(update, context, help_text, parse_mode='HTML')

    # ═══════════════════════════════════════════════════════════════
    # trial
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def trial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        username = update.effective_user.username or ""
        first_name = update.effective_user.first_name or ""
        lang = await _get_lang(user_id)

        if await DB.has_used_trial(user_id):
            await _safe_edit_or_send(
                update, context,
                await _trans('trial_used', lang, "❌ لقد استخدمت التجربة المجانية بالفعل."),
                parse_mode=None,
            )
            return

        days = await DB.activate_trial(user_id)
        if days > 0:
            msg = await _trans('trial_activated', lang,
                               "✅ تم تفعيل التجربة المجانية لمدة {days} يوم")
            try:
                msg = msg.format(days=days)
            except (KeyError, IndexError):
                pass
        else:
            msg = await _trans('trial_failed', lang, "❌ تعذر تفعيل التجربة")

        try:
            await DB.invalidate_subscription_cache(user_id)
        except Exception as e:
            logger.warning(f"⚠️ invalidate_subscription_cache: {e}")
        try:
            await user_cache.invalidate(user_id)
        except Exception:
            pass

        await _safe_edit_or_send(update, context, msg, parse_mode=None)

        if days > 0:
            try:
                username_display = (
                    f"@{username}" if username else "❌ لا يوجد"
                )
                _spawn_notify_dev_log(
                    context,
                    f"🎁 <b>تفعيل تجربة مجانية</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 <b>الاسم:</b> {escape(str(first_name or '—'))}\n"
                    f"🔗 <b>المعرف:</b> {escape(username_display)}\n"
                    f"🆔 <b>الرقم التعريفي:</b> <code>{user_id}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⏱️ <b>المدة:</b> {days} يوم\n"
                    f"📅 <b>الوقت:</b> {TimeUtils.mecca_iso()}",
                )
            except Exception as e:
                logger.warning(f"spawn notify dev log (trial): {e}", exc_info=True)

    @staticmethod
    async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        kb = KeyboardFactory.build("plans", lang=lang)
        await _safe_edit_or_send(
            update, context,
            await _trans('plan_selector', lang, "💎 اختر باقة:"),
            reply_markup=kb, parse_mode=None,
        )

    @staticmethod
    async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        kb = KeyboardFactory.build("support", lang=lang)
        await _safe_edit_or_send(
            update, context,
            await _trans('send_support_message', lang, "📞 أرسل رسالة الدعم"),
            reply_markup=kb, parse_mode=None,
        )

    # ═══════════════════════════════════════════════════════════════
    # developer
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def developer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        ✅ F9: escape الترجمات قبل الإدراج في HTML.
        """
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)

        dev_name = getattr(CONFIG, 'DEVELOPER_NAME', "Relax") or "Relax"
        dev_contact = getattr(CONFIG, 'DEVELOPER_CONTACT', "@RelaxMggr") or "@RelaxMggr"
        if "Reelaaax" in dev_contact or "Reelaaaxbot" in dev_contact:
            dev_contact = "@RelaxMggr"
        if not dev_name or dev_name == "developer_info":
            dev_name = "Relax"

        # ✅ F9: escape الترجمات
        title = escape(await _trans('dev_info_title', lang, "معلومات المطور"))
        name_label = escape(await _trans('dev_name_label', lang, "الاسم"))
        contact_label = escape(await _trans('dev_contact_label', lang, "التواصل"))
        bot_label = escape(await _trans('dev_bot_label', lang, "البوت"))
        home_label = await _trans('main', lang, "🏠 القائمة الرئيسية")

        text = (
            f"👨‍💻 <b>{title}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👤 <b>{name_label}:</b> {escape(str(dev_name))}\n"
            f"📞 <b>{contact_label}:</b> {escape(str(dev_contact))}\n"
            f"━━━━━━━━━━━━━━━\n\n"
            f"💡 <b>{bot_label}:</b> @{escape(str(CONFIG.BOT_USERNAME))}"
        )

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(home_label, callback_data=CB.MAIN)
        ]])

        await _safe_edit_or_send(update, context, text, reply_markup=kb, parse_mode='HTML')

    @staticmethod
    async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        ✅ F9: escape الترجمات + ضمان HTML صحيح.
        """
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            await _safe_edit_or_send(
                update, context, await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        try:
            stats_data = await DB.get_bot_stats()
            if not isinstance(stats_data, dict):
                stats_data = {}
        except Exception as e:
            logger.warning(f"get_bot_stats failed: {e}")
            stats_data = {}

        # ✅ F9: قالب الترجمة قد يحتوي HTML (مقصود).
        # نُهرّب فقط القيم المُدرَجة (وهي أرقام — آمنة تلقائياً).
        text = await _trans('stats_message', lang,
            "📊 <b>الإحصائيات</b>\n\n👥 المستخدمون: {users}\n"
            "📡 القنوات: {channels}\n👥 المجموعات: {groups}\n"
            "📝 المنشورات: {posts}\n✅ المنشورة: {published}\n"
            "💎 الاشتراكات النشطة: {active_subs}\n🎫 التذاكر: {tickets}"
        )
        try:
            text = text.format(
                users=int(stats_data.get('users', 0) or 0),
                channels=int(stats_data.get('channels', 0) or 0),
                groups=int(stats_data.get('groups', 0) or 0),
                posts=int(stats_data.get('posts', 0) or 0),
                published=int(stats_data.get('published', 0) or 0),
                active_subs=int(stats_data.get('active_subs', 0) or 0),
                tickets=int(stats_data.get('tickets', 0) or 0),
            )
        except (KeyError, IndexError, ValueError, TypeError):
            pass
        await _safe_edit_or_send(update, context, text, parse_mode='HTML')

    @staticmethod
    async def language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        ✅ R2: fallback لزر الرجوع.
        ✅ R9: available or {} دفاعي.
        ✅ F5: try/except حول get_available_languages.
        """
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)

        # ✅ F5: try/except
        try:
            available = TranslationManager.get_available_languages() or {}
        except Exception as e:
            logger.warning(f"get_available_languages failed: {e}")
            available = {}

        if not isinstance(available, dict):
            available = {}

        buttons = []
        row = []
        for code, name in available.items():
            row.append(InlineKeyboardButton(name, callback_data=f"lang_{code}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        # ✅ R2: fallback
        back_text = KeyboardFactory.get_text("back", lang) or "🔙"
        buttons.append([InlineKeyboardButton(back_text, callback_data=CB.BACK)])
        kb = InlineKeyboardMarkup(buttons)
        current_lang = await _trans('current_language', lang, "الحالية")
        choose_lang = await _trans('choose_language', lang, "🌐 اختر اللغة:")
        await _safe_edit_or_send(
            update, context, f"{choose_lang}\n\n{current_lang}: {lang}",
            reply_markup=kb, parse_mode=None,
        )

    @staticmethod
    async def replies_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        # ✅ C3 (v7.6.4): parse_mode='HTML'
        await _safe_edit_or_send(
            update, context,
            await _trans('replies_work', lang, "📚 الردود التلقائية تعمل!"),
            parse_mode='HTML',
        )

    # ═══════════════════════════════════════════════════════════════
    # contests
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def contests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        contests = await DB.get_active_contests(10)
        if not contests:
            await _safe_edit_or_send(
                update, context,
                await _trans('no_contests', lang, "📭 لا توجد مسابقات نشطة"),
                parse_mode=None,
            )
            return

        active_label = await _trans('active_contests', lang, "المسابقات النشطة")
        participants_label = await _trans('participants', lang, "المشاركون")
        join_text = await _trans('join_contest', lang, "✍️ المشاركة")

        type_name_raffle = await _trans('contest_type_raffle_name', lang,
                                        "سحب عشوائي")
        type_name_quiz = await _trans('contest_type_quiz_name', lang,
                                      "سؤال وجواب")
        q_label = await _trans('contest_question_label', lang, "❓ السؤال:")

        text = f"🏆 <b>{active_label}</b>\n\n"
        kb = []

        for c in contests:
            c_d = _row_to_dict(c)
            if not c_d:
                continue

            c_id = c_d.get('id')
            if c_id is None:
                continue

            raw_title = str(c_d.get('title') or '—')
            title_display = escape(raw_title)

            # ✅ R6: قطع آمن + ضمان الطول
            title_btn = _safe_truncate_button_title(raw_title, join_text)

            prize = escape(str(c_d.get('prize') or '—'))
            description = str(c_d.get('description') or '').strip()
            question = str(c_d.get('question') or '').strip()
            contest_type = (str(c_d.get('contest_type') or 'raffle')).lower()
            end_date = str(c_d.get('end_date') or '')
            participants = c_d.get('participants', 0)

            if contest_type == 'quiz':
                type_icon = "❓"
                type_label = type_name_quiz
            else:
                type_icon = "🎲"
                type_label = type_name_raffle

            text += f"• <b>{title_display}</b>\n"

            if description:
                if len(description) > CONTEST_DESC_DISPLAY_MAX:
                    description = description[:CONTEST_DESC_DISPLAY_MAX].rstrip() + "…"
                text += f"  📝 {escape(description)}\n"

            if contest_type == 'quiz' and question:
                if len(question) > CONTEST_QUESTION_DISPLAY_MAX:
                    question_disp = question[:CONTEST_QUESTION_DISPLAY_MAX].rstrip() + "…"
                else:
                    question_disp = question
                text += f"  {q_label} {escape(question_disp)}\n"

            text += f"  🎁 {prize}  |  {type_icon} {type_label}\n"

            if end_date:
                text += f"  📅 {escape(end_date[:16])}\n"

            text += f"  👥 {participants_label}: {participants}\n\n"

            # ✅ R6: بناء label + cap نهائي
            if title_btn:
                button_label = f"{join_text} {title_btn}"
            else:
                button_label = join_text
            # cap نهائي
            button_label = button_label[:TELEGRAM_BUTTON_TEXT_LIMIT]

            kb.append([InlineKeyboardButton(
                button_label,
                callback_data=f"{CB.CONTEST_JOIN}:{c_id}"
            )])

        back_text = KeyboardFactory.get_text("back", lang) or "🔙"
        kb.append([InlineKeyboardButton(back_text, callback_data=CB.BACK)])

        await _safe_edit_or_send(
            update, context, text,
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML'
        )

    # ═══════════════════════════════════════════════════════════════
    # mood — ✅ F10: asyncio.to_thread + escape emoji
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def mood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        args = context.args or []

        if not args:
            StateManager.set(user_id, UserState.WAIT_MOOD)
            await _safe_edit_or_send(
                update, context,
                await _trans('send_mood_text', lang, "📝 أرسل النص:"),
                parse_mode=None,
            )
            return

        text = " ".join(args)

        if analyze_sentiment is None:
            await _safe_edit_or_send(
                update, context,
                await _trans('mood_unavailable', lang,
                             "❌ خدمة تحليل المشاعر غير متاحة"),
                parse_mode=None,
            )
            return

        # ✅ F10: asyncio.to_thread (لا يُجمّد event loop)
        try:
            result = await asyncio.to_thread(analyze_sentiment, text)
        except Exception as e:
            logger.error(f"analyze_sentiment فشل: {e}", exc_info=True)
            await _safe_edit_or_send(
                update, context,
                await _trans('mood_unavailable', lang,
                             "❌ خدمة تحليل المشاعر غير متاحة"),
                parse_mode=None,
            )
            return

        if not isinstance(result, dict):
            await _safe_edit_or_send(
                update, context,
                await _trans('mood_unavailable', lang,
                             "❌ خدمة تحليل المشاعر غير متاحة"),
                parse_mode=None,
            )
            return

        mood_analysis = escape(await _trans('mood_analysis', lang, 'تحليل المشاعر'))
        mood_text_l = escape(await _trans('mood_text', lang, 'النص'))
        mood_result = escape(await _trans('mood_result', lang, 'النتيجة'))
        mood_positive = escape(await _trans('mood_positive', lang, 'إيجابي'))
        mood_negative = escape(await _trans('mood_negative', lang, 'سلبي'))
        mood_words = escape(await _trans('mood_words', lang, 'الكلمات'))

        # ✅ F10: escape emoji أيضاً (قد يكون من مصدر خارجي)
        emoji_val = escape(str(result.get('emoji', '🎭')))

        response = (
            f"{emoji_val} <b>{mood_analysis}</b>\n\n"
            f"📝 {mood_text_l}: <code>{escape(text[:100])}</code>\n"
            f"🎯 {mood_result}: <b>{escape(str(result.get('sentiment', '?')))}</b>\n\n"
            f"😊 {mood_positive}: {result.get('positive_percent', 0):.0f}%\n"
            f"😔 {mood_negative}: {result.get('negative_percent', 0):.0f}%\n"
            f"📊 {mood_words}: {result.get('total_words', 0)}"
        )
        await _safe_edit_or_send(update, context, response, parse_mode='HTML')

    @staticmethod
    async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            await _safe_edit_or_send(
                update, context, await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        admin_btn = await _trans('admin_panel_btn', lang, "👑 لوحة الأدمن")
        open_text = await _trans('open_admin_panel', lang,
                                 "👑 لوحة الأدمن\n\nاضغط الزر أدناه:")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(admin_btn, callback_data=CB.ADMIN)
        ]])
        await _safe_edit_or_send(
            update, context, open_text,
            reply_markup=kb, parse_mode='HTML',
        )

    @staticmethod
    async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        if not CONFIG.is_developer(user_id):
            await _safe_edit_or_send(
                update, context, await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        StateManager.set(user_id, UserState.WAIT_BROADCAST)
        await _safe_edit_or_send(
            update, context,
            await _trans('send_broadcast', lang, "📨 أرسل الرسالة التي تريد بثها:"),
            parse_mode=None,
        )

    @staticmethod
    async def set_force(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_FORCE)
        lang = await _get_lang(user_id)
        await _safe_edit_or_send(
            update, context,
            await _trans('send_force_ch_prompt', lang, "🔒 أرسل معرف القناة:"),
            parse_mode=None,
        )

    @staticmethod
    async def set_update_ch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_UPDATE_CH)
        lang = await _get_lang(user_id)
        await _safe_edit_or_send(
            update, context,
            await _trans('send_update_ch_prompt', lang, "📢 أرسل معرف قناة التحديثات:"),
            parse_mode=None,
        )

    @staticmethod
    async def set_log_ch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_LOG_CH)
        lang = await _get_lang(user_id)
        await _safe_edit_or_send(
            update, context,
            await _trans('send_log_ch_prompt', lang, "📋 أرسل معرف قناة السجلات:"),
            parse_mode=None,
        )

    @staticmethod
    async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_ADMIN_ADD)
        lang = await _get_lang(user_id)
        await _safe_edit_or_send(
            update, context,
            await _trans('add_admin_prompt', lang, "👑 أرسل معرف المشرف:"),
            parse_mode=None,
        )

    @staticmethod
    async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_ADMIN_REM)
        lang = await _get_lang(user_id)
        await _safe_edit_or_send(
            update, context,
            await _trans('remove_admin_prompt', lang, "🗑️ أرسل معرف المشرف:"),
            parse_mode=None,
        )

    @staticmethod
    async def export_replies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            return
        try:
            count = await export_auto_replies(-1)
        except Exception as e:
            logger.error(f"export_replies: {e}")
            count = 0
        lang = await _get_lang(user_id)
        msg = await _trans('export_success', lang, "✅ تم تصدير {count} رد")
        try:
            msg = msg.format(count=count)
        except (KeyError, IndexError):
            pass
        await _safe_edit_or_send(update, context, msg, parse_mode=None)

    @staticmethod
    async def import_replies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            return
        StateManager.set(user_id, UserState.WAIT_IMPORT_FILE)
        lang = await _get_lang(user_id)
        await _safe_edit_or_send(
            update, context,
            await _trans('send_json_prompt', lang, "📤 أرسل ملف JSON:"),
            parse_mode=None,
        )

    @staticmethod
    async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            return
        lang = await _get_lang(user_id)
        await _safe_edit_or_send(
            update, context,
            await _trans('backup_start', lang, "⏳ جارٍ النسخ الاحتياطي..."),
            parse_mode=None,
        )
        try:
            from utils import BackgroundTasks
            asyncio.create_task(BackgroundTasks._do_backup())
            await _safe_edit_or_send(
                update, context,
                await _trans('backup_done', lang, "✅ تم أخذ نسخة احتياطية"),
                parse_mode=None,
            )
        except Exception as e:
            await _safe_edit_or_send(
                update, context, f"❌ {str(e)[:50]}",
                parse_mode=None,
            )

    @staticmethod
    async def restore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            return
        lang = await _get_lang(user_id)
        try:
            backups = sorted(PATHS.BACKUPS.glob("backup_*.db"),
                             key=_safe_mtime, reverse=True)
            if not backups:
                await _safe_edit_or_send(
                    update, context,
                    await _trans('no_backups_full', lang, "📭 لا توجد نسخ"),
                    parse_mode=None,
                )
                return
            back_label = KeyboardFactory.get_text("back", lang) or "🔙"
            kb = []
            for b in backups[:10]:
                fname = b.name
                kb.append([InlineKeyboardButton(
                    f"📁 {fname}",
                    callback_data=f"admin_restore_file:{fname}"
                )])
            kb.append([InlineKeyboardButton(back_label, callback_data=CB.ADMIN)])
            await _safe_edit_or_send(
                update, context,
                await _trans('choose_backup_restore_btn', lang,
                             "📂 اختر نسخة احتياطية للاستعادة:"),
                reply_markup=InlineKeyboardMarkup(kb), parse_mode=None,
            )
        except Exception as e:
            logger.error(f"restore: {e}", exc_info=True)
            await _safe_edit_or_send(
                update, context,
                await _trans('error_occurred', lang, "❌ حدث خطأ"),
                parse_mode=None,
            )

    @staticmethod
    async def auto_publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        cur = await DB.get_auto_publish_status(user_id)
        await DB.set_auto_publish(user_id, not cur)
        status = await _trans('enabled', lang, "مفعل") if not cur \
            else await _trans('disabled', lang, "معطل")
        msg = await _trans('auto_publish_toggle', lang, "✅ النشر التلقائي: {status}")
        try:
            msg = msg.format(status=status)
        except (KeyError, IndexError):
            pass
        await _safe_edit_or_send(update, context, msg, parse_mode=None)
        await user_cache.invalidate(user_id)

    @staticmethod
    async def auto_recycle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        cur = await DB.get_auto_recycle_status(user_id)
        await DB.set_auto_recycle(user_id, not cur)
        status = await _trans('enabled', lang, "مفعل") if not cur \
            else await _trans('disabled', lang, "معطل")
        msg = await _trans('auto_recycle_toggle', lang, "✅ التدوير التلقائي: {status}")
        try:
            msg = msg.format(status=status)
        except (KeyError, IndexError):
            pass
        await _safe_edit_or_send(update, context, msg, parse_mode=None)
        await user_cache.invalidate(user_id)

    @staticmethod
    async def channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        channels = await DB.get_user_channels(user_id)
        if not channels:
            await _safe_edit_or_send(
                update, context,
                await _trans('no_channels', lang, "📭 لا توجد قنوات"),
                parse_mode=None,
            )
            return
        title = await _trans('your_channels', lang, "📡 قنواتك:")
        text = f"{title}\n\n"
        for ch in channels:
            ch_d = _row_to_dict(ch)
            name = _get_field(ch_d, 'channel_name', '?')
            ch_id = _get_field(ch_d, 'channel_id', '?')
            text += f"• {escape(str(name))} (<code>{escape(str(ch_id))}</code>)\n"
        await _safe_edit_or_send(update, context, text, parse_mode='HTML')

    @staticmethod
    async def posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        active = await DB.get_active_channel(user_id)
        if not active:
            await _safe_edit_or_send(
                update, context,
                await _trans('no_active_channel', lang, "❌ لا توجد قناة نشطة"),
                parse_mode=None,
            )
            return
        posts = await DB.get_user_posts(user_id, active, 10)
        if not posts:
            await _safe_edit_or_send(
                update, context,
                await _trans('no_posts', lang, "📭 لا توجد منشورات"),
                parse_mode=None,
            )
            return
        title = await _trans('your_posts', lang, "📋 منشوراتك:")
        text = f"{title}\n\n"
        for p in posts:
            p_d = _row_to_dict(p)
            pid = _get_field(p_d, 'id', '?')
            ptext = _get_field(p_d, 'text', '') or ''
            text += f"• <code>{escape(str(pid))}</code>: {escape(str(ptext)[:30])}\n"
        await _safe_edit_or_send(update, context, text, parse_mode='HTML')

    # ═══════════════════════════════════════════════════════════════
    # أوامر المجموعات
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def security(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            lang = await _get_lang(user_id)
            await _safe_edit_or_send(
                update, context,
                await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        context.user_data['security_chat_id'] = chat_id
        settings = await DB.get_security_settings(chat_id)
        if not isinstance(settings, dict):
            settings = _row_to_dict(settings)
        lang = await _get_lang(user_id)
        try:
            text = KeyboardFactory._format_security_text(settings, {}, lang=lang)
        except TypeError:
            text = KeyboardFactory._format_security_text(settings)
        kb = KeyboardFactory.build("security", chat_id=chat_id, lang=lang)
        await _safe_edit_or_send(update, context, text,
                                 reply_markup=kb, parse_mode='HTML')

    @staticmethod
    async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            lang = await _get_lang(user_id)
            await _safe_edit_or_send(
                update, context,
                await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        lang = await _get_lang(user_id)
        kb = KeyboardFactory.build("panel", chat_id=chat_id, lang=lang)
        await _safe_edit_or_send(
            update, context,
            await _trans('group_panel', lang, "📋 لوحة تحكم المجموعة"),
            reply_markup=kb, parse_mode=None,
        )

    @staticmethod
    async def lock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            return
        await DB.execute(
            "INSERT OR REPLACE INTO chat_locks "
            "(chat_id, locked, locked_at, locked_by) VALUES (?,1,?,?)",
            (chat_id, TimeUtils.sql_iso(), user_id),
        )
        lang = await _get_lang(user_id)
        await _safe_edit_or_send(
            update, context,
            await _trans('group_locked_full', lang, "🔒 تم القفل"),
            parse_mode=None,
        )

    @staticmethod
    async def unlock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            return
        await DB.execute("DELETE FROM chat_locks WHERE chat_id=?", (chat_id,))
        lang = await _get_lang(user_id)
        await _safe_edit_or_send(
            update, context,
            await _trans('group_unlocked_full', lang, "🔓 تم الفتح"),
            parse_mode=None,
        )

    @staticmethod
    async def register_hidden_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if user_id != CONFIG.PRIMARY_OWNER_ID:
            return
        if not context.args:
            await _safe_edit_or_send(update, context,
                                     "📝 /register_hidden_owner <user_id>",
                                     parse_mode=None)
            return
        try:
            owner_id = int(context.args[0])
            if owner_id <= 0:
                raise ValueError
        except (ValueError, TypeError):
            await _safe_edit_or_send(update, context,
                                     "⚠️ معرف غير صالح", parse_mode=None)
            return
        chat_id = update.effective_chat.id
        await DB.execute(
            "INSERT OR IGNORE INTO hidden_owner_groups "
            "(chat_id, owner_id, is_hidden) VALUES (?,?,1)",
            (chat_id, owner_id),
        )
        invalidate_auth_cache(chat_id, owner_id)
        await _safe_edit_or_send(
            update, context,
            f"✅ تم تسجيل <code>{owner_id}</code> كمالك مخفي",
            parse_mode='HTML',
        )

    @staticmethod
    async def remove_hidden_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if user_id != CONFIG.PRIMARY_OWNER_ID:
            return
        if not context.args:
            return
        try:
            owner_id = int(context.args[0])
        except (ValueError, TypeError):
            return
        chat_id = update.effective_chat.id
        await DB.execute("DELETE FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?",
                         (chat_id, owner_id))
        invalidate_auth_cache(chat_id, owner_id)
        await _safe_edit_or_send(update, context,
                                 f"✅ تم إزالة <code>{owner_id}</code>",
                                 parse_mode='HTML')

    @staticmethod
    async def add_hidden_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_owner = user_id == CONFIG.PRIMARY_OWNER_ID
        if not is_owner:
            row = await DB.fetchone(
                "SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?",
                (chat_id, user_id))
            is_owner = row is not None
        if not is_owner:
            return
        if not context.args:
            return
        try:
            admin_id = int(context.args[0])
            if admin_id <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return
        await DB.add_hidden_admin(chat_id, admin_id, user_id)
        invalidate_auth_cache(chat_id, admin_id)
        await _safe_edit_or_send(
            update, context,
            f"✅ تم إضافة <code>{admin_id}</code> كمشرف مخفي",
            parse_mode='HTML',
        )

    @staticmethod
    async def remove_hidden_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_owner = user_id == CONFIG.PRIMARY_OWNER_ID
        if not is_owner:
            row = await DB.fetchone(
                "SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?",
                (chat_id, user_id))
            is_owner = row is not None
        if not is_owner:
            return
        if not context.args:
            return
        try:
            admin_id = int(context.args[0])
        except (ValueError, TypeError):
            return
        await DB.execute("DELETE FROM hidden_admins WHERE chat_id=? AND admin_id=?",
                         (chat_id, admin_id))
        invalidate_auth_cache(chat_id, admin_id)
        await _safe_edit_or_send(update, context,
                                 f"✅ تم إزالة <code>{admin_id}</code>",
                                 parse_mode='HTML')

    @staticmethod
    async def list_hidden_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        is_owner = user_id == CONFIG.PRIMARY_OWNER_ID
        if not is_owner:
            row = await DB.fetchone(
                "SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?",
                (chat_id, user_id))
            is_owner = row is not None
        if not is_owner:
            return
        owners = await DB.fetchall(
            "SELECT owner_id FROM hidden_owner_groups WHERE chat_id=?", (chat_id,))
        admins = await DB.fetchall(
            "SELECT admin_id FROM hidden_admins WHERE chat_id=?", (chat_id,))
        anonymous_admins = await DB.fetchall(
            "SELECT anonymous_id, user_id FROM anonymous_admins WHERE chat_id=?",
            (chat_id,)
        )
        text = "👤 <b>المخفيون</b>\n"
        for o in owners:
            o_d = _row_to_dict(o)
            text += f"👑 <code>{o_d.get('owner_id', '?')}</code>\n"
        for a in admins:
            a_d = _row_to_dict(a)
            text += f"🛡️ <code>{a_d.get('admin_id', '?')}</code>\n"
        for a in anonymous_admins:
            a_d = _row_to_dict(a)
            anon_id = a_d.get('anonymous_id')
            if anon_id in _BOT_SENDER_IDS:
                continue
            real = f"<code>{a_d.get('user_id')}</code>" if a_d.get('user_id') else "غير معروف"
            text += f"🕵️ مجهول: <code>{anon_id or '?'}</code> (حقيقي: {real})\n"
        if not (owners or admins or anonymous_admins):
            text = "📭 لا يوجد"
        await _safe_edit_or_send(update, context, text, parse_mode='HTML')

    @staticmethod
    async def syncgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        ✅ F11: perms.get('can_act', False).
        """
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return

        chat_id = update.effective_chat.id
        chat_name = update.effective_chat.title or "بدون اسم"
        user_id = update.effective_user.id
        is_anon = _is_anonymous_sender(update)

        try:
            perms = await check_bot_permissions(context.bot, chat_id)
            # ✅ F11: .get() بدل [] للاتساق
            if not perms.get('can_act', False):
                await _safe_edit_or_send(
                    update, context,
                    "❌ <b>البوت لا يملك الصلاحيات الكافية!</b>\n\n"
                    "يجب أن يكون البوت مشرفاً مع صلاحية حذف الرسائل وتقييد الأعضاء.",
                    parse_mode='HTML',
                )
                return
        except Exception as e:
            await _safe_edit_or_send(update, context, f"❌ {escape(str(e)[:50])}",
                                     parse_mode=None)
            return

        try:
            all_admins = await context.bot.get_chat_administrators(chat_id)
        except Exception:
            await _safe_edit_or_send(update, context, "❌ فشل جلب المشرفين",
                                     parse_mode=None)
            return

        creator_id = None
        for admin in all_admins:
            if admin.status == 'creator' and not admin.user.is_bot:
                creator_id = admin.user.id
                break

        is_admin = False
        real_user_id = user_id

        if (update.message and update.message.sender_chat
                and update.message.sender_chat.id == chat_id):
            is_admin = True
            real_user_id = creator_id if creator_id else user_id
        elif is_anon:
            is_admin = True
            real_user_id = creator_id if creator_id else user_id
        else:
            for admin in all_admins:
                if admin.user.id == user_id:
                    is_admin = True
                    real_user_id = admin.user.id
                    break

        if not is_admin:
            await _safe_edit_or_send(
                update, context,
                "❌ <b>أنت لست مشرفاً في هذه المجموعة!</b>",
                parse_mode='HTML',
            )
            return

        try:
            await DB.register_group(
                chat_id, chat_name, creator_id or real_user_id,
                update.effective_chat.username,
            )
        except Exception:
            await _safe_edit_or_send(update, context, "❌ فشل تسجيل المجموعة",
                                     parse_mode=None)
            return

        try:
            if creator_id:
                await DB.execute(
                    "INSERT OR REPLACE INTO hidden_owner_groups "
                    "(chat_id, owner_id, is_hidden) VALUES (?,?,0)",
                    (chat_id, creator_id),
                )
                await DB.execute(
                    "INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?,?)",
                    (creator_id, chat_id),
                )
                invalidate_auth_cache(chat_id, creator_id)

            if real_user_id and real_user_id > 0:
                await DB.execute(
                    "INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?,?)",
                    (real_user_id, chat_id),
                )
                invalidate_auth_cache(chat_id, real_user_id)
        except Exception as e:
            logger.error(f"❌ فشل ربط المستخدم: {e}")

        try:
            admin_ids = [
                a.user.id for a in all_admins
                if a.user and not a.user.is_bot and a.user.id != chat_id
            ]
            admin_count = await DB.sync_group_admins(chat_id, admin_ids)
        except Exception:
            admin_count = 0

        anonymous_ids = []
        user_id_map = {}
        for admin in all_admins:
            if admin.user.is_bot and admin.status == 'administrator':
                anon_id = admin.user.id
                if anon_id in _BOT_SENDER_IDS:
                    continue
                anonymous_ids.append(anon_id)
                row = await DB.fetchone(
                    "SELECT user_id FROM anonymous_admins "
                    "WHERE chat_id=? AND anonymous_id=?",
                    (chat_id, anon_id),
                )
                if row:
                    row_d = _row_to_dict(row)
                    if row_d.get('user_id'):
                        user_id_map[anon_id] = row_d['user_id']

        if anonymous_ids:
            try:
                await DB.sync_anonymous_admins(
                    chat_id, anonymous_ids,
                    added_by=real_user_id, user_id_map=user_id_map,
                )
                for anon_id, real_id in user_id_map.items():
                    if real_id and real_id > 0:
                        await DB.execute(
                            "INSERT OR IGNORE INTO user_groups_link "
                            "(user_id, chat_id) VALUES (?,?)",
                            (real_id, chat_id),
                        )
            except Exception as e:
                logger.error(f"❌ فشل sync_anonymous_admins: {e}")

        msg = (
            f"🎉 <b>تم تفعيل المجموعة بنجاح!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>المجموعة:</b> {escape(chat_name)}\n"
            f"🆔 <b>المعرف:</b> <code>{chat_id}</code>\n"
        )
        if creator_id:
            msg += f"👑 <b>المالك:</b> <code>{creator_id}</code>\n"
        msg += f"👤 <b>مشرف:</b> <code>{real_user_id}</code>\n"
        msg += f"👥 <b>المشرفون:</b> {admin_count}\n"
        if anonymous_ids:
            msg += f"🕵️ <b>المشرفون المجهولون:</b> {len(anonymous_ids)}\n"
        msg += (
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>الحماية:</b> مفعّلة\n"
            f"💡 استخدم /security للإعدادات"
        )

        await _send_and_auto_delete(
            context, chat_id=chat_id, text=msg, parse_mode='HTML', delay=10,
        )

    # ═══════════════════════════════════════════════════════════════
    # أوامر الإشراف
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await CommandHandlers._moderation_command(update, context, "ban")

    @staticmethod
    async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await CommandHandlers._moderation_command(update, context, "mute")

    @staticmethod
    async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await CommandHandlers._moderation_command(update, context, "warn")

    @staticmethod
    async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await CommandHandlers._moderation_command(update, context, "kick")

    @staticmethod
    async def restrict(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await CommandHandlers._moderation_command(update, context, "restrict")

    @staticmethod
    async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await CommandHandlers._moderation_command(update, context, "unban")

    @staticmethod
    async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            return
        if update.message and update.message.reply_to_message:
            perms = await check_bot_permissions(context.bot, chat_id)
            if not perms.get('can_pin', False):
                await _safe_edit_or_send(
                    update, context,
                    "❌ البوت لا يملك صلاحية تثبيت الرسائل.",
                    parse_mode=None,
                )
                return
            try:
                await context.bot.pin_chat_message(
                    chat_id, update.message.reply_to_message.message_id)
                await _safe_edit_or_send(update, context,
                                         "📌 تم التثبيت", parse_mode=None)
            except Exception as e:
                logger.error(f"❌ فشل التثبيت: {e}")

    @staticmethod
    async def _moderation_command(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   action: str) -> None:
        if not update.effective_chat or update.effective_chat.type not in ['group', 'supergroup']:
            return
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        # ✅ M3: فحص الصلاحية أولاً
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            lang = await _get_lang(user_id)
            await _safe_edit_or_send(
                update, context,
                await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return

        lang = await _get_lang(user_id)

        perms = await check_bot_permissions(context.bot, chat_id)
        if not perms.get('can_act', False):
            await _safe_edit_or_send(
                update, context,
                "❌ البوت لا يملك الصلاحيات الكافية.",
                parse_mode=None,
            )
            return
        args = context.args or []
        if not args:
            usage = await _trans('moderation_usage', lang,
                                 "📝 /{action} معرف_المستخدم [مدة_بالدقائق]")
            try:
                usage = usage.replace("{action}", action)
            except Exception:
                pass
            await _safe_edit_or_send(update, context, usage, parse_mode=None)
            return
        try:
            target = int(args[0])
            if target <= 0:
                raise ValueError
        except (ValueError, TypeError):
            await _safe_edit_or_send(
                update, context,
                await _trans('invalid_id', lang, "❌ معرف غير صالح"),
                parse_mode=None,
            )
            return
        if await is_authorized_in_group(context.bot, chat_id, target):
            await _safe_edit_or_send(
                update, context,
                await _trans('cant_moderate_admin', lang, "❌ لا يمكن معاملة مشرف"),
                parse_mode=None,
            )
            return

        default_durations = {'ban': 0, 'mute': 3600, 'restrict': 1800,
                             'warn': 0, 'kick': 0}
        duration_seconds = default_durations.get(action, 60)
        reason_parts = []
        if len(args) > 1:
            try:
                minutes = int(args[1])
                if minutes > 0:
                    duration_seconds = minutes * 60
                    reason_parts = args[2:]
                else:
                    reason_parts = args[1:]
            except ValueError:
                reason_parts = args[1:]
        reason = " ".join(reason_parts)

        if action == 'unban':
            try:
                await context.bot.unban_chat_member(chat_id, target)
                await DB.remove_penalties_for_user(target, chat_id, penalty_type='ban')
                await _safe_edit_or_send(
                    update, context,
                    await _trans('unbanned_success', lang, "✅ تم إلغاء الحظر"),
                    parse_mode=None,
                )
            except Exception as e:
                await _safe_edit_or_send(
                    update, context, f"❌ {escape(str(e)[:50])}",
                    parse_mode=None,
                )
            return

        success, msg = await apply_penalty(
            context.bot, chat_id, target, action,
            duration_seconds, reason, user_id,
            lang=lang,
        )
        await _safe_edit_or_send(update, context, msg, parse_mode='HTML')
        if success:
            try:
                await invalidate_auth_cache(chat_id=chat_id, user_id=target)
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════════
    # أوامر المطور
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def set_min_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            lang = await _get_lang(user_id)
            await _safe_edit_or_send(
                update, context,
                await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        args = context.args or []
        if not args:
            await _safe_edit_or_send(
                update, context,
                "📝 /set_min_interval <دقائق>",
                parse_mode=None,
            )
            return
        try:
            val = int(args[0])
            if val < 1:
                await _safe_edit_or_send(
                    update, context,
                    "❌ الحد الأدنى يجب أن يكون 1 دقيقة",
                    parse_mode=None,
                )
                return
            await DB.set_setting('min_publish_interval', str(val))
            await _safe_edit_or_send(
                update, context,
                f"✅ تم تعيين الحد الأدنى إلى {val} دقيقة",
                parse_mode=None,
            )
        except ValueError:
            await _safe_edit_or_send(update, context,
                                     "❌ قيمة غير صالحة", parse_mode=None)

    @staticmethod
    async def grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            lang = await _get_lang(user_id)
            await _safe_edit_or_send(
                update, context,
                await _trans('unauthorized', lang, "❌ غير مصرح"),
                parse_mode=None,
            )
            return
        args = context.args or []
        if len(args) < 2:
            await _safe_edit_or_send(
                update, context,
                "📝 /grant <user_id> <days>",
                parse_mode=None,
            )
            return
        try:
            target_id = int(args[0])
            days = int(args[1])
            if target_id <= 0 or days < 1 or days > 365:
                raise ValueError
        except (ValueError, TypeError):
            await _safe_edit_or_send(update, context,
                                     "❌ قيم غير صالحة", parse_mode=None)
            return
        user_row = await DB.fetchone(
            "SELECT user_id FROM users WHERE user_id=?", (target_id,))
        if not user_row:
            await _safe_edit_or_send(
                update, context,
                "❌ المستخدم غير موجود",
                parse_mode=None,
            )
            return
        plan_row = await DB.fetchone("SELECT id FROM plans WHERE is_gift=1 LIMIT 1")
        if not plan_row:
            plan_row = await DB.fetchone(
                "SELECT id FROM plans WHERE is_active=1 AND is_gift=0 LIMIT 1"
            )
        plan_row_d = _row_to_dict(plan_row)
        plan_id = plan_row_d.get('id') if plan_row_d else None
        if plan_id is None:
            await _safe_edit_or_send(update, context,
                                     "❌ لا توجد خطط", parse_mode=None)
            return
        success = await DB.grant_subscription_days(
            target_id, days, plan_id=plan_id, provider='manual'
        )
        if success:
            try:
                await DB.invalidate_subscription_cache(target_id)
            except Exception:
                pass
            lang = await _get_lang(user_id)
            msg = await _trans('grant_success_with_id', lang,
                               "✅ تم منح {days} يوم للمستخدم <code>{user_id}</code>")
            try:
                msg = msg.format(days=days, user_id=_mask_id(target_id))
            except (KeyError, IndexError):
                pass
            await _safe_edit_or_send(update, context, msg, parse_mode='HTML')
            await user_cache.invalidate(target_id)

            try:
                _spawn_notify_dev_log(
                    context,
                    f"🎁 <b>منح اشتراك يدوي</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 <b>المستلم:</b> <code>{target_id}</code>\n"
                    f"🛡️ <b>المُنِح:</b> <code>{user_id}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⏱️ <b>المدة:</b> {days} يوم\n"
                    f"📅 <b>الوقت:</b> {TimeUtils.mecca_iso()}",
                )
            except Exception as e:
                logger.warning(f"spawn notify dev log (grant): {e}", exc_info=True)
        else:
            lang = await _get_lang(user_id)
            await _safe_edit_or_send(
                update, context,
                await _trans('grant_failed', lang, "❌ فشل المنح"),
                parse_mode=None,
            )

    @staticmethod
    async def gift_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        plans = await DB.get_gift_plans()
        if not plans:
            await _safe_edit_or_send(
                update, context,
                await _trans('no_gift_plans', lang, "📭 لا توجد خطط هدايا"),
                parse_mode=None,
            )
            return
        kb = []
        for plan in plans:
            p_d = _row_to_dict(plan)
            p_id = p_d.get('id')
            p_days = p_d.get('days', '?')
            p_price = p_d.get('price', '?')
            if p_id is None:
                continue
            kb.append([InlineKeyboardButton(
                f"🎁 {p_days} يوم - {p_price} ⭐",
                callback_data=f"buy_gift:{p_id}"
            )])
        back_text = KeyboardFactory.get_text("back", lang) or "🔙"
        kb.append([InlineKeyboardButton(back_text, callback_data=CB.BACK)])
        await _safe_edit_or_send(
            update, context,
            await _trans('gift_plans_text', lang, "💎 اختر خطة هدية:"),
            reply_markup=InlineKeyboardMarkup(kb), parse_mode=None,
        )

    # ═══════════════════════════════════════════════════════════════
    # redeem_gift — ✅ F2: معالجة (True, 0)
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def redeem_gift(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        دلالة القيم المُعادة من DB.redeem_gift_code:
          (True, days>0) → ✅ نجاح كامل
          (True, 0)      → ✅ نجاح بدون أيام (نادر) — F2
          (False, -1)    → ⚠️ محاولة استخدام كود المستخدم نفسه
          (False, 0)     → ❌ كود غير صالح / منتهي / مستخدم سابقاً
        """
        user_id = update.effective_user.id
        lang = await _get_lang(user_id)
        args = context.args or []
        if not args:
            await _safe_edit_or_send(
                update, context,
                await _trans('send_code', lang,
                             "📝 أرسل الكود: /redeem_gift <الكود>"),
                parse_mode=None,
            )
            return
        code = args[0].strip()
        if len(code) < 4 or len(code) > 50:
            await _safe_edit_or_send(
                update, context,
                await _trans('invalid_code', lang, "❌ كود غير صالح"),
                parse_mode=None,
            )
            return
        result = await DB.redeem_gift_code(user_id, code)
        if isinstance(result, tuple):
            success, days = result
        else:
            success, days = (bool(result), 0)

        if success and days > 0:
            # ═══ نجاح كامل ═══
            try:
                await DB.invalidate_subscription_cache(user_id)
            except Exception:
                pass
            msg = await _trans('gift_redeemed', lang,
                               "🎉 تم تفعيل اشتراك {days} يوم")
            try:
                msg = msg.format(days=days)
            except (KeyError, IndexError):
                pass
            await _safe_edit_or_send(update, context, msg, parse_mode=None)
            await user_cache.invalidate(user_id)

            try:
                uname = update.effective_user.username or ""
                fname = update.effective_user.first_name or ""
                username_display = f"@{uname}" if uname else "❌ لا يوجد"
                _spawn_notify_dev_log(
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
                logger.warning(f"spawn notify dev log (gift): {e}", exc_info=True)

        elif success and days == 0:
            # ✅ F2: نجاح بدون أيام (نادر)
            try:
                await DB.invalidate_subscription_cache(user_id)
            except Exception:
                pass
            msg = await _trans('gift_redeemed_no_days', lang,
                               "✅ تم قبول الكود (بدون أيام مضافة)")
            await _safe_edit_or_send(update, context, msg, parse_mode=None)
            try:
                await user_cache.invalidate(user_id)
            except Exception:
                pass
            logger.info(
                f"redeem_gift: (True, 0) — user={user_id}, code={code[:6]}..."
            )

        elif days == -1:
            # ⚠️ محاولة استخدام كود المستخدم نفسه
            await _safe_edit_or_send(
                update, context,
                await _trans('own_code', lang, "❌ لا يمكنك استخدام كودك الخاص"),
                parse_mode=None,
            )
        else:
            # ❌ فشل عام
            await _safe_edit_or_send(
                update, context,
                await _trans('invalid_code', lang, "❌ كود غير صالح"),
                parse_mode=None,
            )

    # ═══════════════════════════════════════════════════════════════
    # db_diag — ✅ F12: توحيد وجهة الرسائل
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def db_diag(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """✅ /db_diag — تشخيص قاعدة البيانات."""
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            return

        # ✅ F12: وجهة موحّدة للرسائل
        target_chat = _resolve_target_id(update, context, prefer_chat=True)
        if target_chat is None:
            return

        await _safe_edit_or_send(
            update, context,
            "⏳ <b>جاري التشخيص...</b>\n\n"
            "<i>قد يستغرق 5-10 ثواني</i>",
            parse_mode='HTML',
        )

        try:
            from db_diagnostics import diagnose_db_split
            _has_split = True
        except (ImportError, AttributeError):
            diagnose_db_split = None
            _has_split = False

        if _has_split:
            try:
                parts = await diagnose_db_split()
                if not parts:
                    await _safe_send_message(
                        context.bot, target_chat,
                        "⚠️ التقرير فارغ.",
                    )
                    return

                merged = "\n\n".join(parts)
                sent = await _send_long_report(
                    context, target_chat, merged,
                    parse_mode='HTML',
                    limit=TELEGRAM_MESSAGE_LIMIT,
                    split_delay=DB_DIAG_SPLIT_DELAY,
                )
                if sent == 0:
                    await _safe_send_message(
                        context.bot, target_chat,
                        "⚠️ فشل إرسال التقرير.",
                    )
                logger.info(f"✅ db_diag split: أُرسِلت {sent} جزء")
                return

            except Exception as e:
                logger.error(
                    f"db_diag split فشل، fallback: {e}",
                    exc_info=True,
                )

        try:
            from db_diagnostics import diagnose_db
        except ImportError:
            await _safe_send_message(
                context.bot, target_chat,
                "❌ ملف <code>db_diagnostics.py</code> غير موجود في المشروع",
                parse_mode='HTML',
            )
            return

        try:
            result = await diagnose_db()
        except Exception as e:
            logger.error(f"db_diag: {e}", exc_info=True)
            await _safe_send_message(
                context.bot, target_chat,
                f"❌ فشل التشخيص: <code>{escape(str(e)[:200])}</code>",
                parse_mode='HTML',
            )
            return

        try:
            sent = await _send_long_report(
                context, target_chat, result,
                parse_mode='HTML',
                limit=TELEGRAM_MESSAGE_LIMIT,
                split_delay=DB_DIAG_SPLIT_DELAY,
            )
            if sent == 0:
                await _safe_send_message(
                    context.bot, target_chat,
                    "⚠️ فشل إرسال التقرير.",
                )
        except Exception as e:
            logger.error(f"db_diag send: {e}", exc_info=True)
            await _safe_send_message(
                context.bot, target_chat,
                f"❌ فشل الإرسال: <code>{escape(str(e)[:150])}</code>",
                parse_mode='HTML',
            )

    # ═══════════════════════════════════════════════════════════════
    # db_vacuum — ✅ F12: توحيد وجهة الرسائل
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    async def db_vacuum(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """✅ /db_vacuum — VACUUM ANALYZE."""
        user_id = update.effective_user.id
        if not CONFIG.is_developer(user_id):
            return

        # ✅ F12: وجهة موحّدة
        target_chat = _resolve_target_id(update, context, prefer_chat=True)
        if target_chat is None:
            return

        await _safe_edit_or_send(
            update, context,
            "⏳ <b>جاري تنظيف قاعدة البيانات...</b>\n\n"
            "<i>قد يستغرق 30-60 ثانية. البوت سيبقى مستجيباً.</i>",
            parse_mode='HTML',
        )

        try:
            from db_diagnostics import vacuum_analyze_tables
        except ImportError:
            await _safe_send_message(
                context.bot, target_chat,
                "❌ ملف <code>db_diagnostics.py</code> غير موجود",
                parse_mode='HTML',
            )
            return

        try:
            result = await vacuum_analyze_tables()
        except Exception as e:
            logger.error(f"db_vacuum: {e}", exc_info=True)
            await _safe_send_message(
                context.bot, target_chat,
                f"❌ فشل التنظيف: <code>{escape(str(e)[:200])}</code>",
                parse_mode='HTML',
            )
            return

        await _send_long_report(
            context, target_chat, result,
            parse_mode='HTML',
            limit=TELEGRAM_MESSAGE_LIMIT,
            split_delay=DB_DIAG_SPLIT_DELAY,
        )


__all__ = [
    'CommandHandlers',
    '_notify_dev_log',
    '_spawn_notify_dev_log',
    '_safe_send_message',
    '_safe_edit_or_send',
    '_invalidate_force_sub_cache',
    '_trans',
    '_get_lang',
]