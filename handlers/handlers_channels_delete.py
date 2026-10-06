#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/handlers_channels_delete.py - تأكيد حذف القنوات يدوياً (v1.1.0)
=====================================================================
🆕 v1.1.0 (CROSS-DB-FIX + SECURITY-HARDENING):
    🔴 FIX-CRITICAL: دعم كامل لـ PostgreSQL ($1) + MySQL (%s) + SQLite (?)
                     كان v1.0.0 يستخدم ? فقط → سيفشل على PostgreSQL
    🔴 FIX-SECURITY: التحقق من الملكية في request_delete (وليس في الحذف فقط)
                     → كان يكشف إحصائيات قنوات الآخرين لأي مستخدم!
    🟡 FIX: has_schedule كان يفحص last_publish بدل جدول schedule
    🟡 FIX: معالجة owner_id = None بشكل آمن (كان يرفع exception)
    🟡 FIX: التحقق الفعلي من نجاح DELETE (كان يثق بالنص بلا تحقق)
    🟡 FIX: answer callback query عند الفتح (كان يُبقي loading spinner)
    🟢 NEW: _get_db_type() + _ph(n) helpers للتوافق مع كل DB
    🟢 NEW: _verify_ownership() — دالة مركزية للملكية
    🟢 NEW: _parse_delete_count() — تحويل نتيجة DELETE إلى int
    🟢 NEW: حد أقصى للطلبات المعلقة لكل مستخدم (MAX_PENDING_PER_USER=5)
    🟢 NEW: تسجيل أفضل للأخطاء مع exc_info

✅ v1.0.0-final:
    ✅ CONF-1: عرض إحصائيات كاملة قبل الحذف
    ✅ CONF-2: طلب تأكيد صريح مع أزرار [نعم/إلغاء]
    ✅ CONF-3: مهلة التأكيد 5 دقائق
    ✅ CONF-4: دعم القنوات والمجموعات
    ✅ CONF-5: تسجيل الحذف في admin_logs
    ✅ CONF-6: إشعار فوري بعد الحذف
    ✅ CONF-7: التحقق من ملكية القناة (v1.1.0: مُحسَّن)
    ✅ CONF-8: تنظيف cache تلقائي بعد الحذف

📌 الاستخدام في main.py:
    from handlers.handlers_channels_delete import (
        register_delete_confirmation as register_ch_delete,
    )
    register_ch_delete(app)

📌 الاستخدام من أي مكان في الكود:
    from handlers.handlers_channels_delete import request_delete
    # ...
    await request_delete(
        update, context,
        channel_db_id=5,
        channel_name="قناتي",
        user_id=123,
    )
