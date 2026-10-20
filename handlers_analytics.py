#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_analytics.py — واجهة التحليلات المتقدمة (v1.3.3 — AUTOTUNE-INTEGRATION)
================================================================================
v1.3.3 — فوق v1.3.2:

    🆕 AUTO-1: زر جديد ⚙️ "ضبط autovacuum" (autotune_btn) —
        يستدعي diagnose_autovacuum_tuning(force=True) من db_diagnostics
        v7.2.24+ ويعرض التقرير الناتج.

    🆕 AUTO-2: أمر /autotune — مكافئ للزر، من أي محادثة.

    🆕 AUTO-3: cmd_autotune + show_autotune — fallback آمن إذا
        db_diagnostics < v7.2.24 (رسالة إرشادية بدل خطأ).

    🆕 AUTO-4: الزر يظهر دائماً في القائمة، لكن يعرض "غير متاح"
        إذا لم يكن db_diagnostics >= v7.2.24.

    🆕 AUTO-5: ANALYTICS_BUTTONS أضيف فيه "autotune_btn".

    🆕 AUTO-6: __all__ تصدير show_autotune + cmd_autotune.

v1.3.2 — محفوظ:
    🟢 CLEAN-1: regex-escape آمن.
    🟢 CLEAN-2: إزالة الفحص المزدوج في cmd_analytics.
    🟢 CLEAN-3: تصدير صريح لـ_register_analytics_handlers.

v1.3.1 — محفوظ:
    🔴 FIX-1: force_refresh=True → False.
    🟢 NEW-1: /databases command.
    🟢 NEW-2: زر 🗂️ قواعد البيانات.
    🟢 NEW-3: show_databases() يستدعي diagnose_databases().

v1.3.0 — محفوظ:
    🚀 PERF-1: cache ذكي (TTL=60s).
    🚀 PERF-2: رد فوري على callback.
    🎯 FEAT-1..3.
    ✅ HA1..HA31 محفوظة.

