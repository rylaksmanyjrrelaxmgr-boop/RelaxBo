#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام الحظر المتطور - الإصدار 7.0 (مبسط للتوافق مع Render)
ريلاكس مانيجر · واجهة ويب مستقرة
"""

import os
import asyncio
import logging
import threading
import json
import time
import csv
import io
import secrets
from datetime import datetime, timedelta
from collections import OrderedDict
from aiohttp import web
import aiosqlite

logger = logging.getLogger(__name__)

# ===================== الإعدادات الأساسية =====================
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bot_data.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# قراءة كلمة المرور من البيئة (مع قيمة افتراضية للاختبار)
ADMIN_PASSWORD = os.getenv("WEB_PASSWORD", "mmmmm739377114")
ADMIN_USERNAME = os.getenv("WEB_USERNAME", "admin")

print(f"🔐 كلمة المرور المستخدمة: '{ADMIN_PASSWORD}'")
print(f"👤 اسم المستخدم: '{ADMIN_USERNAME}'")

# ===================== تخزين الجلسات =====================
# نستخدم كوكي بسيط مع صلاحية ساعة
_sessions = {}
_SESSION_TIMEOUT = 3600

def generate_session_id():
    return secrets.token_urlsafe(24)

def create_session():
    session_id = generate_session_id()
    _sessions[session_id] = {
        'created_at': time.time(),
        'expires_at': time.time() + _SESSION_TIMEOUT
    }
    return session_id

def validate_session(session_id):
    if session_id not in _sessions:
        return False
    session = _sessions[session_id]
    if time.time() > session['expires_at']:
        del _sessions[session_id]
        return False
    # تجديد الصلاحية
    session['expires_at'] = time.time() + _SESSION_TIMEOUT
    return True

# ===================== تطبيق الويب =====================
app = web.Application()

@web.middleware
async def auth_middleware(request, handler):
    # السماح بالوصول إلى /health بدون مصادقة
    if request.path in ['/health']:
        return await handler(request)
    
    # التحقق من الكوكي
    session_id = request.cookies.get('session_id')
    if session_id and validate_session(session_id):
        return await handler(request)
    
    # إذا كان طلب API، نرد بـ 401
    if request.path.startswith('/api/'):
        return web.json_response({'error': 'غير مصرح'}, status=401)
    
    # وإلا نعرض صفحة الدخول
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

# صفحة اللوحة الرئيسية (اختصاراً، ستظهر الإحصائيات)
DASHBOARD_PAGE = """
<!DOCTYPE html>
<html dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>لوحة التحكم</title>
    <style>
        body { background: #0d1117; color: #c9d1d9; font-family: Arial; padding: 20px; }
        .container { max-width: 800px; margin: auto; background: #161b22; padding: 20px; border-radius: 10px; border: 1px solid #30363d; }
        h1 { color: #58a6ff; text-align: center; }
        .info { background: #0d1117; padding: 15px; border-radius: 8px; margin: 10px 0; }
        .btn { display: inline-block; padding: 8px 16px; background: #58a6ff; color: #0d1117; text-decoration: none; border-radius: 6px; margin: 5px; }
        a { color: #58a6ff; }
        .logout { color: #f85149; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🛡️ لوحة تحكم ريلاكس مانيجر</h1>
        <div class="info">
            <p>✅ تم تسجيل الدخول بنجاح!</p>
            <p>📊 هذه نسخة مبسطة من اللوحة.</p>
            <p>🕐 الوقت الحالي: <span id="time"></span></p>
        </div>
        <div style="text-align: center;">
            <a href="/logout" class="logout">🚪 تسجيل الخروج</a>
        </div>
    </div>
    <script>
        document.getElementById('time').textContent = new Date().toLocaleString('ar-EG');
    </script>
</body>
</html>
"""

# ===================== معالجات الطلبات =====================

async def login_handler(request):
    if request.method == 'GET':
        return web.Response(text=LOGIN_PAGE, content_type='text/html')
    
    try:
        data = await request.post()
        password = data.get('password', '')
        print(f"📥 استقبال كلمة مرور: '{password}'")
        print(f"🔑 المتوقعة: '{ADMIN_PASSWORD}'")
        
        if password == ADMIN_PASSWORD:
            session_id = create_session()
            response = web.HTTPFound('/panel')
            response.set_cookie('session_id', session_id, max_age=_SESSION_TIMEOUT, httponly=True, secure=False)
            print("✅ تم إنشاء الجلسة والكوكي")
            return response
        else:
            print("❌ كلمة مرور خاطئة")
            error_page = LOGIN_PAGE.replace('</form>', '</form><div class="error">❌ كلمة مرور خاطئة</div>')
            return web.Response(text=error_page, content_type='text/html', status=401)
    except Exception as e:
        print(f"⚠️ خطأ في login_handler: {e}")
        return web.Response(text=LOGIN_PAGE, content_type='text/html', status=401)

async def logout_handler(request):
    response = web.HTTPFound('/login')
    response.del_cookie('session_id')
    return response

async def panel_handler(request):
    return web.Response(text=DASHBOARD_PAGE, content_type='text/html')

async def health_handler(request):
    return web.json_response({"status": "ok", "timestamp": time.time(), "version": "7.0"})

# ===================== تسجيل المسارات =====================
app.router.add_get('/', panel_handler)
app.router.add_get('/panel', panel_handler)
app.router.add_get('/login', login_handler)
app.router.add_post('/login', login_handler)
app.router.add_get('/logout', logout_handler)
app.router.add_get('/health', health_handler)

# ===================== تشغيل الخادم =====================

def start_web_server_background(port=None):
    if port is None:
        port = int(os.getenv('PORT', os.getenv('WEB_PORT', 10000)))
    
    # إذا كان المنفذ 0 أو غير محدد، نستخدم 10000
    if port == 0:
        port = 10000

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, '0.0.0.0', port)
        loop.run_until_complete(site.start())
        print(f"✅ خادم الويب يعمل على المنفذ {port}")
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(runner.cleanup())
            loop.close()

    threading.Thread(target=run, daemon=True).start()
    print(f"🚀 تم تشغيل خادم الويب على المنفذ {port}")

if __name__ == '__main__':
    port = int(os.getenv('PORT', os.getenv('WEB_PORT', 10000)))
    start_web_server_background(port)
    print(f"🌐 خادم الويب متاح على:")
    print(f"   - http://0.0.0.0:{port}")
    print(f"   - http://0.0.0.0:{port}/panel")
    print(f"   - http://0.0.0.0:{port}/health")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف النظام")
