# handlers/handlers_group_log.py
"""
handlers_group_log.py — MessageHandler لاستقبال معرّف قناة السجل (v1.5.0)
=====================================================================
v1.5.0 (cache invalidation):
    ✅ إبطال كاش قائمة قناة السجل بعد set_private ناجح
    ✅ توافق كامل مع handlers_callback.py v9.4.0
    ✅ استيراد internal_cache من database

v1.4.0 (PTB v20+ fix):
    ✅ إصلاح AttributeError: forward_from_chat محذوف في PTB v20+
    ✅ دالة _extract_forward_channel متوافقة مع كل الإصدارات
    ✅ استخدام forward_origin (MessageOriginChannel)
    ✅ fallback لـ forward_from_chat (PTB v13.x)

v1.3.0 (تقرير المشاركة الذكي):
    ✅ set_private يُعيد dict — نعرض معلومات المشاركة للمستخدم
    ✅ عرض عدد المجموعات + الأسماء عند التعيين
    ✅ توضيح "كل رسالة ستحمل رأساً باسم مجموعتك"

v1.2.0:
    ✅ إصلاح import binding — get_group_log() ديناميكياً
    ✅ دعم send() المتزامن (Queue-based)
    ✅ دعم get_effective_target() للقناة النشطة
    ✅ حماية من حالات edge case
    ✅ دعم كامل للـStateManager (WAIT_LOG_CH)

v1.1.0:
    ✅ يستخدم StateManager + UserState.WAIT_LOG_CH
    ✅ يتوافق مع handlers_callback.py
    ✅ تنظيف الحالة بعد النجاح/الفشل
=====================================================================
"""

import logging
from html import escape as _html_escape
from typing import Optional, Tuple

from telegram import Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    filters, ContextTypes,
)

# ✅ استيراد الوحدة (لا المتغير) — لتجنب import binding
try:
    import group_log as _group_log_module
    _GROUP_LOG_MODULE_AVAILABLE = True
except ImportError as _e:
    _group_log_module = None
    _GROUP_LOG_MODULE_AVAILABLE = False
    _GROUP_LOG_IMPORT_ERROR = str(_e)

from utils import StateManager, UserState

# ✅ v1.5.0: استيراد internal_cache لإبطال كاش قائمة قناة السجل
try:
    from database import internal_cache as _internal_cache
    _INTERNAL_CACHE_AVAILABLE = True
except ImportError:
    _internal_cache = None
    _INTERNAL_CACHE_AVAILABLE = False

logger = logging.getLogger(__name__)


# =====================================================================
# كشف إصدار PTB للتوافقية
# =====================================================================

try:
    # PTB v20+
    from telegram import (
        MessageOriginChannel,
        MessageOriginChat,
        MessageOriginUser,
        MessageOriginHiddenUser,
    )
    _PTB_V20_PLUS = True
except ImportError:
    # PTB v13.x
    MessageOriginChannel = None
    MessageOriginChat = None
    MessageOriginUser = None
    MessageOriginHiddenUser = None
    _PTB_V20_PLUS = False


# =====================================================================
# مساعد للوصول الديناميكي
# =====================================================================

def _get_group_log():
    """يقرأ الـinstance الحالي من الوحدة (بعد init_group_log)."""
    if not _GROUP_LOG_MODULE_AVAILABLE or _group_log_module is None:
        return None
    return getattr(_group_log_module, "group_log", None)


def _safe_html(text) -> str:
    """استبدال HTML entities لتفادي كسر الرسالة."""
    return _html_escape(str(text or ""))


# =====================================================================
# ✅ v1.5.0: إبطال كاش قائمة قناة السجل (متوافق مع handlers_callback.py v9.4.0)
# =====================================================================

async def _invalidate_log_channel_menu_cache(chat_id: int) -> None:
    """
    إبطال كاش قائمة قناة السجل بعد تغيير حالة القناة.
    نفس المفتاح المستخدم في handlers_callback.py (v9.4.0).
    """
    if not _INTERNAL_CACHE_AVAILABLE or _internal_cache is None:
        return
    try:
        await _internal_cache.invalidate(f"log_ch_menu_{chat_id}")
    except Exception as e:
        logger.debug(f"_invalidate_log_channel_menu_cache({chat_id}): {e}")


# =====================================================================
# ✅ v1.4.0: استخراج معلومات القناة المُعاد توجيهها
# =====================================================================

