#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
نظام الأمان المتقدم - يشمل NSFW، الكلمات المحظورة، الفلترة، والعقوبات
"""

import io
import hashlib
import base64
import tempfile
import os
import asyncio
import time as time_module
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict
from datetime import datetime, timedelta
from PIL import Image

from constants import (
    SIGHTENGINE_API_USER, SIGHTENGINE_API_SECRET,
    NSFW_ENABLED, NSFW_THRESHOLD, NSFW_MAX_FILE_SIZE,
    NSFW_MAX_VIDEO_SIZE, NSFW_FRAMES,
    CV2_AVAILABLE, ZSTD_AVAILABLE, PRIMARY_OWNER_ID,
    BANNED_WORDS_FILE, NSFW_CACHE, NSFW_CACHE_TTL,
    _NSFW_CACHE_LOCK
)
from utils import (
    sanitize_text, safe_int, utc_now_iso, mecca_now,
    log_error, advanced_logger, utc_now
)

# ===================== استيراد cv2 و numpy بشكل آمن =====================
if CV2_AVAILABLE:
    import cv2
    import numpy as np

# ===================== نظام كشف NSFW المحسن =====================
async def check_nsfw_cached(image_bytes: bytes, cache_key: str = None) -> dict:
    """كشف NSFW مع تخزين مؤقت"""
    if cache_key is None:
        cache_key = hashlib.md5(image_bytes).hexdigest()

    async with _NSFW_CACHE_LOCK:
        if cache_key in NSFW_CACHE:
            cached_data, cached_time = NSFW_CACHE[cache_key]
            if time_module.time() - cached_time < NSFW_CACHE_TTL:
                return cached_data

    result = await check_nsfw_image(image_bytes)

    async with _NSFW_CACHE_LOCK:
        NSFW_CACHE[cache_key] = (result, time_module.time())
        if len(NSFW_CACHE) > 100:
            expired_keys = [k for k, (_, t) in NSFW_CACHE.items() if time_module.time() - t > NSFW_CACHE_TTL]
            for k in expired_keys:
                del NSFW_CACHE[k]

    return result

async def check_nsfw_image(image_bytes: bytes) -> dict:
    """كشف NSFW للصور باستخدام SightEngine API"""
    try:
        if not SIGHTENGINE_API_USER or not SIGHTENGINE_API_SECRET:
            return {"nsfw": False, "score": 0, "error": "API غير مفعل"}

        # ضغط الصورة لتقليل الحجم
        img = Image.open(io.BytesIO(image_bytes))
        img.thumbnail((800, 800))
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=80)
        compressed = buffer.getvalue()

        image_b64 = base64.b64encode(compressed).decode('utf-8')

        import aiohttp
        async with aiohttp.ClientSession() as session:
            url = "https://api.sightengine.com/1.0/check.json"
            params = {
                "models": "nudity-2.0,wad",
                "api_user": SIGHTENGINE_API_USER,
                "api_secret": SIGHTENGINE_API_SECRET,
                "image": image_b64
            }

            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return {"nsfw": False, "score": 0, "error": f"فشل الاتصال ({resp.status})"}

                data = await resp.json()

                nsfw_score = data.get("nudity", {}).get("safe", 1)
                nsfw_score = 1 - nsfw_score

                wad = max(
                    data.get("weapon", 0) or 0,
                    data.get("drugs", 0) or 0,
                    data.get("alcohol", 0) or 0
                )

                faces = data.get("faces", 0) or 0

                return {
                    "nsfw": nsfw_score > NSFW_THRESHOLD or wad > NSFW_THRESHOLD,
                    "nsfw_score": round(nsfw_score, 2),
                    "wad_score": round(wad, 2),
                    "faces": faces,
                    "safe_score": round(1 - nsfw_score, 2),
                    "raw": data
                }

    except Exception as e:
        advanced_logger.log_error("خطأ في كشف NSFW للصورة", e)
        return {"nsfw": False, "score": 0, "error": str(e)}

async def check_nsfw_video(video_bytes: bytes, frames: int = NSFW_FRAMES) -> dict:
    """كشف NSFW للفيديوهات باستخدام cv2"""
    if not CV2_AVAILABLE:
        return {"nsfw": False, "score": 0, "error": "cv2 غير مثبت"}

    try:
        if not video_bytes:
            return {"nsfw": False, "score": 0, "error": "فيديو فارغ"}

        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name

        cap = cv2.VideoCapture(tmp_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if total_frames == 0:
            cap.release()
            os.unlink(tmp_path)
            return {"nsfw": False, "score": 0, "error": "لا يمكن قراءة الفيديو"}

        frame_indices = np.linspace(0, total_frames - 1, min(frames, total_frames), dtype=int)
        nsfw_scores = []
        wad_scores = []
        faces_count = 0

        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue

            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            img_bytes = buffer.tobytes()

            result = await check_nsfw_image(img_bytes)
            if not result.get("error"):
                nsfw_scores.append(result.get("nsfw_score", 0))
                wad_scores.append(result.get("wad_score", 0))
                faces_count += result.get("faces", 0)

            await asyncio.sleep(0.1)

        cap.release()
        os.unlink(tmp_path)

        if not nsfw_scores:
            return {"nsfw": False, "score": 0, "error": "لا يمكن تحليل الإطارات"}

        avg_nsfw = sum(nsfw_scores) / len(nsfw_scores)
        avg_wad = sum(wad_scores) / len(wad_scores)

        return {
            "nsfw": avg_nsfw > NSFW_THRESHOLD or avg_wad > NSFW_THRESHOLD,
            "nsfw_score": round(avg_nsfw, 2),
            "wad_score": round(avg_wad, 2),
            "faces": faces_count // len(frame_indices) if frame_indices else 0,
            "frames_analyzed": len(nsfw_scores),
            "max_nsfw_score": round(max(nsfw_scores), 2) if nsfw_scores else 0,
            "max_wad_score": round(max(wad_scores), 2) if wad_scores else 0
        }

    except Exception as e:
        advanced_logger.log_error("خطأ في كشف NSFW للفيديو", e)
        return {"nsfw": False, "score": 0, "error": str(e)}

# ===================== نظام الكلمات المحظورة من ملف =====================
BANNED_PATTERNS = []

def load_banned_words_from_file(file_path: Path) -> List[str]:
    """تحميل الكلمات المحظورة من ملف"""
    words = []
    if not file_path.exists():
        print(f"⚠️ ملف {file_path} غير موجود، سيتم إنشاؤه فارغاً")
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("# قائمة الكلمات المحظورة - كل كلمة في سطر منفصل\n")
                f.write("# ابدأ السطر بـ # للتعليق\n")
                f.write("# استخدم * للتعبيرات النمطية (مثل: سكس.*\n")
                f.write("\n")
                f.write("بورن\n")
                f.write("سكس\n")
                f.write("جنس\n")
                f.write("عري\n")
                f.write("خمر\n")
                f.write("خمور\n")
                f.write("مخدرات\n")
                f.write("حشيش\n")
                f.write("كحول\n")
                f.write("دعارة\n")
            print(f"✅ تم إنشاء ملف {file_path} مع كلمات افتراضية")
        except Exception as e:
            print(f"❌ فشل إنشاء ملف الكلمات المحظورة: {e}")
        return words

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith('#'):
                    continue
                word = line.lower()
                if len(word) >= 2:
                    words.append(word)
                    if '*' in word or '?' in word or '+' in word:
                        try:
                            BANNED_PATTERNS.append(re.compile(word))
                        except:
                            pass
        print(f"✅ تم تحميل {len(words)} كلمة محظورة من {file_path}")
        print(f"✅ تم تحميل {len(BANNED_PATTERNS)} نمط محظور")
    except Exception as e:
        print(f"❌ فشل تحميل الكلمات المحظورة: {e}")

    return words

def import_banned_words_from_file(conn, words: List[str], added_by: int = 1) -> int:
    """استيراد الكلمات المحظورة إلى قاعدة البيانات"""
    if not words:
        return 0
    imported = 0
    try:
        for word in words:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO banned_words (word, chat_id, added_by, added_at) VALUES (?, ?, ?, ?)",
                    (word, -1, added_by, utc_now_iso())
                )
                imported += 1
            except:
                continue
        conn.commit()
        print(f"✅ تم استيراد {imported} كلمة محظورة إلى قاعدة البيانات")
    except Exception as e:
        print(f"❌ فشل استيراد الكلمات المحظورة: {e}")
    return imported

async def add_banned_pattern(pattern: str) -> bool:
    """إضافة نمط Regex للكلمات المحظورة"""
    try:
        compiled = re.compile(pattern.lower())
        BANNED_PATTERNS.append(compiled)
        return True
    except:
        return False

async def check_banned_patterns(text: str) -> bool:
    """التحقق من وجود أنماط محظورة في النص"""
    text_lower = text.lower()
    for pattern in BANNED_PATTERNS:
        if pattern.search(text_lower):
            return True
    return False

# ===================== دوال العقوبات =====================
async def apply_penalty(bot, chat_id, user_id, settings):
    """تطبيق العقوبة التلقائية حسب الإعدادات"""
    penalty = settings.get('auto_penalty', 'none')
    if penalty == 'none':
        return
    if penalty == 'kick':
        await execute_kick(bot, chat_id, user_id, "مخالفة قواعد المجموعة")
    elif penalty == 'ban':
        await execute_ban(bot, chat_id, user_id, reason="مخالفة قواعد المجموعة")
    elif penalty == 'mute':
        duration = settings.get('auto_mute_duration', 60)
        await execute_mute(bot, chat_id, user_id, duration, "مخالفة قواعد المجموعة")

async def execute_ban(bot, chat_id: int, user_id: int, until_date=None, reason: str = "", moderator_id: int = None):
    """تنفيذ حظر مستخدم"""
    try:
        await bot.ban_chat_member(chat_id, user_id, until_date=until_date)
        from database import execute_db
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'ban', 0, ?, ?, ?)",
                              (chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم حظر المستخدم `{user_id}` بنجاح"
    except Exception as e:
        return False, f"❌ فشل الحظر: {str(e)[:100]}"

async def execute_mute(bot, chat_id: int, user_id: int, duration_minutes: int = None, reason: str = "", moderator_id: int = None):
    """تنفيذ كتم مستخدم"""
    try:
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
        from telegram import ChatPermissions
        permissions = ChatPermissions(can_send_messages=False)
        await bot.restrict_chat_member(chat_id, user_id, permissions, until_date=until_date)
        from database import execute_db
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'mute', ?, ?, ?, ?)",
                              (chat_id, user_id, duration_minutes, moderator_id or PRIMARY_OWNER_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم كتم المستخدم `{user_id}`{duration_text}"
    except Exception as e:
        return False, f"❌ فشل الكتم: {str(e)[:100]}"

async def execute_kick(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    """تنفيذ طرد مستخدم"""
    try:
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id)
        from database import execute_db
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'kick', 0, ?, ?, ?)",
                              (chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم طرد المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل الطرد: {str(e)[:100]}"

async def execute_warn(bot, chat_id: int, user_id: int, moderator_id: int, reason: str = "", auto_ban_limit: int = 3):
    """تنفيذ تحذير مستخدم مع حظر تلقائي بعد 3 تحذيرات"""
    from database import execute_db
    async def _add_warning(conn):
        cur = await conn.execute("SELECT warnings FROM user_warnings WHERE user_id=? AND chat_id=?", (user_id, chat_id))
        row = await cur.fetchone()
        warnings = row[0] + 1 if row else 1
        await conn.execute("INSERT OR REPLACE INTO user_warnings (user_id, chat_id, warnings) VALUES (?,?,?)", (user_id, chat_id, warnings))
        await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'warn', ?, ?, ?, ?)",
                          (chat_id, user_id, warnings, moderator_id, reason[:200] if reason else "", utc_now_iso()))
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

async def execute_restrict(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    """تنفيذ تقييد مستخدم (منع الوسائط)"""
    try:
        from telegram import ChatPermissions
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False
        )
        await bot.restrict_chat_member(chat_id, user_id, permissions)
        from database import execute_db
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'restrict', 0, ?, ?, ?)",
                              (chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, reason[:200] if reason else "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم تقييد المستخدم `{user_id}` (لا يمكنه إرسال وسائط)"
    except Exception as e:
        return False, f"❌ فشل التقييد: {str(e)[:100]}"

async def execute_pin(bot, chat_id: int, message_id: int, disable_notification: bool = False):
    """تنفيذ تثبيت رسالة"""
    try:
        await bot.pin_chat_message(chat_id, message_id, disable_notification=disable_notification)
        return True, "✅ تم تثبيت الرسالة"
    except Exception as e:
        return False, f"❌ فشل التثبيت: {str(e)[:100]}"

async def execute_unban(bot, chat_id: int, user_id: int, moderator_id: int = None):
    """تنفيذ إلغاء حظر مستخدم"""
    try:
        await bot.unban_chat_member(chat_id, user_id)
        from database import execute_db
        async def _log(conn):
            await conn.execute("INSERT INTO moderation_log (chat_id, user_id, action, duration_minutes, moderator_id, reason, created_at) VALUES (?, ?, 'unban', 0, ?, ?, ?)",
                              (chat_id, user_id, moderator_id or PRIMARY_OWNER_ID, "", utc_now_iso()))
            await conn.commit()
        await execute_db(_log)
        return True, f"✅ تم إلغاء حظر المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل إلغاء الحظر: {str(e)[:100]}"

# ===================== دوال سجل الإجراءات =====================
async def get_moderation_log(chat_id: int, limit: int = 20) -> str:
    """جلب سجل الإجراءات للمجموعة"""
    from database import execute_db
    from utils import utc_to_mecca
    async def _get_log(conn):
        cur = await conn.execute("""
            SELECT user_id, action, duration_minutes, reason, created_at
            FROM moderation_log
            WHERE chat_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (chat_id, limit))
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
        if action == 'mute' and duration:
            if duration == -1:
                duration_text = " (دائم)"
            elif duration < 60:
                duration_text = f" ({duration} دقيقة)"
            elif duration < 1440:
                duration_text = f" ({duration//60} ساعة)"
            else:
                duration_text = f" ({duration//1440} يوم)"
        elif action == 'warn' and duration:
            duration_text = f" (تحذير #{duration})"
        reason_text = f"\n   📝 السبب: {reason[:50]}" if reason else ""
        text += f"• `{user_id}` → {action}{duration_text}{reason_text}\n   🕐 {time_str}\n\n"
    return text

