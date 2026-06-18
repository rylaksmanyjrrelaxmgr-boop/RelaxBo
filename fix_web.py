import asyncio
from aiohttp import web

async def start_web_server_correct():
    # دالة الويب الصحيحة
    from reelax_bot import app, WEB_HOST, WEB_PORT
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_HOST, WEB_PORT)
    await site.start()
    print(f"✅ واجهة الويب تعمل على http://{WEB_HOST}:{WEB_PORT}")
    
    # نمنع الإغلاق
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(start_web_server_correct())
