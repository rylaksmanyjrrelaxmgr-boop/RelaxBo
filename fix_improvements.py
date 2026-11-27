#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_improvements.py -- v5.7.37

Adds proposed improvements:
  1. /health command (memory, CPU, DB pool, BG tasks, uptime, metrics)
  2. Weekly performance report (sent to developer every 7 days)
  3. Registers /health in ADMIN_COMMANDS and command list

Note: requests.post in detectors already runs in thread pool
via _run_in_pool -- does NOT block event loop. No change needed.

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


_HEALTH_METHOD = _NL.join([
    '    @staticmethod',
    '    async def health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:',
    '        """v5.7.37: Health report."""',
    '        user_id = update.effective_user.id if update.effective_user else 0',
    '        if not CONFIG.is_developer(user_id):',
    '            return',
    '        try:',
    '            import psutil',
    '            import time as _time',
    '            proc = psutil.Process()',
    '            mem_info = proc.memory_info()',
    '            mem_mb = mem_info.rss / (1024 * 1024)',
    '            cpu_pct = proc.cpu_percent(interval=0.5)',
    '            uptime_s = int(_time.monotonic() - _BOT_METRICS.get("started_at", _time.monotonic()))',
    '            uptime_h = uptime_s // 3600',
    '            uptime_m = (uptime_s % 3600) // 60',
    '            pool_stats = {}',
    '            try:',
    '                pool = getattr(DB, "_pool", None)',
    '                if pool:',
    '                    pool_stats["size"] = getattr(pool, "get_size", lambda: "?")()',
    '                    pool_stats["free"] = getattr(pool, "get_idle_size", lambda: "?")()',
    '            except Exception:',
    '                pool_stats = {"size": "?", "free": "?"}',
    '            bg_count = 0',
    '            try:',
    '                bg_count = len([t for t in asyncio.all_tasks() if not t.done()])',
    '            except Exception:',
    '                pass',
    '            posts_ok = _BOT_METRICS.get("posts_success", 0)',
    '            posts_fail = _BOT_METRICS.get("posts_failed", 0)',
    '            cmds = _BOT_METRICS.get("commands_total", 0)',
    '            pings = _BOT_METRICS.get("pings_total", 0)',
    '            ping_min = _BOT_METRICS.get("ping_min_ms", "?")',
    '            ping_max = _BOT_METRICS.get("ping_max_ms", "?")',
    '            report = (',
    '                "\U0001f4ca <b>Health Report</b>\\n"',
    '                "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\\n"',
    '                f"\U0001f4be Memory: <b>{mem_mb:.1f}MB</b>\\n"',
    '                f"\u2699\ufe0f CPU: <b>{cpu_pct:.1f}%</b>\\n"',
    '                f"\u23f1 Uptime: <b>{uptime_h}h {uptime_m}m</b>\\n"',
    '                f"\U0001f4be DB Pool: <b>{pool_stats.get(\'free\', \'?\')}/{pool_stats.get(\'size\', \'?\')}</b>\\n"',
    '                f"\u2699\ufe0f BG Tasks: <b>{bg_count}</b> active\\n"',
    '                "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\\n"',
    '                f"\u2705 Posts OK: <b>{posts_ok}</b> | \u274c Fail: <b>{posts_fail}</b>\\n"',
    '                f"\u23f1 Commands: <b>{cmds}</b> | Pings: <b>{pings}</b>\\n"',
    '                f"\U0001f4cf Ping: min=<b>{ping_min}ms</b> max=<b>{ping_max}ms</b>"',
    '            )',
    '            try:',
    '                await safe_send(',
    '                    context.bot, update.effective_chat.id, report,',
    '                    parse_mode=\'HTML\',',
    '                )',
    '            except Exception:',
    '                pass',
    '        except Exception as e:',
    '            logger.error("health command: %s", e, exc_info=True)',
    '',
])


def fix_health_command():
    path = 'handlers/handlers_command.py'
    content = _read(path)
    if 'async def health(' in content:
        print('  SKIP: /health already present')
        return 0
    insert_point = content.find('    @staticmethod' + _NL + '    async def set_force(')
    if insert_point < 0:
        print('  WARN: insertion point not found')
        return 0
    new_content = content[:insert_point] + _HEALTH_METHOD + _NL + content[insert_point:]
    _write(path, new_content)
    print('  OK: added /health command')
    return 1


