#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
managed_bots_storage.py — طبقة I/O ذرية للبوتات المُدارة (v5.7.0)
=================================================================================
📌 المسؤولية:
    • قراءة/كتابة managed_bots.json (التوكنات + الرسائل) بشكل ذري.
    • قراءة/كتابة managed_bots_state.json (تقدم المستخدمين).
    • تدوير .bak عند الكتابة، واسترداد من .bak عند التلف.
    • عزل الملف التالف في .corrupt_TIMESTAMP (لا حذف).
    • صلاحيات 0600 لحماية التوكنات.

🎯 العقد مع بقية الملفات:
    managed_bots_runner.py  → import: load_managed_bots, save_managed_bots,
                                        load_managed_state, save_managed_state,
                                        get_lock, next_managed_bot_id
    handlers_managed_*.py   → import: نفس الدوال أعلاه + ensure_default_state

🚫 لا يحتوي هذا الملف على:
    • منطق تشغيل بوتات (مكانه: managed_bots_runner.py)
    • معالجات Telegram (مكانه: handlers_managed_*.py)
    • أي imports من bot.py أو database.py
=================================================================================
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time as _time
from pathlib import Path
from typing import Any, Dict, Optional, Set

from config import CONFIG

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 1. المسارات
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_data_dir() -> Path:
    """
    دليل البيانات:
      1) ENV MANAGED_BOTS_DIR (إن وُجد)
      2) دليل الملف الحالي (جذر المستودع)
    """
    env = (os.getenv("MANAGED_BOTS_DIR") or "").strip()
    if env:
        try:
            return Path(env).expanduser().resolve()
        except Exception as _e:
            logger.warning("⚠️ MANAGED_BOTS_DIR غير صالح: %s — استخدام الجذر", _e)
    return Path(__file__).resolve().parent


_DATA_DIR: Path = _resolve_data_dir()
BOTS_FILE: Path = _DATA_DIR / "managed_bots.json"
STATE_FILE: Path = _DATA_DIR / "managed_bots_state.json"

try:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError as _e:
    logger.warning("⚠️ تعذّر إنشاء %s: %s", _DATA_DIR, _e)


# ═══════════════════════════════════════════════════════════════════════════
# 2. الرسائل الافتراضية
# ═══════════════════════════════════════════════════════════════════════════

_FALLBACK_MESSAGES: Dict[str, str] = {
    "start":  "👋 أهلاً بك!",
    "reply":  "📩 تم استلام رسالتك.",
    "third":  "✅ شكرًا لتواصلك.",
    "fourth": "🙏 نتمنى لك يومًا سعيدًا.",
}