=====================================================================
"""

import html
import logging
import time
from typing import Optional, Dict, Any

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    ContextTypes, CallbackQueryHandler,
)

from database import DB, TimeUtils

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# ثوابت
# ═════════════════════════════════════════════════════════════════════

# مهلة صلاحية زر التأكيد (ثوان) — 5 دقائق
_CONFIRM_TTL = 300.0

# 🆕 v1.1.0: حد أقصى للطلبات المعلقة لكل مستخدم
_MAX_PENDING_PER_USER = 5

# Cache مؤقت لطلبات التأكيد:
#   key = f"{user_id}:{channel_db_id}" → (timestamp, channel_name, user_id)
_pending_confirms: Dict[str, tuple] = {}


# ═════════════════════════════════════════════════════════════════════
# 🆕 v1.1.0: Helpers للتوافق مع قواعد البيانات
# ═════════════════════════════════════════════════════════════════════

def _get_db_type() -> str:
    """
    🆕 v1.1.0: يعتمد على USE_POSTGRES/USE_MYSQL الرسمية
    بدلاً من DB.DB_TYPE غير المضمون.
    """
    try:
        from database import USE_POSTGRES, USE_MYSQL
        if USE_POSTGRES:
            return "postgres"
        if USE_MYSQL:
            return "mysql"
        return "sqlite"
    except Exception as e:
        logger.debug("_get_db_type fallback: %s", e)
        try:
            t = getattr(DB, "DB_TYPE", None)
            if t:
                return str(t).lower()
        except Exception:
            pass
        return "sqlite"


def _ph(n: int = 1) -> str:
    """
    🆕 v1.1.0: placeholder للمعامل رقم n (1-based).

    - postgres: $n
    - mysql:    %s
    - sqlite:   ?
    """
    db = _get_db_type()
    if db == "postgres":
        return f"${n}"
    if db == "mysql":
        return "%s"
    return "?"


def _parse_delete_count(result: Any) -> int:
    """
    🆕 v1.1.0: تحويل نتيجة DELETE إلى int بأمان.

    - asyncpg:    "DELETE N"
    - aiomysql:   rowcount (int)
    - aiosqlite:  rowcount (int) أو "DELETE N"
    """
    if result is None:
        return -1  # ← -1 يعني "غير معروف" (لا نستطيع الحكم)
    if isinstance(result, bool):
        return 0
    if isinstance(result, int):
        return result
    if isinstance(result, str):
        parts = result.strip().split()
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except (ValueError, IndexError):
                pass
        try:
            return int(result)
        except ValueError:
            return -1
    return -1


# ═════════════════════════════════════════════════════════════════════
# إدارة الطلبات المعلقة
# ═════════════════════════════════════════════════════════════════════

def _should_confirm(user_id: int, channel_db_id: int) -> bool:
    """فحص هل التأكيد لا يزال صالحاً."""
    key = f"{user_id}:{channel_db_id}"
    if key not in _pending_confirms:
        return False
    ts = _pending_confirms[key][0]
    if time.monotonic() - ts > _CONFIRM_TTL:
        _pending_confirms.pop(key, None)
        return False
    return True


def _mark_pending(
    user_id: int, channel_db_id: int, channel_name: str
) -> None:
    """تسجيل طلب تأكيد."""
    key = f"{user_id}:{channel_db_id}"
    _pending_confirms[key] = (
        time.monotonic(), channel_name, user_id
    )


def _clear_pending(user_id: int, channel_db_id: int) -> None:
    """إزالة طلب تأكيد."""
    _pending_confirms.pop(f"{user_id}:{channel_db_id}", None)


def _count_user_pending(user_id: int) -> int:
    """
    🆕 v1.1.0: عدد الطلبات المعلقة لمستخدم معين.
    """
    if not user_id:
        return 0
    prefix = f"{user_id}:"
    return sum(1 for k in _pending_confirms if k.startswith(prefix))


def _prune_pending() -> int:
    """تنظيف الطلبات المنتهية."""
    removed = 0
    now = time.monotonic()
    try:
        for k in list(_pending_confirms.keys()):
            if now - _pending_confirms[k][0] > _CONFIRM_TTL:
                _pending_confirms.pop(k, None)
                removed += 1
    except Exception as e:
        logger.debug("_prune_pending: %s", e)
    return removed


def _clear_user_pending(user_id: int) -> int:
    """
    🆕 v1.1.0: إزالة كل طلبات مستخدم معين.
    مفيدة عند الوصول لحد الطلبات.
    """
    if not user_id:
        return 0
    prefix = f"{user_id}:"
    keys = [k for k in _pending_confirms if k.startswith(prefix)]
    for k in keys:
        _pending_confirms.pop(k, None)
    return len(keys)


# ═════════════════════════════════════════════════════════════════════
# 🆕 v1.1.0: التحقق من الملكية
# ═════════════════════════════════════════════════════════════════════

async def _verify_ownership(
    channel_db_id: int,
    user_id: int,
) -> Optional[Dict[str, Any]]:
    """
    🆕 v1.1.0: التحقق من أن المستخدم يملك القناة.

    Returns:
        dict صف القناة إذا كان المستخدم هو المالك، وإلا None.
    """
    if not channel_db_id or not user_id:
        return None

    try:
        row = await DB.fetchone(
            f"SELECT user_id, channel_name, channel_id "
            f"FROM user_channels WHERE id = {_ph(1)}",
            (channel_db_id,),
        )
        if not row:
            return None

        owner_raw = row.get('user_id')
        if owner_raw is None:
            logger.warning(
                f"⚠️ _verify_ownership: owner_id=NULL "
                f"للقناة {channel_db_id} — رفض"
            )
            return None

        try:
            owner_id = int(owner_raw)
        except (TypeError, ValueError):
            logger.warning(
                f"⚠️ _verify_ownership: owner_id غير صالح "
                f"({owner_raw!r}) للقناة {channel_db_id}"
            )
            return None

        if owner_id != int(user_id):
            logger.warning(
                f"⚠️ _verify_ownership: رفض — "
                f"المستخدم {user_id} لا يملك القناة {channel_db_id} "
                f"(المالك: {owner_id})"
            )
            return None

        return row

    except Exception as e:
        logger.warning(
            f"_verify_ownership({channel_db_id}): "
            f"{type(e).__name__}: {e}",
        )
        return None


# ═════════════════════════════════════════════════════════════════════
# جمع الإحصائيات
# ═════════════════════════════════════════════════════════════════════

async def _collect_channel_stats(
    channel_db_id: int
) -> Dict[str, Any]:
    """
    جمع إحصائيات القناة قبل الحذف.

    🆕 v1.1.0: يستخدم placeholders حسب نوع DB + يفحص schedule بشكل صحيح.
    """
    stats: Dict[str, Any] = {
        'posts_total': 0,
        'posts_published': 0,
        'posts_unpublished': 0,
        'channel_name': '',
        'channel_id': None,
        'has_schedule': False,
        'last_publish': None,
    }

    # ── 1) معلومات القناة ──
    try:
        ch_row = await DB.fetchone(
            f"SELECT channel_name, channel_id "
            f"FROM user_channels WHERE id = {_ph(1)}",
            (channel_db_id,),
        )
        if ch_row:
            stats['channel_name'] = ch_row.get('channel_name') or ''
            stats['channel_id'] = ch_row.get('channel_id')
    except Exception as e:
        logger.warning(
            f"⚠️ _collect_channel_stats (channel info): {e}"
        )

    # ── 2) عدد المنشورات ──
    try:
        posts_row = await DB.fetchone(
            f"SELECT "
            f"  COUNT(*) AS total, "
            f"  SUM(CASE WHEN published = 1 THEN 1 ELSE 0 END) AS published, "
            f"  SUM(CASE WHEN published = 0 THEN 1 ELSE 0 END) AS unpublished "
            f"FROM posts WHERE channel_db_id = {_ph(1)}",
            (channel_db_id,),
        )
        if posts_row:
            stats['posts_total'] = int(posts_row.get('total') or 0)
            stats['posts_published'] = int(
                posts_row.get('published') or 0
            )
            stats['posts_unpublished'] = int(
                posts_row.get('unpublished') or 0
            )
    except Exception as e:
        logger.warning(
            f"⚠️ _collect_channel_stats (posts): {e}"
        )

    # ── 3) آخر نشر ──
    try:
        lp_row = await DB.fetchone(
            f"SELECT last_publish_time FROM last_publish "
            f"WHERE channel_db_id = {_ph(1)}",
            (channel_db_id,),
        )
        if lp_row:
            stats['last_publish'] = lp_row.get('last_publish_time')
    except Exception as e:
        logger.debug(
            f"_collect_channel_stats (last_publish): {e}"
        )

    # ── 4) 🆕 v1.1.0: فحص جدول schedule (وليس last_publish) ──
    try:
        sch_row = await DB.fetchone(
            f"SELECT 1 FROM schedule "
            f"WHERE channel_db_id = {_ph(1)}",
            (channel_db_id,),
        )
        stats['has_schedule'] = sch_row is not None
    except Exception as e:
        logger.debug(
            f"_collect_channel_stats (schedule): {e}"
        )

    return stats


# ═════════════════════════════════════════════════════════════════════
# عرض التأكيد
# ═════════════════════════════════════════════════════════════════════

def _format_stats_text(
    channel_name: str,
    stats: Dict[str, Any],
) -> str:
    """صياغة نص الإحصائيات."""
    safe_name = html.escape(str(channel_name or "—"))

    total = stats.get('posts_total', 0)
    pub = stats.get('posts_published', 0)
    unpub = stats.get('posts_unpublished', 0)

    last_pub_str = "—"
    lp = stats.get('last_publish')
    if lp:
        try:
            if hasattr(lp, 'strftime'):
                last_pub_str = lp.strftime("%Y-%m-%d %H:%M")
            else:
                last_pub_str = str(lp)[:16]
        except Exception:
            last_pub_str = str(lp)[:16]

    # 🆕 v1.1.0: عرض حالة الجدول
    schedule_line = (
        "✅ موجود" if stats.get('has_schedule') else "❌ غير موجود"
    )

    text = (
        f"⚠️ <b>تأكيد حذف القناة</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        f"📡 <b>القناة:</b> {safe_name}\n"
        f"🆔 <b>معرف القناة:</b> "
        f"<code>{stats.get('channel_id', '—')}</code>\n\n"

        "📊 <b>ما سيُحذف نهائياً:</b>\n"
        f"   • <b>{total}</b> منشوراً إجمالاً\n"
        f"      ├─ 📤 {pub} منشوراً (منشور)\n"
        f"      └─ 📥 {unpub} منشوراً (لم يُنشر)\n"
        f"   • ⏰ الجدول الزمني: {schedule_line}\n"
        f"   • 📅 آخر نشر: {last_pub_str}\n\n"

        "❌ <b>هذا الإجراء لا يمكن التراجع عنه!</b>\n\n"
        "<i>💡 إذا كنت تريد الاحتفاظ بالبيانات مؤقتاً، "
        "أزل البوت من تيليجرام فقط بدون حذف القناة هنا.</i>"
    )

    return text


def _build_confirm_keyboard(channel_db_id: int) -> InlineKeyboardMarkup:
    """أزرار التأكيد."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🗑️ نعم، احذف نهائياً",
                callback_data=f"ch_confirm_delete:{channel_db_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                "❌ إلغاء",
                callback_data=f"ch_cancel_delete:{channel_db_id}",
            ),
        ],
    ])