# ===================== دوال التحقق من صلاحيات البوت =====================
async def check_bot_admin_permissions(bot, chat_id: int) -> dict:
    """التحقق من صلاحيات البوت في المجموعة"""
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        if me.status not in ['administrator', 'creator']:
            return {'can_act': False, 'reason': 'البوت ليس مشرفاً'}
        permissions = {
            'can_ban': getattr(me, 'can_restrict_members', False),
            'can_pin': getattr(me, 'can_pin_messages', False),
            'can_delete': getattr(me, 'can_delete_messages', False),
        }
        missing = [k for k, v in permissions.items() if not v]
        if missing:
            return {'can_act': False, 'reason': f'البوت يحتاج صلاحيات: {", ".join(missing)}'}
        return {'can_act': True, 'reason': ''}
    except Exception as e:
        return {'can_act': False, 'reason': str(e)[:100]}

# ===================== دوال كشف الروابط والإشارات =====================
def contains_link(text: str) -> bool:
    """التحقق من وجود رابط في النص"""
    return bool(re.search(r'(https?://|www\.|@\w+\.)', text))

def contains_mention(text: str) -> bool:
    """التحقق من وجود إشارة @ في النص"""
    return bool(re.search(r'@\w+', text))

# ===================== دالة حذف الرسائل بعد تأخير =====================
async def delete_message_after_delay(bot, chat_id: int, message_id: int, delay_seconds: int):
    """حذف رسالة بعد فترة زمنية محددة"""
    await asyncio.sleep(delay_seconds)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        pass

