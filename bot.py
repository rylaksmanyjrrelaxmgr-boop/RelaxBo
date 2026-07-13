#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
ريلاكس مانيجر - بوت متكامل لإدارة القنوات والمجموعات
الإصدار: 19.3.1
"""

import sys
import os
from pathlib import Path
import secrets
import json
import hashlib
import time as time_module
import re
import logging
import traceback
import random
import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from typing import Optional, List, Dict, Any, Tuple
from functools import wraps
from enum import Enum, auto

# ===================== التحقق من إصدار بايثون =====================
def check_python_version():
    required_version = (3, 8)
    current_version = sys.version_info
    if current_version < required_version:
        print(f"❌ يحتاج البوت إلى بايثون {required_version[0]}.{required_version[1]} أو أحدث")
        sys.exit(1)

check_python_version()

# ===================== المسارات الأساسية =====================
def get_base_path() -> Path:
    return Path(__file__).parent.resolve()

BASE_PATH = get_base_path()
DATA_PATH = BASE_PATH / "data"
DB_PATH = DATA_PATH / "bot_data.db"
BACKUP_DIR = BASE_PATH / "backups"
LOG_PATH = BASE_PATH / "logs" / "bot.log"
BANNED_WORDS_FILE = BASE_PATH / "banned_words.txt"
TRANSLATIONS_FILE = BASE_PATH / "translations.json"

DATA_PATH.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# ===================== تثبيت المكتبات =====================
def ensure_package(package_name: str, import_name: str = None) -> bool:
    if import_name is None:
        import_name = package_name
    try:
        __import__(import_name)
        return True
    except ImportError:
        try:
            import subprocess
            print(f"📦 جاري تثبيت {package_name}...")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", package_name, "--quiet"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            __import__(import_name)
            print(f"✅ تم تثبيت {package_name}")
            return True
        except:
            print(f"⚠️ لا يمكن تثبيت {package_name}")
            return False

# تثبيت المكتبات الأساسية
ensure_package("python-dotenv", "dotenv")
ensure_package("aiosqlite")
ensure_package("nest-asyncio", "nest_asyncio")
ensure_package("python-telegram-bot", "telegram")

# ===================== استيراد المكتبات =====================
import nest_asyncio
nest_asyncio.apply()

import aiosqlite
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import TimedOut, NetworkError, BadRequest, Forbidden, Conflict
from telegram.request import HTTPXRequest
import httpx

# ===================== استيراد الملفات المنفصلة =====================

# 1. استيراد الردود التلقائية
try:
    from replies import ALL_REPLIES
    REPLIES_LOADED = True
    print(f"✅ تم تحميل {len(ALL_REPLIES)} رد تلقائي من replies.py")
except ImportError:
    REPLIES_LOADED = False
    ALL_REPLIES = {
        "مرحباً": "أهلاً وسهلاً بك 🤍",
        "السلام عليكم": "وعليكم السلام 🌹",
        "كيف حالك": "الحمد لله بخير ❤️",
    }
    print("⚠️ ملف replies.py غير موجود")

# 2. استيراد الترجمات
try:
    from translations import TRANSLATIONS
    TRANSLATIONS_LOADED = True
    print("✅ تم تحميل الترجمات من translations.py")
except ImportError:
    TRANSLATIONS_LOADED = False
    TRANSLATIONS = {
        "ar": {
            "welcome": "🌿 **مرحباً بك في ريلاكس مانيجر**",
            "admin_only": "🔒 هذا الأمر للمشرفين فقط!",
            "cancelled": "❌ تم الإلغاء",
            "help": "❓ **المساعدة**\n/start - القائمة الرئيسية\n/help - المساعدة"
        },
        "en": {
            "welcome": "🌿 **Welcome to Relax Manager**",
            "admin_only": "🔒 This command is for admins only!",
            "cancelled": "❌ Cancelled",
            "help": "❓ **Help**\n/start - Main Menu\n/help - Help"
        }
    }
    print("⚠️ ملف translations.py غير موجود")

# 3. استيراد الكلمات المحظورة
try:
    from banned_words import BANNED_WORDS, BANNED_PATTERNS
    BANNED_LOADED = True
    print(f"✅ تم تحميل {len(BANNED_WORDS)} كلمة محظورة من banned_words.py")
except ImportError:
    BANNED_LOADED = False
    BANNED_WORDS = []
    BANNED_PATTERNS = []
    print("⚠️ ملف banned_words.py غير موجود")

# 4. استيراد اللغات المدعومة
try:
    from languages import SUPPORTED_LANGUAGES
    LANGUAGES_LOADED = True
    print(f"✅ تم تحميل {len(SUPPORTED_LANGUAGES)} لغة من languages.py")
except ImportError:
    LANGUAGES_LOADED = False
    SUPPORTED_LANGUAGES = {
        'ar': 'العربية 🇸🇦',
        'en': 'English 🇬🇧',
        'fr': 'Français 🇫🇷',
        'tr': 'Türkçe 🇹🇷',
    }
    print("⚠️ ملف languages.py غير موجود")

# 5. استيراد خادم الويب
try:
    from web_server import start_web_server, WEB_SERVER_LOADED
    print("✅ تم تحميل web_server.py")
except ImportError:
    WEB_SERVER_LOADED = False
    print("⚠️ ملف web_server.py غير موجود")

# ===================== إعدادات البوت =====================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❌ BOT_TOKEN غير موجود في ملف .env")

PRIMARY_OWNER_ID = int(os.getenv("MAIN_ADMIN_ID", 0))
if PRIMARY_OWNER_ID == 0:
    raise ValueError("❌ MAIN_ADMIN_ID غير محدد")

BOT_NAME = os.getenv("BOT_NAME", "ريلاكس مانيجر")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Reelaaaxbot")
USE_PROXY = os.getenv("USE_PROXY", "False").lower() == "true"
PROXY_URL = os.getenv("PROXY_URL", "http://127.0.0.1:10809")

MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 20 * 1024 * 1024))
MAX_UNPUBLISHED_POSTS = 1000
MAX_POSTS_PER_SESSION = 50
DB_TIMEOUT = 30
DB_MAX_RETRIES = 3
REQUEST_TIMEOUT = 30
POLL_INTERVAL = 1.0
_ADMIN_CACHE_TTL = 300

# ===================== الثوابت =====================
DEFAULT_RULES = """
📋 **قوانين المجموعة**
━━━━━━━━━━━━━━━━━━━━━━

1️⃣ **احترام الآخرين**
• لا للتطاول أو السب أو الشتائم
• لا للتمييز العنصري أو الديني
• كن مهذبا في حوارك

2️⃣ **المحتوى المسموح**
• المواضيع المفيدة فقط
• لا للمنشورات المكررة
• لا للمحتوى غير اللائق (NSFW)

3️⃣ **الروابط والإعلانات**
• ممنوع نشر الروابط الخارجية
• ممنوع الإعلان عن قنوات أو مجموعات أخرى
• الاستثناء: الروابط المفيدة بموافقة المشرف

4️⃣ **السلوك العام**
• لا للتجسس أو اختراق الخصوصية
• لا للمشاكل الشخصية في المجموعة
• لا للبوتات غير المصرح بها

5️⃣ **العقوبات**
• تحذير أول
• كتم لمدة 24 ساعة
• حظر دائم

