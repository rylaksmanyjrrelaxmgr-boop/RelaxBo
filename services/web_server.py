import asyncio
import os
from aiohttp import web
from config import WEB_HOST, PORT

async def health_check(request):
    return web.json_response({
        "status": "healthy",
        "service": "relax-bot",
        "version": "19.0.8"
    })

async def web_handler(request):
    return web.Response(text="""
    <!DOCTYPE html>
    <html>
    <head>
        <title>ريلاكس مانيجر</title>
        <meta charset="UTF-8">
        <style>
            body { font-family: Arial; text-align: center; padding: 50px; background: #1a1a2e; color: white; }
            .status { color: #00b894; font-size: 24px; }
        </style>
    </head>
    <body>
        <h1>🚀 ريلاكس مانيجر</h1>
        <p class="status">✅ البوت يعمل</p>
        <p>الإصدار 19.0.8</p>
        <p>🤖 تم التشغيل على Render</p>
    </body>
    </html>
    """, content_type="text/html")

async def start_web_server():
    try:
        app = web.Application()
        app.router.add_get("/", web_handler)
        app.router.add_get("/health", health_check)
        
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, WEB_HOST, PORT)
        await site.start()
        print(f"✅ خادم الويب يعمل على المنفذ {PORT}")
    except Exception as e:
        print(f"⚠️ فشل تشغيل خادم الويب: {e}")
