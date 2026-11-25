#!/usr/bin/env python3
"""
db_audit_indexes.py — فحص حي للفهارس بين الكود وقاعدة البيانات (v1.0).

يقارن الفهارس المُعرَّفة في الكود (database_tables.py / database.py /
database_migrations.py) مع الفهارس الفعلية في قاعدة البيانات الحية،
ويُنتج تقريراً يكشف:

  1. MISSING: فهارس مُعرَّفة في الكود لكنها غير موجودة في DB (تحتاج CREATE).
  2. ORPHAN:  فهارس موجودة في DB لكنها غير مُعرَّفة في الكود (ربما قديمة).
  3. UNUSED:  فهارس موجودة لكنها لم تُستخدم (idx_scan=0) — مرشحة للحذف.
  4. BLOAT:   فهارس بحجم كبير قد تحتاج REINDEX.
  5. DUPLICATE: فهارس مكررة (نفس الأعمدة على نفس الجدول).

الاستخدام:
  DATABASE_URL=postgres://... python3 db_audit_indexes.py
  DATABASE_URL=postgres://... python3 db_audit_indexes.py --json report.json
  DATABASE_URL=postgres://... python3 db_audit_indexes.py --create-missing

ملاحظات:
  - يعتمد على asyncpg (المستخدم في المشروع). لو غير متاح، يستخدم psycopg2.
  - --create-missing ينشئ الفهارس المفقودة بـ CONCURRENTLY (آمن، لا يأخذ قفل).
  - آمن للقراءة فقط افتراضياً؛ لا يُعدّل DB إلا مع --create-missing.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Set, Optional, Any

# ═══════════════════════════════════════════════════════════════════════
# 1) استخراج الفهارس المُعرَّفة في الكود
# ═══════════════════════════════════════════════════════════════════════

CODE_FILES = [
    "database_tables.py",
    "database.py",
    "database_migrations.py",
]

# نمط: "CREATE [UNIQUE] INDEX [CONCURRENTLY] [IF NOT EXISTS] idx_name ON table(cols)"
# أو tuple ("table", "idx_name", "CREATE INDEX ...")
INDEX_NAME_RE = re.compile(r'idx_[a-z_]+')
# استخراج الجدول من CREATE INDEX ... ON table_name
CREATE_ON_RE = re.compile(
    r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?'
    r'(idx_[a-z_]+)\s+ON\s+(?:ONLY\s+)?([a-z_]+)',
    re.IGNORECASE,
)


def extract_code_indexes(repo_root: Path) -> Dict[str, Dict[str, str]]:
    """
    يُعيد {idx_name: {"table": ..., "file": ..., "stmt": ...}}.

    يتعامل مع أنماط متعددة في الكود:
      1) CREATE [UNIQUE] INDEX [CONCURRENTLY] [IF NOT EXISTS] idx_name ON table(...)
      2) tuple: ("table", "idx_name", "CREATE INDEX ... ON table(...)")
      3) tuple: ("table", "idx_name", "table(cols)") — بدون CREATE INDEX prefix
    """
    import ast

    code_idx: Dict[str, Dict[str, str]] = {}

    for fname in CODE_FILES:
        fpath = repo_root / fname
        if not fpath.exists():
            continue
        src = fpath.read_text(encoding="utf-8", errors="replace")

        # --- Pattern 1: inline CREATE INDEX ... ON table ---
        # يجمع كل idx_name + table من عبارات CREATE INDEX (متعددة الأسطر)
        inline_re = re.compile(
            r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?'
            r'(?:IF\s+NOT\s+EXISTS\s+)?'
            r'(idx_[a-z_]+)\s+ON\s+(?:ONLY\s+)?([a-z_]+)',
            re.IGNORECASE,
        )
        for m in inline_re.finditer(src):
            idx_name = m.group(1)
            table = m.group(2)
            if idx_name not in code_idx:
                code_idx[idx_name] = {
                    "table": table,
                    "file": fname,
                    "stmt": f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}(...)  "
                            f"[extracted from inline]",
                }

        # --- Pattern 2 & 3: AST-parse tuples of strings ---
        # tuple formats:
        #   ("table", "idx_name", "CREATE INDEX ... ON table(...)")
        #   ("table", "idx_name", "table(cols)")  ← partial
        # كذلك قوائم أسماء فهارس: ["idx_a", "idx_b", ...] — لا جدول هنا
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.Tuple, ast.List)):
                continue
            # اجمع عناصر الـ tuple التي هي string literals
            str_elems = []
            for el in node.elts:
                if isinstance(el, ast.Constant) and isinstance(el.value, str):
                    str_elems.append(el.value)
                elif isinstance(el, ast.Str):  # Python <3.8
                    str_elems.append(el.s)
            if len(str_elems) < 2:
                continue

            # Pattern 2/3: ("table", "idx_name", "...") — أول عنصر = table
            # لكن يجب أن يكون table اسم جدول (لا يحتوي مسافات ولا idx_)
            first = str_elems[0]
            second = str_elems[1] if len(str_elems) > 1 else ""

            # هل الأول اسم جدول صالح والثاني اسم فهرس؟
            if (re.fullmatch(r'[a-z_]+', first)
                    and re.fullmatch(r'idx_[a-z_]+', second)):
                table = first
                idx_name = second
                # العنصر الثالث (لو موجود) هو الـ ON-clause أو CREATE stmt
                stmt_part = str_elems[2] if len(str_elems) > 2 else ""
                if idx_name not in code_idx:
                    if "CREATE" in stmt_part.upper():
                        stmt = stmt_part
                    elif stmt_part:
                        # partial: "table(cols)" → ابنِ CREATE كامل
                        stmt = (f"CREATE INDEX IF NOT EXISTS {idx_name} "
                                f"ON {stmt_part}")
                    else:
                        stmt = (f"CREATE INDEX IF NOT EXISTS {idx_name} "
                                f"ON {table}(...)  [name-only]")
                    code_idx[idx_name] = {
                        "table": table,
                        "file": fname,
                        "stmt": stmt,
                    }

            # Pattern: list of index names only ["idx_a", "idx_b", ...]
            # (لا table معروف — نتجاهلها هنا لأنها مراجع لا تعريفات)
    return code_idx


# ═══════════════════════════════════════════════════════════════════════
# 2) الاستعلام عن الفهارس في DB الحية
# ═══════════════════════════════════════════════════════════════════════

# يجمع: اسم الفهرس، الجدول، الأعمدة، الحجم، عدد المسح، آخر استخدام
DB_INDEXES_SQL = """
SELECT
    i.relname                          AS index_name,
    t.relname                          AS table_name,
    pg_get_indexdef(ix.indexrelid)     AS index_def,
    pg_size_pretty(pg_relation_size(ix.indexrelid)) AS size_pretty,
    pg_relation_size(ix.indexrelid)    AS size_bytes,
    COALESCE(s.idx_scan, 0)            AS idx_scan,
    COALESCE(s.idx_tup_read, 0)        AS idx_tup_read,
    COALESCE(s.idx_tup_fetch, 0)       AS idx_tup_fetch,
    ix.indisunique                     AS is_unique,
    ix.indisvalid                      AS is_valid
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
LEFT JOIN pg_stat_user_indexes s
       ON s.indexrelid = ix.indexrelid
      AND s.relid = ix.indrelid
