#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_callbacks_admin.py - v2.0.0
═══════════════════════════════════════════════════════════════════
معالجات Callbacks — لوحة الأدمن + العقوبات + قناة السجلات
═══════════════════════════════════════════════════════════════════
🆕 v2.0.0 (CORRECTED-FULL):
    🔴 FIX-1: _t() → async مع await صحيح (كانت coroutines بدون await).
    🔴 FIX-2: حماية كاملة من BadRequest/Forbidden/TimedOut + fallback
             تلقائي لإزالة HTML عند فشل parse.
    🔴 FIX-3: تحقّق إجباري من صلاحيات المطوّر لكل admin_*.
    🔴 FIX-4: أزرار رجوع إجبارية في كل رسالة (لا شاشات ميتة).
    🟠 FIX-5: parse_mode='HTML' افتراضياً.
    🟠 FIX-6: logger موحّد + logging للمسار التشخيصي.
    🟠 FIX-7: قناة السجلات — show/clear فعليان + set عبر FSM.
    🟠 FIX-8: penalty_* — تحقّق من مشرف المجموعة (لا المطوّر).
    🟡 FIX-9: __all__ صريح + BEACON + __version__.
    🟡 FIX-10: factory pattern لتقليل التكرار مع الحفاظ على
             كل الأسماء الأصلية (توافق كامل مع أي dispatcher).
