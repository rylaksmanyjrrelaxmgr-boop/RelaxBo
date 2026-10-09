#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_analytics.py — واجهة التحليلات المتقدمة (v1.1.0)
================================================================================
Frontend layer: يحوّل بيانات AnalyticsMixin (database_analytics.py)
إلى واجهة Telegram منسّقة بـ HTML.

الأزرار المُدعَمة:
    - admin_analytics    → القائمة الرئيسية
    - growth_30d_btn     → نمو المستخدمين (30 يوم)
    - top_channels_btn   → أفضل 10 قنوات
    - publish_stats_btn  → متوسط النشر
    - channels_rate_btn  → نسبة النجاح
    - subscriptions_btn  → الاشتراكات الشهرية
    - pool_live_btn      → Pool مباشر
    - slow_queries_btn   → أبطأ الاستعلامات
    - export_excel_btn   → تصدير Excel
    - refresh_btn        → تحديث القائمة الحالية

--------------------------------------------------------------------------------
v1.1.0:
    ✅ كل الأزرار العشرة مُعالَجة
    ✅ refresh_btn ذكي — يتذكر آخر تقرير
    ✅ استخدم AnalyticsMixin كاملاً
    ✅ دعم PostgreSQL فقط (مع رسالة واضحة للأنواع الأخرى)
    ✅ تصدير Excel يتطلب openpyxl
    ✅ HTML parse_mode مع safe_send
    ✅ timeouts ديناميكية
================================================================================
"""

import logging
import io
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, CommandHandler,
)

from config import CONFIG
from database import DB
from utils import (
    CB, TimeUtils, safe_send, KeyboardFactory,
    TranslationManager,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# قائمة الأزرار المُدعَمة
# ═══════════════════════════════════════════════════════════════════════

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
)


# ═══════════════════════════════════════════════════════════════════════
# دوال مساعدة
# ═══════════════════════════════════════════════════════════════════════

def _t(key: str, default: str, lang: str = "ar") -> str:
    """ترجمة مع fallback إلى KeyboardFactory."""
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
    """شريط تقدّم بصري."""
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


def _check_developer(user_id: int) -> bool:
    """فحص صلاحية المطور."""
    try:
        if hasattr(CONFIG, "is_developer"):
            return bool(CONFIG.is_developer(user_id))
        return user_id == int(CONFIG.PRIMARY_OWNER_ID)
    except Exception:
        return False


async def _safe_edit(query, text: str, keyboard=None,
                     parse_mode: str = "HTML") -> bool:
    """تعديل الرسالة مع fallback عند الفشل."""
    try:
        await query.edit_message_text(
            text, parse_mode=parse_mode, reply_markup=keyboard,
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return True
        logger.debug("edit_message_text failed: %s", e)
        try:
            if query.message:
                await safe_send(
                    query.bot, query.message.chat_id, text,
                    reply_markup=keyboard, parse_mode=parse_mode,
                )
                return True
        except Exception as e2:
            logger.warning("fallback send failed: %s", e2)
        return False


def _back_keyboard(target: str = "admin_analytics") -> InlineKeyboardMarkup:
    """لوحة رجوع موحّدة."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            _t("back", "🔙 رجوع"),
            callback_data=target,
        )
    ]])


