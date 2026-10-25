#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
handlers_analytics.py — واجهة التحليلات المتقدمة (v1.3.8 — AUDIT-EXECUTOR-ISOLATION)
================================================================================
v1.3.8 — فوق v1.3.7:

    🔴 FIX-AUDIT-EXECUTOR (CRITICAL):
        `_audit_run_reports` كانت تستخدم `asyncio.to_thread` الذي
        يستنزف `ThreadPoolExecutor` الافتراضي المشترك مع `handle_group`
        و`_process_auto_reply` في `handlers_message.py`.

        النتيجة: أثناء /audit (10-30s)، كل رسالة جديدة تنتظر timeoutها
        الكامل (5s ctx + 1.5×3 score + 3s DB + 2s file = ~15s).

        الحل: `_AUDIT_EXECUTOR` مخصص بـ max_workers=2 معزول تماماً.
        `Semaphore(2)` داخل `_audit_run_reports` يطابقه.

    🔴 FIX-COLLECT-FILES-SYNC (HIGH):
        `_audit_collect_files` كانت `async` لكنها تعمل بالكامل
        متزامنة (rglob + resolve على 200 ملف) = 2-5s حجب للحلقة.
        الحل: `_audit_collect_files_sync` في `_AUDIT_EXECUTOR`.

    🔴 FIX-CMD-FILES-SYNC (HIGH):
        `cmd_files` تستورد 200 وحدة (importlib متزامن) على الحلقة
        الرئيسية = 10-30s حجب.
        الحل: `_cmd_files_scan_sync` في `_AUDIT_EXECUTOR`.

v1.3.7 — محفوظ بالكامل:
    🔴 FIX-SQL-FP-1: `SQL_STRING_FORMAT` → `SQL_FSTRING_REAL`
    🔴 FIX-EVAL-EXEC-FP-2: `EVAL_USE` / `EXEC_USE`
    🔴 FIX-EXCEPT-PASS-3: `EXCEPT_PASS` → AST دقيق
    🔴 FIX-LOG-FSTRING-FP-4: `LOG_FSTRING`
    🟢 FIX-SELF-SCAN-5: `_audit_collect_files`
    🟢 FIX-DECLARED-6: `_DECLARED_FIXES_V5713`

v1.3.6 — محفوظ بالكامل:
    🆕 AUDIT-1: /audit + /audit_full + /audit_critical + audit_btn
    🆕 AUDIT-2: 15 قاعدة pattern + 5 AST + 3 PTB + 2 bot-specific
    🆕 AUDIT-3: تصدير Markdown/JSON
    🆕 AUDIT-4: _MAX_AUDIT_FILES=200, _AUDIT_TIMEOUT_SEC=30

v1.3.5 — محفوظ: FILES-SCAN-1..8
v1.3.4 — محفوظ: FIX-VERSIONS-PATH/ERR
v1.3.3 — محفوظ: AUTO-1..6
v1.3.2 — محفوظ: CLEAN-1..3
v1.3.1 — محفوظ: FIX-1, NEW-1..3
v1.3.0 — محفوظ: PERF-1..2, FEAT-1..3, HA1..HA31
v1.2.3..1.1.1 — محفوظة
================================================================================
"""

import logging
import re as _re_mod
import io
import time
import html as _html_mod
import traceback as _tb
import importlib
import asyncio
import ast as _ast_mod
import json as _json_mod
import sys as _sys_mod
import concurrent.futures
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass as _dataclass, field as _dc_field, asdict as _dc_asdict
from typing import Optional, Dict, Any, List, Tuple, Callable, Awaitable, Union

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ContextTypes, CallbackQueryHandler, CommandHandler,
)
from telegram.error import BadRequest

from config import CONFIG
from database import DB
from utils import (
    CB, TimeUtils, safe_send, KeyboardFactory,
    TranslationManager,
)

logger = logging.getLogger(__name__)


ANALYTICS_BUTTONS = (
    "admin_analytics",
    "growth_30d_btn",
    "top_channels_btn",
    "publish_stats_btn",
    "channels_rate_btn",
    "subscriptions_btn",
    "pool_live_btn",
    "slow_queries_btn",
    "export_excel_btn",
    "refresh_btn",
    "full_health_btn",
    "latency_btn",
    "databases_btn",
    "autotune_btn",
    "files_btn",
    "audit_btn",
    "audit_md_btn",
    "audit_json_btn",
)


# ═══════════════════════════════════════════════════════════════════════
# 🆕 v1.3.8 FIX-AUDIT-EXECUTOR: ThreadPoolExecutor مخصص ومعزول
# ═══════════════════════════════════════════════════════════════════════
# لماذا؟ `asyncio.to_thread` يستخدم ThreadPoolExecutor الافتراضي المشترك
# مع `handle_group` و`_process_auto_reply` في handlers_message.py. أثناء
# /audit (10-30s)، ينفد الـ pool → كل رسالة جديدة تنتظر timeoutها الكامل.
# الحل: executor مخصص بـ max_workers=2 معزول تماماً عن الحلقة الرئيسية.
# ═══════════════════════════════════════════════════════════════════════
_AUDIT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="audit-worker",
)
_AUDIT_EXECUTOR_MAX_WORKERS = 2
_AUDIT_SEMAPHORE_LIMIT = 2


def _get_audit_executor() -> concurrent.futures.Executor:
    """يعيد executor audit المخصص (معزول عن ThreadPool الافتراضي)."""
    return _AUDIT_EXECUTOR


# ═══════════════════════════════════════════════════════════════════════
# FILES-SCAN helpers (v1.3.5 — محفوظ)
# ═══════════════════════════════════════════════════════════════════════

_EXCLUDED_DIRS = frozenset({
    ".git", "__pycache__", "venv", ".venv", "env", ".env",
    "node_modules", "tests", "test", ".pytest_cache",
    ".mypy_cache", ".tox", "build", "dist", ".eggs",
    "site-packages", ".idea", ".vscode", ".vscode-test",
    "migrations",
})

_SKIP_FILENAMES = frozenset({
    "setup.py", "conftest.py", "__init__.py",
})

_MAX_FILES_SCAN = 500


def _find_project_root() -> Path:
    """Determine project root — try cwd, then walk up from __file__."""
    try:
        cwd = Path.cwd()
        if (cwd / "bot.py").exists() or (cwd / "config.py").exists():
            return cwd
    except Exception:
        pass
    try:
        here = Path(__file__).resolve().parent
        for _ in range(4):
            if (here / "bot.py").exists() or (here / "config.py").exists():
                return here
            parent = here.parent
            if parent == here:
                break
            here = parent
    except Exception:
        pass
    try:
        return Path.cwd()
    except Exception:
        return Path(".")


def _file_to_module_path(rel_path: Path) -> str:
    """Convert relative .py path to module path."""
    try:
        parts = rel_path.with_suffix("").parts
        return ".".join(parts)
    except Exception:
        return ""


def _extract_version(mod) -> Optional[str]:
    """Extract version from module."""
    if mod is None:
        return None
    try:
        v = (
            getattr(mod, "VERSION", None)
            or getattr(mod, "__version__", None)
            or getattr(mod, "_VERSION", None)
        )
        if v:
            return str(v)
    except Exception:
        pass
    try:
        doc = getattr(mod, "__doc__", "") or ""
        m = _re_mod.search(r"v?(\d+\.\d+\.\d+)", doc[:800])
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def _try_import_any(paths: List[str]) -> Tuple[Optional[Any], Optional[str]]:
    """Try multiple import paths, return first success + last error."""
    last_err: Optional[str] = None
    for p in paths:
        if not p:
            continue
        try:
            return importlib.import_module(p), None
        except ImportError as ie:
            last_err = f"ImportError: {str(ie)[:80]}"
            continue
        except SyntaxError as se:
            last_err = f"SyntaxError: {str(se)[:80]}"
            continue
        except Exception as ex:
            last_err = f"{type(ex).__name__}: {str(ex)[:80]}"
            continue
    return None, last_err


# ═══════════════════════════════════════════════════════════════════════
# AUDIT-SECTION (v1.3.6 + FIXED v1.3.7)
# ═══════════════════════════════════════════════════════════════════════

_SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
_SEVERITY_ICONS = {
    "CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡",
    "LOW": "🔵", "INFO": "⚪",
}
_MAX_AUDIT_FILES = 200
_AUDIT_TIMEOUT_SEC = 30


@_dataclass
class _AuditFinding:
    rule_id: str
    severity: str
    line: int
    message: str
    snippet: str = ""
    suggestion: str = ""
    category: str = "general"


@_dataclass
class _AuditReport:
    file: str = ""
    file_size_bytes: int = 0
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    timestamp: str = ""
    findings: List[_AuditFinding] = _dc_field(default_factory=list)
    stats: Dict[str, Any] = _dc_field(default_factory=dict)
    parse_error: Optional[str] = None
    imports: List[str] = _dc_field(default_factory=list)
    declared_version: Optional[str] = None
    fixes_found: List[str] = _dc_field(default_factory=list)
    fixes_missing: List[str] = _dc_field(default_factory=list)


# 🆕 v1.3.7 FIX-DECLARED-6: أنماط محدَّثة لتطابق bot.py v5.7.16
_DECLARED_FIXES_V5713: Dict[str, List[str]] = {
    "P0-FIX-1: post_init no manual call": [
        r"_post_init_executed",
        r"post_init\s+مُدار\s+من\s+PTB",
    ],
    # 🆕 FIX-DECLARED-6: في v5.7.16 لا يوجد manual unbind — يكفي idempotency flag
    "P0-FIX-2: post_stop unbind _post_stop": [
        r"_post_stop_executed",
    ],
    "P0-FIX-3: watch_runner resets only 2xx/3xx": [
        r"200\s*<=\s*resp\.status\s*<\s*400",
    ],
    # 🆕 FIX-DECLARED-6: يطابق الكود الفعلي `if not result:\n    continue`
    "P1-FIX-4: collect_admin_ids continue on empty": [
        r"if\s+not\s+result:\s*\n\s*continue",
        r"continue\s*\n\s*for\s+a\s+in\s+result",
    ],
    "P1-FIX-5: pre_checkout price validation": [
        r"expected_f\s*<=\s*0",
        r"_amounts_match\(expected_f",
    ],
    "P1-FIX-6: successful_payment dev notify": [
        r"create_gift_code.*exception",
        r"gift_code\s+exception",
    ],
    "P1-FIX-7: pid_is_bot_process cwd check": [
        r"/proc/\{pid\}/cwd",
        r"os\.readlink",
    ],
    "P2-FIX-8: token regex": [
        r"_TG_TOKEN_RE\s*=\s*re\.compile",
        r"\^\\d\{8,10\}",
    ],
    "P2-FIX-9: connection coroutine support": [
        r"asyncio\.iscoroutine\(_conn_cm\)",
    ],
    "P2-FIX-10: no catch SystemExit": [
        r"except\s+\(KeyboardInterrupt,\s*SystemExit\):\s*\n\s*raise",
    ],
    # 🆕 FIX-DECLARED-6: يدعم tuple/list متعدد الأسطر
    "P3-FIX-11: critical commands include grant": [
        r"_CRITICAL_COMMANDS\s*=\s*\([^)]{0,800}\bgrant\b",
        r"_CRITICAL_COMMANDS\s*=\s*\[[^\]]{0,800}\bgrant\b",
    ],
    "P3-FIX-12: group log idempotency": [
        r"_GROUP_LOG_INSTANCE\s+is\s+not\s+None",
    ],
    "P3-FIX-13: pid file parent dir": [
        r"os\.makedirs\(os\.path\.dirname\(_PID_FILE_PATH\)",
    ],
    "P3-FIX-14: pg max connections configurable": [
        r"PG_MAX_CONNECTIONS",
    ],
    "P3-FIX-15: cmd_ping metrics": [
        r"record_bot_metric\(\"pings_total\"",
    ],
    "P3-FIX-16: keep_alive log reason": [
        r"keep_alive:\s*معطّل",
    ],
}

# 🆕 v1.3.7 — الأنماط مُصحَّحة:
#   • SQL_STRING_FORMAT → SQL_FSTRING_REAL (بدون DOTALL، بدون %s/?)
#   • EVAL_USE/EXEC_USE: message بدون "eval("/"exec(" + lookbehind
#   • EXCEPT_PASS: محذوف (يُعالج في AST)
#   • LOG_FSTRING: [ \t]* بدل \s*
_AUDIT_PATTERNS = [
    {"id": "BARE_EXCEPT", "severity": "HIGH",
     "pattern": _re_mod.compile(r"^[ \t]*except[ \t]*:[ \t]*$", _re_mod.MULTILINE),
     "message": "bare except: يُخفي كل الأخطاء",
     "suggestion": "استخدم `except Exception:` أو نوعاً محدداً"},
    # 🆕 FIX-EVAL-EXEC-FP-2: message بدون "eval("/"exec(" + lookbehind
    {"id": "EVAL_USE", "severity": "CRITICAL",
     "pattern": _re_mod.compile(r"(?<![.\w])eval\s*\("),
     "message": "استخدام دالة التقييم الديناميكي — خطر أمني",
     "suggestion": "استخدم ast.literal_eval"},
    {"id": "EXEC_USE", "severity": "CRITICAL",
     "pattern": _re_mod.compile(r"(?<![.\w])exec\s*\("),
     "message": "استخدام تنفيذ الكود الديناميكي — خطر أمني",
     "suggestion": "أعد تصميم المنطق"},
    {"id": "SHELL_TRUE", "severity": "HIGH",
     "pattern": _re_mod.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True"),
     "message": "subprocess مع shell=True",
     "suggestion": "استخدم قائمة args"},
    {"id": "PICKLE_LOAD", "severity": "HIGH",
     "pattern": _re_mod.compile(r"\bpickle\.loads?\s*\("),
     "message": "pickle.load على بيانات غير موثوقة",
     "suggestion": "استخدم json"},
    {"id": "YAML_LOAD_UNSAFE", "severity": "HIGH",
     "pattern": _re_mod.compile(
         r"\byaml\.load\s*\([^)]*\)(?!\s*,\s*Loader\s*=\s*yaml\.SafeLoader)"),
     "message": "yaml.load بدون SafeLoader",
     "suggestion": "استخدم yaml.safe_load"},
    {"id": "TODO_FIXME", "severity": "INFO",
     "pattern": _re_mod.compile(r"#\s*(TODO|FIXME|XXX|HACK)\b"),
     "message": "علامة TODO/FIXME",
     "suggestion": "راجعها قبل الإنتاج"},
    {"id": "PRINT_STATEMENT", "severity": "LOW",
     "pattern": _re_mod.compile(r"^[ \t]*print[ \t]*\(", _re_mod.MULTILINE),
     "message": "print بدل logging",
     "suggestion": "استخدم logger.* (إلا في بدء التشغيل قبل logger)"},
    {"id": "HARDCODED_TOKEN", "severity": "CRITICAL",
     "pattern": _re_mod.compile(r"['\"]\d{8,10}:[A-Za-z0-9_-]{35}['\"]"),
     "message": "توكن بوت مضمّن في الكود",
     "suggestion": "استخدم متغير بيئة"},
    {"id": "HARDCODED_PASSWORD", "severity": "CRITICAL",
     "pattern": _re_mod.compile(
         r"(password|passwd|pwd|secret|api_key)\s*=\s*['\"][^'\"]{6,}['\"]",
         _re_mod.IGNORECASE),
     "message": "كلمة مرور/مفتاح مضمّن",
     "suggestion": "استخدم متغير بيئة"},
    # 🆕 FIX-SQL-FP-1: يطابق فقط f-string/format/concat على SQL
    # لا يطابق: `%s` / `?` (parameterized) / UPDATE كاسم متغير
    {"id": "SQL_FSTRING_REAL", "severity": "HIGH",
     "pattern": _re_mod.compile(
         r"""(?:f['"][ \t]*(?:SELECT|INSERT|UPDATE|DELETE)\b"""
         r"""|['"](?:SELECT|INSERT|UPDATE|DELETE)\b[^'"]{0,500}['"][ \t]*(?:\.format\s*\(|\+))""",
         _re_mod.IGNORECASE),
     "message": "SQL مبني بـ f-string/format/concat — خطر SQL injection",
     "suggestion": "استخدم parameterized queries: cursor.execute('... %s', (var,))"},
    {"id": "TIME_SLEEP_IN_ASYNC", "severity": "HIGH",
     "pattern": _re_mod.compile(
         r"async\s+def\s+\w+[^:]*:[\s\S]{0,2000}?\btime\.sleep\s*\("),
     "message": "time.sleep داخل async def",
     "suggestion": "استخدم await asyncio.sleep"},
    {"id": "REQUESTS_IN_ASYNC", "severity": "HIGH",
     "pattern": _re_mod.compile(
         r"async\s+def\s+\w+[^:]*:[\s\S]{0,3000}?"
         r"\brequests\.(get|post|put|delete|patch)\s*\("),
     "message": "requests.* داخل async def",
     "suggestion": "استخدم aiohttp أو httpx"},
    # 🆕 FIX-LOG-FSTRING-FP-4: [ \t]* بدل \s* (يمنع multi-line match)
    {"id": "LOG_FSTRING", "severity": "LOW",
     "pattern": _re_mod.compile(r"logger\.\w+\([ \t]*f['\"]"),
     "message": "logging مع f-string بدل %s",
     "suggestion": "استخدم logger.info('msg %s', var)"},
]


