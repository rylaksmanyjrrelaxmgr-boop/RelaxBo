#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers_channels_list.py - واجهة قائمة القنوات مع حالتها (v2.1.8)
================================================================================
🆕 v2.1.8 (UPDATES-CHANNEL-STATE-COLLISION-FIX):
    🔴 FIX-STATE-3 (CRITICAL): حذف WAIT_UPDATE_CH و WAIT_UPDATE_CHANNEL
        من _CHANNEL_ADD_STATES.

        السبب الجذري لباغ "قناة التحديثات تظهر كقناة نشطة":
          1. add_channel_from_message مُسجَّل في group=-1
             (يعمل قبل كل handlers أخرى).
          2. كان _CHANNEL_ADD_STATES يحتوي على:
                "WAIT_UPDATE_CH", "WAIT_UPDATE_CHANNEL"
          3. _is_channel_add_state(state_str) في هذا السياق → True.
          4. _user_has_pending_state → False (لأن الحالة "معروفة").
          5. المعالج لا يتخطى → يُنفّذ DB.add_channel(..., set_active=True).
          6. يستدعي _clear_user_state(user_id) → يمسح الحالة.
          7. handlers_command.handle_text لا يرى أي حالة → لا يكتب
             في settings.updates_channel.

        الإصلاح: إزالة الحالتين من _CHANNEL_ADD_STATES. قناة
        التحديثات تُعالج في handlers_command.handle_text حصراً.

    🟡 FIX-STATE-4: إضافة ملاحظة صريحة تحت _CHANNEL_ADD_STATES تُوضّح
        أن الحالات المدرجة تُخصّ إضافة **قناة نشطة** فقط.

🆕 v2.1.7 (SECURITY-COMPLETENESS-FIX) — محفوظ.
🆕 v2.1.6 (BACK-BUTTON-FIX) — محفوظ.
🆕 v2.1.5 (UNIFIED-PREFIXES) — محفوظ.
🆕 v2.1.4 (PTB-V20-MULTI-HANDLER-FIX) — محفوظ.
================================================================================
"""

import functools
import html as _html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, MessageHandler, filters,
    ApplicationHandlerStop,
)

logger = logging.getLogger(__name__)


# =====================================================================
# 🆕 v2.1.7 FIX-ESC-1: HTML escape helper
# =====================================================================

_CONTROL_CHARS_MAP = {i: ' ' for i in range(0x20)}
_CONTROL_CHARS_MAP[0x7f] = ' '


def _esc(value, default: str = "") -> str:
    """
    🆕 v2.1.7 FIX-ESC-1: تنظيف + escape للاستخدام داخل HTML.

    - None/"" → default (بدون escape، للثقة).
    - غير ذلك → إزالة control chars + html.escape.
    """
    if value is None or value == "":
        return default
    try:
        return _html.escape(
            str(value).translate(_CONTROL_CHARS_MAP)
        )
    except Exception:
        return default


# =====================================================================
# 🆕 v2.1.4 — FIX-CB1: إيقاف PTB v20+ بعد أول handler مطابق
# =====================================================================

def _stop_after(fn):
    """
    🔴 FIX-CB1 (v2.1.4): يضمن أن PTB v20+ لا ينفّذ handlers لاحقة
    على نفس الـ update.
    """
    @functools.wraps(fn)
    async def _wrapped(update, context):
        try:
            await fn(update, context)
        except ApplicationHandlerStop:
            raise
        except Exception:
            logger.exception(
                f"❌ {fn.__name__} فشل — سيتم إيقاف المعالجات اللاحقة")
            raise ApplicationHandlerStop
        raise ApplicationHandlerStop
    return _wrapped


# =====================================================================
# استيراد آمن
# =====================================================================

try:
    from database import DB, TimeUtils
except ImportError:
    logger.error("❌ فشل استيراد database.py")
    DB = None
    TimeUtils = None


try:
    from utils import StateManager, UserState
    _STATE_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ StateManager/UserState غير متاح")
    StateManager = None
    UserState = None
    _STATE_AVAILABLE = False


# 🆕 v2.1.6 FIX-BACK-1: استيراد CB للاستخدام الديناميكي
try:
    from utils import CB as _CB_REF
    _CB_AVAILABLE = True
except ImportError:
    _CB_REF = None
    _CB_AVAILABLE = False


try:
    from utils.keyboards import get_back_button
except (ImportError, AttributeError):
    def get_back_button():
        return InlineKeyboardButton("↩️ رجوع", callback_data="main_menu")


try:
    from handlers_callback_base import _row_to_dict as _row_to_dict_shared
    _HAS_SHARED_ROW_TO_DICT = True
except ImportError:
    try:
        from handlers.handlers_callback_base import (
            _row_to_dict as _row_to_dict_shared)
        _HAS_SHARED_ROW_TO_DICT = True
    except ImportError:
        _row_to_dict_shared = None
        _HAS_SHARED_ROW_TO_DICT = False


# =====================================================================
# 🆕 v2.1.7 FIX-PATTERN-1: helpers ديناميكية لبناء patterns
# =====================================================================

def _cb_value(attr: str, fallback: Optional[str] = None) -> Optional[str]:
    """قراءة قيمة CB.* بأمان."""
    if _CB_AVAILABLE and _CB_REF is not None:
        try:
            v = getattr(_CB_REF, attr, None)
            if isinstance(v, str) and v:
                return v
        except Exception:
            pass
    return fallback


def _build_exact_pattern(*literals: str) -> str:
    """نمط مطابقة تامة: `^(name1|name2|...)$`."""
    names = sorted({n for n in literals if isinstance(n, str) and n})
    if not names:
        return r"$^"  # لا يطابق شيئاً
    return r"^(" + "|".join(re.escape(n) for n in names) + r")$"


def _build_prefixed_pattern(*literals: str) -> str:
    """نمط مع معامل: `^(name1|name2|...):`."""
    names = sorted({n for n in literals if isinstance(n, str) and n})
    if not names:
        return r"$^"
    return r"^(" + "|".join(re.escape(n) for n in names) + r"):"


# =====================================================================
# 🆕 v2.1.6 FIX-BACK-1 + v2.1.7 FIX-PATTERN-1: pattern القائمة الرئيسية
# =====================================================================

def _build_main_menu_pattern() -> str:
    """
    🆕 v2.1.6 FIX-BACK-1: يبني pattern ديناميكي يجمع:
      • الأسماء الحرفية المعروفة (main_menu / back / home / ...).
      • قيم CB.MAIN / CB.BACK / CB.MENU / CB.HOME من utils.py.

    الأمان: `re.escape()` لكل عنصر — لا حقن regex.
    """
    names = {
        "main_menu",
        "back_to_main",
        "back_to_main_menu",
        "home",
        "back",
        "menu",
        "start_menu",
    }

    if _CB_AVAILABLE and _CB_REF is not None:
        for attr in (
            "MAIN", "BACK", "MENU", "HOME",
            "BACK_TO_MAIN", "BACK_MAIN", "BACK_BTN",
            "MAIN_MENU", "HOME_MENU",
        ):
            try:
                v = getattr(_CB_REF, attr, None)
                if isinstance(v, str) and v:
                    names.add(v)
            except Exception:
                continue

    pattern = _build_exact_pattern(*names)
    logger.debug(
        "🔍 [v2.1.8] main_menu pattern = %s | CB=%s",
        pattern,
        "available" if _CB_AVAILABLE else "unavailable",
    )
    return pattern


_MAIN_MENU_PATTERN = _build_main_menu_pattern()

# 🆕 v2.1.7 FIX-PATTERN-1: أنماط ديناميكية لكل handler
_CH_ADD_PATTERN = _build_exact_pattern(
    "add_channel", "ch_add",
    _cb_value("CH_ADD", "ch_add"),
)
_CH_LIST_PATTERN = _build_exact_pattern(
    "ch_list",
    _cb_value("CH_LIST", "ch_list"),
)
_POST_ADD_PATTERN = _build_exact_pattern(
    "post_add", "posts_add",
    _cb_value("POST_ADD", "post_add"),
)
_CH_SEL_PATTERN = _build_prefixed_pattern(
    "ch_sel", "ch_select",
    _cb_value("CH_SEL", "ch_sel"),
)
_CH_STATS_PATTERN = _build_prefixed_pattern(
    "ch_stats", "ch_info",
    _cb_value("CH_STATS", "ch_stats"),
)
_CH_DEL_PATTERN = _build_prefixed_pattern(
    "ch_del", "ch_delete_execute",
    _cb_value("CH_DEL", "ch_del"),
)
_CH_DEL_CONFIRM_PATTERN = _build_prefixed_pattern(
    "ch_del_confirm", "ch_delete_confirm",
)
_CH_DEL_MENU_PATTERN = _build_exact_pattern(
    "ch_del_menu", "ch_delete_menu",
)
_CH_RECYCLE_PATTERN = _build_prefixed_pattern("ch_recycle")
_CH_SCHEDULE_PATTERN = _build_prefixed_pattern("ch_schedule")
_CH_SCHED_SET_PATTERN = _build_prefixed_pattern("ch_sched_set")


# =====================================================================
# 🔴 FIX-N1: _is_banned() موحّد
# =====================================================================

def _safe_int(value, default: int = 0) -> int:
    """تحويل آمن إلى int — يتعامل مع int/str/None/Decimal."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_banned(ch_row: dict) -> bool:
    """🔴 FIX-N1: فحص موحّد لحقل 'banned'."""
    if not ch_row:
        return False
    return _safe_int(ch_row.get("banned"), 0) == 1