def _back_refresh_keyboard(target: str = "admin_analytics",
                           refresh: str = "refresh_btn"
                           ) -> InlineKeyboardMarkup:
    """لوحة رجوع + تحديث."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            _t("refresh_btn", "🔄 تحديث"),
            callback_data=refresh,
        )],
        [InlineKeyboardButton(
            _t("back", "🔙 رجوع"),
            callback_data=target,
        )],
    ])


def _fmt_num(n) -> str:
    """تنسيق رقم بفواصل الآلاف."""
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_elapsed(sec) -> str:
    """تنسيق زمن الاستجابة."""
    try:
        s = float(sec)
    except (TypeError, ValueError):
        return "?"
    if s < 1:
        return f"{int(s * 1000)}ms"
    if s < 60:
        return f"{s:.2f}s"
    return f"{int(s // 60)}m{int(s % 60)}s"


# ═══════════════════════════════════════════════════════════════════════
# 1) القائمة الرئيسية — admin_analytics
# ═══════════════════════════════════════════════════════════════════════

async def show_analytics_menu(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض القائمة الرئيسية للتحليلات."""
    try:
        query = update.callback_query
        user_id = update.effective_user.id

        if query:
            try:
                await query.answer()
            except Exception:
                pass

        if not _check_developer(user_id):
            if query:
                await query.answer(
                    "❌ هذه الميزة للمطور فقط.", show_alert=True)
            return

        if not getattr(DB, "USE_POSTGRES", False):
            db_type = getattr(DB, "DB_TYPE", "sqlite").upper()
            text = (
                "📊 <b>التحليلات المتقدمة</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"⚠️ هذه الميزة تتطلب <b>PostgreSQL</b>.\n"
                f"قاعدة البيانات الحالية: <code>{db_type}</code>"
            )
            if query:
                await _safe_edit(query, text, _back_keyboard("admin"))
            return

        # لوحة الأزرار — من KeyboardFactory أو default
        try:
            keyboard = KeyboardFactory.build("analytics", lang="ar")
        except Exception as e:
            logger.debug("KeyboardFactory.build(analytics): %s", e)
            keyboard = _default_analytics_keyboard()

        text = (
            "📊 <b>التحليلات المتقدمة</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "اختر نوع التقرير من الأزرار أدناه.\n\n"
            f"🕐 <i>{TimeUtils.mecca_iso()[:19]}</i>"
        )

        if query:
            await _safe_edit(query, text, keyboard)
        else:
            await safe_send(
                context.bot, update.effective_chat.id, text,
                reply_markup=keyboard, parse_mode="HTML",
            )
    except Exception as e:
        logger.error("show_analytics_menu: %s", e, exc_info=True)


