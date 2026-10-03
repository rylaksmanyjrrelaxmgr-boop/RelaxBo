#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_membership.py - مراقبة إضافة/إزالة البوت (v1.1.0-final)
=====================================================================
🆕 v1.1.0-final — إصلاح قناة السجل:
    ✅ FIX-1: استخدام قناة السجل الخاصة بالمجموعة أولاً
              (fallback للقناة العامة) — يتوافق مع سلوك
              handlers_callback._handle_log_channel
    ✅ FIX-2: دالة جديدة _get_effective_log_channel(chat_id)
              4 طرق fallback بالترتيب الصحيح
    ✅ FIX-3: عرض "النطاق" في التقرير (خاصة/عامة)
    ✅ لا حذف، لا اختصار — نفس بنية v1.0.1

🆕 v1.0.1-final — إصلاحات بعد المراجعة:
    ✅ حذف استيراد CONFIG غير المستخدم
    ✅ حذف _build_chat_link (dead code)
    ✅ إنشاء جدول bot_addition_log مرة واحدة فقط
    ✅ تحسين _get_log_channel (retry أقل)
    ✅ تحسين _try_get_chat_photo (skip للقنوات بدون صورة)

🆕 v1.0.0-final — الإصدار الأول:
    ✅ إرسال تقرير لقناة السجل عند إضافة البوت لمجموعة/قناة
    ✅ يحتوي على: من أضاف، معلومات الدردشة، الوقت
    ✅ Debounce لمنع التكرار (30 ثانية)
    ✅ دعم المجموعات والقنوات (supergroups, channels, groups)
    ✅ حفظ في قاعدة البيانات (جدول bot_addition_log)
    ✅ إرفاق صورة الدردشة إن وُجدت
    ✅ أزرار تفاعلية (فتح المحادثة + معلومات المضيف)
    ✅ معالجة الأخطاء بشكل شامل
    ✅ تنظيف دوري للـ debounce cache
