#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_membership.py - مراقبة إضافة/إزالة البوت (v1.2.2-final)
=====================================================================
🆕 v1.2.2-final — إصلاح نهائي وحاسم لـ added_at:
    ✅ FIX-9: تحويل صريح للتاريخ إلى datetime قبل الإرسال
              (بأي حال، حتى لو أعاد TimeUtils قيمة غير متوقعة)
    ✅ FIX-10: استيراد datetime صراحة في أعلى الملف
    ✅ يحل نهائياً خطأ asyncpg:
              "expected datetime.date or datetime.datetime
               instance, got 'str'"

🆕 v1.2.1-final — إصلاح نوع added_at:
    ✅ FIX-8: استخدام TimeUtils.utc_now() بدلاً من sql_iso()

🆕 v1.2.0-final — إصلاح PostgreSQL (AUTOINCREMENT → SERIAL):
    ✅ FIX-4: SQL صحيح لكل قاعدة بيانات
    ✅ FIX-5: الاعتماد على database_tables.py لإنشاء الجدول
    ✅ FIX-6: _ensure_table_exists أصبحت no-op لـ PostgreSQL/MySQL
    ✅ FIX-7: الإبقاء على الإنشاء لـ SQLite فقط

🆕 v1.1.0-final — إصلاح قناة السجل:
    ✅ FIX-1: استخدام قناة السجل الخاصة بالمجموعة أولاً
    ✅ FIX-2: دالة جديدة _get_effective_log_channel(chat_id)
    ✅ FIX-3: عرض "النطاق" في التقرير

🆕 v1.0.1-final — إصلاحات بعد المراجعة