WHERE n.nspname = 'public'
  AND t.relkind = 'r'
ORDER BY t.relname, i.relname;
"""

# يجمع الأعمدة لكل فهرس (لاكتشاف التكرار)
INDEX_COLUMNS_SQL = """
SELECT
    t.relname AS table_name,
    i.relname AS index_name,
    array_agg(a.attname ORDER BY array_position(ix.indkey, a.attnum)) AS columns
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
WHERE n.nspname = 'public' AND t.relkind = 'r'
GROUP BY t.relname, i.relname;
"""


async def fetch_db_indexes(database_url: str) -> Tuple[List[Dict], Dict[Tuple[str, Tuple], List[str]]]:
    """
    يُعيد (قائمة فهارس DB, { (table, tuple(cols)): [idx_name, ...] }).
    الـ dict الثاني لاكتشاف التكرار (نفس الأعمدة على نفس الجدول).
    """
    try:
        import asyncpg
    except ImportError:
        return await _fetch_with_psycopg(database_url)

    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch(DB_INDEXES_SQL)
        col_rows = await conn.fetch(INDEX_COLUMNS_SQL)
    finally:
        await conn.close()

    db_indexes = []
    for r in rows:
        db_indexes.append({
            "index_name": r["index_name"],
            "table_name": r["table_name"],
            "index_def": r["index_def"],
            "size_pretty": r["size_pretty"],
            "size_bytes": r["size_bytes"] or 0,
            "idx_scan": r["idx_scan"] or 0,
            "idx_tup_read": r["idx_tup_read"] or 0,
            "idx_tup_fetch": r["idx_tup_fetch"] or 0,
            "is_unique": r["is_unique"],
            "is_valid": r["is_valid"],
        })

    col_map: Dict[Tuple[str, Tuple], List[str]] = {}
    for r in col_rows:
        cols = tuple(r["columns"])
        key = (r["table_name"], cols)
        col_map.setdefault(key, []).append(r["index_name"])

    return db_indexes, col_map


async def _fetch_with_psycopg(database_url: str):
    """fallback لو asyncpg غير متاح."""
    import psycopg2
    conn = psycopg2.connect(database_url)
    conn.set_session(readonly=True)
    cur = conn.cursor()
    cur.execute(DB_INDEXES_SQL)
    cols = [d[0] for d in cur.description]
    db_indexes = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.execute(INDEX_COLUMNS_SQL)
    col_map: Dict[Tuple[str, Tuple], List[str]] = {}
    for r in cur.fetchall():
        cols_t = tuple(r[2])
        key = (r[0], cols_t)
        col_map.setdefault(key, []).append(r[1])
    cur.close()
    conn.close()
    return db_indexes, col_map


# ═══════════════════════════════════════════════════════════════════════
# 3) المقارنة + التقرير
# ═══════════════════════════════════════════════════════════════════════

def build_report(
    code_idx: Dict[str, Dict[str, str]],
    db_indexes: List[Dict],
    col_map: Dict[Tuple[str, Tuple], List[str]],
) -> Dict[str, Any]:
    db_names: Set[str] = {i["index_name"] for i in db_indexes}
    code_names: Set[str] = set(code_idx.keys())

    missing = sorted(code_names - db_names)
    orphan = sorted(db_names - code_names)

    # UNUSED: idx_scan=0 و ليست UNIQUE و حجمها > 0
    unused = [
        {
            "index_name": i["index_name"],
            "table_name": i["table_name"],
            "size_pretty": i["size_pretty"],
            "size_bytes": i["size_bytes"],
            "is_unique": i["is_unique"],
        }
        for i in db_indexes
        if i["idx_scan"] == 0
        and not i["is_unique"]
        and i["size_bytes"] > 0
    ]
    unused.sort(key=lambda x: -x["size_bytes"])

    # BLOAT: حجم > 10MB (مرشحة لـ REINDEX)
    bloat = [
        {
            "index_name": i["index_name"],
            "table_name": i["table_name"],
            "size_pretty": i["size_pretty"],
            "size_bytes": i["size_bytes"],
            "idx_scan": i["idx_scan"],
        }
        for i in db_indexes
        if i["size_bytes"] > 10 * 1024 * 1024
    ]
    bloat.sort(key=lambda x: -x["size_bytes"])

    # INVALID: فهارس معطوبة (indisvalid=False) — تحتاج REINDEX
    invalid = [
        {"index_name": i["index_name"], "table_name": i["table_name"]}
        for i in db_indexes
        if not i["is_valid"]
    ]

    # DUPLICATE: نفس الأعمدة على نفس الجدول بأكثر من فهرس
    duplicates = []
    for (table, cols), idxs in col_map.items():
        if len(idxs) > 1:
            duplicates.append({
                "table": table,
                "columns": list(cols),
                "indexes": idxs,
            })

    # تفاصيل الفهارس المفقودة (مع الـ CREATE statement)
    missing_detail = [
        {
            "index_name": name,
            "table": code_idx[name]["table"],
            "file": code_idx[name]["file"],
            "stmt": code_idx[name]["stmt"],
        }
        for name in missing
    ]

    total_db_size = sum(i["size_bytes"] for i in db_indexes)

    return {
        "summary": {
            "code_indexes": len(code_names),
            "db_indexes": len(db_names),
            "missing": len(missing),
            "orphan": len(orphan),
            "unused": len(unused),
            "bloat_candidates": len(bloat),
            "invalid": len(invalid),
            "duplicate_groups": len(duplicates),
            "total_index_size_bytes": total_db_size,
            "total_index_size_mb": round(total_db_size / (1024 * 1024), 2),
        },
        "missing_indexes": missing_detail,
        "orphan_indexes": orphan,
        "unused_indexes": unused[:50],  # top 50
        "bloat_candidates": bloat[:30],
        "invalid_indexes": invalid,
        "duplicate_indexes": duplicates,
    }


def render_text_report(report: Dict[str, Any]) -> str:
    s = report["summary"]
    lines = []
    lines.append("═" * 70)
    lines.append("📊 تقرير فحص الفهارس — Index Audit Report")
    lines.append("═" * 70)
    lines.append("")
    lines.append("📋 الملخص:")
    lines.append(f"  فهارس مُعرَّفة في الكود : {s['code_indexes']}")
    lines.append(f"  فهارس في DB الحية     : {s['db_indexes']}")
    lines.append(f"  حجم إجمالي للفهارس    : {s['total_index_size_mb']:.1f} MB")
    lines.append("")
    lines.append(f"  ❌ مفقودة (في الكود لا في DB): {s['missing']}")
    lines.append(f"  ⚠️  يتيمة (في DB لا في الكود): {s['orphan']}")
    lines.append(f"  🟡 غير مستخدمة (idx_scan=0) : {s['unused']}")
    lines.append(f"  🟠 منتفخة (>10MB)           : {s['bloat_candidates']}")
    lines.append(f"  🔴 معطوبة (invalid)         : {s['invalid']}")
    lines.append(f"  🔁 مكررة (نفس الأعمدة)      : {s['duplicate_groups']}")
    lines.append("")

    if report["missing_indexes"]:
        lines.append("─" * 70)
        lines.append("❌ فهارس مفقودة — تحتاج CREATE:")
        lines.append("─" * 70)
        for m in report["missing_indexes"][:30]:
            lines.append(f"  • {m['index_name']} on {m['table']} ({m['file']})")
            lines.append(f"    {m['stmt'][:120]}")
        if len(report["missing_indexes"]) > 30:
            lines.append(f"  ... و {len(report['missing_indexes']) - 30} أخرى")
        lines.append("")

    if report["invalid_indexes"]:
        lines.append("─" * 70)
        lines.append("🔴 فهارس معطوبة — تحتاج REINDEX:")
        lines.append("─" * 70)
        for i in report["invalid_indexes"]:
            lines.append(f"  • {i['index_name']} on {i['table_name']}")
            lines.append(f"    REINDEX INDEX CONCURRENTLY {i['index_name']};")
        lines.append("")

    if report["bloat_candidates"]:
        lines.append("─" * 70)
        lines.append("🟠 فهارس منتفخة (>10MB) — مرشحة لـ REINDEX:")
        lines.append("─" * 70)
        for b in report["bloat_candidates"][:15]:
            lines.append(
                f"  • {b['index_name']:45s} {b['size_pretty']:>8s} "
                f"(scans={b['idx_scan']})"
            )
        lines.append("")

    if report["duplicate_indexes"]:
        lines.append("─" * 70)
        lines.append("🔁 فهارس مكررة (نفس الأعمدة على نفس الجدول):")
        lines.append("─" * 70)
        for d in report["duplicate_indexes"][:15]:
            lines.append(
                f"  • {d['table']}({','.join(d['columns'])}) ← "
                f"{', '.join(d['indexes'])}"
            )
        lines.append("")

    if report["unused_indexes"]:
        lines.append("─" * 70)
        lines.append("🟡 فهارس غير مستخدمة (idx_scan=0) — مرشحة للحذف:")
        lines.append("  (تحقق أولاً أنها ليست مطلوبة لـ query نادر)")
        lines.append("─" * 70)
        for u in report["unused_indexes"][:20]:
            lines.append(
                f"  • {u['index_name']:45s} {u['size_pretty']:>8s} "
                f"on {u['table_name']}"
            )
        lines.append("")

    lines.append("═" * 70)
    lines.append("💡 توصيات:")
    lines.append("═" * 70)
    if s["missing"] > 0:
        lines.append(
            f"  1. أنشئ {s['missing']} فهرس مفقود بـ: "
            f"python3 db_audit_indexes.py --create-missing"
        )
    if s["invalid"] > 0:
        lines.append(f"  2. أعد بناء {s['invalid']} فهرس معطوب: REINDEX INDEX CONCURRENTLY <name>")
    if s["bloat_candidates"] > 0:
        lines.append(f"  3. فكّر في REINDEX لأكبر {min(s['bloat_candidates'], 5)} فهرس منتفخ")
    if s["duplicate_groups"] > 0:
        lines.append(f"  4. راجع {s['duplicate_groups']} مجموعة فهارس مكررة (احذف الزائد)")
    if s["unused"] > 0:
        lines.append(f"  5. راجع {s['unused']} فهرس غير مستخدم — لكن تحقق أولاً من queries نادرة")
    if all(v == 0 for k, v in s.items() if k not in ("code_indexes", "db_indexes", "total_index_size_bytes", "total_index_size_mb")):
        lines.append("  ✅ كل الفهارس متزامنة ومستخدمة وسليمة — لا إجراء مطلوب.")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 4) إنشاء الفهارس المفقودة (--create-missing)
# ═══════════════════════════════════════════════════════════════════════

async def create_missing_indexes(
    database_url: str,
    missing: List[Dict[str, str]],
    dry_run: bool = False,
) -> None:
    """ينشئ الفهارس المفقودة بـ CONCURRENTLY (آمن)."""
    if not missing:
        print("✅ لا فهارس مفقودة — لا شيء لإنشائه.")
        return

    try:
        import asyncpg
    except ImportError:
        print("❌ asyncpg غير متاح — لا يمكن إنشاء الفهارس. ثبّته: pip install asyncpg")
        return

    conn = await asyncpg.connect(database_url)
    created = 0
    failed = 0
    try:
        for m in missing:
            stmt = m["stmt"]
            # أضف CONCURRENTLY لو غير موجودة (آمن، لا يأخذ قفل حصري)
            if "CONCURRENTLY" not in stmt.upper():
                stmt = stmt.replace("CREATE INDEX", "CREATE INDEX CONCURRENTLY", 1)
                stmt = stmt.replace("CREATE UNIQUE INDEX", "CREATE UNIQUE INDEX CONCURRENTLY", 1)
            # تأكد من IF NOT EXISTS
            if "IF NOT EXISTS" not in stmt.upper():
                stmt = re.sub(
                    r'(CREATE\s+(?:UNIQUE\s+)?INDEX\s+CONCURRENTLY\s+)',
                    r'\1IF NOT EXISTS ',
                    stmt, count=1, flags=re.IGNORECASE,
                )

            print(f"  → {m['index_name']} on {m['table']}... ", end="", flush=True)
            if dry_run:
                print("DRY-RUN")
                continue
            try:
                await conn.execute(stmt)
                print("✅")
                created += 1
            except Exception as e:
                print(f"❌ {str(e)[:80]}")
                failed += 1
    finally:
        await conn.close()

    print(f"\n📊 النتيجة: {created} أُنشئ، {failed} فشل.")
    if dry_run:
        print("   (DRY-RUN — لم يُعدّل شيء فعلياً)")


# ═══════════════════════════════════════════════════════════════════════
# 5) main
# ═══════════════════════════════════════════════════════════════════════

async def main():
    parser = argparse.ArgumentParser(
        description="فحص الفهارس بين الكود و DB الحية",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repo-root", default=".",
        help="جذر المستودع (افتراضي: الحالي)",
    )
    parser.add_argument(
        "--database-url", default=os.getenv("DATABASE_URL", ""),
        help="DATABASE_URL (افتراضي: من env)",
    )
    parser.add_argument(
        "--json", metavar="PATH",
        help="احفظ التقرير كـ JSON في هذا المسار",
    )
    parser.add_argument(
        "--create-missing", action="store_true",
        help="أنشئ الفهارس المفقودة بـ CONCURRENTLY (آمن)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="مع --create-missing: اعرض فقط دون تنفيذ",
    )
    args = parser.parse_args()

    if not args.database_url:
        print("❌ DATABASE_URL غير مضبوط. مرّره بـ --database-url أو كـ env var.")
        print("   مثال: DATABASE_URL=postgres://... python3 db_audit_indexes.py")
        sys.exit(1)

    repo_root = Path(args.repo_root).resolve()
    print(f"📂 المستودع: {repo_root}")
    print(f"🗄️  DB: {args.database_url[:40]}...")

    # 1) استخرج فهارس الكود
    print("\n🔍 استخراج الفهارس من الكود...")
    code_idx = extract_code_indexes(repo_root)
    print(f"   ✅ {len(code_idx)} فهرس مُعرَّف في الكود")

    # 2) استعلم DB
    print("\n🔍 الاستعلام عن الفهارس في DB الحية...")
    try:
        db_indexes, col_map = await fetch_db_indexes(args.database_url)
    except Exception as e:
        print(f"   ❌ فشل الاتصال بـ DB: {e}")
        sys.exit(2)
    print(f"   ✅ {len(db_indexes)} فهرس في DB")

    # 3) ابنِ التقرير
    report = build_report(code_idx, db_indexes, col_map)

    # 4) اعرض/احفظ
    print()
    print(render_text_report(report))

    if args.json:
        out = Path(args.json)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        print(f"\n💾 التقرير JSON محفوظ: {out}")

    # 5) إنشاء المفقودة لو طُلب
    if args.create_missing and report["missing_indexes"]:
        print(f"\n🔨 إنشاء {len(report['missing_indexes'])} فهرس مفقود...")
        await create_missing_indexes(
            args.database_url, report["missing_indexes"], dry_run=args.dry_run
        )


if __name__ == "__main__":
    asyncio.run(main())
