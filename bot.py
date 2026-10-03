#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🌿 Relax Manager – البوت الرئيسي (النسخة النهائية المُحسَّنة v5.5.23)
================================================================================
🆕 v5.5.23 (POOL-MONITOR-V2):
    ✅ PM-1: pool_health_monitor v2 — إصلاح WARNING كاذب على idle_tx
              - idle_tx يحتاج 2 دورات متتالية قبل التحذير
              - util<80% لا يسبب WARNING أبداً
              - grace period 90s بعد بدء التطبيق
              - استعلام تفصيلي عند idle_tx>=3 مع cooldown 10 دقائق
              - streak ظاهر في الرسالة لتشخيص أفضل
    ✅ PM-2: إضافة helper _dump_idle_tx_details

🆕 v5.5.22 (SOFT-DELETE-INTEGRATION):
    ✅ SD-1: handlers_channels_delete (تأكيد حذف القنوات)
    ✅ SD-2: cleanup_removed_channels_periodically (كل 24 ساعة)
    ✅ SD-3: تسجيل معالج تأكيد حذف القناة
    ✅ SD-4: 19 مهمة خلفية
    ✅ SD-5: رسائل تشخيصية

🆕 v5.5.21 (ADMIN_LOGS-AUTO-CLEANUP)
🆕 v5.5.20 (MEMBERSHIP UPGRADE)
🆕 v5.5.19 (MEMBERSHIP INTEGRATION)
🆕 v5.5.18 (CRITICAL FIXES)
🆕 v5.5.17 (REVIEW FIXES)
🆕 v5.5.16 (GRACEFUL SHUTDOWN + SAFETY)
🆕 v5.5.15 (BUG FIXES — aiohttp leak + HTML escape)
🆕 v5.5.14 (REMOVE DUPLICATE INDEX CREATION)
🆕 v5.5.13 (REMOVE DUPLICATE POOL MONITOR)
🆕 v5.5.12 (POOL DATA DUAL FALLBACK)
🆕 v5.5.11 (PERFORMANCE INDEXES + FIXES)
🆕 v5.5.10 (POOL HEALTH MONITOR — NO FALSE ALARMS)
🆕 v5.5.9 (AUTO POOL HEALTH MONITOR)
🆕 v5.5.8 (DEV LOG — SUBSCRIPTION PAYMENT)
🆕 v5.5.7 (DEV LOG NOTIFICATIONS)
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
import signal
import time
from datetime import datetime, timedelta
from html import escape as _html_escape
from urllib.parse import urlparse
from typing import Set
from aiohttp import web

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

from database import DB, initialize_db, TimeUtils

from handlers import (
    CommandHandlers,
    CallbackHandlers,
    MessageHandlers,
    chat_member,
)

# ═════════════════════════════════════════════════════════════════════
# ✅ v5.5.20 (MEM-1): MembershipHandler
# ═════════════════════════════════════════════════════════════════════
register_membership_handlers = None
_MEMBERSHIP_AVAILABLE = False
_MEMBERSHIP_IMPORT_ERROR = None
_MEMBERSHIP_SOURCE = None

try:
    from handlers_membership import (
        register_handlers as _register_membership_standalone,
    )
    register_membership_handlers = _register_membership_standalone
    _MEMBERSHIP_AVAILABLE = True
    _MEMBERSHIP_SOURCE = 'standalone'
except ImportError as _e1:
    try:
        from handlers.handlers_membership import (
            register_handlers as _register_membership_standalone,
        )
        register_membership_handlers = _register_membership_standalone
        _MEMBERSHIP_AVAILABLE = True
        _MEMBERSHIP_SOURCE = 'standalone'
    except ImportError as _e2:
        try:
            from handlers_callback import (
                register_membership_handlers as _register_membership_embedded,
            )
            register_membership_handlers = _register_membership_embedded
            _MEMBERSHIP_AVAILABLE = True
            _MEMBERSHIP_SOURCE = 'embedded'
        except ImportError as _e3:
            try:
                from handlers.handlers_callback import (
                    register_membership_handlers as _register_membership_embedded,
                )
                register_membership_handlers = _register_membership_embedded
                _MEMBERSHIP_AVAILABLE = True
                _MEMBERSHIP_SOURCE = 'embedded'
            except ImportError as _e4:
                register_membership_handlers = None
                _MEMBERSHIP_AVAILABLE = False
                _MEMBERSHIP_SOURCE = None
                _MEMBERSHIP_IMPORT_ERROR = (
                    f"standalone: {_e2} | embedded: {_e4}"
                )

# ═════════════════════════════════════════════════════════════════════
# ✅ v5.5.21 (CLEANUP-1): دوال تنظيف admin_logs
# ═════════════════════════════════════════════════════════════════════
try:
    from database_tables import (
        _cleanup_old_admin_logs_postgres as _cleanup_admin_logs_pg,
        _cleanup_old_admin_logs_sqlite as _cleanup_admin_logs_sqlite,
        _cleanup_old_admin_logs_mysql as _cleanup_admin_logs_mysql,
        ADMIN_LOGS_RETENTION_DAYS,
        ADMIN_LOGS_MAX_ROWS,
    )
    _ADMIN_LOGS_CLEANUP_AVAILABLE = True
except ImportError as _e:
    _cleanup_admin_logs_pg = None
    _cleanup_admin_logs_sqlite = None
    _cleanup_admin_logs_mysql = None
    ADMIN_LOGS_RETENTION_DAYS = 30
    ADMIN_LOGS_MAX_ROWS = 5000
    _ADMIN_LOGS_CLEANUP_AVAILABLE = False
    _ADMIN_LOGS_CLEANUP_IMPORT_ERROR = str(_e)

# ═════════════════════════════════════════════════════════════════════
# ✅ v5.5.22 (SD-1): handlers_channels_delete
# ═════════════════════════════════════════════════════════════════════
register_delete_confirmation = None
_CH_DELETE_AVAILABLE = False
_CH_DELETE_IMPORT_ERROR = None

