#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
خادم الويب المتطور - نظام الحظر الشامل (القنوات، المجموعات، المستخدمين)
الإصدار: 3.0 - مع واجهة إدارة كاملة
"""

import os
import asyncio
import logging
import threading
import json
import time
from datetime import datetime, timedelta
from aiohttp import web, web_exceptions
import aiosqlite

logger = logging.getLogger(__name__)

# ===================== إعدادات =====================
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bot_data.db")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# ===================== دوال قاعدة البيانات =====================

async def get_db():
    """الحصول على اتصال قاعدة البيانات"""
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    return conn

async def db_get_blocked_users(limit=50):
    async with await get_db() as conn:
        cur = await conn.execute(
            "SELECT user_id, reason, blocked_by, blocked_at, expires_at FROM blocked_users ORDER BY blocked_at DESC LIMIT ?",
            (limit,)
        )
        return await cur.fetchall()

async def db_get_blocked_channels(limit=50):
    async with await get_db() as conn:
        cur = await conn.execute(
            "SELECT channel_id, reason, blocked_by, blocked_at FROM blocked_channels ORDER BY blocked_at DESC LIMIT ?",
            (limit,)
        )
        return await cur.fetchall()

async def db_get_blocked_groups(limit=50):
    async with await get_db() as conn:
        cur = await conn.execute(
            "SELECT chat_id, reason, blocked_by, blocked_at FROM blocked_groups ORDER BY blocked_at DESC LIMIT ?",
            (limit,)
        )
        return await cur.fetchall()

async def db_get_block_logs(limit=50):
    async with await get_db() as conn:
        cur = await conn.execute(
            "SELECT id, action, target, admin_id, reason, extra, created_at FROM block_logs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        return await cur.fetchall()

async def db_block_user(user_id, reason, admin_id=1):
    async with await get_db() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO blocked_users (user_id, reason, blocked_by, blocked_at) VALUES (?, ?, ?, ?)",
            (user_id, reason, admin_id, datetime.utcnow().isoformat())
        )
        await conn.commit()

async def db_unblock_user(user_id):
    async with await get_db() as conn:
        await conn.execute("DELETE FROM blocked_users WHERE user_id=?", (user_id,))
        await conn.commit()

async def db_block_channel(channel_id, reason, admin_id=1):
    async with await get_db() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO blocked_channels (channel_id, reason, blocked_by, blocked_at) VALUES (?, ?, ?, ?)",
            (channel_id, reason, admin_id, datetime.utcnow().isoformat())
        )
        await conn.commit()

async def db_unblock_channel(channel_id):
    async with await get_db() as conn:
        await conn.execute("DELETE FROM blocked_channels WHERE channel_id=?", (channel_id,))
        await conn.commit()

async def db_block_group(chat_id, reason, admin_id=1):
    async with await get_db() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO blocked_groups (chat_id, reason, blocked_by, blocked_at) VALUES (?, ?, ?, ?)",
            (chat_id, reason, admin_id, datetime.utcnow().isoformat())
        )
        await conn.commit()

async def db_unblock_group(chat_id):
    async with await get_db() as conn:
        await conn.execute("DELETE FROM blocked_groups WHERE chat_id=?", (chat_id,))
        await conn.commit()

async def db_log_block_action(action, target, admin_id, reason, extra=""):
    async with await get_db() as conn:
        await conn.execute(
            "INSERT INTO block_logs (action, target, admin_id, reason, extra, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (action, target, admin_id, reason, extra, datetime.utcnow().isoformat())
        )
        await conn.commit()

async def db_stats():
    async with await get_db() as conn:
        total_users = (await conn.execute("SELECT COUNT(*) FROM users")).fetchone()[0]
        blocked_users = (await conn.execute("SELECT COUNT(*) FROM blocked_users")).fetchone()[0]
        blocked_channels = (await conn.execute("SELECT COUNT(*) FROM blocked_channels")).fetchone()[0]
        blocked_groups = (await conn.execute("SELECT COUNT(*) FROM blocked_groups")).fetchone()[0]
        return {
            'total_users': total_users,
            'blocked_users': blocked_users,
            'blocked_channels': blocked_channels,
            'blocked_groups': blocked_groups
        }

# ===================== تطبيق الويب =====================
app = web.Application()

# ===================== معالجات نقاط النهاية =====================

async def index_handler(request):
    """الصفحة الرئيسية"""
    html = """
    <!DOCTYPE html>
    <html dir="rtl">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>لوحة تحكم الحظر - ريلاكس مانيجر</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: #f0f2f5;
                padding: 20px;
                color: #333;
            }
            .container {
                max-width: 1200px;
                margin: auto;
            }
            .header {
                background: linear-gradient(135deg, #1a1a2e, #16213e);
                color: white;
                padding: 25px 30px;
                border-radius: 16px;
                margin-bottom: 25px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                flex-wrap: wrap;
            }
            .header h1 { font-size: 26px; }
            .header .subtitle { font-size: 14px; opacity: 0.8; }
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }
            .stat-card {
                background: white;
                padding: 20px;
                border-radius: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.08);
                text-align: center;
            }
            .stat-card .number {
                font-size: 32px;
                font-weight: bold;
                color: #1a1a2e;
            }
            .stat-card .label {
                font-size: 14px;
                color: #666;
                margin-top: 5px;
            }
            .stat-card .icon { font-size: 28px; display: block; margin-bottom: 8px; }
            .tabs {
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
                margin-bottom: 20px;
            }
            .tab-btn {
                padding: 12px 24px;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                cursor: pointer;
                background: #e0e0e0;
                transition: all 0.3s;
                font-weight: 600;
            }
            .tab-btn.active {
                background: #1a1a2e;
                color: white;
            }
            .tab-btn:hover { opacity: 0.8; }
            .tab-content {
                display: none;
                background: white;
                border-radius: 12px;
                padding: 20px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            }
            .tab-content.active { display: block; }
            table {
                width: 100%;
                border-collapse: collapse;
                font-size: 14px;
            }
            th {
                background: #f7f7f7;
                padding: 12px;
                text-align: right;
                border-bottom: 2px solid #ddd;
            }
            td {
                padding: 12px;
                border-bottom: 1px solid #eee;
                word-break: break-word;
            }
            .btn {
                padding: 6px 14px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 13px;
                font-weight: 600;
                transition: all 0.3s;
            }
            .btn-danger { background: #dc3545; color: white; }
            .btn-danger:hover { background: #c82333; }
            .btn-success { background: #28a745; color: white; }
            .btn-success:hover { background: #218838; }
            .btn-primary { background: #007bff; color: white; }
            .btn-primary:hover { background: #0069d9; }
            .form-group {
                margin-bottom: 15px;
                display: flex;
                gap: 10px;
                flex-wrap: wrap;
                align-items: center;
            }
            .form-group input, .form-group textarea {
                padding: 10px 14px;
                border: 1px solid #ddd;
                border-radius: 6px;
                font-size: 14px;
                flex: 1;
                min-width: 200px;
            }
            .form-group textarea { min-height: 60px; }
            .empty-state {
                text-align: center;
                padding: 40px;
                color: #999;
                font-size: 16px;
            }
            .badge {
                display: inline-block;
                padding: 3px 10px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: 600;
            }
            .badge-danger { background: #f8d7da; color: #721c24; }
            .badge-success { background: #d4edda; color: #155724; }
            .badge-warning { background: #fff3cd; color: #856404; }
            .toast {
                position: fixed;
                top: 20px;
                left: 50%;
                transform: translateX(-50%);
                background: #333;
                color: white;
                padding: 16px 30px;
                border-radius: 8px;
                z-index: 9999;
                display: none;
                animation: slideDown 0.3s ease;
            }
            .toast.success { background: #28a745; }
            .toast.error { background: #dc3545; }
            @keyframes slideDown {
                from { opacity: 0; transform: translateX(-50%) translateY(-20px); }
                to { opacity: 1; transform: translateX(-50%) translateY(0); }
            }
            @media (max-width: 768px) {
                .header { flex-direction: column; text-align: center; gap: 10px; }
                .stats-grid { grid-template-columns: repeat(2, 1fr); }
                .tabs { justify-content: center; }
                .tab-btn { flex: 1; min-width: 100px; text-align: center; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div>
                    <h1>🛡️ لوحة تحكم الحظر</h1>
                    <div class="subtitle">ريلاكس مانيجر · إدارة متقدمة للمستخدمين والقنوات والمجموعات</div>
                </div>
                <div>
                    <button class="btn btn-primary" onclick="refreshData()">🔄 تحديث</button>
                    <span style="margin-right:10px;font-size:14px;opacity:0.8;" id="lastUpdate"></span>
                </div>
            </div>

            <div class="stats-grid" id="statsGrid">
                <div class="stat-card"><span class="icon">👤</span><div class="number" id="totalUsers">-</div><div class="label">إجمالي المستخدمين</div></div>
                <div class="stat-card"><span class="icon">🚫</span><div class="number" id="blockedUsers">-</div><div class="label">مستخدمون محظورون</div></div>
                <div class="stat-card"><span class="icon">📺</span><div class="number" id="blockedChannels">-</div><div class="label">قنوات محظورة</div></div>
                <div class="stat-card"><span class="icon">👥</span><div class="number" id="blockedGroups">-</div><div class="label">مجموعات محظورة</div></div>
            </div>

            <div class="tabs">
                <button class="tab-btn active" data-tab="users">👤 المستخدمين</button>
                <button class="tab-btn" data-tab="channels">📺 القنوات</button>
                <button class="tab-btn" data-tab="groups">👥 المجموعات</button>
                <button class="tab-btn" data-tab="logs">📋 سجل الحظر</button>
                <button class="tab-btn" data-tab="add">➕ إضافة حظر</button>
            </div>

            <!-- تبويب المستخدمين -->
            <div class="tab-content active" id="tab-users">
                <h3>👤 المستخدمون المحظورون</h3>
                <div id="usersTable"><div class="empty-state">جاري التحميل...</div></div>
            </div>

            <!-- تبويب القنوات -->
            <div class="tab-content" id="tab-channels">
                <h3>📺 القنوات المحظورة</h3>
                <div id="channelsTable"><div class="empty-state">جاري التحميل...</div></div>
            </div>

            <!-- تبويب المجموعات -->
            <div class="tab-content" id="tab-groups">
                <h3>👥 المجموعات المحظورة</h3>
                <div id="groupsTable"><div class="empty-state">جاري التحميل...</div></div>
            </div>

            <!-- تبويب السجل -->
            <div class="tab-content" id="tab-logs">
                <h3>📋 سجل عمليات الحظر</h3>
                <div id="logsTable"><div class="empty-state">جاري التحميل...</div></div>
            </div>

            <!-- تبويب إضافة حظر -->
            <div class="tab-content" id="tab-add">
                <h3>➕ إضافة حظر جديد</h3>
                <div class="form-group">
                    <select id="blockType" style="padding:10px 14px;border:1px solid #ddd;border-radius:6px;font-size:14px;">
                        <option value="user">👤 مستخدم</option>
                        <option value="channel">📺 قناة</option>
                        <option value="group">👥 مجموعة</option>
                    </select>
                    <input type="text" id="targetId" placeholder="المعرف (مثال: 123456789)" dir="ltr">
                </div>
                <div class="form-group">
                    <textarea id="reasonText" placeholder="سبب الحظر..."></textarea>
                </div>
                <div class="form-group">
                    <button class="btn btn-danger" onclick="addBlock()">🚫 حظر</button>
                </div>
                <div id="addResult"></div>
            </div>

        </div>

        <div class="toast" id="toast"></div>

        <script>
            const API_BASE = window.location.origin;

            async function fetchJSON(endpoint) {
                const res = await fetch(API_BASE + endpoint);
                if (!res.ok) throw new Error(await res.text());
                return res.json();
            }

            function showToast(msg, type = 'success') {
                const t = document.getElementById('toast');
                t.textContent = msg;
                t.className = 'toast ' + type;
                t.style.display = 'block';
                clearTimeout(t._hide);
                t._hide = setTimeout(() => t.style.display = 'none', 4000);
            }

            function renderTable(data, columns, actions) {
                if (!data || data.length === 0) return '<div class="empty-state">📭 لا توجد بيانات</div>';
                let html = `<table><thead><tr>${columns.map(c => `<th>${c.label}</th>`).join('')}</tr></thead><tbody>`;
                data.forEach(row => {
                    html += '<tr>';
                    columns.forEach(c => {
                        let val = row[c.key] !== undefined ? row[c.key] : '-';
                        if (c.key === 'blocked_at' || c.key === 'created_at') {
                            try { val = new Date(val).toLocaleString('ar-EG'); } catch(e){}
                        }
                        html += `<td>${val}</td>`;
                    });
                    if (actions) {
                        html += `<td>${actions(row)}</td>`;
                    }
                    html += '</tr>';
                });
                html += '</tbody></table>';
                return html;
            }

            async function refreshData() {
                try {
                    // الإحصائيات
                    const stats = await fetchJSON('/api/stats');
                    document.getElementById('totalUsers').textContent = stats.total_users || 0;
                    document.getElementById('blockedUsers').textContent = stats.blocked_users || 0;
                    document.getElementById('blockedChannels').textContent = stats.blocked_channels || 0;
                    document.getElementById('blockedGroups').textContent = stats.blocked_groups || 0;
                    document.getElementById('lastUpdate').textContent = '🕐 ' + new Date().toLocaleTimeString('ar-EG');

                    // المستخدمون
                    const users = await fetchJSON('/api/blocked_users');
                    document.getElementById('usersTable').innerHTML = renderTable(users,
                        [{key:'user_id',label:'المعرف'},{key:'reason',label:'السبب'},{key:'blocked_by',label:'بواسطة'},{key:'blocked_at',label:'التاريخ'}],
                        (row) => `<button class="btn btn-success" onclick="unblock('user', ${row.user_id})">🔓 إلغاء</button>`
                    );

                    // القنوات
                    const channels = await fetchJSON('/api/blocked_channels');
                    document.getElementById('channelsTable').innerHTML = renderTable(channels,
                        [{key:'channel_id',label:'المعرف'},{key:'reason',label:'السبب'},{key:'blocked_by',label:'بواسطة'},{key:'blocked_at',label:'التاريخ'}],
                        (row) => `<button class="btn btn-success" onclick="unblock('channel', ${row.channel_id})">🔓 إلغاء</button>`
                    );

                    // المجموعات
                    const groups = await fetchJSON('/api/blocked_groups');
                    document.getElementById('groupsTable').innerHTML = renderTable(groups,
                        [{key:'chat_id',label:'المعرف'},{key:'reason',label:'السبب'},{key:'blocked_by',label:'بواسطة'},{key:'blocked_at',label:'التاريخ'}],
                        (row) => `<button class="btn btn-success" onclick="unblock('group', ${row.chat_id})">🔓 إلغاء</button>`
                    );

                    // السجل
                    const logs = await fetchJSON('/api/block_logs');
                    document.getElementById('logsTable').innerHTML = renderTable(logs,
                        [{key:'action',label:'الإجراء'},{key:'target',label:'الهدف'},{key:'admin_id',label:'المشرف'},{key:'reason',label:'السبب'},{key:'created_at',label:'التاريخ'}]
                    );

                } catch(e) {
                    showToast('فشل التحديث: ' + e.message, 'error');
                }
            }

            async function unblock(type, id) {
                if (!confirm(`هل أنت متأكد من إلغاء حظر هذا ${type === 'user' ? 'المستخدم' : type === 'channel' ? 'القناة' : 'المجموعة'}؟`)) return;
                try {
                    const res = await fetch(API_BASE + '/api/unblock', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({type, id})
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast('✅ تم إلغاء الحظر بنجاح');
                        refreshData();
                    } else {
                        showToast('❌ ' + data.error, 'error');
                    }
                } catch(e) {
                    showToast('❌ فشل: ' + e.message, 'error');
                }
            }

            async function addBlock() {
                const type = document.getElementById('blockType').value;
                const id = document.getElementById('targetId').value.trim();
                const reason = document.getElementById('reasonText').value.trim();

                if (!id) { showToast('❌ الرجاء إدخال المعرف', 'error'); return; }
                if (!reason) { showToast('❌ الرجاء إدخال سبب الحظر', 'error'); return; }
                if (isNaN(id) && type !== 'channel' && type !== 'group') {
                    showToast('❌ المعرف يجب أن يكون رقماً', 'error');
                    return;
                }

                try {
                    const res = await fetch(API_BASE + '/api/block', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({type, id: parseInt(id), reason})
                    });
                    const data = await res.json();
                    if (data.success) {
                        showToast('✅ تم الحظر بنجاح');
                        document.getElementById('targetId').value = '';
                        document.getElementById('reasonText').value = '';
                        refreshData();
                    } else {
                        showToast('❌ ' + data.error, 'error');
                    }
                } catch(e) {
                    showToast('❌ فشل: ' + e.message, 'error');
                }
            }

            // تبديل التبويبات
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.addEventListener('click', function() {
                    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                    this.classList.add('active');
                    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
                    document.getElementById('tab-' + this.dataset.tab).classList.add('active');
                });
            });

            // تحديث تلقائي كل 30 ثانية
            refreshData();
            setInterval(refreshData, 30000);
        </script>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

# ===================== نقاط نهاية API =====================

async def api_stats(request):
    stats = await db_stats()
    return web.json_response(stats)

async def api_blocked_users(request):
    users = await db_get_blocked_users(100)
    return web.json_response([dict(u) for u in users])

async def api_blocked_channels(request):
    channels = await db_get_blocked_channels(100)
    return web.json_response([dict(c) for c in channels])

async def api_blocked_groups(request):
    groups = await db_get_blocked_groups(100)
    return web.json_response([dict(g) for g in groups])

async def api_block_logs(request):
    logs = await db_get_block_logs(100)
    return web.json_response([dict(l) for l in logs])

async def api_block(request):
    try:
        data = await request.json()
        block_type = data.get('type')
        target_id = data.get('id')
        reason = data.get('reason')

        if not target_id or not reason:
            return web.json_response({'success': False, 'error': 'بيانات ناقصة'}, status=400)

        if block_type == 'user':
            await db_block_user(target_id, reason, 1)
            await db_log_block_action('BLOCK_USER', target_id, 1, reason)
        elif block_type == 'channel':
            await db_block_channel(target_id, reason, 1)
            await db_log_block_action('BLOCK_CHANNEL', target_id, 1, reason)
        elif block_type == 'group':
            await db_block_group(target_id, reason, 1)
            await db_log_block_action('BLOCK_GROUP', target_id, 1, reason)
        else:
            return web.json_response({'success': False, 'error': 'نوع غير صالح'}, status=400)

        return web.json_response({'success': True})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)}, status=500)

async def api_unblock(request):
    try:
        data = await request.json()
        block_type = data.get('type')
        target_id = data.get('id')

        if not target_id:
            return web.json_response({'success': False, 'error': 'بيانات ناقصة'}, status=400)

        if block_type == 'user':
            await db_unblock_user(target_id)
            await db_log_block_action('UNBLOCK_USER', target_id, 1, 'إلغاء حظر')
        elif block_type == 'channel':
            await db_unblock_channel(target_id)
            await db_log_block_action('UNBLOCK_CHANNEL', target_id, 1, 'إلغاء حظر')
        elif block_type == 'group':
            await db_unblock_group(target_id)
            await db_log_block_action('UNBLOCK_GROUP', target_id, 1, 'إلغاء حظر')
        else:
            return web.json_response({'success': False, 'error': 'نوع غير صالح'}, status=400)

        return web.json_response({'success': True})
    except Exception as e:
        return web.json_response({'success': False, 'error': str(e)}, status=500)

# تسجيل نقاط النهاية
app.router.add_get('/', index_handler)
app.router.add_get('/api/stats', api_stats)
app.router.add_get('/api/blocked_users', api_blocked_users)
app.router.add_get('/api/blocked_channels', api_blocked_channels)
app.router.add_get('/api/blocked_groups', api_blocked_groups)
app.router.add_get('/api/block_logs', api_block_logs)
app.router.add_post('/api/block', api_block)
app.router.add_post('/api/unblock', api_unblock)

# ===================== تشغيل الخادم =====================

def start_web_server_background(port: int = None):
    """تشغيل خادم الويب في الخلفية"""
    if port is None:
        port = int(os.getenv('PORT', os.getenv('WEB_PORT', 8080)))

    def run_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())

        try:
            site = web.TCPSite(runner, '0.0.0.0', port)
            loop.run_until_complete(site.start())
            logger.info(f"✅ خادم الويب المتطور يعمل على http://0.0.0.0:{port}")
        except OSError as e:
            if "address already in use" in str(e):
                site = web.TCPSite(runner, '0.0.0.0', 0)
                loop.run_until_complete(site.start())
                actual = site._server.sockets[0].getsockname()[1]
                logger.info(f"✅ خادم الويب يعمل على http://0.0.0.0:{actual} (منفذ عشوائي)")
            else:
                raise

        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(runner.cleanup())
            loop.close()

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    logger.info("🚀 تم تشغيل خادم الويب المتطور في الخلفية")

if __name__ == '__main__':
    port = int(os.getenv('PORT', os.getenv('WEB_PORT', 8080)))
    start_web_server_background(port)
    print(f"🌐 خادم الويب متاح على http://0.0.0.0:{port}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف الخادم")
