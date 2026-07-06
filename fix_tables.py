import asyncio
import aiosqlite
from pathlib import Path

DB_PATH = Path("data/bot_data.db")

async def fix_tables():
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        print("🔧 جاري إضافة الجداول المفقودة...")
        
        # ===== الجداول الأساسية (يجب أن تكون موجودة) =====
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                auto_publish INTEGER DEFAULT 1,
                banned INTEGER DEFAULT 0,
                subscription_end TEXT,
                language TEXT DEFAULT 'ar',
                active_channel INTEGER
            )
        """)
        print("✅ جدول users")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_id TEXT,
                channel_name TEXT,
                created_at TIMESTAMP,
                banned INTEGER DEFAULT 0
            )
        """)
        print("✅ جدول user_channels")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_db_id INTEGER,
                text TEXT,
                media_type TEXT DEFAULT 'text',
                media_file_id TEXT,
                published INTEGER DEFAULT 0,
                created_at TIMESTAMP
            )
        """)
        print("✅ جدول posts")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_groups (
                chat_id INTEGER PRIMARY KEY,
                chat_name TEXT,
                username TEXT,
                added_by INTEGER,
                added_at TIMESTAMP,
                banned INTEGER DEFAULT 0
            )
        """)
        print("✅ جدول bot_groups")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        print("✅ جدول settings")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hidden_owners (
                chat_id INTEGER,
                owner_id INTEGER,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, owner_id)
            )
        """)
        print("✅ جدول hidden_owners")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hidden_admins (
                chat_id INTEGER,
                admin_id INTEGER,
                added_by INTEGER,
                permissions TEXT DEFAULT 'full',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, admin_id)
            )
        """)
        print("✅ جدول hidden_admins")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                action TEXT,
                target_id INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✅ جدول activity_log")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_replies (
                keyword TEXT PRIMARY KEY,
                reply TEXT
            )
        """)
        print("✅ جدول group_replies")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                message TEXT,
                ticket_number INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP,
                replied INTEGER DEFAULT 0
            )
        """)
        print("✅ جدول support_tickets")
        
        # ===== الجداول المفقودة =====
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schedule (
                channel_db_id INTEGER PRIMARY KEY,
                schedule_type TEXT DEFAULT 'interval_minutes',
                interval_minutes INTEGER DEFAULT 12,
                interval_hours INTEGER DEFAULT 0,
                interval_days INTEGER DEFAULT 0,
                days_of_week TEXT DEFAULT '',
                specific_dates TEXT DEFAULT '',
                publish_time TEXT DEFAULT '00:00',
                cron_expression TEXT DEFAULT NULL,
                next_publish_date TEXT
            )
        """)
        print("✅ جدول schedule")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS last_publish (
                channel_db_id INTEGER PRIMARY KEY,
                last_publish_time TIMESTAMP
            )
        """)
        print("✅ جدول last_publish")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                publish_time TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                fail_count INTEGER DEFAULT 0
            )
        """)
        print("✅ جدول scheduled_posts")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS banned_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT,
                chat_id INTEGER,
                added_by INTEGER,
                added_at TIMESTAMP,
                UNIQUE(word, chat_id)
            )
        """)
        print("✅ جدول banned_words")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_levels (
                user_id INTEGER PRIMARY KEY,
                points INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1
            )
        """)
        print("✅ جدول user_levels")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL,
                referred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_rewarded INTEGER DEFAULT 0,
                UNIQUE(referred_id)
            )
        """)
        print("✅ جدول referrals")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referral_rewards (
                user_id INTEGER PRIMARY KEY,
                referral_count INTEGER DEFAULT 0,
                total_reward_days INTEGER DEFAULT 0,
                claimed_reward_days INTEGER DEFAULT 0
            )
        """)
        print("✅ جدول referral_rewards")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_reminder_settings (
                user_id INTEGER PRIMARY KEY,
                subscription_reminder INTEGER DEFAULT 1,
                daily_stats_reminder INTEGER DEFAULT 0,
                weekly_report INTEGER DEFAULT 1,
                reminder_days_before INTEGER DEFAULT 3,
                last_reminder_sent INTEGER DEFAULT 0,
                notification_lang TEXT DEFAULT 'ar'
            )
        """)
        print("✅ جدول user_reminder_settings")
        
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
                created_at TIMESTAMP,
                contest_type TEXT DEFAULT 'raffle'
            )
        """)
        print("✅ جدول contests")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contest_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                contest_id INTEGER,
                answer TEXT,
                joined_at TIMESTAMP,
                UNIQUE(user_id, contest_id)
            )
        """)
        print("✅ جدول contest_participants")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contest_winners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contest_id INTEGER,
                winner_id INTEGER,
                announced_at TIMESTAMP
            )
        """)
        print("✅ جدول contest_winners")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_translation (
                user_id INTEGER PRIMARY KEY,
                lang TEXT DEFAULT 'off'
            )
        """)
        print("✅ جدول user_translation")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS channel_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_db_id INTEGER NOT NULL,
                total_posts INTEGER DEFAULT 0,
                published_posts INTEGER DEFAULT 0,
                unpublished_posts INTEGER DEFAULT 0,
                total_views INTEGER DEFAULT 0,
                avg_views_per_post REAL DEFAULT 0,
                last_post_time TIMESTAMP,
                avg_time_between_posts REAL DEFAULT 0,
                best_publish_hour INTEGER DEFAULT 0,
                best_publish_day INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_db_id)
            )
        """)
        print("✅ جدول channel_stats")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS moderation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                action TEXT,
                duration_minutes INTEGER,
                moderator_id INTEGER,
                reason TEXT,
                created_at TIMESTAMP
            )
        """)
        print("✅ جدول moderation_log")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS auto_reply_settings (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                only_admins INTEGER DEFAULT 0,
                ignore_bots INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("✅ جدول auto_reply_settings")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        print("✅ جدول bot_admins")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_locks (
                chat_id INTEGER PRIMARY KEY,
                locked INTEGER DEFAULT 0,
                locked_at TIMESTAMP,
                locked_by INTEGER
            )
        """)
        print("✅ جدول chat_locks")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_security (
                chat_id INTEGER PRIMARY KEY,
                delete_links INTEGER DEFAULT 0,
                delete_mentions INTEGER DEFAULT 0,
                warn_message INTEGER DEFAULT 1,
                slow_mode INTEGER DEFAULT 0,
                slow_mode_seconds INTEGER DEFAULT 5,
                welcome_enabled INTEGER DEFAULT 0,
                welcome_text TEXT DEFAULT 'مرحباً {user} في {chat} 🤍',
                goodbye_enabled INTEGER DEFAULT 0,
                goodbye_text TEXT DEFAULT 'وداعاً {user} 👋',
                delete_banned_words INTEGER DEFAULT 0,
                auto_penalty TEXT DEFAULT 'none',
                auto_mute_duration INTEGER DEFAULT 60
            )
        """)
        print("✅ جدول group_security")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_messages (
                user_id INTEGER,
                chat_id INTEGER,
                message_time TIMESTAMP,
                PRIMARY KEY (user_id, chat_id)
            )
        """)
        print("✅ جدول user_messages")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_warnings (
                user_id INTEGER,
                chat_id INTEGER,
                warnings INTEGER DEFAULT 0,
                PRIMARY KEY(user_id, chat_id)
            )
        """)
        print("✅ جدول user_warnings")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users_cache (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_updated TEXT
            )
        """)
        print("✅ جدول users_cache")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS web_sessions (
                session_id TEXT PRIMARY KEY,
                user_data TEXT,
                expires INTEGER
            )
        """)
        print("✅ جدول web_sessions")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hidden_owner_groups (
                chat_id INTEGER PRIMARY KEY,
                owner_id INTEGER,
                is_hidden INTEGER DEFAULT 1
            )
        """)
        print("✅ جدول hidden_owner_groups")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_groups_link (
                user_id INTEGER,
                chat_id INTEGER,
                PRIMARY KEY(user_id, chat_id)
            )
        """)
        print("✅ جدول user_groups_link")
        
        # ===== الفهارس =====
        try:
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_channel_published ON posts(channel_db_id, published)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_next ON schedule(next_publish_date)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_channels_user ON user_channels(user_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_banned_words_chat ON banned_words(chat_id, word)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_messages_time ON user_messages(message_time)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_channel_fail ON posts(channel_db_id, published, fail_count)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_subscription ON users(subscription_end)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_levels_points ON user_levels(points DESC)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_moderation_chat ON moderation_log(chat_id, created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_channel_stats ON channel_stats(channel_db_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_views ON posts(views_count)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_published_views ON posts(published, views_count)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_contests_active ON contests(status, end_date)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_hidden_admins_chat ON hidden_admins(chat_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_schedule_cron ON schedule(cron_expression)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_last_daily ON users(last_daily_reward)")
            print("✅ الفهارس")
        except Exception as e:
            print(f"⚠️ بعض الفهارس موجودة مسبقاً: {e}")
        
        await conn.commit()
        print("\n✅ ✅ ✅ تم إضافة جميع الجداول بنجاح!")
        print(f"📊 إجمالي الجداول: 34 جدول")

asyncio.run(fix_tables())
