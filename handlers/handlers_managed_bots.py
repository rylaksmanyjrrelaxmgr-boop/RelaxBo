#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers/handlers_managed_bots.py — لوحة إدارة البوتات المُدارة (v5.7.4)
=================================================================================
📌 المسؤولية:
    • register_managed_bots_handlers(app) — تسجيل pattern="^mb_"
    • لوحة إدارة كاملة: عرض/إضافة/تعديل/تشغيل/إيقاف/حذف
    • استقبال النص المعلّق (توكن/رسالة) عبر MessageHandler
    • استخدام ApplicationHandlerStop لتفادي تداخل MessageHandlers

🆕 v5.7.4 (FIX-VERIFY-HANG):
    🔴 إصلاح "جاري التحقق..." يعلّق:
       السبب: Bot(token=raw) + get_me() داخل event loop مع PTB 20.x
       قد يسبب deadlock في HTTPX pool أو انتظاراً غير محدود.
       الحل: التحقق من التوكن مباشرة عبر aiohttp + Telegram Bot API
       (أسرع 10x، لا يعلّق، لا يحتاج إغلاق موارد).
    🟢 إضافة logger.info في كل خطوة من _process_addbot للتشخيص.

🎯 العقد:
    bot.py → register_managed_bots_handlers(app)  (قبل catch-all)
    لوحة الأدمن → callback_data="mb_panel"
=================================================================================
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aiohttp  # 🆕 v5.7.4: للتحقق المباشر من التوكن

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
    get_default_messages,
    get_lock,
    get_stats,
    load_managed_bots,
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
    "fourth": "4️⃣ ثالث نص",
}

_TOKEN_MIN_LEN = 20
_TOKEN_MAX_LEN = 200
_MSG_MAX_LEN = 4000
_TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_\-]{30,}$")
_MAX_BOTS_IN_PANEL = 12

# 🆕 v5.7.4: timeout للتحقق من التوكن
_VERIFY_TIMEOUT_SEC = 10.0


# ═══════════════════════════════════════════════════════════════════════════
# 2. أدوات
# ═══════════════════════════════════════════════════════════════════════════

def _is_admin(user_id: Optional[int]) -> bool:
    if not user_id:
        return False
    try:
        owner = int(getattr(CONFIG, "PRIMARY_OWNER_ID", 0) or 0)
        if owner and user_id == owner:
            return True
    except (TypeError, ValueError):
        pass
    try:
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
                text=text,
                reply_markup=reply_markup,
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


# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v5.7.4: التحقق المباشر من التوكن عبر HTTP (بدون Bot)
# ═══════════════════════════════════════════════════════════════════════════

async def _verify_token_via_api(raw_token: str) -> Optional[str]:
    """
    يتحقق من صحة التوكن مباشرة عبر Telegram Bot API.

    Returns:
        username (str) إذا التوكن صالح
        None إذا التوكن غير صالح أو فشل الاتصال

    💡 لماذا aiohttp وليس Bot()?
       - Bot() قد يعلّق في PTB 20.x خارج Application
       - aiohttp أسرع 10x
       - لا يحتاج إغلاق موارد (Session context manager)
       - لا يتأثر بمشاكل event loop
    """
    url = f"https://api.telegram.org/bot{raw_token}/getMe"
    try:
        timeout = aiohttp.ClientTimeout(total=_VERIFY_TIMEOUT_SEC, connect=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 401:
                    logger.warning(
                        "🔍 verify_token: 401 Unauthorized (توكن غير صالح)"
                    )
                    return None
                if resp.status != 200:
                    logger.warning(
                        "🔍 verify_token: HTTP %d", resp.status
                    )
                    return None
                data = await resp.json()
                if not data.get("ok"):
                    logger.warning(
                        "🔍 verify_token: ok=False | desc=%s",
                        data.get("description", "?")
                    )
                    return None
                result = data.get("result") or {}
                username = (result.get("username") or "").strip()
                logger.info(
                    "🔍 verify_token: ✅ نجح | @%s", username or "?"
                )
                return username
    except asyncio.TimeoutError:
        logger.warning(
            "🔍 verify_token: timeout بعد %.0fs", _VERIFY_TIMEOUT_SEC
        )
        return None
    except aiohttp.ClientError as e:
        logger.warning("🔍 verify_token: ClientError: %s", e)
        return None
    except Exception as e:
        logger.error(
            "🔍 verify_token: exception %s: %s",
            type(e).__name__, e, exc_info=True
        )
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 3. بناء اللوحة
# ═══════════════════════════════════════════════════════════════════════════

def _build_panel(
    bots: Dict[int, Dict[str, Any]],
    state: Dict[int, Any],
) -> tuple:
    if not bots:
        text = (
            "🎛️ <b>مدير البوتات العامة</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "📭 لا توجد بوتات مضافة بعد.\n\n"
            "💡 اضغط الزر أدناه لإضافة بوت عام جديد عبر توكنه."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة بوت جديد", callback_data="mb_add")],
        ])
        return text, kb

    stats = get_stats(bots, state)
    lines = [
        "🎛️ <b>مدير البوتات العامة</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>{stats['bots']}</b> بوت • <b>{stats['users']}</b> مستخدم • "
        f"<b>{stats['completed']}</b> أكملوا",
        "",
    ]

    rows = []
    items = sorted(bots.items())[:_MAX_BOTS_IN_PANEL]
    for bid, info in items:
        alive = "🟢" if is_running(bid) else "🔴"
        uname = info.get("name") or "?"
        n_users = len(state.get(bid, {}))
        label = f"{alive} #{bid} @{uname} — {n_users}👤"
        rows.append([InlineKeyboardButton(label, callback_data=f"mb_bot:{bid}")])

    if len(bots) > _MAX_BOTS_IN_PANEL:
        lines.append(
            f"⚠️ يُعرض {_MAX_BOTS_IN_PANEL}/{len(bots)} — احذف بعضاً للمتابعة"
        )
        lines.append("")

    rows.append([InlineKeyboardButton("➕ إضافة بوت جديد", callback_data="mb_add")])
    rows.append([InlineKeyboardButton("🔄 تحديث", callback_data="mb_panel")])

    text = "\n".join(lines)
    return text, InlineKeyboardMarkup(rows)


