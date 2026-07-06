import asyncio
from core.db_queries import *

async def send_reminders_loop(bot):
    while True:
        await asyncio.sleep(3600)
        # سيتم تنفيذ التذكيرات لاحقاً
        pass
