#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_analytics.py — واجهة التحليلات المتقدمة (v1.2.3 — WAITING-MSG + ROBUSTNESS-FIX)
================================================================================
v1.2.3: رسائل الانتظار + تحسينات المتانة
    🔴 FIX-HA15: show_full_health / show_latency — عند الاستدعاء من
        CommandHandler، كانت رسالة "waiting" تبقى معلّقة للأبد.
        الإصلاح: الاحتفاظ بـ Message object وتحديثه إلى "✅ التقرير جاهز".
    🔴 FIX-HA16: show_analytics_menu / show_growth_30d / ... —
        إضافة فحص update.effective_user قبل الوصول إلى .id.
        (نادر، لكن يحدث مع Updates معطوبة أو من قنوات).
    🟠 FIX-HA17: _safe_send_long — عند فشل chunk (plain fallback فشل
        أيضاً)، يتوقف عن المتابعة بدل الاستمرار مع صفحات مفقودة.
    🟠 FIX-HA18: _fmt_elapsed — يرفض inf / nan / negative.
    🟠 FIX-HA19: _check_developer — log.warning عند استثناء داخلي.
    🟠 FIX-HA20: show_growth_30d — القسمة على عدد الصفوف الفعلي.
    🟠 FIX-HA21: _safe_get_chat_id — fallback إلى query.from_user.id.
    🟡 FIX-HA23: _reject_non_dev — logger.warning بدل debug.
    🟡 FIX-HA24: show_slow_queries — عرض caller_file/caller_line/time.
    🟡 FIX-HA25: _fmt_num — None → "—" (تمييز عن 0).
    🟡 FIX-HA27: export_excel — فحص حجم buffer قبل send_document.
    🟡 FIX-HA31: _default_analytics_keyboard — محاولة الترجمة.

