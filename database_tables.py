#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
database_tables.py — إنشاء الجداول والفهارس لكل قواعد البيانات
================================================================================
هذا الملف مستقل تماماً عن database.py:
- لا يستورد من database.py (لتفادي circular imports)
- لا يستخدم أي شيء من الفئة Database
- يستقبل (conn, logger, TimeUtils) كمعاملات

يحتوي على:
    - create_tables_sqlite(conn, logger, TimeUtils)
    - create_tables_postgres(conn, logger, TimeUtils)
    - create_tables_mysql(conn, logger, TimeUtils)
"""


# =====================================================================
# 1. إنشاء جداول SQLite
# =====================================================================

async def create_tables_sqlite(conn, logger, TimeUtils):
    """إنشاء جميع جداول SQLite + الفهارس"""
    # ---------- USERS ----------
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
    # ---------- USER_CHANNELS ----------
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
    # ---------- POSTS ----------
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
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE,
            UNIQUE(channel_db_id, text_hash, media_type, media_file_id)
        )
    """)
    # ---------- SCHEDULE ----------
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
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
        )
    """)
    # ---------- LAST_PUBLISH ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS last_publish (
            channel_db_id INTEGER PRIMARY KEY,
            last_publish_time TEXT,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
        )
    """)
    # ---------- BOT_GROUPS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_groups (
            chat_id INTEGER PRIMARY KEY,
            chat_name TEXT,
            username TEXT,
            added_by INTEGER,
            added_at TEXT,
            updated_at TEXT,
            banned INTEGER DEFAULT 0
        )
    """)
    # ---------- USER_GROUPS_LINK ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_groups_link (
            user_id INTEGER,
            chat_id INTEGER,
            PRIMARY KEY (user_id, chat_id)
        )
    """)
    # ---------- GROUP_ADMINS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_admins (
            chat_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    # ---------- HIDDEN_OWNER_GROUPS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS hidden_owner_groups (
            chat_id INTEGER,
            owner_id INTEGER,
            is_hidden INTEGER DEFAULT 1,
            PRIMARY KEY (chat_id, owner_id)
        )
    """)
    # ---------- HIDDEN_ADMINS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS hidden_admins (
            chat_id INTEGER,
            admin_id INTEGER,
            added_by INTEGER,
            added_at TEXT,
            PRIMARY KEY (chat_id, admin_id)
        )
    """)
    # ---------- ANONYMOUS_ADMINS ----------
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
    # ---------- GROUP_SECURITY ----------
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
            violation_duration INTEGER DEFAULT 60
        )
    """)
    # ---------- CHAT_LOCKS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_locks (
            chat_id INTEGER PRIMARY KEY,
            locked INTEGER DEFAULT 0,
            locked_at TEXT,
            locked_by INTEGER
        )
    """)
    # ---------- BANNED_WORDS ----------
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
    # ---------- AUTO_REPLIES ----------
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
    # ---------- AUTO_REPLY_SETTINGS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS auto_reply_settings (
            chat_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            only_admins INTEGER DEFAULT 0,
            ignore_bots INTEGER DEFAULT 1,
            updated_at TEXT
        )
    """)
    # ---------- SUPPORT_TICKETS ----------
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
    # ---------- BOT_ADMINS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id INTEGER PRIMARY KEY,
            added_by INTEGER,
            added_at TEXT
        )
    """)
    # ---------- SETTINGS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    default_settings = [
        ("publish_interval", "12"),
        ("auto_backup", "1"),
        ("last_ticket_number", "0"),
        ("last_backup", ""),
    ]
    for key, value in default_settings:
        await conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    # ---------- REFERRALS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            created_at TEXT,
            UNIQUE(referrer_id, referred_id)
        )
    """)
    # ---------- REFERRAL_REWARDS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS referral_rewards (
            user_id INTEGER PRIMARY KEY,
            referral_count INTEGER DEFAULT 0,
            total_reward_days INTEGER DEFAULT 0,
            claimed_reward_days INTEGER DEFAULT 0,
            last_referral_date TEXT
        )
    """)
    # ---------- USER_REMINDER_SETTINGS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_reminder_settings (
            user_id INTEGER PRIMARY KEY,
            subscription_reminder INTEGER DEFAULT 1,
            daily_stats_reminder INTEGER DEFAULT 0,
            weekly_report INTEGER DEFAULT 1,
            reminder_days_before INTEGER DEFAULT 3,
            last_reminder_sent TEXT,
            notification_lang TEXT DEFAULT 'ar'
        )
    """)
    # ---------- USER_TRANSLATION ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_translation (
            user_id INTEGER PRIMARY KEY,
            lang TEXT DEFAULT 'off'
        )
    """)
    # ---------- CONTESTS ----------
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
            contest_type TEXT DEFAULT 'raffle'
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
    # ---------- ADMIN_LOGS ----------
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
    # ---------- USER_WARNINGS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_warnings (
            user_id INTEGER,
            chat_id INTEGER,
            warnings INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, chat_id)
        )
    """)
    # ---------- USER_VIOLATIONS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_violations (
            user_id INTEGER,
            chat_id INTEGER,
            violation_count INTEGER DEFAULT 0,
            last_violation_time TEXT,
            PRIMARY KEY (user_id, chat_id)
        )
    """)
    # ---------- GROUP_RULES ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_rules (
            chat_id INTEGER PRIMARY KEY,
            rules_text TEXT,
            updated_by INTEGER,
            updated_at TEXT
        )
    """)
    # ---------- USER_MESSAGES ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_messages (
            user_id INTEGER,
            chat_id INTEGER,
            message_time TEXT,
            PRIMARY KEY (user_id, chat_id)
        )
    """)
    # ---------- SCHEDULED_POSTS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            text TEXT,
            publish_time TEXT,
            fail_count INTEGER DEFAULT 0
        )
    """)
    # ---------- SENTIMENT_HISTORY ----------
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
    # ---------- PLANS ----------
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
            features TEXT,
            is_active INTEGER DEFAULT 1,
            is_gift INTEGER DEFAULT 0,
            created_at TEXT
        )
    """)
    # ---------- SUBSCRIPTIONS ----------
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
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (plan_id) REFERENCES plans(id)
        )
    """)
    # ---------- INVOICES ----------
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
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (plan_id) REFERENCES plans(id)
        )
    """)
    # ---------- PAYMENT_LOGS ----------
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
    # ---------- USER_PENALTIES ----------
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
    # ---------- VIOLATION_PENALTIES ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS violation_penalties (
            chat_id INTEGER NOT NULL,
            violation_type TEXT NOT NULL,
            penalty_type TEXT NOT NULL DEFAULT 'mute',
            duration_seconds INTEGER DEFAULT 3600,
            PRIMARY KEY (chat_id, violation_type)
        )
    """)
    # ---------- GIFT_CODES ----------
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
        )
    """)
    # ---------- USER_POINTS ----------
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_points (
            user_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 0,
            last_updated TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    # ---------- PENALTY_ARCHIVE ----------
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

    # ============ الفهارس ============
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_posts_text_hash ON posts(text_hash)",
        "CREATE INDEX IF NOT EXISTS idx_users_active_channel ON users(active_channel)",
        "CREATE INDEX IF NOT EXISTS idx_subscriptions_active ON subscriptions(user_id, status, end_date)",
        "CREATE INDEX IF NOT EXISTS idx_auto_replies_lookup ON auto_replies(chat_id, keyword, is_active)",
        "CREATE INDEX IF NOT EXISTS idx_banned_words_chat_word ON banned_words(chat_id, word)",
        "CREATE INDEX IF NOT EXISTS idx_schedule_channel_next ON schedule(channel_db_id, next_publish_date)",
        "CREATE INDEX IF NOT EXISTS idx_subscriptions_user_status ON subscriptions(user_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_penalties_user_chat_status_end ON user_penalties(user_id, chat_id, status, end_time)",
        "CREATE INDEX IF NOT EXISTS idx_posts_channel_pub_fail_created_optimized ON posts(channel_db_id, published, fail_count, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_users_auto_publish_banned ON users(auto_publish, banned)",
        "CREATE INDEX IF NOT EXISTS idx_users_language ON users(language)",
        "CREATE INDEX IF NOT EXISTS idx_users_subscription_end ON users(subscription_end)",
        "CREATE INDEX IF NOT EXISTS idx_bot_groups_added_by ON bot_groups(added_by)",
        "CREATE INDEX IF NOT EXISTS idx_user_groups_link_user_id ON user_groups_link(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_hidden_owner_groups_owner_id ON hidden_owner_groups(owner_id)",
        "CREATE INDEX IF NOT EXISTS idx_hidden_admins_admin_id ON hidden_admins(admin_id)",
        "CREATE INDEX IF NOT EXISTS idx_group_admins_user_id ON group_admins(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_anonymous_admins_user_id ON anonymous_admins(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_anonymous_admins_anonymous_id ON anonymous_admins(anonymous_id)",
        "CREATE INDEX IF NOT EXISTS idx_users_auto_recycle ON users(auto_recycle)",
        "CREATE INDEX IF NOT EXISTS idx_user_channels_user_created ON user_channels(user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_user_channels_user_banned ON user_channels(user_id, banned)",
        "CREATE INDEX IF NOT EXISTS idx_schedule_next_publish ON schedule(next_publish_date)",
        "CREATE INDEX IF NOT EXISTS idx_subscriptions_user_status_end ON subscriptions(user_id, status, end_date)",
        "CREATE INDEX IF NOT EXISTS idx_posts_channel_published ON posts(channel_db_id, published)",
        "CREATE INDEX IF NOT EXISTS idx_posts_channel_pub_fail_created ON posts(channel_db_id, published, fail_count, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_users_banned ON users(banned)",
        "CREATE INDEX IF NOT EXISTS idx_uc_user ON user_channels(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_posts_channel ON posts(channel_db_id)",
        "CREATE INDEX IF NOT EXISTS idx_posts_published ON posts(published)",
        "CREATE INDEX IF NOT EXISTS idx_groups_banned ON bot_groups(banned)",
        "CREATE INDEX IF NOT EXISTS idx_banned_words_chat ON banned_words(chat_id)",
        "CREATE INDEX IF NOT EXISTS idx_ar_chat ON auto_replies(chat_id)",
        "CREATE INDEX IF NOT EXISTS idx_sub_user ON subscriptions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_sub_status ON subscriptions(status)",
        "CREATE INDEX IF NOT EXISTS idx_sub_end ON subscriptions(end_date)",
        "CREATE INDEX IF NOT EXISTS idx_inv_user ON invoices(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)",
        "CREATE INDEX IF NOT EXISTS idx_contests_status ON contests(status)",
        "CREATE INDEX IF NOT EXISTS idx_penalties_user ON user_penalties(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_penalties_chat ON user_penalties(chat_id)",
        "CREATE INDEX IF NOT EXISTS idx_penalties_status ON user_penalties(status)",
        "CREATE INDEX IF NOT EXISTS idx_points_user ON user_points(user_id)",
    ]
    for idx_sql in indexes:
        await conn.execute(idx_sql)

    if logger:
        logger.info("✅ تم إنشاء جميع جداول SQLite مع الفهارس المحسنة")


