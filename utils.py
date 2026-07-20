#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
دوال مساعدة عامة
"""

import re
import json
import time as time_module
import secrets
import base64
import hashlib
import hmac
import os
import sys
import gc
import asyncio
import random
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Tuple, Any, Union, Callable, Awaitable
from functools import lru_cache, wraps
import urllib.parse

# استيراد المكتبات المطلوبة
try:
    import bleach
except ImportError:
    bleach = None

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# من constants.py
from constants import (
    ENCRYPTION_KEY, BACKUP_ENCRYPTION_KEY, DB_ENCRYPTION,
    DATA_PATH, TEMP_PATH, SECURITY_LOG, ERROR_LOG, ACCESS_LOG,
    LOG_PATH, DB_PATH, SUPPORTED_LANGUAGES
)

# ===================== التهرب من علامات Markdown =====================
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
            cleaned = bleach.clean(
                text,
                tags=allow_tags,
                attributes={'a': ['href', 'title']},
                styles=[],
                strip=True
            )
            text = cleaned
        except:
            pass
    else:
        text = re.sub(r'<[^>]+>', '', text)
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

# ===================== دوال الوقت =====================
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

# ===================== دوال التشفير =====================
def encrypt_file_stream(src: Path, dst: Path, cipher: Fernet, chunk_size: int = 64*1024):
    with open(src, 'rb') as f_in, open(dst, 'wb') as f_out:
        while True:
            chunk = f_in.read(chunk_size)
            if not chunk:
                break
            encrypted_chunk = cipher.encrypt(chunk)
            f_out.write(encrypted_chunk)

def decrypt_file_stream(src: Path, dst: Path, cipher: Fernet, chunk_size: int = 64*1024):
    with open(src, 'rb') as f_in, open(dst, 'wb') as f_out:
        while True:
            chunk = f_in.read(chunk_size)
            if not chunk:
                break
            decrypted_chunk = cipher.decrypt(chunk)
            f_out.write(decrypted_chunk)

def encrypt_db_backup():
    if not DB_ENCRYPTION:
        return DB_PATH
    from constants import ENCRYPTION_KEY
    cipher = Fernet(ENCRYPTION_KEY)
    encrypted_path = DB_PATH.with_suffix('.enc')
    encrypt_file_stream(DB_PATH, encrypted_path, cipher)
    return encrypted_path

# ===================== تحسينات التخزين المؤقت =====================
try:
    from cachetools import TTLCache, LRUCache
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
            self.cache = {}
            self.timestamps = {}

        def __contains__(self, key):
            if key in self.cache and time_module.time() - self.timestamps[key] < self.ttl:
                return True
            return False

        def __getitem__(self, key):
            if key in self.cache and time_module.time() - self.timestamps[key] < self.ttl:
                return self.cache[key]
            raise KeyError

        def __setitem__(self, key, value):
            if len(self.cache) >= self.maxsize:
                oldest = min(self.timestamps, key=self.timestamps.get)
                del self.cache[oldest]
                del self.timestamps[oldest]
            self.cache[key] = value
            self.timestamps[key] = time_module.time()

        def get(self, key, default=None):
            try:
                return self.__getitem__(key)
            except KeyError:
                return default

        def pop(self, key, default=None):
            try:
                value = self.__getitem__(key)
                del self.cache[key]
                del self.timestamps[key]
                return value
            except KeyError:
                return default

        def clear(self):
            self.cache.clear()
            self.timestamps.clear()

    _admin_cache = SimpleTTLCache(maxsize=1000, ttl=300)
    _security_cache = SimpleTTLCache(maxsize=500, ttl=60)
    _auth_cache = SimpleTTLCache(maxsize=1000, ttl=300)

# ===================== تخزين مؤقت للترجمة =====================
class TimedLRUCache:
    def __init__(self, maxsize=200, ttl=3600):
        self.cache = {}
        self.maxsize = maxsize
        self.ttl = ttl
        self._lock = asyncio.Lock()

    async def get(self, key):
        async with self._lock:
            if key in self.cache:
                value, timestamp = self.cache[key]
                if time_module.time() - timestamp < self.ttl:
                    return value
                else:
                    del self.cache[key]
            return None

    async def set(self, key, value):
        async with self._lock:
            if key in self.cache:
                del self.cache[key]
            self.cache[key] = (value, time_module.time())
            if len(self.cache) > self.maxsize:
                oldest = min(self.cache.keys(), key=lambda k: self.cache[k][1])
                del self.cache[oldest]

    async def clear(self):
        async with self._lock:
            self.cache.clear()

_translation_cache = TimedLRUCache(maxsize=500, ttl=3600)

# ===================== تحسين الذاكرة =====================
def memory_optimizer():
    try:
        if CACHETOOLS_AVAILABLE:
            _admin_cache.clear()
            _security_cache.clear()
            _auth_cache.clear()
        else:
            _admin_cache.clear()
            _security_cache.clear()
            _auth_cache.clear()
        asyncio.create_task(_translation_cache.clear())
        gc.collect()
        return True
    except:
        return False

# ===================== دوال الصلاحيات =====================
async def is_authorized_in_group(bot, chat_id: int, user_id: int) -> bool:
    if user_id == PRIMARY_OWNER_ID:
        return True

    cache_key = f"auth_{chat_id}_{user_id}"
    if cache_key in _auth_cache:
        return _auth_cache[cache_key]

    authorized = False
    # استيراد دوال قاعدة البيانات بشكل متأخر لتجنب الاعتماد الدائري
    from database import db_is_real_admin, db_is_hidden_owner, db_is_hidden_admin
    if await db_is_real_admin(chat_id, user_id):
        authorized = True
    if not authorized and await db_is_hidden_owner(chat_id, user_id):
        authorized = True
    if not authorized and await db_is_hidden_admin(chat_id, user_id):
        authorized = True

    _auth_cache[cache_key] = authorized
    return authorized

def invalidate_auth_cache(chat_id: int = None, user_id: int = None):
    if chat_id is not None and user_id is not None:
        cache_key = f"auth_{chat_id}_{user_id}"
        _auth_cache.pop(cache_key, None)
    elif chat_id is not None:
        keys_to_remove = [k for k in list(_auth_cache.cache.keys()) if k.startswith(f"auth_{chat_id}_")]
        for k in keys_to_remove:
            _auth_cache.pop(k, None)
    else:
        _auth_cache.clear()

def invalidate_user_cache(user_id: int):
    # إبطال ذاكرة التخزين المؤقت للمستخدم (مثل الكيبورد الرئيسي)
    pass  # يمكن تنفيذها حسب الحاجة

# ===================== دوال الإرسال الآمنة =====================
async def safe_send_markdown(bot, chat_id: int, text: str, reply_markup=None, **kwargs):
    if not text:
        return None
    clean_text = sanitize_text(text)
    try:
        escaped = escape_markdown_v2(clean_text)
        if len(escaped) > 4096:
            escaped = escaped[:4093] + "..."
        return await bot.send_message(
            chat_id=chat_id,
            text=escaped,
            parse_mode='MarkdownV2',
            reply_markup=reply_markup,
            **kwargs
        )
    except Exception as e:
        if "can't parse entities" in str(e).lower():
            try:
                html_text = clean_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                if len(html_text) > 4096:
                    html_text = html_text[:4093] + "..."
                return await bot.send_message(
                    chat_id=chat_id,
                    text=html_text,
                    parse_mode='HTML',
                    reply_markup=reply_markup,
                    **kwargs
                )
            except:
                plain = re.sub(r'[*_`\[\]()~>#+\-=|{}.!\\]', '', clean_text)
                if len(plain) > 4096:
                    plain = plain[:4093] + "..."
                return await bot.send_message(
                    chat_id=chat_id,
                    text=plain,
                    reply_markup=reply_markup,
                    **kwargs
                )
        raise

async def safe_edit_markdown(query, text: str, reply_markup=None, **kwargs):
    if not query or not query.message:
        return None
    clean_text = sanitize_text(text)
    try:
        escaped = escape_markdown_v2(clean_text)
        if len(escaped) > 4096:
            escaped = escaped[:4093] + "..."
        return await query.edit_message_text(
            text=escaped,
            parse_mode='MarkdownV2',
            reply_markup=reply_markup,
            **kwargs
        )
    except Exception as e:
        if "can't parse entities" in str(e).lower():
            try:
                html_text = clean_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                if len(html_text) > 4096:
                    html_text = html_text[:4093] + "..."
                return await query.edit_message_text(
                    text=html_text,
                    parse_mode='HTML',
                    reply_markup=reply_markup,
                    **kwargs
                )
            except:
                plain = re.sub(r'[*_`\[\]()~>#+\-=|{}.!\\]', '', clean_text)
                if len(plain) > 4096:
                    plain = plain[:4093] + "..."
                return await query.edit_message_text(
                    text=plain,
                    reply_markup=reply_markup,
                    **kwargs
                )
        elif "message is not modified" in str(e).lower():
            try:
                await query.answer("✅ تم التحديث")
            except:
                pass
            return None
        raise

async def safe_send_error(bot, chat_id: int, text: str):
    try:
        return await safe_send_markdown(bot, chat_id, text)
    except:
        plain_text = re.sub(r'[*_`\[\]()~>#+\-=|{}.!\\]', '', text)
        return await bot.send_message(chat_id=chat_id, text=plain_text[:4000])

async def safe_send_long_message(bot, chat_id: int, text: str, reply_markup=None, max_length: int = 4000):
    if len(text) <= max_length:
        return await safe_send_markdown(bot, chat_id, text, reply_markup)
    parts = []
    current_part = ""
    for line in text.split('\n'):
        if len(current_part) + len(line) + 1 > max_length:
            parts.append(current_part)
            current_part = line
        else:
            current_part += "\n" + line if current_part else line
    if current_part:
        parts.append(current_part)
    first = True
    for part in parts:
        if first and reply_markup:
            await safe_send_markdown(bot, chat_id, part, reply_markup)
            first = False
        else:
            await safe_send_markdown(bot, chat_id, part)
        await asyncio.sleep(0.5)
    return None

# ===================== دوال أخرى (مترجم، إلخ) =====================
class AsyncTranslator:
    def __init__(self):
        self.session = None

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
        try:
            session = await self.get_session()
            url = "https://translate.googleapis.com/translate_a/single"
            params = {
                "client": "gtx",
                "sl": "auto",
                "tl": target,
                "dt": "t",
                "q": text
            }
            async with session.get(url, params=params, timeout=10) as resp:
                data = await resp.json()
                translated = data[0][0][0] if data and data[0] and data[0][0] else text
                await _translation_cache.set(cache_key, translated)
                return translated
        except:
            return text

smart_translator = AsyncTranslator()

async def translate_text(text: str, target_lang: str, source_lang: str = 'auto') -> str:
    return await smart_translator.translate(text, target_lang)

# ===================== دوال القوائم والأزرار =====================
def get_advanced_group_actions_keyboard(chat_id: int):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from constants import CallbackData
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
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
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
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from constants import CallbackData
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
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from constants import CallbackData
    # هذه دالة ستستخدم get_text من نظام اللغات، سنستدعيها لاحقاً
    # لكن سنبقيها هنا للهيكل
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
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from constants import CallbackData
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"{CallbackData.BANNED_WORDS_ADD_PREFIX}{chat_id}"),
         InlineKeyboardButton("📋 عرض الكلمات", callback_data=f"{CallbackData.BANNED_WORDS_LIST_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=f"{CallbackData.BANNED_WORDS_REMOVE_PREFIX}{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

def get_replies_keyboard():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from constants import CallbackData
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة رد", callback_data=CallbackData.ADMIN_ADD_REPLY),
         InlineKeyboardButton("📋 عرض الردود", callback_data=CallbackData.ADMIN_LIST_REPLIES)],
        [InlineKeyboardButton("🗑️ حذف رد", callback_data=CallbackData.ADMIN_DEL_REPLY),
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])

def get_auto_reply_keyboard(chat_id: int, settings: dict):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from constants import CallbackData
    status_text = "🟢 مفعل" if settings['enabled'] else "🔴 معطل"
    admin_text = "👑 مشرفين فقط" if settings['only_admins'] else "👥 الجميع"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📝 الردود التلقائية: {status_text}",
            callback_data=f"{CallbackData.AUTO_REPLY_TOGGLE_PREFIX}{chat_id}"
        )],
        [InlineKeyboardButton(
            f"👥 المستخدمون: {admin_text}",
            callback_data=f"{CallbackData.AUTO_REPLY_ADMINS_PREFIX}{chat_id}"
        )],
        [InlineKeyboardButton(
            "🔄 إعادة تعيين الردود",
            callback_data=f"{CallbackData.AUTO_REPLY_RESET_PREFIX}{chat_id}"
        )],
        [InlineKeyboardButton(
            "📊 إحصائيات الردود",
            callback_data=f"{CallbackData.AUTO_REPLY_STATS_PREFIX}{chat_id}"
        )],
        [InlineKeyboardButton(
            "🔙 رجوع",
            callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}"
        )]
    ])

def get_user_auto_reply_keyboard(user_id: int, enabled: bool):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from constants import CallbackData
    status_text = "🟢 مفعل" if enabled else "🔴 معطل"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📝 الردود التلقائية: {status_text}",
            callback_data=f"{CallbackData.USER_AUTO_REPLY_TOGGLE_PREFIX}{user_id}"
        )],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])

def get_banned_words_admin_keyboard():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from constants import CallbackData
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة عامة", callback_data=CallbackData.ADMIN_ADD_BANNED_WORD),
         InlineKeyboardButton("📋 عرض الكلمات", callback_data=CallbackData.ADMIN_LIST_BANNED_WORDS)],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=CallbackData.ADMIN_REMOVE_BANNED_WORD),
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])

def penalty_keyboard(chat_id: int):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from constants import CallbackData
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 طرد", callback_data=f"{CallbackData.PENALTY_KICK}:{chat_id}"),
         InlineKeyboardButton("🛑 حظر", callback_data=f"{CallbackData.PENALTY_BAN}:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم", callback_data=f"{CallbackData.PENALTY_MUTE}:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

def mute_duration_keyboard(chat_id: int):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from constants import CallbackData
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

# ===================== دوال كشف الروابط والإشارات =====================
def contains_link(text: str) -> bool:
    return bool(re.search(r'(https?://|www\.|@\w+\.)', text))

def contains_mention(text: str) -> bool:
    return bool(re.search(r'@\w+', text))

# ===================== دوال الحصول على استخدام الرام =====================
def get_ram_usage():
    try:
        import psutil
        return {'percent': psutil.virtual_memory().percent}
    except:
        return {'percent': 0}

# ===================== دوال فحص الصحة =====================
async def check_database_health():
    try:
        from database import execute_db
        async def _check(conn):
            await conn.execute("SELECT 1")
        await execute_db(_check)
        return True
    except:
        return False

async def check_telegram_health():
    # سيتم تمرير bot لاحقاً
    return True

# ===================== دوال تنظيف نقاط المستخدمين =====================
user_points_last_hour = {}

async def cleanup_points_cache():
    while True:
        await asyncio.sleep(3600)
        now = time_module.time()
        to_delete = [uid for uid, (_, ts) in user_points_last_hour.items() if now - ts > 3600]
        for uid in to_delete:
            del user_points_last_hour[uid]

# ===================== دوال بناء لوحة أيام الأسبوع =====================
async def build_days_keyboard(user_id: int, context):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from constants import CallbackData
    selected = context.user_data.get('selected_days', [])
    day_names = ['الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
    keyboard = []
    for i, name in enumerate(day_names):
        status = "✅" if i in selected else "⬜"
        keyboard.append([InlineKeyboardButton(f"{status} {name}", callback_data=f"{CallbackData.SCHEDULE_DAY_SELECT_PREFIX}{i}")])
    keyboard.append([InlineKeyboardButton("💾 حفظ", callback_data=CallbackData.SCHEDULE_SAVE_DAYS)])
    keyboard.append([InlineKeyboardButton("🔙 إلغاء", callback_data=CallbackData.BACK)])
    return InlineKeyboardMarkup(keyboard)

# ===================== دوال التحقق من صلاحيات البوت =====================
async def check_bot_permissions(bot, chat_id: int) -> tuple:
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        if me.status not in ['administrator', 'creator']:
            return False, "البوت ليس مشرفاً"
        if not me.can_post_messages:
            return False, "البوت لا يملك صلاحية النشر"
        return True, ""
    except:
        return False, "فشل التحقق من صلاحيات البوت"

# ===================== دالة معالجة الأخطاء العالمية =====================
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
        print(log_msg)
        traceback.print_exc()
        return error_id

    def log_access(self, user_id, action, details=None):
        log_msg = f"User: {user_id} - Action: {action}"
        if details:
            log_msg += f" - {json.dumps(details, default=str)[:100]}"
        print(log_msg)

    def log_security(self, event, user_id, details=None, severity="INFO"):
        log_msg = f"[{severity}] {event} - User: {user_id}"
        if details:
            log_msg += f" - {json.dumps(details, default=str)[:200]}"
        print(log_msg)

advanced_logger = AdvancedLogger()
log_error = advanced_logger.log_error

# ===================== دوال الـ Rate Limiting =====================
class RateLimiter:
    def __init__(self):
        self.requests = defaultdict(list)
        self.lock = asyncio.Lock()

    async def check_rate_limit(self, user_id: int, action: str, max_requests: int, time_window: int) -> bool:
        async with self.lock:
            key = f"{user_id}:{action}"
            now = time_module.time()
            self.requests[key] = [t for t in self.requests[key] if now - t < time_window]
            if len(self.requests[key]) >= max_requests:
                return False
            self.requests[key].append(now)
            return True

rate_limiter = RateLimiter()

# ===================== دالة safe_int مكررة للتأكيد =====================
# (موجودة بالفعل)

# ===================== دوال إضافية =====================
def parse_days_of_week_safe(days_str: str) -> list:
    if not days_str:
        return []
    try:
        days = json.loads(days_str)
        if isinstance(days, list):
            return [int(d) for d in days if isinstance(d, (int, str)) and str(d).isdigit()]
        return []
    except:
        return []

def parse_dates_safe(dates_str: str) -> list:
    if not dates_str:
        return []
    try:
        dates = json.loads(dates_str)
        if isinstance(dates, list):
            return [str(d) for d in dates if isinstance(d, str)]
        return []
    except:
        return []

# ===================== دالة health_check_handler =====================
async def health_check_handler(request):
    from aiohttp import web
    return web.json_response({'status': 'ok', 'version': '19.3.3'})

