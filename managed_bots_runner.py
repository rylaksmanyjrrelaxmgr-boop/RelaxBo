#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
managed_bots_runner.py — دورة حياة البوتات المُدارة (v5.7.3 - DB-MIGRATION)
=================================================================================
📌 المسؤولية:
    • تشغيل/إيقاف كل بوت مُدار كـ Application مستقل (polling).
    • إدارة القاموس العالمي RUNNING[bid] → Application.
    • retry ذكي عند أخطاء الشبكة (لا retry عند invalid token).
    • تنظيف آمن عند فشل جزئي (updater → app → shutdown).
    • منع تعارض التوكن مع Relax Manager.
    • إعادة تحميل الرسائل في الذاكرة (reload_messages) بدون restart.

🎯 التغييرات الأساسية في v5.7.3:
    • await load_managed_bots() (لأن التخزين أصبح async).
    • reload_messages() أصبحت async.
    • لا تغيير في أي منطق آخر.

🚫 لا يحتوي:
    • DB I/O (مكانه: managed_bots_storage.py)
    • معالجات Telegram (مكانه: handlers_managed_*.py)
=================================================================================
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from telegram import Update
from telegram.error import (
    BadRequest,
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
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 1. ثوابت
# ═══════════════════════════════════════════════════════════════════════════

_TIMEOUTS: Dict[str, float] = {
    "read_timeout": 30.0,
    "write_timeout": 30.0,
    "connect_timeout": 20.0,
    "pool_timeout": 20.0,
}

_RETRY_DELAYS: Tuple[int, ...] = (2, 4, 6)

_INTER_START_DELAY = 0.3

_RELAX_TOKEN: str = (getattr(CONFIG, "TOKEN", "") or "").strip()


# ═══════════════════════════════════════════════════════════════════════════
# 2. السجل العالمي
# ═══════════════════════════════════════════════════════════════════════════

RUNNING: Dict[int, Application] = {}
"""bid → Application. يُعدَّل فقط من start_one/stop_one."""


# ═══════════════════════════════════════════════════════════════════════════
# 3. أدوات داخلية
# ═══════════════════════════════════════════════════════════════════════════

def _is_token_conflict(token: str) -> bool:
    """True إن كان التوكن مطابقاً لتوكن Relax Manager (Conflict حتمي)."""
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
    """تنظيف آمن: updater → app.stop → app.shutdown."""
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
    """معالج أخطاء محلي للبوت المُدار."""
    err = context.error
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
    """يبني Application بمعاملات موحّدة (لا start)."""
    return (
        Application.builder()
        .token(token)
        .read_timeout(_TIMEOUTS["read_timeout"])
        .write_timeout(_TIMEOUTS["write_timeout"])
        .connect_timeout(_TIMEOUTS["connect_timeout"])
        .pool_timeout(_TIMEOUTS["pool_timeout"])
        .build()
    )


# ═══════════════════════════════════════════════════════════════════════════
# 4. start_one
# ═══════════════════════════════════════════════════════════════════════════

async def start_one(
    bid: int,
    token: str,
    *,
    max_retries: int = 3,
) -> bool:
    """يبدأ بوتاً مُداراً واحداً."""
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
        logger.warning(
            "start_one(#%s): التوكن تغيّر — إعادة تشغيل", bid
        )
        await stop_one(bid)

    # استيراد متأخر للـ handlers
    try:
        from handlers.handlers_managed_public import (  # type: ignore
            make_managed_handlers,
            post_init_managed,
        )
    except ImportError as _ie:
        logger.error(
            "❌ start_one(#%s): handlers.handlers_managed_public مفقود — %s\n"
            "   أنشئ handlers/handlers_managed_public.py أولاً.",
            bid, _ie,
        )
        return False

    # 🆕 v5.7.3: await (التخزين أصبح async)
    stored = await load_managed_bots()
    messages = (
        stored.get(bid, {}).get("messages")
        or get_default_messages()
    )
    name = stored.get(bid, {}).get("name", "")

    last_err: Optional[BaseException] = None

    for attempt in range(1, max_retries + 1):
        app: Optional[Application] = None
        try:
            app = _build_application(token)
            app.bot_data["managed_bid"] = bid
            app.bot_data["managed_messages"] = dict(messages)
            app.bot_data["managed_name"] = name

            app.post_init = post_init_managed

            on_start, on_text = make_managed_handlers(bid)
            private = filters.ChatType.PRIVATE
            app.add_handler(
                CommandHandler("start", on_start, filters=private)
            )
            app.add_handler(
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND & private,
                    on_text,
                )
            )
            app.add_error_handler(_error_handler)

            await app.initialize()
            await app.start()
            await app.updater.start_polling(  # type: ignore[union-attr]
                drop_pending_updates=True,
                allowed_updates=[Update.MESSAGE],
            )

            RUNNING[bid] = app
            logger.info(
                "✅ managed_bot #%s (@%s) started", bid, name or "?"
            )
            return True

        except InvalidToken as _e:
            logger.error(
                "❌ managed_bot #%s: توكن غير صالح — %s", bid, _e
            )
            await _safe_cleanup(app)
            return False

        except Forbidden as _e:
            logger.error(
                "❌ managed_bot #%s: محظور/موقوف — %s", bid, _e
            )
            await _safe_cleanup(app)
            return False

        except (NetworkError, TimedOut) as _e:
            last_err = _e
            logger.warning(
                "📡 managed_bot #%s: خطأ شبكة (%d/%d) — %s",
                bid, attempt, max_retries, type(_e).__name__,
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
                bid, type(_e).__name__, _e,
                exc_info=True,
            )
            await _safe_cleanup(app)
            return False

    logger.error(
        "❌ managed_bot #%s: فشل بعد %d محاولات — آخر خطأ: %s",
        bid, max_retries, last_err,
    )
    return False


