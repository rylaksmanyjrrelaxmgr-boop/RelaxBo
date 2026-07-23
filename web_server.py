#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام الحظر المتطور - الإصدار 5.1
ريلاكس مانيجر · إدارة متقدمة للمستخدمين والقنوات والمجموعات
"""

import os
import asyncio
import logging
import threading
import json
import time
from datetime import datetime, timedelta
from aiohttp import web
import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bot_data.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

async def get_db():
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    return conn

async def init_db():
    async with await get_db() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked_users (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                blocked_by INTEGER,
                blocked_at TIMESTAMP,
                expires_at TIMESTAMP,
                severity TEXT DEFAULT 'ban'
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked_channels (
                channel_id INTEGER PRIMARY KEY,
                reason TEXT,
                blocked_by INTEGER,
                blocked_at TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS blocked_groups (
                chat_id INTEGER PRIMARY KEY,
                reason TEXT,
                blocked_by INTEGER,
                blocked_at TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS block_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT,
                target INTEGER,
                admin_id INTEGER,
                reason TEXT,
                extra TEXT,
                created_at TIMESTAMP
            )
        """)
        await conn.commit()

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

async def db_get_blocked_users(limit=100):
    async with await get_db() as conn:
        cur = await conn.execute(
            "SELECT user_id, reason, blocked_by, blocked_at, expires_at, severity FROM blocked_users ORDER BY blocked_at DESC LIMIT ?",
            (limit,)
        )
        return await cur.fetchall()

async def db_get_blocked_channels(limit=100):
    async with await get_db() as conn:
        cur = await conn.execute(
            "SELECT channel_id, reason, blocked_by, blocked_at FROM blocked_channels ORDER BY blocked_at DESC LIMIT ?",
            (limit,)
        )
        return await cur.fetchall()

async def db_get_blocked_groups(limit=100):
    async with await get_db() as conn:
        cur = await conn.execute(
            "SELECT chat_id, reason, blocked_by, blocked_at FROM blocked_groups ORDER BY blocked_at DESC LIMIT ?",
            (limit,)
        )
        return await cur.fetchall()

