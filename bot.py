#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌿 Relax Manager – البوت الرئيسي (bot.py v5.7.6-KILL-PREVIOUS)
================================================================================
📌 نقطة الدخول الرسمية للتطبيق (entrypoint).

🆕 v5.7.6 (KILL-PREVIOUS-INSTANCE):
    🔴 FORCE-KILL-1: _force_kill_previous_instance() — يقتل نسخة البوت القديمة.
        • PID file في /app/.bot.pid
        • /proc scan لاكتشاف كل عمليات bot.py
        • SIGTERM → 5s → SIGKILL
    🔴 FORCE-KILL-2: _wait_for_telegram_release() — ينتظر تحرر token من Telegram
        (يمنع Conflict من النسخة القديمة أثناء الموت).
    🔴 FORCE-KILL-3: _FALLBACK_HOSTNAME — يضمن webhook دائماً على Render
        (لا polling = لا Conflict أبداً).
    🔴 FORCE-KILL-4: _start_polling_mode محسّن — 12 محاولة + backoff تصاعدي.
    🟢 FORCE-KILL-5: beacon محدّث — v5.7.6 + kill_prev=on.

🆕 v5.7.5 (GIL-QUIET-WARMUP):
    🟢 _GIL_LAG_WARN_MS: 50 → 1000ms.
    🟢 _GIL_LAG_ALERT_INTERVAL_SEC: 5 → 30s.
    🟢 _HANDLER_SLOW_WARN_MS: 2000 → 3000ms.
    🟢 _HANDLER_INFO_MS: 1500ms.
    🟢 _wrap_handler_with_timing: + stack hint.
    🟢 _gil_lag_monitor: + memory + tasks + gc.
    🟢 warmup_detectors_pool: blocking + gc.collect().

