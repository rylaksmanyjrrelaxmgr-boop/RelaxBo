#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🌿 Relax Manager – البوت الرئيسي (bot.py v5.6.17-ROBUST-MAINT-IMPORT)
================================================================================
📌 نقطة الدخول الرسمية للتطبيق (entrypoint).

🆕 v5.6.17 (ROBUST-MAINT-IMPORT):
    🟢 PATCH-1: تحسين استيراد db_maintenance_commands — يدعم 5 أسماء:
                register_maintenance_commands
                register
                register_commands
                setup_commands
                setup
    🟢 PATCH-2: رسالة خطأ مُفصَّلة عند الفشل (تُظهر كل المحاولات).

🆕 v5.6.16 (ANALYTICS-HANDLERS-FIX):
    🟢 PATCH-1: استيراد آمن لـ handle_analytics_callback + show_analytics_menu
    🟢 PATCH-2: تسجيل 2 CallbackQueryHandler BEFORE العام
    🟢 PATCH-3: إشعار حالة handlers_analytics في diagnostics
    🟢 PATCH-4: تحديث Load Beacon إلى v5.6.16

🆕 v5.6.15 (CACHE-STATS + CANCEL-COMMAND):
    🟢 PATCH-1: استيراد آمن لـ handle_cache_stats_command من handlers_message
    🟢 PATCH-2: تسجيل /cache_stats (للمطور فقط)
    🟢 PATCH-3: إضافة "cache_stats" إلى ADMIN_COMMANDS
    🟢 PATCH-4: تسجيل /cancel
    🟢 PATCH-5: تحديث Load Beacon إلى v5.6.15

🆕 v5.6.14 (DB-IDLE-COMMAND):
    🟢 PATCH-1: استيراد آمن لـ handle_db_idle_command
    🟢 PATCH-2: تسجيل /db_idle
    🟢 PATCH-3: إضافة "db_idle" إلى ADMIN_COMMANDS
    🟢 PATCH-4: تحديث Load Beacon
