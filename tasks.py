#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
المهام الخلفية - الإصدار النهائي
"""

import asyncio, json, logging, os, random, shutil, sqlite3, sys, tempfile, time as time_module
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import TelegramError, Forbidden, BadRequest, NetworkError, TimedOut

logger = logging.getLogger(__name__)

try:
    import contextvars as _contextvars
    user_language_context = _contextvars.ContextVar('user_language', default='ar')
except ImportError:
    import threading
    class _FallbackContextVar:
        def __init__(self, name, default=None): self._name=name; self._default=default; self._local=threading.local()
        def set(self, value): self._local.value=value; return value
        def get(self): return getattr(self._local,'value',self._default)
    user_language_context = _FallbackContextVar('user_language', default='ar')

from constants import (
    PRIMARY_OWNER_ID, BACKUP_DIR, MAX_BACKUPS, PUBLISH_RETRY_DELAY,
    MAX_CHANNELS_PER_CYCLE, SCHEDULED_POSTS_SLEEP, REMINDERS_SLEEP,
    AUTO_BACKUP_SLEEP, CLOUD_BACKUP_ENABLED, GOOGLE_AUTH_AVAILABLE,
    GOOGLE_DRIVE_FOLDER_ID, DB_PATH, BACKUP_CIPHER, CallbackData,
    user_points_last_hour
)
try: from constants import MAX_BACKUP_SIZE_MB
except ImportError: MAX_BACKUP_SIZE_MB = 500

from utils import (
    utc_now, mecca_now, utc_now_iso, mecca_now_iso,
    memory_optimizer, advanced_logger, log_error,
    translate_text, get_user_translation_language,
    safe_send_markdown, compress_backup, decompress_backup,
    get_ram_usage
)

try: from utils import check_bot_permissions as check_bot_perms
except ImportError:
    async def check_bot_perms(bot: Bot, chat_id: int) -> Tuple[bool, str]:
        try:
            me = await bot.get_chat_member(chat_id, bot.id)
            if me.status not in ('administrator','creator'): return False, "البوت ليس مشرفاً"
            if not me.can_post_messages: return False, "البوت لا يملك صلاحية النشر"
            return True, ""
        except: return False, "فشل التحقق"

from database import (
    db, execute_db, db_has_active_subscription, db_has_used_trial,
    db_get_next_post, db_mark_published, db_increment_fail_count,
    db_set_last_publish, db_update_next_publish_date, db_set_next_publish_date,
    db_get_posts_count, db_get_published_count,
    db_reset_all_posts_to_unpublished, db_get_auto_recycle,
    db_get_users_needing_reminder, db_update_last_reminder_sent,
    db_get_user_unpublished_posts, db_get_user_total_posts,
    db_get_user_channels_count, db_get_user_groups_count,
    db_get_referral_stats, db_get_auto_backup, db_get_last_backup_time,
    db_get_due_scheduled_posts, db_delete_scheduled_post,
    db_update_scheduled_post_fail, db_get_contest,
    db_get_random_participant, db_set_contest_winner, db_stats,
    db_get_publish_interval_seconds
)

try: from web import ws_manager
except ImportError: ws_manager = None

_points_lock = asyncio.Lock()

_SQL_GET_DUE_CHANNELS = """
    SELECT uc.id, uc.channel_id, u.user_id
    FROM user_channels uc
    JOIN users u ON uc.user_id = u.user_id
    LEFT JOIN schedule s ON uc.id = s.channel_db_id
    WHERE u.auto_publish = 1 AND u.banned = 0 AND uc.banned = 0
      AND (s.next_publish_date IS NULL OR s.next_publish_date <= ?)
    ORDER BY COALESCE(s.next_publish_date, '1970-01-01') ASC LIMIT ?
