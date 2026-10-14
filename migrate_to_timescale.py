#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_to_timescale.py — v2 (BATCH-COPY)
- يستخدم executemany بدل execute فردي
- يتخطى الجداول الكبيرة غير الضرورية (اختياري)
- يعرض تقدمًا كل 5000 صف
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
# جداول ثقيلة يمكن تخطيها (اختياري)
SKIP_TABLES = set(os.getenv(
    "MIGRATE_SKIP", ""
).strip().split(",")) - {""}


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


async def copy_table(src, tgt, table):
    try:
        if table in SKIP_TABLES:
            log.info(f"   ⏭️ {table}: متخطى (SKIP_TABLES)")
            return 0

        # هل الجدول موجود في الهدف؟
        exists = await tgt.fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM pg_tables
                WHERE schemaname = current_schema() AND tablename = $1)
        """, table)
        if not exists:
            log.warning(f"   ⚠️ {table}: غير موجود في Timescale — تخطي")
            return 0

        cols = await get_columns(src, table)
        if not cols:
            return 0

        # عدد الصفوف
        total_rows = await src.fetchval(f'SELECT COUNT(*) FROM "{table}"')
        if not total_rows:
            log.info(f"   ⏭️ {table}: فارغ")
            return 0

        pk = await get_pk(src, table)

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
                f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            )

        # قراءة على دفعات
        inserted = 0
        offset = 0
        while offset < total_rows:
            rows = await src.fetch(
                f'SELECT * FROM "{table}" '
                f"ORDER BY 1 LIMIT {BATCH} OFFSET {offset}"
            )
            if not rows:
                break

            # تحويل القيم
            params_list = []
            for r in rows:
                vals = []
                for c in cols:
                    v = r[c]
                    if isinstance(v, datetime) and v.tzinfo is not None:
                        v = v.astimezone(timezone.utc).replace(tzinfo=None)
                    vals.append(v)
                params_list.append(tuple(vals))

            # إدراج جماعي
            try:
                async with tgt.transaction():
                    await tgt.executemany(sql, params_list)
                    inserted += len(params_list)
            except Exception as be:
                # fallback فردي
                for p in params_list:
                    try:
                        await tgt.execute(sql, *p)
                        inserted += 1
                    except Exception as ie:
                        log.debug(f"⚠️ {table}: صف فشل — {ie}")

            offset += BATCH
            if offset % (BATCH * 10) == 0 or offset >= total_rows:
                log.info(f"      ↳ {min(offset, total_rows)}/{total_rows} صف")

        log.info(f"   ✅ {table}: {inserted} صف")
        return inserted

    except Exception as e:
        log.warning(f"   ⚠️ {table}: {e}")
        return 0


async def migrate():
    if not SOURCE or not TARGET:
        log.error("❌ DATABASE_URL أو TIMESCALE_URL غير موجود")
        return

    log.info("🚀 بدء النقل الكامل (v2)...")
    log.info(f"   المصدر: {mask(SOURCE)}")
    log.info(f"   الهدف : {mask(TARGET)}")
    if SKIP_TABLES:
        log.info(f"   متخطى: {sorted(SKIP_TABLES)}")
    log.info("")

    try:
        src = await asyncpg.connect(SOURCE, timeout=20)
        tgt = await asyncpg.connect(TARGET, timeout=20)
    except Exception as e:
        log.error(f"❌ فشل الاتصال: {e}")
        return

    try:
        # مهم: إخبار Timescale بعدم احتساب FK أثناء النقل
        try:
            await tgt.execute("SET session_replication_role = replica")
        except Exception:
            pass

        tables = await get_tables(src)
        log.info(f"📋 عدد الجداول: {len(tables)}\n")

        total = 0
        for i, t in enumerate(tables, 1):
            log.info(f"[{i}/{len(tables)}] {t}")
            n = await copy_table(src, tgt, t)
            total += n

        log.info("")
        log.info(f"🎉 انتهى النقل: {total} صف إجمالًا")

        # إعادة تفعيل FK
        try:
            await tgt.execute("SET session_replication_role = DEFAULT")
        except Exception:
            pass
    finally:
        await src.close()
        await tgt.close()


if __name__ == "__main__":
    try:
        asyncio.run(migrate())
    except KeyboardInterrupt:
        log.info("\n👋 توقف يدوي")