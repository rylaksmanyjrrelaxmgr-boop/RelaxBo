#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام الحظر المتطور - الإصدار 6.2 (المحسن بالكامل مع مصادقة موثوقة)
ريلاكس مانيجر · إدارة متقدمة مع تحسينات الأمان والأداء والواجهة
"""

import os
import asyncio
import logging
import threading
import json
import time
import csv
import io
import hashlib
import secrets
from datetime import datetime, timedelta
from functools import lru_cache
from collections import OrderedDict
from aiohttp import web, web_exceptions
import aiosqlite

logger = logging.getLogger(__name__)

# ===================== الإعدادات =====================
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bot_data.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ✅ استخدام WEB_PASSWORD من البيئة مع قيمة افتراضية آمنة
ADMIN_PASSWORD = os.getenv("WEB_PASSWORD", "")
if not ADMIN_PASSWORD:
    ADMIN_PASSWORD = secrets.token_urlsafe(16)
    print(f"⚠️ لم يتم تعيين WEB_PASSWORD، تم إنشاء كلمة مرور مؤقتة: {ADMIN_PASSWORD}")

# ✅ تسجيل كلمة المرور للتحقق
print(f"🔐 كلمة المرور المستخدمة: {ADMIN_PASSWORD}")

ENABLE_2FA = os.getenv("ENABLE_2FA", "False").lower() == "true"
ADMIN_2FA_SECRET = os.getenv("ADMIN_2FA_SECRET", "")
if ENABLE_2FA and not ADMIN_2FA_SECRET:
    try:
        import pyotp
        ADMIN_2FA_SECRET = pyotp.random_base32()
        logger.info(f"🔐 تم توليد مفتاح 2FA: {ADMIN_2FA_SECRET}")
    except ImportError:
        logger.warning("⚠️ pyotp غير مثبت، سيتم تعطيل 2FA")
        ENABLE_2FA = False

SESSION_SECRET = secrets.token_urlsafe(32)
_sessions = {}
_SESSION_TIMEOUT = 3600  # ساعة
_SERVER_STARTED = False
_SERVER_LOCK = threading.Lock()

# ===================== التخزين المؤقت =====================
class LRUCache:
    def __init__(self, maxsize=100, ttl=60):
        self.cache = OrderedDict()
        self.maxsize = maxsize
        self.ttl = ttl

    def _clean(self):
        now = time.time()
        keys_to_delete = [k for k, (v, t) in self.cache.items() if now - t > self.ttl]
        for k in keys_to_delete:
            del self.cache[k]

    def get(self, key):
        self._clean()
        if key in self.cache:
            value, _ = self.cache[key]
            self.cache.move_to_end(key)
            return value
        return None

    def set(self, key, value):
        self._clean()
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = (value, time.time())
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)

stats_cache = LRUCache(maxsize=20, ttl=30)
data_cache = LRUCache(maxsize=50, ttl=60)

# ===================== دوال قاعدة البيانات =====================

async def get_db():
    conn = await aiosqlite.connect(DB_PATH, timeout=30)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA cache_size=-64000")
    return conn

async def db_stats_cached():
    cached = stats_cache.get("stats")
    if cached is not None:
        return cached
    stats = await db_stats_uncached()
    stats_cache.set("stats", stats)
    return stats

async def db_stats_uncached():
    try:
        async with await get_db() as conn:
            total_users = 0
            total_channels = 0
            total_groups = 0
            pending_posts = 0
            blocked_users = 0
            blocked_channels = 0
            blocked_groups = 0
            today_blocks = 0
            updates_channel = "غير محددة"

            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if await cur.fetchone():
                total_users = (await conn.execute("SELECT COUNT(*) FROM users")).fetchone()[0] or 0

            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='blocked_users'")
            if await cur.fetchone():
                blocked_users = (await conn.execute("SELECT COUNT(*) FROM blocked_users")).fetchone()[0] or 0

            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_channels'")
            if await cur.fetchone():
                total_channels = (await conn.execute("SELECT COUNT(*) FROM user_channels")).fetchone()[0] or 0

            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='blocked_channels'")
            if await cur.fetchone():
                blocked_channels = (await conn.execute("SELECT COUNT(*) FROM blocked_channels")).fetchone()[0] or 0

            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bot_groups'")
            if await cur.fetchone():
                total_groups = (await conn.execute("SELECT COUNT(*) FROM bot_groups")).fetchone()[0] or 0

            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='blocked_groups'")
            if await cur.fetchone():
                blocked_groups = (await conn.execute("SELECT COUNT(*) FROM blocked_groups")).fetchone()[0] or 0

            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='posts'")
            if await cur.fetchone():
                pending_posts = (await conn.execute("SELECT COUNT(*) FROM posts WHERE published=0")).fetchone()[0] or 0

            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='block_logs'")
            if await cur.fetchone():
                today = datetime.utcnow().date().isoformat()
                today_blocks = (await conn.execute(
                    "SELECT COUNT(*) FROM block_logs WHERE DATE(created_at)=?",
                    (today,)
                )).fetchone()[0] or 0

            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
            if await cur.fetchone():
                updates_channel = await conn.execute("SELECT value FROM settings WHERE key='updates_channel'")
                updates_row = await updates_channel.fetchone()
                updates_channel = updates_row[0] if updates_row else "غير محددة"

            return {
                'total_users': total_users,
                'blocked_users': blocked_users,
                'blocked_channels': blocked_channels,
                'blocked_groups': blocked_groups,
                'total_channels': total_channels,
                'total_groups': total_groups,
                'pending_posts': pending_posts,
                'today_blocks': today_blocks,
                'updates_channel': updates_channel
            }
    except Exception as e:
        logger.error(f"خطأ في جلب الإحصائيات: {e}")
        return {
            'total_users': 0, 'blocked_users': 0, 'blocked_channels': 0,
            'blocked_groups': 0, 'total_channels': 0, 'total_groups': 0,
            'pending_posts': 0, 'today_blocks': 0, 'updates_channel': 'غير محددة'
        }

async def db_get_all_groups_cached(limit=200):
    cache_key = f"all_groups_{limit}"
    cached = data_cache.get(cache_key)
    if cached is not None:
        return cached
    data = await db_get_all_groups_uncached(limit)
    data_cache.set(cache_key, data)
    return data

async def db_get_all_groups_uncached(limit=200):
    try:
        async with await get_db() as conn:
            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bot_groups'")
            if not await cur.fetchone():
                return []
            cur = await conn.execute("""
                SELECT g.chat_id, g.chat_name, g.username, g.added_by, g.added_at, g.banned,
                CASE WHEN bg.chat_id IS NOT NULL THEN 1 ELSE 0 END as is_blocked, bg.reason as block_reason
                FROM bot_groups g LEFT JOIN blocked_groups bg ON g.chat_id = bg.chat_id
                ORDER BY g.chat_name LIMIT ?
            """, (limit,))
            return await cur.fetchall()
    except:
        return []

async def db_get_all_channels_cached(limit=200):
    cache_key = f"all_channels_{limit}"
    cached = data_cache.get(cache_key)
    if cached is not None:
        return cached
    data = await db_get_all_channels_uncached(limit)
    data_cache.set(cache_key, data)
    return data

async def db_get_all_channels_uncached(limit=200):
    try:
        async with await get_db() as conn:
            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_channels'")
            if not await cur.fetchone():
                return []
            cur = await conn.execute("""
                SELECT c.id, c.user_id, c.channel_id, c.channel_name, c.created_at, c.banned,
                CASE WHEN bc.channel_id IS NOT NULL THEN 1 ELSE 0 END as is_blocked, bc.reason as block_reason
                FROM user_channels c LEFT JOIN blocked_channels bc ON c.channel_id = bc.channel_id
                ORDER BY c.channel_name LIMIT ?
            """, (limit,))
            return await cur.fetchall()
    except:
        return []

async def db_get_all_users_cached(limit=200):
    cache_key = f"all_users_{limit}"
    cached = data_cache.get(cache_key)
    if cached is not None:
        return cached
    data = await db_get_all_users_uncached(limit)
    data_cache.set(cache_key, data)
    return data

async def db_get_all_users_uncached(limit=200):
    try:
        async with await get_db() as conn:
            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if not await cur.fetchone():
                return []
            cur = await conn.execute("""
                SELECT u.user_id, u.auto_publish, u.banned as user_banned, u.trial_used,
                u.subscription_end, u.auto_reply_enabled, u.auto_recycle,
                CASE WHEN bu.user_id IS NOT NULL THEN 1 ELSE 0 END as is_blocked,
                bu.reason as block_reason, bu.severity as block_severity
                FROM users u LEFT JOIN blocked_users bu ON u.user_id = bu.user_id
                ORDER BY u.user_id LIMIT ?
            """, (limit,))
            return await cur.fetchall()
    except:
        return []

async def db_block_user(user_id, reason, admin_id=1, severity="ban", duration_minutes=None):
    async with await get_db() as conn:
        expires = None
        if duration_minutes:
            expires = (datetime.utcnow() + timedelta(minutes=duration_minutes)).isoformat()
        await conn.execute(
            "INSERT OR REPLACE INTO blocked_users (user_id, reason, blocked_by, blocked_at, expires_at, severity) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, reason, admin_id, datetime.utcnow().isoformat(), expires, severity)
        )
        await conn.commit()
    stats_cache.cache.clear()
    data_cache.cache.clear()

async def db_unblock_user(user_id):
    async with await get_db() as conn:
        await conn.execute("DELETE FROM blocked_users WHERE user_id=?", (user_id,))
        await conn.commit()
    stats_cache.cache.clear()
    data_cache.cache.clear()

async def db_block_channel(channel_id, reason, admin_id=1):
    async with await get_db() as conn:
        await conn.execute("INSERT OR REPLACE INTO blocked_channels (channel_id, reason, blocked_by, blocked_at) VALUES (?, ?, ?, ?)",
            (channel_id, reason, admin_id, datetime.utcnow().isoformat()))
        await conn.commit()
    stats_cache.cache.clear()
    data_cache.cache.clear()

async def db_unblock_channel(channel_id):
    async with await get_db() as conn:
        await conn.execute("DELETE FROM blocked_channels WHERE channel_id=?", (channel_id,))
        await conn.commit()
    stats_cache.cache.clear()
    data_cache.cache.clear()

async def db_block_group(chat_id, reason, admin_id=1):
    async with await get_db() as conn:
        await conn.execute("INSERT OR REPLACE INTO blocked_groups (chat_id, reason, blocked_by, blocked_at) VALUES (?, ?, ?, ?)",
            (chat_id, reason, admin_id, datetime.utcnow().isoformat()))
        await conn.commit()
    stats_cache.cache.clear()
    data_cache.cache.clear()

async def db_unblock_group(chat_id):
    async with await get_db() as conn:
        await conn.execute("DELETE FROM blocked_groups WHERE chat_id=?", (chat_id,))
        await conn.commit()
    stats_cache.cache.clear()
    data_cache.cache.clear()

async def db_log_block_action(action, target, admin_id, reason, extra=""):
    async with await get_db() as conn:
        await conn.execute("INSERT INTO block_logs (action, target, admin_id, reason, extra, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (action, target, admin_id, reason, extra, datetime.utcnow().isoformat()))
        await conn.commit()

async def db_get_blocked_users(limit=100):
    try:
        async with await get_db() as conn:
            cur = await conn.execute("SELECT user_id, reason, blocked_by, blocked_at, expires_at, severity FROM blocked_users ORDER BY blocked_at DESC LIMIT ?", (limit,))
            return await cur.fetchall()
    except:
        return []

async def db_get_blocked_channels(limit=100):
    try:
        async with await get_db() as conn:
            cur = await conn.execute("SELECT channel_id, reason, blocked_by, blocked_at FROM blocked_channels ORDER BY blocked_at DESC LIMIT ?", (limit,))
            return await cur.fetchall()
    except:
        return []

async def db_get_blocked_groups(limit=100):
    try:
        async with await get_db() as conn:
            cur = await conn.execute("SELECT chat_id, reason, blocked_by, blocked_at FROM blocked_groups ORDER BY blocked_at DESC LIMIT ?", (limit,))
            return await cur.fetchall()
    except:
        return []

async def db_get_block_logs(limit=200, action=None):
    try:
        async with await get_db() as conn:
            if action:
                cur = await conn.execute("SELECT id, action, target, admin_id, reason, extra, created_at FROM block_logs WHERE action=? ORDER BY created_at DESC LIMIT ?", (action, limit))
            else:
                cur = await conn.execute("SELECT id, action, target, admin_id, reason, extra, created_at FROM block_logs ORDER BY created_at DESC LIMIT ?", (limit,))
            return await cur.fetchall()
    except:
        return []

# ===================== المصادقة والجلسات =====================

def generate_session_id():
    return secrets.token_urlsafe(24)

def create_session(user_id):
    session_id = generate_session_id()
    _sessions[session_id] = {
        'user_id': user_id,
        'created_at': time.time(),
        'expires_at': time.time() + _SESSION_TIMEOUT
    }
    return session_id

def validate_session(session_id):
    if session_id not in _sessions:
        return None
    session = _sessions[session_id]
    if time.time() > session['expires_at']:
        del _sessions[session_id]
        return None
    session['expires_at'] = time.time() + _SESSION_TIMEOUT
    return session['user_id']

def clear_expired_sessions():
    now = time.time()
    expired = [sid for sid, s in _sessions.items() if now > s['expires_at']]
    for sid in expired:
        del _sessions[sid]

async def check_auth(request):
    if request.path in ['/health']:
        return True

    # 1. التحقق من الرأس (Header)
    password = request.headers.get('X-Admin-Password')
    if password and password == ADMIN_PASSWORD:
        return True

    # 2. التحقق من الجلسة (Cookie)
    session_id = request.cookies.get('session_id')
    if session_id and validate_session(session_id):
        return True

    return False

# ===================== تطبيق الويب =====================
app = web.Application()

@web.middleware
async def auth_middleware(request, handler):
    if await check_auth(request):
        return await handler(request)
    if request.path.startswith('/api/'):
        return web.json_response({'error': 'غير مصرح', 'code': 'UNAUTHORIZED'}, status=401)
    # ✅ إرجاع صفحة تسجيل الدخول بدلاً من 401 مباشرة
    return web.Response(text=LOGIN_PAGE, content_type='text/html', status=401)

app.middlewares.append(auth_middleware)

# ===================== صفحات HTML =====================

LOGIN_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>تسجيل الدخول</title>
    <style>
        body { font-family: Arial; display: flex; justify-content: center; align-items: center; height: 100vh; background: #0d1117; color: #c9d1d9; }
        .login-box { background: #161b22; padding: 40px; border-radius: 12px; border: 1px solid #30363d; width: 350px; }
        h2 { text-align: center; color: #58a6ff; }
        input { width: 100%; padding: 10px; margin: 10px 0; background: #0d1117; border: 1px solid #30363d; border-radius: 6px; color: #fff; }
        button { width: 100%; padding: 10px; background: #58a6ff; color: #0d1117; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; }
        button:hover { opacity: 0.9; }
        .error { color: #f85149; text-align: center; margin-top: 10px; }
    </style>
</head>
<body>
    <div class="login-box">
        <h2>🔐 تسجيل الدخول</h2>
        <form action="/login" method="post">
            <input type="password" name="password" placeholder="كلمة المرور" required>
            <button type="submit">دخول</button>
        </form>
        <div id="error" class="error"></div>
    </div>
</body>
</html>
"""