def _audit_get_line_snippet(source_lines: List[str], line_no: int,
                             context: int = 0) -> str:
    if not (1 <= line_no <= len(source_lines)):
        return ""
    start = max(0, line_no - 1 - context)
    end = min(len(source_lines), line_no + context)
    return "\n".join(
        f"{i+1:5d}| {source_lines[i]}" for i in range(start, end)
    )


def _audit_count_lines(text: str) -> Tuple[int, int, int, int]:
    lines = text.splitlines()
    total = len(lines)
    blank = sum(1 for ln in lines if not ln.strip())
    comment = sum(1 for ln in lines if ln.strip().startswith("#"))
    code = total - blank - comment
    return total, code, comment, blank


def _audit_extract_version(text: str) -> Optional[str]:
    m = _re_mod.search(r"v(\d+\.\d+\.\d+(?:-[A-Za-z0-9-]+)?)", text[:3000])
    return m.group(1) if m else None


class _ASTAuditor(_ast_mod.NodeVisitor):
    def __init__(self, source_lines: List[str],
                 findings: List[_AuditFinding]):
        self.source_lines = source_lines
        self.findings = findings
        self.async_depth = 0
        self.imports: set = set()
        self.stats = {
            "classes": 0, "functions": 0, "async_functions": 0,
            "awaits": 0, "create_tasks": 0, "bare_excepts": 0,
            "try_blocks": 0, "comprehensions": 0, "lambdas": 0,
        }

    def _add(self, rule_id: str, severity: str, line: int,
             message: str, suggestion: str = "", category: str = "ast"):
        self.findings.append(_AuditFinding(
            rule_id=rule_id, severity=severity, line=line,
            message=message,
            snippet=_audit_get_line_snippet(self.source_lines, line),
            suggestion=suggestion, category=category,
        ))

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.add(alias.name.split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self.imports.add(node.module.split(".")[0])
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.stats["classes"] += 1
        self.generic_visit(node)

    def _visit_func(self, node, is_async: bool):
        self.stats["functions"] += 1
        if is_async:
            self.stats["async_functions"] += 1
            self.async_depth += 1
        try:
            self.generic_visit(node)
        finally:
            if is_async:
                self.async_depth -= 1

    def visit_FunctionDef(self, node):
        self._visit_func(node, False)

    def visit_AsyncFunctionDef(self, node):
        self._visit_func(node, True)

    def visit_Await(self, node):
        self.stats["awaits"] += 1
        self.generic_visit(node)

    def visit_Try(self, node):
        self.stats["try_blocks"] += 1
        for h in node.handlers:
            if h.type is None:
                self.stats["bare_excepts"] += 1
                self._add("AST_BARE_EXCEPT", "HIGH", h.lineno,
                          "bare except: يُخفي SystemExit/KeyboardInterrupt",
                          "استخدم `except Exception:`")
            # 🆕 FIX-EXCEPT-PASS-3: كشف دقيق — فقط عندما pass هي العبارة الوحيدة
            elif len(h.body) == 1 and isinstance(h.body[0], _ast_mod.Pass):
                self._add("AST_EXCEPT_PASS", "MEDIUM", h.lineno,
                          "except ...: pass يُخفي الأخطاء بصمت",
                          "أضف تسجيلاً: logger.debug('...: %s', e)")
        self.generic_visit(node)

    def visit_Lambda(self, node):
        self.stats["lambdas"] += 1
        self.generic_visit(node)

    def visit_ListComp(self, node):
        self.stats["comprehensions"] += 1
        self.generic_visit(node)

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_Call(self, node):
        fname = self._func_name(node.func)

        if fname in ("asyncio.create_task", "create_task"):
            self.stats["create_tasks"] += 1

        if fname == "time.sleep" and self.async_depth > 0:
            self._add("AST_TIME_SLEEP_IN_ASYNC", "HIGH", node.lineno,
                      "time.sleep داخل async def — يحجب event loop",
                      "استخدم await asyncio.sleep(...)")

        if fname.startswith("requests.") and self.async_depth > 0:
            self._add("AST_REQUESTS_IN_ASYNC", "HIGH", node.lineno,
                      f"{fname} داخل async def", "استخدم httpx.AsyncClient")

        if fname.startswith("subprocess.") and self._has_kwarg(
                node, "shell", True):
            self._add("AST_SHELL_TRUE", "HIGH", node.lineno,
                      f"{fname} مع shell=True", "استخدم قائمة args")

        # 🆕 v1.3.7: eval/exec عبر AST (أدق من regex)
        if fname in ("eval", "exec"):
            self._add("AST_EVAL_EXEC", "CRITICAL", node.lineno,
                      f"استدعاء {fname}() — خطر أمني",
                      "أعد تصميم المنطق")

        self.generic_visit(node)

    def _has_kwarg(self, node, name, value):
        for kw in node.keywords:
            if kw.arg == name:
                if isinstance(kw.value, _ast_mod.Constant) and \
                        kw.value.value == value:
                    return True
        return False

    def _func_name(self, node) -> str:
        try:
            if isinstance(node, _ast_mod.Name):
                return node.id
            if isinstance(node, _ast_mod.Attribute):
                base = self._func_name(node.value)
                return f"{base}.{node.attr}" if base else node.attr
        except Exception:
            pass
        return ""


def _audit_check_ptb_lifecycle(tree, source_lines, findings):
    functions = {
        n.name: n for n in _ast_mod.walk(tree)
        if isinstance(n, (_ast_mod.FunctionDef, _ast_mod.AsyncFunctionDef))
    }

    fn = functions.get("_run_post_init_hooks")
    if fn:
        for node in _ast_mod.walk(fn):
            if isinstance(node, _ast_mod.Await) and \
                    isinstance(node.value, _ast_mod.Call):
                fname = _ASTAuditor(source_lines, [])._func_name(
                    node.value.func)
                if "post_init" in fname:
                    findings.append(_AuditFinding(
                        rule_id="PTB_POST_INIT_MANUAL", severity="CRITICAL",
                        line=node.lineno,
                        message="استدعاء يدوي لـ post_init — PTB يستدعيه تلقائياً",
                        suggestion="احذف الاستدعاء اليدوي",
                        category="ptb",
                    ))

    fn = functions.get("_run_post_stop_hooks")
    if fn:
        for node in _ast_mod.walk(fn):
            if isinstance(node, _ast_mod.Await) and \
                    isinstance(node.value, _ast_mod.Call):
                fname = _ASTAuditor(source_lines, [])._func_name(
                    node.value.func)
                if "post_stop" in fname:
                    findings.append(_AuditFinding(
                        rule_id="PTB_POST_STOP_MANUAL", severity="CRITICAL",
                        line=node.lineno,
                        message="استدعاء يدوي لـ post_stop — double-call",
                        suggestion="احذف الاستدعاء اليدوي",
                        category="ptb",
                    ))

    fn = functions.get("_stop_polling_mode")
    if fn:
        lines_in_fn = sorted(
            {n.lineno for n in _ast_mod.walk(fn) if hasattr(n, "lineno")})
        if lines_in_fn:
            fn_start, fn_end = min(lines_in_fn), max(lines_in_fn)
            updater_stop_line = post_stop_line = None
            for i in range(fn_start, min(fn_end, len(source_lines)) + 1):
                line = source_lines[i - 1]
                if "updater.stop()" in line and updater_stop_line is None:
                    updater_stop_line = i
                if "_run_post_stop_hooks" in line and post_stop_line is None:
                    post_stop_line = i
            if updater_stop_line and post_stop_line and \
                    post_stop_line < updater_stop_line:
                findings.append(_AuditFinding(
                    rule_id="PTB_POST_STOP_ORDER", severity="CRITICAL",
                    line=post_stop_line,
                    message="_run_post_stop_hooks قبل updater.stop() — ترتيب خاطئ",
                    suggestion="استدعِ updater.stop() أولاً",
                    category="ptb",
                ))


def _audit_check_data_none(tree, source_lines, findings):
    functions = {
        n.name: n for n in _ast_mod.walk(tree)
        if isinstance(n, (_ast_mod.FunctionDef, _ast_mod.AsyncFunctionDef))
    }
    fn = functions.get("successful_payment")
    if not fn:
        return
    body_src = "\n".join(
        source_lines[n.lineno - 1] for n in _ast_mod.walk(fn)
        if hasattr(n, "lineno")
    )
    has_validation = _re_mod.search(
        r"not\s+isinstance\(\s*data\s*,\s*dict\s*\)", body_src
    ) or _re_mod.search(r"if\s+data\s+is\s+None", body_src)
    if "data.get(" in body_src and not has_validation:
        for node in _ast_mod.walk(fn):
            if isinstance(node, _ast_mod.Call) and \
                    isinstance(node.func, _ast_mod.Attribute) and \
                    node.func.attr == "get" and \
                    isinstance(node.func.value, _ast_mod.Name) and \
                    node.func.value.id == "data":
                findings.append(_AuditFinding(
                    rule_id="RUNTIME_DATA_NONE", severity="HIGH",
                    line=node.lineno,
                    message="data.get(...) بدون التحقق من None",
                    suggestion="أضف `if not isinstance(data, dict): return`",
                    category="runtime",
                ))
                break


def _audit_check_admin_ids(tree, source_lines, findings):
    main_fn = None
    for node in _ast_mod.walk(tree):
        if isinstance(node, _ast_mod.AsyncFunctionDef) and node.name == "main":
            main_fn = node
            break
    if not main_fn:
        return
    body_src = "\n".join(
        source_lines[n.lineno - 1] for n in _ast_mod.walk(main_fn)
        if hasattr(n, "lineno") and n.lineno <= len(source_lines)
    )
    if "_admin_ids = await _collect_admin_ids()" in body_src:
        if "if not _admin_ids" not in body_src:
            for node in _ast_mod.walk(main_fn):
                if isinstance(node, _ast_mod.Call) and \
                        isinstance(node.func, _ast_mod.Name) and \
                        node.func.id == "_collect_admin_ids":
                    findings.append(_AuditFinding(
                        rule_id="ADMIN_IDS_EMPTY", severity="HIGH",
                        line=node.lineno,
                        message="_admin_ids قد تكون فارغة → كل الأوامر الإدارية تُرفض",
                        suggestion="أضف `if not _admin_ids: raise SystemExit(1)`",
                        category="runtime",
                    ))
                    break


def _audit_file_sync(path: Path) -> _AuditReport:
    """فحص ملف واحد — نسخة متزامنة (تُستدعى من to_thread)."""
    report = _AuditReport(
        timestamp=datetime.now().isoformat(timespec="seconds"))
    if not path.exists():
        report.parse_error = f"الملف غير موجود: {path}"
        return report

    report.file = str(path)
    try:
        report.file_size_bytes = path.stat().st_size
    except Exception:
        pass

    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except UnicodeDecodeError:
        try:
            with open(path, "r", encoding="latin-1") as f:
                text = f.read()
        except Exception as e:
            report.parse_error = f"تعذّر القراءة: {e}"
            return report
    except Exception as e:
        report.parse_error = f"تعذّر القراءة: {e}"
        return report

    source_lines = text.splitlines()
    (report.total_lines, report.code_lines,
     report.comment_lines, report.blank_lines) = _audit_count_lines(text)
    report.declared_version = _audit_extract_version(text)

    try:
        tree = _ast_mod.parse(text, filename=str(path))
    except SyntaxError as e:
        report.parse_error = f"SyntaxError at line {e.lineno}: {e.msg}"
        report.findings.append(_AuditFinding(
            rule_id="SYNTAX_ERROR", severity="CRITICAL",
            line=e.lineno or 0,
            message=f"خطأ صياغة: {e.msg}",
            snippet=_audit_get_line_snippet(
                source_lines, e.lineno or 0, 1),
            category="syntax",
        ))
        return report

    auditor = _ASTAuditor(source_lines, report.findings)
    try:
        auditor.visit(tree)
    except Exception as e:
        report.findings.append(_AuditFinding(
            rule_id="AST_VISIT_ERROR", severity="MEDIUM", line=0,
            message=f"فشل AST walk: {type(e).__name__}",
            category="ast",
        ))
    report.stats = dict(auditor.stats)
    report.imports = sorted(auditor.imports)

    for rule in _AUDIT_PATTERNS:
        try:
            for m in rule["pattern"].finditer(text):
                line_no = text.count("\n", 0, m.start()) + 1
                report.findings.append(_AuditFinding(
                    rule_id=rule["id"], severity=rule["severity"],
                    line=line_no, message=rule["message"],
                    snippet=_audit_get_line_snippet(source_lines, line_no),
                    suggestion=rule.get("suggestion", ""),
                    category="pattern",
                ))
        except Exception:
            pass

    try:
        _audit_check_ptb_lifecycle(tree, source_lines, report.findings)
    except Exception:
        pass
    try:
        _audit_check_data_none(tree, source_lines, report.findings)
    except Exception:
        pass
    try:
        _audit_check_admin_ids(tree, source_lines, report.findings)
    except Exception:
        pass

    for fix_name, patterns in _DECLARED_FIXES_V5713.items():
        try:
            found = all(
                _re_mod.search(p, text, _re_mod.MULTILINE)
                for p in patterns
            )
            if found:
                report.fixes_found.append(fix_name)
            else:
                report.fixes_missing.append(fix_name)
        except Exception:
            report.fixes_missing.append(fix_name)

    report.findings.sort(key=lambda f: (
        _SEVERITY_ORDER.get(f.severity, 99), f.line))
    return report


def _audit_summary_html(reports: List[_AuditReport],
                        root: Optional[Path] = None) -> str:
    """بناء ملخص HTML من عدة تقارير."""
    by_sev_total = {s: 0 for s in _SEVERITY_ORDER}
    total_findings = 0
    total_files = len(reports)
    ok_files = 0
    err_files = 0
    total_lines = 0
    fixes_found_total = 0
    fixes_missing_total = 0
    parse_errors: List[Tuple[str, str]] = []

    for r in reports:
        if r.parse_error:
            err_files += 1
            parse_errors.append((Path(r.file).name, r.parse_error))
            continue
        ok_files += 1
        total_lines += r.total_lines
        fixes_found_total += len(r.fixes_found)
        fixes_missing_total += len(r.fixes_missing)
        total_findings += len(r.findings)
        for f in r.findings:
            if f.severity in by_sev_total:
                by_sev_total[f.severity] += 1

    lines = [
        "🔍 <b>تقرير الفحص الشامل</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📂 الملفات المفحوصة: <b>{total_files}</b>",
        f"✅ سليمة: <b>{ok_files}</b> | ❌ أخطاء: <b>{err_files}</b>",
        f"📏 إجمالي الأسطر: <b>{total_lines:,}</b>",
        "",
        f"🔎 إجمالي النتائج: <b>{total_findings}</b>",
    ]

    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
        n = by_sev_total[sev]
        if n:
            lines.append(f"{_SEVERITY_ICONS[sev]} {sev}: <b>{n}</b>")

    lines.append("")
    lines.append(
        f"🛠️ إصلاحات v5.7.13+: ✅{fixes_found_total} "
        f"| ❌{fixes_missing_total}"
    )

    if root:
        lines.append("")
        lines.append(
            f"📂 المسح من: <code>{_html_mod.escape(str(root))}</code>")

    lines.append("")
    lines.append("<b>━━━━━━━━━━━━━━━━━━━━━━</b>")
    lines.append("<b>أبرز المشاكل:</b>")
    lines.append("")

    critical_files: List[Tuple[str, List[_AuditFinding]]] = []
    for r in reports:
        if r.parse_error:
            continue
        crits = [f for f in r.findings if f.severity == "CRITICAL"]
        if crits:
            critical_files.append((Path(r.file).name, crits))

    if not critical_files:
        lines.append("✅ <i>لا توجد مشاكل CRITICAL في الملفات المفحوصة.</i>")
    else:
        for fname, crits in critical_files[:5]:
            lines.append(
                f"\n📄 <b>{_html_mod.escape(fname)}</b> "
                f"({len(crits)} CRITICAL)"
            )
            for c in crits[:3]:
                lines.append(
                    f"  🔴 L{c.line} <code>{c.rule_id}</code>: "
                    f"{_html_mod.escape(c.message[:80])}"
                )
            if len(crits) > 3:
                lines.append(f"  … و{len(crits) - 3} آخر")

    if parse_errors:
        lines.append("")
        lines.append("<b>❌ أخطاء صياغة:</b>")
        for fname, err in parse_errors[:5]:
            lines.append(
                f"  ❌ <code>{_html_mod.escape(fname)}</code>\n"
                f"     <i>{_html_mod.escape(err[:100])}</i>"
            )

    lines.append("")
    lines.append(f"🕐 <i>{TimeUtils.mecca_iso()[:19]}</i>")

    return "\n".join(lines)


def _audit_to_markdown(reports: List[_AuditReport],
                       root: Optional[Path] = None) -> str:
    """بناء تقرير Markdown من عدة تقارير."""
    md_lines = [
        "# 🔍 تقرير الفحص الشامل",
        "",
        f"**التاريخ**: {datetime.now().isoformat(timespec='seconds')}",
    ]
    if root:
        md_lines.append(f"**المسح من**: `{root}`")
    md_lines.append(f"**عدد الملفات**: {len(reports)}")
    md_lines.append("")

    for r in reports:
        try:
            name = Path(r.file).name
        except Exception:
            name = r.file
        md_lines.append(f"## 📄 `{name}`")
        md_lines.append("")
        if r.parse_error:
            md_lines.append(f"❌ **خطأ صياغة**: {r.parse_error}")
            md_lines.append("")
            continue

        md_lines.append(f"- **الحجم**: {r.file_size_bytes:,} bytes")
        md_lines.append(f"- **الأسطر**: {r.total_lines:,} "
                        f"(كود={r.code_lines}, تعليقات={r.comment_lines})")
        if r.declared_version:
            md_lines.append(f"- **الإصدار**: v{r.declared_version}")
        md_lines.append(f"- **النتائج**: {len(r.findings)}")
        md_lines.append(
            f"- **إصلاحات v5.7.13+**: "
            f"✅{len(r.fixes_found)} / ❌{len(r.fixes_missing)}"
        )
        md_lines.append("")

        if r.findings:
            md_lines.append("| الشدة | السطر | القاعدة | الرسالة |")
            md_lines.append("|-------|-------|---------|---------|")
            for f in r.findings[:30]:
                msg = f.message.replace("|", "\\|")[:80]
                md_lines.append(
                    f"| {_SEVERITY_ICONS[f.severity]} {f.severity} "
                    f"| {f.line} | `{f.rule_id}` | {msg} |"
                )
            if len(r.findings) > 30:
                md_lines.append(
                    f"\n_… و{len(r.findings) - 30} نتيجة أخرى_")
        else:
            md_lines.append("✅ لا توجد مشاكل.")
        md_lines.append("")

    return "\n".join(md_lines)


async def _audit_run_reports(
    files: List[Path],
    timeout: float = _AUDIT_TIMEOUT_SEC,
) -> List[_AuditReport]:
    """
    تشغيل الفحص على قائمة ملفات.

    🆕 v1.3.8 FIX-AUDIT-EXECUTOR:
        - يستخدم `_AUDIT_EXECUTOR` المخصص (معزول عن ThreadPool المشترك
          مع handle_group في handlers_message.py).
        - `Semaphore(2)` مطابق لـ max_workers=2.
        - النتيجة: `handle_group` لا ينتظر انتهاء /audit.
    """
    reports: List[_AuditReport] = []
    sem = asyncio.Semaphore(_AUDIT_SEMAPHORE_LIMIT)
    loop = asyncio.get_running_loop()
    audit_executor = _get_audit_executor()

    async def _one(p: Path) -> Optional[_AuditReport]:
        async with sem:
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(
                        audit_executor,
                        _audit_file_sync,
                        p,
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                return _AuditReport(
                    file=str(p),
                    parse_error=f"timeout بعد {timeout}s",
                )
            except Exception as e:
                return _AuditReport(
                    file=str(p),
                    parse_error=f"{type(e).__name__}: {str(e)[:100]}",
                )

    try:
        tasks = [asyncio.create_task(_one(p)) for p in files]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, _AuditReport):
                reports.append(r)
            elif isinstance(r, Exception):
                logger.debug(f"_audit_run_reports: {r}")
    except Exception as e:
        logger.error(f"_audit_run_reports: {e}")

    return reports


def _audit_collect_files_sync(root: Path) -> List[Path]:
    """
    🆕 v1.3.8 FIX-COLLECT-FILES-SYNC: نسخة متزامنة.
    تُنفَّذ في `_AUDIT_EXECUTOR` بدلاً من الحلقة الرئيسية.
    """
    files: List[Path] = []
    # 🆕 FIX-SELF-SCAN-5: استثناء self من self-scan
    try:
        _self_path = Path(__file__).resolve()
    except Exception:
        _self_path = None

    try:
        for py_file in root.rglob("*.py"):
            try:
                parts = py_file.relative_to(root).parts
            except ValueError:
                continue
            if any(p in _EXCLUDED_DIRS for p in parts[:-1]):
                continue
            if py_file.name in _SKIP_FILENAMES:
                continue
            if _self_path is not None:
                try:
                    if py_file.resolve() == _self_path:
                        continue
                except Exception:
                    pass
            files.append(py_file)
            if len(files) >= _MAX_AUDIT_FILES:
                break
    except Exception as e:
        logger.warning(f"_audit_collect_files_sync: {e}")

    files.sort(key=lambda p: str(p).lower())
    return files


async def _audit_collect_files(root: Path) -> List[Path]:
    """
    جمع ملفات .py من الجذر.

    🆕 v1.3.8 FIX-COLLECT-FILES-SYNC:
        - التنفيذ الفعلي في `_AUDIT_EXECUTOR` (لا يحجب الحلقة).
        - timeout 15s.
        - يستثني handlers_analytics.py من self-scan.
    """
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(
                _get_audit_executor(),
                _audit_collect_files_sync,
                root,
            ),
            timeout=15.0,
        )
    except asyncio.TimeoutError:
        logger.warning("_audit_collect_files: timeout 15s")
        return []
    except Exception as e:
        logger.warning(f"_audit_collect_files: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════
# v1.3.3 — كشف توفر ميزة الضبط التلقائي (v7.2.24+)
# ═══════════════════════════════════════════════════════════════════════

_AUTOTUNE_AVAILABLE = False
_AUTOTUNE_IMPORT_ERROR: Optional[str] = None

try:
    from db_diagnostics import (
        diagnose_autovacuum_tuning as _diagnose_autovacuum_tuning_fn,
        VERSION as _DB_DIAG_VERSION_AT,
    )
    _AUTOTUNE_AVAILABLE = True
except Exception as _at_err:
    _diagnose_autovacuum_tuning_fn = None
    try:
        from db_diagnostics import VERSION as _DB_DIAG_VERSION_AT
    except Exception:
        _DB_DIAG_VERSION_AT = "unknown"
    _AUTOTUNE_IMPORT_ERROR = f"{type(_at_err).__name__}: {_at_err}"


# ═══════════════════════════════════════════════════════════════════════
# Cache ذكي لاستعلامات DB
# ═══════════════════════════════════════════════════════════════════════

_DB_CACHE: Dict[str, Tuple[Any, float]] = {}
_DB_CACHE_TTL_DEFAULT = 60.0
_DB_CACHE_MAX_ENTRIES = 100


async def _cached_db_call(
    cache_key: str,
    coro_factory: Callable[[], Awaitable[Any]],
    ttl: float = _DB_CACHE_TTL_DEFAULT,
    force_refresh: bool = False,
) -> Any:
    """
    cache ذكي لاستعلامات DB.

    v1.3.1 FIX-1: افتراضي force_refresh=False.
    زر التحديث في handle_analytics_callback يُبطل cache ثم يستدعي.
    """
    now = time.monotonic()
    if not force_refresh:
        entry = _DB_CACHE.get(cache_key)
        if entry:
            data, ts = entry
            if (now - ts) < ttl:
                logger.debug(
                    "💾 CACHE hit: %s (age=%.1fs)",
                    cache_key, now - ts,
                )
                return data

    try:
        result = await coro_factory()
    except Exception as e:
        logger.warning(
            "❌ _cached_db_call(%s) فشل: %s", cache_key, e,
        )
        raise

    if len(_DB_CACHE) >= _DB_CACHE_MAX_ENTRIES:
        try:
            oldest = sorted(
                _DB_CACHE.items(),
                key=lambda kv: kv[1][1],
            )[: max(1, _DB_CACHE_MAX_ENTRIES // 5)]
            for k, _ in oldest:
                _DB_CACHE.pop(k, None)
        except Exception:
            _DB_CACHE.clear()
    _DB_CACHE[cache_key] = (result, now)
    logger.debug("💾 CACHE store: %s", cache_key)
    return result


def _invalidate_analytics_cache(prefix: Optional[str] = None) -> int:
    """إبطال cache (كل أو ببادئة)."""
    if prefix is None:
        n = len(_DB_CACHE)
        _DB_CACHE.clear()
        return n
    keys_to_del = [k for k in _DB_CACHE if k.startswith(prefix)]
    for k in keys_to_del:
        _DB_CACHE.pop(k, None)
    return len(keys_to_del)


def _get_cache_stats() -> Dict[str, Any]:
    """إحصائيات cache."""
    now = time.monotonic()
    out = {
        "total_keys": len(_DB_CACHE),
        "max_entries": _DB_CACHE_MAX_ENTRIES,
        "default_ttl": _DB_CACHE_TTL_DEFAULT,
        "keys": {},
    }
    for k, (_, ts) in _DB_CACHE.items():
        age = now - ts
        out["keys"][k] = round(age, 1)
    return out


# ═══════════════════════════════════════════════════════════════════════
# دوال مساعدة
# ═══════════════════════════════════════════════════════════════════════

def _t(key: str, default: str, lang: str = "ar") -> str:
    try:
        text = TranslationManager.get_text(lang, key)
        if text and text != key:
            return text
    except Exception:
        pass
    try:
        return KeyboardFactory.get_text(key, lang) or default
    except Exception:
        return default


def _bar(value: float, max_value: float, width: int = 10,
         filled: str = "█", empty: str = "░") -> str:
    try:
        v = float(value)
        m = float(max_value)
        if m <= 0:
            return empty * width
        ratio = min(1.0, max(0.0, v / m))
        n = int(round(ratio * width))
        return filled * n + empty * (width - n)
    except Exception:
        return empty * width


def _bar_with_pct(value: float, max_value: float,
                  width: int = 10) -> str:
    try:
        v = float(value)
        m = float(max_value)
        if m <= 0:
            pct = 0.0
        else:
            pct = min(100.0, max(0.0, v / m * 100))
        bar = _bar(v, m, width=width)
        return f"{bar} <b>{pct:.0f}%</b>"
    except Exception:
        return f"{'░' * width} <b>0%</b>"


def _growth_arrow(delta_pct: float) -> str:
    if delta_pct > 5:
        return "📈"
    if delta_pct > 0:
        return "↗️"
    if delta_pct < -5:
        return "📉"
    if delta_pct < 0:
        return "↘️"
    return "➡️"


def _check_developer(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    try:
        if hasattr(CONFIG, "is_developer"):
            return bool(CONFIG.is_developer(user_id))
        return user_id == int(CONFIG.PRIMARY_OWNER_ID)
    except Exception as e:
        logger.warning("_check_developer(%s): %s", user_id, e)
        return False


def _get_safe_user_id(update: Update) -> Optional[int]:
    try:
        user = getattr(update, "effective_user", None)
        if user is None:
            return None
        uid = getattr(user, "id", None)
        return uid if uid is not None else None
    except Exception:
        return None


def _safe_get_chat_id(update: Update, query=None) -> Optional[int]:
    try:
        if query is not None and getattr(query, 'message', None):
            cid = getattr(query.message, 'chat_id', None)
            if cid is not None:
                return cid
    except Exception:
        pass
    try:
        if update is not None and getattr(update, 'effective_chat', None):
            cid = getattr(update.effective_chat, 'id', None)
            if cid is not None:
                return cid
    except Exception:
        pass
    try:
        if query is not None and getattr(query, 'from_user', None):
            uid = getattr(query.from_user, 'id', None)
            if uid is not None:
                return uid
    except Exception:
        pass
    return None


async def _reject_non_dev(bot, chat_id: Optional[int], query=None,
                          message: str = "❌ هذا الأمر للمطور فقط.") -> None:
    if query is not None:
        try:
            await query.answer(message, show_alert=True)
            return
        except Exception as e:
            logger.debug(f"_reject_non_dev (query.answer): {e}")
    if chat_id is not None:
        try:
            await safe_send(bot, chat_id, message)
        except Exception as e:
            logger.warning(f"_reject_non_dev (safe_send): {e}")


def _is_parse_error(err_str: str) -> bool:
    low = (err_str or "").lower()
    return any(k in low for k in (
        "can't parse",
        "can't find end tag",
        "unsupported start tag",
        "unclosed tag",
        "invalid entity",
    ))


def _strip_html(text: str) -> str:
    if not text:
        return text
    try:
        import html as _h
        return _h.unescape(_re_mod.sub(r"<[^>]+>", "", text))
    except Exception:
        return text


async def _quick_answer(query, text: str = "") -> None:
    if query is None:
        return
    try:
        await query.answer(text or "")
    except Exception as e:
        logger.debug(f"_quick_answer: {e}")


async def _safe_edit(query, text: str, keyboard=None,
                     parse_mode: str = "HTML") -> bool:
    if query is None or getattr(query, 'message', None) is None:
        return False

    try:
        await query.edit_message_text(
            text, parse_mode=parse_mode, reply_markup=keyboard,
            disable_web_page_preview=True,
        )
        return True
    except BadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return True
        if parse_mode and _is_parse_error(err):
            logger.warning(
                "⚠️ _safe_edit parse failed — fallback plain | %.80s",
                text,
            )
            try:
                await query.edit_message_text(
                    _strip_html(text), parse_mode=None,
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
                return True
            except Exception as e2:
                logger.debug(f"_safe_edit plain fallback: {e2}")
        if "there is no text in the message" in err or \
           "message can't be edited" in err:
            try:
                await query.edit_message_caption(
                    caption=text, parse_mode=parse_mode,
                    reply_markup=keyboard,
                )
                return True
            except Exception as e2:
                logger.debug(f"_safe_edit caption fallback: {e2}")
    except Exception as e:
        logger.debug(f"_safe_edit non-bad: {type(e).__name__}: {e}")

    try:
        chat_id = None
        try:
            chat_id = query.message.chat_id
        except Exception:
            pass
        if chat_id is None:
            return False
        await safe_send(
            query.bot, chat_id, text,
            reply_markup=keyboard, parse_mode=parse_mode,
        )
        return True
    except Exception as e:
        logger.debug(f"_safe_edit send fallback: {e}")
        return False


async def _safe_send_long(bot, chat_id: int, text: str,
                          parse_mode: str = "HTML",
                          reply_markup=None) -> bool:
    if not text or chat_id is None:
        return False

    async def _send_one(cid, body, kb, pmode) -> bool:
        try:
            await bot.send_message(
                cid, body, parse_mode=pmode,
                disable_web_page_preview=True,
                reply_markup=kb,
            )
            return True
        except BadRequest as be:
            if pmode and _is_parse_error(str(be)):
                logger.warning(
                    "⚠️ _safe_send_long parse failed — plain | %.80s",
                    body,
                )
                try:
                    await bot.send_message(
                        cid, _strip_html(body), parse_mode=None,
                        disable_web_page_preview=True,
                        reply_markup=kb,
                    )
                    return True
                except Exception as e2:
                    logger.warning(
                        f"_safe_send_long plain fallback: {e2}")
                    return False
            logger.warning(f"_safe_send_long BadRequest: {be}")
            return False
        except Exception as e:
            logger.warning(f"_safe_send_long: {type(e).__name__}: {e}")
            return False

    MAX = 3800
    if len(text) <= MAX:
        return await _send_one(chat_id, text, reply_markup, parse_mode)

    chunks: List[str] = []
    remaining = text
    while len(remaining) > MAX:
        cut = remaining.rfind("\n", 0, MAX)
        if cut < MAX // 2:
            cut = MAX
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)

    total = len(chunks)
    all_ok = True
    for i, chunk in enumerate(chunks, 1):
        header = f"<i>({i}/{total})</i>\n" if total > 1 else ""
        kb = reply_markup if i == total else None
        ok = await _send_one(chat_id, header + chunk, kb, parse_mode)
        if not ok:
            logger.warning(
                "_safe_send_long: توقف عند الصفحة %d/%d",
                i, total,
            )
            all_ok = False
            break
    return all_ok


def _back_keyboard(
    target: str = "admin_analytics", lang: str = "ar"
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            _t("back", "🔙 رجوع", lang),
            callback_data=target,
        )
    ]])


def _back_refresh_keyboard(target: str = "admin_analytics",
                           refresh: str = "refresh_btn",
                           lang: str = "ar"
                           ) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            _t("refresh_btn", "🔄 تحديث", lang),
            callback_data=refresh,
        )],
        [InlineKeyboardButton(
            _t("back", "🔙 رجوع", lang),
            callback_data=target,
        )],
    ])


