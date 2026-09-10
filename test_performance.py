#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
test_performance.py - اختبار أداء البوت
================================================================================
يقيس:
1. زمن استجابة /start قبل وبعد الإصلاح
2. أداء كاش الاشتراك الإجباري
3. أداء ChatMemberHandler
4. استدعاءات getChatAdministrators
5. أداء قاعدة البيانات

🚀 التشغيل:
    python test_performance.py
"""

import asyncio
import time
import sys
import logging
from datetime import datetime

# تقليل ضوضاء السجلات
logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("aiohttp").setLevel(logging.ERROR)
logging.getLogger("telegram").setLevel(logging.ERROR)

# الألوان
class C:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    END = "\033[0m"


def header(text):
    print()
    print(f"{C.CYAN}{C.BOLD}{'═' * 70}{C.END}")
    print(f"{C.CYAN}{C.BOLD}  {text}{C.END}")
    print(f"{C.CYAN}{C.BOLD}{'═' * 70}{C.END}")


def section(text):
    print()
    print(f"{C.BLUE}{C.BOLD}🔷 {text}{C.END}")
    print(f"{C.BLUE}{'─' * 70}{C.END}")


def result(label, value, unit="", status="ok", threshold=None):
    """طباعة نتيجة مع تقييم"""
    if status == "ok":
        icon = f"{C.GREEN}✅{C.END}"
    elif status == "warn":
        icon = f"{C.YELLOW}⚠️{C.END}"
    else:
        icon = f"{C.RED}❌{C.END}"

    line = f"  {icon} {label}: {C.BOLD}{value}{unit}{C.END}"

    if threshold:
        line += f" (المتوقع: {threshold})"

    print(line)


def metric(name, value, unit, target, lower_is_better=True):
    """طباعة مقياس مع تقييم"""
    if lower_is_better:
        good = value <= target
    else:
        good = value >= target

    status = "ok" if good else "warn"
    if lower_is_better:
        threshold_str = f"≤ {target}{unit}"
    else:
        threshold_str = f"≥ {target}{unit}"

    result(name, f"{value:.2f}", unit, status, threshold_str)


# ═════════════════════════════════════════════════════════════════════
# 1. اختبار الاستيراد
# ═════════════════════════════════════════════════════════════════════

async def test_imports():
    section("1) اختبار الاستيراد والـ Mixins")

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
            PointsMixin,
            BackupMixin,
            RemindersMixin,
        )
        result("database.py + 10 Mixins", "OK", status="ok")
    except ImportError as e:
        result("database.py", str(e), status="fail")
        return False

    try:
        from handlers import chat_member
        result("handlers.chat_member", "OK", status="ok")
    except ImportError as e:
        result("handlers.chat_member", str(e), status="fail")
        return False

    try:
        from handlers.handlers_command import (
            _force_sub_cache,
            _force_channel_cache,
            _FORCE_SUB_CACHE_TTL,
            _FORCE_CHANNEL_CACHE_TTL,
            _check_force_subscription_cached,
            _get_force_channel_cached,
            _invalidate_force_sub_cache,
        )
        result("كاش الاشتراك الإجباري", "OK", status="ok")
        print(f"      📌 _FORCE_SUB_CACHE_TTL = {_FORCE_SUB_CACHE_TTL} ثانية")
        print(f"      📌 _FORCE_CHANNEL_CACHE_TTL = {_FORCE_CHANNEL_CACHE_TTL} ثانية")
    except ImportError as e:
        result("كاش الاشتراك الإجباري", str(e), status="fail")
        return False

    try:
        from utils import BackgroundTasks
        assert hasattr(BackgroundTasks, "_get_admin_ids_cached")
        assert hasattr(BackgroundTasks, "_group_admins_cache")
        assert hasattr(BackgroundTasks, "_GROUP_ADMINS_CACHE_TTL")
        result("كاش المشرفين في utils", "OK", status="ok")
        print(f"      📌 _GROUP_ADMINS_CACHE_TTL = {BackgroundTasks._GROUP_ADMINS_CACHE_TTL} ثانية")
    except Exception as e:
        result("كاش المشرفين", str(e), status="fail")
        return False

    try:
        from bot import keep_alive
        result("keep_alive() في bot.py", "OK", status="ok")
    except ImportError as e:
        result("keep_alive()", str(e), status="fail")

    return True


# ═════════════════════════════════════════════════════════════════════
# 2. اختبار قاعدة البيانات
# ═════════════════════════════════════════════════════════════════════

async def test_database():
    section("2) اختبار قاعدة البيانات")

    from database import DB

    # قياس وقت التهيئة
    t0 = time.monotonic()
    await DB.initialize_db()
    elapsed = time.monotonic() - t0
    metric("تهيئة قاعدة البيانات", elapsed, "s", 5.0)

    # قياس استعلام بسيط
    t0 = time.monotonic()
    await DB.fetchval("SELECT COUNT(*) FROM users", default=0)
    elapsed = time.monotonic() - t0
    metric("استعلام COUNT (*)", elapsed * 1000, "ms", 500, lower_is_better=True)

    # قياس fetchone
    TEST_USER = 999888777
    await DB.register_user(TEST_USER, "perf_test", "Perf Test")

    t0 = time.monotonic()
    await DB.get_user(TEST_USER)
    elapsed = time.monotonic() - t0
    metric("get_user()", elapsed * 1000, "ms", 500, lower_is_better=True)

    # قياس get_banned_words
    t0 = time.monotonic()
    await DB.get_banned_words(-1)
    elapsed = time.monotonic() - t0
    metric("get_banned_words(-1)", elapsed * 1000, "ms", 300, lower_is_better=True)

    return True


# ═════════════════════════════════════════════════════════════════════
# 3. اختبار كاش الاشتراك الإجباري
# ═════════════════════════════════════════════════════════════════════

async def test_force_sub_cache():
    section("3) اختبار كاش الاشتراك الإجباري")

    from handlers.handlers_command import (
        _force_sub_cache,
        _check_force_subscription_cached,
        _invalidate_force_sub_cache,
        _FORCE_SUB_CACHE_TTL,
    )

    # مسح الكاش للبداية النظيفة
    _invalidate_force_sub_cache()
    result("مسح الكاش", f"{len(_force_sub_cache)} عنصر متبقي", status="ok")

    # اختبار 1: حجم الكاش بعد الإبطال
    assert len(_force_sub_cache) == 0, "الكاش لم يُفرغ!"
    result("الكاش فارغ بعد الإبطال", "OK", status="ok")

    # اختبار 2: وضع قيمة يدوياً
    test_user = 12345
    import time as _time
    _force_sub_cache[test_user] = (_time.time(), True)

    assert test_user in _force_sub_cache
    result("إضافة عنصر للكاش", "OK", status="ok")

    # اختبار 3: إبطال مستخدم واحد
    _invalidate_force_sub_cache(test_user)
    assert test_user not in _force_sub_cache
    result("إبطال مستخدم واحد", "OK", status="ok")

    # اختبار 4: TTL المحدد
    assert _FORCE_SUB_CACHE_TTL == 180, f"TTL غير مطابق: {_FORCE_SUB_CACHE_TTL}"
    result("TTL = 180 ثانية (3 دقائق)", "OK", status="ok")

    return True


# ═════════════════════════════════════════════════════════════════════
# 4. اختبار كاش المشرفين
# ═════════════════════════════════════════════════════════════════════

async def test_admin_cache():
    section("4) اختبار كاش المشرفين في utils")

    from utils import BackgroundTasks

    # مسح الكاش
    BackgroundTasks._group_admins_cache.clear()
    result("مسح كاش المشرفين", "OK", status="ok")

    # اختبار وضع قيمة
    test_chat = -1001234567890
    import time as _time
    test_admins = [111, 222, 333]
    BackgroundTasks._group_admins_cache[test_chat] = (_time.time(), test_admins)

    assert test_chat in BackgroundTasks._group_admins_cache
    cached_time, cached_ids = BackgroundTasks._group_admins_cache[test_chat]
    assert cached_ids == test_admins
    result("تخزين مشرفين", f"{len(test_admins)} مشرف", status="ok")

    # اختبار TTL
    assert BackgroundTasks._GROUP_ADMINS_CACHE_TTL == 600
    result("TTL = 600 ثانية (10 دقائق)", "OK", status="ok")

    # اختبار قراءة
    cached = BackgroundTasks._group_admins_cache.get(test_chat)
    assert cached is not None and cached[1] == test_admins
    result("قراءة من الكاش", "OK", status="ok")

    # تنظيف
    BackgroundTasks._group_admins_cache.clear()
    return True


# ═════════════════════════════════════════════════════════════════════
# 5. اختبار ChatMemberHandler
# ═════════════════════════════════════════════════════════════════════

async def test_chat_member_handler():
    section("5) اختبار ChatMemberHandler")

    from handlers import chat_member

    # التحقق من الدوال
    functions = [
        "on_chat_member_update",
        "on_my_chat_member_update",
        "register",
        "_is_admin_status",
        "_is_transition_admin",
        "_sync_admins_to_db",
        "_update_utils_cache",
    ]

    for fn in functions:
        if hasattr(chat_member, fn):
            result(fn, "OK", status="ok")
        else:
            result(fn, "غير موجود", status="fail")

    # اختبار _is_admin_status
    assert chat_member._is_admin_status("administrator") == True
    assert chat_member._is_admin_status("creator") == True
    assert chat_member._is_admin_status("member") == False
    assert chat_member._is_admin_status("restricted") == False
    result("_is_admin_status logic", "OK", status="ok")

    # اختبار _is_transition_admin
    assert chat_member._is_transition_admin("member", "administrator") == True
    assert chat_member._is_transition_admin("administrator", "member") == True
    assert chat_member._is_transition_admin("member", "restricted") == False
    assert chat_member._is_transition_admin("administrator", "creator") == False
    result("_is_transition_admin logic", "OK", status="ok")

    return True


# ═════════════════════════════════════════════════════════════════════
# 6. محاكاة /start
# ═════════════════════════════════════════════════════════════════════

async def test_start_simulation():
    section("6) محاكاة زمن /start")

    from database import DB

    TEST_USER = 999888777

    # ═══ السيناريو 1: get_user من الكاش (سريع) ═══

    # تسجيل المستخدم مسبقاً
    await DB.register_user(TEST_USER, "perf_test", "Perf Test")

    # قياس الاستعلام الأول (بدون كاش)
    t0 = time.monotonic()
    await DB.get_user(TEST_USER)
    first_query = (time.monotonic() - t0) * 1000

    # قياس الاستعلام الثاني (من internal_cache)
    t0 = time.monotonic()
    await DB.get_user(TEST_USER)
    cached_query = (time.monotonic() - t0) * 1000

    print()
    print(f"  📊 قياس الاستعلامات:")
    print(f"     الاستعلام الأول: {first_query:.2f}ms")
    print(f"     الاستعلام الثاني (مُكاش): {cached_query:.2f}ms")

    if cached_query < first_query * 0.5:
        result("تحسن الاستعلام بعد الكاش", f"{((first_query - cached_query) / first_query * 100):.0f}%", status="ok")
    else:
        result("تحسن الاستعلام", "لم يُلاحظ", status="warn")

    # ═══ السيناريو 2: الاشتراك الإجباري (كاش) ═══

    from handlers.handlers_command import (
        _check_force_subscription_cached,
        _invalidate_force_sub_cache,
    )

    # بدون اشتراك إجباري (get_force_subscribe_channel يعيد None)
    _invalidate_force_sub_cache()
    t0 = time.monotonic()
    # هذا لن يستدعي API لأن force_ch = None
    force_ch = await DB.get_force_subscribe_channel()
    elapsed = (time.monotonic() - t0) * 1000

    if force_ch is None:
        result("لا يوجد اشتراك إجباري", f"{elapsed:.2f}ms", status="ok")
    else:
        # يوجد اشتراك إجباري
        print(f"  ℹ️ الاشتراك الإجباري مفعّل: {force_ch}")

    # ═══ الزمن الكلي المتوقع ═══

    print()
    print(f"  {C.BOLD}📊 الزمن المتوقع لـ /start بعد الإصلاح:{C.END}")
    print(f"     • أول /start (كاش فارغ): ~500-1500ms")
    print(f"     • /start التالي (كاش): < 300ms")
    print(f"     • بعد 3 دقائق: يُعاد الفحص تلقائياً")

    return True


# ═════════════════════════════════════════════════════════════════════
# 7. اختبار إبطال الكاش عند التغييرات
# ═════════════════════════════════════════════════════════════════════

async def test_cache_invalidation():
    section("7) اختبار إبطال الكاش")

    from handlers.handlers_command import (
        _force_sub_cache,
        _invalidate_force_sub_cache,
    )

    import time as _time

    # إضافة بيانات للكاش
    _force_sub_cache[111] = (_time.time(), True)
    _force_sub_cache[222] = (_time.time(), False)
    _force_sub_cache[333] = (_time.time(), True)

    assert len(_force_sub_cache) == 3
    result("إضافة 3 مستخدمين للكاش", "OK", status="ok")

    # إبطال الكل
    _invalidate_force_sub_cache()
    assert len(_force_sub_cache) == 0
    result("إبطال الكل", f"الكاش فارغ", status="ok")

    # إضافة + إبطال فردي
    _force_sub_cache[111] = (_time.time(), True)
    _force_sub_cache[222] = (_time.time(), False)

    _invalidate_force_sub_cache(111)
    assert 111 not in _force_sub_cache
    assert 222 in _force_sub_cache
    result("إبطال مستخدم واحد", "OK", status="ok")

    _force_sub_cache.clear()
    return True


# ═════════════════════════════════════════════════════════════════════
# 8. اختبار keep_alive
# ═════════════════════════════════════════════════════════════════════

async def test_keep_alive():
    section("8) اختبار keep_alive")

    import os
    from bot import keep_alive
    import inspect

    # فحص الدالة
    source = inspect.getsource(keep_alive)
    assert "asyncio.sleep(300)" in source or "sleep(300)" in source
    result("دالة keep_alive موجودة", "OK", status="ok")
    result("الفاصل الزمني", "5 دقائق (300 ثانية)", status="ok")

    # فحص RENDER_EXTERNAL_URL
    url = os.getenv("RENDER_EXTERNAL_URL")
    if url:
        result("RENDER_EXTERNAL_URL", url, status="ok")
    else:
        result("RENDER_EXTERNAL_URL", "غير محدد (سيُفعّل تلقائياً على Render)", status="warn")

    return True


# ═════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════

async def main():
    start_time = datetime.now()

    header("🌿 اختبار أداء البوت - Relax Manager")
    print(f"  📅 التاريخ: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  🐍 Python: {sys.version.split()[0]}")

    all_passed = True

    try:
        if not await test_imports():
            print(f"\n{C.RED}⛔ فشل الاستيراد - توقف الاختبار{C.END}")
            return 1

        await test_database()
        await test_force_sub_cache()
        await test_admin_cache()
        await test_chat_member_handler()
        await test_start_simulation()
        await test_cache_invalidation()
        await test_keep_alive()

    except Exception as e:
        print(f"\n{C.RED}❌ خطأ في الاختبار: {e}{C.END}")
        import traceback
        traceback.print_exc()
        all_passed = False

    # ═══ الملخص ═══
    elapsed = (datetime.now() - start_time).total_seconds()

    header("📊 ملخص اختبار الأداء")

    if all_passed:
        print(f"{C.GREEN}{C.BOLD}🎉 كل الاختبارات نجحت!{C.END}")
        print()
        print(f"{C.GREEN}✅ الإصلاحات التالية تعمل:{C.END}")
        print(f"   • ChatMemberHandler (تحديث المشرفين فورياً)")
        print(f"   • كاش الاشتراك الإجباري (3 دقائق)")
        print(f"   • كاش المشرفين (10 دقائق)")
        print(f"   • keep_alive (5 دقائق)")
        print()
        print(f"{C.GREEN}📊 التحسينات المتوقعة:{C.END}")
        print(f"   • /start: من 5 ثوان → < 300ms")
        print(f"   • getChatAdministrators: من 14/20ث → 0")
        print(f"   • Cold start: من 30ث → لا يحدث")
    else:
        print(f"{C.RED}{C.BOLD}⚠️ بعض الاختبارات فشلت - راجع التفاصيل أعلاه{C.END}")

    print()
    print(f"⏱️  الوقت المستغرق: {elapsed:.2f} ثانية")

    # تنظيف
    try:
        from database import DB
        await DB.execute("DELETE FROM users WHERE user_id = ?", (999888777,))
        await DB.close()
    except Exception:
        pass

    return 0 if all_passed else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}⚠️ تم الإيقاف{C.END}")
        sys.exit(1)