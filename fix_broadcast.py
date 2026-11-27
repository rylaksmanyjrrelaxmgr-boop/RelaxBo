#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_broadcast.py -- v5.7.36 (v3)

Adds _do_broadcast method with:
  - Progress updates every 100 users
  - Final report sent via safe_send (not _safe_edit_or_send)
  - Logging for Render logs
  - Removes old v1/v2 before inserting v3

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


_NL = chr(10)


def fix_broadcast():
    path = 'handlers/handlers_command.py'
    content = _read(path)

    # Remove old _do_broadcast if present (v1/v2 had bugs)
    if 'async def _do_broadcast' in content:
        start = content.find('    @staticmethod' + _NL + '    async def _do_broadcast(')
        if start >= 0:
            next_static = content.find('    @staticmethod', start + 50)
            if next_static >= 0:
                content = content[:start] + content[next_static:]
            else:
                content = content[:start].rstrip() + _NL
        print('  OK: removed old _do_broadcast')

    lines = [
        '    @staticmethod',
        '    async def _do_broadcast(update, context, text: str) -> None:',
        '        """v5.7.36 v3: Broadcast with report."""',
        '        admin_id = update.effective_user.id if update.effective_user else 0',
        '        admin_chat = update.effective_chat.id if update.effective_chat else admin_id',
        '',
        '        status_msg = None',
        '        try:',
        '            status_msg = await safe_send(',
        '                context.bot, admin_chat,',
        '                "\u23f3 <b>Broadcasting...</b>",',
        '                parse_mode=\'HTML\',',
        '            )',
        '        except Exception as e:',
        '            logger.warning("_do_broadcast status: %s", e)',
        '',
        '        sent_ok = 0',
        '        sent_fail = 0',
        '        skipped = 0',
        '        total = 0',
        '        batch_delay = 0.05',
        '        batch_size = 30',
        '        batch_count = 0',
        '        progress_interval = 100',
        '',
        '        try:',
        '            async for user_row in DB.iter_all_users(batch_size=500):',
        '                uid = user_row.get("user_id")',
        '                banned = user_row.get("banned", 0)',
        '                if not uid or banned:',
        '                    skipped += 1',
        '                    continue',
        '                total += 1',
        '                try:',
        '                    await safe_send(',
        '                        context.bot, uid, text,',
        '                        parse_mode=\'HTML\',',
        '                    )',
        '                    sent_ok += 1',
        '                except Exception:',
        '                    sent_fail += 1',
        '                batch_count += 1',
        '                if batch_count >= batch_size:',
        '                    await asyncio.sleep(batch_delay)',
        '                    batch_count = 0',
        '                if total % progress_interval == 0:',
        '                    try:',
        '                        prog_text = (',
        '                            "\u23f3 <b>Broadcasting...</b>\\n"',
        '                            f"\U0001f4ca Processed: <b>{total}</b>\\n"',
        '                            f"\u2705 Sent: <b>{sent_ok}</b> | \u274c Failed: <b>{sent_fail}</b>"',
        '                        )',
        '                        if status_msg:',
        '                            try:',
        '                                await status_msg.edit_text(prog_text, parse_mode=\'HTML\')',
        '                            except Exception:',
        '                                pass',
        '                    except Exception:',
        '                        pass',
        '        except Exception as e:',
        '            logger.error("_do_broadcast iter: %s", e, exc_info=True)',
        '',
        '        report = (',
        '            "\u2705 <b>Broadcast Complete</b>\\n\\n"',
        '            f"\U0001f4e4 Sent: <b>{sent_ok}</b>\\n"',
        '            f"\u274c Failed: <b>{sent_fail}</b>\\n"',
        '            f"\u23ed\ufe0f Skipped: <b>{skipped}</b>\\n"',
        '            f"\U0001f4ca Total: <b>{total}</b>"',
        '        )',
        '',
        '        try:',
        '            await safe_send(',
        '                context.bot, admin_chat, report,',
        '                parse_mode=\'HTML\',',
        '            )',
        '        except Exception as e:',
        '            logger.error("_do_broadcast report: %s", e)',
        '',
        '        if status_msg:',
        '            try:',
        '                await status_msg.edit_text(report, parse_mode=\'HTML\')',
        '            except Exception:',
        '                pass',
        '',
        '        logger.info(',
        '            "BROADCAST REPORT: ok=%d fail=%d skip=%d total=%d",',
        '            sent_ok, sent_fail, skipped, total,',
        '        )',
        '',
    ]

    method_text = _NL.join(lines)

    insert_point = content.find('    @staticmethod' + _NL + '    async def set_force(')
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

    new_content = content[:insert_point] + method_text + _NL + content[insert_point:]

    _write(path, new_content)
    print('  OK: added _do_broadcast v3')
    return 1


def main():
    print('=' * 60)
    print('  fix_broadcast.py -- v5.7.36 v3')
    print('=' * 60)

    print(_NL + 'handlers/handlers_command.py:')
    changes = fix_broadcast()

    print(_NL + '--- Syntax verification ---')
    import ast
    try:
        with open(os.path.join(_BASE_DIR, 'handlers/handlers_command.py')) as f:
            ast.parse(f.read())
        print('OK: syntax OK')
    except SyntaxError as e:
        print(f'ERROR: SYNTAX ERROR line {e.lineno}: {e.msg}')

    if changes > 0:
        print(f'{_NL}OK: {changes} fix applied.')
    else:
        print(f'{_NL}SKIP: No changes needed.')
    print('=' * 60)


if __name__ == '__main__':
    main()
