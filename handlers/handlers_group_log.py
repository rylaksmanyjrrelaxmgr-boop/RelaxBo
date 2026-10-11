# handlers/handlers_group_log.py
r"""
handlers_group_log.py — MessageHandler لاستقبال معرّف قناة السجل (v1.6.6)
=====================================================================
🆕 v1.6.6 (PY312-COMPAT + TELEGRAM.DOG):
    🔴 F12  asyncio.iscoroutine → inspect.isawaitable
            (iscoroutine مهجور في Python 3.12+, ويفشل مع بعض الـ awaitables)
    🟡 F13  دعم telegram.dog في _TME_LINK_RE + _TME_INVITE_RE + _URL_PREFIXES
            (توافق مع handlers_message_detectors v4.1.0)
    🟡 F14  getattr(chat_obj, "title"/"username", None) — أمان ضد None
    🟢 F15  _GROUP_LOG_IMPORT_ERROR = None مبدئياً (منع NameError محتمل)
    🟢 F16  logger % بدل f-string في بعض المواضع الحساسة

🆕 v1.6.5 (TITLE-FALLBACK + TOTAL-TIMEOUT):
    🟡 G1  Title fallback عند فشل جلب العنوان: "قناة <id>"
    🟡 G2  _resolve_username_with_retry: total_timeout خارجي (12s)
    🟡 G3  Get_chat for title: total_timeout=6.0s صريح

🆕 v1.6.4 (SYNTAX-WARNING-FIX):
    ✅ إضافة r prefix لـdocstring الرئيسي

🆕 v1.6.3 (SECURITY + UX FIXES):
    🔴 F1  رفض الرسائل المُعاد توجيهها من مستخدم صراحةً
    🔴 F2  _passes_initial_validation: قبول صريح لصيغ URL
    🟠 F3  حماية context.user_data من None
    🟠 F4  حذف (?:\+)? المُضلِّل من _TME_LINK_RE
    🟠 F5  _resolve_username_with_retry: asyncio.wait_for timeout=5s
    🟡 F6  _TG_USERNAME_RE: {4,31} بدل {3,31}
    🟡 F7  title من username يُضاف @
    🟡 F8  _extract_forward_channel: log عند origin غير معروف
    ⚪ F9  حذف prefix "v1.6.2:" من رسائل السجل
    ⚪ F10 except:pass → logger.debug
    ⚪ F11 gl.send: فحص iscoroutine

🆕 v1.6.2: استخدام _is_valid_channel_ref كطبقة تحقق أولى
🆕 v1.6.1: retry خفيف + كشف موحّد + معالجة "المجموعة نفسها"
🆕 v1.6.0: يقبل @username و t.me/username و https://t.me/...
           يحلّ @username إلى chat_id، يرفض invite links
🆕 v1.5.0: إبطال كاش قائمة قناة السجل
🆕 v1.4.0: PTB v20+ fix (forward_origin)
=====================================================================
"""

import asyncio
import inspect
import logging
import re
from html import escape as _html_escape
from typing import Optional, Tuple, Any

from telegram import Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    filters, ContextTypes,
)

# ✅ استيراد الوحدة (لا المتغير) — لتجنب import binding
_GROUP_LOG_IMPORT_ERROR: Optional[str] = None  # 🆕 F15: مُعرَّف مبدئياً
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

# ✅ v1.6.0: استيراد أداة التحقق
try:
    from database_settings import _is_valid_channel_ref
except ImportError:
    _is_valid_channel_ref = None

logger = logging.getLogger(__name__)


# =====================================================================
# 🆕 v1.6.5: ثوابت المهلات الزمنية
# =====================================================================

_RESOLVE_TOTAL_TIMEOUT = 12.0
_GET_CHAT_TITLE_TIMEOUT = 6.0
_USERNAME_RESOLVE_ATTEMPT_TIMEOUT = 5.0
_USERNAME_RESOLVE_ATTEMPTS = 2
_USERNAME_RESOLVE_DELAY = 0.5


# =====================================================================
# ✅ v1.6.0 + v1.6.3 + v1.6.6: Regex للمساعدة في استخراج username
# =====================================================================

# ✅ F6 (v1.6.3): Telegram يتطلب 5 أحرف — نقبل 4 للبوتات القديمة
_TG_USERNAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$')

