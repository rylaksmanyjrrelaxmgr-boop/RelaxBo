#!/usr/bin/env python3
"""
db_healthcheck.py — فحص تشخيصي شامل لقاعدة PostgreSQL
الاستخدام:  python db_healthcheck.py [DATABASE_URL]
أو:          DATABASE_URL=postgresql://... python db_healthcheck.py
"""
import asyncio
import os
import sys
import time
from datetime import datetime

import asyncpg

DB_URL = (sys.argv[1] if len(sys.argv) > 1
          else os.environ.get("DATABASE_URL"))

if not DB_URL:
    sys.exit("❌ مرّر DATABASE_URL كوسيط أو متغير بيئة")

# ──────────────────────────────────────────────
# أدوات مساعدة
# ──────────────────────────────────────────────
RESET = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
RED = "\033[31m"; GREEN = "\033[32m"; YELLOW = "\033[33m"
CYAN = "\033[36m"; MAGENTA = "\033[35m"

def hr(title, color=CYAN):
    print(f"\n{color}{BOLD}{'━'*60}\n {title}\n{'━'*60}{RESET}")

def flag(cond, ok_msg, bad_msg, warn=False):
    if cond is None:
        return f"{DIM}—{RESET} {bad_msg}"
    if cond and not warn:
        return f"{GREEN}✔{RESET} {ok_msg}"
    if cond and warn:
        return f"{YELLOW}⚠{RESET} {ok_msg}"
    return f"{RED}✘{RESET} {bad_msg}"

def human_size(b):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f}{u}"
        b /= 1024
    return f"{b:.1f}PB"


async def timed(conn, sql, *args):
    t = time.perf_counter()
    rows = await conn.fetch(sql, *args)
    return rows, (time.perf_counter() - t) * 1000


# ──────────────────────────────────────────────
# 1) نظرة عامة على القاعدة
# ──────────────────────────────────────────────
async def overview(conn):
    hr("1) نظرة عامة")
    t = time.perf_counter()
    size = await conn.fetchval("SELECT pg_database_size(current_database())")
    ms = (time.perf_counter() - t) * 1000
    n_rel = await conn.fetchval(
        "SELECT count(*) FROM pg_class WHERE relkind IN ('r','i','t')")
    n_tbl = await conn.fetchval(
        "SELECT count(*) FROM pg_class WHERE relkind IN ('r','p')")
    ver = await conn.fetchval("SHOW server_version")
    print(f"  الحجم        : {BOLD}{human_size(size)}{RESET}  "
          f"({ms:.0f} ms {flag(ms<200, 'جيد', 'بطيء!', warn=ms<800)})")
    print(f"  الإصدار      : {ver}")
    print(f"  جداول+فهارس  : {BOLD}{n_rel:,}{RESET}  ({n_tbl:,} جدول)")
    if n_rel > 5000:
        print(f"  {YELLOW}⚠ عدد الكائنات كبير — يفسّر بطء استعلامات الكتالوج{RESET}")


# ──────────────────────────────────────────────
# 2) أكبر الجداول والفهارس
# ──────────────────────────────────────────────
async def top_tables(conn):
    hr("2) أكبر 15 جدول/فهرس")
    rows = await conn.fetch("""
        SELECT c.relname, c.relkind,
               pg_total_relation_size(c.oid) AS total,
               pg_relation_size(c.oid)        AS heap,
               c.reltuples::bigint            AS rows
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r','i','m')
          AND n.nspname NOT IN ('pg_catalog','information_schema')
        ORDER BY total DESC LIMIT 15
    """)
    print(f"  {'الاسم':<40}{'النوع':<8}{'الحجم':>10}{'الصفوف':>12}")
    for r in rows:
        print(f"  {r['relname']:<40}{r['relkind']:<8}"
              f"{human_size(r['total']):>10}{r['rows']:>12,}")


# ──────────────────────────────────────────────
# 3) الفهارس غير المستخدمة (حرّاس على أداء INSERT)
# ──────────────────────────────────────────────
async def unused_indexes(conn):
    hr("3) فهارس غير مستخدمة (تُبطئ الإدراج)")
    rows = await conn.fetch("""
        SELECT s.relname AS table_name,
               s.indexrelname AS index_name,
               pg_relation_size(s.indexrelid) AS size,
               s.idx_scan
        FROM pg_stat_user_indexes s
        WHERE s.idx_scan = 0
          AND pg_relation_size(s.indexrelid) > 8192
        ORDER BY pg_relation_size(s.indexrelid) DESC
        LIMIT 20
    """)
    if not rows:
        print(f"  {GREEN}✔ لا توجد فهارس غير مستخدمة كبيرة{RESET}")
        return
    print(f"  {YELLOW}⚠ {len(rows)} فهرس لم يُستخدم مطلقاً — رشّح حذفها:{RESET}")
    for r in rows:
        print(f"  • {r['table_name']}.{r['index_name']:<35} "
              f"{human_size(r['size']):>8}  scans=0")
    print(f"  {DIM}💡 تحقق أولاً من إمكانية كونها unique أو constraint قبل الحذف{RESET}")


