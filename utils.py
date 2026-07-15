import os
import re
import json
import time
import gzip
import base64
import tempfile
import hashlib
import secrets
import logging
import asyncio
import shutil
import gc
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
import aiohttp
from cryptography.fernet import Fernet
from config import *
from database import *

logger = logging.getLogger(__name__)

def clean_text_for_telegram(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\u200b\u200c\u200d\u2060\uFEFF\u202a\u202b\u202c\u202d\u202e]', "", text)
    text = text.replace("\ufeff", "").replace("\ufffc", "")
    return text

def escape_markdown_v2(text: str) -> str:
    if not text:
        return ""
    special_chars = r"_*[]()~`>#+\-=|{}.!"
    for char in special_chars:
        text = text.replace(char, f"\\{char}")
    return text

def sanitize_text(text: str, max_length: int = 4096) -> str:
    if not text:
        return ""
    try:
        import bleach
        cleaned = bleach.clean(text, tags=["b", "i", "u", "s", "a", "code", "pre", "strong", "em"], attributes={"a": ["href", "title"]}, styles=[], strip=True)
    except:
        cleaned = text
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned

def encode_callback_data(data: str) -> str:
    import urllib.parse
    return urllib.parse.quote(data, safe="")

def decode_callback_data(data: str) -> str:
    import urllib.parse
    return urllib.parse.unquote(data)

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

def compress_backup(data: bytes) -> bytes:
    try:
        import zstandard
        compressor = zstandard.ZstdCompressor(level=3)
        return compressor.compress(data)
    except:
        return gzip.compress(data)

def decompress_backup(data: bytes) -> bytes:
    try:
        import zstandard
        decompressor = zstandard.ZstdDecompressor()
        return decompressor.decompress(data)
    except:
        return gzip.decompress(data)

def encrypt_file_stream(src: Path, dst: Path, cipher: Fernet, chunk_size: int = 64*1024):
    with open(src, "rb") as f_in, open(dst, "wb") as f_out:
        while True:
            chunk = f_in.read(chunk_size)
            if not chunk:
                break
            encrypted_chunk = cipher.encrypt(chunk)
            f_out.write(encrypted_chunk)

def decrypt_file_stream(src: Path, dst: Path, cipher: Fernet, chunk_size: int = 64*1024):
    with open(src, "rb") as f_in, open(dst, "wb") as f_out:
        while True:
            chunk = f_in.read(chunk_size)
            if not chunk:
                break
            decrypted_chunk = cipher.decrypt(chunk)
            f_out.write(decrypted_chunk)

def encrypt_db_backup() -> Path:
    if not DB_ENCRYPTION:
        return DB_PATH
    cipher = Fernet(ENCRYPTION_KEY)
    encrypted_path = DB_PATH.with_suffix(".enc")
    encrypt_file_stream(DB_PATH, encrypted_path, cipher)
    return encrypted_path

def decrypt_db_backup(encrypted_path: Path) -> bytes:
    if not DB_ENCRYPTION:
        with open(encrypted_path, "rb") as f:
            return f.read()
    cipher = Fernet(ENCRYPTION_KEY)
    temp_decrypted = encrypted_path.with_suffix(".db.tmp")
    decrypt_file_stream(encrypted_path, temp_decrypted, cipher)
    with open(temp_decrypted, "rb") as f:
        data = f.read()
    temp_decrypted.unlink()
    return data

def memory_optimizer():
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
        _reply_cache.clear()
        _reply_cache_time.clear()
        user_language.clear()
        user_translation_settings_cache.clear()
        user_points_last_hour.clear()
        gc.collect()
        return True
    except Exception as e:
        logger.error(f"Memory optimizer failed: {e}")
        return False

async def memory_optimizer_loop():
    while True:
        await asyncio.sleep(300)
        try:
            memory_optimizer()
        except Exception as e:
            logger.error(f"Memory optimizer loop failed: {e}")

def contains_link(text):
    patterns = [r"https?://\S+", r"www\.\S+", r"t\.me/\S+", r"telegram\.me/\S+", r"\b[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)+\S*"]
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)

def contains_mention(text):
    return bool(re.search(r"@\w+", text))

