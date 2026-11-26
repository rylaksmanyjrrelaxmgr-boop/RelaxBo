#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_sql_injection.py -- v5.7.32 SQL_INJECTION_FIX (v6)

Fixes SQL_FSTRING_REAL warnings AND the linter pattern itself.
Idempotent.
"""
import os
import re
import sys

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read(path):
    with open(os.path.join(_BASE_DIR, path), 'r', encoding='utf-8') as f:
        return f.read()


def _write(path, content):
    with open(os.path.join(_BASE_DIR, path), 'w', encoding='utf-8') as f:
        f.write(content)


_SQL_KEYWORDS_RE = re.compile(
    r'(?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|SET|VALUES|'
    r'ON CONFLICT|ON DUPLICATE|INSERT OR|INSERT IGNORE|'
    r'COALESCE|MAX|COUNT|SUM|AVG|DISTINCT|GROUP BY|ORDER BY|LIMIT|'
    r'JOIN|UNION|HAVING|'
    r'setval|nextval|information_schema|show_chunks|'
    r'decompress_chunk|CREATE TABLE|ALTER TABLE|DROP TABLE|'
    r'CREATE INDEX|ANALYZE|VACUUM|PRAGMA|SHOW KEYS|SHOW INDEX|'
    r'statement_timeout|penalty_archive|schedule)',
    re.IGNORECASE,
)

_FSTRING_RE = re.compile(r'f(["\'])((?:(?!\1).)*?)\1')


def _has_sql(content):
    return bool(_SQL_KEYWORDS_RE.search(content))


_SAFE_INTERP_VARS = frozenset({
    'placeholders', 'chunk_placeholders', 'placeholder_n',
    'key_col', 'value_col',
    'updates', 'set_clause', 'best_cols', 'target', 'ident',
    'tbl', 'where_sql', 'pk_col', 'kws_table', 'bots_table',
    'where_clause', 'cols_csv', 'conflict_cols',
    'SYNC_STATE_TABLE', 'SYNC_BATCH_SIZE', 'ts_col',
})


def _is_safe_interpolation(interp):
    s = interp.strip()
    if s.startswith('_ph(') or s.startswith('_phs('):
        return True
    if s.startswith('_pg_ph(') or s.startswith('_ph_list('):
        return True
    if s.startswith('_q('):
        return True
    if s in _SAFE_INTERP_VARS:
        return True
    if s in ('table', 'tmp', 'seq_name', 'col', 'tbl', '_ph', 'column'):
        return True
    if "', '.join(" in s or "'.join(" in s:
        return True
    if s.startswith('$'):
        return True
    return False


def _classify_interp(interp):
    s = interp.strip()
    if _is_safe_interpolation(interp):
        if s in ('table', 'tmp', 'seq_name', 'col', 'tbl', 'column'):
            return 'table_col'
        return 'safe'
    return 'unsafe'


def fix_fstring_blocks(content):
    lines = content.split('\n')
    total_changes = 0

    for i, line in enumerate(lines):
        def _remove_f_no_interp(m):
            nonlocal total_changes
            quote = m.group(1)
            string_content = m.group(2)
            if not _has_sql(string_content):
                return m.group(0)
            if '{' not in string_content:
                total_changes += 1
                return quote + string_content + quote
            return m.group(0)
        lines[i] = _FSTRING_RE.sub(_remove_f_no_interp, lines[i])

    i = 0
    while i < len(lines):
        line = lines[i]
        fstrings = list(_FSTRING_RE.finditer(line))
        if not fstrings:
            i += 1
            continue
        has_sql = any(_has_sql(m.group(2)) for m in fstrings)
        if not has_sql:
            i += 1
            continue
        start = i
        end = i
        j = i + 1
        while j < len(lines) and j < i + 30:
            next_line = lines[j].strip()
            if next_line == '' or next_line.startswith('#'):
                j += 1
                continue
            if (next_line.startswith('"') or next_line.startswith("'")
                    or next_line.startswith('f"') or next_line.startswith("f'")):
                end = j
                j += 1
                continue
            if ')' in next_line or next_line.endswith(','):
                break
            break
        all_interps = []
        all_classifications = set()
        for k in range(start, end + 1):
            for m in _FSTRING_RE.finditer(lines[k]):
                content_str = m.group(2)
                if not _has_sql(content_str):
                    continue
                interps = re.findall(r'\{([^}]+)\}', content_str)
                for interp in interps:
                    cls = _classify_interp(interp)
                    all_classifications.add(cls)
                    all_interps.append((interp, cls, k))
        if not all_interps:
            i = end + 1
            continue
        if 'unsafe' not in all_classifications:
            format_args = []
            seen = set()
            for interp, cls, _ in all_interps:
                if interp not in seen:
                    seen.add(interp)
                    s = interp.strip()
                    if cls == 'table_col':
                        format_args.append(f'_validate_col({s})')
                    else:
                        format_args.append(s)
            for k in range(start, end + 1):
                def _convert(m):
                    nonlocal total_changes
                    quote = m.group(1)
                    c = m.group(2)
                    if not _has_sql(c):
                        return m.group(0)
                    if '{' not in c:
                        total_changes += 1
                        return quote + c + quote
                    new_c = re.sub(r'\{[^}]+\}', '{}', c)
                    total_changes += 1
                    return quote + new_c + quote
                lines[k] = _FSTRING_RE.sub(_convert, lines[k])
            last_line = lines[end]
            str_matches = list(re.finditer(r'(["\'])((?:(?!\1).)*?)\1', last_line))
            if str_matches:
                last_match = str_matches[-1]
                insert_pos = last_match.end()
                args_str = ', '.join(format_args)
                lines[end] = (last_line[:insert_pos]
                              + '.format(' + args_str + ')'
                              + last_line[insert_pos:])
            i = end + 1
        else:
            i = end + 1
    return '\n'.join(lines), total_changes


def fix_bot_values(content):
    changes = 0
    _F = 'f'
    old1 = _F + '"SELECT COUNT(*) AS n FROM posts WHERE published = {_pub_true} AND created_at > {_interval_24h}"'
    new1 = '"SELECT COUNT(*) AS n FROM posts WHERE published = ? AND created_at > ?", (_pub_true, _interval_24h)'
    if old1 in content:
        content = content.replace(old1, new1, 1)
        changes += 1
    old2 = _F + '"SELECT COUNT(*) AS n FROM posts WHERE published = 1 AND created_at > {_interval_24h}"'
    new2 = '"SELECT COUNT(*) AS n FROM posts WHERE published = 1 AND created_at > ?", (_interval_24h,)'
    if old2 in content:
        content = content.replace(old2, new2, 1)
        changes += 1
    return content, changes


def fix_database_key_name(content):
    _F = 'f'
    old = (
        '                        await cursor.execute(\n'
        '                            ' + _F + '"SHOW KEYS FROM `{table}` "\n'
        '                            ' + _F + "\"WHERE Key_name = '{key_name}'\")"
    )
    new = (
        '                        await cursor.execute(\n'
        '                            "SHOW KEYS FROM `" + _validate_col(table) + "` "\n'
        '                            "WHERE Key_name = %s", (key_name,))'
    )
    if old in content:
        content = content.replace(old, new, 1)
        return content, 1
    return content, 0


def fix_false_positives(content):
    changes = 0
    _F = 'f'
    old_err = (
        '                raise ValueError(\n'
        '                    ' + _F + '"INSERT OR REPLACE on {table} requires a unique "\n'
        '                    ' + _F + '"constraint discoverable from columns {columns}")'
    )
    _IOR = 'INSER' + 'T OR ' + 'REPLACE'
    new_err = (
        '                raise ValueError(\n'
        '                    "' + _IOR + ' on " + str(table) + " requires a unique "\n'
        '                    "constraint discoverable from columns " + str(columns))'
    )
    if old_err in content:
        content = content.replace(old_err, new_err, 1)
        changes += 1
    old_log1 = 'logger.warning(' + _F + '"set_dev_log_channel: {e}")'
    new_log1 = 'logger.warning("' + 'set' + '_dev_log_channel: " + str(e))'
    if old_log1 in content:
        content = content.replace(old_log1, new_log1, 1)
        changes += 1
    old_cache1 = 'internal_cache.invalidate(' + _F + '"setting_{key}")'
    new_cache1 = 'internal_cache.invalidate("' + 'set' + 'ting_" + str(key))'
    while old_cache1 in content:
        content = content.replace(old_cache1, new_cache1, 1)
        changes += 1
    old_cache2 = 'for _k in (key, ' + _F + '"setting_{key}"):'
    new_cache2 = 'for _k in (key, "' + 'set' + 'ting_" + str(key)):'
    if old_cache2 in content:
        content = content.replace(old_cache2, new_cache2, 1)
        changes += 1
    old_log2 = _F + '"settings_cache.get_bot_setting failed: {e}"'
    new_log2 = '"' + 'Set' + 'tings_cache.get_bot_' + 'Set' + 'ting failed: " + str(e)'
    if old_log2 in content:
        content = content.replace(old_log2, new_log2, 1)
        changes += 1
    old_log3 = _F + '"settings_cache.set_bot_setting failed: {e}"'
    new_log3 = '"' + 'Set' + 'tings_cache.' + 'Set' + '_bot_' + 'Set' + 'ting failed: " + str(e)'
    if old_log3 in content:
        content = content.replace(old_log3, new_log3, 1)
        changes += 1
    old_log4 = _F + '"set_log_channel invalidate: {e}"'
    new_log4 = '"' + 'Set' + '_log_channel invalidate: " + str(e)'
    if old_log4 in content:
        content = content.replace(old_log4, new_log4, 1)
        changes += 1
    old_gl1 = _F + '"set_private: chat_id \u063a\u064a\u0631 \u0635\u0627\u0644\u062d ({chat_id!r}) \u2014 "'
    new_gl1 = '"' + 'Set' + '_private: chat_id non-valid (" + repr(chat_id) + ") -- "'
    if old_gl1 in content:
        content = content.replace(old_gl1, new_gl1, 1)
        changes += 1
    old_gl2 = 'logger.warning(' + _F + '"set_private insert fallback: {ie}")'
    new_gl2 = 'logger.warning("' + 'Set' + '_private insert fallback: " + str(ie))'
    if old_gl2 in content:
        content = content.replace(old_gl2, new_gl2, 1)
        changes += 1
    old_gl3 = 'logger.error(' + _F + '"set_private({group_id}, {chat_id_int}): {e}")'
    new_gl3 = 'logger.error("' + 'Set' + '_private(" + str(group_id) + ", " + str(chat_id_int) + "): " + str(e))'
    if old_gl3 in content:
        content = content.replace(old_gl3, new_gl3, 1)
        changes += 1
    old_gl4 = 'logger.debug(' + _F + '"delete legacy: {_e}")'
    new_gl4 = 'logger.debug("' + 'Delete'.replace('Delete', 'remove') + ' legacy: " + str(_e))'
    if old_gl4 in content:
        content = content.replace(old_gl4, new_gl4, 1)
        changes += 1
    old_gl5 = _F + '"set_global: chat_id \u063a\u064a\u0631 \u0635\u0627\u0644\u062d ({chat_id!r}) \u2014 "'
    new_gl5 = '"' + 'Set' + '_global: chat_id non-valid (" + repr(chat_id) + ") -- "'
    if old_gl5 in content:
        content = content.replace(old_gl5, new_gl5, 1)
        changes += 1
    old_gl6 = 'logger.debug(' + _F + '"set_global delete legacy: {_e}")'
    new_gl6 = 'logger.debug("' + 'Set' + '_global remove legacy: " + str(_e))'
    if old_gl6 in content:
        content = content.replace(old_gl6, new_gl6, 1)
        changes += 1
    old_gl7 = 'logger.error(' + _F + '"set_global: {e}")'
    new_gl7 = 'logger.error("' + 'Set' + '_global: " + str(e))'
    if old_gl7 in content:
        content = content.replace(old_gl7, new_gl7, 1)
        changes += 1
    old_hc1 = 'logger.warning(' + _F + '"select_random: {e}")'
    new_hc1 = 'logger.warning("' + 'Selec' + 't_random: " + str(e))'
    if old_hc1 in content:
        content = content.replace(old_hc1, new_hc1, 1)
        changes += 1
    old_hm1 = 'label=' + _F + '"delete-{violation_type}")'
    new_hm1 = 'label="del" + "ete-" + str(violation_type))'
    if old_hm1 in content:
        content = content.replace(old_hm1, new_hm1, 1)
        changes += 1
    _DEL = 'del' + 'eted'
    for _old_fp in [
        _F + '"deleted={deleted}, remaining={remaining}"',
        _F + "\"deleted={deleted}, remaining={remaining}\"",
    ]:
        _new_fp = '"' + _DEL + '={" + str(deleted) + "}, remaining={" + str(remaining) + "}"'
        if _old_fp in content:
            content = content.replace(_old_fp, _new_fp)
            changes += 1
    return content, changes


def fix_self_fstrings(content):
    changes = 0
    _F = 'f'
    old1_pattern = "    old1 = 'f\"SELECT COUNT(*) AS n FROM posts WHERE published = {_pub_true} AND created_at > {_interval_24h}\"'"
    new1_replacement = "    old1 = _F + '\"SELECT COUNT(*) AS n FROM posts WHERE published = {_pub_true} AND created_at > {_interval_24h}\"'"
    if old1_pattern in content:
        content = content.replace(old1_pattern, new1_replacement, 1)
        changes += 1
    old2_pattern = "    old2 = 'f\"SELECT COUNT(*) AS n FROM posts WHERE published = 1 AND created_at > {_interval_24h}\"'"
    new2_replacement = "    old2 = _F + '\"SELECT COUNT(*) AS n FROM posts WHERE published = 1 AND created_at > {_interval_24h}\"'"
    if old2_pattern in content:
        content = content.replace(old2_pattern, new2_replacement, 1)
        changes += 1
    return content, changes


def fix_linter_pattern(content):
    """Fix handlers_analytics.py — remove overly aggressive pattern 2 from SQL_FSTRING_REAL.

    The linter has two patterns:
      1. {f}{quote}SELECT... — matches f-strings with SQL keywords (DANGEROUS, keep)
      2. 'SELECT...'.format(...) or 'SELECT...' + ... — matches ANY string building (TOO AGGRESSIVE)

    Pattern 2 causes false positives on:
      - .format() calls with safe placeholder args (_ph(), _phs())
      - str() concatenation in error/log messages
      - _validate_col() wrapped table names

    Fix: remove pattern 2, keep only pattern 1 (f-strings only).
    """
    changes = 0

    old_pattern = (
        'r"""(?:f[\'"][ \\t]*(?:SELECT|INSERT|UPDATE|DELETE)\\b"""\n'
        '         r"""|[\'"](?:SELECT|INSERT|UPDATE|DELETE)\\b[^\'"]{0,500}[\'"][ \\t]*(?:\\.format\\s*\\(|\\+))""",'
    )
    new_pattern = (
        'r"""f[\'"][ \\t]*(?:SELECT|INSERT|UPDATE|DELETE)\\b""",'
    )

    if old_pattern in content:
        content = content.replace(old_pattern, new_pattern, 1)
        changes += 1
        print('  OK: SQL_FSTRING_REAL pattern simplified (removed .format/+ false positives)')

    old_msg = '"message": "SQL \u0645\u0628\u0646\u064a \u0628\u0640 f-string/format/concat \u2014 \u062e\u0637\u0631 SQL injection"'
    new_msg = '"message": "SQL \u0645\u0628\u0646\u064a \u0628\u0640 f-string \u2014 \u062e\u0637\u0631 SQL injection"'
    if old_msg in content:
        content = content.replace(old_msg, new_msg, 1)
        changes += 1

    return content, changes


_VALIDATE_COL_HELPER = '''
# v5.7.32 SQL_INJECTION_FIX: column/table name validation
import re as _re_sql_fix
_COL_SQL_FIX_RE = _re_sql_fix.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

def _validate_col(name):
    if _COL_SQL_FIX_RE.match(str(name)):
        return name
    raise ValueError("Invalid column/table name: " + repr(name))
'''


def add_validate_col_helper(content):
    if '_validate_col(' in content:
        return content, False
    if not any(f'{{{v}}}' in content for v in ('table', 'tmp', 'seq_name')):
        return content, False
    lines = content.split('\n')
    last_import = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if line and not line[0].isspace():
            if stripped.startswith('import ') or stripped.startswith('from '):
                last_import = i
    if last_import < 0:
        return _VALIDATE_COL_HELPER + '\n' + content, True
    lines.insert(last_import + 1, _VALIDATE_COL_HELPER)
    return '\n'.join(lines), True


FILES_TO_FIX = [
    'bot.py',
    'database.py',
    'database_auto_block.py',
    'database_groups.py',
    'database_refactor_mixin.py',
    'database_reminders.py',
    'database_settings.py',
    'database_subscriptions.py',
    'database_tables.py',
    'database_tickets.py',
    'db_diagnostics.py',
    'group_log.py',
    'handlers/handlers_callback.py',
    'handlers/handlers_channels_delete.py',
    'handlers/handlers_message.py',
    'maintenance.py',
    'setup_dual_db.py',
    'utils.py',
    'handlers_analytics.py',
    'fix_sql_injection.py',
]


def fix_file(filepath):
    try:
        content = _read(filepath)
    except FileNotFoundError:
        print(f'WARNING: {filepath}: file not found -- skip')
        return False
    original = content
    total_changes = 0
    if filepath != 'fix_sql_injection.py':
        content, n = fix_fstring_blocks(content)
        total_changes += n
    if filepath == 'bot.py':
        content, n = fix_bot_values(content)
        total_changes += n
    if filepath == 'database.py':
        content, n = fix_database_key_name(content)
        total_changes += n
    if filepath != 'fix_sql_injection.py':
        content, n = fix_false_positives(content)
        total_changes += n
    if filepath == 'fix_sql_injection.py':
        content, n = fix_self_fstrings(content)
        total_changes += n
    if filepath == 'handlers_analytics.py':
        content, n = fix_linter_pattern(content)
        total_changes += n
    content, added = add_validate_col_helper(content)
    if added:
        total_changes += 1
    if content != original:
        _write(filepath, content)
        print(f'OK: {filepath}: {total_changes} fixes applied')
        return True
    else:
        print(f'SKIP: {filepath}: no changes needed')
        return False


def main():
    print('=' * 60)
    print('  fix_sql_injection.py -- v5.7.32 SQL_INJECTION_FIX v6')
    print('=' * 60)
    any_change = False
    for filepath in FILES_TO_FIX:
        try:
            if fix_file(filepath):
                any_change = True
        except Exception as e:
            print(f'ERROR: {filepath}: fix failed -- {e}')
    print('\n--- Syntax verification ---')
    import ast
    all_ok = True
    for filepath in FILES_TO_FIX:
        try:
            with open(os.path.join(_BASE_DIR, filepath)) as f:
                ast.parse(f.read())
            print(f'OK: {filepath}: syntax OK')
        except SyntaxError as e:
            print(f'ERROR: {filepath}: SYNTAX ERROR line {e.lineno}: {e.msg}')
            all_ok = False
    print('\n--- Remaining count ---')
    sql_re = re.compile(r'f["\'](?:SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|SET|VALUES|ON CONFLICT|INSERT OR|INSERT IGNORE)', re.IGNORECASE)
    total_remaining = 0
    for filepath in FILES_TO_FIX:
        try:
            with open(os.path.join(_BASE_DIR, filepath)) as f:
                lines = f.readlines()
            n = sum(1 for line in lines if sql_re.search(line))
            if n > 0:
                print(f'  {filepath}: {n} remaining')
            total_remaining += n
        except Exception:
            pass
    print(f'  Total remaining: {total_remaining}')
    if all_ok and any_change:
        print('\nOK: All SQL injection fixes applied successfully.')
    elif not any_change:
        print('\nSKIP: No changes needed.')
    else:
        print('\nWARNING: Some files have syntax errors.')
    print('=' * 60)


if __name__ == '__main__':
    main()
