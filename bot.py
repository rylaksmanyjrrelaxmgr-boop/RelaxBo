#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🌿 Relax Manager – البوت الرئيسي (النسخة النهائية المُحسَّنة v5.5.12)
================================================================================
🆕 v5.5.12 (POOL DATA DUAL FALLBACK):
    ✅ pool_health_monitor: fallback مزدوج لقراءة pool data
       - المصدر 1: DB.get_pool_live() (من AnalyticsMixin)
       - المصدر 2: DB.get_pool_stats() (من Database مباشرة)
       - المصدر 3: القيم الافتراضية (total/active من pg_stat_activity)
       الفائدة: المراقبة تعمل حتى لو:
         • أُعيد هيكلة AnalyticsMixin
         • فشل تحميل database_analytics.py
         • تغيّرت مفاتيح الإرجاع مستقبلاً
    ✅ إضافة imports: from typing import Any, Dict, Optional

🆕 v5.5.11 (PERFORMANCE INDEXES + FIXES):
    ✅ ensure_performance_indexes(): إنشاء الفهارس الحرجة تلقائياً عند الإقلاع
       - PostgreSQL فقط (SQLite/MySQL → تخطّي)
       - CONCURRENTLY + IF NOT EXISTS → آمن للتكرار
       - لا يفشل الإقلاع عند الخطأ
    ✅ إصلاح حرج: استيراد TimeUtils من database
       (كان يُسبب NameError صامت في إشعار قناة سجل المطور)
    ✅ pool_health_monitor: 
       - لفّ sleep(120) الأولي في try/except CancelledError
       - idle_in_tx: من >=3 إلى >=1 (idle in transaction يحجب VACUUM)
    ✅ _collect_admin_ids: تسجيل اسم الدالة المُستخدمة

🆕 v5.5.10 (POOL HEALTH MONITOR — NO FALSE ALARMS):
    ✅ pool_health_monitor: إصلاح الإنذارات الكاذبة
       - waiting الآن يحسب الأقفال الحقيقية فقط (Lock, LWLock, BufferPin)
       - إزالة waiting>=3 من شروط التحذير
       - waiting أصبح معلومة تشخيصية فقط (لا يفعّل ⚠️)
    ✅ تقليل الضجيج في اللوغ

🆕 v5.5.9 (AUTO POOL HEALTH MONITOR):
    ✅ pool_health_monitor(): مراقبة تلقائية لحالة PostgreSQL Pool
       - كل 5 دقائق → يسجّل في اللوغ
       - يقرأ pg_stat_activity + DB.get_pool_live()
       - 🟢 pool HEALTH (طبيعي) أو ⚠️ pool DIAG (ضغط)

🆕 v5.5.8 (DEV LOG — SUBSCRIPTION PAYMENT):
    ✅ successful_payment: إشعار قناة سجل المطور عند كل اشتراك مدفوع
    ✅ استيراد _notify_dev_log من handlers_command (مع fallback)

🆕 v5.5.7 (DEV LOG NOTIFICATIONS):
    ✅ يدعم إشعار قناة السجل من handlers_command و handlers_message

🆕 v5.5.6 (AUTO-DECLARE-CONTEST-WINNERS)
🆕 v5.5.5 (CONTEST-CLEANUP-COMMENT-FIX)
🆕 v5.5.4 (CONTEST-AUTO-CLEANUP)
🆕 v5.5.3 (GIFT-CODE-FLOW-FIX)
🆕 v5.5.2 (STATS-COMMAND-FIX)
🆕 v5.5.1 (COLLECT-ADMIN-FIX)
🆕 v5.5.0 (COMMAND SCOPING)
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

# ✅ v5.5.12: imports للـ typing (يُستخدم في pool_health_monitor)
from typing import Any, Dict, Optional

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

# ✅ v5.5.11: إضافة TimeUtils — كان مفقوداً ويُسبب NameError صامت
from database import DB, initialize_db, TimeUtils

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

# ✅ v5.5.8: استيراد _notify_dev_log من handlers_command (مع fallback)
try:
    from handlers.handlers_command import _notify_dev_log
    _DEV_LOG_AVAILABLE = True
