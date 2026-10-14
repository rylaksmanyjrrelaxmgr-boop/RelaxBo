#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_membership.py - مراقبة إضافة/إزالة البوت (v1.3.4-final)
=====================================================================
🆕 v1.3.4-final — CACHE-INVALIDATE-ON-ADD:
    🔴 FIX-M: handle_my_chat_member — إبطال user_cache للمُضيف.
              السبب: عند إضافة البوت لمجموعة، قد يكون المستخدم قد
              زرع cache يحمل groups_count=0 سابقاً. إذا لم يُبطَل،
              اللوحة تُظهر رقماً خاطئاً حتى انتهاء TTL (قد يصل لساعات).
              بعد: user_cache.invalidate(user.id) + creator_id إن وُجد.
              ملاحظة: هذا إجراء دفاعي متكامل مع FIX-GC-2 في
              handlers_command.py (syncgroup) + FIX-GC-1 (live read).

    🟠 FIX-N: _invalidate_user_caches — دالة موحّدة جديدة.
              تُجمّع auth_cache + user_cache + force_sub cache.
              الاستيراد محمي (try/except) — لا يكسر التحميل لو
              cache أو utils لم تُصدَّر بعد.

    🟡 FIX-O: تحديث Header + Load Beacon + __all__ إلى v1.3.4.

🆕 v1.3.3-final — POST-AUDIT FIXES (I–L):
    🔴 FIX-I: _should_send — throttle لـ _prune_recent_reports (60s).
    🟠 FIX-J: _restore_channel_if_soft_deleted — fallback بدون
              removal_reason عند schema قديم.
    🟠 FIX-K: شجرة الإرسال — HTML-strip fallback عند parse error.
    🟠 FIX-L: _ensure_table_exists — warn-once للجدول المفقود.

🆕 v1.3.2-final — POST-AUDIT FIXES (D–H):
    🔴 FIX-D: _restore_channel_if_soft_deleted — banned=0 أيضاً.
    🟠 FIX-E: _recent_reports — حد + LRU.
    🟠 FIX-F: _save_addition_to_db — warning بدل debug.
    🟡 FIX-G: _ensure_table_exists — asyncio.Lock للـ double-check.
    🟡 FIX-H: تصحيح رسالة "N صف في user_channels".

🆕 v1.3.1-final — POST-AUDIT FIXES:
    🔴 FIX-A: _get_effective_log_channel — _sql_get_setting_value().
    🟠 FIX-B: تحسين التسجيل في _restore_channel_if_soft_deleted.
    🟡 FIX-C: _try_get_chat_photo — إضافة "channel".

🆕 v1.3.0-final — استرجاع تلقائي عند إعادة الإضافة.
🆕 v1.2.2-final — إصلاح نوع added_at.
🆕 v1.2.1-final — إصلاح نوع added_at (v1).
🆕 v1.2.0-final — إصلاح PostgreSQL.
🆕 v1.1.0-final — إصلاح قناة السجل.
🆕 v1.0.1-final — إصلاحات بعد المراجعة.
🆕 v1.0.0-final — الإصدار الأول.
=====================================================================
"""

import asyncio
import html
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, List

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.error import BadRequest
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

# ✅ v1.3.4 FIX-N: استيرادات محمية للكاشات (لا تكسر التحميل)
try:
    from cache import user_cache as _user_cache
except ImportError:
    try:
        from cache import UserCache as _UC  # noqa: F401
        _user_cache = None
    except Exception:
        _user_cache = None

try:
    from utils import invalidate_auth_cache as _invalidate_auth_cache
except ImportError:
    def _invalidate_auth_cache(chat_id, user_id=None):
        pass

try:
    from cache import invalidate_user_cache as _invalidate_user_cache_async
except ImportError:
    _invalidate_user_cache_async = None

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# ثوابت
# ═════════════════════════════════════════════════════════════════════

_DEBOUNCE_SECONDS = 30.0
_DEBOUNCE_STALE_AGE = _DEBOUNCE_SECONDS * 20  # 10 دقائق

# ✅ v1.3.2 FIX-E: حد أقصى لعدد الإدخالات في _recent_reports
_MAX_RECENT_REPORTS = 10000

# ✅ v1.3.3 FIX-I: throttle لـ prune (60 ثانية)
_PRUNE_INTERVAL_SEC = 60.0

_OUT_STATUSES = frozenset(('left', 'kicked'))
_IN_STATUSES = frozenset(('member', 'administrator'))

# ✅ v1.3.3 FIX-L: flag warning-once
_table_missing_warned: bool = False


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
    ✅ v1.3.3 FIX-L: warn-once للجدول المفقود على PG/MySQL.

    - PostgreSQL/MySQL: يُنشأ من database_tables.py → فحص فقط
    - SQLite: إنشاء محلي (للتوافق)
    """
    global _table_created, _table_missing_warned

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
                        # ✅ FIX-L: warning مرة واحدة فقط
                        if not _table_missing_warned:
                            _table_missing_warned = True
                            _db_label = (
                                'PostgreSQL'
                                if getattr(DB, 'USE_POSTGRES', False)
                                else 'MySQL'
                            )
                            logger.warning(
                                f"⚠️ bot_addition_log غير موجود على "
                                f"{_db_label} — تأكد من رفع "
                                f"database_tables.py المُصحَّح "
                                f"(سيُكتَم هذا التحذير)")
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
# ✅ v1.3.4 FIX-N: إبطال موحّد لكاشات المستخدمين
# ═════════════════════════════════════════════════════════════════════

