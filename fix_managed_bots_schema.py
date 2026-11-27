#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_managed_bots_schema.py -- v5.7.34

Fixes db_diagnostics.py queries that use id/username instead of
bot_id/name in the managed_bots table.

Problem:
  - db_diagnostics.py L816: b.id = k.bot_id -> error: column b.id does not exist
  - db_diagnostics.py L835: SELECT id, username -> error: column "id" does not exist

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

    old1 = 'WHERE NOT EXISTS (SELECT 1 FROM {bots_table} b WHERE b.id = k.bot_id)'
    new1 = 'WHERE NOT EXISTS (SELECT 1 FROM {bots_table} b WHERE b.bot_id = k.bot_id)'
    if old1 in content:
        content = content.replace(old1, new1, 1)
        changes += 1
        print('  OK: fixed b.id -> b.bot_id (orphan FK check)')

    old2 = 'f"SELECT id, username FROM {bots_table} ORDER BY id ASC")'
    new2 = 'f"SELECT bot_id, name FROM {bots_table} ORDER BY bot_id ASC")'
    if old2 in content:
        content = content.replace(old2, new2, 1)
        changes += 1
        print('  OK: fixed SELECT id, username -> SELECT bot_id, name')

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
