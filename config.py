#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
config.py - إعدادات البوت الأساسية (v7.0.3 — FULL-ENV-COVERAGE)
================================================================================
🆕 v7.0.3:
    ✅ إضافة DIAG_INCOMING — مُتغيّر تشخيصي جديد
    ✅ التحقق من تغطية كاملة لكل متغيرات .env
    ✅ توثيق مُحدَّث مع DEV-PERMANENT وملاحظات المُشغّل
    ✅ إضافة SB_SECRET في التحقق (اختياري)
    ✅ إضافة WEBHOOK_SECRET للتحقق الإنتاجي
    ✅ توافق كامل مع .env المُقدَّم

🆕 v7.0.2:
    👑 DEV-1: _parse_developer_ids — إزالة التكرار + ترتيب تنازلي
    👑 DEV-2: is_developer — docstring تفصيلي لاستخدامات DEV-PERMANENT
    👑 DEV-3: validate — تحذير عند تكرار PRIMARY_OWNER_ID في DEVELOPER_IDS
    📝 توثيق: كيف تتفاعل CONFIG مع database.py + database_subscriptions.py

🆕 v7.0.1:
    ✅ إخفاء تحذير NSFW عند استخدام Sightengine API (الوضع الخارجي)
    ✅ التحذير يظهر فقط عند غياب النموذج المحلي AND غياب Sightengine API

🆕 v7 (DETECTORS-v4.0.8-INTEGRATION):
    ✅ إصلاح الرأس: v4.0.0 → v4.0.8 (FULL-AUDIT-V3)
    ✅ إصلاح عدد الطبقات: 14 → 15
    ✅ إضافة ~40 متغير v4.0.8
    ✅ get_pool_env() — helper لـ main.py v5.6.12
    ✅ validate() — تحققات pool + circuit breaker
    ✅ تقرير الإقلاع مُحدَّث (15 طبقة + pool stats)
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
    try:
        return int(value.strip())
    except (ValueError, AttributeError, TypeError):
        return default


def safe_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value.strip())
    except (ValueError, AttributeError, TypeError):
        return default


def safe_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ('true', '1', 'yes', 'on')


def safe_str(value: str, default: str = "", *, single_line: bool = False) -> str:
    if value is None:
        return default
    s = str(value).strip()
    if single_line:
        s = re.sub(r'\s+', ' ', s)
    return s