# ═══════════════════════════════════════════════════════════════════════════
# 5. stop_one
# ═══════════════════════════════════════════════════════════════════════════

async def stop_one(bid: int, timeout: float = 10.0) -> None:
    """يوقف بوتاً مُداراً واحداً."""
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
        logger.warning(
            "⏱️ stop_one(#%s): timeout %.0fs", bid, timeout
        )
    except asyncio.CancelledError:
        raise
    except Exception as _e:
        logger.warning("stop_one(#%s): %s", bid, _e)


# ═══════════════════════════════════════════════════════════════════════════
# 6. restart_one
# ═══════════════════════════════════════════════════════════════════════════

async def restart_one(
    bid: int,
    token: str,
    *,
    max_retries: int = 3,
) -> bool:
    """يوقف ثم يبدأ."""
    await stop_one(bid)
    return await start_one(bid, token, max_retries=max_retries)


# ═══════════════════════════════════════════════════════════════════════════
# 7. reload_messages — بدون restart
# ═══════════════════════════════════════════════════════════════════════════

async def reload_messages(bid: int) -> bool:
    """
    يعيد قراءة رسائل بوت من DB إلى bot_data.
    🆕 v5.7.3: أصبحت async (لأن التخزين async).
    """
    app = RUNNING.get(bid)
    if app is None:
        return False

    # 🆕 v5.7.3: await
    bots = await load_managed_bots()
    entry = bots.get(bid)
    if entry is None:
        return False

    app.bot_data["managed_messages"] = dict(
        entry.get("messages") or get_default_messages()
    )
    app.bot_data["managed_name"] = entry.get("name", "")
    logger.debug("managed_bot #%s: messages reloaded", bid)
    return True


# ═══════════════════════════════════════════════════════════════════════════
# 8. استعلامات الحالة
# ═══════════════════════════════════════════════════════════════════════════

def is_running(bid: int) -> bool:
    return bid in RUNNING


def running_bids() -> List[int]:
    return sorted(RUNNING.keys())


def running_count() -> int:
    return len(RUNNING)


# ═══════════════════════════════════════════════════════════════════════════
# 9. start_all_managed_bots
# ═══════════════════════════════════════════════════════════════════════════

async def start_all_managed_bots() -> Dict[int, bool]:
    """يبدأ كل البوتات المُدارة المحفوظة."""
    try:
        # 🆕 v5.7.3: await
        bots = await load_managed_bots()
    except Exception as _e:
        logger.error(
            "❌ start_all_managed_bots: فشل قراءة التخزين — %s", _e
        )
        return {}

    if not bots:
        logger.info("ℹ️ managed_bots: لا توجد بوتات محفوظة — تخطي")
        return {}

    logger.info(
        "🚀 managed_bots: بدء %d بوت مُدار...", len(bots)
    )

    results: Dict[int, bool] = {}
    for bid, info in bots.items():
        ok = await start_one(bid, info.get("token", ""))
        results[bid] = ok
        await asyncio.sleep(_INTER_START_DELAY)

    started = sum(1 for v in results.values() if v)
    failed = [b for b, v in results.items() if not v]

    logger.info(
        "✅ managed_bots: %d/%d يعمل الآن", started, len(results)
    )
    if failed:
        logger.warning(
            "⚠️ managed_bots: فشل تشغيل %s — يمكن إعادة المحاولة من اللوحة",
            failed,
        )
    return results


# ═══════════════════════════════════════════════════════════════════════════
# 10. stop_all_managed_bots
# ═══════════════════════════════════════════════════════════════════════════

async def stop_all_managed_bots(timeout: float = 15.0) -> None:
    """يوقف كل البوتات المُدارة بالتوازي."""
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
        logger.warning(
            "stop_all_managed_bots: %s", _e, exc_info=True
        )
    finally:
        RUNNING.clear()
    logger.info("✅ managed_bots: أُوقفت كل البوتات")


# ═══════════════════════════════════════════════════════════════════════════
# 11. __all__
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    "RUNNING",
    "start_one",
    "stop_one",
    "restart_one",
    "reload_messages",
    "is_running",
    "running_bids",
    "running_count",
    "start_all_managed_bots",
    "stop_all_managed_bots",
]


# ═══════════════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═══════════════════════════════════════════════════════════════════════════

try:
    logger.debug(
        "🛡️ managed_bots_runner v5.7.3 (DB-MIGRATION) loaded | "
        "timeouts=%s | retries=%d | reload_messages=async",
        _TIMEOUTS, len(_RETRY_DELAYS),
    )
except Exception:
    pass