#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hotfix_published_true.py — إصلاح شامل لـ `published = TRUE` (v1.0)
================================================================================
🎯 الغرض:
    اعتراض كل استعلامات SQL قبل تنفيذها، واستبدال:
        published = TRUE   →   published = 1
        published = FALSE  →   published = 0
    تلقائياً. هذا يُصلح كل ملف في المشروع دفعة واحدة (bot.py,
    handlers_callback, handlers_analytics, أي ملف آخر) دون الحاجة
    لتعديلها جميعاً.

🔴 المشكلة التي يحلها:
    `posts.published` معرّف كـ INTEGER في PostgreSQL. استخدام
    `published = TRUE` يفشل بـ:
        ERROR: operator does not exist: integer = boolean

📦 كيف يُستخدم:
    1) ضع هذا الملف في جذر المشروع (بجانب bot.py).
    2) في bot.py، أضف سطراً واحداً بعد `from database import DB`:
           import hotfix_published_true
       (لا تحتاج أي تعديل آخر)

🛡️ الأمان:
    • regex محدد بـ boundaries (لا يلمس TRUE في سياقات أخرى).
    • idempotent (تشغيله مرتين لا يضاعف التعديل).
    • يطبع log تحذيري عند كل استبدال (للتشخيص).
    • يعمل على PG/MySQL/SQLite.

🔄 للتراجع:
    احذف السطر من bot.py، أو عطّل بـ:
        HOTFIX_PUBLISHED_TRUE_DISABLED=1

================================================================================
"""

import logging
import os
import re
import functools

logger = logging.getLogger(__name__)

_VERSION = "v1.0"
_DISABLED = os.getenv("HOTFIX_PUBLISHED_TRUE_DISABLED", "0") == "1"

# عدّاد داخلي للتشخيص
_STATS = {
    "queries_scanned": 0,
    "replacements_made": 0,
    "errors": 0,
}

# ═══════════════════════════════════════════════════════════════════════
# نمط الاستبدال
# ═══════════════════════════════════════════════════════════════════════
# نستبدل فقط:
#   published = TRUE   →   published = 1
#   published=TRUE     →   published=1
#   published = true   →   published = 1
#   published = FALSE  →   published = 0
#   published = false  →   published = 0
# مع boundaries (?<!\w) و (?!\w) لتفادي مطابقة:
#   "is_published = TRUE"  ← لن يُستبدل (لكن هذا صحيح)
#   "published_at = TRUE"  ← لن يُستبدل (لكن هذا غير موجود أصلاً)
#   "unpublished = TRUE"   ← لن يُستبدل
_RE_PUBLISHED_TRUE = re.compile(
    r"(?<!\w)(published)\s*=\s*(TRUE|true|True)(?!\w)",
    re.IGNORECASE,
)
_RE_PUBLISHED_FALSE = re.compile(
    r"(?<!\w)(published)\s*=\s*(FALSE|false|False)(?!\w)",
    re.IGNORECASE,
)


def _patch_sql(query: str) -> str:
    """يستبدل `published = TRUE/FALSE` بـ `1/0` في الاستعلام."""
    if not query or not isinstance(query, str):
        return query
    try:
        _STATS["queries_scanned"] += 1
        # البحث السريع: هل يحتاج تعديلاً؟
        q_upper = query.upper()
        if "PUBLISHED" not in q_upper:
            return query
        if ("TRUE" not in q_upper) and ("FALSE" not in q_upper):
            return query

        # استبدال TRUE → 1
        new_query, n_true = _RE_PUBLISHED_TRUE.subn(
            r"\1 = 1", query
        )
        # استبدال FALSE → 0
        new_query, n_false = _RE_PUBLISHED_FALSE.subn(
            r"\1 = 0", new_query
        )
        total = n_true + n_false
        if total > 0:
            _STATS["replacements_made"] += total
            logger.warning(
                "🔧 HOTFIX published=TRUE→1 | "
                "replacements=%d (true=%d, false=%d) | "
                "preview=%r",
                total, n_true, n_false,
                query[:120].replace("\n", " "),
            )
        return new_query
    except Exception as e:
        _STATS["errors"] += 1
        logger.error("❌ HOTFIX _patch_sql error: %s", e)
        return query


# ═══════════════════════════════════════════════════════════════════════
# Monkey-patch على DB methods
# ═══════════════════════════════════════════════════════════════════════

def _install_patch():
    """يُغلّف دوال DB الأساسية بـ SQL auto-correct."""
    if _DISABLED:
        logger.info(
            "⏭️ HOTFIX published=TRUE disabled (env flag)")
        return

    try:
        from database import DB
    except ImportError as e:
        logger.error(
            "❌ HOTFIX: فشل استيراد DB: %s — تخطي", e)
        return

    _patched_methods = []

    def _wrap_query_method(method_name: str):
        """يُغلّف method لتعديل SQL قبل التنفيذ."""
        original = getattr(DB, method_name, None)
        if original is None or not callable(original):
            return False
        # تجنّب التغليف المزدوج
        if getattr(original, "_hotfix_patched", False):
            return False

        @functools.wraps(original)
        async def wrapped(query, *args, **kwargs):
            patched_query = _patch_sql(query)
            return await original(
                patched_query, *args, **kwargs)

        try:
            wrapped._hotfix_patched = True
            wrapped._hotfix_original = original
            setattr(DB, method_name, wrapped)
            _patched_methods.append(method_name)
            return True
        except Exception as e:
            logger.warning(
                "⚠️ HOTFIX: فشل تغليف DB.%s: %s",
                method_name, e)
            return False

    # الدوال التي تستقبل SQL كأول argument
    methods_to_patch = (
        "fetchone",
        "fetchall",
        "fetchval",
        "execute",
        "executemany",
    )

    for method_name in methods_to_patch:
        if _wrap_query_method(method_name):
            logger.info(
                "✅ HOTFIX: DB.%s patched", method_name)

    if not _patched_methods:
        logger.warning(
            "⚠️ HOTFIX published=TRUE: لم يتم تغليف أي دالة — "
            "تحقق من database.py")
        return

    logger.info(
        "🩹 hotfix_published_true %s: installed | "
        "patched_methods=%s | disabled=false | "
        "حل شامل لـ `published = TRUE` في كل المشروع",
        _VERSION, _patched_methods,
    )


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════

def get_stats() -> dict:
    """يرجع إحصائيات التشخيص."""
    return {
        **_STATS,
        "version": _VERSION,
        "disabled": _DISABLED,
    }


def uninstall() -> bool:
    """يُزيل التغليف (لاستعادة السلوك الأصلي)."""
    try:
        from database import DB
    except ImportError:
        return False
    success = True
    for method_name in (
        "fetchone", "fetchall", "fetchval",
        "execute", "executemany",
    ):
        original = getattr(DB, method_name, None)
        if original is None:
            continue
        if not getattr(original, "_hotfix_patched", False):
            continue
        real = getattr(original, "_hotfix_original", None)
        if real is None:
            continue
        try:
            setattr(DB, method_name, real)
            logger.info(
                "🔙 HOTFIX: DB.%s restored", method_name)
        except Exception as e:
            logger.warning(
                "⚠️ HOTFIX: uninstall DB.%s: %s", method_name, e)
            success = False
    return success


# ═══════════════════════════════════════════════════════════════════════
# Auto-install عند الاستيراد
# ═══════════════════════════════════════════════════════════════════════

_install_patch()


__all__ = [
    "get_stats",
    "uninstall",
    "_patch_sql",
    "_VERSION",
]