def safe_abs_path(value: str, default: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raw = default
    p = Path(raw)
    if not p.is_absolute():
        p = BASE_DIR / p
    return str(p)


def _parse_developer_ids() -> Tuple[int, ...]:
    """
    👑 v7.0.2 DEV-1: تحليل DEVELOPER_IDS من متغير البيئة.

    - يقبل صيغة comma-separated: "111,222,333"
    - يتجاهل الفراغات والقيم غير الصحيحة
    - يقبل فقط الأرقام الموجبة (> 0)
    - يزيل التكرار تلقائياً (set)
    - يُرجع tuple مُرتَّب تصاعدياً (سلوك متوقّع ومستقر)

    Returns:
        Tuple[int, ...]: مثال (111, 222, 333)
        () إذا كان المتغير فارغاً أو غير صالح
    """
    raw = os.getenv("DEVELOPER_IDS", "") or ""
    seen: set = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        uid = safe_int(token, 0)
        if uid > 0:
            seen.add(uid)
    return tuple(sorted(seen))


# ═══════════════════════════════════════════════════════════════════
# AppConfig
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AppConfig:
    """
    إعدادات البوت — 13 قسم منطقي + قسم 13 الكبير للـdetectors.
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

    # 🆕 v7.0.3: تشخيص الرسائل الواردة
    DIAG_INCOMING: bool = safe_bool(os.getenv("DIAG_INCOMING", "false"))

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
    # 11. NSFW / Sightengine (نظام خارجي — منفصل عن detectors)
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
    # 🆕 13. Spam Detection Engine (v4.0.9 — 15 طبقة)
    # ═══════════════════════════════════════════════════════════════

    # ─── 13.1: تفعيل الطبقات الأساسية (7 طبقات) ───
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

    # ─── 13.2: الطبقات المتقدمة (8 طبقات) ───
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

    # ─── 13.3: إعدادات الطبقات المتقدمة ───

    # L7: Video
    VIDEO_MAX_FRAMES: int = safe_int(os.getenv("VIDEO_MAX_FRAMES", "8"))
    VIDEO_FRAME_INTERVAL_SEC: float = safe_float(
        os.getenv("VIDEO_FRAME_INTERVAL_SEC", "2.0")
    )

    # L8: NSFW Model (محلي — يتطلب transformers+torch)
    NSFW_MODEL_ENABLED: bool = safe_bool(
        os.getenv("NSFW_MODEL_ENABLED", "false")
    )
    NSFW_SIGHTENGINE_MAX_BYTES: int = safe_int(
        os.getenv("NSFW_SIGHTENGINE_MAX_BYTES", str(10 * 1024 * 1024))
    )

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
    URL_EXPAND_CONNECT_TIMEOUT: float = safe_float(
        os.getenv("URL_EXPAND_CONNECT_TIMEOUT", "3.0")
    )
    URL_EXPAND_READ_TIMEOUT: float = safe_float(
        os.getenv("URL_EXPAND_READ_TIMEOUT", "5.0")
    )
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

    # ─── 13.4: Anti-Evasion Toggles (24 متغير) ───
    ANTIEVASION_ENTITY_LINK: bool = safe_bool(
        os.getenv("ANTIEVASION_ENTITY_LINK", "true")
    )
    ANTIEVASION_BUTTON_LINK: bool = safe_bool(
        os.getenv("ANTIEVASION_BUTTON_LINK", "true")
    )
    ANTIEVASION_SCHEMELESS_URL: bool = safe_bool(
        os.getenv("ANTIEVASION_SCHEMELESS_URL", "true")
    )
    ANTIEVASION_HOMOGLYPH: bool = safe_bool(
        os.getenv("ANTIEVASION_HOMOGLYPH", "true")
    )
    ANTIEVASION_COMBINING: bool = safe_bool(
        os.getenv("ANTIEVASION_COMBINING", "true")
    )
    ANTIEVASION_COMPACT_WORDS: bool = safe_bool(
        os.getenv("ANTIEVASION_COMPACT_WORDS", "true")
    )
    ANTIEVASION_EMOJI_SEPARATOR: bool = safe_bool(
        os.getenv("ANTIEVASION_EMOJI_SEPARATOR", "true")
    )
    ANTIEVASION_BUTTON_WEBAPP: bool = safe_bool(
        os.getenv("ANTIEVASION_BUTTON_WEBAPP", "true")
    )
    ANTIEVASION_BUTTON_LOGINURL: bool = safe_bool(
        os.getenv("ANTIEVASION_BUTTON_LOGINURL", "true")
    )
    ANTIEVASION_LEETSPEAK: bool = safe_bool(
        os.getenv("ANTIEVASION_LEETSPEAK", "true")
    )
    ANTIEVASION_TG_SCHEME: bool = safe_bool(
        os.getenv("ANTIEVASION_TG_SCHEME", "true")
    )
    ANTIEVASION_AT_CHANNEL: bool = safe_bool(
        os.getenv("ANTIEVASION_AT_CHANNEL", "true")
    )
    ANTIEVASION_EMAIL: bool = safe_bool(
        os.getenv("ANTIEVASION_EMAIL", "true")
    )
    ANTIEVASION_PUNYCODE: bool = safe_bool(
        os.getenv("ANTIEVASION_PUNYCODE", "true")
    )
    ANTIEVASION_IPV4_SCHEMELESS: bool = safe_bool(
        os.getenv("ANTIEVASION_IPV4_SCHEMELESS", "true")
    )
    ANTIEVASION_MULTILINE_URL: bool = safe_bool(
        os.getenv("ANTIEVASION_MULTILINE_URL", "true")
    )
    ANTIEVASION_VENUE_VCARD: bool = safe_bool(
        os.getenv("ANTIEVASION_VENUE_VCARD", "true")
    )
    ANTIEVASION_POLL: bool = safe_bool(
        os.getenv("ANTIEVASION_POLL", "true")
    )
    ANTIEVASION_EMOJI_IN_DOMAIN: bool = safe_bool(
        os.getenv("ANTIEVASION_EMOJI_IN_DOMAIN", "true")
    )
    ANTIEVASION_UNICODE_DOTS: bool = safe_bool(
        os.getenv("ANTIEVASION_UNICODE_DOTS", "true")
    )
    ANTIEVASION_EXTENDED_COMBINING: bool = safe_bool(
        os.getenv("ANTIEVASION_EXTENDED_COMBINING", "true")
    )
    ANTIEVASION_EXTRA_SCRIPTS: bool = safe_bool(
        os.getenv("ANTIEVASION_EXTRA_SCRIPTS", "true")
    )
    ANTIEVASION_ALT_SCHEMES: bool = safe_bool(
        os.getenv("ANTIEVASION_ALT_SCHEMES", "true")
    )
    ANTIEVASION_RANDOM_DOMAIN: bool = safe_bool(
        os.getenv("ANTIEVASION_RANDOM_DOMAIN", "true")
    )

    # ─── 13.5: Pool + Async ───
    DETECTOR_POOL_WORKERS: int = safe_int(
        os.getenv("DETECTOR_POOL_WORKERS", "8")
    )
    POOL_TASK_TIMEOUT: float = safe_float(
        os.getenv("POOL_TASK_TIMEOUT", "60.0")
    )

    ASYNC_NETWORK_ENABLED: bool = safe_bool(
        os.getenv("ASYNC_NETWORK_ENABLED", "true")
    )
    ASYNC_NETWORK_TIMEOUT: float = safe_float(
        os.getenv("ASYNC_NETWORK_TIMEOUT", "5.0")
    )

    # ─── 13.6: Circuit Breaker + Cache ───
    SE_CIRCUIT_FAILURE_THRESHOLD: int = safe_int(
        os.getenv("SE_CIRCUIT_FAILURE_THRESHOLD", "5")
    )
    SE_CIRCUIT_OPEN_SEC: float = safe_float(
        os.getenv("SE_CIRCUIT_OPEN_SEC", "60.0")
    )

    NORMALIZE_CACHE_MAX: int = safe_int(
        os.getenv("NORMALIZE_CACHE_MAX", "512")
    )

    # ─── 13.7: التشخيص ───
    DEBUG_DIAG: bool = safe_bool(os.getenv("DEBUG_DIAG", "false"))
    DEBUG_SPAM: bool = safe_bool(os.getenv("DEBUG_SPAM", "false"))

    # ─── 13.8: Multi-layer master switches ───
    MULTILAYER_ENABLED: bool = safe_bool(
        os.getenv("MULTILAYER_ENABLED", "true")
    )
    ANTIFLOOD_ENABLED: bool = safe_bool(
        os.getenv("ANTIFLOOD_ENABLED", "true")
    )
    SLOW_MODE_AUTO: bool = safe_bool(os.getenv("SLOW_MODE_AUTO", "true"))

    # ─── 13.9: Arabic Short Whitelist (v4.0.9) 🆕 ───
    ARABIC_SHORT_WHITELIST_ENABLED: bool = safe_bool(
        os.getenv("ARABIC_SHORT_WHITELIST_ENABLED", "true")
    )
    ARABIC_SHORT_MAX_CHARS: int = safe_int(
        os.getenv("ARABIC_SHORT_MAX_CHARS", "40")
    )
    ARABIC_SHORT_MAX_WORDS: int = safe_int(
        os.getenv("ARABIC_SHORT_MAX_WORDS", "6")
    )
    ARABIC_DOMINANCE_RATIO: float = safe_float(
        os.getenv("ARABIC_DOMINANCE_RATIO", "0.6")
    )

    # ─── 13.10: FINAL_THRESHOLD (v4.0.9) 🆕 ───
    FINAL_THRESHOLD: int = safe_int(os.getenv("FINAL_THRESHOLD", "5"))

    # ─── 13.11: PostgreSQL Pool Tuning (v7.7.60) 🆕 ───
    PG_MAX_INACTIVE_LIFETIME: float = safe_float(
        os.getenv("PG_MAX_INACTIVE_LIFETIME", "15.0")
    )
    PG_CONN_PING_IDLE_THRESHOLD: float = safe_float(
        os.getenv("PG_CONN_PING_IDLE_THRESHOLD", "5.0")
    )
    PG_CONN_PING_TIMEOUT: float = safe_float(
        os.getenv("PG_CONN_PING_TIMEOUT", "2.0")
    )
    PG_TCP_KEEPIDLE: int = safe_int(os.getenv("PG_TCP_KEEPIDLE", "20"))
    PG_TCP_KEEPINTVL: int = safe_int(os.getenv("PG_TCP_KEEPINTVL", "5"))
    PG_TCP_KEEPCNT: int = safe_int(os.getenv("PG_TCP_KEEPCNT", "3"))
    PG_STATEMENT_TIMEOUT_MS: int = safe_int(
        os.getenv("PG_STATEMENT_TIMEOUT_MS", "8000")
    )
    PG_IDLE_TX_TIMEOUT_MS: int = safe_int(
        os.getenv("PG_IDLE_TX_TIMEOUT_MS", "30000")
    )
    PG_COMMAND_TIMEOUT: float = safe_float(
        os.getenv("PG_COMMAND_TIMEOUT", "10.0")
    )

    # ═══════════════════════════════════════════════════════════════
    # Properties (aliases خلفية)
    # ═══════════════════════════════════════════════════════════════

    @property
    def DEFAULT_LANG(self) -> str:
        return self.DEFAULT_LANGUAGE

    @property
    def TOKEN_FILE(self) -> str:
        return self.TWO_FA_TOKEN_FILE

    @property
    def SPAM_DETECTION_AVAILABLE(self) -> bool:
        return self.TEXT_LAYER_ENABLED

    @property
    def DETECTION_SUMMARY(self) -> Dict[str, bool]:
        """ملخّص حالة كل الطبقات الـ15."""
        return {
            "text":        self.TEXT_LAYER_ENABLED,
            "ocr":         self.OCR_LAYER_ENABLED,
            "audio":       self.AUDIO_LAYER_ENABLED,
            "url":         self.URL_LAYER_ENABLED,
            "metadata":    self.METADATA_LAYER_ENABLED,
            "obfuscation": self.OBFUSCATION_LAYER_ENABLED,
            "behavioral":  self.BEHAVIORAL_LAYER_ENABLED,
            "video":       self.VIDEO_LAYER_ENABLED,
            "nsfw":        self.NSFW_LAYER_ENABLED,
            "sticker":     self.STICKER_LAYER_ENABLED,
            "reactions":   self.REACTIONS_LAYER_ENABLED,
            "context":     self.CONTEXT_LAYER_ENABLED,
            "cipher":      self.CIPHER_LAYER_ENABLED,
            "stego":       self.STEGO_LAYER_ENABLED,
            "domain_rep":  self.DOMAIN_REP_LAYER_ENABLED,
        }

    @property
    def DETECTION_ENABLED_COUNT(self) -> int:
        return sum(1 for v in self.DETECTION_SUMMARY.values() if v)

    @property
    def DETECTOR_POOL_SIZE(self) -> int:
        """alias لـ DETECTOR_POOL_WORKERS — للتوافق."""
        return self.DETECTOR_POOL_WORKERS

    @property
    def HAS_SIGHTENGINE(self) -> bool:
        """✅ v7.0.1: هل Sightengine API مُهيَّأ؟"""
        return bool(
            self.SIGHTENGINE_API_USER and self.SIGHTENGINE_API_SECRET
        )

    @property
    def HAS_SAFE_BROWSING(self) -> bool:
        """🆕 v7.0.3: هل Safe Browsing API مُهيَّأ؟"""
        return bool(self.SAFE_BROWSING_API_KEY)

    @property
    def HAS_REDIS(self) -> bool:
        """🆕 v7.0.3: هل Redis مُهيَّأ؟"""
        return bool(self.REDIS_AVAILABLE and self.REDIS_URL)

    @property
    def HAS_QSTASH(self) -> bool:
        """🆕 v7.0.3: هل QStash مُهيَّأ؟"""
        return bool(self.QSTASH_TOKEN and self.QSTASH_URL)

    # ═══════════════════════════════════════════════════════════════
    # دوال مساعدة
    # ═══════════════════════════════════════════════════════════════

    def get_log_level(self) -> int:
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
        """
        👑 v7.0.2 DEV-2: هل المستخدم مطور/مالك؟

        تُستخدم من:
          • database.py::Database._is_dev_user
          • database_subscriptions.py::SubscriptionMixin._is_dev_user
          • database_channels_posts.py::ChannelsPostsMixin._is_dev_user

        الأثر عند إرجاع True:
          ✅ منح اشتراك دائم (100 سنة، provider='dev_bypass')
          ✅ bypass has_active_subscription (True دائماً)
          ✅ bypass has_used_trial (False دائماً)
          ✅ activate_trial يُرجع -1 (اشتراكه أطول)
          ✅ تجاوز فحوصات max_channels / max_posts
          ✅ expire_expired_subscriptions يتخطى اشتراكه الدائم
          ✅ get_users_for_reminder لن يُزعجه

        Args:
            user_id: معرّف المستخدم

        Returns:
            True إذا كان المالك الأساسي أو ضمن DEVELOPER_IDS
        """
        return user_id == self.PRIMARY_OWNER_ID or user_id in self.DEVELOPER_IDS

    def is_owner(self, user_id: int) -> bool:
        """هل المستخدم المالك الأساسي فقط (وليس مطوراً إضافياً)؟"""
        return user_id == self.PRIMARY_OWNER_ID

    def get_detector_env(self) -> Dict[str, str]:
        """
        يُصدّر إعدادات الـdetectors كـ dict.

        الاستخدام الموصى به في bot.py:
            # قبل استيراد handlers_message_detectors
            for k, v in CONFIG.get_detector_env().items():
                os.environ.setdefault(k, v)
        """
        def _b(x: bool) -> str:
            return "1" if x else "0"

        return {
            # ─── Layer toggles (15) ───
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

            # ─── Anti-Evasion (24) ───
            "ANTIEVASION_ENTITY_LINK": _b(self.ANTIEVASION_ENTITY_LINK),
            "ANTIEVASION_BUTTON_LINK": _b(self.ANTIEVASION_BUTTON_LINK),
            "ANTIEVASION_SCHEMELESS_URL": _b(self.ANTIEVASION_SCHEMELESS_URL),
            "ANTIEVASION_HOMOGLYPH": _b(self.ANTIEVASION_HOMOGLYPH),
            "ANTIEVASION_COMBINING": _b(self.ANTIEVASION_COMBINING),
            "ANTIEVASION_COMPACT_WORDS": _b(self.ANTIEVASION_COMPACT_WORDS),
            "ANTIEVASION_EMOJI_SEPARATOR": _b(self.ANTIEVASION_EMOJI_SEPARATOR),
            "ANTIEVASION_BUTTON_WEBAPP": _b(self.ANTIEVASION_BUTTON_WEBAPP),
            "ANTIEVASION_BUTTON_LOGINURL": _b(self.ANTIEVASION_BUTTON_LOGINURL),
            "ANTIEVASION_LEETSPEAK": _b(self.ANTIEVASION_LEETSPEAK),
            "ANTIEVASION_TG_SCHEME": _b(self.ANTIEVASION_TG_SCHEME),
            "ANTIEVASION_AT_CHANNEL": _b(self.ANTIEVASION_AT_CHANNEL),
            "ANTIEVASION_EMAIL": _b(self.ANTIEVASION_EMAIL),
            "ANTIEVASION_PUNYCODE": _b(self.ANTIEVASION_PUNYCODE),
            "ANTIEVASION_IPV4_SCHEMELESS": _b(self.ANTIEVASION_IPV4_SCHEMELESS),
            "ANTIEVASION_MULTILINE_URL": _b(self.ANTIEVASION_MULTILINE_URL),
            "ANTIEVASION_VENUE_VCARD": _b(self.ANTIEVASION_VENUE_VCARD),
            "ANTIEVASION_POLL": _b(self.ANTIEVASION_POLL),
            "ANTIEVASION_EMOJI_IN_DOMAIN": _b(self.ANTIEVASION_EMOJI_IN_DOMAIN),
            "ANTIEVASION_UNICODE_DOTS": _b(self.ANTIEVASION_UNICODE_DOTS),
            "ANTIEVASION_EXTENDED_COMBINING": _b(self.ANTIEVASION_EXTENDED_COMBINING),
            "ANTIEVASION_EXTRA_SCRIPTS": _b(self.ANTIEVASION_EXTRA_SCRIPTS),
            "ANTIEVASION_ALT_SCHEMES": _b(self.ANTIEVASION_ALT_SCHEMES),
            "ANTIEVASION_RANDOM_DOMAIN": _b(self.ANTIEVASION_RANDOM_DOMAIN),

            # ─── Layer settings ───
            "VIDEO_MAX_FRAMES": str(self.VIDEO_MAX_FRAMES),
            "VIDEO_FRAME_INTERVAL_SEC": str(self.VIDEO_FRAME_INTERVAL_SEC),
            "NSFW_MODEL_ENABLED": _b(self.NSFW_MODEL_ENABLED),
            "NSFW_THRESHOLD": str(self.NSFW_THRESHOLD),
            "NSFW_SIGHTENGINE_MAX_BYTES": str(self.NSFW_SIGHTENGINE_MAX_BYTES),
            "AUDIO_USE_WHISPER": _b(self.AUDIO_USE_WHISPER),
            "AUDIO_NOISE_REDUCE": _b(self.AUDIO_NOISE_REDUCE),
            "URL_ENRICH_ENABLED": _b(self.URL_ENRICH_ENABLED),
            "URL_EXPAND_TIMEOUT": str(self.URL_EXPAND_TIMEOUT),
            "URL_EXPAND_CONNECT_TIMEOUT": str(self.URL_EXPAND_CONNECT_TIMEOUT),
            "URL_EXPAND_READ_TIMEOUT": str(self.URL_EXPAND_READ_TIMEOUT),
            "URL_EXPAND_MAX_HOPS": str(self.URL_EXPAND_MAX_HOPS),
            "URL_ENRICH_MAX_URLS": str(self.URL_ENRICH_MAX_URLS),
            "WHOIS_ENABLED": _b(self.WHOIS_ENABLED),
            "WHOIS_NEW_DOMAIN_DAYS": str(self.WHOIS_NEW_DOMAIN_DAYS),
            "SAFE_BROWSING_API_KEY": self.SAFE_BROWSING_API_KEY,
            "OCR_LANGUAGES": self.OCR_LANGUAGES,

            # ─── Pool + Async ───
            "DETECTOR_POOL_WORKERS": str(self.DETECTOR_POOL_WORKERS),
            "POOL_TASK_TIMEOUT": str(self.POOL_TASK_TIMEOUT),
            "ASYNC_NETWORK_ENABLED": _b(self.ASYNC_NETWORK_ENABLED),
            "ASYNC_NETWORK_TIMEOUT": str(self.ASYNC_NETWORK_TIMEOUT),

            # ─── Circuit Breaker + Cache ───
            "SE_CIRCUIT_FAILURE_THRESHOLD": str(self.SE_CIRCUIT_FAILURE_THRESHOLD),
            "SE_CIRCUIT_OPEN_SEC": str(self.SE_CIRCUIT_OPEN_SEC),
            "NORMALIZE_CACHE_MAX": str(self.NORMALIZE_CACHE_MAX),

            # ─── Debug ───
            "DEBUG_DIAG": _b(self.DEBUG_DIAG),
            "DEBUG_SPAM": _b(self.DEBUG_SPAM),

            # ─── Arabic Short Whitelist (v4.0.9) 🆕 ───
            "ARABIC_SHORT_WHITELIST_ENABLED": _b(self.ARABIC_SHORT_WHITELIST_ENABLED),
            "ARABIC_SHORT_MAX_CHARS": str(self.ARABIC_SHORT_MAX_CHARS),
            "ARABIC_SHORT_MAX_WORDS": str(self.ARABIC_SHORT_MAX_WORDS),
            "ARABIC_DOMINANCE_RATIO": str(self.ARABIC_DOMINANCE_RATIO),
            "FINAL_THRESHOLD": str(self.FINAL_THRESHOLD),
        }

    def get_pool_env(self) -> Dict[str, Any]:
        """
        helper لـ main.py v5.6.12 — إعدادات pool فقط.

        الاستخدام:
            from config import CONFIG
            pool_env = CONFIG.get_pool_env()
        """
        return {
            "workers": self.DETECTOR_POOL_WORKERS,
            "task_timeout": self.POOL_TASK_TIMEOUT,
            "async_network_enabled": self.ASYNC_NETWORK_ENABLED,
            "async_network_timeout": self.ASYNC_NETWORK_TIMEOUT,
            "circuit_failure_threshold": self.SE_CIRCUIT_FAILURE_THRESHOLD,
            "circuit_open_sec": self.SE_CIRCUIT_OPEN_SEC,
            "normalize_cache_max": self.NORMALIZE_CACHE_MAX,
        }

    def get_pg_pool_env(self) -> Dict[str, Any]:
        """
        🆕 v7.0.3: إعدادات PostgreSQL pool lifecycle.
        helper لـ database.py v7.7.60+.
        """
        return {
            "max_inactive_lifetime": self.PG_MAX_INACTIVE_LIFETIME,
            "ping_idle_threshold": self.PG_CONN_PING_IDLE_THRESHOLD,
            "ping_timeout": self.PG_CONN_PING_TIMEOUT,
            "tcp_keepidle": self.PG_TCP_KEEPIDLE,
            "tcp_keepintvl": self.PG_TCP_KEEPINTVL,
            "tcp_keepcnt": self.PG_TCP_KEEPCNT,
            "statement_timeout_ms": self.PG_STATEMENT_TIMEOUT_MS,
            "idle_tx_timeout_ms": self.PG_IDLE_TX_TIMEOUT_MS,
            "command_timeout": self.PG_COMMAND_TIMEOUT,
        }

    def apply_detector_env(self, *, override: bool = False) -> int:
        """
        يضبط متغيرات detectors في os.environ.
        Returns: عدد المتغيرات المضبوطة.
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
        errors: List[str] = []
        warnings: List[str] = []

        # ─── 1. الإعدادات الحرجة ───
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

        # 👑 v7.0.2 DEV-3: تحقق من تكرار المالك في DEVELOPER_IDS
        if (self.PRIMARY_OWNER_ID > 0
                and self.PRIMARY_OWNER_ID in self.DEVELOPER_IDS):
            warnings.append(
                f"PRIMARY_OWNER_ID ({self.PRIMARY_OWNER_ID}) موجود أيضاً "
                f"في DEVELOPER_IDS — تكرار غير مؤذٍ لكن زائد. "
                f"يُفضَّل إزالته من DEVELOPER_IDS."
            )

        if self.ENVIRONMENT not in (
            "production", "development", "staging", "test"
        ):
            warnings.append(
                f"ENVIRONMENT غير معروف: {self.ENVIRONMENT!r} — "
                f"سيُعامَل كـ production."
            )

        # ─── 2. النشر ───
        if self.MIN_PUBLISH_INTERVAL < 1:
            errors.append("MIN_PUBLISH_INTERVAL يجب أن يكون أكبر من 0")

        if self.DEFAULT_PUBLISH_INTERVAL < self.MIN_PUBLISH_INTERVAL:
            errors.append(
                f"DEFAULT_PUBLISH_INTERVAL ({self.DEFAULT_PUBLISH_INTERVAL}) "
                f"يجب أن يكون >= MIN_PUBLISH_INTERVAL ({self.MIN_PUBLISH_INTERVAL})"
            )

        if self.MAX_CHANNELS_PER_CYCLE < 1:
            errors.append("MAX_CHANNELS_PER_CYCLE يجب أن يكون أكبر من 0")

        # ─── 3. الموارد والشبكة ───
        if self.WEB_PORT < 1 or self.WEB_PORT > 65535:
            errors.append(f"WEB_PORT غير صالح: {self.WEB_PORT}")

        if self.MAX_BACKUPS < 1:
            errors.append("MAX_BACKUPS يجب أن يكون أكبر من 0")
        elif self.MAX_BACKUPS > 100:
            errors.append(
                f"MAX_BACKUPS مرتفع جداً ({self.MAX_BACKUPS}) — الحد 100."
            )

        if self.DB_POOL_SIZE < 1 or self.DB_POOL_SIZE > 100:
            errors.append(f"DB_POOL_SIZE غير صالح: {self.DB_POOL_SIZE}")

        if self.DB_POOL_MIN_SIZE < 1:
            errors.append("DB_POOL_MIN_SIZE يجب أن يكون أكبر من 0")

        if self.DB_POOL_MIN_SIZE >= self.DB_POOL_SIZE:
            errors.append(
                f"DB_POOL_MIN_SIZE ({self.DB_POOL_MIN_SIZE}) "
                f"يجب أن يكون < DB_POOL_SIZE ({self.DB_POOL_SIZE})"
            )

        if self.PUBLISH_DB_CONCURRENCY < 1 or self.PUBLISH_DB_CONCURRENCY > 10:
            errors.append(
                f"PUBLISH_DB_CONCURRENCY يجب أن يكون بين 1 و 10: "
                f"{self.PUBLISH_DB_CONCURRENCY}"
            )

        if self.MAX_GLOBAL_BANNED_WORDS < 1:
            errors.append(
                f"MAX_GLOBAL_BANNED_WORDS يجب أن يكون > 0"
            )

        # 🆕 v7.0.3: تحقق من DB pool tuning
        if self.PG_MAX_INACTIVE_LIFETIME < 5.0:
            warnings.append(
                f"PG_MAX_INACTIVE_LIFETIME ({self.PG_MAX_INACTIVE_LIFETIME}s) "
                f"منخفض جداً — قد يسبب إعادة إنشاء اتصالات متكررة."
            )
        elif self.PG_MAX_INACTIVE_LIFETIME > 300.0:
            warnings.append(
                f"PG_MAX_INACTIVE_LIFETIME ({self.PG_MAX_INACTIVE_LIFETIME}s) "
                f"مرتفع جداً — قد يسبب استعلامات بطيئة على اتصالات ميتة."
            )

        # ─── 4. الميزات الاختيارية ───
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

        # ─── 5. طبقات كشف السبام ───

        # Pool settings
        if self.DETECTOR_POOL_WORKERS < 1 or self.DETECTOR_POOL_WORKERS > 64:
            errors.append(
                f"DETECTOR_POOL_WORKERS خارج النطاق [1-64]: "
                f"{self.DETECTOR_POOL_WORKERS}"
            )

        if self.POOL_TASK_TIMEOUT < 1.0 or self.POOL_TASK_TIMEOUT > 600.0:
            warnings.append(
                f"POOL_TASK_TIMEOUT ({self.POOL_TASK_TIMEOUT}s) "
                f"خارج النطاق المُوصى به [1-600]"
            )

        if self.ASYNC_NETWORK_TIMEOUT < 0.5 or self.ASYNC_NETWORK_TIMEOUT > 60.0:
            warnings.append(
                f"ASYNC_NETWORK_TIMEOUT ({self.ASYNC_NETWORK_TIMEOUT}s) "
                f"خارج النطاق [0.5-60]"
            )

        if self.SE_CIRCUIT_FAILURE_THRESHOLD < 1:
            errors.append(
                f"SE_CIRCUIT_FAILURE_THRESHOLD يجب أن يكون >= 1"
            )

        if self.SE_CIRCUIT_OPEN_SEC < 5.0 or self.SE_CIRCUIT_OPEN_SEC > 3600.0:
            warnings.append(
                f"SE_CIRCUIT_OPEN_SEC ({self.SE_CIRCUIT_OPEN_SEC}s) "
                f"خارج النطاق [5-3600]"
            )

        if self.NORMALIZE_CACHE_MAX < 16:
            errors.append("NORMALIZE_CACHE_MAX صغير جداً (< 16)")
        elif self.NORMALIZE_CACHE_MAX > 65536:
            warnings.append(
                f"NORMALIZE_CACHE_MAX مرتفع جداً ({self.NORMALIZE_CACHE_MAX})"
            )

        if self.NSFW_SIGHTENGINE_MAX_BYTES < 1024:
            errors.append("NSFW_SIGHTENGINE_MAX_BYTES صغير جداً")

        # ✅ v7.0.1: NSFW layer بدون model
        if self.NSFW_LAYER_ENABLED and not self.NSFW_MODEL_ENABLED:
            if not self.HAS_SIGHTENGINE:
                warnings.append(
                    "NSFW_LAYER_ENABLED=1 لكن NSFW_MODEL_ENABLED=0 و "
                    "Sightengine API غير مُهيَّأ — "
                    "كشف NSFW معطّل تماماً! "
                    "أضف SIGHTENGINE_API_USER/SECRET أو فعّل NSFW_MODEL_ENABLED."
                )

        # URL layer بدون Safe Browsing
        if self.URL_LAYER_ENABLED and not self.SAFE_BROWSING_API_KEY:
            warnings.append(
                "URL_LAYER_ENABLED=1 لكن SAFE_BROWSING_API_KEY فارغ — "
                "دقة كشف الروابط ستكون أقل."
            )

        # 🆕 v7.0.3: Arabic Short Whitelist validation
        if self.ARABIC_SHORT_WHITELIST_ENABLED:
            if self.ARABIC_SHORT_MAX_CHARS < 10:
                warnings.append(
                    f"ARABIC_SHORT_MAX_CHARS ({self.ARABIC_SHORT_MAX_CHARS}) "
                    f"منخفض جداً — قد لا يعمل whitelist بشكل صحيح."
                )
            if self.ARABIC_SHORT_MAX_WORDS < 2:
                warnings.append(
                    f"ARABIC_SHORT_MAX_WORDS ({self.ARABIC_SHORT_MAX_WORDS}) "
                    f"منخفض جداً — قد لا يعمل whitelist بشكل صحيح."
                )
            if self.ARABIC_DOMINANCE_RATIO < 0.3:
                warnings.append(
                    f"ARABIC_DOMINANCE_RATIO ({self.ARABIC_DOMINANCE_RATIO}) "
                    f"منخفض جداً — نصوص مختلطة قد تُصنَّف عربية."
                )
            elif self.ARABIC_DOMINANCE_RATIO > 0.95:
                warnings.append(
                    f"ARABIC_DOMINANCE_RATIO ({self.ARABIC_DOMINANCE_RATIO}) "
                    f"مرتفع جداً — رسائل عربية بها كلمات إنجليزية لن تُدرج."
                )

        if self.FINAL_THRESHOLD < 1 or self.FINAL_THRESHOLD > 50:
            warnings.append(
                f"FINAL_THRESHOLD ({self.FINAL_THRESHOLD}) خارج النطاق المُوصى به [1-50]"
            )

        # OCR بدون pytesseract
        if self.OCR_LAYER_ENABLED:
            try:
                import pytesseract  # noqa: F401
            except ImportError:
                warnings.append(
                    "OCR_LAYER_ENABLED=1 لكن pytesseract غير مثبت — "
                    "ثبّت: pip install pytesseract Pillow"
                )

        # Video بدون opencv/ffmpeg
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
                    "VIDEO_LAYER_ENABLED=1 لكن opencv/ffmpeg غير متوفرين."
                )

        # Audio بدون pydub
        if self.AUDIO_LAYER_ENABLED:
            try:
                import speech_recognition  # noqa: F401
                from pydub import AudioSegment  # noqa: F401
            except ImportError:
                warnings.append(
                    "AUDIO_LAYER_ENABLED=1 لكن SpeechRecognition/pydub "
                    "غير مثبتين."
                )

        # Stego بدون numpy
        if self.STEGO_LAYER_ENABLED:
            try:
                import numpy  # noqa: F401
            except ImportError:
                warnings.append(
                    "STEGO_LAYER_ENABLED=1 لكن numpy غير مثبت."
                )

        # كل الطبقات معطّلة
        if not self.SPAM_DETECTION_AVAILABLE:
            warnings.append(
                "TEXT_LAYER_ENABLED=0 — محرك كشف السبام معطّل بالكامل!"
            )

        # ─── 6. تحذيرات الإنتاج ───
        if self.ENVIRONMENT == "production" and not self.WEB_PASSWORD:
            warnings.append(
                "WEB_PASSWORD فارغ في الإنتاج — لوحة الويب غير محمية!"
            )

        if self.ENVIRONMENT == "production" and not self.WEB_SECRET_KEY:
            warnings.append(
                "WEB_SECRET_KEY فارغ في الإنتاج."
            )

        if self.ENVIRONMENT == "production" and not self.WEBHOOK_SECRET:
            warnings.append(
                "WEBHOOK_SECRET فارغ في الإنتاج — حماية webhook معطّلة."
            )

        # 🆕 v7.0.3: SB_SECRET اختياري
        if not self.SB_SECRET:
            warnings.append(
                "SB_SECRET فارغ — قد يُعطّل بعض حمايات الحماية الخارجية."
            )

        # ─── النتيجة النهائية ───
        if warnings:
            for w in warnings:
                logger.warning(f"⚠️ {w}")

        if errors:
            error_msg = "\n".join(f"  • {e}" for e in errors)
            raise ValueError(f"❌ أخطاء في الإعدادات:\n{error_msg}")


