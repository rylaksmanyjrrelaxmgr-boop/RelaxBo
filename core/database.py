import aiosqlite
from config import DB_PATH, DB_TIMEOUT

class DatabasePool:
    def __init__(self):
        self._pool = None
    
    async def initialize(self):
        if self._pool is None:
            self._pool = await aiosqlite.connect(str(DB_PATH), timeout=DB_TIMEOUT)
            await self._pool.execute("PRAGMA journal_mode=WAL")
            await self._pool.execute("PRAGMA synchronous=NORMAL")
            await self._pool.execute("PRAGMA foreign_keys=ON")
            self._pool.row_factory = aiosqlite.Row
        return self._pool
    
    async def get_connection(self):
        if self._pool is None:
            await self.initialize()
        return self._pool
    
    async def close(self):
        if self._pool:
            await self._pool.close()
            self._pool = None

db_pool = DatabasePool()

async def execute_db(func):
    conn = await db_pool.get_connection()
    return await func(conn)

async def init_db():
    async with aiosqlite.connect(str(DB_PATH), timeout=DB_TIMEOUT) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                auto_publish INTEGER DEFAULT 1,
                banned INTEGER DEFAULT 0,
                trial_used INTEGER DEFAULT 0,
                subscription_end TEXT,
                active_channel INTEGER,
                auto_reply_enabled INTEGER DEFAULT 1,
                auto_recycle INTEGER DEFAULT 1,
                language TEXT DEFAULT 'ar'
            )
        """)
        
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
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_db_id INTEGER,
                text TEXT,
                media_type TEXT DEFAULT 'text',
                media_file_id TEXT,
                published INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                created_at TIMESTAMP
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
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
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_levels (
                user_id INTEGER PRIMARY KEY,
                points INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1
            )
        """)
        
        await conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('publish_interval', '720')")
        await conn.commit()
    
    print("✅ قاعدة البيانات جاهزة")
