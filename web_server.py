#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
from aiohttp import web
import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "bot_data.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

ADMIN_PASSWORD = os.getenv("WEB_PASSWORD", "mmmmm739377114")

_sessions = {}
_SESSION_TIMEOUT = 3600
_SERVER_STARTED = False
_SERVER_LOCK = threading.Lock()

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

async def check_auth(request):
    if request.path in ['/health']:
        return True
    session_id = request.cookies.get('session_id')
    if session_id and validate_session(session_id):
        return True
    return False

app = web.Application()

@web.middleware
async def auth_middleware(request, handler):
    if await check_auth(request):
        return await handler(request)
    return web.Response(text="<h1>🔐 تسجيل الدخول مطلوب</h1><form action='/login' method='post'><input type='password' name='password' placeholder='كلمة المرور'><button type='submit'>دخول</button></form>", content_type='text/html', status=401)

app.middlewares.append(auth_middleware)

async def login_handler(request):
    if request.method == 'GET':
        return web.Response(text="<h1>🔐 تسجيل الدخول</h1><form action='/login' method='post'><input type='password' name='password' placeholder='كلمة المرور'><button type='submit'>دخول</button></form>", content_type='text/html')
    try:
        data = await request.post()
        password = data.get('password')
        if password and password == ADMIN_PASSWORD:
            session_id = create_session(1)
            response = web.HTTPFound('/panel')
            response.set_cookie('session_id', session_id, max_age=_SESSION_TIMEOUT, httponly=True)
            return response
        else:
            return web.Response(text="<h1>❌ كلمة مرور خاطئة</h1><a href='/login'>حاول مرة أخرى</a>", content_type='text/html', status=401)
    except:
        return web.Response(text="<h1>❌ خطأ</h1>", content_type='text/html', status=401)

async def logout_handler(request):
    response = web.HTTPFound('/login')
    response.del_cookie('session_id')
    return response

async def index_handler(request):
    return web.Response(text="<h1>🛡️ نظام الحظر المتطور v6.1</h1><p>مرحباً بك في لوحة تحكم ريلاكس مانيجر</p><p><a href='/panel'>الذهاب إلى لوحة التحكم</a></p>", content_type='text/html')

async def panel_handler(request):
    return web.Response(text="<h1>🛡️ لوحة التحكم</h1><p>نظام الحظر المتطور يعمل بنجاح</p><p><a href='/logout'>تسجيل الخروج</a></p>", content_type='text/html')

async def health_handler(request):
    return web.json_response({"status": "ok", "timestamp": time.time(), "version": "6.1"})

app.router.add_get('/', index_handler)
app.router.add_get('/login', login_handler)
app.router.add_post('/login', login_handler)
app.router.add_get('/logout', logout_handler)
app.router.add_get('/panel', panel_handler)
app.router.add_get('/web', panel_handler)
app.router.add_get('/health', health_handler)

def start_web_server_background(port=None):
    global _SERVER_STARTED
    with _SERVER_LOCK:
        if _SERVER_STARTED:
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
            logger.info(f"✅ خادم الويب يعمل على http://0.0.0.0:{port}")
        except Exception as e:
            logger.error(f"❌ فشل تشغيل خادم الويب: {e}")
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(runner.cleanup())
            loop.close()

    threading.Thread(target=run, daemon=True).start()
    logger.info("🚀 تم تشغيل خادم الويب")

if __name__ == '__main__':
    port = int(os.getenv('PORT', os.getenv('WEB_PORT', 10000)))
    start_web_server_background(port)
    print(f"🌐 خادم الويب متاح على http://0.0.0.0:{port}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 تم الإيقاف")
