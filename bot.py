#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🌿 Relax Manager – البوت الرئيسي (النسخة النهائية المُحسَّنة v5.5.2)
================================================================================
🆕 v5.5.2 (STATS-COMMAND-FIX):
    ✅ نقل "stats" من PUBLIC_COMMANDS → ADMIN_COMMANDS
    ✅ السبب: CommandHandlers.stats يرفض غير المطورين، فوجوده في
       القائمة العامة كان يعطي تجربة UX سيئة ("❌ غير مصرح")
    ✅ الآن لا يرى المستخدم العادي الأمر إلا إذا كان أدمن
    ✅ لا تغيير في كود المعالج — فقط في الـ scoping

🆕 v5.5.1 (COLLECT-ADMIN-FIX):
    ✅ _collect_admin_ids: يجرّب عدة أسماء دوال للحصول على قائمة الأدمن
        • get_admin_list  ← الصحيح في المشروع
        • get_all_admins  ← fallback
        • get_admins      ← fallback
    ✅ يحل مشكلة: الأدمن من DB لم يُسجَّلوا عند restart

🆕 v5.5.0 (COMMAND SCOPING — إخفاء الأوامر الإدارية عن المستخدم العادي):
    ✅ تقسيم private_commands إلى public_commands + admin_commands
    ✅ الأوامر العامة → BotCommandScopeAllPrivateChats
    ✅ الأوامر الإدارية → BotCommandScopeChat لكل أدمن
    ✅ حذف Default Scope القديم
    ✅ refresh_admin_commands() — تحديث أدمن بلا restart
    ✅ _collect_admin_ids() — جمع أدمن من CONFIG + DB