try:
    from handlers.handlers_channels_delete import (
        register_delete_confirmation as _reg_ch_delete,
    )
    register_delete_confirmation = _reg_ch_delete
    _CH_DELETE_AVAILABLE = True
except ImportError as _e1:
    try:
        from handlers_channels_delete import (
            register_delete_confirmation as _reg_ch_delete,
        )
        register_delete_confirmation = _reg_ch_delete
        _CH_DELETE_AVAILABLE = True
    except ImportError as _e2:
        register_delete_confirmation = None
        _CH_DELETE_AVAILABLE = False
        _CH_DELETE_IMPORT_ERROR = f"{_e1} | {_e2}"

# ✅ v4: قائمة القنوات
from handlers.handlers_channels_list import register_channels_list_handlers
# ✅ v4.1: إصلاح التنقل
from handlers.handlers_nav_fix import register_nav_fix
# ✅ v5.2.0: GroupRateLimiterManager
from handlers.handlers_message import GroupRateLimiterManager

# ✅ v5.5.8: _notify_dev_log
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

# ✅ v5.3.0: group_log
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

# ✅ v5.4.3: maintenance
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
    warmup_all,
)
from cache import cache_cleanup_task, user_cache, invalidate_user_cache

# =====================================================================
# 🔒 v5.0.0: تصفية السجلات الحساسة
# =====================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL, logging.INFO)
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram.request").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.ExtBot").setLevel(logging.WARNING)
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# ✅ v5.5.16: متتبّع مهام الإشعارات
# ═══════════════════════════════════════════════════════════════════
_NOTIFY_TASKS: Set[asyncio.Task] = set()
_NOTIFY_SHUTDOWN_TIMEOUT = 5.0

# ✅ v5.5.18 (#8): إعدادات _watch_runner
_WATCHER_INTERVAL = 10.0
_WATCHER_HEALTH_TIMEOUT = 5.0
_WATCHER_MAX_PROBE_FAILURES = 3

# ✅ v5.5.22 (SD-2): إعدادات Soft Delete cleanup
_REMOVED_CHANNELS_GRACE_DAYS = 30

# ═══════════════════════════════════════════════════════════════════
# ✅ v5.5.23 (PM-1): إعدادات pool_health_monitor v2
# ═══════════════════════════════════════════════════════════════════
_PM_STARTUP_GRACE_SEC = 90.0          # تجاهل idle_tx خلال هذه الفترة
_PM_IDLE_TX_WARN_STREAK = 2           # دورات متتالية قبل WARNING
_PM_IDLE_TX_ERROR_THRESHOLD = 3       # idle_tx>=هذا → ERROR مباشرة
_PM_UTIL_WARN_PCT = 80.0              # util>=هذا → WARNING
_PM_UTIL_CRITICAL_PCT = 95.0          # util>=هذا → ERROR
_PM_LOCK_WAIT_WARN = 1                # lock_waits>=هذا → WARNING
_PM_WAITING_WARN = 3                  # waiting>=هذا → WARNING
_PM_ALERT_COOLDOWN_SEC = 600.0        # cooldown بين تفاصيل ERROR

# ═══════════════════════════════════════════════════════════════════
# 🔍 v5.4.1: فحص AnalyticsMixin
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
# 🔍 v5.4.1: فحص Mixins
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
# 🆕 v7.7.43: فحص RefactorMixin
# ═══════════════════════════════════════════════════════════════════
try:
    from database import REFACTOR_MIXIN_AVAILABLE
    if REFACTOR_MIXIN_AVAILABLE:
        logger.info("✅ RefactorMixin محمّل (database_refactor_mixin.py)")
    else:
        logger.info(
            "ℹ️ RefactorMixin غير محمّل — database.py يستخدم "
            "النسخة المدمجة (سلوك متطابق)"
        )
except Exception as _e:
    logger.debug(f"⚠️ فحص RefactorMixin: {_e}")

# ═══════════════════════════════════════════════════════════════════
# 🔍 v5.4.3: فحص maintenance
# ═══════════════════════════════════════════════════════════════════
if _MAINTENANCE_AVAILABLE:
    logger.info("✅ maintenance محمّل — الصيانة الدورية مُفعّلة")
else:
    logger.warning(
        f"⚠️ maintenance غير متاح: "
        f"{globals().get('_MAINTENANCE_IMPORT_ERROR', 'unknown')}"
    )

# ═══════════════════════════════════════════════════════════════════
# ✅ v5.5.8: فحص _notify_dev_log
# ═══════════════════════════════════════════════════════════════════
if _DEV_LOG_AVAILABLE:
    logger.info("✅ _notify_dev_log متاح — إشعارات قناة السجل مُفعّلة")
else:
    logger.warning(
        "⚠️ _notify_dev_log غير متاح — لن تُرسل إشعارات الدفع"
    )

# ═══════════════════════════════════════════════════════════════════
# ✅ v5.5.20 (MEM-4): فحص MembershipHandler
# ═══════════════════════════════════════════════════════════════════
if _MEMBERSHIP_AVAILABLE:
    if _MEMBERSHIP_SOURCE == 'standalone':
        logger.info(
            "✅ MembershipHandler (standalone) متاح — "
            "FIX-1 قناة المجموعة + FIX-3 عرض النطاق مُفعّلة"
        )
    elif _MEMBERSHIP_SOURCE == 'embedded':
        logger.info(
            "✅ MembershipHandler (embedded in handlers_callback) "
            "متاح — تقارير إضافة البوت جاهزة"
        )
    else:
        logger.info("✅ MembershipHandler متاح")
else:
    logger.warning(
        f"⚠️ register_membership_handlers غير متاح: "
        f"{_MEMBERSHIP_IMPORT_ERROR}"
    )