MAIN_PAGE = """
<!DOCTYPE html>
<html dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>نظام الحظر المتطور v6.2</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg: #0d1117;
            --card: #161b22;
            --border: #30363d;
            --accent: #58a6ff;
            --success: #3fb950;
            --danger: #f85149;
            --warning: #d29922;
            --text: #c9d1d9;
            --text-muted: #8b949e;
        }
        @media (prefers-color-scheme: light) {
            :root {
                --bg: #f6f8fa;
                --card: #ffffff;
                --border: #d0d7de;
                --text: #24292f;
                --text-muted: #57606a;
            }
        }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); padding: 20px; }
        .container { max-width: 1400px; margin: auto; }
        .header { background: var(--card); padding: 20px; border-radius: 12px; border: 1px solid var(--border); margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 20px; }
        .stat-card { background: var(--card); padding: 16px; border-radius: 10px; border: 1px solid var(--border); text-align: center; }
        .stat-card .num { font-size: 28px; font-weight: 700; color: var(--accent); }
        .stat-card .num.danger { color: var(--danger); }
        .stat-card .num.success { color: var(--success); }
        .stat-card .num.warning { color: var(--warning); }
        .stat-card .label { font-size: 12px; color: var(--text-muted); }
        .tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px; }
        .tab-btn { padding: 8px 16px; border: 1px solid var(--border); border-radius: 8px; background: var(--card); color: var(--text-muted); cursor: pointer; }
        .tab-btn.active { background: var(--accent); color: var(--bg); border-color: var(--accent); }
        .tab-content { display: none; background: var(--card); border-radius: 12px; padding: 18px; border: 1px solid var(--border); }
        .tab-content.active { display: block; }
        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th { text-align: right; padding: 10px 12px; border-bottom: 2px solid var(--border); color: var(--text-muted); }
        td { padding: 8px 12px; border-bottom: 1px solid var(--border); }
        tr:hover { background: rgba(255,255,255,0.03); }
        .btn { padding: 4px 12px; border: none; border-radius: 6px; cursor: pointer; }
        .btn-success { background: var(--success); color: var(--bg); }
        .btn-danger { background: var(--danger); color: #fff; }
        .btn-primary { background: var(--accent); color: var(--bg); }
        .status-blocked { color: var(--danger); font-weight: 600; }
        .status-active { color: var(--success); font-weight: 600; }
        .toast { position: fixed; top: 20px; left: 50%; transform: translateX(-50%); padding: 12px 28px; border-radius: 8px; z-index: 9999; display: none; font-weight: 600; }
        .toast.success { background: var(--success); color: var(--bg); }
        .toast.error { background: var(--danger); color: #fff; }
        .search-box { padding: 6px 12px; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text); width: 200px; }
        .form-group { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; align-items: center; }
        .form-group input, .form-group textarea, .form-group select { padding: 8px 12px; background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text); flex: 1; }
        .table-wrap { overflow-x: auto; }
        .chart-container { height: 300px; margin: 20px 0; }
        @media (max-width: 768px) { .stats-grid { grid-template-columns: repeat(2, 1fr); } }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div><h1 style="color:var(--accent);">🛡️ نظام الحظر المتطور v6.2</h1><div class="subtitle" style="color:var(--text-muted);">ريلاكس مانيجر · تحكم كامل</div></div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                <button class="btn btn-primary" onclick="refreshData()">🔄 تحديث</button>
                <button class="btn btn-primary" onclick="exportCSV()">📥 تصدير CSV</button>
                <button class="btn btn-primary" onclick="toggleChart()">📊 الرسم البياني</button>
                <span style="font-size:12px;color:var(--text-muted);" id="lastUpdate"></span>
                <a href="/logout" style="color:var(--danger);">🚪 خروج</a>
            </div>
        </div>

        <div class="stats-grid" id="statsGrid">
            <div class="stat-card"><span class="icon">👤</span><div class="num" id="totalUsers">-</div><div class="label">إجمالي المستخدمين</div></div>
            <div class="stat-card"><span class="icon">🚫</span><div class="num danger" id="blockedUsers">-</div><div class="label">مستخدمون محظورون</div></div>
            <div class="stat-card"><span class="icon">📺</span><div class="num" id="totalChannels">-</div><div class="label">القنوات المضافة</div></div>
            <div class="stat-card"><span class="icon">🚫📺</span><div class="num danger" id="blockedChannels">-</div><div class="label">قنوات محظورة</div></div>
            <div class="stat-card"><span class="icon">👥</span><div class="num" id="totalGroups">-</div><div class="label">المجموعات المضافة</div></div>
            <div class="stat-card"><span class="icon">🚫👥</span><div class="num danger" id="blockedGroups">-</div><div class="label">مجموعات محظورة</div></div>
            <div class="stat-card"><span class="icon">📝</span><div class="num warning" id="pendingPosts">-</div><div class="label">منشورات غير منشورة</div></div>
            <div class="stat-card"><span class="icon">📊</span><div class="num success" id="todayBlocks">-</div><div class="label">حظر اليوم</div></div>
            <div class="stat-card"><span class="icon">📢</span><div class="num info" id="updatesChannel" style="font-size:16px;">-</div><div class="label">قناة التحديثات</div></div>
        </div>

        <div id="chartContainer" style="display:none;" class="chart-container">
            <canvas id="statsChart"></canvas>
        </div>

        <div class="tabs">
            <button class="tab-btn active" data-tab="all_groups">👥 جميع المجموعات</button>
            <button class="tab-btn" data-tab="all_channels">📺 جميع القنوات</button>
            <button class="tab-btn" data-tab="all_users">👤 جميع المستخدمين</button>
            <button class="tab-btn" data-tab="blocked_users">🚫 مستخدمون محظورون</button>
            <button class="tab-btn" data-tab="logs">📋 سجل الحظر</button>
            <button class="tab-btn" data-tab="add">➕ إضافة حظر</button>
        </div>

        <div class="tab-content active" id="tab-all_groups">
            <div class="actions-row">
                <input class="search-box" id="groupSearch" placeholder="🔍 بحث..." oninput="filterTable('allGroupsTable', this.value)">
                <span style="font-size:12px;color:var(--text-muted);">إجمالي: <span id="allGroupsCount">0</span></span>
            </div>
            <div class="table-wrap"><div id="allGroupsTable"><div class="empty-state">جاري التحميل...</div></div></div>
        </div>
        <div class="tab-content" id="tab-all_channels">
            <div class="actions-row">
                <input class="search-box" id="channelSearch" placeholder="🔍 بحث..." oninput="filterTable('allChannelsTable', this.value)">
                <span style="font-size:12px;color:var(--text-muted);">إجمالي: <span id="allChannelsCount">0</span></span>
            </div>
            <div class="table-wrap"><div id="allChannelsTable"><div class="empty-state">جاري التحميل...</div></div></div>
        </div>
        <div class="tab-content" id="tab-all_users">
            <div class="actions-row">
                <input class="search-box" id="userSearch" placeholder="🔍 بحث..." oninput="filterTable('allUsersTable', this.value)">
                <span style="font-size:12px;color:var(--text-muted);">إجمالي: <span id="allUsersCount">0</span></span>
            </div>
            <div class="table-wrap"><div id="allUsersTable"><div class="empty-state">جاري التحميل...</div></div></div>
        </div>
        <div class="tab-content" id="tab-blocked_users">
            <div id="blockedUsersTable"><div class="empty-state">جاري التحميل...</div></div>
        </div>
        <div class="tab-content" id="tab-logs">
            <div class="actions-row">
                <select id="logFilter" onchange="refreshData()" style="padding:6px 12px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);">
                    <option value="all">جميع الإجراءات</option>
                    <option value="BLOCK_USER">حظر مستخدم</option>
                    <option value="UNBLOCK_USER">إلغاء حظر</option>
                    <option value="BLOCK_CHANNEL">حظر قناة</option>
                    <option value="UNBLOCK_CHANNEL">إلغاء حظر قناة</option>
                    <option value="BLOCK_GROUP">حظر مجموعة</option>
                    <option value="UNBLOCK_GROUP">إلغاء حظر مجموعة</option>
                </select>
            </div>
            <div id="logsTable"><div class="empty-state">جاري التحميل...</div></div>
        </div>
        <div class="tab-content" id="tab-add">
            <h3 style="color:var(--accent);">➕ إضافة حظر جديد</h3>
            <div class="form-group">
                <select id="blockType"><option value="user">👤 مستخدم</option><option value="channel">📺 قناة</option><option value="group">👥 مجموعة</option></select>
                <input type="text" id="targetId" placeholder="المعرف" dir="ltr">
            </div>
            <div class="form-group">
                <select id="severity"><option value="warning">⚠️ تحذير</option><option value="mute">🔇 كتم</option><option value="ban">🚫 حظر مؤقت</option><option value="permanent">🔒 حظر دائم</option></select>
                <input type="number" id="duration" placeholder="المدة (دقائق)" min="1">
            </div>
            <div class="form-group">
                <textarea id="reasonText" placeholder="سبب الحظر..."></textarea>
            </div>
            <div class="form-group">
                <button class="btn btn-danger" onclick="addBlock()">🚫 حظر</button>
                <button class="btn btn-primary" onclick="clearForm()">🗑️ مسح</button>
            </div>
            <div id="addResult"></div>
        </div>
    </div>

    <div class="toast" id="toast"></div>

    <script>
        const API = window.location.origin;
        let chartInstance = null;

        async function fetchJSON(endpoint) {
            const res = await fetch(API + endpoint);
            if (!res.ok) throw new Error(await res.text());
            return res.json();
        }

        function showToast(msg, type='success') {
            const t = document.getElementById('toast');
            t.textContent = msg;
            t.className = 'toast ' + type;
            t.style.display = 'block';
            clearTimeout(t._hide);
            t._hide = setTimeout(() => t.style.display = 'none', 3000);
        }

        function severityLabel(s) {
            const map = {warning:'⚠️ تحذير', mute:'🔇 كتم', ban:'🚫 حظر مؤقت', permanent:'🔒 حظر دائم'};
            return map[s] || s;
        }

        function renderTable(data, cols, actions) {
            if (!data || !data.length) return '<div class="empty-state">📭 لا توجد بيانات</div>';
            let html = `<div class="table-wrap"><table><thead><tr>${cols.map(c => `<th>${c.label}</th>`).join('')}</tr></thead><tbody>`;
            data.forEach(row => {
                html += '<tr>';
                cols.forEach(c => {
                    let val = row[c.key] !== undefined && row[c.key] !== null ? row[c.key] : '-';
                    if (['blocked_at','created_at','expires_at','added_at'].includes(c.key) && val) {
                        try { val = new Date(val).toLocaleString('ar-EG'); } catch(e){}
                    }
                    if (c.key === 'severity' && val) val = severityLabel(val);
                    if (c.key === 'action') {
                        const colors = {BLOCK_USER:'danger',UNBLOCK_USER:'success',BLOCK_CHANNEL:'danger',UNBLOCK_CHANNEL:'success',BLOCK_GROUP:'danger',UNBLOCK_GROUP:'success'};
                        val = `<span class="badge badge-${colors[val] || 'info'}">${val}</span>`;
                    }
                    if (c.key === 'is_blocked' || c.key === 'banned' || c.key === 'user_banned') {
                        if (val == 1 || val == '1') val = '<span class="status-blocked">🚫 محظور</span>';
                        else val = '<span class="status-active">✅ نشط</span>';
                    }
                    html += `<td>${val}</td>`;
                });
                if (actions) html += `<td>${actions(row)}</td>`;
                html += '</tr>';
            });
            html += '</tbody></table></div>';
            return html;
        }

        async function refreshData() {
            try {
                const stats = await fetchJSON('/api/stats');
                document.getElementById('totalUsers').textContent = stats.total_users || 0;
                document.getElementById('blockedUsers').textContent = stats.blocked_users || 0;
                document.getElementById('blockedChannels').textContent = stats.blocked_channels || 0;
                document.getElementById('blockedGroups').textContent = stats.blocked_groups || 0;
                document.getElementById('totalChannels').textContent = stats.total_channels || 0;
                document.getElementById('totalGroups').textContent = stats.total_groups || 0;
                document.getElementById('pendingPosts').textContent = stats.pending_posts || 0;
                document.getElementById('todayBlocks').textContent = stats.today_blocks || 0;
                document.getElementById('updatesChannel').textContent = stats.updates_channel || 'غير محددة';
                document.getElementById('lastUpdate').textContent = '🕐 ' + new Date().toLocaleTimeString('ar-EG');

                updateChart(stats);

                const filter = document.getElementById('logFilter')?.value || 'all';
                const qs = filter !== 'all' ? '?action=' + filter : '';

                const [allGroups, allChannels, allUsers, blockedUsers, logs] = await Promise.all([
                    fetchJSON('/api/all_groups'),
                    fetchJSON('/api/all_channels'),
                    fetchJSON('/api/all_users'),
                    fetchJSON('/api/blocked_users'),
                    fetchJSON('/api/block_logs' + qs)
                ]);

                document.getElementById('allGroupsCount').textContent = allGroups.length;
                document.getElementById('allGroupsTable').innerHTML = renderTable(allGroups,
                    [{key:'chat_id',label:'المعرف'},{key:'chat_name',label:'الاسم'},{key:'username',label:'المعرف'},{key:'added_by',label:'أضيف بواسطة'},{key:'added_at',label:'التاريخ'},{key:'is_blocked',label:'الحالة'}]
                );

                document.getElementById('allChannelsCount').textContent = allChannels.length;
                document.getElementById('allChannelsTable').innerHTML = renderTable(allChannels,
                    [{key:'channel_id',label:'المعرف'},{key:'channel_name',label:'الاسم'},{key:'user_id',label:'المالك'},{key:'created_at',label:'التاريخ'},{key:'is_blocked',label:'الحالة'}]
                );

                document.getElementById('allUsersCount').textContent = allUsers.length;
                document.getElementById('allUsersTable').innerHTML = renderTable(allUsers,
                    [{key:'user_id',label:'المعرف'},{key:'auto_publish',label:'نشر تلقائي'},{key:'user_banned',label:'محظور'},{key:'trial_used',label:'التجربة'},{key:'is_blocked',label:'محظور من الحظر'}]
                );

                document.getElementById('blockedUsersTable').innerHTML = renderTable(blockedUsers,
                    [{key:'user_id',label:'المعرف'},{key:'reason',label:'السبب'},{key:'severity',label:'الخطورة'},{key:'blocked_by',label:'بواسطة'},{key:'blocked_at',label:'التاريخ'}],
                    row => `<button class="btn btn-success" onclick="unblock('user',${row.user_id})">🔓 إلغاء</button>`
                );

                document.getElementById('logsTable').innerHTML = renderTable(logs,
                    [{key:'action',label:'الإجراء'},{key:'target',label:'الهدف'},{key:'admin_id',label:'المشرف'},{key:'reason',label:'السبب'},{key:'created_at',label:'التاريخ'}]
                );

            } catch(e) {
                showToast('❌ فشل التحديث: ' + e.message, 'error');
            }
        }

        function updateChart(stats) {
            const ctx = document.getElementById('statsChart');
            if (!ctx) return;
            if (chartInstance) { chartInstance.destroy(); }
            if (document.getElementById('chartContainer').style.display === 'none') return;
            chartInstance = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: ['المستخدمين', 'محظورون', 'القنوات', 'المجموعات', 'منشورات معلقة'],
                    datasets: [{
                        label: 'الإحصائيات',
                        data: [
                            stats.total_users || 0,
                            stats.blocked_users || 0,
                            stats.total_channels || 0,
                            stats.total_groups || 0,
                            stats.pending_posts || 0
                        ],
                        backgroundColor: ['#58a6ff', '#f85149', '#3fb950', '#d29922', '#8b949e']
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { labels: { color: '#c9d1d9' } }
                    },
                    scales: {
                        y: { ticks: { color: '#c9d1d9' } },
                        x: { ticks: { color: '#c9d1d9' } }
                    }
                }
            });
        }

        function toggleChart() {
            const container = document.getElementById('chartContainer');
            container.style.display = container.style.display === 'none' ? 'block' : 'none';
            if (container.style.display === 'block') refreshData();
        }

        async function exportCSV() {
            try {
                const res = await fetch(API + '/api/export_csv');
                if (!res.ok) throw new Error('فشل التصدير');
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `data_${new Date().toISOString().slice(0,10)}.csv`;
                a.click();
                showToast('✅ تم التصدير بنجاح');
            } catch(e) {
                showToast('❌ فشل التصدير: ' + e.message, 'error');
            }
        }

        function filterTable(tableId, query) {
            const container = document.getElementById(tableId);
            if (!container) return;
            const table = container.querySelector('table');
            if (!table) return;
            const rows = table.querySelectorAll('tbody tr');
            const q = query.toLowerCase();
            rows.forEach(row => row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none');
        }

        async function unblock(type, id) {
            const names = {user:'المستخدم', channel:'القناة', group:'المجموعة'};
            if (!confirm(`هل أنت متأكد من إلغاء حظر ${names[type]}؟`)) return;
            try {
                const res = await fetch(API + '/api/unblock', {
                    method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify({type, id})
                });
                const data = await res.json();
                if (data.success) { showToast('✅ تم إلغاء الحظر'); refreshData(); }
                else showToast('❌ ' + data.error, 'error');
            } catch(e) { showToast('❌ فشل: ' + e.message, 'error'); }
        }

        async function addBlock() {
            const type = document.getElementById('blockType').value;
            const id = document.getElementById('targetId').value.trim();
            const reason = document.getElementById('reasonText').value.trim();
            const severity = document.getElementById('severity').value;
            const duration = document.getElementById('duration').value.trim();

            if (!id) { showToast('❌ الرجاء إدخال المعرف', 'error'); return; }
            if (!reason) { showToast('❌ الرجاء إدخال سبب الحظر', 'error'); return; }

            const data = {type, id: parseInt(id), reason, severity};
            if (duration) data.duration = parseInt(duration);

            try {
                const res = await fetch(API + '/api/block', {
                    method: 'POST',
                    headers: {'Content-Type':'application/json'},
                    body: JSON.stringify(data)
                });
                const result = await res.json();
                if (result.success) {
                    showToast('✅ تم الحظر بنجاح');
                    document.getElementById('targetId').value = '';
                    document.getElementById('reasonText').value = '';
                    document.getElementById('duration').value = '';
                    refreshData();
                } else showToast('❌ ' + result.error, 'error');
            } catch(e) { showToast('❌ فشل: ' + e.message, 'error'); }
        }

        function clearForm() {
            document.getElementById('targetId').value = '';
            document.getElementById('reasonText').value = '';
            document.getElementById('duration').value = '';
            document.getElementById('addResult').innerHTML = '';
        }

        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
                document.getElementById('tab-' + this.dataset.tab).classList.add('active');
            });
        });

        refreshData();
        setInterval(refreshData, 30000);
    </script>
</body>
</html>
"""

