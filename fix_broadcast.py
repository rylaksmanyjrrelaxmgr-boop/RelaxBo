#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_broadcast.py -- v5.7.36

Adds _do_broadcast method to CommandHandlers in handlers/handlers_command.py.

Problem:
  /broadcast command sets user state to WAIT_BROADCAST, then when user
  sends text, handle_text looks for CommandHandlers._do_broadcast --
  but the method doesn't exist!
  Result: "Broadcast not executed -- _do_broadcast not available"

Fix:
  Adds static method _do_broadcast that:
  1. Iterates all users via DB.iter_all_users()
  2. Sends message to each non-banned user
  3. Delays 0.05s every 30 messages (avoid Telegram rate limits)
  4. Shows statistics report

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


_DO_BROADCAST_METHOD = '''
    @staticmethod
    async def _do_broadcast(update, context, text: str) -> None:
        """v5.7.36: Broadcast to all non-banned users."""
        try:
            await _safe_edit_or_send(
                update, context,
                "\u23f3 <b>Broadcasting...</b>",
                parse_mode='HTML',
            )
        except Exception:
            pass

        sent_ok = 0
        sent_fail = 0
        skipped = 0
        total = 0
        batch_delay = 0.05
        batch_size = 30
        batch_count = 0

        try:
            async for user_row in DB.iter_all_users(batch_size=500):
                uid = user_row.get("user_id")
                banned = user_row.get("banned", 0)
                if not uid or banned:
                    skipped += 1
                    continue
                total += 1
                try:
                    await safe_send(
                        context.bot, uid, text,
                        parse_mode='HTML',
                    )
                    sent_ok += 1
                except Exception:
                    sent_fail += 1
                batch_count += 1
                if batch_count >= batch_size:
                    await asyncio.sleep(batch_delay)
                    batch_count = 0
        except Exception as e:
            logger.error("_do_broadcast iter error: %s", e, exc_info=True)

        report = (
            "\u2705 <b>Broadcast complete</b>\n\n"
            f"\U0001f4e4 Sent: <b>{sent_ok}</b>\n"
            f"\u274c Failed: <b>{sent_fail}</b>\n"
            f"\u23ed\ufe0f Skipped (banned): <b>{skipped}</b>\n"
            f"\U0001f4ca Total: <b>{total}</b>"
        )
        try:
            await _safe_edit_or_send(
                update, context, report, parse_mode='HTML',
            )
        except Exception:
            pass
        logger.info(
            "broadcast done: ok=%d fail=%d skip=%d total=%d",
            sent_ok, sent_fail, skipped, total,
        )
'''


def fix_broadcast():
    path = 'handlers/handlers_command.py'
    content = _read(path)

    if 'async def _do_broadcast' in content:
        print('  SKIP: _do_broadcast already present')
        return 0

    # Find insertion point: before the @staticmethod that follows broadcast()
    insert_point = content.find('    @staticmethod\n    async def set_force(')
    if insert_point < 0:
        broadcast_start = content.find('    async def broadcast(')
        if broadcast_start < 0:
            print('  WARN: broadcast method not found')
            return 0
        next_static = content.find('    @staticmethod', broadcast_start + 100)
        if next_static < 0:
            print('  WARN: could not find insertion point')
            return 0
        insert_point = next_static

    new_content = (
        content[:insert_point]
        + _DO_BROADCAST_METHOD.lstrip('\n').rstrip('\n')
        + '\n\n'
        + content[insert_point:]
    )

    _write(path, new_content)
    print('  OK: added _do_broadcast method')
    return 1


def main():
    print('=' * 60)
    print('  fix_broadcast.py -- add _do_broadcast method')
    print('=' * 60)

    print('\nhandlers/handlers_command.py:')
    changes = fix_broadcast()

    print('\n--- Syntax verification ---')
    import ast
    try:
        with open(os.path.join(_BASE_DIR, 'handlers/handlers_command.py')) as f:
            ast.parse(f.read())
        print('OK: handlers/handlers_command.py: syntax OK')
    except SyntaxError as e:
        print(f'ERROR: SYNTAX ERROR line {e.lineno}: {e.msg}')

    if changes > 0:
        print(f'\nOK: {changes} fix applied successfully.')
    else:
        print('\nSKIP: No changes needed.')
    print('=' * 60)


if __name__ == '__main__':
    main()