# =====================================================================
# 2. إنشاء جداول PostgreSQL
# =====================================================================

async def create_tables_postgres(conn, logger, TimeUtils):
    """إنشاء جميع جداول PostgreSQL + الفهارس"""
    # USERS
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
    # USER_CHANNELS
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
    # POSTS
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
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
        )
    """)
    await conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_unique
        ON posts(channel_db_id, text_hash, media_type, media_file_id)
    """)
    # SCHEDULE
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
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
        )
    """)
    # LAST_PUBLISH
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS last_publish (
            channel_db_id INTEGER PRIMARY KEY,
            last_publish_time TIMESTAMP,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
        )
    """)
    # BOT_GROUPS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_groups (
            chat_id BIGINT PRIMARY KEY,
            chat_name TEXT,
            username TEXT,
            added_by BIGINT,
            added_at TIMESTAMP,
            updated_at TIMESTAMP,
            banned INTEGER DEFAULT 0
        )
    """)
    # USER_GROUPS_LINK
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_groups_link (
            user_id BIGINT,
            chat_id BIGINT,
            PRIMARY KEY (user_id, chat_id)
        )
    """)
    # GROUP_ADMINS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_admins (
            chat_id BIGINT,
            user_id BIGINT,
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    # HIDDEN_OWNER_GROUPS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS hidden_owner_groups (
            chat_id BIGINT,
            owner_id BIGINT,
            is_hidden INTEGER DEFAULT 1,
            PRIMARY KEY (chat_id, owner_id)
        )
    """)
    # HIDDEN_ADMINS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS hidden_admins (
            chat_id BIGINT,
            admin_id BIGINT,
            added_by BIGINT,
            added_at TIMESTAMP,
            PRIMARY KEY (chat_id, admin_id)
        )
    """)
    # ANONYMOUS_ADMINS
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
    # GROUP_SECURITY
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
            violation_duration INTEGER DEFAULT 60
        )
    """)
    # CHAT_LOCKS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_locks (
            chat_id BIGINT PRIMARY KEY,
            locked INTEGER DEFAULT 0,
            locked_at TIMESTAMP,
            locked_by BIGINT
        )
    """)
    # BANNED_WORDS
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
    # AUTO_REPLIES
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
    # AUTO_REPLY_SETTINGS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS auto_reply_settings (
            chat_id BIGINT PRIMARY KEY,
            enabled INTEGER DEFAULT 0,
            only_admins INTEGER DEFAULT 0,
            ignore_bots INTEGER DEFAULT 1,
            updated_at TIMESTAMP
        )
    """)
    # SUPPORT_TICKETS
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
    # BOT_ADMINS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id BIGINT PRIMARY KEY,
            added_by BIGINT,
            added_at TIMESTAMP
        )
    """)
    # SETTINGS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    default_settings = [
        ("publish_interval", "12"),
        ("auto_backup", "1"),
        ("last_ticket_number", "0"),
        ("last_backup", ""),
    ]
    for key, value in default_settings:
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
            key,
            value,
        )
    # REFERRALS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id SERIAL PRIMARY KEY,
            referrer_id BIGINT,
            referred_id BIGINT,
            created_at TIMESTAMP,
            UNIQUE(referrer_id, referred_id)
        )
    """)
    # REFERRAL_REWARDS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS referral_rewards (
            user_id BIGINT PRIMARY KEY,
            referral_count INTEGER DEFAULT 0,
            total_reward_days INTEGER DEFAULT 0,
            claimed_reward_days INTEGER DEFAULT 0,
            last_referral_date TIMESTAMP
        )
    """)
    # USER_REMINDER_SETTINGS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_reminder_settings (
            user_id BIGINT PRIMARY KEY,
            subscription_reminder INTEGER DEFAULT 1,
            daily_stats_reminder INTEGER DEFAULT 0,
            weekly_report INTEGER DEFAULT 1,
            reminder_days_before INTEGER DEFAULT 3,
            last_reminder_sent TIMESTAMP,
            notification_lang TEXT DEFAULT 'ar'
        )
    """)
    # USER_TRANSLATION
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_translation (
            user_id BIGINT PRIMARY KEY,
            lang TEXT DEFAULT 'off'
        )
    """)
    # CONTESTS
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
            contest_type TEXT DEFAULT 'raffle'
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
    # ADMIN_LOGS
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
    # USER_WARNINGS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_warnings (
            user_id BIGINT,
            chat_id BIGINT,
            warnings INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, chat_id)
        )
    """)
    # USER_VIOLATIONS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_violations (
            user_id BIGINT,
            chat_id BIGINT,
            violation_count INTEGER DEFAULT 0,
            last_violation_time TIMESTAMP,
            PRIMARY KEY (user_id, chat_id)
        )
    """)
    # GROUP_RULES
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_rules (
            chat_id BIGINT PRIMARY KEY,
            rules_text TEXT,
            updated_by BIGINT,
            updated_at TIMESTAMP
        )
    """)
    # USER_MESSAGES
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_messages (
            user_id BIGINT,
            chat_id BIGINT,
            message_time TIMESTAMP,
            PRIMARY KEY (user_id, chat_id)
        )
    """)
    # SCHEDULED_POSTS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT,
            text TEXT,
            publish_time TIMESTAMP,
            fail_count INTEGER DEFAULT 0
        )
    """)
    # SENTIMENT_HISTORY
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
    # PLANS
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
            features TEXT,
            is_active INTEGER DEFAULT 1,
            is_gift INTEGER DEFAULT 0,
            created_at TIMESTAMP
        )
    """)
    # SUBSCRIPTIONS
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
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (plan_id) REFERENCES plans(id)
        )
    """)
    # INVOICES
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
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (plan_id) REFERENCES plans(id)
        )
    """)
    # PAYMENT_LOGS
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
    # USER_PENALTIES
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
    # VIOLATION_PENALTIES
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS violation_penalties (
            chat_id BIGINT NOT NULL,
            violation_type TEXT NOT NULL,
            penalty_type TEXT NOT NULL DEFAULT 'mute',
            duration_seconds INTEGER DEFAULT 3600,
            PRIMARY KEY (chat_id, violation_type)
        )
    """)
    # GIFT_CODES
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
        )
    """)
    # USER_POINTS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_points (
            user_id BIGINT PRIMARY KEY,
            points INTEGER DEFAULT 0,
            last_updated TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    # PENALTY_ARCHIVE
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

    # ============ الفهارس ============
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_posts_text_hash ON posts(text_hash)",
        "CREATE INDEX IF NOT EXISTS idx_users_active_channel ON users(active_channel)",
        "CREATE INDEX IF NOT EXISTS idx_subscriptions_active ON subscriptions(user_id, status, end_date)",
        "CREATE INDEX IF NOT EXISTS idx_auto_replies_lookup ON auto_replies(chat_id, keyword, is_active)",
        "CREATE INDEX IF NOT EXISTS idx_banned_words_chat_word ON banned_words(chat_id, word)",
        "CREATE INDEX IF NOT EXISTS idx_schedule_channel_next ON schedule(channel_db_id, next_publish_date)",
        "CREATE INDEX IF NOT EXISTS idx_subscriptions_user_status ON subscriptions(user_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_penalties_user_chat_status_end ON user_penalties(user_id, chat_id, status, end_time)",
        "CREATE INDEX IF NOT EXISTS idx_posts_channel_pub_fail_created_optimized ON posts(channel_db_id, published, fail_count, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_users_auto_publish_banned ON users(auto_publish, banned)",
        "CREATE INDEX IF NOT EXISTS idx_users_language ON users(language)",
        "CREATE INDEX IF NOT EXISTS idx_users_subscription_end ON users(subscription_end)",
        "CREATE INDEX IF NOT EXISTS idx_bot_groups_added_by ON bot_groups(added_by)",
        "CREATE INDEX IF NOT EXISTS idx_user_groups_link_user_id ON user_groups_link(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_hidden_owner_groups_owner_id ON hidden_owner_groups(owner_id)",
        "CREATE INDEX IF NOT EXISTS idx_hidden_admins_admin_id ON hidden_admins(admin_id)",
        "CREATE INDEX IF NOT EXISTS idx_group_admins_user_id ON group_admins(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_anonymous_admins_user_id ON anonymous_admins(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_anonymous_admins_anonymous_id ON anonymous_admins(anonymous_id)",
        "CREATE INDEX IF NOT EXISTS idx_users_auto_recycle ON users(auto_recycle)",
        "CREATE INDEX IF NOT EXISTS idx_user_channels_user_created ON user_channels(user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_user_channels_user_banned ON user_channels(user_id, banned)",
        "CREATE INDEX IF NOT EXISTS idx_schedule_next_publish ON schedule(next_publish_date)",
        "CREATE INDEX IF NOT EXISTS idx_subscriptions_user_status_end ON subscriptions(user_id, status, end_date)",
        "CREATE INDEX IF NOT EXISTS idx_posts_channel_published ON posts(channel_db_id, published)",
        "CREATE INDEX IF NOT EXISTS idx_posts_channel_pub_fail_created ON posts(channel_db_id, published, fail_count, created_at)",
    ]
    for idx_sql in indexes:
        await conn.execute(idx_sql)

    if logger:
        logger.info("✅ تم إنشاء جميع جداول PostgreSQL مع الفهارس المحسنة")


