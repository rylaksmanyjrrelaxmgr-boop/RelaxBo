import asyncio
import random
from core.db_queries import *

async def auto_publish_loop(bot):
    await asyncio.sleep(5)
    while True:
        try:
            interval = await db_get_publish_interval()
            channels = await db_get_due_channels()
            
            for ch_db_id, ch_tele_id, user_id in channels:
                post = await db_get_next_post(ch_db_id)
                if post:
                    try:
                        if post["media_type"] == "photo" and post["media_file_id"]:
                            await bot.send_photo(ch_tele_id, post["media_file_id"], caption=post["text"] or None)
                        elif post["media_type"] == "video" and post["media_file_id"]:
                            await bot.send_video(ch_tele_id, post["media_file_id"], caption=post["text"] or None)
                        else:
                            await bot.send_message(ch_tele_id, post["text"] or "📝")
                        
                        await db_mark_published(post["id"])
                        
                        total = await db_get_posts_count(ch_db_id)
                        published = await db_get_published_count(ch_db_id)
                        if total > 0 and published >= total:
                            await db_reset_posts_to_unpublished(ch_db_id)
                    except Exception as e:
                        print(f"⚠️ فشل النشر: {e}")
                
                await asyncio.sleep(random.uniform(1, 3))
            
            await asyncio.sleep(interval)
        except Exception as e:
            print(f"❌ خطأ في النشر التلقائي: {e}")
            await asyncio.sleep(60)

async def db_get_published_count(channel_db_id: int) -> int:
    async def _count(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=1", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_count)

async def run_scheduled_posts_loop(bot):
    while True:
        await asyncio.sleep(10)
        # سيتم تنفيذ المنشورات المجدولة لاحقاً
        pass
