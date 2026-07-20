#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
المهام الخلفية (Background Tasks)
- النشر التلقائي للمنشورات
- النسخ الاحتياطي التلقائي
- التذكيرات والإشعارات
- تنظيف الجلسات والتذاكر القديمة
- مراقبة الذاكرة
- إغلاق المسابقات تلقائياً
- نبض البوت الداخلي
"""

import asyncio
import random
import time as time_module
import json
import os
import shutil
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict

from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from cryptography.fernet import Fernet

from constants import (
    PRIMARY_OWNER_ID, TOKEN, BACKUP_DIR, MAX_BACKUPS,
    DEFAULT_PUBLISH_INTERVAL_SECONDS, PUBLISH_RETRY_DELAY,
    MAX_CHANNELS_PER_CYCLE, SCHEDULED_POSTS_SLEEP,
    REMINDERS_SLEEP, AUTO_BACKUP_SLEEP, CLOUD_BACKUP_ENABLED,
    GOOGLE_AUTH_AVAILABLE, GOOGLE_DRIVE_FOLDER_ID,
    ZSTD_AVAILABLE, ZSTD_COMPRESSOR, ZSTD_DECOMPRESSOR,
    DB_ENCRYPTION, ENCRYPTION_KEY, BACKUP_ENCRYPTION_KEY,
    BACKUP_CIPHER, DB_PATH, user_language, CallbackData
)
from utils import (
    utc_now, mecca_now, utc_now_iso, mecca_now_iso,
    utc_to_mecca, mecca_to_utc, safe_int,
    memory_optimizer, advanced_logger, log_error,
    translate_text, get_user_translation_language,
    safe_send_markdown, encrypt_file_stream, decrypt_file_stream,
    compress_backup, decompress_backup
)
from database import (
    db_pool, execute_db, db_get_channels, db_get_channel_info,
    db_get_next_post, db_mark_published, db_increment_fail_count,
    db_set_last_publish, db_update_next_publish_date,
    db_get_posts_count, db_get_published_count,
    db_reset_all_posts_to_unpublished,
    db_get_auto_recycle, db_set_auto_recycle,
    db_has_active_subscription, db_has_used_trial,
    db_get_user_level, db_update_user_level,
    db_get_user_reminder_settings, db_update_reminder_settings,
    db_get_users_needing_reminder, db_update_last_reminder_sent,
    db_get_user_unpublished_posts, db_get_user_total_posts,
    db_get_user_channels_count, db_get_user_groups_count,
    db_get_referral_stats,
    db_get_updates_channel, db_set_updates_channel,
    db_get_auto_backup, db_set_auto_backup, db_get_last_backup_time,
    db_get_due_scheduled_posts, db_delete_scheduled_post,
    db_update_scheduled_post_fail,
    db_get_active_contests_with_participants, db_get_contest,
    db_get_random_participant, db_set_contest_winner,
    db_stats, db_get_channel_stats, db_get_channel_growth,
    db_get_allowed_sendcode_user,
    db_get_force_subscribe_status, db_get_force_subscribe_channel,
    db_get_log_channel_id,
    db_get_publish_interval_seconds, db_set_publish_interval_seconds,
    db_get_all_users, db_is_banned, db_auto_status,
    db_get_user_posts_for_channel, db_delete_single_post,
    db_unpublished_count,
    db_add_reply, db_del_reply, db_get_reply, db_get_all_replies,
    db_register_group, db_get_user_groups, db_sync_group_admins,
    db_get_security_settings, db_set_security_settings,
    db_add_banned_word, db_remove_banned_word, db_get_banned_words,
    db_register_hidden_owner_group, db_add_hidden_admin,
    db_remove_hidden_admin, db_is_hidden_admin, db_get_hidden_admins,
    db_is_real_admin, add_bot_admin, remove_bot_admin, is_bot_admin,
    db_save_schedule, db_get_schedule, db_set_next_publish_date,
    db_set_last_publish, schedule_cron, db_update_next_publish_date,
    db_set_publish_time,
    db_add_scheduled_post, db_delete_scheduled_post,
    db_update_scheduled_post_fail,
    db_get_auto_reply_settings, db_set_auto_reply_enabled,
    db_set_auto_reply_only_admins, db_toggle_auto_reply,
    db_get_user_auto_reply_status, db_set_user_auto_reply_status,
    db_get_referral_code, db_generate_referral_code,
    db_get_user_by_referral_code,
    db_add_referral, db_auto_reward_referral, db_get_referral_stats,
    db_claim_referral_reward, db_get_referral_settings,
    db_get_welcome_bonus_points,
    db_get_next_ticket_number, db_save_ticket, db_get_user_ticket,
    db_get_all_tickets, db_get_last_ticket_id_for_user,
    db_mark_ticket_replied, db_delete_all_tickets,
    db_set_chat_lock, is_chat_locked,
    db_stats, db_get_channel_stats, db_get_channel_growth,
    db_get_channel_stats_summary,
    db_get_active_contests_with_participants, db_get_user_participation,
    db_get_contest, db_get_random_participant, db_set_contest_winner,
    db_get_contest_winners,
    set_user_language, db_get_all_user_channels_no_limit,
    db_all_users_channels, db_register_channel, db_get_all_bot_channels,
    db_get_user_reminder_settings, db_update_reminder_settings,
    db_get_users_needing_reminder, db_update_last_reminder_sent,
    db_get_subscription_days_left, db_get_auto_recycle,
    get_user_translation_language
)
from security import (
    check_nsfw_cached, check_nsfw_video, load_banned_words_from_file,
    import_banned_words_from_file, BANNED_PATTERNS,
    apply_penalty, execute_ban, execute_mute, execute_kick,
    execute_warn, execute_restrict, execute_pin, execute_unban,
    get_moderation_log, check_bot_admin_permissions,
    delete_message_after_delay, NSFW_ENABLED,
    NSFW_THRESHOLD, NSFW_MAX_FILE_SIZE, NSFW_MAX_VIDEO_SIZE,
    NSFW_FRAMES, security_audit, anomaly_detector,
    is_nsfw_enabled, get_nsfw_threshold, set_nsfw_threshold
)
from web import ws_manager, ws_extended

# ===================== دوال النسخ الاحتياطي =====================
async def create_backup() -> Path:
    """إنشاء نسخة احتياطية كاملة"""
    try:
        encrypted_path = encrypt_db_backup()
        temp_backup = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_backup.close()
        shutil.copy2(DB_PATH, temp_backup.name)
        with open(temp_backup.name, 'rb') as f:
            backup_data = f.read()
        compressed = compress_backup(backup_data)
        encrypted = BACKUP_CIPHER.encrypt(compressed)
        backup_file = BACKUP_DIR / f"backup_{mecca_now().strftime('%Y%m%d_%H%M%S')}.enc"
        with open(backup_file, 'wb') as f:
            f.write(encrypted)
        os.unlink(temp_backup.name)
        # حذف النسخ القديمة
        backups = sorted(BACKUP_DIR.glob("backup_*.enc"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old_backup in backups[MAX_BACKUPS:]:
            old_backup.unlink()
        if CLOUD_BACKUP_ENABLED and GOOGLE_AUTH_AVAILABLE:
            await upload_backup_to_drive(backup_file)
        advanced_logger.log_access(0, "BACKUP_CREATED", {"file": backup_file.name})
        return backup_file
    except Exception as e:
        log_error(e, {"operation": "create_backup"})
        raise

async def list_backups():
    """قائمة النسخ الاحتياطية"""
    backups = sorted(BACKUP_DIR.glob("backup_*.enc"), key=lambda x: x.stat().st_mtime, reverse=True)
    incremental = sorted(BACKUP_DIR.glob("incremental_*.inc"), key=lambda x: x.stat().st_mtime, reverse=True)
    return list(backups) + list(incremental)

async def restore_backup(backup_path: Path):
    """استعادة نسخة احتياطية"""
    if not backup_path.exists():
        raise FileNotFoundError(f"الملف {backup_path} غير موجود")
    with open(backup_path, 'rb') as f:
        encrypted = f.read()
    try:
        decrypted = BACKUP_CIPHER.decrypt(encrypted)
    except Exception as e:
        raise ValueError(f"فشل فك التشفير: {e}")
    try:
        decompressed = decompress_backup(decrypted)
    except Exception as e:
        raise ValueError(f"فشل فك الضغط: {e}")
    if backup_path.suffix == '.inc':
        data = json.loads(decompressed.decode('utf-8'))
        async def _merge_data(conn):
            if 'posts' in data:
                for post in data['posts']:
                    await conn.execute(
                        "INSERT OR IGNORE INTO posts (id, channel_db_id, text, media_type, media_file_id, published, fail_count, views_count, last_view_time, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (post['id'], post['channel_db_id'], post['text'], post['media_type'], post['media_file_id'], post['published'], post['fail_count'], post['views_count'], post['last_view_time'], post['created_at'])
                    )
            if 'users' in data:
                for user in data['users']:
                    await conn.execute(
                        "INSERT OR IGNORE INTO users (user_id, auto_publish, banned, trial_used, subscription_end, referral_code, referred_by, active_channel, auto_reply_enabled, auto_recycle) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (user['user_id'], user['auto_publish'], user['banned'], user['trial_used'], user['subscription_end'], user['referral_code'], user['referred_by'], user['active_channel'], user['auto_reply_enabled'], user['auto_recycle'])
                    )
            await conn.commit()
        await execute_db(_merge_data)
        advanced_logger.log_access(0, "INCREMENTAL_RESTORED", {"file": backup_path.name})
    else:
        temp_restore = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        temp_restore.write(decompressed)
        temp_restore.close()
        current_backup = BACKUP_DIR / f"pre_restore_{mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(DB_PATH, current_backup)
        shutil.copy2(temp_restore.name, DB_PATH)
        os.unlink(temp_restore.name)
        await db_pool.initialize()
        advanced_logger.log_access(0, "FULL_RESTORED", {"file": backup_path.name})

async def incremental_backup() -> Optional[Path]:
    """نسخ احتياطي متزايد"""
    try:
        last_backup = await db_get_last_backup_time()
        if last_backup:
            last_time = datetime.fromisoformat(last_backup)
        else:
            last_time = utc_now() - timedelta(days=7)
        backup_data = {}
        async def _get_new_posts(conn):
            cur = await conn.execute(
                "SELECT * FROM posts WHERE created_at > ? LIMIT 1000",
                (last_time.isoformat(),)
            )
            return await cur.fetchall()
        new_posts = await execute_db(_get_new_posts)
        if new_posts:
            backup_data['posts'] = [dict(post) for post in new_posts]
        async def _get_new_users(conn):
            cur = await conn.execute(
                "SELECT * FROM users WHERE user_id IN (SELECT user_id FROM users_cache WHERE last_updated > ?)",
                (last_time.isoformat(),)
            )
            return await cur.fetchall()
        new_users = await execute_db(_get_new_users)
        if new_users:
            backup_data['users'] = [dict(user) for user in new_users]
        if backup_data:
            data_json = json.dumps(backup_data, default=str)
            compressed = compress_backup(data_json.encode('utf-8'))
            encrypted = BACKUP_CIPHER.encrypt(compressed)
            backup_file = BACKUP_DIR / f"incremental_{mecca_now().strftime('%Y%m%d_%H%M%S')}.inc"
            with open(backup_file, 'wb') as f:
                f.write(encrypted)
            advanced_logger.log_access(0, "INCREMENTAL_BACKUP", {"file": backup_file.name})
            return backup_file
        return None
    except Exception as e:
        log_error(e, {"operation": "incremental_backup"})
        return None

async def upload_backup_to_drive(backup_path: Path, max_retries: int = 3) -> Optional[str]:
    """رفع النسخة الاحتياطية إلى Google Drive"""
    if not CLOUD_BACKUP_ENABLED or not GOOGLE_AUTH_AVAILABLE or not GOOGLE_DRIVE_FOLDER_ID:
        return None
    if not backup_path.exists():
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        from constants import GOOGLE_CREDENTIALS_FILE, TOKEN_FILE
        for attempt in range(max_retries):
            try:
                creds = None
                token_path = Path(TOKEN_FILE)
                if token_path.exists():
                    try:
                        creds = Credentials.from_authorized_user_file(
                            str(token_path),
                            ['https://www.googleapis.com/auth/drive.file']
                        )
                    except:
                        pass
                if creds and creds.valid:
                    service = build('drive', 'v3', credentials=creds)
                elif creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    with open(token_path, 'w') as token:
                        token.write(creds.to_json())
                    service = build('drive', 'v3', credentials=creds)
                else:
                    from google_auth_oauthlib.flow import InstalledAppFlow
                    flow = InstalledAppFlow.from_client_secrets_file(
                        GOOGLE_CREDENTIALS_FILE,
                        ['https://www.googleapis.com/auth/drive.file']
                    )
                    creds = flow.run_local_server(port=0)
                    with open(token_path, 'w') as token:
                        token.write(creds.to_json())
                    service = build('drive', 'v3', credentials=creds)
                file_name = f"backup_{mecca_now().strftime('%Y%m%d_%H%M%S')}.enc"
                # حذف الملفات القديمة
                try:
                    results = service.files().list(
                        q=f"'{GOOGLE_DRIVE_FOLDER_ID}' in parents",
                        orderBy="createdTime desc",
                        pageSize=15,
                        fields="files(id, name)"
                    ).execute()
                    files = results.get('files', [])
                    for old_file in files[10:]:
                        try:
                            service.files().delete(fileId=old_file['id']).execute()
                        except:
                            pass
                except:
                    pass
                media = MediaFileUpload(
                    str(backup_path),
                    mimetype='application/octet-stream',
                    resumable=True,
                    chunksize=1024*1024
                )
                file_metadata = {
                    'name': file_name,
                    'parents': [GOOGLE_DRIVE_FOLDER_ID]
                }
                file = service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id'
                )
                response = file.execute()
                file_id = response.get('id')
                advanced_logger.log_access(0, "DRIVE_UPLOAD", {"file": file_name, "id": file_id})
                return file_id
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
    except Exception as e:
        log_error(e, {"operation": "upload_backup_to_drive"})
        return None

# ===================== حلقة النشر التلقائي =====================
async def auto_publish_loop_improved(bot: Bot):
    """حلقة النشر التلقائي للمنشورات"""
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
                    advanced_logger.log_access(user_id, "AUTO_RECYCLE", {"channel": ch_tele_id, "total": total})
                    await db_reset_all_posts_to_unpublished(ch_db_id)
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"♻️ **تم إعادة تدوير المنشورات تلقائياً!**\n\n📡 القناة: {ch_tele_id}\n📝 تم إعادة تعيين {total} منشور للنشر من جديد.",
                            parse_mode="MarkdownV2"
                        )
                    except:
                        pass
                    return
                else:
                    advanced_logger.log_access(user_id, "PUBLISH_STOPPED", {"channel": ch_tele_id, "reason": "auto_recycle_disabled"})
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=f"⚠️ **توقف النشر التلقائي**\n\n📡 القناة: {ch_tele_id}\n📝 تم نشر جميع المنشورات ({published}/{total}).\n\n♻️ إعادة التدوير التلقائي معطل.\n📌 قم بتفعيله من الإعدادات أو أضف منشورات جديدة.",
                            parse_mode="MarkdownV2"
                        )
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
                        advanced_logger.log_access(user_id, "AUTO_RECYCLE_EMPTY", {"channel": ch_tele_id, "total": total})
                        try:
                            await bot.send_message(
                                chat_id=user_id,
                                text=f"♻️ **تم إعادة تدوير المنشورات تلقائياً!**\n\n📡 القناة: {ch_tele_id}\n📝 تم إعادة تعيين {total} منشور للنشر من جديد.",
                                parse_mode="MarkdownV2"
                            )
                        except:
                            pass
                        return
                    else:
                        return
                else:
                    return
            translation_lang = await get_user_translation_language(user_id)
            final_text = post['text']
            if translation_lang != 'off' and final_text:
                try:
                    translated = await translate_text(final_text, translation_lang)
                    if translated and translated != final_text:
                        final_text = f"{final_text}\n\n🌐 {translated}"
                except:
                    pass
            success = False
            for attempt in range(3):
                try:
                    if post['media_type'] == 'photo' and post['media_file_id']:
                        await bot.send_photo(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                    elif post['media_type'] == 'video' and post['media_file_id']:
                        await bot.send_video(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                    elif post['media_type'] == 'document' and post['media_file_id']:
                        await bot.send_document(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                    elif post['media_type'] == 'audio' and post['media_file_id']:
                        await bot.send_audio(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                    elif post['media_type'] == 'voice' and post['media_file_id']:
                        await bot.send_voice(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                    elif post['media_type'] == 'animation' and post['media_file_id']:
                        await bot.send_animation(ch_tele_id, post['media_file_id'], caption=final_text if final_text else None)
                    else:
                        await bot.send_message(ch_tele_id, final_text, parse_mode=None)
                    success = True
                    break
                except Exception as e:
                    advanced_logger.log_error(f"محاولة {attempt+1} فشلت في النشر", e, {"channel": ch_tele_id})
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
            if success:
                await db_mark_published(post['id'])
                await db_set_last_publish(ch_db_id, utc_now())
                await db_update_next_publish_date(ch_db_id)
            else:
                await db_increment_fail_count(post['id'])
                advanced_logger.log_error(f"فشل دائم في نشر المنشور {post['id']}", None, {"channel": ch_tele_id})
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
            log_error(e, {"operation": "auto_publish_loop"})
            consecutive_errors += 1
            backoff = min(backoff * 1.5, max_backoff)
            await asyncio.sleep(backoff)

# ===================== حلقة المنشورات المجدولة =====================
async def run_scheduled_posts_loop_improved(bot: Bot):
    """حلقة تنفيذ المنشورات المجدولة"""
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
                        advanced_logger.log_error(f"تم حذف منشور مجدول بعد 5 محاولات فاشلة: {post_id}", None, {"chat_id": chat_id})
                    else:
                        log_error(e, {"operation": "scheduled_post", "post_id": post_id})
            consecutive_errors = 0
            backoff = SCHEDULED_POSTS_SLEEP
        except Exception as e:
            log_error(e, {"operation": "scheduled_posts_loop"})
            backoff = min(backoff * 1.5, max_backoff)
            await asyncio.sleep(backoff)

# ===================== حلقة التذكيرات والإشعارات =====================
async def send_reminders_loop_improved(bot: Bot):
    """حلقة إرسال التذكيرات والإشعارات"""
    await asyncio.sleep(30)
    asyncio.create_task(daily_reminder_task(bot))
    asyncio.create_task(weekly_reminder_task(bot))
    while True:
        try:
            now = utc_now()
            now_mecca = utc_to_mecca(now)
            today_str = now_mecca.strftime("%Y-%m-%d")
            users_to_remind = await db_get_users_needing_reminder()
            for user_data in users_to_remind:
                user_id = user_data['user_id']
                days_left = user_data['days_left']
                lang = user_data['notification_lang']
                original_lang = user_language.get(user_id, 'ar')
                user_language[user_id] = lang
                text = f"⚠️ **تنبيه!**\nاشتراكك ينتهي خلال {days_left} أيام\nقم بتجديده الآن لتستمر الميزات 💎"
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
            log_error(e, {"operation": "reminders_loop"})
            await asyncio.sleep(60)

async def daily_reminder_task(bot: Bot):
    """مهمة الإشعار اليومي"""
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
                    original_lang = user_language.get(user_id, 'ar')
                    user_language[user_id] = lang
                    channels = await db_get_user_channels_count(user_id)
                    total_posts = await db_get_user_total_posts(user_id)
                    unpublished = await db_get_user_unpublished_posts(user_id)
                    groups = await db_get_user_groups_count(user_id)
                    text = f"📊 **تقريرك اليومي**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 القنوات: {channels}\n📝 إجمالي المنشورات: {total_posts}\n⏳ غير المنشورة: {unpublished}\n👥 المجموعات: {groups}"
                    try:
                        await safe_send_markdown(bot, user_id, text)
                    except:
                        pass
                    user_language[user_id] = original_lang
                    await asyncio.sleep(0.3)
            await asyncio.sleep(3600)
        except Exception as e:
            log_error(e, {"operation": "daily_reminder_task"})
            await asyncio.sleep(60)

async def weekly_reminder_task(bot: Bot):
    """مهمة الإشعار الأسبوعي"""
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
                    original_lang = user_language.get(user_id, 'ar')
                    user_language[user_id] = lang
                    channels = await db_get_user_channels_count(user_id)
                    total_posts = await db_get_user_total_posts(user_id)
                    unpublished = await db_get_user_unpublished_posts(user_id)
                    groups = await db_get_user_groups_count(user_id)
                    referral_stats = await db_get_referral_stats(user_id)
                    text = f"📈 **تقريرك الأسبوعي**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 القنوات: {channels}\n📝 إجمالي المنشورات: {total_posts}\n⏳ غير المنشورة: {unpublished}\n👥 المجموعات: {groups}\n🔗 الإحالات: {referral_stats['total_referrals']}"
                    try:
                        await safe_send_markdown(bot, user_id, text)
                    except:
                        pass
                    user_language[user_id] = original_lang
                    await asyncio.sleep(0.3)
            await asyncio.sleep(3600)
        except Exception as e:
            log_error(e, {"operation": "weekly_reminder_task"})
            await asyncio.sleep(60)

# ===================== حلقة النسخ الاحتياطي التلقائي =====================
async def auto_backup_loop():
    """حلقة النسخ الاحتياطي التلقائي"""
    consecutive_errors = 0
    backoff = AUTO_BACKUP_SLEEP
    max_backoff = 7 * 24 * 60 * 60
    while True:
        try:
            await asyncio.sleep(AUTO_BACKUP_SLEEP)
            auto_enabled = await db_get_auto_backup()
            if auto_enabled:
                last_backup = await db_get_last_backup_time()
                if not last_backup:
                    await create_backup()
                else:
                    last_time = datetime.fromisoformat(last_backup)
                    if (utc_now() - last_time).days >= 7:
                        await create_backup()
                    else:
                        await incremental_backup()
                async def _update_backup_time(conn):
                    await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_backup', ?)", (utc_now_iso(),))
                    await conn.commit()
                await execute_db(_update_backup_time)
            consecutive_errors = 0
            backoff = AUTO_BACKUP_SLEEP
        except Exception as e:
            log_error(e, {"operation": "auto_backup_loop"})
            backoff = min(backoff * 1.5, max_backoff)
            await asyncio.sleep(backoff)

# ===================== حلقة تنظيف الجلسات والتذاكر =====================
async def cleanup_expired_sessions_improved():
    """تنظيف الجلسات المنتهية والتذاكر القديمة"""
    CLEANUP_SLEEP = 3600
    while True:
        await asyncio.sleep(CLEANUP_SLEEP)
        now = time_module.time()
        async def _cleanup_sessions(conn):
            await conn.execute("DELETE FROM web_sessions WHERE expires < ?", (now,))
            await conn.commit()
        await execute_db(_cleanup_sessions)
        async def _cleanup_tickets(conn):
            cutoff = (utc_now() - timedelta(days=30)).isoformat()
            await conn.execute("DELETE FROM support_tickets WHERE created_at < ? AND status='closed'", (cutoff,))
            await conn.commit()
        await execute_db(_cleanup_tickets)
        advanced_logger.log_access(0, "CLEANUP_COMPLETED", {})

# ===================== حلقة بث الإحصائيات عبر WebSocket =====================
async def broadcast_stats_periodically():
    """بث الإحصائيات عبر WebSocket بشكل دوري"""
    while True:
        await asyncio.sleep(5)
        total, banned, posts, groups, channels = await db_stats()
        await ws_manager.broadcast({
            'type': 'stats',
            'data': {
                'total_users': total,
                'active_users': total - banned,
                'banned_users': banned,
                'pending_posts': posts,
                'groups': groups,
                'channels': channels
            }
        })

# ===================== حلقة إغلاق المسابقات تلقائياً =====================
async def auto_close_contests_loop(bot: Bot):
    """إغلاق المسابقات المنتهية تلقائياً"""
    while True:
        await asyncio.sleep(3600)
        try:
            now = utc_now().isoformat()
            async def _get_expired(conn):
                cur = await conn.execute(
                    "SELECT id FROM contests WHERE status = 'active' AND end_date <= ?",
                    (now,)
                )
                return [row[0] for row in await cur.fetchall()]
            expired = await execute_db(_get_expired)
            for contest_id in expired:
                winner_id = await db_get_random_participant(contest_id)
                if winner_id:
                    await db_set_contest_winner(contest_id, winner_id)
                    contest = await db_get_contest(contest_id)
                    try:
                        await bot.send_message(
                            winner_id,
                            f"🎉 **تهانينا!**\nلقد فزت في مسابقة **{contest['title']}**\n🎁 الجائزة: {contest['prize']}"
                        )
                    except:
                        pass
                    await bot.send_message(
                        PRIMARY_OWNER_ID,
                        f"🤖 تم إغلاق المسابقة #{contest_id} تلقائياً.\nالفائز: {winner_id}"
                    )
                else:
                    async def _close(conn):
                        await conn.execute(
                            "UPDATE contests SET status = 'finished' WHERE id = ?",
                            (contest_id,)
                        )
                        await conn.commit()
                    await execute_db(_close)
        except Exception as e:
            log_error(e, {"operation": "auto_close_contests_loop"})

# ===================== حلقة مراقبة الذاكرة =====================
async def memory_monitor():
    """مراقبة استخدام الذاكرة وتنظيفها تلقائياً"""
    while True:
        try:
            from utils import get_ram_usage
            ram = get_ram_usage()
            if ram['percent'] > 80:
                advanced_logger.log_access(0, "MEMORY_HIGH", {"percent": ram['percent']})
                memory_optimizer()
                advanced_logger.log_access(0, "MEMORY_OPTIMIZED", {})
            await asyncio.sleep(60)
        except Exception as e:
            log_error(e, {"operation": "memory_monitor"})
            await asyncio.sleep(60)

# ===================== حلقة النبض الداخلي (لـ Render) =====================
async def self_ping_loop():
    """نبض داخلي للحفاظ على تشغيل البوت على Render"""
    await asyncio.sleep(10)
    external_url = os.getenv("RENDER_EXTERNAL_URL", "")
    if external_url:
        url = f"{external_url}/"
    else:
        url = f"http://0.0.0.0:{os.getenv('PORT', '10000')}/"
    while True:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    advanced_logger.log_access(0, "SELF_PING", {"status": resp.status})
        except Exception as e:
            advanced_logger.log_error("فشل النبض الداخلي", e)
        await asyncio.sleep(600)

# ===================== دوال مساعدة =====================
async def check_bot_permissions(bot, chat_id: int) -> tuple:
    """التحقق من صلاحيات البوت في القناة"""
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        if me.status not in ['administrator', 'creator']:
            return False, "البوت ليس مشرفاً"
        if not me.can_post_messages:
            return False, "البوت لا يملك صلاحية النشر"
        return True, ""
    except:
        return False, "فشل التحقق من صلاحيات البوت"

async def cleanup_points_cache():
    """تنظيف ذاكرة النقاط المؤقتة"""
    from utils import user_points_last_hour
    while True:
        await asyncio.sleep(3600)
        now = time_module.time()
        to_delete = [uid for uid, (_, ts) in user_points_last_hour.items() if now - ts > 3600]
        for uid in to_delete:
            del user_points_last_hour[uid]

# ===================== دوال التشفير الإضافية =====================
def encrypt_db_backup():
    """تشفير قاعدة البيانات للنسخ الاحتياطي"""
    from constants import DB_ENCRYPTION, ENCRYPTION_KEY
    if not DB_ENCRYPTION:
        return DB_PATH
    cipher = Fernet(ENCRYPTION_KEY)
    encrypted_path = DB_PATH.with_suffix('.enc')
    encrypt_file_stream(DB_PATH, encrypted_path, cipher)
    return encrypted_path

def compress_backup(data: bytes) -> bytes:
    """ضغط البيانات للنسخ الاحتياطي"""
    from constants import ZSTD_AVAILABLE, ZSTD_COMPRESSOR
    if ZSTD_AVAILABLE:
        try:
            return ZSTD_COMPRESSOR.compress(data)
        except:
            pass
    import gzip
    return gzip.compress(data)

def decompress_backup(data: bytes) -> bytes:
    """فك ضغط البيانات من النسخ الاحتياطي"""
    from constants import ZSTD_AVAILABLE, ZSTD_DECOMPRESSOR
    if ZSTD_AVAILABLE:
        try:
            return ZSTD_DECOMPRESSOR.decompress(data)
        except:
            pass
    import gzip
    return gzip.decompress(data)