# ===================== دوال الأمان الإضافية =====================
class SecurityAudit:
    """نظام التدقيق الأمني"""
    async def log(self, event_type: str, user_id: int, details: dict, severity: str = "INFO"):
        log_entry = {
            "event": event_type,
            "user_id": user_id,
            "details": details,
            "severity": severity,
            "timestamp": utc_now_iso()
        }
        advanced_logger.log_security(event_type, user_id, details, severity)
        try:
            from database import db_get_log_channel_id
            log_channel = await db_get_log_channel_id()
            if log_channel:
                try:
                    from telegram import Bot
                    from constants import TOKEN
                    bot = Bot(token=TOKEN)
                    await bot.send_message(
                        chat_id=log_channel,
                        text=f"🔐 **تقرير أمني**\n\n📌 الحدث: {event_type}\n👤 المستخدم: `{user_id}`\n📊 التفاصيل: {json.dumps(details, default=str)[:200]}\n⚠️ الخطورة: {severity}\n🕐 الوقت: {mecca_now().strftime('%Y-%m-%d %H:%M:%S')}",
                        parse_mode="MarkdownV2"
                    )
                except:
                    pass
        except:
            pass
        return True

security_audit = SecurityAudit()

# ===================== دوال كشف النشاط المشبوه =====================
class AnomalyDetector:
    def __init__(self):
        self.user_activity = defaultdict(list)
        self.lock = asyncio.Lock()

    async def detect_anomaly(self, user_id: int, action: str) -> bool:
        async with self.lock:
            now = time_module.time()
            self.user_activity[user_id].append((now, action))
            self.user_activity[user_id] = [
                (t, a) for t, a in self.user_activity[user_id]
                if now - t < 60
            ]
            if len(self.user_activity[user_id]) > 10:
                await security_audit.log(
                    "SUSPICIOUS_ACTIVITY",
                    user_id,
                    {"actions": self.user_activity[user_id], "count": len(self.user_activity[user_id])},
                    "CRITICAL"
                )
                return True
            return False