# ═════════════════════════════════════════════════════════════════════
# طلب التأكيد
# ═════════════════════════════════════════════════════════════════════

async def request_delete(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    channel_db_id: int,
    channel_name: str = "",
    user_id: Optional[int] = None,
) -> bool:
    """
    طلب تأكيد حذف قناة.

    🆕 v1.1.0:
        • التحقق من الملكية قبل عرض الإحصائيات (أمان)
        • answer callback query لمنع loading spinner
        • حد أقصى للطلبات المعلقة لكل مستخدم

    Returns:
        True إذا نجح العرض
    """
    # ── استخراج user_id ──
    if user_id is None:
        if update.effective_user:
            user_id = update.effective_user.id
        else:
            return False

    if not channel_db_id:
        return False

    # ── تنظيف الطلبات المنتهية ──
    _prune_pending()

    # ── 🔴 v1.1.0: التحقق من الملكية قبل أي شيء ──
    ch_row = await _verify_ownership(channel_db_id, user_id)
    if not ch_row:
        try:
            if update.callback_query:
                await update.callback_query.answer(
                    "❌ غير مصرح — لا تملك هذه القناة",
                    show_alert=True,
                )
            elif update.effective_message:
                await update.effective_message.reply_text(
                    "❌ <b>غير مصرح</b>\n\n"
                    "لا تملك هذه القناة أو أنها غير موجودة.",
                    parse_mode='HTML',
                )
        except Exception as e:
            logger.debug(f"notify unauthorized: {e}")
        return False

    # ── 🆕 v1.1.0: answer callback query فوراً ──
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception as e:
            logger.debug(f"answer callback: {e}")

    # ── 🆕 v1.1.0: فحص حد الطلبات المعلقة ──
    pending_count = _count_user_pending(user_id)
    if pending_count >= _MAX_PENDING_PER_USER:
        # نُنظّف أولاً، ثم نعيد الفحص
        _clear_user_pending(user_id)

    # ── جمع الإحصائيات ──
    stats = await _collect_channel_stats(channel_db_id)

    # ── استخدام اسم القناة من DB إن لم يُمرَّر ──
    if not channel_name:
        channel_name = (
            ch_row.get('channel_name')
            or stats.get('channel_name')
            or "—"
        )

    # ── تسجيل الطلب ──
    _mark_pending(user_id, channel_db_id, channel_name)

    # ── بناء النص والأزرار ──
    text = _format_stats_text(channel_name, stats)
    keyboard = _build_confirm_keyboard(channel_db_id)

    # ── العرض ──
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML',
            )
        elif update.effective_message:
            await update.effective_message.reply_text(
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML',
            )
        else:
            return False
        return True
    except Exception as e:
        logger.error(
            f"❌ request_delete عرض فشل: "
            f"{type(e).__name__}: {e}",
            exc_info=True,
        )
        return False


