import asyncio
import logging
import os
import sys
import time
import random
import secrets
import json
import traceback
import gc
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember, BotCommand, LabeledPrice, ChatPermissions
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler, ChatMemberHandler
from telegram.error import TimedOut, NetworkError, BadRequest, Forbidden, Conflict
from telegram.request import HTTPXRequest

import aiohttp
import aiosqlite
from aiohttp import web, WSMsgType

from config import *
from database import *
from handlers import *
from utils import *

logger = logging.getLogger(__name__)

async def check_database_health() -> bool:
    try:
        async def _check(conn):
            cur = await conn.execute("SELECT 1")
            row = await cur.fetchone()
            return row is not None
        return await execute_db(_check)
    except:
        return False

async def check_telegram_health() -> bool:
    try:
        from telegram.ext import Application
        app = Application.builder().token(TOKEN).build()
        me = await app.bot.get_me()
        return me is not None
    except:
        return False

def get_ram_usage():
    try:
        import psutil
        mem = psutil.virtual_memory()
        return {"total": round(mem.total / (1024**3), 1), "used": round(mem.used / (1024**3), 1), "percent": mem.percent}
    except:
        try:
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
            mem_total = 0
            mem_available = 0
            for line in lines:
                if "MemTotal:" in line:
                    mem_total = int(line.split()[1]) / (1024 * 1024)
                if "MemAvailable:" in line:
                    mem_available = int(line.split()[1]) / (1024 * 1024)
            if mem_total > 0:
                used = mem_total - mem_available
                percent = (used / mem_total) * 100
                return {"total": round(mem_total, 1), "used": round(used, 1), "percent": round(percent, 1)}
        except:
            pass
        return {"total": 0, "used": 0, "percent": 0}

async def auto_publish_loop(bot):
    await asyncio.sleep(5)
    consecutive_errors = 0
    backoff = 10
    max_backoff = 60
    semaphore = asyncio.Semaphore(5)

    async def publish_one(row):
        async with semaphore:
            ch_db_id, ch_tele_id, user_id = row
            if not await db_has_active_subscription(user_id) and not await db_has_used_trial(user_id):
                return
            has_permission, permission_msg = await check_bot_permissions(bot, ch_tele_id)
            if not has_permission:
                return
            auto_recycle = await db_get_auto_recycle(user_id)
            total = await db_get_posts_count(ch_db_id)
            published = await db_get_published_count(ch_db_id)
            if total > 0 and published >= total:
                if auto_recycle:
                    logger.info(f"♻️ Auto recycle for channel {ch_tele_id} (enabled for user {user_id})")
                    await db_reset_all_posts_to_unpublished(ch_db_id)
                    try:
                        await bot.send_message(chat_id=user_id, text=f"♻️ **تم إعادة تدوير المنشورات تلقائياً!**\n\n📡 القناة: {ch_tele_id}\n📝 تم إعادة تعيين {total} منشور للنشر من جديد.", parse_mode="MarkdownV2")
                    except:
                        pass
                    return
                else:
                    logger.warning(f"⛔ Publishing stopped for channel {ch_tele_id} (auto_recycle disabled for user {user_id})")
                    try:
                        await bot.send_message(chat_id=user_id, text=f"⚠️ **توقف النشر التلقائي**\n\n📡 القناة: {ch_tele_id}\n📝 تم نشر جميع المنشورات ({published}/{total}).\n\n♻️ إعادة التدوير التلقائي معطل.\n📌 قم بتفعيله من الإعدادات أو أضف منشورات جديدة.", parse_mode="MarkdownV2")
                    except:
                        pass
                    await db_set_next_publish_date(ch_db_id, utc_now() + timedelta(days=365))
                    return
            post = await db_get_next_post(ch_db_id)
            if not post:
                if auto_recycle:
                    total = await db_get_posts_count(ch_db_id)
                    if total > 0:
                        await db_reset_all_posts_to_unpublished(ch_db_id)
                        logger.info(f"♻️ Auto recycle for channel {ch_tele_id} (no unpublished posts)")
                        try:
                            await bot.send_message(chat_id=user_id, text=f"♻️ **تم إعادة تدوير المنشورات تلقائياً!**\n\n📡 القناة: {ch_tele_id}\n📝 تم إعادة تعيين {total} منشور للنشر من جديد.", parse_mode="MarkdownV2")
                        except:
                            pass
                        return
                    else:
                        logger.info(f"📭 No posts in channel {ch_tele_id}")
                        return
                else:
                    logger.info(f"📭 No posts for channel {ch_tele_id} (auto_recycle disabled)")
                    return
            translation_lang = await get_user_translation_language(user_id)
            final_text = post["text"]
            if translation_lang != "off" and final_text:
                try:
                    translated = await translate_text(final_text, translation_lang)
                    if translated and translated != final_text:
                        final_text = f"{final_text}\n\n🌐 {translated}"
                except:
                    pass
            success = False
            for attempt in range(3):
                try:
                    if post["media_type"] == "photo" and post["media_file_id"]:
                        await bot.send_photo(ch_tele_id, post["media_file_id"], caption=final_text if final_text else None)
                    elif post["media_type"] == "video" and post["media_file_id"]:
                        await bot.send_video(ch_tele_id, post["media_file_id"], caption=final_text if final_text else None)
                    elif post["media_type"] == "document" and post["media_file_id"]:
                        await bot.send_document(ch_tele_id, post["media_file_id"], caption=final_text if final_text else None)
                    elif post["media_type"] == "audio" and post["media_file_id"]:
                        await bot.send_audio(ch_tele_id, post["media_file_id"], caption=final_text if final_text else None)
                    elif post["media_type"] == "voice" and post["media_file_id"]:
                        await bot.send_voice(ch_tele_id, post["media_file_id"], caption=final_text if final_text else None)
                    elif post["media_type"] == "animation" and post["media_file_id"]:
                        await bot.send_animation(ch_tele_id, post["media_file_id"], caption=final_text if final_text else None)
                    else:
                        await bot.send_message(ch_tele_id, final_text, parse_mode=None)
                    success = True
                    break
                except Exception as e:
                    logger.warning(f"Attempt {attempt+1} failed to publish to channel {ch_tele_id}: {e}")
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
            if success:
                await db_mark_published(post["id"])
                await db_set_last_publish(ch_db_id, utc_now())
                await db_update_next_publish_date(ch_db_id)
            else:
                await db_increment_fail_count(post["id"])
                logger.error(f"Permanent failure publishing post {post['id']} to channel {ch_tele_id}")
                next_retry = utc_now() + timedelta(seconds=PUBLISH_RETRY_DELAY)
                await db_set_next_publish_date(ch_db_id, next_retry)
            await asyncio.sleep(random.uniform(2, 5))

    while True:
        try:
            publish_interval = await db_get_publish_interval_seconds()
            async def _get_due_channels(conn, limit=MAX_CHANNELS_PER_CYCLE):
                now_utc_iso = utc_now().isoformat()
                cur = await conn.execute("""
                    SELECT uc.id, uc.channel_id, u.user_id
                    FROM user_channels uc
                    JOIN users u ON uc.user_id = u.user_id
                    LEFT JOIN schedule s ON uc.id = s.channel_db_id
                    WHERE u.auto_publish = 1
                      AND u.banned = 0
                      AND uc.banned = 0
                      AND (s.next_publish_date IS NULL OR s.next_publish_date <= ?)
                    ORDER BY COALESCE(s.next_publish_date, '1970-01-01') ASC
                    LIMIT ?
                """, (now_utc_iso, limit))
                return await cur.fetchall()
            rows = await execute_db(_get_due_channels)
            tasks = [publish_one(row) for row in rows]
            await asyncio.gather(*tasks, return_exceptions=True)
            consecutive_errors = 0
            backoff = publish_interval
            await asyncio.sleep(publish_interval)
        except Exception as e:
            logger.error(f"Publish loop error: {e}")
            consecutive_errors += 1
            backoff = min(backoff * 1.5, max_backoff)
            await asyncio.sleep(backoff)