# ✅ F4 (v1.6.3): نمط رابط t.me/username — بدون (?:\+)?
# ✅ F13 (v1.6.6): دعم telegram.dog
_TME_LINK_RE = re.compile(
    r'^(?:https?://)?(?:www\.)?'
    r'(?:t\.me|telegram\.me|telegram\.dog)/'
    r'([A-Za-z][A-Za-z0-9_]{4,31})'
    r'(?:[/?#].*)?$',
    re.IGNORECASE,
)

# رابط دعوة (invite link) — لا يمكن حلّه إلى chat_id بدون join
# ✅ F13 (v1.6.6): دعم telegram.dog
_TME_INVITE_RE = re.compile(
    r'^(?:https?://)?(?:www\.)?'
    r'(?:t\.me|telegram\.me|telegram\.dog)/'
    r'(?:\+|joinchat/)',
    re.IGNORECASE,
)

# ✅ F2 (v1.6.3): كشف صيغ URL للقبول الصريح
# ✅ F13 (v1.6.6): دعم telegram.dog
_URL_PREFIXES = (
    'https://', 'http://',
    't.me/', 'telegram.me/', 'telegram.dog/',
    'www.t.me/', 'www.telegram.me/', 'www.telegram.dog/',
)


def _looks_like_url(text: str) -> bool:
    """✅ F2 (v1.6.3) + F13 (v1.6.6): فحص سريع لصيغ URL."""
    if not text:
        return False
    low = text.lower()
    if low.startswith(_URL_PREFIXES):
        return True
    if _TME_LINK_RE.match(text):
        return True
    return False


def _normalize_channel_input(text: str) -> Tuple[Optional[int], Optional[str]]:
    """
    ✅ v1.6.0: يُحلّل المدخل النصي ويُعيد:
      - (chat_id_int, None) إذا كان رقماً
      - (None, username) إذا كان @username أو username
      - (None, None) إذا كان رابط invite أو غير صالح
    """
    if not text:
        return None, None

    v = text.strip()
    if not v:
        return None, None

    # 1) معرّف رقمي (قد يكون سالباً)
    if v.lstrip('-').isdigit():
        try:
            return int(v), None
        except (ValueError, TypeError):
            return None, None

    # 2) رابط دعوة (invite) — مرفوض
    if _TME_INVITE_RE.match(v):
        return None, None

    # 3) @username
    if v.startswith('@'):
        username = v[1:]
        if _TG_USERNAME_RE.match(username):
            return None, username
        return None, None

    # 4) username مباشر
    if _TG_USERNAME_RE.match(v):
        return None, v

    # 5) رابط t.me/username
    m = _TME_LINK_RE.match(v)
    if m:
        username = m.group(1)
        if _TG_USERNAME_RE.match(username):
            return None, username

    return None, None


# =====================================================================
# كشف إصدار PTB للتوافقية
# =====================================================================

try:
    from telegram import (
        MessageOriginChannel,
        MessageOriginChat,
        MessageOriginUser,
        MessageOriginHiddenUser,
    )
    _PTB_V20_PLUS = True
except ImportError:
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


def _safe_pop_user_data(context, *keys) -> None:
    """✅ F3 (v1.6.3): حماية context.user_data من None."""
    if context is None:
        return
    ud = getattr(context, 'user_data', None)
    if ud is None:
        return
    for k in keys:
        try:
            ud.pop(k, None)
        except Exception:
            pass


def _is_awaitable(obj) -> bool:
    """
    ✅ F12 (v1.6.6): فحص عام للـ awaitable.

    أكثر أماناً من asyncio.iscoroutine (مهجور في Python 3.12+).
    """
    return inspect.isawaitable(obj)


# =====================================================================
# ✅ v1.6.1: كشف موحّد للرسائل المُعاد توجيهها
# =====================================================================

def _is_forwarded(msg) -> bool:
    """✅ v1.6.1: كشف شامل لرسالة معاد توجيهها."""
    if msg is None:
        return False
    if getattr(msg, "forward_origin", None) is not None:
        return True
    if getattr(msg, "forward_date", None) is not None:
        return True
    if getattr(msg, "forward_from", None) is not None:
        return True
    if getattr(msg, "forward_from_chat", None) is not None:
        return True
    if getattr(msg, "forward_sender_name", None) is not None:
        return True
    return False


# =====================================================================
# ✅ v1.5.0: إبطال كاش قائمة قناة السجل
# =====================================================================

