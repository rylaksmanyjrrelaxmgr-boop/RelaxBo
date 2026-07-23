from aiohttp import web
import os

app = web.Application()

async def handler(request):
    return web.Response(text="""
    <!DOCTYPE html>
    <html>
    <head><title>ريلاكس مانيجر</title></head>
    <body style="font-family:Arial;text-align:center;padding:50px;background:#1a1a2e;color:white;">
        <h1>🌿 ريلاكس مانيجر يعمل!</h1>
        <p style="color:#00ff88;">✅ الخادم يعمل بنجاح</p>
        <p>📡 الإصدار: 3.0</p>
        <p>🕐 الوقت: <span id="time"></span></p>
        <hr>
        <p>🔗 استخدم <a href="/health" style="color:#00d2ff;">/health</a> للتحقق</p>
        <script>document.getElementById('time').textContent=new Date().toLocaleString('ar-EG');</script>
    </body>
    </html>
    """, content_type='text/html')

# استجب لكل المسارات
app.router.add_get('/', handler)
app.router.add_get('/panel', handler)
app.router.add_get('/web', handler)
app.router.add_get('/health', handler)
app.router.add_get('/{path:.*}', handler)  # أي مسار آخر

port = int(os.getenv('PORT', 10000))
web.run_app(app, port=port, host='0.0.0.0')