def _default_analytics_keyboard() -> InlineKeyboardMarkup:
    """لوحة افتراضية للتحليلات إذا لم يوجد buttons_config."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 نمو المستخدمين", callback_data="growth_30d_btn"),
         InlineKeyboardButton("🏆 أفضل القنوات", callback_data="top_channels_btn")],
        [InlineKeyboardButton("📊 متوسط النشر", callback_data="publish_stats_btn"),
         InlineKeyboardButton("🎯 نسبة النجاح", callback_data="channels_rate_btn")],
        [InlineKeyboardButton("💎 الاشتراكات", callback_data="subscriptions_btn"),
         InlineKeyboardButton("🚀 Pool مباشر", callback_data="pool_live_btn")],
        [InlineKeyboardButton("🐌 استعلامات بطيئة", callback_data="slow_queries_btn"),
         InlineKeyboardButton("📤 تصدير Excel", callback_data="export_excel_btn")],
        [InlineKeyboardButton("🔄 تحديث", callback_data="refresh_btn")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin")],
    ])


# ═══════════════════════════════════════════════════════════════════════
# 2) نمو المستخدمين — growth_30d_btn
# ═══════════════════════════════════════════════════════════════════════

async def show_growth_30d(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """📈 نمو المستخدمين آخر 30 يوم."""
    query = update.callback_query
    try:
        await query.answer("⏳ جاري الحساب...")
    except Exception:
        pass

    if not _check_developer(update.effective_user.id):
        await query.answer("❌ للمطور فقط", show_alert=True)
        return

    try:
        rows = await DB.get_user_growth(days=30)
        rows = rows or []

        total_count = sum(r.get("count", 0) for r in rows)
        avg = round(total_count / 30, 1) if total_count else 0.0
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
                day = r.get("date", "?")[-5:]
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
        await _safe_edit(
            query,
            f"❌ فشل حساب النمو.\n<code>{str(e)[:200]}</code>",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 3) أفضل 10 قنوات — top_channels_btn
# ═══════════════════════════════════════════════════════════════════════

async def show_top_channels(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """🏆 أفضل 10 قنوات."""
    query = update.callback_query
    try:
        await query.answer("⏳ جاري الحساب...")
    except Exception:
        pass

    if not _check_developer(update.effective_user.id):
        await query.answer("❌ للمطور فقط", show_alert=True)
        return

    try:
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
                name = (r.get("name") or "—")[:28]
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
        await _safe_edit(
            query,
            f"❌ فشل جلب القنوات.\n<code>{str(e)[:200]}</code>",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 4) إحصائيات النشر — publish_stats_btn
# ═══════════════════════════════════════════════════════════════════════

async def show_publish_stats(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """📊 متوسط النشر وإحصائيات عامة."""
    query = update.callback_query
    try:
        await query.answer("⏳ جاري الحساب...")
    except Exception:
        pass

    if not _check_developer(update.effective_user.id):
        await query.answer("❌ للمطور فقط", show_alert=True)
        return

    try:
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
        await _safe_edit(
            query,
            f"❌ فشل جلب الإحصائيات.\n<code>{str(e)[:200]}</code>",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 5) نسبة النجاح — channels_rate_btn
# ═══════════════════════════════════════════════════════════════════════

async def show_channels_rate(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """🎯 نسبة النجاح لكل قناة (الأقل أولاً)."""
    query = update.callback_query
    try:
        await query.answer("⏳ جاري الحساب...")
    except Exception:
        pass

    if not _check_developer(update.effective_user.id):
        await query.answer("❌ للمطور فقط", show_alert=True)
        return

    try:
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
                name = (r.get("name") or "—")[:24]
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
        await _safe_edit(
            query,
            f"❌ فشل جلب النسب.\n<code>{str(e)[:200]}</code>",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 6) الاشتراكات — subscriptions_btn
# ═══════════════════════════════════════════════════════════════════════

async def show_subscriptions(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """💎 اشتراكات جديدة شهرياً."""
    query = update.callback_query
    try:
        await query.answer("⏳ جاري الحساب...")
    except Exception:
        pass

    if not _check_developer(update.effective_user.id):
        await query.answer("❌ للمطور فقط", show_alert=True)
        return

    try:
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
                month = str(r.get("month", "?"))
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
        await _safe_edit(
            query,
            f"❌ فشل جلب الاشتراكات.\n<code>{str(e)[:200]}</code>",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 7) Pool مباشر — pool_live_btn
# ═══════════════════════════════════════════════════════════════════════

async def show_pool_live(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """🚀 حالة Pool مباشرة."""
    query = update.callback_query
    try:
        await query.answer("⏳ جاري الفحص...")
    except Exception:
        pass

    if not _check_developer(update.effective_user.id):
        await query.answer("❌ للمطور فقط", show_alert=True)
        return

    try:
        pool = await DB.get_pool_live() or {}

        if not pool.get("available"):
            reason = pool.get("type", "unknown")
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
        await _safe_edit(
            query,
            f"❌ فشل فحص Pool.\n<code>{str(e)[:200]}</code>",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 8) أبطأ الاستعلامات — slow_queries_btn
# ═══════════════════════════════════════════════════════════════════════

async def show_slow_queries(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    """🐌 أبطأ الاستعلامات."""
    query = update.callback_query
    try:
        await query.answer("⏳ جاري الفحص...")
    except Exception:
        pass

    if not _check_developer(update.effective_user.id):
        await query.answer("❌ للمطور فقط", show_alert=True)
        return

    try:
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
                q = (r.get("query") or r.get("sql") or "?")[:80]
                elapsed = r.get("elapsed", 0)
                q = q.replace("<", "&lt;").replace(">", "&gt;")
                lines.append(
                    f"{i}. <code>{q}</code>\n"
                    f"   ⏱️ <b>{_fmt_elapsed(elapsed)}</b>"
                )

        text = "\n".join(lines)
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="slow_queries_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_slow_queries: %s", e, exc_info=True)
        await _safe_edit(
            query,
            f"❌ فشل جلب الاستعلامات.\n<code>{str(e)[:200]}</code>",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 9) تصدير Excel — export_excel_btn
# ═══════════════════════════════════════════════════════════════════════

async def export_excel(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    """📤 تصدير بيانات التحليلات إلى Excel."""
    query = update.callback_query
    try:
        await query.answer("⏳ جاري التصدير...")
    except Exception:
        pass

    if not _check_developer(update.effective_user.id):
        await query.answer("❌ للمطور فقط", show_alert=True)
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

        # ورقة 1: نمو المستخدمين
        ws1 = wb.active
        ws1.title = "User Growth"
        ws1.append(["Date", "Count"])
        rows1 = await DB.get_user_growth(days=30) or []
        for r in rows1:
            ws1.append([r.get("date"), r.get("count")])

        # ورقة 2: أفضل القنوات
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

        # ورقة 3: إحصائيات النشر
        ws3 = wb.create_sheet("Publish Stats")
        stats = await DB.get_publish_stats() or {}
        ws3.append(["Metric", "Value"])
        for k, v in stats.items():
            ws3.append([k, v])

        # ورقة 4: الاشتراكات
        ws4 = wb.create_sheet("Subscriptions")
        ws4.append(["Month", "Count"])
        rows4 = await DB.get_subscription_rate(months=12) or []
        for r in rows4:
            ws4.append([r.get("month"), r.get("count")])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

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
                "📊 4 أوراق:\n"
                "  • User Growth\n"
                "  • Top Channels\n"
                "  • Publish Stats\n"
                "  • Subscriptions"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("export_excel: %s", e, exc_info=True)
        try:
            await query.answer(
                f"❌ فشل التصدير: {str(e)[:100]}",
                show_alert=True,
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# 10) التوجيه المركزي
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
    # refresh_btn يُعالج عبر last_analytics_btn
}


async def handle_analytics_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """موزّع أزرار التحليلات."""
    query = update.callback_query
    if not query:
        return

    # استخرج المفتاح (يدعم "growth_30d_btn" و "growth_30d_btn:-100123")
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
        try:
            await query.answer(
                f"❌ خطأ: {str(e)[:80]}", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# 11) /analytics — أمر مباشر
# ═══════════════════════════════════════════════════════════════════════

async def cmd_analytics(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """/analytics — فتح لوحة التحليلات."""
    if not _check_developer(update.effective_user.id):
        await safe_send(
            context.bot, update.effective_chat.id,
            "❌ هذا الأمر للمطور فقط.",
        )
        return

    # نبني callback_query اصطناعي لتوحيد المسار
    await show_analytics_menu(update, context)


# ═══════════════════════════════════════════════════════════════════════
# 12) التسجيل
# ═══════════════════════════════════════════════════════════════════════

def register_handlers(application) -> None:
    """
    تسجيل كل معالجات التحليلات.

    ⚠️ مهم: يُستدعى BEFORE المعالج العام (handlers_callback).
    """
    # موزّع مركزي مع regex يطابق كل الأزرار
    pattern = r"^(?:" + "|".join(ANALYTICS_BUTTONS) + r")(?::\d+)?$"
    application.add_handler(
        CallbackQueryHandler(
            handle_analytics_callback,
            pattern=pattern,
        )
    )
    # أمر مباشر
    application.add_handler(CommandHandler("analytics", cmd_analytics))

    logger.info(
        "✅ handlers_analytics: تم تسجيل %d زر + /analytics",
        len(ANALYTICS_BUTTONS),
    )


# alias شائع
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
    "cmd_analytics",
    "register_handlers",
    "register",
]