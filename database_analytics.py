#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
database_analytics.py - دوال التحليلات المتقدمة (v1.0.1)
================================================================================
AnalyticsMixin:
  - get_user_growth          : نمو المستخدمين آخر N يوم
  - get_top_channels         : أفضل N قناة (نجاح + إنجاز)
  - get_publish_stats        : متوسط + نسبة النجاح + نسبة الإنجاز
  - get_channel_success_rate : نسبة نجاح كل قناة
  - get_subscription_rate    : اشتراكات شهرية
  - get_slow_queries         : أبطأ الاستعلامات
  - get_pool_live            : حالة Pool مباشرة
================================================================================
🆕 v1.0.1 — إصلاحات ما بعد التدقيق:
  ✅ get_top_channels: تمييز نسبة النجاح (published/(published+failed))
     عن نسبة الإنجاز (published/total) — كان يعرض الإنجاز باسم النجاح
  ✅ get_top_channels: حقول جديدة
     - attempted: عدد محاولات النشر (published + failed)
     - pending  : منشورات لم تُنشر بعد
     - completion_rate: نسبة الإنجاز
  ✅ get_publish_stats: نفس التمييز + حقول جديدة
  ✅ get_subscription_rate: إصلاح MySQL — strftime غير موجود!
     (MySQL يستخدم DATE_FORMAT، SQLite يستخدم strftime)
  ✅ get_pool_live: دعم asyncmy (maxsize/size/freesize)
================================================================================
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


# =====================================================================
# 🎯 ثوابت نسبة النجاح
# =====================================================================

# الافتراضي عندما لا توجد محاولات نشر بعد
DEFAULT_SUCCESS_RATE = 100.0

# حد "الفشل" — إذا تجاوز fail_count هذا العدد، يُعدّ المنشور فاشلاً
FAIL_COUNT_THRESHOLD = 3