async def check_bot_admin_permissions(bot, chat_id: int) -> dict:
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        if me.status not in ["administrator", "creator"]:
            return {"can_act": False, "reason": "البوت ليس مشرفاً"}
        permissions = {"can_ban": getattr(me, "can_restrict_members", False), "can_pin": getattr(me, "can_pin_messages", False), "can_delete": getattr(me, "can_delete_messages", False)}
        missing = [k for k, v in permissions.items() if not v]
        if missing:
            return {"can_act": False, "reason": f"البوت يحتاج صلاحيات: {', '.join(missing)}"}
        return {"can_act": True, "reason": ""}
    except Exception as e:
        return {"can_act": False, "reason": str(e)}

async def check_bot_permissions(bot, channel_id: str) -> tuple:
    try:
        me = await bot.get_chat_member(channel_id, bot.id)
        if me.status not in ["administrator", "creator"]:
            return False, "البوت ليس مشرفاً في القناة"
        if not me.can_post_messages:
            return False, "البوت لا يملك صلاحية النشر"
        return True, ""
    except Exception as e:
        return False, str(e)[:100]

async def apply_penalty(bot, chat_id, user_id, settings):
    penalty = settings.get("auto_penalty", "none")
    if penalty == "none":
        return
    if await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id):
        return
    if penalty == "kick":
        await execute_kick(bot, chat_id, user_id, "مخالفة قواعد المجموعة")
    elif penalty == "ban":
        await execute_ban(bot, chat_id, user_id, reason="مخالفة قواعد المجموعة")
    elif penalty == "mute":
        duration = settings.get("auto_mute_duration", 60)
        await execute_mute(bot, chat_id, user_id, duration, "مخالفة قواعد المجموعة")

async def execute_ban(bot, chat_id: int, user_id: int, until_date=None, reason: str = "", moderator_id: int = None):
    try:
        if await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id):
            if moderator_id != PRIMARY_OWNER_ID:
                return False, "❌ لا يمكن معاقبة مالك مخفي أو مشرف مخفي!"
        if user_id == bot.id:
            return False, "❌ لا يمكن حظر البوت نفسه!"
        await bot.ban_chat_member(chat_id, user_id, until_date=until_date)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'ban', 0, ?, ?, ?)", (chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم حظر المستخدم `{user_id}` بنجاح"
    except Exception as e:
        return False, f"❌ فشل الحظر: {str(e)[:100]}"

async def execute_mute(bot, chat_id: int, user_id: int, duration_minutes: int = None, reason: str = "", moderator_id: int = None):
    try:
        if await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id):
            if moderator_id != PRIMARY_OWNER_ID:
                return False, "❌ لا يمكن معاقبة مالك مخفي أو مشرف مخفي!"
        if user_id == bot.id:
            return False, "❌ لا يمكن كتم البوت نفسه!"
        until_date = None
        duration_text = ""
        if duration_minutes and duration_minutes > 0:
            until_date = utc_now() + timedelta(minutes=duration_minutes)
            if duration_minutes < 60:
                duration_text = f" لمدة {duration_minutes} دقيقة"
            elif duration_minutes < 1440:
                duration_text = f" لمدة {duration_minutes // 60} ساعة"
            else:
                duration_text = f" لمدة {duration_minutes // 1440} يوم"
        else:
            duration_text = " بشكل دائم"
            duration_minutes = -1
        permissions = ChatPermissions(can_send_messages=False)
        await bot.restrict_chat_member(chat_id, user_id, permissions, until_date=until_date)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'mute', ?, ?, ?, ?)", (chat_id, user_id, duration_minutes, moderator_id or PRIMARY_OWNER_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم كتم المستخدم `{user_id}`{duration_text}"
    except Exception as e:
        return False, f"❌ فشل الكتم: {str(e)[:100]}"

async def execute_kick(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    try:
        if await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id):
            if moderator_id != PRIMARY_OWNER_ID:
                return False, "❌ لا يمكن معاقبة مالك مخفي أو مشرف مخفي!"
        if user_id == bot.id:
            return False, "❌ لا يمكن طرد البوت نفسه!"
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'kick', 0, ?, ?, ?)", (chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم طرد المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل الطرد: {str(e)[:100]}"

