#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers/handlers_managed_bots.py — لوحة إدارة (v5.7.7 - KEYWORDS-UI)
=================================================================================
📌 المسؤولية:
    • register_managed_bots_handlers(app) — تسجيل pattern="^mb_"
    • لوحة إدارة كاملة: عرض/إضافة/تعديل/تشغيل/إيقاف/حذف
    • 🆕 إدارة الكلمات المفتاحية (عرض/إضافة/حذف).
    • استقبال النص المعلّق (توكن/رسالة/كلمة/رد).

🆕 v5.7.7 (KEYWORDS-UI):
    • زر "🔑 الكلمات المفتاحية (N)" في تفاصيل كل بوت.
    • لوحة إدارة الكلمات: عرض الكلمات المخزنة + أزرار حذف.
    • إضافة كلمة = خطوتان (الكلمة، ثم الرد).
    • حذف كل الكلمات تلقائياً عند حذف البوت.
=================================================================================
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from html import escape as _html_escape
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from config import CONFIG
from managed_bots_runner import (
    is_running,
    reload_messages,
    start_one,
    stop_one,
)
from managed_bots_storage import (
    add_managed_keyword,
    delete_all_keywords_for_bot,
    delete_managed_keyword,
    get_default_messages,
    get_keyword_count,
    get_lock,
    get_stats,
    load_managed_bots,
    load_managed_keywords,
    load_managed_state,
    next_managed_bot_id,
    save_managed_bots,
    save_managed_state,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 1. ثوابت
# ═══════════════════════════════════════════════════════════════════════════

_FIELD_LABEL: Dict[str, str] = {
    "start":  "1️⃣ /start",
    "reply":  "2️⃣ أول نص",
    "third":  "3️⃣ ثاني نص",
    "fourth": "4️⃣ رابع نص",
}

_TOKEN_MIN_LEN = 20
_TOKEN_MAX_LEN = 200
_MSG_MAX_LEN = 4000
_KW_MAX_LEN = 100

_TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_\-]{30,}$")

_MAX_BOTS_IN_PANEL = 12
_MAX_KW_DISPLAY = 15
_VERIFY_TIMEOUT_SEC = 15.0
_START_TIMEOUT_SEC = 30.0


# ═══════════════════════════════════════════════════════════════════════════
# 2. أدوات
# ═══════════════════════════════════════════════════════════════════════════

def _is_admin(user_id: Optional[int]) -> bool:
    if not user_id:
        return False
    try:
        if int(getattr(CONFIG, "PRIMARY_OWNER_ID", 0) or 0) == user_id:
            return True
        for d in (getattr(CONFIG, "DEVELOPER_IDS", []) or []):
            try:
                if int(d) == user_id:
                    return True
            except (TypeError, ValueError):
                continue
    except Exception:
        pass
    return False


def _short(text: str, n: int = 40) -> str:
    if not text:
        return "—"
    t = text.replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


async def _safe_edit(
    query: Any,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML",
) -> None:
    msg = getattr(query, "message", None)
    if msg is None:
        try:
            await query.bot.send_message(
                chat_id=query.from_user.id,
                text=text, reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except Exception:
            pass
        return
    try:
        await query.edit_message_text(
            text=text, reply_markup=reply_markup, parse_mode=parse_mode
        )
    except BadRequest as e:
        if "not modified" in str(e).lower():
            return
        try:
            await msg.reply_text(
                text=text, reply_markup=reply_markup, parse_mode=parse_mode
            )
        except Exception:
            pass
    except Exception:
        pass


def _kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ إلغاء", callback_data="mb_panel")]]
    )


def _kb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 رجوع", callback_data="mb_panel")]]
    )


