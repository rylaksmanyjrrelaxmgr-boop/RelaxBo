#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
managed_bots_runner.py — دورة حياة البوتات المُدارة (v5.7.19)
=================================================================================
🆕 v5.7.19 (PRIVATE-TOGGLE):
    🟢 FEATURE-PRIVATE-TOGGLE: زر 💬 للتحكم بالردود في الخاص.
    • `set_respond_in_private(bid, value)` — hot-toggle.
    • `start_one` ينقل `respond_in_private` إلى bot_data.
    • `reload_messages` يحدّثها أيضاً.

✅ محفوظ من v5.7.18: HOT-TOGGLE (groups).
✅ محفوظ من v5.7.11: RETRY-WINDOW-EXTENDED.
=================================================================================
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from telegram import Update
from telegram.error import (
    BadRequest,
    Conflict,
    Forbidden,
    InvalidToken,
    NetworkError,
    RetryAfter,
    TimedOut,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import CONFIG
from managed_bots_storage import (
    get_default_messages,
    load_managed_bots,
    load_managed_keywords,
)

logger = logging.getLogger(__name__)


_TIMEOUTS: Dict[str, float] = {
    "read_timeout": 30.0,
    "write_timeout": 30.0,
    "connect_timeout": 20.0,
    "pool_timeout": 20.0,
}

_RETRY_DELAYS: Tuple[int, ...] = (30, 60)
_INTER_START_DELAY = 0.3

_RELAX_TOKEN: str = (
    os.getenv("BOT_TOKEN", "").strip()
    or getattr(CONFIG, "TOKEN", "")
    or ""
).strip()


RUNNING: Dict[int, Application] = {}


def _is_token_conflict(token: str) -> bool:
    if not _RELAX_TOKEN or not token:
        return False
    if token.strip() == _RELAX_TOKEN:
        logger.error(
            "❌ managed_bots: التوكن مطابق لتوكن Relax Manager! "
            "سيحدث Conflict — رفض التشغيل."
        )
        return True
    return False


async def _safe_cleanup(app: Optional[Application]) -> None:
    if app is None:
        return
    try:
        updater = getattr(app, "updater", None)
        if updater is not None and getattr(updater, "running", False):
            await updater.stop()
    except Exception as _e:
        logger.debug("cleanup updater: %s", _e)
    try:
        if getattr(app, "running", False):
            await app.stop()
    except Exception as _e:
        logger.debug("cleanup app.stop: %s", _e)
    try:
        await app.shutdown()
    except Exception as _e:
        logger.debug("cleanup app.shutdown: %s", _e)


async def _error_handler(update: Any, context: Any) -> None:
    err = context.error
    if isinstance(err, Conflict):
        logger.debug(
            "managed bot: Conflict (deploy in progress) — "
            "PTB retries automatically"
        )
        return
    if isinstance(err, RetryAfter):
        logger.debug("managed bot: RetryAfter %ss", err.retry_after)
    elif isinstance(err, BadRequest):
        logger.debug("managed bot: BadRequest — %s", err)
    elif isinstance(err, (TimedOut, NetworkError)):
        logger.debug("managed bot: network — %s", type(err).__name__)
    else:
        logger.warning(
            "managed bot error | %s: %s",
            type(err).__name__ if err else "?", err,
        )


def _build_application(token: str) -> Application:
    return (
        Application.builder()
        .token(token)
        .read_timeout(_TIMEOUTS["read_timeout"])
        .write_timeout(_TIMEOUTS["write_timeout"])
        .connect_timeout(_TIMEOUTS["connect_timeout"])
        .pool_timeout(_TIMEOUTS["pool_timeout"])
        .build()
    )


async def start_one(
    bid: int,
    token: str,
    *,
    max_retries: int = 3,
) -> bool:
    if not token or not token.strip():
        logger.error("start_one(#%s): token فارغ", bid)
        return False

    token = token.strip()

    if _is_token_conflict(token):
        return False

    existing = RUNNING.get(bid)
    if existing is not None:
        try:
            existing_token = getattr(existing.bot, "token", "") or ""
        except Exception:
            existing_token = ""
        if existing_token == token:
            logger.debug("start_one(#%s): يعمل مسبقاً بنفس التوكن", bid)
            return True
        logger.warning("start_one(#%s): التوكن تغيّر — إعادة تشغيل", bid)
        await stop_one(bid)

    try:
        from handlers.handlers_managed_public import (
            make_managed_handlers,
            post_init_managed,
        )
    except ImportError as _ie:
        logger.error(
            "❌ start_one(#%s): handlers.handlers_managed_public مفقود — %s",
            bid, _ie,
        )
        return False

    stored = await load_managed_bots()
    stored_entry = stored.get(bid, {})
    messages = (
        stored_entry.get("messages")
        or get_default_messages()
    )
    name = stored_entry.get("name", "")
    respond_in_groups = bool(stored_entry.get("respond_in_groups", False))
    respond_in_private = bool(stored_entry.get("respond_in_private", True))  # 🆕
    keywords = await load_managed_keywords(bid)

    last_err: Optional[BaseException] = None

    for attempt in range(1, max_retries + 1):
        app: Optional[Application] = None
        try:
            app = _build_application(token)
            app.bot_data["managed_bid"] = bid
            app.bot_data["managed_messages"] = dict(messages)
            app.bot_data["managed_name"] = name
            app.bot_data["managed_keywords"] = dict(keywords)
            app.bot_data["respond_in_groups"] = respond_in_groups
            app.bot_data["respond_in_private"] = respond_in_private  # 🆕

            app.post_init = post_init_managed

            on_start, on_text = make_managed_handlers(bid)
            private = filters.ChatType.PRIVATE
            groups_filter = (
                filters.ChatType.GROUPS
                | filters.ChatType.SUPERGROUP
            )

            # استقبال الخاص دائماً
            app.add_handler(CommandHandler(
                "start", on_start, filters=private))
            app.add_handler(MessageHandler(
                filters.TEXT & ~filters.COMMAND & private, on_text,
            ))

            # استقبال المجموعات دائماً (Hot-toggle داخلي)
            app.add_handler(MessageHandler(
                filters.TEXT & ~filters.COMMAND & groups_filter,
                on_text,
            ))

            logger.info(
                "✅ managed_bot #%s: handlers registered | "
                "private=%s | groups=%s",
                bid, respond_in_private, respond_in_groups,
            )

            app.add_error_handler(_error_handler)

            await app.initialize()
            await app.start()
            await app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=[Update.MESSAGE],
            )

            RUNNING[bid] = app
            logger.info(
                "✅ managed_bot #%s (@%s) started | keywords=%d | "
                "groups=%s | private=%s",
                bid, name or "?", len(keywords),
                respond_in_groups, respond_in_private,
            )
            return True

        except InvalidToken as _e:
            logger.error("❌ managed_bot #%s: توكن غير صالح — %s", bid, _e)
            await _safe_cleanup(app)
            return False

        except Forbidden as _e:
            logger.error("❌ managed_bot #%s: محظور — %s", bid, _e)
            await _safe_cleanup(app)
            return False

        except Conflict as _e:
            last_err = _e
            logger.warning(
                "⚠️ managed_bot #%s: Conflict (deploy) — retry in %ds (%d/%d)",
                bid,
                _RETRY_DELAYS[attempt - 1]
                if attempt - 1 < len(_RETRY_DELAYS)
                else _RETRY_DELAYS[-1],
                attempt, max_retries,
            )
            await _safe_cleanup(app)
            if attempt < max_retries:
                delay = (
                    _RETRY_DELAYS[attempt - 1]
                    if attempt - 1 < len(_RETRY_DELAYS)
                    else _RETRY_DELAYS[-1]
                )
                await asyncio.sleep(delay)
                continue

        except (NetworkError, TimedOut) as _e:
            last_err = _e
            logger.warning(
                "📡 managed_bot #%s: خطأ شبكة (%d/%d)",
                bid, attempt, max_retries,
            )
            await _safe_cleanup(app)
            if attempt < max_retries:
                delay = (
                    _RETRY_DELAYS[attempt - 1]
                    if attempt - 1 < len(_RETRY_DELAYS)
                    else _RETRY_DELAYS[-1]
                )
                await asyncio.sleep(delay)
                continue

        except asyncio.CancelledError:
            await _safe_cleanup(app)
            raise

        except Exception as _e:
            logger.error(
                "❌ managed_bot #%s: %s: %s",
                bid, type(_e).__name__, _e, exc_info=True,
            )
            await _safe_cleanup(app)
            return False

    logger.error(
        "❌ managed_bot #%s: فشل بعد %d محاولات — آخر خطأ: %s",
        bid, max_retries, last_err,
    )
    return False


