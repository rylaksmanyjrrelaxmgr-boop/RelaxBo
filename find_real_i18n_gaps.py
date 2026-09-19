#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_real_i18n_gaps.py
يكتشف فقط النصوص العربية التي تُرسل للمستخدم فعلاً
(يستبعد التعليقات، docstrings، logger، _COMMON_PHRASES)
"""

import re
from pathlib import Path


def find_user_facing_strings(file_path: str):
    """
    يبحث فقط عن النصوص العربية داخل:
    - safe_send(bot, chat_id, "نص")
    - safe_edit(query, "نص", ...)
    - query.answer("نص")
    - InlineKeyboardButton("نص", ...)
    - send_message(chat_id, "نص")
    - text = "نص عربي"
    - return "نص"
    """
    path = Path(file_path)
    if not path.exists():
        return []

    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    results = []
    patterns = [
        r'safe_send\s*\([^,]+,\s*[^,]+,\s*[fr]?["\']([^"\']+[\u0600-\u06FF][^"\']*)["\']',
        r'safe_edit\s*\([^,]+,\s*[fr]?["\']([^"\']+[\u0600-\u06FF][^"\']*)["\']',
        r'query\.answer\s*\(\s*[fr]?["\']([^"\']+[\u0600-\u06FF][^"\']*)["\']',
        r'InlineKeyboardButton\s*\(\s*[fr]?["\']([^"\']+[\u0600-\u06FF][^"\']*)["\']',
        r'send_message\s*\([^,]+,\s*[fr]?["\']([^"\']+[\u0600-\u06FF][^"\']*)["\']',
        r'=\s*f?["\']([^"\']*[\u0600-\u06FF][^"\']*)["\']',
        r'return\s+f?["\']([^"\']+[\u0600-\u06FF][^"\']*)["\']',
    ]

    lines = content.split('\n')
    seen = set()

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        if stripped.startswith('#'):
            continue
        if re.match(r'\s*logger\.', line):
            continue
        if '"""' in line or "'''" in line:
            continue

        for pattern in patterns:
            try:
                for match in re.finditer(pattern, line):
                    text = match.group(1).strip()
                    if len(text) < 4:
                        continue
                    if not re.search(r'[\u0600-\u06FF]', text):
                        continue
                    key = (file_path, text)
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append({
                        'line': line_num,
                        'text': text,
                        'code': stripped[:120],
                    })
            except re.error:
                continue

    return results


def main():
    files = [
        'handlers_callback.py',
        'handlers_message.py',
        'handlers_command.py',
        'handlers_nav_fix.py',
        'handlers_channels_list.py',
        'handlers_group_log.py',
        'handlers_security.py',
        'chat_member.py',
    ]

    print("=" * 72)
    print("🎯 النصوص العربية التي تُرسل للمستخدم (تحتاج ترجمة)")
    print("=" * 72)

    total = 0
    all_results = {}

    for py_file in files:
        results = find_user_facing_strings(py_file)
        if not results:
            continue

        all_results[py_file] = results
        total += len(results)

        print(f"\n📄 {py_file}: {len(results)} نص يحتاج ترجمة")
        print("-" * 72)

        for r in results:
            text = r['text'][:70] + ('...' if len(r['text']) > 70 else '')
            print(f"  السطر {r['line']:>4}: {text}")

    print()
    print("=" * 72)
    print(f"📊 المجموع: {total} نص يحتاج ترجمة")
    print("=" * 72)

    if all_results:
        with open('i18n_report.txt', 'w', encoding='utf-8') as f:
            for py_file, results in all_results.items():
                f.write(f"\n{'=' * 72}\n📄 {py_file}\n{'=' * 72}\n")
                for r in results:
                    f.write(f"\n[السطر {r['line']}]\n")
                    f.write(f"النص: {r['text']}\n")
                    f.write(f"الكود: {r['code']}\n")
        print(f"\n✅ التقرير محفوظ في: i18n_report.txt")


if __name__ == '__main__':
    main()