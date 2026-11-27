#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_managed_bots_schema.py -- v5.7.34

Fixes db_diagnostics.py queries that use id/username instead of
bot_id/name in the managed_bots table.

IMPORTANT: This script runs AFTER fix_sql_injection.py which converts
f-strings to .format(). So we need to match BOTH versions:
  - Original: {bots_table} (f-string)
  - Converted: {} (.format)

Problem:
  - db_diagnostics.py: b.id = k.bot_id -> error: column b.id does not exist
  - db_diagnostics.py: SELECT id, username -> error: column "id" does not exist

Cause:
  managed_bots table uses bot_id as PRIMARY KEY (not id).
  There is no username column (the column is name).

Fix:
  - b.id -> b.bot_id
  - SELECT id, username -> SELECT bot_id, name
  - b.get("id") -> b.get("bot_id")

Idempotent.
"""
import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read(path):
    with open(os.path.join(_BASE_DIR, path), 'r', encoding='utf-8') as f:
        return f.read()


def _write(path, content):
    with open(os.path.join(_BASE_DIR, path), 'w', encoding='utf-8') as f:
        f.write(content)


def fix_db_diagnostics():
    path = 'db_diagnostics.py'
    content = _read(path)
    changes = 0

    # Fix 1: b.id -> b.bot_id (orphan FK check)
    # Match BOTH original f-string and post-fix_sql_injection .format() versions
    old1a = 'WHERE NOT EXISTS (SELECT 1 FROM {bots_table} b WHERE b.id = k.bot_id)'
    old1b = 'WHERE NOT EXISTS (SELECT 1 FROM {} b WHERE b.id = k.bot_id)'
    new1a = 'WHERE NOT EXISTS (SELECT 1 FROM {bots_table} b WHERE b.bot_id = k.bot_id)'
    new1b = 'WHERE NOT EXISTS (SELECT 1 FROM {} b WHERE b.bot_id = k.bot_id)'
    if old1a in content:
        content = content.replace(old1a, new1a, 1)
        changes += 1
        print('  OK: fixed b.id -> b.bot_id (orphan FK, f-string version)')
    elif old1b in content:
        content = content.replace(old1b, new1b, 1)
        changes += 1
        print('  OK: fixed b.id -> b.bot_id (orphan FK, .format version)')

    # Fix 2: SELECT id, username -> SELECT bot_id, name
    old2a = 'SELECT id, username FROM {bots_table} ORDER BY id ASC'
    old2b = 'SELECT id, username FROM {} ORDER BY id ASC'
    new2a = 'SELECT bot_id, name FROM {bots_table} ORDER BY bot_id ASC'
    new2b = 'SELECT bot_id, name FROM {} ORDER BY bot_id ASC'
    if old2a in content:
        content = content.replace(old2a, new2a, 1)
        changes += 1
        print('  OK: fixed SELECT id, username -> SELECT bot_id, name (f-string version)')
    elif old2b in content:
        content = content.replace(old2b, new2b, 1)
        changes += 1
        print('  OK: fixed SELECT id, username -> SELECT bot_id, name (.format version)')

    # Fix 3: b.get("id") -> b.get("bot_id")
    old3 = 'bid = b.get("id")'
    new3 = 'bid = b.get("bot_id")'
    if old3 in content:
        content = content.replace(old3, new3, 1)
        changes += 1
        print('  OK: fixed b.get("id") -> b.get("bot_id")')

    if changes > 0:
        _write(path, content)
    return changes


def main():
    print('=' * 60)
    print('  fix_managed_bots_schema.py -- managed_bots column fix')
    print('=' * 60)

    print('\ndb_diagnostics.py:')
    changes = fix_db_diagnostics()

    print('\n--- Syntax verification ---')
    import ast
    try:
        with open(os.path.join(_BASE_DIR, 'db_diagnostics.py')) as f:
            ast.parse(f.read())
        print('OK: db_diagnostics.py: syntax OK')
    except SyntaxError as e:
        print(f'ERROR: db_diagnostics.py: SYNTAX ERROR line {e.lineno}: {e.msg}')

    if changes > 0:
        print(f'\nOK: {changes} fixes applied successfully.')
    else:
        print('\nSKIP: No changes needed.')
    print('=' * 60)


if __name__ == '__main__':
    main()