# =====================================================================
# 🔴 v2.1.8 FIX-STATE-3: حالات إضافة القناة النشطة فقط
# =====================================================================
# ⚠️ مهم جداً: هذه القائمة تُحدّد الحالات التي يُسمح فيها لهذا الملف
#    بمعالجة رسالة نصية كـ "محاولة إضافة قناة نشطة".
#
#    ❌ لا تُضِف: WAIT_UPDATE_CH أو WAIT_UPDATE_CHANNEL
#       لأن هذه الحالات مُخصّصة لقناة التحديثات (تُعالَج في
#       handlers_command.handle_text وتُخزَّن في settings.updates_channel).
#       وجودها هنا يُسبّب:
#         1. add_channel_from_message يستقبل الرسالة (group=-1)
#         2. يرى WAIT_UPDATE_CH → يعتقد أنه في سياق "إضافة قناة"
#         3. يُضيف القناة كـ user_channels + set_active=True
#         4. يمسح الحالة → handlers_command لا يراها أبداً
#       النتيجة: قناة التحديثات تظهر كقناة نشطة!
#
#    ✅ القائمة تحتوي فقط على: قنوات النشر النشطة.
# =====================================================================
_CHANNEL_ADD_STATES = (
    "WAIT_CHANNEL",
    "WAIT_ADD_CHANNEL",
    # 🔴 v2.1.8 FIX-STATE-3: REMOVED
    # "WAIT_UPDATE_CH",        ← محذوف
    # "WAIT_UPDATE_CHANNEL",   ← محذوف
)


# =====================================================================
# 0. أدوات مساعدة
# =====================================================================

def _db_ready() -> bool:
    """✅ v2.0.0: فحص موحّد لجهوزية DB."""
    if DB is None:
        logger.error("❌ DB غير مهيأة — تخطي handler")
        return False
    return True


def _row_to_dict(row) -> dict:
    """✅ v2.0.3 FIX-D + 🆕 v2.1.1 FIX-3."""
    if _HAS_SHARED_ROW_TO_DICT and _row_to_dict_shared is not None:
        result = _row_to_dict_shared(row)
        if result is None:
            return {}
        return result
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    try:
        if hasattr(row, 'keys'):
            return {k: row[k] for k in row.keys()}
    except Exception:
        pass
    try:
        return dict(row)
    except (TypeError, ValueError):
        return {}


def _get_state_str(user_id: int) -> str:
    if not _STATE_AVAILABLE or StateManager is None:
        return ""
    try:
        state = StateManager.get(user_id)
        if state is None:
            return ""
        return str(state) or ""
    except Exception as e:
        logger.debug(f"_get_state_str({user_id}): {e}")
        return ""


def _is_channel_add_state(state_str: str) -> bool:
    if not state_str:
        return False
    return any(s in state_str for s in _CHANNEL_ADD_STATES)


def _clear_user_state(user_id: int) -> None:
    if not _STATE_AVAILABLE or StateManager is None:
        return
    try:
        StateManager.clear(user_id)
        logger.debug(f"🔄 state cleared for user {user_id}")
    except Exception as e:
        logger.debug(f"_clear_user_state({user_id}): {e}")


def _set_user_state(user_id: int, state_value) -> bool:
    """
    🆕 v2.1.7 FIX-STATE-1/2: تعيين حالة بأمان.

    Returns:
        True إن نُفّذ التعيين، False إن كانت الحالة غير متاحة.
    """
    if not _STATE_AVAILABLE or StateManager is None:
        return False
    if state_value is None:
        return False
    try:
        StateManager.set(user_id, state_value)
        return True
    except Exception as e:
        logger.debug(f"_set_user_state({user_id}, {state_value}): {e}")
        return False


def _user_has_pending_state(user_id: int) -> bool:
    if not _STATE_AVAILABLE or StateManager is None:
        return False
    try:
        state = StateManager.get(user_id)
        if state is None:
            return False

        state_str = str(state) or ""
        if _is_channel_add_state(state_str):
            return False
        if state_str in ("UserState.NONE", "NONE"):
            return False
        none_member = getattr(UserState, "NONE", None) if UserState else None
        if none_member is not None:
            if state is none_member or state == none_member:
                return False
        return True
    except Exception as e:
        logger.debug(f"_user_has_pending_state({user_id}): {e}")
        return False


async def _safe_answer(query, text: str = None, show_alert: bool = False) -> None:
    try:
        if text is not None:
            await query.answer(text, show_alert=show_alert)
        else:
            await query.answer()
    except Exception as e:
        logger.debug(f"_safe_answer: {e}")


def _format_date(dt_value) -> str:
    """
    🆕 v2.1.7 FIX-DATE-1: تنسيق التاريخ بتوقيت مكة.
    """
    if not dt_value:
        return "غير محدد"
    if TimeUtils is None:
        return str(dt_value)
    try:
        dt = TimeUtils.safe_parse_iso(dt_value)
        if not dt:
            return "غير محدد"

        utc_to_mecca = getattr(TimeUtils, "utc_to_mecca", None)
        if callable(utc_to_mecca):
            try:
                return utc_to_mecca(dt).strftime("%Y-%m-%d %H:%M")
            except Exception as e:
                logger.debug(f"utc_to_mecca فشل، fallback: {e}")

        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        local_dt = dt + timedelta(hours=3)
        return local_dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(dt_value)


