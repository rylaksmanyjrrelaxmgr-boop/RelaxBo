#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_analytics.py — تشخيص شامل لمشكلة "غير متاح / غير متوفر"
=================================================================================
v2.1 — الإصلاحات الجديدة:
    🔴 FIX-9-CORRECTED: حفظ فعلي للناتج عبر TeeOutput
       (في v2.0 كان يطبع "سيُحفظ" دون حفظ فعلي).
    🔴 MAIN-GUARD:      إضافة if __name__ == "__main__" لحماية السكربت
                        من التنفيذ عند الاستيراد.
    🟡 FIX-11:          فحص bot.py v5.6.19 (PERF-WARMUP).
    🟡 FIX-12:          فحص db_diagnostics.py v7.0.0 (CACHE-LAYER).
    🟡 FIX-13:          فحص database_tables.py v7.9.6 (STARTUP-COOLDOWN).
    🟢 FIX-14:          ملخص تقاطعات مع الملفات المُصلَّحة حديثاً.

v2.0 — التصحيحات السابقة:
    🔴 FIX-1:  دعم main.py بالإضافة إلى bot.py (سجل التشغيل يُظهر __main__)
    🔴 FIX-2:  إضافة "غير متاح" إلى أنماط البحث (كانت الرسالة الفعلية)
    🔴 FIX-3:  استثناء __pycache__ و .git و node_modules من البحث
    🔴 FIX-4:  دعم شكلين من JSON: {"rows": [...]} و [...] مباشر
    🟡 FIX-5:  regex يدعم app. و application. كليهما
    🟡 FIX-6:  فحص handlers_nav_fix.py (ظهر في السجل)
    🟡 FIX-7:  استخراج pattern= الفعلي من كل CallbackQueryHandler
    🟡 FIX-8:  بحث بديل عن أي buttons_config_*.json
    🟢 FIX-10: ملخص نهائي واضح مع أولويات
