from aiohttp import web
import os

app = web.Application()

async def home(request):
    return web.Response(text="""
    <!DOCTYPE html>
    <html>
    <head><title>ريلاكس مانيجر v5.1</title></head>
    <body style="font-family:Arial;text-align:center;padding:50px;background:#0d1117;color:#c9d1d9;">
        <h1 style="color:#58a6ff;">🌿 ريلاكس مانيجر</h1>
        <p style="color:#3fb950;">✅ الخادم يعمل بنجاح</p>
        <p>📡 الإصدار: 5.1</p>
        <p>🕐 <span id="t"></span></p>
        <hr style="border-color:#30363d;">
        <p>🔗 <a href="/health" style="color:#58a6ff;">/health</a> للتحقق</p>
        <p>📋 <a href="/panel" style="color:#58a6ff;">/panel</a> لوحة التحكم</p>
        <script>document.getElementById('t').textContent=new Date().toLocaleString('ar-EG');</script>
    </body>
    </html>
    """, content_type='text/html')

# المسارات الثلاثة المهمة
app.router.add_get('/', home)
app.router.add_get('/panel', home)
app.router.add_get('/health', home)

port = int(os.getenv('PORT', 10000))
web.run_app(app, port=port, host='0.0.0.0')