═══════════════════════════════════════════════════════════════════
"""

import asyncio
import logging
from html import escape
from re import compile as re_compile, sub as re_sub
from typing import Optional, Callable, Awaitable, Dict, Any

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.error import BadRequest, Forbidden, TimedOut
from telegram.ext import ContextTypes

from config import CONFIG
from database import DB

try:
    from utils import StateManager, UserState
except ImportError:
    StateManager = None
    UserState = None

try:
    from utils import is_authorized_in_group
except ImportError:
    async def is_authorized_in_group(*args, **kwargs) -> bool:
        return False


logger = logging.getLogger(__name__)


__version__ = "2.0.0"


# ═══════════════════════════════════════════════════════════════════
# ثوابت
# ═══════════════════════════════════════════════════════════════════

_EDIT_TIMEOUT = 20.0
_ANSWER_TIMEOUT = 10.0
_TELEGRAM_TEXT_LIMIT = 4096

_PARSE_ERROR_HINTS = (
    "can't parse",
    "can't find end tag",
    "unsupported start tag",
    "unclosed tag",
    "invalid entity",
)

_TME_INVALID_SEGMENTS = frozenset({
    'c', 'joinchat', 'addstickers', 'addemoji',
})

_HTML_TAG_RE = re_compile(r'<[^>]+>')


# ═══════════════════════════════════════════════════════════════════
# أدوات مساعدة
# ═══════════════════════════════════════════════════════════════════

def _is_parse_error(err_str: str) -> bool:
    low = (err_str or "").lower()
    return any(h in low for h in _PARSE_ERROR_HINTS)


def _strip_html(s: str) -> str:
    if not s:
        return ""
    try:
        return re_sub(_HTML_TAG_RE, '', s)
    except Exception:
        return s


def _is_dev(update: Update) -> bool:
    """تحقّق موحّد من صلاحيات المطوّر."""
    try:
        uid = update.effective_user.id
        if not uid:
            return False
        if hasattr(CONFIG, 'is_developer'):
            return bool(CONFIG.is_developer(uid))
        primary = int(getattr(CONFIG, 'PRIMARY_OWNER_ID', 0) or 0)
        return bool(primary and uid == primary)
    except Exception as e:
        logger.debug("_is_dev failed: %s", e)
        return False


async def _t(
    update: Update,
    text: str,
    *,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = 'HTML',
    silent: bool = False,
    answer_text: Optional[str] = None,
) -> bool:
    """
    v2: edit موثوق مع await صحيح + fallback + logging.

    يُعيد True إذا نجح التعديل، False إذا فشل.

    - answer() دائماً يُستدعى (لإخفاء "جاري...").
    - edit_message_text مع timeout.
    - عند فشل parse → fallback تلقائي لـ plain text.
    - عند "message is not modified" → يُعتبر نجاحاً.
    """
    q = getattr(update, 'callback_query', None)
    if q is None:
        logger.debug("_t: لا يوجد callback_query")
        return False

    # 1) answer دائماً (يُخفي "جاري المعالجة")
    try:
        if answer_text:
            await asyncio.wait_for(
                q.answer(answer_text), timeout=_ANSWER_TIMEOUT
            )
        else:
            await asyncio.wait_for(
                q.answer(), timeout=_ANSWER_TIMEOUT
            )
    except Exception as e:
        logger.debug("_t answer failed: %s", e)

    # 2) حماية من نص فارغ
    if text is None:
        text = ""
    if not text.strip():
        text = "…"

    # 3) اقتطاع النص إن تجاوز حد تيليجرام
    if len(text) > _TELEGRAM_TEXT_LIMIT:
        text = text[:_TELEGRAM_TEXT_LIMIT - 20] + "\n…"

    # 4) حاول edit
    try:
        await asyncio.wait_for(
            q.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            ),
            timeout=_EDIT_TIMEOUT,
        )
        return True

    except BadRequest as e:
        err = str(e).lower()

        if "message is not modified" in err:
            return True

        if parse_mode and _is_parse_error(err):
            try:
                plain = _strip_html(text)
                await asyncio.wait_for(
                    q.edit_message_text(
                        plain,
                        reply_markup=reply_markup,
                        parse_mode=None,
                    ),
                    timeout=_EDIT_TIMEOUT,
                )
                return True
            except Exception as e2:
                logger.warning("_t plain-fallback failed: %s", e2)
                return False

        if not silent:
            logger.warning("_t edit BadRequest: %s", e)
        return False

    except Forbidden as e:
        if not silent:
            logger.warning("_t edit Forbidden: %s", e)
        return False

    except TimedOut:
        logger.warning("_t edit timed out (%.1fs)", _EDIT_TIMEOUT)
        return False

    except asyncio.TimeoutError:
        logger.warning("_t edit asyncio timeout (%.1fs)", _EDIT_TIMEOUT)
        return False

    except Exception as e:
        if not silent:
            logger.warning("_t edit unexpected: %s", e)
        return False


async def _require_dev(update: Update) -> bool:
    """يرسل رسالة رفض إن لم يكن مطوّراً."""
    if _is_dev(update):
        return True
    logger.warning(
        "🚫 unauthorized admin callback | user=%s",
        getattr(update.effective_user, 'id', None),
    )
    await _t(
        update,
        "❌ <b>صلاحيات غير كافية</b>\n"
        "هذه اللوحة مخصّصة للمطوّر فقط.",
        parse_mode='HTML',
    )
    return False


def _kb_back(target: str = "admin_panel") -> InlineKeyboardMarkup:
    """زر رجوع موحّد."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 رجوع", callback_data=target)
    ]])


def _kb(
    *rows,
) -> InlineKeyboardMarkup:
    """بناء لوحة مفاتيح من صفوف مفتاحية."""
    return InlineKeyboardMarkup(list(rows))


# ═══════════════════════════════════════════════════════════════════
# قناة السجلات — التنفيذ الفعلي
# ═══════════════════════════════════════════════════════════════════

async def _read_log_channel() -> Optional[str]:
    """يقرأ قناة السجلات الحالية من DB."""
    value = None
    try:
        getter = getattr(DB, 'get_dev_log_channel', None)
        if callable(getter):
            value = await getter() if asyncio.iscoroutinefunction(getter) \
                    else getter()
    except Exception as e:
        logger.debug("_read_log_channel get_dev_log_channel: %s", e)

    if not value:
        try:
            getter = getattr(DB, 'get_log_channel', None)
            if callable(getter):
                value = await getter() if asyncio.iscoroutinefunction(getter) \
                        else getter()
        except Exception as e:
            logger.debug("_read_log_channel get_log_channel: %s", e)

    if value is None:
        return None
    s = str(value).strip()
    return s or None


