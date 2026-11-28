#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_complete_translations.py -- v5.7.39

Completes missing translations in all language files:
  1. locales/ur.json: 152 missing keys -> filled from ar.json
  2. locales/zh.json: 224 missing keys -> filled from ar.json
  3. buttons_config_*.json: fills missing texts from ar.json
  4. Moves misplaced admin_health from top-level to texts section

Reference: ar.json (Arabic) -- values used as fallback.
User can translate them later.

Idempotent.
"""
import os
import json
import glob

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read(path):
    with open(os.path.join(_BASE_DIR, path), 'r', encoding='utf-8') as f:
        return f.read()


def _write(path, content):
    with open(os.path.join(_BASE_DIR, path), 'w', encoding='utf-8') as f:
        f.write(content)


def fix_locales():
    print('locales/')
    try:
        with open('locales/ar.json') as f:
            ar = json.load(f)
    except Exception as e:
        print(f'  ERROR: {e}')
        return 0
    changes = 0
    for lang in ['ur', 'zh']:
        fname = f'locales/{lang}.json'
        try:
            with open(fname) as f:
                data = json.load(f)
        except Exception as e:
            print(f'  ERROR: {fname}: {e}')
            continue
        missing = set(ar.keys()) - set(data.keys())
        if not missing:
            print(f'  {lang}.json: complete')
            continue
        for key in missing:
            data[key] = ar[key]
        _write(fname, json.dumps(data, ensure_ascii=False, indent=2))
        print(f'  OK: {lang}.json: +{len(missing)} keys')
        changes += len(missing)
    return changes


def fix_buttons_config():
    print('buttons_config/')
    try:
        with open('buttons_config_ar.json') as f:
            ar = json.load(f)
    except Exception as e:
        print(f'  ERROR: {e}')
        return 0
    ar_texts = ar.get('texts', {})
    changes = 0
    for fname in sorted(glob.glob('buttons_config_*.json')):
        if 'ar.json' in fname:
            continue
        lang = fname.replace('buttons_config_', '').replace('.json', '')
        try:
            with open(fname) as f:
                data = json.load(f)
        except Exception as e:
            print(f'  ERROR: {fname}: {e}')
            continue
        texts = data.get('texts', {})
        missing = set(ar_texts.keys()) - set(texts.keys())
        if 'admin_health' in data and 'admin_health' not in texts:
            texts['admin_health'] = data.pop('admin_health')
            missing.discard('admin_health')
        if 'admin_health' not in texts:
            texts['admin_health'] = "\U0001f4ca Health Report"
            missing.discard('admin_health')
        for key in missing:
            texts[key] = ar_texts[key]
        data['texts'] = texts
        if missing:
            _write(fname, json.dumps(data, ensure_ascii=False, indent=2))
            print(f'  OK: {lang}.json: +{len(missing)} keys')
            changes += len(missing)
        elif 'admin_health' not in texts:
            _write(fname, json.dumps(data, ensure_ascii=False, indent=2))
            changes += 1
        else:
            print(f'  {lang}.json: complete')
    return changes


def fix_ar_buttons_config():
    print('buttons_config/ar.json')
    try:
        with open('buttons_config_ar.json') as f:
            data = json.load(f)
    except Exception as e:
        print(f'  ERROR: {e}')
        return 0
    texts = data.get('texts', {})
    if 'admin_health' in texts:
        print('  SKIP: complete')
        return 0
    if 'admin_health' in data:
        texts['admin_health'] = data.pop('admin_health')
    else:
        texts['admin_health'] = "\U0001f4ca Health Report"
    data['texts'] = texts
    _write('buttons_config_ar.json', json.dumps(data, ensure_ascii=False, indent=2))
    print('  OK: added admin_health')
    return 1


def main():
    print('=' * 60)
    print('  fix_complete_translations.py -- v5.7.39')
    print('=' * 60)
    any_change = False
    print()
    if fix_ar_buttons_config() > 0:
        any_change = True
    print()
    if fix_buttons_config() > 0:
        any_change = True
    print()
    if fix_locales() > 0:
        any_change = True
    print()
    print('--- Verification ---')
    with open('locales/ar.json') as f:
        ar = json.load(f)
    ar_keys = set(ar.keys())
    with open('buttons_config_ar.json') as f:
        ar_btn = json.load(f)
    ar_btn_keys = set(ar_btn.get('texts', {}).keys())
    all_ok = True
    for lang in ['de','en','es','fa','fr','hi','it','ja','ko','nl','pl','pt','ru','tr','ur','zh']:
        try:
            with open(f'locales/{lang}.json') as f:
                data = json.load(f)
            miss = len(ar_keys - set(data.keys()))
            if miss:
                print(f'  locales/{lang}.json: missing {miss}')
                all_ok = False
        except Exception:
            pass
        try:
            with open(f'buttons_config_{lang}.json') as f:
                data = json.load(f)
            texts = data.get('texts', {})
            miss = len(ar_btn_keys - set(texts.keys()))
            if miss:
                print(f'  buttons_config_{lang}.json: missing {miss}')
                all_ok = False
        except Exception:
            pass
    if all_ok:
        print('  All language files complete!')
    if any_change:
        print('\nOK: Translations completed.')
    else:
        print('\nSKIP: No changes needed.')
    print('=' * 60)


if __name__ == '__main__':
    main()
