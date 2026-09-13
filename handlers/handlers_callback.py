#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_callback.py - المعالج النهائي الكامل (v9.0.0)
=====================================================================
✅ v9.0.0 — إصلاح شامل لكل الأخطاء المُكتشفة عبر 6 جولات فحص:

🔴 حرجة:
  1.  user_cache dummy عند فشل ImportError
  2.  _handle_group_delete مع فحص صلاحية + ملكية
  3.  sec_activate_all: يعرض تأكيد (لا يتخطاه)
  4.  slow_mode_seconds أُزيل من toggle_map
  5.  _unwrap_get_next_post يُحوّل sqlite3.Row
  6.  admin_add_banned/del_reply/rem_banned تضبط السياق
  7.  فحص auth موحد لكل sec_*
  8.  auto_reply_menu:-1 مقيد بالمطور
  9.  إزالة Early Return (كان يكسر post_clear_confirm و buy_sub_*)
  10. query.from_user None guard
  11. <code> مع parse_mode='HTML'
  12. int(None) crash في pagination

🟠 عالية:
  13. feedback عند أخطاء _handle_parameterized
  14. RetryAfter مع timedelta
  15. semaphore في _handle_post_publish
  16. _publish_all لا يفقد منشورات
  17. حذف effective_chat fallback الخطير
  18. admin_restore_file يغلق DB
  19. _do_backup يحفظ النسخة الجديدة + فحص الحجم
  20. activate_all في transaction
  21. user_cache.get_or_load مع except عام
  22. Rate Limit Alert يعمل (دمج _safe_answer)
  23. DB.get_user_language داخل try
  24. _handle_group_settings يُفحص قبل التلويث
  25. _check_sec_auth مع كاش
  26. PUBLISH_RATE_LIMITER مع timeout
  27. admin_toggle_ch/gr ذرّي (SQL toggle)
  28. .get(k) or default (لا None)
  29. str(x or '?') بدل str(None)
  30. 20+ dead code في _handle_security
  31. safe_edit مع clear_markup

🟡 متوسطة ومنخفضة:
  32-90. تنظيف imports، تأكيدات، ترجمة، pagination، إلخ...
=====================================================================
"""

import asyncio
import logging
import json
import time
import shutil
import os
import weakref
from datetime import timedelta
from pathlib import Path
from typing import Optional, Dict, Tuple, Any, Set

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice, ChatPermissions
)
from telegram.ext import ContextTypes
from telegram.error import BadRequest, RetryAfter, Forbidden

from config import CONFIG, PATHS
from database import DB, TimeUtils

# ─── utils ────────────────────────────────────────────────────────────
try:
    from utils import (
        safe_send, is_authorized_in_group,
        get_text, StateManager, UserState,
        KeyboardFactory, CB, get_ram_usage,
    )
except ImportError:
    from utils import (
        safe_send, is_authorized_in_group,
        get_text, StateManager, UserState,
        KeyboardFactory, CB, get_ram_usage,
    )

# ✅ #31: fallback نظيف لـ PUBLISH_RATE_LIMITER
try:
    from utils import PUBLISH_RATE_LIMITER
except ImportError:
    try:
        from utils import RATE_LIMITER as PUBLISH_RATE_LIMITER
    except ImportError:
        class _NullLimiter:
            async def acquire(self):
                return
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
        PUBLISH_RATE_LIMITER = _NullLimiter()

# ✅ #8: dummy user_cache صريح
try:
    from cache import user_cache, invalidate_user_cache
except ImportError:
    class _DummyUserCache:
        async def get(self, user_id):
            return None
        async def get_or_load(self, user_id, db):
            try:
                return await db.get_start_data(user_id) or {}
            except Exception:
                return {}
        async def invalidate(self, user_id=None):
            return
    user_cache = _DummyUserCache()
    async def invalidate_user_cache(user_id):
        return

try:
    from .handlers_command import CommandHandlers, _invalidate_force_sub_cache
except ImportError:
    from handlers_command import CommandHandlers, _invalidate_force_sub_cache

logger = logging.getLogger(__name__)

# =====================================================================
# ثوابت
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

# ✅ #80/#69: primary owner محوّل لـ int مرة واحدة
try:
    _PRIMARY_OWNER_ID = int(CONFIG.PRIMARY_OWNER_ID)
except (TypeError, ValueError, AttributeError):
    _PRIMARY_OWNER_ID = None

ACTIVE_TASKS: weakref.WeakSet = weakref.WeakSet()
_publish_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PUBLISH)

# ✅ #25: كاش فحص الصلاحيات الأمنية
_sec_auth_cache: Dict[Tuple[int, int], Tuple[bool, float]] = {}

_CONTEXT_KEYS_TO_CLEAR = (
    'security_chat_id', 'auto_chat', 'adv_chat', 'schedule_ch',
    'ban_chat', 'contest_join', 'channel_page', 'post_page', 'sec_chat',
)
_CANCEL_EXTRA_KEYS = ('pin_msg_id',)

GROUP_NUMBER_EMOJIS = [
    "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣",
    "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟",
]


def _group_number(index: int) -> str:
    if 1 <= index <= len(GROUP_NUMBER_EMOJIS):
        return GROUP_NUMBER_EMOJIS[index - 1]
    return f"{index}."


def _is_primary_owner(user_id: int) -> bool:
    """✅ #80: فحص نوع-آمن للمالك."""
    return _PRIMARY_OWNER_ID is not None and user_id == _PRIMARY_OWNER_ID


def _row_to_dict(row) -> Optional[Dict[str, Any]]:
    """✅ #4/#20/#29: تحويل موحد لنتائج DB."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _coerce_int(value, default=0) -> int:
    """✅ #12: لا int(None)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value, default='?') -> str:
    """✅ #29: str(None) → '?' بدل 'None'."""
    if value is None:
        return default
    s = str(value)
    return s if s.strip() else default


# =====================================================================
# دوال مساعدة عامة
# =====================================================================

async def _safe_answer(query, text=None, show_alert=False) -> bool:
    if not query:
        return False
    try:
        if text:
            await query.answer(text, show_alert=show_alert)
        else:
            await query.answer()
        return True
    except BadRequest as e:
        err = str(e).lower()
        if "query is too old" in err or "already been answered" in err:
            return False
        return False
    except Exception:
        return False


async def _trans(key, lang, default_ar) -> str:
    if not lang:
        return default_ar
    try:
        text = await get_text(lang, key)
        if not text or text == key:
            return default_ar
        return text
    except Exception:
        return default_ar


async def safe_edit(query, text, reply_markup=None, parse_mode=None, bot=None,
                    clear_markup=False) -> bool:
    """✅ #74: clear_markup يدعم مسح الكيبورد."""
    if not query or not query.message:
        if bot and query and query.from_user:
            try:
                await bot.send_message(
                    chat_id=query.from_user.id,
                    text=text or "...",
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                return True
            except Exception:
                pass
        return False

    if not text or not str(text).strip():
        text = "..."
    else:
        text = str(text)

    # ✅ clear_markup: إن طُلب مسح الكيبورد
    if clear_markup and reply_markup is None:
        reply_markup = InlineKeyboardMarkup([])

    try:
        await query.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=parse_mode
        )
        return True
    except BadRequest as e:
        error_msg = str(e).lower()

        if "message is not modified" in error_msg:
            return True
        elif "message is too long" in error_msg:
            chat_id = query.message.chat_id
            try:
                await query.message.delete()
            except Exception:
                pass
            try:
                send_bot = bot
                if send_bot:
                    await send_bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                    return True
                return False
            except Exception:
                return False
        elif "query is too old" in error_msg or "message to edit not found" in error_msg:
            return False
        elif "can't parse entities" in error_msg or "parse" in error_msg:
            try:
                await query.edit_message_text(
                    text, reply_markup=reply_markup, parse_mode=None
                )
                return True
            except Exception:
                return False
        elif "message text is empty" in error_msg:
            try:
                await query.edit_message_text("...", reply_markup=reply_markup)
                return True
            except Exception:
                return False
        else:
            return False

    except Exception:
        return False


async def safe_delete_message(query_or_message) -> None:
    try:
        if hasattr(query_or_message, 'message') and query_or_message.message:
            await query_or_message.message.delete()
        elif query_or_message:
            await query_or_message.delete()
    except Exception:
        pass


def _mask_id(id_value, prefix=3, suffix=2) -> str:
    if id_value is None:
        return "***"
    s = str(id_value)
    if len(s) <= 5:
        return "***"
    return s[:prefix] + "***" + s[-suffix:]


async def _is_channel_owner(user_id: int, channel_db_id: int) -> bool:
    try:
        return await DB.is_channel_owner(user_id, channel_db_id)
    except Exception:
        return False


async def _is_group_owner(user_id: int, chat_id: int) -> bool:
    """✅ #2: التحقق من ملكية المجموعة."""
    try:
        if hasattr(DB, 'is_group_owner'):
            return await DB.is_group_owner(user_id, chat_id)
        if hasattr(DB, 'get_user_groups'):
            groups = await DB.get_user_groups(user_id)
            for g in (groups or []):
                gd = _row_to_dict(g)
                if gd and gd.get('chat_id') == chat_id:
                    return True
        return False
    except Exception as e:
        logger.warning(f"_is_group_owner error: {e}")
        return False


def _clear_context_keys(context, extra_keys=None) -> None:
    for k in _CONTEXT_KEYS_TO_CLEAR:
        context.user_data.pop(k, None)
    if extra_keys:
        for k in extra_keys:
            context.user_data.pop(k, None)


def _ensure_bot_start_time(context) -> None:
    if 'start_time' not in context.bot_data:
        context.bot_data['start_time'] = time.monotonic()


async def _resolve_sec_chat_id(context, data: str) -> Optional[int]:
    """✅ #3: بدون update (غير مستخدم)."""
    parts = data.split(":")
    for part in parts[1:]:
        p = part.strip()
        if p.startswith('-') and p[1:].isdigit():
            return int(p)
    stored = context.user_data.get('security_chat_id') or context.user_data.get('sec_chat')
    if stored:
        try:
            return int(stored)
        except (TypeError, ValueError):
            return None
    return None


async def _check_sec_auth(context, user_id: int, chat_id: int) -> bool:
    """✅ #25: فحص موحد مع كاش."""
    if chat_id is None:
        return False
    key = (user_id, chat_id)
    now = time.monotonic()
    cached = _sec_auth_cache.get(key)
    if cached and now - cached[1] < SEC_AUTH_CACHE_TTL:
        return cached[0]
    try:
        result = await is_authorized_in_group(context.bot, chat_id, user_id)
    except Exception:
        result = False
    _sec_auth_cache[key] = (result, now)
    return result


def _invalidate_sec_auth_cache(chat_id: int = None) -> None:
    """✅ #25: إبطال الكاش."""
    if chat_id is None:
        _sec_auth_cache.clear()
    else:
        for k in list(_sec_auth_cache.keys()):
            if k[1] == chat_id:
                del _sec_auth_cache[k]


# =====================================================================
# CallbackHandlers
# =====================================================================