async def _get_active_channel_id(user_id: int) -> Optional[int]:
    try:
        val = await DB.fetchval(
            "SELECT active_channel FROM users WHERE user_id = ?",
            (user_id,),
            default=None,
        )
        if val is None:
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None
    except Exception as e:
        logger.debug(f"_get_active_channel_id({user_id}): {e}")
        return None


# =====================================================================
# 🔴 FIX-N2: badge
# =====================================================================

def _short_channel_badge(ch: dict) -> str:
    try:
        ch_tele = ch.get("channel_id")
        if ch_tele is not None:
            s = str(ch_tele).lstrip("-")
            if len(s) >= 4:
                return f"#{s[-4:]}"
            elif s:
                return f"#{s.zfill(4)}"
        ch_db = ch.get("channel_db_id")
        if ch_db is not None:
            s = str(ch_db).lstrip("-")
            if len(s) >= 3:
                return f"#{s[-3:]}"
            elif s:
                return f"#{s.zfill(3)}"
    except Exception:
        pass
    return ""


def _truncate_name(name: str, max_len: int = 22) -> str:
    if not name:
        return "قناة بدون اسم"
    s = str(name).strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


# =====================================================================
# 1. عرض قائمة القنوات
# =====================================================================

async def show_channels_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _db_ready():
        return

    user_id = update.effective_user.id
    channels = await _get_channels_with_stats(user_id)

    if not channels:
        text = (
            "📭 <b>لا توجد قنوات</b>\n\n"
            "أضف أول قناة لك بالنقر على زر <b>➕ إضافة قناة</b>"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة قناة", callback_data="ch_add")],
            [InlineKeyboardButton("↩️ رجوع للقائمة الرئيسية", callback_data="main_menu")],
        ])
    else:
        active_channel_id = await _get_active_channel_id(user_id)
        text = _build_channels_text(channels, active_channel_id)
        keyboard = _build_channels_keyboard(channels, active_channel_id)

    if update.callback_query:
        await _safe_answer(update.callback_query)
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=keyboard, parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"edit_message_text: {e}")
            try:
                if update.callback_query.message is not None:
                    await update.callback_query.message.reply_text(
                        text, reply_markup=keyboard, parse_mode="HTML",
                    )
                else:
                    logger.debug(
                        "show_channels_list: callback_query.message is None "
                        "— skip fallback reply"
                    )
            except Exception as e2:
                logger.error(f"reply_text fallback: {e2}")
    else:
        try:
            if update.message is not None:
                await update.message.reply_text(
                    text, reply_markup=keyboard, parse_mode="HTML",
                )
        except Exception as e:
            logger.error(f"reply_text: {e}")


async def _get_channels_with_stats(user_id: int):
    _has_removed = False
    try:
        if DB is not None and hasattr(DB, "_has_removed_at_column"):
            _has_removed = await DB._has_removed_at_column()
    except Exception as e:
        logger.debug(f"_get_channels_with_stats: _has_removed_at_column: {e}")

    _where_removed = "AND uc.removed_at IS NULL" if _has_removed else ""

    query = f"""
        SELECT
            uc.id AS channel_db_id,
            uc.channel_id,
            uc.channel_name,
            uc.banned,
            uc.created_at,
            COALESCE(pc.unpublished, 0) AS unpublished,
            COALESCE(pc.published, 0) AS published,
            s.next_publish_date AS next_publish
        FROM user_channels uc
        LEFT JOIN (
            SELECT channel_db_id,
                   SUM(CASE WHEN COALESCE(published, 0) = 0 THEN 1 ELSE 0 END)
                       AS unpublished,
                   SUM(CASE WHEN COALESCE(published, 0) = 1 THEN 1 ELSE 0 END)
                       AS published
            FROM posts
            GROUP BY channel_db_id
        ) pc ON pc.channel_db_id = uc.id
        LEFT JOIN schedule s ON s.channel_db_id = uc.id
        WHERE uc.user_id = ?
          {_where_removed}
        ORDER BY uc.created_at DESC
    """
    try:
        rows = await DB.fetchall(query, (user_id,))
        return [_row_to_dict(r) for r in (rows or [])]
    except Exception as e:
        logger.error(f"❌ _get_channels_with_stats: {e}", exc_info=True)
        try:
            fallback_query = f"""
                SELECT
                    uc.id AS channel_db_id,
                    uc.channel_id,
                    uc.channel_name,
                    uc.banned,
                    uc.created_at,
                    (SELECT COUNT(*) FROM posts p
                     WHERE p.channel_db_id = uc.id
                       AND COALESCE(p.published, 0) = 0
                    ) AS unpublished,
                    (SELECT COUNT(*) FROM posts p
                     WHERE p.channel_db_id = uc.id
                       AND COALESCE(p.published, 0) = 1
                    ) AS published,
                    (SELECT s.next_publish_date FROM schedule s
                     WHERE s.channel_db_id = uc.id
                    ) AS next_publish
                FROM user_channels uc
                WHERE uc.user_id = ?
                  {_where_removed}
                ORDER BY uc.created_at DESC
            """
            rows = await DB.fetchall(fallback_query, (user_id,))
            logger.info(
                "ℹ️ _get_channels_with_stats: استُخدم fallback "
                "(subqueries) — راجع سبب فشل LEFT JOIN أعلاه")
            return [_row_to_dict(r) for r in (rows or [])]
        except Exception as e2:
            logger.error(f"❌ fallback أيضاً فشل: {e2}")
            return []


def _build_channels_text(channels, active_channel_id) -> str:
    lines = [f"📡 <b>قنواتك ({len(channels)})</b>\n"]

    total_unpub = sum(_safe_int(c.get("unpublished"), 0) for c in channels)
    total_pub = sum(_safe_int(c.get("published"), 0) for c in channels)

    lines.append(f"📥 إجمالي غير منشور: <b>{total_unpub}</b>")
    lines.append(f"📤 إجمالي منشور: <b>{total_pub}</b>\n")
    lines.append("─" * 30 + "\n")

    for i, ch in enumerate(channels, 1):
        ch_db_id = ch.get("channel_db_id")
        name = ch.get("channel_name") or "قناة بدون اسم"
        unpublished = _safe_int(ch.get("unpublished"), 0)
        published = _safe_int(ch.get("published"), 0)

        banned = _is_banned(ch)

        if banned:
            icon = "🚫"
            status = "(محظورة)"
        elif ch_db_id == active_channel_id:
            icon = "🟢"
            status = "(نشطة)"
        else:
            icon = "⚪"
            status = ""

        badge = _short_channel_badge(ch)
        badge_txt = f" <code>{_esc(badge)}</code>" if badge else ""

        safe_name = _esc(_truncate_name(name, max_len=22))

        lines.append(
            f"{icon} <b>{i}. {safe_name}</b>{badge_txt} {status}\n"
            f"   📥 {unpublished} | 📤 {published}\n"
        )

    return "\n".join(lines)