=====================================================================
"""

import html
import logging
import time
from typing import Optional, Dict, Any, Tuple

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import ContextTypes, ChatMemberHandler

from database import DB, TimeUtils

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# ثوابت
# ═════════════════════════════════════════════════════════════════════

# مدة Debounce (بالثواني)
_DEBOUNCE_SECONDS = 30.0

# عمر الإدخال قبل التنظيف التلقائي (بالثواني)
_DEBOUNCE_STALE_AGE = _DEBOUNCE_SECONDS * 20  # 10 دقائق

# حالة البوت قبل الإضافة (يعني "لم يكن موجوداً")
_OUT_STATUSES = frozenset(('left', 'kicked'))

# حالة البوت بعد الإضافة (يعني "أصبح موجوداً")
_IN_STATUSES = frozenset(('member', 'administrator'))


# ═════════════════════════════════════════════════════════════════════
# حالة الجدول (لإنشائه مرة واحدة فقط)
# ═════════════════════════════════════════════════════════════════════

_table_created: bool = False


async def _ensure_table_exists() -> None:
    """
    ✅ v1.0.1: إنشاء جدول bot_addition_log مرة واحدة فقط.
    """
    global _table_created
    if _table_created:
        return
    try:
        await DB.execute(
            "CREATE TABLE IF NOT EXISTS bot_addition_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "chat_id INTEGER NOT NULL, "
            "chat_title TEXT, "
            "chat_type TEXT, "
            "chat_username TEXT, "
            "added_by_id INTEGER NOT NULL, "
            "added_by_name TEXT, "
            "added_by_username TEXT, "
            "bot_status TEXT, "
            "added_at TEXT NOT NULL"
            ")"
        )
        _table_created = True
        logger.debug("✅ جدول bot_addition_log جاهز")
    except Exception as e:
        logger.debug(
            f"_ensure_table_exists: {type(e).__name__}: {e}")
        # لا نُعلّم كمنشأ حتى نجرب مجدداً في المرة التالية


# ═════════════════════════════════════════════════════════════════════
# Debounce — لمنع إرسال تقريرين لنفس الحدث
# ═════════════════════════════════════════════════════════════════════

# مفتاح: chat_id → آخر وقت إرسال (time.monotonic)
_recent_reports: Dict[int, float] = {}


def _should_send(chat_id: int) -> bool:
    """
    يمنع إرسال تقرير مكرر لنفس الدردشة خلال 30 ثانية.

    Returns:
        True إذا يجب الإرسال (وتُحدَّث العلامة الزمنية)
        False إذا كان الحدث حديثاً (debounced)
    """
    if chat_id is None:
        return False
    now = time.monotonic()
    last = _recent_reports.get(chat_id, 0.0)
    if now - last < _DEBOUNCE_SECONDS:
        logger.debug(
            f"⏭️ report debounced for chat {chat_id} "
            f"(elapsed={now - last:.1f}s)")
        return False
    _recent_reports[chat_id] = now
    return True


def _prune_recent_reports() -> int:
    """
    تنظيف الإدخالات القديمة من cache.

    Returns:
        عدد الإدخالات المحذوفة
    """
    removed = 0
    try:
        now = time.monotonic()
        for k in list(_recent_reports.keys()):
            if now - _recent_reports[k] > _DEBOUNCE_STALE_AGE:
                _recent_reports.pop(k, None)
                removed += 1
        if removed:
            logger.debug(
                f"🧹 _recent_reports prune: حُذف {removed} إدخال "
                f"(المتبقي: {len(_recent_reports)})")
    except Exception as e:
        logger.debug(f"_prune_recent_reports: {e}")
    return removed


# ═════════════════════════════════════════════════════════════════════
# دوال مساعدة
# ═════════════════════════════════════════════════════════════════════

def _safe_html(value: Any, default: str = "") -> str:
    """تحويل آمن إلى HTML."""
    try:
        if value is None:
            return default
        return html.escape(str(value))
    except Exception:
        return default


def _build_user_link(
    user_id: int, username: Optional[str] = None
) -> str:
    """بناء رابط للمستخدم (username أو tg://)."""
    try:
        if username:
            clean = str(username).lstrip('@')
            if clean:
                return f"https://t.me/{clean}"
        return f"tg://user?id={user_id}"
    except Exception:
        return f"tg://user?id={user_id}"


# ✅ FIX-2: دالة جديدة — قناة السجل الفعّالة (خاصة → عامة)
async def _get_effective_log_channel(
    chat_id: int
) -> Tuple[Optional[str], str]:
    """
    ✅ v1.1.0 (FIX-1 + FIX-2): جلب قناة السجل الفعّالة.

    الأولوية:
        1. قناة السجل الخاصة بالمجموعة (get_group_log_channel)
        2. قناة السجل العامة عبر DB.get_log_channel()
        3. قناة السجل العامة عبر DB.get_setting()
        4. استعلام مباشر من settings table

    Args:
        chat_id: معرّف الدردشة (المجموعة/القناة)

    Returns:
        tuple (channel_or_None, scope)
        scope في: ('group', 'global', 'none')
    """
    # ═══ الطريقة 1: قناة المجموعة الخاصة ═══
    if chat_id is not None:
        try:
            if hasattr(DB, 'get_group_log_channel'):
                value = await DB.get_group_log_channel(chat_id)
                if value:
                    logger.debug(
                        f"✅ _get_effective_log_channel: "
                        f"قناة مجموعة {chat_id} = {value}")
                    return str(value).strip(), 'group'
        except Exception as e:
            logger.debug(
                f"DB.get_group_log_channel({chat_id}) failed: {e}")

    # ═══ الطريقة 2: القناة العامة عبر get_log_channel ═══
    try:
        if hasattr(DB, 'get_log_channel'):
            value = await DB.get_log_channel()
            if value:
                logger.debug(
                    f"✅ _get_effective_log_channel: "
                    f"قناة عامة = {value}")
                return str(value).strip(), 'global'
    except Exception as e:
        logger.debug(f"DB.get_log_channel() failed: {e}")

    # ═══ الطريقة 3: القناة العامة عبر get_setting ═══
    try:
        if hasattr(DB, 'get_setting'):
            value = await DB.get_setting(
                'log_channel', default='')
            if value:
                logger.debug(
                    f"✅ _get_effective_log_channel: "
                    f"setting عام = {value}")
                return str(value).strip(), 'global'
    except Exception as e:
        logger.debug(f"DB.get_setting failed: {e}")

    # ═══ الطريقة 4: استعلام مباشر ═══
    try:
        row = await DB.fetchone(
            "SELECT value FROM settings "
            "WHERE key='log_channel' LIMIT 1"
        )
        if row:
            if hasattr(row, 'get'):
                value = row.get('value')
            elif isinstance(row, (list, tuple)) and len(row) > 0:
                value = row[0]
            else:
                value = None
            if value:
                logger.debug(
                    f"✅ _get_effective_log_channel: "
                    f"query عام = {value}")
                return str(value).strip(), 'global'
    except Exception as e:
        logger.debug(f"direct query failed: {e}")

    return None, 'none'


# ═════════════════════════════════════════════════════════════════════
# دوال قاعدة البيانات
# ═════════════════════════════════════════════════════════════════════

async def _save_addition_to_db(
    chat_id: int,
    chat_title: str,
    chat_type: str,
    chat_username: Optional[str],
    added_by_id: int,
    added_by_name: str,
    added_by_username: Optional[str],
    bot_status: str,
) -> bool:
    """
    حفظ حدث الإضافة في قاعدة البيانات.
    """
    try:
        # ✅ v1.0.1: إنشاء الجدول مرة واحدة
        await _ensure_table_exists()

        await DB.execute(
            "INSERT INTO bot_addition_log "
            "(chat_id, chat_title, chat_type, chat_username, "
            " added_by_id, added_by_name, added_by_username, "
            " bot_status, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                chat_title or '',
                chat_type or '',
                chat_username or '',
                added_by_id,
                added_by_name or '',
                added_by_username or '',
                bot_status or '',
                TimeUtils.sql_iso(),
            )
        )
        return True
    except Exception as e:
        logger.debug(
            f"_save_addition_to_db failed: "
            f"{type(e).__name__}: {e}")
        return False