async def db_get_block_logs(limit=200, action=None):
    async with await get_db() as conn:
        if action:
            cur = await conn.execute(
                "SELECT id, action, target, admin_id, reason, extra, created_at FROM block_logs WHERE action=? ORDER BY created_at DESC LIMIT ?",
                (action, limit)
            )
        else:
            cur = await conn.execute(
                "SELECT id, action, target, admin_id, reason, extra, created_at FROM block_logs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
        return await cur.fetchall()

async def db_stats():
    async with await get_db() as conn:
        total_users = (await conn.execute("SELECT COUNT(*) FROM users")).fetchone()[0] or 0
        blocked_users = (await conn.execute("SELECT COUNT(*) FROM blocked_users")).fetchone()[0] or 0
        blocked_channels = (await conn.execute("SELECT COUNT(*) FROM blocked_channels")).fetchone()[0] or 0
        blocked_groups = (await conn.execute("SELECT COUNT(*) FROM blocked_groups")).fetchone()[0] or 0
        today = datetime.utcnow().date().isoformat()
        today_blocks = (await conn.execute(
            "SELECT COUNT(*) FROM block_logs WHERE DATE(created_at)=?",
            (today,)
        )).fetchone()[0] or 0
        return {
            'total_users': total_users,
            'blocked_users': blocked_users,
            'blocked_channels': blocked_channels,
            'blocked_groups': blocked_groups,
            'today_blocks': today_blocks
        }

app = web.Application()

HTML = """
<!DOCTYPE html>
<html dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>نظام الحظر المتطور v5.1</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
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
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: auto; }
        .header {
            background: var(--card);
            padding: 20px 25px;
            border-radius: 12px;
            border: 1px solid var(--border);
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }
        .header h1 { font-size: 24px; color: var(--accent); }
        .header .subtitle { font-size: 13px; color: var(--text-muted); }
        .version-badge {
            background: var(--accent);
            color: var(--bg);
            padding: 2px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin-bottom: 20px;
        }
        .stat-card {
            background: var(--card);
            padding: 16px;
            border-radius: 10px;
            border: 1px solid var(--border);
            text-align: center;
        }
        .stat-card .num {
            font-size: 28px;
            font-weight: 700;
            color: var(--accent);
        }
        .stat-card .num.danger { color: var(--danger); }
        .stat-card .num.success { color: var(--success); }
        .stat-card .label { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
        .stat-card .icon { font-size: 20px; display: block; margin-bottom: 4px; }
        .tabs {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
            margin-bottom: 16px;
        }
        .tab-btn {
            padding: 8px 16px;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: var(--card);
            color: var(--text-muted);
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
            transition: all 0.2s;
        }
        .tab-btn:hover { background: #21262d; }
        .tab-btn.active {
            background: var(--accent);
            color: var(--bg);
            border-color: var(--accent);
        }
        .tab-content {
            display: none;
            background: var(--card);
            border-radius: 12px;
            padding: 18px;
            border: 1px solid var(--border);
        }
        .tab-content.active { display: block; }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        th {
            text-align: right;
            padding: 10px 12px;
            border-bottom: 2px solid var(--border);
            color: var(--text-muted);
            font-weight: 600;
        }
        td {
            padding: 8px 12px;
            border-bottom: 1px solid var(--border);
            word-break: break-word;
        }
        tr:hover { background: rgba(255,255,255,0.03); }
        .btn {
            padding: 4px 12px;
            border: none;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-danger { background: var(--danger); color: #fff; }
        .btn-danger:hover { opacity: 0.85; }
        .btn-success { background: var(--success); color: var(--bg); }
        .btn-success:hover { opacity: 0.85; }
        .btn-primary { background: var(--accent); color: var(--bg); }
        .btn-primary:hover { opacity: 0.85; }
        .btn-warning { background: var(--warning); color: var(--bg); }
        .btn-warning:hover { opacity: 0.85; }
        .badge {
            display: inline-block;
            padding: 1px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 600;
        }
        .badge-danger { background: rgba(248,81,73,0.15); color: var(--danger); }
        .badge-success { background: rgba(63,185,80,0.15); color: var(--success); }
        .badge-warning { background: rgba(210,153,34,0.15); color: var(--warning); }
        .badge-info { background: rgba(88,166,255,0.15); color: var(--accent); }
        .form-group {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 12px;
            align-items: center;
        }
        .form-group input, .form-group textarea, .form-group select {
            padding: 8px 12px;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text);
            font-size: 13px;
            flex: 1;
            min-width: 180px;
        }
        .form-group input:focus, .form-group textarea:focus, .form-group select:focus {
            outline: none;
            border-color: var(--accent);
        }
        .form-group textarea { min-height: 50px; }
        .form-group select { flex: 0 0 auto; min-width: 130px; }
        .form-group select option { background: var(--bg); }
        .empty-state {
            text-align: center;
            padding: 30px;
            color: var(--text-muted);
            font-size: 14px;
        }
        .toast {
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            padding: 12px 28px;
            border-radius: 8px;
            z-index: 9999;
            display: none;
            font-weight: 600;
            font-size: 14px;
            animation: slideDown 0.3s ease;
        }
        .toast.success { background: var(--success); color: var(--bg); }
        .toast.error { background: var(--danger); color: #fff; }
        .toast.info { background: var(--accent); color: var(--bg); }
        @keyframes slideDown {
            from { opacity: 0; transform: translateX(-50%) translateY(-15px); }
            to { opacity: 1; transform: translateX(-50%) translateY(0); }
        }
        .search-box {
            padding: 6px 12px;
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text);
            width: 200px;
        }
        .search-box:focus { border-color: var(--accent); outline: none; }
        .actions-row {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 12px;
            align-items: center;
        }
        .severity-warning { color: var(--warning); }
        .severity-mute { color: #d29922; }
        .severity-ban { color: var(--danger); }
        .severity-permanent { color: #ff0000; }
        @media (max-width: 768px) {
            .header { flex-direction: column; text-align: center; }
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
            .tabs { justify-content: center; }
            .tab-btn { flex: 1; min-width: 70px; text-align: center; font-size: 12px; padding: 6px 10px; }
            .form-group { flex-direction: column; }
            .form-group input, .form-group textarea, .form-group select { width: 100%; min-width: unset; }
            .search-box { width: 100%; }
            table { font-size: 12px; }
            th, td { padding: 5px 8px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>🛡️ نظام الحظر المتطور</h1>
                <div class="subtitle">ريلاكس مانيجر · الإدارة المتقدمة</div>
            </div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                <span class="version-badge">v5.1</span>
                <button class="btn btn-primary" onclick="refreshData()">🔄 تحديث</button>
                <span style="font-size:12px;color:var(--text-muted);" id="lastUpdate"></span>
            </div>
        </div>

        <div class="stats-grid" id="statsGrid">
            <div class="stat-card"><span class="icon">👤</span><div class="num" id="totalUsers">-</div><div class="label">إجمالي المستخدمين</div></div>
            <div class="stat-card"><span class="icon">🚫</span><div class="num danger" id="blockedUsers">-</div><div class="label">مستخدمون محظورون</div></div>
            <div class="stat-card"><span class="icon">📺</span><div class="num" id="blockedChannels">-</div><div class="label">قنوات محظورة</div></div>
            <div class="stat-card"><span class="icon">👥</span><div class="num" id="blockedGroups">-</div><div class="label">مجموعات محظورة</div></div>
            <div class="stat-card"><span class="icon">📊</span><div class="num success" id="todayBlocks">-</div><div class="label">حظر اليوم</div></div>
        </div>

        <div class="tabs">
            <button class="tab-btn active" data-tab="users">👤 المستخدمين</button>
            <button class="tab-btn" data-tab="channels">📺 القنوات</button>
            <button class="tab-btn" data-tab="groups">👥 المجموعات</button>
            <button class="tab-btn" data-tab="logs">📋 السجل</button>
            <button class="tab-btn" data-tab="add">➕ إضافة حظر</button>
        </div>

        <div class="tab-content active" id="tab-users">
            <div class="actions-row">
                <input class="search-box" id="userSearch" placeholder="🔍 بحث..." oninput="filterTable('usersTable', this.value)">
                <span style="font-size:12px;color:var(--text-muted);">إجمالي: <span id="userCount">0</span></span>
            </div>
            <div id="usersTable"><div class="empty-state">جاري التحميل...</div></div>
        </div>

        <div class="tab-content" id="tab-channels">
            <div id="channelsTable"><div class="empty-state">جاري التحميل...</div></div>
        </div>

        <div class="tab-content" id="tab-groups">
            <div id="groupsTable"><div class="empty-state">جاري التحميل...</div></div>
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
            <h3 style="color:var(--accent);margin-bottom:12px;">➕ إضافة حظر جديد</h3>
            <div class="form-group">
                <select id="blockType" style="flex:0 0 auto;min-width:120px;">
                    <option value="user">👤 مستخدم</option>
                    <option value="channel">📺 قناة</option>
                    <option value="group">👥 مجموعة</option>
                </select>
                <input type="text" id="targetId" placeholder="المعرف (مثال: 123456789)" dir="ltr">
            </div>
            <div class="form-group">
                <select id="severity" style="flex:0 0 auto;min-width:130px;">
                    <option value="warning">⚠️ تحذير</option>
                    <option value="mute">🔇 كتم</option>
                    <option value="ban">🚫 حظر مؤقت</option>
                    <option value="permanent">🔒 حظر دائم</option>
                </select>
                <input type="number" id="duration" placeholder="المدة (دقائق)" min="1">
            </div>
            <div class="form-group">
                <textarea id="reasonText" placeholder="سبب الحظر..."></textarea>
            </div>
            <div class="form-group">
                <button class="btn btn-danger" onclick="addBlock()">🚫 حظر</button>
                <button class="btn btn-warning" onclick="clearForm()">🗑️ مسح</button>
            </div>
            <div id="addResult" style="margin-top:8px;"></div>
        </div>
    </div>

    <div class="toast" id="toast"></div>

    <script>
        const API = window.location.origin;

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

        function severityClass(s) {
            const map = {warning:'severity-warning', mute:'severity-mute', ban:'severity-ban', permanent:'severity-permanent'};
            return map[s] || '';
        }

        function severityLabel(s) {
            const map = {warning:'⚠️ تحذير', mute:'🔇 كتم', ban:'🚫 حظر مؤقت', permanent:'🔒 حظر دائم'};
            return map[s] || s;
        }

        function renderTable(data, cols, actions) {
            if (!data || !data.length) return '<div class="empty-state">📭 لا توجد بيانات</div>';
            let html = `<table><thead><tr>${cols.map(c => `<th>${c.label}</th>`).join('')}</tr></thead><tbody>`;
            data.forEach(row => {
                html += '<tr>';
                cols.forEach(c => {
                    let val = row[c.key] !== undefined && row[c.key] !== null ? row[c.key] : '-';
                    if (['blocked_at','created_at','expires_at'].includes(c.key) && val) {
                        try { val = new Date(val).toLocaleString('ar-EG'); } catch(e){}
                    }
                    if (c.key === 'severity' && val) val = `<span class="${severityClass(val)}">${severityLabel(val)}</span>`;
                    if (c.key === 'action' && val) {
                        const colors = {BLOCK_USER:'danger',UNBLOCK_USER:'success',BLOCK_CHANNEL:'danger',UNBLOCK_CHANNEL:'success',BLOCK_GROUP:'danger',UNBLOCK_GROUP:'success'};
                        const cl = colors[val] || 'info';
                        val = `<span class="badge badge-${cl}">${val}</span>`;
                    }
                    html += `<td>${val}</td>`;
                });
                if (actions) html += `<td>${actions(row)}</td>`;
                html += '</tr>';
            });
            html += '</tbody></table>';
            return html;
        }

        async function refreshData() {
            try {
                const stats = await fetchJSON('/api/stats');
                document.getElementById('totalUsers').textContent = stats.total_users || 0;
                document.getElementById('blockedUsers').textContent = stats.blocked_users || 0;
                document.getElementById('blockedChannels').textContent = stats.blocked_channels || 0;
                document.getElementById('blockedGroups').textContent = stats.blocked_groups || 0;
                document.getElementById('todayBlocks').textContent = stats.today_blocks || 0;
                document.getElementById('lastUpdate').textContent = '🕐 ' + new Date().toLocaleTimeString('ar-EG');

                const filter = document.getElementById('logFilter')?.value || 'all';
                const qs = filter !== 'all' ? '?action=' + filter : '';

                const [users, channels, groups, logs] = await Promise.all([
                    fetchJSON('/api/blocked_users'),
                    fetchJSON('/api/blocked_channels'),
                    fetchJSON('/api/blocked_groups'),
                    fetchJSON('/api/block_logs' + qs)
                ]);

                document.getElementById('userCount').textContent = users.length;
                document.getElementById('usersTable').innerHTML = renderTable(users,
                    [{key:'user_id',label:'المعرف'},{key:'reason',label:'السبب'},{key:'severity',label:'الخطورة'},{key:'blocked_by',label:'بواسطة'},{key:'blocked_at',label:'التاريخ'}],
                    row => `<button class="btn btn-success" onclick="unblock('user',${row.user_id})">🔓 إلغاء</button>`
                );

                document.getElementById('channelsTable').innerHTML = renderTable(channels,
                    [{key:'channel_id',label:'المعرف'},{key:'reason',label:'السبب'},{key:'blocked_by',label:'بواسطة'},{key:'blocked_at',label:'التاريخ'}],
                    row => `<button class="btn btn-success" onclick="unblock('channel',${row.channel_id})">🔓 إلغاء</button>`
                );

                document.getElementById('groupsTable').innerHTML = renderTable(groups,
                    [{key:'chat_id',label:'المعرف'},{key:'reason',label:'السبب'},{key:'blocked_by',label:'بواسطة'},{key:'blocked_at',label:'التاريخ'}],
                    row => `<button class="btn btn-success" onclick="unblock('group',${row.chat_id})">🔓 إلغاء</button>`
                );

                document.getElementById('logsTable').innerHTML = renderTable(logs,
                    [{key:'action',label:'الإجراء'},{key:'target',label:'الهدف'},{key:'admin_id',label:'المشرف'},{key:'reason',label:'السبب'},{key:'created_at',label:'التاريخ'}]
                );

            } catch(e) {
                showToast('❌ فشل التحديث: ' + e.message, 'error');
            }
        }

        function filterTable(tableId, query) {
            const table = document.getElementById(tableId);
            if (!table) return;
            const rows = table.querySelectorAll('tbody tr');
            const q = query.toLowerCase();
            rows.forEach(row => {
                row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
            });
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

async def index_handler(request):
    return web.Response(text=HTML, content_type='text/html')

async def health_handler(request):
    return web.json_response({"status": "ok", "timestamp": time.time(), "version": "5.1"})

async def stats_handler(request):
    return web.json_response(await db_stats())

async def api_blocked_users(request):
    return web.json_response([dict(u) for u in await db_get_blocked_users(200)])

async def api_blocked_channels(request):
    return web.json_response([dict(c) for c in await db_get_blocked_channels(100)])

async def api_blocked_groups(request):
    return web.json_response([dict(g) for g in await db_get_blocked_groups(100)])

async def api_block_logs(request):
    action = request.query.get('action')
    return web.json_response([dict(l) for l in await db_get_block_logs(200, action)])

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

app.router.add_get('/', index_handler)
app.router.add_get('/panel', index_handler)
app.router.add_get('/health', health_handler)
app.router.add_get('/api/stats', stats_handler)
app.router.add_get('/api/blocked_users', api_blocked_users)
app.router.add_get('/api/blocked_channels', api_blocked_channels)
app.router.add_get('/api/blocked_groups', api_blocked_groups)
app.router.add_get('/api/block_logs', api_block_logs)
app.router.add_post('/api/block', api_block)
app.router.add_post('/api/unblock', api_unblock)

def start_web_server_background(port=None):
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
            logger.info(f"✅ نظام الحظر v5.1 يعمل على http://0.0.0.0:{port}")
        except OSError as e:
            if "address already in use" in str(e):
                site = web.TCPSite(runner, '0.0.0.0', 0)
                loop.run_until_complete(site.start())
                actual = site._server.sockets[0].getsockname()[1]
                logger.info(f"✅ يعمل على http://0.0.0.0:{actual} (منفذ عشوائي)")
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
    logger.info("🚀 تم تشغيل نظام الحظر v5.1")

if __name__ == '__main__':
    port = int(os.getenv('PORT', os.getenv('WEB_PORT', 10000)))
    start_web_server_background(port)
    print(f"🌐 نظام الحظر v5.1 متاح على http://0.0.0.0:{port}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف النظام")