🆕 v5.4.3 (Maintenance integration)
🆕 v5.4.2 (DB Diagnostics)
🔍 v5.4.1 (Analytics check)
🔍 v5.4.0 (Pool Monitor integration)
🆕 v5.3.1 (group_log integration كامل)
🆕 v5.3.0 (group_log integration أساسي)
🆕 v5.2.0 (periodic cleanup + تحسينات)
🆕 v5.1.0 (Warmup + فحص دوال)
🆕 v5.0.0 (أمان + إصلاحات)
================================================================================
"""

import asyncio
import os
import logging
import traceback
import json
import time
from urllib.parse import urlparse
from aiohttp import web

from telegram import (
    BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatJoinRequestHandler, filters,
    PreCheckoutQueryHandler
)

from config import CONFIG, PATHS
from database import DB, initialize_db
from handlers import (
    CommandHandlers,
    CallbackHandlers,
    MessageHandlers,
    chat_member,
)
# ✅ v4: قائمة القنوات
from handlers.handlers_channels_list import register_channels_list_handlers
# ✅ v4.1: إصلاح التنقل
from handlers.handlers_nav_fix import register_nav_fix
# ✅ v5.2.0: GroupRateLimiterManager
from handlers.handlers_message import GroupRateLimiterManager

# ✅ v5.3.0: group_log — استيراد بحماية
try:
    from handlers.handlers_group_log import register_group_log_handlers
    _GROUP_LOG_AVAILABLE = True
except ImportError as _e:
    register_group_log_handlers = None
    _GROUP_LOG_AVAILABLE = False
    _GROUP_LOG_IMPORT_ERROR = str(_e)

# ✅ v5.3.1: init_group_log
try:
    from group_log import init_group_log as _init_group_log
    _GROUP_LOG_INIT_AVAILABLE = True
except ImportError as _e:
    _init_group_log = None
    _GROUP_LOG_INIT_AVAILABLE = False
    _GROUP_LOG_INIT_IMPORT_ERROR = str(_e)

# ✅ v5.4.3: الصيانة الدورية لقاعدة البيانات
try:
    from maintenance import maintenance_loop as _maintenance_loop
    _MAINTENANCE_AVAILABLE = True
except ImportError as _e:
    _maintenance_loop = None
    _MAINTENANCE_AVAILABLE = False
    _MAINTENANCE_IMPORT_ERROR = str(_e)

from utils import (
    TranslationManager, KeyboardFactory, BackgroundTasks,
    ErrorHandler, setup_webhook, safe_send,
    warmup_all,  # 🧠 v5.1.0
)
from cache import cache_cleanup_task, user_cache, invalidate_user_cache

# =====================================================================
# ═══════════════════════════════════════════════════════════════════
# 🔒 v5.0.0: تصفية السجلات الحساسة — يمنع تسريب BOT_TOKEN
# ═══════════════════════════════════════════════════════════════════
# =====================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL, logging.INFO)
)

# ⚠️ يجب أن تكون BEFORE أي استدعاء لـ httpx أو Bot API
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.request").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.ExtBot").setLevel(logging.WARNING)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 🔍 v5.4.1: فحص تحميل AnalyticsMixin
# ═══════════════════════════════════════════════════════════════════
try:
    from database import ANALYTICS_MIXIN_AVAILABLE
    if ANALYTICS_MIXIN_AVAILABLE:
        logger.info("✅ AnalyticsMixin محمّل (database_analytics.py)")
    else:
        logger.warning(
            "⚠️ AnalyticsMixin مفقود — database_analytics.py غير موجود"
        )
except Exception as _e:
    logger.error(f"❌ فحص Analytics: {_e}")

# ═══════════════════════════════════════════════════════════════════
# 🔍 v5.4.1: فحص تحميل باقي Mixins (اختياري، للتشخيص)
# ═══════════════════════════════════════════════════════════════════
try:
    from database import (
        CHANNELS_POSTS_MIXIN_AVAILABLE,
        SUBSCRIPTIONS_MIXIN_AVAILABLE,
        GROUPS_MIXIN_AVAILABLE,
        TICKETS_MIXIN_AVAILABLE,
        CONTESTS_MIXIN_AVAILABLE,
        STATS_MIXIN_AVAILABLE,
        SETTINGS_MIXIN_AVAILABLE,
        POINTS_MIXIN_AVAILABLE,
        BACKUP_MIXIN_AVAILABLE,
        REMINDERS_MIXIN_AVAILABLE,
    )
    _mixins_status = {
        "channels_posts": CHANNELS_POSTS_MIXIN_AVAILABLE,
        "subscriptions": SUBSCRIPTIONS_MIXIN_AVAILABLE,
        "groups": GROUPS_MIXIN_AVAILABLE,
        "tickets": TICKETS_MIXIN_AVAILABLE,
        "contests": CONTESTS_MIXIN_AVAILABLE,
        "stats": STATS_MIXIN_AVAILABLE,
        "settings": SETTINGS_MIXIN_AVAILABLE,
        "points": POINTS_MIXIN_AVAILABLE,
        "backup": BACKUP_MIXIN_AVAILABLE,
        "reminders": REMINDERS_MIXIN_AVAILABLE,
        "analytics": ANALYTICS_MIXIN_AVAILABLE,
    }
    _missing = [k for k, v in _mixins_status.items() if not v]
    if _missing:
        logger.warning(f"⚠️ Mixins مفقودة: {_missing}")
    else:
        logger.info(f"✅ كل الـ {len(_mixins_status)} Mixins محمّلة")
except Exception as _e:
    logger.debug(f"⚠️ فحص Mixins: {_e}")

# ═══════════════════════════════════════════════════════════════════
# 🔍 v5.4.3: فحص توفر maintenance
# ═══════════════════════════════════════════════════════════════════
if _MAINTENANCE_AVAILABLE:
    logger.info("✅ maintenance محمّل — الصيانة الدورية مُفعّلة")
else:
    logger.warning(
        f"⚠️ maintenance غير متاح: "
        f"{globals().get('_MAINTENANCE_IMPORT_ERROR', 'unknown')}"
    )

ALLOWED_UPDATES = [
    "message",
    "callback_query",
    "chat_join_request",
    "pre_checkout_query",
    "chat_member",
    "my_chat_member",
]

# ✅ v5.3.1: مرجع عالمي لـgroup_log للإغلاق اللطيف
_GROUP_LOG_INSTANCE = None


# =====================================================================
# 🆕 v5.5.0: قوائم الأوامر — module-level constants
# =====================================================================
# يمكن استدعاؤها من أي مكان (handlers, refresh function).
# تظهر للمستخدم حسب النطاق (Scope) المُسجَّل في Telegram.
# =====================================================================

# ═══════════════════════════════════════════════════════════════════
# ✅ الأوامر العامة — تظهر لكل مستخدم في الخاص
# ═══════════════════════════════════════════════════════════════════
PUBLIC_COMMANDS = [
    ("start", "🏠 القائمة الرئيسية"),
    ("help", "📚 المساعدة"),
    ("trial", "🎁 تجربة مجانية"),
    ("subscribe", "💎 اشتراك"),
    ("support", "📞 دعم فني"),
    ("language", "🌐 اللغة"),
    ("developer", "👨‍💻 المطور"),
    ("contests", "🏆 المسابقات"),
    # ✅ v5.5.2: "stats" نُقل إلى ADMIN_COMMANDS
    ("replies", "💬 الردود التلقائية"),
    ("gift_plans", "🎁 خطط الهدايا"),
    ("redeem_gift", "🎟️ استرداد كود هدية"),
    ("mood", "🎭 تحليل المشاعر"),
    ("channels", "📡 قنواتي"),
    ("posts", "📋 منشوراتي"),
    ("auto_publish", "📤 تبديل النشر التلقائي"),
    ("auto_recycle", "♻️ تبديل التدوير"),
]

# ═══════════════════════════════════════════════════════════════════
# ✅ الأوامر الإدارية — تظهر للأدمن/المالك/المطورين فقط
# ═══════════════════════════════════════════════════════════════════
ADMIN_COMMANDS = [
    # ✅ v5.5.2: "stats" أُضيف هنا (كان في PUBLIC_COMMANDS خطأً)
    ("stats", "📊 الإحصائيات"),
    ("grant", "🎁 منح اشتراك يدوي"),
    ("set_min_interval", "⏱️ تعيين الحد الأدنى للفاصل"),
    ("admin", "👑 لوحة الأدمن"),
    ("broadcast", "📨 بث جماعي"),
    ("set_force", "🔒 تعيين الاشتراك الإجباري"),
    ("set_update_ch", "📢 تعيين قناة التحديثات"),
    ("set_log_ch", "📋 تعيين قناة السجلات"),
    ("add_admin", "👑 إضافة مشرف"),
    ("remove_admin", "🗑️ إزالة مشرف"),
    ("export_replies", "📤 تصدير الردود"),
    ("import_replies", "📥 استيراد الردود"),
    ("backup", "💾 نسخ احتياطي"),
    ("restore", "🔄 عرض النسخ"),
    ("db_diag", "🔬 تشخيص قاعدة البيانات"),
    ("db_vacuum", "🧹 تنظيف قاعدة البيانات"),
]

# ═══════════════════════════════════════════════════════════════════
# ✅ أوامر المجموعات — تظهر في كل المجموعات
# ═══════════════════════════════════════════════════════════════════
GROUP_COMMANDS = [
    ("syncgroup", "🔗 تفعيل المجموعة"),
    ("security", "🛡️ إعدادات الأمان"),
    ("panel", "📋 لوحة التحكم"),
    ("lock", "🔒 قفل المجموعة"),
    ("unlock", "🔓 فتح المجموعة"),
    ("ban", "🚫 حظر مستخدم"),
    ("mute", "🔇 كتم مستخدم"),
    ("warn", "⚠️ تحذير مستخدم"),
    ("kick", "👢 طرد مستخدم"),
    ("restrict", "🔒 تقييد مستخدم"),
    ("unban", "🔓 إلغاء حظر"),
    ("pin", "📌 تثبيت رسالة"),
]


# =====================================================================
# 🆕 v5.5.1: جمع معرّفات الأدمن — يجرّب عدة أسماء دوال
# =====================================================================

async def _collect_admin_ids() -> list:
    """
    جمع كل معرّفات الأدمن الذين يجب أن تظهر لهم الأوامر الإدارية.

    المصادر:
      • CONFIG.PRIMARY_OWNER_ID (المالك)
      • CONFIG.DEVELOPER_IDS (المطورون)
      • DB.get_admin_list() / get_all_admins() / get_admins() — أول اسم متاح

    🆕 v5.5.1:
      يحاول ثلاث أسماء دوال مختلفة بترتيب الأولوية. أول واحدة تنجح
      تُستخدم، والبقية تُتجاهَل. هذا يحل مشكلة عدم قراءة الأدمن من DB
      عند اختلاف اسم الدالة بين الإصدارات.

    Returns:
        قائمة أعداد صحيحة مرتّبة بدون تكرار.
    """
    admin_ids = set()

    # ─── المالك ───
    try:
        owner = int(getattr(CONFIG, "PRIMARY_OWNER_ID", 0) or 0)
        if owner:
            admin_ids.add(owner)
    except (TypeError, ValueError):
        pass

    # ─── المطورون ───
    try:
        devs = getattr(CONFIG, "DEVELOPER_IDS", []) or []
        for dev in devs:
            try:
                d = int(dev)
                if d:
                    admin_ids.add(d)
            except (TypeError, ValueError):
                continue
    except Exception:
        pass

    # ─── الأدمن من DB — نحاول عدة أسماء محتملة ───
    admin_list_getters = (
        "get_admin_list",   # ← المستخدم فعلياً في المشروع
        "get_all_admins",   # ← احتياطي
        "get_admins",       # ← احتياطي
    )

    for method_name in admin_list_getters:
        if not hasattr(DB, method_name):
            continue
        try:
            method = getattr(DB, method_name)
            result = method()
            if asyncio.iscoroutine(result):
                result = await result
            if not result:
                continue

            added_from_db = 0
            for a in result:
                uid = None
                if isinstance(a, dict):
                    uid = a.get("user_id") or a.get("id")
                elif isinstance(a, (int, str)):
                    uid = a
                if uid is None:
                    continue
                try:
                    admin_ids.add(int(uid))
                    added_from_db += 1
                except (TypeError, ValueError):
                    continue

            if added_from_db > 0:
                logger.debug(
                    f"✅ _collect_admin_ids: قرأ {added_from_db} "
                    f"أدمن من DB.{method_name}()"
                )
                # نجحنا — لا داعي لتجربة الأسماء الأخرى
                break
        except Exception as _e:
            logger.debug(
                f"_collect_admin_ids → DB.{method_name}(): {_e}"
            )
            continue

    return sorted(admin_ids)


# =====================================================================
# 🆕 v5.5.0: تحديث أوامر أدمن بلا restart
# =====================================================================

async def refresh_admin_commands(bot, user_id: int, is_admin: bool) -> bool:
    """
    تحديث قائمة أوامر مستخدم بعد إضافته/إزالته من الأدمن.

    Args:
        bot: instance الـ bot
        user_id: معرّف المستخدم
        is_admin: True = أضف الأوامر الإدارية | False = ارجع للعامة فقط

    Returns:
        True إذا نجح، False خلاف ذلك.

    الاستخدام من handlers:
        from main import refresh_admin_commands
        await refresh_admin_commands(context.bot, new_admin_id, True)
    """
    if not user_id:
        return False
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False

    try:
        if is_admin:
            await bot.set_my_commands(
                PUBLIC_COMMANDS + ADMIN_COMMANDS,
                scope=BotCommandScopeChat(chat_id=uid),
            )
        else:
            # امسح أي scope خاص
            try:
                await bot.delete_my_commands(
                    scope=BotCommandScopeChat(chat_id=uid)
                )
            except Exception:
                pass
            # أعد المستخدم للـ AllPrivateChats (يرث العامة)
            await bot.set_my_commands(
                PUBLIC_COMMANDS,
                scope=BotCommandScopeChat(chat_id=uid),
            )
        logger.info(
            f"✅ refresh_admin_commands({uid}, "
            f"is_admin={is_admin}) نجح"
        )
        return True
    except Exception as e:
        logger.warning(
            f"⚠️ refresh_admin_commands({uid}): {e}"
        )
        return False


# =====================================================================
# 🔒 v5.0.0: دوال إخفاء التوكن
# =====================================================================

def _redact_token(text: str, token: str = None) -> str:
    """استبدال التوكن بـ *** في أي نص."""
    if not text:
        return text
    if token is None:
        try:
            token = _get_bot_token()
        except Exception:
            return text
    if not token or len(token) < 8:
        return text
    return text.replace(token, "***REDACTED***")


def _get_bot_token() -> str:
    """قراءة التوكن من البيئة أولاً، ثم CONFIG."""
    env_token = os.getenv("BOT_TOKEN", "").strip()
    if env_token:
        return env_token
    return getattr(CONFIG, "TOKEN", "") or ""


def _safe_url(url: str) -> str:
    """إخفاء التوكن من URL للطباعة."""
    return _redact_token(url)


# =====================================================================
# 🛡️ v5.1.0: فحص دوال CommandHandlers
# =====================================================================

def _verify_command_handlers() -> bool:
    """
    التحقق من أن كل دالة مطلوبة موجودة في CommandHandlers.

    يُنفَّذ قبل التسجيل — يمنع AttributeError مفاجئ.
    """
    required = [
        # الأوامر الخاصة
        "start", "help_command", "trial", "subscribe", "support",
        "developer", "stats", "language", "contests", "replies_command",
        "grant", "set_min_interval", "gift_plans", "redeem_gift",
        "mood", "admin", "broadcast", "set_force", "set_update_ch",
        "set_log_ch", "add_admin", "remove_admin",
        "export_replies", "import_replies", "backup", "restore",
        "auto_publish", "auto_recycle", "channels", "posts",
        # ✅ v5.4.2: أوامر التشخيص
        "db_diag", "db_vacuum",
        # أوامر المجموعة
        "syncgroup", "security", "panel", "lock", "unlock",
        "ban", "mute", "warn", "kick", "restrict", "unban", "pin",
        # أوامر المشرفين المخفيين
        "register_hidden_owner", "remove_hidden_owner",
        "add_hidden_admin", "remove_hidden_admin", "list_hidden_admins",
    ]

    missing = []
    for name in required:
        if not hasattr(CommandHandlers, name):
            missing.append(name)

    if missing:
        logger.error(
            f"❌ دوال مفقودة في CommandHandlers ({len(missing)}): {missing}"
        )
        return False

    logger.info(f"✅ كل {len(required)} دالة CommandHandlers موجودة")
    return True


# =====================================================================
# 🛡️ v5.2.0: فحص توافق DB_TYPE مع DATABASE_URL
# =====================================================================

def _verify_db_config() -> bool:
    """
    التحقق من توافق نوع DB المكتشف مع DATABASE_URL.

    يكشف المشاكل مبكراً قبل محاولة الاتصال.
    """
    try:
        db_type = getattr(DB, "DB_TYPE", "unknown")
        db_url = os.getenv("DATABASE_URL", "").strip()

        if not db_url:
            if db_type != "sqlite":
                logger.warning(
                    f"⚠️ DB_TYPE={db_type} لكن DATABASE_URL فارغ! "
                    f"سيتم fallback إلى SQLite"
                )
            else:
                logger.info("✅ DB: SQLite (لا يوجد DATABASE_URL)")
            return True

        # فحص توافق
        url_lower = db_url.lower()
        is_pg_url = "postgres" in url_lower or "postgresql" in url_lower
        is_mysql_url = "mysql" in url_lower or "mariadb" in url_lower

        if db_type == "postgres" and not is_pg_url:
            logger.error("❌ DB_TYPE=postgres لكن DATABASE_URL ليس postgres!")
            return False
        if db_type == "mysql" and not is_mysql_url:
            logger.error("❌ DB_TYPE=mysql لكن DATABASE_URL ليس mysql!")
            return False

        logger.info(f"✅ DB: {db_type.upper()} — إعداد صحيح")
        return True
    except Exception as e:
        logger.warning(f"⚠️ فشل فحص DB: {e}")
        return True  # لا نوقف التشغيل بسبب هذا


# =====================================================================
# 🛡️ v5.3.0: فحص توفر معالجات group_log
# =====================================================================

def _verify_group_log_handlers() -> bool:
    """
    التحقق من توفر معالجات group_log (غير معطِّل).

    يرجع True إذا كانت متوفرة، False إذا لا — لكن لا يوقف التشغيل.
    """
    if not _GROUP_LOG_AVAILABLE:
        logger.warning(
            f"⚠️ handlers_group_log غير متاح: "
            f"{globals().get('_GROUP_LOG_IMPORT_ERROR', 'unknown')}"
        )
        logger.warning("⚠️ زر قناة السجل لن يعمل — سيتم تجاهله")
        return False

    try:
        if not callable(register_group_log_handlers):
            logger.warning(
                "⚠️ register_group_log_handlers غير قابل للاستدعاء"
            )
            return False
        logger.info("✅ handlers_group_log متاح")
        return True
    except Exception as e:
        logger.warning(f"⚠️ فحص group_log فشل: {e}")
        return False


# =====================================================================
# 🛡️ v5.3.1: تهيئة group_log instance
# =====================================================================

def _init_group_log_instance(app) -> bool:
    """
    إنشاء وتشغيل GroupLog instance.

    ✅ v5.3.1:
        - يستدعي init_group_log(DB, app.bot)
        - يبدأ الـWorker
        - يخزّن المرجع في _GROUP_LOG_INSTANCE للإغلاق لاحقاً
    """
    global _GROUP_LOG_INSTANCE

    if not _GROUP_LOG_INIT_AVAILABLE:
        logger.warning(
            f"⚠️ group_log.init غير متاح: "
            f"{globals().get('_GROUP_LOG_INIT_IMPORT_ERROR', 'unknown')}"
        )
        return False

    if not callable(_init_group_log):
        logger.warning("⚠️ init_group_log غير قابل للاستدعاء")
        return False

    try:
        _GROUP_LOG_INSTANCE = _init_group_log(DB, app.bot)
        if _GROUP_LOG_INSTANCE is None:
            logger.error("❌ init_group_log أعاد None")
            return False

        _GROUP_LOG_INSTANCE.start()
        logger.info(
            "✅ GroupLog: instance مُنشأ + worker started"
        )
        return True
    except Exception as e:
        logger.error(
            f"❌ فشل تهيئة GroupLog: {e}", exc_info=True
        )
        return False


async def _shutdown_group_log() -> None:
    """
    إغلاق لطيف لـGroupLog عند إيقاف البوت.

    ✅ v5.3.1:
        - انتظار الطابور (5s كحد أقصى)
        - إلغاء Worker
        - تسجيل النتيجة
    """
    global _GROUP_LOG_INSTANCE

    if _GROUP_LOG_INSTANCE is None:
        return

    try:
        if hasattr(_GROUP_LOG_INSTANCE, "shutdown"):
            await _GROUP_LOG_INSTANCE.shutdown(drain_timeout=5.0)
            logger.info("✅ GroupLog: تم الإغلاق بنجاح")
        elif hasattr(_GROUP_LOG_INSTANCE, "stop"):
            _GROUP_LOG_INSTANCE.stop()
            logger.info("✅ GroupLog: worker stopped")
    except asyncio.CancelledError:
        logger.info("🛑 GroupLog: shutdown أُلغي")
        raise
    except Exception as e:
        logger.warning(f"⚠️ GroupLog shutdown: {e}")
    finally:
        _GROUP_LOG_INSTANCE = None


# =====================================================================
# دوال مساعدة للدفع
# =====================================================================

async def _validate_invoice_for_payment(user_id: int, payload: str):
    """التحقق من صحة الفاتورة للدفع."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("❌ Invalid JSON payload")
        return None, None, None

    invoice_number = data.get('invoice')
    if not invoice_number:
        return None, None, None

    try:
        invoice = await DB.get_invoice(invoice_number)
    except Exception as e:
        logger.error(f"❌ DB.get_invoice failed: {e}")
        return None, None, None

    if not invoice or invoice.get('user_id') != user_id or invoice.get('status') != 'pending':
        logger.warning(f"❌ Invoice invalid or not pending for user {user_id}")
        return None, None, None

    payment_type = data.get('type')
    if payment_type not in ('subscription', 'gift'):
        logger.warning(f"❌ Unknown payment type: {payment_type}")
        return None, None, None

    plan_id = data.get('plan_id') or data.get('gift_plan_id')

    try:
        if payment_type == 'subscription':
            plan = await DB.get_plan(plan_id)
        else:
            plan = await DB.get_gift_plan(plan_id)
    except Exception as e:
        logger.error(f"❌ DB.get_plan failed: {e}")
        return None, None, None

    if not plan:
        logger.warning(f"❌ Plan not found: {plan_id}")
        return None, None, None

    return invoice, plan, data


