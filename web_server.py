#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
خادم الويب للبوت
"""

import os
import sys
import json
import asyncio
import time
import secrets
import hashlib
from pathlib import Path
from datetime import datetime

WEB_HOST = "0.0.0.0"
WEB_PORT = 10000
WEB_PASSWORD = secrets.token_urlsafe(16)
WEB_USERNAME = "admin"

try:
    from aiohttp import web
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "aiohttp"])
    from aiohttp import web

sessions = {}

async def login_page(request):
    html = '''
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>تسجيل الدخول</title>
    <style>
        body{background:#0a0a1a;color:#fff;font-family:Arial;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
        .box{background:rgba(255,255,255,0.05);padding:40px;border-radius:20px;border:1px solid rgba(255,255,255,0.1);width:350px}
        h1{text-align:center;color:#6c63ff}
        input{width:100%;padding:12px;margin:10px 0;border-radius:10px;border:1px solid rgba(255,255,255,0.1);background:rgba(255,255,255,0.05);color:#fff}
        button{width:100%;padding:12px;background:#6c63ff;border:none;border-radius:10px;color:#fff;font-size:16px;cursor:pointer}
        .error{color:#ff6b6b;text-align:center;display:none}
    </style>
    </head>
    <body>
    <div class="box">
        <h1>🤖 ريلاكس مانيجر</h1>
        <p style="text-align:center;color:gray">لوحة التحكم</p>
        <div id="error" class="error"></div>
        <form onsubmit="return login(event)">
            <input type="text" id="user" placeholder="اسم المستخدم" value="admin">
            <input type="password" id="pass" placeholder="كلمة المرور">
            <button type="submit">🚀 تسجيل الدخول</button>
        </form>
    </div>
    <script>
    async function login(e){
        e.preventDefault();
        const u=document.getElementById('user').value;
        const p=document.getElementById('pass').value;
        const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
        const d=await r.json();
        if(d.success){window.location.href='/dashboard'}else{document.getElementById('error').textContent='❌ '+d.message;document.getElementById('error').style.display='block'}
        return false;
    }
    </script>
    </body>
    </html>
    '''
    return web.Response(text=html, content_type='text/html')

async def dashboard(request):
    html = '''
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>لوحة التحكم</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{background:#0a0a1a;color:#fff;font-family:Arial;padding:20px}
        .header{background:rgba(255,255,255,0.05);padding:15px 20px;border-radius:10px;display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
        .header h1{color:#6c63ff;font-size:20px}
        .logout{color:#ff6b6b;text-decoration:none}
        .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:15px;margin-bottom:20px}
        .card{background:rgba(255,255,255,0.03);padding:20px;border-radius:12px;border:1px solid rgba(255,255,255,0.05)}
        .card .num{font-size:28px;font-weight:bold;color:#fff}
        .card .label{color:gray;font-size:13px}
        .row{display:grid;grid-template-columns:2fr 1fr;gap:20px}
        .box{background:rgba(255,255,255,0.03);padding:20px;border-radius:12px;border:1px solid rgba(255,255,255,0.05)}
        .box h3{color:#6c63ff;margin-bottom:10px}
        .item{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.03)}
        .item .label{color:gray}
        .item .value{color:#fff}
        .bar{width:100%;height:6px;background:rgba(255,255,255,0.05);border-radius:10px;margin-top:5px;overflow:hidden}
        .bar .fill{height:100%;background:#6c63ff;border-radius:10px;transition:width 0.5s}
        @media(max-width:600px){.row{grid-template-columns:1fr}}
    </style>
    </head>
    <body>
    <div class="header">
        <h1>🤖 ريلاكس مانيجر</h1>
        <a href="/logout" class="logout">🚪 خروج</a>
    </div>
    <div class="grid" id="stats">
        <div class="card"><div class="num" id="users">-</div><div class="label">👥 المستخدمين</div></div>
        <div class="card"><div class="num" id="active">-</div><div class="label">🟢 نشط</div></div>
        <div class="card"><div class="num" id="banned">-</div><div class="label">🚫 محظور</div></div>
        <div class="card"><div class="num" id="posts">-</div><div class="label">📝 منشورات</div></div>
        <div class="card"><div class="num" id="groups">-</div><div class="label">👥 مجموعات</div></div>
        <div class="card"><div class="num" id="channels">-</div><div class="label">📡 قنوات</div></div>
    </div>
    <div class="row">
        <div class="box"><h3>📋 النشاط الأخير</h3><div id="activity">جاري التحميل...</div></div>
        <div class="box"><h3>🖥️ حالة النظام</h3><div id="system">جاري التحميل...</div></div>
    </div>
    <script>
    async function loadStats(){
        try{
            const r=await fetch('/api/stats');
            const d=await r.json();
            document.getElementById('users').textContent=d.total_users||0;
            document.getElementById('active').textContent=d.active_users||0;
            document.getElementById('banned').textContent=d.banned_users||0;
            document.getElementById('posts').textContent=d.pending_posts||0;
            document.getElementById('groups').textContent=d.groups||0;
            document.getElementById('channels').textContent=d.channels||0;
        }catch(e){}
    }
    async function loadActivity(){
        try{
            const r=await fetch('/api/activity');
            const d=await r.json();
            let html='';
            if(d.activities&&d.activities.length>0){
                d.activities.slice(0,10).forEach(a=>{
                    html+='<div class="item"><span>'+a.user_id+'</span><span style="color:gray">'+a.action+'</span></div>';
                });
            }else{html='<div style="color:gray">📭 لا يوجد نشاط</div>'}
            document.getElementById('activity').innerHTML=html;
        }catch(e){}
    }
    async function loadSystem(){
        try{
            const r=await fetch('/api/system');
            const d=await r.json();
            document.getElementById('system').innerHTML='
                <div class="item"><span class="label">💾 الرام</span><span class="value">'+d.ram_used+'/'+d.ram_total+' GB</span></div>
                <div class="bar"><div class="fill" style="width:'+d.ram_percent+'%"></div></div>
                <div class="item"><span class="label">⏱️ التشغيل</span><span class="value">'+d.uptime_hours+' ساعة</span></div>
            ';
        }catch(e){}
    }
    loadStats();loadActivity();loadSystem();
    setInterval(()=>{loadStats();loadActivity();loadSystem();},10000);
    </script>
    </body>
    </html>
    '''
    return web.Response(text=html, content_type='text/html')

async def api_login(request):
    data = await request.json()
    if data.get('username') == WEB_USERNAME and data.get('password') == WEB_PASSWORD:
        sid = secrets.token_urlsafe(32)
        sessions[sid] = time.time() + WEB_SESSION_TIMEOUT
        resp = web.json_response({'success': True})
        resp.set_cookie('session', sid)
        return resp
    return web.json_response({'success': False, 'message': 'بيانات غير صحيحة'}, status=401)

async def api_logout(request):
    resp = web.Response(status=302, headers={'Location': '/'})
    resp.del_cookie('session')
    return resp

async def api_stats(request):
    try:
        import aiosqlite
        db_path = Path(__file__).parent / "data" / "bot_data.db"
        async with aiosqlite.connect(str(db_path)) as db:
            users = await (await db.execute("SELECT COUNT(*) FROM users")).fetchone()
            active = await (await db.execute("SELECT COUNT(*) FROM users WHERE banned=0")).fetchone()
            banned = await (await db.execute("SELECT COUNT(*) FROM users WHERE banned=1")).fetchone()
            posts = await (await db.execute("SELECT COUNT(*) FROM posts WHERE published=0")).fetchone()
            groups = await (await db.execute("SELECT COUNT(*) FROM bot_groups")).fetchone()
            channels = await (await db.execute("SELECT COUNT(*) FROM user_channels")).fetchone()
            return web.json_response({
                'total_users': users[0], 'active_users': active[0], 'banned_users': banned[0],
                'pending_posts': posts[0], 'groups': groups[0], 'channels': channels[0]
            })
    except:
        return web.json_response({'total_users':0,'active_users':0,'banned_users':0,'pending_posts':0,'groups':0,'channels':0})

async def api_activity(request):
    try:
        import aiosqlite
        db_path = Path(__file__).parent / "data" / "bot_data.db"
        async with aiosqlite.connect(str(db_path)) as db:
            cur = await db.execute("SELECT user_id, action, created_at FROM moderation_log ORDER BY created_at DESC LIMIT 10")
            rows = await cur.fetchall()
            return web.json_response({'activities': [{'user_id':r[0],'action':r[1],'created_at':r[2]} for r in rows]})
    except:
        return web.json_response({'activities': []})

async def api_system(request):
    try:
        import psutil
        mem = psutil.virtual_memory()
        return web.json_response({
            'ram_total': round(mem.total/(1024**3),1),
            'ram_used': round(mem.used/(1024**3),1),
            'ram_percent': mem.percent,
            'uptime_hours': int(time.time() - getattr(api_system, 'start', time.time())) // 3600
        })
    except:
        return web.json_response({'ram_total':0,'ram_used':0,'ram_percent':0,'uptime_hours':0})

async def index(request):
    return web.Response(status=302, headers={'Location': '/login'})

def create_app():
    app = web.Application()
    app.router.add_get('/', index)
    app.router.add_get('/login', login_page)
    app.router.add_get('/dashboard', dashboard)
    app.router.add_post('/api/login', api_login)
    app.router.add_get('/logout', api_logout)
    app.router.add_get('/api/stats', api_stats)
    app.router.add_get('/api/activity', api_activity)
    app.router.add_get('/api/system', api_system)
    return app

async def run_web_server():
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_HOST, WEB_PORT)
    await site.start()
    print(f"\n✅ خادم الويب يعمل على http://{WEB_HOST}:{WEB_PORT}")
    print(f"🔑 اسم المستخدم: {WEB_USERNAME}")
    print(f"🔑 كلمة المرور: {WEB_PASSWORD}\n")
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(run_web_server())
    except KeyboardInterrupt:
        print("\n🛑 تم الإيقاف")
