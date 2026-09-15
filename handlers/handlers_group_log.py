# handlers/handlers_group_log.py
"""
handlers_group_log.py — MessageHandler لاستقبال معرّف قناة السجل (v1.2.0)
=====================================================================
✅ v1.2.0 (المُدمَجة النهائية):
    🔧 إصلاح import binding — استخدام get_group_log() ديناميكياً
    🔧 استخدام send() المتزامن (Queue-based) في group_log v1.2.0
    ✅ دعم StateManager + UserState.WAIT_LOG_CH
    ✅ دعم الإلغاء بكلمة "إلغاء"/"cancel"
    ✅ أمر /cancel_group_log لإلغاء الانتظار
    ✅ فحص أن البوت مشرف + can_post_messages
    ✅ فحص أن القناة ليست المجموعة نفسها
    ✅ عرض عنوان القناة في رسالة التأكيد
    ✅ تنظيف الحالة دائماً (نجاح/فشل/إلغاء)
    ✅ حماية شاملة من edge cases

📌 v1.0.0 (الأساس):
    - يستقبل معرّف القناة كنص أو رسالة موجّهة
    - يتحقق أن البوت مشرف في القناة
    - يحفظ log_channel_id في bot_groups عبر group_log.set_private
    - يرسل رسالة اختبار للتأكد
=====================================================================
"""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    filters, ContextTypes,
)

# ✅ v1.2.0: استيراد الوحدة (لا المتغير) — لإصلاح import binding
try:
    import group_log as _group_log_module
    _GROUP_LOG_MODULE_AVAILABLE = True
except ImportError as _e:
    _group_log_module = None
    _GROUP_LOG_MODULE_AVAILABLE = False
    _GROUP_LOG_IMPORT_ERROR = str(_e)

from utils import StateManager, UserState

logger = logging.getLogger(__name__)


# =====================================================================
# ✅ v1.2.0: مساعد للوصول الديناميكي إلى الـinstance
# =====================================================================

def _get_group_log():
    """
    يقرأ الـinstance الحالي من الوحدة (بعد init_group_log).
    لا ينسخ القيمة — يتعامل مع النموذج المحدّث في كل استدعاء.
    """
    if not _GROUP_LOG_MODULE_AVAILABLE or _group_log_module is None:
        return None
    return getattr(_group_log_module, "group_log", None)


# =====================================================================
# استقبال معرّف قناة السجل
# =====================================================================

async def receive_log_channel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    يستقبل معرّف القناة أو رسالة موجّهة من قناة، ويحفظها كقناة سجل
    للمجموعة المخزّنة في context.user_data['log_group_id'].

    ✅ v1.2.0:
        - يقرأ الحالة من StateManager (متوافق مع handlers_callback)
        - يستخدم get_group_log() ديناميكياً
        - ينظّف الحالة بعد النجاح/الفشل
        - يدعم الإلغاء بكلمة "إلغاء" / "cancel"
        - يستخدم send() المتزامن (Queue-based)
    """
    user = update.effective_user
    if not user:
        return

    # ✅ الفحص الأساسي: هل المستخدم في حالة انتظار معرّف قناة؟
    state = StateManager.get(user.id)
    if state != UserState.WAIT_LOG_CH:
        return  # ليس دوره — تجاهل بهدوء

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

    # ─── استرجاع group_id (دعم كلا المفتاحين) ───
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
    chat_id: Optional[int] = None
    title: str = ""

    # (أ) رسالة موجّهة من قناة
    if msg.forward_from_chat and msg.forward_from_chat.type == "channel":
        chat_id = msg.forward_from_chat.id
        title = msg.forward_from_chat.title or ""

    # (ب) نص = معرّف رقمي (مثل -1001234567890)
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

    # ─── فحص أن القناة ليست المجموعة نفسها ───
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
                f"<code>{str(e)[:150]}</code>\n\n"
                f"تأكد أن:\n"
                f"• البوت عضو في القناة\n"
                f"• البوت مشرف فيها",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    # ─── فحص صلاحية النشر (can_post_messages) ───
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
        ok = await gl.set_private(group_id, chat_id)
    except Exception as e:
        logger.error(
            f"❌ gl.set_private فشل: {e}", exc_info=True
        )
        ok = False

    # ✅ تنظيف الحالة بعد المحاولة (نجحت أو فشلت)
    StateManager.clear(user.id)
    context.user_data.pop("log_group_id", None)
    context.user_data.pop("awaiting_log_channel_for", None)

    # ─── النتيجة ───
    if ok:
        try:
            await msg.reply_text(
                f"✅ <b>تم تعيين قناة السجل بنجاح</b>\n\n"
                f"📌 المجموعة: <code>{group_id}</code>\n"
                f"📢 القناة: <code>{chat_id}</code>"
                + (f"\n🏷️ العنوان: {title}" if title else ""),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning(f"فشل إرسال تأكيد التعيين: {e}")

        # =============================================================
        # إرسال رسالة اختبار للقناة
        # =============================================================
        try:
            # ✅ v1.2.0: send() متزامن (يضع في Queue)
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
# إلغاء الانتظار — معالج مستقل
# =====================================================================

async def cancel_log_channel_wait(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    ✅ v1.2.0: معالج مستقل لإلغاء الانتظار بأمر /cancel_group_log.
    مفيد لو المستخدم عالق.
    """
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
    """
    يُسجّل MessageHandler في Application.
    يُنادَى من bot.py بعد init_group_log.

    ✅ v1.2.0:
        - group=1 (يعمل بالتوازي مع handle_private)
        - يجب أن يتجاهل handle_private الحالة WAIT_LOG_CH أولاً
        - CommandHandler منفصل لإلغاء الانتظار
    """
    if app is None:
        logger.error("❌ register_group_log_handlers: app=None")
        return

    # 1) معالج الرسائل الرئيسي (نص + موجّه)
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