━━━━━━━━━━━━━━━━━━━━━━
📌 **للتواصل مع المشرفين:** /support
📌 **للتبليغ عن مخالفة:** @admin
"""

# ===================== دوال الترجمة =====================
user_language = {}

def get_text(user_id: int, key: str) -> str:
    """الحصول على النص المترجم حسب لغة المستخدم"""
    lang = user_language.get(user_id, 'ar')
    if TRANSLATIONS_LOADED:
        lang_data = TRANSLATIONS.get(lang, TRANSLATIONS.get('ar', {}))
        return lang_data.get(key, key)
    # ترجمات مدمجة في حالة عدم وجود ملف
    fallback = {
        "ar": {
            "welcome": "🌿 **مرحباً بك في ريلاكس مانيجر**",
            "main_title": "🌿 **{0}**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 المعرف: `{1}`\n👥 مجموعاتي: {2}\n💎 الاشتراك: {3}\n📡 القناة النشطة: {4}\n📝 المنشورات غير المنشورة: {5}\n⚙️ النشر التلقائي: {6}",
            "no_channels": "لا توجد قنوات",
            "add_channel": "➕ إضافة قناة",
            "my_channels": "📡 قنواتي",
            "add_15_posts": "📥 إضافة 15 منشور",
            "publish_one": "📤 نشر واحد",
            "my_posts_btn": "📋 منشوراتي",
            "recycle": "♻️ إعادة تدوير",
            "stats_btn": "📊 إحصائياتي",
            "my_stats_btn": "📈 إحصائيات كاملة",
            "my_groups_btn": "👥 مجموعاتي",
            "settings_btn": "⚙️ الإعدادات",
            "schedule_btn": "⏰ الجدولة",
            "help_btn": "❓ المساعدة",
            "trial_btn": "🎁 تجربة مجانية",
            "subscribe_btn": "💎 اشتراك",
            "developer_btn": "👨‍💻 المطور",
            "language_btn": "🌐 اللغة",
            "support_btn": "📞 الدعم",
            "referral": "🔗 الإحالات",
            "reminder_settings": "⏰ التذكيرات",
            "translation_settings": "🌐 الترجمة",
            "publish_all": "📤 نشر الكل",
            "updates_btn": "📢 التحديثات",
            "add_to_group": "➕ إضافة إلى مجموعة",
            "admin_panel": "👑 لوحة الأدمن",
            "my_rank_btn": "📊 رتبتي",
            "top_10_btn": "🏆 أفضل 10",
            "schedule_post_btn": "📝 جدولة منشور",
            "channel_stats": "📊 إحصائيات القناة",
            "my_channels_summary": "📊 ملخص قنواتي",
            "auto_on": "مفعل",
            "auto_off": "معطل",
            "subscribed": "✅ مفعل",
            "not_subscribed": "❌ غير مفعل",
            "send_channel_id": "📡 أرسل معرف القناة (مثال: @channel أو -100123456)",
            "channel_added": "✅ تم إضافة القناة {0}",
            "channel_exists": "⚠️ القناة موجودة مسبقاً",
            "no_channels_list": "📭 لا توجد قنوات مسجلة",
            "channels_list": "📡 **قنواتي**\nاختر قناة للتحكم بها:",
            "delete_channel": "🗑️ حذف",
            "channel_deleted": "✅ تم حذف القناة",
            "delete_failed": "❌ فشل الحذف",
            "no_posts": "📭 لا توجد منشورات",
            "my_posts_title": "📋 **منشوراتي غير المنشورة**",
            "confirm_delete": "⚠️ هل أنت متأكد من حذف جميع المنشورات؟",
            "deleted_all": "✅ تم حذف جميع المنشورات",
            "recycled": "♻️ تم إعادة تدوير جميع المنشورات",
            "pending_stats": "📊 **إحصائيات المنشورات**\n━━━━━━━━━━━━━━━━━━━━━━\n📝 غير المنشورة: {0}\n📋 الإجمالي: {1}",
            "stats": "📈 **إحصائياتي الكاملة**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 القنوات: {0}\n📝 إجمالي المنشورات: {1}\n⏳ غير المنشورة: {2}\n👥 المجموعات: {3}\n⚙️ النشر التلقائي: {4}",
            "settings": "⚙️ **الإعدادات**\nاختر الإعداد المطلوب:",
            "disabled": "❌ تعطيل",
            "enabled": "✅ تفعيل",
            "auto_toggled": "✅ تم تغيير حالة النشر التلقائي إلى: {0}",
            "schedule_settings": "⏰ **إعدادات الجدولة**\n━━━━━━━━━━━━━━━━━━━━━━\n{0}\n━━━━━━━━━━━━━━━━━━━━━━\nاختر نوع الجدولة:",
            "interval_minutes": "دقائق: {0}",
            "interval_hours": "ساعات: {0}",
            "interval_days": "أيام: {0}",
            "days_week": "أيام الأسبوع: {0}",
            "specific_dates": "تواريخ محددة: {0}",
            "nothing": "لا شيء",
            "send_minutes": "⏱️ أرسل عدد الدقائق (مثال: 30)",
            "send_hours": "⏱️ أرسل عدد الساعات (مثال: 2)",
            "send_days": "⏱️ أرسل عدد الأيام (مثال: 1)",
            "send_dates": "📅 أرسل التواريخ مفصولة بفواصل (مثال: 2024-12-25,2025-01-01)",
            "send_time": "🕐 أرسل وقت النشر (مثال: 14:30)",
            "interval_set": "✅ تم حفظ الإعدادات",
            "invalid_number": "❌ رقم غير صالح",
            "invalid_date": "❌ تاريخ غير صالح",
            "invalid_time": "❌ وقت غير صالح",
            "days_saved": "✅ تم حفظ أيام النشر",
            "monday": "الإثنين",
            "tuesday": "الثلاثاء",
            "wednesday": "الأربعاء",
            "thursday": "الخميس",
            "friday": "الجمعة",
            "saturday": "السبت",
            "sunday": "الأحد",
            "admin_only": "🔒 هذا الأمر للمشرفين فقط!",
            "group_only": "🔒 هذا الأمر يعمل فقط في المجموعات!",
            "locked": "🔒 تم قفل المجموعة",
            "unlocked": "🔓 تم فتح المجموعة",
            "cancelled": "❌ تم الإلغاء",
            "error": "⚠️ حدث خطأ، حاول مرة أخرى",
            "help": "❓ **المساعدة**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 **الأوامر المتاحة:**\n/start - القائمة الرئيسية\n/trial - تجربة مجانية\n/subscribe - الاشتراك\n/syncgroup - تفعيل المجموعة\n/security - إعدادات الأمان\n/register_hidden_owner - تسجيل مالك مخفي\n/add_hidden_admin - إضافة مشرف مخفي\n/remove_hidden_admin - إزالة مشرف مخفي\n/list_hidden_admins - عرض المشرفين المخفيين\n/rank - رتبتك\n/top - أفضل 10\n/stats - إحصائيات القناة\n/lock - قفل المجموعة\n/unlock - فتح المجموعة\n/schedule - جدولة منشور\n/panel - لوحة التحكم\n/language - تغيير اللغة\n/support - مركز الدعم\n/help - هذه المساعدة\n/developer - المطور\n/updates - التحديثات\n/contests - المسابقات\n/create_contest - إنشاء مسابقة\n/declare_winner - إعلان فائز\n/update_admins - تحديث المشرفين\n/rules - عرض قوانين المجموعة",
            "support_welcome": "📞 **مركز الدعم**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الخدمة المطلوبة:",
            "support_help": "❓ **المساعدة**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 للتواصل مع الدعم:\n• استخدم /support\n• اكتب رسالتك\n• ستصلك تذكرة برقم\n• سنرد عليك بأسرع وقت\n\n📌 للمشاكل التقنية:\n• تأكد من أن البوت مشرف\n• تأكد من صلاحيات البوت\n• راجع إعدادات الأمان",
            "trial_used": "❌ لقد استخدمت التجربة المجانية مسبقاً",
            "already_subscribed": "✅ لديك اشتراك فعال بالفعل",
            "trial": "🎁 **تم تفعيل التجربة المجانية!**\n━━━━━━━━━━━━━━━━━━━━━━\n✅ لديك 30 يوماً مجاناً\n📌 استمتع بجميع الميزات\n💎 يمكنك الاشتراك بعد انتهاء التجربة",
            "subscribe": "💎 **الاشتراك**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الباقة المناسبة لك:\n\n⭐ 1 يوم - 5 نجوم\n⭐ 2 يوم - 9 نجوم\n⭐ شهر (30 يوم) - 50 نجمة\n⭐ 3 أشهر (90 يوم) - 120 نجمة\n\n📌 الدفع عبر نجوم تيليجرام",
            "updates_text": "📢 **آخر التحديثات**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 تابع قناة التحديثات لمعرفة كل جديد:\n• إضافات جديدة\n• تحسينات الأداء\n• إصلاحات الأخطاء\n• ميزات حصرية",
            "referral_title": "🔗 **الإحالات**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 رابط الإحالة الخاص بك:\n`https://t.me/{1}?start=ref_{0}`\n\n👥 عدد المحالين: {3}\n🎁 المكافآت المتاحة: {4} يوم\n⭐ المكافأة لكل إحالة: {5} يوم\n🎁 نقاط الترحيب: {6}",
            "copy_link": "📋 نسخ الرابط",
            "claim_reward": "🎁 صرف المكافآت",
            "referral_list": "📋 قائمة المحالين",
            "no_referrals": "📭 لا توجد إحالات بعد",
            "no_reward_available": "❌ لا توجد مكافآت متاحة للصرف",
            "reward_claimed": "✅ تم صرف {0} يوم اشتراك!",
            "reminder_title": "⏰ **إعدادات التذكيرات**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 تذكير انتهاء الاشتراك: {0}\n📊 تقرير يومي: {1}\n📈 تقرير أسبوعي: {2}\n⏰ التذكير قبل: {3} أيام",
            "reminder_sub": "🔔 تذكير الاشتراك",
            "reminder_daily": "📊 تقرير يومي",
            "reminder_weekly": "📈 تقرير أسبوعي",
            "reminder_days_btn": "⏰ عدد الأيام",
            "reminder_lang_btn": "🌐 لغة الإشعارات",
            "subscription_warning": "⚠️ **تنبيه!**\nاشتراكك ينتهي خلال {0} أيام\nقم بتجديده الآن لتستمر الميزات 💎",
            "daily_stats": "📊 **تقريرك اليومي**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 القنوات: {0}\n📝 إجمالي المنشورات: {1}\n⏳ غير المنشورة: {2}\n👥 المجموعات: {3}",
            "weekly_report": "📈 **تقريرك الأسبوعي**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 القنوات: {0}\n📝 إجمالي المنشورات: {1}\n⏳ غير المنشورة: {2}\n👥 المجموعات: {3}\n🔗 الإحالات: {4}",
            "translation_status_off": "معطلة ❌",
            "translation_status_on": "مفعلة ✅ إلى {0}",
            "translation_settings": "إعدادات الترجمة",
            "translation_how_it_works": "📌 كيفية العمل:\nسيتم ترجمة المنشورات تلقائياً عند النشر إلى اللغة التي تختارها",
            "translation_choose": "اختر لغة الترجمة:",
            "translation_off": "🚫 إيقاف الترجمة",
            "translation_disabled": "✅ تم إيقاف الترجمة",
            "translation_enabled": "✅ تم تفعيل الترجمة إلى {0}",
            "admin_panel": "👑 **لوحة الأدمن**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الإجراء المطلوب:",
            "admin_users": "👥 المستخدمين",
            "admin_banned": "🚫 المحظورين",
            "admin_channels": "📡 القنوات",
            "enter_admin_id": "👑 أرسل معرف المستخدم لإضافته كمشرف:",
            "enter_remove_admin_id": "🗑️ أرسل معرف المستخدم لإزالته من المشرفين:",
            "no_admins": "📭 لا يوجد مشرفون",
            "add_admin_success": "✅ تم إضافة {0} كمشرف",
            "remove_admin_success": "✅ تم إزالة {0} من المشرفين",
            "cannot_remove_main_admin": "❌ لا يمكن إزالة المطور الأساسي",
            "invalid_user_id": "❌ معرف مستخدم غير صالح",
            "select_backup": "💾 اختر النسخة الاحتياطية للاستعادة:",
            "no_backups": "📭 لا توجد نسخ احتياطية",
            "current_allowed_user": "📁 المستخدم الحالي المصرح له بـ /sendcode: {0}",
            "no_allowed_user": "لا يوجد",
            "set_new_sendcode_user": "➕ تعيين مستخدم جديد",
            "sendcode_user_set": "✅ تم تعيين {0} كمستخدم مصرح له بـ /sendcode",
            "confirm_delete_tickets": "⚠️ هل أنت متأكد من حذف جميع تذاكر الدعم؟",
            "tickets_deleted": "✅ تم حذف {0} تذكرة",
            "post_published": "✅ تم نشر المنشور بنجاح",
            "publish_error": "❌ فشل النشر: {0}",
            "not_admin": "❌ أنت لست مشرفاً في هذه المجموعة",
            "contests_active": "🏆 **المسابقات النشطة**\n━━━━━━━━━━━━━━━━━━━━━━\n{0}\n━━━━━━━━━━━━━━━━━━━━━━",
            "no_contests": "📭 لا توجد مسابقات نشطة حالياً.",
            "contest_join": "📝 شارك في {0}",
            "contest_participated": "✅ أنت مشترك بالفعل في هذه المسابقة!",
            "contest_join_success": "✅ تم تسجيل مشاركتك في المسابقة بنجاح!",
            "contest_join_error": "⚠️ أنت مشترك بالفعل أو حدث خطأ.",
            "contest_winners_title": "🏆 **آخر الفائزين في المسابقات**\n━━━━━━━━━━━━━━━━━━━━━━\n",
            "no_winners": "🏆 لا يوجد فائزون سابقون.",
            "contest_created": "✅ **تم إنشاء المسابقة بنجاح!**\n\n📌 العنوان: {0}\n🎁 الجائزة: {1}\n📅 تنتهي: {2} (بتوقيت مكة)\n🆔 معرف المسابقة: `{3}`",
            "contest_created_error": "❌ فشل إنشاء المسابقة.",
            "contest_declared": "✅ **تم إعلان الفائز!**\n\n🏆 المسابقة: {0}\n👤 الفائز: `{1}`\n🎁 الجائزة: {2}",
            "contest_declared_error": "❌ فشل إعلان الفائز.",
            "contest_not_found": "❌ المسابقة غير موجودة.",
            "contest_expired": "❌ هذه المسابقة منتهية بالفعل.",
            "contest_not_participant": "❌ هذا المستخدم لم يشارك في المسابقة.",
            "contest_winner_notification": "🎉 **تهانينا!**\n\nلقد فزت في مسابقة **{0}** 🏆\nالجائزة: {1}\n\nتواصل مع المشرف لاستلام جائزتك.",
            "contest_auto_winner": "🎉 **تهانينا!**\n\nلقد فزت في مسابقة **{0}** 🏆\nالجائزة: {1}\n\nتم اختيارك عشوائياً من بين المشاركين.",
            "contest_creator": "📢 تم إنشاء مسابقة جديدة بواسطة {0}\nالعنوان: {1}",
            "create_contest_title": "📝 **إنشاء مسابقة جديدة**\n\nأرسل **عنوان** المسابقة:",
            "create_contest_description": "📝 أرسل **وصف** المسابقة:",
            "create_contest_prize": "🎁 أرسل **الجائزة** (مثال: 100 نقطة، اشتراك شهر، هدية):",
            "create_contest_end_date": "📅 أرسل **تاريخ الانتهاء** (بتوقيت مكة) بالصيغة:\n`YYYY-MM-DD HH:MM`\nمثال: `2025-07-01 23:59`",
            "contest_date_future": "❌ التاريخ يجب أن يكون في المستقبل!",
            "contest_date_invalid": "❌ صيغة غير صحيحة! استخدم `YYYY-MM-DD HH:MM`",
            "declare_winner_usage": "📝 **الاستخدام:**\n`/declare_winner معرف_المسابقة معرف_المستخدم`\n\nمثال: `/declare_winner 5 123456789`",
            "contests_menu": "🏆 المسابقات",
            "contest_participants_count": "👥 عدد المشاركين: {0}",
            "contest_time_left": "⏳ متبقي {0} يوم",
            "contest_expired_label": "🔴 انتهت",
            "hidden_admin_added": "✅ تم إضافة المشرف المخفي `{0}` بنجاح",
            "hidden_admin_removed": "✅ تم إزالة المشرف المخفي `{0}` بنجاح",
            "hidden_admin_list": "🔒 **قائمة المشرفين المخفيين**\n━━━━━━━━━━━━━━━━━━━━━━\n{0}",
            "no_hidden_admins": "📭 لا يوجد مشرفين مخفيين في هذه المجموعة",
            "hidden_owner_registered": "✅ تم تسجيل المالك المخفي بنجاح",
            "hidden_owner_already": "⚠️ أنت مسجل بالفعل كمالك مخفي",
            "update_admins_success": "✅ **تم تحديث المشرفين بنجاح!**\n\nتم تحديث {0} مشرف في هذه المجموعة.",
            "update_admins_no_changes": "ℹ️ **لا توجد تغييرات في المشرفين.**\nجميع المشرفين محدثون بالفعل.",
            "update_admins_error": "❌ **فشل تحديث المشرفين.**\nالرجاء التأكد من أن البوت مشرف في المجموعة."
        },
        "en": {
            "welcome": "🌿 **Welcome to Relax Manager**\nChoose your language",
            "main_title": "🌿 **{0}**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 ID: `{1}`\n👥 My Groups: {2}\n💎 Subscription: {3}\n📡 Active Channel: {4}\n📝 Unpublished Posts: {5}\n⚙️ Auto Publish: {6}",
            "no_channels": "No channels",
            "add_channel": "➕ Add Channel",
            "my_channels": "📡 My Channels",
            "add_15_posts": "📥 Add 15 Posts",
            "publish_one": "📤 Publish One",
            "my_posts_btn": "📋 My Posts",
            "recycle": "♻️ Recycle",
            "stats_btn": "📊 My Stats",
            "my_stats_btn": "📈 Full Stats",
            "my_groups_btn": "👥 My Groups",
            "settings_btn": "⚙️ Settings",
            "schedule_btn": "⏰ Schedule",
            "help_btn": "❓ Help",
            "trial_btn": "🎁 Free Trial",
            "subscribe_btn": "💎 Subscribe",
            "developer_btn": "👨‍💻 Developer",
            "language_btn": "🌐 Language",
            "support_btn": "📞 Support",
            "referral": "🔗 Referrals",
            "reminder_settings": "⏰ Reminders",
            "translation_settings": "🌐 Translation",
            "publish_all": "📤 Publish All",
            "updates_btn": "📢 Updates",
            "add_to_group": "➕ Add to Group",
            "admin_panel": "👑 Admin Panel",
            "my_rank_btn": "📊 My Rank",
            "top_10_btn": "🏆 Top 10",
            "schedule_post_btn": "📝 Schedule Post",
            "channel_stats": "📊 Channel Stats",
            "my_channels_summary": "📊 My Channels Summary",
            "auto_on": "Enabled",
            "auto_off": "Disabled",
            "subscribed": "✅ Active",
            "not_subscribed": "❌ Inactive",
            "send_channel_id": "📡 Send channel ID (e.g., @channel or -100123456)",
            "channel_added": "✅ Channel {0} added",
            "channel_exists": "⚠️ Channel already exists",
            "no_channels_list": "📭 No channels registered",
            "channels_list": "📡 **My Channels**\nSelect a channel to control:",
            "delete_channel": "🗑️ Delete",
            "channel_deleted": "✅ Channel deleted",
            "delete_failed": "❌ Delete failed",
            "no_posts": "📭 No posts",
            "my_posts_title": "📋 **My Unpublished Posts**",
            "confirm_delete": "⚠️ Are you sure you want to delete all posts?",
            "deleted_all": "✅ All posts deleted",
            "recycled": "♻️ All posts recycled",
            "pending_stats": "📊 **Post Statistics**\n━━━━━━━━━━━━━━━━━━━━━━\n📝 Unpublished: {0}\n📋 Total: {1}",
            "stats": "📈 **My Full Stats**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 Channels: {0}\n📝 Total Posts: {1}\n⏳ Unpublished: {2}\n👥 Groups: {3}\n⚙️ Auto Publish: {4}",
            "settings": "⚙️ **Settings**\nSelect the setting:",
            "disabled": "❌ Disable",
            "enabled": "✅ Enable",
            "auto_toggled": "✅ Auto publish status changed to: {0}",
            "schedule_settings": "⏰ **Schedule Settings**\n━━━━━━━━━━━━━━━━━━━━━━\n{0}\n━━━━━━━━━━━━━━━━━━━━━━\nSelect schedule type:",
            "interval_minutes": "Minutes: {0}",
            "interval_hours": "Hours: {0}",
            "interval_days": "Days: {0}",
            "days_week": "Days of week: {0}",
            "specific_dates": "Specific dates: {0}",
            "nothing": "Nothing",
            "send_minutes": "⏱️ Send number of minutes (e.g., 30)",
            "send_hours": "⏱️ Send number of hours (e.g., 2)",
            "send_days": "⏱️ Send number of days (e.g., 1)",
            "send_dates": "📅 Send dates separated by commas (e.g., 2024-12-25,2025-01-01)",
            "send_time": "🕐 Send publish time (e.g., 14:30)",
            "interval_set": "✅ Settings saved",
            "invalid_number": "❌ Invalid number",
            "invalid_date": "❌ Invalid date",
            "invalid_time": "❌ Invalid time",
            "days_saved": "✅ Days saved",
            "monday": "Monday",
            "tuesday": "Tuesday",
            "wednesday": "Wednesday",
            "thursday": "Thursday",
            "friday": "Friday",
            "saturday": "Saturday",
            "sunday": "Sunday",
            "admin_only": "🔒 This command is for admins only!",
            "group_only": "🔒 This command works only in groups!",
            "locked": "🔒 Group locked",
            "unlocked": "🔓 Group unlocked",
            "cancelled": "❌ Cancelled",
            "error": "⚠️ An error occurred, try again",
            "help": "❓ **Help**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 **Available Commands:**\n/start - Main Menu\n/trial - Free Trial\n/subscribe - Subscribe\n/syncgroup - Activate Group\n/security - Security Settings\n/register_hidden_owner - Register Hidden Owner\n/add_hidden_admin - Add Hidden Admin\n/remove_hidden_admin - Remove Hidden Admin\n/list_hidden_admins - List Hidden Admins\n/rank - Your Rank\n/top - Top 10\n/stats - Channel Stats\n/lock - Lock Group\n/unlock - Unlock Group\n/schedule - Schedule Post\n/panel - Control Panel\n/language - Change Language\n/support - Support Center\n/help - This Help\n/developer - Developer\n/updates - Updates\n/contests - Contests\n/create_contest - Create Contest\n/declare_winner - Declare Winner\n/update_admins - Update Admins\n/rules - View Group Rules",
            "support_welcome": "📞 **Support Center**\n━━━━━━━━━━━━━━━━━━━━━━\nSelect the required service:",
            "support_help": "❓ **Help**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 To contact support:\n• Use /support\n• Write your message\n• You'll get a ticket number\n• We'll reply ASAP",
            "trial_used": "❌ You have already used the free trial",
            "already_subscribed": "✅ You already have an active subscription",
            "trial": "🎁 **Free Trial Activated!**\n━━━━━━━━━━━━━━━━━━━━━━\n✅ You have 30 days free\n📌 Enjoy all features",
            "subscribe": "💎 **Subscription**\n━━━━━━━━━━━━━━━━━━━━━━\nChoose your plan:\n\n⭐ 1 Day - 5 Stars\n⭐ 2 Days - 9 Stars\n⭐ 30 Days (Month) - 50 Stars\n⭐ 90 Days (3 Months) - 120 Stars",
            "updates_text": "📢 **Latest Updates**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 Follow updates channel for news",
            "referral_title": "🔗 **Referrals**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 Your referral link:\n`https://t.me/{1}?start=ref_{0}`\n\n👥 Total Referrals: {3}\n🎁 Available Rewards: {4} days",
            "copy_link": "📋 Copy Link",
            "claim_reward": "🎁 Claim Rewards",
            "referral_list": "📋 Referral List",
            "no_referrals": "📭 No referrals yet",
            "no_reward_available": "❌ No rewards available to claim",
            "reward_claimed": "✅ Claimed {0} days subscription!",
            "reminder_title": "⏰ **Reminder Settings**\n━━━━━━━━━━━━━━━━━━━━━━\n📌 Subscription Reminder: {0}\n📊 Daily Report: {1}\n📈 Weekly Report: {2}\n⏰ Remind Before: {3} days",
            "reminder_sub": "🔔 Subscription Reminder",
            "reminder_daily": "📊 Daily Report",
            "reminder_weekly": "📈 Weekly Report",
            "reminder_days_btn": "⏰ Days Before",
            "reminder_lang_btn": "🌐 Notification Language",
            "subscription_warning": "⚠️ **Warning!**\nYour subscription expires in {0} days",
            "daily_stats": "📊 **Your Daily Report**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 Channels: {0}\n📝 Total Posts: {1}\n⏳ Unpublished: {2}\n👥 Groups: {3}",
            "weekly_report": "📈 **Your Weekly Report**\n━━━━━━━━━━━━━━━━━━━━━━\n📡 Channels: {0}\n📝 Total Posts: {1}\n⏳ Unpublished: {2}\n👥 Groups: {3}\n🔗 Referrals: {4}",
            "translation_status_off": "Disabled ❌",
            "translation_status_on": "Enabled ✅ to {0}",
            "translation_settings": "Translation Settings",
            "translation_how_it_works": "📌 How it works:\nPosts will be automatically translated when published",
            "translation_choose": "Choose translation language:",
            "translation_off": "🚫 Disable Translation",
            "translation_disabled": "✅ Translation disabled",
            "translation_enabled": "✅ Translation enabled to {0}",
            "admin_panel": "👑 **Admin Panel**\n━━━━━━━━━━━━━━━━━━━━━━\nSelect the action:",
            "admin_users": "👥 Users",
            "admin_banned": "🚫 Banned",
            "admin_channels": "📡 Channels",
            "enter_admin_id": "👑 Send user ID to add as admin:",
            "enter_remove_admin_id": "🗑️ Send user ID to remove from admins:",
            "no_admins": "📭 No admins",
            "add_admin_success": "✅ Added {0} as admin",
            "remove_admin_success": "✅ Removed {0} from admins",
            "cannot_remove_main_admin": "❌ Cannot remove main developer",
            "invalid_user_id": "❌ Invalid user ID",
            "select_backup": "💾 Select backup to restore:",
            "no_backups": "📭 No backups",
            "current_allowed_user": "📁 Currently allowed /sendcode user: {0}",
            "no_allowed_user": "None",
            "set_new_sendcode_user": "➕ Set new user",
            "sendcode_user_set": "✅ Set {0} as allowed /sendcode user",
            "confirm_delete_tickets": "⚠️ Are you sure you want to delete all support tickets?",
            "tickets_deleted": "✅ Deleted {0} tickets",
            "post_published": "✅ Post published successfully",
            "publish_error": "❌ Publish failed: {0}",
            "not_admin": "❌ You are not an admin in this group",
            "contests_active": "🏆 **Active Contests**\n━━━━━━━━━━━━━━━━━━━━━━\n{0}\n━━━━━━━━━━━━━━━━━━━━━━",
            "no_contests": "📭 No active contests at the moment.",
            "contest_join": "📝 Join {0}",
            "contest_participated": "✅ You are already participating in this contest!",
            "contest_join_success": "✅ Your participation has been registered successfully!",
            "contest_join_error": "⚠️ You are already participating or an error occurred.",
            "contest_winners_title": "🏆 **Recent Contest Winners**\n━━━━━━━━━━━━━━━━━━━━━━\n",
            "no_winners": "🏆 No previous winners.",
            "contest_created": "✅ **Contest created successfully!**\n\n📌 Title: {0}\n🎁 Prize: {1}\n📅 Ends: {2} (Mecca time)\n🆔 Contest ID: `{3}`",
            "contest_created_error": "❌ Failed to create contest.",
            "contest_declared": "✅ **Winner announced!**\n\n🏆 Contest: {0}\n👤 Winner: `{1}`\n🎁 Prize: {2}",
            "contest_declared_error": "❌ Failed to declare winner.",
            "contest_not_found": "❌ Contest not found.",
            "contest_expired": "❌ This contest has already ended.",
            "contest_not_participant": "❌ This user did not participate in the contest.",
            "contest_winner_notification": "🎉 **Congratulations!**\n\nYou won the contest **{0}** 🏆\nPrize: {1}",
            "contest_auto_winner": "🎉 **Congratulations!**\n\nYou won the contest **{0}** 🏆\nPrize: {1}",
            "contest_creator": "📢 New contest created by {0}\nTitle: {1}",
            "create_contest_title": "📝 **Create New Contest**\n\nSend the contest **Title**:",
            "create_contest_description": "📝 Send the contest **Description**:",
            "create_contest_prize": "🎁 Send the **Prize** (e.g., 100 points, 1 month subscription, gift):",
            "create_contest_end_date": "📅 Send the **End Date** (Mecca time) in format:\n`YYYY-MM-DD HH:MM`",
            "contest_date_future": "❌ The date must be in the future!",
            "contest_date_invalid": "❌ Invalid format! Use `YYYY-MM-DD HH:MM`",
            "declare_winner_usage": "📝 **Usage:**\n`/declare_winner contest_id user_id`",
            "contests_menu": "🏆 Contests",
            "contest_participants_count": "👥 Participants: {0}",
            "contest_time_left": "⏳ {0} days left",
            "contest_expired_label": "🔴 Expired",
            "hidden_admin_added": "✅ Hidden admin `{0}` added successfully",
            "hidden_admin_removed": "✅ Hidden admin `{0}` removed successfully",
            "hidden_admin_list": "🔒 **Hidden Admins List**\n━━━━━━━━━━━━━━━━━━━━━━\n{0}",
            "no_hidden_admins": "📭 No hidden admins in this group",
            "hidden_owner_registered": "✅ Hidden owner registered successfully",
            "hidden_owner_already": "⚠️ You are already registered as hidden owner",
            "update_admins_success": "✅ **Admins updated successfully!**\n\nUpdated {0} admins in this group.",
            "update_admins_no_changes": "ℹ️ **No changes in admins.**\nAll admins are already up to date.",
            "update_admins_error": "❌ **Failed to update admins.**\nPlease make sure the bot is an admin in the group."
        }
    }
    return fallback.get(lang, fallback.get('ar', {})).get(key, key)

async def set_user_language(user_id: int, lang: str):
    """تعيين لغة المستخدم"""
    user_language[user_id] = lang

# ===================== دوال المساعدة =====================
def clean_text_for_telegram(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r'[\u200b\u200c\u200d\u2060\uFEFF\u202a\u202b\u202c\u202d\u202e]', '', text)
    return text.replace('\ufeff', '').replace('\ufffc', '')

def escape_markdown_v2(text: str) -> str:
    if not text:
        return ""
    special_chars = r'([_*\[\]()~`>#+\-=|{}.!\\])'
    return re.sub(special_chars, r'\\\1', text)

def sanitize_text(text: str, max_length: int = 4096) -> str:
    if not text:
        return ""
    cleaned = re.sub(r'<[^>]+>', '', text)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned

async def safe_send(bot, chat_id, text, reply_markup=None, parse_mode="MarkdownV2"):
    if not text:
        return None
    try:
        escaped = escape_markdown_v2(text)
        if len(escaped) > 4096:
            escaped = escaped[:4093] + "..."
        return await bot.send_message(
            chat_id=chat_id,
            text=escaped,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            timeout=REQUEST_TIMEOUT
        )
    except Exception:
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=text[:4096],
                reply_markup=reply_markup,
                timeout=REQUEST_TIMEOUT
            )
        except:
            return None

async def safe_edit(query, text, reply_markup=None, parse_mode="MarkdownV2"):
    if not query or not text:
        return None
    try:
        escaped = escape_markdown_v2(text)
        if len(escaped) > 4096:
            escaped = escaped[:4093] + "..."
        return await query.edit_message_text(
            text=escaped,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            timeout=REQUEST_TIMEOUT
        )
    except Exception:
        try:
            return await query.edit_message_text(
                text=text[:4096],
                reply_markup=reply_markup,
                timeout=REQUEST_TIMEOUT
            )
        except:
            return None

def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def mecca_now():
    return utc_now() + timedelta(hours=3)

def utc_now_iso():
    return utc_now().isoformat()

def mecca_now_iso():
    return mecca_now().isoformat()

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

def log_error(error: Exception, context: dict = None) -> str:
    error_id = secrets.token_hex(4)
    print(f"[{error_id}] خطأ: {error}")
    if context:
        print(f"السياق: {context}")
    return error_id

# ===================== تعريفات الكولباك =====================
class CallbackData:
    MAIN_MENU = "main_menu"
    BACK = "back"
    CHANNELS_ADD = "channels:add"
    CHANNELS_MY = "channels:my_channels"
    CHANNELS_DELETE_PREFIX = "channels:delete:"
    CHANNELS_SELECT_PREFIX = "channels:select:"
    POSTS_ADD_15 = "posts:add_15"
    POSTS_PUBLISH_ONE = "posts:publish_one"
    POSTS_MY = "posts:my_posts"
    POSTS_RECYCLE = "posts:recycle"
    POSTS_DELETE_SINGLE_PREFIX = "posts:delete_single:"
    POSTS_CONFIRM_CLEAR_ALL_PREFIX = "posts:confirm_clear_all:"
    POSTS_CLEAR_ALL_PREFIX = "posts:clear_all:"
    STATS_PENDING = "stats:pending"
    STATS_FULL = "stats:full"
    GROUPS_MY = "groups:my_groups"
    GROUPS_SETTINGS_PREFIX = "groups:settings:"
    SETTINGS_MENU = "settings:menu"
    SETTINGS_TOGGLE_AUTO_PUBLISH = "settings:toggle_auto_publish"
    SETTINGS_TOGGLE_AUTO_RECYCLE = "settings:toggle_auto_recycle"
    SCHEDULE_MENU_PREFIX = "schedule:menu:"
    SCHEDULE_SET_INTERVAL_MINUTES_PREFIX = "schedule:set_interval_minutes:"
    SCHEDULE_SET_INTERVAL_HOURS_PREFIX = "schedule:set_interval_hours:"
    SCHEDULE_SET_INTERVAL_DAYS_PREFIX = "schedule:set_interval_days:"
    SCHEDULE_SET_DAYS_PREFIX = "schedule:set_days:"
    SCHEDULE_SET_DATES_PREFIX = "schedule:set_dates:"
    SCHEDULE_SET_PUBLISH_TIME_PREFIX = "schedule:set_publish_time:"
    SCHEDULE_DAY_SELECT_PREFIX = "schedule:day_select:"
    SCHEDULE_SAVE_DAYS = "schedule:save_days"
    SECURITY_LINKS_PREFIX = "security:links:"
    SECURITY_MENTIONS_PREFIX = "security:mentions:"
    SECURITY_WARN_PREFIX = "security:warn:"
    SECURITY_SLOWMODE_PREFIX = "security:slowmode:"
    SECURITY_BANNED_WORDS_MENU_PREFIX = "security:banned_words_menu:"
    SECURITY_WELCOME_PREFIX = "security:welcome:"
    SECURITY_GOODBYE_PREFIX = "security:goodbye:"
    SECURITY_MAIN = "security:main"
    SECURITY_CLOSE = "security:close"
    BANNED_WORDS_ADD_PREFIX = "banned_words:add:"
    BANNED_WORDS_LIST_PREFIX = "banned_words:list:"
    BANNED_WORDS_REMOVE_PREFIX = "banned_words:remove:"
    HELP = "help"
    SUPPORT_MENU = "support:menu"
    SUPPORT_HELP = "support:help"
    SUPPORT_TICKET = "support:ticket"
    SUPPORT_BACK = "support:back"
    TRIAL = "trial"
    SUBSCRIBE_MENU = "subscribe:menu"
    BUY_SUBSCRIPTION_1 = "buy:subscription_1"
    BUY_SUBSCRIPTION_2 = "buy:subscription_2"
    BUY_SUBSCRIPTION_30 = "buy:subscription_30"
    BUY_SUBSCRIPTION_90 = "buy:subscription_90"
    DEVELOPER = "developer"
    UPDATES = "updates"
    REFERRAL_MENU = "referral:menu"
    REFERRAL_COPY_LINK_PREFIX = "referral:copy_link:"
    REFERRAL_CLAIM_REWARD = "referral:claim_reward"
    REFERRAL_LIST = "referral:list"
    REMINDER_MENU = "reminder:menu"
    REMINDER_TOGGLE_SUB = "reminder:toggle_sub"
    REMINDER_TOGGLE_DAILY = "reminder:toggle_daily"
    REMINDER_TOGGLE_WEEKLY = "reminder:toggle_weekly"
    REMINDER_SET_DAYS = "reminder:set_days"
    REMINDER_SET_LANG = "reminder:set_lang"
    REMINDER_LANG_PREFIX = "reminder:lang:"
    TRANSLATION_MENU = "translation:menu"
    TRANSLATION_OFF = "translation:off"
    TRANSLATION_SET_PREFIX = "translation:set:"
    ADMIN_PANEL = "admin:panel"
    ADMIN_USERS = "admin:users"
    ADMIN_BANNED_USERS = "admin:banned_users"
    ADMIN_UNBAN_ALL_USERS = "admin:unban_all_users"
    ADMIN_ALL_CHANNELS = "admin:all_channels"
    ADMIN_BANNED_CHANNELS = "admin:banned_channels"
    ADMIN_ACTIVATE_ALL_CHANNELS = "admin:activate_all_channels"
    ADMIN_GROUPS = "admin:groups"
    ADMIN_BANNED_GROUPS = "admin:banned_groups"
    ADMIN_UNBAN_ALL_GROUPS = "admin:unban_all_groups"
    ADMIN_BOT_CHANNELS = "admin:bot_channels"
    ADMIN_BANNED_BOT_CHANNELS = "admin:banned_bot_channels"
    ADMIN_UNBAN_ALL_BOT_CHANNELS = "admin:unban_all_bot_channels"
    ADMIN_MONITOR_USERS = "admin:monitor_users"
    ADMIN_ADD_ADMIN = "admin:add_admin"
    ADMIN_REMOVE_ADMIN = "admin:remove_admin"
    ADMIN_RAM = "admin:ram"
    ADMIN_STATS = "admin:stats"
    ADMIN_METRICS = "admin:metrics"
    ADMIN_BACKUP = "admin:backup"
    ADMIN_RESTORE_BACKUP = "admin:restore_backup"
    ADMIN_RESTORE_BACKUP_SELECT_PREFIX = "admin:restore_backup_select:"
    ADMIN_BACKUP_SETTINGS = "admin:backup_settings"
    ADMIN_TOGGLE_AUTO_BACKUP = "admin:toggle_auto_backup"
    ADMIN_CHANGE_INTERVAL = "admin:change_interval"
    ADMIN_SEND_UPDATE = "admin:send_update"
    ADMIN_SET_UPDATE_CHANNEL = "admin:set_update_channel"
    ADMIN_SHOW_UPDATE_CHANNEL = "admin:show_update_channel"
    ADMIN_UPDATES = "admin:updates"
    ADMIN_FORCE_SUBSCRIBE = "admin:force_subscribe"
    ADMIN_SET_FORCE_CHANNEL = "admin:set_force_channel"
    ADMIN_BROADCAST = "admin:broadcast"
    ADMIN_CONFIRM_BROADCAST = "admin:confirm_broadcast"
    ADMIN_SUPPORT_TICKETS = "admin:support_tickets"
    ADMIN_DELETE_ALL_TICKETS = "admin:delete_all_tickets"
    ADMIN_CONFIRM_DELETE_TICKETS = "admin:confirm_delete_tickets"
    ADMIN_MANAGE_SENDCODE = "admin:manage_sendcode"
    ADMIN_SET_SENDCODE_USER = "admin:set_sendcode_user"
    ADMIN_SHOW_LOG_CHANNEL = "admin:show_log_channel"
    ADMIN_SET_LOG_CHANNEL = "admin:set_log_channel"
    ADMIN_REPLIES = "admin:replies"
    ADMIN_ADD_REPLY = "admin:add_reply"
    ADMIN_LIST_REPLIES = "admin:list_replies"
    ADMIN_DEL_REPLY = "admin:del_reply"
    ADMIN_BANNED_WORDS = "admin:banned_words"
    ADMIN_ADD_BANNED_WORD = "admin:add_banned_word"
    ADMIN_LIST_BANNED_WORDS = "admin:list_banned_words"
    ADMIN_REMOVE_BANNED_WORD = "admin:remove_banned_word"
    ADMIN_CREATE_CONTEST = "admin:create_contest"
    ADMIN_DECLARE_WINNER = "admin:declare_winner"
    PANEL_LOCK_PREFIX = "panel:lock:"
    PANEL_UNLOCK_PREFIX = "panel:unlock:"
    PANEL_CLOSE = "panel:close"
    CHECK_SUBSCRIBE = "check_subscribe"
    CANCEL_SESSION = "cancel_session"
    ADVANCED_ACTIONS = "advanced_actions"
    GROUP_ACTION_BAN = "group_action:ban"
    GROUP_ACTION_MUTE = "group_action:mute"
    GROUP_ACTION_WARN = "group_action:warn"
    GROUP_ACTION_KICK = "group_action:kick"
    GROUP_ACTION_RESTRICT = "group_action:restrict"
    GROUP_ACTION_PIN = "group_action:pin"
    GROUP_ACTION_LOG = "group_action:log"
    GROUP_ACTION_UNBAN = "group_action:unban"
    GROUP_MUTE_DURATION_5 = "group_mute_duration:5"
    GROUP_MUTE_DURATION_30 = "group_mute_duration:30"
    GROUP_MUTE_DURATION_60 = "group_mute_duration:60"
    GROUP_MUTE_DURATION_720 = "group_mute_duration:720"
    GROUP_MUTE_DURATION_1440 = "group_mute_duration:1440"
    GROUP_MUTE_DURATION_10080 = "group_mute_duration:10080"
    GROUP_MUTE_DURATION_PERMANENT = "group_mute_duration:permanent"
    SECURITY_SELECT_GROUP = "security_select_group:"
    SECURITY_REFRESH_GROUPS = "security_refresh_groups"
    PENALTY_MENU = "penalty_menu"
    PENALTY_KICK = "penalty:kick"
    PENALTY_BAN = "penalty:ban"
    PENALTY_MUTE = "penalty:mute"
    PUBLISH_ALL_CHANNELS = "publish_all_channels"
    CHANNEL_STATS = "channel_stats"
    CHANNEL_GROWTH = "channel_growth"
    CHANNEL_STATS_REFRESH = "channel_stats_refresh"
    MY_CHANNEL_STATS = "my_channel_stats"
    ADMIN_TOGGLE_CHANNEL_BAN_PREFIX = "admin:toggle_channel_ban:"
    ADMIN_TOGGLE_GROUP_BAN_PREFIX = "admin:toggle_group_ban:"
    CONTESTS_MENU = "contests_menu"
    CONTEST_JOIN_PREFIX = "contest_join:"
    CONTEST_WINNERS = "contest_winners"
    CONTESTS_BACK = "contests_back"
    ADMIN_DEL_CONTEST_PREFIX = "admin:del_contest:"
    HIDDEN_ADMIN_ADD = "hidden_admin:add"
    HIDDEN_ADMIN_REMOVE_PREFIX = "hidden_admin:remove:"
    HIDDEN_ADMIN_LIST = "hidden_admin:list"
    ADMIN_AUTO_REPLY = "admin_auto_reply"
    ADMIN_AUTO_REPLY_SELECT_PREFIX = "admin_auto_reply_select:"
    AUTO_REPLY_MENU_PREFIX = "auto_reply_menu:"
    AUTO_REPLY_TOGGLE_PREFIX = "auto_reply_toggle:"
    AUTO_REPLY_ADMINS_PREFIX = "auto_reply_admins:"
    AUTO_REPLY_RESET_PREFIX = "auto_reply_reset:"
    AUTO_REPLY_CONFIRM_RESET_PREFIX = "auto_reply_confirm_reset:"
    AUTO_REPLY_CANCEL_PREFIX = "auto_reply_cancel:"
    AUTO_REPLY_STATS_PREFIX = "auto_reply_stats:"
    USER_AUTO_REPLY_TOGGLE_PREFIX = "user_auto_reply_toggle:"
    NSFW_SETTINGS = "nsfw_settings"
    NSFW_TOGGLE = "nsfw_toggle"
    NSFW_THRESHOLD_SET = "nsfw_threshold_set"
    UPDATE_ADMINS = "update_admins"
    RULES_SHOW = "rules_show:"
    RULES_CONFIRM_RESET = "rules_confirm_reset:"
    RULES_CANCEL_RESET = "rules_cancel_reset:"

# ===================== تعريفات الحالات =====================
class UserState(Enum):
    NONE = auto()
    ADDING_POSTS = auto()
    WAITING_CHANNEL_ID = auto()
    WAITING_INTERVAL_MINUTES = auto()
    WAITING_INTERVAL_HOURS = auto()
    WAITING_INTERVAL_DAYS = auto()
    WAITING_DATES = auto()
    WAITING_PUBLISH_TIME = auto()
    SELECTING_DAYS = auto()
    WAITING_ADMIN_ID_ADD = auto()
    WAITING_ADMIN_ID_REMOVE = auto()
    WAITING_BROADCAST = auto()
    WAITING_UPDATE_TEXT = auto()
    WAITING_UPDATE_CHANNEL = auto()
    WAITING_FORCE_CHANNEL = auto()
    WAITING_SENDCODE_CONFIRM = auto()
    WAITING_SENDCODE_PASSWORD = auto()
    WAITING_REMINDER_DAYS = auto()
    WAITING_SCHEDULE_POST = auto()
    WAITING_BAN_USER = auto()
    WAITING_MUTE_USER = auto()
    WAITING_WARN_USER = auto()
    WAITING_KICK_USER = auto()
    WAITING_RESTRICT_USER = auto()
    WAITING_UNBAN_USER = auto()
    WAITING_PIN_MESSAGE = auto()
    WAITING_GROUP_BANNED_WORD = auto()
    WAITING_REMOVE_GROUP_BANNED_WORD = auto()
    WAITING_GLOBAL_BANNED_WORD = auto()
    WAITING_REMOVE_GLOBAL_BANNED_WORD = auto()
    WAITING_KEYWORD = auto()
    WAITING_REPLY = auto()
    WAITING_SENDCODE_USER = auto()
    WAITING_LOG_CHANNEL = auto()
    WAITING_2FA = auto()
    SUPPORT_MODE = auto()
    WAITING_CONTEST_TITLE = auto()
    WAITING_CONTEST_DESCRIPTION = auto()
    WAITING_CONTEST_PRIZE = auto()
    WAITING_CONTEST_END_DATE = auto()
    WAITING_CONTEST_ANSWER = auto()
    WAITING_DELETE_CONTEST = auto()
    WAITING_GROUP_SECURITY = auto()
    WAITING_HIDDEN_ADMIN_ADD = auto()
    WAITING_HIDDEN_ADMIN_REMOVE = auto()
    WAITING_AUTO_REPLY_MENU = auto()
    WAITING_NSFW_THRESHOLD = auto()
    WAITING_EXPORT_DATA = auto()
    WAITING_RULES_EDIT = auto()

# ===================== دوال قاعدة البيانات =====================
db_pool = None

async def init_db():
    global db_pool
    db_pool = await aiosqlite.connect(str(DB_PATH), timeout=DB_TIMEOUT)
    await db_pool.execute("PRAGMA journal_mode=WAL")
    await db_pool.execute("PRAGMA synchronous=NORMAL")
    await db_pool.execute("PRAGMA foreign_keys=ON")
    await db_pool.execute("PRAGMA cache_size=-64000")
    await db_pool.execute("PRAGMA temp_store=MEMORY")
    await db_pool.execute("PRAGMA wal_autocheckpoint=1000")
    await db_pool.execute("PRAGMA optimize")
    await db_pool.execute("PRAGMA max_page_count=1000000")
    await db_pool.execute("PRAGMA secure_delete=ON")
    db_pool.row_factory = aiosqlite.Row
    
    # جدول المستخدمين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            auto_publish INTEGER DEFAULT 1,
            banned INTEGER DEFAULT 0,
            trial_used INTEGER DEFAULT 0,
            subscription_end TEXT DEFAULT NULL,
            referral_code TEXT DEFAULT NULL,
            referred_by INTEGER DEFAULT NULL,
            active_channel INTEGER DEFAULT NULL,
            auto_reply_enabled INTEGER DEFAULT 1,
            auto_recycle INTEGER DEFAULT 1,
            last_daily_reward TEXT DEFAULT NULL,
            last_weekly_reward TEXT DEFAULT NULL,
            achievements TEXT DEFAULT '[]'
        )
    """)
    
    # جدول قنوات المستخدمين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id TEXT,
            channel_name TEXT,
            created_at TIMESTAMP,
            banned INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
    """)
    
    # جدول المنشورات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_db_id INTEGER,
            text TEXT,
            media_type TEXT DEFAULT 'text',
            media_file_id TEXT,
            published INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            views_count INTEGER DEFAULT 0,
            last_view_time TIMESTAMP,
            created_at TIMESTAMP,
            FOREIGN KEY(channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
        )
    """)
    
    # جدول الإعدادات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # جدول الردود
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS group_replies (
            keyword TEXT PRIMARY KEY,
            reply TEXT
        )
    """)
    
    # جدول إعدادات الأمان
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS group_security (
            chat_id INTEGER PRIMARY KEY,
            delete_links INTEGER DEFAULT 0,
            delete_mentions INTEGER DEFAULT 0,
            warn_message INTEGER DEFAULT 1,
            slow_mode INTEGER DEFAULT 0,
            slow_mode_seconds INTEGER DEFAULT 5,
            welcome_enabled INTEGER DEFAULT 0,
            welcome_text TEXT DEFAULT 'مرحباً {user} في {chat} 🤍',
            goodbye_enabled INTEGER DEFAULT 0,
            goodbye_text TEXT DEFAULT 'وداعاً {user} 👋',
            delete_banned_words INTEGER DEFAULT 0,
            auto_penalty TEXT DEFAULT 'none',
            auto_mute_duration INTEGER DEFAULT 60
        )
    """)
    
    # جدول إعدادات المجموعة
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS group_settings (
            chat_id INTEGER PRIMARY KEY,
            anti_links INTEGER DEFAULT 0,
            anti_badwords INTEGER DEFAULT 0,
            welcome_msg INTEGER DEFAULT 1,
            mute_all INTEGER DEFAULT 0
        )
    """)
    
    # جدول المشرفين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id INTEGER PRIMARY KEY
        )
    """)
    
    # جدول المجموعات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS bot_groups (
            chat_id INTEGER PRIMARY KEY,
            chat_name TEXT,
            username TEXT,
            added_by INTEGER,
            added_at TIMESTAMP,
            banned INTEGER DEFAULT 0
        )
    """)
    
    # جدول قنوات البوت
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS bot_channels (
            channel_id INTEGER PRIMARY KEY,
            channel_name TEXT,
            added_by INTEGER,
            added_at TIMESTAMP,
            banned INTEGER DEFAULT 0
        )
    """)
    
    # جدول رسائل المستخدمين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_messages (
            user_id INTEGER,
            chat_id INTEGER,
            message_time TIMESTAMP,
            PRIMARY KEY (user_id, chat_id)
        )
    """)
    
    # جدول كاش المستخدمين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS users_cache (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_updated TEXT
        )
    """)
    
    # جدول التحذيرات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_warnings (
            user_id INTEGER,
            chat_id INTEGER,
            warnings INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, chat_id)
        )
    """)
    
    # جدول الكلمات المحظورة
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS banned_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT,
            chat_id INTEGER,
            added_by INTEGER,
            added_at TIMESTAMP,
            UNIQUE(word, chat_id)
        )
    """)
    
    # جدول المالكين المخفيين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS hidden_owner_groups (
            chat_id INTEGER PRIMARY KEY,
            owner_id INTEGER,
            is_hidden INTEGER DEFAULT 1
        )
    """)
    
    # جدول المشرفين المخفيين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS hidden_admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            admin_id INTEGER NOT NULL,
            added_by INTEGER,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chat_id, admin_id)
        )
    """)
    
    # جدول روابط المستخدمين والمجموعات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_groups_link (
            user_id INTEGER,
            chat_id INTEGER,
            PRIMARY KEY(user_id, chat_id)
        )
    """)
    
    # جدول المستويات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_levels (
            user_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1
        )
    """)
    
    # جدول تذاكر الدعم
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            message TEXT,
            ticket_number INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP,
            replied INTEGER DEFAULT 0
        )
    """)
    
    # جدول أقفال المجموعات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS chat_locks (
            chat_id INTEGER PRIMARY KEY,
            locked INTEGER DEFAULT 0,
            locked_at TIMESTAMP,
            locked_by INTEGER
        )
    """)
    
    # جدول الجدولة
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            channel_db_id INTEGER PRIMARY KEY,
            schedule_type TEXT DEFAULT 'interval_minutes',
            interval_minutes INTEGER DEFAULT 12,
            interval_hours INTEGER DEFAULT 0,
            interval_days INTEGER DEFAULT 0,
            days_of_week TEXT DEFAULT '',
            specific_dates TEXT DEFAULT '',
            publish_time TEXT DEFAULT '00:00',
            cron_expression TEXT DEFAULT NULL,
            next_publish_date TEXT,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
        )
    """)
    
    # جدول آخر نشر
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS last_publish (
            channel_db_id INTEGER PRIMARY KEY,
            last_publish_time TIMESTAMP,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE
        )
    """)
    
    # جدول المنشورات المجدولة
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            publish_time TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            fail_count INTEGER DEFAULT 0
        )
    """)
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_time ON scheduled_posts(publish_time)")
    
    # جدول المستخدم المصرح بـ /sendcode
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS allowed_sendcode_user (
            id INTEGER PRIMARY KEY CHECK (id=1),
            user_id INTEGER
        )
    """)
    
    # جدول الإحالات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL,
            referred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_rewarded INTEGER DEFAULT 0,
            UNIQUE(referred_id)
        )
    """)
    
    # جدول مكافآت الإحالات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS referral_rewards (
            user_id INTEGER PRIMARY KEY,
            referral_count INTEGER DEFAULT 0,
            total_reward_days INTEGER DEFAULT 0,
            claimed_reward_days INTEGER DEFAULT 0
        )
    """)
    
    # جدول إعدادات الإحالات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS referral_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # جدول إعدادات التذكيرات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_reminder_settings (
            user_id INTEGER PRIMARY KEY,
            subscription_reminder INTEGER DEFAULT 1,
            daily_stats_reminder INTEGER DEFAULT 0,
            weekly_report INTEGER DEFAULT 1,
            reminder_days_before INTEGER DEFAULT 3,
            last_reminder_sent INTEGER DEFAULT 0,
            notification_lang TEXT DEFAULT 'ar'
        )
    """)
    
    # جدول سجل الإجراءات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS moderation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            user_id INTEGER,
            action TEXT,
            duration_minutes INTEGER,
            moderator_id INTEGER,
            reason TEXT,
            created_at TIMESTAMP
        )
    """)
    
    # جدول ترجمة المستخدمين
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS user_translation (
            user_id INTEGER PRIMARY KEY,
            lang TEXT DEFAULT 'off'
        )
    """)
    
    # جدول إحصائيات القنوات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS channel_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_db_id INTEGER NOT NULL,
            total_posts INTEGER DEFAULT 0,
            published_posts INTEGER DEFAULT 0,
            unpublished_posts INTEGER DEFAULT 0,
            total_views INTEGER DEFAULT 0,
            avg_views_per_post REAL DEFAULT 0,
            last_post_time TIMESTAMP,
            avg_time_between_posts REAL DEFAULT 0,
            best_publish_hour INTEGER DEFAULT 0,
            best_publish_day INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_db_id) REFERENCES user_channels(id) ON DELETE CASCADE,
            UNIQUE(channel_db_id)
        )
    """)
    
    # جدول جلسات الويب
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS web_sessions (
            session_id TEXT PRIMARY KEY,
            user_data TEXT,
            expires INTEGER
        )
    """)
    
    # جدول المسابقات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS contests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creator_id INTEGER,
            title TEXT,
            description TEXT,
            prize TEXT,
            end_date TEXT,
            status TEXT DEFAULT 'active',
            winner_id INTEGER,
            created_at TIMESTAMP,
            contest_type TEXT DEFAULT 'raffle'
        )
    """)
    
    # جدول مشاركي المسابقات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS contest_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            contest_id INTEGER,
            answer TEXT,
            joined_at TIMESTAMP,
            UNIQUE(user_id, contest_id)
        )
    """)
    
    # جدول فائزي المسابقات
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS contest_winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contest_id INTEGER,
            winner_id INTEGER,
            announced_at TIMESTAMP
        )
    """)
    
    # جدول إعدادات الردود التلقائية
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS auto_reply_settings (
            chat_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 1,
            only_admins INTEGER DEFAULT 0,
            ignore_bots INTEGER DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # جدول قوانين المجموعة
    await db_pool.execute("""
        CREATE TABLE IF NOT EXISTS group_rules (
            chat_id INTEGER PRIMARY KEY,
            rules_text TEXT,
            updated_by INTEGER,
            updated_at TIMESTAMP
        )
    """)
    
    # ===== إنشاء الفهارس =====
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_posts_channel_published ON posts(channel_db_id, published)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_schedule_next ON schedule(next_publish_date)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_user_channels_user ON user_channels(user_id)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_banned_words_chat ON banned_words(chat_id, word)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_user_messages_time ON user_messages(message_time)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_posts_channel_fail ON posts(channel_db_id, published, fail_count)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_users_subscription ON users(subscription_end)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_user_levels_points ON user_levels(points DESC)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_moderation_chat ON moderation_log(chat_id, created_at)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_channel_stats ON channel_stats(channel_db_id)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_posts_views ON posts(views_count)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_posts_published_views ON posts(published, views_count)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_contests_active ON contests(status, end_date)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_hidden_admins_chat ON hidden_admins(chat_id)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_schedule_cron ON schedule(cron_expression)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_at)")
    await db_pool.execute("CREATE INDEX IF NOT EXISTS idx_users_last_daily ON users(last_daily_reward)")
    
    # ===== تحديث الجداول =====
    try:
        cursor = await db_pool.execute("PRAGMA table_info(group_security)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        if 'auto_penalty' not in column_names:
            await db_pool.execute("ALTER TABLE group_security ADD COLUMN auto_penalty TEXT DEFAULT 'none'")
        if 'auto_mute_duration' not in column_names:
            await db_pool.execute("ALTER TABLE group_security ADD COLUMN auto_mute_duration INTEGER DEFAULT 60")
    except:
        pass
    
    try:
        cursor = await db_pool.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        if 'active_channel' not in column_names:
            await db_pool.execute("ALTER TABLE users ADD COLUMN active_channel INTEGER DEFAULT NULL")
        if 'referral_code' not in column_names:
            await db_pool.execute("ALTER TABLE users ADD COLUMN referral_code TEXT DEFAULT NULL")
        if 'auto_reply_enabled' not in column_names:
            await db_pool.execute("ALTER TABLE users ADD COLUMN auto_reply_enabled INTEGER DEFAULT 1")
        if 'auto_recycle' not in column_names:
            await db_pool.execute("ALTER TABLE users ADD COLUMN auto_recycle INTEGER DEFAULT 1")
        if 'last_daily_reward' not in column_names:
            await db_pool.execute("ALTER TABLE users ADD COLUMN last_daily_reward TEXT DEFAULT NULL")
        if 'last_weekly_reward' not in column_names:
            await db_pool.execute("ALTER TABLE users ADD COLUMN last_weekly_reward TEXT DEFAULT NULL")
        if 'achievements' not in column_names:
            await db_pool.execute("ALTER TABLE users ADD COLUMN achievements TEXT DEFAULT '[]'")
    except:
        pass
    
    try:
        cursor = await db_pool.execute("PRAGMA table_info(posts)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        if 'views_count' not in column_names:
            await db_pool.execute("ALTER TABLE posts ADD COLUMN views_count INTEGER DEFAULT 0")
        if 'last_view_time' not in column_names:
            await db_pool.execute("ALTER TABLE posts ADD COLUMN last_view_time TIMESTAMP")
    except:
        pass
    
    try:
        cursor = await db_pool.execute("PRAGMA table_info(contests)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        if 'contest_type' not in column_names:
            await db_pool.execute("ALTER TABLE contests ADD COLUMN contest_type TEXT DEFAULT 'raffle'")
    except:
        pass
    
    try:
        cursor = await db_pool.execute("PRAGMA table_info(schedule)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        if 'cron_expression' not in column_names:
            await db_pool.execute("ALTER TABLE schedule ADD COLUMN cron_expression TEXT DEFAULT NULL")
    except:
        pass
    
    # ===== إدخال البيانات الافتراضية =====
    await db_pool.execute("INSERT OR IGNORE INTO bot_admins (user_id) VALUES (?)", (PRIMARY_OWNER_ID,))
    await db_pool.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('publish_interval', ?)", (str(DEFAULT_PUBLISH_INTERVAL_SECONDS),))
    await db_pool.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('updates_channel', '')")
    await db_pool.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('force_subscribe_enabled', '0')")
    await db_pool.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('force_subscribe_channel', '')")
    await db_pool.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_backup', '1')")
    await db_pool.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_backup', '')")
    await db_pool.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_ticket_number', '0')")
    await db_pool.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('log_channel_id', '')")
    
    await db_pool.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('reward_days_per_referral', '3')")
    await db_pool.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('referral_bonus_points', '50')")
    await db_pool.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('max_referrals_per_day', '5')")
    await db_pool.execute("INSERT OR IGNORE INTO referral_settings (key, value) VALUES ('welcome_bonus_points', '10')")
    
    await db_pool.commit()
    print("✅ قاعدة البيانات جاهزة مع جميع الجداول والتحسينات")

async def execute_db(func):
    return await func(db_pool)

# ===================== دوال المستخدمين =====================
async def db_register_user(user_id: int) -> bool:
    async def _register(conn):
        cur = await conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if await cur.fetchone():
            return False
        await conn.execute("INSERT INTO users (user_id, auto_publish, banned, trial_used, auto_reply_enabled, auto_recycle) VALUES (?, 1, 0, 0, 1, 1)", (user_id,))
        await conn.commit()
        return True
    return await execute_db(_register)

async def db_get_all_users():
    async def _get(conn):
        cur = await conn.execute("SELECT user_id, banned FROM users ORDER BY user_id")
        return await cur.fetchall()
    return await execute_db(_get)

async def db_update_user_cache(user_id: int, username: str, first_name: str):
    async def _update(conn):
        await conn.execute("INSERT OR REPLACE INTO users_cache (user_id, username, first_name, last_updated) VALUES (?, ?, ?, ?)",
                          (user_id, username or "", first_name or "", utc_now_iso()))
        await conn.commit()
    return await execute_db(_update)

async def db_is_banned(user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT banned FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_check)

async def db_set_ban(user_id: int, banned: bool):
    async def _set(conn):
        await conn.execute("UPDATE users SET banned=? WHERE user_id=?", (1 if banned else 0, user_id))
        await conn.commit()
    return await execute_db(_set)

async def db_has_used_trial(user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT trial_used FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_check)

async def db_activate_trial(user_id: int) -> int:
    async def _activate(conn):
        cur = await conn.execute("SELECT trial_used FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0] == 1:
            return 0
        end_date = (utc_now() + timedelta(days=30)).isoformat()
        await conn.execute("UPDATE users SET trial_used=1, subscription_end=? WHERE user_id=?", (end_date, user_id))
        await conn.commit()
        return 30
    return await execute_db(_activate)

async def db_activate_subscription(user_id: int, days: int):
    async def _activate(conn):
        cur = await conn.execute("SELECT subscription_end FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        try:
            if row and row[0]:
                current_end = datetime.fromisoformat(row[0])
                if current_end > utc_now():
                    new_end = current_end + timedelta(days=days)
                else:
                    new_end = utc_now() + timedelta(days=days)
            else:
                new_end = utc_now() + timedelta(days=days)
        except:
            new_end = utc_now() + timedelta(days=days)
        await conn.execute("UPDATE users SET subscription_end=? WHERE user_id=?", (new_end.isoformat(), user_id))
        await conn.commit()
    return await execute_db(_activate)

async def db_has_active_subscription(user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT subscription_end FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0]:
            try:
                end_date = datetime.fromisoformat(row[0])
                return end_date > utc_now()
            except:
                return False
        return False
    return await execute_db(_check)

async def db_get_subscription_days_left(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT subscription_end FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0]:
            try:
                end_date = datetime.fromisoformat(row[0])
                days = (end_date - utc_now()).days
                return max(0, days)
            except:
                return 0
        return 0
    return await execute_db(_get)

async def db_auto_status(user_id: int) -> bool:
    async def _get(conn):
        cur = await conn.execute("SELECT auto_publish FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_get)

async def db_set_auto(user_id: int, enabled: bool):
    async def _set(conn):
        await conn.execute("UPDATE users SET auto_publish=? WHERE user_id=?", (1 if enabled else 0, user_id))
        await conn.commit()
    return await execute_db(_set)

# ===================== دوال قنوات المستخدمين =====================
async def db_add_channel(user_id: int, channel_id: str, channel_name: str) -> int:
    async def _add(conn):
        cur = await conn.execute("SELECT id FROM user_channels WHERE user_id=? AND channel_id=?", (user_id, channel_id))
        if await cur.fetchone():
            return None
        cur = await conn.execute("INSERT INTO user_channels (user_id, channel_id, channel_name, created_at) VALUES (?, ?, ?, ?) RETURNING id",
                                (user_id, channel_id, channel_name, utc_now_iso()))
        row = await cur.fetchone()
        await conn.commit()
        if row:
            new_id = row[0]
            await db_set_next_publish_date(new_id, utc_now() + timedelta(minutes=1))
        return row[0] if row else None
    return await execute_db(_add)

async def db_get_channels(user_id: int):
    async def _get(conn):
        try:
            cur = await conn.execute("SELECT id, channel_id, channel_name, banned FROM user_channels WHERE user_id=? ORDER BY id", (user_id,))
            rows = await cur.fetchall()
            safe_rows = []
            for row in rows:
                try:
                    if len(row) >= 4:
                        ch_id = row[0] if row[0] is not None else 0
                        ch_tele_id = row[1] if row[1] is not None else "unknown"
                        ch_name = row[2] if row[2] is not None else ch_tele_id
                        banned = row[3] if row[3] is not None else 0
                        safe_rows.append((ch_id, ch_tele_id, ch_name, banned))
                except:
                    continue
            return safe_rows
        except Exception as e:
            print(f"خطأ في جلب قنوات المستخدم {user_id}: {e}")
            return []
    return await execute_db(_get)

async def db_get_channel_info(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT channel_id, channel_name FROM user_channels WHERE id=?", (channel_db_id,))
        return await cur.fetchone()
    return await execute_db(_get)

async def db_delete_channel_by_id(user_id: int, channel_db_id: int) -> bool:
    async def _delete(conn):
        await conn.execute("DELETE FROM user_channels WHERE id=? AND user_id=?", (channel_db_id, user_id))
        await conn.execute("DELETE FROM posts WHERE channel_db_id=?", (channel_db_id,))
        await conn.execute("DELETE FROM schedule WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
        return True
    return await execute_db(_delete)

async def db_get_active_channel(user_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT active_channel FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row and row[0] is not None:
            return row[0]
        cur = await conn.execute("SELECT id FROM user_channels WHERE user_id=? AND banned=0 ORDER BY id LIMIT 1", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_set_active_channel(user_id: int, channel_db_id: int):
    async def _set(conn):
        await conn.execute("UPDATE users SET active_channel=? WHERE user_id=?", (channel_db_id, user_id))
        await conn.commit()
    return await execute_db(_set)

async def db_get_user_channels_count(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM user_channels WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_get)

# ===================== دوال المنشورات =====================
async def db_save_posts(channel_db_id: int, posts: list) -> int:
    async def _save(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0", (channel_db_id,))
        current_unpublished = (await cur.fetchone())[0]
        max_allowed = MAX_UNPUBLISHED_POSTS - current_unpublished
        if max_allowed <= 0:
            return 0
        posts_to_save = posts[:max_allowed]
        values = []
        for text_content, media_type, media_file_id in posts_to_save:
            values.append((channel_db_id, sanitize_text(text_content), media_type, media_file_id, utc_now_iso()))
        await conn.executemany(
            "INSERT INTO posts (channel_db_id, text, media_type, media_file_id, created_at) VALUES (?, ?, ?, ?, ?)",
            values
        )
        await conn.commit()
        return len(values)
    return await execute_db(_save)

async def db_get_next_post(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT id, text, media_type, media_file_id FROM posts WHERE channel_db_id=? AND published=0 AND (fail_count IS NULL OR fail_count < 3) ORDER BY id LIMIT 1", (channel_db_id,))
        row = await cur.fetchone()
        if row:
            return {'id': row[0], 'text': row[1], 'media_type': row[2], 'media_file_id': row[3]}
        return None
    return await execute_db(_get)

async def db_mark_published(post_id: int):
    async def _mark(conn):
        await conn.execute("UPDATE posts SET published=1 WHERE id=?", (post_id,))
        await conn.commit()
    return await execute_db(_mark)

async def db_increment_fail_count(post_id: int):
    async def _inc(conn):
        await conn.execute("UPDATE posts SET fail_count = fail_count + 1 WHERE id=?", (post_id,))
        await conn.commit()
    return await execute_db(_inc)

async def db_get_posts_count(channel_db_id: int) -> int:
    async def _count(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_count)

async def db_get_published_count(channel_db_id: int) -> int:
    async def _count(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=1", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_count)

async def db_reset_all_posts_to_unpublished(channel_db_id: int) -> int:
    async def _reset(conn):
        await conn.execute("UPDATE posts SET published=0, fail_count=0 WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=?", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_reset)

async def db_should_auto_recycle(channel_db_id: int) -> bool:
    total = await db_get_posts_count(channel_db_id)
    published = await db_get_published_count(channel_db_id)
    return total > 0 and published >= total

async def db_reset_posts_to_unpublished(channel_db_id: int, user_id: int = None):
    async def _reset(conn):
        await conn.execute("UPDATE posts SET published=0, fail_count=0 WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
    return await execute_db(_reset)

async def db_get_user_posts_for_channel(channel_db_id: int, limit=15):
    async def _get(conn):
        cur = await conn.execute("SELECT id, text, media_type FROM posts WHERE channel_db_id=? AND published=0 ORDER BY id LIMIT ?", (channel_db_id, limit))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_delete_single_post(post_id: int, user_id: int, channel_db_id: int) -> bool:
    async def _delete(conn):
        cur = await conn.execute("SELECT 1 FROM posts p JOIN user_channels uc ON p.channel_db_id=uc.id WHERE p.id=? AND uc.user_id=?", (post_id, user_id))
        if not await cur.fetchone():
            return False
        await conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
        await conn.commit()
        return True
    return await execute_db(_delete)

async def db_get_user_unpublished_posts(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts p JOIN user_channels uc ON p.channel_db_id=uc.id WHERE uc.user_id=? AND p.published=0", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_get)

async def db_get_user_total_posts(user_id: int) -> int:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts p JOIN user_channels uc ON p.channel_db_id=uc.id WHERE uc.user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_get)

async def db_unpublished_count(channel_db_id: int) -> int:
    async def _count(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM posts WHERE channel_db_id=? AND published=0", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    return await execute_db(_count)

# ===================== دوال المجموعات =====================
async def db_register_group(chat_id: int, chat_name: str, added_by: int, username: str = None) -> bool:
    async def _register(conn):
        cur = await conn.execute("SELECT chat_id FROM bot_groups WHERE chat_id=?", (chat_id,))
        if await cur.fetchone():
            await conn.execute("UPDATE bot_groups SET chat_name=?, username=?, added_by=? WHERE chat_id=?", (chat_name, username, added_by, chat_id))
            await conn.commit()
            return False
        await conn.execute("INSERT INTO bot_groups (chat_id, chat_name, username, added_by, added_at) VALUES (?, ?, ?, ?, ?)",
                          (chat_id, chat_name, username, added_by, utc_now_iso()))
        await conn.execute("INSERT OR IGNORE INTO user_groups_link (user_id, chat_id) VALUES (?, ?)", (added_by, chat_id))
        await conn.commit()
        return True
    return await execute_db(_register)

async def db_get_user_groups(user_id: int):
    async def _get(conn):
        cur = await conn.execute("""
            SELECT bg.chat_id, bg.chat_name, bg.username, bg.banned
            FROM bot_groups bg
            WHERE bg.added_by = ?
               OR EXISTS (SELECT 1 FROM hidden_owner_groups hog WHERE hog.chat_id = bg.chat_id AND hog.owner_id = ?)
               OR EXISTS (SELECT 1 FROM hidden_admins ha WHERE ha.chat_id = bg.chat_id AND ha.admin_id = ?)
               OR EXISTS (SELECT 1 FROM user_groups_link ugl WHERE ugl.chat_id = bg.chat_id AND ugl.user_id = ?)
            ORDER BY bg.chat_name
        """, (user_id, user_id, user_id, user_id))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_user_groups_count(user_id: int) -> int:
    groups = await db_get_user_groups(user_id)
    return len(groups)

async def db_set_chat_lock(chat_id: int, locked: bool, locked_by: int = None):
    async def _set(conn):
        if locked:
            await conn.execute("INSERT OR REPLACE INTO chat_locks (chat_id, locked, locked_at, locked_by) VALUES (?, 1, ?, ?)", (chat_id, utc_now_iso(), locked_by))
        else:
            await conn.execute("DELETE FROM chat_locks WHERE chat_id=?", (chat_id,))
        await conn.commit()
    return await execute_db(_set)

async def is_chat_locked(chat_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT locked FROM chat_locks WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return row and row[0] == 1
    return await execute_db(_check)

# ===================== دوال الأمان =====================
async def db_get_security_settings(chat_id: int):
    if BANNED_LOADED:
        if chat_id in _security_cache:
            return _security_cache[chat_id]
    
    async def _get(conn):
        cur = await conn.execute("""
            SELECT delete_links, delete_mentions, warn_message, slow_mode, slow_mode_seconds,
                   welcome_enabled, welcome_text, goodbye_enabled, goodbye_text,
                   delete_banned_words, auto_penalty, auto_mute_duration
            FROM group_security WHERE chat_id=?
        """, (chat_id,))
        row = await cur.fetchone()
        if row:
            settings = {
                'links': row[0] == 1,
                'mentions': row[1] == 1,
                'warn': row[2] == 1,
                'slow_mode': row[3] == 1,
                'slow_mode_seconds': row[4] if row[4] is not None else 5,
                'welcome_enabled': row[5] == 1,
                'welcome_text': row[6] if row[6] else "مرحباً {user} في {chat} 🤍",
                'goodbye_enabled': row[7] == 1,
                'goodbye_text': row[8] if row[8] else "وداعاً {user} 👋",
                'delete_banned_words': row[9] == 1,
                'auto_penalty': row[10] if row[10] else 'none',
                'auto_mute_duration': row[11] if row[11] is not None else 60
            }
            return settings
        default_settings = {
            'links': False, 'mentions': False, 'warn': True, 'slow_mode': False,
            'slow_mode_seconds': 5, 'welcome_enabled': False,
            'welcome_text': "مرحباً {user} في {chat} 🤍",
            'goodbye_enabled': False, 'goodbye_text': "وداعاً {user} 👋",
            'delete_banned_words': False, 'auto_penalty': 'none', 'auto_mute_duration': 60
        }
        return default_settings
    return await execute_db(_get)

async def db_set_security_settings(chat_id: int, **kwargs):
    async def _set(conn):
        cur = await conn.execute("SELECT 1 FROM group_security WHERE chat_id=?", (chat_id,))
        exists = await cur.fetchone()
        if exists:
            updates = []
            values = []
            for key, value in kwargs.items():
                if key == 'links':
                    updates.append("delete_links=?")
                    values.append(1 if value else 0)
                elif key == 'mentions':
                    updates.append("delete_mentions=?")
                    values.append(1 if value else 0)
                elif key == 'warn':
                    updates.append("warn_message=?")
                    values.append(1 if value else 0)
                elif key == 'slow_mode':
                    updates.append("slow_mode=?")
                    values.append(1 if value else 0)
                elif key == 'slow_mode_seconds':
                    updates.append("slow_mode_seconds=?")
                    values.append(value)
                elif key == 'welcome_enabled':
                    updates.append("welcome_enabled=?")
                    values.append(1 if value else 0)
                elif key == 'welcome_text':
                    updates.append("welcome_text=?")
                    values.append(value)
                elif key == 'goodbye_enabled':
                    updates.append("goodbye_enabled=?")
                    values.append(1 if value else 0)
                elif key == 'goodbye_text':
                    updates.append("goodbye_text=?")
                    values.append(value)
                elif key == 'delete_banned_words':
                    updates.append("delete_banned_words=?")
                    values.append(1 if value else 0)
                elif key == 'auto_penalty':
                    updates.append("auto_penalty=?")
                    values.append(value)
                elif key == 'auto_mute_duration':
                    updates.append("auto_mute_duration=?")
                    values.append(value)
            if updates:
                query = f"UPDATE group_security SET {', '.join(updates)} WHERE chat_id=?"
                values.append(chat_id)
                await conn.execute(query, values)
        else:
            await conn.execute("""
                INSERT INTO group_security (
                    chat_id, delete_links, delete_mentions, warn_message,
                    slow_mode, slow_mode_seconds, welcome_enabled, welcome_text,
                    goodbye_enabled, goodbye_text, delete_banned_words,
                    auto_penalty, auto_mute_duration
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                chat_id,
                1 if kwargs.get('links', False) else 0,
                1 if kwargs.get('mentions', False) else 0,
                1 if kwargs.get('warn', True) else 0,
                1 if kwargs.get('slow_mode', False) else 0,
                kwargs.get('slow_mode_seconds', 5),
                1 if kwargs.get('welcome_enabled', False) else 0,
                kwargs.get('welcome_text', "مرحباً {user} في {chat} 🤍"),
                1 if kwargs.get('goodbye_enabled', False) else 0,
                kwargs.get('goodbye_text', "وداعاً {user} 👋"),
                1 if kwargs.get('delete_banned_words', False) else 0,
                kwargs.get('auto_penalty', 'none'),
                kwargs.get('auto_mute_duration', 60)
            ))
        await conn.commit()
    return await execute_db(_set)

async def db_check_slow_mode(chat_id: int, user_id: int) -> bool:
    settings = await db_get_security_settings(chat_id)
    if not settings['slow_mode']:
        return True
    seconds = settings.get('slow_mode_seconds', 5)
    async def _check(conn):
        cur = await conn.execute("SELECT message_time FROM user_messages WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        row = await cur.fetchone()
        now = utc_now()
        if row:
            last_time = datetime.fromisoformat(row[0])
            if (now - last_time).total_seconds() < seconds:
                return False
        await conn.execute("INSERT OR REPLACE INTO user_messages (user_id, chat_id, message_time) VALUES (?, ?, ?)", (user_id, chat_id, now.isoformat()))
        await conn.commit()
        return True
    return await execute_db(_check)

async def db_add_banned_word(word: str, chat_id: int, added_by: int) -> bool:
    async def _add(conn):
        try:
            await conn.execute("INSERT OR IGNORE INTO banned_words (word, chat_id, added_by, added_at) VALUES (?, ?, ?, ?)", (word, chat_id, added_by, utc_now_iso()))
            await conn.commit()
            return True
        except:
            return False
    return await execute_db(_add)

async def db_remove_banned_word(word: str, chat_id: int) -> bool:
    async def _remove(conn):
        await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, chat_id))
        await conn.commit()
        return True
    return await execute_db(_remove)

async def db_get_banned_words(chat_id: int):
    if BANNED_LOADED:
        async def _get(conn):
            cur = await conn.execute("SELECT word, added_by, added_at FROM banned_words WHERE chat_id=? OR chat_id=-1 ORDER BY word", (chat_id,))
            return await cur.fetchall()
        return await execute_db(_get)
    return []

async def db_contains_banned_word(text: str, chat_id: int) -> str:
    if BANNED_LOADED:
        words = await db_get_banned_words(chat_id)
        text_lower = text.lower()
        for word, _, _ in words:
            if word in text_lower:
                return word
        for pattern in BANNED_PATTERNS:
            if pattern.search(text_lower):
                return pattern.pattern
    return None

# ===================== دوال المالكين والمشرفين المخفيين =====================
async def db_register_hidden_owner_group(chat_id: int, owner_id: int):
    async def _register(conn):
        await conn.execute("""
            INSERT OR REPLACE INTO hidden_owner_groups (chat_id, owner_id, is_hidden)
            VALUES (?, ?, 1)
        """, (chat_id, owner_id))
        await conn.execute("""
            INSERT OR IGNORE INTO user_groups_link (user_id, chat_id)
            VALUES (?, ?)
        """, (owner_id, chat_id))
        await conn.commit()
    return await execute_db(_register)

async def db_is_hidden_owner(chat_id: int, user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM hidden_owner_groups WHERE chat_id=? AND owner_id=?", (chat_id, user_id))
        return await cur.fetchone() is not None
    return await execute_db(_check)

async def db_add_hidden_admin(chat_id: int, admin_id: int, added_by: int) -> bool:
    async def _add(conn):
        try:
            await conn.execute("""
                INSERT OR IGNORE INTO hidden_admins (chat_id, admin_id, added_by, added_at)
                VALUES (?, ?, ?, ?)
            """, (chat_id, admin_id, added_by, utc_now_iso()))
            await conn.execute("""
                INSERT OR IGNORE INTO user_groups_link (user_id, chat_id)
                VALUES (?, ?)
            """, (admin_id, chat_id))
            await conn.commit()
            return True
        except Exception as e:
            print(f"خطأ في إضافة مشرف مخفي: {e}")
            return False
    return await execute_db(_add)

async def db_remove_hidden_admin(chat_id: int, admin_id: int) -> bool:
    async def _remove(conn):
        await conn.execute("""
            DELETE FROM hidden_admins
            WHERE chat_id=? AND admin_id=?
        """, (chat_id, admin_id))
        await conn.execute("""
            DELETE FROM user_groups_link
            WHERE user_id=? AND chat_id=?
        """, (admin_id, chat_id))
        await conn.commit()
        return True
    return await execute_db(_remove)

async def db_is_hidden_admin(chat_id: int, user_id: int) -> bool:
    async def _check(conn):
        cur = await conn.execute("""
            SELECT 1 FROM hidden_admins
            WHERE chat_id=? AND admin_id=?
        """, (chat_id, user_id))
        return await cur.fetchone() is not None
    return await execute_db(_check)

async def db_get_hidden_admins(chat_id: int) -> List[Dict]:
    async def _get(conn):
        cur = await conn.execute("""
            SELECT admin_id, added_by, added_at
            FROM hidden_admins
            WHERE chat_id=?
            ORDER BY added_at DESC
        """, (chat_id,))
        rows = await cur.fetchall()
        return [
            {
                'admin_id': row[0],
                'added_by': row[1],
                'added_at': row[2]
            }
            for row in rows
        ]
    return await execute_db(_get)

# ===================== دوال الصلاحيات =====================
async def check_admin_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update or not update.effective_user:
        return False
    user_id = update.effective_user.id
    if user_id == PRIMARY_OWNER_ID:
        return True
    chat = update.effective_chat
    if not chat:
        return False
    
    cache_key = f"{chat.id}:{user_id}"
    
    if chat.type == 'private':
        return False
    
    if chat.type in ['group', 'supergroup']:
        chat_id = chat.id
        
        if await db_is_hidden_owner(chat_id, user_id):
            return True
        
        if await db_is_hidden_admin(chat_id, user_id):
            return True
        
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status in ['administrator', 'creator']:
                return True
        except Exception:
            pass
        
        return False
    
    return False

async def is_authorized_in_group(bot, chat_id: int, user_id: int, update: Update = None) -> bool:
    if user_id == PRIMARY_OWNER_ID:
        return True
    if await db_is_hidden_owner(chat_id, user_id):
        return True
    if await db_is_hidden_admin(chat_id, user_id):
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ['administrator', 'creator']
    except:
        return False

async def is_telegram_admin(bot, chat_id: int, user_id: int, update: Update = None) -> bool:
    try:
        if user_id == PRIMARY_OWNER_ID:
            return True
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ['creator', 'administrator']
    except:
        return False

async def is_bot_admin(user_id: int) -> bool:
    if user_id == PRIMARY_OWNER_ID:
        return True
    async def _check(conn):
        cur = await conn.execute("SELECT 1 FROM bot_admins WHERE user_id=?", (user_id,))
        return await cur.fetchone() is not None
    return await execute_db(_check)

# ===================== دوال الإجراءات المتقدمة =====================
async def execute_ban(bot, chat_id: int, user_id: int, until_date=None, reason: str = "", moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن حظر البوت نفسه!"
        if await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id):
            if moderator_id != PRIMARY_OWNER_ID:
                return False, "❌ لا يمكن معاقبة مالك مخفي أو مشرف مخفي!"
        await bot.ban_chat_member(chat_id, user_id, until_date=until_date)
        return True, f"✅ تم حظر المستخدم `{user_id}` بنجاح"
    except Exception as e:
        return False, f"❌ فشل الحظر: {str(e)[:100]}"

async def execute_mute(bot, chat_id: int, user_id: int, duration_minutes: int = None, reason: str = "", moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن كتم البوت نفسه!"
        if await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id):
            if moderator_id != PRIMARY_OWNER_ID:
                return False, "❌ لا يمكن معاقبة مالك مخفي أو مشرف مخفي!"
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
        permissions = ChatPermissions(can_send_messages=False)
        await bot.restrict_chat_member(chat_id, user_id, permissions, until_date=until_date)
        return True, f"✅ تم كتم المستخدم `{user_id}`{duration_text}"
    except Exception as e:
        return False, f"❌ فشل الكتم: {str(e)[:100]}"

async def execute_kick(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن طرد البوت نفسه!"
        if await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id):
            if moderator_id != PRIMARY_OWNER_ID:
                return False, "❌ لا يمكن معاقبة مالك مخفي أو مشرف مخفي!"
        await bot.ban_chat_member(chat_id, user_id)
        await bot.unban_chat_member(chat_id, user_id)
        return True, f"✅ تم طرد المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل الطرد: {str(e)[:100]}"

async def execute_warn(bot, chat_id: int, user_id: int, moderator_id: int, reason: str = "", auto_ban_limit: int = 3):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن تحذير البوت نفسه!"
        if await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id):
            if moderator_id != PRIMARY_OWNER_ID:
                return False, "❌ لا يمكن معاقبة مالك مخفي أو مشرف مخفي!"
        async def _add_warning(conn):
            cur = await conn.execute("SELECT warnings FROM user_warnings WHERE user_id=? AND chat_id=?", (user_id, chat_id))
            row = await cur.fetchone()
            warnings = row[0] + 1 if row else 1
            await conn.execute("INSERT OR REPLACE INTO user_warnings (user_id, chat_id, warnings) VALUES (?,?,?)", (user_id, chat_id, warnings))
            await conn.commit()
            return warnings
        warnings = await execute_db(_add_warning)
        if warnings >= auto_ban_limit:
            await execute_ban(bot, chat_id, user_id, reason=f"تلقائي بعد {warnings} تحذيرات", moderator_id=moderator_id)
            return True, f"⚠️ تم تحذير المستخدم `{user_id}` ({warnings}/{auto_ban_limit}) وتم حظره تلقائياً"
        return True, f"⚠️ تم تحذير المستخدم `{user_id}` ({warnings}/{auto_ban_limit})"
    except Exception as e:
        return False, f"❌ فشل التحذير: {str(e)[:100]}"

async def execute_restrict(bot, chat_id: int, user_id: int, reason: str = "", moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن تقييد البوت نفسه!"
        if await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id):
            if moderator_id != PRIMARY_OWNER_ID:
                return False, "❌ لا يمكن معاقبة مالك مخفي أو مشرف مخفي!"
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False
        )
        await bot.restrict_chat_member(chat_id, user_id, permissions)
        return True, f"✅ تم تقييد المستخدم `{user_id}` (لا يمكنه إرسال وسائط)"
    except Exception as e:
        return False, f"❌ فشل التقييد: {str(e)[:100]}"

async def execute_pin(bot, chat_id: int, message_id: int, disable_notification: bool = False):
    try:
        await bot.pin_chat_message(chat_id, message_id, disable_notification=disable_notification)
        return True, "✅ تم تثبيت الرسالة"
    except Exception as e:
        return False, f"❌ فشل التثبيت: {str(e)[:100]}"

async def execute_unban(bot, chat_id: int, user_id: int, moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن إلغاء حظر البوت نفسه!"
        await bot.unban_chat_member(chat_id, user_id)
        return True, f"✅ تم إلغاء حظر المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل إلغاء الحظر: {str(e)[:100]}"

async def execute_unmute(bot, chat_id: int, user_id: int, moderator_id: int = None):
    try:
        if user_id == bot.id:
            return False, "❌ لا يمكن إلغاء كتم البوت نفسه!"
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True
        )
        await bot.restrict_chat_member(chat_id, user_id, permissions)
        return True, f"✅ تم إلغاء كتم المستخدم `{user_id}`"
    except Exception as e:
        return False, f"❌ فشل إلغاء الكتم: {str(e)[:100]}"

async def apply_penalty(bot, chat_id, user_id, settings):
    penalty = settings.get('auto_penalty', 'none')
    if penalty == 'none':
        return
    if await db_is_hidden_owner(chat_id, user_id) or await db_is_hidden_admin(chat_id, user_id):
        return
    if penalty == 'kick':
        await execute_kick(bot, chat_id, user_id, "مخالفة قواعد المجموعة")
    elif penalty == 'ban':
        await execute_ban(bot, chat_id, user_id, reason="مخالفة قواعد المجموعة")
    elif penalty == 'mute':
        duration = settings.get('auto_mute_duration', 60)
        await execute_mute(bot, chat_id, user_id, duration, "مخالفة قواعد المجموعة")

# ===================== دوال الجدولة =====================
async def db_save_schedule(channel_db_id: int, schedule_type: str, interval_minutes: int = None, interval_hours: int = None, interval_days: int = None, days_of_week: str = None, specific_dates: str = None, publish_time: str = None, cron_expression: str = None):
    async def _save(conn):
        await conn.execute("""
            INSERT OR REPLACE INTO schedule (
                channel_db_id, schedule_type, interval_minutes, interval_hours,
                interval_days, days_of_week, specific_dates, publish_time,
                cron_expression, next_publish_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """, (channel_db_id, schedule_type, interval_minutes, interval_hours,
              interval_days, days_of_week, specific_dates, publish_time or "00:00",
              cron_expression))
        await conn.commit()
    return await execute_db(_save)

async def db_get_schedule(channel_db_id: int):
    async def _get(conn):
        cur = await conn.execute("""
            SELECT schedule_type, interval_minutes, interval_hours, interval_days,
                   days_of_week, specific_dates, publish_time, cron_expression,
                   next_publish_date
            FROM schedule WHERE channel_db_id=?
        """, (channel_db_id,))
        row = await cur.fetchone()
        if row:
            return {
                'type': row[0] or 'interval_minutes',
                'interval_minutes': row[1] or 12,
                'interval_hours': row[2] or 0,
                'interval_days': row[3] or 0,
                'days_of_week': row[4] or '[]',
                'specific_dates': row[5] or '[]',
                'publish_time': row[6] or '00:00',
                'cron_expression': row[7],
                'next_publish_date': row[8]
            }
        return {
            'type': 'interval_minutes',
            'interval_minutes': 12,
            'interval_hours': 0,
            'interval_days': 0,
            'days_of_week': '[]',
            'specific_dates': '[]',
            'publish_time': '00:00',
            'cron_expression': None,
            'next_publish_date': None
        }
    return await execute_db(_get)

async def db_set_next_publish_date(channel_db_id: int, next_date: datetime):
    async def _set(conn):
        if next_date:
            await conn.execute("UPDATE schedule SET next_publish_date=? WHERE channel_db_id=?", (next_date.isoformat(), channel_db_id))
        else:
            await conn.execute("UPDATE schedule SET next_publish_date=NULL WHERE channel_db_id=?", (channel_db_id,))
        await conn.commit()
    return await execute_db(_set)

async def db_set_last_publish(channel_db_id: int, publish_time: datetime):
    async def _set(conn):
        await conn.execute("INSERT OR REPLACE INTO last_publish (channel_db_id, last_publish_time) VALUES (?, ?)", (channel_db_id, publish_time.isoformat()))
        await conn.commit()
    return await execute_db(_set)

async def db_update_next_publish_date(channel_db_id: int):
    async def _update(conn):
        schedule = await db_get_schedule(channel_db_id)
        last_publish_cur = await conn.execute("SELECT last_publish_time FROM last_publish WHERE channel_db_id=?", (channel_db_id,))
        last_row = await last_publish_cur.fetchone()
        last_time = datetime.fromisoformat(last_row[0]) if last_row else utc_now()
        schedule_type = schedule['type']
        publish_time_str = schedule.get('publish_time', '00:00')
        if ':' not in publish_time_str:
            publish_time_str = '00:00'
        try:
            hour, minute = map(int, publish_time_str.split(':'))
        except:
            hour, minute = 0, 0
        next_date = None
        now = utc_now()
        if schedule_type == 'interval_minutes':
            minutes = schedule.get('interval_minutes', 12)
            next_date = last_time + timedelta(minutes=minutes)
        elif schedule_type == 'interval_hours':
            hours = schedule.get('interval_hours', 1)
            next_date = last_time + timedelta(hours=hours)
        elif schedule_type == 'interval_days':
            days = schedule.get('interval_days', 1)
            next_date = last_time + timedelta(days=days)
        elif schedule_type == 'days':
            days_of_week = json.loads(schedule.get('days_of_week', '[]'))
            if days_of_week:
                target_date = last_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                for i in range(1, 8):
                    check_date = target_date + timedelta(days=i)
                    if check_date.weekday() in days_of_week:
                        next_date = check_date
                        break
                if not next_date:
                    next_date = target_date + timedelta(days=7)
                    while next_date.weekday() not in days_of_week:
                        next_date += timedelta(days=1)
            else:
                next_date = last_time + timedelta(days=1)
        elif schedule_type == 'dates':
            specific_dates = json.loads(schedule.get('specific_dates', '[]'))
            if specific_dates:
                target_date = last_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
                for date_str in sorted(specific_dates):
                    try:
                        date_obj = datetime.strptime(date_str, '%Y-%m-%d').replace(
                            hour=hour, minute=minute, second=0, microsecond=0
                        )
                        if date_obj > last_time:
                            next_date = date_obj
                            break
                    except:
                        continue
                if not next_date:
                    try:
                        next_date = datetime.strptime(specific_dates[0], '%Y-%m-%d').replace(
                            hour=hour, minute=minute, second=0, microsecond=0
                        ) + timedelta(days=365)
                    except:
                        next_date = utc_now() + timedelta(days=1)
            else:
                next_date = utc_now() + timedelta(days=1)
        elif schedule_type == 'cron':
            cron_expr = schedule.get('cron_expression', '0 0 * * *')
            try:
                parts = cron_expr.split()
                if len(parts) >= 5:
                    minute_cron, hour_cron, day_cron, month_cron, weekday_cron = parts[:5]
                    next_date = last_time + timedelta(days=1)
                    for i in range(1, 31):
                        check_date = last_time + timedelta(days=i)
                        if check_date.hour == hour and check_date.minute == minute:
                            if day_cron == '*' or check_date.day == int(day_cron):
                                if month_cron == '*' or check_date.month == int(month_cron):
                                    if weekday_cron == '*' or check_date.weekday() == int(weekday_cron):
                                        next_date = check_date
                                        break
            except:
                next_date = utc_now() + timedelta(days=1)
        else:
            next_date = utc_now() + timedelta(minutes=schedule.get('interval_minutes', 12))
        
        if next_date:
            await conn.execute("UPDATE schedule SET next_publish_date=? WHERE channel_db_id=?", (next_date.isoformat(), channel_db_id))
            await conn.commit()
    return await execute_db(_update)

async def db_set_publish_time(channel_db_id: int, time_str: str):
    async def _set(conn):
        await conn.execute("UPDATE schedule SET publish_time=? WHERE channel_db_id=?", (time_str, channel_db_id))
        await conn.commit()
    return await execute_db(_set)

# ===================== دوال المنشورات المجدولة =====================
async def db_add_scheduled_post(chat_id: int, text: str, publish_time: datetime):
    async def _add(conn):
        await conn.execute("INSERT INTO scheduled_posts (chat_id, text, publish_time, fail_count) VALUES (?, ?, ?, 0)", (chat_id, sanitize_text(text), publish_time.isoformat()))
        await conn.commit()
    return await execute_db(_add)

async def db_get_due_scheduled_posts(now: datetime):
    async def _get(conn):
        cur = await conn.execute("SELECT id, chat_id, text, fail_count FROM scheduled_posts WHERE publish_time <= ?", (now.isoformat(),))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_update_scheduled_post_fail(post_id: int, fail_count: int):
    async def _update(conn):
        await conn.execute("UPDATE scheduled_posts SET fail_count = ? WHERE id = ?", (fail_count, post_id))
        await conn.commit()
    return await execute_db(_update)

async def db_delete_scheduled_post(post_id: int):
    async def _delete(conn):
        await conn.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
        await conn.commit()
    return await execute_db(_delete)

# ===================== دوال الردود =====================
async def db_add_reply(keyword, reply):
    async def _add(conn):
        await conn.execute("INSERT OR REPLACE INTO group_replies (keyword, reply) VALUES (?,?)", (keyword.lower(), reply))
        await conn.commit()
    return await execute_db(_add)

async def db_del_reply(keyword):
    async def _del(conn):
        await conn.execute("DELETE FROM group_replies WHERE keyword=?", (keyword.lower(),))
        await conn.commit()
    return await execute_db(_del)

async def db_get_reply(keyword):
    async def _get(conn):
        cur = await conn.execute("SELECT reply FROM group_replies WHERE keyword=?", (keyword.lower(),))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_get_all_replies():
    async def _get(conn):
        cur = await conn.execute("SELECT keyword, reply FROM group_replies ORDER BY keyword")
        return await cur.fetchall()
    return await execute_db(_get)

# ===================== دوال الردود المتقدمة =====================
async def db_get_auto_reply_settings(chat_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute(
            "SELECT enabled, only_admins, ignore_bots FROM auto_reply_settings WHERE chat_id=?",
            (chat_id,)
        )
        row = await cur.fetchone()
        if row:
            return {
                'enabled': row[0] == 1,
                'only_admins': row[1] == 1,
                'ignore_bots': row[2] == 1
            }
        return {'enabled': True, 'only_admins': False, 'ignore_bots': True}
    return await execute_db(_get)

async def db_set_auto_reply_enabled(chat_id: int, enabled: bool) -> None:
    async def _set(conn):
        await conn.execute("""
            INSERT OR REPLACE INTO auto_reply_settings (chat_id, enabled, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (chat_id, 1 if enabled else 0))
        await conn.commit()
    return await execute_db(_set)

async def db_set_auto_reply_only_admins(chat_id: int, only_admins: bool) -> None:
    async def _set(conn):
        await conn.execute("""
            UPDATE auto_reply_settings SET only_admins=?, updated_at=CURRENT_TIMESTAMP
            WHERE chat_id=?
        """, (1 if only_admins else 0, chat_id))
        await conn.commit()
    return await execute_db(_set)

async def db_toggle_auto_reply(chat_id: int) -> bool:
    settings = await db_get_auto_reply_settings(chat_id)
    new_status = not settings['enabled']
    await db_set_auto_reply_enabled(chat_id, new_status)
    return new_status

async def db_get_user_auto_reply_status(user_id: int) -> bool:
    async def _get(conn):
        cur = await conn.execute(
            "SELECT auto_reply_enabled FROM users WHERE user_id=?",
            (user_id,)
        )
        row = await cur.fetchone()
        return row[0] == 1 if row else True
    return await execute_db(_get)

async def db_set_user_auto_reply_status(user_id: int, enabled: bool) -> None:
    async def _set(conn):
        await conn.execute(
            "UPDATE users SET auto_reply_enabled=? WHERE user_id=?",
            (1 if enabled else 0, user_id)
        )
        await conn.commit()
    return await execute_db(_set)

# ===================== دوال التذاكر =====================
async def db_get_next_ticket_number():
    async def _get(conn):
        cur = await conn.execute("SELECT value FROM settings WHERE key='last_ticket_number'")
        row = await cur.fetchone()
        return int(row[0]) if row else 0
    return await execute_db(_get)

async def db_save_ticket(user_id, username, message, ticket_num):
    async def _save(conn):
        created_at = utc_now_iso()
        await conn.execute("INSERT INTO support_tickets (user_id, username, message, ticket_number, status, created_at) VALUES (?,?,?,?,?,?)", (user_id, username, sanitize_text(message), ticket_num, 'pending', created_at))
        await conn.commit()
        return True
    return await execute_db(_save)

async def db_get_user_ticket(user_id):
    async def _get(conn):
        cur = await conn.execute("SELECT ticket_number, status, created_at FROM support_tickets WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        return await cur.fetchone()
    return await execute_db(_get)

async def db_get_all_tickets(limit=20):
    async def _get(conn):
        cur = await conn.execute("SELECT id, user_id, username, message, ticket_number, status, created_at FROM support_tickets ORDER BY id DESC LIMIT ?", (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_get_last_ticket_id_for_user(user_id):
    async def _get(conn):
        cur = await conn.execute("SELECT id FROM support_tickets WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_mark_ticket_replied(ticket_id):
    async def _mark(conn):
        await conn.execute("UPDATE support_tickets SET status='replied', replied=1 WHERE id=?", (ticket_id,))
        await conn.commit()
    return await execute_db(_mark)

async def db_delete_all_tickets() -> int:
    async def _delete(conn):
        cur = await conn.execute("DELETE FROM support_tickets")
        count = cur.rowcount
        await conn.execute("UPDATE settings SET value='0' WHERE key='last_ticket_number'")
        await conn.commit()
        return count
    return await execute_db(_delete)

# ===================== دوال الإحالات =====================
async def db_get_referral_settings() -> dict:
    async def _get(conn):
        settings = {}
        cur = await conn.execute("SELECT key, value FROM referral_settings")
        rows = await cur.fetchall()
        for key, value in rows:
            settings[key] = value
        return settings
    return await execute_db(_get)

async def db_get_referral_code(user_id: int) -> str:
    async def _get(conn):
        cur = await conn.execute("SELECT referral_code FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return row[0] if row and row[0] else None
    return await execute_db(_get)

async def db_generate_referral_code(user_id: int) -> str:
    async def _generate(conn):
        code_hash = hashlib.md5(f"{user_id}{time_module.time()}".encode()).hexdigest()[:8]
        referral_code = f"REF{code_hash.upper()}"
        await conn.execute("UPDATE users SET referral_code=? WHERE user_id=?", (referral_code, user_id))
        await conn.commit()
        return referral_code
    return await execute_db(_generate)

async def db_get_user_by_referral_code(referral_code: str) -> int | None:
    async def _get(conn):
        cur = await conn.execute("SELECT user_id FROM users WHERE referral_code=?", (referral_code,))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

async def db_add_referral(referrer_id: int, referred_id: int) -> bool:
    async def _add(conn):
        if referrer_id == referred_id:
            return False
        cur = await conn.execute("SELECT 1 FROM referrals WHERE referred_id=?", (referred_id,))
        if await cur.fetchone():
            return False
        today_start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        cur = await conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND referred_at >= ?", (referrer_id, today_start))
        count_today = (await cur.fetchone())[0]
        settings = await db_get_referral_settings()
        max_per_day = int(settings.get('max_referrals_per_day', '5'))
        if count_today >= max_per_day:
            return False
        await conn.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, referred_id))
        await conn.execute("INSERT INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days) VALUES (?, 1, 0, 0) ON CONFLICT(user_id) DO UPDATE SET referral_count = referral_count + 1", (referrer_id,))
        await conn.commit()
        return True
    return await execute_db(_add)

async def db_auto_reward_referral(referrer_id: int, referred_id: int) -> int:
    async def _reward(conn):
        settings = await db_get_referral_settings()
        reward_days = int(settings.get('reward_days_per_referral', '3'))
        await conn.execute("INSERT INTO referral_rewards (user_id, referral_count, total_reward_days, claimed_reward_days) VALUES (?, 0, ?, 0) ON CONFLICT(user_id) DO UPDATE SET total_reward_days = total_reward_days + ?", (referrer_id, reward_days, reward_days))
        await conn.execute("UPDATE referrals SET is_rewarded=1 WHERE referrer_id=? AND referred_id=?", (referrer_id, referred_id))
        await conn.commit()
        return reward_days
    return await execute_db(_reward)

async def db_get_referral_stats(user_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (user_id,))
        total_referrals = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT referral_count, total_reward_days, claimed_reward_days FROM referral_rewards WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        return {
            'total_referrals': total_referrals,
            'referral_count': row[0] if row else 0,
            'total_reward_days': row[1] if row else 0,
            'claimed_reward_days': row[2] if row else 0,
            'available_days': (row[1] if row else 0) - (row[2] if row else 0)
        }
    return await execute_db(_get)

async def db_claim_referral_reward(user_id: int) -> int:
    async def _claim(conn):
        cur = await conn.execute("SELECT total_reward_days, claimed_reward_days FROM referral_rewards WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if not row:
            return 0
        total = row[0]
        claimed = row[1]
        available = total - claimed
        if available <= 0:
            return 0
        current_sub = await db_get_subscription_days_left(user_id)
        new_sub_days = current_sub + available
        end_date = (utc_now() + timedelta(days=new_sub_days)).isoformat()
        await conn.execute("UPDATE users SET subscription_end=? WHERE user_id=?", (end_date, user_id))
        await conn.execute("UPDATE referral_rewards SET claimed_reward_days = claimed_reward_days + ? WHERE user_id=?", (available, user_id))
        await conn.commit()
        return available
    return await execute_db(_claim)

async def db_get_welcome_bonus_points() -> int:
    settings = await db_get_referral_settings()
    return int(settings.get('welcome_bonus_points', '10'))

# ===================== دوال التذكيرات =====================
async def db_get_user_reminder_settings(user_id: int) -> dict:
    async def _get(conn):
        cur = await conn.execute("""
            SELECT subscription_reminder, daily_stats_reminder, weekly_report,
                   reminder_days_before, last_reminder_sent, notification_lang
            FROM user_reminder_settings WHERE user_id=?
        """, (user_id,))
        row = await cur.fetchone()
        if row:
            return {
                'subscription_reminder': row[0] == 1,
                'daily_stats_reminder': row[1] == 1,
                'weekly_report': row[2] == 1,
                'reminder_days_before': row[3] if row[3] is not None else 3,
                'last_reminder_sent': row[4] if row[4] else 0,
                'notification_lang': row[5] if row[5] else 'ar'
            }
        else:
            await conn.execute("""
                INSERT INTO user_reminder_settings (
                    user_id, subscription_reminder, daily_stats_reminder,
                    weekly_report, reminder_days_before, last_reminder_sent,
                    notification_lang
                ) VALUES (?, 1, 0, 1, 3, 0, 'ar')
            """, (user_id,))
            await conn.commit()
            return {
                'subscription_reminder': True,
                'daily_stats_reminder': False,
                'weekly_report': True,
                'reminder_days_before': 3,
                'last_reminder_sent': 0,
                'notification_lang': 'ar'
            }
    return await execute_db(_get)

async def db_update_reminder_settings(user_id: int, **kwargs):
    async def _update(conn):
        fields, values = [], []
        for key, value in kwargs.items():
            if key == 'subscription_reminder':
                fields.append("subscription_reminder=?")
                values.append(1 if value else 0)
            elif key == 'daily_stats_reminder':
                fields.append("daily_stats_reminder=?")
                values.append(1 if value else 0)
            elif key == 'weekly_report':
                fields.append("weekly_report=?")
                values.append(1 if value else 0)
            elif key == 'reminder_days_before':
                fields.append("reminder_days_before=?")
                values.append(value)
            elif key == 'notification_lang':
                fields.append("notification_lang=?")
                values.append(value)
        if fields:
            query = f"UPDATE user_reminder_settings SET {', '.join(fields)} WHERE user_id=?"
            values.append(user_id)
            await conn.execute(query, values)
            await conn.commit()
    return await execute_db(_update)

async def db_update_last_reminder_sent(user_id: int, reminder_type: str):
    async def _update(conn):
        now_timestamp = int(time_module.time())
        await conn.execute("UPDATE user_reminder_settings SET last_reminder_sent=? WHERE user_id=?", (now_timestamp, user_id))
        await conn.commit()
    return await execute_db(_update)

async def db_get_users_needing_reminder() -> list:
    async def _get(conn):
        now = utc_now()
        users = []
        cur = await conn.execute("SELECT user_id, subscription_end FROM users WHERE subscription_end IS NOT NULL AND banned=0")
        rows = await cur.fetchall()
        for user_id, subscription_end_str in rows:
            try:
                end_date = datetime.fromisoformat(subscription_end_str)
                days_left = (end_date - now).days
                if days_left < 0:
                    continue
                settings = await db_get_user_reminder_settings(user_id)
                if settings['subscription_reminder']:
                    reminder_days = settings['reminder_days_before']
                    last_sent = settings['last_reminder_sent']
                    now_timestamp = int(time_module.time())
                    need_reminder = False
                    if 0 < days_left <= reminder_days:
                        if last_sent == 0:
                            need_reminder = True
                        elif (now_timestamp - last_sent) > (3 * 24 * 60 * 60):
                            need_reminder = True
                    if need_reminder:
                        users.append({
                            'user_id': user_id,
                            'days_left': days_left,
                            'notification_lang': settings['notification_lang']
                        })
            except:
                continue
        return users
    return await execute_db(_get)

async def db_get_all_active_users_for_report() -> list:
    async def _get(conn):
        thirty_days_ago = (utc_now() - timedelta(days=30)).isoformat()
        cur = await conn.execute("SELECT user_id FROM users_cache WHERE last_updated >= ?", (thirty_days_ago,))
        return [row[0] for row in await cur.fetchall()]
    return await execute_db(_get)

# ===================== دوال المستويات =====================
LEVEL_REQUIREMENTS = {
    1: 0, 2: 100, 3: 250, 4: 500, 5: 1000,
    6: 2000, 7: 3500, 8: 5000, 9: 7500, 10: 10000
}

async def db_get_user_level(user_id: int):
    async def _get(conn):
        cur = await conn.execute("SELECT points, level FROM user_levels WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if row:
            return {'points': row[0], 'level': row[1]}
        return {'points': 0, 'level': 1}
    return await execute_db(_get)

async def db_update_user_level(user_id: int, points: int, level: int):
    async def _update(conn):
        await conn.execute("INSERT OR REPLACE INTO user_levels (user_id, points, level) VALUES (?,?,?)", (user_id, points, level))
        await conn.commit()
    return await execute_db(_update)

# ===================== دوال المسابقات =====================
async def db_create_contest(creator_id: int, title: str, description: str, prize: str, end_date: datetime, contest_type: str = 'raffle') -> int:
    async def _create(conn):
        if not isinstance(end_date, datetime):
            raise ValueError("end_date must be datetime object")
        end_date_str = end_date.isoformat()
        created_at_str = utc_now_iso()
        cur = await conn.execute("""
            INSERT INTO contests (
                creator_id, title, description, prize, end_date,
                status, created_at, contest_type
            ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?) RETURNING id
        """, (creator_id, title, description, prize, end_date_str, created_at_str, contest_type))
        row = await cur.fetchone()
        await conn.commit()
        return row[0] if row else None
    return await execute_db(_create)

async def db_get_contest(contest_id: int) -> dict | None:
    async def _get(conn):
        cur = await conn.execute("""
            SELECT id, title, description, prize, end_date, status,
                   winner_id, creator_id, created_at, contest_type
            FROM contests WHERE id = ?
        """, (contest_id,))
        row = await cur.fetchone()
        if row:
            return {
                'id': row[0], 'title': row[1], 'description': row[2],
                'prize': row[3], 'end_date': row[4], 'status': row[5],
                'winner_id': row[6], 'creator_id': row[7], 'created_at': row[8],
                'contest_type': row[9] if len(row) > 9 else 'raffle'
            }
        return None
    return await execute_db(_get)

async def db_participate_in_contest(user_id: int, contest_id: int, answer: str = "") -> bool:
    async def _participate(conn):
        try:
            await conn.execute("""
                INSERT INTO contest_participants (user_id, contest_id, answer, joined_at)
                VALUES (?, ?, ?, ?)
            """, (user_id, contest_id, answer, utc_now_iso()))
            await conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    return await execute_db(_participate)

async def db_get_user_participation(user_id: int, contest_id: int) -> dict | None:
    async def _get(conn):
        cur = await conn.execute("""
            SELECT id, answer, joined_at
            FROM contest_participants
            WHERE user_id = ? AND contest_id = ?
        """, (user_id, contest_id))
        row = await cur.fetchone()
        if row:
            return {'id': row[0], 'answer': row[1], 'joined_at': row[2]}
        return None
    return await execute_db(_get)

async def db_set_contest_winner(contest_id: int, winner_id: int) -> bool:
    async def _set(conn):
        await conn.execute("""
            UPDATE contests SET status = 'finished', winner_id = ?
            WHERE id = ?
        """, (winner_id, contest_id))
        await conn.execute("""
            INSERT INTO contest_winners (contest_id, winner_id, announced_at)
            VALUES (?, ?, ?)
        """, (contest_id, winner_id, utc_now_iso()))
        await conn.commit()
        return True
    return await execute_db(_set)

async def db_get_contest_winners(limit: int = 10) -> list:
    async def _get(conn):
        cur = await conn.execute("""
            SELECT c.id, c.title, c.prize, cw.winner_id, cw.announced_at
            FROM contest_winners cw
            JOIN contests c ON cw.contest_id = c.id
            ORDER BY cw.announced_at DESC LIMIT ?
        """, (limit,))
        return await cur.fetchall()
    return await execute_db(_get)

async def db_delete_contest(contest_id: int, user_id: int) -> bool:
    async def _delete(conn):
        cur = await conn.execute("SELECT creator_id FROM contests WHERE id = ?", (contest_id,))
        row = await cur.fetchone()
        if row and (row[0] == user_id or await is_bot_admin(user_id)):
            await conn.execute("DELETE FROM contest_participants WHERE contest_id = ?", (contest_id,))
            await conn.execute("DELETE FROM contests WHERE id = ?", (contest_id,))
            await conn.commit()
            return True
        return False
    return await execute_db(_delete)

async def db_get_random_participant(contest_id: int) -> int | None:
    async def _get(conn):
        cur = await conn.execute("""
            SELECT user_id FROM contest_participants
            WHERE contest_id = ? ORDER BY RANDOM() LIMIT 1
        """, (contest_id,))
        row = await cur.fetchone()
        return row[0] if row else None
    return await execute_db(_get)

# ===================== دوال إحصائيات القنوات =====================
async def db_get_channel_stats(channel_db_id: int) -> dict:
    async def _get_stats(conn):
        cur = await conn.execute("""
            SELECT
                COUNT(*) as total_posts,
                SUM(CASE WHEN published = 1 THEN 1 ELSE 0 END) as published_posts,
                SUM(CASE WHEN published = 0 THEN 1 ELSE 0 END) as unpublished_posts,
                SUM(views_count) as total_views,
                AVG(views_count) as avg_views,
                MAX(created_at) as last_post_time,
                MIN(created_at) as first_post_time
            FROM posts
            WHERE channel_db_id = ?
        """, (channel_db_id,))
        row = await cur.fetchone()
        if not row or row[0] == 0:
            return {
                'total_posts': 0,
                'published_posts': 0,
                'unpublished_posts': 0,
                'total_views': 0,
                'avg_views': 0,
                'last_post_time': None,
                'first_post_time': None
            }
        return {
            'total_posts': row[0] or 0,
            'published_posts': row[1] or 0,
            'unpublished_posts': row[2] or 0,
            'total_views': row[3] or 0,
            'avg_views': round(row[4], 2) if row[4] else 0,
            'last_post_time': row[5],
            'first_post_time': row[6]
        }
    return await execute_db(_get_stats)

# ===================== دوال الكيبورد =====================
def get_auto_reply_keyboard(chat_id: int, settings: dict) -> InlineKeyboardMarkup:
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

def get_user_auto_reply_keyboard(user_id: int, enabled: bool) -> InlineKeyboardMarkup:
    status_text = "🟢 مفعل" if enabled else "🔴 معطل"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📝 الردود التلقائية: {status_text}",
            callback_data=f"{CallbackData.USER_AUTO_REPLY_TOGGLE_PREFIX}{user_id}"
        )],
        [InlineKeyboardButton(
            "🔙 رجوع",
            callback_data=CallbackData.BACK
        )]
    ])

def get_replies_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة رد", callback_data=CallbackData.ADMIN_ADD_REPLY),
         InlineKeyboardButton("📋 عرض الردود", callback_data=CallbackData.ADMIN_LIST_REPLIES)],
        [InlineKeyboardButton("🗑️ حذف رد", callback_data=CallbackData.ADMIN_DEL_REPLY),
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])

def get_group_banned_words_keyboard(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة", callback_data=f"{CallbackData.BANNED_WORDS_ADD_PREFIX}{chat_id}"),
         InlineKeyboardButton("📋 عرض الكلمات", callback_data=f"{CallbackData.BANNED_WORDS_LIST_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=f"{CallbackData.BANNED_WORDS_REMOVE_PREFIX}{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

def get_banned_words_admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة كلمة عامة", callback_data=CallbackData.ADMIN_ADD_BANNED_WORD),
         InlineKeyboardButton("📋 عرض الكلمات", callback_data=CallbackData.ADMIN_LIST_BANNED_WORDS)],
        [InlineKeyboardButton("🗑️ حذف كلمة", callback_data=CallbackData.ADMIN_REMOVE_BANNED_WORD),
         InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.ADMIN_PANEL)]
    ])

def get_advanced_group_actions_keyboard(chat_id: int) -> InlineKeyboardMarkup:
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

def get_advanced_mute_duration_keyboard(chat_id: int) -> InlineKeyboardMarkup:
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

def get_admin_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'admin_users'), callback_data=CallbackData.ADMIN_USERS),
         InlineKeyboardButton(get_text(user_id, 'admin_banned'), callback_data=CallbackData.ADMIN_BANNED_USERS)],
        [InlineKeyboardButton(get_text(user_id, 'admin_channels'), callback_data=CallbackData.ADMIN_ALL_CHANNELS),
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
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])

def security_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 حذف الروابط", callback_data=f"{CallbackData.SECURITY_LINKS_PREFIX}{chat_id}"),
         InlineKeyboardButton("@ حذف المعرفات", callback_data=f"{CallbackData.SECURITY_MENTIONS_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🚫 كلمات محظورة", callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}"),
         InlineKeyboardButton("⏱️ الوضع البطيء", callback_data=f"{CallbackData.SECURITY_SLOWMODE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("🎯 الترحيب", callback_data=f"{CallbackData.SECURITY_WELCOME_PREFIX}{chat_id}"),
         InlineKeyboardButton("👋 الوداع", callback_data=f"{CallbackData.SECURITY_GOODBYE_PREFIX}{chat_id}")],
        [InlineKeyboardButton("⚖️ تحديد العقوبة", callback_data=f"{CallbackData.PENALTY_MENU}:{chat_id}"),
         InlineKeyboardButton("📝 إعدادات الردود", callback_data=CallbackData.ADMIN_AUTO_REPLY)],
        [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}")],
        [InlineKeyboardButton("📜 سجل الإجراءات", callback_data=f"{CallbackData.GROUP_ACTION_LOG}:{chat_id}")],
        [InlineKeyboardButton("🔙 إغلاق", callback_data=CallbackData.SECURITY_CLOSE)]
    ])

def penalty_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 طرد", callback_data=f"{CallbackData.PENALTY_KICK}:{chat_id}"),
         InlineKeyboardButton("🛑 حظر", callback_data=f"{CallbackData.PENALTY_BAN}:{chat_id}")],
        [InlineKeyboardButton("🔇 كتم", callback_data=f"{CallbackData.PENALTY_MUTE}:{chat_id}"),
         InlineKeyboardButton("🔙 رجوع", callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])

def mute_duration_keyboard(chat_id: int) -> InlineKeyboardMarkup:
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

# ===================== دوال الكيبورد الرئيسية =====================
async def get_main_keyboard(user_id: int):
    channels = await db_get_channels(user_id)
    active = None
    if channels:
        try:
            active = await db_get_active_channel(user_id)
            if active is not None:
                channel_exists = False
                for ch in channels:
                    if ch[0] == active:
                        channel_exists = True
                        break
                if not channel_exists:
                    active = channels[0][0]
                    await db_set_active_channel(user_id, active)
            else:
                active = channels[0][0]
                await db_set_active_channel(user_id, active)
        except:
            active = channels[0][0] if channels else None
    
    cnt = 0
    ch_display = get_text(user_id, 'no_channels')
    if active is not None:
        try:
            cnt = await db_unpublished_count(active)
            ch_info = await db_get_channel_info(active)
            if ch_info and len(ch_info) >= 2:
                ch_tele_id = ch_info[0] if ch_info[0] is not None else "unknown"
                ch_name = ch_info[1] if ch_info[1] is not None else ch_tele_id
                ch_display = f"{ch_name} ({ch_tele_id})"
        except:
            ch_display = get_text(user_id, 'no_channels')
    
    my_groups = 0
    try:
        my_groups = await db_get_user_groups_count(user_id)
    except:
        my_groups = 0
    
    has_sub = False
    try:
        has_sub = await db_has_active_subscription(user_id)
    except:
        has_sub = False
    sub_text = get_text(user_id, 'subscribed') if has_sub else get_text(user_id, 'not_subscribed')
    
    auto_status = False
    try:
        auto_status = await db_auto_status(user_id)
    except:
        auto_status = False
    auto_text = get_text(user_id, 'auto_on') if auto_status else get_text(user_id, 'auto_off')
    
    title = get_text(user_id, 'main_title').format(
        BOT_NAME, user_id, my_groups, sub_text,
        ch_display, cnt, auto_status
    )
    
    keyboard = []
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'my_groups_btn'), callback_data=CallbackData.GROUPS_MY),
        InlineKeyboardButton(get_text(user_id, 'add_channel'), callback_data=CallbackData.CHANNELS_ADD)
    ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'my_channels'), callback_data=CallbackData.CHANNELS_MY),
        InlineKeyboardButton(get_text(user_id, 'settings_btn'), callback_data=CallbackData.SETTINGS_MENU)
    ])
    if channels:
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'add_15_posts'), callback_data=CallbackData.POSTS_ADD_15),
            InlineKeyboardButton(get_text(user_id, 'publish_one'), callback_data=CallbackData.POSTS_PUBLISH_ONE)
        ])
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'my_posts_btn'), callback_data=CallbackData.POSTS_MY),
            InlineKeyboardButton(get_text(user_id, 'recycle'), callback_data=CallbackData.POSTS_RECYCLE)
        ])
        keyboard.append([
            InlineKeyboardButton(f"{get_text(user_id, 'stats_btn')} ({cnt})", callback_data=CallbackData.STATS_PENDING),
            InlineKeyboardButton(get_text(user_id, 'my_stats_btn'), callback_data=CallbackData.STATS_FULL)
        ])
        if active is not None:
            keyboard.append([
                InlineKeyboardButton(get_text(user_id, 'schedule_btn'), callback_data=f"{CallbackData.SCHEDULE_MENU_PREFIX}{active}"),
                InlineKeyboardButton(get_text(user_id, 'channel_stats'), callback_data=f"{CallbackData.CHANNEL_STATS}:{active}")
            ])
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'my_channels_summary'), callback_data=CallbackData.MY_CHANNEL_STATS),
            InlineKeyboardButton(get_text(user_id, 'my_rank_btn'), callback_data="rank")
        ])
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'top_10_btn'), callback_data="top"),
            InlineKeyboardButton(get_text(user_id, 'schedule_post_btn'), callback_data="schedule_post")
        ])
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'publish_all'), callback_data=CallbackData.PUBLISH_ALL_CHANNELS)
        ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'help_btn'), callback_data=CallbackData.HELP),
        InlineKeyboardButton(get_text(user_id, 'trial_btn'), callback_data=CallbackData.TRIAL)
    ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'subscribe_btn'), callback_data=CallbackData.SUBSCRIBE_MENU),
        InlineKeyboardButton(get_text(user_id, 'developer_btn'), callback_data=CallbackData.DEVELOPER)
    ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'language_btn'), callback_data="language"),
        InlineKeyboardButton(get_text(user_id, 'support_btn'), callback_data=CallbackData.SUPPORT_MENU)
    ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'referral'), callback_data=CallbackData.REFERRAL_MENU),
        InlineKeyboardButton(get_text(user_id, 'reminder_settings'), callback_data=CallbackData.REMINDER_MENU)
    ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'translation_settings'), callback_data=CallbackData.TRANSLATION_MENU)
    ])
    keyboard.append([
        InlineKeyboardButton(get_text(user_id, 'contests_menu'), callback_data=CallbackData.CONTESTS_MENU)
    ])
    is_admin = (user_id == PRIMARY_OWNER_ID) or (await is_bot_admin(user_id))
    if is_admin:
        keyboard.append([
            InlineKeyboardButton(get_text(user_id, 'admin_panel'), callback_data=CallbackData.ADMIN_PANEL)
        ])
    return InlineKeyboardMarkup(keyboard), title, active