# ═════════════════════════════════════════════════════════════════════
# تنفيذ الحذف
# ═════════════════════════════════════════════════════════════════════

async def _execute_delete(
    channel_db_id: int,
    user_id: int,
) -> bool:
    """
    تنفيذ حذف القناة فعلياً (CASCADE يحذف المنشورات).

    🆕 v1.1.0: يتحقق فعلياً من نجاح الحذف (وليس فقط من عدم رفع exception).
    """
    # ── 1) التحقق من الملكية ──
    ch_row = await _verify_ownership(channel_db_id, user_id)
    if not ch_row:
        logger.warning(
            f"⚠️ _execute_delete: ملكية مرفوضة أو القناة "
            f"مفقودة ({channel_db_id})"
        )
        return False

    channel_name = ch_row.get('channel_name') or ''
    channel_id = ch_row.get('channel_id')

    # ── 2) الحذف (CASCADE) ──
    try:
        result = await DB.execute(
            f"DELETE FROM user_channels WHERE id = {_ph(1)}",
            (channel_db_id,),
        )
    except Exception as e:
        logger.error(
            f"❌ _execute_delete({channel_db_id}) DELETE failed: "
            f"{type(e).__name__}: {e}",
            exc_info=True,
        )
        return False

    # ── 3) 🆕 v1.1.0: تحليل نتيجة DELETE ──
    deleted_count = _parse_delete_count(result)
    if deleted_count == 0:
        logger.warning(
            f"⚠️ _execute_delete: DELETE أثر 0 صفوف "
            f"(channel_db_id={channel_db_id})"
        )
        return False

    # ── 4) 🆕 v1.1.0: التحقق الفعلي من الحذف ──
    if deleted_count < 0:
        # لم نستطع قراءة العدد — نتحقق يدوياً
        try:
            check = await DB.fetchone(
                f"SELECT 1 FROM user_channels WHERE id = {_ph(1)}",
                (channel_db_id,),
            )
            if check:
                logger.warning(
                    f"⚠️ _execute_delete: القناة لا تزال موجودة "
                    f"بعد DELETE — channel_db_id={channel_db_id}"
                )
                return False
        except Exception as e:
            logger.debug(f"verify deletion: {e}")
            # لا نستطيع التحقق — نفترض النجاح

    # ── 5) تسجيل في admin_logs ──
    try:
        if hasattr(DB, 'add_admin_log'):
            await DB.add_admin_log(
                chat_id=channel_id or 0,
                admin_id=user_id,
                action='channel_deleted',
                target_id=channel_db_id,
                reason=(
                    f'user manually deleted channel '
                    f'"{channel_name}" (id={channel_db_id})'
                ),
            )
    except Exception as e:
        logger.debug(f"add_admin_log: {e}")

    # ── 6) log ──
    logger.info(
        f"🗑️ حُذفت القناة {channel_db_id} "
        f"({channel_name}) بواسطة المستخدم {user_id} — "
        f"CASCADE محى كل المنشورات"
        + (
            f" [deleted={deleted_count}]"
            if deleted_count > 0 else ""
        )
    )

    return True


