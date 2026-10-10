#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
callback_security.py - معالج أزرار الأمان (v9.7.19-ROUTING-FIX)
=====================================================================
🆕 v9.7.19-ROUTING-FIX:
    🟢 FIX-1: إضافة معالجة act_* / ban_* / pen_* داخل handle_parameterized
              لتمريرها عبر _check_sec_auth المخزَّن (بدل is_authorized_in_group المباشر).
    🟢 FIX-2: تفعيل زر act_log:<chat> (كان ميتاً لأن الزر لا يبدأ بـ sec_).
    🟢 FIX-3: توحيد سلوك أزرار الأدوات المتقدمة مع بقية أزرار الأمان.
    🟢 FIX-4: حماية شاملة بـ try/except مع رسائل خطأ واضحة للمستخدم.
=====================================================================
"""
import asyncio
import html as _html
import logging
import time
from typing import Dict, Tuple, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

from config import CONFIG
from database import DB, TimeUtils
from database import internal_cache

try:
    from utils import (
        safe_send, is_authorized_in_group,
        StateManager, UserState, KeyboardFactory, CB,
        SmartCache, SECURITY_TOGGLE_MAP, NEW_SECURITY_DEFAULTS,
        get_security_settings as bridge_get_security_settings,
        invalidate_security_settings_cache as bridge_invalidate_sec_cache,
    )
    _SECURITY_BRIDGE_AVAILABLE = True
except ImportError:
    from .utils import (
        safe_send, is_authorized_in_group,
        StateManager, UserState, KeyboardFactory, CB,
        SmartCache, SECURITY_TOGGLE_MAP, NEW_SECURITY_DEFAULTS,
        get_security_settings as bridge_get_security_settings,
        invalidate_security_settings_cache as bridge_invalidate_sec_cache,
    )
    _SECURITY_BRIDGE_AVAILABLE = True

try:
    from cache import settings_cache
except ImportError:
    class _DummySettingsCache:
        async def get_security(self, cid): return None
        async def set_security(self, cid, v): return
        async def invalidate_security(self, cid=None): return
        async def get_auto_reply_settings(self, cid): return None
        async def set_auto_reply_settings(self, cid, v): return
        async def invalidate_auto_reply(self, cid=None): return
    settings_cache = _DummySettingsCache()

try:
    from .handlers_callback_base import (
        SEC_AUTH_CACHE_TTL, SEC_AUTH_CACHE_MAX_SIZE, SEC_STATS_CACHE_TTL,
        _trans, _fmt, _row_to_dict, _coerce_int, _coerce_float, _safe_str,
    )
except ImportError:
    from handlers_callback_base import (
        SEC_AUTH_CACHE_TTL, SEC_AUTH_CACHE_MAX_SIZE, SEC_STATS_CACHE_TTL,
        _trans, _fmt, _row_to_dict, _coerce_int, _coerce_float, _safe_str,
    )

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# ثوابت الأمان
# ═══════════════════════════════════════════════════════════════════

_ANTIFLOOD_MESSAGES_OPTIONS = [3, 5, 7, 10, 15, 20, 30]
_ANTIFLOOD_SECONDS_OPTIONS = [3, 5, 10, 15, 30, 60, 120]
_ANTIFLOOD_MESSAGES_MAX = 100
_ANTIFLOOD_SECONDS_MAX = 3600

_SEC_ACTIONS_WITH_SPECIFIC_HANDLERS = frozenset({
    "warn",
    "banned_words",
})

_SEC_AUTH_NEG_BASE = 3.0
_SEC_AUTH_NEG_MAX = 60.0
_SEC_AUTH_PRUNE_EVERY = 500
_SEC_VIEW_TOKEN_KEY = '_sec_view_token'


# ═══════════════════════════════════════════════════════════════════
# كاشات المصادقة (module-level state)
# ═══════════════════════════════════════════════════════════════════

_sec_auth_cache: Dict[Tuple[int, int], Tuple[bool, float]] = {}
_sec_auth_neg_cache: Dict[Tuple[int, int], Tuple[float, int]] = {}
_sec_auth_locks: Dict[Tuple[int, int], asyncio.Lock] = {}
_security_stats_cache_local = SmartCache(ttl=SEC_STATS_CACHE_TTL, max_size=500)


# ═══════════════════════════════════════════════════════════════════
# الحاقنات (Dependency Injection)
# ═══════════════════════════════════════════════════════════════════

_metrics_inc_fn = None
_safe_edit_fn = None


def set_metrics_inc(fn):
    global _metrics_inc_fn
    _metrics_inc_fn = fn


def set_safe_edit(fn):
    global _safe_edit_fn
    _safe_edit_fn = fn


def _metrics_inc(key, delta=1):
    if _metrics_inc_fn is None:
        return
    try:
        _metrics_inc_fn(key, delta)
    except Exception:
        pass


async def _safe_edit(query, text, reply_markup=None, parse_mode="HTML",
                     bot=None, clear_markup=False):
    if _safe_edit_fn is not None:
        try:
            return await _safe_edit_fn(
                query, text, reply_markup, parse_mode, bot, clear_markup
            )
        except TypeError:
            return await _safe_edit_fn(query, text, reply_markup,
                                        parse_mode, bot)
    import re
    if not query or not query.message:
        return False
    try:
        await query.edit_message_text(
            text or "...", reply_markup=reply_markup, parse_mode=parse_mode
        )
        return True
    except BadRequest as e:
        em = str(e).lower()
        if "message is not modified" in em:
            return True
        if "can't parse entities" in em or "parse" in em:
            try:
                clean = re.sub(r'<[^>]+>', '', text or "")
                await query.edit_message_text(
                    clean, reply_markup=reply_markup, parse_mode=None
                )
                return True
            except Exception:
                return False
        return False
    except Exception:
        return False


async def _safe_answer(query, text=None, show_alert=False):
    if not query:
        return False
    try:
        await query.answer(text or "", show_alert=show_alert)
        return True
    except Exception:
        return False


async def _show_error(query, context, lang):
    """v9.7.19: عرض خطأ موحّد للمستخدم."""
    try:
        await _safe_edit(query,
            await _trans('error_occurred', lang, "❌ حدث خطأ"),
            bot=context.bot)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# فحص المصادقة وتخزينها المؤقت
# ═══════════════════════════════════════════════════════════════════

def _prune_sec_auth_cache(now):
    removed = 0
    for k in [k for k, (_, ts) in _sec_auth_cache.items()
              if now - ts >= SEC_AUTH_CACHE_TTL]:
        _sec_auth_cache.pop(k, None)
        removed += 1
    if len(_sec_auth_cache) > SEC_AUTH_CACHE_MAX_SIZE:
        target = max(1, SEC_AUTH_CACHE_MAX_SIZE // 4)
        for k, _ in sorted(_sec_auth_cache.items(),
                           key=lambda kv: kv[1][1])[:target]:
            _sec_auth_cache.pop(k, None)
            removed += 1
    expired_neg = []
    for k, val in _sec_auth_neg_cache.items():
        try:
            until = val[0] if isinstance(val, tuple) else val
        except Exception:
            expired_neg.append(k)
            continue
        if until <= now:
            expired_neg.append(k)
    for k in expired_neg:
        _sec_auth_neg_cache.pop(k, None)
    for k in list(_sec_auth_locks.keys()):
        lock = _sec_auth_locks.get(k)
        if lock is None:
            continue
        if (not lock.locked() and k not in _sec_auth_cache
                and k not in _sec_auth_neg_cache):
            _sec_auth_locks.pop(k, None)
    return removed


async def _check_sec_auth(context, user_id, chat_id):
    if chat_id is None:
        return False
    key = (user_id, chat_id)
    now = time.monotonic()
    cached = _sec_auth_cache.get(key)
    if cached and now - cached[1] < SEC_AUTH_CACHE_TTL:
        _metrics_inc('auth_cache_hits')
        return cached[0]
    neg_val = _sec_auth_neg_cache.get(key)
    if neg_val is not None:
        try:
            until = neg_val[0] if isinstance(neg_val, tuple) else neg_val
            if until > now:
                _metrics_inc('auth_neg_cache_hits')
                return False
        except Exception:
            pass
    _metrics_inc('auth_cache_misses')

    lock = _sec_auth_locks.get(key)
    if lock is None:
        new_lock = asyncio.Lock()
        lock = _sec_auth_locks.setdefault(key, new_lock)

    async with lock:
        now = time.monotonic()
        cached = _sec_auth_cache.get(key)
        if cached and now - cached[1] < SEC_AUTH_CACHE_TTL:
            return cached[0]
        neg_val = _sec_auth_neg_cache.get(key)
        if neg_val is not None:
            try:
                until = neg_val[0] if isinstance(neg_val, tuple) else neg_val
                if until > now:
                    return False
            except Exception:
                pass
        if len(_sec_auth_cache) >= SEC_AUTH_CACHE_MAX_SIZE:
            _prune_sec_auth_cache(now)
        try:
            result = await is_authorized_in_group(
                context.bot, chat_id, user_id
            )
        except Exception:
            prev = _sec_auth_neg_cache.get(key)
            fails = 0
            if prev is not None and isinstance(prev, tuple):
                try:
                    fails = int(prev[1])
                except Exception:
                    fails = 0
            nf = min(fails + 1, 6)
            ttl = min(_SEC_AUTH_NEG_BASE * (2 ** (nf - 1)),
                      _SEC_AUTH_NEG_MAX)
            _sec_auth_neg_cache[key] = (now + ttl, nf)
            _metrics_inc('auth_api_failures')
            return False
        _sec_auth_cache[key] = (result, now)
        _sec_auth_neg_cache.pop(key, None)
        return result


def _invalidate_sec_auth_cache(chat_id=None):
    if chat_id is None:
        _sec_auth_cache.clear()
        _sec_auth_neg_cache.clear()
        for k in list(_sec_auth_locks.keys()):
            lock = _sec_auth_locks.get(k)
            if lock is not None and not lock.locked():
                _sec_auth_locks.pop(k, None)
    else:
        for k in list(_sec_auth_cache.keys()):
            if k[1] == chat_id:
                del _sec_auth_cache[k]
        for k in list(_sec_auth_neg_cache.keys()):
            if k[1] == chat_id:
                del _sec_auth_neg_cache[k]
        for k in list(_sec_auth_locks.keys()):
            if k[1] == chat_id:
                lock = _sec_auth_locks.get(k)
                if lock is not None and not lock.locked():
                    _sec_auth_locks.pop(k, None)


def _set_sec_chat(context, chat_id):
    try:
        context.user_data['sec_chat'] = chat_id
        context.user_data['security_chat_id'] = chat_id
    except Exception:
        pass


async def _resolve_sec_chat_id(context, data):
    for part in data.split(":")[1:]:
        p = part.strip()
        if p.startswith('-') and p[1:].isdigit():
            return int(p)
    stored = (context.user_data.get('security_chat_id')
              or context.user_data.get('sec_chat'))
    if stored:
        try:
            return int(stored)
        except (TypeError, ValueError):
            return None
    return None


# ═══════════════════════════════════════════════════════════════════
# SecurityCallbacks — الفئة الرئيسية
# ═══════════════════════════════════════════════════════════════════

class SecurityCallbacks:

    @staticmethod
    async def _invalidate_security_settings_cache(chat_id):
        try:
            await settings_cache.invalidate_security(chat_id)
        except Exception:
            pass
        try:
            await _security_stats_cache_local.delete(f"sec_stats_{chat_id}")
        except Exception:
            pass
        if _SECURITY_BRIDGE_AVAILABLE:
            try:
                bridge_invalidate_sec_cache(chat_id)
            except Exception:
                pass

    @staticmethod
    async def _get_security_settings_cached(chat_id):
        try:
            cached = await settings_cache.get_security(chat_id)
        except Exception:
            cached = None
        if cached is not None:
            if isinstance(cached, dict):
                return cached
            as_dict = _row_to_dict(cached)
            if as_dict is not None:
                return as_dict
            try:
                await settings_cache.invalidate_security(chat_id)
            except Exception:
                pass

        settings: Dict = {}
        try:
            raw = await DB.get_security_settings(chat_id) or {}
            if not isinstance(raw, dict):
                raw = _row_to_dict(raw) or {}
            settings = raw
        except Exception as e:
            logger.debug(f"DB.get_security_settings({chat_id}): {e}")
            settings = {}

        try:
            await settings_cache.set_security(chat_id, settings)
        except Exception:
            pass
        return settings

    @staticmethod
    async def _load_stats_and_edit(query, context, chat_id, lang, settings,
                                    expected_token=None):
        try:
            if expected_token is not None:
                if context.user_data.get(_SEC_VIEW_TOKEN_KEY) != expected_token:
                    return
            cache_key = f"sec_stats_{chat_id}"
            cached_stats = await _security_stats_cache_local.get(cache_key)
            if cached_stats is not None:
                stats = cached_stats
            else:
                stats = await KeyboardFactory._get_security_stats(chat_id) or {}
                await _security_stats_cache_local.set(
                    cache_key, stats, ttl=SEC_STATS_CACHE_TTL
                )
            if expected_token is not None:
                if context.user_data.get(_SEC_VIEW_TOKEN_KEY) != expected_token:
                    return
            try:
                text = KeyboardFactory._format_security_text(
                    settings, stats, lang=lang
                )
            except TypeError:
                text = KeyboardFactory._format_security_text(settings, stats)
            kb = KeyboardFactory.build("security", chat_id=chat_id, lang=lang)
            await _safe_edit(query, text, reply_markup=kb,
                             parse_mode='HTML', bot=context.bot)
        except Exception as e:
            logger.debug(f"_load_stats_and_edit({chat_id}): {e}")

    @staticmethod
    async def _render_security_two_phase(query, context, chat_id, lang,
                                          force_refresh_settings=False):
        try:
            if force_refresh_settings:
                await SecurityCallbacks._invalidate_security_settings_cache(
                    chat_id
                )
            settings = await SecurityCallbacks._get_security_settings_cached(
                chat_id
            )
            try:
                text_no_stats = KeyboardFactory._format_security_text(
                    settings, {}, lang=lang
                )
            except TypeError:
                text_no_stats = KeyboardFactory._format_security_text(
                    settings, {}
                )
            kb = KeyboardFactory.build("security", chat_id=chat_id, lang=lang)
            await _safe_edit(query, text_no_stats, reply_markup=kb,
                             parse_mode='HTML', bot=context.bot)
            token = time.monotonic()
            try:
                context.user_data[_SEC_VIEW_TOKEN_KEY] = token
            except Exception:
                pass
            task = asyncio.create_task(
                SecurityCallbacks._load_stats_and_edit(
                    query, context, chat_id, lang, settings,
                    expected_token=token
                )
            )
            try:
                from handlers_callback import ACTIVE_TASKS
                ACTIVE_TASKS.add(task)
                task.add_done_callback(ACTIVE_TASKS.discard)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"_render_security_two_phase: {e}", exc_info=True)

    @staticmethod
    async def _refresh_security_view(query, context, chat_id, lang):
        try:
            await SecurityCallbacks._invalidate_security_settings_cache(
                chat_id
            )
            await SecurityCallbacks._render_security_two_phase(
                query, context, chat_id, lang, force_refresh_settings=False
            )
        except Exception as e:
            logger.error(f"_refresh_security_view: {e}", exc_info=True)

    # ─── شاشات العرض ──────────────────────────────────────────────
    @staticmethod
    async def _show_antiflood_messages_buttons(update, context, query,
                                                chat_id, lang):
        try:
            settings = await SecurityCallbacks._get_security_settings_cached(
                chat_id
            )
            current = _coerce_int(settings.get('antiflood_messages'), 5)
            title = await _trans('antiflood_messages_title', lang,
                "🔢 <b>عدد الرسائل المسموحة</b>")
            current_label = _fmt(await _trans(
                'antiflood_messages_current', lang,
                "📊 <b>القيمة الحالية:</b> <code>{count}</code> رسالة"),
                count=current)
            choose = await _trans('antiflood_messages_choose', lang,
                "اختر الحد الأقصى للرسائل خلال النافذة الزمنية:")
            text = (f"{title}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{current_label}\n\n{choose}")
            kb = []
            row = []
            for n in _ANTIFLOOD_MESSAGES_OPTIONS:
                icon = "✅" if n == current else "▫️"
                row.append(InlineKeyboardButton(
                    f"{icon} {n}",
                    callback_data=f"set_antiflood_messages:{chat_id}:{n}"
                ))
                if len(row) == 3:
                    kb.append(row); row = []
            if row:
                kb.append(row)
            kb.append([InlineKeyboardButton(
                KeyboardFactory.get_text("back", lang),
                callback_data=f"sec_antiflood_settings:{chat_id}"
            )])
            await _safe_edit(query, text,
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='HTML', bot=context.bot)
        except Exception as e:
            logger.error(f"_show_antiflood_messages_buttons: {e}",
                          exc_info=True)
            await _show_error(query, context, lang)

    @staticmethod
    async def _show_antiflood_seconds_buttons(update, context, query,
                                               chat_id, lang):
        try:
            settings = await SecurityCallbacks._get_security_settings_cached(
                chat_id
            )
            current = _coerce_int(settings.get('antiflood_seconds'), 10)
            title = await _trans('antiflood_seconds_title', lang,
                "⏱️ <b>النافذة الزمنية (ثواني)</b>")
            current_label = _fmt(await _trans(
                'antiflood_seconds_current', lang,
                "⏱️ <b>القيمة الحالية:</b> <code>{count}</code> ثانية"),
                count=current)
            choose = await _trans('antiflood_seconds_choose', lang,
                "اختر النافذة الزمنية لعدّ الرسائل:")
            text = (f"{title}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{current_label}\n\n{choose}")
            kb = []
            row = []
            for n in _ANTIFLOOD_SECONDS_OPTIONS:
                icon = "✅" if n == current else "▫️"
                if n < 60:
                    label = f"{icon} {n}s"
                elif n % 60 == 0:
                    label = f"{icon} {n // 60}m"
                else:
                    label = f"{icon} {n}s"
                row.append(InlineKeyboardButton(
                    label,
                    callback_data=f"set_antiflood_seconds:{chat_id}:{n}"
                ))
                if len(row) == 3:
                    kb.append(row); row = []
            if row:
                kb.append(row)
            kb.append([InlineKeyboardButton(
                KeyboardFactory.get_text("back", lang),
                callback_data=f"sec_antiflood_settings:{chat_id}"
            )])
            await _safe_edit(query, text,
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='HTML', bot=context.bot)
        except Exception as e:
            logger.error(f"_show_antiflood_seconds_buttons: {e}",
                          exc_info=True)
            await _show_error(query, context, lang)

    @staticmethod
    async def _show_warn_count_buttons(update, context, query, chat_id, lang):
        settings = await SecurityCallbacks._get_security_settings_cached(
            chat_id
        )
        current = _coerce_int(settings.get('max_warnings'), 3)
        title = await _trans('warn_count_title', lang, "🔢")
        current_label = _fmt(await _trans('warn_count_current', lang,
            "{count}"), count=current)
        choose = await _trans('warn_count_choose', lang, "")
        text = f"{title}\n\n{current_label}\n\n{choose}"
        counts = [1, 2, 3, 4, 5, 10]
        kb = []; row = []
        for n in counts:
            icon = "✅" if n == current else ""
            row.append(InlineKeyboardButton(f"{icon} {n}",
                callback_data=f"set_warn_count:{chat_id}:{n}"))
            if len(row) == 3:
                kb.append(row); row = []
        if row:
            kb.append(row)
        kb.append([InlineKeyboardButton(
            KeyboardFactory.get_text("back", lang),
            callback_data=f"sec_warn:{chat_id}")])
        await _safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='HTML', bot=context.bot)

    @staticmethod
    async def _show_warn_penalty_types(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(await _trans('ban_btn', lang, "🚫"),
                callback_data=f"set_warn_penalty:ban:{chat_id}"),
             InlineKeyboardButton(await _trans('mute_btn', lang, "🔇"),
                callback_data=f"set_warn_penalty:mute:{chat_id}")],
            [InlineKeyboardButton(await _trans('kick_btn', lang, "👢"),
                callback_data=f"set_warn_penalty:kick:{chat_id}"),
             InlineKeyboardButton(await _trans('restrict_btn', lang, "🔒"),
                callback_data=f"set_warn_penalty:restrict:{chat_id}")],
            [InlineKeyboardButton(KeyboardFactory.get_text("back", lang),
                callback_data=f"sec_warn:{chat_id}")]])
        await _safe_edit(query,
            await _trans('choose_warn_penalty', lang, "⚖️"),
            reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_banned_words_menu(update, context, query, chat_id, lang):
        settings = await SecurityCallbacks._get_security_settings_cached(
            chat_id
        )
        is_enabled = _coerce_int(settings.get('delete_banned_words'), 0)
        if is_enabled:
            toggle_text = await _trans('banned_words_btn_on', lang,
                "✅ حذف الكلمات المحظورة: مفعّل (اضغط للتعطيل)")
        else:
            toggle_text = await _trans('banned_words_btn_off', lang,
                "❌ حذف الكلمات المحظورة: معطّل (اضغط للتفعيل)")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(await _trans('add_word', lang, "➕"),
                callback_data=f"ban_add:{chat_id}"),
             InlineKeyboardButton(await _trans('words_list', lang, "📋"),
                callback_data=f"ban_list:{chat_id}")],
            [InlineKeyboardButton(await _trans('delete_word', lang, "🗑️"),
                callback_data=f"ban_rem:{chat_id}")],
            [InlineKeyboardButton(toggle_text,
                callback_data=f"sec_toggle_banned_words:{chat_id}")],
            [InlineKeyboardButton(KeyboardFactory.get_text("back", lang),
                callback_data=f"{CB.GRP_SET}:{chat_id}")]])
        await _safe_edit(query,
            await _trans('manage_banned_words', lang, "🚫"),
            reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_penalty_type_selection(update, context, query, chat_id,
                                            lang, setting_key):
        penalty_types = [
            (await _trans('mute_btn', lang, "🔇"), "mute"),
            (await _trans('ban_btn', lang, "🚫"), "ban"),
            (await _trans('kick_btn', lang, "👢"), "kick"),
            (await _trans('restrict_btn', lang, "🔒"), "restrict"),
            (await _trans('no_penalty_btn', lang, "🚫"), "none")]
        kb = []
        for label, ptype in penalty_types:
            callback = f"sec_set_{setting_key}:{chat_id}:{ptype}"
            kb.append([InlineKeyboardButton(label, callback_data=callback)])
        _back_map = {
            'antiflood_penalty': f"sec_antiflood_settings:{chat_id}",
            'night_action': f"sec_night_settings:{chat_id}",
            'violation_penalty': f"sec_violation_settings:{chat_id}"}
        back_cb = _back_map.get(setting_key, f"{CB.GRP_SET}:{chat_id}")
        kb.append([InlineKeyboardButton(
            KeyboardFactory.get_text("back", lang), callback_data=back_cb)])
        text = await _trans('choose_penalty_type', lang, "🚫")
        await _safe_edit(query, text, reply_markup=InlineKeyboardMarkup(kb),
            bot=context.bot)

    @staticmethod
    async def _show_all_penalty_durations_menu(query, context, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(await _trans('mute_duration_btn', lang,
                "⏱️"), callback_data=f"sec_set_mute_duration:{chat_id}"),
             InlineKeyboardButton(await _trans('ban_duration_btn', lang,
                "⏱️"), callback_data=f"sec_set_ban_duration:{chat_id}")],
            [InlineKeyboardButton(await _trans('restrict_duration_btn', lang,
                "⏱️"), callback_data=f"sec_set_restrict_duration:{chat_id}"),
             InlineKeyboardButton(await _trans('warn_duration_btn', lang,
                "⏱️"), callback_data=f"sec_warn_penalty_duration:{chat_id}")],
            [InlineKeyboardButton(await _trans('flood_duration_btn', lang,
                "⏱️"), callback_data=f"sec_antiflood_duration:{chat_id}"),
             InlineKeyboardButton(await _trans('night_duration_btn', lang,
                "⏱️"), callback_data=f"sec_night_duration:{chat_id}")],
            [InlineKeyboardButton(await _trans('delete_penalty_duration_btn',
                lang, "⏱️"),
                callback_data=f"sec_set_del_penalty_duration:{chat_id}")],
            [InlineKeyboardButton(KeyboardFactory.get_text("back", lang),
                callback_data=f"{CB.GRP_SET}:{chat_id}")]])
        await _safe_edit(query,
            await _trans('penalty_durations_title', lang, "⏱️"),
            reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_penalty_durations(update, context, query, chat_id, lang,
                                       penalty_type='mute'):
        if penalty_type == 'kick':
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(
                KeyboardFactory.get_text("back", lang),
                callback_data=f"{CB.GRP_SET}:{chat_id}")]])
            await _safe_edit(query,
                await _trans('kick_no_duration', lang, "✅"),
                reply_markup=kb, bot=context.bot)
            return
        durations = [
            (await _trans('duration_permanent', lang, "∞"), 0),
            (await _trans('duration_half_hour', lang, "30m"), 1800),
            (await _trans('duration_hour', lang, "1h"), 3600),
            (await _trans('duration_day', lang, "1d"), 86400),
            (await _trans('duration_week', lang, "1w"), 604800),
            (await _trans('duration_ten_days', lang, "10d"), 864000),
            (await _trans('duration_month', lang, "1mo"), 2592000)]
        kb = []
        for i in range(0, len(durations), 2):
            row = []
            name, secs = durations[i]
            row.append(InlineKeyboardButton(name,
                callback_data=f"set_duration:{penalty_type}:{chat_id}:{secs}"))
            if i + 1 < len(durations):
                name2, secs2 = durations[i + 1]
                row.append(InlineKeyboardButton(name2,
                    callback_data=f"set_duration:{penalty_type}:{chat_id}:{secs2}"))
            kb.append(row)
        _back_map = {
            'warn_penalty': f"sec_warn:{chat_id}",
            'delete_penalty': f"sec_del_pen:{chat_id}",
            'antiflood': f"sec_antiflood_settings:{chat_id}",
            'night': f"sec_night_settings:{chat_id}",
            'violation': f"sec_violation_settings:{chat_id}"}
        back_cb = _back_map.get(penalty_type, f"{CB.GRP_SET}:{chat_id}")
        kb.append([InlineKeyboardButton(
            KeyboardFactory.get_text("back", lang), callback_data=back_cb)])
        type_key = f"duration_type_{penalty_type}"
        type_name = await _trans(type_key, lang, penalty_type)
        msg = _fmt(await _trans('choose_duration_for', lang,
            "⏱️ Choose {type_name} duration:"), type_name=type_name)
        await _safe_edit(query, msg, reply_markup=InlineKeyboardMarkup(kb),
            bot=context.bot)

    @staticmethod
    async def _show_violation_penalties(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(await _trans('violation_strikes_btn', lang,
                "🔢"), callback_data=f"sec_set_violation_strikes:{chat_id}"),
             InlineKeyboardButton(await _trans('violation_duration_btn', lang,
                "⏱️"), callback_data=f"sec_set_violation_duration:{chat_id}")],
            [InlineKeyboardButton(await _trans('violation_penalty_btn', lang,
                "⚖️"), callback_data=f"sec_violation_penalty:{chat_id}")],
            [InlineKeyboardButton(KeyboardFactory.get_text("back", lang),
                callback_data=f"{CB.GRP_SET}:{chat_id}")]])
        await _safe_edit(query,
            await _trans('violation_settings_title', lang, "🚨"),
            reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_antiflood_settings(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(await _trans('messages_count_btn', lang,
                "🔢"), callback_data=f"sec_set_antiflood_messages:{chat_id}"),
             InlineKeyboardButton(await _trans('seconds_btn', lang, "⏱️"),
                callback_data=f"sec_set_antiflood_seconds:{chat_id}")],
            [InlineKeyboardButton(await _trans('penalty_type_btn', lang,
                "Penalty type"),
                callback_data=f"sec_antiflood_penalty:{chat_id}"),
             InlineKeyboardButton(await _trans('penalty_duration_btn', lang,
                "⏱️"), callback_data=f"sec_antiflood_duration:{chat_id}")],
            [InlineKeyboardButton(KeyboardFactory.get_text("back", lang),
                callback_data=f"{CB.GRP_SET}:{chat_id}")]])
        await _safe_edit(query,
            await _trans('antiflood_settings_title', lang, "🌊"),
            reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_night_settings(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(await _trans('start_time_btn', lang, "🌙"),
                callback_data=f"sec_set_night_start:{chat_id}"),
             InlineKeyboardButton(await _trans('end_time_btn', lang, "🌙"),
                callback_data=f"sec_set_night_end:{chat_id}")],
            [InlineKeyboardButton(await _trans('action_type_btn', lang, "🎬"),
                callback_data=f"sec_night_action:{chat_id}"),
             InlineKeyboardButton(await _trans('action_duration_btn', lang,
                "⏱️"), callback_data=f"sec_night_duration:{chat_id}")],
            [InlineKeyboardButton(KeyboardFactory.get_text("back", lang),
                callback_data=f"{CB.GRP_SET}:{chat_id}")]])
        await _safe_edit(query,
            await _trans('night_mode_settings', lang, "🌙"),
            reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_advanced_actions(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(await _trans('deactivate_all_btn', lang,
                "🔴"), callback_data=f"sec_deactivate_all:{chat_id}"),
             InlineKeyboardButton(await _trans('activate_all_btn_short', lang,
                "🟢"), callback_data=f"sec_activate_all:{chat_id}")],
            [InlineKeyboardButton(await _trans('act_ban', lang, "🚫"),
                callback_data=f"act_ban:{chat_id}"),
             InlineKeyboardButton(await _trans('act_mute', lang, "🔇"),
                callback_data=f"act_mute:{chat_id}")],
            [InlineKeyboardButton(await _trans('act_kick', lang, "👢"),
                callback_data=f"act_kick:{chat_id}"),
             InlineKeyboardButton(await _trans('act_restrict', lang, "🔒"),
                callback_data=f"act_restrict:{chat_id}")],
            [InlineKeyboardButton(await _trans('act_unban', lang, "🔓"),
                callback_data=f"act_unban:{chat_id}"),
             InlineKeyboardButton(await _trans('act_warn', lang, "⚠️"),
                callback_data=f"act_warn:{chat_id}")],
            [InlineKeyboardButton(await _trans('act_pin', lang, "📌"),
                callback_data=f"act_pin:{chat_id}")],
            [InlineKeyboardButton(await _trans('act_log', lang, "📜"),
                callback_data=f"sec_act_log:{chat_id}")],  # ✅ FIX-2: sec_ prefix
            [InlineKeyboardButton(KeyboardFactory.get_text("back", lang),
                callback_data=f"{CB.GRP_SET}:{chat_id}")]])
        await _safe_edit(query,
            await _trans('advanced_actions_title', lang, "🛠️"),
            reply_markup=kb, bot=context.bot)

    @staticmethod
    async def _show_admin_logs(update, context, query, chat_id, lang):
        try:
            logs = await DB.get_admin_logs(chat_id, 10)
            if logs:
                lines = []
                for l in logs:
                    ld = _row_to_dict(l) or {}
                    lines.append(f"• {_safe_str(ld.get('admin_id'))} → "
                                 f"{_safe_str(ld.get('action'))}")
                text = (await _trans('admin_logs_title', lang, "📋") + "\n\n"
                        + "\n".join(lines))
            else:
                text = await _trans('no_data', lang, "📭")
            await _safe_edit(query, text, reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(KeyboardFactory.get_text("back", lang),
                    callback_data=f"{CB.GRP_SET}:{chat_id}")]]),
                bot=context.bot)
        except Exception as e:
            logger.error(f"_show_admin_logs: {e}", exc_info=True)
            await _show_error(query, context, lang)

    @staticmethod
    async def _show_penalty_types(update, context, query, chat_id, lang):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(await _trans('ban_btn', lang, "🚫"),
                callback_data=f"sec_penalty_ban:{chat_id}"),
             InlineKeyboardButton(await _trans('mute_btn', lang, "🔇"),
                callback_data=f"sec_penalty_mute:{chat_id}")],
            [InlineKeyboardButton(await _trans('kick_btn', lang, "👢"),
                callback_data=f"sec_penalty_kick:{chat_id}"),
             InlineKeyboardButton(await _trans('restrict_btn', lang, "🔒"),
                callback_data=f"sec_penalty_restrict:{chat_id}")],
            [InlineKeyboardButton(await _trans('no_penalty_btn', lang, "🚫"),
                callback_data=f"sec_penalty_none:{chat_id}")],
            [InlineKeyboardButton(KeyboardFactory.get_text("back", lang),
                callback_data=f"{CB.GRP_SET}:{chat_id}")]])
        await _safe_edit(query,
            await _trans('choose_penalty_type', lang, "🚫"),
            reply_markup=kb, bot=context.bot)

    # ─── قناة السجل ───────────────────────────────────────────────
    @staticmethod
    async def _show_log_channel_menu(query, context, chat_id, user_id, lang):
        from handlers_callback import (
            _get_log_channel_menu_data, _log_channel_cache_key,
        )
        data = await _get_log_channel_menu_data(chat_id)
        current = data.get('current')
        effective = data.get('effective')
        share_count = data.get('share_count', 0)
        share_names = data.get('share_names', [])
        if current:
            if share_count == 0:
                status_block = (f"✅ <b>Private</b>\n🆔 <code>{current}</code>")
            else:
                others_text = "، ".join(
                    _html.escape(str(n)) for n in share_names
                )
                if share_count > 3:
                    others_text += f" +{share_count - 3}"
                status_block = (f"🤝 <b>Shared</b>\n🆔 <code>{current}</code>\n"
                                f"👥 {share_count + 1}\n📋 {others_text}")
        elif effective:
            status_block = f"🌐 <b>Global</b>\n🆔 <code>{effective}</code>"
        else:
            status_block = "❌"
        help_text = KeyboardFactory.get_text("log_channel_help", lang) or ""
        title = await _trans('log_channel_btn', lang, "📢 Log channel")
        text = (f"{title}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{status_block}\n\n<i>{_html.escape(help_text)}</i>\n\n"
                f"🆔 <code>{chat_id}</code>")
        if current:
            set_text = (KeyboardFactory.get_text("log_channel_change", lang)
                        or "🔄 Change channel")
        else:
            set_text = (KeyboardFactory.get_text("log_channel_set", lang)
                        or "🔗 Set log")
        test_text = KeyboardFactory.get_text("log_channel_test", lang) or "🧪 Test"
        remove_text = (KeyboardFactory.get_text("log_channel_remove", lang)
                       or "🗑️ Remove log")
        back_text = KeyboardFactory.get_text("back", lang) or "🔙 Back"
        rows = [[InlineKeyboardButton(set_text,
            callback_data=f"log_channel_set:{chat_id}")]]
        if current:
            rows.append([
                InlineKeyboardButton(test_text,
                    callback_data=f"log_channel_test:{chat_id}"),
                InlineKeyboardButton(remove_text,
                    callback_data=f"log_channel_remove:{chat_id}"),
            ])
        rows.append([InlineKeyboardButton(back_text,
            callback_data=f"{CB.GRP_SET}:{chat_id}")])
        await _safe_edit(query, text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode='HTML', bot=context.bot)

    @staticmethod
    async def _handle_log_channel(update, context, query, user_id, lang):
        from handlers_callback import _invalidate_log_channel_menu_cache
        data = query.data or ""
        parts = data.split(":")
        chat_id = None
        if len(parts) >= 2 and parts[1].lstrip('-').isdigit():
            chat_id = int(parts[1])
        if chat_id is None:
            stored = (context.user_data.get('security_chat_id')
                      or context.user_data.get('sec_chat'))
            if stored:
                try:
                    chat_id = int(stored)
                except (TypeError, ValueError):
                    chat_id = None
        if chat_id is None:
            await _safe_edit(query,
                await _trans('group_not_specified', lang, "❌"),
                bot=context.bot)
            return
        if not await _check_sec_auth(context, user_id, chat_id):
            await _safe_edit(query,
                await _trans('no_permission', lang, "❌"), bot=context.bot)
            return
        if parts[0] == "log_channel_btn":
            action = "menu"
        elif parts[0].startswith("log_channel_"):
            action = parts[0][len("log_channel_"):]
        else:
            action = parts[0]
        try:
            if action in ("menu", "btn", "show"):
                await SecurityCallbacks._show_log_channel_menu(
                    query, context, chat_id, user_id, lang)
                return
            if action == "set":
                StateManager.set(user_id, UserState.WAIT_LOG_CH)
                context.user_data['log_group_id'] = chat_id
                await _safe_edit(query,
                    await _trans('log_channel_set', lang, "🔗 Set log"),
                    parse_mode='HTML', bot=context.bot)
                return
            if action == "remove":
                current = await DB.get_group_log_channel(chat_id)
                share_info = ""
                if current:
                    try:
                        others = await DB.get_groups_sharing_log_channel(
                            current, exclude_group_id=chat_id)
                        if others:
                            share_info = f"\n\n⚠️ {len(others)}"
                    except Exception:
                        pass
                ok = await DB.remove_group_log_channel(chat_id)
                await _invalidate_log_channel_menu_cache(chat_id)
                if not ok:
                    await _safe_edit(query,
                        await _trans('delete_failed', lang, "❌"),
                        bot=context.bot)
                    return
                back_text = (KeyboardFactory.get_text("back", lang)
                             or "🔙 Back")
                msg = await _trans('log_channel_removed', lang,
                                    "🗑️ Log channel removed")
                await _safe_edit(query,
                    f"{msg}\n\n🆔 <code>{chat_id}</code>{share_info}",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(back_text,
                            callback_data=f"{CB.GRP_SET}:{chat_id}")]]),
                    parse_mode='HTML', bot=context.bot)
                return
            if action == "test":
                current = await DB.get_group_log_channel(chat_id)
                if not current:
                    current = await DB.get_log_channel()
                if not current:
                    await _safe_edit(query,
                        await _trans('log_channel_none', lang,
                                     "❌ No log channel"), bot=context.bot)
                    return
                try:
                    test_msg = await _trans('log_channel_test', lang,
                        "🧪 Test — Log channel works!")
                    await safe_send(context.bot, current,
                        f"{test_msg}\n🆔 <code>{chat_id}</code>\n"
                        f"🕐 {TimeUtils.mecca_iso()}",
                        parse_mode='HTML')
                    await _invalidate_log_channel_menu_cache(chat_id)
                    await _safe_edit(query, f"✅ <code>{current}</code>",
                        parse_mode='HTML', bot=context.bot)
                except Exception as e:
                    await _safe_edit(query, f"❌ {str(e)[:100]}",
                        bot=context.bot)
                return
            await _safe_edit(query,
                await _trans('unknown_action', lang, "⚠️"), bot=context.bot)
        except Exception as e:
            logger.error(f"_handle_log_channel: {e}", exc_info=True)
            await _show_error(query, context, lang)

    # ═══════════════════════════════════════════════════════════════
    # الموجّه الرئيسي لأزرار sec_*
    # ═══════════════════════════════════════════════════════════════
    @staticmethod
    async def handle_security(update, context, query, user_id, lang=None):
        from handlers_callback import _render_auto_reply_menu
        if not lang:
            lang = await DB.get_user_language(user_id) or 'ar'
        data = query.data
        parts = data.split(":")
        chat_id = None
        if len(parts) >= 2 and parts[1].lstrip('-').isdigit():
            chat_id = int(parts[1])
        else:
            stored = (context.user_data.get('security_chat_id')
                      or context.user_data.get('sec_chat'))
            if stored:
                try:
                    chat_id = int(stored)
                except (TypeError, ValueError):
                    chat_id = None
        if chat_id is None:
            await _safe_edit(query,
                await _trans('group_not_specified', lang, "❌"),
                bot=context.bot)
            return
        prefix0 = parts[0]
        action = (prefix0[4:] if prefix0.startswith("sec_") else prefix0)
        if not await _check_sec_auth(context, user_id, chat_id):
            await _safe_edit(query,
                await _trans('no_permission', lang, "❌"), bot=context.bot)
            return
        try:
            if action == "auto_reply_menu":
                await _render_auto_reply_menu(query, context, chat_id, lang)
                return
            if action == "maxlen":
                StateManager.set(user_id, UserState.WAIT_MAX_LEN)
                _set_sec_chat(context, chat_id)
                await _safe_edit(query,
                    await _trans('send_max_length', lang, "📏"),
                    bot=context.bot)
                return
            if action == "act_log":
                await SecurityCallbacks._show_admin_logs(
                    update, context, query, chat_id, lang)
                return
            if action in ("activate_all", "enable_all",
                          "deactivate_all", "disable_all"):
                is_activate = action in ("activate_all", "enable_all")
                confirm_action = ("activate_all_confirm" if is_activate
                                  else "deactivate_all_confirm")
                if is_activate:
                    confirm_text = await _trans('activate_all_confirmation',
                                                 lang, "⚠️")
                else:
                    confirm_text = await _trans('deactivate_all_confirmation',
                                                 lang, "⚠️")
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(await _trans('yes_btn', lang, "✅"),
                        callback_data=f"sec_{confirm_action}:{chat_id}")],
                    [InlineKeyboardButton(await _trans('cancel_btn', lang, "❌"),
                        callback_data=f"{CB.GRP_SET}:{chat_id}")]])
                await _safe_edit(query, confirm_text, reply_markup=kb,
                    bot=context.bot)
                return
            if action in ("activate_all_confirm", "deactivate_all_confirm"):
                await SecurityCallbacks._apply_all_toggle(
                    update, context, query, user_id, lang, chat_id, action)
                return
            if action == "warn":
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(await _trans('warn_toggle_btn',
                        lang, "✅"), callback_data=f"sec_warn_toggle:{chat_id}")],
                    [InlineKeyboardButton(await _trans('warn_count_btn',
                        lang, "🔢"), callback_data=f"sec_warn_count:{chat_id}")],
                    [InlineKeyboardButton(await _trans('warn_penalty_btn',
                        lang, "⚖️"),
                        callback_data=f"sec_warn_penalty:{chat_id}")],
                    [InlineKeyboardButton(await _trans(
                        'warn_penalty_duration_btn', lang, "⏱️"),
                        callback_data=f"sec_warn_penalty_duration:{chat_id}")],
                    [InlineKeyboardButton(
                        KeyboardFactory.get_text("back", lang),
                        callback_data=f"{CB.GRP_SET}:{chat_id}")]])
                await _safe_edit(query,
                    await _trans('warnings_management', lang, "⚠️"),
                    reply_markup=kb, bot=context.bot)
                return
            if action == "banned_words":
                await SecurityCallbacks._show_banned_words_menu(
                    update, context, query, chat_id, lang)
                return
            if action == "toggle_banned_words":
                settings = (await SecurityCallbacks.
                            _get_security_settings_cached(chat_id))
                new_val = 1 - _coerce_int(
                    settings.get('delete_banned_words', 0))
                await DB.update_security_settings(chat_id,
                    delete_banned_words=new_val)
                await SecurityCallbacks._invalidate_security_settings_cache(
                    chat_id
                )
                await SecurityCallbacks._show_banned_words_menu(
                    update, context, query, chat_id, lang)
                return
            if (action in SECURITY_TOGGLE_MAP
                    and action not in _SEC_ACTIONS_WITH_SPECIFIC_HANDLERS):
                col = SECURITY_TOGGLE_MAP[action]
                settings = (await SecurityCallbacks.
                            _get_security_settings_cached(chat_id))
                new_val = 1 - _coerce_int(settings.get(col, 0))
                update_data = {col: new_val}
                if action == "forward":
                    update_data['delete_protected_forward'] = new_val
                    update_data['delete_protected_any'] = new_val
                if action == "approve_join" and new_val:
                    update_data['auto_reject_join'] = 0
                elif action == "reject_join" and new_val:
                    update_data['auto_approve_join'] = 0
                await DB.update_security_settings(chat_id, **update_data)
                await SecurityCallbacks._invalidate_security_settings_cache(
                    chat_id
                )
                await SecurityCallbacks._refresh_security_view(
                    query, context, chat_id, lang)
                return
            if action == "penalty":
                await SecurityCallbacks._show_penalty_types(
                    update, context, query, chat_id, lang)
                return
            if action == "del_pen":
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(await _trans('ban_btn', lang, "🚫"),
                        callback_data=f"sec_set_del_penalty:ban:{chat_id}"),
                     InlineKeyboardButton(await _trans('mute_btn', lang, "🔇"),
                        callback_data=f"sec_set_del_penalty:mute:{chat_id}")],
                    [InlineKeyboardButton(await _trans('kick_btn', lang, "👢"),
                        callback_data=f"sec_set_del_penalty:kick:{chat_id}"),
                     InlineKeyboardButton(await _trans('restrict_btn', lang,
                        "🔒"),
                        callback_data=f"sec_set_del_penalty:restrict:{chat_id}")],
                    [InlineKeyboardButton(await _trans('no_penalty_btn',
                        lang, "🚫"),
                        callback_data=f"sec_set_del_penalty:none:{chat_id}")],
                    [InlineKeyboardButton(await _trans('penalty_duration_btn',
                        lang, "⏱️"),
                        callback_data=f"sec_set_del_penalty_duration:{chat_id}")],
                    [InlineKeyboardButton(
                        KeyboardFactory.get_text("back", lang),
                        callback_data=f"{CB.GRP_SET}:{chat_id}")]])
                await _safe_edit(query,
                    await _trans('choose_delete_penalty', lang, "🚫"),
                    reply_markup=kb, bot=context.bot)
                return
            if action in ("close", "back"):
                StateManager.clear(user_id)
                from handlers_callback import CallbackHandlers
                await CallbackHandlers._show_groups_list(
                    update, context, query, user_id, lang)
                return
            if action == "antiflood_settings":
                await SecurityCallbacks._show_antiflood_settings(
                    update, context, query, chat_id, lang)
                return
            if action == "night_settings":
                await SecurityCallbacks._show_night_settings(
                    update, context, query, chat_id, lang)
                return
            if action == "adv_act":
                await SecurityCallbacks._show_advanced_actions(
                    update, context, query, chat_id, lang)
                return
            if action == "slow_mode_seconds":
                StateManager.set(user_id, UserState.WAIT_SLOW_MODE_SECONDS)
                _set_sec_chat(context, chat_id)
                await _safe_edit(query,
                    await _trans('send_slow_mode_seconds', lang, "⏱️"),
                    bot=context.bot)
                return
            if action == "welcome_text":
                StateManager.set(user_id, UserState.WAIT_WELCOME_TEXT)
                _set_sec_chat(context, chat_id)
                await _safe_edit(query,
                    await _trans('send_welcome_text', lang, "📝"),
                    bot=context.bot)
                return
            if action == "goodbye_text":
                StateManager.set(user_id, UserState.WAIT_GOODBYE_TEXT)
                _set_sec_chat(context, chat_id)
                await _safe_edit(query,
                    await _trans('send_goodbye_text', lang, "📝"),
                    bot=context.bot)
                return
            if action == "set_antiflood_messages":
                StateManager.set(user_id, UserState.WAIT_ANTIFLOOD_MESSAGES)
                _set_sec_chat(context, chat_id)
                await _safe_edit(query,
                    await _trans('send_antiflood_messages', lang, "📊"),
                    bot=context.bot)
                return
            if action == "set_antiflood_seconds":
                StateManager.set(user_id, UserState.WAIT_ANTIFLOOD_SECONDS)
                _set_sec_chat(context, chat_id)
                await _safe_edit(query,
                    await _trans('send_antiflood_seconds', lang, "⏱️"),
                    bot=context.bot)
                return
            if action == "antiflood_penalty":
                await SecurityCallbacks._show_penalty_type_selection(
                    update, context, query, chat_id, lang,
                    'antiflood_penalty')
                return
            if action == "set_night_start":
                StateManager.set(user_id, UserState.WAIT_NIGHT_START)
                _set_sec_chat(context, chat_id)
                await _safe_edit(query,
                    await _trans('send_night_start', lang, "🌙"),
                    bot=context.bot)
                return
            if action == "set_night_end":
                StateManager.set(user_id, UserState.WAIT_NIGHT_END)
                _set_sec_chat(context, chat_id)
                await _safe_edit(query,
                    await _trans('send_night_end', lang, "🌙"),
                    bot=context.bot)
                return
            if action == "night_action":
                await SecurityCallbacks._show_penalty_type_selection(
                    update, context, query, chat_id, lang, 'night_action')
                return
            if action in ("violation_settings", "violation_penalties"):
                await SecurityCallbacks._show_violation_penalties(
                    update, context, query, chat_id, lang)
                return
            if action == "violation_penalty":
                await SecurityCallbacks._show_penalty_type_selection(
                    update, context, query, chat_id, lang,
                    'violation_penalty')
                return
            await _safe_edit(query,
                await _trans('not_available', lang, "⚠️"), bot=context.bot)
        except Exception as e:
            logger.error(f"security error: {e}", exc_info=True)
            await _show_error(query, context, lang)

    @staticmethod
    async def _apply_all_toggle(update, context, query, user_id, lang,
                                 chat_id, action):
        is_activate = (action == "activate_all_confirm")
        activate_values = dict(
            delete_links=1, delete_mentions=1, slow_mode=1,
            slow_mode_seconds=5, delete_videos=1, delete_audio=1,
            delete_animation=1, delete_service=1, delete_documents=1,
            delete_stickers=1, delete_forwarded=1, delete_polls=1,
            delete_games=1, delete_voice=1, delete_video_note=1,
            welcome_enabled=1, goodbye_enabled=1, antiflood_enabled=1,
            antiflood_messages=5, antiflood_seconds=10,
            antiflood_penalty="mute", antiflood_penalty_duration=60,
            night_mode_enabled=1, night_mode_start="22:00",
            night_mode_end="06:00", night_mode_action="mute",
            night_mode_action_duration=3600, auto_approve_join=0,
            auto_reject_join=0, nsfw_enabled=0, warn_enabled=1,
            max_warnings=3, warn_penalty="mute",
            warn_penalty_duration=3600, delete_banned_words=1,
            auto_penalty="mute", delete_penalty="mute",
            delete_penalty_duration=3600, violation_strikes=3,
            violation_duration=60,
            delete_at_channel=1, delete_tg_scheme=1,
            delete_button_links=1, delete_emails=1,
            delete_protected_any=1, delete_postbot_pattern=1)
        deactivate_values = dict(
            delete_links=0, delete_mentions=0, slow_mode=0,
            slow_mode_seconds=0, delete_videos=0, delete_audio=0,
            delete_animation=0, delete_service=0, delete_documents=0,
            delete_stickers=0, delete_forwarded=0, delete_polls=0,
            delete_games=0, delete_voice=0, delete_video_note=0,
            welcome_enabled=0, goodbye_enabled=0, antiflood_enabled=0,
            antiflood_messages=0, antiflood_seconds=0,
            antiflood_penalty="none", antiflood_penalty_duration=0,
            night_mode_enabled=0, night_mode_start="",
            night_mode_end="", night_mode_action="none",
            night_mode_action_duration=0, auto_approve_join=0,
            auto_reject_join=0, nsfw_enabled=0, warn_enabled=0,
            max_warnings=0, warn_penalty="none",
            warn_penalty_duration=0, delete_banned_words=0,
            auto_penalty="none", delete_penalty="none",
            delete_penalty_duration=0, violation_strikes=0,
            violation_duration=0,
            delete_at_channel=0, delete_tg_scheme=0,
            delete_button_links=0, delete_emails=0,
            delete_protected_any=0, delete_postbot_pattern=0)
        values = activate_values if is_activate else deactivate_values
        action_name = (f"{'activate' if is_activate else 'deactivate'}"
                       "_all_security")
        settings_ok = False
        try:
            async with DB.transaction() as _conn:
                await DB.update_security_settings(
                    chat_id, conn=_conn, **values)
                await DB.add_admin_log(
                    chat_id=chat_id, admin_id=user_id,
                    action=action_name, target_id=None,
                    reason="", conn=_conn)
            settings_ok = True
        except TypeError:
            try:
                await DB.update_security_settings(chat_id, **values)
                settings_ok = True
            except Exception:
                await _show_error(query, context, lang)
                return
            try:
                await DB.add_admin_log(chat_id=chat_id,
                    admin_id=user_id, action=action_name)
            except Exception:
                pass
        except Exception:
            await _show_error(query, context, lang)
            return
        if not settings_ok:
            await _show_error(query, context, lang)
            return
        await SecurityCallbacks._invalidate_security_settings_cache(chat_id)
        await _safe_edit(query,
            await _trans('applying_changes', lang, "⏳ جاري التطبيق..."),
            bot=context.bot)
        task = asyncio.create_task(
            SecurityCallbacks._refresh_security_view(
                query, context, chat_id, lang))
        try:
            from handlers_callback import ACTIVE_TASKS
            ACTIVE_TASKS.add(task)
            task.add_done_callback(ACTIVE_TASKS.discard)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════
    # الموجّه للأزرار المعاملاتية
    # ═══════════════════════════════════════════════════════════════
    @staticmethod
    async def handle_parameterized(update, context, query, user_id, lang,
                                    data) -> bool:
        """
        v9.7.19-ROUTING-FIX: يعالج كل الأزرار المعاملاتية التالية:
          - set_warn_count / set_warn_penalty / set_duration
          - set_antiflood_messages / set_antiflood_seconds
          - sec_set_* / sec_penalty_* / sec_warn_*
          - 🆕 act_* / ban_* / pen_* — بمرور cache auth
        """
        try:
            return await SecurityCallbacks._handle_parameterized_inner(
                update, context, query, user_id, lang, data
            )
        except Exception as e:
            logger.error(f"❌ security param: {e}", exc_info=True)
            try:
                await _show_error(query, context, lang)
            except Exception:
                pass
            return True

    @staticmethod
    async def _handle_parameterized_inner(update, context, query, user_id,
                                           lang, data) -> bool:
        # ═══════════════════════════════════════════════════════════
        # 🆕 v9.7.19 FIX-1/2/3: معالجة act_* / ban_* / pen_*
        # ═══════════════════════════════════════════════════════════

        # ─── act_log:<chat> ──────────────────────────────────────
        if data.startswith("act_log:"):
            parts = data.split(":")
            if len(parts) < 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if chat_id == 0 or chat_id == -1:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            await SecurityCallbacks._show_admin_logs(
                update, context, query, chat_id, lang)
            return True

        # ─── ban_add / ban_list / ban_rem ────────────────────────
        if (data.startswith("ban_add:")
                or data.startswith("ban_list:")
                or data.startswith("ban_rem:")):
            parts = data.split(":")
            if len(parts) < 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            action = parts[0][4:]  # add/list/rem
            chat_id = _coerce_int(parts[1])
            # global (-1) يتطلب developer
            if chat_id == -1:
                if not CONFIG.is_developer(user_id):
                    await _safe_edit(query,
                        await _trans('unauthorized', lang, "❌"),
                        bot=context.bot)
                    return True
            else:
                if not await _check_sec_auth(context, user_id, chat_id):
                    await _safe_edit(query,
                        await _trans('no_permission', lang, "❌"),
                        bot=context.bot)
                    return True
            if action == "add":
                state = (UserState.WAIT_GROUP_BAN if chat_id != -1
                         else UserState.WAIT_GLOBAL_BAN)
                StateManager.set(user_id, state)
                context.user_data['ban_chat'] = chat_id
                await _safe_edit(query,
                    await _trans('send_keyword_prompt', lang, "📝"),
                    bot=context.bot)
                return True
            if action == "list":
                try:
                    words = await DB.get_banned_words(chat_id)
                except Exception:
                    words = None
                if words:
                    text = (await _trans('words_list_title_full', lang, "🚫")
                            + "\n\n" + "\n".join(
                                f"• {w}" for w in words[:50]))
                else:
                    text = await _trans('no_data', lang, "📭")
                await _safe_edit(query, text, bot=context.bot)
                return True
            if action == "rem":
                state = (UserState.WAIT_REM_GROUP_BAN if chat_id != -1
                         else UserState.WAIT_REM_GLOBAL_BAN)
                StateManager.set(user_id, state)
                context.user_data['ban_chat'] = chat_id
                await _safe_edit(query,
                    await _trans('send_keyword_delete_prompt', lang, "🗑️"),
                    bot=context.bot)
                return True

        # ─── act_ban / act_mute / act_warn / act_kick / act_restrict /
        #     act_unban / act_pin ───────────────────────────────────
        _act_user_actions = {
            "act_ban":      (UserState.WAIT_BAN,      "send_user_id_ban",      "🚫"),
            "act_mute":     (UserState.WAIT_MUTE,     "send_user_id_mute",     "🔇"),
            "act_warn":     (UserState.WAIT_WARN,     "send_user_id_warn",     "⚠️"),
            "act_kick":     (UserState.WAIT_KICK,     "send_user_id_kick",     "👢"),
            "act_restrict": (UserState.WAIT_RESTRICT, "send_user_id_restrict", "🔒"),
            "act_unban":    (UserState.WAIT_UNBAN,    "send_user_id_unban",    "🔓"),
            "act_pin":      (UserState.WAIT_PIN,      "pin_prompt_full",       "📌"),
        }
        for act_prefix, (state, prompt_key, prompt_default) in \
                _act_user_actions.items():
            if data.startswith(act_prefix + ":"):
                parts = data.split(":")
                if len(parts) < 2:
                    await _safe_edit(query,
                        await _trans('invalid_data', lang, "❌"),
                        bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if chat_id == 0 or chat_id == -1:
                    await _safe_edit(query,
                        await _trans('invalid_data', lang, "❌"),
                        bot=context.bot)
                    return True
                if not await _check_sec_auth(context, user_id, chat_id):
                    await _safe_edit(query,
                        await _trans('no_permission', lang, "❌"),
                        bot=context.bot)
                    return True
                StateManager.set(user_id, state)
                context.user_data['adv_chat'] = chat_id
                await _safe_edit(query,
                    await _trans(prompt_key, lang, prompt_default),
                    bot=context.bot)
                return True

        # ─── pen_<type>:<chat>  (auto_penalty) ───────────────────
        if data.startswith("pen_"):
            parts = data.split(":")
            if len(parts) >= 2:
                penalty_type = parts[0][4:]
                chat_id = _coerce_int(parts[1])
                if penalty_type in ('ban', 'mute', 'kick',
                                     'restrict', 'none'):
                    if not await _check_sec_auth(context, user_id, chat_id):
                        await _safe_edit(query,
                            await _trans('no_permission', lang, "❌"),
                            bot=context.bot)
                        return True
                    try:
                        await DB.update_security_settings(
                            chat_id, auto_penalty=penalty_type)
                    except Exception:
                        await _show_error(query, context, lang)
                        return True
                    await SecurityCallbacks.\
                        _invalidate_security_settings_cache(chat_id)
                    await _safe_edit(query,
                        await _trans('applying_changes', lang,
                                     "⏳ جاري التطبيق..."),
                        bot=context.bot)
                    return True

        # ═══════════════════════════════════════════════════════════
        # نهاية إصلاح v9.7.19 — ما يلي من النسخة الأصلية v9.7.17
        # ═══════════════════════════════════════════════════════════

        # ─── set_warn_count:<chat>:<n> ───────────────────────────
        if data.startswith("set_warn_count:"):
            parts = data.split(":")
            if len(parts) != 3:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1]); count = _coerce_int(parts[2])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            if count < 1 or count > 100:
                await _safe_edit(query,
                    await _trans('invalid_number', lang, "❌"),
                    bot=context.bot)
                return True
            await DB.update_security_settings(chat_id, max_warnings=count)
            await SecurityCallbacks._invalidate_security_settings_cache(
                chat_id)
            await SecurityCallbacks._refresh_security_view(
                query, context, chat_id, lang)
            return True

        # ─── set_antiflood_messages:<chat>:<n> ────────────────────
        if data.startswith("set_antiflood_messages:"):
            parts = data.split(":")
            if len(parts) != 3:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            value = _coerce_int(parts[2])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            if value < 1 or value > _ANTIFLOOD_MESSAGES_MAX:
                await _safe_edit(query,
                    await _trans('invalid_number', lang, "❌"),
                    bot=context.bot)
                return True
            try:
                await DB.update_security_settings(
                    chat_id, antiflood_messages=value
                )
            except Exception:
                await _show_error(query, context, lang)
                return True
            await SecurityCallbacks._invalidate_security_settings_cache(
                chat_id)
            await SecurityCallbacks._show_antiflood_messages_buttons(
                update, context, query, chat_id, lang
            )
            return True

        # ─── set_antiflood_seconds:<chat>:<n> ─────────────────────
        if data.startswith("set_antiflood_seconds:"):
            parts = data.split(":")
            if len(parts) != 3:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            value = _coerce_int(parts[2])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            if value < 1 or value > _ANTIFLOOD_SECONDS_MAX:
                await _safe_edit(query,
                    await _trans('invalid_number', lang, "❌"),
                    bot=context.bot)
                return True
            try:
                await DB.update_security_settings(
                    chat_id, antiflood_seconds=value
                )
            except Exception:
                await _show_error(query, context, lang)
                return True
            await SecurityCallbacks._invalidate_security_settings_cache(
                chat_id)
            await SecurityCallbacks._show_antiflood_seconds_buttons(
                update, context, query, chat_id, lang
            )
            return True

        # ─── set_warn_penalty:<type>:<chat> ───────────────────────
        if data.startswith("set_warn_penalty:"):
            parts = data.split(":")
            if len(parts) != 3:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            _, penalty_type, chat_id_str = parts
            chat_id = _coerce_int(chat_id_str)
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            if penalty_type not in DB.VALID_PENALTY_TYPES:
                await _safe_edit(query,
                    await _trans('invalid_penalty_type', lang, "❌"),
                    bot=context.bot)
                return True
            await DB.update_security_settings(chat_id,
                warn_penalty=penalty_type)
            await SecurityCallbacks._invalidate_security_settings_cache(
                chat_id)
            await SecurityCallbacks._refresh_security_view(
                query, context, chat_id, lang)
            return True

        # ─── set_duration:<type>:<chat>:<secs> ────────────────────
        if data.startswith("set_duration:"):
            parts = data.split(":")
            if len(parts) < 4:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            penalty_type = parts[1]
            chat_id = _coerce_int(parts[2])
            duration = _coerce_int(parts[3])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            col_map = {
                'mute': 'mute_default_duration',
                'ban': 'ban_default_duration',
                'restrict': 'restrict_default_duration',
                'antiflood': 'antiflood_penalty_duration',
                'night': 'night_mode_action_duration',
                'warn_penalty': 'warn_penalty_duration',
                'delete_penalty': 'delete_penalty_duration',
                'violation': 'violation_penalty_duration'}
            col = col_map.get(penalty_type)
            if col is None:
                await _safe_edit(query,
                    await _trans('invalid_penalty_type', lang, "❌"),
                    bot=context.bot)
                return True
            await DB.update_security_settings(chat_id, **{col: duration})
            await SecurityCallbacks._invalidate_security_settings_cache(
                chat_id)
            await SecurityCallbacks._refresh_security_view(
                query, context, chat_id, lang)
            return True

        # ─── sec_set_del_penalty_duration:<chat> ──────────────────
        if data.startswith("sec_set_del_penalty_duration:"):
            parts = data.split(":")
            if len(parts) != 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            await SecurityCallbacks._show_penalty_durations(
                update, context, query, chat_id, lang, 'delete_penalty')
            return True

        # ─── sec_set_del_penalty:<type>:<chat> ────────────────────
        if data.startswith("sec_set_del_penalty:"):
            parts = data.split(":")
            if len(parts) != 3:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            _, penalty_type, chat_id_str = parts
            chat_id = _coerce_int(chat_id_str)
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            if penalty_type == "none":
                await DB.update_security_settings(chat_id,
                    delete_penalty="none")
            elif penalty_type in DB.VALID_PENALTY_TYPES:
                await DB.update_security_settings(chat_id,
                    delete_penalty=penalty_type)
            else:
                await _safe_edit(query,
                    await _trans('invalid_penalty_type', lang, "❌"),
                    bot=context.bot)
                return True
            await SecurityCallbacks._invalidate_security_settings_cache(
                chat_id)
            await SecurityCallbacks._refresh_security_view(
                query, context, chat_id, lang)
            return True

        # ─── sec_penalty_durations:<chat> ─────────────────────────
        if data.startswith("sec_penalty_durations:"):
            parts = data.split(":")
            if len(parts) != 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            await SecurityCallbacks._show_all_penalty_durations_menu(
                query, context, chat_id, lang)
            return True

        # ─── sec_set_*_duration / sec_*_duration ──────────────────
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
                    await _safe_edit(query,
                        await _trans('invalid_data', lang, "❌"),
                        bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await _safe_edit(query,
                        await _trans('no_permission', lang, "❌"),
                        bot=context.bot)
                    return True
                await SecurityCallbacks._show_penalty_durations(
                    update, context, query, chat_id, lang, action_type)
                return True

        # ─── sec_warn_penalty_duration:<chat> ─────────────────────
        if data.startswith("sec_warn_penalty_duration:"):
            parts = data.split(":")
            if len(parts) != 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            await SecurityCallbacks._show_penalty_durations(
                update, context, query, chat_id, lang, 'warn_penalty')
            return True

        # ─── sec_warn_penalty:<chat> ──────────────────────────────
        if data.startswith("sec_warn_penalty:"):
            parts = data.split(":")
            if len(parts) != 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            await SecurityCallbacks._show_warn_penalty_types(
                update, context, query, chat_id, lang)
            return True

        # ─── sec_warn_count:<chat> ────────────────────────────────
        if data.startswith("sec_warn_count:"):
            parts = data.split(":")
            if len(parts) != 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            await SecurityCallbacks._show_warn_count_buttons(
                update, context, query, chat_id, lang)
            return True

        # ─── sec_warn_toggle:<chat> ───────────────────────────────
        if data.startswith("sec_warn_toggle:"):
            parts = data.split(":")
            if len(parts) != 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            settings = (await SecurityCallbacks.
                        _get_security_settings_cached(chat_id))
            new_val = 1 - _coerce_int(settings.get('warn_enabled', 0))
            await DB.update_security_settings(chat_id, warn_enabled=new_val)
            await SecurityCallbacks._invalidate_security_settings_cache(
                chat_id)
            await SecurityCallbacks._refresh_security_view(
                query, context, chat_id, lang)
            return True

        # ─── sec_penalty_<type>:<chat> ────────────────────────────
        if data.startswith("sec_penalty_"):
            parts = data.split(":")
            if len(parts) < 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            if parts[1].lstrip('-').isdigit():
                chat_id = int(parts[1])
            else:
                chat_id = await _resolve_sec_chat_id(context, data)
            if chat_id is None:
                await _safe_edit(query,
                    await _trans('group_not_specified', lang, "❌"),
                    bot=context.bot)
                return True
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            action = (parts[0][4:] if parts[0].startswith("sec_")
                      else parts[0])
            if action.startswith("penalty_"):
                action = action[len("penalty_"):]
            if action in ('ban', 'mute', 'kick', 'restrict', 'none'):
                await DB.update_security_settings(chat_id,
                    auto_penalty=action)
                await SecurityCallbacks._invalidate_security_settings_cache(
                    chat_id
                )
                await SecurityCallbacks._refresh_security_view(
                    query, context, chat_id, lang)
            else:
                await _safe_edit(query,
                    await _trans('invalid_penalty_type', lang, "❌"),
                    bot=context.bot)
            return True

        # ─── sec_set_antiflood_messages / seconds:<chat> ──────────
        if data.startswith("sec_set_antiflood_messages:"):
            parts = data.split(":")
            if len(parts) != 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            StateManager.clear(user_id)
            await SecurityCallbacks._show_antiflood_messages_buttons(
                update, context, query, chat_id, lang)
            return True

        if data.startswith("sec_set_antiflood_seconds:"):
            parts = data.split(":")
            if len(parts) != 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            StateManager.clear(user_id)
            await SecurityCallbacks._show_antiflood_seconds_buttons(
                update, context, query, chat_id, lang)
            return True

        # ─── sec_antiflood_penalty / sec_set_antiflood_penalty ────
        if data.startswith("sec_antiflood_penalty:"):
            parts = data.split(":")
            if len(parts) != 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            await SecurityCallbacks._show_penalty_type_selection(
                update, context, query, chat_id, lang, 'antiflood_penalty')
            return True

        if data.startswith("sec_set_antiflood_penalty:"):
            parts = data.split(":")
            if len(parts) < 3:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            penalty_type = parts[2]
            if penalty_type in ('ban', 'mute', 'kick', 'restrict', 'none'):
                await DB.update_security_settings(chat_id,
                    antiflood_penalty=penalty_type)
                await SecurityCallbacks._invalidate_security_settings_cache(
                    chat_id
                )
                await SecurityCallbacks._refresh_security_view(
                    query, context, chat_id, lang)
            return True

        # ─── sec_set_night_start / sec_set_night_end ──────────────
        for prefix, state, prompt_key, prompt_default in (
            ("sec_set_night_start:", UserState.WAIT_NIGHT_START,
             "send_night_start", "🌙 Send start time (HH:MM):"),
            ("sec_set_night_end:", UserState.WAIT_NIGHT_END,
             "send_night_end", "🌙 Send end time (HH:MM):")):
            if data.startswith(prefix):
                parts = data.split(":")
                if len(parts) != 2:
                    await _safe_edit(query,
                        await _trans('invalid_data', lang, "❌"),
                        bot=context.bot)
                    return True
                chat_id = _coerce_int(parts[1])
                if not await _check_sec_auth(context, user_id, chat_id):
                    await _safe_edit(query,
                        await _trans('no_permission', lang, "❌"),
                        bot=context.bot)
                    return True
                StateManager.set(user_id, state)
                _set_sec_chat(context, chat_id)
                await _safe_edit(query,
                    await _trans(prompt_key, lang, prompt_default),
                    bot=context.bot)
                return True

        # ─── sec_night_action / sec_set_night_action ──────────────
        if data.startswith("sec_night_action:"):
            parts = data.split(":")
            if len(parts) != 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            await SecurityCallbacks._show_penalty_type_selection(
                update, context, query, chat_id, lang, 'night_action')
            return True

        if data.startswith("sec_set_night_action:"):
            parts = data.split(":")
            if len(parts) < 3:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            action_type = parts[2]
            if action_type in ('ban', 'mute', 'kick', 'restrict'):
                await DB.update_security_settings(chat_id,
                    night_mode_action=action_type)
                await SecurityCallbacks._invalidate_security_settings_cache(
                    chat_id
                )
                await SecurityCallbacks._refresh_security_view(
                    query, context, chat_id, lang)
            return True

        # ─── sec_violation_settings:<chat> ────────────────────────
        if data.startswith("sec_violation_settings:"):
            parts = data.split(":")
            if len(parts) != 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            await SecurityCallbacks._show_violation_penalties(
                update, context, query, chat_id, lang)
            return True

        # ─── sec_set_violation_strikes:<chat> ─────────────────────
        if data.startswith("sec_set_violation_strikes:"):
            parts = data.split(":")
            if len(parts) != 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            StateManager.set(user_id, UserState.WAIT_VIOLATION_STRIKES)
            _set_sec_chat(context, chat_id)
            await _safe_edit(query,
                await _trans('send_violation_strikes', lang, "🔢"),
                bot=context.bot)
            return True

        # ─── sec_set_violation_duration:<chat> ────────────────────
        if data.startswith("sec_set_violation_duration:"):
            parts = data.split(":")
            if len(parts) != 2:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            await SecurityCallbacks._show_penalty_durations(
                update, context, query, chat_id, lang, 'violation')
            return True

        # ─── sec_set_violation_penalty:<chat>:<type> ──────────────
        if data.startswith("sec_set_violation_penalty:"):
            parts = data.split(":")
            if len(parts) < 3:
                await _safe_edit(query,
                    await _trans('invalid_data', lang, "❌"),
                    bot=context.bot)
                return True
            chat_id = _coerce_int(parts[1])
            if not await _check_sec_auth(context, user_id, chat_id):
                await _safe_edit(query,
                    await _trans('no_permission', lang, "❌"),
                    bot=context.bot)
                return True
            penalty_type = parts[2]
            if penalty_type in ('ban', 'mute', 'kick', 'restrict', 'none'):
                await DB.update_security_settings(chat_id,
                    violation_penalty=penalty_type)
                await SecurityCallbacks._invalidate_security_settings_cache(
                    chat_id
                )
                await SecurityCallbacks._refresh_security_view(
                    query, context, chat_id, lang)
            return True

        # ─── sec_close / grp_close / back_to_groups ───────────────
        if data in ("sec_close", "grp_close", "security_close",
                    "back_to_groups", "sec_back"):
            StateManager.clear(user_id)
            from handlers_callback import (
                CallbackHandlers, _clear_context_keys,
            )
            _clear_context_keys(context)
            await CallbackHandlers._show_groups_list(
                update, context, query, user_id, lang)
            return True
        if (data.startswith("sec_close:")
                or data.startswith("grp_close:")
                or data.startswith("back_to_groups:")
                or data.startswith("sec_back:")):
            StateManager.clear(user_id)
            from handlers_callback import (
                CallbackHandlers, _clear_context_keys,
            )
            _clear_context_keys(context)
            await CallbackHandlers._show_groups_list(
                update, context, query, user_id, lang)
            return True

        # ─── CB.GRP_SET:<chat> → فتح شاشة الأمان ──────────────────
        if data.startswith(CB.GRP_SET + ":"):
            await SecurityCallbacks.handle_group_settings(
                update, context, query, user_id, lang, data)
            return True

        return False

    # ─── فتح شاشة الأمان للمجموعة ──────────────────────────────────
    @staticmethod
    async def handle_group_settings(update, context, query, user_id, lang,
                                     data):
        try:
            chat_id = int(data.split(":")[-1])
        except (ValueError, IndexError):
            await _safe_edit(query,
                await _trans('invalid_data', lang, "❌"), bot=context.bot)
            return
        if not await _check_sec_auth(context, user_id, chat_id):
            await _safe_edit(query,
                await _trans('no_permission', lang, "❌"), bot=context.bot)
            return
        _set_sec_chat(context, chat_id)
        await SecurityCallbacks._render_security_two_phase(
            query, context, chat_id, lang, force_refresh_settings=False)


__all__ = [
    "SecurityCallbacks",
    "set_metrics_inc", "set_safe_edit",
    "_check_sec_auth", "_invalidate_sec_auth_cache",
    "_prune_sec_auth_cache", "_set_sec_chat", "_resolve_sec_chat_id",
    "_sec_auth_cache", "_sec_auth_neg_cache", "_sec_auth_locks",
    "_security_stats_cache_local",
    "_ANTIFLOOD_MESSAGES_OPTIONS", "_ANTIFLOOD_SECONDS_OPTIONS",
    "_ANTIFLOOD_MESSAGES_MAX", "_ANTIFLOOD_SECONDS_MAX",
    "_SEC_ACTIONS_WITH_SPECIFIC_HANDLERS",
    "_SEC_AUTH_NEG_BASE", "_SEC_AUTH_NEG_MAX", "_SEC_AUTH_PRUNE_EVERY",
    "safe_edit",
]

logger.info("🔐 callback_security.py loaded (v9.7.19-ROUTING-FIX)")