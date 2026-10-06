#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
config.py - إعدادات البوت الأساسية (v6 — Spam Detection Integration)
================================================================================
🆕 v6 (SPAM-DETECTION-V4-INTEGRATION):
    ✅ قسم 13 جديد: Spam Detection Engine (v4.0.0 — 14 طبقة)
        • تفعيل/تعطيل كل طبقة عبر .env
        • إعدادات الطبقات المتقدمة (Video, NSFW, Cipher, Stego, ...)
        • Safe Browsing API key
        • OCR Languages, Audio Whisper, URL enrichment
        • DEBUG_DIAG, DEBUG_SPAM
    ✅ تكامل كامل مع:
        • handlers_message_detectors.py v4.0.0
        • utils.py v7.10.2 (Security Bridge)
        • database_tables.py v7.9.0 (7 أعمدة جديدة)
    ✅ validate() — تحققات إضافية لطبقات الكشف
    ✅ get_detector_env() — helper لتصدير إعدادات الكشف إلى os.environ
    ✅ Properties جديدة: SPAM_DETECTION_AVAILABLE, DETECTION_SUMMARY
    ✅ سجل الإقلاع يُظهر حالة الطبقات

🆕 v5 (REVIEW R4 FIXES):
    🔴 C1  WEBHOOK_SECRET — مُضاف (مطلوب لـ utils.webhook_handler C2)
    🟠 M1-M6 + 🟡 m1-m14

🆕 v4 (إصلاح MAX_GLOBAL_BANNED_WORDS):
    ✅ القيمة الافتراضية: 100 → 10000

🆕 v3 (إعادة تنظيم شاملة):
    ✅ 12 قسم منطقي
    ✅ 100% توافق خلفي مع v2

🆕 v2 (2026-09-24):
    ✅ safe_float() + تحقق WEB_PASSWORD