# ═════════════════════════════════════════════════════════════════════
# Callback Handlers
# ═════════════════════════════════════════════════════════════════════

async def _on_confirm_delete(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """معالج زر 'نعم، احذف نهائياً'."""
    query = update.callback_query
    if not query:
        return

    try:
        await query.answer()
    except Exception:
        pass

    user_id = query.from_user.id if query.from_user else 0
    if not user_id:
        return

    # ── استخراج channel_db_id ──
    try:
        data = query.data or ''
        parts = data.split(':', 1)
        if len(parts) != 2:
            return
        channel_db_id = int(parts[1])
    except (ValueError, IndexError):
        return

    # ── التحقق من صلاحية التأكيد ──
    if not _should_confirm(user_id, channel_db_id):
        try:
            await query.edit_message_text(
                text=(
                    "⏰ <b>انتهت صلاحية التأكيد</b>\n\n"
                    "يرجى بدء عملية الحذف من جديد."
                ),
                parse_mode='HTML',
            )
        except Exception:
            pass
        return

    # ── تنفيذ الحذف ──
    success = await _execute_delete(channel_db_id, user_id)

    # ── إزالة الطلب ──
    _clear_pending(user_id, channel_db_id)

    # ── الرد ──
    try:
        if success:
            await query.edit_message_text(
                text=(
                    "✅ <b>تم الحذف بنجاح</b>\n\n"
                    "🗑️ حُذفت القناة وجميع منشوراتها نهائياً.\n"
                    "شكراً لاستخدامك البوت 🌿"
                ),
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🏠 القائمة الرئيسية",
                        callback_data="main",
                    )],
                ]),
            )
        else:
            await query.edit_message_text(
                text=(
                    "❌ <b>فشل الحذف</b>\n\n"
                    "حدث خطأ أثناء الحذف. حاول لاحقاً أو "
                    "تواصل مع الدعم الفني."
                ),
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🏠 القائمة الرئيسية",
                        callback_data="main",
                    )],
                ]),
            )
    except Exception as e:
        logger.debug(f"edit confirm result: {e}")