def _fmt_num(n) -> str:
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"


def _fmt_elapsed(sec) -> str:
    try:
        s = float(sec)
    except (TypeError, ValueError):
        return "?"
    if not (s == s) or s < 0 or s == float("inf"):
        return "?"
    if s < 1:
        try:
            return f"{int(s * 1000)}ms"
        except (OverflowError, ValueError):
            return "?"
    if s < 60:
        return f"{s:.2f}s"
    return f"{int(s // 60)}m{int(s % 60)}s"


def _err_detail(e: Exception) -> str:
    try:
        tb_lines = _tb.format_exc().strip().split("\n")
        loc = " | ".join(
            l.strip() for l in tb_lines[-3:-1] if l.strip()
        )[:200]
    except Exception:
        loc = "?"
    try:
        err_type = type(e).__name__
        err_msg = str(e)[:250]
    except Exception:
        err_type = "Unknown"
        err_msg = "?"
    if not err_msg:
        err_msg = "(بدون رسالة)"
    safe_type = _html_mod.escape(err_type)
    safe_msg = _html_mod.escape(err_msg)
    safe_loc = _html_mod.escape(loc)

    suggestion = ""
    err_low = err_msg.lower() + " " + err_type.lower()
    if "attribute" in err_low and "none" in err_low:
        suggestion = "\n💡 <i>احتمال: update/query/message=None</i>"
    elif "timeout" in err_low:
        suggestion = "\n💡 <i>احتمال: الشبكة بطيئة أو DB مشبع</i>"
    elif "asyncpg" in err_low or "connection" in err_low:
        suggestion = "\n💡 <i>احتمال: DB pool استنفد أو انقطع</i>"
    elif "openpyxl" in err_low:
        suggestion = "\n💡 <i>ثبّت: pip install openpyxl</i>"
    elif "permission" in err_low or "forbidden" in err_low:
        suggestion = "\n💡 <i>احتمال: البوت غير مشرف أو محظور</i>"

    return (
        f"<b>النوع:</b> <code>{safe_type}</code>\n"
        f"<b>الرسالة:</b> <code>{safe_msg}</code>\n"
        f"<b>الموقع:</b> <code>{safe_loc}</code>"
        f"{suggestion}"
    )