async def _verify_token_via_api(raw_token: str) -> Optional[str]:
    """التحقق من التوكن عبر Telegram Bot API (لا يعلّق)."""
    url = f"https://api.telegram.org/bot{raw_token}/getMe"
    try:
        timeout = aiohttp.ClientTimeout(total=_VERIFY_TIMEOUT_SEC, connect=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 401:
                    return None
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not data.get("ok"):
                    return None
                return (data.get("result", {}).get("username") or "").strip()
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        logger.error("verify_token: %s: %s", type(e).__name__, e)
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 3. بناء اللوحات
# ═══════════════════════════════════════════════════════════════════════════

def _build_panel(bots, state) -> tuple:
    if not bots:
        return (
            "🎛️ <b>مدير البوتات العامة</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📭 لا توجد بوتات مضافة بعد.\n\n"
            "💡 اضغط الزر أدناه لإضافة بوت عام جديد عبر توكنه.",
            InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ إضافة بوت جديد", callback_data="mb_add")
            ]]),
        )

    stats = get_stats(bots, state)
    lines = [
        "🎛️ <b>مدير البوتات العامة</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>{stats['bots']}</b> بوت • "
        f"<b>{stats['users']}</b> مستخدم • "
        f"<b>{stats['completed']}</b> أكملوا",
        "",
    ]

    rows = []
    for bid, info in sorted(bots.items())[:_MAX_BOTS_IN_PANEL]:
        alive = "🟢" if is_running(bid) else "🔴"
        uname = info.get("name") or "?"
        n_users = len(state.get(bid, {}))
        rows.append([InlineKeyboardButton(
            f"{alive} #{bid} @{uname} — {n_users}👤",
            callback_data=f"mb_bot:{bid}",
        )])

    if len(bots) > _MAX_BOTS_IN_PANEL:
        lines.append(f"⚠️ يُعرض {_MAX_BOTS_IN_PANEL}/{len(bots)}")
        lines.append("")

    rows.append([InlineKeyboardButton("➕ إضافة بوت جديد", callback_data="mb_add")])
    rows.append([InlineKeyboardButton("🔄 تحديث", callback_data="mb_panel")])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _build_bot_detail(
    bid: int,
    info: Dict[str, Any],
    users_state: Dict[int, Any],
    n_keywords: int = 0,
) -> tuple:
    msgs = info.get("messages") or get_default_messages()
    alive = "🟢 يعمل" if is_running(bid) else "🔴 متوقف"
    uname = info.get("name") or "?"
    n_users = len(users_state)
    n_completed = sum(
        1 for st in users_state.values()
        if isinstance(st, dict)
        and all(st.get(f) for f in ("start", "reply", "third", "fourth"))
    )
    added = (info.get("added_at") or "—").replace("T", " ")[:16]

    text = (
        f"📋 <b>بوت #{bid} — @{uname}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🔌 الحالة: {alive}\n"
        f"👥 المستخدمون: <b>{n_users}</b>\n"
        f"✅ أكملوا: <b>{n_completed}</b>\n"
        f"🔑 الكلمات المفتاحية: <b>{n_keywords}</b>\n"
        f"📅 أُضيف: <code>{added}</code>\n\n"
        "📝 <b>الرسائل:</b>\n"
        f"1️⃣ <code>{_short(msgs.get('start',  ''), 60)}</code>\n"
        f"2️⃣ <code>{_short(msgs.get('reply',  ''), 60)}</code>\n"
        f"3️⃣ <code>{_short(msgs.get('third',  ''), 60)}</code>\n"
        f"4️⃣ <code>{_short(msgs.get('fourth', ''), 60)}</code>"
    )

    toggle = (
        InlineKeyboardButton("⏹️ إيقاف", callback_data=f"mb_toggle:{bid}")
        if is_running(bid)
        else InlineKeyboardButton("▶️ تشغيل", callback_data=f"mb_toggle:{bid}")
    )

    rows = [
        [toggle,
         InlineKeyboardButton("✏️ رسالة 1", callback_data=f"mb_set:{bid}:start")],
        [InlineKeyboardButton("✏️ رسالة 2", callback_data=f"mb_set:{bid}:reply"),
         InlineKeyboardButton("✏️ رسالة 3", callback_data=f"mb_set:{bid}:third")],
        [InlineKeyboardButton("✏️ رسالة 4", callback_data=f"mb_set:{bid}:fourth")],
        [InlineKeyboardButton(
            f"🔑 الكلمات المفتاحية ({n_keywords})",
            callback_data=f"mb_kw:{bid}",
        )],
        [InlineKeyboardButton("🗑️ حذف البوت", callback_data=f"mb_del:{bid}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="mb_panel")],
    ]
    return text, InlineKeyboardMarkup(rows)


def _build_keyword_panel(
    bid: int, keywords: Dict[str, str],
) -> tuple:
    if not keywords:
        text = (
            f"🔑 <b>الكلمات المفتاحية — بوت #{bid}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📭 لا توجد كلمات مفتاحية مضافة بعد.\n\n"
            "💡 مثال:\n"
            "  • الكلمة: <code>اليمن</code>\n"
            "  • الرد: <code>🇾🇪 أهلاً بك يا يمني!</code>\n\n"
            "عندما يكتب أي مستخدم كلمة 'اليمن' في رسالته،\n"
            "سيرد البوت بهذا الرد فوراً."
        )
    else:
        lines = [
            f"🔑 <b>الكلمات المفتاحية — بوت #{bid}</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"📋 <b>{len(keywords)}</b> كلمة مخزنة:",
            "",
        ]
        sorted_kws = sorted(keywords.items())
        for idx, (kw, rp) in enumerate(sorted_kws[:_MAX_KW_DISPLAY], 1):
            lines.append(
                f"{idx}. 🔹 <code>{_html_escape(_short(kw, 30))}</code>\n"
                f"   ↪️ {_html_escape(_short(rp, 50))}"
            )
        if len(sorted_kws) > _MAX_KW_DISPLAY:
            lines.append(
                f"\n⚠️ يُعرض {_MAX_KW_DISPLAY}/{len(sorted_kws)} — "
                f"احذف بعضها لعرض الباقي"
            )
        text = "\n".join(lines)

    rows = []
    sorted_kws = sorted(keywords.items()) if keywords else []
    # أزرار حذف (2 في كل صف)
    for i in range(0, min(len(sorted_kws), _MAX_KW_DISPLAY), 2):
        chunk = sorted_kws[i:i + 2]
        row = []
        for j, (kw, _) in enumerate(chunk):
            idx = i + j
            row.append(InlineKeyboardButton(
                f"🗑️ {_short(kw, 12)}",
                callback_data=f"mb_kw_del:{bid}:{idx}",
            ))
        rows.append(row)

    rows.append([InlineKeyboardButton(
        "➕ إضافة كلمة جديدة", callback_data=f"mb_kw_add:{bid}"
    )])
    rows.append([InlineKeyboardButton(
        "🔙 رجوع للبوت", callback_data=f"mb_bot:{bid}"
    )])

    return text, InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Callbacks
# ═══════════════════════════════════════════════════════════════════════════

async def _cb_panel(update, context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    context.user_data.pop("managed_pending", None)
    try:
        bots = await load_managed_bots()
        state = await load_managed_state()
        text, kb = _build_panel(bots, state)
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("_cb_panel: %s", e, exc_info=True)


async def _cb_add(update, context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    context.user_data["managed_pending"] = {"kind": "addbot"}
    await _safe_edit(
        query,
        "➕ <b>إضافة بوت عام جديد</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "1. افتح @BotFather في تلجرام\n"
        "2. أرسل <code>/newbot</code> وأنشئ البوت\n"
        "3. انسخ <b>التوكن</b> الذي سيرسله\n"
        "4. الصقه هنا في هذه المحادثة\n\n"
        "🔒 سيُحذف تلقائياً بعد التحقق والحفظ.",
        _kb_cancel(),
    )


async def _cb_bot(update, context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    m = re.match(r"^mb_bot:(\d+)$", query.data or "")
    if not m:
        return
    bid = int(m.group(1))
    try:
        bots = await load_managed_bots()
        info = bots.get(bid)
        if info is None:
            await _safe_edit(query, "⚠️ البوت غير موجود.", _kb_back())
            return
        state = await load_managed_state()
        n_kw = await get_keyword_count(bid)
        text, kb = _build_bot_detail(bid, info, state.get(bid, {}), n_kw)
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("_cb_bot: %s", e, exc_info=True)


async def _cb_set(update, context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    m = re.match(r"^mb_set:(\d+):(\w+)$", query.data or "")
    if not m:
        return
    bid = int(m.group(1))
    field = m.group(2)
    if field not in _FIELD_LABEL:
        return
    try:
        bots = await load_managed_bots()
        if bid not in bots:
            await _safe_edit(query, "⚠️ البوت غير موجود.", _kb_back())
            return
        current = (bots[bid].get("messages") or {}).get(field, "")
        context.user_data["managed_pending"] = {
            "kind": "set", "bid": bid, "field": field,
        }
        await _safe_edit(
            query,
            f"✏️ <b>تعديل {_FIELD_LABEL[field]}</b> — بوت #{bid}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>الحالي:</b>\n<code>{_short(current, 200)}</code>\n\n"
            "📩 أرسل النص الجديد الآن.\n"
            "💡 للأسطر المتعددة استخدم <code>|</code> كفاصل.",
            _kb_cancel(),
        )
    except Exception as e:
        logger.error("_cb_set: %s", e, exc_info=True)


async def _cb_toggle(update, context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    m = re.match(r"^mb_toggle:(\d+)$", query.data or "")
    if not m:
        return
    bid = int(m.group(1))
    try:
        bots = await load_managed_bots()
        info = bots.get(bid)
        if info is None:
            await _safe_edit(query, "⚠️ البوت غير موجود.", _kb_back())
            return

        if is_running(bid):
            await _safe_edit(query, f"⏳ إيقاف بوت #{bid}...",
                             InlineKeyboardMarkup([]))
            await stop_one(bid)
        else:
            await _safe_edit(query, f"⏳ تشغيل بوت #{bid}...",
                             InlineKeyboardMarkup([]))
            try:
                ok = await asyncio.wait_for(
                    start_one(bid, info.get("token", "")),
                    timeout=_START_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                ok = False
            if not ok:
                await _safe_edit(
                    query,
                    f"❌ فشل تشغيل بوت #{bid}.\n"
                    "تحقق من التوكن أو الصلاحيات.",
                    _kb_back(),
                )
                return

        state = await load_managed_state()
        n_kw = await get_keyword_count(bid)
        text, kb = _build_bot_detail(bid, info, state.get(bid, {}), n_kw)
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("_cb_toggle: %s", e, exc_info=True)


# ═══ 🆕 v5.7.7: لوحة الكلمات المفتاحية ═══

async def _cb_kw_panel(update, context) -> None:
    """عرض لوحة الكلمات المفتاحية."""
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    m = re.match(r"^mb_kw:(\d+)$", query.data or "")
    if not m:
        return
    bid = int(m.group(1))
    context.user_data.pop("managed_pending", None)
    try:
        keywords = await load_managed_keywords(bid)
        text, kb = _build_keyword_panel(bid, keywords)
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("_cb_kw_panel: %s", e, exc_info=True)


async def _cb_kw_add(update, context) -> None:
    """بدء إضافة كلمة مفتاحية (خطوة 1: الكلمة)."""
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    m = re.match(r"^mb_kw_add:(\d+)$", query.data or "")
    if not m:
        return
    bid = int(m.group(1))
    context.user_data["managed_pending"] = {
        "kind": "kw_keyword", "bid": bid,
    }
    await _safe_edit(
        query,
        f"➕ <b>إضافة كلمة مفتاحية — بوت #{bid}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>الخطوة 1 من 2: الكلمة</b>\n\n"
        "📩 أرسل الكلمة التي تريد أن يبحث عنها البوت.\n"
        "مثل: <code>اليمن</code> أو <code>صنعاء</code> أو <code>عدن</code>\n\n"
        "💡 المطابقة: إذا كانت الكلمة موجودة داخل رسالة المستخدم.\n"
        f"الحد الأقصى: {_KW_MAX_LEN} حرف.",
        _kb_cancel(),
    )


async def _cb_kw_del(update, context) -> None:
    """حذف كلمة بالترتيب (index)."""
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    m = re.match(r"^mb_kw_del:(\d+):(\d+)$", query.data or "")
    if not m:
        return
    bid = int(m.group(1))
    idx = int(m.group(2))
    try:
        keywords = await load_managed_keywords(bid)
        sorted_kws = sorted(keywords.items())
        if not (0 <= idx < len(sorted_kws)):
            await _safe_edit(
                query, "⚠️ الكلمة غير موجودة (ربما حُذفت).",
                InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع", callback_data=f"mb_kw:{bid}")
                ]])
            )
            return
        kw_to_del, _ = sorted_kws[idx]
        ok = await delete_managed_keyword(bid, kw_to_del)
        if not ok:
            await _safe_edit(
                query, "❌ فشل الحذف.",
                InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع", callback_data=f"mb_kw:{bid}")
                ]])
            )
            return
        # إعادة تحميل الكلمات في البوت العامل
        try:
            await reload_messages(bid)
        except Exception:
            pass
        # عرض اللوحة المحدثة
        keywords = await load_managed_keywords(bid)
        text, kb = _build_keyword_panel(bid, keywords)
        await _safe_edit(
            query,
            f"🗑️ حُذفت: <code>{_html_escape(_short(kw_to_del, 30))}</code>\n\n"
            + text,
            kb,
        )
    except Exception as e:
        logger.error("_cb_kw_del: %s", e, exc_info=True)


# ═══ حذف البوت ═══

async def _cb_del_confirm(update, context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    m = re.match(r"^mb_del:(\d+)$", query.data or "")
    if not m:
        return
    bid = int(m.group(1))
    try:
        bots = await load_managed_bots()
        if bid not in bots:
            await _safe_edit(query, "⚠️ البوت غير موجود.", _kb_back())
            return
        state = await load_managed_state()
        n_users = len(state.get(bid, {}))
        n_kw = await get_keyword_count(bid)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"✅ نعم، احذف #{bid}", callback_data=f"mb_dodel:{bid}"
            )],
            [InlineKeyboardButton("🔙 إلغاء", callback_data=f"mb_bot:{bid}")],
        ])
        await _safe_edit(
            query,
            f"⚠️ <b>تأكيد حذف بوت #{bid}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "• سيُوقف البوت فوراً\n"
            "• ستُحذف رسائله\n"
            f"• ستُحذف بيانات <b>{n_users}</b> مستخدم\n"
            f"• ستُحذف <b>{n_kw}</b> كلمة مفتاحية\n"
            "• لا يمكن التراجع\n\n"
            "هل أنت متأكد؟",
            kb,
        )
    except Exception as e:
        logger.error("_cb_del_confirm: %s", e, exc_info=True)