# ═════════════════════════════════════════════════════════════════════
# بناء التقرير
# ═════════════════════════════════════════════════════════════════════

def _build_report_text(
    chat,
    user,
    new_status: str,
    log_scope: str = 'global',
) -> str:
    """
    بناء نص التقرير الكامل.

    ✅ v1.1.0: يضيف سطر "نطاق القناة" (خاصة/عامة).
    """
    is_channel = (chat.type == "channel")
    chat_type_emoji = "📡" if is_channel else "👥"
    chat_type_name = "قناة" if is_channel else "مجموعة"

    # اسم الدردشة
    chat_title = _safe_html(chat.title, "بدون اسم")
    chat_id = chat.id
    chat_type = chat.type or 'unknown'
    chat_username = getattr(chat, 'username', None)

    # معلومات المُضيف
    adder_id = user.id
    adder_name = _safe_html(
        getattr(user, 'full_name', None)
        or getattr(user, 'first_name', None)
        or "بدون اسم"
    )
    adder_username = getattr(user, 'username', None)
    adder_username_display = (
        f"@{adder_username}" if adder_username else "—"
    )
    adder_link = _build_user_link(adder_id, adder_username)

    # حالة البوت
    new_status_label = (
        "مشرف ✅"
        if new_status == "administrator"
        else "عضو ✅"
    )

    # ✅ v1.1.0: نطاق قناة السجل
    scope_label = {
        'group': "🔒 خاصة بالمجموعة",
        'global': "🌐 عامة",
        'none': "❓",
    }.get(log_scope, "🌐 عامة")

    # ═══════════════════════════════════════════════════════════
    # بناء النص
    # ═══════════════════════════════════════════════════════════
    text = (
        f"🆕 <b>تمت إضافة البوت إلى {chat_type_name} جديدة!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        f"{chat_type_emoji} <b>معلومات {chat_type_name}:</b>\n"
        f"   • الاسم: <b>{chat_title}</b>\n"
        f"   • المعرف: <code>{chat_id}</code>\n"
        f"   • النوع: <code>{_safe_html(chat_type)}</code>\n"
        f"   • صلاحية البوت: {new_status_label}\n"
        f"   • نطاق السجل: {scope_label}\n"
    )

    # رابط الدردشة (إن وُجد username)
    if chat_username:
        clean_chat_username = str(chat_username).lstrip('@')
        text += (
            f"   • الرابط: "
            f"https://t.me/{clean_chat_username}\n"
        )

    text += (
        "\n"
        f"👤 <b>من أضاف البوت:</b>\n"
        f"   • الاسم: <b>{adder_name}</b>\n"
        f"   • المعرف: {_safe_html(adder_username_display)}\n"
        f"   • الـ ID: <code>{adder_id}</code>\n"
        f"   • رابط: {_safe_html(adder_link)}\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 <b>الوقت:</b> {_safe_html(TimeUtils.mecca_iso())}"
    )

    return text


