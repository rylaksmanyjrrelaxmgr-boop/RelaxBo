#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db_diagnostics.py — واجهة تشخيص وصيانة قاعدة البيانات (v7.1.0 — LATENCY-PROBE)
================================================================================
🆕 v7.1.0 — LATENCY-PROBE:
    🔬 FEAT-1: _probe_db_latency() — قياس كمون الشبكة/DB مباشرةً.
        • يقيس: TCP connect → first query → warm queries → PK SELECT → bulk fetch
        • يكشف: هل البطء من الشبكة أم من DB أم من البوت؟
        • يعمل على PostgreSQL / MySQL / SQLite.
    🔬 FEAT-2: format_latency_report() — تقرير HTML جاهز للعرض.
    🔬 FEAT-3: diagnose_latency() — API عام.
    🔬 FEAT-4: get_latency_verdict() — إصدار حكم آلي:
        • "excellent" | "good" | "acceptable" | "slow" | "critical"
        • مع توصية عملية بناءً على القياس.
    🟢 FEAT-5: cache 120s — يمنع الضغط عند استدعاءات متكررة.
    🟢 FEAT-6: لا يلمس pool البوت — يستخدم اتصالاً مستقلاً للقياس النقي.

🆕 v7.0.1 — FIX-BUNDLE (AF1 + AF2 + AF3 + AF4):
    🔴 FIX-AF1: bot_addition_log.date_column — من created_at إلى added_at.
    🔴 FIX-AF2: user_messages.date_column — من created_at إلى message_time.
    🔴 FIX-AF3: vacuum_analyze_tables — فحص SQLite قبل حلقة VACUUM.
    🔴 FIX-AF4: run_maintenance — نفس منطق AF3 في قسم VACUUM.

🆕 v7.0.0 — CACHE-LAYER + PARALLEL-REPORT:
    🟢 PERF-1: طبقة cache مركزية بـ TTL لكل دالة تشخيصية.
    🟢 PERF-2: _build_sections() يستخدم asyncio.gather (6 استعلامات متوازية).
    🟢 PERF-3: _invalidate_cache() جديدة + تُستدعى بعد VACUUM.
