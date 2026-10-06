#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_auto_block.py - v1.1.0
=============================================================================
🗄️ جدول تلقائي لحجب المصادر المشبوهة (Post Bot / Spam channels)
=============================================================================
🆕 v1.1.0 (FIX + FEATURES):
  🔴 FIX-CRITICAL: DB.DB_TYPE → استخدام USE_POSTGRES/USE_MYSQL الرسمية
  🔴 FIX-CRITICAL: cleanup_old_entries كان يُرجع 0 دائماً
                   (DB.execute يُرجع "DELETE N" كنص، ليس int)
  🔴 FIX-CRITICAL: SQLite كان يستخدم INSERT OR REPLACE
                   (يحذف الصف ثم يعيد إدخاله → يفقد created_at)
                   → استُبدل بـ ON CONFLICT DO UPDATE
  🟡 FIX: MySQL cleanup استخدم NOW() بدل UTC_TIMESTAMP() للتوحيد
  🟡 FIX: ensure_table أصبح مُخزَّناً (cache flag) — لا يضرب DB كل مرة
  🟡 FIX: log levels مُحدَّثة (warning للأخطاء الحقيقية، debug لغير الموجود)
  🟢 NEW: update_source()       — تحديث source_name بدون زيادة hit_count
  🟢 NEW: get_source()          — جلب مصدر واحد
  🟢 NEW: count_blocked()       — عدّ سريع
  🟢 NEW: get_top_blocked()     — أعلى N مصادر
  🟢 NEW: search_by_name()      — بحث جزئي بالاسم
  🟢 NEW: bulk_add()            — إضافة دفعة مصادر
  🟢 NEW: reset_hits()          — تصفير hit_count بعد مراجعة إدارية
  🟢 NEW: add_source(auto_added=...) — تمييز الإضافة اليدوية من التلقائية
  🟢 NEW: _execute() helper      — توافق مع DB.execute أو DB.transaction
  🟢 NEW: _parse_delete_count()  — تحويل نتيجة DELETE إلى int بأمان
  🟢 NEW: _normalize_source_type() — تطبيع source_type

الميزات:
    ✅ إنشاء الجدول تلقائياً (PostgreSQL / MySQL / SQLite)
    ✅ إضافة مصدر (upsert آمن — idempotent)
    ✅ فحص مصدر (is_blocked)
    ✅ عرض القائمة (list_blocked)
    ✅ إزالة مصدر (remove_source)
    ✅ تنظيف المصادر القديمة (cleanup_old_entries)

التكامل:
    - يُستورد تلقائياً من handlers_message.py
    - يُنشئ الجدول عند أول استدعاء (ensure_table)
    - يعمل بدون أي تعديل على main.py

الاستخدام:
    from database_auto_block import (
        ensure_table, is_blocked, add_source,
        list_blocked, remove_source, cleanup_old_entries,
        # 🆕 v1.1.0
        get_source, update_source, count_blocked,
        get_top_blocked, search_by_name, bulk_add, reset_hits,
    )
=============================================================================
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any, Iterable


logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# ثوابت
# ═════════════════════════════════════════════════════════════════════

DEFAULT_CLEANUP_DAYS = 90
MAX_BULK_SIZE = 10_000
MAX_SOURCE_TYPE_LEN = 20
MAX_SOURCE_NAME_LEN = 255
MAX_REASON_LEN = 100

_ALLOWED_SOURCE_TYPES = frozenset({
    "channel", "group", "user", "bot",
    "anonymous", "supergroup", "unknown",
})


# ═════════════════════════════════════════════════════════════════════
# حالة عامة
# ═════════════════════════════════════════════════════════════════════

_table_ensured: bool = False


# ═════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════

def _get_db_type() -> str:
    """
    🔴 FIX v1.1.0: يعتمد على USE_POSTGRES/USE_MYSQL الرسمية
    بدلاً من DB.DB_TYPE غير المضمون.
    """
    try:
        from database import USE_POSTGRES, USE_MYSQL
        if USE_POSTGRES:
            return "postgres"
        if USE_MYSQL:
            return "mysql"
        return "sqlite"
    except Exception as e:
        logger.debug("_get_db_type: fallback → sqlite (%s)", e)
        # fallback للتوافق الخلفي فقط
        try:
            t = getattr(__import__("database").DB, "DB_TYPE", None)
            if t:
                return str(t).lower()
        except Exception:
            pass
        return "sqlite"