async def pre_checkout(update, context):
    """معالجة ما قبل الدفع."""
    query = update.pre_checkout_query
    user_id = query.from_user.id
    payload = query.invoice_payload

    invoice, plan, data = await _validate_invoice_for_payment(user_id, payload)

    if invoice is None or plan is None:
        logger.warning(f"❌ Pre-checkout rejected for user {user_id}")
        try:
            await query.answer(
                ok=False,
                error_message="الفاتورة غير صالحة أو انتهت صلاحيتها."
            )
        except Exception as e:
            logger.error(f"❌ Failed to answer pre-checkout rejection: {e}")
        return

    if hasattr(query, 'total_amount'):
        expected_amount = plan.get('price')
        if (
            expected_amount is not None
            and expected_amount > 0
            and query.total_amount != expected_amount
        ):
            logger.warning(
                f"❌ Amount mismatch for user {user_id}: "
                f"expected {expected_amount}, got {query.total_amount}"
            )
            try:
                await query.answer(
                    ok=False,
                    error_message="المبلغ غير مطابق لسعر الخطة."
                )
            except Exception as e:
                logger.error(f"❌ Failed to answer amount mismatch: {e}")
            return

    try:
        await query.answer(ok=True)
        logger.info("✅ Pre-checkout success")
    except Exception as e:
        logger.error(f"❌ Failed to answer pre-checkout success: {e}")