def _default_analytics_keyboard(lang: str = "ar") -> InlineKeyboardMarkup:
    def _lbl(key: str, default: str) -> str:
        try:
            return _t(key, default, lang)
        except Exception:
            return default

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            _lbl("analytics_growth", "📈 نمو المستخدمين"),
            callback_data="growth_30d_btn"),
         InlineKeyboardButton(
            _lbl("analytics_top_channels", "🏆 أفضل القنوات"),
            callback_data="top_channels_btn")],
        [InlineKeyboardButton(
            _lbl("analytics_publish_stats", "📊 متوسط النشر"),
            callback_data="publish_stats_btn"),
         InlineKeyboardButton(
            _lbl("analytics_channels_rate", "🎯 نسبة النجاح"),
            callback_data="channels_rate_btn")],
        [InlineKeyboardButton(
            _lbl("analytics_subscriptions", "💎 الاشتراكات"),
            callback_data="subscriptions_btn"),
         InlineKeyboardButton(
            _lbl("analytics_pool", "🚀 Pool مباشر"),
            callback_data="pool_live_btn")],
        [InlineKeyboardButton(
            _lbl("analytics_slow_queries", "🐌 استعلامات بطيئة"),
            callback_data="slow_queries_btn"),
         InlineKeyboardButton(
            _lbl("analytics_export", "📤 تصدير Excel"),
            callback_data="export_excel_btn")],
        [InlineKeyboardButton(
            _lbl("analytics_full_health", "🏥 التشخيص الشامل"),
            callback_data="full_health_btn"),
         InlineKeyboardButton(
            _lbl("analytics_latency", "🔬 اختبار الكمون"),
            callback_data="latency_btn")],
        [InlineKeyboardButton(
            _lbl("analytics_databases", "🗂️ قواعد البيانات"),
            callback_data="databases_btn"),
         InlineKeyboardButton(
            _lbl("analytics_autotune", "⚙️ ضبط autovacuum"),
            callback_data="autotune_btn")],
        [InlineKeyboardButton(
            _lbl("analytics_files", "📂 ملفات المشروع"),
            callback_data="files_btn")],
        [InlineKeyboardButton(
            _lbl("analytics_audit", "🔍 فحص شامل"),
            callback_data="audit_btn")],
        [InlineKeyboardButton(
            _lbl("refresh_btn", "🔄 تحديث"),
            callback_data="refresh_btn")],
        [InlineKeyboardButton(
            _lbl("back", "🔙 رجوع"),
            callback_data="admin")],
    ])


# ═══════════════════════════════════════════════════════════════════════
# 1) القائمة الرئيسية
# ═══════════════════════════════════════════════════════════════════════