# ===================== نقاط النهاية =====================

async def login_handler(request):
    """معالج تسجيل الدخول - يدعم GET و POST"""
    if request.method == 'GET':
        return web.Response(text=LOGIN_PAGE, content_type='text/html')

    try:
        # ✅ استقبال البيانات من النموذج
        data = await request.post()
        password = data.get('password', '')

        print(f"🔍 محاولة تسجيل الدخول: كلمة المرور المدخلة = '{password}'")
        print(f"🔍 كلمة المرور المتوقعة = '{ADMIN_PASSWORD}'")

        if password and password == ADMIN_PASSWORD:
            # ✅ إنشاء جلسة
            session_id = create_session(1)
            response = web.HTTPFound('/panel')
            response.set_cookie('session_id', session_id, max_age=_SESSION_TIMEOUT, httponly=True, secure=True)
            print("✅ تسجيل الدخول ناجح")
            return response
        else:
            print("❌ كلمة مرور خاطئة")
            # إرجاع صفحة الدخول مع رسالة خطأ
            error_page = LOGIN_PAGE.replace('</form>', '</form><div class="error">❌ كلمة مرور خاطئة</div>')
            return web.Response(text=error_page, content_type='text/html', status=401)
    except Exception as e:
        print(f"⚠️ خطأ في login_handler: {e}")
        return web.Response(text=LOGIN_PAGE, content_type='text/html', status=401)