async def _on_cancel_delete(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """معالج زر 'إلغاء'."""
    query = update.callback_query
    if not query:
        return

    try:
        await query.answer(text="✅ تم الإلغاء")
    except Exception:
        pass

    user_id = query.from_user.id if query.from_user else 0

    # ── استخراج channel_db_id لإزالة الطلب ──
    try:
        data = query.data or ''
        parts = data.split(':', 1)
        if len(parts) == 2:
            channel_db_id = int(parts[1])
            _clear_pending(user_id, channel_db_id)
    except (ValueError, IndexError):
        pass

    # ── العودة إلى قائمة القنوات ──
    try:
        await query.edit_message_text(
            text=(
                "✅ <b>تم الإلغاء</b>\n\n"
                "لم يتم حذف أي شيء."
            ),
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📡 قنواتي",
                    callback_data="channels",
                )],
                [InlineKeyboardButton(
                    "🏠 القائمة الرئيسية",
                    callback_data="main",
                )],
            ]),
        )
    except Exception as e:
        logger.debug(f"edit cancel result: {e}")


# ═════════════════════════════════════════════════════════════════════
# التسجيل
# ═════════════════════════════════════════════════════════════════════

def register_delete_confirmation(application) -> None:
    """
    تسجيل معالجات تأكيد الحذف في Application.

    استخدمها في main.py:
        from handlers.handlers_channels_delete import (
            register_delete_confirmation,
        )
        register_delete_confirmation(app)
    """
    try:
        application.add_handler(
            CallbackQueryHandler(
                _on_confirm_delete,
                pattern=r"^ch_confirm_delete:\d+$",
            ),
            group=-5,  # أولوية عالية (قبل callback العام)
        )
        application.add_handler(
            CallbackQueryHandler(
                _on_cancel_delete,
                pattern=r"^ch_cancel_delete:\d+$",
            ),
            group=-5,
        )
        logger.info(
            "✅ تم تسجيل handlers تأكيد حذف القناة "
            "(handlers_channels_delete v1.1.0)"
        )
    except Exception as e:
        logger.error(
            f"❌ فشل تسجيل delete confirmation: "
            f"{type(e).__name__}: {e}",
            exc_info=True,
        )


# ═════════════════════════════════════════════════════════════════════
# __all__
# ═════════════════════════════════════════════════════════════════════

__all__ = [
    "request_delete",
    "register_delete_confirmation",
    # Internal helpers (للاختبار)
    "_collect_channel_stats",
    "_execute_delete",
    "_verify_ownership",
    "_should_confirm",
    "_mark_pending",
    "_clear_pending",
    "_count_user_pending",
    "_clear_user_pending",
    "_prune_pending",
    "_get_db_type",
    "_ph",
    "_parse_delete_count",
    "_format_stats_text",
    "_build_confirm_keyboard",
    # Constants
    "_CONFIRM_TTL",
    "_MAX_PENDING_PER_USER",
    "_pending_confirms",
]