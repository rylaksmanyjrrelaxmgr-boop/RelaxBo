#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_admin_health_button.py -- v5.7.38

Adds Health Report button to admin panel:
  1. Adds admin_health to keyboard layout in utils.py
  2. Adds callback handler in handlers_callback.py
  3. Adds button text to all 17 buttons_config_*.json files

Idempotent.
"""
import os
import json

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read(path):
    with open(os.path.join(_BASE_DIR, path), 'r', encoding='utf-8') as f:
        return f.read()


def _write(path, content):
    with open(os.path.join(_BASE_DIR, path), 'w', encoding='utf-8') as f:
        f.write(content)


_NL = chr(10)


def fix_utils_keyboard():
    path = 'utils.py'
    content = _read(path)
    if 'admin_health' in content:
        print('  SKIP: admin_health already in utils.py')
        return 0
    old = '                ["admin_metrics"],'
    new = '                ["admin_metrics", "admin_health"],'
    if old in content:
        content = content.replace(old, new, 1)
        _write(path, content)
        print('  OK: added admin_health to keyboard layout')
        return 1
    print('  WARN: keyboard pattern not found')
    return 0


def fix_callback_handler():
    path = 'handlers/handlers_callback.py'
    content = _read(path)
    if 'admin_health' in content:
        print('  SKIP: admin_health already in callback handler')
        return 0
    old = (
        '            if data == "admin_metrics_live":' + _NL +
        '                await CallbackHandlers._show_metrics_dashboard(' + _NL +
        '                    query, context, user_id, lang); return'
    )
    new_handler = _NL.join([
        '            if data == "admin_health":',
        '                try:',
        '                    from handlers.handlers_command import CommandHandlers',
        '                    fake_update = type("U", (), {',
        '                        "effective_user": query.from_user,',
        '                        "effective_chat": query.message.chat if query.message else None,',
        '                    })()',
        '                    await CommandHandlers.health(fake_update, context)',
        '                except Exception as e:',
        '                    logger.error("admin_health callback: %s", e)',
        '                return',
        '            if data == "admin_metrics_live":',
        '                await CallbackHandlers._show_metrics_dashboard(',
        '                    query, context, user_id, lang); return',
    ])
    if old in content:
        content = content.replace(old, new_handler, 1)
        _write(path, content)
        print('  OK: added admin_health callback handler')
        return 1
    print('  WARN: callback pattern not found')
    return 0


def fix_translations():
    import glob
    changes = 0
    for filepath in sorted(glob.glob(os.path.join(_BASE_DIR, 'buttons_config_*.json'))):
        fname = os.path.basename(filepath)
        try:
            content = _read(fname)
            data = json.loads(content)
        except Exception:
            continue
        if 'admin_health' in data:
            continue
        data['admin_health'] = "\U0001f4ca Health Report"
        _write(fname, json.dumps(data, ensure_ascii=False, indent=2))
        print(f'  OK: {fname}')
        changes += 1
    return changes


def main():
    print('=' * 60)
    print('  fix_admin_health_button.py -- v5.7.38')
    print('=' * 60)
    any_change = False
    print(_NL + 'utils.py:')
    if fix_utils_keyboard() > 0:
        any_change = True
    print(_NL + 'handlers/handlers_callback.py:')
    if fix_callback_handler() > 0:
        any_change = True
    print(_NL + 'buttons_config files:')
    if fix_translations() > 0:
        any_change = True
    print(_NL + '--- Syntax verification ---')
    import ast
    all_ok = True
    for filepath in ['utils.py', 'handlers/handlers_callback.py']:
        try:
            with open(os.path.join(_BASE_DIR, filepath)) as f:
                ast.parse(f.read())
            print(f'OK: {filepath}: syntax OK')
        except SyntaxError as e:
            print(f'ERROR: {filepath}: SYNTAX ERROR line {e.lineno}: {e.msg}')
            all_ok = False
    if all_ok and any_change:
        print(f'{_NL}OK: Admin health button added successfully.')
    elif not any_change:
        print(f'{_NL}SKIP: No changes needed.')
    else:
        print(f'{_NL}WARNING: Some files have syntax errors.')
    print('=' * 60)


if __name__ == '__main__':
    main()
