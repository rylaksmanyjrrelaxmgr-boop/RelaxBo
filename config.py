#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
config.py - إعدادات البوت الأساسية (v3 — منظم بشكل منطقي)
================================================================================
🆕 v3 (إعادة تنظيم شاملة — بدون تغيير سلوكي):
    ✅ إعادة تنظيم الإعدادات في 12 قسم منطقي
    ✅ إضافة المتغيرات المفقودة التي يقرأها database.py مباشرة
       (DB_POOL_SIZE, PUBLISH_DB_CONCURRENCY, إلخ) لتحسين الوضوح
    ✅ ترتيب التحققات في validate() حسب الأهمية المنطقية
    ✅ تحسين التعليقات والتنظيم البصري
    ✅ لا تغيير في أي قيمة افتراضية
    ✅ لا تغيير في أي سلوك
    ✅ 100% توافق خلفي مع v2

🆕 v2 (2026-09-24):
    ✅ safe_float() — حماية من القيم غير الصالحة
    ✅ تحقق من WEB_PASSWORD عند ENVIRONMENT=production
    ✅ ترتيب التحققات حسب الأهمية
================================================================================
"""

import os
import logging
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import List
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
    return value.lower() in ('true', '1', 'yes', 'on')


def safe_str(value: str, default: str = "") -> str:
    """إرجاع قيمة نصية نظيفة."""
    if value is None:
        return default
    return str(value).strip()


# ═══════════════════════════════════════════════════════════════════
# AppConfig — الإعدادات الرئيسية
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AppConfig:
    """
    إعدادات البوت — مقسّمة إلى 12 قسم منطقي:

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
    """

    # ═══════════════════════════════════════════════════════════════
    # 1. الهوية والملاك
    # ═══════════════════════════════════════════════════════════════

    TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
    BOT_NAME: str = os.getenv("BOT_NAME", "ريلاكس مانيجر")
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "Reelaaaxbot").lstrip('@')

    PRIMARY_OWNER_ID: int = safe_int(os.getenv("MAIN_ADMIN_ID", "0"))
    DEVELOPER_IDS: List[int] = field(default_factory=lambda: [
        id for id in [
            safe_int(x)
            for x in os.getenv("DEVELOPER_IDS", "").split(",")
            if x.strip()
        ] if id > 0
    ])
    ANONYMOUS_ADMIN_ID: int = safe_int(
        os.getenv("ANONYMOUS_ADMIN_ID", "1087968824")
    )

    # ═══════════════════════════════════════════════════════════════
    # 2. البيئة والتشخيص
    # ═══════════════════════════════════════════════════════════════

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "production")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    DEBUG_MODE: bool = safe_bool(os.getenv("DEBUG_MODE", "false"))
    BATTERY_SAVER_MODE: bool = safe_bool(
        os.getenv("BATTERY_SAVER_MODE", "false")
    )
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "ar")

    # ═══════════════════════════════════════════════════════════════
    # 3. قاعدة البيانات
    # ═══════════════════════════════════════════════════════════════

    # الاتصال
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
    DB_TIMEOUT: int = safe_int(os.getenv("DB_TIMEOUT", "30"))

    # Pool (يُقرأ في database.py)
    DB_POOL_SIZE: int = safe_int(os.getenv("DB_POOL_SIZE", "20"))
    DB_POOL_MIN_SIZE: int = safe_int(os.getenv("DB_POOL_MIN_SIZE", "2"))
    SQLITE_POOL_SIZE: int = safe_int(os.getenv("SQLITE_POOL_SIZE", "10"))
    MAX_CONNECTIONS: int = safe_int(os.getenv("MAX_CONNECTIONS", "20"))

    # الأداء والصيانة
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

    # التشفير
    DB_ENCRYPTION: bool = safe_bool(os.getenv("DB_ENCRYPTION", "false"))
    DB_ENCRYPTION_PASSWORD: str = os.getenv("DB_ENCRYPTION_PASSWORD", "")

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

    # ✅ v7.9.17: حد التزامن لاستعلامات النشر (منع TooManyConnections)
    PUBLISH_DB_CONCURRENCY: int = safe_int(
        os.getenv("PUBLISH_DB_CONCURRENCY", "4")
    )

    # حدود المحتوى
    MAX_UNPUBLISHED_POSTS: int = safe_int(
        os.getenv("MAX_UNPUBLISHED_POSTS", "1000")
    )
    MAX_POSTS_PER_CHANNEL: int = safe_int(
        os.getenv("MAX_POSTS_PER_CHANNEL", "30")
    )
    MAX_POSTS_PER_SESSION: int = safe_int(
        os.getenv("MAX_POSTS_PER_SESSION", "100")
    )
    SUB_CACHE_TTL: int = safe_int(os.getenv("SUB_CACHE_TTL", "300"))

    # ═══════════════════════════════════════════════════════════════
    # 5. النسخ الاحتياطي
    # ═══════════════════════════════════════════════════════════════

    AUTO_BACKUP_ENABLED: bool = safe_bool(
        os.getenv("AUTO_BACKUP_ENABLED", "true")
    )
    AUTO_BACKUP_SLEEP: int = safe_int(os.getenv("AUTO_BACKUP_SLEEP", "86400"))
    MAX_BACKUPS: int = safe_int(os.getenv("MAX_BACKUPS", "20"))

    # Google Drive (اختياري)
    GOOGLE_CREDENTIALS_FILE: str = os.getenv(
        "GOOGLE_CREDENTIALS_FILE", "credentials.json"
    )
    GOOGLE_DRIVE_FOLDER_ID: str = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "")
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

    # حدود الأقفال (تُقرأ في database.py)
    MAX_USER_LOCKS: int = safe_int(os.getenv("MAX_USER_LOCKS", "10000"))
    MAX_GROUP_LOCKS: int = safe_int(os.getenv("MAX_GROUP_LOCKS", "5000"))
    MAX_CHANNEL_LOCKS: int = safe_int(os.getenv("MAX_CHANNEL_LOCKS", "5000"))
    MAX_PENALTY_LOCKS: int = safe_int(os.getenv("MAX_PENALTY_LOCKS", "5000"))

    # ═══════════════════════════════════════════════════════════════
    # 7. الشبكة والبروكسي والمهام الخلفية
    # ═══════════════════════════════════════════════════════════════

    WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
    WEB_PORT: int = safe_int(os.getenv("PORT", "10000"))

    USE_PROXY: bool = safe_bool(os.getenv("USE_PROXY", "false"))
    PROXY_URL: str = os.getenv("PROXY_URL", "http://127.0.0.1:10809")

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

    WEB_USERNAME: str = os.getenv("WEB_USERNAME", "admin")
    WEB_PASSWORD: str = os.getenv("WEB_PASSWORD", "")
    WEB_SECRET_KEY: str = os.getenv("WEB_SECRET_KEY", "")
    WEB_SESSION_TIMEOUT: int = safe_int(
        os.getenv("WEB_SESSION_TIMEOUT", "3600")
    )
    WEB_RATE_LIMIT: int = safe_int(os.getenv("WEB_RATE_LIMIT", "100"))
    WEB_RATE_WINDOW: int = safe_int(os.getenv("WEB_RATE_WINDOW", "60"))

    # ═══════════════════════════════════════════════════════════════
    # 9. الميزات الاختيارية
    # ═══════════════════════════════════════════════════════════════

    # العملة والاشتراكات
    XTR_CURRENCY: str = os.getenv("XTR_CURRENCY", "XTR")
    GIFT_PLANS_ENABLED: bool = safe_bool(
        os.getenv("GIFT_PLANS_ENABLED", "true")
    )
    PENALTY_SYSTEM_ENABLED: bool = safe_bool(
        os.getenv("PENALTY_SYSTEM_ENABLED", "true")
    )

    # الإحالات
    MAX_DAILY_REFERRALS: int = safe_int(os.getenv("MAX_DAILY_REFERRALS", "5"))
    MAX_GLOBAL_BANNED_WORDS: int = safe_int(
        os.getenv("MAX_GLOBAL_BANNED_WORDS", "100")
    )

    # Redis + QStash
    REDIS_AVAILABLE: bool = safe_bool(os.getenv("REDIS_AVAILABLE", "false"))
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    QSTASH_TOKEN: str = os.getenv("QSTASH_TOKEN", "")
    QSTASH_URL: str = os.getenv("QSTASH_URL", "")

    # ═══════════════════════════════════════════════════════════════
    # 10. المصادقة الثنائية (2FA)
    # ═══════════════════════════════════════════════════════════════

    ENABLE_2FA: bool = safe_bool(os.getenv("ENABLE_2FA", "true"))
    ADMIN_2FA_SECRET: str = os.getenv("ADMIN_2FA_SECRET", "")
    TOKEN_FILE: str = os.getenv("TOKEN_FILE", "token.json")

    # ═══════════════════════════════════════════════════════════════
    # 11. NSFW / Sightengine
    # ═══════════════════════════════════════════════════════════════

    NSFW_ENABLED: bool = safe_bool(os.getenv("NSFW_ENABLED", "false"))
    NSFW_THRESHOLD: float = safe_float(os.getenv("NSFW_THRESHOLD", "0.7"))
    NSFW_FRAMES: int = safe_int(os.getenv("NSFW_FRAMES", "5"))
    NSFW_MAX_FILE_SIZE: int = safe_int(os.getenv("NSFW_MAX_FILE_SIZE", "5242880"))
    NSFW_MAX_VIDEO_SIZE: int = safe_int(
        os.getenv("NSFW_MAX_VIDEO_SIZE", "10485760")
    )
    SIGHTENGINE_API_USER: str = os.getenv("SIGHTENGINE_API_USER", "")
    SIGHTENGINE_API_SECRET: str = os.getenv("SIGHTENGINE_API_SECRET", "")

    # ═══════════════════════════════════════════════════════════════
    # 12. المسارات والملفات والأمان الإضافي
    # ═══════════════════════════════════════════════════════════════

    BANNED_WORDS_FILE: str = os.getenv("BANNED_WORDS_FILE", "./banned_words.txt")
    LANG_PATH: str = os.getenv("LANG_PATH", "./lang")
    TEMP_PATH: str = os.getenv("TEMP_PATH", "/tmp/bot_temp")
    PERSISTENT_DATA_PATH: str = os.getenv("PERSISTENT_DATA_PATH", "/data")

    SB_SECRET: str = os.getenv("SB_SECRET", "")
    SECURITY_LOG_LEVEL: str = os.getenv("SECURITY_LOG_LEVEL", "CRITICAL")

    # ═══════════════════════════════════════════════════════════════
    # التحقق من الإعدادات
    # ═══════════════════════════════════════════════════════════════

    def validate(self) -> None:
        """
        التحقق من القيم المطلوبة — مرتّب حسب الأهمية المنطقية:
          1. الإعدادات الحرجة (البوت لا يعمل بدونها)
          2. إعدادات النشر (جوهر عمل البوت)
          3. إعدادات الشبكة والموارد
          4. إعدادات الميزات الاختيارية
        """
        errors: List[str] = []

        # ─── 1. الإعدادات الحرجة ───────────────────────────────

        if not self.TOKEN:
            errors.append("BOT_TOKEN غير موجود في .env")
        elif len(self.TOKEN) < 20:
            errors.append("BOT_TOKEN يبدو غير صالح (قصير جداً)")

        if self.PRIMARY_OWNER_ID == 0:
            errors.append("MAIN_ADMIN_ID غير موجود في .env")
        elif self.PRIMARY_OWNER_ID < 0:
            errors.append("MAIN_ADMIN_ID يجب أن يكون رقماً موجباً")

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

        if self.DB_POOL_SIZE < 1 or self.DB_POOL_SIZE > 100:
            errors.append(f"DB_POOL_SIZE غير صالح: {self.DB_POOL_SIZE}")

        if self.DB_POOL_MIN_SIZE < 1:
            errors.append("DB_POOL_MIN_SIZE يجب أن يكون أكبر من 0")

        if self.DB_POOL_MIN_SIZE > self.DB_POOL_SIZE:
            errors.append(
                f"DB_POOL_MIN_SIZE ({self.DB_POOL_MIN_SIZE}) "
                f"يجب أن يكون أصغر من "
                f"DB_POOL_SIZE ({self.DB_POOL_SIZE})"
            )

        if self.PUBLISH_DB_CONCURRENCY < 1 or self.PUBLISH_DB_CONCURRENCY > 10:
            errors.append(
                f"PUBLISH_DB_CONCURRENCY يجب أن يكون بين 1 و 10: "
                f"{self.PUBLISH_DB_CONCURRENCY}"
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

        # ─── 5. تحذيرات (ليست أخطاء) ───────────────────────────

        if self.ENVIRONMENT == "production" and not self.WEB_PASSWORD:
            logger.warning(
                "⚠️ WEB_PASSWORD فارغ في بيئة الإنتاج — "
                "لوحة الويب غير محمية! اضبط WEB_PASSWORD في env."
            )

        if self.ENVIRONMENT == "production" and not self.WEB_SECRET_KEY:
            logger.warning(
                "⚠️ WEB_SECRET_KEY فارغ في بيئة الإنتاج — "
                "جلسات الويب غير آمنة."
            )

        # ─── النتيجة النهائية ──────────────────────────────────

        if errors:
            error_msg = "\n".join(f"  • {e}" for e in errors)
            raise ValueError(f"❌ أخطاء في الإعدادات:\n{error_msg}")

    # ═══════════════════════════════════════════════════════════════
    # دوال مساعدة
    # ═══════════════════════════════════════════════════════════════

    def is_developer(self, user_id: int) -> bool:
        """هل المستخدم مطور؟ (المالك أو في قائمة المطورين)."""
        return user_id == self.PRIMARY_OWNER_ID or user_id in self.DEVELOPER_IDS

    def is_owner(self, user_id: int) -> bool:
        """هل المستخدم هو المالك؟"""
        return user_id == self.PRIMARY_OWNER_ID


# ═══════════════════════════════════════════════════════════════════
# PathManager — إدارة المسارات
# ═══════════════════════════════════════════════════════════════════

class PathManager:
    """
    إنشاء وإدارة مسارات المشروع (Singleton).

    المسارات:
      BASE    → مجلد المشروع
      DATA    → قاعدة البيانات
      BACKUPS → النسخ الاحتياطية
      LOGS    → ملفات السجل
      TEMP    → ملفات مؤقتة
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
        self.TEMP = (
            Path(CONFIG.TEMP_PATH)
            if hasattr(CONFIG, 'TEMP_PATH')
            else self.BASE / "temp"
        )

        # إنشاء المجلدات اللازمة
        for d in (self.DATA, self.BACKUPS, self.LOGS, self.TEMP):
            d.mkdir(parents=True, exist_ok=True)

        # إنشاء ملف السجل إن لم يكن موجوداً
        if not self.LOG_FILE.exists():
            self.LOG_FILE.touch(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# التهيئة النهائية
# ═══════════════════════════════════════════════════════════════════

CONFIG = AppConfig()
PATHS = PathManager()

# التحقق من الإعدادات — إيقاف البوت فوراً عند وجود أخطاء
try:
    CONFIG.validate()
except ValueError as e:
    logger.error(f"❌ {e}")
    raise SystemExit(1)

# سجل الإقلاع
logger.info(
    f"✅ تم تحميل الإعدادات: {CONFIG.BOT_NAME} (@{CONFIG.BOT_USERNAME})"
)
logger.info(f"📁 قاعدة البيانات: {PATHS.DB}")
logger.info(
    f"🔐 المصادقة الثنائية: {'مفعلة' if CONFIG.ENABLE_2FA else 'معطلة'}"
)
logger.info(f"📊 NSFW: {'مفعل' if CONFIG.NSFW_ENABLED else 'معطل'}")
logger.info(
    f"🗄️ Redis: {'متاح' if CONFIG.REDIS_AVAILABLE else 'غير متاح'}"
)
logger.info(
    f"🚀 Pool: size={CONFIG.DB_POOL_SIZE} "
    f"min={CONFIG.DB_POOL_MIN_SIZE} "
    f"concurrency={CONFIG.PUBLISH_DB_CONCURRENCY}"
)