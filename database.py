import aiosqlite
from config import DB_PATH, fernet

# ---- تجميع الاتصال ----
_conn = None

async def get_conn():
    global _conn
    if _conn is None:
        _conn = await aiosqlite.connect(DB_PATH)
        _conn.row_factory = aiosqlite.Row
        await _conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, banned INTEGER DEFAULT 0,
                subscription_end TEXT, language TEXT DEFAULT 'ar',
                active_channel INTEGER, referral_code TEXT,
                points INTEGER DEFAULT 0, level INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                channel_id TEXT, channel_name TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, channel_db_id INTEGER,
                text TEXT, media_type TEXT DEFAULT 'text', media_file_id TEXT,
                published INTEGER DEFAULT 0, scheduled_time TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS bot_groups (
                chat_id INTEGER PRIMARY KEY, chat_name TEXT,
                added_by INTEGER, added_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT
            );
            CREATE TABLE IF NOT EXISTS owners (
                chat_id INTEGER, user_id INTEGER, PRIMARY KEY(chat_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS admins (
                chat_id INTEGER, user_id INTEGER, PRIMARY KEY(chat_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS replies (
                keyword TEXT PRIMARY KEY, reply TEXT
            );
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                username TEXT, message TEXT, ticket_num INTEGER,
                status TEXT DEFAULT 'pending', created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS banned_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT, word TEXT,
                chat_id INTEGER DEFAULT -1, UNIQUE(word, chat_id)
            );
            CREATE TABLE IF NOT EXISTS contests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER,
                title TEXT, prize TEXT, end_date TEXT, status TEXT DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS contest_participants (
                contest_id INTEGER, user_id INTEGER, PRIMARY KEY(contest_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS contest_winners (
                contest_id INTEGER, winner_id INTEGER, PRIMARY KEY(contest_id, winner_id)
            );
            CREATE TABLE IF NOT EXISTS referrals (
                referrer_id INTEGER, referred_id INTEGER, PRIMARY KEY(referrer_id, referred_id)
            );
            CREATE TABLE IF NOT EXISTS referral_rewards (
                user_id INTEGER PRIMARY KEY, total_days INTEGER DEFAULT 0,
                claimed_days INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS reminders (
                user_id INTEGER PRIMARY KEY, sub_reminder INTEGER DEFAULT 1,
                daily_stats INTEGER DEFAULT 0, weekly_report INTEGER DEFAULT 1,
                days_before INTEGER DEFAULT 3
            );
            CREATE TABLE IF NOT EXISTS group_settings (
                chat_id INTEGER PRIMARY KEY, lock_links INTEGER DEFAULT 0,
                lock_mentions INTEGER DEFAULT 0, slow_mode INTEGER DEFAULT 0,
                welcome_msg TEXT, goodbye_msg TEXT
            );
            CREATE TABLE IF NOT EXISTS moderation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER,
                admin_id INTEGER, target_id INTEGER, action TEXT,
                reason TEXT, timestamp TEXT
            );
            INSERT OR IGNORE INTO settings VALUES('publish_interval', '720');
            INSERT OR IGNORE INTO settings VALUES('last_ticket', '0');
        """)
        await _conn.commit()
    return _conn

async def init_db():
    await get_conn()

async def fetch(query, *params):
    conn = await get_conn()
    async with conn.execute(query, params) as cur:
        return await cur.fetchall()

async def execute(query, *params):
    conn = await get_conn()
    await conn.execute(query, params)
    await conn.commit()

def encrypt(text):
    if text is None: return None
    return fernet.encrypt(text.encode()).decode()

def decrypt(text):
    if text is None: return None
    return fernet.decrypt(text.encode()).decode()