_WEEKLY_REPORT_FUNC = _NL.join([
    'async def _weekly_perf_report(bot) -> None:',
    '    """v5.7.37: Weekly performance report to developer."""',
    '    import time as _time',
    '    while True:',
    '        await asyncio.sleep(7 * 24 * 3600)',
    '        try:',
    '            dev_id = int(getattr(CONFIG, "PRIMARY_OWNER_ID", 0) or 0)',
    '            if not dev_id:',
    '                continue',
    '            uptime_s = int(_time.monotonic() - _BOT_METRICS.get("started_at", _time.monotonic()))',
    '            uptime_d = uptime_s // 86400',
    '            uptime_h = (uptime_s % 86400) // 3600',
    '            posts_ok = _BOT_METRICS.get("posts_success", 0)',
    '            posts_fail = _BOT_METRICS.get("posts_failed", 0)',
    '            cmds = _BOT_METRICS.get("commands_total", 0)',
    '            pings = _BOT_METRICS.get("pings_total", 0)',
    '            ping_min = _BOT_METRICS.get("ping_min_ms", "?")',
    '            ping_max = _BOT_METRICS.get("ping_max_ms", "?")',
    '            ping_avg = (_BOT_METRICS.get("ping_sum_ms", 0) / pings) if pings else 0',
    '            report = (',
    '                "\U0001f4ca <b>Weekly Performance Report</b>\\n"',
    '                "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\\n"',
    '                f"\u23f1 Uptime: <b>{uptime_d}d {uptime_h}h</b>\\n"',
    '                f"\u2705 Posts OK: <b>{posts_ok}</b>\\n"',
    '                f"\u274c Posts Fail: <b>{posts_fail}</b>\\n"',
    '                f"\u23f1 Commands: <b>{cmds}</b>\\n"',
    '                f"\U0001f4cf Pings: <b>{pings}</b> (avg={ping_avg:.0f}ms)\\n"',
    '                f"   min=<b>{ping_min}ms</b> max=<b>{ping_max}ms</b>"',
    '            )',
    '            try:',
    '                await safe_send(bot, dev_id, report, parse_mode=\'HTML\')',
    '                logger.info("weekly report sent to dev %d", dev_id)',
    '            except Exception as e:',
    '                logger.warning("weekly report send: %s", e)',
    '        except Exception as e:',
    '            logger.error("weekly report loop: %s", e, exc_info=True)',
    '',
])


def fix_weekly_report():
    path = 'bot.py'
    content = _read(path)
    if '_weekly_perf_report' in content:
        print('  SKIP: weekly report already present')
        return 0
    marker = 'def record_bot_metric(key: str, value: Any = 1) -> None:'
    idx = content.find(marker)
    if idx < 0:
        marker = '_bg_task_specs: List[Tuple[str, Any, tuple]] = ['
        idx = content.find(marker)
        if idx < 0:
            print('  WARN: could not find insertion point')
            return 0
    next_def = content.find(_NL + _NL + 'def ', idx + 100)
    if next_def < 0:
        next_def = content.find(_NL + 'async def ', idx + 100)
    if next_def < 0:
        next_def = idx + 500
    insert_point = next_def + 2
    new_content = content[:insert_point] + _NL + _WEEKLY_REPORT_FUNC + _NL + content[insert_point:]
    old_spec = '        ("keep_alive", keep_alive, ()),'
    new_spec = ('        ("keep_alive", keep_alive, ()),\n'
                '        ("weekly_perf_report", _weekly_perf_report, (app.bot,)),')
    if old_spec in new_content:
        new_content = new_content.replace(old_spec, new_spec, 1)
    _write(path, new_content)
    print('  OK: added weekly perf report task')
    return 1


def fix_register_health():
    path = 'bot.py'
    content = _read(path)
    changes = 0
    old_reg = '        ("broadcast", CommandHandlers.broadcast),'
    new_reg = ('        ("broadcast", CommandHandlers.broadcast),\n'
               '        ("health", CommandHandlers.health),')
    if old_reg in content and 'CommandHandlers.health' not in content:
        content = content.replace(old_reg, new_reg, 1)
        changes += 1
        print('  OK: registered /health command')
    old_admin2 = '    ("broadcast",'
    new_admin2 = '    ("health", "\U0001f4ca Health Report"),\n    ("broadcast",'
    if old_admin2 in content and '("health",' not in content:
        content = content.replace(old_admin2, new_admin2, 1)
        changes += 1
        print('  OK: added /health to ADMIN_COMMANDS')
    if changes > 0:
        _write(path, content)
    return changes


def main():
    print('=' * 60)
    print('  fix_improvements.py -- v5.7.37')
    print('=' * 60)
    any_change = False
    print(_NL + 'handlers/handlers_command.py:')
    if fix_health_command() > 0:
        any_change = True
    print(_NL + 'bot.py:')
    if fix_register_health() > 0:
        any_change = True
    if fix_weekly_report() > 0:
        any_change = True
    print(_NL + '--- Syntax verification ---')
    import ast
    all_ok = True
    for filepath in ['handlers/handlers_command.py', 'bot.py']:
        try:
            with open(os.path.join(_BASE_DIR, filepath)) as f:
                ast.parse(f.read())
            print(f'OK: {filepath}: syntax OK')
        except SyntaxError as e:
            print(f'ERROR: {filepath}: SYNTAX ERROR line {e.lineno}: {e.msg}')
            all_ok = False
    if all_ok and any_change:
        print(f'{_NL}OK: All improvements applied successfully.')
    elif not any_change:
        print(f'{_NL}SKIP: No changes needed.')
    else:
        print(f'{_NL}WARNING: Some files have syntax errors.')
    print('=' * 60)


if __name__ == '__main__':
    main()