anomaly_detector = AnomalyDetector()

# ===================== دوال NSFW الإضافية =====================
def is_nsfw_enabled() -> bool:
    """التحقق من تفعيل NSFW"""
    return NSFW_ENABLED

def get_nsfw_threshold() -> float:
    """الحصول على نسبة الحساسية الحالية"""
    return NSFW_THRESHOLD

async def set_nsfw_threshold(value: float):
    """تغيير نسبة الحساسية"""
    global NSFW_THRESHOLD
    if 0 < value <= 1:
        NSFW_THRESHOLD = value
        os.environ["NSFW_THRESHOLD"] = str(value)
        return True
    return False

# ===================== دوال استيراد الكلمات المحظورة عند التشغيل =====================
async def import_banned_words_on_startup():
    """استيراد الكلمات المحظورة من ملف عند بدء التشغيل"""
    try:
        from database import execute_db
        words = load_banned_words_from_file(BANNED_WORDS_FILE)
        if words:
            async def _import(conn):
                imported = 0
                for word in words:
                    try:
                        await conn.execute(
                            "INSERT OR IGNORE INTO banned_words (word, chat_id, added_by, added_at) VALUES (?, ?, ?, ?)",
                            (word, -1, PRIMARY_OWNER_ID, utc_now_iso())
                        )
                        imported += 1
                    except:
                        continue
                await conn.commit()
                return imported
            imported_count = await execute_db(_import)
            print(f"✅ تم استيراد {imported_count} كلمة محظورة من {BANNED_WORDS_FILE}")
        else:
            print(f"📭 لا توجد كلمات محظورة في {BANNED_WORDS_FILE} للاستيراد")
    except Exception as e:
        print(f"❌ فشل استيراد الكلمات المحظورة: {e}")
def check_database_health():
    """التحقق من صحة قاعدة البيانات (مؤقت)"""
    return True

def check_telegram_health():
    """التحقق من صحة اتصال تيليجرام (مؤقت)"""
    return True
