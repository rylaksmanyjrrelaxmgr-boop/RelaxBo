#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌿 Relax Manager – البوت الرئيسي (bot.py v5.7.16-AUTO-URL-LOG)
================================================================================
🆕 v5.7.16 (AUTO-URL-LOG — فوق v5.7.15):
    🟢 FIX-20: `_print_public_url_hint()` تطبع رابط النبض دائماً، حتى في polling mode.
    🟢 FIX-21: keep_alive() يطبع تلميح الرابط عند التعطيل.
    🟢 FIX-22: رسالة صريحة عند POLLING mode تطبع /health المتوقع.
    🟢 محفوظ: v5.7.15 (AUTO-HOSTNAME) + v5.7.14 (FIX-17..18) + v5.7.13 (P0..P3).
================================================================================
"""

import asyncio
import os
import logging
import traceback
import json
import re
import signal
import sys
import time
import aiohttp
import functools
import faulthandler
from datetime import datetime, timedelta, timezone
from html import escape as _html_escape
from urllib.parse import urlparse
from typing import Set, Any, Dict, Optional, List, Tuple, Callable, Awaitable
from aiohttp import web

if __name__ == "__main__":
    _existing_bot = sys.modules.get('bot')
    _main_mod = sys.modules.get('__main__')
    if _main_mod is None:
        print("🔴 __main__ not in sys.modules", file=sys.stderr)
    elif _existing_bot is None:
        sys.modules['bot'] = _main_mod
        print("🔗 sys.modules['bot'] = __main__", file=sys.stderr)
    elif _existing_bot is not _main_mod:
        print("🔴 sys.modules['bot'] already exists as SEPARATE", file=sys.stderr)

from telegram import (
    BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats,
    BotCommandScopeChat, BotCommandScopeDefault,
    Update as _TgUpdate,
)

try:
    from telegram import ReplyParameters
    _HAS_REPLY_PARAMETERS = True
except ImportError:
    ReplyParameters = None
    _HAS_REPLY_PARAMETERS = False

from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatJoinRequestHandler, filters, PreCheckoutQueryHandler,
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
    _MARK_PROCESS_START_FN = getattr(_db_diag_mod, "mark_process_start", None)
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
from handlers import CommandHandlers, CallbackHandlers, MessageHandlers, chat_member

register_membership_handlers = None
_MEMBERSHIP_AVAILABLE = False
_MEMBERSHIP_IMPORT_ERROR = None
_MEMBERSHIP_SOURCE = None

try:
    from handlers_membership import register_handlers as _r1
    register_membership_handlers = _r1
    _MEMBERSHIP_AVAILABLE = True
    _MEMBERSHIP_SOURCE = 'standalone'
except ImportError as _e1:
    try:
        from handlers.handlers_membership import register_handlers as _r2
        register_membership_handlers = _r2
        _MEMBERSHIP_AVAILABLE = True
        _MEMBERSHIP_SOURCE = 'standalone'
    except ImportError as _e2:
        try:
            from handlers_callback import register_membership_handlers as _r3
            register_membership_handlers = _r3
            _MEMBERSHIP_AVAILABLE = True
            _MEMBERSHIP_SOURCE = 'embedded'
        except ImportError as _e3:
            try:
                from handlers.handlers_callback import register_membership_handlers as _r4
                register_membership_handlers = _r4
                _MEMBERSHIP_AVAILABLE = True
                _MEMBERSHIP_SOURCE = 'embedded'
            except ImportError as _e4:
                _MEMBERSHIP_IMPORT_ERROR = f"standalone: {_e1}/{_e2} | embedded: {_e3}/{_e4}"

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
        cmd_fullhealth as _cf,
        cmd_latency as _cl,
    )
    _cmd_fullhealth = _cf
    _cmd_latency = _cl
    _ANALYTICS_HANDLERS_AVAILABLE = True
except ImportError as _e_an1:
    try:
        from handlers_analytics import (
            handle_analytics_callback as _handle_analytics_callback,
            show_analytics_menu as _show_analytics_menu,
            cmd_fullhealth as _cf,
            cmd_latency as _cl,
        )
        _cmd_fullhealth = _cf
        _cmd_latency = _cl
        _ANALYTICS_HANDLERS_AVAILABLE = True
    except ImportError as _e_an2:
        _ANALYTICS_HANDLERS_IMPORT_ERROR = f"{_e_an1} | {_e_an2}"

try:
    from handlers.handlers_analytics import register_handlers as _ra1
    if callable(_ra1):
        _register_analytics_handlers = _ra1
        _ANALYTICS_REGISTER_AVAILABLE = True
except ImportError:
    try:
        from handlers_analytics import register_handlers as _ra2
        if callable(_ra2):
            _register_analytics_handlers = _ra2
            _ANALYTICS_REGISTER_AVAILABLE = True
    except ImportError:
        pass
except Exception:
    pass

_SPAM_DETECTOR_AVAILABLE = False
_SPAM_DETECTOR_IMPORT_ERROR = None
_SPAM_DETECTOR_VERSION = None
_SPAM_DETECTOR_LAYERS_COUNT = 0
_detectors_module = None

for _mod_path in ("handlers_message_detectors", "handlers.handlers_message_detectors"):
    try:
        from importlib import import_module
        _detectors_module = import_module(_mod_path)
        _SPAM_DETECTOR_AVAILABLE = True
        break
    except ImportError as _e:
        _SPAM_DETECTOR_IMPORT_ERROR = str(_e)
    except Exception as _e:
        _SPAM_DETECTOR_IMPORT_ERROR = f"unexpected: {_e}"

_shutdown_detector_pool_fn = None
_install_default_executor_fn = None
_shutdown_default_executor_fn = None
_DETECTORS_HAS_SHUTDOWN_HELPER = False
_DETECTORS_HAS_INSTALL_HELPER = False

if _SPAM_DETECTOR_AVAILABLE and _detectors_module is not None:
    try:
        _SPAM_DETECTOR_VERSION = getattr(_detectors_module, "_DETECTORS_VERSION", None)
        _lw = getattr(_detectors_module, "LAYER_WEIGHTS", {})
        _SPAM_DETECTOR_LAYERS_COUNT = len(_lw) if isinstance(_lw, dict) else 0
    except Exception:
        pass
    try:
        _shutdown_detector_pool_fn = getattr(_detectors_module, "_shutdown_shared_pool", None)
        _shutdown_default_executor_fn = getattr(_detectors_module, "shutdown_default_executor", None)
        _install_default_executor_fn = getattr(_detectors_module, "install_default_executor", None)
        _DETECTORS_HAS_SHUTDOWN_HELPER = callable(_shutdown_default_executor_fn)
        _DETECTORS_HAS_INSTALL_HELPER = callable(_install_default_executor_fn)
    except Exception:
        pass

_SECURITY_BRIDGE_AVAILABLE = False
_SB_IMPORT_ERROR = None
try:
    from utils import (
        SECURITY_TOGGLE_MAP, NEW_SECURITY_DEFAULTS, get_security_settings,
        invalidate_security_settings_cache, should_delete_by_security, check_all_security,
    )
    _SECURITY_BRIDGE_AVAILABLE = True
except ImportError as _sb_e:
    _SB_IMPORT_ERROR = str(_sb_e)
except Exception as _sb_e:
    _SB_IMPORT_ERROR = f"unexpected: {_sb_e}"

try:
    from database_tables import (
        _cleanup_old_admin_logs_postgres as _cleanup_admin_logs_pg,
        _cleanup_old_admin_logs_sqlite as _cleanup_admin_logs_sqlite,
        _cleanup_old_admin_logs_mysql as _cleanup_admin_logs_mysql,
        ADMIN_LOGS_RETENTION_DAYS, ADMIN_LOGS_MAX_ROWS,
    )
    _ADMIN_LOGS_CLEANUP_AVAILABLE = True
except ImportError as _e:
    _cleanup_admin_logs_pg = None
    _cleanup_admin_logs_sqlite = None
    _cleanup_admin_logs_mysql = None
    ADMIN_LOGS_RETENTION_DAYS = 30
    ADMIN_LOGS_MAX_ROWS = 5000
    _ADMIN_LOGS_CLEANUP_AVAILABLE = False

register_delete_confirmation = None
_CH_DELETE_AVAILABLE = False
_CH_DELETE_IMPORT_ERROR = None

try:
    from handlers.handlers_channels_delete import register_delete_confirmation as _r
    register_delete_confirmation = _r
    _CH_DELETE_AVAILABLE = True
except ImportError:
    try:
        from handlers_channels_delete import register_delete_confirmation as _r
        register_delete_confirmation = _r
        _CH_DELETE_AVAILABLE = True
    except ImportError as _e2:
        _CH_DELETE_IMPORT_ERROR = str(_e2)

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

_warmup_detectors_pool_fn = None
_HAS_WARMUP_DETECTORS = False

try:
    from handlers.handlers_message import warmup_detectors_pool as _w
    if callable(_w):
        _warmup_detectors_pool_fn = _w
        _HAS_WARMUP_DETECTORS = True
except ImportError:
    try:
        from handlers_message import warmup_detectors_pool as _w
        if callable(_w):
            _warmup_detectors_pool_fn = _w
            _HAS_WARMUP_DETECTORS = True
    except ImportError:
        pass

_HAS_DB_IDLE_CMD = False
_handle_db_idle_command = None

try:
    from handlers.handlers_message import handle_db_idle_command as _h
    _handle_db_idle_command = _h
    _HAS_DB_IDLE_CMD = True
except ImportError:
    try:
        from handlers_message import handle_db_idle_command as _h
        _handle_db_idle_command = _h
        _HAS_DB_IDLE_CMD = True
    except ImportError:
        pass

_HAS_CACHE_STATS_CMD = False
_handle_cache_stats_command = None

try:
    from handlers.handlers_message import handle_cache_stats_command as _h
    _handle_cache_stats_command = _h
    _HAS_CACHE_STATS_CMD = True
except ImportError:
    try:
        from handlers_message import handle_cache_stats_command as _h
        _handle_cache_stats_command = _h
        _HAS_CACHE_STATS_CMD = True
    except ImportError:
        pass

register_maintenance_commands = None
start_weekly_diagnostic_task = None
stop_weekly_diagnostic_task = None
stop_auto_vacuum_task = None
_MAINT_CMDS_AVAILABLE = False
_MAINT_CMDS_IMPORT_ERROR = None
_MAINT_REGISTER_NAMES = (
    "register_maintenance_commands", "register", "register_commands",
    "setup_commands", "setup", "register_maintenance", "register_db_maintenance",
)

try:
    import db_maintenance_commands as _maint_mod
    _mod_import_ok = True
except ImportError as _e_mod:
    _mod_import_ok = False
    _MAINT_CMDS_IMPORT_ERROR = str(_e_mod)
    _maint_mod = None

if _mod_import_ok:
    try:
        start_weekly_diagnostic_task = getattr(_maint_mod, "start_weekly_diagnostic_task", None)
    except Exception:
        pass
    try:
        stop_weekly_diagnostic_task = getattr(_maint_mod, "stop_weekly_diagnostic_task", None)
    except Exception:
        pass
    try:
        stop_auto_vacuum_task = getattr(_maint_mod, "stop_auto_vacuum_task", None)
    except Exception:
        pass
    for _name in _MAINT_REGISTER_NAMES:
        _fn = getattr(_maint_mod, _name, None)
        if callable(_fn):
            register_maintenance_commands = _fn
            _MAINT_CMDS_AVAILABLE = True
            break
    if not _MAINT_CMDS_AVAILABLE:
        _MAINT_CMDS_IMPORT_ERROR = "لم أجد دالة register: " + ", ".join(_MAINT_REGISTER_NAMES)

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

try:
    from handlers.handlers_group_log import register_group_log_handlers
    _GROUP_LOG_AVAILABLE = True
except ImportError as _e:
    register_group_log_handlers = None
    _GROUP_LOG_AVAILABLE = False

try:
    from group_log import init_group_log as _init_group_log
    _GROUP_LOG_INIT_AVAILABLE = True
except ImportError:
    _init_group_log = None
    _GROUP_LOG_INIT_AVAILABLE = False

try:
    from maintenance import maintenance_loop as _maintenance_loop
    _MAINTENANCE_AVAILABLE = True
except ImportError:
    _maintenance_loop = None
    _MAINTENANCE_AVAILABLE = False

from utils import (
    TranslationManager, KeyboardFactory, BackgroundTasks,
    ErrorHandler, setup_webhook, safe_send,
    warmup_all, get_min_publish_interval,
)
from cache import cache_cleanup_task, user_cache, invalidate_user_cache

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL, logging.INFO)
)
for _noisy in ("httpx", "httpcore", "telegram.request", "telegram.ext.ExtBot", "aiohttp.access"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger("relax_bot")

# ═══════════════════════════════════════════════════════════════════
# 🔴 v5.7.14 FIX-17: faulthandler — التقاط stacks حقيقية عند GIL
# ═══════════════════════════════════════════════════════════════════
_GIL_DIAG_LOG = os.getenv("GIL_DIAG_LOG", "").strip()
_gil_diag_fd: Optional[int] = None
_GIL_DIAG_ENABLED = False

def _init_faulthandler() -> bool:
    global _gil_diag_fd, _GIL_DIAG_ENABLED
    if not _GIL_DIAG_LOG:
        _gil_diag_fd = None
        _GIL_DIAG_ENABLED = False
        logger.info("ℹ️ faulthandler: معطّل (GIL_DIAG_LOG فارغ)")
        return False
    try:
        _dir = os.path.dirname(_GIL_DIAG_LOG)
        if _dir:
            os.makedirs(_dir, exist_ok=True)
        _gil_diag_fd = os.open(
            _GIL_DIAG_LOG,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o644,
        )
        faulthandler.enable(file=_gil_diag_fd)
        _GIL_DIAG_ENABLED = True
        logger.info("🔍 FIX-17: faulthandler enabled → %s", _GIL_DIAG_LOG)
        return True
    except Exception as _e:
        _gil_diag_fd = None
        _GIL_DIAG_ENABLED = False
        logger.warning("⚠️ FIX-17: faulthandler failed — %s", _e)
        return False

def _shutdown_faulthandler() -> None:
    global _gil_diag_fd, _GIL_DIAG_ENABLED
    try:
        faulthandler.cancel_dump_traceback_later()
    except Exception:
        pass
    try:
        faulthandler.disable()
    except Exception:
        pass
    if _gil_diag_fd is not None:
        try:
            os.close(_gil_diag_fd)
        except Exception:
            pass
        _gil_diag_fd = None
    _GIL_DIAG_ENABLED = False

# ═══════════════════════════════════════════════════════════════════
# PID / KILL-PREVIOUS
# ═══════════════════════════════════════════════════════════════════
_PID_FILE_PATH = "/app/.bot.pid"
_KILL_TIMEOUT_SEC = 5.0
_TELEGRAM_RELEASE_TIMEOUT_SEC = 15.0

_FALLBACK_HOSTNAME = (os.getenv("FALLBACK_HOSTNAME", "")).strip()

logger.info("🔧 v5.7.16 init: _FALLBACK_HOSTNAME=%r", _FALLBACK_HOSTNAME)
logger.info("🔧 v5.7.16 init: RENDER_EXTERNAL_HOSTNAME=%r",
            os.getenv("RENDER_EXTERNAL_HOSTNAME", ""))
logger.info("🔧 v5.7.16 init: RENDER_EXTERNAL_URL=%r",
            os.getenv("RENDER_EXTERNAL_URL", ""))
logger.info("🔧 v5.7.16 init: ALLOW_POLLING=%r",
            os.getenv("ALLOW_POLLING", ""))

def _read_pid_file() -> Optional[int]:
    try:
        if not os.path.exists(_PID_FILE_PATH):
            return None
        with open(_PID_FILE_PATH, "r") as f:
            pid_str = f.read().strip()
            if pid_str:
                return int(pid_str)
    except (IOError, ValueError):
        pass
    return None

def _write_pid_file() -> None:
    try:
        os.makedirs(os.path.dirname(_PID_FILE_PATH), exist_ok=True)
        with open(_PID_FILE_PATH, "w") as f:
            f.write(str(os.getpid()))
        logger.info("📝 PID file written: %d", os.getpid())
    except IOError as e:
        logger.warning("_write_pid_file: %s", e)

def _remove_pid_file() -> None:
    try:
        if os.path.exists(_PID_FILE_PATH):
            if _read_pid_file() == os.getpid():
                os.remove(_PID_FILE_PATH)
                logger.info("🗑️ PID file removed")
    except Exception:
        pass

def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        return False
    except PermissionError:
        return True

def _pid_is_bot_process(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read().replace(b"\x00", b" ").decode("utf-8", errors="ignore")
        if not cmdline.strip():
            return False
        _has_bot_py = False
        for _part in cmdline.split():
            _base = os.path.basename(_part)
            if _base == "bot.py":
                _has_bot_py = True
                break
        if not _has_bot_py:
            return False
        try:
            _pid_cwd = os.readlink(f"/proc/{pid}/cwd")
            _my_cwd = os.getcwd()
            if os.path.realpath(_pid_cwd) != os.path.realpath(_my_cwd):
                logger.debug(
                    "_pid_is_bot_process(%d): cwd %r != %r — تجاهل",
                    pid, _pid_cwd, _my_cwd,
                )
                return False
        except (IOError, OSError):
            return False
        return True
    except (IOError, PermissionError, OSError):
        return False

def _force_kill_pid(pid: int, force: bool = False) -> bool:
    if pid == os.getpid():
        return False
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.kill(pid, sig)
        logger.warning("%s → PID %d", "💀 SIGKILL" if force else "🔪 SIGTERM", pid)
        return True
    except ProcessLookupError:
        return True
    except Exception as e:
        logger.warning("_force_kill_pid(%d): %s", pid, e)
        return False

def _find_bot_processes() -> List[int]:
    pids: List[int] = []
    current_pid = os.getpid()
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            if pid == current_pid:
                continue
            if _pid_is_bot_process(pid):
                pids.append(pid)
    except (IOError, OSError):
        pass
    return pids

async def _force_kill_previous_instance() -> int:
    killed_total = 0
    targets: Set[int] = set()
    old_pid = _read_pid_file()
    if old_pid and old_pid != os.getpid() and _is_process_alive(old_pid):
        if _pid_is_bot_process(old_pid):
            logger.warning("🔪 PID file يشير لنسخة قديمة نشطة: %d", old_pid)
            targets.add(old_pid)
        else:
            logger.warning(
                "⚠️ PID file يشير إلى %d لكنها ليست عملية bot.py في نفس المجلد — تجاهل",
                old_pid,
            )
    other_pids = _find_bot_processes()
    if other_pids:
        logger.warning("🔪 وجدت %d نسخة bot.py إضافية: %s", len(other_pids), other_pids)
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
        for pid in still_alive:
            _force_kill_pid(pid, force=True)
        await asyncio.sleep(1.0)
    final_alive = [p for p in targets if _is_process_alive(p)]
    if final_alive:
        logger.error("❌ %d عملية حية بعد SIGKILL: %s", len(final_alive), final_alive)
    else:
        logger.info("✅ كل النسخ القديمة انتهت (%d)", killed_total)
    _write_pid_file()
    return killed_total

async def _wait_for_telegram_release(timeout: float = _TELEGRAM_RELEASE_TIMEOUT_SEC) -> bool:
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
                me = await asyncio.wait_for(bot.get_me(), timeout=5.0)
                logger.info("✅ Telegram API جاهز (@%s) — attempt %d",
                            getattr(me, "username", "?"), attempts)
                return True
            except telegram.error.Conflict:
                logger.debug("⏳ Conflict — انتظار (attempt %d)", attempts)
                await asyncio.sleep(1.0)
            except asyncio.TimeoutError:
                logger.debug("⏳ get_me timeout (attempt %d)", attempts)
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.debug("⏳ get_me failed (%s) — retry", type(e).__name__)
                await asyncio.sleep(1.0)
        logger.warning("⚠️ Telegram لم يتحرر خلال %.0fs — متابعة", timeout)
        return False
    finally:
        try:
            await bot.close()
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════
# INIT-RETRY
# ═══════════════════════════════════════════════════════════════════
async def _initialize_with_retry(
    app: Application,
    max_attempts: int = 6,
) -> bool:
    try:
        import telegram as _tg
        _Conflict = _tg.error.Conflict
        _NetworkError = _tg.error.NetworkError
        _TimedOut = _tg.error.TimedOut
        _InvalidToken = _tg.error.InvalidToken
        _Unauthorized = _tg.error.Unauthorized
    except Exception:
        class _FakeTGError(Exception):
            pass
        _Conflict = _NetworkError = _TimedOut = _InvalidToken = _Unauthorized = _FakeTGError

    delay = 3.0
    for attempt in range(1, max_attempts + 1):
        try:
            await asyncio.wait_for(app.initialize(), timeout=30.0)
            logger.info("✅ app.initialize() نجح (attempt %d/%d)", attempt, max_attempts)
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "⚠️ INIT TIMEOUT (attempt %d/%d) >30s — retry in %.0fs",
                attempt, max_attempts, delay,
            )
        except _InvalidToken as _e:
            logger.error(
                "❌ INVALID TOKEN — تحقق من BOT_TOKEN: %s",
                str(_e)[:120],
            )
            return False
        except _Unauthorized as _e:
            logger.error(
                "❌ UNAUTHORIZED — BOT_TOKEN ملغى/محظور: %s",
                str(_e)[:120],
            )
            return False
        except _Conflict as _e:
            logger.warning(
                "⚠️ INIT CONFLICT (attempt %d/%d): %s — retry in %.0fs",
                attempt, max_attempts, str(_e)[:120], delay,
            )
            try:
                await app.bot.delete_webhook(drop_pending_updates=True)
            except Exception:
                pass
        except _NetworkError as _e:
            logger.warning(
                "⚠️ INIT NETWORK (attempt %d/%d): %s — retry in %.0fs",
                attempt, max_attempts, str(_e)[:120], delay,
            )
        except _TimedOut as _e:
            logger.warning(
                "⚠️ INIT TIMED-OUT (attempt %d/%d): %s — retry in %.0fs",
                attempt, max_attempts, str(_e)[:120], delay,
            )
        except Exception as _e:
            logger.warning(
                "⚠️ INIT UNEXPECTED (attempt %d/%d): %s: %s — retry in %.0fs",
                attempt, max_attempts, type(_e).__name__, str(_e)[:120], delay,
            )

        if attempt < max_attempts:
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                raise
            delay = min(delay * 1.5, 30.0)

    logger.error("❌ app.initialize() فشل بعد %d محاولات — الخروج", max_attempts)
    return False

# ═══════════════════════════════════════════════════════════════════
# SLEEP-PROBE
# ═══════════════════════════════════════════════════════════════════
_sleep_probe_available = False
try:
    from sleep_probe import auto_install as _sp_auto_install, is_installed as _sp_is_installed
    _sleep_probe_available = True
    try:
        _sp_activated = _sp_auto_install()
        if _sp_activated:
            logger.info("✅ sleep_probe: مُفعَّل")
    except Exception as _sp_install_e:
        logger.warning("⚠️ sleep_probe install: %s", _sp_install_e)
except ImportError:
    pass
except Exception as _sp_import_e:
    logger.warning("⚠️ sleep_probe import: %s", _sp_import_e)

def _log_db_diagnostics_status() -> None:
    if not _DB_DIAG_AVAILABLE:
        logger.info("ℹ️ db_diagnostics: غير متاح — %s", _DB_DIAG_IMPORT_ERROR or "missing")
        return
    if _MARK_PROCESS_START_FN is not None:
        logger.info("✅ db_diagnostics: v%s متاح", _DB_DIAG_VERSION)
    else:
        logger.warning("⚠️ db_diagnostics: v%s محمّل بلا mark_process_start", _DB_DIAG_VERSION)
    if _AUTOTUNE_AVAILABLE:
        logger.info("⚙️ auto-tuning: ✅ متاح")

_NOTIFY_SHUTDOWN_TIMEOUT = 5.0
_BG_TASKS_SHUTDOWN_TIMEOUT = 10.0
_WATCHER_INTERVAL = 30.0
_WATCHER_HEALTH_TIMEOUT = 5.0
_WATCHER_MAX_PROBE_FAILURES = 3
_REMOVED_CHANNELS_GRACE_DAYS = 30
_PM_INITIAL_DELAY_SEC = 120.0
_PM_IDLE_TX_ERROR_THRESHOLD = 3
_PM_UTIL_WARN_PCT = 80.0
_PM_UTIL_CRITICAL_PCT = 95.0

_PAYMENT_AMOUNT_EPSILON = 0.01
_DIAG_INCOMING = os.getenv("DIAG_INCOMING", "0").strip().lower() in ("1", "true", "yes", "on", "enabled")
_KEEP_ALIVE_INTERVAL_SEC = 180.0
_KEEP_ALIVE_INITIAL_DELAY = 30.0
_TG_WARMUP_TIMEOUT = 10.0
_PM_QUERY_TTL = 290.0
_pm_last_query_ts = 0.0
_pm_last_query_result: Optional[Dict[str, Any]] = None
_GIL_LAG_MONITOR_TASK: Optional[asyncio.Task] = None
_GIL_LAG_SAMPLES_MAX = 300
_GIL_LAG_HISTORY_WINDOW_SEC = 60.0
_GIL_LAG_WARN_MS = 1000.0
_GIL_LAG_ALERT_INTERVAL_SEC = 30.0
_GIL_LAG_BLOCKED_CUMULATIVE_WARN_MS = 5000.0
_HANDLER_SLOW_WARN_MS = 3000.0
_HANDLER_INFO_MS = 1500.0
_FAULTHANDLER_DUMP_INTERVAL_SEC = 2.0

_ADMIN_GUARD_WARNED = False

_ACTIVE_HANDLER: Dict[str, Any] = {"name": None, "start": 0.0, "chat_id": None}

_GROUP_CHAT_FILTER = filters.ChatType.GROUP | filters.ChatType.SUPERGROUP

_TG_TOKEN_RE = re.compile(r"^\d{8,10}:[A-Za-z0-9_-]{35}$")

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
    except Exception:
        pass

def _read_gil_dump_tail(max_bytes: int = 3000) -> str:
    if not _GIL_DIAG_ENABLED:
        return ""
    try:
        with open(_GIL_DIAG_LOG, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read()
    except Exception:
        return ""

def _wrap_handler_with_timing(handler: Callable, name: str) -> Callable:
    if not callable(handler):
        return handler

    @functools.wraps(handler)
    async def _timed(update, context):
        _prev = _ACTIVE_HANDLER.copy()
        _ACTIVE_HANDLER["name"] = name
        _ACTIVE_HANDLER["start"] = time.monotonic()
        try:
            _ACTIVE_HANDLER["chat_id"] = (
                update.effective_chat.id if getattr(update, "effective_chat", None) else None
            )
        except Exception:
            _ACTIVE_HANDLER["chat_id"] = None
        t0 = time.monotonic()

        _fh_armed = False
        if _GIL_DIAG_ENABLED:
            try:
                faulthandler.dump_traceback_later(
                    timeout=_FAULTHANDLER_DUMP_INTERVAL_SEC,
                    repeat=True,
                    file=_gil_diag_fd,
                    exit=False,
                )
                _fh_armed = True
            except Exception:
                pass

        try:
            return await handler(update, context)
        finally:
            if _fh_armed:
                try:
                    faulthandler.cancel_dump_traceback_later()
                except Exception:
                    pass

            elapsed_ms = (time.monotonic() - t0) * 1000.0
            try:
                if elapsed_ms >= _HANDLER_INFO_MS:
                    logger.info("⏱️ handler %s: %.0fms | chat=%s",
                                name, elapsed_ms, _ACTIVE_HANDLER.get("chat_id"))
                if elapsed_ms >= _HANDLER_SLOW_WARN_MS:
                    _stack_hint = ""
                    if _GIL_DIAG_ENABLED:
                        _tail = _read_gil_dump_tail(max_bytes=3000)
                        if _tail.strip():
                            _stack_hint = (
                                "\n🔍 FAULTHANDLER STACK (آخر dump):\n" + _tail
                            )
                    if not _stack_hint:
                        try:
                            _frames = traceback.extract_stack()
                            _relevant = [
                                f"  {f.filename.split('/')[-1]}:{f.lineno} in {f.name}"
                                for f in _frames[-6:]
                                if "handlers_message" in f.filename or "handlers/" in f.filename
                            ]
                            if _relevant:
                                _stack_hint = "\n" + "\n".join(_relevant)
                        except Exception:
                            pass
                    logger.warning(
                        "🐌 SLOW handler: %s took %.0fms | chat=%s%s",
                        name, elapsed_ms, _ACTIVE_HANDLER.get("chat_id"), _stack_hint,
                    )
            except Exception:
                pass
            _ACTIVE_HANDLER.update(_prev)
    return _timed

async def _gil_lag_monitor() -> None:
    logger.info("🔍 GIL-MONITOR: warn=%.0fms, cooldown=%.0fs",
                _GIL_LAG_WARN_MS, _GIL_LAG_ALERT_INTERVAL_SEC)
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
            if (lag_ms > _GIL_LAG_WARN_MS and (now - last_alert_ts) >= _GIL_LAG_ALERT_INTERVAL_SEC):
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
                active_elapsed = (now - _ACTIVE_HANDLER["start"]) if _ACTIVE_HANDLER.get("name") else 0.0
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
                try:
                    import gc as _gc_t
                    _gc_raw = _gc_t.get_count()
                    _gc_count = _gc_raw[0] if isinstance(_gc_raw, tuple) else int(_gc_raw)
                except Exception:
                    _gc_count = 0
                logger.warning(
                    "🔴 GIL-MONITOR: lag=%.0fms | p50=%.0f p90=%.0f p99=%.0f max=%.0f | "
                    "active=%s (%.1fs, chat=%s) | mem=%.0fMB tasks=%d gc=%d | cum=%.0fms/%.0fs",
                    lag_ms, p50, p90, p99, maxv,
                    active_name, active_elapsed, active_chat or "-",
                    _mem_mb, _task_count, _gc_count,
                    cumulative_blocked_ms, _GIL_LAG_HISTORY_WINDOW_SEC,
                )
                if cumulative_blocked_ms > _GIL_LAG_BLOCKED_CUMULATIVE_WARN_MS:
                    logger.error(
                        "🚨 GIL-MONITOR: تراكم %.0fms خلال %.0fs",
                        cumulative_blocked_ms, _GIL_LAG_HISTORY_WINDOW_SEC,
                    )
                    cumulative_blocked_ms = 0.0
        except asyncio.CancelledError:
            raise
        except Exception as _e:
            logger.debug("GIL-MONITOR error: %s", _e)

def _spawn_gil_lag_monitor() -> Optional[asyncio.Task]:
    global _GIL_LAG_MONITOR_TASK
    if _GIL_LAG_MONITOR_TASK is not None and not _GIL_LAG_MONITOR_TASK.done():
        return _GIL_LAG_MONITOR_TASK
    try:
        _GIL_LAG_MONITOR_TASK = asyncio.create_task(_gil_lag_monitor(), name="gil-lag-monitor")
        return _GIL_LAG_MONITOR_TASK
    except Exception as _e:
        logger.warning("⚠️ فشل بدء GIL-MONITOR: %s", _e)
        return None

def _build_http_request_pools():
    if not _HAS_HTTPX_REQUEST or HTTPXRequest is None:
        return None, None
    try:
        req_pool = HTTPXRequest(
            connection_pool_size=32, connect_timeout=15.0,
            read_timeout=20.0, write_timeout=20.0, pool_timeout=10.0,
        )
        upd_pool = HTTPXRequest(
            connection_pool_size=8, connect_timeout=15.0,
            read_timeout=65.0, write_timeout=30.0, pool_timeout=20.0,
        )
        logger.info("🚀 HTTPXRequest pools: req=32(read=20s) upd=8(read=65s, pool=20s)")
        return req_pool, upd_pool
    except TypeError:
        try:
            req_pool = HTTPXRequest(connection_pool_size=32)
            upd_pool = HTTPXRequest(connection_pool_size=8)
            logger.warning("⚠️ pools: fallback PTB-compat (تقليل المعاملات)")
            return req_pool, upd_pool
        except Exception:
            return None, None
    except Exception:
        return None, None

async def _warmup_telegram_api(app: Application) -> bool:
    try:
        me = await asyncio.wait_for(app.bot.get_me(), timeout=_TG_WARMUP_TIMEOUT)
        if me is not None:
            logger.info("✅ Telegram API: اتصال مُهيَّأ — @%s",
                        getattr(me, "username", "?"))
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
        logger.info("🛡️ Spam Detector: ✅ محمّل (%s, %d layers)",
                    _SPAM_DETECTOR_VERSION, _SPAM_DETECTOR_LAYERS_COUNT)
    else:
        logger.warning("⚠️ Spam Detector: ❌ %s", _SPAM_DETECTOR_IMPORT_ERROR)

def _log_security_bridge_status() -> None:
    if _SECURITY_BRIDGE_AVAILABLE:
        logger.info("🌉 Security Bridge: ✅ محمّل")
    else:
        logger.warning("⚠️ Security Bridge: غير متاح — %s", _SB_IMPORT_ERROR)

def _log_perf_tuning_status() -> None:
    try:
        _max_ch = getattr(CONFIG, "MAX_CHANNELS_PER_CYCLE", "?")
        logger.info("⚡ PERF Tuning: MAX_CHANNELS=%s | HTTPX_POOL=%s",
                    _max_ch, "32/8" if _HAS_HTTPX_REQUEST else "default")
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
    _missing = [
        k for k, v in {
            "channels_posts": CHANNELS_POSTS_MIXIN_AVAILABLE,
            "subscriptions": SUBSCRIPTIONS_MIXIN_AVAILABLE,
            "groups": GROUPS_MIXIN_AVAILABLE, "tickets": TICKETS_MIXIN_AVAILABLE,
            "contests": CONTESTS_MIXIN_AVAILABLE, "stats": STATS_MIXIN_AVAILABLE,
            "settings": SETTINGS_MIXIN_AVAILABLE, "points": POINTS_MIXIN_AVAILABLE,
            "backup": BACKUP_MIXIN_AVAILABLE, "reminders": REMINDERS_MIXIN_AVAILABLE,
            "analytics": ANALYTICS_MIXIN_AVAILABLE,
        }.items() if not v
    ]
    if _missing:
        logger.warning("⚠️ Mixins مفقودة: %s", _missing)
    else:
        logger.info("✅ كل الـ 11 Mixins محمّلة")
except Exception:
    pass

if _MAINTENANCE_AVAILABLE:
    logger.info("✅ maintenance محمّل")
if _DEV_LOG_AVAILABLE:
    logger.info("✅ _notify_dev_log متاح")
if _MEMBERSHIP_AVAILABLE:
    logger.info("✅ MembershipHandler متاح")
if _ADMIN_LOGS_CLEANUP_AVAILABLE:
    logger.info("✅ admin_logs cleanup متاح")
if _CH_DELETE_AVAILABLE:
    logger.info("✅ handlers_channels_delete متاح")
if _MAINT_CMDS_AVAILABLE:
    logger.info("✅ db_maintenance_commands متاح")
if _ANALYTICS_REGISTER_AVAILABLE:
    logger.info("✅ handlers_analytics.register_handlers متاح")

_log_spam_detector_status()
_log_security_bridge_status()
_log_db_diagnostics_status()
_log_perf_tuning_status()

_periodic_cleanup_callable: Optional[Callable] = None
try:
    import inspect as _inspect_pc
    _pc_fn = getattr(GroupRateLimiterManager, "periodic_cleanup_task", None)
    if _pc_fn is None:
        logger.warning("⚠️ periodic_cleanup_task غير موجود")
    else:
        _pc_sig = None
        try:
            _pc_sig = _inspect_pc.signature(_pc_fn)
        except (ValueError, TypeError):
            pass
        if _pc_sig is not None and 'self' in _pc_sig.parameters:
            try:
                _pc_mgr = GroupRateLimiterManager()
                _periodic_cleanup_callable = _pc_mgr.periodic_cleanup_task
                logger.info("✅ periodic_cleanup: bound via instance")
            except Exception as _pce:
                logger.warning("⚠️ periodic_cleanup: cannot instantiate — %s", _pce)
        else:
            _periodic_cleanup_callable = _pc_fn
            logger.info("✅ periodic_cleanup: static/classmethod")
except Exception as _pce:
    logger.warning("⚠️ periodic_cleanup inspect: %s", _pce)

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
    ("auto_publish", "📤 تبديل النشر"), ("auto_recycle", "♻️ تبديل التدوير"),
]

ADMIN_COMMANDS = [
    ("stats", "📊 الإحصائيات"), ("grant", "🎁 منح اشتراك"),
    ("set_min_interval", "⏱️ تعيين الفاصل"), ("admin", "👑 لوحة الأدمن"),
    ("broadcast", "📨 بث جماعي"), ("set_force", "🔒 اشتراك إجباري"),
    ("set_update_ch", "📢 قناة التحديثات"), ("set_log_ch", "📋 قناة السجلات"),
    ("add_admin", "👑 إضافة مشرف"), ("remove_admin", "🗑️ إزالة مشرف"),
    ("export_replies", "📤 تصدير الردود"), ("import_replies", "📥 استيراد الردود"),
    ("backup", "💾 نسخ احتياطي"), ("restore", "🔄 عرض النسخ"),
    ("db_diag", "🔬 تشخيص DB"), ("db_vacuum", "🧹 تنظيف DB"),
    ("db_diag_quick", "🔬 تقرير مختصر"), ("db_maintenance", "🧹 صيانة DB"),
    ("db_weekly", "📅 التقرير الأسبوعي"), ("autoblocked", "🚫 المحجوبة تلقائياً"),
    ("db_idle", "🔍 idle-in-transaction"), ("cache_stats", "📊 إحصائيات الكاش"),
    ("fullhealth", "🏥 التشخيص الشامل"), ("latency", "🔬 اختبار الكمون"),
    ("databases", "🗂️ قواعد البيانات"), ("ping", "🏓 قياس الكمون"),
    ("posts_stats", "📊 إحصائيات النشر"), ("autotune", "⚙️ ضبط autovacuum"),
    ("db_tune", "⚙️ ضبط (اختصار)"), ("analytics", "📊 التحليلات"),
    ("versions", "📦 الإصدارات"), ("analytics_reset", "🗑️ إبطال كاش"),
    ("files", "📂 ملفات المشروع"),
]

GROUP_COMMANDS = [
    ("syncgroup", "🔗 تفعيل"), ("security", "🛡️ الأمان"),
    ("panel", "📋 اللوحة"), ("lock", "🔒 قفل"),
    ("unlock", "🔓 فتح"), ("ban", "🚫 حظر"),
    ("mute", "🔇 كتم"), ("warn", "⚠️ تحذير"),
    ("kick", "👢 طرد"), ("restrict", "🔒 تقييد"),
    ("unban", "🔓 إلغاء حظر"), ("pin", "📌 تثبيت"),
]

async def _shutdown_detector_tasks(timeout: float = 3.0) -> None:
    if not _SPAM_DETECTOR_AVAILABLE or _detectors_module is None:
        return
    if _DETECTORS_HAS_SHUTDOWN_HELPER:
        try:
            try:
                _loop = asyncio.get_running_loop()
                result = _shutdown_default_executor_fn(_loop, timeout=timeout)
            except TypeError:
                result = _shutdown_default_executor_fn(timeout=timeout)
            if asyncio.iscoroutine(result):
                await asyncio.wait_for(result, timeout=timeout + 0.5)
            return
        except Exception:
            pass
    if callable(_shutdown_detector_pool_fn):
        try:
            result = _shutdown_detector_pool_fn()
            if asyncio.iscoroutine(result):
                await asyncio.wait_for(result, timeout=timeout)
        except Exception:
            pass

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
        logger.info("✅ DB.%s() — pool مغلق", _fn_name)
    except asyncio.TimeoutError:
        logger.warning("⚠️ DB.%s() timeout", _fn_name)
    except Exception:
        pass

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
    for method_name in ("get_admin_list", "get_all_admins", "get_admins"):
        if not hasattr(DB, method_name):
            continue
        try:
            result = getattr(DB, method_name)()
            if asyncio.iscoroutine(result):
                result = await result
            if result is None:
                continue
            if isinstance(result, dict):
                result = [result]
            if not result:
                continue
            for a in result:
                uid = a.get("user_id") if isinstance(a, dict) else a
                try:
                    if uid:
                        admin_ids.add(int(uid))
                except (TypeError, ValueError):
                    continue
            break
        except Exception:
            continue
    return sorted(admin_ids)

def _get_bot_token() -> str:
    env_token = os.getenv("BOT_TOKEN", "").strip()
    if env_token and _TG_TOKEN_RE.match(env_token):
        return env_token
    for attr in ("BOT_TOKEN", "TOKEN", "bot_token", "token"):
        try:
            val = getattr(CONFIG, attr, None)
            if isinstance(val, str):
                val_stripped = val.strip()
                if val_stripped and _TG_TOKEN_RE.match(val_stripped):
                    return val_stripped
        except Exception:
            continue
    if env_token:
        logger.warning("⚠️ BOT_TOKEN لا يطابق الصيغة القياسية — سيُستخدم كما هو")
        return env_token
    for attr in ("BOT_TOKEN", "TOKEN", "bot_token", "token"):
        try:
            val = getattr(CONFIG, attr, None)
            if isinstance(val, str) and val.strip():
                logger.warning("⚠️ CONFIG.%s لا يطابق الصيغة القياسية — سيُستخدم", attr)
                return val.strip()
        except Exception:
            continue
    return ""

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

_CRITICAL_COMMANDS = (
    "start", "help_command", "subscribe", "stats", "admin",
    "db_diag", "db_vacuum", "broadcast", "grant", "backup", "restore",
)
_OPTIONAL_COMMANDS = (
    "trial", "support", "developer", "language", "contests",
    "replies_command", "set_min_interval", "gift_plans",
    "redeem_gift", "mood", "set_force", "set_update_ch",
    "set_log_ch", "add_admin", "remove_admin", "export_replies",
    "import_replies", "auto_publish",
    "auto_recycle", "channels", "posts", "syncgroup", "security",
    "panel", "lock", "unlock", "ban", "mute", "warn", "kick",
    "restrict", "unban", "pin",
    "register_hidden_owner", "remove_hidden_owner",
    "add_hidden_admin", "remove_hidden_admin", "list_hidden_admins",
)

def _verify_command_handlers() -> bool:
    missing_critical = [
        n for n in _CRITICAL_COMMANDS
        if not callable(getattr(CommandHandlers, n, None))
    ]
    missing_optional = [
        n for n in _OPTIONAL_COMMANDS
        if not callable(getattr(CommandHandlers, n, None))
    ]
    if missing_critical:
        logger.error("❌ دوال حرجة مفقودة: %s", missing_critical)
        return False
    if missing_optional:
        logger.warning("⚠️ دوال اختيارية مفقودة (لن تُسجَّل أوامرها): %s",
                       missing_optional)
    _total = len(_CRITICAL_COMMANDS) + len(_OPTIONAL_COMMANDS)
    logger.info("✅ %d/%d دالة CommandHandlers موجودة",
                _total - len(missing_optional), _total)
    return True

def _verify_db_config() -> bool:
    try:
        db_type = str(getattr(DB, "DB_TYPE", "unknown")).upper()
        logger.info("✅ DB type (pre-init): %s", db_type)
        if db_type not in ("SQLITE", "POSTGRES", "MYSQL", "UNKNOWN"):
            logger.warning("⚠️ DB type غير معروف: %s — تحقق من الإعدادات", db_type)
        return True
    except Exception as _e:
        logger.warning("⚠️ DB verify (pre-init): %s", _e)
        return True

def _init_group_log_instance(app) -> bool:
    global _GROUP_LOG_INSTANCE
    if _GROUP_LOG_INSTANCE is not None:
        logger.debug("group_log already initialized — skip")
        return True
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
        logger.error("❌ GroupLog: %s", e)
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
    except Exception:
        pass
    finally:
        _GROUP_LOG_INSTANCE = None

async def cleanup_admin_logs_periodically() -> None:
    if not _ADMIN_LOGS_CLEANUP_AVAILABLE:
        return
    if not hasattr(DB, "connection"):
        logger.warning("⚠️ DB.connection() غير متاح — إيقاف admin_logs cleanup")
        return
    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        raise
    while True:
        try:
            db_type = str(getattr(DB, "DB_TYPE", "sqlite")).lower().strip()
            deleted = 0
            _conn_cm = DB.connection()
            if asyncio.iscoroutine(_conn_cm):
                _conn_cm = await _conn_cm
            async with _conn_cm as conn:
                if db_type.startswith("postgres") and _cleanup_admin_logs_pg is not None:
                    deleted = await _cleanup_admin_logs_pg(conn, logger)
                elif db_type in ("mysql", "mariadb") and _cleanup_admin_logs_mysql is not None:
                    deleted = await _cleanup_admin_logs_mysql(conn, logger)
                elif _cleanup_admin_logs_sqlite is not None:
                    deleted = await _cleanup_admin_logs_sqlite(conn, logger)
            if deleted:
                logger.info("✅ admin_logs cleanup: %d صف", deleted)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("❌ cleanup_admin_logs: %s", e)
        try:
            await asyncio.sleep(86400)
        except asyncio.CancelledError:
            raise

async def cleanup_removed_channels_periodically() -> None:
    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        raise
    while True:
        try:
            deleted = 0
            if hasattr(DB, 'hard_delete_removed_channels_before'):
                cutoff_dt = TimeUtils.utc_now() - timedelta(days=_REMOVED_CHANNELS_GRACE_DAYS)
                deleted = await DB.hard_delete_removed_channels_before(cutoff_dt)
            if deleted:
                logger.info("✅ removed_channels cleanup: %d", deleted)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("❌ cleanup_removed_channels: %s", e)
        try:
            await asyncio.sleep(86400)
        except asyncio.CancelledError:
            raise

async def _validate_invoice_for_payment(user_id: int, payload: str):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None, None, None, "invalid_payload"
    invoice_number = data.get('invoice')
    if not invoice_number:
        return None, None, None, "missing_invoice"
    try:
        invoice = await DB.get_invoice(invoice_number)
    except Exception as _e:
        logger.error("DB.get_invoice(%s) failed: %s", invoice_number, _e)
        return None, None, None, "db_error"
    if (not invoice or invoice.get('user_id') != user_id
            or invoice.get('status') != 'pending' or not invoice.get('number')):
        return None, None, None, "invoice_invalid"
    payment_type = data.get('type')
    if payment_type not in ('subscription', 'gift'):
        return None, None, None, "type_invalid"
    plan_id = (data.get('plan_id') if payment_type == 'subscription'
               else data.get('gift_plan_id'))
    if not plan_id:
        return None, None, None, "plan_missing"
    try:
        plan = (await DB.get_plan(plan_id) if payment_type == 'subscription'
                else await DB.get_gift_plan(plan_id))
    except Exception as _e:
        logger.error("DB.get_plan(%s) failed: %s", plan_id, _e)
        return None, None, None, "db_error"
    if not plan:
        return None, None, None, "plan_missing"
    return invoice, plan, data, None

async def pre_checkout(update, context):
    query = update.pre_checkout_query
    user_id = query.from_user.id
    invoice, plan, data, err = await _validate_invoice_for_payment(user_id, query.invoice_payload)
    if err == "db_error":
        try:
            await query.answer(ok=False, error_message="خطأ تقني مؤقت. حاول بعد قليل.")
        except Exception:
            pass
        return
    if invoice is None or plan is None:
        try:
            await query.answer(ok=False, error_message="الفاتورة غير صالحة.")
        except Exception:
            pass
        return
    try:
        q_currency = getattr(query, 'currency', None)
        if q_currency and q_currency != "XTR":
            await query.answer(ok=False, error_message="العملة غير مدعومة.")
            return
    except Exception:
        pass
    if hasattr(query, 'total_amount'):
        try:
            _price_raw = plan.get('price')
            expected_f = float(_price_raw) if _price_raw is not None else 0.0
        except (TypeError, ValueError):
            logger.error(
                "pre_checkout: plan %s price غير صالح (%r) — رفض",
                plan.get('id'), plan.get('price'),
            )
            try:
                await query.answer(ok=False, error_message="خطأ في بيانات الخطة. تواصل مع الدعم.")
            except Exception:
                pass
            return
        if expected_f <= 0:
            logger.error(
                "pre_checkout: plan %s price غير موجب (%r) — رفض",
                plan.get('id'), plan.get('price'),
            )
            try:
                await query.answer(ok=False, error_message="الخطة غير متاحة للدفع حالياً.")
            except Exception:
                pass
            return
        if not _amounts_match(expected_f, query.total_amount):
            try:
                await query.answer(ok=False, error_message="المبلغ غير مطابق.")
            except Exception:
                pass
            return
    try:
        await query.answer(ok=True)
    except Exception:
        pass

async def successful_payment(update, context):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    invoice, plan, data, err = await _validate_invoice_for_payment(user_id, payment.invoice_payload)
    if err == "db_error":
        await safe_send(
            context.bot, user_id,
            "⚠️ خطأ تقني مؤقت في قاعدة البيانات. سيتم التحقق من الدفع تلقائياً لاحقاً."
        )
        return
    if invoice is None or plan is None:
        try:
            _pd = json.loads(payment.invoice_payload)
            if _pd.get('invoice'):
                _existing = await DB.get_invoice(_pd['invoice'])
                if (_existing and _existing.get('user_id') == user_id
                        and _existing.get('status') == 'paid'):
                    await safe_send(context.bot, user_id, "✅ الفاتورة معالجة مسبقاً.")
                    return
        except Exception:
            pass
        await safe_send(context.bot, user_id, "❌ خطأ في معالجة الدفع.")
        return
    payment_id = payment.telegram_payment_charge_id or payment.provider_payment_charge_id
    if not payment_id:
        await safe_send(context.bot, user_id, "❌ بيانات الدفع غير صالحة.")
        return
    plan_name = plan.get('name', 'الخطة')
    if data.get('type') == 'subscription':
        try:
            success = await DB.activate_subscription_with_payment(
                user_id=user_id, invoice_number=invoice['number'],
                payment_id=payment_id, plan_id=plan['id'],
            )
        except Exception:
            success = False
        if success:
            await safe_send(context.bot, user_id, f"✅ تم تفعيل اشتراك {plan_name}!")
            try:
                await invalidate_user_cache(user_id)
            except Exception:
                pass
        else:
            await safe_send(context.bot, user_id, "⚠️ الدفع مستلم لكن التفعيل فشل.")
    elif data.get('type') == 'gift':
        try:
            paid = await DB.mark_invoice_paid(invoice['number'], payment_id)
        except Exception:
            paid = False
        if paid:
            try:
                code = await DB.create_gift_code(plan_id=plan['id'], creator_id=user_id)
            except Exception as _e:
                logger.error("create_gift_code(%s) exception: %s", plan['id'], _e)
                try:
                    await _notify_dev_log(
                        context,
                        f"⚠️ gift_code exception — invoice={invoice['number']} "
                        f"plan={plan['id']} err={str(_e)[:120]}",
                    )
                except Exception:
                    pass
                await safe_send(
                    context.bot, user_id,
                    "⚠️ تم استلام دفعك لكن إنشاء كود الهدية فشل. "
                    "تواصل مع الدعم مع رقم الفاتورة: "
                    f"<code>{_html_escape(str(invoice['number']))}</code>",
                    parse_mode='HTML',
                )
                return
            if code:
                await safe_send(
                    context.bot, user_id,
                    f"🎉 كود الهدية: <code>{_html_escape(str(code))}</code>",
                    parse_mode='HTML',
                )
            else:
                logger.error(
                    "create_gift_code(%s) returned None — invoice=%s",
                    plan['id'], invoice['number'],
                )
                try:
                    await _notify_dev_log(
                        context,
                        f"⚠️ gift_code None — invoice={invoice['number']} "
                        f"plan={plan['id']} user={user_id}",
                    )
                except Exception:
                    pass
                await safe_send(
                    context.bot, user_id,
                    "⚠️ تم استلام دفعك لكن كود الهدية لم يُنشأ. "
                    f"تواصل مع الدعم مع رقم الفاتورة: "
                    f"<code>{_html_escape(str(invoice['number']))}</code>",
                    parse_mode='HTML',
                )

async def keep_alive():
    try:
        await asyncio.sleep(_KEEP_ALIVE_INITIAL_DELAY)
    except asyncio.CancelledError:
        raise
    url = (os.getenv("KEEP_ALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL"))
    if not url:
        logger.info("ℹ️ keep_alive: معطّل (لا KEEP_ALIVE_URL / RENDER_EXTERNAL_URL)")
        # 🆕 v5.7.16 FIX-21: اطبع تلميح الرابط حتى عند التعطيل
        _h = (os.getenv("RENDER_EXTERNAL_HOSTNAME") or "").strip()
        if _h:
            logger.info("💡 تلميح: جرّب https://%s/health يدوياً", _h)
        else:
            logger.info(
                "💡 تلميح: على Render → Dashboard → أعلى صفحة الخدمة → URL، "
                "ثم أضف /health"
            )
        await asyncio.Event().wait()
        return
    url = url.rstrip('/')
    health_url = f"{url}/health"
    _timeout = aiohttp.ClientTimeout(total=15, connect=5)
    _connector = aiohttp.TCPConnector(limit=2, ttl_dns_cache=300, keepalive_timeout=60)
    logger.info("💓 keep_alive: %s (كل %.0fs)", health_url, _KEEP_ALIVE_INTERVAL_SEC)
    async with aiohttp.ClientSession(timeout=_timeout, connector=_connector) as session:
        while True:
            try:
                await asyncio.sleep(_KEEP_ALIVE_INTERVAL_SEC)
                async with session.get(health_url) as response:
                    await response.read()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

async def _fetch_pg_activity_cached() -> Dict[str, Any]:
    global _pm_last_query_ts, _pm_last_query_result
    now = time.monotonic()
    if _pm_last_query_result is not None and (now - _pm_last_query_ts) < _PM_QUERY_TTL:
        return _pm_last_query_result
    try:
        row = await DB.fetchone(
            "SELECT count(*) AS total, count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_tx "
            "FROM pg_stat_activity WHERE datname = current_database()"
        )
        data = row if isinstance(row, dict) else (dict(row) if row else {})
        _pm_last_query_ts = now
        _pm_last_query_result = data
        return data
    except Exception:
        return {}

async def pool_health_monitor() -> None:
    try:
        _max_conn = int(os.getenv("PG_MAX_CONNECTIONS", "20"))
        if _max_conn <= 0:
            _max_conn = 20
    except (TypeError, ValueError):
        _max_conn = 20
    try:
        await asyncio.sleep(_PM_INITIAL_DELAY_SEC)
    except asyncio.CancelledError:
        raise
    while True:
        try:
            db_type = str(getattr(DB, "DB_TYPE", "sqlite")).lower().strip()
            if not db_type.startswith("postgres"):
                await asyncio.sleep(1800)
                continue
            data = await _fetch_pg_activity_cached()
            total = int(data.get("total") or 0)
            idle_in_tx = int(data.get("idle_in_tx") or 0)
            util_pct = (total / _max_conn * 100) if total else 0
            if idle_in_tx >= _PM_IDLE_TX_ERROR_THRESHOLD or util_pct >= _PM_UTIL_CRITICAL_PCT:
                logger.error(
                    "🔴 pool CRITICAL: total=%d/%d idle_tx=%d util=%.0f%%",
                    total, _max_conn, idle_in_tx, util_pct,
                )
            elif util_pct >= _PM_UTIL_WARN_PCT:
                logger.warning(
                    "⚠️ pool DIAG: total=%d/%d util=%.0f%%",
                    total, _max_conn, util_pct,
                )
            else:
                logger.info(
                    "🟢 pool HEALTH: total=%d/%d util=%.0f%%",
                    total, _max_conn, util_pct,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        try:
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            raise

def _resolve_hostname() -> Optional[str]:
    for var in (
        "RENDER_EXTERNAL_HOSTNAME", "RENDER_EXTERNAL_URL",
        "RAILWAY_PUBLIC_DOMAIN", "WEBHOOK_URL", "PUBLIC_URL",
        "BOT_HOSTNAME", "FLY_APP_NAME",
    ):
        val = (os.getenv(var) or "").strip()
        if not val:
            continue
        if val.startswith("http"):
            try:
                n = urlparse(val).netloc
                if n:
                    logger.info("✅ HOSTNAME from %s: %s", var, n)
                    return n
            except Exception:
                continue
        else:
            logger.info("✅ HOSTNAME from %s: %s", var, val)
            return val
    heroku_app = (os.getenv("HEROKU_APP_NAME") or "").strip()
    if heroku_app:
        return f"{heroku_app}.herokuapp.com"
    if _FALLBACK_HOSTNAME:
        logger.warning("🚨 NO HOSTNAME — FALLBACK_HOSTNAME (env): %s", _FALLBACK_HOSTNAME)
        return _FALLBACK_HOSTNAME
    logger.error("❌ FATAL: no hostname and _FALLBACK_HOSTNAME empty")
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
        if 1 <= port <= 65535:
            return port
    except (TypeError, ValueError):
        pass
    return default_port

# 🆕 v5.7.16 FIX-20: اطبع رابط النبض دائماً، حتى في polling mode
def _print_public_url_hint(port: int, hostname: Optional[str]) -> None:
    """
    يطبع رابط النبض بغض النظر عن وضع التشغيل:
      • webhook mode: يعرض https://{hostname}/health
      • polling mode: يحاول استخراج النطاق من env vars ليعرض الرابط المتوقع
      • لا شيء متاح: يطبع تعليمات واضحة
    """
    # 1) المسار الطبيعي: webhook mode
    if hostname:
        logger.info("🌐 PUBLIC URL: https://%s", hostname)
        logger.info("💓 HEALTH URL: https://%s/health", hostname)
        return

    # 2) polling mode: حاول استخراج النطاق من env vars مباشرة
    for var in (
        "RENDER_EXTERNAL_URL", "RENDER_EXTERNAL_HOSTNAME",
        "RAILWAY_PUBLIC_DOMAIN", "RAILWAY_STATIC_URL",
        "FLY_APP_NAME", "VERCEL_URL",
        "KEEP_ALIVE_URL", "PUBLIC_URL", "WEBHOOK_URL", "BOT_HOSTNAME",
    ):
        val = (os.getenv(var) or "").strip()
        if not val:
            continue
        _host = None
        if val.startswith("http"):
            try:
                _host = urlparse(val).netloc
            except Exception:
                _host = None
        else:
            _host = val
        if _host:
            logger.warning(
                "💓 HEALTH URL (from %s, POLLING mode): https://%s/health",
                var, _host,
            )
            logger.info(
                "ℹ️ البوت يعمل في polling، لكن الخادم المحلي يستمع على 0.0.0.0:%d. "
                "إذا كانت خدمتك Web Service على Render، فهذا الرابط يعمل من الخارج.",
                port,
            )
            return

    # 3) لا شيء متاح
    logger.warning(
        "⚠️ لا يمكن تحديد رابط النبض — لا hostname في أي env var.\n"
        "   المنفذ المحلي: 0.0.0.0:%d/health (يعمل داخلياً فقط)\n"
        "   على Render: Dashboard → أعلى صفحة الخدمة → URL، ثم أضف /health\n"
        "   لإيقاظ الخدمة تلقائياً: أضف env متغير KEEP_ALIVE_URL=https://<نطاقك>",
        port,
    )

async def _watch_runner(runner, shutdown_event: asyncio.Event, port: int) -> None:
    try:
        await asyncio.sleep(3.0)
    except asyncio.CancelledError:
        raise
    probe_failures = 0
    health_url = f"http://127.0.0.1:{port}/health"
    _timeout = aiohttp.ClientTimeout(total=_WATCHER_HEALTH_TIMEOUT, connect=2)
    _connector = aiohttp.TCPConnector(limit=2, ttl_dns_cache=60, keepalive_timeout=30)
    async with aiohttp.ClientSession(timeout=_timeout, connector=_connector) as session:
        while not shutdown_event.is_set():
            try:
                async with session.get(health_url) as resp:
                    await resp.read()
                    if 200 <= resp.status < 400:
                        probe_failures = 0
                    else:
                        probe_failures += 1
                        logger.warning(
                            "⚠️ health returned %d (%d/%d)",
                            resp.status, probe_failures, _WATCHER_MAX_PROBE_FAILURES,
                        )
                        if probe_failures >= _WATCHER_MAX_PROBE_FAILURES:
                            logger.error(
                                "❌ health probe failed %d مرات — إغلاق",
                                probe_failures,
                            )
                            shutdown_event.set()
                            return
                await asyncio.sleep(_WATCHER_INTERVAL)
            except asyncio.CancelledError:
                raise
            except Exception as _e:
                probe_failures += 1
                logger.debug("health probe failure %d/%d: %s",
                             probe_failures, _WATCHER_MAX_PROBE_FAILURES, _e)
                if probe_failures >= _WATCHER_MAX_PROBE_FAILURES:
                    logger.error("❌ health probe failed %d مرات — إغلاق",
                                 probe_failures)
                    shutdown_event.set()
                    return
                await asyncio.sleep(_WATCHER_INTERVAL)

async def run_task_with_retry(task_func, *args, task_name=""):
    consecutive_failures = 0
    while True:
        try:
            await task_func(*args)
            consecutive_failures = 0
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            consecutive_failures += 1
            logger.error("❌ Task %s crashed: %s", task_name, e)
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
            logger.error("❌ cleanup_locks: %s", e)
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
                    if winner_id:
                        try:
                            msg = f"🎉 <b>مبروك!</b>\n\nلقد فزت في <b>{_html_escape(str(w.get('title') or 'مسابقة'))}</b>!"
                            await app.bot.send_message(chat_id=winner_id, text=msg, parse_mode="HTML")
                        except Exception:
                            pass
                        try:
                            await asyncio.sleep(0.5)
                        except asyncio.CancelledError:
                            raise
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("❌ contest_cleanup: %s", e)
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise

async def _run_post_init_hooks(app: Application) -> None:
    if app.bot_data.get("_post_init_executed"):
        logger.debug("post_init already executed — skip")
        return
    app.bot_data["_post_init_executed"] = True
    _post_init = getattr(app, "_post_init", None) or getattr(app, "post_init", None)
    if not callable(_post_init):
        logger.debug("post_init غير مضبوط — skip")
        return
    logger.info("✅ post_init مُدار من PTB.initialize() — لا استدعاء يدوي")

async def _run_post_stop_hooks(app: Application) -> None:
    if app.bot_data.get("_post_stop_executed"):
        logger.debug("post_stop already executed — skip")
        return
    app.bot_data["_post_stop_executed"] = True
    _post_stop = getattr(app, "_post_stop", None) or getattr(app, "post_stop", None)
    if not callable(_post_stop):
        return
    try:
        await _post_stop(app)
        logger.info("✅ post_stop executed")
    except Exception as _e:
        logger.warning("post_stop hook failed: %s", _e)
    finally:
        try:
            if hasattr(app, "_post_stop"):
                app._post_stop = None
            elif hasattr(app, "post_stop"):
                try:
                    app.post_stop = None
                except (AttributeError, TypeError):
                    logger.debug("app.post_stop is read-only — relying on _post_stop_executed flag")
        except Exception as _e:
            logger.debug("post_stop unbind: %s", _e)

_polling_state = {"running": False}

async def _stop_polling_mode(app: Application) -> None:
    if not _polling_state["running"]:
        if app.updater is not None:
            try:
                if getattr(app.updater, "running", False):
                    await app.updater.stop()
            except Exception:
                pass
        return
    try:
        await _run_post_stop_hooks(app)
    finally:
        _polling_state["running"] = False
        if app.updater is not None:
            try:
                await app.updater.stop()
            except Exception:
                pass

async def _diag_incoming(update, context):
    try:
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat or chat.type not in ("group", "supergroup"):
            return
        try:
            markup = getattr(msg, "reply_markup", None)
            rows = getattr(markup, "inline_keyboard", None) or []
            btn_count = sum(len(r or []) for r in rows)
        except Exception:
            btn_count = 0
        fwd_origin = getattr(msg, "forward_origin", None)
        fwd_chat = getattr(msg, "forward_from_chat", None)
        logger.info(
            "📥 INCOMING | chat=%s msg=%s | text=%s caption=%s photo=%s "
            "video=%s doc=%s audio=%s voice=%s anim=%s sticker=%s vn=%s "
            "poll=%s | fwd_origin=%s fwd_chat=%s auto_fwd=%s | btn_count=%d",
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

def _resolve_admin_guard(context) -> Set[int]:
    global _ADMIN_GUARD_WARNED
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
        if not fallback and not _ADMIN_GUARD_WARNED:
            logger.warning(
                "⚠️ ADMIN GUARD: قائمة الأدمن فارغة — كل الأوامر الإدارية ستُرفض. "
                "تحقق من PRIMARY_OWNER_ID و DEVELOPER_IDS."
            )
            _ADMIN_GUARD_WARNED = True
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
        t0 = time.monotonic()
        try:
            if _HAS_REPLY_PARAMETERS and ReplyParameters is not None:
                sent = await msg.reply_text(
                    "🏓 قياس...",
                    reply_parameters=ReplyParameters(message_id=msg.message_id),
                )
            else:
                sent = await msg.reply_text("🏓 قياس...", reply_to_message_id=msg.message_id)
        except TypeError:
            sent = await msg.reply_text("🏓 قياس...")
        send_rtt_ms = int((time.monotonic() - t0) * 1000)
        try:
            record_bot_metric("pings_total", 1)
            record_bot_metric("ping_sum_ms", send_rtt_ms)
            _cur_min = _BOT_METRICS.get("ping_min_ms")
            if _cur_min is None or send_rtt_ms < _cur_min:
                _BOT_METRICS["ping_min_ms"] = send_rtt_ms
            _cur_max = _BOT_METRICS.get("ping_max_ms")
            if _cur_max is None or send_rtt_ms > _cur_max:
                _BOT_METRICS["ping_max_ms"] = send_rtt_ms
        except Exception:
            pass
        lines = ["🏓 <b>Pong</b>", "", f"⚡ <b>RTT:</b> <code>{send_rtt_ms}ms</code>"]
        try:
            await sent.edit_text("\n".join(lines), parse_mode='HTML')
        except Exception:
            pass
    except Exception as e:
        logger.error("❌ /ping error: %s", e)

async def cmd_posts_stats(update, context):
    user = update.effective_user
    if user is None:
        return
    allowed = _resolve_admin_guard(context)
    if not allowed or user.id not in allowed:
        return
    msg = update.effective_message
    if msg is None:
        return
    _db_type = str(getattr(DB, "DB_TYPE", "sqlite")).lower().strip()
    if _db_type.startswith("postgres"):
        _interval_24h = "NOW() - INTERVAL '24 hours'"
        _pub_true = "TRUE"
    elif _db_type in ("mysql", "mariadb"):
        _interval_24h = "NOW() - INTERVAL 24 HOUR"
        _pub_true = "1"
    else:
        _interval_24h = "datetime('now', '-24 hours')"
        _pub_true = "1"

    async def _try_count(sql: str):
        try:
            row = await DB.fetchone(sql)
            if row is None:
                return 0, None
            n = row.get('n', 0) if isinstance(row, dict) else (row[0] if row else 0)
            return int(n or 0), None
        except Exception as _e:
            return None, f"{type(_e).__name__}: {str(_e)[:60]}"

    cnt_total, _ = await _try_count("SELECT COUNT(*) AS n FROM posts")
    cnt_p1, err_p1 = await _try_count(
        f"SELECT COUNT(*) AS n FROM posts WHERE published = {_pub_true} AND created_at > {_interval_24h}"
    )
    if err_p1 and _db_type.startswith("postgres"):
        logger.debug("posts_stats: TRUE failed (%s) — fallback to 1", err_p1)
        cnt_p1, err_p1 = await _try_count(
            f"SELECT COUNT(*) AS n FROM posts WHERE published = 1 AND created_at > {_interval_24h}"
        )

    lines = ["📊 <b>إحصائيات النشر</b>", ""]
    lines.append(f"✅ total: <b>{cnt_total or 0}</b>")
    if err_p1:
        lines.append(f"⚠️ published (24h): <i>تعذّر الحساب</i>")
    else:
        lines.append(f"✅ published (24h): <b>{cnt_p1 or 0}</b>")
    uptime_s = int(time.monotonic() - _BOT_METRICS.get("started_at", time.monotonic()))
    lines.append(f"⏱️ uptime: <code>{uptime_s}s</code>")
    try:
        await msg.reply_text("\n".join(lines), parse_mode='HTML')
    except Exception:
        pass

async def _cmd_analytics_alias(update, context):
    try:
        if _show_analytics_menu is not None:
            return await _show_analytics_menu(update, context)
    except Exception as _e:
        logger.debug("_cmd_analytics_alias menu: %s", _e)
    try:
        msg = update.effective_message
        if msg:
            await msg.reply_text("📊 استخدم /analytics للوصول إلى هذه الميزة.")
    except Exception:
        pass

async def main():
    t_start = time.monotonic()
    _shutdown_event = asyncio.Event()

    def _on_shutdown_signal(sig_name: str):
        logger.info("🛑 تلقّيت %s", sig_name)
        _shutdown_event.set()

    try:
        _loop_for_signals = asyncio.get_running_loop()
        _signals_to_hook = [signal.SIGTERM, signal.SIGINT]
        if hasattr(signal, "SIGHUP"):
            _signals_to_hook.append(signal.SIGHUP)
        for _sig in _signals_to_hook:
            try:
                _loop_for_signals.add_signal_handler(
                    _sig, lambda s=_sig: _on_shutdown_signal(s.name)
                )
            except (NotImplementedError, RuntimeError, ValueError):
                pass
    except Exception:
        pass

    _init_faulthandler()

    logger.info("🔪 FORCE-KILL-PREVIOUS: بدء الفحص...")
    try:
        _killed = await _force_kill_previous_instance()
        if _killed > 0:
            logger.warning("🔪 قتلت %d نسخة قديمة", _killed)
    except Exception as _e:
        logger.warning("⚠️ فشل قتل النسخة القديمة: %s", _e)

    if _MARK_PROCESS_START_FN is not None:
        try:
            _MARK_PROCESS_START_FN()
            logger.info("🕐 mark_process_start()")
        except Exception:
            pass

    try:
        CONFIG.validate()
    except ValueError as e:
        logger.error("❌ %s", e)
        raise SystemExit(1)

    bot_token = _get_bot_token()
    if not bot_token:
        logger.error("❌ BOT_TOKEN غير محدّد أو غير صالح")
        raise SystemExit(1)

    logger.info("🌿 %s", CONFIG.BOT_NAME)
    logger.info("👨‍💼 المالك: %s", CONFIG.PRIMARY_OWNER_ID)

    logger.info(
        "📦 bot.py: v5.7.16 | kill_prev=on | init_retry=on | webhook_force=on | "
        "webhook_verify=on | diag_incoming=%r | "
        "detectors=%s | layers=%d | fallback_hostname=%r | "
        "allow_polling_env=%r | faulthandler=%s",
        _DIAG_INCOMING,
        _SPAM_DETECTOR_VERSION or "N/A",
        _SPAM_DETECTOR_LAYERS_COUNT,
        _FALLBACK_HOSTNAME,
        os.getenv("ALLOW_POLLING", ""),
        "on" if _GIL_DIAG_ENABLED else "off",
    )

    if not _verify_command_handlers():
        logger.error("❌ دوال الأوامر الحرجة مفقودة — الخروج")
        raise SystemExit(1)
    if not _verify_db_config():
        logger.error("❌ إعدادات DB — الخروج")
        raise SystemExit(1)

    t0 = time.monotonic()
    if hasattr(DB, 'pre_initialize'):
        await DB.pre_initialize()
    else:
        await initialize_db()
    logger.info("⏱️ DB init: %.2fs", time.monotonic() - t0)

    try:
        _ping = await DB.fetchone("SELECT 1 AS ok")
        logger.info("✅ DB ping: %s", _ping)
        logger.info("✅ DB type (post-init): %s",
                    str(getattr(DB, "DB_TYPE", "unknown")).upper())
    except Exception as _e:
        logger.warning("⚠️ DB ping (non-fatal): %s", _e)

    try:
        if hasattr(DB, "migrate_reminders_columns"):
            await DB.migrate_reminders_columns()
    except Exception as _e:
        logger.warning("⚠️ migrate_reminders_columns: %s", _e)

    for dev_id in CONFIG.DEVELOPER_IDS:
        try:
            await DB.register_user(dev_id)
        except Exception:
            pass
    try:
        await DB.register_user(CONFIG.PRIMARY_OWNER_ID)
    except Exception:
        pass

    t1 = time.monotonic()
    KeyboardFactory.load_config()
    available_langs = TranslationManager.get_available_languages()
    for lang in available_langs:
        TranslationManager.load_translation(lang)
    logger.info("✅ %d لغة في %.2fs", len(available_langs), time.monotonic() - t1)

    t_warmup = time.monotonic()
    try:
        await warmup_all()
        logger.info("⏱️ Warmup: %.2fs", time.monotonic() - t_warmup)
    except Exception as e:
        logger.warning("⚠️ Warmup: %s", e)

    port = _resolve_port()
    hostname = _resolve_hostname()

    # 🆕 v5.7.16 FIX-20: اطبع رابط النبض دائماً
    _print_public_url_hint(port, hostname)

    _allow_polling = os.getenv("ALLOW_POLLING", "0").strip() == "1"

    if not hostname:
        if not _allow_polling:
            logger.error(
                "❌ FATAL: Webhook hostname لا يمكن تحديده.\n"
                "   الحل: RENDER_EXTERNAL_HOSTNAME أو FALLBACK_HOSTNAME\n"
                "   أو (غير موصى): ALLOW_POLLING=1\n"
                "   رفض الإقلاع."
            )
            raise SystemExit(1)

    if hostname:
        logger.info("🌐 WEBHOOK mode FORCED: hostname=%s", hostname)
    else:
        logger.warning("⚠️ POLLING mode (ALLOW_POLLING=1)")
        # 🆕 v5.7.16 FIX-22: رسالة صريحة بالـ /health المتوقع
        logger.warning(
            "⚠️ HEALTH endpoint: http://0.0.0.0:%d/health (يعمل داخلياً)",
            port,
        )

    t_app = time.monotonic()
    _req_pool, _upd_pool = _build_http_request_pools()
    _app_builder = Application.builder().token(bot_token)
    if _req_pool is not None and _upd_pool is not None:
        _app_builder = (
            _app_builder
            .request(_req_pool)
            .get_updates_request(_upd_pool)
        )
        logger.info("🚀 HTTPXRequest pools applied (req=32/upd=8)")

    app = _app_builder.build()
    app.bot_data['start_time'] = time.monotonic()

    if hostname:
        logger.info("⏳ انتظار Telegram release (webhook mode)...")
        _rel_ok = await _wait_for_telegram_release()
        if not _rel_ok:
            logger.warning("⚠️ Telegram release timeout — app.initialize سيعيد المحاولة")

    _init_ok = await _initialize_with_retry(app)
    if not _init_ok:
        logger.error("❌ فشل app.initialize() — الخروج")
        try:
            await asyncio.wait_for(app.shutdown(), timeout=5.0)
        except Exception as _sd_e:
            logger.debug("app.shutdown() after init failure: %s", _sd_e)
        raise SystemExit(1)
    logger.info("⏱️ App init: %.2fs", time.monotonic() - t_app)

    try:
        await app.start()
        logger.info("✅ app.start()")
    except RuntimeError as _e:
        if "already running" not in str(_e).lower():
            raise

    try:
        _BOT_METRICS["started_at"] = time.monotonic()
    except Exception:
        pass

    _tg_warm_ok = await _warmup_telegram_api(app)
    if not _tg_warm_ok:
        logger.info("ℹ️ Telegram API warmup لم ينجح")

    if _HAS_WARMUP_DETECTORS and _warmup_detectors_pool_fn is not None:
        try:
            logger.info("🔥 warmup_detectors_pool: blocking...")
            _warm_t0 = time.monotonic()
            _warm_result = await asyncio.wait_for(
                _warmup_detectors_pool_fn(), timeout=30.0
            )
            if _warm_result:
                logger.info("✅ detectors ready in %.1fs", time.monotonic() - _warm_t0)
        except asyncio.TimeoutError:
            logger.warning("⚠️ detectors warmup timeout (30s)")
        except asyncio.CancelledError:
            raise
        except Exception as _we:
            logger.warning("⚠️ detectors warmup: %s", _we)

    try:
        import gc as _gc_t
        _gc_t.collect()
        logger.info("🧹 gc.collect()")
    except Exception:
        pass

    try:
        from managed_bots_runner import start_all_managed_bots
        _managed_apps = await start_all_managed_bots()
        logger.info("✅ managed_bots: %d/%d",
                    sum(1 for ok in _managed_apps.values() if ok),
                    len(_managed_apps))
    except Exception as _mb_e:
        logger.error("❌ managed_bots: %s", _mb_e)

    _spawn_gil_lag_monitor()

    try:
        _register_message_shutdown(app)
        logger.info("✅ message shutdown handlers")
    except Exception:
        pass

    if _GROUP_LOG_INIT_AVAILABLE and _GROUP_LOG_AVAILABLE:
        _init_group_log_instance(app)

    for _scope in (
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
    ):
        try:
            await app.bot.delete_my_commands(scope=_scope)
        except Exception:
            pass

    try:
        await app.bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeAllPrivateChats())
        logger.info("✅ %d أمراً عاماً", len(PUBLIC_COMMANDS))
    except Exception as _e:
        logger.error("❌ الأوامر العامة: %s", _e)

    try:
        await app.bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
        logger.info("✅ %d أمراً للمجموعات", len(GROUP_COMMANDS))
    except Exception as _e:
        logger.error("❌ أوامر المجموعات: %s", _e)

    _admin_ids = await _collect_admin_ids()
    _admin_full_list = PUBLIC_COMMANDS + ADMIN_COMMANDS
    logger.info("👥 الأدمن: %d", len(_admin_ids))
    app.bot_data["admin_ids"] = set(_admin_ids)

    for _admin_id in _admin_ids:
        try:
            await app.bot.set_my_commands(_admin_full_list, scope=BotCommandScopeChat(chat_id=_admin_id))
        except Exception:
            pass

    if _DIAG_INCOMING and _HAS_TYPE_HANDLER:
        try:
            app.add_handler(
                TypeHandler(_TgUpdate, _diag_incoming),
                group=-100,
            )
            logger.info(
                "🔔 DIAG_INCOMING=1 — TypeHandler تشخيصي مُسجّل "
                "(group=-100, Update, log level=info)."
            )
        except Exception as _e:
            logger.error("❌ فشل تسجيل DIAG handler: %s", _e)
    elif _DIAG_INCOMING and not _HAS_TYPE_HANDLER:
        logger.warning("⚠️ DIAG_INCOMING=1 لكن TypeHandler غير متاح")

    _group_msg_filter = _GROUP_CHAT_FILTER & filters.UpdateType.MESSAGE & ~filters.COMMAND

    try:
        _hg_timed = _wrap_handler_with_timing(MessageHandlers.handle_group, "handle_group")
        app.add_handler(MessageHandler(_group_msg_filter, _hg_timed), group=-1)
        logger.info("✅ handle_group [timed+faulthandler]")
    except Exception as _e:
        logger.error("❌ handle_group: %s", _e)

    if hasattr(MessageHandlers, "handle_edited"):
        try:
            _he_timed = _wrap_handler_with_timing(MessageHandlers.handle_edited, "handle_edited")
            app.add_handler(
                MessageHandler(_GROUP_CHAT_FILTER & filters.UpdateType.EDITED_MESSAGE, _he_timed),
                group=-1,
            )
            logger.info("✅ handle_edited [timed+faulthandler]")
        except Exception as _e:
            logger.error("❌ handle_edited: %s", _e)

    try:
        _hs_timed = _wrap_handler_with_timing(MessageHandlers.handle_service, "handle_service")
        app.add_handler(
            MessageHandler(filters.StatusUpdate.ALL & _GROUP_CHAT_FILTER, _hs_timed),
            group=-1,
        )
        logger.info("✅ handle_service [timed+faulthandler]")
    except Exception as _e:
        logger.error("❌ handle_service: %s", _e)

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
            logger.warning("⚠️ /%s: %s", _name, _e)

    for _alias_cmd in ("databases", "files", "versions"):
        try:
            app.add_handler(CommandHandler(_alias_cmd, _cmd_analytics_alias))
            logger.info("✅ /%s → _cmd_analytics_alias", _alias_cmd)
        except Exception as _e:
            logger.warning("⚠️ /%s alias: %s", _alias_cmd, _e)

    if _admin_ids:
        try:
            app.add_handler(CommandHandler("ping", cmd_ping, filters=filters.User(_admin_ids)))
        except Exception:
            app.add_handler(CommandHandler("ping", cmd_ping))
    else:
        app.add_handler(CommandHandler("ping", cmd_ping))

    if _admin_ids:
        try:
            app.add_handler(CommandHandler("posts_stats", cmd_posts_stats, filters=filters.User(_admin_ids)))
        except Exception:
            app.add_handler(CommandHandler("posts_stats", cmd_posts_stats))
    else:
        app.add_handler(CommandHandler("posts_stats", cmd_posts_stats))

    try:
        app.add_handler(CommandHandler("autoblocked", _handle_autoblocked_command))
    except Exception:
        pass

    if _HAS_DB_IDLE_CMD and _handle_db_idle_command is not None:
        try:
            app.add_handler(CommandHandler("db_idle", _handle_db_idle_command))
        except Exception:
            pass

    if _HAS_CACHE_STATS_CMD and _handle_cache_stats_command is not None:
        try:
            app.add_handler(CommandHandler("cache_stats", _handle_cache_stats_command))
        except Exception:
            pass

    if _cmd_fullhealth is not None:
        try:
            app.add_handler(CommandHandler("fullhealth", _cmd_fullhealth))
        except Exception:
            pass

    if _cmd_latency is not None:
        try:
            app.add_handler(CommandHandler("latency", _cmd_latency))
        except Exception:
            pass

    if hasattr(MessageHandlers, "handle_cancel"):
        try:
            app.add_handler(CommandHandler("cancel", MessageHandlers.handle_cancel), group=1)
        except Exception:
            pass

    if _MAINT_CMDS_AVAILABLE and callable(register_maintenance_commands):
        try:
            register_maintenance_commands(app)
        except Exception as _e:
            logger.error("❌ db_maintenance_commands: %s", _e)

    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(
        filters.SUCCESSFUL_PAYMENT & filters.ChatType.PRIVATE,
        successful_payment,
    ))

    try:
        register_channels_list_handlers(app)
    except Exception as e:
        logger.error("❌ [1/6] channels_list: %s", e)

    if _NAV_FIX_AVAILABLE and callable(register_nav_fix):
        try:
            register_nav_fix(app)
        except Exception as e:
            logger.error("❌ [2/6] NAV_FIX: %s", e)

    if _CH_DELETE_AVAILABLE and callable(register_delete_confirmation):
        try:
            register_delete_confirmation(app)
        except Exception as _e:
            logger.error("❌ [3/6] channels_delete: %s", _e)

    if _GROUP_LOG_AVAILABLE:
        try:
            register_group_log_handlers(app)
        except Exception as e:
            logger.error("❌ [4/6] group_log: %s", e)

    _analytics_registered = False
    if _ANALYTICS_REGISTER_AVAILABLE and callable(_register_analytics_handlers):
        try:
            if _register_analytics_handlers(app):
                _analytics_registered = True
                logger.info("✅ [5/6] handlers_analytics")
        except Exception as _e:
            logger.error("❌ [5/6] analytics: %s", _e)

    if not _analytics_registered:
        if (_ANALYTICS_HANDLERS_AVAILABLE and _show_analytics_menu is not None
                and _handle_analytics_callback is not None):
            try:
                app.add_handler(CallbackQueryHandler(_show_analytics_menu, pattern=r"^admin_analytics$"))
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
            except Exception as _e:
                logger.error("❌ [5/6] analytics fallback: %s", _e)

    if not _analytics_registered:
        try:
            app.add_handler(CommandHandler("analytics", _cmd_analytics_alias))
            logger.info("✅ /analytics → _cmd_analytics_alias (fallback)")
        except Exception as _e:
            logger.warning("⚠️ /analytics fallback: %s", _e)

    try:
        from handlers.handlers_managed_bots import register_managed_bots_handlers
        register_managed_bots_handlers(app)
    except Exception as _mb_e:
        logger.error("❌ [5.5/6] managed_bots: %s", _mb_e)

    try:
        app.add_handler(CallbackQueryHandler(CallbackHandlers.handle))
        logger.info("✅ [6/6] CallbackHandlers.handle")
    except Exception as _e:
        logger.error("❌ [6/6] callback: %s", _e)

    try:
        _hp_timed = _wrap_handler_with_timing(MessageHandlers.handle_private, "handle_private")
        app.add_handler(MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL
             | filters.AUDIO | filters.VOICE | filters.ANIMATION
             | filters.Sticker.ALL | filters.VIDEO_NOTE)
            & filters.ChatType.PRIVATE & ~filters.COMMAND
            & ~filters.SUCCESSFUL_PAYMENT,
            _hp_timed,
        ))
        logger.info("✅ handle_private [timed+faulthandler]")
    except Exception as _e:
        logger.error("❌ handle_private: %s", _e)

    app.add_handler(ChatJoinRequestHandler(MessageHandlers.handle_join_request))
    app.add_error_handler(ErrorHandler.handle_error)

    try:
        chat_member.register(app)
    except Exception as _e:
        logger.error("❌ ChatMemberHandler: %s", _e)

    if _MEMBERSHIP_AVAILABLE and callable(register_membership_handlers):
        try:
            register_membership_handlers(app)
        except Exception as _e:
            logger.error("❌ MembershipHandler: %s", _e)

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
        ("monitor_pool_alert", BackgroundTasks.monitor_pool_alert, (app.bot,)),
        ("contest_cleanup", contest_cleanup, (app,)),
        ("pool_health_monitor", pool_health_monitor, ()),
        ("admin_logs_cleanup", cleanup_admin_logs_periodically, ()),
        ("removed_channels_cleanup", cleanup_removed_channels_periodically, ()),
    ]
    if _periodic_cleanup_callable is not None:
        _bg_task_specs.append(("periodic_cleanup", _periodic_cleanup_callable, ()))
    else:
        logger.warning("⚠️ periodic_cleanup: skipped (لا callable صالح)")

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
            run_task_with_retry(_maintenance_loop, app.bot, owner_id, task_name="maintenance")
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
                secret_token=(getattr(CONFIG, "WEBHOOK_SECRET", "") or None),
            )
            logger.info("✅ Webhook تم التعيين")

            try:
                _wb_info = await app.bot.get_webhook_info()
                _wb_url = getattr(_wb_info, "url", "") or ""
                _expected_prefix = f"https://{hostname}/"
                if _wb_url and _wb_url.startswith(_expected_prefix):
                    logger.info("✅ WEBHOOK VERIFIED: %s<TOKEN> (pending=%d)",
                                _expected_prefix,
                                getattr(_wb_info, "pending_update_count", 0))
                else:
                    logger.error("❌ WEBHOOK MISMATCH! expected=%r got=%r",
                                 _expected_prefix,
                                 _redact_token(_wb_url)[:80] if _wb_url else "(empty)")
            except Exception as _wbv_e:
                logger.warning("⚠️ Webhook verification failed: %s", _wbv_e)

            runner = await setup_webhook(app, port)
            await _run_post_init_hooks(app)

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"http://127.0.0.1:{port}/health") as resp:
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
                    except (asyncio.CancelledError, Exception):
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
            logger.warning("⚠️ POLLING mode (ALLOW_POLLING=1)")
            runner = await setup_webhook(app, port)
            try:
                _app_running = (getattr(app, "running", False) or getattr(app, "_running", False))
                if not _app_running:
                    raise RuntimeError("app.running=False")
                _polling_state["running"] = True
                await app.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=ALLOWED_UPDATES,
                )
                logger.warning("⚠️ POLLING STARTED")
                await _run_post_init_hooks(app)
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
                    asyncio.gather(*_NOTIFY_TASKS, return_exceptions=True),
                    timeout=_NOTIFY_SHUTDOWN_TIMEOUT,
                )
            except asyncio.TimeoutError:
                for _t in list(_NOTIFY_TASKS):
                    _t.cancel()
            except asyncio.CancelledError:
                raise

        if _GIL_LAG_MONITOR_TASK is not None and not _GIL_LAG_MONITOR_TASK.done():
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
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass

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
                from sleep_probe import uninstall_sleep_probe as _sp_uninstall
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

        try:
            _shutdown_faulthandler()
        except Exception:
            pass

        _remove_pid_file()

    logger.info("👋 انتهت دورة حياة البوت (%.2fs)", time.monotonic() - t_start)


if __name__ == "__main__":
    _loop = None
    try:
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("\n👋 تم الإيقاف")
    except SystemExit:
        raise
    except Exception as e:
        logger.error("❌ خطأ: %s", e, exc_info=True)
        traceback.print_exc()
        sys.exit(1)
    finally:
        if _loop is not None:
            try:
                try:
                    pending = asyncio.all_tasks(_loop)
                except Exception:
                    pending = set()
                try:
                    _current = asyncio.current_task()
                    pending = {t for t in pending if t is not _current}
                except Exception:
                    pass
                if pending:
                    logger.info("⏳ إلغاء %d مهمة معلّقة...", len(pending))
                    for _t in pending:
                        _t.cancel()
                    try:
                        _loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
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
                                _result = _shutdown_default_executor_fn(timeout=5.0)
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