async def _invalidate_user_caches(
    user_ids: List[int],
    chat_id: Optional[int] = None,
) -> int:
    """
    ✅ v1.3.4 FIX-N: إبطال موحّد لكل الكاشات المرتبطة بالمستخدم.

    يُبطِل:
      • user_cache (groups_count, has_subscription, ...)
      • auth_cache (إن مررنا chat_id)
      • invalidate_user_cache في cache.py (إن وُجدت)

    الاستيرادات محمية — لا تكسر التحميل لو ملفات لم تُصدَّر بعد.

    Args:
        user_ids: قائمة معرّفات المستخدمين.
        chat_id: معرّف المجموعة (اختياري — لـ auth_cache).

    Returns:
        عدد المستخدمين الذين نجح إبطالهم (تقريبي).
    """
    if not user_ids:
        return 0

    # تنظيف + de-dup
    seen = set()
    clean_ids: List[int] = []
    for uid in user_ids:
        try:
            iuid = int(uid)
        except (TypeError, ValueError):
            continue
        if iuid <= 0:
            continue
        if iuid in seen:
            continue
        seen.add(iuid)
        clean_ids.append(iuid)

    if not clean_ids:
        return 0

    success_count = 0

    # ─── 1) user_cache (الأهم) ───
    for uid in clean_ids:
        invalidated = False

        # الطريق 1: كائن user_cache المستورَد
        if _user_cache is not None:
            try:
                result = _user_cache.invalidate(uid)
                if asyncio.iscoroutine(result):
                    await result
                invalidated = True
            except Exception as e:
                logger.debug(
                    f"_invalidate_user_caches user_cache({uid}): {e}")

        # الطريق 2: دالة invalidate_user_cache المباشرة
        if not invalidated and _invalidate_user_cache_async is not None:
            try:
                result = _invalidate_user_cache_async(uid)
                if asyncio.iscoroutine(result):
                    await result
                invalidated = True
            except Exception as e:
                logger.debug(
                    f"_invalidate_user_caches async_direct({uid}): {e}")

        if invalidated:
            success_count += 1

    # ─── 2) auth_cache (إن مررنا chat_id) ───
    if chat_id is not None:
        for uid in clean_ids:
            try:
                _invalidate_auth_cache(chat_id, uid)
            except Exception as e:
                logger.debug(
                    f"_invalidate_user_caches auth({chat_id},{uid}): {e}")

    return success_count


# ═════════════════════════════════════════════════════════════════════
# Debounce
# ✅ v1.3.2 FIX-E: حد أقصى + pruning LRU
# ✅ v1.3.3 FIX-I: throttle لـ prune (60s)
# ═════════════════════════════════════════════════════════════════════

_recent_reports: Dict[int, float] = {}
_last_prune_ts: float = 0.0


def _should_send(chat_id: int) -> bool:
    global _last_prune_ts

    if chat_id is None:
        return False
    now = time.monotonic()

    # ✅ FIX-I: prune throttled (60s)
    if now - _last_prune_ts >= _PRUNE_INTERVAL_SEC:
        _last_prune_ts = now
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


def _strip_html_tags(s: str) -> str:
    """✅ v1.3.3 FIX-K: fallback عند فشل parse."""
    if not s:
        return s
    try:
        import re as _re
        from html import unescape as _unescape
        return _unescape(_re.sub(r'<[^>]+>', '', s))
    except Exception:
        return s


def _is_parse_error(err_str: str) -> bool:
    """✅ v1.3.3 FIX-K: كشف أخطاء parse HTML."""
    low = (err_str or "").lower()
    return any(k in low for k in (
        "can't parse",
        "can't find end tag",
        "unsupported start tag",
        "unclosed tag",
        "invalid entity",
    ))


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
# ✅ v1.3.3 FIX-J: fallback بدون removal_reason (schema قديم)
# ═════════════════════════════════════════════════════════════════════