# =====================================================================
# 3. إنشاء جداول MySQL
# =====================================================================

async def create_tables_mysql(conn, logger, TimeUtils):
    """إنشاء جميع جداول MySQL + الفهارس"""
    await conn.execute("SET FOREIGN_KEY_CHECKS=0")
    # USERS
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
    # USER_CHANNELS
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
    # POSTS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INT PRIMARY KEY AUTO_INCREMENT,
            channel_db_id INT,
            text VARCHAR(4096) NOT NULL,
            text_hash CHAR(64) DEFAULT '',
            media_type VARCHAR(50),
            media_file_id VARCHAR(4096),
            published TINYINT(1) DEFAULT 0,
            fail_count INT DEFAULT 0,
            created_at DATETIME,
            published_at DATETIME,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE,
            UNIQUE KEY idx_posts_unique (channel_db_id, text_hash, media_type, media_file_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # SCHEDULE
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            channel_db_id INT PRIMARY KEY,
            schedule_type VARCHAR(50) DEFAULT 'interval_minutes',
            interval_minutes INT DEFAULT 12,
            interval_hours INT DEFAULT 0,
            interval_days INT DEFAULT 0,
            days_of_week TEXT DEFAULT '[]',
            specific_dates TEXT DEFAULT '[]',
            publish_time VARCHAR(10) DEFAULT '00:00',
            cron_expression TEXT,
            next_publish_date DATETIME,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # LAST_PUBLISH
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS last_publish (
            channel_db_id INT PRIMARY KEY,
            last_publish_time DATETIME,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # BOT_GROUPS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_groups (
            chat_id BIGINT PRIMARY KEY,
            chat_name VARCHAR(255),
            username VARCHAR(255),
            added_by BIGINT,
            added_at DATETIME,
            updated_at DATETIME,
            banned TINYINT(1) DEFAULT 0
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # USER_GROUPS_LINK
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_groups_link (
            user_id BIGINT,
            chat_id BIGINT,
            PRIMARY KEY (user_id, chat_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # GROUP_ADMINS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_admins (
            chat_id BIGINT,
            user_id BIGINT,
            PRIMARY KEY (chat_id, user_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # HIDDEN_OWNER_GROUPS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS hidden_owner_groups (
            chat_id BIGINT,
            owner_id BIGINT,
            is_hidden TINYINT(1) DEFAULT 1,
            PRIMARY KEY (chat_id, owner_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # HIDDEN_ADMINS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS hidden_admins (
            chat_id BIGINT,
            admin_id BIGINT,
            added_by BIGINT,
            added_at DATETIME,
            PRIMARY KEY (chat_id, admin_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # ANONYMOUS_ADMINS
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
    # GROUP_SECURITY
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_security (
            chat_id BIGINT PRIMARY KEY,
            delete_links TINYINT(1) DEFAULT 0,
            mentions TINYINT(1) DEFAULT 0,
            slow_mode TINYINT(1) DEFAULT 0,
            slow_mode_seconds INT DEFAULT 5,
            welcome_enabled TINYINT(1) DEFAULT 0,
            welcome_text TEXT DEFAULT 'مرحباً {user} في {chat} 🤍',
            goodbye_enabled TINYINT(1) DEFAULT 0,
            goodbye_text TEXT DEFAULT 'وداعاً {user} 👋',
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
            violation_duration INT DEFAULT 60
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # CHAT_LOCKS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_locks (
            chat_id BIGINT PRIMARY KEY,
            locked TINYINT(1) DEFAULT 0,
            locked_at DATETIME,
            locked_by BIGINT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # BANNED_WORDS
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
    # AUTO_REPLIES
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
    # AUTO_REPLY_SETTINGS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS auto_reply_settings (
            chat_id BIGINT PRIMARY KEY,
            enabled TINYINT(1) DEFAULT 0,
            only_admins TINYINT(1) DEFAULT 0,
            ignore_bots TINYINT(1) DEFAULT 1,
            updated_at DATETIME
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # SUPPORT_TICKETS
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
    # BOT_ADMINS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id BIGINT PRIMARY KEY,
            added_by BIGINT,
            added_at DATETIME
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # SETTINGS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            `key` VARCHAR(255) PRIMARY KEY,
            `value` TEXT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    default_settings = [
        ("publish_interval", "12"),
        ("auto_backup", "1"),
        ("last_ticket_number", "0"),
        ("last_backup", ""),
    ]
    for key, value in default_settings:
        await conn.execute(
            "INSERT IGNORE INTO settings (`key`, `value`) VALUES (%s, %s)",
            (key, value),
        )
    # REFERRALS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INT PRIMARY KEY AUTO_INCREMENT,
            referrer_id BIGINT,
            referred_id BIGINT,
            created_at DATETIME,
            UNIQUE KEY (referrer_id, referred_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # REFERRAL_REWARDS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS referral_rewards (
            user_id BIGINT PRIMARY KEY,
            referral_count INT DEFAULT 0,
            total_reward_days INT DEFAULT 0,
            claimed_reward_days INT DEFAULT 0,
            last_referral_date DATETIME
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # USER_REMINDER_SETTINGS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_reminder_settings (
            user_id BIGINT PRIMARY KEY,
            subscription_reminder TINYINT(1) DEFAULT 1,
            daily_stats_reminder TINYINT(1) DEFAULT 0,
            weekly_report TINYINT(1) DEFAULT 1,
            reminder_days_before INT DEFAULT 3,
            last_reminder_sent DATETIME,
            notification_lang VARCHAR(10) DEFAULT 'ar'
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # USER_TRANSLATION
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_translation (
            user_id BIGINT PRIMARY KEY,
            lang VARCHAR(10) DEFAULT 'off'
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # CONTESTS
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
            contest_type VARCHAR(50) DEFAULT 'raffle'
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
    # ADMIN_LOGS
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
    # USER_WARNINGS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_warnings (
            user_id BIGINT,
            chat_id BIGINT,
            warnings INT DEFAULT 0,
            PRIMARY KEY (user_id, chat_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # USER_VIOLATIONS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_violations (
            user_id BIGINT,
            chat_id BIGINT,
            violation_count INT DEFAULT 0,
            last_violation_time DATETIME,
            PRIMARY KEY (user_id, chat_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # GROUP_RULES
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_rules (
            chat_id BIGINT PRIMARY KEY,
            rules_text TEXT,
            updated_by BIGINT,
            updated_at DATETIME
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # USER_MESSAGES
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_messages (
            user_id BIGINT,
            chat_id BIGINT,
            message_time DATETIME,
            PRIMARY KEY (user_id, chat_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # SCHEDULED_POSTS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INT PRIMARY KEY AUTO_INCREMENT,
            chat_id BIGINT,
            text TEXT,
            publish_time DATETIME,
            fail_count INT DEFAULT 0
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # SENTIMENT_HISTORY
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
    # PLANS
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
    # SUBSCRIPTIONS
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
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (plan_id) REFERENCES plans(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # INVOICES
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
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (plan_id) REFERENCES plans(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # PAYMENT_LOGS
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
    # USER_PENALTIES
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
    # VIOLATION_PENALTIES
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS violation_penalties (
            chat_id BIGINT NOT NULL,
            violation_type VARCHAR(50) NOT NULL,
            penalty_type VARCHAR(50) NOT NULL DEFAULT 'mute',
            duration_seconds INT DEFAULT 3600,
            PRIMARY KEY (chat_id, violation_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # GIFT_CODES
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
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # USER_POINTS
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_points (
            user_id BIGINT PRIMARY KEY,
            points INT DEFAULT 0,
            last_updated DATETIME,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # PENALTY_ARCHIVE
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
    await conn.execute("SET FOREIGN_KEY_CHECKS=1")

    # ============ الفهارس ============
    indexes = [
        "CREATE INDEX idx_posts_text_hash ON posts(text_hash)",
        "CREATE INDEX idx_users_active_channel ON users(active_channel)",
        "CREATE INDEX idx_subscriptions_active ON subscriptions(user_id, status, end_date)",
        "CREATE INDEX idx_auto_replies_lookup ON auto_replies(chat_id, keyword, is_active)",
        "CREATE INDEX idx_banned_words_chat_word ON banned_words(chat_id, word)",
        "CREATE INDEX idx_schedule_channel_next ON schedule(channel_db_id, next_publish_date)",
        "CREATE INDEX idx_subscriptions_user_status ON subscriptions(user_id, status)",
        "CREATE INDEX idx_penalties_user_chat_status_end ON user_penalties(user_id, chat_id, status, end_time)",
        "CREATE INDEX idx_posts_channel_pub_fail_created_optimized ON posts(channel_db_id, published, fail_count, created_at)",
        "CREATE INDEX idx_users_auto_publish_banned ON users(auto_publish, banned)",
        "CREATE INDEX idx_users_language ON users(language)",
        "CREATE INDEX idx_users_subscription_end ON users(subscription_end)",
        "CREATE INDEX idx_bot_groups_added_by ON bot_groups(added_by)",
        "CREATE INDEX idx_user_groups_link_user_id ON user_groups_link(user_id)",
        "CREATE INDEX idx_hidden_owner_groups_owner_id ON hidden_owner_groups(owner_id)",
        "CREATE INDEX idx_hidden_admins_admin_id ON hidden_admins(admin_id)",
        "CREATE INDEX idx_group_admins_user_id ON group_admins(user_id)",
        "CREATE INDEX idx_anonymous_admins_user_id ON anonymous_admins(user_id)",
        "CREATE INDEX idx_anonymous_admins_anonymous_id ON anonymous_admins(anonymous_id)",
        "CREATE INDEX idx_users_auto_recycle ON users(auto_recycle)",
        "CREATE INDEX idx_user_channels_user_created ON user_channels(user_id, created_at DESC)",
        "CREATE INDEX idx_user_channels_user_banned ON user_channels(user_id, banned)",
        "CREATE INDEX idx_schedule_next_publish ON schedule(next_publish_date)",
        "CREATE INDEX idx_subscriptions_user_status_end ON subscriptions(user_id, status, end_date)",
        "CREATE INDEX idx_posts_channel_published ON posts(channel_db_id, published)",
        "CREATE INDEX idx_posts_channel_pub_fail_created ON posts(channel_db_id, published, fail_count, created_at)",
    ]
    for idx_sql in indexes:
        try:
            await conn.execute(idx_sql)
        except Exception as e:
            if "Duplicate key name" not in str(e) and "already exists" not in str(e).lower():
                if logger:
                    logger.debug(f"index already exists or error: {e}")

    if logger:
        logger.info("✅ تم إنشاء جميع جداول MySQL مع الفهارس المحسنة")