# ===================== دوال معالجة المسابقات =====================
async def handle_contest_creation_states(update: Update, context: ContextTypes.DEFAULT_TYPE, state: UserState) -> bool:
    try:
        if not update or not update.effective_user:
            return False
        user_id = update.effective_user.id
        text = update.message.text.strip() if update.message.text else ""
        
        if state == UserState.WAITING_CONTEST_TITLE:
            if not text:
                await update.message.reply_text("❌ الرجاء إدخال عنوان صحيح.")
                return True
            context.user_data['contest_title'] = text
            context.user_data['state'] = UserState.WAITING_CONTEST_DESCRIPTION
            await update.message.reply_text(get_text(user_id, 'create_contest_description'))
            return True
        
        elif state == UserState.WAITING_CONTEST_DESCRIPTION:
            if not text:
                await update.message.reply_text("❌ الرجاء إدخال وصف صحيح.")
                return True
            context.user_data['contest_description'] = text
            context.user_data['state'] = UserState.WAITING_CONTEST_PRIZE
            await update.message.reply_text(get_text(user_id, 'create_contest_prize'))
            return True
        
        elif state == UserState.WAITING_CONTEST_PRIZE:
            if not text:
                await update.message.reply_text("❌ الرجاء إدخال جائزة صحيحة.")
                return True
            context.user_data['contest_prize'] = text
            context.user_data['state'] = UserState.WAITING_CONTEST_END_DATE
            await update.message.reply_text(get_text(user_id, 'create_contest_end_date'))
            return True
        
        elif state == UserState.WAITING_CONTEST_END_DATE:
            try:
                try:
                    end_date = datetime.strptime(text, "%Y-%m-%d %H:%M")
                except:
                    await update.message.reply_text(get_text(user_id, 'contest_date_invalid'))
                    return True
                now_mecca = mecca_now()
                if end_date <= now_mecca:
                    await update.message.reply_text(get_text(user_id, 'contest_date_future'))
                    return True
                end_date_utc = mecca_to_utc(end_date)
                title = context.user_data.pop('contest_title', 'بدون عنوان')
                description = context.user_data.pop('contest_description', '')
                prize = context.user_data.pop('contest_prize', '')
                contest_type = context.user_data.pop('contest_type', 'raffle')
                contest_id = await db_create_contest(user_id, title, description, prize, end_date_utc, contest_type)
                if contest_id:
                    await update.message.reply_text(
                        get_text(user_id, 'contest_created').format(
                            title, prize, end_date.strftime('%Y-%m-%d %H:%M'), contest_id
                        )
                    )
                    try:
                        await context.bot.send_message(
                            PRIMARY_OWNER_ID,
                            get_text(PRIMARY_OWNER_ID, 'contest_creator').format(user_id, title)
                        )
                    except:
                        pass
                else:
                    await update.message.reply_text(get_text(user_id, 'contest_created_error'))
            except Exception as e:
                error_id = log_error(e, {'user_id': user_id, 'action': 'create_contest'})
                await update.message.reply_text(f"❌ حدث خطأ (الرمز: `{error_id}`)")
                return True
            context.user_data.pop('state', None)
            await main_menu_callback(update, context)
            return True
        
        elif state == UserState.WAITING_CONTEST_ANSWER:
            contest_id = context.user_data.get('contest_join_id')
            if not contest_id:
                await update.message.reply_text("❌ لم يتم العثور على المسابقة.")
                context.user_data.pop('state', None)
                return True
            answer = text if text else ""
            if answer.lower() == '/skip':
                answer = ""
            success = await db_participate_in_contest(user_id, contest_id, answer)
            if success:
                await update.message.reply_text(get_text(user_id, 'contest_join_success'))
                try:
                    level_data = await db_get_user_level(user_id)
                    await db_update_user_level(user_id, level_data['points'] + 5, level_data['level'])
                except:
                    pass
            else:
                await update.message.reply_text(get_text(user_id, 'contest_join_error'))
            context.user_data.pop('contest_join_id', None)
            context.user_data.pop('state', None)
            await contests_command_handler(update, context)
            return True
        
        return False
    except Exception as e:
        error_id = log_error(e, {'user_id': user_id, 'state': state.name if state else 'None'})
        await update.message.reply_text(f"❌ حدث خطأ (الرمز: `{error_id}`)")
        context.user_data.pop('state', None)
        return True