async def _restore_channel_if_soft_deleted(chat_id: int) -> int:
    """
    ✅ v1.3.0 (FIX-11): يُلغي علامة الإزالة إذا كانت القناة مُعلَّمة.

    عند إعادة إضافة البوت لقناة كانت مُزالة سابقاً (Soft delete)،
    تُلغى العلامة تلقائياً + تُستعاد القناة مع منشوراتها.

    ✅ v1.3.2 FIX-D: يُصفَّر banned=0 أيضاً.
    ✅ v1.3.3 FIX-J: fallback تلقائي بدون removal_reason عند
        schema قديم لا يحتوي العمود.

    Args:
        chat_id: معرّف القناة/المجموعة في تيليجرام

    Returns:
        عدد الصفوف المُحدَّثة (0 إذا لم تكن مُعلَّمة أو فشل الاستعلام)
    """
    if not chat_id:
        return 0

    # ═══ المسار 1: مع removal_reason (schema حديث) ═══
    try:
        result = await DB.execute(
            "UPDATE user_channels "
            "SET removed_at = NULL, removal_reason = NULL, banned = 0 "
            "WHERE channel_id = ? AND removed_at IS NOT NULL",
            (chat_id,),
        )
        restored = result if isinstance(result, int) else 0

        if restored > 0:
            logger.info(
                f"♻️ استُرجعت القناة {chat_id}: "
                f"removed_at=NULL, banned=0 "
                f"({restored} صف في user_channels)"
            )
        else:
            logger.debug(
                f"ℹ️ القناة {chat_id} لم تكن مُعلَّمة كمُزالة"
            )
        return restored

    except Exception as e:
        err_type = type(e).__name__
        err_msg = str(e)[:200]
        err_low = err_msg.lower()

        # ✅ FIX-J: كشف "عمود مفقود" → fallback
        is_column_missing = (
            "column" in err_low
            and (
                "removal_reason" in err_low
                or "does not exist" in err_low
                or "unknown" in err_low
            )
        ) or (
            "no such column" in err_low
            and "removal_reason" in err_low
        )

        if is_column_missing:
            logger.info(
                f"ℹ️ _restore_channel_if_soft_deleted({chat_id}): "
                f"removal_reason غير موجود (schema قديم) — "
                f"محاولة fallback"
            )
            # ═══ المسار 2: fallback بدون removal_reason ═══
            try:
                result = await DB.execute(
                    "UPDATE user_channels "
                    "SET removed_at = NULL, banned = 0 "
                    "WHERE channel_id = ? AND removed_at IS NOT NULL",
                    (chat_id,),
                )
                restored = result if isinstance(result, int) else 0

                if restored > 0:
                    logger.info(
                        f"♻️ استُرجعت القناة {chat_id} (fallback): "
                        f"removed_at=NULL, banned=0 "
                        f"({restored} صف في user_channels)"
                    )
                else:
                    logger.debug(
                        f"ℹ️ القناة {chat_id} لم تكن مُعلَّمة "
                        f"كمُزالة (fallback)"
                    )
                return restored
            except Exception as e2:
                logger.warning(
                    f"⚠️ _restore_channel_if_soft_deleted "
                    f"fallback({chat_id}): "
                    f"{type(e2).__name__}: {str(e2)[:200]}"
                )
                return 0

        # خطأ آخر — warning
        if "column" in err_low or "unknown" in err_low:
            logger.warning(
                f"⚠️ _restore_channel_if_soft_deleted({chat_id}): "
                f"عمود مفقود في schema — تأكد من migrations "
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
# ✅ v1.3.1 FIX-A: _sql_get_setting_value()
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

    # 4: استعلام مباشر — ✅ FIX-A
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
# ✅ v1.3.2 FIX-F: warning بدل debug
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
        err_type = type(e).__name__
        err_msg = str(e)[:200]
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
            f"https://t.me/{_safe_html(clean_chat_username)}\n"
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
    """
    try:
        photo = getattr(chat, 'photo', None)
        if photo is not None:
            file_id = getattr(photo, 'big_file_id', None)
            if file_id:
                return file_id

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
# ✅ v1.3.3 FIX-K: شجرة إرسال موحّدة مع HTML-strip fallback
# ═════════════════════════════════════════════════════════════════════

async def _send_with_html_fallback(
    bot,
    log_channel,
    text: str,
    keyboard: Optional[InlineKeyboardMarkup],
    photo_id: Optional[str],
    chat_id_for_log,
    user_id_for_log,
    log_scope: str,
) -> bool:
    """
    ✅ v1.3.3 FIX-K: شجرة إرسال موحّدة:
      1. photo + caption (إن وُجدت photo)
      2. text + buttons (HTML)
      3. text + buttons (plain — عند can't parse)
      4. text بدون أزرار (HTML)
      5. text بدون أزرار (plain — عند can't parse)
    """
    sent = False

    # ═══ محاولة 1: صورة + caption ═══
    if photo_id:
        try:
            await bot.send_photo(
                chat_id=log_channel,
                photo=photo_id,
                caption=text,
                parse_mode='HTML',
                reply_markup=keyboard,
            )
            sent = True
            logger.info(
                f"📬 تقرير أُرسل مع صورة "
                f"(chat={chat_id_for_log}, adder={user_id_for_log}, "
                f"scope={log_scope})")
            return True
        except BadRequest as e:
            if _is_parse_error(str(e)):
                logger.warning(
                    f"⚠️ send_photo HTML parse failed — "
                    f"retry plain caption: {str(e)[:100]}")
                try:
                    plain = _strip_html_tags(text)
                    await bot.send_photo(
                        chat_id=log_channel,
                        photo=photo_id,
                        caption=plain,
                        parse_mode=None,
                        reply_markup=keyboard,
                    )
                    sent = True
                    logger.info(
                        f"📬 تقرير أُرسل مع صورة (plain) "
                        f"(chat={chat_id_for_log})")
                    return True
                except Exception as e2:
                    logger.debug(
                        f"send_photo plain fallback failed: {e2}")
                    sent = False
            else:
                logger.debug(
                    f"send_photo failed, fallback to text: {e}")
                sent = False
        except Exception as e:
            logger.debug(
                f"send_photo failed, fallback to text: {e}")
            sent = False

    # ═══ محاولة 2: نص + أزرار (HTML) ═══
    if not sent:
        try:
            await bot.send_message(
                chat_id=log_channel,
                text=text,
                parse_mode='HTML',
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )
            sent = True
            logger.info(
                f"📬 تقرير أُرسل "
                f"(chat={chat_id_for_log}, adder={user_id_for_log}, "
                f"scope={log_scope})")
            return True
        except BadRequest as e:
            if _is_parse_error(str(e)):
                # ═══ محاولة 3: نص + أزرار (plain) ═══
                logger.warning(
                    f"⚠️ send_message HTML parse failed — "
                    f"retry plain: {str(e)[:100]}")
                try:
                    plain = _strip_html_tags(text)
                    await bot.send_message(
                        chat_id=log_channel,
                        text=plain,
                        parse_mode=None,
                        disable_web_page_preview=True,
                        reply_markup=keyboard,
                    )
                    sent = True
                    logger.info(
                        f"📬 تقرير أُرسل (plain) "
                        f"(chat={chat_id_for_log})")
                    return True
                except Exception as e2:
                    logger.debug(
                        f"send_message plain fallback failed: {e2}")
            else:
                logger.debug(
                    f"send_message failed: {e}")
        except Exception as e:
            logger.debug(f"send_message failed: {e}")

    # ═══ محاولة 4: نص بدون أزرار (HTML) ═══
    if not sent:
        try:
            await bot.send_message(
                chat_id=log_channel,
                text=text,
                parse_mode='HTML',
                disable_web_page_preview=True,
            )
            sent = True
            logger.info(
                f"📬 تقرير أُرسل (بدون أزرار) "
                f"(chat={chat_id_for_log})")
            return True
        except BadRequest as e:
            if _is_parse_error(str(e)):
                # ═══ محاولة 5: نص بدون أزرار (plain) ═══
                logger.warning(
                    f"⚠️ send_message (no buttons) HTML parse "
                    f"failed — retry plain: {str(e)[:100]}")
                try:
                    plain = _strip_html_tags(text)
                    await bot.send_message(
                        chat_id=log_channel,
                        text=plain,
                        parse_mode=None,
                        disable_web_page_preview=True,
                    )
                    sent = True
                    logger.info(
                        f"📬 تقرير أُرسل (plain, بدون أزرار) "
                        f"(chat={chat_id_for_log})")
                    return True
                except Exception as e2:
                    logger.error(
                        f"❌ فشل الإرسال حتى مع plain: "
                        f"{type(e2).__name__}: {e2}")
            else:
                logger.error(
                    f"❌ فشل الإرسال (no buttons): "
                    f"{type(e).__name__}: {e}")
        except Exception as e:
            logger.error(
                f"❌ فشل الإرسال (no buttons): "
                f"{type(e).__name__}: {e}")

    if not sent:
        logger.error(
            f"❌ تقرير إضافة البوت لم يُرسل بعد كل المحاولات "
            f"(chat={chat_id_for_log}, scope={log_scope})")

    return sent


# ═════════════════════════════════════════════════════════════════════
# Handler الرئيسي
# ═════════════════════════════════════════════════════════════════════

async def handle_my_chat_member(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    معالج تغيّر حالة البوت في الدردشات.

    ✅ v1.3.0: يستدعي _restore_channel_if_soft_deleted.
    ✅ v1.3.2 FIX-D: الاسترجاع يُصفّر banned=0.
    ✅ v1.3.3 FIX-I: إزالة _prune_recent_reports المُكرَّر (موجود
        داخل _should_send بـ throttle).
    ✅ v1.3.4 FIX-M: إبطال user_cache للمُضيف بعد الحفظ الناجح.
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

    # ✅ FIX-I: _should_send يُشغّل prune داخلياً بـ throttle
    if not _should_send(chat.id):
        return

    # ═══════════════════════════════════════════════════════════
    # استرجاع تلقائي إن كانت مُعلَّمة كمُزالة
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
    save_ok = False
    try:
        save_ok = await _save_addition_to_db(
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
    # ✅ v1.3.4 FIX-M: إبطال user_cache بعد الحفظ الناجح.
    # ═══════════════════════════════════════════════════════════
    # السبب: لو حُفظ الحدث بنجاح، فهناك احتمال أن اللوحة قريباً
    #        ستقرأ user_data المُخزَّن (groups_count) → القيمة
    #        القديمة تبقى إن لم نُبطِل. حتى لو syncgroup هو المصدر
    #        الحقيقي، الإبطال هنا إجراء دفاعي متكامل.
    # ═══════════════════════════════════════════════════════════
    if save_ok:
        try:
            _uids_to_invalidate: List[int] = []
            try:
                if user and getattr(user, 'id', None):
                    _uids_to_invalidate.append(int(user.id))
            except (TypeError, ValueError):
                pass

            if _uids_to_invalidate:
                invalidated = await _invalidate_user_caches(
                    user_ids=_uids_to_invalidate,
                    chat_id=chat.id,
                )
                if invalidated > 0:
                    logger.info(
                        f"♻️ FIX-M: أُبطل كاش {invalidated} مستخدم "
                        f"بعد إضافة البوت للمجموعة {chat.id}"
                    )
        except Exception as e:
            logger.debug(f"FIX-M invalidate user caches: {e}")

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

    # ✅ FIX-K: شجرة إرسال موحّدة مع HTML-strip fallback
    await _send_with_html_fallback(
        bot=context.bot,
        log_channel=log_channel,
        text=text,
        keyboard=keyboard,
        photo_id=photo_id,
        chat_id_for_log=chat.id,
        user_id_for_log=user.id,
        log_scope=log_scope,
    )


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
            "إضافة/إزالة البوت (v1.3.4)"
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
    "_restore_channel_if_soft_deleted",
    "_build_report_text",
    "_build_report_keyboard",
    "_try_get_chat_photo",
    "_send_with_html_fallback",
    "_strip_html_tags",
    "_is_parse_error",
    "_recent_reports",
    "_last_prune_ts",
    "_table_created",
    "_table_lock",
    "_table_missing_warned",
    "_MAX_RECENT_REPORTS",
    "_PRUNE_INTERVAL_SEC",
    "_DEBOUNCE_SECONDS",
    "_DEBOUNCE_STALE_AGE",
    "_OUT_STATUSES",
    "_IN_STATUSES",
    # 🆕 v1.3.4 FIX-N
    "_invalidate_user_caches",
]


# ═════════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "📋 handlers_membership.py v1.3.4 "
        "CACHE-INVALIDATE-ON-ADD loaded | "
        "FIX-M=invalidate-user-cache-on-add | "
        "FIX-N=unified-invalidator | "
        "FIX-I=prune-throttle(%ds) | "
        "FIX-J=restore-fallback-no-removal-reason | "
        "FIX-K=send-html-strip-fallback | "
        "FIX-L=table-missing-warn-once | "
        "FIX-D=restore-banned-0 | "
        "FIX-E=recent-reports-cap(%d) | "
        "FIX-G=table-lock | "
        "FIX-A=sql-get-setting-value | "
        "user_cache_import=%s | "
        "async_invalidator=%s",
        int(_PRUNE_INTERVAL_SEC),
        _MAX_RECENT_REPORTS,
        "yes" if _user_cache is not None else "no",
        "yes" if _invalidate_user_cache_async is not None else "no",
    )
except Exception:
    pass