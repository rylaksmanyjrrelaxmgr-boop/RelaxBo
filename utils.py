#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
دوال مساعدة عامة – النسخة النهائية الشاملة
- جميع دوال الوقت، التشفير، الترجمة، الضغط
- دوال لوحات المفاتيح (Keyboards)
- compress_backup / decompress_backup
- contains_link / contains_mention / contains_hashtag
"""

import re, json, time as time_module, secrets, hashlib, html, os, sys, gc, asyncio, socket, logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Tuple, Any
import urllib.parse
from collections import defaultdict, OrderedDict

try: import bleach
except ImportError: bleach = None

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
    try: return int(os.getenv(key, str(default)))
    except: return default

def get_env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() in ['true','1','yes','on']

def get_env_float(key: str, default: float) -> float:
    try: return float(os.getenv(key, str(default)))
    except: return default

def escape_markdown_v2(text: str) -> str:
    if not text: return ""
    for char in r'_*[]()~`>#+\-=|{}.!': text = text.replace(char, f'\\{char}')
    return text

def clean_text_for_telegram(text: str) -> str:
    if not text: return ""
    text = re.sub(r'[\u200b\u200c\u200d\u2060\uFEFF\u202a\u202b\u202c\u202d\u202e]', '', text)
    return text.replace('\ufeff','').replace('\ufffc','')

def sanitize_text(text: str, max_length: int = 4096, allow_tags: list = None) -> str:
    if not text: return ""
    if bleach is not None:
        try:
            if allow_tags is None: allow_tags = ['b','i','u','s','a','code','pre','strong','em']
            text = bleach.clean(text, tags=allow_tags, attributes={'a':['href','title']}, styles=[], strip=True)
        except: pass
    else:
        text = re.sub(r'<[^>]*>', '', text)
    if len(text) > max_length: text = text[:max_length]
    return text

def encode_callback_data(data: str) -> str: return urllib.parse.quote(data, safe='')
def decode_callback_data(data: str) -> str: return urllib.parse.unquote(data)
def safe_int(value, default=0):
    try: return int(value)
    except: return default

def utc_now(): return datetime.now(timezone.utc).replace(tzinfo=None)
def mecca_now(): return utc_now() + timedelta(hours=3)
def utc_now_iso(): return utc_now().isoformat()
def mecca_now_iso(): return mecca_now().isoformat()

def to_naive(dt):
    if dt is None: return None
    if hasattr(dt,'tzinfo') and dt.tzinfo is not None: return dt.replace(tzinfo=None)
    return dt

def mecca_to_utc(mecca_dt):
    if mecca_dt is None: return None
    if hasattr(mecca_dt,'tzinfo') and mecca_dt.tzinfo is not None: mecca_dt = mecca_dt.replace(tzinfo=None)
    return mecca_dt - timedelta(hours=3)

def utc_to_mecca(utc_dt):
    if utc_dt is None: return None
    if hasattr(utc_dt,'tzinfo') and utc_dt.tzinfo is not None: utc_dt = utc_dt.replace(tzinfo=None)
    return utc_dt + timedelta(hours=3)

def encrypt_file(path: Path, cipher: Fernet) -> Path:
    data = path.read_bytes()
    encrypted = cipher.encrypt(data)
    encrypted_path = path.with_suffix('.enc')
    encrypted_path.write_bytes(encrypted)
    return encrypted_path

def decrypt_file(path: Path, cipher: Fernet) -> Path:
    encrypted = path.read_bytes()
    decrypted = cipher.decrypt(encrypted)
    decrypted_path = path.with_suffix('.dec')
    decrypted_path.write_bytes(decrypted)
    return decrypted_path

def encrypt_db_backup():
    if not DB_ENCRYPTION: return DB_PATH
    return encrypt_file(DB_PATH, Fernet(ENCRYPTION_KEY))

try:
    import zstandard
    ZSTD_AVAILABLE = True; ZSTD_COMPRESSOR = zstandard.ZstdCompressor(level=3); ZSTD_DECOMPRESSOR = zstandard.ZstdDecompressor()
except ImportError:
    ZSTD_AVAILABLE = False; ZSTD_COMPRESSOR = None; ZSTD_DECOMPRESSOR = None

def compress_backup(data: bytes) -> bytes:
    if ZSTD_AVAILABLE and ZSTD_COMPRESSOR:
        try: return ZSTD_COMPRESSOR.compress(data)
        except: pass
    return data

def decompress_backup(data: bytes) -> bytes:
    if ZSTD_AVAILABLE and ZSTD_DECOMPRESSOR:
        try: return ZSTD_DECOMPRESSOR.decompress(data)
        except: pass
    return data

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
            self.maxsize, self.ttl = maxsize, ttl
            self.cache = OrderedDict(); self.timestamps = {}
        def _clean_expired(self):
            now = time_module.time()
            for k in [k for k,ts in self.timestamps.items() if now-ts>=self.ttl]:
                del self.cache[k]; del self.timestamps[k]
        def __contains__(self, key): self._clean_expired(); return key in self.cache
        def __getitem__(self, key):
            self._clean_expired()
            if key in self.cache: self.cache.move_to_end(key); return self.cache[key]
            raise KeyError
        def __setitem__(self, key, value):
            self._clean_expired()
            if key in self.cache: del self.cache[key]
            elif len(self.cache)>=self.maxsize:
                oldest, _ = self.cache.popitem(last=False); del self.timestamps[oldest]
            self.cache[key] = value; self.timestamps[key] = time_module.time()
        def get(self, key, default=None):
            try: return self[key]
            except KeyError: return default
        def pop(self, key, default=None):
            self._clean_expired()
            if key in self.cache:
                v = self.cache[key]; del self.cache[key]; del self.timestamps[key]; return v
            return default
        def clear(self): self.cache.clear(); self.timestamps.clear()
        def clear_pattern(self, prefix):
            self._clean_expired()
            for k in [k for k in list(self.cache.keys()) if k.startswith(prefix)]:
                del self.cache[k]; del self.timestamps[k]
    _admin_cache = SimpleTTLCache(1000,300)
    _security_cache = SimpleTTLCache(500,60)
    _auth_cache = SimpleTTLCache(1000,300)

class TimedLRUCache:
    def __init__(self, maxsize=200, ttl=3600):
        self.cache = OrderedDict(); self.maxsize = maxsize; self.ttl = ttl; self._lock = asyncio.Lock()
    async def get(self, key):
        async with self._lock:
            if key in self.cache:
                v, ts = self.cache[key]
                if time_module.time()-ts < self.ttl: self.cache.move_to_end(key); return v
                del self.cache[key]
            return None
    async def set(self, key, value):
        async with self._lock:
            if key in self.cache: del self.cache[key]
            self.cache[key] = (value, time_module.time())
            if len(self.cache) > self.maxsize: self.cache.popitem(last=False)
    async def clear(self):
        async with self._lock: self.cache.clear()

_translation_cache = TimedLRUCache(500, 3600)

async def memory_optimizer():
    try:
        _admin_cache.clear(); _security_cache.clear(); _auth_cache.clear()
        await _translation_cache.clear(); gc.collect()
        return True
    except: return False

async def is_authorized_in_group(bot, chat_id, user_id):
    if user_id == PRIMARY_OWNER_ID: return True
    cache_key = f"auth_{chat_id}_{user_id}"
    if cache_key in _auth_cache: return _auth_cache[cache_key]
    from database import db_is_real_admin, db_is_hidden_owner, db_is_hidden_admin
    authorized = await db_is_real_admin(chat_id, user_id) or await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id)
    _auth_cache[cache_key] = authorized
    return authorized

def invalidate_auth_cache(chat_id=None, user_id=None):
    if chat_id and user_id: _auth_cache.pop(f"auth_{chat_id}_{user_id}", None)
    elif chat_id:
        if hasattr(_auth_cache,'clear_pattern'): _auth_cache.clear_pattern(f"auth_{chat_id}_")
        else:
            for k in [k for k in _auth_cache if k.startswith(f"auth_{chat_id}_")]: del _auth_cache[k]
    else: _auth_cache.clear()

def invalidate_user_cache(user_id): pass

async def safe_send_markdown(bot, chat_id, text, reply_markup=None, **kwargs):
    if not text: return None
    clean = sanitize_text(text)
    try:
        escaped = escape_markdown_v2(clean)
        if len(escaped)>4096: escaped = escaped[:4093]+"..."
        return await bot.send_message(chat_id=chat_id, text=escaped, parse_mode='MarkdownV2', reply_markup=reply_markup, **kwargs)
    except Exception as e:
        if "can't parse entities" in str(e).lower():
            try:
                html_text = clean.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                if len(html_text)>4096: html_text = html_text[:4093]+"..."
                return await bot.send_message(chat_id=chat_id, text=html_text, parse_mode='HTML', reply_markup=reply_markup, **kwargs)
            except:
                try: return await bot.send_message(chat_id=chat_id, text=clean[:4096], reply_markup=reply_markup, **kwargs)
                except: raise
        else: raise

async def safe_edit_markdown(query, text, reply_markup=None, **kwargs):
    if not query or not query.message: return None
    clean = sanitize_text(text)
    try:
        escaped = escape_markdown_v2(clean)
        if len(escaped)>4096: escaped = escaped[:4093]+"..."
        return await query.edit_message_text(text=escaped, parse_mode='MarkdownV2', reply_markup=reply_markup, **kwargs)
    except Exception as e:
        err = str(e).lower()
        if "can't parse entities" in err:
            try:
                html_text = clean.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                if len(html_text)>4096: html_text = html_text[:4093]+"..."
                return await query.edit_message_text(text=html_text, parse_mode='HTML', reply_markup=reply_markup, **kwargs)
            except:
                try: return await query.edit_message_text(text=clean[:4096], reply_markup=reply_markup, **kwargs)
                except: raise
        elif "message is not modified" in err:
            try: await query.answer("✅ تم التحديث")
            except: pass
            return None
        else: raise

async def safe_send_plain(bot, chat_id, text, **kwargs):
    if not text: return
    return await bot.send_message(chat_id=chat_id, text=sanitize_text(text)[:4096], parse_mode=None, **kwargs)

async def safe_send_error(bot, chat_id, text):
    try: return await safe_send_markdown(bot, chat_id, text)
    except: return await bot.send_message(chat_id=chat_id, text=text[:4000], parse_mode=None)

async def safe_send_long_message(bot, chat_id, text, reply_markup=None, max_length=4000):
    if len(text) <= max_length: return await safe_send_markdown(bot, chat_id, text, reply_markup)
    parts = []; current = ""
    for line in text.split('\n'):
        if len(current)+len(line)+1 > max_length: parts.append(current); current = line
        else: current += "\n"+line if current else line
    if current: parts.append(current)
    first = True
    for part in parts:
        if first and reply_markup: await safe_send_markdown(bot, chat_id, part, reply_markup); first = False
        else: await safe_send_markdown(bot, chat_id, part)
        await asyncio.sleep(0.5)

class AsyncTranslator:
    def __init__(self): self.session = None; self.pending = {}
    async def get_session(self):
        if self.session is None:
            import aiohttp; self.session = aiohttp.ClientSession()
        return self.session
    async def translate(self, text, target):
        if not text or target not in SUPPORTED_LANGUAGES: return text
        cache_key = hashlib.md5(f"{text}_{target}".encode()).hexdigest()
        cached = await _translation_cache.get(cache_key)
        if cached: return cached
        key = (text, target)
        if key in self.pending:
            future = asyncio.Future(); self.pending[key].append(future); return await future
        self.pending[key] = []
        try:
            session = await self.get_session()
            url = "https://translate.googleapis.com/translate_a/single"
            params = {"client":"gtx","sl":"auto","tl":target,"dt":"t","q":text}
            async with session.get(url, params=params, timeout=10) as resp:
                data = await resp.json()
                translated = data[0][0][0] if data and data[0] and data[0][0] else text
            await _translation_cache.set(cache_key, translated)
            for future in self.pending[key]:
                if not future.done(): future.set_result(translated)
            return translated
        except (Exception, asyncio.CancelledError) as e:
            for future in self.pending[key]:
                if not future.done(): future.set_result(text)
            return text
        finally:
            if key in self.pending: del self.pending[key]

smart_translator = AsyncTranslator()
translate_text = smart_translator.translate

def get_ram_usage():
    try:
        import psutil; return {'percent': psutil.virtual_memory().percent}
    except ImportError: return {'percent': 0}

async def check_database_health():
    try:
        from database import execute_db
        await execute_db(lambda conn: conn.execute("SELECT 1"))
        return True
    except: return False

async def check_telegram_health(): return True

class AdvancedLogger:
    def log_error(self, message, error=None, context=None):
        import traceback
        eid = secrets.token_hex(4)
        msg = f"[{eid}] {message}"
        if error: msg += f" - {error}"
        if context: msg += f" - {json.dumps(context, default=str)[:200]}"
        logger.error(msg)
        if error: traceback.print_exc()
        return eid
    def log_access(self, uid, action, details=None):
        msg = f"User: {uid} - Action: {action}"
        if details: msg += f" - {json.dumps(details, default=str)[:100]}"
        logger.info(msg)

advanced_logger = AdvancedLogger()
log_error = advanced_logger.log_error

class RateLimiter:
    def __init__(self): self.requests = {}; self.lock = asyncio.Lock()
    async def check_rate_limit(self, user_id, action, max_requests, time_window):
        async with self.lock:
            key = f"{user_id}:{action}"; now = time_module.time()
            if key in self.requests:
                self.requests[key] = [t for t in self.requests[key] if now-t < time_window]
                if not self.requests[key]: del self.requests[key]
            if key not in self.requests: self.requests[key] = [now]; return True
            if len(self.requests[key]) >= max_requests: return False
            self.requests[key].append(now); return True
    async def cleanup_old_entries(self, max_age=600):
        async with self.lock:
            now = time_module.time()
            for key in [k for k,ts in self.requests.items() if not ts or now-ts[-1]>max_age]:
                del self.requests[key]

rate_limiter = RateLimiter()

def parse_days_of_week_safe(days_str):
    if not days_str: return []
    try:
        days = json.loads(days_str)
        if isinstance(days,list): return [int(d) for d in days if str(d).isdigit()]
    except: pass
    return []

def parse_dates_safe(dates_str):
    if not dates_str: return []
    try:
        dates = json.loads(dates_str)
        if isinstance(dates,list): return [str(d) for d in dates if isinstance(d,str)]
    except: pass
    return []

def check_single_instance():
    try:
        sock_path = TEMP_PATH / "bot.sock"
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try: sock.bind(str(sock_path)); return sock
        except socket.error: logger.error("❌ البوت يعمل بالفعل!"); return False
    except AttributeError: logger.warning("⚠️ AF_UNIX غير مدعوم"); return None
    except: return None

async def check_bot_permissions(bot, chat_id, chat_type=None):
    try:
        if chat_type is None: chat_type = (await bot.get_chat(chat_id)).type
        me = await bot.get_chat_member(chat_id, bot.id)
        if me.status not in ('administrator','creator'): return False, "البوت ليس مشرفاً"
        if chat_type == 'channel' and not me.can_post_messages: return False, "البوت لا يملك صلاحية النشر"
        return True, ""
    except Exception as e: return False, f"فشل التحقق: {e}"

# ===================== دوال فحص الروابط والإشارات =====================
def contains_link(text: str) -> bool:
    if not text: return False
    patterns = [r'https?://[^\s]+', r'www\.[a-zA-Z0-9][^\s]*\.[a-zA-Z]{2,}[^\s]*',
                r'[a-zA-Z0-9][^\s]*\.(com|net|org|io|gov|edu|me|info|xyz|online|site|store|web|co|uk|de|fr|ru|ir|sa|ae|eg)/[^\s]*']
    for p in patterns:
        if re.search(p, text, re.IGNORECASE): return True
    return False

def contains_mention(text: str) -> bool:
    if not text: return False
    return bool(re.search(r'@\w{5,}', text))

def contains_hashtag(text: str) -> bool:
    if not text: return False
    return bool(re.search(r'#\w+', text))

# ===================== لوحات المفاتيح =====================
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_advanced_group_actions_keyboard(chat_id):
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

def get_advanced_mute_duration_keyboard(chat_id):
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

def security_keyboard(chat_id):
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

def get_admin_keyboard(user_id):
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

def get_auto_reply_keyboard(chat_id, settings):
    status = "🟢 مفعل" if settings.get('enabled') else "🔴 معطل"
    admin = "👑 مشرفين فقط" if settings.get('only_admins') else "👥 الجميع"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 الردود التلقائية: {status}", callback_data=f"{CallbackData.AUTO_REPLY_TOGGLE_PREFIX}{chat_id}")],
        [InlineKeyboardButton(f"👥 المستخدمون: {admin}", callback_data=f"{CallbackData.AUTO_REPLY_ADMINS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🔄 إعادة تعيين الردود", callback_data=f"{CallbackData.AUTO_REPLY_RESET_PREFIX}{chat_id}")],
        [InlineKeyboardButton("📊 إحصائيات الردود", callback_data=f"{CallbackData.AUTO_REPLY_STATS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

def get_user_auto_reply_keyboard(user_id, enabled):
    status = "🟢 مفعل" if enabled else "🔴 معطل"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 الردود التلقائية: {status}", callback_data=f"{CallbackData.USER_AUTO_REPLY_TOGGLE_PREFIX}{user_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])

def get_banned_words_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة عامة", callback_data=CallbackData.ADMIN_ADD_BANNED_WORD),
         InlineKeyboardButton("📋 عرض الكلمات", callback_data=CallbackData.ADMIN_LIST_BANNED_WORDS)],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=CallbackData.ADMIN_REMOVE_BANNED_WORD),
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])

def penalty_keyboard(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 طرد", callback_data=f"{CallbackData.PENALTY_KICK}:{chat_id}"),
         InlineKeyboardButton("🛑 حظر", callback_data=f"{CallbackData.PENALTY_BAN}:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم", callback_data=f"{CallbackData.PENALTY_MUTE}:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

def mute_duration_keyboard(chat_id):
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

async def build_days_keyboard(user_id, context):
    selected = context.user_data.get('selected_days', [])
    day_names = ['الإثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت','الأحد']
    keyboard = []
    for i, name in enumerate(day_names):
        status = "✅" if i in selected else "⬜"
        keyboard.append([InlineKeyboardButton(f"{status} {name}", callback_data=f"{CallbackData.SCHEDULE_DAY_SELECT_PREFIX}{i}")])
    keyboard.append([InlineKeyboardButton("💾 حفظ", callback_data=CallbackData.SCHEDULE_SAVE_DAYS)])
    keyboard.append([InlineKeyboardButton("🔙 إلغاء", callback_data=CallbackData.BACK)])
    return InlineKeyboardMarkup(keyboard)