# ===================== الأوامر والكولباك =====================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await db_register_user(user.id)
    await db_update_user_cache(user.id, user.username or "", user.first_name or "")
    keyboard, title, active = await get_main_keyboard(user.id)
    if active:
        await db_set_active_channel(user.id, active)
    await safe_send(context.bot, user.id, title, reply_markup=keyboard)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await safe_send(context.bot, user_id, get_text(user_id, 'help'))

async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat = update.effective_chat
    rules = DEFAULT_RULES
    if chat and chat.type in ['group', 'supergroup']:
        custom = await db_get_group_rules(chat.id)
        if custom:
            rules = custom
    await safe_send(context.bot, user_id, rules)

async def set_rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/set_rules نص القوانين`")
        return
    rules_text = " ".join(args)
    await db_set_group_rules(chat_id, rules_text, user_id)
    await update.message.reply_text("✅ **تم تحديث قوانين المجموعة!**")

async def reset_rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await check_admin_access(update, context):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    await db_delete_group_rules(chat_id)
    await update.message.reply_text("✅ **تم إعادة تعيين القوانين للافتراضي!**")

async def syncgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    chat_name = update.effective_chat.title or "بدون اسم"
    user_id = update.effective_user.id
    await db_register_group(chat_id, chat_name, user_id, update.effective_chat.username)
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"⚠️ **تنبيه:**\n{bot_perms['reason']}")
        return
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ['creator', 'administrator']:
            await db_register_hidden_owner_group(chat_id, user_id)
            await update.message.reply_text(
                f"✅ **تم تسجيلك كمالك مخفي لهذه المجموعة.**\n\n"
                f"📌 اسم المجموعة: {chat_name}\n"
                f"🆔 المعرف: {chat_id}\n"
                f"👤 المستخدم: {user_id}\n\n"
                f"🔐 استخدم /security لإعدادات الأمان\n"
                f"🛠️ استخدم /panel للوحة التحكم"
            )
        else:
            await update.message.reply_text(
                f"⚠️ **عذراً، أنت لست مشرفاً في هذه المجموعة.**\n\n"
                f"🔗 **ادعُ البوت إلى مجموعتك:**\n"
                f"https://t.me/{BOT_USERNAME}?startgroup"
            )
            return
    except Exception as e:
        await update.message.reply_text(f"⚠️ تعذر التحقق من صلاحياتك: {e}")
        return
    await update.message.reply_text(
        f"✅ **تم تفعيل المجموعة بنجاح!**\n\n"
        f"📌 اسم المجموعة: {chat_name}\n"
        f"🆔 المعرف: {chat_id}\n"
        f"👤 المضافة بواسطة: {user_id}\n\n"
        f"🔐 استخدم /security لإعدادات الأمان\n"
        f"🛠️ استخدم /panel للوحة التحكم"
    )

async def security_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text(get_text(user_id, 'admin_only'))
            return
        await security_select_group_callback(update, context)
        return
    groups = await db_get_user_groups(user_id)
    if not groups:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ أضف البوت إلى مجموعة", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
            [InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)],
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        text = """🔐 **إعدادات الأمان**

⚠️ لم يتم العثور على مجموعات.

📌 **لتفعيل إعدادات الأمان والإجراءات المتقدمة:**
1. أضف البوت إلى مجموعتك
2. اجعل البوت مشرفاً
3. استخدم الأمر /syncgroup في المجموعة"""
        await safe_send(context.bot, user_id, text, reply_markup=keyboard)
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        name = gname[:40] + "..." if len(gname) > 43 else gname
        keyboard.append([InlineKeyboardButton(f"📌 {name}", callback_data=f"{CallbackData.SECURITY_SELECT_GROUP}{gid}")])
    keyboard.append([InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    text = """🔐 **إعدادات الأمان والإجراءات المتقدمة**

📌 اختر المجموعة التي تريد إدارة إعداداتها:

⚠️ ملاحظة: يجب أن يكون البوت مشرفاً في المجموعة"""
    await safe_send(context.bot, user_id, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def trial_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await trial_callback(update, context)

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscribe_menu_callback(update, context)

async def developer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await developer_callback(update, context)

async def updates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await updates_callback(update, context)

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇸🇦 العربية", callback_data="lang_ar"),
         InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton("🇫🇷 Français", callback_data="lang_fr"),
         InlineKeyboardButton("🇹🇷 Türkçe", callback_data="lang_tr")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_send(context.bot, user_id, get_text(user_id, 'welcome'), reply_markup=keyboard)

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 كتابة تذكرة", callback_data=CallbackData.SUPPORT_TICKET)],
        [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_send(context.bot, user_id, get_text(user_id, 'support_welcome'), reply_markup=keyboard)

async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.effective_chat.type in ['group', 'supergroup']:
        chat = update.effective_chat
        chat_id = chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text(get_text(user_id, 'admin_only'))
            return
        current_lock_status = await is_chat_locked(chat_id)
        lock_status_text = "🔒 مقفلة" if current_lock_status else "🔓 مفتوحة"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔒 قفل المجموعة", callback_data=f"{CallbackData.PANEL_LOCK_PREFIX}{chat_id}"),
             InlineKeyboardButton("🔓 فتح المجموعة", callback_data=f"{CallbackData.PANEL_UNLOCK_PREFIX}{chat_id}")],
            [InlineKeyboardButton("🛠️ إجراءات متقدمة", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{chat_id}"),
             InlineKeyboardButton("🔙 إغلاق اللوحة", callback_data=CallbackData.PANEL_CLOSE)]
        ])
        await update.message.reply_text(
            f"🔧 **لوحة تحكم المجموعة**\n━━━━━━━━━━━━━━\n📌 **المجموعة:** {chat.title}\n🔐 **الحالة:** {lock_status_text}\n━━━━━━━━━━━━━━\n\nاستخدم الأزرار للتحكم",
            reply_markup=kb
        )
        return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة.\nأضف البوت إلى مجموعة واجعلها نشطة.")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        if await is_authorized_in_group(context.bot, gid, user_id):
            is_locked = await is_chat_locked(gid)
            icon = "🔒" if is_locked else "🔓"
            keyboard.append([InlineKeyboardButton(f"{icon} {gname[:30]}", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await update.message.reply_text("🔧 **لوحة التحكم**\nاختر مجموعة:", reply_markup=InlineKeyboardMarkup(keyboard))

async def schedule_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = None
    args = context.args or []
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
            return
        if len(args) < 3:
            await update.message.reply_text("📝 **الاستخدام:**\n`/schedule YYYY-MM-DD HH:MM نص المنشور`")
            return
        try:
            date_str = args[0]
            time_str = args[1]
            text = " ".join(args[2:])
            mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if mecca_dt <= mecca_now():
                await update.message.reply_text("❌ **الوقت يجب أن يكون في المستقبل!**")
                return
            utc_dt = mecca_to_utc(mecca_dt)
            await db_add_scheduled_post(chat_id, text, utc_dt)
            await update.message.reply_text(f"✅ **تم جدولة المنشور!**\n📅 {date_str} 🕐 {time_str} (بتوقيت مكة)")
            return
        except ValueError:
            await update.message.reply_text("❌ صيغة التاريخ أو الوقت غير صحيحة!")
            return
    if len(args) >= 4:
        try:
            chat_id = int(args[0])
            date_str = args[1]
            time_str = args[2]
            text = " ".join(args[3:])
        except ValueError:
            await update.message.reply_text("❌ معرف المجموعة غير صحيح!")
            return
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text("❌ غير مصرح أو البوت ليس في المجموعة.")
            return
        try:
            mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if mecca_dt <= mecca_now():
                await update.message.reply_text("❌ **الوقت يجب أن يكون في المستقبل!**")
                return
            utc_dt = mecca_to_utc(mecca_dt)
            await db_add_scheduled_post(chat_id, text, utc_dt)
            await update.message.reply_text(f"✅ **تم جدولة المنشور!**\n📅 {date_str} 🕐 {time_str} (بتوقيت مكة)")
            return
        except ValueError:
            await update.message.reply_text("❌ صيغة التاريخ أو الوقت غير صحيحة!")
            return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة.")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        if await is_authorized_in_group(context.bot, gid, user_id):
            keyboard.append([InlineKeyboardButton(f"📌 {gname[:30]}", callback_data=f"schedule_select:{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await update.message.reply_text("📝 **اختر مجموعة لجدولة منشور:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = None
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text(get_text(user_id, 'admin_only'))
            return
        await db_set_chat_lock(chat_id, True, user_id)
        await update.message.reply_text(get_text(user_id, 'locked'))
        return
    args = context.args or []
    if args and args[0].lstrip('-').isdigit():
        chat_id = int(args[0])
        if await is_authorized_in_group(context.bot, chat_id, user_id):
            await db_set_chat_lock(chat_id, True, user_id)
            await update.message.reply_text(get_text(user_id, 'locked'))
            return
        else:
            await update.message.reply_text("❌ غير مصرح أو البوت ليس في المجموعة.")
            return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة.")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        if await is_authorized_in_group(context.bot, gid, user_id):
            keyboard.append([InlineKeyboardButton(f"🔒 {gname[:30]}", callback_data=f"{CallbackData.PANEL_LOCK_PREFIX}{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await update.message.reply_text("🔒 **اختر مجموعة لقفلها:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = None
    if update.effective_chat.type in ['group', 'supergroup']:
        chat_id = update.effective_chat.id
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await update.message.reply_text(get_text(user_id, 'admin_only'))
            return
        await db_set_chat_lock(chat_id, False)
        await update.message.reply_text(get_text(user_id, 'unlocked'))
        return
    args = context.args or []
    if args and args[0].lstrip('-').isdigit():
        chat_id = int(args[0])
        if await is_authorized_in_group(context.bot, chat_id, user_id):
            await db_set_chat_lock(chat_id, False)
            await update.message.reply_text(get_text(user_id, 'unlocked'))
            return
        else:
            await update.message.reply_text("❌ غير مصرح أو البوت ليس في المجموعة.")
            return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await update.message.reply_text("📭 لا توجد مجموعات مسجلة.")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        if await is_authorized_in_group(context.bot, gid, user_id):
            keyboard.append([InlineKeyboardButton(f"🔓 {gname[:30]}", callback_data=f"{CallbackData.PANEL_UNLOCK_PREFIX}{gid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await update.message.reply_text("🔓 **اختر مجموعة لفتحها:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    if not active:
        await update.message.reply_text("⚠️ يرجى اختيار قناة أولاً")
        return
    stats = await db_get_channel_stats(active)
    ch_info = await db_get_channel_info(active)
    channel_name = ch_info[1] if ch_info else "القناة"
    if stats['total_posts'] == 0:
        text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد منشورات بعد"
        await safe_send(context.bot, user_id, text)
        return
    text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📝 إجمالي المنشورات: {stats['total_posts']}\n"
    text += f"✅ المنشورة: {stats['published_posts']}\n"
    text += f"⏳ غير المنشورة: {stats['unpublished_posts']}\n"
    text += f"👁️ إجمالي المشاهدات: {stats['total_views']}\n"
    text += f"📊 متوسط المشاهدات: {stats['avg_views']}\n"
    if stats['last_post_time']:
        try:
            last_dt = datetime.fromisoformat(stats['last_post_time'])
            last_mecca = utc_to_mecca(last_dt)
            text += f"🕐 آخر نشر: {last_mecca.strftime('%Y-%m-%d %H:%M')}\n"
        except:
            pass
    if stats['first_post_time']:
        try:
            first_dt = datetime.fromisoformat(stats['first_post_time'])
            first_mecca = utc_to_mecca(first_dt)
            text += f"📅 أول نشر: {first_mecca.strftime('%Y-%m-%d %H:%M')}\n"
        except:
            pass
    await safe_send(context.bot, user_id, text)

async def contests_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    contests = await db_get_active_contests(limit=10)
    if not contests:
        text = get_text(user_id, 'no_contests')
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
        ])
        await safe_send(update, text, reply_markup=keyboard)
        return
    text = "🏆 **المسابقات النشطة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for contest in contests:
        cid = contest[0]
        title = contest[1] or "بدون عنوان"
        prize = contest[3] or "غير محددة"
        end_date = contest[4]
        try:
            end_dt = datetime.fromisoformat(end_date)
            days_left = (end_dt - utc_now()).days
            time_left = f"⏳ متبقي {days_left} يوم" if days_left > 0 else "🔴 انتهت"
        except:
            time_left = "📅 تاريخ غير صحيح"
        participated = await db_get_user_participation(user_id, cid)
        status_icon = "✅" if participated else "📝"
        text += f"📌 **{title}**\n🎁 الجائزة: {prize}\n🕐 {time_left}\n━━━━━━━━━━━━━━━━━━━━━━\n"
        if not participated and days_left > 0:
            keyboard.append([InlineKeyboardButton(
                f"{status_icon} شارك في {title[:20]}",
                callback_data=f"{CallbackData.CONTEST_JOIN_PREFIX}{cid}"
            )])
    keyboard.append([InlineKeyboardButton("🏆 الفائزون السابقون", callback_data=CallbackData.CONTEST_WINNERS)])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)])
    await safe_send(update, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def create_contest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    context.user_data['state'] = UserState.WAITING_CONTEST_TITLE
    await update.message.reply_text(get_text(user_id, 'create_contest_title'))

async def declare_winner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await update.message.reply_text(get_text(user_id, 'admin_only'))
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(get_text(user_id, 'declare_winner_usage'))
        return
    try:
        contest_id = int(args[0])
        winner_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ معرف غير صالح.")
        return
    contest = await db_get_contest(contest_id)
    if not contest:
        await update.message.reply_text(get_text(user_id, 'contest_not_found'))
        return
    if contest['status'] != 'active':
        await update.message.reply_text(get_text(user_id, 'contest_expired'))
        return
    if not await db_get_user_participation(winner_id, contest_id):
        await update.message.reply_text(get_text(user_id, 'contest_not_participant'))
        return
    if await db_set_contest_winner(contest_id, winner_id):
        await update.message.reply_text(
            get_text(user_id, 'contest_declared').format(contest['title'], winner_id, contest['prize'])
        )
        try:
            await context.bot.send_message(
                winner_id,
                get_text(winner_id, 'contest_winner_notification').format(contest['title'], contest['prize'])
            )
        except:
            pass
        level_data = await db_get_user_level(winner_id)
        await db_update_user_level(winner_id, level_data['points'] + 50, level_data['level'])
    else:
        await update.message.reply_text(get_text(user_id, 'contest_declared_error'))

async def update_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        await update.message.reply_text(f"⚠️ **تنبيه:**\n{bot_perms['reason']}")
        return
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        if not admins:
            await update.message.reply_text("❌ لا يمكن جلب قائمة المشرفين.")
            return
        updated_count = 0
        for admin in admins:
            admin_user = admin.user
            admin_id = admin_user.id
            if admin_user.is_bot:
                continue
            if admin.status == 'creator':
                if not await db_is_hidden_owner(chat_id, admin_id):
                    await db_register_hidden_owner_group(chat_id, admin_id)
                    updated_count += 1
            elif admin.status == 'administrator':
                if not await db_is_hidden_admin(chat_id, admin_id) and admin_id != PRIMARY_OWNER_ID:
                    await db_add_hidden_admin(chat_id, admin_id, user_id)
                    updated_count += 1
        await invalidate_user_cache(chat_id=chat_id)
        if updated_count > 0:
            await update.message.reply_text(
                get_text(user_id, 'update_admins_success').format(updated_count)
            )
        else:
            await update.message.reply_text(
                get_text(user_id, 'update_admins_no_changes')
            )
    except Exception as e:
        error_id = log_error(e, {'user_id': user_id, 'chat_id': chat_id})
        await update.message.reply_text(
            f"{get_text(user_id, 'update_admins_error')}\n\nالرمز: `{error_id}`"
        )

# ===================== معالجات الكولباك =====================
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    keyboard, title, active = await get_main_keyboard(user_id)
    if active:
        await db_set_active_channel(user_id, active)
    await safe_edit(query, title, reply_markup=keyboard)

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu_callback(update, context)

async def cancel_session_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data.pop('state', None)
    await safe_edit(query, get_text(user_id, 'cancelled'))
    await main_menu_callback(update, context)

async def add_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_CHANNEL_ID
    await safe_edit(query, get_text(user_id, 'send_channel_id'))

async def my_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    channels = await db_get_channels(user_id)
    if not channels:
        await safe_edit(query, get_text(user_id, 'no_channels_list'))
        return
    keyboard = []
    for ch in channels:
        ch_db_id, ch_tele_id, ch_name, banned = ch
        display = ch_name if ch_name != ch_tele_id else ch_tele_id
        keyboard.append([
            InlineKeyboardButton(f"📢 {display}", callback_data=f"{CallbackData.CHANNELS_SELECT_PREFIX}{ch_db_id}"),
            InlineKeyboardButton(get_text(user_id, 'channel_stats'), callback_data=f"{CallbackData.CHANNEL_STATS}:{ch_db_id}"),
            InlineKeyboardButton(get_text(user_id, 'delete_channel'), callback_data=f"{CallbackData.CHANNELS_DELETE_PREFIX}{ch_db_id}")
        ])
    keyboard.append([InlineKeyboardButton(get_text(user_id, 'add_channel'), callback_data=CallbackData.CHANNELS_ADD)])
    keyboard.append([InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)])
    await safe_edit(query, get_text(user_id, 'channels_list'), reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    if await db_delete_channel_by_id(user_id, ch_db_id):
        await safe_edit(query, get_text(user_id, 'channel_deleted'))
    else:
        await safe_edit(query, get_text(user_id, 'delete_failed'))
    await my_channels_callback(update, context)

async def select_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    await db_set_active_channel(user_id, ch_db_id)
    context.user_data['active_channel'] = ch_db_id
    keyboard, title, active = await get_main_keyboard(user_id)
    await safe_edit(query, title, reply_markup=keyboard)

async def add_15_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    if not active:
        await safe_edit(query, "⚠️ اختر قناة أولاً")
        return
    unpublished_count = await db_unpublished_count(active)
    if unpublished_count >= MAX_UNPUBLISHED_POSTS:
        remaining = MAX_UNPUBLISHED_POSTS - unpublished_count
        await safe_edit(query, f"⚠️ لقد تجاوزت الحد الأقصى للمنشورات غير المنشورة ({MAX_UNPUBLISHED_POSTS}).\nالعدد المتبقي: {remaining} منشور")
        return
    context.user_data['session_posts'] = []
    context.user_data['session_target'] = min(15, MAX_UNPUBLISHED_POSTS - unpublished_count)
    context.user_data['state'] = UserState.ADDING_POSTS
    await safe_edit(query, f"📥 أرسل المنشورات (نصوص أو صور أو فيديوهات)\nالحد الأقصى المسموح: {MAX_UNPUBLISHED_POSTS - unpublished_count} منشور")

async def publish_one_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    if not active:
        await safe_edit(query, "⚠️ اختر قناة أولاً")
        return
    post = await db_get_next_post(active)
    if not post:
        await safe_edit(query, get_text(user_id, 'no_posts'))
        return
    ch_info = await db_get_channel_info(active)
    try:
        if post['media_type'] == 'photo' and post['media_file_id']:
            await context.bot.send_photo(ch_info[0], post['media_file_id'], caption=post['text'] if post['text'] else None)
        elif post['media_type'] == 'video' and post['media_file_id']:
            await context.bot.send_video(ch_info[0], post['media_file_id'], caption=post['text'] if post['text'] else None)
        else:
            await context.bot.send_message(ch_info[0], post['text'])
        await db_mark_published(post['id'])
        await db_set_last_publish(active, utc_now())
        await db_update_next_publish_date(active)
        await safe_edit(query, get_text(user_id, 'post_published'))
    except Exception as e:
        await safe_edit(query, get_text(user_id, 'publish_error').format(str(e)[:100]))
    await main_menu_callback(update, context)

async def my_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    if not active:
        await safe_edit(query, "⚠️ اختر قناة أولاً")
        return
    posts = await db_get_user_posts_for_channel(active, limit=15)
    if not posts:
        await safe_edit(query, get_text(user_id, 'no_posts'))
        return
    text = get_text(user_id, 'my_posts_title') + "\n"
    for idx, (pid, ptext, media_type) in enumerate(posts[:10], 1):
        short = re.sub('<[^>]+>', '', ptext)[:80]
        media_icon = "🖼️" if media_type == 'photo' else "🎬" if media_type == 'video' else "📝" if media_type == 'text' else "📄"
        text += f"{idx}. {media_icon} {short}...\n🆔 {pid}\n\n"
    await safe_edit(query, text)

async def delete_single_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    parts = query.data.split(":")[-1].split("_")
    if len(parts) >= 2:
        post_id = int(parts[0])
        active = int(parts[1])
        if await db_delete_single_post(post_id, user_id, active):
            await query.answer("✅ تم حذف المنشور", show_alert=True)
        else:
            await query.answer("❌ فشل الحذف", show_alert=True)
    await my_posts_callback(update, context)

async def confirm_clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    active = int(query.data.split(":")[-1])
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم", callback_data=f"{CallbackData.POSTS_CLEAR_ALL_PREFIX}{active}"),
         InlineKeyboardButton("❌ لا", callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, get_text(user_id, 'confirm_delete'), reply_markup=keyboard)

async def clear_all_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    active = int(query.data.split(":")[-1])
    async def _clear_posts(conn):
        await conn.execute("DELETE FROM posts WHERE channel_db_id=?", (active,))
        await conn.commit()
    await execute_db(_clear_posts)
    await query.answer(get_text(user_id, 'deleted_all'), show_alert=True)
    await main_menu_callback(update, context)

async def recycle_posts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
    if active:
        await db_reset_posts_to_unpublished(active)
        await safe_edit(query, get_text(user_id, 'recycled'))
    else:
        await safe_edit(query, "⚠️ اختر قناة أولاً")
    await main_menu_callback(update, context)

async def my_pending_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    unpublished = await db_get_user_unpublished_posts(user_id)
    total = await db_get_user_total_posts(user_id)
    text = get_text(user_id, 'pending_stats').format(unpublished, total)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def my_full_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    channels = await db_get_user_channels_count(user_id)
    total = await db_get_user_total_posts(user_id)
    unpublished = await db_get_user_unpublished_posts(user_id)
    groups = await db_get_user_groups_count(user_id)
    auto = get_text(user_id, 'auto_on') if await db_auto_status(user_id) else get_text(user_id, 'auto_off')
    text = get_text(user_id, 'stats').format(channels, total, unpublished, groups, auto)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def my_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    groups = await db_get_user_groups(user_id)
    if not groups:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ أضف البوت", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
            [InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)],
            [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
        ])
        await safe_edit(query, "📭 لا توجد مجموعات مسجلة\n\nأضف البوت إلى مجموعة وستظهر هنا.", reply_markup=keyboard)
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        display_name = gname[:28] + "..." if len(gname) > 31 else gname
        status_icon = "⛔" if _ else "✅"
        keyboard.append([
            InlineKeyboardButton(
                f"{status_icon} {display_name}",
                callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{gid}"
            )
        ])
        keyboard.append([
            InlineKeyboardButton("🔐 الأمان", callback_data=f"{CallbackData.SECURITY_SELECT_GROUP}{gid}"),
            InlineKeyboardButton("📜 السجل", callback_data=f"{CallbackData.GROUP_ACTION_LOG}:{gid}"),
            InlineKeyboardButton("⚙️ متقدم", callback_data=f"{CallbackData.ADVANCED_ACTIONS}:{gid}")
        ])
        is_locked = await is_chat_locked(gid)
        lock_label = "🔒 قفل" if not is_locked else "🔓 فتح"
        lock_callback = f"{CallbackData.PANEL_LOCK_PREFIX}{gid}" if not is_locked else f"{CallbackData.PANEL_UNLOCK_PREFIX}{gid}"
        can_delete = await db_is_hidden_owner(gid, user_id) or user_id == PRIMARY_OWNER_ID
        if can_delete:
            keyboard.append([
                InlineKeyboardButton(lock_label, callback_data=lock_callback),
                InlineKeyboardButton("🗑️ حذف", callback_data=f"delete_group:{gid}")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton(lock_label, callback_data=lock_callback)
            ])
        keyboard.append([InlineKeyboardButton("─" * 20, callback_data="noop")])
    keyboard.append([
        InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS),
        InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)
    ])
    text = "👥 **مجموعاتي**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر مجموعة للتحكم بها:\n\n✅ = نشطة  |  ⛔ = محظورة"
    await safe_edit(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await db_is_hidden_owner(chat_id, user_id) and user_id != PRIMARY_OWNER_ID:
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    async def _delete_group(conn):
        await conn.execute("DELETE FROM bot_groups WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM user_groups_link WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM group_security WHERE chat_id = ?", (chat_id,))
        await conn.execute("DELETE FROM chat_locks WHERE chat_id = ?", (chat_id,))
        await conn.commit()
    await execute_db(_delete_group)
    await safe_edit(query, "✅ تم حذف المجموعة من قاعدة البيانات.")
    await my_groups_callback(update, context)

async def group_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    async def _get_group_name(conn):
        cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return row[0] if row else str(chat_id)
    gname = await execute_db(_get_group_name)
    text = f"⚙️ **لوحة تحكم المجموعة: {gname}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"🔗 حذف الروابط: {'✅' if settings['links'] else '❌'}\n"
    text += f"@ حذف المعرفات: {'✅' if settings['mentions'] else '❌'}\n"
    text += f"🚫 كلمات محظورة: {'✅' if settings.get('delete_banned_words', False) else '❌'}\n"
    text += f"⏱️ وضع بطيء: {'✅' if settings.get('slow_mode', False) else '❌'}\n"
    text += f"🎯 رسالة ترحيب: {'✅' if settings.get('welcome_enabled', False) else '❌'}\n"
    text += f"👋 رسالة وداع: {'✅' if settings.get('goodbye_enabled', False) else '❌'}\n"
    text += f"🔊 رسالة تحذير: {'✅' if settings['warn'] else '❌'}\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"⚖️ **العقوبة التلقائية:** {'طرد' if settings.get('auto_penalty') == 'kick' else 'حظر' if settings.get('auto_penalty') == 'ban' else 'كتم' if settings.get('auto_penalty') == 'mute' else 'لا شيء'}\n"
    if settings.get('auto_penalty') == 'mute' and settings.get('auto_mute_duration'):
        minutes = settings.get('auto_mute_duration')
        if minutes == -1:
            text += f"   مدة الكتم: دائم\n"
        elif minutes < 60:
            text += f"   مدة الكتم: {minutes} دقيقة\n"
        elif minutes < 1440:
            text += f"   مدة الكتم: {minutes // 60} ساعة\n"
        else:
            text += f"   مدة الكتم: {minutes // 1440} يوم\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📌 **اختر الإجراء المناسب:**"
    await safe_edit(query, text, reply_markup=security_keyboard(chat_id))

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    auto = await db_auto_status(user_id)
    auto_btn = get_text(user_id, 'disabled') if auto else get_text(user_id, 'enabled')
    recycle = await db_get_auto_recycle(user_id)
    recycle_btn = get_text(user_id, 'enabled') if recycle else get_text(user_id, 'disabled')
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{auto_btn} النشر التلقائي", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH)],
        [InlineKeyboardButton(f"♻️ إعادة التدوير: {recycle_btn}", callback_data=CallbackData.SETTINGS_TOGGLE_AUTO_RECYCLE)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, get_text(user_id, 'settings'), reply_markup=keyboard)

async def toggle_auto_publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    cur = await db_auto_status(user_id)
    await db_set_auto(user_id, not cur)
    status = get_text(user_id, 'enabled') if not cur else get_text(user_id, 'disabled')
    await safe_edit(query, get_text(user_id, 'auto_toggled').format(status))
    await main_menu_callback(update, context)

async def toggle_auto_recycle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    cur = await db_get_auto_recycle(user_id)
    new_status = not cur
    await db_set_auto_recycle(user_id, new_status)
    status = get_text(user_id, 'enabled') if new_status else get_text(user_id, 'disabled')
    await safe_edit(query, f"✅ تم تغيير إعادة التدوير التلقائي إلى: {status}")
    await settings_menu_callback(update, context)

async def schedule_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    parts = query.data.split(":")
    if len(parts) >= 3:
        ch_db_id = int(parts[-1])
    else:
        ch_db_id = context.user_data.get('active_channel')
    if not ch_db_id:
        await safe_edit(query, "⚠️ يرجى اختيار قناة أولاً")
        return
    schedule = await db_get_schedule(ch_db_id)
    if schedule['type'] == 'interval_minutes':
        txt = get_text(user_id, 'interval_minutes').format(schedule['interval_minutes'])
    elif schedule['type'] == 'interval_hours':
        txt = get_text(user_id, 'interval_hours').format(schedule['interval_hours'])
    elif schedule['type'] == 'interval_days':
        txt = get_text(user_id, 'interval_days').format(schedule['interval_days'])
    elif schedule['type'] == 'days':
        days = json.loads(schedule['days_of_week'])
        day_names = [get_text(user_id, 'monday'), get_text(user_id, 'tuesday'), get_text(user_id, 'wednesday'),
                     get_text(user_id, 'thursday'), get_text(user_id, 'friday'), get_text(user_id, 'saturday'),
                     get_text(user_id, 'sunday')]
        txt = get_text(user_id, 'days_week').format(', '.join([day_names[d] for d in days]) if days else get_text(user_id, 'nothing'))
    elif schedule['type'] == 'dates':
        dates = json.loads(schedule['specific_dates'])
        txt = get_text(user_id, 'specific_dates').format(', '.join(dates) if dates else get_text(user_id, 'nothing'))
    else:
        txt = "⏱️ غير محدد"
    pub_time = schedule.get('publish_time', '00:00')
    txt += f"\n🕐 وقت النشر: {pub_time} (بتوقيت مكة)"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 دقائق", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_MINUTES_PREFIX}{ch_db_id}"),
         InlineKeyboardButton("🕒 ساعات", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_HOURS_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton("📆 أيام", callback_data=f"{CallbackData.SCHEDULE_SET_INTERVAL_DAYS_PREFIX}{ch_db_id}"),
         InlineKeyboardButton("📅 أيام أسبوع", callback_data=f"{CallbackData.SCHEDULE_SET_DAYS_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton("🗓️ تواريخ محددة", callback_data=f"{CallbackData.SCHEDULE_SET_DATES_PREFIX}{ch_db_id}"),
         InlineKeyboardButton("⏰ وقت النشر", callback_data=f"{CallbackData.SCHEDULE_SET_PUBLISH_TIME_PREFIX}{ch_db_id}")],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, get_text(user_id, 'schedule_settings').format(txt), reply_markup=keyboard)

async def set_interval_minutes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_INTERVAL_MINUTES
    context.user_data['schedule_ch_id'] = ch_db_id
    await safe_edit(query, get_text(user_id, 'send_minutes'))

async def set_interval_hours_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_INTERVAL_HOURS
    context.user_data['schedule_ch_id'] = ch_db_id
    await safe_edit(query, get_text(user_id, 'send_hours'))

async def set_interval_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_INTERVAL_DAYS
    context.user_data['schedule_ch_id'] = ch_db_id
    await safe_edit(query, get_text(user_id, 'send_days'))

async def set_cron_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_INTERVAL_MINUTES
    context.user_data['schedule_ch_id'] = ch_db_id
    context.user_data['schedule_cron'] = True
    await safe_edit(query, "⏱️ **إعداد CRON**\n\nأرسل تعبير CRON (مثال: `0 12 * * *` للنشر يومياً الساعة 12:00)\n\nالشرح:\n• دقيقة (0-59)\n• ساعة (0-23)\n• يوم (1-31)\n• شهر (1-12)\n• يوم أسبوع (0-6)")

async def set_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['selected_days_ch'] = ch_db_id
    context.user_data['selected_days'] = []
    context.user_data['state'] = UserState.SELECTING_DAYS
    await safe_edit(query, "اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(user_id, context))

async def build_days_keyboard(user_id, context):
    selected = context.user_data.get('selected_days', [])
    day_names = [get_text(user_id, 'monday'), get_text(user_id, 'tuesday'), get_text(user_id, 'wednesday'),
                 get_text(user_id, 'thursday'), get_text(user_id, 'friday'), get_text(user_id, 'saturday'),
                 get_text(user_id, 'sunday')]
    keyboard = []
    for i in range(0, 7, 3):
        row = []
        for j in range(3):
            if i + j < 7:
                day_index = i + j
                name = day_names[day_index]
                mark = "✅ " if day_index in selected else ""
                row.append(InlineKeyboardButton(f"{mark}{name}", callback_data=f"{CallbackData.SCHEDULE_DAY_SELECT_PREFIX}{day_index}"))
        if row:
            keyboard.append(row)
    keyboard.append([
        InlineKeyboardButton("✔️ حفظ", callback_data=CallbackData.SCHEDULE_SAVE_DAYS),
        InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)
    ])
    return InlineKeyboardMarkup(keyboard)

async def day_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    day = int(query.data.split(":")[-1])
    selected = context.user_data.get('selected_days', [])
    if day in selected:
        selected.remove(day)
    else:
        selected.append(day)
    context.user_data['selected_days'] = selected
    await safe_edit(query, "اختر أيام النشر (بتوقيت مكة):", reply_markup=await build_days_keyboard(user_id, context))

async def save_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch = context.user_data.get('selected_days_ch')
    if ch:
        days_json = json.dumps(context.user_data.get('selected_days', []))
        await db_save_schedule(ch, 'days', days_of_week=days_json)
        await db_set_next_publish_date(ch, None)
        context.user_data.pop('selected_days_ch', None)
        context.user_data.pop('selected_days', None)
        context.user_data.pop('state', None)
        await safe_edit(query, get_text(user_id, 'days_saved'))
        await schedule_menu_callback(update, context)
    else:
        await safe_edit(query, get_text(user_id, 'error'))

async def set_dates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_DATES
    context.user_data['schedule_ch_id'] = ch_db_id
    await safe_edit(query, get_text(user_id, 'send_dates'))

async def set_publish_time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ch_db_id = int(query.data.split(":")[-1])
    context.user_data['state'] = UserState.WAITING_PUBLISH_TIME
    context.user_data['schedule_ch_id'] = ch_db_id
    await safe_edit(query, get_text(user_id, 'send_time'))

async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]])
    await safe_edit(query, get_text(user_id, 'help'), reply_markup=keyboard)

async def support_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 كتابة تذكرة", callback_data=CallbackData.SUPPORT_TICKET)],
        [InlineKeyboardButton("❓ المساعدة", callback_data=CallbackData.SUPPORT_HELP)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, get_text(user_id, 'support_welcome'), reply_markup=keyboard)

async def support_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.SUPPORT_MENU)]])
    await safe_edit(query, get_text(user_id, 'support_help'), reply_markup=keyboard)

async def support_ticket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data['support_mode'] = True
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 إلغاء", callback_data=CallbackData.SUPPORT_MENU)]])
    await safe_edit(query, "📝 **اكتب رسالتك** (سيتم إرسالها كتذكرة دعم)\nيمكنك إلغاء العملية بالضغط على الزر أدناه.", reply_markup=keyboard)

async def support_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await support_menu_callback(update, context)

async def trial_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if await db_has_used_trial(user_id):
        await safe_edit(query, get_text(user_id, 'trial_used'))
        return
    if await db_has_active_subscription(user_id):
        await safe_edit(query, get_text(user_id, 'already_subscribed'))
        return
    await db_activate_trial(user_id)
    await safe_edit(query, get_text(user_id, 'trial'))
    await main_menu_callback(update, context)

async def subscribe_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if await db_has_active_subscription(user_id):
        days = await db_get_subscription_days_left(user_id)
        await safe_edit(query, f"✅ اشتراكك مفعل، متبقي {days} يوم\nشكراً لدعمك ❤️")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 1 يوم - 5 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_1),
         InlineKeyboardButton("⭐ 2 يوم - 9 نجوم", callback_data=CallbackData.BUY_SUBSCRIPTION_2)],
        [InlineKeyboardButton("⭐ شهر (30 يوم) - 50 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_30),
         InlineKeyboardButton("⭐ 3 أشهر (90 يوم) - 120 نجمة", callback_data=CallbackData.BUY_SUBSCRIPTION_90)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, get_text(user_id, 'subscribe'), reply_markup=keyboard)

async def buy_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, days: int, price: int, title: str):
    query = update.callback_query
    user_id = update.effective_user.id
    try:
        await context.bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=f"اشتراك {days} يوم",
            payload=f"sub_{days}_{price}",
            currency="XTR",
            prices=[LabeledPrice(label=f"اشتراك {days} يوم", amount=price)],
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            is_flexible=False
        )
    except Exception as e:
        await safe_edit(query, f"❌ خطأ: {str(e)[:100]}")

async def buy_subscription_1_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_subscription_callback(update, context, 1, 5, "اشتراك 1 يوم")

async def buy_subscription_2_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_subscription_callback(update, context, 2, 9, "اشتراك 2 يوم")

async def buy_subscription_30_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_subscription_callback(update, context, 30, 50, "اشتراك شهر")

async def buy_subscription_90_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await buy_subscription_callback(update, context, 90, 120, "اشتراك 3 أشهر")

async def developer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    text = f"""👑 **معلومات المطور**
━━━━━━━━━━━━━━━━━━━━━━
🤖 **البوت:** {BOT_NAME}
📦 **الإصدار:** 19.3.1
👨‍💻 **المطور:** @RelaxMgr
━━━━━━━━━━━━━━━━━━━━━━
📞 **طرق التواصل:**
✅ **تيليجرام:** @RelaxMgr
✅ **البوت:** @{BOT_USERNAME}"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 تواصل مع المطور", url=f"https://t.me/RelaxMgr")],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    updates_channel = await db_get_updates_channel()
    if updates_channel:
        text = f"""📢 **قناة التحديثات**
━━━━━━━━━━━━━━━━━━━━━━
📌 القناة: @{updates_channel}

📢 تابع القناة لمعرفة آخر التحديثات:
• ميزات جديدة ✨
• تحسينات الأداء ⚡
• إصلاحات الأخطاء 🔧"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 افتح القناة", url=f"https://t.me/{updates_channel}")],
            [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
        ])
    else:
        text = """📢 **لم يتم تعيين قناة التحديثات بعد**

📌 **لتعيين قناة التحديثات:**
1. استخدم `/admin_panel`
2. اضغط على `⚙️ قناة التحديثات`
3. أرسل معرف القناة"""
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("👑 الذهاب للوحة الأدمن", callback_data=CallbackData.ADMIN_PANEL)],
            [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
        ])
    await safe_edit(query, text, reply_markup=keyboard)

async def referral_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    referral_code = await db_get_referral_code(user_id)
    if not referral_code:
        referral_code = await db_generate_referral_code(user_id)
    stats = await db_get_referral_stats(user_id)
    settings = await db_get_referral_settings()
    reward_days = int(settings.get('reward_days_per_referral', '3'))
    welcome_points = int(settings.get('welcome_bonus_points', '10'))
    text = get_text(user_id, 'referral_title').format(
        referral_code, BOT_USERNAME, referral_code,
        stats['total_referrals'], stats['available_days'],
        reward_days, welcome_points
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'copy_link'), callback_data=f"{CallbackData.REFERRAL_COPY_LINK_PREFIX}{referral_code}"),
         InlineKeyboardButton(get_text(user_id, 'claim_reward'), callback_data=CallbackData.REFERRAL_CLAIM_REWARD)],
        [InlineKeyboardButton(get_text(user_id, 'referral_list'), callback_data=CallbackData.REFERRAL_LIST),
         InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def referral_copy_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    referral_code = query.data.split(":")[-1]
    text = f"🔗 **رابط الإحالة الخاص بك:**\n`https://t.me/{BOT_USERNAME}?start=ref_{referral_code}`\n\nيمكنك الضغط مع الاستمرار على الرابط لنسخه."
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.REFERRAL_MENU)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def referral_claim_reward_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    stats = await db_get_referral_stats(user_id)
    if stats['available_days'] <= 0:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.REFERRAL_MENU)]])
        await safe_edit(query, get_text(user_id, 'no_reward_available'), reply_markup=keyboard)
        return
    claimed = await db_claim_referral_reward(user_id)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.REFERRAL_MENU)]])
    await safe_edit(query, get_text(user_id, 'reward_claimed').format(claimed), reply_markup=keyboard)