def _build_channels_keyboard(channels, active_channel_id):
    keyboard = []

    for i, ch in enumerate(channels, 1):
        ch_db_id = ch.get("channel_db_id")
        name = ch.get("channel_name") or "قناة"

        if _is_banned(ch):
            select_icon = "🚫"
        elif ch_db_id == active_channel_id:
            select_icon = "✅"
        else:
            select_icon = "⚪"

        badge = _short_channel_badge(ch)
        safe_name = _truncate_name(name, max_len=22)

        label = f"{select_icon} {i}. {safe_name}"
        if badge:
            label = f"{label} {badge}"

        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=f"ch_sel:{ch_db_id}"
            ),
            InlineKeyboardButton(
                "ℹ️",
                callback_data=f"ch_stats:{ch_db_id}"
            ),
        ])

    keyboard.append([
        InlineKeyboardButton("➕ إضافة قناة", callback_data="ch_add"),
    ])
    keyboard.append([
        InlineKeyboardButton("🗑️ حذف قناة", callback_data="ch_del_menu"),
    ])
    keyboard.append([
        InlineKeyboardButton("↩️ رجوع للقائمة الرئيسية", callback_data="main_menu"),
    ])

    return InlineKeyboardMarkup(keyboard)


# =====================================================================
# 2. اختيار قناة
# =====================================================================

async def channel_select_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    try:
        owns = await DB.is_channel_owner(user_id, ch_db_id)
        if not owns:
            await _safe_answer(query, "⚠️ لا تملك هذه القناة", show_alert=True)
            return

        success = await DB.set_active_channel(user_id, ch_db_id)
        if success:
            await _safe_answer(query, "✅ تم تعيينها كقناة نشطة")
            await show_channels_list(update, context)
        else:
            await _safe_answer(query, "⚠️ فشل التحديث", show_alert=True)
    except Exception as e:
        logger.error(f"❌ channel_select: {e}", exc_info=True)
        await _safe_answer(query, "⚠️ خطأ غير متوقع", show_alert=True)


# =====================================================================
# 3. تفاصيل قناة
# =====================================================================

async def _render_channel_info(query, user_id: int, ch_db_id: int) -> None:
    try:
        try:
            owns = await DB.is_channel_owner(user_id, ch_db_id)
            if not owns:
                await _safe_answer(
                    query, "⚠️ لا تملك هذه القناة", show_alert=True)
                return
        except Exception as e:
            logger.debug(f"_render_channel_info ownership: {e}")

        ch_raw = await DB.get_channel_by_id(user_id, ch_db_id)
        ch = _row_to_dict(ch_raw)
        if not ch:
            await _safe_answer(query, "⚠️ القناة غير موجودة", show_alert=True)
            return

        stats_raw = await DB.get_channel_stats(user_id, ch_db_id) or {}
        stats = _row_to_dict(stats_raw)
        active_channel_id = await _get_active_channel_id(user_id)

        try:
            schedule_raw = await DB.get_schedule(ch_db_id)
            schedule = _row_to_dict(schedule_raw)
            interval_min = _safe_int(
                schedule.get("interval_minutes"), 12) or 12
            next_publish = schedule.get("next_publish_date")
        except Exception:
            interval_min = 12
            next_publish = None

        name = ch.get("channel_name") or "قناة بدون اسم"
        ch_telegram_id = ch.get("channel_id") or "غير معروف"

        banned = _is_banned(ch)

        status_icon = "🚫 محظورة" if banned else (
            "🟢 نشطة" if ch_db_id == active_channel_id else "⚪ غير نشطة"
        )

        badge = _short_channel_badge(ch)
        badge_line = (
            f"<b>البادج:</b> <code>{_esc(badge)}</code>\n" if badge else ""
        )

        name_esc = _esc(name)
        ch_telegram_id_esc = _esc(ch_telegram_id)

        text = (
            f"📡 <b>{name_esc}</b>\n\n"
            f"<b>المعرف:</b> <code>{ch_telegram_id_esc}</code>\n"
            f"{badge_line}"
            f"<b>الحالة:</b> {status_icon}\n\n"
            f"<b>📊 الإحصائيات:</b>\n"
            f"├ 📝 إجمالي: <b>{_safe_int(stats.get('total'), 0)}</b>\n"
            f"├ 📥 غير منشور: <b>{_safe_int(stats.get('unpublished'), 0)}</b>\n"
            f"└ 📤 منشور: <b>{_safe_int(stats.get('published'), 0)}</b>\n\n"
            f"<b>⚙️ الجدولة:</b>\n"
            f"├ ⏱ كل: <b>{interval_min} دقيقة</b>\n"
            f"└ 📅 التالي: <b>{_format_date(next_publish)}</b>"
        )

        buttons = []

        if ch_db_id != active_channel_id and not banned:
            buttons.append([
                InlineKeyboardButton(
                    "✅ تعيين نشطة",
                    callback_data=f"ch_sel:{ch_db_id}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "⚙️ تعديل الجدولة",
                callback_data=f"ch_schedule:{ch_db_id}"
            ),
        ])
        buttons.append([
            InlineKeyboardButton(
                "♻️ إعادة تدوير الآن",
                callback_data=f"ch_recycle:{ch_db_id}"
            ),
        ])
        buttons.append([
            InlineKeyboardButton(
                "🗑️ حذف القناة",
                callback_data=f"ch_del_confirm:{ch_db_id}"
            ),
        ])
        buttons.append([
            InlineKeyboardButton("↩️ رجوع للقائمة", callback_data="ch_list")
        ])
        buttons.append([
            InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")
        ])

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"❌ _render_channel_info: {e}", exc_info=True)
        try:
            if query.message is not None:
                await query.message.reply_text(
                    "⚠️ فشل عرض تفاصيل القناة. حاول لاحقاً.",
                    parse_mode="HTML",
                )
        except Exception:
            pass


async def channel_info_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    await _safe_answer(query)
    await _render_channel_info(query, user_id, ch_db_id)


# =====================================================================
# 4. قائمة حذف القنوات
# =====================================================================

async def channel_delete_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    channels = await _get_channels_with_stats(user_id)
    if not channels:
        await _safe_answer(query, "📭 لا توجد قنوات", show_alert=True)
        return

    await _safe_answer(query)

    text = (
        "🗑️ <b>حذف قناة</b>\n\n"
        "اختر القناة التي تريد حذفها:\n"
        "<i>⚠️ الحذف لا يمكن التراجع عنه، وسيتم حذف كل المنشورات!</i>"
    )

    buttons = []
    for i, ch in enumerate(channels, 1):
        ch_db_id = ch.get("channel_db_id")
        name = ch.get("channel_name") or "قناة"

        badge = _short_channel_badge(ch)
        safe_name = _truncate_name(name, max_len=22)

        label = f"🗑️ {i}. {safe_name}"
        if badge:
            label = f"{label} {badge}"

        buttons.append([
            InlineKeyboardButton(
                label,
                callback_data=f"ch_del_confirm:{ch_db_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton("↩️ رجوع للقائمة", callback_data="ch_list")
    ])

    try:
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"edit_message_text: {e}")