def _build_bot_detail(
    bid: int,
    info: Dict[str, Any],
    users_state: Dict[int, Any],
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
        [InlineKeyboardButton("🗑️ حذف البوت", callback_data=f"mb_del:{bid}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="mb_panel")],
    ]
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
        await _safe_edit(
            query, f"❌ خطأ: {type(e).__name__}", _kb_back()
        )


async def _cb_add(update, context) -> None:
    query = update.callback_query
    await query.answer()
    if not _is_admin(query.from_user.id):
        return
    context.user_data["managed_pending"] = {"kind": "addbot"}
    logger.info("🔍 mb_add: pending=addbot set")
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
        text, kb = _build_bot_detail(bid, info, state.get(bid, {}))
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
            "kind": "set",
            "bid": bid,
            "field": field,
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
            await _safe_edit(
                query, f"⏳ إيقاف بوت #{bid}...", InlineKeyboardMarkup([])
            )
            await stop_one(bid)
        else:
            await _safe_edit(
                query, f"⏳ تشغيل بوت #{bid}...", InlineKeyboardMarkup([])
            )
            ok = await start_one(bid, info.get("token", ""))
            if not ok:
                await _safe_edit(
                    query,
                    f"❌ فشل تشغيل بوت #{bid}.\n"
                    "تحقق من التوكن أو الصلاحيات.",
                    _kb_back(),
                )
                return

        state = await load_managed_state()
        text, kb = _build_bot_detail(bid, info, state.get(bid, {}))
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("_cb_toggle: %s", e, exc_info=True)


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
        info = bots.get(bid)
        if info is None:
            await _safe_edit(query, "⚠️ البوت غير موجود.", _kb_back())
            return
        _state = await load_managed_state()
        n_users = len(_state.get(bid, {}))
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
            "• ستُحذف رسائله من التخزين\n"
            f"• ستُحذف بيانات <b>{n_users}</b> مستخدم\n"
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
    except Exception as _e:
        logger.debug("del_bot stop: %s", _e)

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
    except Exception as _e:
        logger.error("del_bot storage: %s", _e, exc_info=True)
        await _safe_edit(query, "❌ فشل الحذف.", _kb_back())
        return

    try:
        bots = await load_managed_bots()
        state = await load_managed_state()
        text, kb = _build_panel(bots, state)
        await _safe_edit(query, f"🗑️ تم حذف بوت #{bid}.\n\n" + text, kb)
    except Exception as e:
        logger.error("_cb_del_do final panel: %s", e, exc_info=True)


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
    logger.info(
        "🔍 _handle_pending_text: kind=%s len=%d", kind, len(raw)
    )

    if kind == "addbot":
        await _process_addbot(update, context, raw)
    elif kind == "set":
        await _process_set(update, context, pending, raw)
    else:
        context.user_data.pop("managed_pending", None)
        return

    raise ApplicationHandlerStop


async def _process_addbot(update, context, raw: str) -> None:
    """
    🆕 v5.7.4: يستخدم aiohttp للتحقق من التوكن (لا يعلّق).
    """
    logger.info(
        "🔍 _process_addbot: بدأ | len=%d", len(raw) if raw else 0
    )

    # ── 1. تحقق أولي ──
    if not raw or len(raw) < _TOKEN_MIN_LEN or len(raw) > _TOKEN_MAX_LEN:
        logger.warning(
            "🔍 _process_addbot: فشل طول | len=%d", len(raw) if raw else 0
        )
        await update.message.reply_text(
            "❌ التوكن غير صالح (الطول غير متوقع).\n"
            "أعد الإرسال أو /cancel."
        )
        return

    if not _TOKEN_RE.match(raw):
        logger.warning("🔍 _process_addbot: فشل regex")
        await update.message.reply_text(
            "❌ شكل التوكن غير صحيح.\n"
            "يجب أن يكون مثل: <code>123456789:ABC...xyz</code>",
            parse_mode="HTML",
        )
        return

    # ── 2. تحقق تعارض Relax ──
    relax_token = (getattr(CONFIG, "TOKEN", "") or "").strip()
    if relax_token and raw == relax_token:
        logger.warning("🔍 _process_addbot: تعارض مع Relax")
        await update.message.reply_text(
            "❌ هذا توكن Relax Manager نفسه — سيتعارض!"
        )
        return

    # ── 3. تحقق التكرار ──
    logger.info("🔍 _process_addbot: تحميل البوتات الحالية...")
    try:
        existing = await load_managed_bots()
        logger.info(
            "🔍 _process_addbot: عدد البوتات الحالية=%d", len(existing)
        )
    except Exception as _e:
        logger.error(
            "🔍 _process_addbot: فشل load_managed_bots: %s",
            _e, exc_info=True
        )
        await update.message.reply_text(
            "❌ فشل قراءة التخزين. حاول لاحقاً."
        )
        return

    for bid, info in existing.items():
        if info.get("token") == raw:
            logger.info(
                "🔍 _process_addbot: التوكن مستخدم في بوت #%s", bid
            )
            await update.message.reply_text(
                f"⚠️ التوكن مستخدم مسبقاً في بوت #{bid}."
            )
            return

    # ── 4. عرض رسالة التحقق ──
    try:
        status_msg = await update.message.reply_text(
            "⏳ جاري التحقق من التوكن..."
        )
        logger.info(
            "🔍 _process_addbot: status_msg_id=%s", status_msg.message_id
        )
    except Exception as _e:
        logger.error(
            "🔍 _process_addbot: فشل إرسال status_msg: %s",
            _e, exc_info=True
        )
        return

    # ── 5. التحقق عبر HTTP (aiohttp) ──
    logger.info(
        "🔍 _process_addbot: بدء التحقق عبر aiohttp (timeout=%.0fs)...",
        _VERIFY_TIMEOUT_SEC,
    )
    username = await _verify_token_via_api(raw)

    if username is None:
        logger.warning(
            "🔍 _process_addbot: التحقق فشل — عرض رسالة خطأ للمستخدم"
        )
        try:
            await status_msg.edit_text(
                "❌ توكن غير صالح أو تعذّر الاتصال بتلجرام.\n"
                "تحقق من:\n"
                "• التوكن صحيح (من @BotFather)\n"
                "• الشبكة تعمل\n"
                "• ثم أعد المحاولة."
            )
        except Exception as _e:
            logger.debug("edit_text verify fail: %s", _e)
        return

    logger.info(
        "🔍 _process_addbot: التحقق نجح | @%s", username or "?"
    )

    # ── 6. حفظ في DB ──
    logger.info("🔍 _process_addbot: حفظ البوت الجديد...")
    try:
        async with get_lock():
            bots = await load_managed_bots()
            new_bid = next_managed_bot_id(bots)
            bots[new_bid] = {
                "token":    raw,
                "name":     username,
                "messages": get_default_messages(),
                "added_at": _now_iso(),
            }
            await save_managed_bots(bots)
        logger.info(
            "🔍 _process_addbot: حفظ نجح | new_bid=%d", new_bid
        )
    except Exception as _e:
        logger.error(
            "🔍 _process_addbot: save فشل: %s", _e, exc_info=True
        )
        try:
            await status_msg.edit_text("❌ فشل الحفظ في قاعدة البيانات.")
        except Exception:
            pass
        return

    # ── 7. حذف رسالة التوكن ──
    try:
        await update.message.delete()
        logger.info("🔍 _process_addbot: حُذفت رسالة التوكن")
    except Exception as _e:
        logger.debug("🔍 _process_addbot: delete: %s", _e)

    # ── 8. تشغيل البوت ──
    context.user_data.pop("managed_pending", None)
    logger.info("🔍 _process_addbot: بدء تشغيل البوت #%d...", new_bid)
    try:
        ok = await start_one(new_bid, raw)
        status_text = (
            "🟢 يعمل الآن" if ok else "🔴 فشل التشغيل — استخدم ▶️ لاحقاً"
        )
        logger.info(
            "🔍 _process_addbot: start_one نتيجة=%s", ok
        )
    except Exception as _e:
        logger.error(
            "🔍 _process_addbot: start_one exception: %s",
            _e, exc_info=True
        )
        status_text = "🔴 فشل التشغيل"

    # ── 9. إرسال رسالة النجاح ──
    chat_id = update.effective_chat.id
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"✅ أُضيف بوت <b>#{new_bid}</b> — @{username}\n"
                f"{status_text}"
            ),
            parse_mode="HTML",
        )
        logger.info("🔍 _process_addbot: رسالة النجاح أُرسلت")
    except Exception as _e:
        logger.error(
            "🔍 _process_addbot: فشل إرسال النتيجة: %s",
            _e, exc_info=True
        )

    # ── 10. إرسال اللوحة المحدّثة ──
    try:
        bots = await load_managed_bots()
        state = await load_managed_state()
        text, kb = _build_panel(bots, state)
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=kb,
            parse_mode="HTML",
        )
        logger.info(
            "🔍 _process_addbot: لوحة الإدارة أُرسلت — انتهى بنجاح"
        )
    except Exception as _e:
        logger.error(
            "🔍 _process_addbot: فشل إرسال اللوحة: %s",
            _e, exc_info=True
        )