async def successful_payment(update, context):
    """معالجة الدفع الناجح."""
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    total_amount = payment.total_amount
    telegram_payment_charge_id = payment.telegram_payment_charge_id
    provider_payment_charge_id = payment.provider_payment_charge_id

    invoice, plan, data = await _validate_invoice_for_payment(user_id, payload)

    if invoice is None or plan is None:
        logger.error(f"❌ Payment processing failed: invalid invoice for user {user_id}")
        await safe_send(context.bot, user_id, "❌ حدث خطأ في معالجة الدفع.")
        return

    if plan.get('price', 0) > 0 and plan.get('price') != total_amount:
        logger.error(f"❌ Amount mismatch in successful payment for user {user_id}")
        await safe_send(context.bot, user_id, "❌ المبلغ المدفوع غير مطابق.")
        return

    payment_type = data.get('type')
    payment_id = telegram_payment_charge_id or provider_payment_charge_id
    plan_name = plan.get('name', 'الخطة')

    if payment_type == 'subscription':
        try:
            success = await DB.activate_subscription_with_payment(
                user_id=user_id,
                invoice_number=invoice['number'],
                payment_id=payment_id,
                plan_id=plan['id']
            )
            if success:
                await DB.add_payment_log(
                    user_id, 'xtr', 'subscription_paid',
                    {'invoice': invoice['number'], 'plan_id': plan['id']}
                )
                await safe_send(
                    context.bot, user_id,
                    f"✅ تم تفعيل اشتراك {plan_name} بنجاح!"
                )
                logger.info(f"✅ Subscription activated: user={user_id}")
                await invalidate_user_cache(user_id)
            else:
                await safe_send(context.bot, user_id, "❌ حدث خطأ في معالجة الدفع.")
                logger.error(f"❌ Failed to activate subscription for user {user_id}")
        except Exception as e:
            logger.exception(f"❌ Exception in subscription payment: {e}")
            await safe_send(context.bot, user_id, "❌ حدث خطأ غير متوقع.")

    elif payment_type == 'gift':
        try:
            code = await DB.create_gift_code(
                plan_id=plan['id'], creator_id=user_id
            )
            if code:
                duration = (
                    plan.get('duration_days')
                    or plan.get('days')
                    or 0
                )
                await DB.mark_invoice_paid(invoice['number'], payment_id)
                await safe_send(
                    context.bot, user_id,
                    f"🎉 تم شراء كود الهدية!\n"
                    f"🎁 الكود: `{code}`\n"
                    f"📅 المدة: {duration} يوم"
                )
                logger.info(f"✅ Gift code created: user={user_id}")
            else:
                await safe_send(context.bot, user_id, "❌ حدث خطأ في توليد كود الهدية.")
                logger.error(f"❌ Failed to create gift code: {user_id}")
        except Exception as e:
            logger.exception(f"❌ Exception in gift payment: {e}")
            await safe_send(context.bot, user_id, "❌ حدث خطأ غير متوقع.")


