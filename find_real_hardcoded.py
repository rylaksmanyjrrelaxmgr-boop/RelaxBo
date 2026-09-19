#!/usr/bin/env python3
"""
find_real_hardcoded.py
يكتشف النصوص العربية الحقيقية القابلة للترجمة فقط
(يستبعد التعليقات، Docstrings، logger، _COMMON_PHRASES)
"""

import re
from pathlib import Path

def find_real_arabic_strings(file_path: str):
    """
    يبحث عن نصوص عربية فعلية تُرسل للمستخدم
    """
    path = Path(file_path)
    if not path.exists():
        return []
    
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    results = []
    in_docstring = False
    in_common_phrases = False
    docstring_count = 0
    
    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        
        # ✅ تجاهل التعليقات
        if stripped.startswith('#'):
            continue
        
        # ✅ تجاهل Docstrings
        docstring_markers = stripped.count('"""') + stripped.count("'''")
        if docstring_markers == 1:
            in_docstring = not in_docstring
            docstring_count += 1
            continue
        if in_docstring:
            continue
        
        # ✅ تجاهل _COMMON_PHRASES
        if '_COMMON_PHRASES' in line:
            in_common_phrases = True
            continue
        if in_common_phrases:
            if stripped.startswith('}'):
                in_common_phrases = False
            continue
        
        # ✅ تجاهل logger.info/warning/error/debug
        if re.match(r'\s*logger\.(info|warning|error|debug|critical|exception)\s*\(', line):
            # لكن قد يكون بعدها نص يحتاج ترجمة — تجاهل فقط في السطر نفسه
            continue
        
        # ✅ تجاهل return/def/class/import
        if re.match(r'\s*(def|class|import|from|return)\s', stripped):
            continue
        
        # ✅ ابحث عن نصوص عربية حقيقية بين علامتي تنصيص
        # لا تحتوي على \n في البداية
        matches = re.findall(r'["\']([^"\'\n]{3,}[^\u0600-\u06FF]*[\u0600-\u06FF][^"\']*)["\']', line)
        
        for match in matches:
            # تجاهل النصوص التي تحتوي كود
            if any(x in match for x in ['{e}', '{error}', 'traceback', 'Exception', 'Error']):
                # لكن اسمح بـ {var} إذا كان نصاً
                if not re.search(r'\{[a-zA-Z_]+\}', match):
                    continue
            
            # تجاهل النصوص الطويلة جداً (تعليقات)
            if len(match) > 200:
                continue
            
            # تجاهل النصوص القصيرة جداً
            if len(match) < 4:
                continue
            
            results.append({
                'line': line_num,
                'text': match,
                'code': stripped[:100]
            })
    
    return results


def analyze_all_files():
    """يحلل كل الملفات ويصنف النصوص"""
    
    files = [
        'handlers_callback.py',
        'handlers_message.py',
        'handlers_command.py',
        'handlers_nav_fix.py',
        'handlers_channels_list.py',
        'handlers_group_log.py',
        'chat_member.py',
    ]
    
    print("=" * 70)
    print("🔍 النصوص العربية الحقيقية (تحتاج ترجمة)")
    print("=" * 70)
    
    total = 0
    all_results = {}
    
    for py_file in files:
        results = find_real_arabic_strings(py_file)
        if not results:
            continue
        
        all_results[py_file] = results
        total += len(results)
        
        print(f"\n📄 {py_file}: {len(results)} نص حقيقي")
        print("-" * 70)
        
        for r in results[:30]:  # أول 30
            text = r['text'][:70] + ('...' if len(r['text']) > 70 else '')
            print(f"  السطر {r['line']}: {text}")
        
        if len(results) > 30:
            print(f"  ... و {len(results) - 30} نص آخر")
    
    print()
    print("=" * 70)
    print(f"📊 المجموع: {total} نص يحتاج ترجمة")
    print("=" * 70)
    
    # حفظ النتائج في ملف
    with open('hardcoded_report.txt', 'w', encoding='utf-8') as f:
        for py_file, results in all_results.items():
            f.write(f"\n{'=' * 70}\n📄 {py_file}\n{'=' * 70}\n")
            for r in results:
                f.write(f"السطر {r['line']}: {r['text']}\n")
                f.write(f"  الكود: {r['code']}\n\n")
    
    print(f"\n📁 التقرير الكامل محفوظ في: hardcoded_report.txt")
    print(f"   أرسله لي لأعطيك الترجمة الإنجليزية لكل نص")


if __name__ == '__main__':
    analyze_all_files()