async def stop_one(bid: int, timeout: float = 10.0) -> None:
    app = RUNNING.pop(bid, None)
    if app is None:
        return

    async def _do() -> None:
        try:
            updater = getattr(app, "updater", None)
            if updater is not None and getattr(updater, "running", False):
                await updater.stop()
        except Exception as _e:
            logger.debug("stop_one(#%s) updater: %s", bid, _e)
        try:
            if getattr(app, "running", False):
                await app.stop()
        except Exception as _e:
            logger.debug("stop_one(#%s) app.stop: %s", bid, _e)
        try:
            await app.shutdown()
        except Exception as _e:
            logger.debug("stop_one(#%s) shutdown: %s", bid, _e)

    try:
        await asyncio.wait_for(_do(), timeout=timeout)
        logger.info("🛑 managed_bot #%s stopped", bid)
    except asyncio.TimeoutError:
        logger.warning("⏱️ stop_one(#%s): timeout %.0fs", bid, timeout)
    except asyncio.CancelledError:
        raise
    except Exception as _e:
        logger.warning("stop_one(#%s): %s", bid, _e)


async def restart_one(
    bid: int,
    token: str,
    *,
    max_retries: int = 3,
) -> bool:
    await stop_one(bid)
    return await start_one(bid, token, max_retries=max_retries)