================================================================================
"""

import os
import re
import logging
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any
from dotenv import load_dotenv

# ═══════════════════════════════════════════════════════════════════
# تحميل .env من مجلد المشروع
# ═══════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# دوال التحويل الآمن
# ═══════════════════════════════════════════════════════════════════

def safe_int(value: str, default: int = 0) -> int:
    """تحويل قيمة نصية إلى رقم صحيح مع إرجاع الافتراضي عند الخطأ."""
    try:
        return int(value.strip())
    except (ValueError, AttributeError, TypeError):
        return default


def safe_float(value: str, default: float = 0.0) -> float:
    """تحويل قيمة نصية إلى رقم عشري مع إرجاع الافتراضي عند الخطأ."""
    try:
        return float(value.strip())
    except (ValueError, AttributeError, TypeError):
        return default


def safe_bool(value: str, default: bool = False) -> bool:
    """تحويل قيمة نصية إلى منطقية."""
    if value is None:
        return default
    return value.strip().lower() in ('true', '1', 'yes', 'on')


def safe_str(value: str, default: str = "", *, single_line: bool = False) -> str:
    """
    إرجاع قيمة نصية نظيفة.
    عند single_line=True يتم طي كل المسافات إلى مسافة واحدة.
    """
    if value is None:
        return default
    s = str(value).strip()
    if single_line:
        s = re.sub(r'\s+', ' ', s)
    return s


def safe_abs_path(value: str, default: str) -> str:
    """توحيد المسارات — يحوّل المسار النسبي إلى مطلق."""
    raw = (value or "").strip()
    if not raw:
        raw = default
    p = Path(raw)
    if not p.is_absolute():
        p = BASE_DIR / p
    return str(p)


def _parse_developer_ids() -> Tuple[int, ...]:
    """إزالة shadowing لـ`id()` builtin + إرجاع tuple."""
    raw = os.getenv("DEVELOPER_IDS", "") or ""
    result: List[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        uid = safe_int(token, 0)
        if uid > 0:
            result.append(uid)
    return tuple(result)


# ═══════════════════════════════════════════════════════════════════
# AppConfig — الإعدادات الرئيسية
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AppConfig:
    """
    إعدادات البوت — مقسّمة إلى 13 قسم منطقي:

      1.  الهوية والملاك        (من أنا؟ من يملكني؟)
      2.  البيئة والتشخيص       (production/development)
      3.  قاعدة البيانات        (URL, pool, timeouts)
      4.  النشر التلقائي        (المحرّك الأساسي للبوت)
      5.  النسخ الاحتياطي       (الحماية من فقدان البيانات)
      6.  الكاش والأقفال        (الأداء)
      7.  الشبكة والبروكسي      (الاتصال)
      8.  لوحة الويب            (الأمان الخارجي)
      9.  الميزات الاختيارية    (Redis, QStash, NSFW, 2FA, ...)
      10. المصادقة الثنائية     (2FA)
      11. NSFW / Sightengine    (فلترة المحتوى)
      12. المسارات والملفات     (مكان التخزين)
      13. 🆕 Spam Detection Engine (v4.0.0 — 14 طبقة)
    """

    # ═══════════════════════════════════════════════════════════════
    # 1. الهوية والملاك
    # ═══════════════════════════════════════════════════════════════

    TOKEN: str = safe_str(os.getenv("BOT_TOKEN", ""), single_line=True)
    BOT_NAME: str = safe_str(os.getenv("BOT_NAME", "ريلاكس مانيجر"))
    BOT_USERNAME: str = safe_str(
        os.getenv("BOT_USERNAME", "Reelaaaxbot")
    ).lstrip('@')

    PRIMARY_OWNER_ID: int = safe_int(os.getenv("MAIN_ADMIN_ID", "0"))
    DEVELOPER_IDS: Tuple[int, ...] = field(default_factory=_parse_developer_ids)
    ANONYMOUS_ADMIN_ID: int = safe_int(
        os.getenv("ANONYMOUS_ADMIN_ID", "1087968824")
    )

    # ═══════════════════════════════════════════════════════════════
    # 2. البيئة والتشخيص
    # ═══════════════════════════════════════════════════════════════

    ENVIRONMENT: str = safe_str(
        os.getenv("ENVIRONMENT", "production")
    ).lower() or "production"

    LOG_LEVEL: str = safe_str(os.getenv("LOG_LEVEL", "INFO")).upper()
    DEBUG_MODE: bool = safe_bool(os.getenv("DEBUG_MODE", "false"))
    BATTERY_SAVER_MODE: bool = safe_bool(
        os.getenv("BATTERY_SAVER_MODE", "false")
    )
    DEFAULT_LANGUAGE: str = safe_str(
        os.getenv("DEFAULT_LANGUAGE", "ar")
    ).lower() or "ar"

    # ═══════════════════════════════════════════════════════════════
    # 3. قاعدة البيانات
    # ═══════════════════════════════════════════════════════════════

    DATABASE_URL: str = safe_str(
        os.getenv("DATABASE_URL", ""), single_line=True
    )
    DB_TIMEOUT: int = safe_int(os.getenv("DB_TIMEOUT", "30"))

    DB_POOL_SIZE: int = safe_int(os.getenv("DB_POOL_SIZE", "20"))
    DB_POOL_MIN_SIZE: int = safe_int(os.getenv("DB_POOL_MIN_SIZE", "2"))
    SQLITE_POOL_SIZE: int = safe_int(os.getenv("SQLITE_POOL_SIZE", "10"))
    MAX_CONNECTIONS: int = safe_int(os.getenv("MAX_CONNECTIONS", "20"))

    MV_REFRESH_COOLDOWN: int = safe_int(os.getenv("MV_REFRESH_COOLDOWN", "3600"))
    VACUUM_TIMEOUT: int = safe_int(os.getenv("VACUUM_TIMEOUT", "300"))
    SLOW_QUERY_LOG_THRESHOLD: float = safe_float(
        os.getenv("SLOW_QUERY_LOG_THRESHOLD", "1.0")
    )
    SLOW_QUERY_FULL_STACK: bool = safe_bool(
        os.getenv("SLOW_QUERY_FULL_STACK", "true")
    )
    EXPLAIN_SLOW_QUERIES: bool = safe_bool(
        os.getenv("EXPLAIN_SLOW_QUERIES", "false")
    )
    POSTS_BATCH_SIZE: int = safe_int(os.getenv("POSTS_BATCH_SIZE", "100"))
    EXPIRED_PENALTIES_BATCH: int = safe_int(
        os.getenv("EXPIRED_PENALTIES_BATCH", "500")
    )

    DB_ENCRYPTION: bool = safe_bool(os.getenv("DB_ENCRYPTION", "false"))
    DB_ENCRYPTION_PASSWORD: str = safe_str(
        os.getenv("DB_ENCRYPTION_PASSWORD", ""), single_line=True
    )

    # ═══════════════════════════════════════════════════════════════
    # 4. النشر التلقائي
    # ═══════════════════════════════════════════════════════════════

    DEFAULT_PUBLISH_INTERVAL: int = safe_int(
        os.getenv("DEFAULT_PUBLISH_INTERVAL", "12")
    )
    DEFAULT_PUBLISH_INTERVAL_SECONDS: int = safe_int(
        os.getenv("DEFAULT_PUBLISH_INTERVAL_SECONDS", "720")
    )
    MIN_PUBLISH_INTERVAL: int = safe_int(
        os.getenv("MIN_PUBLISH_INTERVAL", "5")
    )
    MAX_CHANNELS_PER_CYCLE: int = safe_int(
        os.getenv("MAX_CHANNELS_PER_CYCLE", "20")
    )
    PUBLISH_RETRY_DELAY: int = safe_int(os.getenv("PUBLISH_RETRY_DELAY", "5"))

    PUBLISH_DB_CONCURRENCY: int = safe_int(
        os.getenv("PUBLISH_DB_CONCURRENCY", "4")
    )

    MAX_UNPUBLISHED_POSTS: int = safe_int(
        os.getenv("MAX_UNPUBLISHED_POSTS", "1000")
    )
    MAX_POSTS_PER_CHANNEL: int = safe_int(
        os.getenv("MAX_POSTS_PER_CHANNEL", "30")
    )
    MAX_POSTS_PER_SESSION: int = safe_int(
        os.getenv("MAX_POSTS_PER_SESSION", "100")
    )

    # ═══════════════════════════════════════════════════════════════
    # 5. النسخ الاحتياطي
    # ═══════════════════════════════════════════════════════════════

    AUTO_BACKUP_ENABLED: bool = safe_bool(
        os.getenv("AUTO_BACKUP_ENABLED", "true")
    )
    AUTO_BACKUP_SLEEP: int = safe_int(os.getenv("AUTO_BACKUP_SLEEP", "86400"))
    MAX_BACKUPS: int = safe_int(os.getenv("MAX_BACKUPS", "20"))

    GOOGLE_CREDENTIALS_FILE: str = safe_str(
        os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    )
    GOOGLE_DRIVE_FOLDER_ID: str = safe_str(
        os.getenv("GOOGLE_DRIVE_FOLDER_ID", ""), single_line=True
    )
    CLOUD_BACKUP_ENABLED: bool = safe_bool(
        os.getenv("CLOUD_BACKUP_ENABLED", "false")
    )

    # ═══════════════════════════════════════════════════════════════
    # 6. الكاش والأقفال
    # ═══════════════════════════════════════════════════════════════

    CACHE_TTL: int = safe_int(os.getenv("CACHE_TTL", "30"))
    AUTH_CACHE_SIZE: int = safe_int(os.getenv("AUTH_CACHE_SIZE", "2000"))
    AUTH_CACHE_TTL: int = safe_int(os.getenv("AUTH_CACHE_TTL", "15"))
    BANNED_WORDS_CACHE_TTL: int = safe_int(
        os.getenv("BANNED_WORDS_CACHE_TTL", "60")
    )
    ENABLE_BANNED_WORDS_CACHE: bool = safe_bool(
        os.getenv("ENABLE_BANNED_WORDS_CACHE", "true")
    )
    SUB_CACHE_TTL: int = safe_int(os.getenv("SUB_CACHE_TTL", "300"))

    MAX_USER_LOCKS: int = safe_int(os.getenv("MAX_USER_LOCKS", "10000"))
    MAX_GROUP_LOCKS: int = safe_int(os.getenv("MAX_GROUP_LOCKS", "5000"))
    MAX_CHANNEL_LOCKS: int = safe_int(os.getenv("MAX_CHANNEL_LOCKS", "5000"))
    MAX_PENALTY_LOCKS: int = safe_int(os.getenv("MAX_PENALTY_LOCKS", "5000"))

    # ═══════════════════════════════════════════════════════════════
    # 7. الشبكة والبروكسي والمهام الخلفية
    # ═══════════════════════════════════════════════════════════════

    WEB_HOST: str = safe_str(os.getenv("WEB_HOST", "0.0.0.0"))
    WEB_PORT: int = safe_int(
        os.getenv("WEB_PORT") or os.getenv("PORT", "10000")
    )

    USE_PROXY: bool = safe_bool(os.getenv("USE_PROXY", "false"))
    PROXY_URL: str = safe_str(
        os.getenv("PROXY_URL", "http://127.0.0.1:10809"), single_line=True
    )

    CONNECT_TIMEOUT: int = safe_int(os.getenv("CONNECT_TIMEOUT", "30"))
    READ_TIMEOUT: int = safe_int(os.getenv("READ_TIMEOUT", "60"))
    WRITE_TIMEOUT: int = safe_int(os.getenv("WRITE_TIMEOUT", "30"))
    POOL_TIMEOUT: int = safe_int(os.getenv("POOL_TIMEOUT", "10"))
    POLL_INTERVAL: float = safe_float(os.getenv("POLL_INTERVAL", "1.0"))

    HEARTBEAT_INTERVAL: int = safe_int(os.getenv("HEARTBEAT_INTERVAL", "300"))
    ENABLE_SELF_PING: bool = safe_bool(os.getenv("ENABLE_SELF_PING", "true"))
    CLEANUP_SLEEP: int = safe_int(os.getenv("CLEANUP_SLEEP", "3600"))

    # ═══════════════════════════════════════════════════════════════
    # 8. لوحة الويب (أمان خارجي)
    # ═══════════════════════════════════════════════════════════════

    WEB_USERNAME: str = safe_str(os.getenv("WEB_USERNAME", "admin"))
    WEB_PASSWORD: str = safe_str(
        os.getenv("WEB_PASSWORD", ""), single_line=True
    )
    WEB_SECRET_KEY: str = safe_str(
        os.getenv("WEB_SECRET_KEY", ""), single_line=True
    )
    WEB_SESSION_TIMEOUT: int = safe_int(
        os.getenv("WEB_SESSION_TIMEOUT", "3600")
    )
    WEB_RATE_LIMIT: int = safe_int(os.getenv("WEB_RATE_LIMIT", "100"))
    WEB_RATE_WINDOW: int = safe_int(os.getenv("WEB_RATE_WINDOW", "60"))

    WEBHOOK_SECRET: str = safe_str(
        os.getenv("WEBHOOK_SECRET", ""), single_line=True
    )

    # ═══════════════════════════════════════════════════════════════
    # 9. الميزات الاختيارية
    # ═══════════════════════════════════════════════════════════════

    XTR_CURRENCY: str = safe_str(os.getenv("XTR_CURRENCY", "XTR"))
    GIFT_PLANS_ENABLED: bool = safe_bool(
        os.getenv("GIFT_PLANS_ENABLED", "true")
    )
    PENALTY_SYSTEM_ENABLED: bool = safe_bool(
        os.getenv("PENALTY_SYSTEM_ENABLED", "true")
    )

    MAX_DAILY_REFERRALS: int = safe_int(os.getenv("MAX_DAILY_REFERRALS", "5"))

    MAX_GLOBAL_BANNED_WORDS: int = safe_int(
        os.getenv("MAX_GLOBAL_BANNED_WORDS", "10000")
    )

    REDIS_AVAILABLE: bool = safe_bool(os.getenv("REDIS_AVAILABLE", "false"))
    REDIS_URL: str = safe_str(os.getenv("REDIS_URL", ""), single_line=True)
    QSTASH_TOKEN: str = safe_str(
        os.getenv("QSTASH_TOKEN", ""), single_line=True
    )
    QSTASH_URL: str = safe_str(os.getenv("QSTASH_URL", ""), single_line=True)

    # ═══════════════════════════════════════════════════════════════
    # 10. المصادقة الثنائية (2FA)
    # ═══════════════════════════════════════════════════════════════

    ENABLE_2FA: bool = safe_bool(os.getenv("ENABLE_2FA", "true"))
    ADMIN_2FA_SECRET: str = safe_str(
        os.getenv("ADMIN_2FA_SECRET", ""), single_line=True
    )

    TWO_FA_TOKEN_FILE: str = safe_str(
        os.getenv("TWO_FA_TOKEN_FILE")
        or os.getenv("TOKEN_FILE", "token.json")
    )

    # ═══════════════════════════════════════════════════════════════
    # 11. NSFW / Sightengine
    # ═══════════════════════════════════════════════════════════════

    NSFW_ENABLED: bool = safe_bool(os.getenv("NSFW_ENABLED", "false"))
    NSFW_THRESHOLD: float = safe_float(os.getenv("NSFW_THRESHOLD", "0.7"))
    NSFW_FRAMES: int = safe_int(os.getenv("NSFW_FRAMES", "5"))
    NSFW_MAX_FILE_SIZE: int = safe_int(
        os.getenv("NSFW_MAX_FILE_SIZE", "5242880")
    )
    NSFW_MAX_VIDEO_SIZE: int = safe_int(
        os.getenv("NSFW_MAX_VIDEO_SIZE", "10485760")
    )
    SIGHTENGINE_API_USER: str = safe_str(
        os.getenv("SIGHTENGINE_API_USER", ""), single_line=True
    )
    SIGHTENGINE_API_SECRET: str = safe_str(
        os.getenv("SIGHTENGINE_API_SECRET", ""), single_line=True
    )

    # ═══════════════════════════════════════════════════════════════
    # 12. المسارات والملفات والأمان الإضافي
    # ═══════════════════════════════════════════════════════════════

    BANNED_WORDS_FILE: str = safe_abs_path(
        os.getenv("BANNED_WORDS_FILE", ""), "./banned_words.txt"
    )
    LANG_PATH: str = safe_abs_path(
        os.getenv("LANG_PATH", ""), "./lang"
    )
    TEMP_PATH: str = safe_str(os.getenv("TEMP_PATH", "/tmp/bot_temp"))
    PERSISTENT_DATA_PATH: str = safe_str(
        os.getenv("PERSISTENT_DATA_PATH", "/data")
    )

    SB_SECRET: str = safe_str(os.getenv("SB_SECRET", ""), single_line=True)
    SECURITY_LOG_LEVEL: str = safe_str(
        os.getenv("SECURITY_LOG_LEVEL", "CRITICAL")
    ).upper()

    # ═══════════════════════════════════════════════════════════════
    # 🆕 13. Spam Detection Engine (v4.0.0 — 14 طبقة)
    # ═══════════════════════════════════════════════════════════════

    # ─── تفعيل الطبقات (افتراضي: الكل مُفعَّل) ───
    TEXT_LAYER_ENABLED: bool = safe_bool(
        os.getenv("TEXT_LAYER_ENABLED", "true")
    )
    OCR_LAYER_ENABLED: bool = safe_bool(
        os.getenv("OCR_LAYER_ENABLED", "true")
    )
    AUDIO_LAYER_ENABLED: bool = safe_bool(
        os.getenv("AUDIO_LAYER_ENABLED", "true")
    )
    URL_LAYER_ENABLED: bool = safe_bool(
        os.getenv("URL_LAYER_ENABLED", "true")
    )
    METADATA_LAYER_ENABLED: bool = safe_bool(
        os.getenv("METADATA_LAYER_ENABLED", "true")
    )
    OBFUSCATION_LAYER_ENABLED: bool = safe_bool(
        os.getenv("OBFUSCATION_LAYER_ENABLED", "true")
    )
    BEHAVIORAL_LAYER_ENABLED: bool = safe_bool(
        os.getenv("BEHAVIORAL_LAYER_ENABLED", "true")
    )

    # 🆕 v4.0.0 — 7 طبقات إضافية
    VIDEO_LAYER_ENABLED: bool = safe_bool(
        os.getenv("VIDEO_LAYER_ENABLED", "true")
    )
    NSFW_LAYER_ENABLED: bool = safe_bool(
        os.getenv("NSFW_LAYER_ENABLED", "true")
    )
    STICKER_LAYER_ENABLED: bool = safe_bool(
        os.getenv("STICKER_LAYER_ENABLED", "true")
    )
    REACTIONS_LAYER_ENABLED: bool = safe_bool(
        os.getenv("REACTIONS_LAYER_ENABLED", "true")
    )
    CONTEXT_LAYER_ENABLED: bool = safe_bool(
        os.getenv("CONTEXT_LAYER_ENABLED", "true")
    )
    CIPHER_LAYER_ENABLED: bool = safe_bool(
        os.getenv("CIPHER_LAYER_ENABLED", "true")
    )
    STEGO_LAYER_ENABLED: bool = safe_bool(
        os.getenv("STEGO_LAYER_ENABLED", "true")
    )
    DOMAIN_REP_LAYER_ENABLED: bool = safe_bool(
        os.getenv("DOMAIN_REP_LAYER_ENABLED", "true")
    )

    # ─── إعدادات الطبقات المتقدمة ───

    # L7: Video
    VIDEO_MAX_FRAMES: int = safe_int(os.getenv("VIDEO_MAX_FRAMES", "8"))
    VIDEO_FRAME_INTERVAL_SEC: float = safe_float(
        os.getenv("VIDEO_FRAME_INTERVAL_SEC", "2.0")
    )

    # L8: NSFW Model
    NSFW_MODEL_ENABLED: bool = safe_bool(
        os.getenv("NSFW_MODEL_ENABLED", "false")
    )
    # NSFW_THRESHOLD أعلاه (قسم 11) — يُستخدم لكلا النظامين

    # L2: Audio
    AUDIO_USE_WHISPER: bool = safe_bool(
        os.getenv("AUDIO_USE_WHISPER", "false")
    )
    AUDIO_NOISE_REDUCE: bool = safe_bool(
        os.getenv("AUDIO_NOISE_REDUCE", "true")
    )

    # L3: URL Enrichment
    URL_ENRICH_ENABLED: bool = safe_bool(
        os.getenv("URL_ENRICH_ENABLED", "true")
    )
    URL_EXPAND_TIMEOUT: int = safe_int(os.getenv("URL_EXPAND_TIMEOUT", "5"))
    URL_EXPAND_MAX_HOPS: int = safe_int(os.getenv("URL_EXPAND_MAX_HOPS", "5"))
    URL_ENRICH_MAX_URLS: int = safe_int(os.getenv("URL_ENRICH_MAX_URLS", "5"))
    WHOIS_ENABLED: bool = safe_bool(os.getenv("WHOIS_ENABLED", "true"))
    WHOIS_NEW_DOMAIN_DAYS: int = safe_int(
        os.getenv("WHOIS_NEW_DOMAIN_DAYS", "30")
    )
    SAFE_BROWSING_API_KEY: str = safe_str(
        os.getenv("SAFE_BROWSING_API_KEY", ""), single_line=True
    )

    # L1: OCR Languages
    OCR_LANGUAGES: str = safe_str(
        os.getenv("OCR_LANGUAGES", "ara+eng+fas+rus"), single_line=True
    )

    # ─── التشخيص ───
    DEBUG_DIAG: bool = safe_bool(os.getenv("DEBUG_DIAG", "false"))
    DEBUG_SPAM: bool = safe_bool(os.getenv("DEBUG_SPAM", "false"))

    # ═══════════════════════════════════════════════════════════════
    # Properties (aliases خلفية)
    # ═══════════════════════════════════════════════════════════════

    @property
    def DEFAULT_LANG(self) -> str:
        """alias لـ DEFAULT_LANGUAGE — متوافق مع utils.py."""
        return self.DEFAULT_LANGUAGE

    @property
    def TOKEN_FILE(self) -> str:
        """alias خلفي لـ TWO_FA_TOKEN_FILE."""
        return self.TWO_FA_TOKEN_FILE

    @property
    def SPAM_DETECTION_AVAILABLE(self) -> bool:
        """هل محرك كشف السبام متاح؟"""
        return self.TEXT_LAYER_ENABLED

    @property
    def DETECTION_SUMMARY(self) -> Dict[str, bool]:
        """
        🆕 v6: ملخّص حالة كل طبقات الكشف.
        مفيد لـ /health endpoint أو logging.
        """
        return {
            "text":        self.TEXT_LAYER_ENABLED,
            "ocr":         self.OCR_LAYER_ENABLED,
            "audio":       self.AUDIO_LAYER_ENABLED,
            "url":         self.URL_LAYER_ENABLED,
            "metadata":    self.METADATA_LAYER_ENABLED,
            "obfuscation": self.OBFUSCATION_LAYER_ENABLED,
            "behavioral":  self.BEHAVIORAL_LAYER_ENABLED,
            "video":       self.VIDEO_LAYER_ENABLED,
            "nsfw":        self.NSFW_LAYER_ENABLED and self.NSFW_MODEL_ENABLED,
            "sticker":     self.STICKER_LAYER_ENABLED,
            "reactions":   self.REACTIONS_LAYER_ENABLED,
            "context":     self.CONTEXT_LAYER_ENABLED,
            "cipher":      self.CIPHER_LAYER_ENABLED,
            "stego":       self.STEGO_LAYER_ENABLED,
            "domain_rep":  self.DOMAIN_REP_LAYER_ENABLED,
        }

    @property
    def DETECTION_ENABLED_COUNT(self) -> int:
        """عدد الطبقات المُفعَّلة حالياً (0-15)."""
        return sum(1 for v in self.DETECTION_SUMMARY.values() if v)

    # ═══════════════════════════════════════════════════════════════
    # دوال مساعدة
    # ═══════════════════════════════════════════════════════════════

    def get_log_level(self) -> int:
        """يُرجع numeric logging level من النص."""
        mapping = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "WARN": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
            "FATAL": logging.CRITICAL,
        }
        return mapping.get(self.LOG_LEVEL, logging.INFO)

    def is_developer(self, user_id: int) -> bool:
        """هل المستخدم مطور؟ (المالك أو في قائمة المطورين)."""
        return user_id == self.PRIMARY_OWNER_ID or user_id in self.DEVELOPER_IDS

    def is_owner(self, user_id: int) -> bool:
        """هل المستخدم هو المالك؟"""
        return user_id == self.PRIMARY_OWNER_ID

    def get_detector_env(self) -> Dict[str, str]:
        """
        🆕 v6: يُصدّر إعدادات كاشف السبام كـ dict
        متوافق مع os.environ — مفيد عند استيراد
        handlers_message_detectors قبل config.

        الاستخدام:
            for k, v in CONFIG.get_detector_env().items():
                os.environ.setdefault(k, v)
        """
        def _b(x: bool) -> str:
            return "1" if x else "0"

        return {
            # Layer toggles
            "TEXT_LAYER_ENABLED": _b(self.TEXT_LAYER_ENABLED),
            "OCR_LAYER_ENABLED": _b(self.OCR_LAYER_ENABLED),
            "AUDIO_LAYER_ENABLED": _b(self.AUDIO_LAYER_ENABLED),
            "URL_LAYER_ENABLED": _b(self.URL_LAYER_ENABLED),
            "METADATA_LAYER_ENABLED": _b(self.METADATA_LAYER_ENABLED),
            "OBFUSCATION_LAYER_ENABLED": _b(self.OBFUSCATION_LAYER_ENABLED),
            "BEHAVIORAL_LAYER_ENABLED": _b(self.BEHAVIORAL_LAYER_ENABLED),
            "VIDEO_LAYER_ENABLED": _b(self.VIDEO_LAYER_ENABLED),
            "NSFW_LAYER_ENABLED": _b(self.NSFW_LAYER_ENABLED),
            "STICKER_LAYER_ENABLED": _b(self.STICKER_LAYER_ENABLED),
            "REACTIONS_LAYER_ENABLED": _b(self.REACTIONS_LAYER_ENABLED),
            "CONTEXT_LAYER_ENABLED": _b(self.CONTEXT_LAYER_ENABLED),
            "CIPHER_LAYER_ENABLED": _b(self.CIPHER_LAYER_ENABLED),
            "STEGO_LAYER_ENABLED": _b(self.STEGO_LAYER_ENABLED),
            "DOMAIN_REP_LAYER_ENABLED": _b(self.DOMAIN_REP_LAYER_ENABLED),

            # Settings
            "VIDEO_MAX_FRAMES": str(self.VIDEO_MAX_FRAMES),
            "VIDEO_FRAME_INTERVAL_SEC": str(self.VIDEO_FRAME_INTERVAL_SEC),
            "NSFW_MODEL_ENABLED": _b(self.NSFW_MODEL_ENABLED),
            "NSFW_THRESHOLD": str(self.NSFW_THRESHOLD),
            "AUDIO_USE_WHISPER": _b(self.AUDIO_USE_WHISPER),
            "AUDIO_NOISE_REDUCE": _b(self.AUDIO_NOISE_REDUCE),
            "URL_ENRICH_ENABLED": _b(self.URL_ENRICH_ENABLED),
            "URL_EXPAND_TIMEOUT": str(self.URL_EXPAND_TIMEOUT),
            "URL_EXPAND_MAX_HOPS": str(self.URL_EXPAND_MAX_HOPS),
            "URL_ENRICH_MAX_URLS": str(self.URL_ENRICH_MAX_URLS),
            "WHOIS_ENABLED": _b(self.WHOIS_ENABLED),
            "WHOIS_NEW_DOMAIN_DAYS": str(self.WHOIS_NEW_DOMAIN_DAYS),
            "SAFE_BROWSING_API_KEY": self.SAFE_BROWSING_API_KEY,
            "OCR_LANGUAGES": self.OCR_LANGUAGES,
            "DEBUG_DIAG": _b(self.DEBUG_DIAG),
            "DEBUG_SPAM": _b(self.DEBUG_SPAM),
        }

    def apply_detector_env(self, *, override: bool = False) -> int:
        """
        🆕 v6: يضبط متغيرات كاشف السبام في os.environ.
        Returns: عدد المتغيرات المضبوطة.

        يُستدعى في bot.py مبكراً قبل import handlers_message_detectors
        لضمان أن CONFIG هو مصدر الحقيقة الوحيد.
        """
        env = self.get_detector_env()
        applied = 0
        for k, v in env.items():
            if override or k not in os.environ:
                os.environ[k] = v
                applied += 1
        return applied

    # ═══════════════════════════════════════════════════════════════
    # التحقق من الإعدادات
    # ═══════════════════════════════════════════════════════════════

    def validate(self) -> None:
        """التحقق من القيم المطلوبة — 5 مستويات."""
        errors: List[str] = []
        warnings: List[str] = []

        # ─── 1. الإعدادات الحرجة ───────────────────────────────

        if not self.TOKEN:
            errors.append("BOT_TOKEN غير موجود في .env")
        elif len(self.TOKEN) < 20:
            errors.append("BOT_TOKEN يبدو غير صالح (قصير جداً)")

        if self.PRIMARY_OWNER_ID == 0:
            errors.append("MAIN_ADMIN_ID غير موجود في .env")
        elif self.PRIMARY_OWNER_ID < 0:
            errors.append("MAIN_ADMIN_ID يجب أن يكون رقماً موجباً")

        if self.ANONYMOUS_ADMIN_ID <= 0:
            errors.append(
                f"ANONYMOUS_ADMIN_ID يجب أن يكون رقماً موجباً: "
                f"{self.ANONYMOUS_ADMIN_ID}"
            )

        if self.ENVIRONMENT not in (
            "production", "development", "staging", "test"
        ):
            warnings.append(
                f"ENVIRONMENT غير معروف: {self.ENVIRONMENT!r} — "
                f"سيُعامَل كـ production."
            )

        # ─── 2. إعدادات النشر ──────────────────────────────────

        if self.MIN_PUBLISH_INTERVAL < 1:
            errors.append("MIN_PUBLISH_INTERVAL يجب أن يكون أكبر من 0")

        if self.DEFAULT_PUBLISH_INTERVAL < self.MIN_PUBLISH_INTERVAL:
            errors.append(
                f"DEFAULT_PUBLISH_INTERVAL ({self.DEFAULT_PUBLISH_INTERVAL}) "
                f"يجب أن يكون أكبر من أو يساوي "
                f"MIN_PUBLISH_INTERVAL ({self.MIN_PUBLISH_INTERVAL})"
            )

        if self.MAX_CHANNELS_PER_CYCLE < 1:
            errors.append("MAX_CHANNELS_PER_CYCLE يجب أن يكون أكبر من 0")

        # ─── 3. الموارد والشبكة ────────────────────────────────

        if self.WEB_PORT < 1 or self.WEB_PORT > 65535:
            errors.append(f"WEB_PORT غير صالح: {self.WEB_PORT}")

        if self.MAX_BACKUPS < 1:
            errors.append("MAX_BACKUPS يجب أن يكون أكبر من 0")
        elif self.MAX_BACKUPS > 100:
            errors.append(
                f"MAX_BACKUPS مرتفع جداً ({self.MAX_BACKUPS}) — "
                f"يُستهلك القرص. الحد الأقصى المعقول 100."
            )

        if self.DB_POOL_SIZE < 1 or self.DB_POOL_SIZE > 100:
            errors.append(f"DB_POOL_SIZE غير صالح: {self.DB_POOL_SIZE}")

        if self.DB_POOL_MIN_SIZE < 1:
            errors.append("DB_POOL_MIN_SIZE يجب أن يكون أكبر من 0")

        if self.DB_POOL_MIN_SIZE >= self.DB_POOL_SIZE:
            errors.append(
                f"DB_POOL_MIN_SIZE ({self.DB_POOL_MIN_SIZE}) "
                f"يجب أن يكون أصغر تماماً من "
                f"DB_POOL_SIZE ({self.DB_POOL_SIZE})"
            )

        if self.PUBLISH_DB_CONCURRENCY < 1 or self.PUBLISH_DB_CONCURRENCY > 10:
            errors.append(
                f"PUBLISH_DB_CONCURRENCY يجب أن يكون بين 1 و 10: "
                f"{self.PUBLISH_DB_CONCURRENCY}"
            )

        if self.MAX_GLOBAL_BANNED_WORDS < 1:
            errors.append(
                f"MAX_GLOBAL_BANNED_WORDS يجب أن يكون أكبر من 0: "
                f"{self.MAX_GLOBAL_BANNED_WORDS}"
            )

        # ─── 4. الميزات الاختيارية ─────────────────────────────

        if self.ENABLE_2FA and not self.ADMIN_2FA_SECRET:
            errors.append("ADMIN_2FA_SECRET مطلوب عند تفعيل ENABLE_2FA")

        if self.NSFW_ENABLED:
            if not self.SIGHTENGINE_API_USER or not self.SIGHTENGINE_API_SECRET:
                errors.append(
                    "SIGHTENGINE_API_USER و SIGHTENGINE_API_SECRET "
                    "مطلوبان عند تفعيل NSFW_ENABLED"
                )

        if self.REDIS_AVAILABLE and not self.REDIS_URL:
            errors.append("REDIS_URL مطلوب عند تفعيل REDIS_AVAILABLE")

        # ─── 5. 🆕 v6: طبقات كشف السبام ──────────────────────

        # NSFW_LAYER_ENABLED بدون NSFW_MODEL_ENABLED = تحذير (لن يعمل)
        if self.NSFW_LAYER_ENABLED and not self.NSFW_MODEL_ENABLED:
            warnings.append(
                "NSFW_LAYER_ENABLED=1 لكن NSFW_MODEL_ENABLED=0 — "
                "طبقة NSFW لن تعمل. "
                "إما فعّل NSFW_MODEL_ENABLED (يتطلب transformers+torch) "
                "أو عطّل NSFW_LAYER_ENABLED."
            )

        # URL_LAYER_ENABLED بدون Safe Browsing = تحذير
        if self.URL_LAYER_ENABLED and not self.SAFE_BROWSING_API_KEY:
            warnings.append(
                "URL_LAYER_ENABLED=1 لكن SAFE_BROWSING_API_KEY فارغ — "
                "دقة كشف الروابط ستكون أقل (بدون Google Safe Browsing)."
            )

        # OCR_LAYER_ENABLED بدون tesseract = تحذير
        if self.OCR_LAYER_ENABLED:
            try:
                import pytesseract  # noqa: F401
            except ImportError:
                warnings.append(
                    "OCR_LAYER_ENABLED=1 لكن pytesseract غير مثبت — "
                    "OCR معطّل فعلياً. "
                    "ثبّت: pip install pytesseract Pillow"
                )

        # VIDEO_LAYER_ENABLED بدون opencv/ffmpeg = تحذير
        if self.VIDEO_LAYER_ENABLED:
            _has_cv2 = False
            _has_ffmpeg = False
            try:
                import cv2  # noqa: F401
                _has_cv2 = True
            except ImportError:
                pass
            try:
                import subprocess
                r = subprocess.run(
                    ["ffmpeg", "-version"],
                    capture_output=True,
                    timeout=3,
                )
                _has_ffmpeg = (r.returncode == 0)
            except Exception:
                pass
            if not (_has_cv2 or _has_ffmpeg):
                warnings.append(
                    "VIDEO_LAYER_ENABLED=1 لكن opencv و ffmpeg غير متوفرين — "
                    "طبقة الفيديو معطّلة فعلياً."
                )

        # AUDIO_LAYER_ENABLED بدون pydub = تحذير
        if self.AUDIO_LAYER_ENABLED:
            try:
                import speech_recognition  # noqa: F401
                from pydub import AudioSegment  # noqa: F401
            except ImportError:
                warnings.append(
                    "AUDIO_LAYER_ENABLED=1 لكن SpeechRecognition/pydub "
                    "غير مثبتين — طبقة الصوت معطّلة فعلياً."
                )

        # STEGO_LAYER_ENABLED بدون numpy = تحذير
        if self.STEGO_LAYER_ENABLED:
            try:
                import numpy  # noqa: F401
            except ImportError:
                warnings.append(
                    "STEGO_LAYER_ENABLED=1 لكن numpy غير مثبت — "
                    "طبقة Steganography معطّلة فعلياً. "
                    "ثبّت: pip install numpy"
                )

        # إذا كل طبقات الكشف معطّلة = تحذير
        if not self.SPAM_DETECTION_AVAILABLE:
            warnings.append(
                "TEXT_LAYER_ENABLED=0 — محرك كشف السبام معطّل بالكامل! "
                "لن يكتشف البوت أي سبام."
            )

        # ─── 6. تحذيرات الإنتاج ────────────────────────────────

        if self.ENVIRONMENT == "production" and not self.WEB_PASSWORD:
            warnings.append(
                "WEB_PASSWORD فارغ في بيئة الإنتاج — "
                "لوحة الويب غير محمية!"
            )

        if self.ENVIRONMENT == "production" and not self.WEB_SECRET_KEY:
            warnings.append(
                "WEB_SECRET_KEY فارغ في بيئة الإنتاج — "
                "جلسات الويب غير آمنة."
            )

        if self.ENVIRONMENT == "production" and not self.WEBHOOK_SECRET:
            warnings.append(
                "WEBHOOK_SECRET فارغ في بيئة الإنتاج — "
                "حماية webhook معطّلة."
            )

        # ─── النتيجة النهائية ──────────────────────────────────

        if warnings:
            for w in warnings:
                logger.warning(f"⚠️ {w}")

        if errors:
            error_msg = "\n".join(f"  • {e}" for e in errors)
            raise ValueError(f"❌ أخطاء في الإعدادات:\n{error_msg}")


# ═══════════════════════════════════════════════════════════════════
# PathManager — إدارة المسارات
# ═══════════════════════════════════════════════════════════════════

class PathManager:
    """
    إنشاء وإدارة مسارات المشروع (Singleton).
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_paths()
            return cls._instance

    def _init_paths(self) -> None:
        self.BASE = Path(__file__).resolve().parent
        self.DATA = self.BASE / "data"
        self.BACKUPS = self.BASE / "backups"
        self.LOGS = self.BASE / "logs"
        self.DB = self.DATA / "bot_data.db"
        self.LOG_FILE = self.LOGS / "bot.log"

        try:
            self.TEMP = Path(CONFIG.TEMP_PATH)
        except Exception:
            self.TEMP = self.BASE / "temp"

        for d in (self.DATA, self.BACKUPS, self.LOGS, self.TEMP):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning(f"⚠️ تعذّر إنشاء {d}: {e}")

        try:
            if not self.LOG_FILE.exists():
                self.LOG_FILE.touch(exist_ok=True)
        except Exception as e:
            logger.warning(f"⚠️ تعذّر إنشاء ملف السجل: {e}")


