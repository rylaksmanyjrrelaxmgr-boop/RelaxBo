#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_dual_db.py — إعداد تلقائي للتزامن بين Aiven و Timescale
================================================================
🎯 الهدف:
   إبقاء Timescale نسخة حيّة من Aiven تلقائيًا WITHOUT تعديل database.py.

🧠 الآلية:
   1) يُحاول تفعيل PostgreSQL Logical Replication.
   2) إذا فشل، يتحوّل تلقائيًا إلى نسخ دوري.

🚀 التشغيل:
   python setup_dual_db.py setup      # إعداد مرة واحدة
   python setup_dual_db.py status     # الحالة
   python setup_dual_db.py sync       # نسخة يدوية
   python setup_dual_db.py worker     # العامل الدوري (لا ينتهي)
   python setup_dual_db.py teardown   # حذف كل شيء

⚠️ على Render: استخدم "Background Worker" لا "Web Service".
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
    print("❌ يتطلب: pip install asyncpg python-dotenv")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("dual_db")

# ═══════════════════════════════════════════════════════════════════
# الإعدادات
# ═══════════════════════════════════════════════════════════════════
PRIMARY_URL   = os.getenv("DATABASE_URL", "").strip().strip('"')
SECONDARY_URL = os.getenv("TIMESCALE_URL", "").strip().strip('"')

PUBLICATION_NAME  = "relax_pub"
SUBSCRIPTION_NAME = "relax_sub"
SYNC_STATE_TABLE  = "_dual_sync_state"

SYNC_INTERVAL_SEC = int(os.getenv("DUAL_SYNC_INTERVAL_SEC", "300"))
SYNC_BATCH_SIZE   = int(os.getenv("DUAL_SYNC_BATCH", "500"))


# ═══════════════════════════════════════════════════════════════════
# أدوات
# ═══════════════════════════════════════════════════════════════════
def _mask(url: str) -> str:
    try:
        p = urlparse(url)
        if p.password:
            return url.replace(p.password, "***")
    except Exception:
        pass
    return url


def _to_naive_utc(dt) -> datetime:
    if dt is None:
        return datetime(1970, 1, 1)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _to_aware_utc(dt) -> datetime:
    if dt is None:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def _fetch_table_list(conn) -> list:
    rows = await conn.fetch("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = current_schema()
          AND tablename NOT LIKE '\\_%'
        ORDER BY tablename
    """)
    return [r["tablename"] for r in rows]


async def _table_columns(conn, table: str) -> list:
    rows = await conn.fetch("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = $1
        ORDER BY ordinal_position
    """, table)
    return [r["column_name"] for r in rows]


async def _column_data_type(conn, table: str, col: str) -> str:
    row = await conn.fetchrow("""
        SELECT data_type FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = $1 AND column_name = $2
    """, table, col)
    return (row["data_type"] or "") if row else ""


async def _table_has_pk(conn, table: str) -> bool:
    row = await conn.fetchval("""
        SELECT EXISTS (
            SELECT 1 FROM pg_index i
            JOIN pg_class c ON c.oid = i.indrelid
            WHERE c.relname = $1 AND i.indisprimary
        )
    """, table)
    return bool(row)


async def _pk_columns(conn, table: str) -> list:
    rows = await conn.fetch("""
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid
                            AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = to_regclass($1)
          AND i.indisprimary
    """, table)
    return [r["attname"] for r in rows]