async def run_scheduled_posts_loop(bot):
    consecutive_errors = 0
    backoff = SCHEDULED_POSTS_SLEEP
    max_backoff = 60
    while True:
        try:
            await asyncio.sleep(SCHEDULED_POSTS_SLEEP)
            now_utc = utc_now()
            posts = await db_get_due_scheduled_posts(now_utc)
            for post_id, chat_id, text, fail_count in posts:
                try:
                    await bot.send_message(chat_id, text)
                    await db_delete_scheduled_post(post_id)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    new_fail = fail_count + 1
                    await db_update_scheduled_post_fail(post_id, new_fail)
                    if new_fail >= 5:
                        await db_delete_scheduled_post(post_id)
                        logger.warning(f"Deleted scheduled post after 5 failed attempts: {post_id}")
                    else:
                        logger.error(f"Failed to send scheduled post: {e}")
            consecutive_errors = 0
            backoff = SCHEDULED_POSTS_SLEEP
        except Exception as e:
            logger.error(f"Scheduled posts loop error: {e}")
            backoff = min(backoff * 1.5, max_backoff)
            await asyncio.sleep(backoff)

async def send_reminders_loop(bot):
    await asyncio.sleep(30)
    asyncio.create_task(daily_reminder_task(bot))
    asyncio.create_task(weekly_reminder_task(bot))
    while True:
        try:
            users_to_remind = await db_get_users_needing_reminder()
            for user_data in users_to_remind:
                user_id = user_data["user_id"]
                days_left = user_data["days_left"]
                lang = user_data["notification_lang"]
                original_lang = user_language.get(user_id, "ar")
                user_language[user_id] = lang
                text = get_text(user_id, "subscription_warning").format(days_left)
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💎 تجديد الاشتراك", callback_data=CallbackData.SUBSCRIBE_MENU),
                     InlineKeyboardButton("🔕 إيقاف التذكير", callback_data=CallbackData.REMINDER_TOGGLE_SUB)]
                ])
                try:
                    await safe_send_markdown(bot, user_id, text, reply_markup=keyboard)
                    await db_update_last_reminder_sent(user_id, "subscription_expiry")
                except:
                    pass
                user_language[user_id] = original_lang
                await asyncio.sleep(0.5)
            await asyncio.sleep(REMINDERS_SLEEP)
        except Exception as e:
            logger.error(f"Reminders loop error: {e}")
            await asyncio.sleep(60)

async def daily_reminder_task(bot):
    last_daily_date = None
    while True:
        try:
            now = utc_now()
            now_mecca = utc_to_mecca(now)
            today_str = now_mecca.strftime("%Y-%m-%d")
            if last_daily_date != today_str:
                last_daily_date = today_str
                async def _get_daily_users(conn):
                    cur = await conn.execute("SELECT user_id, notification_lang FROM user_reminder_settings WHERE daily_stats_reminder=1")
                    return await cur.fetchall()
                daily_users = await execute_db(_get_daily_users)
                for user_id, lang in daily_users:
                    original_lang = user_language.get(user_id, "ar")
                    user_language[user_id] = lang
                    channels = await db_get_user_channels_count(user_id)
                    total_posts = await db_get_user_total_posts(user_id)
                    unpublished = await db_get_user_unpublished_posts(user_id)
                    groups = await db_get_user_groups_count(user_id)
                    text = get_text(user_id, "daily_stats").format(channels, total_posts, unpublished, groups)
                    try:
                        await safe_send_markdown(bot, user_id, text)
                    except:
                        pass
                    user_language[user_id] = original_lang
                    await asyncio.sleep(0.3)
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Daily reminder task error: {e}")
            await asyncio.sleep(60)

async def weekly_reminder_task(bot):
    last_weekly_date = None
    while True:
        try:
            now = utc_now()
            now_mecca = utc_to_mecca(now)
            today_str = now_mecca.strftime("%Y-%m-%d")
            if last_weekly_date != today_str and now_mecca.weekday() == 6:
                last_weekly_date = today_str
                async def _get_weekly_users(conn):
                    cur = await conn.execute("SELECT user_id, notification_lang FROM user_reminder_settings WHERE weekly_report=1")
                    return await cur.fetchall()
                weekly_users = await execute_db(_get_weekly_users)
                for user_id, lang in weekly_users:
                    original_lang = user_language.get(user_id, "ar")
                    user_language[user_id] = lang
                    channels = await db_get_user_channels_count(user_id)
                    total_posts = await db_get_user_total_posts(user_id)
                    unpublished = await db_get_user_unpublished_posts(user_id)
                    groups = await db_get_user_groups_count(user_id)
                    referral_stats = await db_get_referral_stats(user_id)
                    text = get_text(user_id, "weekly_report").format(channels, total_posts, unpublished, groups, referral_stats["total_referrals"])
                    try:
                        await safe_send_markdown(bot, user_id, text)
                    except:
                        pass
                    user_language[user_id] = original_lang
                    await asyncio.sleep(0.3)
            await asyncio.sleep(3600)
        except Exception as e:
            logger.error(f"Weekly reminder task error: {e}")
            await asyncio.sleep(60)

async def cleanup_expired_sessions():
    while True:
        await asyncio.sleep(3600)
        now = time.time()
        async def _cleanup_sessions(conn):
            await conn.execute("DELETE FROM web_sessions WHERE expires < ?", (now,))
            await conn.commit()
        await execute_db(_cleanup_sessions)
        async def _cleanup_tickets(conn):
            cutoff = (utc_now() - timedelta(days=30)).isoformat()
            await conn.execute("DELETE FROM support_tickets WHERE created_at < ? AND status='closed'", (cutoff,))
            await conn.commit()
        await execute_db(_cleanup_tickets)
        logger.info(f"✅ Cleaned expired sessions and old tickets")

async def cleanup_points_cache_loop():
    while True:
        await asyncio.sleep(3600)
        user_points_last_hour.clear()