================================================================================
"""

import logging
import html as _html
import asyncio
import time
import os
import socket
import statistics
from typing import Dict, List, Any, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# الإصدار
# ═══════════════════════════════════════════════════════════════════════

VERSION = "7.1.0"

# 🆕 v6.9.4: حدود الدقة — تمنع الإنذارات الكاذبة
_MIN_DEAD_FOR_CRITICAL = 50   # أقل من هذا → لا يُصنَّف حرجاً مهما كانت النسبة
_MIN_DEAD_FOR_COLOR = 10      # أقل من هذا → ✅ دائماً


# ═══════════════════════════════════════════════════════════════════════
# 🆕 v7.0.0 PERF-1: طبقة Cache مركزية بـ TTL
# ═══════════════════════════════════════════════════════════════════════

_CACHE: Dict[str, Dict[str, Any]] = {}

_CACHE_TTL: Dict[str, float] = {
    "all_tables_health": 60.0,   # الأهم — 0.45s → ~0ms
    "all_table_names":   300.0,  # 5 دقائق
    "db_metadata":       300.0,  # 5 دقائق
    "pg_settings":       600.0,  # 10 دقائق (نادراً ما تتغير)
    "table_sizes":       300.0,  # 5 دقائق
    "indexes":           300.0,  # 5 دقائق
    "latency_probe":     120.0,  # 🆕 v7.1.0: 120s
}


def _cache_get(key: str) -> Optional[Any]:
    """إرجاع القيمة المخبأة أو None إن انتهت صلاحيتها."""
    entry = _CACHE.get(key)
    if not entry:
        return None
    ttl = entry.get("ttl", 60.0)
    if (time.monotonic() - entry["ts"]) >= ttl:
        _CACHE.pop(key, None)
        return None
    return entry["data"]


def _cache_set(key: str, data: Any, ttl: Optional[float] = None) -> None:
    """تخزين القيمة مع TTL."""
    _CACHE[key] = {
        "ts": time.monotonic(),
        "data": data,
        "ttl": ttl if ttl is not None else _CACHE_TTL.get(key, 60.0),
    }


def _invalidate_cache(key: Optional[str] = None) -> None:
    """
    🆕 v7.0.0 PERF-3: إبطال الكاش.
      • key=None → إبطال كل شيء
      • key="all_tables_health" → إبطال مفتاح واحد
    """
    if key is None:
        _CACHE.clear()
    else:
        _CACHE.pop(key, None)


def get_cache_stats() -> Dict[str, Any]:
    """🆕 v7.0.0: إحصائيات الكاش الحالية (للتشخيص)."""
    now = time.monotonic()
    out: Dict[str, Any] = {"entries": {}, "total_keys": 0}
    for k, v in _CACHE.items():
        age = now - v["ts"]
        ttl = v.get("ttl", 60.0)
        out["entries"][k] = {
            "age_sec": round(age, 2),
            "ttl_sec": ttl,
            "expires_in_sec": round(max(0.0, ttl - age), 2),
            "is_valid": age < ttl,
        }
        out["total_keys"] += 1
    return out


# ═══════════════════════════════════════════════════════════════════════
# 🆕 v6.9.4 — سياسة التنظيف الآمنة
# ═══════════════════════════════════════════════════════════════════════

_CLEANUP_POLICY: Dict[str, Dict[str, Any]] = {

    # ── المجموعة 1: سجلات النظام (آمنة تماماً) ──────────────────────
    "admin_logs": {
        "date_column": "created_at",
        "retention":   30,
        "max_mb":      20,
        "extra_where": None,
    },
    "payment_logs": {
        "date_column": "created_at",
        "retention":   90,
        "max_mb":      20,
        "extra_where": None,
    },
    "bot_addition_log": {
        # 🔴 FIX-AF1 (v7.0.1): العمود الصحيح هو added_at
        "date_column": "added_at",
        "retention":   90,
        "max_mb":      20,
        "extra_where": None,
    },

    # ── المجموعة 2: سجلات سلوكية ────────────────────────────────────
    "sentiment_history": {
        "date_column": "created_at",
        "retention":   90,
        "max_mb":      20,
        "extra_where": None,
    },

    # رسائل المستخدمين — 🔒 لا تحذف رسائل مشترك نشط
    "user_messages": {
        # 🔴 FIX-AF2 (v7.0.1): العمود الصحيح هو message_time
        "date_column": "message_time",
        "retention":   30,
        "max_mb":      20,
        "extra_where": (
            "user_id NOT IN ("
            "  SELECT user_id FROM subscriptions "
            "  WHERE status = 'active'"
            ")"
        ),
    },

    # ── المجموعة 3: أرشيف ───────────────────────────────────────────
    "penalty_archive": {
        "date_column": "created_at",
        "retention":   90,
        "max_mb":      20,
        "extra_where": None,
    },

    # ── المجموعة 4: حساسة — حماية مشددة ────────────────────────────
    "user_violations": {
        "date_column": "last_violation_time",
        "retention":   180,
        "max_mb":      20,
        "extra_where": (
            "user_id NOT IN ("
            "  SELECT user_id FROM subscriptions "
            "  WHERE status = 'active'"
            ")"
        ),
    },

    # ═══════════════════════════════════════════════════════════════
    # 🔒 جداول محمية — لا حذف أبداً
    # ═══════════════════════════════════════════════════════════════
    "users":             {"protected": True},
    "subscriptions":     {"protected": True},
    "user_penalties":    {"protected": True},
    "user_warnings":     {"protected": True},
    "user_points":       {"protected": True},
    "referrals":         {"protected": True},
    "referral_rewards":  {"protected": True},
    "support_tickets":   {"protected": True},
    "scheduled_posts":   {"protected": True},
    "banned_words":      {"protected": True},
    "posts":             {"protected": True},
    "bot_groups":        {"protected": True},
    "user_channels":     {"protected": True},
    "plans":             {"protected": True},
}

# للتوافق مع الكود القديم
_CLEANUP_TABLES = tuple(
    k for k, v in _CLEANUP_POLICY.items()
    if not v.get("protected")
)
_CLEANUP_THRESHOLD_KB = 20 * 1024


# ═══════════════════════════════════════════════════════════════════════
# Lazy imports
# ═══════════════════════════════════════════════════════════════════════

_DB_IMPORT_ERROR: Optional[str] = None


def _get_db():
    global _DB_IMPORT_ERROR
    try:
        from database import DB
        return DB
    except Exception as e:
        if _DB_IMPORT_ERROR is None:
            _DB_IMPORT_ERROR = f"{type(e).__name__}: {e}"
            logger.error(f"❌ db_diagnostics: فشل استيراد DB: {_DB_IMPORT_ERROR}")
        return None


def _now_iso() -> str:
    try:
        from utils import TimeUtils
        return TimeUtils.mecca_iso()[:19]
    except Exception:
        pass
    try:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "?"


def _get_db_type() -> str:
    db = _get_db()
    if db is not None:
        return str(getattr(db, "DB_TYPE", "sqlite")).upper()
    return "UNKNOWN"


def _is_postgres() -> bool:
    db = _get_db()
    return db is not None and bool(getattr(db, "USE_POSTGRES", False))


# ═══════════════════════════════════════════════════════════════════════
# أدوات مساعدة
# ═══════════════════════════════════════════════════════════════════════

def _safe_escape(text: Any) -> str:
    try:
        return _html.escape(str(text)) if text is not None else ""
    except Exception:
        return ""


_esc = _safe_escape


def _fmt_num(n: Any) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_bytes(num: Any) -> str:
    try:
        b = float(num or 0)
    except (TypeError, ValueError):
        return "0 B"
    if b < 1024:
        return f"{int(b)} B"
    if b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    if b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.2f} MB"
    return f"{b / (1024 * 1024 * 1024):.2f} GB"


def _fmt_ts(ts: Any) -> str:
    if not ts:
        return "—"
    try:
        s = str(ts)
        return s[:16] if len(s) >= 16 else s
    except Exception:
        return "—"


def _bar(value: float, max_value: float, width: int = 10,
         filled: str = "█", empty: str = "░") -> str:
    try:
        v = float(value)
        m = float(max_value)
        if m <= 0:
            return empty * width
        ratio = min(1.0, max(0.0, v / m))
        n = int(round(ratio * width))
        return filled * n + empty * (width - n)
    except Exception:
        return empty * width


def _dead_color(dead: int, live: int) -> str:
    """🆕 v6.9.3: حد أدنى مطلق — لا إنذارات على الأعداد التافهة."""
    if dead < _MIN_DEAD_FOR_COLOR:
        return "✅"

    total = live + dead
    if total == 0:
        return "⚪"
    ratio = dead / total

    if live < 1000 and ratio < 0.20:
        return "✅"
    if ratio < 0.05:
        return "✅"
    if ratio < 0.10:
        return "🟡"
    if ratio < 0.20:
        return "🟠"
    return "🔴"


# ═══════════════════════════════════════════════════════════════════════
# 🆕 v7.1.0: LATENCY PROBE — قياس كمون الشبكة/DB
# ═══════════════════════════════════════════════════════════════════════
#
# الهدف: تشخيص ما إذا كان البطء ناتجاً عن:
#   (أ) شبكة بطيئة بين البوت و DB  → connect_time مرتفع
#   (ب) DB محمّلة                   → warm queries مرتفعة
#   (ج) event loop مشبع             → كل القياسات طبيعية لكن البوت بطيء
#
# المنهجية:
#   1. TCP connect إلى DB host (صافي الشبكة — لا asyncpg).
#   2. asyncpg.connect → قياس زمن المصادقة الكامل.
#   3. أول استعلام (cold) → يتضمّن prepare + execute + fetch.
#   4. 5 استعلامات متتالية (warm) → لقياس الاستقرار.
#   5. PK SELECT حقيقي → قياس أقرب لسلوك البوت.
#   6. bulk fetch (100 صف) → لقياس bandwidth.
#
# ملاحظة: يستخدم اتصالاً مستقلاً — لا يؤثر على pool البوت.
# ═══════════════════════════════════════════════════════════════════════

async def _probe_db_latency(
    *,
    force: bool = False,
    socket_timeout: float = 5.0,
) -> Dict[str, Any]:
    """
    🔬 v7.1.0: قياس كمون الشبكة/DB مباشرةً.

    Args:
        force: تجاهل الكاش.
        socket_timeout: مهلة فتح socket TCP (ثوان).

    Returns:
        dict بمفاتيح:
          - ok: bool — هل نجح القياس؟
          - db_type: "postgres" | "mysql" | "sqlite" | "unknown"
          - host, port: معلومات الاتصال (بدون credentials)
          - tcp_connect_ms: زمن TCP connect (خارج asyncpg)
          - asyncpg_connect_ms: زمن asyncpg.connect الكامل (TCP+auth)
          - first_query_ms: أول استعلام (cold)
          - warm_queries_ms: قائمة أزمنة 5 استعلامات warm
          - warm_median_ms: الوسيط
          - pk_select_ms: PK SELECT حقيقي
          - bulk_fetch_ms: fetch 100 صف
          - bulk_rows: عدد الصفوف
          - verdict: excellent | good | acceptable | slow | critical
          - diagnosis: نص وصفي
          - recommendation: توصية عملية
    """

    if not force:
        cached = _cache_get("latency_probe")
        if cached is not None:
            return cached

    db = _get_db()
    if db is None:
        return {
            "ok": False,
            "error": "DB غير مستورد",
            "verdict": "unknown",
        }

    db_type = str(getattr(db, "DB_TYPE", "sqlite")).lower()
    result: Dict[str, Any] = {
        "ok": False,
        "db_type": db_type,
        "verdict": "unknown",
        "diagnosis": "",
        "recommendation": "",
    }

    # ═══════════════════════════════════════════════════════════════
    # SQLite — قياس مباشر بدون شبكة
    # ═══════════════════════════════════════════════════════════════
    if db_type == "sqlite":
        try:
            t0 = time.monotonic()
            await db.fetchval("SELECT 1", default=0)
            first_ms = (time.monotonic() - t0) * 1000

            warm: List[float] = []
            for _ in range(5):
                t0 = time.monotonic()
                await db.fetchval("SELECT 1", default=0)
                warm.append((time.monotonic() - t0) * 1000)

            result.update({
                "ok": True,
                "tcp_connect_ms": 0.0,
                "asyncpg_connect_ms": 0.0,
                "first_query_ms": round(first_ms, 2),
                "warm_queries_ms": [round(x, 2) for x in warm],
                "warm_median_ms": round(statistics.median(warm), 2),
                "pk_select_ms": round(first_ms, 2),
                "bulk_fetch_ms": 0.0,
                "bulk_rows": 0,
                "verdict": _verdict_from_warm(statistics.median(warm)),
                "diagnosis": "SQLite محلي — لا شبكة.",
                "recommendation": "الأداء يعتمد على I/O القرص.",
            })
        except Exception as e:
            result["error"] = f"SQLite probe: {e}"
        _cache_set("latency_probe", result, ttl=120.0)
        return result

    # ═══════════════════════════════════════════════════════════════
    # PostgreSQL / MySQL — قياس شبكة + DB
    # ═══════════════════════════════════════════════════════════════

    # استخرج host/port من DATABASE_URL (بدون credentials)
    db_url = (
        getattr(db, "DATABASE_URL", "")
        or os.getenv("DATABASE_URL", "")
    )
    host = "?"
    port = 0
    try:
        parsed = urlparse(db_url)
        host = parsed.hostname or "?"
        port = parsed.port or (5432 if db_type == "postgres" else 3306)
        result["host"] = host
        result["port"] = port
    except Exception as e:
        logger.debug(f"parse DATABASE_URL: {e}")

    # ─── 1) TCP connect (خارج asyncpg — قياس نقي) ────────────────
    if host != "?" and port > 0:
        try:
            t0 = time.monotonic()
            loop = asyncio.get_event_loop()
            # asyncio.open_connection عبر loop.sock_connect → قياس TCP handshake
            fut = loop.run_in_executor(
                None,
                lambda: socket.create_connection(
                    (host, port), timeout=socket_timeout
                ),
            )
            sock = await asyncio.wait_for(fut, timeout=socket_timeout + 1.0)
            tcp_ms = (time.monotonic() - t0) * 1000
            try:
                sock.close()
            except Exception:
                pass
            result["tcp_connect_ms"] = round(tcp_ms, 2)
        except asyncio.TimeoutError:
            result["tcp_connect_ms"] = -1.0
            result["error"] = f"TCP timeout >{socket_timeout}s"
            result["verdict"] = "critical"
            result["diagnosis"] = (
                f"🔴 لا يمكن الوصول إلى {host}:{port} خلال "
                f"{socket_timeout}s — شبكة مقطوعة أو DB مُطفأ."
            )
            _cache_set("latency_probe", result, ttl=120.0)
            return result
        except Exception as e:
            result["tcp_connect_ms"] = -1.0
            result["error"] = f"TCP: {type(e).__name__}: {e}"
            result["verdict"] = "critical"
            _cache_set("latency_probe", result, ttl=120.0)
            return result
    else:
        result["tcp_connect_ms"] = -1.0

    # ─── 2) asyncpg/asyncmy connect كامل ─────────────────────────
    conn = None
    try:
        t0 = time.monotonic()

        if db_type == "postgres":
            try:
                import asyncpg  # type: ignore
            except ImportError:
                result["error"] = "asyncpg غير مثبت"
                _cache_set("latency_probe", result, ttl=120.0)
                return result

            try:
                conn = await asyncio.wait_for(
                    asyncpg.connect(db_url, timeout=socket_timeout),
                    timeout=socket_timeout + 2.0,
                )
            except asyncio.TimeoutError:
                result["error"] = f"asyncpg.connect timeout >{socket_timeout}s"
                result["verdict"] = "critical"
                _cache_set("latency_probe", result, ttl=120.0)
                return result
        elif db_type == "mysql":
            try:
                import asyncmy  # type: ignore
            except ImportError:
                result["error"] = "asyncmy غير مثبت"
                _cache_set("latency_probe", result, ttl=120.0)
                return result
            try:
                conn = await asyncio.wait_for(
                    asyncmy.connect(db_url),
                    timeout=socket_timeout + 2.0,
                )
            except asyncio.TimeoutError:
                result["error"] = f"asyncmy.connect timeout >{socket_timeout}s"
                result["verdict"] = "critical"
                _cache_set("latency_probe", result, ttl=120.0)
                return result
        else:
            result["error"] = f"DB type غير مدعوم: {db_type}"
            _cache_set("latency_probe", result, ttl=120.0)
            return result

        connect_ms = (time.monotonic() - t0) * 1000
        result["asyncpg_connect_ms"] = round(connect_ms, 2)

        # ─── 3) أول استعلام (cold) ────────────────────────────────
        t0 = time.monotonic()
        if db_type == "postgres":
            await conn.fetchval("SELECT 1")
        else:
            cur = conn.cursor()
            await cur.execute("SELECT 1")
            await cur.fetchone()
            try:
                await cur.close()
            except Exception:
                pass
        first_ms = (time.monotonic() - t0) * 1000
        result["first_query_ms"] = round(first_ms, 2)

        # ─── 4) 5 استعلامات warm ─────────────────────────────────
        warm: List[float] = []
        for _ in range(5):
            t0 = time.monotonic()
            if db_type == "postgres":
                await conn.fetchval("SELECT 1")
            else:
                cur = conn.cursor()
                await cur.execute("SELECT 1")
                await cur.fetchone()
                try:
                    await cur.close()
                except Exception:
                    pass
            warm.append((time.monotonic() - t0) * 1000)
        result["warm_queries_ms"] = [round(x, 2) for x in warm]
        warm_median = statistics.median(warm)
        result["warm_median_ms"] = round(warm_median, 2)

        # ─── 5) PK SELECT حقيقي ──────────────────────────────────
        try:
            t0 = time.monotonic()
            if db_type == "postgres":
                await conn.fetchval(
                    "SELECT language FROM users WHERE user_id = $1 LIMIT 1",
                    1,
                )
            else:
                cur = conn.cursor()
                await cur.execute(
                    "SELECT language FROM users WHERE user_id = %s LIMIT 1",
                    (1,),
                )
                await cur.fetchone()
                try:
                    await cur.close()
                except Exception:
                    pass
            result["pk_select_ms"] = round(
                (time.monotonic() - t0) * 1000, 2
            )
        except Exception as e:
            result["pk_select_ms"] = -1.0
            logger.debug(f"pk_select probe: {e}")

        # ─── 6) bulk fetch ───────────────────────────────────────
        try:
            t0 = time.monotonic()
            if db_type == "postgres":
                rows = await conn.fetch(
                    "SELECT * FROM admin_logs LIMIT 100"
                )
            else:
                cur = conn.cursor()
                await cur.execute("SELECT * FROM admin_logs LIMIT 100")
                rows = await cur.fetchall()
                try:
                    await cur.close()
                except Exception:
                    pass
            bulk_ms = (time.monotonic() - t0) * 1000
            result["bulk_fetch_ms"] = round(bulk_ms, 2)
            result["bulk_rows"] = len(rows) if rows else 0
        except Exception as e:
            result["bulk_fetch_ms"] = -1.0
            result["bulk_rows"] = 0
            logger.debug(f"bulk_fetch probe: {e}")

        # ─── 7) الحكم ────────────────────────────────────────────
        verdict, diagnosis, recommendation = _compute_latency_verdict(result)
        result["verdict"] = verdict
        result["diagnosis"] = diagnosis
        result["recommendation"] = recommendation
        result["ok"] = True

    except Exception as e:
        logger.warning(f"_probe_db_latency: {e}")
        result["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        result["verdict"] = "critical"
    finally:
        if conn is not None:
            try:
                if db_type == "postgres":
                    await conn.close()
                else:
                    try:
                        conn.close()
                    except Exception:
                        pass
            except Exception:
                pass

    _cache_set("latency_probe", result, ttl=120.0)
    return result


def _verdict_from_warm(warm_ms: float) -> str:
    """حكم مختصر بناءً على الوسيط فقط (SQLite)."""
    if warm_ms < 5:
        return "excellent"
    if warm_ms < 20:
        return "good"
    if warm_ms < 100:
        return "acceptable"
    if warm_ms < 500:
        return "slow"
    return "critical"


def _compute_latency_verdict(result: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    🔬 v7.1.0 FEAT-4: يبني حكماً آلياً + توصية عملية.

    المنطق:
      • TCP connect > 300ms → شبكة سيئة (لا علاقة بالـ DB).
      • asyncpg_connect - tcp_connect > 200ms → مشكلة TLS/auth.
      • warm_median > 100ms → DB محمّلة.
      • first_query >> warm_median (10x+) → cold start للـ cache.
      • pk_select > 200ms → مشكلة فهارس أو network متكرر.
    """
    tcp = float(result.get("tcp_connect_ms") or 0)
    conn = float(result.get("asyncpg_connect_ms") or 0)
    warm = float(result.get("warm_median_ms") or 0)
    first = float(result.get("first_query_ms") or 0)
    pk = float(result.get("pk_select_ms") or 0)

    # ─── الحالة الأسوأ أولاً ────────────────────────────────
    if tcp < 0:
        return (
            "critical",
            "🔴 لا يمكن قياس TCP — الشبكة مقطوعة أو DB غير متاح.",
            "تحقّق من DATABASE_URL، حالة DB، وأي firewall.",
        )

    # ─── مقارنة TCP مع warm ────────────────────────────────
    if tcp > 300 and warm < 50:
        return (
            "slow",
            f"🟠 زمن TCP ({tcp:.0f}ms) مرتفع جداً، لكن DB يستجيب "
            f"بسرعة (warm={warm:.0f}ms). المشكلة في **الشبكة**، لا DB.",
            "انقل البوت أو DB إلى نفس المنطقة الجغرافية. "
            "أو استخدم connection pooler (PgBouncer) قريباً منك.",
        )

    if tcp > 150 and warm < 30:
        return (
            "acceptable",
            f"🟡 TCP={tcp:.0f}ms (مقبول)، DB={warm:.0f}ms. "
            f"هذا يطابق نمط: كل استعلام +{tcp:.0f}ms.",
            f"مع {tcp:.0f}ms ذهاب-وإياب، كل استعلام معقّد (3-5 round-trips) "
            f"يستغرق ~{tcp*3:.0f}-{tcp*5:.0f}ms. "
            "قلّل عدد الاستعلامات أو انقل DB أقرب.",
        )

    # ─── DB محمّلة ──────────────────────────────────────────
    if warm > 500:
        return (
            "critical",
            f"🔴 DB بطيء حتى على SELECT 1 ({warm:.0f}ms). "
            "الخادم مُشبع أو مشاكل hardware.",
            "راجع CPU/RAM/disk I/O على خادم PostgreSQL. "
            "جرّب pg_stat_statements لكشف استعلامات ثقيلة.",
        )

    if warm > 100:
        return (
            "slow",
            f"🟠 DB يستجيب بـ {warm:.0f}ms لـ SELECT 1 — بطء داخلي. "
            "ربما autovacuum يجري، أو replication lag.",
            "شغّل VACUUM ANALYZE، راجع pg_stat_activity، "
            "تحقّق من shared_buffers (يجب ≥ 25% RAM).",
        )

    # ─── كل شيء جيد ────────────────────────────────────────
    if warm < 20 and tcp < 50:
        return (
            "excellent",
            f"🟢 ممتاز — TCP={tcp:.0f}ms، DB={warm:.0f}ms.",
            "لا حاجة لأي تغيير.",
        )

    if warm < 50 and tcp < 100:
        return (
            "good",
            f"🟢 جيد — TCP={tcp:.0f}ms، DB={warm:.0f}ms.",
            "الأداء سليم.",
        )

    # ─── حالة default ───────────────────────────────────────
    return (
        "acceptable",
        f"🟡 TCP={tcp:.0f}ms، DB={warm:.0f}ms، "
        f"first={first:.0f}ms، PK={pk:.0f}ms.",
        "راقب الأداء — قد يحتاج ضبطاً لاحقاً.",
    )