async def _cb_del_do(update, context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    m = re.match(r"^mb_dodel:(\d+)$", query.data or "")
    if not m:
        return
    bid = int(m.group(1))

    await _safe_edit(query, f"⏳ حذف بوت #{bid}...", InlineKeyboardMarkup([]))

    try:
        await stop_one(bid)
    except Exception:
        pass

    try:
        async with get_lock():
            bots = await load_managed_bots()
            if bid in bots:
                del bots[bid]
                await save_managed_bots(bots)
            state = await load_managed_state()
            if bid in state:
                del state[bid]
                await save_managed_state(state)
        # 🆕 v5.7.7: حذف الكلمات المفتاحية
        await delete_all_keywords_for_bot(bid)
    except Exception as e:
        logger.error("del_bot: %s", e, exc_info=True)
        await _safe_edit(query, "❌ فشل الحذف.", _kb_back())
        return

    try:
        bots = await load_managed_bots()
        state = await load_managed_state()
        text, kb = _build_panel(bots, state)
        await _safe_edit(query, f"🗑️ تم حذف بوت #{bid}.\n\n" + text, kb)
    except Exception as e:
        logger.error("_cb_del_do: %s", e, exc_info=True)


# ═══════════════════════════════════════════════════════════════════════════
# 5. معالج النص المعلّق
# ═══════════════════════════════════════════════════════════════════════════

async def _handle_pending_text(update, context) -> None:
    if not update.effective_user or not update.message:
        return
    chat = update.effective_chat
    if chat is None or chat.type != "private":
        return
    if not _is_admin(update.effective_user.id):
        return

    pending = context.user_data.get("managed_pending")
    if not pending:
        return

    kind = pending.get("kind")
    raw = (update.message.text or "").strip()

    if kind == "addbot":
        await _process_addbot(update, context, raw)
    elif kind == "set":
        await _process_set(update, context, pending, raw)
    elif kind == "kw_keyword":
        await _process_kw_keyword(update, context, pending, raw)
    elif kind == "kw_reply":
        await _process_kw_reply(update, context, pending, raw)
    else:
        context.user_data.pop("managed_pending", None)
        return

    raise ApplicationHandlerStop


async def _process_addbot(update, context, raw: str) -> None:
    logger.info("_process_addbot: len=%d", len(raw) if raw else 0)

    if not raw or len(raw) < _TOKEN_MIN_LEN or len(raw) > _TOKEN_MAX_LEN:
        await update.message.reply_text("❌ التوكن غير صالح (الطول).")
        return
    if not _TOKEN_RE.match(raw):
        await update.message.reply_text(
            "❌ شكل التوكن غير صحيح.\nمثل: <code>123456789:ABC...xyz</code>",
            parse_mode="HTML",
        )
        return

    relax_token = (getattr(CONFIG, "TOKEN", "") or "").strip()
    if relax_token and raw == relax_token:
        await update.message.reply_text("❌ هذا توكن Relax Manager نفسه!")
        return

    try:
        status_msg = await update.message.reply_text("⏳ جاري التحقق...")
    except Exception:
        return

    username = None
    try:
        username = await asyncio.wait_for(
            _verify_token_via_api(raw),
            timeout=_VERIFY_TIMEOUT_SEC + 2.0,
        )
    except asyncio.TimeoutError:
        logger.error("verify timeout")
    except Exception as e:
        logger.error("verify exception: %s", e)

    if not username:
        try:
            await status_msg.edit_text(
                "❌ فشل التحقق من التوكن.\n"
                "تحقق من التوكن أو الشبكة."
            )
        except Exception:
            pass
        return

    try:
        await status_msg.edit_text(f"✅ تم التحقق من @{username}")
    except Exception:
        pass

    try:
        existing = await load_managed_bots()
    except Exception:
        await status_msg.edit_text("❌ فشل قراءة التخزين.")
        return

    for bid, info in existing.items():
        if info.get("token") == raw:
            await status_msg.edit_text(f"⚠️ التوكن مستخدم في بوت #{bid}.")
            return

    try:
        async with get_lock():
            bots = await load_managed_bots()
            new_bid = next_managed_bot_id(bots)
            bots[new_bid] = {
                "token": raw,
                "name": username,
                "messages": get_default_messages(),
                "added_at": _now_iso(),
            }
            await save_managed_bots(bots)
    except Exception as e:
        logger.error("addbot save: %s", e)
        await status_msg.edit_text("❌ فشل الحفظ.")
        return

    try:
        await update.message.delete()
    except Exception:
        pass

    context.user_data.pop("managed_pending", None)
    ok = False
    try:
        ok = await asyncio.wait_for(
            start_one(new_bid, raw), timeout=_START_TIMEOUT_SEC,
        )
    except (asyncio.TimeoutError, Exception) as e:
        logger.error("start_one: %s", e)
        ok = False

    status_text = "🟢 يعمل الآن" if ok else "🔴 فشل التشغيل — استخدم ▶️"
    chat_id = update.effective_chat.id
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"✅ أُضيف بوت <b>#{new_bid}</b> — @{username}\n{status_text}"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    try:
        bots = await load_managed_bots()
        state = await load_managed_state()
        text, kb = _build_panel(bots, state)
        await context.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=kb, parse_mode="HTML",
        )
    except Exception:
        pass