# =====================================================================
# معالج الصحة (Health Check)
# =====================================================================

async def health_check(request):
    """نقطة نهاية للتحقق من صحة البوت."""
    return web.Response(text="OK", status=200)


# =====================================================================
# keep-alive
# =====================================================================

async def keep_alive():
    """يرسل طلب ping كل 5 دقائق لمنع Render من إيقاف الخدمة."""
    await asyncio.sleep(60)

    url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("KEEP_ALIVE_URL")

    if not url:
        logger.info("ℹ️ keep_alive: RENDER_EXTERNAL_URL غير موجود — سيتم تعطيله")
        return

    url = url.rstrip('/')
    health_url = f"{url}/health"

    logger.info(f"💓 keep_alive مُفعّل — Ping كل 5 دقائق")

    import aiohttp

    while True:
        try:
            await asyncio.sleep(300)

            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(health_url) as response:
                    logger.debug(f"💓 Keep-alive: {response.status}")
        except asyncio.CancelledError:
            logger.info("🛑 keep_alive تم إلغاؤه")
            raise
        except Exception as e:
            logger.debug(f"💓 keep-alive: {e}")


# =====================================================================
# المهمة الرئيسية
# =====================================================================

async def main():
    """الدالة الرئيسية."""
    t_start = time.monotonic()

    # ═══ التحقق من صحة الإعدادات ═══
    try:
        CONFIG.validate()
    except ValueError as e:
        logger.error(f"❌ {e}")
        raise SystemExit(1)

    # 🔒 v5.0.0: BOT_TOKEN من البيئة إن وُجد
    bot_token = _get_bot_token()
    if not bot_token:
        logger.error("❌ BOT_TOKEN غير محدّد (بيئة أو CONFIG.TOKEN)")
        raise SystemExit(1)

    logger.info(f"🌿 {CONFIG.BOT_NAME}")
    logger.info(f"👨‍💼 المالك: {CONFIG.PRIMARY_OWNER_ID}")

    # 🛡️ v5.1.0: فحص دوال الأوامر
    if not _verify_command_handlers():
        logger.error("❌ فشل فحص دوال الأوامر — الخروج")
        raise SystemExit(1)

    # 🛡️ v5.2.0: فحص توافق DB
    if not _verify_db_config():
        logger.error("❌ فشل فحص إعدادات قاعدة البيانات — الخروج")
        raise SystemExit(1)

    # 🛡️ v5.3.0: فحص group_log handlers (غير معطِّل)
    _verify_group_log_handlers()

    # ═══ تهيئة قاعدة البيانات ═══
    t0 = time.monotonic()
    if hasattr(DB, 'pre_initialize'):
        await DB.pre_initialize()
    else:
        await initialize_db()
    db_time = time.monotonic() - t0
    logger.info(f"⏱️ قاعدة البيانات تمت تهيئتها في {db_time:.2f} ثانية")

    # ═══ تسجيل المطورين والمالك ═══
    for dev_id in CONFIG.DEVELOPER_IDS:
        try:
            await DB.register_user(dev_id)
        except Exception as e:
            logger.error(f"❌ Failed to register developer {dev_id}: {e}")
    try:
        await DB.register_user(CONFIG.PRIMARY_OWNER_ID)
    except Exception as e:
        logger.error(f"❌ Failed to register owner: {e}")

    # ═══ تحميل الترجمات ═══
    t1 = time.monotonic()
    KeyboardFactory.load_config()
    available_langs = TranslationManager.get_available_languages()
    for lang in available_langs:
        TranslationManager.load_translation(lang)
    logger.info(
        f"✅ تم تحميل {len(available_langs)} لغة في "
        f"{time.monotonic()-t1:.2f} ثانية"
    )

    # ═══════════════════════════════════════════════════════════════
    # 🧠 v5.1.0: Warmup الشامل — تحميل كل الموارد مسبقاً
    # ═══════════════════════════════════════════════════════════════
    t_warmup = time.monotonic()
    try:
        warmup_result = await warmup_all()
        logger.info(
            f"⏱️ Warmup اكتمل في "
            f"{time.monotonic()-t_warmup:.2f} ثانية"
        )
    except Exception as e:
        logger.warning(f"⚠️ Warmup فشل (سيتم المتابعة): {e}")

    # ═══ المنفذ ═══
    port = int(os.getenv("PORT", CONFIG.WEB_PORT))

    # ═══ عنوان Webhook ═══
    hostname = (
        os.getenv("RENDER_EXTERNAL_HOSTNAME") or
        os.getenv("RENDER_EXTERNAL_URL") or
        os.getenv("RAILWAY_PUBLIC_DOMAIN") or
        os.getenv("HEROKU_APP_NAME") or
        os.getenv("WEBHOOK_URL")
    )
    if hostname and hostname.startswith("http"):
        hostname = urlparse(hostname).netloc

    # ═══ بناء التطبيق ═══
    t_app = time.monotonic()
    app = Application.builder().token(bot_token).build()
    app.bot_data['start_time'] = time.monotonic()
    await app.initialize()
    logger.info(
        f"⏱️ تم تهيئة التطبيق في {time.monotonic()-t_app:.2f} ثانية"
    )

    # ========== ✅ v5.3.1: تهيئة group_log ==========
    if _GROUP_LOG_INIT_AVAILABLE and _GROUP_LOG_AVAILABLE:
        _init_group_log_instance(app)
    else:
        if not _GROUP_LOG_INIT_AVAILABLE:
            logger.warning(
                "⚠️ group_log.init غير متاح — لن يعمل "
                "نظام سجل المجموعات"
            )
        elif not _GROUP_LOG_AVAILABLE:
            logger.warning(
                "⚠️ handlers_group_log غير متاح — لن يعمل "
                "نظام سجل المجموعات"
            )

    # =================================================================
    # 🆕 v5.5.0: تسجيل الأوامر بنطاقات صحيحة
    # =================================================================
    # 1) امسح أي قوائم قديمة (خصوصاً Default لتجنّب تسرّب)
    # 2) سجّل العامة على AllPrivateChats
    # 3) سجّل أوامر المجموعات على AllGroupChats
    # 4) سجّل الإدارية على BotCommandScopeChat لكل أدمن منفرداً
    # =================================================================

    # ─── 1) حذف Scopes القديمة ───
    for _scope_name, _scope in (
        ("Default", BotCommandScopeDefault()),
        ("AllPrivateChats", BotCommandScopeAllPrivateChats()),
        ("AllGroupChats", BotCommandScopeAllGroupChats()),
    ):
        try:
            await app.bot.delete_my_commands(scope=_scope)
            logger.debug(f"🧹 حُذفت أوامر {_scope_name} القديمة")
        except Exception as _e:
            logger.debug(f"delete {_scope_name} commands: {_e}")

    # ─── 2) الأوامر العامة ───
    try:
        await app.bot.set_my_commands(
            PUBLIC_COMMANDS,
            scope=BotCommandScopeAllPrivateChats(),
        )
        logger.info(
            f"✅ سُجِّلت {len(PUBLIC_COMMANDS)} أمراً عاماً "
            f"(AllPrivateChats)"
        )
    except Exception as _e:
        logger.error(f"❌ فشل تسجيل الأوامر العامة: {_e}")

    # ─── 3) أوامر المجموعات ───
    try:
        await app.bot.set_my_commands(
            GROUP_COMMANDS,
            scope=BotCommandScopeAllGroupChats(),
        )
        logger.info(
            f"✅ سُجِّلت {len(GROUP_COMMANDS)} أمراً للمجموعات "
            f"(AllGroupChats)"
        )
    except Exception as _e:
        logger.error(f"❌ فشل تسجيل أوامر المجموعات: {_e}")

    # ─── 4) الأوامر الإدارية — لكل أدمن منفرداً ───
    _admin_ids = await _collect_admin_ids()
    _registered_admins = 0
    _failed_admins = 0
    _admin_full_list = PUBLIC_COMMANDS + ADMIN_COMMANDS

    logger.info(
        f"👥 عدد الأدمن المُكتشفين: {len(_admin_ids)}"
    )

    for _admin_id in _admin_ids:
        try:
            await app.bot.set_my_commands(
                _admin_full_list,
                scope=BotCommandScopeChat(chat_id=_admin_id),
            )
            _registered_admins += 1
        except Exception as _e:
            _failed_admins += 1
            logger.warning(
                f"⚠️ فشل تسجيل أوامر الأدمن {_admin_id}: {_e}"
            )

    logger.info(
        f"✅ الأوامر الإدارية: {len(ADMIN_COMMANDS)} أمراً | "
        f"سُجِّلت لـ {_registered_admins}/{len(_admin_ids)} أدمن "
        f"(فشل {_failed_admins})"
    )

    # ========== تسجيل المعالجات ==========
    app.add_handler(CommandHandler("start", CommandHandlers.start))
    app.add_handler(CommandHandler("help", CommandHandlers.help_command))
    app.add_handler(CommandHandler("trial", CommandHandlers.trial))
    app.add_handler(CommandHandler("subscribe", CommandHandlers.subscribe))
    app.add_handler(CommandHandler("support", CommandHandlers.support))
    app.add_handler(CommandHandler("developer", CommandHandlers.developer))
    app.add_handler(CommandHandler("stats", CommandHandlers.stats))
    app.add_handler(CommandHandler("language", CommandHandlers.language))
    app.add_handler(CommandHandler("contests", CommandHandlers.contests))
    app.add_handler(CommandHandler("replies", CommandHandlers.replies_command))
    app.add_handler(CommandHandler("grant", CommandHandlers.grant))
    app.add_handler(CommandHandler("set_min_interval", CommandHandlers.set_min_interval))
    app.add_handler(CommandHandler("gift_plans", CommandHandlers.gift_plans))
    app.add_handler(CommandHandler("redeem_gift", CommandHandlers.redeem_gift))

    app.add_handler(CommandHandler("syncgroup", CommandHandlers.syncgroup))
    app.add_handler(CommandHandler("security", CommandHandlers.security))
    app.add_handler(CommandHandler("panel", CommandHandlers.panel))
    app.add_handler(CommandHandler("lock", CommandHandlers.lock))
    app.add_handler(CommandHandler("unlock", CommandHandlers.unlock))
    app.add_handler(CommandHandler("ban", CommandHandlers.ban))
    app.add_handler(CommandHandler("mute", CommandHandlers.mute))
    app.add_handler(CommandHandler("warn", CommandHandlers.warn))
    app.add_handler(CommandHandler("kick", CommandHandlers.kick))
    app.add_handler(CommandHandler("restrict", CommandHandlers.restrict))
    app.add_handler(CommandHandler("unban", CommandHandlers.unban))
    app.add_handler(CommandHandler("pin", CommandHandlers.pin))

    # أوامر المشرفين المخفيين
    app.add_handler(CommandHandler("register_hidden_owner", CommandHandlers.register_hidden_owner))
    app.add_handler(CommandHandler("remove_hidden_owner", CommandHandlers.remove_hidden_owner))
    app.add_handler(CommandHandler("add_hidden_admin", CommandHandlers.add_hidden_admin))
    app.add_handler(CommandHandler("remove_hidden_admin", CommandHandlers.remove_hidden_admin))
    app.add_handler(CommandHandler("list_hidden_admins", CommandHandlers.list_hidden_admins))

    app.add_handler(CommandHandler("mood", CommandHandlers.mood))
    app.add_handler(CommandHandler("admin", CommandHandlers.admin))
    app.add_handler(CommandHandler("broadcast", CommandHandlers.broadcast))
    app.add_handler(CommandHandler("set_force", CommandHandlers.set_force))
    app.add_handler(CommandHandler("set_update_ch", CommandHandlers.set_update_ch))
    app.add_handler(CommandHandler("set_log_ch", CommandHandlers.set_log_ch))
    app.add_handler(CommandHandler("add_admin", CommandHandlers.add_admin))
    app.add_handler(CommandHandler("remove_admin", CommandHandlers.remove_admin))
    app.add_handler(CommandHandler("export_replies", CommandHandlers.export_replies))
    app.add_handler(CommandHandler("import_replies", CommandHandlers.import_replies))
    app.add_handler(CommandHandler("backup", CommandHandlers.backup))
    app.add_handler(CommandHandler("restore", CommandHandlers.restore))
    app.add_handler(CommandHandler("auto_publish", CommandHandlers.auto_publish))
    app.add_handler(CommandHandler("auto_recycle", CommandHandlers.auto_recycle))
    app.add_handler(CommandHandler("channels", CommandHandlers.channels))
    app.add_handler(CommandHandler("posts", CommandHandlers.posts))

    # ✅ v5.4.2: أوامر تشخيص قاعدة البيانات (للمطور)
    app.add_handler(CommandHandler("db_diag", CommandHandlers.db_diag))
    app.add_handler(CommandHandler("db_vacuum", CommandHandlers.db_vacuum))

    # معالجات الدفع
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    # ═══ NAV_FIX أولاً (group=-10) ═══
    try:
        register_nav_fix(app)
        logger.info("✅ NAV_FIX: معالج الإغلاق/الرجوع مُسجّل")
    except Exception as e:
        logger.error(f"❌ فشل تسجيل NAV_FIX: {e}", exc_info=True)

    # ═══ قائمة القنوات ═══
    try:
        register_channels_list_handlers(app)
        logger.info("✅ handlers قائمة القنوات مُسجَّل")
    except Exception as e:
        logger.error(f"❌ فشل تسجيل handlers القنوات: {e}", exc_info=True)

    # ═══ ✅ v5.3.0: معالجات سجل قناة المجموعات ═══
    if _GROUP_LOG_AVAILABLE:
        try:
            register_group_log_handlers(app)
            logger.info("✅ group_log: معالجات سجل قناة المجموعات مُسجّلة")
        except Exception as e:
            logger.error(
                f"❌ فشل تسجيل group_log: {e}",
                exc_info=True
            )
    else:
        logger.warning(
            "⚠️ group_log غير متاح — زر قناة السجل لن يعمل"
        )

    # معالج الأزرار العام
    app.add_handler(CallbackQueryHandler(CallbackHandlers.handle))

    # معالجات الرسائل
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL |
         filters.AUDIO | filters.VOICE | filters.ANIMATION | filters.Sticker.ALL |
         filters.VIDEO_NOTE) &
        filters.ChatType.PRIVATE & ~filters.COMMAND,
        MessageHandlers.handle_private
    ))

    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL |
         filters.AUDIO | filters.VOICE | filters.ANIMATION | filters.Sticker.ALL |
         filters.VIDEO_NOTE) &
        filters.ChatType.GROUPS & ~filters.COMMAND,
        MessageHandlers.handle_group
    ))

    app.add_handler(MessageHandler(
        filters.StatusUpdate.ALL & filters.ChatType.GROUPS,
        MessageHandlers.handle_service
    ))

    app.add_handler(ChatJoinRequestHandler(MessageHandlers.handle_join_request))
    app.add_error_handler(ErrorHandler.handle_error)

    # ═══ ChatMemberHandler ═══
    chat_member.register(app)
    logger.info("✅ ChatMemberHandler مُفعّل — تحديث المشرفين فوري")

    # ========== المهام الخلفية ==========
    async def run_task_with_retry(task_func, *args, task_name=""):
        """
        ✅ v5.2.0: تشغيل المهمة مع إعادة محاولة + تقرير دوري.
        """
        consecutive_failures = 0
        while True:
            try:
                await task_func(*args)
                consecutive_failures = 0
            except asyncio.CancelledError:
                logger.info(f"🛑 مهمة {task_name} أُلغيت")
                raise
            except Exception as e:
                consecutive_failures += 1
                logger.error(
                    f"❌ Task {task_name} crashed "
                    f"(x{consecutive_failures}): {e}",
                    exc_info=True,
                )
                # ✅ v5.2.0: backoff متزايد
                delay = min(5 * consecutive_failures, 60)
                logger.info(
                    f"🔄 إعادة تشغيل {task_name} بعد {delay} ثانية..."
                )
                await asyncio.sleep(delay)

    async def cleanup_locks():
        while True:
            try:
                await DB.cleanup_user_locks(max_idle_seconds=3600)
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"❌ cleanup_locks failed: {e}")
                await asyncio.sleep(60)

    tasks = [
        asyncio.create_task(run_task_with_retry(keep_alive, task_name="keep_alive")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.auto_publish, app.bot, task_name="auto_publish")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.auto_backup, task_name="auto_backup")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.reminders, app.bot, task_name="reminders")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.heartbeat, app.bot, task_name="heartbeat")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.flush_usage_periodically, task_name="flush_usage")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.expire_subscriptions, task_name="expire_subscriptions")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.sync_admins_periodically, app.bot, task_name="sync_admins")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.expire_penalties_periodically, task_name="expire_penalties")),
        asyncio.create_task(run_task_with_retry(BackgroundTasks.cleanup_old_data, task_name="cleanup_old_data")),
        asyncio.create_task(run_task_with_retry(cache_cleanup_task, task_name="cache_cleanup")),
        asyncio.create_task(run_task_with_retry(cleanup_locks, task_name="cleanup_locks")),
        # ✅ v5.2.0: تنظيف دوري للـRateLimiter وsec_auth_cache
        asyncio.create_task(
            run_task_with_retry(
                GroupRateLimiterManager.periodic_cleanup_task,
                task_name="periodic_cleanup"
            )
        ),
        # 🔍 v5.4.0: مراقبة PostgreSQL Pool
        asyncio.create_task(
            run_task_with_retry(
                BackgroundTasks.monitor_pool,
                task_name="monitor_pool"
            )
        ),
        asyncio.create_task(
            run_task_with_retry(
                BackgroundTasks.monitor_pool_alert,
                app.bot,
                task_name="monitor_pool_alert"
            )
        ),
    ]

    # ✅ v5.4.3: الصيانة الدورية لقاعدة البيانات (كل 24 ساعة)
    if _MAINTENANCE_AVAILABLE and callable(_maintenance_loop):
        try:
            owner_id = int(CONFIG.PRIMARY_OWNER_ID)
        except (TypeError, ValueError):
            owner_id = None
            logger.warning(
                "⚠️ PRIMARY_OWNER_ID غير صالح — "
                "لن يُرسل تقرير الصيانة"
            )

        tasks.append(asyncio.create_task(
            run_task_with_retry(
                _maintenance_loop,
                app.bot,        # للإشعار
                owner_id,       # معرّف المالك
                task_name="maintenance"
            )
        ))
        logger.info(
            "✅ maintenance: مهمة الصيانة الدورية مُضافة "
            "(كل 24 ساعة)"
        )
    else:
        logger.warning(
            f"⚠️ maintenance غير متاح — الصيانة التلقائية معطّلة: "
            f"{globals().get('_MAINTENANCE_IMPORT_ERROR', 'module missing')}"
        )

    logger.info(f"✅ تم تشغيل {len(tasks)} مهمة خلفية")

    # ========== بدء التشغيل ==========
    try:
        if hostname:
            webhook_url = f"https://{hostname}/{bot_token}"
            logger.info(f"🔗 Webhook: {_safe_url(webhook_url)}")

            await app.bot.delete_webhook(drop_pending_updates=True)
            await app.bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True,
                allowed_updates=ALLOWED_UPDATES,
            )
            logger.info("✅ Webhook تم التعيين")

            runner = await setup_webhook(app, port)

            # تسخين الخادم
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    await session.get(f"http://127.0.0.1:{port}/health")
                    logger.info("🔥 تم تسخين الخادم بنجاح")
            except Exception:
                pass

            await asyncio.Event().wait()
        else:
            logger.info("⚠️ وضع Polling (لا يوجد hostname)")
            runner = await setup_webhook(app, port)
            try:
                await app.run_polling(
                    drop_pending_updates=True,
                    allowed_updates=ALLOWED_UPDATES,
                )
            finally:
                await runner.cleanup()
    finally:
        # ✅ v5.3.1: إغلاق GroupLog بلطف أولاً
        await _shutdown_group_log()

        # إلغاء المهام الخلفية
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        # إغلاق التطبيق
        await app.shutdown()

    logger.info(f"✅ اكتمل الإقلاع في {time.monotonic()-t_start:.2f} ثانية")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 تم الإيقاف")
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        traceback.print_exc()