async def show_analytics_menu(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        query = update.callback_query
        user_id = _get_safe_user_id(update)
        chat_id = _safe_get_chat_id(update, query)

        await _quick_answer(query)

        if user_id is None:
            return

        if not _check_developer(user_id):
            await _reject_non_dev(
                context.bot, chat_id, query,
                "❌ لوحة التحليلات للمطور فقط.",
            )
            return

        missing = []
        for _fn in (
            "get_user_growth", "get_top_channels",
            "get_publish_stats", "get_subscription_rate",
            "get_pool_live", "get_slowest_queries",
        ):
            if not hasattr(DB, _fn):
                missing.append(_fn)

        use_pg = bool(getattr(DB, "USE_POSTGRES", False))
        db_type = str(getattr(DB, "DB_TYPE", "?")).upper()

        if not use_pg:
            text = (
                "📊 <b>التحليلات المتقدمة</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"⚠️ هذه الميزة تتطلب <b>PostgreSQL</b>.\n"
                f"النوع الحالي: <code>{db_type}</code>"
            )
            if query:
                await _safe_edit(query, text, _back_keyboard("admin"))
            elif chat_id is not None:
                await safe_send(
                    context.bot, chat_id, text,
                    reply_markup=_back_keyboard("admin"),
                )
            return

        if missing:
            text = (
                "⚠️ <b>تحذير — دوال مفقودة</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<b>دوال غير موجودة في DB:</b>\n"
                + "\n".join(f"  ❌ <code>{m}</code>" for m in missing)
                + "\n\n💡 <b>السبب:</b> "
                "<code>database.py</code> لا يرث من "
                "<code>AnalyticsMixin</code>.\n\n"
                "✅ <b>الحل:</b> ارفع <code>database.py</code> v7.7.65+"
            )
            if query:
                await _safe_edit(query, text, _back_keyboard("admin"))
            elif chat_id is not None:
                await safe_send(
                    context.bot, chat_id, text,
                    reply_markup=_back_keyboard("admin"),
                )
            return

        try:
            keyboard = KeyboardFactory.build("analytics", lang="ar")
        except Exception:
            keyboard = _default_analytics_keyboard(lang="ar")

        cache_stats = _get_cache_stats()
        cache_info = (
            f"\n💾 cache: <b>{cache_stats['total_keys']}</b>"
            f"/{cache_stats['max_entries']}"
        )

        autotune_line = (
            "⚙️ autovacuum-tuning: 🟢 متاح"
            if _AUTOTUNE_AVAILABLE else
            "⚙️ autovacuum-tuning: 🔴 غير متاح "
            f"<i>(يتطلب v7.2.24+، الحالي: "
            f"{_html_mod.escape(str(_DB_DIAG_VERSION_AT))})</i>"
        )

        text = (
            "📊 <b>التحليلات المتقدمة</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ DB: <code>{db_type}</code>\n"
            f"✅ AnalyticsMixin: مُحمَّل\n"
            f"{autotune_line}\n"
            f"{cache_info}\n"
            f"🕐 <i>{TimeUtils.mecca_iso()[:19]}</i>"
        )

        if query:
            await _safe_edit(query, text, keyboard)
        elif chat_id is not None:
            await safe_send(
                context.bot, chat_id, text,
                reply_markup=keyboard, parse_mode="HTML",
            )
    except Exception as e:
        logger.error("show_analytics_menu: %s", e, exc_info=True)


# ═══════════════════════════════════════════════════════════════════════
# 2) نمو المستخدمين
# ═══════════════════════════════════════════════════════════════════════

async def show_growth_30d(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الحساب...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    force_refresh = False

    try:
        if not hasattr(DB, "get_user_growth"):
            raise AttributeError("DB.get_user_growth غير موجود")

        async def _fetch_current():
            return await DB.get_user_growth(days=30)

        async def _fetch_prev():
            full = await DB.get_user_growth(days=60)
            return full[:30] if len(full) > 30 else []

        rows = await _cached_db_call(
            "growth_30d_current",
            _fetch_current,
            ttl=60.0,
            force_refresh=force_refresh,
        )
        rows = rows or []

        prev_rows = []
        try:
            prev_rows = await _cached_db_call(
                "growth_30d_prev",
                _fetch_prev,
                ttl=300.0,
                force_refresh=force_refresh,
            )
            prev_rows = prev_rows or []
        except Exception as _pe:
            logger.debug(f"prev_rows failed: {_pe}")

        total_count = sum(r.get("count", 0) for r in rows)
        n_days = len(rows) if rows else 30
        avg = round(total_count / n_days, 1) if n_days > 0 else 0.0
        max_count = max((r.get("count", 0) for r in rows), default=0)

        prev_total = sum(r.get("count", 0) for r in prev_rows)
        delta_line = ""
        if prev_total > 0:
            delta_pct = (total_count - prev_total) / prev_total * 100
            arrow = _growth_arrow(delta_pct)
            delta_line = (
                f"{arrow} <b>التغيير:</b> {delta_pct:+.1f}% "
                f"<i>({prev_total} → {total_count})</i>"
            )
        elif prev_rows:
            delta_line = "↗️ <i>لا توجد بيانات كافية للمقارنة</i>"

        lines = [
            "📈 <b>نمو المستخدمين — 30 يوم</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📊 الإجمالي: <b>{_fmt_num(total_count)}</b>",
            f"📅 المتوسط اليومي: <b>{avg}</b>",
            f"🏔️ الذروة: <b>{_fmt_num(max_count)}</b>",
        ]
        if delta_line:
            lines.append(delta_line)
        lines.append("")

        if rows:
            lines.append("<b>آخر 10 أيام:</b>")
            for r in rows[-10:]:
                day = _html_mod.escape(str(r.get("date", "?"))[-5:])
                cnt = r.get("count", 0)
                bar = _bar(cnt, max_count or 1, width=8)
                lines.append(f"  <code>{day}</code> {bar} <b>{cnt}</b>")
        else:
            lines.append("<i>📭 لا توجد بيانات</i>")

        text = "\n".join(lines)
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="growth_30d_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_growth_30d: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل نمو المستخدمين</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 3) أفضل 10 قنوات
# ═══════════════════════════════════════════════════════════════════════

async def show_top_channels(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الحساب...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_top_channels"):
            raise AttributeError("DB.get_top_channels غير موجود")

        rows = await _cached_db_call(
            "top_channels_10",
            lambda: DB.get_top_channels(limit=10),
            ttl=60.0,
            force_refresh=False,
        )
        rows = rows or []

        lines = [
            "🏆 <b>أفضل 10 قنوات</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        if not rows:
            lines.append("<i>📭 لا توجد قنوات مسجّلة بعد.</i>")
        else:
            medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
            for i, r in enumerate(rows):
                name = _html_mod.escape((r.get("name") or "—")[:28])
                published = int(r.get("published") or 0)
                total = int(r.get("total") or 0)
                rate = r.get("success_rate", 0)
                lines.append(
                    f"{medals[i]} <b>{name}</b>\n"
                    f"   📤 {published}/{total} "
                    f"({rate}% نجاح)"
                )

        text = "\n".join(lines)
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="top_channels_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_top_channels: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل أفضل القنوات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 4) إحصائيات النشر
# ═══════════════════════════════════════════════════════════════════════

async def show_publish_stats(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الحساب...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_publish_stats"):
            raise AttributeError("DB.get_publish_stats غير موجود")

        stats = await _cached_db_call(
            "publish_stats",
            lambda: DB.get_publish_stats(),
            ttl=60.0,
            force_refresh=False,
        )
        stats = stats or {}

        total_ch = int(stats.get("total_channels") or 0)
        total_po = int(stats.get("total_posts") or 0)
        pub = int(stats.get("published") or 0)
        failed = int(stats.get("failed") or 0)
        pending = int(stats.get("pending") or 0)
        avg_posts = stats.get("avg_posts_per_channel", 0)
        avg_pub = stats.get("avg_published_per_channel", 0)
        succ = stats.get("success_rate", 0)
        comp = stats.get("completion_rate", 0)

        text = (
            "📊 <b>إحصائيات النشر</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📡 عدد القنوات: <b>{_fmt_num(total_ch)}</b>\n"
            f"📥 إجمالي المنشورات: <b>{_fmt_num(total_po)}</b>\n"
            f"✅ نُشرت: <b>{_fmt_num(pub)}</b>\n"
            f"❌ فشلت: <b>{_fmt_num(failed)}</b>\n"
            f"⏳ منتظرة: <b>{_fmt_num(pending)}</b>\n\n"
            f"📈 متوسط لكل قناة: <b>{avg_posts}</b>\n"
            f"📤 متوسط المنشور: <b>{avg_pub}</b>\n\n"
            f"🎯 نسبة النجاح: <b>{succ}%</b>\n"
            f"🏁 نسبة الإنجاز: <b>{comp}%</b>"
        )
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="publish_stats_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_publish_stats: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل إحصائيات النشر</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 5) نسبة النجاح
# ═══════════════════════════════════════════════════════════════════════

async def show_channels_rate(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الحساب...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_channel_success_rate"):
            raise AttributeError("DB.get_channel_success_rate غير موجود")

        rows = await _cached_db_call(
            "channels_rate_20",
            lambda: DB.get_channel_success_rate(
                limit=20, filter_min_attempts=3),
            ttl=60.0,
            force_refresh=False,
        )
        rows = rows or []

        lines = [
            "🎯 <b>نسبة النجاح</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "<i>الأقل نجاحاً أولاً (≥ 3 محاولات)</i>",
            "",
        ]

        if not rows:
            lines.append("<i>📭 لا توجد بيانات كافية بعد.</i>")
        else:
            rows = sorted(rows, key=lambda x: x.get("success_rate", 100))
            for r in rows[:15]:
                name = _html_mod.escape((r.get("name") or "—")[:24])
                rate = r.get("success_rate", 0)
                att = int(r.get("attempted") or 0)
                color = ("🟢" if rate >= 80
                         else ("🟡" if rate >= 50 else "🔴"))
                bar = _bar(rate, 100, width=10)
                lines.append(
                    f"{color} <b>{name}</b>\n"
                    f"   {bar} <b>{rate}%</b> ({att} محاولة)"
                )

        text = "\n".join(lines)
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="channels_rate_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_channels_rate: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل نسبة النجاح</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 6) الاشتراكات
# ═══════════════════════════════════════════════════════════════════════

async def show_subscriptions(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الحساب...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_subscription_rate"):
            raise AttributeError("DB.get_subscription_rate غير موجود")

        rows = await _cached_db_call(
            "subscriptions_6m",
            lambda: DB.get_subscription_rate(months=6),
            ttl=120.0,
            force_refresh=False,
        )
        rows = rows or []

        total = sum(r.get("count", 0) for r in rows)
        max_c = max((r.get("count", 0) for r in rows), default=0)

        lines = [
            "💎 <b>الاشتراكات — 6 أشهر</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📊 الإجمالي: <b>{_fmt_num(total)}</b>",
            "",
        ]

        if rows:
            for r in rows:
                month = _html_mod.escape(str(r.get("month", "?")))
                cnt = r.get("count", 0)
                bar = _bar(cnt, max_c or 1, width=10)
                lines.append(f"  <code>{month}</code> {bar} <b>{cnt}</b>")
        else:
            lines.append("<i>📭 لا توجد اشتراكات بعد.</i>")

        text = "\n".join(lines)
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="subscriptions_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_subscriptions: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل الاشتراكات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 7) Pool مباشر
# ═══════════════════════════════════════════════════════════════════════

async def show_pool_live(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الفحص...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_pool_live"):
            raise AttributeError("DB.get_pool_live غير موجود")

        pool = await DB.get_pool_live() or {}

        if not pool.get("available"):
            reason = _html_mod.escape(str(pool.get("type", "unknown")))
            await _safe_edit(
                query,
                f"⚠️ Pool غير متاح: <code>{reason}</code>",
                _back_keyboard("admin_analytics"),
            )
            return

        util = pool.get("utilization_pct", 0)
        color = "🟢" if util < 50 else ("🟡" if util < 80 else "🔴")
        bar = _bar(util, 100, width=15)

        lines = [
            "🚀 <b>Pool مباشر</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"{color} الاستخدام: <b>{util}%</b>",
            f"<code>{bar}</code>",
            "",
            f"📊 الحجم: <b>{pool.get('in_use', 0)}/{pool.get('max_size', 0)}</b>",
            f"🆓 فاضي: <b>{pool.get('idle_size', 0)}</b>",
            f"🔗 مفتوح: <b>{pool.get('current_size', 0)}</b>",
        ]

        if "rollback_timeout" in pool:
            lines.append(
                f"\n⏱️ rollback timeout: "
                f"<b>{pool['rollback_timeout']}s</b>")
        if "idle_tx_audit_active" in pool:
            active = pool["idle_tx_audit_active"]
            icon = "✅" if active else "❌"
            lines.append(
                f"{icon} رصد idle-tx: "
                f"<b>{'نشط' if active else 'معطّل'}</b>")
        if "idle_tx_last_count" in pool:
            cnt = pool["idle_tx_last_count"]
            ic = "🟢" if cnt == 0 else ("🟠" if cnt < 3 else "🔴")
            lines.append(f"{ic} idle-tx آخر قراءة: <b>{cnt}</b>")

        lines.append(f"\n🕐 <i>{TimeUtils.mecca_iso()[:19]}</i>")

        text = "\n".join(lines)
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="pool_live_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_pool_live: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل Pool</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 8) أبطأ الاستعلامات
# ═══════════════════════════════════════════════════════════════════════

async def show_slow_queries(update: Update,
                            context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري الفحص...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        if not hasattr(DB, "get_slowest_queries"):
            raise AttributeError("DB.get_slowest_queries غير موجود")

        rows = await _cached_db_call(
            "slow_queries_15",
            lambda: DB.get_slowest_queries(limit=15),
            ttl=30.0,
            force_refresh=False,
        )
        rows = rows or []

        lines = [
            "🐌 <b>أبطأ الاستعلامات</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        if not rows:
            lines.append(
                "<i>📭 لا توجد استعلامات بطيئة مسجّلة.</i>\n\n"
                "💡 تظهر هنا الاستعلامات التي تتجاوز العتبة."
            )
        else:
            for i, r in enumerate(rows[:10], 1):
                q_raw = (r.get("query") or r.get("sql") or "?")[:80]
                elapsed = r.get("elapsed", 0)
                q = _html_mod.escape(q_raw)
                lines.append(
                    f"{i}. <code>{q}</code>\n"
                    f"   ⏱️ <b>{_fmt_elapsed(elapsed)}</b>"
                )
                caller_file = r.get("caller_file")
                caller_line = r.get("caller_line")
                if caller_file or caller_line is not None:
                    loc = _html_mod.escape(
                        f"{caller_file or '?'}:{caller_line or '?'}"
                    )[:80]
                    lines.append(f"   📍 <code>{loc}</code>")
                ts = r.get("time") or r.get("created_at")
                if ts:
                    try:
                        if isinstance(ts, (int, float)):
                            ts_str = datetime.fromtimestamp(
                                float(ts)
                            ).strftime("%m-%d %H:%M")
                        else:
                            ts_str = str(ts)[:16]
                        lines.append(
                            f"   🕐 <i>{_html_mod.escape(ts_str)}</i>"
                        )
                    except Exception:
                        pass
                lines.append("")

        text = "\n".join(lines)
        kb = _back_refresh_keyboard(
            target="admin_analytics", refresh="slow_queries_btn")
        await _safe_edit(query, text, kb)
    except Exception as e:
        logger.error("show_slow_queries: %s", e, exc_info=True)
        err_html = _err_detail(e)
        await _safe_edit(
            query,
            f"❌ <b>فشل أبطأ الاستعلامات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
            _back_keyboard("admin_analytics"),
        )


# ═══════════════════════════════════════════════════════════════════════
# 9) تصدير Excel
# ═══════════════════════════════════════════════════════════════════════

async def export_excel(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await _quick_answer(query, "⏳ جاري التصدير...")

    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    if query is None or getattr(query, 'message', None) is None:
        if chat_id is not None:
            await safe_send(
                context.bot, chat_id,
                "❌ هذا الزر يعمل من داخل القائمة فقط.")
        return

    try:
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            await query.answer(
                "❌ مكتبة openpyxl غير مُثبّتة.\n"
                "ثبّتها: pip install openpyxl",
                show_alert=True,
            )
            return

        import openpyxl
        wb = openpyxl.Workbook()

        ws1 = wb.active
        ws1.title = "User Growth"
        ws1.append(["Date", "Count"])
        rows1 = await _cached_db_call(
            "export_growth_30d",
            lambda: DB.get_user_growth(days=30),
            ttl=60.0,
            force_refresh=False,
        ) or []
        for r in rows1:
            ws1.append([r.get("date"), r.get("count")])

        ws2 = wb.create_sheet("Top Channels")
        ws2.append([
            "Name", "Channel ID", "Total", "Published",
            "Failed", "Success %", "Completion %",
        ])
        rows2 = await _cached_db_call(
            "export_top_channels_50",
            lambda: DB.get_top_channels(limit=50),
            ttl=60.0,
            force_refresh=False,
        ) or []
        for r in rows2:
            ws2.append([
                r.get("name"), r.get("channel_id"),
                r.get("total"), r.get("published"),
                r.get("failed"), r.get("success_rate"),
                r.get("completion_rate"),
            ])

        ws3 = wb.create_sheet("Publish Stats")
        stats = await _cached_db_call(
            "export_publish_stats",
            lambda: DB.get_publish_stats(),
            ttl=60.0,
            force_refresh=False,
        ) or {}
        ws3.append(["Metric", "Value"])
        for k, v in stats.items():
            ws3.append([k, v])

        ws4 = wb.create_sheet("Subscriptions")
        ws4.append(["Month", "Count"])
        rows4 = await _cached_db_call(
            "export_subscriptions_12m",
            lambda: DB.get_subscription_rate(months=12),
            ttl=120.0,
            force_refresh=False,
        ) or []
        for r in rows4:
            ws4.append([r.get("month"), r.get("count")])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        MAX_BYTES = 20 * 1024 * 1024
        size_bytes = buf.getbuffer().nbytes
        if size_bytes > MAX_BYTES:
            logger.warning(
                "export_excel: الملف %d bytes > %d",
                size_bytes, MAX_BYTES,
            )
            await _safe_edit(
                query,
                f"❌ <b>الملف كبير جداً</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💾 الحجم: <b>{size_bytes / (1024*1024):.1f}MB</b>\n"
                f"الحد: 20MB",
                _back_keyboard("admin_analytics"),
            )
            return

        filename = (
            f"analytics_"
            f"{TimeUtils.utc_now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )

        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=buf,
            filename=filename,
            caption=(
                f"📤 <b>تصدير التحليلات</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 4 أوراق\n"
                f"💾 الحجم: <b>{size_bytes / 1024:.1f} KB</b>"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error("export_excel: %s", e, exc_info=True)
        err_html = _err_detail(e)
        try:
            await _safe_edit(
                query,
                f"❌ <b>فشل تصدير Excel</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
                _back_keyboard("admin_analytics"),
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# 10) التشخيص الشامل
# ═══════════════════════════════════════════════════════════════════════

async def show_full_health(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)

    await _quick_answer(query, "⏳ جاري التشخيص... (5-10s)")

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    if chat_id is None:
        return

    waiting_text = (
        "🏥 <b>التشخيص الشامل جارٍ...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔬 يقيس 6 أبعاد:\n"
        "  🌐 الشبكة → DB\n"
        "  📨 الشبكة → Telegram\n"
        "  🗄️ DB Internal\n"
        "  🔄 Event Loop\n"
        "  💾 القرص\n"
        "  ⚙️ CPU/RAM\n\n"
        "⏳ يرجى الانتظار 5-10 ثواني..."
    )

    waiting_msg = None
    if query:
        try:
            await _safe_edit(query, waiting_text, None)
        except Exception as e:
            logger.debug(f"show_full_health waiting (edit): {e}")
    else:
        try:
            waiting_msg = await context.bot.send_message(
                chat_id, waiting_text, parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"show_full_health waiting (send): {e}")

    async def _cleanup_waiting(success: bool = False):
        if waiting_msg is None:
            return
        try:
            if success:
                await waiting_msg.edit_text(
                    "✅ <b>التقرير جاهز 👇</b>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            else:
                await waiting_msg.delete()
        except Exception as e:
            logger.debug(f"_cleanup_waiting: {e}")

    try:
        from db_diagnostics import diagnose_full
    except Exception as ie:
        err = (
            "❌ <b>db_diagnostics غير متاح</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<code>{_html_mod.escape(str(ie)[:300])}</code>\n\n"
            "💡 تأكد من وجود <code>diagnose_full</code> في "
            "<code>db_diagnostics.py</code> v7.2.0+."
        )
        await _cleanup_waiting(success=False)
        if query:
            await _safe_edit(query, err, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err)
        return

    try:
        report = await diagnose_full(force=True)
        if not report:
            report = "⚠️ لا توجد بيانات."

        back_kb = _back_refresh_keyboard(
            target="admin_analytics",
            refresh="full_health_btn",
        )

        MAX_SINGLE = 3800
        if len(report) <= MAX_SINGLE and query:
            ok = await _safe_edit(query, report, back_kb)
            if ok:
                return
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )
        else:
            await _cleanup_waiting(success=True)
            if query:
                try:
                    await _safe_edit(
                        query,
                        "✅ <b>التقرير جاهز 👇</b>",
                        None,
                    )
                except Exception as e:
                    logger.debug(f"show_full_health after: {e}")
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )

    except Exception as e:
        logger.error("show_full_health: %s", e, exc_info=True)
        await _cleanup_waiting(success=False)
        err_html = _err_detail(e)
        err_text = (
            f"❌ <b>فشل التشخيص الشامل</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}"
        )
        if query:
            await _safe_edit(
                query, err_text, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err_text)


# ═══════════════════════════════════════════════════════════════════════
# 11) اختبار الكمون
# ═══════════════════════════════════════════════════════════════════════

async def show_latency(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)

    await _quick_answer(query, "⏳ جاري اختبار الكمون...")

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    if chat_id is None:
        return

    waiting_text = (
        "🔬 <b>جاري اختبار الكمون...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⏳ 3-5 ثواني..."
    )

    waiting_msg = None
    if query:
        try:
            await _safe_edit(query, waiting_text, None)
        except Exception as e:
            logger.debug(f"show_latency waiting (edit): {e}")
    else:
        try:
            waiting_msg = await context.bot.send_message(
                chat_id, waiting_text, parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"show_latency waiting (send): {e}")

    async def _cleanup_waiting(success: bool = False):
        if waiting_msg is None:
            return
        try:
            if success:
                await waiting_msg.edit_text(
                    "✅ <b>التقرير جاهز 👇</b>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            else:
                await waiting_msg.delete()
        except Exception as e:
            logger.debug(f"_cleanup_waiting: {e}")

    try:
        from db_diagnostics import diagnose_latency
    except Exception as ie:
        err = (
            "❌ <b>db_diagnostics غير متاح</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<code>{_html_mod.escape(str(ie)[:300])}</code>\n\n"
            "💡 تأكد من وجود <code>diagnose_latency</code> في "
            "<code>db_diagnostics.py</code> v7.1.0+."
        )
        await _cleanup_waiting(success=False)
        if query:
            await _safe_edit(query, err, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err)
        return

    try:
        report = await diagnose_latency(force=True)
        if not report:
            report = "⚠️ لا توجد بيانات."

        back_kb = _back_refresh_keyboard(
            target="admin_analytics",
            refresh="latency_btn",
        )

        MAX_SINGLE = 3800
        if len(report) <= MAX_SINGLE and query:
            ok = await _safe_edit(query, report, back_kb)
            if ok:
                return
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )
        else:
            await _cleanup_waiting(success=True)
            if query:
                try:
                    await _safe_edit(
                        query,
                        "✅ <b>التقرير جاهز 👇</b>",
                        None,
                    )
                except Exception as e:
                    logger.debug(f"show_latency after: {e}")
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )

    except Exception as e:
        logger.error("show_latency: %s", e, exc_info=True)
        await _cleanup_waiting(success=False)
        err_html = _err_detail(e)
        err_text = (
            f"❌ <b>فشل اختبار الكمون</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}"
        )
        if query:
            await _safe_edit(
                query, err_text, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err_text)


# ═══════════════════════════════════════════════════════════════════════
# 12) Multi-DB Discovery
# ═══════════════════════════════════════════════════════════════════════

async def show_databases(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """🗂️ تقرير قواعد البيانات المُعدّة + النشطة."""
    query = update.callback_query
    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)

    await _quick_answer(query, "⏳ جاري الفحص...")

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    if chat_id is None:
        return

    try:
        from db_diagnostics import diagnose_databases
    except Exception as ie:
        err = (
            "❌ <b>db_diagnostics غير متاح</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<code>{_html_mod.escape(str(ie)[:300])}</code>\n\n"
            "💡 تأكد من وجود <code>diagnose_databases</code> في "
            "<code>db_diagnostics.py</code> v7.2.13+."
        )
        if query:
            await _safe_edit(query, err, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err)
        return

    try:
        report = await diagnose_databases()
        if not report:
            report = "⚠️ لا توجد بيانات."

        back_kb = _back_refresh_keyboard(
            target="admin_analytics",
            refresh="databases_btn",
        )

        MAX_SINGLE = 3800
        if len(report) <= MAX_SINGLE and query:
            ok = await _safe_edit(query, report, back_kb)
            if ok:
                return
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )
        else:
            if query:
                try:
                    await _safe_edit(
                        query,
                        "✅ <b>التقرير جاهز 👇</b>",
                        None,
                    )
                except Exception as e:
                    logger.debug(f"show_databases after: {e}")
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )

    except Exception as e:
        logger.error("show_databases: %s", e, exc_info=True)
        err_html = _err_detail(e)
        err_text = (
            f"❌ <b>فشل قواعد البيانات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}"
        )
        if query:
            await _safe_edit(
                query, err_text, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err_text)


# ═══════════════════════════════════════════════════════════════════════
# 12b) ضبط autovacuum (db_diagnostics v7.2.24+)
# ═══════════════════════════════════════════════════════════════════════

async def show_autotune(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """⚙️ ضبط autovacuum تلقائي — تقرير + تنفيذ فوري."""
    query = update.callback_query
    chat_id = _safe_get_chat_id(update, query)
    user_id = _get_safe_user_id(update)

    await _quick_answer(query, "⏳ جاري الضبط...")

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    if chat_id is None:
        return

    if not _AUTOTUNE_AVAILABLE or _diagnose_autovacuum_tuning_fn is None:
        err = (
            "⚙️ <b>ضبط autovacuum — غير متاح</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"❌ يتطلب <code>db_diagnostics ≥ v7.2.24</code>\n"
            f"📦 الحالي: <code>{_html_mod.escape(str(_DB_DIAG_VERSION_AT))}</code>\n"
        )
        if _AUTOTUNE_IMPORT_ERROR:
            err += (
                f"\n<b>سبب الاستيراد:</b>\n"
                f"<code>{_html_mod.escape(_AUTOTUNE_IMPORT_ERROR[:200])}</code>\n"
            )
        err += (
            "\n💡 <b>الحل:</b> ارفع <code>db_diagnostics.py</code> "
            "إلى v7.2.24+ (يحتوي على ensure_autovacuum_tuning)."
        )
        kb = _back_keyboard("admin_analytics")
        if query:
            await _safe_edit(query, err, kb)
        else:
            await safe_send(context.bot, chat_id, err, reply_markup=kb)
        return

    try:
        if not bool(getattr(DB, "USE_POSTGRES", False)):
            err = (
                "⚠️ <b>الضبط التلقائي يتطلب PostgreSQL</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"النوع الحالي: "
                f"<code>{_html_mod.escape(str(getattr(DB, 'DB_TYPE', '?')).upper())}</code>"
            )
            kb = _back_keyboard("admin_analytics")
            if query:
                await _safe_edit(query, err, kb)
            else:
                await safe_send(context.bot, chat_id, err, reply_markup=kb)
            return
    except Exception:
        pass

    waiting_text = (
        "⚙️ <b>جاري ضبط autovacuum...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔍 فحص reloptions الحالية + اكتشاف الجداول عالية الـ churn\n"
        "⏳ 2-5 ثواني..."
    )

    waiting_msg = None
    if query:
        try:
            await _safe_edit(query, waiting_text, None)
        except Exception as e:
            logger.debug(f"show_autotune waiting (edit): {e}")
    else:
        try:
            waiting_msg = await context.bot.send_message(
                chat_id, waiting_text, parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"show_autotune waiting (send): {e}")

    async def _cleanup_waiting(success: bool = False):
        if waiting_msg is None:
            return
        try:
            if success:
                await waiting_msg.edit_text(
                    "✅ <b>التقرير جاهز 👇</b>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            else:
                await waiting_msg.delete()
        except Exception as e:
            logger.debug(f"_cleanup_waiting: {e}")

    try:
        report = await _diagnose_autovacuum_tuning_fn(force=True)
        if not report:
            report = "⚠️ لا توجد بيانات."

        back_kb = _back_refresh_keyboard(
            target="admin_analytics",
            refresh="autotune_btn",
        )

        MAX_SINGLE = 3800
        if len(report) <= MAX_SINGLE and query:
            ok = await _safe_edit(query, report, back_kb)
            if ok:
                return
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )
        else:
            await _cleanup_waiting(success=True)
            if query:
                try:
                    await _safe_edit(
                        query,
                        "✅ <b>التقرير جاهز 👇</b>",
                        None,
                    )
                except Exception as e:
                    logger.debug(f"show_autotune after: {e}")
            await _safe_send_long(
                context.bot, chat_id, report,
                reply_markup=back_kb,
            )

    except Exception as e:
        logger.error("show_autotune: %s", e, exc_info=True)
        await _cleanup_waiting(success=False)
        err_html = _err_detail(e)
        err_text = (
            f"❌ <b>فشل ضبط autovacuum</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}"
        )
        if query:
            await _safe_edit(
                query, err_text, _back_keyboard("admin_analytics"))
        else:
            await safe_send(context.bot, chat_id, err_text)


# ═══════════════════════════════════════════════════════════════════════
# 12c) /files — عرض كل ملفات المشروع
# ═══════════════════════════════════════════════════════════════════════

def _cmd_files_scan_sync(root: Path) -> Tuple[List, List, List, int]:
    """
    🆕 v1.3.8 FIX-CMD-FILES-SYNC: نسخة متزامنة.
    تُنفَّذ في `_AUDIT_EXECUTOR` — لا تحجب الحلقة الرئيسية أثناء استيراد
    الوحدات (importlib متزامن = 10-30s على 200 وحدة).
    """
    py_files: List[Path] = []
    try:
        for py_file in root.rglob("*.py"):
            try:
                parts = py_file.relative_to(root).parts
            except ValueError:
                continue
            if any(p in _EXCLUDED_DIRS for p in parts[:-1]):
                continue
            if py_file.name in _SKIP_FILENAMES:
                continue
            py_files.append(py_file)
            if len(py_files) >= _MAX_FILES_SCAN:
                logger.warning(
                    "cmd_files: reached %d files, truncating",
                    _MAX_FILES_SCAN,
                )
                break
    except Exception as e:
        logger.warning(f"_cmd_files_scan_sync rglob: {e}")

    py_files.sort(key=lambda p: str(p.relative_to(root)).lower())

    loaded: List[Dict[str, Any]] = []
    no_version: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for py_file in py_files:
        try:
            rel = py_file.relative_to(root)
            mod_path = _file_to_module_path(rel)
            if not mod_path:
                continue

            if rel.parent == Path("."):
                candidates = [mod_path]
                if rel.name == "bot.py":
                    candidates = ["bot", "__main__"]
            else:
                candidates = [mod_path]
                if len(rel.parts) >= 2:
                    candidates.append(rel.stem)

            mod, err = _try_import_any(candidates)

            if mod is None:
                failed.append({
                    "name": str(rel),
                    "reason": err or "unknown",
                })
                continue

            ver = _extract_version(mod)
            if ver:
                loaded.append({
                    "name": str(rel),
                    "version": str(ver),
                })
            else:
                no_version.append({"name": str(rel)})
        except Exception as e:
            failed.append({
                "name": str(py_file),
                "reason": f"{type(e).__name__}: {str(e)[:80]}",
            })

    return loaded, no_version, failed, len(py_files)


async def cmd_files(update: Update,
                    context: ContextTypes.DEFAULT_TYPE) -> None:
    """📂 v1.3.5 — عرض كل ملفات المشروع .py ديناميكياً."""
    user_id = _get_safe_user_id(update)
    chat_id = _safe_get_chat_id(update, None)
    query = update.callback_query

    if query:
        await _quick_answer(query, "⏳ جاري فحص الملفات...")

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    waiting_text = (
        "📂 <b>جاري فحص ملفات المشروع...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔍 يبحث في root + handlers/ + subdirs\n"
        "⏳ 2-5 ثواني..."
    )

    waiting_msg = None
    if query:
        try:
            await _safe_edit(query, waiting_text, None)
        except Exception as e:
            logger.debug(f"cmd_files waiting (edit): {e}")
    else:
        try:
            waiting_msg = await context.bot.send_message(
                chat_id, waiting_text, parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"cmd_files waiting (send): {e}")

    try:
        root = _find_project_root()

        # 🆕 v1.3.8 FIX-CMD-FILES-SYNC: المسح والاستيراد في thread منفصل
        loop = asyncio.get_running_loop()
        try:
            loaded, no_version, failed, total = await asyncio.wait_for(
                loop.run_in_executor(
                    _get_audit_executor(),
                    _cmd_files_scan_sync,
                    root,
                ),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            logger.warning("cmd_files: timeout 60s")
            await _cleanup_waiting_msg(waiting_msg)
            err = (
                "❌ <b>فحص الملفات تجاوز المهلة (60s)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 عدد الملفات كبير — قلّل _MAX_FILES_SCAN."
            )
            if query:
                await _safe_edit(query, err, _back_keyboard("admin_analytics"))
            elif chat_id is not None:
                await safe_send(context.bot, chat_id, err)
            return

        lines: List[str] = []
        lines.append("📂 <b>ملفات المشروع (.py)</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("")
        lines.append(f"📊 إجمالي: <b>{total}</b> ملف")
        lines.append(f"✅ محمّل بإصدار: <b>{len(loaded)}</b>")
        lines.append(f"🟡 محمّل بلا إصدار: <b>{len(no_version)}</b>")
        lines.append(f"❌ فشل الاستيراد: <b>{len(failed)}</b>")
        lines.append("")

        by_dir: Dict[str, List[Dict[str, Any]]] = {}
        for item in loaded:
            try:
                parent = str(Path(item["name"]).parent)
            except Exception:
                parent = "?"
            if parent == "." or parent == "":
                parent = "(root)"
            by_dir.setdefault(parent, []).append(item)

        for parent in sorted(by_dir.keys(), key=lambda x: (x != "(root)", x)):
            lines.append(f"<b>📁 {_html_mod.escape(parent)}</b>")
            for item in by_dir[parent]:
                try:
                    name = Path(item["name"]).name
                except Exception:
                    name = item["name"]
                lines.append(
                    f"  ✅ <code>{_html_mod.escape(name)}</code>: "
                    f"v{_html_mod.escape(item['version'])}"
                )
            lines.append("")

        if no_version:
            lines.append(f"<b>🟡 بلا إصدار ({len(no_version)}):</b>")
            for item in no_version[:25]:
                try:
                    name = Path(item["name"]).name
                except Exception:
                    name = item["name"]
                lines.append(
                    f"  🟡 <code>{_html_mod.escape(name)}</code>"
                )
            if len(no_version) > 25:
                lines.append(f"  … و{len(no_version) - 25} آخر")
            lines.append("")

        if failed:
            lines.append(f"<b>❌ فشل الاستيراد ({len(failed)}):</b>")
            for item in failed[:15]:
                try:
                    name = Path(item["name"]).name
                except Exception:
                    name = item["name"]
                lines.append(
                    f"  ❌ <code>{_html_mod.escape(name)}</code>\n"
                    f"     <i>{_html_mod.escape(item['reason'][:100])}</i>"
                )
            if len(failed) > 15:
                lines.append(f"  … و{len(failed) - 15} آخر")
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        try:
            lines.append(
                f"📂 <b>المسح من:</b> "
                f"<code>{_html_mod.escape(str(root))}</code>"
            )
        except Exception:
            pass
        lines.append(f"🕐 <i>{TimeUtils.mecca_iso()[:19]}</i>")

        text = "\n".join(lines)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔄 إعادة الفحص",
                callback_data="files_refresh",
            )],
            [InlineKeyboardButton(
                "📦 الإصدارات المختصرة",
                callback_data="versions_refresh",
            )],
            [InlineKeyboardButton(
                "🔙 رجوع",
                callback_data="admin",
            )],
        ])

        MAX_SINGLE = 3800
        if query:
            if len(text) <= MAX_SINGLE:
                ok = await _safe_edit(query, text, kb)
                if ok:
                    return
            try:
                if waiting_msg is not None:
                    await waiting_msg.delete()
            except Exception:
                pass
            if chat_id is not None:
                await _safe_send_long(
                    context.bot, chat_id, text,
                    reply_markup=kb,
                )
        elif chat_id is not None:
            try:
                if waiting_msg is not None:
                    await waiting_msg.delete()
            except Exception:
                pass
            await _safe_send_long(
                context.bot, chat_id, text,
                reply_markup=kb,
            )

    except Exception as e:
        logger.error("cmd_files: %s", e, exc_info=True)
        try:
            if waiting_msg is not None:
                await waiting_msg.delete()
        except Exception:
            pass
        err_html = _err_detail(e)
        err_text = (
            f"❌ <b>فشل فحص الملفات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}"
        )
        if query:
            await _safe_edit(
                query, err_text, _back_keyboard("admin_analytics"))
        elif chat_id is not None:
            await safe_send(context.bot, chat_id, err_text)


async def _cleanup_waiting_msg(waiting_msg):
    """v1.3.8: مساعد — يحذف رسالة الانتظار."""
    if waiting_msg is None:
        return
    try:
        await waiting_msg.delete()
    except Exception as e:
        logger.debug(f"_cleanup_waiting_msg: {e}")


# ═══════════════════════════════════════════════════════════════════════
# 13) /audit — فحص شامل
# ═══════════════════════════════════════════════════════════════════════

async def cmd_audit(update: Update,
                    context: ContextTypes.DEFAULT_TYPE) -> None:
    """🔍 فحص شامل لكل ملفات المشروع .py."""
    user_id = _get_safe_user_id(update)
    chat_id = _safe_get_chat_id(update, None)
    query = update.callback_query

    if query:
        await _quick_answer(query, "⏳ جاري الفحص...")

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    waiting_text = (
        "🔍 <b>جاري الفحص الشامل...</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📂 حتى {_MAX_AUDIT_FILES} ملف\n"
        "🔬 AST + Patterns + PTB + Bot-specific\n"
        "⏳ 10-30 ثانية..."
    )

    waiting_msg = None
    if query:
        try:
            await _safe_edit(query, waiting_text, None)
        except Exception as e:
            logger.debug(f"cmd_audit waiting (edit): {e}")
    else:
        try:
            waiting_msg = await context.bot.send_message(
                chat_id, waiting_text, parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"cmd_audit waiting (send): {e}")

    try:
        root = _find_project_root()
        files = await _audit_collect_files(root)
        if not files:
            err = "⚠️ لم يتم العثور على ملفات .py للفحص."
            if query:
                await _safe_edit(query, err, _back_keyboard("admin_analytics"))
            elif chat_id is not None:
                await safe_send(context.bot, chat_id, err)
            return

        reports = await _audit_run_reports(files)
        summary = _audit_summary_html(reports, root)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "📄 تقرير Markdown",
                callback_data="audit_md_btn",
            ),
             InlineKeyboardButton(
                "💾 تقرير JSON",
                callback_data="audit_json_btn",
            )],
            [InlineKeyboardButton(
                "🔄 إعادة الفحص",
                callback_data="audit_btn",
            )],
            [InlineKeyboardButton(
                "🔙 رجوع",
                callback_data="admin_analytics",
            )],
        ])

        try:
            _cache_key = f"audit_reports:{user_id}"
            context.bot_data[_cache_key] = {
                "reports": reports,
                "root": str(root),
                "ts": time.time(),
            }
            for k in list(context.bot_data.keys()):
                if isinstance(k, str) and k.startswith("audit_reports:"):
                    entry = context.bot_data.get(k)
                    if isinstance(entry, dict):
                        try:
                            if time.time() - entry.get("ts", 0) > 600:
                                context.bot_data.pop(k, None)
                        except Exception:
                            pass
        except Exception as e:
            logger.debug(f"cmd_audit cache store: {e}")

        MAX_SINGLE = 3800
        if query:
            if len(summary) <= MAX_SINGLE:
                ok = await _safe_edit(query, summary, kb)
                if ok:
                    return
            try:
                if waiting_msg is not None:
                    await waiting_msg.delete()
            except Exception:
                pass
            if chat_id is not None:
                await _safe_send_long(
                    context.bot, chat_id, summary, reply_markup=kb)
        elif chat_id is not None:
            try:
                if waiting_msg is not None:
                    await waiting_msg.delete()
            except Exception:
                pass
            await _safe_send_long(
                context.bot, chat_id, summary, reply_markup=kb)

    except Exception as e:
        logger.error("cmd_audit: %s", e, exc_info=True)
        try:
            if waiting_msg is not None:
                await waiting_msg.delete()
        except Exception:
            pass
        err_text = (
            f"❌ <b>فشل الفحص الشامل</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{_err_detail(e)}"
        )
        if query:
            await _safe_edit(
                query, err_text, _back_keyboard("admin_analytics"))
        elif chat_id is not None:
            await safe_send(context.bot, chat_id, err_text)


async def _audit_send_markdown(update: Update,
                                context: ContextTypes.DEFAULT_TYPE,
                                user_id: int) -> None:
    query = update.callback_query
    chat_id = _safe_get_chat_id(update, query)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    cache_key = f"audit_reports:{user_id}"
    entry = context.bot_data.get(cache_key)
    if not entry:
        err = (
            "⚠️ لا توجد تقارير محفوظة.\n"
            "شغّل /audit أولاً."
        )
        if query:
            await query.answer(err, show_alert=True)
        elif chat_id is not None:
            await safe_send(context.bot, chat_id, err)
        return

    reports = entry.get("reports") or []
    root_str = entry.get("root")
    root = Path(root_str) if root_str else None

    try:
        md = _audit_to_markdown(reports, root)
        buf = io.BytesIO(md.encode("utf-8"))
        buf.seek(0)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"audit_report_{ts}.md"
        await context.bot.send_document(
            chat_id=chat_id,
            document=buf,
            filename=filename,
            caption=(
                f"📄 <b>تقرير Markdown</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📂 الملفات: <b>{len(reports)}</b>\n"
                f"📏 الحجم: <b>{len(md):,} حرف</b>"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"_audit_send_markdown: {e}", exc_info=True)
        if chat_id is not None:
            await safe_send(
                context.bot, chat_id,
                f"❌ فشل إرسال Markdown: {_err_detail(e)}",
            )


async def _audit_send_json(update: Update,
                            context: ContextTypes.DEFAULT_TYPE,
                            user_id: int) -> None:
    query = update.callback_query
    chat_id = _safe_get_chat_id(update, query)
    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    cache_key = f"audit_reports:{user_id}"
    entry = context.bot_data.get(cache_key)
    if not entry:
        err = (
            "⚠️ لا توجد تقارير محفوظة.\n"
            "شغّل /audit أولاً."
        )
        if query:
            await query.answer(err, show_alert=True)
        elif chat_id is not None:
            await safe_send(context.bot, chat_id, err)
        return

    reports = entry.get("reports") or []
    try:
        data = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "root": entry.get("root"),
            "total_files": len(reports),
            "reports": [_dc_asdict(r) for r in reports],
        }
        js = _json_mod.dumps(data, ensure_ascii=False, indent=2)
        buf = io.BytesIO(js.encode("utf-8"))
        buf.seek(0)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"audit_report_{ts}.json"
        await context.bot.send_document(
            chat_id=chat_id,
            document=buf,
            filename=filename,
            caption=(
                f"💾 <b>تقرير JSON</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📂 الملفات: <b>{len(reports)}</b>"
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(f"_audit_send_json: {e}", exc_info=True)
        if chat_id is not None:
            await safe_send(
                context.bot, chat_id,
                f"❌ فشل إرسال JSON: {_err_detail(e)}",
            )


async def cmd_audit_full(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """🔍 فحص كل الملفات + تقرير مفصل."""
    await cmd_audit(update, context)


async def cmd_audit_critical(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """🔴 فحص CRITICAL/HIGH فقط."""
    user_id = _get_safe_user_id(update)
    chat_id = _safe_get_chat_id(update, None)
    query = update.callback_query

    if query:
        await _quick_answer(query, "⏳ جاري الفحص...")

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    try:
        root = _find_project_root()
        files = await _audit_collect_files(root)
        reports = await _audit_run_reports(files)

        critical_only = []
        for r in reports:
            if r.parse_error:
                continue
            crits = [f for f in r.findings
                     if f.severity in ("CRITICAL", "HIGH")]
            if crits:
                critical_only.append((Path(r.file).name, crits))

        if not critical_only:
            text = (
                "✅ <b>لا توجد مشاكل CRITICAL/HIGH</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📂 فُحص {len(reports)} ملف"
            )
        else:
            lines = [
                "🔴 <b>مشاكل CRITICAL/HIGH فقط</b>",
                "━━━━━━━━━━━━━━━━━━━━━━",
                "",
            ]
            total = sum(len(c) for _, c in critical_only)
            lines.append(f"📊 الإجمالي: <b>{total}</b>")
            lines.append("")
            for fname, crits in critical_only[:10]:
                lines.append(
                    f"\n📄 <b>{_html_mod.escape(fname)}</b> ({len(crits)})")
                for c in crits[:5]:
                    icon = _SEVERITY_ICONS[c.severity]
                    lines.append(
                        f"  {icon} L{c.line} <code>{c.rule_id}</code>\n"
                        f"     <i>{_html_mod.escape(c.message[:100])}</i>"
                    )
                if len(crits) > 5:
                    lines.append(f"  … و{len(crits) - 5} آخر")
            text = "\n".join(lines)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔄 إعادة الفحص",
                callback_data="audit_btn",
            )],
            [InlineKeyboardButton(
                "🔙 رجوع",
                callback_data="admin_analytics",
            )],
        ])

        if query:
            ok = await _safe_edit(query, text, kb)
            if not ok and chat_id is not None:
                await _safe_send_long(
                    context.bot, chat_id, text, reply_markup=kb)
        elif chat_id is not None:
            await _safe_send_long(
                context.bot, chat_id, text, reply_markup=kb)

    except Exception as e:
        logger.error("cmd_audit_critical: %s", e, exc_info=True)
        err_text = (
            f"❌ <b>فشل الفحص</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n{_err_detail(e)}"
        )
        if query:
            await _safe_edit(
                query, err_text, _back_keyboard("admin_analytics"))
        elif chat_id is not None:
            await safe_send(context.bot, chat_id, err_text)


# ═══════════════════════════════════════════════════════════════════════
# 14) /versions
# ═══════════════════════════════════════════════════════════════════════

async def cmd_versions(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = _get_safe_user_id(update)
    chat_id = _safe_get_chat_id(update, None)
    query = update.callback_query

    if query:
        await _quick_answer(query)

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    modules_to_check: List[Tuple[str, List[str]]] = [
        ("bot.py", ["bot"]),
        ("config.py", ["config"]),
        ("database.py", ["database"]),
        ("db_diagnostics.py", ["db_diagnostics"]),
        ("database_groups.py", ["database_groups"]),
        ("database_channels_posts.py", ["database_channels_posts"]),
        ("database_subscriptions.py", ["database_subscriptions"]),
        ("db_maintenance_commands.py", ["db_maintenance_commands"]),
        ("handlers_message.py",
         ["handlers.handlers_message", "handlers_message"]),
        ("handlers_command.py",
         ["handlers.handlers_command", "handlers_command"]),
        ("handlers_callback.py",
         ["handlers.handlers_callback", "handlers_callback"]),
        ("handlers_analytics.py",
         ["handlers.handlers_analytics", "handlers_analytics"]),
        ("handlers_channels_list.py",
         ["handlers.handlers_channels_list", "handlers_channels_list"]),
        ("handlers_membership.py",
         ["handlers.handlers_membership", "handlers_membership"]),
        ("handlers_group_log.py",
         ["handlers.handlers_group_log", "handlers_group_log"]),
        ("handlers_message_detectors.py",
         ["handlers.handlers_message_detectors",
          "handlers_message_detectors"]),
        ("cache.py", ["cache"]),
        ("utils.py", ["utils"]),
        ("sleep_probe.py", ["sleep_probe"]),
    ]

    lines = [
        "📦 <b>الإصدارات الحالية</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    loaded = 0
    missing = 0

    for name, paths in modules_to_check:
        mod = None
        last_err: Optional[str] = None

        for path in paths:
            try:
                mod = importlib.import_module(path)
                break
            except ImportError as _ie:
                last_err = f"{type(_ie).__name__}"
                continue
            except Exception as _ex:
                last_err = f"{type(_ex).__name__}"
                continue

        if mod is None:
            lines.append(
                f"❌ <code>{name}</code>: <i>غير محمّل</i>"
                + (f" <code>({last_err})</code>" if last_err else "")
            )
            missing += 1
            continue

        ver = (
            getattr(mod, "VERSION", None)
            or getattr(mod, "__version__", None)
            or getattr(mod, "_VERSION", None)
            or "?"
        )
        if ver == "?":
            doc = getattr(mod, "__doc__", "") or ""
            m = _re_mod.search(r"v?(\d+\.\d+\.\d+)", doc[:500])
            if m:
                ver = m.group(1)
        icon = "✅" if ver != "?" else "🟡"
        lines.append(f"{icon} <code>{name}</code>: v{ver}")
        loaded += 1

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"📊 محمّل: <b>{loaded}</b> | مفقود: <b>{missing}</b>")

    cache_stats = _get_cache_stats()
    lines.append(
        f"💾 cache: <b>{cache_stats['total_keys']}</b>"
        f"/{cache_stats['max_entries']}"
    )

    lines.append(
        "⚙️ autotune: " + (
            "🟢 متاح" if _AUTOTUNE_AVAILABLE else
            f"🔴 غير متاح "
            f"<i>(db_diagnostics="
            f"{_html_mod.escape(str(_DB_DIAG_VERSION_AT))})</i>"
        )
    )

    lines.append(f"🕐 <i>{TimeUtils.mecca_iso()[:19]}</i>")

    text = "\n".join(lines)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔄 تحديث",
            callback_data="versions_refresh",
        )],
        [InlineKeyboardButton(
            "📂 كل الملفات",
            callback_data="files_open",
        )],
        [InlineKeyboardButton(
            "💾 إبطال cache",
            callback_data="analytics_reset_cache",
        )],
        [InlineKeyboardButton(
            "🔙 رجوع",
            callback_data="admin",
        )],
    ])

    if query:
        await _safe_edit(query, text, kb)
    elif chat_id is not None:
        await safe_send(
            context.bot, chat_id, text,
            reply_markup=kb, parse_mode="HTML",
        )


# ═══════════════════════════════════════════════════════════════════════
# 15) /analytics_reset
# ═══════════════════════════════════════════════════════════════════════

async def cmd_analytics_reset(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = _get_safe_user_id(update)
    chat_id = _safe_get_chat_id(update, None)
    query = update.callback_query

    if query:
        await _quick_answer(query, "🗑️ جاري الإبطال...")

    if not _check_developer(user_id):
        await _reject_non_dev(context.bot, chat_id, query)
        return

    removed = _invalidate_analytics_cache()

    text = (
        f"✅ <b>تم إبطال cache التحليلات</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🗑️ محذوف: <b>{removed}</b> مفتاح\n"
        f"💾 حجم الحالي: <b>0</b>\n\n"
        f"<i>ستُقرأ البيانات من DB في الطلب التالي.</i>"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📊 التحليلات",
            callback_data="admin_analytics",
        )],
        [InlineKeyboardButton(
            "📦 الإصدارات",
            callback_data="versions_refresh",
        )],
    ])

    if query:
        await _safe_edit(query, text, kb)
    elif chat_id is not None:
        await safe_send(
            context.bot, chat_id, text,
            reply_markup=kb, parse_mode="HTML",
        )

    logger.info(
        "🗑️ analytics cache invalidated by user=%s (removed=%d)",
        user_id, removed,
    )


