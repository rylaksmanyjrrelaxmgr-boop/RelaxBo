#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_translations.py -- v5.7.34

Generates locales/translations.json from individual language files
(ar.json, en.json, ...). Runs at Docker build time. Idempotent.
"""
import json
import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LANG_META = {
    "ar": "\u0627\u0644\u0639\u0631\u0628\u064a\u0629",
    "de": "Deutsch",
    "en": "English",
    "es": "Espa\u00f1ol",
    "fa": "\u0641\u0627\u0631\u0633\u06cc",
    "fr": "Fran\u00e7ais",
    "hi": "\u0939\u093f\u0928\u094d\u0926\u0940",
    "it": "Italiano",
    "ja": "\u65e5\u672c\u8a9e",
    "ko": "\ud55c\uad6d\uc5b4",
    "nl": "Nederlands",
    "pl": "Polski",
    "pt": "Portugu\u00eas",
    "ru": "\u0420\u0443\u0441\u0441\u043a\u0438\u0439",
    "tr": "T\u00fcrk\u00e7e",
    "ur": "\u0627\u0631\u062f\u0648",
    "zh": "\u4e2d\u6587",
}


def main():
    print('=' * 60)
    print('  generate_translations.py -- merge language files')
    print('=' * 60)

    locales_dir = os.path.join(_BASE_DIR, 'locales')
    output_path = os.path.join(locales_dir, 'translations.json')

    merged = {
        '_meta': {
            'default': 'ar',
            'languages': LANG_META,
        }
    }

    for lang, display in sorted(LANG_META.items()):
        filepath = os.path.join(locales_dir, f'{lang}.json')
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                merged[lang] = data
                print(f'  OK: {lang}.json -- {len(data)} keys')
            else:
                print(f'  WARN: {lang}.json -- not a dict, skipping')
        else:
            print(f'  WARN: {lang}.json -- not found')

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    total_keys = sum(len(v) for k, v in merged.items() if k != '_meta')
    size = os.path.getsize(output_path)
    print(f'\n  OK: Created translations.json: {len(LANG_META)} languages, {total_keys} keys, {size} bytes')
    print('=' * 60)


if __name__ == '__main__':
    main()