async def _invalidate_log_channel_menu_cache(chat_id: int) -> None:
    """إبطال كاش قائمة قناة السجل بعد تغيير حالة القناة."""
    if not _INTERNAL_CACHE_AVAILABLE or _internal_cache is None:
        return
    try:
        await _internal_cache.invalidate(f"log_ch_menu_{chat_id}")
    except Exception as e:
        logger.debug(
            "_invalidate_log_channel_menu_cache(%s): %s", chat_id, e
        )


# =====================================================================
# ✅ v1.4.0 + v1.6.3: استخراج معلومات القناة المُعاد توجيهها
# =====================================================================

def _extract_forward_channel(msg) -> Tuple[Optional[int], str]:
    """
    يستخرج (chat_id, title) للقناة المُعاد توجيه رسالة منها.
    متوافق مع PTB v20+ (forward_origin) و v13.x (forward_from_chat).
    """
    # ─── PTB v20+ ───
    origin = getattr(msg, "forward_origin", None)
    if origin is not None:
        if _PTB_V20_PLUS and isinstance(origin, MessageOriginChannel):
            chat = getattr(origin, "chat", None)
            if chat is not None:
                cid = getattr(chat, "id", None)
                title = getattr(chat, "title", None) or ""
                return cid, title
        if _PTB_V20_PLUS and isinstance(origin, MessageOriginChat):
            chat = getattr(origin, "sender_chat", None)
            if chat is not None:
                ctype = getattr(chat, "type", None)
                if ctype == "channel":
                    cid = getattr(chat, "id", None)
                    title = getattr(chat, "title", None) or ""
                    return cid, title
        if _PTB_V20_PLUS and isinstance(
            origin, (MessageOriginUser, MessageOriginHiddenUser)
        ):
            return None, ""
        # ✅ F8 (v1.6.3): log عند origin غير معروف
        logger.debug(
            "_extract_forward_channel: unknown origin type: %s",
            type(origin).__name__,
        )
        return None, ""

    # ─── PTB v13.x fallback ───
    fwd_chat = getattr(msg, "forward_from_chat", None)
    if fwd_chat is not None:
        ctype = getattr(fwd_chat, "type", None)
        if ctype == "channel":
            cid = getattr(fwd_chat, "id", None)
            title = getattr(fwd_chat, "title", None) or ""
            return cid, title

    return None, ""


# =====================================================================
# ✅ v1.6.1 + v1.6.3 + v1.6.5: حلّ @username مع retry و timeout
# =====================================================================

async def _resolve_username_with_retry(
    bot,
    username: str,
    max_attempts: int = _USERNAME_RESOLVE_ATTEMPTS,
    delay: float = _USERNAME_RESOLVE_DELAY,
    timeout: float = _USERNAME_RESOLVE_ATTEMPT_TIMEOUT,
    total_timeout: float = _RESOLVE_TOTAL_TIMEOUT,
) -> Tuple[Optional[int], str]:
    """
    ✅ v1.6.1: يحلّ @username إلى (chat_id, title) مع retry.
    ✅ F5 (v1.6.3): asyncio.wait_for بـ timeout=5s.
    ✅ F7 (v1.6.3): title من username يُضاف @.
    ✅ G2 (v1.6.5): total_timeout خارجي شامل (12s).
    ✅ F14 (v1.6.6): getattr لـ title/username.
    """
    async def _do_attempts():
        for attempt in range(max_attempts):
            try:
                chat_obj = await asyncio.wait_for(
                    bot.get_chat(f"@{username}"),
                    timeout=timeout,
                )
                if chat_obj is not None:
                    cid = getattr(chat_obj, "id", None)
                    # ✅ F14: getattr للسلامة
                    chat_title = getattr(chat_obj, "title", None) or ""
                    chat_username = (
                        getattr(chat_obj, "username", None) or ""
                    )
                    if chat_title:
                        title = chat_title
                    elif chat_username:
                        title = f"@{chat_username}"
                    else:
                        title = f"@{username}"
                    return cid, title
            except asyncio.TimeoutError:
                logger.debug(
                    "_resolve_username_with_retry (@%s) "
                    "attempt %d/%d: timeout",
                    username, attempt + 1, max_attempts,
                )
                if attempt < max_attempts - 1:
                    try:
                        await asyncio.sleep(delay)
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(
                    "_resolve_username_with_retry (@%s) "
                    "attempt %d/%d: %s",
                    username, attempt + 1, max_attempts, e,
                )
                if attempt < max_attempts - 1:
                    try:
                        await asyncio.sleep(delay)
                    except Exception:
                        pass
        return None, ""

    # ✅ G2: سقف زمني شامل
    try:
        return await asyncio.wait_for(
            _do_attempts(), timeout=total_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "_resolve_username_with_retry(@%s): "
            "total_timeout (%ss) reached",
            username, total_timeout,
        )
        return None, ""


