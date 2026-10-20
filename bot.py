#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌿 Relax Manager – البوت الرئيسي (bot.py v5.7.4-GIL-DIAGNOSTICS)
================================================================================
📌 نقطة الدخول الرسمية للتطبيق (entrypoint).

🆕 v5.7.4 (GIL-DIAGNOSTICS):
    🟢 _wrap_handler_with_timing: يكشف الـ handlers البطيئة (> 2s) تلقائياً.
    🟢 _active_handler tracker: يسجّل الـ handler النشط عند GIL lag.
    🟢 GIL monitor محسّن: تاريخ 60s + p50/p90/p99/max + suspect attribution.
    🟢 _resolve_hostname محسّن: يجرّب متغيرات بيئة أكثر.
    🟢 beacon محدّث: v5.7.4 + العلامات الجديدة.

🆕 v5.7.3 (AUTOTUNE-INTEGRATION):
    🟢 ADMIN_COMMANDS + autotune, db_tune, analytics, versions, analytics_reset.
    🟢 _AUTOTUNE_AVAILABLE للـ beacon.

🆕 v5.7.2 (FIX-ACTIVE-CHANNELS-SCOPE):
    🟢 إصلاح NameError في _active_channels.

🆕 v5.7.1 (STATS-CHANNELS-FIX):
    🟢 حساب معدل النشر المتوقع بناءً على عدد القنوات النشطة.

