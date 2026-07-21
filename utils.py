#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
دوال مساعدة عامة – النسخة النهائية الكاملة
- جميع دوال الوقت، التشفير، الترجمة، الضغط
- جميع دوال لوحات المفاتيح (Keyboards) المطلوبة لـ handlers.py
- compress_backup / decompress_backup لدعم tasks.py
"""

import re
import json
import time as time_module
import secrets
import hashlib
import html
import os
import sys
import gc
import asyncio
import socket
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Tuple, Any
import urllib.parse
from collections import defaultdict, OrderedDict

try:
    import bleach
except ImportError:
    bleach = None

from cryptography.fernet import Fernet

from constants import (
    ENCRYPTION_KEY, BACKUP_ENCRYPTION_KEY, DB_ENCRYPTION,
    DATA_PATH, TEMP_PATH, LOG_PATH, DB_PATH,
    SUPPORTED_LANGUAGES, PRIMARY_OWNER_ID,
    user_points_last_hour, user_language,
    get_nsfw_lock, CallbackData
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

def get_env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() in ['true', '1', 'yes', 'on']

def get_env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default

def escape_markdown_v2(text: str) -> str:
    if not text:
        return ""
    special_chars = r'_*[]()~`>#+\-=|{}.!'
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def clean_text_for_telegram(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\u200b\u200c\u200d\u2060\uFEFF\u202a\u202b\u202c\u202d\u202e]', '', text)
    text = text.replace('\ufeff', '').replace('\ufffc', '')
    return text

def sanitize_text(text: str, max_length: int = 4096, allow_tags: list = None) -> str:
    if not text:
        return ""
    if bleach is not None:
        try:
            if allow_tags is None:
                allow_tags = ['b', 'i', 'u', 's', 'a', 'code', 'pre', 'strong', 'em']
            cleaned = bleach.clean(text, tags=allow_tags, attributes={'a': ['href', 'title']}, styles=[], strip=True)
            text = cleaned
        except Exception as e:
            logger.warning(f"فشل تنظيف النص باستخدام bleach: {e}")
    else:
        text = re.sub(r'<[^>]*>', '', text)
    if len(text) > max_length:
        text = text[:max_length]
    return text

def encode_callback_data(data: str) -> str:
    return urllib.parse.quote(data, safe='')

def decode_callback_data(data: str) -> str:
    return urllib.parse.unquote(data)

def safe_int(value, default=0):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def mecca_now():
    return utc_now() + timedelta(hours=3)

def utc_now_iso():
    return utc_now().isoformat()

def mecca_now_iso():
    return mecca_now().isoformat()

def to_naive(dt):
    if dt is None:
        return None
    if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt

def mecca_to_utc(mecca_dt):
    if mecca_dt is None:
        return None
    if hasattr(mecca_dt, 'tzinfo') and mecca_dt.tzinfo is not None:
        mecca_dt = mecca_dt.replace(tzinfo=None)
    return mecca_dt - timedelta(hours=3)

def utc_to_mecca(utc_dt):
    if utc_dt is None:
        return None
    if hasattr(utc_dt, 'tzinfo') and utc_dt.tzinfo is not None:
        utc_dt = utc_dt.replace(tzinfo=None)
    return utc_dt + timedelta(hours=3)

def encrypt_file(path: Path, cipher: Fernet) -> Path:
    with open(path, 'rb') as f:
        data = f.read()
    encrypted = cipher.encrypt(data)
    encrypted_path = path.with_suffix('.enc')
    with open(encrypted_path, 'wb') as f:
        f.write(encrypted)
    return encrypted_path

def decrypt_file(path: Path, cipher: Fernet) -> Path:
    with open(path, 'rb') as f:
        encrypted = f.read()
    decrypted = cipher.decrypt(encrypted)
    decrypted_path = path.with_suffix('.dec')
    with open(decrypted_path, 'wb') as f:
        f.write(decrypted)
    return decrypted_path

def encrypt_db_backup():
    if not DB_ENCRYPTION:
        logger.info("تشفير قاعدة البيانات معطّل. استخدام النسخة الأصلية.")
        return DB_PATH
    cipher = Fernet(ENCRYPTION_KEY)
    return encrypt_file(DB_PATH, cipher)

# ========== دوال الضغط للنسخ الاحتياطي ==========
try:
    import zstandard
    ZSTD_AVAILABLE = True
    ZSTD_COMPRESSOR = zstandard.ZstdCompressor(level=3)
    ZSTD_DECOMPRESSOR = zstandard.ZstdDecompressor()
except ImportError:
    ZSTD_AVAILABLE = False
    ZSTD_COMPRESSOR = None
    ZSTD_DECOMPRESSOR = None

def compress_backup(data: bytes) -> bytes:
    if ZSTD_AVAILABLE and ZSTD_COMPRESSOR:
        try:
            return ZSTD_COMPRESSOR.compress(data)
        except Exception as e:
            logger.warning(f"فشل ضغط النسخ الاحتياطي: {e}")
    return data

def decompress_backup(data: bytes) -> bytes:
    if ZSTD_AVAILABLE and ZSTD_DECOMPRESSOR:
        try:
            return ZSTD_DECOMPRESSOR.decompress(data)
        except Exception as e:
            logger.warning(f"فشل فك ضغط النسخ الاحتياطي: {e}")
    return data

# ========== التخزين المؤقت ==========
try:
    from cachetools import TTLCache
    CACHETOOLS_AVAILABLE = True
    _admin_cache = TTLCache(maxsize=1000, ttl=300)
    _security_cache = TTLCache(maxsize=500, ttl=60)
    _auth_cache = TTLCache(maxsize=1000, ttl=300)
except ImportError:
    CACHETOOLS_AVAILABLE = False
    class SimpleTTLCache:
        def __init__(self, maxsize=1000, ttl=300):
            self.maxsize = maxsize
            self.ttl = ttl
            self.cache = OrderedDict()
            self.timestamps = {}
        def _clean_expired(self):
            now = time_module.time()
            expired = [k for k, ts in self.timestamps.items() if now - ts >= self.ttl]
            for k in expired:
                del self.cache[k]
                del self.timestamps[k]
        def __contains__(self, key):
            self._clean_expired()
            return key in self.cache
        def __getitem__(self, key):
            self._clean_expired()
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            raise KeyError
        def __setitem__(self, key, value):
            self._clean_expired()
            if key in self.cache:
                del self.cache[key]
            elif len(self.cache) >= self.maxsize:
                oldest_key, _ = self.cache.popitem(last=False)
                del self.timestamps[oldest_key]
            self.cache[key] = value
            self.timestamps[key] = time_module.time()
        def get(self, key, default=None):
            try:
                return self.__getitem__(key)
            except KeyError:
                return default
        def pop(self, key, default=None):
            self._clean_expired()
            if key in self.cache:
                value = self.cache[key]
                del self.cache[key]
                del self.timestamps[key]
                return value
            return default
        def clear(self):
            self.cache.clear()
            self.timestamps.clear()
        def clear_pattern(self, prefix: str):
            self._clean_expired()
            keys = [k for k in list(self.cache.keys()) if k.startswith(prefix)]
            for k in keys:
                del self.cache[k]
                del self.timestamps[k]
    _admin_cache = SimpleTTLCache(maxsize=1000, ttl=300)
    _security_cache = SimpleTTLCache(maxsize=500, ttl=60)
    _auth_cache = SimpleTTLCache(maxsize=1000, ttl=300)

class TimedLRUCache:
    def __init__(self, maxsize=200, ttl=3600):
        self.cache = OrderedDict()
        self.maxsize = maxsize
        self.ttl = ttl
        self._lock = asyncio.Lock()
    async def get(self, key):
        async with self._lock:
            if key in self.cache:
                value, timestamp = self.cache[key]
                if time_module.time() - timestamp < self.ttl:
                    self.cache.move_to_end(key)
                    return value
                del self.cache[key]
            return None
    async def set(self, key, value):
        async with self._lock:
            if key in self.cache:
                del self.cache[key]
            self.cache[key] = (value, time_module.time())
            if len(self.cache) > self.maxsize:
                self.cache.popitem(last=False)
    async def clear(self):
        async with self._lock:
            self.cache.clear()

_translation_cache = TimedLRUCache(maxsize=500, ttl=3600)

async def memory_optimizer():
    try:
        _admin_cache.clear()
        _security_cache.clear()
        _auth_cache.clear()
        await _translation_cache.clear()
        gc.collect()
        return True
    except Exception as e:
        logger.warning(f"⚠️ فشل تحسين الذاكرة: {e}")
        return False

async def is_authorized_in_group(bot, chat_id: int, user_id: int) -> bool:
    if user_id == PRIMARY_OWNER_ID:
        return True
    cache_key = f"auth_{chat_id}_{user_id}"
    if cache_key in _auth_cache:
        return _auth_cache[cache_key]
    from database import db_is_real_admin, db_is_hidden_owner, db_is_hidden_admin
    authorized = await db_is_real_admin(chat_id, user_id)
    if not authorized:
        authorized = await db_is_hidden_owner(chat_id, user_id)
    if not authorized:
        authorized = await db_is_hidden_admin(chat_id, user_id)
    _auth_cache[cache_key] = authorized
    return authorized

def invalidate_auth_cache(chat_id: int = None, user_id: int = None):
    if chat_id is not None and user_id is not None:
        _auth_cache.pop(f"auth_{chat_id}_{user_id}", None)
    elif chat_id is not None:
        prefix = f"auth_{chat_id}_"
        if hasattr(_auth_cache, 'clear_pattern'):
            _auth_cache.clear_pattern(prefix)
        else:
            keys = [k for k in _auth_cache if k.startswith(prefix)]
            for k in keys:
                del _auth_cache[k]
    else:
        _auth_cache.clear()

def invalidate_user_cache(user_id: int):
    pass

# ========== الإرسال الآمن ==========
async def safe_send_markdown(bot, chat_id: int, text: str, reply_markup=None, **kwargs):
    if not text:
        return None
    clean = sanitize_text(text)
    try:
        escaped = escape_markdown_v2(clean)
        if len(escaped) > 4096:
            escaped = escaped[:4093] + "..."
        return await bot.send_message(chat_id=chat_id, text=escaped, parse_mode='MarkdownV2', reply_markup=reply_markup, **kwargs)
    except Exception as e:
        if "can't parse entities" in str(e).lower():
            try:
                html_text = clean.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                if len(html_text) > 4096:
                    html_text = html_text[:4093] + "..."
                return await bot.send_message(chat_id=chat_id, text=html_text, parse_mode='HTML', reply_markup=reply_markup, **kwargs)
            except Exception:
                try:
                    return await bot.send_message(chat_id=chat_id, text=clean[:4096], reply_markup=reply_markup, **kwargs)
                except Exception:
                    raise
        else:
            raise

async def safe_edit_markdown(query, text: str, reply_markup=None, **kwargs):
    if not query or not query.message:
        return None
    clean = sanitize_text(text)
    try:
        escaped = escape_markdown_v2(clean)
        if len(escaped) > 4096:
            escaped = escaped[:4093] + "..."
        return await query.edit_message_text(text=escaped, parse_mode='MarkdownV2', reply_markup=reply_markup, **kwargs)
    except Exception as e:
        err = str(e).lower()
        if "can't parse entities" in err:
            try:
                html_text = clean.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                if len(html_text) > 4096:
                    html_text = html_text[:4093] + "..."
                return await query.edit_message_text(text=html_text, parse_mode='HTML', reply_markup=reply_markup, **kwargs)
            except Exception:
                try:
                    return await query.edit_message_text(text=clean[:4096], reply_markup=reply_markup, **kwargs)
                except Exception:
                    raise
        elif "message is not modified" in err:
            try:
                await query.answer("✅ تم التحديث")
            except:
                pass
            return None
        else:
            raise

async def safe_send_plain(bot, chat_id: int, text: str, **kwargs):
    if not text:
        return
    clean = sanitize_text(text)
    return await bot.send_message(chat_id=chat_id, text=clean[:4096], parse_mode=None, **kwargs)

async def safe_send_error(bot, chat_id: int, text: str):
    try:
        return await safe_send_markdown(bot, chat_id, text)
    except Exception:
        return await bot.send_message(chat_id=chat_id, text=text[:4000], parse_mode=None)

async def safe_send_long_message(bot, chat_id: int, text: str, reply_markup=None, max_length: int = 4000):
    if len(text) <= max_length:
        return await safe_send_markdown(bot, chat_id, text, reply_markup)
    parts = []
    current = ""
    for line in text.split('\n'):
        if len(current) + len(line) + 1 > max_length:
            parts.append(current)
            current = line
        else:
            current += "\n" + line if current else line
    if current:
        parts.append(current)
    first = True
    for part in parts:
        if first and reply_markup:
            await safe_send_markdown(bot, chat_id, part, reply_markup)
            first = False
        else:
            await safe_send_markdown(bot, chat_id, part)
        await asyncio.sleep(0.5)
    return None

# ========== الترجمة ==========
class AsyncTranslator:
    def __init__(self):
        self.session = None
        self.pending = {}
    async def get_session(self):
        if self.session is None:
            import aiohttp
            self.session = aiohttp.ClientSession()
        return self.session
    async def translate(self, text: str, target: str) -> str:
        if not text or target not in SUPPORTED_LANGUAGES:
            return text
        cache_key = hashlib.md5(f"{text}_{target}".encode()).hexdigest()
        cached = await _translation_cache.get(cache_key)
        if cached:
            return cached
        key = (text, target)
        if key in self.pending:
            future = asyncio.Future()
            self.pending[key].append(future)
            return await future
        self.pending[key] = []
        try:
            session = await self.get_session()
            url = "https://translate.googleapis.com/translate_a/single"
            params = {"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text}
            async with session.get(url, params=params, timeout=10) as resp:
                data = await resp.json()
                translated = data[0][0][0] if data and data[0] and data[0][0] else text
            await _translation_cache.set(cache_key, translated)
            for future in self.pending[key]:
                if not future.done():
                    future.set_result(translated)
            return translated
        except (Exception, asyncio.CancelledError) as e:
            if isinstance(e, asyncio.CancelledError):
                logger.warning(f"تم إلغاء مهمة الترجمة: {text[:30]}...")
            else:
                logger.error(f"خطأ في الترجمة: {e}")
            for future in self.pending[key]:
                if not future.done():
                    future.set_result(text)
            return text
        finally:
            if key in self.pending:
                del self.pending[key]

smart_translator = AsyncTranslator()

async def translate_text(text: str, target_lang: str, source_lang: str = 'auto') -> str:
    return await smart_translator.translate(text, target_lang)

# ========== أدوات أخرى ==========
def get_ram_usage():
    try:
        import psutil
        return {'percent': psutil.virtual_memory().percent}
    except ImportError:
        return {'percent': 0}

async def check_database_health():
    try:
        from database import execute_db
        async def _check(conn):
            await conn.execute("SELECT 1")
        await execute_db(_check)
        return True
    except Exception as e:
        logger.warning(f"⚠️ فشل فحص صحة قاعدة البيانات: {e}")
        return False

async def check_telegram_health():
    return True

class AdvancedLogger:
    def __init__(self):
        self.loggers = {}
    def log_error(self, message, error=None, context=None):
        import traceback
        error_id = secrets.token_hex(4)
        log_msg = f"[{error_id}] {message}"
        if error:
            log_msg += f" - {error}"
        if context:
            log_msg += f" - السياق: {json.dumps(context, default=str)[:200]}"
        logger.error(log_msg)
        if error:
            traceback.print_exc()
        return error_id
    def log_access(self, user_id, action, details=None):
        log_msg = f"User: {user_id} - Action: {action}"
        if details:
            log_msg += f" - {json.dumps(details, default=str)[:100]}"
        logger.info(log_msg)
    def log_security(self, event, user_id, details=None, severity="INFO"):
        log_msg = f"[{severity}] {event} - User: {user_id}"
        if details:
            log_msg += f" - {json.dumps(details, default=str)[:200]}"
        logger.warning(log_msg)

advanced_logger = AdvancedLogger()
log_error = advanced_logger.log_error

class RateLimiter:
    def __init__(self):
        self.requests = {}
        self.lock = asyncio.Lock()
    async def check_rate_limit(self, user_id: int, action: str, max_requests: int, time_window: int) -> bool:
        async with self.lock:
            key = f"{user_id}:{action}"
            now = time_module.time()
            if key in self.requests:
                self.requests[key] = [t for t in self.requests[key] if now - t < time_window]
                if not self.requests[key]:
                    del self.requests[key]
            if key not in self.requests:
                self.requests[key] = [now]
                return True
            if len(self.requests[key]) >= max_requests:
                return False
            self.requests[key].append(now)
            return True
    async def cleanup_old_entries(self, max_age: int = 600):
        async with self.lock:
            now = time_module.time()
            keys_to_delete = []
            for key, timestamps in self.requests.items():
                if not timestamps or (now - timestamps[-1] > max_age):
                    keys_to_delete.append(key)
            for key in keys_to_delete:
                del self.requests[key]

rate_limiter = RateLimiter()

def parse_days_of_week_safe(days_str: str) -> list:
    if not days_str:
        return []
    try:
        days = json.loads(days_str)
        if isinstance(days, list):
            return [int(d) for d in days if isinstance(d, (int, str)) and str(d).isdigit()]
        return []
    except Exception:
        return []

def parse_dates_safe(dates_str: str) -> list:
    if not dates_str:
        return []
    try:
        dates = json.loads(dates_str)
        if isinstance(dates, list):
            return [str(d) for d in dates if isinstance(d, str)]
        return []
    except Exception:
        return []

def check_single_instance():
    try:
        sock_path = TEMP_PATH / "bot.sock"
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(sock_path))
            return sock
        except socket.error:
            logger.error("❌ البوت يعمل بالفعل!")
            return False
    except AttributeError:
        logger.warning("⚠️ نظام التشغيل لا يدعم AF_UNIX. تخطي التحقق من المثيل الواحد.")
        return None
    except Exception as e:
        logger.warning(f"⚠️ لا يمكن التحقق من التشغيل الواحد: {e}")
        return None

# ========== صلاحيات البوت ==========
async def check_bot_permissions(bot, chat_id: int, chat_type: str = None) -> tuple:
    try:
        if chat_type is None:
            chat = await bot.get_chat(chat_id)
            chat_type = chat.type
        me = await bot.get_chat_member(chat_id, bot.id)
        if me.status not in ['administrator', 'creator']:
            return False, "البوت ليس مشرفاً"
        if chat_type == 'channel':
            if not me.can_post_messages:
                return False, "البوت لا يملك صلاحية النشر في القناة"
        else:
            if not me.can_send_messages:
                return False, "البوت لا يملك صلاحية إرسال الرسائل في المجموعة"
        return True, ""
    except Exception as e:
        return False, f"فشل التحقق من صلاحيات البوت: {str(e)[:100]}"

# ===================== لوحات المفاتيح (Keyboards) =====================
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_advanced_group_actions_keyboard(chat_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 حظر", callback_data=f"{CallbackData.GROUP_ACTION_BAN}:{chat_id}"),
         InlineKeyboardButton("🔇 كتم", callback_data=f"{CallbackData.GROUP_ACTION_MUTE}:{chat_id}")],
        [InlineKeyboardButton("⚠️ تحذير", callback_data=f"{CallbackData.GROUP_ACTION_WARN}:{chat_id}"),
         InlineKeyboardButton("👢 طرد", callback_data=f"{CallbackData.GROUP_ACTION_KICK}:{chat_id}")],
        [InlineKeyboardButton("🔒 تقييد", callback_data=f"{CallbackData.GROUP_ACTION_RESTRICT}:{chat_id}"),
         InlineKeyboardButton("📌 تثبيت", callback_data=f"{CallbackData.GROUP_ACTION_PIN}:{chat_id}")],
        [InlineKeyboardButton("🔓 إلغاء حظر", callback_data=f"{CallbackData.GROUP_ACTION_UNBAN}:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

def get_advanced_mute_duration_keyboard(chat_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ 5 دقائق", callback_data=f"adv_mute_duration:5:{chat_id}"),
         InlineKeyboardButton("⏱️ 30 دقيقة", callback_data=f"adv_mute_duration:30:{chat_id}")],
        [InlineKeyboardButton("⏱️ 1 ساعة", callback_data=f"adv_mute_duration:60:{chat_id}"),
         InlineKeyboardButton("⏱️ 12 ساعة", callback_data=f"adv_mute_duration:720:{chat_id}")],
        [InlineKeyboardButton("📆 يوم", callback_data=f"adv_mute_duration:1440:{chat_id}"),
         InlineKeyboardButton("📆 أسبوع", callback_data=f"adv_mute_duration:10080:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم دائم", callback_data=f"adv_mute_duration:0:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}")]
    ])

def security_keyboard(chat_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 حذف الروابط", callback_data=f"{CallbackData.SECURITY_LINKS_PREFIX}{chat_id}"),
         InlineKeyboardButton("@ حذف المعرفات", callback_data=f"{CallbackData.SECURITY_MENTIONS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🚫 كلمات محظورة", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}"),
         InlineKeyboardButton("⏱️ الوضع البطيء", callback_data=f"{CallbackData.SECURITY_SLOWMODE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🎯 الترحيب", callback_data=f"{CallbackData.SECURITY_WELCOME_PREFIX}{chat_id}"),
         InlineKeyboardButton("👋 الوداع", callback_data=f"{CallbackData.SECURITY_GOODBYE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🎴 حذف الملصقات", callback_data=f"{CallbackData.SECURITY_STICKERS_PREFIX}{chat_id}"),
         InlineKeyboardButton("🎬 حذف الفيديوهات", callback_data=f"{CallbackData.SECURITY_VIDEOS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("📨 حذف رسائل الخدمة", callback_data=f"{CallbackData.SECURITY_SERVICE_MESSAGES_PREFIX}{chat_id}")],
        [InlineKeyboardButton("⚖️ تحديد العقوبة", callback_data=f"{CallbackData.PENALTY_MENU}:{chat_id}"),
         InlineKeyboardButton("📝 إعدادات الردود", callback_data=CallbackData.ADMIN_AUTO_REPLY)],
        [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}")],
        [InlineKeyboardButton("📜 سجل الإجراءات", callback_data=f"{CallbackData.GROUP_ACTION_LOG}:{chat_id}")],
        [InlineKeyboardButton("🔙 إغلاق", callback_data=CallbackData.SECURITY_CLOSE)]
    ])

def get_admin_keyboard(user_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 المستخدمين", callback_data=CallbackData.ADMIN_USERS),
         InlineKeyboardButton("🚫 المحظورين", callback_data=CallbackData.ADMIN_BANNED_USERS)],
        [InlineKeyboardButton("📡 القنوات", callback_data=CallbackData.ADMIN_ALL_CHANNELS),
         InlineKeyboardButton("⛔ قنوات محظورة", callback_data=CallbackData.ADMIN_BANNED_CHANNELS)],
        [InlineKeyboardButton("📊 المجموعات", callback_data=CallbackData.ADMIN_GROUPS),
         InlineKeyboardButton("🚷 مجموعات محظورة", callback_data=CallbackData.ADMIN_BANNED_GROUPS)],
        [InlineKeyboardButton("📢 قنوات البوت", callback_data=CallbackData.ADMIN_BOT_CHANNELS),
         InlineKeyboardButton("🚫 قنوات بوت محظورة", callback_data=CallbackData.ADMIN_BANNED_BOT_CHANNELS)],
        [InlineKeyboardButton("❤️ تنشيط الكل", callback_data=CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS),
         InlineKeyboardButton("📂 مراقبة المستخدمين", callback_data=CallbackData.ADMIN_MONITOR_USERS)],
        [InlineKeyboardButton("👑 + مشرف", callback_data=CallbackData.ADMIN_ADD_ADMIN),
         InlineKeyboardButton("🗑️ - مشرف", callback_data=CallbackData.ADMIN_REMOVE_ADMIN)],
        [InlineKeyboardButton("💬 ردود المجموعة", callback_data=CallbackData.ADMIN_REPLIES),
         InlineKeyboardButton("🚫 كلمات محظورة (عامة)", callback_data=CallbackData.ADMIN_BANNED_WORDS)],
        [InlineKeyboardButton("📝 إعدادات الردود", callback_data=CallbackData.ADMIN_AUTO_REPLY)],
        [InlineKeyboardButton("🔒 إعدادات NSFW", callback_data=CallbackData.NSFW_SETTINGS)],
        [InlineKeyboardButton("🏆 إنشاء مسابقة", callback_data=CallbackData.ADMIN_CREATE_CONTEST),
         InlineKeyboardButton("🏅 إعلان فائز", callback_data=CallbackData.ADMIN_DECLARE_WINNER)],
        [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:0")],
        [InlineKeyboardButton("🖥️ حالة الرام", callback_data=CallbackData.ADMIN_RAM),
         InlineKeyboardButton("📊 إحصائيات عامة", callback_data=CallbackData.ADMIN_STATS)],
        [InlineKeyboardButton("📈 مقاييس الأداء", callback_data=CallbackData.ADMIN_METRICS)],
        [InlineKeyboardButton("💾 نسخة احتياطية", callback_data=CallbackData.ADMIN_BACKUP),
         InlineKeyboardButton("🔄 استعادة نسخة", callback_data=CallbackData.ADMIN_RESTORE_BACKUP)],
        [InlineKeyboardButton("⏱️ وقت النشر (عام)", callback_data=CallbackData.ADMIN_CHANGE_INTERVAL),
         InlineKeyboardButton("⚙️ إعدادات النسخ", callback_data=CallbackData.ADMIN_BACKUP_SETTINGS)],
        [InlineKeyboardButton("📢 نشر تحديث", callback_data=CallbackData.ADMIN_SEND_UPDATE),
         InlineKeyboardButton("⚙️ قناة التحديثات", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
        [InlineKeyboardButton("📢 عرض القناة الحالية", callback_data=CallbackData.ADMIN_SHOW_UPDATE_CHANNEL)],
        [InlineKeyboardButton("🔄 التحديثات", callback_data=CallbackData.ADMIN_UPDATES),
         InlineKeyboardButton("🔒 الاشتراك الإجباري", callback_data=CallbackData.ADMIN_FORCE_SUBSCRIBE)],
        [InlineKeyboardButton("⚙️ تعيين القناة", callback_data=CallbackData.ADMIN_SET_FORCE_CHANNEL),
         InlineKeyboardButton("📨 إرسال رسالة", callback_data=CallbackData.ADMIN_BROADCAST)],
        [InlineKeyboardButton("📋 تذاكر الدعم", callback_data=CallbackData.ADMIN_SUPPORT_TICKETS),
         InlineKeyboardButton("🗑️ حذف جميع التذاكر", callback_data=CallbackData.ADMIN_DELETE_ALL_TICKETS)],
        [InlineKeyboardButton("📁 صلاحية /sendcode", callback_data=CallbackData.ADMIN_MANAGE_SENDCODE),
         InlineKeyboardButton("📋 قناة التقارير", callback_data=CallbackData.ADMIN_SHOW_LOG_CHANNEL)],
        [InlineKeyboardButton("📋 تعيين قناة التقارير", callback_data=CallbackData.ADMIN_SET_LOG_CHANNEL)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])

def get_group_banned_words_keyboard(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"{CallbackData.BANNED_WORDS_ADD_PREFIX}{chat_id}"),
         InlineKeyboardButton("📋 عرض الكلمات", callback_data=f"{CallbackData.BANNED_WORDS_LIST_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=f"{CallbackData.BANNED_WORDS_REMOVE_PREFIX}{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

def get_replies_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة رد", callback_data=CallbackData.ADMIN_ADD_REPLY),
         InlineKeyboardButton("📋 عرض الردود", callback_data=CallbackData.ADMIN_LIST_REPLIES)],
        [InlineKeyboardButton("🗑️ حذف رد", callback_data=CallbackData.ADMIN_DEL_REPLY),
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])

def get_auto_reply_keyboard(chat_id: int, settings: dict):
    status_text = "🟢 مفعل" if settings['enabled'] else "🔴 معطل"
    admin_text = "👑 مشرفين فقط" if settings['only_admins'] else "👥 الجميع"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 الردود التلقائية: {status_text}", callback_data=f"{CallbackData.AUTO_REPLY_TOGGLE_PREFIX}{chat_id}")],
        [InlineKeyboardButton(f"👥 المستخدمون: {admin_text}", callback_data=f"{CallbackData.AUTO_REPLY_ADMINS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🔄 إعادة تعيين الردود", callback_data=f"{CallbackData.AUTO_REPLY_RESET_PREFIX}{chat_id}")],
        [InlineKeyboardButton("📊 إحصائيات الردود", callback_data=f"{CallbackData.AUTO_REPLY_STATS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

def get_user_auto_reply_keyboard(user_id: int, enabled: bool):
    status_text = "🟢 مفعل" if enabled else "🔴 معطل"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 الردود التلقائية: {status_text}", callback_data=f"{CallbackData.USER_AUTO_REPLY_TOGGLE_PREFIX}{user_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])

def get_banned_words_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة عامة", callback_data=CallbackData.ADMIN_ADD_BANNED_WORD),
         InlineKeyboardButton("📋 عرض الكلمات", callback_data=CallbackData.ADMIN_LIST_BANNED_WORDS)],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=CallbackData.ADMIN_REMOVE_BANNED_WORD),
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])

def penalty_keyboard(chat_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 طرد", callback_data=f"{CallbackData.PENALTY_KICK}:{chat_id}"),
         InlineKeyboardButton("🛑 حظر", callback_data=f"{CallbackData.PENALTY_BAN}:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم", callback_data=f"{CallbackData.PENALTY_MUTE}:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

def mute_duration_keyboard(chat_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ 5 دقائق", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_5}:{chat_id}"),
         InlineKeyboardButton("⏱️ 30 دقيقة", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_30}:{chat_id}")],
        [InlineKeyboardButton("⏱️ 1 ساعة", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_60}:{chat_id}"),
         InlineKeyboardButton("⏱️ 12 ساعة", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_720}:{chat_id}")],
        [InlineKeyboardButton("📆 يوم", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_1440}:{chat_id}"),
         InlineKeyboardButton("📆 أسبوع", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_10080}:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم دائم", callback_data=f"{CallbackData.GROUP_MUTE_DURATION_PERMANENT}:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.PENALTY_MENU}:{chat_id}")]
    ])

async def build_days_keyboard(user_id: int, context):
    selected = context.user_data.get('selected_days', [])
    day_names = ['الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
    keyboard = []
    for i, name in enumerate(day_names):
        status = "✅" if i in selected else "⬜"
        keyboard.append([InlineKeyboardButton(f"{status} {name}", callback_data=f"{CallbackData.SCHEDULE_DAY_SELECT_PREFIX}{i}")])
    keyboard.append([InlineKeyboardButton("💾 حفظ", callback_data=CallbackData.SCHEDULE_SAVE_DAYS)])
    keyboard.append([InlineKeyboardButton("🔙 إلغاء", callback_data=CallbackData.BACK)])
    return InlineKeyboardMarkup(keyboard)
