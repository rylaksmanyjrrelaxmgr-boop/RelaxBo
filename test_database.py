#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_database.py - اختبار شامل لقاعدة البيانات
================================================================================
يختبر كل الدوال في الملفات التالية:
  - database.py
  - database_groups.py
  - database_tickets.py
  - database_contests.py
  - database_stats.py
  - database_settings.py
  - database_channels_posts.py (إن وجد)
  - database_subscriptions.py (إن وجد)

🚀 التشغيل:
    python test_database.py

📌 المتوقع:
    ✅ كل الاختبارات تنجح بدون أخطاء
"""

import asyncio
import sys
import logging
import traceback
from datetime import datetime, timedelta

# ═══════════════════════════════════════════════════════════════════
# إعداد الـ logging (تقليل الضوضاء)
# ═══════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("aiohttp").setLevel(logging.ERROR)
logging.getLogger("aiosqlite").setLevel(logging.ERROR)

# ═══════════════════════════════════════════════════════════════════
# الألوان
# ═══════════════════════════════════════════════════════════════════

class Color:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    END = "\033[0m"

# ═══════════════════════════════════════════════════════════════════
# عدّادات
# ═══════════════════════════════════════════════════════════════════

class Stats:
    def __init__(self):
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []

    def report(self):
        print()
        print(f"{Color.BOLD}{'═' * 70}{Color.END}")
        print(f"{Color.BOLD}📊 ملخص النتائج{Color.END}")
        print(f"{Color.BOLD}{'═' * 70}{Color.END}")
        print(f"  📌 الإجمالي:     {self.total}")
        print(f"  {Color.GREEN}✅ نجح:         {self.passed}{Color.END}")
        print(f"  {Color.RED}❌ فشل:         {self.failed}{Color.END}")
        print(f"  {Color.YELLOW}⏭️  تم تخطيه:    {self.skipped}{Color.END}")

        if self.errors:
            print()
            print(f"{Color.RED}{Color.BOLD}⚠️ تفاصيل الأخطاء:{Color.END}")
            for name, err in self.errors:
                print(f"  {Color.RED}❌ {name}: {err}{Color.END}")
            print()

        if self.failed == 0:
            print(f"{Color.GREEN}{Color.BOLD}🎉 كل الاختبارات نجحت!{Color.END}")
        else:
            print(f"{Color.RED}{Color.BOLD}⚠️ هناك {self.failed} فشل يجب معالجته{Color.END}")
        print(f"{Color.BOLD}{'═' * 70}{Color.END}")
        print()


stats = Stats()


# ═══════════════════════════════════════════════════════════════════
# Decorator للاختبار
# ═══════════════════════════════════════════════════════════════════

def test(name, skip=False):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            stats.total += 1
            prefix = f"  [{stats.total:3d}]"

            if skip:
                print(f"{prefix} {Color.YELLOW}⏭️  {name} (تم تخطيه){Color.END}")
                stats.skipped += 1
                return None

            try:
                result = await func(*args, **kwargs)
                if result is False:
                    print(f"{prefix} {Color.RED}❌ {name}{Color.END}")
                    stats.failed += 1
                    stats.errors.append((name, "returned False"))
                else:
                    print(f"{prefix} {Color.GREEN}✅ {name}{Color.END}")
                    stats.passed += 1
                return result
            except Exception as e:
                print(f"{prefix} {Color.RED}❌ {name}: {e}{Color.END}")
                stats.failed += 1
                stats.errors.append((name, str(e)))
                return None
        return wrapper
    return decorator


def section(title):
    print()
    print(f"{Color.CYAN}{Color.BOLD}🔷 {title}{Color.END}")
    print(f"{Color.CYAN}{'─' * 70}{Color.END}")


# ═══════════════════════════════════════════════════════════════════
# الاختبارات
# ═══════════════════════════════════════════════════════════════════

async def run_all_tests():
    """يُشغّل كل الاختبارات"""

    print()
    print(f"{Color.BOLD}{'═' * 70}{Color.END}")
    print(f"{Color.BOLD}🧪 اختبار شامل لقاعدة البيانات{Color.END}")
    print(f"{Color.BOLD}{'═' * 70}{Color.END}")

    # ═════════════════════════════════════════════════════════════
    # 1) التحقق من الاستيراد
    # ═════════════════════════════════════════════════════════════

    section("1) التحقق من الاستيراد والـ Mixins")

    try:
        from database import (
            DB,
            ChannelsPostsMixin,
            SubscriptionsMixin,
            GroupsMixin,
            TicketsMixin,
            ContestsMixin,
            StatsMixin,
            SettingsMixin,
        )
        print(f"  ✅ تم استيراد كل الـ Mixins")
        stats.total += 1
        stats.passed += 1
    except ImportError as e:
        print(f"  {Color.RED}❌ فشل الاستيراد: {e}{Color.END}")
        stats.total += 1
        stats.failed += 1
        stats.errors.append(("Import", str(e)))
        return

    # ═════════════════════════════════════════════════════════════
    # 2) التحقق من الوراثة
    # ═════════════════════════════════════════════════════════════

    section("2) التحقق من الوراثة (MRO)")

    @test("Database يرث من ChannelsPostsMixin")
    async def t():
        return isinstance(DB, ChannelsPostsMixin)

    @test("Database يرث من SubscriptionsMixin")
    async def t():
        return isinstance(DB, SubscriptionsMixin)

    @test("Database يرث من GroupsMixin")
    async def t():
        return isinstance(DB, GroupsMixin)

    @test("Database يرث من TicketsMixin")
    async def t():
        return isinstance(DB, TicketsMixin)

    @test("Database يرث من ContestsMixin")
    async def t():
        return isinstance(DB, ContestsMixin)

    @test("Database يرث من StatsMixin")
    async def t():
        return isinstance(DB, StatsMixin)

    @test("Database يرث من SettingsMixin")
    async def t():
        return isinstance(DB, SettingsMixin)

    await t()

    # ═════════════════════════════════════════════════════════════
    # 3) التهيئة
    # ═════════════════════════════════════════════════════════════

    section("3) تهيئة قاعدة البيانات")

    @test("initialize_db()")
    async def t():
        result = await DB.initialize_db()
        return result is True

    @test("نوع قاعدة البيانات")
    async def t():
        print(f"       📌 النوع: {Color.BOLD}{DB.DB_TYPE.upper()}{Color.END}")
        return DB.DB_TYPE in ("sqlite", "postgres", "mysql")

    await t()

    # ═════════════════════════════════════════════════════════════
    # 4) دوال الوقت
    # ═════════════════════════════════════════════════════════════

    section("4) TimeUtils")

    @test("utc_now()")
    async def t():
        dt = DB.TimeUtils.utc_now()
        return isinstance(dt, datetime) and dt.tzinfo is None

    @test("mecca_now()")
    async def t():
        dt = DB.TimeUtils.mecca_now()
        return isinstance(dt, datetime)

    @test("sql_iso()")
    async def t():
        s = DB.TimeUtils.sql_iso()
        return isinstance(s, str) and len(s) > 10

    @test("safe_parse_iso()")
    async def t():
        dt = DB.TimeUtils.safe_parse_iso("2026-09-10 21:44:35")
        return isinstance(dt, datetime)

    @test("safe_parse_iso() مع None")
    async def t():
        return DB.TimeUtils.safe_parse_iso(None) is None

    await t()

    # ═════════════════════════════════════════════════════════════
    # 5) دوال الاستعلام الأساسية
    # ═════════════════════════════════════════════════════════════

    section("5) دوال الاستعلام (execute/fetchone/fetchall/fetchval)")

    TEST_USER = 999900001
    TEST_CHAT = -999900001

    @test("execute() - INSERT/UPDATE")
    async def t():
        r = await DB.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (TEST_USER, "test_user")
        )
        return r >= 0

    @test("fetchone()")
    async def t():
        row = await DB.fetchone(
            "SELECT user_id, username FROM users WHERE user_id = ?",
            (TEST_USER,)
        )
        return row is not None and row.get("user_id") == TEST_USER

    @test("fetchall()")
    async def t():
        rows = await DB.fetchall(
            "SELECT user_id FROM users WHERE user_id = ?", (TEST_USER,)
        )
        return isinstance(rows, list) and len(rows) >= 1

    @test("fetchval()")
    async def t():
        val = await DB.fetchval(
            "SELECT username FROM users WHERE user_id = ?", (TEST_USER,)
        )
        return val == "test_user"

    @test("fetchval() مع default")
    async def t():
        val = await DB.fetchval(
            "SELECT username FROM users WHERE user_id = ?",
            (123456789,),
            default="not_found"
        )
        return val == "not_found"

    @test("executemany()")
    async def t():
        r = await DB.executemany(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            [(999900002, "u2"), (999900003, "u3")]
        )
        return r >= 0

    @test("connection() context manager")
    async def t():
        async with DB.connection() as conn:
            cursor = await conn.execute("SELECT 1")
            row = await cursor.fetchone()
            return row is not None

    @test("transaction() context manager")
    async def t():
        async with DB.transaction() as conn:
            await DB._execute_with_conn(
                conn, "UPDATE users SET username = ? WHERE user_id = ?",
                "test_user_tx", TEST_USER
            )
        row = await DB.fetchone("SELECT username FROM users WHERE user_id = ?", (TEST_USER,))
        return row and row.get("username") == "test_user_tx"

    await t()

    # ═════════════════════════════════════════════════════════════
    # 6) دوال المستخدمين
    # ═════════════════════════════════════════════════════════════

    section("6) دوال المستخدمين (database.py)")

    @test("register_user()")
    async def t():
        return await DB.register_user(TEST_USER, "test_user", "Test")

    @test("get_user()")
    async def t():
        u = await DB.get_user(TEST_USER)
        return u is not None and u.get("user_id") == TEST_USER

    @test("get_user_full_data()")
    async def t():
        u = await DB.get_user_full_data(TEST_USER)
        return u is not None and "channel_info" in u

    @test("set_user_language()")
    async def t():
        return await DB.set_user_language(TEST_USER, "ar")

    @test("get_user_language()")
    async def t():
        return await DB.get_user_language(TEST_USER) == "ar"

    @test("get_auto_publish_status()")
    async def t():
        return isinstance(await DB.get_auto_publish_status(TEST_USER), bool)

    @test("set_auto_publish()")
    async def t():
        return await DB.set_auto_publish(TEST_USER, True)

    @test("get_auto_recycle_status()")
    async def t():
        return isinstance(await DB.get_auto_recycle_status(TEST_USER), bool)

    @test("set_auto_recycle()")
    async def t():
        return await DB.set_auto_recycle(TEST_USER, True)

    @test("is_user_banned()")
    async def t():
        return isinstance(await DB.is_user_banned(TEST_USER), bool)

    @test("ban_user() + unban_user()")
    async def t():
        ok1 = await DB.ban_user(TEST_USER)
        ok2 = await DB.unban_user(TEST_USER)
        return ok1 and ok2

    @test("get_all_users()")
    async def t():
        users = await DB.get_all_users(limit=10)
        return isinstance(users, list)

    @test("iter_all_users()")
    async def t():
        count = 0
        async for _ in DB.iter_all_users(batch_size=5):
            count += 1
            if count >= 3:
                break
        return count >= 0

    await t()

    # ═════════════════════════════════════════════════════════════
    # 7) دوال المجموعات (GroupsMixin)
    # ═════════════════════════════════════════════════════════════

    section("7) دوال المجموعات (database_groups.py)")

    @test("register_group()")
    async def t():
        return await DB.register_group(TEST_CHAT, "Test Group", TEST_USER)

    @test("get_user_groups()")
    async def t():
        groups = await DB.get_user_groups(TEST_USER)
        return isinstance(groups, list)

    @test("get_security_settings()")
    async def t():
        s = await DB.get_security_settings(TEST_CHAT)
        return isinstance(s, dict)

    @test("update_security_settings()")
    async def t():
        return await DB.update_security_settings(TEST_CHAT, delete_links=1)

    @test("update_security_settings() مع مرادف")
    async def t():
        return await DB.update_security_settings(TEST_CHAT, remove_links=1)

    @test("update_security_settings() مع night_start")
    async def t():
        return await DB.update_security_settings(TEST_CHAT, night_start="22:00")

    @test("get_group_security_columns()")
    async def t():
        cols = await DB.get_group_security_columns()
        return isinstance(cols, set) and len(cols) > 0

    @test("get_penalty_settings()")
    async def t():
        s = await DB.get_penalty_settings(TEST_CHAT)
        return isinstance(s, dict)

    @test("update_penalty_settings()")
    async def t():
        return await DB.update_penalty_settings(TEST_CHAT, mute_default_duration=7200)

    @test("add_banned_word()")
    async def t():
        r = await DB.add_banned_word("__test_bad_word__", TEST_CHAT, TEST_USER)
        return isinstance(r, tuple) and len(r) == 2

    @test("get_banned_words()")
    async def t():
        words = await DB.get_banned_words(TEST_CHAT)
        return isinstance(words, list)

    @test("remove_banned_word()")
    async def t():
        return await DB.remove_banned_word("__test_bad_word__", TEST_CHAT)

    @test("get_auto_reply_settings()")
    async def t():
        s = await DB.get_auto_reply_settings(TEST_CHAT)
        return isinstance(s, dict)

    @test("update_auto_reply_settings()")
    async def t():
        return await DB.update_auto_reply_settings(TEST_CHAT, enabled=1)

    @test("add_auto_reply()")
    async def t():
        return await DB.add_auto_reply(TEST_CHAT, "__test_hi__", "مرحبا")

    @test("get_auto_reply()")
    async def t():
        r = await DB.get_auto_reply("__test_hi__", TEST_CHAT)
        return r is not None

    @test("remove_auto_reply()")
    async def t():
        return await DB.remove_auto_reply(TEST_CHAT, "__test_hi__")

    @test("add_hidden_admin()")
    async def t():
        return await DB.add_hidden_admin(TEST_CHAT, 999888777, TEST_USER)

    @test("get_hidden_admins()")
    async def t():
        admins = await DB.get_hidden_admins(TEST_CHAT)
        return isinstance(admins, list)

    @test("add_anonymous_admin()")
    async def t():
        return await DB.add_anonymous_admin(TEST_CHAT, 111222333, TEST_USER)

    @test("get_anonymous_admins()")
    async def t():
        admins = await DB.get_anonymous_admins(TEST_CHAT)
        return isinstance(admins, list)

    @test("is_anonymous_admin()")
    async def t():
        return isinstance(await DB.is_anonymous_admin(TEST_CHAT, 111222333), bool)

    @test("add_user_warning()")
    async def t():
        count = await DB.add_user_warning(999888777, TEST_CHAT)
        return count >= 1

    @test("get_user_warnings()")
    async def t():
        return await DB.get_user_warnings(999888777, TEST_CHAT) >= 1

    @test("reset_user_warnings()")
    async def t():
        return await DB.reset_user_warnings(999888777, TEST_CHAT)

    @test("add_admin_log()")
    async def t():
        return await DB.add_admin_log(TEST_CHAT, TEST_USER, "test_action")

    @test("get_admin_logs()")
    async def t():
        logs = await DB.get_admin_logs(TEST_CHAT, limit=5)
        return isinstance(logs, list)

    @test("get_violation_penalty()")
    async def t():
        p = await DB.get_violation_penalty(TEST_CHAT, "link")
        return isinstance(p, dict)

    @test("set_violation_penalty()")
    async def t():
        return await DB.set_violation_penalty(TEST_CHAT, "link", "mute", 3600)

    @test("get_all_violation_penalties()")
    async def t():
        p = await DB.get_all_violation_penalties(TEST_CHAT)
        return isinstance(p, dict)

    @test("get_violation_count()")
    async def t():
        return isinstance(await DB.get_violation_count(999888777, TEST_CHAT), int)

    @test("increment_violation_count()")
    async def t():
        c = await DB.increment_violation_count(999888777, TEST_CHAT)
        return c >= 1

    @test("reset_violation_count()")
    async def t():
        return await DB.reset_violation_count(999888777, TEST_CHAT)

    await t()

    # ═════════════════════════════════════════════════════════════
    # 8) دوال التذاكر (TicketsMixin)
    # ═════════════════════════════════════════════════════════════

    section("8) دوال التذاكر (database_tickets.py)")

    @test("create_ticket()")
    async def t():
        num = await DB.create_ticket(TEST_USER, "test_user", "رسالة اختبار")
        return num > 0

    @test("get_tickets()")
    async def t():
        tickets = await DB.get_tickets()
        return isinstance(tickets, list) and len(tickets) >= 1

    @test("close_ticket()")
    async def t():
        tickets = await DB.get_tickets()
        if not tickets:
            return False
        return await DB.close_ticket(tickets[0]["id"])

    @test("delete_all_tickets()")
    async def t():
        return isinstance(await DB.delete_all_tickets(), bool)

    await t()

    # ═════════════════════════════════════════════════════════════
    # 9) دوال المسابقات (ContestsMixin)
    # ═════════════════════════════════════════════════════════════

    section("9) دوال المسابقات (database_contests.py)")

    CONTEST_ID = None

    @test("create_contest()")
    async def t():
        nonlocal CONTEST_ID
        end = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        CONTEST_ID = await DB.create_contest(TEST_USER, "مسابقة اختبار", "وصف", "جائزة", end)
        return CONTEST_ID > 0

    @test("get_active_contests()")
    async def t():
        contests = await DB.get_active_contests()
        return isinstance(contests, list)

    @test("get_contest_by_id()")
    async def t():
        if not CONTEST_ID:
            return False
        c = await DB.get_contest_by_id(CONTEST_ID)
        return c is not None

    @test("check_contest_joined()")
    async def t():
        if not CONTEST_ID:
            return False
        return isinstance(await DB.check_contest_joined(CONTEST_ID, TEST_USER), bool)

    @test("join_contest()")
    async def t():
        if not CONTEST_ID:
            return False
        return await DB.join_contest(CONTEST_ID, TEST_USER, "إجابة")

    @test("declare_winner()")
    async def t():
        if not CONTEST_ID:
            return False
        return await DB.declare_winner(CONTEST_ID, TEST_USER)

    @test("get_contest_winners()")
    async def t():
        w = await DB.get_contest_winners()
        return isinstance(w, list)

    @test("delete_contest()")
    async def t():
        if not CONTEST_ID:
            return False
        return await DB.delete_contest(CONTEST_ID, TEST_USER)

    await t()

    # ═════════════════════════════════════════════════════════════
    # 10) دوال الإحصائيات (StatsMixin)
    # ═════════════════════════════════════════════════════════════

    section("10) دوال الإحصائيات والمشرفين (database_stats.py)")

    @test("get_bot_stats()")
    async def t():
        s = await DB.get_bot_stats()
        return isinstance(s, dict) and "users" in s

    @test("get_general_stats()")
    async def t():
        s = await DB.get_general_stats()
        return isinstance(s, dict) and "invoices" in s

    @test("get_user_stats()")
    async def t():
        s = await DB.get_user_stats()
        return isinstance(s, dict) and "users" in s

    @test("add_admin()")
    async def t():
        return await DB.add_admin(999888777, TEST_USER)

    @test("get_admin_list()")
    async def t():
        a = await DB.get_admin_list()
        return isinstance(a, list)

    @test("remove_admin()")
    async def t():
        return await DB.remove_admin(999888777)

    await t()

    # ═════════════════════════════════════════════════════════════
    # 11) دوال الإعدادات (SettingsMixin)
    # ═════════════════════════════════════════════════════════════

    section("11) دوال الإعدادات العامة (database_settings.py)")

    @test("set_setting()")
    async def t():
        return await DB.set_setting("__test_key__", "__test_value__")

    @test("get_setting()")
    async def t():
        v = await DB.get_setting("__test_key__")
        return v == "__test_value__"

    @test("get_setting() مع default")
    async def t():
        v = await DB.get_setting("__nonexistent__", "default_val")
        return v == "default_val"

    @test("get_force_subscribe_channel()")
    async def t():
        v = await DB.get_force_subscribe_channel()
        return v is None or isinstance(v, str)

    @test("get_updates_channel()")
    async def t():
        v = await DB.get_updates_channel()
        return v is None or isinstance(v, str)

    @test("get_log_channel()")
    async def t():
        v = await DB.get_log_channel()
        return v is None or isinstance(v, str)

    @test("get_publish_interval()")
    async def t():
        v = await DB.get_publish_interval()
        return isinstance(v, int) and v >= 1

    @test("get_auto_backup()")
    async def t():
        return isinstance(await DB.get_auto_backup(), bool)

    await t()

    # ═════════════════════════════════════════════════════════════
    # 12) دوال العقوبات
    # ═════════════════════════════════════════════════════════════

    section("12) دوال العقوبات (database.py)")

    PENALTY_ID = None

    @test("add_penalty()")
    async def t():
        nonlocal PENALTY_ID
        PENALTY_ID = await DB.add_penalty(
            TEST_USER, TEST_CHAT, "mute", 3600, "اختبار", TEST_USER
        )
        return PENALTY_ID is not None and PENALTY_ID > 0

    @test("get_active_penalties()")
    async def t():
        p = await DB.get_active_penalties(TEST_USER)
        return isinstance(p, list)

    @test("get_user_penalty_count()")
    async def t():
        return isinstance(await DB.get_user_penalty_count(TEST_USER, TEST_CHAT), int)

    @test("get_all_active_penalties()")
    async def t():
        return isinstance(await DB.get_all_active_penalties(), list)

    @test("remove_penalties_for_user()")
    async def t():
        return await DB.remove_penalties_for_user(TEST_USER, TEST_CHAT) >= 0

    @test("expire_penalties()")
    async def t():
        return await DB.expire_penalties() >= 0

    await t()

    # ═════════════════════════════════════════════════════════════
    # 13) دوال النقاط
    # ═════════════════════════════════════════════════════════════

    section("13) دوال النقاط (database.py)")

    @test("add_points()")
    async def t():
        p = await DB.add_points(TEST_USER, 100)
        return p >= 100

    @test("get_user_points()")
    async def t():
        return await DB.get_user_points(TEST_USER) >= 100

    @test("get_user_level()")
    async def t():
        return await DB.get_user_level(TEST_USER) >= 1

    @test("get_top_users()")
    async def t():
        return isinstance(await DB.get_top_users(limit=5), list)

    await t()

    # ═════════════════════════════════════════════════════════════
    # 14) دوال التذكيرات
    # ═════════════════════════════════════════════════════════════

    section("14) دوال التذكيرات (database.py)")

    @test("get_reminder_settings()")
    async def t():
        s = await DB.get_reminder_settings(TEST_USER)
        return isinstance(s, dict)

    @test("update_reminder_settings()")
    async def t():
        return await DB.update_reminder_settings(TEST_USER, subscription_reminder=1)

    @test("get_reminder_stats()")
    async def t():
        s = await DB.get_reminder_stats(TEST_USER)
        return isinstance(s, dict)

    @test("is_user_reminder_enabled()")
    async def t():
        return isinstance(await DB.is_user_reminder_enabled(TEST_USER, "subscription"), bool)

    @test("get_users_with_reminder_enabled()")
    async def t():
        return isinstance(await DB.get_users_with_reminder_enabled("subscription"), list)

    @test("update_reminder_sent()")
    async def t():
        return await DB.update_reminder_sent(TEST_USER)

    @test("reset_reminder_settings()")
    async def t():
        return await DB.reset_reminder_settings(TEST_USER)

    await t()

    # ═════════════════════════════════════════════════════════════
    # 15) دوال الجدولة
    # ═════════════════════════════════════════════════════════════

    section("15) دوال الجدولة (database.py)")

    @test("get_schedule()")
    async def t():
        # نحتاج channel_db_id — نستخدم ID من قناة موجودة أو 1
        s = await DB.get_schedule(1)
        return isinstance(s, dict)

    @test("update_schedule()")
    async def t():
        return await DB.update_schedule(1, interval_minutes=15)

    @test("update_last_publish()")
    async def t():
        return await DB.update_last_publish(1)

    @test("update_next_publish()")
    async def t():
        return await DB.update_next_publish(1)

    @test("get_channels_to_publish()")
    async def t():
        return isinstance(await DB.get_channels_to_publish(limit=5), list)

    await t()

    # ═════════════════════════════════════════════════════════════
    # 16) دوال الأقفال
    # ═════════════════════════════════════════════════════════════

    section("16) دوال الأقفال (database.py)")

    @test("_get_user_lock()")
    async def t():
        lock = await DB._get_user_lock(TEST_USER)
        return lock is not None

    @test("_get_group_lock()")
    async def t():
        lock = await DB._get_group_lock(TEST_CHAT)
        return lock is not None

    @test("_get_channel_lock()")
    async def t():
        lock = await DB._get_channel_lock(1)
        return lock is not None

    @test("cleanup_user_locks()")
    async def t():
        return isinstance(await DB.cleanup_user_locks(), int)

    @test("cleanup_group_locks()")
    async def t():
        return isinstance(await DB.cleanup_group_locks(), int)

    @test("cleanup_channel_locks()")
    async def t():
        return isinstance(await DB.cleanup_channel_locks(), int)

    await t()

    # ═════════════════════════════════════════════════════════════
    # 17) الثوابت
    # ═════════════════════════════════════════════════════════════

    section("17) الثوابت (Constants)")

    @test("COLUMN_ALIASES موجودة")
    async def t():
        n = len(DB.COLUMN_ALIASES)
        print(f"       📌 {n} مرادف")
        return n > 50

    @test("VALID_PENALTY_TYPES")
    async def t():
        return len(DB.VALID_PENALTY_TYPES) == 5

    @test("VALID_VIOLATION_TYPES")
    async def t():
        n = len(DB.VALID_VIOLATION_TYPES)
        print(f"       📌 {n} نوع")
        return n > 30

    @test("VALID_REPLY_TYPES")
    async def t():
        return len(DB.VALID_REPLY_TYPES) == 8

    @test("MAX_PENALTY_DURATION")
    async def t():
        return DB.MAX_PENALTY_DURATION == 365 * 86400

    await t()

    # ═════════════════════════════════════════════════════════════
    # 18) تنظيف
    # ═════════════════════════════════════════════════════════════

    section("18) تنظيف بيانات الاختبار")

    @test("حذف المستخدمين التجريبيين")
    async def t():
        await DB.execute("DELETE FROM users WHERE user_id IN (?, ?, ?)",
                         (TEST_USER, 999900002, 999900003))
        return True

    @test("حذف المجموعة التجريبية")
    async def t():
        await DB.delete_group(TEST_CHAT)
        return True

    @test("حذف الإعداد التجريبي")
    async def t():
        await DB.execute("DELETE FROM settings WHERE key = ?", ("__test_key__",))
        return True

    await t()


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

async def main():
    start = datetime.now()
    try:
        await run_all_tests()
    except KeyboardInterrupt:
        print(f"\n{Color.YELLOW}⚠️ تم إيقاف الاختبار{Color.END}")
    except Exception as e:
        print(f"\n{Color.RED}❌ خطأ غير متوقع: {e}{Color.END}")
        traceback.print_exc()
    finally:
        try:
            from database import DB
            await DB.close()
        except Exception:
            pass

    elapsed = (datetime.now() - start).total_seconds()
    stats.report()
    print(f"⏱️  الوقت المستغرق: {elapsed:.2f} ثانية")
    print()

    sys.exit(0 if stats.failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())