#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
database_tables.py — إنشاء الجداول والفهارس لكل قواعد البيانات (v7.6.22)
================================================================================
🚀 v7.6.22 (CONTEST-QUIZ-COLUMNS):
  ✅ CURRENT_SCHEMA_VERSION: 20 → 21
       - السبب: إضافة أعمدة لجدول contests لمسابقات quiz:
            • contest_type   (كان موجوداً، نُبقيه للتوافق)
            • question       (جديد — لمسابقات quiz)
            • correct_answer (جديد — لمسابقات quiz)
       - الإصلاح: migration تلقائي يُضيف الأعمدة للقواعد القديمة
       - المتوقع: مسابقات quiz تعمل بعد إعادة التشغيل

🚀 v7.6.21 (FORCE-BOOTSTRAP-RERUN — إصلاح جذري)
🚀 v7.6.20 (FORCE-DEPRECATED-INDEX-DROP + ADMIN_LOGS-MAX-ROWS)
🚀 v7.6.19 (AUTOVACUUM-COVERAGE-FIX)
🚀 v7.6.18 (DIAGNOSIS-FIXES)
🚀 v7.6.17 (SCHEMA-AWARE-INDEX-CHECK + MIGRATION-FIX)
🚀 v7.6.16 (REMOVE-REDUNDANT-POSTS-INDEXES)
🚀 v7.6.15 (SLOW-QUERY-FIX)
🚀 v7.6.14 (ADVANCED-INDEXES-PER-DB)
🚀 v7.6.13 (FASTPATH-INDEX-RECOVERY + QUICK-ANALYZE)
🚀 v7.6.12 (VACUUM + SLOW-QUERY-FIX)
🚀 v7.6.11 (MISSING-TABLES-MIGRATION)
🚀 v7.6.10 (AUTO-CLEANUP-STALE-LINKS)
🚀 v7.6.9  (SLOW-QUERY-INDEX-FIX)
🚀 v7.6.8  (CURSOR-CLEANUP)
🚀 v7.6.7  (BANNED-WORDS-INDEX-FIX)
================================================================================
"""

import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta

# =====================================================================
# 0. ثوابت
# =====================================================================

# ✅ v7.6.22: 20 → 21 (إجبار database.py على إعادة create_tables)
# السبب: إضافة أعمدة لجدول contests لمسابقات quiz
CURRENT_SCHEMA_VERSION = 21

# ✅ v7.6.10: معرّفات بوتات تليجرام الرسمية
CLEANUP_ANONYMOUS_BOT_IDS = (1087968824, 136817688)

# ✅ v7.6.12: فاصل VACUUM التلقائي (24 ساعة)
MAINTENANCE_INTERVAL_SECONDS = 86400

# ✅ v7.6.13: فاصل بين عمليات VACUUM لكل جدول
VACUUM_INTER_TABLE_DELAY_SECONDS = 0.5

# ✅ v7.6.20: 60 → 30 (تنظيف أكثر شدة)
ADMIN_LOGS_RETENTION_DAYS = 30

# ✅ v7.6.20: حد أقصى لعدد الصفوف في admin_logs
ADMIN_LOGS_MAX_ROWS = 5000

# ✅ v7.6.12: الجداول التي تحتاج VACUUM دوري
MAINTENANCE_TABLES = (
    "posts",
    "auto_replies",
    "subscriptions",
    "user_channels",
    "user_penalties",
    "banned_words",
    "schedule",
    "admin_logs",
)

# ✅ v7.6.19: جداول صغيرة تحتاج autovacuum عدواني
SMALL_TABLES_FOR_AGGRESSIVE_AUTOVACUUM = (
    "auto_replies",
    "auto_reply_settings",
    "anonymous_admins",
    "last_publish",
    "user_groups_link",
    "user_points",
    "settings",
    "group_admins",
    "group_security",
    "hidden_owner_groups",
    "hidden_admins",
    "plans",
    "user_warnings",
    "user_violations",
    "referral_rewards",
    "bot_admins",
    "chat_locks",
    "group_rules",
    "schedule",
    "user_reminder_settings",
    "support_tickets",
)

DEFAULT_SETTINGS = (
    ("publish_interval", "12"),
    ("auto_backup", "1"),
    ("last_ticket_number", "0"),
    ("last_backup", ""),
)

# ✅ v7.6.16: 72 (حُذف 3 فهارس زائدة من posts)
EXPECTED_INDEX_COUNT = 72

# ✅ v7.6.14: فهارس تُتخطى على MySQL
MYSQL_SKIP_INDEXES = frozenset({
    "idx_penalties_active_id",
})

COMMON_INDEXES = [
    # ═══ USERS (6) ═══
    ("users", "idx_users_banned", "users(banned)"),
    ("users", "idx_users_active_channel", "users(active_channel)"),
    ("users", "idx_users_auto_publish_banned", "users(auto_publish, banned)"),
    ("users", "idx_users_language", "users(language)"),
    ("users", "idx_users_subscription_end", "users(subscription_end)"),
    ("users", "idx_users_auto_recycle", "users(auto_recycle)"),

    # ═══ USER_CHANNELS (4) ═══
    ("user_channels", "idx_uc_user", "user_channels(user_id)"),
    ("user_channels", "idx_user_channels_user_created",
     "user_channels(user_id, created_at DESC)"),
    ("user_channels", "idx_user_channels_user_banned",
     "user_channels(user_id, banned)"),
    ("user_channels", "idx_user_channels_banned_user",
     "user_channels(banned, user_id)"),

    # ═══ POSTS (4) — ✅ v7.6.16: حُذف 3 فهارس زائدة
    ("posts", "idx_posts_text_hash", "posts(text_hash)"),
    ("posts", "idx_posts_channel_pub_fail_created",
     "posts(channel_db_id, published, fail_count, created_at)"),
    ("posts", "idx_posts_channel_pub_at",
     "posts(channel_db_id, published, published_at)"),
    ("posts", "idx_posts_channel_unpub_fresh_created",
     "posts(channel_db_id, id) WHERE published = 0 "
     "AND (fail_count IS NULL OR fail_count < 3)"),

    # ═══ BOT_GROUPS (4) ═══
    ("bot_groups", "idx_groups_banned", "bot_groups(banned)"),
    ("bot_groups", "idx_bot_groups_added_by", "bot_groups(added_by)"),
    ("bot_groups", "idx_bot_groups_log_channel",
     "bot_groups(log_channel_id)"),
    ("bot_groups", "idx_bot_groups_banned_cover",
     "bot_groups(banned) INCLUDE (chat_id, chat_name, username)"),

    # ═══ USER_GROUPS_LINK (1) ═══
    ("user_groups_link", "idx_user_groups_link_user_id",
     "user_groups_link(user_id)"),

    # ═══ GROUP_ADMINS (2) ═══
    ("group_admins", "idx_group_admins_user_id",
     "group_admins(user_id)"),
    ("group_admins", "idx_group_admins_user_chat",
     "group_admins(user_id, chat_id)"),

    # ═══ HIDDEN_OWNER_GROUPS (2) ═══
    ("hidden_owner_groups", "idx_hidden_owner_groups_owner_id",
     "hidden_owner_groups(owner_id)"),
    ("hidden_owner_groups", "idx_hidden_owner_groups_owner_chat",
     "hidden_owner_groups(owner_id, chat_id)"),

    # ═══ HIDDEN_ADMINS (2) ═══
    ("hidden_admins", "idx_hidden_admins_admin_id",
     "hidden_admins(admin_id)"),
    ("hidden_admins", "idx_hidden_admins_admin_chat",
     "hidden_admins(admin_id, chat_id)"),

    # ═══ ANONYMOUS_ADMINS (4) ═══
    ("anonymous_admins", "idx_anonymous_admins_user_id",
     "anonymous_admins(user_id)"),
    ("anonymous_admins", "idx_anonymous_admins_anonymous_id",
     "anonymous_admins(anonymous_id)"),
    ("anonymous_admins", "idx_anon_user_chat",
     "anonymous_admins(user_id, chat_id)"),
    ("anonymous_admins", "idx_anon_anon_chat",
     "anonymous_admins(anonymous_id, chat_id)"),

    # ═══ BANNED_WORDS (2) ═══
    ("banned_words", "idx_banned_words_chat", "banned_words(chat_id)"),
    ("banned_words", "idx_banned_words_chat_word",
     "banned_words(chat_id, word)"),

    # ═══ AUTO_REPLIES (6) ═══
    ("auto_replies", "idx_ar_chat", "auto_replies(chat_id)"),
    ("auto_replies", "idx_auto_replies_lookup",
     "auto_replies(chat_id, keyword, is_active)"),
    ("auto_replies", "idx_ar_chat_keyword",
     "auto_replies(chat_id, keyword)"),
    ("auto_replies", "idx_ar_usage",
     "auto_replies(usage_count DESC)"),
    ("auto_replies", "idx_auto_replies_keyword_active",
     "auto_replies(keyword, is_active, chat_id)"),
    ("auto_replies", "idx_auto_replies_active_keyword",
     "auto_replies(is_active, keyword, chat_id)"),

    # ═══ SCHEDULE (2) ═══
    ("schedule", "idx_schedule_next_publish",
     "schedule(next_publish_date)"),
    ("schedule", "idx_schedule_channel_next",
     "schedule(channel_db_id, next_publish_date)"),

    # ═══ SUBSCRIPTIONS (5) ═══
    ("subscriptions", "idx_sub_user", "subscriptions(user_id)"),
    ("subscriptions", "idx_sub_status", "subscriptions(status)"),
    ("subscriptions", "idx_sub_end", "subscriptions(end_date)"),
    ("subscriptions", "idx_subscriptions_user_status",
     "subscriptions(user_id, status)"),
    ("subscriptions", "idx_subscriptions_user_status_end",
     "subscriptions(user_id, status, end_date)"),

    # ═══ INVOICES (1) ═══
    ("invoices", "idx_inv_user", "invoices(user_id)"),

    # ═══ REFERRALS (2) ═══
    ("referrals", "idx_referrals_referrer", "referrals(referrer_id)"),
    ("referrals", "idx_referrals_referrer_created",
     "referrals(referrer_id, created_at DESC)"),

    # ═══ REFERRAL_REWARDS (1) ═══
    ("referral_rewards", "idx_referral_rewards_count",
     "referral_rewards(referral_count)"),

    # ═══ CONTESTS (2) ═══
    ("contests", "idx_contests_status", "contests(status)"),
    ("contests", "idx_contests_status_end",
     "contests(status, end_date)"),

    # ═══ CONTEST_PARTICIPANTS (1) ═══
    ("contest_participants", "idx_contest_participants_contest",
     "contest_participants(contest_id)"),

    # ═══ GIFT_CODES (1) ═══
    ("gift_codes", "idx_gift_codes_plan",
     "gift_codes(plan_id)"),

    # ═══ USER_PENALTIES (6) ═══
    ("user_penalties", "idx_penalties_user",
     "user_penalties(user_id)"),
    ("user_penalties", "idx_penalties_chat",
     "user_penalties(chat_id)"),
    ("user_penalties", "idx_penalties_status",
     "user_penalties(status)"),
    ("user_penalties", "idx_penalties_user_chat_status_end",
     "user_penalties(user_id, chat_id, status, end_time)"),
    ("user_penalties", "idx_penalties_status_end",
     "user_penalties(status, end_time)"),
    ("user_penalties", "idx_penalties_active_id",
     "user_penalties(id) WHERE status = 'active' "
     "AND end_time IS NOT NULL"),

    # ═══ USER_POINTS (2) ═══
    ("user_points", "idx_points_user", "user_points(user_id)"),
    ("user_points", "idx_user_points_value", "user_points(points DESC)"),

    # ═══ SUPPORT_TICKETS (2) ═══
    ("support_tickets", "idx_tickets_status",
     "support_tickets(status)"),
    ("support_tickets", "idx_tickets_status_created",
     "support_tickets(status, created_at DESC)"),

    # ═══ PAYMENT_LOGS (1) ═══
    ("payment_logs", "idx_payment_logs_user", "payment_logs(user_id)"),

    # ═══ ADMIN_LOGS (1) ═══
    ("admin_logs", "idx_admin_logs_chat",
     "admin_logs(chat_id, id DESC)"),

    # ═══ PENALTY_ARCHIVE (1) ═══
    ("penalty_archive", "idx_penalty_archive_archived",
     "penalty_archive(archived_at)"),

    # ═══ SENTIMENT_HISTORY (2) ═══
    ("sentiment_history", "idx_sentiment_user_chat",
     "sentiment_history(user_id, chat_id)"),
    ("sentiment_history", "idx_sentiment_created",
     "sentiment_history(created_at)"),

    # ═══ USER_MESSAGES (1) ═══
    ("user_messages", "idx_user_messages_chat",
     "user_messages(chat_id)"),

    # ═══ SCHEDULED_POSTS (1) ═══
    ("scheduled_posts", "idx_scheduled_posts_time",
     "scheduled_posts(publish_time)"),

    # ═══ USER_REMINDER_SETTINGS (1) ═══
    ("user_reminder_settings", "idx_reminder_subscription",
     "user_reminder_settings(subscription_reminder)"),

    # ═══ USER_VIOLATIONS (1) ═══
    ("user_violations", "idx_user_violations_chat",
     "user_violations(chat_id)"),

    # ═══ USER_WARNINGS (1) ═══
    ("user_warnings", "idx_user_warnings_chat",
     "user_warnings(chat_id)"),
]

DEPRECATED_INDEXES = [
    # ═══ POSTS — ✅ v7.6.16: حُذف 3 فهارس زائدة على published ═══
    "idx_posts_channel",
    "idx_posts_published",
    "idx_posts_channel_published",
    "idx_posts_channel_pub_fail_created_optimized",
    "idx_posts_next", "idx_posts_channel_unpub",
    "idx_posts_channel_pub", "idx_posts_channel_pub_fail",
    "idx_posts_channel_pub_fail_count",
    "idx_posts_fail", "idx_posts_created_at",
    "idx_posts_fail_count", "idx_posts_channel_created",
    "idx_posts_channel_fail",

    # ═══ SUBSCRIPTIONS ═══
    "idx_sub_user_status_end", "idx_subscriptions_active",
    "idx_subscriptions_active_end",

    # ═══ USER_CHANNELS ═══
    "idx_user_channels_user_banned_only",
    "idx_user_channels_user_banned_id",
    "idx_user_channels_id_user", "idx_uc_user_banned",
    "idx_uc_channel_id", "idx_uc_active",

    # ═══ USER_PENALTIES ═══
    "idx_penalties_user_chat_status", "idx_penalties_user_chat",
    "idx_user_penalties_active_end", "idx_user_penalties_expiry",
    "idx_user_penalties_cleanup", "idx_penalties_chat_status",
    "idx_penalties_expiry",
    "idx_penalties_cleanup",
    "idx_penalties_end_time",
    "idx_security_chat",
    "idx_group_security_chat",

    # ═══ BANNED_WORDS ═══
    "idx_banned_words_word",

    # ═══ REMINDERS ═══
    "idx_reminders_subscription", "idx_reminders_user",

    # ═══ ADMIN_LOGS ═══
    "idx_admin_logs_created", "idx_admin_logs_admin",

    # ═══ ANONYMOUS_ADMINS ═══
    "idx_anonymous_admins_chat", "idx_anonymous_admins_user",

    # ═══ HIDDEN_ADMINS ═══
    "idx_hidden_admin_admin",

    # ═══ GROUP_ADMINS ═══
    "idx_group_admins_user", "idx_group_admins_chat",

    # ═══ SCHEDULE ═══
    "idx_sched_next", "idx_schedule_next", "idx_schedule_next_channel",

    # ═══ CONTEST_PARTICIPANTS ═══
    "idx_contest_participants_user",

    # ═══ USERS ═══
    "idx_users_updated", "idx_users_trial_used",
    "idx_users_subscription", "idx_users_referral",
    "idx_users_banned_publish",

    # ═══ REFERRALS ═══
    "idx_referrals_referred", "idx_referrals_created",

    # ═══ CONTESTS ═══
    "idx_contests_end",

    # ═══ HIDDEN_OWNER_GROUPS ═══
    "idx_hidden_owner_owner",

    # ═══ SUPPORT_TICKETS ═══
    "idx_tickets_user", "idx_tickets_number",

    # ═══ INVOICES ═══
    "idx_inv_status", "idx_inv_number",

    # ═══ AUTO_REPLIES ═══
    "idx_auto_replies_keyword", "idx_ar_keyword",

    # ═══ SETTINGS ═══
    "idx_settings_key",

    # ═══ USER_VIOLATIONS / WARNINGS ═══
    "idx_user_violations_user",
    "idx_violations_user_chat",
    "idx_user_warnings_user",

    # ═══ USER_GROUPS_LINK ═══
    "idx_ugl_user",
]

CRITICAL_INDEX_NAMES = frozenset({
    "idx_bot_groups_log_channel",
    "idx_posts_channel_pub_fail_created",
    "idx_posts_channel_pub_at",
    "idx_posts_channel_unpub_fresh_created",
    "idx_penalties_user_chat_status_end",
    "idx_penalties_status_end",
    "idx_penalties_active_id",
    "idx_user_channels_user_banned",
    "idx_subscriptions_user_status_end",
    "idx_schedule_channel_next",
    "idx_banned_words_chat",
    "idx_banned_words_chat_word",
    "idx_auto_replies_keyword_active",
    "idx_auto_replies_active_keyword",
    "idx_user_violations_chat",
    "idx_user_warnings_chat",
    "idx_bot_groups_banned_cover",
})

if len(COMMON_INDEXES) != EXPECTED_INDEX_COUNT:
    raise RuntimeError(
        f"❌ عدد الفهارس غير مطابق: "
        f"متوقع {EXPECTED_INDEX_COUNT}، وُجد {len(COMMON_INDEXES)}."
    )


# =====================================================================
# دوال مساعدة
# =====================================================================

def _safe_now_iso(TimeUtils) -> str:
    if TimeUtils:
        try:
            return TimeUtils.sql_iso()
        except Exception as e:
            logging.debug(f"_safe_now_iso fallback: {e}")
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _safe_now_dt(TimeUtils):
    if TimeUtils:
        try:
            return TimeUtils.utc_now()
        except Exception as e:
            logging.debug(f"_safe_now_dt fallback: {e}")
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _is_valid_index_name(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name))


def _normalize_columns(col_str: str) -> str:
    if not col_str:
        return ""
    s = col_str.replace(" ", "").lower()
    s = s.replace("public.", "")
    return s


def _normalize_columns_mysql(col_str: str) -> str:
    if not col_str:
        return ""
    s = col_str.lower()
    s = re.sub(r"\s+(asc|desc)\b", "", s)
    s = s.replace(" ", "")
    return s


def _parse_expected_columns(cols: str) -> str:
    if not cols:
        return ""
    m = re.match(r"^\w+\s*\((.+?)\)(?:\s|$)", cols.strip())
    if not m:
        return ""
    return m.group(1)


def _adapt_cols_for_db(cols: str, db_type: str) -> str:
    if not cols:
        return cols
    if db_type == "postgres":
        return cols

    s = cols

    include_match = re.search(
        r"\s+INCLUDE\s*\(([^)]*)\)", s, re.IGNORECASE
    )
    if include_match:
        included = include_match.group(1).strip()
        s = s[:include_match.start()] + s[include_match.end():]
        s = s.rstrip()
        if s.endswith(")"):
            s = s[:-1].rstrip()
            if not s.endswith("("):
                s += ", " + included + ")"
            else:
                s += included + ")"

    if db_type == "mysql":
        s = re.sub(
            r"\s+WHERE\s+.*$", "", s,
            flags=re.IGNORECASE | re.DOTALL,
        )
        s = s.rstrip()

    return s


def _get_expected_cols_for_index(
    idx_name: str, db_type: str = "postgres"
) -> str:
    for _table, name, cols in COMMON_INDEXES:
        if name == idx_name:
            return _adapt_cols_for_db(cols, db_type)
    return ""


def _is_advanced_index(cols: str) -> bool:
    if not cols:
        return False
    s = cols.upper()
    return " WHERE " in s or " INCLUDE " in s


# =====================================================================
# ✅ v7.6.18/v7.6.20: تنظيف admin_logs القديمة + حد أقصى للصفوف
# =====================================================================

async def _cleanup_old_admin_logs_postgres(conn, logger):
    total_deleted = 0

    try:
        result = await conn.execute(
            "DELETE FROM admin_logs "
            "WHERE created_at < NOW() - "
            f"INTERVAL '{ADMIN_LOGS_RETENTION_DAYS} days'"
        )
        if result and isinstance(result, str) and result.startswith("DELETE "):
            try:
                deleted = int(result.split()[1])
                total_deleted += deleted
                if logger and deleted:
                    logger.info(
                        f"🧹 PG: حُذف {deleted} صف قديم من admin_logs "
                        f"(> {ADMIN_LOGS_RETENTION_DAYS} يوم)"
                    )
            except (IndexError, ValueError):
                pass
    except Exception as e:
        if logger:
            logger.debug(f"⚠️ PG cleanup admin_logs (age): {e}")

    try:
        total = await conn.fetchval("SELECT COUNT(*) FROM admin_logs")
        if total and total > ADMIN_LOGS_MAX_ROWS:
            to_delete = total - ADMIN_LOGS_MAX_ROWS
            result = await conn.execute(
                "DELETE FROM admin_logs "
                "WHERE id IN ("
                "  SELECT id FROM admin_logs "
                "  ORDER BY id ASC "
                f"  LIMIT {to_delete}"
                ")"
            )
            if result and isinstance(result, str) and result.startswith("DELETE "):
                try:
                    deleted = int(result.split()[1])
                    total_deleted += deleted
                    if logger and deleted:
                        logger.info(
                            f"🧹 PG: حُذف {deleted} صف من admin_logs "
                            f"(تجاوز الحد {ADMIN_LOGS_MAX_ROWS})"
                        )
                except (IndexError, ValueError):
                    pass
    except Exception as e:
        if logger:
            logger.debug(f"⚠️ PG cleanup admin_logs (max_rows): {e}")

    return total_deleted


async def _cleanup_old_admin_logs_sqlite(conn, logger):
    total_deleted = 0

    try:
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(days=ADMIN_LOGS_RETENTION_DAYS)
        ).strftime("%Y-%m-%d %H:%M:%S")
        cursor = await conn.execute(
            "DELETE FROM admin_logs WHERE created_at < ?",
            (cutoff,),
        )
        try:
            deleted = cursor.rowcount or 0
            total_deleted += deleted
            if logger and deleted:
                logger.info(
                    f"🧹 SQLite: حُذف {deleted} صف قديم من admin_logs "
                    f"(> {ADMIN_LOGS_RETENTION_DAYS} يوم)"
                )
        finally:
            try:
                await cursor.close()
            except Exception:
                pass
        try:
            await conn.commit()
        except Exception:
            pass
    except Exception as e:
        if logger:
            logger.debug(f"⚠️ SQLite cleanup admin_logs (age): {e}")

    try:
        cursor = await conn.execute("SELECT COUNT(*) FROM admin_logs")
        try:
            row = await cursor.fetchone()
            total = row[0] if row else 0
        finally:
            try:
                await cursor.close()
            except Exception:
                pass

        if total > ADMIN_LOGS_MAX_ROWS:
            to_delete = total - ADMIN_LOGS_MAX_ROWS
            cursor = await conn.execute(
                "DELETE FROM admin_logs "
                "WHERE id IN ("
                "  SELECT id FROM admin_logs "
                "  ORDER BY id ASC "
                "  LIMIT ?"
                ")",
                (to_delete,),
            )
            try:
                deleted = cursor.rowcount or 0
                total_deleted += deleted
                if logger and deleted:
                    logger.info(
                        f"🧹 SQLite: حُذف {deleted} صف من admin_logs "
                        f"(تجاوز الحد {ADMIN_LOGS_MAX_ROWS})"
                    )
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
            try:
                await conn.commit()
            except Exception:
                pass
    except Exception as e:
        if logger:
            logger.debug(f"⚠️ SQLite cleanup admin_logs (max_rows): {e}")

    return total_deleted


async def _cleanup_old_admin_logs_mysql(conn, logger):
    total_deleted = 0

    try:
        cursor = await conn.cursor()
        try:
            await cursor.execute(
                "DELETE FROM admin_logs "
                "WHERE created_at < NOW() - "
                f"INTERVAL {ADMIN_LOGS_RETENTION_DAYS} DAY"
            )
            deleted = cursor.rowcount or 0
            total_deleted += deleted
            if logger and deleted:
                logger.info(
                    f"🧹 MySQL: حُذف {deleted} صف قديم من admin_logs "
                    f"(> {ADMIN_LOGS_RETENTION_DAYS} يوم)"
                )
        finally:
            try:
                await cursor.close()
            except Exception:
                pass
        try:
            await conn.commit()
        except Exception:
            pass
    except Exception as e:
        if logger:
            logger.debug(f"⚠️ MySQL cleanup admin_logs (age): {e}")

    try:
        cursor = await conn.cursor()
        try:
            await cursor.execute("SELECT COUNT(*) FROM admin_logs")
            row = await cursor.fetchone()
            total = row[0] if row else 0
        finally:
            try:
                await cursor.close()
            except Exception:
                pass

        if total > ADMIN_LOGS_MAX_ROWS:
            to_delete = total - ADMIN_LOGS_MAX_ROWS
            cursor = await conn.cursor()
            try:
                await cursor.execute(
                    "DELETE FROM admin_logs "
                    f"ORDER BY id ASC "
                    f"LIMIT {to_delete}"
                )
                deleted = cursor.rowcount or 0
                total_deleted += deleted
                if logger and deleted:
                    logger.info(
                        f"🧹 MySQL: حُذف {deleted} صف من admin_logs "
                        f"(تجاوز الحد {ADMIN_LOGS_MAX_ROWS})"
                    )
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
            try:
                await conn.commit()
            except Exception:
                pass
    except Exception as e:
        if logger:
            logger.debug(f"⚠️ MySQL cleanup admin_logs (max_rows): {e}")

    return total_deleted


# =====================================================================
# ✅ v7.6.18: ضبط autovacuum للجداول الصغيرة
# =====================================================================

async def _tune_autovacuum_postgres(conn, logger):
    tuned = 0
    failed = 0
    for tbl in SMALL_TABLES_FOR_AGGRESSIVE_AUTOVACUUM:
        if not _is_valid_index_name(tbl):
            failed += 1
            continue
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = $1 "
                "AND table_schema = current_schema()",
                tbl,
            )
            if not exists:
                continue
            await conn.execute(
                f"ALTER TABLE {tbl} SET ("
                f"autovacuum_vacuum_scale_factor = 0.05, "
                f"autovacuum_vacuum_threshold = 10, "
                f"autovacuum_analyze_scale_factor = 0.02, "
                f"autovacuum_analyze_threshold = 10"
                f")"
            )
            tuned += 1
        except Exception as e:
            failed += 1
            if logger:
                logger.debug(f"⚠️ PG autovacuum tune {tbl}: {e}")
    if logger and tuned:
        logger.info(
            f"⚙️ PG: ضُبط autovacuum على {tuned} جدول صغير "
            f"({failed} فشل)"
        )
    return tuned


# =====================================================================
# فحص جماعي للفهارس (SCHEMA-AWARE)
# =====================================================================

async def _ensure_all_indexes_exist_postgres(conn, logger):
    try:
        all_names = [n for _, n, _ in COMMON_INDEXES]
        rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes "
            "WHERE indexname = ANY($1::text[]) "
            "  AND schemaname = ANY(current_schemas(false))",
            all_names,
        )
        existing = {r["indexname"] for r in rows}
        missing = [n for n in all_names if n not in existing]
        if not missing:
            return 0

        if logger:
            logger.warning(
                f"⚠️ PG: {len(missing)} فهرس مفقود في fast-path "
                f"— إعادة إنشاء"
            )

        created = 0
        failed = 0
        for idx_name in missing:
            if not _is_valid_index_name(idx_name):
                failed += 1
                continue
            cols = _get_expected_cols_for_index(idx_name, "postgres")
            if not cols:
                failed += 1
                continue
            try:
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {cols}"
                )
                created += 1
            except Exception as e:
                failed += 1
                if logger:
                    logger.warning(
                        f"⚠️ PG fast-path فهرس {idx_name}: {e}"
                    )
        if logger and created:
            logger.info(
                f"✅ PG fast-path: أُعيد إنشاء {created} فهرس "
                f"({failed} فشل)"
            )
        return created
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _ensure_all_indexes_exist_postgres: {e}")
        return 0


async def _ensure_all_indexes_exist_sqlite(conn, logger):
    try:
        all_names = [n for _, n, _ in COMMON_INDEXES]
        placeholders = ",".join(["?"] * len(all_names))
        cursor = await conn.execute(
            f"SELECT name FROM sqlite_master "
            f"WHERE type='index' AND name IN ({placeholders})",
            tuple(all_names),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            try:
                await cursor.close()
            except Exception:
                pass
        existing = {r[0] for r in rows}
        missing = [n for n in all_names if n not in existing]
        if not missing:
            return 0

        if logger:
            logger.warning(
                f"⚠️ SQLite: {len(missing)} فهرس مفقود في fast-path "
                f"— إعادة إنشاء"
            )

        created = 0
        failed = 0
        for idx_name in missing:
            if not _is_valid_index_name(idx_name):
                failed += 1
                continue
            cols = _get_expected_cols_for_index(idx_name, "sqlite")
            if not cols:
                failed += 1
                continue
            try:
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {cols}"
                )
                created += 1
            except Exception as e:
                failed += 1
                if logger:
                    logger.warning(
                        f"⚠️ SQLite fast-path فهرس {idx_name}: {e}"
                    )
        if created:
            try:
                await conn.commit()
            except Exception:
                pass
        if logger and created:
            logger.info(
                f"✅ SQLite fast-path: أُعيد إنشاء {created} فهرس "
                f"({failed} فشل)"
            )
        return created
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _ensure_all_indexes_exist_sqlite: {e}")
        return 0


async def _ensure_all_indexes_exist_mysql(conn, logger):
    try:
        tables = set(t for t, _, _ in COMMON_INDEXES)
        try:
            existing_pairs = await _fetch_existing_indexes_mysql(
                conn, list(tables)
            )
        except Exception as e:
            if logger:
                logger.warning(f"⚠️ MySQL fetch indexes: {e}")
            return 0

        existing = {(t, idx) for (t, idx) in existing_pairs}
        missing = [
            (t, n, c) for t, n, c in COMMON_INDEXES
            if (t, n) not in existing and n not in MYSQL_SKIP_INDEXES
        ]
        if not missing:
            return 0

        if logger:
            logger.warning(
                f"⚠️ MySQL: {len(missing)} فهرس مفقود في fast-path "
                f"— إعادة إنشاء"
            )

        created = 0
        failed = 0
        for _table, idx_name, cols in missing:
            if not _is_valid_index_name(idx_name):
                failed += 1
                continue
            adapted = _adapt_cols_for_db(cols, "mysql")
            if not adapted:
                failed += 1
                continue
            try:
                await conn.execute(
                    f"CREATE INDEX {idx_name} ON {adapted}"
                )
                created += 1
            except Exception as e:
                err_msg = str(e).lower()
                if (
                    "duplicate" in err_msg
                    or "already exists" in err_msg
                    or "1061" in err_msg
                ):
                    continue
                failed += 1
                if logger:
                    logger.warning(
                        f"⚠️ MySQL fast-path فهرس {idx_name}: {e}"
                    )
        if logger and created:
            logger.info(
                f"✅ MySQL fast-path: أُنشئ {created} فهرس "
                f"({failed} فشل)"
            )
        return created
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _ensure_all_indexes_exist_mysql: {e}")
        return 0


# =====================================================================
# ANALYZE سريع
# =====================================================================

async def _quick_analyze_postgres(conn, logger):
    try:
        done = 0
        for tbl in MAINTENANCE_TABLES:
            try:
                await conn.execute(f"ANALYZE {tbl}")
                done += 1
            except Exception as e:
                if logger:
                    logger.debug(f"⚠️ ANALYZE {tbl}: {e}")
        if logger and done:
            logger.info(f"📊 PG: ANALYZE على {done} جدول")
        return done
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _quick_analyze_postgres: {e}")
        return 0


async def _quick_analyze_mysql(conn, logger):
    try:
        done = 0
        for tbl in MAINTENANCE_TABLES:
            try:
                await conn.execute(f"ANALYZE TABLE `{tbl}`")
                done += 1
            except Exception as e:
                if logger:
                    logger.debug(f"⚠️ ANALYZE {tbl}: {e}")
        if logger and done:
            logger.info(f"📊 MySQL: ANALYZE على {done} جدول")
        return done
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _quick_analyze_mysql: {e}")
        return 0


# =====================================================================
# VACUUM ANALYZE الدوري
# =====================================================================

async def _run_maintenance_postgres(conn, logger):
    try:
        try:
            last_val = await conn.fetchval(
                "SELECT value FROM settings WHERE key = 'last_maintenance_at'"
            )
        except Exception:
            last_val = None

        if last_val:
            try:
                last_dt = datetime.fromisoformat(str(last_val))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - last_dt).total_seconds()
                if age < MAINTENANCE_INTERVAL_SECONDS:
                    if logger:
                        logger.debug(
                            f"⏩ PG maintenance: تخطي (آخر صيانة منذ "
                            f"{age / 3600:.1f}h)"
                        )
                    return 0
            except (ValueError, TypeError):
                pass

        if logger:
            logger.info(
                "🧹 PG: بدء VACUUM (ANALYZE, SKIP_LOCKED) "
                "على الجداول الحرجة..."
            )

        done = 0
        failed = 0
        for tbl in MAINTENANCE_TABLES:
            try:
                await conn.execute(
                    f"VACUUM (ANALYZE, SKIP_LOCKED) {tbl}"
                )
                done += 1
            except Exception as e:
                failed += 1
                if logger:
                    logger.debug(f"⚠️ VACUUM {tbl}: {e}")
            try:
                await asyncio.sleep(VACUUM_INTER_TABLE_DELAY_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

        try:
            await conn.execute(
                "INSERT INTO settings (key, value) VALUES ($1, $2) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                "last_maintenance_at",
                datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            if logger:
                logger.debug(f"⚠️ record maintenance time: {e}")

        if logger and done:
            logger.info(
                f"✅ PG: VACUUM (ANALYZE, SKIP_LOCKED) على {done} جدول "
                f"({failed} فشل)"
            )
        return done
    except asyncio.CancelledError:
        raise
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _run_maintenance_postgres: {e}")
        return 0


async def _run_maintenance_sqlite(conn, logger):
    try:
        try:
            cursor = await conn.execute(
                "SELECT value FROM settings WHERE key = 'last_maintenance_at'"
            )
            try:
                row = await cursor.fetchone()
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
        except Exception:
            row = None

        last_val = row[0] if row else None
        if last_val:
            try:
                last_dt = datetime.fromisoformat(str(last_val))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - last_dt).total_seconds()
                if age < MAINTENANCE_INTERVAL_SECONDS:
                    return 0
            except (ValueError, TypeError):
                pass

        if logger:
            logger.info("🧹 SQLite: بدء VACUUM + ANALYZE...")

        try:
            await conn.execute("VACUUM")
        except Exception as e:
            if logger:
                logger.debug(f"⚠️ SQLite VACUUM: {e}")

        try:
            await conn.execute("ANALYZE")
        except Exception as e:
            if logger:
                logger.debug(f"⚠️ SQLite ANALYZE: {e}")

        try:
            await conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("last_maintenance_at", datetime.now(timezone.utc).isoformat()),
            )
            await conn.commit()
        except Exception:
            pass

        if logger:
            logger.info("✅ SQLite: VACUUM + ANALYZE مكتمل")
        return 1
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _run_maintenance_sqlite: {e}")
        return 0


async def _run_maintenance_mysql(conn, logger):
    try:
        try:
            cursor = await conn.cursor()
            try:
                await cursor.execute(
                    "SELECT `value` FROM settings "
                    "WHERE `key` = 'last_maintenance_at'"
                )
                row = await cursor.fetchone()
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
        except Exception:
            row = None

        last_val = row[0] if row else None
        if last_val:
            try:
                last_dt = datetime.fromisoformat(str(last_val))
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - last_dt).total_seconds()
                if age < MAINTENANCE_INTERVAL_SECONDS:
                    return 0
            except (ValueError, TypeError):
                pass

        if logger:
            logger.info("🧹 MySQL: بدء ANALYZE + OPTIMIZE...")

        done = 0
        for tbl in MAINTENANCE_TABLES:
            try:
                await conn.execute(f"ANALYZE TABLE `{tbl}`")
                done += 1
            except Exception as e:
                if logger:
                    logger.debug(f"⚠️ ANALYZE {tbl}: {e}")
            try:
                await asyncio.sleep(VACUUM_INTER_TABLE_DELAY_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

        try:
            cursor = await conn.cursor()
            try:
                await cursor.execute(
                    "INSERT INTO settings (`key`, `value`) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)",
                    ("last_maintenance_at",
                     datetime.now(timezone.utc).isoformat()),
                )
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass
            await conn.commit()
        except Exception:
            pass

        if logger and done:
            logger.info(f"✅ MySQL: ANALYZE على {done} جدول")
        return done
    except asyncio.CancelledError:
        raise
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _run_maintenance_mysql: {e}")
        return 0


# =====================================================================
# Migrations — إضافة أعمدة مفقودة
# =====================================================================

# ✅ v7.6.22: group_security — أعمدة إضافية
_GROUP_SECURITY_NEW_COLUMNS = [
    ("violation_penalty", "TEXT DEFAULT 'none'"),
    ("violation_penalty_duration", "INTEGER DEFAULT 3600"),
]

# ✅ v7.6.22: contests — أعمدة مسابقات quiz
_CONTESTS_NEW_COLUMNS = [
    ("contest_type", "TEXT DEFAULT 'raffle'"),
    ("question", "TEXT DEFAULT ''"),
    ("correct_answer", "TEXT DEFAULT ''"),
]


async def _migrate_missing_columns_sqlite(conn, logger):
    checked = 0
    added = 0

    # ─── group_security ───
    for col_name, col_def in _GROUP_SECURITY_NEW_COLUMNS:
        checked += 1
        try:
            await conn.execute(
                f"ALTER TABLE group_security "
                f"ADD COLUMN {col_name} {col_def}"
            )
            added += 1
            if logger:
                logger.info(
                    f"✅ SQLite: أُضيف عمود {col_name} (group_security)"
                )
        except Exception as e:
            err = str(e).lower()
            if "duplicate" in err or "already exists" in err:
                continue
            if logger:
                logger.debug(f"⚠️ SQLite migration {col_name}: {e}")

    # ─── contests ─── (v7.6.22)
    for col_name, col_def in _CONTESTS_NEW_COLUMNS:
        checked += 1
        try:
            await conn.execute(
                f"ALTER TABLE contests "
                f"ADD COLUMN {col_name} {col_def}"
            )
            added += 1
            if logger:
                logger.info(
                    f"✅ SQLite: أُضيف عمود {col_name} (contests)"
                )
        except Exception as e:
            err = str(e).lower()
            if "duplicate" in err or "already exists" in err:
                continue
            if logger:
                logger.debug(
                    f"⚠️ SQLite migration contests.{col_name}: {e}"
                )

    if added:
        await conn.commit()
    return added


async def _migrate_missing_columns_postgres(conn, logger):
    checked = 0
    added = 0
    skipped = 0

    # ─── group_security ───
    for col_name, col_def in _GROUP_SECURITY_NEW_COLUMNS:
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'group_security' "
                "AND column_name = $1 "
                "AND table_schema = current_schema()",
                col_name,
            )
            checked += 1
            if exists:
                skipped += 1
                continue

            await conn.execute(
                f"ALTER TABLE group_security "
                f"ADD COLUMN {col_name} {col_def}"
            )
            added += 1
            if logger:
                logger.info(
                    f"✅ PG: أُضيف عمود {col_name} (group_security)"
                )
        except Exception as e:
            if logger:
                logger.debug(f"⚠️ PG migration {col_name}: {e}")

    # ─── contests ─── (v7.6.22)
    for col_name, col_def in _CONTESTS_NEW_COLUMNS:
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'contests' "
                "AND column_name = $1 "
                "AND table_schema = current_schema()",
                col_name,
            )
            checked += 1
            if exists:
                skipped += 1
                continue

            await conn.execute(
                f"ALTER TABLE contests "
                f"ADD COLUMN {col_name} {col_def}"
            )
            added += 1
            if logger:
                logger.info(
                    f"✅ PG: أُضيف عمود {col_name} (contests)"
                )
        except Exception as e:
            if logger:
                logger.debug(
                    f"⚠️ PG migration contests.{col_name}: {e}"
                )

    if logger and checked:
        logger.debug(
            f"📊 PG migration: فُحص {checked}، "
            f"أُضيف {added}، موجود مسبقاً {skipped}"
        )
    return added


async def _migrate_missing_columns_mysql(conn, logger):
    checked = 0
    added = 0
    skipped = 0

    # ─── group_security ───
    for col_name, col_def in _GROUP_SECURITY_NEW_COLUMNS:
        checked += 1
        try:
            cursor = await conn.cursor()
            try:
                await cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE TABLE_SCHEMA = DATABASE() "
                    "AND TABLE_NAME = 'group_security' "
                    "AND COLUMN_NAME = %s",
                    (col_name,),
                )
                row = await cursor.fetchone()
                exists = row and row[0] > 0
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass

            if exists:
                skipped += 1
                continue

            await conn.execute(
                f"ALTER TABLE group_security "
                f"ADD COLUMN {col_name} {col_def}"
            )
            added += 1
            if logger:
                logger.info(
                    f"✅ MySQL: أُضيف عمود {col_name} (group_security)"
                )
        except Exception as e:
            if logger:
                logger.debug(f"⚠️ MySQL migration {col_name}: {e}")

    # ─── contests ─── (v7.6.22)
    for col_name, col_def in _CONTESTS_NEW_COLUMNS:
        checked += 1
        try:
            cursor = await conn.cursor()
            try:
                await cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE TABLE_SCHEMA = DATABASE() "
                    "AND TABLE_NAME = 'contests' "
                    "AND COLUMN_NAME = %s",
                    (col_name,),
                )
                row = await cursor.fetchone()
                exists = row and row[0] > 0
            finally:
                try:
                    await cursor.close()
                except Exception:
                    pass

            if exists:
                skipped += 1
                continue

            await conn.execute(
                f"ALTER TABLE contests "
                f"ADD COLUMN {col_name} {col_def}"
            )
            added += 1
            if logger:
                logger.info(
                    f"✅ MySQL: أُضيف عمود {col_name} (contests)"
                )
        except Exception as e:
            if logger:
                logger.debug(
                    f"⚠️ MySQL migration contests.{col_name}: {e}"
                )

    if logger and checked:
        logger.debug(
            f"📊 MySQL migration: فُحص {checked}، "
            f"أُضيف {added}، موجود مسبقاً {skipped}"
        )
    return added


# =====================================================================
# Fast-path: قراءة schema_version
# =====================================================================

async def _get_current_schema_version_postgres(conn):
    try:
        row = await conn.fetchrow(
            "SELECT MAX(version) AS v FROM schema_version"
        )
        if row and row["v"] is not None:
            return int(row["v"])
    except Exception:
        pass
    return 0


async def _get_current_schema_version_sqlite(conn):
    try:
        cursor = await conn.execute(
            "SELECT MAX(version) FROM schema_version"
        )
        try:
            row = await cursor.fetchone()
        finally:
            try:
                await cursor.close()
            except Exception:
                pass
        if row and row[0] is not None:
            return int(row[0])
    except Exception:
        pass
    return 0


async def _get_current_schema_version_mysql(conn):
    try:
        cursor = await conn.cursor()
        try:
            await cursor.execute("SELECT MAX(version) FROM schema_version")
            row = await cursor.fetchone()
            if row and row[0] is not None:
                return int(row[0])
        finally:
            try:
                await cursor.close()
            except Exception:
                pass
    except Exception:
        pass
    return 0


# =====================================================================
# التنظيف التلقائي للبيانات القديمة
# =====================================================================

async def _cleanup_stale_links_sqlite(conn, logger):
    cleaned_links = 0
    cleaned_anon = 0
    try:
        cursor = await conn.execute(
            "DELETE FROM user_groups_link WHERE user_id < 0"
        )
        try:
            cleaned_links = cursor.rowcount or 0
        finally:
            try:
                await cursor.close()
            except Exception:
                pass
        await conn.commit()
    except Exception as e:
        if logger:
            logger.debug(f"⚠️ SQLite cleanup user_groups_link: {e}")

    try:
        placeholders = ",".join(["?"] * len(CLEANUP_ANONYMOUS_BOT_IDS))
        cursor = await conn.execute(
            f"DELETE FROM anonymous_admins "
            f"WHERE anonymous_id IN ({placeholders})",
            CLEANUP_ANONYMOUS_BOT_IDS,
        )
        try:
            cleaned_anon = cursor.rowcount or 0
        finally:
            try:
                await cursor.close()
            except Exception:
                pass
        await conn.commit()
    except Exception as e:
        if logger:
            logger.debug(f"⚠️ SQLite cleanup anonymous_admins: {e}")

    if logger and (cleaned_links or cleaned_anon):
        logger.info(
            f"🧹 SQLite cleanup: {cleaned_links} صف سالب من user_groups_link، "
            f"{cleaned_anon} صف بوت نظام من anonymous_admins"
        )
    return cleaned_links + cleaned_anon


async def _cleanup_stale_links_postgres(conn, logger):
    cleaned_links = 0
    cleaned_anon = 0
    try:
        result = await conn.execute(
            "DELETE FROM user_groups_link WHERE user_id < 0"
        )
        if result and isinstance(result, str) and result.startswith("DELETE "):
            try:
                cleaned_links = int(result.split()[1])
            except (IndexError, ValueError):
                pass
    except Exception as e:
        if logger:
            logger.debug(f"⚠️ PG cleanup user_groups_link: {e}")

    try:
        result = await conn.execute(
            "DELETE FROM anonymous_admins "
            "WHERE anonymous_id = ANY($1::bigint[])",
            list(CLEANUP_ANONYMOUS_BOT_IDS),
        )
        if result and isinstance(result, str) and result.startswith("DELETE "):
            try:
                cleaned_anon = int(result.split()[1])
            except (IndexError, ValueError):
                pass
    except Exception as e:
        if logger:
            logger.debug(f"⚠️ PG cleanup anonymous_admins: {e}")

    if logger and (cleaned_links or cleaned_anon):
        logger.info(
            f"🧹 PG cleanup: {cleaned_links} صف سالب من user_groups_link، "
            f"{cleaned_anon} صف بوت نظام من anonymous_admins"
        )
    return cleaned_links + cleaned_anon


async def _cleanup_stale_links_mysql(conn, logger):
    cleaned_links = 0
    cleaned_anon = 0
    try:
        cursor = await conn.cursor()
        try:
            await cursor.execute(
                "DELETE FROM user_groups_link WHERE user_id < 0"
            )
            cleaned_links = cursor.rowcount or 0
        finally:
            try:
                await cursor.close()
            except Exception:
                pass
        await conn.commit()
    except Exception as e:
        if logger:
            logger.debug(f"⚠️ MySQL cleanup user_groups_link: {e}")

    try:
        cursor = await conn.cursor()
        try:
            placeholders = ",".join(["%s"] * len(CLEANUP_ANONYMOUS_BOT_IDS))
            await cursor.execute(
                f"DELETE FROM anonymous_admins "
                f"WHERE anonymous_id IN ({placeholders})",
                CLEANUP_ANONYMOUS_BOT_IDS,
            )
            cleaned_anon = cursor.rowcount or 0
        finally:
            try:
                await cursor.close()
            except Exception:
                pass
        await conn.commit()
    except Exception as e:
        if logger:
            logger.debug(f"⚠️ MySQL cleanup anonymous_admins: {e}")

    if logger and (cleaned_links or cleaned_anon):
        logger.info(
            f"🧹 MySQL cleanup: {cleaned_links} صف سالب من user_groups_link، "
            f"{cleaned_anon} صف بوت نظام من anonymous_admins"
        )
    return cleaned_links + cleaned_anon


# =====================================================================
# فحص الفهارس الحرجة
# =====================================================================

async def _verify_critical_indexes_postgres(conn, logger):
    try:
        rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes "
            "WHERE indexname = ANY($1::text[]) "
            "  AND schemaname = ANY(current_schemas(false))",
            list(CRITICAL_INDEX_NAMES),
        )
        existing = {r["indexname"] for r in rows}
        missing = CRITICAL_INDEX_NAMES - existing
        if not missing:
            return 0
        if logger:
            logger.warning(
                f"⚠️ PG: {len(missing)} فهرس حرج مفقود — إعادة إنشاء"
            )
        created = 0
        for idx_name in missing:
            if not _is_valid_index_name(idx_name):
                continue
            cols = _get_expected_cols_for_index(idx_name, "postgres")
            if not cols:
                continue
            try:
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {cols}"
                )
                created += 1
                if logger:
                    logger.info(f"✅ PG: أُنشئ {idx_name}")
            except Exception as e:
                if logger:
                    logger.warning(f"⚠️ PG فشل إنشاء {idx_name}: {e}")
        return created
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _verify_critical_indexes_postgres: {e}")
        return 0


async def _verify_critical_indexes_sqlite(conn, logger):
    try:
        placeholders = ",".join(["?"] * len(CRITICAL_INDEX_NAMES))
        cursor = await conn.execute(
            f"SELECT name FROM sqlite_master "
            f"WHERE type='index' AND name IN ({placeholders})",
            tuple(CRITICAL_INDEX_NAMES),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            try:
                await cursor.close()
            except Exception:
                pass
        existing = {r[0] for r in rows}
        missing = CRITICAL_INDEX_NAMES - existing
        if not missing:
            return 0
        if logger:
            logger.warning(
                f"⚠️ SQLite: {len(missing)} فهرس حرج مفقود — إعادة إنشاء"
            )
        created = 0
        for idx_name in missing:
            if not _is_valid_index_name(idx_name):
                continue
            cols = _get_expected_cols_for_index(idx_name, "sqlite")
            if not cols:
                continue
            try:
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS {idx_name} ON {cols}"
                )
                created += 1
                if logger:
                    logger.info(f"✅ SQLite: أُنشئ {idx_name}")
            except Exception as e:
                if logger:
                    logger.warning(f"⚠️ SQLite فشل {idx_name}: {e}")
        return created
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _verify_critical_indexes_sqlite: {e}")
        return 0


async def _verify_critical_indexes_mysql(conn, logger):
    try:
        tables = set()
        for _t, idx_name, _c in COMMON_INDEXES:
            if idx_name in CRITICAL_INDEX_NAMES:
                tables.add(_t)
        if not tables:
            return 0
        existing_pairs = await _fetch_existing_indexes_mysql(
            conn, list(tables)
        )
        existing_names = {idx for _, idx in existing_pairs}
        missing = CRITICAL_INDEX_NAMES - existing_names
        missing = {n for n in missing if n not in MYSQL_SKIP_INDEXES}
        if not missing:
            return 0
        if logger:
            logger.warning(
                f"⚠️ MySQL: {len(missing)} فهرس حرج مفقود — إعادة إنشاء"
            )
        created = 0
        for idx_name in missing:
            if not _is_valid_index_name(idx_name):
                continue
            cols = _get_expected_cols_for_index(idx_name, "mysql")
            if not cols:
                continue
            try:
                await conn.execute(f"CREATE INDEX {idx_name} ON {cols}")
                created += 1
                if logger:
                    logger.info(f"✅ MySQL: أُنشئ {idx_name}")
            except Exception as e:
                err_msg = str(e).lower()
                if (
                    "duplicate" in err_msg
                    or "already exists" in err_msg
                    or "1061" in err_msg
                ):
                    continue
                if logger:
                    logger.warning(f"⚠️ MySQL فشل {idx_name}: {e}")
        return created
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _verify_critical_indexes_mysql: {e}")
        return 0


# =====================================================================
# دوال فحص جماعية
# =====================================================================

async def _fetch_existing_indexes_postgres(conn, index_names):
    if not index_names:
        return set()
    try:
        rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes "
            "WHERE indexname = ANY($1::text[]) "
            "  AND schemaname = ANY(current_schemas(false))",
            list(index_names),
        )
        return {row["indexname"] for row in rows}
    except Exception as e:
        logging.debug(f"_fetch_existing_indexes_postgres: {e}")
        return set()


async def _fetch_existing_indexes_sqlite(conn):
    try:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND name IS NOT NULL"
        )
        try:
            rows = await cursor.fetchall()
        finally:
            try:
                await cursor.close()
            except Exception:
                pass
        return {row[0] for row in rows}
    except Exception as e:
        logging.debug(f"_fetch_existing_indexes_sqlite: {e}")
        return set()


async def _fetch_existing_indexes_mysql(conn, tables):
    if not tables:
        return set()
    try:
        cursor = await conn.cursor()
        placeholders = ",".join(["%s"] * len(tables))
        await cursor.execute(
            f"SELECT DISTINCT TABLE_NAME, INDEX_NAME "
            f"FROM information_schema.statistics "
            f"WHERE TABLE_SCHEMA = DATABASE() "
            f"AND TABLE_NAME IN ({placeholders})",
            tuple(tables),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return {(r[0], r[1]) for r in rows}
    except Exception as e:
        logging.warning(
            f"⚠️ information_schema فشل ({e}) — استخدام SHOW INDEX"
        )
        existing = set()
        for table in tables:
            try:
                cursor = await conn.cursor()
                try:
                    await cursor.execute(f"SHOW INDEX FROM `{table}`")
                    rows = await cursor.fetchall()
                    for r in rows:
                        existing.add((table, r[2]))
                finally:
                    try:
                        await cursor.close()
                    except Exception:
                        pass
            except Exception:
                continue
        return existing


# =====================================================================
# فحص تعريفات الفهارس
# =====================================================================

async def _ensure_index_definitions_match_postgres(conn, logger):
    checked = 0
    dropped = 0
    missing = 0
    try:
        rows = await conn.fetch(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE indexname = ANY($1::text[]) "
            "  AND schemaname = ANY(current_schemas(false))",
            [name for _, name, _ in COMMON_INDEXES],
        )
        existing = {row["indexname"]: row["indexdef"] for row in rows}
        for _table, idx_name, cols in COMMON_INDEXES:
            if not _is_valid_index_name(idx_name):
                continue
            if _is_advanced_index(cols):
                checked += 1
                continue
            if idx_name not in existing:
                missing += 1
                continue
            actual_def = existing[idx_name]
            m = re.search(
                r"USING\s+\w+\s+\(([^)]+)\)",
                actual_def,
                re.IGNORECASE,
            )
            if not m:
                continue
            actual_cols = _normalize_columns(m.group(1))
            expected_cols = _normalize_columns(
                _parse_expected_columns(cols)
            )
            if actual_cols != expected_cols:
                logger.warning(
                    f"⚠️ PG: {idx_name} تعريف مختلف "
                    f"(فعلي={actual_cols[:60]}, متوقع={expected_cols[:60]}) — يُحذف"
                )
                try:
                    await conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
                    dropped += 1
                except Exception as e:
                    logger.warning(f"⚠️ فشل حذف {idx_name}: {e}")
            checked += 1
        if logger and dropped > 0:
            logger.info(
                f"🔧 PG: أُعيد بناء {dropped} فهرس — "
                f"فُحص {checked}، مفقود {missing}"
            )
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _ensure_index_definitions_match_postgres: {e}")


async def _ensure_index_definitions_match_sqlite(conn, logger):
    checked = 0
    dropped = 0
    missing = 0
    try:
        names = [name for _, name, _ in COMMON_INDEXES]
        if not names:
            return
        placeholders = ",".join(["?"] * len(names))
        cursor = await conn.execute(
            f"SELECT name, sql FROM sqlite_master "
            f"WHERE type='index' AND name IN ({placeholders})",
            tuple(names),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            try:
                await cursor.close()
            except Exception:
                pass
        existing = {r[0]: (r[1] or "") for r in rows}
        for _table, idx_name, cols in COMMON_INDEXES:
            if not _is_valid_index_name(idx_name):
                continue
            if " INCLUDE " in cols.upper():
                checked += 1
                continue
            if idx_name not in existing:
                missing += 1
                continue
            sql_def = existing[idx_name]
            m = re.search(
                r"ON\s+\w+\s*\(([^)]+)\)",
                sql_def,
                re.IGNORECASE,
            )
            if not m:
                continue
            actual_cols = _normalize_columns(m.group(1))
            expected_cols = _normalize_columns(
                _parse_expected_columns(cols)
            )
            if actual_cols != expected_cols:
                logger.warning(f"⚠️ SQLite: {idx_name} تعريف مختلف — يُحذف")
                try:
                    await conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
                    dropped += 1
                except Exception as e:
                    logger.warning(f"⚠️ فشل حذف {idx_name}: {e}")
            checked += 1
        if logger and dropped > 0:
            logger.info(
                f"🔧 SQLite: أُعيد بناء {dropped} فهرس — "
                f"فُحص {checked}، مفقود {missing}"
            )
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _ensure_index_definitions_match_sqlite: {e}")


async def _ensure_index_definitions_match_mysql(conn, logger):
    checked = 0
    dropped = 0
    missing = 0
    try:
        tables = set(t for t, _, _ in COMMON_INDEXES)
        for table in tables:
            if not _is_valid_index_name(table):
                continue
            try:
                cursor = await conn.cursor()
                try:
                    await cursor.execute(f"SHOW INDEX FROM `{table}`")
                    rows = await cursor.fetchall()
                finally:
                    await cursor.close()
            except Exception:
                continue
            by_key = {}
            for r in rows:
                key_name = r[2]
                seq = r[3]
                col_name = r[4]
                by_key.setdefault(key_name, []).append((seq, col_name))
            for _t, idx_name, cols in COMMON_INDEXES:
                if _t != table:
                    continue
                if not _is_valid_index_name(idx_name):
                    continue
                if idx_name in MYSQL_SKIP_INDEXES:
                    continue
                if idx_name not in by_key:
                    missing += 1
                    continue
                sorted_cols = sorted(by_key[idx_name], key=lambda x: x[0])
                actual_cols = _normalize_columns_mysql(
                    ",".join(c for _, c in sorted_cols)
                )
                adapted_cols = _adapt_cols_for_db(cols, "mysql")
                expected_cols = _normalize_columns_mysql(
                    _parse_expected_columns(adapted_cols)
                )
                if actual_cols != expected_cols:
                    logger.warning(
                        f"⚠️ MySQL: {table}.{idx_name} تعريف مختلف — يُحذف"
                    )
                    try:
                        await conn.execute(
                            f"DROP INDEX {idx_name} ON `{table}`"
                        )
                        dropped += 1
                    except Exception as e:
                        logger.warning(f"⚠️ فشل حذف {idx_name}: {e}")
                checked += 1
        if logger and dropped > 0:
            logger.info(
                f"🔧 MySQL: أُعيد بناء {dropped} فهرس — "
                f"فُحص {checked}، مفقود {missing}"
            )
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ _ensure_index_definitions_match_mysql: {e}")


# =====================================================================
# حذف الفهارس القديمة (SCHEMA-AWARE)
# =====================================================================

async def _drop_deprecated_indexes_postgres(conn, logger):
    if not DEPRECATED_INDEXES:
        return 0
    dropped = 0
    try:
        rows = await conn.fetch(
            "SELECT indexname FROM pg_indexes "
            "WHERE indexname = ANY($1::text[]) "
            "  AND schemaname = ANY(current_schemas(false))",
            DEPRECATED_INDEXES,
        )
        existing = {row["indexname"] for row in rows}
        if not existing:
            if logger:
                logger.debug("🧹 PG: 0 فهرس قديم للحذف")
            return 0
        for idx_name in existing:
            if not _is_valid_index_name(idx_name):
                continue
            try:
                await conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
                dropped += 1
                if logger:
                    logger.info(f"🧹 PG: حُذف فهرس قديم {idx_name}")
            except Exception as e:
                logger.warning(f"⚠️ فشل حذف فهرس {idx_name}: {e}")
        if dropped > 0:
            logger.info(f"🧹 PG: حُذف إجمالي {dropped} فهرس قديم")
    except Exception as e:
        logger.warning(f"⚠️ _drop_deprecated_indexes_postgres: {e}")
    return dropped


async def _drop_deprecated_indexes_sqlite(conn, logger):
    if not DEPRECATED_INDEXES:
        return 0
    dropped = 0
    try:
        placeholders = ",".join(["?"] * len(DEPRECATED_INDEXES))
        cursor = await conn.execute(
            f"SELECT name FROM sqlite_master "
            f"WHERE type='index' AND name IN ({placeholders})",
            tuple(DEPRECATED_INDEXES),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            try:
                await cursor.close()
            except Exception:
                pass
        existing = {row[0] for row in rows}
        for idx_name in existing:
            if not _is_valid_index_name(idx_name):
                continue
            try:
                await conn.execute(f"DROP INDEX IF EXISTS {idx_name}")
                dropped += 1
            except Exception as e:
                logger.warning(f"⚠️ SQLite فشل حذف {idx_name}: {e}")
        if dropped > 0:
            logger.info(f"🧹 SQLite: حُذف {dropped} فهرس قديم")
    except Exception as e:
        logger.warning(f"⚠️ _drop_deprecated_indexes_sqlite: {e}")
    return dropped


async def _drop_deprecated_indexes_mysql(conn, logger):
    if not DEPRECATED_INDEXES:
        return 0
    dropped = 0
    try:
        tables = set(t for t, _, _ in COMMON_INDEXES)
        existing = await _fetch_existing_indexes_mysql(conn, tables)
        for table, idx_name in existing:
            if idx_name in DEPRECATED_INDEXES:
                if not _is_valid_index_name(idx_name):
                    continue
                if not _is_valid_index_name(table):
                    continue
                try:
                    await conn.execute(
                        f"DROP INDEX {idx_name} ON `{table}`"
                    )
                    dropped += 1
                except Exception as e:
                    err_msg = str(e).lower()
                    if "1091" not in err_msg and "doesn't exist" not in err_msg:
                        logger.warning(
                            f"⚠️ MySQL فشل حذف {idx_name}: {e}"
                        )
        if dropped > 0:
            logger.info(f"🧹 MySQL: حُذف {dropped} فهرس قديم")
    except Exception as e:
        logger.warning(f"⚠️ _drop_deprecated_indexes_mysql: {e}")
    return dropped


# =====================================================================
# إنشاء الفهارس
# =====================================================================

async def _create_indexes_generic(
    conn, logger, db_name: str, fetch_existing_fn, db_type: str
):
    try:
        existing = await fetch_existing_fn(conn)
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ {db_name} فشل جلب الفهارس: {e}")
        return

    to_create = []
    for t, n, c in COMMON_INDEXES:
        if n in existing:
            continue
        adapted = _adapt_cols_for_db(c, db_type)
        if not adapted:
            continue
        to_create.append((t, n, adapted))

    if not to_create:
        if logger:
            logger.info(
                f"✅ {db_name}: 0 فهرس جديد، "
                f"{len(COMMON_INDEXES)} موجود، 0 فشل"
            )
        return

    created = 0
    failed = 0
    for _table, idx_name, cols in to_create:
        if not _is_valid_index_name(idx_name):
            failed += 1
            continue
        try:
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS {idx_name} ON {cols}"
            )
            created += 1
        except Exception as e:
            failed += 1
            if logger:
                logger.warning(f"⚠️ {db_name} فهرس {idx_name}: {e}")

    skipped = len(COMMON_INDEXES) - len(to_create)
    if logger:
        logger.info(
            f"✅ {db_name}: {created} فهرس جديد، "
            f"{skipped} موجود، {failed} فشل"
        )


async def _create_indexes_sqlite(conn, logger):
    async def _fetch(c):
        return await _fetch_existing_indexes_sqlite(c)
    await _create_indexes_generic(
        conn, logger, "SQLite", _fetch, "sqlite"
    )


async def _create_indexes_postgres(conn, logger):
    index_names = [idx_name for _, idx_name, _ in COMMON_INDEXES]

    async def _fetch(c):
        return await _fetch_existing_indexes_postgres(c, index_names)

    await _create_indexes_generic(
        conn, logger, "PostgreSQL", _fetch, "postgres"
    )


async def _create_indexes_mysql(conn, logger):
    tables = set(t for t, _, _ in COMMON_INDEXES)
    try:
        existing = await _fetch_existing_indexes_mysql(conn, tables)
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ MySQL فشل جلب الفهارس: {e}")
        return

    created = 0
    skipped = 0
    failed = 0
    for table, idx_name, cols in COMMON_INDEXES:
        if idx_name in MYSQL_SKIP_INDEXES:
            skipped += 1
            continue
        if (table, idx_name) in existing:
            skipped += 1
            continue
        if not _is_valid_index_name(idx_name):
            failed += 1
            continue
        adapted = _adapt_cols_for_db(cols, "mysql")
        if not adapted:
            failed += 1
            continue
        try:
            await conn.execute(
                f"CREATE INDEX {idx_name} ON {adapted}"
            )
            created += 1
        except Exception as e:
            err_msg = str(e).lower()
            if (
                "duplicate" in err_msg
                or "already exists" in err_msg
                or "1061" in err_msg
            ):
                skipped += 1
            else:
                failed += 1
                if logger:
                    logger.warning(f"⚠️ MySQL فهرس {idx_name}: {e}")

    if logger:
        logger.info(
            f"✅ MySQL: {created} فهرس جديد، "
            f"{skipped} موجود، {failed} فشل"
        )


# =====================================================================
# 1. جداول SQLite
# =====================================================================

async def create_tables_sqlite(conn, logger, TimeUtils):
    current = await _get_current_schema_version_sqlite(conn)
    if current >= CURRENT_SCHEMA_VERSION:
        await _verify_critical_indexes_sqlite(conn, logger)
        await _ensure_all_indexes_exist_sqlite(conn, logger)
        await _drop_deprecated_indexes_sqlite(conn, logger)
        await _cleanup_stale_links_sqlite(conn, logger)
        await _cleanup_old_admin_logs_sqlite(conn, logger)
        await _migrate_missing_columns_sqlite(conn, logger)
        await _run_maintenance_sqlite(conn, logger)
        if logger:
            logger.info(
                f"⏩ SQLite: schema v{current} محدّث — تخطي (fast-path)"
            )
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            language TEXT DEFAULT 'ar',
            auto_publish INTEGER DEFAULT 1,
            auto_recycle INTEGER DEFAULT 1,
            banned INTEGER DEFAULT 0,
            trial_used INTEGER DEFAULT 0,
            subscription_end TEXT,
            referral_code TEXT UNIQUE,
            created_at TEXT,
            updated_at TEXT,
            active_channel INTEGER
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id INTEGER,
            channel_name TEXT,
            banned INTEGER DEFAULT 0,
            created_at TEXT,
            UNIQUE(user_id, channel_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_db_id INTEGER,
            text TEXT,
            text_hash TEXT,
            media_type TEXT,
            media_file_id TEXT,
            published INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            created_at TEXT,
            published_at TEXT,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id)
                ON DELETE CASCADE
        )
    """)
    try:
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_unique
            ON posts(
                channel_db_id,
                text_hash,
                COALESCE(media_type, ''),
                COALESCE(media_file_id, '')
            )
        """)
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ SQLite idx_posts_unique: {e}")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            channel_db_id INTEGER PRIMARY KEY,
            schedule_type TEXT DEFAULT 'interval_minutes',
            interval_minutes INTEGER DEFAULT 12,
            interval_hours INTEGER DEFAULT 0,
            interval_days INTEGER DEFAULT 0,
            days_of_week TEXT DEFAULT '[]',
            specific_dates TEXT DEFAULT '[]',
            publish_time TEXT DEFAULT '00:00',
            cron_expression TEXT,
            next_publish_date TEXT,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id)
                ON DELETE CASCADE
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS last_publish (
            channel_db_id INTEGER PRIMARY KEY,
            last_publish_time TEXT,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id)
                ON DELETE CASCADE
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_groups (
            chat_id INTEGER PRIMARY KEY,
            chat_name TEXT,
            username TEXT,
            added_by INTEGER,
            added_at TEXT,
            updated_at TEXT,
            banned INTEGER DEFAULT 0,
            log_channel_id INTEGER DEFAULT NULL
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_locks (
            chat_id INTEGER PRIMARY KEY,
            locked INTEGER DEFAULT 0,
            locked_at TEXT,
            locked_by INTEGER
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_groups_link (
            user_id INTEGER,
            chat_id INTEGER,
            PRIMARY KEY (user_id, chat_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_admins (
            chat_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS hidden_owner_groups (
            chat_id INTEGER,
            owner_id INTEGER,
            is_hidden INTEGER DEFAULT 1,
            PRIMARY KEY (chat_id, owner_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS hidden_admins (
            chat_id INTEGER,
            admin_id INTEGER,
            added_by INTEGER,
            added_at TEXT,
            PRIMARY KEY (chat_id, admin_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS anonymous_admins (
            chat_id INTEGER NOT NULL,
            anonymous_id INTEGER NOT NULL,
            added_by INTEGER,
            user_id INTEGER,
            added_at TEXT,
            PRIMARY KEY (chat_id, anonymous_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_security (
            chat_id INTEGER PRIMARY KEY,
            delete_links INTEGER DEFAULT 0,
            mentions INTEGER DEFAULT 0,
            slow_mode INTEGER DEFAULT 0,
            slow_mode_seconds INTEGER DEFAULT 5,
            welcome_enabled INTEGER DEFAULT 0,
            welcome_text TEXT DEFAULT 'مرحباً {user} في {chat} 🤍',
            goodbye_enabled INTEGER DEFAULT 0,
            goodbye_text TEXT DEFAULT 'وداعاً {user} 👋',
            delete_banned_words INTEGER DEFAULT 0,
            auto_penalty TEXT DEFAULT 'none',
            auto_mute_duration INTEGER DEFAULT 3600,
            delete_videos INTEGER DEFAULT 0,
            delete_audio INTEGER DEFAULT 0,
            delete_animation INTEGER DEFAULT 0,
            delete_service INTEGER DEFAULT 0,
            delete_documents INTEGER DEFAULT 0,
            delete_stickers INTEGER DEFAULT 0,
            delete_forwarded INTEGER DEFAULT 0,
            delete_polls INTEGER DEFAULT 0,
            delete_games INTEGER DEFAULT 0,
            delete_voice INTEGER DEFAULT 0,
            delete_video_note INTEGER DEFAULT 0,
            delete_photos INTEGER DEFAULT 0,
            delete_penalty TEXT DEFAULT 'none',
            delete_penalty_duration INTEGER DEFAULT 0,
            delete_penalty_messages INTEGER DEFAULT 0,
            antiflood_enabled INTEGER DEFAULT 0,
            antiflood_messages INTEGER DEFAULT 5,
            antiflood_seconds INTEGER DEFAULT 10,
            antiflood_penalty TEXT DEFAULT 'mute',
            antiflood_penalty_duration INTEGER DEFAULT 3600,
            max_warnings INTEGER DEFAULT 3,
            warn_penalty TEXT DEFAULT 'ban',
            warn_penalty_duration INTEGER DEFAULT 3600,
            warn_enabled INTEGER DEFAULT 0,
            max_message_length INTEGER DEFAULT 0,
            night_mode_enabled INTEGER DEFAULT 0,
            night_mode_start TEXT DEFAULT '23:00',
            night_mode_end TEXT DEFAULT '06:00',
            night_mode_action TEXT DEFAULT 'mute',
            night_mode_action_duration INTEGER DEFAULT 3600,
            nsfw_enabled INTEGER DEFAULT 0,
            nsfw_threshold REAL DEFAULT 0.7,
            nsfw_filter INTEGER DEFAULT 0,
            auto_approve_join INTEGER DEFAULT 0,
            auto_reject_join INTEGER DEFAULT 0,
            mute_default_duration INTEGER DEFAULT 3600,
            ban_default_duration INTEGER DEFAULT 0,
            warn_default_duration INTEGER DEFAULT 0,
            restrict_default_duration INTEGER DEFAULT 1800,
            enable_timed_penalties INTEGER DEFAULT 1,
            auto_remove_penalties INTEGER DEFAULT 1,
            violation_strikes INTEGER DEFAULT 3,
            violation_duration INTEGER DEFAULT 60,
            violation_penalty TEXT DEFAULT 'none',
            violation_penalty_duration INTEGER DEFAULT 3600
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS banned_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT,
            chat_id INTEGER,
            added_by INTEGER,
            added_at TEXT,
            UNIQUE(word, chat_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS auto_replies (
            chat_id INTEGER,
            keyword TEXT,
            reply TEXT,
            reply_type TEXT DEFAULT 'text',
            reply_media_id TEXT,
            reply_buttons TEXT,
            created_at TEXT,
            is_active INTEGER DEFAULT 1,
            usage_count INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, keyword)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS auto_reply_settings (
            chat_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            only_admins INTEGER DEFAULT 0,
            ignore_bots INTEGER DEFAULT 1,
            updated_at TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            message TEXT,
            media_type TEXT,
            media_file_id TEXT,
            ticket_number INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            replied INTEGER DEFAULT 0
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id INTEGER PRIMARY KEY,
            added_by INTEGER,
            added_at TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    for key, value in DEFAULT_SETTINGS:
        try:
            await conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO NOTHING",
                (key, value),
            )
        except Exception as e:
            if logger:
                logger.warning(f"⚠️ SQLite settings '{key}': {e}")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            created_at TEXT,
            UNIQUE(referrer_id, referred_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS referral_rewards (
            user_id INTEGER PRIMARY KEY,
            referral_count INTEGER DEFAULT 0,
            total_reward_days INTEGER DEFAULT 0,
            claimed_reward_days INTEGER DEFAULT 0,
            last_referral_date TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_reminder_settings (
            user_id INTEGER PRIMARY KEY,
            subscription_reminder INTEGER DEFAULT 1,
            daily_stats_reminder INTEGER DEFAULT 0,
            weekly_report INTEGER DEFAULT 1,
            reminder_days_before INTEGER DEFAULT 3,
            last_daily_sent TEXT,
            last_weekly_sent TEXT,
            last_subscription_sent TEXT,
            last_reminder_sent TEXT,
            notification_lang TEXT DEFAULT 'ar'
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_translation (
            user_id INTEGER PRIMARY KEY,
            lang TEXT DEFAULT 'off'
        )
    """)

    # ✅ v7.6.22: contests — مع question/correct_answer (للتركيبات الجديدة)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS contests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            title TEXT,
            description TEXT,
            prize TEXT,
            end_date TEXT,
            status TEXT DEFAULT 'active',
            winner_id INTEGER,
            created_at TEXT,
            contest_type TEXT DEFAULT 'raffle',
            question TEXT DEFAULT '',
            correct_answer TEXT DEFAULT ''
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS contest_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            contest_id INTEGER,
            answer TEXT,
            joined_at TEXT,
            UNIQUE(user_id, contest_id)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS contest_winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contest_id INTEGER,
            winner_id INTEGER,
            announced_at TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            admin_id INTEGER,
            action TEXT,
            target_id INTEGER,
            reason TEXT,
            created_at TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_warnings (
            user_id INTEGER,
            chat_id INTEGER,
            warnings INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, chat_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_violations (
            user_id INTEGER,
            chat_id INTEGER,
            violation_count INTEGER DEFAULT 0,
            last_violation_time TEXT,
            PRIMARY KEY (user_id, chat_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_rules (
            chat_id INTEGER PRIMARY KEY,
            rules_text TEXT,
            updated_by INTEGER,
            updated_at TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_messages (
            user_id INTEGER,
            chat_id INTEGER,
            message_time TEXT,
            PRIMARY KEY (user_id, chat_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            text TEXT,
            publish_time TEXT,
            fail_count INTEGER DEFAULT 0
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            text_encrypted BLOB,
            sentiment TEXT,
            score REAL,
            created_at TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            description TEXT,
            price INTEGER,
            currency TEXT DEFAULT 'XTR',
            duration_days INTEGER,
            max_channels INTEGER,
            max_posts INTEGER,
            features TEXT CHECK(features IS NULL OR json_valid(features)),
            is_active INTEGER DEFAULT 1,
            is_gift INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            plan_id INTEGER,
            status TEXT DEFAULT 'active',
            start_date TEXT,
            end_date TEXT,
            auto_renew INTEGER DEFAULT 0,
            provider TEXT DEFAULT 'xtr',
            provider_subscription_id TEXT,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
                ON DELETE CASCADE,
            FOREIGN KEY (plan_id) REFERENCES plans(id)
                ON DELETE RESTRICT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT UNIQUE,
            user_id INTEGER,
            plan_id INTEGER,
            amount INTEGER,
            currency TEXT DEFAULT 'XTR',
            status TEXT DEFAULT 'pending',
            provider TEXT DEFAULT 'xtr',
            provider_payment_id TEXT,
            paid_at TEXT,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
                ON DELETE CASCADE,
            FOREIGN KEY (plan_id) REFERENCES plans(id)
                ON DELETE RESTRICT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS payment_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            provider TEXT DEFAULT 'xtr',
            event_type TEXT,
            data TEXT,
            created_at TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_penalties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            penalty_type TEXT,
            duration INTEGER,
            start_time TEXT,
            end_time TEXT,
            reason TEXT,
            issued_by INTEGER,
            status TEXT DEFAULT 'active',
            created_at TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS violation_penalties (
            chat_id INTEGER NOT NULL,
            violation_type TEXT NOT NULL,
            penalty_type TEXT NOT NULL DEFAULT 'mute',
            duration_seconds INTEGER DEFAULT 3600,
            PRIMARY KEY (chat_id, violation_type)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS gift_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            plan_id INTEGER,
            creator_id INTEGER,
            used_by INTEGER,
            used_at TEXT,
            created_at TEXT,
            FOREIGN KEY (plan_id) REFERENCES plans(id)
                ON DELETE RESTRICT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_points (
            user_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 0,
            last_updated TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
                ON DELETE CASCADE
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS penalty_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            penalty_type TEXT,
            duration INTEGER,
            start_time TEXT,
            end_time TEXT,
            reason TEXT,
            issued_by INTEGER,
            status TEXT,
            created_at TEXT,
            archived_at TEXT
        )
    """)

    await _drop_deprecated_indexes_sqlite(conn, logger)
    await _ensure_index_definitions_match_sqlite(conn, logger)
    await _create_indexes_sqlite(conn, logger)
    await _cleanup_stale_links_sqlite(conn, logger)
    await _cleanup_old_admin_logs_sqlite(conn, logger)
    await _migrate_missing_columns_sqlite(conn, logger)

    try:
        await conn.execute(
            "INSERT INTO schema_version "
            "(version, applied_at, description) "
            "VALUES (?, ?, ?) ON CONFLICT(version) DO NOTHING",
            (CURRENT_SCHEMA_VERSION, _safe_now_iso(TimeUtils),
             "v7.6.22-contest-quiz-columns"),
        )
        await conn.commit()
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ schema_version SQLite: {e}")

    if logger:
        logger.info("✅ تم إنشاء جميع جداول SQLite مع الفهارس المحسنة")


# =====================================================================
# 2. جداول PostgreSQL
# =====================================================================

async def create_tables_postgres(conn, logger, TimeUtils):
    current = await _get_current_schema_version_postgres(conn)
    if current >= CURRENT_SCHEMA_VERSION:
        if logger:
            logger.info(
                f"⏩ PG fast-path: schema v{current} — بدء الفحوصات"
            )
        await _verify_critical_indexes_postgres(conn, logger)
        await _ensure_all_indexes_exist_postgres(conn, logger)
        await _ensure_index_definitions_match_postgres(conn, logger)
        await _drop_deprecated_indexes_postgres(conn, logger)
        await _cleanup_stale_links_postgres(conn, logger)
        await _cleanup_old_admin_logs_postgres(conn, logger)
        await _tune_autovacuum_postgres(conn, logger)
        await _migrate_missing_columns_postgres(conn, logger)
        await _quick_analyze_postgres(conn, logger)
        await _run_maintenance_postgres(conn, logger)
        if logger:
            logger.info(
                f"⏩ PG: schema v{current} محدّث — تخطي (fast-path)"
            )
        return

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL,
            description TEXT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            language TEXT DEFAULT 'ar',
            auto_publish INTEGER DEFAULT 1,
            auto_recycle INTEGER DEFAULT 1,
            banned INTEGER DEFAULT 0,
            trial_used INTEGER DEFAULT 0,
            subscription_end TIMESTAMP,
            referral_code TEXT UNIQUE,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            active_channel INTEGER
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_channels (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            channel_id BIGINT,
            channel_name TEXT,
            banned INTEGER DEFAULT 0,
            created_at TIMESTAMP,
            UNIQUE(user_id, channel_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id SERIAL PRIMARY KEY,
            channel_db_id INTEGER,
            text TEXT,
            text_hash TEXT,
            media_type TEXT,
            media_file_id TEXT,
            published INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            created_at TIMESTAMP,
            published_at TIMESTAMP,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id)
                ON DELETE CASCADE
        )
    """)
    try:
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_unique
            ON posts(
                channel_db_id,
                text_hash,
                COALESCE(media_type, ''),
                COALESCE(media_file_id, '')
            )
        """)
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ PG idx_posts_unique: {e}")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            channel_db_id INTEGER PRIMARY KEY,
            schedule_type TEXT DEFAULT 'interval_minutes',
            interval_minutes INTEGER DEFAULT 12,
            interval_hours INTEGER DEFAULT 0,
            interval_days INTEGER DEFAULT 0,
            days_of_week TEXT DEFAULT '[]',
            specific_dates TEXT DEFAULT '[]',
            publish_time TEXT DEFAULT '00:00',
            cron_expression TEXT,
            next_publish_date TIMESTAMP,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id)
                ON DELETE CASCADE
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS last_publish (
            channel_db_id INTEGER PRIMARY KEY,
            last_publish_time TIMESTAMP,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id)
                ON DELETE CASCADE
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_groups (
            chat_id BIGINT PRIMARY KEY,
            chat_name TEXT,
            username TEXT,
            added_by BIGINT,
            added_at TIMESTAMP,
            updated_at TIMESTAMP,
            banned INTEGER DEFAULT 0,
            log_channel_id BIGINT DEFAULT NULL
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_locks (
            chat_id BIGINT PRIMARY KEY,
            locked INTEGER DEFAULT 0,
            locked_at TIMESTAMP,
            locked_by BIGINT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_groups_link (
            user_id BIGINT,
            chat_id BIGINT,
            PRIMARY KEY (user_id, chat_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_admins (
            chat_id BIGINT,
            user_id BIGINT,
            PRIMARY KEY (chat_id, user_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS hidden_owner_groups (
            chat_id BIGINT,
            owner_id BIGINT,
            is_hidden INTEGER DEFAULT 1,
            PRIMARY KEY (chat_id, owner_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS hidden_admins (
            chat_id BIGINT,
            admin_id BIGINT,
            added_by BIGINT,
            added_at TIMESTAMP,
            PRIMARY KEY (chat_id, admin_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS anonymous_admins (
            chat_id BIGINT NOT NULL,
            anonymous_id BIGINT NOT NULL,
            added_by BIGINT,
            user_id BIGINT,
            added_at TIMESTAMP,
            PRIMARY KEY (chat_id, anonymous_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_security (
            chat_id BIGINT PRIMARY KEY,
            delete_links INTEGER DEFAULT 0,
            mentions INTEGER DEFAULT 0,
            slow_mode INTEGER DEFAULT 0,
            slow_mode_seconds INTEGER DEFAULT 5,
            welcome_enabled INTEGER DEFAULT 0,
            welcome_text TEXT DEFAULT 'مرحباً {user} في {chat} 🤍',
            goodbye_enabled INTEGER DEFAULT 0,
            goodbye_text TEXT DEFAULT 'وداعاً {user} 👋',
            delete_banned_words INTEGER DEFAULT 0,
            auto_penalty TEXT DEFAULT 'none',
            auto_mute_duration INTEGER DEFAULT 3600,
            delete_videos INTEGER DEFAULT 0,
            delete_audio INTEGER DEFAULT 0,
            delete_animation INTEGER DEFAULT 0,
            delete_service INTEGER DEFAULT 0,
            delete_documents INTEGER DEFAULT 0,
            delete_stickers INTEGER DEFAULT 0,
            delete_forwarded INTEGER DEFAULT 0,
            delete_polls INTEGER DEFAULT 0,
            delete_games INTEGER DEFAULT 0,
            delete_voice INTEGER DEFAULT 0,
            delete_video_note INTEGER DEFAULT 0,
            delete_photos INTEGER DEFAULT 0,
            delete_penalty TEXT DEFAULT 'none',
            delete_penalty_duration INTEGER DEFAULT 0,
            delete_penalty_messages INTEGER DEFAULT 0,
            antiflood_enabled INTEGER DEFAULT 0,
            antiflood_messages INTEGER DEFAULT 5,
            antiflood_seconds INTEGER DEFAULT 10,
            antiflood_penalty TEXT DEFAULT 'mute',
            antiflood_penalty_duration INTEGER DEFAULT 3600,
            max_warnings INTEGER DEFAULT 3,
            warn_penalty TEXT DEFAULT 'ban',
            warn_penalty_duration INTEGER DEFAULT 3600,
            warn_enabled INTEGER DEFAULT 0,
            max_message_length INTEGER DEFAULT 0,
            night_mode_enabled INTEGER DEFAULT 0,
            night_mode_start TEXT DEFAULT '23:00',
            night_mode_end TEXT DEFAULT '06:00',
            night_mode_action TEXT DEFAULT 'mute',
            night_mode_action_duration INTEGER DEFAULT 3600,
            nsfw_enabled INTEGER DEFAULT 0,
            nsfw_threshold REAL DEFAULT 0.7,
            nsfw_filter INTEGER DEFAULT 0,
            auto_approve_join INTEGER DEFAULT 0,
            auto_reject_join INTEGER DEFAULT 0,
            mute_default_duration INTEGER DEFAULT 3600,
            ban_default_duration INTEGER DEFAULT 0,
            warn_default_duration INTEGER DEFAULT 0,
            restrict_default_duration INTEGER DEFAULT 1800,
            enable_timed_penalties INTEGER DEFAULT 1,
            auto_remove_penalties INTEGER DEFAULT 1,
            violation_strikes INTEGER DEFAULT 3,
            violation_duration INTEGER DEFAULT 60,
            violation_penalty TEXT DEFAULT 'none',
            violation_penalty_duration INTEGER DEFAULT 3600
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS banned_words (
            id SERIAL PRIMARY KEY,
            word TEXT,
            chat_id BIGINT,
            added_by BIGINT,
            added_at TIMESTAMP,
            UNIQUE(word, chat_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS auto_replies (
            chat_id BIGINT,
            keyword TEXT,
            reply TEXT,
            reply_type TEXT DEFAULT 'text',
            reply_media_id TEXT,
            reply_buttons TEXT,
            created_at TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            usage_count INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, keyword)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS auto_reply_settings (
            chat_id BIGINT PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            only_admins INTEGER DEFAULT 0,
            ignore_bots INTEGER DEFAULT 1,
            updated_at TIMESTAMP
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            username TEXT,
            message TEXT,
            media_type TEXT,
            media_file_id TEXT,
            ticket_number INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP,
            replied INTEGER DEFAULT 0
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id BIGINT PRIMARY KEY,
            added_by BIGINT,
            added_at TIMESTAMP
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    for key, value in DEFAULT_SETTINGS:
        try:
            await conn.execute(
                "INSERT INTO settings (key, value) VALUES ($1, $2) "
                "ON CONFLICT (key) DO NOTHING",
                key, value,
            )
        except Exception as e:
            if logger:
                logger.warning(f"⚠️ PG settings '{key}': {e}")

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id SERIAL PRIMARY KEY,
            referrer_id BIGINT,
            referred_id BIGINT,
            created_at TIMESTAMP,
            UNIQUE(referrer_id, referred_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS referral_rewards (
            user_id BIGINT PRIMARY KEY,
            referral_count INTEGER DEFAULT 0,
            total_reward_days INTEGER DEFAULT 0,
            claimed_reward_days INTEGER DEFAULT 0,
            last_referral_date TIMESTAMP
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_reminder_settings (
            user_id BIGINT PRIMARY KEY,
            subscription_reminder INTEGER DEFAULT 1,
            daily_stats_reminder INTEGER DEFAULT 0,
            weekly_report INTEGER DEFAULT 1,
            reminder_days_before INTEGER DEFAULT 3,
            last_daily_sent TIMESTAMP,
            last_weekly_sent TIMESTAMP,
            last_subscription_sent TIMESTAMP,
            last_reminder_sent TIMESTAMP,
            notification_lang TEXT DEFAULT 'ar'
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_translation (
            user_id BIGINT PRIMARY KEY,
            lang TEXT DEFAULT 'off'
        )
    """)

    # ✅ v7.6.22: contests — مع question/correct_answer (للتركيبات الجديدة)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS contests (
            id SERIAL PRIMARY KEY,
            creator_id BIGINT,
            title TEXT,
            description TEXT,
            prize TEXT,
            end_date TIMESTAMP,
            status TEXT DEFAULT 'active',
            winner_id BIGINT,
            created_at TIMESTAMP,
            contest_type TEXT DEFAULT 'raffle',
            question TEXT DEFAULT '',
            correct_answer TEXT DEFAULT ''
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS contest_participants (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            contest_id INTEGER,
            answer TEXT,
            joined_at TIMESTAMP,
            UNIQUE(user_id, contest_id)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS contest_winners (
            id SERIAL PRIMARY KEY,
            contest_id INTEGER,
            winner_id BIGINT,
            announced_at TIMESTAMP
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_logs (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT,
            admin_id BIGINT,
            action TEXT,
            target_id BIGINT,
            reason TEXT,
            created_at TIMESTAMP
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_warnings (
            user_id BIGINT,
            chat_id BIGINT,
            warnings INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, chat_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_violations (
            user_id BIGINT,
            chat_id BIGINT,
            violation_count INTEGER DEFAULT 0,
            last_violation_time TIMESTAMP,
            PRIMARY KEY (user_id, chat_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_rules (
            chat_id BIGINT PRIMARY KEY,
            rules_text TEXT,
            updated_by BIGINT,
            updated_at TIMESTAMP
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_messages (
            user_id BIGINT,
            chat_id BIGINT,
            message_time TIMESTAMP,
            PRIMARY KEY (user_id, chat_id)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT,
            text TEXT,
            publish_time TIMESTAMP,
            fail_count INTEGER DEFAULT 0
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_history (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            chat_id BIGINT,
            text_encrypted BYTEA,
            sentiment TEXT,
            score REAL,
            created_at TIMESTAMP
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE,
            description TEXT,
            price INTEGER,
            currency TEXT DEFAULT 'XTR',
            duration_days INTEGER,
            max_channels INTEGER,
            max_posts INTEGER,
            features TEXT CHECK (
                features IS NULL
                OR features = ''
                OR features ~ '^\\s*[\\{\\[]'
            ),
            is_active INTEGER DEFAULT 1,
            is_gift INTEGER DEFAULT 0,
            created_at TIMESTAMP
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            plan_id INTEGER,
            status TEXT DEFAULT 'active',
            start_date TIMESTAMP,
            end_date TIMESTAMP,
            auto_renew INTEGER DEFAULT 0,
            provider TEXT DEFAULT 'xtr',
            provider_subscription_id TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
                ON DELETE CASCADE,
            FOREIGN KEY (plan_id) REFERENCES plans(id)
                ON DELETE RESTRICT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id SERIAL PRIMARY KEY,
            number TEXT UNIQUE,
            user_id BIGINT,
            plan_id INTEGER,
            amount INTEGER,
            currency TEXT DEFAULT 'XTR',
            status TEXT DEFAULT 'pending',
            provider TEXT DEFAULT 'xtr',
            provider_payment_id TEXT,
            paid_at TIMESTAMP,
            created_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
                ON DELETE CASCADE,
            FOREIGN KEY (plan_id) REFERENCES plans(id)
                ON DELETE RESTRICT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS payment_logs (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            provider TEXT DEFAULT 'xtr',
            event_type TEXT,
            data TEXT,
            created_at TIMESTAMP
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_penalties (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            chat_id BIGINT,
            penalty_type TEXT,
            duration INTEGER,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            reason TEXT,
            issued_by BIGINT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS violation_penalties (
            chat_id BIGINT NOT NULL,
            violation_type TEXT NOT NULL,
            penalty_type TEXT NOT NULL DEFAULT 'mute',
            duration_seconds INTEGER DEFAULT 3600,
            PRIMARY KEY (chat_id, violation_type)
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS gift_codes (
            id SERIAL PRIMARY KEY,
            code TEXT UNIQUE,
            plan_id INTEGER,
            creator_id BIGINT,
            used_by BIGINT,
            used_at TIMESTAMP,
            created_at TIMESTAMP,
            FOREIGN KEY (plan_id) REFERENCES plans(id)
                ON DELETE RESTRICT
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_points (
            user_id BIGINT PRIMARY KEY,
            points INTEGER DEFAULT 0,
            last_updated TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
                ON DELETE CASCADE
        )
    """)

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS penalty_archive (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            chat_id BIGINT,
            penalty_type TEXT,
            duration INTEGER,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            reason TEXT,
            issued_by BIGINT,
            status TEXT,
            created_at TIMESTAMP,
            archived_at TIMESTAMP
        )
    """)

    await _drop_deprecated_indexes_postgres(conn, logger)
    await _ensure_index_definitions_match_postgres(conn, logger)
    await _create_indexes_postgres(conn, logger)
    await _cleanup_stale_links_postgres(conn, logger)
    await _cleanup_old_admin_logs_postgres(conn, logger)
    await _tune_autovacuum_postgres(conn, logger)
    await _migrate_missing_columns_postgres(conn, logger)
    await _quick_analyze_postgres(conn, logger)

    try:
        await conn.execute(
            "INSERT INTO schema_version "
            "(version, applied_at, description) "
            "VALUES ($1, $2, $3) ON CONFLICT (version) DO NOTHING",
            CURRENT_SCHEMA_VERSION,
            _safe_now_dt(TimeUtils),
            "v7.6.22-contest-quiz-columns",
        )
    except Exception as e:
        if logger:
            logger.warning(f"⚠️ schema_version PG: {e}")

    if logger:
        logger.info("✅ تم إنشاء جميع جداول PostgreSQL مع الفهارس المحسنة")


# =====================================================================
# 3. جداول MySQL
# =====================================================================

async def create_tables_mysql(conn, logger, TimeUtils):
    current = await _get_current_schema_version_mysql(conn)
    if current >= CURRENT_SCHEMA_VERSION:
        await _verify_critical_indexes_mysql(conn, logger)
        await _ensure_all_indexes_exist_mysql(conn, logger)
        await _ensure_index_definitions_match_mysql(conn, logger)
        await _drop_deprecated_indexes_mysql(conn, logger)
        await _cleanup_stale_links_mysql(conn, logger)
        await _cleanup_old_admin_logs_mysql(conn, logger)
        await _migrate_missing_columns_mysql(conn, logger)
        await _quick_analyze_mysql(conn, logger)
        await _run_maintenance_mysql(conn, logger)
        if logger:
            logger.info(
                f"⏩ MySQL: schema v{current} محدّث — تخطي (fast-path)"
            )
        return

    await conn.execute("SET FOREIGN_KEY_CHECKS=0")
    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INT PRIMARY KEY,
                applied_at DATETIME NOT NULL,
                description TEXT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                language VARCHAR(10) DEFAULT 'ar',
                auto_publish TINYINT(1) DEFAULT 1,
                auto_recycle TINYINT(1) DEFAULT 1,
                banned TINYINT(1) DEFAULT 0,
                trial_used TINYINT(1) DEFAULT 0,
                subscription_end DATETIME,
                referral_code VARCHAR(255) UNIQUE,
                created_at DATETIME,
                updated_at DATETIME,
                active_channel INT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_channels (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id BIGINT,
                channel_id BIGINT,
                channel_name VARCHAR(255),
                banned TINYINT(1) DEFAULT 0,
                created_at DATETIME,
                UNIQUE KEY (user_id, channel_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INT PRIMARY KEY AUTO_INCREMENT,
                channel_db_id INT,
                text TEXT NOT NULL,
                text_hash CHAR(64) DEFAULT '',
                media_type VARCHAR(50),
                media_file_id VARCHAR(255),
                published TINYINT(1) DEFAULT 0,
                fail_count INT DEFAULT 0,
                created_at DATETIME,
                published_at DATETIME,
                FOREIGN KEY (channel_db_id)
                    REFERENCES user_channels(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        try:
            await conn.execute("""
                CREATE UNIQUE INDEX idx_posts_unique
                ON posts(
                    channel_db_id,
                    text_hash,
                    (COALESCE(media_type, '')),
                    (COALESCE(media_file_id, ''))
                )
            """)
        except Exception as e:
            err_msg = str(e).lower()
            if (
                "duplicate" not in err_msg
                and "1061" not in err_msg
                and "already exists" not in err_msg
            ):
                if logger:
                    logger.warning(f"⚠️ MySQL idx_posts_unique: {e}")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schedule (
                channel_db_id INT PRIMARY KEY,
                schedule_type VARCHAR(50) DEFAULT 'interval_minutes',
                interval_minutes INT DEFAULT 12,
                interval_hours INT DEFAULT 0,
                interval_days INT DEFAULT 0,
                days_of_week TEXT,
                specific_dates TEXT,
                publish_time VARCHAR(10) DEFAULT '00:00',
                cron_expression TEXT,
                next_publish_date DATETIME,
                FOREIGN KEY (channel_db_id)
                    REFERENCES user_channels(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS last_publish (
                channel_db_id INT PRIMARY KEY,
                last_publish_time DATETIME,
                FOREIGN KEY (channel_db_id)
                    REFERENCES user_channels(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_groups (
                chat_id BIGINT PRIMARY KEY,
                chat_name VARCHAR(255),
                username VARCHAR(255),
                added_by BIGINT,
                added_at DATETIME,
                updated_at DATETIME,
                banned TINYINT(1) DEFAULT 0,
                log_channel_id BIGINT DEFAULT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_locks (
                chat_id BIGINT PRIMARY KEY,
                locked TINYINT(1) DEFAULT 0,
                locked_at DATETIME,
                locked_by BIGINT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_groups_link (
                user_id BIGINT,
                chat_id BIGINT,
                PRIMARY KEY (user_id, chat_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_admins (
                chat_id BIGINT,
                user_id BIGINT,
                PRIMARY KEY (chat_id, user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hidden_owner_groups (
                chat_id BIGINT,
                owner_id BIGINT,
                is_hidden TINYINT(1) DEFAULT 1,
                PRIMARY KEY (chat_id, owner_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hidden_admins (
                chat_id BIGINT,
                admin_id BIGINT,
                added_by BIGINT,
                added_at DATETIME,
                PRIMARY KEY (chat_id, admin_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS anonymous_admins (
                chat_id BIGINT NOT NULL,
                anonymous_id BIGINT NOT NULL,
                added_by BIGINT,
                user_id BIGINT,
                added_at DATETIME,
                PRIMARY KEY (chat_id, anonymous_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_security (
                chat_id BIGINT PRIMARY KEY,
                delete_links TINYINT(1) DEFAULT 0,
                mentions TINYINT(1) DEFAULT 0,
                slow_mode TINYINT(1) DEFAULT 0,
                slow_mode_seconds INT DEFAULT 5,
                welcome_enabled TINYINT(1) DEFAULT 0,
                welcome_text VARCHAR(2000)
                    DEFAULT 'مرحباً {user} في {chat} 🤍',
                goodbye_enabled TINYINT(1) DEFAULT 0,
                goodbye_text VARCHAR(2000)
                    DEFAULT 'وداعاً {user} 👋',
                delete_banned_words TINYINT(1) DEFAULT 0,
                auto_penalty VARCHAR(50) DEFAULT 'none',
                auto_mute_duration INT DEFAULT 3600,
                delete_videos TINYINT(1) DEFAULT 0,
                delete_audio TINYINT(1) DEFAULT 0,
                delete_animation TINYINT(1) DEFAULT 0,
                delete_service TINYINT(1) DEFAULT 0,
                delete_documents TINYINT(1) DEFAULT 0,
                delete_stickers TINYINT(1) DEFAULT 0,
                delete_forwarded TINYINT(1) DEFAULT 0,
                delete_polls TINYINT(1) DEFAULT 0,
                delete_games TINYINT(1) DEFAULT 0,
                delete_voice TINYINT(1) DEFAULT 0,
                delete_video_note TINYINT(1) DEFAULT 0,
                delete_photos TINYINT(1) DEFAULT 0,
                delete_penalty VARCHAR(50) DEFAULT 'none',
                delete_penalty_duration INT DEFAULT 0,
                delete_penalty_messages INT DEFAULT 0,
                antiflood_enabled TINYINT(1) DEFAULT 0,
                antiflood_messages INT DEFAULT 5,
                antiflood_seconds INT DEFAULT 10,
                antiflood_penalty VARCHAR(50) DEFAULT 'mute',
                antiflood_penalty_duration INT DEFAULT 3600,
                max_warnings INT DEFAULT 3,
                warn_penalty VARCHAR(50) DEFAULT 'ban',
                warn_penalty_duration INT DEFAULT 3600,
                warn_enabled TINYINT(1) DEFAULT 0,
                max_message_length INT DEFAULT 0,
                night_mode_enabled TINYINT(1) DEFAULT 0,
                night_mode_start VARCHAR(10) DEFAULT '23:00',
                night_mode_end VARCHAR(10) DEFAULT '06:00',
                night_mode_action VARCHAR(50) DEFAULT 'mute',
                night_mode_action_duration INT DEFAULT 3600,
                nsfw_enabled TINYINT(1) DEFAULT 0,
                nsfw_threshold FLOAT DEFAULT 0.7,
                nsfw_filter TINYINT(1) DEFAULT 0,
                auto_approve_join TINYINT(1) DEFAULT 0,
                auto_reject_join TINYINT(1) DEFAULT 0,
                mute_default_duration INT DEFAULT 3600,
                ban_default_duration INT DEFAULT 0,
                warn_default_duration INT DEFAULT 0,
                restrict_default_duration INT DEFAULT 1800,
                enable_timed_penalties TINYINT(1) DEFAULT 1,
                auto_remove_penalties TINYINT(1) DEFAULT 1,
                violation_strikes INT DEFAULT 3,
                violation_duration INT DEFAULT 60,
                violation_penalty VARCHAR(50) DEFAULT 'none',
                violation_penalty_duration INT DEFAULT 3600
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS banned_words (
                id INT PRIMARY KEY AUTO_INCREMENT,
                word VARCHAR(255),
                chat_id BIGINT,
                added_by BIGINT,
                added_at DATETIME,
                UNIQUE KEY (word, chat_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS auto_replies (
                chat_id BIGINT,
                keyword VARCHAR(255),
                reply TEXT,
                reply_type VARCHAR(50) DEFAULT 'text',
                reply_media_id TEXT,
                reply_buttons TEXT,
                created_at DATETIME,
                is_active TINYINT(1) DEFAULT 1,
                usage_count INT DEFAULT 0,
                PRIMARY KEY (chat_id, keyword)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS auto_reply_settings (
                chat_id BIGINT PRIMARY KEY,
                enabled TINYINT(1) DEFAULT 0,
                only_admins TINYINT(1) DEFAULT 0,
                ignore_bots TINYINT(1) DEFAULT 1,
                updated_at DATETIME
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id BIGINT,
                username VARCHAR(255),
                message TEXT,
                media_type VARCHAR(50),
                media_file_id TEXT,
                ticket_number INT,
                status VARCHAR(50) DEFAULT 'pending',
                created_at DATETIME,
                replied TINYINT(1) DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id BIGINT PRIMARY KEY,
                added_by BIGINT,
                added_at DATETIME
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                `key` VARCHAR(255) PRIMARY KEY,
                `value` TEXT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        for key, value in DEFAULT_SETTINGS:
            try:
                await conn.execute(
                    "INSERT IGNORE INTO settings (`key`, `value`) "
                    "VALUES (%s, %s)",
                    (key, value),
                )
            except Exception as e:
                if logger:
                    logger.warning(f"⚠️ MySQL settings '{key}': {e}")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INT PRIMARY KEY AUTO_INCREMENT,
                referrer_id BIGINT,
                referred_id BIGINT,
                created_at DATETIME,
                UNIQUE KEY (referrer_id, referred_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referral_rewards (
                user_id BIGINT PRIMARY KEY,
                referral_count INT DEFAULT 0,
                total_reward_days INT DEFAULT 0,
                claimed_reward_days INT DEFAULT 0,
                last_referral_date DATETIME
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_reminder_settings (
                user_id BIGINT PRIMARY KEY,
                subscription_reminder TINYINT(1) DEFAULT 1,
                daily_stats_reminder TINYINT(1) DEFAULT 0,
                weekly_report TINYINT(1) DEFAULT 1,
                reminder_days_before INT DEFAULT 3,
                last_daily_sent DATETIME,
                last_weekly_sent DATETIME,
                last_subscription_sent DATETIME,
                last_reminder_sent DATETIME,
                notification_lang VARCHAR(10) DEFAULT 'ar'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_translation (
                user_id BIGINT PRIMARY KEY,
                lang VARCHAR(10) DEFAULT 'off'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # ✅ v7.6.22: contests — مع question/correct_answer (للتركيبات الجديدة)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contests (
                id INT PRIMARY KEY AUTO_INCREMENT,
                creator_id BIGINT,
                title VARCHAR(255),
                description TEXT,
                prize VARCHAR(255),
                end_date DATETIME,
                status VARCHAR(50) DEFAULT 'active',
                winner_id BIGINT,
                created_at DATETIME,
                contest_type VARCHAR(50) DEFAULT 'raffle',
                question TEXT,
                correct_answer TEXT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contest_participants (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id BIGINT,
                contest_id INT,
                answer TEXT,
                joined_at DATETIME,
                UNIQUE KEY (user_id, contest_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contest_winners (
                id INT PRIMARY KEY AUTO_INCREMENT,
                contest_id INT,
                winner_id BIGINT,
                announced_at DATETIME
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INT PRIMARY KEY AUTO_INCREMENT,
                chat_id BIGINT,
                admin_id BIGINT,
                action VARCHAR(255),
                target_id BIGINT,
                reason TEXT,
                created_at DATETIME
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_warnings (
                user_id BIGINT,
                chat_id BIGINT,
                warnings INT DEFAULT 0,
                PRIMARY KEY (user_id, chat_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_violations (
                user_id BIGINT,
                chat_id BIGINT,
                violation_count INT DEFAULT 0,
                last_violation_time DATETIME,
                PRIMARY KEY (user_id, chat_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_rules (
                chat_id BIGINT PRIMARY KEY,
                rules_text TEXT,
                updated_by BIGINT,
                updated_at DATETIME
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_messages (
                user_id BIGINT,
                chat_id BIGINT,
                message_time DATETIME,
                PRIMARY KEY (user_id, chat_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INT PRIMARY KEY AUTO_INCREMENT,
                chat_id BIGINT,
                text TEXT,
                publish_time DATETIME,
                fail_count INT DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sentiment_history (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id BIGINT,
                chat_id BIGINT,
                text_encrypted BLOB,
                sentiment VARCHAR(50),
                score FLOAT,
                created_at DATETIME
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id INT PRIMARY KEY AUTO_INCREMENT,
                name VARCHAR(100) UNIQUE,
                description TEXT,
                price INT,
                currency VARCHAR(10) DEFAULT 'XTR',
                duration_days INT,
                max_channels INT,
                max_posts INT,
                features TEXT,
                is_active TINYINT(1) DEFAULT 1,
                is_gift TINYINT(1) DEFAULT 0,
                created_at DATETIME
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id BIGINT,
                plan_id INT,
                status VARCHAR(50) DEFAULT 'active',
                start_date DATETIME,
                end_date DATETIME,
                auto_renew TINYINT(1) DEFAULT 0,
                provider VARCHAR(50) DEFAULT 'xtr',
                provider_subscription_id VARCHAR(255),
                created_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (plan_id) REFERENCES plans(id)
                    ON DELETE RESTRICT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INT PRIMARY KEY AUTO_INCREMENT,
                number VARCHAR(50) UNIQUE,
                user_id BIGINT,
                plan_id INT,
                amount INT,
                currency VARCHAR(10) DEFAULT 'XTR',
                status VARCHAR(50) DEFAULT 'pending',
                provider VARCHAR(50) DEFAULT 'xtr',
                provider_payment_id VARCHAR(255),
                paid_at DATETIME,
                created_at DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (plan_id) REFERENCES plans(id)
                    ON DELETE RESTRICT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS payment_logs (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id BIGINT,
                provider VARCHAR(50) DEFAULT 'xtr',
                event_type VARCHAR(100),
                data TEXT,
                created_at DATETIME
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_penalties (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id BIGINT,
                chat_id BIGINT,
                penalty_type VARCHAR(50),
                duration INT,
                start_time DATETIME,
                end_time DATETIME,
                reason TEXT,
                issued_by BIGINT,
                status VARCHAR(50) DEFAULT 'active',
                created_at DATETIME
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS violation_penalties (
                chat_id BIGINT NOT NULL,
                violation_type VARCHAR(50) NOT NULL,
                penalty_type VARCHAR(50) NOT NULL DEFAULT 'mute',
                duration_seconds INT DEFAULT 3600,
                PRIMARY KEY (chat_id, violation_type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS gift_codes (
                id INT PRIMARY KEY AUTO_INCREMENT,
                code VARCHAR(50) UNIQUE,
                plan_id INT,
                creator_id BIGINT,
                used_by BIGINT,
                used_at DATETIME,
                created_at DATETIME,
                FOREIGN KEY (plan_id) REFERENCES plans(id)
                    ON DELETE RESTRICT
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_points (
                user_id BIGINT PRIMARY KEY,
                points INT DEFAULT 0,
                last_updated DATETIME,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS penalty_archive (
                id INT PRIMARY KEY AUTO_INCREMENT,
                user_id BIGINT,
                chat_id BIGINT,
                penalty_type VARCHAR(50),
                duration INT,
                start_time DATETIME,
                end_time DATETIME,
                reason TEXT,
                issued_by BIGINT,
                status VARCHAR(50),
                created_at DATETIME,
                archived_at DATETIME
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        await _drop_deprecated_indexes_mysql(conn, logger)
        await _ensure_index_definitions_match_mysql(conn, logger)
        await _create_indexes_mysql(conn, logger)
        await _cleanup_stale_links_mysql(conn, logger)
        await _cleanup_old_admin_logs_mysql(conn, logger)
        await _migrate_missing_columns_mysql(conn, logger)
        await _quick_analyze_mysql(conn, logger)

        try:
            await conn.execute(
                "INSERT IGNORE INTO schema_version "
                "(version, applied_at, description) "
                "VALUES (%s, %s, %s)",
                (
                    CURRENT_SCHEMA_VERSION,
                    _safe_now_iso(TimeUtils),
                    "v7.6.22-contest-quiz-columns",
                ),
            )
        except Exception as e:
            if logger:
                logger.warning(f"⚠️ schema_version MySQL: {e}")

        if logger:
            logger.info("✅ تم إنشاء جميع جداول MySQL مع الفهارس المحسنة")

    finally:
        try:
            await conn.execute("SET FOREIGN_KEY_CHECKS=1")
        except Exception as e:
            if logger:
                logger.error(f"❌ فشل إعادة FOREIGN_KEY_CHECKS: {e}")


# =====================================================================
# تصدير
# =====================================================================

__all__ = [
    "create_tables_sqlite",
    "create_tables_postgres",
    "create_tables_mysql",
    "CURRENT_SCHEMA_VERSION",
    "CLEANUP_ANONYMOUS_BOT_IDS",
    "COMMON_INDEXES",
    "EXPECTED_INDEX_COUNT",
    "CRITICAL_INDEX_NAMES",
    "DEPRECATED_INDEXES",
    "DEFAULT_SETTINGS",
    "MAINTENANCE_INTERVAL_SECONDS",
    "MAINTENANCE_TABLES",
    "VACUUM_INTER_TABLE_DELAY_SECONDS",
    "MYSQL_SKIP_INDEXES",
    "ADMIN_LOGS_RETENTION_DAYS",
    "ADMIN_LOGS_MAX_ROWS",
    "SMALL_TABLES_FOR_AGGRESSIVE_AUTOVACUUM",
    "_adapt_cols_for_db",
]