def _parse_delete_count(result: Any) -> int:
    """
    🔴 FIX v1.1.0: تحويل نتيجة DELETE إلى int بأمان.

    - asyncpg: يُرجع "DELETE N"
    - aiomysql: يُرجع rowcount كـ int
    - aiosqlite (عبر wrapper): قد يُرجع int أو "DELETE N"
    """
    if result is None:
        return 0
    if isinstance(result, bool):
        return 0
    if isinstance(result, int):
        return result
    if isinstance(result, str):
        parts = result.strip().split()
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except (ValueError, IndexError):
                pass
        try:
            return int(result)
        except ValueError:
            return 0
    return 0


def _normalize_source_type(st: Any) -> str:
    """تطبيع source_type إلى قيمة آمنة."""
    if not st or not isinstance(st, str):
        return "channel"
    s = st.strip().lower()[:MAX_SOURCE_TYPE_LEN]
    if s not in _ALLOWED_SOURCE_TYPES:
        return "unknown"
    return s


def _safe_str(value: Any, max_len: int, default: str = "") -> str:
    if value is None:
        return default
    try:
        s = str(value).strip()
    except Exception:
        return default
    if not s:
        return default
    return s[:max_len]


async def _execute(sql: str, params: Any = None) -> Any:
    """
    🟢 NEW v1.1.0: مساعد تنفيذ يتوافق مع DB.execute أو DB.transaction.

    يستخدم DB.execute إن وُجد، وإلا يستخدم DB.transaction كـ fallback.
    """
    from database import DB

    execute_fn = getattr(DB, "execute", None)
    if callable(execute_fn):
        if params is None:
            return await execute_fn(sql)
        return await execute_fn(sql, params)

    # Fallback: عبر transaction context
    async with DB.transaction() as conn:
        if params is None:
            return await conn.execute(sql)
        return await conn.execute(sql, params)


# ═════════════════════════════════════════════════════════════════════
# إنشاء الجدول
# ═════════════════════════════════════════════════════════════════════