async def execute_warn(bot, chat_id: int, user_id: int, moderator_id: int, reason: str = "", auto_ban_limit: int = 3):
    try:
        if await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id):
            if moderator_id != PRIMARY_OWNER_ID:
                return False, "❌ لا يمكن معاقبة مالك مخفي أو مشرف مخفي!"
        if user_id == bot.id:
            return False, "❌ لا يمكن تحذير البوت نفسه!"
        async def _add_warning(conn):
            cur = await conn.execute("SELECT warnings FROM user_warnings WHERE user_id=? AND chat_id=?", (user_id, chat_id))
            row = await cur.fetchone()
            warnings = row[0] + 1 if row else 1
            await conn.execute("INSERT OR REPLACE INTO user_warnings (user_id, chat_id, warnings) VALUES (?,?,?)", (user_id, chat_id, warnings))
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'warn', ?, ?, ?, ?)", (chat_id, user_id, warnings, moderator_id, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
            return warnings
        warnings = await execute_db(_add_warning)
        if warnings >= auto_ban_limit:
            await execute_ban(bot, chat_id, user_id, reason=f"تلقائي بعد {warnings} تحذيرات", moderator_id=moderator_id)
            async def _clear_warnings(conn):
                await conn.execute("DELETE FROM user_warnings WHERE user_id=? AND chat_id=?", (user_id, chat_id))
                await conn.commit()
            await execute_db(_clear_warnings)
            return True, f"⚠️ تم تحذير المستخدم `{user_id}` ({warnings}/{auto_ban_limit}) وتم حظره تلقائياً"
        return True, f"⚠️ تم تحذير المستخدم `{user_id}` ({warnings}/{auto_ban_limit})"
    except Exception as e:
        return False, f"❌ فشل التحذير: {str(e)[:100]}"

async def execute_restrict(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    try:
        if await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id):
            if moderator_id != PRIMARY_OWNER_ID:
                return False, "❌ لا يمكن معاقبة مالك مخفي أو مشرف مخفي!"
        if user_id == bot.id:
            return False, "❌ لا يمكن تقييد البوت نفسه!"
        permissions = ChatPermissions(can_send_messages=True, can_send_media_messages=False, can_send_other_messages=False, can_add_web_page_previews=False)
        await bot.restrict_chat_member(chat_id, user_id, permissions)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'restrict', 0, ?, ?, ?)", (chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم تقييد المستخدم `{user_id}` (لا يمكنه إرسال وسائط)"
    except Exception as e:
        return False, f"❌ فشل التقييد: {str(e)[:100]}"

async def execute_pin(bot, chat_id: int, message_id: int, disable_notification: bool = False):
    try:
        await bot.pin_chat_message(chat_id, message_id, disable_notification=disable_notification)
        return True, "✅ تم تثبيت الرسالة"
    except Exception as e:
        return False, f"❌ فشل التثبيت: {str(e)[:100]}"

async def execute_unban(bot, chat_id: int, user_id: int, moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن إلغاء حظر البوت نفسه!"
        await bot.unban_chat_member(chat_id, user_id)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'unban', 0, ?, ?, ?)", (chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم إلغاء حظر المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل إلغاء الحظر: {str(e)[:100]}"

async def execute_unmute(bot, chat_id: int, user_id: int, moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن إلغاء كتم البوت نفسه!"
        permissions = ChatPermissions(can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True)
        await bot.restrict_chat_member(chat_id, user_id, permissions)
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'unmute', 0, ?, ?, ?)", (chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم إلغاء كتم المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل إلغاء الكتم: {str(e)[:100]}"