async def channel_delete_confirm_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    try:
        ch_raw = await DB.get_channel_by_id(user_id, ch_db_id)
        ch = _row_to_dict(ch_raw)
        if not ch:
            await _safe_answer(query, "⚠️ القناة غير موجودة", show_alert=True)
            return

        await _safe_answer(query)

        name = ch.get("channel_name") or "قناة"
        stats_raw = await DB.get_channel_stats(user_id, ch_db_id) or {}
        stats = _row_to_dict(stats_raw)

        badge = _short_channel_badge(ch)
        badge_line = f"  <code>{_esc(badge)}</code>\n" if badge else ""
        name_esc = _esc(name)

        text = (
            f"⚠️ <b>تأكيد الحذف</b>\n\n"
            f"هل أنت متأكد من حذف القناة:\n"
            f"<b>{name_esc}</b>\n"
            f"{badge_line}"
            f"\n<b>سيتم حذف:</b>\n"
            f"├ 📝 {_safe_int(stats.get('total'), 0)} منشور\n"
            f"├ 📥 {_safe_int(stats.get('unpublished'), 0)} غير منشور\n"
            f"└ 📤 {_safe_int(stats.get('published'), 0)} منشور\n\n"
            f"<i>⚠️ لا يمكن التراجع!</i>"
        )

        buttons = [
            [
                InlineKeyboardButton(
                    "🗑️ نعم، احذف",
                    callback_data=f"ch_del:{ch_db_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "❌ إلغاء",
                    callback_data=f"ch_stats:{ch_db_id}"
                ),
            ],
        ]

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"❌ channel_delete_confirm: {e}", exc_info=True)


async def channel_delete_execute_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    try:
        success = await DB.delete_channel(user_id, ch_db_id)

        if not success:
            await _safe_answer(query, "⚠️ فشل الحذف", show_alert=True)
            return

        try:
            from cache import invalidate_user_cache
            await invalidate_user_cache(user_id)
        except Exception:
            pass

        await _safe_answer(query, "✅ تم الحذف", show_alert=True)
        logger.info(f"✅ حُذفت القناة {ch_db_id} بواسطة {user_id}")

        await show_channels_list(update, context)
    except Exception as e:
        logger.error(f"❌ channel_delete_execute: {e}", exc_info=True)
        await _safe_answer(query, "⚠️ خطأ غير متوقع", show_alert=True)


# =====================================================================
# 5. إعادة تدوير قناة
# =====================================================================

async def channel_recycle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    try:
        owns = await DB.is_channel_owner(user_id, ch_db_id)
        if not owns:
            await _safe_answer(query, "⚠️ لا تملك هذه القناة", show_alert=True)
            return

        count = await DB.reset_posts(user_id, ch_db_id)

        await _safe_answer(
            query,
            f"✅ تم إعادة تدوير {count} منشور",
            show_alert=True,
        )

        await _render_channel_info(query, user_id, ch_db_id)
    except Exception as e:
        logger.error(f"❌ channel_recycle: {e}", exc_info=True)
        await _safe_answer(query, "⚠️ خطأ غير متوقع", show_alert=True)


# =====================================================================
# 6. تعديل الجدولة
# =====================================================================

async def channel_schedule_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        ch_db_id = int(query.data.split(":")[1])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    try:
        owns = await DB.is_channel_owner(user_id, ch_db_id)
        if not owns:
            await _safe_answer(query, "⚠️ لا تملك هذه القناة", show_alert=True)
            return

        await _safe_answer(query)

        try:
            schedule_raw = await DB.get_schedule(ch_db_id)
            schedule = _row_to_dict(schedule_raw)
            current = _safe_int(
                schedule.get("interval_minutes"), 12) or 12
        except Exception:
            current = 12

        text = (
            f"⚙️ <b>تعديل الجدولة</b>\n\n"
            f"التردد الحالي: <b>{current} دقيقة</b>\n\n"
            f"اختر التردد الجديد:"
        )

        intervals = [5, 10, 15, 30, 60, 120, 360, 720, 1440]
        buttons = []
        row = []

        for minutes in intervals:
            if minutes < 60:
                label = f"{minutes} د"
            elif minutes < 1440:
                label = f"{minutes // 60} س"
            else:
                label = "يوم"

            row.append(InlineKeyboardButton(
                label,
                callback_data=f"ch_sched_set:{ch_db_id}:{minutes}"
            ))

            if len(row) == 3:
                buttons.append(row)
                row = []

        if row:
            buttons.append(row)

        buttons.append([
            InlineKeyboardButton("↩️ رجوع", callback_data=f"ch_stats:{ch_db_id}")
        ])

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"❌ channel_schedule: {e}", exc_info=True)


async def channel_schedule_set_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id

    try:
        parts = query.data.split(":")
        ch_db_id = int(parts[1])
        minutes = int(parts[2])
    except (ValueError, IndexError):
        await _safe_answer(query, "⚠️ بيانات غير صالحة", show_alert=True)
        return

    if minutes <= 0 or minutes > 30 * 24 * 60:
        await _safe_answer(query, "⚠️ قيمة غير مسموحة", show_alert=True)
        return

    try:
        owns = await DB.is_channel_owner(user_id, ch_db_id)
        if not owns:
            await _safe_answer(query, "⚠️ لا تملك هذه القناة", show_alert=True)
            return

        success = await DB.update_schedule(
            ch_db_id,
            schedule_type="interval_minutes",
            interval_minutes=minutes,
        )

        if not success:
            await _safe_answer(query, "⚠️ فشل التحديث", show_alert=True)
            return

        try:
            await DB.update_next_publish(ch_db_id)
        except Exception as e:
            logger.debug(f"update_next_publish: {e}")

        await _safe_answer(query, f"✅ التردد الجديد: {minutes} دقيقة")

        await _render_channel_info(query, user_id, ch_db_id)
    except Exception as e:
        logger.error(f"❌ channel_schedule_set: {e}", exc_info=True)
        await _safe_answer(query, "⚠️ خطأ غير متوقع", show_alert=True)


# =====================================================================
# 7. الرجوع للقائمة الرئيسية
# =====================================================================

async def back_to_main_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """
    🆕 v2.1.6 FIX-BACK-2: أكثر صلابة.
    """
    query = update.callback_query
    if query is None:
        logger.debug("back_to_main_menu_callback: no callback_query")
        return

    await _safe_answer(query)

    try:
        if query.message is not None:
            await query.message.delete()
    except Exception as e:
        logger.debug(f"حذف الرسالة: {e}")

    _cmd_ok = False
    try:
        from handlers.handlers_command import CommandHandlers
        try:
            await CommandHandlers.start(update, context)
            _cmd_ok = True
            return
        except (AttributeError, TypeError) as e:
            logger.debug(
                f"back_to_main_menu: CommandHandlers.start signature "
                f"mismatch: {e}")
        except Exception as e:
            logger.warning(
                f"back_to_main_menu: CommandHandlers.start فشل: {e}",
                exc_info=False)
    except ImportError as e:
        logger.debug(f"handlers.handlers_command غير متاح: {e}")

    if _cmd_ok:
        return

    try:
        await _send_main_menu_fallback(context, query.from_user.id)
    except Exception as e:
        logger.error(
            f"❌ back_to_main_menu fallback: {e}", exc_info=True)
        try:
            await context.bot.send_message(
                query.from_user.id,
                "⚠️ فشل عرض القائمة الرئيسية.\nأرسل /start",
            )
        except Exception:
            pass


async def _send_main_menu_fallback(context, user_id: int):
    """إرسال القائمة الرئيسية بطريقة احتياطية."""
    text = "🌿 <b>Relax Manager</b>\n\nاختر من القائمة:"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 قنواتي", callback_data="ch_list")],
        [InlineKeyboardButton("📋 منشوراتي", callback_data="posts_menu")],
        [InlineKeyboardButton("💎 اشتراكي", callback_data="subscription_info")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings_menu")],
        [InlineKeyboardButton("❓ مساعدة", callback_data="help_menu")],
    ])
    await context.bot.send_message(
        user_id, text, reply_markup=kb, parse_mode="HTML",
    )