🆕 v5.7.4 (GIL-DIAGNOSTICS): محفوظ بالكامل.
🆕 v5.7.3 (AUTOTUNE-INTEGRATION): محفوظ بالكامل.
🆕 v5.7.2 (FIX-ACTIVE-CHANNELS-SCOPE): محفوظ بالكامل.
🆕 v5.7.1 (STATS-CHANNELS-FIX): محفوظ بالكامل.
🆕 v5.7.0 (MANAGED-BOTS-INTEGRATION): محفوظ بالكامل.
================================================================================
"""

import asyncio
import os
import logging
import traceback
import json
import signal
import sys
import time
import aiohttp
import functools
from datetime import datetime, timedelta, timezone
from html import escape as _html_escape
from urllib.parse import urlparse
from typing import Set, Any, Dict, Optional, List, Tuple, Callable, Awaitable
from aiohttp import web

# ═══════════════════════════════════════════════════════════════════
# 🔴 v5.6.43 FIX-RECORD-METRIC-MODULE-EARLY (CRITICAL)
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    _existing_bot = sys.modules.get('bot')
    _main_mod = sys.modules.get('__main__')
    if _main_mod is None:
        print(
            "🔴 FIX-RECORD-METRIC-MODULE: __main__ not in sys.modules — "
            "cannot establish 'bot' alias.",
            file=sys.stderr,
        )
    elif _existing_bot is None:
        sys.modules['bot'] = _main_mod
        print(
            "🔗 FIX-RECORD-METRIC-MODULE: sys.modules['bot'] = __main__",
            file=sys.stderr,
        )

from telegram import (
    BotCommandScopeAllPrivateChats,
    BotCommandScopeAllGroupChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

try:
    from telegram import ReplyParameters
    _HAS_REPLY_PARAMETERS = True
except ImportError:
    ReplyParameters = None
    _HAS_REPLY_PARAMETERS = False

from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatJoinRequestHandler, filters,
    PreCheckoutQueryHandler,
)

try:
    from telegram.request import HTTPXRequest
    _HAS_HTTPX_REQUEST = True
except ImportError:
    HTTPXRequest = None
    _HAS_HTTPX_REQUEST = False

try:
    from telegram.ext import TypeHandler
    _HAS_TYPE_HANDLER = True
except ImportError:
    TypeHandler = None
    _HAS_TYPE_HANDLER = False

_DB_DIAG_AVAILABLE = False
_DB_DIAG_VERSION = None
_MARK_PROCESS_START_FN = None
_DB_DIAG_IMPORT_ERROR = None

try:
    import db_diagnostics as _db_diag_mod
    _DB_DIAG_AVAILABLE = True
    _DB_DIAG_VERSION = getattr(_db_diag_mod, "VERSION", "unknown")
    _MARK_PROCESS_START_FN = getattr(
        _db_diag_mod, "mark_process_start", None,
    )
    if not callable(_MARK_PROCESS_START_FN):
        _MARK_PROCESS_START_FN = None
except ImportError as _e_dbdiag:
    _DB_DIAG_IMPORT_ERROR = str(_e_dbdiag)
except Exception as _e_dbdiag:
    _DB_DIAG_IMPORT_ERROR = f"unexpected: {_e_dbdiag}"

_AUTOTUNE_AVAILABLE = False
try:
    from db_diagnostics import ensure_autovacuum_tuning as _fn_autotune
    _AUTOTUNE_AVAILABLE = callable(_fn_autotune)
except ImportError:
    _fn_autotune = None
    _AUTOTUNE_AVAILABLE = False
except Exception:
    _fn_autotune = None
    _AUTOTUNE_AVAILABLE = False

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
# handlers_analytics
# ═════════════════════════════════════════════════════════════════════
_ANALYTICS_HANDLERS_AVAILABLE = False
_ANALYTICS_HANDLERS_IMPORT_ERROR = None
_handle_analytics_callback = None
_show_analytics_menu = None
_cmd_fullhealth = None
_cmd_latency = None
_register_analytics_handlers = None
_ANALYTICS_REGISTER_AVAILABLE = False

try:
    from handlers.handlers_analytics import (
        handle_analytics_callback as _handle_analytics_callback,
        show_analytics_menu as _show_analytics_menu,
        cmd_fullhealth as _cmd_fullhealth_imported,
        cmd_latency as _cmd_latency_imported,
    )
    _cmd_fullhealth = _cmd_fullhealth_imported
    _cmd_latency = _cmd_latency_imported
    _ANALYTICS_HANDLERS_AVAILABLE = True
except ImportError as _e_an1:
    try:
        from handlers_analytics import (
            handle_analytics_callback as _handle_analytics_callback,
            show_analytics_menu as _show_analytics_menu,
            cmd_fullhealth as _cmd_fullhealth_imported,
            cmd_latency as _cmd_latency_imported,
        )
        _cmd_fullhealth = _cmd_fullhealth_imported
        _cmd_latency = _cmd_latency_imported
        _ANALYTICS_HANDLERS_AVAILABLE = True
    except ImportError as _e_an2:
        try:
            from handlers.handlers_analytics import (
                handle_analytics_callback as _handle_analytics_callback,
                show_analytics_menu as _show_analytics_menu,
            )
            _ANALYTICS_HANDLERS_AVAILABLE = True
            _cmd_fullhealth = None
            _cmd_latency = None
            _ANALYTICS_HANDLERS_IMPORT_ERROR = (
                f"handlers_analytics محمّل لكن cmd_fullhealth/cmd_latency "
                f"مفقودة. {_e_an1} | {_e_an2}"
            )
        except ImportError as _e_an3:
            _handle_analytics_callback = None
            _show_analytics_menu = None
            _cmd_fullhealth = None
            _cmd_latency = None
            _ANALYTICS_HANDLERS_AVAILABLE = False
            _ANALYTICS_HANDLERS_IMPORT_ERROR = (
                f"{_e_an1} | {_e_an2} | {_e_an3}"
            )

try:
    from handlers.handlers_analytics import (
        register_handlers as _register_analytics_handlers_imported,
    )
    if callable(_register_analytics_handlers_imported):
        _register_analytics_handlers = _register_analytics_handlers_imported
        _ANALYTICS_REGISTER_AVAILABLE = True
except ImportError:
    try:
        from handlers_analytics import (
            register_handlers as _register_analytics_handlers_imported,
        )
        if callable(_register_analytics_handlers_imported):
            _register_analytics_handlers = _register_analytics_handlers_imported
            _ANALYTICS_REGISTER_AVAILABLE = True
    except ImportError:
        _register_analytics_handlers = None
        _ANALYTICS_REGISTER_AVAILABLE = False
except Exception:
    _register_analytics_handlers = None
    _ANALYTICS_REGISTER_AVAILABLE = False

# ═════════════════════════════════════════════════════════════════════
# Spam detector
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
    except Exception:
        pass

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
    except Exception:
        pass

# ═════════════════════════════════════════════════════════════════════
# Security Bridge
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

try:
    from handlers.handlers_nav_fix import register_nav_fix
    _NAV_FIX_AVAILABLE = True
except ImportError:
    try:
        from handlers_nav_fix import register_nav_fix
        _NAV_FIX_AVAILABLE = True
    except ImportError:
        register_nav_fix = None
        _NAV_FIX_AVAILABLE = False

from handlers.handlers_message import (
    GroupRateLimiterManager,
    register_shutdown_handlers as _register_message_shutdown,
    shutdown_log_dispatcher as _shutdown_log_dispatcher,
    shutdown_delete_tasks as _shutdown_delete_tasks,
    handle_autoblocked_command as _handle_autoblocked_command,
)

# ═════════════════════════════════════════════════════════════════════
# warmup_detectors_pool
# ═════════════════════════════════════════════════════════════════════
_warmup_detectors_pool_fn = None
_HAS_WARMUP_DETECTORS = False
_WARMUP_DETECTORS_IMPORT_ERROR = None

try:
    from handlers.handlers_message import (
        warmup_detectors_pool as _warmup_detectors_pool_fn_imported,
    )
    if callable(_warmup_detectors_pool_fn_imported):
        _warmup_detectors_pool_fn = _warmup_detectors_pool_fn_imported
        _HAS_WARMUP_DETECTORS = True
    else:
        _WARMUP_DETECTORS_IMPORT_ERROR = "not callable"
except ImportError as _e_wd1:
    try:
        from handlers_message import (
            warmup_detectors_pool as _warmup_detectors_pool_fn_imported,
        )
        if callable(_warmup_detectors_pool_fn_imported):
            _warmup_detectors_pool_fn = _warmup_detectors_pool_fn_imported
            _HAS_WARMUP_DETECTORS = True
        else:
            _WARMUP_DETECTORS_IMPORT_ERROR = "not callable"
    except ImportError as _e_wd2:
        _WARMUP_DETECTORS_IMPORT_ERROR = f"{_e_wd1} | {_e_wd2}"
        _warmup_detectors_pool_fn = None
        _HAS_WARMUP_DETECTORS = False

# ═════════════════════════════════════════════════════════════════════
# /db_idle + /cache_stats
# ═════════════════════════════════════════════════════════════════════
_HAS_DB_IDLE_CMD = False
_handle_db_idle_command = None
_DB_IDLE_IMPORT_ERROR = None

try:
    from handlers.handlers_message import (
        handle_db_idle_command as _handle_db_idle_command_imported,
    )
    _handle_db_idle_command = _handle_db_idle_command_imported
    _HAS_DB_IDLE_CMD = True
except ImportError as _e_dbidle1:
    try:
        from handlers_message import (
            handle_db_idle_command as _handle_db_idle_command_imported,
        )
        _handle_db_idle_command = _handle_db_idle_command_imported
        _HAS_DB_IDLE_CMD = True
    except ImportError as _e_dbidle2:
        _handle_db_idle_command = None
        _HAS_DB_IDLE_CMD = False
        _DB_IDLE_IMPORT_ERROR = f"{_e_dbidle1} | {_e_dbidle2}"

_HAS_CACHE_STATS_CMD = False
_handle_cache_stats_command = None
_CACHE_STATS_IMPORT_ERROR = None

try:
    from handlers.handlers_message import (
        handle_cache_stats_command as _handle_cache_stats_command_imported,
    )
    _handle_cache_stats_command = _handle_cache_stats_command_imported
    _HAS_CACHE_STATS_CMD = True
except ImportError as _e_cs1:
    try:
        from handlers_message import (
            handle_cache_stats_command as _handle_cache_stats_command_imported,
        )
        _handle_cache_stats_command = _handle_cache_stats_command_imported
        _HAS_CACHE_STATS_CMD = True
    except ImportError as _e_cs2:
        _handle_cache_stats_command = None
        _HAS_CACHE_STATS_CMD = False
        _CACHE_STATS_IMPORT_ERROR = f"{_e_cs1} | {_e_cs2}"

# ═════════════════════════════════════════════════════════════════════
# db_maintenance_commands
# ═════════════════════════════════════════════════════════════════════
register_maintenance_commands = None
start_weekly_diagnostic_task = None
stop_weekly_diagnostic_task = None
stop_auto_vacuum_task = None
_MAINT_CMDS_AVAILABLE = False
_MAINT_CMDS_IMPORT_ERROR = None
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

try:
    import db_maintenance_commands as _maint_mod
    _mod_import_ok = True
except ImportError as _e_mod:
    _mod_import_ok = False
    _maint_import_attempts.append(f"import module: {_e_mod}")
    _maint_mod = None

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

    try:
        stop_auto_vacuum_task = getattr(
            _maint_mod, "stop_auto_vacuum_task", None
        )
    except Exception:
        stop_auto_vacuum_task = None

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
    get_min_publish_interval,
)
from cache import cache_cleanup_task, user_cache, invalidate_user_cache

# ═══════════════════════════════════════════════════════════════════
# Logging setup
# ═══════════════════════════════════════════════════════════════════

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL, logging.INFO)
)
for _noisy in (
    "httpx", "httpcore", "telegram.request", "telegram.ext.ExtBot", "aiohttp.access",
):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger("bot" if __name__ == "__main__" else __name__)

# ═══════════════════════════════════════════════════════════════════
# 🆕 v5.7.6 — FORCE-KILL PREVIOUS INSTANCE
# ═══════════════════════════════════════════════════════════════════

_PID_FILE_PATH = "/app/.bot.pid"
_KILL_TIMEOUT_SEC = 5.0
_TELEGRAM_RELEASE_TIMEOUT_SEC = 15.0
_FALLBACK_HOSTNAME = os.getenv(
    "FALLBACK_HOSTNAME",
    "relaxbo-78m4.onrender.com",
).strip()


def _read_pid_file() -> Optional[int]:
    """يقرأ PID من ملف القفل."""
    try:
        if not os.path.exists(_PID_FILE_PATH):
            return None
        with open(_PID_FILE_PATH, "r") as f:
            pid_str = f.read().strip()
            if pid_str:
                return int(pid_str)
    except (IOError, ValueError) as e:
        logger.debug("_read_pid_file: %s", e)
    return None


def _write_pid_file() -> None:
    """يكتب PID الحالي."""
    try:
        with open(_PID_FILE_PATH, "w") as f:
            f.write(str(os.getpid()))
        logger.info("📝 PID file written: %d", os.getpid())
    except IOError as e:
        logger.warning("_write_pid_file: %s", e)


def _remove_pid_file() -> None:
    """يحذف PID file عند الخروج."""
    try:
        if os.path.exists(_PID_FILE_PATH):
            current = _read_pid_file()
            if current == os.getpid():
                os.remove(_PID_FILE_PATH)
                logger.info("🗑️ PID file removed")
    except Exception as e:
        logger.debug("_remove_pid_file: %s", e)


def _is_process_alive(pid: int) -> bool:
    """هل العملية موجودة؟"""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _force_kill_pid(pid: int, force: bool = False) -> bool:
    """يقتل عملية بـ PID."""
    if pid == os.getpid():
        return False
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.kill(pid, sig)
        logger.warning(
            "%s → PID %d",
            "💀 SIGKILL" if force else "🔪 SIGTERM",
            pid,
        )
        return True
    except ProcessLookupError:
        logger.debug("PID %d غير موجود", pid)
        return True
    except PermissionError:
        logger.warning("لا صلاحية لقتل PID %d", pid)
        return False
    except Exception as e:
        logger.warning("_force_kill_pid(%d): %s", pid, e)
        return False


def _find_bot_processes() -> List[int]:
    """
    يبحث في /proc عن عمليات python تشغّل bot.py.
    يعمل على Linux (Render). يستثني العملية الحالية.
    """
    pids: List[int] = []
    current_pid = os.getpid()
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            if pid == current_pid:
                continue
            try:
                cmdline_path = f"/proc/{pid}/cmdline"
                with open(cmdline_path, "rb") as f:
                    cmdline = f.read().replace(b"\x00", b" ").decode(
                        "utf-8", errors="ignore"
                    )
                if not cmdline:
                    continue
                if "bot.py" in cmdline:
                    pids.append(pid)
                elif "python" in cmdline and "/bot" in cmdline:
                    pids.append(pid)
            except (IOError, PermissionError, OSError):
                continue
    except (IOError, OSError) as e:
        logger.debug("_find_bot_processes: %s", e)
    return pids


async def _force_kill_previous_instance() -> int:
    """
    v5.7.6 — يقتل النسخة القديمة قبل بدء العمل.
    يستخدم 3 استراتيجيات:
      1. PID file (سريع)
      2. /proc scan (شامل)
      3. SIGTERM → 5s → SIGKILL

    Returns: عدد العمليات المقتولة.
    """
    killed_total = 0
    targets: Set[int] = set()

    old_pid = _read_pid_file()
    if old_pid and old_pid != os.getpid() and _is_process_alive(old_pid):
        logger.warning(
            "🔪 PID file يشير لنسخة قديمة نشطة: %d", old_pid
        )
        targets.add(old_pid)

    other_pids = _find_bot_processes()
    if other_pids:
        logger.warning(
            "🔪 وجدت %d نسخة bot.py إضافية: %s",
            len(other_pids), other_pids,
        )
        targets.update(other_pids)

    if not targets:
        logger.info("✅ لا نسخ قديمة نشطة — بيئة نظيفة")
        _write_pid_file()
        return 0

    for pid in targets:
        if _force_kill_pid(pid, force=False):
            killed_total += 1

    deadline = time.monotonic() + _KILL_TIMEOUT_SEC
    while time.monotonic() < deadline:
        remaining = [p for p in targets if _is_process_alive(p)]
        if not remaining:
            break
        await asyncio.sleep(0.5)

    still_alive = [p for p in targets if _is_process_alive(p)]
    if still_alive:
        logger.warning(
            "⚠️ %d عملية لم تنته بـ SIGTERM — SIGKILL: %s",
            len(still_alive), still_alive,
        )
        for pid in still_alive:
            _force_kill_pid(pid, force=True)
        await asyncio.sleep(1.0)

    final_alive = [p for p in targets if _is_process_alive(p)]
    if final_alive:
        logger.error(
            "❌ %d عملية لا تزال حية بعد SIGKILL: %s",
            len(final_alive), final_alive,
        )
    else:
        logger.info("✅ كل النسخ القديمة انتهت (%d)", killed_total)

    _write_pid_file()
    return killed_total


async def _wait_for_telegram_release(
    timeout: float = _TELEGRAM_RELEASE_TIMEOUT_SEC,
) -> bool:
    """
    v5.7.6 — ينتظر حتى يحرر Telegram الـ token.
    يحاول get_me عدة مرات مع backoff.
    """
    try:
        import telegram
    except ImportError:
        return True

    token = _get_bot_token()
    if not token:
        return True

    deadline = time.monotonic() + timeout
    bot = telegram.Bot(token=token)
    attempts = 0

    try:
        while time.monotonic() < deadline:
            attempts += 1
            try:
                me = await asyncio.wait_for(
                    bot.get_me(), timeout=5.0
                )
                logger.info(
                    "✅ Telegram API جاهز (@%s) — attempt %d",
                    getattr(me, "username", "?"), attempts,
                )
                return True
            except telegram.error.Conflict:
                logger.debug(
                    "⏳ Conflict — انتظار (attempt %d)...", attempts
                )
                await asyncio.sleep(1.0)
            except asyncio.TimeoutError:
                logger.debug(
                    "⏳ get_me timeout — retry (attempt %d)", attempts
                )
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.debug(
                    "⏳ get_me failed (%s) — retry", type(e).__name__
                )
                await asyncio.sleep(1.0)

        logger.warning(
            "⚠️ Telegram لم يتحرر خلال %.0fs — متابعة على أي حال",
            timeout,
        )
        return False
    finally:
        try:
            await bot.close()
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════
# SLEEP-PROBE
# ═══════════════════════════════════════════════════════════════════════
_sleep_probe_available = False
try:
    from sleep_probe import (
        auto_install as _sp_auto_install,
        is_installed as _sp_is_installed,
    )
    _sleep_probe_available = True
    try:
        _sp_activated = _sp_auto_install()
        if _sp_activated:
            logger.info("✅ sleep_probe: مُفعَّل")
        else:
            logger.debug("ℹ️ sleep_probe: متاح لكن معطّل")
    except Exception as _sp_install_e:
        logger.warning("⚠️ sleep_probe install: %s", _sp_install_e)
except ImportError:
    logger.debug("ℹ️ sleep_probe.py غير موجود")
except Exception as _sp_import_e:
    logger.warning("⚠️ sleep_probe import: %s", _sp_import_e)


def _log_db_diagnostics_status() -> None:
    if not _DB_DIAG_AVAILABLE:
        logger.info(
            "ℹ️ db_diagnostics: غير متاح — %s",
            _DB_DIAG_IMPORT_ERROR or "module missing",
        )
        return
    if _MARK_PROCESS_START_FN is not None:
        logger.info(
            "✅ db_diagnostics: v%s | mark_process_start ✅",
            _DB_DIAG_VERSION,
        )
    else:
        logger.warning(
            "⚠️ db_diagnostics: v%s محمّل لكن بلا mark_process_start",
            _DB_DIAG_VERSION,
        )
    if _AUTOTUNE_AVAILABLE:
        logger.info(
            "⚙️ auto-tuning: ✅ متاح (ensure_autovacuum_tuning)"
        )
    else:
        logger.info(
            "⚙️ auto-tuning: ℹ️ غير متاح (يتطلب v7.2.24+)"
        )


_NOTIFY_SHUTDOWN_TIMEOUT = 5.0
_BG_TASKS_SHUTDOWN_TIMEOUT = 10.0
_WATCHER_INTERVAL = 30.0
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

try:
    _PM_SLOW_QUERY_WARN_MS = float(
        os.getenv("PM_SLOW_QUERY_WARN_MS", "250")
    )
    if _PM_SLOW_QUERY_WARN_MS < 50:
        _PM_SLOW_QUERY_WARN_MS = 250.0
except (TypeError, ValueError):
    _PM_SLOW_QUERY_WARN_MS = 250.0

_PAYMENT_AMOUNT_EPSILON = 0.01
_DIAG_INCOMING = os.getenv("DIAG_INCOMING", "0").strip().lower() in (
    "1", "true", "yes", "on", "enabled",
)
_KEEP_ALIVE_INTERVAL_SEC = 180.0
_KEEP_ALIVE_INITIAL_DELAY = 30.0
_TG_WARMUP_TIMEOUT = 10.0
_PM_QUERY_TTL = 290.0
_pm_last_query_ts = 0.0
_pm_last_query_result: Optional[Dict[str, Any]] = None
_pm_slow_query_warned = False
_WARMUP_DETECTORS_TASK: Optional[asyncio.Task] = None
_GIL_LAG_MONITOR_TASK: Optional[asyncio.Task] = None
_GIL_LAG_SAMPLES_MAX = 300
_GIL_LAG_HISTORY_WINDOW_SEC = 60.0
_GIL_LAG_WARN_MS = 1000.0
_GIL_LAG_ALERT_INTERVAL_SEC = 30.0
_GIL_LAG_BLOCKED_CUMULATIVE_WARN_MS = 5000.0
_HANDLER_SLOW_WARN_MS = 3000.0
_HANDLER_INFO_MS = 1500.0

_ACTIVE_HANDLER: Dict[str, Any] = {
    "name": None,
    "start": 0.0,
    "chat_id": None,
}

_GROUP_CHAT_FILTER = filters.ChatType.GROUP | filters.ChatType.SUPERGROUP


def _amounts_match(expected: Any, actual: Any) -> bool:
    try:
        e = float(expected or 0)
        a = float(actual or 0)
    except (TypeError, ValueError):
        return False
    return abs(e - a) < _PAYMENT_AMOUNT_EPSILON


_NOTIFY_TASKS: Set[asyncio.Task] = set()

_BOT_METRICS: Dict[str, Any] = {
    "posts_success": 0, "posts_failed": 0, "commands_total": 0,
    "pings_total": 0, "ping_min_ms": None, "ping_max_ms": None,
    "ping_sum_ms": 0, "started_at": time.monotonic(),
}


def record_bot_metric(key: str, value: Any = 1) -> None:
    try:
        cur = _BOT_METRICS.get(key)
        if isinstance(cur, int) and isinstance(value, int):
            _BOT_METRICS[key] = cur + value
        else:
            _BOT_METRICS[key] = value
    except Exception as _e:
        logger.debug("record_bot_metric(%r): %s", key, _e)


def _wrap_handler_with_timing(
    handler: Callable,
    name: str,
) -> Callable:
    """
    v5.7.5: INFO @ 1.5s، WARNING + stack @ 3s.
    """
    if not callable(handler):
        return handler

    @functools.wraps(handler)
    async def _timed(update, context):
        _prev = _ACTIVE_HANDLER.copy()
        _ACTIVE_HANDLER["name"] = name
        _ACTIVE_HANDLER["start"] = time.monotonic()
        try:
            _ACTIVE_HANDLER["chat_id"] = (
                update.effective_chat.id
                if getattr(update, "effective_chat", None) else None
            )
        except Exception:
            _ACTIVE_HANDLER["chat_id"] = None

        t0 = time.monotonic()
        try:
            return await handler(update, context)
        finally:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            try:
                if elapsed_ms >= _HANDLER_INFO_MS:
                    logger.info(
                        "⏱️ handler %s: %.0fms | chat=%s",
                        name, elapsed_ms,
                        _ACTIVE_HANDLER.get("chat_id"),
                    )
                if elapsed_ms >= _HANDLER_SLOW_WARN_MS:
                    _stack_hint = ""
                    try:
                        _frames = traceback.extract_stack()
                        _relevant = [
                            f"  {f.filename.split('/')[-1]}:{f.lineno} "
                            f"in {f.name}"
                            for f in _frames[-6:]
                            if "handlers_message" in f.filename
                            or "handlers/" in f.filename
                        ]
                        if _relevant:
                            _stack_hint = "\n" + "\n".join(_relevant)
                    except Exception:
                        pass
                    logger.warning(
                        "🐌 SLOW handler: %s took %.0fms | chat=%s%s",
                        name, elapsed_ms,
                        _ACTIVE_HANDLER.get("chat_id"),
                        _stack_hint,
                    )
            except Exception:
                pass
            _ACTIVE_HANDLER.update(_prev)

    return _timed


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


def _spawn_warmup_detectors_pool() -> Optional[asyncio.Task]:
    global _WARMUP_DETECTORS_TASK
    if not _HAS_WARMUP_DETECTORS or _warmup_detectors_pool_fn is None:
        return None
    if _WARMUP_DETECTORS_TASK is not None and not _WARMUP_DETECTORS_TASK.done():
        return _WARMUP_DETECTORS_TASK
    if _WARMUP_DETECTORS_TASK is not None and _WARMUP_DETECTORS_TASK.done():
        try:
            _ = _WARMUP_DETECTORS_TASK.result()
        except Exception:
            pass
        _WARMUP_DETECTORS_TASK = None
    try:
        _WARMUP_DETECTORS_TASK = asyncio.create_task(
            _warmup_detectors_pool_fn(), name="warmup-detectors-pool",
        )
        logger.info("🔥 warmup_detectors_pool: task spawned")
        return _WARMUP_DETECTORS_TASK
    except Exception as _e:
        logger.warning(
            "⚠️ فشل إنشاء task تسخين detectors: %s", _e, exc_info=True
        )
        return None


async def _await_warmup_detectors_pool(timeout: float = 15.0) -> bool:
    global _WARMUP_DETECTORS_TASK
    if _WARMUP_DETECTORS_TASK is None:
        return False
    if _WARMUP_DETECTORS_TASK.done():
        try:
            return bool(_WARMUP_DETECTORS_TASK.result())
        except Exception as _e:
            logger.debug("warmup task done with exception: %s", _e)
            return False
    try:
        result = await asyncio.wait_for(
            _WARMUP_DETECTORS_TASK, timeout=timeout
        )
        return bool(result)
    except asyncio.TimeoutError:
        logger.warning(
            "⚠️ warmup_detectors_pool: لم ينتهِ خلال %.1fs", timeout
        )
        return False
    except asyncio.CancelledError:
        raise
    except Exception as _e:
        logger.debug("warmup_detectors_pool: %s", _e)
        return False


async def _gil_lag_monitor() -> None:
    logger.info(
        "🔍 GIL-MONITOR: بدء المراقبة (warn=%.0fms, cooldown=%.0fs)",
        _GIL_LAG_WARN_MS, _GIL_LAG_ALERT_INTERVAL_SEC,
    )
    history: List[Tuple[float, float]] = []
    last_alert_ts = 0.0
    cumulative_blocked_ms = 0.0

    try:
        import psutil as _psu_t
        _proc = _psu_t.Process()
    except Exception:
        _proc = None

    while True:
        try:
            t0 = time.monotonic()
            await asyncio.sleep(0.1)
            now = time.monotonic()
            elapsed = now - t0
            lag_ms = max(0.0, (elapsed - 0.1) * 1000.0)

            history.append((now, lag_ms))
            cutoff = now - _GIL_LAG_HISTORY_WINDOW_SEC
            history = [(ts, l) for (ts, l) in history if ts >= cutoff]
            if len(history) > _GIL_LAG_SAMPLES_MAX:
                history = history[-_GIL_LAG_SAMPLES_MAX:]

            if lag_ms > _GIL_LAG_WARN_MS:
                cumulative_blocked_ms += lag_ms

            if (lag_ms > _GIL_LAG_WARN_MS
                    and (now - last_alert_ts) >= _GIL_LAG_ALERT_INTERVAL_SEC):
                last_alert_ts = now
                lags = sorted(l for (_, l) in history)
                n = len(lags)
                if n:
                    p50 = lags[n // 2]
                    p90 = lags[min(int(n * 0.9), n - 1)]
                    p99 = lags[min(int(n * 0.99), n - 1)]
                    maxv = lags[-1]
                else:
                    p50 = p90 = p99 = maxv = 0.0

                active_name = _ACTIVE_HANDLER.get("name") or "none"
                active_elapsed = (
                    now - _ACTIVE_HANDLER["start"]
                    if _ACTIVE_HANDLER.get("name") else 0.0
                )
                active_chat = _ACTIVE_HANDLER.get("chat_id")

                _mem_mb = 0.0
                try:
                    if _proc is not None:
                        _mem_mb = _proc.memory_info().rss / (1024 * 1024)
                except Exception:
                    pass
                _task_count = 0
                try:
                    _task_count = len(asyncio.all_tasks())
                except Exception:
                    pass
                _gc_count = 0
                try:
                    import gc as _gc_t
                    _gc_count = _gc_t.get_count()
                except Exception:
                    pass

                logger.warning(
                    "🔴 GIL-MONITOR: lag=%.0fms | "
                    "p50=%.0f p90=%.0f p99=%.0f max=%.0f | "
                    "active=%s (%.1fs, chat=%s) | "
                    "mem=%.0fMB tasks=%d gc=%d | cum=%.0fms/%.0fs",
                    lag_ms, p50, p90, p99, maxv,
                    active_name, active_elapsed,
                    active_chat or "-",
                    _mem_mb, _task_count, _gc_count,
                    cumulative_blocked_ms, _GIL_LAG_HISTORY_WINDOW_SEC,
                )

                if (cumulative_blocked_ms
                        > _GIL_LAG_BLOCKED_CUMULATIVE_WARN_MS):
                    logger.error(
                        "🚨 GIL-MONITOR: تراكم %.0fms خلال %.0fs — "
                        "sync code؟ OCR؟ backup؟",
                        cumulative_blocked_ms,
                        _GIL_LAG_HISTORY_WINDOW_SEC,
                    )
                    cumulative_blocked_ms = 0.0
        except asyncio.CancelledError:
            logger.info("🛑 GIL-MONITOR: تم الإيقاف")
            raise
        except Exception as _e:
            logger.debug("GIL-MONITOR error: %s", _e)


def _spawn_gil_lag_monitor() -> Optional[asyncio.Task]:
    global _GIL_LAG_MONITOR_TASK
    if (_GIL_LAG_MONITOR_TASK is not None
            and not _GIL_LAG_MONITOR_TASK.done()):
        return _GIL_LAG_MONITOR_TASK
    try:
        _GIL_LAG_MONITOR_TASK = asyncio.create_task(
            _gil_lag_monitor(), name="gil-lag-monitor"
        )
        return _GIL_LAG_MONITOR_TASK
    except Exception as _e:
        logger.warning("⚠️ فشل بدء GIL-MONITOR: %s", _e)
        return None


def _build_http_request_pool():
    if not _HAS_HTTPX_REQUEST or HTTPXRequest is None:
        logger.warning("⚠️ HTTPXRequest غير متاح")
        return None
    try:
        request = HTTPXRequest(
            connection_pool_size=32, connect_timeout=15.0,
            read_timeout=20.0, write_timeout=20.0, pool_timeout=10.0,
        )
        logger.info("🚀 HTTPXRequest pool: 32")
        return request
    except TypeError:
        try:
            return HTTPXRequest(connection_pool_size=32)
        except Exception:
            return None
    except Exception:
        return None


async def _warmup_telegram_api(app: Application) -> bool:
    t_warm = time.monotonic()
    try:
        me = await asyncio.wait_for(
            app.bot.get_me(), timeout=_TG_WARMUP_TIMEOUT
        )
        elapsed_ms = (time.monotonic() - t_warm) * 1000
        if me is not None:
            logger.info(
                "✅ Telegram API: اتصال مُهيَّأ — @%s (%.0fms)",
                getattr(me, "username", "?"), elapsed_ms,
            )
            return True
        return False
    except asyncio.TimeoutError:
        logger.warning("⚠️ Telegram API warmup: timeout")
        return False
    except Exception as _e:
        logger.warning("⚠️ Telegram API warmup: %s", _e)
        return False


def _log_spam_detector_status() -> None:
    if _SPAM_DETECTOR_AVAILABLE:
        logger.info(
            "🛡️ Spam Detector: ✅ محمّل (%s, %d layers)",
            _SPAM_DETECTOR_VERSION, _SPAM_DETECTOR_LAYERS_COUNT,
        )
    else:
        logger.warning(
            "⚠️ Spam Detector: ❌ غير محمّل — %s",
            _SPAM_DETECTOR_IMPORT_ERROR,
        )


def _log_security_bridge_status() -> None:
    if _SECURITY_BRIDGE_AVAILABLE:
        logger.info("🌉 Security Bridge: ✅ محمّل")
    else:
        logger.warning(
            "⚠️ Security Bridge: غير متاح — %s", _SB_IMPORT_ERROR
        )


def _log_perf_tuning_status() -> None:
    try:
        _max_ch = getattr(CONFIG, "MAX_CHANNELS_PER_CYCLE", "?")
        logger.info(
            "⚡ PERF Tuning: MAX_CHANNELS=%s | HTTPX_POOL=%s",
            _max_ch, "32" if _HAS_HTTPX_REQUEST else "default",
        )
    except Exception as _e:
        logger.debug("_log_perf_tuning_status: %s", _e)


try:
    from database import ANALYTICS_MIXIN_AVAILABLE
    if not ANALYTICS_MIXIN_AVAILABLE:
        logger.warning("⚠️ AnalyticsMixin مفقود")
except Exception:
    ANALYTICS_MIXIN_AVAILABLE = False

try:
    from database import (
        CHANNELS_POSTS_MIXIN_AVAILABLE, SUBSCRIPTIONS_MIXIN_AVAILABLE,
        GROUPS_MIXIN_AVAILABLE, TICKETS_MIXIN_AVAILABLE,
        CONTESTS_MIXIN_AVAILABLE, STATS_MIXIN_AVAILABLE,
        SETTINGS_MIXIN_AVAILABLE, POINTS_MIXIN_AVAILABLE,
        BACKUP_MIXIN_AVAILABLE, REMINDERS_MIXIN_AVAILABLE,
    )
    _mixins_status = {
        "channels_posts": CHANNELS_POSTS_MIXIN_AVAILABLE,
        "subscriptions": SUBSCRIPTIONS_MIXIN_AVAILABLE,
        "groups": GROUPS_MIXIN_AVAILABLE, "tickets": TICKETS_MIXIN_AVAILABLE,
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
        logger.info(
            "✅ كل الـ %d Mixins محمّلة", len(_mixins_status)
        )
except Exception:
    pass

try:
    from database import REFACTOR_MIXIN_AVAILABLE
    if REFACTOR_MIXIN_AVAILABLE:
        logger.info("✅ RefactorMixin محمّل")
except Exception:
    pass

if _MAINTENANCE_AVAILABLE:
    logger.info("✅ maintenance محمّل")
else:
    logger.warning(
        "⚠️ maintenance غير متاح: %s", _MAINTENANCE_IMPORT_ERROR
    )

if _DEV_LOG_AVAILABLE:
    logger.info("✅ _notify_dev_log متاح")
else:
    logger.warning("⚠️ _notify_dev_log غير متاح")

if _MEMBERSHIP_AVAILABLE:
    logger.info("✅ MembershipHandler متاح")
else:
    logger.warning("⚠️ register_membership_handlers غير متاح")

if _ADMIN_LOGS_CLEANUP_AVAILABLE:
    logger.info("✅ admin_logs cleanup متاح")
else:
    logger.warning("⚠️ دوال تنظيف admin_logs غير متاحة")

if _CH_DELETE_AVAILABLE:
    logger.info("✅ handlers_channels_delete متاح")
else:
    logger.warning("⚠️ handlers_channels_delete غير متاح")

if _NAV_FIX_AVAILABLE:
    logger.info("✅ handlers_nav_fix متاح")
else:
    logger.info("ℹ️ handlers_nav_fix غير متاح")

if _MAINT_CMDS_AVAILABLE:
    logger.info("✅ db_maintenance_commands متاح")
else:
    logger.warning("⚠️ db_maintenance_commands غير متاح")

if _HAS_DB_IDLE_CMD:
    logger.info("✅ /db_idle متاح")
if _HAS_CACHE_STATS_CMD:
    logger.info("✅ /cache_stats متاح")
if _HAS_WARMUP_DETECTORS:
    logger.info("🔥 warmup_detectors_pool: ✅ متاح")

if _ANALYTICS_HANDLERS_AVAILABLE:
    logger.info("✅ handlers_analytics متاح")
else:
    logger.warning("⚠️ handlers_analytics غير متاح")

if (_ANALYTICS_REGISTER_AVAILABLE
        and callable(_register_analytics_handlers)):
    logger.info("✅ handlers_analytics.register_handlers متاح")
else:
    logger.info("ℹ️ handlers_analytics.register_handlers غير متاح")

_log_spam_detector_status()
_log_security_bridge_status()
_log_db_diagnostics_status()
_log_perf_tuning_status()

try:
    import inspect as _inspect_pc
    _pc_fn = getattr(GroupRateLimiterManager, "periodic_cleanup_task", None)
    if _pc_fn is None:
        logger.warning("⚠️ periodic_cleanup_task غير موجود")
    elif _inspect_pc.isfunction(_pc_fn):
        try:
            _pc_sig = _inspect_pc.signature(_pc_fn)
            if (len(_pc_sig.parameters) >= 1
                    and 'self' in _pc_sig.parameters):
                logger.warning("⚠️ periodic_cleanup_task يحتاج 'self'")
        except (ValueError, TypeError):
            pass
except Exception:
    pass

ALLOWED_UPDATES = [
    "message", "edited_message", "callback_query", "chat_join_request",
    "pre_checkout_query", "chat_member", "my_chat_member",
]
_GROUP_LOG_INSTANCE = None

PUBLIC_COMMANDS = [
    ("start", "🏠 القائمة الرئيسية"), ("help", "📚 المساعدة"),
    ("trial", "🎁 تجربة مجانية"), ("subscribe", "💎 اشتراك"),
    ("support", "📞 دعم فني"), ("language", "🌐 اللغة"),
    ("developer", "👨‍💻 المطور"), ("contests", "🏆 المسابقات"),
    ("replies", "💬 الردود التلقائية"), ("gift_plans", "🎁 خطط الهدايا"),
    ("redeem_gift", "🎟️ استرداد كود هدية"), ("mood", "🎭 تحليل المشاعر"),
    ("channels", "📡 قنواتي"), ("posts", "📋 منشوراتي"),
    ("auto_publish", "📤 تبديل النشر التلقائي"),
    ("auto_recycle", "♻️ تبديل التدوير"),
]

ADMIN_COMMANDS = [
    ("stats", "📊 الإحصائيات"), ("grant", "🎁 منح اشتراك يدوي"),
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
    ("backup", "💾 نسخ احتياطي"), ("restore", "🔄 عرض النسخ"),
    ("db_diag", "🔬 تشخيص قاعدة البيانات"),
    ("db_vacuum", "🧹 تنظيف قاعدة البيانات"),
    ("db_diag_quick", "🔬 تقرير صحي مختصر"),
    ("db_maintenance", "🧹 صيانة قاعدة البيانات"),
    ("db_weekly", "📅 التقرير الأسبوعي"),
    ("autoblocked", "🚫 المصادر المحجوبة تلقائياً"),
    ("db_idle", "🔍 تدقيق idle-in-transaction"),
    ("cache_stats", "📊 إحصائيات الكاش الحية"),
    ("fullhealth", "🏥 التشخيص الشامل"),
    ("latency", "🔬 اختبار الكمون"),
    ("databases", "🗂️ قواعد البيانات المُعدّة"),
    ("ping", "🏓 قياس كمون الاتصال"),
    ("posts_stats", "📊 إحصائيات النشر (DB)"),
    ("autotune", "⚙️ ضبط autovacuum"),
    ("db_tune", "⚙️ ضبط autovacuum (اختصار)"),
    ("analytics", "📊 التحليلات المتقدمة"),
    ("versions", "📦 إصدارات الوحدات"),
    ("analytics_reset", "🗑️ إبطال كاش التحليلات"),
    ("files", "📂 ملفات المشروع"),
]

GROUP_COMMANDS = [
    ("syncgroup", "🔗 تفعيل المجموعة"),
    ("security", "🛡️ إعدادات الأمان"),
    ("panel", "📋 لوحة التحكم"), ("lock", "🔒 قفل المجموعة"),
    ("unlock", "🔓 فتح المجموعة"), ("ban", "🚫 حظر مستخدم"),
    ("mute", "🔇 كتم مستخدم"), ("warn", "⚠️ تحذير مستخدم"),
    ("kick", "👢 طرد مستخدم"), ("restrict", "🔒 تقييد مستخدم"),
    ("unban", "🔓 إلغاء حظر"), ("pin", "📌 تثبيت رسالة"),
]


async def _shutdown_detector_tasks(timeout: float = 3.0) -> None:
    if not _SPAM_DETECTOR_AVAILABLE or _detectors_module is None:
        return
    if _DETECTORS_HAS_SHUTDOWN_HELPER:
        try:
            result = None
            try:
                _loop = asyncio.get_running_loop()
                result = _shutdown_default_executor_fn(
                    _loop, timeout=timeout
                )
            except TypeError:
                try:
                    result = _shutdown_default_executor_fn(timeout=timeout)
                except TypeError:
                    result = _shutdown_default_executor_fn()
            if asyncio.iscoroutine(result):
                await asyncio.wait_for(result, timeout=timeout + 0.5)
            return
        except Exception as _e:
            logger.debug("shutdown_default_executor failed: %s", _e)

    if callable(_shutdown_detector_pool_fn):
        try:
            result = _shutdown_detector_pool_fn()
            if asyncio.iscoroutine(result):
                await asyncio.wait_for(result, timeout=timeout)
            return
        except Exception as _e:
            logger.debug("_shutdown_detector_pool_fn: %s", _e)


async def _shutdown_db_pool(timeout: float = 5.0) -> None:
    if not hasattr(DB, "close_pool") and not hasattr(DB, "close"):
        return
    _fn_name = "close_pool" if hasattr(DB, "close_pool") else "close"
    _fn = getattr(DB, _fn_name, None)
    if not callable(_fn):
        return
    try:
        result = _fn()
        if asyncio.iscoroutine(result):
            await asyncio.wait_for(result, timeout=timeout)
        logger.info("✅ DB.%s() — تم إغلاق pool نظيفاً", _fn_name)
    except asyncio.TimeoutError:
        logger.warning("⚠️ DB.%s() — انتهت المهلة", _fn_name)
    except asyncio.CancelledError:
        raise
    except Exception as _e:
        logger.debug("DB.%s(): %s", _fn_name, _e)


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
                except (TypeError, ValueError):
                    continue
            any_method_succeeded = True
            break
        except Exception:
            continue

    if not any_method_succeeded:
        logger.warning("⚠️ _collect_admin_ids: لا توجد قائمة أدمن من DB")

    return sorted(admin_ids)


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
        "db_diag", "db_vacuum", "syncgroup", "security", "panel",
        "lock", "unlock", "ban", "mute", "warn", "kick",
        "restrict", "unban", "pin", "register_hidden_owner",
        "remove_hidden_owner", "add_hidden_admin",
        "remove_hidden_admin", "list_hidden_admins",
    ]

    import inspect as _inspect_vc
    missing: List[str] = []
    sync_handlers: List[str] = []
    for name in required:
        _attr = getattr(CommandHandlers, name, None)
        if not callable(_attr):
            missing.append(name)
            continue
        try:
            if not _inspect_vc.iscoroutinefunction(_attr):
                sync_handlers.append(name)
        except Exception:
            pass

    if missing:
        logger.error("❌ دوال مفقودة: %s", missing)
        _command_handlers_verified = False
        return False
    if sync_handlers:
        logger.error("❌ دوال sync: %s", sync_handlers)
        _command_handlers_verified = False
        return False

    logger.info(
        "✅ كل %d دالة CommandHandlers موجودة و async", len(required)
    )
    _command_handlers_verified = True
    return True


def _verify_db_config() -> bool:
    try:
        db_type = getattr(DB, "DB_TYPE", "unknown")
        db_url = getattr(CONFIG, "DATABASE_URL", "") or ""
        try:
            _pid = int(getattr(CONFIG, "PRIMARY_OWNER_ID", 0) or 0)
            if _pid == 0:
                logger.warning("⚠️ PRIMARY_OWNER_ID=0")
        except (TypeError, ValueError):
            pass
        if not db_url:
            if db_type != "sqlite":
                logger.warning(
                    "⚠️ DB_TYPE=%s لكن DATABASE_URL فارغ!", db_type
                )
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


def _init_group_log_instance(app) -> bool:
    global _GROUP_LOG_INSTANCE
    if not _GROUP_LOG_INIT_AVAILABLE or not callable(_init_group_log):
        return False
    bot = getattr(app, "bot", None)
    if bot is None:
        return False
    try:
        _GROUP_LOG_INSTANCE = _init_group_log(DB, bot)
        if _GROUP_LOG_INSTANCE is None:
            return False
        _GROUP_LOG_INSTANCE.start()
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
        elif hasattr(_GROUP_LOG_INSTANCE, "stop"):
            _GROUP_LOG_INSTANCE.stop()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("⚠️ GroupLog shutdown: %s", e)
    finally:
        _GROUP_LOG_INSTANCE = None


async def cleanup_admin_logs_periodically() -> None:
    if not _ADMIN_LOGS_CLEANUP_AVAILABLE:
        return
    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        raise
    while True:
        try:
            db_type = getattr(DB, "DB_TYPE", "sqlite")
            deleted = 0
            async with DB.connection() as conn:
                if db_type == "postgres" and _cleanup_admin_logs_pg is not None:
                    deleted = await _cleanup_admin_logs_pg(conn, logger)
                elif db_type == "mysql" and _cleanup_admin_logs_mysql is not None:
                    deleted = await _cleanup_admin_logs_mysql(conn, logger)
                elif _cleanup_admin_logs_sqlite is not None:
                    deleted = await _cleanup_admin_logs_sqlite(conn, logger)
            if deleted:
                logger.info(
                    "✅ admin_logs cleanup: حُذف %d صف", deleted
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("❌ cleanup_admin_logs: %s", e, exc_info=True)
        try:
            await asyncio.sleep(86400)
        except asyncio.CancelledError:
            raise


async def cleanup_removed_channels_periodically() -> None:
    GRACE_DAYS = _REMOVED_CHANNELS_GRACE_DAYS
    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        raise
    while True:
        try:
            deleted = 0
            if hasattr(DB, 'hard_delete_removed_channels_before'):
                cutoff_dt = TimeUtils.utc_now() - timedelta(days=GRACE_DAYS)
                deleted = await DB.hard_delete_removed_channels_before(cutoff_dt)
            else:
                db_type = getattr(DB, "DB_TYPE", "sqlite")
                if db_type == "postgres":
                    result = await DB.execute(
                        "DELETE FROM user_channels WHERE removed_at IS "
                        "NOT NULL AND removed_at < NOW() - INTERVAL "
                        "'1 day' * $1",
                        (GRACE_DAYS,)
                    )
                elif db_type == "mysql":
                    result = await DB.execute(
                        "DELETE FROM user_channels WHERE removed_at IS "
                        "NOT NULL AND removed_at < UTC_TIMESTAMP() - "
                        "INTERVAL %s DAY",
                        (GRACE_DAYS,)
                    )
                else:
                    result = await DB.execute(
                        "DELETE FROM user_channels WHERE removed_at IS "
                        "NOT NULL AND julianday('now') - "
                        "julianday(removed_at) > ?",
                        (GRACE_DAYS,)
                    )
                if isinstance(result, int):
                    deleted = result
                else:
                    try:
                        deleted = int(getattr(result, 'rowcount', 0) or 0)
                    except (TypeError, ValueError):
                        deleted = 0
            if deleted:
                logger.info(
                    "✅ removed_channels cleanup: حُذف %d قناة", deleted
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(
                "❌ cleanup_removed_channels: %s", e, exc_info=True
            )
        try:
            await asyncio.sleep(86400)
        except asyncio.CancelledError:
            raise


async def _validate_invoice_for_payment(user_id: int, payload: str):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None, None, None
    invoice_number = data.get('invoice')
    if not invoice_number:
        return None, None, None
    try:
        invoice = await DB.get_invoice(invoice_number)
    except Exception:
        return None, None, None
    if (not invoice or invoice.get('user_id') != user_id
            or invoice.get('status') != 'pending'
            or not invoice.get('number')):
        return None, None, None
    payment_type = data.get('type')
    if payment_type not in ('subscription', 'gift'):
        return None, None, None
    plan_id = (data.get('plan_id') if payment_type == 'subscription'
               else data.get('gift_plan_id'))
    if not plan_id:
        return None, None, None
    try:
        plan = (await DB.get_plan(plan_id)
                if payment_type == 'subscription'
                else await DB.get_gift_plan(plan_id))
    except Exception:
        return None, None, None
    if not plan:
        return None, None, None
    return invoice, plan, data


async def pre_checkout(update, context):
    query = update.pre_checkout_query
    user_id = query.from_user.id
    payload = query.invoice_payload
    invoice, plan, data = await _validate_invoice_for_payment(user_id, payload)
    if invoice is None or plan is None:
        try:
            await query.answer(
                ok=False,
                error_message="الفاتورة غير صالحة أو انتهت صلاحيتها."
            )
        except Exception as e:
            logger.error("❌ pre-checkout reject: %s", e)
        return
    try:
        q_currency = getattr(query, 'currency', None)
        if q_currency and q_currency != "XTR":
            await query.answer(
                ok=False, error_message="العملة غير مدعومة."
            )
            return
    except Exception:
        pass
    if hasattr(query, 'total_amount'):
        expected_amount = plan.get('price')
        if (expected_amount is not None
                and float(expected_amount or 0) > 0
                and not _amounts_match(expected_amount, query.total_amount)):
            await query.answer(
                ok=False,
                error_message="المبلغ غير مطابق لسعر الخطة."
            )
            return
    try:
        await query.answer(ok=True)
    except Exception as e:
        logger.error("❌ pre-checkout success: %s", e)


async def successful_payment(update, context):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    payload = payment.invoice_payload
    total_amount = payment.total_amount
    telegram_payment_charge_id = payment.telegram_payment_charge_id
    provider_payment_charge_id = payment.provider_payment_charge_id

    invoice, plan, data = await _validate_invoice_for_payment(user_id, payload)
    if invoice is None or plan is None:
        try:
            _pd = json.loads(payload)
            _inv_num = _pd.get('invoice')
            if _inv_num:
                _existing = await DB.get_invoice(_inv_num)
                if (_existing and _existing.get('user_id') == user_id
                        and _existing.get('status') == 'paid'):
                    await safe_send(
                        context.bot, user_id,
                        "✅ تم استلام إشعار الدفع.\nالفاتورة مُعالجة مسبقاً."
                    )
                    return
        except Exception:
            pass
        await safe_send(context.bot, user_id, "❌ حدث خطأ في معالجة الدفع.")
        return

    plan_price = plan.get('price', 0)
    if float(plan_price or 0) > 0 and not _amounts_match(
        plan_price, total_amount
    ):
        await safe_send(context.bot, user_id, "❌ المبلغ المدفوع غير مطابق.")
        return

    payment_type = data.get('type')
    payment_id = telegram_payment_charge_id or provider_payment_charge_id
    if not payment_id:
        await safe_send(
            context.bot, user_id,
            f"❌ مشكلة في بيانات الدفع. الفاتورة: "
            f"<code>{invoice.get('number') or '?'}</code>",
            parse_mode='HTML'
        )
        return

    plan_name = plan.get('name', 'الخطة')

    if payment_type == 'subscription':
        try:
            success = await DB.activate_subscription_with_payment(
                user_id=user_id, invoice_number=invoice['number'],
                payment_id=payment_id, plan_id=plan['id']
            )
        except Exception as e:
            logger.exception("❌ subscription activation: %s", e)
            await safe_send(context.bot, user_id, "❌ حدث خطأ غير متوقع.")
            return
        if not success:
            logger.error(
                "🔴 SUBSCRIPTION_DB_FAILED: user=%s invoice=%s",
                user_id, invoice['number']
            )
            try:
                _spawn_notify_dev_log(
                    context,
                    f"🔴 فشل تفعيل اشتراك\n👤 {user_id}\n"
                    f"🧾 {invoice['number']}"
                )
            except Exception:
                pass
            await safe_send(
                context.bot, user_id,
                "⚠️ تم استلام الدفع لكن حدث خطأ في التفعيل."
            )
            return
        try:
            await safe_send(
                context.bot, user_id,
                f"✅ تم تفعيل اشتراك {plan_name} بنجاح!"
            )
        except Exception:
            pass
        try:
            await DB.add_payment_log(
                user_id, 'xtr', 'subscription_paid',
                {'invoice': invoice['number'], 'plan_id': plan['id']}
            )
        except Exception:
            pass
        try:
            await invalidate_user_cache(user_id)
        except Exception:
            pass
        try:
            _fname = update.effective_user.first_name or ""
            _spawn_notify_dev_log(
                context,
                f"💎 اشتراك مدفوع جديد\n👤 {_fname}\n"
                f"🆔 {user_id}\n💎 {plan_name}\n"
                f"💰 {int(total_amount or 0)} ⭐"
            )
        except Exception:
            pass

    elif payment_type == 'gift':
        try:
            paid = await DB.mark_invoice_paid(
                invoice['number'], payment_id
            )
        except Exception as e:
            logger.exception("❌ mark_invoice_paid: %s", e)
            await safe_send(context.bot, user_id, "❌ حدث خطأ غير متوقع.")
            return
        if not paid:
            await safe_send(context.bot, user_id, "❌ فشل توثيق الدفع.")
            return
        try:
            code = await DB.create_gift_code(
                plan_id=plan['id'], creator_id=user_id
            )
        except Exception as e:
            logger.exception("❌ create_gift_code: %s", e)
            try:
                _spawn_notify_dev_log(
                    context,
                    f"🔴 فشل توليد كود هدية\n👤 {user_id}\n"
                    f"🧾 {invoice['number']}"
                )
            except Exception:
                pass
            await safe_send(
                context.bot, user_id,
                "⚠️ تم توثيق الدفع لكن فشل توليد الكود."
            )
            return
        if not code:
            logger.error("❌ create_gift_code أعاد None: user=%s", user_id)
            try:
                _spawn_notify_dev_log(
                    context,
                    f"🔴 create_gift_code أعاد None\n"
                    f"👤 {user_id}\n🧾 {invoice['number']}"
                )
            except Exception:
                pass
            await safe_send(
                context.bot, user_id,
                "⚠️ تم توثيق الدفع لكن فشل توليد الكود."
            )
            return
        duration = plan.get('duration_days') or plan.get('days') or 0
        try:
            await safe_send(
                context.bot, user_id,
                f"🎉 تم شراء كود الهدية بنجاح!\n"
                f"🎁 <code>{code}</code>\n📅 المدة: {duration} يوم",
                parse_mode='HTML'
            )
        except Exception:
            pass
        try:
            _fname = update.effective_user.first_name or ""
            _spawn_notify_dev_log(
                context,
                f"🎁 هدية مُشتراة\n👤 {_fname}\n"
                f"🆔 {user_id}\n💎 {plan_name}\n🔑 {code}"
            )
        except Exception:
            pass


async def health_check(request):
    return web.Response(text="OK", status=200)


async def keep_alive():
    try:
        await asyncio.sleep(_KEEP_ALIVE_INITIAL_DELAY)
    except asyncio.CancelledError:
        raise
    url = (os.getenv("KEEP_ALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL"))
    if not url:
        logger.info(
            "ℹ️ keep_alive: URL غير موجود — المهمة ستُحجب أبدياً"
        )
        await asyncio.Event().wait()
        return
    url = url.rstrip('/')
    health_url = f"{url}/health"
    _consecutive_errors = 0
    _timeout = aiohttp.ClientTimeout(total=15, connect=5)
    _connector = aiohttp.TCPConnector(
        limit=2, ttl_dns_cache=300, keepalive_timeout=60
    )
    async with aiohttp.ClientSession(
        timeout=_timeout, connector=_connector
    ) as session:
        while True:
            try:
                await asyncio.sleep(_KEEP_ALIVE_INTERVAL_SEC)
                async with session.get(health_url) as response:
                    await response.read()
                    if response.status == 200:
                        _consecutive_errors = 0
                    else:
                        _consecutive_errors += 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                _consecutive_errors += 1
                if _consecutive_errors >= 3:
                    logger.warning(
                        "💓 keep-alive: %d أخطاء متتالية",
                        _consecutive_errors
                    )
                else:
                    logger.debug("💓 keep-alive: %s", e)


async def _fetch_pg_activity_cached() -> Dict[str, Any]:
    global _pm_last_query_ts, _pm_last_query_result
    now = time.monotonic()
    if (_pm_last_query_result is not None
            and (now - _pm_last_query_ts) < _PM_QUERY_TTL):
        return _pm_last_query_result
    try:
        row = await DB.fetchone(
            "SELECT count(*) AS total, "
            "count(*) FILTER (WHERE state = 'active') AS active, "
            "count(*) FILTER (WHERE state = 'idle') AS idle, "
            "count(*) FILTER (WHERE state = 'idle in transaction') "
            "AS idle_in_tx, "
            "count(*) FILTER (WHERE wait_event_type = 'Lock') AS lock_waits, "
            "count(*) FILTER (WHERE wait_event_type IN "
            "('Lock', 'LWLock', 'BufferPin')) AS waiting "
            "FROM pg_stat_activity WHERE datname = current_database()"
        )
        data = row if isinstance(row, dict) else (dict(row) if row else {})
        _pm_last_query_ts = now
        _pm_last_query_result = data
        return data
    except Exception as e:
        logger.debug("_fetch_pg_activity_cached: %s", e)
        return {}


async def pool_health_monitor() -> None:
    _idle_tx_streak = 0
    try:
        await asyncio.sleep(_PM_INITIAL_DELAY_SEC)
    except asyncio.CancelledError:
        raise
    while True:
        try:
            db_type = getattr(DB, "DB_TYPE", "sqlite")
            if db_type != "postgres":
                try:
                    await asyncio.sleep(1800)
                except asyncio.CancelledError:
                    raise
                continue
            data = await _fetch_pg_activity_cached()
            total = int(data.get("total") or 0)
            idle_in_tx = int(data.get("idle_in_tx") or 0)
            util_pct = (total / 20 * 100) if total else 0
            if idle_in_tx > 0:
                _idle_tx_streak += 1
            else:
                _idle_tx_streak = 0
            if (idle_in_tx >= _PM_IDLE_TX_ERROR_THRESHOLD
                    or util_pct >= _PM_UTIL_CRITICAL_PCT):
                logger.error(
                    "🔴 pool CRITICAL: total=%d idle_tx=%d util=%.0f%%",
                    total, idle_in_tx, util_pct
                )
            elif util_pct >= _PM_UTIL_WARN_PCT:
                logger.warning(
                    "⚠️ pool DIAG: total=%d util=%.0f%%",
                    total, util_pct
                )
            else:
                logger.info(
                    "🟢 pool HEALTH: total=%d util=%.0f%%",
                    total, util_pct
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("pool_health_monitor: %s", e)
        try:
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            raise


def _resolve_hostname() -> Optional[str]:
    """
    v5.7.6: 7 متغيرات + fallback.
    """
    for var in (
        "RENDER_EXTERNAL_HOSTNAME",
        "RENDER_EXTERNAL_URL",
        "RAILWAY_PUBLIC_DOMAIN",
        "WEBHOOK_URL",
        "PUBLIC_URL",
        "BOT_HOSTNAME",
        "FLY_APP_NAME",
    ):
        val = (os.getenv(var) or "").strip()
        if not val:
            continue
        if val.startswith("http://") or val.startswith("https://"):
            try:
                n = urlparse(val).netloc
                if n:
                    return n
            except Exception:
                continue
        else:
            return val

    heroku_app = (os.getenv("HEROKU_APP_NAME") or "").strip()
    if heroku_app:
        return f"{heroku_app}.herokuapp.com"

    if _FALLBACK_HOSTNAME:
        logger.warning(
            "⚠️ لا hostname في env — استخدام fallback: %s",
            _FALLBACK_HOSTNAME,
        )
        return _FALLBACK_HOSTNAME

    return None


def _resolve_port() -> int:
    try:
        default_port = int(getattr(CONFIG, "WEB_PORT", None) or 10000)
    except (TypeError, ValueError):
        default_port = 10000
    raw = os.getenv("PORT")
    if raw is None or str(raw).strip() == "":
        return default_port
    try:
        port = int(str(raw).strip())
    except (TypeError, ValueError):
        logger.error("❌ PORT غير صالح (%r)", raw)
        return default_port
    if port < 1 or port > 65535:
        logger.error("❌ PORT خارج النطاق (%d)", port)
        return default_port
    return port


async def _watch_runner(runner, shutdown_event: asyncio.Event, port: int) -> None:
    try:
        try:
            await asyncio.sleep(3.0)
        except asyncio.CancelledError:
            raise
        site = None
        _addresses_available = False
        try:
            sites = getattr(runner, "sites", None)
            if sites:
                site = next(iter(sites))
        except Exception:
            pass
        try:
            addrs = getattr(runner, "addresses", None)
            if addrs is not None:
                _addresses_available = True
        except Exception:
            pass
        if site is None:
            if hasattr(runner, "site"):
                site = runner.site
            elif hasattr(runner, "_site"):
                site = runner._site
            elif hasattr(runner, "runner") and hasattr(runner.runner, "site"):
                site = runner.runner.site
            elif hasattr(runner, "_server"):
                site = runner
        if site is None and not _addresses_available:
            return
        probe_failures = 0
        health_url = f"http://127.0.0.1:{port}/health"
        _timeout = aiohttp.ClientTimeout(
            total=_WATCHER_HEALTH_TIMEOUT, connect=2
        )
        _connector = aiohttp.TCPConnector(
            limit=2, ttl_dns_cache=60, keepalive_timeout=30
        )
        async with aiohttp.ClientSession(
            timeout=_timeout, connector=_connector
        ) as session:
            while not shutdown_event.is_set():
                try:
                    if site is not None:
                        server = getattr(site, "_server", None)
                        if server is not None and (
                            server.sockets is None
                            or len(server.sockets) == 0
                        ):
                            shutdown_event.set()
                            return
                    if _addresses_available:
                        try:
                            addrs = getattr(runner, "addresses", None)
                            if addrs is not None and len(addrs) == 0:
                                shutdown_event.set()
                                return
                        except Exception:
                            pass
                    try:
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
                    except Exception:
                        probe_failures += 1
                        if probe_failures >= _WATCHER_MAX_PROBE_FAILURES:
                            shutdown_event.set()
                            return
                    await asyncio.sleep(_WATCHER_INTERVAL)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await asyncio.sleep(_WATCHER_INTERVAL)
    except asyncio.CancelledError:
        raise
    except Exception as _e:
        logger.debug("_watch_runner: %s", _e)


async def run_task_with_retry(task_func, *args, task_name=""):
    consecutive_failures = 0
    while True:
        try:
            await task_func(*args)
            consecutive_failures = 0
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            consecutive_failures += 1
            logger.error(
                "❌ Task %s crashed: %s", task_name, e, exc_info=True
            )
            delay = min(5 * consecutive_failures, 60)
            await asyncio.sleep(delay)


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
                for w in winners:
                    winner_id = w.get("winner_id")
                    if winner_id is None:
                        continue
                    try:
                        msg = (
                            f"🎉 <b>مبروك!</b>\n\nلقد فزت في مسابقة "
                            f"<b>{_html_escape(str(w.get('title') or 'مسابقة'))}"
                            f"</b>!"
                        )
                        await app.bot.send_message(
                            chat_id=winner_id, text=msg, parse_mode="HTML"
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
            raise
        except Exception as e:
            logger.error("❌ contest_cleanup: %s", e, exc_info=True)
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise


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


_polling_state = {"running": False}

_POLLING_CONFLICT_MAX_RETRIES = 12
_POLLING_CONFLICT_INITIAL_DELAY = 5.0
_POLLING_CONFLICT_MAX_DELAY = 60.0


async def _start_polling_mode(app: Application) -> None:
    """
    v5.7.6: retry مع backoff تصاعدي (12 محاولة).
    يحذف webhook في كل محاولة قبل start_polling.
    """
    if app.updater is None:
        raise RuntimeError("Polling mode يتطلب updater.")
    if _polling_state["running"]:
        raise RuntimeError("Application is already running!")

    _app_running = (
        getattr(app, "running", False)
        or getattr(app, "_running", False)
    )
    if not _app_running:
        raise RuntimeError(
            "app.running=False — يجب استدعاء app.start() قبل "
            "_start_polling_mode()"
        )

    try:
        webhook_info = await app.bot.get_webhook_info()
        if webhook_info and getattr(webhook_info, "url", None):
            logger.warning(
                "⚠️ POLLING: webhook موجود (%s) — حذفه",
                webhook_info.url,
            )
            await app.bot.delete_webhook(drop_pending_updates=True)
    except Exception as _e:
        logger.debug("webhook pre-check: %s", _e)

    _polling_state["running"] = True
    delay = _POLLING_CONFLICT_INITIAL_DELAY

    for attempt in range(1, _POLLING_CONFLICT_MAX_RETRIES + 1):
        try:
            await app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=ALLOWED_UPDATES,
            )
            logger.info(
                "✅ Polling started (attempt %d/%d)",
                attempt, _POLLING_CONFLICT_MAX_RETRIES,
            )
            await _run_post_init_hooks(app)
            return
        except Exception as e:
            err_lower = str(e).lower()
            is_conflict = "conflict" in err_lower

            if (not is_conflict
                    or attempt >= _POLLING_CONFLICT_MAX_RETRIES):
                _polling_state["running"] = False
                if is_conflict:
                    logger.error(
                        "🔴 POLLING CONFLICT (final): نسخة أخرى من "
                        "البوت تستخدم نفس الـ token.\n"
                        "🔧 الحل:\n"
                        "  1. افتح Render Dashboard\n"
                        "  2. تأكد من Web Service واحد فقط (لا Worker)\n"
                        "  3. أوقف النسخة القديمة يدوياً\n"
                        "  4. تأكد RENDER_EXTERNAL_HOSTNAME موجود\n"
                        "آخر خطأ: %s", str(e)[:200],
                    )
                raise

            logger.warning(
                "⚠️ POLLING CONFLICT (attempt %d/%d): %s — "
                "retry in %.0fs...",
                attempt, _POLLING_CONFLICT_MAX_RETRIES,
                str(e)[:200], delay,
            )

            try:
                await app.bot.delete_webhook(drop_pending_updates=True)
            except Exception:
                pass

            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                _polling_state["running"] = False
                raise

            delay = min(delay * 1.5, _POLLING_CONFLICT_MAX_DELAY)


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


async def _diag_incoming(update, context):
    try:
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat:
            return
        if chat.type not in ("group", "supergroup"):
            return
        logger.warning(
            "📥 INCOMING | chat=%s msg=%s | text=%s photo=%s",
            chat.id, msg.message_id,
            bool(getattr(msg, "text", None)),
            bool(getattr(msg, "photo", None)),
        )
    except Exception as _e:
        logger.debug("_diag_incoming error: %s", _e)


def _resolve_admin_guard(context) -> Set[int]:
    allowed = context.bot_data.get("admin_ids")
    if allowed:
        return allowed
    try:
        fallback: Set[int] = set()
        _pid = int(getattr(CONFIG, "PRIMARY_OWNER_ID", 0) or 0)
        if _pid:
            fallback.add(_pid)
        for _d in (getattr(CONFIG, "DEVELOPER_IDS", []) or []):
            try:
                _di = int(_d)
                if _di:
                    fallback.add(_di)
            except (TypeError, ValueError):
                continue
        return fallback
    except Exception:
        return set()


async def cmd_ping(update, context):
    user = update.effective_user
    if user is None:
        return
    allowed = _resolve_admin_guard(context)
    if not allowed or user.id not in allowed:
        return
    try:
        msg = update.effective_message
        if msg is None:
            return
        msg_date = getattr(msg, "date", None)
        age_ms = None
        if msg_date is not None:
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)
            age_ms = int(
                (datetime.now(timezone.utc) - msg_date).total_seconds()
                * 1000
            )
        t0 = time.monotonic()
        try:
            if _HAS_REPLY_PARAMETERS and ReplyParameters is not None:
                sent = await msg.reply_text(
                    "🏓 قياس...",
                    reply_parameters=ReplyParameters(
                        message_id=msg.message_id
                    ),
                )
            else:
                sent = await msg.reply_text(
                    "🏓 قياس...", reply_to_message_id=msg.message_id
                )
        except TypeError:
            sent = await msg.reply_text("🏓 قياس...")
        t1 = time.monotonic()
        send_rtt_ms = int((t1 - t0) * 1000)
        try:
            _BOT_METRICS["pings_total"] = int(
                _BOT_METRICS.get("pings_total") or 0
            ) + 1
            _BOT_METRICS["ping_sum_ms"] = int(
                _BOT_METRICS.get("ping_sum_ms") or 0
            ) + send_rtt_ms
            _cur_min = _BOT_METRICS.get("ping_min_ms")
            if _cur_min is None or send_rtt_ms < _cur_min:
                _BOT_METRICS["ping_min_ms"] = send_rtt_ms
            _cur_max = _BOT_METRICS.get("ping_max_ms")
            if _cur_max is None or send_rtt_ms > _cur_max:
                _BOT_METRICS["ping_max_ms"] = send_rtt_ms
        except Exception:
            pass
        lines = [
            "🏓 <b>Pong</b>", "",
            f"⚡ <b>Send API RTT:</b> <code>{send_rtt_ms}ms</code>"
        ]
        if age_ms is not None:
            lines.append(f"📥 <b>زمن الوصول:</b> <code>~{age_ms}ms</code>")
        if send_rtt_ms < 300:
            verdict = "🟢 ممتاز"
        elif send_rtt_ms < 500:
            verdict = "🟢 جيد جداً"
        elif send_rtt_ms < 800:
            verdict = "🟡 جيد"
        elif send_rtt_ms < 1500:
            verdict = "🟠 مقبول"
        else:
            verdict = "🔴 يحتاج تحسين"
        lines.append(f"\n<b>{verdict}</b>")
        try:
            await sent.edit_text("\n".join(lines), parse_mode='HTML')
        except Exception as _ee:
            logger.debug("ping edit_text: %s", _ee)
        logger.info(
            "🏓 /ping | user=%s | send=%dms | age=%sms",
            user.id, send_rtt_ms,
            age_ms if age_ms is not None else -1,
        )
    except Exception as e:
        logger.error("❌ /ping error: %s", e, exc_info=True)


async def cmd_posts_stats(update, context):
    """📊 إحصائيات النشر من DB مباشرة."""
    user = update.effective_user
    if user is None:
        return
    allowed = _resolve_admin_guard(context)
    if not allowed:
        logger.warning(
            "/posts_stats refused (fail-closed): no admin list. user=%s",
            user.id,
        )
        return
    if user.id not in allowed:
        return

    msg = update.effective_message
    if msg is None:
        return

    _db_type = getattr(DB, "DB_TYPE", "sqlite").lower()

    if _db_type == "postgres":
        _interval_24h = "NOW() - INTERVAL '24 hours'"
        _interval_15m = "NOW() - INTERVAL '15 minutes'"
        _info_schema_query = (
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'posts'"
        )
    elif _db_type == "mysql":
        _interval_24h = "NOW() - INTERVAL 24 HOUR"
        _interval_15m = "NOW() - INTERVAL 15 MINUTE"
        _info_schema_query = "SHOW COLUMNS FROM posts"
    else:
        _interval_24h = "datetime('now', '-24 hours')"
        _interval_15m = "datetime('now', '-15 minutes')"
        _info_schema_query = "PRAGMA table_info(posts)"

    async def _try_count(sql: str):
        try:
            row = await DB.fetchone(sql)
            if row is None:
                return 0, None
            if isinstance(row, dict):
                n = row.get('n') or 0
            else:
                try:
                    n = row[0]
                except (TypeError, IndexError):
                    n = 0
            return int(n or 0), None
        except Exception as _e:
            return None, f"{type(_e).__name__}: {str(_e)[:60]}"

    async def _get_posts_columns() -> Set[str]:
        try:
            rows = await DB.fetchall(_info_schema_query)
            cols: Set[str] = set()
            for r in rows:
                c = None
                rd = r if isinstance(r, dict) else None
                if rd is None:
                    try:
                        rd = dict(r)
                    except Exception:
                        rd = None
                if rd is not None:
                    c = (
                        rd.get('column_name') or rd.get('name')
                        or rd.get('Field') or rd.get('COLUMN_NAME')
                    )
                if c is None:
                    try:
                        c = r[1] if _db_type == "sqlite" else r[0]
                    except Exception:
                        c = None
                if c:
                    cols.add(str(c).lower())
            return cols
        except Exception as _e:
            logger.debug("_get_posts_columns: %s", _e)
            return set()

    posts_cols = await _get_posts_columns()
    lines = ["📊 <b>إحصائيات النشر</b>", ""]

    if not posts_cols:
        lines.append(f"⚠️ جدول <code>posts</code> غير موجود ({_db_type})")
        try:
            await msg.reply_text("\n".join(lines), parse_mode='HTML')
        except Exception:
            pass
        return

    cnt_total, _ = await _try_count("SELECT COUNT(*) AS n FROM posts")
    cnt_pub_at, _ = await _try_count(
        f"SELECT COUNT(*) AS n FROM posts "
        f"WHERE published_at IS NOT NULL AND created_at > {_interval_24h}"
    )
    cnt_p1, _ = await _try_count(
        f"SELECT COUNT(*) AS n FROM posts "
        f"WHERE published = 1 AND created_at > {_interval_24h}"
    )
    cnt_15m, _ = await _try_count(
        f"SELECT COUNT(*) AS n FROM posts "
        f"WHERE published_at IS NOT NULL AND published_at > {_interval_15m}"
    )

    lines.append(f"✅ total posts: <b>{cnt_total or 0}</b>")
    lines.append(f"✅ published_at (24h): <b>{cnt_pub_at or 0}</b>")
    lines.append(f"✅ published=1 (24h): <b>{cnt_p1 or 0}</b>")
    lines.append(f"✅ last 15m: <b>{cnt_15m or 0}</b>")

    uptime_s = int(
        time.monotonic() - _BOT_METRICS.get(
            "started_at", time.monotonic()
        )
    )
    _ps = _BOT_METRICS.get('posts_success', 0)
    _pf = _BOT_METRICS.get('posts_failed', 0)
    lines.append("")
    lines.append(f"⏱️ uptime: <code>{uptime_s}s</code>")
    lines.append(f"✅ posts_success: <code>{_ps}</code>")
    lines.append(f"❌ posts_failed: <code>{_pf}</code>")

    text = "\n".join(lines)
    try:
        await msg.reply_text(text, parse_mode='HTML')
    except Exception:
        pass


async def main():
    t_start = time.monotonic()
    _shutdown_event = asyncio.Event()

    def _on_shutdown_signal(sig_name: str):
        logger.info("🛑 تلقّيت %s — بدء الإغلاق", sig_name)
        _shutdown_event.set()

    try:
        _loop_for_signals = asyncio.get_running_loop()
        _signals_to_install = [signal.SIGTERM, signal.SIGINT]
        if hasattr(signal, "SIGHUP"):
            _signals_to_install.append(signal.SIGHUP)
        for _sig in _signals_to_install:
            try:
                _loop_for_signals.add_signal_handler(
                    _sig, lambda s=_sig: _on_shutdown_signal(s.name)
                )
            except (NotImplementedError, RuntimeError, ValueError) as _e:
                logger.debug(
                    "add_signal_handler(%s): %s", _sig.name, _e
                )
    except Exception as _e:
        logger.debug("Signal setup: %s", _e)

    # 🆕 v5.7.6 — قتل النسخة القديمة
    logger.info("🔪 FORCE-KILL-PREVIOUS: بدء الفحص...")
    try:
        _killed = await _force_kill_previous_instance()
        if _killed > 0:
            logger.warning(
                "🔪 قتلت %d نسخة قديمة — انتظار Telegram release...",
                _killed,
            )
    except Exception as _e:
        logger.warning("⚠️ فشل قتل النسخة القديمة: %s", _e)

    if _MARK_PROCESS_START_FN is not None:
        try:
            _MARK_PROCESS_START_FN()
            logger.info("🕐 mark_process_start() — نافذة 60s")
        except Exception as _e:
            logger.debug("mark_process_start: %s", _e)

    try:
        CONFIG.validate()
    except ValueError as e:
        logger.error("❌ %s", e)
        raise SystemExit(1)

    bot_token = _get_bot_token()
    if not bot_token:
        logger.error("❌ BOT_TOKEN غير محدّد")
        raise SystemExit(1)

    logger.info("🌿 %s", CONFIG.BOT_NAME)
    logger.info("👨‍💼 المالك: %s", CONFIG.PRIMARY_OWNER_ID)

    logger.info(
        "📦 bot.py: v5.7.6 | kill_prev=on | "
        "detectors=%s | layers=%d | "
        "db_idle=%s | cache_stats=%s | analytics=%s | "
        "fullhealth=%s | latency=%s | maint_cmds=%s | "
        "analytics_register=%s | autotune_available=%s | "
        "files_cmd=on | gil_quiet=on | warmup_blocking=on | "
        "gc_collect=on | fallback_hostname=%s",
        _SPAM_DETECTOR_VERSION or "N/A",
        _SPAM_DETECTOR_LAYERS_COUNT,
        "yes" if _HAS_DB_IDLE_CMD else "no",
        "yes" if _HAS_CACHE_STATS_CMD else "no",
        "yes" if _ANALYTICS_HANDLERS_AVAILABLE else "no",
        "yes" if _cmd_fullhealth is not None else "no",
        "yes" if _cmd_latency is not None else "no",
        "yes" if _MAINT_CMDS_AVAILABLE else "no",
        "yes" if _ANALYTICS_REGISTER_AVAILABLE else "no",
        "yes" if _AUTOTUNE_AVAILABLE else "no",
        _FALLBACK_HOSTNAME or "none",
    )

    if not _verify_command_handlers():
        logger.error("❌ دوال الأوامر — الخروج")
        raise SystemExit(1)
    if not _verify_db_config():
        logger.error("❌ إعدادات DB — الخروج")
        raise SystemExit(1)

    t0 = time.monotonic()
    if hasattr(DB, 'pre_initialize'):
        await DB.pre_initialize()
    else:
        await initialize_db()
    logger.info(
        "⏱️ DB init: %.2fs", time.monotonic() - t0
    )

    try:
        if hasattr(DB, "migrate_reminders_columns"):
            await DB.migrate_reminders_columns()
    except Exception as _e:
        logger.warning("⚠️ migrate_reminders_columns: %s", _e)

    for dev_id in CONFIG.DEVELOPER_IDS:
        try:
            await DB.register_user(dev_id)
        except Exception as e:
            logger.error("❌ register dev %s: %s", dev_id, e)
    try:
        await DB.register_user(CONFIG.PRIMARY_OWNER_ID)
    except Exception as e:
        logger.error("❌ register owner: %s", e)

    t1 = time.monotonic()
    KeyboardFactory.load_config()
    available_langs = TranslationManager.get_available_languages()
    for lang in available_langs:
        TranslationManager.load_translation(lang)
    logger.info(
        "✅ %d لغة محمّلة في %.2fs",
        len(available_langs), time.monotonic() - t1,
    )

    t_warmup = time.monotonic()
    try:
        await warmup_all()
        logger.info(
            "⏱️ Warmup: %.2fs", time.monotonic() - t_warmup
        )
    except Exception as e:
        logger.warning("⚠️ Warmup: %s", e, exc_info=True)

    port = _resolve_port()
    hostname = _resolve_hostname()

    if hostname:
        logger.info(
            "🌐 WEBHOOK mode (hostname=%s) — آمن ضد تكرار instances",
            hostname,
        )
    else:
        logger.warning(
            "⚠️ POLLING mode (لا hostname) — يتطلب instance واحد فقط"
        )

    t_app = time.monotonic()
    _http_request_pool = _build_http_request_pool()

    _app_builder = Application.builder().token(bot_token)
    if _http_request_pool is not None:
        _app_builder = (
            _app_builder
            .request(_http_request_pool)
            .get_updates_request(_http_request_pool)
        )
        logger.info("🚀 HTTPXRequest pool=32")

    app = _app_builder.build()
    app.bot_data['start_time'] = time.monotonic()

    # 🆕 v5.7.6 — انتظار Telegram release قبل initialize
    if hostname:
        logger.info("⏳ انتظار Telegram release (webhook mode)...")
        await _wait_for_telegram_release()

    await app.initialize()
    logger.info(
        "⏱️ App init: %.2fs", time.monotonic() - t_app
    )

    try:
        await app.start()
        logger.info("✅ app.start()")
    except RuntimeError as _e:
        if "already running" in str(_e).lower():
            logger.debug("app.start(): running already")
        else:
            raise

    try:
        _BOT_METRICS["started_at"] = time.monotonic()
    except Exception:
        pass

    _tg_warm_ok = await _warmup_telegram_api(app)
    if not _tg_warm_ok:
        logger.info("ℹ️ Telegram API warmup لم ينجح — متابعة")

    _spawn_warmup_detectors_pool()

    if _HAS_WARMUP_DETECTORS and _warmup_detectors_pool_fn is not None:
        try:
            logger.info(
                "🔥 warmup_detectors_pool: blocking (prevents 13s lag)..."
            )
            _warm_t0 = time.monotonic()
            _warm_result = await asyncio.wait_for(
                _warmup_detectors_pool_fn(), timeout=30.0
            )
            _warm_elapsed = time.monotonic() - _warm_t0
            if _warm_result:
                logger.info(
                    "✅ detectors pool ready in %.1fs", _warm_elapsed
                )
            else:
                logger.warning(
                    "⚠️ detectors pool False (%.1fs) — lazy", _warm_elapsed
                )
        except asyncio.TimeoutError:
            logger.warning("⚠️ detectors warmup timeout (30s)")
        except asyncio.CancelledError:
            raise
        except Exception as _we:
            logger.warning("⚠️ detectors warmup error: %s", _we)

    try:
        import gc as _gc_t
        _gc_t.collect()
        logger.info("🧹 gc.collect() — memory baseline")
    except Exception:
        pass

    _managed_apps: Dict[str, Any] = {}
    try:
        from managed_bots_runner import start_all_managed_bots
        _managed_apps = await start_all_managed_bots()
        logger.info(
            "✅ managed_bots: %d/%d",
            sum(1 for ok in _managed_apps.values() if ok),
            len(_managed_apps),
        )
    except Exception as _mb_e:
        logger.error("❌ managed_bots: %s", _mb_e, exc_info=True)

    _spawn_gil_lag_monitor()

    try:
        _register_message_shutdown(app)
        logger.info("✅ message shutdown handlers مسجّلة")
    except Exception as _e:
        logger.debug("register_message_shutdown: %s", _e)

    if _GROUP_LOG_INIT_AVAILABLE and _GROUP_LOG_AVAILABLE:
        _init_group_log_instance(app)

    for _scope_name, _scope in (
        ("Default", BotCommandScopeDefault()),
        ("AllPrivateChats", BotCommandScopeAllPrivateChats()),
        ("AllGroupChats", BotCommandScopeAllGroupChats()),
    ):
        try:
            await app.bot.delete_my_commands(scope=_scope)
        except Exception:
            pass

    try:
        await app.bot.set_my_commands(
            PUBLIC_COMMANDS,
            scope=BotCommandScopeAllPrivateChats(),
        )
        logger.info("✅ %d أمراً عاماً", len(PUBLIC_COMMANDS))
    except Exception as _e:
        logger.error("❌ فشل الأوامر العامة: %s", _e)

    try:
        await app.bot.set_my_commands(
            GROUP_COMMANDS,
            scope=BotCommandScopeAllGroupChats(),
        )
        logger.info("✅ %d أمراً للمجموعات", len(GROUP_COMMANDS))
    except Exception as _e:
        logger.error("❌ فشل أوامر المجموعات: %s", _e)

    _admin_ids = await _collect_admin_ids()
    _admin_full_list = PUBLIC_COMMANDS + ADMIN_COMMANDS
    logger.info("👥 الأدمن المُكتشفون: %d", len(_admin_ids))
    app.bot_data["admin_ids"] = set(_admin_ids)

    for _admin_id in _admin_ids:
        try:
            await app.bot.set_my_commands(
                _admin_full_list,
                scope=BotCommandScopeChat(chat_id=_admin_id),
            )
        except Exception as _e:
            logger.warning("⚠️ فشل أوامر الأدمن %s: %s", _admin_id, _e)

    _group_msg_filter = (
        _GROUP_CHAT_FILTER
        & filters.UpdateType.MESSAGE
        & ~filters.COMMAND
    )

    try:
        _handle_group_timed = _wrap_handler_with_timing(
            MessageHandlers.handle_group, "handle_group"
        )
        app.add_handler(
            MessageHandler(_group_msg_filter, _handle_group_timed),
            group=-1,
        )
        logger.info("✅ handle_group [timed]")
    except Exception as _e:
        logger.error("❌ handle_group: %s", _e, exc_info=True)

    if hasattr(MessageHandlers, "handle_edited"):
        try:
            _handle_edited_timed = _wrap_handler_with_timing(
                MessageHandlers.handle_edited, "handle_edited"
            )
            app.add_handler(
                MessageHandler(
                    _GROUP_CHAT_FILTER
                    & filters.UpdateType.EDITED_MESSAGE,
                    _handle_edited_timed,
                ),
                group=-1,
            )
            logger.info("✅ handle_edited [timed]")
        except Exception as _e:
            logger.error("❌ handle_edited: %s", _e, exc_info=True)

    try:
        _handle_service_timed = _wrap_handler_with_timing(
            MessageHandlers.handle_service, "handle_service"
        )
        app.add_handler(
            MessageHandler(
                filters.StatusUpdate.ALL & _GROUP_CHAT_FILTER,
                _handle_service_timed,
            ),
            group=-1,
        )
        logger.info("✅ handle_service [timed]")
    except Exception as _e:
        logger.error("❌ handle_service: %s", _e, exc_info=True)

    # Public commands
    for _name, _fn in (
        ("start", CommandHandlers.start),
        ("help", CommandHandlers.help_command),
        ("trial", CommandHandlers.trial),
        ("subscribe", CommandHandlers.subscribe),
        ("support", CommandHandlers.support),
        ("developer", CommandHandlers.developer),
        ("stats", CommandHandlers.stats),
        ("language", CommandHandlers.language),
        ("contests", CommandHandlers.contests),
        ("replies", CommandHandlers.replies_command),
        ("grant", CommandHandlers.grant),
        ("set_min_interval", CommandHandlers.set_min_interval),
        ("gift_plans", CommandHandlers.gift_plans),
        ("redeem_gift", CommandHandlers.redeem_gift),
        ("syncgroup", CommandHandlers.syncgroup),
        ("security", CommandHandlers.security),
        ("panel", CommandHandlers.panel),
        ("lock", CommandHandlers.lock),
        ("unlock", CommandHandlers.unlock),
        ("ban", CommandHandlers.ban),
        ("mute", CommandHandlers.mute),
        ("warn", CommandHandlers.warn),
        ("kick", CommandHandlers.kick),
        ("restrict", CommandHandlers.restrict),
        ("unban", CommandHandlers.unban),
        ("pin", CommandHandlers.pin),
        ("register_hidden_owner", CommandHandlers.register_hidden_owner),
        ("remove_hidden_owner", CommandHandlers.remove_hidden_owner),
        ("add_hidden_admin", CommandHandlers.add_hidden_admin),
        ("remove_hidden_admin", CommandHandlers.remove_hidden_admin),
        ("list_hidden_admins", CommandHandlers.list_hidden_admins),
        ("mood", CommandHandlers.mood),
        ("admin", CommandHandlers.admin),
        ("broadcast", CommandHandlers.broadcast),
        ("set_force", CommandHandlers.set_force),
        ("set_update_ch", CommandHandlers.set_update_ch),
        ("set_log_ch", CommandHandlers.set_log_ch),
        ("add_admin", CommandHandlers.add_admin),
        ("remove_admin", CommandHandlers.remove_admin),
        ("export_replies", CommandHandlers.export_replies),
        ("import_replies", CommandHandlers.import_replies),
        ("backup", CommandHandlers.backup),
        ("restore", CommandHandlers.restore),
        ("auto_publish", CommandHandlers.auto_publish),
        ("auto_recycle", CommandHandlers.auto_recycle),
        ("channels", CommandHandlers.channels),
        ("posts", CommandHandlers.posts),
        ("db_diag", CommandHandlers.db_diag),
        ("db_vacuum", CommandHandlers.db_vacuum),
    ):
        try:
            app.add_handler(CommandHandler(_name, _fn))
        except Exception as _e:
            logger.warning("⚠️ register /%s: %s", _name, _e)

    if _admin_ids:
        try:
            app.add_handler(CommandHandler(
                "ping", cmd_ping, filters=filters.User(_admin_ids)
            ))
        except Exception:
            app.add_handler(CommandHandler("ping", cmd_ping))
    else:
        app.add_handler(CommandHandler("ping", cmd_ping))

    if _admin_ids:
        try:
            app.add_handler(CommandHandler(
                "posts_stats", cmd_posts_stats,
                filters=filters.User(_admin_ids)
            ))
        except Exception:
            app.add_handler(CommandHandler("posts_stats", cmd_posts_stats))
    else:
        app.add_handler(CommandHandler("posts_stats", cmd_posts_stats))

    try:
        app.add_handler(CommandHandler(
            "autoblocked", _handle_autoblocked_command
        ))
    except Exception as _e:
        logger.warning("⚠️ /autoblocked: %s", _e)

    if _HAS_DB_IDLE_CMD and _handle_db_idle_command is not None:
        try:
            app.add_handler(CommandHandler(
                "db_idle", _handle_db_idle_command
            ))
        except Exception as _e:
            logger.warning("⚠️ /db_idle: %s", _e)

    if _HAS_CACHE_STATS_CMD and _handle_cache_stats_command is not None:
        try:
            app.add_handler(CommandHandler(
                "cache_stats", _handle_cache_stats_command
            ))
        except Exception as _e:
            logger.warning("⚠️ /cache_stats: %s", _e)

    if _cmd_fullhealth is not None:
        try:
            app.add_handler(CommandHandler(
                "fullhealth", _cmd_fullhealth
            ))
        except Exception as _e:
            logger.warning("⚠️ /fullhealth: %s", _e)

    if _cmd_latency is not None:
        try:
            app.add_handler(CommandHandler(
                "latency", _cmd_latency
            ))
        except Exception as _e:
            logger.warning("⚠️ /latency: %s", _e)

    if hasattr(MessageHandlers, "handle_cancel"):
        try:
            app.add_handler(
                CommandHandler("cancel", MessageHandlers.handle_cancel),
                group=1,
            )
        except Exception:
            pass

    if _MAINT_CMDS_AVAILABLE and callable(register_maintenance_commands):
        try:
            register_maintenance_commands(app)
        except Exception as _e:
            logger.error("❌ db_maintenance_commands: %s", _e, exc_info=True)

    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(
        filters.SUCCESSFUL_PAYMENT & filters.ChatType.PRIVATE,
        successful_payment,
    ))

    try:
        register_channels_list_handlers(app)
    except Exception as e:
        logger.error("❌ [1/6] channels_list: %s", e, exc_info=True)

    if _NAV_FIX_AVAILABLE and callable(register_nav_fix):
        try:
            register_nav_fix(app)
        except Exception as e:
            logger.error("❌ [2/6] NAV_FIX: %s", e, exc_info=True)

    if _CH_DELETE_AVAILABLE and callable(register_delete_confirmation):
        try:
            register_delete_confirmation(app)
        except Exception as _e:
            logger.error("❌ [3/6] channels_delete: %s", _e, exc_info=True)

    if _GROUP_LOG_AVAILABLE:
        try:
            register_group_log_handlers(app)
        except Exception as e:
            logger.error("❌ [4/6] group_log: %s", e, exc_info=True)

    _analytics_registered = False
    if (_ANALYTICS_REGISTER_AVAILABLE
            and callable(_register_analytics_handlers)):
        try:
            if _register_analytics_handlers(app):
                _analytics_registered = True
                logger.info("✅ [5/6] handlers_analytics")
        except Exception as _e:
            logger.error("❌ [5/6] analytics: %s", _e, exc_info=True)

    if not _analytics_registered:
        if (_ANALYTICS_HANDLERS_AVAILABLE
                and _show_analytics_menu is not None
                and _handle_analytics_callback is not None):
            try:
                app.add_handler(CallbackQueryHandler(
                    _show_analytics_menu,
                    pattern=r"^admin_analytics$",
                ))
                app.add_handler(CallbackQueryHandler(
                    _handle_analytics_callback,
                    pattern=(
                        r"^(growth_30d_btn|top_channels_btn|"
                        r"publish_stats_btn|channels_rate_btn|"
                        r"subscriptions_btn|pool_live_btn|"
                        r"slow_queries_btn|export_excel_btn|"
                        r"full_health_btn|latency_btn|"
                        r"databases_btn|autotune_btn|files_btn|"
                        r"refresh_btn)$"
                    ),
                ))
            except Exception as _e:
                logger.error("❌ [5/6] analytics fallback: %s", _e)

    try:
        from handlers.handlers_managed_bots import (
            register_managed_bots_handlers,
        )
        register_managed_bots_handlers(app)
    except Exception as _mb_e:
        logger.error("❌ [5.5/6] managed_bots: %s", _mb_e)

    try:
        app.add_handler(CallbackQueryHandler(CallbackHandlers.handle))
        logger.info("✅ [6/6] CallbackHandlers.handle")
    except Exception as _e:
        logger.error("❌ [6/6] callback: %s", _e, exc_info=True)

    try:
        _handle_private_timed = _wrap_handler_with_timing(
            MessageHandlers.handle_private, "handle_private"
        )
        app.add_handler(MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.VIDEO
             | filters.Document.ALL | filters.AUDIO | filters.VOICE
             | filters.ANIMATION | filters.Sticker.ALL
             | filters.VIDEO_NOTE) &
            filters.ChatType.PRIVATE & ~filters.COMMAND
            & ~filters.SUCCESSFUL_PAYMENT,
            _handle_private_timed
        ))
        logger.info("✅ handle_private [timed]")
    except Exception as _e:
        logger.error("❌ handle_private: %s", _e, exc_info=True)

    app.add_handler(ChatJoinRequestHandler(
        MessageHandlers.handle_join_request
    ))
    app.add_error_handler(ErrorHandler.handle_error)

    try:
        chat_member.register(app)
    except Exception as _e:
        logger.error("❌ ChatMemberHandler: %s", _e, exc_info=True)

    if _MEMBERSHIP_AVAILABLE and callable(register_membership_handlers):
        try:
            register_membership_handlers(app)
        except Exception as _e:
            logger.error("❌ MembershipHandler: %s", _e, exc_info=True)

    tasks: List[asyncio.Task] = []
    _bg_task_specs: List[Tuple[str, Any, tuple]] = [
        ("keep_alive", keep_alive, ()),
        ("auto_publish", BackgroundTasks.auto_publish, (app.bot,)),
        ("auto_backup", BackgroundTasks.auto_backup, ()),
        ("reminders", BackgroundTasks.reminders, (app.bot,)),
        ("heartbeat", BackgroundTasks.heartbeat, (app.bot,)),
        ("flush_usage", BackgroundTasks.flush_usage_periodically, ()),
        ("expire_subscriptions",
         BackgroundTasks.expire_subscriptions, ()),
        ("sync_admins", BackgroundTasks.sync_admins_periodically,
         (app.bot,)),
        ("expire_penalties",
         BackgroundTasks.expire_penalties_periodically, ()),
        ("cleanup_old_data", BackgroundTasks.cleanup_old_data, ()),
        ("cache_cleanup", cache_cleanup_task, ()),
        ("cleanup_locks", cleanup_locks, ()),
        ("periodic_cleanup",
         GroupRateLimiterManager.periodic_cleanup_task, ()),
        ("monitor_pool_alert",
         BackgroundTasks.monitor_pool_alert, (app.bot,)),
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
        tasks.append(asyncio.create_task(
            run_task_with_retry(
                _maintenance_loop, app.bot, owner_id,
                task_name="maintenance",
            )
        ))

    logger.info("✅ %d مهمة خلفية", len(tasks))

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
            await _run_post_init_hooks(app)

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://127.0.0.1:{port}/health"
                    ) as resp:
                        await resp.read()
                logger.info("🔥 تم تسخين الخادم")
            except Exception:
                pass

            watcher_task = None
            try:
                watcher_task = asyncio.create_task(
                    _watch_runner(runner, _shutdown_event, port)
                )
                await _shutdown_event.wait()
                logger.info("📴 إغلاق...")
            finally:
                if watcher_task is not None:
                    watcher_task.cancel()
                    try:
                        await watcher_task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        pass
                try:
                    await _run_post_stop_hooks(app)
                except Exception:
                    pass
                try:
                    await runner.cleanup()
                except Exception:
                    pass
        else:
            logger.info("⚠️ POLLING mode")
            runner = await setup_webhook(app, port)
            try:
                await _start_polling_mode(app)
                logger.info("✅ Polling started")
                await _shutdown_event.wait()
                logger.info("📴 إغلاق...")
            finally:
                try:
                    await _stop_polling_mode(app)
                except Exception:
                    pass
                try:
                    await runner.cleanup()
                except Exception:
                    pass

    finally:
        try:
            await _shutdown_group_log()
        except Exception:
            pass

        if _NOTIFY_TASKS:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *_NOTIFY_TASKS, return_exceptions=True
                    ),
                    timeout=_NOTIFY_SHUTDOWN_TIMEOUT,
                )
            except asyncio.TimeoutError:
                for _t in list(_NOTIFY_TASKS):
                    _t.cancel()
            except asyncio.CancelledError:
                raise

        if (_WARMUP_DETECTORS_TASK is not None
                and not _WARMUP_DETECTORS_TASK.done()):
            try:
                _WARMUP_DETECTORS_TASK.cancel()
                try:
                    await _WARMUP_DETECTORS_TASK
                except Exception:
                    pass
            except Exception:
                pass

        if (_GIL_LAG_MONITOR_TASK is not None
                and not _GIL_LAG_MONITOR_TASK.done()):
            try:
                _GIL_LAG_MONITOR_TASK.cancel()
                try:
                    await _GIL_LAG_MONITOR_TASK
                except Exception:
                    pass
            except Exception:
                pass

        for t in tasks:
            if not t.done():
                t.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=_BG_TASKS_SHUTDOWN_TIMEOUT,
            )
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            raise

        if _MAINT_CMDS_AVAILABLE and callable(stop_weekly_diagnostic_task):
            try:
                await stop_weekly_diagnostic_task(timeout=3.0)
            except Exception:
                pass

        if _MAINT_CMDS_AVAILABLE and callable(stop_auto_vacuum_task):
            try:
                await stop_auto_vacuum_task(timeout=3.0)
            except Exception:
                pass

        try:
            await _shutdown_detector_tasks(timeout=3.0)
        except Exception:
            pass

        try:
            await _shutdown_log_dispatcher(timeout=5.0)
        except Exception:
            pass
        try:
            await _shutdown_delete_tasks(timeout=3.0)
        except Exception:
            pass

        if _sleep_probe_available:
            try:
                from sleep_probe import (
                    uninstall_sleep_probe as _sp_uninstall
                )
                _sp_uninstall()
            except Exception:
                pass

        if not app_shutdown_done:
            try:
                if getattr(app, "running", False):
                    try:
                        await app.stop()
                    except Exception:
                        pass
            except Exception:
                pass

            try:
                await app.shutdown()
                app_shutdown_done = True
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

        try:
            from managed_bots_runner import stop_all_managed_bots
            await stop_all_managed_bots(timeout=15.0)
        except Exception as _mb_e:
            logger.warning("⚠️ managed_bots shutdown: %s", _mb_e)

        try:
            await _shutdown_db_pool(timeout=5.0)
        except Exception:
            pass

        _remove_pid_file()

    logger.info(
        "👋 انتهت دورة حياة البوت (%.2fs)",
        time.monotonic() - t_start,
    )


if __name__ == "__main__":
    _loop = None
    try:
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)

        if _DETECTORS_HAS_INSTALL_HELPER:
            logger.info(
                "ℹ️ v5.6.44: detectors pool منفصل — "
                "يقلل lag p90 من ~372ms إلى <100ms"
            )

        _loop.run_until_complete(main())

    except KeyboardInterrupt:
        logger.info("\n👋 تم الإيقاف")
    except Exception as e:
        logger.error("❌ خطأ: %s", e, exc_info=True)
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
                        "⏳ إلغاء %d مهمة معلّقة...", len(pending)
                    )
                    for _t in pending:
                        _t.cancel()
                    try:
                        _loop.run_until_complete(
                            asyncio.gather(
                                *pending, return_exceptions=True
                            )
                        )
                    except Exception:
                        pass

                try:
                    if _DETECTORS_HAS_SHUTDOWN_HELPER:
                        _result = None
                        try:
                            _result = _shutdown_default_executor_fn(_loop)
                        except TypeError:
                            try:
                                _result = _shutdown_default_executor_fn()
                            except TypeError:
                                _result = _shutdown_default_executor_fn(
                                    timeout=5.0
                                )
                        if asyncio.iscoroutine(_result):
                            _loop.run_until_complete(_result)
                    elif callable(_shutdown_detector_pool_fn):
                        _shutdown_detector_pool_fn()
                except Exception:
                    pass

                try:
                    _loop.run_until_complete(_loop.shutdown_asyncgens())
                except Exception:
                    pass

                try:
                    _loop.close()
                    logger.info("✅ event loop closed")
                except Exception:
                    pass
            except Exception:
                pass