# ═══════════════════════════════════════════════════════════════════
# التهيئة النهائية
# ═══════════════════════════════════════════════════════════════════

CONFIG = AppConfig()
PATHS = PathManager()

# 🆕 v6: تصدير إعدادات كاشف السبام إلى os.environ (بدون override)
try:
    _applied = CONFIG.apply_detector_env(override=False)
    if _applied > 0:
        logger.debug(
            f"🛡️ تم تصدير {_applied} متغير كشف سبام إلى os.environ"
        )
except Exception as e:
    logger.debug(f"apply_detector_env: {e}")

# التحقق من الإعدادات
try:
    CONFIG.validate()
except ValueError as e:
    logger.error(f"❌ {e}")
    raise SystemExit(1)

# ═══════════════════════════════════════════════════════════════════
# سجل الإقلاع — v6
# ═══════════════════════════════════════════════════════════════════

logger.info(
    f"✅ تم تحميل الإعدادات: {CONFIG.BOT_NAME} (@{CONFIG.BOT_USERNAME})"
)
logger.info(f"📁 قاعدة البيانات: {PATHS.DB}")
logger.info(
    f"🔐 المصادقة الثنائية: {'مفعلة' if CONFIG.ENABLE_2FA else 'معطلة'}"
)
logger.info(f"📊 NSFW (Sightengine): {'مفعل' if CONFIG.NSFW_ENABLED else 'معطل'}")
logger.info(
    f"🗄️ Redis: {'متاح' if CONFIG.REDIS_AVAILABLE else 'غير متاح'}"
)
logger.info(
    f"🚀 Pool: size={CONFIG.DB_POOL_SIZE} "
    f"min={CONFIG.DB_POOL_MIN_SIZE} "
    f"concurrency={CONFIG.PUBLISH_DB_CONCURRENCY}"
)
logger.info(
    f"🔒 Webhook secret: "
    f"{'مُهيَّأ' if CONFIG.WEBHOOK_SECRET else 'غير مُهيَّأ (اختياري)'}"
)

# 🆕 v6: تقرير طبقات كشف السبام
_summary = CONFIG.DETECTION_SUMMARY
_enabled_layers = [k for k, v in _summary.items() if v]
_disabled_layers = [k for k, v in _summary.items() if not v]

logger.info(
    f"🛡️ Spam Detection Engine v4.0.0 | "
    f"مُفعَّلة: {len(_enabled_layers)}/15 طبقة"
)
if _enabled_layers:
    logger.info(f"   ✅ مُفعَّلة: {', '.join(_enabled_layers)}")
if _disabled_layers:
    logger.info(f"   ❌ معطّلة: {', '.join(_disabled_layers)}")

if CONFIG.SAFE_BROWSING_API_KEY:
    logger.info("   🔗 Safe Browsing API: مُهيَّأ ✅")
else:
    logger.info("   🔗 Safe Browsing API: غير مُهيَّأ ⚠️ (يُوصى به)")