# =====================================================================
# 8. إضافة قناة (زر → تعليمات)
# =====================================================================

async def add_channel_redirect_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await _safe_answer(query)

    user_id = query.from_user.id

    _clear_user_state(user_id)
    _set_user_state(
        user_id,
        getattr(UserState, "WAIT_CHANNEL", None) if UserState else None,
    )

    if context.user_data is not None:
        context.user_data["awaiting_channel_add"] = True

    try:
        text = (
            "➕ <b>إضافة قناة جديدة</b>\n\n"
            "لإضافة قناة، اختر إحدى الطرق التالية:\n\n"
            "1️⃣ <b>أرسل معرف القناة</b> في المحادثة\n"
            "   مثال: <code>@my_channel</code>\n\n"
            "2️⃣ <b>أعد توجيه رسالة</b> من القناة إلى البوت\n\n"
            "3️⃣ <b>أرسل رابط القناة</b>\n"
            "   مثال: <code>https://t.me/my_channel</code>\n\n"
            "⚠️ <b>مهم:</b> تأكد من أن البوت <b>مشرف</b> في القناة!\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "💡 <i>أرسل الآن اسم القناة أو رابطها للبدء</i>"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ رجوع للقائمة", callback_data="ch_list")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
        ])

        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"❌ add_channel_redirect: {e}", exc_info=True)


# =====================================================================
# 9. معالج الرسائل النصية لإضافة قناة نشطة
# =====================================================================

_USERNAME_RE = re.compile(r"^@([a-zA-Z][a-zA-Z0-9_]{4,31})$")

_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?t\.me/"
    r"([a-zA-Z][a-zA-Z0-9_]{4,31})"
    r"(?:[/?#].*)?$",
    re.IGNORECASE,
)

_FILTER_REGEX = (
    r"^(?:@[a-zA-Z][a-zA-Z0-9_]{4,31}|"
    r"(?:https?://)?(?:www\.)?t\.me/"
    r"[a-zA-Z][a-zA-Z0-9_]{4,31}(?:[/?#].*)?)$"
)


def _extract_channel_username(text: str) -> Optional[str]:
    text = text.strip()
    m = _USERNAME_RE.match(text)
    if m:
        return m.group(1)
    m = _URL_RE.match(text)
    if m:
        return m.group(1)
    return None


def _mark_channel_add_handled(context) -> None:
    try:
        if context is not None and context.user_data is not None:
            context.user_data["_channel_add_handled"] = True
    except Exception as e:
        logger.debug(f"_mark_channel_add_handled: {e}")