================================================================================
"""

import asyncio
import os
import logging
import traceback
import json
import signal
import time
import aiohttp
from datetime import datetime, timedelta
from html import escape as _html_escape
from urllib.parse import urlparse
from typing import Set, Any, Dict, Optional, List, Tuple
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
    PreCheckoutQueryHandler,
)

try:
    from telegram.ext import TypeHandler
    _HAS_TYPE_HANDLER = True
except ImportError:
    TypeHandler = None
    _HAS_TYPE_HANDLER = False

from config import CONFIG

from database import DB, initialize_db, TimeUtils

from handlers import (
    CommandHandlers,
    CallbackHandlers,
    MessageHandlers,
    chat_member,
)

# ═════════════════════════════════════════════════════════════════════
# MembershipHandler
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
                    f"standalone: {_e1} / {_e2} | "
                    f"embedded: {_e3} / {_e4}"
                )

# ═════════════════════════════════════════════════════════════════════
# handlers_analytics — استيراد آمن
# ═════════════════════════════════════════════════════════════════════
_ANALYTICS_HANDLERS_AVAILABLE = False
_ANALYTICS_HANDLERS_IMPORT_ERROR = None
_handle_analytics_callback = None
_show_analytics_menu = None

try:
    from handlers.handlers_analytics import (
        handle_analytics_callback as _handle_analytics_callback,
        show_analytics_menu as _show_analytics_menu,
    )
    _ANALYTICS_HANDLERS_AVAILABLE = True
except ImportError as _e_an1:
    try:
        from handlers_analytics import (  # type: ignore
            handle_analytics_callback as _handle_analytics_callback,
            show_analytics_menu as _show_analytics_menu,
        )
        _ANALYTICS_HANDLERS_AVAILABLE = True
    except ImportError as _e_an2:
        _handle_analytics_callback = None
        _show_analytics_menu = None
        _ANALYTICS_HANDLERS_AVAILABLE = False
        _ANALYTICS_HANDLERS_IMPORT_ERROR = f"{_e_an1} | {_e_an2}"

# ═════════════════════════════════════════════════════════════════════
# فحص محرك كشف السبام
# ═════════════════════════════════════════════════════════════════════
_SPAM_DETECTOR_AVAILABLE = False
_SPAM_DETECTOR_IMPORT_ERROR = None
_SPAM_DETECTOR_VERSION = None
_SPAM_DETECTOR_LAYERS_COUNT = 0
_SPAM_DETECTOR_SOURCE = None

_detectors_module = None
for _mod_path in (
    "handlers_message_detectors",
    "handlers.handlers_message_detectors",
    ".handlers_message_detectors",
):
    try:
        if _mod_path.startswith("."):
            from importlib import import_module
            _detectors_module = import_module(
                _mod_path, package=__package__ or None,
            )
        else:
            from importlib import import_module
            _detectors_module = import_module(_mod_path)
        _SPAM_DETECTOR_AVAILABLE = True
        _SPAM_DETECTOR_SOURCE = _mod_path
        break
    except ImportError as _e:
        _SPAM_DETECTOR_IMPORT_ERROR = str(_e)
        _detectors_module = None
    except Exception as _e:
        _SPAM_DETECTOR_IMPORT_ERROR = f"unexpected: {_e}"
        _detectors_module = None

_shutdown_detector_pool_fn = None
_install_default_executor_fn = None
_shutdown_default_executor_fn = None
_DETECTORS_HAS_SHUTDOWN_HELPER = False
_DETECTORS_HAS_INSTALL_HELPER = False

if _SPAM_DETECTOR_AVAILABLE and _detectors_module is not None:
    try:
        _SPAM_DETECTOR_VERSION = getattr(
            _detectors_module, "_DETECTORS_VERSION", None,
        )
        _layer_weights = getattr(_detectors_module, "LAYER_WEIGHTS", {})
        if isinstance(_layer_weights, dict) and _layer_weights:
            _SPAM_DETECTOR_LAYERS_COUNT = len(_layer_weights)
        else:
            _layer_flag_names = (
                "TEXT_LAYER_ENABLED", "OCR_LAYER_ENABLED",
                "AUDIO_LAYER_ENABLED", "URL_LAYER_ENABLED",
                "METADATA_LAYER_ENABLED", "OBFUSCATION_LAYER_ENABLED",
                "BEHAVIORAL_LAYER_ENABLED", "VIDEO_LAYER_ENABLED",
                "NSFW_LAYER_ENABLED", "STICKER_LAYER_ENABLED",
                "REACTIONS_LAYER_ENABLED", "CONTEXT_LAYER_ENABLED",
                "CIPHER_LAYER_ENABLED", "STEGO_LAYER_ENABLED",
                "DOMAIN_REP_LAYER_ENABLED",
            )
            _SPAM_DETECTOR_LAYERS_COUNT = sum(
                1 for name in _layer_flag_names
                if hasattr(_detectors_module, name)
            )
    except Exception as _e:
        logger_pre_init = logging.getLogger(__name__)
        logger_pre_init.debug("detector introspection: %s", _e)

    try:
        _shutdown_detector_pool_fn = getattr(
            _detectors_module, "_shutdown_shared_pool", None,
        )
        _shutdown_default_executor_fn = getattr(
            _detectors_module, "shutdown_default_executor", None,
        )
        _install_default_executor_fn = getattr(
            _detectors_module, "install_default_executor", None,
        )
        _DETECTORS_HAS_SHUTDOWN_HELPER = callable(
            _shutdown_default_executor_fn
        )
        _DETECTORS_HAS_INSTALL_HELPER = callable(
            _install_default_executor_fn
        )
    except Exception as _e:
        logger_pre_init = logging.getLogger(__name__)
        logger_pre_init.debug("detectors helpers bind: %s", _e)

# ═════════════════════════════════════════════════════════════════════
# فحص Security Bridge
# ═════════════════════════════════════════════════════════════════════
_SECURITY_BRIDGE_AVAILABLE = False
_SB_IMPORT_ERROR = None
try:
    from utils import (
        SECURITY_TOGGLE_MAP as _stm,
        NEW_SECURITY_DEFAULTS as _nsd,
        get_security_settings as _bridge_get_sec,
        invalidate_security_settings_cache as _bridge_inv_sec,
        should_delete_by_security as _bridge_should_del,
        check_all_security as _bridge_check_all,
    )
    _SECURITY_BRIDGE_AVAILABLE = True
except ImportError as _sb_e:
    _SECURITY_BRIDGE_AVAILABLE = False
    _SB_IMPORT_ERROR = str(_sb_e)
except Exception as _sb_e:
    _SECURITY_BRIDGE_AVAILABLE = False
    _SB_IMPORT_ERROR = f"unexpected: {_sb_e}"

# ═════════════════════════════════════════════════════════════════════
# admin_logs cleanup
# ═════════════════════════════════════════════════════════════════════
try:
    from database_tables import (
        _cleanup_old_admin_logs_postgres as _cleanup_admin_logs_pg,
        _cleanup_old_admin_logs_sqlite as _cleanup_admin_logs_sqlite,
        _cleanup_old_admin_logs_mysql as _cleanup_admin_logs_mysql,
        ADMIN_LOGS_RETENTION_DAYS,
        ADMIN_LOGS_MAX_ROWS,
        CURRENT_SCHEMA_VERSION as _DB_SCHEMA_VERSION,
    )
    _ADMIN_LOGS_CLEANUP_AVAILABLE = True
    _ADMIN_LOGS_CLEANUP_IMPORT_ERROR = None
except ImportError as _e:
    _cleanup_admin_logs_pg = None
    _cleanup_admin_logs_sqlite = None
    _cleanup_admin_logs_mysql = None
    ADMIN_LOGS_RETENTION_DAYS = 30
    ADMIN_LOGS_MAX_ROWS = 5000
    _DB_SCHEMA_VERSION = None
    _ADMIN_LOGS_CLEANUP_AVAILABLE = False
    _ADMIN_LOGS_CLEANUP_IMPORT_ERROR = str(_e)

# ═════════════════════════════════════════════════════════════════════
# handlers_channels_delete
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

from handlers.handlers_channels_list import register_channels_list_handlers
from handlers.handlers_nav_fix import register_nav_fix
from handlers.handlers_message import (
    GroupRateLimiterManager,
    register_shutdown_handlers as _register_message_shutdown,
    shutdown_log_dispatcher as _shutdown_log_dispatcher,
    shutdown_delete_tasks as _shutdown_delete_tasks,
    handle_autoblocked_command as _handle_autoblocked_command,
)

# ═════════════════════════════════════════════════════════════════════
# /db_idle — استيراد آمن
# ═════════════════════════════════════════════════════════════════════
_HAS_DB_IDLE_CMD = False
_handle_db_idle_command = None

try:
    from handlers.handlers_message import (
        handle_db_idle_command as _handle_db_idle_command_imported,
    )
    _handle_db_idle_command = _handle_db_idle_command_imported
    _HAS_DB_IDLE_CMD = True
except ImportError as _e_dbidle1:
    try:
        from handlers_message import (  # type: ignore
            handle_db_idle_command as _handle_db_idle_command_imported,
        )
        _handle_db_idle_command = _handle_db_idle_command_imported
        _HAS_DB_IDLE_CMD = True
    except ImportError as _e_dbidle2:
        _handle_db_idle_command = None
        _HAS_DB_IDLE_CMD = False
        _DB_IDLE_IMPORT_ERROR = f"{_e_dbidle1} | {_e_dbidle2}"

# ═════════════════════════════════════════════════════════════════════
# /cache_stats — استيراد آمن
# ═════════════════════════════════════════════════════════════════════
_HAS_CACHE_STATS_CMD = False
_handle_cache_stats_command = None

try:
    from handlers.handlers_message import (
        handle_cache_stats_command as _handle_cache_stats_command_imported,
    )
    _handle_cache_stats_command = _handle_cache_stats_command_imported
    _HAS_CACHE_STATS_CMD = True
except ImportError as _e_cs1:
    try:
        from handlers_message import (  # type: ignore
            handle_cache_stats_command as _handle_cache_stats_command_imported,
        )
        _handle_cache_stats_command = _handle_cache_stats_command_imported
        _HAS_CACHE_STATS_CMD = True
    except ImportError as _e_cs2:
        _handle_cache_stats_command = None
        _HAS_CACHE_STATS_CMD = False
        _CACHE_STATS_IMPORT_ERROR = f"{_e_cs1} | {_e_cs2}"

# ═════════════════════════════════════════════════════════════════════
# db_maintenance_commands — 🆕 v5.6.17 ROBUST IMPORT
# ═════════════════════════════════════════════════════════════════════
register_maintenance_commands = None
start_weekly_diagnostic_task = None
stop_weekly_diagnostic_task = None
_MAINT_CMDS_AVAILABLE = False
_MAINT_CMDS_IMPORT_ERROR = None

# 🆕 v5.6.17: قائمة الأسماء المحتملة بترتيب الأولوية
_MAINT_REGISTER_NAMES = (
    "register_maintenance_commands",
    "register",
    "register_commands",
    "setup_commands",
    "setup",
    "register_maintenance",
    "register_db_maintenance",
)

_maint_import_attempts: List[str] = []

# 1) حاول استيراد الوحدة كاملة
try:
    import db_maintenance_commands as _maint_mod
    _mod_import_ok = True
except ImportError as _e_mod:
    _mod_import_ok = False
    _maint_import_attempts.append(f"import module: {_e_mod}")
    _maint_mod = None

# 2) حاول استيراد دوال start/stop weekly
if _mod_import_ok:
    try:
        start_weekly_diagnostic_task = getattr(
            _maint_mod, "start_weekly_diagnostic_task", None
        )
    except Exception:
        start_weekly_diagnostic_task = None

    try:
        stop_weekly_diagnostic_task = getattr(
            _maint_mod, "stop_weekly_diagnostic_task", None
        )
    except Exception:
        stop_weekly_diagnostic_task = None

    # 3) حاول إيجاد دالة register بأي اسم
    for _name in _MAINT_REGISTER_NAMES:
        _fn = getattr(_maint_mod, _name, None)
        if callable(_fn):
            register_maintenance_commands = _fn
            _MAINT_CMDS_AVAILABLE = True
            logger_temp = logging.getLogger(__name__)
            logger_temp.info(
                "✅ db_maintenance_commands: وجدتُ الدالة بالاسم %r",
                _name,
            )
            break
        else:
            _maint_import_attempts.append(f"getattr({_name}): not found")

    if not _MAINT_CMDS_AVAILABLE:
        _MAINT_CMDS_IMPORT_ERROR = (
            "لم أجد أي دالة register بالأسماء: "
            + ", ".join(_MAINT_REGISTER_NAMES)
        )
else:
    _MAINT_CMDS_IMPORT_ERROR = " | ".join(_maint_import_attempts) or "unknown"

# ═════════════════════════════════════════════════════════════════════
# _notify_dev_log
# ═════════════════════════════════════════════════════════════════════
try:
    from handlers.handlers_command import _notify_dev_log
    _DEV_LOG_AVAILABLE = True
except ImportError:
    try:
        from handlers_command import _notify_dev_log
        _DEV_LOG_AVAILABLE = True
    except ImportError:
        async def _notify_dev_log(context, text: str) -> None:
            pass
        _DEV_LOG_AVAILABLE = False

# ═════════════════════════════════════════════════════════════════════
# group_log
# ═════════════════════════════════════════════════════════════════════
try:
    from handlers.handlers_group_log import register_group_log_handlers
    _GROUP_LOG_AVAILABLE = True
    _GROUP_LOG_IMPORT_ERROR = None
except ImportError as _e:
    register_group_log_handlers = None
    _GROUP_LOG_AVAILABLE = False
    _GROUP_LOG_IMPORT_ERROR = str(_e)

try:
    from group_log import init_group_log as _init_group_log
    _GROUP_LOG_INIT_AVAILABLE = True
    _GROUP_LOG_INIT_IMPORT_ERROR = None
except ImportError as _e:
    _init_group_log = None
    _GROUP_LOG_INIT_AVAILABLE = False
    _GROUP_LOG_INIT_IMPORT_ERROR = str(_e)

try:
    from maintenance import maintenance_loop as _maintenance_loop
    _MAINTENANCE_AVAILABLE = True
    _MAINTENANCE_IMPORT_ERROR = None
except ImportError as _e:
    _maintenance_loop = None
    _MAINTENANCE_AVAILABLE = False
    _MAINTENANCE_IMPORT_ERROR = str(_e)

from utils import (
    TranslationManager, KeyboardFactory, BackgroundTasks,
    ErrorHandler, setup_webhook, safe_send,
    warmup_all,
)
from cache import cache_cleanup_task, user_cache, invalidate_user_cache  # noqa: F401

# ═══════════════════════════════════════════════════════════════════
# Logging setup
# ═══════════════════════════════════════════════════════════════════

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL, logging.INFO)
)

for _noisy in (
    "httpx",
    "httpcore",
    "telegram.request",
    "telegram.ext.ExtBot",
    "aiohttp.access",
):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

_NOTIFY_SHUTDOWN_TIMEOUT = 5.0
_BG_TASKS_SHUTDOWN_TIMEOUT = 10.0

_WATCHER_INTERVAL = 10.0
_WATCHER_HEALTH_TIMEOUT = 5.0
_WATCHER_MAX_PROBE_FAILURES = 3

_REMOVED_CHANNELS_GRACE_DAYS = 30

_PM_STARTUP_GRACE_SEC = 180.0
_PM_INITIAL_DELAY_SEC = 120.0
_PM_IDLE_TX_WARN_STREAK = 2
_PM_IDLE_TX_ERROR_THRESHOLD = 3
_PM_UTIL_WARN_PCT = 80.0
_PM_UTIL_CRITICAL_PCT = 95.0
_PM_LOCK_WAIT_WARN = 1
_PM_WAITING_WARN = 3
_PM_ALERT_COOLDOWN_SEC = 600.0

_PAYMENT_AMOUNT_EPSILON = 0.01

_DIAG_INCOMING = os.getenv("DIAG_INCOMING", "0").strip().lower() in (
    "1", "true", "yes", "on", "enabled",
)

# ═══════════════════════════════════════════════════════════════════
# مساعد مقارنة المبالغ
# ═══════════════════════════════════════════════════════════════════

def _amounts_match(expected: Any, actual: Any) -> bool:
    try:
        e = float(expected or 0)
        a = float(actual or 0)
    except (TypeError, ValueError):
        return False
    return abs(e - a) < _PAYMENT_AMOUNT_EPSILON

# ═══════════════════════════════════════════════════════════════════
# متتبّع مهام الإشعارات
# ═══════════════════════════════════════════════════════════════════

_NOTIFY_TASKS: Set[asyncio.Task] = set()

def _spawn_notify_dev_log(context, text: str) -> None:
    try:
        task = asyncio.create_task(_notify_dev_log(context, text))
        _NOTIFY_TASKS.add(task)

        def _cleanup(t: asyncio.Task) -> None:
            _NOTIFY_TASKS.discard(t)
            try:
                if not t.cancelled() and t.exception():
                    logger.debug(
                        "notify_dev_log task failed: %s", t.exception()
                    )
            except Exception:
                pass

        task.add_done_callback(_cleanup)
    except Exception as _e:
        logger.debug("_spawn_notify_dev_log: %s", _e)

# ═══════════════════════════════════════════════════════════════════
# تقرير محرك كشف السبام
# ═══════════════════════════════════════════════════════════════════

def _log_spam_detector_status() -> None:
    """يطبع حالة محرك كشف السبام + التبعيات (v4.0.8-aware)."""

    if _SPAM_DETECTOR_AVAILABLE:
        _helpers_ok = []
        if _DETECTORS_HAS_INSTALL_HELPER:
            _helpers_ok.append("install")
        if _DETECTORS_HAS_SHUTDOWN_HELPER:
            _helpers_ok.append("shutdown")
        _helpers_label = (
            f"helpers={','.join(_helpers_ok)}"
            if _helpers_ok else "helpers=none"
        )

        logger.info(
            "🛡️ Spam Detector: ✅ محمّل (%s, %d layers, %s) [from %s]",
            _SPAM_DETECTOR_VERSION or "unknown version",
            _SPAM_DETECTOR_LAYERS_COUNT,
            _helpers_label,
            _SPAM_DETECTOR_SOURCE or "unknown",
        )
    else:
        logger.warning(
            "⚠️ Spam Detector: ❌ غير محمّل — السبب: %s",
            _SPAM_DETECTOR_IMPORT_ERROR or "unknown",
        )
        logger.warning(
            "   💡 تأكد من وجود handlers_message_detectors.py في: "
            "الجذر، أو handlers/، أو نفس مجلد bot.py"
        )
        return

    try:
        _summary = CONFIG.DETECTION_SUMMARY  # type: ignore
        _enabled = [k for k, v in _summary.items() if v]
        _disabled = [k for k, v in _summary.items() if not v]

        logger.info(
            "   📊 الطبقات (per CONFIG): %d/%d مُفعَّلة",
            len(_enabled), len(_summary),
        )
        if _enabled:
            logger.info("   ✅ مُفعَّلة: %s", ", ".join(_enabled))
        if _disabled:
            logger.info("   ❌ معطّلة: %s", ", ".join(_disabled))
    except AttributeError:
        logger.debug(
            "   ℹ️ CONFIG.DETECTION_SUMMARY غير متاح "
            "(config.py قديم؟)"
        )

    _deps: Dict[str, bool] = {}

    try:
        import numpy  # noqa: F401
        _deps["numpy (L13 Stego)"] = True
    except ImportError:
        _deps["numpy (L13 Stego)"] = False

    try:
        import PIL  # noqa: F401
        _deps["Pillow (L1 OCR)"] = True
    except ImportError:
        _deps["Pillow (L1 OCR)"] = False

    try:
        import pytesseract  # noqa: F401
        _deps["pytesseract (L1 OCR)"] = True
    except ImportError:
        _deps["pytesseract (L1 OCR)"] = False

    try:
        from pyzbar.pyzbar import decode as _test_qr_decode  # noqa: F401
        _deps["pyzbar (L1 QR)"] = True
    except ImportError:
        _deps["pyzbar (L1 QR)"] = False
    except Exception:
        _deps["pyzbar (L1 QR)"] = False

    try:
        import cv2  # noqa: F401
        _deps["opencv (L7 Video)"] = True
    except ImportError:
        _deps["opencv (L7 Video)"] = False

    try:
        import speech_recognition  # noqa: F401
        _deps["SpeechRecognition (L2 Audio)"] = True
    except ImportError:
        _deps["SpeechRecognition (L2 Audio)"] = False

    try:
        from pydub import AudioSegment  # noqa: F401
        _deps["pydub (L2 Audio)"] = True
    except ImportError:
        _deps["pydub (L2 Audio)"] = False

    try:
        import requests  # noqa: F401
        _deps["requests (L3 URL)"] = True
    except ImportError:
        _deps["requests (L3 URL)"] = False

    try:
        import whois  # noqa: F401
        _deps["python-whois (L3 URL)"] = True
    except ImportError:
        _deps["python-whois (L3 URL)"] = False

    try:
        import torch  # noqa: F401
        _deps["torch (L8 NSFW-local backend)"] = True
    except ImportError:
        _deps["torch (L8 NSFW-local backend)"] = False

    try:
        import transformers  # noqa: F401
        _deps["transformers (L8 NSFW-local)"] = True
    except ImportError:
        _deps["transformers (L8 NSFW-local)"] = False

    _se_user = os.getenv("SIGHTENGINE_API_USER", "").strip()
    _se_secret = os.getenv("SIGHTENGINE_API_SECRET", "").strip()
    _deps["Sightengine API (L8 NSFW-cloud)"] = bool(_se_user and _se_secret)

    if _detectors_module is not None:
        try:
            _deps["NSFW local mode enabled"] = bool(
                getattr(_detectors_module, "NSFW_MODEL_ENABLED", False)
            )
        except Exception:
            pass

    _missing_deps = [name for name, ok in _deps.items() if not ok]
    _loaded_deps = [name for name, ok in _deps.items() if ok]

    if _loaded_deps:
        logger.info(
            "   📦 التبعيات المتوفرة (%d): %s",
            len(_loaded_deps), ", ".join(_loaded_deps),
        )
    if _missing_deps:
        logger.debug(
            "   ⚠️ التبعيات المفقودة (%d): %s",
            len(_missing_deps), ", ".join(_missing_deps),
        )

    try:
        import subprocess as _sp
        _r = _sp.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=3,
        )
        _ffmpeg_ok = (_r.returncode == 0)
    except Exception:
        _ffmpeg_ok = False

    if _ffmpeg_ok:
        logger.info("   🎬 ffmpeg: ✅ متوفر")
    else:
        logger.info(
            "   🎬 ffmpeg: ⚠️ غير متوفر — فيديو كبير لن يُعالَج"
        )

    try:
        _sb_key = getattr(CONFIG, "SAFE_BROWSING_API_KEY", "")
        if _sb_key:
            logger.info("   🔗 Safe Browsing API: ✅ مُهيَّأ")
        else:
            logger.info(
                "   🔗 Safe Browsing API: ⚠️ غير مُهيَّأ "
                "(يُوصى به لدقة كشف الروابط)"
            )
    except AttributeError:
        pass

def _log_security_bridge_status() -> None:
    if _SECURITY_BRIDGE_AVAILABLE:
        try:
            _buttons = len(_stm)
            _defaults = len(_nsd)
            logger.info(
                "🌉 Security Bridge: ✅ محمّل | "
                "أزرار=%d | قيم افتراضية=%d",
                _buttons, _defaults,
            )
        except Exception:
            logger.info("🌉 Security Bridge: ✅ محمّل")
    else:
        logger.warning(
            "⚠️ Security Bridge: غير متاح — السبب: %s",
            _SB_IMPORT_ERROR or "unknown",
        )

# ═══════════════════════════════════════════════════════════════════
# Diagnostics — Mixins
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
    logger.error("❌ فحص Analytics: %s", _e)
    ANALYTICS_MIXIN_AVAILABLE = False

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
        logger.warning("⚠️ Mixins مفقودة: %s", _missing)
    else:
        logger.info("✅ كل الـ %d Mixins محمّلة", len(_mixins_status))
except Exception as _e:
    logger.debug("⚠️ فحص Mixins: %s", _e)

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
    logger.debug("⚠️ فحص RefactorMixin: %s", _e)

# ═══════════════════════════════════════════════════════════════════
# Diagnostics — Optional modules
# ═══════════════════════════════════════════════════════════════════

if _MAINTENANCE_AVAILABLE:
    logger.info("✅ maintenance محمّل — الصيانة الدورية مُفعّلة")
else:
    logger.warning(
        "⚠️ maintenance غير متاح: %s",
        _MAINTENANCE_IMPORT_ERROR or "unknown",
    )

if _DEV_LOG_AVAILABLE:
    logger.info("✅ _notify_dev_log متاح — إشعارات قناة السجل مُفعّلة")
else:
    logger.warning(
        "⚠️ _notify_dev_log غير متاح — لن تُرسل إشعارات الدفع"
    )

if _MEMBERSHIP_AVAILABLE:
    if _MEMBERSHIP_SOURCE == 'standalone':
        logger.info(
            "✅ MembershipHandler (standalone) — "
            "FIX-1 قناة المجموعة + FIX-3 عرض النطاق مُفعّلة"
        )
    elif _MEMBERSHIP_SOURCE == 'embedded':
        logger.info(
            "✅ MembershipHandler (embedded in handlers_callback)"
        )
    else:
        logger.info("✅ MembershipHandler متاح")
else:
    logger.warning(
        "⚠️ register_membership_handlers غير متاح: %s",
        _MEMBERSHIP_IMPORT_ERROR or "unknown",
    )

if _ADMIN_LOGS_CLEANUP_AVAILABLE:
    logger.info(
        "✅ admin_logs cleanup متاح — احتفاظ=%dd, حد أقصى=%d صف",
        ADMIN_LOGS_RETENTION_DAYS, ADMIN_LOGS_MAX_ROWS,
    )
    if _DB_SCHEMA_VERSION is not None:
        logger.info(
            "✅ database_tables v7.9.0 (schema version=%d)",
            _DB_SCHEMA_VERSION,
        )
else:
    logger.warning(
        "⚠️ دوال تنظيف admin_logs غير متاحة: %s — المهمة معطّلة",
        _ADMIN_LOGS_CLEANUP_IMPORT_ERROR or "unknown",
    )

if _CH_DELETE_AVAILABLE:
    logger.info(
        "✅ handlers_channels_delete متاح — تأكيد حذف القنوات مُفعّل"
    )
else:
    logger.warning(
        "⚠️ handlers_channels_delete غير متاح: %s — "
        "سيتم استخدام الحذف الفوري (بدون تأكيد)",
        _CH_DELETE_IMPORT_ERROR or "unknown",
    )

# 🆕 v5.6.17: إشعار db_maintenance_commands (محسّن)
if _MAINT_CMDS_AVAILABLE:
    logger.info(
        "✅ db_maintenance_commands متاح — "
        "/db_diag_quick, /db_maintenance, /db_weekly مُفعّلة"
    )
else:
    logger.warning(
        "⚠️ db_maintenance_commands غير متاح: %s — "
        "أوامر الصيانة معطّلة",
        _MAINT_CMDS_IMPORT_ERROR or "unknown",
    )

if _HAS_DB_IDLE_CMD:
    logger.info(
        "✅ /db_idle متاح — تدقيق idle-in-transaction (للمطور فقط)"
    )
else:
    logger.debug(
        "ℹ️ /db_idle غير متاح — "
        "يتطلب handlers_message.py v7.18.14+"
    )

if _HAS_CACHE_STATS_CMD:
    logger.info(
        "✅ /cache_stats متاح — إحصائيات الكاش الحية (للمطور فقط)"
    )
else:
    logger.debug(
        "ℹ️ /cache_stats غير متاح — "
        "يتطلب handlers_message.py v7.18.18+"
    )

if _ANALYTICS_HANDLERS_AVAILABLE:
    logger.info(
        "✅ handlers_analytics متاح — "
        "أزرار التحليلات المتقدمة (10 معالجات) جاهزة"
    )
else:
    logger.warning(
        "⚠️ handlers_analytics غير متاح — "
        "أزرار التحليلات لن تعمل: %s",
        _ANALYTICS_HANDLERS_IMPORT_ERROR or "unknown",
    )

_log_spam_detector_status()
_log_security_bridge_status()

# ═══════════════════════════════════════════════════════════════════
# Allowed updates
# ═══════════════════════════════════════════════════════════════════

ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "callback_query",
    "chat_join_request",
    "pre_checkout_query",
    "chat_member",
    "my_chat_member",
]

_GROUP_LOG_INSTANCE = None

# ═══════════════════════════════════════════════════════════════════
# Bot command lists
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
    ("db_diag_quick", "🔬 تقرير صحي مختصر"),
    ("db_maintenance", "🧹 صيانة قاعدة البيانات"),
    ("db_weekly", "📅 التقرير الأسبوعي"),
    ("autoblocked", "🚫 المصادر المحجوبة تلقائياً"),
    ("db_idle", "🔍 تدقيق idle-in-transaction"),
    ("cache_stats", "📊 إحصائيات الكاش الحية"),
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

# ═══════════════════════════════════════════════════════════════════
# إغلاق مهام + pool + default executor
# ═══════════════════════════════════════════════════════════════════

async def _shutdown_detector_tasks(timeout: float = 3.0) -> None:
    if not _SPAM_DETECTOR_AVAILABLE or _detectors_module is None:
        return

    if _DETECTORS_HAS_SHUTDOWN_HELPER:
        try:
            result = _shutdown_default_executor_fn(timeout=timeout)
            if asyncio.iscoroutine(result):
                await asyncio.wait_for(result, timeout=timeout + 0.5)
            logger.info(
                "✅ detectors: shutdown_default_executor complete"
            )
            return
        except asyncio.TimeoutError:
            logger.warning(
                "⚠️ detectors shutdown_default_executor: timeout"
            )
        except Exception as _e:
            logger.debug(
                "shutdown_default_executor failed: %s — fallback", _e,
            )

    if callable(_shutdown_detector_pool_fn):
        try:
            result = _shutdown_detector_pool_fn()
            if asyncio.iscoroutine(result):
                await asyncio.wait_for(result, timeout=timeout)
            logger.info("✅ detectors pool: shutdown (via helper)")
            return
        except asyncio.TimeoutError:
            logger.warning("⚠️ detectors pool shutdown: timeout")
        except Exception as _e:
            logger.debug("_shutdown_detector_pool_fn: %s", _e)

    try:
        getter = getattr(_detectors_module, "_get_shared_pool", None)
        if callable(getter):
            pool = getter()
            if pool is not None:
                try:
                    pool.shutdown(wait=False, cancel_futures=True)
                    logger.info("✅ detectors pool: shutdown (direct)")
                except TypeError:
                    pool.shutdown(wait=False)
                    logger.info("✅ detectors pool: shutdown (legacy)")
    except Exception as _e:
        logger.debug("_shutdown_detector_tasks (direct): %s", _e)

# ═══════════════════════════════════════════════════════════════════
# Admin IDs collection
# ═══════════════════════════════════════════════════════════════════

async def _collect_admin_ids() -> List[int]:
    admin_ids: Set[int] = set()

    try:
        owner = int(getattr(CONFIG, "PRIMARY_OWNER_ID", 0) or 0)
        if owner:
            admin_ids.add(owner)
    except (TypeError, ValueError):
        pass

    try:
        for dev in (getattr(CONFIG, "DEVELOPER_IDS", []) or []):
            try:
                d = int(dev)
                if d:
                    admin_ids.add(d)
            except (TypeError, ValueError):
                continue
    except Exception:
        pass

    admin_list_getters = ("get_admin_list", "get_all_admins", "get_admins")

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
                    "ℹ️ _collect_admin_ids: DB.%s() أعادت قائمة فارغة "
                    "— تجربة الدالة التالية",
                    method_name,
                )
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

            logger.debug(
                "✅ _collect_admin_ids: قرأ %d أدمن من DB.%s()",
                added_from_db, method_name,
            )
            break
        except Exception as _e:
            last_error = _e
            logger.debug(
                "_collect_admin_ids → DB.%s(): %s", method_name, _e
            )
            continue

    if not any_method_succeeded and last_error is not None:
        logger.warning(
            "⚠️ _collect_admin_ids: فشلت كل الطرق — آخر خطأ: %s. "
            "الأوامر الإدارية ستظهر للمالك والمطورين فقط.",
            last_error,
        )

    return sorted(admin_ids)

# ═══════════════════════════════════════════════════════════════════
# Refresh admin commands
# ═══════════════════════════════════════════════════════════════════

async def refresh_admin_commands(bot, user_id: int, is_admin: bool) -> bool:
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
            "✅ refresh_admin_commands(%d, is_admin=%s) نجح",
            uid, is_admin,
        )
        return True
    except Exception as e:
        logger.warning("⚠️ refresh_admin_commands(%d): %s", uid, e)
        return False

# ═══════════════════════════════════════════════════════════════════
# Token redaction
# ═══════════════════════════════════════════════════════════════════

def _get_bot_token() -> str:
    env_token = os.getenv("BOT_TOKEN", "").strip()
    if env_token:
        return env_token
    return getattr(CONFIG, "TOKEN", "") or ""

def _redact_token(text: str, token: str = None) -> str:
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

def _safe_url(url: str) -> str:
    return _redact_token(url)

# ═══════════════════════════════════════════════════════════════════
# Verifications
# ═══════════════════════════════════════════════════════════════════

_command_handlers_verified: Optional[bool] = None

def _verify_command_handlers() -> bool:
    global _command_handlers_verified
    if _command_handlers_verified is not None:
        return _command_handlers_verified

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

    missing = [name for name in required if not hasattr(CommandHandlers, name)]

    if missing:
        logger.error(
            "❌ دوال مفقودة في CommandHandlers (%d): %s",
            len(missing), missing,
        )
        _command_handlers_verified = False
        return False

    logger.info("✅ كل %d دالة CommandHandlers موجودة", len(required))

    if not hasattr(MessageHandlers, "handle_edited"):
        logger.warning(
            "⚠️ MessageHandlers.handle_edited مفقود — "
            "تعديل الرسائل لن يُفحص! حدّث handlers_message.py إلى v7.15.1+"
        )
    else:
        logger.info("✅ MessageHandlers.handle_edited متاح")

    _command_handlers_verified = True
    return True

def _verify_db_config() -> bool:
    try:
        db_type = getattr(DB, "DB_TYPE", "unknown")
        db_url = getattr(CONFIG, "DATABASE_URL", "") or ""

        if not db_url:
            if db_type != "sqlite":
                logger.warning(
                    "⚠️ DB_TYPE=%s لكن DATABASE_URL فارغ! "
                    "سيتم fallback إلى SQLite",
                    db_type,
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

        logger.info("✅ DB: %s — إعداد صحيح", db_type.upper())
        return True
    except Exception as e:
        logger.warning("⚠️ فشل فحص DB: %s", e, exc_info=True)
        return True

def _verify_group_log_handlers() -> bool:
    if not _GROUP_LOG_AVAILABLE:
        logger.warning(
            "⚠️ handlers_group_log غير متاح: %s",
            _GROUP_LOG_IMPORT_ERROR or "unknown",
        )
        logger.warning("⚠️ زر قناة السجل لن يعمل — سيتم تجاهله")
        return False

    if not callable(register_group_log_handlers):
        logger.warning("⚠️ register_group_log_handlers غير قابل للاستدعاء")
        return False

    logger.info("✅ handlers_group_log متاح")
    return True

def _verify_membership_handler() -> bool:
    if not _MEMBERSHIP_AVAILABLE:
        logger.warning(
            "⚠️ MembershipHandler غير متاح: %s",
            _MEMBERSHIP_IMPORT_ERROR or "unknown",
        )
        return False
    if not callable(register_membership_handlers):
        logger.warning("⚠️ register_membership_handlers غير قابل للاستدعاء")
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

def _init_group_log_instance(app) -> bool:
    global _GROUP_LOG_INSTANCE

    if not _GROUP_LOG_INIT_AVAILABLE:
        logger.warning(
            "⚠️ group_log.init غير متاح: %s",
            _GROUP_LOG_INIT_IMPORT_ERROR or "unknown",
        )
        return False

    if not callable(_init_group_log):
        logger.warning("⚠️ init_group_log غير قابل للاستدعاء")
        return False

    bot = getattr(app, "bot", None)
    if bot is None:
        logger.error(
            "❌ _init_group_log_instance: app.bot = None — "
            "هل app.initialize() نُفِّذ؟"
        )
        return False

    try:
        _GROUP_LOG_INSTANCE = _init_group_log(DB, bot)
        if _GROUP_LOG_INSTANCE is None:
            logger.error("❌ init_group_log أعاد None")
            return False

        _GROUP_LOG_INSTANCE.start()
        logger.info("✅ GroupLog: instance مُنشأ + worker started")
        return True
    except Exception as e:
        logger.error("❌ فشل تهيئة GroupLog: %s", e, exc_info=True)
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
        logger.warning("⚠️ GroupLog shutdown: %s", e)
    finally:
        _GROUP_LOG_INSTANCE = None

# ═══════════════════════════════════════════════════════════════════
# Background periodic tasks
# ═══════════════════════════════════════════════════════════════════

async def cleanup_admin_logs_periodically() -> None:
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
        "🧹 cleanup_admin_logs_periodically: بدء الحلقة (كل 24 ساعة)"
    )

    while True:
        try:
            db_type = getattr(DB, "DB_TYPE", "sqlite")
            deleted = 0

            async with DB.connection() as conn:
                if db_type == "postgres":
                    if _cleanup_admin_logs_pg is not None:
                        deleted = await _cleanup_admin_logs_pg(conn, logger)
                elif db_type == "mysql":
                    if _cleanup_admin_logs_mysql is not None:
                        deleted = await _cleanup_admin_logs_mysql(conn, logger)
                else:
                    if _cleanup_admin_logs_sqlite is not None:
                        deleted = await _cleanup_admin_logs_sqlite(conn, logger)

            if deleted:
                logger.info(
                    "✅ admin_logs cleanup: حُذف %d صف "
                    "(احتفاظ=%dd, حد أقصى=%d)",
                    deleted, ADMIN_LOGS_RETENTION_DAYS, ADMIN_LOGS_MAX_ROWS,
                )
            else:
                logger.debug("ℹ️ admin_logs cleanup: لا شيء للحذف")

        except asyncio.CancelledError:
            logger.info("🛑 cleanup_admin_logs أُلغيت")
            raise
        except Exception as e:
            logger.error(
                "❌ cleanup_admin_logs (سيُعاد بعد 24h): %s", e,
                exc_info=True,
            )

        try:
            await asyncio.sleep(86400)
        except asyncio.CancelledError:
            logger.info("🛑 cleanup_admin_logs أُلغيت")
            raise

async def cleanup_removed_channels_periodically() -> None:
    GRACE_DAYS = _REMOVED_CHANNELS_GRACE_DAYS

    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("🛑 cleanup_removed_channels: initial sleep أُلغي")
        raise

    logger.info(
        "🧹 cleanup_removed_channels_periodically: بدء الحلقة "
        "(كل 24 ساعة، فترة سماح=%d يوم)",
        GRACE_DAYS,
    )

    while True:
        try:
            deleted = 0

            if hasattr(DB, 'hard_delete_removed_channels_before'):
                cutoff_dt = TimeUtils.utc_now() - timedelta(days=GRACE_DAYS)
                deleted = await DB.hard_delete_removed_channels_before(
                    cutoff_dt
                )
            else:
                db_type = getattr(DB, "DB_TYPE", "sqlite")

                if db_type == "postgres":
                    sql = (
                        "DELETE FROM user_channels "
                        "WHERE removed_at IS NOT NULL "
                        "AND removed_at < NOW() - "
                        "INTERVAL '1 day' * $1"
                    )
                    result = await DB.execute(sql, (GRACE_DAYS,))
                elif db_type == "mysql":
                    sql = (
                        "DELETE FROM user_channels "
                        "WHERE removed_at IS NOT NULL "
                        "AND removed_at < UTC_TIMESTAMP() - "
                        "INTERVAL %s DAY"
                    )
                    result = await DB.execute(sql, (GRACE_DAYS,))
                else:
                    sql = (
                        "DELETE FROM user_channels "
                        "WHERE removed_at IS NOT NULL "
                        "AND julianday('now') - "
                        "julianday(removed_at) > ?"
                    )
                    result = await DB.execute(sql, (GRACE_DAYS,))

                if isinstance(result, int):
                    deleted = result

            if deleted:
                logger.info(
                    "✅ removed_channels cleanup: "
                    "حُذف نهائياً %d قناة مهجورة (بعد %d يوم من الإزالة)",
                    deleted, GRACE_DAYS,
                )
            else:
                logger.debug("ℹ️ removed_channels cleanup: لا شيء للحذف")

        except asyncio.CancelledError:
            logger.info("🛑 cleanup_removed_channels أُلغيت")
            raise
        except Exception as e:
            logger.error(
                "❌ cleanup_removed_channels (سيُعاد بعد 24h): %s", e,
                exc_info=True,
            )

        try:
            await asyncio.sleep(86400)
        except asyncio.CancelledError:
            logger.info("🛑 cleanup_removed_channels أُلغيت")
            raise

# ═══════════════════════════════════════════════════════════════════
# Payment helpers
# ═══════════════════════════════════════════════════════════════════

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
        logger.error("❌ DB.get_invoice failed: %s", e)
        return None, None, None

    if (
        not invoice
        or invoice.get('user_id') != user_id
        or invoice.get('status') != 'pending'
        or not invoice.get('number')
    ):
        logger.warning(
            "❌ Invoice invalid or not pending for user %s", user_id
        )
        return None, None, None

    payment_type = data.get('type')
    if payment_type not in ('subscription', 'gift'):
        logger.warning("❌ Unknown payment type: %s", payment_type)
        return None, None, None

    plan_id = data.get('plan_id') or data.get('gift_plan_id')

    try:
        if payment_type == 'subscription':
            plan = await DB.get_plan(plan_id)
        else:
            plan = await DB.get_gift_plan(plan_id)
    except Exception as e:
        logger.error("❌ DB.get_plan failed: %s", e)
        return None, None, None

    if not plan:
        logger.warning("❌ Plan not found: %s", plan_id)
        return None, None, None

    return invoice, plan, data

async def pre_checkout(update, context):
    query = update.pre_checkout_query
    user_id = query.from_user.id
    payload = query.invoice_payload

    invoice, plan, data = await _validate_invoice_for_payment(user_id, payload)

    if invoice is None or plan is None:
        logger.warning("❌ Pre-checkout rejected for user %s", user_id)
        try:
            await query.answer(
                ok=False,
                error_message="الفاتورة غير صالحة أو انتهت صلاحيتها."
            )
        except Exception as e:
            logger.error("❌ Failed to answer pre-checkout rejection: %s", e)
        return

    if hasattr(query, 'total_amount'):
        expected_amount = plan.get('price')
        if (
            expected_amount is not None
            and float(expected_amount or 0) > 0
            and not _amounts_match(expected_amount, query.total_amount)
        ):
            logger.warning(
                "❌ Amount mismatch for user %s: expected %s, got %s",
                user_id, expected_amount, query.total_amount,
            )
            try:
                await query.answer(
                    ok=False,
                    error_message="المبلغ غير مطابق لسعر الخطة."
                )
            except Exception as e:
                logger.error("❌ Failed to answer amount mismatch: %s", e)
            return

    try:
        await query.answer(ok=True)
        logger.info("✅ Pre-checkout success")
    except Exception as e:
        logger.error("❌ Failed to answer pre-checkout success: %s", e)

async def successful_payment(update, context):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    total_amount = payment.total_amount
    telegram_payment_charge_id = payment.telegram_payment_charge_id
    provider_payment_charge_id = payment.provider_payment_charge_id

    invoice, plan, data = await _validate_invoice_for_payment(user_id, payload)

    if invoice is None or plan is None:
        logger.error(
            "❌ Payment processing failed: invalid invoice for user %s",
            user_id,
        )
        await safe_send(context.bot, user_id, "❌ حدث خطأ في معالجة الدفع.")
        return

    plan_price = plan.get('price', 0)
    if float(plan_price or 0) > 0 and not _amounts_match(
        plan_price, total_amount,
    ):
        logger.error(
            "❌ Amount mismatch in successful payment for user %s", user_id
        )
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
                logger.info("✅ Subscription activated: user=%s", user_id)
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
                        f"👤 <b>الاسم:</b> "
                        f"{_html_escape(str(_fname or '—'))}\n"
                        f"🔗 <b>المعرف:</b> "
                        f"{_html_escape(_username_display)}\n"
                        f"🆔 <b>الرقم التعريفي:</b> "
                        f"<code>{user_id}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"💎 <b>الباقة:</b> {_plan_display}\n"
                        f"💰 <b>المبلغ:</b> {_price_display} ⭐\n"
                        f"📅 <b>الوقت:</b> {TimeUtils.mecca_iso()}",
                    )
                except Exception as _e:
                    logger.debug("spawn notify dev log: %s", _e)
            else:
                await safe_send(
                    context.bot, user_id, "❌ حدث خطأ في معالجة الدفع."
                )
                logger.error(
                    "❌ Failed to activate subscription for user %s", user_id
                )
        except Exception as e:
            logger.exception("❌ Exception in subscription payment: %s", e)
            await safe_send(context.bot, user_id, "❌ حدث خطأ غير متوقع.")

    elif payment_type == 'gift':
        try:
            paid = await DB.mark_invoice_paid(invoice['number'], payment_id)
            if not paid:
                logger.error(
                    "❌ mark_invoice_paid فشل: %s", invoice['number']
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
                    plan.get('duration_days') or plan.get('days') or 0
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
                    "✅ Gift code created: user=%s (code=%s...)",
                    user_id, code[:8],
                )
            else:
                logger.error(
                    "❌ create_gift_code فشل: user=%s invoice=%s",
                    user_id, invoice['number'],
                )
                await safe_send(
                    context.bot, user_id,
                    "⚠️ <b>تم توثيق الدفع لكن فشل توليد الكود</b>\n\n"
                    "يرجى التواصل مع الدعم لإصدار الكود يدوياً.\n"
                    f"رقم الفاتورة: <code>{invoice['number']}</code>",
                    parse_mode='HTML',
                )
        except Exception as e:
            logger.exception("❌ Exception in gift payment: %s", e)
            await safe_send(
                context.bot, user_id,
                "❌ حدث خطأ غير متوقع أثناء معالجة كود الهدية."
            )

# ═══════════════════════════════════════════════════════════════════
# Health check + keep-alive
# ═══════════════════════════════════════════════════════════════════

async def health_check(request):
    return web.Response(text="OK", status=200)

async def keep_alive():
    try:
        await asyncio.sleep(60)
    except asyncio.CancelledError:
        logger.info("🛑 keep_alive أُلغي (initial sleep)")
        raise

    url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("KEEP_ALIVE_URL")
    if not url:
        logger.info(
            "ℹ️ keep_alive: RENDER_EXTERNAL_URL غير موجود — معطّل"
        )
        return

    url = url.rstrip('/')
    health_url = f"{url}/health"

    logger.info("💓 keep_alive مُفعّل — Ping كل 5 دقائق")

    while True:
        try:
            await asyncio.sleep(300)
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(health_url) as response:
                    await response.read()
                    logger.debug("💓 Keep-alive: %s", response.status)
        except asyncio.CancelledError:
            logger.info("🛑 keep_alive تم إلغاؤه")
            raise
        except Exception as e:
            logger.debug("💓 keep-alive: %s", e)

# ═══════════════════════════════════════════════════════════════════
# Pool health monitor
# ═══════════════════════════════════════════════════════════════════

async def _dump_idle_tx_details() -> None:
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
            "🔍 idle-in-transaction details (%d اتصال عالق):",
            len(rows),
        )
        for r in rows:
            pid = r.get("pid")
            user = r.get("usename")
            app = r.get("application_name")
            age = r.get("seconds_in_state")
            snippet = (r.get("query_snippet") or "").replace("\n", " ")[:120]
            logger.error(
                "   • pid=%s user=%s app=%r age=%ss q=%r",
                pid, user, app, age, snippet,
            )
    except Exception as qe:
        logger.debug("_dump_idle_tx_details: %s", qe)

async def _fetch_pool_data(total: int, active: int) -> Optional[Dict[str, Any]]:
    try:
        if hasattr(DB, "get_pool_live"):
            _pd = await DB.get_pool_live()
            if (
                isinstance(_pd, dict)
                and _pd.get("available")
                and _pd.get("max_size")
            ):
                return _pd
    except Exception as _e:
        logger.debug("_fetch_pool_data: get_pool_live: %s", _e)

    try:
        if hasattr(DB, "get_pool_stats"):
            _pd = await DB.get_pool_stats()
            if (
                isinstance(_pd, dict)
                and _pd.get("type") in ("postgres", "mysql")
                and _pd.get("max_size")
            ):
                return {
                    "max_size": _pd.get("max_size"),
                    "current_size": _pd.get("current_size"),
                    "in_use": _pd.get("in_use"),
                }
    except Exception as _e:
        logger.debug("_fetch_pool_data: get_pool_stats: %s", _e)

    return None

async def pool_health_monitor() -> None:
    _task_start_mono = time.monotonic()
    _idle_tx_streak = 0
    _last_details_dump_mono = 0.0

    try:
        await asyncio.sleep(_PM_INITIAL_DELAY_SEC)
    except asyncio.CancelledError:
        logger.info("🛑 pool_health_monitor أُلغيت (قبل البدء)")
        raise

    while True:
        try:
            db_type = getattr(DB, "DB_TYPE", "sqlite")
            if db_type != "postgres":
                try:
                    await asyncio.sleep(1800)
                except asyncio.CancelledError:
                    logger.info("🛑 pool_health_monitor أُلغيت")
                    raise
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

            _pool_data = await _fetch_pool_data(total, active)

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
                        "pool_health_monitor: تطبيق pool_data: %s", _e
                    )

            util_pct = (pool_current / pool_max * 100) if pool_max else 0

            if idle_in_tx > 0:
                _idle_tx_streak += 1
            else:
                _idle_tx_streak = 0

            in_grace = (
                time.monotonic() - _task_start_mono
            ) < _PM_STARTUP_GRACE_SEC

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
                logger.error("🔴 pool CRITICAL: %s", msg)
                if idle_in_tx >= 1:
                    now_mono = time.monotonic()
                    if (
                        now_mono - _last_details_dump_mono
                        >= _PM_ALERT_COOLDOWN_SEC
                    ):
                        _last_details_dump_mono = now_mono
                        await _dump_idle_tx_details()
            elif level == "WARNING":
                logger.warning("⚠️ pool DIAG  : %s", msg)
            else:
                if _idle_tx_streak == 0:
                    logger.info("🟢 pool HEALTH: %s", msg)
                else:
                    logger.info("🟢 pool OK    : %s", msg)

        except asyncio.CancelledError:
            logger.info("🛑 pool_health_monitor أُلغيت")
            raise
        except Exception as e:
            logger.debug("pool_health_monitor: %s", e)

        try:
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            logger.info("🛑 pool_health_monitor أُلغيت")
            raise

# ═══════════════════════════════════════════════════════════════════
# Hostname/Port resolution
# ═══════════════════════════════════════════════════════════════════

def _resolve_hostname() -> Optional[str]:
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
    default_port = int(getattr(CONFIG, "WEB_PORT", 10000))
    raw = os.getenv("PORT")

    if raw is None or str(raw).strip() == "":
        return default_port

    try:
        port = int(str(raw).strip())
    except (TypeError, ValueError):
        logger.error(
            "❌ PORT غير صالح (%r) — استخدام %d", raw, default_port
        )
        return default_port

    if port < 1 or port > 65535:
        logger.error(
            "❌ PORT خارج النطاق (%d) — استخدام %d", port, default_port
        )
        return default_port

    return port

# ═══════════════════════════════════════════════════════════════════
# Webhook runner watcher
# ═══════════════════════════════════════════════════════════════════

async def _watch_runner(
    runner,
    shutdown_event: asyncio.Event,
    port: int,
) -> None:
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
                "— مراقبة انهيار Webhook معطّلة."
            )
            return

        logger.debug("✅ _watch_runner: بدء المراقبة")

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
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.get(health_url) as resp:
                            await resp.read()
                            if resp.status != 200:
                                raise RuntimeError(
                                    f"health status={resp.status}"
                                )
                    if probe_failures > 0:
                        probe_failures -= 1
                except asyncio.CancelledError:
                    raise
                except Exception as probe_e:
                    probe_failures += 1
                    logger.debug(
                        "_watch_runner: health probe فشل "
                        "(%d/%d): %s",
                        probe_failures, _WATCHER_MAX_PROBE_FAILURES,
                        probe_e,
                    )
                    if probe_failures >= _WATCHER_MAX_PROBE_FAILURES:
                        logger.error(
                            "❌ _watch_runner: خادم Webhook لا يستجيب "
                            "(%d مرات متتالية) — إيقاف البوت بلطف",
                            probe_failures,
                        )
                        shutdown_event.set()
                        return

                await asyncio.sleep(_WATCHER_INTERVAL)

            except asyncio.CancelledError:
                raise
            except Exception as _e:
                logger.debug("_watch_runner loop: %s", _e)
                await asyncio.sleep(_WATCHER_INTERVAL)

    except asyncio.CancelledError:
        raise
    except Exception as _e:
        logger.debug("_watch_runner: %s", _e)

# ═══════════════════════════════════════════════════════════════════
# run_task_with_retry
# ═══════════════════════════════════════════════════════════════════

async def run_task_with_retry(task_func, *args, task_name=""):
    consecutive_failures = 0
    while True:
        try:
            await task_func(*args)
            if consecutive_failures == 0:
                logger.warning(
                    "⚠️ المهمة %s عادت بدون استثناء — إعادة بعد 5s",
                    task_name,
                )
            consecutive_failures = 0
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("🛑 مهمة %s أُلغيت", task_name)
            raise
        except Exception as e:
            consecutive_failures += 1
            logger.error(
                "❌ Task %s crashed (x%d): %s",
                task_name, consecutive_failures, e,
                exc_info=True,
            )
            delay = min(5 * consecutive_failures, 60)
            logger.info(
                "🔄 إعادة تشغيل %s بعد %d ثانية...", task_name, delay
            )
            await asyncio.sleep(delay)

# ═══════════════════════════════════════════════════════════════════
# Local cleanup tasks
# ═══════════════════════════════════════════════════════════════════

async def cleanup_locks():
    while True:
        try:
            await DB.cleanup_user_locks(max_idle_seconds=3600)
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("❌ cleanup_locks failed: %s", e)
            await asyncio.sleep(60)

async def contest_cleanup(app: Application):
    try:
        await asyncio.sleep(300)
    except asyncio.CancelledError:
        raise

    while True:
        try:
            winners = await DB.auto_declare_expired_contests()

            if winners:
                logger.info(
                    "🏆 contest_cleanup: أُعلن %d فائزًا تلقائيًا",
                    len(winners),
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
                            f"لقد فزت في مسابقة <b>{title}</b>!\n\n"
                            f"<i>سيتم التواصل معك قريبًا لاستلام الجائزة.</i>"
                        )
                        await app.bot.send_message(
                            chat_id=winner_id,
                            text=msg,
                            parse_mode="HTML",
                        )
                    except Exception as ne:
                        logger.debug(
                            "إشعار الفائز %s فشل: %s", winner_id, ne
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
                "❌ contest_cleanup (سيُعاد بعد ساعة): %s", e,
                exc_info=True,
            )

        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise

# ═══════════════════════════════════════════════════════════════════
# Post-init / Post-stop hook helpers
# ═══════════════════════════════════════════════════════════════════

async def _run_post_init_hooks(app: Application) -> None:
    _post_init = getattr(app, "post_init", None)
    if _post_init is None:
        return

    if callable(_post_init):
        try:
            await _post_init(app)
        except Exception as _e:
            logger.warning("post_init hook failed: %s", _e)
    elif isinstance(_post_init, (list, tuple)):
        for hook in _post_init:
            if callable(hook):
                try:
                    await hook(app)
                except Exception as _e:
                    logger.warning("post_init hook failed: %s", _e)

async def _run_post_stop_hooks(app: Application) -> None:
    _post_stop = getattr(app, "post_stop", None)
    if _post_stop is None:
        return

    if callable(_post_stop):
        try:
            await _post_stop(app)
        except Exception as _e:
            logger.warning("post_stop hook failed: %s", _e)
    elif isinstance(_post_stop, (list, tuple)):
        for hook in _post_stop:
            if callable(hook):
                try:
                    await hook(app)
                except Exception as _e:
                    logger.warning("post_stop hook failed: %s", _e)

# ═══════════════════════════════════════════════════════════════════
# Polling mode helpers
# ═══════════════════════════════════════════════════════════════════

_polling_state = {
    "running": False,
}

async def _start_polling_mode(app: Application) -> None:
    if app.updater is None:
        raise RuntimeError(
            "Polling mode يتطلب updater — تأكد أن Application.builder() "
            "لم يستدعِ .updater(None)."
        )

    if _polling_state["running"]:
        raise RuntimeError("Application is already running!")

    if getattr(app, "running", False):
        raise RuntimeError("Application.running=True — تعارض حالة")

    _polling_state["running"] = True

    try:
        await app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=ALLOWED_UPDATES,
        )
    except Exception:
        _polling_state["running"] = False
        raise

    await _run_post_init_hooks(app)

async def _stop_polling_mode(app: Application) -> None:
    if not _polling_state["running"]:
        if app.updater is not None:
            try:
                if getattr(app.updater, "running", False):
                    await app.updater.stop()
            except Exception as _e:
                logger.debug("updater.stop (cleanup): %s", _e)
        return

    try:
        await _run_post_stop_hooks(app)
    finally:
        _polling_state["running"] = False

    if app.updater is not None:
        try:
            await app.updater.stop()
        except Exception as _e:
            logger.debug("updater.stop: %s", _e)

# ═══════════════════════════════════════════════════════════════════
# Diagnostic handler
# ═══════════════════════════════════════════════════════════════════

async def _diag_incoming(update, context):
    try:
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat:
            return
        if chat.type not in ("group", "supergroup"):
            return

        try:
            markup = getattr(msg, "reply_markup", None)
            rows = getattr(markup, "inline_keyboard", None) or []
            btn_count = sum(len(r or []) for r in rows)
        except Exception:
            btn_count = 0

        fwd_origin = getattr(msg, "forward_origin", None)
        fwd_chat = getattr(msg, "forward_from_chat", None)

        logger.warning(
            "📥 INCOMING | chat=%s msg=%s | "
            "text=%s caption=%s photo=%s video=%s doc=%s "
            "audio=%s voice=%s anim=%s sticker=%s vn=%s poll=%s | "
            "fwd_origin=%s fwd_chat=%s auto_fwd=%s | "
            "btn_count=%d",
            chat.id, msg.message_id,
            bool(getattr(msg, "text", None)),
            bool(getattr(msg, "caption", None)),
            bool(getattr(msg, "photo", None)),
            bool(getattr(msg, "video", None)),
            bool(getattr(msg, "document", None)),
            bool(getattr(msg, "audio", None)),
            bool(getattr(msg, "voice", None)),
            bool(getattr(msg, "animation", None)),
            bool(getattr(msg, "sticker", None)),
            bool(getattr(msg, "video_note", None)),
            bool(getattr(msg, "poll", None)),
            type(fwd_origin).__name__ if fwd_origin is not None else None,
            getattr(fwd_chat, "id", None) if fwd_chat is not None else None,
            bool(getattr(msg, "is_automatic_forward", False)),
            btn_count,
        )
    except Exception as _e:
        logger.debug("_diag_incoming error: %s", _e)

# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

async def main():
    t_start = time.monotonic()

    try:
        CONFIG.validate()
    except ValueError as e:
        logger.error("❌ %s", e)
        raise SystemExit(1)

    bot_token = _get_bot_token()
    if not bot_token:
        logger.error("❌ BOT_TOKEN غير محدّد (بيئة أو CONFIG.TOKEN)")
        raise SystemExit(1)

    logger.info("🌿 %s", CONFIG.BOT_NAME)
    logger.info("👨‍💼 المالك: %s", CONFIG.PRIMARY_OWNER_ID)

    logger.info(
        "📦 bot.py: v5.6.17 | "
        "detectors=%s | layers=%d | helpers=%s | "
        "db_idle=%s | cache_stats=%s | analytics=%s | maint_cmds=%s",
        _SPAM_DETECTOR_VERSION or "N/A",
        _SPAM_DETECTOR_LAYERS_COUNT,
        (
            ",".join([
                h for h, ok in (
                    ("install", _DETECTORS_HAS_INSTALL_HELPER),
                    ("shutdown", _DETECTORS_HAS_SHUTDOWN_HELPER),
                ) if ok
            ]) or "none"
        ),
        "yes" if _HAS_DB_IDLE_CMD else "no",
        "yes" if _HAS_CACHE_STATS_CMD else "no",
        "yes" if _ANALYTICS_HANDLERS_AVAILABLE else "no",
        "yes" if _MAINT_CMDS_AVAILABLE else "no",
    )

    try:
        if not CONFIG.SPAM_DETECTION_AVAILABLE:  # type: ignore
            logger.warning(
                "⚠️ محرك كشف السبام معطّل — "
                "TEXT_LAYER_ENABLED=0 في config.py"
            )
    except AttributeError:
        logger.info(
            "ℹ️ CONFIG.SPAM_DETECTION_AVAILABLE غير متاح "
            "(config.py v5 أو أقدم)"
        )

    if not _verify_command_handlers():
        logger.error("❌ فشل فحص دوال الأوامر — الخروج")
        raise SystemExit(1)

    if not _verify_db_config():
        logger.error("❌ فشل فحص إعدادات قاعدة البيانات — الخروج")
        raise SystemExit(1)

    _verify_group_log_handlers()
    _verify_membership_handler()

    t0 = time.monotonic()
    if hasattr(DB, 'pre_initialize'):
        await DB.pre_initialize()
    else:
        await initialize_db()
    logger.info(
        "⏱️ قاعدة البيانات تمت تهيئتها في %.2f ثانية",
        time.monotonic() - t0,
    )

    for dev_id in CONFIG.DEVELOPER_IDS:
        try:
            await DB.register_user(dev_id)
        except Exception as e:
            logger.error("❌ Failed to register developer %s: %s", dev_id, e)
    try:
        await DB.register_user(CONFIG.PRIMARY_OWNER_ID)
    except Exception as e:
        logger.error("❌ Failed to register owner: %s", e)

    t1 = time.monotonic()
    KeyboardFactory.load_config()
    available_langs = TranslationManager.get_available_languages()
    for lang in available_langs:
        TranslationManager.load_translation(lang)
    logger.info(
        "✅ تم تحميل %d لغة في %.2f ثانية",
        len(available_langs), time.monotonic() - t1,
    )

    t_warmup = time.monotonic()
    try:
        await warmup_all()
        logger.info(
            "⏱️ Warmup اكتمل في %.2f ثانية",
            time.monotonic() - t_warmup,
        )
    except Exception as e:
        logger.warning(
            "⚠️ Warmup فشل (سيتم المتابعة): %s", e, exc_info=True
        )

    port = _resolve_port()
    hostname = _resolve_hostname()

    t_app = time.monotonic()
    app = Application.builder().token(bot_token).build()
    app.bot_data['start_time'] = time.monotonic()
    await app.initialize()
    logger.info(
        "⏱️ تم تهيئة التطبيق في %.2f ثانية",
        time.monotonic() - t_app,
    )

    try:
        _register_message_shutdown(app)
        logger.info(
            "✅ handlers_message: shutdown handlers مُسجّلة "
            "(log dispatcher + delayed delete)"
        )
    except Exception as _e:
        logger.debug("register_message_shutdown: %s", _e)

    if _GROUP_LOG_INIT_AVAILABLE and _GROUP_LOG_AVAILABLE:
        _init_group_log_instance(app)
    else:
        if not _GROUP_LOG_INIT_AVAILABLE:
            logger.warning(
                "⚠️ group_log.init غير متاح — لن يعمل نظام سجل المجموعات"
            )
        elif not _GROUP_LOG_AVAILABLE:
            logger.warning(
                "⚠️ handlers_group_log غير متاح — لن يعمل سجل المجموعات"
            )

    for _scope_name, _scope in (
        ("Default", BotCommandScopeDefault()),
        ("AllPrivateChats", BotCommandScopeAllPrivateChats()),
        ("AllGroupChats", BotCommandScopeAllGroupChats()),
    ):
        try:
            await app.bot.delete_my_commands(scope=_scope)
            logger.debug("🧹 حُذفت أوامر %s القديمة", _scope_name)
        except Exception as _e:
            logger.debug("delete %s commands: %s", _scope_name, _e)

    try:
        await app.bot.set_my_commands(
            PUBLIC_COMMANDS,
            scope=BotCommandScopeAllPrivateChats(),
        )
        logger.info(
            "✅ سُجِّلت %d أمراً عاماً (AllPrivateChats)",
            len(PUBLIC_COMMANDS),
        )
    except Exception as _e:
        logger.error("❌ فشل تسجيل الأوامر العامة: %s", _e)

    try:
        await app.bot.set_my_commands(
            GROUP_COMMANDS,
            scope=BotCommandScopeAllGroupChats(),
        )
        logger.info(
            "✅ سُجِّلت %d أمراً للمجموعات (AllGroupChats)",
            len(GROUP_COMMANDS),
        )
    except Exception as _e:
        logger.error("❌ فشل تسجيل أوامر المجموعات: %s", _e)

    _admin_ids = await _collect_admin_ids()
    _registered_admins = 0
    _failed_admins = 0
    _admin_full_list = PUBLIC_COMMANDS + ADMIN_COMMANDS

    logger.info("👥 عدد الأدمن المُكتشفين: %d", len(_admin_ids))

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
                "⚠️ فشل تسجيل أوامر الأدمن %s: %s", _admin_id, _e
            )

    logger.info(
        "✅ الأوامر الإدارية: %d أمراً | سُجِّلت لـ %d/%d أدمن (فشل %d)",
        len(ADMIN_COMMANDS), _registered_admins,
        len(_admin_ids), _failed_admins,
    )

    if _DIAG_INCOMING and _HAS_TYPE_HANDLER:
        try:
            app.add_handler(
                TypeHandler(object, _diag_incoming),
                group=-100,
            )
            logger.warning(
                "🔔 DIAG_INCOMING=1 — TypeHandler تشخيصي مُسجّل "
                "(group=-100). سيُطبع كل رسالة واردة للمجموعة."
            )
        except Exception as _e:
            logger.error("❌ فشل تسجيل DIAG handler: %s", _e)
    elif _DIAG_INCOMING and not _HAS_TYPE_HANDLER:
        logger.warning(
            "⚠️ DIAG_INCOMING=1 لكن TypeHandler غير متاح في هذا الإصدار"
        )

    _group_msg_filter = (
        filters.ChatType.GROUPS
        & filters.UpdateType.MESSAGE
        & ~filters.COMMAND
    )

    try:
        app.add_handler(
            MessageHandler(_group_msg_filter, MessageHandlers.handle_group),
            group=-1,
        )
        logger.info(
            "✅ handle_group مُسجَّل في group=-1 "
            "(فلتر شامل — كل الأنواع، رسائل جديدة فقط)"
        )
    except Exception as _e:
        logger.error("❌ فشل تسجيل handle_group: %s", _e, exc_info=True)

    if hasattr(MessageHandlers, "handle_edited"):
        try:
            app.add_handler(
                MessageHandler(
                    filters.ChatType.GROUPS
                    & filters.UpdateType.EDITED_MESSAGE,
                    MessageHandlers.handle_edited,
                ),
                group=-1,
            )
            logger.info(
                "✅ handle_edited مُسجَّل في group=-1 "
                "(رسائل معدّلة فقط)"
            )
        except Exception as _e:
            logger.error(
                "❌ فشل تسجيل handle_edited: %s", _e, exc_info=True
            )
    else:
        logger.warning(
            "⚠️ MessageHandlers.handle_edited مفقود — "
            "تعديل الرسائل لن يُفحص! حدّث handlers_message.py إلى v7.15.1+"
        )

    try:
        app.add_handler(
            MessageHandler(
                filters.StatusUpdate.ALL & filters.ChatType.GROUPS,
                MessageHandlers.handle_service,
            ),
            group=-1,
        )
        logger.info("✅ handle_service مُسجَّل في group=-1")
    except Exception as _e:
        logger.error("❌ فشل تسجيل handle_service: %s", _e, exc_info=True)

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

    try:
        app.add_handler(CommandHandler(
            "autoblocked", _handle_autoblocked_command
        ))
        logger.info(
            "✅ /autoblocked مُسجَّل — إدارة المصادر المحجوبة تلقائياً"
        )
    except Exception as _e:
        logger.warning("⚠️ فشل تسجيل /autoblocked: %s", _e)

    if _HAS_DB_IDLE_CMD and _handle_db_idle_command is not None:
        try:
            app.add_handler(CommandHandler(
                "db_idle", _handle_db_idle_command
            ))
            logger.info(
                "✅ /db_idle مُسجَّل — تدقيق idle-in-transaction"
            )
        except Exception as _e:
            logger.warning("⚠️ فشل تسجيل /db_idle: %s", _e)
    else:
        logger.debug(
            "ℹ️ /db_idle غير مُسجَّل — "
            "يتطلب handlers_message v7.18.14+"
        )

    if _HAS_CACHE_STATS_CMD and _handle_cache_stats_command is not None:
        try:
            app.add_handler(CommandHandler(
                "cache_stats", _handle_cache_stats_command
            ))
            logger.info(
                "✅ /cache_stats مُسجَّل — إحصائيات الكاش (للمطور فقط)"
            )
        except Exception as _e:
            logger.warning("⚠️ فشل تسجيل /cache_stats: %s", _e)
    else:
        logger.debug(
            "ℹ️ /cache_stats غير مُسجَّل — "
            "يتطلب handlers_message v7.18.18+"
        )

    if hasattr(MessageHandlers, "handle_cancel"):
        try:
            app.add_handler(
                CommandHandler("cancel", MessageHandlers.handle_cancel),
                group=1,
            )
            logger.info(
                "✅ /cancel مُسجَّل — إلغاء العمليات المنتظرة"
            )
        except Exception as _e:
            logger.warning("⚠️ فشل تسجيل /cancel: %s", _e)
    else:
        logger.debug(
            "ℹ️ MessageHandlers.handle_cancel غير متاح — "
            "/cancel لن يعمل"
        )

    # ═══════════════════════════════════════════════════════════════
    # 🆕 v5.6.17: db_maintenance_commands — استدعاء محسّن
    # ═══════════════════════════════════════════════════════════════
    if _MAINT_CMDS_AVAILABLE and callable(register_maintenance_commands):
        try:
            if register_maintenance_commands(app):
                logger.info(
                    "✅ db_maintenance_commands: "
                    "الأوامر الثلاثة مُسجَّلة"
                )
            else:
                logger.warning(
                    "⚠️ بعض أوامر الصيانة فشلت في التسجيل"
                )
        except Exception as _e:
            logger.error(
                "❌ فشل تسجيل db_maintenance_commands: %s", _e,
                exc_info=True,
            )
    else:
        logger.warning(
            "⚠️ db_maintenance_commands غير متاح: %s",
            _MAINT_CMDS_IMPORT_ERROR or "unknown",
        )

    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))

    try:
        register_nav_fix(app)
        logger.info("✅ NAV_FIX: معالج الإغلاق/الرجوع مُسجّل")
    except Exception as e:
        logger.error("❌ فشل تسجيل NAV_FIX: %s", e, exc_info=True)

    try:
        register_channels_list_handlers(app)
        logger.info("✅ handlers قائمة القنوات مُسجَّل")
    except Exception as e:
        logger.error(
            "❌ فشل تسجيل handlers القنوات: %s", e, exc_info=True
        )

    if _CH_DELETE_AVAILABLE and callable(register_delete_confirmation):
        try:
            register_delete_confirmation(app)
            logger.info(
                "✅ handlers_channels_delete مُسجَّل — "
                "تأكيد حذف القنوات مُفعّل"
            )
        except Exception as _e:
            logger.error(
                "❌ فشل تسجيل handlers_channels_delete: %s", _e,
                exc_info=True,
            )
    else:
        logger.warning(
            "⚠️ handlers_channels_delete غير متاح — "
            "سيتم استخدام الحذف الفوري (بدون تأكيد): %s",
            _CH_DELETE_IMPORT_ERROR or "unknown",
        )

    if _GROUP_LOG_AVAILABLE:
        try:
            register_group_log_handlers(app)
            logger.info(
                "✅ group_log: معالجات سجل قناة المجموعات مُسجّلة"
            )
        except Exception as e:
            logger.error("❌ فشل تسجيل group_log: %s", e, exc_info=True)
    else:
        logger.warning("⚠️ group_log غير متاح — زر قناة السجل لن يعمل")

    # handlers_analytics BEFORE العام
    if _ANALYTICS_HANDLERS_AVAILABLE and \
       _show_analytics_menu is not None and \
       _handle_analytics_callback is not None:
        try:
            app.add_handler(CallbackQueryHandler(
                _show_analytics_menu,
                pattern=r"^admin_analytics$",
            ))
            app.add_handler(CallbackQueryHandler(
                _handle_analytics_callback,
                pattern=(
                    r"^(growth_30d_btn|top_channels_btn|publish_stats_btn|"
                    r"channels_rate_btn|subscriptions_btn|pool_live_btn|"
                    r"slow_queries_btn|export_excel_btn|refresh_btn)$"
                ),
            ))
            logger.info(
                "✅ handlers_analytics: 10 معالج مسجّل "
                "(admin_analytics + 9 أزرار التقرير)"
            )
        except Exception as _e:
            logger.error(
                "❌ فشل تسجيل handlers_analytics: %s", _e,
                exc_info=True,
            )
    else:
        logger.warning(
            "⚠️ handlers_analytics غير متاح — "
            "أزرار التحليلات لن تعمل: %s",
            _ANALYTICS_HANDLERS_IMPORT_ERROR or "unknown",
        )

    app.add_handler(CallbackQueryHandler(CallbackHandlers.handle))

    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL |
         filters.AUDIO | filters.VOICE | filters.ANIMATION | filters.Sticker.ALL |
         filters.VIDEO_NOTE) &
        filters.ChatType.PRIVATE & ~filters.COMMAND,
        MessageHandlers.handle_private
    ))

    app.add_handler(ChatJoinRequestHandler(MessageHandlers.handle_join_request))
    app.add_error_handler(ErrorHandler.handle_error)

    try:
        chat_member.register(app)
        logger.info("✅ ChatMemberHandler مُفعّل — تحديث المشرفين فوري")
    except Exception as _e:
        logger.error(
            "❌ فشل تسجيل ChatMemberHandler: %s — "
            "تحديثات المشرفين لن تكون فورية",
            _e,
            exc_info=True,
        )

    if _MEMBERSHIP_AVAILABLE and callable(register_membership_handlers):
        try:
            register_membership_handlers(app)
            _source_label = (
                "standalone (FIX-1/FIX-3)"
                if _MEMBERSHIP_SOURCE == 'standalone'
                else "embedded"
            )
            logger.info(
                "✅ MembershipHandler مُفعّل [%s] — "
                "تقارير إضافة البوت جاهزة",
                _source_label,
            )
        except Exception as _e:
            logger.error(
                "❌ فشل تسجيل MembershipHandler: %s", _e, exc_info=True
            )
    else:
        logger.warning(
            "⚠️ MembershipHandler غير متاح — "
            "لن تُرسل تقارير إضافة البوت: %s",
            _MEMBERSHIP_IMPORT_ERROR or "unknown",
        )

    tasks: List[asyncio.Task] = []

    _bg_task_specs: List[Tuple[str, Any, tuple]] = [
        ("keep_alive", keep_alive, ()),
        ("auto_publish", BackgroundTasks.auto_publish, (app.bot,)),
        ("auto_backup", BackgroundTasks.auto_backup, ()),
        ("reminders", BackgroundTasks.reminders, (app.bot,)),
        ("heartbeat", BackgroundTasks.heartbeat, (app.bot,)),
        ("flush_usage", BackgroundTasks.flush_usage_periodically, ()),
        ("expire_subscriptions", BackgroundTasks.expire_subscriptions, ()),
        ("sync_admins", BackgroundTasks.sync_admins_periodically, (app.bot,)),
        ("expire_penalties", BackgroundTasks.expire_penalties_periodically, ()),
        ("cleanup_old_data", BackgroundTasks.cleanup_old_data, ()),
        ("cache_cleanup", cache_cleanup_task, ()),
        ("cleanup_locks", cleanup_locks, ()),
        ("periodic_cleanup", GroupRateLimiterManager.periodic_cleanup_task, ()),
        ("monitor_pool_alert", BackgroundTasks.monitor_pool_alert, (app.bot,)),
        ("contest_cleanup", contest_cleanup, (app,)),
        ("pool_health_monitor", pool_health_monitor, ()),
        ("admin_logs_cleanup", cleanup_admin_logs_periodically, ()),
        ("removed_channels_cleanup",
         cleanup_removed_channels_periodically, ()),
    ]

    for _name, _fn, _args in _bg_task_specs:
        tasks.append(asyncio.create_task(
            run_task_with_retry(_fn, *_args, task_name=_name)
        ))

    if _MAINTENANCE_AVAILABLE and callable(_maintenance_loop):
        try:
            owner_id = int(CONFIG.PRIMARY_OWNER_ID)
        except (TypeError, ValueError):
            owner_id = None
            logger.warning(
                "⚠️ PRIMARY_OWNER_ID غير صالح — لن يُرسل تقرير الصيانة"
            )

        tasks.append(asyncio.create_task(
            run_task_with_retry(
                _maintenance_loop, app.bot, owner_id,
                task_name="maintenance",
            )
        ))
        logger.info(
            "✅ maintenance: مهمة الصيانة الدورية مُضافة (كل 24 ساعة)"
        )
    else:
        logger.warning(
            "⚠️ maintenance غير متاح — الصيانة التلقائية معطّلة: %s",
            _MAINTENANCE_IMPORT_ERROR or "module missing",
        )

    if _MAINT_CMDS_AVAILABLE and callable(start_weekly_diagnostic_task):
        try:
            if start_weekly_diagnostic_task(app):
                logger.info(
                    "✅ weekly diagnostic task بدأت "
                    "(تُرسل التقرير كل 7 أيام إن كان مُفعّلاً)"
                )
            else:
                logger.warning(
                    "⚠️ start_weekly_diagnostic_task أعادت False"
                )
        except Exception as _e:
            logger.error(
                "❌ فشل بدء weekly diagnostic: %s", _e, exc_info=True
            )

    logger.info("✅ تم تشغيل %d مهمة خلفية", len(tasks))
    if _ADMIN_LOGS_CLEANUP_AVAILABLE:
        logger.info(
            "🧹 admin_logs cleanup مُفعّل — كل 24 ساعة "
            "(احتفاظ=%dd, حد أقصى=%d صف)",
            ADMIN_LOGS_RETENTION_DAYS, ADMIN_LOGS_MAX_ROWS,
        )
    logger.info(
        "🧹 removed_channels cleanup مُفعّل — كل 24 ساعة "
        "(فترة سماح=%d يوم)",
        _REMOVED_CHANNELS_GRACE_DAYS,
    )

    _shutdown_event = asyncio.Event()

    def _on_shutdown_signal(sig_name: str):
        logger.info("🛑 تلقّيت %s — بدء الإغلاق اللطيف", sig_name)
        _shutdown_event.set()

    try:
        _loop = asyncio.get_running_loop()
        _signals_to_install = [signal.SIGTERM, signal.SIGINT]
        if hasattr(signal, "SIGHUP"):
            _signals_to_install.append(signal.SIGHUP)

        for _sig in _signals_to_install:
            try:
                _loop.add_signal_handler(
                    _sig,
                    lambda s=_sig: _on_shutdown_signal(s.name),
                )
                logger.debug("✅ handler لـ %s مسجّل", _sig.name)
            except (NotImplementedError, RuntimeError, ValueError) as _e:
                logger.debug(
                    "add_signal_handler(%s) غير مدعوم: %s", _sig.name, _e
                )
    except Exception as _e:
        logger.debug("Signal setup: %s", _e)

    app_shutdown_done = False

    try:
        if hostname:
            webhook_url = f"https://{hostname}/{bot_token}"
            logger.info("🔗 Webhook: %s", _safe_url(webhook_url))

            await app.bot.delete_webhook(drop_pending_updates=True)
            await app.bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True,
                allowed_updates=ALLOWED_UPDATES,
                secret_token=(
                    getattr(CONFIG, "WEBHOOK_SECRET", "") or None
                ),
            )
            logger.info("✅ Webhook تم التعيين")

            runner = await setup_webhook(app, port)

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        await resp.read()
                logger.info("🔥 تم تسخين الخادم بنجاح")
            except Exception as _e:
                logger.debug("تسخين الخادم: %s", _e)

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
                        logger.debug("watcher_task: %s", _e)

                try:
                    await runner.cleanup()
                    logger.info(
                        "✅ aiohttp runner: تم الإغلاق النظيف"
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as _e:
                    logger.debug("runner.cleanup (webhook): %s", _e)

        else:
            logger.info(
                "⚠️ وضع Polling (لا يوجد hostname) — "
                "باستخدام start_polling() + محاكاة app.start()"
            )

            runner = await setup_webhook(app, port)

            try:
                await _start_polling_mode(app)
                logger.info(
                    "✅ Polling started — في انتظار الإشارات"
                )

                await _shutdown_event.wait()
                logger.info(
                    "📴 تم استلام إشارة الإغلاق — إنهاء الخدمات..."
                )

            finally:
                try:
                    await _stop_polling_mode(app)
                    logger.info("✅ polling mode: تم الإيقاف")
                except Exception as _e:
                    logger.debug("_stop_polling_mode: %s", _e)

                try:
                    await runner.cleanup()
                    logger.info(
                        "✅ aiohttp runner: تم الإغلاق النظيف (polling)"
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as _e:
                    logger.debug("runner.cleanup (polling): %s", _e)

    finally:
        try:
            await _shutdown_group_log()
        except asyncio.CancelledError:
            raise
        except Exception as _e:
            logger.debug("_shutdown_group_log: %s", _e)

        if _NOTIFY_TASKS:
            logger.info(
                "⏳ انتظار %d مهمة إشعار (بحد أقصى %.1fs)...",
                len(_NOTIFY_TASKS), _NOTIFY_SHUTDOWN_TIMEOUT,
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
            if not t.done():
                t.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=_BG_TASKS_SHUTDOWN_TIMEOUT,
            )
            logger.info("✅ background tasks: أُلغيت بشكل نظيف")
        except asyncio.TimeoutError:
            remaining = sum(1 for t in tasks if not t.done())
            logger.warning(
                "⚠️ %d مهمة خلفية لم تنته خلال %.1fs — استمرار الإغلاق",
                remaining, _BG_TASKS_SHUTDOWN_TIMEOUT,
            )
        except asyncio.CancelledError:
            raise

        if _MAINT_CMDS_AVAILABLE and callable(stop_weekly_diagnostic_task):
            try:
                await stop_weekly_diagnostic_task(timeout=3.0)
            except Exception as _e:
                logger.debug("stop_weekly_diagnostic_task: %s", _e)

        try:
            await _shutdown_detector_tasks(timeout=3.0)
        except Exception as _e:
            logger.debug("_shutdown_detector_tasks: %s", _e)

        try:
            await _shutdown_log_dispatcher(timeout=5.0)
        except Exception as _e:
            logger.debug("shutdown_log_dispatcher (bot): %s", _e)
        try:
            await _shutdown_delete_tasks(timeout=3.0)
        except Exception as _e:
            logger.debug("shutdown_delete_tasks (bot): %s", _e)

        if not app_shutdown_done:
            try:
                await app.shutdown()
                app_shutdown_done = True
                logger.info("✅ app.shutdown() اكتمل")
            except asyncio.CancelledError:
                raise
            except Exception as _e:
                logger.debug("app.shutdown: %s", _e)

    logger.info(
        "👋 انتهت دورة حياة البوت (%.2fs)",
        time.monotonic() - t_start,
    )

# ═══════════════════════════════════════════════════════════════════
# Entrypoint
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    _loop = None
    try:
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)

        if _DETECTORS_HAS_INSTALL_HELPER:
            try:
                _install_default_executor_fn(_loop)
                logger.info(
                    "✅ detectors pool: installed as default executor"
                )
            except Exception as _e:
                logger.warning(
                    "⚠️ install_default_executor failed: %s", _e,
                )
        else:
            logger.debug(
                "install_default_executor غير متاح "
                "(detectors أقدم من v4.0.8)"
            )

        _loop.run_until_complete(main())

    except KeyboardInterrupt:
        logger.info("\n👋 تم الإيقاف")
    except Exception as e:
        logger.error("❌ خطأ: %s", e)
        traceback.print_exc()
    finally:
        if _loop is not None:
            try:
                try:
                    pending = asyncio.all_tasks(_loop)
                except Exception:
                    pending = set()

                try:
                    _current = asyncio.current_task(loop=_loop)
                    pending = {t for t in pending if t is not _current}
                except Exception:
                    pass

                if pending:
                    logger.info(
                        "⏳ إلغاء %d مهمة معلّقة قبل إغلاق الحلقة...",
                        len(pending),
                    )
                    for _t in pending:
                        _t.cancel()
                    try:
                        _loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    except Exception as _e:
                        logger.debug("gather pending: %s", _e)

                try:
                    if _DETECTORS_HAS_SHUTDOWN_HELPER:
                        _loop.run_until_complete(
                            _shutdown_default_executor_fn(_loop)
                        )
                        logger.info(
                            "✅ detectors: default executor shutdown"
                        )
                    elif callable(_shutdown_detector_pool_fn):
                        _shutdown_detector_pool_fn()
                        logger.info(
                            "✅ detectors: shared pool shutdown (fallback)"
                        )
                except Exception as _e:
                    logger.debug("shutdown_default_executor: %s", _e)

                try:
                    _loop.run_until_complete(_loop.shutdown_asyncgens())
                except Exception:
                    pass

                try:
                    _loop.close()
                    logger.info("✅ event loop closed")
                except Exception as _e:
                    logger.debug("loop.close: %s", _e)
            except Exception as _e:
                logger.debug("loop cleanup: %s", _e)