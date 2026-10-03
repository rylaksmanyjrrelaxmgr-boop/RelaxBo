#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
handlers/handlers_channels_delete.py - تأكيد حذف القنوات يدوياً (v1.0.0)
=====================================================================
🆕 v1.0.0-final:
    ✅ CONF-1: عرض إحصائيات كاملة قبل الحذف
               (عدد المنشورات، الجدول، آخر نشر)
    ✅ CONF-2: طلب تأكيد صريح مع أزرار [نعم/إلغاء]
    ✅ CONF-3: مهلة التأكيد 5 دقائق (يمنع الضغط المتأخر)
    ✅ CONF-4: دعم القنوات والمجموعات
    ✅ CONF-5: تسجيل الحذف في admin_logs
    ✅ CONF-6: إشعار فوري بعد الحذف
    ✅ CONF-7: التحقق من ملكية القناة (أمان)
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

# Cache مؤقت لطلبات التأكيد:
#   key = f"{user_id}:{channel_db_id}" → (timestamp, channel_name, user_id)
_pending_confirms: Dict[str, tuple] = {}


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


def _prune_pending() -> int:
    """تنظيف الطلبات المنتهية."""
    removed = 0
    now = time.monotonic()
    try:
        for k in list(_pending_confirms.keys()):
            if now - _pending_confirms[k][0] > _CONFIRM_TTL:
                _pending_confirms.pop(k, None)
                removed += 1
    except Exception:
        pass
    return removed


# ═════════════════════════════════════════════════════════════════════
# جمع الإحصائيات
# ═════════════════════════════════════════════════════════════════════

