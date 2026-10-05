#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
config.py - إعدادات البوت الأساسية (v5 — Production Fixes)
================================================================================
🆕 v5 (REVIEW R4 FIXES):
    🔴 Critical:
        ✅ C1  WEBHOOK_SECRET — مُضاف (مطلوب لـ utils.webhook_handler C2)
                + فحص في validate() يُحذّر عند production

    🟠 Medium:
        ✅ M1  DEVELOPER_IDS — إزالة shadowing لـ id() builtin
        ✅ M2  DEFAULT_LANG — alias موحّد مع DEFAULT_LANGUAGE
        ✅ M3  ENVIRONMENT — تطبيع .strip().lower() + فحص القيم المعروفة
        ✅ M4  get_log_level() — numeric level helper
        ✅ M5  validate() — فحص MAX_GLOBAL_BANNED_WORDS > 0
        ✅ M6  WEB_PORT — fallback من WEB_PORT ثم PORT

    🟡 Minor:
        ✅ m1  safe_str: خيار single-line يُزيل \n\r\t
        ✅ m6  SUB_CACHE_TTL نُقل إلى قسم الكاش
        ✅ m8  DEVELOPER_IDS كـ tuple (frozen=True)
        ✅ m9  AUTO_BACKUP_SLEEP موثّق ويُمرَّر لـ utils (لا hardcode)
        ✅ m10 ANONYMOUS_ADMIN_ID — تحقق إجباري > 0
        ✅ m11 TOKEN_FILE → TWO_FA_TOKEN_FILE (اسم أوضح) + alias خلفي
        ✅ m12 BANNED_WORDS_FILE — مسار مطلق موحّد
        ✅ m13 DB_POOL_MIN_SIZE > DB_POOL_SIZE check موثّق
        ✅ m14 MAX_BACKUPS — حد أعلى 100

🆕 v4 (إصلاح MAX_GLOBAL_BANNED_WORDS):
    ✅ القيمة الافتراضية للحد الأقصى للكلمات المحظورة العالمية:
       من 100 → 10000
    ✅ يحل مشكلة "وصلنا للحد الأقصى (1897/100)"

🆕 v3 (إعادة تنظيم شاملة — بدون تغيير سلوكي):
    ✅ إعادة تنظيم الإعدادات في 12 قسم منطقي
    ✅ إضافة المتغيرات المفقودة التي يقرأها database.py مباشرة
    ✅ ترتيب التحققات في validate() حسب الأهمية المنطقية
    ✅ 100% توافق خلفي مع v2

🆕 v2 (2026-09-24):
    ✅ safe_float() — حماية من القيم غير الصالحة
    ✅ تحقق من WEB_PASSWORD عند ENVIRONMENT=production
================================================================================
"""

import os
import re
import logging
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple
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

    ✅ m1: عند single_line=True يتم طي كل المسافات (بما فيها \n\r\t)
    إلى مسافة واحدة. مفيد للـsecrets و tokens.
    """
    if value is None:
        return default
    s = str(value).strip()
    if single_line:
        s = re.sub(r'\s+', ' ', s)
    return s


def safe_abs_path(value: str, default: str) -> str:
    """
    ✅ m12: توحيد المسارات — يحوّل المسار النسبي إلى مطلق بناءً على BASE_DIR.
    """
    raw = (value or "").strip()
    if not raw:
        raw = default
    p = Path(raw)
    if not p.is_absolute():
        p = BASE_DIR / p
    return str(p)


