#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام الأمان المتقدم – نسخة نهائية متوافقة
"""

import io, hashlib, base64, tempfile, os, asyncio, time as time_module, re, json, logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
from datetime import datetime, timedelta
from enum import Enum
from PIL import Image, ImageOps

try:
    import cv2, numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

from constants import (
    SIGHTENGINE_API_USER, SIGHTENGINE_API_SECRET, NSFW_ENABLED, NSFW_THRESHOLD,
    NSFW_MAX_FILE_SIZE, NSFW_MAX_VIDEO_SIZE, NSFW_FRAMES, PRIMARY_OWNER_ID, TOKEN
)
from utils import sanitize_text, safe_int, utc_now_iso, mecca_now, log_error, advanced_logger, logger, utc_now

logger = logging.getLogger(__name__)

BANNED_WORDS_FILE = Path(os.getenv("BANNED_WORDS_FILE", "data/banned_words.txt"))
BANNED_WORDS_FILE.parent.mkdir(parents=True, exist_ok=True)

NSFW_CACHE_TTL = int(os.getenv("NSFW_CACHE_TTL", 3600))
NSFW_CACHE_MAX_SIZE = int(os.getenv("NSFW_CACHE_MAX_SIZE", 500))
NSFW_CACHE: Dict[str, Tuple[dict, float]] = {}
NSFW_CACHE_LOCK = asyncio.Lock()

BANNED_PATTERNS: List[re.Pattern] = []
BANNED_PATTERNS_LOCK = asyncio.Lock()

class ViolationLevel(Enum):
    NONE=0; LOW=1; MEDIUM=2; HIGH=3; CRITICAL=4

class RateLimiter:
    def __init__(self, max_calls=10, period=60.0):
        self.max_calls = max_calls; self.period = period
        self.calls: List[float] = []; self.lock = asyncio.Lock()
    async def acquire(self) -> bool:
        async with self.lock:
            while True:
                now = time_module.time()
                self.calls = [t for t in self.calls if now - t < self.period]
                if len(self.calls) < self.max_calls:
                    self.calls.append(now); return True
                wait = self.calls[0] + self.period - now
                if wait <= 0: continue
                self.lock.release()
                try: await asyncio.sleep(wait)
                finally: await self.lock.acquire()
    def get_remaining(self) -> int:
        now = time_module.time()
        self.calls = [t for t in self.calls if now - t < self.period]
        return max(0, self.max_calls - len(self.calls))

NSFW_RATE_LIMITER = RateLimiter(max_calls=30, period=60.0)

def get_cache_key(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()

async def cleanup_nsfw_cache():
    async with NSFW_CACHE_LOCK:
        now = time_module.time()
        expired = [k for k, (_, ts) in NSFW_CACHE.items() if now - ts > NSFW_CACHE_TTL]
        for k in expired: del NSFW_CACHE[k]
        if len(NSFW_CACHE) > NSFW_CACHE_MAX_SIZE:
            sorted_keys = sorted(NSFW_CACHE.keys(), key=lambda k: NSFW_CACHE[k][1])
            for k in sorted_keys[:len(NSFW_CACHE)-NSFW_CACHE_MAX_SIZE]: del NSFW_CACHE[k]

async def nsfw_cache_cleanup_task():
    while True:
        await asyncio.sleep(300)
        try: await cleanup_nsfw_cache()
        except asyncio.CancelledError: break
        except: pass

async def check_nsfw_cached(image_bytes: bytes, cache_key: Optional[str] = None) -> dict:
    if cache_key is None: cache_key = get_cache_key(image_bytes)
    async with NSFW_CACHE_LOCK:
        if cache_key in NSFW_CACHE:
            cached_result, cached_time = NSFW_CACHE[cache_key]
            if time_module.time() - cached_time < NSFW_CACHE_TTL:
                return cached_result
    result = await check_nsfw_image(image_bytes)
    async with NSFW_CACHE_LOCK:
        NSFW_CACHE[cache_key] = (result, time_module.time())
        if len(NSFW_CACHE) > NSFW_CACHE_MAX_SIZE * 1.2:
            await cleanup_nsfw_cache()
    return result

_nsfw_session: Optional[aiohttp.ClientSession] = None
_nsfw_session_lock = asyncio.Lock()

async def get_nsfw_session() -> aiohttp.ClientSession:
    global _nsfw_session
    if _nsfw_session is None or _nsfw_session.closed:
        async with _nsfw_session_lock:
            if _nsfw_session is None or _nsfw_session.closed:
                _nsfw_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    return _nsfw_session

async def close_nsfw_session():
    global _nsfw_session
    if _nsfw_session and not _nsfw_session.closed:
        await _nsfw_session.close(); _nsfw_session = None

async def check_nsfw_image(image_bytes: bytes) -> dict:
    if not AIOHTTP_AVAILABLE: return {"nsfw":False,"score":0,"error":"aiohttp غير مثبت"}
    if not SIGHTENGINE_API_USER or not SIGHTENGINE_API_SECRET: return {"nsfw":False,"score":0,"error":"API غير مفعل"}
    await NSFW_RATE_LIMITER.acquire()
    img = buffer = None
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)
        if img.mode in ('RGBA','P','LA'): img = img.convert('RGB')
        img.thumbnail((800,800), Image.Resampling.LANCZOS)
        buffer = io.BytesIO(); img.save(buffer, format='JPEG', quality=80, optimize=True)
        compressed = buffer.getvalue()
        image_b64 = base64.b64encode(compressed).decode('utf-8')
        url = "https://api.sightengine.com/1.0/check.json"
        request_data = {
            "media": image_b64,
            "models": "nudity-2.0,wad,face-attributes",
            "api_user": SIGHTENGINE_API_USER,
            "api_secret": SIGHTENGINE_API_SECRET
        }
        session = await get_nsfw_session()
        async with session.post(url, data=request_data) as resp:
            if resp.status == 429: return {"nsfw":False,"score":0,"error":"تجاوز حد API"}
            if resp.status != 200: return {"nsfw":False,"score":0,"error":f"فشل الاتصال ({resp.status})"}
            data = await resp.json()
        nudity_data = data.get("nudity",{})
        safe_score = nudity_data.get("safe",1.0)
        raw = nudity_data.get("raw",{})
        sexual_activity = float(raw.get("sexual_activity",0) or 0)
        sexual_display = float(raw.get("sexual_display",0) or 0)
        erotica = float(raw.get("erotica",0) or 0)
        suggestive = float(raw.get("suggestive",0) or 0)
        nsfw_score = max(sexual_activity, sexual_display, erotica, suggestive)
        weapon_score = float(data.get("weapon",0) or 0)
        alcohol_score = float(data.get("alcohol",0) or 0)
        drugs_score = float(data.get("drugs",0) or 0)
        wad_score = max(weapon_score, alcohol_score, drugs_score)
        faces_data = data.get("faces",[])
        faces_count = len(faces_data) if isinstance(faces_data,list) else int(faces_data or 0)
        is_nsfw = nsfw_score > NSFW_THRESHOLD or wad_score > NSFW_THRESHOLD
        result = {
            "nsfw": is_nsfw,
            "nsfw_score": round(nsfw_score,4),
            "safe_score": round(safe_score,4),
            "wad_score": round(wad_score,4),
            "faces": faces_count,
            "details": {
                "sexual_activity": round(sexual_activity,4),
                "sexual_display": round(sexual_display,4),
                "erotica": round(erotica,4),
                "suggestive": round(suggestive,4),
                "weapon": round(weapon_score,4),
                "alcohol": round(alcohol_score,4),
                "drugs": round(drugs_score,4)
            }
        }
        if is_nsfw: logger.warning(f"⚠️ NSFW detected: score={nsfw_score:.2f}")
        return result
    except Exception as e:
        logger.error(f"❌ NSFW error: {e}")
        return {"nsfw":False,"score":0,"error":str(e)[:100]}
    finally:
        if img: img.close()
        if buffer: buffer.close()

async def check_nsfw_video(video_bytes: bytes, frames: int = None) -> dict:
    if not CV2_AVAILABLE: return {"nsfw":False,"score":0,"error":"cv2 غير مثبت"}
    if frames is None: frames = NSFW_FRAMES
    tmp_path = None; cap = None
    try:
        if not video_bytes or len(video_bytes) == 0: return {"nsfw":False,"score":0,"error":"فيديو فارغ"}
        if len(video_bytes) > NSFW_MAX_VIDEO_SIZE: return {"nsfw":False,"score":0,"error":"الفيديو كبير جداً"}
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(video_bytes); tmp_path = tmp.name
        cap = cv2.VideoCapture(tmp_path)
        if not cap.isOpened(): return {"nsfw":False,"score":0,"error":"لا يمكن فتح الفيديو"}
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames == 0: return {"nsfw":False,"score":0,"error":"لا يمكن قراءة الفيديو"}
        frames_to_analyze = min(frames, total_frames)
        frame_indices = np.linspace(0, total_frames-1, frames_to_analyze, dtype=int)
        nsfw_scores = []; wad_scores = []; faces_counts = []
        max_nsfw = 0.0; max_wad = 0.0
        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
            ret, frame = cap.read()
            if not ret: continue
            success, encoded_frame = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not success: continue
            img_bytes = encoded_frame.tobytes()
            result = await check_nsfw_image(img_bytes)
            if not result.get("error"):
                nsfw_scores.append(result.get("nsfw_score",0))
                wad_scores.append(result.get("wad_score",0))
                faces_counts.append(result.get("faces",0))
                max_nsfw = max(max_nsfw, result.get("nsfw_score",0))
                max_wad = max(max_wad, result.get("wad_score",0))
            await asyncio.sleep(0.05)
        if not nsfw_scores: return {"nsfw":False,"score":0,"error":"لا يمكن تحليل الإطارات"}
        avg_nsfw = sum(nsfw_scores)/len(nsfw_scores)
        avg_wad = sum(wad_scores)/len(wad_scores)
        avg_faces = sum(faces_counts)/len(faces_counts) if faces_counts else 0
        return {
            "nsfw": avg_nsfw > NSFW_THRESHOLD or avg_wad > NSFW_THRESHOLD,
            "nsfw_score": round(avg_nsfw,4), "wad_score": round(avg_wad,4),
            "faces": round(avg_faces,1), "frames_analyzed": len(nsfw_scores),
            "max_nsfw_score": round(max_nsfw,4), "max_wad_score": round(max_wad,4)
        }
    except Exception as e:
        logger.error(f"❌ video NSFW error: {e}")
        return {"nsfw":False,"score":0,"error":str(e)[:100]}
    finally:
        if cap: cap.release()
        if tmp_path and os.path.exists(tmp_path):
            try: os.unlink(tmp_path)
            except: pass

# ========== الكلمات المحظورة ==========
def load_banned_words_from_file(file_path: Path) -> List[str]:
    words = []
    if not file_path.exists():
        file_path.parent.mkdir(parents=True, exist_ok=True)
        default_words = ["# قائمة الكلمات المحظورة","","بورن","سكس","جنس","عري","خمر","خمور","مخدرات","حشيش","كحول","دعارة","قمار","انتحار","ارهاب","تفجير","ممنوعات","مخلة","فاحشة"]
        with open(file_path,'w',encoding='utf-8') as f: f.write('\n'.join(default_words)+'\n')
        for w in default_words:
            w = w.strip().lower()
            if w and not w.startswith('#') and len(w)>=2: words.append(w)
        return words
    with open(file_path,'r',encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'): continue
            word = line.lower()
            if len(word)<2: continue
            words.append(word)
            if any(ch in word for ch in ['*','?','+','[',']','(',')','|','^','$']):
                try: BANNED_PATTERNS.append(re.compile(word))
                except: pass
    return words

async def import_banned_words_to_db(conn, words: List[str], added_by: int = None) -> int:
    if not words: return 0
    if added_by is None: added_by = PRIMARY_OWNER_ID
    imported = 0
    try:
        for word in words:
            try:
                await conn.execute("INSERT OR IGNORE INTO banned_words (word, chat_id, added_by, added_at) VALUES (?,?,?,?)",(word,-1,added_by,utc_now_iso()))
                imported += 1
            except: continue
        await conn.commit()
    except: pass
    return imported

async def check_banned_words(text: str, db_conn=None) -> Tuple[bool, Optional[str]]:
    if not text: return False, None
    async with BANNED_PATTERNS_LOCK:
        for pattern in BANNED_PATTERNS:
            if pattern.search(text.lower()): return True, "نمط محظور"
    if db_conn:
        try:
            cursor = await db_conn.execute("SELECT word FROM banned_words WHERE chat_id = ? OR chat_id = -1",(-1,))
            rows = await cursor.fetchall(); await cursor.close()
            for row in rows:
                if row[0].lower() in text.lower(): return True, row[0]
        except: pass
    return False, None

# ========== العقوبات ==========
async def execute_ban(bot, chat_id: int, user_id: int, *, until_date=None, reason: str = "", moderator_id: Optional[int] = None) -> Tuple[bool, str]:
    try:
        await bot.ban_chat_member(chat_id, user_id, until_date=until_date)
        from database import execute_db
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?,?,'ban',0,?,?,?)",(chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, reason[:200], utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم حظر المستخدم `{user_id}`"
    except Exception as e: return False, str(e)[:100]

async def execute_mute(bot, chat_id: int, user_id: int, duration_minutes: Optional[int] = None, reason: str = "", moderator_id: Optional[int] = None) -> Tuple[bool, str]:
    try:
        from telegram import ChatPermissions
        until_date = (utc_now() + timedelta(minutes=duration_minutes)) if duration_minutes and duration_minutes>0 else None
        await bot.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=False, can_send_media_messages=False, can_send_polls=False, can_send_other_messages=False, can_add_web_page_previews=False, can_change_info=False, can_invite_users=False, can_pin_messages=False), until_date=until_date)
        from database import execute_db
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?,?,'mute',?,?,?,?)",(chat_id, user_id, duration_minutes or -1, moderator_id or PRIMARY_OWNER_ID, reason[:200], utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم كتم المستخدم `{user_id}`"
    except Exception as e: return False, str(e)[:100]

async def execute_kick(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: Optional[int] = None) -> Tuple[bool, str]:
    try:
        await bot.ban_chat_member(chat_id, user_id); await asyncio.sleep(0.5); await bot.unban_chat_member(chat_id, user_id)
        from database import execute_db
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?,?,'kick',0,?,?,?)",(chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, reason[:200], utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم طرد المستخدم `{user_id}`"
    except Exception as e: return False, str(e)[:100]

async def execute_warn(bot, chat_id: int, user_id: int, moderator_id: Optional[int] = None, reason: str = "", auto_ban_limit: int = 3) -> Tuple[bool, str]:
    from database import execute_db
    try:
        async def _add_warning(conn):
            async with conn:
                cursor = await conn.execute("SELECT warnings FROM user_warnings WHERE user_id=? AND chat_id=?",(user_id, chat_id))
                row = await cursor.fetchone(); await cursor.close()
                current = (row[0]+1) if row else 1
                if row: await conn.execute("UPDATE user_warnings SET warnings=?, updated_at=? WHERE user_id=? AND chat_id=?",(current, utc_now_iso(), user_id, chat_id))
                else: await conn.execute("INSERT INTO user_warnings (user_id, chat_id, warnings, created_at, updated_at) VALUES (?,?,?,?,?)",(user_id, chat_id, current, utc_now_iso(), utc_now_iso()))
                await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?,?,'warn',?,?,?,?)",(chat_id, user_id, current, moderator_id or PRIMARY_OWNER_ID, reason[:200], utc_now_iso()))
                should_ban = current >= auto_ban_limit
                if should_ban: await conn.execute("DELETE FROM user_warnings WHERE user_id=? AND chat_id=?",(user_id, chat_id))
                return current, should_ban
        warnings_count, should_ban = await execute_db(_add_warning)
        if should_ban:
            ban_reason = f"حظر تلقائي بعد {warnings_count} تحذيرات"
            success, msg = await execute_ban(bot, chat_id, user_id, reason=ban_reason, moderator_id=moderator_id)
            if success: return True, f"⚠️ تم تحذير المستخدم `{user_id}` ({warnings_count}/{auto_ban_limit}) وتم حظره تلقائياً"
            else:
                async def _restore(conn):
                    await conn.execute("INSERT OR REPLACE INTO user_warnings (user_id, chat_id, warnings, created_at, updated_at) VALUES (?,?,?,?,?)",(user_id, chat_id, warnings_count, utc_now_iso(), utc_now_iso()))
                    await conn.commit()
                await execute_db(_restore)
                return False, f"❌ تم التحذير لكن فشل الحظر التلقائي: {msg}"
        return True, f"⚠️ تم تحذير المستخدم `{user_id}` ({warnings_count}/{auto_ban_limit})"
    except Exception as e: return False, str(e)[:100]

async def execute_restrict(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: Optional[int] = None) -> Tuple[bool, str]:
    try:
        from telegram import ChatPermissions
        await bot.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=True, can_send_media_messages=False, can_send_polls=False, can_send_other_messages=False, can_add_web_page_previews=False, can_change_info=False, can_invite_users=False, can_pin_messages=False))
        from database import execute_db
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?,?,'restrict',0,?,?,?)",(chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, reason[:200], utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم تقييد المستخدم `{user_id}`"
    except Exception as e: return False, str(e)[:100]

async def execute_unban(bot, chat_id: int, user_id: int, moderator_id: Optional[int] = None) -> Tuple[bool, str]:
    try:
        await bot.unban_chat_member(chat_id, user_id)
        from database import execute_db
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?,?,'unban',0,?,?,?)",(chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم إلغاء حظر المستخدم `{user_id}`"
    except Exception as e: return False, str(e)[:100]

async def execute_pin(bot, chat_id: int, message_id: int, disable_notification: bool = False) -> Tuple[bool, str]:
    try:
        await bot.pin_chat_message(chat_id, message_id, disable_notification)
        return True, "✅ تم تثبيت الرسالة"
    except Exception as e: return False, str(e)[:100]

async def apply_penalty(bot, chat_id: int, user_id: int, settings: dict, reason: str = "مخالفة") -> Tuple[bool, str]:
    penalty = settings.get('auto_penalty','none')
    if penalty == 'kick': return await execute_kick(bot, chat_id, user_id, reason=reason)
    if penalty == 'ban': return await execute_ban(bot, chat_id, user_id, reason=reason)
    if penalty == 'mute': return await execute_mute(bot, chat_id, user_id, duration_minutes=settings.get('auto_mute_duration',60), reason=reason)
    if penalty == 'restrict': return await execute_restrict(bot, chat_id, user_id, reason=reason)
    if penalty == 'warn': return await execute_warn(bot, chat_id, user_id, reason=reason, auto_ban_limit=settings.get('auto_ban_limit',3))
    return False, "لا توجد عقوبة"

def contains_link(text: str) -> bool:
    if not text: return False
    patterns = [r'https?://[^\s]+', r'www\.[a-zA-Z0-9][^\s]*\.[a-zA-Z]{2,}[^\s]*', r'[a-zA-Z0-9][^\s]*\.(com|net|org|io|gov|edu|me|info|xyz|online|site|store|web|co|uk|de|fr|ru|ir|sa|ae|eg)/[^\s]*']
    for p in patterns:
        if re.search(p, text, re.IGNORECASE): return True
    return False

def contains_mention(text: str) -> bool:
    return bool(re.search(r'@\w{5,}', text)) if text else False

async def get_moderation_log(chat_id: int, limit: int = 20, action_filter: Optional[str] = None) -> str:
    from database import execute_db
    from utils import utc_to_mecca
    try:
        query = "SELECT user_id, action, duration_minutes, reason, moderator_id, created_at FROM moderation_log WHERE chat_id = ?"
        params = [chat_id]
        if action_filter: query += " AND action = ?"; params.append(action_filter)
        query += " ORDER BY created_at DESC LIMIT ?"; params.append(limit)
        async def _fetch(conn):
            cursor = await conn.execute(query, tuple(params)); rows = await cursor.fetchall(); await cursor.close(); return rows
        logs = await execute_db(_fetch)
        if not logs: return "📭 لا توجد سجلات"
        text = "📜 **سجل الإجراءات**\n"
        for user_id, action, duration, reason, mod_id, created_at in logs:
            text += f"• `{user_id}` → {action}\n"
        return text
    except Exception as e: return f"❌ خطأ: {e}"

async def import_banned_words_on_startup():
    from database import execute_db
    words = load_banned_words_from_file(BANNED_WORDS_FILE)
    if words:
        async def _import(conn): return await import_banned_words_to_db(conn, words, PRIMARY_OWNER_ID)
        await execute_db(_import)
    asyncio.create_task(nsfw_cache_cleanup_task())

def is_nsfw_enabled() -> bool: return NSFW_ENABLED
def get_nsfw_threshold() -> float: return NSFW_THRESHOLD

async def set_nsfw_threshold(value: float) -> bool:
    if not (0.0 < value <= 1.0): return False
    os.environ["NSFW_THRESHOLD"] = str(value)
    import constants; constants.NSFW_THRESHOLD = value
    return True