# ═══════════════════════════════════════════════════════════════════
# ✅ v5.5.21 (CLEANUP-1): فحص دوال تنظيف admin_logs
# ═══════════════════════════════════════════════════════════════════
if _ADMIN_LOGS_CLEANUP_AVAILABLE:
    logger.info(
        f"✅ admin_logs cleanup متاح — "
        f"احتفاظ={ADMIN_LOGS_RETENTION_DAYS}d, "
        f"حد أقصى={ADMIN_LOGS_MAX_ROWS} صف"
    )
else:
    logger.warning(
        f"⚠️ دوال تنظيف admin_logs غير متاحة: "
        f"{globals().get('_ADMIN_LOGS_CLEANUP_IMPORT_ERROR', 'unknown')} "
        f"— المهمة الدورية معطّلة"
    )

# ═══════════════════════════════════════════════════════════════════
# ✅ v5.5.22 (SD-1): فحص handlers_channels_delete
# ═══════════════════════════════════════════════════════════════════
if _CH_DELETE_AVAILABLE:
    logger.info(
        "✅ handlers_channels_delete متاح — "
        "تأكيد حذف القنوات مُفعّل"
    )
else:
    logger.warning(
        f"⚠️ handlers_channels_delete غير متاح: "
        f"{_CH_DELETE_IMPORT_ERROR} "
        f"— سيتم استخدام الحذف الفوري (بدون تأكيد)"
    )

ALLOWED_UPDATES = [
    "message",
    "callback_query",
    "chat_join_request",
    "pre_checkout_query",
    "chat_member",
    "my_chat_member",
]

_GROUP_LOG_INSTANCE = None


# =====================================================================
# ✅ v5.5.16: _spawn_notify_dev_log
# =====================================================================

def _spawn_notify_dev_log(context, text: str) -> None:
    """تشغيل _notify_dev_log في الخلفية بأمان."""
    try:
        task = asyncio.create_task(_notify_dev_log(context, text))
        _NOTIFY_TASKS.add(task)
        task.add_done_callback(_NOTIFY_TASKS.discard)
    except Exception as _e:
        logger.debug(f"_spawn_notify_dev_log: {_e}")


# =====================================================================
# 🆕 v5.5.0: قوائم الأوامر
# =====================================================================

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
# 🆕 v5.5.1: جمع معرّفات الأدمن
# =====================================================================

async def _collect_admin_ids() -> list:
    """جمع كل معرّفات الأدمن."""
    admin_ids = set()

    try:
        owner = int(getattr(CONFIG, "PRIMARY_OWNER_ID", 0) or 0)
        if owner:
            admin_ids.add(owner)
    except (TypeError, ValueError):
        pass

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

    admin_list_getters = (
        "get_admin_list",
        "get_all_admins",
        "get_admins",
    )

    any_method_succeeded = False
    last_error = None

    for method_name in admin_list_getters:
        if not hasattr(DB, method_name):
            continue
        try:
            method = getattr(DB, method_name)
            result = method()
            if asyncio.iscoroutine(result):
                result = await result

            any_method_succeeded = True

            if not result:
                logger.debug(
                    f"ℹ️ _collect_admin_ids: DB.{method_name}() "
                    f"أعادت قائمة فارغة (لا أدمن إضافي)"
                )
                break

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

            logger.debug(
                f"✅ _collect_admin_ids: قرأ {added_from_db} "
                f"أدمن من DB.{method_name}()"
            )
            break

        except Exception as _e:
            last_error = _e
            logger.debug(
                f"_collect_admin_ids → DB.{method_name}(): {_e}"
            )
            continue

    if not any_method_succeeded and last_error is not None:
        logger.warning(
            f"⚠️ _collect_admin_ids: فشلت كل الطرق لقراءة "
            f"الأدمن من DB — آخر خطأ: {last_error}. "
            f"الأوامر الإدارية ستظهر للمالك والمطورين فقط."
        )

    return sorted(admin_ids)


# =====================================================================
# 🆕 v5.5.0: تحديث أوامر أدمن
# =====================================================================

async def refresh_admin_commands(bot, user_id: int, is_admin: bool) -> bool:
    """تحديث قائمة أوامر مستخدم."""
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
# 🛡️ v5.3.0: فحص group_log
# =====================================================================

def _verify_group_log_handlers() -> bool:
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
# 🛡️ v5.5.20 (MEM-2): فحص MembershipHandler
# =====================================================================

def _verify_membership_handler() -> bool:
    """فحص توفر register_membership_handlers."""
    if not _MEMBERSHIP_AVAILABLE:
        logger.warning(
            f"⚠️ MembershipHandler غير متاح: "
            f"{_MEMBERSHIP_IMPORT_ERROR}"
        )
        return False
    if not callable(register_membership_handlers):
        logger.warning(
            "⚠️ register_membership_handlers غير قابل للاستدعاء"
        )
        return False

    if _MEMBERSHIP_SOURCE == 'standalone':
        logger.info(
            "✅ MembershipHandler متاح (standalone — handlers_membership.py)"
        )
    elif _MEMBERSHIP_SOURCE == 'embedded':
        logger.info(
            "✅ MembershipHandler متاح (embedded — handlers_callback.py)"
        )
    else:
        logger.info("✅ MembershipHandler متاح")

    return True


# =====================================================================
# 🛡️ v5.3.1: تهيئة group_log instance
# =====================================================================

def _init_group_log_instance(app) -> bool:
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
# ✅ v5.5.21 (CLEANUP-1): تنظيف admin_logs دورياً
# =====================================================================