# ──────────────────────────────────────────────
# 4) استعلامات seq_scan على جداول كبيرة (فهارس ناقصة)
# ──────────────────────────────────────────────
async def missing_indexes(conn):
    hr("4) مسح تسلسلي مفرط — فهارس ناقصة محتملة")
    rows = await conn.fetch("""
        SELECT relname, seq_scan, idx_scan, n_live_tup,
               pg_relation_size(relid) AS size
        FROM pg_stat_user_tables
        WHERE seq_scan > 100
          AND n_live_tup > 1000
          AND pg_relation_size(relid) > 1024*1024
        ORDER BY seq_scan * n_live_tup DESC
        LIMIT 10
    """)
    if not rows:
        print(f"  {GREEN}✔ لا مشاكل واضحة{RESET}")
        return
    print(f"  {'الجدول':<30}{'seq_scan':>10}{'idx_scan':>10}"
          f"{'صفوف':>10}{'الحجم':>10}")
    for r in rows:
        ratio = r['seq_scan'] / max(r['idx_scan'] + 1, 1)
        warn = YELLOW if ratio > 5 else DIM
        print(f"  {warn}{r['relname']:<30}{r['seq_scan']:>10}{r['idx_scan']:>10}"
              f"{r['n_live_tup']:>10}{human_size(r['size']):>10}{RESET}")


# ──────────────────────────────────────────────
# 5) حالة autovacuum
# ──────────────────────────────────────────────
async def autovacuum_status(conn):
    hr("5) حالة autovacuum (جداول متأخرة)")
    rows = await conn.fetch("""
        SELECT relname, n_live_tup, n_dead_tup,
               COALESCE(n_dead_tup * 100.0 / NULLIF(n_live_tup + n_dead_tup, 0), 0)
                   AS dead_pct,
               last_autovacuum, last_autoanalyze
        FROM pg_stat_user_tables
        WHERE n_live_tup > 1000
        ORDER BY n_dead_tup DESC
        LIMIT 15
    """)
    print(f"  {'الجدول':<28}{'live':>8}{'dead':>8}{'%dead':>7}"
          f"  آخر autovacuum")
    for r in rows:
        pct = r['dead_pct']
        color = RED if pct > 20 else (YELLOW if pct > 10 else "")
        av = r['last_autovacuum']
        av_s = av.strftime("%m-%d %H:%M") if av else f"{RED}أبداً{RESET}"
        print(f"  {color}{r['relname']:<28}{r['n_live_tup']:>8}"
              f"{r['n_dead_tup']:>8}{pct:>6.1f}%  {av_s}{RESET}")

    # فحص إعدادات
    print(f"\n  {DIM}الإعدادات الحالية:{RESET}")
    for p in ("autovacuum", "autovacuum_naptime",
              "autovacuum_vacuum_scale_factor",
              "autovacuum_analyze_scale_factor"):
        v = await conn.fetchval(f"SHOW {p}")
        print(f"    {p:<40}= {v}")


# ──────────────────────────────────────────────
# 6) نسبة إصابة الـ cache
# ──────────────────────────────────────────────
async def cache_hit(conn):
    hr("6) نسبة إصابة الـ Cache")
    r = await conn.fetchrow("""
        SELECT
          sum(heap_blks_read)::bigint              AS hr,
          sum(heap_blks_hit)::bigint               AS hh,
          sum(idx_blks_read)::bigint               AS ir,
          sum(idx_blks_hit)::bigint                AS ih
        FROM pg_statio_user_tables
    """)
    th = r['hr'] + r['hh']
    ti = r['ir'] + r['ih']
    heap_pct = 100 * r['hh'] / th if th else 100
    idx_pct  = 100 * r['ih'] / ti if ti else 100
    print(f"  Heap hit : {heap_pct:5.2f}%  "
          f"{flag(heap_pct >= 95, 'ممتاز', 'منخفض (<95%) — ارفع shared_buffers', warn=heap_pct>=90)}")
    print(f"  Index hit: {idx_pct:5.2f}%  "
          f"{flag(idx_pct >= 97, 'ممتاز', 'منخفض (<97%)', warn=idx_pct>=93)}")
    sb = await conn.fetchval("SHOW shared_buffers")
    print(f"  {DIM}shared_buffers = {sb}{RESET}")


# ──────────────────────────────────────────────
# 7) أقفال معلّقة
# ──────────────────────────────────────────────
async def locks(conn):
    hr("7) أقفال معلّقة / معاملات طويلة")
    rows = await conn.fetch("""
        SELECT pid, state,
               now() - xact_start AS xact_age,
               wait_event_type, wait_event,
               left(query, 80) AS q
        FROM pg_stat_activity
        WHERE state <> 'idle'
          AND xact_start IS NOT NULL
          AND now() - xact_start > interval '5 seconds'
          AND pid <> pg_backend_pid()
        ORDER BY xact_start
        LIMIT 10
    """)
    if not rows:
        print(f"  {GREEN}✔ لا معاملات طويلة (>5s){RESET}")
        return
    for r in rows:
        print(f"  pid={r['pid']} {r['state']} age={r['xact_age']} "
              f"wait={r['wait_event_type']}/{r['wait_event']}")
        print(f"    {DIM}{r['q']}{RESET}")