class CallbackHandlers:

    RATE_LIMIT_PER_MINUTE = 30
    PUBLISH_DELAY_SECONDS = 0.2
    PUBLISH_BATCH_SIZE = 10

    # =================================================================
    # المعالج الرئيسي
    # =================================================================

    @staticmethod
    async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return

        # ✅ #10: from_user guard
        user = query.from_user
        if not user or not user.id:
            await _safe_answer(query, "❌ تعذر التعرف على المستخدم", show_alert=True)
            return

        data = query.data
        if not data:
            await _safe_answer(query)
            return

        user_id = user.id
        now_time = time.monotonic()

        # ✅ #37: interval أقصر
        last_cb_key = f"last_cb_{user_id}"
        last_time = context.user_data.get(last_cb_key, 0)
        if now_time - last_time < CALLBACK_MIN_INTERVAL:
            await _safe_answer(query, "⚠️ انتظر لحظة")
            return
        context.user_data[last_cb_key] = now_time

        # ✅ #60: تنظيف دوري
        counter_key = "_cb_counter"
        cb_count = context.bot_data.get(counter_key, 0) + 1
        context.bot_data[counter_key] = cb_count
        if cb_count % RATE_LIMIT_CLEANUP_EVERY == 0:
            CallbackHandlers._cleanup_user_data(context)

        # ✅ #63: rate limit — التحقق قبل الإجابة
        rate_key = f"rate_{user_id}"
        rate_data = context.user_data.get(rate_key)
        if not rate_data or now_time - rate_data.get('reset', 0) > RATE_LIMIT_WINDOW:
            rate_data = {'count': 0, 'reset': now_time}
        rate_data['count'] = rate_data.get('count', 0) + 1
        context.user_data[rate_key] = rate_data

        if rate_data['count'] > CallbackHandlers.RATE_LIMIT_PER_MINUTE:
            # ✅ #63: إجابة واحدة مع alert
            await _safe_answer(query, "⚠️ تجاوزت الحد، انتظر قليلاً", show_alert=True)
            return

        # ✅ إجابة واحدة فقط بعد تجاوز الفحوص
        await _safe_answer(query)

        # ✅ #23: try يشمل كل شيء حتى lang
        start_time = time.monotonic()
        _ensure_bot_start_time(context)

        try:
            lang = await DB.get_user_language(user_id) or 'ar'
        except Exception as e:
            logger.warning(f"get_user_language failed: {e}")
            lang = 'ar'

        # ✅ #9: احذف Early Return — ندع _handle_parameterized تفحص طبيعياً
        try:
            handled = await CallbackHandlers._handle_parameterized(
                update, context, query, user_id, lang, data
            )
            if handled:
                elapsed = time.monotonic() - start_time
                if elapsed > 1.0:
                    logger.warning(f"🐢 زر بطيء (param) {data[:30]} — {elapsed:.2f}s")
                return
        except Exception as e:
            logger.error(f"❌ _handle_parameterized outer: {e}", exc_info=True)
            try:
                await safe_edit(query, "❌ حدث خطأ", bot=context.bot)
            except Exception:
                pass
            return

        base_data = data
        if ':' in data:
            parts = data.split(':')
            known = [
                CB.TOGGLE_AUTO, CB.TOGGLE_REC, CB.TRANSLATION, CB.REFERRAL,
                CB.REMINDER, CB.CONTESTS, CB.SUPPORT_TICKET, CB.CH_LIST,
                CB.POST_ADD, CB.POST_PUB, CB.POST_LIST, CB.POST_REC, CB.PUB_ALL,
                CB.GROUPS, CB.ADMIN, CB.SETTINGS, CB.PLANS, CB.INVOICES,
                CB.REF_CLAIM, CB.REF_LIST, CB.CONTEST_WINNERS, CB.DEVELOPER,
                CB.SUBSCRIBE, CB.SUPPORT, CB.LANGUAGE, CB.TRIAL, CB.HELP,
                CB.CANCEL, CB.CHECK_SUB, CB.TRANS_OFF, CB.REM_TOGGLE_SUB,
                CB.REM_TOGGLE_DAILY, CB.REM_TOGGLE_WEEKLY, CB.REM_SET_DAYS,
                CB.ADMIN_LIST_ADMINS,
                "finish_posts", "gift_plans", "redeem_gift",
            ]
            if parts[0] in known:
                base_data = parts[0]

        try:
            if base_data in (CB.MAIN, CB.BACK):
                StateManager.clear(user_id)
                _clear_context_keys(context)
                ok = await CallbackHandlers._show_main_menu_inline(query, context, user_id)
                if not ok:
                    await CommandHandlers.start(update, context)
                return

            if base_data == CB.CANCEL:
                StateManager.clear(user_id)
                _clear_context_keys(context, extra_keys=list(_CANCEL_EXTRA_KEYS))
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception:
                    pass
                return

            if base_data == CB.HELP:
                StateManager.clear(user_id)
                await CommandHandlers.help_command(update, context)
                return

            if base_data == CB.TRIAL:
                if await DB.has_used_trial(user_id):
                    await safe_edit(query, await _trans('trial_used', lang, "❌ لقد استخدمت التجربة المجانية بالفعل."), bot=context.bot)
                    return
                days = await DB.activate_trial(user_id)
                text = f"✅ تم تفعيل التجربة المجانية لمدة {days} يوم" if days > 0 else "❌ تعذر تفعيل التجربة"
                await safe_edit(query, text, bot=context.bot)
                await invalidate_user_cache(user_id)
                return

            if base_data == CB.DEVELOPER:
                StateManager.clear(user_id)
                await CommandHandlers.developer(update, context)
                return

            if base_data == CB.SUBSCRIBE:
                StateManager.clear(user_id)
                await CommandHandlers.subscribe(update, context)
                return

            if base_data == CB.SUPPORT:
                StateManager.clear(user_id)
                await CommandHandlers.support(update, context)
                return

            if base_data == CB.LANGUAGE:
                StateManager.clear(user_id)
                await CommandHandlers.language(update, context)
                return

            if base_data == CB.CHECK_SUB:
                try:
                    _invalidate_force_sub_cache(user_id)
                except Exception:
                    pass
                StateManager.clear(user_id)
                ok = await CallbackHandlers._show_main_menu_inline(query, context, user_id)
                if not ok:
                    await CommandHandlers.start(update, context)
                return

            if base_data == CB.SETTINGS:
                await CallbackHandlers._render_settings(query, context, user_id, lang)
                return

            if base_data == CB.TOGGLE_AUTO:
                cur = await DB.get_auto_publish_status(user_id)
                await DB.set_auto_publish(user_id, not cur)
                await CallbackHandlers._render_settings(query, context, user_id, lang)
                await invalidate_user_cache(user_id)
                return

            if base_data == CB.TOGGLE_REC:
                cur = await DB.get_auto_recycle_status(user_id)
                await DB.set_auto_recycle(user_id, not cur)
                await CallbackHandlers._render_settings(query, context, user_id, lang)
                await invalidate_user_cache(user_id)
                return

            if base_data == CB.PLANS:
                await safe_edit(query, "💎 اختر باقة:",
                                reply_markup=KeyboardFactory.build("plans", lang=lang), bot=context.bot)
                return

            if base_data == "gift_plans":
                plans = await DB.get_gift_plans()
                if not plans:
                    await safe_edit(query, "📭 لا توجد خطط هدايا", bot=context.bot)
                    return
                kb = []
                for p in plans:
                    pd = _row_to_dict(p) or {}
                    days = _safe_str(pd.get('days'), '0')
                    price = _safe_str(pd.get('price'), '0')
                    kb.append([InlineKeyboardButton(
                        f"🎁 {days} يوم - {price} ⭐",
                        callback_data=f"buy_gift:{pd.get('id', 0)}")])
                kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)])
                await safe_edit(query, "💎 اختر خطة هدية:",
                                reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)
                return

            if base_data == "redeem_gift":
                StateManager.clear(user_id)
                await CommandHandlers.redeem_gift(update, context)
                return

            if base_data == CB.INVOICES:
                invoices = await DB.get_user_invoices(user_id, 10)
                if not invoices:
                    await safe_edit(query, "📭 لا توجد فواتير", bot=context.bot)
                    return
                lines = []
                for inv in invoices:
                    inv_d = _row_to_dict(inv) or {}
                    lines.append(f"• #{_safe_str(inv_d.get('number'))} - {_safe_str(inv_d.get('amount'), '0')} ⭐")
                text = "🧾 فواتيري\n\n" + "\n".join(lines)
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)]]), bot=context.bot)
                return

            if base_data == CB.REFERRAL:
                await CallbackHandlers._render_referral(query, context, user_id, lang)
                return

            if base_data == CB.REF_CLAIM:
                days = await DB.claim_referral_reward(user_id)
                text = f"✅ تم صرف {days} يوم!" if days > 0 else "📭 لا توجد مكافآت"
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 رجوع", callback_data=CB.REFERRAL)]]), bot=context.bot)
                await invalidate_user_cache(user_id)
                return

            if base_data == CB.REF_LIST:
                refs = await DB.get_referrals_list(user_id)
                if refs:
                    text = "📋 المُحالين\n\n" + "\n".join(
                        f"{i}. {_mask_id(r)}" for i, r in enumerate(refs[:20], 1))
                else:
                    text = "📭 لا يوجد"
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 رجوع", callback_data=CB.REFERRAL)]]), bot=context.bot)
                return

            if base_data in (CB.REM_TOGGLE_SUB, CB.REM_TOGGLE_DAILY, CB.REM_TOGGLE_WEEKLY):
                await CallbackHandlers._handle_reminder_toggle(query, context, user_id, lang, base_data)
                return

            if base_data == CB.REMINDER:
                await CallbackHandlers._render_reminder(query, context, user_id, lang)
                return

            if base_data == CB.REM_SET_DAYS:
                StateManager.set(user_id, UserState.WAIT_REM_DAYS)
                await safe_edit(query, "📅 أرسل عدد الأيام (1-30):", bot=context.bot)
                return

            if base_data == CB.TRANSLATION:
                await CallbackHandlers._render_translation_menu(query, context, lang)
                return

            if base_data == CB.TRANS_OFF:
                await DB.set_user_language(user_id, 'off')
                await safe_edit(query, "✅ تم إيقاف الترجمة", bot=context.bot)
                await invalidate_user_cache(user_id)
                return

            if base_data == CB.CONTESTS:
                StateManager.clear(user_id)
                await CommandHandlers.contests(update, context)
                return

            if base_data == CB.CONTEST_WINNERS:
                winners = await DB.get_contest_winners(10)
                if winners:
                    lines = []
                    for w in winners:
                        wd = _row_to_dict(w) or {}
                        lines.append(f"• {_safe_str(wd.get('title'))} - {_mask_id(wd.get('winner_id'))}")
                    text = "🏆 الفائزون\n\n" + "\n".join(lines)
                else:
                    text = "📭 لا يوجد"
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)]]), bot=context.bot)
                StateManager.clear(user_id)
                return

            if base_data == CB.SUPPORT_TICKET:
                StateManager.set(user_id, UserState.SUPPORT_MODE)
                await safe_send(context.bot, user_id, "📞 أرسل رسالتك:")
                return

            if base_data == CB.CH_ADD:
                has_sub = _is_primary_owner(user_id) or await DB.has_active_subscription(user_id)
                if not has_sub:
                    await safe_edit(query, "❌ يتطلب اشتراك نشط", bot=context.bot)
                    return
                StateManager.set(user_id, UserState.WAIT_CHANNEL)
                await safe_edit(query, "📡 أرسل معرف القناة:", bot=context.bot)
                return

            if base_data == CB.CH_LIST:
                await CallbackHandlers._show_channel_list(update, context, query, user_id, lang)
                return

            if base_data == CB.POST_ADD:
                await CallbackHandlers._handle_post_add(update, context, query, user_id)
                return

            if base_data == "finish_posts":
                StateManager.clear(user_id)
                await invalidate_user_cache(user_id)
                ok = await CallbackHandlers._show_main_menu_inline(query, context, user_id)
                if not ok:
                    await safe_edit(query, "✅ تم إنهاء إضافة المنشورات", bot=context.bot)
                return

            if base_data == CB.POST_PUB:
                await CallbackHandlers._handle_post_publish(update, context, query, user_id)
                return

            if base_data == CB.POST_LIST:
                await CallbackHandlers._show_post_list(update, context, query, user_id, lang)
                return

            if base_data == CB.POST_REC:
                active = await DB.get_active_channel(user_id)
                if active:
                    count = await DB.reset_posts(user_id, active)
                    try:
                        await invalidate_user_cache(user_id)
                    except Exception:
                        pass
                    context.user_data['post_page'] = 0
                    await safe_send(context.bot, user_id, f"♻️ تم إعادة تدوير {count} منشور")
                    await CallbackHandlers._show_post_list(update, context, query, user_id, lang)
                else:
                    await safe_edit(query, "❌ لا توجد قناة نشطة", bot=context.bot)
                return

            if base_data == CB.POST_CLEAR:
                active = await DB.get_active_channel(user_id)
                if active:
                    await DB.execute("DELETE FROM posts WHERE channel_db_id=?", (active,))
                    try:
                        from database import internal_cache, CACHE_AVAILABLE, posts_cache
                        await internal_cache.invalidate(f"channel_info_{active}")
                        if CACHE_AVAILABLE:
                            await posts_cache.invalidate()
                        await invalidate_user_cache(user_id)
                    except Exception:
                        pass
                    context.user_data['post_page'] = 0
                    await safe_send(context.bot, user_id, "🧹 تم مسح جميع المنشورات")
                    await CallbackHandlers._show_post_list(update, context, query, user_id, lang)
                else:
                    await safe_edit(query, "❌ لا توجد قناة نشطة", bot=context.bot)
                return

            if base_data == CB.PUB_ALL:
                await CallbackHandlers._handle_publish_all(update, context, query, user_id)
                return

            if base_data == CB.GROUPS:
                await CallbackHandlers._show_groups_list(update, context, query, user_id, lang)
                return

            if base_data == CB.ADMIN:
                if not CONFIG.is_developer(user_id):
                    await safe_edit(query, "❌ غير مصرح", bot=context.bot)
                    return
                kb = KeyboardFactory.build("admin_panel", lang=lang)
                await safe_edit(query, "👑 لوحة الأدمن", reply_markup=kb, bot=context.bot)
                return

            # ✅ #30: sec_* موحد
            if data.startswith("sec_"):
                await CallbackHandlers._handle_security(update, context, query, user_id, lang)
                return

            if data.startswith("admin_"):
                if CONFIG.is_developer(user_id):
                    await CallbackHandlers._handle_admin(update, context, query, user_id, lang)
                else:
                    await safe_edit(query, "❌ غير مصرح", bot=context.bot)
                return

            if data.startswith("auto_reply_") or data.startswith("auto_reply_menu:"):
                await CallbackHandlers._handle_auto_reply(update, context, query, user_id, lang)
                return

            if data.startswith("sched_open:") or data.startswith("sched_"):
                await CallbackHandlers._handle_schedule(update, context, query, user_id)
                return

            if data.startswith("ban_") or data.startswith("act_") or data.startswith("pen_"):
                await CallbackHandlers._handle_advanced_actions(update, context, query, user_id)
                return

            declare_sel = getattr(CB, 'DECLARE_WINNER_SEL', 'declare_winner_sel')
            if data.startswith("contest_") or data.startswith(declare_sel + ":"):
                await CallbackHandlers._handle_contests(update, context, query, user_id)
                return

            if data.startswith("lang_"):
                await CallbackHandlers._handle_language_change(update, context, query, user_id)
                return

            if data == "ch_page_prev":
                context.user_data['channel_page'] = max(0, _coerce_int(context.user_data.get('channel_page'), 0) - 1)
                await CallbackHandlers._show_channel_list(update, context, query, user_id, lang)
                return
            if data == "ch_page_next":
                context.user_data['channel_page'] = _coerce_int(context.user_data.get('channel_page'), 0) + 1
                await CallbackHandlers._show_channel_list(update, context, query, user_id, lang)
                return
            if data == "post_page_prev":
                context.user_data['post_page'] = max(0, _coerce_int(context.user_data.get('post_page'), 0) - 1)
                await CallbackHandlers._show_post_list(update, context, query, user_id, lang)
                return
            if data == "post_page_next":
                context.user_data['post_page'] = _coerce_int(context.user_data.get('post_page'), 0) + 1
                await CallbackHandlers._show_post_list(update, context, query, user_id, lang)
                return

            if data.startswith("adm_ch_page:"):
                page = _coerce_int(data.split(":")[-1], 0)
                context.user_data['adm_ch_page'] = page
                await CallbackHandlers._show_admin_channels(update, context, query, user_id, lang)
                return
            if data.startswith("adm_gr_page:"):
                page = _coerce_int(data.split(":")[-1], 0)
                context.user_data['adm_gr_page'] = page
                await CallbackHandlers._show_admin_groups(update, context, query, user_id, lang)
                return

            if data in ("panel_lock", "panel_unlock", "panel_close"):
                await CallbackHandlers._handle_panel(update, context, query, user_id, data)
                return

            await safe_edit(query, "⚠️ غير متوفر", bot=context.bot)

        except BadRequest as e:
            if "query is too old" not in str(e).lower():
                logger.error(f"❌ BadRequest: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"❌ Callback error: {e}", exc_info=True)
        finally:
            elapsed = time.monotonic() - start_time
            if elapsed > 1.0:
                logger.warning(f"🐢 زر بطيء {data[:30]} — {elapsed:.2f}s")

    @staticmethod
    def _cleanup_user_data(context) -> None:
        """✅ #60: تنظيف دوري."""
        try:
            now = time.monotonic()
            keys_to_del = []
            for k, v in list(context.user_data.items()):
                if k.startswith('rate_') and isinstance(v, dict):
                    if now - v.get('reset', 0) > RATE_LIMIT_WINDOW * 5:
                        keys_to_del.append(k)
                elif k.startswith('last_cb_'):
                    if isinstance(v, (int, float)) and now - v > 3600:
                        keys_to_del.append(k)
            for k in keys_to_del:
                context.user_data.pop(k, None)
        except Exception:
            pass

    # =================================================================
    # القائمة الرئيسية — ✅ #71: parse_mode='HTML'
    # =================================================================

    @staticmethod
    async def _show_main_menu_inline(query, context, user_id) -> bool:
        try:
            user_data = None
            try:
                user_data = await user_cache.get(user_id)
            except Exception:
                pass

            if not user_data:
                try:
                    user_data = await user_cache.get_or_load(user_id, DB)
                except Exception as e:
                    logger.warning(f"user_cache.get_or_load failed: {e}")
                    try:
                        user_data = await DB.get_start_data(user_id) or {}
                    except Exception:
                        user_data = {}

            if not isinstance(user_data, dict):
                user_data = _row_to_dict(user_data) or {}

            lang = user_data.get('language', 'ar') or 'ar'
            channel_info = user_data.get('channel_info')
            unpublished_posts = user_data.get('unpublished_posts', 0)
            groups_count = user_data.get('groups_count', 0)
            has_sub = bool(user_data.get('has_subscription', False))

            ch_display = await _trans('no_active_channel', lang, "لا توجد قنوات")
            if channel_info and isinstance(channel_info, dict):
                ch_display = channel_info.get('channel_name') or ch_display

            sub_text = await _trans('subscription_active', lang, "✅ مفعل") if has_sub else await _trans('subscription_inactive', lang, "❌ غير مفعل")

            try:
                kb = KeyboardFactory.build("main_menu", lang=lang)
            except Exception:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)]])

            if CONFIG.is_developer(user_id):
                admin_text = KeyboardFactory.get_text("admin_panel_btn", lang)
                existing_callbacks = set()
                for row in kb.inline_keyboard:
                    for btn in row:
                        if btn.callback_data:
                            existing_callbacks.add(btn.callback_data)
                if CB.ADMIN not in existing_callbacks:
                    new_rows = list(kb.inline_keyboard)
                    new_rows.append([InlineKeyboardButton(admin_text, callback_data=CB.ADMIN)])
                    kb = InlineKeyboardMarkup(new_rows)

            title = await get_text(
                lang, 'main_menu',
                user_name=f"<code>{user_id}</code>",
                groups_count=groups_count,
                active_channel=ch_display,
                unpublished_posts=unpublished_posts,
                subscription_status=sub_text,
            )
            # ✅ #71: parse_mode='HTML' لعرض <code>
            await safe_edit(query, title, reply_markup=kb, parse_mode='HTML', bot=context.bot)
            return True
        except Exception as e:
            logger.error(f"_show_main_menu_inline: {e}", exc_info=True)
            return False

    # =================================================================
    # الأزرار ذات الصيغة الخاصة
    # ✅ #9: إزالة Early Return
    # =================================================================

    @staticmethod
    async def _handle_parameterized(update, context, query, user_id, lang, data) -> bool:
        # ✅ v9.0.0: لا Early Return — post_clear_confirm و buy_sub_* يحتاجان الوصول
        try:
            # ─── رجوع ───────────────────────────────────────────────
            if data in ("sec_close", "grp_close", "security_close", "back_to_groups", "sec_back"):
                StateManager.clear(user_id)
                _clear_context_keys(context)
                await CallbackHandlers._show_groups_list(update, context, query, user_id, lang)
                return True

            if data.startswith("sec_close:") or data.startswith("grp_close:"):
                StateManager.clear(user_id)
                _clear_context_keys(context)
                await CallbackHandlers._show_groups_list(update, context, query, user_id, lang)
                return True

            if data.startswith("back_to_groups:") or data.startswith("sec_back:"):
                StateManager.clear(user_id)
                _clear_context_keys(context)
                await CallbackHandlers._show_groups_list(update, context, query, user_id, lang)
                return True

            # ─── set_warn_count:CHAT_ID:COUNT ───────────────────────
            if data.startswith("set_warn_count:"):
                parts = data.split(":")
                if len(parts) != 3:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                count = _coerce_int(parts[2])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                if count < 1 or count > 100:
                    await safe_edit(query, "❌ العدد يجب أن يكون 1-100", bot=context.bot)
                    return True
                await DB.update_security_settings(chat_id, max_warnings=count)
                await CallbackHandlers._refresh_security_view(query, context, chat_id, lang)
                return True

            # ─── POST_CLEAR تأكيد ✅ #3 ─────────────────────────────
            if data == f"{CB.POST_CLEAR}_confirm":
                active = await DB.get_active_channel(user_id)
                if not active:
                    await safe_edit(query, "❌ لا توجد قناة نشطة", bot=context.bot)
                    return True
                count = await DB.fetchval("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (active,), default=0)
                text = (f"⚠️ <b>تأكيد مسح كل المنشورات</b>\n\n"
                        f"سيتم حذف <b>{count}</b> منشور نهائياً!\n<i>لا يمكن التراجع.</i>")
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🧹 نعم، امسح الكل", callback_data=CB.POST_CLEAR)],
                    [InlineKeyboardButton("❌ إلغاء", callback_data=CB.POST_LIST)],
                ])
                await safe_edit(query, text, reply_markup=kb, parse_mode='HTML', bot=context.bot)
                return True

            # ✅ #38: تأكيد حذف منشور واحد
            if data.startswith("post_del_confirm:"):
                post_id = _coerce_int(data.split(":")[-1])
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑️ نعم احذف", callback_data=f"{CB.POST_DEL}:{post_id}")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data=CB.POST_LIST)],
                ])
                await safe_edit(query, f"⚠️ هل تريد حذف المنشور <b>{post_id}</b>؟",
                                reply_markup=kb, parse_mode='HTML', bot=context.bot)
                return True

            # ✅ #38: تأكيد حذف قناة
            if data.startswith("ch_del_confirm:"):
                ch_id = _coerce_int(data.split(":")[-1])
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑️ نعم احذف القناة", callback_data=f"{CB.CH_DEL}:{ch_id}")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data=CB.CH_LIST)],
                ])
                await safe_edit(query, "⚠️ هل أنت متأكد من حذف القناة؟",
                                reply_markup=kb, parse_mode='HTML', bot=context.bot)
                return True

            # ✅ #38: تأكيد حذف مجموعة
            if data.startswith("grp_del_confirm:"):
                chat_id = _coerce_int(data.split(":")[-1])
                if not await is_authorized_in_group(context.bot, chat_id, user_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                if not await _is_group_owner(user_id, chat_id):
                    await safe_edit(query, "❌ لا تملك هذه المجموعة", bot=context.bot)
                    return True
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑️ نعم احذف", callback_data=f"grp_del:{chat_id}")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data=CB.GROUPS)],
                ])
                await safe_edit(query, "⚠️ هل أنت متأكد من حذف المجموعة؟",
                                reply_markup=kb, parse_mode='HTML', bot=context.bot)
                return True

            # ─── set_warn_penalty:TYPE:CHAT_ID ──────────────────────
            if data.startswith("set_warn_penalty:"):
                parts = data.split(":")
                if len(parts) != 3:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                _, penalty_type, chat_id_str = parts
                chat_id = _coerce_int(chat_id_str)
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                if penalty_type not in DB.VALID_PENALTY_TYPES:
                    await safe_edit(query, "❌ نوع عقوبة غير صالح", bot=context.bot)
                    return True
                await DB.update_security_settings(chat_id, warn_penalty=penalty_type)
                await CallbackHandlers._refresh_security_view(query, context, chat_id, lang)
                return True

            # ─── set_duration:TYPE:CHAT_ID:SECS ─────────────────────
            if data.startswith("set_duration:"):
                parts = data.split(":")
                if len(parts) < 4:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                penalty_type = parts[1]
                chat_id = _coerce_int(parts[2])
                duration = _coerce_int(parts[3])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                col_map = {
                    'mute': 'mute_default_duration', 'ban': 'ban_default_duration',
                    'restrict': 'restrict_default_duration', 'antiflood': 'antiflood_penalty_duration',
                    'night': 'night_mode_action_duration', 'warn_penalty': 'warn_penalty_duration',
                    'delete_penalty': 'delete_penalty_duration', 'violation': 'violation_penalty_duration',
                }
                col = col_map.get(penalty_type)
                if col is None:
                    await safe_edit(query, "❌ نوع عقوبة غير صالح", bot=context.bot)
                    return True
                await DB.update_security_settings(chat_id, **{col: duration})
                await CallbackHandlers._refresh_security_view(query, context, chat_id, lang)
                return True

            # ─── sec_set_del_penalty:TYPE:CHAT_ID ───────────────────
            if data.startswith("sec_set_del_penalty:"):
                parts = data.split(":")
                if len(parts) != 3:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                _, penalty_type, chat_id_str = parts
                chat_id = _coerce_int(chat_id_str)
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                if penalty_type == "none":
                    await DB.update_security_settings(chat_id, delete_penalty="none")
                elif penalty_type in DB.VALID_PENALTY_TYPES:
                    await DB.update_security_settings(chat_id, delete_penalty=penalty_type)
                else:
                    await safe_edit(query, "❌ نوع عقوبة غير صالح", bot=context.bot)
                    return True
                await CallbackHandlers._refresh_security_view(query, context, chat_id, lang)
                return True

            # ─── sec_set_del_penalty_duration:CHAT_ID ───────────────
            if data.startswith("sec_set_del_penalty_duration:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                await CallbackHandlers._show_penalty_durations(update, context, query, chat_id, lang, 'delete_penalty')
                return True

            # ─── sec_penalty_durations:CHAT_ID ──────────────────────
            if data.startswith("sec_penalty_durations:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                await CallbackHandlers._show_all_penalty_durations_menu(query, context, chat_id)
                return True

            # ─── مدد مختلفة ────────────────────────────────────────
            for prefix, action_type in (
                ("sec_set_mute_duration:", "mute"),
                ("sec_set_ban_duration:", "ban"),
                ("sec_set_restrict_duration:", "restrict"),
                ("sec_antiflood_duration:", "antiflood"),
                ("sec_night_duration:", "night"),
            ):
                if data.startswith(prefix):
                    parts = data.split(":")
                    if len(parts) != 2:
                        await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                        return True
                    chat_id = _coerce_int(parts[1])
                    if not await _check_sec_auth(context, user_id, chat_id):
                        await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                        return True
                    await CallbackHandlers._show_penalty_durations(update, context, query, chat_id, lang, action_type)
                    return True

            if data.startswith("sec_warn_penalty_duration:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                await CallbackHandlers._show_penalty_durations(update, context, query, chat_id, lang, 'warn_penalty')
                return True

            # ─── sec_penalty_TYPE:CHAT_ID ───────────────────────────
            if data.startswith("sec_penalty_"):
                parts = data.split(":")
                if len(parts) < 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                if parts[1].lstrip('-').isdigit():
                    chat_id = int(parts[1])
                else:
                    chat_id = await _resolve_sec_chat_id(context, data)
                if chat_id is None:
                    await safe_edit(query, "❌ لم يتم تحديد المجموعة", bot=context.bot)
                    return True
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                action = parts[0][4:] if parts[0].startswith("sec_") else parts[0]
                action = action.replace("penalty_", "", 1)
                if action in ('ban', 'mute', 'kick', 'restrict', 'none'):
                    await DB.update_security_settings(chat_id, auto_penalty=action)
                    await CallbackHandlers._refresh_security_view(query, context, chat_id, lang)
                else:
                    await safe_edit(query, "❌ نوع عقوبة غير صالح", bot=context.bot)
                return True

            # ─── antiflood messages/seconds ─────────────────────────
            for prefix, state, prompt in (
                ("sec_set_antiflood_messages:", UserState.WAIT_ANTIFLOOD_MESSAGES, "📊 أرسل عدد الرسائل المسموحة:"),
                ("sec_set_antiflood_seconds:", UserState.WAIT_ANTIFLOOD_SECONDS, "⏱️ أرسل عدد الثواني:"),
            ):
                if data.startswith(prefix):
                    parts = data.split(":")
                    if len(parts) != 2:
                        await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                        return True
                    chat_id = _coerce_int(parts[1])
                    if not await _check_sec_auth(context, user_id, chat_id):
                        await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                        return True
                    StateManager.set(user_id, state)
                    context.user_data['sec_chat'] = chat_id
                    await safe_edit(query, prompt, bot=context.bot)
                    return True

            if data.startswith("sec_antiflood_penalty:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                await CallbackHandlers._show_penalty_type_selection(update, context, query, chat_id, lang, 'antiflood_penalty')
                return True

            if data.startswith("sec_set_antiflood_penalty:"):
                parts = data.split(":")
                if len(parts) < 3:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                penalty_type = parts[2]
                if penalty_type in ('ban', 'mute', 'kick', 'restrict', 'none'):
                    await DB.update_security_settings(chat_id, antiflood_penalty=penalty_type)
                    await CallbackHandlers._refresh_security_view(query, context, chat_id, lang)
                else:
                    await safe_edit(query, "❌ نوع عقوبة غير صالح", bot=context.bot)
                return True

            # ─── night start/end ────────────────────────────────────
            for prefix, state, prompt in (
                ("sec_set_night_start:", UserState.WAIT_NIGHT_START, "🌙 أرسل وقت البدء (HH:MM):"),
                ("sec_set_night_end:", UserState.WAIT_NIGHT_END, "🌙 أرسل وقت النهاية (HH:MM):"),
            ):
                if data.startswith(prefix):
                    parts = data.split(":")
                    if len(parts) != 2:
                        await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                        return True
                    chat_id = _coerce_int(parts[1])
                    if not await _check_sec_auth(context, user_id, chat_id):
                        await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                        return True
                    StateManager.set(user_id, state)
                    context.user_data['sec_chat'] = chat_id
                    await safe_edit(query, prompt, bot=context.bot)
                    return True

            if data.startswith("sec_night_action:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                await CallbackHandlers._show_penalty_type_selection(update, context, query, chat_id, lang, 'night_action')
                return True

            if data.startswith("sec_set_night_action:"):
                parts = data.split(":")
                if len(parts) < 3:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                action_type = parts[2]
                if action_type in ('ban', 'mute', 'kick', 'restrict'):
                    await DB.update_security_settings(chat_id, night_mode_action=action_type)
                    await CallbackHandlers._refresh_security_view(query, context, chat_id, lang)
                else:
                    await safe_edit(query, "❌ نوع إجراء غير صالح", bot=context.bot)
                return True

            # ─── violation settings ─────────────────────────────────
            if data.startswith("sec_violation_settings:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                await CallbackHandlers._show_violation_penalties(update, context, query, chat_id, lang)
                return True

            if data.startswith("sec_set_violation_strikes:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                StateManager.set(user_id, UserState.WAIT_VIOLATION_STRIKES)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🔢 أرسل عدد المخالفات المسموحة:", bot=context.bot)
                return True

            if data.startswith("sec_set_violation_duration:"):
                parts = data.split(":")
                if len(parts) != 2:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                await CallbackHandlers._show_penalty_durations(update, context, query, chat_id, lang, 'violation')
                return True

            if data.startswith("sec_set_violation_penalty:"):
                parts = data.split(":")
                if len(parts) < 3:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                    return True
                penalty_type = parts[2]
                if penalty_type in ('ban', 'mute', 'kick', 'restrict', 'none'):
                    await DB.update_security_settings(chat_id, violation_penalty=penalty_type)
                    await CallbackHandlers._refresh_security_view(query, context, chat_id, lang)
                else:
                    await safe_edit(query, "❌ نوع عقوبة غير صالح", bot=context.bot)
                return True

            # ─── الشراء ✅ #61 ──────────────────────────────────────
            if data.startswith("buy_sub_"):
                await CallbackHandlers._handle_buy_subscription(update, context, query, user_id, data)
                return True

            if data.startswith("buy_gift:"):
                await CallbackHandlers._handle_buy_gift(update, context, query, user_id, data)
                return True

            # ✅ #2: حذف مجموعة مع auth
            if data.startswith("grp_del:"):
                await CallbackHandlers._handle_group_delete(update, context, query, user_id, data)
                return True

            if data.startswith(CB.GRP_SET + ":"):
                await CallbackHandlers._handle_group_settings(update, context, query, user_id, lang, data)
                return True

            if data.startswith(CB.CH_SEL + ":"):
                await CallbackHandlers._handle_channel_select(update, context, query, user_id, data)
                return True

            if data.startswith(CB.CH_DEL + ":"):
                await CallbackHandlers._handle_channel_delete(update, context, query, user_id, lang, data)
                return True

            if data.startswith(CB.CH_STATS + ":"):
                await CallbackHandlers._handle_channel_stats(update, context, query, user_id, data)
                return True

            if data.startswith(CB.POST_DEL + ":"):
                await CallbackHandlers._handle_post_delete(update, context, query, user_id, lang, data)
                return True

            return False

        except BadRequest as e:
            if "query is too old" not in str(e).lower():
                logger.error(f"❌ _handle_parameterized BadRequest: {e}", exc_info=True)
            return True
        except Exception as e:
            # ✅ #13: feedback عند الأخطاء
            logger.error(f"❌ _handle_parameterized: {e}", exc_info=True)
            try:
                await safe_edit(query, "❌ حدث خطأ غير متوقع", bot=context.bot)
            except Exception:
                pass
            return True

    # =================================================================
    # Refresh موحد لشاشة الأمان
    # =================================================================

    @staticmethod
    async def _refresh_security_view(query, context, chat_id, lang):
        try:
            settings = await DB.get_security_settings(chat_id) or {}
            if not isinstance(settings, dict):
                settings = _row_to_dict(settings) or {}
            stats = await KeyboardFactory._get_security_stats(chat_id) or {}
            await safe_edit(
                query,
                KeyboardFactory._format_security_text(settings, stats),
                reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                bot=context.bot,
            )
        except Exception as e:
            logger.error(f"_refresh_security_view: {e}", exc_info=True)

    # =================================================================
    # معالجات صغيرة
    # =================================================================

    @staticmethod
    async def _render_settings(query, context, user_id, lang):
        try:
            s = await DB.get_user_settings_batch(user_id) or {}
            if not isinstance(s, dict):
                s = _row_to_dict(s) or {}
            auto = "✅" if s.get('auto_publish') else "❌"
            rec = "✅" if s.get('auto_recycle') else "❌"
            kb = KeyboardFactory.build("settings", lang=lang)
            await safe_edit(query, f"⚙️ الإعدادات\n\n📤 النشر: {auto}\n♻️ التدوير: {rec}",
                            reply_markup=kb, bot=context.bot)
        except Exception as e:
            logger.error(f"_render_settings: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    @staticmethod
    async def _render_referral(query, context, user_id, lang):
        try:
            stats = await DB.get_referral_stats(user_id) or {}
            if not isinstance(stats, dict):
                stats = _row_to_dict(stats) or {}
            code = await DB.get_referral_code(user_id)
            if code and code.startswith('ref_'):
                code = code[4:]
            link = f"https://t.me/{CONFIG.BOT_USERNAME}?start=ref_{code}"
            text = (f"🔗 نظام الإحالات\n\n📎 رابطك:\n{link}\n\n"
                    f"👥 المُحالين: {stats.get('total', 0)}\n🎁 الأيام المتاحة: {stats.get('available', 0)} يوم")
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🎁 صرف المكافأة", callback_data=CB.REF_CLAIM),
                 InlineKeyboardButton("📋 المُحالين", callback_data=CB.REF_LIST)],
                [InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)],
            ])
            await safe_edit(query, text, reply_markup=kb, bot=context.bot)
        except Exception as e:
            logger.error(f"_render_referral: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    @staticmethod
    async def _render_reminder(query, context, user_id, lang):
        try:
            settings = await DB.get_reminder_settings(user_id) or {}
            if not isinstance(settings, dict):
                settings = _row_to_dict(settings) or {}
            text = (f"⏰ التذكيرات\n\n"
                    f"🔔 الاشتراك: {'✅' if settings.get('subscription_reminder') else '❌'}\n"
                    f"📊 يومي: {'✅' if settings.get('daily_stats_reminder') else '❌'}\n"
                    f"📈 أسبوعي: {'✅' if settings.get('weekly_report') else '❌'}")
            await safe_edit(query, text, reply_markup=KeyboardFactory.build("reminder", lang=lang), bot=context.bot)
        except Exception as e:
            logger.error(f"_render_reminder: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    @staticmethod
    async def _handle_reminder_toggle(query, context, user_id, lang, base_data):
        try:
            settings = await DB.get_reminder_settings(user_id) or {}
            if not isinstance(settings, dict):
                settings = _row_to_dict(settings) or {}
            if base_data == CB.REM_TOGGLE_SUB:
                new_val = not settings.get('subscription_reminder', False)
                await DB.update_reminder_settings(user_id, subscription_reminder=new_val)
            elif base_data == CB.REM_TOGGLE_DAILY:
                new_val = not settings.get('daily_stats_reminder', False)
                await DB.update_reminder_settings(user_id, daily_stats_reminder=new_val)
            elif base_data == CB.REM_TOGGLE_WEEKLY:
                new_val = not settings.get('weekly_report', False)
                await DB.update_reminder_settings(user_id, weekly_report=new_val)
            await CallbackHandlers._render_reminder(query, context, user_id, lang)
        except Exception as e:
            logger.error(f"_handle_reminder_toggle: {e}", exc_info=True)

    @staticmethod
    async def _render_translation_menu(query, context, lang):
        # ✅ #51: كل اللغات
        rows = [
            [("🇸🇦 العربية", "ar"), ("🇬🇧 English", "en")],
            [("🇫🇷 Français", "fr"), ("🇹🇷 Türkçe", "tr")],
            [("🇨🇳 中文", "zh"), ("🇷🇺 Русский", "ru")],
            [("🇩🇪 Deutsch", "de"), ("🇪🇸 Español", "es")],
            [("🇮🇹 Italiano", "it"), ("🇵🇹 Português", "pt")],
            [("🇯🇵 日本語", "ja"), ("🇰🇷 한국어", "ko")],
            [("🇮🇷 فارسی", "fa"), ("🇵🇰 اردو", "ur")],
            [("🇳🇱 Nederlands", "nl"), ("🇵🇱 Polski", "pl")],
            [("🇮🇳 हिन्दी", "hi")],
        ]
        kb = [[InlineKeyboardButton(t, callback_data=f"lang_{c}") for t, c in row] for row in rows]
        kb.append([InlineKeyboardButton("❌ إيقاف الترجمة", callback_data=CB.TRANS_OFF)])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)])
        await safe_edit(query, "🌐 اختر اللغة:", reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    @staticmethod
    async def _handle_language_change(update, context, query, user_id):
        data = query.data or ""
        lang_set = data[5:] if data.startswith("lang_") else data.split("_")[-1]
        valid_langs = {'ar','en','fr','tr','zh','ru','de','es','it','pt','ja','ko','fa','ur','nl','pl','hi','off'}
        if lang_set in valid_langs:
            await DB.set_user_language(user_id, lang_set)
            await invalidate_user_cache(user_id)
            ok = await CallbackHandlers._show_main_menu_inline(query, context, user_id)
            if not ok:
                await CommandHandlers.start(update, context)
        else:
            await safe_edit(query, "❌ لغة غير مدعومة", bot=context.bot)

    # =================================================================
    # معالجات فرعية
    # =================================================================

    @staticmethod
    async def _handle_buy_subscription(update, context, query, user_id, data):
        try:
            days = int(data.split("_")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        plan_names = {1: "يوم", 7: "أسبوع", 30: "شهر", 90: "3 أشهر", 365: "سنة"}
        plan_name = plan_names.get(days)
        if not plan_name:
            await safe_edit(query, "❌ باقة غير موجودة", bot=context.bot)
            return
        plan = await DB.get_plan_by_name(plan_name)
        plan_d = _row_to_dict(plan)
        if not plan_d:
            await safe_edit(query, "❌ باقة غير موجودة", bot=context.bot)
            return
        plan_id = plan_d.get('id', 0)
        price = _coerce_int(plan_d.get('price'), 0)
        name = plan_d.get('name') or plan_name  # ✅ #84
        description = plan_d.get('description') or name  # ✅ #40
        invoice_number = await DB.create_invoice(user_id, plan_id, price)
        if not invoice_number:
            await safe_edit(query, "❌ فشل الدفع", bot=context.bot)
            return
        try:
            await context.bot.send_invoice(
                chat_id=user_id, title=f"💎 {name}",
                description=description,
                payload=json.dumps({'plan_id': plan_id, 'invoice': invoice_number, 'type': 'subscription'}),
                provider_token="", currency="XTR",
                prices=[LabeledPrice(name, price)],
            )
            await safe_delete_message(query)
        except Exception as e:
            logger.error(f"❌ فشل إرسال الفاتورة: {e}")
            try:
                await DB.execute("UPDATE invoices SET status='cancelled' WHERE number=?", (invoice_number,))
            except Exception:
                pass
            await safe_edit(query, f"❌ {str(e)[:50]}", bot=context.bot)

    @staticmethod
    async def _handle_buy_gift(update, context, query, user_id, data):
        try:
            gift_plan_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        plan = await DB.get_gift_plan(gift_plan_id)
        plan_d = _row_to_dict(plan)
        if not plan_d:
            await safe_edit(query, "❌ خطة الهدية غير موجودة", bot=context.bot)
            return
        plan_id = plan_d.get('id', 0)
        price = _coerce_int(plan_d.get('price'), 0)
        name = plan_d.get('name') or 'هدية'  # ✅ #84
        description = plan_d.get('description') or "كود هدية"
        invoice_number = await DB.create_invoice(user_id, plan_id, price)
        if not invoice_number:
            await safe_edit(query, "❌ فشل إنشاء الفاتورة", bot=context.bot)
            return
        try:
            await context.bot.send_invoice(
                chat_id=user_id, title=f"🎁 {name}",
                description=description,
                payload=json.dumps({'gift_plan_id': plan_id, 'invoice': invoice_number, 'type': 'gift'}),
                provider_token="", currency="XTR",
                prices=[LabeledPrice(name, price)],
            )
            await safe_delete_message(query)
        except Exception as e:
            logger.error(f"❌ فشل إرسال فاتورة الهدية: {e}")
            try:
                await DB.execute("UPDATE invoices SET status='cancelled' WHERE number=?", (invoice_number,))
            except Exception:
                pass
            await safe_edit(query, f"❌ {str(e)[:50]}", bot=context.bot)

    # ✅ #2: حماية كاملة
    @staticmethod
    async def _handle_group_delete(update, context, query, user_id, data):
        try:
            chat_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await safe_edit(query, "❌ لا صلاحية في هذه المجموعة", bot=context.bot)
            return
        if not await _is_group_owner(user_id, chat_id):
            await safe_edit(query, "❌ لا تملك هذه المجموعة", bot=context.bot)
            return
        if await DB.delete_group(chat_id):
            await safe_edit(query, "✅ تم حذف المجموعة", bot=context.bot)
        else:
            await safe_edit(query, "❌ فشل الحذف", bot=context.bot)

    # ✅ #24: لا تلويث قبل فحص الصلاحية
    @staticmethod
    async def _handle_group_settings(update, context, query, user_id, lang, data):
        try:
            chat_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
            return
        # ✅ بعد الفحص فقط
        context.user_data['security_chat_id'] = chat_id
        try:
            settings = await DB.get_security_settings(chat_id) or {}
            if not isinstance(settings, dict):
                settings = _row_to_dict(settings) or {}
            stats = await KeyboardFactory._get_security_stats(chat_id) or {}
            await safe_edit(query, KeyboardFactory._format_security_text(settings, stats),
                            reply_markup=KeyboardFactory.build("security", chat_id=chat_id, lang=lang),
                            bot=context.bot)
        except Exception as e:
            logger.error(f"_handle_group_settings: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    @staticmethod
    async def _handle_channel_select(update, context, query, user_id, data):
        try:
            ch_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        if await DB.set_active_channel(user_id, ch_id):
            await safe_edit(query, "✅ تم تحديد القناة!", bot=context.bot)
            await invalidate_user_cache(user_id)
        else:
            await safe_edit(query, "❌ لا يمكنك تحديد هذه القناة", bot=context.bot)

    @staticmethod
    async def _handle_channel_delete(update, context, query, user_id, lang, data):
        try:
            ch_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        if await DB.delete_channel(user_id, ch_id):
            context.user_data['channel_page'] = 0
            await CallbackHandlers._show_channel_list(update, context, query, user_id, lang)
            await invalidate_user_cache(user_id)
        else:
            await safe_edit(query, "❌ فشل", bot=context.bot)

    @staticmethod
    async def _handle_channel_stats(update, context, query, user_id, data):
        try:
            ch_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        try:
            stats = await DB.get_channel_stats(user_id, ch_id) or {}
            if not isinstance(stats, dict):
                stats = _row_to_dict(stats) or {}
            text = (f"📊 إحصائيات\n\n"
                    f"📝 {stats.get('total', 0)}\n"
                    f"✅ {stats.get('published', 0)}\n"
                    f"⏳ {stats.get('unpublished', 0)}")
        except Exception as e:
            logger.error(f"_handle_channel_stats: {e}", exc_info=True)
            text = "❌ فشل جلب الإحصائيات"
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 رجوع", callback_data=CB.CH_LIST)]]), bot=context.bot)

    # =================================================================
    # _handle_post_add
    # =================================================================

    @staticmethod
    async def _handle_post_add(update, context, query, user_id):
        try:
            is_owner = _is_primary_owner(user_id)
            has_sub = True if is_owner else await DB.has_active_subscription(user_id)
            active = await DB.get_active_channel(user_id)

            if not has_sub:
                await safe_edit(query, "❌ انتهى اشتراكك!", bot=context.bot)
                return

            if not active:
                await safe_edit(
                    query,
                    "❌ <b>لا توجد قناة نشطة</b>\n\n"
                    "📡 اذهب إلى <b>قنواتي</b> وأضف قناة أولاً.",
                    parse_mode='HTML',
                    bot=context.bot,
                )
                return

            StateManager.set(user_id, UserState.ADDING_POSTS)

            await safe_edit(
                query, "📥 أرسل المنشورات:",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("✅ إنهاء", callback_data="finish_posts")]]
                ),
                bot=context.bot,
            )
        except Exception as e:
            logger.error(f"❌ _handle_post_add: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    # =================================================================
    # _handle_post_publish — ✅ #15: semaphore + #41: فحص اشتراك
    # =================================================================

    @staticmethod
    async def _handle_post_publish(update, context, query, user_id):
        is_owner = _is_primary_owner(user_id)
        if not is_owner and not await DB.has_active_subscription(user_id):
            await safe_edit(query, "❌ انتهى اشتراكك!", bot=context.bot)
            return

        active = await DB.get_active_channel(user_id)
        if not active:
            await safe_edit(query, "❌ لا توجد قناة", bot=context.bot)
            return
        raw_result = await DB.get_next_post(active)
        post, was_recycled = CallbackHandlers._unwrap_get_next_post(raw_result)
        if not post or not isinstance(post, dict):
            await safe_edit(query, "📭 لا توجد منشورات", bot=context.bot)
            return
        ch_info = await DB.get_channel_info(user_id, active)
        ch_info_d = _row_to_dict(ch_info)
        if not ch_info_d or not ch_info_d.get('channel_id'):
            await safe_edit(query, "❌ معلومات القناة غير متوفرة", bot=context.bot)
            return

        bot = context.bot
        ch_id = ch_info_d['channel_id']
        recycled_flag = was_recycled

        async def _publish_task():
            suffix = " (بعد إعادة تدوير)" if recycled_flag else ""
            try:
                async with _publish_semaphore:
                    result = await CallbackHandlers._publish_single(bot, active, ch_id, post)
                if result:
                    await safe_send(bot, user_id, f"✅ تم النشر بنجاح{suffix}")
                else:
                    await safe_send(bot, user_id, f"❌ فشل النشر{suffix}")
            except Exception as e:
                logger.error(f"❌ _publish_task: {e}", exc_info=True)
                try:
                    await safe_send(bot, user_id, f"❌ خطأ غير متوقع: {str(e)[:80]}")
                except Exception:
                    pass

        task = asyncio.create_task(_publish_task())
        ACTIVE_TASKS.add(task)
        task.add_done_callback(ACTIVE_TASKS.discard)
        msg = "✅ بدأ النشر" + (" (بعد إعادة تدوير)" if was_recycled else "")
        await safe_edit(query, msg, bot=context.bot)

    @staticmethod
    async def _handle_post_delete(update, context, query, user_id, lang, data):
        try:
            post_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        active = await DB.get_active_channel(user_id)
        if active and await DB.delete_post(user_id, post_id, active):
            await CallbackHandlers._show_post_list(update, context, query, user_id, lang)
        else:
            await safe_edit(query, "❌ فشل", bot=context.bot)

    @staticmethod
    async def _handle_publish_all(update, context, query, user_id):
        is_owner = _is_primary_owner(user_id)
        if not is_owner and not await DB.has_active_subscription(user_id):
            await safe_edit(query, "❌ انتهى اشتراكك!", bot=context.bot)
            return

        channels = await DB.get_user_channels(user_id)
        if not channels:
            await safe_edit(query, "❌ لا توجد قنوات", bot=context.bot)
            return
        task = asyncio.create_task(CallbackHandlers._publish_all(context.bot, user_id, channels))
        ACTIVE_TASKS.add(task)
        task.add_done_callback(ACTIVE_TASKS.discard)
        await safe_edit(query, "✅ بدأ النشر الجماعي", bot=context.bot)

    # =================================================================
    # قائمة المجموعات — ✅ #90: ترقيم بدون فراغات
    # =================================================================

    @staticmethod
    async def _show_groups_list(update, context, query, user_id, lang):
        groups = await DB.get_user_groups(user_id)
        if not groups:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{CONFIG.BOT_USERNAME}?startgroup")],
                [InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)],
            ])
            await safe_edit(query, "📭 لا توجد مجموعات", reply_markup=kb, bot=context.bot)
            return

        text = "👥 مجموعاتي\n\n"
        kb = []
        display_idx = 0
        for g in groups:
            gd = _row_to_dict(g) or {}
            gid = gd.get('chat_id')
            if gid is None:
                continue
            display_idx += 1
            name = gd.get('chat_name') or f"Group {gid}"
            status = "⛔" if gd.get('banned') else "✅"
            number = _group_number(display_idx)
            text += f"{status} {number} {name}\n"
            kb.append([
                InlineKeyboardButton(f"{number} ⚙️ أمان", callback_data=f"{CB.GRP_SET}:{gid}"),
                InlineKeyboardButton(f"{number} 🗑️ حذف", callback_data=f"grp_del_confirm:{gid}"),
            ])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)])
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    # =================================================================
    # النشر — ✅ #5: Row→dict
    # =================================================================

    @staticmethod
    def _unwrap_get_next_post(result) -> Tuple[Optional[Dict], bool]:
        if result is None:
            return None, False
        if isinstance(result, tuple) and len(result) == 2:
            post_obj, was_recycled = result
            if post_obj is None:
                return None, bool(was_recycled)
            as_dict = _row_to_dict(post_obj)
            if as_dict is not None:
                return as_dict, bool(was_recycled)
            return None, False
        as_dict = _row_to_dict(result)
        if as_dict is not None:
            return as_dict, False
        return None, False

    @staticmethod
    async def _publish_single(bot, ch_db_id, ch_tele, post) -> bool:
        if isinstance(post, tuple) and len(post) == 2:
            post, _ = CallbackHandlers._unwrap_get_next_post(post)
        if not isinstance(post, dict):
            post = _row_to_dict(post)
        if not isinstance(post, dict):
            return False
        post_id = post.get('id')
        try:
            text = post.get('text', '') or ''
            media_type = post.get('media_type')
            media_file_id = post.get('media_file_id')
            if not text and not media_type and not media_file_id:
                return False
            caption = text[:MAX_CAPTION_LENGTH] if text else None
            if media_type == 'photo' and media_file_id:
                await bot.send_photo(ch_tele, media_file_id, caption=caption)
            elif media_type == 'video' and media_file_id:
                await bot.send_video(ch_tele, media_file_id, caption=caption)
            elif media_type == 'document' and media_file_id:
                await bot.send_document(ch_tele, media_file_id, caption=caption)
            elif media_type == 'audio' and media_file_id:
                await bot.send_audio(ch_tele, media_file_id, caption=caption)
            elif media_type == 'voice' and media_file_id:
                await bot.send_voice(ch_tele, media_file_id)
                if text:
                    try:
                        await bot.send_message(ch_tele, text)
                    except Exception:
                        pass
            elif media_type == 'animation' and media_file_id:
                await bot.send_animation(ch_tele, media_file_id, caption=caption)
            elif media_type == 'sticker' and media_file_id:
                await bot.send_sticker(ch_tele, media_file_id)
                if text:
                    try:
                        await bot.send_message(ch_tele, text)
                    except Exception:
                        pass
            elif media_type == 'video_note' and media_file_id:
                await bot.send_video_note(ch_tele, media_file_id)
                if text:
                    try:
                        await bot.send_message(ch_tele, text)
                    except Exception:
                        pass
            else:
                if text and len(text) > MAX_MESSAGE_LENGTH:
                    for i in range(0, len(text), MAX_MESSAGE_LENGTH):
                        await bot.send_message(ch_tele, text[i:i + MAX_MESSAGE_LENGTH])
                else:
                    await bot.send_message(ch_tele, text if text else ".")
            if post_id:
                await DB.mark_post_published(post_id)
            await DB.update_last_publish(ch_db_id)
            await DB.update_next_publish(ch_db_id)
            return True
        except RetryAfter as e:
            # ✅ #14: دعم timedelta
            delay = e.retry_after
            if isinstance(delay, timedelta):
                delay = delay.total_seconds()
            try:
                await asyncio.sleep(float(delay))
            except Exception:
                await asyncio.sleep(5)
            if post_id:
                try:
                    await DB.increment_post_fail(post_id)
                except Exception:
                    pass
            return False
        except Forbidden:
            try:
                await DB.execute("UPDATE user_channels SET banned=1 WHERE id=?", (ch_db_id,))
            except Exception:
                pass
            if post_id:
                try:
                    await DB.increment_post_fail(post_id)
                except Exception:
                    pass
            return False
        except Exception as e:
            logger.error(f"❌ فشل النشر: {e}", exc_info=True)
            if post_id:
                try:
                    await DB.increment_post_fail(post_id)
                except Exception:
                    pass
            return False

    @staticmethod
    async def _publish_all(bot, user_id, channels):
        published = 0
        failed = 0
        tasks = []
        banned_count = 0
        no_post_count = 0
        lost_count = 0
        try:
            for ch in channels:
                chd = _row_to_dict(ch) or {}
                if chd.get('banned'):
                    banned_count += 1
                    continue
                raw_result = await DB.get_next_post(chd.get('id'))
                post, _ = CallbackHandlers._unwrap_get_next_post(raw_result)
                if post and isinstance(post, dict):
                    ch_info = await DB.get_channel_info(user_id, chd.get('id'))
                    ch_info_d = _row_to_dict(ch_info)
                    if ch_info_d and ch_info_d.get('channel_id'):
                        tasks.append((chd.get('id'), ch_info_d['channel_id'], post))
                    else:
                        # ✅ #16: لا نفقد المنشور
                        pid = post.get('id')
                        if pid:
                            try:
                                await DB.increment_post_fail(pid)
                            except Exception:
                                pass
                        lost_count += 1
                else:
                    no_post_count += 1

            if not tasks:
                if banned_count == len(channels):
                    msg = "❌ جميع القنوات محظورة"
                elif no_post_count == len(channels) - banned_count:
                    msg = "📭 لا توجد منشورات للنشر"
                else:
                    msg = "📭 لا توجد منشورات صالحة للنشر"
                await safe_send(bot, user_id, msg)
                return

            async def run(task):
                async with _publish_semaphore:
                    # ✅ #26: timeout للـ limiter
                    try:
                        await asyncio.wait_for(PUBLISH_RATE_LIMITER.acquire(), timeout=PUBLISH_ACQUIRE_TIMEOUT)
                    except (asyncio.TimeoutError, Exception):
                        pass
                    result = await CallbackHandlers._publish_single(bot, task[0], task[1], task[2])
                    await asyncio.sleep(CallbackHandlers.PUBLISH_DELAY_SECONDS)
                    return result

            BATCH = CallbackHandlers.PUBLISH_BATCH_SIZE
            for i in range(0, len(tasks), BATCH):
                batch = tasks[i:i + BATCH]
                results = await asyncio.gather(*(run(t) for t in batch), return_exceptions=True)
                for r in results:
                    if r is True:
                        published += 1
                    else:
                        failed += 1

            summary = f"✅ تم نشر {published} | ❌ فشل {failed}"
            if lost_count:
                summary += f" | ⚠️ فقد {lost_count}"
            await safe_send(bot, user_id, summary)
        except Exception as e:
            logger.error(f"❌ _publish_all: {e}", exc_info=True)
            try:
                await safe_send(bot, user_id, f"❌ فشل النشر الجماعي: {str(e)[:100]}")
            except Exception:
                pass

    # =================================================================
    # عرض القوائم — ✅ #12 + #90
    # =================================================================

    @staticmethod
    async def _show_channel_list(update, context, query, user_id, lang=None):
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        channels = await DB.get_user_channels(user_id)
        if not channels:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(KeyboardFactory.get_text("ch_add", lang), callback_data=CB.CH_ADD)],
                [InlineKeyboardButton(KeyboardFactory.get_text("back", lang), callback_data=CB.BACK)],
            ])
            await safe_edit(query, "📭 لا توجد قنوات!", reply_markup=kb, bot=context.bot)
            return

        # ✅ #12: _coerce_int
        page = _coerce_int(context.user_data.get('channel_page'), 0)
        per_page = 5
        total_pages = max(1, (len(channels) + per_page - 1) // per_page)
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
        context.user_data['channel_page'] = page

        page_channels = channels[page * per_page:(page + 1) * per_page]
        start_index = page * per_page

        text = f"📡 <b>قنواتي</b>  ({len(channels)} قناة)\n"
        text += f"<i>صفحة {page + 1}/{total_pages}</i>\n\n"

        kb = []
        display_idx = start_index
        for ch in page_channels:
            chd = _row_to_dict(ch) or {}
            ch_id = chd.get('id')
            if ch_id is None:
                continue
            display_idx += 1
            number = _group_number(display_idx)
            st = "✅" if not chd.get('banned') else "🚫"
            raw_name = chd.get('channel_name') or f"قناة {display_idx}"
            name = raw_name[:35]

            text += f"{st} {number}  {name}\n"

            kb.append([
                InlineKeyboardButton(f"{number} 📌 اختيار", callback_data=f"{CB.CH_SEL}:{ch_id}"),
                InlineKeyboardButton(f"{number} 📅 جدولة", callback_data=f"sched_open:{ch_id}"),
            ])
            kb.append([
                InlineKeyboardButton(f"{number} 📊 إحصائيات", callback_data=f"{CB.CH_STATS}:{ch_id}"),
                InlineKeyboardButton(f"{number} 🗑️ حذف", callback_data=f"ch_del_confirm:{ch_id}"),
            ])

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="ch_page_prev"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("التالي ➡️", callback_data="ch_page_next"))
        if nav:
            kb.append(nav)

        kb.append([InlineKeyboardButton(KeyboardFactory.get_text("ch_add", lang), callback_data=CB.CH_ADD)])
        kb.append([InlineKeyboardButton(KeyboardFactory.get_text("back", lang), callback_data=CB.BACK)])

        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb),
                        parse_mode='HTML', bot=context.bot)

    @staticmethod
    async def _show_post_list(update, context, query, user_id, lang=None):
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        active = await DB.get_active_channel(user_id)
        if not active:
            await safe_edit(query, "❌ لا توجد قناة نشطة", bot=context.bot)
            return
        per_page = 5
        total = await DB.fetchval("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (active,), default=0)
        total_pages = max(1, (total + per_page - 1) // per_page)
        # ✅ #12: _coerce_int
        page = _coerce_int(context.user_data.get('post_page'), 0)
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
        context.user_data['post_page'] = page
        posts = await DB.fetchall(
            "SELECT id, text, published FROM posts WHERE channel_db_id=? "
            "ORDER BY created_at ASC LIMIT ? OFFSET ?",
            (active, per_page, page * per_page))
        text = f"📋 منشوراتي (صفحة {page + 1}/{total_pages})\n\n"
        kb = []
        for p in posts:
            pd = _row_to_dict(p) or {}
            pid = pd.get('id')
            if pid is None:
                continue
            text += f"🆔 {pid}: {(pd.get('text') or '')[:30]}\n"
            # ✅ #38: تأكيد الحذف
            kb.append([InlineKeyboardButton(f"🗑️ حذف {pid}", callback_data=f"post_del_confirm:{pid}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="post_page_prev"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("التالي ➡️", callback_data="post_page_next"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton("🔄 إعادة تدوير", callback_data=CB.POST_REC)])
        kb.append([InlineKeyboardButton("🧹 مسح الكل", callback_data=f"{CB.POST_CLEAR}_confirm")])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.BACK)])
        display_text = text if posts else "📭 لا يوجد منشورات"
        await safe_edit(query, display_text, reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    # =================================================================
    # معالجات الأمان — ✅ #30: Dead Code أُزيل
    # =================================================================

    @staticmethod
    async def _handle_security(update, context, query, user_id, lang=None):
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        data = query.data
        parts = data.split(":")

        # ✅ #17: لا effective_chat fallback
        chat_id = None
        if len(parts) >= 2 and parts[1].lstrip('-').isdigit():
            chat_id = int(parts[1])
        else:
            stored = context.user_data.get('security_chat_id') or context.user_data.get('sec_chat')
            if stored:
                try:
                    chat_id = int(stored)
                except (TypeError, ValueError):
                    chat_id = None

        if chat_id is None:
            await safe_edit(query, "❌ لم يتم تحديد المجموعة", bot=context.bot)
            return

        # ✅ #82: استخراج آمن للـ action
        prefix0 = parts[0]
        action = prefix0[4:] if prefix0.startswith("sec_") else prefix0

        if not await _check_sec_auth(context, user_id, chat_id):
            await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
            return

        try:
            # ─── تفعيل/تعطيل الكل (مع تأكيد) ✅ #3 ─────────────────
            if action in ("activate_all", "enable_all", "deactivate_all", "disable_all"):
                is_activate = action in ("activate_all", "enable_all")
                confirm_action = "activate_all_confirm" if is_activate else "deactivate_all_confirm"
                if is_activate:
                    confirm_text = await _trans("activate_all_confirmation", lang,
                                                "⚠️ هل أنت متأكد من تفعيل جميع الإعدادات الأمنية؟")
                else:
                    confirm_text = await _trans("deactivate_all_confirmation", lang,
                                                "⚠️ هل أنت متأكد من تعطيل جميع الإعدادات الأمنية؟")
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ نعم", callback_data=f"sec_{confirm_action}:{chat_id}")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data=f"{CB.GRP_SET}:{chat_id}")],
                ])
                await safe_edit(query, confirm_text, reply_markup=kb, bot=context.bot)
                return

            if action in ("activate_all_confirm", "deactivate_all_confirm"):
                is_activate = (action == "activate_all_confirm")
                # ✅ #20: transaction إن أمكن
                activate_values = dict(
                    delete_links=1, delete_mentions=1, slow_mode=1, slow_mode_seconds=5,
                    delete_videos=1, delete_audio=1, delete_animation=1,
                    delete_service=1, delete_documents=1, delete_stickers=1,
                    delete_forwarded=1, delete_polls=1, delete_games=1,
                    delete_voice=1, delete_video_note=1,
                    welcome_enabled=1, goodbye_enabled=1,
                    antiflood_enabled=1, antiflood_messages=5, antiflood_seconds=5,
                    antiflood_penalty="mute", antiflood_penalty_duration=60,
                    night_mode_enabled=1, night_mode_start="22:00", night_mode_end="06:00",
                    night_mode_action="mute", night_mode_action_duration=3600,
                    auto_approve_join=0, auto_reject_join=0, nsfw_enabled=0,
                    warn_enabled=1, max_warnings=3,
                    warn_penalty="mute", warn_penalty_duration=3600,
                    delete_banned_words=1, auto_penalty="mute",
                    delete_penalty="mute", delete_penalty_duration=3600,
                    violation_strikes=3, violation_duration=60,
                )
                deactivate_values = dict(
                    delete_links=0, delete_mentions=0, slow_mode=0, slow_mode_seconds=0,
                    delete_videos=0, delete_audio=0, delete_animation=0,
                    delete_service=0, delete_documents=0, delete_stickers=0,
                    delete_forwarded=0, delete_polls=0, delete_games=0,
                    delete_voice=0, delete_video_note=0,
                    welcome_enabled=0, goodbye_enabled=0,
                    antiflood_enabled=0, antiflood_messages=0, antiflood_seconds=0,
                    antiflood_penalty="none", antiflood_penalty_duration=0,
                    night_mode_enabled=0, night_mode_start="", night_mode_end="",
                    night_mode_action="none", night_mode_action_duration=0,
                    auto_approve_join=0, auto_reject_join=0, nsfw_enabled=0,
                    warn_enabled=0, max_warnings=0,
                    warn_penalty="none", warn_penalty_duration=0,
                    delete_banned_words=0, auto_penalty="none",
                    delete_penalty="none", delete_penalty_duration=0,
                    violation_strikes=0, violation_duration=0,
                )
                values = activate_values if is_activate else deactivate_values
                try:
                    if hasattr(DB, 'transaction'):
                        async with DB.transaction():
                            await DB.update_security_settings(chat_id, **values)
                    else:
                        await DB.update_security_settings(chat_id, **values)
                except Exception as ex:
                    logger.error(f"activate/deactivate failed: {ex}", exc_info=True)
                    await safe_edit(query, "❌ فشل تحديث الإعدادات", bot=context.bot)
                    return
                try:
                    await DB.execute(
                        "INSERT INTO admin_logs (admin_id, action, chat_id, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (user_id,
                         f"{'activate' if is_activate else 'deactivate'}_all_security",
                         chat_id, TimeUtils.utc_now()))
                except Exception:
                    pass
                await CallbackHandlers._refresh_security_view(query, context, chat_id, lang)
                return

            # ✅ #4: slow_mode_seconds أُزيل من toggle_map
            toggle_map = {
                "links": "delete_links", "mentions": "mentions", "slow": "slow_mode",
                "video": "delete_videos", "audio": "delete_audio",
                "anim": "delete_animation", "service": "delete_service",
                "doc": "delete_documents", "sticker": "delete_stickers",
                "forward": "delete_forwarded", "poll": "delete_polls",
                "game": "delete_games", "voice": "delete_voice",
                "videonote": "delete_video_note", "welcome": "welcome_enabled",
                "goodbye": "goodbye_enabled", "flood": "antiflood_enabled",
                "night": "night_mode_enabled",
                "approve_join": "auto_approve_join",
                "reject_join": "auto_reject_join", "nsfw": "nsfw_enabled",
            }

            if action in toggle_map:
                col = toggle_map[action]
                settings = await DB.get_security_settings(chat_id) or {}
                if not isinstance(settings, dict):
                    settings = _row_to_dict(settings) or {}
                new_val = 1 - _coerce_int(settings.get(col, 0))
                update_data = {col: new_val}
                if action == "approve_join" and new_val:
                    update_data['auto_reject_join'] = 0
                elif action == "reject_join" and new_val:
                    update_data['auto_approve_join'] = 0
                await DB.update_security_settings(chat_id, **update_data)
                await CallbackHandlers._refresh_security_view(query, context, chat_id, lang)
                return

            if action == "warn":
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تفعيل/تعطيل", callback_data=f"sec_warn_toggle:{chat_id}")],
                    [InlineKeyboardButton("🔢 عدد التحذيرات", callback_data=f"sec_warn_count:{chat_id}")],
                    [InlineKeyboardButton("⚖️ عقوبة التحذير", callback_data=f"sec_warn_penalty:{chat_id}")],
                    [InlineKeyboardButton("⏱️ مدة العقوبة", callback_data=f"sec_warn_penalty_duration:{chat_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")],
                ])
                await safe_edit(query, "⚠️ إدارة التحذيرات:", reply_markup=kb, bot=context.bot)
                return

            if action == "warn_penalty":
                await CallbackHandlers._show_warn_penalty_types(update, context, query, chat_id, lang)
                return

            if action == "warn_toggle":
                settings = await DB.get_security_settings(chat_id) or {}
                if not isinstance(settings, dict):
                    settings = _row_to_dict(settings) or {}
                new_val = 1 - _coerce_int(settings.get('warn_enabled', 0))
                await DB.update_security_settings(chat_id, warn_enabled=new_val)
                await CallbackHandlers._refresh_security_view(query, context, chat_id, lang)
                return

            if action == "warn_count":
                await CallbackHandlers._show_warn_count_buttons(update, context, query, chat_id, lang)
                return

            if action == "penalty":
                await CallbackHandlers._show_penalty_types(update, context, query, chat_id, lang)
                return

            if action == "del_pen":
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚫 حظر", callback_data=f"sec_set_del_penalty:ban:{chat_id}"),
                     InlineKeyboardButton("🔇 كتم", callback_data=f"sec_set_del_penalty:mute:{chat_id}")],
                    [InlineKeyboardButton("👢 طرد", callback_data=f"sec_set_del_penalty:kick:{chat_id}"),
                     InlineKeyboardButton("🔒 تقييد", callback_data=f"sec_set_del_penalty:restrict:{chat_id}")],
                    [InlineKeyboardButton("🚫 بدون عقوبة", callback_data=f"sec_set_del_penalty:none:{chat_id}")],
                    [InlineKeyboardButton("⏱️ مدة العقوبة", callback_data=f"sec_set_del_penalty_duration:{chat_id}")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")],
                ])
                await safe_edit(query, "🚫 اختر عقوبة الحذف:", reply_markup=kb, bot=context.bot)
                return

            if action == "banned_words":
                await CallbackHandlers._show_banned_words_menu(update, context, query, chat_id, lang)
                return

            if action == "toggle_banned_words":
                settings = await DB.get_security_settings(chat_id) or {}
                if not isinstance(settings, dict):
                    settings = _row_to_dict(settings) or {}
                new_val = 1 - _coerce_int(settings.get('delete_banned_words', 0))
                await DB.update_security_settings(chat_id, delete_banned_words=new_val)
                await CallbackHandlers._show_banned_words_menu(update, context, query, chat_id, lang)
                return

            if action in ("close", "back"):
                StateManager.clear(user_id)
                _clear_context_keys(context)
                await CallbackHandlers._show_groups_list(update, context, query, user_id, lang)
                return

            if action == "antiflood_settings":
                await CallbackHandlers._show_antiflood_settings(update, context, query, chat_id, lang)
                return

            if action == "night_settings":
                await CallbackHandlers._show_night_settings(update, context, query, chat_id, lang)
                return

            if action == "adv_act":
                await CallbackHandlers._show_advanced_actions(update, context, query, chat_id, lang)
                return

            # ✅ #3: slow_mode_seconds مستقل
            if action == "slow_mode_seconds":
                StateManager.set(user_id, UserState.WAIT_SLOW_MODE_SECONDS)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "⏱️ أرسل مدة الوضع البطيء بالثواني:", bot=context.bot)
                return

            if action == "welcome_text":
                StateManager.set(user_id, UserState.WAIT_WELCOME_TEXT)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "📝 أرسل نص الترحيب:", bot=context.bot)
                return

            if action == "goodbye_text":
                StateManager.set(user_id, UserState.WAIT_GOODBYE_TEXT)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "📝 أرسل نص الوداع:", bot=context.bot)
                return

            if action == "penalty_durations":
                await CallbackHandlers._show_all_penalty_durations_menu(query, context, chat_id)
                return

            if action == "set_antiflood_messages":
                StateManager.set(user_id, UserState.WAIT_ANTIFLOOD_MESSAGES)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "📊 أرسل عدد الرسائل المسموحة:", bot=context.bot)
                return

            if action == "set_antiflood_seconds":
                StateManager.set(user_id, UserState.WAIT_ANTIFLOOD_SECONDS)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "⏱️ أرسل عدد الثواني:", bot=context.bot)
                return

            if action == "antiflood_penalty":
                await CallbackHandlers._show_penalty_type_selection(update, context, query, chat_id, lang, 'antiflood_penalty')
                return

            if action == "set_night_start":
                StateManager.set(user_id, UserState.WAIT_NIGHT_START)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🌙 أرسل وقت البدء (HH:MM):", bot=context.bot)
                return

            if action == "set_night_end":
                StateManager.set(user_id, UserState.WAIT_NIGHT_END)
                context.user_data['sec_chat'] = chat_id
                await safe_edit(query, "🌙 أرسل وقت النهاية (HH:MM):", bot=context.bot)
                return

            if action == "night_action":
                await CallbackHandlers._show_penalty_type_selection(update, context, query, chat_id, lang, 'night_action')
                return

            if action in ("violation_settings", "violation_penalties"):
                await CallbackHandlers._show_violation_penalties(update, context, query, chat_id, lang)
                return

            if action == "violation_penalty":
                await CallbackHandlers._show_penalty_type_selection(update, context, query, chat_id, lang, 'violation_penalty')
                return

            logger.debug(f"⚠️ sec action غير معروف: {action}")
            await safe_edit(query, "⚠️ غير متوفر", bot=context.bot)

        except Exception as e:
            logger.error(f"خطأ في إعدادات الأمان: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    # =================================================================
    # دوال عرض الأمان
    # =================================================================

    @staticmethod
    async def _show_warn_count_buttons(update, context, query, chat_id, lang):
        settings = await DB.get_security_settings(chat_id) or {}
        if not isinstance(settings, dict):
            settings = _row_to_dict(settings) or {}
        current = _coerce_int(settings.get('max_warnings'), 3)
        text = f"🔢 <b>عدد التحذيرات قبل العقوبة</b>\n\nالحالي: <b>{current}</b>\n\nاختر العدد الجديد:"
        counts = [1, 2, 3, 4, 5, 10]
        kb = []
        row = []
        for n in counts:
            icon = "✅" if n == current else ""
            row.append(InlineKeyboardButton(f"{icon} {n}", callback_data=f"set_warn_count:{chat_id}:{n}"))
            if len(row) == 3:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"sec_warn:{chat_id}")])
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML', bot=context.bot)

    @staticmethod
    async def _show_warn_penalty_types(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚫 حظر", callback_data=f"set_warn_penalty:ban:{chat_id}"),
             InlineKeyboardButton("🔇 كتم", callback_data=f"set_warn_penalty:mute:{chat_id}")],
            [InlineKeyboardButton("👢 طرد", callback_data=f"set_warn_penalty:kick:{chat_id}"),
             InlineKeyboardButton("🔒 تقييد", callback_data=f"set_warn_penalty:restrict:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")],
        ])
        await safe_edit(query, "⚖️ اختر عقوبة تجاوز التحذيرات:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_banned_words_menu(update, context, query, chat_id, lang):
        settings = await DB.get_security_settings(chat_id) or {}
        if not isinstance(settings, dict):
            settings = _row_to_dict(settings) or {}
        is_enabled = _coerce_int(settings.get('delete_banned_words'), 0)
        toggle_text = "❌ تعطيل الحذف" if is_enabled else "✅ تفعيل الحذف"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"ban_add:{chat_id}"),
             InlineKeyboardButton("📋 القائمة", callback_data=f"ban_list:{chat_id}")],
            [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=f"ban_rem:{chat_id}")],
            [InlineKeyboardButton(toggle_text, callback_data=f"sec_toggle_banned_words:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")],
        ])
        await safe_edit(query, "🚫 إدارة الكلمات المحظورة:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_penalty_type_selection(update, context, query, chat_id, lang, setting_key):
        penalty_types = [
            ("🔇 كتم", "mute"), ("🚫 حظر", "ban"),
            ("👢 طرد", "kick"), ("🔒 تقييد", "restrict"),
            ("🚫 بدون عقوبة", "none"),
        ]
        kb = []
        for label, ptype in penalty_types:
            callback = f"sec_set_{setting_key}:{chat_id}:{ptype}"
            kb.append([InlineKeyboardButton(label, callback_data=callback)])
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")])
        await safe_edit(query, f"🚫 اختر نوع العقوبة لـ {setting_key.replace('_', ' ')}:",
                        reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    @staticmethod
    async def _show_all_penalty_durations_menu(query, context, chat_id):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏱️ مدة الكتم", callback_data=f"sec_set_mute_duration:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة الحظر", callback_data=f"sec_set_ban_duration:{chat_id}")],
            [InlineKeyboardButton("⏱️ مدة التقييد", callback_data=f"sec_set_restrict_duration:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة التحذير", callback_data=f"sec_warn_penalty_duration:{chat_id}")],
            [InlineKeyboardButton("⏱️ مدة الفيضان", callback_data=f"sec_antiflood_duration:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة الليل", callback_data=f"sec_night_duration:{chat_id}")],
            [InlineKeyboardButton("⏱️ مدة عقوبة الحذف", callback_data=f"sec_set_del_penalty_duration:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")],
        ])
        await safe_edit(query, "⏱️ اختر نوع العقوبة لتعديل مدتها:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_penalty_durations(update, context, query, chat_id, lang, penalty_type='mute'):
        if penalty_type == 'kick':
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")]
            ])
            await safe_edit(query, "ℹ️ الطرد (kick) لا يحتاج مدة — يُنفَّذ فوراً.", reply_markup=kb, bot=context.bot)
            return
        durations = [
            ("دائم", 0), ("نصف ساعة", 1800), ("ساعة", 3600),
            ("يوم", 86400), ("أسبوع", 604800), ("عشرة أيام", 864000), ("شهر", 2592000),
        ]
        kb = []
        for i in range(0, len(durations), 2):
            row = []
            name, secs = durations[i]
            row.append(InlineKeyboardButton(name, callback_data=f"set_duration:{penalty_type}:{chat_id}:{secs}"))
            if i + 1 < len(durations):
                name2, secs2 = durations[i + 1]
                row.append(InlineKeyboardButton(name2, callback_data=f"set_duration:{penalty_type}:{chat_id}:{secs2}"))
            kb.append(row)
        kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")])
        type_name = {
            'mute': 'كتم', 'ban': 'حظر', 'restrict': 'تقييد',
            'antiflood': 'الفيضان', 'night': 'الوضع الليلي',
            'warn_penalty': 'عقوبة التحذير', 'delete_penalty': 'عقوبة الحذف',
            'violation': 'عقوبات المخالفات',
        }.get(penalty_type, penalty_type)
        await safe_edit(query, f"⏱️ اختر مدة {type_name}:",
                        reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)

    @staticmethod
    async def _show_violation_penalties(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔢 عدد المخالفات", callback_data=f"sec_set_violation_strikes:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة العقوبة", callback_data=f"sec_set_violation_duration:{chat_id}")],
            [InlineKeyboardButton("⚖️ نوع العقوبة", callback_data=f"sec_violation_penalty:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")],
        ])
        await safe_edit(query, "🚨 إعدادات عقوبات المخالفات:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_antiflood_settings(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("عدد الرسائل", callback_data=f"sec_set_antiflood_messages:{chat_id}"),
             InlineKeyboardButton("الثواني", callback_data=f"sec_set_antiflood_seconds:{chat_id}")],
            [InlineKeyboardButton("نوع العقوبة", callback_data=f"sec_antiflood_penalty:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة العقوبة", callback_data=f"sec_antiflood_duration:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")],
        ])
        await safe_edit(query, "🌊 إعدادات الفيضان:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_night_settings(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("وقت البدء", callback_data=f"sec_set_night_start:{chat_id}"),
             InlineKeyboardButton("وقت النهاية", callback_data=f"sec_set_night_end:{chat_id}")],
            [InlineKeyboardButton("نوع الإجراء", callback_data=f"sec_night_action:{chat_id}"),
             InlineKeyboardButton("⏱️ مدة الإجراء", callback_data=f"sec_night_duration:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")],
        ])
        await safe_edit(query, "🌙 إعدادات الوضع الليلي:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_advanced_actions(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 تعطيل الكل", callback_data=f"sec_deactivate_all:{chat_id}"),
             InlineKeyboardButton("🟢 تفعيل الكل", callback_data=f"sec_activate_all:{chat_id}")],
            [InlineKeyboardButton("🚫 حظر", callback_data=f"act_ban:{chat_id}"),
             InlineKeyboardButton("🔇 كتم", callback_data=f"act_mute:{chat_id}")],
            [InlineKeyboardButton("👢 طرد", callback_data=f"act_kick:{chat_id}"),
             InlineKeyboardButton("🔒 تقييد", callback_data=f"act_restrict:{chat_id}")],
            [InlineKeyboardButton("🔓 فك الحظر", callback_data=f"act_unban:{chat_id}"),
             InlineKeyboardButton("⚠️ تحذير", callback_data=f"act_warn:{chat_id}")],
            [InlineKeyboardButton("📋 السجل", callback_data=f"act_log:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")],
        ])
        await safe_edit(query, "🛠️ الإجراءات المتقدمة:", reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_admin_logs(update, context, query, chat_id, lang):
        logs = await DB.get_admin_logs(chat_id, 10)
        if logs:
            lines = []
            for l in logs:
                ld = _row_to_dict(l) or {}
                lines.append(f"• {_safe_str(ld.get('admin_id'))} → {_safe_str(ld.get('action'))}")
            text = "📋 سجل المشرفين\n\n" + "\n".join(lines)
        else:
            text = "📭 لا يوجد"
        await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")]]), bot=context.bot)

    @staticmethod
    async def _show_penalty_types(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("حظر", callback_data=f"sec_penalty_ban:{chat_id}"),
             InlineKeyboardButton("كتم", callback_data=f"sec_penalty_mute:{chat_id}")],
            [InlineKeyboardButton("طرد", callback_data=f"sec_penalty_kick:{chat_id}"),
             InlineKeyboardButton("تقييد", callback_data=f"sec_penalty_restrict:{chat_id}")],
            [InlineKeyboardButton("بدون عقوبة", callback_data=f"sec_penalty_none:{chat_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CB.GRP_SET}:{chat_id}")],
        ])
        await safe_edit(query, "🚫 اختر نوع العقوبة:", reply_markup=kb, bot=context.bot)

    # =================================================================
    # معالجات الأدمن
    # =================================================================

    @staticmethod
    async def _handle_admin(update, context, query, user_id, lang=None):
        if not CONFIG.is_developer(user_id):
            await safe_edit(query, "❌ غير مصرح", bot=context.bot)
            return
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        data = query.data

        try:
            if data == "admin_grant_free":
                StateManager.set(user_id, UserState.WAIT_GRANT_FREE)
                await safe_edit(query, "🎁 أرسل: معرف_المستخدم عدد_الأيام", bot=context.bot)
                return

            if data == "admin_ban_user":
                StateManager.set(user_id, UserState.WAIT_BAN_USER_ID)
                await safe_edit(query,
                                "🚫 <b>حظر مستخدم</b>\n\nأرسل معرف المستخدم (ID) لحظره:\n<i>مثال: 123456789</i>",
                                bot=context.bot)
                return

            if data == "admin_unban_user":
                StateManager.set(user_id, UserState.WAIT_UNBAN_USER_ID)
                await safe_edit(query,
                                "✅ <b>فك حظر مستخدم</b>\n\nأرسل معرف المستخدم (ID) لفك حظره:\n<i>مثال: 123456789</i>",
                                bot=context.bot)
                return

            if data == CB.ADMIN_USERS:
                try:
                    stats = await DB.get_user_stats() or {}
                    if not isinstance(stats, dict):
                        stats = _row_to_dict(stats) or {}
                except Exception:
                    stats = {}
                text = f"👥 المستخدمون\n\n👥 الإجمالي: {stats.get('users', 0)}\n⛔ المحظورون: {stats.get('banned', 0)}"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⛔ المحظورين", callback_data=CB.ADMIN_BANNED)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_BANNED:
                banned_users = await DB.fetchall("SELECT user_id FROM users WHERE banned=1 LIMIT 20")
                if banned_users:
                    text = "⛔ المحظورين\n\n" + "\n".join(
                        _safe_str((_row_to_dict(u) or {}).get('user_id')) for u in banned_users)
                else:
                    text = "📭 لا يوجد محظورون"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ فك حظر الكل", callback_data=CB.ADMIN_UNBAN_ALL)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_UNBAN_ALL:
                await DB.execute("UPDATE users SET banned=0 WHERE banned=1")
                await safe_edit(query, "✅ تم إلغاء حظر الجميع", bot=context.bot)
                return

            if data == CB.ADMIN_STATS:
                try:
                    stats = await DB.get_general_stats() or {}
                    if not isinstance(stats, dict):
                        stats = _row_to_dict(stats) or {}
                except Exception:
                    stats = {}
                text = (f"📊 إحصائيات عامة\n\n"
                        f"👥 المستخدمون: {stats.get('users', 0)}\n"
                        f"📡 القنوات: {stats.get('channels', 0)}\n"
                        f"👥 المجموعات: {stats.get('groups', 0)}\n"
                        f"📝 المنشورات: {stats.get('posts', 0)}\n"
                        f"✅ المنشورة: {stats.get('published', 0)}\n"
                        f"🧾 الفواتير: {stats.get('invoices', 0)}\n"
                        f"🎫 التذاكر المعلقة: {stats.get('tickets', 0)}")
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)]])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_CHANNELS:
                context.user_data['adm_ch_page'] = 0
                await CallbackHandlers._show_admin_channels(update, context, query, user_id, lang)
                return

            # ✅ #94: SQL toggle ذرّي
            if data.startswith("admin_toggle_ch:"):
                ch_db_id = _coerce_int(data.split(":")[-1])
                if ch_db_id <= 0:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return
                await DB.execute("UPDATE user_channels SET banned = 1 - banned WHERE id=?", (ch_db_id,))
                await CallbackHandlers._show_admin_channels(update, context, query, user_id, lang)
                return

            if data == CB.ADMIN_GROUPS:
                context.user_data['adm_gr_page'] = 0
                await CallbackHandlers._show_admin_groups(update, context, query, user_id, lang)
                return

            if data.startswith("admin_toggle_gr:"):
                chat_id = _coerce_int(data.split(":")[-1])
                if chat_id == 0:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return
                row = await DB.fetchone("SELECT banned FROM bot_groups WHERE chat_id=?", (chat_id,))
                row_d = _row_to_dict(row) or {}
                if row_d:
                    new_val = 0 if row_d.get('banned') else 1
                    if new_val == 1:
                        try:
                            await context.bot.leave_chat(chat_id)
                        except Exception:
                            pass
                    await DB.execute("UPDATE bot_groups SET banned=? WHERE chat_id=?", (new_val, chat_id))
                await CallbackHandlers._show_admin_groups(update, context, query, user_id, lang)
                return

            if data == CB.ADMIN_ADD_ADMIN:
                StateManager.set(user_id, UserState.WAIT_ADMIN_ADD)
                await safe_edit(query, "👑 أرسل معرف المشرف:", bot=context.bot)
                return

            if data == CB.ADMIN_REM_ADMIN:
                StateManager.set(user_id, UserState.WAIT_ADMIN_REM)
                await safe_edit(query, "🗑️ أرسل معرف المشرف:", bot=context.bot)
                return

            if data == CB.ADMIN_LIST_ADMINS:
                admins = await DB.get_admin_list()
                if admins:
                    text = "👑 المشرفون\n\n" + "\n".join(
                        f"• {_safe_str((_row_to_dict(a) or {}).get('user_id'))}" for a in admins)
                else:
                    text = "📭 لا يوجد"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إضافة", callback_data=CB.ADMIN_ADD_ADMIN),
                     InlineKeyboardButton("🗑️ إزالة", callback_data=CB.ADMIN_REM_ADMIN)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_BROADCAST:
                StateManager.set(user_id, UserState.WAIT_BROADCAST)
                await safe_edit(query, "📨 أرسل الرسالة:", bot=context.bot)
                return

            if data == CB.ADMIN_INVOICES:
                invoices = await DB.fetchall("SELECT number, amount, status FROM invoices ORDER BY id DESC LIMIT 20")
                if invoices:
                    lines = []
                    for i in invoices:
                        id_ = _row_to_dict(i) or {}
                        lines.append(f"• {_safe_str(id_.get('number'))} - {_safe_str(id_.get('amount'), '0')} ⭐ - {_safe_str(id_.get('status'))}")
                    text = "🧾 الفواتير\n\n" + "\n".join(lines)
                else:
                    text = "📭 لا توجد"
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)]])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_BACKUP:
                await safe_edit(query, "⏳ جاري إنشاء النسخة الاحتياطية...", bot=context.bot)
                task = asyncio.create_task(CallbackHandlers._do_backup(context, user_id))
                ACTIVE_TASKS.add(task)
                task.add_done_callback(ACTIVE_TASKS.discard)
                return

            if data in (CB.ADMIN_RESTORE, CB.ADMIN_RESTORE_SEL):
                await CallbackHandlers._show_restore_backups(update, context, query, user_id)
                return

            if data.startswith("admin_restore_file:"):
                fname = data.split(":", 1)[1]
                backup_file = PATHS.BACKUPS / fname
                try:
                    resolved = backup_file.resolve(strict=False)
                    base = PATHS.BACKUPS.resolve(strict=False)
                except OSError as ex:
                    logger.warning(f"resolve failed: {ex}")
                    await safe_edit(query, "❌ تعذر التحقق من الملف", bot=context.bot)
                    return
                if resolved.parent != base:
                    await safe_edit(query, "❌ مسار غير صالح", bot=context.bot)
                    return
                if not backup_file.exists():
                    await safe_edit(query, "❌ الملف غير موجود", bot=context.bot)
                    return
                try:
                    pre_restore_backup = (PATHS.BACKUPS /
                                          f"pre_restore_{TimeUtils.mecca_now().strftime('%Y%m%d_%H%M%S_%f')}.db")
                    shutil.copy2(PATHS.DB, pre_restore_backup)

                    # ✅ #18: إغلاق DB
                    db_closed = False
                    try:
                        close_fn = getattr(DB, 'close', None)
                        if callable(close_fn):
                            await close_fn()
                            db_closed = True
                    except Exception:
                        pass

                    shutil.copy2(backup_file, PATHS.DB)

                    if db_closed:
                        try:
                            reconnect = getattr(DB, 'reconnect', None) or getattr(DB, 'connect', None)
                            if callable(reconnect):
                                await reconnect()
                        except Exception:
                            pass

                    await safe_edit(query, "✅ تمت الاستعادة بنجاح! يُنصح بإعادة تشغيل البوت.", bot=context.bot)
                except Exception as e:
                    await safe_edit(query, f"❌ فشل الاستعادة: {str(e)[:100]}", bot=context.bot)
                return

            if data == CB.ADMIN_RAM:
                ram = get_ram_usage() or {}
                text = (f"🖥️ الرام\n\n"
                        f"💾 الإجمالي: {ram.get('total', 0)} GB\n"
                        f"📊 المستخدم: {ram.get('used', 0)} GB\n"
                        f"📈 النسبة: {ram.get('percent', 0)}%")
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_METRICS:
                try:
                    stats = await DB.get_general_stats() or {}
                    if not isinstance(stats, dict):
                        stats = _row_to_dict(stats) or {}
                except Exception:
                    stats = {}
                try:
                    db_size = PATHS.DB.stat().st_size / 1024
                except Exception:
                    db_size = 0
                text = (f"📊 مقاييس النظام\n\n"
                        f"👥 المستخدمون: {stats.get('users', 0)}\n"
                        f"📡 القنوات: {stats.get('channels', 0)}\n"
                        f"👥 المجموعات: {stats.get('groups', 0)}\n"
                        f"📝 المنشورات: {stats.get('posts', 0)}\n"
                        f"✅ المنشورة: {stats.get('published', 0)}\n"
                        f"🧾 الفواتير: {stats.get('invoices', 0)}\n"
                        f"🎫 تذاكر معلقة: {stats.get('tickets', 0)}\n"
                        f"💾 حجم قاعدة البيانات: {db_size:.1f} KB")
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_UPTIME:
                uptime = time.monotonic() - context.bot_data.get('start_time', time.monotonic())
                hours, remainder = divmod(uptime, 3600)
                minutes, seconds = divmod(remainder, 60)
                text = f"⏳ فترة التشغيل: {int(hours)} ساعة {int(minutes)} دقيقة {int(seconds)} ثانية"
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_TICKETS:
                tickets = await DB.get_tickets()
                if tickets:
                    lines = []
                    for t in tickets[:10]:
                        td = _row_to_dict(t) or {}
                        lines.append(f"• #{_safe_str(td.get('ticket_number'))} - {_safe_str(td.get('user_id'))}: {_safe_str(td.get('message'), '')[:50]}")
                    text = "🎫 التذاكر المعلقة\n\n" + "\n".join(lines)
                else:
                    text = "📭 لا توجد تذاكر"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑️ حذف الكل", callback_data=CB.ADMIN_DEL_TICKETS)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_DEL_TICKETS:
                await DB.delete_all_tickets()
                await safe_edit(query, "✅ تم حذف جميع التذاكر", bot=context.bot)
                return

            if data == CB.ADMIN_PAYMENT_LOGS:
                logs = await DB.fetchall(
                    "SELECT user_id, event_type, created_at FROM payment_logs ORDER BY id DESC LIMIT 20")
                if logs:
                    lines = []
                    for l in logs:
                        ld = _row_to_dict(l) or {}
                        lines.append(f"• {_safe_str(ld.get('user_id'))} - {_safe_str(ld.get('event_type'))} ({_safe_str(ld.get('created_at'))})")
                    text = "💳 سجلات الدفع\n\n" + "\n".join(lines)
                else:
                    text = "📭 لا توجد"
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_SET_UPDATE_CH:
                StateManager.set(user_id, UserState.WAIT_UPDATE_CH)
                await safe_edit(query, "📢 أرسل معرف قناة التحديثات:", bot=context.bot)
                return

            if data == CB.ADMIN_SEND_UPDATE:
                StateManager.set(user_id, UserState.WAIT_UPDATE)
                await safe_edit(query, "📝 أرسل نص التحديث:", bot=context.bot)
                return

            if data == CB.ADMIN_SHOW_UPDATE:
                ch = await DB.get_updates_channel()
                text = f"📢 قناة التحديثات: {ch}" if ch else "📭 لم يتم تعيين قناة تحديثات"
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_SET_LOG_CH:
                StateManager.set(user_id, UserState.WAIT_LOG_CH)
                await safe_edit(query, "📋 أرسل معرف قناة السجلات:", bot=context.bot)
                return

            if data == CB.ADMIN_LOG_CH:
                ch = await DB.get_log_channel()
                text = f"📋 قناة السجلات: {ch}" if ch else "📭 لم يتم تعيين قناة سجلات"
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_FORCE_SUB:
                sub = await DB.get_force_subscribe_channel()
                text = f"🔒 الاشتراك الإجباري: {'✅ مفعل' if sub else '❌ معطل'}\n"
                if sub:
                    text += f"القناة: {sub}"
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_SET_FORCE:
                StateManager.set(user_id, UserState.WAIT_FORCE)
                await safe_edit(query, "🔒 أرسل معرف قناة الاشتراك الإجباري:", bot=context.bot)
                return

            if data == "admin_disable_force":
                await DB.execute("UPDATE settings SET value = '' WHERE key = 'force_subscribe_channel'")
                try:
                    _invalidate_force_sub_cache()
                except Exception:
                    pass
                await safe_edit(query, "✅ تم تعطيل الاشتراك الإجباري", bot=context.bot)
                return

            if data == "admin_upload_backup":
                StateManager.set(user_id, UserState.WAIT_BACKUP_FILE)
                await safe_edit(query, "📤 أرسل ملف النسخ الاحتياطي بصيغة .db:", bot=context.bot)
                return

            if data == "admin_show_backups":
                await CallbackHandlers._show_restore_backups(update, context, query, user_id)
                return

            if data == CB.ADMIN_REFRESH_CACHE:
                _invalidate_sec_auth_cache()
                await invalidate_user_cache(user_id)
                await safe_edit(query, "🔄 تم تحديث الكاش", bot=context.bot)
                return

            if data == CB.ADMIN_BANNED_CH:
                banned_channels = await DB.fetchall(
                    "SELECT channel_id, channel_name FROM user_channels WHERE banned=1 LIMIT 20")
                if banned_channels:
                    lines = []
                    for c in banned_channels:
                        cd = _row_to_dict(c) or {}
                        lines.append(f"• {_safe_str(cd.get('channel_name'))} ({_safe_str(cd.get('channel_id'))})")
                    text = "🚫 القنوات المحظورة\n\n" + "\n".join(lines)
                else:
                    text = "📭 لا توجد"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ تفعيل الكل", callback_data=CB.ADMIN_ACTIVATE_CH)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_ACTIVATE_CH:
                await DB.execute("UPDATE user_channels SET banned=0 WHERE banned=1")
                await safe_edit(query, "✅ تم تفعيل جميع القنوات", bot=context.bot)
                return

            if data == CB.ADMIN_BANNED_GR:
                banned_groups = await DB.fetchall(
                    "SELECT chat_id, chat_name FROM bot_groups WHERE banned=1 LIMIT 20")
                if banned_groups:
                    lines = []
                    for g in banned_groups:
                        gd = _row_to_dict(g) or {}
                        lines.append(f"• {_safe_str(gd.get('chat_name'))} ({_safe_str(gd.get('chat_id'))})")
                    text = "🚫 المجموعات المحظورة\n\n" + "\n".join(lines)
                else:
                    text = "📭 لا توجد"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CB.ADMIN_UNBAN_GR)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if data == CB.ADMIN_UNBAN_GR:
                await DB.execute("UPDATE bot_groups SET banned=0 WHERE banned=1")
                await safe_edit(query, "✅ تم إلغاء حظر جميع المجموعات", bot=context.bot)
                return

            if data == CB.ADMIN_REPLIES:
                replies = await DB.fetchall("SELECT keyword FROM auto_replies WHERE chat_id=-1 LIMIT 30")
                if replies:
                    lines = []
                    for r in replies:
                        rd = _row_to_dict(r) or {}
                        lines.append(f"• {_safe_str(rd.get('keyword'))}")
                    text = "💬 الردود العامة\n\n" + "\n".join(lines)
                else:
                    text = "📭 لا توجد"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إضافة", callback_data="admin_add_reply"),
                     InlineKeyboardButton("🗑️ حذف", callback_data="admin_del_reply")],
                    [InlineKeyboardButton("📤 تصدير", callback_data=CB.ADMIN_EXPORT_REPLIES),
                     InlineKeyboardButton("📥 استيراد", callback_data=CB.ADMIN_IMPORT_REPLIES)],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            # ✅ #6: يضبط auto_chat
            if data == "admin_add_reply":
                StateManager.set(user_id, UserState.WAIT_KEYWORD)
                context.user_data['auto_chat'] = -1
                await safe_edit(query, "📝 أرسل الكلمة:", bot=context.bot)
                return

            if data == "admin_del_reply":
                StateManager.set(user_id, UserState.WAIT_AUTO_DEL)
                context.user_data['auto_chat'] = -1
                await safe_edit(query, "🗑️ أرسل الكلمة:", bot=context.bot)
                return

            if data == "admin_list_replies":
                replies = await DB.fetchall("SELECT keyword FROM auto_replies WHERE chat_id=-1 LIMIT 50")
                if replies:
                    lines = []
                    for r in replies:
                        rd = _row_to_dict(r) or {}
                        lines.append(f"• {_safe_str(rd.get('keyword'))}")
                    text = "📋 قائمة الردود العامة\n\n" + "\n".join(lines)
                else:
                    text = "📭 لا توجد"
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_EXPORT_REPLIES:
                try:
                    file_path = await DB.export_auto_replies_to_file()
                except (AttributeError, Exception):
                    file_path = None
                if file_path:
                    try:
                        with open(file_path, 'rb') as f:
                            await context.bot.send_document(chat_id=user_id, document=f, filename=Path(file_path).name)
                    except Exception as e:
                        await safe_send(context.bot, user_id, f"❌ فشل الإرسال: {e}")
                    finally:
                        try:
                            os.remove(file_path)
                        except OSError:
                            pass
                else:
                    await safe_edit(query, "📭 لا توجد ردود", bot=context.bot)
                return

            if data == CB.ADMIN_IMPORT_REPLIES:
                StateManager.set(user_id, UserState.WAIT_IMPORT_FILE)
                await safe_edit(query, "📤 أرسل ملف JSON:", bot=context.bot)
                return

            if data == CB.ADMIN_IMPORT_GITHUB:
                StateManager.set(user_id, UserState.WAIT_GITHUB_URL)
                await safe_edit(query, "📥 أرسل الرابط:", bot=context.bot)
                return

            if data == CB.ADMIN_BANNED_WORDS:
                words = await DB.get_banned_words(-1)
                if words:
                    text = "🚫 الكلمات المحظورة العامة\n\n" + "\n".join(f"• {w}" for w in words[:30])
                else:
                    text = "📭 لا توجد"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إضافة", callback_data="admin_add_banned"),
                     InlineKeyboardButton("🗑️ حذف", callback_data="admin_rem_banned")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)],
                ])
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            # ✅ #6: يضبط ban_chat
            if data == "admin_add_banned":
                StateManager.set(user_id, UserState.WAIT_GLOBAL_BAN)
                context.user_data['ban_chat'] = -1
                await safe_edit(query, "📝 أرسل الكلمة:", bot=context.bot)
                return

            if data == "admin_rem_banned":
                StateManager.set(user_id, UserState.WAIT_REM_GLOBAL_BAN)
                context.user_data['ban_chat'] = -1
                await safe_edit(query, "🗑️ أرسل الكلمة:", bot=context.bot)
                return

            if data == "admin_list_banned":
                words = await DB.get_banned_words(-1)
                if words:
                    text = "📋 قائمة الكلمات المحظورة العامة\n\n" + "\n".join(f"• {w}" for w in words)
                else:
                    text = "📭 لا توجد"
                await safe_edit(query, text, bot=context.bot)
                return

            if data == CB.ADMIN_CREATE_CONTEST:
                StateManager.set(user_id, UserState.WAIT_CONTEST_TITLE)
                await safe_edit(query, "🏆 أرسل العنوان:", bot=context.bot)
                return

            if data == CB.ADMIN_DECLARE_WINNER:
                contests = await DB.get_active_contests(5)
                if not contests:
                    await safe_edit(query, "📭 لا توجد مسابقات نشطة", bot=context.bot)
                    return
                kb = []
                for c in contests:
                    cd = _row_to_dict(c) or {}
                    kb.append([InlineKeyboardButton(
                        f"🏆 {_safe_str(cd.get('title'))[:20]}",
                        callback_data=f"{CB.DECLARE_WINNER_SEL}:{cd.get('id', 0)}")])
                kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
                await safe_edit(query, "🏆 اختر المسابقة:", reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)
                return

            if data == CB.ADMIN_DEL_CONTEST:
                contests = await DB.fetchall("SELECT id, title FROM contests WHERE status='active' LIMIT 10")
                if not contests:
                    await safe_edit(query, "📭 لا توجد مسابقات", bot=context.bot)
                    return
                kb = []
                for c in contests:
                    cd = _row_to_dict(c) or {}
                    kb.append([InlineKeyboardButton(
                        f"🗑️ {_safe_str(cd.get('title'))[:20]}",
                        callback_data=f"admin_delete_contest:{cd.get('id', 0)}")])
                kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
                await safe_edit(query, "🗑️ اختر المسابقة للحذف:", reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)
                return

            if data.startswith("admin_delete_contest:"):
                contest_id = _coerce_int(data.split(":")[-1])
                if await DB.delete_contest(contest_id, user_id):
                    await safe_edit(query, "✅ تم حذف المسابقة", bot=context.bot)
                else:
                    await safe_edit(query, "❌ فشل", bot=context.bot)
                return

            await safe_edit(query, "⚠️ غير متوفر", bot=context.bot)

        except BadRequest as e:
            if "query is too old" not in str(e).lower():
                logger.error(f"خطأ في لوحة الأدمن: {e}", exc_info=True)
                await safe_edit(query, "❌ حدث خطأ", bot=context.bot)
        except Exception as e:
            logger.error(f"خطأ في لوحة الأدمن: {e}", exc_info=True)
            try:
                await safe_edit(query, "❌ حدث خطأ", bot=context.bot)
            except Exception:
                pass

    # ✅ #27: pagination
    @staticmethod
    async def _show_admin_channels(update, context, query, user_id, lang):
        try:
            total = await DB.fetchval("SELECT COUNT(*) FROM user_channels", default=0)
            page = _coerce_int(context.user_data.get('adm_ch_page'), 0)
            total_pages = max(1, (total + ADMIN_PAGE_SIZE - 1) // ADMIN_PAGE_SIZE)
            if page >= total_pages:
                page = total_pages - 1
            if page < 0:
                page = 0
            context.user_data['adm_ch_page'] = page

            channels = await DB.fetchall(
                "SELECT id, channel_id, channel_name, banned FROM user_channels "
                "ORDER BY channel_name LIMIT ? OFFSET ?",
                (ADMIN_PAGE_SIZE, page * ADMIN_PAGE_SIZE))

            kb = []
            for c in (channels or []):
                cd = _row_to_dict(c) or {}
                action = "🔓 فك حظر" if cd.get('banned') else "🔒 حظر"
                icon = "🚫" if cd.get('banned') else "✅"
                kb.append([InlineKeyboardButton(
                    f"{icon} {_safe_str(cd.get('channel_name'))[:20]} - {action}",
                    callback_data=f"admin_toggle_ch:{cd.get('id', 0)}")])

            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"adm_ch_page:{page - 1}"))
            if page < total_pages - 1:
                nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"adm_ch_page:{page + 1}"))
            if nav:
                kb.append(nav)

            kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
            text = f"📡 إدارة القنوات ({total}) — صفحة {page + 1}/{total_pages}\n\nاضغط على القناة للتبديل:"
            await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)
        except Exception as e:
            logger.error(f"_show_admin_channels: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    @staticmethod
    async def _show_admin_groups(update, context, query, user_id, lang):
        try:
            total = await DB.fetchval("SELECT COUNT(*) FROM bot_groups", default=0)
            page = _coerce_int(context.user_data.get('adm_gr_page'), 0)
            total_pages = max(1, (total + ADMIN_PAGE_SIZE - 1) // ADMIN_PAGE_SIZE)
            if page >= total_pages:
                page = total_pages - 1
            if page < 0:
                page = 0
            context.user_data['adm_gr_page'] = page

            groups = await DB.fetchall(
                "SELECT chat_id, chat_name, banned FROM bot_groups "
                "ORDER BY chat_name LIMIT ? OFFSET ?",
                (ADMIN_PAGE_SIZE, page * ADMIN_PAGE_SIZE))

            kb = []
            for g in (groups or []):
                gd = _row_to_dict(g) or {}
                action = "🔓 فك حظر" if gd.get('banned') else "🔒 حظر"
                icon = "🚫" if gd.get('banned') else "✅"
                kb.append([InlineKeyboardButton(
                    f"{icon} {_safe_str(gd.get('chat_name'))[:20]} - {action}",
                    callback_data=f"admin_toggle_gr:{gd.get('chat_id', 0)}")])

            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"adm_gr_page:{page - 1}"))
            if page < total_pages - 1:
                nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"adm_gr_page:{page + 1}"))
            if nav:
                kb.append(nav)

            kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
            text = f"👥 إدارة المجموعات ({total}) — صفحة {page + 1}/{total_pages}\n\nاضغط على المجموعة للتبديل:"
            await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)
        except Exception as e:
            logger.error(f"_show_admin_groups: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    @staticmethod
    async def _show_restore_backups(update, context, query, user_id):
        def _safe_mtime(p):
            try:
                return p.stat().st_mtime
            except (OSError, FileNotFoundError):
                return 0

        try:
            backups = sorted(PATHS.BACKUPS.glob("backup_*.db"),
                             key=_safe_mtime, reverse=True)
            if not backups:
                await safe_edit(query, "📭 لا توجد نسخ احتياطية", bot=context.bot)
                return
            kb = []
            for b in backups[:10]:
                fname = b.name
                kb.append([InlineKeyboardButton(f"📁 {fname}", callback_data=f"admin_restore_file:{fname}")])
            kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=CB.ADMIN)])
            await safe_edit(query, "📂 اختر نسخة احتياطية للاستعادة:",
                            reply_markup=InlineKeyboardMarkup(kb), bot=context.bot)
        except Exception as e:
            logger.error(f"_show_restore_backups: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    # =================================================================
    # الردود التلقائية — ✅ #7
    # =================================================================

    @staticmethod
    async def _handle_auto_reply(update, context, query, user_id, lang=None):
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        data = query.data
        parts = data.split(":")
        action = parts[0].replace("auto_reply_", "")

        chat_id = None
        if len(parts) >= 2:
            p = parts[1].strip()
            if p.lstrip('-').isdigit():
                chat_id = int(p)
        if chat_id is None:
            stored = context.user_data.get('auto_chat')
            if stored is not None:
                try:
                    chat_id = int(stored)
                except (TypeError, ValueError):
                    chat_id = None

        if chat_id is None:
            await safe_edit(query, "❌ لم يتم تحديد المجموعة", bot=context.bot)
            return

        # ✅ #7: -1 للمطور فقط
        if chat_id == -1:
            if not CONFIG.is_developer(user_id):
                await safe_edit(query, "❌ غير مصرح", bot=context.bot)
                return
        else:
            if not await is_authorized_in_group(context.bot, chat_id, user_id):
                await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                return

        try:
            if action == "menu":
                kb = KeyboardFactory.build("auto_reply", chat_id=chat_id, lang=lang)
                await safe_edit(query, "🤖 إعدادات الردود التلقائية:", reply_markup=kb, bot=context.bot)
                return

            if action == "toggle":
                settings = await DB.get_auto_reply_settings(chat_id) or {}
                if not isinstance(settings, dict):
                    settings = _row_to_dict(settings) or {}
                new_status = not settings.get('enabled', False)
                await DB.update_auto_reply_settings(chat_id, enabled=new_status)
                kb = KeyboardFactory.build("auto_reply", chat_id=chat_id, lang=lang)
                text = (f"🤖 إعدادات الردود التلقائية\n\n"
                        f"الحالة: {'✅ مفعلة' if new_status else '❌ معطلة'}\n"
                        f"للمشرفين فقط: {'✅ نعم' if settings.get('only_admins') else '❌ لا'}")
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if action == "admins":
                settings = await DB.get_auto_reply_settings(chat_id) or {}
                if not isinstance(settings, dict):
                    settings = _row_to_dict(settings) or {}
                new_status = not settings.get('only_admins', 0)
                await DB.update_auto_reply_settings(chat_id, only_admins=new_status)
                kb = KeyboardFactory.build("auto_reply", chat_id=chat_id, lang=lang)
                text = (f"🤖 إعدادات الردود التلقائية\n\n"
                        f"الحالة: {'✅ مفعلة' if settings.get('enabled') else '❌ معطلة'}\n"
                        f"للمشرفين فقط: {'✅ نعم' if new_status else '❌ لا'}")
                await safe_edit(query, text, reply_markup=kb, bot=context.bot)
                return

            if action == "add":
                StateManager.set(user_id, UserState.WAIT_AUTO_KEY)
                context.user_data['auto_chat'] = chat_id
                await safe_edit(query, "📝 أرسل الكلمة:", bot=context.bot)
                return

            if action == "del":
                StateManager.set(user_id, UserState.WAIT_AUTO_DEL)
                context.user_data['auto_chat'] = chat_id
                await safe_edit(query, "🗑️ أرسل الكلمة:", bot=context.bot)
                return

            # ✅ #39: تأكيد
            if action == "reset":
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑️ نعم احذف الكل", callback_data=f"auto_reply_reset_confirm:{chat_id}")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data=f"auto_reply_menu:{chat_id}")],
                ])
                await safe_edit(query, "⚠️ هل أنت متأكد من حذف جميع الردود؟\n<i>لا يمكن التراجع.</i>",
                                reply_markup=kb, parse_mode='HTML', bot=context.bot)
                return

            if action == "reset_confirm":
                await DB.reset_auto_replies(chat_id)
                await safe_edit(query, "✅ تم حذف كل الردود", bot=context.bot)
                return

            if action == "list":
                rows = await DB.fetchall("SELECT keyword FROM auto_replies WHERE chat_id=? LIMIT 20", (chat_id,))
                if rows:
                    lines = []
                    for r in rows:
                        rd = _row_to_dict(r) or {}
                        lines.append(f"• {_safe_str(rd.get('keyword'))}")
                    text = "📋 الردود\n\n" + "\n".join(lines)
                else:
                    text = "📭 لا يوجد"
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 رجوع", callback_data=f"auto_reply_menu:{chat_id}")]]), bot=context.bot)
                return

            if action == "stats":
                stats = await DB.get_auto_reply_stats(chat_id, 20)
                if stats:
                    text = "📊 إحصائيات الردود\n\n"
                    for s in stats:
                        sd = _row_to_dict(s) or {}
                        source = "🌐 عام" if sd.get('source') == 'global' else "👥 مجموعة"
                        text += f"• {_safe_str(sd.get('keyword'))} ({source}): {sd.get('usage_count', 0)} استخدام\n"
                else:
                    text = "📭 لا توجد ردود"
                await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 رجوع", callback_data=f"auto_reply_menu:{chat_id}")]]), bot=context.bot)
                return

            await safe_edit(query, "⚠️ غير معروف", bot=context.bot)
        except Exception as e:
            logger.error(f"خطأ في الردود التلقائية: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    # =================================================================
    # الجدولة
    # =================================================================

    @staticmethod
    async def _handle_schedule(update, context, query, user_id):
        data = query.data
        parts = data.split(":")
        if len(parts) < 2:
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        action = parts[0].replace("sched_", "")
        try:
            ch_id = int(parts[1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        if not await _is_channel_owner(user_id, ch_id):
            await safe_edit(query, "❌ لا تملك هذه القناة", bot=context.bot)
            return
        try:
            if action == "open":
                await CallbackHandlers._show_schedule_menu(update, context, query, ch_id, user_id)
                return
            if action == "min":
                StateManager.set(user_id, UserState.WAIT_MIN)
                context.user_data['schedule_ch'] = ch_id
                await safe_edit(query, "📅 أرسل الدقائق:", bot=context.bot)
                return
            if action == "hour":
                StateManager.set(user_id, UserState.WAIT_HOUR)
                context.user_data['schedule_ch'] = ch_id
                await safe_edit(query, "📅 أرسل الساعات:", bot=context.bot)
                return
            if action == "day":
                StateManager.set(user_id, UserState.WAIT_DAY)
                context.user_data['schedule_ch'] = ch_id
                await safe_edit(query, "📅 أرسل الأيام:", bot=context.bot)
                return
            if action == "time":
                StateManager.set(user_id, UserState.WAIT_PUB_TIME)
                context.user_data['schedule_ch'] = ch_id
                await safe_edit(query, "🕐 أرسل الوقت HH:MM:", bot=context.bot)
                return
            await safe_edit(query, "⚠️ غير معروف", bot=context.bot)
        except Exception as e:
            logger.error(f"خطأ في الجدولة: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    @staticmethod
    async def _show_schedule_menu(update, context, query, ch_id, user_id):
        lang = await DB.get_user_language(user_id) or 'ar'
        kb = KeyboardFactory.build("channel_settings", chat_id=ch_id, lang=lang)
        await safe_edit(query, "📅 جدولة القناة", reply_markup=kb, bot=context.bot)

    # =================================================================
    # الإجراءات المتقدمة
    # =================================================================

    @staticmethod
    async def _handle_advanced_actions(update, context, query, user_id):
        data = query.data
        parts = data.split(":")
        if len(parts) < 2:
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return
        prefix = parts[0]
        action = prefix.replace("act_", "").replace("pen_", "").replace("ban_", "")
        try:
            chat_id = int(parts[1])
        except (ValueError, IndexError):
            await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
            return

        if chat_id == -1 and (prefix.startswith("act_") or prefix.startswith("pen_")):
            await safe_edit(query, "❌ معرف غير صالح", bot=context.bot)
            return
        if chat_id != -1:
            if not await is_authorized_in_group(context.bot, chat_id, user_id):
                await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
                return
        else:
            if not CONFIG.is_developer(user_id):
                await safe_edit(query, "❌ غير مصرح", bot=context.bot)
                return

        try:
            if prefix.startswith("ban_"):
                if action == "add":
                    state = UserState.WAIT_GROUP_BAN if chat_id != -1 else UserState.WAIT_GLOBAL_BAN
                    StateManager.set(user_id, state)
                    context.user_data['ban_chat'] = chat_id
                    await safe_edit(query, "📝 أرسل الكلمة:", bot=context.bot)
                    return
                if action == "list":
                    words = await DB.get_banned_words(chat_id)
                    if words:
                        text = "🚫 الكلمات\n\n" + "\n".join(f"• {w}" for w in words[:50])
                    else:
                        text = "📭 لا يوجد"
                    await safe_edit(query, text, bot=context.bot)
                    return
                if action == "rem":
                    state = UserState.WAIT_REM_GROUP_BAN if chat_id != -1 else UserState.WAIT_REM_GLOBAL_BAN
                    StateManager.set(user_id, state)
                    context.user_data['ban_chat'] = chat_id
                    await safe_edit(query, "🗑️ أرسل الكلمة:", bot=context.bot)
                    return
                await safe_edit(query, "⚠️ غير معروف", bot=context.bot)
                return

            if prefix.startswith("act_"):
                user_actions = {
                    "ban": (UserState.WAIT_BAN, "🚫 أرسل معرف المستخدم:"),
                    "mute": (UserState.WAIT_MUTE, "🔇 أرسل معرف المستخدم:"),
                    "warn": (UserState.WAIT_WARN, "⚠️ أرسل معرف المستخدم:"),
                    "kick": (UserState.WAIT_KICK, "👢 أرسل معرف المستخدم:"),
                    "restrict": (UserState.WAIT_RESTRICT, "🔒 أرسل معرف المستخدم:"),
                    "unban": (UserState.WAIT_UNBAN, "🔓 أرسل معرف المستخدم:"),
                }
                if action in user_actions:
                    state, msg = user_actions[action]
                    StateManager.set(user_id, state)
                    context.user_data['adv_chat'] = chat_id
                    await safe_edit(query, msg, bot=context.bot)
                    return

                if action == "log":
                    await CallbackHandlers._show_admin_logs(update, context, query, chat_id, lang='ar')
                    StateManager.clear(user_id)
                    return
                await safe_edit(query, "⚠️ غير معروف", bot=context.bot)
                return

            if prefix.startswith("pen_"):
                penalty_types = {'ban', 'mute', 'kick', 'restrict', 'none'}
                if action in penalty_types:
                    await DB.update_security_settings(chat_id, auto_penalty=action)
                    await CallbackHandlers._refresh_security_view(query, context, chat_id, 'ar')
                    return
                await safe_edit(query, "⚠️ غير معروف", bot=context.bot)
                return
            await safe_edit(query, "⚠️ غير معروف", bot=context.bot)
        except Exception as e:
            logger.error(f"خطأ في الإجراءات المتقدمة: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    # =================================================================
    # اللوحة
    # =================================================================

    @staticmethod
    async def _handle_panel(update, context, query, user_id, data):
        if not update.effective_chat:
            await safe_edit(query, "❌ لا يمكن تحديد المجموعة", bot=context.bot)
            return
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await safe_edit(query, "❌ لا صلاحية", bot=context.bot)
            return
        try:
            if data == "panel_lock":
                await context.bot.set_chat_permissions(chat_id, permissions=ChatPermissions(
                    can_send_messages=False, can_send_audios=False, can_send_documents=False,
                    can_send_photos=False, can_send_videos=False, can_send_video_notes=False,
                    can_send_voice_notes=False, can_send_polls=False, can_send_other_messages=False,
                    can_add_web_page_previews=False, can_change_info=False,
                    can_invite_users=False, can_pin_messages=False))
                await safe_edit(query, "🔒 تم قفل المجموعة", bot=context.bot)
                return
            if data == "panel_unlock":
                await context.bot.set_chat_permissions(chat_id, permissions=ChatPermissions(
                    can_send_messages=True, can_send_audios=True, can_send_documents=True,
                    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                    can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
                    can_add_web_page_previews=True, can_change_info=True,
                    can_invite_users=True, can_pin_messages=True))
                await safe_edit(query, "🔓 تم فتح المجموعة", bot=context.bot)
                return
            if data == "panel_close":
                StateManager.clear(user_id)
                _clear_context_keys(context)
                await safe_delete_message(query)
                return
            await safe_edit(query, "⚠️ غير معروف", bot=context.bot)
        except Exception as e:
            logger.error(f"خطأ في اللوحة: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    # =================================================================
    # المسابقات
    # =================================================================

    @staticmethod
    async def _handle_contests(update, context, query, user_id):
        data = query.data
        declare_sel = getattr(CB, 'DECLARE_WINNER_SEL', 'declare_winner_sel')
        contest_join = getattr(CB, 'CONTEST_JOIN', 'contest_join')
        try:
            if data.startswith(contest_join + ":"):
                cid = _coerce_int(data.split(":")[-1])
                if cid <= 0:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return
                contest = await DB.get_contest_by_id(cid)
                cd = _row_to_dict(contest) or {}
                if not cd or cd.get('status') != 'active':
                    await safe_edit(query, "❌ المسابقة غير متاحة", bot=context.bot)
                    StateManager.clear(user_id)
                    return
                already_joined = await DB.check_contest_joined(cid, user_id)
                if already_joined:
                    await safe_edit(query, "❌ شاركت في هذه المسابقة مسبقاً", bot=context.bot)
                    return
                StateManager.set(user_id, UserState.WAIT_CONTEST_ANSWER)
                context.user_data['contest_join'] = cid
                await safe_edit(query, "📝 أرسل إجابتك:", bot=context.bot)
                return

            if data == CB.CONTEST_WINNERS:
                winners = await DB.get_contest_winners(10)
                if winners:
                    lines = []
                    for w in winners:
                        wd = _row_to_dict(w) or {}
                        lines.append(f"• {_safe_str(wd.get('title'))} - {_safe_str(wd.get('winner_id'))}")
                    text = "🏆 الفائزون\n\n" + "\n".join(lines)
                else:
                    text = "📭 لا يوجد"
                await safe_edit(query, text, bot=context.bot)
                StateManager.clear(user_id)
                return

            if data.startswith(declare_sel + ":"):
                if not CONFIG.is_developer(user_id):
                    await safe_edit(query, "❌ غير مصرح", bot=context.bot)
                    return
                cid = _coerce_int(data.split(":")[-1])
                if cid <= 0:
                    await safe_edit(query, "❌ بيانات غير صالحة", bot=context.bot)
                    return
                winner = await DB.fetchone(
                    "SELECT user_id FROM contest_participants WHERE contest_id=? ORDER BY RANDOM() LIMIT 1",
                    (cid,))
                wd = _row_to_dict(winner) or {}
                if not wd:
                    await safe_edit(query, "❌ لا يوجد مشاركون", bot=context.bot)
                    return
                winner_id = wd.get('user_id')
                if await DB.declare_winner(cid, winner_id):
                    await safe_edit(query, f"✅ الفائز: {winner_id}", bot=context.bot)
                    try:
                        await context.bot.send_message(winner_id, "🎉 مبروك! فزت بالمسابقة!")
                    except Exception:
                        pass
                else:
                    await safe_edit(query, "❌ فشل", bot=context.bot)
                return
            await safe_edit(query, "⚠️ غير معروف", bot=context.bot)
        except Exception as e:
            logger.error(f"خطأ في المسابقات: {e}", exc_info=True)
            await safe_edit(query, "❌ حدث خطأ", bot=context.bot)

    # =================================================================
    # النسخ الاحتياطي — ✅ #15 #16 #19 #40
    # =================================================================

    @staticmethod
    async def _do_backup(context, user_id):
        try:
            PATHS.BACKUPS.mkdir(parents=True, exist_ok=True)
            timestamp = TimeUtils.mecca_now().strftime('%Y%m%d_%H%M%S_%f')
            backup_file = PATHS.BACKUPS / f"backup_{timestamp}.db"
            success = await DB.backup_database(backup_file)
            if not success:
                await safe_send(context.bot, user_id, "❌ فشل النسخ الاحتياطي")
                return
            try:
                await DB.set_setting('last_backup', TimeUtils.sql_iso())
            except Exception:
                pass

            # ✅ #16: فحص الحجم
            try:
                size = backup_file.stat().st_size
            except Exception:
                size = 0
            if size > MAX_TG_FILE_SIZE:
                size_mb = size / (1024 * 1024)
                await safe_send(context.bot, user_id,
                                f"⚠️ النسخة جاهزة ({size_mb:.1f}MB) لكنها تتجاوز حد تيليجرام.\n"
                                f"الملف في: {backup_file}")
                return

            # ✅ #19: لا نحذف النسخة الجديدة
            def _safe_mtime(p):
                try:
                    return p.stat().st_mtime
                except (OSError, FileNotFoundError):
                    return 0

            backups = sorted(PATHS.BACKUPS.glob("backup_*.db"),
                             key=_safe_mtime, reverse=True)
            others = [b for b in backups if b != backup_file]
            for old in others[MAX_BACKUPS - 1:]:
                try:
                    old.unlink(missing_ok=True)
                except OSError:
                    pass

            with open(backup_file, 'rb') as f:
                await context.bot.send_document(chat_id=user_id, document=f, filename=backup_file.name)
        except Exception as e:
            logger.error(f"❌ فشل النسخ: {e}", exc_info=True)
            try:
                await safe_send(context.bot, user_id, f"❌ فشل النسخ: {str(e)[:100]}")
            except Exception:
                pass


# =====================================================================
# تصدير
# =====================================================================

__all__ = ["CallbackHandlers"]