async def cleanup_admin_logs_periodically() -> None:
    """
    ✅ v5.5.21 (CLEANUP-1): ينظّف admin_logs كل 24 ساعة.

    - حذف السجلات الأقدم من ADMIN_LOGS_RETENTION_DAYS (30 يوماً)
    - حذف الزائد عن ADMIN_LOGS_MAX_ROWS (5000 صف)
    """
    if not _ADMIN_LOGS_CLEANUP_AVAILABLE:
        logger.info(
            "⏭️ cleanup_admin_logs_periodically: "
            "دوال التنظيف غير متاحة — تخطي"
        )
        return

    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("🛑 cleanup_admin_logs: initial sleep أُلغي")
        raise

    logger.info(
        "🧹 cleanup_admin_logs_periodically: بدء الحلقة "
        "(كل 24 ساعة)"
    )

    while True:
        try:
            db_type = getattr(DB, "DB_TYPE", "sqlite")
            deleted = 0

            async with DB.connection() as conn:
                if db_type == "postgres":
                    if _cleanup_admin_logs_pg is not None:
                        deleted = await _cleanup_admin_logs_pg(
                            conn, logger
                        )
                elif db_type == "mysql":
                    if _cleanup_admin_logs_mysql is not None:
                        deleted = await _cleanup_admin_logs_mysql(
                            conn, logger
                        )
                else:
                    if _cleanup_admin_logs_sqlite is not None:
                        deleted = await _cleanup_admin_logs_sqlite(
                            conn, logger
                        )

            if deleted:
                logger.info(
                    f"✅ admin_logs cleanup: حُذف {deleted} صف "
                    f"(احتفاظ={ADMIN_LOGS_RETENTION_DAYS}d, "
                    f"حد أقصى={ADMIN_LOGS_MAX_ROWS})"
                )
            else:
                logger.debug(
                    "ℹ️ admin_logs cleanup: لا شيء للحذف"
                )

        except asyncio.CancelledError:
            logger.info("🛑 cleanup_admin_logs أُلغيت")
            raise
        except Exception as e:
            logger.error(
                f"❌ cleanup_admin_logs (سيُعاد بعد 24h): {e}",
                exc_info=True,
            )

        try:
            await asyncio.sleep(86400)
        except asyncio.CancelledError:
            logger.info("🛑 cleanup_admin_logs أُلغيت")
            raise


# =====================================================================
# ✅ v5.5.22 (SD-2): تنظيف القنوات المُزالة (Soft Delete) دورياً
# =====================================================================

async def cleanup_removed_channels_periodically() -> None:
    """
    ✅ v5.5.22 (SD-2): يحذف نهائياً القنوات المُزالة بعد فترة السماح.

    - يعمل كل 24 ساعة
    - ينتظر ساعة قبل أول تشغيل
    - يحذف القنوات التي:
        * removed_at IS NOT NULL
        * removed_at < NOW() - GRACE_DAYS
    - الحذف نهائي (CASCADE يحذف المنشورات)
    """
    GRACE_DAYS = _REMOVED_CHANNELS_GRACE_DAYS

    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info(
            "🛑 cleanup_removed_channels: initial sleep أُلغي"
        )
        raise

    logger.info(
        f"🧹 cleanup_removed_channels_periodically: بدء الحلقة "
        f"(كل 24 ساعة، فترة سماح={GRACE_DAYS} يوم)"
    )

    while True:
        try:
            deleted = 0

            if hasattr(DB, 'hard_delete_removed_channels_before'):
                cutoff_dt = (
                    datetime.utcnow()
                    - timedelta(days=GRACE_DAYS)
                )
                deleted = (
                    await DB.hard_delete_removed_channels_before(
                        cutoff_dt
                    )
                )
            else:
                db_type = getattr(DB, "DB_TYPE", "sqlite")

                if db_type == "postgres":
                    sql = (
                        "DELETE FROM user_channels "
                        "WHERE removed_at IS NOT NULL "
                        f"AND removed_at < NOW() - "
                        f"INTERVAL '{GRACE_DAYS} days'"
                    )
                elif db_type == "mysql":
                    sql = (
                        "DELETE FROM user_channels "
                        "WHERE removed_at IS NOT NULL "
                        f"AND removed_at < UTC_TIMESTAMP() - "
                        f"INTERVAL {GRACE_DAYS} DAY"
                    )
                else:
                    sql = (
                        "DELETE FROM user_channels "
                        "WHERE removed_at IS NOT NULL "
                        f"AND julianday('now') - "
                        f"julianday(removed_at) > {GRACE_DAYS}"
                    )

                result = await DB.execute(sql)
                if isinstance(result, int):
                    deleted = result

            if deleted:
                logger.info(
                    f"✅ removed_channels cleanup: "
                    f"حُذف نهائياً {deleted} قناة مهجورة "
                    f"(بعد {GRACE_DAYS} يوم من الإزالة)"
                )
            else:
                logger.debug(
                    "ℹ️ removed_channels cleanup: لا شيء للحذف"
                )

        except asyncio.CancelledError:
            logger.info("🛑 cleanup_removed_channels أُلغيت")
            raise
        except Exception as e:
            logger.error(
                f"❌ cleanup_removed_channels (سيُعاد بعد 24h): {e}",
                exc_info=True,
            )

        try:
            await asyncio.sleep(86400)
        except asyncio.CancelledError:
            logger.info("🛑 cleanup_removed_channels أُلغيت")
            raise


# =====================================================================
# دوال مساعدة للدفع
# =====================================================================

async def _validate_invoice_for_payment(user_id: int, payload: str):
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

                try:
                    _uname = update.effective_user.username or ""
                    _fname = update.effective_user.first_name or ""
                    _username_display = (
                        f"@{_uname}" if _uname else "❌ لا يوجد"
                    )
                    _plan_display = _html_escape(str(plan_name or '—'))
                    _price_display = int(total_amount or 0)

                    _spawn_notify_dev_log(
                        context,
                        f"💎 <b>اشتراك مدفوع جديد</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"👤 <b>الاسم:</b> {_html_escape(str(_fname or '—'))}\n"
                        f"🔗 <b>المعرف:</b> {_html_escape(_username_display)}\n"
                        f"🆔 <b>الرقم التعريفي:</b> <code>{user_id}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"💎 <b>الباقة:</b> {_plan_display}\n"
                        f"💰 <b>المبلغ:</b> {_price_display} ⭐\n"
                        f"📅 <b>الوقت:</b> {TimeUtils.mecca_iso()}",
                    )
                except Exception as _e:
                    logger.debug(
                        f"spawn notify dev log (subscription): {_e}"
                    )
            else:
                await safe_send(context.bot, user_id, "❌ حدث خطأ في معالجة الدفع.")
                logger.error(f"❌ Failed to activate subscription for user {user_id}")
        except Exception as e:
            logger.exception(f"❌ Exception in subscription payment: {e}")
            await safe_send(context.bot, user_id, "❌ حدث خطأ غير متوقع.")

    elif payment_type == 'gift':
        try:
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

            code = await DB.create_gift_code(
                plan_id=plan['id'], creator_id=user_id
            )
            if code:
                duration = (
                    plan.get('duration_days')
                    or plan.get('days')
                    or 0
                )
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
# معالج الصحة
# =====================================================================