# ═══════════════════════════════════════════════════════════════════
# PathManager
# ═══════════════════════════════════════════════════════════════════

class PathManager:
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

# تصدير إعدادات detectors إلى os.environ
try:
    _applied = CONFIG.apply_detector_env(override=False)
    if _applied > 0:
        logger.debug(
            f"🛡️ تم تصدير {_applied} متغير detector إلى os.environ"
        )
except Exception as e:
    logger.debug(f"apply_detector_env: {e}")

# التحقق
try:
    CONFIG.validate()
except ValueError as e:
    logger.error(f"❌ {e}")
    raise SystemExit(1)

# ═══════════════════════════════════════════════════════════════════
# سجل الإقلاع
# ═══════════════════════════════════════════════════════════════════

logger.info(
    f"✅ تم تحميل الإعدادات: {CONFIG.BOT_NAME} (@{CONFIG.BOT_USERNAME})"
)
logger.info(f"📁 قاعدة البيانات: {PATHS.DB}")
logger.info(
    f"🔐 المصادقة الثنائية: {'مفعلة' if CONFIG.ENABLE_2FA else 'معطلة'}"
)
logger.info(
    f"📊 NSFW (Sightengine): {'مفعل' if CONFIG.NSFW_ENABLED else 'معطل'}"
)
logger.info(
    f"🗄️ Redis: "
    f"{'متاح ✅' if CONFIG.HAS_REDIS else 'غير متاح'}"
)
logger.info(
    f"📨 QStash: "
    f"{'مُهيَّأ ✅' if CONFIG.HAS_QSTASH else 'غير مُهيَّأ'}"
)
logger.info(
    f"🚀 DB Pool: size={CONFIG.DB_POOL_SIZE} "
    f"min={CONFIG.DB_POOL_MIN_SIZE} "
    f"concurrency={CONFIG.PUBLISH_DB_CONCURRENCY}"
)
logger.info(
    f"🐘 PG Pool Tuning: "
    f"max_inactive={CONFIG.PG_MAX_INACTIVE_LIFETIME:.0f}s "
    f"ping_idle={CONFIG.PG_CONN_PING_IDLE_THRESHOLD:.0f}s "
    f"stmt_timeout={CONFIG.PG_STATEMENT_TIMEOUT_MS}ms"
)
logger.info(
    f"🔒 Webhook secret: "
    f"{'مُهيَّأ ✅' if CONFIG.WEBHOOK_SECRET else 'غير مُهيَّأ (اختياري)'}"
)
logger.info(
    f"🛡️ Safe Browsing API: "
    f"{'مُهيَّأ ✅' if CONFIG.HAS_SAFE_BROWSING else 'غير مُهيَّأ ⚠️'}"
)