async def referral_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    async def _get_referrals(conn):
        cur = await conn.execute("""
            SELECT r.referred_id, r.referred_at, r.is_rewarded,
                   u.first_name, u.username
            FROM referrals r
            LEFT JOIN users_cache u ON r.referred_id = u.user_id
            WHERE r.referrer_id = ?
            ORDER BY r.referred_at DESC LIMIT 20
        """, (user_id,))
        return await cur.fetchall()
    referrals = await execute_db(_get_referrals)
    if not referrals:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.REFERRAL_MENU)]])
        await safe_edit(query, get_text(user_id, 'no_referrals'), reply_markup=keyboard)
        return
    text = f"📊 **{get_text(user_id, 'referral_list')}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for referred_id, referred_at, is_rewarded, first_name, username in referrals:
        try:
            referred_dt = datetime.fromisoformat(referred_at)
            referred_mecca = utc_to_mecca(referred_dt)
            date_str = referred_mecca.strftime("%Y-%m-%d")
        except:
            date_str = referred_at[:10] if referred_at else "تاريخ غير معروف"
        status = "✅" if is_rewarded else "⏳"
        name = first_name or username or str(referred_id)
        text += f"{status} {name} - {date_str}\n"
    text += "\n✅ = تم منح المكافأة  |  ⏳ = قيد الانتظار"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'claim_reward'), callback_data=CallbackData.REFERRAL_CLAIM_REWARD)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.REFERRAL_MENU)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def reminder_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    settings = await db_get_user_reminder_settings(user_id)
    status_sub = "🟢 مفعل" if settings['subscription_reminder'] else "🔴 معطل"
    status_daily = "🟢 مفعل" if settings['daily_stats_reminder'] else "🔴 معطل"
    status_weekly = "🟢 مفعل" if settings['weekly_report'] else "🔴 معطل"
    text = get_text(user_id, 'reminder_title').format(status_sub, status_daily, status_weekly, settings['reminder_days_before'])
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'reminder_sub'), callback_data=CallbackData.REMINDER_TOGGLE_SUB),
         InlineKeyboardButton(get_text(user_id, 'reminder_daily'), callback_data=CallbackData.REMINDER_TOGGLE_DAILY)],
        [InlineKeyboardButton(get_text(user_id, 'reminder_weekly'), callback_data=CallbackData.REMINDER_TOGGLE_WEEKLY),
         InlineKeyboardButton(get_text(user_id, 'reminder_days_btn'), callback_data=CallbackData.REMINDER_SET_DAYS)],
        [InlineKeyboardButton(get_text(user_id, 'reminder_lang_btn'), callback_data=CallbackData.REMINDER_SET_LANG),
         InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def reminder_toggle_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    settings = await db_get_user_reminder_settings(user_id)
    await db_update_reminder_settings(user_id, subscription_reminder=not settings['subscription_reminder'])
    await reminder_menu_callback(update, context)

async def reminder_toggle_daily_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    settings = await db_get_user_reminder_settings(user_id)
    await db_update_reminder_settings(user_id, daily_stats_reminder=not settings['daily_stats_reminder'])
    await reminder_menu_callback(update, context)

async def reminder_toggle_weekly_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    settings = await db_get_user_reminder_settings(user_id)
    await db_update_reminder_settings(user_id, weekly_report=not settings['weekly_report'])
    await reminder_menu_callback(update, context)

async def reminder_set_days_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    context.user_data['state'] = UserState.WAITING_REMINDER_DAYS
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.REMINDER_MENU)]])
    await safe_edit(query, "⏰ **عدد أيام التذكير**\n\nأرسل عدد الأيام التي تريد أن يتم تذكيرك بها قبل انتهاء الاشتراك (1-10 أيام):", reply_markup=keyboard)

async def reminder_set_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("العربية 🇸🇦", callback_data=f"{CallbackData.REMINDER_LANG_PREFIX}ar"),
         InlineKeyboardButton("English 🇬🇧", callback_data=f"{CallbackData.REMINDER_LANG_PREFIX}en")],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.REMINDER_MENU)]
    ])
    await safe_edit(query, "🌐 **اختر لغة الإشعارات:**", reply_markup=keyboard)

async def reminder_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = query.data.split(":")[-1]
    await db_update_reminder_settings(user_id, notification_lang=lang)
    await reminder_menu_callback(update, context)