async def health_check(request):
    """نقطة نهاية للتحقق من صحة البوت."""
    return web.Response(text="OK", status=200)


# =====================================================================
# keep-alive
# =====================================================================

async def keep_alive():
    """يرسل ping كل 5 دقائق لمنع Render من إيقاف الخدمة."""
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
                    await response.read()
                    logger.debug(f"💓 Keep-alive: {response.status}")
        except asyncio.CancelledError:
            logger.info("🛑 keep_alive تم إلغاؤه")
            raise
        except Exception as e:
            logger.debug(f"💓 keep-alive: {e}")


# =====================================================================
# ✅ v5.5.23 (PM-2): تفاصيل idle-in-transaction
# =====================================================================

async def _dump_idle_tx_details() -> None:
    """
    ✅ v5.5.23: يسجّل تفاصيل الاتصالات العالقة في idle-in-transaction.

    يُستدعى فقط عند ERROR مع cooldown، لتفادي إغراق السجل.
    """
    try:
        rows = await DB.fetchall(
            """
            SELECT pid,
                   usename,
                   application_name,
                   state,
                   EXTRACT(EPOCH FROM (now() - state_change))::int
                       AS seconds_in_state,
                   LEFT(query, 200) AS query_snippet
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND state = 'idle in transaction'
            ORDER BY state_change ASC
            LIMIT 5
            """
        )
        if not rows:
            logger.error("   (لا توجد اتصالات idle_tx عند الاستعلام)")
            return

        logger.error(
            f"🔍 idle-in-transaction details "
            f"({len(rows)} اتصال عالق):"
        )
        for r in rows:
            pid = r.get("pid")
            user = r.get("usename")
            app = r.get("application_name")
            age = r.get("seconds_in_state")
            snippet = r.get("query_snippet") or ""
            snippet = snippet.replace("\n", " ")[:120]
            logger.error(
                f"   • pid={pid} user={user} app={app!r} "
                f"age={age}s q={snippet!r}"
            )
    except Exception as qe:
        logger.debug(f"_dump_idle_tx_details: {qe}")


# =====================================================================
# ✅ v5.5.23 (PM-1): pool_health_monitor v2
# =====================================================================

async def pool_health_monitor() -> None:
    """
    ✅ v5.5.23 (POOL-MONITOR-V2):
    يراقب حالة Pool + الاتصالات كل 5 دقائق.

    قواعد التصنيف الجديدة:
      • idle_tx == 1 في دورة واحدة   → INFO (transient، طبيعي خلال backup)
      • idle_tx >= 1 لدورتين متتاليتين → WARNING (مع streak ظاهر)
      • idle_tx >= 3 في أي دورة       → ERROR + تفاصيل
      • util < 80%                    → INFO (حتى لو idle_tx=1)
      • util >= 80%                   → WARNING
      • util >= 95%                   → ERROR
      • lock_waits >= 1               → WARNING
      • waiting >= 3                  → WARNING

    Grace period: 90 ثانية بعد بدء المهمة → لا تحذيرات idle_tx
                  (يمنع إزعاج bootstrap/backup)
    """
    _task_start_mono = time.monotonic()
    _idle_tx_streak = 0
    _last_details_dump_mono = 0.0

    try:
        await asyncio.sleep(120)
    except asyncio.CancelledError:
        logger.info("🛑 pool_health_monitor أُلغيت (قبل البدء)")
        return

    while True:
        try:
            db_type = getattr(DB, "DB_TYPE", "sqlite")
            if db_type != "postgres":
                try:
                    await asyncio.sleep(1800)
                except asyncio.CancelledError:
                    logger.info("🛑 pool_health_monitor أُلغيت")
                    return
                continue

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

            pool_max = 20
            pool_current = total
            pool_in_use = active

            _pool_data: Optional[Dict[str, Any]] = None

            try:
                if hasattr(DB, "get_pool_live"):
                    _pd_live = await DB.get_pool_live()
                    if (isinstance(_pd_live, dict)
                            and _pd_live.get("available")
                            and _pd_live.get("max_size")):
                        _pool_data = _pd_live
            except Exception as _e:
                logger.debug(f"pool_health_monitor: get_pool_live: {_e}")

            if _pool_data is None:
                try:
                    if hasattr(DB, "get_pool_stats"):
                        _pd_stats = await DB.get_pool_stats()
                        if (isinstance(_pd_stats, dict)
                                and _pd_stats.get("type") in (
                                    "postgres", "mysql"
                                )
                                and _pd_stats.get("max_size")):
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

            # ✅ v5.5.23: تتبع streak
            if idle_in_tx > 0:
                _idle_tx_streak += 1
            else:
                _idle_tx_streak = 0

            # grace period بعد بدء المهمة
            in_grace = (
                time.monotonic() - _task_start_mono
            ) < _PM_STARTUP_GRACE_SEC

            # ✅ v5.5.23: تحديد المستوى بشكل ذكي
            level = "INFO"
            if idle_in_tx >= _PM_IDLE_TX_ERROR_THRESHOLD:
                level = "ERROR"
            elif util_pct >= _PM_UTIL_CRITICAL_PCT:
                level = "ERROR"
            elif lock_waits >= _PM_LOCK_WAIT_WARN:
                level = "WARNING"
            elif waiting >= _PM_WAITING_WARN:
                level = "WARNING"
            elif util_pct >= _PM_UTIL_WARN_PCT:
                level = "WARNING"
            elif (
                idle_in_tx >= 1
                and _idle_tx_streak >= _PM_IDLE_TX_WARN_STREAK
                and not in_grace
            ):
                level = "WARNING"

            msg = (
                f"total={total}/{pool_max} active={active} idle={idle} "
                f"idle_tx={idle_in_tx} streak={_idle_tx_streak} "
                f"lock_waits={lock_waits} waiting={waiting} "
                f"util={util_pct:.0f}%"
            )

            if level == "ERROR":
                logger.error(f"🔴 pool CRITICAL: {msg}")

                # ✅ v5.5.23: تفاصيل idle_tx مع cooldown
                if idle_in_tx >= 1:
                    now_mono = time.monotonic()
                    if (now_mono - _last_details_dump_mono
                            >= _PM_ALERT_COOLDOWN_SEC):
                        _last_details_dump_mono = now_mono
                        await _dump_idle_tx_details()

            elif level == "WARNING":
                logger.warning(f"⚠️ pool DIAG  : {msg}")
            else:
                # ✅ v5.5.23: اختلاف بين "healthy" و "recovered"
                if _idle_tx_streak == 0:
                    logger.info(f"🟢 pool HEALTH: {msg}")
                else:
                    logger.info(f"🟢 pool OK    : {msg}")

        except asyncio.CancelledError:
            logger.info("🛑 pool_health_monitor أُلغيت")
            raise
        except Exception as e:
            logger.debug(f"pool_health_monitor: {e}")

        try:
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            logger.info("🛑 pool_health_monitor أُلغيت")
            return


