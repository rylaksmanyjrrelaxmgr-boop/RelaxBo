#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_fix_published_true.py — تطبيق إصلاح FIX-PUBLISHED-TRUE (v9.7.32)

يزيل هذا السكربت خيار `published = TRUE` المعيب من
handlers/handlers_callback.py::_read_posts_count_from_db().

المشكلة:
    posts.published معرّف كـ INTEGER في database_tables.py.
    PostgreSQL يرفض published = TRUE بـ:
        ERROR: operator does not exist: integer = boolean
    الكود كان يسقط على fallback published = 1 الذي يعمل،
    لكن كل استدعاء كان يولّد تحذيراً في السجل — مصدر "التحذيرات الخاطئة".

الحل:
    حذف خيار published = TRUE تماماً.
    published = 1 يعمل على PG/MySQL/SQLite بنفس النتيجة.

الاستخدام:
    python3 apply_fix_published_true.py

السكربت idempotent — تشغيله مرتين لا يحدث تغييراً إضافياً.
"""
import os
import sys

TARGET = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "handlers", "handlers_callback.py"
)

# The 4 buggy lines to remove from the postgres variants list
# These 4 lines form the complete buggy published=TRUE query variant.
# The next line after these 4 starts the working published=1 variant
# (also beginning with f"SELECT COUNT(*)..."), which we keep.
BUGGY_LINES = [
    '            f"SELECT COUNT(*) AS n FROM posts "',
    '            f"WHERE published = TRUE "',
    "            f\"AND created_at > NOW() - INTERVAL '{h} hours'\",",
]

FIX_COMMENT_LINES = [
    "        # FIX-PUBLISHED-TRUE (v9.7.32): removed buggy published=TRUE variant",
    "        # published=1 works on PG/MySQL/SQLite (column is INTEGER in database_tables.py).",
    "        # The old published=TRUE variant failed on PG with:",
    "        #   ERROR: operator does not exist: integer = boolean",
    "        # and generated a debug-log warning on every metrics refresh.",
]

MARKER = '    if db_type == "postgres":'


def line_eq(actual, expected):
    """Compare a file line with an expected string, ignoring trailing newline."""
    return actual.rstrip("\n") == expected


def main():
    if not os.path.exists(TARGET):
        print("File not found: " + TARGET)
        return 1

    with open(TARGET, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Check if fix is already applied
    content = "".join(lines)
    if "FIX-PUBLISHED-TRUE (v9.7.32)" in content:
        print("Fix already applied — no changes needed.")
        return 0

    # Find and remove the buggy lines (all 3 at once)
    removed = 0
    new_lines = []
    i = 0
    while i < len(lines):
        # Check if this line starts the buggy sequence
        if (line_eq(lines[i], BUGGY_LINES[0])
                and i + 2 < len(lines)
                and line_eq(lines[i + 1], BUGGY_LINES[1])
                and line_eq(lines[i + 2], BUGGY_LINES[2])):
            # Skip all 3 buggy lines
            removed = 3
            i += 3
            continue
        new_lines.append(lines[i])
        i += 1

    if removed == 0:
        print("Buggy pattern not found — file may have been modified.")
        return 0

    # Insert the fix comment after the postgres branch marker
    final_lines = []
    for line in new_lines:
        final_lines.append(line)
        if line_eq(line, MARKER):
            for cl in FIX_COMMENT_LINES:
                final_lines.append(cl + "\n")

    with open(TARGET, "w", encoding="utf-8") as f:
        f.writelines(final_lines)

    print("FIX-PUBLISHED-TRUE (v9.7.32) applied successfully!")
    print("Removed " + str(removed) + " buggy lines from postgres branch.")
    print("published = 1 is now the primary variant (works on all DBs).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
