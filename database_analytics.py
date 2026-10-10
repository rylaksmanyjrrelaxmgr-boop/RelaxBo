#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_analytics.py - دوال التحليلات المتقدمة (v1.1.0)
================================================================================
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


DEFAULT_SUCCESS_RATE = 100.0
FAIL_COUNT_THRESHOLD = 3
DEAD_TUPLE_THRESHOLDS = (0.05, 0.10, 0.20)
DEAD_TUPLE_MIN_LIVE = 1000
TABLE_SIZE_WARN_KB = 5 * 1024
TABLE_SIZE_CRITICAL_KB = 50 * 1024
ADMIN_LOGS_WARN_COUNT = 5000
BANNED_WORDS_WARN_COUNT = 500
IDLE_TX_WARN_COUNT = 1
IDLE_TX_CRIT_COUNT = 3


def color_emoji(value: float, thresholds=(0.3, 0.7), inverse=False) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "⚪"
    low, high = thresholds
    if inverse:
        if v <= low: return "🟢"
        if v <= high: return "🟡"
        return "🔴"
    else:
        if v >= high: return "🟢"
        if v >= low: return "🟡"
        return "🔴"


def _dead_tuple_color(dead: int, live: int) -> str:
    total = live + dead
    if total == 0: return "⚪"
    ratio = dead / total
    if live < DEAD_TUPLE_MIN_LIVE and ratio < 0.20: return "🟢"
    low, mid, high = DEAD_TUPLE_THRESHOLDS
    if ratio < low: return "🟢"
    if ratio < mid: return "🟡"
    if ratio < high: return "🟠"
    return "🔴"


def _dead_tuple_advice(dead: int, live: int, table: str) -> str:
    total = live + dead
    if total == 0: return ""
    ratio = dead / total
    if live < DEAD_TUPLE_MIN_LIVE and ratio < 0.20: return ""
    if ratio < 0.05: return ""
    if ratio < 0.10: return f"💡 راقب {table}"
    if ratio < 0.20: return f"⚠️ VACUUM ANALYZE {table}"
    return f"🔴 VACUUM FULL {table} عاجل"


def _idle_tx_color(count: int) -> str:
    if count >= IDLE_TX_CRIT_COUNT: return "🔴"
    if count >= IDLE_TX_WARN_COUNT: return "🟠"
    return "🟢"


def _format_bytes(num_bytes) -> str:
    try:
        b = float(num_bytes or 0)
    except (TypeError, ValueError):
        return "0 B"
    if b < 1024: return f"{int(b)} B"
    if b < 1024 * 1024: return f"{b / 1024:.1f} KB"
    if b < 1024 * 1024 * 1024: return f"{b / (1024 * 1024):.2f} MB"
    return f"{b / (1024 * 1024 * 1024):.2f} GB"


def _compute_channel_rates(total: int, published: int, failed: int) -> Dict[str, Any]:
    attempted = published + failed
    pending = max(0, total - attempted)
    success_rate = round(published / attempted * 100, 1) if attempted > 0 else DEFAULT_SUCCESS_RATE
    completion_rate = round(published / total * 100, 1) if total > 0 else 0.0
    return {'attempted': attempted, 'pending': pending,
            'success_rate': success_rate, 'completion_rate': completion_rate}