async def add_channel_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not _db_ready():
        return

    message = update.message
    if not message or not message.text:
        return

    user_id = message.from_user.id

    if context.user_data is not None:
        if context.user_data.get("_adding_channel_lock"):
            logger.debug(
                f"🔒 add_channel_from_message: قفل مسبق للمستخدم {user_id}"
            )
            raise ApplicationHandlerStop
        context.user_data["_adding_channel_lock"] = True

    try:
        state_str = _get_state_str(user_id)
        is_channel_add_ctx = _is_channel_add_state(state_str)

        if _user_has_pending_state(user_id):
            logger.debug(
                f"⏭️ add_channel_from_message: تجاهل — "
                f"المستخدم {user_id} في حالة معلقة ({state_str})"
            )
            return

        # 🔴 v2.1.8 FIX-STATE-3: الآن WAIT_UPDATE_CH/CHANNEL يصل إلى هنا
        #    لأنها ليست في _CHANNEL_ADD_STATES → _user_has_pending_state
        #    يُرجع True → نُتجاهل. handlers_command.handle_text يعالجها.

        text = message.text.strip()

        channel_username = _extract_channel_username(text)
        if not channel_username:
            if ((context.user_data
                 and context.user_data.get("awaiting_channel_add"))
                    or is_channel_add_ctx):
                try:
                    await message.reply_text(
                        "⚠️ <b>صيغة غير صحيحة</b>\n\n"
                        "أرسل:\n"
                        "• <code>@my_channel</code>\n"
                        "• <code>https://t.me/my_channel</code>",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                _mark_channel_add_handled(context)
                _clear_user_state(user_id)
                if context.user_data:
                    context.user_data.pop("awaiting_channel_add", None)
                raise ApplicationHandlerStop
            return

        logger.info(
            f"📥 محاولة إضافة قناة: @{channel_username} من {user_id} "
            f"(state={state_str or 'none'})"
        )

        processing_msg = None
        try:
            try:
                user_raw = await DB.get_user_full_data(
                    user_id, include_stats=True)
                user = _row_to_dict(user_raw)
                if not user:
                    await _reply_or_edit(
                        processing_msg, message,
                        "⚠️ الرجاء إرسال /start أولاً."
                    )
                    _mark_channel_add_handled(context)
                    _clear_user_state(user_id)
                    raise ApplicationHandlerStop

                if user.get("banned"):
                    await _reply_or_edit(
                        processing_msg, message,
                        "🚫 أنت محظور من استخدام البوت."
                    )
                    _mark_channel_add_handled(context)
                    _clear_user_state(user_id)
                    raise ApplicationHandlerStop

                if not user.get("has_subscription"):
                    await _reply_or_edit(
                        processing_msg, message,
                        "💎 <b>يجب أن يكون لديك اشتراك نشط</b>\n\n"
                        "استخدم /subscribe للاشتراك."
                    )
                    _mark_channel_add_handled(context)
                    _clear_user_state(user_id)
                    raise ApplicationHandlerStop

                channels_count = _safe_int(
                    user.get("channels_count"), 0)
                active_sub_raw = await DB.get_active_subscription(user_id)
                active_sub = _row_to_dict(active_sub_raw)
                if active_sub:
                    max_channels = _safe_int(
                        active_sub.get("max_channels"), 0)
                    if max_channels > 0 and channels_count >= max_channels:
                        await _reply_or_edit(
                            processing_msg, message,
                            f"⚠️ <b>وصلت للحد الأقصى</b>\n\n"
                            f"عدد قنواتك: {channels_count}/{max_channels}"
                        )
                        _mark_channel_add_handled(context)
                        _clear_user_state(user_id)
                        raise ApplicationHandlerStop

            except ApplicationHandlerStop:
                raise
            except Exception as e:
                logger.error(f"❌ فحص الصلاحيات: {e}", exc_info=True)
                await _reply_or_edit(
                    processing_msg, message,
                    "⚠️ حدث خطأ. حاول لاحقاً."
                )
                _mark_channel_add_handled(context)
                _clear_user_state(user_id)
                raise ApplicationHandlerStop

            try:
                processing_msg = await message.reply_text(
                    f"⏳ جاري التحقق من <code>@{_esc(channel_username)}</code>...",
                    parse_mode="HTML",
                )
            except Exception:
                processing_msg = None

            try:
                chat = await context.bot.get_chat(f"@{channel_username}")
            except Exception as e:
                logger.warning(
                    f"⚠️ فشل جلب القناة @{channel_username}: {e}")
                await _edit_or_send(
                    processing_msg, message,
                    f"❌ <b>لم أتمكن من الوصول للقناة</b>\n\n"
                    f"تأكد أن:\n"
                    f"• القناة موجودة\n"
                    f"• المعرّف صحيح: <code>@{_esc(channel_username)}</code>\n"
                    f"• القناة عامة (public)"
                )
                _mark_channel_add_handled(context)
                _clear_user_state(user_id)
                raise ApplicationHandlerStop

            try:
                bot_member = await context.bot.get_chat_member(
                    chat.id, context.bot.id)
                bot_status = getattr(bot_member, "status", "")

                if bot_status not in ("administrator", "creator"):
                    chat_title_esc = _esc(chat.title)
                    username_esc = _esc(channel_username)
                    await _edit_or_send(
                        processing_msg, message,
                        f"⚠️ <b>البوت ليس مشرفاً في القناة</b>\n\n"
                        f"📌 القناة: <b>{chat_title_esc}</b>\n\n"
                        f"<b>الحل:</b>\n"
                        f"1. أضف البوت إلى القناة\n"
                        f"2. ارقِّه إلى <b>مشرف</b>\n"
                        f"3. امنحه صلاحية <b>نشر الرسائل</b>\n"
                        f"4. أعد إرسال <code>@{username_esc}</code>"
                    )
                    _mark_channel_add_handled(context)
                    _clear_user_state(user_id)
                    raise ApplicationHandlerStop

                can_post = getattr(
                    bot_member, "can_post_messages", True)
                if not can_post:
                    await _edit_or_send(
                        processing_msg, message,
                        f"⚠️ <b>البوت لا يملك صلاحية النشر</b>\n\n"
                        f"امنح البوت صلاحية <b>Post Messages</b>."
                    )
                    _mark_channel_add_handled(context)
                    _clear_user_state(user_id)
                    raise ApplicationHandlerStop

            except ApplicationHandlerStop:
                raise
            except Exception as e:
                logger.error(
                    f"❌ فحص صلاحيات البوت: {e}", exc_info=True)
                await _edit_or_send(
                    processing_msg, message,
                    "⚠️ لم أتمكن من التحقق من صلاحيات البوت."
                )
                _mark_channel_add_handled(context)
                _clear_user_state(user_id)
                raise ApplicationHandlerStop

            try:
                result = await DB.add_channel(
                    user_id=user_id,
                    channel_id=chat.id,
                    channel_name=chat.title,
                    set_active=True,
                )
            except Exception as e:
                logger.error(f"❌ فشل add_channel: {e}", exc_info=True)
                await _edit_or_send(
                    processing_msg, message,
                    "❌ حدث خطأ أثناء إضافة القناة."
                )
                _mark_channel_add_handled(context)
                _clear_user_state(user_id)
                raise ApplicationHandlerStop

            result_d = _row_to_dict(result)
            if result_d or result:
                channel_name = (
                    result_d.get("channel_name")
                    if result_d else chat.title
                ) or chat.title
                posts_count = _safe_int(
                    (result_d.get("posts_count") if result_d else 0), 0)

                channel_name_esc = _esc(channel_name)
                chat_id_esc = _esc(chat.id)
                username_esc = _esc(channel_username)

                success_text = (
                    f"✅ <b>تم إضافة القناة بنجاح!</b>\n\n"
                    f"📡 <b>{channel_name_esc}</b>\n"
                    f"🆔 <code>{chat_id_esc}</code>\n"
                    f"🔗 @{username_esc}\n\n"
                    f"📥 منشورات موجودة: {posts_count}\n"
                    f"🟢 تم تعيينها <b>القناة النشطة</b>"
                )

                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "📡 قنواتي", callback_data="ch_list")],
                    [InlineKeyboardButton(
                        "➕ إضافة منشورات", callback_data="post_add")],
                    [InlineKeyboardButton(
                        "🏠 القائمة الرئيسية",
                        callback_data="main_menu")],
                ])

                try:
                    if processing_msg:
                        await processing_msg.edit_text(
                            success_text,
                            reply_markup=keyboard,
                            parse_mode="HTML",
                        )
                    else:
                        await message.reply_text(
                            success_text,
                            reply_markup=keyboard,
                            parse_mode="HTML",
                        )
                except Exception:
                    try:
                        await message.reply_text(
                            success_text,
                            reply_markup=keyboard,
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass

                logger.info(
                    f"✅ تم إضافة القناة @{channel_username} "
                    f"للمستخدم {user_id}"
                )
            else:
                await _edit_or_send(
                    processing_msg, message,
                    f"❌ <b>فشل إضافة القناة</b>\n\n"
                    f"قد تكون مسجلة مسبقاً."
                )

            _mark_channel_add_handled(context)
            _clear_user_state(user_id)
            if context.user_data:
                context.user_data.pop("awaiting_channel_add", None)
            raise ApplicationHandlerStop

        except ApplicationHandlerStop:
            raise
        except Exception as e:
            logger.error(
                f"❌ add_channel_from_message غير متوقع: {e}",
                exc_info=True,
            )
            _mark_channel_add_handled(context)
            _clear_user_state(user_id)
            if context.user_data:
                context.user_data.pop("awaiting_channel_add", None)
            try:
                await message.reply_text(
                    "⚠️ حدث خطأ غير متوقع. حاول مجدداً.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            raise ApplicationHandlerStop
    finally:
        if context.user_data is not None:
            context.user_data.pop("_adding_channel_lock", None)


async def _edit_or_send(processing_msg, message, text: str):
    if processing_msg is not None:
        try:
            mid = getattr(processing_msg, "message_id", None)
            if mid:
                await processing_msg.edit_text(text, parse_mode="HTML")
                return
        except Exception as e:
            logger.debug(f"_edit_or_send edit_text: {e}")

    try:
        await message.reply_text(text, parse_mode="HTML")
    except Exception as e:
        logger.debug(f"_edit_or_send reply_text: {e}")


async def _reply_or_edit(processing_msg, message, text: str):
    await _edit_or_send(processing_msg, message, text)


# =====================================================================
# 10. معالج سريع لزر "إضافة منشورات"
# =====================================================================

async def posts_add_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not _db_ready():
        return

    query = update.callback_query
    user_id = query.from_user.id
    await _safe_answer(query)

    _set_user_state(
        user_id,
        getattr(UserState, "ADDING_POSTS", None) if UserState else None,
    )

    ch_name = None
    try:
        row = await DB.fetchone(
            """
            SELECT uc.channel_name
            FROM users u
            JOIN user_channels uc ON uc.id = u.active_channel
            WHERE u.user_id = ? AND COALESCE(uc.banned, 0) = 0
            """,
            (user_id,),
        )
        row_d = _row_to_dict(row)
        if row_d:
            ch_name = row_d.get("channel_name")
    except Exception as e:
        logger.error(f"posts_add_callback query: {e}")

    if ch_name:
        ch_name_esc = _esc(ch_name)
        text = (
            f"➕ <b>إضافة منشورات</b>\n\n"
            f"📡 القناة النشطة: <b>{ch_name_esc}</b>\n\n"
            f"<b>📌 طرق الإضافة:</b>\n"
            f"• أرسل <b>نص</b> مباشرة في المحادثة\n"
            f"• أرسل <b>صورة/فيديو/ملف</b> مع تعليق\n"
            f"• أرسل <b>عدة رسائل</b> — كلها تُضاف تلقائياً\n\n"
            f"💡 <i>ابدأ بإرسال المحتوى الآن</i>"
        )
    else:
        _clear_user_state(user_id)
        text = (
            "⚠️ <b>لا توجد قناة نشطة</b>\n\n"
            "اختر قناة أولاً من قائمة قنواتك."
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 قنواتي", callback_data="ch_list")],
        [InlineKeyboardButton(
            "🏠 القائمة الرئيسية", callback_data="main_menu")],
    ])

    try:
        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode="HTML",
        )
    except Exception as e:
        logger.debug(f"edit_message_text: {e}")
        try:
            if query.message is not None:
                await query.message.reply_text(
                    text, reply_markup=keyboard, parse_mode="HTML",
                )
        except Exception as e2:
            logger.error(f"reply_text: {e2}")