async def logout_handler(request):
    response = web.HTTPFound('/login')
    response.del_cookie('session_id')
    return response

async def index_handler(request):
    return web.Response(text=MAIN_PAGE, content_type='text/html')

async def health_handler(request):
    return web.json_response({"status": "ok", "timestamp": time.time(), "version": "6.2"})

async def stats_handler(request):
    return web.json_response(await db_stats_cached())

async def api_blocked_users(request):
    return web.json_response([dict(u) for u in await db_get_blocked_users(200)])

async def api_blocked_channels(request):
    return web.json_response([dict(c) for c in await db_get_blocked_channels(100)])

async def api_blocked_groups(request):
    return web.json_response([dict(g) for g in await db_get_blocked_groups(100)])

async def api_all_groups(request):
    return web.json_response([dict(g) for g in await db_get_all_groups_cached(200)])

async def api_all_channels(request):
    return web.json_response([dict(c) for c in await db_get_all_channels_cached(200)])

async def api_all_users(request):
    return web.json_response([dict(u) for u in await db_get_all_users_cached(200)])

async def api_block_logs(request):
    action = request.query.get('action')
    return web.json_response([dict(l) for l in await db_get_block_logs(200, action)])

async def api_export_csv(request):
    try:
        groups = await db_get_all_groups_uncached(10000)
        channels = await db_get_all_channels_uncached(10000)
        users = await db_get_all_users_uncached(10000)
        logs = await db_get_block_logs(10000)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['نوع', 'المعرف', 'الاسم', 'الحالة', 'التاريخ'])
        for g in groups:
            writer.writerow(['مجموعة', g['chat_id'], g['chat_name'], 'محظور' if g['is_blocked'] else 'نشط', g['added_at']])
        for c in channels:
            writer.writerow(['قناة', c['channel_id'], c['channel_name'], 'محظورة' if c['is_blocked'] else 'نشطة', c['created_at']])
        for u in users:
            writer.writerow(['مستخدم', u['user_id'], '', 'محظور' if u['is_blocked'] else 'نشط', ''])
        for l in logs:
            writer.writerow(['سجل', l['target'], l['action'], l['reason'], l['created_at']])

        response = web.Response(text=output.getvalue(), content_type='text/csv')
        response.headers['Content-Disposition'] = f'attachment; filename="data_{datetime.utcnow().date().isoformat()}.csv"'
        return response
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def api_block(request):
    try:
        data = await request.json()
        t = data.get('type')
        target = data.get('id')
        reason = data.get('reason')
        severity = data.get('severity', 'ban')
        duration = data.get('duration')

        if not target or not reason:
            return web.json_response({'success': False, 'error': 'بيانات ناقصة'}, status=400)

        if t == 'user':
            await db_block_user(target, reason, 1, severity, duration)
            await db_log_block_action('BLOCK_USER', target, 1, reason, f"severity:{severity},duration:{duration}")
        elif t == 'channel':
            await db_block_channel(target, reason, 1)
            await db_log_block_action('BLOCK_CHANNEL', target, 1, reason, f"severity:{severity}")
        elif t == 'group':
            await db_block_group(target, reason, 1)
            await db_log_block_action('BLOCK_GROUP', target, 1, reason, f"severity:{severity}")
        else:
            return web.json_response({'success': False, 'error': 'نوع غير صالح'}, status=400)

        return web.json_response({'success': True})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def api_unblock(request):
    try:
        data = await request.json()
        t = data.get('type')
        target = data.get('id')

        if not target:
            return web.json_response({'success': False, 'error': 'بيانات ناقصة'}, status=400)

        if t == 'user':
            await db_unblock_user(target)
            await db_log_block_action('UNBLOCK_USER', target, 1, 'إلغاء حظر')
        elif t == 'channel':
            await db_unblock_channel(target)
            await db_log_block_action('UNBLOCK_CHANNEL', target, 1, 'إلغاء حظر')
        elif t == 'group':
            await db_unblock_group(target)
            await db_log_block_action('UNBLOCK_GROUP', target, 1, 'إلغاء حظر')
        else:
            return web.json_response({'success': False, 'error': 'نوع غير صالح'}, status=400)

        return web.json_response({'success': True})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)}, status=500)