class AnalyticsMixin:

    async def get_user_growth(self, days: int = 30) -> List[Dict[str, Any]]:
        try:
            days = max(1, min(int(days), 365))
            since = self.TimeUtils.utc_now() - timedelta(days=days)
            if getattr(self, "USE_POSTGRES", False):
                query = """SELECT created_at::date AS day, COUNT(*) AS cnt
                    FROM users WHERE created_at >= $1
                    GROUP BY created_at::date ORDER BY day ASC"""
            else:
                query = """SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                    FROM users WHERE created_at >= ?
                    GROUP BY DATE(created_at) ORDER BY day ASC"""
            rows = await self.fetchall(query, (since,))
            result = []
            for r in (rows or []):
                rd = r if isinstance(r, dict) else dict(r)
                day = rd.get('day')
                cnt = rd.get('cnt', 0)
                if day is None: continue
                result.append({'date': str(day)[:10], 'count': int(cnt or 0)})
            return result
        except Exception as e:
            logger.error(f"❌ get_user_growth: {e}", exc_info=True)
            return []

    async def get_top_channels(self, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            limit = max(1, min(int(limit), 50))
            query = f"""SELECT uc.id, uc.channel_name, uc.channel_id, uc.user_id,
                COUNT(p.id) AS total_posts,
                SUM(CASE WHEN p.published = 1 THEN 1 ELSE 0 END) AS published,
                SUM(CASE WHEN p.published = 0 AND p.fail_count >= {FAIL_COUNT_THRESHOLD}
                    THEN 1 ELSE 0 END) AS failed
                FROM user_channels uc
                LEFT JOIN posts p ON p.channel_db_id = uc.id
                WHERE uc.banned = 0
                GROUP BY uc.id, uc.channel_name, uc.channel_id, uc.user_id
                ORDER BY published DESC, total_posts DESC LIMIT ?"""
            rows = await self.fetchall(query, (limit,))
            result = []
            for r in (rows or []):
                rd = r if isinstance(r, dict) else dict(r)
                total = int(rd.get('total_posts', 0) or 0)
                published = int(rd.get('published', 0) or 0)
                failed = int(rd.get('failed', 0) or 0)
                rates = _compute_channel_rates(total, published, failed)
                result.append({
                    'name': rd.get('channel_name') or f"قناة {rd.get('id')}",
                    'channel_id': rd.get('channel_id'),
                    'user_id': rd.get('user_id'), 'total': total,
                    'published': published, 'failed': failed,
                    'attempted': rates['attempted'], 'pending': rates['pending'],
                    'success_rate': rates['success_rate'],
                    'completion_rate': rates['completion_rate']})
            return result
        except Exception as e:
            logger.error(f"❌ get_top_channels: {e}", exc_info=True)
            return []

    async def get_channel_success_rate(self, limit: int = 20, filter_min_attempts: int = 0) -> List[Dict[str, Any]]:
        channels = await self.get_top_channels(limit)
        if filter_min_attempts > 0:
            min_att = max(0, int(filter_min_attempts))
            channels = [c for c in channels if c.get('attempted', 0) >= min_att]
        return channels

    async def get_publish_stats(self) -> Dict[str, Any]:
        try:
            row = await self.fetchone(f"""SELECT
                COUNT(DISTINCT uc.id) AS total_channels,
                COUNT(p.id) AS total_posts,
                SUM(CASE WHEN p.published = 1 THEN 1 ELSE 0 END) AS published,
                SUM(CASE WHEN p.published = 0 AND p.fail_count >= {FAIL_COUNT_THRESHOLD}
                    THEN 1 ELSE 0 END) AS failed
                FROM user_channels uc
                LEFT JOIN posts p ON p.channel_db_id = uc.id
                WHERE uc.banned = 0""") or {}
            rd = row if isinstance(row, dict) else dict(row)
            total_channels = int(rd.get('total_channels', 0) or 0)
            total_posts = int(rd.get('total_posts', 0) or 0)
            published = int(rd.get('published', 0) or 0)
            failed = int(rd.get('failed', 0) or 0)
            avg_posts = round(total_posts / total_channels, 1) if total_channels > 0 else 0
            avg_published = round(published / total_channels, 1) if total_channels > 0 else 0
            rates = _compute_channel_rates(total_posts, published, failed)
            return {'total_channels': total_channels, 'total_posts': total_posts,
                    'published': published, 'failed': failed,
                    'attempted': rates['attempted'], 'pending': rates['pending'],
                    'avg_posts_per_channel': avg_posts,
                    'avg_published_per_channel': avg_published,
                    'success_rate': rates['success_rate'],
                    'completion_rate': rates['completion_rate']}
        except Exception as e:
            logger.error(f"❌ get_publish_stats: {e}", exc_info=True)
            return {'total_channels': 0, 'total_posts': 0, 'published': 0,
                    'failed': 0, 'attempted': 0, 'pending': 0,
                    'avg_posts_per_channel': 0, 'avg_published_per_channel': 0,
                    'success_rate': DEFAULT_SUCCESS_RATE, 'completion_rate': 0.0}

    async def get_subscription_rate(self, months: int = 6) -> List[Dict[str, Any]]:
        try:
            months = max(1, min(int(months), 24))
            since = self.TimeUtils.utc_now() - timedelta(days=months * 31)
            if getattr(self, "USE_POSTGRES", False):
                query = """SELECT TO_CHAR(created_at, 'YYYY-MM') AS month,
                    COUNT(*) AS cnt FROM subscriptions WHERE created_at >= $1
                    GROUP BY TO_CHAR(created_at, 'YYYY-MM') ORDER BY month ASC"""
            elif getattr(self, "USE_MYSQL", False):
                query = """SELECT DATE_FORMAT(created_at, '%%Y-%%m') AS month,
                    COUNT(*) AS cnt FROM subscriptions WHERE created_at >= %s
                    GROUP BY DATE_FORMAT(created_at, '%%Y-%%m') ORDER BY month ASC"""
            else:
                query = """SELECT strftime('%Y-%m', created_at) AS month,
                    COUNT(*) AS cnt FROM subscriptions WHERE created_at >= ?
                    GROUP BY strftime('%Y-%m', created_at) ORDER BY month ASC"""
            rows = await self.fetchall(query, (since,))
            result = []
            for r in (rows or []):
                rd = r if isinstance(r, dict) else dict(r)
                month = rd.get('month')
                cnt = rd.get('cnt', 0)
                if month is None: continue
                result.append({'month': str(month), 'count': int(cnt or 0)})
            return result
        except Exception as e:
            logger.error(f"❌ get_subscription_rate: {e}", exc_info=True)
            return []

    async def get_pool_live(self) -> Dict[str, Any]:
        if not (getattr(self, "USE_POSTGRES", False) or getattr(self, "USE_MYSQL", False)):
            return {"available": False, "type": "sqlite"}
        pool = getattr(self, "_pool", None)
        if pool is None: return {"available": False, "type": "none"}
        try:
            max_size = pool.get_max_size() if hasattr(pool, 'get_max_size') else None
            current_size = pool.get_size() if hasattr(pool, 'get_size') else None
            idle_size = pool.get_idle_size() if hasattr(pool, 'get_idle_size') else None
            if max_size is None: max_size = getattr(pool, 'maxsize', None)
            if current_size is None: current_size = getattr(pool, 'size', None)
            if idle_size is None: idle_size = getattr(pool, 'freesize', None)
            if max_size is None or current_size is None:
                return {"available": False, "type": "unknown"}
            if idle_size is None: idle_size = 0
            in_use = max(0, current_size - idle_size)
            util = (in_use / max_size * 100) if max_size > 0 else 0.0
            result = {"available": True,
                    "type": "postgres" if getattr(self, "USE_POSTGRES", False) else "mysql",
                    "max_size": max_size, "current_size": current_size,
                    "idle_size": idle_size, "in_use": in_use,
                    "utilization_pct": round(util, 1)}
            if getattr(self, "USE_POSTGRES", False):
                try:
                    from database import PG_ROLLBACK_ON_RETURN_TIMEOUT
                    result["rollback_timeout"] = PG_ROLLBACK_ON_RETURN_TIMEOUT
                except Exception: pass
                audit_task = getattr(self, "_idle_tx_audit_task", None)
                result["idle_tx_audit_active"] = (audit_task is not None and not audit_task.done())
                last_count = getattr(self, "_idle_tx_audit_last_count", None)
                if last_count is not None: result["idle_tx_last_count"] = int(last_count)
            return result
        except Exception as e:
            logger.warning(f"⚠️ get_pool_live: {e}")
            return {"available": False, "type": "error", "error": str(e)}

    async def get_slow_queries(self, limit: int = 20) -> List[Dict[str, Any]]:
        return await self.get_slowest_queries(limit)

    async def get_slowest_queries(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            limit = max(1, min(int(limit), 100))
            log = getattr(self, "_slow_queries_log", None)
            if not log: return []
            lock = getattr(self, "_slow_queries_lock", None)
            if lock is not None:
                async with lock: snapshot = list(log)
            else: snapshot = list(log)
            snapshot.sort(key=lambda x: x.get('elapsed', 0), reverse=True)
            return snapshot[:limit]
        except Exception as e:
            logger.warning(f"⚠️ get_slowest_queries: {e}")
            return []

    async def get_idle_tx_info(self, min_seconds=None, app_filter=None, limit=None) -> Dict[str, Any]:
        if not getattr(self, "USE_POSTGRES", False):
            return {"available": False, "reason": "not_postgres"}
        audit_fn = getattr(self, "audit_idle_in_transactions", None)
        if audit_fn is None:
            return {"available": False, "reason": "requires_database_v7.7.62+"}
        try:
            kwargs = {}
            if min_seconds is not None: kwargs["min_seconds"] = min_seconds
            if app_filter is not None: kwargs["app_filter"] = app_filter
            if limit is not None: kwargs["limit"] = limit
            report = await audit_fn(**kwargs)
            if not isinstance(report, dict):
                return {"available": False, "reason": "invalid_report_type"}
            return {"available": True, **report}
        except Exception as e:
            logger.warning(f"⚠️ get_idle_tx_info: {e}")
            return {"available": False, "reason": "call_failed", "error": str(e)}

    async def get_idle_tx_status_info(self) -> Dict[str, Any]:
        if not getattr(self, "USE_POSTGRES", False):
            return {"available": False, "reason": "not_postgres"}
        status_fn = getattr(self, "get_idle_tx_audit_status", None)
        if status_fn is None:
            return {"available": False, "reason": "requires_database_v7.7.62+"}
        try:
            status = await status_fn()
            if not isinstance(status, dict):
                return {"available": False, "reason": "invalid_status_type"}
            return {"available": True, **status}
        except Exception as e:
            logger.warning(f"⚠️ get_idle_tx_status_info: {e}")
            return {"available": False, "reason": "call_failed", "error": str(e)}

    async def get_dead_tuples(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not getattr(self, "USE_POSTGRES", False): return []
        try:
            limit = max(1, min(int(limit), 100))
            rows = await self.fetchall("""SELECT relname AS table_name,
                n_live_tup AS live_tuples, n_dead_tup AS dead_tuples,
                n_mod_since_analyze, last_vacuum, last_autovacuum,
                last_analyze, last_autoanalyze
                FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT $1""", (limit,))
            result = []
            for r in (rows or []):
                rd = r if isinstance(r, dict) else dict(r)
                name = rd.get('table_name') or '?'
                live = int(rd.get('live_tuples', 0) or 0)
                dead = int(rd.get('dead_tuples', 0) or 0)
                total = live + dead
                ratio = (dead / total) if total > 0 else 0.0
                try: n_mod = int(rd.get('n_mod_since_analyze', 0) or 0)
                except (TypeError, ValueError): n_mod = 0
                result.append({'name': name, 'live': live, 'dead': dead,
                    'total': total, 'dead_ratio': round(ratio, 4),
                    'color': _dead_tuple_color(dead, live),
                    'advice': _dead_tuple_advice(dead, live, name),
                    'n_mod_since_analyze': n_mod,
                    'last_vacuum': rd.get('last_vacuum'),
                    'last_autovacuum': rd.get('last_autovacuum'),
                    'last_analyze': rd.get('last_analyze'),
                    'last_autoanalyze': rd.get('last_autoanalyze')})
            return result
        except Exception as e:
            logger.error(f"❌ get_dead_tuples: {e}", exc_info=True)
            return []

    async def get_table_sizes(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not getattr(self, "USE_POSTGRES", False): return []
        try:
            limit = max(1, min(int(limit), 100))
            rows = await self.fetchall("""SELECT relname AS table_name,
                pg_total_relation_size(relid) AS total_bytes,
                pg_relation_size(relid) AS table_bytes,
                pg_indexes_size(relid) AS index_bytes
                FROM pg_stat_user_tables
                ORDER BY pg_total_relation_size(relid) DESC LIMIT $1""", (limit,))
            result = []
            for r in (rows or []):
                rd = r if isinstance(r, dict) else dict(r)
                total_bytes = int(rd.get('total_bytes', 0) or 0)
                total_kb = total_bytes / 1024
                if total_kb >= TABLE_SIZE_CRITICAL_KB: size_color = "🔴"
                elif total_kb >= TABLE_SIZE_WARN_KB: size_color = "🟡"
                else: size_color = "🟢"
                result.append({'name': rd.get('table_name') or '?',
                    'total_bytes': total_bytes,
                    'table_bytes': int(rd.get('table_bytes', 0) or 0),
                    'index_bytes': int(rd.get('index_bytes', 0) or 0),
                    'total_display': _format_bytes(total_bytes),
                    'size_color': size_color})
            return result
        except Exception as e:
            logger.error(f"❌ get_table_sizes: {e}", exc_info=True)
            return []

    async def get_indexes_info(self, tables=None) -> Dict[str, List[Dict[str, Any]]]:
        if not getattr(self, "USE_POSTGRES", False): return {}
        try:
            if tables:
                placeholders = ",".join(f"${i+1}" for i in range(len(tables)))
                query = f"""SELECT t.relname AS table_name, i.relname AS index_name,
                    pg_relation_size(i.oid) AS index_bytes,
                    idx.indisunique AS is_unique, idx.indisprimary AS is_primary
                    FROM pg_index idx JOIN pg_class i ON i.oid = idx.indexrelid
                    JOIN pg_class t ON t.oid = idx.indrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = 'public' AND t.relname IN ({placeholders})
                    ORDER BY t.relname, i.relname"""
                rows = await self.fetchall(query, tuple(tables))
            else:
                rows = await self.fetchall("""SELECT t.relname AS table_name,
                    i.relname AS index_name, pg_relation_size(i.oid) AS index_bytes,
                    idx.indisunique AS is_unique, idx.indisprimary AS is_primary
                    FROM pg_index idx JOIN pg_class i ON i.oid = idx.indexrelid
                    JOIN pg_class t ON t.oid = idx.indrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = 'public'
                    ORDER BY t.relname, i.relname""")
            result = {}
            for r in (rows or []):
                rd = r if isinstance(r, dict) else dict(r)
                tname = rd.get('table_name') or '?'
                ibytes = int(rd.get('index_bytes', 0) or 0)
                result.setdefault(tname, []).append({
                    'index_name': rd.get('index_name') or '?',
                    'is_unique': bool(rd.get('is_unique')),
                    'is_primary': bool(rd.get('is_primary')),
                    'size_bytes': ibytes,
                    'size_display': _format_bytes(ibytes)})
            return result
        except Exception as e:
            logger.error(f"❌ get_indexes_info: {e}", exc_info=True)
            return {}

    async def get_autovacuum_settings(self) -> Dict[str, Any]:
        if not getattr(self, "USE_POSTGRES", False): return {}
        try:
            rows = await self.fetchall("""SELECT name, setting, unit
                FROM pg_settings WHERE name IN ('autovacuum','autovacuum_naptime',
                'autovacuum_vacuum_scale_factor','autovacuum_analyze_scale_factor',
                'autovacuum_vacuum_threshold','autovacuum_analyze_threshold',
                'autovacuum_max_workers')""")
            result = {}
            for r in (rows or []):
                rd = r if isinstance(r, dict) else dict(r)
                name = rd.get('name')
                setting = rd.get('setting')
                unit = rd.get('unit') or ''
                if name:
                    result[name] = f"{setting}{unit}" if unit else str(setting)
            return result
        except Exception as e:
            logger.error(f"❌ get_autovacuum_settings: {e}", exc_info=True)
            return {}

    async def get_maintenance_recommendations(self, dead_tables=None, table_sizes=None, idle_tx_info=None) -> List[str]:
        recs: List[str] = []
        if not getattr(self, "USE_POSTGRES", False): return recs
        try:
            if idle_tx_info is None: idle_tx_info = await self.get_idle_tx_info()
            if idle_tx_info.get("available"):
                count = int(idle_tx_info.get("count") or 0)
                if count >= IDLE_TX_WARN_COUNT:
                    app_matches = int(idle_tx_info.get("app_matches") or 0)
                    color = _idle_tx_color(count)
                    detail = ""
                    if app_matches > 0:
                        detail = f"\n🚨 <b>{app_matches}</b> من تطبيقنا"
                    recs.append(f"{color} <b>idle-in-transaction:</b> <b>{count}</b> اتصال{detail}")
        except Exception: pass
        try:
            admin_count = await self.fetchval("SELECT COUNT(*) FROM admin_logs", default=0) or 0
            if int(admin_count) > ADMIN_LOGS_WARN_COUNT:
                recs.append(f"🟠 <b>admin_logs</b> = {admin_count} سجل")
        except Exception: pass
        try:
            bw_count = await self.fetchval("SELECT COUNT(*) FROM banned_words", default=0) or 0
            if int(bw_count) > BANNED_WORDS_WARN_COUNT:
                recs.append(f"🟡 <b>banned_words</b> = {bw_count} كلمة")
        except Exception: pass
        try:
            if dead_tables is None: dead_tables = await self.get_dead_tuples(20)
            for t in dead_tables:
                if t.get('dead_ratio', 0) >= 0.10:
                    recs.append(f"🟠 <b>{t['name']}</b> — dead={t['dead']} ({t['dead_ratio'] * 100:.1f}%)")
        except Exception: pass
        if not recs:
            recs.append("✅ لا توجد توصيات — قاعدة البيانات في حالة ممتازة")
        return recs

    async def get_db_diagnostics(self, top_n: int = 10) -> Dict[str, Any]:
        result = {'available': False, 'db_type': 'sqlite',
                'dead_tuples': [], 'table_sizes': [], 'indexes': {},
                'autovacuum': {}, 'idle_tx': {}, 'idle_tx_status': {},
                'recommendations': [], 'summary': {}}
        if not getattr(self, "USE_POSTGRES", False): return result
        result['available'] = True
        result['db_type'] = 'postgres'
        try: result['dead_tuples'] = await self.get_dead_tuples(top_n)
        except Exception: pass
        try: result['table_sizes'] = await self.get_table_sizes(top_n)
        except Exception: pass
        try:
            active_tables = [t['name'] for t in result['table_sizes'][:8]]
            result['indexes'] = await self.get_indexes_info(active_tables)
        except Exception: pass
        try: result['autovacuum'] = await self.get_autovacuum_settings()
        except Exception: pass
        try: result['idle_tx'] = await self.get_idle_tx_info()
        except Exception: result['idle_tx'] = {"available": False}
        try: result['idle_tx_status'] = await self.get_idle_tx_status_info()
        except Exception: result['idle_tx_status'] = {"available": False}
        try:
            result['recommendations'] = await self.get_maintenance_recommendations(
                dead_tables=result['dead_tuples'],
                table_sizes=result['table_sizes'],
                idle_tx_info=result['idle_tx'])
        except Exception: pass
        try:
            dead_total = sum(t.get('dead', 0) for t in result['dead_tuples'])
            live_total = sum(t.get('live', 0) for t in result['dead_tuples'])
            overall_color = "🟢"
            if live_total > 0:
                g = dead_total / (live_total + dead_total)
                if g >= 0.20: overall_color = "🔴"
                elif g >= 0.10: overall_color = "🟠"
                elif g >= 0.05: overall_color = "🟡"
            idle_count = 0
            idle_color = "🟢"
            if result['idle_tx'].get("available"):
                idle_count = int(result['idle_tx'].get("count") or 0)
                idle_color = _idle_tx_color(idle_count)
            result['summary'] = {'dead_total': dead_total, 'live_total': live_total,
                'overall_color': overall_color,
                'tables_count': len(result['dead_tuples']),
                'idle_tx_count': idle_count, 'idle_tx_color': idle_color}
        except Exception: pass
        return result


__all__ = [
    "AnalyticsMixin", "color_emoji", "DEFAULT_SUCCESS_RATE",
    "FAIL_COUNT_THRESHOLD", "DEAD_TUPLE_THRESHOLDS",
    "DEAD_TUPLE_MIN_LIVE", "TABLE_SIZE_WARN_KB",
    "TABLE_SIZE_CRITICAL_KB", "ADMIN_LOGS_WARN_COUNT",
    "BANNED_WORDS_WARN_COUNT", "IDLE_TX_WARN_COUNT", "IDLE_TX_CRIT_COUNT",
]