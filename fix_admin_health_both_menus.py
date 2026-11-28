#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_admin_health_both_menus.py -- v5.7.40

Adds admin_health to the SHORT admin menu too.
Previously only added to admin_panel (full menu).
The user sees the short admin menu when clicking the admin button.
"""
import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read(path):
    with open(os.path.join(_BASE_DIR, path), 'r', encoding='utf-8') as f:
        return f.read()


def _write(path, content):
    with open(os.path.join(_BASE_DIR, path), 'w', encoding='utf-8') as f:
        f.write(content)


def fix_admin_menu():
    path = 'utils.py'
    content = _read(path)
    old = '                ["admin_ram", "admin_metrics"], ["back"],'
    new = '                ["admin_ram", "admin_metrics"], ["admin_health"], ["back"],'
    if old in content:
        content = content.replace(old, new, 1)
        _write(path, content)
        print('  OK: added admin_health to admin (short) menu')
        return 1
    if 'admin_health' in content:
        print('  SKIP: admin_health already present')
        return 0
    print('  WARN: pattern not found')
    return 0


def main():
    print('=' * 60)
    print('  fix_admin_health_both_menus.py -- v5.7.40')
    print('=' * 60)
    print()
    changes = fix_admin_menu()
    print()
    print('--- Syntax verification ---')
    import ast
    try:
        with open(os.path.join(_BASE_DIR, 'utils.py')) as f:
            ast.parse(f.read())
        print('OK: utils.py syntax OK')
    except SyntaxError as e:
        print(f'ERROR: SYNTAX ERROR line {e.lineno}: {e.msg}')
    if changes > 0:
        print('\nOK: Fix applied.')
    else:
        print('\nSKIP: No changes needed.')
    print('=' * 60)


if __name__ == '__main__':
    main()
