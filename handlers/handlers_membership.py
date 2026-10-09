#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_membership.py - مراقبة إضافة/إزالة البوت (v1.3.2-final)
=====================================================================
🆕 v1.3.2-final — POST-AUDIT FIXES (D–H):
    🔴 FIX-D: _restore_channel_if_soft_deleted — تصفير banned=0 أيضاً
              عند الاسترجاع. السبب: عند طرد البوت (Forbidden أثناء
              النشر) كان يُضبط banned=1. لاحقاً عند الإزالة يُضبط
              removed_at. عند إعادة الإضافة، كانت removed_at تُصفَّر
              فقط — بينما banned=1 يبقى → القناة تُظهر "مُسترجَعة"
              لكن لا تنشر أبداً (كل الاستعلامات تشترط banned=0).
              الأثر: إرباك المستخدم + شلل النشر بعد الاسترجاع.
    🟠 FIX-E: _recent_reports — إضافة حد أقصى _MAX_RECENT_REPORTS
              مع pruning LRU عند التجاوز. السبب: بدون حد، لو تفاعل
              البوت مع آلاف القنوات دون إضافات فعلية، الذاكرة تتضخم
              (prune TTL الحالي يعمل فقط عند _should_send=True).
    🟠 FIX-F: _save_addition_to_db — رفع مستوى الفشل من debug → warning
              مع نوع الاستثناء. السبب: الفشل المتكرر (schema قديم،
              أعمدة مفقودة) كان صامتاً ويصعب تشخيصه.
    🟡 FIX-G: _ensure_table_exists — asyncio.Lock للـ double-check
              بدل bool فقط. يضمن تزامن صحيح تحت coroutines متعددة.
    🟡 FIX-H: _build_report_text — تصحيح رسالة "منشوراتها (N صف)"
              إلى "N صف في user_channels" (كانت مضلِّلة — N هو عدد
              صفوف user_channels، وليس المنشورات).

🆕 v1.3.1-final — POST-AUDIT FIXES:
    🔴 FIX-A: _get_effective_log_channel — استخدام
              _sql_get_setting_value() بدل الاستعلام الخام.
              السبب: `key` محجوز في PostgreSQL/MySQL، و`value` محجوز
              في MySQL. الاستعلام الخام كان يفشل دائماً على هذه
              المنصات، والخطأ مدفون في try/except → fallback معطّل.
    🟠 FIX-B: _restore_channel_if_soft_deleted — تحسين التسجيل:
              - logger.info عند نجاح استرجاع فعلي
              - logger.warning عند فشل الاستعلام (كان debug)
              - تسجيل تفصيلي لأسباب عدم الاسترجاع
    🟡 FIX-C: _try_get_chat_photo — إضافة "channel" للـ fallback
              عبر bot.get_chat() — لأن بعض تحديثات my_chat_member
              لا تحمل صورة القناة.

🆕 v1.3.0-final — استرجاع تلقائي عند إعادة الإضافة:
    ✅ FIX-11: دالة _restore_channel_if_soft_deleted()
               تُلغي علامة الإزالة (removed_at) عند إعادة إضافة البوت
    ✅ FIX-12: تُستدعى من handle_my_chat_member بعد حفظ الإضافة
    ✅ FIX-13: __all__ محدّث بالدالة الجديدة
    ✅ الفائدة: إذا أعاد المستخدم البوت خلال فترة السماح،
                تُستعاد القناة + جميع منشوراتها تلقائياً

🆕 v1.2.2-final — إصلاح نوع added_at:
    ✅ FIX-9: تحويل صريح للتاريخ إلى datetime قبل الإرسال
    ✅ FIX-10: استيراد datetime صراحة