async def ensure_table() -> bool:
    """
    إنشاء الجدول إن لم يكن موجوداً (متوافق مع كل قواعد البيانات).
    آمن للاستدعاء المتكرر — يُخزَّن في _table_ensured بعد النجاح.
    """
    global _table_ensured

    if _table_ensured:
        return True

    db_type = _get_db_type()
    try:
        if db_type == "postgres":
            await _execute("""
                CREATE TABLE IF NOT EXISTS auto_blocked_sources (
                    source_id BIGINT PRIMARY KEY,
                    source_type VARCHAR(20) DEFAULT 'channel',
                    source_name VARCHAR(255) DEFAULT '',
                    first_seen TIMESTAMP DEFAULT NOW(),
                    last_seen TIMESTAMP DEFAULT NOW(),
                    hit_count INTEGER DEFAULT 1,
                    reason VARCHAR(100) DEFAULT 'auto_detected',
                    auto_added BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
        elif db_type == "mysql":
            await _execute("""
                CREATE TABLE IF NOT EXISTS auto_blocked_sources (
                    source_id BIGINT PRIMARY KEY,
                    source_type VARCHAR(20) DEFAULT 'channel',
                    source_name VARCHAR(255) DEFAULT '',
                    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                    hit_count INT DEFAULT 1,
                    reason VARCHAR(100) DEFAULT 'auto_detected',
                    auto_added TINYINT(1) DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)
        else:  # sqlite
            await _execute("""
                CREATE TABLE IF NOT EXISTS auto_blocked_sources (
                    source_id INTEGER PRIMARY KEY,
                    source_type TEXT DEFAULT 'channel',
                    source_name TEXT DEFAULT '',
                    first_seen TEXT,
                    last_seen TEXT,
                    hit_count INTEGER DEFAULT 1,
                    reason TEXT DEFAULT 'auto_detected',
                    auto_added INTEGER DEFAULT 1,
                    created_at TEXT
                )
            """)

        _table_ensured = True
        logger.info("✅ auto_blocked_sources جاهز (DB=%s)", db_type)
        return True
    except Exception as e:
        logger.warning("ensure_table(%s): %s", db_type, e)
        return False


# ═════════════════════════════════════════════════════════════════════
# فحص مصدر
# ═════════════════════════════════════════════════════════════════════

async def is_blocked(source_id: Optional[int]) -> bool:
    """هل المصدر في القائمة السوداء؟"""
    if source_id is None:
        return False
    try:
        db_type = _get_db_type()
        if db_type == "postgres":
            sql = ("SELECT 1 FROM auto_blocked_sources "
                   "WHERE source_id = $1 LIMIT 1")
        else:
            sql = ("SELECT 1 FROM auto_blocked_sources "
                   "WHERE source_id = ? LIMIT 1")

        from database import DB
        row = await DB.fetchval(sql, (source_id,))
        return row is not None
    except Exception as e:
        logger.debug("is_blocked(%s): %s", source_id, e)
        return False


# ═════════════════════════════════════════════════════════════════════
# جلب مصدر واحد
# ═════════════════════════════════════════════════════════════════════

async def get_source(source_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """
    🟢 NEW v1.1.0: جلب بيانات مصدر واحد.
    """
    if source_id is None:
        return None
    try:
        db_type = _get_db_type()
        if db_type == "postgres":
            sql = ("SELECT * FROM auto_blocked_sources "
                   "WHERE source_id = $1 LIMIT 1")
        else:
            sql = ("SELECT * FROM auto_blocked_sources "
                   "WHERE source_id = ? LIMIT 1")

        from database import DB
        row = await DB.fetchone(sql, (source_id,))
        if not row:
            return None
        try:
            return dict(row)
        except Exception:
            return None
    except Exception as e:
        logger.debug("get_source(%s): %s", source_id, e)
        return None


# ═════════════════════════════════════════════════════════════════════
# إضافة مصدر (upsert)
# ═════════════════════════════════════════════════════════════════════

async def add_source(
    source_id: Optional[int],
    source_type: str = "channel",
    source_name: str = "",
    reason: str = "auto_detected",
    auto_added: bool = True,
) -> bool:
    """
    إضافة مصدر للقائمة السوداء (upsert آمن).
    إذا كان موجوداً، يزيد hit_count ويحدّث last_seen.

    Args:
        auto_added: True للإضافة التلقائية، False للإضافة اليدوية.
    """
    if source_id is None:
        return False

    # ✅ تطبيع المدخلات
    source_type = _normalize_source_type(source_type)
    source_name = _safe_str(source_name, MAX_SOURCE_NAME_LEN, "")
    reason = _safe_str(reason, MAX_REASON_LEN, "auto_detected") or "auto_detected"

    # ✅ ضمان وجود الجدول
    if not _table_ensured:
        await ensure_table()

    db_type = _get_db_type()
    try:
        if db_type == "postgres":
            # ✅ v1.1.0: تمرير auto_added بشكل صريح
            sql = """
                INSERT INTO auto_blocked_sources
                    (source_id, source_type, source_name, reason,
                     auto_added, first_seen, last_seen, hit_count)
                VALUES ($1, $2, $3, $4, $5, NOW(), NOW(), 1)
                ON CONFLICT (source_id) DO UPDATE SET
                    hit_count = auto_blocked_sources.hit_count + 1,
                    last_seen = NOW(),
                    source_name = EXCLUDED.source_name,
                    reason = EXCLUDED.reason
            """
            await _execute(
                sql,
                (source_id, source_type, source_name, reason, auto_added),
            )

        elif db_type == "mysql":
            sql = """
                INSERT INTO auto_blocked_sources
                    (source_id, source_type, source_name, reason,
                     auto_added, first_seen, last_seen, hit_count)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW(), 1)
                ON DUPLICATE KEY UPDATE
                    hit_count = hit_count + 1,
                    last_seen = NOW(),
                    source_name = VALUES(source_name),
                    reason = VALUES(reason)
            """
            await _execute(
                sql,
                (source_id, source_type, source_name, reason,
                 1 if auto_added else 0),
            )

        else:  # sqlite
            # 🔴 FIX v1.1.0: استُبدل INSERT OR REPLACE بـ ON CONFLICT
            #    السبب: INSERT OR REPLACE يحذف ثم يعيد الإدخال
            #    مما يفقد created_at الأصلي
            sql = """
                INSERT INTO auto_blocked_sources
                    (source_id, source_type, source_name, reason,
                     auto_added, first_seen, last_seen, hit_count,
                     created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(source_id) DO UPDATE SET
                    hit_count = auto_blocked_sources.hit_count + 1,
                    last_seen = CURRENT_TIMESTAMP,
                    source_name = excluded.source_name,
                    reason = excluded.reason
            """
            await _execute(
                sql,
                (source_id, source_type, source_name, reason,
                 1 if auto_added else 0),
            )

        return True
    except Exception as e:
        logger.warning("add_source(%s): %s", source_id, e)
        return False


# ═════════════════════════════════════════════════════════════════════
# تحديث مصدر (بدون زيادة hit_count)
# ═════════════════════════════════════════════════════════════════════

async def update_source(
    source_id: int,
    source_name: Optional[str] = None,
    reason: Optional[str] = None,
) -> bool:
    """
    🟢 NEW v1.1.0: تحديث بيانات مصدر بدون زيادة hit_count.
    مفيد لتصحيح الأسماء من لوحة الإدارة.
    """
    if source_id is None:
        return False

    updates: List[str] = []
    params: List[Any] = []

    db_type = _get_db_type()
    ph = "$1" if db_type == "postgres" else "?"

    if source_name is not None:
        updates.append(f"source_name = {ph}")
        params.append(_safe_str(source_name, MAX_SOURCE_NAME_LEN, ""))
        if db_type == "postgres":
            ph = f"${len(params) + 1}"

    if reason is not None:
        updates.append(f"reason = {ph}")
        params.append(_safe_str(reason, MAX_REASON_LEN, "auto_detected"))
        if db_type == "postgres":
            ph = f"${len(params) + 1}"

    if not updates:
        return False

    if db_type == "postgres":
        sql = (f"UPDATE auto_blocked_sources SET {', '.join(updates)} "
               f"WHERE source_id = ${len(params) + 1}")
    else:
        sql = (f"UPDATE auto_blocked_sources SET {', '.join(updates)} "
               f"WHERE source_id = ?")

    params.append(source_id)

    try:
        await _execute(sql, tuple(params))
        return True
    except Exception as e:
        logger.warning("update_source(%s): %s", source_id, e)
        return False


# ═════════════════════════════════════════════════════════════════════
# عرض القائمة
# ═════════════════════════════════════════════════════════════════════

async def list_blocked(limit: int = 100) -> List[Dict[str, Any]]:
    """قائمة المصادر المحجوبة (مرتبة حسب hit_count تنازلياً)."""
    try:
        limit = max(1, min(int(limit), MAX_BULK_SIZE))
    except (TypeError, ValueError):
        limit = 100

    try:
        db_type = _get_db_type()
        if db_type == "postgres":
            sql = ("SELECT * FROM auto_blocked_sources "
                   "ORDER BY hit_count DESC, last_seen DESC LIMIT $1")
        else:
            sql = ("SELECT * FROM auto_blocked_sources "
                   "ORDER BY hit_count DESC, last_seen DESC LIMIT ?")

        from database import DB
        rows = await DB.fetchall(sql, (limit,))
        result: List[Dict[str, Any]] = []
        for r in (rows or []):
            try:
                result.append(dict(r))
            except Exception:
                continue
        return result
    except Exception as e:
        logger.debug("list_blocked: %s", e)
        return []


# ═════════════════════════════════════════════════════════════════════
# 🟢 NEW v1.1.0: أعلى N مصادر
# ═════════════════════════════════════════════════════════════════════

async def get_top_blocked(n: int = 10) -> List[Dict[str, Any]]:
    """
    🟢 NEW v1.1.0: أعلى N مصادر حسب hit_count.
    """
    try:
        n = max(1, min(int(n), 500))
    except (TypeError, ValueError):
        n = 10
    return await list_blocked(limit=n)


# ═════════════════════════════════════════════════════════════════════
# 🟢 NEW v1.1.0: بحث بالاسم
# ═════════════════════════════════════════════════════════════════════

async def search_by_name(
    query: str,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    🟢 NEW v1.1.0: بحث جزئي بـ source_name (ILIKE / LIKE).
    """
    if not query or not isinstance(query, str):
        return []

    q = query.strip()
    if not q:
        return []

    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 50

    db_type = _get_db_type()
    try:
        from database import DB

        if db_type == "postgres":
            sql = ("SELECT * FROM auto_blocked_sources "
                   "WHERE source_name ILIKE $1 "
                   "ORDER BY hit_count DESC LIMIT $2")
        elif db_type == "mysql":
            sql = ("SELECT * FROM auto_blocked_sources "
                   "WHERE source_name LIKE %s "
                   "ORDER BY hit_count DESC LIMIT %s")
        else:
            sql = ("SELECT * FROM auto_blocked_sources "
                   "WHERE source_name LIKE ? "
                   "ORDER BY hit_count DESC LIMIT ?")

        rows = await DB.fetchall(sql, (f"%{q}%", limit))
        result: List[Dict[str, Any]] = []
        for r in (rows or []):
            try:
                result.append(dict(r))
            except Exception:
                continue
        return result
    except Exception as e:
        logger.debug("search_by_name(%s): %s", q, e)
        return []


# ═════════════════════════════════════════════════════════════════════
# إزالة مصدر (unblock)
# ═════════════════════════════════════════════════════════════════════

async def remove_source(source_id: int) -> bool:
    """إزالة مصدر من القائمة السوداء (unblock)."""
    if source_id is None:
        return False
    try:
        db_type = _get_db_type()
        if db_type == "postgres":
            sql = "DELETE FROM auto_blocked_sources WHERE source_id = $1"
        else:
            sql = "DELETE FROM auto_blocked_sources WHERE source_id = ?"

        await _execute(sql, (source_id,))
        return True
    except Exception as e:
        logger.warning("remove_source(%s): %s", source_id, e)
        return False


# ═════════════════════════════════════════════════════════════════════
# 🟢 NEW v1.1.0: إضافة دفعة
# ═════════════════════════════════════════════════════════════════════

async def bulk_add(sources: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """
    🟢 NEW v1.1.0: إضافة عدة مصادر دفعة واحدة.

    Returns:
        {"total": N, "success": M, "failed": K}
    """
    if not sources:
        return {"total": 0, "success": 0, "failed": 0}

    total = 0
    success = 0
    failed = 0

    for src in sources:
        if total >= MAX_BULK_SIZE:
            break
        total += 1
        try:
            ok = await add_source(
                source_id=src.get("source_id"),
                source_type=src.get("source_type", "channel"),
                source_name=src.get("source_name", ""),
                reason=src.get("reason", "auto_detected"),
                auto_added=bool(src.get("auto_added", True)),
            )
            if ok:
                success += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.debug("bulk_add item failed: %s", e)

    return {"total": total, "success": success, "failed": failed}


# ═════════════════════════════════════════════════════════════════════
# 🟢 NEW v1.1.0: تصفير hit_count
# ═════════════════════════════════════════════════════════════════════

async def reset_hits(source_id: int) -> bool:
    """
    🟢 NEW v1.1.0: تصفير hit_count لمصدر (بعد مراجعة إدارية).
    """
    if source_id is None:
        return False
    try:
        db_type = _get_db_type()
        if db_type == "postgres":
            sql = ("UPDATE auto_blocked_sources SET hit_count = 0 "
                   "WHERE source_id = $1")
        else:
            sql = ("UPDATE auto_blocked_sources SET hit_count = 0 "
                   "WHERE source_id = ?")

        await _execute(sql, (source_id,))
        return True
    except Exception as e:
        logger.warning("reset_hits(%s): %s", source_id, e)
        return False


# ═════════════════════════════════════════════════════════════════════
# تنظيف المصادر القديمة
# ═════════════════════════════════════════════════════════════════════

async def cleanup_old_entries(days: int = DEFAULT_CLEANUP_DAYS) -> int:
    """
    حذف المصادر التي لم تُشاهَد منذ X يوم.
    الافتراضي: 90 يوم.

    🔴 FIX v1.1.0: الاستخدام الصحيح لـ _parse_delete_count
    لإرجاع العدد الحقيقي بدلاً من 0 دائماً.
    """
    try:
        days = max(1, int(days))
    except (TypeError, ValueError):
        days = DEFAULT_CLEANUP_DAYS

    db_type = _get_db_type()
    try:
        if db_type == "postgres":
            sql = ("DELETE FROM auto_blocked_sources "
                   "WHERE last_seen < NOW() - INTERVAL '1 day' * $1")
            result = await _execute(sql, (days,))

        elif db_type == "mysql":
            # ✅ v1.1.0: استخدام DATE_SUB + UTC_TIMESTAMP للتوحيد
            sql = ("DELETE FROM auto_blocked_sources "
                   "WHERE last_seen < DATE_SUB(UTC_TIMESTAMP(), "
                   "INTERVAL %s DAY)")
            result = await _execute(sql, (days,))

        else:  # sqlite
            sql = ("DELETE FROM auto_blocked_sources "
                   "WHERE julianday('now') - julianday(last_seen) > ?")
            result = await _execute(sql, (days,))

        deleted = _parse_delete_count(result)
        if deleted > 0:
            logger.info(
                "🧹 auto_blocked_sources: حُذف %d صف (>%d يوم)",
                deleted, days,
            )
        return deleted

    except Exception as e:
        logger.warning("cleanup_old_entries(%s): %s", days, e)
        return 0


# ═════════════════════════════════════════════════════════════════════
# إحصائيات
# ═════════════════════════════════════════════════════════════════════

async def count_blocked() -> int:
    """
    🟢 NEW v1.1.0: عدد المصادر المحجوبة إجمالاً.
    """
    try:
        from database import DB
        db_type = _get_db_type()
        if db_type == "postgres":
            sql = "SELECT COUNT(*)::int FROM auto_blocked_sources"
        else:
            sql = "SELECT COUNT(*) FROM auto_blocked_sources"
        val = await DB.fetchval(sql, default=0)
        try:
            return int(val or 0)
        except (TypeError, ValueError):
            return 0
    except Exception as e:
        logger.debug("count_blocked: %s", e)
        return 0


async def get_stats() -> Dict[str, int]:
    """إحصائيات سريعة للقائمة السوداء."""
    try:
        from database import DB
        db_type = _get_db_type()

        if db_type == "postgres":
            sql = ("SELECT COUNT(*)::int AS total, "
                   "COALESCE(SUM(hit_count), 0)::int AS hits "
                   "FROM auto_blocked_sources")
        elif db_type == "mysql":
            sql = ("SELECT COUNT(*) AS total, "
                   "COALESCE(SUM(hit_count), 0) AS hits "
                   "FROM auto_blocked_sources")
        else:
            sql = ("SELECT COUNT(*) AS total, "
                   "COALESCE(SUM(hit_count), 0) AS hits "
                   "FROM auto_blocked_sources")

        row = await DB.fetchone(sql)
        if row:
            try:
                d = dict(row)
                return {
                    "total": int(d.get("total", 0) or 0),
                    "hits": int(d.get("hits", 0) or 0),
                }
            except Exception:
                pass
        return {"total": 0, "hits": 0}
    except Exception as e:
        logger.debug("get_stats: %s", e)
        return {"total": 0, "hits": 0}


# ═════════════════════════════════════════════════════════════════════
# Exports
# ═════════════════════════════════════════════════════════════════════

__all__ = [
    # Core
    "ensure_table",
    "is_blocked",
    "add_source",
    "list_blocked",
    "remove_source",
    "cleanup_old_entries",
    "get_stats",
    # 🆕 v1.1.0
    "get_source",
    "update_source",
    "count_blocked",
    "get_top_blocked",
    "search_by_name",
    "bulk_add",
    "reset_hits",
    # Constants
    "DEFAULT_CLEANUP_DAYS",
    "MAX_BULK_SIZE",
    # Internal helpers (للاختبار)
    "_get_db_type",
    "_parse_delete_count",
    "_normalize_source_type",
    "_execute",
]