=================================================================================
"""
import os
import sys
import re
import json
import io
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent

# ═══════════════════════════════════════════════════════════════════
# 🆕 v2.1 FIX-9: TeeOutput — يكتب للمخرجات والملف معاً
# ═══════════════════════════════════════════════════════════════════

class TeeOutput:
    """
    يكتب كل ما يُطبع إلى stdout العادي AND إلى buffer داخلي.
    يُستخدم لحفظ التقرير الكامل في ملف دون تغيير أي print().
    """
    def __init__(self, original_stream, buffer):
        self.original = original_stream
        self.buffer = buffer

    def write(self, data):
        self.original.write(data)
        try:
            self.buffer.write(data)
        except Exception:
            pass

    def flush(self):
        try:
            self.original.flush()
        except Exception:
            pass

    def isatty(self):
        try:
            return self.original.isatty()
        except Exception:
            return False

    def fileno(self):
        return self.original.fileno()


# ═══════════════════════════════════════════════════════════════════
# استثناءات البحث
# ═══════════════════════════════════════════════════════════════════
SKIP_DIRS = {
    ".venv", "venv", "env", "site-packages", "__pycache__",
    ".git", ".hg", ".svn", "node_modules", ".pytest_cache",
    ".mypy_cache", ".tox", "build", "dist", ".idea", ".vscode",
    "backups", "logs", "tmp", "temp",
}


def _should_skip(p: Path) -> bool:
    """يتحقق إن كان المسار داخل مجلد مستثنى."""
    try:
        parts = set(p.parts)
        return bool(parts & SKIP_DIRS)
    except Exception:
        return True


def line(title):
    """طباعة عنوان قسم بشكل موحّد."""
    print("\n" + "═" * 70)
    print(f"  {title}")
    print("═" * 70)


def _safe_read(p: Path, encoding: str = "utf-8") -> str:
    """قراءة آمنة للملفات."""
    try:
        return p.read_text(encoding=encoding, errors="ignore")
    except Exception:
        try:
            return p.read_text(encoding="latin-1", errors="ignore")
        except Exception:
            return ""


# ═══════════════════════════════════════════════════════════════════
# 🆕 v2.1 FIX-14: فحص إصدارات الملفات المُصلَّحة
# ═══════════════════════════════════════════════════════════════════

def _extract_version(content: str, patterns: list) -> str:
    """يستخرج رقم الإصدار من محتوى ملف."""
    for pat in patterns:
        m = re.search(pat, content)
        if m:
            return m.group(1)
    return "?"


def _check_recent_fixes():
    """
    🆕 v2.1: فحص الملفات الثلاثة المُصلَّحة حديثاً.
    يعرض الإصدارات والتقاطعات مع مشكلة التحليلات.
    """
    line("4b) 🆕 فحص الملفات المُصلَّحة حديثاً (v7.x)")

    files_to_check = [
        {
            "path": "database_tables.py",
            "expected_marker": "STARTUP-MAINTENANCE-COOLDOWN",
            "version_regex": [r'v7\.\d+\.\d+'],
            "desc": "جداول + فهارس DB",
        },
        {
            "path": "db_diagnostics.py",
            "expected_marker": "CACHE-LAYER",
            "version_regex": [r'VERSION\s*=\s*["\'](\d+\.\d+\.\d+)["\']'],
            "desc": "تشخيص DB",
        },
        {
            "path": "bot.py",
            "expected_marker": "PERF-WARMUP",
            "version_regex": [r'v5\.\d+\.\d+'],
            "desc": "البوت الرئيسي",
        },
    ]

    for entry in files_to_check:
        fpath = ROOT / entry["path"]
        if not fpath.exists():
            print(f"  ⚠️ {entry['path']:<28} غير موجود ({entry['desc']})")
            continue

        content = _safe_read(fpath)
        version = _extract_version(content, entry["version_regex"])
        has_marker = entry["expected_marker"] in content

        marker_icon = "✅" if has_marker else "❌"
        print(f"  {marker_icon} {entry['path']:<28} "
              f"v{version:<10} ({entry['desc']})")
        if has_marker:
            print(f"       ✅ يحتوي على {entry['expected_marker']}")
        else:
            print(f"       ⚠️ لا يحتوي على {entry['expected_marker']} — "
                  f"هل طبّقت التحديث؟")


# ═══════════════════════════════════════════════════════════════════
# الدالة الرئيسية للتشخيص
# ═══════════════════════════════════════════════════════════════════

def run_diagnostics():
    """🆕 v2.1: الدالة الرئيسية — تنفّذ كل الفحوصات."""

    # ═══════════════════════════════════════════════════════════════
    # 1) فحص وجود الملفات الحرجة
    # ═══════════════════════════════════════════════════════════════
    line("1) فحص وجود الملفات الحرجة")

    FILES_TO_CHECK = [
        # ملفات رئيسية
        ("bot.py", "الملف الرئيسي (احتمال 1)"),
        ("main.py", "الملف الرئيسي (احتمال 2)"),
        ("app.py", "الملف الرئيسي (احتمال 3)"),
        ("config.py", "الإعدادات"),
        ("utils.py", "الأدوات المساعدة"),
        ("database.py", "قاعدة البيانات"),
        # handlers
        ("handlers/__init__.py", "تهيئة handlers"),
        ("handlers/handlers_callback.py", "معالج الأزرار العام"),
        ("handlers/handlers_analytics.py", "🔴 التحليلات (المشكلة)"),
        ("handlers/handlers_command.py", "معالج الأوامر"),
        ("handlers/handlers_message.py", "معالج الرسائل"),
        ("handlers/handlers_admin.py", "معالج الأدمن"),
        ("handlers/handlers_nav_fix.py", "موزّع الأزرار (NAV_FIX)"),
        # إعدادات الأزرار
        ("buttons_config_ar.json", "أزرار العربية"),
        ("buttons_config_en.json", "أزرار الإنجليزية"),
        # قاعدة بيانات
        ("database_analytics.py", "استعلامات التحليلات"),
    ]

    main_file = None
    ar_config = None

    for fname, desc in FILES_TO_CHECK:
        p = ROOT / fname
        if p.exists():
            size = p.stat().st_size
            print(f"  ✅ {fname:<45} ({size:>8,} bytes)  ← {desc}")
            if fname in ("bot.py", "main.py", "app.py") and main_file is None:
                main_file = p
            if fname == "buttons_config_ar.json":
                ar_config = p
        else:
            marker = "🔴" if "analytics" in fname else "  "
            print(f"  {marker} {fname:<45} (غير موجود!)  ← {desc}")

    if main_file:
        print(f"\n  📌 الملف الرئيسي المُكتشف: {main_file.name}")
    else:
        print("\n  ⚠️ لم يُعثر على ملف رئيسي (bot.py / main.py / app.py)")

    # ═══════════════════════════════════════════════════════════════
    # 2) البحث عن "غير متاح" / "غير متوفر"
    # ═══════════════════════════════════════════════════════════════
    line('2) البحث عن "غير متاح" / "غير متوفر" في كل ملفات .py')

    PATTERNS = [
        "غير متاح",
        "غير متوفر",
        "غير مُتاح",
        "غير مُتوفر",
        "not available",
        "not_available",
        "unavailable",
        "not supported",
        "not_supported",
        "module not found",
        "ModuleNotFoundError",
    ]

    hits = []
    for py in ROOT.rglob("*.py"):
        if _should_skip(py):
            continue
        content = _safe_read(py)
        if not content:
            continue
        for pat in PATTERNS:
            for m in re.finditer(re.escape(pat), content, re.IGNORECASE):
                line_no = content[:m.start()].count("\n") + 1
                start = content.rfind("\n", 0, m.start()) + 1
                end = content.find("\n", m.end())
                if end == -1:
                    end = len(content)
                snippet = content[start:end].strip()[:140]
                try:
                    rel = py.relative_to(ROOT)
                except ValueError:
                    rel = py
                hits.append((str(rel), line_no, pat, snippet))

    if hits:
        print(f"\n  🔴 وُجد {len(hits)} موضع:\n")
        for rel, ln, pat, snip in hits[:50]:
            print(f"  📍 {rel}:{ln}")
            print(f"     pattern: {pat!r}")
            print(f"     → {snip}")
            print()
        if len(hits) > 50:
            print(f"  ... و{len(hits) - 50} آخرين")
    else:
        print("\n  ✅ لا يوجد أي أثر لرسائل 'غير متاح/غير متوفر'")

    # ═══════════════════════════════════════════════════════════════
    # 3) البحث عن معالجات أزرار التحليلات
    # ═══════════════════════════════════════════════════════════════
    line("3) البحث عن معالجات أزرار التحليلات في المشروع")

    ANALYTICS_BUTTONS = [
        "growth_30d_btn",
        "top_channels_btn",
        "publish_stats_btn",
        "channels_rate_btn",
        "subscriptions_btn",
        "pool_live_btn",
        "slow_queries_btn",
        "export_excel_btn",
        "refresh_btn",
        "admin_analytics",
        "an_growth_30d",
        "an_top_channels",
        "an_publish_stats",
        "an_channels_rate",
        "an_subscriptions",
        "an_pool_live",
        "an_slow_queries",
        "an_export_excel",
    ]

    button_locations = {}
    for btn in ANALYTICS_BUTTONS:
        found = []
        for py in ROOT.rglob("*.py"):
            if _should_skip(py):
                continue
            content = _safe_read(py)
            if not content:
                continue
            for m in re.finditer(re.escape(btn), content):
                line_no = content[:m.start()].count("\n") + 1
                try:
                    rel = py.relative_to(ROOT)
                except ValueError:
                    rel = py
                found.append(f"{rel}:{line_no}")
        button_locations[btn] = found
        if found:
            print(f"  ✅ {btn:<22} ← {len(found)} موضع")
            for loc in found[:3]:
                print(f"       • {loc}")
            if len(found) > 3:
                print(f"       ... و{len(found) - 3} آخرين")
        else:
            print(f"  ❌ {btn:<22} ← غير موجود!")

    # ═══════════════════════════════════════════════════════════════
    # 4) فحص الملف الرئيسي
    # ═══════════════════════════════════════════════════════════════
    line(f"4) فحص الملف الرئيسي: {main_file.name if main_file else 'غير موجود'}")

    main_content = ""
    if main_file:
        main_content = _safe_read(main_file)

        checks = [
            ("handlers_analytics", "استيراد handlers_analytics"),
            ("_ANALYTICS_HANDLERS_AVAILABLE", "متغير التتبع _ANALYTICS_HANDLERS_AVAILABLE"),
            ("show_analytics_menu", "الدالة show_analytics_menu"),
            ("_show_analytics_menu", "الدالة _show_analytics_menu"),
            ("handle_analytics_callback", "الدالة handle_analytics_callback"),
            ("_handle_analytics_callback", "الدالة _handle_analytics_callback"),
            ("admin_analytics", "زر admin_analytics"),
            ("NAV_FIX", "NAV_FIX مُسجَّل"),
            ("register_shutdown_handlers", "shutdown handlers"),
            ("warmup_all", "warmup مُستدعى"),
            # 🆕 v2.1 FIX-11: فحص ميزات v5.6.19
            ("_warmup_telegram_api", "PERF-4: warmup Telegram API"),
            ("_KEEP_ALIVE_INTERVAL_SEC", "PERF-1: keep_alive محسّن"),
            ("_log_perf_tuning_status", "PERF-2: سجل قيم الأداء"),
        ]

        for needle, desc in checks:
            if needle in main_content:
                line_no = main_content[:main_content.find(needle)].count("\n") + 1
                print(f"  ✅ {desc:<48} (سطر {line_no})")
            else:
                print(f"  ❌ {desc:<48} ← مفقود")

        # فحص ترتيب CallbackQueryHandler
        print("\n  📋 ترتيب تسجيل CallbackQueryHandler:")
        pattern = re.compile(
            r"(?:app|application)\.add_handler\s*\(\s*CallbackQueryHandler\s*\(",
            re.MULTILINE
        )
        matches = list(pattern.finditer(main_content))
        print(f"     إجمالي: {len(matches)} معالج\n")

        for i, m in enumerate(matches, 1):
            ln = main_content[:m.start()].count("\n") + 1
            snippet = main_content[m.start():m.start() + 500]

            labels = []
            if "_show_analytics_menu" in snippet:
                labels.append("✅ _show_analytics_menu")
            if "_handle_analytics_callback" in snippet:
                labels.append("✅ _handle_analytics_callback")
            if "handlers_analytics" in snippet:
                labels.append("📦 من handlers_analytics")
            if "CallbackHandlers.handle" in snippet or "callback_handler" in snippet.lower():
                labels.append("🔵 العام")
            pm = re.search(r'pattern\s*=\s*["\']([^"\']+)["\']', snippet)
            if pm:
                labels.append(f"📎 pattern={pm.group(1)!r}")

            if not labels:
                labels.append("❓ غير معروف")

            print(f"     {i}. سطر {ln}: {' | '.join(labels)}")
    else:
        print("  ❌ لا يوجد ملف رئيسي للفحص")

    # ═══════════════════════════════════════════════════════════════
    # 🆕 4b) فحص الملفات المُصلَّحة حديثاً
    # ═══════════════════════════════════════════════════════════════
    _check_recent_fixes()

    # ═══════════════════════════════════════════════════════════════
    # 5) فحص buttons_config_ar.json
    # ═══════════════════════════════════════════════════════════════
    line("5) فحص buttons_config_ar.json — قائمة analytics")

    if ar_config and ar_config.exists():
        try:
            raw = ar_config.read_text(encoding="utf-8")
            cfg = json.loads(raw)
            menus = cfg.get("menus", {})
            print(f"  ✅ عدد القوائم في الملف: {len(menus)}")

            if "analytics" in menus:
                entry = menus["analytics"]
                if isinstance(entry, dict):
                    rows = entry.get("rows", [])
                    print(f"  ✅ قائمة 'analytics' موجودة (dict) بـ {len(rows)} صف")
                elif isinstance(entry, list):
                    rows = entry
                    print(f"  ✅ قائمة 'analytics' موجودة (list) بـ {len(rows)} صف")
                else:
                    rows = []
                    print(f"  ⚠️ شكل غير متوقع: {type(entry).__name__}")

                for i, r in enumerate(rows):
                    print(f"     {i+1}. {r}")
            else:
                print("  ❌ قائمة 'analytics' مفقودة!")
                print(f"     القوائم المتاحة: {list(menus.keys())}")

            # فحص النصوص
            texts = cfg.get("texts", {})
            needed_texts = [
                "analytics_title", "analytics_hint",
                "growth_30d_btn", "top_channels_btn", "publish_stats_btn",
                "channels_rate_btn", "subscriptions_btn", "pool_live_btn",
                "slow_queries_btn", "export_excel_btn", "refresh_btn",
                "back",
            ]
            print(f"\n  📋 النصوص المطلوبة (إجمالي {len(needed_texts)}):")
            missing = []
            for t in needed_texts:
                status = "✅" if t in texts else "❌"
                print(f"     {status} {t}")
                if t not in texts:
                    missing.append(t)
            if missing:
                print(f"\n  ⚠️ ناقص {len(missing)} نص: {missing}")

            print(f"\n  📊 إجمالي النصوص في الملف: {len(texts)}")

        except json.JSONDecodeError as e:
            print(f"  ❌ JSON غير صحيح: {e}")
            print(f"     السطر: {e.lineno}, العمود: {e.colno}")
        except Exception as e:
            print(f"  ❌ خطأ: {e}")
    else:
        print("  ❌ buttons_config_ar.json غير موجود")
        alt = sorted(ROOT.glob("buttons_config_*.json"))
        if alt:
            print(f"  ℹ️ لكن وُجدت الملفات: ")
            for p in alt:
                print(f"       • {p.name} ({p.stat().st_size:,} bytes)")
        else:
            print("  ⚠️ لا يوجد أي buttons_config_*.json في المجلد الجذر!")

    # ═══════════════════════════════════════════════════════════════
    # 6) فحص handlers/handlers_analytics.py
    # ═══════════════════════════════════════════════════════════════
    line("6) فحص handlers/handlers_analytics.py")

    ha_path = ROOT / "handlers" / "handlers_analytics.py"
    ha_content = ""
    if ha_path.exists():
        ha_content = _safe_read(ha_path)
        size = ha_path.stat().st_size
        print(f"  ✅ الملف موجود ({size:,} bytes)\n")

        checks = [
            ("def show_analytics_menu", "show_analytics_menu معرّفة"),
            ("def _show_analytics_menu", "_show_analytics_menu معرّفة"),
            ("def handle_analytics_callback", "handle_analytics_callback"),
            ("def _handle_analytics_callback", "_handle_analytics_callback"),
            ("def show_growth", "show_growth معرّفة"),
            ("def show_top_channels", "show_top_channels"),
            ("def show_publish_stats", "show_publish_stats"),
            ("def show_channels_rate", "show_channels_rate"),
            ("def show_subscriptions", "show_subscriptions"),
            ("def show_pool_live", "show_pool_live"),
            ("def show_slow_queries", "show_slow_queries"),
            ("def export_excel", "export_excel"),
            ("ANALYTICS_BUTTONS", "ANALYTICS_BUTTONS"),
            ("__all__", "__all__ موجود"),
            ("register_handlers", "register_handlers (دالة)"),
            ("def register", "register (alias)"),
        ]
        for needle, desc in checks:
            st = "✅" if needle in ha_content else "❌"
            print(f"  {st} {desc}")

        lines_count = ha_content.count("\n") + 1
        funcs = re.findall(r"^(?:async\s+)?def\s+(\w+)", ha_content, re.MULTILINE)
        print(f"\n  📊 إحصائيات:")
        print(f"     • عدد الأسطر: {lines_count}")
        print(f"     • عدد الدوال: {len(funcs)}")
        if funcs:
            print(f"     • الدوال: {', '.join(funcs[:10])}")
            if len(funcs) > 10:
                print(f"       ... و{len(funcs) - 10} أخرى")
    else:
        print("  ❌ handlers/handlers_analytics.py غير موجود!")
        print("     🔴 هذا هو مصدر التحذير الأساسي")

    # ═══════════════════════════════════════════════════════════════
    # 7) فحص handlers/handlers_nav_fix.py
    # ═══════════════════════════════════════════════════════════════
    line("7) فحص handlers/handlers_nav_fix.py — التوجيه")

    nav_path = ROOT / "handlers" / "handlers_nav_fix.py"
    if nav_path.exists():
        nav_content = _safe_read(nav_path)
        size = nav_path.stat().st_size
        print(f"  ✅ الملف موجود ({size:,} bytes)\n")

        checks = [
            ("analytics", "ذكر analytics"),
            ("admin_analytics", "زر admin_analytics"),
            ("growth_30d", "زر growth_30d"),
            ("top_channels", "زر top_channels"),
            ("publish_stats", "زر publish_stats"),
            ("channels_rate", "زر channels_rate"),
            ("subscriptions", "زر subscriptions"),
            ("pool_live", "زر pool_live"),
            ("slow_queries", "زر slow_queries"),
            ("export_excel", "زر export_excel"),
            ("refresh", "زر refresh"),
            ("_DELEGATE_TO", "آلية التفويض"),
            ("DELEGATION", "DELEGATION mode"),
            ("delegation", "delegation (lowercase)"),
            ("_RESOLVE", "resolver"),
            ("fallback", "fallback mechanism"),
        ]
        for needle, desc in checks:
            st = "✅" if needle in nav_content else "❌"
            print(f"  {st} {desc}")

        print(f"\n  📋 كل المواضع التي تذكر 'analytics' في NAV_FIX:")
        mentions = list(re.finditer(r"analytics", nav_content, re.IGNORECASE))
        if mentions:
            for m in mentions[:10]:
                ln = nav_content[:m.start()].count("\n") + 1
                start = nav_content.rfind("\n", 0, m.start()) + 1
                end = nav_content.find("\n", m.end())
                if end == -1:
                    end = len(nav_content)
                snippet = nav_content[start:end].strip()[:100]
                print(f"     • سطر {ln}: {snippet}")
            if len(mentions) > 10:
                print(f"     ... و{len(mentions) - 10} أخرى")
        else:
            print("     ❌ لا يوجد أي ذكر لـ analytics")
    else:
        print("  ⚠️ handlers/handlers_nav_fix.py غير موجود")

    # ═══════════════════════════════════════════════════════════════
    # 8) فحص handlers/handlers_callback.py
    # ═══════════════════════════════════════════════════════════════
    line("8) فحص handlers/handlers_callback.py — المعالج العام")

    cb_path = ROOT / "handlers" / "handlers_callback.py"
    if cb_path.exists():
        cb_content = _safe_read(cb_path)
        size = cb_path.stat().st_size
        print(f"  ✅ الملف موجود ({size:,} bytes)\n")

        checks = [
            ("admin_analytics", "زر admin_analytics"),
            ("analytics", "ذكر analytics"),
            ("growth_30d", "زر growth_30d"),
            ("غير متاح", "رسالة 'غير متاح'"),
            ("غير متوفر", "رسالة 'غير متوفر'"),
            ("answer", "callback.answer()"),
            ("edit_message", "edit_message_text"),
            ("elif", "elif chain"),
            ("match", "match statement"),
            ("callback_data", "callback_data"),
        ]
        for needle, desc in checks:
            st = "✅" if needle in cb_content else "❌"
            print(f"  {st} {desc}")

        print(f"\n  📋 كل المواضع التي تذكر 'analytics':")
        mentions = list(re.finditer(r"analytics", cb_content, re.IGNORECASE))
        if mentions:
            for m in mentions[:15]:
                ln = cb_content[:m.start()].count("\n") + 1
                start = cb_content.rfind("\n", 0, m.start()) + 1
                end = cb_content.find("\n", m.end())
                if end == -1:
                    end = len(cb_content)
                snippet = cb_content[start:end].strip()[:110]
                print(f"     • سطر {ln}: {snippet}")
            if len(mentions) > 15:
                print(f"     ... و{len(mentions) - 15} أخرى")
        else:
            print("     ❌ لا يوجد أي ذكر لـ analytics — 🔴 مشكلة محتملة!")
    else:
        print("  ⚠️ handlers/handlers_callback.py غير موجود")

    # ═══════════════════════════════════════════════════════════════
    # 9) الخلاصة والتوصيات
    # ═══════════════════════════════════════════════════════════════
    line("9) 🎯 الخلاصة والتوصيات النهائية")

    recommendations = []

    # أ) هل handlers_analytics.py موجود؟
    if not ha_path.exists():
        recommendations.append((
            "🔴 عاجل",
            "أنشئ handlers/handlers_analytics.py — الأزرار لن تعمل بدونه"
        ))
    else:
        if "def register" not in ha_content and "register_handlers" not in ha_content:
            recommendations.append((
                "🟡 متوسط",
                "handlers_analytics.py لا يحتوي على دالة register/register_handlers"
            ))

    # ب) هل الملف الرئيسي يستورد handlers_analytics؟
    if main_file and main_content:
        if "handlers_analytics" not in main_content:
            recommendations.append((
                "🔴 عاجل",
                f"أضف استيراد handlers_analytics إلى {main_file.name}"
            ))
        if "_show_analytics_menu" not in main_content and "show_analytics_menu" not in main_content:
            recommendations.append((
                "🔴 عاجل",
                f"سجّل show_analytics_menu في {main_file.name}"
            ))
        if "_handle_analytics_callback" not in main_content and "handle_analytics_callback" not in main_content:
            recommendations.append((
                "🔴 عاجل",
                f"سجّل handle_analytics_callback في {main_file.name}"
            ))

    # ج) هل NAV_FIX يعرف التحليلات؟
    if nav_path.exists():
        nav_content = _safe_read(nav_path)
        if "analytics" not in nav_content.lower():
            recommendations.append((
                "🟡 متوسط",
                "handlers_nav_fix.py لا يعرف أزرار analytics"
            ))

    # د) هل ملف الأزرار ناقص؟
    if ar_config and ar_config.exists():
        try:
            cfg = json.loads(ar_config.read_text(encoding="utf-8"))
            if "analytics" not in cfg.get("menus", {}):
                recommendations.append((
                    "🔴 عاجل",
                    "أضف قائمة 'analytics' إلى buttons_config_ar.json"
                ))
        except Exception:
            pass
    else:
        recommendations.append((
            "🔴 عاجل",
            "buttons_config_ar.json مفقود — أنشئه"
        ))

    # هـ) هل handlers_callback.py يعرف analytics؟
    if cb_path.exists():
        cb_content = _safe_read(cb_path)
        if "analytics" not in cb_content.lower():
            recommendations.append((
                "🟡 متوسط",
                "handlers_callback.py لا يعرف analytics — أضف معالج للأزرار"
            ))

    # و) رسائل التحذير
    if main_content and ("غير متاح" in main_content or "غير متوفر" in main_content):
        m = re.search(r"غير (?:متاح|متوفر)", main_content)
        if m:
            line_no = main_content[:m.start()].count("\n") + 1
            start = main_content.rfind("\n", 0, m.start()) + 1
            end = main_content.find("\n", m.end())
            if end == -1:
                end = len(main_content)
            snippet = main_content[start:end].strip()[:120]
            recommendations.append((
                "ℹ️ معلومة",
                f"رسالة التحذير في {main_file.name} سطر {line_no}: {snippet}"
            ))

    # طباعة التوصيات
    if not recommendations:
        print("  🎉 كل شيء على ما يرام من ناحية البنية!")
        print("\n  📌 إذا استمر التحذير، أرسل:")
        print("     1. السطر الكامل من السجل عند ظهور التحذير")
        print("     2. نتيجة: grep -rn 'handlers_analytics' .")
    else:
        priority_order = {"🔴 عاجل": 1, "🟡 متوسط": 2, "ℹ️ معلومة": 3}
        recommendations.sort(key=lambda x: priority_order.get(x[0], 99))

        print(f"  📋 عدد التوصيات: {len(recommendations)}\n")
        for priority, desc in recommendations:
            print(f"  {priority} → {desc}")

    # ═══════════════════════════════════════════════════════════════
    # 10) ملخص نهائي
    # ═══════════════════════════════════════════════════════════════
    line("10) 📊 الملخص التنفيذي")

    print(f"  📁 المجلد الجذر: {ROOT}")
    print(f"  🕐 وقت الفحص: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  📄 الملف الرئيسي: {main_file.name if main_file else '❌ غير موجود'}")
    print(f"  🔧 handlers_analytics.py: {'✅ موجود' if ha_path.exists() else '❌ مفقود'}")
    print(f"  📝 buttons_config_ar.json: {'✅ موجود' if ar_config and ar_config.exists() else '❌ مفقود'}")
    print(f"  🔴 عدد التوصيات العاجلة: {sum(1 for p, _ in recommendations if p == '🔴 عاجل')}")
    print(f"  🟡 عدد التوصيات المتوسطة: {sum(1 for p, _ in recommendations if p == '🟡 متوسط')}")

    print("\n" + "═" * 70)
    print("  ✅ انتهى الفحص — انسخ كل الناتج وأرسله")
    print("═" * 70)

    return recommendations


# ═══════════════════════════════════════════════════════════════════
# 🆕 v2.1 MAIN-GUARD: نقطة الدخول الآمنة
# ═══════════════════════════════════════════════════════════════════

def main():
    """
    🆕 v2.1: نقطة الدخول الرئيسية.
      • تُفعِّل TeeOutput لالتقاط كل المُخرجات.
      • تشغّل التشخيص.
      • تحفظ الناتج في diagnose_output.txt فعلياً.
    """
    os.chdir(ROOT)

    # 🆕 FIX-9: التقاط كل المُخرجات في buffer
    buffer = io.StringIO()
    original_stdout = sys.stdout
    tee = TeeOutput(original_stdout, buffer)
    sys.stdout = tee

    try:
        # تشغيل التشخيص
        run_diagnostics()

        # ✅ الآن نحفظ فعلاً (Fix لـ FIX-9 في v2.0)
        try:
            output_file = ROOT / "diagnose_output.txt"
            content = buffer.getvalue()

            # إضافة ترويسة
            header = (
                "═" * 70 + "\n"
                f"  diagnose_analytics.py — تقرير v2.1\n"
                f"  التاريخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"  المجلد الجذر: {ROOT}\n"
                "═" * 70 + "\n\n"
            )

            output_file.write_text(
                header + content,
                encoding="utf-8",
            )
            # استخدم original_stdout للطباعة النهائية (لتفادي التكرار في الملف)
            original_stdout.write(
                f"\n  💾 تم حفظ التقرير فعلاً في: {output_file}\n"
                f"     الحجم: {output_file.stat().st_size:,} bytes\n"
            )
            original_stdout.flush()

        except Exception as e:
            original_stdout.write(
                f"\n  ⚠️ فشل حفظ التقرير: {e}\n"
            )
            original_stdout.flush()

    finally:
        # إعادة stdout الأصلي
        sys.stdout = original_stdout


# ═══════════════════════════════════════════════════════════════════
# نقطة الدخول
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()