# =====================================================================
# ✅ v5.5.16/17: helpers
# =====================================================================

def _resolve_hostname() -> Optional[str]:
    """يُحلّ hostname من متغيرات البيئة."""
    rh = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    if rh:
        return rh.strip()

    ru = os.getenv("RENDER_EXTERNAL_URL")
    if ru:
        ru = ru.strip()
        if ru.startswith("http"):
            try:
                return urlparse(ru).netloc
            except Exception:
                pass
        return ru.rstrip('/')

    rw = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if rw:
        return rw.strip()

    heroku_app = os.getenv("HEROKU_APP_NAME")
    if heroku_app:
        heroku_app = heroku_app.strip()
        if heroku_app:
            return f"{heroku_app}.herokuapp.com"

    wh = os.getenv("WEBHOOK_URL")
    if wh:
        wh = wh.strip()
        if wh.startswith("http"):
            try:
                return urlparse(wh).netloc
            except Exception:
                pass
        return wh.rstrip('/')

    return None


def _resolve_port() -> int:
    """قراءة PORT بشكل آمن."""
    default_port = int(getattr(CONFIG, "WEB_PORT", 10000))
    raw = os.getenv("PORT")

    if raw is None or str(raw).strip() == "":
        return default_port

    try:
        port = int(str(raw).strip())
    except (TypeError, ValueError):
        logger.error(
            f"❌ PORT غير صالح ({raw!r}) — استخدام {default_port}"
        )
        return default_port

    if port < 1 or port > 65535:
        logger.error(
            f"❌ PORT خارج النطاق ({port}) — استخدام {default_port}"
        )
        return default_port

    return port


# =====================================================================
# ✅ v5.5.18: _watch_runner
# =====================================================================

async def _watch_runner(
    runner,
    shutdown_event: asyncio.Event,
    port: int,
) -> None:
    """يراقب خادم Webhook (aiohttp)."""
    try:
        site = None

        if hasattr(runner, "site"):
            site = runner.site
        elif hasattr(runner, "_site"):
            site = runner._site
        elif hasattr(runner, "runner") and hasattr(runner.runner, "site"):
            site = runner.runner.site
        elif hasattr(runner, "_server"):
            site = runner

        if site is None:
            logger.warning(
                "⚠️ _watch_runner: لم أتمكّن من الوصول إلى TCP site "
                "— مراقبة انهيار Webhook معطّلة. "
                "تحقق من القيمة المُرجَعة من setup_webhook()."
            )
            return

        logger.debug("✅ _watch_runner: بدء المراقبة")

        import aiohttp

        probe_failures = 0
        health_url = f"http://127.0.0.1:{port}/health"

        while not shutdown_event.is_set():
            try:
                server = getattr(site, "_server", None)
                if server is None:
                    await asyncio.sleep(2.0)
                    continue

                if server.sockets is None or len(server.sockets) == 0:
                    logger.error(
                        "❌ _watch_runner: خادم Webhook أُغلق بشكل "
                        "غير متوقع — إيقاف البوت بلطف"
                    )
                    shutdown_event.set()
                    return

                try:
                    timeout = aiohttp.ClientTimeout(
                        total=_WATCHER_HEALTH_TIMEOUT
                    )
                    async with aiohttp.ClientSession(
                        timeout=timeout
                    ) as session:
                        async with session.get(health_url) as resp:
                            await resp.read()
                            if resp.status != 200:
                                raise RuntimeError(
                                    f"health status={resp.status}"
                                )
                    probe_failures = 0
                except asyncio.CancelledError:
                    raise
                except Exception as probe_e:
                    probe_failures += 1
                    logger.debug(
                        f"_watch_runner: health probe فشل "
                        f"({probe_failures}/{_WATCHER_MAX_PROBE_FAILURES}): "
                        f"{probe_e}"
                    )
                    if probe_failures >= _WATCHER_MAX_PROBE_FAILURES:
                        logger.error(
                            f"❌ _watch_runner: خادم Webhook لا يستجيب "
                            f"({probe_failures} مرات متتالية) — "
                            f"إيقاف البوت بلطف"
                        )
                        shutdown_event.set()
                        return

                await asyncio.sleep(_WATCHER_INTERVAL)

            except asyncio.CancelledError:
                raise
            except Exception as _e:
                logger.debug(f"_watch_runner loop: {_e}")
                await asyncio.sleep(_WATCHER_INTERVAL)

    except asyncio.CancelledError:
        raise
    except Exception as _e:
        logger.debug(f"_watch_runner: {_e}")