async def _process_set(update, context, pending, raw: str) -> None:
    bid = int(pending.get("bid", 0))
    field = pending.get("field", "")
    if field not in _FIELD_LABEL or not raw or len(raw) > _MSG_MAX_LEN:
        return

    new_text = raw.replace("|", "\n")

    try:
        async with get_lock():
            bots = await load_managed_bots()
            if bid not in bots:
                context.user_data.pop("managed_pending", None)
                await update.message.reply_text("⚠️ البوت غير موجود.")
                return
            bots[bid]["messages"][field] = new_text
            await save_managed_bots(bots)
    except Exception as e:
        logger.error("set message: %s", e)
        await update.message.reply_text("❌ فشل الحفظ.")
        return

    try:
        await reload_messages(bid)
    except Exception:
        pass

    context.user_data.pop("managed_pending", None)
    await update.message.reply_text(
        f"✅ تم تحديث {_FIELD_LABEL[field]} — بوت #{bid}.",
        parse_mode="HTML",
    )

    try:
        bots = await load_managed_bots()
        state = await load_managed_state()
        info = bots.get(bid)
        if info:
            n_kw = await get_keyword_count(bid)
            text, kb = _build_bot_detail(bid, info, state.get(bid, {}), n_kw)
            await update.message.reply_text(
                text=text, reply_markup=kb, parse_mode="HTML",
            )
    except Exception:
        pass


