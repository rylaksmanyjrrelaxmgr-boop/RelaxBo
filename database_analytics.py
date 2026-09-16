#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_analytics.py - دوال التحليلات المتقدمة (v1.0.0)
================================================================================
AnalyticsMixin:
  - get_user_growth          : نمو المستخدمين آخر N يوم
  - get_top_channels         : أفضل N قناة
  - get_publish_stats        : متوسط + نسبة النجاح
  - get_channel_success_rate : نسبة نجاح كل قناة
  - get_subscription_rate    : اشتراكات شهرية
  - get_slow_queries         : أبطأ الاستعلامات
  - get_pool_live            : حالة Pool مباشرة
================================================================================
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


def color_emoji(value: float, thresholds=(0.3, 0.7), inverse=False) -> str:
    """
    🎨 v10: إرجاع إيموجي ملوّن حسب القيمة.
    thresholds = (red_below, yellow_below) → 🟢/🟡/🔴
    inverse=True للقلب (مثلاً: 0 = ممتاز)
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "⚪"

    low, high = thresholds
    if inverse:
        if v <= low:
            return "🟢"
        elif v <= high:
            return "🟡"
        else:
            return "🔴"
    else:
        if v >= high:
            return "🟢"
        elif v >= low:
            return "🟡"
        else:
            return "🔴"


class AnalyticsMixin:
    """Mixin للتحليلات المتقدمة"""

    # =================================================================
    # 1) نمو المستخدمين
    # =================================================================

    async def get_user_growth(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        📈 نمو المستخدمين آخر N يوم.
        Returns: [{date, count}, ...]
        """
        try:
            days = max(1, min(int(days), 365))
            since = self.TimeUtils.utc_now() - timedelta(days=days)

            if getattr(self, "USE_POSTGRES", False):
                query = """
                    SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                    FROM users
                    WHERE created_at >= $1
                    GROUP BY DATE(created_at)
                    ORDER BY day ASC
                """
                rows = await self.fetchall(query, (since,))
            else:
                query = """
                    SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                    FROM users
                    WHERE created_at >= ?
                    GROUP BY DATE(created_at)
                    ORDER BY day ASC
                """
                rows = await self.fetchall(query, (since,))

            result = []
            for r in (rows or []):
                rd = r if isinstance(r, dict) else dict(r)
                day = rd.get('day')
                cnt = rd.get('cnt', 0)
                if day is None:
                    continue
                result.append({
                    'date': str(day)[:10],
                    'count': int(cnt or 0),
                })
            return result
        except Exception as e:
            logger.error(f"❌ get_user_growth: {e}", exc_info=True)
            return []

    # =================================================================
    # 2) أفضل 10 قنوات
    # =================================================================

    async def get_top_channels(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        🏆 أفضل N قناة بعدد المنشورات المنشورة.
        """
        try:
            limit = max(1, min(int(limit), 50))
            query = """
                SELECT uc.id, uc.channel_name, uc.channel_id,
                       uc.user_id,
                       COUNT(p.id) AS total_posts,
                       SUM(CASE WHEN p.published = 1 THEN 1 ELSE 0 END) AS published,
                       SUM(CASE WHEN p.published = 0 AND p.fail_count >= 3
                                THEN 1 ELSE 0 END) AS failed
                FROM user_channels uc
                LEFT JOIN posts p ON p.channel_db_id = uc.id
                WHERE uc.banned = 0
                GROUP BY uc.id, uc.channel_name, uc.channel_id, uc.user_id
                ORDER BY published DESC, total_posts DESC
                LIMIT ?
            """
            # PostgreSQL: LIMIT $1
            if getattr(self, "USE_POSTGRES", False):
                query = query.replace("LIMIT ?", "LIMIT $1")
            rows = await self.fetchall(query, (limit,))

            result = []
            for r in (rows or []):
                rd = r if isinstance(r, dict) else dict(r)
                total = int(rd.get('total_posts', 0) or 0)
                published = int(rd.get('published', 0) or 0)
                failed = int(rd.get('failed', 0) or 0)
                success_rate = (published / total * 100) if total > 0 else 0
                result.append({
                    'name': rd.get('channel_name') or f"قناة {rd.get('id')}",
                    'channel_id': rd.get('channel_id'),
                    'user_id': rd.get('user_id'),
                    'total': total,
                    'published': published,
                    'failed': failed,
                    'success_rate': round(success_rate, 1),
                })
            return result
        except Exception as e:
            logger.error(f"❌ get_top_channels: {e}", exc_info=True)
            return []

    # =================================================================
    # 3) متوسط النشر + 4) نسبة النجاح العامة
    # =================================================================

    async def get_publish_stats(self) -> Dict[str, Any]:
        """
        📊 متوسط النشر + نسبة النجاح العامة.
        """
        try:
            row = await self.fetchone("""
                SELECT
                    COUNT(DISTINCT uc.id) AS total_channels,
                    COUNT(p.id) AS total_posts,
                    SUM(CASE WHEN p.published = 1 THEN 1 ELSE 0 END)
                        AS published,
                    SUM(CASE WHEN p.published = 0 AND p.fail_count >= 3
                             THEN 1 ELSE 0 END) AS failed
                FROM user_channels uc
                LEFT JOIN posts p ON p.channel_db_id = uc.id
                WHERE uc.banned = 0
            """) or {}

            rd = row if isinstance(row, dict) else dict(row)
            total_channels = int(rd.get('total_channels', 0) or 0)
            total_posts = int(rd.get('total_posts', 0) or 0)
            published = int(rd.get('published', 0) or 0)
            failed = int(rd.get('failed', 0) or 0)

            avg_posts = (
                round(total_posts / total_channels, 1)
                if total_channels > 0 else 0
            )
            avg_published = (
                round(published / total_channels, 1)
                if total_channels > 0 else 0
            )
            success_rate = (
                round(published / total_posts * 100, 1)
                if total_posts > 0 else 0
            )

            return {
                'total_channels': total_channels,
                'total_posts': total_posts,
                'published': published,
                'failed': failed,
                'avg_posts_per_channel': avg_posts,
                'avg_published_per_channel': avg_published,
                'success_rate': success_rate,
            }
        except Exception as e:
            logger.error(f"❌ get_publish_stats: {e}", exc_info=True)
            return {
                'total_channels': 0, 'total_posts': 0,
                'published': 0, 'failed': 0,
                'avg_posts_per_channel': 0,
                'avg_published_per_channel': 0,
                'success_rate': 0,
            }

    # =================================================================
    # 5) معدل الاشتراكات
    # =================================================================

    async def get_subscription_rate(self, months: int = 6) -> List[Dict[str, Any]]:
        """
        💎 اشتراكات جديدة/ملغاة شهرياً.
        """
        try:
            months = max(1, min(int(months), 24))
            since = self.TimeUtils.utc_now() - timedelta(days=months * 31)

            if getattr(self, "USE_POSTGRES", False):
                query = """
                    SELECT
                        TO_CHAR(created_at, 'YYYY-MM') AS month,
                        COUNT(*) AS cnt
                    FROM subscriptions
                    WHERE created_at >= $1
                    GROUP BY TO_CHAR(created_at, 'YYYY-MM')
                    ORDER BY month ASC
                """
            else:
                query = """
                    SELECT
                        strftime('%Y-%m', created_at) AS month,
                        COUNT(*) AS cnt
                    FROM subscriptions
                    WHERE created_at >= ?
                    GROUP BY strftime('%Y-%m', created_at)
                    ORDER BY month ASC
                """
            rows = await self.fetchall(query, (since,))

            result = []
            for r in (rows or []):
                rd = r if isinstance(r, dict) else dict(r)
                month = rd.get('month')
                cnt = rd.get('cnt', 0)
                if month is None:
                    continue
                result.append({
                    'month': str(month),
                    'count': int(cnt or 0),
                })
            return result
        except Exception as e:
            logger.error(f"❌ get_subscription_rate: {e}", exc_info=True)
            return []

    # =================================================================
    # 6) Pool مباشر
    # =================================================================

    async def get_pool_live(self) -> Dict[str, Any]:
        """
        🚀 حالة Pool مباشرة (PostgreSQL/MySQL).
        """
        if not (getattr(self, "USE_POSTGRES", False)
                or getattr(self, "USE_MYSQL", False)):
            return {"available": False, "type": "sqlite"}

        pool = getattr(self, "_pool", None)
        if pool is None:
            return {"available": False, "type": "none"}

        try:
            max_size = pool.get_max_size() if hasattr(pool, 'get_max_size') else 0
            current_size = pool.get_size() if hasattr(pool, 'get_size') else 0
            idle_size = pool.get_idle_size() if hasattr(pool, 'get_idle_size') else 0
            in_use = max(0, current_size - idle_size)
            util = (in_use / max_size * 100) if max_size > 0 else 0.0

            return {
                "available": True,
                "type": "postgres" if getattr(self, "USE_POSTGRES", False) else "mysql",
                "max_size": max_size,
                "current_size": current_size,
                "idle_size": idle_size,
                "in_use": in_use,
                "utilization_pct": round(util, 1),
            }
        except Exception as e:
            logger.warning(f"⚠️ get_pool_live: {e}")
            return {"available": False, "type": "error", "error": str(e)}

    # =================================================================
    # 7) الاستعلامات البطيئة
    # =================================================================

    async def get_slow_queries(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        🐌 قائمة أبطأ الاستعلامات (من الذاكرة).
        """
        try:
            limit = max(1, min(int(limit), 100))
            log = getattr(self, "_slow_queries_log", None)
            if not log:
                return []
            lock = getattr(self, "_slow_queries_lock", None)
            if lock is not None:
                async with lock:
                    snapshot = list(log)
            else:
                snapshot = list(log)
            snapshot.sort(key=lambda x: x.get('elapsed', 0), reverse=True)
            return snapshot[:limit]
        except Exception as e:
            logger.warning(f"⚠️ get_slow_queries: {e}")
            return []