# 👑 v7.0.2: سجل المطورين (DEV-PERMANENT)
_all_dev_ids = tuple(sorted(set(
    ([CONFIG.PRIMARY_OWNER_ID] if CONFIG.PRIMARY_OWNER_ID else [])
    + list(CONFIG.DEVELOPER_IDS)
)))
if _all_dev_ids:
    logger.info(
        f"👑 المطورون (DEV-PERMANENT) — {len(_all_dev_ids)} "
        f"مُعرَّف: {', '.join(str(u) for u in _all_dev_ids)}"
    )
    if CONFIG.PRIMARY_OWNER_ID:
        logger.info(
            f"   • المالك الأساسي: {CONFIG.PRIMARY_OWNER_ID}"
        )
    if CONFIG.DEVELOPER_IDS:
        logger.info(
            f"   • مطورون إضافيون: "
            f"{', '.join(str(u) for u in CONFIG.DEVELOPER_IDS)}"
        )
    logger.info(
        "   💡 هؤلاء سيحصلون على: اشتراك دائم + "
        "تجاوز max_channels/max_posts + "
        "bypass has_active_subscription/has_used_trial"
    )
else:
    logger.warning(
        "⚠️ لا يوجد مطورون/مالك مُعرَّفون — "
        "لن يُمنح أحد اشتراكاً دائماً. "
        "أضف MAIN_ADMIN_ID أو DEVELOPER_IDS."
    )