async def get_moderation_log(chat_id: int, limit: int = 20) -> str:
    async def _get_log(conn):
        cur = await conn.execute("SELECT user_id, action, duration_minutes, reason, created_at FROM moderation_log WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?", (chat_id, limit))
        return await cur.fetchall()
    logs = await execute_db(_get_log)
    if not logs:
        return "📭 لا توجد سجلات إجراءات"
    text = "📜 **سجل إجراءات المجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user_id, action, duration, reason, created_at in logs:
        try:
            dt = datetime.fromisoformat(created_at)
            dt_mecca = utc_to_mecca(dt)
            time_str = dt_mecca.strftime("%Y-%m-%d %H:%M")
        except:
            time_str = created_at[:16] if created_at else "?"
        duration_text = ""
        if action == "mute" and duration:
            if duration == -1:
                duration_text = " (دائم)"
            elif duration < 60:
                duration_text = f" ({duration} دقيقة)"
            elif duration < 1440:
                duration_text = f" ({duration//60} ساعة)"
            else:
                duration_text = f" ({duration//1440} يوم)"
        elif action == "warn" and duration:
            duration_text = f" (تحذير #{duration})"
        reason_text = f"\n   📝 السبب: {reason[:50]}" if reason else ""
        text += f"• `{user_id}` → {action}{duration_text}{reason_text}\n   🕐 {time_str}\n\n"
    return text

async def is_user_subscribed(bot, user_id, channel):
    if not channel:
        return True
    channel = channel.lstrip("@")
    try:
        member = await bot.get_chat_member(f"@{channel}", user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

async def ensure_force_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None) -> bool:
    if user_id is None:
        if update.effective_user is None:
            return True
        user_id = update.effective_user.id
    if user_id == PRIMARY_OWNER_ID or await is_bot_admin(user_id):
        return True
    if not await db_get_force_subscribe_status():
        return True
    channel = await db_get_force_subscribe_channel()
    if not channel:
        return True
    if await is_user_subscribed(context.bot, user_id, channel):
        return True
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("📢 اشترك في القناة", url=f"https://t.me/{channel.lstrip('@')}"), InlineKeyboardButton("🔄 تأكد من الاشتراك", callback_data="check_subscribe")], [InlineKeyboardButton("❌ إلغاء", callback_data="back")]])
    msg = f"🔒 **اشتراك إجباري**\n\nيجب عليك الاشتراك في قناتنا أولاً:\n👉 @{channel.lstrip('@')}\n\nبعد الاشتراك، اضغط على زر التحقق."
    try:
        if update.callback_query:
            await safe_edit_markdown(update.callback_query, msg, reply_markup=keyboard)
        elif update.message:
            await safe_send_markdown(context.bot, user_id, msg, reply_markup=keyboard)
    except Exception:
        pass
    return False

async def check_nsfw_cached(image_bytes: bytes, cache_key: str) -> dict:
    if cache_key in NSFW_CACHE:
        cached_result, timestamp = NSFW_CACHE[cache_key]
        if time.time() - timestamp < NSFW_CACHE_TTL:
            return cached_result
    result = await check_nsfw_image(image_bytes)
    NSFW_CACHE[cache_key] = (result, time.time())
    if len(NSFW_CACHE) > 100:
        expired_keys = []
        for key, (_, timestamp) in NSFW_CACHE.items():
            if time.time() - timestamp > NSFW_CACHE_TTL:
                expired_keys.append(key)
        for key in expired_keys:
            del NSFW_CACHE[key]
    return result

async def check_nsfw_image(image_bytes: bytes) -> dict:
    if not SIGHTENGINE_API_USER or not SIGHTENGINE_API_SECRET:
        return {"error": "مفاتيح API غير مضبوطة"}
    try:
        import aiohttp
        import base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        async with aiohttp.ClientSession() as session:
            url = "https://api.sightengine.com/1.0/check.json"
            params = {"api_user": SIGHTENGINE_API_USER, "api_secret": SIGHTENGINE_API_SECRET, "models": "nudity-2.0,wad", "image_base64": image_b64}
            async with session.get(url, params=params, timeout=10) as response:
                data = await response.json()
                if "error" in data:
                    return {"error": data["error"]["message"]}
                nsfw_score = 0.0
                if "nudity" in data:
                    nsfw_data = data["nudity"]
                    if "raw" in nsfw_data:
                        nsfw_score = nsfw_data["raw"]
                    elif "sexual_activity" in nsfw_data:
                        nsfw_score = nsfw_data["sexual_activity"]
                    else:
                        nsfw_score = max(nsfw_data.values()) if nsfw_data else 0.0
                elif "weapon" in data:
                    weapon_score = data["weapon"]
                    if weapon_score > 0.5:
                        nsfw_score = max(nsfw_score, weapon_score)
                is_nsfw = nsfw_score >= NSFW_THRESHOLD
                return {"nsfw": is_nsfw, "nsfw_score": nsfw_score, "details": data}
    except Exception as e:
        logger.error(f"NSFW check error: {e}")
        return {"error": str(e)}