def _build_report_keyboard(
    chat, user
) -> Optional[InlineKeyboardMarkup]:
    """بناء الأزرار التفاعلية للتقرير."""
    rows = []

    # زر فتح المحادثة (إن وُجد username)
    chat_username = getattr(chat, 'username', None)
    if chat_username:
        try:
            clean = str(chat_username).lstrip('@')
            if clean:
                rows.append([InlineKeyboardButton(
                    "🔗 فتح المحادثة",
                    url=f"https://t.me/{clean}",
                )])
        except Exception:
            pass

    # زر معلومات المُضيف
    try:
        user_username = getattr(user, 'username', None)
        user_link = _build_user_link(user.id, user_username)
        rows.append([InlineKeyboardButton(
            "👤 معلومات المُضيف",
            url=user_link,
        )])
    except Exception:
        pass

    if not rows:
        return None

    try:
        return InlineKeyboardMarkup(rows)
    except Exception:
        return None


async def _try_get_chat_photo(
    bot, chat, chat_type: str
) -> Optional[str]:
    """
    ✅ v1.0.1: محاولة جلب صورة الدردشة (اختياري).

    - للقنوات: photo موجود في كائن chat مباشرة
    - للمجموعات: نحتاج get_chat لجلبه
    """
    try:
        # ✅ للقنوات: chat.photo متوفر عادة
        photo = getattr(chat, 'photo', None)
        if photo is not None:
            file_id = getattr(photo, 'big_file_id', None)
            if file_id:
                return file_id

        # للمجموعات: جلب من API (يُكلف طلب واحد)
        if chat_type in ('group', 'supergroup'):
            try:
                full_chat = await bot.get_chat(chat.id)
                photo = getattr(full_chat, 'photo', None)
                if photo is not None:
                    return getattr(photo, 'big_file_id', None)
            except Exception as e:
                logger.debug(
                    f"_try_get_chat_photo get_chat "
                    f"({chat.id}): {e}")
    except Exception as e:
        logger.debug(f"_try_get_chat_photo: {e}")
    return None


# ═════════════════════════════════════════════════════════════════════
# Handler الرئيسي
# ═════════════════════════════════════════════════════════════════════

