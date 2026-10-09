#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_analytics.py — تشخيص مشكلة "غير متوفر"
================================================================
"""
import os
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)


def line(title):
    print("\n" + "═" * 70)
    print(f"  {title}")
    print("═" * 70)


# ═══════════════════════════════════════════════════════════════════
# 1) فحص وجود الملفات الحرجة
# ═══════════════════════════════════════════════════════════════════
line("1) فحص وجود الملفات الحرجة")

FILES_TO_CHECK = [
    "bot.py",
    "handlers/__init__.py",
    "handlers/handlers_callback.py",
    "handlers/handlers_analytics.py",
    "handlers/handlers_command.py",
    "handlers/handlers_message.py",
    "handlers/handlers_admin.py",
    "buttons_config_ar.json",
    "database_analytics.py",
]

for f in FILES_TO_CHECK:
    p = ROOT / f
    if p.exists():
        size = p.stat().st_size
        print(f"  ✅ {f:<45} ({size:>8,} bytes)")
    else:
        print(f"  ❌ {f:<45} (غير موجود!)")


# ═══════════════════════════════════════════════════════════════════
# 2) البحث عن "غير متوفر" في كل المشروع
# ═══════════════════════════════════════════════════════════════════
line('2) البحث عن "غير متوفر" في كل ملفات .py')

PATTERNS = [
    "غير متوفر",
    "not_available",
    "unavailable",
    "not supported",
]

hits = []
for py in ROOT.rglob("*.py"):
    if ".venv" in str(py) or "site-packages" in str(py):
        continue
    try:
        content = py.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    for pat in PATTERNS:
        for m in re.finditer(re.escape(pat), content, re.IGNORECASE):
            line_no = content[:m.start()].count("\n") + 1
            # خذ السطر كاملاً
            start = content.rfind("\n", 0, m.start()) + 1
            end = content.find("\n", m.end())
            if end == -1:
                end = len(content)
            snippet = content[start:end].strip()[:120]
            rel = py.relative_to(ROOT)
            hits.append((str(rel), line_no, pat, snippet))

if hits:
    print(f"\n  🔴 وُجد {len(hits)} موضع:\n")
    for rel, ln, pat, snip in hits[:30]:
        print(f"  📍 {rel}:{ln}")
        print(f"     pattern: {pat!r}")
        print(f"     → {snip}")
        print()
    if len(hits) > 30:
        print(f"  ... و{len(hits) - 30} آخرين")
else:
    print("\n  ✅ لا يوجد أي أثر لـ 'غير متوفر'")


# ═══════════════════════════════════════════════════════════════════
# 3) البحث عن معالجات أزرار التحليلات
# ═══════════════════════════════════════════════════════════════════
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
]

for btn in ANALYTICS_BUTTONS:
    found = []
    for py in ROOT.rglob("*.py"):
        if ".venv" in str(py) or "site-packages" in str(py):
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in re.finditer(re.escape(btn), content):
            line_no = content[:m.start()].count("\n") + 1
            rel = py.relative_to(ROOT)
            found.append(f"{rel}:{line_no}")
    if found:
        print(f"  ✅ {btn:<22} ← {len(found)} موضع")
        for loc in found[:3]:
            print(f"       • {loc}")
    else:
        print(f"  ❌ {btn:<22} ← غير موجود!")


# ═══════════════════════════════════════════════════════════════════
# 4) فحص bot.py للتأكد من التسجيل
# ═══════════════════════════════════════════════════════════════════
line("4) فحص bot.py — هل handlers_analytics مُستورد ومسجَّل؟")

bot_py = ROOT / "bot.py"
if bot_py.exists():
    content = bot_py.read_text(encoding="utf-8", errors="ignore")

    checks = [
        ("handlers_analytics", "استيراد handlers_analytics"),
        ("_ANALYTICS_HANDLERS_AVAILABLE", "متغير التتبع"),
        ("show_analytics_menu", "الدالة show_analytics_menu"),
        ("handle_analytics_callback", "الدالة handle_analytics_callback"),
        ("admin_analytics", "زر admin_analytics"),
        ("v5.6.16", "الإصدار v5.6.16"),
    ]

    for needle, desc in checks:
        if needle in content:
            # اعرض السطر
            line_no = content[:content.find(needle)].count("\n") + 1
            print(f"  ✅ {desc:<45} (سطر {line_no})")
        else:
            print(f"  ❌ {desc:<45} ← مفقود!")

    # فحص ترتيب add_handler
    print("\n  📋 ترتيب تسجيل CallbackQueryHandler:")
    matches = list(re.finditer(
        r"app\.add_handler\(\s*CallbackQueryHandler\(",
        content
    ))
    for i, m in enumerate(matches, 1):
        ln = content[:m.start()].count("\n") + 1
        # ابحث عن pattern
        snippet = content[m.start():m.start() + 300]
        has_pattern = "pattern=" in snippet
        has_show = "_show_analytics_menu" in snippet
        has_cb = "_handle_analytics_callback" in snippet
        has_general = "CallbackHandlers.handle" in snippet

        label = "❓"
        if has_show:
            label = "✅ show_analytics_menu"
        elif has_cb:
            label = "✅ handle_analytics_callback"
        elif has_general:
            label = "🔵 CallbackHandlers.handle (العام)"
        elif has_pattern:
            label = "📎 CallbackQueryHandler مع pattern"

        print(f"     {i}. سطر {ln}: {label}")
else:
    print("  ❌ bot.py غير موجود")


# ═══════════════════════════════════════════════════════════════════
# 5) فحص buttons_config_ar.json
# ═══════════════════════════════════════════════════════════════════
line("5) فحص buttons_config_ar.json — قائمة analytics")

import json
cfg_path = ROOT / "buttons_config_ar.json"
if cfg_path.exists():
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        menus = cfg.get("menus", {})
        print(f"  ✅ عدد القوائم في الملف: {len(menus)}")

        if "analytics" in menus:
            rows = menus["analytics"].get("rows", [])
            print(f"  ✅ قائمة 'analytics' موجودة بـ {len(rows)} صف")
            for i, r in enumerate(rows):
                print(f"     {i+1}. {r}")
        else:
            print("  ❌ قائمة 'analytics' مفقودة!")

        # فحص النصوص
        texts = cfg.get("texts", {})
        needed_texts = [
            "analytics_title", "analytics_hint",
            "growth_30d_btn", "top_channels_btn", "publish_stats_btn",
            "channels_rate_btn", "subscriptions_btn", "pool_live_btn",
            "slow_queries_btn", "export_excel_btn", "refresh_btn",
        ]
        print("\n  📋 النصوص المطلوبة لقائمة analytics:")
        for t in needed_texts:
            status = "✅" if t in texts else "❌"
            print(f"     {status} {t}")

    except json.JSONDecodeError as e:
        print(f"  ❌ JSON غير صحيح: {e}")
else:
    print("  ❌ buttons_config_ar.json غير موجود")


# ═══════════════════════════════════════════════════════════════════
# 6) فحص handlers_analytics.py
# ═══════════════════════════════════════════════════════════════════
line("6) فحص handlers/handlers_analytics.py")

ha_path = ROOT / "handlers" / "handlers_analytics.py"
if ha_path.exists():
    content = ha_path.read_text(encoding="utf-8", errors="ignore")
    checks = [
        ("def show_analytics_menu", "show_analytics_menu معرّفة"),
        ("def handle_analytics_callback", "handle_analytics_callback معرّفة"),
        ("def show_growth", "show_growth معرّفة"),
        ("def export_excel", "export_excel معرّفة"),
        ("ANALYTICS_BUTTONS", "ANALYTICS_BUTTONS معرّف"),
        ("__all__", "__all__ موجود"),
    ]
    for needle, desc in checks:
        st = "✅" if needle in content else "❌"
        print(f"  {st} {desc}")
else:
    print("  ❌ handlers/handlers_analytics.py غير موجود!")


# ═══════════════════════════════════════════════════════════════════
# 7) تشخيص نهائي
# ═══════════════════════════════════════════════════════════════════
line("7) 🎯 الخلاصة والتوصيات")

recommendations = []

if not ha_path.exists():
    recommendations.append(
        "🔴 أنشئ handlers/handlers_analytics.py — الأزرار لن تعمل بدونه"
    )

bot_content = bot_py.read_text(encoding="utf-8") if bot_py.exists() else ""
if "from handlers.handlers_analytics" not in bot_content:
    recommendations.append(
        "🔴 أضف استيراد handlers_analytics إلى bot.py"
    )
if "_show_analytics_menu" not in bot_content:
    recommendations.append(
        "🔴 سجّل show_analytics_menu في bot.py (BEFORE العام)"
    )
if "_handle_analytics_callback" not in bot_content:
    recommendations.append(
        "🔴 سجّل handle_analytics_callback في bot.py (BEFORE العام)"
    )

if not recommendations:
    print("  🎉 كل شيء على ما يرام من ناحية البنية!")
    print("     المشكلة إذن في:")
    print("     1. handlers_callback.py — ابحث عن سطر 'غير متوفر'")
    print("     2. السجل عند الضغط — أرسل السطر من log")
else:
    print("  التوصيات:")
    for r in recommendations:
        print(f"     {r}")

print("\n" + "═" * 70)
print("  انتهى الفحص — انسخ كل النتيجة وأرسلها")
print("═" * 70)