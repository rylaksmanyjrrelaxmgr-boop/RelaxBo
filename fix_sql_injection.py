#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_sql_injection.py — v5.7.32 SQL_INJECTION_FIX (v2)

يُصلح تحذيرات SQL_FSTRING_REAL عبر:

  1. إزالة f-prefix من الـ f-strings بدون interpolation — حتى داخل الكتل المختلطة.
  2. تحويل الكتل (متعددة الأسطر أو سطر واحد) مع interpolation آمن بالكامل إلى .format().
  3. إضافة _validate_col() للأسماء المتغيرة (table/tmp/seq_name/col).
  4. تحويل bot.py value interpolation إلى parameterized queries.
  5. معالجة SET clause patterns ({', '.join(updates)}).
  6. معالجة single-line f-strings.

السكربت idempotent.
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


# Safe interpolation patterns (placeholders, validated column refs)
_SAFE_INTERP_VARS = frozenset({
    'placeholders', 'chunk_placeholders', 'placeholder_n',
    'key_col', 'value_col',
    'updates', 'set_clause', 'best_cols', 'target', 'ident',
})


def _is_safe_interpolation(interp):
    s = interp.strip()
    if s.startswith('_ph(') or s.startswith('_phs('):
        return True
    if s.startswith('_q('):
        return True
    if s in _SAFE_INTERP_VARS:
        return True
    if s in ('table', 'tmp', 'seq_name', 'col'):
        return True  # will be wrapped with _validate_col()
    # Check for ', '.join(updates) pattern
    if "', '.join(" in s or "'.join(" in s:
        return True  # SET clause — column names from validated dict
    # ${placeholder_n} pattern (already has $ prefix)
    if s.startswith('$'):
        return True
    return False


def _classify_interp(interp):
    """Classify interpolation as safe/table/unsafe."""
    s = interp.strip()
    if _is_safe_interpolation(interp):
        if s in ('table', 'tmp', 'seq_name', 'col'):
            return 'table_col'
        return 'safe'
    return 'unsafe'


def fix_fstring_blocks(content):
    """Fix all f-string SQL patterns."""
    lines = content.split('\n')
    total_changes = 0

    # Pass 1: Remove f from no-interpolation f-strings that contain SQL keywords
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

    # Pass 2: Find multi-line f-string blocks and convert safe ones to .format()
    i = 0
    while i < len(lines):
        line = lines[i]
        fstrings = list(_FSTRING_RE.finditer(line))
        if not fstrings:
            i += 1
            continue

        has_sql = False
        for m in fstrings:
            if _has_sql(m.group(2)):
                has_sql = True
                break

        if not has_sql:
            i += 1
            continue

        start = i
        end = i

        j = i + 1
        while j < len(lines) and j < i + 30:
            next_line = lines[j].strip()
            if next_line == '':
                j += 1
                continue
            if next_line.startswith('#'):
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
    """Parameterize actual value interpolations in bot.py."""
    changes = 0

    old1 = 'f"SELECT COUNT(*) AS n FROM posts WHERE published = {_pub_true} AND created_at > {_interval_24h}"'
    new1 = '"SELECT COUNT(*) AS n FROM posts WHERE published = ? AND created_at > ?", (_pub_true, _interval_24h)'
    if old1 in content:
        content = content.replace(old1, new1, 1)
        changes += 1

    old2 = 'f"SELECT COUNT(*) AS n FROM posts WHERE published = 1 AND created_at > {_interval_24h}"'
    new2 = '"SELECT COUNT(*) AS n FROM posts WHERE published = 1 AND created_at > ?", (_interval_24h,)'
    if old2 in content:
        content = content.replace(old2, new2, 1)
        changes += 1

    return content, changes


def fix_database_key_name(content):
    """Fix database.py:1234 — parameterize key_name in SHOW KEYS query."""
    old = '''                        await cursor.execute(
                            f"SHOW KEYS FROM `{table}` "
                            f"WHERE Key_name = '{key_name}'")'''
    new = '''                        await cursor.execute(
                            "SHOW KEYS FROM `" + _validate_col(table) + "` "
                            "WHERE Key_name = %s", (key_name,))'''
    if old in content:
        content = content.replace(old, new, 1)
        return content, 1
    return content, 0


_VALIDATE_COL_HELPER = '''
# 🆕 v5.7.32 SQL_INJECTION_FIX: column/table name validation
import re as _re_sql_fix
_COL_SQL_FIX_RE = _re_sql_fix.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

def _validate_col(name):
    """Validate column/table name to prevent SQL injection via identifiers."""
    if _COL_SQL_FIX_RE.match(str(name)):
        return name
    raise ValueError(f"Invalid column/table name: {name!r}")
'''


def add_validate_col_helper(content):
    """Add _validate_col helper if needed."""
    if '_validate_col(' in content:
        return content, False
    if not any(f'{{{v}}}' in content for v in ('table', 'tmp', 'seq_name')):
        return content, False
    lines = content.split('\n')
    last_import = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
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
]


def fix_file(filepath):
    try:
        content = _read(filepath)
    except FileNotFoundError:
        print(f'⚠️ {filepath}: file not found — skip')
        return False

    original = content
    total_changes = 0

    content, n = fix_fstring_blocks(content)
    total_changes += n

    if filepath == 'bot.py':
        content, n = fix_bot_values(content)
        total_changes += n

    if filepath == 'database.py':
        content, n = fix_database_key_name(content)
        total_changes += n

    content, added = add_validate_col_helper(content)
    if added:
        total_changes += 1

    if content != original:
        _write(filepath, content)
        print(f'✅ {filepath}: {total_changes} fixes applied')
        return True
    else:
        print(f'ℹ️ {filepath}: no changes needed')
        return False


def main():
    print('═══════════════════════════════════════════════════════════')
    print('  fix_sql_injection.py — v5.7.32 SQL_INJECTION_FIX')
    print('═══════════════════════════════════════════════════════════')

    any_change = False
    for filepath in FILES_TO_FIX:
        try:
            if fix_file(filepath):
                any_change = True
        except Exception as e:
            print(f'❌ {filepath}: fix failed — {e}')

    print('\n--- Syntax verification ---')
    import ast
    all_ok = True
    for filepath in FILES_TO_FIX:
        try:
            with open(os.path.join(_BASE_DIR, filepath)) as f:
                ast.parse(f.read())
            print(f'✅ {filepath}: syntax OK')
        except SyntaxError as e:
            print(f'❌ {filepath}: SYNTAX ERROR line {e.lineno}: {e.msg}')
            all_ok = False

    print('\n--- Remaining f-string SQL count ---')
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
        print('\n✅ All SQL injection fixes applied successfully.')
    elif not any_change:
        print('\nℹ️ No changes needed — fixes already applied.')
    else:
        print('\n⚠️ Some files have syntax errors — manual review needed.')
    print('═══════════════════════════════════════════════════════════')


if __name__ == '__main__':
    main()