async def translation_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    current_lang = await get_user_translation_language(user_id)
    if current_lang == 'off':
        status_text = get_text(user_id, 'translation_status_off')
    else:
        status_text = get_text(user_id, 'translation_status_on').format(current_lang)
    text = f"""🌐 **{get_text(user_id, 'translation_settings')}**
━━━━━━━━━━━━━━━━━━━━━━
📌 **الحالة:** {status_text}
{get_text(user_id, 'translation_how_it_works')}
━━━━━━━━━━━━━━━━━━━━━━
{get_text(user_id, 'translation_choose')}"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'translation_off'), callback_data=CallbackData.TRANSLATION_OFF)],
        [InlineKeyboardButton("🇸🇦 العربية", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ar"),
         InlineKeyboardButton("🇬🇧 English", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}en")],
        [InlineKeyboardButton("🇫🇷 Français", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}fr"),
         InlineKeyboardButton("🇹🇷 Türkçe", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}tr")],
        [InlineKeyboardButton("🇨🇳 中文", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}zh"),
         InlineKeyboardButton("🇷🇺 Русский", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ru")],
        [InlineKeyboardButton("🇩🇪 Deutsch", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}de"),
         InlineKeyboardButton("🇪🇸 Español", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}es")],
        [InlineKeyboardButton("🇮🇹 Italiano", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}it"),
         InlineKeyboardButton("🇵🇹 Português", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}pt")],
        [InlineKeyboardButton("🇯🇵 日本語", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ja"),
         InlineKeyboardButton("🇰🇷 한국어", callback_data=f"{CallbackData.TRANSLATION_SET_PREFIX}ko")],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def translation_off_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    await set_user_translation_language(user_id, 'off')
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]])
    await safe_edit(query, get_text(user_id, 'translation_disabled'), reply_markup=keyboard)

async def translation_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = query.data.split(":")[-1]
    await set_user_translation_language(user_id, lang)
    lang_names = {
        'ar': 'العربية', 'en': 'English', 'fr': 'Français', 'tr': 'Türkçe',
        'zh': '中文', 'ru': 'Русский', 'de': 'Deutsch', 'es': 'Español',
        'it': 'Italiano', 'pt': 'Português', 'ja': '日本語', 'ko': '한국어'
    }
    lang_name = lang_names.get(lang, lang)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]])
    await safe_edit(query, get_text(user_id, 'translation_enabled').format(lang_name), reply_markup=keyboard)

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    await safe_edit(query, get_text(user_id, 'admin_panel'), reply_markup=get_admin_keyboard(user_id))

async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    users = await db_get_all_users()
    if not users:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا يوجد مستخدمون مسجلون.", reply_markup=keyboard)
        return
    text = "👥 **قائمة المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for uid, banned in users[:50]:
        status = "🚫 محظور" if banned else "✅ نشط"
        text += f"• `{uid}` - {status}\n"
    if len(users) > 50:
        text += f"\nو {len(users)-50} آخرون..."
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_banned_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    users = await db_get_all_users()
    banned_users = [u for u in users if u[1] == 1]
    if not banned_users:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا يوجد مستخدمون محظورون.", reply_markup=keyboard)
        return
    text = "🚫 **المستخدمون المحظورون**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for uid, _ in banned_users[:50]:
        text += f"• `{uid}`\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_USERS)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_unban_all_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    async def _unban_all(conn):
        await conn.execute("UPDATE users SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_all)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, "✅ تم إلغاء حظر جميع المستخدمين.", reply_markup=keyboard)

async def admin_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    channels = await db_all_users_channels(limit=500)
    if not channels:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا توجد قنوات مسجلة.", reply_markup=keyboard)
        return
    text = "📡 **قنوات المستخدمين**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for idx, (uid, ch_id, ch_tele, ch_name, banned) in enumerate(channels[:100], 1):
        status = "⛔ محظورة" if banned else "✅ نشطة"
        ban_status_text = "🔓 إلغاء الحظر" if banned else "⛔ حظر"
        ban_callback = f"{CallbackData.ADMIN_TOGGLE_CHANNEL_BAN_PREFIX}{ch_id}"
        text += f"{idx}. {status} `{ch_name}`\n   👤 المستخدم: `{uid}`\n   🆔 القناة: `{ch_tele}`\n"
    if len(channels) > 100:
        text += f"\nو {len(channels)-100} قناة أخرى..."
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_banned_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    channels = await db_all_users_channels(only_banned=True, limit=500)
    if not channels:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا توجد قنوات محظورة.", reply_markup=keyboard)
        return
    text = "⛔ **قنوات المستخدمين المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for uid, ch_id, ch_tele, ch_name, banned in channels[:50]:
        text += f"• المستخدم: `{uid}` | القناة: {ch_name} (`{ch_tele}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ تنشيط الكل", callback_data=CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_activate_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    async def _activate_all(conn):
        await conn.execute("UPDATE user_channels SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_activate_all)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, "✅ تم إلغاء حظر جميع قنوات المستخدمين.", reply_markup=keyboard)

async def admin_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    groups = await db_get_all_groups(only_banned=False)
    if not groups:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا توجد مجموعات مسجلة.", reply_markup=keyboard)
        return
    text = "👥 **المجموعات المسجلة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for gid, gname, username, added_by, added_at, banned in groups[:50]:
        status = "⛔ محظورة" if banned else "✅ نشطة"
        text += f"• {gname} (ID: `{gid}`)\n  أضيف بواسطة: `{added_by}`\n  الحالة: {status}\n"
    if len(groups) > 50:
        text += f"\nو {len(groups)-50} أخرى..."
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_banned_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    groups = await db_get_all_groups(only_banned=True)
    if not groups:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا توجد مجموعات محظورة.", reply_markup=keyboard)
        return
    text = "🚷 **المجموعات المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for gid, gname, username, added_by, added_at, banned in groups[:50]:
        text += f"• {gname} (ID: `{gid}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_GROUPS)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_unban_all_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    async def _unban_groups(conn):
        await conn.execute("UPDATE bot_groups SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_groups)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, "✅ تم إلغاء حظر جميع المجموعات.", reply_markup=keyboard)

async def admin_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    channels = await db_get_all_bot_channels(only_banned=False)
    if not channels:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا توجد قنوات أضيف إليها البوت.", reply_markup=keyboard)
        return
    text = "📢 **قنوات البوت**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for channel_id, channel_name, added_by, added_at, banned in channels[:50]:
        text += f"• {channel_name} (ID: `{channel_id}`)\n  أضيف بواسطة: `{added_by}`\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_banned_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    channels = await db_get_all_bot_channels(only_banned=True)
    if not channels:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, "📭 لا توجد قنوات بوت محظورة.", reply_markup=keyboard)
        return
    text = "🚫 **قنوات البوت المحظورة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for channel_id, channel_name, added_by, added_at, banned in channels[:50]:
        text += f"• {channel_name} (ID: `{channel_id}`)\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔓 إلغاء حظر الكل", callback_data=CallbackData.ADMIN_UNBAN_ALL_BOT_CHANNELS)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_unban_all_bot_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    async def _unban_bot_channels(conn):
        await conn.execute("UPDATE bot_channels SET banned=0 WHERE banned=1")
        await conn.commit()
    await execute_db(_unban_bot_channels)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, "✅ تم إلغاء حظر جميع قنوات البوت.", reply_markup=keyboard)

async def admin_monitor_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    all_users = await db_get_all_users()
    total_users = len(all_users)
    active_users = len([u for u in all_users if u[1] == 0])
    banned_users = len([u for u in all_users if u[1] == 1])
    admins_list = await get_all_bot_admins()
    admin_count = len(admins_list)
    all_channels = await db_all_users_channels()
    channels_count = len(all_channels)
    all_groups = await db_get_all_groups()
    groups_count = len(all_groups)
    text = (
        f"📂 **مراقبة المستخدمين**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **إجمالي المستخدمين:** `{total_users}`\n"
        f"✅ **النشطاء:** `{active_users}`\n"
        f"🚫 **المحظورون:** `{banned_users}`\n"
        f"👑 **المشرفون:** `{admin_count}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📡 **قنوات المستخدمين:** `{channels_count}`\n"
        f"👥 **المجموعات المسجلة:** `{groups_count}`\n"
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_add_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_ADMIN_ID_ADD
    await safe_edit(query, get_text(user_id, 'enter_admin_id'))

async def admin_remove_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    admins = await get_all_bot_admins()
    if not admins:
        await safe_edit(query, get_text(user_id, 'no_admins'))
        return
    text = "👑 المشرفون الحاليون:\n"
    for a in admins:
        text += f"- {a}\n"
    text += "\n" + get_text(user_id, 'enter_remove_admin_id')
    context.user_data['state'] = UserState.WAITING_ADMIN_ID_REMOVE
    await safe_edit(query, text)

async def admin_ram_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    try:
        import psutil
        mem = psutil.virtual_memory()
        text = f"🖥️ **حالة الرام**\n━━━━━━━━━━━━━━━━━━━━━━\n• الإجمالي: {round(mem.total / (1024**3), 1)} GB\n• المستخدم: {round(mem.used / (1024**3), 1)} GB\n• النسبة: {mem.percent}%"
    except:
        text = "🖥️ **حالة الرام**\n━━━━━━━━━━━━━━━━━━━━━━\n❌ تعذر جلب معلومات الرام"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    total, banned, posts, groups, channels = await db_stats()
    text = f"📊 **إحصائيات عامة**\n━━━━━━━━━━━━━━━━━━━━━━\n• المستخدمين: {total}\n• المحظورين: {banned}\n• المنشورات غير المنشورة: {posts}\n• المجموعات: {groups}\n• قنوات المستخدمين: {channels}"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_metrics_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    try:
        import psutil
        mem = psutil.virtual_memory()
        text = f"📈 **مقاييس الأداء**\n━━━━━━━━━━━━━━━━━━━━━━\n🖥️ **حالة النظام:**\n• إجمالي الرام: {round(mem.total / (1024**3), 1)} GB\n• المستخدم: {round(mem.used / (1024**3), 1)} GB\n• النسبة: {mem.percent}%"
    except:
        text = "📈 **مقاييس الأداء**\n━━━━━━━━━━━━━━━━━━━━━━\n❌ تعذر جلب معلومات النظام"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    try:
        import shutil
        backup_file = BACKUP_DIR / f"backup_{mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(DB_PATH, backup_file)
        backups = sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old_backup in backups[10:]:
            old_backup.unlink()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, f"✅ تم إنشاء نسخة احتياطية جديدة.\n📁 اسم الملف: `{backup_file.name}`", reply_markup=keyboard)
    except Exception as e:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, f"❌ فشل إنشاء النسخة: {str(e)[:100]}", reply_markup=keyboard)

async def admin_restore_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    backups = sorted(BACKUP_DIR.glob("backup_*.db"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not backups:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, get_text(user_id, 'no_backups'), reply_markup=keyboard)
        return
    keyboard = []
    for b in backups[:10]:
        keyboard.append([InlineKeyboardButton(b.name, callback_data=f"{CallbackData.ADMIN_RESTORE_BACKUP_SELECT_PREFIX}{b.name}")])
    keyboard.append([InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)])
    await safe_edit(query, get_text(user_id, 'select_backup'), reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_restore_backup_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    backup_name = query.data.split(":")[-1]
    backup_path = BACKUP_DIR / backup_name
    try:
        import shutil
        current_backup = BACKUP_DIR / f"pre_restore_{mecca_now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(DB_PATH, current_backup)
        shutil.copy2(backup_path, DB_PATH)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, f"✅ تم استعادة النسخة الاحتياطية بنجاح.\n📁 الملف: `{backup_name}`", reply_markup=keyboard)
    except Exception as e:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, f"❌ فشل استعادة النسخة: {str(e)[:100]}", reply_markup=keyboard)

async def admin_backup_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    auto = await db_get_auto_backup()
    status = "مفعل" if auto else "معطل"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تبديل النسخ التلقائي", callback_data=CallbackData.ADMIN_TOGGLE_AUTO_BACKUP)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    text = f"⚙️ **إعدادات النسخ الاحتياطي**\n━━━━━━━━━━━━━━━━━━━━━━\n• النسخ التلقائي: {status}\n• الحد الأقصى للنسخ: {MAX_BACKUPS}\n\nيمكنك تبديل الحالة بالزر أدناه."
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_toggle_auto_backup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    auto = await db_get_auto_backup()
    new_auto = not auto
    await db_set_auto_backup(new_auto)
    status = "مفعل" if new_auto else "معطل"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_BACKUP_SETTINGS)]])
    await safe_edit(query, f"✅ تم تغيير إعداد النسخ التلقائي إلى: {status}", reply_markup=keyboard)

async def admin_change_interval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    current = await db_get_publish_interval()
    current_min = current // 60
    context.user_data['state'] = UserState.WAITING_INTERVAL_MINUTES
    context.user_data['admin_interval'] = True
    await safe_edit(query, f"⏱️ **وقت النشر العام الحالي:** {current_min} دقيقة\n\n📌 أرسل العدد الجديد من الدقائق (الحد الأدنى 1 دقيقة، الحد الأقصى 1440 دقيقة = 24 ساعة):")

async def admin_send_update_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    channel = await db_get_updates_channel()
    if not channel:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ تعيين قناة", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
            [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
        ])
        await safe_edit(query, "⚠️ **لم يتم تعيين قناة تحديثات بعد!**\n\nيرجى تعيين قناة التحديثات أولاً باستخدام الزر أدناه.", reply_markup=keyboard)
        return
    context.user_data['state'] = UserState.WAITING_UPDATE_TEXT
    await safe_edit(query, f"📢 أرسل نص التحديث الذي تريد نشره في قناة التحديثات @{channel}:")

async def admin_set_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_UPDATE_CHANNEL
    await safe_edit(query, """⚙️ **تعيين قناة التحديثات**

📢 أرسل معرف قناة التحديثات:

• `@username` (مثل: @my_channel)
• أو المعرف الرقمي (مثل: -1001234567890)

⚠️ **تنبيهات مهمة:**
• تأكد من أن البوت مشرف في القناة
• تأكد من أن البوت لديه صلاحية الإرسال
• القناة يجب أن تكون عامة (Public)""")

async def admin_show_update_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    channel = await db_get_updates_channel()
    if channel:
        text = f"📢 **قناة التحديثات الحالية:**\n`@{channel}`"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 فتح القناة", url=f"https://t.me/{channel}")],
            [InlineKeyboardButton("🔄 تغيير القناة", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
            [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
        ])
    else:
        text = "📢 **لم يتم تعيين قناة تحديثات بعد**"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ تعيين قناة", callback_data=CallbackData.ADMIN_SET_UPDATE_CHANNEL)],
            [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
        ])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_updates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_show_update_channel_callback(update, context)

async def admin_force_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    enabled = await db_get_force_subscribe_status()
    new_status = not enabled
    await db_set_force_subscribe_status(new_status)
    status_text = "مفعل" if new_status else "معطل"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, f"✅ تم {status_text} الاشتراك الإجباري.", reply_markup=keyboard)

async def admin_set_force_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_FORCE_CHANNEL
    await safe_edit(query, "⚙️ أرسل معرف قناة الاشتراك الإجباري (مثال: @channel_username):")

async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_BROADCAST
    await safe_edit(query, "📨 أرسل النص الذي تريد إرساله إلى جميع المستخدمين:")

async def admin_confirm_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    broadcast_text = context.user_data.get('broadcast_text', '')
    if not broadcast_text:
        await safe_edit(query, "❌ لا يوجد نص للإرسال")
        return
    dangerous_patterns = [r'<script', r'javascript:', r'data:', r'vbscript:', r'<\?php', r'<%', r'{%']
    for pattern in dangerous_patterns:
        if re.search(pattern, broadcast_text, re.IGNORECASE):
            await safe_edit(query, "❌ النص يحتوي على كود ضار! تم منع الإرسال.")
            return
    if len(broadcast_text) > 4000:
        await safe_edit(query, "❌ النص طويل جداً (الحد الأقصى 4000 حرف)")
        return
    await safe_edit(query, "📨 جاري الإرسال... يرجى الانتظار")
    async def _get_active_users(conn):
        cur = await conn.execute("SELECT user_id FROM users WHERE banned = 0")
        return [row[0] for row in await cur.fetchall()]
    users = await execute_db(_get_active_users)
    sent = 0
    failed = 0
    if not users:
        await safe_edit(query, "📭 لا يوجد مستخدمين نشطين لإرسال الرسالة لهم.")
        return
    sem = asyncio.Semaphore(20)
    async def send_one(uid):
        async with sem:
            try:
                await safe_send(context.bot, uid, broadcast_text)
                return True
            except:
                return False
    tasks = [send_one(uid) for uid in users]
    results = await asyncio.gather(*tasks)
    sent = sum(results)
    failed = len(results) - sent
    context.user_data.pop('broadcast_text', None)
    context.user_data.pop('state', None)
    msg = f"✅ **تم إرسال الرسالة**\n\n📨 تم الإرسال إلى: {sent} مستخدم\n❌ فشل الإرسال إلى: {failed} مستخدم"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, msg, reply_markup=keyboard)

async def admin_support_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    tickets = await db_get_all_tickets(limit=20)
    if not tickets:
        await safe_edit(query, "📭 لا توجد تذاكر دعم مسجلة")
        return
    text = "📋 **تذاكر الدعم**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for tid, uid_u, username, msg, ticket_num, status, created_at in tickets:
        try:
            created_utc = datetime.fromisoformat(created_at)
            created_mecca = utc_to_mecca(created_utc)
            created_str = created_mecca.strftime("%Y-%m-%d %H:%M")
        except:
            created_str = created_at
        status_icon = "🟡" if status == "pending" else "🟢"
        msg_preview = msg[:40] + "..." if len(msg) > 40 else msg
        text += f"\n{status_icon} #{ticket_num} | 👤 {username}\n🆔 `{uid_u}` | 📅 {created_str}\n📝 {msg_preview}\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_delete_all_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    confirm_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، احذف الكل", callback_data=CallbackData.ADMIN_CONFIRM_DELETE_TICKETS),
         InlineKeyboardButton("❌ لا، إلغاء", callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit(query, get_text(user_id, 'confirm_delete_tickets'), reply_markup=confirm_kb)

async def admin_confirm_delete_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    count = await db_delete_all_tickets()
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
    await safe_edit(query, get_text(user_id, 'tickets_deleted').format(count), reply_markup=keyboard)

async def admin_manage_sendcode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    allowed_user = await db_get_allowed_sendcode_user()
    if allowed_user:
        current_text = get_text(user_id, 'current_allowed_user').format(f"`{allowed_user}`")
    else:
        current_text = get_text(user_id, 'current_allowed_user').format(get_text(user_id, 'no_allowed_user'))
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'set_new_sendcode_user'), callback_data=CallbackData.ADMIN_SET_SENDCODE_USER)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit(query, current_text, reply_markup=keyboard)

async def admin_set_sendcode_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_SENDCODE_USER
    await safe_edit(query, "➕ أرسل معرف المستخدم (user_id) الذي تريد منحه صلاحية استخدام أمر /sendcode:")

async def admin_show_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    log_ch = await db_get_log_channel_id()
    if log_ch:
        text = f"📋 **قناة التقارير الحالية:**\n`{log_ch}`\n\nيمكنك تغييرها باستخدام الأمر `/set_log_channel`\nأو الضغط على زر 'تعيين قناة التقارير'."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, text, reply_markup=keyboard)
    else:
        text = "📋 **لم يتم تعيين قناة تقارير بعد.**\nاستخدم الأمر `/set_log_channel` أو زر 'تعيين قناة التقارير' لتعيينها."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]])
        await safe_edit(query, text, reply_markup=keyboard)

async def admin_set_log_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_LOG_CHANNEL
    await safe_edit(query, "📢 **تعيين قناة التقارير**\n\nأرسل معرف القناة (ID) أو معرف المستخدم (@username) للقناة التي تريد استقبال التقارير فيها.\n\nمثال: `-1001234567890` أو `@channel_username`\n\n⚠️ تأكد من أن البوت مشرف في القناة ولديه صلاحية إرسال الرسائل.")

async def admin_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    await safe_edit(query, "💬 **إدارة ردود المجموعة**", reply_markup=get_replies_keyboard())

async def admin_add_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_KEYWORD
    await safe_edit(query, "📝 **إضافة رد تلقائي**\n\nأرسل الكلمة المفتاحية (مثل: مرحبا، السلام عليكم، كيف حالك):")

async def admin_list_replies_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    replies = await db_get_all_replies()
    if not replies:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_REPLIES)]])
        await safe_edit(query, "📭 لا توجد ردود مسجلة.", reply_markup=keyboard)
        return
    text = "💬 **قائمة الردود التلقائية**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for kw, rep in replies[:30]:
        short_rep = rep[:40] + "..." if len(rep) > 40 else rep
        text += f"• **{kw}** → {short_rep}\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_REPLIES)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_del_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    if query and query.data.startswith("admin_del_reply_"):
        keyword = query.data.replace("admin_del_reply_", "")
        if await db_del_reply(keyword):
            await query.answer(f"✅ تم حذف رد {keyword}", show_alert=True)
        else:
            await query.answer(f"❌ الكلمة {keyword} غير موجودة", show_alert=True)
        await admin_list_replies_callback(update, context)
        return
    else:
        context.user_data['state'] = UserState.WAITING_REPLY
        context.user_data['admin_del_reply'] = True
        await safe_edit(query, "🗑️ **حذف رد تلقائي**\n\nأرسل الكلمة المفتاحية لحذف ردها:")

async def admin_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    await safe_edit(query, "🚫 **إدارة الكلمات المحظورة على مستوى البوت (لجميع المجموعات)**", reply_markup=get_banned_words_admin_keyboard())

async def admin_add_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_GLOBAL_BANNED_WORD
    await safe_edit(query, "➕ أرسل الكلمة التي تريد حظرها على مستوى البوت:")

async def admin_list_banned_words_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    words = await db_get_banned_words(-1)
    if not words:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_BANNED_WORDS)]])
        await safe_edit(query, "📭 لا توجد كلمات محظورة عامة.", reply_markup=keyboard)
        return
    text = "🚫 **الكلمات المحظورة عامة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for w, by, at in words[:20]:
        text += f"• `{w}` (أضيف بواسطة {by})\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_BANNED_WORDS)]])
    await safe_edit(query, text, reply_markup=keyboard)

async def admin_remove_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_REMOVE_GLOBAL_BANNED_WORD
    await safe_edit(query, "🗑️ أرسل الكلمة التي تريد حذفها من الكلمات المحظورة العامة:")

async def admin_del_banned_word_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    word = query.data.replace("admin_del_banned_word_", "")
    async def _remove_global_word(conn):
        await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
        await conn.commit()
    await execute_db(_remove_global_word)
    await query.answer(f"✅ تم حذف {word}", show_alert=True)
    await admin_list_banned_words_callback(update, context)

async def admin_toggle_channel_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    channel_db_id = int(query.data.split(":")[-1])
    async def _get_ban(conn):
        cur = await conn.execute("SELECT banned FROM user_channels WHERE id=?", (channel_db_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    current = await execute_db(_get_ban)
    new_status = 0 if current == 1 else 1
    async def _update_ban(conn):
        await conn.execute("UPDATE user_channels SET banned=? WHERE id=?", (new_status, channel_db_id))
        await conn.commit()
    await execute_db(_update_ban)
    status_text = "محظورة" if new_status == 1 else "نشطة"
    await query.answer(f"✅ تم تغيير حالة القناة إلى: {status_text}", show_alert=True)
    await admin_all_channels_callback(update, context)

async def admin_toggle_group_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    group_chat_id = int(query.data.split(":")[-1])
    async def _get_ban(conn):
        cur = await conn.execute("SELECT banned FROM bot_groups WHERE chat_id=?", (group_chat_id,))
        row = await cur.fetchone()
        return row[0] if row else 0
    current = await execute_db(_get_ban)
    new_status = 0 if current == 1 else 1
    async def _update_ban(conn):
        await conn.execute("UPDATE bot_groups SET banned=? WHERE chat_id=?", (new_status, group_chat_id))
        await conn.commit()
    await execute_db(_update_ban)
    status_text = "محظورة" if new_status == 1 else "نشطة"
    await query.answer(f"✅ تم تغيير حالة المجموعة إلى: {status_text}", show_alert=True)
    await admin_groups_callback(update, context)

async def auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    new_status = await db_toggle_auto_reply(chat_id)
    settings = await db_get_auto_reply_settings(chat_id)
    status_text = "🟢 مفعل" if new_status else "🔴 معطل"
    await safe_edit(query, f"✅ تم تغيير حالة الردود التلقائية إلى: {status_text}", reply_markup=get_auto_reply_keyboard(chat_id, settings))

async def auto_reply_admins_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    settings = await db_get_auto_reply_settings(chat_id)
    new_status = not settings['only_admins']
    await db_set_auto_reply_only_admins(chat_id, new_status)
    settings = await db_get_auto_reply_settings(chat_id)
    admin_text = "👑 مشرفين فقط" if new_status else "👥 الجميع"
    await safe_edit(query, f"✅ تم تغيير وضع الردود إلى: {admin_text}", reply_markup=get_auto_reply_keyboard(chat_id, settings))

async def auto_reply_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، إعادة تعيين", callback_data=f"auto_reply_confirm_reset:{chat_id}")],
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"auto_reply_cancel:{chat_id}")]
    ])
    await safe_edit(query, "⚠️ **تأكيد إعادة التعيين**\n\nسيتم حذف جميع الردود المخصصة في هذه المجموعة وإعادة تعيين الإعدادات إلى الافتراضية.\nالردود المدمجة ستبقى كما هي.\n\nهل أنت متأكد؟", reply_markup=keyboard)

async def auto_reply_confirm_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    async def _reset_replies(conn):
        await conn.execute("DELETE FROM group_replies WHERE keyword LIKE ?", (f"{chat_id}:%",))
        await conn.commit()
    await execute_db(_reset_replies)
    await db_set_auto_reply_enabled(chat_id, True)
    await db_set_auto_reply_only_admins(chat_id, False)
    settings = await db_get_auto_reply_settings(chat_id)
    await safe_edit(query, "✅ **تم إعادة تعيين الردود بنجاح!**\n\n• تم حذف جميع الردود المخصصة\n• تم تفعيل الردود التلقائية\n• وضع الردود: الجميع\n• الردود المدمجة ما زالت تعمل", reply_markup=get_auto_reply_keyboard(chat_id, settings))

async def auto_reply_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    settings = await db_get_auto_reply_settings(chat_id)
    await safe_edit(query, "❌ تم إلغاء إعادة التعيين", reply_markup=get_auto_reply_keyboard(chat_id, settings))

async def auto_reply_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    async def _get_stats(conn):
        cur = await conn.execute("SELECT COUNT(*) FROM group_replies WHERE keyword LIKE ?", (f"{chat_id}:%",))
        custom_count = (await cur.fetchone())[0]
        return {
            'custom_replies': custom_count,
            'embedded_replies': len(ALL_REPLIES),
            'total_replies': custom_count + len(ALL_REPLIES)
        }
    stats = await execute_db(_get_stats)
    settings = await db_get_auto_reply_settings(chat_id)
    status_text = "🟢 مفعل" if settings['enabled'] else "🔴 معطل"
    admin_text = "👑 مشرفين فقط" if settings['only_admins'] else "👥 الجميع"
    text = f"""📊 **إحصائيات الردود التلقائية**

━━━━━━━━━━━━━━━━━━━━━━
📝 **الحالة:** {status_text}
👥 **المستخدمون:** {admin_text}
━━━━━━━━━━━━━━━━━━━━━━
📋 **الردود المخصصة:** {stats['custom_replies']}
💾 **الردود المدمجة:** {stats['embedded_replies']}
📚 **إجمالي الردود:** {stats['total_replies']}
━━━━━━━━━━━━━━━━━━━━━━

📌 **ملاحظة:** الردود المدمجة لا يمكن حذفها، ولكن يمكن تعطيلها."""
    await safe_edit(query, text, reply_markup=get_auto_reply_keyboard(chat_id, settings))

async def user_auto_reply_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split(":")[-1])
    current_status = await db_get_user_auto_reply_status(user_id)
    new_status = not current_status
    await db_set_user_auto_reply_status(user_id, new_status)
    status_text = "🟢 مفعل" if new_status else "🔴 معطل"
    await safe_edit(query, f"✅ تم تغيير حالة الردود التلقائية إلى: {status_text}", reply_markup=get_user_auto_reply_keyboard(user_id, new_status))

async def admin_auto_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    groups = await db_get_user_groups(user_id)
    if not groups:
        await safe_edit(query, "📭 لا توجد مجموعات مسجلة.\nأضف البوت إلى مجموعة واجعلها نشطة.")
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        settings = await db_get_auto_reply_settings(gid)
        status = "🟢" if settings['enabled'] else "🔴"
        keyboard.append([InlineKeyboardButton(f"{status} {gname[:30]}", callback_data=f"admin_auto_reply_select:{gid}")])
    keyboard.append([InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)])
    await safe_edit(query, "📝 **إدارة الردود التلقائية**\n\nاختر مجموعة للتحكم في إعدادات الردود:\n🟢 = مفعل  |  🔴 = معطل", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_auto_reply_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer("❌ غير مصرح", show_alert=True)
        return
    settings = await db_get_auto_reply_settings(chat_id)
    async def _get_name(conn):
        cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return row[0] if row else str(chat_id)
    group_name = await execute_db(_get_name)
    await safe_edit(query, f"📝 **إعدادات الردود: {group_name}**\n\nاختر الإعداد المطلوب:", reply_markup=get_auto_reply_keyboard(chat_id, settings))

async def nsfw_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    status = "🟢 مفعل" if NSFW_ENABLED else "🔴 معطل"
    threshold = f"{NSFW_THRESHOLD * 100:.0f}%"
    text = f"""🔞 **إعدادات كشف المحتوى غير اللائق (NSFW)**

━━━━━━━━━━━━━━━━━━━━━━
📌 **الحالة:** {status}
📊 **نسبة الحساسية:** {threshold}
🖼️ **حجم الصورة الأقصى:** {NSFW_MAX_FILE_SIZE // (1024*1024)} ميجابايت
🎬 **حجم الفيديو الأقصى:** {NSFW_MAX_VIDEO_SIZE // (1024*1024)} ميجابايت
📸 **عدد إطارات الفيديو:** {NSFW_FRAMES}
🗄️ **تخزين مؤقت:** {len(NSFW_CACHE)} نتيجة
━━━━━━━━━━━━━━━━━━━━━━

📌 **الشرح:**
• عندما يرسل مستخدم صورة أو فيديو، يتحقق البوت من المحتوى
• إذا تجاوزت نسبة المحتوى غير اللائق {threshold}، يتم حذف الملف
• يتم تحليل {NSFW_FRAMES} إطارات من الفيديو للحصول على دقة أعلى
• النتائج يتم تخزينها مؤقتاً لمدة {NSFW_CACHE_TTL} ثانية

🔑 **مطلوب مفاتيح Sightengine API:**
• `SIGHTENGINE_API_USER` في ملف .env
• `SIGHTENGINE_API_SECRET` في ملف .env
• سجل مجاناً على: https://sightengine.com

⚙️ **اختر الإجراء المناسب:"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'🔴 تعطيل' if NSFW_ENABLED else '🟢 تفعيل'}", callback_data=CallbackData.NSFW_TOGGLE)],
        [InlineKeyboardButton("📊 تغيير نسبة الحساسية", callback_data=CallbackData.NSFW_THRESHOLD_SET)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.ADMIN_PANEL)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def nsfw_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    global NSFW_ENABLED
    NSFW_ENABLED = not NSFW_ENABLED
    os.environ["NSFW_ENABLED"] = "True" if NSFW_ENABLED else "False"
    await nsfw_settings_callback(update, context)

async def nsfw_threshold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_NSFW_THRESHOLD
    await safe_edit(query, """📊 **تغيير نسبة حساسية كشف NSFW**

أرسل النسبة المئوية المطلوبة (من 0 إلى 100):
• 70% = حساسية متوسطة (افتراضي)
• 50% = حساسية عالية (يكتشف محتوى أقل وضوحاً)
• 90% = حساسية منخفضة (يكتشف محتوى واضحاً فقط)

مثال: أرسل `75` أو `80`

⚠️ **تنبيه:** النسبة الأقل تزيد من احتمالية الحظر الخاطئ.""")

async def contests_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await contests_command_handler(update, context)

async def contest_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    contest_id = int(query.data.split(":")[-1])
    contest = await db_get_contest(contest_id)
    if not contest:
        await safe_edit(query, "❌ المسابقة غير موجودة.")
        return
    if contest['status'] != 'active':
        await safe_edit(query, "❌ هذه المسابقة غير متاحة حالياً.")
        return
    if await db_get_user_participation(user_id, contest_id):
        await safe_edit(query, get_text(user_id, 'contest_participated'))
        return
    context.user_data['contest_join_id'] = contest_id
    context.user_data['state'] = UserState.WAITING_CONTEST_ANSWER
    await safe_edit(query, f"📝 **المشاركة في المسابقة: {contest['title']}**\n\nأرسل إجابتك (نص) أو اضغط /skip للمشاركة بدون إجابة.")

async def contest_winners_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    winners = await db_get_contest_winners(limit=10)
    if not winners:
        text = get_text(user_id, 'no_winners')
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.CONTESTS_BACK)]
        ])
        await safe_edit(query, text, reply_markup=keyboard)
        return
    text = get_text(user_id, 'contest_winners_title')
    for contest_id, title, prize, winner_id, announced_at in winners:
        try:
            winner = await context.bot.get_chat(winner_id)
            winner_name = winner.first_name or str(winner_id)
        except:
            winner_name = str(winner_id)
        try:
            announced_dt = datetime.fromisoformat(announced_at)
            announced_mecca = utc_to_mecca(announced_dt)
            date_str = announced_mecca.strftime("%Y-%m-%d")
        except:
            date_str = announced_at[:10] if announced_at else "?"
        text += f"📌 **{title}**\n🎁 {prize}\n👤 {winner_name}\n📅 {date_str}\n━━━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=CallbackData.CONTEST_WINNERS)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=CallbackData.CONTESTS_BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def contests_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await contests_menu_callback(update, context)

async def admin_create_contest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_CONTEST_TITLE
    await safe_edit(query, get_text(user_id, 'create_contest_title'))

async def admin_declare_winner_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if user_id != PRIMARY_OWNER_ID and not await is_bot_admin(user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    await safe_edit(query, get_text(user_id, 'declare_winner_usage'))

async def security_links_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    settings['links'] = not settings['links']
    await db_set_security_settings(chat_id, **settings)
    await safe_edit(query, "✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_mentions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    settings['mentions'] = not settings['mentions']
    await db_set_security_settings(chat_id, **settings)
    await safe_edit(query, "✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_warn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    settings['warn'] = not settings['warn']
    await db_set_security_settings(chat_id, **settings)
    await safe_edit(query, "✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_slowmode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    settings['slow_mode'] = not settings['slow_mode']
    await db_set_security_settings(chat_id, **settings)
    await safe_edit(query, "✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_banned_words_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['banned_words_chat_id'] = chat_id
    await safe_edit(query, "🚫 إدارة الكلمات المحظورة للمجموعة", reply_markup=get_group_banned_words_keyboard(chat_id))

async def security_welcome_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    settings['welcome_enabled'] = not settings['welcome_enabled']
    await db_set_security_settings(chat_id, **settings)
    await safe_edit(query, "✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_goodbye_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    settings = await db_get_security_settings(chat_id)
    settings['goodbye_enabled'] = not settings['goodbye_enabled']
    await db_set_security_settings(chat_id, **settings)
    await safe_edit(query, "✅ تم التحديث")
    await group_settings_callback(update, context)

async def security_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.delete()

async def security_select_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await safe_edit(query, "❌ **غير مصرح**\n\nتأكد من:\n1. أن البوت مشرف في المجموعة\n2. أن لديك صلاحيات مشرف في المجموعة")
        return
    settings = await db_get_security_settings(chat_id)
    async def _get_group_name(conn):
        cur = await conn.execute("SELECT chat_name FROM bot_groups WHERE chat_id=?", (chat_id,))
        row = await cur.fetchone()
        return row[0] if row else str(chat_id)
    gname = await execute_db(_get_group_name)
    text = f"""⚙️ **لوحة تحكم المجموعة: {gname}**
━━━━━━━━━━━━━━━━━━━━━━
🔗 حذف الروابط: {'✅' if settings['links'] else '❌'}
@ حذف المعرفات: {'✅' if settings['mentions'] else '❌'}
🚫 كلمات محظورة: {'✅' if settings.get('delete_banned_words', False) else '❌'}
⏱️ وضع بطيء: {'✅' if settings['slow_mode'] else '❌'}
🎯 ترحيب: {'✅' if settings['welcome_enabled'] else '❌'}
👋 وداع: {'✅' if settings['goodbye_enabled'] else '❌'}
🔊 تحذير: {'✅' if settings['warn'] else '❌'}
━━━━━━━━━━━━━━━━━━━━━━
⚖️ **العقوبة التلقائية:** {'طرد' if settings.get('auto_penalty') == 'kick' else 'حظر' if settings.get('auto_penalty') == 'ban' else 'كتم' if settings.get('auto_penalty') == 'mute' else 'لا شيء'}
━━━━━━━━━━━━━━━━━━━━━━
💡 **اختر الإجراء المناسب:**"""
    await safe_edit(query, text, reply_markup=security_keyboard(chat_id))

async def security_refresh_groups_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    groups = await db_get_user_groups(user_id)
    if not groups:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ أضف البوت إلى مجموعة", url=f"https://t.me/{BOT_USERNAME}?startgroup")],
            [InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)],
            [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
        ])
        await safe_edit(query, "🔐 **إعدادات الأمان**\n\n⚠️ لم يتم العثور على مجموعات.\n\n📌 **لتفعيل إعدادات الأمان:**\n1. أضف البوت إلى مجموعتك\n2. اجعل البوت مشرفاً\n3. استخدم الأمر /syncgroup في المجموعة", reply_markup=keyboard)
        return
    keyboard = []
    for gid, gname, _, _ in groups:
        name = gname[:40] + "..." if len(gname) > 43 else gname
        keyboard.append([InlineKeyboardButton(f"📌 {name}", callback_data=f"{CallbackData.SECURITY_SELECT_GROUP}{gid}")])
    keyboard.append([InlineKeyboardButton("🔄 تحديث القائمة", callback_data=CallbackData.SECURITY_REFRESH_GROUPS)])
    keyboard.append([InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)])
    await safe_edit(query, "🔐 **إعدادات الأمان والإجراءات المتقدمة**\n\n📌 اختر المجموعة التي تريد إدارة إعداداتها:", reply_markup=InlineKeyboardMarkup(keyboard))

async def banned_words_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    await safe_edit(query, "➕ أرسل الكلمة التي تريد إضافتها للكلمات المحظورة:")

async def banned_words_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    words = await db_get_banned_words(chat_id)
    if not words:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]])
        await safe_edit(query, "📭 لا توجد كلمات محظورة في هذه المجموعة.", reply_markup=keyboard)
        return
    text = "🚫 **الكلمات المحظورة في المجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for word, added_by, added_at in words[:20]:
        text += f"• `{word}` (أضيف بواسطة {added_by})\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=f"{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}{chat_id}")]])
    await safe_edit(query, text, reply_markup=keyboard)

async def banned_words_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_REMOVE_GROUP_BANNED_WORD
    context.user_data['banned_words_chat_id'] = chat_id
    await safe_edit(query, "🗑️ أرسل الكلمة التي تريد حذفها من الكلمات المحظورة:")

async def penalty_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    await safe_edit(query, "⚖️ **اختر العقوبة التلقائية:**\n\nسيتم تطبيق هذه العقوبة عند مخالفة قواعد الحماية:", reply_markup=penalty_keyboard(chat_id))

async def penalty_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    await db_set_security_settings(chat_id, auto_penalty='kick')
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    await safe_edit(query, "✅ تم تعيين العقوبة التلقائية إلى: **طرد**", reply_markup=keyboard)

async def penalty_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    await db_set_security_settings(chat_id, auto_penalty='ban')
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
    await safe_edit(query, "✅ تم تعيين العقوبة التلقائية إلى: **حظر**", reply_markup=keyboard)

async def penalty_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['penalty_chat_id'] = chat_id
    await safe_edit(query, "🔇 **اختر مدة الكتم:**", reply_markup=mute_duration_keyboard(chat_id))

async def penalty_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data_parts = query.data.split(":")
    if len(data_parts) == 3:
        duration = data_parts[1]
        chat_id = int(data_parts[2])
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
            return
        if duration == "permanent":
            minutes = -1
            text = "دائم"
        else:
            minutes = int(duration)
            if minutes < 60:
                text = f"{minutes} دقيقة"
            elif minutes < 1440:
                text = f"{minutes // 60} ساعة"
            else:
                text = f"{minutes // 1440} يوم"
        await db_set_security_settings(chat_id, auto_penalty='mute', auto_mute_duration=minutes)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text(user_id, 'back'), callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]])
        await safe_edit(query, f"✅ تم تعيين العقوبة التلقائية إلى: **كتم {text}**", reply_markup=keyboard)

async def advanced_actions_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if chat_id == 0:
        await safe_edit(query, "⚠️ يرجى اختيار مجموعة أولاً باستخدام أمر /security")
        return
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    await safe_edit(query, "🛠️ **الإجراءات المتقدمة للمجموعة**\n━━━━━━━━━━━━━━━━━━━━━━\nاختر الإجراء المطلوب:", reply_markup=get_advanced_group_actions_keyboard(chat_id))

async def group_action_ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_BAN_USER
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "🚫 **حظر مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /ban\n\nيمكنك إضافة سبب بعد المعرف: `/ban 123456789 السبب`")

async def group_action_mute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    await safe_edit(query, "🔇 **كتم مستخدم**\n\nاختر مدة الكتم:", reply_markup=get_advanced_mute_duration_keyboard(chat_id))

async def advanced_mute_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    parts = query.data.split(":")
    if len(parts) == 3:
        minutes = int(parts[1])
        chat_id = int(parts[2])
        if not await is_authorized_in_group(context.bot, chat_id, user_id):
            await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
            return
        context.user_data['mute_minutes'] = minutes
        context.user_data['state'] = UserState.WAITING_MUTE_USER
        context.user_data['advanced_chat_id'] = chat_id
        if minutes == 0:
            msg = "🔇 **كتم دائم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute"
        elif minutes < 60:
            msg = f"🔇 **كتم {minutes} دقيقة**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute"
        elif minutes < 1440:
            msg = f"🔇 **كتم {minutes // 60} ساعة**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute"
        else:
            msg = f"🔇 **كتم {minutes // 1440} يوم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /mute"
        await safe_edit(query, msg)