# ===================== تسجيل المسارات =====================
app.router.add_get('/', index_handler)
app.router.add_get('/login', login_handler)
app.router.add_post('/login', login_handler)
app.router.add_get('/logout', logout_handler)
app.router.add_get('/panel', index_handler)
app.router.add_get('/web', index_handler)
app.router.add_get('/health', health_handler)
app.router.add_get('/api/stats', stats_handler)
app.router.add_get('/api/blocked_users', api_blocked_users)
app.router.add_get('/api/blocked_channels', api_blocked_channels)
app.router.add_get('/api/blocked_groups', api_blocked_groups)
app.router.add_get('/api/all_groups', api_all_groups)
app.router.add_get('/api/all_channels', api_all_channels)
app.router.add_get('/api/all_users', api_all_users)
app.router.add_get('/api/block_logs', api_block_logs)
app.router.add_get('/api/export_csv', api_export_csv)
app.router.add_post('/api/block', api_block)
app.router.add_post('/api/unblock', api_unblock)

# ===================== تشغيل الخادم =====================

def start_web_server_background(port=None):
    global _SERVER_STARTED
    with _SERVER_LOCK:
        if _SERVER_STARTED:
            logger.info("⚠️ خادم الويب يعمل بالفعل")
            return
        _SERVER_STARTED = True

    if port is None:
        port = int(os.getenv('PORT', os.getenv('WEB_PORT', 10000)))

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        try:
            site = web.TCPSite(runner, '0.0.0.0', port)
            loop.run_until_complete(site.start())
            logger.info(f"✅ نظام الحظر v6.2 يعمل على http://0.0.0.0:{port}")
            print(f"✅ خادم الويب شغال على المنفذ {port}")
        except OSError as e:
            if "address already in use" in str(e):
                site = web.TCPSite(runner, '0.0.0.0', 0)
                loop.run_until_complete(site.start())
                actual = site._server.sockets[0].getsockname()[1]
                logger.info(f"✅ يعمل على http://0.0.0.0:{actual} (منفذ عشوائي)")
                print(f"✅ خادم الويب شغال على منفذ عشوائي: {actual}")
            else:
                raise
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(runner.cleanup())
            loop.close()

    threading.Thread(target=run, daemon=True).start()
    logger.info("🚀 تم تشغيل نظام الحظر v6.2")
    print("🚀 نظام الحظر v6.2 بدأ العمل")

if __name__ == '__main__':
    # تأكد من وجود قاعدة البيانات
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    port = int(os.getenv('PORT', os.getenv('WEB_PORT', 10000)))
    start_web_server_background(port)
    print(f"🌐 نظام الحظر v6.2 متاح على:")
    print(f"   - http://0.0.0.0:{port}")
    print(f"   - http://0.0.0.0:{port}/panel")
    print(f"   - http://0.0.0.0:{port}/health")
    print(f"🔑 كلمة المرور: {ADMIN_PASSWORD}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف النظام")