except ImportError:
    try:
        from handlers_command import _notify_dev_log
        _DEV_LOG_AVAILABLE = True
    except ImportError:
        async def _notify_dev_log(context, text: str) -> None:
            """fallback — لا يفشل أبداً"""
            pass
        _DEV_LOG_AVAILABLE = False

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

# ═══════════════════════════════════════════════════════════════════
# ✅ v5.5.8: فحص توفر _notify_dev_log
# ═══════════════════════════════════════════════════════════════════
if _DEV_LOG_AVAILABLE:
    logger.info("✅ _notify_dev_log متاح — إشعارات قناة السجل مُفعّلة")
else:
    logger.warning(
        "⚠️ _notify_dev_log غير متاح — لن تُرسل إشعارات الدفع"
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
# 🆕 v5.5.11: إنشاء الفهارس الحرجة تلقائياً عند الإقلاع
# =====================================================================

# الفهارس التي تُنشأ:
#   - CONCURRENTLY: لا تقفل الجدول
#   - IF NOT EXISTS: آمن للتكرار (البوت قد يُعاد تشغيله)
#   - PostgreSQL فقط: SQLite/MySQL يتخطّى
_PERFORMANCE_INDEXES = [
    (
        "idx_user_penalties_active_end",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "idx_user_penalties_active_end "
        "ON user_penalties(status, end_time) "
        "WHERE status = 'active'",
    ),
    (
        "idx_user_penalties_user_status",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "idx_user_penalties_user_status "
        "ON user_penalties(user_id, status)",
    ),
    (
        "idx_auto_replies_chat_keyword",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "idx_auto_replies_chat_keyword "
        "ON auto_replies(chat_id, keyword)",
    ),
    (
        "idx_user_violations_user_chat",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "idx_user_violations_user_chat "
        "ON user_violations(user_id, chat_id)",
    ),
    (
        "idx_posts_channel_created",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "idx_posts_channel_created "
        "ON posts(channel_db_id, created_at)",
    ),
    (
        "idx_posts_channel_published_partial",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "idx_posts_channel_published_partial "
        "ON posts(channel_db_id) WHERE published = 0",
    ),
]


async def ensure_performance_indexes() -> None:
    """
    ✅ v5.5.11: ينشئ الفهارس الحرجة تلقائياً عند بدء البوت.

    - PostgreSQL فقط (SQLite/MySQL → تخطّي بصمت)
    - يستخدم CONCURRENTLY → لا يقفل الجدول
    - يستخدم IF NOT EXISTS → آمن للتكرار
    - لا يفشل الإقلاع عند الخطأ (يُسجَّل تحذير فقط)

    ملاحظة:
        DB.execute() عادة لا يفتح transaction، لذا CONCURRENTLY يعمل.
        لو ظهر خطأ "cannot run inside a transaction block" →
        استبدل CONCURRENTLY في القائمة أعلاه.

    Returns:
        None (يعمل side effect فقط)
    """
    # ─── فحص نوع DB ───
    try:
        db_type = getattr(DB, "DB_TYPE", "sqlite")
        if db_type != "postgres":
            logger.debug(
                f"ℹ️ ensure_performance_indexes: "
                f"DB={db_type} — تخطّي (PG فقط)"
            )
            return
    except Exception as e:
        logger.debug(f"ensure_performance_indexes: فحص DB_TYPE: {e}")
        return

    created = 0
    skipped = 0
    failed = 0
    t0 = time.monotonic()

    for idx_name, sql in _PERFORMANCE_INDEXES:
        try:
            await DB.execute(sql)
            created += 1
            logger.debug(f"✅ فهرس: {idx_name}")
        except Exception as e:
            err = str(e).lower()
            if "already exists" in err or "duplicate" in err:
                skipped += 1
            else:
                failed += 1
                logger.warning(
                    f"⚠️ فشل إنشاء {idx_name}: {e}"
                )

    elapsed = time.monotonic() - t0
    if failed:
        logger.warning(
            f"⚠️ ensure_performance_indexes: "
            f"{created} مُنشأ | {skipped} موجود | {failed} فشل "
            f"({elapsed:.2f}s)"
        )
    else:
        logger.info(
            f"✅ ensure_performance_indexes: "
            f"{created} مُنشأ | {skipped} موجود | 0 فشل "
            f"({elapsed:.2f}s)"
        )


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
            try:
                await bot.delete_my_commands(
                    scope=BotCommandScopeChat(chat_id=uid)
                )
            except Exception:
                pass
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
    """
    required = [
        "start", "help_command", "trial", "subscribe", "support",
        "developer", "stats", "language", "contests", "replies_command",
        "grant", "set_min_interval", "gift_plans", "redeem_gift",
        "mood", "admin", "broadcast", "set_force", "set_update_ch",
        "set_log_ch", "add_admin", "remove_admin",
        "export_replies", "import_replies", "backup", "restore",
        "auto_publish", "auto_recycle", "channels", "posts",
        "db_diag", "db_vacuum",
        "syncgroup", "security", "panel", "lock", "unlock",
        "ban", "mute", "warn", "kick", "restrict", "unban", "pin",
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
    """التحقق من توافق نوع DB المكتشف مع DATABASE_URL."""
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
        return True


# =====================================================================
# 🛡️ v5.3.0: فحص توفر معالجات group_log
# =====================================================================

def _verify_group_log_handlers() -> bool:
    """التحقق من توفر معالجات group_log (غير معطِّل)."""
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
    """إنشاء وتشغيل GroupLog instance."""
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
    """إغلاق لطيف لـGroupLog عند إيقاف البوت."""
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

                # ✅ v5.5.8: إشعار قناة سجل المطور — دفع حقيقي فقط
                try:
                    from html import escape as _escape

                    _uname = update.effective_user.username or ""
                    _fname = update.effective_user.first_name or ""
                    _username_display = (
                        f"@{_uname}" if _uname else "❌ لا يوجد"
                    )
                    _plan_display = _escape(str(plan_name or '—'))
                    _price_display = int(total_amount or 0)

                    await _notify_dev_log(
                        context,
                        f"💎 <b>اشتراك مدفوع جديد</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"👤 <b>الاسم:</b> {_escape(str(_fname or '—'))}\n"
                        f"🔗 <b>المعرف:</b> {_escape(_username_display)}\n"
                        f"🆔 <b>الرقم التعريفي:</b> <code>{user_id}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"💎 <b>الباقة:</b> {_plan_display}\n"
                        f"💰 <b>المبلغ:</b> {_price_display} ⭐\n"
                        f"📅 <b>الوقت:</b> {TimeUtils.mecca_iso()}",
                    )
                except Exception as _e:
                    logger.warning(
                        f"notify dev log (subscription): {_e}",
                        exc_info=True,
                    )
            else:
                await safe_send(context.bot, user_id, "❌ حدث خطأ في معالجة الدفع.")
                logger.error(f"❌ Failed to activate subscription for user {user_id}")
        except Exception as e:
            logger.exception(f"❌ Exception in subscription payment: {e}")
            await safe_send(context.bot, user_id, "❌ حدث خطأ غير متوقع.")

    elif payment_type == 'gift':
        # 🆕 v5.5.3: ترتيب آمن + رسالة HTML نظيفة
        try:
            # ─── 1) توثيق الدفع أولاً (لا نترك كود "يتيم") ───
            paid = await DB.mark_invoice_paid(
                invoice['number'], payment_id
            )
            if not paid:
                logger.error(
                    f"❌ mark_invoice_paid فشل: {invoice['number']}"
                )
                await safe_send(
                    context.bot, user_id,
                    "❌ <b>فشل توثيق الدفع</b>\n\n"
                    "لم يُصدر كود الهدية. يرجى التواصل مع الدعم.",
                    parse_mode='HTML',
                )
                return

            # ─── 2) إنشاء الكود ───
            code = await DB.create_gift_code(
                plan_id=plan['id'], creator_id=user_id
            )
            if code:
                duration = (
                    plan.get('duration_days')
                    or plan.get('days')
                    or 0
                )
                # ─── 3) إرسال برسالة HTML جميلة ───
                await safe_send(
                    context.bot, user_id,
                    f"🎉 <b>تم شراء كود الهدية بنجاح!</b>\n\n"
                    f"🎁 <b>الكود:</b>\n"
                    f"<code>{code}</code>\n\n"
                    f"📅 <b>المدة:</b> {duration} يوم\n\n"
                    f"<i>شارك هذا الكود مع من تحب 💝</i>",
                    parse_mode='HTML',
                )
                logger.info(
                    f"✅ Gift code created: user={user_id} "
                    f"(code={code[:8]}...)"
                )
            else:
                logger.error(
                    f"❌ create_gift_code فشل: user={user_id} "
                    f"invoice={invoice['number']}"
                )
                await safe_send(
                    context.bot, user_id,
                    "⚠️ <b>تم توثيق الدفع لكن فشل توليد الكود</b>\n\n"
                    "يرجى التواصل مع الدعم لإصدار الكود يدوياً.\n"
                    f"رقم الفاتورة: <code>{invoice['number']}</code>",
                    parse_mode='HTML',
                )
        except Exception as e:
            logger.exception(f"❌ Exception in gift payment: {e}")
            await safe_send(
                context.bot, user_id,
                "❌ حدث خطأ غير متوقع أثناء معالجة كود الهدية."
            )


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
# ✅ v5.5.9/10/11/12: مراقبة تلقائية لحالة PostgreSQL Pool
# =====================================================================

async def pool_health_monitor() -> None:
    """
    ✅ v5.5.9/10/11/12: يراقب حالة Pool + الاتصالات كل 5 دقائق.

    يسجّل في اللوغ:
      🟢 pool HEALTH: total=N active=N idle_tx=N lock_waits=N waiting=N util=N%
      ⚠️ pool DIAG  : نفس المعلومات عند ضغط حقيقي

    ✅ v5.5.10: 
      - waiting الآن يحسب الأقفال الحقيقية فقط
        (Lock, LWLock, BufferPin) — لا ClientRead/IO
      - waiting لم يعد يفعّل ⚠️ (معلومة فقط)

    ✅ v5.5.11:
      - sleep(120) الأولي داخل try/except CancelledError
        (كان يُسجّل كخطأ عند الإلغاء المبكر)
      - idle_in_tx: >=1 بدل >=3 — أي idle in transaction يحجب
        VACUUM ويستنزف pool، لذلك نُنبّه فوراً

    ✅ v5.5.12:
      - fallback مزدوج لقراءة pool data:
          1) DB.get_pool_live() (من AnalyticsMixin)
          2) DB.get_pool_stats() (من Database مباشرة)
          3) القيم الافتراضية (total/active من pg_stat_activity)
        الفائدة: المراقبة تعمل حتى لو:
          • أُعيد هيكلة AnalyticsMixin
          • فشل تحميل database_analytics.py
          • تغيّرت مفاتيح الإرجاع مستقبلاً
    """
    # ✅ v5.5.11: تأخير أولي — مُلفّف لمنع CancelledError غير الملتقط
    try:
        await asyncio.sleep(120)
    except asyncio.CancelledError:
        logger.info("🛑 pool_health_monitor أُلغيت (قبل البدء)")
        return

    while True:
        try:
            # تخطّي إذا ليس PostgreSQL
            db_type = getattr(DB, "DB_TYPE", "sqlite")
            if db_type != "postgres":
                # نستمر لكن نطبع مرة كل 30 دقيقة فقط
                try:
                    await asyncio.sleep(1800)
                except asyncio.CancelledError:
                    logger.info("🛑 pool_health_monitor أُلغيت")
                    return
                continue

            # ═══ قراءة pg_stat_activity ═══
            # ✅ v5.5.10: waiting يحسب الأقفال الحقيقية فقط
            row = await DB.fetchone(
                """
                SELECT 
                    count(*) AS total,
                    count(*) FILTER (WHERE state = 'active') AS active,
                    count(*) FILTER (WHERE state = 'idle') AS idle,
                    count(*) FILTER (WHERE state = 'idle in transaction') 
                        AS idle_in_tx,
                    count(*) FILTER (WHERE wait_event_type = 'Lock') 
                        AS lock_waits,
                    count(*) FILTER (
                        WHERE wait_event_type IN ('Lock', 'LWLock', 'BufferPin')
                    ) AS waiting
                FROM pg_stat_activity
                WHERE datname = current_database()
                """
            )

            # استخراج آمن للقيم (row قد يكون dict أو tuple)
            if isinstance(row, dict):
                data = row
            elif row is None:
                data = {}
            else:
                try:
                    data = dict(row)
                except (TypeError, ValueError):
                    data = {}

            total = int(data.get("total") or 0)
            active = int(data.get("active") or 0)
            idle = int(data.get("idle") or 0)
            idle_in_tx = int(data.get("idle_in_tx") or 0)
            lock_waits = int(data.get("lock_waits") or 0)
            waiting = int(data.get("waiting") or 0)

            # ═══════════════════════════════════════════════════════════
            # ✅ v5.5.12: fallback مزدوج لقراءة pool data
            # ═══════════════════════════════════════════════════════════
            # القيم الافتراضية (تُستخدم إن فشل المصدران)
            pool_max = 20
            pool_current = total
            pool_in_use = active

            # _pool_data: dict يحوي max_size/current_size/in_use
            # إن نجح أحد المصادر
            _pool_data: Optional[Dict[str, Any]] = None

            # ── المصدر 1: DB.get_pool_live() (من AnalyticsMixin) ──
            try:
                if hasattr(DB, "get_pool_live"):
                    _pd_live = await DB.get_pool_live()
                    if (isinstance(_pd_live, dict)
                            and _pd_live.get("available")
                            and _pd_live.get("max_size")):
                        _pool_data = _pd_live
            except Exception as _e:
                logger.debug(f"pool_health_monitor: get_pool_live: {_e}")

            # ── المصدر 2: DB.get_pool_stats() (من Database مباشرة) ──
            if _pool_data is None:
                try:
                    if hasattr(DB, "get_pool_stats"):
                        _pd_stats = await DB.get_pool_stats()
                        if (isinstance(_pd_stats, dict)
                                and _pd_stats.get("type") in (
                                    "postgres", "mysql"
                                )
                                and _pd_stats.get("max_size")):
                            # نُوحّد المفاتيح لتُطابق get_pool_live
                            _pool_data = {
                                "max_size": _pd_stats.get("max_size"),
                                "current_size": _pd_stats.get(
                                    "current_size"
                                ),
                                "in_use": _pd_stats.get("in_use"),
                            }
                except Exception as _e:
                    logger.debug(
                        f"pool_health_monitor: get_pool_stats: {_e}"
                    )

            # ── تطبيق القيم إن نجح أي مصدر ──
            if _pool_data is not None:
                try:
                    pool_max = int(_pool_data.get("max_size") or 20)
                    pool_current = int(
                        _pool_data.get("current_size") or total
                    )
                    pool_in_use = int(
                        _pool_data.get("in_use") or active
                    )
                except (TypeError, ValueError) as _e:
                    logger.debug(
                        f"pool_health_monitor: تطبيق pool_data: {_e}"
                    )

            util_pct = (
                (pool_current / pool_max * 100) if pool_max else 0
            )

            # ═══ تحديد المستوى ═══
            # ✅ v5.5.10: أزلنا waiting>=3 — waiting معلومة فقط
            # ✅ v5.5.11: idle_in_tx >= 1 (أي transaction معلّق يحجب VACUUM)
            is_stressed = (
                lock_waits > 0
                or idle_in_tx >= 1
                or util_pct >= 80
            )

            msg = (
                f"total={total}/{pool_max} active={active} idle={idle} "
                f"idle_tx={idle_in_tx} lock_waits={lock_waits} "
                f"waiting={waiting} util={util_pct:.0f}%"
            )

            if is_stressed:
                logger.warning(f"⚠️ pool DIAG  : {msg}")
            else:
                logger.info(f"🟢 pool HEALTH: {msg}")

        except asyncio.CancelledError:
            logger.info("🛑 pool_health_monitor أُلغيت")
            raise
        except Exception as e:
            # لا نطبع stack trace — فقط سطر بسيط
            logger.debug(f"pool_health_monitor: {e}")

        # ═══ الانتظار 5 دقائق ═══
        try:
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            logger.info("🛑 pool_health_monitor أُلغيت")
            return


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

    # ✅ v5.5.11: إنشاء الفهارس الحرجة تلقائياً (آمن + لا يقفل الجدول)
    try:
        await ensure_performance_indexes()
    except Exception as e:
        logger.warning(f"⚠️ ensure_performance_indexes فشل: {e}")

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

        يُستخدم للمهام التي لا تُدير أخطاءها داخليًا.
        أي استثناء → تسجيل + إعادة تشغيل بعد backoff متزايد.
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

    # ✅ v5.5.6: إعلان فائزين تلقائي (كل ساعة)
    async def contest_cleanup():
        """
        يُعلن الفائزين تلقائيًا للمسابقات المنتهية.

        السلوك:
          • انتظار 5 دقائق أولي عند الإقلاع (منح bootstrap فرصة)
          • كل ساعة:
              ① DB.auto_declare_expired_contests()
                  - يعلن فائزين للمسابقات المنتهية التي فيها مشاركون
                  - يُلغي المسابقات المنتهية بدون مشاركين
              ② إشعار كل فائز برسالة تهنئة
          • يعالج أخطاءه داخليًا (لا يرمي) → أي فشل عابر لا يُعيد
            تنفيذ الـ sleep(300) الأولي
          • يُلغى بشكل نظيف عند إيقاف البوت

        يعتمد على:
          • database_contests.py → auto_declare_expired_contests()
          • يُدار مباشرة عبر asyncio.create_task
        """
        # انتظار أولي — يُنفَّذ مرة واحدة فقط عند الإقلاع
        try:
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            raise

        while True:
            try:
                # ─── 1) الإعلان التلقائي ───
                winners = await DB.auto_declare_expired_contests()

                if winners:
                    logger.info(
                        f"🏆 contest_cleanup: أُعلن "
                        f"{len(winners)} فائزًا تلقائيًا"
                    )

                    # ─── 2) إشعار كل فائز ───
                    for w in winners:
                        winner_id = w.get("winner_id")
                        title = w.get("title") or "مسابقة"
                        if winner_id is None:
                            continue
                        try:
                            msg = (
                                f"🎉 <b>مبروك!</b>\n\n"
                                f"لقد فزت في مسابقة "
                                f"<b>{title}</b>!\n\n"
                                f"<i>سيتم التواصل معك قريبًا "
                                f"لاستلام الجائزة.</i>"
                            )
                            await app.bot.send_message(
                                chat_id=winner_id,
                                text=msg,
                                parse_mode="HTML",
                            )
                        except Exception as ne:
                            # المستخدم قد حظر البوت أو chat غير صالح
                            logger.debug(
                                f"إشعار الفائز {winner_id} فشل: {ne}"
                            )
                        # مهلة صغيرة بين الإشعارات لتجنّب rate limit
                        try:
                            await asyncio.sleep(0.5)
                        except asyncio.CancelledError:
                            raise

            except asyncio.CancelledError:
                logger.info("🛑 contest_cleanup أُلغيت")
                raise
            except Exception as e:
                logger.error(
                    f"❌ contest_cleanup (سيُعاد بعد ساعة): {e}",
                    exc_info=True,
                )

            try:
                await asyncio.sleep(3600)  # كل ساعة
            except asyncio.CancelledError:
                raise

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
        # ✅ v5.5.6: إعلان فائزين تلقائي (كل ساعة)
        # ملاحظة: لا نستخدم run_task_with_retry هنا لأن contest_cleanup
        # تُدير أخطاءها داخليًا (لا ترمي) → يُمنع إعادة تنفيذ sleep(300).
        asyncio.create_task(contest_cleanup()),

        # ✅ v5.5.9/10/11/12: مراقبة تلقائية لحالة Pool (كل 5 دقائق)
        # نفس المنطق — تُدير أخطاءها داخليًا.
        asyncio.create_task(pool_health_monitor()),
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