async def check_nsfw_video(video_bytes: bytes, frames: int = 5) -> dict:
    if not CV2_AVAILABLE:
        return {"error": "مكتبة OpenCV غير مثبتة"}
    try:
        import cv2
        import numpy as np
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_file:
            temp_file.write(video_bytes)
            video_path = temp_file.name
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            os.unlink(video_path)
            return {"error": "لا يمكن فتح الفيديو"}
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames == 0:
            cap.release()
            os.unlink(video_path)
            return {"error": "الفيديو لا يحتوي على إطارات"}
        frame_indices = []
        if total_frames <= frames:
            frame_indices = list(range(total_frames))
        else:
            step = total_frames // frames
            for i in range(frames):
                frame_indices.append(min(i * step, total_frames - 1))
        nsfw_scores = []
        frames_analyzed = 0
        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue
            _, img_encoded = cv2.imencode(".jpg", frame)
            img_bytes = img_encoded.tobytes()
            result = await check_nsfw_image(img_bytes)
            if "error" not in result and "nsfw_score" in result:
                nsfw_scores.append(result["nsfw_score"])
                frames_analyzed += 1
        cap.release()
        os.unlink(video_path)
        if not nsfw_scores:
            return {"error": "لم يتم تحليل أي إطار"}
        avg_nsfw_score = sum(nsfw_scores) / len(nsfw_scores)
        is_nsfw = avg_nsfw_score >= NSFW_THRESHOLD
        return {"nsfw": is_nsfw, "nsfw_score": avg_nsfw_score, "frames_analyzed": frames_analyzed, "total_frames": total_frames, "frame_scores": nsfw_scores}
    except Exception as e:
        logger.error(f"Video NSFW check error: {e}")
        return {"error": str(e)}

try:
    import cv2
    CV2_AVAILABLE = True
except:
    CV2_AVAILABLE = False

async def safe_send_markdown(bot, chat_id: int, text: str, reply_markup=None, **kwargs):
    if not text:
        return None
    clean_text = sanitize_text(text)
    try:
        escaped = escape_markdown_v2(clean_text)
        if len(escaped) > 4096:
            escaped = escaped[:4093] + "..."
        return await bot.send_message(chat_id=chat_id, text=escaped, parse_mode="MarkdownV2", reply_markup=reply_markup, **kwargs)
    except BadRequest as e:
        if "can't parse entities" in str(e).lower():
            try:
                html_text = clean_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                if len(html_text) > 4096:
                    html_text = html_text[:4093] + "..."
                return await bot.send_message(chat_id=chat_id, text=html_text, parse_mode="HTML", reply_markup=reply_markup, **kwargs)
            except:
                plain = re.sub(r"[*_`\[\]()~>#+\-=|{}.!\\]", "", clean_text)
                if len(plain) > 4096:
                    plain = plain[:4093] + "..."
                return await bot.send_message(chat_id=chat_id, text=plain, reply_markup=reply_markup, **kwargs)
        raise

async def safe_edit_markdown(query, text: str, reply_markup=None, **kwargs):
    if not query or not query.message:
        return None
    if not text:
        return None
    clean_text = sanitize_text(text)
    try:
        escaped = escape_markdown_v2(clean_text)
        if len(escaped) > 4096:
            escaped = escaped[:4093] + "..."
        return await query.edit_message_text(text=escaped, parse_mode="MarkdownV2", reply_markup=reply_markup, **kwargs)
    except BadRequest as e:
        error_msg = str(e).lower()
        if "can't parse entities" in error_msg:
            try:
                html_text = clean_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                if len(html_text) > 4096:
                    html_text = html_text[:4093] + "..."
                return await query.edit_message_text(text=html_text, parse_mode="HTML", reply_markup=reply_markup, **kwargs)
            except:
                plain = re.sub(r"[*_`\[\]()~>#+\-=|{}.!\\]", "", clean_text)
                if len(plain) > 4096:
                    plain = plain[:4093] + "..."
                return await query.edit_message_text(text=plain, reply_markup=reply_markup, **kwargs)
        elif "message is not modified" in error_msg:
            try:
                await query.answer("✅ تم التحديث")
            except:
                pass
            return None
        raise