🆕 v1.2.1-final — إصلاح نوع added_at (v1)
🆕 v1.2.0-final — إصلاح PostgreSQL (AUTOINCREMENT → SERIAL)
🆕 v1.1.0-final — إصلاح قناة السجل (FIX-1..3)
🆕 v1.0.1-final — إصلاحات بعد المراجعة
🆕 v1.0.0-final — الإصدار الأول
=====================================================================
"""

import asyncio
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

# ✅ v1.3.1 FIX-A: استيراد محمي للدالة المساعدة
try:
    from database import _sql_get_setting_value
except ImportError:
    def _sql_get_setting_value() -> str:
        """fallback آمن إن لم تُصدَّر من database."""
        if getattr(DB, "USE_MYSQL", False):
            return "SELECT `value` FROM settings WHERE `key` = ? LIMIT 1"
        if getattr(DB, "USE_POSTGRES", False):
            return 'SELECT "value" FROM settings WHERE "key" = ? LIMIT 1'
        return "SELECT value FROM settings WHERE key = ? LIMIT 1"

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# ثوابت
# ═════════════════════════════════════════════════════════════════════

_DEBOUNCE_SECONDS = 30.0
_DEBOUNCE_STALE_AGE = _DEBOUNCE_SECONDS * 20  # 10 دقائق

# ✅ v1.3.2 FIX-E: حد أقصى لعدد الإدخالات في _recent_reports
_MAX_RECENT_REPORTS = 10000

_OUT_STATUSES = frozenset(('left', 'kicked'))
_IN_STATUSES = frozenset(('member', 'administrator'))


# ═════════════════════════════════════════════════════════════════════
# حالة الجدول
# ✅ v1.3.2 FIX-G: asyncio.Lock للـ double-check
# ═════════════════════════════════════════════════════════════════════

_table_created: bool = False
_table_lock: asyncio.Lock = asyncio.Lock()


async def _ensure_table_exists() -> None:
    """
    ✅ v1.2.0 (FIX-4..7): إنشاء جدول bot_addition_log.
    ✅ v1.3.2 FIX-G: double-checked locking تحت asyncio.Lock.

    - PostgreSQL/MySQL: يُنشأ من database_tables.py → فحص فقط
    - SQLite: إنشاء محلي (للتوافق)
    """
    global _table_created

    if _table_created:
        return

    async with _table_lock:
        if _table_created:
            return

        try:
            if getattr(DB, 'USE_POSTGRES', False) or \
               getattr(DB, 'USE_MYSQL', False):
                try:
                    if getattr(DB, 'USE_POSTGRES', False):
                        exists = await DB.fetchval(
                            "SELECT 1 FROM information_schema.tables "
                            "WHERE table_name = 'bot_addition_log' "
                            "AND table_schema = current_schema()"
                        )
                    else:
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

            # SQLite
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
# Debounce
# ✅ v1.3.2 FIX-E: حد أقصى + pruning LRU
# ═════════════════════════════════════════════════════════════════════

_recent_reports: Dict[int, float] = {}


def _should_send(chat_id: int) -> bool:
    if chat_id is None:
        return False
    now = time.monotonic()

    # ✅ FIX-E: pruning TTL عند كل فحص (ليس فقط بعد النجاح)
    # + cap على الحجم
    if len(_recent_reports) > 0:
        try:
            _prune_recent_reports()
        except Exception:
            pass

    last = _recent_reports.get(chat_id, 0.0)
    if now - last < _DEBOUNCE_SECONDS:
        logger.debug(
            f"⏭️ report debounced for chat {chat_id} "
            f"(elapsed={now - last:.1f}s)")
        return False

    # ✅ FIX-E: إن امتلأ، نُفرغ 25% من الأقدم (LRU بسيط)
    if len(_recent_reports) >= _MAX_RECENT_REPORTS:
        try:
            sorted_items = sorted(
                _recent_reports.items(), key=lambda kv: kv[1])
            remove_n = max(1, len(sorted_items) // 4)
            for k, _ in sorted_items[:remove_n]:
                _recent_reports.pop(k, None)
            logger.warning(
                f"⚠️ _recent_reports تجاوز الحد "
                f"({_MAX_RECENT_REPORTS}) — حُذف {remove_n} "
                f"من الأقدم (المتبقي: {len(_recent_reports)})")
        except Exception as e:
            logger.debug(f"_recent_reports cap prune: {e}")
            _recent_reports.clear()

    _recent_reports[chat_id] = now
    return True


def _prune_recent_reports() -> int:
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
    try:
        if value is None:
            return default
        return html.escape(str(value))
    except Exception:
        return default


def _build_user_link(
    user_id: int, username: Optional[str] = None
) -> str:
    try:
        if username:
            clean = str(username).lstrip('@')
            if clean:
                return f"https://t.me/{clean}"
        return f"tg://user?id={user_id}"
    except Exception:
        return f"tg://user?id={user_id}"


def _normalize_datetime(value: Any) -> datetime:
    """
    ✅ v1.2.2 (FIX-9): تحويل أي قيمة زمنية إلى datetime.
    """
    try:
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                try:
                    value = value.astimezone(timezone.utc).replace(
                        tzinfo=None)
                except Exception:
                    value = value.replace(tzinfo=None)
            return value

        if isinstance(value, str):
            s = value.strip()
            if not s:
                return datetime.now(timezone.utc).replace(tzinfo=None)

            try:
                if hasattr(TimeUtils, 'safe_parse_iso'):
                    parsed = TimeUtils.safe_parse_iso(s)
                    if isinstance(parsed, datetime):
                        return parsed
            except Exception:
                pass

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

            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt
            except (ValueError, TypeError):
                pass

            return datetime.now(timezone.utc).replace(tzinfo=None)

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


# ═════════════════════════════════════════════════════════════════════
# ✅ v1.3.0 (FIX-11): استرجاع تلقائي للقناة المُعلَّمة كمُزالة
# ✅ v1.3.1 FIX-B: تحسين التسجيل
# ✅ v1.3.2 FIX-D: تصفير banned=0 أيضاً + تصحيح رسالة اللوج
# ═════════════════════════════════════════════════════════════════════

async def _restore_channel_if_soft_deleted(chat_id: int) -> int:
    """
    ✅ v1.3.0 (FIX-11): يُلغي علامة الإزالة إذا كانت القناة مُعلَّمة.

    عند إعادة إضافة البوت لقناة كانت مُزالة سابقاً (Soft delete)،
    تُلغى العلامة تلقائياً + تُستعاد القناة مع منشوراتها.

    ✅ v1.3.2 FIX-D: يُصفَّر banned=0 أيضاً.
       السبب: عند طرد البوت (Forbidden أثناء النشر) يُضبط banned=1.
       لاحقاً عند الإزالة يُضبط removed_at. عند إعادة الإضافة،
       كانت removed_at تُصفَّر فقط → banned=1 يبقى → القناة لا تنشر
       أبداً. الآن: استرجاع كامل (removed_at=NULL, banned=0).

    ✅ v1.3.1 FIX-B: التسجيل رُفع لمستوى أوضح:
       - نجاح حقيقي → logger.info (كان debug)
       - فشل استعلام → logger.warning (كان debug في caller)
       - عدم وجود علامة → logger.debug (طبيعي، لا يهم)

    Args:
        chat_id: معرّف القناة/المجموعة في تيليجرام

    Returns:
        عدد الصفوف المُحدَّثة (0 إذا لم تكن مُعلَّمة أو فشل الاستعلام)
    """
    if not chat_id:
        return 0

    try:
        # ✅ FIX-D: تصفير banned=0 مع removed_at=NULL
        result = await DB.execute(
            "UPDATE user_channels "
            "SET removed_at = NULL, removal_reason = NULL, banned = 0 "
            "WHERE channel_id = ? AND removed_at IS NOT NULL",
            (chat_id,),
        )

        # PG/MySQL/SQLite: DB.execute يُرجع rowcount (int)
        restored = 0
        if isinstance(result, int):
            restored = result

        if restored > 0:
            # ✅ FIX-D: رسالة دقيقة — N صف في user_channels (ليس منشورات)
            logger.info(
                f"♻️ استُرجعت القناة {chat_id}: "
                f"removed_at=NULL, banned=0 ({restored} صف في user_channels)"
            )
        else:
            logger.debug(
                f"ℹ️ القناة {chat_id} لم تكن مُعلَّمة كمُزالة"
            )

        return restored

    except Exception as e:
        # ✅ FIX-B: warning بدل debug — الأخطاء الفعلية يجب أن تظهر
        err_type = type(e).__name__
        err_msg = str(e)[:200]
        # كشف شائع: عمود غير موجود (schema قديم)
        if "column" in err_msg.lower() or "unknown" in err_msg.lower():
            logger.warning(
                f"⚠️ _restore_channel_if_soft_deleted({chat_id}): "
                f"عمود removed_at/removal_reason/banned غير موجود "
                f"في schema — تأكد من migrations "
                f"({err_type}: {err_msg})"
            )
        else:
            logger.warning(
                f"⚠️ _restore_channel_if_soft_deleted({chat_id}): "
                f"{err_type}: {err_msg}"
            )
        return 0


# ═════════════════════════════════════════════════════════════════════
# قناة السجل الفعّالة
# ✅ v1.3.1 FIX-A: استخدام _sql_get_setting_value() في المسار الأخير
# ═════════════════════════════════════════════════════════════════════

async def _get_effective_log_channel(
    chat_id: int
) -> Tuple[Optional[str], str]:
    """
    جلب قناة السجل الفعّالة.
    الأولوية: مجموعة → عامة (4 طرق fallback)
    """
    # 1: قناة المجموعة
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

    # 2: القناة العامة
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

    # 3: get_setting
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

    # 4: استعلام مباشر — ✅ FIX-A: عبر _sql_get_setting_value()
    try:
        row = await DB.fetchone(
            _sql_get_setting_value(),
            ("log_channel",),
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
# حفظ في قاعدة البيانات
# ✅ v1.3.2 FIX-F: رفع مستوى الفشل من debug → warning
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

    ✅ v1.2.2 (FIX-9): يمرر datetime دائماً لـ added_at.
    ✅ v1.3.2 FIX-F: الفشل يُسجَّل كـ warning مع نوع الاستثناء.
    """
    try:
        await _ensure_table_exists()

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
                added_at_value,
            )
        )
        return True
    except Exception as e:
        # ✅ FIX-F: warning بدل debug — الفشل المتكرر يجب أن يظهر
        err_type = type(e).__name__
        err_msg = str(e)[:200]
        # كشف خاص: جدول مفقود (schema قديم على PG/MySQL)
        if "does not exist" in err_msg.lower() or \
           "no such table" in err_msg.lower():
            logger.warning(
                f"⚠️ _save_addition_to_db({chat_id}): "
                f"جدول bot_addition_log غير موجود — "
                f"تأكد من database_tables.py "
                f"({err_type}: {err_msg})"
            )
        else:
            logger.warning(
                f"⚠️ _save_addition_to_db({chat_id}): "
                f"{err_type}: {err_msg}"
            )
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
    """
    ✅ v1.3.1 FIX-C: توسيع fallback ليشمل "channel" أيضاً.
    بعض تحديثات my_chat_member لا تحمل صورة القناة/المجموعة،
    لذا نجلبها عبر get_chat في هذه الحالة.
    """
    try:
        photo = getattr(chat, 'photo', None)
        if photo is not None:
            file_id = getattr(photo, 'big_file_id', None)
            if file_id:
                return file_id

        # ✅ FIX-C: channel + group + supergroup
        if chat_type in ('group', 'supergroup', 'channel'):
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
    معالج تغيّر حالة البوت في الدردشات.

    يُرسل تقريراً لقناة السجل عند الإضافة.
    ✅ v1.3.0: يستدعي _restore_channel_if_soft_deleted تلقائياً.
    ✅ v1.3.2 FIX-D: الاسترجاع يُصفّر banned=0 أيضاً.
    """
    result = update.my_chat_member
    if result is None:
        return

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

    chat = result.chat
    user = result.from_user

    if not chat or not user:
        logger.debug("my_chat_member: no chat or user")
        return

    if chat.type == "private":
        logger.debug("my_chat_member: private chat ignored")
        return

    if not _should_send(chat.id):
        return

    _prune_recent_reports()

    # ═══════════════════════════════════════════════════════════
    # ✅ v1.3.0 (FIX-11) + v1.3.2 (FIX-D):
    # استرجاع تلقائي إن كانت مُعلَّمة كمُزالة (مع banned=0)
    # ═══════════════════════════════════════════════════════════
    try:
        restored = await _restore_channel_if_soft_deleted(chat.id)
        if restored > 0:
            logger.debug(
                f"♻️ restore succeeded: {restored} rows for chat={chat.id}"
            )
    except Exception as e:
        logger.debug(f"restore soft-deleted (outer): {e}")

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

    photo_id = None
    try:
        photo_id = await _try_get_chat_photo(
            context.bot, chat, chat.type or '')
    except Exception:
        photo_id = None

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

    # محاولة 2: نصية + أزرار
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
# التسجيل
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
            "إضافة/إزالة البوت (v1.3.2)"
        )
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
    "_restore_channel_if_soft_deleted",   # ✅ v1.3.0 + v1.3.2 FIX-D
    "_build_report_text",
    "_build_report_keyboard",
    "_try_get_chat_photo",
    "_recent_reports",
    "_table_created",
    "_table_lock",                         # ✅ v1.3.2 FIX-G
    "_MAX_RECENT_REPORTS",                 # ✅ v1.3.2 FIX-E
    "_DEBOUNCE_SECONDS",
    "_DEBOUNCE_STALE_AGE",
    "_OUT_STATUSES",
    "_IN_STATUSES",
]