def _extract_forward_channel(msg) -> Tuple[Optional[int], str]:
    """
    يستخرج (chat_id, title) للقناة المُعاد توجيه رسالة منها.
    متوافق مع PTB v20+ (forward_origin) و v13.x (forward_from_chat).

    Returns:
        (chat_id, title) — chat_id=None إذا لم تكن الرسالة من قناة.
    """
    # ─── PTB v20+ ───
    origin = getattr(msg, "forward_origin", None)
    if origin is not None:
        # قناة
        if _PTB_V20_PLUS and isinstance(origin, MessageOriginChannel):
            chat = getattr(origin, "chat", None)
            if chat is not None:
                cid = getattr(chat, "id", None)
                title = getattr(chat, "title", "") or ""
                return cid, title
        # محادثة (قد تكون قناة أو مجموعة)
        if _PTB_V20_PLUS and isinstance(origin, MessageOriginChat):
            chat = getattr(origin, "sender_chat", None)
            if chat is not None:
                ctype = getattr(chat, "type", None)
                if ctype == "channel":
                    cid = getattr(chat, "id", None)
                    title = getattr(chat, "title", "") or ""
                    return cid, title
        # مستخدم / مخفي — ليست قناة
        if _PTB_V20_PLUS and isinstance(
            origin, (MessageOriginUser, MessageOriginHiddenUser)
        ):
            return None, ""
        # أي كائن origin آخر — لا نعرف نوعه، نتجاهل
        return None, ""

    # ─── PTB v13.x fallback ───
    fwd_chat = getattr(msg, "forward_from_chat", None)
    if fwd_chat is not None:
        ctype = getattr(fwd_chat, "type", None)
        if ctype == "channel":
            cid = getattr(fwd_chat, "id", None)
            title = getattr(fwd_chat, "title", "") or ""
            return cid, title

    return None, ""


# =====================================================================
# استقبال معرّف قناة السجل
# =====================================================================

