#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
خادم الويب المتطور - نظام الحظر الشامل
الإصدار: 3.0
"""

import os
import asyncio
import logging
import threading
import json
import time
from datetime import datetime
from aiohttp import web

logger = logging.getLogger(__name__)

# ===================== دوال قاعدة البيانات =====================

async def db_stats():
    """إحصائيات عامة"""
    return {
        'total_users': 0,
        'blocked_users': 0,
        'blocked_channels': 0,
        'blocked_groups': 0
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
        <title>لوحة تحكم الحظر</title>
        <style>
            body { font-family: Arial; text-align: center; padding: 50px; background: #1a1a2e; color: white; }
            .container { max-width: 800px; margin: auto; background: #16213e; padding: 30px; border-radius: 16px; }
            h1 { color: #00d2ff; }
            .status { color: #00ff88; font-weight: bold; font-size: 24px; }
            .btn { background: #00d2ff; color: #1a1a2e; padding: 12px 24px; border: none; border-radius: 8px; font-size: 18px; cursor: pointer; }
            .btn:hover { background: #00b8d4; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🛡️ ريلاكس مانيجر</h1>
            <p class="status">✅ الخادم يعمل بنجاح</p>
            <p>📡 الإصدار: 3.0</p>
            <p>🕐 وقت التشغيل: <span id="uptime">جاري التحميل...</span></p>
            <hr>
            <p>🔗 نقاط النهاية المتاحة:</p>
            <ul style="list-style: none; padding: 0;">
                <li><code>/health</code> - التحقق من الصحة</li>
                <li><code>/stats</code> - إحصائيات (JSON)</li>
            </ul>
            <br>
            <button class="btn" onclick="location.href='/health'">🔍 التحقق من الصحة</button>
        </div>
        <script>
            fetch('/uptime')
                .then(res => res.json())
                .then(data => document.getElementById('uptime').textContent = data.uptime + ' ثانية')
                .catch(() => document.getElementById('uptime').textContent = 'غير متاح');
        </script>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def health_handler(request):
    return web.json_response({
        "status": "ok",
        "timestamp": time.time(),
        "uptime": int(time.time() - getattr(health_handler, 'start_time', time.time()))
    })

health_handler.start_time = time.time()

async def uptime_handler(request):
    return web.json_response({
        "uptime": int(time.time() - health_handler.start_time)
    })

async def stats_handler(request):
    stats = await db_stats()
    return web.json_response(stats)

# تسجيل المسارات
app.router.add_get('/', index_handler)
app.router.add_get('/health', health_handler)
app.router.add_get('/uptime', uptime_handler)
app.router.add_get('/stats', stats_handler)

# ===================== تشغيل الخادم =====================

def start_web_server_background(port: int = None):
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
            logger.info(f"✅ خادم الويب يعمل على http://0.0.0.0:{port}")
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
    logger.info("🚀 تم تشغيل خادم الويب في الخلفية")

if __name__ == '__main__':
    port = int(os.getenv('PORT', os.getenv('WEB_PORT', 8080)))
    start_web_server_background(port)
    print(f"🌐 خادم الويب متاح على http://0.0.0.0:{port}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف الخادم")