async def group_action_warn_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_WARN_USER
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "⚠️ **تحذير مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /warn\n\n📌 بعد 3 تحذيرات يتم حظر المستخدم تلقائياً")

async def group_action_kick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_KICK_USER
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "👢 **طرد مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /kick")

async def group_action_restrict_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_RESTRICT_USER
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "🔒 **تقييد مستخدم**\n\nأرسل معرف المستخدم (user_id) أو قم بالرد على رسالة المستخدم ثم أرسل /restrict\n\n📌 التقييد يمنع المستخدم من إرسال الصور والفيديوهات والملفات")

async def group_action_pin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_PIN_MESSAGE
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "📌 **تثبيت رسالة**\n\nقم بالرد على الرسالة التي تريد تثبيتها ثم أرسل /pin")

async def group_action_log_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    text = await get_moderation_log(chat_id, 20)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=f"{CallbackData.GROUPS_SETTINGS_PREFIX}{chat_id}")]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def group_action_unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['state'] = UserState.WAITING_UNBAN_USER
    context.user_data['advanced_chat_id'] = chat_id
    await safe_edit(query, "🔓 **إلغاء حظر مستخدم**\n\nأرسل معرف المستخدم (user_id) لإلغاء حظره:\n`/unban 123456789`")

async def panel_lock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if await is_authorized_in_group(context.bot, chat_id, user_id):
        await db_set_chat_lock(chat_id, True, user_id)
        await safe_edit(query, get_text(user_id, 'locked'))
    else:
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)

async def panel_unlock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if await is_authorized_in_group(context.bot, chat_id, user_id):
        await db_set_chat_lock(chat_id, False)
        await safe_edit(query, get_text(user_id, 'unlocked'))
    else:
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)

async def panel_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.delete()

async def check_subscribe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    enabled = await db_get_force_subscribe_status()
    channel = await db_get_force_subscribe_channel()
    if enabled and channel:
        if await is_user_subscribed(context.bot, user_id, channel):
            await safe_edit(query, "✅ تم التحقق! أنت مشترك الآن.")
            await main_menu_callback(update, context)
        else:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 اشترك", url=f"https://t.me/{channel.lstrip('@')}"),
                 InlineKeyboardButton("🔄 تأكد", callback_data=CallbackData.CHECK_SUBSCRIBE),
                 InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
            ])
            await safe_edit(query, f"❌ لم تشترك في @{channel.lstrip('@')}", reply_markup=keyboard)
    else:
        await safe_edit(query, "⚠️ الاشتراك الإجباري غير مفعل")

async def publish_all_channels_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    channels = await db_get_channels(user_id)
    if not channels:
        await safe_edit(query, "📭 لا توجد قنوات للنشر فيها.")
        return
    await safe_edit(query, "📤 جاري النشر في جميع القنوات...")
    results = []
    success_count = 0
    fail_count = 0
    no_posts_count = 0
    for ch_db_id, ch_tele_id, ch_name, banned in channels:
        if banned:
            results.append(f"⛔ {ch_name}: قناة محظورة")
            continue
        post = await db_get_next_post(ch_db_id)
        if not post:
            results.append(f"📭 {ch_name}: لا توجد منشورات")
            no_posts_count += 1
            continue
        try:
            if post['media_type'] == 'photo' and post['media_file_id']:
                await context.bot.send_photo(ch_tele_id, post['media_file_id'], caption=post['text'] if post['text'] else None)
            elif post['media_type'] == 'video' and post['media_file_id']:
                await context.bot.send_video(ch_tele_id, post['media_file_id'], caption=post['text'] if post['text'] else None)
            else:
                await context.bot.send_message(ch_tele_id, post['text'])
            await db_mark_published(post['id'])
            await db_set_last_publish(ch_db_id, utc_now())
            await db_update_next_publish_date(ch_db_id)
            results.append(f"✅ {ch_name}: تم النشر بنجاح")
            success_count += 1
        except Exception as e:
            results.append(f"❌ {ch_name}: {str(e)[:50]}")
            fail_count += 1
        await asyncio.sleep(1)
    summary = f"📊 **نتائج النشر في جميع القنوات**\n━━━━━━━━━━━━━━━━━━━━━━\n✅ نجح: {success_count}\n❌ فشل: {fail_count}\n📭 لا توجد منشورات: {no_posts_count}\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    result_text = summary + "\n".join(results[:20])
    if len(results) > 20:
        result_text += f"\n\n... و {len(results)-20} نتيجة أخرى"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, result_text, reply_markup=keyboard)

async def channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    try:
        channel_db_id = int(query.data.split(":")[-1])
    except:
        channel_db_id = context.user_data.get('channel_stats_id')
    if not channel_db_id:
        await safe_edit(query, "⚠️ لم يتم تحديد القناة.")
        return
    channels = await db_get_channels(user_id)
    if not any(ch[0] == channel_db_id for ch in channels):
        await query.answer("❌ هذه القناة ليست لك", show_alert=True)
        return
    stats = await db_get_channel_stats(channel_db_id)
    ch_info = await db_get_channel_info(channel_db_id)
    channel_name = ch_info[1] if ch_info else "القناة"
    if stats['total_posts'] == 0:
        text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد منشورات بعد"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{channel_db_id}")],
            [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{channel_db_id}")],
            [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
        ])
        await safe_edit(query, text, reply_markup=keyboard)
        return
    text = f"📊 **إحصائيات {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📝 إجمالي المنشورات: {stats['total_posts']}\n"
    text += f"✅ المنشورة: {stats['published_posts']}\n"
    text += f"⏳ غير المنشورة: {stats['unpublished_posts']}\n"
    text += f"👁️ إجمالي المشاهدات: {stats['total_views']}\n"
    text += f"📊 متوسط المشاهدات: {stats['avg_views']}\n"
    if stats['last_post_time']:
        try:
            last_dt = datetime.fromisoformat(stats['last_post_time'])
            last_mecca = utc_to_mecca(last_dt)
            text += f"🕐 آخر نشر: {last_mecca.strftime('%Y-%m-%d %H:%M')}\n"
        except:
            pass
    if stats['first_post_time']:
        try:
            first_dt = datetime.fromisoformat(stats['first_post_time'])
            first_mecca = utc_to_mecca(first_dt)
            text += f"📅 أول نشر: {first_mecca.strftime('%Y-%m-%d %H:%M')}\n"
        except:
            pass
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"{CallbackData.CHANNEL_STATS_REFRESH}:{channel_db_id}")],
        [InlineKeyboardButton("📈 نمو القناة", callback_data=f"{CallbackData.CHANNEL_GROWTH}:{channel_db_id}")],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def channel_growth_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    try:
        channel_db_id = int(query.data.split(":")[-1])
    except:
        channel_db_id = context.user_data.get('channel_stats_id')
    if not channel_db_id:
        await safe_edit(query, "⚠️ لم يتم تحديد القناة.")
        return
    channels = await db_get_channels(user_id)
    if not any(ch[0] == channel_db_id for ch in channels):
        await query.answer("❌ هذه القناة ليست لك", show_alert=True)
        return
    growth = await db_get_channel_growth(channel_db_id, days=30)
    ch_info = await db_get_channel_info(channel_db_id)
    channel_name = ch_info[1] if ch_info else "القناة"
    if not growth['dates']:
        text = f"📈 **نمو {channel_name}**\n━━━━━━━━━━━━━━━━━━━━━━\nلا توجد بيانات كافية لعرض النمو."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=f"{CallbackData.CHANNEL_STATS}:{channel_db_id}")]
        ])
        await safe_edit(query, text, reply_markup=keyboard)
        return
    text = f"📈 **نمو {channel_name} (آخر 30 يوم)**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📝 إجمالي المنشورات في الفترة: {growth['total_posts']}\n"
    text += f"👁️ إجمالي المشاهدات: {growth['total_views']}\n"
    text += f"📅 عدد الأيام: {growth['total_days']}\n"
    text += f"📊 متوسط المنشورات يومياً: {growth['total_posts'] / max(1, growth['total_days']):.1f}\n"
    text += f"📊 متوسط المشاهدات يومياً: {growth['total_views'] / max(1, growth['total_days']):.1f}\n"
    text += "\n📅 **التفاصيل اليومية:**\n"
    for i, (date, count, views) in enumerate(zip(growth['dates'], growth['counts'], growth['views'])):
        if i >= 10:
            break
        text += f"• {date}: {count} منشورات، {views} مشاهدة\n"
    if len(growth['dates']) > 10:
        text += f"\n... و {len(growth['dates']) - 10} أيام أخرى"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 العودة للإحصائيات", callback_data=f"{CallbackData.CHANNEL_STATS}:{channel_db_id}")],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def channel_stats_refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await channel_stats_callback(update, context)

async def my_channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    summary = await db_get_channel_stats_summary(user_id)
    if not summary:
        text = "📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n📭 لا توجد قنوات مسجلة."
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة قناة", callback_data=CallbackData.CHANNELS_ADD)],
            [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
        ])
        await safe_edit(query, text, reply_markup=keyboard)
        return
    text = f"📊 **ملخص قنواتي**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📡 عدد القنوات: {summary['total_channels']}\n"
    text += f"✅ القنوات النشطة: {summary['active_channels']}\n"
    text += f"📝 إجمالي المنشورات: {summary['total_posts']}\n"
    text += f"✅ المنشورة: {summary['total_published']}\n"
    text += f"👁️ إجمالي المشاهدات: {summary['total_views']}\n"
    text += f"📊 متوسط المشاهدات لكل قناة: {summary['avg_views_per_channel']}\n"
    if summary['best_channel']:
        text += f"\n🏆 **أفضل قناة:**\n"
        text += f"• {summary['best_channel']['name']}\n"
        text += f"• مشاهدات: {summary['best_channel']['views']}\n"
        text += f"• منشورات: {summary['best_channel']['posts']}\n"
        text += f"• متوسط المشاهدات: {summary['best_channel']['avg_views']}\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 عرض القنوات", callback_data=CallbackData.CHANNELS_MY)],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, text, reply_markup=keyboard)

async def schedule_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    context.user_data['schedule_chat_id'] = chat_id
    context.user_data['state'] = UserState.WAITING_SCHEDULE_POST
    await safe_edit(query, "📝 **أرسل المنشور بالصيغة التالية:**\n`YYYY-MM-DD HH:MM نص المنشور`\n\nمثال: `2024-12-31 20:00 مرحباً بالجميع!`\n🕐 الوقت بتوقيت مكة المكرمة")

async def register_hidden_owner_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    if await db_is_hidden_owner(chat_id, user_id):
        await update.message.reply_text(get_text(user_id, 'hidden_owner_already'))
        return
    await db_register_hidden_owner_group(chat_id, user_id)
    await invalidate_user_cache(user_id=user_id, chat_id=chat_id)
    await update.message.reply_text(get_text(user_id, 'hidden_owner_registered'))