v1.2.3..1.1.1 — محفوظة.
================================================================================
"""

import logging
import re as _re_mod
import io
import time
import html as _html_mod
import traceback as _tb
import importlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple, Callable, Awaitable, Union

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, CommandHandler,
)
from telegram.error import BadRequest

from config import CONFIG
from database import DB
from utils import (
    CB, TimeUtils, safe_send, KeyboardFactory,
    TranslationManager,
)

logger = logging.getLogger(__name__)


ANALYTICS_BUTTONS = (
    "admin_analytics",
    "growth_30d_btn",
    "top_channels_btn",
    "publish_stats_btn",
    "channels_rate_btn",
    "subscriptions_btn",
    "pool_live_btn",
    "slow_queries_btn",
    "export_excel_btn",
    "refresh_btn",
    "full_health_btn",
    "latency_btn",
    "databases_btn",
    "autotune_btn",         # 🆕 v1.3.3
)


# ═══════════════════════════════════════════════════════════════════════
# 🆕 v1.3.3 — كشف توفر ميزة الضبط التلقائي (v7.2.24+)
# ═══════════════════════════════════════════════════════════════════════

_AUTOTUNE_AVAILABLE = False
_AUTOTUNE_IMPORT_ERROR: Optional[str] = None

try:
    from db_diagnostics import (
        diagnose_autovacuum_tuning as _diagnose_autovacuum_tuning_fn,
        VERSION as _DB_DIAG_VERSION_AT,
    )
    _AUTOTUNE_AVAILABLE = True
except Exception as _at_err:
    _diagnose_autovacuum_tuning_fn = None
    try:
        from db_diagnostics import VERSION as _DB_DIAG_VERSION_AT
    except Exception:
        _DB_DIAG_VERSION_AT = "unknown"
    _AUTOTUNE_IMPORT_ERROR = f"{type(_at_err).__name__}: {_at_err}"


# ═══════════════════════════════════════════════════════════════════════
# Cache ذكي لاستعلامات DB
# ═══════════════════════════════════════════════════════════════════════

_DB_CACHE: Dict[str, Tuple[Any, float]] = {}
_DB_CACHE_TTL_DEFAULT = 60.0
_DB_CACHE_MAX_ENTRIES = 100


async def _cached_db_call(
    cache_key: str,
    coro_factory: Callable[[], Awaitable[Any]],
    ttl: float = _DB_CACHE_TTL_DEFAULT,
    force_refresh: bool = False,
) -> Any:
    """
    cache ذكي لاستعلامات DB.

    v1.3.1 FIX-1: افتراضي force_refresh=False.
    زر التحديث في handle_analytics_callback يُبطل cache ثم يستدعي.
    """
    now = time.monotonic()
    if not force_refresh:
        entry = _DB_CACHE.get(cache_key)
        if entry:
            data, ts = entry
            if (now - ts) < ttl:
                logger.debug(
                    "💾 CACHE hit: %s (age=%.1fs)",
                    cache_key, now - ts,
                )
                return data

    try:
        result = await coro_factory()
    except Exception as e:
        logger.warning(
            "❌ _cached_db_call(%s) فشل: %s", cache_key, e,
        )
        raise

    if len(_DB_CACHE) >= _DB_CACHE_MAX_ENTRIES:
        try:
            oldest = sorted(
                _DB_CACHE.items(),
                key=lambda kv: kv[1][1],
            )[: max(1, _DB_CACHE_MAX_ENTRIES // 5)]
            for k, _ in oldest:
                _DB_CACHE.pop(k, None)
        except Exception:
            _DB_CACHE.clear()
    _DB_CACHE[cache_key] = (result, now)
    logger.debug("💾 CACHE store: %s", cache_key)
    return result


def _invalidate_analytics_cache(prefix: Optional[str] = None) -> int:
    """إبطال cache (كل أو ببادئة)."""
    if prefix is None:
        n = len(_DB_CACHE)
        _DB_CACHE.clear()
        return n
    keys_to_del = [k for k in _DB_CACHE if k.startswith(prefix)]
    for k in keys_to_del:
        _DB_CACHE.pop(k, None)
    return len(keys_to_del)


def _get_cache_stats() -> Dict[str, Any]:
    """إحصائيات cache."""
    now = time.monotonic()
    out = {
        "total_keys": len(_DB_CACHE),
        "max_entries": _DB_CACHE_MAX_ENTRIES,
        "default_ttl": _DB_CACHE_TTL_DEFAULT,
        "keys": {},
    }
    for k, (_, ts) in _DB_CACHE.items():
        age = now - ts
        out["keys"][k] = round(age, 1)
    return out


# ═══════════════════════════════════════════════════════════════════════
# دوال مساعدة
# ═══════════════════════════════════════════════════════════════════════

def _t(key: str, default: str, lang: str = "ar") -> str:
    try:
        text = TranslationManager.get_text(lang, key)
        if text and text != key:
            return text
    except Exception:
        pass
    try:
        return KeyboardFactory.get_text(key, lang) or default
    except Exception:
        return default


def _bar(value: float, max_value: float, width: int = 10,
         filled: str = "█", empty: str = "░") -> str:
    try:
        v = float(value)
        m = float(max_value)
        if m <= 0:
            return empty * width
        ratio = min(1.0, max(0.0, v / m))
        n = int(round(ratio * width))
        return filled * n + empty * (width - n)
    except Exception:
        return empty * width


def _bar_with_pct(value: float, max_value: float,
                  width: int = 10) -> str:
    try:
        v = float(value)
        m = float(max_value)
        if m <= 0:
            pct = 0.0
        else:
            pct = min(100.0, max(0.0, v / m * 100))
        bar = _bar(v, m, width=width)
        return f"{bar} <b>{pct:.0f}%</b>"
    except Exception:
        return f"{'░' * width} <b>0%</b>"


def _growth_arrow(delta_pct: float) -> str:
    if delta_pct > 5:
        return "📈"
    if delta_pct > 0:
        return "↗️"
    if delta_pct < -5:
        return "📉"
    if delta_pct < 0:
        return "↘️"
    return "➡️"


def _check_developer(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    try:
        if hasattr(CONFIG, "is_developer"):
            return bool(CONFIG.is_developer(user_id))
        return user_id == int(CONFIG.PRIMARY_OWNER_ID)
    except Exception as e:
        logger.warning("_check_developer(%s): %s", user_id, e)
        return False


def _get_safe_user_id(update: Update) -> Optional[int]:
    try:
        user = getattr(update, "effective_user", None)
        if user is None:
            return None
        uid = getattr(user, "id", None)
        return uid if uid is not None else None
    except Exception:
        return None


def _safe_get_chat_id(update: Update, query=None) -> Optional[int]:
    try:
        if query is not None and getattr(query, 'message', None):
            cid = getattr(query.message, 'chat_id', None)
            if cid is not None:
                return cid
    except Exception:
        pass
    try:
        if update is not None and getattr(update, 'effective_chat', None):
            cid = getattr(update.effective_chat, 'id', None)
            if cid is not None:
                return cid
    except Exception:
        pass
    try:
        if query is not None and getattr(query, 'from_user', None):
            uid = getattr(query.from_user, 'id', None)
            if uid is not None:
                return uid
    except Exception:
        pass
    return None


async def _reject_non_dev(bot, chat_id: Optional[int], query=None,
                          message: str = "❌ هذا الأمر للمطور فقط.") -> None:
    if query is not None:
        try:
            await query.answer(message, show_alert=True)
            return
        except Exception as e:
            logger.debug(f"_reject_non_dev (query.answer): {e}")
    if chat_id is not None:
        try:
            await safe_send(bot, chat_id, message)
        except Exception as e:
            logger.warning(f"_reject_non_dev (safe_send): {e}")


def _is_parse_error(err_str: str) -> bool:
    low = (err_str or "").lower()
    return any(k in low for k in (
        "can't parse",
        "can't find end tag",
        "unsupported start tag",
        "unclosed tag",
        "invalid entity",
    ))


def _strip_html(text: str) -> str:
    if not text:
        return text
    try:
        import html as _h
        return _h.unescape(_re_mod.sub(r"<[^>]+>", "", text))
    except Exception:
        return text


async def _quick_answer(query, text: str = "") -> None:
    if query is None:
        return
    try:
        await query.answer(text or "")
    except Exception as e:
        logger.debug(f"_quick_answer: {e}")


async def _safe_edit(query, text: str, keyboard=None,
                     parse_mode: str = "HTML") -> bool:
    if query is None or getattr(query, 'message', None) is None:
        return False

    try:
        await query.edit_message_text(
            text, parse_mode=parse_mode, reply_markup=keyboard,
            disable_web_page_preview=True,
        )
        return True
    except BadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return True
        if parse_mode and _is_parse_error(err):
            logger.warning(
                "⚠️ _safe_edit parse failed — fallback plain | %.80s",
                text,
            )
            try:
                await query.edit_message_text(
                    _strip_html(text), parse_mode=None,
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
                return True
            except Exception as e2:
                logger.debug(f"_safe_edit plain fallback: {e2}")
        if "there is no text in the message" in err or \
           "message can't be edited" in err:
            try:
                await query.edit_message_caption(
                    caption=text, parse_mode=parse_mode,
                    reply_markup=keyboard,
                )
                return True
            except Exception as e2:
                logger.debug(f"_safe_edit caption fallback: {e2}")
    except Exception as e:
        logger.debug(f"_safe_edit non-bad: {type(e).__name__}: {e}")

    try:
        chat_id = None
        try:
            chat_id = query.message.chat_id
        except Exception:
            pass
        if chat_id is None:
            return False
        await safe_send(
            query.bot, chat_id, text,
            reply_markup=keyboard, parse_mode=parse_mode,
        )
        return True
    except Exception as e:
        logger.debug(f"_safe_edit send fallback: {e}")
        return False


async def _safe_send_long(bot, chat_id: int, text: str,
                          parse_mode: str = "HTML",
                          reply_markup=None) -> bool:
    if not text or chat_id is None:
        return False

    async def _send_one(cid, body, kb, pmode) -> bool:
        try:
            await bot.send_message(
                cid, body, parse_mode=pmode,
                disable_web_page_preview=True,
                reply_markup=kb,
            )
            return True
        except BadRequest as be:
            if pmode and _is_parse_error(str(be)):
                logger.warning(
                    "⚠️ _safe_send_long parse failed — plain | %.80s",
                    body,
                )
                try:
                    await bot.send_message(
                        cid, _strip_html(body), parse_mode=None,
                        disable_web_page_preview=True,
                        reply_markup=kb,
                    )
                    return True
                except Exception as e2:
                    logger.warning(
                        f"_safe_send_long plain fallback: {e2}")
                    return False
            logger.warning(f"_safe_send_long BadRequest: {be}")
            return False
        except Exception as e:
            logger.warning(f"_safe_send_long: {type(e).__name__}: {e}")
            return False

    MAX = 3800
    if len(text) <= MAX:
        return await _send_one(chat_id, text, reply_markup, parse_mode)

    chunks: List[str] = []
    remaining = text
    while len(remaining) > MAX:
        cut = remaining.rfind("\n", 0, MAX)
        if cut < MAX // 2:
            cut = MAX
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)

    total = len(chunks)
    all_ok = True
    for i, chunk in enumerate(chunks, 1):
        header = f"<i>({i}/{total})</i>\n" if total > 1 else ""
        kb = reply_markup if i == total else None
        ok = await _send_one(chat_id, header + chunk, kb, parse_mode)
        if not ok:
            logger.warning(
                "_safe_send_long: توقف عند الصفحة %d/%d",
                i, total,
            )
            all_ok = False
            break
    return all_ok


def _back_keyboard(
    target: str = "admin_analytics", lang: str = "ar"
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            _t("back", "🔙 رجوع", lang),
            callback_data=target,
        )
    ]])


def _back_refresh_keyboard(target: str = "admin_analytics",
                           refresh: str = "refresh_btn",
                           lang: str = "ar"
                           ) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            _t("refresh_btn", "🔄 تحديث", lang),
            callback_data=refresh,
        )],
        [InlineKeyboardButton(
            _t("back", "🔙 رجوع", lang),
            callback_data=target,
        )],
    ])


def _fmt_num(n) -> str:
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_elapsed(sec) -> str:
    try:
        s = float(sec)
    except (TypeError, ValueError):
        return "?"
    if not (s == s) or s < 0 or s == float("inf"):
        return "?"
    if s < 1:
        try:
            return f"{int(s * 1000)}ms"
        except (OverflowError, ValueError):
            return "?"
    if s < 60:
        return f"{s:.2f}s"
    return f"{int(s // 60)}m{int(s % 60)}s"


def _err_detail(e: Exception) -> str:
    try:
        tb_lines = _tb.format_exc().strip().split("\n")
        loc = " | ".join(
            l.strip() for l in tb_lines[-3:-1] if l.strip()
        )[:200]
    except Exception:
        loc = "?"
    try:
        err_type = type(e).__name__
        err_msg = str(e)[:250]
    except Exception:
        err_type = "Unknown"
        err_msg = "?"
    if not err_msg:
        err_msg = "(بدون رسالة)"
    safe_type = _html_mod.escape(err_type)
    safe_msg = _html_mod.escape(err_msg)
    safe_loc = _html_mod.escape(loc)

    suggestion = ""
    err_low = err_msg.lower() + " " + err_type.lower()
    if "attribute" in err_low and "none" in err_low:
        suggestion = "\n💡 <i>احتمال: update/query/message=None</i>"
    elif "timeout" in err_low:
        suggestion = "\n💡 <i>احتمال: الشبكة بطيئة أو DB مشبع</i>"
    elif "asyncpg" in err_low or "connection" in err_low:
        suggestion = "\n💡 <i>احتمال: DB pool استنفد أو انقطع</i>"
    elif "openpyxl" in err_low:
        suggestion = "\n💡 <i>ثبّت: pip install openpyxl</i>"
    elif "permission" in err_low or "forbidden" in err_low:
        suggestion = "\n💡 <i>احتمال: البوت غير مشرف أو محظور</i>"

    return (
        f"<b>النوع:</b> <code>{safe_type}</code>\n"
        f"<b>الرسالة:</b> <code>{safe_msg}</code>\n"
        f"<b>الموقع:</b> <code>{safe_loc}</code>"
        f"{suggestion}"
    )


def _default_analytics_keyboard(lang: str = "ar") -> InlineKeyboardMarkup:
    def _lbl(key: str, default: str) -> str:
        try:
            return _t(key, default, lang)
        except Exception:
            return default

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            _lbl("analytics_growth", "📈 نمو المستخدمين"),
            callback_data="growth_30d_btn"),
         InlineKeyboardButton(
            _lbl("analytics_top_channels", "🏆 أفضل القنوات"),
            callback_data="top_channels_btn")],
        [InlineKeyboardButton(
            _lbl("analytics_publish_stats", "📊 متوسط النشر"),
            callback_data="publish_stats_btn"),
         InlineKeyboardButton(
            _lbl("analytics_channels_rate", "🎯 نسبة النجاح"),
            callback_data="channels_rate_btn")],
        [InlineKeyboardButton(
            _lbl("analytics_subscriptions", "💎 الاشتراكات"),
            callback_data="subscriptions_btn"),
         InlineKeyboardButton(
            _lbl("analytics_pool", "🚀 Pool مباشر"),
            callback_data="pool_live_btn")],
        [InlineKeyboardButton(
            _lbl("analytics_slow_queries", "🐌 استعلامات بطيئة"),
            callback_data="slow_queries_btn"),
         InlineKeyboardButton(
            _lbl("analytics_export", "📤 تصدير Excel"),
            callback_data="export_excel_btn")],
        [InlineKeyboardButton(
            _lbl("analytics_full_health", "🏥 التشخيص الشامل"),
            callback_data="full_health_btn"),
         InlineKeyboardButton(
            _lbl("analytics_latency", "🔬 اختبار الكمون"),
            callback_data="latency_btn")],
        # 🆕 v1.3.3 — صف واحد: databases + autotune
        [InlineKeyboardButton(
            _lbl("analytics_databases", "🗂️ قواعد البيانات"),
            callback_data="databases_btn"),
         InlineKeyboardButton(
            _lbl("analytics_autotune", "⚙️ ضبط autovacuum"),
            callback_data="autotune_btn")],
        [InlineKeyboardButton(
            _lbl("refresh_btn", "🔄 تحديث"),
            callback_data="refresh_btn")],
        [InlineKeyboardButton(
            _lbl("back", "🔙 رجوع"),
            callback_data="admin")],
    ])


# ═══════════════════════════════════════════════════════════════════════
# 1) القائمة الرئيسية
# ═══════════════════════════════════════════════════════════════════════

async def show_analytics_menu(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        query = update.callback_query
        user_id = _get_safe_user_id(update)
        chat_id = _safe_get_chat_id(update, query)

        await _quick_answer(query)

        if user_id is None:
            return

        if not _check_developer(user_id):
            await _reject_non_dev(
                context.bot, chat_id, query,
                "❌ لوحة التحليلات للمطور فقط.",
            )
            return

        missing = []
        for _fn in (
            "get_user_growth", "get_top_channels",
            "get_publish_stats", "get_subscription_rate",
            "get_pool_live", "get_slowest_queries",
        ):
            if not hasattr(DB, _fn):
                missing.append(_fn)

        use_pg = bool(getattr(DB, "USE_POSTGRES", False))
        db_type = str(getattr(DB, "DB_TYPE", "?")).upper()

        if not use_pg:
            text = (
                "📊 <b>التحليلات المتقدمة</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"⚠️ هذه الميزة تتطلب <b>PostgreSQL</b>.\n"
                f"النوع الحالي: <code>{db_type}</code>"
            )
            if query:
                await _safe_edit(query, text, _back_keyboard("admin"))
            elif chat_id is not None:
                await safe_send(
                    context.bot, chat_id, text,
                    reply_markup=_back_keyboard("admin"),
                )
            return

        if missing:
            text = (
                "⚠️ <b>تحذير — دوال مفقودة</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<b>دوال غير موجودة في DB:</b>\n"
                + "\n".join(f"  ❌ <code>{m}</code>" for m in missing)
                + "\n\n💡 <b>السبب:</b> "
                "<code>database.py</code> لا يرث من "
                "<code>AnalyticsMixin</code>.\n\n"
                "✅ <b>الحل:</b> ارفع <code>database.py</code> v7.7.65+"
            )
            if query:
                await _safe_edit(query, text, _back_keyboard("admin"))
            elif chat_id is not None:
                await safe_send(
                    context.bot, chat_id, text,
                    reply_markup=_back_keyboard("admin"),
                )
            return

        try:
            keyboard = KeyboardFactory.build("analytics", lang="ar")
        except Exception:
            keyboard = _default_analytics_keyboard(lang="ar")

        cache_stats = _get_cache_stats()
        cache_info = (
            f"\n💾 cache: <b>{cache_stats['total_keys']}</b>"
            f"/{cache_stats['max_entries']}"
        )

        # 🆕 v1.3.3 — مؤشر توفّر الضبط التلقائي
        autotune_line = (
            "⚙️ autovacuum-tuning: 🟢 متاح"
            if _AUTOTUNE_AVAILABLE else
            "⚙️ autovacuum-tuning: 🔴 غير متاح "
            f"<i>(يتطلب v7.2.24+، الحالي: "
            f"{_html_mod.escape(str(_DB_DIAG_VERSION_AT))})</i>"
        )

        text = (
            "📊 <b>التحليلات المتقدمة</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ DB: <code>{db_type}</code>\n"
            f"✅ AnalyticsMixin: مُحمَّل\n"
            f"{autotune_line}\n"
            f"{cache_info}\n"
            f"🕐 <i>{TimeUtils.mecca_iso()[:19]}</i>"
        )

        if query:
            await _safe_edit(query, text, keyboard)
        elif chat_id is not None:
            await safe_send(
                context.bot, chat_id, text,
                reply_markup=keyboard, parse_mode="HTML",
            )
    except Exception as e:
        logger.error("show_analytics_menu: %s", e, exc_info=True)


# ═══════════════════════════════════════════════════════════════════════
# 2) نمو المستخدمين
# ═══════════════════════════════════════════════════════════════════════

async def show_growth_30d(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الحساب...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    force_refresh = False

    try:
        if not hasattr(DB, "get_user_growth"):
            raise AttributeError("DB.get_user_growth غير موجود")

        async def _fetch_current():
            return await DB.get_user_growth(days=30)

        async def _fetch_prev():
            full = await DB.get_user_growth(days=60)
            return full[:30] if len(full) > 30 else []

        rows = await _cached_db_call(
            "growth_30d_current",
            _fetch_current,
            ttl=60.0,
            force_refresh=force_refresh,
        )
        rows = rows or []

        prev_rows = []
        try:
            prev_rows = await _cached_db_call(
                "growth_30d_prev",
                _fetch_prev,
                ttl=300.0,
                force_refresh=force_refresh,
            )
            prev_rows = prev_rows or []
        except Exception as _pe:
            logger.debug(f"prev_rows failed: {_pe}")

        total_count = sum(r.get("count", 0) for r in rows)
        n_days = len(rows) if rows else 30
        avg = round(total_count / n_days, 1) if n_days > 0 else 0.0
        max_count = max((r.get("count", 0) for r in rows), default=0)

        prev_total = sum(r.get("count", 0) for r in prev_rows)
        delta_line = ""
        if prev_total > 0:
            delta_pct = (total_count - prev_total) / prev_total * 100
            arrow = _growth_arrow(delta_pct)
            delta_line = (
                f"{arrow} <b>التغيير:</b> {delta_pct:+.1f}% "
                f"<i>({prev_total} → {total_count})</i>"
            )
        elif prev_rows:
            delta_line = "↗️ <i>لا توجد بيانات كافية للمقارنة</i>"

        lines = [
            "📈 <b>نمو المستخدمين — 30 يوم</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📊 الإجمالي: <b>{_fmt_num(total_count)}</b>",
            f"📅 المتوسط اليومي: <b>{avg}</b>",
            f"🏔️ الذروة: <b>{_fmt_num(max_count)}</b>",
        ]
        if delta_line:
            lines.append(delta_line)
        lines.append("")

        if rows:
            lines.append("<b>آخر 10 أيام:</b>")
            for r in rows[-10:]:
                day = _html_mod.escape(str(r.get("date", "?"))[-5:])
                cnt = r.get("count", 0)
                bar = _bar(cnt, max_count or 1, width=8)
                lines.append(f"  <code>{day}</code> {bar} <b>{cnt}</b>")
        else:
            lines.append("<i>📭 لا توجد بيانات</i>")

        text = "\n".join(lines)
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="growth_30d_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_growth_30d: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل نمو المستخدمين</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 3) أفضل 10 قنوات
# ═══════════════════════════════════════════════════════════════════════

async def show_top_channels(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الحساب...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_top_channels"):
            raise AttributeError("DB.get_top_channels غير موجود")

        rows = await _cached_db_call(
            "top_channels_10",
            lambda: DB.get_top_channels(limit=10),
            ttl=60.0,
            force_refresh=False,
        )
        rows = rows or []

        lines = [
            "🏆 <b>أفضل 10 قنوات</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        if not rows:
            lines.append("<i>📭 لا توجد قنوات مسجّلة بعد.</i>")
        else:
            medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
            for i, r in enumerate(rows):
                name = _html_mod.escape((r.get("name") or "—")[:28])
                published = int(r.get("published") or 0)
                total = int(r.get("total") or 0)
                rate = r.get("success_rate", 0)
                lines.append(
                    f"{medals[i]} <b>{name}</b>\n"
                    f"   📤 {published}/{total} "
                    f"({rate}% نجاح)"
                )

        text = "\n".join(lines)
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="top_channels_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_top_channels: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل أفضل القنوات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 4) إحصائيات النشر
# ═══════════════════════════════════════════════════════════════════════

async def show_publish_stats(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الحساب...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_publish_stats"):
            raise AttributeError("DB.get_publish_stats غير موجود")

        stats = await _cached_db_call(
            "publish_stats",
            lambda: DB.get_publish_stats(),
            ttl=60.0,
            force_refresh=False,
        )
        stats = stats or {}

        total_ch = int(stats.get("total_channels") or 0)
        total_po = int(stats.get("total_posts") or 0)
        pub = int(stats.get("published") or 0)
        failed = int(stats.get("failed") or 0)
        pending = int(stats.get("pending") or 0)
        avg_posts = stats.get("avg_posts_per_channel", 0)
        avg_pub = stats.get("avg_published_per_channel", 0)
        succ = stats.get("success_rate", 0)
        comp = stats.get("completion_rate", 0)

        text = (
            "📊 <b>إحصائيات النشر</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📡 عدد القنوات: <b>{_fmt_num(total_ch)}</b>\n"
            f"📥 إجمالي المنشورات: <b>{_fmt_num(total_po)}</b>\n"
            f"✅ نُشرت: <b>{_fmt_num(pub)}</b>\n"
            f"❌ فشلت: <b>{_fmt_num(failed)}</b>\n"
            f"⏳ منتظرة: <b>{_fmt_num(pending)}</b>\n\n"
            f"📈 متوسط لكل قناة: <b>{avg_posts}</b>\n"
            f"📤 متوسط المنشور: <b>{avg_pub}</b>\n\n"
            f"🎯 نسبة النجاح: <b>{succ}%</b>\n"
            f"🏁 نسبة الإنجاز: <b>{comp}%</b>"
        )
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="publish_stats_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_publish_stats: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل إحصائيات النشر</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 5) نسبة النجاح
# ═══════════════════════════════════════════════════════════════════════

async def show_channels_rate(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الحساب...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_channel_success_rate"):
            raise AttributeError("DB.get_channel_success_rate غير موجود")

        rows = await _cached_db_call(
            "channels_rate_20",
            lambda: DB.get_channel_success_rate(
                limit=20, filter_min_attempts=3),
            ttl=60.0,
            force_refresh=False,
        )
        rows = rows or []

        lines = [
            "🎯 <b>نسبة النجاح</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "<i>الأقل نجاحاً أولاً (≥ 3 محاولات)</i>",
            "",
        ]

        if not rows:
            lines.append("<i>📭 لا توجد بيانات كافية بعد.</i>")
        else:
            rows = sorted(rows, key=lambda x: x.get("success_rate", 100))
            for r in rows[:15]:
                name = _html_mod.escape((r.get("name") or "—")[:24])
                rate = r.get("success_rate", 0)
                att = int(r.get("attempted") or 0)
                color = ("🟢" if rate >= 80
                         else ("🟡" if rate >= 50 else "🔴"))
                bar = _bar(rate, 100, width=10)
                lines.append(
                    f"{color} <b>{name}</b>\n"
                    f"   {bar} <b>{rate}%</b> ({att} محاولة)"
                )

        text = "\n".join(lines)
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="channels_rate_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_channels_rate: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل نسبة النجاح</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 6) الاشتراكات
# ═══════════════════════════════════════════════════════════════════════

async def show_subscriptions(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الحساب...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_subscription_rate"):
            raise AttributeError("DB.get_subscription_rate غير موجود")

        rows = await _cached_db_call(
            "subscriptions_6m",
            lambda: DB.get_subscription_rate(months=6),
            ttl=120.0,
            force_refresh=False,
        )
        rows = rows or []

        total = sum(r.get("count", 0) for r in rows)
        max_c = max((r.get("count", 0) for r in rows), default=0)

        lines = [
            "💎 <b>الاشتراكات — 6 أشهر</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📊 الإجمالي: <b>{_fmt_num(total)}</b>",
            "",
        ]

        if rows:
            for r in rows:
                month = _html_mod.escape(str(r.get("month", "?")))
                cnt = r.get("count", 0)
                bar = _bar(cnt, max_c or 1, width=10)
                lines.append(f"  <code>{month}</code> {bar} <b>{cnt}</b>")
        else:
            lines.append("<i>📭 لا توجد اشتراكات بعد.</i>")

        text = "\n".join(lines)
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="subscriptions_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_subscriptions: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل الاشتراكات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 7) Pool مباشر
# ═══════════════════════════════════════════════════════════════════════

async def show_pool_live(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الفحص...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_pool_live"):
            raise AttributeError("DB.get_pool_live غير موجود")

        pool = await DB.get_pool_live() or {}

        if not pool.get("available"):
            reason = _html_mod.escape(str(pool.get("type", "unknown")))
            await _safe_edit(
                query,
                f"⚠️ Pool غير متاح: <code>{reason}</code>",
                _back_keyboard("admin_analytics"),
            )
            return

        util = pool.get("utilization_pct", 0)
        color = "🟢" if util < 50 else ("🟡" if util < 80 else "🔴")
        bar = _bar(util, 100, width=15)

        lines = [
            "🚀 <b>Pool مباشر</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"{color} الاستخدام: <b>{util}%</b>",
            f"<code>{bar}</code>",
            "",
            f"📊 الحجم: <b>{pool.get('in_use', 0)}/{pool.get('max_size', 0)}</b>",
            f"🆓 فاضي: <b>{pool.get('idle_size', 0)}</b>",
            f"🔗 مفتوح: <b>{pool.get('current_size', 0)}</b>",
        ]

        if "rollback_timeout" in pool:
            lines.append(
                f"\n⏱️ rollback timeout: "
                f"<b>{pool['rollback_timeout']}s</b>")
        if "idle_tx_audit_active" in pool:
            active = pool["idle_tx_audit_active"]
            icon = "✅" if active else "❌"
            lines.append(
                f"{icon} رصد idle-tx: "
                f"<b>{'نشط' if active else 'معطّل'}</b>")
        if "idle_tx_last_count" in pool:
            cnt = pool["idle_tx_last_count"]
            ic = "🟢" if cnt == 0 else ("🟠" if cnt < 3 else "🔴")
            lines.append(f"{ic} idle-tx آخر قراءة: <b>{cnt}</b>")

        lines.append(f"\n🕐 <i>{TimeUtils.mecca_iso()[:19]}</i>")

        text = "\n".join(lines)
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="pool_live_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_pool_live: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل Pool</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 8) أبطأ الاستعلامات
# ═══════════════════════════════════════════════════════════════════════

async def show_slow_queries(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الفحص...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_slowest_queries"):
            raise AttributeError("DB.get_slowest_queries غير موجود")

        rows = await _cached_db_call(
            "slow_queries_15",
            lambda: DB.get_slowest_queries(limit=15),
            ttl=30.0,
            force_refresh=False,
        )
        rows = rows or []

        lines = [
            "🐌 <b>أبطأ الاستعلامات</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        if not rows:
            lines.append(
                "<i>📭 لا توجد استعلامات بطيئة مسجّلة.</i>\n\n"
                "💡 تظهر هنا الاستعلامات التي تتجاوز العتبة."
            )
        else:
            for i, r in enumerate(rows[:10], 1):
                q_raw = (r.get("query") or r.get("sql") or "?")[:80]
                elapsed = r.get("elapsed", 0)
                q = _html_mod.escape(q_raw)
                lines.append(
                    f"{i}. <code>{q}</code>\n"
                    f"   ⏱️ <b>{_fmt_elapsed(elapsed)}</b>"
                )
                caller_file = r.get("caller_file")
                caller_line = r.get("caller_line")
                if caller_file or caller_line is not None:
                    loc = _html_mod.escape(
                        f"{caller_file or '?'}:{caller_line or '?'}"
                    )[:80]
                    lines.append(f"   📍 <code>{loc}</code>")
                ts = r.get("time") or r.get("created_at")
                if ts:
                    try:
                        if isinstance(ts, (int, float)):
                            ts_str = datetime.fromtimestamp(
                                float(ts)
                            ).strftime("%m-%d %H:%M")
                        else:
                            ts_str = str(ts)[:16]
                        lines.append(
                            f"   🕐 <i>{_html_mod.escape(ts_str)}</i>"
                        )
                    except Exception:
                        pass
                lines.append("")

        text = "\n".join(lines)
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="slow_queries_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_slow_queries: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل أبطأ الاستعلامات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 9) تصدير Excel
# ═══════════════════════════════════════════════════════════════════════

async def export_excel(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري التصدير...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    if query is None or getattr(query, 'message', None) is None:
        if chat_id is not None:
            await safe_send(
                context.bot, chat_id,
                "❌ هذا الزر يعمل من داخل القائمة فقط.")
        return

    try:
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            await query.answer(
                "❌ مكتبة openpyxl غير مُثبّتة.\n"
                "ثبّتها: pip install openpyxl",
                show_alert=True,
            )
            return

        import openpyxl
        wb = openpyxl.Workbook()

        ws1 = wb.active
        ws1.title = "User Growth"
        ws1.append(["Date", "Count"])
        rows1 = await _cached_db_call(
            "export_growth_30d",
            lambda: DB.get_user_growth(days=30),
            ttl=60.0,
            force_refresh=False,
        ) or []
        for r in rows1:
            ws1.append([r.get("date"), r.get("count")])

        ws2 = wb.create_sheet("Top Channels")
        ws2.append([
            "Name", "Channel ID", "Total", "Published",
            "Failed", "Success %", "Completion %",
        ])
        rows2 = await _cached_db_call(
            "export_top_channels_50",
            lambda: DB.get_top_channels(limit=50),
            ttl=60.0,
            force_refresh=False,
        ) or []
        for r in rows2:
            ws2.append([
                r.get("name"), r.get("channel_id"),
                r.get("total"), r.get("published"),
                r.get("failed"), r.get("success_rate"),
                r.get("completion_rate"),
            ])

        ws3 = wb.create_sheet("Publish Stats")
        stats = await _cached_db_call(
            "export_publish_stats",
            lambda: DB.get_publish_stats(),
            ttl=60.0,
            force_refresh=False,
        ) or {}
        ws3.append(["Metric", "Value"])
        for k, v in stats.items():
            ws3.append([k, v])

        ws4 = wb.create_sheet("Subscriptions")
        ws4.append(["Month", "Count"])
        rows4 = await _cached_db_call(
            "export_subscriptions_12m",
            lambda: DB.get_subscription_rate(months=12),
            ttl=120.0,
            force_refresh=False,
        ) or []
        for r in rows4:
            ws4.append([r.get("month"), r.get("count")])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        MAX_BYTES = 20 * 1024 * 1024
        size_bytes = buf.getbuffer().nbytes
        if size_bytes > MAX_BYTES:
            logger.warning(
                "export_excel: الملف %d bytes > %d",
                size_bytes, MAX_BYTES,
            )
            await _safe_edit(
                query,
                f"❌ <b>الملف كبير جداً</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💾 الحجم: <b>{size_bytes / (1024*1024):.1f}MB</b>\n"
                f"الحد: 20MB",
                _back_keyboard("admin_analytics"),
            )
            return

        filename = (
            f"analytics_"
            f"{TimeUtils.utc_now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )

        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=buf,
            filename=filename,
            caption=(
                f"📤 <b>تصدير التحليلات</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 4 أوراق\n"
                f"💾 الحجم: <b>{size_bytes / 1024:.1f} KB</b>"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("export_excel: %s", e, exc_info=True)
        err_html = _err_detail(e)
        try:
            await _safe_edit(
                query,
                f"❌ <b>فشل تصدير Excel</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
                _back_keyboard("admin_analytics"),
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# 10) التشخيص الشامل
# ═══════════════════════════════════════════════════════════════════════

async def show_full_health(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)

    await _quick_answer(query, "⏳ جاري التشخيص... (5-10s)")

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    if chat_id is None:
        return

    waiting_text = (
        "🏥 <b>التشخيص الشامل جارٍ...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔬 يقيس 6 أبعاد:\n"
        "  🌐 الشبكة → DB\n"
        "  📨 الشبكة → Telegram\n"
        "  🗄️ DB Internal\n"
        "  🔄 Event Loop\n"
        "  💾 القرص\n"
        "  ⚙️ CPU/RAM\n\n"
        "⏳ يرجى الانتظار 5-10 ثواني..."
    )

    waiting_msg = None
    if query:
        try:
            await _safe_edit(query, waiting_text, None)
        except Exception as e:
            logger.debug(f"show_full_health waiting (edit): {e}")
    else:
        try:
            waiting_msg = await context.bot.send_message(
                chat_id, waiting_text, parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"show_full_health waiting (send): {e}")

    async def _cleanup_waiting(success: bool = False):
        if waiting_msg is None:
            return
        try:
            if success:
                await waiting_msg.edit_text(
                    "✅ <b>التقرير جاهز 👇</b>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            else:
                await waiting_msg.delete()
        except Exception as e:
            logger.debug(f"_cleanup_waiting: {e}")

    try:
        from db_diagnostics import diagnose_full
    except Exception as ie:
        err = (
            "❌ <b>db_diagnostics غير متاح</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<code>{_html_mod.escape(str(ie)[:300])}</code>\n\n"
            "💡 تأكد من وجود <code>diagnose_full</code> في "
            "<code>db_diagnostics.py</code> v7.2.0+."
        )
        await _cleanup_waiting(success=False)
        if query:
            await _safe_edit(query, err, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err)
        return

    try:
        report = await diagnose_full(force=True)
        if not report:
            report = "⚠️ لا توجد بيانات."

        back_kb = _back_refresh_keyboard(
            target="admin_analytics",
            refresh="full_health_btn",
        )

        MAX_SINGLE = 3800
        if len(report) <= MAX_SINGLE and query:
            ok = await _safe_edit(query, report, back_kb)
            if ok:
                return
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )
        else:
            await _cleanup_waiting(success=True)
            if query:
                try:
                    await _safe_edit(
                        query,
                        "✅ <b>التقرير جاهز 👇</b>",
                        None,
                    )
                except Exception as e:
                    logger.debug(f"show_full_health after: {e}")
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )

    except Exception as e:
        logger.error("show_full_health: %s", e, exc_info=True)
        await _cleanup_waiting(success=False)
        err_html = _err_detail(e)
        err_text = (
            f"❌ <b>فشل التشخيص الشامل</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}"
        )
        if query:
            await _safe_edit(
                query, err_text, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err_text)


# ═══════════════════════════════════════════════════════════════════════
# 11) اختبار الكمون
# ═══════════════════════════════════════════════════════════════════════

async def show_latency(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)

    await _quick_answer(query, "⏳ جاري اختبار الكمون...")

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    if chat_id is None:
        return

    waiting_text = (
        "🔬 <b>جاري اختبار الكمون...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⏳ 3-5 ثواني..."
    )

    waiting_msg = None
    if query:
        try:
            await _safe_edit(query, waiting_text, None)
        except Exception as e:
            logger.debug(f"show_latency waiting (edit): {e}")
    else:
        try:
            waiting_msg = await context.bot.send_message(
                chat_id, waiting_text, parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"show_latency waiting (send): {e}")

    async def _cleanup_waiting(success: bool = False):
        if waiting_msg is None:
            return
        try:
            if success:
                await waiting_msg.edit_text(
                    "✅ <b>التقرير جاهز 👇</b>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            else:
                await waiting_msg.delete()
        except Exception as e:
            logger.debug(f"_cleanup_waiting: {e}")

    try:
        from db_diagnostics import diagnose_latency
    except Exception as ie:
        err = (
            "❌ <b>db_diagnostics غير متاح</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<code>{_html_mod.escape(str(ie)[:300])}</code>\n\n"
            "💡 تأكد من وجود <code>diagnose_latency</code> في "
            "<code>db_diagnostics.py</code> v7.1.0+."
        )
        await _cleanup_waiting(success=False)
        if query:
            await _safe_edit(query, err, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err)
        return

    try:
        report = await diagnose_latency(force=True)
        if not report:
            report = "⚠️ لا توجد بيانات."

        back_kb = _back_refresh_keyboard(
            target="admin_analytics",
            refresh="latency_btn",
        )

        MAX_SINGLE = 3800
        if len(report) <= MAX_SINGLE and query:
            ok = await _safe_edit(query, report, back_kb)
            if ok:
                return
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )
        else:
            await _cleanup_waiting(success=True)
            if query:
                try:
                    await _safe_edit(
                        query,
                        "✅ <b>التقرير جاهز 👇</b>",
                        None,
                    )
                except Exception as e:
                    logger.debug(f"show_latency after: {e}")
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )

    except Exception as e:
        logger.error("show_latency: %s", e, exc_info=True)
        await _cleanup_waiting(success=False)
        err_html = _err_detail(e)
        err_text = (
            f"❌ <b>فشل اختبار الكمون</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}"
        )
        if query:
            await _safe_edit(
                query, err_text, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err_text)


# ═══════════════════════════════════════════════════════════════════════
# 12) Multi-DB Discovery
# ═══════════════════════════════════════════════════════════════════════

async def show_databases(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """🗂️ تقرير قواعد البيانات المُعدّة + النشطة."""
    query = update.callback_query
    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)

    await _quick_answer(query, "⏳ جاري الفحص...")

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    if chat_id is None:
        return

    try:
        from db_diagnostics import diagnose_databases
    except Exception as ie:
        err = (
            "❌ <b>db_diagnostics غير متاح</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<code>{_html_mod.escape(str(ie)[:300])}</code>\n\n"
            "💡 تأكد من وجود <code>diagnose_databases</code> في "
            "<code>db_diagnostics.py</code> v7.2.13+."
        )
        if query:
            await _safe_edit(query, err, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err)
        return

    try:
        report = await diagnose_databases()
        if not report:
            report = "⚠️ لا توجد بيانات."

        back_kb = _back_refresh_keyboard(
            target="admin_analytics",
            refresh="databases_btn",
        )

        MAX_SINGLE = 3800
        if len(report) <= MAX_SINGLE and query:
            ok = await _safe_edit(query, report, back_kb)
            if ok:
                return
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )
        else:
            if query:
                try:
                    await _safe_edit(
                        query,
                        "✅ <b>التقرير جاهز 👇</b>",
                        None,
                    )
                except Exception as e:
                    logger.debug(f"show_databases after: {e}")
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )

    except Exception as e:
        logger.error("show_databases: %s", e, exc_info=True)
        err_html = _err_detail(e)
        err_text = (
            f"❌ <b>فشل قواعد البيانات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}"
        )
        if query:
            await _safe_edit(
                query, err_text, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err_text)


# ═══════════════════════════════════════════════════════════════════════
# 🆕 v1.3.3 — 12b) ضبط autovacuum (db_diagnostics v7.2.24+)
# ═══════════════════════════════════════════════════════════════════════

async def show_autotune(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """⚙️ ضبط autovacuum تلقائي — تقرير + تنفيذ فوري."""
    query = update.callback_query
    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)

    await _quick_answer(query, "⏳ جاري الضبط...")

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    if chat_id is None:
        return

    # فحص التوفّر
    if not _AUTOTUNE_AVAILABLE or _diagnose_autovacuum_tuning_fn is None:
        err = (
            "⚙️ <b>ضبط autovacuum — غير متاح</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ يتطلب <code>db_diagnostics ≥ v7.2.24</code>\n"
            f"📦 الحالي: <code>{_html_mod.escape(str(_DB_DIAG_VERSION_AT))}</code>\n"
        )
        if _AUTOTUNE_IMPORT_ERROR:
            err += (
                f"\n<b>سبب الاستيراد:</b>\n"
                f"<code>{_html_mod.escape(_AUTOTUNE_IMPORT_ERROR[:200])}</code>\n"
            )
        err += (
            "\n💡 <b>الحل:</b> ارفع <code>db_diagnostics.py</code> "
            "إلى v7.2.24+ (يحتوي على ensure_autovacuum_tuning)."
        )
        kb = _back_keyboard("admin_analytics")
        if query:
            await _safe_edit(query, err, kb)
        else:
            await safe_send(context.bot, chat_id, err, reply_markup=kb)
        return

    # فحص PG
    try:
        if not bool(getattr(DB, "USE_POSTGRES", False)):
            err = (
                "⚠️ <b>الضبط التلقائي يتطلب PostgreSQL</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"النوع الحالي: "
                f"<code>{_html_mod.escape(str(getattr(DB, 'DB_TYPE', '?')).upper())}</code>"
            )
            kb = _back_keyboard("admin_analytics")
            if query:
                await _safe_edit(query, err, kb)
            else:
                await safe_send(context.bot, chat_id, err, reply_markup=kb)
            return
    except Exception:
        pass

    waiting_text = (
        "⚙️ <b>جاري ضبط autovacuum...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔍 فحص reloptions الحالية + اكتشاف الجداول عالية الـ churn\n"
        "⏳ 2-5 ثواني..."
    )

    waiting_msg = None
    if query:
        try:
            await _safe_edit(query, waiting_text, None)
        except Exception as e:
            logger.debug(f"show_autotune waiting (edit): {e}")
    else:
        try:
            waiting_msg = await context.bot.send_message(
                chat_id, waiting_text, parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"show_autotune waiting (send): {e}")

    async def _cleanup_waiting(success: bool = False):
        if waiting_msg is None:
            return
        try:
            if success:
                await waiting_msg.edit_text(
                    "✅ <b>التقرير جاهز 👇</b>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            else:
                await waiting_msg.delete()
        except Exception as e:
            logger.debug(f"_cleanup_waiting: {e}")

    try:
        report = await _diagnose_autovacuum_tuning_fn(force=True)
        if not report:
            report = "⚠️ لا توجد بيانات."

        back_kb = _back_refresh_keyboard(
            target="admin_analytics",
            refresh="autotune_btn",
        )

        MAX_SINGLE = 3800
        if len(report) <= MAX_SINGLE and query:
            ok = await _safe_edit(query, report, back_kb)
            if ok:
                return
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )
        else:
            await _cleanup_waiting(success=True)
            if query:
                try:
                    await _safe_edit(
                        query,
                        "✅ <b>التقرير جاهز 👇</b>",
                        None,
                    )
                except Exception as e:
                    logger.debug(f"show_autotune after: {e}")
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )

    except Exception as e:
        logger.error("show_autotune: %s", e, exc_info=True)
        await _cleanup_waiting(success=False)
        err_html = _err_detail(e)
        err_text = (
            f"❌ <b>فشل ضبط autovacuum</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}"
        )
        if query:
            await _safe_edit(
                query, err_text, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err_text)


# ═══════════════════════════════════════════════════════════════════════
# 13) /versions
# ═══════════════════════════════════════════════════════════════════════

async def cmd_versions(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = _get_safe_user_id(update)
    chat_id = _safe_get_chat_id(update, None)
    query = update.callback_query

    if query:
        await _quick_answer(query)

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    modules_to_check = [
        ("bot.py", "bot"),
        ("config.py", "config"),
        ("database.py", "database"),
        ("db_diagnostics.py", "db_diagnostics"),
        ("database_groups.py", "database_groups"),
        ("database_channels_posts.py", "database_channels_posts"),
        ("database_subscriptions.py", "database_subscriptions"),
        ("db_maintenance_commands.py", "db_maintenance_commands"),
        ("handlers_message.py", "handlers.handlers_message"),
        ("handlers_command.py", "handlers.handlers_command"),
        ("handlers_callback.py", "handlers_callback"),
        ("handlers_analytics.py", "handlers_analytics"),
        ("handlers_channels_list.py", "handlers_channels_list"),
        ("handlers_membership.py", "handlers_membership"),
        ("handlers_group_log.py", "handlers.handlers_group_log"),
        ("handlers_message_detectors.py", "handlers_message_detectors"),
        ("cache.py", "cache"),
        ("utils.py", "utils"),
        ("sleep_probe.py", "sleep_probe"),
    ]

    lines = [
        "📦 <b>الإصدارات الحالية</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    loaded = 0
    missing = 0
    for name, mod_path in modules_to_check:
        try:
            mod = importlib.import_module(mod_path)
            ver = (
                getattr(mod, "VERSION", None)
                or getattr(mod, "__version__", None)
                or getattr(mod, "_VERSION", None)
                or "?"
            )
            if ver == "?":
                doc = getattr(mod, "__doc__", "") or ""
                m = _re_mod.search(r"v?(\d+\.\d+\.\d+)", doc[:500])
                if m:
                    ver = m.group(1)
            icon = "✅" if ver != "?" else "🟡"
            lines.append(f"{icon} <code>{name}</code>: v{ver}")
            loaded += 1
        except ImportError:
            lines.append(f"❌ <code>{name}</code>: <i>غير محمّل</i>")
            missing += 1
        except Exception as e:
            lines.append(f"⚠️ <code>{name}</code>: <i>{type(e).__name__}</i>")
            missing += 1

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 محمّل: <b>{loaded}</b> | مفقود: <b>{missing}</b>")

    cache_stats = _get_cache_stats()
    lines.append(
        f"💾 cache: <b>{cache_stats['total_keys']}</b>"
        f"/{cache_stats['max_entries']}"
    )

    # 🆕 v1.3.3 — مؤشر الضبط
    lines.append(
        "⚙️ autotune: " + (
            "🟢 متاح" if _AUTOTUNE_AVAILABLE else
            f"🔴 غير متاح <i>(db_diagnostics={_html_mod.escape(str(_DB_DIAG_VERSION_AT))})</i>"
        )
    )

    lines.append(f"🕐 <i>{TimeUtils.mecca_iso()[:19]}</i>")

    text = "\n".join(lines)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔄 تحديث",
            callback_data="versions_refresh",
        )],
        [InlineKeyboardButton(
            "💾 إبطال cache",
            callback_data="analytics_reset_cache",
        )],
        [InlineKeyboardButton(
            "🔙 رجوع",
            callback_data="admin",
        )],
    ])

    if query:
        await _safe_edit(query, text, kb)
    elif chat_id is not None:
        await safe_send(
            context.bot, chat_id, text,
            reply_markup=kb, parse_mode="HTML",
        )


# ═══════════════════════════════════════════════════════════════════════
# 14) /analytics_reset
# ═══════════════════════════════════════════════════════════════════════

async def cmd_analytics_reset(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = _get_safe_user_id(update)
    chat_id = _safe_get_chat_id(update, None)
    query = update.callback_query

    if query:
        await _quick_answer(query, "🗑️ جاري الإبطال...")

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    removed = _invalidate_analytics_cache()

    text = (
        f"✅ <b>تم إبطال cache التحليلات</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🗑️ محذوف: <b>{removed}</b> مفتاح\n"
        f"💾 حجم الحالي: <b>0</b>\n\n"
        f"<i>ستُقرأ البيانات من DB في الطلب التالي.</i>"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📊 التحليلات",
            callback_data="admin_analytics",
        )],
        [InlineKeyboardButton(
            "📦 الإصدارات",
            callback_data="versions_refresh",
        )],
    ])

    if query:
        await _safe_edit(query, text, kb)
    elif chat_id is not None:
        await safe_send(
            context.bot, chat_id, text,
            reply_markup=kb, parse_mode="HTML",
        )

    logger.info(
        "🗑️ analytics cache invalidated by user=%s (removed=%d)",
        user_id, removed,
    )


# ═══════════════════════════════════════════════════════════════════════
# 15) التوجيه المركزي
# ═══════════════════════════════════════════════════════════════════════

_ANALYTICS_HANDLERS = {
    "admin_analytics": show_analytics_menu,
    "growth_30d_btn": show_growth_30d,
    "top_channels_btn": show_top_channels,
    "publish_stats_btn": show_publish_stats,
    "channels_rate_btn": show_channels_rate,
    "subscriptions_btn": show_subscriptions,
    "pool_live_btn": show_pool_live,
    "slow_queries_btn": show_slow_queries,
    "export_excel_btn": export_excel,
    "full_health_btn": show_full_health,
    "latency_btn": show_latency,
    "databases_btn": show_databases,
    "autotune_btn": show_autotune,       # 🆕 v1.3.3
}


async def handle_analytics_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query:
        return

    data = (query.data or "").split(":")[0]

    if data == "versions_refresh":
        await cmd_versions(update, context)
        return
    if data == "analytics_reset_cache":
        await cmd_analytics_reset(update, context)
        return

    if data not in ANALYTICS_BUTTONS:
        return

    if data == "refresh_btn":
        last = context.user_data.get(
            "last_analytics_btn", "admin_analytics")
        data = last
        _invalidate_analytics_cache()
    else:
        context.user_data["last_analytics_btn"] = data

    handler = _ANALYTICS_HANDLERS.get(data)
    if handler is None:
        try:
            await query.answer("⚠️ غير مدعوم")
        except Exception:
            pass
        return

    try:
        await handler(update, context)
    except Exception as e:
        logger.error(
            "handle_analytics_callback[%s]: %s", data, e, exc_info=True)
        err_html = _err_detail(e)
        try:
            await _safe_edit(
                query,
                f"❌ <b>خطأ في {_html_mod.escape(data)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
                _back_keyboard("admin_analytics"),
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# 16) /analytics + أوامر مباشرة
# ═══════════════════════════════════════════════════════════════════════

async def cmd_analytics(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    v1.3.2 CLEAN-2: نُفوّض التحقق الكامل إلى show_analytics_menu
    (التي تفحص _check_developer بنفسها) — لتفادي التنفيذ المزدوج.
    """
    await show_analytics_menu(update, context)