# تقرير Spam Detection Engine v4.0.9
_summary = CONFIG.DETECTION_SUMMARY
_enabled_layers = [k for k, v in _summary.items() if v]
_disabled_layers = [k for k, v in _summary.items() if not v]

logger.info(
    f"🛡️ Spam Detection Engine v4.0.9 | "
    f"مُفعَّلة: {len(_enabled_layers)}/{len(_summary)} طبقة"
)
if _enabled_layers:
    logger.info(f"   ✅ مُفعَّلة: {', '.join(_enabled_layers)}")
if _disabled_layers:
    logger.info(f"   ❌ معطّلة: {', '.join(_disabled_layers)}")

logger.info(
    f"   ⚙️ Pool: workers={CONFIG.DETECTOR_POOL_WORKERS} | "
    f"task_timeout={CONFIG.POOL_TASK_TIMEOUT}s | "
    f"async_net={CONFIG.ASYNC_NETWORK_ENABLED}"
)
logger.info(
    f"   🔌 Circuit Breaker: threshold={CONFIG.SE_CIRCUIT_FAILURE_THRESHOLD} | "
    f"open={CONFIG.SE_CIRCUIT_OPEN_SEC}s"
)
logger.info(
    f"   🇸🇦 Arabic Short Whitelist: "
    f"{'✅ مُفعَّل' if CONFIG.ARABIC_SHORT_WHITELIST_ENABLED else '❌ معطّل'} "
    f"(max={CONFIG.ARABIC_SHORT_MAX_CHARS} chars/"
    f"{CONFIG.ARABIC_SHORT_MAX_WORDS} words, "
    f"ratio={CONFIG.ARABIC_DOMINANCE_RATIO})"
)
logger.info(
    f"   🎯 FINAL_THRESHOLD: {CONFIG.FINAL_THRESHOLD}"
)