# ═══════════════════════════════════════════════════════════════════════
# 16) التوجيه المركزي
# ═══════════════════════════════════════════════════════════════════════

_ANALYTICS_HANDLERS = {
    "admin_analytics": show_analytics_menu,
    "growth_30d_btn": show_growth_30d,
    "top_channels_btn": show_top_channels,
    "publish_stats_btn": show_publish_stats,
    "channels_rate_btn": show_channels_rate,
    "subscriptions_btn": show_subscriptions,
    "pool_live_btn": show_pool_live,
    "slow_queries_btn": show_slow_queries,
    "export_excel_btn": export_excel,
    "full_health_btn": show_full_health,
    "latency_btn": show_latency,
    "databases_btn": show_databases,
    "autotune_btn": show_autotune,
    "files_btn": cmd_files,
    "audit_btn": cmd_audit,
}


async def handle_analytics_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if not query:
        return

    data = (query.data or "").split(":")[0]
    user_id = _get_safe_user_id(update)

    if data == "versions_refresh":
        await cmd_versions(update, context)
        return
    if data == "analytics_reset_cache":
        await cmd_analytics_reset(update, context)
        return
    if data in ("files_open", "files_refresh"):
        await cmd_files(update, context)
        return
    if data == "audit_md_btn":
        await _quick_answer(query, "⏳ جاري التصدير...")
        if user_id is not None:
            await _audit_send_markdown(update, context, user_id)
        return
    if data == "audit_json_btn":
        await _quick_answer(query, "⏳ جاري التصدير...")
        if user_id is not None:
            await _audit_send_json(update, context, user_id)
        return

    if data not in ANALYTICS_BUTTONS:
        return

    if data == "refresh_btn":
        last = context.user_data.get(
            "last_analytics_btn", "admin_analytics")
        data = last
        _invalidate_analytics_cache()
    else:
        context.user_data["last_analytics_btn"] = data

    handler = _ANALYTICS_HANDLERS.get(data)
    if handler is None:
        try:
            await query.answer("⚠️ غير مدعوم")
        except Exception:
            pass
        return

    try:
        await handler(update, context)
    except Exception as e:
        logger.error(
            "handle_analytics_callback[%s]: %s", data, e, exc_info=True)
        err_html = _err_detail(e)
        try:
            await _safe_edit(
                query,
                f"❌ <b>خطأ في {_html_mod.escape(data)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n{err_html}",
                _back_keyboard("admin_analytics"),
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════
# 17) /analytics + أوامر مباشرة
# ═══════════════════════════════════════════════════════════════════════

async def cmd_analytics(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """v1.3.2 CLEAN-2: نُفوّض التحقق الكامل إلى show_analytics_menu."""
    await show_analytics_menu(update, context)


async def cmd_fullhealth(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_full_health(update, context)


async def cmd_latency(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_latency(update, context)


async def cmd_databases(update: Update,
                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """🗂️ v1.3.1: أمر مباشر لقواعد البيانات."""
    await show_databases(update, context)


async def cmd_autotune(update: Update,
                       context: ContextTypes.DEFAULT_TYPE) -> None:
    """⚙️ v1.3.3: أمر مباشر لضبط autovacuum."""
    await show_autotune(update, context)


# ═══════════════════════════════════════════════════════════════════════
# 18) التسجيل
# ═══════════════════════════════════════════════════════════════════════

def register_handlers(application) -> bool:
    """
    v1.3.8: يُسجّل كل الـ handlers (buttons + commands).

    Returns:
        True إن نجح التسجيل، False إن فشل.
    """
    try:
        _safe_buttons = "|".join(
            _re_mod.escape(b) for b in ANALYTICS_BUTTONS
        )
        pattern = (
            r"^(?:" + _safe_buttons + r"|"
            r"versions_refresh|analytics_reset_cache|"
            r"files_open|files_refresh|"
            r"audit_md_btn|audit_json_btn"
            r")(?::\d+)?$"
        )
        application.add_handler(
            CallbackQueryHandler(
                handle_analytics_callback,
                pattern=pattern,
            )
        )
        application.add_handler(
            CommandHandler("analytics", cmd_analytics)
        )
        application.add_handler(
            CommandHandler("fullhealth", cmd_fullhealth)
        )
        application.add_handler(
            CommandHandler("latency", cmd_latency)
        )
        application.add_handler(
            CommandHandler("versions", cmd_versions)
        )
        application.add_handler(
            CommandHandler("analytics_reset", cmd_analytics_reset)
        )
        application.add_handler(
            CommandHandler("databases", cmd_databases)
        )
        application.add_handler(
            CommandHandler("autotune", cmd_autotune)
        )
        application.add_handler(
            CommandHandler("files", cmd_files)
        )
        application.add_handler(
            CommandHandler("audit", cmd_audit)
        )
        application.add_handler(
            CommandHandler("audit_full", cmd_audit_full)
        )
        application.add_handler(
            CommandHandler("audit_critical", cmd_audit_critical)
        )

        cmds = (
            "analytics, fullhealth, latency, versions, "
            "analytics_reset, databases, autotune, files, "
            "audit, audit_full, audit_critical"
        )
        logger.info(
            "✅ handlers_analytics v1.3.8: %d زر + 11 أمر (%s)",
            len(ANALYTICS_BUTTONS),
            cmds,
        )
        return True
    except Exception as e:
        logger.error(
            f"❌ handlers_analytics.register_handlers: "
            f"{type(e).__name__}: {e}",
            exc_info=True,
        )
        return False


register = register_handlers


__all__ = [
    "ANALYTICS_BUTTONS",
    "show_analytics_menu",
    "handle_analytics_callback",
    "show_growth_30d",
    "show_top_channels",
    "show_publish_stats",
    "show_channels_rate",
    "show_subscriptions",
    "show_pool_live",
    "show_slow_queries",
    "export_excel",
    "show_full_health",
    "show_latency",
    "show_databases",
    "show_autotune",
    "cmd_analytics",
    "cmd_fullhealth",
    "cmd_latency",
    "cmd_versions",
    "cmd_analytics_reset",
    "cmd_databases",
    "cmd_autotune",
    "cmd_files",
    "cmd_audit",
    "cmd_audit_full",
    "cmd_audit_critical",
    "register_handlers",
    "register",
    "_cached_db_call",
    "_invalidate_analytics_cache",
    "_get_cache_stats",
    "_quick_answer",
    "_find_project_root",
    "_file_to_module_path",
    "_extract_version",
    "_try_import_any",
    "_AuditFinding",
    "_AuditReport",
    "_audit_file_sync",
    "_audit_run_reports",
    "_audit_collect_files",
    "_audit_collect_files_sync",
    "_audit_summary_html",
    "_audit_to_markdown",
    "_cmd_files_scan_sync",
    "_get_audit_executor",
    "_AUDIT_EXECUTOR",
    "_AUDIT_EXECUTOR_MAX_WORKERS",
    "_AUDIT_SEMAPHORE_LIMIT",
]


# ═══════════════════════════════════════════════════════════════════════
# LOAD BEACON — v1.3.8
# ═══════════════════════════════════════════════════════════════════════

try:
    logger.info(
        "✅ handlers_analytics v1.3.8 loaded | "
        "buttons=%d | "
        "FIX-AUDIT-EXECUTOR=on(max_workers=%d,sem=%d) | "
        "FIX-COLLECT-FILES-SYNC=on | "
        "FIX-CMD-FILES-SYNC=on | "
        "FILES-SCAN-1=/files | "
        "FILES-SCAN-2=files_open+files_refresh | "
        "FILES-SCAN-3=files_btn | "
        "FILES-SCAN-4=_find_project_root | "
        "FILES-SCAN-5=_EXCLUDED_DIRS | "
        "FILES-SCAN-6=_file_to_module_path | "
        "FILES-SCAN-7=bot.py-special | "
        "FILES-SCAN-8=max_scan=%d | "
        "AUDIT-1=/audit+/audit_full+/audit_critical | "
        "AUDIT-2=AST+Patterns+PTB+BotSpecific | "
        "AUDIT-3=MD+JSON export | "
        "AUDIT-4=max_audit=%d,timeout=%.0fs | "
        "FIX-SQL-FP-1=no-DOTALL+no-%%s | "
        "FIX-EVAL-EXEC-FP-2=lookbehind+no-self-match | "
        "FIX-EXCEPT-PASS-3=AST-accurate | "
        "FIX-LOG-FSTRING-FP-4=single-line-only | "
        "FIX-SELF-SCAN-5=self-excluded | "
        "FIX-DECLARED-6=patterns-match-v5716 | "
        "FIX-VERSIONS-PATH=on | "
        "FIX-VERSIONS-ERR=on | "
        "AUTO-1..6=on | "
        "autotune_available=%s | "
        "db_diag_version=%s | "
        "CLEAN-1=regex-escape | "
        "CLEAN-2=cmd-analytics-no-double-check | "
        "INTEGRATION=bot.py-v5.7.16 | "
        "FIX-1=force-refresh-false | "
        "PERF-1=db-cache(ttl=%.0fs,max=%d) | "
        "PERF-2=quick-answer | "
        "FEAT-1=growth-comparison | "
        "FEAT-2=/versions | "
        "FEAT-3=/analytics_reset | "
        "KEPT: HA1..HA31",
        len(ANALYTICS_BUTTONS),
        _AUDIT_EXECUTOR_MAX_WORKERS,
        _AUDIT_SEMAPHORE_LIMIT,
        _MAX_FILES_SCAN,
        _MAX_AUDIT_FILES,
        _AUDIT_TIMEOUT_SEC,
        _AUTOTUNE_AVAILABLE,
        _DB_DIAG_VERSION_AT,
        _DB_CACHE_TTL_DEFAULT,
        _DB_CACHE_MAX_ENTRIES,
    )
except Exception:
    pass