async def broadcast_stats_periodically():
    while True:
        await asyncio.sleep(5)
        try:
            total, banned, posts, groups, channels = await db_stats()
            await ws_manager.broadcast({
                "type": "stats",
                "data": {
                    "total_users": total,
                    "active_users": total - banned,
                    "banned_users": banned,
                    "pending_posts": posts,
                    "groups": groups,
                    "channels": channels
                }
            })
        except Exception as e:
            logger.error(f"Stats broadcast error: {e}")

async def auto_close_contests_loop(bot):
    while True:
        await asyncio.sleep(3600)
        try:
            now = utc_now().isoformat()
            async def _get_expired(conn):
                cur = await conn.execute("SELECT id FROM contests WHERE status = 'active' AND end_date <= ?", (now,))
                return [row[0] for row in await cur.fetchall()]
            expired = await execute_db(_get_expired)
            for contest_id in expired:
                winner_id = await db_get_random_participant(contest_id)
                if winner_id:
                    await db_set_contest_winner(contest_id, winner_id)
                    contest = await db_get_contest(contest_id)
                    try:
                        await bot.send_message(winner_id, get_text(winner_id, "contest_auto_winner").format(contest["title"], contest["prize"]))
                    except:
                        pass
                    await bot.send_message(PRIMARY_OWNER_ID, f"🤖 تم إغلاق المسابقة #{contest_id} تلقائياً.\nالفائز: {winner_id}")
                else:
                    async def _close(conn):
                        await conn.execute("UPDATE contests SET status = 'finished' WHERE id = ?", (contest_id,))
                        await conn.commit()
                    await execute_db(_close)
        except Exception as e:
            logger.error(f"Auto close contests loop error: {e}")

async def memory_monitor():
    while True:
        try:
            ram = get_ram_usage()
            if ram["percent"] > 80:
                logger.warning(f"⚠️ High memory usage: {ram['percent']}%")
                await cache_cleaner.cleanup()
                logger.info("✅ Memory cleaned")
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"Memory monitor error: {e}")
            await asyncio.sleep(60)

class CacheCleaner:
    def __init__(self):
        self.last_cleanup = time.time()
        self.cleanup_interval = 300

    async def cleanup(self):
        try:
            if CACHETOOLS_AVAILABLE:
                _admin_cache.clear()
                _security_cache.clear()
                _user_cache.clear()
                _group_cache.clear()
            else:
                _admin_cache.clear()
                _security_cache.clear()
                _user_cache.clear()
                _group_cache.clear()
                _admin_cache_time.clear()
                _security_cache_time.clear()
            _translation_cache.clear()
            NSFW_CACHE.clear()
            user_translation_settings_cache.clear()
            user_points_last_hour.clear()
            user_language.clear()
            await clear_reply_cache()
            gc.collect()
            self.last_cleanup = time.time()
            logger.info("🧹 All caches cleaned successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Cache cleanup failed: {e}")
            return False

    async def auto_cleanup_loop(self):
        while True:
            await asyncio.sleep(self.cleanup_interval)
            try:
                if time.time() - self.last_cleanup >= self.cleanup_interval:
                    await self.cleanup()
            except Exception as e:
                logger.error(f"Auto cleanup loop error: {e}")

cache_cleaner = CacheCleaner()

class WebSocketManager:
    def __init__(self):
        self.sockets = set()
        self._lock = asyncio.Lock()

    async def broadcast(self, data):
        async with self._lock:
            if not self.sockets:
                return
            message = json.dumps(data)
            for ws in list(self.sockets):
                try:
                    await ws.send_str(message)
                except:
                    self.sockets.remove(ws)

    def add_socket(self, ws):
        self.sockets.add(ws)

    def remove_socket(self, ws):
        self.sockets.discard(ws)

ws_manager = WebSocketManager()

async def health_check_handler(request):
    try:
        db_healthy = await check_database_health()
        tg_healthy = await check_telegram_health()
        ram = get_ram_usage()
        checks = {
            "database": db_healthy,
            "telegram_api": tg_healthy,
            "memory": ram,
            "uptime": time.time() - getattr(health_check_handler, "start_time", time.time())
        }
        status = 200 if all([checks["database"], checks["telegram_api"]]) else 503
        return web.json_response({"status": "healthy" if status == 200 else "unhealthy", "checks": checks}, status=status)
    except Exception as e:
        return web.json_response({"status": "unhealthy", "error": str(e)}, status=503)