# ──────────────────────────────────────────────
# 8) فحوصات موجّهة (subscriptions / managed_bot_users)
# ──────────────────────────────────────────────
async def targeted_checks(conn):
    hr("8) فحوصات موجّهة (من سجلاتك)")

    # (أ) فهرس utils.py:3992 على subscriptions(user_id, end_date)
    print(f"\n  {BOLD}[أ] استعلام: MAX(end_date) GROUP BY user_id{RESET}")
    exists = await conn.fetchval("""
        SELECT EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE tablename = 'subscriptions'
              AND indexdef ILIKE '%user_id%end_date%'
        )
    """)
    print(f"  {flag(exists, 'فهرس (user_id, end_date) موجود', 'مفقود → CREATE INDEX CONCURRENTLY على (user_id, end_date DESC)')}")

    if exists:
        rows, ms = await timed(conn, """
            EXPLAIN (FORMAT JSON)
            SELECT user_id, MAX(end_date) FROM subscriptions GROUP BY user_id
        """)
        plan = rows[0][0]
        print(f"  {DIM}EXPLAIN زمن الاستخراج: {ms:.0f}ms{RESET}")
        # اطبع نوع المسح
        try:
            node = plan[0]["Plan"]
            print(f"  {DIM}Node: {node.get('Node Type')}{RESET}")
        except Exception:
            pass

    # (ب) managed_bot_users
    print(f"\n  {BOLD}[ب] جدول managed_bot_users{RESET}")
    idx = await conn.fetch("""
        SELECT indexname, indexdef FROM pg_indexes
        WHERE tablename = 'managed_bot_users'
    """)
    print(f"  عدد الفهارس: {len(idx)}")
    for r in idx:
        print(f"    • {r['indexname']}")

    tst = await conn.fetch("""
        SELECT relname, n_tup_ins, n_tup_upd, n_tup_del, n_dead_tup,
               pg_total_relation_size(relid) AS size
        FROM pg_stat_user_tables
        WHERE relname = 'managed_bot_users'
    """)
    for r in tst:
        print(f"  حجم: {human_size(r['size'])}  | "
              f"ins={r['n_tup_ins']:,} upd={r['n_tup_upd']:,} "
              f"del={r['n_tup_del']:,} dead={r['n_dead_tup']:,}")

    # synchronous_commit
    sc = await conn.fetchval("SHOW synchronous_commit")
    print(f"  synchronous_commit = {sc}")
    if sc == "on":
        print(f"  {DIM}💡 إذا كانت الكتابة غير حرجة لحظياً جرّب "
              f"SET LOCAL synchronous_commit=local{RESET}")


# ──────────────────────────────────────────────
# 9) أبطأ الاستعلامات (pg_stat_statements)
# ──────────────────────────────────────────────
async def slow_queries(conn):
    hr("9) أبطأ الاستعلامات (pg_stat_statements)")
    try:
        rows = await conn.fetch("""
            SELECT left(query, 90) AS q,
                   calls,
                   round(total_exec_time::numeric, 1) AS total_ms,
                   round(mean_exec_time::numeric, 2)  AS mean_ms,
                   rows
            FROM pg_stat_statements
            WHERE query NOT ILIKE '%pg_stat_statements%'
            ORDER BY mean_exec_time DESC
            LIMIT 8
        """)
        for r in rows:
            print(f"  mean={r['mean_ms']:>8}ms calls={r['calls']:>6,} "
                  f"total={r['total_ms']:>10}ms")
            print(f"    {DIM}{r['q']}{RESET}")
    except asyncpg.exceptions.UndefinedTableError:
        print(f"  {YELLOW}⚠ امتداد pg_stat_statements غير مثبّت{RESET}")
        print(f"  {DIM}أضفه في postgresql.conf: shared_preload_libraries "
              f"= 'pg_stat_statements'{RESET}")
        print(f"  {DIM}ثم: CREATE EXTENSION pg_stat_statements;{RESET}")


# ──────────────────────────────────────────────
# Runner
# ──────────────────────────────────────────────
async def main():
    print(f"{MAGENTA}{BOLD}🩺 فحص صحة قاعدة البيانات — "
          f"{datetime.now():%Y-%m-%d %H:%M}{RESET}")
    conn = await asyncpg.connect(DB_URL)
    try:
        await overview(conn)
        await top_tables(conn)
        await unused_indexes(conn)
        await missing_indexes(conn)
        await autovacuum_status(conn)
        await cache_hit(conn)
        await locks(conn)
        await targeted_checks(conn)
        await slow_queries(conn)
    finally:
        await conn.close()
    print(f"\n{MAGENTA}{BOLD}✅ اكتمل الفحص{RESET}")


if __name__ == "__main__":
    asyncio.run(main())