# =====================================================================
# 11. تسجيل كل الـ handlers
# =====================================================================

def register_channels_list_handlers(application):
    """
    تسجيل كل handlers قائمة القنوات.

    🆕 v2.1.8 FIX-STATE-3:
        _CHANNEL_ADD_STATES لم يعد يحتوي WAIT_UPDATE_CH/CHANNEL.
        هذا يضمن أن قناة التحديثات لا تُعالَج كقناة نشطة.
    """
    try:
        # ═══ الرجوع للقائمة الرئيسية ═══
        application.add_handler(
            CallbackQueryHandler(
                _stop_after(back_to_main_menu_callback),
                pattern=_MAIN_MENU_PATTERN,
            )
        )
        logger.info(
            "✅ [v2.1.8] back-to-main pattern = %s",
            _MAIN_MENU_PATTERN,
        )

        # ═══ إضافة قناة ═══
        application.add_handler(
            CallbackQueryHandler(
                _stop_after(add_channel_redirect_callback),
                pattern=_CH_ADD_PATTERN,
            )
        )

        # ═══ إضافة منشورات ═══
        application.add_handler(
            CallbackQueryHandler(
                _stop_after(posts_add_callback),
                pattern=_POST_ADD_PATTERN,
            )
        )

        # ═══ قائمة القنوات ═══
        application.add_handler(
            CallbackQueryHandler(
                _stop_after(show_channels_list),
                pattern=_CH_LIST_PATTERN,
            )
        )

        # ═══ اختيار/تفاصيل ═══
        application.add_handler(
            CallbackQueryHandler(
                _stop_after(channel_select_callback),
                pattern=_CH_SEL_PATTERN,
            )
        )
        application.add_handler(
            CallbackQueryHandler(
                _stop_after(channel_info_callback),
                pattern=_CH_STATS_PATTERN,
            )
        )

        # ═══ الحذف ═══
        application.add_handler(
            CallbackQueryHandler(
                _stop_after(channel_delete_menu_callback),
                pattern=_CH_DEL_MENU_PATTERN,
            )
        )
        application.add_handler(
            CallbackQueryHandler(
                _stop_after(channel_delete_confirm_callback),
                pattern=_CH_DEL_CONFIRM_PATTERN,
            )
        )
        application.add_handler(
            CallbackQueryHandler(
                _stop_after(channel_delete_execute_callback),
                pattern=_CH_DEL_PATTERN,
            )
        )

        # ═══ إعادة التدوير ═══
        application.add_handler(
            CallbackQueryHandler(
                _stop_after(channel_recycle_callback),
                pattern=_CH_RECYCLE_PATTERN,
            )
        )

        # ═══ الجدولة ═══
        application.add_handler(
            CallbackQueryHandler(
                _stop_after(channel_schedule_callback),
                pattern=_CH_SCHEDULE_PATTERN,
            )
        )
        application.add_handler(
            CallbackQueryHandler(
                _stop_after(channel_schedule_set_callback),
                pattern=_CH_SCHED_SET_PATTERN,
            )
        )

        # ═══ معالج الرسائل النصية لإضافة قناة ═══
        # ⚠️ v2.1.8: group=-1 يجعله يعمل قبل handlers أخرى.
        #    لهذا السبب كان الباغ خطيراً: كان يسرق رسائل قناة
        #    التحديثات. الآن الحالات محذوفة من _CHANNEL_ADD_STATES
        #    → لن يستقبلها.
        application.add_handler(
            MessageHandler(
                filters.TEXT
                & filters.ChatType.PRIVATE
                & ~filters.COMMAND
                & filters.Regex(re.compile(_FILTER_REGEX, re.IGNORECASE)),
                add_channel_from_message,
            ),
            group=-1,
        )

        logger.info(
            "✅ تم تسجيل handlers قائمة القنوات (v2.1.8 — "
            "UPDATES-CHANNEL-STATE-COLLISION-FIX + "
            "SECURITY-COMPLETENESS-FIX + BACK-BUTTON-FIX + "
            "UNIFIED-PREFIXES + PTB-V20-MULTI-HANDLER-FIX)"
        )
        return True
    except Exception as e:
        logger.error(f"❌ فشل تسجيل handlers: {e}", exc_info=True)
        return False


# =====================================================================
# 12. __all__
# =====================================================================

__all__ = [
    "show_channels_list",
    "channel_select_callback",
    "channel_info_callback",
    "channel_delete_menu_callback",
    "channel_delete_confirm_callback",
    "channel_delete_execute_callback",
    "channel_recycle_callback",
    "channel_schedule_callback",
    "channel_schedule_set_callback",
    "back_to_main_menu_callback",
    "add_channel_redirect_callback",
    "add_channel_from_message",
    "posts_add_callback",
    "register_channels_list_handlers",
    "_extract_channel_username",
    "_mark_channel_add_handled",
    "_is_banned",
    "_short_channel_badge",
    "_truncate_name",
    "_stop_after",
    "_build_main_menu_pattern",
    "_MAIN_MENU_PATTERN",
    "_CHANNEL_ADD_STATES",
    "_esc",
    "_cb_value",
    "_build_exact_pattern",
    "_build_prefixed_pattern",
    "_CH_ADD_PATTERN",
    "_CH_LIST_PATTERN",
    "_POST_ADD_PATTERN",
    "_CH_SEL_PATTERN",
    "_CH_STATS_PATTERN",
    "_CH_DEL_PATTERN",
    "_CH_DEL_CONFIRM_PATTERN",
    "_CH_DEL_MENU_PATTERN",
    "_CH_RECYCLE_PATTERN",
    "_CH_SCHEDULE_PATTERN",
    "_CH_SCHED_SET_PATTERN",
]


# =====================================================================
# LOAD BEACON
# =====================================================================

try:
    logger.info(
        "✅ handlers_channels_list v2.1.8 loaded | "
        "fixes=(UPDATES-CHANNEL-STATE-COLLISION-FIX + "
        "SECURITY-COMPLETENESS-FIX + BACK-BUTTON-FIX + "
        "UNIFIED-PREFIXES + PTB-V20-MULTI-HANDLER-FIX) | "
        "_CHANNEL_ADD_STATES=(WAIT_CHANNEL+WAIT_ADD_CHANNEL) | "
        "removed=(WAIT_UPDATE_CH+WAIT_UPDATE_CHANNEL) | "
        "main_menu_pattern=%s | "
        "ch_add_pattern=%s | "
        "ch_list_pattern=%s | "
        "stop_after=wraps-all-callbacks | "
        "html_escape=applied-everywhere | "
        "date=utc_to_mecca-with-tz-aware-fallback | "
        "CB_module=%s | row_to_dict=%s",
        _MAIN_MENU_PATTERN,
        _CH_ADD_PATTERN,
        _CH_LIST_PATTERN,
        "available" if _CB_AVAILABLE else "unavailable",
        "shared" if _HAS_SHARED_ROW_TO_DICT else "fallback",
    )
except Exception:
    pass