def _parse_developer_ids() -> Tuple[int, ...]:
    """
    ✅ M1: إزالة shadowing لـ`id()` builtin.
    ✅ m8: يُعيد tuple (متوافق مع frozen=True).
    """
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

    TOKEN: str = safe_str(os.getenv("BOT_TOKEN", ""), single_line=True)
    BOT_NAME: str = safe_str(os.getenv("BOT_NAME", "ريلاكس مانيجر"))
    BOT_USERNAME: str = safe_str(
        os.getenv("BOT_USERNAME", "Reelaaaxbot")
    ).lstrip('@')

    PRIMARY_OWNER_ID: int = safe_int(os.getenv("MAIN_ADMIN_ID", "0"))
    # ✅ M1 + m8: tuple بدل list + lambda نظيفة بدون shadowing
    DEVELOPER_IDS: Tuple[int, ...] = field(default_factory=_parse_developer_ids)
    ANONYMOUS_ADMIN_ID: int = safe_int(
        os.getenv("ANONYMOUS_ADMIN_ID", "1087968824")
    )

    # ═══════════════════════════════════════════════════════════════
    # 2. البيئة والتشخيص
    # ═══════════════════════════════════════════════════════════════

    # ✅ M3: تطبيع القيمة (lower + strip) لتفادي "Production" != "production"
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

    # ✅ M2: alias موحّد — بعض الوحدات (utils.py) تقرأ DEFAULT_LANG
    # (لا يمكن أن يكون حقل dataclass property بسبب frozen=True، لذا
    #  نُعرّفه كـ@property على مستوى الفئة — انظر أدناه)
    # DEFAULT_LANG → @property

    # ═══════════════════════════════════════════════════════════════
    # 3. قاعدة البيانات
    # ═══════════════════════════════════════════════════════════════

    # الاتصال
    DATABASE_URL: str = safe_str(
        os.getenv("DATABASE_URL", ""), single_line=True
    )
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

    # ═══════════════════════════════════════════════════════════════
    # 5. النسخ الاحتياطي
    # ═══════════════════════════════════════════════════════════════

    AUTO_BACKUP_ENABLED: bool = safe_bool(
        os.getenv("AUTO_BACKUP_ENABLED", "true")
    )
    # ✅ m9: القيمة الافتراضية 86400 (يوم) — utils._do_backup يستخدمها
    AUTO_BACKUP_SLEEP: int = safe_int(os.getenv("AUTO_BACKUP_SLEEP", "86400"))
    MAX_BACKUPS: int = safe_int(os.getenv("MAX_BACKUPS", "20"))

    # Google Drive (اختياري)
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

    # ✅ m6: SUB_CACHE_TTL انتقل إلى هنا (منطقياً كاش، لا نشر)
    SUB_CACHE_TTL: int = safe_int(os.getenv("SUB_CACHE_TTL", "300"))

    # حدود الأقفال (تُقرأ في database.py)
    MAX_USER_LOCKS: int = safe_int(os.getenv("MAX_USER_LOCKS", "10000"))
    MAX_GROUP_LOCKS: int = safe_int(os.getenv("MAX_GROUP_LOCKS", "5000"))
    MAX_CHANNEL_LOCKS: int = safe_int(os.getenv("MAX_CHANNEL_LOCKS", "5000"))
    MAX_PENALTY_LOCKS: int = safe_int(os.getenv("MAX_PENALTY_LOCKS", "5000"))

    # ═══════════════════════════════════════════════════════════════
    # 7. الشبكة والبروكسي والمهام الخلفية
    # ═══════════════════════════════════════════════════════════════

    WEB_HOST: str = safe_str(os.getenv("WEB_HOST", "0.0.0.0"))

    # ✅ M6: fallback من WEB_PORT ثم PORT (لسهولة الضبط)
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

    # ✅ C1: WEBHOOK_SECRET — مطلوب لـ utils.webhook_handler (C2 fix)
    # إذا كان فارغاً، تُعطَّل حماية X-Telegram-Bot-Api-Secret-Token تلقائياً
    # (متوافق خلفياً مع السلوك السابق) لكن يُحذَّر في production.
    WEBHOOK_SECRET: str = safe_str(
        os.getenv("WEBHOOK_SECRET", ""), single_line=True
    )

    # ═══════════════════════════════════════════════════════════════
    # 9. الميزات الاختيارية
    # ═══════════════════════════════════════════════════════════════

    # العملة والاشتراكات
    XTR_CURRENCY: str = safe_str(os.getenv("XTR_CURRENCY", "XTR"))
    GIFT_PLANS_ENABLED: bool = safe_bool(
        os.getenv("GIFT_PLANS_ENABLED", "true")
    )
    PENALTY_SYSTEM_ENABLED: bool = safe_bool(
        os.getenv("PENALTY_SYSTEM_ENABLED", "true")
    )

    # الإحالات
    MAX_DAILY_REFERRALS: int = safe_int(os.getenv("MAX_DAILY_REFERRALS", "5"))

    # ✅ v4: رُفع الافتراضي من 100 → 10000
    # السبب: بعض deployments تحتوي على 1897+ كلمة محظورة عالمية
    MAX_GLOBAL_BANNED_WORDS: int = safe_int(
        os.getenv("MAX_GLOBAL_BANNED_WORDS", "10000")
    )

    # Redis + QStash
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

    # ✅ m11: اسم أوضح — يمنع اللبس مع BOT_TOKEN
    # يُحتفظ بـ TOKEN_FILE كـ alias خلفي عبر @property
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

    # ✅ m12: مسار مطلق موحّد
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
    # Properties (aliases خلفية)
    # ═══════════════════════════════════════════════════════════════

    @property
    def DEFAULT_LANG(self) -> str:
        """✅ M2: alias لـ DEFAULT_LANGUAGE — متوافق مع utils.py."""
        return self.DEFAULT_LANGUAGE

    @property
    def TOKEN_FILE(self) -> str:
        """✅ m11: alias خلفي لـ TWO_FA_TOKEN_FILE."""
        return self.TWO_FA_TOKEN_FILE

    # ═══════════════════════════════════════════════════════════════
    # دوال مساعدة
    # ═══════════════════════════════════════════════════════════════

    def get_log_level(self) -> int:
        """
        ✅ M4: يُرجع numeric logging level من النص.
        يُستخدم في bot.py / setup_logging() بدل LOG_LEVEL مباشرة.
        """
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

        يرفع ValueError عند وجود أخطاء حرجة.
        التحذيرات تُطبع في logger.warning ولا توقف البوت.
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

        # ✅ m10: ANONYMOUS_ADMIN_ID يجب أن يكون موجباً
        if self.ANONYMOUS_ADMIN_ID <= 0:
            errors.append(
                f"ANONYMOUS_ADMIN_ID يجب أن يكون رقماً موجباً: "
                f"{self.ANONYMOUS_ADMIN_ID}"
            )

        # ✅ M3: فحص القيم المعروفة لـ ENVIRONMENT
        if self.ENVIRONMENT not in (
            "production", "development", "staging", "test"
        ):
            logger.warning(
                f"⚠️ ENVIRONMENT غير معروف: {self.ENVIRONMENT!r} — "
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

        # ✅ m14: حد أعلى لـ MAX_BACKUPS
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

        # ✅ m13: min يجب أن يكون < size (لا يساوي) لضمان مرونة pool
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

        # ✅ M5: فحص MAX_GLOBAL_BANNED_WORDS
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

        # ✅ C1: تحذير عند production بدون WEBHOOK_SECRET
        if self.ENVIRONMENT == "production" and not self.WEBHOOK_SECRET:
            logger.warning(
                "⚠️ WEBHOOK_SECRET فارغ في بيئة الإنتاج — "
                "حماية webhook (X-Telegram-Bot-Api-Secret-Token) "
                "معطّلة. اضبط المتغير + استخدمه في set_webhook()."
            )

        # ─── النتيجة النهائية ──────────────────────────────────

        if errors:
            error_msg = "\n".join(f"  • {e}" for e in errors)
            raise ValueError(f"❌ أخطاء في الإعدادات:\n{error_msg}")


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

        # TEMP: استخدم CONFIG.TEMP_PATH إن وُجد وإلا fallback
        try:
            self.TEMP = Path(CONFIG.TEMP_PATH)
        except Exception:
            self.TEMP = self.BASE / "temp"

        # إنشاء المجلدات اللازمة
        for d in (self.DATA, self.BACKUPS, self.LOGS, self.TEMP):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning(f"⚠️ تعذّر إنشاء {d}: {e}")

        # إنشاء ملف السجل إن لم يكن موجوداً
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
logger.info(
    f"🔒 Webhook secret: "
    f"{'مُهيَّأ' if CONFIG.WEBHOOK_SECRET else 'غير مُهيَّأ (اختياري)'}"
)