🆕 v5.7.0 (MANAGED-BOTS-INTEGRATION):
    3 hooks جراحية — دون أي تعديل على منطق v5.6.44.
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
            "cannot establish 'bot' alias. posts_success may stay 0.",
            file=sys.stderr,
        )
    elif _existing_bot is None:
        sys.modules['bot'] = _main_mod
        print(
            "🔗 FIX-RECORD-METRIC-MODULE: sys.modules['bot'] = __main__ "
            "(early alias established)",
            file=sys.stderr,
        )
    elif _existing_bot is not _main_mod:
        print(
            "🔴 FIX-RECORD-METRIC-MODULE FAILED: "
            "sys.modules['bot'] already exists as a SEPARATE module "
            "(an eager 'from bot import ...' happened before this line). "
            "posts_success will stay 0. "
            "Investigate which module imports 'bot' at import-time.",
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

# 🆕 v5.7.3 — كشف توفر auto-tuning من db_diagnostics v7.2.24+
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
                f"مفقودة (v1.1.1 أقدم؟). {_e_an1} | {_e_an2}"
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
# warmup_detectors_pool (optional)
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
# /db_idle
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

# ═════════════════════════════════════════════════════════════════════
# /cache_stats
# ═════════════════════════════════════════════════════════════════════
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
        logger.info("ℹ️ db_diagnostics: غير متاح — %s", _DB_DIAG_IMPORT_ERROR or "module missing")
        return
    if _MARK_PROCESS_START_FN is not None:
        logger.info("✅ db_diagnostics: v%s متاح | mark_process_start ✅", _DB_DIAG_VERSION)
    else:
        logger.warning("⚠️ db_diagnostics: v%s محمّل لكن بلا mark_process_start", _DB_DIAG_VERSION)
    if _AUTOTUNE_AVAILABLE:
        logger.info("⚙️ auto-tuning: ✅ متاح (ensure_autovacuum_tuning)")
    else:
        logger.info(
            "⚙️ auto-tuning: ℹ️ غير متاح (يتطلب db_diagnostics v7.2.24+)"
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
    _PM_SLOW_QUERY_WARN_MS = float(os.getenv("PM_SLOW_QUERY_WARN_MS", "250"))
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
_GIL_LAG_SAMPLES_MAX = 300              # 🆕 v5.7.4: 300 samples (30s)
_GIL_LAG_HISTORY_WINDOW_SEC = 60.0      # 🆕 v5.7.4
_GIL_LAG_WARN_MS = 50.0
_GIL_LAG_ALERT_INTERVAL_SEC = 5.0
_GIL_LAG_BLOCKED_CUMULATIVE_WARN_MS = 5000.0  # 🆕 v5.7.4
_HANDLER_SLOW_WARN_MS = 2000.0          # 🆕 v5.7.4

# 🆕 v5.7.4 — tracking handler النشط
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

# ═══════════════════════════════════════════════════════════════════
# 🆕 v5.7.4 — Handler timing wrapper (يكشف الـ handlers البطيئة)
# ═══════════════════════════════════════════════════════════════════

def _wrap_handler_with_timing(
    handler: Callable,
    name: str,
) -> Callable:
    """
    يلفّ handler بـ timer — يسجّل تنبيه إذا تجاوز _HANDLER_SLOW_WARN_MS.
    يسجّل أيضاً اسم الـ handler النشط في _ACTIVE_HANDLER (لـ GIL monitor).
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
                if elapsed_ms >= _HANDLER_SLOW_WARN_MS:
                    logger.warning(
                        "🐌 SLOW handler: %s took %.0fms | chat=%s",
                        name, elapsed_ms, _ACTIVE_HANDLER.get("chat_id"),
                    )
                elif elapsed_ms >= 500.0:
                    logger.info(
                        "⏱️ handler %s: %.0fms", name, elapsed_ms,
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
                    logger.debug("notify_dev_log task failed: %s", t.exception())
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
        logger.warning("⚠️ فشل إنشاء task تسخين detectors: %s", _e, exc_info=True)
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
        result = await asyncio.wait_for(_WARMUP_DETECTORS_TASK, timeout=timeout)
        return bool(result)
    except asyncio.TimeoutError:
        logger.warning("⚠️ warmup_detectors_pool: لم ينتهِ خلال %.1fs", timeout)
        return False
    except asyncio.CancelledError:
        raise
    except Exception as _e:
        logger.debug("warmup_detectors_pool: %s", _e)
        return False

async def _gil_lag_monitor() -> None:
    """
    v5.7.4: نسخة محسّنة.
      - تاريخ 60s (قائمة انزلاقية)
      - يحسب p50/p90/p99/max
      - عند lag > warn: يعرض الـ handler النشط
      - إنبّه إذا التراكم > 5s خلال النافذة
    """
    logger.info("🔍 GIL-MONITOR: بدء المراقبة (window=%.0fs)",
                _GIL_LAG_HISTORY_WINDOW_SEC)
    history: List[Tuple[float, float]] = []  # (ts, lag_ms)
    last_alert_ts = 0.0
    cumulative_blocked_ms = 0.0

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

                logger.warning(
                    "🔴 GIL-MONITOR: lag=%.0fms | "
                    "p50=%.0fms p90=%.0fms p99=%.0fms max=%.0fms | "
                    "active=%s (%.1fs, chat=%s) | "
                    "cum=%.0fms/%.0fs",
                    lag_ms, p50, p90, p99, maxv,
                    active_name, active_elapsed,
                    active_chat or "-",
                    cumulative_blocked_ms, _GIL_LAG_HISTORY_WINDOW_SEC,
                )

                if cumulative_blocked_ms > _GIL_LAG_BLOCKED_CUMULATIVE_WARN_MS:
                    logger.error(
                        "🚨 GIL-MONITOR: تراكم %.0fms خلال %.0fs — "
                        "المشكلة منهجية (sync code؟ OCR؟ backup؟)",
                        cumulative_blocked_ms, _GIL_LAG_HISTORY_WINDOW_SEC,
                    )
                    cumulative_blocked_ms = 0.0
        except asyncio.CancelledError:
            logger.info("🛑 GIL-MONITOR: تم الإيقاف")
            raise
        except Exception as _e:
            logger.debug("GIL-MONITOR error: %s", _e)

def _spawn_gil_lag_monitor() -> Optional[asyncio.Task]:
    global _GIL_LAG_MONITOR_TASK
    if (_GIL_LAG_MONITOR_TASK is not None and not _GIL_LAG_MONITOR_TASK.done()):
        return _GIL_LAG_MONITOR_TASK
    try:
        _GIL_LAG_MONITOR_TASK = asyncio.create_task(_gil_lag_monitor(), name="gil-lag-monitor")
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
            request = HTTPXRequest(connection_pool_size=32)
            return request
        except Exception as _e:
            return None
    except Exception as _e:
        return None

async def _warmup_telegram_api(app: Application) -> bool:
    t_warm = time.monotonic()
    try:
        me = await asyncio.wait_for(app.bot.get_me(), timeout=_TG_WARMUP_TIMEOUT)
        elapsed_ms = (time.monotonic() - t_warm) * 1000
        if me is not None:
            logger.info("✅ Telegram API: اتصال مُهيَّأ — @%s", getattr(me, "username", "?"))
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
        logger.info("🛡️ Spam Detector: ✅ محمّل (%s, %d layers)", _SPAM_DETECTOR_VERSION, _SPAM_DETECTOR_LAYERS_COUNT)
    else:
        logger.warning("⚠️ Spam Detector: ❌ غير محمّل — %s", _SPAM_DETECTOR_IMPORT_ERROR)

def _log_security_bridge_status() -> None:
    if _SECURITY_BRIDGE_AVAILABLE:
        logger.info("🌉 Security Bridge: ✅ محمّل")
    else:
        logger.warning("⚠️ Security Bridge: غير متاح — %s", _SB_IMPORT_ERROR)

def _log_perf_tuning_status() -> None:
    try:
        _max_ch = getattr(CONFIG, "MAX_CHANNELS_PER_CYCLE", "?")
        _slow_q = getattr(CONFIG, "SLOW_QUERY_LOG_THRESHOLD", "?")
        _stmt_to = getattr(CONFIG, "PG_STATEMENT_TIMEOUT_MS", "?")
        _pool_size = getattr(CONFIG, "DB_POOL_SIZE", "?")
        logger.info("⚡ PERF Tuning: MAX_CHANNELS=%s | HTTPX_POOL=%s", _max_ch, "32" if _HAS_HTTPX_REQUEST else "default")
    except Exception as _e:
        logger.debug("_log_perf_tuning_status: %s", _e)

try:
    from database import ANALYTICS_MIXIN_AVAILABLE
    if not ANALYTICS_MIXIN_AVAILABLE:
        logger.warning("⚠️ AnalyticsMixin مفقود")
except Exception as _e:
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
        "contests": CONTESTS_MIXIN_AVAILABLE, "stats": STATS_MIXIN_AVAILABLE,
        "settings": SETTINGS_MIXIN_AVAILABLE, "points": POINTS_MIXIN_AVAILABLE,
        "backup": BACKUP_MIXIN_AVAILABLE, "reminders": REMINDERS_MIXIN_AVAILABLE,
        "analytics": ANALYTICS_MIXIN_AVAILABLE,
    }
    _missing = [k for k, v in _mixins_status.items() if not v]
    if _missing:
        logger.warning("⚠️ Mixins مفقودة: %s", _missing)
    else:
        logger.info("✅ كل الـ %d Mixins محمّلة", len(_mixins_status))
except Exception as _e:
    pass

try:
    from database import REFACTOR_MIXIN_AVAILABLE
    if REFACTOR_MIXIN_AVAILABLE:
        logger.info("✅ RefactorMixin محمّل")
except Exception as _e:
    pass

if _MAINTENANCE_AVAILABLE:
    logger.info("✅ maintenance محمّل")
else:
    logger.warning("⚠️ maintenance غير متاح: %s", _MAINTENANCE_IMPORT_ERROR)

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

if _ANALYTICS_REGISTER_AVAILABLE and callable(_register_analytics_handlers):
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
            if len(_pc_sig.parameters) >= 1 and 'self' in _pc_sig.parameters:
                logger.warning("⚠️ periodic_cleanup_task يحتاج 'self'")
        except (ValueError, TypeError):
            pass
except Exception as _e:
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
    ("auto_publish", "📤 تبديل النشر التلقائي"), ("auto_recycle", "♻️ تبديل التدوير"),
]

ADMIN_COMMANDS = [
    ("stats", "📊 الإحصائيات"), ("grant", "🎁 منح اشتراك يدوي"),
    ("set_min_interval", "⏱️ تعيين الحد الأدنى للفاصل"), ("admin", "👑 لوحة الأدمن"),
    ("broadcast", "📨 بث جماعي"), ("set_force", "🔒 تعيين الاشتراك الإجباري"),
    ("set_update_ch", "📢 تعيين قناة التحديثات"), ("set_log_ch", "📋 تعيين قناة السجلات"),
    ("add_admin", "👑 إضافة مشرف"), ("remove_admin", "🗑️ إزالة مشرف"),
    ("export_replies", "📤 تصدير الردود"), ("import_replies", "📥 استيراد الردود"),
    ("backup", "💾 نسخ احتياطي"), ("restore", "🔄 عرض النسخ"),
    ("db_diag", "🔬 تشخيص قاعدة البيانات"), ("db_vacuum", "🧹 تنظيف قاعدة البيانات"),
    ("db_diag_quick", "🔬 تقرير صحي مختصر"), ("db_maintenance", "🧹 صيانة قاعدة البيانات"),
    ("db_weekly", "📅 التقرير الأسبوعي"), ("autoblocked", "🚫 المصادر المحجوبة تلقائياً"),
    ("db_idle", "🔍 تدقيق idle-in-transaction"), ("cache_stats", "📊 إحصائيات الكاش الحية"),
    ("fullhealth", "🏥 التشخيص الشامل"), ("latency", "🔬 اختبار الكمون"),
    ("databases", "🗂️ قواعد البيانات المُعدّة"), ("ping", "🏓 قياس كمون الاتصال"),
    ("posts_stats", "📊 إحصائيات النشر (DB)"),
    ("autotune", "⚙️ ضبط autovacuum"),
    ("db_tune", "⚙️ ضبط autovacuum (اختصار)"),
    ("analytics", "📊 التحليلات المتقدمة"),
    ("versions", "📦 إصدارات الوحدات"),
    ("analytics_reset", "🗑️ إبطال كاش التحليلات"),
    ("files", "📂 ملفات المشروع"),
]

GROUP_COMMANDS = [
    ("syncgroup", "🔗 تفعيل المجموعة"), ("security", "🛡️ إعدادات الأمان"),
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
                result = _shutdown_default_executor_fn(_loop, timeout=timeout)
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
    any_method_ran = False
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
            any_method_ran = True
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
            any_method_succeeded = True
            break
        except Exception as _e:
            last_error = _e
            continue

    if not any_method_succeeded:
        logger.warning("⚠️ _collect_admin_ids: لا توجد قائمة أدمن من DB")

    return sorted(admin_ids)

async def refresh_admin_commands(bot, user_id: int, is_admin: bool) -> bool:
    if not user_id:
        return False
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    try:
        if is_admin:
            await bot.set_my_commands(PUBLIC_COMMANDS + ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=uid))
        else:
            try:
                await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=uid))
            except Exception:
                pass
            await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeChat(chat_id=uid))
        return True
    except Exception as e:
        logger.warning("⚠️ refresh_admin_commands(%d): %s", uid, e)
        return False

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
        "remove_hidden_owner", "add_hidden_admin", "remove_hidden_admin",
        "list_hidden_admins",
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

    logger.info("✅ كل %d دالة CommandHandlers موجودة و async", len(required))
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
                logger.warning("⚠️ DB_TYPE=%s لكن DATABASE_URL فارغ!", db_type)
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
    if not _GROUP_LOG_AVAILABLE or not callable(register_group_log_handlers):
        return False
    return True

def _verify_membership_handler() -> bool:
    if not _MEMBERSHIP_AVAILABLE or not callable(register_membership_handlers):
        return False
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
                logger.info("✅ admin_logs cleanup: حُذف %d صف", deleted)
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
                    result = await DB.execute("DELETE FROM user_channels WHERE removed_at IS NOT NULL AND removed_at < NOW() - INTERVAL '1 day' * $1", (GRACE_DAYS,))
                elif db_type == "mysql":
                    result = await DB.execute("DELETE FROM user_channels WHERE removed_at IS NOT NULL AND removed_at < UTC_TIMESTAMP() - INTERVAL %s DAY", (GRACE_DAYS,))
                else:
                    result = await DB.execute("DELETE FROM user_channels WHERE removed_at IS NOT NULL AND julianday('now') - julianday(removed_at) > ?", (GRACE_DAYS,))
                if isinstance(result, int):
                    deleted = result
                else:
                    try:
                        deleted = int(getattr(result, 'rowcount', 0) or 0)
                    except (TypeError, ValueError):
                        deleted = 0
            if deleted:
                logger.info("✅ removed_channels cleanup: حُذف %d قناة", deleted)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("❌ cleanup_removed_channels: %s", e, exc_info=True)
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
    if (not invoice or invoice.get('user_id') != user_id or invoice.get('status') != 'pending' or not invoice.get('number')):
        return None, None, None
    payment_type = data.get('type')
    if payment_type not in ('subscription', 'gift'):
        return None, None, None
    plan_id = data.get('plan_id') if payment_type == 'subscription' else data.get('gift_plan_id')
    if not plan_id:
        return None, None, None
    try:
        plan = await DB.get_plan(plan_id) if payment_type == 'subscription' else await DB.get_gift_plan(plan_id)
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
            await query.answer(ok=False, error_message="الفاتورة غير صالحة أو انتهت صلاحيتها.")
        except Exception as e:
            logger.error("❌ pre-checkout reject: %s", e)
        return
    try:
        q_currency = getattr(query, 'currency', None)
        if q_currency and q_currency != "XTR":
            await query.answer(ok=False, error_message="العملة غير مدعومة.")
            return
    except Exception:
        pass
    if hasattr(query, 'total_amount'):
        expected_amount = plan.get('price')
        if (expected_amount is not None and float(expected_amount or 0) > 0 and not _amounts_match(expected_amount, query.total_amount)):
            await query.answer(ok=False, error_message="المبلغ غير مطابق لسعر الخطة.")
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
                if (_existing and _existing.get('user_id') == user_id and _existing.get('status') == 'paid'):
                    await safe_send(context.bot, user_id, "✅ تم استلام إشعار الدفع.\nالفاتورة مُعالجة مسبقاً.")
                    return
        except Exception:
            pass
        await safe_send(context.bot, user_id, "❌ حدث خطأ في معالجة الدفع.")
        return

    plan_price = plan.get('price', 0)
    if float(plan_price or 0) > 0 and not _amounts_match(plan_price, total_amount):
        await safe_send(context.bot, user_id, "❌ المبلغ المدفوع غير مطابق.")
        return

    payment_type = data.get('type')
    payment_id = telegram_payment_charge_id or provider_payment_charge_id
    if not payment_id:
        await safe_send(context.bot, user_id, f"❌ مشكلة في بيانات الدفع. الفاتورة: <code>{invoice.get('number') or '?'}</code>", parse_mode='HTML')
        return

    plan_name = plan.get('name', 'الخطة')

    if payment_type == 'subscription':
        try:
            success = await DB.activate_subscription_with_payment(user_id=user_id, invoice_number=invoice['number'], payment_id=payment_id, plan_id=plan['id'])
        except Exception as e:
            logger.exception("❌ Exception in subscription activation: %s", e)
            await safe_send(context.bot, user_id, "❌ حدث خطأ غير متوقع.")
            return
        if not success:
            logger.error("🔴 SUBSCRIPTION_DB_FAILED: user=%s invoice=%s", user_id, invoice['number'])
            try:
                _spawn_notify_dev_log(context, f"🔴 فشل تفعيل اشتراك\n👤 {user_id}\n🧾 {invoice['number']}")
            except Exception:
                pass
            await safe_send(context.bot, user_id, "⚠️ تم استلام الدفع لكن حدث خطأ في التفعيل.")
            return
        try:
            await safe_send(context.bot, user_id, f"✅ تم تفعيل اشتراك {plan_name} بنجاح!")
        except Exception as _e:
            pass
        try:
            await DB.add_payment_log(user_id, 'xtr', 'subscription_paid', {'invoice': invoice['number'], 'plan_id': plan['id']})
        except Exception as _e:
            pass
        try:
            await invalidate_user_cache(user_id)
        except Exception as _e:
            pass
        try:
            _uname = update.effective_user.username or ""
            _fname = update.effective_user.first_name or ""
            _spawn_notify_dev_log(context, f"💎 اشتراك مدفوع جديد\n👤 {_fname}\n🆔 {user_id}\n💎 {plan_name}\n💰 {int(total_amount or 0)} ⭐")
        except Exception:
            pass

    elif payment_type == 'gift':
        try:
            paid = await DB.mark_invoice_paid(invoice['number'], payment_id)
        except Exception as e:
            logger.exception("❌ mark_invoice_paid exception: %s", e)
            await safe_send(context.bot, user_id, "❌ حدث خطأ غير متوقع.")
            return
        if not paid:
            await safe_send(context.bot, user_id, "❌ فشل توثيق الدفع.")
            return
        try:
            code = await DB.create_gift_code(plan_id=plan['id'], creator_id=user_id)
        except Exception as e:
            logger.exception("❌ create_gift_code exception: %s", e)
            try:
                _spawn_notify_dev_log(context, f"🔴 فشل توليد كود هدية\n👤 {user_id}\n🧾 {invoice['number']}")
            except Exception:
                pass
            await safe_send(context.bot, user_id, "⚠️ تم توثيق الدفع لكن فشل توليد الكود.")
            return
        if not code:
            logger.error("❌ create_gift_code أعاد None: user=%s", user_id)
            try:
                _spawn_notify_dev_log(context, f"🔴 create_gift_code أعاد None\n👤 {user_id}\n🧾 {invoice['number']}")
            except Exception:
                pass
            await safe_send(context.bot, user_id, "⚠️ تم توثيق الدفع لكن فشل توليد الكود.")
            return
        duration = plan.get('duration_days') or plan.get('days') or 0
        try:
            await safe_send(context.bot, user_id, f"🎉 تم شراء كود الهدية بنجاح!\n🎁 <code>{code}</code>\n📅 المدة: {duration} يوم", parse_mode='HTML')
        except Exception as _e:
            pass
        try:
            _uname = update.effective_user.username or ""
            _fname = update.effective_user.first_name or ""
            _spawn_notify_dev_log(context, f"🎁 هدية مُشتراة\n👤 {_fname}\n🆔 {user_id}\n💎 {plan_name}\n🔑 {code}")
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
        logger.info("ℹ️ keep_alive: URL غير موجود — المهمة ستُحجب أبدياً")
        await asyncio.Event().wait()
        return
    url = url.rstrip('/')
    health_url = f"{url}/health"
    _consecutive_errors = 0
    _timeout = aiohttp.ClientTimeout(total=15, connect=5)
    _connector = aiohttp.TCPConnector(limit=2, ttl_dns_cache=300, keepalive_timeout=60)
    async with aiohttp.ClientSession(timeout=_timeout, connector=_connector) as session:
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
                    logger.warning("💓 keep-alive: %d أخطاء متتالية", _consecutive_errors)
                else:
                    logger.debug("💓 keep-alive: %s", e)

async def _dump_idle_tx_details() -> None:
    try:
        rows = await DB.fetchall("SELECT pid, usename, application_name, state, EXTRACT(EPOCH FROM (now() - state_change))::int AS seconds_in_state, LEFT(query, 200) AS query_snippet FROM pg_stat_activity WHERE datname = current_database() AND state = 'idle in transaction' ORDER BY state_change ASC LIMIT 5")
        if not rows:
            return
        for r in rows:
            logger.error("   • pid=%s user=%s age=%ss", r.get("pid"), r.get("usename"), r.get("seconds_in_state"))
    except Exception as qe:
        logger.debug("_dump_idle_tx_details: %s", qe)

async def _fetch_pool_data(total: int, active: int) -> Optional[Dict[str, Any]]:
    try:
        if hasattr(DB, "get_pool_live"):
            _pd = await DB.get_pool_live()
            if (isinstance(_pd, dict) and _pd.get("available") and _pd.get("max_size")):
                return _pd
    except Exception as _e:
        pass
    try:
        if hasattr(DB, "get_pool_stats"):
            _pd = await DB.get_pool_stats()
            if (isinstance(_pd, dict) and _pd.get("type") in ("postgres", "mysql") and _pd.get("max_size")):
                return {"max_size": _pd.get("max_size"), "current_size": _pd.get("current_size"), "in_use": _pd.get("in_use")}
    except Exception as _e:
        pass
    return None

async def _fetch_pg_activity_cached() -> Dict[str, Any]:
    global _pm_last_query_ts, _pm_last_query_result, _pm_slow_query_warned
    now = time.monotonic()
    if (_pm_last_query_result is not None and (now - _pm_last_query_ts) < _PM_QUERY_TTL):
        return _pm_last_query_result
    try:
        row = await DB.fetchone("SELECT count(*) AS total, count(*) FILTER (WHERE state = 'active') AS active, count(*) FILTER (WHERE state = 'idle') AS idle, count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_tx, count(*) FILTER (WHERE wait_event_type = 'Lock') AS lock_waits, count(*) FILTER (WHERE wait_event_type IN ('Lock', 'LWLock', 'BufferPin')) AS waiting FROM pg_stat_activity WHERE datname = current_database()")
        data = row if isinstance(row, dict) else (dict(row) if row else {})
        _pm_last_query_ts = now
        _pm_last_query_result = data
        return data
    except Exception as e:
        logger.debug("_fetch_pg_activity_cached: %s", e)
        return {}

async def pool_health_monitor() -> None:
    _task_start_mono = time.monotonic()
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
            active = int(data.get("active") or 0)
            idle_in_tx = int(data.get("idle_in_tx") or 0)
            util_pct = (total / 20 * 100) if total else 0
            if idle_in_tx > 0:
                _idle_tx_streak += 1
            else:
                _idle_tx_streak = 0
            if idle_in_tx >= _PM_IDLE_TX_ERROR_THRESHOLD or util_pct >= _PM_UTIL_CRITICAL_PCT:
                logger.error("🔴 pool CRITICAL: total=%d idle_tx=%d util=%.0f%%", total, idle_in_tx, util_pct)
            elif util_pct >= _PM_UTIL_WARN_PCT:
                logger.warning("⚠️ pool DIAG: total=%d util=%.0f%%", total, util_pct)
            else:
                logger.info("🟢 pool HEALTH: total=%d util=%.0f%%", total, util_pct)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("pool_health_monitor: %s", e)
        try:
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            raise

def _resolve_hostname() -> Optional[str]:
    """v5.7.4: يجرّب متغيرات بيئة أكثر."""
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
        _timeout = aiohttp.ClientTimeout(total=_WATCHER_HEALTH_TIMEOUT, connect=2)
        _connector = aiohttp.TCPConnector(limit=2, ttl_dns_cache=60, keepalive_timeout=30)
        async with aiohttp.ClientSession(timeout=_timeout, connector=_connector) as session:
            while not shutdown_event.is_set():
                try:
                    if site is not None:
                        server = getattr(site, "_server", None)
                        if server is not None and (server.sockets is None or len(server.sockets) == 0):
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
                                raise RuntimeError(f"health status={resp.status}")
                        if probe_failures > 0:
                            probe_failures -= 1
                    except asyncio.CancelledError:
                        raise
                    except Exception as probe_e:
                        probe_failures += 1
                        if probe_failures >= _WATCHER_MAX_PROBE_FAILURES:
                            shutdown_event.set()
                            return
                    await asyncio.sleep(_WATCHER_INTERVAL)
                except asyncio.CancelledError:
                    raise
                except Exception as _e:
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
            logger.error("❌ Task %s crashed: %s", task_name, e, exc_info=True)
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
                        msg = f"🎉 <b>مبروك!</b>\n\nلقد فزت في مسابقة <b>{_html_escape(str(w.get('title') or 'مسابقة'))}</b>!"
                        await app.bot.send_message(chat_id=winner_id, text=msg, parse_mode="HTML")
                    except Exception as ne:
                        logger.debug("إشعار الفائز %s فشل: %s", winner_id, ne)
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

async def _start_polling_mode(app: Application) -> None:
    if app.updater is None:
        raise RuntimeError("Polling mode يتطلب updater.")
    if _polling_state["running"]:
        raise RuntimeError("Application is already running!")
    _app_running = (getattr(app, "running", False) or getattr(app, "_running", False))
    if not _app_running:
        raise RuntimeError("app.running=False — يجب استدعاء app.start() قبل _start_polling_mode()")
    _polling_state["running"] = True
    try:
        await app.updater.start_polling(drop_pending_updates=True, allowed_updates=ALLOWED_UPDATES)
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
            "📥 INCOMING | chat=%s msg=%s | text=%s caption=%s photo=%s video=%s doc=%s audio=%s voice=%s anim=%s sticker=%s vn=%s poll=%s | fwd_origin=%s fwd_chat=%s auto_fwd=%s | btn_count=%d",
            chat.id, msg.message_id, bool(getattr(msg, "text", None)), bool(getattr(msg, "caption", None)),
            bool(getattr(msg, "photo", None)), bool(getattr(msg, "video", None)),
            bool(getattr(msg, "document", None)), bool(getattr(msg, "audio", None)),
            bool(getattr(msg, "voice", None)), bool(getattr(msg, "animation", None)),
            bool(getattr(msg, "sticker", None)), bool(getattr(msg, "video_note", None)),
            bool(getattr(msg, "poll", None)),
            type(fwd_origin).__name__ if fwd_origin is not None else None,
            getattr(fwd_chat, "id", None) if fwd_chat is not None else None,
            bool(getattr(msg, "is_automatic_forward", False)), btn_count,
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
            age_ms = int((datetime.now(timezone.utc) - msg_date).total_seconds() * 1000)
        t0 = time.monotonic()
        try:
            if _HAS_REPLY_PARAMETERS and ReplyParameters is not None:
                sent = await msg.reply_text("🏓 قياس...", reply_parameters=ReplyParameters(message_id=msg.message_id))
            else:
                sent = await msg.reply_text("🏓 قياس...", reply_to_message_id=msg.message_id)
        except TypeError:
            sent = await msg.reply_text("🏓 قياس...")
        t1 = time.monotonic()
        send_rtt_ms = int((t1 - t0) * 1000)
        try:
            _BOT_METRICS["pings_total"] = int(_BOT_METRICS.get("pings_total") or 0) + 1
            _BOT_METRICS["ping_sum_ms"] = int(_BOT_METRICS.get("ping_sum_ms") or 0) + send_rtt_ms
            _cur_min = _BOT_METRICS.get("ping_min_ms")
            if _cur_min is None or send_rtt_ms < _cur_min:
                _BOT_METRICS["ping_min_ms"] = send_rtt_ms
            _cur_max = _BOT_METRICS.get("ping_max_ms")
            if _cur_max is None or send_rtt_ms > _cur_max:
                _BOT_METRICS["ping_max_ms"] = send_rtt_ms
        except Exception as _e:
            pass
        lines = ["🏓 <b>Pong</b>", "", f"⚡ <b>Send API RTT:</b> <code>{send_rtt_ms}ms</code>"]
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
        t2 = time.monotonic()
        edit_rtt_ms = -1
        try:
            await sent.edit_text("\n".join(lines), parse_mode='HTML')
            t3 = time.monotonic()
            edit_rtt_ms = int((t3 - t2) * 1000)
        except Exception as _ee:
            logger.debug("ping edit_text: %s", _ee)
        logger.info("🏓 /ping | user=%s | send=%dms | edit=%dms | age=%sms", user.id, send_rtt_ms, edit_rtt_ms, age_ms if age_ms is not None else -1)
    except Exception as e:
        logger.error("❌ /ping error: %s", e, exc_info=True)
        try:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ فشل القياس: {type(e).__name__}")
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════
# v5.7.2: /posts_stats — إحصائيات النشر من DB مباشرة
# ═══════════════════════════════════════════════════════════════════

async def cmd_posts_stats(update, context):
    """
    📊 إحصائيات النشر من DB مباشرة.
    """
    user = update.effective_user
    if user is None:
        return
    allowed = _resolve_admin_guard(context)
    if not allowed:
        logger.warning(
            "/posts_stats refused (fail-closed): no admin list available. "
            "user=%s", user.id,
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

    async def _try_count(sql: str) -> Tuple[Optional[int], Optional[str]]:
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
                        rd.get('column_name')
                        or rd.get('name')
                        or rd.get('Field')
                        or rd.get('COLUMN_NAME')
                    )
                if c is None:
                    try:
                        if _db_type == "sqlite":
                            c = r[1]
                        else:
                            c = r[0]
                    except Exception:
                        c = None
                if c:
                    cols.add(str(c).lower())
            return cols
        except Exception as _e:
            logger.debug("_get_posts_columns: %s", _e)
            return set()

    posts_cols = await _get_posts_columns()

    async def _discover_channel_col() -> Optional[str]:
        candidates = (
            "channel_db_id", "channel_id", "channel", "chat_id",
            "source_id", "source", "target_channel",
            "channel_username", "chat",
        )
        for c in candidates:
            if c in posts_cols:
                return c
        for c in candidates:
            try:
                await DB.fetchone(f"SELECT {c} FROM posts LIMIT 1")
                return c
            except Exception:
                continue
        return None

    channel_col = await _discover_channel_col()

    lines = ["📊 <b>إحصائيات النشر — من DB مباشرة</b>", ""]

    if not posts_cols:
        lines.append(
            "⚠️ <b>جدول <code>posts</code> غير موجود أو فارغ</b> "
            f"<i>(DB_TYPE={_db_type})</i>"
        )
        lines.append(
            "  <i>تأكد من تنفيذ migrations، أو أن الجدول في schema آخر "
            "(public افتراضياً).</i>"
        )
        text = "\n".join(lines)
        try:
            await msg.reply_text(text, parse_mode='HTML')
        except Exception:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=text, parse_mode='HTML',
                )
            except Exception:
                pass
        return

    _important = [
        "published", "published_at", "created_at",
        "sent_at", "status", "channel_db_id",
        "channel_id", "channel",
    ]
    _present = [c for c in _important if c in posts_cols]
    _absent = [c for c in _important if c not in posts_cols]
    if _present:
        lines.append(
            f"🔑 <b>أعمدة موجودة:</b> "
            f"<code>{', '.join(_present)}</code>"
        )
    if _absent:
        lines.append(
            f"🚫 <b>أعمدة مفقودة:</b> "
            f"<code>{', '.join(_absent)}</code>"
        )
    if channel_col:
        lines.append(
            f"📡 <b>عمود القناة:</b> <code>{channel_col}</code>"
        )
    lines.append("")

    cnt_pub_at, err_pub_at = await _try_count(
        f"SELECT COUNT(*) AS n FROM posts "
        f"WHERE published_at IS NOT NULL "
        f"AND created_at > {_interval_24h}"
    )
    if err_pub_at is None:
        lines.append(
            f"✅ <code>published_at NOT NULL (24h)</code>: "
            f"<b>{cnt_pub_at}</b>"
        )
    else:
        lines.append(
            f"⚠️ <code>published_at NOT NULL (24h)</code>: "
            f"<i>{err_pub_at}</i>"
        )

    cnt_p1, err_p1 = await _try_count(
        f"SELECT COUNT(*) AS n FROM posts "
        f"WHERE published = 1 "
        f"AND created_at > {_interval_24h}"
    )
    if err_p1 is None:
        lines.append(
            f"✅ <code>published=1 (24h)</code>: <b>{cnt_p1}</b>"
        )
    else:
        lines.append(
            f"⚠️ <code>published=1 (24h)</code>: <i>{err_p1}</i>"
        )

    if _db_type == "postgres":
        cnt_pt, err_pt = await _try_count(
            f"SELECT COUNT(*) AS n FROM posts "
            f"WHERE published = TRUE "
            f"AND created_at > {_interval_24h}"
        )
        if err_pt is None:
            lines.append(
                f"✅ <code>published=TRUE (24h)</code>: <b>{cnt_pt}</b>"
            )
        elif cnt_p1 is not None:
            lines.append(
                "ℹ️ <code>published=TRUE</code>: "
                "<i>غير مدعوم (integer column) — استخدم =1</i>"
            )
        else:
            lines.append(
                f"⚠️ <code>published=TRUE</code>: <i>{err_pt}</i>"
            )

    if "sent_at" in posts_cols:
        cnt_sa, err_sa = await _try_count(
            f"SELECT COUNT(*) AS n FROM posts "
            f"WHERE sent_at IS NOT NULL "
            f"AND created_at > {_interval_24h}"
        )
        if err_sa is None:
            lines.append(
                f"✅ <code>sent_at NOT NULL (24h)</code>: "
                f"<b>{cnt_sa}</b>"
            )
        else:
            lines.append(
                f"⚠️ <code>sent_at NOT NULL</code>: <i>{err_sa}</i>"
            )

    if "status" in posts_cols:
        cnt_st, err_st = await _try_count(
            f"SELECT COUNT(*) AS n FROM posts "
            f"WHERE status = 'published' "
            f"AND created_at > {_interval_24h}"
        )
        if err_st is None:
            lines.append(
                f"✅ <code>status='published' (24h)</code>: "
                f"<b>{cnt_st}</b>"
            )
        else:
            lines.append(
                f"⚠️ <code>status='published'</code>: <i>{err_st}</i>"
            )

    cnt_total, err_total = await _try_count(
        "SELECT COUNT(*) AS n FROM posts"
    )
    if err_total is None:
        lines.append(
            f"✅ <code>total posts (all-time)</code>: <b>{cnt_total}</b>"
        )
    else:
        lines.append(
            f"⚠️ <code>total posts</code>: <i>{err_total}</i>"
        )

    cnt_15m, err_15m = await _try_count(
        f"SELECT COUNT(*) AS n FROM posts "
        f"WHERE published_at IS NOT NULL "
        f"AND published_at > {_interval_15m}"
    )
    if err_15m is None:
        lines.append(
            f"✅ <code>published last 15m</code>: <b>{cnt_15m}</b>"
        )
    else:
        lines.append(
            f"⚠️ <code>published last 15m</code>: <i>{err_15m}</i>"
        )

    try:
        _main_mod = sys.modules.get("__main__")
        _bot_mod = sys.modules.get("bot")
        _same_module = (_main_mod is _bot_mod)
        _main_id = id(_main_mod) if _main_mod else 0
        _bot_id = id(_bot_mod) if _bot_mod else 0
        if _same_module:
            lines.append(
                "✅ <code>module binding</code>: <b>unified</b> "
                f"<i>(__main__ == bot)</i>"
            )
        elif _bot_mod is None:
            lines.append(
                "⚠️ <code>module binding</code>: "
                "<b>bot غير محمّل بعد</b> "
                "<i>(record_bot_metric لم يُستدعَ)</i>"
            )
        else:
            lines.append(
                f"🔴 <code>module binding</code>: <b>SEPARATE!</b> "
                f"<i>(__main__={_main_id:#x}, bot={_bot_id:#x})</i>"
            )
    except Exception as _mbe:
        lines.append(
            f"⚠️ <code>module binding</code>: <i>{type(_mbe).__name__}</i>"
        )

    lines.append("")
    if channel_col:
        try:
            rows = await DB.fetchall(
                f"SELECT {channel_col} AS ch, COUNT(*) AS n FROM posts "
                f"WHERE published_at IS NOT NULL "
                f"AND created_at > {_interval_24h} "
                f"GROUP BY {channel_col} "
                f"ORDER BY n DESC LIMIT 10"
            )
            if rows:
                lines.append(
                    f"📡 <b>لكل قناة (24h) — عبر "
                    f"<code>{channel_col}</code>:</b>"
                )
                for r in rows:
                    if isinstance(r, dict):
                        cid = r.get('ch')
                        n = r.get('n', 0)
                    else:
                        try:
                            cid, n = r[0], r[1]
                        except Exception:
                            continue
                    lines.append(
                        f"  • <code>{cid}</code>: <b>{n}</b>"
                    )
            else:
                lines.append(
                    "📭 <i>لا منشورات مُصنَّفة بقناة في آخر 24h</i>"
                )
        except Exception as _e:
            lines.append(
                f"⚠️ per-channel: "
                f"<code>{type(_e).__name__}: {str(_e)[:80]}</code>"
            )
    else:
        lines.append(
            "⚠️ <b>per-channel:</b> <i>لم يُعثر على عمود قناة "
            "(تم فحص: channel_db_id, channel_id, channel, chat_id, "
            "source_id, source, target_channel, channel_username, chat)</i>"
        )

    uptime_s = int(time.monotonic() - _BOT_METRICS.get(
        "started_at", time.monotonic()
    ))

    _active_channels = 1
    if uptime_s > 0:
        try:
            _ch_row = await DB.fetchone(
                "SELECT COUNT(*) AS n FROM user_channels "
                "WHERE removed_at IS NULL"
            )
            if _ch_row:
                _ch_n = (
                    _ch_row.get('n')
                    if isinstance(_ch_row, dict)
                    else _ch_row[0]
                )
                if _ch_n and int(_ch_n) > 0:
                    _active_channels = int(_ch_n)
        except Exception as _e:
            logger.debug("get_active_channels for stats: %s", _e)

    lines.append("")
    lines.append("🔢 <b>bot.py metrics (since restart):</b>")
    lines.append(
        f"  • ⏱️ uptime: <code>{uptime_s}s</code> "
        f"(~{uptime_s // 60}د {uptime_s % 60}ث)"
    )
    _ps = _BOT_METRICS.get('posts_success', 0)
    _pf = _BOT_METRICS.get('posts_failed', 0)
    lines.append(
        f"  • ✅ posts_success: <code>{_ps}</code> "
        f"{'🟢' if _ps > 0 else '⏳ (لم ينشر بعد)'}"
    )
    lines.append(
        f"  • ❌ posts_failed: <code>{_pf}</code>"
    )

    pings_total = _BOT_METRICS.get('pings_total', 0)
    pings_sum = _BOT_METRICS.get('ping_sum_ms', 0)
    pings_avg = (pings_sum // pings_total) if pings_total else 0
    lines.append(
        f"  • 🏓 pings: <code>{pings_total}</code> "
        f"(avg={pings_avg}ms, "
        f"min={_BOT_METRICS.get('ping_min_ms') or '—'}, "
        f"max={_BOT_METRICS.get('ping_max_ms') or '—'})"
    )

    lines.append("")
    if uptime_s < 600 and _ps == 0:
        lines.append(
            "ℹ️ <i>البوت حديث الإقلاع — لم ينشر بعد. "
            "انتظر الدورة التالية للقناة ثم أعد الفحص.</i>"
        )
    elif uptime_s > 600 and _ps == 0:
        lines.append(
            "⚠️ <i>مضى أكثر من 10 دقائق بلا posts_success. "
            "تحقق من utils.py v7.10.26 (record_bot_metric) "
            "و module binding أعلاه.</i>"
        )
    elif _ps > 0:
        lines.append(
            f"✅ <i>record_bot_metric يعمل — "
            f"{_ps} منشور/منشورات منذ الإقلاع.</i>"
        )

    lines.append("")
    if uptime_s > 0 and _ps > 0:
        try:
            _min_interval = await get_min_publish_interval()
            _min_interval = int(_min_interval) if _min_interval else 5
        except Exception:
            _min_interval = 5
        if _min_interval < 1:
            _min_interval = 1

        rate_per_hour = (_ps / uptime_s) * 3600.0
        expected_per_hour = (60.0 / _min_interval) * _active_channels

        lines.append(
            f"📈 <b>معدل النشر:</b> "
            f"<code>{rate_per_hour:.0f}/ساعة</code> "
            f"<i>(متوقع لـ {_active_channels} قناة نشطة بـ "
            f"interval={_min_interval}د: "
            f"~{expected_per_hour:.0f}/ساعة)</i>"
        )
        if rate_per_hour > expected_per_hour * 1.5:
            lines.append(
                "🔴 <b>معدل النشر أعلى من المتوقع 1.5×!</b> "
                "<i>تحقق من:</i>"
            )
            lines.append("  <i>1. min_publish_interval قصير جداً؟</i>")
            lines.append(
                "  <i>2. posts يتيمة (channel_db_id=NULL) تُنشر؟</i>"
            )
            lines.append(
                "  <i>3. مهام auto_publish متعددة في نفس الوقت؟</i>"
            )
        elif rate_per_hour < expected_per_hour * 0.5:
            lines.append(
                "⚠️ <b>معدل النشر أقل من المتوقع 0.5×</b> "
                "<i>(قنوات خاملة أو مشاكل اشتراكات)</i>"
            )
        else:
            lines.append(
                "✅ <i>معدل النشر ضمن النطاق الطبيعي</i>"
            )

    if cnt_15m is not None and cnt_15m > 0 and uptime_s > 0:
        try:
            _min_interval_15m = await get_min_publish_interval()
            _min_interval_15m = (
                int(_min_interval_15m) if _min_interval_15m else 5
            )
        except Exception:
            _min_interval_15m = 5
        if _min_interval_15m < 1:
            _min_interval_15m = 1

        expected_15m = (15.0 / _min_interval_15m) * _active_channels

        if cnt_15m > expected_15m * 1.5:
            lines.append("")
            lines.append(
                f"🔴 <b>نشر سريع جداً:</b> <code>{cnt_15m}</code> "
                f"في 15 دقيقة <i>(متوقع ~{expected_15m:.0f} "
                f"لـ {_active_channels} قناة بـ "
                f"interval={_min_interval_15m}د)</i>"
            )
            lines.append(
                "  <i>راجع min_publish_interval "
                "أو مهام auto_publish المكررة</i>"
            )

    text = "\n".join(lines)
    try:
        await msg.reply_text(text, parse_mode='HTML')
    except Exception:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text, parse_mode='HTML',
            )
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

async def main():
    t_start = time.monotonic()

    _shutdown_event = asyncio.Event()

    def _on_shutdown_signal(sig_name: str):
        logger.info("🛑 تلقّيت %s — بدء الإغلاق اللطيف", sig_name)
        _shutdown_event.set()

    try:
        _loop_for_signals = asyncio.get_running_loop()
        _signals_to_install = [signal.SIGTERM, signal.SIGINT]
        if hasattr(signal, "SIGHUP"):
            _signals_to_install.append(signal.SIGHUP)

        for _sig in _signals_to_install:
            try:
                _loop_for_signals.add_signal_handler(
                    _sig,
                    lambda s=_sig: _on_shutdown_signal(s.name),
                )
                logger.debug("✅ handler لـ %s مسجّل", _sig.name)
            except (NotImplementedError, RuntimeError, ValueError) as _e:
                logger.debug(
                    "add_signal_handler(%s) غير مدعوم: %s", _sig.name, _e
                )
    except Exception as _e:
        logger.debug("Signal setup (early): %s", _e)

    if _MARK_PROCESS_START_FN is not None:
        try:
            _MARK_PROCESS_START_FN()
            logger.info(
                "🕐 db_diagnostics.mark_process_start() — "
                "نافذة السماح بدأت الآن (60s)"
            )
        except Exception as _e:
            logger.debug(
                "mark_process_start فشل (سيستمر البوت): %s", _e
            )

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
        "📦 bot.py: v5.7.4 | "
        "detectors=%s | layers=%d | helpers=%s | "
        "db_idle=%s | cache_stats=%s | analytics=%s | "
        "fullhealth=%s | latency=%s | maint_cmds=%s | "
        "pool_cache_ttl=%ds | nav_fix=%s | perf_sessions=on | "
        "nav_fix_mode=trace-only | handle_reg=always | "
        "dup_fix=on | sleep_probe=%s | app_start=on | "
        "watcher_interval=%.0fs | shutdown_robust=on | "
        "httpx_pool=%s | "
        "db_diag=%s | db_diag_mark=%s | "
        "warmup_detectors=%s | analytics_register=%s | "
        "payment_order_fix=on | post_init_webhook=on | "
        "db_close=on | signal_early=on | "
        "app_stop=on | chattype_modern=on | pay_filter=on | "
        "ping_cmd=on | ping_admin_guard=fail-closed | "
        "keepalive_flood_fix=on | "
        "stop_polling_order=on | double_payment_ux=on | "
        "gift_notify=on | reply_params_modern=%s | "
        "resolve_port_none_fix=on | resolve_hostname_invalid=on | "
        "verify_callable=on | verify_async=on | "
        "bot_data_admin_ids=on | "
        "posts_stats_cmd=on | record_bot_metric=on | "
        "record_metric_module_fix=on | record_metric_module_early=on | "
        "posts_stats_15m_diag=on | module_binding_diag=on | "
        "stats_rate_comparison=on | stats_15m_rate=on | "
        "admin_guard_empty_set_fix=on | admin_guard_fail_closed=on | "
        "watch_runner_multipath=on | watch_runner_probe=on | "
        "stats_sqlite=on | stats_published_true_pg_only=on | "
        "successful_payment_private_filter=on | "
        "gift_refund_notify=on | collect_admins_clarity=on | "
        "logger_name_unified=on | metrics_started_at_after_start=on | "
        "keepalive_hang_v2=on | cleanup_removed_rowcount=on | "
        "warmup_task_cleanup=on | posts_table_empty_hint=on | "
        "posts_stats_sql_fix=on | per_channel_discovery=on | "
        "channel_db_id_priority=on | "
        "gil_contention_fix=on | gil_lag_monitor=on | "
        "managed_bots_startup=on | managed_bots_handlers=on | "
        "managed_bots_shutdown=on | stats_channels_rate_fix=on | "
        "stats_active_channels_scope_fix=on | "
        "autotune_available=%s | autotune_cmd=on | db_tune_cmd=on | "
        "analytics_menu=on | versions_cmd=on | files_cmd=on | "
        "admin_commands_extended=on | "
        "handler_timing=on | active_handler_tracker=on | "
        "gil_diagnostics_enhanced=on | resolve_hostname_extended=on",
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
        "yes" if _cmd_fullhealth is not None else "no",
        "yes" if _cmd_latency is not None else "no",
        "yes" if _MAINT_CMDS_AVAILABLE else "no",
        int(_PM_QUERY_TTL),
        "yes" if _NAV_FIX_AVAILABLE else "no",
        (
            "available" if _sleep_probe_available else "missing"
        ),
        _WATCHER_INTERVAL,
        "32" if _HAS_HTTPX_REQUEST else "default(1)",
        _DB_DIAG_VERSION or "N/A",
        "on" if _MARK_PROCESS_START_FN is not None else "off",
        "yes" if _HAS_WARMUP_DETECTORS else "no",
        "yes" if _ANALYTICS_REGISTER_AVAILABLE else "no",
        "yes" if _HAS_REPLY_PARAMETERS else "no",
        "yes" if _AUTOTUNE_AVAILABLE else "no",
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

    try:
        if hasattr(DB, "migrate_reminders_columns"):
            await DB.migrate_reminders_columns()
            logger.info("✅ migrate_reminders_columns: تم")
    except Exception as _e:
        logger.warning("⚠️ migrate_reminders_columns: %s", _e)

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

    if hostname:
        logger.info(
            "🌐 وضع الاتصال: WEBHOOK (hostname=%s) — "
            "آمن ضد تكرار instances",
            hostname,
        )
    else:
        logger.warning(
            "⚠️ وضع الاتصال: POLLING (لا hostname) — "
            "يتطلب instance واحد فقط.\n"
            "   💡 لتجنب Conflict: اضبط RENDER_EXTERNAL_HOSTNAME "
            "أو WEBHOOK_URL، أو تأكد أن Render type=Web Service."
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
        logger.info(
            "🚀 Application.builder: HTTPXRequest pool=32 مُستخدم"
        )
    else:
        logger.info(
            "ℹ️ Application.builder: الإعداد الافتراضي (pool=1)"
        )

    app = _app_builder.build()
    app.bot_data['start_time'] = time.monotonic()
    await app.initialize()
    logger.info(
        "⏱️ تم تهيئة التطبيق في %.2f ثانية",
        time.monotonic() - t_app,
    )

    try:
        await app.start()
        logger.info("✅ app.start() — التطبيق جاهز لمعالجة التحديثات")
    except RuntimeError as _e:
        if "already running" in str(_e).lower():
            logger.debug("app.start(): التطبيق يعمل مسبقاً")
        else:
            raise

    try:
        _BOT_METRICS["started_at"] = time.monotonic()
        logger.debug(
            "📊 _BOT_METRICS['started_at'] reset after app.start() "
            "— uptime will be accurate"
        )
    except Exception as _e:
        logger.debug("reset started_at: %s", _e)

    _tg_warm_ok = await _warmup_telegram_api(app)
    if not _tg_warm_ok:
        logger.info(
            "ℹ️ Telegram API warmup لم ينجح — البوت سيستمر "
            "(قد يكون أول /start أبطأ قليلاً)."
        )

    _spawn_warmup_detectors_pool()

    # ═══ v5.7.0: Managed Bots — بدء البوتات المُدارة ═══
    _managed_apps: Dict[str, Any] = {}
    try:
        from managed_bots_runner import start_all_managed_bots
        _managed_apps = await start_all_managed_bots()
        logger.info(
            "✅ managed_bots: %d/%d بوت عام يعمل",
            sum(1 for ok in _managed_apps.values() if ok),
            len(_managed_apps),
        )
    except Exception as _mb_e:
        logger.error(
            "❌ managed_bots startup: %s", _mb_e, exc_info=True
        )

    _spawn_gil_lag_monitor()

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

    if not _admin_ids:
        logger.critical(
            "🔴 _collect_admin_ids() أعادت قائمة فارغة! "
            "لا يوجد PRIMARY_OWNER_ID ولا DEVELOPER_IDS ولا DB admins. "
            "أي مستخدم سيُرفض من /ping و /posts_stats (fail-closed). "
            "اضبط PRIMARY_OWNER_ID أو DEVELOPER_IDS في البيئة."
        )

    app.bot_data["admin_ids"] = set(_admin_ids)

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
        _GROUP_CHAT_FILTER
        & filters.UpdateType.MESSAGE
        & ~filters.COMMAND
    )

    # 🆕 v5.7.4: timing wrappers
    try:
        _handle_group_timed = _wrap_handler_with_timing(
            MessageHandlers.handle_group, "handle_group"
        )
        app.add_handler(
            MessageHandler(_group_msg_filter, _handle_group_timed),
            group=-1,
        )
        logger.info(
            "✅ handle_group مُسجَّل في group=-1 "
            "(فلتر شامل — كل الأنواع، رسائل جديدة فقط) [timed]"
        )
    except Exception as _e:
        logger.error("❌ فشل تسجيل handle_group: %s", _e, exc_info=True)

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
            logger.info(
                "✅ handle_edited مُسجَّل في group=-1 "
                "(رسائل معدّلة فقط) [timed]"
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
        logger.info("✅ handle_service مُسجَّل في group=-1 [timed]")
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

    # /ping — admin-only
    if _admin_ids:
        try:
            app.add_handler(CommandHandler(
                "ping", cmd_ping,
                filters=filters.User(_admin_ids),
            ))
            logger.info(
                "✅ /ping مُسجَّل (admin-only via filters.User, n=%d)",
                len(_admin_ids),
            )
        except Exception as _e:
            logger.warning(
                "⚠️ فشل تسجيل /ping مع filter — fallback: %s", _e
            )
            app.add_handler(CommandHandler("ping", cmd_ping))
    else:
        app.add_handler(CommandHandler("ping", cmd_ping))
        logger.info(
            "✅ /ping مُسجَّل (internal fail-closed guard — admin_ids فارغة)"
        )

    # /posts_stats — admin-only
    if _admin_ids:
        try:
            app.add_handler(CommandHandler(
                "posts_stats", cmd_posts_stats,
                filters=filters.User(_admin_ids),
            ))
            logger.info(
                "✅ /posts_stats مُسجَّل (admin-only, n=%d)",
                len(_admin_ids),
            )
        except Exception as _e:
            logger.warning(
                "⚠️ فشل تسجيل /posts_stats مع filter — fallback: %s", _e
            )
            app.add_handler(CommandHandler("posts_stats", cmd_posts_stats))
    else:
        app.add_handler(CommandHandler("posts_stats", cmd_posts_stats))
        logger.info(
            "✅ /posts_stats مُسجَّل (internal fail-closed guard)"
        )

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

    if _cmd_fullhealth is not None:
        try:
            app.add_handler(CommandHandler(
                "fullhealth", _cmd_fullhealth
            ))
            logger.info(
                "✅ /fullhealth مُسجَّل — التشخيص الشامل "
                "(شبكة + DB + CPU + RAM + event loop + قرص)"
            )
        except Exception as _e:
            logger.error(
                "❌ فشل تسجيل /fullhealth: %s", _e, exc_info=True
            )
    else:
        logger.warning(
            "⚠️ /fullhealth غير مُسجَّل — "
            "cmd_fullhealth غير متاح (handlers_analytics v1.1.1 أقدم؟)"
        )

    if _cmd_latency is not None:
        try:
            app.add_handler(CommandHandler(
                "latency", _cmd_latency
            ))
            logger.info(
                "✅ /latency مُسجَّل — اختبار كمون الشبكة/DB"
            )
        except Exception as _e:
            logger.error(
                "❌ فشل تسجيل /latency: %s", _e, exc_info=True
            )
    else:
        logger.warning(
            "⚠️ /latency غير مُسجَّل — "
            "cmd_latency غير متاح (handlers_analytics v1.1.1 أقدم؟)"
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
    app.add_handler(MessageHandler(
        filters.SUCCESSFUL_PAYMENT & filters.ChatType.PRIVATE,
        successful_payment,
    ))

    try:
        register_channels_list_handlers(app)
        logger.info(
            "✅ [ORDER 1/6] handlers قائمة القنوات مُسجَّل "
            "(يحتوي _stop_after — يمنع ازدواج CallbackHandlers)"
        )
    except Exception as e:
        logger.error(
            "❌ [ORDER 1/6] فشل تسجيل handlers القنوات: %s",
            e, exc_info=True
        )

    if _NAV_FIX_AVAILABLE and callable(register_nav_fix):
        try:
            register_nav_fix(app)
            logger.info(
                "✅ [ORDER 2/6] NAV_FIX: trace-only مُسجّل "
                "(group=-99، يسجّل الضغطات فقط — لا تفويض)"
            )
        except Exception as e:
            logger.error(
                "❌ [ORDER 2/6] فشل تسجيل NAV_FIX: %s",
                e, exc_info=True
            )
    else:
        logger.info(
            "ℹ️ [ORDER 2/6] NAV_FIX غير متاح — تخطي"
        )

    if _CH_DELETE_AVAILABLE and callable(register_delete_confirmation):
        try:
            register_delete_confirmation(app)
            logger.info(
                "✅ [ORDER 3/6] handlers_channels_delete مُسجَّل — "
                "تأكيد حذف القنوات مُفعّل"
            )
        except Exception as _e:
            logger.error(
                "❌ [ORDER 3/6] فشل تسجيل handlers_channels_delete: %s",
                _e, exc_info=True,
            )
    else:
        logger.warning(
            "⚠️ [ORDER 3/6] handlers_channels_delete غير متاح — "
            "سيتم استخدام الحذف الفوري (بدون تأكيد): %s",
            _CH_DELETE_IMPORT_ERROR or "unknown",
        )

    if _GROUP_LOG_AVAILABLE:
        try:
            register_group_log_handlers(app)
            logger.info(
                "✅ [ORDER 4/6] group_log: "
                "معالجات سجل قناة المجموعات مُسجّلة"
            )
        except Exception as e:
            logger.error(
                "❌ [ORDER 4/6] فشل تسجيل group_log: %s",
                e, exc_info=True
            )
    else:
        logger.warning(
            "⚠️ [ORDER 4/6] group_log غير متاح — "
            "زر قناة السجل لن يعمل"
        )

    _analytics_registered = False

    if _ANALYTICS_REGISTER_AVAILABLE and callable(_register_analytics_handlers):
        try:
            _ok = _register_analytics_handlers(app)
            if _ok:
                _analytics_registered = True
                logger.info(
                    "✅ [ORDER 5/6] handlers_analytics: register_handlers() "
                    "نجح — يشمل /databases + /versions + /analytics_reset "
                    "+ /analytics + databases_btn + versions_refresh + "
                    "analytics_reset_cache + /autotune + autotune_btn + "
                    "/files + files_btn"
                )
            else:
                logger.warning(
                    "⚠️ [ORDER 5/6] register_handlers() أعاد False — "
                    "سيتم استخدام التسجيل اليدوي"
                )
        except Exception as _e:
            logger.error(
                "❌ [ORDER 5/6] register_handlers() فشل: %s — "
                "سيتم استخدام التسجيل اليدوي",
                _e, exc_info=True,
            )
    else:
        logger.info(
            "ℹ️ [ORDER 5/6] handlers_analytics.register_handlers غير متاح "
            "(v1.3.1 مطلوب) — سيتم التسجيل اليدوي"
        )

    if not _analytics_registered:
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
                        r"slow_queries_btn|export_excel_btn|"
                        r"full_health_btn|latency_btn|"
                        r"databases_btn|autotune_btn|files_btn|"
                        r"refresh_btn)$"
                    ),
                ))
                logger.info(
                    "✅ [ORDER 5/6] handlers_analytics (fallback يدوي): "
                    "13 زر مُسجّل — databases_btn + autotune_btn + files_btn ✅ "
                    "(لكن /databases, /versions, /analytics_reset, "
                    "/autotune, /files قد لا تعمل — يتطلب register_handlers "
                    "من v1.3.1+)"
                )
            except Exception as _e:
                logger.error(
                    "❌ [ORDER 5/6] فشل التسجيل اليدوي: %s",
                    _e, exc_info=True,
                )
        else:
            logger.warning(
                "⚠️ [ORDER 5/6] handlers_analytics غير متاح — "
                "أزرار التحليلات لن تعمل: %s",
                _ANALYTICS_HANDLERS_IMPORT_ERROR or "unknown",
            )

    # ═══ v5.7.0: Managed Bots handlers — قبل catch-all ═══
    try:
        from handlers.handlers_managed_bots import (
            register_managed_bots_handlers,
        )
        register_managed_bots_handlers(app)
        logger.info(
            "✅ [ORDER 5.5/6] managed_bots: "
            "لوحة الإدارة مُسجَّلة (pattern=r'^mb_')"
        )
    except Exception as _mb_e:
        logger.error(
            "❌ [ORDER 5.5/6] managed_bots handlers: %s",
            _mb_e, exc_info=True,
        )

    try:
        app.add_handler(CallbackQueryHandler(CallbackHandlers.handle))
        logger.info(
            "✅ [ORDER 6/6] CallbackHandlers.handle مُسجَّل — "
            "يُغطّي كل الأزرار غير المُلتقطة من channels_list "
            "(NAV_FIX v3.4.0 = trace-only، لا يُسجّله)"
        )
    except Exception as _e:
        logger.error(
            "❌ [ORDER 6/6] فشل تسجيل CallbackHandlers.handle: %s",
            _e, exc_info=True,
        )

    try:
        _handle_private_timed = _wrap_handler_with_timing(
            MessageHandlers.handle_private, "handle_private"
        )
        app.add_handler(MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL |
             filters.AUDIO | filters.VOICE | filters.ANIMATION | filters.Sticker.ALL |
             filters.VIDEO_NOTE) &
            filters.ChatType.PRIVATE & ~filters.COMMAND
            & ~filters.SUCCESSFUL_PAYMENT,
            _handle_private_timed
        ))
        logger.info("✅ handle_private مُسجَّل [timed]")
    except Exception as _e:
        logger.error("❌ فشل تسجيل handle_private: %s", _e, exc_info=True)
        app.add_handler(MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL |
             filters.AUDIO | filters.VOICE | filters.ANIMATION | filters.Sticker.ALL |
             filters.VIDEO_NOTE) &
            filters.ChatType.PRIVATE & ~filters.COMMAND
            & ~filters.SUCCESSFUL_PAYMENT,
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

    if _WARMUP_DETECTORS_TASK is not None and not _WARMUP_DETECTORS_TASK.done():
        _warmup_ok = await _await_warmup_detectors_pool(timeout=2.0)
        if _warmup_ok:
            logger.info(
                "✅ detectors pool: جاهز قبل أول رسالة حقيقية"
            )
        else:
            logger.info(
                "⏳ detectors pool: سيكمل في الخلفية "
                "(محمي بـ _SPAM_ASYNC_TIMEOUT=2.5s في handlers_message)"
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
                    await _run_post_stop_hooks(app)
                except Exception as _e:
                    logger.debug("_run_post_stop_hooks (webhook): %s", _e)

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
                "باستخدام start_polling() + app.start()"
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

        if _WARMUP_DETECTORS_TASK is not None and \
                not _WARMUP_DETECTORS_TASK.done():
            try:
                _WARMUP_DETECTORS_TASK.cancel()
                try:
                    await _WARMUP_DETECTORS_TASK
                except (asyncio.CancelledError, Exception):
                    pass
                logger.debug("🛑 warmup_detectors_pool: أُلغيت")
            except Exception as _e:
                logger.debug("cancel warmup task: %s", _e)

        if _GIL_LAG_MONITOR_TASK is not None and \
                not _GIL_LAG_MONITOR_TASK.done():
            try:
                _GIL_LAG_MONITOR_TASK.cancel()
                try:
                    await _GIL_LAG_MONITOR_TASK
                except (asyncio.CancelledError, Exception):
                    pass
                logger.debug("🛑 GIL-MONITOR: أُلغيت")
            except Exception as _e:
                logger.debug("cancel GIL monitor task: %s", _e)

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

        if _MAINT_CMDS_AVAILABLE and callable(stop_auto_vacuum_task):
            try:
                await stop_auto_vacuum_task(timeout=3.0)
            except Exception as _e:
                logger.debug("stop_auto_vacuum_task: %s", _e)

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

        if _sleep_probe_available:
            try:
                from sleep_probe import uninstall_sleep_probe as _sp_uninstall
                if _sp_uninstall():
                    logger.info("✅ sleep_probe: uninstalled")
            except Exception as _sp_u_e:
                logger.debug("sleep_probe uninstall: %s", _sp_u_e)

        if not app_shutdown_done:
            try:
                if getattr(app, "running", False):
                    try:
                        await app.stop()
                        logger.info("✅ app.stop() اكتمل")
                    except Exception as _e:
                        logger.debug("app.stop: %s", _e)
            except Exception as _e:
                logger.debug("app.stop check: %s", _e)

            try:
                await app.shutdown()
                app_shutdown_done = True
                logger.info("✅ app.shutdown() اكتمل")
            except asyncio.CancelledError:
                raise
            except Exception as _e:
                logger.debug("app.shutdown: %s", _e)

        # ═══ v5.7.0: Managed Bots shutdown ═══
        try:
            from managed_bots_runner import stop_all_managed_bots
            await stop_all_managed_bots(timeout=15.0)
            logger.info(
                "✅ managed_bots: أُوقفت كل البوتات العامة"
            )
        except Exception as _mb_e:
            logger.warning(
                "⚠️ managed_bots shutdown: %s", _mb_e
            )

        try:
            await _shutdown_db_pool(timeout=5.0)
        except asyncio.CancelledError:
            raise
        except Exception as _e:
            logger.debug("_shutdown_db_pool: %s", _e)

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
            logger.info(
                "ℹ️ v5.6.44 FIX-GIL-CONTENTION: "
                "تم تجاوز install_default_executor عمداً — "
                "detectors pool (16 workers) منفصل عن default executor "
                "التطبيق (12 workers تلقائياً). "
                "هذا يقلل lag p90 من ~372ms إلى <100ms متوقع."
            )
        else:
            logger.debug(
                "install_default_executor غير متاح "
                "(detectors أقدم من v4.0.8) — لا يوجد ما نتجاوزه"
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