# ═══════════════════════════════════════════════════════════════════
# 1) Logical Replication
# ═══════════════════════════════════════════════════════════════════
async def try_logical_replication() -> bool:
    logger.info("🔍 [1/4] التحقق من إمكانية Logical Replication...")

    try:
        pri_conn = await asyncpg.connect(PRIMARY_URL, timeout=15)
    except Exception as e:
        logger.error(f"❌ فشل الاتصال بـ Aiven: {e}")
        return False

    try:
        wal_level = await pri_conn.fetchval("SHOW wal_level")
        logger.info(f"   wal_level = {wal_level}")

        if wal_level != "logical":
            logger.warning(
                "⚠️ Aiven wal_level ليس 'logical'. "
                "فعّله من Aiven Console → Advanced Configuration."
            )
            return False

        try:
            await pri_conn.execute(
                f"DROP PUBLICATION IF EXISTS {PUBLICATION_NAME}")
            await pri_conn.execute(
                f"CREATE PUBLICATION {PUBLICATION_NAME} FOR ALL TABLES")
            logger.info(f"✅ [2/4] أُنشئ Publication: {PUBLICATION_NAME}")
        except Exception as e:
            logger.warning(
                f"⚠️ فشل CREATE PUBLICATION: {e}\n"
                f"   خطة Aiven لا تسمح. سننتقل للنسخ الدوري.")
            return False
    finally:
        await pri_conn.close()

    try:
        sec_conn = await asyncpg.connect(SECONDARY_URL, timeout=15)
    except Exception as e:
        logger.error(f"❌ فشل الاتصال بـ Timescale: {e}")
        return False

    try:
        try:
            await sec_conn.execute(
                f"ALTER SUBSCRIPTION {SUBSCRIPTION_NAME} DISABLE")
            await sec_conn.execute(
                f"ALTER SUBSCRIPTION {SUBSCRIPTION_NAME} "
                f"SET (slot_name = NONE)")
            await sec_conn.execute(
                f"DROP SUBSCRIPTION IF EXISTS {SUBSCRIPTION_NAME}")
        except Exception:
            pass

        primary_clean = PRIMARY_URL.split("?")[0]

        await sec_conn.execute(f"""
            CREATE SUBSCRIPTION {SUBSCRIPTION_NAME}
            CONNECTION '{primary_clean}'
            PUBLICATION {PUBLICATION_NAME}
            WITH (copy_data = true, create_slot = true, enabled = true)
        """)
        logger.info(
            f"✅ [3/4] أُنشئ Subscription: {SUBSCRIPTION_NAME}")
        logger.info("✅ [4/4] Logical Replication يعمل لحظيًا 🎉")
        return True
    except Exception as e:
        logger.warning(
            f"⚠️ فشل CREATE SUBSCRIPTION: {e}\n"
            f"   سننتقل للنسخ الدوري.")
        return False
    finally:
        await sec_conn.close()