async def add_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/add_hidden_admin user_id`")
        return
    try:
        admin_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح.")
        return
    if admin_id == user_id:
        await update.message.reply_text("❌ لا يمكن إضافة نفسك كمشرف مخفي.")
        return
    if await db_is_hidden_admin(chat_id, admin_id):
        await update.message.reply_text("⚠️ هذا المستخدم مشرف مخفي بالفعل.")
        return
    if await db_add_hidden_admin(chat_id, admin_id, user_id):
        await invalidate_user_cache(user_id=admin_id, chat_id=chat_id)
        await update.message.reply_text(get_text(user_id, 'hidden_admin_added').format(admin_id))
    else:
        await update.message.reply_text("❌ فشل إضافة المشرف المخفي.")

async def remove_hidden_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    args = context.args or []
    if not args:
        await update.message.reply_text("📝 **الاستخدام:**\n`/remove_hidden_admin user_id`")
        return
    try:
        admin_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ معرف مستخدم غير صالح.")
        return
    if not await db_is_hidden_admin(chat_id, admin_id):
        await update.message.reply_text("⚠️ هذا المستخدم ليس مشرفاً مخفياً.")
        return
    if await db_remove_hidden_admin(chat_id, admin_id):
        await invalidate_user_cache(user_id=admin_id, chat_id=chat_id)
        await update.message.reply_text(get_text(user_id, 'hidden_admin_removed').format(admin_id))
    else:
        await update.message.reply_text("❌ فشل إزالة المشرف المخفي.")

async def list_hidden_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text("⚠️ هذا الأمر يعمل فقط في المجموعات!")
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if not await is_telegram_admin(context.bot, chat_id, user_id, update):
        await update.message.reply_text("🔒 هذا الأمر للمشرفين فقط!")
        return
    admins = await db_get_hidden_admins(chat_id)
    if not admins:
        await update.message.reply_text(get_text(user_id, 'no_hidden_admins'))
        return
    text = get_text(user_id, 'hidden_admin_list').format("")
    for admin in admins:
        admin_id = admin['admin_id']
        added_by = admin['added_by']
        added_at = admin['added_at']
        try:
            dt = datetime.fromisoformat(added_at)
            dt_mecca = utc_to_mecca(dt)
            date_str = dt_mecca.strftime("%Y-%m-%d %H:%M")
        except:
            date_str = added_at or "غير معروف"
        text += f"• `{admin_id}` (أضيف بواسطة `{added_by}`)\n   🕐 {date_str}\n"
    await safe_send(context.bot, user_id, text)

async def rules_show_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    rules = await db_get_group_rules(chat_id)
    if not rules:
        rules = DEFAULT_RULES
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"rules_show:{chat_id}")],
        [InlineKeyboardButton(get_text(user_id, 'back'), callback_data=CallbackData.BACK)]
    ])
    await safe_edit(query, rules, reply_markup=keyboard)

async def reset_rules_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    chat_id = int(query.data.split(":")[-1])
    if not await is_authorized_in_group(context.bot, chat_id, user_id):
        await query.answer(get_text(user_id, 'admin_only'), show_alert=True)
        return
    await db_delete_group_rules(chat_id)
    await safe_edit(query, "✅ **تم إعادة تعيين القوانين للافتراضي!**")

async def reset_rules_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await safe_edit(query, "❌ تم إلغاء إعادة التعيين.")

# ===================== معالج الأخطاء =====================
async def global_error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        error = context.error
        error_id = secrets.token_hex(4)
        print(f"❌ [{error_id}] {error}")
        if isinstance(error, (TimedOut, NetworkError)):
            return
        if isinstance(error, Conflict):
            return
        if isinstance(error, Forbidden):
            return
        if update and update.effective_user:
            try:
                await safe_send(context.bot, update.effective_user.id, f"❌ حدث خطأ غير متوقع (الرمز: {error_id})")
            except:
                pass
        if PRIMARY_OWNER_ID:
            try:
                await context.bot.send_message(
                    PRIMARY_OWNER_ID,
                    f"🚨 **خطأ في البوت**\nالرمز: {error_id}\nالخطأ: {str(error)[:200]}"
                )
            except:
                pass
    except Exception as e:
        print(f"❌ فشل معالج الأخطاء نفسه: {e}")

# ===================== معالج الرسائل الرئيسي =====================
async def message_handler_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text or ""
    state = context.user_data.get('state')
    
    # إلغاء
    if text == "/cancel":
        context.user_data.pop('state', None)
        await update.message.reply_text(get_text(user_id, 'cancelled'))
        await main_menu_callback(update, context)
        return
    
    # إضافة منشورات
    if state == UserState.ADDING_POSTS:
        posts = context.user_data.get('session_posts', [])
        target = context.user_data.get('session_target', 15)
        media_type = 'text'
        media_file_id = None
        text_content = text
        if update.message.photo:
            media_type = 'photo'
            media_file_id = update.message.photo[-1].file_id
            text_content = update.message.caption or ""
        elif update.message.video:
            media_type = 'video'
            media_file_id = update.message.video.file_id
            text_content = update.message.caption or ""
        elif update.message.document:
            media_type = 'document'
            media_file_id = update.message.document.file_id
            text_content = update.message.caption or ""
        elif update.message.audio:
            media_type = 'audio'
            media_file_id = update.message.audio.file_id
            text_content = update.message.caption or ""
        elif update.message.voice:
            media_type = 'voice'
            media_file_id = update.message.voice.file_id
            text_content = update.message.caption or ""
        elif update.message.animation:
            media_type = 'animation'
            media_file_id = update.message.animation.file_id
            text_content = update.message.caption or ""
        posts.append((text_content, media_type, media_file_id))
        context.user_data['session_posts'] = posts
        if len(posts) >= target:
            active = context.user_data.get('active_channel') or await db_get_active_channel(user_id)
            if active:
                saved = await db_save_posts(active, posts)
                await update.message.reply_text(f"✅ تم حفظ {saved} منشور")
            context.user_data.pop('state', None)
            context.user_data.pop('session_posts', None)
            await main_menu_callback(update, context)
        else:
            await update.message.reply_text(f"📥 {len(posts)}/{target}")
        return
    
    # انتظار معرف القناة
    if state == UserState.WAITING_CHANNEL_ID:
        channel_id = text.strip()
        if not channel_id.startswith('@') and not channel_id.startswith('-100'):
            await update.message.reply_text("❌ **معرف قناة غير صالح!**\n\nالصيغ المدعومة:\n• `@username`\n• `-1001234567890`")
            return
        new_id = await db_add_channel(user_id, channel_id, channel_id)
        if new_id:
            await db_set_active_channel(user_id, new_id)
            await update.message.reply_text(get_text(user_id, 'channel_added').format(channel_id))
        else:
            await update.message.reply_text(get_text(user_id, 'channel_exists'))
        context.user_data.pop('state', None)
        await main_menu_callback(update, context)
        return
    
    # انتظار المدة
    if state == UserState.WAITING_INTERVAL_MINUTES:
        ch_db_id = context.user_data.get('schedule_ch_id')
        is_admin = context.user_data.get('admin_interval', False)
        is_cron = context.user_data.get('schedule_cron', False)
        if is_cron:
            cron_expr = text.strip()
            if len(cron_expr.split()) >= 5:
                await schedule_cron(ch_db_id, cron_expr)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text(f"✅ **تم حفظ تعبير CRON:** `{cron_expr}`")
                await schedule_menu_callback(update, context)
            else:
                await update.message.reply_text("❌ **تعبير CRON غير صحيح!**\nتأكد من الصيغة: `دقيقة ساعة يوم شهر يوم_أسبوع`")
            context.user_data.pop('state', None)
            return
        try:
            minutes = int(text)
            if minutes < 1:
                minutes = 1
            if is_admin:
                seconds = minutes * 60
                if seconds > 86400:
                    seconds = 86400
                await db_set_publish_interval_seconds(seconds, user_id, is_admin=True)
                await update.message.reply_text(f"✅ **تم ضبط وقت النشر العام بنجاح!**\n\n🕐 الوقت الجديد: {minutes} دقيقة ({seconds} ثانية)")
                await admin_panel_callback(update, context)
            else:
                await db_save_schedule(ch_db_id, 'interval_minutes', interval_minutes=minutes)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text(get_text(user_id, 'interval_set'))
                await schedule_menu_callback(update, context)
        except ValueError:
            await update.message.reply_text(get_text(user_id, 'invalid_number'))
        context.user_data.pop('state', None)
        return
    
    # انتظار الساعات
    if state == UserState.WAITING_INTERVAL_HOURS:
        ch_db_id = context.user_data.get('schedule_ch_id')
        try:
            hours = int(text)
            if hours < 1:
                hours = 1
            await db_save_schedule(ch_db_id, 'interval_hours', interval_hours=hours)
            await db_set_next_publish_date(ch_db_id, None)
            await update.message.reply_text(get_text(user_id, 'interval_set'))
        except:
            await update.message.reply_text(get_text(user_id, 'invalid_number'))
        context.user_data.pop('state', None)
        await schedule_menu_callback(update, context)
        return
    
    # انتظار الأيام
    if state == UserState.WAITING_INTERVAL_DAYS:
        ch_db_id = context.user_data.get('schedule_ch_id')
        try:
            days = int(text)
            if days < 1:
                days = 1
            await db_save_schedule(ch_db_id, 'interval_days', interval_days=days)
            await db_set_next_publish_date(ch_db_id, None)
            await update.message.reply_text(get_text(user_id, 'interval_set'))
        except:
            await update.message.reply_text(get_text(user_id, 'invalid_number'))
        context.user_data.pop('state', None)
        await schedule_menu_callback(update, context)
        return
    
    # انتظار التواريخ
    if state == UserState.WAITING_DATES:
        ch_db_id = context.user_data.get('schedule_ch_id')
        dates = text.split(',')
        valid_dates = []
        for d in dates:
            d = d.strip()
            try:
                datetime.strptime(d, '%Y-%m-%d')
                valid_dates.append(d)
            except:
                await update.message.reply_text(get_text(user_id, 'invalid_date'))
                return
        await db_save_schedule(ch_db_id, 'dates', specific_dates=json.dumps(valid_dates))
        await db_set_next_publish_date(ch_db_id, None)
        await update.message.reply_text(get_text(user_id, 'interval_set'))
        context.user_data.pop('state', None)
        await schedule_menu_callback(update, context)
        return
    
    # انتظار وقت النشر
    if state == UserState.WAITING_PUBLISH_TIME:
        ch_db_id = context.user_data.get('schedule_ch_id')
        try:
            time_str = text.strip()
            hour, minute = map(int, time_str.split(':'))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                await db_set_publish_time(ch_db_id, time_str)
                await db_set_next_publish_date(ch_db_id, None)
                await update.message.reply_text(get_text(user_id, 'interval_set'))
            else:
                await update.message.reply_text(get_text(user_id, 'invalid_time'))
        except:
            await update.message.reply_text(get_text(user_id, 'invalid_time'))
        context.user_data.pop('state', None)
        await schedule_menu_callback(update, context)
        return
    
    # جدولة منشور
    if state == UserState.WAITING_SCHEDULE_POST:
        chat_id = context.user_data.get('schedule_chat_id')
        if not chat_id:
            await update.message.reply_text("❌ لم يتم تحديد المجموعة.")
            return
        args = text.split()
        if len(args) < 3:
            await update.message.reply_text("❌ **صيغة غير صحيحة!**\n\nالاستخدام الصحيح:\n`YYYY-MM-DD HH:MM نص المنشور`")
            return
        try:
            date_str = args[0]
            time_str = args[1]
            post_text = " ".join(args[2:])
            mecca_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            if mecca_dt <= mecca_now():
                await update.message.reply_text("❌ **الوقت يجب أن يكون في المستقبل!**")
                return
            utc_dt = mecca_to_utc(mecca_dt)
            await db_add_scheduled_post(chat_id, post_text, utc_dt)
            await update.message.reply_text(f"✅ **تم جدولة المنشور بنجاح!**\n\n📅 التاريخ: {date_str}\n🕐 الوقت: {time_str} (بتوقيت مكة)")
        except ValueError:
            await update.message.reply_text("❌ **صيغة التاريخ أو الوقت غير صحيحة!**")
        context.user_data.pop('state', None)
        await main_menu_callback(update, context)
        return
    
    # تذكير
    if state == UserState.WAITING_REMINDER_DAYS:
        try:
            days = int(text)
            if 1 <= days <= 10:
                await db_update_reminder_settings(user_id, reminder_days_before=days)
                await update.message.reply_text(f"✅ تم تعيين التذكير قبل {days} يوم من انتهاء الاشتراك")
            else:
                await update.message.reply_text("❌ الرجاء إدخال رقم بين 1 و 10")
        except ValueError:
            await update.message.reply_text("❌ الرجاء إدخال رقم صحيح")
        context.user_data.pop('state', None)
        await reminder_menu_callback(update, context)
        return
    
    # تحديث
    if state == UserState.WAITING_UPDATE_TEXT:
        channel = await db_get_updates_channel()
        if channel:
            try:
                await context.bot.send_message(chat_id=f"@{channel}", text=text)
                await update.message.reply_text("✅ تم نشر التحديث في قناة التحديثات")
            except Exception as e:
                await update.message.reply_text(f"❌ فشل النشر: {str(e)[:100]}\nتأكد من أن البوت مشرف في القناة @{channel}")
        else:
            await update.message.reply_text("❌ لم يتم تعيين قناة تحديثات بعد")
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    # تعيين قناة التحديثات
    if state == UserState.WAITING_UPDATE_CHANNEL:
        channel = text.strip()
        if channel.startswith('@'):
            channel = channel[1:]
        if not channel:
            await update.message.reply_text("❌ **معرف قناة غير صالح!**")
            return
        try:
            if channel.startswith('-'):
                chat_obj = await context.bot.get_chat(int(channel))
            else:
                chat_obj = await context.bot.get_chat(f"@{channel}")
            if chat_obj.type != 'channel':
                await update.message.reply_text("❌ **هذا ليس قناة!**")
                return
            success = await db_set_updates_channel(channel)
            if success:
                await update.message.reply_text(f"✅ **تم تعيين قناة التحديثات بنجاح!**\n📢 القناة: @{channel}")
                try:
                    await context.bot.send_message(
                        chat_id=f"@{channel}",
                        text="✅ **تم تفعيل قناة التحديثات!**"
                    )
                except:
                    pass
            else:
                await update.message.reply_text("❌ **فشل حفظ القناة!**")
        except Exception as e:
            await update.message.reply_text(f"❌ **لا يمكن الوصول إلى القناة:**\n{str(e)[:200]}")
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    # قناة الاشتراك الإجباري
    if state == UserState.WAITING_FORCE_CHANNEL:
        await db_set_force_subscribe_channel(text)
        await update.message.reply_text(f"✅ تم تعيين قناة الاشتراك الإجباري: {text}")
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    # إرسال رسالة جماعية
    if state == UserState.WAITING_BROADCAST:
        context.user_data['broadcast_text'] = text
        confirm_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ نعم، أرسل", callback_data=CallbackData.ADMIN_CONFIRM_BROADCAST),
             InlineKeyboardButton("❌ إلغاء", callback_data=CallbackData.ADMIN_PANEL)]
        ])
        await update.message.reply_text(
            f"📨 **تأكيد الإرسال الجماعي**\n\nالنص المرسل:\n━━━━━━━━━━━━━━\n{text[:500]}\n━━━━━━━━━━━━━━\n\n⚠️ سيتم إرسال هذه الرسالة إلى **جميع مستخدمي البوت**\nهل أنت متأكد؟",
            reply_markup=confirm_kb
        )
        context.user_data.pop('state', None)
        return
    
    # تعيين مستخدم مصرح بـ /sendcode
    if state == UserState.WAITING_SENDCODE_USER:
        try:
            target_user_id = int(text)
        except ValueError:
            await update.message.reply_text(get_text(user_id, 'invalid_number'))
            return
        await db_set_allowed_sendcode_user(target_user_id)
        await update.message.reply_text(get_text(user_id, 'sendcode_user_set').format(target_user_id))
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    # تعيين قناة التقارير
    if state == UserState.WAITING_LOG_CHANNEL:
        identifier = text.strip()
        if not identifier.startswith('@') and not identifier.startswith('-100'):
            await update.message.reply_text("❌ **معرف قناة غير صالح!**")
            return
        try:
            identifier_clean = identifier.lstrip('@')
            if identifier_clean.startswith('-100') or identifier_clean.lstrip('-').isdigit():
                chat_id = int(identifier_clean)
            else:
                chat_obj = await context.bot.get_chat(f"@{identifier_clean}")
                chat_id = chat_obj.id
            bot_member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if bot_member.status not in ['administrator', 'creator']:
                await update.message.reply_text("❌ **البوت ليس مشرفاً في هذه القناة.**")
                return
            if not bot_member.can_post_messages:
                await update.message.reply_text("❌ **البوت لا يملك صلاحية الإرسال.**")
                return
            await db_set_log_channel_id(str(chat_id))
            await update.message.reply_text(f"✅ **تم تعيين قناة التقارير بنجاح!**\nمعرف القناة: `{chat_id}`")
            try:
                await context.bot.send_message(chat_id, "✅ **تم تفعيل نظام التقارير**")
            except:
                pass
        except Exception as e:
            await update.message.reply_text(f"❌ **لا يمكن الوصول إلى القناة:**\n{str(e)[:200]}")
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    # إضافة رد
    if state == UserState.WAITING_KEYWORD:
        keyword = text.strip().lower()
        if len(keyword) < 2:
            await update.message.reply_text("❌ الكلمة المفتاحية قصيرة جداً")
            return
        context.user_data['state'] = UserState.WAITING_REPLY
        context.user_data['admin_keyword'] = keyword
        await update.message.reply_text(f"📝 **إضافة رد للكلمة:** `{keyword}`\n\nأرسل الرد الذي تريده لهذه الكلمة:")
        return
    
    # إرسال الرد
    if state == UserState.WAITING_REPLY:
        if context.user_data.get('admin_del_reply'):
            kw = text.lower()
            if await db_del_reply(kw):
                await update.message.reply_text(f"✅ تم حذف رد {kw}")
            else:
                await update.message.reply_text(f"⚠️ الكلمة {kw} غير موجودة")
            context.user_data.pop('admin_del_reply', None)
            await admin_replies_callback(update, context)
            return
        kw = context.user_data.pop('admin_keyword', '')
        reply = text.strip()
        if kw and reply:
            await db_add_reply(kw, reply)
            await update.message.reply_text(f"✅ تم إضافة رد للكلمة {kw}")
        else:
            await update.message.reply_text("❌ حدث خطأ")
        context.user_data.pop('state', None)
        await admin_replies_callback(update, context)
        return
    
    # إضافة مشرف
    if state == UserState.WAITING_ADMIN_ID_ADD:
        try:
            target_id = int(text)
            if target_id == PRIMARY_OWNER_ID:
                await update.message.reply_text(get_text(user_id, 'cannot_remove_main_admin'))
            else:
                await add_bot_admin(target_id)
                await update.message.reply_text(get_text(user_id, 'add_admin_success').format(target_id))
        except ValueError:
            await update.message.reply_text(get_text(user_id, 'invalid_user_id'))
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    # إزالة مشرف
    if state == UserState.WAITING_ADMIN_ID_REMOVE:
        try:
            target_id = int(text)
            if target_id == PRIMARY_OWNER_ID:
                await update.message.reply_text(get_text(user_id, 'cannot_remove_main_admin'))
            else:
                await remove_bot_admin(target_id)
                await update.message.reply_text(get_text(user_id, 'remove_admin_success').format(target_id))
        except ValueError:
            await update.message.reply_text(get_text(user_id, 'invalid_user_id'))
        context.user_data.pop('state', None)
        await admin_panel_callback(update, context)
        return
    
    # كلمة محظورة للمجموعة
    if state == UserState.WAITING_GROUP_BANNED_WORD:
        chat_id = context.user_data.get('banned_words_chat_id')
        if chat_id:
            word = text.split()[0].lower() if text else ""
            if len(word) < 2:
                await update.message.reply_text("❌ الكلمة قصيرة جداً")
                return
            if await db_add_banned_word(word, chat_id, user_id):
                await update.message.reply_text(f"✅ تم إضافة {word}")
            else:
                await update.message.reply_text(f"⚠️ {word} موجودة مسبقاً")
            context.user_data.pop('state', None)
            await banned_words_list_callback(update, context)
        return
    
    # حذف كلمة محظورة من المجموعة
    if state == UserState.WAITING_REMOVE_GROUP_BANNED_WORD:
        chat_id = context.user_data.get('banned_words_chat_id')
        if chat_id:
            word = text.lower()
            if await db_remove_banned_word(word, chat_id):
                await update.message.reply_text(f"✅ تم حذف {word}")
            else:
                await update.message.reply_text(f"⚠️ الكلمة {word} غير موجودة")
            context.user_data.pop('state', None)
            await banned_words_list_callback(update, context)
        return
    
    # كلمة محظورة عامة
    if state == UserState.WAITING_GLOBAL_BANNED_WORD:
        word = text.split()[0].lower() if text else ""
        if len(word) < 2:
            await update.message.reply_text("❌ الكلمة قصيرة جداً")
            return
        if await db_add_banned_word(word, -1, user_id):
            await update.message.reply_text(f"✅ تم إضافة {word} ككلمة محظورة عامة")
        else:
            await update.message.reply_text(f"⚠️ {word} موجودة مسبقاً")
        context.user_data.pop('state', None)
        await admin_banned_words_callback(update, context)
        return
    
    # حذف كلمة محظورة عامة
    if state == UserState.WAITING_REMOVE_GLOBAL_BANNED_WORD:
        word = text.lower()
        async def _remove(conn):
            await conn.execute("DELETE FROM banned_words WHERE word=? AND chat_id=?", (word, -1))
            await conn.commit()
        await execute_db(_remove)
        await update.message.reply_text(f"✅ تم حذف {word} من الكلمات المحظورة العامة")
        context.user_data.pop('state', None)
        await admin_banned_words_callback(update, context)
        return
    
    # NSFW
    if state == UserState.WAITING_NSFW_THRESHOLD:
        try:
            threshold = float(text)
            if 0 < threshold <= 100:
                global NSFW_THRESHOLD
                NSFW_THRESHOLD = threshold / 100
                os.environ["NSFW_THRESHOLD"] = str(NSFW_THRESHOLD)
                await update.message.reply_text(f"✅ تم تغيير نسبة الحساسية إلى: {threshold}%")
            else:
                await update.message.reply_text("❌ الرجاء إدخال رقم بين 1 و 100")
        except ValueError:
            await update.message.reply_text("❌ الرجاء إدخال رقم صحيح (مثال: 75)")
        context.user_data.pop('state', None)
        await nsfw_settings_callback(update, context)
        return
    
    # إجراءات متقدمة
    if state == UserState.WAITING_BAN_USER:
        parts = text.split(maxsplit=1)
        reason = parts[1] if len(parts) > 1 else ""
        try:
            target_id = int(parts[0])
            success, msg = await execute_ban(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
            await safe_send(context.bot, chat_id, msg)
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        return
    
    if state == UserState.WAITING_MUTE_USER:
        parts = text.split(maxsplit=1)
        reason = parts[1] if len(parts) > 1 else ""
        try:
            target_id = int(parts[0])
            minutes = context.user_data.get('mute_minutes', 60)
            success, msg = await execute_mute(context.bot, chat_id, target_id, minutes, reason=reason, moderator_id=user_id)
            await safe_send(context.bot, chat_id, msg)
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        return
    
    if state == UserState.WAITING_WARN_USER:
        parts = text.split(maxsplit=1)
        reason = parts[1] if len(parts) > 1 else ""
        try:
            target_id = int(parts[0])
            success, msg = await execute_warn(context.bot, chat_id, target_id, user_id, reason=reason)
            await safe_send(context.bot, chat_id, msg)
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        return
    
    if state == UserState.WAITING_KICK_USER:
        parts = text.split(maxsplit=1)
        reason = parts[1] if len(parts) > 1 else ""
        try:
            target_id = int(parts[0])
            success, msg = await execute_kick(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
            await safe_send(context.bot, chat_id, msg)
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        return
    
    if state == UserState.WAITING_RESTRICT_USER:
        parts = text.split(maxsplit=1)
        reason = parts[1] if len(parts) > 1 else ""
        try:
            target_id = int(parts[0])
            success, msg = await execute_restrict(context.bot, chat_id, target_id, reason=reason, moderator_id=user_id)
            await safe_send(context.bot, chat_id, msg)
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        return
    
    if state == UserState.WAITING_UNBAN_USER:
        try:
            target_id = int(text)
            success, msg = await execute_unban(context.bot, chat_id, target_id, moderator_id=user_id)
            await safe_send(context.bot, chat_id, msg)
        except ValueError:
            await update.message.reply_text("❌ معرف مستخدم غير صالح")
        context.user_data.pop('state', None)
        return
    
    if state == UserState.WAITING_PIN_MESSAGE:
        if update.message.reply_to_message:
            success, msg = await execute_pin(context.bot, chat_id, update.message.reply_to_message.message_id)
            await safe_send(context.bot, chat_id, msg)
        else:
            await update.message.reply_text("❌ يرجى الرد على الرسالة التي تريد تثبيتها")
        context.user_data.pop('state', None)
        return
    
    # مسابقات
    await handle_contest_creation_states(update, context, state)
    
    # دعم
    if context.user_data.get('support_mode') and update.effective_chat.type == 'private':
        ticket_num = await db_get_next_ticket_number()
        username = update.effective_user.first_name or str(user_id)
        clean_text = sanitize_text(text, max_length=2000)
        await db_save_ticket(user_id, username, clean_text, ticket_num)
        now_mecca = mecca_now()
        now_str = now_mecca.strftime("%Y-%m-%d %H:%M:%S")
        reply_text = f"✅ **تم استلام رسالتك!**\n📋 رقم التذكرة: #{ticket_num}\n🕐 {now_str}\n\nسيتم الرد عليك في أقرب وقت ممكن."
        await update.message.reply_text(reply_text)
        notification_text = f"📬 **تذكرة دعم جديدة**\n━━━━━━━━━━━━━━━━━━━━━━\n👤 المستخدم: {username}\n🆔 المعرف: `{user_id}`\n📋 رقم التذكرة: #{ticket_num}\n🕐 الوقت: {now_str}\n━━━━━━━━━━━━━━━━━━━━━━\n📝 **الرسالة:**\n{clean_text[:500]}\n━━━━━━━━━━━━━━━━━━━━━━\nللرد استخدم:\n`/support_reply {user_id} نص الرد`"
        await context.bot.send_message(chat_id=PRIMARY_OWNER_ID, text=notification_text)
        context.user_data['support_mode'] = False
        return
    
    # الردود التلقائية
    if REPLIES_LOADED and text in ALL_REPLIES:
        await update.message.reply_text(ALL_REPLIES[text])

# ===================== فلتر الرسائل للمجموعات =====================
async def filter_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message or not update.effective_chat or not update.effective_user:
        return
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id
    user_id = user.id
    if chat.type not in ['group', 'supergroup']:
        return
    if user.is_bot:
        return
    if await is_chat_locked(chat_id):
        try:
            await update.message.delete()
            await safe_send(context.bot, chat_id, "🔒 المجموعة مقفلة من قبل المشرف")
        except:
            pass
        return
    bot_perms = await check_bot_admin_permissions(context.bot, chat_id)
    if not bot_perms['can_act']:
        return
    if not await db_check_slow_mode(chat_id, user_id):
        try:
            await update.message.delete()
            await safe_send(context.bot, chat_id, f"⏱️ **وضع بطيء مفعل**\n@{user.username or str(user_id)} يرجى الانتظار")
        except:
            pass
        return
    security_settings = await db_get_security_settings(chat_id)
    text = update.message.text or update.message.caption or ""
    if security_settings.get('delete_banned_words'):
        banned_word = await db_contains_banned_word(text, chat_id)
        if banned_word:
            try:
                await update.message.delete()
                await safe_send(context.bot, chat_id, f"🚫 **كلمة محظورة**\n@{user.username or str(user_id)} الكلمة `{banned_word}` غير مسموح بها")
            except:
                pass
            await apply_penalty(context.bot, chat_id, user_id, security_settings)
            return
    if security_settings.get('links') and contains_link(text):
        try:
            await update.message.delete()
            await safe_send(context.bot, chat_id, f"🔗 **الروابط غير مسموح بها**\n@{user.username or str(user_id)}")
        except:
            pass
        await apply_penalty(context.bot, chat_id, user_id, security_settings)
        return
    if security_settings.get('mentions') and contains_mention(text):
        try:
            await update.message.delete()
            await safe_send(context.bot, chat_id, f"@ **المعرفات غير مسموح بها**\n@{user.username or str(user_id)}")
        except:
            pass
        await apply_penalty(context.bot, chat_id, user_id, security_settings)
        return
    if REPLIES_LOADED and text in ALL_REPLIES:
        await update.message.reply_text(ALL_REPLIES[text])

# ===================== دوال إضافية =====================
async def pre_checkout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("sub_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="بيانات غير صالحة")

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    try:
        parts = payment.invoice_payload.split('_')
        days = int(parts[1]) if len(parts) >= 2 else 30
    except:
        days = 30
    await db_activate_subscription(user_id, days)
    await update.message.reply_text(f"✅ **تم تفعيل اشتراكك لمدة {days} يوماً!**\nشكراً لدعمك ❤️")

async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update or not update.message or not update.message.new_chat_members:
        return
    bot_id = context.bot.id
    chat = update.effective_chat
    inviter = update.effective_user
    if chat.type not in ['group', 'supergroup']:
        return
    for member in update.message.new_chat_members:
        if member.id == bot_id:
            added_by_id = inviter.id if inviter else 0
            chat_name = chat.title or "بدون اسم"
            await db_register_group(chat.id, chat_name, added_by_id, chat.username)
            await db_register_hidden_owner_group(chat.id, added_by_id)
            await invalidate_user_cache(user_id=added_by_id, chat_id=chat.id)
            try:
                await safe_send(context.bot, chat.id, "✅ **تم تفعيل البوت في المجموعة**\n\n📌 استخدم /panel للوحة التحكم")
            except:
                pass
            break

async def track_chat_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if not result:
        return
    new_status = result.new_chat_member.status
    old_status = result.old_chat_member.status
    if new_status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
        is_new = old_status in [ChatMember.LEFT, ChatMember.BANNED, ChatMember.RESTRICTED]
        if is_new:
            chat = result.chat
            adder = result.from_user
            if chat.type in ['group', 'supergroup']:
                await db_register_group(chat.id, chat.title or "بدون اسم", adder.id, chat.username)
                await db_register_hidden_owner_group(chat.id, adder.id)
                await invalidate_user_cache(user_id=adder.id, chat_id=chat.id)

async def track_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result or result.chat.type not in ['group', 'supergroup']:
        return
    settings = await db_get_security_settings(result.chat.id)
    if result.new_chat_member.status == 'member' and result.old_chat_member.status in ['left', 'kicked']:
        if settings.get('welcome_enabled'):
            user = result.new_chat_member.user
            msg = settings.get('welcome_text', "مرحباً {user} في {chat} 🤍")
            msg = msg.replace('{user}', user.full_name or user.first_name).replace('{chat}', result.chat.title)
            try:
                await safe_send(context.bot, result.chat.id, msg)
            except:
                pass
    elif result.old_chat_member.status == 'member' and result.new_chat_member.status in ['left', 'kicked']:
        if settings.get('goodbye_enabled'):
            user = result.old_chat_member.user
            msg = settings.get('goodbye_text', "وداعاً {user} 👋")
            msg = msg.replace('{user}', user.full_name or user.first_name).replace('{chat}', result.chat.title)
            try:
                await safe_send(context.bot, result.chat.id, msg)
            except:
                pass

# ===================== دوال الجدولة في الخلفية =====================
async def auto_publish_loop(bot):
    await asyncio.sleep(5)
    while True:
        try:
            now_iso = utc_now().isoformat()
            async def _get_due_channels(conn):
                cur = await conn.execute("""
                    SELECT uc.id, uc.channel_id, u.user_id
                    FROM user_channels uc
                    JOIN users u ON uc.user_id = u.user_id
                    LEFT JOIN schedule s ON uc.id = s.channel_db_id
                    WHERE u.auto_publish = 1
                      AND u.banned = 0
                      AND uc.banned = 0
                      AND (s.next_publish_date IS NULL OR s.next_publish_date <= ?)
                    ORDER BY COALESCE(s.next_publish_date, '1970-01-01') ASC
                    LIMIT 20
                """, (now_iso,))
                return await cur.fetchall()
            rows = await execute_db(_get_due_channels)
            for row in rows:
                ch_db_id, ch_tele_id, user_id = row
                if not await db_has_active_subscription(user_id) and not await db_has_used_trial(user_id):
                    continue
                if not await check_bot_permissions(bot, ch_tele_id):
                    continue
                post = await db_get_next_post(ch_db_id)
                if not post:
                    continue
                ch_info = await db_get_channel_info(ch_db_id)
                try:
                    if post['media_type'] == 'photo' and post['media_file_id']:
                        await bot.send_photo(ch_info[0], post['media_file_id'], caption=post['text'] if post['text'] else None)
                    elif post['media_type'] == 'video' and post['media_file_id']:
                        await bot.send_video(ch_info[0], post['media_file_id'], caption=post['text'] if post['text'] else None)
                    else:
                        await bot.send_message(ch_info[0], post['text'])
                    await db_mark_published(post['id'])
                    await db_set_last_publish(ch_db_id, utc_now())
                    await db_update_next_publish_date(ch_db_id)
                except Exception as e:
                    print(f"⚠️ فشل النشر في {ch_tele_id}: {e}")
                await asyncio.sleep(1)
            await asyncio.sleep(60)
        except Exception as e:
            print(f"⚠️ خطأ في الناشر التلقائي: {e}")
            await asyncio.sleep(60)

async def check_bot_permissions(bot, channel_id: str) -> bool:
    try:
        me = await bot.get_chat_member(channel_id, bot.id)
        return me.status in ['administrator', 'creator'] and me.can_post_messages
    except:
        return False

# ===================== الوظيفة الرئيسية =====================
async def main():
    await init_db()
    if USE_PROXY:
        request = HTTPXRequest(proxy_url=PROXY_URL)
        app = Application.builder().token(TOKEN).request(request).build()
    else:
        app = Application.builder().token(TOKEN).build()
    app.add_error_handler(global_error_handler)
    
    # الأوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("rules", rules_command))
    app.add_handler(CommandHandler("set_rules", set_rules_command))
    app.add_handler(CommandHandler("reset_rules", reset_rules_command))
    app.add_handler(CommandHandler("syncgroup", syncgroup_command))
    app.add_handler(CommandHandler("security", security_command))
    app.add_handler(CommandHandler("trial", trial_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CommandHandler("developer", developer_command))
    app.add_handler(CommandHandler("updates", updates_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("support", support_command))
    app.add_handler(CommandHandler("panel", panel_command))
    app.add_handler(CommandHandler("schedule", schedule_post_command))
    app.add_handler(CommandHandler("lock", lock_command))
    app.add_handler(CommandHandler("unlock", unlock_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("contests", contests_command_handler))
    app.add_handler(CommandHandler("create_contest", create_contest_command))
    app.add_handler(CommandHandler("declare_winner", declare_winner_command))
    app.add_handler(CommandHandler("update_admins", update_admins_command))
    app.add_handler(CommandHandler("register_hidden_owner", register_hidden_owner_handler))
    app.add_handler(CommandHandler("add_hidden_admin", add_hidden_admin_command))
    app.add_handler(CommandHandler("remove_hidden_admin", remove_hidden_admin_command))
    app.add_handler(CommandHandler("list_hidden_admins", list_hidden_admins_command))
    
    # كولباك
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern=f"^{CallbackData.MAIN_MENU}$"))
    app.add_handler(CallbackQueryHandler(back_callback, pattern=f"^{CallbackData.BACK}$"))
    app.add_handler(CallbackQueryHandler(cancel_session_callback, pattern=f"^{CallbackData.CANCEL_SESSION}$"))
    app.add_handler(CallbackQueryHandler(add_channel_callback, pattern=f"^{CallbackData.CHANNELS_ADD}$"))
    app.add_handler(CallbackQueryHandler(my_channels_callback, pattern=f"^{CallbackData.CHANNELS_MY}$"))
    app.add_handler(CallbackQueryHandler(delete_channel_callback, pattern=f"^{CallbackData.CHANNELS_DELETE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(select_channel_callback, pattern=f"^{CallbackData.CHANNELS_SELECT_PREFIX}"))
    app.add_handler(CallbackQueryHandler(add_15_posts_callback, pattern=f"^{CallbackData.POSTS_ADD_15}$"))
    app.add_handler(CallbackQueryHandler(publish_one_callback, pattern=f"^{CallbackData.POSTS_PUBLISH_ONE}$"))
    app.add_handler(CallbackQueryHandler(my_posts_callback, pattern=f"^{CallbackData.POSTS_MY}$"))
    app.add_handler(CallbackQueryHandler(delete_single_post_callback, pattern=f"^{CallbackData.POSTS_DELETE_SINGLE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(confirm_clear_all_posts_callback, pattern=f"^{CallbackData.POSTS_CONFIRM_CLEAR_ALL_PREFIX}"))
    app.add_handler(CallbackQueryHandler(clear_all_posts_callback, pattern=f"^{CallbackData.POSTS_CLEAR_ALL_PREFIX}"))
    app.add_handler(CallbackQueryHandler(recycle_posts_callback, pattern=f"^{CallbackData.POSTS_RECYCLE}$"))
    app.add_handler(CallbackQueryHandler(my_pending_stats_callback, pattern=f"^{CallbackData.STATS_PENDING}$"))
    app.add_handler(CallbackQueryHandler(my_full_stats_callback, pattern=f"^{CallbackData.STATS_FULL}$"))
    app.add_handler(CallbackQueryHandler(my_groups_callback, pattern=f"^{CallbackData.GROUPS_MY}$"))
    app.add_handler(CallbackQueryHandler(delete_group_callback, pattern="^delete_group:"))
    app.add_handler(CallbackQueryHandler(group_settings_callback, pattern=f"^{CallbackData.GROUPS_SETTINGS_PREFIX}"))
    app.add_handler(CallbackQueryHandler(settings_menu_callback, pattern=f"^{CallbackData.SETTINGS_MENU}$"))
    app.add_handler(CallbackQueryHandler(toggle_auto_publish_callback, pattern=f"^{CallbackData.SETTINGS_TOGGLE_AUTO_PUBLISH}$"))
    app.add_handler(CallbackQueryHandler(toggle_auto_recycle_callback, pattern=f"^{CallbackData.SETTINGS_TOGGLE_AUTO_RECYCLE}$"))
    app.add_handler(CallbackQueryHandler(schedule_menu_callback, pattern=f"^{CallbackData.SCHEDULE_MENU_PREFIX}"))
    app.add_handler(CallbackQueryHandler(set_interval_minutes_callback, pattern=f"^{CallbackData.SCHEDULE_SET_INTERVAL_MINUTES_PREFIX}"))
    app.add_handler(CallbackQueryHandler(set_interval_hours_callback, pattern=f"^{CallbackData.SCHEDULE_SET_INTERVAL_HOURS_PREFIX}"))
    app.add_handler(CallbackQueryHandler(set_interval_days_callback, pattern=f"^{CallbackData.SCHEDULE_SET_INTERVAL_DAYS_PREFIX}"))
    app.add_handler(CallbackQueryHandler(set_cron_callback, pattern="^schedule:set_cron:"))
    app.add_handler(CallbackQueryHandler(set_days_callback, pattern=f"^{CallbackData.SCHEDULE_SET_DAYS_PREFIX}"))
    app.add_handler(CallbackQueryHandler(day_select_callback, pattern=f"^{CallbackData.SCHEDULE_DAY_SELECT_PREFIX}"))
    app.add_handler(CallbackQueryHandler(save_days_callback, pattern=f"^{CallbackData.SCHEDULE_SAVE_DAYS}$"))
    app.add_handler(CallbackQueryHandler(set_dates_callback, pattern=f"^{CallbackData.SCHEDULE_SET_DATES_PREFIX}"))
    app.add_handler(CallbackQueryHandler(set_publish_time_callback, pattern=f"^{CallbackData.SCHEDULE_SET_PUBLISH_TIME_PREFIX}"))
    app.add_handler(CallbackQueryHandler(schedule_select_callback, pattern="^schedule_select:"))
    app.add_handler(CallbackQueryHandler(help_callback, pattern=f"^{CallbackData.HELP}$"))
    app.add_handler(CallbackQueryHandler(support_menu_callback, pattern=f"^{CallbackData.SUPPORT_MENU}$"))
    app.add_handler(CallbackQueryHandler(support_help_callback, pattern=f"^{CallbackData.SUPPORT_HELP}$"))
    app.add_handler(CallbackQueryHandler(support_ticket_callback, pattern=f"^{CallbackData.SUPPORT_TICKET}$"))
    app.add_handler(CallbackQueryHandler(support_back_callback, pattern=f"^{CallbackData.SUPPORT_BACK}$"))
    app.add_handler(CallbackQueryHandler(trial_callback, pattern=f"^{CallbackData.TRIAL}$"))
    app.add_handler(CallbackQueryHandler(subscribe_menu_callback, pattern=f"^{CallbackData.SUBSCRIBE_MENU}$"))
    app.add_handler(CallbackQueryHandler(buy_subscription_1_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_1}$"))
    app.add_handler(CallbackQueryHandler(buy_subscription_2_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_2}$"))
    app.add_handler(CallbackQueryHandler(buy_subscription_30_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_30}$"))
    app.add_handler(CallbackQueryHandler(buy_subscription_90_callback, pattern=f"^{CallbackData.BUY_SUBSCRIPTION_90}$"))
    app.add_handler(CallbackQueryHandler(developer_callback, pattern=f"^{CallbackData.DEVELOPER}$"))
    app.add_handler(CallbackQueryHandler(updates_callback, pattern=f"^{CallbackData.UPDATES}$"))
    app.add_handler(CallbackQueryHandler(referral_menu_callback, pattern=f"^{CallbackData.REFERRAL_MENU}$"))
    app.add_handler(CallbackQueryHandler(referral_copy_link_callback, pattern=f"^{CallbackData.REFERRAL_COPY_LINK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(referral_claim_reward_callback, pattern=f"^{CallbackData.REFERRAL_CLAIM_REWARD}$"))
    app.add_handler(CallbackQueryHandler(referral_list_callback, pattern=f"^{CallbackData.REFERRAL_LIST}$"))
    app.add_handler(CallbackQueryHandler(reminder_menu_callback, pattern=f"^{CallbackData.REMINDER_MENU}$"))
    app.add_handler(CallbackQueryHandler(reminder_toggle_sub_callback, pattern=f"^{CallbackData.REMINDER_TOGGLE_SUB}$"))
    app.add_handler(CallbackQueryHandler(reminder_toggle_daily_callback, pattern=f"^{CallbackData.REMINDER_TOGGLE_DAILY}$"))
    app.add_handler(CallbackQueryHandler(reminder_toggle_weekly_callback, pattern=f"^{CallbackData.REMINDER_TOGGLE_WEEKLY}$"))
    app.add_handler(CallbackQueryHandler(reminder_set_days_callback, pattern=f"^{CallbackData.REMINDER_SET_DAYS}$"))
    app.add_handler(CallbackQueryHandler(reminder_set_lang_callback, pattern=f"^{CallbackData.REMINDER_SET_LANG}$"))
    app.add_handler(CallbackQueryHandler(reminder_lang_callback, pattern=f"^{CallbackData.REMINDER_LANG_PREFIX}"))
    app.add_handler(CallbackQueryHandler(translation_menu_callback, pattern=f"^{CallbackData.TRANSLATION_MENU}$"))
    app.add_handler(CallbackQueryHandler(translation_off_callback, pattern=f"^{CallbackData.TRANSLATION_OFF}$"))
    app.add_handler(CallbackQueryHandler(translation_set_callback, pattern=f"^{CallbackData.TRANSLATION_SET_PREFIX}"))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=f"^{CallbackData.ADMIN_PANEL}$"))
    app.add_handler(CallbackQueryHandler(admin_users_callback, pattern=f"^{CallbackData.ADMIN_USERS}$"))
    app.add_handler(CallbackQueryHandler(admin_banned_users_callback, pattern=f"^{CallbackData.ADMIN_BANNED_USERS}$"))
    app.add_handler(CallbackQueryHandler(admin_unban_all_users_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_USERS}$"))
    app.add_handler(CallbackQueryHandler(admin_all_channels_callback, pattern=f"^{CallbackData.ADMIN_ALL_CHANNELS}$"))
    app.add_handler(CallbackQueryHandler(admin_banned_channels_callback, pattern=f"^{CallbackData.ADMIN_BANNED_CHANNELS}$"))
    app.add_handler(CallbackQueryHandler(admin_activate_all_channels_callback, pattern=f"^{CallbackData.ADMIN_ACTIVATE_ALL_CHANNELS}$"))
    app.add_handler(CallbackQueryHandler(admin_groups_callback, pattern=f"^{CallbackData.ADMIN_GROUPS}$"))
    app.add_handler(CallbackQueryHandler(admin_banned_groups_callback, pattern=f"^{CallbackData.ADMIN_BANNED_GROUPS}$"))
    app.add_handler(CallbackQueryHandler(admin_unban_all_groups_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_GROUPS}$"))
    app.add_handler(CallbackQueryHandler(admin_bot_channels_callback, pattern=f"^{CallbackData.ADMIN_BOT_CHANNELS}$"))
    app.add_handler(CallbackQueryHandler(admin_banned_bot_channels_callback, pattern=f"^{CallbackData.ADMIN_BANNED_BOT_CHANNELS}$"))
    app.add_handler(CallbackQueryHandler(admin_unban_all_bot_channels_callback, pattern=f"^{CallbackData.ADMIN_UNBAN_ALL_BOT_CHANNELS}$"))
    app.add_handler(CallbackQueryHandler(admin_monitor_users_callback, pattern=f"^{CallbackData.ADMIN_MONITOR_USERS}$"))
    app.add_handler(CallbackQueryHandler(admin_add_admin_callback, pattern=f"^{CallbackData.ADMIN_ADD_ADMIN}$"))
    app.add_handler(CallbackQueryHandler(admin_remove_admin_callback, pattern=f"^{CallbackData.ADMIN_REMOVE_ADMIN}$"))
    app.add_handler(CallbackQueryHandler(admin_ram_callback, pattern=f"^{CallbackData.ADMIN_RAM}$"))
    app.add_handler(CallbackQueryHandler(admin_stats_callback, pattern=f"^{CallbackData.ADMIN_STATS}$"))
    app.add_handler(CallbackQueryHandler(admin_metrics_callback, pattern=f"^{CallbackData.ADMIN_METRICS}$"))
    app.add_handler(CallbackQueryHandler(admin_backup_callback, pattern=f"^{CallbackData.ADMIN_BACKUP}$"))
    app.add_handler(CallbackQueryHandler(admin_restore_backup_callback, pattern=f"^{CallbackData.ADMIN_RESTORE_BACKUP}$"))
    app.add_handler(CallbackQueryHandler(admin_restore_backup_select_callback, pattern=f"^{CallbackData.ADMIN_RESTORE_BACKUP_SELECT_PREFIX}"))
    app.add_handler(CallbackQueryHandler(admin_backup_settings_callback, pattern=f"^{CallbackData.ADMIN_BACKUP_SETTINGS}$"))
    app.add_handler(CallbackQueryHandler(admin_toggle_auto_backup_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_AUTO_BACKUP}$"))
    app.add_handler(CallbackQueryHandler(admin_change_interval_callback, pattern=f"^{CallbackData.ADMIN_CHANGE_INTERVAL}$"))
    app.add_handler(CallbackQueryHandler(admin_send_update_callback, pattern=f"^{CallbackData.ADMIN_SEND_UPDATE}$"))
    app.add_handler(CallbackQueryHandler(admin_set_update_channel_callback, pattern=f"^{CallbackData.ADMIN_SET_UPDATE_CHANNEL}$"))
    app.add_handler(CallbackQueryHandler(admin_show_update_channel_callback, pattern=f"^{CallbackData.ADMIN_SHOW_UPDATE_CHANNEL}$"))
    app.add_handler(CallbackQueryHandler(admin_updates_callback, pattern=f"^{CallbackData.ADMIN_UPDATES}$"))
    app.add_handler(CallbackQueryHandler(admin_force_subscribe_callback, pattern=f"^{CallbackData.ADMIN_FORCE_SUBSCRIBE}$"))
    app.add_handler(CallbackQueryHandler(admin_set_force_channel_callback, pattern=f"^{CallbackData.ADMIN_SET_FORCE_CHANNEL}$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_callback, pattern=f"^{CallbackData.ADMIN_BROADCAST}$"))
    app.add_handler(CallbackQueryHandler(admin_confirm_broadcast_callback, pattern=f"^{CallbackData.ADMIN_CONFIRM_BROADCAST}$"))
    app.add_handler(CallbackQueryHandler(admin_support_tickets_callback, pattern=f"^{CallbackData.ADMIN_SUPPORT_TICKETS}$"))
    app.add_handler(CallbackQueryHandler(admin_delete_all_tickets_callback, pattern=f"^{CallbackData.ADMIN_DELETE_ALL_TICKETS}$"))
    app.add_handler(CallbackQueryHandler(admin_confirm_delete_tickets_callback, pattern=f"^{CallbackData.ADMIN_CONFIRM_DELETE_TICKETS}$"))
    app.add_handler(CallbackQueryHandler(admin_manage_sendcode_callback, pattern=f"^{CallbackData.ADMIN_MANAGE_SENDCODE}$"))
    app.add_handler(CallbackQueryHandler(admin_set_sendcode_user_callback, pattern=f"^{CallbackData.ADMIN_SET_SENDCODE_USER}$"))
    app.add_handler(CallbackQueryHandler(admin_show_log_channel_callback, pattern=f"^{CallbackData.ADMIN_SHOW_LOG_CHANNEL}$"))
    app.add_handler(CallbackQueryHandler(admin_set_log_channel_callback, pattern=f"^{CallbackData.ADMIN_SET_LOG_CHANNEL}$"))
    app.add_handler(CallbackQueryHandler(admin_replies_callback, pattern=f"^{CallbackData.ADMIN_REPLIES}$"))
    app.add_handler(CallbackQueryHandler(admin_add_reply_callback, pattern=f"^{CallbackData.ADMIN_ADD_REPLY}$"))
    app.add_handler(CallbackQueryHandler(admin_list_replies_callback, pattern=f"^{CallbackData.ADMIN_LIST_REPLIES}$"))
    app.add_handler(CallbackQueryHandler(admin_del_reply_callback, pattern=f"^{CallbackData.ADMIN_DEL_REPLY}$"))
    app.add_handler(CallbackQueryHandler(admin_del_reply_callback, pattern="^admin_del_reply_"))
    app.add_handler(CallbackQueryHandler(admin_banned_words_callback, pattern=f"^{CallbackData.ADMIN_BANNED_WORDS}$"))
    app.add_handler(CallbackQueryHandler(admin_add_banned_word_callback, pattern=f"^{CallbackData.ADMIN_ADD_BANNED_WORD}$"))
    app.add_handler(CallbackQueryHandler(admin_list_banned_words_callback, pattern=f"^{CallbackData.ADMIN_LIST_BANNED_WORDS}$"))
    app.add_handler(CallbackQueryHandler(admin_remove_banned_word_callback, pattern=f"^{CallbackData.ADMIN_REMOVE_BANNED_WORD}$"))
    app.add_handler(CallbackQueryHandler(admin_del_banned_word_callback, pattern="^admin_del_banned_word_"))
    app.add_handler(CallbackQueryHandler(admin_toggle_channel_ban_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_CHANNEL_BAN_PREFIX}"))
    app.add_handler(CallbackQueryHandler(admin_toggle_group_ban_callback, pattern=f"^{CallbackData.ADMIN_TOGGLE_GROUP_BAN_PREFIX}"))
    app.add_handler(CallbackQueryHandler(auto_reply_toggle_callback, pattern=f"^{CallbackData.AUTO_REPLY_TOGGLE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(auto_reply_admins_callback, pattern=f"^{CallbackData.AUTO_REPLY_ADMINS_PREFIX}"))
    app.add_handler(CallbackQueryHandler(auto_reply_reset_callback, pattern=f"^{CallbackData.AUTO_REPLY_RESET_PREFIX}"))
    app.add_handler(CallbackQueryHandler(auto_reply_confirm_reset_callback, pattern=f"^{CallbackData.AUTO_REPLY_CONFIRM_RESET_PREFIX}"))
    app.add_handler(CallbackQueryHandler(auto_reply_cancel_callback, pattern=f"^{CallbackData.AUTO_REPLY_CANCEL_PREFIX}"))
    app.add_handler(CallbackQueryHandler(auto_reply_stats_callback, pattern=f"^{CallbackData.AUTO_REPLY_STATS_PREFIX}"))
    app.add_handler(CallbackQueryHandler(user_auto_reply_toggle_callback, pattern=f"^{CallbackData.USER_AUTO_REPLY_TOGGLE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(admin_auto_reply_callback, pattern=f"^{CallbackData.ADMIN_AUTO_REPLY}$"))
    app.add_handler(CallbackQueryHandler(admin_auto_reply_select_callback, pattern=f"^{CallbackData.ADMIN_AUTO_REPLY_SELECT_PREFIX}"))
    app.add_handler(CallbackQueryHandler(nsfw_settings_callback, pattern=f"^{CallbackData.NSFW_SETTINGS}$"))
    app.add_handler(CallbackQueryHandler(nsfw_toggle_callback, pattern=f"^{CallbackData.NSFW_TOGGLE}$"))
    app.add_handler(CallbackQueryHandler(nsfw_threshold_callback, pattern=f"^{CallbackData.NSFW_THRESHOLD_SET}$"))
    app.add_handler(CallbackQueryHandler(contests_menu_callback, pattern=f"^{CallbackData.CONTESTS_MENU}$"))
    app.add_handler(CallbackQueryHandler(contest_join_callback, pattern=f"^{CallbackData.CONTEST_JOIN_PREFIX}"))
    app.add_handler(CallbackQueryHandler(contest_winners_callback, pattern=f"^{CallbackData.CONTEST_WINNERS}$"))
    app.add_handler(CallbackQueryHandler(contests_back_callback, pattern=f"^{CallbackData.CONTESTS_BACK}$"))
    app.add_handler(CallbackQueryHandler(admin_create_contest_callback, pattern=f"^{CallbackData.ADMIN_CREATE_CONTEST}$"))
    app.add_handler(CallbackQueryHandler(admin_declare_winner_callback, pattern=f"^{CallbackData.ADMIN_DECLARE_WINNER}$"))
    app.add_handler(CallbackQueryHandler(security_links_callback, pattern=f"^{CallbackData.SECURITY_LINKS_PREFIX}"))
    app.add_handler(CallbackQueryHandler(security_mentions_callback, pattern=f"^{CallbackData.SECURITY_MENTIONS_PREFIX}"))
    app.add_handler(CallbackQueryHandler(security_warn_callback, pattern=f"^{CallbackData.SECURITY_WARN_PREFIX}"))
    app.add_handler(CallbackQueryHandler(security_slowmode_callback, pattern=f"^{CallbackData.SECURITY_SLOWMODE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(security_banned_words_menu_callback, pattern=f"^{CallbackData.SECURITY_BANNED_WORDS_MENU_PREFIX}"))
    app.add_handler(CallbackQueryHandler(security_welcome_callback, pattern=f"^{CallbackData.SECURITY_WELCOME_PREFIX}"))
    app.add_handler(CallbackQueryHandler(security_goodbye_callback, pattern=f"^{CallbackData.SECURITY_GOODBYE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(security_close_callback, pattern=f"^{CallbackData.SECURITY_CLOSE}$"))
    app.add_handler(CallbackQueryHandler(security_select_group_callback, pattern=f"^{CallbackData.SECURITY_SELECT_GROUP}"))
    app.add_handler(CallbackQueryHandler(security_refresh_groups_callback, pattern=f"^{CallbackData.SECURITY_REFRESH_GROUPS}$"))
    app.add_handler(CallbackQueryHandler(banned_words_add_callback, pattern=f"^{CallbackData.BANNED_WORDS_ADD_PREFIX}"))
    app.add_handler(CallbackQueryHandler(banned_words_list_callback, pattern=f"^{CallbackData.BANNED_WORDS_LIST_PREFIX}"))
    app.add_handler(CallbackQueryHandler(banned_words_remove_callback, pattern=f"^{CallbackData.BANNED_WORDS_REMOVE_PREFIX}"))
    app.add_handler(CallbackQueryHandler(penalty_menu_callback, pattern=f"^{CallbackData.PENALTY_MENU}:"))
    app.add_handler(CallbackQueryHandler(penalty_kick_callback, pattern=f"^{CallbackData.PENALTY_KICK}:"))
    app.add_handler(CallbackQueryHandler(penalty_ban_callback, pattern=f"^{CallbackData.PENALTY_BAN}:"))
    app.add_handler(CallbackQueryHandler(penalty_mute_callback, pattern=f"^{CallbackData.PENALTY_MUTE}:"))
    app.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_5}:"))
    app.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_30}:"))
    app.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_60}:"))
    app.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_720}:"))
    app.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_1440}:"))
    app.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_10080}:"))
    app.add_handler(CallbackQueryHandler(penalty_mute_duration_callback, pattern=f"^{CallbackData.GROUP_MUTE_DURATION_PERMANENT}:"))
    app.add_handler(CallbackQueryHandler(advanced_actions_callback, pattern=f"^{CallbackData.ADVANCED_ACTIONS}:"))
    app.add_handler(CallbackQueryHandler(group_action_ban_callback, pattern=f"^{CallbackData.GROUP_ACTION_BAN}:"))
    app.add_handler(CallbackQueryHandler(group_action_mute_callback, pattern=f"^{CallbackData.GROUP_ACTION_MUTE}:"))
    app.add_handler(CallbackQueryHandler(advanced_mute_duration_callback, pattern="^adv_mute_duration:"))
    app.add_handler(CallbackQueryHandler(group_action_warn_callback, pattern=f"^{CallbackData.GROUP_ACTION_WARN}:"))
    app.add_handler(CallbackQueryHandler(group_action_kick_callback, pattern=f"^{CallbackData.GROUP_ACTION_KICK}:"))
    app.add_handler(CallbackQueryHandler(group_action_restrict_callback, pattern=f"^{CallbackData.GROUP_ACTION_RESTRICT}:"))
    app.add_handler(CallbackQueryHandler(group_action_pin_callback, pattern=f"^{CallbackData.GROUP_ACTION_PIN}:"))
    app.add_handler(CallbackQueryHandler(group_action_log_callback, pattern=f"^{CallbackData.GROUP_ACTION_LOG}:"))
    app.add_handler(CallbackQueryHandler(group_action_unban_callback, pattern=f"^{CallbackData.GROUP_ACTION_UNBAN}:"))
    app.add_handler(CallbackQueryHandler(panel_lock_callback, pattern=f"^{CallbackData.PANEL_LOCK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(panel_unlock_callback, pattern=f"^{CallbackData.PANEL_UNLOCK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(panel_close_callback, pattern=f"^{CallbackData.PANEL_CLOSE}$"))
    app.add_handler(CallbackQueryHandler(check_subscribe_callback, pattern=f"^{CallbackData.CHECK_SUBSCRIBE}$"))
    app.add_handler(CallbackQueryHandler(publish_all_channels_callback, pattern=f"^{CallbackData.PUBLISH_ALL_CHANNELS}$"))
    app.add_handler(CallbackQueryHandler(channel_stats_callback, pattern=f"^{CallbackData.CHANNEL_STATS}:"))
    app.add_handler(CallbackQueryHandler(channel_growth_callback, pattern=f"^{CallbackData.CHANNEL_GROWTH}:"))
    app.add_handler(CallbackQueryHandler(channel_stats_refresh_callback, pattern=f"^{CallbackData.CHANNEL_STATS_REFRESH}:"))
    app.add_handler(CallbackQueryHandler(my_channel_stats_callback, pattern=f"^{CallbackData.MY_CHANNEL_STATS}$"))
    app.add_handler(CallbackQueryHandler(rules_show_callback, pattern=f"^{CallbackData.RULES_SHOW}"))
    app.add_handler(CallbackQueryHandler(reset_rules_confirm_callback, pattern=f"^{CallbackData.RULES_CONFIRM_RESET}"))
    app.add_handler(CallbackQueryHandler(reset_rules_cancel_callback, pattern=f"^{CallbackData.RULES_CANCEL_RESET}"))
    app.add_handler(CallbackQueryHandler(lang_callback, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(handle_text_callbacks, pattern="^(rank|top|schedule_post)$"))
    
    # معالجات الدفع
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))
    
    # معالجات المجموعات
    app.add_handler(ChatMemberHandler(track_chat_add, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_bot_added))
    
    # معالجات الرسائل
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    app.add_handler(MessageHandler(filters.CAPTION & filters.ChatType.GROUPS & ~filters.COMMAND, filter_messages_handler))
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler_main))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler_main))
    app.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE & ~filters.COMMAND, message_handler_main))
    
    # قائمة الأوامر
    commands = [
        BotCommand("start", "القائمة الرئيسية"),
        BotCommand("help", "المساعدة"),
        BotCommand("rules", "قوانين المجموعة"),
        BotCommand("set_rules", "تعيين قوانين (للمشرفين)"),
        BotCommand("reset_rules", "إعادة تعيين القوانين (للمشرفين)"),
        BotCommand("syncgroup", "تفعيل المجموعة"),
        BotCommand("security", "إعدادات الأمان"),
        BotCommand("trial", "تجربة مجانية"),
        BotCommand("subscribe", "الاشتراك"),
        BotCommand("developer", "المطور"),
        BotCommand("updates", "التحديثات"),
        BotCommand("language", "تغيير اللغة"),
        BotCommand("support", "الدعم"),
        BotCommand("panel", "لوحة التحكم"),
        BotCommand("schedule", "جدولة منشور"),
        BotCommand("lock", "قفل المجموعة"),
        BotCommand("unlock", "فتح المجموعة"),
        BotCommand("stats", "إحصائيات القناة"),
        BotCommand("contests", "المسابقات"),
        BotCommand("create_contest", "إنشاء مسابقة"),
        BotCommand("declare_winner", "إعلان فائز"),
        BotCommand("update_admins", "تحديث المشرفين"),
        BotCommand("register_hidden_owner", "تسجيل مالك مخفي"),
        BotCommand("add_hidden_admin", "إضافة مشرف مخفي"),
        BotCommand("remove_hidden_admin", "إزالة مشرف مخفي"),
        BotCommand("list_hidden_admins", "عرض المشرفين المخفيين"),
    ]
    await app.bot.set_my_commands(commands)
    
    # تشغيل المهام الخلفية
    asyncio.create_task(auto_publish_loop(app.bot))
    
    print(f"🚀 تم تشغيل {BOT_NAME} (الإصدار 19.3.1)")
    print("✅ جميع التصحيحات والتحسينات تم تطبيقها")
    print("✅ تم إضافة نظام قوانين المجموعة (/rules)")
    print("✅ تم إضافة نظام المشرفين المخفيين")
    
    try:
        await app.run_polling(drop_pending_updates=True, poll_interval=POLL_INTERVAL)
    except asyncio.CancelledError:
        print("🛑 تم إلغاء تشغيل البوت")
    except KeyboardInterrupt:
        print("🛑 تم إيقاف البوت بواسطة المستخدم")
    finally:
        await db_pool.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 تم إيقاف البوت")
    except Exception as e:
        print(f"❌ خطأ فادح: {e}")
        traceback.print_exc()
        sys.exit(1)