async def dashboard_handler(request):
    try:
        total, banned, posts, groups, channels = await db_stats()
        ram = get_ram_usage()
        stats = {
            "total_users": total,
            "active_users": total - banned,
            "banned_users": banned,
            "pending_posts": posts,
            "groups": groups,
            "channels": channels,
            "ram": ram,
            "uptime": int(time.time() - getattr(health_check_handler, "start_time", time.time()))
        }
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>لوحة تحكم البوت</title>
            <style>
                body { font-family: Arial, sans-serif; direction: rtl; background: #1a1a2e; color: #eee; margin: 0; padding: 20px; }
                .container { max-width: 1200px; margin: auto; }
                h1 { text-align: center; color: #e94560; }
                .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 30px 0; }
                .stat-card { background: #16213e; padding: 20px; border-radius: 10px; text-align: center; box-shadow: 0 4px 8px rgba(0,0,0,0.3); }
                .stat-card h3 { margin: 0; color: #aaa; font-size: 14px; }
                .stat-card .value { font-size: 32px; font-weight: bold; color: #e94560; margin: 10px 0; }
                .stat-card .sub { color: #888; font-size: 12px; }
                .footer { text-align: center; margin-top: 50px; color: #666; }
                .badge { display: inline-block; background: #e94560; color: #fff; padding: 3px 10px; border-radius: 20px; font-size: 12px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🤖 لوحة تحكم ريلاكس مانيجر</h1>
                <div class="stats-grid">
                    <div class="stat-card"><h3>👥 المستخدمين</h3><div class="value">""" + str(stats["total_users"]) + """</div><div class="sub">نشط: """ + str(stats["active_users"]) + """ | محظور: """ + str(stats["banned_users"]) + """</div></div>
                    <div class="stat-card"><h3>📝 المنشورات</h3><div class="value">""" + str(stats["pending_posts"]) + """</div><div class="sub">غير منشورة</div></div>
                    <div class="stat-card"><h3>👥 المجموعات</h3><div class="value">""" + str(stats["groups"]) + """</div></div>
                    <div class="stat-card"><h3>📡 القنوات</h3><div class="value">""" + str(stats["channels"]) + """</div></div>
                    <div class="stat-card"><h3>🖥️ الرام</h3><div class="value">""" + str(stats["ram"]["percent"]) + """%</div><div class="sub">""" + str(stats["ram"]["used"]) + """ / """ + str(stats["ram"]["total"]) + """ GB</div></div>
                    <div class="stat-card"><h3>⏱️ التشغيل</h3><div class="value">""" + str(stats["uptime"] // 3600) + """ ساعة</div></div>
                </div>
                <div style="text-align:center;margin-top:20px;">
                    <span class="badge">🟢 البوت يعمل</span>
                </div>
                <div class="footer">
                    <p>ريلاكس مانيجر v19.3.0 | © 2026</p>
                </div>
            </div>
            <script>
                const ws = new WebSocket('ws://' + window.location.host + '/ws');
                ws.onmessage = function(event) {
                    const data = JSON.parse(event.data);
                    if (data.type === 'stats') {
                        document.querySelector('.stat-card:nth-child(1) .value').textContent = data.data.total_users;
                        document.querySelector('.stat-card:nth-child(1) .sub').textContent = 'نشط: ' + data.data.active_users + ' | محظور: ' + data.data.banned_users;
                        document.querySelector('.stat-card:nth-child(2) .value').textContent = data.data.pending_posts;
                        document.querySelector('.stat-card:nth-child(3) .value').textContent = data.data.groups;
                        document.querySelector('.stat-card:nth-child(4) .value').textContent = data.data.channels;
                    }
                };
                ws.onclose = function() { console.log('تم قطع الاتصال'); };
            </script>
        </body>
        </html>
        """
        return web.Response(text=html, content_type="text/html")
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return web.Response(text=f"<h1>خطأ</h1><p>{str(e)}</p>", content_type="text/html", status=500)

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_manager.add_socket(ws)
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                pass
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        ws_manager.remove_socket(ws)
    return ws

web_app = web.Application()
web_app.router.add_get("/", dashboard_handler)
web_app.router.add_get("/health", health_check_handler)
web_app.router.add_get("/ws", websocket_handler)

async def start_web_server():
    try:
        render_port = int(os.getenv("PORT", "0"))
        ports_to_try = []
        if render_port > 0:
            ports_to_try.append(render_port)
        ports_to_try.extend([WEB_PORT, 8080, 10000, 8081, 8082, 8083])
        for port in ports_to_try:
            try:
                runner = web.AppRunner(web_app)
                await runner.setup()
                site = web.TCPSite(runner, WEB_HOST, port)
                await site.start()
                logger.info(f"✅ Web server running on http://{WEB_HOST}:{port}")
                global WEB_PORT_USED
                WEB_PORT_USED = port
                return
            except OSError as e:
                if "address already in use" in str(e):
                    logger.warning(f"⚠️ Port {port} in use, trying next...")
                    continue
                raise
        logger.error("❌ No available port found for web server")
    except Exception as e:
        logger.error(f"❌ Failed to start web server: {e}")

WEB_PORT_USED = WEB_PORT

async def self_ping_loop():
    await asyncio.sleep(10)
    external_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if external_url:
        url = f"{external_url}/"
    else:
        url = f"http://0.0.0.0:{WEB_PORT_USED}/"
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    logger.info(f"💓 Internal ping successful: {resp.status}")
        except Exception as e:
            logger.warning(f"⚠️ Internal ping failed: {e}")
        await asyncio.sleep(600)

def load_banned_words_from_file(file_path: Path) -> List[str]:
    words = []
    if not file_path.exists():
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("# قائمة الكلمات المحظورة - كل كلمة في سطر منفصل\n")
                f.write("# ابدأ السطر بـ # للتعليق\n")
                f.write("# استخدم * للتعبيرات النمطية (مثل: سكس.*\n")
                f.write("\n")
                f.write("بورن\nسكس\nجنس\nعري\nخمر\nخمور\nمخدرات\nحشيش\nكحول\nدعارة\n")
            print(f"✅ Created {file_path} with default words")
        except Exception as e:
            print(f"❌ Failed to create banned words file: {e}")
        return words
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    continue
                word = line.lower()
                if len(word) >= 2:
                    words.append(word)
        print(f"✅ Loaded {len(words)} banned words from {file_path}")
    except Exception as e:
        print(f"❌ Failed to load banned words: {e}")
    return words

BANNED_WORDS_FILE = BASE_PATH / "banned_words.txt"

async def import_banned_words_on_startup():
    try:
        words = load_banned_words_from_file(BANNED_WORDS_FILE)
        if words:
            async def _import(conn):
                imported = 0
                for word in words:
                    try:
                        await conn.execute("INSERT OR IGNORE INTO banned_words (word, chat_id, added_by, added_at) VALUES (?, ?, ?, ?)", (word, -1, PRIMARY_OWNER_ID, utc_now_iso()))
                        imported += 1
                    except:
                        continue
                await conn.commit()
                return imported
            imported_count = await execute_db(_import)
            logger.info(f"✅ Imported {imported_count} banned words from {BANNED_WORDS_FILE}")
        else:
            logger.info(f"📭 No banned words in {BANNED_WORDS_FILE} to import")
    except Exception as e:
        logger.error(f"❌ Failed to import banned words: {e}")

async def main():
    await init_db()
    await import_banned_words_on_startup()
    if USE_PROXY:
        request_kwargs = {
            "proxy_url": PROXY_URL,
            "read_timeout": 60.0,
            "write_timeout": 30.0,
            "connect_timeout": 30.0,
            "pool_timeout": 10.0,
            "connection_pool_size": MAX_CONNECTIONS
        }
        request = HTTPXRequest(**request_kwargs)
        application = Application.builder().token(TOKEN).request(request).build()
    else:
        request_kwargs = {
            "read_timeout": 60.0,
            "write_timeout": 30.0,
            "connect_timeout": 30.0,
            "pool_timeout": 10.0,
            "connection_pool_size": MAX_CONNECTIONS
        }
        request = HTTPXRequest(**request_kwargs)
        application = Application.builder().token(TOKEN).request(request).build()
    application.add_error_handler(global_error_handler)
    application.add_handler(CommandHandler("start", start_command_handler))
    application.add_handler(CommandHandler("language", language_command_handler))
    application.add_handler(CommandHandler("syncgroup", syncgroup_command_handler))
    application.add_handler(CommandHandler("security", security_command_handler))
    application.add_handler(CommandHandler("register_hidden_owner", register_hidden_owner_handler))
    application.add_handler(CommandHandler("add_hidden_admin", add_hidden_admin_command))
    application.add_handler(CommandHandler("remove_hidden_admin", remove_hidden_admin_command))
    application.add_handler(CommandHandler("list_hidden_admins", list_hidden_admins_command))
    application.add_handler(CommandHandler("update_admins", update_admins_command_handler))
    application.add_handler(CommandHandler("trial", trial_command_handler))
    application.add_handler(CommandHandler("subscribe", subscribe_command_handler))
    application.add_handler(CommandHandler("help", help_command_handler))
    application.add_handler(CommandHandler("support", support_command_handler))
    application.add_handler(CommandHandler("support_reply", support_reply_command_handler))
    application.add_handler(CommandHandler("rank", rank_command_handler))
    application.add_handler(CommandHandler("top", top_command_handler))
    application.add_handler(CommandHandler("developer", developer_command_handler))
    application.add_handler(CommandHandler("updates", updates_command_handler))
    application.add_handler(CommandHandler("stats", stats_command_handler))
    application.add_handler(CommandHandler("sendcode", sendcode_command_handler))
    application.add_handler(CommandHandler("lock", lock_chat_command_handler))
    application.add_handler(CommandHandler("unlock", unlock_chat_command_handler))
    application.add_handler(CommandHandler("schedule", schedule_post_command_handler))
    application.add_handler(CommandHandler("panel", panel_command_handler))
    application.add_handler(CommandHandler("set_log_channel", set_log_channel_command_handler))
    application.add_handler(CommandHandler("ban", handle_moderation_commands))
    application.add_handler(CommandHandler("mute", handle_moderation_commands))
    application.add_handler(CommandHandler("unmute", handle_moderation_commands))
    application.add_handler(CommandHandler("warn", handle_moderation_commands))
    application.add_handler(CommandHandler("kick", handle_moderation_commands))
    application.add_handler(CommandHandler("restrict", handle_moderation_commands))
    application.add_handler(CommandHandler("pin", handle_moderation_commands))
    application.add_handler(CommandHandler("unban", handle_moderation_commands))
    application.add_handler(CommandHandler("add_banned_word", handle_moderation_commands))
    application.add_handler(CommandHandler("remove_banned_word", handle_moderation_commands))
    application.add_handler(CommandHandler("contests", contests_command_handler))
    application.add_handler(CommandHandler("create_contest", create_contest_command_handler))
    application.add_handler(CommandHandler("declare_winner", declare_winner_command_handler))
    application.add_handler(CallbackQueryHandler(lang_callback_handler, pattern="^lang_"))
    application.add_handler(CallbackQueryHandler(handle_text_callbacks, pattern="^(rank|top|schedule_post|language)$"))
    application.add_handler(CallbackQueryHandler(main_menu_callback, pattern=f"^{CallbackData.MAIN_MENU}$"))
    application.add_handler(CallbackQueryHandler(back_callback, pattern=f"^{CallbackData.BACK}$"))
    application.add_handler(CallbackQueryHandler(cancel_session_callback, pattern=f"^{CallbackData.CANCEL_SESSION}$"))
    application.add_handler(CallbackQueryHandler(add_channel_callback, pattern=f"^{CallbackData.CHANNELS_ADD}$"))
    application.add_handler(CallbackQueryHandler(my_channels_callback, pattern=f"^{CallbackData.CHANNELS_MY}$"))
    application.add_handler(CallbackQueryHandler(delete_channel_callback, pattern=f"^{CallbackData.CHANNELS_DELETE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(select_channel_callback, pattern=f"^{CallbackData.CHANNELS_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(add_15_posts_callback, pattern=f"^{CallbackData.POSTS_ADD_15}$"))
    application.add_handler(CallbackQueryHandler(publish_one_callback, pattern=f"^{CallbackData.POSTS_PUBLISH_ONE}$"))
    application.add_handler(CallbackQueryHandler(my_posts_callback, pattern=f"^{CallbackData.POSTS_MY}$"))
    application.add_handler(CallbackQueryHandler(recycle_posts_callback, pattern=f"^{CallbackData.POSTS_RECYCLE}$"))
    application.add_handler(CallbackQueryHandler(delete_single_post_callback, pattern=f"^{CallbackData.POSTS_DELETE_SINGLE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(confirm_clear_all_posts_callback, pattern=f"^{CallbackData.POSTS_CONFIRM_CLEAR_ALL_PREFIX}"))
    application.add_handler(CallbackQueryHandler(clear_all_posts_callback, pattern=f"^{CallbackData.POSTS_CLEAR_ALL_PREFIX}"))
    application.add_handler(CallbackQueryHandler(my_pending_stats_callback, pattern=f"^{CallbackData.STATS_PENDING}$"))
    application.add_handler(CallbackQueryHandler(my_full_stats_callback, pattern=f"^{CallbackData.STATS_FULL}$"))
    application.add_handler(CallbackQueryHandler(my_groups_callback, pattern=f"^{CallbackData.GROUPS_MY}$"))
    application.add_handler(CallbackQueryHandler(group_settings_callback, pattern=f"^{CallbackData.GROUPS_SETTINGS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(settings_menu_callback, pattern=f"^{CallbackData.SETTINGS_MENU}$"))
    application.add_handler(CallbackQueryHandler(toggle_auto_publish_callback, pattern=f"^{CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH}$"))
    application.add_handler(CallbackQueryHandler(toggle_auto_recycle_callback, pattern=f"^{CallbackData.SETTINGS_TOGGLE_AUTO_RECYCLE}$"))
    application.add_handler(CallbackQueryHandler(schedule_menu_callback, pattern=f"^{CallbackData.SCHEDULE_MENU_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_interval_minutes_callback, pattern=f"^{CallbackData.SCHEDULE_SET_INTERVAL_MINUTES_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_interval_hours_callback, pattern=f"^{CallbackData.SCHEDULE_SET_INTERVAL_HOURS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_interval_days_callback, pattern=f"^{CallbackData.SCHEDULE_SET_INTERVAL_DAYS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_cron_callback, pattern="^schedule:set_cron:"))
    application.add_handler(CallbackQueryHandler(set_days_callback, pattern=f"^{CallbackData.SCHEDULE_SET_DAYS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_dates_callback, pattern=f"^{CallbackData.SCHEDULE_SET_DATES_PREFIX}"))
    application.add_handler(CallbackQueryHandler(set_publish_time_callback, pattern=f"^{CallbackData.SCHEDULE_SET_PUBLISH_TIME_PREFIX}"))
    application.add_handler(CallbackQueryHandler(day_select_callback, pattern=f"^{CallbackData.SCHEDULE_DAY_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(save_days_callback, pattern=f"^{CallbackData.SCHEDULE_SAVE_DAYS}$"))
    application.add_handler(CallbackQueryHandler(security_links_callback, pattern=f"^{CallbackData.SECURITY_LINKS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_mentions_callback, pattern=f"^{CallbackData.SECURITY_MENTIONS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_slowmode_callback, pattern=f"^{CallbackData.SECURITY_SLOWMODE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_banned_words_menu_callback, pattern=f"^{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_welcome_callback, pattern=f"^{CallbackData.SECURITY_WELCOME_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_goodbye_callback, pattern=f"^{CallbackData.SECURITY_GOODBYE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(security_close_callback, pattern=f"^{CallbackData.SECURITY_CLOSE}$"))
    application.add_handler(CallbackQueryHandler(banned_words_add_callback, pattern=f"^{CallbackData.BANNED_WORDS_ADD_PREFIX}"))
    application.add_handler(CallbackQueryHandler(banned_words_list_callback, pattern=f"^{CallbackData.BANNED_WORDS_LIST_PREFIX}"))
    application.add_handler(CallbackQueryHandler(banned_words_remove_callback, pattern=f"^{CallbackData.BANNED_WORDS_REMOVE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(help_callback, pattern=f"^{CallbackData.HELP}$"))
    application.add_handler(CallbackQueryHandler(support_menu_callback, pattern=f"^{CallbackData.SUPPORT_MENU}$"))
    application.add_handler(CallbackQueryHandler(support_help_callback, pattern=f"^{CallbackData.SUPPORT_HELP}$"))
    application.add_handler(CallbackQueryHandler(support_ticket_callback, pattern=f"^{CallbackData.SUPPORT_TICKET}$"))
    application.add_handler(CallbackQueryHandler(trial_callback, pattern=f"^{CallbackData.TRIAL}$"))
    application.add_handler(CallbackQueryHandler(subscribe_menu_callback, pattern=f"^{CallbackData.SUBSCRIBE_MENU}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_1_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_1}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_2_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_2}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_30_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_30}$"))
    application.add_handler(CallbackQueryHandler(buy_subscription_90_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_90}$"))
    application.add_handler(CallbackQueryHandler(developer_callback, pattern=f"^{CallbackData.DEVELOPER}$"))
    application.add_handler(CallbackQueryHandler(updates_callback, pattern=f"^{CallbackData.UPDATES}$"))
    application.add_handler(CallbackQueryHandler(referral_menu_callback, pattern=f"^{CallbackData.REFERRAL_MENU}$"))
    application.add_handler(CallbackQueryHandler(referral_copy_link_callback, pattern=f"^{CallbackData.REFERRAL_COPY_LINK_PREFIX}"))
    application.add_handler(CallbackQueryHandler(referral_claim_reward_callback, pattern=f"^{CallbackData.REFERRAL_CLAIM_REWARD}$"))
    application.add_handler(CallbackQueryHandler(referral_list_callback, pattern=f"^{CallbackData.REFERRAL_LIST}$"))
    application.add_handler(CallbackQueryHandler(reminder_menu_callback, pattern=f"^{CallbackData.REMINDER_MENU}$"))
    application.add_handler(CallbackQueryHandler(reminder_toggle_sub_callback, pattern=f"^{CallbackData.REMINDER_TOGGLE_SUB}$"))
    application.add_handler(CallbackQueryHandler(reminder_toggle_daily_callback, pattern=f"^{CallbackData.REMINDER_TOGGLE_DAILY}$"))
    application.add_handler(CallbackQueryHandler(reminder_toggle_weekly_callback, pattern=f"^{CallbackData.REMINDER_TOGGLE_WEEKLY}$"))
    application.add_handler(CallbackQueryHandler(reminder_set_days_callback, pattern=f"^{CallbackData.REMINDER_SET_DAYS}$"))
    application.add_handler(CallbackQueryHandler(reminder_set_lang_callback, pattern=f"^{CallbackData.REMINDER_SET_LANG}$"))
    application.add_handler(CallbackQueryHandler(reminder_lang_callback, pattern=f"^{CallbackData.REMINDER_LANG_PREFIX}"))
    application.add_handler(CallbackQueryHandler(translation_menu_callback, pattern=f"^{CallbackData.TRANSLATION_MENU}$"))
    application.add_handler(CallbackQueryHandler(translation_off_callback, pattern=f"^{CallbackData.TRANSLATION_OFF}$"))
    application.add_handler(CallbackQueryHandler(translation_set_callback, pattern=f"^{CallbackData.TRANSLATION_SET_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=f"^{CallbackData.ADMIN_PANEL}$"))
    application.add_handler(CallbackQueryHandler(admin_users_callback, pattern=f"^{CallbackData.ADMIN_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_users_callback, pattern=f"^{CallbackData.ADMIN_BANNED_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_unban_all_users_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_all_channels_callback, pattern=f"^{CallbackData.ADMIN_ALL_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_channels_callback, pattern=f"^{CallbackData.ADMIN_BANNED_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_activate_all_channels_callback, pattern=f"^{CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_groups_callback, pattern=f"^{CallbackData.ADMIN_GROUPS}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_groups_callback, pattern=f"^{CallbackData.ADMIN_BANNED_GROUPS}$"))
    application.add_handler(CallbackQueryHandler(admin_unban_all_groups_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_GROUPS}$"))
    application.add_handler(CallbackQueryHandler(admin_bot_channels_callback, pattern=f"^{CallbackData.ADMIN_BOT_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_banned_bot_channels_callback, pattern=f"^{CallbackData.ADMIN_BANNED_BOT_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_unban_all_bot_channels_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_BOT_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(admin_monitor_users_callback, pattern=f"^{CallbackData.ADMIN_MONITOR_USERS}$"))
    application.add_handler(CallbackQueryHandler(admin_add_admin_callback, pattern=f"^{CallbackData.ADMIN_ADD_ADMIN}$"))
    application.add_handler(CallbackQueryHandler(admin_remove_admin_callback, pattern=f"^{CallbackData.ADMIN_REMOVE_ADMIN}$"))
    application.add_handler(CallbackQueryHandler(admin_ram_callback, pattern=f"^{CallbackData.ADMIN_RAM}$"))
    application.add_handler(CallbackQueryHandler(admin_stats_callback, pattern=f"^{CallbackData.ADMIN_STATS}$"))
    application.add_handler(CallbackQueryHandler(admin_metrics_callback, pattern=f"^{CallbackData.ADMIN_METRICS}$"))
    application.add_handler(CallbackQueryHandler(admin_backup_callback, pattern=f"^{CallbackData.ADMIN_BACKUP}$"))
    application.add_handler(CallbackQueryHandler(admin_restore_backup_callback, pattern=f"^{CallbackData.ADMIN_RESTORE_BACKUP}$"))
    application.add_handler(CallbackQueryHandler(admin_restore_backup_select_callback, pattern=f"^{CallbackData.ADMIN_RESTORE_BACKUP_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_backup_settings_callback, pattern=f"^{CallbackData.ADMIN_BACKUP_SETTINGS}$"))
    application.add_handler(CallbackQueryHandler(admin_toggle_auto_backup_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_AUTO_BACKUP}$"))
    application.add_handler(CallbackQueryHandler(admin_change_interval_callback, pattern=f"^{CallbackData.ADMIN_CHANGE_INTERVAL}$"))
    application.add_handler(CallbackQueryHandler(admin_send_update_callback, pattern=f"^{CallbackData.ADMIN_SEND_UPDATE}$"))
    application.add_handler(CallbackQueryHandler(admin_set_update_channel_callback, pattern=f"^{CallbackData.ADMIN_SET_UPDATE_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_show_update_channel_callback, pattern=f"^{CallbackData.ADMIN_SHOW_UPDATE_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_updates_callback, pattern=f"^{CallbackData.ADMIN_UPDATES}$"))
    application.add_handler(CallbackQueryHandler(admin_force_subscribe_callback, pattern=f"^{CallbackData.ADMIN_FORCE_SUBSCRIBE}$"))
    application.add_handler(CallbackQueryHandler(admin_set_force_channel_callback, pattern=f"^{CallbackData.ADMIN_SET_FORCE_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_broadcast_callback, pattern=f"^{CallbackData.ADMIN_BROADCAST}$"))
    application.add_handler(CallbackQueryHandler(admin_confirm_broadcast_callback, pattern=f"^{CallbackData.ADMIN_CONFIRM_BROADCAST}$"))
    application.add_handler(CallbackQueryHandler(admin_support_tickets_callback, pattern=f"^{CallbackData.ADMIN_SUPPORT_TICKETS}$"))
    application.add_handler(CallbackQueryHandler(admin_delete_all_tickets_callback, pattern=f"^{CallbackData.ADMIN_DELETE_ALL_TICKETS}$"))
    application.add_handler(CallbackQueryHandler(admin_confirm_delete_tickets_callback, pattern=f"^{CallbackData.ADMIN_CONFIRM_DELETE_TICKETS}$"))
    application.add_handler(CallbackQueryHandler(admin_manage_sendcode_callback, pattern=f"^{CallbackData.ADMIN_MANAGE_SENDCODE}$"))
    application.add_handler(CallbackQueryHandler(admin_set_sendcode_user_callback, pattern=f"^{CallbackData.ADMIN_SET_SENDCODE_USER}$"))
    application.add_handler(CallbackQueryHandler(admin_show_log_channel_callback, pattern=f"^{CallbackData.ADMIN_SHOW_LOG_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_set_log_channel_callback, pattern=f"^{CallbackData.ADMIN_SET_LOG_CHANNEL}$"))
    application.add_handler(CallbackQueryHandler(admin_replies_callback, pattern=f"^{CallbackData.ADMIN_REPLIES}$"))
    application.add_handler(CallbackQueryHandler(admin_add_reply_callback, pattern=f"^{CallbackData.ADMIN_ADD_REPLY}$"))
    application.add_handler(CallbackQueryHandler(admin_list_replies_callback, pattern=f"^{CallbackData.ADMIN_LIST_REPLIES}$"))
    application.add_handler(CallbackQueryHandler(admin_del_reply_callback, pattern=f"^{CallbackData.ADMIN_DEL_REPLY}$"))
    application.add_handler(CallbackQueryHandler(admin_del_reply_callback, pattern="^admin_del_reply_"))
    application.add_handler(CallbackQueryHandler(admin_banned_words_callback, pattern=f"^{CallbackData.ADMIN_BANNED_WORDS}$"))
    application.add_handler(CallbackQueryHandler(admin_add_banned_word_callback, pattern=f"^{CallbackData.ADMIN_ADD_BANNED_WORD}$"))
    application.add_handler(CallbackQueryHandler(admin_list_banned_words_callback, pattern=f"^{CallbackData.ADMIN_LIST_BANNED_WORDS}$"))
    application.add_handler(CallbackQueryHandler(admin_remove_banned_word_callback, pattern=f"^{CallbackData.ADMIN_REMOVE_BANNED_WORD}$"))
    application.add_handler(CallbackQueryHandler(admin_del_banned_word_callback, pattern="^admin_del_banned_word_"))
    application.add_handler(CallbackQueryHandler(auto_reply_toggle_callback, pattern=f"^{CallbackData.AUTO_REPLY_TOGGLE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_admins_callback, pattern=f"^{CallbackData.AUTO_REPLY_ADMINS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_reset_callback, pattern=f"^{CallbackData.AUTO_REPLY_RESET_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_confirm_reset_callback, pattern=f"^{CallbackData.AUTO_REPLY_CONFIRM_RESET_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_cancel_callback, pattern=f"^{CallbackData.AUTO_REPLY_CANCEL_PREFIX}"))
    application.add_handler(CallbackQueryHandler(auto_reply_stats_callback, pattern=f"^{CallbackData.AUTO_REPLY_STATS_PREFIX}"))
    application.add_handler(CallbackQueryHandler(user_auto_reply_toggle_callback, pattern=f"^{CallbackData.USER_AUTO_REPLY_TOGGLE_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern=f"^{CallbackData.ADMIN_AUTO_REPLY}$"))
    application.add_handler(CallbackQueryHandler(admin_auto_reply_select_callback, pattern=f"^{CallbackData.ADMIN_AUTO_REPLY_SELECT_PREFIX}"))
    application.add_handler(CallbackQueryHandler(nsfw_settings_callback, pattern=f"^{CallbackData.NSFW_SETTINGS}$"))
    application.add_handler(CallbackQueryHandler(nsfw_toggle_callback, pattern=f"^{CallbackData.NSFW_TOGGLE}$"))
    application.add_handler(CallbackQueryHandler(nsfw_threshold_callback, pattern=f"^{CallbackData.NSFW_THRESHOLD_SET}$"))
    application.add_handler(CallbackQueryHandler(contests_menu_callback, pattern=f"^{CallbackData.CONTESTS_MENU}$"))
    application.add_handler(CallbackQueryHandler(contest_join_callback, pattern=f"^{CallbackData.CONTEST_JOIN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(contest_winners_callback, pattern=f"^{CallbackData.CONTEST_WINNERS}$"))
    application.add_handler(CallbackQueryHandler(contests_back_callback, pattern=f"^{CallbackData.CONTESTS_BACK}$"))
    application.add_handler(CallbackQueryHandler(admin_create_contest_callback, pattern=f"^{CallbackData.ADMIN_CREATE_CONTEST}$"))
    application.add_handler(CallbackQueryHandler(admin_declare_winner_callback, pattern=f"^{CallbackData.ADMIN_DECLARE_WINNER}$"))
    application.add_handler(CallbackQueryHandler(admin_toggle_channel_ban_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_CHANNEL_BAN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(admin_toggle_group_ban_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_GROUP_BAN_PREFIX}"))
    application.add_handler(CallbackQueryHandler(channel_stats_callback, pattern=f"^{CallbackData.CHANNEL_STATS}:"))
    application.add_handler(CallbackQueryHandler(channel_growth_callback, pattern=f"^{CallbackData.CHANNEL_GROWTH}:"))
    application.add_handler(CallbackQueryHandler(channel_stats_refresh_callback, pattern=f"^{CallbackData.CHANNEL_STATS_REFRESH}:"))
    application.add_handler(CallbackQueryHandler(my_channel_stats_callback, pattern=f"^{CallbackData.MY_CHANNEL_STATS}$"))
    application.add_handler(CallbackQueryHandler(check_subscribe_callback_handler, pattern=f"^{CallbackData.CHECK_SUBSCRIBE}$"))
    application.add_handler(CallbackQueryHandler(panel_lock_callback_handler, pattern=f"^{CallbackData.PANEL_LOCK_PREFIX}"))
    application.add_handler(CallbackQueryHandler(panel_unlock_callback_handler, pattern=f"^{CallbackData.PANEL_UNLOCK_PREFIX}"))
    application.add_handler(CallbackQueryHandler(panel_close_callback_handler, pattern=f"^{CallbackData.PANEL_CLOSE}$"))
    application.add_handler(CallbackQueryHandler(advanced_actions_callback, pattern=f"^{CallbackData.ADVANCED_ACTIONS}:"))
    application.add_handler(CallbackQueryHandler(group_action_ban_callback, pattern=f"^{CallbackData.GROUP_ACTION_BAN}:"))
    application.add_handler(CallbackQueryHandler(group_action_mute_callback, pattern=f"^{CallbackData.GROUP_ACTION_MUTE}:"))
    application.add_handler(CallbackQueryHandler(advanced_mute_duration_callback, pattern="^adv_mute_duration:"))
    application.add_handler(CallbackQueryHandler(group_action_warn_callback, pattern=f"^{CallbackData.GROUP_ACTION_WARN}:"))
    application.add_handler(CallbackQueryHandler(group_action_kick_callback, pattern=f"^{CallbackData.GROUP_ACTION_KICK}:"))
    application.add_handler(CallbackQueryHandler(group_action_restrict_callback, pattern=f"^{CallbackData.GROUP_ACTION_RESTRICT}:"))
    application.add_handler(CallbackQueryHandler(group_action_pin_callback, pattern=f"^{CallbackData.GROUP_ACTION_PIN}:"))
    application.add_handler(CallbackQueryHandler(group_action_log_callback, pattern=f"^{CallbackData.GROUP_ACTION_LOG}:"))
    application.add_handler(CallbackQueryHandler(group_action_unban_callback, pattern=f"^{CallbackData.GROUP_ACTION_UNBAN}:"))
    application.add_handler(CallbackQueryHandler(security_select_group_callback, pattern=f"^{CallbackData.SECURITY_SELECT_GROUP}"))
    application.add_handler(CallbackQueryHandler(security_refresh_groups_callback, pattern=f"^{CallbackData.SECURITY_REFRESH_GROUPS}$"))
    application.add_handler(CallbackQueryHandler(penalty_menu_callback, pattern=f"^{CallbackData.PENALTY_MENU}:"))
    application.add_handler(CallbackQueryHandler(penalty_kick_callback, pattern=f"^{CallbackData.PENALTY_KICK}:"))
    application.add_handler(CallbackQueryHandler(penalty_ban_callback, pattern=f"^{CallbackData.PENALTY_BAN}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_callback, pattern=f"^{CallbackData.PENALTY_MUTE}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_5}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_30}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_60}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_720}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_1440}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_10080}:"))
    application.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_PERMANENT}:"))
    application.add_handler(CallbackQueryHandler(publish_all_channels_callback_handler, pattern=f"^{CallbackData.PUBLISH_ALL_CHANNELS}$"))
    application.add_handler(CallbackQueryHandler(delete_group_callback, pattern="^delete_group:"))
    application.add_handler(CallbackQueryHandler(schedule_select_callback, pattern="^schedule_select:"))
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_callback_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback_handler))
    application.add_handler(ChatMemberHandler(track_chat_add, ChatMemberHandler.MY_CHAT_MEMBER))
    application.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_bot_added))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    application.add_handler(MessageHandler(filters.CAPTION & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler_main))
    application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.AUDIO & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.VOICE & filters.ChatType.PRIVATE, message_handler_main))
    application.add_handler(MessageHandler(filters.ANIMATION & filters.ChatType.PRIVATE, message_handler_main))
    commands = [
        BotCommand("start", "بدء البوت"),
        BotCommand("trial", "تجربة مجانية"),
        BotCommand("subscribe", "الاشتراك"),
        BotCommand("syncgroup", "تفعيل المجموعة (للمشرفين)"),
        BotCommand("activate", "تنشيط المجموعة (للمضيف)"),
        BotCommand("security", "إعدادات الأمان"),
        BotCommand("register_hidden_owner", "تسجيل مالك مخفي"),
        BotCommand("add_hidden_admin", "إضافة مشرف مخفي"),
        BotCommand("remove_hidden_admin", "إزالة مشرف مخفي"),
        BotCommand("list_hidden_admins", "عرض المشرفين المخفيين"),
        BotCommand("rank", "رتبتك"),
        BotCommand("top", "أفضل 10"),
        BotCommand("stats", "إحصائيات القناة"),
        BotCommand("lock", "قفل المجموعة"),
        BotCommand("unlock", "فتح المجموعة"),
        BotCommand("schedule", "جدولة منشور"),
        BotCommand("panel", "لوحة التحكم"),
        BotCommand("language", "تغيير اللغة"),
        BotCommand("support", "مركز الدعم"),
        BotCommand("support_reply", "الرد على تذكرة"),
        BotCommand("help", "المساعدة"),
        BotCommand("developer", "المطور"),
        BotCommand("updates", "آخر التحديثات"),
        BotCommand("sendcode", "إرسال كود البوت"),
        BotCommand("set_log_channel", "تعيين قناة التقارير"),
        BotCommand("ban", "حظر مستخدم"),
        BotCommand("mute", "كتم مستخدم"),
        BotCommand("unmute", "إلغاء كتم مستخدم"),
        BotCommand("warn", "تحذير مستخدم"),
        BotCommand("kick", "طرد مستخدم"),
        BotCommand("restrict", "تقييد مستخدم"),
        BotCommand("pin", "تثبيت رسالة"),
        BotCommand("unban", "إلغاء حظر مستخدم"),
        BotCommand("add_banned_word", "إضافة كلمة محظورة عامة"),
        BotCommand("remove_banned_word", "حذف كلمة محظورة عامة"),
        BotCommand("contests", "المسابقات"),
        BotCommand("create_contest", "إنشاء مسابقة"),
        BotCommand("declare_winner", "إعلان فائز"),
        BotCommand("update_admins", "تحديث المشرفين"),
    ]
    await application.bot.set_my_commands(commands)
    asyncio.create_task(auto_publish_loop(application.bot))
    asyncio.create_task(auto_backup())
    asyncio.create_task(run_scheduled_posts_loop(application.bot))
    asyncio.create_task(send_reminders_loop(application.bot))
    asyncio.create_task(cleanup_expired_sessions())
    asyncio.create_task(start_web_server())
    asyncio.create_task(self_ping_loop())
    asyncio.create_task(broadcast_stats_periodically())
    asyncio.create_task(cleanup_points_cache_loop())
    asyncio.create_task(memory_monitor())
    asyncio.create_task(auto_close_contests_loop(application.bot))
    asyncio.create_task(cache_cleaner.auto_cleanup_loop())
    asyncio.create_task(memory_optimizer_loop())
    print(f"🚀 {BOT_NAME} (v19.3.0) started")
    print("✅ All enhancements applied:")
    print("   • ✅ Full support for hidden admins (Anonymous) via sender_chat")
    print("   • ✅ Smart separation of permissions between private and group")
    print("   • ✅ Removed all 'Hidden owner registered' messages from groups (silent registration)")
    print("   • ✅ New /update_admins command to update admin list")
    print("   • ✅ Updated all moderation commands to use check_admin_access")
    print("   • ✅ Absolute permission for MAIN_ADMIN_ID everywhere")
    print("   • ✅ Improved cache performance and memory usage")
    print("   • ✅ Auto cache cleanup for faster replies")
    print("   • ✅ Embedded reply cache for faster response")
    try:
        await application.run_polling(drop_pending_updates=True, poll_interval=POLL_INTERVAL)
    except asyncio.CancelledError:
        logger.info("🛑 Bot cancelled")
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    finally:
        logger.info("🧹 Cleaning resources...")
        await db_pool.close()
        logger.info("✅ Resources cleaned")

if __name__ == "__main__":
    try:
        os.environ["WEB_CONCURRENCY"] = "1"
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        traceback.print_exc()
        sys.exit(1)