🆕 v1.0.0-final — الإصدار الأول
=====================================================================
"""

import html
import logging
import time
from datetime import datetime, timezone
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
    ✅ v1.2.0 (FIX-4..7): إنشاء جدول bot_addition_log.

    - PostgreSQL/MySQL: الجدول يُنشأ تلقائياً من database_tables.py
      → نتحقق فقط من وجوده (بدون إنشاء) — no-op تقريباً
    - SQLite: نُبقيه كـ fallback (للتوافق)
    """
    global _table_created
    if _table_created:
        return

    try:
        # ═══════════════════════════════════════════════════════════
        # PostgreSQL/MySQL — الاعتماد على database_tables.py
        # ═══════════════════════════════════════════════════════════
        if getattr(DB, 'USE_POSTGRES', False) or \
           getattr(DB, 'USE_MYSQL', False):
            try:
                if getattr(DB, 'USE_POSTGRES', False):
                    exists = await DB.fetchval(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = 'bot_addition_log' "
                        "AND table_schema = current_schema()"
                    )
                else:  # MySQL
                    exists = await DB.fetchval(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = 'bot_addition_log' "
                        "AND table_schema = DATABASE()"
                    )

                if exists:
                    _table_created = True
                    logger.debug(
                        "✅ جدول bot_addition_log موجود "
                        "(مُنشأ من database_tables.py)")
                    return
                else:
                    logger.warning(
                        "⚠️ bot_addition_log غير موجود على "
                        f"{'PostgreSQL' if getattr(DB, 'USE_POSTGRES', False) else 'MySQL'} "
                        "— تأكد من رفع database_tables.py المُصحَّح")
                    return
            except Exception as e:
                logger.debug(
                    f"_ensure_table_exists check failed: {e}")
                return

        # ═══════════════════════════════════════════════════════════
        # SQLite — الإنشاء المحلي (للتوافق)
        # ═══════════════════════════════════════════════════════════
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
        logger.debug("✅ جدول bot_addition_log جاهز (SQLite)")

    except Exception as e:
        logger.debug(
            f"_ensure_table_exists: {type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════════
# Debounce — لمنع إرسال تقريرين لنفس الحدث
# ═════════════════════════════════════════════════════════════════════

_recent_reports: Dict[int, float] = {}


def _should_send(chat_id: int) -> bool:
    """يمنع إرسال تقرير مكرر لنفس الدردشة خلال 30 ثانية."""
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
    """تنظيف الإدخالات القديمة من cache."""
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


# ═════════════════════════════════════════════════════════════════════
# ✅ FIX-9: تحويل صريح للتاريخ إلى datetime
# ═════════════════════════════════════════════════════════════════════

def _normalize_datetime(value: Any) -> datetime:
    """
    ✅ v1.2.2 (FIX-9): تحويل صريح لأي قيمة زمنية إلى datetime.

    الغرض: ضمان أن `added_at` دائماً datetime، مهما كان نوع المدخل:
      - datetime              → يُعاد كما هو (بعد إزالة tzinfo)
      - str (ISO / SQL)       → يُحلَّل إلى datetime
      - None / قيمة غريبة     → يُرجع datetime.utcnow()

    هذا يمنع خطأ asyncpg:
      "expected datetime.date or datetime.datetime instance, got 'str'"
    """
    try:
        # ── الحالة 1: datetime صريح ──
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                try:
                    value = value.astimezone(timezone.utc).replace(
                        tzinfo=None)
                except Exception:
                    value = value.replace(tzinfo=None)
            return value

        # ── الحالة 2: string (ISO / SQL) ──
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return datetime.now(timezone.utc).replace(tzinfo=None)

            # محاولة استخدام TimeUtils.safe_parse_iso
            try:
                if hasattr(TimeUtils, 'safe_parse_iso'):
                    parsed = TimeUtils.safe_parse_iso(s)
                    if isinstance(parsed, datetime):
                        return parsed
            except Exception:
                pass

            # محاولات يدوية
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d",
            ):
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    continue

            # محاولة fromisoformat
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt
            except (ValueError, TypeError):
                pass

            # fallback: now
            return datetime.now(timezone.utc).replace(tzinfo=None)

        # ── الحالة 3: قيمة غير متوقعة ──
        # محاولة استخدام TimeUtils.utc_now أولاً
        try:
            if hasattr(TimeUtils, 'utc_now'):
                dt = TimeUtils.utc_now()
                if isinstance(dt, datetime):
                    return dt
        except Exception:
            pass

        return datetime.now(timezone.utc).replace(tzinfo=None)

    except Exception as e:
        logger.debug(f"_normalize_datetime failed: {e}")
        return datetime.now(timezone.utc).replace(tzinfo=None)


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

    ✅ v1.2.0: يعتمد على database_tables.py لإنشاء الجدول.
    ✅ v1.2.2 (FIX-9): يمرر datetime دائماً لـ added_at
                       (بعد التحويل الصريح).
    """
    try:
        # ✅ v1.0.1: إنشاء الجدول مرة واحدة (no-op لـ PG/MySQL)
        await _ensure_table_exists()

        # ✅ v1.2.2 (FIX-9): تحويل صريح للتاريخ
        #    أي قيمة → datetime مضمونة
        try:
            now_raw = TimeUtils.utc_now()
        except Exception:
            now_raw = None
        added_at_value = _normalize_datetime(now_raw)

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
                added_at_value,  # ✅ datetime مضمون
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
    """بناء نص التقرير الكامل."""
    is_channel = (chat.type == "channel")
    chat_type_emoji = "📡" if is_channel else "👥"
    chat_type_name = "قناة" if is_channel else "مجموعة"

    chat_title = _safe_html(chat.title, "بدون اسم")
    chat_id = chat.id
    chat_type = chat.type or 'unknown'
    chat_username = getattr(chat, 'username', None)

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

    new_status_label = (
        "مشرف ✅"
        if new_status == "administrator"
        else "عضو ✅"
    )

    scope_label = {
        'group': "🔒 خاصة بالمجموعة",
        'global': "🌐 عامة",
        'none': "❓",
    }.get(log_scope, "🌐 عامة")

    # ═══════════════════════════════════════════════════════════
    # الوقت الحالي (Mecca) — للعرض فقط
    # ═══════════════════════════════════════════════════════════
    try:
        mecca_time_str = TimeUtils.mecca_iso()
    except Exception:
        mecca_time_str = str(datetime.now(timezone.utc))

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
        f"🕐 <b>الوقت:</b> {_safe_html(mecca_time_str)}"
    )

    return text


def _build_report_keyboard(
    chat, user
) -> Optional[InlineKeyboardMarkup]:
    """بناء الأزرار التفاعلية للتقرير."""
    rows = []

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
    """محاولة جلب صورة الدردشة (اختياري)."""
    try:
        photo = getattr(chat, 'photo', None)
        if photo is not None:
            file_id = getattr(photo, 'big_file_id', None)
            if file_id:
                return file_id

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

    if chat.type == "private":
        logger.debug("my_chat_member: private chat ignored")
        return

    # ═══════════════════════════════════════════════════════════
    # Debounce
    # ═══════════════════════════════════════════════════════════
    if not _should_send(chat.id):
        return

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
    # جلب قناة السجل الفعّالة
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

    # محاولة 3: بدون أزرار
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
    """تسجيل الـ handler في Application."""
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
# __all__
# ═════════════════════════════════════════════════════════════════════

__all__ = [
    "handle_my_chat_member",
    "register_handlers",
    "_should_send",
    "_prune_recent_reports",
    "_get_effective_log_channel",
    "_save_addition_to_db",
    "_ensure_table_exists",
    "_normalize_datetime",
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