# NSFW status — v7.0.1: عرض واضح للوضع
if CONFIG.NSFW_LAYER_ENABLED:
    if CONFIG.NSFW_MODEL_ENABLED:
        logger.info("   🔞 NSFW: نموذج محلي (transformers+torch)")
    elif CONFIG.HAS_SIGHTENGINE:
        logger.info("   🔞 NSFW: Sightengine API (خارجي) ✅")
    else:
        logger.warning(
            "   🔞 NSFW: ⚠️ معطّل! لا نموذج محلي ولا Sightengine API"
        )

_antievasion_enabled = sum([
    CONFIG.ANTIEVASION_ENTITY_LINK,
    CONFIG.ANTIEVASION_BUTTON_LINK,
    CONFIG.ANTIEVASION_SCHEMELESS_URL,
    CONFIG.ANTIEVASION_HOMOGLYPH,
    CONFIG.ANTIEVASION_COMBINING,
    CONFIG.ANTIEVASION_COMPACT_WORDS,
    CONFIG.ANTIEVASION_EMOJI_SEPARATOR,
    CONFIG.ANTIEVASION_BUTTON_WEBAPP,
    CONFIG.ANTIEVASION_BUTTON_LOGINURL,
    CONFIG.ANTIEVASION_LEETSPEAK,
    CONFIG.ANTIEVASION_TG_SCHEME,
    CONFIG.ANTIEVASION_AT_CHANNEL,
    CONFIG.ANTIEVASION_EMAIL,
    CONFIG.ANTIEVASION_PUNYCODE,
    CONFIG.ANTIEVASION_IPV4_SCHEMELESS,
    CONFIG.ANTIEVASION_MULTILINE_URL,
    CONFIG.ANTIEVASION_VENUE_VCARD,
    CONFIG.ANTIEVASION_POLL,
    CONFIG.ANTIEVASION_EMOJI_IN_DOMAIN,
    CONFIG.ANTIEVASION_UNICODE_DOTS,
    CONFIG.ANTIEVASION_EXTENDED_COMBINING,
    CONFIG.ANTIEVASION_EXTRA_SCRIPTS,
    CONFIG.ANTIEVASION_ALT_SCHEMES,
    CONFIG.ANTIEVASION_RANDOM_DOMAIN,
])
logger.info(
    f"   🛡️ Anti-Evasion: {_antievasion_enabled}/24 toggle مُفعَّل"
)

# 🆕 v7.0.3: تشخيص الواردات
logger.info(
    f"   🔍 DIAG_INCOMING: "
    f"{'✅ مُفعَّل' if CONFIG.DIAG_INCOMING else '❌ معطّل'}"
)