v1.2.2: تصلب fallbacks + إصلاح HTML escape ناقص (محفوظ).
v1.2.1: إصلاحات أمنية ووظيفية (محفوظة).
v1.2.0: تكامل التشخيص الشامل + اختبار الكمون (محفوظ).
v1.1.1: كشف تلقائي للفروقات (محفوظ).
================================================================================
"""

import logging
import re as _re_mod
import io
import html as _html_mod
import traceback as _tb
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

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
)


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


def _check_developer(user_id: Optional[int]) -> bool:
    """
    🆕 v1.2.3 FIX-HA19: log عند استثناء داخلي (بدل ابتلاع صامت).
    """
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
    """
    🆕 v1.2.3 FIX-HA16: استخراج user_id بأمان.
    """
    try:
        user = getattr(update, "effective_user", None)
        if user is None:
            return None
        uid = getattr(user, "id", None)
        return uid if uid is not None else None
    except Exception:
        return None


def _safe_get_chat_id(update: Update, query=None) -> Optional[int]:
    """
    🆕 v1.2.2 FIX-HA8: استخراج chat_id بأمان.
    🆕 v1.2.3 FIX-HA21: fallback إلى query.from_user.id.

    الأولوية:
      1. query.message.chat_id (لو callback)
      2. update.effective_chat.id
      3. query.from_user.id (في الخاص، chat_id == user_id)
      4. None
    """
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
    # 🆕 FIX-HA21: fallback
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
    """
    🆕 v1.2.1 FIX-HA2: رفض موحّد.
    🆕 v1.2.2 FIX-HA8: chat_id يمكن أن يكون None.
    🆕 v1.2.3 FIX-HA23: warning بدل debug على الفشل.
    """
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
    """🆕 v1.2.2 FIX-HA9/HA11: كشف أخطاء parse HTML."""
    low = (err_str or "").lower()
    return any(k in low for k in (
        "can't parse",
        "can't find end tag",
        "unsupported start tag",
        "unclosed tag",
        "invalid entity",
    ))


def _strip_html(text: str) -> str:
    """إزالة وسوم HTML — للعرض كـ plain."""
    if not text:
        return text
    try:
        import html as _h
        return _h.unescape(_re_mod.sub(r"<[^>]+>", "", text))
    except Exception:
        return text


async def _safe_edit(query, text: str, keyboard=None,
                     parse_mode: str = "HTML") -> bool:
    """
    🆕 v1.2.2:
      - FIX-HA9: HTML-strip fallback عند parse error
      - FIX-HA10: caption-fallback عند no-text
    """
    if query is None or getattr(query, 'message', None) is None:
        return False

    # محاولة 1: edit_message_text عادي
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
        # 🆕 FIX-HA9: parse error → plain
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
        # 🆕 FIX-HA10: caption-only message
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

    # 🆕 fallback: إرسال كرسالة جديدة
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
    """
    إرسال نص طويل مع تقسيم إلى 3800 حرف/رسالة.
    🆕 v1.2.2 FIX-HA11: plain fallback عند parse error.
    🆕 v1.2.3 FIX-HA17: يتوقف عند فشل chunk (بدل تفقّد صفحات).
        Returns: True إذا كل الصفحات أُرسلت بنجاح.
    """
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

    # تقسيم على حدود الأسطر قدر الإمكان
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
        # keyboard على آخر chunk فقط
        kb = reply_markup if i == total else None
        ok = await _send_one(chat_id, header + chunk, kb, parse_mode)
        if not ok:
            # 🆕 FIX-HA17: توقف فوري بدل متابعة مع صفحات ناقصة
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
    """🆕 v1.2.2 FIX-HA13: lang param."""
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
    """🆕 v1.2.2 FIX-HA13: lang param."""
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
    """
    🆕 v1.2.3 FIX-HA25: None → "—" (تمييز عن 0 الفعلي).
    """
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_elapsed(sec) -> str:
    """
    🆕 v1.2.3 FIX-HA18: يرفض inf / nan / negative.
    """
    try:
        s = float(sec)
    except (TypeError, ValueError):
        return "?"
    # رفض inf / nan / negative
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
    """
    استخراج تفاصيل كاملة للخطأ.
    🔴 v1.2.1 FIX-HA1: HTML escape.
    """
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
    return (
        f"<b>النوع:</b> <code>{safe_type}</code>\n"
        f"<b>الرسالة:</b> <code>{safe_msg}</code>\n"
        f"<b>الموقع:</b> <code>{safe_loc}</code>"
    )


def _default_analytics_keyboard(lang: str = "ar") -> InlineKeyboardMarkup:
    """
    🆕 v1.2.3 FIX-HA31: محاولة الترجمة، وإلا نصوص عربية افتراضية.
    """
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
            callback_data="full_health_btn")],
        [InlineKeyboardButton(
            _lbl("analytics_latency", "🔬 اختبار الكمون"),
            callback_data="latency_btn")],
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

        if query:
            try:
                await query.answer()
            except Exception:
                pass

        # 🆕 FIX-HA16
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

        text = (
            "📊 <b>التحليلات المتقدمة</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ DB: <code>{db_type}</code>\n"
            f"✅ AnalyticsMixin: مُحمَّل\n"
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
    try:
        if query:
            await query.answer("⏳ جاري الحساب...")
    except Exception:
        pass

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_user_growth"):
            raise AttributeError("DB.get_user_growth غير موجود")
        rows = await DB.get_user_growth(days=30)
        rows = rows or []

        total_count = sum(r.get("count", 0) for r in rows)
        # 🆕 FIX-HA20: قسمة على عدد الأيام الفعلي
        n_days = len(rows) if rows else 30
        avg = round(total_count / n_days, 1) if n_days > 0 else 0.0
        max_count = max((r.get("count", 0) for r in rows), default=0)

        lines = [
            "📈 <b>نمو المستخدمين — 30 يوم</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📊 الإجمالي: <b>{_fmt_num(total_count)}</b>",
            f"📅 المتوسط اليومي: <b>{avg}</b>",
            f"🏔️ الذروة: <b>{_fmt_num(max_count)}</b>",
            "",
        ]

        if rows:
            lines.append("<b>آخر 10 أيام:</b>")
            for r in rows[-10:]:
                # 🔴 v1.2.2 FIX-HA7: HTML escape
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
    try:
        if query:
            await query.answer("⏳ جاري الحساب...")
    except Exception:
        pass

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_top_channels"):
            raise AttributeError("DB.get_top_channels غير موجود")
        rows = await DB.get_top_channels(limit=10)
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
    try:
        if query:
            await query.answer("⏳ جاري الحساب...")
    except Exception:
        pass

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_publish_stats"):
            raise AttributeError("DB.get_publish_stats غير موجود")
        stats = await DB.get_publish_stats() or {}

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
    try:
        if query:
            await query.answer("⏳ جاري الحساب...")
    except Exception:
        pass

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_channel_success_rate"):
            raise AttributeError("DB.get_channel_success_rate غير موجود")
        rows = await DB.get_channel_success_rate(
            limit=20, filter_min_attempts=3,
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
    try:
        if query:
            await query.answer("⏳ جاري الحساب...")
    except Exception:
        pass

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_subscription_rate"):
            raise AttributeError("DB.get_subscription_rate غير موجود")
        rows = await DB.get_subscription_rate(months=6)
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
    try:
        if query:
            await query.answer("⏳ جاري الفحص...")
    except Exception:
        pass

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
    try:
        if query:
            await query.answer("⏳ جاري الفحص...")
    except Exception:
        pass

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_slowest_queries"):
            raise AttributeError("DB.get_slowest_queries غير موجود")
        rows = await DB.get_slowest_queries(limit=15)
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
                # 🆕 FIX-HA24: عرض caller/time إن توفر
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
                        # ts قد يكون unix timestamp أو string
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
    try:
        if query:
            await query.answer("⏳ جاري التصدير...")
    except Exception:
        pass

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    # 🆕 v1.2.2: تأكد أننا في سياق callback
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
        rows1 = await DB.get_user_growth(days=30) or []
        for r in rows1:
            ws1.append([r.get("date"), r.get("count")])

        ws2 = wb.create_sheet("Top Channels")
        ws2.append([
            "Name", "Channel ID", "Total", "Published",
            "Failed", "Success %", "Completion %",
        ])
        rows2 = await DB.get_top_channels(limit=50) or []
        for r in rows2:
            ws2.append([
                r.get("name"), r.get("channel_id"),
                r.get("total"), r.get("published"),
                r.get("failed"), r.get("success_rate"),
                r.get("completion_rate"),
            ])

        ws3 = wb.create_sheet("Publish Stats")
        stats = await DB.get_publish_stats() or {}
        ws3.append(["Metric", "Value"])
        for k, v in stats.items():
            ws3.append([k, v])

        ws4 = wb.create_sheet("Subscriptions")
        ws4.append(["Month", "Count"])
        rows4 = await DB.get_subscription_rate(months=12) or []
        for r in rows4:
            ws4.append([r.get("month"), r.get("count")])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        # 🆕 FIX-HA27: فحص الحجم قبل الإرسال
        # Telegram حد أقصى 50MB للمستندات.
        # نتوقع أن ملفنا صغير جداً، لكن نضع حد 20MB كأمان.
        MAX_BYTES = 20 * 1024 * 1024  # 20MB
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
                "📤 <b>تصدير التحليلات</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "📊 4 أوراق"
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
# 10) التشخيص الشامل (Full Health Probe)
# 🆕 v1.2.3 FIX-HA15: تحديث رسالة الانتظار عند الاستدعاء من CommandHandler
# ═══════════════════════════════════════════════════════════════════════

async def show_full_health(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """🏥 تشخيص شامل — 6 أبعاد + حكم آلي."""
    query = update.callback_query
    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)

    if query:
        try:
            await query.answer("⏳ جاري التشخيص الشامل... (5-10s)")
        except Exception:
            pass

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    if chat_id is None:
        return

    # ─── رسالة انتظار ─────────────────────────────────────────
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

    # 🆕 FIX-HA15: نحتفظ بالـ Message object لتحديثه لاحقاً
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
        """🆕 FIX-HA15: تحديث/حذف رسالة الانتظار."""
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

    # ─── استيراد آمن ──────────────────────────────────────────
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

    # ─── تنفيذ التشخيص ────────────────────────────────────────
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
            # 🆕 FIX-HA15: نُحدّث رسالة الانتظار (بدل تركها)
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
# 11) اختبار الكمون (Latency Probe)
# 🆕 v1.2.3 FIX-HA15: تحديث رسالة الانتظار عند الاستدعاء من CommandHandler
# ═══════════════════════════════════════════════════════════════════════

async def show_latency(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    """🔬 اختبار كمون الشبكة/DB."""
    query = update.callback_query
    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)

    if query:
        try:
            await query.answer("⏳ جاري اختبار الكمون...")
        except Exception:
            pass

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    if chat_id is None:
        return

    # 🆕 FIX-HA15: waiting message مع الاحتفاظ بالمرجع
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
        """🆕 FIX-HA15: تحديث/حذف رسالة الانتظار."""
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
# 12) التوجيه المركزي
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
}


async def handle_analytics_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query:
        return

    data = (query.data or "").split(":")[0]
    if data not in ANALYTICS_BUTTONS:
        return

    if data == "refresh_btn":
        last = context.user_data.get(
            "last_analytics_btn", "admin_analytics")
        data = last
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
# 13) /analytics
# ═══════════════════════════════════════════════════════════════════════

async def cmd_analytics(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        chat_id = _safe_get_chat_id(update, None)
        await _reject_non_dev(context.bot, chat_id, None)
        return
    await show_analytics_menu(update, context)


# ═══════════════════════════════════════════════════════════════════════
# 14) أوامر مباشرة — /fullhealth + /latency
# ═══════════════════════════════════════════════════════════════════════

async def cmd_fullhealth(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """🏥 أمر مباشر للتشخيص الشامل."""
    await show_full_health(update, context)


async def cmd_latency(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> None:
    """🔬 أمر مباشر لاختبار الكمون."""
    await show_latency(update, context)


# ═══════════════════════════════════════════════════════════════════════
# 15) التسجيل
# 🆕 v1.2.2 FIX-HA14: try/except
# ═══════════════════════════════════════════════════════════════════════

def register_handlers(application) -> bool:
    """
    🆕 v1.2.2 FIX-HA14: try/except + إرجاع bool.

    ملاحظة: هذا الـ helper غير مطلوب عادةً لأن bot.py
    يسجّل الـ handlers مباشرة (ORDER 5/6). يبقى للاستخدام المستقل.
    """
    try:
        pattern = (
            r"^(?:" + "|".join(ANALYTICS_BUTTONS) + r")(?::\d+)?$"
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

        logger.info(
            "✅ handlers_analytics: تم تسجيل %d زر + /analytics "
            "+ /fullhealth + /latency",
            len(ANALYTICS_BUTTONS),
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
    "cmd_analytics",
    "cmd_fullhealth",
    "cmd_latency",
    "register_handlers",
    "register",
]


# ═══════════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═══════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "✅ handlers_analytics v1.2.3 loaded | "
        "buttons=%d | "
        "FIX-HA15=waiting-msg-cleanup | "
        "FIX-HA16=safe-effective-user | "
        "FIX-HA17=send-long-stop-on-fail | "
        "FIX-HA18=elapsed-inf-guard | "
        "FIX-HA19=developer-log | "
        "FIX-HA20=growth-actual-days | "
        "FIX-HA21=chat-id-from-user | "
        "FIX-HA23=reject-warning | "
        "FIX-HA24=slow-query-caller | "
        "FIX-HA25=fmt-num-none-dash | "
        "FIX-HA27=excel-size-guard | "
        "FIX-HA31=default-keyboard-i18n | "
        "KEPT: HA1..HA14",
        len(ANALYTICS_BUTTONS),
    )
except Exception:
    pass
