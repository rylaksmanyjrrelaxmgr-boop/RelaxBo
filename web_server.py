#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
خادم الويب المنفصل لبوت ريلاكس مانيجر
"""

import os
import asyncio
import logging
import threading
import json
import time
from aiohttp import web

logger = logging.getLogger(__name__)

app = web.Application()

async def index_handler(request):
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>ريلاكس مانيجر - واجهة الويب</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; background: #f0f4f8; direction: rtl; }
            .container { max-width: 800px; margin: auto; background: white; padding: 30px; border-radius: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
            h1 { color: #2c3e50; }
            .status { color: #27ae60; font-weight: bold; }
            .footer { margin-top: 30px; font-size: 14px; color: #7f8c8d; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🌿 ريلاكس مانيجر</h1>
            <p>البوت يعمل <span class="status">✅</span></p>
            <p>📡 الإصدار: 19.3.3</p>
            <p>🕐 وقت التشغيل: <span id="uptime">جاري التحميل...</span></p>
            <hr>
            <p>🔗 نقاط النهاية المتاحة:</p>
            <ul style="list-style: none; padding: 0;">
                <li><code>/health</code> - التحقق من صحة البوت</li>
                <li><code>/stats</code> - إحصائيات عامة (JSON)</li>
            </ul>
            <div class="footer">© 2026 Relax Manager</div>
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
        "uptime": time.time() - getattr(health_handler, 'start_time', time.time())
    })

health_handler.start_time = time.time()

async def uptime_handler(request):
    return web.json_response({
        "uptime": int(time.time() - health_handler.start_time)
    })

async def stats_handler(request):
    return web.json_response({
        "users": 0,
        "channels": 0,
        "groups": 0,
        "pending_posts": 0,
        "status": "active"
    })

app.router.add_get('/', index_handler)
app.router.add_get('/health', health_handler)
app.router.add_get('/uptime', uptime_handler)
app.router.add_get('/stats', stats_handler)

def start_web_server_background(port: int = 8080):
    def run_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, '0.0.0.0', port)
        loop.run_until_complete(site.start())
        logger.info(f"✅ خادم الويب يعمل على المنفذ {port}")
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(runner.cleanup())
            loop.close()

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    logger.info(f"🚀 تم تشغيل خادم الويب في الخلفية على المنفذ {port}")

if __name__ == '__main__':
    port = int(os.getenv('WEB_PORT', 8080))
    start_web_server_background(port)
    print(f"خادم الويب يعمل على http://0.0.0.0:{port}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف الخادم")
# تحديث Thu Jul 23 03:29:32 +03 2026