# ═══ 🆕 v5.7.7: إضافة كلمة مفتاحية (خطوتان) ═══

async def _process_kw_keyword(update, context, pending, raw: str) -> None:
    """الخطوة 1: استلام الكلمة."""
    bid = int(pending.get("bid", 0))
    if not raw:
        await update.message.reply_text("⚠️ الكلمة فارغة.")
        return
    if len(raw) > _KW_MAX_LEN:
        await update.message.reply_text(
            f"⚠️ الكلمة طويلة (الحد {_KW_MAX_LEN} حرف)."
        )
        return

    # حفظ الكلمة في pending، وطلب الرد
    context.user_data["managed_pending"] = {
        "kind": "kw_reply",
        "bid": bid,
        "keyword": raw,
    }
    await update.message.reply_text(
        f"✅ الكلمة: <code>{_html_escape(raw)}</code>\n\n"
        "<b>الخطوة 2 من 2: الرد</b>\n\n"
        "📩 الآن أرسل الرد الذي سيرسله البوت عند مطابقة هذه الكلمة.\n\n"
        "💡 مثال: <code>🇾🇪 أهلاً بك يا يمني!</code>",
        parse_mode="HTML",
    )


async def _process_kw_reply(update, context, pending, raw: str) -> None:
    """الخطوة 2: استلام الرد وحفظه."""
    bid = int(pending.get("bid", 0))
    keyword = (pending.get("keyword") or "").strip()

    if not keyword:
        context.user_data.pop("managed_pending", None)
        await update.message.reply_text("⚠️ حدث خطأ، أعد المحاولة.")
        return
    if not raw:
        await update.message.reply_text("⚠️ الرد فارغ.")
        return
    if len(raw) > _MSG_MAX_LEN:
        await update.message.reply_text(
            f"⚠️ الرد طويل (الحد {_MSG_MAX_LEN} حرف)."
        )
        return

    try:
        ok = await add_managed_keyword(bid, keyword, raw)
    except Exception as e:
        logger.error("add_keyword: %s", e)
        ok = False

    if not ok:
        await update.message.reply_text("❌ فشل حفظ الكلمة.")
        context.user_data.pop("managed_pending", None)
        return

    # إعادة تحميل الكلمات في البوت العامل
    try:
        await reload_messages(bid)
    except Exception:
        pass

    context.user_data.pop("managed_pending", None)
    await update.message.reply_text(
        f"✅ <b>أُضيفت الكلمة المفتاحية</b>\n\n"
        f"🔹 الكلمة: <code>{_html_escape(keyword)}</code>\n"
        f"↪️ الرد: {_html_escape(_short(raw, 100))}",
        parse_mode="HTML",
    )

    # عرض لوحة الكلمات المحدثة
    try:
        keywords = await load_managed_keywords(bid)
        text, kb = _build_keyword_panel(bid, keywords)
        await update.message.reply_text(
            text=text, reply_markup=kb, parse_mode="HTML",
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 6. التسجيل
# ═══════════════════════════════════════════════════════════════════════════

def register_managed_bots_handlers(app: Application) -> None:
    handlers = [
        (r"^mb_panel$", _cb_panel),
        (r"^mb_add$", _cb_add),
        (r"^mb_bot:\d+$", _cb_bot),
        (r"^mb_set:\d+:\w+$", _cb_set),
        (r"^mb_toggle:\d+$", _cb_toggle),
        (r"^mb_del:\d+$", _cb_del_confirm),
        (r"^mb_dodel:\d+$", _cb_del_do),
        # 🆕 v5.7.7: الكلمات المفتاحية
        (r"^mb_kw:\d+$", _cb_kw_panel),
        (r"^mb_kw_add:\d+$", _cb_kw_add),
        (r"^mb_kw_del:\d+:\d+$", _cb_kw_del),
    ]

    for pattern, cb in handlers:
        app.add_handler(
            CallbackQueryHandler(cb, pattern=pattern),
            group=0,
        )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            _handle_pending_text,
        ),
        group=-1,
    )

    logger.info(
        "✅ managed_bots v5.7.7: %d callbacks + 1 text handler | "
        "keywords=enabled",
        len(handlers),
    )


__all__ = ["register_managed_bots_handlers"]


try:
    logger.debug(
        "🛡️ handlers_managed_bots v5.7.7 (KEYWORDS-UI) loaded"
    )
except Exception:
    pass