# =====================================================================
# ✅ v1.6.2 + v1.6.3: طبقة تحقق أولى
# =====================================================================

def _passes_initial_validation(text: str) -> bool:
    """
    ✅ v1.6.2: طبقة تحقق أولى (fail-open).
    ✅ F2 (v1.6.3): قبول صريح لصيغ URL.
    """
    if _looks_like_url(text):
        return True

    if _is_valid_channel_ref is None:
        return True
    try:
        return bool(_is_valid_channel_ref(text))
    except Exception as e:
        logger.debug("_passes_initial_validation exception: %s", e)
        return True


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
    if text.lower() in ("إلغاء", "الغاء", "cancel", "/cancel", "none"):
        StateManager.clear(user.id)
        _safe_pop_user_data(
            context, "log_group_id", "awaiting_log_channel_for"
        )
        try:
            await msg.reply_text("❌ تم إلغاء العملية.")
        except Exception as e:
            logger.debug("reply_text (cancel) failed: %s", e)
        return

    # ─── استرجاع group_id ───
    ud = getattr(context, 'user_data', None) or {}
    group_id = (
        ud.get("log_group_id")
        or ud.get("awaiting_log_channel_for")
    )
    if not group_id:
        logger.warning(
            "⚠️ WAIT_LOG_CH بدون log_group_id للمستخدم %s", user.id
        )
        StateManager.clear(user.id)
        try:
            await msg.reply_text(
                "❌ انتهت الجلسة. ابدأ من جديد من لوحة الأمان."
            )
        except Exception as e:
            logger.debug("reply_text (no group_id) failed: %s", e)
        return

    # ─── فحص توفّر group_log ───
    gl = _get_group_log()
    if gl is None:
        logger.warning(
            "⚠️ group_log غير مُهيّأ — تأكد من استدعاء "
            "init_group_log(DB, bot) في bot.py"
        )
        StateManager.clear(user.id)
        _safe_pop_user_data(
            context, "log_group_id", "awaiting_log_channel_for"
        )
        try:
            await msg.reply_text(
                "❌ خدمة قناة السجل غير متوفرة حالياً.\n"
                "تواصل مع المطور."
            )
        except Exception as e:
            logger.debug("reply_text (no gl) failed: %s", e)
        return

    # ─── ✅ v1.6.2: استخراج/حلّ chat_id ───
    chat_id: Optional[int] = None
    title: str = ""

    # 1) من رسالة معاد توجيهها
    is_fwd = _is_forwarded(msg)
    if is_fwd:
        forwarded_id, forwarded_title = _extract_forward_channel(msg)
        if forwarded_id is not None:
            chat_id = forwarded_id
            title = forwarded_title
            logger.info(
                "✅ chat_id من forwarded: %s (%r)",
                chat_id, title,
            )
        else:
            # ✅ F1: رسالة موجّهة من مستخدم/غير قناة → رفض
            logger.info(
                "⛔ F1: رسالة موجّهة من مستخدم/غير قناة — مرفوضة"
            )
            try:
                await msg.reply_text(
                    "❌ <b>هذه رسالة مُعاد توجيهها من مستخدم</b>، "
                    "وليست من قناة.\n\n"
                    "الرجاء:\n"
                    "• أعد توجيه رسالة <b>من القناة نفسها</b>، أو\n"
                    "• أرسل المعرّف الرقمي أو الرابط مباشرة.\n\n"
                    "للإلغاء: أرسل <b>إلغاء</b>.",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.debug("reply_text (user-forward) failed: %s", e)
            return

    # 2) من النص
    if chat_id is None and text:
        if not _passes_initial_validation(text):
            logger.info(
                "⛔ رفض النص عبر _is_valid_channel_ref: %r",
                text[:50],
            )
            try:
                await msg.reply_text(
                    "❌ <b>قيمة غير صالحة</b>\n\n"
                    "أرسل أحد التالي:\n"
                    "• معرّف رقمي: <code>-1001234567890</code>\n"
                    "• <code>@username</code>\n"
                    "• <code>username</code>\n"
                    "• رابط: <code>https://t.me/username</code>\n"
                    "• أو <b>أعد توجيه رسالة</b> من القناة\n\n"
                    "⚠️ روابط الدعوة (<code>t.me/+abc</code>) غير مدعومة.\n"
                    "للإلغاء: أرسل <b>إلغاء</b>.",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.debug("reply_text (invalid) failed: %s", e)
            return

        parsed_id, parsed_username = _normalize_channel_input(text)

        if parsed_id is not None:
            chat_id = parsed_id
            logger.debug("📍 chat_id من نص رقمي: %s", chat_id)
        elif parsed_username is not None:
            resolved_id, resolved_title = (
                await _resolve_username_with_retry(
                    context.bot, parsed_username,
                    max_attempts=_USERNAME_RESOLVE_ATTEMPTS,
                    delay=_USERNAME_RESOLVE_DELAY,
                    timeout=_USERNAME_RESOLVE_ATTEMPT_TIMEOUT,
                    total_timeout=_RESOLVE_TOTAL_TIMEOUT,
                )
            )
            if resolved_id is not None:
                chat_id = resolved_id
                title = resolved_title
                logger.debug(
                    "📍 chat_id من @%s: %s (%s)",
                    parsed_username, chat_id, title,
                )
            else:
                try:
                    await msg.reply_text(
                        f"❌ لم أتمكن من الوصول إلى "
                        f"<code>@{_safe_html(parsed_username)}</code>\n\n"
                        f"تأكد أن:\n"
                        f"• القناة <b>عامة</b> (لها username)\n"
                        f"• البوت عضو فيها\n"
                        f"• البوت مشرف فيها\n\n"
                        f"أو أرسل <b>المعرّف الرقمي</b> "
                        f"(مثل <code>-1001234567890</code>)",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.debug(
                        "reply_text (resolve fail) failed: %s", e
                    )
                return

    # 3) إذا لم نجد أياً من ذلك
    if not chat_id:
        try:
            await msg.reply_text(
                "❌ <b>لم أتعرف على قناة</b>\n\n"
                "أرسل أحد التالي:\n"
                "• معرّف رقمي: <code>-1001234567890</code>\n"
                "• <code>@username</code>\n"
                "• <code>username</code>\n"
                "• رابط: <code>https://t.me/username</code>\n"
                "• أو <b>أعد توجيه رسالة</b> من القناة\n\n"
                "⚠️ روابط الدعوة (<code>t.me/+abc</code>) غير مدعومة.\n"
                "للإلغاء: أرسل <b>إلغاء</b>.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.debug("reply_text (no chat_id) failed: %s", e)
        return

    # ✅ v1.6.1: فحص "المجموعة نفسها"
    if chat_id == group_id:
        try:
            await msg.reply_text(
                "❌ <b>لا يمكن استخدام المجموعة نفسها كقناة سجل</b>\n\n"
                "• <b>المجموعة</b>: حيث يعمل البوت للحماية\n"
                "• <b>قناة السجل</b>: قناة منفصلة يستقبل فيها البوت "
                "تقارير الأحداث\n\n"
                "الرجاء إنشاء قناة جديدة وتعيينها.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.debug("reply_text (same group) failed: %s", e)
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
            except Exception as e:
                logger.debug("reply_text (not admin) failed: %s", e)
            return
    except Exception as e:
        logger.warning(
            "⚠️ فشل فحص صلاحيات البوت في %s: %s", chat_id, e
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
        except Exception as e2:
            logger.debug("reply_text (access fail) failed: %s", e2)
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
            except Exception as e:
                logger.debug("reply_text (no post perm) failed: %s", e)
            return
    except Exception:
        pass

    # ─── محاولة استخراج عنوان القناة ───
    # ✅ G3: total_timeout صريح
    # ✅ F14: getattr للسلامة
    if not title:
        try:
            chat_obj = await asyncio.wait_for(
                context.bot.get_chat(chat_id),
                timeout=_GET_CHAT_TITLE_TIMEOUT,
            )
            if chat_obj:
                _t = getattr(chat_obj, "title", None)
                _u = getattr(chat_obj, "username", None)
                if _t:
                    title = _t
                elif _u:
                    title = f"@{_u}"
        except asyncio.TimeoutError:
            logger.debug(
                "get_chat for title (%s): timeout (%ss)",
                chat_id, _GET_CHAT_TITLE_TIMEOUT,
            )
        except Exception as e:
            logger.debug("get_chat for title (%s): %s", chat_id, e)

    # ✅ G1: title fallback
    if not title:
        title = f"قناة {chat_id}"

    # ─── الحفظ في قاعدة البيانات ───
    try:
        result = await gl.set_private(group_id, chat_id)
    except Exception as e:
        logger.error("❌ gl.set_private فشل: %s", e, exc_info=True)
        result = {'ok': False}

    # ✅ تنظيف الحالة
    StateManager.clear(user.id)
    _safe_pop_user_data(
        context, "log_group_id", "awaiting_log_channel_for"
    )

    # ─── النتيجة ───
    ok = (
        result.get('ok', False)
        if isinstance(result, dict)
        else bool(result)
    )

    if ok:
        # ✅ v1.5.0: إبطال كاش قائمة قناة السجل
        try:
            await _invalidate_log_channel_menu_cache(group_id)
        except Exception as e:
            logger.debug(
                "invalidate log_channel_menu cache failed: %s", e
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
                f"📢 القناة: <code>{chat_id}</code>\n"
                f"🏷️ العنوان: {_safe_html(title)}"
                + share_notice,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning("فشل إرسال تأكيد التعيين: %s", e)

        # ✅ F11 + F12 (v1.6.6): إرسال رسالة اختبار — isawaitable
        try:
            send_result = gl.send(
                group_id,
                "🧪 <b>رسالة اختبار</b>\n"
                "قناة السجل تعمل بنجاح! ✅\n"
                "<i>هذه الرسالة من اختبار الإعداد.</i>",
                event="general",
                silent=False,
            )
            if _is_awaitable(send_result):
                await send_result
        except Exception as e:
            logger.warning("⚠️ اختبار الإرسال فشل: %s", e)
    else:
        try:
            await msg.reply_text(
                "❌ فشل الحفظ في قاعدة البيانات.\n"
                "تحقق من السجلات (Logs) لمعرفة السبب."
            )
        except Exception as e:
            logger.warning("فشل إرسال رسالة الخطأ: %s", e)


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
    _safe_pop_user_data(
        context, "log_group_id", "awaiting_log_channel_for"
    )
    try:
        await update.message.reply_text(
            "❌ تم إلغاء انتظار قناة السجل."
        )
    except Exception as e:
        logger.debug("cancel_log_channel_wait reply failed: %s", e)


# =====================================================================
# تسجيل المعالجات
# =====================================================================

def register_group_log_handlers(app: Application) -> None:
    """يُسجّل MessageHandler في Application."""
    if app is None:
        logger.error("❌ register_group_log_handlers: app=None")
        return

    # 1) معالج الرسائل الرئيسي (FORWARDED أو TEXT)
    try:
        app.add_handler(
            MessageHandler(
                (filters.FORWARDED | filters.TEXT) & ~filters.COMMAND,
                receive_log_channel,
            ),
            group=1,
        )
        logger.debug(
            "✅ MessageHandler(receive_log_channel) مُسجَّل في group=1"
        )
    except Exception as e:
        logger.error(
            "❌ فشل تسجيل MessageHandler(receive_log_channel): %s",
            e, exc_info=True,
        )
        return

    # 2) أمر إلغاء الانتظار
    try:
        app.add_handler(
            CommandHandler(
                "cancel_group_log", cancel_log_channel_wait
            ),
            group=1,
        )
        logger.debug(
            "✅ CommandHandler(/cancel_group_log) مُسجَّل في group=1"
        )
    except Exception as e:
        logger.debug("cancel_group_log handler: %s", e)

    logger.info("✅ handlers قناة السجل مُسجَّل (group=1)")


__all__ = [
    "receive_log_channel",
    "cancel_log_channel_wait",
    "register_group_log_handlers",
    # دوال مساعدة مُصدَّرة للاختبار
    "_normalize_channel_input",
    "_extract_forward_channel",
    "_is_forwarded",
    "_resolve_username_with_retry",
    "_get_group_log",
    "_invalidate_log_channel_menu_cache",
    "_safe_html",
    "_passes_initial_validation",
    "_safe_pop_user_data",
    "_looks_like_url",
    "_is_awaitable",
    # ✅ v1.6.5: ثوابت المهلات الزمنية
    "_RESOLVE_TOTAL_TIMEOUT",
    "_GET_CHAT_TITLE_TIMEOUT",
    "_USERNAME_RESOLVE_ATTEMPT_TIMEOUT",
    "_USERNAME_RESOLVE_ATTEMPTS",
    "_USERNAME_RESOLVE_DELAY",
    # 🆕 v1.6.6
    "_GROUP_LOG_IMPORT_ERROR",
    "_URL_PREFIXES",
    "_TME_LINK_RE",
    "_TME_INVITE_RE",
    "_TG_USERNAME_RE",
]