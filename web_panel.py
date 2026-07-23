from aiohttp import web
import os

app = web.Application()

async def panel(request):
    return web.Response(text="<h1>🌿 ريلاكس مانيجر يعمل!</h1><p>✅ الخادم يعمل بنجاح</p>", content_type='text/html')

app.router.add_get('/', panel)
app.router.add_get('/panel', panel)
app.router.add_get('/health', panel)

port = int(os.getenv('PORT', 8080))
web.run_app(app, port=port)