async def reload_messages(bid: int) -> bool:
    app = RUNNING.get(bid)
    if app is None:
        return False

    bots = await load_managed_bots()
    entry = bots.get(bid)
    if entry is None:
        return False

    app.bot_data["managed_messages"] = dict(
        entry.get("messages") or get_default_messages()
    )
    app.bot_data["managed_name"] = entry.get("name", "")

    new_respond_groups = bool(entry.get("respond_in_groups", False))
    app.bot_data["respond_in_groups"] = new_respond_groups

    new_respond_private = bool(entry.get("respond_in_private", True))  # 🆕
    app.bot_data["respond_in_private"] = new_respond_private

    keywords = await load_managed_keywords(bid)
    app.bot_data["managed_keywords"] = dict(keywords)

    logger.debug(
        "managed_bot #%s: reloaded (messages + kw=%d + groups=%s + private=%s)",
        bid, len(keywords), new_respond_groups, new_respond_private,
    )
    return True


async def set_respond_in_groups(bid: int, value: bool) -> bool:
    app = RUNNING.get(bid)
    if app is None:
        logger.debug(
            "set_respond_in_groups(#%s): البوت غير مشغّل — "
            "الحالة ستُطبَّق عند التشغيل التالي", bid,
        )
        return False

    old = bool(app.bot_data.get("respond_in_groups", False))
    new = bool(value)
    app.bot_data["respond_in_groups"] = new

    logger.info(
        "🎛️ managed_bot #%s: respond_in_groups %s → %s (hot-toggle, no restart)",
        bid, old, new,
    )
    return True


# 🆕 v5.7.19
async def set_respond_in_private(bid: int, value: bool) -> bool:
    app = RUNNING.get(bid)
    if app is None:
        logger.debug(
            "set_respond_in_private(#%s): البوت غير مشغّل — "
            "الحالة ستُطبَّق عند التشغيل التالي", bid,
        )
        return False

    old = bool(app.bot_data.get("respond_in_private", True))
    new = bool(value)
    app.bot_data["respond_in_private"] = new

    logger.info(
        "🎛️ managed_bot #%s: respond_in_private %s → %s "
        "(hot-toggle, no restart)",
        bid, old, new,
    )
    return True


def is_running(bid: int) -> bool:
    return bid in RUNNING


def running_bids() -> List[int]:
    return sorted(RUNNING.keys())


def running_count() -> int:
    return len(RUNNING)


async def start_all_managed_bots() -> Dict[int, bool]:
    try:
        bots = await load_managed_bots()
    except Exception as _e:
        logger.error("❌ start_all_managed_bots: %s", _e)
        return {}

    if not bots:
        logger.info("ℹ️ managed_bots: لا توجد بوتات محفوظة — تخطي")
        return {}

    logger.info("🚀 managed_bots: بدء %d بوت مُدار...", len(bots))

    results: Dict[int, bool] = {}
    for bid, info in bots.items():
        ok = await start_one(bid, info.get("token", ""))
        results[bid] = ok
        await asyncio.sleep(_INTER_START_DELAY)

    started = sum(1 for v in results.values() if v)
    failed = [b for b, v in results.items() if not v]

    logger.info("✅ managed_bots: %d/%d يعمل الآن", started, len(results))
    if failed:
        logger.warning("⚠️ managed_bots: فشل تشغيل %s", failed)
    return results


async def stop_all_managed_bots(timeout: float = 15.0) -> None:
    if not RUNNING:
        return
    bids = list(RUNNING.keys())
    logger.info("🛑 managed_bots: إيقاف %d بوت...", len(bids))
    try:
        await asyncio.gather(
            *(stop_one(bid, timeout=timeout) for bid in bids),
            return_exceptions=True,
        )
    except asyncio.CancelledError:
        raise
    except Exception as _e:
        logger.warning("stop_all_managed_bots: %s", _e, exc_info=True)
    finally:
        RUNNING.clear()
    logger.info("✅ managed_bots: أُوقفت كل البوتات")


__all__ = [
    "RUNNING",
    "start_one",
    "stop_one",
    "restart_one",
    "reload_messages",
    "set_respond_in_groups",
    "set_respond_in_private",  # 🆕
    "is_running",
    "running_bids",
    "running_count",
    "start_all_managed_bots",
    "stop_all_managed_bots",
]


try:
    _total_coverage = sum(
        _RETRY_DELAYS[i]
        if i < len(_RETRY_DELAYS)
        else _RETRY_DELAYS[-1]
        for i in range(2)
    )
    logger.debug(
        "🛡️ managed_bots_runner v5.7.19 "
        "(PRIVATE-TOGGLE) loaded | "
        "timeouts=%s | retry_delays=%s (coverage=%ds) | "
        "keywords_enabled=True | groups=hot(private=default_on) | "
        "private=hot(default_on) | toggle=hot(no_restart)",
        _TIMEOUTS, _RETRY_DELAYS, _total_coverage,
    )
except Exception:
    pass