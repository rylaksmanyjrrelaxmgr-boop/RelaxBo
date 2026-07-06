import asyncio, logging
from datetime import datetime, timedelta
from database import fetch, execute, decrypt
from handlers import add_points

logger = logging.getLogger(__name__)

async def auto_publish(app):
    await asyncio.sleep(15)
    while True:
        try:
            interval_row = await fetch("SELECT value FROM settings WHERE key='publish_interval'")
            interval = int(interval_row[0]['value']) if interval_row else 720
        except: interval = 720
        try:
            users = await fetch("SELECT user_id, active_channel FROM users WHERE auto_publish=1 AND banned=0 AND active_channel IS NOT NULL")
            for u in users:
                if not u['active_channel']: continue
                post = await fetch("SELECT * FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT 1", u['active_channel'])
                if not post: continue
                post = dict(post[0])
                ch = await fetch("SELECT channel_id FROM channels WHERE id=?", u['active_channel'])
                if not ch: continue
                try:
                    if post['media_type']=="photo": await app.bot.send_photo(ch[0]['channel_id'], post['media_file_id'], caption=post['text'])
                    elif post['media_type']=="video": await app.bot.send_video(ch[0]['channel_id'], post['media_file_id'], caption=post['text'])
                    else: await app.bot.send_message(ch[0]['channel_id'], post['text'])
                    await execute("UPDATE posts SET published=1 WHERE id=?", post['id'])
                    await add_points(u['user_id'], 1)
                except Exception as e: logger.error(f"Publish error: {e}")
                await asyncio.sleep(2)
        except Exception as e: logger.error(f"Auto publish: {e}")
        await asyncio.sleep(interval)

async def reminder_loop(app):
    await asyncio.sleep(30)
    while True:
        try:
            rows = await fetch("SELECT * FROM reminders WHERE sub_reminder=1")
            for r in rows:
                r = dict(r)
                sub = await fetch("SELECT subscription_end FROM users WHERE user_id=?", r['user_id'])
                if sub and sub[0]['subscription_end']:
                    try:
                        end_str = decrypt(sub[0]['subscription_end'])
                        if end_str:
                            days = (datetime.fromisoformat(end_str) - datetime.now()).days
                            if 0 < days <= r.get('days_before',3):
                                try: await app.bot.send_message(r['user_id'], f"⏰ اشتراكك ينتهي خلال {days} يوم")
                                except: pass
                    except Exception as e: logger.error(f"Reminder: {e}")
        except Exception as e: logger.error(f"Reminder loop: {e}")
        await asyncio.sleep(3600)

async def scheduler_loop(app):
    await asyncio.sleep(20)
    while True:
        try:
            tasks = await fetch("SELECT * FROM scheduled_tasks WHERE executed=0 AND execute_at <= ?", datetime.now().isoformat())
            for task in tasks:
                task = dict(task)
                if task['task_type'] == "publish":
                    active_row = await fetch("SELECT active_channel FROM users WHERE user_id=?", task['user_id'])
                    if active_row and active_row[0]['active_channel']:
                        ch = await fetch("SELECT channel_id FROM channels WHERE id=?", active_row[0]['active_channel'])
                        if ch:
                            try: await app.bot.send_message(ch[0]['channel_id'], task['task_data'])
                            except: pass
                await execute("UPDATE scheduled_tasks SET executed=1 WHERE id=?", task['id'])
        except Exception as e: logger.error(f"Scheduler: {e}")
        await asyncio.sleep(10)