async def create_backup():
    try:
        encrypted_path = encrypt_db_backup()
        temp_backup = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_backup.close()
        shutil.copy2(DB_PATH, temp_backup.name)
        with open(temp_backup.name, "rb") as f:
            backup_data = f.read()
        compressed = compress_backup(backup_data)
        encrypted = BACKUP_CIPHER.encrypt(compressed)
        backup_file = BACKUP_DIR / f"backup_{mecca_now().strftime('%Y%m%d_%H%M%S')}.enc"
        with open(backup_file, "wb") as f:
            f.write(encrypted)
        os.unlink(temp_backup.name)
        backups = sorted(BACKUP_DIR.glob("backup_*.enc"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old_backup in backups[MAX_BACKUPS:]:
            old_backup.unlink()
        logger.info(f"✅ Backup created: {backup_file}")
        return backup_file
    except Exception as e:
        logger.error(f"❌ Backup failed: {e}")
        raise

async def list_backups():
    backups = sorted(BACKUP_DIR.glob("backup_*.enc"), key=lambda x: x.stat().st_mtime, reverse=True)
    incremental = sorted(BACKUP_DIR.glob("incremental_*.inc"), key=lambda x: x.stat().st_mtime, reverse=True)
    return backups + incremental

async def restore_backup(backup_path: Path):
    if not backup_path.exists():
        raise FileNotFoundError(f"File {backup_path} not found")
    with open(backup_path, "rb") as f:
        encrypted = f.read()
    try:
        decrypted = BACKUP_CIPHER.decrypt(encrypted)
    except Exception as e:
        raise ValueError(f"Decryption failed: {e}")
    try:
        decompressed = decompress_backup(decrypted)
    except Exception as e:
        raise ValueError(f"Decompression failed: {e}")
    temp_restore = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    temp_restore.write(decompressed)
    temp_restore.close()
    current_backup = BACKUP_DIR / f"pre_restore_{mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(DB_PATH, current_backup)
    shutil.copy2(temp_restore.name, DB_PATH)
    os.unlink(temp_restore.name)
    await db_pool.initialize()
    logger.info(f"✅ Restored backup: {backup_path}")

async def auto_backup():
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
                        pass
                async def _update_backup_time(conn):
                    await conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('last_backup', ?)", (utc_now_iso(),))
                    await conn.commit()
                await execute_db(_update_backup_time)
            consecutive_errors = 0
            backoff = AUTO_BACKUP_SLEEP
        except Exception as e:
            logger.error(f"Auto backup error: {e}")
            backoff = min(backoff * 1.5, max_backoff)
            await asyncio.sleep(backoff)

async def translate_text(text: str, target_lang: str, source_lang: str = "auto") -> str:
    try:
        if not text or len(text.strip()) == 0:
            return text
        if target_lang not in SUPPORTED_LANGUAGES and target_lang != "auto":
            return text
        cache_key = hashlib.md5(f"{text}_{target_lang}".encode()).hexdigest()
        if cache_key in _translation_cache:
            return _translation_cache[cache_key]
        import aiohttp
        async with aiohttp.ClientSession() as session:
            url = "https://translate.googleapis.com/translate_a/single"
            params = {"client": "gtx", "sl": source_lang, "tl": target_lang, "dt": "t", "q": text}
            async with session.get(url, params=params, timeout=10) as resp:
                data = await resp.json()
                translated = data[0][0][0] if data and data[0] and data[0][0] else text
                _translation_cache[cache_key] = translated
                return translated
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text

async def get_user_translation_language(user_id: int) -> str:
    async def _get(conn):
        cur = await conn.execute("SELECT lang FROM user_translation WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else "off"
    lang = await execute_db(_get)
    user_translation_settings_cache[user_id] = lang
    return lang

async def set_user_translation_language(user_id: int, lang: str):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO user_translation (user_id, lang) VALUES (?, ?)", (user_id, lang))
        await conn.commit()
    await execute_db(_set)
    user_translation_settings_cache[user_id] = lang