async def receive_log_channel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    يستقبل معرّف القناة أو رسالة موجّهة، ويحفظها كقناة سجل.
    """
    user = update.effective_user
    if not user:
        return

    # الفحص الأساسي: هل المستخدم في حالة انتظار؟
    state = StateManager.get(user.id)
    if state != UserState.WAIT_LOG_CH:
        return

    msg = update.message
    if not msg:
        return

    # ─── الإلغاء ───
    text = (msg.text or "").strip()
    if text.lower() in ("إلغاء", "الغاء", "cancel", "/cancel"):
        StateManager.clear(user.id)
        context.user_data.pop("log_group_id", None)
        context.user_data.pop("awaiting_log_channel_for", None)
        try:
            await msg.reply_text("❌ تم إلغاء العملية.")
        except Exception:
            pass
        return

    # ─── استرجاع group_id ───
    group_id = (
        context.user_data.get("log_group_id")
        or context.user_data.get("awaiting_log_channel_for")
    )
    if not group_id:
        logger.warning(
            f"⚠️ WAIT_LOG_CH بدون log_group_id للمستخدم {user.id}"
        )
        StateManager.clear(user.id)
        try:
            await msg.reply_text(
                "❌ انتهت الجلسة. ابدأ من جديد من لوحة الأمان."
            )
        except Exception:
            pass
        return

    # ─── فحص توفّر group_log ───
    gl = _get_group_log()
    if gl is None:
        logger.warning(
            "⚠️ group_log غير مُهيّأ — تأكد من استدعاء "
            "init_group_log(DB, bot) في bot.py"
        )
        StateManager.clear(user.id)
        context.user_data.pop("log_group_id", None)
        context.user_data.pop("awaiting_log_channel_for", None)
        try:
            await msg.reply_text(
                "❌ خدمة قناة السجل غير متوفرة حالياً.\n"
                "تواصل مع المطور."
            )
        except Exception:
            pass
        return

    # ─── استخراج chat_id ───
    # ✅ v1.4.0: استخدام الدالة المساعدة المتوافقة
    chat_id: Optional[int] = None
    title: str = ""

    forwarded_id, forwarded_title = _extract_forward_channel(msg)
    if forwarded_id is not None:
        chat_id = forwarded_id
        title = forwarded_title
    elif text and text.lstrip("-").isdigit():
        try:
            chat_id = int(text)
        except (ValueError, TypeError):
            chat_id = None

    if not chat_id:
        try:
            await msg.reply_text(
                "❌ أرسل معرّفاً رقمياً صحيحاً "
                "(مثل <code>-1001234567890</code>)\n"
                "أو <b>أعد توجيه رسالة</b> من القناة إلى هنا.\n\n"
                "للإلغاء: أرسل <b>إلغاء</b>.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    if chat_id == group_id:
        try:
            await msg.reply_text(
                "❌ لا يمكن استخدام المجموعة نفسها كقناة سجل.\n"
                "أضف قناة منفصلة."
            )
        except Exception:
            pass
        return

    # ─── التحقق: البوت مشرف في القناة؟ ───
    try:
        member = await context.bot.get_chat_member(
            chat_id, context.bot.id
        )
        if member.status not in ("administrator", "creator"):
            try:
                await msg.reply_text(
                    "❌ البوت ليس مشرفاً في هذه القناة.\n"
                    "أضِفه مشرفاً بصلاحية "
                    "<b>نشر الرسائل</b> ثم أعد المحاولة.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return
    except Exception as e:
        logger.warning(
            f"⚠️ فشل فحص صلاحيات البوت في {chat_id}: {e}"
        )
        try:
            await msg.reply_text(
                f"❌ تعذّر الوصول للقناة:\n"
                f"<code>{_safe_html(str(e)[:150])}</code>\n\n"
                f"تأكد أن:\n"
                f"• البوت عضو في القناة\n"
                f"• البوت مشرف فيها",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    # ─── فحص صلاحية النشر ───
    try:
        can_post = getattr(member, "can_post_messages", True)
        if member.status == "administrator" and can_post is False:
            try:
                await msg.reply_text(
                    "⚠️ البوت مشرف لكن بدون صلاحية "
                    "<b>نشر الرسائل</b>.\n"
                    "فعّل الصلاحية ثم أعد المحاولة.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return
    except Exception:
        pass

    # ─── محاولة استخراج عنوان القناة ───
    try:
        chat_obj = await context.bot.get_chat(chat_id)
        if chat_obj and chat_obj.title:
            title = chat_obj.title
        elif chat_obj and chat_obj.username:
            title = f"@{chat_obj.username}"
    except Exception:
        pass

    # ─── الحفظ في قاعدة البيانات ───
    try:
        result = await gl.set_private(group_id, chat_id)
    except Exception as e:
        logger.error(
            f"❌ gl.set_private فشل: {e}", exc_info=True
        )
        result = {'ok': False}

    # ✅ تنظيف الحالة
    StateManager.clear(user.id)
    context.user_data.pop("log_group_id", None)
    context.user_data.pop("awaiting_log_channel_for", None)

    # ─── النتيجة ───
    ok = result.get('ok', False) if isinstance(result, dict) else bool(result)

    if ok:
        # ✅ v1.5.0: إبطال كاش قائمة قناة السجل
        try:
            await _invalidate_log_channel_menu_cache(group_id)
        except Exception as e:
            logger.debug(
                f"invalidate log_channel_menu cache failed: {e}"
            )

        # ✅ v1.3.0: عرض حالة المشاركة
        share_notice = ""
        if isinstance(result, dict) and result.get('shared'):
            count = result.get('share_count', 0)
            others = result.get('other_groups', [])
            others_str = "، ".join(
                _safe_html(o) for o in others
            ) if others else "—"

            share_notice = (
                f"\n\n🤝 <b>قناة مشتركة</b>\n"
                f"👥 <b>{count + 1} مجموعات</b> تستخدم هذه القناة\n"
                f"📋 <i>المجموعات الأخرى:</i> "
                f"<code>{others_str}</code>\n\n"
                f"💡 <b>كل رسالة ستحمل رأساً يحمل اسم مجموعتك</b>"
                f" لتمييز المصدر في القناة."
            )

        try:
            await msg.reply_text(
                f"✅ <b>تم تعيين قناة السجل بنجاح</b>\n\n"
                f"📌 المجموعة: <code>{group_id}</code>\n"
                f"📢 القناة: <code>{chat_id}</code>"
                + (f"\n🏷️ العنوان: {_safe_html(title)}" if title else "")
                + share_notice,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"فشل إرسال تأكيد التعيين: {e}")

        # إرسال رسالة اختبار
        try:
            gl.send(
                group_id,
                "🧪 <b>رسالة اختبار</b>\n"
                "قناة السجل تعمل بنجاح! ✅\n"
                "<i>هذه الرسالة من اختبار الإعداد.</i>",
                event="general",
                silent=False,
            )
        except Exception as e:
            logger.warning(f"⚠️ اختبار الإرسال فشل: {e}")
    else:
        try:
            await msg.reply_text(
                "❌ فشل الحفظ في قاعدة البيانات.\n"
                "تحقق من السجلات (Logs) لمعرفة السبب."
            )
        except Exception as e:
            logger.warning(f"فشل إرسال رسالة الخطأ: {e}")


# =====================================================================
# إلغاء الانتظار — أمر مستقل
# =====================================================================

async def cancel_log_channel_wait(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """معالج مستقل لإلغاء الانتظار بأمر /cancel_group_log."""
    user = update.effective_user
    if not user:
        return

    if StateManager.get(user.id) != UserState.WAIT_LOG_CH:
        return

    StateManager.clear(user.id)
    context.user_data.pop("log_group_id", None)
    context.user_data.pop("awaiting_log_channel_for", None)
    try:
        await update.message.reply_text(
            "❌ تم إلغاء انتظار قناة السجل."
        )
    except Exception:
        pass


# =====================================================================
# تسجيل المعالجات
# =====================================================================

def register_group_log_handlers(app: Application) -> None:
    """يُسجّل MessageHandler في Application."""
    if app is None:
        logger.error("❌ register_group_log_handlers: app=None")
        return

    # 1) معالج الرسائل الرئيسي
    app.add_handler(
        MessageHandler(
            (filters.FORWARDED | filters.TEXT) & ~filters.COMMAND,
            receive_log_channel,
        ),
        group=1,
    )

    # 2) أمر إلغاء الانتظار
    try:
        app.add_handler(
            CommandHandler(
                "cancel_group_log", cancel_log_channel_wait
            ),
            group=1,
        )
    except Exception as e:
        logger.debug(f"cancel_group_log handler: {e}")

    logger.info(
        "✅ handlers قناة السجل مُسجَّل (group=1)"
    )


__all__ = [
    "receive_log_channel",
    "cancel_log_channel_wait",
    "register_group_log_handlers",
]
