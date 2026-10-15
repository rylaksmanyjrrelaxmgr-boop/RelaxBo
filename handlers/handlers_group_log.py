r"""
handlers_group_log.py — MessageHandler لاستقبال معرّف قناة السجل (v1.7.0)
=====================================================================
🆕 v1.7.0 (DEV-LOG-CHANNEL-FIX):
    🔴 FIX-DEV-LOG-1 (CRITICAL): دعم تعيين قناة السجلات العامة للمطور.

    المشكلة المُبلَّغ عنها:
        • المطور يفتح لوحة الأدمن → يضغط "تعيين قناة السجلات"
        • StateManager.set(user_id, WAIT_LOG_CH) ✅
        • يرسل @channel
        • handle_private يرى WAIT_LOG_CH في _EXTERNAL_HANDLED_STATES
          → يتخطى (يترك المسؤولية لـ handlers_group_log)
        • receive_log_channel يبحث عن log_group_id في user_data
          → لا يجده (يُضبط فقط من لوحة أمان مجموعة)
        • يرد: "❌ انتهت الجلسة. ابدأ من جديد من لوحة الأمان."
        • ❌ لا يُحفظ شيء → المطور يظن الزر معطّل

    السبب الجذري:
        receive_log_channel لا يفرّق بين حالتين:
          (أ) مجموعة:  log_group_id موجود في user_data
              → احفظ في bot_groups.log_channel_id (via gl.set_private)
          (ب) مطور:    log_group_id غير موجود
              → احفظ في settings.log_channel (قناة عامة)

    الإصلاح:
        1) إضافة helper _is_developer_user(user_id) لفحص المطور
        2) إضافة _handle_developer_log_input() — يحفظ قناة عامة للمطور
        3) تعديل receive_log_channel:
           - إذا log_group_id موجود → السلوك القديم (مجموعة)
           - إذا غير موجود + المستخدم مطوّر → استدعاء Handler المطور
           - إذا غير موجود + ليس مطوّر → رسالة خطأ

    النتيجة المتوقعة:
        ✅ المطور يضغط الزر → يرسل @channel → تُحفظ في settings.log_channel
        ✅ لم تعد تظهر كـ "قناة نشطة"
        ✅ لا مزيد من "انتهت الجلسة" المضلِّلة

🆕 v1.6.8 (POST-REVIEW FIXES) — محفوظ:
    🔴 AL3  register_group_log_handlers — إزالة `return` المُبكِّر
    🟠 AL4  _resolve_username_with_retry — chat_obj.id is None → continue
    🟠 AL5  receive_log_channel — فحص حالة FSM متين
    🟠 AL6  _normalize_channel_input — رفض chat_id == 0
    🟡 AL7  __all__ — إضافة _GROUP_LOG_MODULE_AVAILABLE و _PTB_V20_PLUS
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

# ═══════════════════════════════════════════════════════════════════
# 🆕 FIX-DEV-LOG-1: استيراد CONFIG لكشف المطور
# ═══════════════════════════════════════════════════════════════════
try:
    from config import CONFIG
    _CONFIG_AVAILABLE = True
except ImportError:
    CONFIG = None
    _CONFIG_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════════
# 🆕 FIX-DEV-LOG-1: استيراد DB لحفظ الإعدادات
# ═══════════════════════════════════════════════════════════════════
try:
    from database import DB as _DB
    _DB_AVAILABLE = True
except ImportError:
    _DB = None
    _DB_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════════
# استيراد group_log module
# ═══════════════════════════════════════════════════════════════════
_GROUP_LOG_IMPORT_ERROR: Optional[str] = None
try:
    import group_log as _group_log_module
    _GROUP_LOG_MODULE_AVAILABLE = True
except ImportError as _e:
    _group_log_module = None
    _GROUP_LOG_MODULE_AVAILABLE = False
    _GROUP_LOG_IMPORT_ERROR = str(_e)

from utils import StateManager, UserState

# استيراد internal_cache لإبطال كاش قائمة قناة السجل
try:
    from database import internal_cache as _internal_cache
    _INTERNAL_CACHE_AVAILABLE = True
except ImportError:
    _internal_cache = None
    _INTERNAL_CACHE_AVAILABLE = False

# استيراد أداة التحقق
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
# Regex
# =====================================================================

_TG_USERNAME_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{4,31}$')

_TME_LINK_RE = re.compile(
    r'^(?:https?://)?(?:www\.)?'
    r'(?:t\.me|telegram\.me|telegram\.dog)/'
    r'([A-Za-z][A-Za-z0-9_]{4,31})'
    r'(?:[/?#].*)?$',
    re.IGNORECASE,
)

_TME_INVITE_RE = re.compile(
    r'^(?:https?://)?(?:www\.)?'
    r'(?:t\.me|telegram\.me|telegram\.dog)/'
    r'(?:\+|joinchat/)',
    re.IGNORECASE,
)

_URL_PREFIXES = (
    'https://', 'http://',
    't.me/', 'telegram.me/', 'telegram.dog/',
    'www.t.me/', 'www.telegram.me/', 'www.telegram.dog/',
)


# =====================================================================
# 🆕 FIX-DEV-LOG-1: فحص المطور
# =====================================================================

def _is_developer_user(user_id: int) -> bool:
    """
    🆕 FIX-DEV-LOG-1: فحص موثوق هل المستخدم مطور/مالك.

    الترتيب:
      1) CONFIG.is_developer(uid) — الطريقة الرسمية
      2) PRIMARY_OWNER_ID
      3) DEVELOPER_IDS
    """
    if not user_id:
        return False
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False

    # ─── 1) CONFIG.is_developer ───
    if _CONFIG_AVAILABLE and CONFIG is not None:
        try:
            fn = getattr(CONFIG, 'is_developer', None)
            if callable(fn):
                try:
                    if bool(fn(uid)):
                        return True
                except Exception as _e:
                    logger.debug("CONFIG.is_developer(%s): %s", uid, _e)
        except Exception as _e:
            logger.debug("CONFIG.is_developer access: %s", _e)

        # ─── 2) PRIMARY_OWNER_ID ───
        try:
            primary = int(getattr(CONFIG, 'PRIMARY_OWNER_ID', 0) or 0)
            if primary and uid == primary:
                return True
        except (TypeError, ValueError):
            pass

        # ─── 3) DEVELOPER_IDS ───
        try:
            devs = getattr(CONFIG, 'DEVELOPER_IDS', ()) or ()
            if uid in tuple(devs):
                return True
        except (TypeError, ValueError):
            pass

    return False


def _looks_like_url(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    if low.startswith(_URL_PREFIXES):
        return True
    if _TME_LINK_RE.match(text):
        return True
    return False


def _normalize_channel_input(
    text: str,
) -> Tuple[Optional[int], Optional[str]]:
    """
    يحلّل المدخل النصي:
      - (chat_id_int, None) إذا كان رقماً صالحاً
      - (None, username) إذا كان @username أو username
      - (None, None) إذا كان رابط invite أو غير صالح
    """
    if not text:
        return None, None

    v = text.strip()
    if not v:
        return None, None

    if v.lstrip('-').isdigit():
        try:
            cid = int(v)
            if cid == 0:
                logger.debug(
                    "_normalize_channel_input: رُفض chat_id=0 | %r", v
                )
                return None, None
            return cid, None
        except (ValueError, TypeError):
            return None, None

    if _TME_INVITE_RE.match(v):
        return None, None

    if v.startswith('@'):
        username = v[1:]
        if _TG_USERNAME_RE.match(username):
            return None, username
        return None, None

    if _TG_USERNAME_RE.match(v):
        return None, v

    m = _TME_LINK_RE.match(v)
    if m:
        username = m.group(1)
        if _TG_USERNAME_RE.match(username):
            return None, username

    return None, None


# =====================================================================
# كشف إصدار PTB
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
# مساعدات عامة
# =====================================================================

def _get_group_log():
    if not _GROUP_LOG_MODULE_AVAILABLE or _group_log_module is None:
        return None
    return getattr(_group_log_module, "group_log", None)


def _safe_html(text) -> str:
    return _html_escape(str(text or ""))


def _safe_pop_user_data(context, *keys) -> None:
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
    return inspect.isawaitable(obj)


def _state_matches(state: Any, target_name: str) -> bool:
    """
    فحص حالة FSM متين (Enum + string).
    """
    if state is None:
        return False

    name = getattr(state, "name", None)
    if isinstance(name, str) and name == target_name:
        return True

    if isinstance(state, str):
        if state == target_name:
            return True
        if state == f"UserState.{target_name}":
            return True
        if state.endswith(f".{target_name}"):
            return True

    value = getattr(state, "value", None)
    if isinstance(value, str) and value == target_name:
        return True

    return False


def _is_forwarded(msg) -> bool:
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


async def _invalidate_log_channel_menu_cache(chat_id: int) -> None:
    if not _INTERNAL_CACHE_AVAILABLE or _internal_cache is None:
        return
    try:
        await _internal_cache.invalidate(f"log_ch_menu_{chat_id}")
    except Exception as e:
        logger.debug(
            "_invalidate_log_channel_menu_cache(%s): %s", chat_id, e
        )


# =====================================================================
# استخراج معلومات القناة المُعاد توجيهها
# =====================================================================

def _extract_forward_channel(msg) -> Tuple[Optional[int], str]:
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
        logger.debug(
            "_extract_forward_channel: unknown origin type: %s",
            type(origin).__name__,
        )
        return None, ""

    fwd_chat = getattr(msg, "forward_from_chat", None)
    if fwd_chat is not None:
        ctype = getattr(fwd_chat, "type", None)
        if ctype == "channel":
            cid = getattr(fwd_chat, "id", None)
            title = getattr(fwd_chat, "title", None) or ""
            return cid, title

    return None, ""


# =====================================================================
# حلّ @username مع retry
# =====================================================================

async def _resolve_username_with_retry(
    bot,
    username: str,
    max_attempts: int = _USERNAME_RESOLVE_ATTEMPTS,
    delay: float = _USERNAME_RESOLVE_DELAY,
    timeout: float = _USERNAME_RESOLVE_ATTEMPT_TIMEOUT,
    total_timeout: float = _RESOLVE_TOTAL_TIMEOUT,
) -> Tuple[Optional[int], str]:
    async def _do_attempts():
        for attempt in range(max_attempts):
            try:
                chat_obj = await asyncio.wait_for(
                    bot.get_chat(f"@{username}"),
                    timeout=timeout,
                )
                if chat_obj is None:
                    if attempt < max_attempts - 1:
                        try:
                            await asyncio.sleep(delay)
                        except Exception:
                            pass
                    continue

                cid = getattr(chat_obj, "id", None)
                if cid is None:
                    if attempt < max_attempts - 1:
                        try:
                            await asyncio.sleep(delay)
                        except Exception:
                            pass
                    continue

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


def _passes_initial_validation(text: str) -> bool:
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
# 🆕 FIX-DEV-LOG-1: حفظ قناة السجلات العامة للمطور
# =====================================================================

async def _save_dev_log_channel(chat_id: int) -> bool:
    """
    🆕 FIX-DEV-LOG-1: يحفظ قناة السجلات العامة في settings.log_channel.

    يجرب بالترتيب:
      1) DB.set_log_channel(chat_id) — إن وُجدت
      2) DB.set_setting('log_channel', str(chat_id))

    Returns:
        True عند النجاح
    """
    if not _DB_AVAILABLE or _DB is None:
        logger.error("_save_dev_log_channel: DB غير متاح")
        return False

    # ─── 1) محاولة DB.set_log_channel ───
    setter = getattr(_DB, 'set_log_channel', None)
    if callable(setter):
        try:
            result = setter(chat_id)
            if _is_awaitable(result):
                result = await result
            if result is None or bool(result):
                logger.info(
                    "✅ dev_log_channel saved via set_log_channel: %s",
                    chat_id,
                )
                return True
        except Exception as e:
            logger.warning(
                "DB.set_log_channel(%s) فشل: %s — fallback set_setting",
                chat_id, e,
            )

    # ─── 2) Fallback: DB.set_setting ───
    setter = getattr(_DB, 'set_setting', None)
    if callable(setter):
        try:
            result = setter('log_channel', str(chat_id))
            if _is_awaitable(result):
                result = await result
            logger.info(
                "✅ dev_log_channel saved via set_setting: %s",
                chat_id,
            )
            return True
        except Exception as e:
            logger.error(
                "DB.set_setting('log_channel', %s) فشل: %s",
                chat_id, e, exc_info=True,
            )
            return False

    logger.error(
        "_save_dev_log_channel: لا توجد دالة حفظ متاحة في DB "
        "(set_log_channel / set_setting)"
    )
    return False


async def _invalidate_dev_log_caches(chat_id: int) -> None:
    """
    🆕 FIX-DEV-LOG-1: إبطال الكاشات ذات الصلة بعد تغيير قناة السجلات.
    """
    # 1) handlers_message._invalidate_dev_log_cache
    try:
        mod = None
        import sys as _sys
        for _name in ('handlers_message', 'handlers.handlers_message'):
            if _name in _sys.modules:
                mod = _sys.modules[_name]
                break
        if mod is not None:
            inv = getattr(mod, '_invalidate_dev_log_cache', None)
            if callable(inv):
                try:
                    r = inv()
                    if _is_awaitable(r):
                        await r
                except Exception as _e:
                    logger.debug("_invalidate_dev_log_cache: %s", _e)
    except Exception as e:
        logger.debug("invalidate dev_log cache: %s", e)

    # 2) قائمة قناة السجل للمجموعة (احتياطي)
    try:
        await _invalidate_log_channel_menu_cache(chat_id)
    except Exception as e:
        logger.debug("invalidate menu cache: %s", e)


async def _handle_developer_log_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    msg,
    text: str,
    is_fwd: bool,
) -> None:
    """
    🆕 FIX-DEV-LOG-1: معالج قناة السجلات العامة للمطور.

    المنطق:
      1) استخراج chat_id من الرسالة (forward أو نص)
      2) حلّ @username إن لزم
      3) حفظ في settings.log_channel
      4) تأكيد + رسالة اختبار اختيارية
    """
    chat_id: Optional[int] = None
    title: str = ""

    # ─── من رسالة معاد توجيهها ───
    if is_fwd:
        fwd_id, fwd_title = _extract_forward_channel(msg)
        if fwd_id is not None:
            chat_id = fwd_id
            title = fwd_title
            logger.info(
                "✅ [DEV-LOG] chat_id من forwarded: %s (%r)",
                chat_id, title,
            )
        else:
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
                logger.debug("reply_text (dev-fwd-fail) failed: %s", e)
            return

    # ─── من النص ───
    if chat_id is None and text:
        if not _passes_initial_validation(text):
            logger.info(
                "⛔ [DEV-LOG] رفض النص عبر _is_valid_channel_ref: %r",
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
                    "⚠️ روابط الدعوة (<code>t.me/+abc</code>) "
                    "غير مدعومة.\n"
                    "للإلغاء: أرسل <b>إلغاء</b>.",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.debug("reply_text (dev-invalid) failed: %s", e)
            return

        parsed_id, parsed_username = _normalize_channel_input(text)

        if parsed_id is not None:
            chat_id = parsed_id
        elif parsed_username is not None:
            resolved_id, resolved_title = (
                await _resolve_username_with_retry(
                    context.bot, parsed_username,
                )
            )
            if resolved_id is not None:
                chat_id = resolved_id
                title = resolved_title
            else:
                try:
                    await msg.reply_text(
                        f"❌ لم أتمكن من الوصول إلى "
                        f"<code>@{_safe_html(parsed_username)}</code>\n\n"
                        f"تأكد أن:\n"
                        f"• القناة <b>عامة</b> (لها username)\n"
                        f"• البوت عضو فيها\n\n"
                        f"أو أرسل <b>المعرّف الرقمي</b> "
                        f"(مثل <code>-1001234567890</code>)",
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.debug(
                        "reply_text (dev-resolve-fail) failed: %s", e
                    )
                return

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
                "للإلغاء: أرسل <b>إلغاء</b>.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.debug("reply_text (dev-no-cid) failed: %s", e)
        return

    # ─── جلب العنوان إن لم يكن موجوداً ───
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
                "[DEV-LOG] get_chat title timeout for %s", chat_id
            )
        except Exception as e:
            logger.debug(
                "[DEV-LOG] get_chat title for %s: %s", chat_id, e
            )
    if not title:
        title = f"قناة {chat_id}"

    # ─── حفظ ───
    saved = await _save_dev_log_channel(chat_id)

    # ─── تنظيف الحالة ───
    try:
        StateManager.clear(user.id)
    except Exception:
        pass
    _safe_pop_user_data(
        context, "log_group_id", "awaiting_log_channel_for"
    )

    # ─── النتيجة ───
    if not saved:
        try:
            await msg.reply_text(
                "❌ <b>فشل حفظ قناة السجلات</b>\n\n"
                "راجع سجلات البوت (Logs) لمعرفة السبب.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning("reply_text (dev-save-fail): %s", e)
        return

    # ─── إبطال الكاشات ───
    try:
        await _invalidate_dev_log_caches(chat_id)
    except Exception as e:
        logger.debug("_invalidate_dev_log_caches: %s", e)

    # ─── تأكيد ───
    try:
        await msg.reply_text(
            f"✅ <b>تم تعيين قناة السجلات العامة بنجاح</b>\n\n"
            f"📢 القناة: <code>{chat_id}</code>\n"
            f"🏷️ العنوان: {_safe_html(title)}\n\n"
            f"<i>ستُرسل إليها إشعارات الدفع والإحالات "
            f"والأحداث العامة.</i>",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning("reply_text (dev-success): %s", e)

    # ─── رسالة اختبار ───
    try:
        test_text = (
            "🧪 <b>رسالة اختبار</b>\n"
            "قناة السجلات العامة تعمل بنجاح! ✅\n"
            "<i>هذه الرسالة من اختبار الإعداد.</i>"
        )
        await context.bot.send_message(
            chat_id=chat_id, text=test_text, parse_mode="HTML",
        )
    except Exception as e:
        logger.info(
            "⚠️ [DEV-LOG] اختبار الإرسال للقناة %s فشل: %s",
            chat_id, e,
        )
        try:
            await msg.reply_text(
                f"⚠️ <b>تنبيه:</b> لم أستطع إرسال رسالة اختبار "
                f"إلى القناة.\n\n"
                f"<code>{_safe_html(str(e)[:150])}</code>\n\n"
                f"تأكد أن البوت:\n"
                f"• عضو في القناة\n"
                f"• يملك صلاحية نشر الرسائل",
                parse_mode="HTML",
            )
        except Exception:
            pass


# =====================================================================
# استقبال معرّف قناة السجل — الرئيسي
# 🆕 FIX-DEV-LOG-1: يفرّق بين حالة المجموعة وحالة المطور
# =====================================================================

async def receive_log_channel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    يستقبل معرّف القناة أو رسالة موجّهة، ويحفظها كقناة سجل.

    🆕 FIX-DEV-LOG-1: يفرّق بين:
      (أ) مجموعة: log_group_id في user_data → gl.set_private
      (ب) مطور:   لا log_group_id + مستخدم مطوّر → settings.log_channel
    """
    user = update.effective_user
    if not user:
        return

    try:
        state = StateManager.get(user.id)
    except Exception as e:
        logger.debug("StateManager.get(%s): %s", user.id, e)
        return

    if not _state_matches(state, "WAIT_LOG_CH"):
        return

    msg = update.message
    if not msg:
        return

    text = (msg.text or "").strip()

    # ─── الإلغاء ───
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

    # ═══════════════════════════════════════════════════════════════
    # 🆕 FIX-DEV-LOG-1: فرع المطور (لا log_group_id)
    # ═══════════════════════════════════════════════════════════════
    if not group_id:
        is_dev = _is_developer_user(user.id)
        if is_dev:
            logger.info(
                "🎯 [DEV-LOG] تفعيل معالج قناة السجلات العامة | "
                "user=%s", user.id,
            )
            await _handle_developer_log_input(
                update, context, user, msg, text,
                _is_forwarded(msg),
            )
            return
        # ليس مطوراً → رسالة الخطأ القديمة
        logger.warning(
            "⚠️ WAIT_LOG_CH بدون log_group_id لغير المطور %s",
            user.id,
        )
        StateManager.clear(user.id)
        try:
            await msg.reply_text(
                "❌ انتهت الجلسة. ابدأ من جديد من لوحة الأمان."
            )
        except Exception as e:
            logger.debug("reply_text (no group_id) failed: %s", e)
        return

    # ═══════════════════════════════════════════════════════════════
    # من هنا: حالة المجموعة (group_id موجود)
    # ═══════════════════════════════════════════════════════════════

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

    # ─── استخراج/حلّ chat_id ───
    chat_id: Optional[int] = None
    title: str = ""

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
                    "⚠️ روابط الدعوة (<code>t.me/+abc</code>) "
                    "غير مدعومة.\n"
                    "للإلغاء: أرسل <b>إلغاء</b>.",
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.debug("reply_text (invalid) failed: %s", e)
            return

        parsed_id, parsed_username = _normalize_channel_input(text)

        if parsed_id is not None:
            chat_id = parsed_id
        elif parsed_username is not None:
            resolved_id, resolved_title = (
                await _resolve_username_with_retry(
                    context.bot, parsed_username,
                )
            )
            if resolved_id is not None:
                chat_id = resolved_id
                title = resolved_title
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
                "⚠️ روابط الدعوة (<code>t.me/+abc</code>) "
                "غير مدعومة.\n"
                "للإلغاء: أرسل <b>إلغاء</b>.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.debug("reply_text (no chat_id) failed: %s", e)
        return

    # ─── فحص "المجموعة نفسها" ───
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

    # ─── استخراج عنوان القناة ───
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

    if not title:
        title = f"قناة {chat_id}"

    # ─── الحفظ في قاعدة البيانات ───
    try:
        result = await gl.set_private(group_id, chat_id)
    except Exception as e:
        logger.error("❌ gl.set_private فشل: %s", e, exc_info=True)
        result = {'ok': False}

    StateManager.clear(user.id)
    _safe_pop_user_data(
        context, "log_group_id", "awaiting_log_channel_for"
    )

    ok = (
        result.get('ok', False)
        if isinstance(result, dict)
        else bool(result)
    )

    if ok:
        try:
            await _invalidate_log_channel_menu_cache(group_id)
        except Exception as e:
            logger.debug(
                "invalidate log_channel_menu cache failed: %s", e
            )

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

    try:
        state = StateManager.get(user.id)
    except Exception as e:
        logger.debug("StateManager.get(%s): %s", user.id, e)
        return

    if not _state_matches(state, "WAIT_LOG_CH"):
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
    """
    يُسجّل MessageHandler في Application.
    """
    if app is None:
        logger.error("❌ register_group_log_handlers: app=None")
        return

    _message_handler_ok = False
    _cancel_handler_ok = False

    try:
        app.add_handler(
            MessageHandler(
                (filters.FORWARDED | filters.TEXT)
                & filters.ChatType.PRIVATE
                & ~filters.COMMAND,
                receive_log_channel,
            ),
            group=1,
        )
        _message_handler_ok = True
        logger.debug(
            "✅ MessageHandler(receive_log_channel) مُسجَّل في group=1 "
            "(PRIVATE فقط)"
        )
    except Exception as e:
        logger.error(
            "❌ فشل تسجيل MessageHandler(receive_log_channel): %s",
            e, exc_info=True,
        )

    try:
        app.add_handler(
            CommandHandler(
                "cancel_group_log", cancel_log_channel_wait
            ),
            group=1,
        )
        _cancel_handler_ok = True
        logger.debug(
            "✅ CommandHandler(/cancel_group_log) مُسجَّل في group=1"
        )
    except Exception as e:
        logger.error(
            "❌ فشل تسجيل CommandHandler(/cancel_group_log): %s",
            e, exc_info=True,
        )

    if _message_handler_ok and _cancel_handler_ok:
        logger.info(
            "✅ handlers قناة السجل مُسجَّل كاملاً "
            "(group=1 — PRIVATE only)"
        )
    elif _cancel_handler_ok:
        logger.warning(
            "⚠️ handlers قناة السجل: MessageHandler فشل — "
            "لكن /cancel_group_log متاح للخروج من WAIT_LOG_CH"
        )
    elif _message_handler_ok:
        logger.warning(
            "⚠️ handlers قناة السجل: CommandHandler فشل — "
            "receive_log_channel يعمل لكن /cancel_group_log غير متاح. "
            "استخدم /start للخروج."
        )
    else:
        logger.error(
            "❌ handlers قناة السجل: فشل تسجيل كل الـ handlers"
        )


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
    "_state_matches",
    # 🆕 v1.7.0 FIX-DEV-LOG-1
    "_is_developer_user",
    "_handle_developer_log_input",
    "_save_dev_log_channel",
    "_invalidate_dev_log_caches",
    # ثوابت المهلات الزمنية
    "_RESOLVE_TOTAL_TIMEOUT",
    "_GET_CHAT_TITLE_TIMEOUT",
    "_USERNAME_RESOLVE_ATTEMPT_TIMEOUT",
    "_USERNAME_RESOLVE_ATTEMPTS",
    "_USERNAME_RESOLVE_DELAY",
    # وحدات اختيارية
    "_GROUP_LOG_IMPORT_ERROR",
    "_GROUP_LOG_MODULE_AVAILABLE",
    "_PTB_V20_PLUS",
    "_URL_PREFIXES",
    "_TME_LINK_RE",
    "_TME_INVITE_RE",
    "_TG_USERNAME_RE",
    # 🆕 v1.7.0
    "_CONFIG_AVAILABLE",
    "_DB_AVAILABLE",
]


# ═══════════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═══════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "✅ handlers_group_log v1.7.0 loaded | "
        "module=%s | "
        "PTB_v20=%s | "
        "config=%s | db=%s | "
        "fixes=(FIX-DEV-LOG-1:dev-general-log-channel, "
        "AL2:ChatType.PRIVATE, "
        "AL3:no-early-return, "
        "AL4:resolve-cid-None, "
        "AL5:robust-state-check, "
        "AL6:reject-cid-0, "
        "AL7:__all__-additions) | "
        "F12:isawaitable | F13:telegram.dog",
        "yes" if _GROUP_LOG_MODULE_AVAILABLE else "no",
        "yes" if _PTB_V20_PLUS else "no",
        "yes" if _CONFIG_AVAILABLE else "no",
        "yes" if _DB_AVAILABLE else "no",
    )
except Exception:
    pass