async def handle_my_chat_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    يستمع لتغيّر حالة البوت في الدردشات.

    يُرسل تقريراً لقناة السجل عند:
      - إضافة البوت (left/kicked → member/administrator)

    ✅ v1.1.0: يستخدم قناة السجل الخاصة بالمجموعة أولاً،
    ثم العامة كـ fallback.

    ⚠️ لا يُرسل تقريراً عند:
      - الطرد (member → left) — معالَج في _notify_channel_owner_kicked
      - ترقية/تنزيل المشرف (administrator ↔ member)
      - أي تغيير آخر
    """
    result = update.my_chat_member
    if result is None:
        return

    # ═══════════════════════════════════════════════════════════
    # فحص تغيير الحالة
    # ═══════════════════════════════════════════════════════════
    try:
        old_status = result.old_chat_member.status
        new_status = result.new_chat_member.status
    except Exception as e:
        logger.debug(f"my_chat_member status parse: {e}")
        return

    was_out = old_status in _OUT_STATUSES
    is_in = new_status in _IN_STATUSES

    if not (was_out and is_in):
        logger.debug(
            f"⏭️ my_chat_member ignored "
            f"(old={old_status}, new={new_status})")
        return

    # ═══════════════════════════════════════════════════════════
    # استخراج المعلومات
    # ═══════════════════════════════════════════════════════════
    chat = result.chat
    user = result.from_user

    if not chat or not user:
        logger.debug("my_chat_member: no chat or user")
        return

    # تجاهل المحادثات الخاصة
    if chat.type == "private":
        logger.debug("my_chat_member: private chat ignored")
        return

    # ═══════════════════════════════════════════════════════════
    # Debounce
    # ═══════════════════════════════════════════════════════════
    if not _should_send(chat.id):
        return

    # تنظيف دوري
    _prune_recent_reports()

    # ═══════════════════════════════════════════════════════════
    # الحفظ في قاعدة البيانات
    # ═══════════════════════════════════════════════════════════
    try:
        await _save_addition_to_db(
            chat_id=chat.id,
            chat_title=chat.title or '',
            chat_type=chat.type or '',
            chat_username=getattr(chat, 'username', None),
            added_by_id=user.id,
            added_by_name=(
                getattr(user, 'full_name', None) or ''
            ),
            added_by_username=getattr(user, 'username', None),
            bot_status=new_status,
        )
    except Exception as e:
        logger.debug(f"save_addition_to_db outer: {e}")

    # ═══════════════════════════════════════════════════════════
    # ✅ v1.1.0 (FIX-1): جلب قناة السجل الفعّالة
    # ═══════════════════════════════════════════════════════════
    log_channel, log_scope = await _get_effective_log_channel(chat.id)
    if not log_channel:
        logger.debug(
            "No log channel configured; skipping bot-addition report")
        return

    logger.info(
        f"📤 تقرير الإضافة: قناة السجل={log_channel} "
        f"(نطاق={log_scope}) chat={chat.id}")

    # ═══════════════════════════════════════════════════════════
    # بناء التقرير
    # ═══════════════════════════════════════════════════════════
    try:
        text = _build_report_text(
            chat, user, new_status, log_scope=log_scope)
    except Exception as e:
        logger.error(
            f"_build_report_text failed: "
            f"{type(e).__name__}: {e}",
            exc_info=True)
        return

    try:
        keyboard = _build_report_keyboard(chat, user)
    except Exception as e:
        logger.debug(f"_build_report_keyboard: {e}")
        keyboard = None

    # ═══════════════════════════════════════════════════════════
    # محاولة إرفاق صورة الدردشة
    # ═══════════════════════════════════════════════════════════
    photo_id = None
    try:
        photo_id = await _try_get_chat_photo(
            context.bot, chat, chat.type or '')
    except Exception:
        photo_id = None

    # ═══════════════════════════════════════════════════════════
    # الإرسال (سلسلة fallback)
    # ═══════════════════════════════════════════════════════════
    sent = False

    # محاولة 1: مع الصورة
    if photo_id:
        try:
            await context.bot.send_photo(
                chat_id=log_channel,
                photo=photo_id,
                caption=text,
                parse_mode='HTML',
                reply_markup=keyboard,
            )
            sent = True
            logger.info(
                f"📬 تقرير إضافة البوت أُرسل مع صورة "
                f"(chat={chat.id}, adder={user.id}, "
                f"scope={log_scope})")
        except Exception as e:
            logger.debug(
                f"send_photo failed, fallback to text: {e}")
            sent = False

    # محاولة 2: رسالة نصية مع أزرار
    if not sent:
        try:
            await context.bot.send_message(
                chat_id=log_channel,
                text=text,
                parse_mode='HTML',
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )
            sent = True
            logger.info(
                f"📬 تقرير إضافة البوت أُرسل "
                f"(chat={chat.id}, adder={user.id}, "
                f"scope={log_scope})")
        except Exception as e:
            logger.error(
                f"❌ فشل إرسال تقرير قناة السجل: "
                f"{type(e).__name__}: {e}")
            sent = False

    # محاولة 3: بدون أزرار (احتياطي أخير)
    if not sent:
        try:
            await context.bot.send_message(
                chat_id=log_channel,
                text=text,
                parse_mode='HTML',
                disable_web_page_preview=True,
            )
            logger.info(
                f"📬 تقرير أُرسل (بدون أزرار) "
                f"(chat={chat.id}, scope={log_scope})")
        except Exception as e:
            logger.error(
                f"❌ فشل إرسال تقرير حتى بدون أزرار: "
                f"{type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════════
# تسجيل الـ handler
# ═════════════════════════════════════════════════════════════════════

def register_handlers(application) -> None:
    """
    تسجيل الـ handler في Application.

    استخدمها في main.py:
        from handlers_membership import register_handlers
        register_handlers(application)
    """
    try:
        handler = ChatMemberHandler(
            handle_my_chat_member,
            ChatMemberHandler.MY_CHAT_MEMBER,
        )
        application.add_handler(handler, group=-1)
        logger.info(
            "✅ تم تسجيل ChatMemberHandler لمراقبة "
            "إضافة/إزالة البوت")
    except Exception as e:
        logger.error(
            f"❌ فشل تسجيل ChatMemberHandler: "
            f"{type(e).__name__}: {e}",
            exc_info=True)


# ═════════════════════════════════════════════════════════════════════
# __all__ — التصدير الصريح
# ═════════════════════════════════════════════════════════════════════

__all__ = [
    "handle_my_chat_member",
    "register_handlers",
    "_should_send",
    "_prune_recent_reports",
    "_get_effective_log_channel",   # ✅ v1.1.0: دالة جديدة
    "_save_addition_to_db",
    "_ensure_table_exists",
    "_build_report_text",
    "_build_report_keyboard",
    "_try_get_chat_photo",
    "_recent_reports",
    "_table_created",
    "_DEBOUNCE_SECONDS",
    "_DEBOUNCE_STALE_AGE",
    "_OUT_STATUSES",
    "_IN_STATUSES",
]