# ═══════════════════════════════════════════════════════════════════
# 2) Fallback: نسخ دوري
# ═══════════════════════════════════════════════════════════════════
async def _ensure_sync_state_table(sec_conn):
    await sec_conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {SYNC_STATE_TABLE} (
            table_name TEXT PRIMARY KEY,
            last_sync TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            rows_synced BIGINT NOT NULL DEFAULT 0
        )
    """)


async def _get_last_sync(sec_conn, table: str) -> datetime:
    row = await sec_conn.fetchrow(
        f"SELECT last_sync FROM {SYNC_STATE_TABLE} "
        f"WHERE table_name = $1", table)
    if row and row["last_sync"]:
        # نعيدها aware دائمًا، وسنحوّلها حسب نوع العمود
        return _to_aware_utc(row["last_sync"])
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


async def _set_last_sync(sec_conn, table: str, rows: int):
    await sec_conn.execute(f"""
        INSERT INTO {SYNC_STATE_TABLE} (table_name, last_sync, rows_synced)
        VALUES ($1, NOW(), $2)
        ON CONFLICT (table_name) DO UPDATE SET
            last_sync = NOW(),
            rows_synced = {SYNC_STATE_TABLE}.rows_synced
                        + EXCLUDED.rows_synced
    """, table, rows)


async def _table_timestamp_col(conn, table: str) -> str:
    cols = await _table_columns(conn, table)
    if "updated_at" in cols:
        return "updated_at"
    if "created_at" in cols:
        return "created_at"
    return ""


async def sync_table(pri_conn, sec_conn, table: str, full: bool = False):
    """
    ينسخ جدولًا واحدًا من Aiven إلى Timescale.
    يعيد عدد الصفوف المُدرَجة/المُحدَّثة.
    """
    try:
        if not await _table_has_pk(pri_conn, table):
            logger.debug(f"⏭️ {table}: بدون PK — تخطي")
            return 0

        cols = await _table_columns(pri_conn, table)
        if not cols:
            return 0

        ts_col = await _table_timestamp_col(pri_conn, table)

        if not ts_col or full:
            rows = await pri_conn.fetch(
                f"SELECT * FROM {table} LIMIT {SYNC_BATCH_SIZE}")
        else:
            # نحدّد نوع العمود: timestamp بدون منطقة زمنية
            # أو timestamptz معها
            col_type = await _column_data_type(
                pri_conn, table, ts_col)
            is_aware_col = "with time zone" in (col_type or "").lower()

            since = await _get_last_sync(sec_conn, table)
            # نحوّل القيمة بحسب نوع العمود لتفادي خطأ asyncpg
            if is_aware_col:
                since_param = _to_aware_utc(since)
            else:
                since_param = _to_naive_utc(since)

            rows = await pri_conn.fetch(
                f"SELECT * FROM {table} "
                f"WHERE {ts_col} > $1 "
                f"ORDER BY {ts_col} ASC "
                f"LIMIT {SYNC_BATCH_SIZE}",
                since_param)

        if not rows:
            return 0

        cols_csv = ", ".join(cols)
        placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
        pk_cols = await _pk_columns(pri_conn, table)

        if pk_cols:
            conflict_cols = ", ".join(pk_cols)
            set_clause = ", ".join(
                f"{c} = EXCLUDED.{c}" for c in cols
                if c not in pk_cols) or f"{pk_cols[0]} = EXCLUDED.{pk_cols[0]}"
            sql = (
                f"INSERT INTO {table} ({cols_csv}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT ({conflict_cols}) "
                f"DO UPDATE SET {set_clause}"
            )
        else:
            sql = (
                f"INSERT INTO {table} ({cols_csv}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT DO NOTHING"
            )

        # نحوّل قيم datetime لكل عمود بحسب نوعه في القاعدة الهدف
        # (مبسّط: نحوّل aware → naive إن كان العمود بدون منطقة زمنية)
        inserted = 0
        async with sec_conn.transaction():
            for r in rows:
                values = []
                for c in cols:
                    v = r[c]
                    if isinstance(v, datetime) and v.tzinfo is not None:
                        v = v.astimezone(timezone.utc).replace(
                            tzinfo=None)
                    values.append(v)
                try:
                    await sec_conn.execute(sql, *values)
                    inserted += 1
                except Exception as ie:
                    logger.debug(f"⚠️ {table}: صف فشل — {ie}")
                    continue

        await _set_last_sync(sec_conn, table, inserted)
        if inserted:
            logger.info(f"   ✅ {table}: +{inserted} صف")
        return inserted

    except Exception as e:
        logger.warning(f"   ⚠️ {table}: {e}")
        return 0


async def do_full_sync():
    logger.info("🔄 بدء جلسة النسخ...")
    try:
        pri = await asyncpg.connect(PRIMARY_URL, timeout=15)
        sec = await asyncpg.connect(SECONDARY_URL, timeout=15)
    except Exception as e:
        logger.error(f"❌ فشل الاتصال: {e}")
        return False

    try:
        await _ensure_sync_state_table(sec)
        tables = await _fetch_table_list(pri)
        logger.info(f"📋 {len(tables)} جدول للنسخ")

        total = 0
        for t in tables:
            n = await sync_table(pri, sec, t, full=False)
            total += n

        logger.info(f"✅ انتهت الجلسة: +{total} صف إجمالًا")
        return True
    finally:
        await pri.close()
        await sec.close()


async def worker_loop():
    logger.info(f"🔁 Worker: نسخ كل {SYNC_INTERVAL_SEC} ثانية")
    while True:
        try:
            await do_full_sync()
        except Exception as e:
            logger.error(f"❌ worker: {e}")
        try:
            await asyncio.sleep(SYNC_INTERVAL_SEC)
        except asyncio.CancelledError:
            break


# ═══════════════════════════════════════════════════════════════════
# 3) الأوامر
# ═══════════════════════════════════════════════════════════════════
async def cmd_setup():
    logger.info("🚀 بدء إعداد النسخ التلقائي...")
    logger.info(f"   Primary  : {_mask(PRIMARY_URL)}")
    logger.info(f"   Secondary: {_mask(SECONDARY_URL)}")
    logger.info("")

    if not PRIMARY_URL or not SECONDARY_URL:
        logger.error("❌ DATABASE_URL أو TIMESCALE_URL غير موجود.")
        return

    ok = await try_logical_replication()
    if ok:
        logger.info("")
        logger.info("🎉 الإعداد نجح! النسخ يعمل لحظيًا تلقائيًا.")
        return

    logger.info("")
    logger.info("⚠️ تعذّر Logical Replication. تفعيل النسخ الدوري...")
    logger.info(
        f"   🕒 سيُنسخ كل {SYNC_INTERVAL_SEC} ثانية.\n"
        f"   ▶️ لتشغيل العامل الدائم: "
        f"python setup_dual_db.py worker")
    await do_full_sync()


async def cmd_status():
    logger.info("📊 حالة النسخ...")
    try:
        pri = await asyncpg.connect(PRIMARY_URL, timeout=10)
        sec = await asyncpg.connect(SECONDARY_URL, timeout=10)
    except Exception as e:
        logger.error(f"❌ فشل الاتصال: {e}")
        return

    try:
        logger.info("\n─── Primary (Aiven) ───")
        wal_level = await pri.fetchval("SHOW wal_level")
        logger.info(f"   wal_level : {wal_level}")
        pub = await pri.fetchrow(
            "SELECT pubname FROM pg_publication WHERE pubname = $1",
            PUBLICATION_NAME)
        logger.info(f"   publication: {pub['pubname'] if pub else '—'}")

        logger.info("\n─── Secondary (Timescale) ───")
        sub = await sec.fetchrow(
            "SELECT subname, subenabled FROM pg_subscription "
            "WHERE subname = $1", SUBSCRIPTION_NAME)
        if sub:
            logger.info(
                f"   subscription: {sub['subname']} "
                f"(enabled={sub['subenabled']})")
        else:
            logger.info("   subscription: —")

        has_state = await sec.fetchval(f"""
            SELECT EXISTS (
                SELECT 1 FROM pg_tables
                WHERE tablename = '{SYNC_STATE_TABLE}')
        """)
        if has_state:
            rows = await sec.fetch(f"""
                SELECT table_name, last_sync, rows_synced
                FROM {SYNC_STATE_TABLE}
                ORDER BY last_sync DESC LIMIT 10
            """)
            logger.info("\n─── آخر مزامنات ───")
            for r in rows:
                logger.info(
                    f"   {r['table_name']:30} | "
                    f"{r['last_sync']} | +{r['rows_synced']}")
    finally:
        await pri.close()
        await sec.close()


async def cmd_sync():
    await do_full_sync()


async def cmd_worker():
    await worker_loop()


async def cmd_teardown():
    logger.warning("🗑️ حذف الإعداد...")
    try:
        sec = await asyncpg.connect(SECONDARY_URL, timeout=10)
        try:
            await sec.execute(
                f"ALTER SUBSCRIPTION {SUBSCRIPTION_NAME} DISABLE")
            await sec.execute(
                f"ALTER SUBSCRIPTION {SUBSCRIPTION_NAME} "
                f"SET (slot_name = NONE)")
            await sec.execute(
                f"DROP SUBSCRIPTION IF EXISTS {SUBSCRIPTION_NAME}")
            logger.info("   ✅ حُذفت subscription")
        except Exception as e:
            logger.debug(f"subscription drop: {e}")
        try:
            await sec.execute(f"DROP TABLE IF EXISTS {SYNC_STATE_TABLE}")
        except Exception:
            pass
        await sec.close()
    except Exception as e:
        logger.warning(f"⚠️ teardown secondary: {e}")

    try:
        pri = await asyncpg.connect(PRIMARY_URL, timeout=10)
        try:
            await pri.execute(
                f"DROP PUBLICATION IF EXISTS {PUBLICATION_NAME}")
            logger.info("   ✅ حُذفت publication")
        except Exception as e:
            logger.debug(f"publication drop: {e}")
        await pri.close()
    except Exception as e:
        logger.warning(f"⚠️ teardown primary: {e}")

    logger.info("✅ تم التنظيف")


# ═══════════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════════
COMMANDS = {
    "setup": cmd_setup,
    "status": cmd_status,
    "sync": cmd_sync,
    "worker": cmd_worker,
    "teardown": cmd_teardown,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print("الأوامر المتاحة:", ", ".join(COMMANDS))
        sys.exit(1)

    cmd = sys.argv[1]
    try:
        asyncio.run(COMMANDS[cmd]())
    except KeyboardInterrupt:
        logger.info("\n👋 توقف يدوي")


if __name__ == "__main__":
    main()