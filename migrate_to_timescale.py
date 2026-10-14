#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_to_timescale.py
نقل كل البيانات من Aiven (DATABASE_URL) إلى Timescale (TIMESCALE_URL)
- ينسخ: القنوات، المجموعات، المستخدمين، المنشورات، الاشتراكات، كل شيء
- لا يحذف شيئًا من Aiven
- يمكن إعادة تشغيله بأمان (idempotent)
"""

import os
import sys
import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import asyncpg
except ImportError:
    print("❌ pip install asyncpg python-dotenv")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("migrate")

SOURCE = os.getenv("DATABASE_URL", "").strip().strip('"')
TARGET = os.getenv("TIMESCALE_URL", "").strip().strip('"')

BATCH = 500


def mask(url):
    try:
        p = urlparse(url)
        return url.replace(p.password, "***") if p.password else url
    except Exception:
        return url


async def get_tables(conn):
    rows = await conn.fetch("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = current_schema()
          AND tablename NOT LIKE '\\_%'
        ORDER BY tablename
    """)
    return [r["tablename"] for r in rows]


async def get_columns(conn, table):
    rows = await conn.fetch("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = $1
        ORDER BY ordinal_position
    """, table)
    return [r["column_name"] for r in rows]


async def get_pk(conn, table):
    rows = await conn.fetch("""
        SELECT a.attname FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid
                            AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = to_regclass($1) AND i.indisprimary
    """, table)
    return [r["attname"] for r in rows]


async def create_table_on_target(src, tgt, table):
    """ينشئ نفس بنية الجدول في Timescale"""
    row = await src.fetchval("""
        SELECT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = current_schema() AND tablename = $1)
    """, table)
    if not row:
        return

    exists = await tgt.fetchval("""
        SELECT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = current_schema() AND tablename = $1)
    """, table)
    if exists:
        return

    # ننشئ الجدول عبر نسخ DDL مبسط
    cols = await src.fetch("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = $1
        ORDER BY ordinal_position
    """, table)

    defs = []
    for c in cols:
        name = c["column_name"]
        dtype = c["data_type"]
        # تخطي SERIAL — نستخدم BIGINT يدويًا
        if dtype == "integer":
            dtype = "integer"
        elif dtype == "bigint":
            dtype = "bigint"
        elif dtype == "character varying":
            dtype = "text"
        elif dtype == "timestamp without time zone":
            dtype = "timestamp"
        elif dtype == "timestamp with time zone":
            dtype = "timestamptz"
        elif dtype == "USER-DEFINED":
            dtype = "text"
        d = f'"{name}" {dtype}'
        if c["is_nullable"] == "NO":
            d += " NOT NULL"
        defs.append(d)

    ddl = f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(defs)})'
    await tgt.execute(ddl)
    log.info(f"   🔨 جدول {table} أُنشئ في Timescale")


async def copy_table(src, tgt, table):
    try:
        # 1) إنشاء الجدول في الهدف إن لم يكن موجودًا
        await create_table_on_target(src, tgt, table)

        # 2) الأعمدة والمفتاح الأساسي
        cols = await get_columns(src, table)
        if not cols:
            return 0

        pk = await get_pk(src, table)

        # 3) قراءة كل الصفوف من المصدر
        rows = await src.fetch(f'SELECT * FROM "{table}"')
        if not rows:
            log.info(f"   ⏭️ {table}: فارغ")
            return 0

        cols_csv = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))

        if pk:
            conflict = ", ".join(f'"{c}"' for c in pk)
            set_clause = ", ".join(
                f'"{c}" = EXCLUDED."{c}"' for c in cols if c not in pk
            ) or f'"{pk[0]}" = EXCLUDED."{pk[0]}"'
            sql = (
                f'INSERT INTO "{table}" ({cols_csv}) '
                f"VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict}) DO UPDATE SET {set_clause}"
            )
        else:
            sql = (
                f'INSERT INTO "{table}" ({cols_csv}) '
                f"VALUES ({placeholders}) "
                f"ON CONFLICT DO NOTHING"
            )

        # 4) إدراج على دفعات
        total = 0
        async with tgt.transaction():
            for r in rows:
                values = []
                for c in cols:
                    v = r[c]
                    if isinstance(v, datetime) and v.tzinfo is not None:
                        v = v.astimezone(timezone.utc).replace(tzinfo=None)
                    values.append(v)
                try:
                    await tgt.execute(sql, *values)
                    total += 1
                except Exception as ie:
                    log.debug(f"⚠️ {table}: صف فشل — {ie}")

        log.info(f"   ✅ {table}: {total} صف")
        return total

    except Exception as e:
        log.warning(f"   ⚠️ {table}: {e}")
        return 0


async def migrate():
    if not SOURCE or not TARGET:
        log.error("❌ DATABASE_URL أو TIMESCALE_URL غير موجود")
        return

    log.info("🚀 بدء النقل الكامل...")
    log.info(f"   المصدر  : {mask(SOURCE)}")
    log.info(f"   الهدف   : {mask(TARGET)}")
    log.info("")

    try:
        src = await asyncpg.connect(SOURCE, timeout=20)
        tgt = await asyncpg.connect(TARGET, timeout=20)
    except Exception as e:
        log.error(f"❌ فشل الاتصال: {e}")
        return

    try:
        tables = await get_tables(src)
        log.info(f"📋 عدد الجداول: {len(tables)}")
        log.info("")

        total = 0
        for i, t in enumerate(tables, 1):
            log.info(f"[{i}/{len(tables)}] {t}")
            n = await copy_table(src, tgt, t)
            total += n

        log.info("")
        log.info(f"🎉 انتهى النقل: {total} صف إجمالًا")
    finally:
        await src.close()
        await tgt.close()


if __name__ == "__main__":
    try:
        asyncio.run(migrate())
    except KeyboardInterrupt:
        log.info("\n👋 توقف يدوي")