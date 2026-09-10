#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
health_check.py — فحص شامل لصحة نظام قاعدة البيانات
================================================================================
يفحص:
  1. البيئة والاعتماديات
  2. محرك قاعدة البيانات النشط
  3. الاتصال الفعلي
  4. الجداول الموجودة والمفقودة
  5. الفهارس المُنشأة
  6. نظام الكاش (حقيقي أم fallback)
  7. المهام الخلفية
  8. الأقفال والـ pools
  9. اختبار كتابة/قراءة/حذف فعلي
 10. اختبار المعاملات (transaction rollback)

الاستخدام:
    python health_check.py
    python health_check.py --verbose
    python health_check.py --json > report.json
"""

import os
import sys
import json
import time
import asyncio
import argparse
import importlib
from pathlib import Path
from typing import Dict, List, Any, Tuple

# ═══════════════════════════════════════════════════════════════════
# الألوان
# ═══════════════════════════════════════════════════════════════════
class C:
    OK    = "\033[92m"
    WARN  = "\033[93m"
    ERR   = "\033[91m"
    INFO  = "\033[96m"
    BOLD  = "\033[1m"
    DIM   = "\033[2m"
    END   = "\033[0m"
    @staticmethod
    def strip(s): return s


# ═══════════════════════════════════════════════════════════════════
# أدوات التقرير
# ═══════════════════════════════════════════════════════════════════
class Report:
    def __init__(self, json_mode: bool = False):
        self.json_mode = json_mode
        self.sections: List[Dict[str, Any]] = []

    def section(self, title: str):
        if not self.json_mode:
            print(f"\n{C.BOLD}{'═' * 60}{C.END}")
            print(f"{C.BOLD}  {title}{C.END}")
            print(f"{C.BOLD}{'═' * 60}{C.END}")
        self.sections.append({"title": title, "items": []})

    def item(self, label: str, value: Any, status: str = "info", note: str = ""):
        if not self.json_mode:
            icon = {
                "ok":   f"{C.OK}✅{C.END}",
                "warn": f"{C.WARN}⚠️ {C.END}",
                "err":  f"{C.ERR}❌{C.END}",
                "info": f"{C.INFO}ℹ️ {C.END}",
            }.get(status, "  ")
            line = f"  {icon} {label:<40} = {value}"
            if note:
                line += f"  {C.DIM}({note}){C.END}"
            print(line)
        self.sections[-1]["items"].append({
            "label": label, "value": str(value),
            "status": status, "note": note,
        })

    def summary(self, ok: int, warn: int, err: int):
        if not self.json_mode:
            print(f"\n{C.BOLD}{'═' * 60}{C.END}")
            print(f"{C.BOLD}  الملخص{C.END}")
            print(f"{C.BOLD}{'═' * 60}{C.END}")
            print(f"  {C.OK}✅ ناجح  : {ok}{C.END}")
            print(f"  {C.WARN}⚠️  تحذير : {warn}{C.END}")
            print(f"  {C.ERR}❌ فاشل  : {err}{C.END}")
            total = ok + warn + err
            pct = (ok / total * 100) if total else 0
            color = C.OK if pct >= 90 else (C.WARN if pct >= 60 else C.ERR)
            print(f"  {color}📊 الصحة : {pct:.1f}%{C.END}\n")
        self.sections.append({
            "title": "summary",
            "ok": ok, "warn": warn, "err": err,
        })


# ═══════════════════════════════════════════════════════════════════
# 1. فحص البيئة
# ═══════════════════════════════════════════════════════════════════
def check_environment(rep: Report) -> Dict[str, Any]:
    rep.section("1. البيئة والاعتماديات")
    info = {}

    info["python_version"] = sys.version.split()[0]
    rep.item("Python", info["python_version"], "ok")

    info["platform"] = sys.platform
    rep.item("المنصة", info["platform"], "info")

    info["cwd"] = os.getcwd()
    rep.item("مجلد العمل", info["cwd"], "info")

    # متغيرات البيئة
    db_url = os.getenv("DATABASE_URL", "").strip()
    info["DATABASE_URL"] = "SET" if db_url else "EMPTY"
    rep.item(
        "DATABASE_URL",
        "مضبوط" if db_url else "فارغ (سيُستخدم SQLite)",
        "ok" if db_url else "warn",
        note=(db_url[:60] + "...") if len(db_url) > 60 else db_url,
    )

    # الحزم
    packages = {
        "aiosqlite": "SQLite async",
        "asyncpg": "PostgreSQL async",
        "asyncmy": "MySQL async",
    }
    info["packages"] = {}
    for pkg, desc in packages.items():
        try:
            mod = importlib.import_module(pkg)
            ver = getattr(mod, "__version__", "?")
            info["packages"][pkg] = ver
            rep.item(f"حزمة {pkg}", f"مثبتة v{ver}", "ok", note=desc)
        except ImportError:
            info["packages"][pkg] = None
            rep.item(f"حزمة {pkg}", "غير مثبتة", "warn", note=desc)

    # الملفات
    files = ["database.py", "database_tables.py", "cache.py", "config.py",
             "banned_words.py", "auto_replies.py"]
    info["files"] = {}
    for f in files:
        exists = Path(f).exists()
        info["files"][f] = exists
        status = "ok" if exists else ("warn" if f in ("cache.py", "banned_words.py", "auto_replies.py") else "err")
        rep.item(f"ملف {f}", "موجود" if exists else "مفقود", status)

    return info


# ═══════════════════════════════════════════════════════════════════
# 2. فحص استيراد الوحدات
# ═══════════════════════════════════════════════════════════════════
def check_imports(rep: Report) -> Dict[str, Any]:
    rep.section("2. استيراد الوحدات")
    info = {}

    try:
        import database as db_mod
        info["database"] = True
        rep.item("استيراد database.py", "نجح", "ok")
    except Exception as e:
        info["database"] = False
        rep.item("استيراد database.py", f"فشل: {e}", "err")
        return info

    # ثوابت الكشف
    info["DB_TYPE"] = getattr(db_mod, "DB_TYPE", "?")
    rep.item("DB_TYPE المكتشف", info["DB_TYPE"], "ok")

    info["USE_POSTGRES"] = getattr(db_mod, "USE_POSTGRES", False)
    rep.item("USE_POSTGRES", info["USE_POSTGRES"], "info")

    info["USE_MYSQL"] = getattr(db_mod, "USE_MYSQL", False)
    rep.item("USE_MYSQL", info["USE_MYSQL"], "info")

    info["CACHE_AVAILABLE"] = getattr(db_mod, "CACHE_AVAILABLE", False)
    rep.item(
        "نظام الكاش",
        "cache.py الحقيقي" if info["CACHE_AVAILABLE"] else "fallback داخلي",
        "ok" if info["CACHE_AVAILABLE"] else "warn",
    )

    info["TABLES_MODULE_AVAILABLE"] = getattr(db_mod, "TABLES_MODULE_AVAILABLE", False)
    rep.item(
        "database_tables.py",
        "متاح" if info["TABLES_MODULE_AVAILABLE"] else "غير متاح",
        "ok" if info["TABLES_MODULE_AVAILABLE"] else "err",
    )

    info["DB"] = getattr(db_mod, "DB", None)
    info["TimeUtils"] = getattr(db_mod, "TimeUtils", None)
    rep.item("TimeUtils", "متاح" if info["TimeUtils"] else "مفقود",
             "ok" if info["TimeUtils"] else "err")

    # اختبار TimeUtils
    if info["TimeUtils"]:
        try:
            now = info["TimeUtils"].utc_now()
            mecca = info["TimeUtils"].mecca_now()
            diff = (mecca - now).total_seconds() / 3600
            rep.item("TimeUtils.utc_now()", now.isoformat(), "ok")
            rep.item("TimeUtils.mecca_now()", mecca.isoformat(), "ok")
            rep.item("فرق مكة/UTC", f"{diff:.1f} ساعة",
                     "ok" if abs(diff - 3) < 0.1 else "warn")
        except Exception as e:
            rep.item("TimeUtils", f"خطأ: {e}", "err")

    return info


# ═══════════════════════════════════════════════════════════════════
# 3. فحص الاتصال
# ═══════════════════════════════════════════════════════════════════
async def check_connection(rep: Report, db) -> Dict[str, Any]:
    rep.section("3. تهيئة الاتصال")
    info = {}

    t0 = time.monotonic()
    try:
        ok = await db.initialize_db()
        elapsed = time.monotonic() - t0
        info["init_ok"] = ok
        info["init_time"] = elapsed
        rep.item("initialize_db()", f"{'نجح' if ok else 'فشل'} في {elapsed:.2f}s",
                 "ok" if ok else "err")
        if not ok:
            return info
    except Exception as e:
        info["init_ok"] = False
        info["error"] = str(e)
        rep.item("initialize_db()", f"استثناء: {e}", "err")
        return info

    # اختبار استعلام بسيط
    try:
        t0 = time.monotonic()
        result = await db.fetchval("SELECT 1 AS x", default=None)
        elapsed = time.monotonic() - t0
        info["ping_ms"] = elapsed * 1000
        rep.item("SELECT 1", f"نجح ({elapsed * 1000:.1f}ms)", "ok")
    except Exception as e:
        rep.item("SELECT 1", f"فشل: {e}", "err")

    # اختبار العدّاد
    try:
        info["open_count"] = db._sqlite_open_count
        info["pool_size"] = db._sqlite_pool_size
        if db._pool is not None:
            info["pool_type"] = type(db._pool).__name__
            rep.item("نوع الـ Pool", info["pool_type"], "ok")
        if db._sqlite_queue is not None:
            info["queue_size"] = db._sqlite_queue.qsize()
            rep.item("طابور SQLite", f"{info['queue_size']}/{info['pool_size']}", "ok")
    except Exception as e:
        rep.item("فحص الـ Pool", f"خطأ: {e}", "warn")

    return info


# ═══════════════════════════════════════════════════════════════════
# 4. فحص الجداول
# ═══════════════════════════════════════════════════════════════════
EXPECTED_TABLES = [
    "schema_version", "users", "user_channels", "posts", "schedule", "last_publish",
    "bot_groups", "user_groups_link", "group_admins", "hidden_owner_groups",
    "hidden_admins", "anonymous_admins", "group_security", "chat_locks",
    "banned_words", "auto_replies", "auto_reply_settings", "support_tickets",
    "bot_admins", "settings", "referrals", "referral_rewards",
    "user_reminder_settings", "user_translation", "contests",
    "contest_participants", "contest_winners", "admin_logs", "user_warnings",
    "user_violations", "group_rules", "user_messages", "scheduled_posts",
    "sentiment_history", "plans", "subscriptions", "invoices", "payment_logs",
    "user_penalties", "violation_penalties", "gift_codes", "user_points",
    "penalty_archive",
]


async def check_tables(rep: Report, db) -> Dict[str, Any]:
    rep.section("4. الجداول")
    info = {"present": [], "missing": []}

    from database import DB_TYPE, USE_POSTGRES, USE_MYSQL

    try:
        if USE_POSTGRES:
            rows = await db.fetchall(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
            present = {r["table_name"] for r in rows}
        elif USE_MYSQL:
            rows = await db.fetchall("SHOW TABLES")
            present = set()
            for r in rows:
                present.update(r.values())
        else:
            rows = await db.fetchall(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            present = {r["name"] for r in rows}

        for t in EXPECTED_TABLES:
            if t in present:
                info["present"].append(t)
            else:
                info["missing"].append(t)

        rep.item("عدد الجداول المتوقعة", len(EXPECTED_TABLES), "info")
        rep.item("عدد الجداول الموجودة", len(info["present"]),
                 "ok" if not info["missing"] else "warn")
        if info["missing"]:
            rep.item("جداول مفقودة", ", ".join(info["missing"]), "err")

        # جداول زائدة
        extra = present - set(EXPECTED_TABLES)
        if extra:
            rep.item("جداول إضافية", ", ".join(sorted(extra)), "info")
    except Exception as e:
        rep.item("فحص الجداول", f"خطأ: {e}", "err")
        info["error"] = str(e)

    return info


# ═══════════════════════════════════════════════════════════════════
# 5. فحص الفهارس
# ═══════════════════════════════════════════════════════════════════
async def check_indexes(rep: Report, db) -> Dict[str, Any]:
    rep.section("5. الفهارس")
    info = {"present": [], "missing": []}

    try:
        from database_tables import COMMON_INDEXES
        from database import USE_POSTGRES, USE_MYSQL

        # اجمع أسماء الفهارس الموجودة
        if USE_POSTGRES:
            rows = await db.fetchall(
                "SELECT indexname FROM pg_indexes WHERE schemaname='public'"
            )
            present = {r["indexname"] for r in rows}
        elif USE_MYSQL:
            rows = await db.fetchall(
                "SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE()"
            )
            present = {r["INDEX_NAME"] for r in rows}
        else:
            rows = await db.fetchall(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
            present = {r["name"] for r in rows}

        for _, idx_name, _ in COMMON_INDEXES:
            if idx_name in present:
                info["present"].append(idx_name)
            else:
                info["missing"].append(idx_name)

        total = len(COMMON_INDEXES)
        rep.item("إجمالي الفهارس المتوقعة", total, "info")
        rep.item("فهارس موجودة", len(info["present"]),
                 "ok" if not info["missing"] else "warn")
        if info["missing"]:
            # اطبع أول 10 فقط
            shown = info["missing"][:10]
            extra = f" (+{len(info['missing']) - 10} أخرى)" if len(info["missing"]) > 10 else ""
            rep.item("فهارس مفقودة", ", ".join(shown) + extra, "warn")
    except Exception as e:
        rep.item("فحص الفهارس", f"خطأ: {e}", "err")
        info["error"] = str(e)

    return info


# ═══════════════════════════════════════════════════════════════════
# 6. فحص الكاش
# ═══════════════════════════════════════════════════════════════════
async def check_cache(rep: Report) -> Dict[str, Any]:
    rep.section("6. نظام الكاش")
    info = {}

    try:
        import cache
        info["mode"] = "real"
        rep.item("الوضع", "cache.py الحقيقي", "ok")
    except ImportError:
        info["mode"] = "fallback"
        rep.item("الوضع", "fallback داخلي", "warn")

    try:
        from database import (
            user_cache, banned_words_cache, settings_cache,
            channels_cache, groups_cache, auth_cache, posts_cache,
            internal_cache, get_cache_stats,
        )

        caches = {
            "user_cache": user_cache,
            "banned_words_cache": banned_words_cache,
            "settings_cache": settings_cache,
            "channels_cache": channels_cache,
            "groups_cache": groups_cache,
            "auth_cache": auth_cache,
            "posts_cache": posts_cache,
            "internal_cache": internal_cache,
        }

        info["caches"] = {}
        for name, obj in caches.items():
            try:
                if hasattr(obj, "get_stats"):
                    stats = await obj.get_stats()
                elif hasattr(obj, "get_size"):
                    stats = {"size": await obj.get_size()}
                else:
                    stats = {"size": len(getattr(obj, "_cache", {}))}
                info["caches"][name] = stats
                rep.item(f"كاش {name}", f"size={stats.get('size', '?')}", "ok")
            except Exception as e:
                rep.item(f"كاش {name}", f"خطأ: {e}", "warn")

        # اختبار كتابة/قراءة
        try:
            await internal_cache.set("__health_check__", "test_value", ttl=5)
            val = await internal_cache.get("__health_check__")
            if val == "test_value":
                rep.item("اختبار internal_cache", "قراءة/كتابة تعمل", "ok")
            else:
                rep.item("اختبار internal_cache", f"قيمة غير متوقعة: {val}", "err")
            await internal_cache.invalidate("__health_check__")
        except Exception as e:
            rep.item("اختبار internal_cache", f"فشل: {e}", "err")

        # إحصائيات شاملة
        try:
            stats = await get_cache_stats()
            info["global_stats"] = stats
            rep.item("get_cache_stats()", "متاح", "ok")
        except Exception as e:
            rep.item("get_cache_stats()", f"خطأ: {e}", "warn")
    except Exception as e:
        rep.item("فحص الكاشات", f"خطأ: {e}", "err")
        info["error"] = str(e)

    return info


# ═══════════════════════════════════════════════════════════════════
# 7. فحص المهام الخلفية
# ═══════════════════════════════════════════════════════════════════
def check_tasks(rep: Report, db) -> Dict[str, Any]:
    rep.section("7. المهام الخلفية")
    info = {}

    tasks = {
        "_cleanup_task":       getattr(db, "_cleanup_task", None),
        "_secondary_index_task": getattr(db, "_secondary_index_task", None),
        "_cache_cleanup_task": getattr(db, "_cache_cleanup_task", None),
    }

    for name, task in tasks.items():
        if task is None:
            rep.item(name, "غير مُنشأة", "warn")
            info[name] = "none"
        elif task.done():
            if task.cancelled():
                rep.item(name, "ملغاة", "warn")
                info[name] = "cancelled"
            else:
                exc = task.exception()
                rep.item(name, f"انتهت (exc: {exc})", "err")
                info[name] = f"done: {exc}"
        else:
            rep.item(name, "تعمل", "ok")
            info[name] = "running"

    return info


# ═══════════════════════════════════════════════════════════════════
# 8. فحص الأقفال
# ═══════════════════════════════════════════════════════════════════
def check_locks(rep: Report, db) -> Dict[str, Any]:
    rep.section("8. الأقفال")
    info = {}

    try:
        info["user_locks_count"] = len(db._user_locks)
        info["user_locks_max"] = db._MAX_USER_LOCKS
        rep.item("أقفال المستخدمين", f"{info['user_locks_count']}/{info['user_locks_max']}",
                 "ok" if info["user_locks_count"] < info["user_locks_max"] * 0.8 else "warn")

        info["channel_locks"] = len(db._channel_locks)
        rep.item("أقفال القنوات", info["channel_locks"], "ok")

        info["group_locks"] = len(db._group_locks)
        rep.item("أقفال المجموعات", info["group_locks"], "ok")

        info["last_access_user"] = len(db._user_locks_last_access)
        rep.item("سجل آخر وصول", info["last_access_user"], "info")
    except Exception as e:
        rep.item("فحص الأقفال", f"خطأ: {e}", "warn")

    return info


# ═══════════════════════════════════════════════════════════════════
# 9. اختبار CRUD فعلي
# ═══════════════════════════════════════════════════════════════════
TEST_USER_ID = 999_999_999_999


async def check_crud(rep: Report, db) -> Dict[str, Any]:
    rep.section("9. اختبار CRUD فعلي")
    info = {"steps": {}}

    # تنظيف مسبق
    try:
        await db.execute("DELETE FROM users WHERE user_id = ?", (TEST_USER_ID,))
    except Exception:
        pass

    # 1) INSERT / register_user
    try:
        ok = await db.register_user(TEST_USER_ID, "health_check", "HealthCheck")
        info["steps"]["register_user"] = ok
        rep.item("register_user()", "نجح" if ok else "فشل", "ok" if ok else "err")
    except Exception as e:
        info["steps"]["register_user"] = str(e)
        rep.item("register_user()", f"استثناء: {e}", "err")
        return info

    # 2) SELECT
    try:
        user = await db.get_user(TEST_USER_ID)
        exists = user is not None
        info["steps"]["get_user"] = exists
        rep.item("get_user()", "نجح" if exists else "لم يُعثر عليه",
                 "ok" if exists else "err")
    except Exception as e:
        rep.item("get_user()", f"استثناء: {e}", "err")

    # 3) UPDATE
    try:
        ok = await db.set_user_language(TEST_USER_ID, "en")
        info["steps"]["set_user_language"] = ok
        lang = await db.get_user_language(TEST_USER_ID)
        rep.item("set_user_language()", f"تم → lang={lang}",
                 "ok" if ok and lang == "en" else "warn")
    except Exception as e:
        rep.item("set_user_language()", f"استثناء: {e}", "err")

    # 4) Referral code
    try:
        code = await db.get_referral_code(TEST_USER_ID)
        info["steps"]["referral_code"] = code
        rep.item("get_referral_code()", code[:20] + "..." if code else "لا يوجد",
                 "ok" if code else "warn")
    except Exception as e:
        rep.item("get_referral_code()", f"استثناء: {e}", "err")

    # 5) Settings
    try:
        await db.set_setting("__health_check_key__", "test_value_42")
        val = await db.get_setting("__health_check_key__")
        info["steps"]["settings"] = val
        rep.item("set/get_setting()", f"قراءة: {val}",
                 "ok" if val == "test_value_42" else "err")
        await db.set_setting("__health_check_key__", "")
    except Exception as e:
        rep.item("set/get_setting()", f"استثناء: {e}", "err")

    # 6) DELETE
    try:
        n = await db.execute("DELETE FROM users WHERE user_id = ?", (TEST_USER_ID,))
        info["steps"]["delete"] = n
        rep.item("DELETE user", f"حُذف {n} صف", "ok" if n >= 1 else "warn")
    except Exception as e:
        rep.item("DELETE user", f"استثناء: {e}", "err")

    return info


# ═══════════════════════════════════════════════════════════════════
# 10. اختبار المعاملات
# ═══════════════════════════════════════════════════════════════════
async def check_transactions(rep: Report, db) -> Dict[str, Any]:
    rep.section("10. اختبار المعاملات (Rollback)")
    info = {}

    try:
        # محاولة معاملة تفشل عمداً
        try:
            async with db.transaction() as conn:
                await db._execute_with_conn(
                    conn, "INSERT INTO settings (key, value) VALUES (?, ?)",
                    "__tx_test__", "should_rollback",
                )
                raise RuntimeError("intentional rollback")
        except RuntimeError:
            pass  # متوقع

        val = await db.get_setting("__tx_test__")
        if val is None:
            rep.item("ROLLBACK", "نجح — لم تُحفظ البيانات", "ok")
            info["rollback"] = "ok"
        else:
            rep.item("ROLLBACK", f"فشل — القيمة موجودة: {val}", "err")
            info["rollback"] = "failed"
            await db.set_setting("__tx_test__", "")

        # معاملة ناجحة
        try:
            async with db.transaction() as conn:
                await db._execute_with_conn(
                    conn, "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    "__tx_test2__", "committed",
                )
            val2 = await db.get_setting("__tx_test2__")
            info["commit"] = val2
            rep.item("COMMIT", f"نجح — value={val2}",
                     "ok" if val2 == "committed" else "err")
            # تنظيف
            await db.execute("DELETE FROM settings WHERE key = ?", ("__tx_test2__",))
        except Exception as e:
            rep.item("COMMIT", f"فشل: {e}", "err")
    except Exception as e:
        rep.item("اختبار المعاملات", f"خطأ عام: {e}", "err")

    return info


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════
async def run_health_check(verbose: bool = False) -> Tuple[Report, Dict]:
    rep = Report()
    all_info: Dict[str, Any] = {}

    # 1-2: متزامن
    all_info["environment"] = check_environment(rep)
    all_info["imports"] = check_imports(rep)

    if not all_info["imports"].get("database"):
        return rep, all_info

    # استيراد DB
    from database import DB

    # 3+: غير متزامن
    all_info["connection"] = await check_connection(rep, DB)
    if not all_info["connection"].get("init_ok"):
        return rep, all_info

    all_info["tables"] = await check_tables(rep, DB)
    all_info["indexes"] = await check_indexes(rep, DB)
    all_info["cache"] = await check_cache(rep)
    all_info["tasks"] = check_tasks(rep, DB)
    all_info["locks"] = check_locks(rep, DB)
    all_info["crud"] = await check_crud(rep, DB)
    all_info["transactions"] = await check_transactions(rep, DB)

    # إغلاق نظيف
    try:
        await DB.close()
    except Exception:
        pass

    # حساب الملخص
    ok = warn = err = 0
    for sec in rep.sections:
        for it in sec.get("items", []):
            s = it.get("status", "info")
            if s == "ok": ok += 1
            elif s == "warn": warn += 1
            elif s == "err": err += 1
    rep.summary(ok, warn, err)

    return rep, all_info


def main():
    parser = argparse.ArgumentParser(description="فحص صحة نظام قاعدة البيانات")
    parser.add_argument("--verbose", "-v", action="store_true", help="تفاصيل إضافية")
    parser.add_argument("--json", action="store_true", help="إخراج JSON")
    args = parser.parse_args()

    if args.json:
        # وضع JSON: أوقف الطباعة
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rep, info = asyncio.run(run_health_check(args.verbose))
        print(json.dumps(info, ensure_ascii=False, indent=2, default=str))
    else:
        asyncio.run(run_health_check(args.verbose))


if __name__ == "__main__":
    main()