def format_latency_report(probe: Dict[str, Any]) -> str:
    """
    🔬 v7.1.0 FEAT-2: تقرير HTML جاهز للعرض.
    """
    if not probe.get("ok"):
        err = _esc(probe.get("error", "خطأ غير معروف"))
        return (
            f"🔬 <b>اختبار الكمون</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ <b>فشل:</b> {err}"
        )

    lines: List[str] = []
    lines.append("🔬 <b>اختبار الكمون (Latency Probe)</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    db_type = str(probe.get("db_type", "?")).upper()
    host = probe.get("host", "")
    port = probe.get("port", "")
    if host and host != "?":
        lines.append(f"🗄️ <b>{_esc(db_type)}</b> @ "
                     f"<code>{_esc(host)}:{port}</code>")
    else:
        lines.append(f"🗄️ <b>{_esc(db_type)}</b> (محلي)")
    lines.append("")

    # ─── الشبكة ────────────────────────────────────────────
    tcp = float(probe.get("tcp_connect_ms", 0) or 0)
    if tcp > 0:
        tcp_icon = ("🟢" if tcp < 50 else
                    "🟡" if tcp < 150 else
                    "🟠" if tcp < 300 else "🔴")
        lines.append(f"🌐 TCP connect: {tcp_icon} <b>{tcp:.0f}ms</b>")

    conn = float(probe.get("asyncpg_connect_ms", 0) or 0)
    if conn > 0:
        conn_icon = ("🟢" if conn < 100 else
                     "🟡" if conn < 300 else "🔴")
        lines.append(f"🔌 asyncpg connect: {conn_icon} "
                     f"<b>{conn:.0f}ms</b>")
        if tcp > 0:
            delta = conn - tcp
            if delta > 200:
                lines.append(f"   ⚠️ فرق TCP↔connect: +{delta:.0f}ms "
                             f"(TLS/auth بطيء)")
    lines.append("")

    # ─── الاستعلامات ───────────────────────────────────────
    first = float(probe.get("first_query_ms", 0) or 0)
    if first > 0:
        first_icon = ("🟢" if first < 10 else
                      "🟡" if first < 100 else "🔴")
        lines.append(f"⚡ أول استعلام: {first_icon} <b>{first:.0f}ms</b>")

    warm_median = float(probe.get("warm_median_ms", 0) or 0)
    warm_list = probe.get("warm_queries_ms", []) or []
    if warm_median > 0:
        warm_icon = ("🟢" if warm_median < 20 else
                     "🟡" if warm_median < 100 else
                     "🟠" if warm_median < 500 else "🔴")
        preview = ", ".join(f"{x:.0f}" for x in warm_list[:5])
        lines.append(f"🔥 warm (5x): {warm_icon} "
                     f"وسيط=<b>{warm_median:.0f}ms</b> [{preview}]")

    pk = float(probe.get("pk_select_ms", 0) or 0)
    if pk > 0:
        pk_icon = ("🟢" if pk < 20 else
                   "🟡" if pk < 100 else "🔴")
        lines.append(f"🎯 PK SELECT: {pk_icon} <b>{pk:.0f}ms</b>")
    lines.append("")

    # ─── Bulk ──────────────────────────────────────────────
    bulk = float(probe.get("bulk_fetch_ms", 0) or 0)
    bulk_rows = int(probe.get("bulk_rows", 0) or 0)
    if bulk > 0 and bulk_rows > 0:
        per_row = bulk / bulk_rows
        lines.append(f"📦 fetch 100: <b>{bulk:.0f}ms</b> "
                     f"({per_row:.2f}ms/row)")
        lines.append("")

    # ─── الحكم ─────────────────────────────────────────────
    verdict = str(probe.get("verdict", "unknown"))
    diagnosis = str(probe.get("diagnosis", ""))
    recommendation = str(probe.get("recommendation", ""))

    verdict_label = {
        "excellent": "🟢 ممتاز",
        "good": "🟢 جيد",
        "acceptable": "🟡 مقبول",
        "slow": "🟠 بطيء",
        "critical": "🔴 حرج",
        "unknown": "⚪ غير معروف",
    }.get(verdict, "⚪ غير معروف")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 <b>الحكم:</b> {verdict_label}")
    lines.append("")
    if diagnosis:
        lines.append(f"<b>التشخيص:</b>")
        lines.append(f"  {_esc(diagnosis)}")
    if recommendation:
        lines.append("")
        lines.append(f"<b>التوصية:</b>")
        lines.append(f"  {_esc(recommendation)}")

    return "\n".join(lines)


async def diagnose_latency(*, force: bool = False) -> str:
    """
    🔬 v7.1.0 FEAT-3: API عام — يُرجع تقرير HTML جاهزاً.

    Args:
        force: تجاهل الكاش (افتراضياً 120s).
    """
    probe = await _probe_db_latency(force=force)
    return format_latency_report(probe)


async def get_latency_verdict() -> Dict[str, Any]:
    """
    🔬 v7.1.0: يُرجع الحكم فقط (بدون HTML) — للاستخدام البرمجي.
    """
    probe = await _probe_db_latency()
    return {
        "verdict": probe.get("verdict", "unknown"),
        "ok": probe.get("ok", False),
        "warm_median_ms": probe.get("warm_median_ms", 0),
        "tcp_connect_ms": probe.get("tcp_connect_ms", 0),
        "asyncpg_connect_ms": probe.get("asyncpg_connect_ms", 0),
        "diagnosis": probe.get("diagnosis", ""),
        "recommendation": probe.get("recommendation", ""),
    }


# ═══════════════════════════════════════════════════════════════════════
# 1) DB Metadata — 🆕 v7.0.0: cache 300s
# ═══════════════════════════════════════════════════════════════════════

async def _get_db_metadata() -> Dict[str, Any]:
    cached = _cache_get("db_metadata")
    if cached is not None:
        return cached

    db = _get_db()
    meta = {
        "size_bytes": 0,
        "size_display": "?",
        "current_schema": "?",
        "schemas": [],
        "database_name": "?",
    }
    if db is None:
        return meta

    try:
        if _is_postgres():
            size_b = await db.fetchval(
                "SELECT pg_database_size(current_database())", default=0
            ) or 0
            meta["size_bytes"] = int(size_b)
            meta["size_display"] = _fmt_bytes(size_b)

            meta["current_schema"] = await db.fetchval(
                "SELECT current_schema()", default="public"
            ) or "public"

            rows = await db.fetchall(
                "SELECT nspname FROM pg_namespace "
                "WHERE nspname NOT LIKE 'pg_%' "
                "  AND nspname != 'information_schema' "
                "ORDER BY nspname"
            ) or []
            meta["schemas"] = [
                r.get("nspname") for r in rows
                if isinstance(r, dict) and r.get("nspname")
            ]

            meta["database_name"] = await db.fetchval(
                "SELECT current_database()", default="?"
            ) or "?"
        else:
            size_kb = (await db.get_db_size_kb()
                       if hasattr(db, "get_db_size_kb") else 0)
            meta["size_bytes"] = int(size_kb * 1024)
            meta["size_display"] = _fmt_bytes(meta["size_bytes"])
            meta["current_schema"] = "main"
            meta["schemas"] = ["main"]
            meta["database_name"] = "sqlite"
    except Exception as e:
        logger.debug(f"_get_db_metadata: {e}")
        return meta  # لا نُخزّن الفشل في الكاش

    _cache_set("db_metadata", meta)
    return meta


# ═══════════════════════════════════════════════════════════════════════
# 2) Dead Tuples + Clean Tables — 🆕 v7.0.0: cache 60s
# ═══════════════════════════════════════════════════════════════════════

async def _get_all_tables_health() -> Tuple[List[Dict], List[Dict]]:
    cached = _cache_get("all_tables_health")
    if cached is not None:
        return cached

    db = _get_db()
    if db is None or not _is_postgres():
        return [], []

    try:
        rows = await db.fetchall("""
            SELECT
                c.relname AS table_name,
                c.relkind AS relkind,
                COALESCE(s.n_live_tup, 0) AS live_tuples,
                COALESCE(s.n_dead_tup, 0) AS dead_tuples,
                COALESCE(s.n_mod_since_analyze, 0) AS n_mod_since_analyze,
                s.last_vacuum,
                s.last_autovacuum,
                s.last_analyze,
                s.last_autoanalyze,
                c.reloptions
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_all_tables s ON s.relid = c.oid
            WHERE n.nspname = current_schema()
              AND c.relkind IN ('r', 'm')
            ORDER BY COALESCE(s.n_dead_tup, 0) DESC,
                     COALESCE(s.n_live_tup, 0) DESC
        """) or []
    except Exception as e:
        logger.warning(f"_get_all_tables_health: {e}")
        return [], []

    dirty = []
    clean = []

    for r in rows:
        if not isinstance(r, dict):
            continue

        name = r.get("table_name") or "?"
        relkind = str(r.get("relkind") or "r")
        is_matview = relkind == "m"

        live = int(r.get("live_tuples") or 0)
        dead = int(r.get("dead_tuples") or 0)
        total = live + dead
        ratio = (dead / total) if total > 0 else 0.0
        n_mod = int(r.get("n_mod_since_analyze") or 0)

        opts = r.get("reloptions") or []
        av_scale = None
        an_scale = None
        for opt in opts:
            if isinstance(opt, str):
                if "autovacuum_vacuum_scale_factor=" in opt:
                    try:
                        av_scale = float(opt.split("=")[1])
                    except Exception:
                        pass
                elif "autovacuum_analyze_scale_factor=" in opt:
                    try:
                        an_scale = float(opt.split("=")[1])
                    except Exception:
                        pass

        auto_tuned = av_scale is not None and an_scale is not None
        last_av = r.get("last_vacuum") or r.get("last_autovacuum")
        last_an = r.get("last_analyze") or r.get("last_autoanalyze")

        entry = {
            "name": name,
            "relkind": relkind,
            "is_matview": is_matview,
            "live": live,
            "dead": dead,
            "total": total,
            "ratio": ratio,
            "n_mod": n_mod,
            "last_av": last_av,
            "last_an": last_an,
            "auto_tuned": auto_tuned,
            "av_scale": av_scale,
            "an_scale": an_scale,
        }

        if dead > 0:
            dirty.append(entry)
        else:
            clean.append(entry)

    result = (dirty, clean)
    _cache_set("all_tables_health", result, ttl=60.0)
    return result


# ═══════════════════════════════════════════════════════════════════════
# 3) Activity Stats — بلا cache (real-time)
# ═══════════════════════════════════════════════════════════════════════

async def _get_activity_stats() -> Dict[str, Any]:
    out = {
        "long_tx": 0,
        "idle_tx": 0,
        "vacuum_running": 0,
        "total_active": 0,
        "total_connections": 0,
    }
    db = _get_db()
    if db is None or not _is_postgres():
        return out

    try:
        row = await db.fetchone("""
            SELECT
                count(*) FILTER (WHERE state = 'active') AS active,
                count(*) FILTER (WHERE state = 'idle in transaction') AS idle_tx,
                count(*) FILTER (
                    WHERE state = 'active'
                      AND now() - xact_start > interval '5 minutes'
                ) AS long_tx,
                count(*) FILTER (
                    WHERE query ILIKE 'VACUUM%'
                      AND state = 'active'
                ) AS vacuum_running,
                count(*) AS total
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
        """) or {}
        if isinstance(row, dict):
            out["total_active"] = int(row.get("active") or 0)
            out["idle_tx"] = int(row.get("idle_tx") or 0)
            out["long_tx"] = int(row.get("long_tx") or 0)
            out["vacuum_running"] = int(row.get("vacuum_running") or 0)
            out["total_connections"] = int(row.get("total") or 0)
    except Exception as e:
        logger.debug(f"_get_activity_stats: {e}")

    return out


# ═══════════════════════════════════════════════════════════════════════
# 4) PG Settings — cache 600s
# ═══════════════════════════════════════════════════════════════════════

_CRITICAL_SETTINGS = (
    "autovacuum",
    "autovacuum_naptime",
    "autovacuum_vacuum_scale_factor",
    "autovacuum_analyze_scale_factor",
    "autovacuum_vacuum_threshold",
    "autovacuum_analyze_threshold",
    "autovacuum_max_workers",
    "max_connections",
    "shared_buffers",
    "work_mem",
    "synchronous_commit",
    "idle_in_transaction_session_timeout",
    "statement_timeout",
    "server_version",
)


async def _get_pg_settings() -> Dict[str, str]:
    cached = _cache_get("pg_settings")
    if cached is not None:
        return cached

    db = _get_db()
    if db is None or not _is_postgres():
        return {}

    try:
        rows = await db.fetchall("""
            SELECT name, setting, unit
            FROM pg_settings
            WHERE name = ANY($1::text[])
        """, (list(_CRITICAL_SETTINGS),)) or []

        out: Dict[str, str] = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            name = r.get("name")
            setting = r.get("setting") or ""
            unit = r.get("unit") or ""
            out[name] = f"{setting}{unit}" if unit else str(setting)

        _cache_set("pg_settings", out, ttl=600.0)
        return out
    except Exception as e:
        logger.debug(f"_get_pg_settings: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════
# 5) Sizes + Indexes — cache 300s
# ═══════════════════════════════════════════════════════════════════════

async def _get_table_sizes(limit: int = 15) -> List[Dict[str, Any]]:
    cache_key = f"table_sizes_{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    db = _get_db()
    if db is None or not _is_postgres():
        return []
    fn = getattr(db, "get_table_sizes", None)
    if not callable(fn):
        return []
    try:
        result = await fn(limit) or []
        _cache_set(cache_key, result, ttl=300.0)
        return result
    except Exception as e:
        logger.debug(f"_get_table_sizes: {e}")
        return []


async def _get_indexes(tables: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    cache_key = "indexes_" + ",".join(sorted(tables))
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    db = _get_db()
    if db is None or not _is_postgres():
        return {}
    fn = getattr(db, "get_indexes_info", None)
    if not callable(fn):
        return {}
    try:
        result = await fn(tables) or {}
        _cache_set(cache_key, result, ttl=300.0)
        return result
    except Exception as e:
        logger.debug(f"_get_indexes: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════
# 6) Auto-Cleanup Status — بلا cache
# ═══════════════════════════════════════════════════════════════════════

async def _get_cleanup_status() -> List[Dict[str, Any]]:
    db = _get_db()
    if db is None or not _is_postgres():
        return []

    deletable = [
        k for k, v in _CLEANUP_POLICY.items()
        if not v.get("protected")
    ]
    if not deletable:
        return []

    try:
        rows = await db.fetchall("""
            SELECT relname AS table_name,
                   pg_total_relation_size(relid) AS total_bytes
            FROM pg_stat_user_tables
            WHERE relname = ANY($1::text[])
        """, (deletable,)) or []
    except Exception as e:
        logger.debug(f"_get_cleanup_status: {e}")
        return []

    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = r.get("table_name")
        if name not in _CLEANUP_POLICY:
            continue

        policy = _CLEANUP_POLICY[name]
        retention_days = policy["retention"]
        max_mb = policy["max_mb"]

        b = int(r.get("total_bytes") or 0)
        kb = b / 1024
        threshold_kb = max_mb * 1024

        if kb >= threshold_kb:
            color = "🔴"
            status = f"تجاوز الحد ({max_mb}MB) — سيُنظَّف"
        elif kb >= threshold_kb * 0.75:
            color = "🟡"
            status = f"قريب من الحد ({max_mb}MB)"
        else:
            color = "🟢"
            status = f"ضمن الحد ({max_mb}MB)"

        out.append({
            "name": name,
            "bytes": b,
            "display": _fmt_bytes(b),
            "color": color,
            "status": status,
            "retention_days": retention_days,
            "max_mb": max_mb,
        })

    out.sort(key=lambda x: (
        {"🔴": 0, "🟡": 1, "🟢": 2}.get(x["color"], 3),
        -x["bytes"],
    ))
    return out


# ═══════════════════════════════════════════════════════════════════════
# 7) Table Names Helper — cache 300s
# ═══════════════════════════════════════════════════════════════════════

async def _get_all_table_names() -> List[str]:
    cached = _cache_get("all_table_names")
    if cached is not None:
        return cached

    db = _get_db()
    if db is None:
        return []

    if not _is_postgres():
        try:
            rows = await db.fetchall(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ) or []
            result = [r.get("name") for r in rows
                      if isinstance(r, dict) and r.get("name")]
            _cache_set("all_table_names", result, ttl=300.0)
            return result
        except Exception:
            return []

    try:
        rows = await db.fetchall("""
            SELECT c.relname AS tablename
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relkind IN ('r', 'm')
            ORDER BY c.relkind DESC, c.relname
        """) or []
        result = [r.get("tablename") for r in rows
                  if isinstance(r, dict) and r.get("tablename")]
        _cache_set("all_table_names", result, ttl=300.0)
        return result
    except Exception as e:
        logger.debug(f"_get_all_table_names: {e}")
        try:
            rows = await db.fetchall("""
                SELECT tablename FROM pg_tables
                WHERE schemaname = current_schema()
                ORDER BY tablename
            """) or []
            result = [r.get("tablename") for r in rows
                      if isinstance(r, dict) and r.get("tablename")]
            _cache_set("all_table_names", result, ttl=300.0)
            return result
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════════════════
# 8) Score
# ═══════════════════════════════════════════════════════════════════════

def _calc_technical_score(
    dirty: List[Dict],
    activity: Dict,
    settings: Dict,
) -> Tuple[int, int, int, int]:
    score = 100
    critical = 0
    warn = 0

    for t in dirty:
        dead = int(t.get("dead", 0))
        r = float(t.get("ratio", 0))

        if dead < _MIN_DEAD_FOR_CRITICAL:
            continue

        if r >= 0.20:
            critical += 1
            score -= 10
        elif r >= 0.10:
            warn += 1
            score -= 3

    if activity.get("long_tx", 0) > 0:
        score -= 5
    if activity.get("idle_tx", 0) > 0:
        score -= 2
    if settings.get("autovacuum") != "on":
        score -= 15

    score = max(0, min(100, score))
    return score, critical, warn, activity.get("idle_tx", 0)


# ═══════════════════════════════════════════════════════════════════════
# 9) Maintenance — dict API
# ═══════════════════════════════════════════════════════════════════════

async def preview_maintenance() -> Dict[str, Any]:
    db = _get_db()
    result: Dict[str, Any] = {
        'plan': [],
        'total_deletions': 0,
        'vacuum_tables': [],
        'db_type': _get_db_type(),
        'protected_tables': [
            k for k, v in _CLEANUP_POLICY.items()
            if v.get("protected")
        ],
    }
    if db is None:
        return result

    if not _is_postgres():
        result['vacuum_tables'] = await _get_all_table_names()
        return result

    deletable = [
        k for k, v in _CLEANUP_POLICY.items()
        if not v.get("protected")
    ]

    sizes_map: Dict[str, int] = {}
    try:
        rows = await db.fetchall("""
            SELECT relname AS table_name,
                   pg_total_relation_size(relid) AS total_bytes
            FROM pg_stat_user_tables
            WHERE relname = ANY($1::text[])
        """, (deletable,)) or []
        for r in rows:
            if isinstance(r, dict) and r.get("table_name"):
                sizes_map[r["table_name"]] = int(r.get("total_bytes") or 0)
    except Exception as e:
        logger.debug(f"preview_maintenance sizes: {e}")

    total = 0
    for tbl in deletable:
        policy = _CLEANUP_POLICY[tbl]
        col = policy["date_column"]
        days = policy["retention"]
        max_mb = policy["max_mb"]
        extra_where = policy.get("extra_where")

        size_bytes = sizes_map.get(tbl, 0)
        size_kb = size_bytes / 1024
        threshold_kb = max_mb * 1024

        entry = {
            'name': tbl,
            'column': col,
            'days': days,
            'max_mb': max_mb,
            'threshold_str': f">{days}d | {max_mb}MB",
            'size_display': _fmt_bytes(size_bytes),
            'over_limit': size_kb >= threshold_kb,
            'count': 0,
            'error': None,
        }

        if not entry['over_limit']:
            entry['skip_reason'] = 'within_limit'
            result['plan'].append(entry)
            continue

        try:
            base_where = f"{col} < NOW() - INTERVAL '{days} days'"
            if extra_where:
                full_where = f"({base_where}) AND ({extra_where})"
            else:
                full_where = base_where

            row = await db.fetchone(
                f"SELECT COUNT(*) AS cnt FROM {tbl} "
                f"WHERE {full_where}"
            )
            cnt = int((row or {}).get("cnt") or 0)
            entry['count'] = cnt
            total += cnt
        except Exception as e:
            logger.warning(f"preview_maintenance({tbl}): {e}")
            entry['count'] = -1
            entry['error'] = str(e)[:100]

        result['plan'].append(entry)

    result['total_deletions'] = total
    result['vacuum_tables'] = await _get_all_table_names()
    return result


async def run_maintenance() -> Dict[str, Any]:
    db = _get_db()
    start = time.monotonic()
    result: Dict[str, Any] = {
        'duration_sec': 0.0,
        'deletions': {},
        'deletion_errors': {},
        'skipped': [],
        'protected': [
            k for k, v in _CLEANUP_POLICY.items()
            if v.get("protected")
        ],
        'vacuum': {'success': 0, 'failed': 0, 'details': []},
    }
    if db is None:
        result['duration_sec'] = round(time.monotonic() - start, 2)
        return result

    if _is_postgres():
        deletable = [
            k for k, v in _CLEANUP_POLICY.items()
            if not v.get("protected")
        ]

        sizes_map: Dict[str, int] = {}
        try:
            rows = await db.fetchall("""
                SELECT relname AS table_name,
                       pg_total_relation_size(relid) AS total_bytes
                FROM pg_stat_user_tables
                WHERE relname = ANY($1::text[])
            """, (deletable,)) or []
            for r in rows:
                if isinstance(r, dict) and r.get("table_name"):
                    sizes_map[r["table_name"]] = int(r.get("total_bytes") or 0)
        except Exception as e:
            logger.debug(f"run_maintenance sizes: {e}")

        for tbl in deletable:
            policy = _CLEANUP_POLICY[tbl]
            col = policy["date_column"]
            days = policy["retention"]
            max_mb = policy["max_mb"]
            extra_where = policy.get("extra_where")

            size_kb = sizes_map.get(tbl, 0) / 1024
            threshold_kb = max_mb * 1024

            if size_kb < threshold_kb:
                result['skipped'].append({
                    'name': tbl,
                    'reason': 'within_limit',
                    'size_display': _fmt_bytes(sizes_map.get(tbl, 0)),
                })
                continue

            try:
                base_where = f"{col} < NOW() - INTERVAL '{days} days'"
                if extra_where:
                    full_where = f"({base_where}) AND ({extra_where})"
                else:
                    full_where = base_where

                r = await db.execute(
                    f"DELETE FROM {tbl} WHERE {full_where}"
                )
                result['deletions'][tbl] = int(r or 0)
            except Exception as e:
                logger.warning(f"run_maintenance delete({tbl}): {e}")
                result['deletions'][tbl] = 0
                result['deletion_errors'][tbl] = str(e)[:100]

    if _get_db_type() == "SQLITE":
        try:
            await db.execute("VACUUM")
            try:
                await db.execute("ANALYZE")
            except Exception:
                pass
            result['vacuum']['success'] = 1
            result['vacuum']['details'].append(
                ("__sqlite_full__", True, None)
            )
        except Exception as e:
            result['vacuum']['failed'] = 1
            result['vacuum']['details'].append(
                ("__sqlite_full__", False, str(e)[:80])
            )
    else:
        tables = await _get_all_table_names()
        for t in tables:
            try:
                if hasattr(db, "vacuum") and callable(db.vacuum):
                    await db.vacuum(t)
                else:
                    await db.execute(f"VACUUM ANALYZE {t}")
                result['vacuum']['success'] += 1
                result['vacuum']['details'].append((t, True, None))
            except Exception as e:
                err = str(e).lower()
                if "does not exist" in err or "no such" in err:
                    result['vacuum']['details'].append((t, True, "skip"))
                else:
                    result['vacuum']['failed'] += 1
                    result['vacuum']['details'].append(
                        (t, False, str(e)[:80])
                    )
            try:
                await asyncio.sleep(0.05)
            except Exception:
                pass

    result['duration_sec'] = round(time.monotonic() - start, 2)
    _invalidate_cache()
    return result


# ═══════════════════════════════════════════════════════════════════════
# 10) Maintenance formatters
# ═══════════════════════════════════════════════════════════════════════

def format_maintenance_preview(preview: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("🧹 <b>معاينة الصيانة الآمنة</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("🔒 <i>المشتركون النشطون محميون تلقائياً</i>")
    lines.append("")

    plan = preview.get('plan', []) if isinstance(preview, dict) else []
    has_errors = False

    over = [p for p in plan if p.get('over_limit')]
    within = [p for p in plan if not p.get('over_limit')]

    if over:
        lines.append("🗑️ <b>جداول ستُحذف منها سجلات قديمة:</b>")
        for item in over:
            name = _esc(item.get('name', '?'))
            threshold = _esc(item.get('threshold_str', '?'))
            cnt = item.get('count', 0)
            size = _esc(item.get('size_display', '?'))

            if cnt == -1:
                icon = "❌"
                val = f"<i>فشل: {_esc(item.get('error', '?'))[:40]}</i>"
                has_errors = True
            elif cnt == 0:
                icon = "✅"
                val = "لا شيء (كلها محمية أو حديثة)"
            else:
                icon = "🗑️"
                val = f"<b>{cnt}</b> صف"

            lines.append(f"  {icon} <code>{name:<22}</code>")
            lines.append(f"      {size} | {threshold} → {val}")
        lines.append("")

    if within:
        lines.append(f"✅ <b>جداول ضمن الحد ({len(within)}):</b>")
        for item in within:
            name = _esc(item.get('name', '?'))
            size = _esc(item.get('size_display', '?'))
            max_mb = item.get('max_mb', '?')
            lines.append(f"  🟢 <code>{name:<22}</code> {size} / {max_mb}MB")
        lines.append("")

    protected = preview.get('protected_tables', []) if isinstance(preview, dict) else []
    if protected:
        lines.append(f"🔒 <b>جداول محمية ({len(protected)}):</b>")
        lines.append(
            "  <i>users, subscriptions, user_penalties, "
            "user_warnings, referral_rewards, ...</i>"
        )
        lines.append("")

    total = (preview.get('total_deletions', 0)
             if isinstance(preview, dict) else 0)
    lines.append(f"📊 <b>الإجمالي:</b> {total} صف سيُحذف")
    lines.append("")

    tables = (preview.get('vacuum_tables', [])
              if isinstance(preview, dict) else [])
    if tables:
        lines.append(f"🧹 <b>VACUUM على ({len(tables)} جدول/MV)</b>")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("لتنفيذ الصيانة:")
    lines.append("<code>/db_maintenance confirm</code>")

    if has_errors:
        lines.append("")
        lines.append("⚠️ <i>بعض استعلامات العدّ فشلت.</i>")

    return "\n".join(lines)


def format_maintenance_result(result: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("✅ <b>اكتملت الصيانة بنجاح</b>")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    duration = (result.get('duration_sec', 0.0)
                if isinstance(result, dict) else 0.0)
    lines.append(f"⏱️ <b>المدة:</b> {duration:.2f}s")
    lines.append("")

    deletions = (result.get('deletions', {})
                 if isinstance(result, dict) else {})
    deletion_errors = (result.get('deletion_errors', {})
                       if isinstance(result, dict) else {})
    skipped = (result.get('skipped', [])
               if isinstance(result, dict) else [])

    if deletions:
        lines.append("🗑️ <b>الحذف:</b>")
        for name, cnt in deletions.items():
            if name in deletion_errors:
                icon = "❌"
                val = "<i>فشل</i>"
            elif cnt == 0:
                icon = "✅"
                val = "لا شيء"
            else:
                icon = "🗑️"
                val = f"<b>{cnt}</b>"
            lines.append(f"  {icon} <code>{_esc(name):<22}</code> {val}")
        lines.append("")

    if skipped:
        lines.append(f"⏭️ <b>تخطّي ({len(skipped)} — ضمن الحد)</b>")
        lines.append("")

    protected = result.get('protected', [])
    if protected:
        lines.append(f"🔒 <b>محمية ({len(protected)}):</b>")
        lines.append(
            f"  <i>{', '.join(protected[:6])}"
            + ("..." if len(protected) > 6 else "")
            + "</i>"
        )
        lines.append("")

    vacuum = (result.get('vacuum', {})
              if isinstance(result, dict) else {})
    success = vacuum.get('success', 0) if isinstance(vacuum, dict) else 0
    failed = vacuum.get('failed', 0) if isinstance(vacuum, dict) else 0

    lines.append("🧹 <b>VACUUM:</b>")
    lines.append(f"  ✅ نجح: <b>{success}</b>")
    if failed:
        lines.append(f"  ❌ فشل: <b>{failed}</b>")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 11) Maintenance HTML shortcuts
# ═══════════════════════════════════════════════════════════════════════

async def diagnose_maintenance_preview() -> str:
    preview = await preview_maintenance()
    return format_maintenance_preview(preview)


async def run_db_maintenance() -> str:
    result = await run_maintenance()
    return format_maintenance_result(result)


async def vacuum_analyze_tables() -> str:
    db = _get_db()
    if db is None:
        return "❌ DB غير مستورد"

    start = time.monotonic()

    if _get_db_type() == "SQLITE":
        lines = ["🧹 <b>VACUUM (SQLite)</b>",
                 "━━━━━━━━━━━━━━━━━━━━━━", ""]
        try:
            await db.execute("VACUUM")
            try:
                await db.execute("ANALYZE")
            except Exception as _e:
                logger.debug(f"SQLite ANALYZE: {_e}")
            lines.append("  ✅ VACUUM + ANALYZE كامل")
            success = 1
            fail = 0
        except Exception as e:
            lines.append(f"  ❌ فشل: <code>{_esc(str(e)[:80])}</code>")
            success = 0
            fail = 1

        elapsed = time.monotonic() - start
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"⏱️ المدة: {elapsed:.2f}s | "
                     f"✅ نجح: {success} | ❌ فشل: {fail}")
        _invalidate_cache()
        return "\n".join(lines)

    tables = await _get_all_table_names()
    lines = ["🧹 <b>VACUUM ANALYZE</b>", "━━━━━━━━━━━━━━━━━━━━━━", ""]

    success = 0
    fail = 0
    for t in tables:
        try:
            if hasattr(db, "vacuum") and callable(db.vacuum):
                await db.vacuum(t)
            else:
                await db.execute(f"VACUUM ANALYZE {t}")
            success += 1
            lines.append(f"  ✅ {_esc(t)}")
        except Exception as e:
            err = str(e).lower()
            if "does not exist" in err or "no such" in err:
                lines.append(f"  ⏭️ {_esc(t)}")
            else:
                fail += 1
                lines.append(f"  ❌ {_esc(t)} — "
                             f"<code>{_esc(str(e)[:60])}</code>")
        await asyncio.sleep(0.05)

    elapsed = time.monotonic() - start
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"⏱️ المدة: {elapsed:.2f}s | "
                 f"✅ نجح: {success} | ❌ فشل: {fail}")

    _invalidate_cache()
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 11b) التنظيف التلقائي للـ MVs
# ═══════════════════════════════════════════════════════════════════════

async def auto_vacuum_dirty_mvs(min_dead: int = 10) -> Dict[str, Any]:
    db = _get_db()
    result: Dict[str, Any] = {
        'vacuumed': [],
        'failed': [],
        'total_dead_before': 0,
        'total_dead_after': 0,
        'cleaned': 0,
        'duration_sec': 0.0,
    }
    if db is None or not _is_postgres():
        return result

    start = time.monotonic()

    _invalidate_cache("all_tables_health")
    dirty, _ = await _get_all_tables_health()
    result['total_dead_before'] = sum(
        int(t.get('dead', 0)) for t in dirty
    )

    targets = [
        t for t in dirty
        if int(t.get('dead', 0)) >= int(min_dead)
    ]

    if not targets:
        result['duration_sec'] = round(time.monotonic() - start, 2)
        return result

    for t in targets:
        name = t.get('name')
        dead_before = int(t.get('dead', 0))
        is_mv = bool(t.get('is_matview', False))
        try:
            if hasattr(db, "vacuum") and callable(db.vacuum):
                await db.vacuum(name)
            else:
                await db.execute(f'VACUUM ANALYZE "{name}"')
            result['vacuumed'].append({
                'name': name,
                'dead_before': dead_before,
                'is_matview': is_mv,
            })
            result['cleaned'] += 1
        except Exception as e:
            err = str(e)[:120]
            logger.warning(f"auto_vacuum({name}): {err}")
            result['failed'].append({'name': name, 'error': err})
        try:
            await asyncio.sleep(0.05)
        except Exception:
            pass

    _invalidate_cache("all_tables_health")
    dirty_after, _ = await _get_all_tables_health()
    result['total_dead_after'] = sum(
        int(t.get('dead', 0)) for t in dirty_after
    )
    result['duration_sec'] = round(time.monotonic() - start, 2)

    logger.info(
        "🧹 auto_vacuum_dirty_mvs: cleaned=%d | dead %d → %d | %.2fs",
        result['cleaned'],
        result['total_dead_before'],
        result['total_dead_after'],
        result['duration_sec'],
    )
    return result


# ═══════════════════════════════════════════════════════════════════════
# 12) Build Sections — parallel gather
# ═══════════════════════════════════════════════════════════════════════

async def _build_sections() -> List[str]:
    parts: List[str] = []

    critical_idx_tables = ["posts", "banned_words", "bot_groups",
                           "users", "user_channels", "subscriptions"]

    gathered = await asyncio.gather(
        _get_db_metadata(),
        _get_all_tables_health(),
        _get_activity_stats(),
        _get_pg_settings(),
        _get_table_sizes(limit=15),
        _get_cleanup_status(),
        _get_all_table_names(),
        _get_indexes(critical_idx_tables),
        return_exceptions=True,
    )

    meta = gathered[0] if not isinstance(gathered[0], BaseException) else {}
    health_result = gathered[1] if not isinstance(gathered[1], BaseException) else ([], [])
    activity = gathered[2] if not isinstance(gathered[2], BaseException) else {}
    settings = gathered[3] if not isinstance(gathered[3], BaseException) else {}
    sizes = gathered[4] if not isinstance(gathered[4], BaseException) else []
    cleanup_status = gathered[5] if not isinstance(gathered[5], BaseException) else []
    idx_map = gathered[7] if not isinstance(gathered[7], BaseException) else {}

    if isinstance(health_result, tuple) and len(health_result) == 2:
        dirty, clean = health_result
    else:
        dirty, clean = [], []

    if not isinstance(meta, dict):
        meta = {"size_display": "?", "current_schema": "?",
                "schemas": [], "database_name": "?"}
    if not isinstance(activity, dict):
        activity = {}
    if not isinstance(settings, dict):
        settings = {}
    if not isinstance(sizes, list):
        sizes = []
    if not isinstance(cleanup_status, list):
        cleanup_status = []
    if not isinstance(idx_map, dict):
        idx_map = {}

    score, critical_count, warn_count, idle_tx_count = _calc_technical_score(
        dirty, activity, settings
    )
    total_dead = sum(t.get("dead", 0) for t in dirty)
    total_tables = len(dirty) + len(clean)

    # SECTION 1
    s1: List[str] = []
    s1.append(f"🔬 <b>تشخيص قاعدة البيانات v{VERSION}</b>")
    s1.append("━━━━━━━━━━━━━━━━━━━━━━")
    db_type_label = "PostgreSQL" if _is_postgres() else _get_db_type()
    s1.append(f"🗄️ <b>النوع:</b> {_esc(db_type_label)}")
    s1.append(f"💾 <b>الحجم:</b> {meta.get('size_display', '?')}")
    s1.append(f"📋 <b>Schema:</b> {_esc(meta.get('current_schema', '?'))}")
    schemas = meta.get("schemas", [])
    if schemas:
        s1.append(f"📋 <b>Schemas المتاحة:</b> {_esc(', '.join(schemas))}")
    s1.append(f"🗃️ <b>Database:</b> {_esc(meta.get('database_name', '?'))}")
    s1.append("")

    score_icon = "🟢" if score >= 80 else ("🟡" if score >= 60 else "🔴")
    s1.append("📌 <b>الخلاصة التقنية</b>")
    s1.append(f"  🔴 جداول حرجة: <b>{critical_count}</b>")
    s1.append(f"  🟡 جداول تحتاج انتباه: <b>{warn_count}</b>")
    s1.append(f"  ⚠️ Long transactions: <b>{activity.get('long_tx', 0)}</b>")
    s1.append(f"  🟠 Idle transactions: <b>{idle_tx_count}</b>")
    s1.append(f"  💀 إجمالي dead tuples: <b>{_fmt_num(total_dead)}</b>")
    s1.append(f"  📊 جداول مهمة: <b>{len(dirty)}</b>")
    s1.append(f"  🗂️ إجمالي الجداول: <b>{total_tables}</b>")
    av_setting = settings.get("autovacuum", "?")
    av_icon = "🟢" if av_setting == "on" else "🔴"
    s1.append(f"  autovacuum: {av_icon} <b>{_esc(av_setting).upper()}</b>")
    s1.append(f"  مؤشر الحالة التقني: <b>{score}/100</b> {score_icon}")
    parts.append("\n".join(s1))

    # SECTION 2 — التحليل المنطقي
    s2: List[str] = []
    s2.append("╔══════════════════════════════════╗")
    s2.append("║  🎯 التحليل المنطقي          ║")
    s2.append("╚══════════════════════════════════╝")
    s2.append("")
    if av_setting == "on":
        s2.append("🟢 autovacuum = ON.")
    else:
        s2.append("🔴 autovacuum = OFF — خطر على الأداء.")

    if settings.get("synchronous_commit") == "off":
        s2.append("")
        s2.append("ℹ️ synchronous_commit=off — مقصود لتحسين الأداء. "
                  "لا تعتبره خطأً.")

    if critical_count > 0:
        s2.append("")
        s2.append(f"🔴 <b>{critical_count} جدول حرج</b> — راجع التفاصيل.")
    else:
        s2.append("")
        s2.append("✅ لا توجد جداول حرجة (الحد الأدنى "
                  f"{_MIN_DEAD_FOR_CRITICAL} dead tuples).")

    s2.append("")
    s2.append("🔒 <b>سياسة التنظيف:</b> آمنة — "
              "المشتركون والمستخدمون محميون.")
    parts.append("\n".join(s2))

    # SECTION 3 — Dead Tuples
    if dirty:
        s3: List[str] = []
        s3.append("━━━━━━━━━━━━━━━━━━━━━━")
        s3.append("📊 <b>التفاصيل الكاملة</b>")
        s3.append("━━━━━━━━━━━━━━━━━━━━━━")
        s3.append("")
        s3.append("1. <b>Dead Tuples + نشاط التنظيف</b>")
        s3.append("")
        for t in dirty[:20]:
            color = _dead_color(t["dead"], t["live"])
            name = _esc(t["name"])
            mv_tag = " <code>[MV]</code>" if t.get("is_matview") else ""
            ratio_pct = t["ratio"] * 100
            s3.append(f"{color} <b>{name}</b>{mv_tag}")
            s3.append(f"     live={_fmt_num(t['live'])} "
                      f"dead={_fmt_num(t['dead'])} ({ratio_pct:.1f}%)")
            av = _fmt_ts(t["last_av"])
            an = _fmt_ts(t["last_an"])
            mod = t["n_mod"]
            s3.append(f"     🧹 AV: {av} | 📊 AN: {an} | 🔄 mod={mod}")
            s3.append("")
        parts.append("\n".join(s3))

    if clean:
        s3b: List[str] = []
        s3b.append("1b. <b>جداول نظيفة (dead=0)</b>")
        s3b.append("")
        clean_sorted = sorted(clean, key=lambda x: -x["live"])
        for t in clean_sorted[:15]:
            an = _fmt_ts(t["last_an"])
            mv_tag = " <code>[MV]</code>" if t.get("is_matview") else ""
            s3b.append(f"✅ <b>{_esc(t['name'])}</b>{mv_tag}")
            s3b.append(f"     live={_fmt_num(t['live'])} | 📊 AN: {an}")
        if len(clean_sorted) > 15:
            s3b.append(f"… و{len(clean_sorted) - 15} جدول نظيف آخر")
        parts.append("\n".join(s3b))

    # SECTION 4 — Autovacuum
    tuned = [t for t in dirty + clean if t.get("auto_tuned")]
    not_tuned = [t for t in dirty + clean if not t.get("auto_tuned")]

    s4: List[str] = []
    s4.append("2. <b>Autovacuum للجداول الحرجة (HEAVY)</b>")
    s4.append("")
    for tname in ("posts", "subscriptions", "user_penalties", "users"):
        match = next((t for t in tuned if t["name"] == tname), None)
        if match:
            av = match.get("av_scale", "?")
            an = match.get("an_scale", "?")
            s4.append(f"✅ <b>{_esc(tname)}</b> — مضبوط ({av}/{an})")
        else:
            match2 = next((t for t in not_tuned if t["name"] == tname), None)
            if match2:
                s4.append(f"⚙️ <b>{_esc(tname)}</b> — غير مضبوط")
    parts.append("\n".join(s4))

    if not_tuned:
        s4b: List[str] = []
        s4b.append("")
        s4b.append(f"2b. <b>جداول ليست مضبوطة autovacuum "
                   f"({len(not_tuned)} من {len(tuned) + len(not_tuned)})</b>")
        s4b.append("")
        for t in not_tuned[:15]:
            mv_tag = " <code>[MV]</code>" if t.get("is_matview") else ""
            s4b.append(f"⚙️ <b>{_esc(t['name'])}</b>{mv_tag} — "
                       f"live={_fmt_num(t['live'])} dead={_fmt_num(t['dead'])}")
        if len(not_tuned) > 15:
            s4b.append(f"… و{len(not_tuned) - 15} آخر")
        parts.append("\n".join(s4b))

    # SECTION 5 — Activity
    s5: List[str] = []
    s5.append("3. <b>نشاط PostgreSQL / Blockers</b>")
    s5.append("")
    if (activity.get("long_tx", 0) == 0
            and activity.get("idle_tx", 0) == 0
            and activity.get("vacuum_running", 0) == 0):
        s5.append("✅ لا توجد معاملات طويلة / idle-in-tx / VACUUM جارٍ.")
    else:
        if activity.get("long_tx", 0):
            s5.append(f"⚠️ Long transactions: <b>{activity['long_tx']}</b>")
        if activity.get("idle_tx", 0):
            s5.append(f"🟠 Idle transactions: <b>{activity['idle_tx']}</b>")
        if activity.get("vacuum_running", 0):
            s5.append(f"🧹 VACUUM قيد التنفيذ: <b>{activity['vacuum_running']}</b>")
    s5.append(f"📊 إجمالي الاتصالات: <b>{activity.get('total_connections', 0)}</b>")
    parts.append("\n".join(s5))

    # SECTION 6 — Sizes
    if sizes:
        s6: List[str] = []
        s6.append("4. <b>أحجام الجداول — Top 15</b>")
        s6.append("")
        for t in sizes[:15]:
            name = t.get("name", "?")
            display = t.get("total_display", "0 B")
            s6.append(f"  <code>{_esc(name):<22}</code> {display}")
        parts.append("\n".join(s6))

    # SECTION 7 — Indexes
    if idx_map:
        s7: List[str] = []
        s7.append("5. <b>الفهارس الحرجة (يدوياً)</b>")
        s7.append("")
        for tname in critical_idx_tables:
            if tname in idx_map:
                cnt = len(idx_map[tname])
                s7.append(f"✅ <b>{_esc(tname)}</b> ({cnt})")
        parts.append("\n".join(s7))

    # SECTION 8 — PG Settings
    if settings:
        s8: List[str] = []
        s8.append("6. <b>إعدادات PostgreSQL</b>")
        s8.append("")
        for k in _CRITICAL_SETTINGS:
            if k in settings:
                s8.append(f"  <code>{_esc(k)}</code> = {_esc(settings[k])}")
        parts.append("\n".join(s8))

    # SECTION 9 — Cleanup status
    if cleanup_status:
        s9: List[str] = []
        s9.append("8. <b>Auto-Cleanup (سياسة آمنة)</b>")
        s9.append("")
        s9.append("🔒 <i>المشتركون والمستخدمون محميون تلقائياً</i>")
        s9.append("")
        for c in cleanup_status:
            retention = c.get("retention_days", "?")
            s9.append(f"  {c['color']} <b>{_esc(c['name'])}</b> — "
                      f"{c['display']} (حد {c['max_mb']}MB, "
                      f"احتفاظ {retention}d)")
        s9.append("")

        protected_list = [
            k for k, v in _CLEANUP_POLICY.items()
            if v.get("protected")
        ]
        s9.append(f"🔒 <b>جداول محمية ({len(protected_list)}):</b>")
        s9.append(
            "  <i>users, subscriptions, user_penalties, "
            "user_warnings, referral_rewards, scheduled_posts, ...</i>"
        )
        s9.append("")
        s9.append("⚙️ كل 6h | VACUUM: ON 🟢 | Mode: safe")
        parts.append("\n".join(s9))

    # SECTION 10 — Footer
    parts.append(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ <b>اكتمل التشخيص</b>\n"
        f"🕐 <i>{_now_iso()}</i>"
    )

    # SECTION 11 — Maintenance Preview
    try:
        preview = await preview_maintenance()
        s11_text = format_maintenance_preview(preview)
        parts.append(s11_text)
    except Exception as e:
        logger.warning(f"maintenance preview in sections: {e}")

    # 🆕 v7.1.0 SECTION 12 — Latency Probe (قسم جديد)
    try:
        latency_probe = await _probe_db_latency()
        # نضيف القسم فقط إذا كان DB يحتاج فحص (لا نُثقله)
        # أو إذا كان الحكم slow/critical — كتنبيه
        verdict = latency_probe.get("verdict", "unknown")
        if verdict in ("slow", "critical", "acceptable"):
            latency_text = format_latency_report(latency_probe)
            parts.append(latency_text)
    except Exception as e:
        logger.debug(f"latency probe in sections: {e}")

    return parts


# ═══════════════════════════════════════════════════════════════════════
# 13) Public API — Diagnostics
# ═══════════════════════════════════════════════════════════════════════

async def diagnose_db() -> str:
    parts = await _build_sections()
    return "\n\n".join(parts)


async def diagnose_db_split() -> List[str]:
    return await _build_sections()


async def diagnose_db_quick() -> str:
    db = _get_db()
    if db is None:
        return "❌ DB غير مستورد"

    lines: List[str] = []

    try:
        meta = await _get_db_metadata()
        db_type = "PostgreSQL" if _is_postgres() else _get_db_type()
        lines.append(f"🔬 <b>DB:</b> {db_type} | 💾 {meta.get('size_display', '?')}")
    except Exception:
        lines.append(f"🔬 <b>DB:</b> {_get_db_type()}")

    total_dead = 0
    critical = 0
    try:
        dirty, clean = await _get_all_tables_health()
        total_dead = sum(t.get("dead", 0) for t in dirty)
        critical = sum(
            1 for t in dirty
            if t.get("ratio", 0) >= 0.20
            and int(t.get("dead", 0)) >= _MIN_DEAD_FOR_CRITICAL
        )
    except Exception:
        pass
    lines.append(
        f"💀 Dead: <b>{_fmt_num(total_dead)}</b> | "
        f"🔴 حرجة: <b>{critical}</b>"
    )

    try:
        activity = await _get_activity_stats()
        idle = activity.get("idle_tx", 0)
        long_tx = activity.get("long_tx", 0)
        idle_icon = "🟢" if idle == 0 else ("🟡" if idle < 3 else "🔴")
        long_icon = "🟢" if long_tx == 0 else "🔴"
        lines.append(
            f"{idle_icon} idle-tx: <b>{idle}</b> | "
            f"{long_icon} long-tx: <b>{long_tx}</b>"
        )
    except Exception:
        lines.append("🟠 idle-tx: ? | long-tx: ?")

    try:
        settings = await _get_pg_settings()
        av = settings.get("autovacuum", "?")
        av_icon = "🟢" if av == "on" else "🔴"
        lines.append(f"{av_icon} autovacuum: <b>{_esc(av).upper()}</b>")
    except Exception:
        pass

    # 🆕 v7.1.0: سطر كمون مختصر في التقرير السريع
    try:
        latency = await get_latency_verdict()
        if latency.get("ok"):
            verdict = latency.get("verdict", "unknown")
            icon = {
                "excellent": "🟢",
                "good": "🟢",
                "acceptable": "🟡",
                "slow": "🟠",
                "critical": "🔴",
            }.get(verdict, "⚪")
            warm = latency.get("warm_median_ms", 0)
            tcp = latency.get("tcp_connect_ms", 0)
            if tcp > 0:
                lines.append(
                    f"{icon} كمون: TCP={tcp:.0f}ms، DB={warm:.0f}ms"
                )
            else:
                lines.append(f"{icon} كمون DB: {warm:.0f}ms")
    except Exception:
        pass

    return "\n".join(lines)


async def get_diagnostics_data(top_n: int = 15) -> Dict[str, Any]:
    parts = await _build_sections()
    return {
        "sections": parts,
        "available": True,
        "db_type": _get_db_type(),
        "version": VERSION,
    }


# ═══════════════════════════════════════════════════════════════════════
# 14) Aliases
# ═══════════════════════════════════════════════════════════════════════

maintenance_preview = diagnose_maintenance_preview
preview_maintenance_html = diagnose_maintenance_preview
run_maintenance_html = run_db_maintenance
execute_maintenance = run_db_maintenance
perform_maintenance = run_db_maintenance
do_maintenance = run_db_maintenance

vacuum_all_tables = vacuum_analyze_tables
vacuum_tables = vacuum_analyze_tables
run_vacuum = vacuum_analyze_tables
do_vacuum = vacuum_analyze_tables
vacuum_db = vacuum_analyze_tables

diagnose = diagnose_db
run_diagnostics = diagnose_db
get_diagnostics = diagnose_db
diagnose_postgres = diagnose_db
diag = diagnose_db
diagnose_database = diagnose_db
diagnose_split = diagnose_db_split
get_diagnostics_split = diagnose_db_split
diagnostics_split = diagnose_db_split
split_diagnostics = diagnose_db_split
get_diagnostics_report = diagnose_db
get_quick_health = diagnose_db_quick

get_db_info = _get_db_metadata
get_database_info = _get_db_metadata
get_pg_info = _get_db_metadata

auto_vacuum = auto_vacuum_dirty_mvs
auto_cleanup = auto_vacuum_dirty_mvs
cleanup_dead_tuples = auto_vacuum_dirty_mvs
vacuum_dirty_tables = auto_vacuum_dirty_mvs

invalidate_cache = _invalidate_cache
clear_cache = _invalidate_cache

# 🆕 v7.1.0: aliases للـ latency
probe_latency = _probe_db_latency
latency_report = diagnose_latency
check_latency = diagnose_latency
get_latency_report = diagnose_latency


# ═══════════════════════════════════════════════════════════════════════
# 15) __all__
# ═══════════════════════════════════════════════════════════════════════

__all__ = [
    "VERSION",
    # Cache API
    "invalidate_cache",
    "clear_cache",
    "get_cache_stats",
    # Diagnostics
    "diagnose_db",
    "diagnose_db_split",
    "diagnose_db_quick",
    "get_diagnostics_data",
    # 🆕 v7.1.0: Latency Probe
    "diagnose_latency",
    "get_latency_verdict",
    "format_latency_report",
    "probe_latency",
    "latency_report",
    "check_latency",
    "get_latency_report",
    # Auto vacuum
    "auto_vacuum_dirty_mvs",
    "auto_vacuum",
    "auto_cleanup",
    "cleanup_dead_tuples",
    "vacuum_dirty_tables",
    # Maintenance
    "preview_maintenance",
    "run_maintenance",
    "format_maintenance_preview",
    "format_maintenance_result",
    "diagnose_maintenance_preview",
    "run_db_maintenance",
    "vacuum_analyze_tables",
    "maintenance_preview",
    "preview_maintenance_html",
    "run_maintenance_html",
    "execute_maintenance",
    "perform_maintenance",
    "do_maintenance",
    "vacuum_all_tables",
    "vacuum_tables",
    "run_vacuum",
    "do_vacuum",
    "vacuum_db",
    # Aliases
    "diagnose",
    "run_diagnostics",
    "get_diagnostics",
    "diagnose_postgres",
    "diag",
    "diagnose_database",
    "diagnose_split",
    "get_diagnostics_split",
    "diagnostics_split",
    "split_diagnostics",
    "get_diagnostics_report",
    "get_quick_health",
    "get_db_info",
    "get_database_info",
    "get_pg_info",
]


# ═══════════════════════════════════════════════════════════════════════
# LOAD BEACON
# ═══════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "🛡️ db_diagnostics.py v%s loaded | "
        "LATENCY-PROBE ✅ | "
        "CACHE-LAYER ✅ | "
        "PARALLEL-REPORT ✅ | "
        "MV-AWARE-HEALTH ✅ | "
        "SAFE CLEANUP ✅ | "
        "subscribers protected 🔒 | "
        "MVs in VACUUM ✅ | "
        "abs-threshold=%d dead | "
        "auto-vacuum API ✅ | "
        "AF1+AF2+AF3+AF4 ✅ | "
        "cache_keys=%d | exports=%d",
        VERSION,
        _MIN_DEAD_FOR_CRITICAL,
        len(_CACHE_TTL),
        len(__all__),
    )
except Exception:
    pass