# handlers/handlers_group_log.py
"""
handlers_group_log.py — MessageHandler لاستقبال معرّف قناة السجل
=====================================================================
v1.0.0
- يستقبل معرّف القناة كنص أو رسالة موجّهة
- يتحقق أن البوت مشرف في القناة
- يحفظ `log_channel_id` في `bot_groups` عبر group_log.set_private
- يرسل رسالة اختبار للتأكد
"""

import logging
from telegram import Update
from telegram.ext import (
    Application, MessageHandler, filters, ContextTypes
)

try:
    from group_log import group_log
except ImportError:
    group_log = None

logger = logging.getLogger(__name__)


# =====================================================================
# استقبال معرّف قناة السجل
# =====================================================================

async def receive_log_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    يستقبل معرّف القناة أو رسالة موجّهة من قناة، ويحفظها كقناة سجل
    للمجموعة المخزّنة في context.user_data['awaiting_log_channel_for'].
    """
    group_id = context.user_data.get("awaiting_log_channel_for")
    if not group_id:
        # لا يوجد انتظار لمعرّف قناة — نتجاهل
        return

    if group_log is None:
        logger.warning("⚠️ group_log غير مُهيّأ — تجاهل الرسالة")
        return

    msg = update.message
    if not msg:
        return

    chat_id = None
    title = ""

    # (أ) رسالة موجّهة من قناة
    if msg.forward_from_chat and msg.forward_from_chat.type == "channel":
        chat_id = msg.forward_from_chat.id
        title = msg.forward_from_chat.title or ""

    # (ب) نص = معرّف رقمي (مثل -1001234567890)
    elif msg.text and msg.text.strip().lstrip("-").isdigit():
        chat_id = int(msg.text.strip())

    if not chat_id:
        await msg.reply_text(
            "❌ أرسل معرّفاً رقمياً صحيحاً (مثل <code>-1001234567890</code>)\n"
            "أو <b>أعد توجيه رسالة</b> من القناة إلى هنا.",
            parse_mode="HTML",
        )
        return

    # التحقق: البوت مشرف في القناة؟
    try:
        member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if member.status not in ("administrator", "creator"):
            await msg.reply_text(
                "❌ البوت ليس مشرفاً في هذه القناة.\n"
                "أضِفه مشرفاً بصلاحية <b>نشر الرسائل</b> ثم أعد المحاولة.",
                parse_mode="HTML",
            )
            return
    except Exception as e:
        await msg.reply_text(
            f"❌ تعذّر الوصول للقناة:\n<code>{str(e)[:150]}</code>\n\n"
            "تأكد أن:\n"
            "• البوت عضو في القناة\n"
            "• البوت مشرف فيها",
            parse_mode="HTML",
        )
        return

    # الحفظ
    ok = await group_log.set_private(group_id, chat_id)
    context.user_data.pop("awaiting_log_channel_for", None)
    context.user_data.pop("log_group_id", None)

    if ok:
        await msg.reply_text(
            f"✅ <b>تم تعيين قناة السجل بنجاح</b>\n\n"
            f"المجموعة: <code>{group_id}</code>\n"
            f"القناة: <code>{chat_id}</code>",
            parse_mode="HTML",
        )
        # رسالة اختبار
        try:
            await group_log.send(
                group_id,
                "🧪 <b>رسالة اختبار</b>\n"
                "قناة السجل تعمل بنجاح! ✅\n"
                "<i>هذه الرسالة من اختبار الإعداد.</i>",
                event="general",
                silent=False,
            )
        except Exception as e:
            logger.warning(f"اختبار الإرسال فشل: {e}")
    else:
        await msg.reply_text(
            "❌ فشل الحفظ في قاعدة البيانات.\n"
            "تحقق من السجلات (Logs) لمعرفة السبب.",
        )


# =====================================================================
# تسجيل المعالج
# =====================================================================

def register_group_log_handlers(app: Application):
    """
    يُسجّل MessageHandler في Application.
    يُنادَى من bot.py بعد init_group_log.
    """
    app.add_handler(
        MessageHandler(
            (filters.FORWARDED | filters.TEXT) & ~filters.COMMAND,
            receive_log_channel,
        ),
        group=1,  # ⬅️ group=1 ليعمل بالتوازي مع باقي handlers
    )
    logger.info("✅ handlers قناة السجل مُسجَّل")


__all__ = [
    "receive_log_channel",
    "register_group_log_handlers",
]