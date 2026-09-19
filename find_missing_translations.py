#!/usr/bin/env python3
"""
find_missing_translations.py
يكتشف:
1. المفاتيح الناقصة في en.json
2. النصوص المكتوبة hardcoded في الكود
"""

import json
import re
from pathlib import Path

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def find_missing_keys():
    """يقارن ar.json مع en.json"""
    ar = load_json('locales/ar.json')
    en = load_json('locales/en.json')
    
    ar_keys = set(ar.keys())
    en_keys = set(en.keys())
    
    missing_in_ar = en_keys - ar_keys
    missing_in_en = ar_keys - en_keys
    
    print("=" * 60)
    print("🔍 المفاتيح الناقصة")
    print("=" * 60)
    
    if missing_in_en:
        print(f"\n❌ في ar.json لكن ليست في en.json ({len(missing_in_en)}):")
        for k in sorted(missing_in_en):
            print(f"  - {k}")
    
    if missing_in_ar:
        print(f"\n❌ في en.json لكن ليست في ar.json ({len(missing_in_ar)}):")
        for k in sorted(missing_in_ar):
            print(f"  - {k}")
    
    if not missing_in_en and not missing_in_ar:
        print("✅ كل المفاتيح موجودة في الملفين")
    
    return ar_keys, en_keys

def find_hardcoded_arabic():
    """يبحث عن النصوص العربية المكتوبة مباشرة في ملفات Python"""
    py_files = [
        'handlers_callback.py',
        'handlers_message.py',
        'handlers_command.py',
        'handlers_nav_fix.py',
        'handlers_channels_list.py',
        'handlers_group_log.py',
        'utils.py',
    ]
    
    # نمط: نصوص عربية بين علامتي تنصيص
    arabic_pattern = re.compile(r'["\']([^"\']*[\u0600-\u06FF][^"\']*)["\']')
    
    print()
    print("=" * 60)
    print("🔍 النصوص العربية المكتوبة مباشرة في الكود")
    print("=" * 60)
    
    total_found = 0
    for py_file in py_files:
        path = Path(py_file)
        if not path.exists():
            continue
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"⚠️ خطأ في قراءة {py_file}: {e}")
            continue
        
        matches = arabic_pattern.findall(content)
        # استبعاد النصوص القصيرة جداً
        matches = [m for m in matches if len(m) > 3 and not m.startswith('#')]
        
        if matches:
            print(f"\n📄 {py_file}: {len(matches)} نص")
            for m in matches[:15]:  # أول 15 فقط
                short = m[:60] + ('...' if len(m) > 60 else '')
                print(f"  • {short}")
            if len(matches) > 15:
                print(f"  ... و {len(matches) - 15} آخر")
            total_found += len(matches)
    
    print(f"\n📊 المجموع: {total_found} نص عربي hardcoded")

def test_translation_coverage():
    """يختبر كل المفاتيح الحرجة"""
    from utils import TranslationManager
    
    print()
    print("=" * 60)
    print("🔍 اختبار الترجمة الفعلية")
    print("=" * 60)
    
    critical_keys = [
        'security_title', 'back', 'main_menu',
        'sec_links_short', 'security_enabled_footer',
        'violation_link', 'translation_label',
        'growth_30d_btn', 'admin_analytics',
    ]
    
    for key in critical_keys:
        ar = TranslationManager.get_text('ar', key)
        en = TranslationManager.get_text('en', key)
        
        ar_ok = ar != key
        en_ok = en != key
        
        status_ar = '✅' if ar_ok else '❌'
        status_en = '✅' if en_ok else '❌'
        
        print(f"{status_ar} AR: {key} → {ar[:40]}")
        print(f"{status_en} EN: {key} → {en[:40]}")
        print()

if __name__ == '__main__':
    print()
    print("🔍 أداة كشف المفاتيح الناقصة")
    print()
    
    # 1. المفاتيح الناقصة
    find_missing_keys()
    
    # 2. النصوص العربية hardcoded
    find_hardcoded_arabic()
    
    # 3. اختبار الترجمة
    try:
        test_translation_coverage()
    except ImportError:
        print("⚠️ لا يمكن استيراد utils.py")
    
    print()
    print("=" * 60)
    print("🎉 انتهى الفحص")
    print("=" * 60)