def color_emoji(value: float, thresholds=(0.3, 0.7), inverse=False) -> str:
    """
    🎨 إرجاع إيموجي ملوّن حسب القيمة.
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


def _compute_channel_rates(
    total: int, published: int, failed: int
) -> Dict[str, Any]:
    """
    🎯 حساب نسب النجاح والإنجاز لقناة واحدة.

    - attempted       = published + failed     (محاولات النشر الفعلية)
    - pending         = total - attempted      (منشورات لم يُحاول نشرها بعد)
    - success_rate    = published / attempted  (نسبة النجاح الحقيقية)
    - completion_rate = published / total      (نسبة الإنجاز)
    """
    attempted = published + failed
    pending = max(0, total - attempted)

    success_rate = (
        round(published / attempted * 100, 1)
        if attempted > 0 else DEFAULT_SUCCESS_RATE
    )
    completion_rate = (
        round(published / total * 100, 1)
        if total > 0 else 0.0
    )

    return {
        'attempted': attempted,
        'pending': pending,
        'success_rate': success_rate,
        'completion_rate': completion_rate,
    }


class AnalyticsMixin:
    """Mixin للتحليلات المتقدمة"""

    # =================================================================
    # 1) نمو المستخدمين
    # =================================================================

    async def get_user_growth(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        📈 نمو المستخدمين آخر N يوم.
        Returns: [{date, count}, ...]

        DATE() متوفر في PostgreSQL و MySQL و SQLite.
        """
        try:
            days = max(1, min(int(days), 365))
            since = self.TimeUtils.utc_now() - timedelta(days=days)

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
    # 2) أفضل 10 قنوات (نجاح + إنجاز)
    # =================================================================

    async def get_top_channels(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        🏆 أفضل N قناة.

        ✅ v1.0.1: يُرجع مقياسين منفصلين:
          - success_rate    = published / (published + failed)
                              نسبة النجاح الحقيقية
          - completion_rate = published / total
                              نسبة الإنجاز من إجمالي المنشورات

        🔴 v1.0.0: كانت success_rate = published / total
                   (نسبة إنجاز مغلوطة باسم نسبة نجاح).
        """
        try:
            limit = max(1, min(int(limit), 50))
            query = f"""
                SELECT uc.id, uc.channel_name, uc.channel_id,
                       uc.user_id,
                       COUNT(p.id) AS total_posts,
                       SUM(CASE WHEN p.published = 1 THEN 1 ELSE 0 END)
                           AS published,
                       SUM(CASE WHEN p.published = 0
                                AND p.fail_count >= {FAIL_COUNT_THRESHOLD}
                                THEN 1 ELSE 0 END) AS failed
                FROM user_channels uc
                LEFT JOIN posts p ON p.channel_db_id = uc.id
                WHERE uc.banned = 0
                GROUP BY uc.id, uc.channel_name, uc.channel_id, uc.user_id
                ORDER BY published DESC, total_posts DESC
                LIMIT ?
            """
            # ? → $1 على PostgreSQL (auto via _convert_placeholders)
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
                    'user_id': rd.get('user_id'),
                    'total': total,
                    'published': published,
                    'failed': failed,
                    'attempted': rates['attempted'],
                    'pending': rates['pending'],
                    'success_rate': rates['success_rate'],
                    'completion_rate': rates['completion_rate'],
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
        📊 متوسط النشر + نسبة النجاح + نسبة الإنجاز.

        ✅ v1.0.1: يُرجع مقياسين منفصلين:
          - success_rate    = published / (published + failed)
          - completion_rate = published / total_posts

        🔴 v1.0.0: كانت success_rate = published / total_posts
                   (نسبة إنجاز مغلوطة باسم نسبة نجاح).
        """
        try:
            row = await self.fetchone(f"""
                SELECT
                    COUNT(DISTINCT uc.id) AS total_channels,
                    COUNT(p.id) AS total_posts,
                    SUM(CASE WHEN p.published = 1 THEN 1 ELSE 0 END)
                        AS published,
                    SUM(CASE WHEN p.published = 0
                             AND p.fail_count >= {FAIL_COUNT_THRESHOLD}
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

            rates = _compute_channel_rates(total_posts, published, failed)

            return {
                'total_channels': total_channels,
                'total_posts': total_posts,
                'published': published,
                'failed': failed,
                'attempted': rates['attempted'],
                'pending': rates['pending'],
                'avg_posts_per_channel': avg_posts,
                'avg_published_per_channel': avg_published,
                # ✅ نسبة النجاح الحقيقية (كانت نسبة إنجاز في v1.0.0)
                'success_rate': rates['success_rate'],
                # ✅ نسبة الإنجاز (حقل جديد)
                'completion_rate': rates['completion_rate'],
            }
        except Exception as e:
            logger.error(f"❌ get_publish_stats: {e}", exc_info=True)
            return {
                'total_channels': 0, 'total_posts': 0,
                'published': 0, 'failed': 0,
                'attempted': 0, 'pending': 0,
                'avg_posts_per_channel': 0,
                'avg_published_per_channel': 0,
                'success_rate': DEFAULT_SUCCESS_RATE,
                'completion_rate': 0.0,
            }

    # =================================================================
    # 5) معدل الاشتراكات
    # =================================================================

    async def get_subscription_rate(self, months: int = 6) -> List[Dict[str, Any]]:
        """
        💎 اشتراكات جديدة شهرياً.

        ✅ v1.0.1: إصلاح MySQL — كان يستخدم strftime الذي لا يوجد!
        - PostgreSQL: TO_CHAR
        - MySQL     : DATE_FORMAT
        - SQLite    : strftime
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
            elif getattr(self, "USE_MYSQL", False):
                # ✅ v1.0.1: MySQL يستخدم DATE_FORMAT لا strftime
                query = """
                    SELECT
                        DATE_FORMAT(created_at, '%%Y-%%m') AS month,
                        COUNT(*) AS cnt
                    FROM subscriptions
                    WHERE created_at >= %s
                    GROUP BY DATE_FORMAT(created_at, '%%Y-%%m')
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

        ✅ v1.0.1: دعم asyncmy (maxsize/size/freesize)
        بجانب asyncpg (get_max_size/get_size/get_idle_size).
        """
        if not (getattr(self, "USE_POSTGRES", False)
                or getattr(self, "USE_MYSQL", False)):
            return {"available": False, "type": "sqlite"}

        pool = getattr(self, "_pool", None)
        if pool is None:
            return {"available": False, "type": "none"}

        try:
            # asyncpg style (methods)
            max_size = pool.get_max_size() if hasattr(pool, 'get_max_size') else None
            current_size = pool.get_size() if hasattr(pool, 'get_size') else None
            idle_size = pool.get_idle_size() if hasattr(pool, 'get_idle_size') else None

            # ✅ v1.0.1: asyncmy style (properties)
            if max_size is None:
                max_size = getattr(pool, 'maxsize', None)
            if current_size is None:
                current_size = getattr(pool, 'size', None)
            if idle_size is None:
                idle_size = getattr(pool, 'freesize', None)

            if max_size is None or current_size is None:
                return {"available": False, "type": "unknown"}
            if idle_size is None:
                idle_size = 0

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


__all__ = ["AnalyticsMixin", "color_emoji"]