async def _process_set(
    update, context, pending: Dict[str, Any], raw: str
) -> None:
    bid = int(pending.get("bid", 0))
    field = pending.get("field", "")
    if field not in _FIELD_LABEL:
        context.user_data.pop("managed_pending", None)
        return
    if not raw:
        await update.message.reply_text("⚠️ النص فارغ.")
        return
    if len(raw) > _MSG_MAX_LEN:
        await update.message.reply_text(
            f"⚠️ النص طويل جداً (الحد {_MSG_MAX_LEN} حرف)."
        )
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
    except Exception as _e:
        logger.error("set message storage: %s", _e, exc_info=True)
        await update.message.reply_text("❌ فشل الحفظ.")
        return

    try:
        await reload_messages(bid)
    except Exception as _e:
        logger.debug("reload_messages: %s", _e)

    context.user_data.pop("managed_pending", None)
    await update.message.reply_text(
        f"✅ تم تحديث {_FIELD_LABEL[field]} — بوت #{bid}.",
        parse_mode="HTML",
    )

    try:
        bots = await load_managed_bots()
        state = await load_managed_state()
        info = bots.get(bid)
        if info is not None:
            text, kb = _build_bot_detail(bid, info, state.get(bid, {}))
            await update.message.reply_text(
                text=text, reply_markup=kb, parse_mode="HTML"
            )
    except Exception as _e:
        logger.debug("_process_set final panel: %s", _e)


# ═══════════════════════════════════════════════════════════════════════════
# 6. register_managed_bots_handlers
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
        "✅ managed_bots_handlers v5.7.4: %d callbacks + 1 text handler "
        "(group=-1) | verify=HTTP",
        len(handlers),
    )


# ═══════════════════════════════════════════════════════════════════════════
# 7. __all__
# ═══════════════════════════════════════════════════════════════════════════

__all__ = ["register_managed_bots_handlers"]


# ═══════════════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═══════════════════════════════════════════════════════════════════════════

try:
    logger.debug(
        "🛡️ handlers_managed_bots v5.7.4 (FIX-VERIFY-HANG) loaded | "
        "callbacks=7 | text_handler=group(-1) | "
        "verify=aiohttp | timeout=%.0fs",
        _VERIFY_TIMEOUT_SEC,
    )
except Exception:
    pass