async def _collect_channel_stats(
    channel_db_id: int
) -> Dict[str, Any]:
    """
    جمع إحصائيات القناة قبل الحذف.

    Returns:
        dict يحتوي على:
        - posts_total: إجمالي المنشورات
        - posts_published: المنشورة
        - posts_unpublished: غير المنشورة
        - channel_name: اسم القناة
        - channel_id: معرف تيليجرام
        - has_schedule: هل لها جدول
        - last_publish: آخر نشر
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

    try:
        # معلومات القناة
        ch_row = await DB.fetchone(
            "SELECT channel_name, channel_id "
            "FROM user_channels WHERE id = ?",
            (channel_db_id,),
        )
        if ch_row:
            stats['channel_name'] = ch_row.get('channel_name') or ''
            stats['channel_id'] = ch_row.get('channel_id')

        # عدد المنشورات
        posts_row = await DB.fetchone(
            "SELECT "
            "  COUNT(*) AS total, "
            "  SUM(CASE WHEN published = 1 THEN 1 ELSE 0 END) AS published, "
            "  SUM(CASE WHEN published = 0 THEN 1 ELSE 0 END) AS unpublished "
            "FROM posts WHERE channel_db_id = ?",
            (channel_db_id,),
        )
        if posts_row:
            stats['posts_total'] = int(
                posts_row.get('total') or 0
            )
            stats['posts_published'] = int(
                posts_row.get('published') or 0
            )
            stats['posts_unpublished'] = int(
                posts_row.get('unpublished') or 0
            )

        # آخر نشر
        lp_row = await DB.fetchone(
            "SELECT last_publish_time FROM last_publish "
            "WHERE channel_db_id = ?",
            (channel_db_id,),
        )
        if lp_row:
            stats['last_publish'] = lp_row.get('last_publish_time')
            stats['has_schedule'] = True

    except Exception as e:
        logger.warning(
            f"⚠️ _collect_channel_stats({channel_db_id}): {e}"
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

    text = (
        f"⚠️ <b>تأكيد حذف القناة</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        f"📡 <b>القناة:</b> {safe_name}\n"
        f"🆔 <b>معرف القناة:</b> <code>{stats.get('channel_id', '—')}</code>\n\n"

        "📊 <b>ما سيُحذف نهائياً:</b>\n"
        f"   • <b>{total}</b> منشوراً إجمالاً\n"
        f"      ├─ 📤 {pub} منشوراً (منشور)\n"
        f"      └─ 📥 {unpub} منشوراً (لم يُنشر)\n"
        f"   • ⏰ الجدول الزمني للنشر\n"
        f"   • 📅 بيانات آخر نشر ({last_pub_str})\n\n"

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


async def request_delete(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    channel_db_id: int,
    channel_name: str = "",
    user_id: Optional[int] = None,
) -> bool:
    """
    طلب تأكيد حذف قناة.

    Args:
        update: كائن التحديث (لـ callback أو message)
        context: context PTB
        channel_db_id: معرّف القناة في قاعدة البيانات
        channel_name: اسم القناة (اختياري)
        user_id: معرّف المستخدم (يُستخرج تلقائياً إن لم يُمرَّر)

    Returns:
        True إذا نجح العرض
    """
    if user_id is None:
        if update.effective_user:
            user_id = update.effective_user.id
        else:
            return False

    if not channel_db_id:
        return False

    # تنظيف الطلبات القديمة
    _prune_pending()

    # جمع الإحصائيات
    stats = await _collect_channel_stats(channel_db_id)

    # إذا لم يُمرَّر اسم، استخدم من stats
    if not channel_name:
        channel_name = stats.get('channel_name') or "—"

    # تسجيل الطلب
    _mark_pending(user_id, channel_db_id, channel_name)

    # بناء النص والأزرار
    text = _format_stats_text(channel_name, stats)
    keyboard = _build_confirm_keyboard(channel_db_id)

    # عرض
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

    Returns:
        True إذا نجح
    """
    try:
        # التحقق من الملكية
        ch_row = await DB.fetchone(
            "SELECT user_id, channel_name, channel_id "
            "FROM user_channels WHERE id = ?",
            (channel_db_id,),
        )
        if not ch_row:
            logger.warning(
                f"⚠️ _execute_delete: القناة {channel_db_id} "
                f"غير موجودة"
            )
            return False

        # التحقق من أن المستخدم هو المالك
        owner_id = ch_row.get('user_id')
        if owner_id and int(owner_id) != int(user_id):
            logger.warning(
                f"⚠️ _execute_delete: المستخدم {user_id} "
                f"لا يملك القناة {channel_db_id} (المالك: {owner_id})"
            )
            return False

        channel_name = ch_row.get('channel_name') or ''
        channel_id = ch_row.get('channel_id')

        # ✅ الحذف (CASCADE يحذف المنشورات + schedule + last_publish)
        result = await DB.execute(
            "DELETE FROM user_channels WHERE id = ?",
            (channel_db_id,),
        )

        # تسجيل في admin_logs (اختياري)
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

        logger.info(
            f"🗑️ حُذفت القناة {channel_db_id} "
            f"({channel_name}) بواسطة المستخدم {user_id} — "
            f"CASCADE محى كل المنشورات"
        )

        return True

    except Exception as e:
        logger.error(
            f"❌ _execute_delete({channel_db_id}): "
            f"{type(e).__name__}: {e}",
            exc_info=True,
        )
        return False


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

    # استخراج channel_db_id
    try:
        data = query.data or ''
        parts = data.split(':', 1)
        if len(parts) != 2:
            return
        channel_db_id = int(parts[1])
    except (ValueError, IndexError):
        return

    # التحقق من صلاحية التأكيد
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

    # تنفيذ الحذف
    success = await _execute_delete(channel_db_id, user_id)

    # إزالة الطلب
    _clear_pending(user_id, channel_db_id)

    # الرد
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

    # استخراج channel_db_id لإزالة الطلب
    try:
        data = query.data or ''
        parts = data.split(':', 1)
        if len(parts) == 2:
            channel_db_id = int(parts[1])
            _clear_pending(user_id, channel_db_id)
    except (ValueError, IndexError):
        pass

    # العودة إلى قائمة القنوات
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
            "(handlers_channels_delete v1.0.0)"
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
    "_collect_channel_stats",
    "_execute_delete",
    "_should_confirm",
    "_mark_pending",
    "_clear_pending",
    "_prune_pending",
    "_CONFIRM_TTL",
    "_pending_confirms",
]