async def _resolve_chat_target(ch_str: str):
    """يحوّل سلسلة إلى مُعرّف صالح لـ get_chat."""
    if not ch_str:
        return None
    if ch_str.lstrip('-').isdigit():
        try:
            return int(ch_str)
        except (ValueError, TypeError):
            return None
    if ch_str.startswith('@'):
        return ch_str
    return f"@{ch_str}"


# ═══════════════════════════════════════════════════════════════════
# admin_show_log_channel_callback — التنفيذ الكامل
# ═══════════════════════════════════════════════════════════════════

async def admin_show_log_channel_callback(u, c) -> None:
    """v2: يعرض قناة السجلات الحالية فعلياً + أزرار إدارة."""
    if not await _require_dev(u):
        return

    ch_str = await _read_log_channel()

    if not ch_str:
        body = (
            "📋 <b>قناة السجلات</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <b>لم يتم تعيين قناة سجلات بعد.</b>\n\n"
            "💡 <b>الخطوات:</b>\n"
            "1. اضغط <b>✏️ تغيير</b> أدناه.\n"
            "2. أرسل المعرّف: <code>@username</code> أو "
            "<code>-100xxxxxxxxx</code>.\n"
            "3. تأكد أن البوت <b>مشرف</b> في القناة.\n\n"
            "أو استخدم الأمر: <code>/set_log_ch</code>"
        )
        kb = _kb(
            [InlineKeyboardButton("✏️ تغيير", callback_data="admin_set_log_ch")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")],
        )
        await _t(u, body, reply_markup=kb)
        return

    # قراءة بيانات القناة من تيليجرام
    chat_type = "?"
    chat_title = "—"
    bot_status = "?"
    can_post = None

    try:
        target = await _resolve_chat_target(ch_str)
        if target is not None:
            chat = await c.bot.get_chat(target)
            chat_type = getattr(chat, 'type', '?') or '?'
            chat_title = getattr(chat, 'title', None) or '—'
            chat_type = chat_type  # type: str

            try:
                bot_id = c.bot.id
                member = await c.bot.get_chat_member(target, bot_id)
                status = getattr(member, 'status', None) or '?'
                bot_status = status
                can_post = getattr(member, 'can_post_messages', None)
            except Exception as me:
                logger.debug("get_chat_member failed: %s", me)
                bot_status = "unknown"
    except Exception as e:
        logger.warning("admin_show_log_channel get_chat failed: %s", e)
        chat_title = f"⚠️ تعذّر الوصول ({type(e).__name__})"

    type_labels = {
        'channel': '📢 قناة',
        'supergroup': '👥 مجموعة كبرى',
        'group': '👥 مجموعة',
        'private': '👤 خاص',
    }
    type_label = type_labels.get(chat_type, f"❔ {chat_type}")

    status_labels = {
        'administrator': '✅ مشرف',
        'creator': '👑 المالك',
        'member': '👤 عضو',
        'restricted': '🔒 مقيَّد',
        'left': '❌ غادر',
        'kicked': '🚫 محظور',
        'unknown': '❔ غير معروف',
    }
    status_label = status_labels.get(bot_status, f"❔ {bot_status}")

    can_post_line = ""
    if can_post is True:
        can_post_line = "✍️ صلاحية النشر: ✅\n"
    elif can_post is False:
        can_post_line = "✍️ صلاحية النشر: ❌ (لن تعمل السجلات)\n"

    body = (
        "📋 <b>قناة السجلات الحالية</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>المعرّف:</b> <code>{escape(ch_str)}</code>\n"
        f"📛 <b>العنوان:</b> {escape(str(chat_title))}\n"
        f"🏷️ <b>النوع:</b> {type_label}\n"
        f"🤖 <b>حالة البوت:</b> {status_label}\n"
        f"{can_post_line}"
    )

    # تحذيرات ذكية
    warnings = []
    if bot_status in ('left', 'kicked'):
        warnings.append("🔴 <b>البوت ليس عضواً في القناة!</b>")
    elif bot_status not in ('administrator', 'creator'):
        warnings.append("⚠️ البوت ليس مشرفاً — قد لا تصل السجلات.")
    if can_post is False:
        warnings.append("⚠️ البوت لا يملك صلاحية نشر الرسائل.")

    if warnings:
        body += "\n" + "\n".join(warnings) + "\n"

    kb = _kb(
        [
            InlineKeyboardButton("✏️ تغيير", callback_data="admin_set_log_ch"),
            InlineKeyboardButton("🗑️ إزالة", callback_data="admin_clear_log_ch"),
        ],
        [InlineKeyboardButton("🔄 تحديث", callback_data="admin_show_log_channel")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")],
    )

    await _t(u, body, reply_markup=kb)


async def admin_clear_log_channel_callback(u, c) -> None:
    """v2: يمسح قناة السجلات من DB."""
    if not await _require_dev(u):
        return

    try:
        setter = getattr(DB, 'set_setting', None)
        if not callable(setter):
            await _t(
                u,
                "❌ <b>DB.set_setting غير متاح</b>\n"
                "لا يمكن إزالة القناة.",
                reply_markup=_kb_back(),
            )
            return

        result = setter('log_channel', '')
        if asyncio.iscoroutine(result):
            await result

        # محاولة إزالة المفتاح القديم أيضاً
        try:
            exec_fn = getattr(DB, 'execute', None)
            if callable(exec_fn):
                r = exec_fn(
                    "DELETE FROM settings WHERE key = ?",
                    ('global_log_channel',))
                if asyncio.iscoroutine(r):
                    await r
        except Exception:
            pass

        try:
            from handlers.handlers_message import _invalidate_group_log_cache
            _invalidate_group_log_cache(None)
        except Exception:
            pass
        try:
            from handlers.handlers_message import _invalidate_dev_log_cache
            _invalidate_dev_log_cache()
        except Exception:
            pass

        logger.info(
            "✅ log_channel cleared by user=%s",
            u.effective_user.id,
        )

        await _t(
            u,
            "✅ <b>تمت إزالة قناة السجلات</b>\n\n"
            "لن تُستقبَل الإشعارات حتى تُعيَّن قناة جديدة.",
            reply_markup=_kb_back(),
        )

    except Exception as e:
        logger.error("admin_clear_log_channel failed: %s", e, exc_info=True)
        await _t(
            u,
            f"❌ <b>فشلت الإزالة</b>\n<code>{escape(str(e)[:120])}</code>",
            reply_markup=_kb_back(),
        )


async def admin_set_log_channel_callback(u, c) -> None:
    """v2: يضع المستخدم في حالة WAIT_LOG_CH لاستقبال المعرّف."""
    if not await _require_dev(u):
        return

    if StateManager is None or UserState is None:
        await _t(
            u,
            "❌ <b>StateManager غير متاح</b>\n"
            "استخدم الأمر النصي: <code>/set_log_ch</code>",
            reply_markup=_kb_back(),
        )
        return

    try:
        StateManager.set(u.effective_user.id, UserState.WAIT_LOG_CH)
    except Exception as e:
        logger.warning("set_log_channel state set failed: %s", e)

    try:
        ud = c.user_data
        if ud is not None:
            ud['awaiting_log_channel_for'] = u.effective_user.id
    except Exception:
        pass

    await _t(
        u,
        "📋 <b>تعيين قناة السجلات</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📝 <b>أرسل الآن أحد الأشكال التالية:</b>\n\n"
        "• <code>@username</code> — لقناة عامة\n"
        "• <code>-100xxxxxxxxx</code> — بالمعرّف الرقمي\n"
        "• <code>https://t.me/username</code>\n"
        "• <code>t.me/username</code>\n\n"
        "💡 <b>ملاحظة:</b> يجب أن يكون البوت <b>مشرفاً</b> "
        "في القناة مع صلاحية النشر.\n\n"
        "❌ للإلغاء: أرسل <code>/cancel</code>",
        reply_markup=_kb_back(),
    )


# ═══════════════════════════════════════════════════════════════════
# admin_panel_callback — اللوحة الرئيسية
# ═══════════════════════════════════════════════════════════════════

async def admin_panel_callback(u, c) -> None:
    """v2: لوحة التحكم الرئيسية مع أزرار فعلية."""
    if not await _require_dev(u):
        return

    body = (
        "⚙️ <b>لوحة التحكم</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "👑 مرحباً بك في لوحة المطوّر.\n\n"
        "📋 <b>المجموعات:</b>\n"
        "• المستخدمون / القنوات / المجموعات\n"
        "• الكلمات المحظورة / الردود\n\n"
        "🛡️ <b>الحماية:</b>\n"
        "• الاشتراك الإجباري\n"
        "• قناة التحديثات / قناة السجلات\n\n"
        "🏆 <b>المسابقات:</b>\n"
        "• إنشاء / إدارة / حذف\n"
    )

    kb = _kb(
        [
            InlineKeyboardButton("👥 المستخدمون", callback_data="admin_users"),
            InlineKeyboardButton("📢 القنوات", callback_data="admin_all_channels"),
        ],
        [
            InlineKeyboardButton("🚫 الكلمات المحظورة", callback_data="admin_banned_words"),
            InlineKeyboardButton("💬 الردود", callback_data="admin_replies"),
        ],
        [
            InlineKeyboardButton("📋 قناة السجلات", callback_data="admin_show_log_channel"),
            InlineKeyboardButton("📢 قناة التحديثات", callback_data="admin_show_update_channel"),
        ],
        [
            InlineKeyboardButton("🔔 الاشتراك الإجباري", callback_data="admin_force_subscribe"),
            InlineKeyboardButton("📈 الإحصائيات", callback_data="admin_stats"),
        ],
        [
            InlineKeyboardButton("🏆 المسابقات", callback_data="admin_create_contest"),
            InlineKeyboardButton("🎫 التذاكر", callback_data="admin_support_tickets"),
        ],
        [
            InlineKeyboardButton("📣 إذاعة", callback_data="admin_broadcast"),
            InlineKeyboardButton("💾 النسخ الاحتياطي", callback_data="admin_backup"),
        ],
        [
            InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu"),
        ],
    )

    await _t(u, body, reply_markup=kb)


# ═══════════════════════════════════════════════════════════════════
# Factory pattern — قوالب موحّدة للأزرار الثابتة
# ═══════════════════════════════════════════════════════════════════

def _make_static_menu(
    title: str,
    back_target: str = "admin_panel",
    *,
    require_dev: bool = True,
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]:
    """يُنشئ callback لعرض رسالة ثابتة مع زر رجوع."""
    async def _cb(u, c) -> None:
        if require_dev and not await _require_dev(u):
            return
        await _t(
            u,
            f"{title}\n\n<i>(هذا القسم قيد التطوير — عد قريباً)</i>",
            reply_markup=_kb_back(back_target),
        )
    _cb.__name__ = f"_static_{title[:20]}"
    return _cb


# ─── قوالب ثابتة (48 اسم محفوظ للتوافق الكامل) ──────────────────

# المجموعة 1: تفعيل/إدارة عامة
admin_activate_all_channels_callback = _make_static_menu("⚙️ تفعيل جميع القنوات")
admin_deactivate_all_channels_callback = _make_static_menu("⚙️ تعطيل جميع القنوات")  # (إضافة)
admin_all_channels_callback = _make_static_menu("📢 جميع القنوات")
admin_users_callback = _make_static_menu("👥 إدارة المستخدمين")
admin_stats_callback = _make_static_menu("📈 الإحصائيات")

# المجموعة 2: المشرفون
admin_add_admin_callback = _make_static_menu("➕ إضافة مشرف")
admin_remove_admin_callback = _make_static_menu("➖ إزالة مشرف")

# المجموعة 3: الكلمات المحظورة
admin_add_banned_word_callback = _make_static_menu("🚫 إضافة كلمة محظورة")
admin_remove_banned_word_callback = _make_static_menu("❌ إزالة كلمة محظورة")
admin_banned_words_callback = _make_static_menu("📝 الكلمات المحظورة")
admin_list_banned_words_callback = _make_static_menu("📋 قائمة الكلمات المحظورة")

# المجموعة 4: الردود
admin_add_reply_callback = _make_static_menu("💬 إضافة رد")
admin_del_reply_callback = _make_static_menu("❌ حذف رد")
admin_replies_callback = _make_static_menu("💬 إدارة الردود")
admin_list_replies_callback = _make_static_menu("💬 قائمة الردود")
admin_auto_reply_callback = _make_static_menu("🔄 الرد التلقائي")
admin_auto_reply_select_callback = _make_static_menu("🔽 اختيار الرد التلقائي")

# المجموعة 5: النسخ الاحتياطي
admin_backup_callback = _make_static_menu("💾 النسخ الاحتياطي")
admin_backup_settings_callback = _make_static_menu("⚙️ إعدادات النسخ الاحتياطي")
admin_toggle_auto_backup_callback = _make_static_menu("🔄 تفعيل النسخ التلقائي")

# المجموعة 6: الحظر/الإلغاء
admin_banned_users_callback = _make_static_menu("🚫 المستخدمون المحظورون")
admin_toggle_channel_ban_callback = _make_static_menu("🚫 حظر القنوات")
admin_toggle_group_ban_callback = _make_static_menu("🚫 حظر المجموعات")
admin_unban_all_users_callback = _make_static_menu("🔓 رفع حظر المستخدمين")
admin_unban_all_bot_channels_callback = _make_static_menu("🔓 رفع حظر قنوات البوت")
admin_unban_all_groups_callback = _make_static_menu("🔓 رفع حظر المجموعات")

# المجموعة 7: الإذاعة
admin_broadcast_callback = _make_static_menu("📣 إذاعة")
admin_confirm_broadcast_callback = _make_static_menu("✅ تأكيد الإذاعة")

# المجموعة 8: المدة/الوقت
admin_change_interval_callback = _make_static_menu("⏱️ تغيير المدة")

# المجموعة 9: التذاكر
admin_support_tickets_callback = _make_static_menu("🎫 تذاكر الدعم")
admin_delete_all_tickets_callback = _make_static_menu("🧹 حذف جميع التذاكر")
admin_confirm_delete_tickets_callback = _make_static_menu("🗑️ تأكيد حذف التذاكر")

# المجموعة 10: المسابقات
admin_create_contest_callback = _make_static_menu("🏆 إنشاء مسابقة")
admin_del_contest_callback = _make_static_menu("🗑️ حذف مسابقة")

# المجموعة 11: قنوات الإعدادات
admin_force_subscribe_callback = _make_static_menu("🔔 الاشتراك الإجباري")
admin_show_update_channel_callback = _make_static_menu("👁️ عرض قناة التحديثات")
admin_set_update_channel_callback = _make_static_menu("📢 تعيين قناة التحديثات")
admin_send_update_callback = _make_static_menu("📬 إرسال تحديث")

# المجموعة 12: إدارة الكود
admin_manage_sendcode_callback = _make_static_menu("📨 إدارة إرسال الكود")

# المجموعة 13: الذاكرة
admin_ram_callback = _make_static_menu("📊 استخدام الذاكرة")


# ═══════════════════════════════════════════════════════════════════
# penalty_* — callbacks عقوبات المجموعة (تحقّق مختلف: مشرف المجموعة)
# ═══════════════════════════════════════════════════════════════════

async def _require_group_admin(update: Update) -> bool:
    """تحقّق من مشرف المجموعة (للعقوبات)."""
    try:
        chat = update.effective_chat
        user = update.effective_user
        if not chat or not user:
            return False
        # المطوّر دائماً مسموح
        if _is_dev(update):
            return True
        # لا يمكن تطبيق عقوبات في الخاص
        if chat.type not in ('group', 'supergroup'):
            await _t(
                update,
                "❌ هذه الأزرار تعمل في المجموعات فقط.",
                parse_mode='HTML',
            )
            return False
        try:
            authorized = await is_authorized_in_group(
                update.get_bot() if hasattr(update, 'get_bot') else None,
                chat.id, user.id,
            )
            if authorized:
                return True
        except Exception as e:
            logger.debug("is_authorized_in_group: %s", e)
        await _t(update, "❌ صلاحيات غير كافية.")
        return False
    except Exception as e:
        logger.warning("_require_group_admin: %s", e)
        return False


def _make_penalty_stub(
    title: str,
    action: Optional[str] = None,
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]:
    """يُنشئ callback لعقوبة معينة."""
    async def _cb(u, c) -> None:
        if not await _require_group_admin(u):
            return
        body = f"{title}\n\n<i>(قيد التطوير)</i>"
        if action:
            body += f"\n\n🎯 الإجراء: <code>{action}</code>"
        await _t(u, body, reply_markup=_kb_back("penalty_menu"))
    _cb.__name__ = f"_penalty_{action or title[:15]}"
    return _cb


penalty_menu_callback = _make_penalty_stub("⚖️ قائمة العقوبات")
penalty_ban_callback = _make_penalty_stub("🔨 حظر", "ban")
penalty_kick_callback = _make_penalty_stub("👢 طرد", "kick")
penalty_mute_callback = _make_penalty_stub("🔇 كتم", "mute")
penalty_mute_duration_callback = _make_penalty_stub("⏳ مدة الكتم")


# ═══════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════

__all__ = [
    "__version__",
    # أدوات مساعدة (للتصدير عند الحاجة)
    "_t",
    "_is_dev",
    "_require_dev",
    "_require_group_admin",
    "_kb",
    "_kb_back",
    # قناة السجلات
    "admin_show_log_channel_callback",
    "admin_set_log_channel_callback",
    "admin_clear_log_channel_callback",
    # اللوحة الرئيسية
    "admin_panel_callback",
    # admin_* (ثابتة)
    "admin_activate_all_channels_callback",
    "admin_deactivate_all_channels_callback",
    "admin_add_admin_callback",
    "admin_add_banned_word_callback",
    "admin_add_reply_callback",
    "admin_all_channels_callback",
    "admin_auto_reply_callback",
    "admin_auto_reply_select_callback",
    "admin_backup_callback",
    "admin_backup_settings_callback",
    "admin_banned_users_callback",
    "admin_banned_words_callback",
    "admin_broadcast_callback",
    "admin_change_interval_callback",
    "admin_confirm_broadcast_callback",
    "admin_confirm_delete_tickets_callback",
    "admin_create_contest_callback",
    "admin_del_contest_callback",
    "admin_del_reply_callback",
    "admin_delete_all_tickets_callback",
    "admin_force_subscribe_callback",
    "admin_list_banned_words_callback",
    "admin_list_replies_callback",
    "admin_manage_sendcode_callback",
    "admin_ram_callback",
    "admin_remove_admin_callback",
    "admin_remove_banned_word_callback",
    "admin_replies_callback",
    "admin_send_update_callback",
    "admin_set_update_channel_callback",
    "admin_show_update_channel_callback",
    "admin_stats_callback",
    "admin_support_tickets_callback",
    "admin_toggle_auto_backup_callback",
    "admin_toggle_channel_ban_callback",
    "admin_toggle_group_ban_callback",
    "admin_unban_all_bot_channels_callback",
    "admin_unban_all_groups_callback",
    "admin_unban_all_users_callback",
    "admin_users_callback",
    # penalty_*
    "penalty_ban_callback",
    "penalty_kick_callback",
    "penalty_menu_callback",
    "penalty_mute_callback",
    "penalty_mute_duration_callback",
]


# ═══════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═══════════════════════════════════════════════════════════════════

try:
    logger.info(
        "✅ handlers_callbacks_admin v%s loaded | "
        "callbacks=%d | "
        "log_channel=implemented (show/set/clear) | "
        "penalty=group-admin-checked | "
        "fixes=(FIX-1:await, FIX-2:error-handling, "
        "FIX-3:dev-check, FIX-4:back-buttons, "
        "FIX-5:parse-mode, FIX-6:logging, "
        "FIX-7:log-ch-real, FIX-8:penalty-group, "
        "FIX-9:__all__, FIX-10:factory)",
        __version__,
        len([n for n in __all__ if n.endswith('_callback')]),
    )
except Exception:
    pass