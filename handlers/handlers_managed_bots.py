#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers/handlers_managed_bots.py — لوحة إدارة (v5.8.1 - PRIVATE-TOGGLE)
=================================================================================
🆕 v5.8.1 (PRIVATE-TOGGLE):
    🟢 FEATURE-PRIVATE-TOGGLE: زر 💬 للتحكم بالردود في الخاص (hot-toggle).
    • يستدعي `set_respond_in_private` (بدون restart).
    • تناظر كامل مع زر 📢.

✅ محفوظ من v5.8.0: HOT-TOGGLE (groups).
✅ محفوظ من v5.7.9: SPLIT-REPLIES.
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
    set_respond_in_groups,
    set_respond_in_private,   # 🆕 v5.8.1
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
    update_managed_keyword_reply,
)

logger = logging.getLogger(__name__)


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

_SKIP_TOKEN = "/skip"


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


def _normalize_keyword_entry(entry: Any) -> Dict[str, str]:
    if isinstance(entry, dict):
        return {
            "private_reply": str(entry.get("private_reply", "") or ""),
            "group_reply":   str(entry.get("group_reply",   "") or ""),
        }
    if entry is None:
        return {"private_reply": "", "group_reply": ""}
    s = str(entry)
    return {"private_reply": s, "group_reply": s}


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
# بناء اللوحات
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
        groups = "📢" if info.get("respond_in_groups", False) else ""
        # 🆕 private indicator (يبقى فارغاً افتراضياً لأنه مفعّل)
        private_off = "" if info.get("respond_in_private", True) else "💬"
        rows.append([InlineKeyboardButton(
            f"{alive} #{bid} @{uname} — {n_users}👤 {groups}{private_off}",
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

    groups_on = bool(info.get("respond_in_groups", False))
    groups_status = "🟢 مفعّل" if groups_on else "🔴 معطّل"

    # 🆕 v5.8.1
    private_on = bool(info.get("respond_in_private", True))
    private_status = "🟢 مفعّل" if private_on else "🔴 معطّل"

    text = (
        f"📋 <b>بوت #{bid} — @{uname}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🔌 الحالة: {alive}\n"
        f"👥 المستخدمون: <b>{n_users}</b>\n"
        f"✅ أكملوا: <b>{n_completed}</b>\n"
        f"🔑 الكلمات المفتاحية: <b>{n_keywords}</b>\n"
        f"📢 الردود في المجموعات: {groups_status}\n"
        f"💬 الردود في الخاص: {private_status}\n"
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

    groups_toggle = InlineKeyboardButton(
        f"📢 الردود في المجموعات: {'🟢' if groups_on else '🔴'}",
        callback_data=f"mb_toggle_groups:{bid}",
    )

    # 🆕 v5.8.1
    private_toggle = InlineKeyboardButton(
        f"💬 الردود في الخاص: {'🟢' if private_on else '🔴'}",
        callback_data=f"mb_toggle_private:{bid}",
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
        [groups_toggle],
        [private_toggle],   # 🆕
        [InlineKeyboardButton("🗑️ حذف البوت", callback_data=f"mb_del:{bid}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="mb_panel")],
    ]
    return text, InlineKeyboardMarkup(rows)


def _build_keyword_panel(
    bid: int, keywords: Dict[str, Any],
) -> tuple:
    if not keywords:
        text = (
            f"🔑 <b>الكلمات المفتاحية — بوت #{bid}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📭 لا توجد كلمات مفتاحية مضافة بعد.\n\n"
            "💡 عند الإضافة ستُطلب 3 خطوات:\n"
            "  1. الكلمة (مثل: <code>اليمن</code>)\n"
            "  2. رد الخاص    (مثل: <code>أهلاً يا يمني 🇾🇪</code>)\n"
            "  3. رد المجموعات (مثل: <code>🇾🇪 صنعاء عاصمة اليمن</code>)\n\n"
            "يمكنك كتابة <code>/skip</code> لتخطي أي خطوة."
        )
    else:
        lines = [
            f"🔑 <b>الكلمات المفتاحية — بوت #{bid}</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            f"📋 <b>{len(keywords)}</b> كلمة مخزنة:",
            "",
        ]
        sorted_kws = sorted(keywords.items())
        for idx, (kw, entry) in enumerate(sorted_kws[:_MAX_KW_DISPLAY], 1):
            norm = _normalize_keyword_entry(entry)
            pv = _short(norm["private_reply"], 50) or "<i>(غير مضبوط)</i>"
            gr = _short(norm["group_reply"],   50) or "<i>(غير مضبوط)</i>"
            lines.append(
                f"<b>{idx}. 🔹 <code>{_html_escape(_short(kw, 30))}</code></b>\n"
                f"   💬 خاص: {_html_escape(pv) if norm['private_reply'] else pv}\n"
                f"   📢 مجموعات: {_html_escape(gr) if norm['group_reply'] else gr}"
            )
        if len(sorted_kws) > _MAX_KW_DISPLAY:
            lines.append(
                f"\n⚠️ يُعرض {_MAX_KW_DISPLAY}/{len(sorted_kws)}"
            )
        text = "\n".join(lines)

    rows = []
    sorted_kws = sorted(keywords.items()) if keywords else []

    for i, (kw, _) in enumerate(sorted_kws[:_MAX_KW_DISPLAY]):
        rows.append([
            InlineKeyboardButton(
                f"💬 {i+1}", callback_data=f"mb_kw_pe:{bid}:{i}"
            ),
            InlineKeyboardButton(
                f"📢 {i+1}", callback_data=f"mb_kw_ge:{bid}:{i}"
            ),
            InlineKeyboardButton(
                f"🗑️ {i+1}", callback_data=f"mb_kw_del:{bid}:{i}"
            ),
        ])

    rows.append([InlineKeyboardButton(
        "➕ إضافة كلمة جديدة", callback_data=f"mb_kw_add:{bid}"
    )])
    rows.append([InlineKeyboardButton(
        "🔙 رجوع للبوت", callback_data=f"mb_bot:{bid}"
    )])

    return text, InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# Callbacks
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


async def _cb_toggle_groups(update, context) -> None:
    """v5.8.0: hot-toggle للمجموعات."""
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    m = re.match(r"^mb_toggle_groups:(\d+)$", query.data or "")
    if not m:
        return
    bid = int(m.group(1))

    try:
        async with get_lock():
            bots = await load_managed_bots()
            info = bots.get(bid)
            if info is None:
                await _safe_edit(query, "⚠️ البوت غير موجود.", _kb_back())
                return
            current = bool(info.get("respond_in_groups", False))
            new_state = not current
            info["respond_in_groups"] = new_state
            await save_managed_bots(bots)

        hot_ok = await set_respond_in_groups(bid, new_state)

        logger.info(
            "🎛️ mb_toggle_groups: bot #%d → respond_in_groups=%s "
            "(storage_saved=True, hot_applied=%s)",
            bid, new_state, hot_ok,
        )

        state = await load_managed_state()
        n_kw = await get_keyword_count(bid)
        text, kb = _build_bot_detail(bid, info, state.get(bid, {}), n_kw)

        if new_state:
            prefix = (
                "🟢 <b>فُعّلت الردود في المجموعات.</b>\n\n"
                "✅ الخاص لم يتأثر — يعمل كما هو.\n"
                "✅ التغيير فوري — لا إعادة تشغيل.\n\n"
                "⚠️ <b>مهم:</b> ليعمل البوت فعلياً في مجموعة:\n"
                "1. عطّل Privacy من @BotFather لهذا البوت\n"
                "   (<code>/setprivacy</code> → Disable)\n"
                "2. أو ارفعه <b>مشرفاً</b> في كل مجموعة\n\n"
            )
        else:
            prefix = (
                "🔴 <b>أُوقفت الردود في المجموعات.</b>\n\n"
                "✅ الخاص لم يتأثر — يعمل كما هو.\n"
                "✅ التغيير فوري — لا إعادة تشغيل.\n\n"
            )

        if not hot_ok:
            prefix += "⚠️ البوت غير مشغّل — ستُطبَّق عند تشغيله.\n\n"

        await _safe_edit(query, prefix + text, kb)

    except Exception as e:
        logger.error("_cb_toggle_groups: %s", e, exc_info=True)


# 🆕 v5.8.1
async def _cb_toggle_private(update, context) -> None:
    """v5.8.1: hot-toggle للخاص (تناظر مع 📢)."""
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    m = re.match(r"^mb_toggle_private:(\d+)$", query.data or "")
    if not m:
        return
    bid = int(m.group(1))

    try:
        async with get_lock():
            bots = await load_managed_bots()
            info = bots.get(bid)
            if info is None:
                await _safe_edit(query, "⚠️ البوت غير موجود.", _kb_back())
                return
            current = bool(info.get("respond_in_private", True))
            new_state = not current
            info["respond_in_private"] = new_state
            await save_managed_bots(bots)

        hot_ok = await set_respond_in_private(bid, new_state)

        logger.info(
            "🎛️ mb_toggle_private: bot #%d → respond_in_private=%s "
            "(storage_saved=True, hot_applied=%s)",
            bid, new_state, hot_ok,
        )

        state = await load_managed_state()
        n_kw = await get_keyword_count(bid)
        text, kb = _build_bot_detail(bid, info, state.get(bid, {}), n_kw)

        if new_state:
            prefix = (
                "🟢 <b>فُعّلت الردود في الخاص.</b>\n\n"
                "✅ التغيير فوري — لا إعادة تشغيل.\n"
                "📌 /start + الكلمات المفتاحية + التسلسل: تعمل الآن.\n\n"
            )
        else:
            prefix = (
                "🔴 <b>أُوقفت الردود في الخاص.</b>\n\n"
                "✅ التغيير فوري — لا إعادة تشغيل.\n"
                "📌 المجموعات لم تتأثر — تعمل كما هي.\n"
                "📌 في الخاص: /start + الكلمات + التسلسل: متوقفة.\n\n"
            )

        if not hot_ok:
            prefix += "⚠️ البوت غير مشغّل — ستُطبَّق عند تشغيله.\n\n"

        await _safe_edit(query, prefix + text, kb)

    except Exception as e:
        logger.error("_cb_toggle_private: %s", e, exc_info=True)


async def _cb_kw_panel(update, context) -> None:
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
        "<b>الخطوة 1 من 3: الكلمة</b>\n\n"
        "📩 أرسل الكلمة التي تريد أن يبحث عنها البوت.\n"
        "مثل: <code>اليمن</code> أو <code>صنعاء</code>\n\n"
        f"الحد الأقصى: {_KW_MAX_LEN} حرف.",
        _kb_cancel(),
    )


async def _cb_kw_edit_private(update, context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    m = re.match(r"^mb_kw_pe:(\d+):(\d+)$", query.data or "")
    if not m:
        return
    bid = int(m.group(1))
    idx = int(m.group(2))

    try:
        keywords = await load_managed_keywords(bid)
        sorted_kws = sorted(keywords.items())
        if not (0 <= idx < len(sorted_kws)):
            await _safe_edit(query, "⚠️ الكلمة غير موجودة.", _kb_back())
            return
        kw, entry = sorted_kws[idx]
        norm = _normalize_keyword_entry(entry)

        context.user_data["managed_pending"] = {
            "kind": "kw_edit_private",
            "bid": bid,
            "keyword": kw,
        }
        current_display = _short(norm["private_reply"], 200) or "<i>(فارغ)</i>"
        await _safe_edit(
            query,
            f"💬 <b>تعديل رد الخاص — <code>{_html_escape(kw)}</code></b>\n"
            f"بوت #{bid}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>الحالي:</b>\n<code>{current_display}</code>\n\n"
            "📩 أرسل النص الجديد الآن.\n"
            "أو <code>/skip</code> للإبقاء على الحالي.",
            _kb_cancel(),
        )
    except Exception as e:
        logger.error("_cb_kw_edit_private: %s", e, exc_info=True)


async def _cb_kw_edit_group(update, context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    m = re.match(r"^mb_kw_ge:(\d+):(\d+)$", query.data or "")
    if not m:
        return
    bid = int(m.group(1))
    idx = int(m.group(2))

    try:
        keywords = await load_managed_keywords(bid)
        sorted_kws = sorted(keywords.items())
        if not (0 <= idx < len(sorted_kws)):
            await _safe_edit(query, "⚠️ الكلمة غير موجودة.", _kb_back())
            return
        kw, entry = sorted_kws[idx]
        norm = _normalize_keyword_entry(entry)

        context.user_data["managed_pending"] = {
            "kind": "kw_edit_group",
            "bid": bid,
            "keyword": kw,
        }
        current_display = _short(norm["group_reply"], 200) or "<i>(فارغ)</i>"
        await _safe_edit(
            query,
            f"📢 <b>تعديل رد المجموعات — <code>{_html_escape(kw)}</code></b>\n"
            f"بوت #{bid}\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>الحالي:</b>\n<code>{current_display}</code>\n\n"
            "📩 أرسل النص الجديد الآن.\n"
            "أو <code>/skip</code> للإبقاء على الحالي.",
            _kb_cancel(),
        )
    except Exception as e:
        logger.error("_cb_kw_edit_group: %s", e, exc_info=True)


async def _cb_kw_del(update, context) -> None:
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
        try:
            await reload_messages(bid)
        except Exception:
            pass
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
# معالج النص المعلّق
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
    elif kind == "kw_private":
        await _process_kw_private(update, context, pending, raw)
    elif kind == "kw_group":
        await _process_kw_group(update, context, pending, raw)
    elif kind == "kw_edit_private":
        await _process_kw_edit_private(update, context, pending, raw)
    elif kind == "kw_edit_group":
        await _process_kw_edit_group(update, context, pending, raw)
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
                "❌ فشل التحقق من التوكن.\nتحقق من التوكن أو الشبكة."
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
                "respond_in_groups": False,
                "respond_in_private": True,  # 🆕 افتراضي مفعّل
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


async def _process_kw_keyword(update, context, pending, raw: str) -> None:
    bid = int(pending.get("bid", 0))
    if not raw:
        await update.message.reply_text("⚠️ الكلمة فارغة.")
        return
    if len(raw) > _KW_MAX_LEN:
        await update.message.reply_text(
            f"⚠️ الكلمة طويلة (الحد {_KW_MAX_LEN} حرف)."
        )
        return

    context.user_data["managed_pending"] = {
        "kind": "kw_private",
        "bid": bid,
        "keyword": raw,
    }
    await update.message.reply_text(
        f"✅ الكلمة: <code>{_html_escape(raw)}</code>\n\n"
        "<b>الخطوة 2 من 3: رد الخاص</b>\n\n"
        "📩 أرسل الرد الذي سيُرسل في <b>الخاص</b> عند مطابقة الكلمة.\n"
        "أو <code>/skip</code> لتخطي (لن يرد في الخاص).\n\n"
        "💡 مثال: <code>أهلاً يا يمني 🇾🇪</code>",
        parse_mode="HTML",
    )


async def _process_kw_private(update, context, pending, raw: str) -> None:
    bid = int(pending.get("bid", 0))
    keyword = (pending.get("keyword") or "").strip()

    if not keyword:
        context.user_data.pop("managed_pending", None)
        await update.message.reply_text("⚠️ حدث خطأ، أعد المحاولة.")
        return

    if raw.lower() == _SKIP_TOKEN:
        private_reply = ""
    else:
        if len(raw) > _MSG_MAX_LEN:
            await update.message.reply_text(
                f"⚠️ الرد طويل (الحد {_MSG_MAX_LEN} حرف)."
            )
            return
        private_reply = raw

    context.user_data["managed_pending"] = {
        "kind": "kw_group",
        "bid": bid,
        "keyword": keyword,
        "private_reply": private_reply,
    }
    private_display = _short(private_reply, 80) or "<i>(تخطي)</i>"
    await update.message.reply_text(
        f"✅ رد الخاص: <code>{_html_escape(private_display)}</code>\n\n"
        "<b>الخطوة 3 من 3: رد المجموعات</b>\n\n"
        "📩 أرسل الرد الذي سيُرسل في <b>المجموعات</b> عند مطابقة الكلمة.\n"
        "أو <code>/skip</code> لتخطي (لن يرد في المجموعات).\n\n"
        "💡 مثال: <code>🇾🇪 صنعاء عاصمة اليمن</code>",
        parse_mode="HTML",
    )


async def _process_kw_group(update, context, pending, raw: str) -> None:
    bid = int(pending.get("bid", 0))
    keyword = (pending.get("keyword") or "").strip()
    private_reply = (pending.get("private_reply") or "")

    if not keyword:
        context.user_data.pop("managed_pending", None)
        await update.message.reply_text("⚠️ حدث خطأ، أعد المحاولة.")
        return

    if raw.lower() == _SKIP_TOKEN:
        group_reply = ""
    else:
        if len(raw) > _MSG_MAX_LEN:
            await update.message.reply_text(
                f"⚠️ الرد طويل (الحد {_MSG_MAX_LEN} حرف)."
            )
            return
        group_reply = raw

    if not private_reply and not group_reply:
        await update.message.reply_text(
            "⚠️ لا يمكن حفظ كلمة بدون أي رد.\n"
            "أرسل رداً واحداً على الأقل (خاص أو مجموعات)."
        )
        return

    try:
        ok = await add_managed_keyword(
            bid, keyword,
            private_reply=private_reply,
            group_reply=group_reply,
        )
    except Exception as e:
        logger.error("add_keyword: %s", e)
        ok = False

    if not ok:
        await update.message.reply_text("❌ فشل حفظ الكلمة.")
        context.user_data.pop("managed_pending", None)
        return

    try:
        await reload_messages(bid)
    except Exception:
        pass

    context.user_data.pop("managed_pending", None)

    pv = _short(private_reply, 100) or "<i>(بدون)</i>"
    gr = _short(group_reply,   100) or "<i>(بدون)</i>"
    await update.message.reply_text(
        f"✅ <b>أُضيفت الكلمة المفتاحية</b>\n\n"
        f"🔹 الكلمة: <code>{_html_escape(keyword)}</code>\n"
        f"💬 رد الخاص: {_html_escape(pv)}\n"
        f"📢 رد المجموعات: {_html_escape(gr)}",
        parse_mode="HTML",
    )

    try:
        keywords = await load_managed_keywords(bid)
        text, kb = _build_keyword_panel(bid, keywords)
        await update.message.reply_text(
            text=text, reply_markup=kb, parse_mode="HTML",
        )
    except Exception:
        pass


async def _process_kw_edit_private(update, context, pending, raw: str) -> None:
    bid = int(pending.get("bid", 0))
    keyword = (pending.get("keyword") or "").strip()

    if not keyword:
        context.user_data.pop("managed_pending", None)
        await update.message.reply_text("⚠️ حدث خطأ.")
        return

    if raw.lower() == _SKIP_TOKEN:
        context.user_data.pop("managed_pending", None)
        await update.message.reply_text("✅ لم يُغيَّر شيء.")
        try:
            keywords = await load_managed_keywords(bid)
            text, kb = _build_keyword_panel(bid, keywords)
            await update.message.reply_text(
                text=text, reply_markup=kb, parse_mode="HTML",
            )
        except Exception:
            pass
        return

    if len(raw) > _MSG_MAX_LEN:
        await update.message.reply_text(
            f"⚠️ الرد طويل (الحد {_MSG_MAX_LEN} حرف)."
        )
        return

    try:
        ok = await update_managed_keyword_reply(
            bid, keyword, private_reply=raw,
        )
    except Exception as e:
        logger.error("update kw private: %s", e)
        ok = False

    if not ok:
        await update.message.reply_text("❌ فشل الحفظ.")
        context.user_data.pop("managed_pending", None)
        return

    try:
        await reload_messages(bid)
    except Exception:
        pass

    context.user_data.pop("managed_pending", None)
    await update.message.reply_text(
        f"✅ تم تحديث رد الخاص لـ <code>{_html_escape(keyword)}</code>.",
        parse_mode="HTML",
    )
    try:
        keywords = await load_managed_keywords(bid)
        text, kb = _build_keyword_panel(bid, keywords)
        await update.message.reply_text(
            text=text, reply_markup=kb, parse_mode="HTML",
        )
    except Exception:
        pass


async def _process_kw_edit_group(update, context, pending, raw: str) -> None:
    bid = int(pending.get("bid", 0))
    keyword = (pending.get("keyword") or "").strip()

    if not keyword:
        context.user_data.pop("managed_pending", None)
        await update.message.reply_text("⚠️ حدث خطأ.")
        return

    if raw.lower() == _SKIP_TOKEN:
        context.user_data.pop("managed_pending", None)
        await update.message.reply_text("✅ لم يُغيَّر شيء.")
        try:
            keywords = await load_managed_keywords(bid)
            text, kb = _build_keyword_panel(bid, keywords)
            await update.message.reply_text(
                text=text, reply_markup=kb, parse_mode="HTML",
            )
        except Exception:
            pass
        return

    if len(raw) > _MSG_MAX_LEN:
        await update.message.reply_text(
            f"⚠️ الرد طويل (الحد {_MSG_MAX_LEN} حرف)."
        )
        return

    try:
        ok = await update_managed_keyword_reply(
            bid, keyword, group_reply=raw,
        )
    except Exception as e:
        logger.error("update kw group: %s", e)
        ok = False

    if not ok:
        await update.message.reply_text("❌ فشل الحفظ.")
        context.user_data.pop("managed_pending", None)
        return

    try:
        await reload_messages(bid)
    except Exception:
        pass

    context.user_data.pop("managed_pending", None)
    await update.message.reply_text(
        f"✅ تم تحديث رد المجموعات لـ <code>{_html_escape(keyword)}</code>.",
        parse_mode="HTML",
    )
    try:
        keywords = await load_managed_keywords(bid)
        text, kb = _build_keyword_panel(bid, keywords)
        await update.message.reply_text(
            text=text, reply_markup=kb, parse_mode="HTML",
        )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# التسجيل
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
        (r"^mb_kw:\d+$", _cb_kw_panel),
        (r"^mb_kw_add:\d+$", _cb_kw_add),
        (r"^mb_kw_del:\d+:\d+$", _cb_kw_del),
        (r"^mb_toggle_groups:\d+$", _cb_toggle_groups),
        (r"^mb_toggle_private:\d+$", _cb_toggle_private),   # 🆕 v5.8.1
        (r"^mb_kw_pe:\d+:\d+$", _cb_kw_edit_private),
        (r"^mb_kw_ge:\d+:\d+$", _cb_kw_edit_group),
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
        "✅ managed_bots v5.8.1: %d callbacks + 1 text handler | "
        "keywords=splitted | groups-toggle=hot | private-toggle=hot",
        len(handlers),
    )


__all__ = ["register_managed_bots_handlers"]


try:
    logger.debug(
        "🛡️ handlers_managed_bots v5.8.1 (PRIVATE-TOGGLE) loaded"
    )
except Exception:
    pass