async def cmd_fullhealth(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_full_health(update, context)


async def cmd_latency(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_latency(update, context)


async def cmd_databases(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """🗂️ v1.3.1: أمر مباشر لقواعد البيانات."""
    await show_databases(update, context)


async def cmd_autotune(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    """⚙️ v1.3.3: أمر مباشر لضبط autovacuum."""
    await show_autotune(update, context)


# ═══════════════════════════════════════════════════════════════════════
# 17) التسجيل
# ═══════════════════════════════════════════════════════════════════════

def register_handlers(application) -> bool:
    """
    v1.3.3: يُسجّل كل الـ handlers (buttons + commands).

    يُستدعى من bot.py v5.6.32+ ضمن [ORDER 5/6].
    في حال نجاحه، لا حاجة للتسجيل اليدوي في bot.py.

    Returns:
        True إن نجح التسجيل (كل الأوامر)، False إن فشل.
    """
    try:
        _safe_buttons = "|".join(
            _re_mod.escape(b) for b in ANALYTICS_BUTTONS
        )
        pattern = (
            r"^(?:" + _safe_buttons + r"|"
            r"versions_refresh|analytics_reset_cache"
            r")(?::\d+)?$"
        )
        application.add_handler(
            CallbackQueryHandler(
                handle_analytics_callback,
                pattern=pattern,
            )
        )
        application.add_handler(
            CommandHandler("analytics", cmd_analytics)
        )
        application.add_handler(
            CommandHandler("fullhealth", cmd_fullhealth)
        )
        application.add_handler(
            CommandHandler("latency", cmd_latency)
        )
        application.add_handler(
            CommandHandler("versions", cmd_versions)
        )
        application.add_handler(
            CommandHandler("analytics_reset", cmd_analytics_reset)
        )
        application.add_handler(
            CommandHandler("databases", cmd_databases)
        )
        application.add_handler(
            CommandHandler("autotune", cmd_autotune)
        )

        cmds = (
            "analytics, fullhealth, latency, versions, "
            "analytics_reset, databases, autotune"
        )
        logger.info(
            "✅ handlers_analytics v1.3.3: %d زر + 7 أوامر (%s)",
            len(ANALYTICS_BUTTONS),
            cmds,
        )
        return True
    except Exception as e:
        logger.error(
            f"❌ handlers_analytics.register_handlers: "
            f"{type(e).__name__}: {e}",
            exc_info=True,
        )
        return False


register = register_handlers


__all__ = [
    "ANALYTICS_BUTTONS",
    "show_analytics_menu",
    "handle_analytics_callback",
    "show_growth_30d",
    "show_top_channels",
    "show_publish_stats",
    "show_channels_rate",
    "show_subscriptions",
    "show_pool_live",
    "show_slow_queries",
    "export_excel",
    "show_full_health",
    "show_latency",
    "show_databases",
    "show_autotune",            # 🆕 v1.3.3
    "cmd_analytics",
    "cmd_fullhealth",
    "cmd_latency",
    "cmd_versions",
    "cmd_analytics_reset",
    "cmd_databases",
    "cmd_autotune",             # 🆕 v1.3.3
    "register_handlers",
    "register",
    "_cached_db_call",
    "_invalidate_analytics_cache",
    "_get_cache_stats",
    "_quick_answer",
]


# ═══════════════════════════════════════════════════════════════════════
# LOAD BEACON — v1.3.3
# ═══════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "✅ handlers_analytics v1.3.3 loaded | "
        "buttons=%d | "
        "AUTO-1=autotune-btn | "
        "AUTO-2=/autotune | "
        "AUTO-3=safe-fallback | "
        "AUTO-4=btn-always-visible | "
        "AUTO-5=buttons-tuple | "
        "AUTO-6=exports | "
        "autotune_available=%s | "
        "db_diag_version=%s | "
        "CLEAN-1=regex-escape | "
        "CLEAN-2=cmd-analytics-no-double-check | "
        "INTEGRATION=bot.py-v5.6.32-register-handlers | "
        "FIX-1=force-refresh-false | "
        "NEW-1=/databases | "
        "NEW-2=databases-btn | "
        "NEW-3=show-databases | "
        "PERF-1=db-cache(ttl=%.0fs,max=%d) | "
        "PERF-2=quick-answer | "
        "FEAT-1=growth-comparison | "
        "FEAT-2=/versions | "
        "FEAT-3=/analytics_reset | "
        "KEPT: HA1..HA31",
        len(ANALYTICS_BUTTONS),
        _AUTOTUNE_AVAILABLE,
        _DB_DIAG_VERSION_AT,
        _DB_CACHE_TTL_DEFAULT,
        _DB_CACHE_MAX_ENTRIES,
    )
except Exception:
    pass