# =====================================================================
# المهمة الرئيسية
# =====================================================================

async def main():
    """الدالة الرئيسية."""
    t_start = time.monotonic()

    try:
        CONFIG.validate()
    except ValueError as e:
        logger.error(f"❌ {e}")
        raise SystemExit(1)

    bot_token = _get_bot_token()
    if not bot_token:
        logger.error("❌ BOT_TOKEN غير محدّد (بيئة أو CONFIG.TOKEN)")
        raise SystemExit(1)

    logger.info(f"🌿 {CONFIG.BOT_NAME}")
    logger.info(f"👨‍💼 المالك: {CONFIG.PRIMARY_OWNER_ID}")

    if not _verify_command_handlers():
        logger.error("❌ فشل فحص دوال الأوامر — الخروج")
        raise SystemExit(1)

    if not _verify_db_config():
        logger.error("❌ فشل فحص إعدادات قاعدة البيانات — الخروج")
        raise SystemExit(1)

    _verify_group_log_handlers()
    _verify_membership_handler()

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

    # ═══ Warmup ═══
    t_warmup = time.monotonic()
    try:
        warmup_result = await warmup_all()
        logger.info(
            f"⏱️ Warmup اكتمل في "
            f"{time.monotonic()-t_warmup:.2f} ثانية"
        )
    except Exception as e:
        logger.warning(
            f"⚠️ Warmup فشل (سيتم المتابعة): {e}",
            exc_info=True,
        )

    port = _resolve_port()
    hostname = _resolve_hostname()

    # ═══ بناء التطبيق ═══
    t_app = time.monotonic()
    app = Application.builder().token(bot_token).build()
    app.bot_data['start_time'] = time.monotonic()
    await app.initialize()
    logger.info(
        f"⏱️ تم تهيئة التطبيق في {time.monotonic()-t_app:.2f} ثانية"
    )

    # ═══ تهيئة group_log ═══
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

    # ═════════════════════════════════════════════════════════════
    # تسجيل الأوامر
    # ═════════════════════════════════════════════════════════════

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

    # ═════════════════════════════════════════════════════════════
    # تسجيل المعالجات
    # ═════════════════════════════════════════════════════════════
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

    app.add_handler(CommandHandler("db_diag", CommandHandlers.db_diag))
    app.add_handler(CommandHandler("db_vacuum", CommandHandlers.db_vacuum))

    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    try:
        register_nav_fix(app)
        logger.info("✅ NAV_FIX: معالج الإغلاق/الرجوع مُسجّل")
    except Exception as e:
        logger.error(f"❌ فشل تسجيل NAV_FIX: {e}", exc_info=True)

    try:
        register_channels_list_handlers(app)
        logger.info("✅ handlers قائمة القنوات مُسجَّل")
    except Exception as e:
        logger.error(f"❌ فشل تسجيل handlers القنوات: {e}", exc_info=True)

    # ═════════════════════════════════════════════════════════════
    # ✅ v5.5.22 (SD-3): تسجيل handlers_channels_delete
    # ═════════════════════════════════════════════════════════════
    if _CH_DELETE_AVAILABLE and callable(register_delete_confirmation):
        try:
            register_delete_confirmation(app)
            logger.info(
                "✅ handlers_channels_delete مُسجَّل — "
                "تأكيد حذف القنوات مُفعّل"
            )
        except Exception as _e:
            logger.error(
                f"❌ فشل تسجيل handlers_channels_delete: {_e}",
                exc_info=True,
            )
    else:
        logger.warning(
            f"⚠️ handlers_channels_delete غير متاح — "
            f"سيتم استخدام الحذف الفوري (بدون تأكيد): "
            f"{_CH_DELETE_IMPORT_ERROR}"
        )

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

    app.add_handler(CallbackQueryHandler(CallbackHandlers.handle))

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

    chat_member.register(app)
    logger.info("✅ ChatMemberHandler مُفعّل — تحديث المشرفين فوري")

    # ═════════════════════════════════════════════════════════════
    # ✅ v5.5.20 (MEM-3): تسجيل MembershipHandler
    # ═════════════════════════════════════════════════════════════
    if _MEMBERSHIP_AVAILABLE and callable(register_membership_handlers):
        try:
            register_membership_handlers(app)
            _source_label = (
                "standalone (FIX-1/FIX-3)" 
                if _MEMBERSHIP_SOURCE == 'standalone'
                else "embedded"
            )
            logger.info(
                f"✅ MembershipHandler مُفعّل [{_source_label}] — "
                f"تقارير إضافة البوت جاهزة"
            )
        except Exception as _e:
            logger.error(
                f"❌ فشل تسجيل MembershipHandler: {_e}",
                exc_info=True,
            )
    else:
        logger.warning(
            f"⚠️ MembershipHandler غير متاح — "
            f"لن تُرسل تقارير إضافة البوت: "
            f"{_MEMBERSHIP_IMPORT_ERROR}"
        )

    # ═════════════════════════════════════════════════════════════
    # المهام الخلفية
    # ═════════════════════════════════════════════════════════════
    async def run_task_with_retry(task_func, *args, task_name=""):
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

    async def contest_cleanup():
        """يُعلن الفائزين تلقائياً للمسابقات المنتهية (كل ساعة)."""
        try:
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            raise

        while True:
            try:
                winners = await DB.auto_declare_expired_contests()

                if winners:
                    logger.info(
                        f"🏆 contest_cleanup: أُعلن "
                        f"{len(winners)} فائزًا تلقائيًا"
                    )

                    for w in winners:
                        winner_id = w.get("winner_id")
                        raw_title = w.get("title") or "مسابقة"
                        title = _html_escape(str(raw_title))
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
                            logger.debug(
                                f"إشعار الفائز {winner_id} فشل: {ne}"
                            )
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
                await asyncio.sleep(3600)
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
        asyncio.create_task(
            run_task_with_retry(
                GroupRateLimiterManager.periodic_cleanup_task,
                task_name="periodic_cleanup"
            )
        ),
        asyncio.create_task(
            run_task_with_retry(
                BackgroundTasks.monitor_pool_alert,
                app.bot,
                task_name="monitor_pool_alert"
            )
        ),
        asyncio.create_task(contest_cleanup()),
        asyncio.create_task(pool_health_monitor()),
        # ✅ v5.5.21 (CLEANUP-2): تنظيف admin_logs دورياً
        asyncio.create_task(cleanup_admin_logs_periodically()),
        # ✅ v5.5.22 (SD-4): تنظيف القنوات المُزالة دورياً
        asyncio.create_task(cleanup_removed_channels_periodically()),
    ]

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
                app.bot,
                owner_id,
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

    # ✅ v5.5.22 (SD-5): رسائل تعريفية بالمهام
    logger.info(f"✅ تم تشغيل {len(tasks)} مهمة خلفية")
    if _ADMIN_LOGS_CLEANUP_AVAILABLE:
        logger.info(
            f"🧹 admin_logs cleanup مُفعّل — كل 24 ساعة "
            f"(احتفاظ={ADMIN_LOGS_RETENTION_DAYS}d, "
            f"حد أقصى={ADMIN_LOGS_MAX_ROWS} صف)"
        )
    logger.info(
        f"🧹 removed_channels cleanup مُفعّل — كل 24 ساعة "
        f"(فترة سماح={_REMOVED_CHANNELS_GRACE_DAYS} يوم)"
    )

    # ═════════════════════════════════════════════════════════════
    # ✅ v5.5.18 (#7): SIGTERM handler
    # ═════════════════════════════════════════════════════════════
    _shutdown_event = asyncio.Event()

    if hostname:
        def _on_sigterm():
            logger.info(
                "🛑 تلقّيت SIGTERM — بدء الإغلاق اللطيف"
            )
            _shutdown_event.set()

        try:
            _loop = asyncio.get_running_loop()
            for _sig in (signal.SIGTERM,):
                try:
                    _loop.add_signal_handler(_sig, _on_sigterm)
                    logger.debug(
                        f"✅ تم تسجيل handler لـ {_sig.name}"
                    )
                except (NotImplementedError, RuntimeError, ValueError) as _e:
                    logger.debug(
                        f"add_signal_handler({_sig.name}) غير مدعوم: {_e}"
                    )
        except Exception as _e:
            logger.debug(f"SIGTERM setup: {_e}")
    else:
        logger.debug(
            "ℹ️ وضع Polling — PTB يدير SIGTERM/SIGINT داخلياً"
        )

    # ═════════════════════════════════════════════════════════════
    # بدء التشغيل
    # ═════════════════════════════════════════════════════════════
    app_shutdown_done = False

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

            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        await resp.read()
                logger.info("🔥 تم تسخين الخادم بنجاح")
            except Exception as _e:
                logger.debug(f"تسخين الخادم: {_e}")

            watcher_task = None
            try:
                watcher_task = asyncio.create_task(
                    _watch_runner(runner, _shutdown_event, port)
                )

                await _shutdown_event.wait()
                logger.info(
                    "📴 تم استلام إشارة الإغلاق — إنهاء الخدمات..."
                )
            finally:
                if watcher_task is not None:
                    watcher_task.cancel()
                    try:
                        await watcher_task
                    except asyncio.CancelledError:
                        pass
                    except Exception as _e:
                        logger.debug(f"watcher_task: {_e}")

                try:
                    await runner.cleanup()
                    logger.info(
                        "✅ aiohttp runner: تم الإغلاق النظيف"
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as _e:
                    logger.debug(
                        f"runner.cleanup (webhook): {_e}"
                    )
        else:
            logger.info("⚠️ وضع Polling (لا يوجد hostname)")
            runner = await setup_webhook(app, port)
            try:
                await app.run_polling(
                    drop_pending_updates=True,
                    allowed_updates=ALLOWED_UPDATES,
                )
                app_shutdown_done = True
            finally:
                try:
                    await runner.cleanup()
                except asyncio.CancelledError:
                    raise
                except Exception as _e:
                    logger.debug(f"runner.cleanup (polling): {_e}")
    finally:
        try:
            await _shutdown_group_log()
        except asyncio.CancelledError:
            raise
        except Exception as _e:
            logger.debug(f"_shutdown_group_log: {_e}")

        if _NOTIFY_TASKS:
            logger.info(
                f"⏳ انتظار {len(_NOTIFY_TASKS)} مهمة إشعار... "
                f"(بحد أقصى {_NOTIFY_SHUTDOWN_TIMEOUT}s)"
            )
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *_NOTIFY_TASKS, return_exceptions=True
                    ),
                    timeout=_NOTIFY_SHUTDOWN_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.debug(
                    "⚠️ انتهت مهلة انتظار الإشعارات — إلغاء المتبقي"
                )
                for _t in list(_NOTIFY_TASKS):
                    _t.cancel()
            except asyncio.CancelledError:
                raise

        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        if not app_shutdown_done:
            try:
                await app.shutdown()
            except asyncio.CancelledError:
                raise
            except Exception as _e:
                logger.debug(f"app.shutdown: {_e}")

    logger.info(
        f"👋 انتهت دورة حياة البوت "
        f"({time.monotonic() - t_start:.2f}s)"
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 تم الإيقاف")
    except Exception as e:
        logger.error(f"❌ خطأ: {e}")
        traceback.print_exc()