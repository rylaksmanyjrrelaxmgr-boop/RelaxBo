#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_auto_block.py - v1.0.0
=============================================================================
🗄️ جدول تلقائي لحجب المصادر المشبوهة (Post Bot / Spam channels)
=============================================================================
الميزات:
    ✅ إنشاء الجدول تلقائياً (PostgreSQL / MySQL / SQLite)
    ✅ إضافة مصدر (upsert آمن — idempotent)
    ✅ فحص مصدر (is_blocked)
    ✅ عرض القائمة (list_blocked)
    ✅ إزالة مصدر (remove_source)
    ✅ تنظيف المصادر القديمة (cleanup_old_entries)

التكامل:
    - يُستورد تلقائياً من handlers_message.py
    - يُنشئ الجدول عند أول رسالة (_lazy_init_columns)
    - يعمل بدون أي تعديل على main.py

الاستخدام:
    from database_auto_block import (
        ensure_table, is_blocked, add_source,
        list_blocked, remove_source, cleanup_old_entries,
    )
=============================================================================
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any

from database import DB


logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════
# إنشاء الجدول
# ═════════════════════════════════════════════════════════════════════

async def ensure_table() -> bool:
    """
    إنشاء الجدول إن لم يكن موجوداً (متوافق مع كل قواعد البيانات).
    آمن للاستدعاء المتكرر.
    """
    db_type = getattr(DB, "DB_TYPE", "sqlite")
    try:
        if db_type == "postgres":
            await DB.execute("""
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
            await DB.execute("""
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
        else:
            await DB.execute("""
                CREATE TABLE IF NOT EXISTS auto_blocked_sources (
                    source_id INTEGER PRIMARY KEY,
                    source_type TEXT DEFAULT 'channel',
                    source_name TEXT DEFAULT '',
                    first_seen TIMESTAMP,
                    last_seen TIMESTAMP,
                    hit_count INTEGER DEFAULT 1,
                    reason TEXT DEFAULT 'auto_detected',
                    auto_added INTEGER DEFAULT 1,
                    created_at TIMESTAMP
                )
            """)
        logger.info("✅ auto_blocked_sources جاهز (DB=%s)", db_type)
        return True
    except Exception as e:
        logger.debug("ensure_table: %s", e)
        return False


# ═════════════════════════════════════════════════════════════════════
# فحص مصدر
# ═════════════════════════════════════════════════════════════════════

async def is_blocked(source_id: Optional[int]) -> bool:
    """هل المصدر في القائمة السوداء؟"""
    if source_id is None:
        return False
    try:
        db_type = getattr(DB, "DB_TYPE", "sqlite")
        if db_type == "postgres":
            sql = ("SELECT 1 FROM auto_blocked_sources "
                   "WHERE source_id = $1 LIMIT 1")
        else:
            sql = ("SELECT 1 FROM auto_blocked_sources "
                   "WHERE source_id = ? LIMIT 1")
        row = await DB.fetchval(sql, (source_id,))
        return row is not None
    except Exception as e:
        logger.debug("is_blocked(%s): %s", source_id, e)
        return False


# ═════════════════════════════════════════════════════════════════════
# إضافة مصدر (upsert)
# ═════════════════════════════════════════════════════════════════════

async def add_source(
    source_id: Optional[int],
    source_type: str = "channel",
    source_name: str = "",
    reason: str = "auto_detected",
) -> bool:
    """
    إضافة مصدر للقائمة السوداء (upsert آمن).
    إذا كان موجوداً، يزيد hit_count ويحدّث last_seen.
    """
    if source_id is None:
        return False
    try:
        db_type = getattr(DB, "DB_TYPE", "sqlite")

        if db_type == "postgres":
            sql = """
                INSERT INTO auto_blocked_sources
                    (source_id, source_type, source_name, reason,
                     first_seen, last_seen, hit_count)
                VALUES ($1, $2, $3, $4, NOW(), NOW(), 1)
                ON CONFLICT (source_id) DO UPDATE SET
                    hit_count = auto_blocked_sources.hit_count + 1,
                    last_seen = NOW(),
                    source_name = EXCLUDED.source_name,
                    reason = EXCLUDED.reason
            """
            await DB.execute(
                sql, (source_id, source_type, source_name, reason)
            )

        elif db_type == "mysql":
            sql = """
                INSERT INTO auto_blocked_sources
                    (source_id, source_type, source_name, reason,
                     first_seen, last_seen, hit_count)
                VALUES (%s, %s, %s, %s, NOW(), NOW(), 1)
                ON DUPLICATE KEY UPDATE
                    hit_count = hit_count + 1,
                    last_seen = NOW(),
                    source_name = VALUES(source_name),
                    reason = VALUES(reason)
            """
            await DB.execute(
                sql, (source_id, source_type, source_name, reason)
            )

        else:
            # SQLite
            sql = """
                INSERT OR REPLACE INTO auto_blocked_sources
                    (source_id, source_type, source_name, reason,
                     first_seen, last_seen, hit_count)
                VALUES (?, ?, ?, ?,
                    COALESCE(
                        (SELECT first_seen FROM auto_blocked_sources
                         WHERE source_id = ?),
                        CURRENT_TIMESTAMP
                    ),
                    CURRENT_TIMESTAMP,
                    COALESCE(
                        (SELECT hit_count FROM auto_blocked_sources
                         WHERE source_id = ?),
                        0
                    ) + 1
                )
            """
            await DB.execute(
                sql,
                (source_id, source_type, source_name, reason,
                 source_id, source_id),
            )

        return True
    except Exception as e:
        logger.debug("add_source(%s): %s", source_id, e)
        return False


# ═════════════════════════════════════════════════════════════════════
# عرض القائمة
# ═════════════════════════════════════════════════════════════════════

async def list_blocked(limit: int = 100) -> List[Dict[str, Any]]:
    """قائمة المصادر المحجوبة (مرتبة حسب hit_count تنازلياً)."""
    try:
        db_type = getattr(DB, "DB_TYPE", "sqlite")
        if db_type == "postgres":
            sql = ("SELECT * FROM auto_blocked_sources "
                   "ORDER BY hit_count DESC, last_seen DESC LIMIT $1")
        else:
            sql = ("SELECT * FROM auto_blocked_sources "
                   "ORDER BY hit_count DESC, last_seen DESC LIMIT ?")
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
# إزالة مصدر (unblock)
# ═════════════════════════════════════════════════════════════════════

async def remove_source(source_id: int) -> bool:
    """إزالة مصدر من القائمة السوداء (unblock)."""
    if source_id is None:
        return False
    try:
        db_type = getattr(DB, "DB_TYPE", "sqlite")
        if db_type == "postgres":
            sql = "DELETE FROM auto_blocked_sources WHERE source_id = $1"
        else:
            sql = "DELETE FROM auto_blocked_sources WHERE source_id = ?"
        await DB.execute(sql, (source_id,))
        return True
    except Exception as e:
        logger.debug("remove_source(%s): %s", source_id, e)
        return False


# ═════════════════════════════════════════════════════════════════════
# تنظيف المصادر القديمة
# ═════════════════════════════════════════════════════════════════════

async def cleanup_old_entries(days: int = 90) -> int:
    """
    حذف المصادر التي لم تُشاهَد منذ X يوم.
    الافتراضي: 90 يوم.
    """
    try:
        db_type = getattr(DB, "DB_TYPE", "sqlite")
        if db_type == "postgres":
            sql = ("DELETE FROM auto_blocked_sources "
                   "WHERE last_seen < NOW() - INTERVAL '1 day' * $1")
            result = await DB.execute(sql, (days,))
        elif db_type == "mysql":
            sql = ("DELETE FROM auto_blocked_sources "
                   "WHERE last_seen < UTC_TIMESTAMP() - "
                   "INTERVAL %s DAY")
            result = await DB.execute(sql, (days,))
        else:
            sql = ("DELETE FROM auto_blocked_sources "
                   "WHERE julianday('now') - julianday(last_seen) > ?")
            result = await DB.execute(sql, (days,))
        return result if isinstance(result, int) else 0
    except Exception as e:
        logger.debug("cleanup_old_entries: %s", e)
        return 0


# ═════════════════════════════════════════════════════════════════════
# إحصائيات
# ═════════════════════════════════════════════════════════════════════

async def get_stats() -> Dict[str, int]:
    """إحصائيات سريعة للقائمة السوداء."""
    try:
        db_type = getattr(DB, "DB_TYPE", "sqlite")
        if db_type == "postgres":
            sql = ("SELECT COUNT(*) as total, "
                   "COALESCE(SUM(hit_count), 0) as hits "
                   "FROM auto_blocked_sources")
        else:
            sql = ("SELECT COUNT(*) as total, "
                   "COALESCE(SUM(hit_count), 0) as hits "
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
    "ensure_table",
    "is_blocked",
    "add_source",
    "list_blocked",
    "remove_source",
    "cleanup_old_entries",
    "get_stats",
]