def get_default_messages() -> Dict[str, str]:
    """
    أولويات:
      1) CONFIG.MANAGED_START_MESSAGE (إن وُجد)
      2) القيمة الافتراضية
    """
    return {
        k: str(getattr(CONFIG, f"MANAGED_{k.upper()}_MESSAGE", None)
               or _FALLBACK_MESSAGES[k])
        for k in ("start", "reply", "third", "fourth")
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3. القفل (asyncio)
# ═══════════════════════════════════════════════════════════════════════════

_io_lock: Optional[asyncio.Lock] = None


def get_lock() -> asyncio.Lock:
    """Lazy init — آمن عند الاستيراد قبل وجود event loop."""
    global _io_lock
    if _io_lock is None:
        _io_lock = asyncio.Lock()
    return _io_lock


# ═══════════════════════════════════════════════════════════════════════════
# 4. I/O ذري
# ═══════════════════════════════════════════════════════════════════════════

def _load_json_safe(path: Path) -> Dict[str, Any]:
    """
    - يقرأ JSON بأمان.
    - إن كان الملف مفقوداً → {}.
    - إن كان تالفاً:
        a) يحاول .bak
        b) إن نجح .bak → يسترد
        c) إن فشل → يعزل الملف في .corrupt_TIMESTAMP ويعيد {}.
    """
    if not path.exists():
        return {}

    # محاولة القراءة الأساسية
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        logger.warning("⚠️ %s: ليس dict — تجاهل", path.name)
    except (json.JSONDecodeError, OSError) as _e:
        logger.error("❌ %s تالف: %s", path.name, _e)

    # محاولة الاسترداد من .bak
    bak = path.with_suffix(path.suffix + ".bak")
    if bak.exists():
        try:
            with open(bak, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                logger.warning(
                    "🆘 استُعيد %s من %s", path.name, bak.name
                )
                return data
        except Exception as _e:
            logger.error("❌ .bak أيضاً تالف: %s", _e)

    # عزل الملف التالف (لا حذف)
    try:
        stamp = _time.strftime("%Y%m%d_%H%M%S")
        corrupt = path.with_suffix(path.suffix + f".corrupt_{stamp}")
        os.replace(path, corrupt)
        logger.error("🆘 %s → %s (لن يُحذف)", path.name, corrupt.name)
    except OSError as _e:
        logger.error("⚠️ فشل عزل %s: %s", path.name, _e)

    return {}


def _save_json_atomic(path: Path, data: Dict[str, Any]) -> bool:
    """
    حفظ ذري:
      1) إن الملف موجود → نسخه إلى .bak (حماية النسخة السابقة).
      2) كتابة إلى .tmp مع fsync.
      3) os.replace(tmp, path) — ذري على نفس الجهاز.
      4) chmod 0600.
    """
    tmp: Optional[Path] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        # 1) نسخة احتياطية من المحتوى الحالي (إن وُجد)
        if path.exists():
            try:
                bak = path.with_suffix(path.suffix + ".bak")
                with open(path, "rb") as src, open(bak, "wb") as dst:
                    dst.write(src.read())
                try:
                    os.chmod(bak, 0o600)
                except OSError:
                    pass
            except OSError as _e:
                logger.debug("backup before write: %s", _e)

        # 2) كتابة ذرية
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass

        # 3) استبدال ذري
        os.replace(tmp, path)
        tmp = None

        # 4) صلاحيات
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

        return True

    except OSError as _e:
        logger.error("❌ حفظ %s: %s", path.name, _e)
        return False
    finally:
        if tmp is not None and tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


# ═══════════════════════════════════════════════════════════════════════════
# 5. مساعدات التطبيع
# ═══════════════════════════════════════════════════════════════════════════

def _pick_str(data: Dict[str, Any], key: str, default: str) -> str:
    val = data.get(key)
    if isinstance(val, str) and val.strip():
        return val
    return default


def _normalize_bot_entry(raw: Any) -> Optional[Dict[str, Any]]:
    """يطبّع سجل بوت واحد. يعيد None إن كان غير صالح."""
    if not isinstance(raw, dict):
        return None

    token = raw.get("token")
    if not isinstance(token, str) or not token.strip():
        return None

    defaults = get_default_messages()
    msgs_raw = raw.get("messages")
    if not isinstance(msgs_raw, dict):
        msgs_raw = {}

    messages = {
        "start":  _pick_str(msgs_raw, "start",  defaults["start"]),
        "reply":  _pick_str(msgs_raw, "reply",  defaults["reply"]),
        "third":  _pick_str(msgs_raw, "third",  defaults["third"]),
        "fourth": _pick_str(msgs_raw, "fourth", defaults["fourth"]),
    }

    name = raw.get("name")
    added_at = raw.get("added_at")

    return {
        "token":    token.strip(),
        "name":     (str(name).strip() if isinstance(name, str) else ""),
        "messages": messages,
        "added_at": (str(added_at).strip() if isinstance(added_at, str) else ""),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 6. Public API — managed_bots.json
# ═══════════════════════════════════════════════════════════════════════════

def load_managed_bots() -> Dict[int, Dict[str, Any]]:
    """
    يقرأ managed_bots.json ويطبّع كل سجل.
    يتجاهل المفاتيح غير الرقمية والسجلات بدون token.
    """
    raw = _load_json_safe(BOTS_FILE)
    result: Dict[int, Dict[str, Any]] = {}

    for k, v in raw.items():
        try:
            bid = int(k)
        except (ValueError, TypeError):
            continue
        if bid <= 0:
            continue
        entry = _normalize_bot_entry(v)
        if entry is not None:
            result[bid] = entry

    return result


def save_managed_bots(bots: Dict[int, Dict[str, Any]]) -> bool:
    """يحفظ القاموس كاملاً (مع أخذ نسخة .bak تلقائياً)."""
    raw: Dict[str, Dict[str, Any]] = {}
    for bid, info in bots.items():
        if not isinstance(info, dict):
            continue
        if "token" not in info or not info["token"]:
            continue
        raw[str(int(bid))] = {
            "token":    info["token"],
            "name":     info.get("name", ""),
            "messages": dict(info.get("messages") or get_default_messages()),
            "added_at": info.get("added_at", ""),
        }
    return _save_json_atomic(BOTS_FILE, raw)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Public API — managed_bots_state.json
# ═══════════════════════════════════════════════════════════════════════════

def load_managed_state() -> Dict[int, Dict[int, Dict[str, bool]]]:
    """
    يقرأ managed_bots_state.json.
    الشكل: {bid: {uid: {start/reply/third/fourth: bool}}}
    يتجاهل الحاويات الفارغة.
    """
    raw = _load_json_safe(STATE_FILE)
    result: Dict[int, Dict[int, Dict[str, bool]]] = {}

    for k_bid, users_raw in raw.items():
        try:
            bid = int(k_bid)
        except (ValueError, TypeError):
            continue
        if bid <= 0 or not isinstance(users_raw, dict):
            continue

        users: Dict[int, Dict[str, bool]] = {}
        for k_uid, st in users_raw.items():
            try:
                uid = int(k_uid)
            except (ValueError, TypeError):
                continue
            if uid <= 0 or not isinstance(st, dict):
                continue
            users[uid] = {
                "start":  bool(st.get("start",  False)),
                "reply":  bool(st.get("reply",  False)),
                "third":  bool(st.get("third",  False)),
                "fourth": bool(st.get("fourth", False)),
            }

        if users:
            result[bid] = users

    return result


def save_managed_state(
    state: Dict[int, Dict[int, Dict[str, bool]]],
) -> bool:
    """يحفظ حالة كل البوتات (مع أخذ نسخة .bak تلقائياً)."""
    raw: Dict[str, Dict[str, Dict[str, bool]]] = {}
    for bid, users in state.items():
        if not users:
            continue
        raw[str(int(bid))] = {
            str(int(uid)): {
                "start":  bool(st.get("start",  False)),
                "reply":  bool(st.get("reply",  False)),
                "third":  bool(st.get("third",  False)),
                "fourth": bool(st.get("fourth", False)),
            }
            for uid, st in users.items()
            if isinstance(st, dict)
        }
    return _save_json_atomic(STATE_FILE, raw)


# ═══════════════════════════════════════════════════════════════════════════
# 8. أدوات مساعدة للـ runner/panel
# ═══════════════════════════════════════════════════════════════════════════

def next_managed_bot_id(existing: Dict[int, Any]) -> int:
    """أول رقم موجب غير مستخدم."""
    used: Set[int] = set()
    for k in existing.keys():
        try:
            used.add(int(k))
        except (ValueError, TypeError):
            continue
    n = 1
    while n in used:
        n += 1
    return n


def ensure_default_state() -> Dict[str, bool]:
    """حالة مستخدم جديد — كل الرسائل غير مكتملة."""
    return {"start": False, "reply": False, "third": False, "fourth": False}


def get_stats(
    bots: Dict[int, Dict[str, Any]],
    state: Dict[int, Dict[int, Dict[str, bool]]],
) -> Dict[str, int]:
    """إحصاء سريع للعرض في اللوحة."""
    total_users = 0
    completed = 0
    for users in state.values():
        total_users += len(users)
        for st in users.values():
            if all(st.get(f) for f in ("start", "reply", "third", "fourth")):
                completed += 1
    return {
        "bots": len(bots),
        "users": total_users,
        "completed": completed,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 9. تشخيص (لـ /mb_status لاحقاً)
# ═══════════════════════════════════════════════════════════════════════════

def health_check() -> Dict[str, Any]:
    """حالة الملفين — للاستخدام في أمر تشخيصي."""
    bots_ok = True
    state_ok = True

    try:
        bots = load_managed_bots()
    except Exception as _e:
        logger.warning("health_check/bots: %s", _e)
        bots_ok = False
        bots = {}

    try:
        state = load_managed_state()
    except Exception as _e:
        logger.warning("health_check/state: %s", _e)
        state_ok = False
        state = {}

    return {
        "data_dir": str(_DATA_DIR),
        "bots_file": {
            "path":     str(BOTS_FILE),
            "exists":   BOTS_FILE.exists(),
            "readable": bots_ok,
            "count":    len(bots),
        },
        "state_file": {
            "path":          str(STATE_FILE),
            "exists":        STATE_FILE.exists(),
            "readable":      state_ok,
            "bots_tracked":  len(state),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# 10. __all__
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    "BOTS_FILE",
    "STATE_FILE",
    "get_default_messages",
    "get_lock",
    "load_managed_bots",
    "save_managed_bots",
    "load_managed_state",
    "save_managed_state",
    "next_managed_bot_id",
    "ensure_default_state",
    "get_stats",
    "health_check",
]


# ═══════════════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═══════════════════════════════════════════════════════════════════════════

try:
    logger.debug(
        "🛡️ managed_bots_storage v5.7.0 loaded | "
        "data_dir=%s | atomic_write=✅ | bak_recovery=✅ | "
        "chmod=0600 | lock=lazy",
        _DATA_DIR,
    )
except Exception:
    pass