"""
_SQL_GET_DAILY_USERS = "SELECT user_id, notification_lang FROM user_reminder_settings WHERE daily_stats_reminder = 1"
_SQL_GET_WEEKLY_USERS = "SELECT user_id, notification_lang FROM user_reminder_settings WHERE weekly_report = 1"
_SQL_GET_EXPIRED_CONTESTS = "SELECT id FROM contests WHERE status = 'active' AND end_date <= ?"
_SQL_CLEANUP_SESSIONS = "DELETE FROM web_sessions WHERE expires < ?"
_SQL_CLEANUP_TICKETS = "DELETE FROM support_tickets WHERE created_at < ? AND status = 'closed'"
_SQL_CLOSE_CONTEST = "UPDATE contests SET status = 'finished' WHERE id = ?"
_SQL_UPDATE_BACKUP_TIME = "INSERT OR REPLACE INTO settings (key, value) VALUES ('last_backup', ?)"

def is_fernet_valid(obj): return obj is not None and callable(getattr(obj,'encrypt',None)) and callable(getattr(obj,'decrypt',None))

async def wait_with_timeout(stop_event: asyncio.Event, timeout: float) -> bool:
    try: await asyncio.wait_for(stop_event.wait(), timeout=timeout); return True
    except asyncio.TimeoutError: return False

class BackgroundTaskManager:
    def __init__(self, bot: Bot):
        self.bot = bot
        self._tasks: Dict[str, asyncio.Task] = {}
        self._stop_events: Dict[str, asyncio.Event] = {}
        self._error_counts: Dict[str, int] = {}
        self._max_errors = {'auto_publish':10,'scheduled_posts':5,'reminders':10,'daily_reports':10,'weekly_reports':10,'auto_backup':5,'cleanup':20,'memory_monitor':20,'stats_broadcast':20,'contests':10,'self_ping':30}
        self._max_backoff = {'auto_publish':300,'scheduled_posts':120,'reminders':300,'daily_reports':600,'weekly_reports':600,'auto_backup':900,'cleanup':600,'memory_monitor':300,'stats_broadcast':300,'contests':600,'self_ping':120}
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    async def start_all(self):
        if self._tasks: return
        logger.info("بدء تشغيل المهام الخلفية...")
        task_definitions = [
            ('auto_publish', self._auto_publish_loop), ('scheduled_posts', self._scheduled_posts_loop),
            ('reminders', self._reminders_loop), ('daily_reports', self._daily_report_loop),
            ('weekly_reports', self._weekly_report_loop), ('auto_backup', self._auto_backup_loop),
            ('cleanup', self._cleanup_loop), ('memory_monitor', self._memory_monitor_loop),
            ('stats_broadcast', self._stats_broadcast_loop), ('contests', self._contests_loop),
            ('self_ping', self._self_ping_loop)
        ]
        for name, coro_func in task_definitions:
            event = asyncio.Event(); self._stop_events[name] = event; self._error_counts[name] = 0
            self._tasks[name] = asyncio.create_task(self._run_with_error_tracking(name, coro_func, event))
        logger.info(f"تم بدء {len(self._tasks)} مهمة")

    async def stop_all(self):
        if not self._tasks: return
        for event in self._stop_events.values(): event.set()
        for task in self._tasks.values():
            if not task.done(): task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear(); self._stop_events.clear()

    async def _run_with_error_tracking(self, name, coro_func, stop_event):
        max_errors = self._max_errors.get(name,10)
        max_backoff = self._max_backoff.get(name,300)
        base_backoff = 10
        while not stop_event.is_set():
            try: await coro_func(stop_event); break
            except asyncio.CancelledError: break
            except Exception as e:
                self._error_counts[name] += 1
                if self._error_counts[name] >= max_errors: break
                wait = min(base_backoff * (2**(self._error_counts[name]-1)), max_backoff)
                if await wait_with_timeout(stop_event, wait): break

    async def _send_message_safe(self, chat_id, text):
        try: await self.bot.send_message(chat_id, text, read_timeout=30)
        except TypeError: await self.bot.send_message(chat_id, text)

    async def _auto_publish_loop(self, stop_event):
        sem = asyncio.Semaphore(5)
        async def publish_single(row):
            async with sem:
                ch_db_id, ch_tele_id, user_id = row
                if not (await db_has_active_subscription(user_id) or await db_has_used_trial(user_id)): return
                has_perm, _ = await check_bot_perms(self.bot, ch_tele_id)
                if not has_perm: return
                total = await db_get_posts_count(ch_db_id); published = await db_get_published_count(ch_db_id)
                post = None
                if total > 0 and published >= total:
                    if await db_get_auto_recycle(user_id):
                        await db_reset_all_posts_to_unpublished(ch_db_id)
                        post = await db_get_next_post(ch_db_id)
                    else:
                        await db_set_next_publish_date(ch_db_id, utc_now()+timedelta(days=365))
                        return
                else:
                    post = await db_get_next_post(ch_db_id)
                if not post: return
                final_text = post.get('text','') or ''
                lang = get_user_translation_language(user_id)
                if asyncio.iscoroutine(lang): lang = await lang
                if lang and lang not in ('off','ar'):
                    try:
                        trans = await translate_text(final_text, lang)
                        if trans and trans != final_text: final_text = f"{final_text}\n\n🌐 {trans}"
                    except: pass
                success = False
                for attempt in range(3):
                    try:
                        media_type = post.get('media_type','text')
                        media_file_id = (post.get('media_file_id','') or '').strip()
                        if media_file_id:
                            methods = {'photo':self.bot.send_photo,'video':self.bot.send_video,'document':self.bot.send_document,'audio':self.bot.send_audio,'voice':self.bot.send_voice,'animation':self.bot.send_animation}
                            method = methods.get(media_type)
                            if method:
                                try: await method(ch_tele_id, media_file_id, caption=final_text or None, read_timeout=30)
                                except TypeError: await method(ch_tele_id, media_file_id, caption=final_text or None)
                            else: await self._send_message_safe(ch_tele_id, final_text or ' ')
                        else: await self._send_message_safe(ch_tele_id, final_text or ' ')
                        success = True; break
                    except (Forbidden, BadRequest): break
                    except (NetworkError, TimedOut): await asyncio.sleep(2**attempt)
                    except TelegramError: await asyncio.sleep(2**attempt)
                    except Exception: await asyncio.sleep(2**attempt)
                if success:
                    await db_mark_published(post['id']); await db_set_last_publish(ch_db_id, utc_now())
                    await db_update_next_publish_date(ch_db_id)
                else:
                    await db_increment_fail_count(post['id'])
                    await db_set_next_publish_date(ch_db_id, utc_now()+timedelta(seconds=PUBLISH_RETRY_DELAY))
                await asyncio.sleep(random.uniform(1,3))

        while not stop_event.is_set():
            interval = await db_get_publish_interval_seconds()
            now_iso = utc_now().isoformat()
            async def _get(conn):
                cur = await conn.execute(_SQL_GET_DUE_CHANNELS, (now_iso, MAX_CHANNELS_PER_CYCLE))
                return await cur.fetchall()
            rows = await execute_db(_get)
            if rows: await asyncio.gather(*[publish_single(r) for r in rows], return_exceptions=True)
            if await wait_with_timeout(stop_event, interval): break

    async def _scheduled_posts_loop(self, stop_event):
        while not stop_event.is_set():
            posts = await db_get_due_scheduled_posts(utc_now())
            for post_id, chat_id, text, fail_count in posts:
                if stop_event.is_set(): break
                try:
                    await self._send_message_safe(chat_id, text); await db_delete_scheduled_post(post_id)
                except (Forbidden, BadRequest): await db_delete_scheduled_post(post_id)
                except TelegramError:
                    if fail_count+1 >= 5: await db_delete_scheduled_post(post_id)
                    else: await db_update_scheduled_post_fail(post_id, fail_count+1)
            if await wait_with_timeout(stop_event, SCHEDULED_POSTS_SLEEP): break

    async def _reminders_loop(self, stop_event):
        while not stop_event.is_set():
            users = await db_get_users_needing_reminder()
            for u in users:
                if stop_event.is_set(): break
                user_id = u['user_id']; days_left = u['days_left']; lang = u.get('notification_lang','ar')
                token = user_language_context.set(lang)
                try:
                    sub_cb = CallbackData.SUBSCRIBE_MENU.value if hasattr(CallbackData,'SUBSCRIBE_MENU') else "subscribe"
                    rem_cb = CallbackData.REMINDER_TOGGLE_SUB.value if hasattr(CallbackData,'REMINDER_TOGGLE_SUB') else "toggle_reminder"
                    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("💎 تجديد الاشتراك", callback_data=sub_cb), InlineKeyboardButton("🔕 إيقاف التذكير", callback_data=rem_cb)]])
                    sent = False
                    try:
                        await safe_send_markdown(self.bot, user_id, f"⚠️ **تنبيه!**\nاشتراكك ينتهي خلال {days_left} أيام\nقم بتجديده الآن لتستمر الميزات 💎", reply_markup=keyboard)
                        sent = True
                    except: pass
                    if sent: await db_update_last_reminder_sent(user_id, "subscription_expiry")
                finally: user_language_context.reset(token)
                await asyncio.sleep(0.5)
            if await wait_with_timeout(stop_event, REMINDERS_SLEEP): break

    async def _daily_report_loop(self, stop_event):
        last_date = None
        while not stop_event.is_set():
            today = mecca_now().strftime("%Y-%m-%d")
            if last_date == today: await asyncio.sleep(3600); continue
            last_date = today
            async def _get(conn):
                cur = await conn.execute(_SQL_GET_DAILY_USERS); return await cur.fetchall()
            for user_id, lang in await execute_db(_get):
                if stop_event.is_set(): break
                token = user_language_context.set(lang)
                try:
                    text = f"📊 **تقريرك اليومي**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 القنوات: {await db_get_user_channels_count(user_id)}\n📝 إجمالي المنشورات: {await db_get_user_total_posts(user_id)}\n⏳ غير المنشورة: {await db_get_user_unpublished_posts(user_id)}\n👥 المجموعات: {await db_get_user_groups_count(user_id)}"
                    try: await safe_send_markdown(self.bot, user_id, text)
                    except: pass
                finally: user_language_context.reset(token)
                await asyncio.sleep(0.3)
            if await wait_with_timeout(stop_event, 3600): break

    async def _weekly_report_loop(self, stop_event):
        last_date = None
        while not stop_event.is_set():
            now = mecca_now(); today = now.strftime("%Y-%m-%d")
            if last_date == today or now.weekday() != 4: await asyncio.sleep(3600); continue
            last_date = today
            async def _get(conn):
                cur = await conn.execute(_SQL_GET_WEEKLY_USERS); return await cur.fetchall()
            for user_id, lang in await execute_db(_get):
                if stop_event.is_set(): break
                token = user_language_context.set(lang)
                try:
                    ref = await db_get_referral_stats(user_id)
                    total_ref = ref.get('total_referrals',0) if isinstance(ref,dict) else (ref if isinstance(ref,(int,float)) else 0)
                    text = f"📈 **تقريرك الأسبوعي**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 القنوات: {await db_get_user_channels_count(user_id)}\n📝 إجمالي المنشورات: {await db_get_user_total_posts(user_id)}\n⏳ غير المنشورة: {await db_get_user_unpublished_posts(user_id)}\n👥 المجموعات: {await db_get_user_groups_count(user_id)}\n🔗 الإحالات: {total_ref}"
                    try: await safe_send_markdown(self.bot, user_id, text)
                    except: pass
                finally: user_language_context.reset(token)
                await asyncio.sleep(0.3)
            if await wait_with_timeout(stop_event, 3600): break

    async def _auto_backup_loop(self, stop_event):
        while not stop_event.is_set():
            if await db_get_auto_backup():
                last = await db_get_last_backup_time()
                if not last: await self._create_full_backup(); await self._update_backup_time()
                else:
                    try: days = (utc_now() - datetime.fromisoformat(last)).days
                    except: days = 999
                    if days >= 7: await self._create_full_backup(); await self._update_backup_time()
                    else: await self._create_incremental_backup()
            if await wait_with_timeout(stop_event, AUTO_BACKUP_SLEEP): break

    async def _update_backup_time(self):
        await execute_db(lambda conn: conn.execute(_SQL_UPDATE_BACKUP_TIME, (utc_now_iso(),)) or conn.commit())

    async def _create_full_backup(self) -> Optional[Path]:
        temp_files = []
        try:
            if not DB_PATH.exists(): return None
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.db'); tmp.close(); temp_files.append(Path(tmp.name))
            shutil.copy2(DB_PATH, tmp.name)
            with open(tmp.name,'rb') as f: data = f.read()
            compressed = compress_backup(data)
            if not is_fernet_valid(BACKUP_CIPHER): raise ValueError("BACKUP_CIPHER غير مهيأ")
            encrypted = BACKUP_CIPHER.encrypt(compressed)
            path = BACKUP_DIR / f"backup_{mecca_now().strftime('%Y%m%d_%H%M%S')}.enc"
            with open(path,'wb') as f: f.write(encrypted)
            await self._cleanup_old_backups()
            logger.info(f"نسخة احتياطية كاملة: {path.name}")
            return path
        except Exception as e: log_error(e, {"operation":"create_full_backup"}); raise
        finally:
            for f in temp_files:
                with suppress(OSError): f.unlink(missing_ok=True)

    async def _create_incremental_backup(self) -> Optional[Path]:
        try:
            last = await db_get_last_backup_time()
            try: last_time = datetime.fromisoformat(last) if last else utc_now()-timedelta(days=7)
            except: last_time = utc_now()-timedelta(days=7)
            data = {}
            async def _posts(conn):
                cur = await conn.execute("SELECT * FROM posts WHERE created_at > ? LIMIT 1000", (last_time.isoformat(),))
                rows = await cur.fetchall()
                try: return [dict(row) for row in rows]
                except: return []
            posts = await execute_db(_posts)
            if posts: data['posts'] = posts
            if not data: return None
            compressed = compress_backup(json.dumps(data, default=str, ensure_ascii=False).encode())
            encrypted = BACKUP_CIPHER.encrypt(compressed)
            path = BACKUP_DIR / f"incremental_{mecca_now().strftime('%Y%m%d_%H%M%S')}.inc"
            with open(path,'wb') as f: f.write(encrypted)
            logger.info(f"نسخة تزايدية: {path.name}")
            return path
        except Exception as e: log_error(e, {"operation":"create_incremental_backup"}); return None

    async def _cleanup_old_backups(self):
        try:
            backups = sorted(BACKUP_DIR.glob("backup_*.enc"), key=lambda x: x.stat().st_mtime, reverse=True)
            for old in backups[MAX_BACKUPS:]: old.unlink(missing_ok=True)
            backups = sorted(BACKUP_DIR.glob("backup_*.enc"), key=lambda x: x.stat().st_mtime, reverse=True)
            total = sum(b.stat().st_size for b in backups)
            limit = MAX_BACKUP_SIZE_MB * 1024 * 1024
            while total > limit and len(backups)>1:
                old = backups.pop(); total -= old.stat().st_size; old.unlink(missing_ok=True)
        except Exception as e: logger.warning(f"خطأ في تنظيف النسخ القديمة: {e}")

    async def _cleanup_loop(self, stop_event):
        while not stop_event.is_set():
            now_ts = time_module.time()
            await execute_db(lambda conn: conn.execute(_SQL_CLEANUP_SESSIONS, (now_ts,)) or conn.commit())
            await execute_db(lambda conn: conn.execute(_SQL_CLEANUP_TICKETS, ((utc_now()-timedelta(days=30)).isoformat(),)) or conn.commit())
            async with _points_lock:
                for uid in [u for u, (_, t) in list(user_points_last_hour.items()) if now_ts - t > 3600]:
                    with suppress(KeyError): del user_points_last_hour[uid]
            if await wait_with_timeout(stop_event, 3600): break

    async def _memory_monitor_loop(self, stop_event):
        while not stop_event.is_set():
            ram = get_ram_usage(); pct = ram.get('percent',0) if isinstance(ram,dict) else 0
            if pct > 80: memory_optimizer()
            if await wait_with_timeout(stop_event, 60): break

    async def _stats_broadcast_loop(self, stop_event):
        if ws_manager is None: return
        while not stop_event.is_set():
            s = await db_stats()
            if s and isinstance(s,(tuple,list)):
                await ws_manager.broadcast({'type':'stats','data':{'total_users':s[0],'active_users':s[0]-s[1],'banned_users':s[1],'pending_posts':s[2],'groups':s[3],'channels':s[4]}})
            if await wait_with_timeout(stop_event, 5): break

    async def _contests_loop(self, stop_event):
        while not stop_event.is_set():
            expired = await execute_db(lambda conn: [r[0] for r in (await conn.execute(_SQL_GET_EXPIRED_CONTESTS, (utc_now().isoformat(),))).fetchall()])
            for cid in expired:
                winner = await db_get_random_participant(cid)
                if winner:
                    await db_set_contest_winner(cid, winner)
                    contest = await db_get_contest(cid)
                    if contest:
                        try: await self.bot.send_message(winner, f"🎉 **تهانينا!**\nلقد فزت في مسابقة **{contest.get('title','')}**\n🎁 الجائزة: {contest.get('prize','')}", parse_mode="MarkdownV2")
                        except: pass
                else: await execute_db(lambda conn: conn.execute(_SQL_CLOSE_CONTEST, (cid,)) or conn.commit())
            if await wait_with_timeout(stop_event, 3600): break

    async def _self_ping_loop(self, stop_event):
        url = f"{os.getenv('RENDER_EXTERNAL_URL','')}/" if os.getenv("RENDER_EXTERNAL_URL") else f"http://0.0.0.0:{os.getenv('PORT','10000')}/"
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                while not stop_event.is_set():
                    try: await session.get(url, timeout=10)
                    except: pass
                    if await wait_with_timeout(stop_event, 600): break
        except ImportError: pass

async def start_background_tasks(bot: Bot) -> BackgroundTaskManager:
    mgr = BackgroundTaskManager(bot); await mgr.start_all(); return mgr

async def stop_background_tasks(mgr: BackgroundTaskManager):
    if mgr: await mgr.stop_all()
