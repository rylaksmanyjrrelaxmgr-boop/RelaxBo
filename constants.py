#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
مكتبة الدوال المساعدة - نسخة محسّنة ومنظمة
المميزات:
- تنظيم هرمي للدوال حسب الوظيفة
- معالجة أخطاء موحدة
- أداء محسن مع تخزين مؤقت ذكي
- توثيق كامل بالعربية
- دعم كامل للأنماط البرمجية الحديثة
"""

import re
import json
import time
import secrets
import base64
import hashlib
import hmac
import os
import sys
import gc
import asyncio
import random
import socket
import logging
import traceback
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import (
    Optional, List, Dict, Tuple, Any, Union, 
    Callable, Awaitable, TypeVar, Generic
)
from functools import lru_cache, wraps
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, field

# ============================================================================
# استيراد الاعتماديات الخارجية
# ============================================================================

try:
    import bleach
    BLEACH_AVAILABLE = True
except ImportError:
    BLEACH_AVAILABLE = False

try:
    from cachetools import TTLCache, LRUCache
    CACHETOOLS_AVAILABLE = True
except ImportError:
    CACHETOOLS_AVAILABLE = False

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

# استيراد الإعدادات
from constants import (
    ENCRYPTION_KEY, BACKUP_ENCRYPTION_KEY, DB_ENCRYPTION,
    DATA_PATH, TEMP_PATH, SECURITY_LOG, ERROR_LOG, ACCESS_LOG,
    LOG_PATH, DB_PATH, SUPPORTED_LANGUAGES, PRIMARY_OWNER_ID,
    NSFW_CACHE, NSFW_CACHE_TTL, user_points_last_hour,
    WEB_PORT, user_language
)

# ============================================================================
# إعداد التسجيل
# ============================================================================

logger = logging.getLogger(__name__)

# ============================================================================
# فئات مساعدة
# ============================================================================

T = TypeVar('T')

@dataclass
class CacheEntry(Generic[T]):
    """إدخال في الذاكرة المؤقتة"""
    value: T
    timestamp: float = field(default_factory=time.time)
    
    def is_expired(self, ttl: int) -> bool:
        """التحقق من انتهاء الصلاحية"""
        return time.time() - self.timestamp > ttl

class SimpleCache(Generic[T]):
    """ذاكرة مؤقتة بسيطة مع TTL"""
    
    def __init__(self, maxsize: int = 1000, ttl: int = 300):
        self.maxsize = maxsize
        self.ttl = ttl
        self._cache: OrderedDict = OrderedDict()
    
    def _cleanup_expired(self):
        """تنظيف العناصر منتهية الصلاحية"""
        expired = [
            k for k, v in self._cache.items() 
            if v.is_expired(self.ttl)
        ]
        for k in expired:
            del self._cache[k]
    
    def get(self, key: Any, default: T = None) -> Optional[T]:
        """الحصول على قيمة من الذاكرة المؤقتة"""
        self._cleanup_expired()
        if key in self._cache:
            entry = self._cache[key]
            if not entry.is_expired(self.ttl):
                # تحديث الموقع في OrderedDict
                self._cache.move_to_end(key)
                return entry.value
            del self._cache[key]
        return default
    
    def set(self, key: Any, value: T):
        """تخزين قيمة في الذاكرة المؤقتة"""
        if len(self._cache) >= self.maxsize:
            # حذف أقدم عنصر
            self._cache.popitem(last=False)
        self._cache[key] = CacheEntry(value)
    
    def clear(self):
        """مسح الذاكرة المؤقتة"""
        self._cache.clear()
    
    def __contains__(self, key: Any) -> bool:
        return self.get(key) is not None

# ============================================================================
# 1. دوال معالجة النصوص والأمان
# ============================================================================

class TextProcessor:
    """معالج النصوص المتقدم"""
    
    # أحرف MarkdownV2 الخاصة
    MARKDOWN_SPECIAL_CHARS = r'_*[]()~`>#+\-=|{}.!'
    
    # أحرف التحكم المخفية
    HIDDEN_CHARS_PATTERN = re.compile(
        r'[\u200b\u200c\u200d\u2060\uFEFF\u202a\u202b\u202c\u202d\u202e\ufeff\ufffc]'
    )
    
    @staticmethod
    def escape_markdown_v2(text: str) -> str:
        """
        تهريب أحرف MarkdownV2 الخاصة
        
        المعاملات:
            text: النص المراد تهريبه
            
        النتيجة:
            النص بعد تهريب الأحرف الخاصة
        """
        if not text:
            return ""
        for char in TextProcessor.MARKDOWN_SPECIAL_CHARS:
            text = text.replace(char, f'\\{char}')
        return text
    
    @staticmethod
    def clean_hidden_chars(text: str) -> str:
        """إزالة الأحرف الخفية والتحكم"""
        if not text:
            return ""
        return TextProcessor.HIDDEN_CHARS_PATTERN.sub('', text)
    
    @staticmethod
    def sanitize_html(text: str, max_length: int = 4096, 
                     allowed_tags: Optional[List[str]] = None) -> str:
        """
        تنظيف النص من HTML غير الآمن
        
        المعاملات:
            text: النص المراد تنظيفه
            max_length: الطول الأقصى المسموح
            allowed_tags: قائمة الوسوم المسموحة
            
        النتيجة:
            النص المنظف
        """
        if not text:
            return ""
        
        if BLEACH_AVAILABLE and allowed_tags is not None:
            try:
                default_tags = ['b', 'i', 'u', 's', 'a', 'code', 'pre', 'strong', 'em']
                tags = allowed_tags or default_tags
                text = bleach.clean(
                    text,
                    tags=tags,
                    attributes={'a': ['href', 'title']},
                    styles=[],
                    strip=True
                )
            except Exception as e:
                logger.warning(f"فشل تنظيف HTML: {e}")
        else:
            # إزالة جميع وسوم HTML
            text = re.sub(r'<[^>]+>', '', text)
        
        # تقليم النص
        if len(text) > max_length:
            text = text[:max_length - 3] + "..."
        
        return text
    
    @staticmethod
    def truncate_text(text: str, max_length: int = 4096, 
                     suffix: str = "...") -> str:
        """تقليم النص لطول محدد مع إضافة لاحقة"""
        if not text or len(text) <= max_length:
            return text
        return text[:max_length - len(suffix)] + suffix
    
    @classmethod
    def prepare_for_telegram(cls, text: str, parse_mode: str = 'MarkdownV2',
                            max_length: int = 4096) -> str:
        """
        تحضير النص للإرسال عبر تيليجرام
        
        المعاملات:
            text: النص الأصلي
            parse_mode: وضع التنسيق (MarkdownV2, HTML, None)
            max_length: الطول الأقصى
            
        النتيجة:
            النص المجهز
        """
        text = cls.clean_hidden_chars(text)
        
        if parse_mode == 'MarkdownV2':
            text = cls.escape_markdown_v2(text)
        elif parse_mode == 'HTML':
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        return cls.truncate_text(text, max_length)

# ============================================================================
# 2. دوال التشفير والأمان
# ============================================================================

class CryptoHelper:
    """مساعد التشفير المتقدم"""
    
    CHUNK_SIZE = 64 * 1024  # 64 كيلوبايت
    
    @staticmethod
    def generate_token(length: int = 32) -> str:
        """توليد رمز آمن"""
        return secrets.token_hex(length)
    
    @staticmethod
    def generate_password(length: int = 16) -> str:
        """توليد كلمة مرور قوية"""
        return secrets.token_urlsafe(length)
    
    @staticmethod
    def hash_data(data: str, algorithm: str = 'sha256') -> str:
        """تجزئة البيانات"""
        if algorithm == 'sha256':
            return hashlib.sha256(data.encode()).hexdigest()
        elif algorithm == 'md5':
            return hashlib.md5(data.encode()).hexdigest()
        else:
            raise ValueError(f"خوارزمية غير مدعومة: {algorithm}")
    
    @classmethod
    def stream_encrypt(cls, source: Path, destination: Path, 
                      cipher: Fernet) -> None:
        """
        تشفير ملف بشكل تدفقي
        
        المعاملات:
            source: مسار الملف المصدر
            destination: مسار الملف الهدف
            cipher: كائن Fernet للتشفير
        """
        try:
            with open(source, 'rb') as f_in, open(destination, 'wb') as f_out:
                while True:
                    chunk = f_in.read(cls.CHUNK_SIZE)
                    if not chunk:
                        break
                    encrypted = cipher.encrypt(chunk)
                    f_out.write(encrypted)
            logger.info(f"✅ تم تشفير الملف: {source.name}")
        except Exception as e:
            logger.error(f"❌ فشل تشفير الملف: {e}")
            raise
    
    @classmethod
    def stream_decrypt(cls, source: Path, destination: Path,
                      cipher: Fernet) -> None:
        """
        فك تشفير ملف بشكل تدفقي
        
        المعاملات:
            source: مسار الملف المشفر
            destination: مسار الملف الهدف
            cipher: كائن Fernet للتشفير
        """
        try:
            with open(source, 'rb') as f_in, open(destination, 'wb') as f_out:
                while True:
                    chunk = f_in.read(cls.CHUNK_SIZE)
                    if not chunk:
                        break
                    decrypted = cipher.decrypt(chunk)
                    f_out.write(decrypted)
            logger.info(f"✅ تم فك تشفير الملف: {source.name}")
        except Exception as e:
            logger.error(f"❌ فشل فك تشفير الملف: {e}")
            raise

# ============================================================================
# 3. دوال الوقت والتاريخ
# ============================================================================

class TimeHelper:
    """مساعد الوقت والتاريخ"""
    
    MECCA_OFFSET = timedelta(hours=3)
    
    @staticmethod
    def utc_now() -> datetime:
        """الحصول على الوقت الحالي UTC"""
        return datetime.now(timezone.utc).replace(tzinfo=None)
    
    @staticmethod
    def mecca_now() -> datetime:
        """الحصول على الوقت الحالي في مكة المكرمة"""
        return TimeHelper.utc_now() + TimeHelper.MECCA_OFFSET
    
    @staticmethod
    def to_iso(dt: datetime) -> str:
        """تحويل التاريخ إلى صيغة ISO"""
        if dt is None:
            return ""
        return dt.isoformat()
    
    @staticmethod
    def to_naive(dt: datetime) -> datetime:
        """إزالة معلومات المنطقة الزمنية"""
        if dt is None:
            return None
        if hasattr(dt, 'tzinfo') and dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt
    
    @classmethod
    def utc_to_mecca(cls, dt: datetime) -> datetime:
        """تحويل من UTC إلى توقيت مكة"""
        if dt is None:
            return None
        dt = cls.to_naive(dt)
        return dt + cls.MECCA_OFFSET
    
    @classmethod
    def mecca_to_utc(cls, dt: datetime) -> datetime:
        """تحويل من توقيت مكة إلى UTC"""
        if dt is None:
            return None
        dt = cls.to_naive(dt)
        return dt - cls.MECCA_OFFSET
    
    @staticmethod
    def format_duration(seconds: int) -> str:
        """تنسيق المدة الزمنية"""
        if seconds < 60:
            return f"{seconds} ثانية"
        elif seconds < 3600:
            return f"{seconds // 60} دقيقة"
        elif seconds < 86400:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours} ساعة و {minutes} دقيقة"
        else:
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            return f"{days} يوم و {hours} ساعة"
    
    @staticmethod
    def parse_duration(text: str) -> Optional[int]:
        """تحليل المدة الزمنية من النص"""
        patterns = {
            r'(\d+)\s*ثانية': 1,
            r'(\d+)\s*دقيقة': 60,
            r'(\d+)\s*ساعة': 3600,
            r'(\d+)\s*يوم': 86400,
            r'(\d+)\s*أسبوع': 604800,
        }
        
        for pattern, multiplier in patterns.items():
            match = re.search(pattern, text)
            if match:
                return int(match.group(1)) * multiplier
        return None

# ============================================================================
# 4. دوال الإرسال الآمنة
# ============================================================================

class MessageSender:
    """مرسل الرسائل الآمن"""
    
    def __init__(self, bot):
        self.bot = bot
        self.text_processor = TextProcessor()
    
    async def send_message(self, chat_id: int, text: str,
                          parse_mode: str = 'MarkdownV2',
                          reply_markup=None,
                          max_retries: int = 3,
                          **kwargs) -> Optional[Any]:
        """
        إرسال رسالة بأمان مع إعادة المحاولة
        
        المعاملات:
            chat_id: معرف المحادثة
            text: نص الرسالة
            parse_mode: وضع التنسيق
            reply_markup: لوحة المفاتيح
            max_retries: عدد محاولات الإعادة
            
        النتيجة:
            كائن الرسالة أو None
        """
        if not text:
            return None
        
        # تجهيز النص
        processed_text = self.text_processor.prepare_for_telegram(
            text, parse_mode
        )
        
        # محاولة الإرسال
        for attempt in range(max_retries):
            try:
                # المحاولة الأولى: استخدام وضع التنسيق المطلوب
                if attempt == 0:
                    return await self.bot.send_message(
                        chat_id=chat_id,
                        text=processed_text,
                        parse_mode=parse_mode,
                        reply_markup=reply_markup,
                        **kwargs
                    )
                # المحاولة الثانية: HTML
                elif attempt == 1 and parse_mode != 'HTML':
                    html_text = self.text_processor.prepare_for_telegram(
                        text, 'HTML'
                    )
                    return await self.bot.send_message(
                        chat_id=chat_id,
                        text=html_text,
                        parse_mode='HTML',
                        reply_markup=reply_markup,
                        **kwargs
                    )
                # المحاولة الثالثة: نص عادي
                else:
                    plain_text = re.sub(
                        r'[*_`\[\]()~>#+\-=|{}.!\\]', '', text
                    )
                    return await self.bot.send_message(
                        chat_id=chat_id,
                        text=plain_text[:4000],
                        reply_markup=reply_markup,
                        **kwargs
                    )
            except Exception as e:
                error_msg = str(e).lower()
                if "can't parse entities" not in error_msg:
                    if attempt == max_retries - 1:
                        raise
                    await asyncio.sleep(0.5)
        
        return None
    
    async def send_long_message(self, chat_id: int, text: str,
                               max_length: int = 4000,
                               reply_markup=None) -> None:
        """
        إرسال رسالة طويلة بتقسيمها
        
        المعاملات:
            chat_id: معرف المحادثة
            text: النص الكامل
            max_length: الحد الأقصى لكل جزء
            reply_markup: لوحة المفاتيح (للجزء الأول فقط)
        """
        if len(text) <= max_length:
            await self.send_message(chat_id, text, reply_markup=reply_markup)
            return
        
        # تقسيم النص
        parts = []
        current_part = []
        current_length = 0
        
        for line in text.split('\n'):
            line_length = len(line) + 1  # +1 للسطر الجديد
            if current_length + line_length > max_length and current_part:
                parts.append('\n'.join(current_part))
                current_part = [line]
                current_length = line_length
            else:
                current_part.append(line)
                current_length += line_length
        
        if current_part:
            parts.append('\n'.join(current_part))
        
        # إرسال الأجزاء
        for i, part in enumerate(parts):
            if i == 0 and reply_markup:
                await self.send_message(chat_id, part, reply_markup=reply_markup)
            else:
                await self.send_message(chat_id, part)
            await asyncio.sleep(0.5)
    
    async def edit_message(self, query, text: str,
                          parse_mode: str = 'MarkdownV2',
                          reply_markup=None,
                          max_retries: int = 3) -> Optional[Any]:
        """
        تعديل رسالة بأمان
        
        المعاملات:
            query: كائن الاستعلام
            text: النص الجديد
            parse_mode: وضع التنسيق
            reply_markup: لوحة المفاتيح
            max_retries: عدد المحاولات
            
        النتيجة:
            كائن الرسالة المعدلة أو None
        """
        if not query or not query.message:
            return None
        
        processed_text = self.text_processor.prepare_for_telegram(
            text, parse_mode
        )
        
        for attempt in range(max_retries):
            try:
                return await query.edit_message_text(
                    text=processed_text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
            except Exception as e:
                error_msg = str(e).lower()
                if "message is not modified" in error_msg:
                    await query.answer("✅ تم التحديث")
                    return None
                if "can't parse entities" in error_msg:
                    if attempt == 0 and parse_mode != 'HTML':
                        processed_text = self.text_processor.prepare_for_telegram(
                            text, 'HTML'
                        )
                        continue
                    else:
                        plain_text = re.sub(
                            r'[*_`\[\]()~>#+\-=|{}.!\\]', '', text
                        )
                        return await query.edit_message_text(
                            text=plain_text[:4000],
                            reply_markup=reply_markup
                        )
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(0.5)
        
        return None
    
    async def send_error(self, chat_id: int, error_text: str) -> None:
        """إرسال رسالة خطأ"""
        try:
            await self.send_message(chat_id, f"❌ {error_text}")
        except Exception as e:
            logger.error(f"فشل إرسال رسالة خطأ: {e}")

# ============================================================================
# 5. دوال التخزين المؤقت
# ============================================================================

class CacheManager:
    """مدير التخزين المؤقت المتقدم"""
    
    def __init__(self):
        # إنشاء الذاكرات المؤقتة
        if CACHETOOLS_AVAILABLE:
            self.admin_cache = TTLCache(maxsize=1000, ttl=300)
            self.security_cache = TTLCache(maxsize=500, ttl=60)
            self.auth_cache = TTLCache(maxsize=1000, ttl=300)
        else:
            self.admin_cache = SimpleCache(maxsize=1000, ttl=300)
            self.security_cache = SimpleCache(maxsize=500, ttl=60)
            self.auth_cache = SimpleCache(maxsize=1000, ttl=300)
        
        self.translation_cache = SimpleCache(maxsize=500, ttl=3600)
    
    async def get_or_set(self, cache: Any, key: Any, 
                        factory: Callable[[], Awaitable[Any]]) -> Any:
        """
        الحصول على قيمة من الذاكرة المؤقتة أو إنشائها
        
        المعاملات:
            cache: الذاكرة المؤقتة
            key: المفتاح
            factory: دالة إنشاء القيمة
            
        النتيجة:
            القيمة المطلوبة
        """
        if key in cache:
            return cache.get(key)
        
        value = await factory()
        if value is not None:
            cache.set(key, value)
        return value
    
    def clear_all(self):
        """مسح جميع الذاكرات المؤقتة"""
        self.admin_cache.clear()
        self.security_cache.clear()
        self.auth_cache.clear()
        self.translation_cache.clear()
        gc.collect()
        logger.info("🧹 تم مسح جميع الذاكرات المؤقتة")

# ============================================================================
# 6. دوال الصلاحيات
# ============================================================================

class AuthChecker:
    """مدقق الصلاحيات"""
    
    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
    
    async def check_group_admin(self, bot, chat_id: int, 
                               user_id: int) -> bool:
        """
        التحقق من صلاحيات المستخدم في المجموعة
        
        المعاملات:
            bot: كائن البوت
            chat_id: معرف المجموعة
            user_id: معرف المستخدم
            
        النتيجة:
            True إذا كان المستخدم مصرحاً
        """
        # المالك الرئيسي لديه صلاحية كاملة
        if user_id == PRIMARY_OWNER_ID:
            return True
        
        # التحقق من الذاكرة المؤقتة
        cache_key = f"auth_{chat_id}_{user_id}"
        cached = self.cache.auth_cache.get(cache_key)
        if cached is not None:
            return cached
        
        # التحقق من قاعدة البيانات
        authorized = False
        try:
            from database import (
                db_is_real_admin, 
                db_is_hidden_owner, 
                db_is_hidden_admin
            )
            
            if await db_is_real_admin(chat_id, user_id):
                authorized = True
            elif await db_is_hidden_owner(chat_id, user_id):
                authorized = True
            elif await db_is_hidden_admin(chat_id, user_id):
                authorized = True
        except Exception as e:
            logger.error(f"خطأ في التحقق من الصلاحيات: {e}")
        
        # تخزين النتيجة
        self.cache.auth_cache.set(cache_key, authorized)
        return authorized
    
    def invalidate_cache(self, chat_id: int = None, 
                        user_id: int = None):
        """
        إبطال الذاكرة المؤقتة للصلاحيات
        
        المعاملات:
            chat_id: معرف المجموعة (اختياري)
            user_id: معرف المستخدم (اختياري)
        """
        if chat_id is not None and user_id is not None:
            key = f"auth_{chat_id}_{user_id}"
            self.cache.auth_cache.set(key, None)
        elif chat_id is not None:
            # إبطال جميع صلاحيات المجموعة
            keys_to_remove = [
                k for k in self.cache.auth_cache._cache.keys()
                if k.startswith(f"auth_{chat_id}_")
            ]
            for k in keys_to_remove:
                self.cache.auth_cache.set(k, None)
        else:
            self.cache.auth_cache.clear()

# ============================================================================
# 7. دوال الترجمة
# ============================================================================

class SmartTranslator:
    """مترجم ذكي مع تخزين مؤقت"""
    
    def __init__(self, cache_manager: CacheManager):
        self.cache = cache_manager
        self._session = None
        self._pending: Dict[str, List[asyncio.Future]] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    async def _get_session(self):
        """الحصول على جلسة HTTP"""
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def translate(self, text: str, target_lang: str,
                       source_lang: str = 'auto') -> str:
        """
        ترجمة نص إلى اللغة المستهدفة
        
        المعاملات:
            text: النص المراد ترجمته
            target_lang: اللغة المستهدفة
            source_lang: اللغة المصدر
            
        النتيجة:
            النص المترجم
        """
        if not text or target_lang not in SUPPORTED_LANGUAGES:
            return text
        
        # التحقق من الذاكرة المؤقتة
        cache_key = hashlib.md5(
            f"{text}_{target_lang}_{source_lang}".encode()
        ).hexdigest()
        
        cached = self.cache.translation_cache.get(cache_key)
        if cached:
            return cached
        
        # منع الترجمة المتكررة لنفس النص
        async with self._lock:
            if text in self._pending:
                future = asyncio.Future()
                self._pending[text].append(future)
                return await future
            self._pending[text] = []
        
        try:
            # تنفيذ الترجمة
            session = await self._get_session()
            url = "https://translate.googleapis.com/translate_a/single"
            params = {
                "client": "gtx",
                "sl": source_lang,
                "tl": target_lang,
                "dt": "t",
                "q": text
            }
            
            async with session.get(url, params=params, timeout=10) as resp:
                data = await resp.json()
                translated = (
                    data[0][0][0] 
                    if data and data[0] and data[0][0] 
                    else text
                )
            
            # تخزين في الذاكرة المؤقتة
            self.cache.translation_cache.set(cache_key, translated)
            
            # إكمال الطلبات المعلقة
            for future in self._pending[text]:
                if not future.done():
                    future.set_result(translated)
            
            return translated
            
        except Exception as e:
            logger.error(f"خطأ في الترجمة: {e}")
            # إعادة النص الأصلي في حالة الفشل
            for future in self._pending[text]:
                if not future.done():
                    future.set_result(text)
            return text
        finally:
            if text in self._pending:
                del self._pending[text]
    
    async def close(self):
        """إغلاق الجلسة"""
        if self._session:
            await self._session.close()
            self._session = None

# ============================================================================
# 8. دوال التحقق والمراقبة
# ============================================================================

class SystemMonitor:
    """مراقب النظام"""
    
    @staticmethod
    def get_memory_usage() -> Dict[str, Any]:
        """الحصول على معلومات استخدام الذاكرة"""
        try:
            import psutil
            memory = psutil.virtual_memory()
            return {
                'percent': memory.percent,
                'used': memory.used,
                'available': memory.available,
                'total': memory.total
            }
        except ImportError:
            return {'percent': 0, 'error': 'psutil غير متوفر'}
    
    @staticmethod
    def get_cpu_usage() -> float:
        """الحصول على استخدام المعالج"""
        try:
            import psutil
            return psutil.cpu_percent(interval=1)
        except ImportError:
            return 0.0
    
    @staticmethod
    async def check_database_health() -> bool:
        """التحقق من صحة قاعدة البيانات"""
        try:
            from database import execute_db
            
            async def _check(conn):
                await conn.execute("SELECT 1")
            
            await execute_db(_check)
            return True
        except Exception as e:
            logger.error(f"فشل فحص صحة قاعدة البيانات: {e}")
            return False
    
    @staticmethod
    def optimize_memory():
        """تحسين استخدام الذاكرة"""
        try:
            gc.collect()
            return True
        except Exception as e:
            logger.warning(f"فشل تحسين الذاكرة: {e}")
            return False

# ============================================================================
# 9. دوال الـ Rate Limiting
# ============================================================================

class RateLimiter:
    """محدد معدل الطلبات"""
    
    def __init__(self):
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    async def check(self, user_id: int, action: str,
                   max_requests: int, time_window: int) -> bool:
        """
        التحقق من معدل الطلبات
        
        المعاملات:
            user_id: معرف المستخدم
            action: نوع الإجراء
            max_requests: الحد الأقصى للطلبات
            time_window: النافذة الزمنية بالثواني
            
        النتيجة:
            True إذا كان الطلب مسموحاً
        """
        async with self._lock:
            key = f"{user_id}:{action}"
            now = time.time()
            
            # تنظيف الطلبات القديمة
            self._requests[key] = [
                t for t in self._requests[key]
                if now - t < time_window
            ]
            
            # التحقق من الحد
            if len(self._requests[key]) >= max_requests:
                return False
            
            # تسجيل الطلب
            self._requests[key].append(now)
            return True
    
    def get_remaining(self, user_id: int, action: str,
                     max_requests: int, time_window: int) -> int:
        """الحصول على عدد الطلبات المتبقية"""
        key = f"{user_id}:{action}"
        now = time.time()
        recent = [t for t in self._requests[key] if now - t < time_window]
        return max(0, max_requests - len(recent))

# ============================================================================
# 10. دوال بناء لوحات المفاتيح
# ============================================================================

class KeyboardBuilder:
    """باني لوحات المفاتيح"""
    
    @staticmethod
    def create_inline_keyboard(buttons: List[List[Tuple[str, str]]],
                              row_width: int = 2) -> Any:
        """
        إنشاء لوحة مفاتيح مضمّنة
        
        المعاملات:
            buttons: قائمة الأزرار (نص, بيانات الكولباك)
            row_width: عدد الأزرار في الصف
            
        النتيجة:
            كائن InlineKeyboardMarkup
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = []
        for i in range(0, len(buttons), row_width):
            row = []
            for text, callback_data in buttons[i:i + row_width]:
                row.append(InlineKeyboardButton(
                    text, callback_data=callback_data
                ))
            keyboard.append(row)
        
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_url_keyboard(buttons: List[Tuple[str, str]],
                          row_width: int = 2) -> Any:
        """
        إنشاء لوحة مفاتيح بروابط
        
        المعاملات:
            buttons: قائمة (نص, رابط)
            row_width: عدد الأزرار في الصف
            
        النتيجة:
            كائن InlineKeyboardMarkup
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        
        keyboard = []
        for i in range(0, len(buttons), row_width):
            row = []
            for text, url in buttons[i:i + row_width]:
                row.append(InlineKeyboardButton(text, url=url))
            keyboard.append(row)
        
        return InlineKeyboardMarkup(keyboard)

# ============================================================================
# 11. مدير الأخطاء المتقدم
# ============================================================================

class ErrorManager:
    """مدير الأخطاء المتقدم"""
    
    def __init__(self):
        self.error_count: Dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()
    
    async def handle_error(self, error: Exception, context: str = "",
                          user_id: Optional[int] = None,
                          notify_admin: bool = False) -> str:
        """
        معالجة خطأ مع تسجيل وإشعار
        
        المعاملات:
            error: كائن الخطأ
            context: سياق الخطأ
            user_id: معرف المستخدم
            notify_admin: إشعار المسؤول
            
        النتيجة:
            معرف الخطأ
        """
        error_id = secrets.token_hex(4)
        
        # تسجيل الخطأ
        log_message = f"[{error_id}] {context}: {error}"
        if user_id:
            log_message = f"User {user_id} - {log_message}"
        
        logger.error(log_message)
        logger.error(traceback.format_exc())
        
        # تحديث عداد الأخطاء
        async with self._lock:
            error_type = type(error).__name__
            self.error_count[error_type] += 1
        
        # إشعار المسؤول
        if notify_admin and PRIMARY_OWNER_ID:
            # سيتم تنفيذه لاحقاً عند توفر كائن البوت
            pass
        
        return error_id
    
    def get_error_stats(self) -> Dict[str, int]:
        """الحصول على إحصائيات الأخطاء"""
        return dict(self.error_count)

# ============================================================================
# التهيئة والتصدير
# ============================================================================

# إنشاء النسخ الرئيسية
cache_manager = CacheManager()
auth_checker = AuthChecker(cache_manager)
smart_translator = SmartTranslator(cache_manager)
system_monitor = SystemMonitor()
rate_limiter = RateLimiter()
keyboard_builder = KeyboardBuilder()
error_manager = ErrorManager()
text_processor = TextProcessor()
crypto_helper = CryptoHelper()
time_helper = TimeHelper()

# دوال مختصرة للاستخدام الشائع
escape_markdown_v2 = text_processor.escape_markdown_v2
clean_text = text_processor.clean_hidden_chars
sanitize_text = text_processor.sanitize_html
utc_now = time_helper.utc_now
mecca_now = time_helper.mecca_now
format_duration = time_helper.format_duration
encrypt_file = crypto_helper.stream_encrypt
decrypt_file = crypto_helper.stream_decrypt
generate_token = crypto_helper.generate_token

# ============================================================================
# دوال مركبة للاستخدام المباشر
# ============================================================================

async def safe_send_markdown(bot, chat_id: int, text: str,
                            reply_markup=None, **kwargs):
    """دالة مختصرة للإرسال الآمن"""
    sender = MessageSender(bot)
    return await sender.send_message(
        chat_id, text, parse_mode='MarkdownV2',
        reply_markup=reply_markup, **kwargs
    )

async def safe_edit_markdown(query, text: str,
                            reply_markup=None, **kwargs):
    """دالة مختصرة للتعديل الآمن"""
    sender = MessageSender(query.bot)
    return await sender.edit_message(
        query, text, parse_mode='MarkdownV2',
        reply_markup=reply_markup, **kwargs
    )

async def translate_text(text: str, target_lang: str,
                        source_lang: str = 'auto') -> str:
    """دالة مختصرة للترجمة"""
    return await smart_translator.translate(text, target_lang, source_lang)

async def check_rate_limit(user_id: int, action: str,
                          max_requests: int, time_window: int) -> bool:
    """دالة مختصرة للتحقق من معدل الطلبات"""
    return await rate_limiter.check(
        user_id, action, max_requests, time_window
    )

# ============================================================================
# دوال مساعدة إضافية
# ============================================================================

def contains_link(text: str) -> bool:
    """التحقق من وجود رابط في النص"""
    url_pattern = re.compile(
        r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*|'
        r'www\.(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*|'
        r'@\w+\.\w+'
    )
    return bool(url_pattern.search(text))

def contains_mention(text: str) -> bool:
    """التحقق من وجود إشارة @ في النص"""
    return bool(re.search(r'@\w{5,}', text))

def parse_json_safe(data: str, default: Any = None) -> Any:
    """تحليل JSON بشكل آمن"""
    if not data:
        return default
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return default

def to_json_safe(data: Any) -> str:
    """تحويل إلى JSON بشكل آمن"""
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return "{}"

def encode_callback(data: str) -> str:
    """تشفير بيانات الكولباك"""
    return urllib.parse.quote(data, safe='')

def decode_callback(data: str) -> str:
    """فك تشفير بيانات الكولباك"""
    return urllib.parse.unquote(data)

def safe_int(value: Any, default: int = 0) -> int:
    """تحويل آمن إلى عدد صحيح"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def safe_float(value: Any, default: float = 0.0) -> float:
    """تحويل آمن إلى عدد عشري"""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

# ============================================================================
# التصدير
# ============================================================================

__all__ = [
    # فئات رئيسية
    'TextProcessor', 'CryptoHelper', 'TimeHelper',
    'MessageSender', 'CacheManager', 'AuthChecker',
    'SmartTranslator', 'SystemMonitor', 'RateLimiter',
    'KeyboardBuilder', 'ErrorManager',
    
    # نسخ جاهزة
    'text_processor', 'crypto_helper', 'time_helper',
    'cache_manager', 'auth_checker', 'smart_translator',
    'system_monitor', 'rate_limiter', 'keyboard_builder',
    'error_manager',
    
    # دوال مختصرة
    'escape_markdown_v2', 'clean_text', 'sanitize_text',
    'utc_now', 'mecca_now', 'format_duration',
    'encrypt_file', 'decrypt_file', 'generate_token',
    'safe_send_markdown', 'safe_edit_markdown',
    'translate_text', 'check_rate_limit',
    'contains_link', 'contains_mention',
    'parse_json_safe', 'to_json_safe',
    'encode_callback', 'decode_callback',
    'safe_int', 'safe_float'
]
