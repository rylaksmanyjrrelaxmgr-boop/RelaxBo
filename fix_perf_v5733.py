#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_perf_v5733.py -- v5.7.33 PERF-DB-POOL + RATELIMITER-EXPAND + SEND-TIMEOUT

Fixes:
  1. RATE_LIMITER max_concurrent: 15 -> 30
  2. PUBLISH_RATE_LIMITER max_concurrent: 5 -> 10
  3. DB pool: enforce minimum=20
  4. safe_send acquire timeout: 5.0s -> 2.0s
  5. _try_count() signature: accept params tuple (fixes TypeError)

Idempotent.
"""
import os
import re

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read(path):
    with open(os.path.join(_BASE_DIR, path), 'r', encoding='utf-8') as f:
        return f.read()


def _write(path, content):
    with open(os.path.join(_BASE_DIR, path), 'w', encoding='utf-8') as f:
        f.write(content)


def fix_utils():
    path = 'utils.py'
    content = _read(path)
    changes = 0

    old_rl = 'RATE_LIMITER = RateLimiter(max_concurrent=15, max_per_second=30)'
    new_rl = 'RATE_LIMITER = RateLimiter(max_concurrent=30, max_per_second=30)'
    if old_rl in content:
        content = content.replace(old_rl, new_rl, 1)
        changes += 1
        print('  OK: RATE_LIMITER: 15 -> 30 concurrent')

    old_prl = 'PUBLISH_RATE_LIMITER = RateLimiter(max_concurrent=5, max_per_second=10)'
    new_prl = 'PUBLISH_RATE_LIMITER = RateLimiter(max_concurrent=10, max_per_second=10)'
    if old_prl in content:
        content = content.replace(old_prl, new_prl, 1)
        changes += 1
        print('  OK: PUBLISH_RATE_LIMITER: 5 -> 10 concurrent')

    old_timeout = 'await asyncio.wait_for(RATE_LIMITER.acquire(), timeout=5.0)'
    new_timeout = 'await asyncio.wait_for(RATE_LIMITER.acquire(), timeout=2.0)'
    if old_timeout in content:
        content = content.replace(old_timeout, new_timeout, 1)
        changes += 1
        print('  OK: safe_send acquire timeout: 5.0s -> 2.0s')

    if changes > 0:
        _write(path, content)
    return changes


def fix_database():
    path = 'database.py'
    content = _read(path)
    changes = 0

    old_pool = 'self._max_connections = int(os.getenv("DB_POOL_SIZE", "20"))'
    new_pool = 'self._max_connections = max(20, int(os.getenv("DB_POOL_SIZE", "20")))'
    if old_pool in content:
        content = content.replace(old_pool, new_pool, 1)
        changes += 1
        print('  OK: DB pool: enforced minimum=20')

    if changes > 0:
        _write(path, content)
    return changes


def fix_bot_try_count():
    """Fix bot.py -- _try_count() signature to accept params tuple.

    fix_bot_values() in fix_sql_injection.py converts f-strings to
    parameterized queries: (sql, params). But _try_count() only accepts
    1 arg (sql). This causes:
      TypeError: _try_count() takes 1 positional argument but 2 were given

    Fix: change _try_count(sql) to _try_count(sql, params=None) and
    pass params to DB.fetchone().
    """
    path = 'bot.py'
    content = _read(path)
    changes = 0

    old_def = 'async def _try_count(sql: str):'
    new_def = 'async def _try_count(sql: str, params=None):'
    if old_def in content:
        content = content.replace(old_def, new_def, 1)
        changes += 1
        print('  OK: _try_count() signature: added params=None')

    old_call = 'row = await DB.fetchone(sql)'
    new_call = 'row = await DB.fetchone(sql, params)'
    if old_call in content:
        content = content.replace(old_call, new_call, 1)
        changes += 1
        print('  OK: DB.fetchone(sql) -> DB.fetchone(sql, params)')

    if changes > 0:
        _write(path, content)
    return changes


def fix_bot_version():
    path = 'bot.py'
    content = _read(path)
    if 'perf_sd5' in content:
        print('  SKIP: perf_sd5 already present')
        return 0

    old = '"perf_sd4=on(ratelimiter_release_fix+warn_parallel+penalty_msg_bg)",'
    new = ('"perf_sd4=on(ratelimiter_release_fix+warn_parallel+penalty_msg_bg) | "\n'
           '        "perf_sd5=on(db_pool_min20+ratelimiter_30concurrent+send_timeout_2s)",')
    if old in content:
        content = content.replace(old, new, 1)
        _write(path, content)
        print('  OK: added perf_sd5 marker')
        return 1
    print('  WARN: perf_sd4 marker not found')
    return 0


def main():
    print('=' * 60)
    print('  fix_perf_v5733.py -- v5.7.33 PERF performance fixes')
    print('=' * 60)

    any_change = False

    print('\nutils.py:')
    if fix_utils() > 0:
        any_change = True

    print('\ndatabase.py:')
    if fix_database() > 0:
        any_change = True

    print('\nbot.py:')
    if fix_bot_try_count() > 0:
        any_change = True
    if fix_bot_version() > 0:
        any_change = True

    print('\n--- Syntax verification ---')
    import ast
    all_ok = True
    for filepath in ['utils.py', 'database.py', 'bot.py']:
        try:
            with open(os.path.join(_BASE_DIR, filepath)) as f:
                ast.parse(f.read())
            print(f'OK: {filepath}: syntax OK')
        except SyntaxError as e:
            print(f'ERROR: {filepath}: SYNTAX ERROR line {e.lineno}: {e.msg}')
            all_ok = False

    if all_ok and any_change:
        print('\nOK: v5.7.33 performance fixes applied successfully.')
    elif not any_change:
        print('\nSKIP: No changes needed.')
    else:
        print('\nWARNING: Some files have syntax errors.')
    print('=' * 60)


if __name__ == '__main__':
    main()
